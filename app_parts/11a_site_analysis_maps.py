


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Site analysis and map endpoints: geocoding and OSM polygon lookup,
# nearby-landmark discovery, the map-preview data feed, satellite site-field
# collection, /api/analyze-site and /api/site-analysis, and the
# single/batch map-image generation routes including presentation map
# regeneration.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@app.route('/api/geocode', methods=['POST'])
@require_auth
def api_geocode():
    """Geocode an address or Google Maps link to lat/lng."""
    data = request.json or {}
    address = data.get('address', '').strip()
    maps_link = data.get('maps_link', '').strip()

    if not address and not maps_link:
        return jsonify({'error': 'رابط Google Maps مطلوب لتحديد موقع المشروع'}), 400

    query = maps_link or address
    if not query.startswith('http'):
        return jsonify({'error': 'موقع المشروع يجب أن يكون رابط Google Maps'}), 400

    if query.startswith('http'):
        coords = maps_service.extract_coords_from_maps_link(query)
        if coords:
            print(f"[MAPS LINK] Extracted coords from link: {coords}")
            place = maps_service.reverse_geocode_location(
                coords['lat'], coords['lng'], tenant_id=g.tenant_id, language='ar',
                usage_ctx=maps_service.maps_usage_ctx('geocode', g.tenant_id, data=data)
            ) or {}
            names = market_study.extract_city_district(
                place.get('address_components') or [],
                place.get('formatted_address') or '',
            )
            return jsonify({
                'success': True,
                'lat': coords['lat'],
                'lng': coords['lng'],
                'formatted_address': place.get('formatted_address') or (
                    address if (address and not address.startswith('http')) else 'تم الاستخراج من رابط خرائط جوجل'
                ),
                'city': names.get('city') or '',
                'district': names.get('district') or '',
                'source': 'maps_link'
            })

    return jsonify({'success': False, 'error': 'رابط Google Maps غير صالح أو لا يحتوي على إحداثيات'})


@app.route('/api/debug-osm-polygon', methods=['GET'])
@require_auth
def api_debug_osm_polygon():
    try:
        lat = float(request.args.get('lat'))
        lng = float(request.args.get('lng'))
    except (TypeError, ValueError):
        return jsonify({'error': 'lat and lng are required'}), 400
    radius = int(request.args.get('radius', 400))
    maps_service._osm_polygon_cache.clear()
    coords = maps_service._fetch_osm_polygon(lat, lng, radius_m=radius)
    if not coords:
        return jsonify({'found': False, 'lat': lat, 'lng': lng, 'radius_m': radius})
    return jsonify({
        'found': True,
        'points': len(coords),
        'area_sqm': round(maps_service._approx_polygon_area_sqm(coords)),
        'coords': coords,
    })


@app.route('/api/nearby-landmarks', methods=['POST'])
@require_auth
def api_nearby_landmarks():
    """Get nearby landmarks for given coordinates."""
    data = request.json or {}
    lat = data.get('lat')
    lng = data.get('lng')
    radius = data.get('radius', 20000)
    if lat is None or lng is None:
        return jsonify({'error': 'lat and lng are required'}), 400
    result = maps_service.get_nearby_landmarks(float(lat), float(lng), int(radius), max_results=int(data.get('maxResults', 20)), include_all=True, usage_ctx=maps_service.maps_usage_ctx('places', g.tenant_id, data=data))
    status = 502 if result.get('error') and not result.get('success') else 200
    return jsonify(result), status


