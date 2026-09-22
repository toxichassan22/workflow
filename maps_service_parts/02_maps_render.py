

def _get_drive_matrix_chunk(origin, destinations, usage_ctx=None):
    """Return [{name, distance_km, duration_min}] for one driving matrix request.

    origin may be (lat, lng) or a dict with lat/lng keys.
    """
    if not _has_api_key():
        return []

    if not destinations:
        return []

    if isinstance(origin, (tuple, list)) and len(origin) >= 2:
        origin_str = f"{origin[0]},{origin[1]}"
    else:
        origin_str = f"{origin.get('lat')},{origin.get('lng')}"

    points = []
    names = []
    for d in destinations:
        lat = d.get('lat') if isinstance(d, dict) else d[0]
        lng = d.get('lng') if isinstance(d, dict) else d[1]
        if lat is None or lng is None:
            return []  # index alignment with destinations must be preserved
        points.append(f"{lat},{lng}")
        names.append(d.get('name', '') if isinstance(d, dict) else '')

    if not points:
        return []

    matrix_tenant = usage_ctx.get('tenant_id') if isinstance(usage_ctx, dict) else None
    matrix_key = _discovery_cache_key(
        matrix_tenant, 'matrix', None, None,
        extra=f"{origin_str}|{'|'.join(points)}")
    matrix_hit = _discovery_cache_get(matrix_tenant, matrix_key)
    if isinstance(matrix_hit, list) and len(matrix_hit) == len(points):
        return matrix_hit

    url = 'https://maps.googleapis.com/maps/api/distancematrix/json'
    params = {
        'origins': origin_str,
        'destinations': '|'.join(points),
        'mode': 'driving',
        'language': 'ar',
        'region': 'SA',
        # Live traffic: without departure_time Google returns free-flow duration,
        # which is what made our numbers lower than the Google Maps app.
        'departure_time': 'now',
        'traffic_model': 'best_guess',
        'key': _get_api_key(),
    }

    try:
        response = requests.get(_assert_allowed_remote_url(url), params=params, timeout=15)
        data = response.json()
        if data.get('status') != 'OK':
            print(f"[DRIVE MATRIX] API error: {data.get('status')}")
            return []
        _record_maps_usage(usage_ctx, 'distance_matrix', len(points))

        rows = data.get('rows', [])
        if not rows:
            return []

        elements = rows[0].get('elements', [])
        result = []
        for i, elem in enumerate(elements):
            distance_km = None
            duration_min = None
            in_traffic = False
            if elem.get('status') == 'OK' and elem.get('duration') and elem.get('distance'):
                distance_km = round(elem['distance']['value'] / 1000.0, 1)
                # Prefer the traffic-aware duration; fall back to free-flow.
                traffic = elem.get('duration_in_traffic') or {}
                seconds = traffic.get('value') or elem['duration']['value']
                in_traffic = bool(traffic.get('value'))
                duration_min = math.ceil(seconds / 60)
            # One entry per destination, in order, so callers can zip by index.
            result.append({
                'name': names[i] if i < len(names) else '',
                'distance_km': distance_km,
                'duration_min': duration_min,
                'distance_text': f"{distance_km} كم" if distance_km is not None else None,
                'in_traffic': in_traffic,
            })
        # Google bills one element per origin-destination pair; a single origin
        # keeps elements equal to destinations, and the cached answer is reused
        # for the same pairs instead of paying per re-analysis.
        _discovery_cache_put(matrix_tenant, matrix_key, result, ttl_days=7)
        return result
    except Exception as e:
        print(f"[DRIVE MATRIX] request failed: {e}")
        return []


def get_street_view(lat, lng, heading=None, pitch=0, fov=90, size=(640, 480), output_path=None, usage_ctx=None):
    """Download a Street View static image."""
    if not _has_api_key():
        return _api_key_error()

    if output_path is None:
        filename = f"streetview_{uuid.uuid4().hex}.jpg"
        output_path = os.path.join(MAPS_DIR, filename)

    url = 'https://maps.googleapis.com/maps/api/streetview'
    params = {
        'location': f"{lat},{lng}",
        'size': f"{size[0]}x{size[1]}",
        'key': _get_api_key(),
        'pitch': pitch,
        'fov': fov,
    }
    if heading is not None:
        params['heading'] = heading

    res = _download_image(url, params, output_path)
    if res.get('success'):
        _record_maps_usage(usage_ctx, 'streetview', 1)
    return res


def _build_markers(lat, lng, landmarks=None, label_start=1):
    """Build custom marker overlay list for a map."""
    markers = [{'lat': lat, 'lng': lng, 'color': MARKER_COLOR_SITE, 'type': 'site', 'label': None}]
    if landmarks:
        for i, lm in enumerate(landmarks):
            label = str((label_start + i) % 100)
            markers.append({
                'lat': lm['lat'],
                'lng': lm['lng'],
                'color': MARKER_COLOR_LANDMARK,
                'type': 'landmark',
                'label': label,
                'name': str(lm.get('name') or '').strip(),
            })
    return markers


def _build_catchment_paths(lat, lng, zones):
    """Build path strings for catchment area circles."""
    paths = []
    # Professional maroon-red colors matching the theme
    colors = ['0x6B1C23', '0x8B2020', '0xA63A3A']
    for i, zone in enumerate(zones):
        radius_km = zone.get('km', zone.get('minutes', 5) * 0.8 / 1.60934)
        points = []
        for angle in range(0, 360, 10):
            rad = math.radians(angle)
            # Approximate degree offset for radius
            lat_offset = (radius_km / 111.32) * math.cos(rad)
            lng_offset = (radius_km / (111.32 * math.cos(math.radians(lat)))) * math.sin(rad)
            points.append(f"{lat + lat_offset},{lng + lng_offset}")
        color = colors[i % len(colors)]
        # Use 20 (hex) opacity for fillcolor for a subtle transparent overlay
        paths.append(f"weight:2|color:{color}|fillcolor:{color}20|{ '|'.join(points)}")
    return paths if paths else None


def normalize_access_road_names(value):
    values = value if isinstance(value, list) else re.split(r'[\n,،;|]+', str(value or ''))
    result = []
    seen = set()
    for raw in values:
        name = str(raw or '').strip()
        if not name:
            continue
        name = re.split(r'\s+[—–-]\s+(?=\d|\d*[.]\d|\D*دقيقة)', name, maxsplit=1)[0].strip()
        prefix_match = re.match(r'^(طريق|شارع|جادة|ممر)\s+', name)
        prefix = prefix_match.group(1) if prefix_match else ''
        parts = [part.strip() for part in re.split(r'\s+و(?=\s|ال|شارع|طريق|جادة|ممر)\s*', name) if part.strip()]
        for part in parts:
            if prefix and not re.match(r'^(طريق|شارع|جادة|ممر)\s+', part):
                part = f'{prefix} {part}'
            key = re.sub(r'^(?:طريق|شارع|جادة|ممر)\s+', '', part)
            key = re.sub(r'[\sـ]+', ' ', key).strip().casefold()
            if key and key not in seen:
                seen.add(key)
                result.append(part)
    return result


def _build_road_paths(lat, lng, main_roads=None, secondary_roads=None):
    """No longer draws random lines. Roads are highlighted via map styles instead."""
    # Previously this drew star-pattern lines from center which looked terrible.
    # Now we rely on ACCESS_MAP_STYLES to highlight roads on the map itself.
    return None


def _build_site_area_path(lat, lng, zoom, area_radius_m=300):
    """Build a filled rectangle path around the site to highlight the project area."""
    # Convert radius in meters to approximate degree offsets
    lat_offset = area_radius_m / 111320.0
    lng_offset = area_radius_m / (111320.0 * math.cos(math.radians(lat)))
    # Build a rectangle (4 corners)
    corners = [
        f"{lat - lat_offset},{lng - lng_offset}",
        f"{lat + lat_offset},{lng - lng_offset}",
        f"{lat + lat_offset},{lng + lng_offset}",
        f"{lat - lat_offset},{lng + lng_offset}",
        f"{lat - lat_offset},{lng - lng_offset}",
    ]
    return f"weight:3|color:0xC0392B|fillcolor:0xC0392B30|{'|'.join(corners)}"


