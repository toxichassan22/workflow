import json
import math
import re


_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_DIRECTIONS = {'north': r'شمال|north', 'south': r'جنوب|south',
               'east': r'شرق|east', 'west': r'غرب|west'}
_OPPOSITE = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).translate(_DIGITS).replace(',', '').replace('٬', '')
                       .replace('٫', '.').strip())
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


def _cardinal(value):
    matches = [key for key, pattern in _DIRECTIONS.items()
               if re.search(pattern, str(value or ''), re.I)]
    return matches[0] if len(matches) == 1 else None


def _frontages(project):
    rows = _decoded(project.get('directions_table'), [])
    if isinstance(rows, dict):
        rows = [dict(value, direction=key) if isinstance(value, dict)
                else {'direction': key, 'description': value} for key, value in rows.items()]
    found = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        direction = _cardinal(row.get('direction') or row.get('name') or row.get('side'))
        description = ' '.join(str(row.get(key) or '') for key in
                               ('description', 'boundary', 'neighbor', 'type', 'kind', 'street_name', 'street'))
        if direction and (re.search(r'شارع|طريق|street|road', description, re.I)
                          or number(row.get('street_width') or row.get('streetWidth'))):
            found.add(direction)
    return found


def _setback_values(value):
    text = str(value or '').translate(_DIGITS).replace('٫', '.')
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    patterns = {
        'front': r'امامي(?:ة|ه)?|front', 'back': r'خلفي(?:ة|ه)?|rear|back',
        'side': r'جانبي(?:ة|ه|ان|ين)?|side',
        'north': r'شمالي(?:ة|ه)?|شمال|north', 'south': r'جنوبي(?:ة|ه)?|جنوب|south',
        'east': r'شرقي(?:ة|ه)?|شرق|east', 'west': r'غربي(?:ة|ه)?|غرب|west',
    }
    values = {}
    for key, label in patterns.items():
        matches = re.findall(r'(?:' + label + r')[^\d\n;،]{0,32}'
                             r'(\d+(?:\.\d+)?)\s*(?:متر|امتار|م\b|meters?\b|m\b)', text, re.I)
        amounts = {number(item) for item in matches}
        if len(amounts) > 1:
            return {}
        if amounts:
            values[key] = amounts.pop()
    return values


def _polygon_rows(project):
    for key in ('survey_coordinates', 'regulation_coordinates'):
        rows = _decoded(project.get(key), [])
        if isinstance(rows, list) and 3 <= len(rows) <= 200:
            return rows
    analysis = _decoded(project.get('land_documents_analysis'), {})
    parcels = analysis.get('parcels') if isinstance(analysis, dict) else []
    rows = [row for parcel in (parcels if isinstance(parcels, list) else [])
            if isinstance(parcel, dict)
            for row in (parcel.get('survey_coordinates') or [])]
    return rows if isinstance(rows, list) and 3 <= len(rows) <= 200 else []


def _polygon(project):
    rows = _polygon_rows(project)
    if not rows:
        return [], 'rows'
    points = []
    parcels = set()
    for row in rows:
        if not isinstance(row, dict):
            return [], 'coords'
        x = number(row.get('eastings', row.get('easting', row.get('x'))))
        y = number(row.get('northings', row.get('northing', row.get('y'))))
        if x is None or y is None or x < 1000 or y < 1000:
            return [], 'coords'
        parcels.add(str(row.get('parcel_id') or row.get('parcelId') or ''))
        if not points or points[-1] != (x, y):
            points.append((x, y))
    if len(parcels) > 1:
        return [], 'parcels'
    if points and points[0] == points[-1]:
        points.pop()
    if len(points) < 3 or len(set(points)) != len(points):
        return [], 'points'
    origin = points[0]
    return [(x - origin[0], y - origin[1]) for x, y in points], None


def _signed_area(points):
    return sum(a[0] * b[1] - b[0] * a[1]
               for a, b in zip(points, points[1:] + points[:1])) / 2


def _clip(points, origin, normal, setback):
    output = []
    previous = points[-1]
    distance = lambda point: ((point[0] - origin[0]) * normal[0]
                              + (point[1] - origin[1]) * normal[1] - setback)
    prior = distance(previous)
    for point in points:
        current = distance(point)
        if (current >= -1e-8) != (prior >= -1e-8):
            ratio = prior / (prior - current)
            output.append((previous[0] + ratio * (point[0] - previous[0]),
                           previous[1] + ratio * (point[1] - previous[1])))
        if current >= -1e-8:
            output.append(point)
        previous, prior = point, current
    return output


def setback_envelope(project):
    points, polygon_issue = _polygon(project)
    if not points:
        return None, {'code': polygon_issue or 'polygon'}
    values = _setback_values(project.get('setbacks'))
    if not values:
        return None, {'code': 'setbacks'}
    signed = _signed_area(points)
    cadastral = number(project.get('croquis_land_area'))
    if not cadastral:
        return None, {'code': 'cadastral'}
    if abs(abs(signed) - cadastral) > max(5, cadastral * 0.03):
        return None, {'code': 'mismatch', 'polygonArea': round(abs(signed), 1),
                      'cadastralArea': cadastral}
    if signed < 0:
        points.reverse()
    triples = zip(points, points[1:] + points[:1], points[2:] + points[:2])
    if any((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) < -1e-8
           for a, b, c in triples):
        return None, {'code': 'concave'}
    fronts = _frontages(project)
    common = set(values.values())
    uniform = len(common) == 1 and ({'front', 'back', 'side'}.issubset(values)
                                   or set(_DIRECTIONS).issubset(values))
    clipped = list(points)
    for a, b in zip(points, points[1:] + points[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length <= 1e-8:
            return None, {'code': 'degenerate'}
        normal = (-dy / length, dx / length)
        direction = ('east' if dy > 0 else 'west') if abs(dy) > abs(dx) else ('south' if dx > 0 else 'north')
        setback = values.get(direction)
        if setback is None and uniform:
            setback = next(iter(common))
        if setback is None and direction in fronts:
            setback = values.get('front')
        if setback is None and len(fronts) == 1 and direction == _OPPOSITE[next(iter(fronts))]:
            setback = values.get('back')
        if setback is None and fronts and direction not in fronts:
            setback = values.get('side')
            if len(fronts) > 1 and values.get('back') != setback:
                return None, {'code': 'frontages'}
        if setback is None:
            return None, {'code': 'unresolved'}
        clipped = _clip(clipped, a, normal, setback)
        if len(clipped) < 3:
            return 0.0, None
    return abs(_signed_area(clipped)), None