@app.route('/api/preview-map-data', methods=['POST'])
@require_auth
def api_preview_map_data():
    """Preview calculated landmarks, drive matrix times, distances, and catchment zones before generation."""
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))

    lat = maps_service._extract_coordinate(
        project_data.get('location_lat') or project_data.get('locationLat') or
        project_data.get('latitude') or project_data.get('lat')
    )
    lng = maps_service._extract_coordinate(
        project_data.get('location_lng') or project_data.get('locationLng') or
        project_data.get('longitude') or project_data.get('lng')
    )

    if lat is None or lng is None:
        address = project_data.get('location_address') or project_data.get('location', '')
        if address and not address.startswith('http'):
            geo = maps_service.geocode_address(address, tenant_id=g.tenant_id, usage_ctx=maps_service.maps_usage_ctx('geocode', g.tenant_id, data=data))
            if geo.get('success'):
                lat = geo['lat']
                lng = geo['lng']

    if lat is None or lng is None:
        return jsonify({'success': False, 'error': 'لم يتم العثور على إحداثيات للموقع'}), 400

    landmark_radius_m = 20000
    selected_landmarks = data.get('selectedLandmarks')
    custom_text = project_data.get('nearby_landmarks') or project_data.get('landmarks_text')
    landmarks = selected_landmarks if isinstance(selected_landmarks, list) else (
        maps_service._parse_landmarks_text(custom_text) if isinstance(custom_text, str) else (custom_text or [])
    )
    landmarks_error = None
    landmarks_warning = None

    if not landmarks:
        places = maps_service.get_nearby_landmarks(lat, lng, radius=landmark_radius_m, max_results=20, include_all=True, usage_ctx=maps_service.maps_usage_ctx('places', g.tenant_id, data=data))
        if places.get('success'):
            landmarks = places['landmarks']
            if not landmarks:
                landmarks_warning = 'لم تُرجع Google Places أي معالم ضمن نطاق 20 كم من الموقع'
        else:
            landmarks_error = places.get('error') or 'تعذر جلب المعالم من Google Places'

    location_context = project_data.get('location_detail') or project_data.get('location_address') or project_data.get('location', '')
    for lm in landmarks:
        if lm.get('lat') is None or lm.get('lng') is None:
            query = f"{lm['name']}, {location_context}" if location_context else lm['name']
            geo = maps_service.geocode_address(query, tenant_id=g.tenant_id, usage_ctx=maps_service.maps_usage_ctx('geocode', g.tenant_id, data=data))
            if geo.get('success'):
                lm['lat'] = geo['lat']
                lm['lng'] = geo['lng']

    filtered_landmarks = []
    for lm in landmarks:
        if lm.get('lat') is None or lm.get('lng') is None:
            lm['location_status'] = 'unresolved'
            filtered_landmarks.append(lm)
            continue
        dist_m = maps_service._distance_meters(lat, lng, lm['lat'], lm['lng'])
        if dist_m < 50 or dist_m > landmark_radius_m:
            continue
        lm['distance_meters'] = round(dist_m)
        filtered_landmarks.append(lm)

    landmarks = sorted(filtered_landmarks, key=lambda item: item.get('distance_meters', float('inf')))

    geocoded = [lm for lm in landmarks if lm.get('lat') is not None and lm.get('lng') is not None]
    matrix = []
    if data.get('calculateDriving') and geocoded:
        matrix = maps_service.get_drive_matrix((lat, lng), geocoded, usage_ctx=maps_service.maps_usage_ctx('matrix', g.tenant_id, data=data))
        for i, lm in enumerate(geocoded):
            if i < len(matrix) and matrix[i]:
                entry = matrix[i]
                lm['duration_minutes'] = entry.get('duration_min')
                lm['distance_km'] = entry.get('distance_km')
                lm['distance_text'] = f"{entry.get('distance_km')} كم" if entry.get('distance_km') else None

    catchment_text = project_data.get('catchment_areas') or project_data.get('catchment_zones')
    zones = maps_service._parse_catchment_zones(catchment_text) if isinstance(catchment_text, str) else catchment_text

    if landmarks_error:
        return jsonify({
            'success': False,
            'error': landmarks_error,
            'error_code': 'NEARBY_LANDMARKS_UNAVAILABLE',
            'lat': lat,
            'lng': lng,
            'landmarks': [],
        }), 503

    return jsonify({
        'success': True,
        'lat': lat,
        'lng': lng,
        'landmarks': landmarks,
        'landmarks_matrix': matrix or landmarks,
        'catchment_zones': zones,
        'warning': landmarks_warning,
    })


def _map_image_point_to_coords(x, y, width, height, center_lat, center_lng, zoom, scale=2):
    """Convert normalized image coordinates to WGS84 using Web Mercator."""
    world = 256 * (2 ** zoom) * scale
    center_x = (center_lng + 180.0) / 360.0 * world
    center_lat_rad = math.radians(center_lat)
    center_y = (1.0 - math.log(math.tan(math.pi / 4.0 + center_lat_rad / 2.0)) / math.pi) / 2.0 * world
    target_x = center_x + (float(x) - 0.5) * width
    target_y = center_y + (float(y) - 0.5) * height
    lng = target_x / world * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * target_y / world))))
    return lat, lng


