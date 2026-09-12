"""Designer-only, unabridged context snapshots; never use generation fact filters.

Both public builders return immutable JSON strings and leave their inputs untouched.
Only explicit root bookkeeping and binary image payloads are omitted. Structured JSON
strings are decoded, but scalar strings (identifiers, dates, numbers) retain their
spelling and type. Unsupported/cyclic input fails explicitly instead of returning a
partial context. The caller owns whole-prompt token budgeting and must not slice these
snapshots or store them inside project_data/slides.
"""

import hashlib
import importlib
import json
import math
import re
from collections.abc import Mapping


# These are stored previous output, not project facts. Apply ONLY at project root.
PROJECT_BOOKKEEPING_KEYS = frozenset({
    'tenantSlidesData', 'slides', 'pageDrafts', 'designerChat',
})
# Explicit transport slots, not a prefix rule: unknown underscore fields are facts.
# Keep snapshots in local variables, but exclude these slots if a caller attached one.
RUNTIME_CONTEXT_KEYS = frozenset({
    '_designer_project_context', '_designer_deck_context',
})
SLIDE_RUNTIME_KEYS = RUNTIME_CONTEXT_KEYS | {'_designer_keep_html'}

_IMAGE_DATA_RE = re.compile(
    r'data:(?P<media_type>image/[a-z0-9.+-]+)'
    r'(?:;[a-z0-9!#$&^_.+-]+=[^;,\s\"\'<>]*)*;base64,'
    r'(?P<payload>[a-z0-9+/_=-]*)', re.IGNORECASE,
)


class DesignerContextError(ValueError):
    """The full designer snapshot could not be built; do not send partial facts."""


def _path(parent, key):
    if not isinstance(key, str):
        raise DesignerContextError(f'Non-string JSON key at {parent}')
    return (f'{parent}.{key}' if key.isidentifier()
            else f'{parent}[{json.dumps(key, ensure_ascii=False)}]')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _decode_structure(value):
    """Decode containers, including double-encoded ones, never coerce scalar text."""
    candidate = value
    while isinstance(candidate, str) and candidate.lstrip().startswith(('{', '[', '"')):
        try:
            candidate = json.loads(candidate, object_pairs_hook=_unique_object)
        except (ValueError, TypeError):
            return value
        if isinstance(candidate, (dict, list)):
            return candidate
    return value


def _image_reference(match, path):
    payload = match.group('payload')
    return {
        'path': path,
        'kind': 'inline image',
        'media_type': match.group('media_type'),
        'encoding': 'base64',
        'encoded_length': len(payload),
        'sha256': hashlib.sha256(match.group(0).encode('utf-8')).hexdigest(),
        'payload': 'omitted; original asset remains at this path',
    }


def _image_text(value, path):
    whole = _IMAGE_DATA_RE.fullmatch(value)
    if whole:
        return {'asset_reference': _image_reference(whole, path)}
    occurrence = 0

    def replace(match):
        nonlocal occurrence
        occurrence += 1
        reference = _image_reference(match, f'{path}#inline-image[{occurrence}]')
        return '[asset reference: ' + json.dumps(reference, ensure_ascii=False,
                                               separators=(',', ':')) + ']'

    # Do not parse/minify HTML or CSS. Only replace the embedded image payload.
    return _IMAGE_DATA_RE.sub(replace, value)


def _snapshot(value, path, *, decode_json=True, omit_keys=frozenset(), ancestors=None):
    if ancestors is None:
        ancestors = set()
    if isinstance(value, str):
        decoded = _decode_structure(value) if decode_json else value
        if not isinstance(decoded, str):
            return _snapshot(decoded, path, decode_json=decode_json,
                             omit_keys=omit_keys, ancestors=ancestors)
        return _image_text(value, path)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {'asset_reference': {
            'path': path, 'kind': 'binary', 'byte_length': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
            'payload': 'omitted; original asset remains at this path',
        }}
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DesignerContextError(f'Non-finite JSON number at {path}')
        return value
    if isinstance(value, (Mapping, list, tuple)):
        identity = id(value)
        if identity in ancestors:
            raise DesignerContextError(f'Cyclic input at {path}')
        ancestors.add(identity)
        try:
            if isinstance(value, Mapping):
                return {
                    key: _snapshot(item, _path(path, key), decode_json=decode_json,
                                   ancestors=ancestors)
                    for key, item in value.items() if key not in omit_keys
                }
            return [_snapshot(item, f'{path}[{index}]', decode_json=decode_json,
                              ancestors=ancestors)
                    for index, item in enumerate(value)]
        finally:
            ancestors.remove(identity)
    raise DesignerContextError(f'Unsupported {type(value).__name__} at {path}')


