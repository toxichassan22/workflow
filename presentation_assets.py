"""Freeze presentation media without network, database, or application imports.

``freeze_presentation_assets(value, tenant_id, *, root=None,
allowed_origin=None, authorized_paths=None)`` returns a new JSON-compatible value.
Strings may contain HTML, inline CSS, URLs, or serialized JSON. Remote and data
URLs are preserved (remote content is NOT snapshotted). Local missing, private,
unsafe, or unsupported media raises ``PresentationAssetError``; callers must not
save the original mutable value after such a failure.

The default root is this module's directory, alongside app.py. ``allowed_origin``
is an explicit HTTP(S) origin; otherwise an active Flask request supplies its
origin. Without either, absolute URLs remain remote. No forwarded-host headers
are interpreted here.

Default sources are this tenant's creative images, logo/watermark files and
fonts, tenant font routes, and media in public ``assets/``. Raw project-documents
and dynamic API URLs are NOT public sources. ``authorized_paths`` may be an
iterable of exact tenant-authorized flat map URLs, or a mapping of URL to local
Path for aliases already resolved/authorized by the application (branding,
project image, or map). Mappings still cannot escape public media or the owning
tenant's directories. The caller must obtain these grants from trusted records,
never from the presentation payload. Truncated map filename tenant prefixes are
not authorization. Logo/watermark aliases require explicit mappings, not a guess
based on whichever file was modified last.

Snapshots are retained at /uploads/creative/<tenant>/revisions/<sha256>.<ext>.
The serving application must allow that precise nested path. Writes publish a
complete temporary file atomically without replacing an existing revision, and
existing revisions are hash-checked. This module never deletes a revision.
"""

from collections.abc import Mapping
import hashlib
import html
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent
_MEDIA_EXTENSIONS = frozenset({
    '.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif', '.bmp', '.ico', '.svg',
    '.ttf', '.otf', '.woff', '.woff2',
})
_TENANT_RE = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_REVISION_RE = re.compile(r'([a-f0-9]{64})(\.[a-z0-9]+)\Z')
# Consume whole remote URLs as well, so /uploads/... in a remote URL is never
# mistaken for a local substring. Delimiters cover HTML, CSS and srcset syntax.
_URL_RE = re.compile(
    r'''(?<![\w/\\%])(?:https?://|//|file://|blob:|(?:\./)?/?(?:uploads|tenant-assets|assets)/|/?api/(?:project-files/|map-images/|branding/font\.css))(?:&(?:[A-Za-z]+|\#[0-9]+|\#x[0-9a-fA-F]+);|[^\s<>"'`(){}\[\],;])*''',
    re.IGNORECASE,
)
_LOCAL_ROOTS = ('uploads', 'tenant-assets', 'assets')
_HTML_URL_RE = re.compile(
    r'''(?P<prefix>\b(?:src|href|poster|data-src)\s*=\s*)(?P<quote>["'])(?P<url>.*?)(?P=quote)''',
    re.IGNORECASE | re.DOTALL,
)
_CSS_URL_RE = re.compile(
    r'''(?P<prefix>\burl\(\s*)(?P<quote>["']?)(?P<url>.*?)(?P=quote)(?P<suffix>\s*\))''',
    re.IGNORECASE | re.DOTALL,
)


class PresentationAssetError(ValueError):
    """A required local presentation asset could not be frozen safely."""

    def __init__(self, reason, url=''):
        self.reason = reason
        # Query strings may carry credentials; never include them in diagnostics.
        self.url = str(url).split('?', 1)[0].split('#', 1)[0]
        super().__init__(f'Presentation asset {reason}' + (f': {self.url}' if self.url else ''))


