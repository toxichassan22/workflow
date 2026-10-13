"""Plot shape from documented boundary lengths.

When a croquis records each side's length (97م واجهة، 250م عمق) but carries no
survey-coordinate table, the documented lengths still describe a real shape:
the north/south boundaries span the parcel width and the east/west boundaries
span its depth. This module recovers those lengths from every place they are
stored — the editable directions table, the extracted parcel directions, and
the «أطوال الأضلاع» summary text — and synthesizes a plain rectangle the
geometry consumers can clip setbacks against, render as the boundary stage,
and constrain building footprints with.

The rectangle is an approximation of the documented record, never a surveyed
boundary: callers keep it out of ``survey_coordinates``, and the capacity
report flags it via ``boundaryShape`` so nobody mistakes it for a survey.
"""

import json
import math
import re


_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_COMPASS_WORDS = {'north': r'شمال', 'south': r'جنوب', 'east': r'شرق', 'west': r'غرب'}
_AXIS_WORDS = {'front': r'أمامي|امامي|front', 'back': r'خلفي|rear|\bback\b',
               'side': r'جانب|side'}
_LENGTH_KEYS = ('boundary_length_m', 'boundary_length', 'boundaryLength', 'boundaryLengthM',
                'length_m', 'length', 'lengthMeters', 'edge_length_m', 'side_length_m',
                'boundary_m')
_LENGTH_TEXT_KEYS = ('regulation_text', 'regulation', 'description', 'text', 'notes',
                     'uses', 'boundary_text', 'boundary', 'summary')
_LENGTH_TEXT_FIELDS = ('boundary_lengths', 'boundary_dimensions')
# A strict «بطول Nم» mention inside a direction row — bare meter figures there
# are street widths and setbacks, so only the explicit length phrase counts.
_LENGTH_PHRASE_RE = re.compile(
    r'(?:بطول|طول(?:\s+(?:الحد|الضلع|الجهة|الجانب))?)\s*[:=\-–—]?\s*'
    r'([0-9٠-٩۰-۹]+(?:[.,٫][0-9]+)?)\s*(?:متر|أمتار|امتار|م\.?|meters?\b|m\b)',
    re.IGNORECASE)
_METER_RE = re.compile(
    r'([0-9٠-٩۰-۹]+(?:[.,٫][0-9]+)?)\s*(?:متر|أمتار|امتار|م\.?|meters?\b|m\b)',
    re.IGNORECASE)
# Synthesized rows sit in a local frame offset from zero so parsers that drop
# falsy/zero coordinates still keep every vertex.
SYNTHETIC_ORIGIN = 1000.0
SYNTHETIC_SOURCE = 'boundary_lengths'


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).translate(_DIGITS).replace(',', '')
                       .replace('٬', '').replace('٫', '.').strip())
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _decoded(value, default):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default
    return value if isinstance(value, (dict, list)) else default


def _compass(value):
    """Exactly one compass direction in a label, or nothing — ambiguous
    composites («شمال شرقي») stay unresolved rather than guessing."""
    candidate = str(value or '').translate(_DIGITS).strip().lower()
    if not candidate:
        return None
    matches = [key for key, word in _COMPASS_WORDS.items()
               if re.search(word, candidate)
               or re.search(r'\b' + key + r'(?:ern)?\b', candidate)]
    return matches[0] if len(matches) == 1 else None


def _direction_items(value):
    """Yield (compass, row) pairs from a directions table whether it is stored
    as a list of row dicts or as a {direction: cell} map."""
    rows = _decoded(value, [])
    if isinstance(rows, dict):
        rows = [dict(cell, direction=key) if isinstance(cell, dict)
                else {'direction': key, 'regulation_text': cell}
                for key, cell in rows.items()]
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        direction = _compass(row.get('direction') or row.get('label')
                             or row.get('name') or row.get('side') or row.get('key'))
        if direction:
            yield direction, row


def row_length(row):
    """A direction row's boundary length: the structured field first, then the
    strict «بطول Nم» phrase in its prose cells."""
    for key in _LENGTH_KEYS:
        value = number(row.get(key))
        if value is not None and value > 0:
            return value
    prose = ' '.join(str(row.get(key) or '') for key in _LENGTH_TEXT_KEYS)
    match = _LENGTH_PHRASE_RE.search(prose)
    return number(match.group(1)) if match else None


def _parcels(source):
    analysis = _decoded(source.get('land_documents_analysis'), {})
    parcels = analysis.get('parcels') if isinstance(analysis, dict) else []
    return [parcel for parcel in parcels if isinstance(parcel, dict)] \
        if isinstance(parcels, list) else []


def _clause_figures(clause):
    """Ordered (start, end, value) meter figures in a clause. When any strict
    «بطول Nم» phrase is present only those count — bare meter figures there are
    street widths and setbacks, not lengths."""
    phrases = [(m.start(1), m.end(1), number(m.group(1)))
               for m in _LENGTH_PHRASE_RE.finditer(clause)]
    pool = phrases or [(m.start(1), m.end(1), number(m.group(1)))
                       for m in _METER_RE.finditer(clause)]
    return sorted((s, e, v) for s, e, v in pool if v and v > 0)