def _approx_polygon_area_sqm(coords):
    """Approximate polygon area using the Shoelace formula with degree-to-meter conversion."""
    n = len(coords)
    if n < 3:
        return 0
    avg_lat = sum(c[0] for c in coords) / n
    m_per_deg_lat = 111320.0
    m_per_deg_lng = 111320.0 * math.cos(math.radians(avg_lat))
    
    area = 0
    for i in range(n):
        j = (i + 1) % n
        x_i = coords[i][1] * m_per_deg_lng
        y_i = coords[i][0] * m_per_deg_lat
        x_j = coords[j][1] * m_per_deg_lng
        y_j = coords[j][0] * m_per_deg_lat
        area += x_i * y_j - x_j * y_i
    return abs(area) / 2.0


def _point_in_polygon(lat, lng, coords):
    """Return True only when the requested site point lies inside a polygon.

    Geocoding an address frequently returns the centre of a street or district.
    Selecting the nearest OSM building in that situation creates a misleading,
    apparently random highlight. Containment is the safe condition for an
    automatically selected footprint.
    """
    if len(coords) < 3:
        return False
    inside = False
    previous_lat, previous_lng = coords[-1]
    for current_lat, current_lng in coords:
        crosses = (current_lat > lat) != (previous_lat > lat)
        if crosses:
            boundary_lng = (previous_lng - current_lng) * (lat - current_lat) / (previous_lat - current_lat) + current_lng
            if lng < boundary_lng:
                inside = not inside
        previous_lat, previous_lng = current_lat, current_lng
    return inside


def _is_viewport_rectangle(coords):
    """Check if coordinates form a 4-point geocoding viewport bounding rectangle."""
    if not coords or len(coords) != 4:
        return False
    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    unique_lats = {round(lat, 5) for lat in lats}
    unique_lngs = {round(lng, 5) for lng in lngs}
    return len(unique_lats) == 2 and len(unique_lngs) == 2


def _point_to_segment_dist_m(plat, plng, alat, alng, blat, blng):
    """Shortest distance in meters from a point to a line segment between two vertices."""
    mlat = math.radians((plat + alat + blat) / 3.0)
    mx = 111320.0 * math.cos(mlat)
    my = 110540.0
    px, py = plng * mx, plat * my
    ax, ay = alng * mx, alat * my
    bx, by = blng * mx, blat * my
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _min_dist_to_polygon_m(plat, plng, coords):
    """Shortest distance from point to polygon perimeter (edges, not just vertices)."""
    best = float('inf')
    for i in range(len(coords)):
        a = coords[i]
        b = coords[(i + 1) % len(coords)]
        d = _point_to_segment_dist_m(plat, plng, a[0], a[1], b[0], b[1])
        if d < best:
            best = d
    return best


def utm_to_latlng(easting, northing, zone, northern=True):
    """Inverse UTM on WGS84 so croquis eastings/northings can be drawn on a map."""
    a = 6378137.0
    f = 1 / 298.257223563
    k0 = 0.9996
    e2 = f * (2 - f)
    e_prime2 = e2 / (1 - e2)
    x = easting - 500000.0
    y = northing if northern else northing - 10000000.0
    m = y / k0
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
        + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
        + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
        + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
    )
    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    tan_phi1 = math.tan(phi1)
    c1 = e_prime2 * cos_phi1 ** 2
    t1 = tan_phi1 ** 2
    n1 = a / math.sqrt(1 - e2 * sin_phi1 ** 2)
    r1 = a * (1 - e2) / (1 - e2 * sin_phi1 ** 2) ** 1.5
    d = x / (n1 * k0)
    latitude = phi1 - (n1 * tan_phi1 / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * e_prime2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * e_prime2 - 3 * c1 ** 2) * d ** 6 / 720
    )
    longitude = (
        d
        - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * e_prime2 + 24 * t1 ** 2) * d ** 5 / 120
    ) / cos_phi1
    central_meridian = (zone - 1) * 6 - 180 + 3
    return math.degrees(latitude), central_meridian + math.degrees(longitude)


def utm_zone_for_longitude(longitude):
    return int((float(longitude) + 180) / 6) + 1


def _survey_points(project_data):
    """Read the croquis coordinates table, whatever shape the draft stored it in."""
    raw = (project_data or {}).get('survey_coordinates')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        easting = item.get('eastings') or item.get('easting') or item.get('x')
        northing = item.get('northings') or item.get('northing') or item.get('y')
        try:
            easting = float(str(easting).replace(',', '').strip())
            northing = float(str(northing).replace(',', '').strip())
        except (TypeError, ValueError):
            continue
        if easting <= 0 or northing <= 0:
            continue
        rows.append({
            'easting': easting,
            'northing': northing,
            'parcel_id': str(item.get('parcel_id') or item.get('parcelId') or '').strip(),
        })
    return rows


def survey_polygon_from_project(project_data, site_lat, site_lng, tolerance_km=8.0):
    """Build the site boundary from the croquis survey coordinates.

    No Google Maps API returns a building footprint or a parcel outline — Geocoding and
    Places expose only a bounds rectangle — so the croquis table is the one authoritative
    boundary the system actually receives, and it is already in the draft.
    """
    rows = _survey_points(project_data)
    if len(rows) < 3:
        return None
    try:
        zone = utm_zone_for_longitude(site_lng)
        northern = float(site_lat) >= 0
    except (TypeError, ValueError):
        return None
    parcels = {}
    for row in rows:
        parcels.setdefault(row['parcel_id'], []).append(row)
    best = None
    for parcel_id, points in parcels.items():
        if len(points) < 3:
            continue
        coords = []
        for point in points:
            try:
                coords.append(utm_to_latlng(point['easting'], point['northing'], zone, northern))
            except (ValueError, ZeroDivisionError, OverflowError):
                coords = []
                break
        if len(coords) < 3:
            continue
        center_lat = sum(item[0] for item in coords) / len(coords)
        center_lng = sum(item[1] for item in coords) / len(coords)
        offset_km = math.hypot(
            (center_lat - float(site_lat)) * 111.32,
            (center_lng - float(site_lng)) * 111.32 * math.cos(math.radians(float(site_lat))),
        )
        # A local or municipal grid converts to somewhere else entirely; reject it rather
        # than highlighting the wrong place.
        if offset_km > tolerance_km:
            print(f'[SURVEY POLYGON] parcel {parcel_id or "-"} lands {offset_km:.1f} km away; ignored')
            continue
        if best is None or offset_km < best[0]:
            best = (offset_km, parcel_id, coords)
    if not best:
        return None
    offset_km, parcel_id, coords = best
    print(
        f'[SURVEY POLYGON] parcel {parcel_id or "-"}: {len(coords)} croquis points, '
        f'centre {offset_km * 1000:.0f} m from the site pin'
    )
    return coords


def _google_bounds_polygon(lat, lng, tenant_id=None, max_span_m=400, usage_ctx=None):
    """Last automatic resort: the Geocoding bounds rectangle for the address.

    This is a rectangle, not a real outline, so it is only accepted when it is small
    enough to plausibly be one plot.
    """
    if not _has_api_key():
        return None
    try:
        response = requests.get(
            'https://maps.googleapis.com/maps/api/geocode/json',
            params={'latlng': f'{lat},{lng}', 'key': _get_api_key(), 'language': 'ar'}, timeout=15
        )
        data = response.json()
        if data.get('status') != 'OK':
            return None
        _record_maps_usage(
            usage_ctx or maps_usage_ctx('geocode', tenant_id=tenant_id),
            'geocode', 1)
        for result in data.get('results', []):
            geometry = result.get('geometry') or {}
            bounds = geometry.get('bounds')
            if not bounds:
                continue
            northeast = bounds.get('northeast') or {}
            southwest = bounds.get('southwest') or {}
            try:
                north, east = float(northeast['lat']), float(northeast['lng'])
                south, west = float(southwest['lat']), float(southwest['lng'])
            except (KeyError, TypeError, ValueError):
                continue
            height_m = abs(north - south) * 111320.0
            width_m = abs(east - west) * 111320.0 * math.cos(math.radians(lat))
            if max(height_m, width_m) > max_span_m or min(height_m, width_m) <= 0:
                continue
            print(f'[GOOGLE BOUNDS] rectangle {width_m:.0f}m x {height_m:.0f}m from geocoding')
            return [(south, west), (south, east), (north, east), (north, west)]
    except Exception as error:
        print(f'[GOOGLE BOUNDS ERROR] {error}')
    return None


