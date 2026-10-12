

def _get_drive_matrix_chunk(origin, destinations, usage_ctx=None, language='ar'):
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

    language = _lang_norm(language)
    matrix_tenant = usage_ctx.get('tenant_id') if isinstance(usage_ctx, dict) else None
    matrix_key = _discovery_cache_key(
        matrix_tenant, 'matrix', None, None,
        extra=f"{origin_str}|{'|'.join(points)}|{language}")
    matrix_hit = _discovery_cache_get(matrix_tenant, matrix_key)
    if isinstance(matrix_hit, list) and len(matrix_hit) == len(points):
        return matrix_hit

    url = 'https://maps.googleapis.com/maps/api/distancematrix/json'
    params = {
        'origins': origin_str,
        'destinations': '|'.join(points),
        'mode': 'driving',
        'language': language,
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
                'distance_text': f"{distance_km} {_distance_unit(language)}" if distance_km is not None else None,
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
            
            overlay_draw.polygon(pixel_points, fill=fill_color)
            overlay_draw.line(pixel_points + [pixel_points[0]], fill=border_color,
                              width=max(1, round(6.5 * img_w / 1000.0)), joint='curve')
        else:
            # Priority 3: Compact exact-point halo when no building polygon exists
            unit = img_w / 1000.0
            r = 10 * unit
            overlay_draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(160, 50, 50, 45), outline=border_color, width=max(1, round(3 * unit)))
            overlay_draw.line([(cx - r - 2 * unit, cy), (cx + r + 2 * unit, cy)], fill=(255, 255, 255, 180), width=max(1, round(unit)))
            overlay_draw.line([(cx, cy - r - 2 * unit), (cx, cy + r + 2 * unit)], fill=(255, 255, 255, 180), width=max(1, round(unit)))

        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[SITE HIGHLIGHT ERROR] {e}")
        return False