def _estimate_site_polygon_from_satellite(image_path, center_lat, center_lng, zoom, usage_ctx=None):
    """Ask the vision model for a conservative building-only polygon estimate."""
    vision_ctx = usage_ctx or _usage_ctx('site')
    if _tenant_key_gate(vision_ctx) is not None:
        return None
    if not _has_any_openrouter_key(vision_ctx) or not image_path or not os.path.isfile(image_path):
        return None
    site_attempt_id = _begin_ai_attempt_record(vision_ctx, GEMINI_TEXT_MODEL)
    try:
        from reference_analyzer import encode_image_to_base64
        from PIL import Image
        image_uri = encode_image_to_base64(image_path)
        prompt = (
            'Analyze this satellite map image. The target site is at the exact image center. '
            'Identify only the footprint of the building or compound directly at the center; '
            'do not select roads, highways, interchanges, districts, empty land, airport areas, '
            'or any nearby polygon. Return JSON only: '
            '{"confidence":0.0,"points":[{"x":0.0,"y":0.0}]} where x and y are normalized '
            'image coordinates between 0 and 1. Return an empty points array if no building footprint '
            'can be identified with confidence >= 0.65.'
        )
        response = requests.post(
            f'{OPENROUTER_BASE}/chat/completions',
            headers=_openrouter_headers(vision_ctx, title='Real Estate Proposal Generator - Site Boundary'),
            json={
                'model': GEMINI_TEXT_MODEL,
                'messages': [{'role': 'user', 'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url', 'image_url': {'url': image_uri}},
                ]}],
                'modalities': ['text'],
                'max_tokens': 1200,
            },
            timeout=90,
        )
        payload = response.json()
        generation_id, vision_usage = _extract_openrouter_usage(payload)
        _settle_ai_attempt_record(
            site_attempt_id,
            'ok' if response.status_code < 400 and 'error' not in payload else 'error',
            vision_usage, generation_id)
        content = payload.get('choices', [{}])[0].get('message', {}).get('content', '')
        if isinstance(content, list):
            content = ' '.join(str(part.get('text', '')) if isinstance(part, dict) else str(part) for part in content)
        match = re.search(r'\{[\s\S]*\}', content or '')
        if not match:
            return None
        result = json.loads(match.group())
        confidence = float(result.get('confidence', 0) or 0)
        raw_points = result.get('points') or []
        if confidence < 0.65 or len(raw_points) < 3 or len(raw_points) > 40:
            return None
        with Image.open(image_path) as image:
            width, height = image.size
        normalized = []
        for point in raw_points:
            if not isinstance(point, dict):
                return None
            x, y = float(point.get('x')), float(point.get('y'))
            if not (0 <= x <= 1 and 0 <= y <= 1):
                return None
            normalized.append(_map_image_point_to_coords(x, y, width, height, center_lat, center_lng, zoom))
        if not maps_service._point_in_polygon(center_lat, center_lng, normalized):
            return None
        area = maps_service._approx_polygon_area_sqm(normalized)
        if area < 20 or area > 100000:
            return None
        return normalized
    except requests.exceptions.Timeout:
        print('[SITE BOUNDARY VISION] OpenRouter timeout')
        _settle_ai_attempt_record(site_attempt_id, 'error', {}, None)
        return None
    except requests.exceptions.ConnectionError as error:
        print(f'[SITE BOUNDARY VISION] {error}')
        _settle_ai_attempt_record(site_attempt_id, 'error', {}, None)
        return None
    except Exception as error:
        print(f'[SITE BOUNDARY VISION] {error}')
        try:
            _settle_ai_attempt_record(site_attempt_id, 'error', {}, None)
        except Exception:
            pass
        return None


