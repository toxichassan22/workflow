

def _get_cached_map_images(tenant_id, presentation_id, expected_lat=None, expected_lng=None, expected_highlight_site=None):
    """Return existing map images for a tenant/presentation if any exist."""
    from db import get_map_images
    existing = get_map_images(tenant_id, presentation_id=presentation_id)
    if not existing:
        return None
    placeholders = {}
    metadata_by_type = {}
    found_types = set()
    for img in existing:
        image_type = img['image_type']
        if image_type in metadata_by_type or not os.path.exists(img['file_path']):
            continue
        found_types.add(image_type)
        placeholders[img['placeholder']] = img['file_path']
        try:
            metadata_by_type[image_type] = json.loads(img.get('metadata_json') or '{}')
        except Exception:
            metadata_by_type[image_type] = {}
    if not placeholders:
        return None
    if any(
        image_type.startswith('access')
        and metadata_by_type.get(image_type, {}).get('access_roads_version') != ACCESS_ROADS_RENDER_VERSION
        for image_type in found_types
    ):
        return None
    if any(
        metadata_by_type.get(image_type, {}).get('map_highlight_version') != MAP_HIGHLIGHT_RENDER_VERSION
        for image_type in found_types
    ):
        return None
    if any(
        metadata_by_type.get(image_type, {}).get('map_label_version') != MAP_LABEL_RENDER_VERSION
        for image_type in found_types
    ):
        return None
    if expected_highlight_site is not None and any(
        metadata_by_type.get(image_type, {}).get('highlight_site') is not bool(expected_highlight_site)
        for image_type in found_types
    ):
        return None
    locations = set()
    for metadata in metadata_by_type.values():
        try:
            if metadata.get('lat') is not None and metadata.get('lng') is not None:
                locations.add((round(float(metadata.get('lat')), 6), round(float(metadata.get('lng')), 6)))
        except (TypeError, ValueError):
            return None
    if len(locations) > 1:
        return None
    if expected_lat is not None and expected_lng is not None and locations:
        cached_lat, cached_lng = next(iter(locations))
        if abs(cached_lat - float(expected_lat)) >= 1e-5 or abs(cached_lng - float(expected_lng)) >= 1e-5:
            return None
    found_base = {t.split('_')[0] for t in found_types}
    meta = next((m for t, m in metadata_by_type.items() if t.startswith('overview')), None)
    if meta is None:
        meta = next(iter(metadata_by_type.values()), {})
    landmarks = next((m.get('landmarks') for m in metadata_by_type.values() if m.get('landmarks')), [])
    landmarks_matrix = next((m.get('landmarks_matrix') for m in metadata_by_type.values() if m.get('landmarks_matrix')), [])
    access_roads = next((m.get('access_roads') for m in metadata_by_type.values() if m.get('access_roads')), [])
    catchment_landmarks = next((m.get('catchment_landmarks') for m in metadata_by_type.values() if m.get('catchment_landmarks')), [])
    landmark_map_items = next((m.get('landmark_map_items') for m in metadata_by_type.values() if m.get('landmark_map_items')), [])
    zooms = {
        image_type: meta['zoom'] for image_type, meta in metadata_by_type.items()
        if isinstance(meta, dict) and meta.get('zoom') is not None
    }
    centers = {
        image_type: _stored_map_frame_center(item['center_lat'], item['center_lng'], item)
        for image_type, item in metadata_by_type.items()
        if isinstance(item, dict) and item.get('center_lat') is not None and item.get('center_lng') is not None
    }
    return {
        'lat': meta.get('lat'),
        'lng': meta.get('lng'),
        'placeholders': placeholders,
        'landmarks': landmarks,
        'landmarks_matrix': landmarks_matrix,
        'access_roads': access_roads,
        'catchment_landmarks': catchment_landmarks,
        'landmark_map_items': landmark_map_items,
        'zooms': zooms,
        'centers': centers,
        'found_types': found_types,
        'found_base': found_base,
        'cached': True,
    }


def _calculate_map_zooms(polygon_coords):
    """Choose presentation-friendly zoom levels for a polygon and its context."""
    zooms = {'overview': 17, 'landmarks': 16, 'access': 18, 'catchment': 12}
    if not polygon_coords or len(polygon_coords) < 3:
        return zooms
    try:
        lats = [point[0] for point in polygon_coords]
        lngs = [point[1] for point in polygon_coords]
        max_dim = max(max(lats) - min(lats), max(lngs) - min(lngs))
        if max_dim <= 0:
            return zooms
        target_pixels = 1280 * 2 * 0.45
        suggested_zoom = math.floor(math.log2((target_pixels * 360) / (max_dim * 256 * 2))) - 1
        # A 7,000 sqm plot is invisible at zoom 17, and the croquis boundary is exact, so
        # the plot view is allowed to go all the way in.
        overview_zoom = max(13, min(19, suggested_zoom))
        zooms.update({
            'overview': overview_zoom,
            'landmarks': max(14, min(17, overview_zoom - 2)),
            'access': max(15, min(17, overview_zoom)),
            'catchment': max(12, min(14, overview_zoom - 4)),
        })
    except (TypeError, ValueError, OverflowError) as error:
        print(f'[DYNAMIC ZOOM ERROR] {error}')
    return zooms


def _resolve_map_coordinates(project_data, tenant_id):
    address = project_data.get('location_address') or project_data.get('location', '')
    maps_link = (
        (address if str(address).startswith('http') else '') or
        project_data.get('location_maps_link') or project_data.get('maps_link')
    )
    confirmed = project_data.get('location_coordinates_confirmed')
    if isinstance(confirmed, str):
        confirmed = confirmed.strip().lower() in {'true', '1', 'yes'}
    lat = _extract_coordinate(
        project_data.get('location_lat') or project_data.get('locationLat') or
        project_data.get('latitude') or project_data.get('lat')
    )
    lng = _extract_coordinate(
        project_data.get('location_lng') or project_data.get('locationLng') or
        project_data.get('longitude') or project_data.get('lng')
    )
    if not confirmed:
        linked_coords = extract_coords_from_maps_link(maps_link) if maps_link else None
        if linked_coords:
            lat, lng = linked_coords['lat'], linked_coords['lng']
        elif maps_link:
            return None, None
    if (lat is None or lng is None) and address and not str(address).startswith('http'):
        geo = geocode_address(address, tenant_id=tenant_id)
        if geo.get('success'):
            lat, lng = geo['lat'], geo['lng']
    return lat, lng