def _word_figures(clause, words):
    """{key: length} — each direction/facade mention in the clause takes the
    first figure after it (before the next mention), else the last figure
    before it. «الشمالي 97م والجنوبي 98م» keeps 98 on the south instead of
    handing every mention the clause's first figure."""
    mentions = sorted((m.start(), m.end(), key)
                      for key, pattern in words.items()
                      for m in re.finditer(pattern, clause, re.IGNORECASE))
    figures = _clause_figures(clause)
    found = {}
    for index, (start, end, key) in enumerate(mentions):
        if key in found:
            continue
        nxt = mentions[index + 1][0] if index + 1 < len(mentions) else len(clause)
        after = [v for fs, fe, v in figures if end <= fs < nxt]
        if after:
            found[key] = after[0]
            continue
        prv = mentions[index - 1][1] if index else 0
        before = [v for fs, fe, v in figures if prv <= fe <= start]
        if before:
            found[key] = before[-1]
    return found


def _lengths_from_text(source):
    """Lengths from the «أطوال الأضلاع وحدود الأرض» summary field — clauses like
    «الشمالي 72م» or «شمال: 97م | جنوب: 97م». Figures in this field are lengths
    by definition, so each direction's clause figure counts."""
    found = {}
    for field in _LENGTH_TEXT_FIELDS:
        raw = source.get(field)
        if isinstance(raw, (dict, list)):
            for direction, row in _direction_items(raw):
                if direction not in found:
                    value = row_length(row)
                    if value is not None:
                        found[direction] = value
            continue
        for clause in re.split(r'[\n|؛;,،]+', str(raw or '')):
            if not clause.strip():
                continue
            for direction, value in _word_figures(clause, _COMPASS_WORDS).items():
                if direction not in found:
                    found[direction] = value
    return found


def direction_lengths(source):
    """Compass-keyed boundary lengths in meters from every documented location.

    Priority order — the user-editable directions table and summary field win
    over the stored extraction blob: a corrected value must never be overridden
    by the raw analysis it corrected."""
    source = source if isinstance(source, dict) else {}
    found = {}
    for table in (source.get('directions_table'), source.get('directions')):
        for direction, row in _direction_items(table):
            if direction not in found:
                value = row_length(row)
                if value is not None:
                    found[direction] = value
    for direction, value in _lengths_from_text(source).items():
        if direction not in found:
            found[direction] = value
    analysis = _decoded(source.get('land_documents_analysis'), {})
    parcels = _parcels(source)
    # Only the primary parcel fills gaps — lengths from different plots must
    # never merge into one fabricated shape.
    tables = [analysis.get('directions') if isinstance(analysis, dict) else None,
              parcels[0].get('directions') if parcels else None]
    for table in tables:
        for direction, row in _direction_items(table):
            if direction not in found:
                value = row_length(row)
                if value is not None:
                    found[direction] = value
    return {key: found.get(key) for key in _COMPASS_WORDS}


def _axis_lengths(source):
    """«واجهة/خلفية/جانب» phrasing for summaries that never name a compass —
    the front and back boundaries both span the parcel width, the side
    boundaries its depth."""
    found = {}
    for field in _LENGTH_TEXT_FIELDS:
        for clause in re.split(r'[\n|؛;,،]+', str(source.get(field) or '')):
            for axis, value in _word_figures(clause, _AXIS_WORDS).items():
                if axis not in found:
                    found[axis] = value
    return found


def _mean(values):
    present = [value for value in values if value is not None and value > 0]
    return sum(present) / len(present) if present else None


def dimension_rectangle(source):
    """The (width, depth) the documented lengths describe, in meters.

    Width is the mean of the recorded north/south boundaries — or of the
    «أمامي/خلفي» pair when only facade wording exists — and depth the mean of
    the east/west ones. Both axes need at least one figure; anything less is
    not a shape."""
    lengths = direction_lengths(source)
    width = _mean((lengths['north'], lengths['south']))
    depth = _mean((lengths['east'], lengths['west']))
    if width is None or depth is None:
        axes = _axis_lengths(source)
        if width is None:
            width = _mean((axes.get('front'), axes.get('back')))
        if depth is None:
            depth = axes.get('side')
    if not width or not depth:
        return None
    return width, depth


def dimension_points(source):
    """CCW rectangle in local meters — south edge first, matching the compass
    assignment the geometry helpers expect (x extent = north/south boundary
    length, y extent = east/west boundary length)."""
    rectangle = dimension_rectangle(source)
    if not rectangle:
        return []
    width, depth = rectangle
    return [(0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth)]


def dimension_survey_rows(source):
    """The same rectangle as survey-style rows so point/geometry consumers treat
    it exactly like a recorded boundary — including the 60-point cap, parcel
    grouping and polygon validation. ``source`` marks the rows as derived from
    documented lengths rather than a coordinate table."""
    return [{'point': str(index + 1), 'parcel_id': '',
             'eastings': x + SYNTHETIC_ORIGIN, 'northings': y + SYNTHETIC_ORIGIN,
             'source': SYNTHETIC_SOURCE}
            for index, (x, y) in enumerate(dimension_points(source))]