def _collect_site_fields(project_data, tenant_id, lat, lng):
    """Gather site fields (landmarks, roads, population, polygon) from Google/BigQuery data.

    Does not generate map images.  Used by analyze-site and site-analysis so they
    share the same data sources.
    """

    def landmark_lines(items, matrix=None):
        matrix = matrix or []
        lines = []
        for index, item in enumerate(items or []):
            name = item.get('name') or item.get('displayName') or ''
            if not name:
                continue
            drive = matrix[index] if index < len(matrix) and isinstance(matrix[index], dict) else {}
            distance = drive.get('distance_text') or item.get('distance_text')
            duration = drive.get('duration_min') or item.get('duration_minutes')
            category = item.get('category')
            details = []
            if category:
                details.append(str(category))
            if distance:
                details.append(str(distance))
            if duration:
                details.append(f'{duration} دقيقة')
            lines.append(f"{name} - {' - '.join(details)}" if details else name)
        return '\n'.join(lines)

    def enrich_road_metrics(items):
        if not items or all(item.get('distance_text') and item.get('duration_minutes') for item in items):
            return
        matrix = maps_service.get_drive_matrix((lat, lng), items)
        for index, item in enumerate(items):
            if index >= len(matrix) or not isinstance(matrix[index], dict):
                continue
            entry = matrix[index]
            item['distance_text'] = entry.get('distance_text') or item.get('distance_text')
            item['distance_km'] = entry.get('distance_km') or item.get('distance_km')
            item['duration_min'] = entry.get('duration_min') or item.get('duration_min')
            item['duration_minutes'] = entry.get('duration_min') or item.get('duration_minutes')

    nearby = maps_service.get_nearby_landmarks(lat, lng, radius=20000, max_results=20, include_all=True)
    nearby_items = nearby.get('landmarks', []) if nearby.get('success') else []
    nearby_error = nearby.get('error') if not nearby.get('success') else None
    nearby_warning = 'لم تُرجع Google Places أي معالم ضمن نطاق 20 كم من الموقع' if nearby.get('success') and not nearby_items else None
    nearby_matrix = maps_service.get_drive_matrix((lat, lng), nearby_items) if nearby_items else []
    for index, item in enumerate(nearby_items):
        if index >= len(nearby_matrix) or not isinstance(nearby_matrix[index], dict):
            continue
        entry = nearby_matrix[index]
        item['distance_km'] = entry.get('distance_km') or item.get('distance_km')
        item['distance_text'] = entry.get('distance_text') or item.get('distance_text')
        item['duration_min'] = entry.get('duration_min') or item.get('duration_min')
        item['duration_minutes'] = entry.get('duration_min') or item.get('duration_minutes')

    curated_city = maps_service.detect_curated_city(lat, lng, tenant_id=tenant_id)
    city_error = None
    city_warning = None
    if curated_city:
        city_items = maps_service.get_curated_city_landmarks(lat=lat, lng=lng, city=curated_city, tenant_id=tenant_id)
    else:
        city = maps_service.get_nearby_landmarks(lat, lng, radius=5000, max_results=20, include_all=True)
        city_items = city.get('landmarks', []) if city.get('success') else []
        city_error = city.get('error') if not city.get('success') else None
        existing_city_names = {item.get('name', '').casefold() for item in city_items}
        city_items.extend(
            item for item in maps_service.get_nearest_category_landmarks(lat, lng, radius=20000, tenant_id=tenant_id)
            if item.get('name', '').casefold() not in existing_city_names
        )
    if not city_items and not city_error:
        city_warning = 'لم تُرجع Google Places أي معالم للمدينة ضمن النطاق المحدد'
    # One Google discovery per analysis: the main and secondary road lists are
    # split locally from the same probes instead of paying for a second
    # 8-probe discovery. Previously every analysis burned ~16 Roads plus
    # ~16 Directions calls here alone.
    all_roads = maps_service.discover_nearby_roads(lat, lng, tenant_id=tenant_id, max_results=10)
    enrich_road_metrics(all_roads)
    roads = all_roads[:6]

    polygon = None
    raw_polygon = project_data.get('location_polygon')
    if isinstance(raw_polygon, str):
        try:
            polygon = [
                (float(lat_value.strip()), float(lng_value.strip()))
                for point in raw_polygon.split(';') if ',' in point
                for lat_value, lng_value in [point.split(',', 1)]
            ]
            if len(polygon) < 3:
                polygon = None
        except (TypeError, ValueError):
            polygon = None
    if not polygon:
        polygon = maps_service._fetch_osm_polygon(lat, lng, radius_m=180)

    population = population_service.get_population_density(lat, lng)
    location_details = maps_service.reverse_geocode_location(lat, lng, tenant_id=tenant_id, language='en')
    arabic_location = maps_service.reverse_geocode_location(lat, lng, tenant_id=tenant_id, language='ar') or {}
    place_names = market_study.extract_city_district(
        arabic_location.get('address_components') or location_details.get('address_components') or [],
        arabic_location.get('formatted_address') or location_details.get('formatted_address') or '',
    )
    fields = {
        'location_lat': lat,
        'location_detail': arabic_location.get('formatted_address') or location_details.get('formatted_address', ''),
        'location_lng': lng,
        'nearby_landmarks': landmark_lines(nearby_items, nearby_matrix),
        'city_landmarks': landmark_lines(city_items),
    }
    if place_names.get('city') and not str(project_data.get('city') or '').strip():
        fields['city'] = place_names['city']
    if place_names.get('district') and not str(project_data.get('district') or '').strip():
        fields['district'] = place_names['district']
    if population.get('available'):
        fields['population_density'] = f"{population['value']} {population.get('unit', 'نسمة/كم²')}"
        fields['population_density_source'] = population.get('source')
    road_names = []
    for road in roads:
        name = road.get('name')
        if name and name not in road_names:
            road_names.append(name)
    road_names = maps_service.normalize_access_road_names(road_names)
    if road_names:
        fields['main_roads'] = '\n'.join(road_names)

    city_matrix = maps_service.get_drive_matrix((lat, lng), city_items) if city_items else []
    for index, item in enumerate(city_items):
        if index < len(city_matrix) and isinstance(city_matrix[index], dict):
            if city_matrix[index].get('duration_min') is not None:
                item['duration_minutes'] = city_matrix[index].get('duration_min')
            if city_matrix[index].get('distance_text'):
                item['distance_text'] = city_matrix[index].get('distance_text')
    fields['city_landmarks'] = landmark_lines(city_items, city_matrix)
    catchment_lines = []
    for item in city_items:
        name = item.get('name')
        duration = item.get('duration_minutes')
        if not name:
            continue
        parts = [name]
        if item.get('category'):
            parts.append(str(item['category']))
        if item.get('distance_text'):
            parts.append(str(item['distance_text']))
        if duration is not None:
            parts.append(f'{duration} دقائق')
        catchment_lines.append(' — '.join(parts))
    if catchment_lines:
        fields['catchment_areas'] = '\n'.join(catchment_lines)

    if polygon:
        fields['location_polygon'] = ';'.join(f'{point[0]:.6f},{point[1]:.6f}' for point in polygon)

    diagnostics = {
        'nearby_landmarks_error': nearby_error,
        'nearby_landmarks_warning': nearby_warning,
        'city_landmarks_error': city_error,
        'city_landmarks_warning': city_warning,
    }
    return fields, nearby_items, nearby_matrix, city_items, city_matrix, roads, polygon, diagnostics