def _overview_polygon(project_data, highlight_site):
    if not highlight_site:
        return None
    value = project_data.get('location_polygon')
    try:
        if isinstance(value, str):
            points = [
                (float(lat.strip()), float(lng.strip()))
                for item in value.split(';') if ',' in item
                for lat, lng in [item.split(',', 1)]
            ]
        elif isinstance(value, list):
            points = [(float(item[0]), float(item[1])) for item in value if len(item) >= 2]
        else:
            points = []
    except (TypeError, ValueError):
        points = []
    return points if len(points) >= 3 else None


def _fetch_map_base(center_lat, center_lng, active_maptype, zoom, styles, tenant_id, language='ar', size=(1280, 720)):
    """Fetch the raw provider base for a frame when its cache file is gone.

    Recompose normally rebuilds a missing editable sidecar from the cached raw
    map. Legacy maps and wiped map dirs have no cache file either — without this
    fetch the recompose would silently keep the baked render and the client edit
    overlay would have nothing to draw on. Uses the same cache key as
    generation, so a successful call also refills the cache for later edits.
    """
    fetched = get_static_map(center_lat, center_lng, zoom=zoom, paths=None,
                             size=size, maptype=active_maptype, styles=styles,
                             language=language)
    if not fetched.get('success'):
        return None
    _record_maps_call(tenant_id)
    return fetched.get('path')