def _fetch_osm_polygon(lat, lng, radius_m=400):
    """Fetch the real building/compound polygon from OpenStreetMap via Overpass API in a single optimized query."""
    
    overpass_servers = [
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    
    headers = {
        'User-Agent': 'RealEstateProposalGenerator/1.0'
    }
    
    query = f"""[out:json][timeout:15];
    (
      way(around:{radius_m},{lat},{lng})["building"];
      relation(around:{radius_m},{lat},{lng})["building"];
    );
    out geom;"""
    
    data = None
    for server_url in overpass_servers:
        try:
            resp = requests.post(_assert_allowed_remote_url(server_url), data={'data': query}, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                break
        except Exception as e:
            print(f"[OSM POLYGON] Server {server_url} failed: {e}")
            continue
            
    if not data:
        return None
        
    elements = data.get('elements', [])
    if not elements:
        return None
        
    MAX_BUILDING_AREA_SQM = 100000

    print(f"[OSM POLYGON] Overpass returned {len(elements)} building elements near ({lat}, {lng})")
    rejected = {'no_tag': 0, 'too_large': 0, 'too_small': 0, 'too_far': 0}

    best_el = None
    best_sort_key = None

    for el in elements:
        geom = el.get('geometry', [])
        if len(geom) < 3:
            continue
            
        coords = [(p['lat'], p['lon']) for p in geom]
        area_sqm = _approx_polygon_area_sqm(coords)
        tags = el.get('tags', {})
        
        if 'building' not in tags:
            rejected['no_tag'] += 1
            continue
        tag_type = "building:" + str(tags['building'])

        if area_sqm > MAX_BUILDING_AREA_SQM:
            rejected['too_large'] += 1
            continue
        if area_sqm < 10:
            rejected['too_small'] += 1
            continue
            
        min_dist_to_vertex = _min_dist_to_polygon_m(lat, lng, coords)
        is_inside = _point_in_polygon(lat, lng, coords)
        
        if not is_inside:
            rejected['too_far'] += 1
            print(f"[OSM CANDIDATE] rejected-outside {tag_type}: {area_sqm:.0f} sqm, {min_dist_to_vertex:.1f} m")
            continue

        print(f"[OSM CANDIDATE] accepted {tag_type}: {area_sqm:.0f} sqm, {min_dist_to_vertex:.1f} m, inside={is_inside}")
            
        # Prefer the smallest building footprint that contains the exact coordinate.
        sort_key = (area_sqm, min_dist_to_vertex)
        if best_sort_key is None or sort_key < best_sort_key:
            best_sort_key = sort_key
            best_el = el
            
    if best_el and best_el.get('geometry'):
        coords = [(p['lat'], p['lon']) for p in best_el['geometry']]
        tags = best_el.get('tags', {})
        area_sqm = _approx_polygon_area_sqm(coords)
        tag_name = tags.get('name', '')
        tag_type = tags.get('leisure', tags.get('building', tags.get('amenity', tags.get('landuse', 'polygon'))))
        is_inside_str = "containing"
        try:
            print(f"[OSM POLYGON] Found {is_inside_str} {tag_type} '{tag_name}' ({best_sort_key[1]:.0f} sqm), ~{area_sqm:.0f} sqm")
        except Exception:
            safe_name = str(tag_name).encode('ascii', errors='ignore').decode('ascii')
            print(f"[OSM POLYGON] Found {is_inside_str} {tag_type} '{safe_name}' ({best_sort_key[1]:.0f} sqm), ~{area_sqm:.0f} sqm")
        return coords
        
    print(f"[OSM POLYGON] No suitable polygon found near ({lat}, {lng}) | rejected={rejected}")
    return None


def _fetch_osm_neighborhood(lat, lng, radius_m=2000):
    """Fetch a neighborhood/suburb/district boundary from OpenStreetMap for sites without building footprints."""

    overpass_servers = [
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]

    headers = {
        'User-Agent': 'RealEstateProposalGenerator/1.0'
    }

    query = f"""[out:json][timeout:20];
    (
      way(around:{radius_m},{lat},{lng})["place"~"suburb|neighbourhood|quarter|district|city_block|locality"];
      relation(around:{radius_m},{lat},{lng})["place"~"suburb|neighbourhood|quarter|district|city_block|locality"];
      relation(around:{radius_m},{lat},{lng})["boundary"="administrative"]["admin_level"="8"];
      relation(around:{radius_m},{lat},{lng})["boundary"="administrative"]["admin_level"="9"];
      relation(around:{radius_m},{lat},{lng})["boundary"="administrative"]["admin_level"="10"];
    );
    out geom;"""

    data = None
    for server_url in overpass_servers:
        try:
            resp = requests.post(_assert_allowed_remote_url(server_url), data={'data': query}, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                break
        except Exception as e:
            print(f"[OSM NEIGHBORHOOD] Server {server_url} failed: {e}")
            continue

    if not data:
        return None

    elements = data.get('elements', [])
    if not elements:
        return None

    candidates = []
    for el in elements:
        el_type = el.get('type')
        tags = el.get('tags', {})
        if el_type == 'relation':
            for member in el.get('members', []):
                if member.get('type') == 'way' and member.get('role') == 'outer' and member.get('geometry'):
                    outer = [(p['lat'], p['lon']) for p in member['geometry'] if 'lat' in p and 'lon' in p]
                    if len(outer) >= 3:
                        candidates.append({'coords': outer, 'tags': tags})
        elif el_type == 'way' and el.get('geometry'):
            outer = [(p['lat'], p['lon']) for p in el['geometry'] if 'lat' in p and 'lon' in p]
            if len(outer) >= 3:
                candidates.append({'coords': outer, 'tags': tags})

    if not candidates:
        return None

    MAX_NEIGHBORHOOD_AREA_SQM = 50_000_000  # 50 km²
    MIN_NEIGHBORHOOD_AREA_SQM = 10_000      # 1 hectare

    best = None
    best_key = None
    best_area = 0
    for cand in candidates:
        area_sqm = _approx_polygon_area_sqm(cand['coords'])
        if area_sqm > MAX_NEIGHBORHOOD_AREA_SQM or area_sqm < MIN_NEIGHBORHOOD_AREA_SQM:
            continue
        inside = _point_in_polygon(lat, lng, cand['coords'])
        dist = _min_dist_to_polygon_m(lat, lng, cand['coords'])
        # Prefer containing, then smallest containing, then closest non-containing
        key = (0 if inside else 1, area_sqm if inside else dist, dist if inside else area_sqm)
        if best is None or key < best_key:
            best = cand['coords']
            best_key = key
            best_area = area_sqm

    if best:
        print(f"[OSM NEIGHBORHOOD] Found neighborhood {best_area:.0f} sqm, inside={best_key[0] == 0}")
        return best

    return None


# Cache for OSM polygons to avoid re-querying for the same location across map types
_osm_polygon_cache = {}

# Cache for OSM neighborhood boundaries
_osm_neighborhood_cache = {}


def _draw_site_highlight(image_path, center_lat, center_lng, zoom, area_radius_m=300, size=(1280, 720), scale=2,
                         polygon_coords=None, auto_detect_polygon=True, auto_detected=True, rotation_deg=18.0):
    """Draw the site highlight using the real building shape.
    Priority: 1) Real user polygon, 2) Auto-detected building/neighborhood polygon from OSM, 3) Styled site circle fallback.
    auto_detected=False skips the 4-point viewport-rectangle filter, preserving user-drawn rectangles."""
    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        cx, cy = img_w // 2, img_h // 2

        overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        fill_color = SITE_FILL_COLOR
        border_color = SITE_BORDER_COLOR

        # Ignore 4-point geocoding viewport rectangles so real OSM building shapes are preferred.
        # Only apply to auto-detected (OSM) polygons; user-drawn rectangles must be preserved.
        if auto_detected and polygon_coords and _is_viewport_rectangle(polygon_coords):
            polygon_coords = None

        # Priority 1 & 2: Real building polygon
        if auto_detect_polygon and (not polygon_coords or len(polygon_coords) < 3):
            cache_key = f"{center_lat:.6f},{center_lng:.6f}"
            if cache_key in _osm_polygon_cache:
                osm_poly = _osm_polygon_cache[cache_key]
            else:
                osm_poly = _fetch_osm_polygon(center_lat, center_lng, radius_m=400)
                if osm_poly:
                    _osm_polygon_cache[cache_key] = osm_poly
            
            if osm_poly and len(osm_poly) >= 3:
                polygon_coords = osm_poly

        if polygon_coords and len(polygon_coords) >= 3:
            pixel_points = []
            for p_lat, p_lng in polygon_coords:
                dx, dy = _latlng_to_pixel_offset(p_lat, p_lng, center_lat, center_lng, zoom, scale=scale)
                px = int(cx + dx)
                py = int(cy + dy)
                pixel_points.append((px, py))
            
            overlay_draw.polygon(pixel_points, fill=fill_color, outline=border_color, width=5)
            overlay_draw.polygon(pixel_points, fill=None, outline=(255, 255, 255, 160), width=3)
        else:
            # Priority 3: Compact exact-point halo when no building polygon exists
            r = 14 if zoom >= 16 else 10
            overlay_draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(160, 50, 50, 45), outline=border_color, width=3)
            overlay_draw.line([(cx - r - 5, cy), (cx + r + 5, cy)], fill=(255, 255, 255, 180), width=2)
            overlay_draw.line([(cx, cy - r - 5), (cx, cy + r + 5)], fill=(255, 255, 255, 180), width=2)

        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[SITE HIGHLIGHT ERROR] {e}")
        return False


def catchment_rings(zones, limit=3):
    """Collapse the catchment rows into a few concentric drive-time bands.

    The rows the user fills are destinations (airport, station, corniche), not zones, so
    drawing one ring per row produced nine overlapping circles up to 31 km wide whose
    labels were unreadable.
    """
    candidates = []
    for zone in zones or []:
        if not isinstance(zone, dict):
            continue
        try:
            km = float(zone.get('km') or zone.get('distance_km') or zone.get('distance'))
        except (TypeError, ValueError):
            continue
        if km <= 0:
            continue
        minutes = zone.get('minutes') or zone.get('duration_minutes') or zone.get('duration_min')
        try:
            minutes = int(float(minutes))
        except (TypeError, ValueError):
            minutes = None
        candidates.append({
            'km': km,
            'minutes': minutes,
            'label': zone.get('label') or zone.get('name') or '',
        })
    if not candidates:
        return []
    candidates.sort(key=lambda item: item['km'])
    if len(candidates) <= limit:
        chosen = candidates
    else:
        indexes = {0, len(candidates) // 2, len(candidates) - 1}
        chosen = [candidates[index] for index in sorted(indexes)][:limit]
    rings = []
    for item in chosen:
        minutes = item['minutes']
        name = str(item.get('label') or item.get('name') or '').strip()
        time_label = f'{minutes} دقائق' if minutes else f'{item["km"]:.1f} كم'
        label = f'{name} — {time_label}' if name else time_label
        rings.append({'km': item['km'], 'minutes': minutes or 0, 'name': name, 'label': label})
    return rings


def zoom_for_radius_km(lat, radius_km, size=(1280, 720), scale=2, fill=0.8):
    """Pick the closest zoom that still keeps a radius fully inside the frame."""
    try:
        radius_m = float(radius_km) * 1000.0
    except (TypeError, ValueError):
        return None
    if radius_m <= 0:
        return None
    allowed_px = min(size[0], size[1]) * scale * 0.5 * fill
    for zoom in range(20, 7, -1):
        metres_per_pixel = 156543.03392 * math.cos(math.radians(float(lat))) / (2 ** zoom) / scale
        if radius_m / metres_per_pixel <= allowed_px:
            return zoom
    return 8


def access_map_zoom(lat, base_zoom):
    try:
        base = int(base_zoom)
    except (TypeError, ValueError):
        base = 17
    context_zoom = zoom_for_radius_km(lat, ACCESS_MAP_CONTEXT_RADIUS_KM)
    if context_zoom is None:
        return max(15, min(17, base))
    return max(15, min(17, base, context_zoom))


def _draw_catchment_zones(image_path, center_lat, center_lng, zoom, zones, scale=2):
    """Draw smooth, anti-aliased concentric catchment rings and elegant label pills using PIL."""
    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        cx, cy = img_w // 2, img_h // 2
        
        # Create a high-res canvas for anti-aliasing
        canvas_scale = 4
        canvas_w = img_w * canvas_scale
        canvas_h = img_h * canvas_scale
        canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        
        ccx = canvas_w // 2
        ccy = canvas_h // 2
        
        # Theme colors: Gold/Maroon/Teal for premium look
        # [Inner, Middle, Outer]
        fill_colors = [
            (107, 28, 35, 20),   # Subtle dark maroon fill (alpha 20)
            (171, 131, 75, 15),  # Subtle bronze/gold fill (alpha 15)
            (37, 75, 102, 12),   # Subtle dark blue/teal fill (alpha 12)
        ]
        border_colors = [
            (107, 28, 35, 160),  # Dark maroon
            (171, 131, 75, 150), # Bronze/gold
            (37, 75, 102, 130),  # Teal/blue
        ]
        
        # Sort zones from largest radius to smallest, so smaller ones are drawn on top
        sorted_zones = sorted(zones, key=lambda z: z.get('km', z.get('minutes', 5) * 0.8), reverse=True)
        
        for idx, zone in enumerate(sorted_zones):
            radius_km = zone.get('km', zone.get('minutes', 5) * 0.8 / 1.60934)
            radius_m = radius_km * 1000.0
            
            # Get latitude offset for radius
            lat_offset = radius_m / 111320.0
            _, dy = _latlng_to_pixel_offset(center_lat + lat_offset, center_lng, center_lat, center_lng, zoom, scale=scale)
            
            # Scale to canvas coordinates
            r = int(abs(dy) * canvas_scale)
            
            color_idx = idx % len(fill_colors)
            fill_c = fill_colors[color_idx]
            border_c = border_colors[color_idx]
            
            # Draw catchment circle
            draw.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=fill_c, outline=border_c, width=3 * canvas_scale)
            # Add thin white inner edge for premium glassmorphism glow
            draw.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=None, outline=(255, 255, 255, 60), width=1 * canvas_scale)
            
            # Draw elegant label pill for each zone
            label = zone.get('label') or f"{zone.get('minutes', 5)} دقائق"
            font = _get_arabic_font(14 * canvas_scale)
            reshaped = _reshape_arabic_text(label)
                
            bbox = draw.textbbox((0, 0), reshaped, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            
            # Spread the pills around the circle: stacking them all straight above the centre
            # buried the innermost label under the site pin.
            pad_x = 10 * canvas_scale
            pad_y = 5 * canvas_scale
            angle = math.radians(90 + 35 * (idx % 3))
            lx = int(ccx + r * math.cos(angle))
            ly = int(ccy - r * math.sin(angle))
            
            label_width = tw + pad_x * 2
            label_height = th + pad_y * 2
            rect_left = max(8 * canvas_scale, min(canvas_w - label_width - 8 * canvas_scale, lx - label_width // 2))
            rect_top = max(8 * canvas_scale, min(canvas_h - label_height - 8 * canvas_scale, ly - label_height // 2))
            rect = [rect_left, rect_top, rect_left + label_width, rect_top + label_height]

            # Draw pill background and border
            draw.rounded_rectangle(rect, radius=4 * canvas_scale, fill=border_c, outline=(255, 255, 255, 200), width=1 * canvas_scale)
            draw.text((rect_left + pad_x - bbox[0], rect_top + pad_y - bbox[1]), reshaped, fill='#FFFFFF', font=font)

        # Downsample with LANCZOS
        resized = canvas.resize((img_w, img_h), Image.Resampling.LANCZOS)
        img = Image.alpha_composite(img, resized)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[DRAW CATCHMENT ERROR] {e}")
        return False


def _post_process_streetview(image_path, heading, index):
    """Apply professional enhancements to Street View images: vignette, contrast, elegant borders, and direction labels."""
    try:
        from PIL import ImageEnhance
        img = Image.open(image_path).convert('RGBA')
        w, h = img.size
        
        # 1. Enhance Contrast & Color Saturation slightly for a professional architectural photo look
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.15)
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(1.05)
        
        # 2. Add subtle warm sepia-like color balance
        r, g, b, a = img.split()
        grey = img.convert('L')
        # Warm golden-cream tint
        sepia_r = grey.point(lambda x: min(255, int(x * 1.05)))
        sepia_g = grey.point(lambda x: min(255, int(x * 1.00)))
        sepia_b = grey.point(lambda x: min(255, int(x * 0.92)))
        sepia = Image.merge('RGBA', (sepia_r, sepia_g, sepia_b, a))
        img = Image.blend(img, sepia, 0.15) # Subtle blending
        
        # 3. Create a professional vignette (darkening towards corners)
        vignette = Image.new('L', (w, h), 255)
        v_draw = ImageDraw.Draw(vignette)
        # Draw a radial gradient centered
        for i in range(min(w, h) // 2):
            alpha = int(120 * (i / (min(w, h) // 2)) ** 2) # quadratic scaling for smooth transition
            v_draw.ellipse([i, i, w - i, h - i], outline=255 - alpha)
        
        # Apply vignette as alpha mask on black overlay
        black_overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        for x in range(w):
            for y in range(h):
                val = vignette.getpixel((x, y))
                if val < 255:
                    black_overlay.putpixel((x, y), (0, 0, 0, int((255 - val) * 0.4)))
        img = Image.alpha_composite(img, black_overlay)
        
        # 4. Draw elegant thin gold/cream border and white inner frame
        draw = ImageDraw.Draw(img)
        border_w = 4
        # Outer gold/bronze border
        gold_color = (171, 131, 75, 230)
        draw.rectangle([0, 0, w - 1, h - 1], outline=gold_color, width=border_w)
        # Inner thin white line
        draw.rectangle([border_w + 2, border_w + 2, w - border_w - 3, h - border_w - 3], outline=(255, 255, 255, 120), width=1)
        
        # 5. Add an elegant direction label pill at the bottom-right
        directions = {
            0: "إطلالة الشمال",
            90: "إطلالة الشرق",
            180: "إطلالة الجنوب",
            270: "إطلالة الغرب"
        }
        dir_text = directions.get(heading, f"إطلالة {heading} درجة")
        font = _get_arabic_font(14)
        reshaped = _reshape_arabic_text(dir_text)
            
        bbox = draw.textbbox((0, 0), reshaped, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        
        pad_x = 12
        pad_y = 6
        rx = w - border_w - 15 - tw - pad_x * 2
        ry = h - border_w - 15 - th - pad_y * 2
        
        rect = [rx, ry, w - border_w - 15, h - border_w - 15]
        
        # Dark transculent background for label
        draw.rounded_rectangle(rect, radius=5, fill=(37, 75, 102, 210), outline=gold_color, width=1)
        draw.text((rx + pad_x, ry + pad_y - 2), reshaped, fill='#FFFFFF', font=font)
        
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[STREETVIEW ENHANCE ERROR] {e}")
        return False


def _draw_compass(image_path, position='top-right', compass_size=60):
    """Draw a professional compass indicator (ش = North) matching reference examples."""
    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Position compass
        margin = 30
        if position == 'top-right':
            comp_cx = img_w - margin - compass_size // 2
            comp_cy = margin + compass_size // 2
        else:
            comp_cx = margin + compass_size // 2
            comp_cy = margin + compass_size // 2

        r = compass_size // 2
        # Outer circle (cream/beige)
        draw.ellipse([comp_cx - r, comp_cy - r, comp_cx + r, comp_cy + r],
                     fill=(240, 230, 210, 220), outline=COMPASS_COLOR + (255,), width=3)

        font = _get_arabic_font(compass_size // 2)
        text = _reshape_arabic_text('ش')
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((comp_cx - tw // 2, comp_cy - th // 2 - 2), text,
                  fill=COMPASS_COLOR + (255,), font=font)

        # Small triangle pointing up (North indicator)
        tri_size = 8
        draw.polygon([(comp_cx, comp_cy - r + 6),
                      (comp_cx - tri_size // 2, comp_cy - r + 6 + tri_size),
                      (comp_cx + tri_size // 2, comp_cy - r + 6 + tri_size)],
                     fill=COMPASS_COLOR + (255,))

        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[COMPASS ERROR] {e}")
        return False


def _apply_sepia_tone(image_path, intensity=0.3):
    """Apply a warm sepia tone to satellite imagery matching reference examples."""
    try:
        img = Image.open(image_path).convert('RGBA')
        r, g, b, a = img.split()
        # Convert to greyscale
        grey = img.convert('L')
        # Create sepia channels (warm brown tone)
        sepia_r = grey.point(lambda x: min(255, int(x * (1 + 0.2 * intensity))))
        sepia_g = grey.point(lambda x: min(255, int(x * (1 + 0.05 * intensity))))
        sepia_b = grey.point(lambda x: min(255, int(x * (1 - 0.1 * intensity))))
        sepia = Image.merge('RGBA', (sepia_r, sepia_g, sepia_b, a))
        # Blend original with sepia
        result = Image.blend(img, sepia, intensity)
        result.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[SEPIA ERROR] {e}")
        return False


def _draw_inset_map(image_path, center_lat, center_lng, inset_size=180):
    """Draw a small inset/overview map in the bottom-right corner."""
    try:
        # Download a smaller wide-area map
        inset_path = image_path + '.inset.png'
        inset_res = get_static_map(center_lat, center_lng, zoom=9,
                                    size=(inset_size, inset_size),
                                    output_path=inset_path,
                                    styles=SATELLITE_CLEAN_STYLES)
        if not inset_res.get('success'):
            return False

        img = Image.open(image_path).convert('RGBA')
        inset = Image.open(inset_path).convert('RGBA')
        # Resize inset (scale=2 makes it 2x, resize down)
        inset = inset.resize((inset_size, inset_size), Image.LANCZOS)

        img_w, img_h = img.size
        # Position: bottom-right with margin
        margin = 20
        ix = img_w - inset_size - margin
        iy = img_h - inset_size - margin

        # Draw border around inset
        border = Image.new('RGBA', (inset_size + 6, inset_size + 6), (240, 230, 210, 200))
        img.paste(border, (ix - 3, iy - 3), border)
        img.paste(inset, (ix, iy), inset)

        # Draw site marker on inset (center dot)
        draw = ImageDraw.Draw(img)
        inset_cx = ix + inset_size // 2
        inset_cy = iy + inset_size // 2
        # Small maroon triangle pin
        pin_s = 10
        draw.polygon([(inset_cx - pin_s, inset_cy - pin_s // 2),
                      (inset_cx + pin_s, inset_cy - pin_s // 2),
                      (inset_cx, inset_cy + pin_s)],
                     fill=MARKER_COLOR_SITE)

        img.save(image_path, 'PNG')

        # Cleanup temp inset file
        try:
            os.remove(inset_path)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[INSET MAP ERROR] {e}")
        return False


def _decode_polyline(polyline_str):
    """Decode Google Maps encoded polyline string into lat/lng list."""
    index = 0
    lat = 0
    lng = 0
    coordinates = []
    try:
        while index < len(polyline_str):
            b = 0
            shift = 0
            result = 0
            while True:
                b = ord(polyline_str[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if not b >= 0x20:
                     break
            dlat = ~(result >> 1) if (result & 1) else (result >> 1)
            lat += dlat

            shift = 0
            result = 0
            while True:
                b = ord(polyline_str[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if not b >= 0x20:
                     break
            dlng = ~(result >> 1) if (result & 1) else (result >> 1)
            lng += dlng
            coordinates.append((lat / 1e5, lng / 1e5))
    except Exception as e:
        print(f"[POLYLINE DECODE ERROR] {e}")
    return coordinates


def _snap_to_roads(lat, lng, tenant_id=None, usage_ctx=None):
    """Snap coordinates to nearest road using Google Roads API for precision."""
    if not _has_api_key():
        return None
    url = 'https://roads.googleapis.com/v1/nearestRoads'
    params = {
        'points': f"{lat},{lng}",
        'key': _get_api_key(),
    }
    try:
        resp = requests.get(_assert_allowed_remote_url(url), params=params, timeout=10)
        data = resp.json()
        if 'snappedPoints' in data and data['snappedPoints']:
            sp = data['snappedPoints'][0]
            loc = sp.get('location', {})
            if loc.get('latitude') and loc.get('longitude'):
                if tenant_id:
                    _record_maps_call(tenant_id)
                _record_maps_usage(
                    usage_ctx or maps_usage_ctx('maps', tenant_id=tenant_id),
                    'roads', 1)
                return {
                    'lat': loc['latitude'],
                    'lng': loc['longitude'],
                    'place_id': sp.get('placeId'),
                }
    except Exception as e:
        print(f"[ROADS API ERROR] {e}")
    return None


def _google_directions_route(origin_lat, origin_lng, destination_lat, destination_lng, tenant_id=None, usage_ctx=None):
    """Return Google Maps road geometry; never fall back to a third-party router."""
    if not _has_api_key():
        return None
    params = {
        'origin': f'{origin_lat},{origin_lng}',
        'destination': f'{destination_lat},{destination_lng}',
        'mode': 'driving',
        'alternatives': 'false',
        'language': 'ar',
        'region': 'sa',
        'key': _get_api_key(),
    }
    try:
        response = requests.get('https://maps.googleapis.com/maps/api/directions/json', params=params, timeout=15)
        data = response.json()
        if data.get('status') != 'OK' or not data.get('routes'):
            err_msg = data.get('error_message', '')
            print(f"[GOOGLE DIRECTIONS] {data.get('status', 'no route')} - {err_msg}")
            return None
        route = data['routes'][0]
        encoded = route.get('overview_polyline', {}).get('points')
        coordinates = _decode_polyline(encoded) if encoded else []
        if len(coordinates) < 2:
            return None
        if tenant_id:
            _record_maps_call(tenant_id)
        _record_maps_usage(
            usage_ctx or maps_usage_ctx('maps', tenant_id=tenant_id),
            'directions', 1)
        leg = (route.get('legs') or [{}])[0]
        distance = leg.get('distance') or {}
        duration = leg.get('duration_in_traffic') or leg.get('duration') or {}
        distance_meters = distance.get('value')
        duration_seconds = duration.get('value')
        return {
            'coords': coordinates,
            'summary': route.get('summary', ''),
            'distance_meters': distance_meters,
            'distance_km': round(distance_meters / 1000.0, 1) if distance_meters is not None else None,
            'duration_min': math.ceil(duration_seconds / 60) if duration_seconds is not None else None,
        }
    except Exception as error:
        print(f"[GOOGLE DIRECTIONS ERROR] {error}")
        return None


def _google_reverse_geocode_road(lat, lng, tenant_id=None, usage_ctx=None):
    """Ask Google which named road is nearest to a point used for an access route."""
    if not _has_api_key():
        return ''
    try:
        response = requests.get(
            'https://maps.googleapis.com/maps/api/geocode/json',
            params={'latlng': f'{lat},{lng}', 'key': _get_api_key(), 'language': 'ar'}, timeout=15
        )
        data = response.json()
        if data.get('status') != 'OK':
            return ''
        for result in data.get('results', []):
            for component in result.get('address_components', []):
                if 'route' in component.get('types', []):
                    if tenant_id:
                        _record_maps_call(tenant_id)
                    _record_maps_usage(
                        usage_ctx or maps_usage_ctx('geocode', tenant_id=tenant_id),
                        'geocode', 1)
                    return component.get('long_name') or ''
    except Exception as error:
        print(f"[GOOGLE ROAD NAME ERROR] {error}")
    return ''


def _fixed_road_probe_points(lat, lng, lat_step, lng_step):
    diagonal_lat = lat_step * 0.72
    diagonal_lng = lng_step * 0.72
    return [
        (lat + lat_step, lng),
        (lat - lat_step, lng),
        (lat, lng + lng_step),
        (lat, lng - lng_step),
        (lat + diagonal_lat, lng + diagonal_lng),
        (lat + diagonal_lat, lng - diagonal_lng),
        (lat - diagonal_lat, lng + diagonal_lng),
        (lat - diagonal_lat, lng - diagonal_lng),
    ]


def discover_nearby_roads(center_lat, center_lng, tenant_id=None, origin_lat=None, origin_lng=None, max_results=6,
                          lat_step=0.0018, lng_step=0.0024):
    """Return verified nearby road names from Google Roads + Directions."""
    route_origin_lat = origin_lat if origin_lat is not None else center_lat
    route_origin_lng = origin_lng if origin_lng is not None else center_lng
    roads_key = _discovery_cache_key(
        tenant_id, 'roads', route_origin_lat, route_origin_lng,
        extra=f"{max_results}:{lat_step}:{lng_step}")
    roads_hit = _discovery_cache_get(tenant_id, roads_key)
    if isinstance(roads_hit, list):
        return roads_hit
    probes = _fixed_road_probe_points(route_origin_lat, route_origin_lng, lat_step, lng_step)
    # The metering scope is thread-local, so capture it before the pool:
    # worker threads would otherwise bill with only the tenant fallback and
    # lose the flow/draft/presentation attribution.
    ambient_ctx = _current_maps_ctx()

    def fetch(probe):
        p_lat, p_lng = probe
        snapped = _snap_to_roads(p_lat, p_lng, tenant_id=tenant_id, usage_ctx=ambient_ctx)
        dest_lat = snapped['lat'] if snapped else p_lat
        dest_lng = snapped['lng'] if snapped else p_lng
        route = _google_directions_route(
            route_origin_lat, route_origin_lng, dest_lat, dest_lng, tenant_id=tenant_id,
            usage_ctx=ambient_ctx
        )
        if not route:
            return None
        name = (route.get('summary') or '').strip()
        if not name or re.search(r'[A-Za-z]', name):
            localized_name = _google_reverse_geocode_road(
                dest_lat, dest_lng, tenant_id=tenant_id, usage_ctx=ambient_ctx)
            if localized_name:
                name = localized_name
        name = name or 'طريق قريب'
        key = (snapped or {}).get('place_id') or name.casefold()
        distance_meters = route.get('distance_meters')
        if distance_meters is None:
            distance_meters = round(_distance_meters(route_origin_lat, route_origin_lng, dest_lat, dest_lng))
        distance_km = route.get('distance_km')
        if distance_km is None:
            distance_km = round(distance_meters / 1000.0, 1)
        duration_min = route.get('duration_min')
        return {
            'name': name,
            'lat': dest_lat,
            'lng': dest_lng,
            'distance_meters': distance_meters,
            'distance_km': distance_km,
            'distance_text': f'{distance_km} كم',
            'duration_min': duration_min,
            'duration_minutes': duration_min,
            'place_id': key,
        }

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        candidates = list(executor.map(fetch, probes))

    roads = []
    seen = set()
    for road in candidates:
        if not road or road['place_id'] in seen:
            continue
        seen.add(road['place_id'])
        roads.append(road)
        if len(roads) >= max(1, int(max_results)):
            break
    _discovery_cache_put(tenant_id, roads_key, roads, ttl_days=30)
    return roads


def access_probe_points(lat, lng):
    """Fixed points used to discover the access roads around a site.

    These must never depend on a regeneration seed: moving them snapped to different roads
    and produced a different set of street names on every regeneration of the same site.
    """
    return _fixed_road_probe_points(lat, lng, 0.0018, 0.0024)


_ROAD_NAME_PREFIXES = ('طريق', 'شارع', 'الطريق', 'الشارع', 'ش.', 'ش')


def _road_name_key(name):
    """Normalise a road name so the same road is not drawn twice under two spellings."""
    text = _strip_arabic_diacritics(name).strip()
    text = re.sub(r'[\u0623\u0625\u0622]', '\u0627', text)
    text = re.sub(r'[\u0649]', '\u064a', text)
    text = re.sub(r'[\u0629]', '\u0647', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    words = [word for word in text.split() if word not in _ROAD_NAME_PREFIXES]
    words = [word[2:] if word.startswith('ال') and len(word) > 3 else word for word in words]
    return ' '.join(words).casefold()


def is_same_road_name(first, second):
    """Two labels are the same road when one name is contained in the other.

    The entered list holds compound rows such as «الامير فيصل بن فهد والخليفة المهدي»
    beside «الامير فيصل بن فهد», so comparing keys for equality drew one street twice.
    """
    first_words = set(_road_name_key(first).split())
    second_words = set(_road_name_key(second).split())
    if not first_words or not second_words:
        return False
    return first_words <= second_words or second_words <= first_words


def match_known_road_name(discovered, known_names):
    """Return an approved label only when its normalized name matches Google's name."""
    discovered_key = _road_name_key(discovered)
    if not discovered_key:
        return ''
    discovered_words = set(discovered_key.split())
    candidates = []
    for index, candidate in enumerate(known_names or []):
        candidate_key = _road_name_key(candidate)
        if not candidate_key:
            continue
        if candidate_key == discovered_key:
            return str(candidate).strip()
        candidate_words = set(candidate_key.split())
        if discovered_words <= candidate_words or candidate_words <= discovered_words:
            difference = discovered_words ^ candidate_words
            if difference & {'غير', 'بدون', 'ليس'}:
                continue
            candidates.append((len(difference), index, str(candidate).strip()))
    return min(candidates)[2] if candidates else ''


def _approved_manual_road_paths(value, approved_names):
    """Validate manual geometry and keep only roads named in the approved main-road list."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if not isinstance(value, list):
        return []

    approved_by_key = {
        _road_name_key(name): name for name in approved_names or [] if _road_name_key(name)
    }
    paths = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized_names = normalize_access_road_names([item.get('name')])
        if len(normalized_names) != 1:
            continue
        approved_name = approved_by_key.get(_road_name_key(normalized_names[0]))
        if not approved_name:
            continue
        points = []
        for point in item.get('points') or []:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                point_lat = float(point[0])
                point_lng = float(point[1])
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(point_lat) and math.isfinite(point_lng)):
                continue
            if not (-90 <= point_lat <= 90 and -180 <= point_lng <= 180):
                continue
            points.append((point_lat, point_lng))
        if len(points) >= 2:
            paths.append((points, approved_name))
    return paths


def _draw_access_roads(image_path, center_lat, center_lng, zoom, scale=2, project_data=None, tenant_id=None,
                       origin_lat=None, origin_lng=None, allow_discovery=True):
    """Draw only approved main-road geometry and labels."""
    def _draw_road_label(draw, px, py, text, label_scale=1.0, font=None, bg_color=(37, 75, 102, 255), border_color=(240, 230, 210, 255)):
        label_scale = max(0.6, min(1.8, float(label_scale or 1)))
        if not font:
            font = _get_arabic_font(max(12, round(24 * label_scale)))

        reshaped_text = _reshape_arabic_text(text)
        bbox = draw.textbbox((0, 0), reshaped_text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        pad_x = max(7, round(12 * label_scale))
        pad_y = max(4, round(7 * label_scale))
        rect = [int(px - tw // 2 - pad_x), int(py - th // 2 - pad_y), int(px + tw // 2 + pad_x), int(py + th // 2 + pad_y)]

        draw.rounded_rectangle(rect, radius=max(5, round(8 * label_scale)), fill=bg_color, outline=border_color, width=2)
        draw.text((int(px - tw // 2), int(py - th // 2 - 2)), reshaped_text, fill='#FFFFFF', font=font)

    def _offset_label_point(point, route_segment, img_w, img_h, distance=52):
        px, py = point
        if len(route_segment) < 2:
            return px, py
        nearest_index = min(range(len(route_segment)), key=lambda index: (route_segment[index][0] - px) ** 2 + (route_segment[index][1] - py) ** 2)
        previous_point = route_segment[max(0, nearest_index - 1)]
        next_point = route_segment[min(len(route_segment) - 1, nearest_index + 1)]
        dx = next_point[0] - previous_point[0]
        dy = next_point[1] - previous_point[1]
        length = math.hypot(dx, dy) or 1
        ox = -dy / length * distance
        oy = dx / length * distance
        candidates = [(px + ox, py + oy), (px - ox, py - oy)]
        for candidate_x, candidate_y in candidates:
            if 90 <= candidate_x <= img_w - 90 and 60 <= candidate_y <= img_h - 60:
                return int(candidate_x), int(candidate_y)
        return px, py

    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        cx, cy = img_w // 2, img_h // 2
        overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        gold_color = (212, 163, 89, 180) # Premium gold/bronze color matching branding
        
        # main_roads is the authoritative approval list. Secondary roads and
        # unmatched Google route names must never be introduced into this view.
        route_origin_lat = origin_lat if origin_lat is not None else center_lat
        route_origin_lng = origin_lng if origin_lng is not None else center_lng
        approved_road_names = normalize_access_road_names(
            (project_data or {}).get('main_roads')
        )
        road_data = (project_data or {}).get('main_roads_data')
        if isinstance(road_data, str):
            try:
                road_data = json.loads(road_data)
            except (TypeError, ValueError):
                road_data = []
        manual_road_keys = {
            _road_name_key(item.get('name')) for item in (road_data if isinstance(road_data, list) else [])
            if isinstance(item, dict) and item.get('row_source') == 'manual'
        }
        discoverable_road_names = [name for name in approved_road_names if _road_name_key(name) not in manual_road_keys]

        # Manual geometry is already reviewed by the user, but its label must still
        # match a normalized main-road name. The provided point sequence is kept intact.
        road_route_mapping = _approved_manual_road_paths(
            (project_data or {}).get('manual_road_paths'), approved_road_names
        )
        seen_road_keys = {name for _, name in road_route_mapping}
        if not allow_discovery:
            for stored_path in _approved_manual_road_paths(
                (project_data or {}).get('access_roads_data'), approved_road_names
            ):
                if not any(is_same_road_name(stored_path[1], accepted) for accepted in seen_road_keys):
                    road_route_mapping.append(stored_path)
                    seen_road_keys.add(stored_path[1])
        label_positions = (project_data or {}).get('access_road_label_positions') or {}
        if isinstance(label_positions, str):
            try:
                label_positions = json.loads(label_positions)
            except (TypeError, ValueError):
                label_positions = {}
        position_by_key = {}
        if isinstance(label_positions, dict):
            for name, point in label_positions.items():
                try:
                    if isinstance(point, (list, tuple)) and len(point) >= 2:
                        position_by_key[_road_name_key(name)] = (float(point[0]), float(point[1]))
                except (TypeError, ValueError):
                    continue
        label_sizes = (project_data or {}).get('access_road_label_sizes') or {}
        if isinstance(label_sizes, str):
            try:
                label_sizes = json.loads(label_sizes)
            except (TypeError, ValueError):
                label_sizes = {}
        size_by_key = {}
        if isinstance(label_sizes, dict):
            for name, value in label_sizes.items():
                try:
                    size_by_key[_road_name_key(name)] = max(0.6, min(1.8, float(value)))
                except (TypeError, ValueError):
                    continue

        # Find actual nearby access roads through Google Roads + Directions.
        # The probes are fixed on purpose. They used to be shifted and rotated by regen_seed,
        # so every regeneration snapped to different roads and the map came back with a
        # different set of street names for the same site.
        probe_points = access_probe_points(route_origin_lat, route_origin_lng)
        targeted_probes = []
        for item in road_data if isinstance(road_data, list) else []:
            if not isinstance(item, dict) or item.get('row_source') == 'manual':
                continue
            expected_name = match_known_road_name(item.get('name'), discoverable_road_names)
            try:
                road_lat = float(item.get('lat'))
                road_lng = float(item.get('lng'))
            except (TypeError, ValueError):
                continue
            if expected_name and math.isfinite(road_lat) and math.isfinite(road_lng):
                targeted_probes.append(((road_lat, road_lng), expected_name))
        probe_entries = targeted_probes + [(point, None) for point in probe_points]

        def _fetch_probe_route(entry):
            probe, expected_name = entry
            p_lat, p_lng = probe
            snapped = _snap_to_roads(p_lat, p_lng, tenant_id=tenant_id)
            dest_lat = snapped['lat'] if snapped else p_lat
            dest_lng = snapped['lng'] if snapped else p_lng
            route = _google_directions_route(
                route_origin_lat, route_origin_lng, dest_lat, dest_lng, tenant_id=tenant_id
            )
            if not route:
                return None

            discovered_name = (route.get('summary') or '').strip()
            if not discovered_name or re.search(r'[A-Za-z]', discovered_name):
                localized_name = _google_reverse_geocode_road(
                    dest_lat, dest_lng, tenant_id=tenant_id
                )
                if localized_name:
                    discovered_name = localized_name
            candidates = [expected_name] if expected_name else discoverable_road_names
            approved_name = match_known_road_name(discovered_name, candidates)
            if not approved_name:
                return None
            return route['coords'], approved_name, _road_name_key(approved_name)

        remaining_approved_names = [
            name for name in discoverable_road_names
            if not any(is_same_road_name(name, accepted) for accepted in seen_road_keys)
        ]
        probe_results = []
        if allow_discovery and remaining_approved_names:
            print("[ACCESS ROADS] Discovering approved nearby roads through Google Maps APIs...")
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, max(1, len(probe_entries)))) as executor:
                probe_results = list(executor.map(_fetch_probe_route, probe_entries))

        for result in probe_results:
            if not result:
                continue
            if any(is_same_road_name(result[1], accepted) for accepted in seen_road_keys):
                continue
            seen_road_keys.add(result[1])
            road_route_mapping.append((result[0], result[1]))
        print(f"[ACCESS ROADS] labels: {[name for _, name in road_route_mapping]}")

        # 3. Draw routes and labels. Highlights first, names last so the gold
        # stroke never covers the road name.
        placed_label_rects = []  # track (x1,y1,x2,y2) of placed labels to avoid overlap
        pending_labels = []
        rendered_roads = []

        if road_route_mapping:
            origin_dx, origin_dy = _latlng_to_pixel_offset(
                route_origin_lat, route_origin_lng, center_lat, center_lng, zoom, scale=scale
            )
            origin_px, origin_py = cx + origin_dx, cy + origin_dy

            for coords, label_text in road_route_mapping:
                pixels = []
                for lat, lng in coords:
                    dx, dy = _latlng_to_pixel_offset(lat, lng, center_lat, center_lng, zoom, scale=scale)
                    pixels.append((int(cx + dx), int(cy + dy)))

                segments = []
                current_segment = []
                for point in pixels:
                    inside = -40 <= point[0] <= img_w + 40 and -40 <= point[1] <= img_h + 40
                    if inside:
                        current_segment.append(point)
                    elif len(current_segment) >= 2:
                        segments.append(current_segment)
                        current_segment = []
                    else:
                        current_segment = []
                if len(current_segment) >= 2:
                    segments.append(current_segment)
                if not segments:
                    continue

                # Draw thick gold road line
                for segment in segments:
                    draw.line(segment, fill=(105, 73, 35, 125), width=18)
                    draw.line(segment, fill=gold_color, width=9)

                route_segment = max(segments, key=len)
                pending_labels.append((route_segment, label_text, coords))

            img = Image.alpha_composite(img, overlay)
            labels_overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
            labels_draw = ImageDraw.Draw(labels_overlay)
            for route_segment, label_text, route_coords in pending_labels:
                best_p = None
                label_key = _road_name_key(label_text)
                label_point = position_by_key.get(label_key)
                label_scale = size_by_key.get(label_key, 1.0)
                if label_point:
                    label_dx, label_dy = _latlng_to_pixel_offset(
                        label_point[0], label_point[1], center_lat, center_lng, zoom, scale=scale
                    )
                    candidate = (int(cx + label_dx), int(cy + label_dy))
                    if 60 <= candidate[0] <= img_w - 60 and 40 <= candidate[1] <= img_h - 40:
                        best_p = candidate
                preferred_candidates = []
                visible_candidates = []
                for p in route_segment:
                    distance = math.sqrt((p[0] - origin_px) ** 2 + (p[1] - origin_py) ** 2)
                    if 90 <= p[0] <= img_w - 90 and 60 <= p[1] <= img_h - 60:
                        visible_candidates.append((distance, p))
                        if distance >= 120:
                            preferred_candidates.append((distance, p))
                candidates = preferred_candidates or visible_candidates
                candidates.sort(key=lambda candidate: -candidate[0])

                label_half_width = min(300, max(70, len(label_text or '') * 7 * label_scale))
                if best_p is None:
                    for _, point in candidates:
                        offset_point = _offset_label_point(point, route_segment, img_w, img_h)
                        lx1 = offset_point[0] - label_half_width
                        ly1 = offset_point[1] - 30
                        lx2 = offset_point[0] + label_half_width
                        ly2 = offset_point[1] + 30
                        collision = any(
                            not (lx2 < rx1 or lx1 > rx2 or ly2 < ry1 or ly1 > ry2)
                            for rx1, ry1, rx2, ry2 in placed_label_rects
                        )
                        if not collision:
                            best_p = offset_point
                            placed_label_rects.append((lx1, ly1, lx2, ly2))
                            break

                if best_p and label_text:
                    _draw_road_label(labels_draw, best_p[0], best_p[1], label_text, label_scale=label_scale)
                    label_point = _pixel_to_latlng(
                        best_p[0], best_p[1], img_w, img_h, center_lat, center_lng, zoom, scale=scale
                    )
                rendered_roads.append({
                    'name': label_text,
                    'points': [[point[0], point[1]] for point in route_coords],
                    'label_point': list(label_point) if label_point else None,
                    'label_scale': label_scale,
                })

            img = Image.alpha_composite(img, labels_overlay)
            img.save(image_path, 'PNG')
            print("[ACCESS ROADS] Successfully drew approved road routes")
            return rendered_roads

        # Never invent a schematic road grid when there is no approved geometry.
        print("[ACCESS ROADS] No approved road route available; leaving the base map unchanged")
        return False
    except Exception as e:
        print(f"[DRAW ACCESS ROADS ERROR] {e}")
        return False