@app.route('/api/analyze-site', methods=['POST'])
@require_permission('create_presentation')
def api_analyze_site():
    """Resolve and enrich site data without generating map images."""
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    _billing_guard = _require_billing_balance('analyze_site')
    if _billing_guard is not None:
        return _billing_guard
    if data.get('generateMaps') is True:
        return jsonify({
            'success': False,
            'error': 'توليد الخرائط متاح لكل خريطة على حدة بعد اعتماد تحليل الموقع',
            'error_code': 'INDIVIDUAL_MAP_GENERATION_REQUIRED',
        }), 400
    address = project_data.get('location_address') or project_data.get('location') or ''
    link = address if isinstance(address, str) and address.startswith('http') else (
        project_data.get('location_maps_link') or project_data.get('maps_link')
    )
    if not isinstance(link, str) or not link.startswith('http'):
        return jsonify({'success': False, 'error': 'موقع المشروع يجب أن يكون رابط Google Maps'}), 400
    coords = maps_service.extract_coords_from_maps_link(link)
    if coords:
        lat, lng = coords['lat'], coords['lng']
        source = 'maps_link'
    elif link:
        return jsonify({'success': False, 'error': 'تعذر استخراج الإحداثيات من رابط Google Maps'}), 400
    else:
        lat = maps_service._extract_coordinate(
            project_data.get('location_lat') or project_data.get('locationLat') or
            project_data.get('latitude') or project_data.get('lat')
        )
        lng = maps_service._extract_coordinate(
            project_data.get('location_lng') or project_data.get('locationLng') or
            project_data.get('longitude') or project_data.get('lng')
        )
        source = 'existing_coordinates'
        if (lat is None or lng is None) and address and not str(address).startswith('http'):
            geo = maps_service.geocode_address(address, tenant_id=g.tenant_id, usage_ctx=maps_service.maps_usage_ctx('site', g.tenant_id, data=data))
            if geo.get('success'):
                lat, lng = geo['lat'], geo['lng']
                source = 'geocoding'

    if lat is None or lng is None:
        return jsonify({'success': False, 'error': 'أدخل رابط Google Maps أو عنوان الموقع أولاً'}), 400

    site_maps_ctx = maps_service.maps_usage_ctx('site', g.tenant_id, data=data)
    with maps_service.maps_usage_scope(site_maps_ctx):
        fields, nearby_items, nearby_matrix, city_items, city_matrix, roads, polygon, diagnostics = _collect_site_fields(
            project_data, g.tenant_id, lat, lng
        )
    fields['location_polygon_source'] = (
        'manual' if project_data.get('location_polygon_source') == 'manual'
        # 'cleared' is the user switching the highlight off; it must survive a re-analysis.
        else 'cleared' if project_data.get('location_polygon_source') == 'cleared'
        else 'auto' if fields.get('location_polygon')
        else 'none'
    )

    return jsonify({
        'success': True,
        'fields': fields,
        'mapPlaceholders': {},
        'mapsDeferred': True,
        'landmarks': nearby_items,
        'landmarksMatrix': nearby_matrix,
        'cityLandmarks': city_items,
        'roads': roads,
        'zooms': {},
        'lat': lat,
        'lng': lng,
        'source': source,
        'boundary': {
            'status': 'verified_building' if polygon else 'needs_review',
            'estimated': False,
            'manual_edit_available': True,
        },
        'warning': None,
        'landmarksWarning': diagnostics.get('nearby_landmarks_error') or diagnostics.get('nearby_landmarks_warning'),
        'cityLandmarksWarning': diagnostics.get('city_landmarks_error') or diagnostics.get('city_landmarks_warning'),
    })