def _origin(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        return (parsed.scheme.lower(), parsed.hostname.lower(),
                parsed.port or (443 if parsed.scheme.lower() == 'https' else 80))
    except ValueError:
        return None


def _request_origin():
    # Flask is optional for standalone tools/tests. Never import app or db.
    try:
        from flask import has_request_context, request
        return _origin(request.host_url) if has_request_context() else None
    except ImportError:
        return None


def _decoded_path(path, original):
    """Decode before validating, including repeatedly encoded traversal."""
    for _ in range(8):
        try:
            decoded = unquote(path, errors='strict')
        except UnicodeError as exc:
            raise PresentationAssetError('has invalid URL encoding', original) from exc
        if decoded == path:
            break
        path = decoded
    else:
        raise PresentationAssetError('has excessive URL encoding', original)
    if '%' in path:
        # Reject ambiguous leftover escapes rather than guessing browser decoding.
        raise PresentationAssetError('has invalid URL encoding', original)
    if any(ord(char) < 32 or ord(char) == 127 for char in path) or '\\' in path:
        raise PresentationAssetError('contains an unsafe path', original)
    path = path.removeprefix('./')
    pieces = path.removeprefix('/').split('/')
    if any(not piece or piece in ('.', '..') or piece.startswith('.')
           or ':' in piece or piece.endswith((' ', '.')) for piece in pieces):
        raise PresentationAssetError('contains an unsafe path', original)
    return '/' + '/'.join(pieces)


class _Freezer:
    def __init__(self, tenant_id, root, allowed_origin, authorized_paths):
        tenant = str(tenant_id) if tenant_id is not None else ''
        if not _TENANT_RE.fullmatch(tenant):
            raise PresentationAssetError('has an invalid tenant identifier')
        self.tenant = tenant
        self.root = Path(os.path.abspath(root if root is not None else ROOT))
        self.origin = _origin(allowed_origin) if allowed_origin else _request_origin()
        if allowed_origin and not self.origin:
            raise PresentationAssetError('has an invalid allowed origin')
        self.authorized = {}
        if authorized_paths is not None:
            if isinstance(authorized_paths, (str, bytes)):
                raise PresentationAssetError('authorization must be a mapping or iterable of URLs')
            entries = (authorized_paths.items() if isinstance(authorized_paths, Mapping)
                       else ((url, None) for url in authorized_paths))
            for url, path in entries:
                local = self.local_url(str(url))
                if local is None:
                    raise PresentationAssetError('authorization requires a local URL', url)
                canonical, _ = local
                if path is None:
                    if not self.is_flat_map(canonical):
                        raise PresentationAssetError('iterable authorization only permits flat map URLs', url)
                    path = canonical.lstrip('/')
                target = Path(path)
                if not target.is_absolute():
                    target = self.root / target
                self.authorized[canonical] = target
        self.cache = {}

    def local_url(self, url):
        value = html.unescape(url)
        if value.lower().startswith(('file:', 'blob:')):
            raise PresentationAssetError('uses an unsupported non-durable URL', url)
        try:
            parsed = urlsplit(value)
        except ValueError as exc:
            raise PresentationAssetError('has an invalid URL', url) from exc
        if parsed.scheme or parsed.netloc:
            absolute = value
            if not parsed.scheme and parsed.netloc:
                if not self.origin:
                    return None
                absolute = self.origin[0] + ':' + value
            if not self.origin or _origin(absolute) != self.origin:
                return None
        raw = parsed.path.removeprefix('./').lstrip('/')
        # Decode for classification too: encoded root names must not bypass checks.
        classified_path = raw
        for _ in range(8):
            decoded = unquote(classified_path)
            if decoded == classified_path:
                break
            classified_path = decoded
        classification = classified_path.lstrip('/')
        while classification.startswith(('./', '../')):
            classification = classification.split('/', 1)[1]
        classified = classification.split('/', 1)[0].lower()
        if classified not in _LOCAL_ROOTS and not classification.lower().startswith(
                ('api/project-files/', 'api/map-images/', 'api/branding/font.css')):
            return None
        canonical = _decoded_path(parsed.path, url)
        return canonical, parsed.fragment

    def is_flat_map(self, url):
        return url.startswith('/uploads/maps/') and len(url.split('/')) == 4

    def checked_path(self, path, url, *, allow_missing=False):
        """Reject symlinks/junctions at every component, not just path escapes."""
        path = Path(os.path.abspath(path))
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise PresentationAssetError('is outside the asset root', url) from exc
        # Include root's ancestors: a symlinked uploads root is not an exception.
        for component in (*reversed(path.parents), path):
            try:
                info = component.lstat()
            except FileNotFoundError:
                if allow_missing:
                    continue
                raise PresentationAssetError('is missing', url) from None
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, 'st_file_attributes', 0) & 0x400):
                raise PresentationAssetError('uses a symlink or reparse point', url)
        return path

    def authorized_source(self, url):
        pieces = url.lstrip('/').split('/')
        if pieces[0] == 'tenant-assets':
            if len(pieces) < 3 or pieces[1] != self.tenant:
                raise PresentationAssetError('belongs to another tenant', url)
        elif pieces[0] == 'uploads':
            if len(pieces) < 3:
                raise PresentationAssetError('is not an authorized media path', url)
            owner = pieces[2] if pieces[1] == 'creative' and len(pieces) > 2 else pieces[1]
            if pieces[1] != 'maps' and owner != self.tenant:
                raise PresentationAssetError('belongs to another tenant', url)

        if url in self.authorized:
            path = self.authorized[url]
            return self.check_source_scope(path, url, explicit=True)
        if pieces[0] == 'assets':
            path = self.root.joinpath(*pieces)
        elif pieces[:3] == ['uploads', 'creative', self.tenant]:
            if len(pieces) != 4 and not (len(pieces) == 5 and pieces[3] == 'revisions'):
                raise PresentationAssetError('is not an authorized creative path', url)
            path = self.root.joinpath(*pieces)
        elif pieces[:3] == ['tenant-assets', self.tenant, 'fonts'] and len(pieces) == 4:
            path = self.root / 'uploads' / self.tenant / 'fonts' / pieces[3]
        elif pieces[:2] == ['uploads', self.tenant] and pieces[1] not in ('maps', 'creative') and (
                len(pieces) == 3 and Path(pieces[-1]).stem in ('logo', 'watermark')
                or len(pieces) == 4 and pieces[2] == 'fonts'):
            path = self.root.joinpath(*pieces)
        else:
            raise PresentationAssetError('requires explicit tenant authorization', url)
        return self.check_source_scope(path, url, explicit=False)

    def check_source_scope(self, path, url, *, explicit):
        path = self.checked_path(path, url)
        relative = path.relative_to(self.root).parts
        if any(part.startswith('.') or ':' in part or part.endswith((' ', '.')) for part in relative):
            raise PresentationAssetError('source contains an unsafe path', url)
        public = len(relative) >= 2 and relative[0] == 'assets'
        creative = (len(relative) >= 4 and relative[:3] == ('uploads', 'creative', self.tenant))
        owned = len(relative) >= 3 and relative[:2] == ('uploads', self.tenant)
        mapped = explicit and len(relative) == 3 and relative[:2] == ('uploads', 'maps')
        if not (public or creative or owned or mapped):
            raise PresentationAssetError('source is outside the authorized tenant media directories', url)
        if path.suffix.lower() not in _MEDIA_EXTENSIONS:
            raise PresentationAssetError('has an unsupported media type', url)
        return path

    def read_source(self, path, url):
        path = self.checked_path(path, url)
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise PresentationAssetError('is not a regular file', url)
            flags = (os.O_RDONLY | getattr(os, 'O_BINARY', 0)
                     | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, 'rb') as source:
                before = os.fstat(source.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise PresentationAssetError('is not a regular file', url)
                data = source.read()
                after = os.fstat(source.fileno())
            self.checked_path(path, url)
            current = path.stat()
            identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
            if identity(before) != identity(after) or identity(after) != identity(current):
                raise PresentationAssetError('changed while being snapshotted; retry the save', url)
            return data
        except OSError as exc:
            raise PresentationAssetError('could not be read', url) from exc

    def publish(self, data, suffix, url):
        digest = hashlib.sha256(data).hexdigest()
        relative = f'uploads/creative/{self.tenant}/revisions/{digest}{suffix}'
        target = self.root / relative
        self.checked_path(target, url, allow_missing=True)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self.checked_path(target.parent, url)
            if target.exists():
                if self.read_source(target, url) != data:
                    raise PresentationAssetError('revision content does not match its hash', url)
                return '/' + relative
            descriptor, temporary = tempfile.mkstemp(prefix='.snapshot-', dir=target.parent)
            try:
                with os.fdopen(descriptor, 'wb') as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                self.checked_path(target, url, allow_missing=True)
                # Linking publishes atomically and cannot overwrite another writer.
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    if self.read_source(target, url) != data:
                        raise PresentationAssetError('revision content does not match its hash', url)
            finally:
                os.unlink(temporary)
            return '/' + relative
        except OSError as exc:
            raise PresentationAssetError('could not be stored atomically', url) from exc

    def freeze_url(self, url):
        local = self.local_url(url)
        if local is None:
            return url
        canonical, fragment = local
        if canonical not in self.cache:
            source = self.authorized_source(canonical)
            data = self.read_source(source, canonical)
            revision_prefix = f'/uploads/creative/{self.tenant}/revisions/'
            if canonical.startswith(revision_prefix):
                match = _REVISION_RE.fullmatch(canonical[len(revision_prefix):])
                if not match or hashlib.sha256(data).hexdigest() != match[1]:
                    raise PresentationAssetError('revision content does not match its hash', canonical)
                frozen = canonical
            else:
                frozen = self.publish(data, source.suffix.lower(), canonical)
            self.cache[canonical] = frozen
        # A fragment can select an SVG view/font face; queries only bust old caches.
        return self.cache[canonical] + ('#' + fragment if fragment else '')

    def walk(self, value):
        if isinstance(value, dict):
            return {key: self.walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.walk(item) for item in value]
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped.startswith(('{', '[')):
            try:
                decoded = json.loads(value)
            except (ValueError, RecursionError):
                pass
            else:
                frozen = self.walk(decoded)
                return value if frozen == decoded else json.dumps(frozen, ensure_ascii=False)
        # A whole URL can include an encoded root or legal punctuation that the
        # conservative HTML/CSS token scanner treats as a delimiter.
        if stripped and not any(char.isspace() for char in stripped) and not any(
                char in stripped for char in '<>"\'`'):
            frozen = self.freeze_url(stripped)
            if frozen != stripped:
                return value.replace(stripped, frozen, 1)
        def replace_attribute(match):
            original = match['url']
            frozen = self.freeze_url(original)
            if frozen == original:
                return match[0]
            return match['prefix'] + match['quote'] + frozen + match['quote']

        def replace_css(match):
            original = match['url'].strip()
            # CSS escapes can hide URL path components; decode before applying
            # the same authorization and traversal validation as plain URLs.
            decoded = re.sub(
                r'\\(?:([0-9a-fA-F]{1,6})[ \t\r\n\f]?|([^\r\n\f]))',
                lambda escaped: chr(int(escaped[1], 16) or 0xfffd) if escaped[1]
                and int(escaped[1], 16) <= 0x10ffff else escaped[2] or '\ufffd',
                original,
            )
            frozen = self.freeze_url(decoded)
            if frozen == decoded:
                return match[0]
            return match['prefix'] + match['quote'] + frozen + match['quote'] + match['suffix']

        value = _HTML_URL_RE.sub(replace_attribute, value)
        value = _CSS_URL_RE.sub(replace_css, value)
        return _URL_RE.sub(lambda match: self.freeze_url(match[0]), value)


def freeze_presentation_assets(value, tenant_id, *, root=None, allowed_origin=None,
                               authorized_paths=None):
    """Return immutable tenant media references; fail closed for local errors.

    ``authorized_paths`` is trusted application input, not part of ``value``.
    Root must contain the application's uploads/ and assets/ directories. Input
    containers are never mutated. Failure may leave already-created immutable
    revisions, but never a partially rewritten return value or partial file.
    """
    return _Freezer(tenant_id, root, allowed_origin, authorized_paths).walk(value)
