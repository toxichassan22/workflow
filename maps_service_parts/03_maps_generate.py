

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
        next_metadata = {**metadata, 'lat': lat, 'lng': lng, 'highlight_site': bool(highlight_site),
                         'map_label_version': MAP_LABEL_RENDER_VERSION,
                         'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION}
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
            'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION,
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
    landmarks = _recompose_landmark_items(
        project_data, 'catchment_map_landmarks', 'catchment_landmarks', by_type.values(),
        lat, lng, 'city_landmarks_data')
    draw_compass = True
    draw_inset = True
    zones = _parse_catchment_zones(project_data.get('catchment_areas', ''))
    rings = catchment_rings(zones)
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
        frame_fit = catchment_frame_fit(lat, lng, ring_km, landmarks)
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
            # exactly the stale-extent case this refit exists to repair. The
            # sidecar must also still be the canonical fixed size: a legacy
            # phone-viewport raster gets rebuilt instead of stretched.
            if (existing_zoom is not None and existing_zoom == frame_zoom
                    and existing_center is not None
                    and existing_meta.get('catchment_rings') == rings
                    and _distance_meters(existing_center[0], existing_center[1],
                                         frame_center_lat, frame_center_lng) < 25
                    and _static_map_image_matches(existing['file_path'], FIXED_MAP_VIEWPORT_SIZE)):
                continue
        active_maptype = 'roadmap' if final_type.endswith('_roadmap') else 'satellite'
        styles = SATELLITE_WIDE_STYLES if active_maptype == 'satellite' else SATELLITE_WITH_LABELS_STYLES
        cached_base = _map_cache_path(frame_center_lat, frame_center_lng, active_maptype, frame_zoom, None, None, FIXED_MAP_VIEWPORT_SIZE, styles, language=map_lang)
        if not os.path.isfile(cached_base):
            cached_base = _fetch_map_base(frame_center_lat, frame_center_lng, active_maptype, frame_zoom, styles, tenant_id, language=map_lang, size=FIXED_MAP_VIEWPORT_SIZE)
            if not cached_base:
                # The rebuild was required — composing over the stale frame
                # would certify the wrong extent, so the recompose fails.
                return {'error': 'تعذر جلب صورة الخريطة الأساسية'}
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
        if draw_inset:
            _draw_inset_map(editable_path, lat, lng, inset_size=180, language=map_lang)
        editable_placeholder = (
            str(final.get('placeholder') or '')[:-2] + '_EDITABLE##'
            if final else str(existing.get('placeholder') or '')
        )
        metadata = {**metadata, 'zoom': frame_zoom, 'center_lat': frame_center_lat,
                    'center_lng': frame_center_lng, 'manual_viewport': False,
                    'viewport_size': _map_size_metadata(FIXED_MAP_VIEWPORT_SIZE)}
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
        draw_landmarks = landmarks
        label_positions = project_data.get('catchment_label_positions')
        if not label_positions:
            label_positions = {item['name']: item['label_point'] for item in draw_landmarks
                               if isinstance(item, dict) and item.get('name') and item.get('label_point')}
        current_landmarks = _draw_catchment_markers(
            final_path, center_lat, center_lng, zoom, draw_landmarks,
            label_positions, scale=2, site_lat=lat, site_lng=lng
        )
        if current_landmarks is None:
            return {'error': 'تعذر رسم معالم خريطة المنطقة'}
        next_metadata = {**metadata, 'lat': lat, 'lng': lng, 'catchment_landmarks': current_landmarks,
                         'zones': zones, 'catchment_rings': rings,
                         'viewport_size': _map_size_metadata(FIXED_MAP_VIEWPORT_SIZE),
                         'map_label_version': MAP_LABEL_RENDER_VERSION,
                         'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION}
        final = by_type.get(final_type)
        if final:
            update_map_image(final['id'], tenant_id, final_path, final_placeholder, next_metadata)
        else:
            add_map_image(tenant_id, final_type, final_path, final_placeholder, effective_id, next_metadata)
        update_map_image(editable['id'], tenant_id, editable['file_path'], editable['placeholder'], next_metadata)
        placeholders[final_placeholder] = final_path
        placeholders[editable['placeholder']] = editable['file_path']
        centers['catchment'] = _stored_map_frame_center(center_lat, center_lng, next_metadata)
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
    landmarks = _recompose_landmark_items(
        project_data, 'landmark_map_items', 'landmark_map_items', by_type.values(),
        site_lat, site_lng, 'nearby_landmarks_data')
    draw_compass = True
    draw_inset = True
    map_lang = map_language(project_data)
    # Road-named rows keep their drawn-road anchor near the site — a geocoded
    # endpoint kilometres out would otherwise pin the marker off-frame.
    _snap_road_landmarks(landmarks, project_data, site_lat, site_lng,
                         language=map_lang, search_radius_m=20000)
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
        # The landmarks frame mirrors generation: the same directional content
        # fit — a site-centred radius around the farthest row mirrored empty
        # space into the opposite half of the frame.
        frame_fit = catchment_frame_fit(site_lat, site_lng, 0, landmarks)
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
            # Identical frame → keep the editable; a wider one is the stale
            # extent this refit repairs. A legacy-sized raster also rebuilds —
            # fixed maps always compose at the canonical viewport.
            if (existing_zoom is not None and existing_zoom == frame_zoom
                    and existing_center is not None
                    and _distance_meters(existing_center[0], existing_center[1],
                                         frame_center_lat, frame_center_lng) < 25
                    and _static_map_image_matches(existing['file_path'], FIXED_MAP_VIEWPORT_SIZE)):
                continue
        active_maptype = 'roadmap' if final_type.endswith('_roadmap') else 'satellite'
        styles = SATELLITE_WIDE_STYLES if active_maptype == 'satellite' else SATELLITE_WITH_LABELS_STYLES
        cached_base = _map_cache_path(frame_center_lat, frame_center_lng, active_maptype, frame_zoom, None, None, FIXED_MAP_VIEWPORT_SIZE, styles, language=map_lang)
        if not os.path.isfile(cached_base):
            cached_base = _fetch_map_base(frame_center_lat, frame_center_lng, active_maptype, frame_zoom, styles, tenant_id, language=map_lang, size=FIXED_MAP_VIEWPORT_SIZE)
            if not cached_base:
                # Same stale-frame guard as the catchment recompose: no clean
                # base at the fitted frame means no certified render.
                return {'error': 'تعذر جلب صورة الخريطة الأساسية'}
        editable_path = _unique_map_path(tenant_id, effective_id, editable_type)
        shutil.copyfile(cached_base, editable_path)
        if active_maptype == 'satellite':
            _apply_sepia_tone(editable_path, intensity=0.35)
            _apply_map_overlay(editable_path, dark_factor=0.20)
        if draw_compass:
            _draw_compass(editable_path, position='top-right', language=map_lang)
        if draw_inset:
            _draw_inset_map(editable_path, site_lat, site_lng, inset_size=180, language=map_lang)
        editable_placeholder = (
            str(final.get('placeholder') or '')[:-2] + '_EDITABLE##'
            if final else str(existing.get('placeholder') or '')
        )
        metadata = {**metadata, 'zoom': frame_zoom, 'center_lat': frame_center_lat,
                    'center_lng': frame_center_lng, 'manual_viewport': False,
                    'viewport_size': _map_size_metadata(FIXED_MAP_VIEWPORT_SIZE)}
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
        draw_landmarks = landmarks
        label_positions = project_data.get('landmark_label_positions')
        if not label_positions:
            label_positions = {item['name']: item['label_point'] for item in draw_landmarks
                               if isinstance(item, dict) and item.get('name') and item.get('label_point')}
        current_landmarks = _draw_catchment_markers(
            final_path, center_lat, center_lng, zoom, draw_landmarks,
            label_positions, scale=2, site_lat=site_lat, site_lng=site_lng
        )
        if current_landmarks is None:
            return {'error': 'تعذر رسم معالم الخريطة'}
        next_metadata = {**metadata, 'lat': site_lat, 'lng': site_lng, 'landmark_map_items': current_landmarks,
                         'viewport_size': _map_size_metadata(FIXED_MAP_VIEWPORT_SIZE),
                         'map_label_version': MAP_LABEL_RENDER_VERSION,
                         'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION}
        final = by_type.get(final_type)
        if final:
            update_map_image(final['id'], tenant_id, final_path, final_placeholder, next_metadata)
        else:
            add_map_image(tenant_id, final_type, final_path, final_placeholder, effective_id, next_metadata)
        update_map_image(editable['id'], tenant_id, editable['file_path'], editable['placeholder'], next_metadata)
        placeholders[final_placeholder] = final_path
        placeholders[editable['placeholder']] = editable['file_path']
        centers['landmarks'] = _stored_map_frame_center(center_lat, center_lng, next_metadata)
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