@app.route('/api/site-analysis', methods=['POST'])
@require_permission('create_presentation')
def api_site_analysis():
    data = request.json or {}
    _billing_guard = _require_billing_balance('site_analysis')
    if _billing_guard is not None:
        return _billing_guard
    raw_project_data = clean_project_data(data.get('projectData', {}))
    analysis_keys = (
        'project_name', 'project_type', 'project_subtype', 'project_idea', 'description', 'project_description',
        'project_goal', 'project_stage', 'initial_features', 'initial_strengths',
        'project_features', 'investment_opportunities', 'target_audience', 'location_address',
        'location_maps_link', 'maps_link', 'location_detail', 'location_lat', 'location_lng',
        'city', 'district', 'main_roads', 'nearby_landmarks', 'nearby_landmarks_data',
        'city_landmarks', 'catchment_areas', 'population_density', 'population_density_source',
        'location_polygon'
    )
    project_data = {
        key: raw_project_data.get(key)
        for key in analysis_keys
        if raw_project_data.get(key) not in (None, '', [], {})
    }
    if not project_data.get('location_lat') or not project_data.get('location_lng'):
        return jsonify({'success': False, 'error': 'بيانات الموقع والإحداثيات مطلوبة أولًا'}), 400

    lat = maps_service._extract_coordinate(project_data.get('location_lat'))
    lng = maps_service._extract_coordinate(project_data.get('location_lng'))
    if lat is None or lng is None:
        return jsonify({'success': False, 'error': 'بيانات الموقع والإحداثيات مطلوبة أولًا'}), 400

    enriched_fields = {}
    enrichment_diagnostics = {}
    needs_enrichment = any(
        project_data.get(key) in (None, '', [], {})
        for key in (
            'location_detail', 'main_roads', 'nearby_landmarks', 'nearby_landmarks_data',
            'city_landmarks', 'catchment_areas', 'population_density',
            'location_polygon',
        )
    )
    filled_fields = {}
    if needs_enrichment:
        try:
            # Same metering scope as analyze-site: every Google call inside
            # _collect_site_fields bills to this tenant/draft instead of
            # landing as an unbillable tenant_id=NULL row.
            site_maps_ctx = maps_service.maps_usage_ctx('site', g.tenant_id, data=data)
            with maps_service.maps_usage_scope(site_maps_ctx):
                enrichment_result = _collect_site_fields(raw_project_data, g.tenant_id, lat, lng)
            enriched_fields, nearby_items, *_rest, enrichment_diagnostics = enrichment_result
            enrichment_diagnostics = enrichment_diagnostics or {}
            if not project_data.get('nearby_landmarks_data') and nearby_items:
                enriched_fields['nearby_landmarks_data'] = nearby_items
        except Exception as error:
            print(f'[SITE DATA ENRICHMENT ERROR] {error}')
            enriched_fields = {}

    for key in analysis_keys:
        if enriched_fields.get(key) not in (None, '', [], {}) and project_data.get(key) in (None, '', [], {}):
            project_data[key] = enriched_fields[key]
            filled_fields[key] = enriched_fields[key]

    prompt = f"""اكتب تحليلًا عربيًا احترافيًا ومفصلًا لموقع مشروع عقاري اعتمادًا على البيانات التالية فقط.

المطلوب:
- اكتب تحليلًا عربيًا مسترسلًا في فقرات مترابطة، ولا تختصره إلى ملخص سريع أو عبارات عامة.
- غطِّ جميع الفئات التالية الموجودة في البيانات ولا تتخطى أي فئة فيها بيانات.
- يجب أن يتضمن التحليل إشارة مختصرة إلى كل ما يلي متاح منه، بالترتيب التالي قدر الإمكان:
  1. نوع المشروع وفكرته ووصفه والهدف منه ومرحلته الحالية والجمهور المستهدف.
  2. المميزات الأولية ونقاط القوة وفرص الاستثمار المناسبة للمشروع.
  3. طبيعة الموقع وموقعه الاستراتيجي والعنوان التفصيلي والإحداثيات.
  4. الكثافة السكانية ومصدرها إن وجدت.
  5. الطرق الرئيسية وطبيعة الوصول.
  6. المعالم القريبة ومعالم المدينة، مع ذكر المسافات وأوقات القيادة كدليل لا كموضوع رئيسي.
  7. نطاق التأثير ومناطق الالتقاط إن وجدت.
- اربط كل فئة بصلاحية الموقع لنوع المشروع وفكرته وهدفه ومرحلته والجمهور المستهدف ومميزات المشروع وفرصه.
- اشرح العلاقة والاستنتاجات بالتفصيل دون تكرار نفس المعلومة.
- لا تخترع أي معلومة غير موجودة في البيانات.
- إذا كانت معلومة غير متوفرة، لا تذكرها أبدًا بدلًا من اختلاقها.
- لا تستخدم عناوين أو نقاط تعداد في النص النهائي؛ أعد تحليلًا عربيًا سلسًا جاهزًا للعرض.

بيانات المشروع والموقع:
{json.dumps(project_data, ensure_ascii=False, indent=2)}"""
    system_prompt = 'أنت محلل مواقع عقارية دقيق. أخرج تحليلًا عربيًا سلسًا يغطي كل فئة متاحة من البيانات دون تخطي أي منها، ودون اختلاق معلومات غير موجودة.'
    training_context = db.get_training_context(g.tenant_id, surface='content') or ''
    if training_context:
        system_prompt += f"\n\n## بيانات خاصة بالشركة\n{training_context}"
    try:
        try:
            response = call_zai_chat(
                system_prompt, prompt, max_tokens=SITE_ANALYSIS_MAX_TOKENS,
                reasoning_effort='max', usage_ctx=_usage_ctx('site', data))
            analysis = extract_chat_content(response, 'SITE-ANALYSIS').strip()
        except Exception as primary_error:
            if not _has_any_openrouter_key(_usage_ctx('site', data)):
                raise
            print(f'[SITE ANALYSIS PRIMARY ERROR] {primary_error}. Trying direct OpenRouter fallback...')
            fallback = call_openrouter_chat(
                system_prompt,
                prompt,
                temperature=None,
                max_tokens=SITE_ANALYSIS_MAX_TOKENS,
                model=LUNA_TEXT_MODEL,
                usage_ctx=_usage_ctx('site', data)
            )
            analysis = extract_chat_content(fallback, 'SITE-ANALYSIS-FALLBACK').strip()
        warnings = [value for value in (
            enrichment_diagnostics.get('nearby_landmarks_error'),
            enrichment_diagnostics.get('nearby_landmarks_warning'),
            enrichment_diagnostics.get('city_landmarks_error'),
            enrichment_diagnostics.get('city_landmarks_warning'),
        ) if value]
        return jsonify({
            'success': True,
            'analysis': analysis,
            'fields': filled_fields,
            'warnings': warnings,
        })
    except Exception as error:
        print(f'[SITE ANALYSIS AI ERROR] {error}')
        return jsonify({
            'success': False,
            'error': 'تعذر تشغيل خدمة تحليل AI للموقع: ' + str(error),
            'error_code': 'SITE_ANALYSIS_AI_UNAVAILABLE'
        }), 503


