import json
import math


EPSILON = 1e-7
DIRECTION_VECTORS = {'east': (1, 0), 'north': (0, 1), 'west': (-1, 0), 'south': (0, -1)}


class PlanGeometryError(ValueError):
    def __init__(self, message, code='PLANS_GEOMETRY_INVALID'):
        super().__init__(message)
        self.code = code


def finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩٬', '0123456789,')).strip().replace(',', '')
        if not value:
            return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def read_points(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            value = []
    if isinstance(value, dict):
        value = value.get('points') or value.get('survey_coordinates') or value.get('coordinates') or []
    if not isinstance(value, list) or not 3 <= len(value) <= 60:
        raise PlanGeometryError('إحداثيات حدود الأرض غير مكتملة.')
    points = []
    for index, raw in enumerate(value):
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            raw = {'eastings': raw[0], 'northings': raw[1]}
        if not isinstance(raw, dict):
            raise PlanGeometryError('إحدى نقاط حدود الأرض غير صالحة.')
        east = finite_number(next((raw[key] for key in ('eastings', 'easting', 'x') if key in raw), None))
        north = finite_number(next((raw[key] for key in ('northings', 'northing', 'y') if key in raw), None))
        if east is None or north is None:
            raise PlanGeometryError('إحداثيات إحدى نقاط حدود الأرض ناقصة أو غير صالحة.')
        points.append({'point': str(raw.get('point') or raw.get('point_number') or index + 1),
                       'parcel_id': str(raw.get('parcel_id') or raw.get('parcelId') or ''),
                       'eastings': east, 'northings': north})
    return points


def signed_area(polygon):
    if len(polygon) < 3:
        return 0.0
    x0, y0 = polygon[0]
    local = [(x - x0, y - y0) for x, y in polygon]
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in segments(local)) / 2


def segments(polygon):
    return zip(polygon, polygon[1:] + polygon[:1])


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def proper_intersection(a, b, c, d):
    ab_c, ab_d, cd_a, cd_b = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
    return ab_c * ab_d < -EPSILON and cd_a * cd_b < -EPSILON


def point_segment_distance(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length)) if length else 0
    return math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy)


def segment_distance(a, b, c, d):
    if proper_intersection(a, b, c, d):
        return 0.0
    return min(point_segment_distance(a, c, d), point_segment_distance(b, c, d),
               point_segment_distance(c, a, b), point_segment_distance(d, a, b))


def point_inside(point, polygon, boundary=True):
    if any(point_segment_distance(point, a, b) <= EPSILON for a, b in segments(polygon)):
        return boundary
    inside = False
    for a, b in segments(polygon):
        if (a[1] > point[1]) != (b[1] > point[1]):
            x = a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if point[0] < x:
                inside = not inside
    return inside


def validate_polygon(raw, limit=60):
    # Closed GeoJSON rings repeat their first point at the end. Permit that
    # one bookkeeping vertex without relaxing the actual polygon limit.
    if not isinstance(raw, list) or not 3 <= len(raw) <= limit + 1:
        raise PlanGeometryError('عدد رؤوس المضلع غير صالح.')
    polygon = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise PlanGeometryError('صيغة إحدى نقاط المضلع غير صالحة.')
        parsed = [finite_number(value) for value in point]
        if any(value is None for value in parsed):
            raise PlanGeometryError('قيم إحدى نقاط المضلع غير صالحة.')
        polygon.append(parsed)
    if polygon[0] == polygon[-1]:
        polygon = polygon[:-1]
    if not 3 <= len(polygon) <= limit:
        raise PlanGeometryError('عدد رؤوس المضلع غير صالح.')
    if len({tuple(point) for point in polygon}) != len(polygon):
        raise PlanGeometryError('حدود المضلع تحتوي نقاطًا مكررة.')
    if abs(signed_area(polygon)) <= EPSILON:
        raise PlanGeometryError('المضلع لا يكوّن مساحة أرض صالحة.')
    edges = list(segments(polygon))
    for index, (a, b) in enumerate(edges):
        for other, (c, d) in enumerate(edges[index + 1:], index + 1):
            if other in (index + 1, len(edges) - 1 if index == 0 else -1):
                continue
            if proper_intersection(a, b, c, d) or segment_distance(a, b, c, d) <= EPSILON:
                raise PlanGeometryError('حدود المضلع تتقاطع مع نفسها.')
    return polygon


def boundary_geometry(value):
    surveyed = read_points(value)
    origin = [min(point['eastings'] for point in surveyed), min(point['northings'] for point in surveyed)]
    grouped = {}
    for point in surveyed:
        grouped.setdefault(point['parcel_id'] or 'parcel_1', []).append(point)
    if not any(len(rows) >= 3 for rows in grouped.values()):
        # A parcel under three vertices can never be a polygon, so per-point
        # parcel ids here are extraction noise, not real parcels — merge the
        # rows back into one boundary (exact-coordinate duplicates dropped).
        merged, seen = [], set()
        for row in surveyed:
            key = (row['eastings'], row['northings'])
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
        grouped = {'parcel_1': merged}
    parcels = []
    for parcel_id, rows in grouped.items():
        polygon = validate_polygon([[row['eastings'] - origin[0], row['northings'] - origin[1]] for row in rows])
        parcels.append({'id': parcel_id, 'polygon': polygon})
    for index, parcel in enumerate(parcels):
        if any(polygons_overlap(parcel['polygon'], other['polygon']) for other in parcels[index + 1:]):
            raise PlanGeometryError('القطع المساحية تتداخل.')
    return {'surveyPoints': surveyed, 'origin': origin, 'parcels': parcels}