def _recompose_overview_map(project_data, tenant_id, effective_id, highlight_site, draft_id=None):
    from db import add_map_image, get_map_images, update_map_image
    rows = get_map_images(tenant_id, presentation_id=effective_id, draft_id=draft_id)
    by_type = {}
    for row in rows:
        if row.get('image_type') not in by_type and os.path.isfile(row.get('file_path') or ''):
            by_type[row['image_type']] = row
    lat = _extract_coordinate(
        project_data.get('location_lat') or project_data.get('locationLat') or
        project_data.get('latitude') or project_data.get('lat')
    )
    lng = _extract_coordinate(
        project_data.get('location_lng') or project_data.get('locationLng') or
        project_data.get('longitude') or project_data.get('lng')
    )
    if lat is None or lng is None:
        return {'error': 'لم يتم العثور على إحداثيات الموقع المعتمدة'}
    polygon = _overview_polygon(project_data, highlight_site)
    # Map type and chrome are platform-fixed: no company or project setting
    # carries map_styles, draw_compass or draw_inset any more.
    draw_compass = True
    draw_inset = True
    map_lang = map_language(project_data)
    # Same editable-sidecar rebuild the other three maps already had: a legacy or
    # cross-scope overview map that kept only its marked row could never recompose,
    # so the section edit overlay and the designer chat kept serving the old file.
    for final_type, editable_type in (
        ('overview', 'overview_editable'),
        ('overview_satellite', 'overview_satellite_editable'),
        ('overview_roadmap', 'overview_roadmap_editable'),
    ):
        final = by_type.get(final_type)
        if not final or editable_type in by_type:
            continue
        try:
            metadata = json.loads(final.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        active_maptype = 'roadmap' if final_type.endswith('_roadmap') else 'satellite'
        styles = SATELLITE_WITH_LABELS_STYLES if active_maptype == 'satellite' else []
        cached_base = _map_cache_path(center_lat, center_lng, active_maptype, zoom, None, None, _stored_map_viewport_size(metadata), styles, language=map_lang)
        if not os.path.isfile(cached_base):
            cached_base = _fetch_map_base(center_lat, center_lng, active_maptype, zoom, styles, tenant_id, language=map_lang, size=_stored_map_viewport_size(metadata))
            if not cached_base:
                continue
        editable_path = _unique_map_path(tenant_id, effective_id, editable_type)
        shutil.copyfile(cached_base, editable_path)
        if active_maptype == 'satellite':
            _apply_sepia_tone(editable_path, intensity=0.35)
            _apply_map_overlay(editable_path, dark_factor=0.12)
        if draw_compass:
            _draw_compass(editable_path, position='top-right', language=map_lang)
        if draw_inset:
            _draw_inset_map(editable_path, lat, lng, inset_size=180, language=map_lang)
        editable_placeholder = str(final.get('placeholder') or '')[:-2] + '_EDITABLE##'
        editable_id = add_map_image(tenant_id, editable_type, editable_path, editable_placeholder, effective_id, metadata)
        by_type[editable_type] = {
            'id': editable_id,
            'image_type': editable_type,
            'file_path': editable_path,
            'placeholder': editable_placeholder,
            'metadata_json': json.dumps(metadata, ensure_ascii=False),
        }
    placeholders = {}
    centers = {}
    zooms = {}
    for editable_type in ('overview_editable', 'overview_satellite_editable', 'overview_roadmap_editable'):
        editable = by_type.get(editable_type)
        if not editable:
            continue
        try:
            metadata = json.loads(editable.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        final_type = editable_type.replace('_editable', '')
        final_placeholder = str(editable.get('placeholder') or '').replace('_EDITABLE##', '##')
        final_path = _unique_map_path(tenant_id, effective_id, final_type)
        shutil.copyfile(editable['file_path'], final_path)
        if polygon and not _draw_site_highlight(final_path, center_lat, center_lng, zoom, size=_stored_map_viewport_size(metadata), polygon_coords=polygon, auto_detect_polygon=False, auto_detected=False):
            continue
        if not _overlay_markers(final_path, center_lat, center_lng, zoom, _build_markers(lat, lng), size=_stored_map_viewport_size(metadata)):
            continue
        next_metadata = {**metadata, 'lat': lat, 'lng': lng, 'highlight_site': bool(highlight_site)}
        final = by_type.get(final_type)
        if final:
            update_map_image(final['id'], tenant_id, final_path, final_placeholder, next_metadata)
        else:
            add_map_image(tenant_id, final_type, final_path, final_placeholder, effective_id, next_metadata)
        update_map_image(editable['id'], tenant_id, editable['file_path'], editable['placeholder'], next_metadata)
        placeholders[final_placeholder] = final_path
        placeholders[editable['placeholder']] = editable['file_path']
        centers['overview'] = _stored_map_frame_center(center_lat, center_lng, metadata)
        zooms['overview'] = zoom
    if not placeholders:
        return {'error': 'نسخة الخريطة النظيفة غير متاحة'}
    return {
        'placeholders': placeholders,
        'centers': centers,
        'zooms': zooms,
        'site_polygon': [list(point) for point in polygon] if polygon else [],
    }


def recompose_overview_map(project_data, tenant_id, presentation_id=None, draft_id=None, highlight_site=True):
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None)
    if not effective_id:
        return {'error': 'معرّف العرض أو المسودة مطلوب'}
    lock_key = (str(tenant_id), str(effective_id))
    with _MAP_GENERATION_LOCKS_GUARD:
        lock = _MAP_GENERATION_LOCKS.setdefault(lock_key, threading.Lock())
    with lock:
        return _recompose_overview_map(project_data, tenant_id, effective_id, highlight_site,
                                       draft_id=draft_id)


def _recompose_access_map(project_data, tenant_id, effective_id, draft_id=None):
    from db import add_map_image, get_map_images, update_map_image
    rows = get_map_images(tenant_id, presentation_id=effective_id, draft_id=draft_id)
    by_type = {}
    for row in rows:
        if row.get('image_type') not in by_type and os.path.isfile(row.get('file_path') or ''):
            by_type[row['image_type']] = row
    lat = _extract_coordinate(
        project_data.get('location_lat') or project_data.get('locationLat') or
        project_data.get('latitude') or project_data.get('lat')
    )
    lng = _extract_coordinate(
        project_data.get('location_lng') or project_data.get('locationLng') or
        project_data.get('longitude') or project_data.get('lng')
    )
    if lat is None or lng is None:
        return {'error': 'لم يتم العثور على إحداثيات الموقع المعتمدة'}
    draw_compass = True
    map_lang = map_language(project_data)
    for final_type, editable_type in (
        ('access', 'access_editable'),
        ('access_satellite', 'access_satellite_editable'),
        ('access_roadmap', 'access_roadmap_editable'),
    ):
        final = by_type.get(final_type)
        if not final or editable_type in by_type:
            continue
        try:
            metadata = json.loads(final.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        # The unsuffixed access map is the roadmap render — only an explicit
        # _satellite suffix means satellite.
        active_maptype = 'satellite' if final_type.endswith('_satellite') else 'roadmap'
        styles = SATELLITE_CLEAN_STYLES if active_maptype == 'satellite' else ACCESS_ROADMAP_STYLES
        cached_base = _map_cache_path(center_lat, center_lng, active_maptype, zoom, None, None, _stored_map_viewport_size(metadata), styles, language=map_lang)
        if not os.path.isfile(cached_base):
            cached_base = _fetch_map_base(center_lat, center_lng, active_maptype, zoom, styles, tenant_id, language=map_lang, size=_stored_map_viewport_size(metadata))
            if not cached_base:
                continue
        editable_path = _unique_map_path(tenant_id, effective_id, editable_type)
        shutil.copyfile(cached_base, editable_path)
        if active_maptype == 'satellite':
            _apply_sepia_tone(editable_path, intensity=0.35)
            _apply_map_overlay(editable_path, dark_factor=0.10)
        if draw_compass:
            _draw_compass(editable_path, position='top-right', language=map_lang)
        editable_placeholder = str(final.get('placeholder') or '')[:-2] + '_EDITABLE##'
        editable_id = add_map_image(tenant_id, editable_type, editable_path, editable_placeholder, effective_id, metadata)
        by_type[editable_type] = {
            'id': editable_id,
            'image_type': editable_type,
            'file_path': editable_path,
            'placeholder': editable_placeholder,
            'metadata_json': json.dumps(metadata, ensure_ascii=False),
        }
    placeholders = {}
    centers = {}
    zooms = {}
    access_roads = []
    for editable_type in ('access_editable', 'access_satellite_editable', 'access_roadmap_editable'):
        editable = by_type.get(editable_type)
        if not editable:
            continue
        try:
            metadata = json.loads(editable.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        final_type = editable_type.replace('_editable', '')
        final_placeholder = str(editable.get('placeholder') or '').replace('_EDITABLE##', '##')
        final_path = _unique_map_path(tenant_id, effective_id, final_type)
        shutil.copyfile(editable['file_path'], final_path)
        rendered_roads = _draw_access_roads(
            final_path, center_lat, center_lng, zoom, scale=2, project_data=project_data,
            tenant_id=tenant_id, origin_lat=lat, origin_lng=lng, allow_discovery=False
        ) or []
        if not _overlay_markers(
            final_path, center_lat, center_lng, zoom,
            [{'lat': lat, 'lng': lng, 'color': MARKER_COLOR_SITE, 'type': 'site', 'label': None}],
            size=_stored_map_viewport_size(metadata)
        ):
            continue
        next_metadata = {
            **metadata,
            'lat': lat,
            'lng': lng,
            'access_roads': rendered_roads,
            'access_roads_version': ACCESS_ROADS_RENDER_VERSION,
            'map_label_version': MAP_LABEL_RENDER_VERSION,
        }
        final = by_type.get(final_type)
        if final:
            update_map_image(final['id'], tenant_id, final_path, final_placeholder, next_metadata)
        else:
            add_map_image(tenant_id, final_type, final_path, final_placeholder, effective_id, next_metadata)
        update_map_image(editable['id'], tenant_id, editable['file_path'], editable['placeholder'], next_metadata)
        placeholders[final_placeholder] = final_path
        placeholders[editable['placeholder']] = editable['file_path']
        centers['access'] = _stored_map_frame_center(center_lat, center_lng, metadata)
        zooms['access'] = zoom
        if not access_roads:
            access_roads = rendered_roads
    if not placeholders:
        return {'error': 'نسخة خريطة الطرق النظيفة غير متاحة'}
    return {'placeholders': placeholders, 'centers': centers, 'zooms': zooms, 'access_roads': access_roads}


def recompose_access_map(project_data, tenant_id, presentation_id=None, draft_id=None):
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None)
    if not effective_id:
        return {'error': 'معرّف العرض أو المسودة مطلوب'}
    lock_key = (str(tenant_id), str(effective_id))
    with _MAP_GENERATION_LOCKS_GUARD:
        lock = _MAP_GENERATION_LOCKS.setdefault(lock_key, threading.Lock())
    with lock:
        scope_ctx = maps_usage_ctx('access', tenant_id=tenant_id,
                                   presentation_id=presentation_id, draft_id=draft_id)
        with maps_usage_scope(scope_ctx):
            return _recompose_access_map(project_data, tenant_id, effective_id,
                                         draft_id=draft_id)


def _recompose_catchment_map(project_data, tenant_id, effective_id, draft_id=None):
    from db import add_map_image, get_map_images, update_map_image
    rows = get_map_images(tenant_id, presentation_id=effective_id, draft_id=draft_id)
    by_type = {}
    for row in rows:
        if row.get('image_type') not in by_type and os.path.isfile(row.get('file_path') or ''):
            by_type[row['image_type']] = row
    lat = _extract_coordinate(project_data.get('location_lat') or project_data.get('locationLat') or project_data.get('lat'))
    lng = _extract_coordinate(project_data.get('location_lng') or project_data.get('locationLng') or project_data.get('lng'))
    if lat is None or lng is None:
        return {'error': 'لم يتم العثور على إحداثيات الموقع المعتمدة'}
    landmarks = project_data.get('catchment_map_landmarks') or []
    if isinstance(landmarks, str):
        try:
            landmarks = json.loads(landmarks)
        except (TypeError, ValueError):
            landmarks = []
    if not isinstance(landmarks, list):
        landmarks = []
    draw_compass = True
    rings = catchment_rings(_parse_catchment_zones(project_data.get('catchment_areas', '')))
    map_lang = map_language(project_data)
    ring_km = max([ring['km'] for ring in rings] + [0.0])
    # A stored road point can sit at the feature's remote endpoint — snap those
    # rows back near the site before the frame is measured around them.
    _snap_road_landmarks(
        landmarks, project_data, lat, lng, language=map_lang,
        search_radius_m=max(20000, int(ring_km * 1000)))
    # The stored frame was fitted to the rings only — a selected landmark beyond
    # it was drawn off-canvas and dropped. Refit on the directional spread of
    # rings + sent landmarks so every checked row stays drawable without
    # mirroring empty space opposite a far row; a tighter existing editable is
    # rebuilt.
    for final_type, editable_type in (
        ('catchment', 'catchment_editable'),
        ('catchment_satellite', 'catchment_satellite_editable'),
        ('catchment_roadmap', 'catchment_roadmap_editable'),
    ):
        final = by_type.get(final_type)
        existing = by_type.get(editable_type)
        source = final or existing
        if source is None:
            continue
        try:
            metadata = json.loads(source.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        # The catchment map is a fixed frame fitted to content — a wider stored
        # frame only ever meant the fit was stretched by a badly resolved
        # landmark, so the recompose refits and recentres on the real spread.
        frame_fit = catchment_frame_fit(
            lat, lng, ring_km, landmarks, size=_stored_map_viewport_size(metadata))
        if frame_fit:
            frame_zoom, frame_center_lat, frame_center_lng = frame_fit
        else:
            frame_zoom, frame_center_lat, frame_center_lng = zoom, center_lat, center_lng
        if existing is not None:
            try:
                existing_meta = json.loads(existing.get('metadata_json') or '{}')
                existing_zoom = int(existing_meta.get('zoom'))
                existing_center = (
                    float(existing_meta.get('center_lat')),
                    float(existing_meta.get('center_lng')))
            except (TypeError, ValueError, json.JSONDecodeError):
                existing_zoom, existing_center = None, None
            # Only an identical frame skips the rebuild — a wider stored one is
            # exactly the stale-extent case this refit exists to repair.
            if (existing_zoom is not None and existing_zoom == frame_zoom
                    and existing_center is not None
                    and _distance_meters(existing_center[0], existing_center[1],
                                         frame_center_lat, frame_center_lng) < 25):
                continue
        active_maptype = 'roadmap' if final_type.endswith('_roadmap') else 'satellite'
        styles = SATELLITE_WIDE_STYLES if active_maptype == 'satellite' else SATELLITE_WITH_LABELS_STYLES
        cached_base = _map_cache_path(frame_center_lat, frame_center_lng, active_maptype, frame_zoom, None, None, _stored_map_viewport_size(metadata), styles, language=map_lang)
        if not os.path.isfile(cached_base):
            cached_base = _fetch_map_base(frame_center_lat, frame_center_lng, active_maptype, frame_zoom, styles, tenant_id, language=map_lang, size=_stored_map_viewport_size(metadata))
            if not cached_base:
                continue
        editable_path = _unique_map_path(tenant_id, effective_id, editable_type)
        shutil.copyfile(cached_base, editable_path)
        if active_maptype == 'satellite':
            _apply_sepia_tone(editable_path, intensity=0.35)
            _apply_map_overlay(editable_path, dark_factor=0.15)
        if rings:
            _draw_catchment_zones(editable_path, frame_center_lat, frame_center_lng, frame_zoom, rings, scale=2,
                                  site_lat=lat, site_lng=lng)
        if draw_compass:
            _draw_compass(editable_path, position='top-right', language=map_lang)
        editable_placeholder = (
            str(final.get('placeholder') or '')[:-2] + '_EDITABLE##'
            if final else str(existing.get('placeholder') or '')
        )
        metadata = {**metadata, 'zoom': frame_zoom, 'center_lat': frame_center_lat,
                    'center_lng': frame_center_lng, 'manual_viewport': False}
        if existing is not None:
            update_map_image(existing['id'], tenant_id, editable_path, editable_placeholder, metadata)
            editable_id = existing['id']
        else:
            editable_id = add_map_image(tenant_id, editable_type, editable_path, editable_placeholder, effective_id, metadata)
        by_type[editable_type] = {
            'id': editable_id,
            'image_type': editable_type,
            'file_path': editable_path,
            'placeholder': editable_placeholder,
            'metadata_json': json.dumps(metadata, ensure_ascii=False),
        }
    placeholders = {}
    centers = {}
    zooms = {}
    rendered_landmarks = []
    for editable_type in ('catchment_editable', 'catchment_satellite_editable', 'catchment_roadmap_editable'):
        editable = by_type.get(editable_type)
        if not editable:
            continue
        try:
            metadata = json.loads(editable.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        final_type = editable_type.replace('_editable', '')
        final_placeholder = str(editable.get('placeholder') or '').replace('_EDITABLE##', '##')
        final_path = _unique_map_path(tenant_id, effective_id, final_type)
        shutil.copyfile(editable['file_path'], final_path)
        # An empty payload list means the client holds no resolved coordinates
        # (map predates editable sidecars, or its table rows were never
        # geocoded). Redraw the render set stored on the row instead of wiping
        # the markers off the approved image.
        draw_landmarks = landmarks if landmarks else (metadata.get('catchment_landmarks') or [])
        label_positions = project_data.get('catchment_label_positions')
        if not label_positions:
            label_positions = {item['name']: item['label_point'] for item in draw_landmarks
                               if isinstance(item, dict) and item.get('name') and item.get('label_point')}
        current_landmarks = _draw_catchment_markers(
            final_path, center_lat, center_lng, zoom, draw_landmarks,
            label_positions, scale=2, site_lat=lat, site_lng=lng
        )
        next_metadata = {**metadata, 'lat': lat, 'lng': lng, 'catchment_landmarks': current_landmarks}
        final = by_type.get(final_type)
        if final:
            update_map_image(final['id'], tenant_id, final_path, final_placeholder, next_metadata)
        else:
            add_map_image(tenant_id, final_type, final_path, final_placeholder, effective_id, next_metadata)
        update_map_image(editable['id'], tenant_id, editable['file_path'], editable['placeholder'], next_metadata)
        placeholders[final_placeholder] = final_path
        placeholders[editable['placeholder']] = editable['file_path']
        centers['catchment'] = _stored_map_frame_center(center_lat, center_lng, metadata)
        zooms['catchment'] = zoom
        if not rendered_landmarks:
            rendered_landmarks = current_landmarks
    if not placeholders:
        return {'error': 'نسخة خريطة المنطقة النظيفة غير متاحة'}
    return {
        'placeholders': placeholders,
        'centers': centers,
        'zooms': zooms,
        'catchment_landmarks': rendered_landmarks,
    }


def recompose_catchment_map(project_data, tenant_id, presentation_id=None, draft_id=None):
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None)
    if not effective_id:
        return {'error': 'معرّف العرض أو المسودة مطلوب'}
    lock_key = (str(tenant_id), str(effective_id))
    with _MAP_GENERATION_LOCKS_GUARD:
        lock = _MAP_GENERATION_LOCKS.setdefault(lock_key, threading.Lock())
    with lock:
        scope_ctx = maps_usage_ctx('catchment', tenant_id=tenant_id,
                                   presentation_id=presentation_id, draft_id=draft_id)
        with maps_usage_scope(scope_ctx):
            return _recompose_catchment_map(project_data, tenant_id, effective_id,
                                            draft_id=draft_id)


def _recompose_landmarks_map(project_data, tenant_id, effective_id, draft_id=None):
    from db import add_map_image, get_map_images, update_map_image
    rows = get_map_images(tenant_id, presentation_id=effective_id, draft_id=draft_id)
    by_type = {}
    for row in rows:
        if row.get('image_type') not in by_type and os.path.isfile(row.get('file_path') or ''):
            by_type[row['image_type']] = row
    site_lat = _extract_coordinate(project_data.get('location_lat') or project_data.get('locationLat') or project_data.get('lat'))
    site_lng = _extract_coordinate(project_data.get('location_lng') or project_data.get('locationLng') or project_data.get('lng'))
    if site_lat is None or site_lng is None:
        return {'error': 'لم يتم العثور على إحداثيات الموقع المعتمدة'}
    landmarks = project_data.get('landmark_map_items') or []
    if isinstance(landmarks, str):
        try:
            landmarks = json.loads(landmarks)
        except (TypeError, ValueError):
            landmarks = []
    if not isinstance(landmarks, list):
        landmarks = []
    draw_compass = True
    map_lang = map_language(project_data)
    # Road-named rows keep their drawn-road anchor near the site — a geocoded
    # endpoint kilometres out would otherwise pin the marker off-frame.
    _snap_road_landmarks(landmarks, project_data, site_lat, site_lng,
                         language=map_lang, search_radius_m=20000)
    # The landmarks frame mirrors generation: content-fitted over the selected
    # landmarks and centred on the plot (or the site when no boundary exists).
    frame_lat, frame_lng = site_lat, site_lng
    poly_data = project_data.get('location_polygon')
    try:
        if isinstance(poly_data, str):
            poly_pts = [
                tuple(float(v.strip()) for v in pt.split(',', 1))
                for pt in poly_data.split(';') if ',' in pt
            ]
        elif isinstance(poly_data, list):
            poly_pts = [(float(pt[0]), float(pt[1])) for pt in poly_data if len(pt) >= 2]
        else:
            poly_pts = []
        if len(poly_pts) >= 3:
            centroid_lat = sum(point[0] for point in poly_pts) / len(poly_pts)
            centroid_lng = sum(point[1] for point in poly_pts) / len(poly_pts)
            if (min(_distance_meters(site_lat, site_lng, p[0], p[1]) for p in poly_pts) <= 500
                    or _distance_meters(site_lat, site_lng, centroid_lat, centroid_lng) <= 500):
                frame_lat = (min(p[0] for p in poly_pts) + max(p[0] for p in poly_pts)) / 2
                frame_lng = (min(p[1] for p in poly_pts) + max(p[1] for p in poly_pts)) / 2
    except (TypeError, ValueError, IndexError):
        pass
    landmark_km = 0.0
    for item in landmarks:
        try:
            landmark_km = max(landmark_km, _distance_meters(
                site_lat, site_lng, float(item.get('lat')), float(item.get('lng'))) / 1000.0)
        except (TypeError, ValueError):
            continue
    needed_zoom = (
        zoom_for_radius_km(site_lat, max(0.6, min(20.0, landmark_km * 1.1)))
        if landmark_km else None
    )
    for final_type, editable_type in (
        ('landmarks', 'landmarks_editable'),
        ('landmarks_satellite', 'landmarks_satellite_editable'),
        ('landmarks_roadmap', 'landmarks_roadmap_editable'),
    ):
        final = by_type.get(final_type)
        existing = by_type.get(editable_type)
        source = final or existing
        if source is None:
            continue
        try:
            metadata = json.loads(source.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if needed_zoom is not None:
            frame_zoom, frame_center_lat, frame_center_lng = needed_zoom, frame_lat, frame_lng
        else:
            frame_zoom, frame_center_lat, frame_center_lng = zoom, center_lat, center_lng
        if existing is not None:
            try:
                existing_meta = json.loads(existing.get('metadata_json') or '{}')
                existing_zoom = int(existing_meta.get('zoom'))
                existing_center = (
                    float(existing_meta.get('center_lat')),
                    float(existing_meta.get('center_lng')))
            except (TypeError, ValueError, json.JSONDecodeError):
                existing_zoom, existing_center = None, None
            # Identical frame → keep the editable; a wider one is the stale
            # extent this refit repairs.
            if (existing_zoom is not None and existing_zoom == frame_zoom
                    and existing_center is not None
                    and _distance_meters(existing_center[0], existing_center[1],
                                         frame_center_lat, frame_center_lng) < 25):
                continue
        active_maptype = 'roadmap' if final_type.endswith('_roadmap') else 'satellite'
        styles = SATELLITE_WIDE_STYLES if active_maptype == 'satellite' else SATELLITE_WITH_LABELS_STYLES
        cached_base = _map_cache_path(frame_center_lat, frame_center_lng, active_maptype, frame_zoom, None, None, _stored_map_viewport_size(metadata), styles, language=map_lang)
        if not os.path.isfile(cached_base):
            cached_base = _fetch_map_base(frame_center_lat, frame_center_lng, active_maptype, frame_zoom, styles, tenant_id, language=map_lang, size=_stored_map_viewport_size(metadata))
            if not cached_base:
                continue
        editable_path = _unique_map_path(tenant_id, effective_id, editable_type)
        shutil.copyfile(cached_base, editable_path)
        if active_maptype == 'satellite':
            _apply_sepia_tone(editable_path, intensity=0.35)
            _apply_map_overlay(editable_path, dark_factor=0.20)
        if draw_compass:
            _draw_compass(editable_path, position='top-right', language=map_lang)
        editable_placeholder = (
            str(final.get('placeholder') or '')[:-2] + '_EDITABLE##'
            if final else str(existing.get('placeholder') or '')
        )
        metadata = {**metadata, 'zoom': frame_zoom, 'center_lat': frame_center_lat,
                    'center_lng': frame_center_lng, 'manual_viewport': False}
        if existing is not None:
            update_map_image(existing['id'], tenant_id, editable_path, editable_placeholder, metadata)
            editable_id = existing['id']
        else:
            editable_id = add_map_image(tenant_id, editable_type, editable_path, editable_placeholder, effective_id, metadata)
        by_type[editable_type] = {
            'id': editable_id,
            'image_type': editable_type,
            'file_path': editable_path,
            'placeholder': editable_placeholder,
            'metadata_json': json.dumps(metadata, ensure_ascii=False),
        }
    placeholders = {}
    centers = {}
    zooms = {}
    rendered_landmarks = []
    for editable_type in ('landmarks_editable', 'landmarks_satellite_editable', 'landmarks_roadmap_editable'):
        editable = by_type.get(editable_type)
        if not editable:
            continue
        try:
            metadata = json.loads(editable.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        final_type = editable_type.replace('_editable', '')
        final_placeholder = str(editable.get('placeholder') or '').replace('_EDITABLE##', '##')
        final_path = _unique_map_path(tenant_id, effective_id, final_type)
        shutil.copyfile(editable['file_path'], final_path)
        # Same empty-payload guard as the catchment recompose: fall back to the
        # render set stored on the row rather than wiping the approved markers.
        draw_landmarks = landmarks if landmarks else (metadata.get('landmark_map_items') or [])
        label_positions = project_data.get('landmark_label_positions')
        if not label_positions:
            label_positions = {item['name']: item['label_point'] for item in draw_landmarks
                               if isinstance(item, dict) and item.get('name') and item.get('label_point')}
        current_landmarks = _draw_catchment_markers(
            final_path, center_lat, center_lng, zoom, draw_landmarks,
            label_positions, scale=2, site_lat=site_lat, site_lng=site_lng
        )
        next_metadata = {**metadata, 'lat': site_lat, 'lng': site_lng, 'landmark_map_items': current_landmarks}
        final = by_type.get(final_type)
        if final:
            update_map_image(final['id'], tenant_id, final_path, final_placeholder, next_metadata)
        else:
            add_map_image(tenant_id, final_type, final_path, final_placeholder, effective_id, next_metadata)
        update_map_image(editable['id'], tenant_id, editable['file_path'], editable['placeholder'], next_metadata)
        placeholders[final_placeholder] = final_path
        placeholders[editable['placeholder']] = editable['file_path']
        centers['landmarks'] = _stored_map_frame_center(center_lat, center_lng, metadata)
        zooms['landmarks'] = zoom
        if not rendered_landmarks:
            rendered_landmarks = current_landmarks
    if not placeholders:
        return {'error': 'نسخة خريطة المعالم النظيفة غير متاحة'}
    return {
        'placeholders': placeholders,
        'centers': centers,
        'zooms': zooms,
        'landmark_map_items': rendered_landmarks,
    }


def recompose_landmarks_map(project_data, tenant_id, presentation_id=None, draft_id=None):
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None)
    if not effective_id:
        return {'error': 'معرّف العرض أو المسودة مطلوب'}
    lock_key = (str(tenant_id), str(effective_id))
    with _MAP_GENERATION_LOCKS_GUARD:
        lock = _MAP_GENERATION_LOCKS.setdefault(lock_key, threading.Lock())
    with lock:
        scope_ctx = maps_usage_ctx('landmarks', tenant_id=tenant_id,
                                   presentation_id=presentation_id, draft_id=draft_id)
        with maps_usage_scope(scope_ctx):
            return _recompose_landmarks_map(project_data, tenant_id, effective_id,
                                            draft_id=draft_id)


def generate_all_map_images(project_data, tenant_id, presentation_id=None, force=False, branding=None, draft_id=None, highlight_site=True, usage_flow=None):
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None) or (project_data or {}).get('draft_id') or (project_data or {}).get('draftId') or 'unscoped'
    lock_key = (str(tenant_id), str(effective_id))
    with _MAP_GENERATION_LOCKS_GUARD:
        lock = _MAP_GENERATION_LOCKS.setdefault(lock_key, threading.Lock())
    with lock:
        flow = usage_flow if usage_flow in MAPS_USAGE_FLOWS else 'maps'
        scope_ctx = maps_usage_ctx(
            flow, tenant_id=tenant_id, presentation_id=presentation_id,
            draft_id=draft_id or (project_data or {}).get('draftId') or (project_data or {}).get('draft_id'))
        with maps_usage_scope(scope_ctx):
            return _generate_all_map_images(project_data, tenant_id, presentation_id, force, branding, draft_id, highlight_site)


def _unique_map_path(tenant_id, presentation_id, image_type):
    """Generate a unique file path for a map image."""
    safe_tenant = str(tenant_id).replace('-', '')[:12]
    pres_part = str(presentation_id).replace('-', '')[:12] if presentation_id else 'draft'
    filename = f"{safe_tenant}_{pres_part}_{image_type}_{uuid.uuid4().hex[:8]}.png"
    return os.path.join(MAPS_DIR, filename)


def _extract_coordinate(value):
    """Extract float coordinate from string or number."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        val_str = value.strip()
        if not val_str:
            return None
        match = re.search(r'(-?\d+\.\d+)', val_str)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
    return None


def _parse_landmarks_text(text, language='ar'):
    """Parse landmark text into structured list with name, duration_minutes, and distance_km."""
    if not text:
        return []
    landmarks = []
    for line in text.strip().split('\n'):
        line = line.strip().lstrip('-').lstrip('•').strip()
        if not line:
            continue

        duration = None
        distance = None

        dur_match = re.search(r'(\d+)\s*(?:دقيقة|دقائق|د|min|mins|minutes)', line, re.IGNORECASE)
        if dur_match:
            duration = int(dur_match.group(1))

        dist_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:كم|كـم|km|kms|kilometer|kilometers)', line, re.IGNORECASE)
        if dist_match:
            distance = float(dist_match.group(1))

        clean_name = line
        if dur_match:
            clean_name = clean_name.replace(dur_match.group(0), '')
        if dist_match:
            clean_name = clean_name.replace(dist_match.group(0), '')

        category = ''
        category_match = re.search(r'(?:^|\s)[—\-]\s*(ترفيهي|تعليمي|صحي|تجاري|ديني(?: ومركزي)?|ثقافي/سياحي|حكومي/خدمي|اجتماعي/خدمي|Leisure|Education|Health|Retail|Religious|Culture/Tourism|Government/Services|Social/Services|Shopping|Transport|Public transit|Main corridor|Waterfront|Future development|Heritage & tourism|Business & logistics|Sports & events|Events|Coastal areas|Religious & central|Holy sites|Major projects|Religious tourism|Business & finance|Business & tech|Business & government|City center|Tourism & landmarks|Exhibitions & events|Nature & leisure|Logistics|Industry & logistics|Major landmark|Landmark)\s*(?:[—\-]|$)', clean_name, re.IGNORECASE)
        if category_match:
            category = category_match.group(1)
            clean_name = clean_name.replace(category_match.group(0), ' ')
        clean_name = re.sub(r'[\-\(\)\,\،\s—–]+', ' ', clean_name).strip()
        if not clean_name:
            clean_name = line

        landmarks.append({
            'name': clean_name,
            'category': category,
            'duration_minutes': duration,
            'distance_km': distance,
            'distance_text': f"{distance} {_distance_unit(language)}" if distance is not None else None,
            'lat': None,
            'lng': None,
        })
    return landmarks


def _landmark_row_selected(item):
    """Twin of slide_engine._landmark_row_selected — keep both in sync.

    Tolerant of string flags from older drafts («true», «1», «yes»); a checked
    row must render however it was stored.
    """
    for key in ('show_on_map', 'selected'):
        value = (item or {}).get(key)
        if value is True or str(value or '').strip().lower() in {'true', '1', 'yes'}:
            return True
    return False


def select_map_landmark_rows(structured, limit=7):
    """Return the approved landmark rows for a map without changing their input order.

    Every checked row renders — the client picks the count; with no selection the
    first ``limit`` rows show like before.
    """
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except (TypeError, ValueError):
            return []
    if not isinstance(structured, list):
        return []

    rows = [dict(item) for item in structured if isinstance(item, dict)]
    selected = [item for item in rows if _landmark_row_selected(item)]
    try:
        row_limit = max(0, min(7, int(limit)))
    except (TypeError, ValueError):
        row_limit = 7
    if selected:
        return selected
    return rows[:row_limit]


def _merge_landmark_data(landmarks, structured):
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except (TypeError, ValueError):
            return landmarks
    if not isinstance(structured, list):
        return landmarks

    def normalized_name(value):
        return re.sub(r'\s+', ' ', _strip_arabic_diacritics(str(value or '')).strip()).casefold()

    def numeric(value):
        if value in (None, ''):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    by_name = {normalized_name(item.get('name')): item for item in landmarks if item.get('name')}
    for item in structured:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or item.get('title') or item.get('description') or '').strip()
        key = normalized_name(name)
        if not key:
            continue
        target = by_name.get(key)
        if target is None:
            target = {
                'name': name,
                'category': item.get('category') or item.get('type') or '',
                'duration_minutes': item.get('duration_minutes') or item.get('duration_min'),
                'distance_km': item.get('distance_km') or item.get('distance'),
                'distance_text': item.get('distance_text'),
                'lat': None,
                'lng': None,
            }
            landmarks.append(target)
            by_name[key] = target
        else:
            target['name'] = name or target.get('name')
            if item.get('category') or item.get('type'):
                target['category'] = item.get('category') or item.get('type')
            for field in ('duration_minutes', 'duration_min', 'distance_km', 'distance', 'distance_text'):
                if target.get(field) in (None, '') and item.get(field) not in (None, ''):
                    target[field] = item[field]

        latitude = numeric(item.get('lat') or item.get('latitude'))
        longitude = numeric(item.get('lng') or item.get('longitude'))
        if latitude is not None and longitude is not None:
            target['lat'] = latitude
            target['lng'] = longitude
        distance_meters = numeric(item.get('distance_meters'))
        if distance_meters is not None:
            target['distance_meters'] = round(distance_meters)
        if item.get('manual_position'):
            target['manual_position'] = True
    return landmarks


def _snap_road_landmarks(items, project_data, site_lat, site_lng, language='ar', search_radius_m=50000):
    """Re-anchor road-named landmark rows near the site.

    A road name geocodes to a single point that can sit at the feature's remote
    end — the marker then lands kilometres out and the fitted frame zooms out to
    cover it. When the same road is drawn on the access map, its stored path is
    the truth: the marker belongs at the path's closest point to the site.
    Undrawn roads re-resolve through the Places candidate nearest the site.
    Markers the user placed by hand (``manual_position``) are never moved.
    """
    if not isinstance(items, list):
        return
    paths = []
    for key in ('manual_road_paths', 'access_roads_data'):
        raw = (project_data or {}).get(key)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = []
        for entry in raw or []:
            if not isinstance(entry, dict):
                continue
            road_name = str(entry.get('name') or '').strip()
            points = []
            for point in entry.get('points') or []:
                try:
                    points.append((float(point[0]), float(point[1])))
                except (TypeError, ValueError, IndexError):
                    continue
            if road_name and points:
                paths.append((road_name, points))
    for item in items:
        if not isinstance(item, dict) or item.get('manual_position'):
            continue
        names = [item.get('name'), item.get('name_src')]
        if not any(is_road_name(name) for name in names if name):
            continue
        old_lat, old_lng = item.get('lat'), item.get('lng')
        match = next((
            points for road_name, points in paths
            if any(is_same_road_name(name, road_name) for name in names if name)), None)
        if match:
            item['lat'], item['lng'] = min(
                match, key=lambda pt: _distance_meters(site_lat, site_lng, pt[0], pt[1]))
        else:
            place = find_place_near(item.get('name'), site_lat, site_lng,
                                    radius_m=search_radius_m, language=language)
            if not (place and place.get('lat') is not None and place.get('lng') is not None):
                continue
            item['lat'], item['lng'] = place['lat'], place['lng']
        item['distance_meters'] = round(_distance_meters(
            site_lat, site_lng, float(item['lat']), float(item['lng'])))
        moved_m = None
        try:
            moved_m = _distance_meters(float(old_lat), float(old_lng), float(item['lat']), float(item['lng']))
        except (TypeError, ValueError):
            moved_m = None
        if moved_m is None or moved_m > 250:
            # The stored label point was drawn beside the old marker — a moved
            # pin would leave it stranded off-frame, so the label re-seats.
            item.pop('label_point', None)
            for labels_key in ('catchment_label_positions', 'landmark_label_positions'):
                labels = (project_data or {}).get(labels_key)
                if isinstance(labels, dict):
                    labels.pop(item.get('name'), None)
            print(f"[LANDMARKS] road marker '{item.get('name')}' snapped near the site")


def _parse_catchment_zones(text):
    """Parse catchment zones text into zone objects.

    Supports both the legacy formats ("10 دقائق", "5 دقائق: مجمع الراشد") and the
    structured table format ("مجمع الراشد — 4.2 كم — 5 دقائق")."""
    default_zones = [{'minutes': 10, 'km': 8}, {'minutes': 20, 'km': 16}, {'minutes': 35, 'km': 28}]
    if not text:
        return default_zones
    if isinstance(text, list):
        zones = []
        for item in text:
            if not isinstance(item, dict):
                continue
            km = item.get('km') or item.get('distance_km') or item.get('distance')
            minutes = item.get('minutes') or item.get('duration_minutes') or item.get('duration_min')
            try:
                minutes = int(float(minutes)) if minutes not in (None, '') else None
            except (TypeError, ValueError):
                minutes = None
            try:
                km = float(km) if km not in (None, '') else None
            except (TypeError, ValueError):
                km = None
            if km is None and minutes:
                km = minutes * 0.8 / 1.60934
            if not km or km <= 0:
                continue
            zone = {'minutes': minutes, 'km': km}
            label = str(item.get('label') or item.get('name') or item.get('area') or '').strip()
            if label:
                zone['label'] = label
            zones.append(zone)
        return zones or default_zones
    if not isinstance(text, str):
        return default_zones
    zones = []
    for line in text.strip().split('\n'):
        line = line.strip().lstrip('-').lstrip('•').strip()
        if not line:
            continue
        dur_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:دقيقة|دقائق|min|mins|minutes)', line, re.IGNORECASE)
        dist_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:كم|كـم|km|kms|kilometer|kilometers)', line, re.IGNORECASE)
        if dur_match:
            minutes = int(float(dur_match.group(1)))
        else:
            digits = ''.join([c for c in line if c.isdigit()])
            if not digits:
                continue
            minutes = int(digits)
        zone = {'minutes': minutes, 'km': minutes * 0.8 / 1.60934}
        if dist_match:
            zone['km'] = float(dist_match.group(1))
        label = line
        if dur_match:
            label = label.replace(dur_match.group(0), '')
        if dist_match:
            label = label.replace(dist_match.group(0), '')
        label = re.sub(r'^[\s:：\-—–,،]+|[\s:：\-—–,،]+$', '', label).strip()
        if label:
            zone['label'] = label
        zones.append(zone)
    if not zones:
        return default_zones
    return zones
