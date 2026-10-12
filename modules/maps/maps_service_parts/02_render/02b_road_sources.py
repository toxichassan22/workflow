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


def _google_directions_route(origin_lat, origin_lng, destination_lat, destination_lng, tenant_id=None, usage_ctx=None, language='ar'):
    """Return Google Maps road geometry; never fall back to a third-party router."""
    if not _has_api_key():
        return None
    params = {
        'origin': f'{origin_lat},{origin_lng}',
        'destination': f'{destination_lat},{destination_lng}',
        'mode': 'driving',
        'alternatives': 'false',
        'language': _lang_norm(language),
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


def _google_reverse_geocode_road(lat, lng, tenant_id=None, usage_ctx=None, language='ar'):
    """Ask Google which named road is nearest to a point used for an access route."""
    if not _has_api_key():
        return ''
    try:
        response = requests.get(
            'https://maps.googleapis.com/maps/api/geocode/json',
            params={'latlng': f'{lat},{lng}', 'key': _get_api_key(), 'language': _lang_norm(language)}, timeout=15
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
                          lat_step=0.0018, lng_step=0.0024, language='ar'):
    """Return verified nearby road names from Google Roads + Directions."""
    language = _lang_norm(language)
    route_origin_lat = origin_lat if origin_lat is not None else center_lat
    route_origin_lng = origin_lng if origin_lng is not None else center_lng
    roads_key = _discovery_cache_key(
        tenant_id, 'roads', route_origin_lat, route_origin_lng,
        extra=f"{max_results}:{lat_step}:{lng_step}:{language}")
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
            usage_ctx=ambient_ctx, language=language
        )
        if not route:
            return None
        name = (route.get('summary') or '').strip()
        # The summary should already arrive in the requested language; when it
        # still comes back in the other script, re-geocode for a localized name.
        wrong_script = bool(_ARABIC_CHAR_RE.search(name)) if language == 'en' else bool(re.search(r'[A-Za-z]', name))
        if not name or wrong_script:
            localized_name = _google_reverse_geocode_road(
                dest_lat, dest_lng, tenant_id=tenant_id, usage_ctx=ambient_ctx, language=language)
            if localized_name:
                name = localized_name
        name = name or ('Nearby road' if language == 'en' else 'طريق قريب')
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
            'distance_text': f'{distance_km} {_distance_unit(language)}',
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


_ROAD_NAME_PREFIXES = ('طريق', 'شارع', 'الطريق', 'الشارع', 'ش.', 'ش',
                       'road', 'rd', 'street', 'st', 'highway', 'hwy', 'avenue', 'ave',
                       'boulevard', 'blvd', 'drive', 'dr', 'lane', 'route', 'corridor')


def is_road_name(value):
    """A landmark label that names a road rather than a point place.

    Arabic names carry the word first («طريق الملك عبدالعزيز») while English
    ones trail it («King Fahd Road»), so both ends count.
    """
    text = re.sub(r'\s+', ' ', str(value or '').strip().casefold())
    return any(
        text == prefix or text.startswith(prefix + ' ') or text.endswith(' ' + prefix)
        for prefix in _ROAD_NAME_PREFIXES)


def _road_name_key(name):
    """Normalise a road name so the same road is not drawn twice under two spellings."""
    text = _strip_arabic_diacritics(name).strip()
    text = re.sub(r'[\u0623\u0625\u0622]', '\u0627', text)
    text = re.sub(r'[\u0649]', '\u064a', text)
    text = re.sub(r'[\u0629]', '\u0647', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    words = [word for word in text.split() if word.casefold() not in _ROAD_NAME_PREFIXES]
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