def _field_labels(database, tenant_id, source):
    """Optional labels supplement raw keys; never dump tenant settings/field rows."""
    labels = {}
    if not isinstance(source, Mapping):
        return labels
    for field in getattr(database, 'PREBUILT_FIELDS', ()):
        if isinstance(field, Mapping) and field.get('key') in source:
            if isinstance(field.get('label'), str):
                labels[field['key']] = field['label']
    try:
        fields = database.get_fields(tenant_id, active_only=False)
        for field in fields:
            if isinstance(field, Mapping):
                key = field.get('key') or field.get('field_key')
                label = field.get('label') or field.get('field_label')
                if key in source and isinstance(label, str):
                    labels[key] = label
    except Exception:
        # A label lookup must not erase otherwise available facts or expose DB errors.
        pass
    return labels


def _selected_team(source, database, tenant_id):
    selection = source.get('team_selection') if isinstance(source, Mapping) else None
    selection = selection if isinstance(selection, Mapping) else {}
    excluded = selection.get('excluded')
    excluded = {str(item) for item in excluded} if isinstance(excluded, list) else set()
    roles = selection.get('roles')
    roles = roles if isinstance(roles, Mapping) else {}
    selected = []
    if database is not None:
        try:
            library = database.get_team_entities(tenant_id)
        except Exception as exc:
            raise DesignerContextError('Selected team library lookup failed') from exc
        if not isinstance(library, (list, tuple)):
            raise DesignerContextError('Selected team library must be a list')
        for entity in library:
            if not isinstance(entity, Mapping):
                raise DesignerContextError('Selected team entity must be an object')
            entity_id = str(entity.get('id'))
            if entity_id in excluded:
                continue
            entry = dict(entity)
            # Presence matters: an explicitly blank/null role overrides the library too.
            if entity_id in roles:
                entry['role'] = roles[entity_id]
            selected.append(entry)
    local = selection.get('local')
    if isinstance(local, list):
        selected.extend(local)
    return selected


def build_project_context(project_data, creative_images=None, tenant_id=None):
    """Return full factual JSON, selected team entities and optional field labels.

    Accepts a project object (or its stored JSON string). creative_images stays a
    separate namespace, so it cannot overwrite project fields. Only the supplied
    tenant's team library and labels are read, never drafts, users or other DB data.
    Without tenant_id local team entries still resolve, with no database import.
    """
    source = _snapshot(project_data, '$.project_data',
                       omit_keys=PROJECT_BOOKKEEPING_KEYS | RUNTIME_CONTEXT_KEYS)
    database = None
    if tenant_id is not None:
        try:
            database = importlib.import_module('db')
        except Exception as exc:
            raise DesignerContextError('Team database module is unavailable') from exc
    team = _selected_team(source, database, tenant_id)
    labels = _field_labels(database, tenant_id, source) if database is not None else {}
    context = {
        'project_data': source,
        'creative_images': _snapshot(creative_images, '$.creative_images',
                                     omit_keys=RUNTIME_CONTEXT_KEYS),
        'selected_team_entities': _snapshot(team, '$.selected_team_entities'),
        'field_labels': _snapshot(labels, '$.field_labels', decode_json=False),
    }
    return json.dumps(context, ensure_ascii=False, indent=2, allow_nan=False)


def build_deck_context(slides):
    """Return every current slide, numbered from one, as an immutable compact JSON.

    HTML is preserved verbatim (including CSS, comments, scripts and whitespace),
    except inline base64 images become descriptive path-bearing asset references.
    Unlike project bookkeeping filtering, no slide or nested ``slides`` key is lost.
    Both slide objects and raw HTML strings are accepted, including empty entries.
    """
    if not isinstance(slides, (list, tuple)):
        raise DesignerContextError('Current slides must be a list')
    entries = [
        {'slide_number': index + 1,
         'slide': _snapshot(slide, f'$.slides[{index}].slide', decode_json=False,
                            omit_keys=SLIDE_RUNTIME_KEYS)}
        for index, slide in enumerate(slides)
    ]
    return json.dumps({'slides': entries}, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)