def edge_direction(a, b, polygon):
    dx, dy = b[0] - a[0], b[1] - a[1]
    normal = (dy, -dx) if signed_area(polygon) > 0 else (-dy, dx)
    return max(DIRECTION_VECTORS, key=lambda direction: sum(
        x * y for x, y in zip(normal, DIRECTION_VECTORS[direction])))


def parcel_edges(geometry):
    return [{'parcelId': parcel['id'], 'a': a, 'b': b,
             'direction': edge_direction(a, b, parcel['polygon'])}
            for parcel in geometry['parcels'] for a, b in segments(parcel['polygon'])]


def polygon_inside(polygon, outer):
    if not all(point_inside(point, outer) for point in polygon):
        return False
    for a, b in segments(polygon):
        if not point_inside([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], outer):
            return False
        if any(proper_intersection(a, b, c, d) for c, d in segments(outer)):
            return False
    return True


def polygons_overlap(first, second):
    if any(proper_intersection(a, b, c, d) for a, b in segments(first) for c, d in segments(second)):
        return True
    if any(point_inside(point, second, boundary=False) for point in first):
        return True
    if any(point_inside(point, first, boundary=False) for point in second):
        return True
    winding = 1 if signed_area(first) > 0 else -1
    for a, b in segments(first):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        inset = max(EPSILON * 20, length * 1e-6)
        point = [(a[0] + b[0]) / 2 - winding * (b[1] - a[1]) * inset / length,
                 (a[1] + b[1]) / 2 + winding * (b[0] - a[0]) * inset / length]
        if point_inside(point, first, boundary=False) and point_inside(point, second, boundary=False):
            return True
    return False


def clip_halfplane(polygon, a, b, sign):
    """Sutherland-Hodgman clip of a polygon against the line through shifted
    edge ab, keeping the parcel-interior side: sign*cross(b-a, p-a) >= 0."""
    direction = (b[0] - a[0], b[1] - a[1])

    def offset(point):
        return sign * (direction[0] * (point[1] - a[1]) - direction[1] * (point[0] - a[0]))

    clipped = []
    previous, previous_in = polygon[-1], offset(polygon[-1]) >= -EPSILON
    for point in polygon:
        current_in = offset(point) >= -EPSILON
        if current_in != previous_in:
            denominator = direction[0] * (point[1] - previous[1]) - direction[1] * (point[0] - previous[0])
            if abs(denominator) > EPSILON:
                t = (direction[0] * (a[1] - previous[1]) - direction[1] * (a[0] - previous[0])) / denominator
                clipped.append([previous[0] + t * (point[0] - previous[0]),
                                previous[1] + t * (point[1] - previous[1])])
        if current_in:
            clipped.append(point)
        previous, previous_in = point, current_in
    return clipped


def setback_envelope(polygon, setbacks):
    """The buildable region of one parcel after the recorded setbacks: the
    parcel clipped by each recorded-direction edge shifted inward by its
    setback. A point inside keeps at least the setback distance from every
    setback edge's supporting line, and segment distance never undershoots line
    distance — so a footprint wholly inside the envelope always passes the
    recorded setback check. Convex parcels get the exact feasible region."""
    envelope = [list(point) for point in polygon]
    if not setbacks or len(envelope) < 3:
        return envelope
    sign = 1.0 if signed_area(polygon) > 0 else -1.0
    for a, b in segments(polygon):
        setback = finite_number(setbacks.get(edge_direction(a, b, polygon)))
        if not setback or setback <= 0:
            continue
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if not length:
            continue
        shift = (-(b[1] - a[1]) * sign * setback / length, (b[0] - a[0]) * sign * setback / length)
        envelope = clip_halfplane(envelope, (a[0] + shift[0], a[1] + shift[1]),
                                  (b[0] + shift[0], b[1] + shift[1]), sign)
        if not envelope:
            break
    if len(envelope) < 3 or abs(signed_area(envelope)) <= EPSILON:
        return []
    return envelope


def validate_footprint(value, geometry, setbacks=None):
    polygon = validate_polygon(value, limit=24)
    parcel = next((item for item in geometry['parcels'] if polygon_inside(polygon, item['polygon'])), None)
    if parcel is None:
        raise PlanGeometryError('بصمة أحد المباني تتجاوز حدود الأرض.', 'PLANS_FOOTPRINT_OUTSIDE')
    for a, b in segments(parcel['polygon']):
        direction = edge_direction(a, b, parcel['polygon'])
        setback = finite_number((setbacks or {}).get(direction))
        if setback is not None and setback > 0:
            distance = min(segment_distance(a, b, c, d) for c, d in segments(polygon))
            if distance + EPSILON < setback:
                raise PlanGeometryError('بصمة أحد المباني تتجاوز الارتداد المسجل.', 'PLANS_SETBACK_CONFLICT')
    return polygon


def fit_projection(points, width, height, margin=80):
    min_x, max_x = min(point[0] for point in points), max(point[0] for point in points)
    min_y, max_y = min(point[1] for point in points), max(point[1] for point in points)
    scale = min((width - 2 * margin) / max(max_x - min_x, EPSILON),
                (height - 2 * margin) / max(max_y - min_y, EPSILON))
    offset_x = (width - (max_x - min_x) * scale) / 2
    offset_y = (height - (max_y - min_y) * scale) / 2
    return lambda point: (offset_x + (point[0] - min_x) * scale,
                          height - offset_y - (point[1] - min_y) * scale)


def isometric_projection(point, height=0, frontage='south'):
    angle = {'south': math.pi, 'north': 0, 'east': math.pi / 2, 'west': -math.pi / 2}.get(frontage, 0)
    x = point[0] * math.cos(angle) - point[1] * math.sin(angle)
    y = point[0] * math.sin(angle) + point[1] * math.cos(angle)
    return ((x - y) * math.sqrt(3) / 2, -(x + y) / 2 + height, x + y)