@app.route('/api/generate-map-image', methods=['POST'])
@require_permission('generate_maps')
def api_generate_single_map_image():
    data = request.json or {}
    _billing_guard = _require_billing_balance('map_image')
    if _billing_guard is not None:
        return _billing_guard
    map_type = str(data.get('mapType') or '').strip().lower()
    if map_type not in {'overview', 'landmarks', 'access', 'catchment'}:
        return jsonify({'success': False, 'error': 'نوع خريطة غير صالح'}), 400
    project_data = clean_project_data(data.get('projectData', {})) or {}
    overlay_only = data.get('overlayOnly') is True and map_type in {'overview', 'access', 'catchment', 'landmarks'}
    presentation_id = data.get('presentationId')
    draft_id = project_data.get('draftId') or project_data.get('draft_id')
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None)
    if not effective_id:
        return jsonify({'success': False, 'error': 'معرّف العرض أو المسودة مطلوب'}), 400
    # ISS-025: workflow approvals are read from the stored project, never the
    # request payload — a flag the caller types in is not the ceremony.
    stored_project = {}
    presentation = None
    if presentation_id:
        presentation = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
        if not presentation or not _presentation_in_scope(presentation):
            return jsonify({'error': 'Presentation not found'}), 404
        try:
            stored_project = json.loads(presentation.get('project_data') or '{}')
        except (TypeError, ValueError):
            stored_project = {}
    elif draft_id:
        stored_draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
        if stored_draft and not db.user_may_access_draft(g.user_id, stored_draft):
            return jsonify({'success': False, 'error': 'المشروع غير موجود'}), 404
        stored_project = (stored_draft or {}).get('draft_data') or {}
    if not isinstance(stored_project, dict):
        stored_project = {}
    stored_creative = stored_project.get('tenantCreativeImages') \
        if isinstance(stored_project.get('tenantCreativeImages'), dict) else {}
    stored_map_approvals = stored_creative.get('map_approvals') \
        if isinstance(stored_creative.get('map_approvals'), dict) else {}
    if not overlay_only and stored_project.get('location_analysis_approved') not in (True, 'true', 1):
        return jsonify({
            'success': False,
            'error': 'يجب اعتماد تحليل الموقع قبل إنشاء الخريطة',
            'error_code': 'LOCATION_ANALYSIS_NOT_APPROVED',
        }), 400
    if not overlay_only and map_type in {'landmarks', 'access', 'catchment'} \
            and stored_map_approvals.get('overview') is not True:
        return jsonify({
            'success': False,
            'error': 'يجب اعتماد خريطة الموقع العامة قبل إنشاء هذه الخريطة',
            'error_code': 'OVERVIEW_MAP_NOT_APPROVED',
        }), 400
    if stored_map_approvals.get(map_type) is True:
        return jsonify({
            'success': False,
            'error': 'يجب إلغاء اعتماد الخريطة قبل إعادة توليدها',
            'error_code': 'MAP_ALREADY_APPROVED',
        }), 400
    highlight_site = data.get('highlightSite', True) is not False
    expected_revision = None
    if presentation:
        try:
            expected_revision = _expected_presentation_revision(data, presentation)
            # Freeze a legacy baseline before a map provider can overwrite its files.
            checkpoint = _commit_presentation_state(
                g.tenant_id, presentation_id, expected_revision=expected_revision,
                action='حفظ حالة العرض قبل تعديل الخريطة', source='system')
            expected_revision = checkpoint['revision']
            presentation = checkpoint['presentation']
        except (LookupError, ValueError) as error:
            return jsonify({'error': str(error)}), 400
    if data.get('overlayOnly') is True and map_type == 'overview':
        result = maps_service.recompose_overview_map(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
            highlight_site=highlight_site,
        )
    elif data.get('overlayOnly') is True and map_type == 'access':
        result = maps_service.recompose_access_map(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
        )
    elif data.get('overlayOnly') is True and map_type == 'catchment':
        result = maps_service.recompose_catchment_map(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
        )
    elif data.get('overlayOnly') is True and map_type == 'landmarks':
        result = maps_service.recompose_landmarks_map(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
        )
    else:
        image_types = [map_type, f'{map_type}_satellite', f'{map_type}_roadmap']
        if map_type in {'overview', 'access', 'catchment', 'landmarks'}:
            image_types.extend([
                f'{map_type}_editable', f'{map_type}_satellite_editable', f'{map_type}_roadmap_editable'
            ])
        for image_type in image_types:
            db.delete_map_images(g.tenant_id, presentation_id=effective_id, image_type=image_type)
        project_data['enabled_maps'] = [map_type]
        project_data['refresh_maps'] = True
        if data.get('regenSeed') is not None:
            project_data['regen_seed'] = data.get('regenSeed')
        branding = db.get_branding(g.tenant_id) or {}
        result = maps_service.generate_all_map_images(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
            force=False,
            branding=branding,
            highlight_site=highlight_site,
            usage_flow=map_type,
        )
    if result.get('error'):
        return jsonify({'success': False, 'error': result['error']}), 400
    placeholders = {}
    for placeholder, path in result.get('placeholders', {}).items():
        if path and os.path.exists(path):
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            placeholders[placeholder] = '/' + rel_path
    map_labels = {'overview': 'الموقع العام', 'access': 'الوصول', 'catchment': 'نطاق الخدمة', 'landmarks': 'المعالم'}
    revision_result = None
    if presentation_id:
        state = _presentation_state(presentation)
        old_placeholders = dict(state['projectData'].get('map_placeholders') or {})
        old_creative = state['projectData'].get('tenantCreativeImages') or {}
        if isinstance(old_creative, dict):
            old_placeholders.update(old_creative.get('map_placeholders') or {})
        updated_project = {**state['projectData'], **project_data}
        updated_project['map_placeholders'] = {**old_placeholders, **placeholders}
        updated_project['tenantCreativeImages'] = {
            **(old_creative if isinstance(old_creative, dict) else {}),
            'map_placeholders': updated_project['map_placeholders'],
        }
        slides = state['slidesData']
        for slide in slides:
            if isinstance(slide, dict) and isinstance(slide.get('html'), str):
                for token, url in placeholders.items():
                    old_url = old_placeholders.get(token)
                    if isinstance(old_url, str) and old_url:
                        slide['html'] = slide['html'].replace(old_url, url)
                    slide['html'] = slide['html'].replace(token, url)
        try:
            revision_result = _commit_presentation_state(
                g.tenant_id, presentation_id, project_data=updated_project, slides_data=slides,
                expected_revision=expected_revision, action='تعديل خريطة' if overlay_only else 'توليد خريطة',
                details=[f'خريطة {map_labels.get(map_type, map_type)}'], source='manual')
        except (LookupError, ValueError) as error:
            return jsonify({'error': str(error)}), 400
    elif draft_id:
        _record_change('draft', draft_id, 'توليد خريطة',
                       [f'وُلّدت خريطة {map_labels.get(map_type, map_type)}'])
    return jsonify({
        **(_presentation_revision_response(revision_result) if revision_result else {}),
        'success': True,
        'mapType': map_type,
        'placeholders': placeholders,
        'landmarks': result.get('landmarks', []),
        'landmarks_matrix': result.get('landmarks_matrix', []),
        'zooms': result.get('zooms', {}),
        'centers': result.get('centers', {}),
        'sitePolygon': result.get('site_polygon', []),
        'accessRoads': result.get('access_roads', []),
        'catchmentLandmarks': result.get('catchment_landmarks', []),
        'landmarkMapItems': result.get('landmark_map_items', []),
    })


@app.route('/api/generate-map-images', methods=['POST'])
@require_auth
def api_generate_map_images():
    """Reject the retired bulk path so maps can only be generated individually."""
    return jsonify({
        'success': False,
        'error': 'توليد الخرائط متاح لكل خريطة على حدة',
        'error_code': 'INDIVIDUAL_MAP_GENERATION_REQUIRED',
    }), 400


@app.route('/api/presentations/<pres_id>/regenerate-maps', methods=['POST'])
@require_permission('create_presentation')
def api_regenerate_presentation_maps(pres_id):
    """Reject the retired saved-presentation bulk regeneration path."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404

    return jsonify({
        'success': False,
        'error': 'إعادة توليد الخرائط متاحة لكل خريطة على حدة',
        'error_code': 'INDIVIDUAL_MAP_GENERATION_REQUIRED',
    }), 400
