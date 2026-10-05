def _generate_all_map_images(project_data, tenant_id, presentation_id=None, force=False, branding=None, draft_id=None, highlight_site=True):
    """
    Generate all map images needed for a project.
    Returns dict of placeholder -> file_path.
    If force=False and valid cached images exist, returns them without calling Google APIs.
    """
    if not _has_api_key():
        return {'error': 'Google Maps API key not configured'}

    limit_error = _check_maps_rate_limit(tenant_id)
    if limit_error:
        return limit_error

    map_lang = map_language(project_data)

    address = project_data.get('location_address') or project_data.get('location', '')
    maps_link = (
        (address if str(address).startswith('http') else '') or
        project_data.get('location_maps_link') or project_data.get('maps_link')
    )
    lat, lng = _resolve_map_coordinates(project_data, tenant_id)
    if lat is None or lng is None:
        if maps_link:
            return {'error': 'تعذر استخراج الإحداثيات من رابط Google Maps'}
        return {'error': 'لم يتم العثور على موقع أو إحداثيات للمشروع. يرجى إدخال عنوان المشروع أو رابط Google Maps في البيانات.'}

    enabled_maps = project_data.get('enabled_maps')
    if isinstance(enabled_maps, str):
        try:
            enabled_maps = json.loads(enabled_maps)
        except Exception:
            enabled_maps = None
    if not isinstance(enabled_maps, list):
        enabled_maps = ['overview', 'landmarks', 'access', 'catchment']

    # Select each map's structured rows before any geocoding. A structured table is
    # authoritative when present; legacy text remains a compatibility fallback.
    nearby_structured = project_data.get('nearby_landmarks_data')
    city_structured = project_data.get('city_landmarks_data')
    nearby_rows = select_map_landmark_rows(nearby_structured)
    city_rows = select_map_landmark_rows(city_structured)
    if nearby_structured is None:
        nearby_text = project_data.get('nearby_landmarks', '')
        nearby_rows = _parse_landmarks_text(nearby_text, language=map_lang)[:7] if isinstance(nearby_text, str) else []
    if city_structured is None:
        city_text = project_data.get('city_landmarks', '')
        city_rows = _parse_landmarks_text(city_text, language=map_lang)[:7] if isinstance(city_text, str) else []
    landmarks = _merge_landmark_data([], nearby_rows) if 'landmarks' in enabled_maps else []
    city_landmarks = _merge_landmark_data([], city_rows) if 'catchment' in enabled_maps else []
    zones = _parse_catchment_zones(project_data.get('catchment_areas', ''))

    draft_id = draft_id or project_data.get('draft_id') or project_data.get('draftId')
    effective_pres_id = presentation_id or (f"draft_{draft_id}" if draft_id else None)

    def _close(a, b):
        try:
            return a is not None and b is not None and abs(float(a) - float(b)) < 1e-5
        except Exception:
            return False

    if not force and not project_data.get('refresh_maps') and effective_pres_id:
        cached = _get_cached_map_images(
            tenant_id,
            effective_pres_id,
            expected_lat=lat,
            expected_lng=lng,
            expected_highlight_site=highlight_site,
        )
        if cached and _close(cached.get('lat'), lat) and _close(cached.get('lng'), lng):
            found_base = cached.get('found_base') or set()
            required_base = {t for t in enabled_maps if t not in ('streetview',)}
            if not (required_base - found_base):
                return cached

    if force and effective_pres_id:
        from db import delete_map_images
        delete_map_images(tenant_id, presentation_id=effective_pres_id)

    result = {
        'lat': lat,
        'lng': lng,
        'placeholders': {},
        'landmarks': [],
        'landmarks_matrix': [],
        'access_roads': [],
        'catchment_landmarks': [],
        'landmark_map_items': [],
    }

    polygon_coords = None
    poly_data = project_data.get('location_polygon')
    user_polygon_used = False
    if highlight_site and poly_data:
        try:
            if isinstance(poly_data, str):
                polygon_coords = []
                for pt in poly_data.split(';'):
                    if ',' in pt:
                        plat, plng = pt.split(',')
                        polygon_coords.append((float(plat.strip()), float(plng.strip())))
            elif isinstance(poly_data, list):
                polygon_coords = [(float(pt[0]), float(pt[1])) for pt in poly_data if len(pt) >= 2]
            if polygon_coords and len(polygon_coords) >= 3:
                user_polygon_used = True
                print(f"[POLYGON] Using user-provided polygon with {len(polygon_coords)} points")
        except Exception as e:
            print(f"[POLYGON PARSE ERROR] {e}")

    if polygon_coords and len(polygon_coords) >= 3:
        # A boundary saved for a previous site must not drive the frame: its
        # centroid lands on the old location, the base fetch centres there and
        # every overlay lands off-map. Legitimate plot boundaries sit within a
        # few hundred metres of the pin.
        nearest_vertex_m = min(
            _distance_meters(lat, lng, point[0], point[1]) for point in polygon_coords)
        centroid_lat = sum(point[0] for point in polygon_coords) / len(polygon_coords)
        centroid_lng = sum(point[1] for point in polygon_coords) / len(polygon_coords)
        if nearest_vertex_m > 500 and _distance_meters(lat, lng, centroid_lat, centroid_lng) > 500:
            print('[POLYGON] Stored boundary sits far from the resolved site — discarded')
            polygon_coords = None
            user_polygon_used = False

    # Croquis coordinates are the real plot boundary, so they outrank any guess.
    if highlight_site and not user_polygon_used and (not polygon_coords or len(polygon_coords) < 3):
        survey_polygon = survey_polygon_from_project(project_data, lat, lng)
        if survey_polygon and len(survey_polygon) >= 3:
            polygon_coords = survey_polygon
            print(f"[POLYGON] Using croquis survey polygon with {len(polygon_coords)} points")

    # Try to auto-detect a building/compound polygon from OSM
    if highlight_site and not user_polygon_used and (not polygon_coords or len(polygon_coords) < 3):
        cache_key = f"{lat:.6f},{lng:.6f}"
        if cache_key in _osm_polygon_cache:
            osm_poly = _osm_polygon_cache[cache_key]
        else:
            osm_poly = _fetch_osm_polygon(lat, lng, radius_m=400)
            if osm_poly:
                _osm_polygon_cache[cache_key] = osm_poly
        if osm_poly and len(osm_poly) >= 3 and not _is_viewport_rectangle(osm_poly):
            polygon_coords = osm_poly
            print(f"[POLYGON] Using OSM building polygon with {len(polygon_coords)} points")

    if highlight_site and not user_polygon_used and (not polygon_coords or len(polygon_coords) < 3):
        bounds_polygon = _google_bounds_polygon(lat, lng, tenant_id=tenant_id)
        if bounds_polygon:
            polygon_coords = bounds_polygon
            print('[POLYGON] Using the Google geocoding bounds rectangle')

    auto_detected = not user_polygon_used
    result['site_polygon'] = [list(point) for point in polygon_coords] if polygon_coords and len(polygon_coords) >= 3 else []

    # Compute presentation-friendly zoom levels from the selected boundary.
    zooms = _calculate_map_zooms(polygon_coords)
    refresh_maps = force or bool(project_data.get('refresh_maps'))
    try:
        regen_seed = int(project_data.get('regen_seed') or 0)
    except (TypeError, ValueError):
        regen_seed = 0
    # A viewport the user picked in the preview (manual zoom/pan) overrides the
    # computed frame for the overview and access maps — landmark and catchment
    # extents stay fitted to their content. Only types flagged in
    # map_viewport_overrides count: the payload also carries every stored frame,
    # and an unflagged one is just the last render, not a user request.
    manual_types = project_data.get('map_viewport_overrides')
    manual_types = {key for key, flag in manual_types.items() if flag} if isinstance(manual_types, dict) else set()
    zoom_overrides = project_data.get('map_zooms')
    zoom_overrides = {
        key: value for key, value in zoom_overrides.items() if key in manual_types
    } if isinstance(zoom_overrides, dict) else {}
    center_overrides = project_data.get('map_centers')
    center_overrides = {
        key: value for key, value in center_overrides.items() if key in manual_types
    } if isinstance(center_overrides, dict) else {}
    map_sizes = {key: _map_viewport_size(center_overrides.get(key)) or (1280, 720)
                 for key in ('overview', 'access', 'catchment', 'landmarks')}
    # A regenerate must not re-frame a map whose extent is derived from a real boundary:
    # shifting the zoom by two levels shrank the plot back to a dot. A manual viewport
    # wins over the seed shift too — the user asked for that exact frame.
    if project_data.get('refresh_maps') and regen_seed and not (polygon_coords and len(polygon_coords) >= 3):
        zoom_shift = MAP_REGEN_ZOOM_OFFSETS[regen_seed % len(MAP_REGEN_ZOOM_OFFSETS)]
        for map_key in enabled_maps:
            if map_key in zooms and map_key not in zoom_overrides:
                zooms[map_key] = max(12, min(20, int(zooms[map_key]) + zoom_shift))
    overview_zoom = zooms['overview']
    landmarks_zoom = zooms['landmarks']
    access_zoom = access_map_zoom(lat, zooms['access'])
    catchment_zoom = zooms['catchment']

    if polygon_coords and len(polygon_coords) >= 3:
        print(
            f"[DYNAMIC ZOOM] overview={overview_zoom}, landmarks={landmarks_zoom}, "
            f"access={access_zoom}, catchment={catchment_zoom}"
        )

    map_center_lat, map_center_lng = lat, lng
    if polygon_coords and len(polygon_coords) >= 3:
        map_center_lat = (min(point[0] for point in polygon_coords) + max(point[0] for point in polygon_coords)) / 2
        map_center_lng = (min(point[1] for point in polygon_coords) + max(point[1] for point in polygon_coords)) / 2

    result['zooms'] = {
        'overview': overview_zoom,
        'landmarks': landmarks_zoom,
        'access': access_zoom,
        'catchment': catchment_zoom,
    }
    # The client converts clicks to coordinates against these, so it must know the centre each
    # image was actually rendered around. Assuming the site pin put every drawn boundary off by
    # the distance between the pin and the plot centroid.
    result['centers'] = {
        'overview': {'lat': map_center_lat, 'lng': map_center_lng},
        'landmarks': {'lat': map_center_lat, 'lng': map_center_lng},
        'access': {'lat': map_center_lat, 'lng': map_center_lng},
        'catchment': {'lat': lat, 'lng': lng},
    }

    def _manual_viewport_zoom(map_key, fallback):
        try:
            value = int(zoom_overrides.get(map_key))
        except (TypeError, ValueError):
            return fallback
        return max(8, min(20, value)) if 0 < value else fallback

    def _manual_viewport_center(map_key, fallback_lat, fallback_lng):
        item = center_overrides.get(map_key)
        if not isinstance(item, dict):
            return fallback_lat, fallback_lng
        try:
            c_lat, c_lng = float(item.get('lat')), float(item.get('lng'))
        except (TypeError, ValueError):
            return fallback_lat, fallback_lng
        if not (-85 <= c_lat <= 85 and -180 <= c_lng <= 180):
            return fallback_lat, fallback_lng
        # A stored frame from a previous site is stale, not a manual pan —
        # beyond ~3 km it cannot be a viewport adjustment of this map.
        if _distance_meters(lat, lng, c_lat, c_lng) > 3000 and _map_viewport_size(item) is None:
            return fallback_lat, fallback_lng
        return c_lat, c_lng

    overview_zoom = _manual_viewport_zoom('overview', overview_zoom)
    access_zoom = _manual_viewport_zoom('access', access_zoom)
    overview_center_lat, overview_center_lng = _manual_viewport_center('overview', map_center_lat, map_center_lng)
    access_center_lat, access_center_lng = _manual_viewport_center('access', map_center_lat, map_center_lng)
    result['zooms'].update({'overview': overview_zoom, 'access': access_zoom})
    result['centers'].update({
        'overview': _map_frame_center(overview_center_lat, overview_center_lng, map_sizes['overview']),
        'access': _map_frame_center(access_center_lat, access_center_lng, map_sizes['access']),
    })

    # The approved latitude/longitude is the user-controlled pin for every map. The boundary may
    # center the viewport, but it must never move that saved pin implicitly.
    marker_lat, marker_lng = lat, lng

    # Map type and chrome are platform-fixed — every map renders satellite except
    # the roads map, which renders roadmap; compass and inset always on. No
    # company or project setting carries them.
    draw_compass = True
    draw_inset = True
    map_styles = {'overview': 'satellite', 'landmarks': 'satellite',
                  'access': 'roadmap', 'catchment': 'satellite'}

    landmark_radius_m = 20000
    city_context = project_data.get('city') or project_data.get('location', '')

    # Preserve the selected table order through geocoding and filtering so marker
    # numbering stays aligned with the approved rows.
    def _resolve_map_landmarks(rows, search_radius_m, maximum_distance_m=None):
        # Road rows carry a stored point that may be a remote endpoint of the
        # feature — re-anchor them to the drawn road path (or the nearest
        # Places candidate) before trusting any stored coordinate.
        _snap_road_landmarks(rows, project_data, lat, lng, language=map_lang,
                             search_radius_m=search_radius_m)
        resolved = []
        for landmark in rows:
            if landmark.get('lat') is None or landmark.get('lng') is None:
                place = find_place_near(landmark.get('name'), lat, lng, radius_m=search_radius_m, language=map_lang)
                if place:
                    landmark['lat'] = place['lat']
                    landmark['lng'] = place['lng']
                else:
                    # Only the city is appended here: adding the project address made Google
                    # return the project's own coordinates for every landmark.
                    query = f"{landmark.get('name')}, {city_context}" if city_context else landmark.get('name')
                    geo = geocode_address(query, tenant_id=tenant_id)
                    if geo.get('success'):
                        landmark['lat'] = geo['lat']
                        landmark['lng'] = geo['lng']
            if landmark.get('lat') is None or landmark.get('lng') is None:
                print(f"[LANDMARKS] '{landmark.get('name')}' has no resolvable coordinates — skipped")
                continue
            distance_meters = _distance_meters(lat, lng, landmark['lat'], landmark['lng'])
            if distance_meters < 50:
                print(f"[LANDMARKS] '{landmark.get('name')}' resolves to the site itself — skipped")
                continue
            if maximum_distance_m is not None and distance_meters > maximum_distance_m:
                print(f"[LANDMARKS] '{landmark.get('name')}' is {distance_meters / 1000.0:.1f} km away, beyond {maximum_distance_m / 1000.0:.0f} km — skipped")
                continue
            landmark['distance_meters'] = round(distance_meters)
            resolved.append(landmark)
        return resolved

    # Retain automatic discovery only for old projects that have no structured
    # nearby-landmark table. An explicit table, including an empty one, is authoritative.
    if 'landmarks' in enabled_maps and nearby_structured is None and not landmarks:
        places = get_nearby_landmarks(
            lat, lng, radius=landmark_radius_m, max_results=7, include_all=True, language=map_lang
        )
        if places.get('success'):
            landmarks = (places.get('landmarks') or [])[:7]
            _record_maps_call(tenant_id)

    if landmarks:
        landmarks = _resolve_map_landmarks(
            landmarks, landmark_radius_m, maximum_distance_m=landmark_radius_m
        )
    if city_landmarks:
        city_search_radius_m = min(
            50000,
            max([landmark_radius_m] + [float(zone.get('km') or 0) * 1000 for zone in zones]),
        )
        city_landmarks = _resolve_map_landmarks(city_landmarks, city_search_radius_m)
    result['landmarks'] = landmarks

    # Get driving times and distances only for the nearby rows used by the landmarks map.
    if landmarks and project_data.get('calculate_landmark_driving', True) is not False:
        matrix = get_drive_matrix((lat, lng), landmarks, language=map_lang)
        if matrix:
            for i, landmark in enumerate(landmarks):
                if i >= len(matrix):
                    break
                entry = matrix[i]
                if not entry.get('name'):
                    entry['name'] = landmark.get('name', '')
                if entry['duration_min'] is None:
                    continue
                landmark['duration_minutes'] = entry['duration_min']
                landmark['distance_text'] = entry.get('distance_text') or f"{entry['distance_km']} {_distance_unit(map_lang)}"
            # Only rows with real Google numbers are handed to the AI prompt.
            usable = [item for item in matrix if item.get('duration_min') is not None]
            if usable:
                project_data['landmarks_matrix'] = usable
                result['landmarks_matrix'] = usable
            _record_maps_call(tenant_id)

    # Helper: pick styles based on maptype
    def _styles_for(maptype, default_styles, map_kind=None):
        """Satellite keeps custom tones; access roadmap hides native labels so our names stay readable."""
        if maptype == 'satellite':
            return default_styles
        if map_kind == 'access':
            return ACCESS_ROADMAP_STYLES
        return []

    # Generate map_overview. This view contains only the site pin/highlight.
    if 'overview' in enabled_maps:
        overview_markers = _build_markers(marker_lat, marker_lng)
        overview_mt = map_styles['overview']
        if overview_mt == 'both':
            styles_to_gen = [('satellite', '##MAP_OVERVIEW_SATELLITE##', 'overview_satellite'),
                             ('roadmap', '##MAP_OVERVIEW_ROADMAP##', 'overview_roadmap')]
        else:
            styles_to_gen = [(overview_mt, '##MAP_OVERVIEW##', 'overview')]
        editable_placeholders = {
            '##MAP_OVERVIEW##': '##MAP_OVERVIEW_EDITABLE##',
            '##MAP_OVERVIEW_SATELLITE##': '##MAP_OVERVIEW_SATELLITE_EDITABLE##',
            '##MAP_OVERVIEW_ROADMAP##': '##MAP_OVERVIEW_ROADMAP_EDITABLE##',
        }

        for active_mt, placeholder, img_suffix in styles_to_gen:
            overview_path = _unique_map_path(tenant_id, effective_pres_id, img_suffix)
            overview_res = get_static_map(overview_center_lat, overview_center_lng, zoom=overview_zoom, size=map_sizes['overview'], output_path=overview_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_WITH_LABELS_STYLES), bypass_cache=refresh_maps, language=map_lang)
            if overview_res.get('error'):
                return overview_res
            if overview_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(overview_path, intensity=0.35)
                    _apply_map_overlay(overview_path, dark_factor=0.12)
                if draw_compass:
                    _draw_compass(overview_path, position='top-right', language=map_lang)
                if draw_inset:
                    _draw_inset_map(overview_path, lat, lng, inset_size=180, language=map_lang)
                editable_placeholder = editable_placeholders[placeholder]
                editable_suffix = img_suffix + '_editable'
                editable_path = _unique_map_path(tenant_id, effective_pres_id, editable_suffix)
                shutil.copyfile(overview_path, editable_path)
                metadata = {'lat': lat, 'lng': lng, 'zoom': overview_zoom, 'center_lat': overview_center_lat, 'center_lng': overview_center_lng, 'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION, 'map_label_version': MAP_LABEL_RENDER_VERSION, 'highlight_site': bool(highlight_site), 'landmarks_matrix': result.get('landmarks_matrix') or [], 'viewport_size': _map_size_metadata(map_sizes['overview'])}
                if highlight_site:
                    _draw_site_highlight(overview_path, overview_center_lat, overview_center_lng, overview_zoom, size=map_sizes['overview'], polygon_coords=polygon_coords, auto_detect_polygon=False, auto_detected=auto_detected)
                _overlay_markers(overview_path, overview_center_lat, overview_center_lng, overview_zoom, overview_markers, size=map_sizes['overview'])
                result['placeholders'][placeholder] = overview_path
                result['placeholders'][editable_placeholder] = editable_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, img_suffix, overview_path, placeholder, effective_pres_id, metadata)
                add_map_image(tenant_id, editable_suffix, editable_path, editable_placeholder, effective_pres_id, metadata)

    # Generate map_landmarks (closer zoom)
    if 'landmarks' in enabled_maps:
        # The landmark view uses only the selected nearby table rows and fits that content.
        shown_landmarks = [item for item in landmarks if item.get('distance_meters')]
        if shown_landmarks:
            radius_km = max(item['distance_meters'] for item in shown_landmarks) / 1000.0
            # The frame must cover everything the resolver kept — a tighter cap
            # drew far-but-valid selections off-canvas and dropped them silently.
            radius_km = max(0.6, min(landmark_radius_m / 1000.0, radius_km * 1.1))
            fitted_zoom = zoom_for_radius_km(lat, radius_km)
            if fitted_zoom:
                landmarks_zoom = fitted_zoom
                print(f'[LANDMARKS] {len(shown_landmarks)} landmarks within {radius_km:.1f} km, zoom {landmarks_zoom}')
        # The landmarks map is a fixed auto frame: a stored manual viewport from
        # the interactive era no longer applies — the content fit is the frame.
        landmarks_center_lat, landmarks_center_lng = map_center_lat, map_center_lng
        result['zooms']['landmarks'] = landmarks_zoom
        result['centers']['landmarks'] = _map_frame_center(landmarks_center_lat, landmarks_center_lng, map_sizes['landmarks'])
        landmarks_mt = map_styles['landmarks']
        if landmarks_mt == 'both':
            styles_to_gen = [('satellite', '##MAP_LANDMARKS_SATELLITE##', 'landmarks_satellite'),
                             ('roadmap', '##MAP_LANDMARKS_ROADMAP##', 'landmarks_roadmap')]
        else:
            styles_to_gen = [(landmarks_mt, '##MAP_LANDMARKS##', 'landmarks')]

        editable_placeholders = {
            '##MAP_LANDMARKS##': '##MAP_LANDMARKS_EDITABLE##',
            '##MAP_LANDMARKS_SATELLITE##': '##MAP_LANDMARKS_SATELLITE_EDITABLE##',
            '##MAP_LANDMARKS_ROADMAP##': '##MAP_LANDMARKS_ROADMAP_EDITABLE##',
        }
        for active_mt, placeholder, img_suffix in styles_to_gen:
            landmarks_path = _unique_map_path(tenant_id, effective_pres_id, img_suffix)
            lm_res = get_static_map(landmarks_center_lat, landmarks_center_lng, zoom=landmarks_zoom, size=map_sizes['landmarks'], output_path=landmarks_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_WIDE_STYLES), bypass_cache=refresh_maps, language=map_lang)
            if lm_res.get('error'):
                return lm_res
            if lm_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(landmarks_path, intensity=0.35)
                    _apply_map_overlay(landmarks_path, dark_factor=0.20)
                if draw_compass:
                    _draw_compass(landmarks_path, position='top-right', language=map_lang)
                if draw_inset:
                    _draw_inset_map(landmarks_path, lat, lng, inset_size=180, language=map_lang)
                editable_placeholder = editable_placeholders[placeholder]
                editable_suffix = img_suffix + '_editable'
                editable_path = _unique_map_path(tenant_id, effective_pres_id, editable_suffix)
                shutil.copyfile(landmarks_path, editable_path)
                rendered_landmarks = _draw_catchment_markers(
                    landmarks_path, landmarks_center_lat, landmarks_center_lng, landmarks_zoom, shown_landmarks or landmarks,
                    project_data.get('landmark_label_positions'), scale=2, site_lat=marker_lat, site_lng=marker_lng
                )
                if not result['landmark_map_items']:
                    result['landmark_map_items'] = rendered_landmarks
                metadata = {
                    'lat': lat,
                    'lng': lng,
                    'zoom': landmarks_zoom,
                    'center_lat': landmarks_center_lat,
                    'center_lng': landmarks_center_lng,
                    'viewport_size': _map_size_metadata(map_sizes['landmarks']),
                    'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION,
                    'map_label_version': MAP_LABEL_RENDER_VERSION,
                    'highlight_site': bool(highlight_site),
                    'landmarks': landmarks,
                    'landmarks_matrix': result.get('landmarks_matrix') or [],
                    'landmark_map_items': rendered_landmarks,
                }
                result['placeholders'][placeholder] = landmarks_path
                result['placeholders'][editable_placeholder] = editable_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, img_suffix, landmarks_path, placeholder, effective_pres_id, metadata)
                add_map_image(tenant_id, editable_suffix, editable_path, editable_placeholder, effective_pres_id, metadata)

    # Generate map_access
    if 'access' in enabled_maps:
        access_markers = [{'lat': marker_lat, 'lng': marker_lng, 'color': MARKER_COLOR_SITE, 'type': 'site', 'label': None}]
        access_mt = map_styles['access']
        if access_mt == 'both':
            styles_to_gen = [('satellite', '##MAP_ACCESS_SATELLITE##', 'access_satellite'),
                             ('roadmap', '##MAP_ACCESS_ROADMAP##', 'access_roadmap')]
        else:
            styles_to_gen = [(access_mt, '##MAP_ACCESS##', 'access')]

        editable_placeholders = {
            '##MAP_ACCESS##': '##MAP_ACCESS_EDITABLE##',
            '##MAP_ACCESS_SATELLITE##': '##MAP_ACCESS_SATELLITE_EDITABLE##',
            '##MAP_ACCESS_ROADMAP##': '##MAP_ACCESS_ROADMAP_EDITABLE##',
        }
        for active_mt, placeholder, img_suffix in styles_to_gen:
            access_path = _unique_map_path(tenant_id, effective_pres_id, img_suffix)
            access_res = get_static_map(access_center_lat, access_center_lng, zoom=access_zoom, size=map_sizes['access'], output_path=access_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_CLEAN_STYLES, 'access'), bypass_cache=refresh_maps, language=map_lang)
            if access_res.get('error'):
                return access_res
            if access_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(access_path, intensity=0.35)
                    _apply_map_overlay(access_path, dark_factor=0.10)
                if draw_compass:
                    _draw_compass(access_path, position='top-right', language=map_lang)
                editable_placeholder = editable_placeholders[placeholder]
                editable_suffix = img_suffix + '_editable'
                editable_path = _unique_map_path(tenant_id, effective_pres_id, editable_suffix)
                shutil.copyfile(access_path, editable_path)
                rendered_roads = _draw_access_roads(
                    access_path,
                    access_center_lat,
                    access_center_lng,
                    access_zoom,
                    scale=2,
                    project_data=project_data,
                    tenant_id=tenant_id,
                    origin_lat=marker_lat,
                    origin_lng=marker_lng,
                ) or []
                if not result['access_roads']:
                    result['access_roads'] = rendered_roads
                _overlay_markers(access_path, access_center_lat, access_center_lng, access_zoom, access_markers, size=map_sizes['access'])
                metadata = {
                    'lat': lat,
                    'lng': lng,
                    'zoom': access_zoom,
                    'center_lat': access_center_lat,
                    'center_lng': access_center_lng,
                    'viewport_size': _map_size_metadata(map_sizes['access']),
                    'access_roads_version': ACCESS_ROADS_RENDER_VERSION,
                    'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION, 'map_label_version': MAP_LABEL_RENDER_VERSION,
                    'highlight_site': bool(highlight_site),
                    'landmarks_matrix': result.get('landmarks_matrix') or [],
                    'access_roads': rendered_roads,
                }
                result['placeholders'][placeholder] = access_path
                result['placeholders'][editable_placeholder] = editable_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, img_suffix, access_path, placeholder, effective_pres_id, metadata)
                add_map_image(tenant_id, editable_suffix, editable_path, editable_placeholder, effective_pres_id, metadata)



    # Generate map_catchment
    if 'catchment' in enabled_maps:
        # zones were pre-parsed before the cache check
        rings = catchment_rings(zones)
        ring_km = max([ring['km'] for ring in rings] + [0.0])
        # The frame must cover the selected landmarks too, not just the rings —
        # a marker beyond the outer ring was silently drawn off-canvas. Fitting
        # each direction on its own keeps a far row drawable without mirroring
        # the same empty distance into the opposite side of the frame.
        frame_fit = catchment_frame_fit(lat, lng, ring_km, city_landmarks)
        if frame_fit:
            catchment_zoom, catchment_center_lat, catchment_center_lng = frame_fit
            print(f"[CATCHMENT] {len(rings)} rings + {len(city_landmarks)} landmarks, zoom {catchment_zoom}")
        else:
            catchment_center_lat, catchment_center_lng = lat, lng
        # Catchment is fixed too — always the content-fitted frame; a stored
        # manual frame is leftover from the interactive era.
        catchment_manual_frame = False
        result['zooms']['catchment'] = catchment_zoom
        result['centers']['catchment'] = _map_frame_center(catchment_center_lat, catchment_center_lng, map_sizes['catchment'])
        catchment_mt = map_styles['catchment']
        if catchment_mt == 'both':
            styles_to_gen = [('satellite', '##MAP_CATCHMENT_SATELLITE##', 'catchment_satellite'),
                             ('roadmap', '##MAP_CATCHMENT_ROADMAP##', 'catchment_roadmap')]
        else:
            styles_to_gen = [(catchment_mt, '##MAP_CATCHMENT##', 'catchment')]

        editable_placeholders = {
            '##MAP_CATCHMENT##': '##MAP_CATCHMENT_EDITABLE##',
            '##MAP_CATCHMENT_SATELLITE##': '##MAP_CATCHMENT_SATELLITE_EDITABLE##',
            '##MAP_CATCHMENT_ROADMAP##': '##MAP_CATCHMENT_ROADMAP_EDITABLE##',
        }
        for active_mt, placeholder, img_suffix in styles_to_gen:
            catchment_path = _unique_map_path(tenant_id, effective_pres_id, img_suffix)
            # Fetch clean map without the API-drawn paths, as we will draw them with PIL for premium styling.
            catchment_res = get_static_map(catchment_center_lat, catchment_center_lng, zoom=catchment_zoom, paths=None, size=map_sizes['catchment'], output_path=catchment_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_WIDE_STYLES), bypass_cache=refresh_maps, language=map_lang)
            if catchment_res.get('error'):
                return catchment_res
            if catchment_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(catchment_path, intensity=0.35)
                    _apply_map_overlay(catchment_path, dark_factor=0.15)
                # Draw the anti-aliased concentric rings with time label pills
                if rings:
                    _draw_catchment_zones(catchment_path, catchment_center_lat, catchment_center_lng,
                                          catchment_zoom, rings, scale=2, site_lat=lat, site_lng=lng)
                if draw_compass:
                    _draw_compass(catchment_path, position='top-right', language=map_lang)
                if draw_inset:
                    _draw_inset_map(catchment_path, lat, lng, inset_size=180, language=map_lang)
                editable_placeholder = editable_placeholders[placeholder]
                editable_suffix = img_suffix + '_editable'
                editable_path = _unique_map_path(tenant_id, effective_pres_id, editable_suffix)
                shutil.copyfile(catchment_path, editable_path)
                rendered_landmarks = _draw_catchment_markers(
                    catchment_path, catchment_center_lat, catchment_center_lng, catchment_zoom, city_landmarks,
                    project_data.get('catchment_label_positions'), scale=2, site_lat=lat, site_lng=lng
                )
                if not result['catchment_landmarks']:
                    result['catchment_landmarks'] = rendered_landmarks
                metadata = {
                    'lat': lat,
                    'lng': lng,
                    'zoom': catchment_zoom,
                    'center_lat': catchment_center_lat,
                    'center_lng': catchment_center_lng,
                    'viewport_size': _map_size_metadata(map_sizes['catchment']),
                    # Catchment is a fixed map — no client frame is baked in.
                    'manual_viewport': catchment_manual_frame,
                    'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION,
                    'map_label_version': MAP_LABEL_RENDER_VERSION,
                    'highlight_site': bool(highlight_site),
                    'zones': zones,
                    'landmarks_matrix': result.get('landmarks_matrix') or [],
                    'catchment_landmarks': rendered_landmarks,
                }
                result['placeholders'][placeholder] = catchment_path
                result['placeholders'][editable_placeholder] = editable_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, img_suffix, catchment_path, placeholder, effective_pres_id, metadata)
                add_map_image(tenant_id, editable_suffix, editable_path, editable_placeholder, effective_pres_id, metadata)

    return result
