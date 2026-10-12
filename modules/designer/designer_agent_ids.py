"""Stable per-slide identities for the designer agent.

Positions shuffle on every structural edit, so every slide carries an ``id``
(``s_`` + 8 hex chars) generated once and preserved for the slide's lifetime.
The planner selects slides by id; the runner resolves ids to positions only
when it needs the deck order, so a renumber between turns never mis-targets.
"""

import hashlib
import json
import re
import secrets

_SLIDE_ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{2,63}')


def new_slide_id():
    return 's_' + secrets.token_hex(4)


def _valid_id(value):
    return isinstance(value, str) and bool(_SLIDE_ID_RE.fullmatch(value))


def ensure_slide_ids(slides):
    """Give every slide a stable unique id, in place and idempotent.

    Existing valid ids are kept; the first occurrence of a duplicated id wins
    and later copies receive fresh ids, so a duplicated slide never shares an
    identity with its source.
    """
    if not isinstance(slides, list):
        return slides
    seen = set()
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        sid = slide.get('id')
        if not _valid_id(sid) or sid in seen:
            sid = new_slide_id()
            while sid in seen:
                sid = new_slide_id()
            slide['id'] = sid
        seen.add(sid)
    return slides


def index_by_id(slides):
    """Map ``id`` -> current 0-based position (first occurrence wins)."""
    out = {}
    for index, slide in enumerate(slides if isinstance(slides, list) else []):
        if isinstance(slide, dict) and _valid_id(slide.get('id')):
            out.setdefault(slide['id'], index)
    return out


def deck_signature(slides):
    """Fingerprint of the ordered deck: id + title + content hash per slide.

    Stored next to a pending plan so the runner can prove the deck it was
    planned against is the deck it is about to mutate.
    """
    rows = []
    for slide in slides if isinstance(slides, list) else []:
        slide = slide if isinstance(slide, dict) else {}
        html = str(slide.get('html') or '')
        rows.append({
            'id': slide.get('id') or '',
            'title': str(slide.get('title') or ''),
            'h': hashlib.sha1(html.encode('utf-8')).hexdigest()[:12],
        })
    return hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True).encode('utf-8')
    ).hexdigest()[:24]


def slide_signature(slide):
    """Fingerprint of one slide's mutable content.

    Same fields as the per-slide row in :func:`deck_signature` so a pending
    plan can guard only the slides its tasks touch — an edit anywhere else in
    the deck is none of the plan's business.
    """
    slide = slide if isinstance(slide, dict) else {}
    html = str(slide.get('html') or '')
    payload = {
        'title': str(slide.get('title') or ''),
        'h': hashlib.sha1(html.encode('utf-8')).hexdigest()[:12],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    ).hexdigest()[:24]


def slide_signatures(slides, ids=None):
    """``{slide_id: slide_signature}`` for the given ids (all keyed slides by
    default). Missing or unkeyed slides are simply absent from the map."""
    wanted = {str(sid) for sid in ids} if ids is not None else None
    out = {}
    for slide in slides if isinstance(slides, list) else []:
        if not isinstance(slide, dict) or not _valid_id(slide.get('id')):
            continue
        sid = str(slide['id'])
        if wanted is not None and sid not in wanted:
            continue
        out[sid] = slide_signature(slide)
    return out
