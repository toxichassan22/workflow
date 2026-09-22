

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
        image_type: {'lat': item['center_lat'], 'lng': item['center_lng']}
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


def _recompose_overview_map(project_data, tenant_id, effective_id, highlight_site):
    from db import add_map_image, get_map_images, update_map_image
    rows = get_map_images(tenant_id, presentation_id=effective_id)
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
        if polygon and not _draw_site_highlight(final_path, center_lat, center_lng, zoom, size=(1280, 720), polygon_coords=polygon, auto_detect_polygon=False, auto_detected=False):
            continue
        if not _overlay_markers(final_path, center_lat, center_lng, zoom, _build_markers(lat, lng), size=(1280, 720)):
            continue
        next_metadata = {**metadata, 'lat': lat, 'lng': lng, 'highlight_site': bool(highlight_site)}
        final = by_type.get(final_type)
        if final:
            update_map_image(final['id'], tenant_id, final_path, final_placeholder, next_metadata)
        else:
            add_map_image(tenant_id, final_type, final_path, final_placeholder, effective_id, next_metadata)
        update_map_image(editable['id'], tenant_id, editable['file_path'], editable['placeholder'], next_metadata)
        placeholders[final_placeholder] = final_path
        centers['overview'] = {'lat': center_lat, 'lng': center_lng}
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
        return _recompose_overview_map(project_data, tenant_id, effective_id, highlight_site)


def _recompose_access_map(project_data, tenant_id, effective_id):
    from db import add_map_image, get_map_images, update_map_image
    rows = get_map_images(tenant_id, presentation_id=effective_id)
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
    map_styles = project_data.get('map_styles') or {}
    if isinstance(map_styles, str):
        try:
            map_styles = json.loads(map_styles)
        except (TypeError, ValueError):
            map_styles = {}
    draw_compass = project_data.get('draw_compass', True)
    if isinstance(draw_compass, str):
        draw_compass = draw_compass.lower() in {'true', '1', 'yes'}
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
        active_maptype = 'satellite' if final_type.endswith('_satellite') else 'roadmap' if final_type.endswith('_roadmap') else str(map_styles.get('access') or project_data.get('map_type') or 'satellite')
        if active_maptype in {'auto', 'both'}:
            active_maptype = 'roadmap' if active_maptype == 'auto' else 'satellite'
        styles = SATELLITE_CLEAN_STYLES if active_maptype == 'satellite' else ACCESS_ROADMAP_STYLES
        cached_base = _map_cache_path(center_lat, center_lng, active_maptype, zoom, None, None, (1280, 720), styles)
        if not os.path.isfile(cached_base):
            continue
        editable_path = _unique_map_path(tenant_id, effective_id, editable_type)
        shutil.copyfile(cached_base, editable_path)
        if active_maptype == 'satellite':
            _apply_sepia_tone(editable_path, intensity=0.35)
            _apply_map_overlay(editable_path, dark_factor=0.10)
        if draw_compass:
            _draw_compass(editable_path, position='top-right')
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
            size=(1280, 720)
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
        centers['access'] = {'lat': center_lat, 'lng': center_lng}
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
        return _recompose_access_map(project_data, tenant_id, effective_id)


def _recompose_catchment_map(project_data, tenant_id, effective_id):
    from db import add_map_image, get_map_images, update_map_image
    rows = get_map_images(tenant_id, presentation_id=effective_id)
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
    map_styles = project_data.get('map_styles') or {}
    if isinstance(map_styles, str):
        try:
            map_styles = json.loads(map_styles)
        except (TypeError, ValueError):
            map_styles = {}
    draw_compass = project_data.get('draw_compass', True)
    if isinstance(draw_compass, str):
        draw_compass = draw_compass.lower() in {'true', '1', 'yes'}
    rings = catchment_rings(_parse_catchment_zones(project_data.get('catchment_areas', '')))
    for final_type, editable_type in (
        ('catchment', 'catchment_editable'),
        ('catchment_satellite', 'catchment_satellite_editable'),
        ('catchment_roadmap', 'catchment_roadmap_editable'),
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
        active_maptype = 'satellite' if final_type.endswith('_satellite') else 'roadmap' if final_type.endswith('_roadmap') else str(map_styles.get('catchment') or project_data.get('map_type') or 'satellite')
        if active_maptype in {'auto', 'both'}:
            active_maptype = 'satellite'
        styles = SATELLITE_WIDE_STYLES if active_maptype == 'satellite' else SATELLITE_WITH_LABELS_STYLES
        cached_base = _map_cache_path(center_lat, center_lng, active_maptype, zoom, None, None, (1280, 720), styles)
        if not os.path.isfile(cached_base):
            continue
        editable_path = _unique_map_path(tenant_id, effective_id, editable_type)
        shutil.copyfile(cached_base, editable_path)
        if active_maptype == 'satellite':
            _apply_sepia_tone(editable_path, intensity=0.35)
            _apply_map_overlay(editable_path, dark_factor=0.15)
        if rings:
            _draw_catchment_zones(editable_path, center_lat, center_lng, zoom, rings, scale=2)
        if draw_compass:
            _draw_compass(editable_path, position='top-right')
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
        current_landmarks = _draw_catchment_markers(
            final_path, center_lat, center_lng, zoom, landmarks,
            project_data.get('catchment_label_positions'), scale=2
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
        centers['catchment'] = {'lat': center_lat, 'lng': center_lng}
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
        return _recompose_catchment_map(project_data, tenant_id, effective_id)


def _recompose_landmarks_map(project_data, tenant_id, effective_id):
    from db import add_map_image, get_map_images, update_map_image
    rows = get_map_images(tenant_id, presentation_id=effective_id)
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
    map_styles = project_data.get('map_styles') or {}
    if isinstance(map_styles, str):
        try:
            map_styles = json.loads(map_styles)
        except (TypeError, ValueError):
            map_styles = {}
    draw_compass = project_data.get('draw_compass', True)
    if isinstance(draw_compass, str):
        draw_compass = draw_compass.lower() in {'true', '1', 'yes'}
    for final_type, editable_type in (
        ('landmarks', 'landmarks_editable'),
        ('landmarks_satellite', 'landmarks_satellite_editable'),
        ('landmarks_roadmap', 'landmarks_roadmap_editable'),
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
        active_maptype = 'satellite' if final_type.endswith('_satellite') else 'roadmap' if final_type.endswith('_roadmap') else str(map_styles.get('landmarks') or project_data.get('map_type') or 'satellite')
        if active_maptype in {'auto', 'both'}:
            active_maptype = 'satellite'
        styles = SATELLITE_WIDE_STYLES if active_maptype == 'satellite' else SATELLITE_WITH_LABELS_STYLES
        cached_base = _map_cache_path(center_lat, center_lng, active_maptype, zoom, None, None, (1280, 720), styles)
        if not os.path.isfile(cached_base):
            continue
        editable_path = _unique_map_path(tenant_id, effective_id, editable_type)
        shutil.copyfile(cached_base, editable_path)
        if active_maptype == 'satellite':
            _apply_sepia_tone(editable_path, intensity=0.35)
            _apply_map_overlay(editable_path, dark_factor=0.20)
        if draw_compass:
            _draw_compass(editable_path, position='top-right')
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
        current_landmarks = _draw_catchment_markers(
            final_path, center_lat, center_lng, zoom, landmarks,
            project_data.get('landmark_label_positions'), scale=2, site_lat=site_lat, site_lng=site_lng
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
        centers['landmarks'] = {'lat': center_lat, 'lng': center_lng}
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
        return _recompose_landmarks_map(project_data, tenant_id, effective_id)


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
        nearby_rows = _parse_landmarks_text(nearby_text)[:7] if isinstance(nearby_text, str) else []
    if city_structured is None:
        city_text = project_data.get('city_landmarks', '')
        city_rows = _parse_landmarks_text(city_text)[:7] if isinstance(city_text, str) else []
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
    # A regenerate must not re-frame a map whose extent is derived from a real boundary:
    # shifting the zoom by two levels shrank the plot back to a dot.
    if project_data.get('refresh_maps') and regen_seed and not (polygon_coords and len(polygon_coords) >= 3):
        zoom_shift = MAP_REGEN_ZOOM_OFFSETS[regen_seed % len(MAP_REGEN_ZOOM_OFFSETS)]
        for map_key in enabled_maps:
            if map_key in zooms:
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

    # The approved latitude/longitude is the user-controlled pin for every map. The boundary may
    # center the viewport, but it must never move that saved pin implicitly.
    marker_lat, marker_lng = lat, lng

    # Parse UI element flags (compass, inset map)
    draw_compass = project_data.get('draw_compass', True)
    if isinstance(draw_compass, str):
        draw_compass = draw_compass.lower() in ('true', '1', 'yes')
    elif not isinstance(draw_compass, bool):
        if branding and 'draw_compass' in branding:
            draw_compass = bool(branding['draw_compass'])
        else:
            draw_compass = True

    draw_inset = project_data.get('draw_inset', True)
    if isinstance(draw_inset, str):
        draw_inset = draw_inset.lower() in ('true', '1', 'yes')
    elif not isinstance(draw_inset, bool):
        if branding and 'draw_inset' in branding:
            draw_inset = bool(branding['draw_inset'])
        else:
            draw_inset = True

    # Parse per-map style preferences (satellite/roadmap/terrain/hybrid/both)
    # Default: all satellite. Employee can override per-map via map_styles dict.
    # Fallback to tenant branding defaults if not in project_data
    map_styles_raw = project_data.get('map_styles', {})
    if isinstance(map_styles_raw, str):
        try:
            map_styles_raw = json.loads(map_styles_raw)
        except Exception:
            map_styles_raw = {}
    if not isinstance(map_styles_raw, dict):
        map_styles_raw = {}
    else:
        map_styles_raw = dict(map_styles_raw)
    # default_map_type is only a fallback; explicit per-map tenant settings win.
    default_map_type = (
        project_data.get('map_type')
        or (branding.get('default_map_type') if branding else None)
        or 'satellite'
    )
    if branding:
        for key in ('overview', 'landmarks', 'access', 'catchment'):
            if not map_styles_raw.get(key):
                map_styles_raw[key] = branding.get(f'map_style_{key}') or default_map_type
    VALID_MAPTYPES = {'auto', 'satellite', 'roadmap', 'terrain', 'hybrid', 'both'}
    map_styles = {}
    for key in ('overview', 'landmarks', 'access', 'catchment'):
        val = map_styles_raw.get(key) or default_map_type
        if val not in VALID_MAPTYPES:
            val = 'auto'
        map_styles[key] = 'roadmap' if val == 'auto' and key == 'access' else 'satellite' if val == 'auto' else val

    landmark_radius_m = 20000
    city_context = project_data.get('city') or project_data.get('location', '')

    # Preserve the selected table order through geocoding and filtering so marker
    # numbering stays aligned with the approved rows.
    def _resolve_map_landmarks(rows, search_radius_m, maximum_distance_m=None):
        resolved = []
        for landmark in rows:
            if landmark.get('lat') is None or landmark.get('lng') is None:
                place = find_place_near(landmark.get('name'), lat, lng, radius_m=search_radius_m)
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
                continue
            distance_meters = _distance_meters(lat, lng, landmark['lat'], landmark['lng'])
            if distance_meters < 50:
                continue
            if maximum_distance_m is not None and distance_meters > maximum_distance_m:
                continue
            landmark['distance_meters'] = round(distance_meters)
            resolved.append(landmark)
        return resolved

    # Retain automatic discovery only for old projects that have no structured
    # nearby-landmark table. An explicit table, including an empty one, is authoritative.
    if 'landmarks' in enabled_maps and nearby_structured is None and not landmarks:
        places = get_nearby_landmarks(
            lat, lng, radius=landmark_radius_m, max_results=7, include_all=True
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
        matrix = get_drive_matrix((lat, lng), landmarks)
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
                landmark['distance_text'] = entry.get('distance_text') or f"{entry['distance_km']} كم"
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
            overview_res = get_static_map(map_center_lat, map_center_lng, zoom=overview_zoom, size=(1280, 720), output_path=overview_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_WITH_LABELS_STYLES), bypass_cache=refresh_maps)
            if overview_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(overview_path, intensity=0.35)
                    _apply_map_overlay(overview_path, dark_factor=0.12)
                if draw_compass:
                    _draw_compass(overview_path, position='top-right')
                if draw_inset:
                    _draw_inset_map(overview_path, lat, lng, inset_size=180)
                editable_placeholder = editable_placeholders[placeholder]
                editable_suffix = img_suffix + '_editable'
                editable_path = _unique_map_path(tenant_id, effective_pres_id, editable_suffix)
                shutil.copyfile(overview_path, editable_path)
                metadata = {'lat': lat, 'lng': lng, 'zoom': overview_zoom, 'center_lat': map_center_lat, 'center_lng': map_center_lng, 'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION, 'map_label_version': MAP_LABEL_RENDER_VERSION, 'highlight_site': bool(highlight_site), 'landmarks_matrix': result.get('landmarks_matrix') or []}
                if highlight_site:
                    _draw_site_highlight(overview_path, map_center_lat, map_center_lng, overview_zoom, size=(1280, 720), polygon_coords=polygon_coords, auto_detect_polygon=False, auto_detected=auto_detected)
                _overlay_markers(overview_path, map_center_lat, map_center_lng, overview_zoom, overview_markers, size=(1280, 720))
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
            radius_km = max(0.6, min(LANDMARKS_MAX_RADIUS_KM, radius_km * 1.1))
            fitted_zoom = zoom_for_radius_km(lat, radius_km)
            if fitted_zoom:
                landmarks_zoom = fitted_zoom
                result['zooms']['landmarks'] = landmarks_zoom
                print(f'[LANDMARKS] {len(shown_landmarks)} landmarks within {radius_km:.1f} km, zoom {landmarks_zoom}')
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
            lm_res = get_static_map(map_center_lat, map_center_lng, zoom=landmarks_zoom, size=(1280, 720), output_path=landmarks_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_WIDE_STYLES), bypass_cache=refresh_maps)
            if lm_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(landmarks_path, intensity=0.35)
                    _apply_map_overlay(landmarks_path, dark_factor=0.20)
                if draw_compass:
                    _draw_compass(landmarks_path, position='top-right')
                if draw_inset:
                    _draw_inset_map(landmarks_path, lat, lng, inset_size=180)
                editable_placeholder = editable_placeholders[placeholder]
                editable_suffix = img_suffix + '_editable'
                editable_path = _unique_map_path(tenant_id, effective_pres_id, editable_suffix)
                shutil.copyfile(landmarks_path, editable_path)
                rendered_landmarks = _draw_catchment_markers(
                    landmarks_path, map_center_lat, map_center_lng, landmarks_zoom, shown_landmarks or landmarks,
                    project_data.get('landmark_label_positions'), scale=2, site_lat=marker_lat, site_lng=marker_lng
                )
                if not result['landmark_map_items']:
                    result['landmark_map_items'] = rendered_landmarks
                metadata = {
                    'lat': lat,
                    'lng': lng,
                    'zoom': landmarks_zoom,
                    'center_lat': map_center_lat,
                    'center_lng': map_center_lng,
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
            access_res = get_static_map(map_center_lat, map_center_lng, zoom=access_zoom, size=(1280, 720), output_path=access_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_CLEAN_STYLES, 'access'), bypass_cache=refresh_maps)
            if access_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(access_path, intensity=0.35)
                    _apply_map_overlay(access_path, dark_factor=0.10)
                if draw_compass:
                    _draw_compass(access_path, position='top-right')
                editable_placeholder = editable_placeholders[placeholder]
                editable_suffix = img_suffix + '_editable'
                editable_path = _unique_map_path(tenant_id, effective_pres_id, editable_suffix)
                shutil.copyfile(access_path, editable_path)
                rendered_roads = _draw_access_roads(
                    access_path,
                    map_center_lat,
                    map_center_lng,
                    access_zoom,
                    scale=2,
                    project_data=project_data,
                    tenant_id=tenant_id,
                    origin_lat=marker_lat,
                    origin_lng=marker_lng,
                ) or []
                if not result['access_roads']:
                    result['access_roads'] = rendered_roads
                _overlay_markers(access_path, map_center_lat, map_center_lng, access_zoom, access_markers, size=(1280, 720))
                metadata = {
                    'lat': lat,
                    'lng': lng,
                    'zoom': access_zoom,
                    'center_lat': map_center_lat,
                    'center_lng': map_center_lng,
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
        if rings:
            fitted_zoom = zoom_for_radius_km(lat, max(ring['km'] for ring in rings))
            if fitted_zoom:
                catchment_zoom = fitted_zoom
                result['zooms']['catchment'] = catchment_zoom
                print(f"[CATCHMENT] {len(rings)} rings, outer {max(ring['km'] for ring in rings):.1f} km, zoom {catchment_zoom}")
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
            catchment_res = get_static_map(lat, lng, zoom=catchment_zoom, paths=None, size=(1280, 720), output_path=catchment_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_WIDE_STYLES), bypass_cache=refresh_maps)
            if catchment_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(catchment_path, intensity=0.35)
                    _apply_map_overlay(catchment_path, dark_factor=0.15)
                # Draw the anti-aliased concentric rings with time label pills
                if rings:
                    _draw_catchment_zones(catchment_path, lat, lng, catchment_zoom, rings, scale=2)
                if draw_compass:
                    _draw_compass(catchment_path, position='top-right')
                if draw_inset:
                    _draw_inset_map(catchment_path, lat, lng, inset_size=180)
                editable_placeholder = editable_placeholders[placeholder]
                editable_suffix = img_suffix + '_editable'
                editable_path = _unique_map_path(tenant_id, effective_pres_id, editable_suffix)
                shutil.copyfile(catchment_path, editable_path)
                rendered_landmarks = _draw_catchment_markers(
                    catchment_path, lat, lng, catchment_zoom, city_landmarks,
                    project_data.get('catchment_label_positions'), scale=2
                )
                if not result['catchment_landmarks']:
                    result['catchment_landmarks'] = rendered_landmarks
                metadata = {
                    'lat': lat,
                    'lng': lng,
                    'zoom': catchment_zoom,
                    'center_lat': lat,
                    'center_lng': lng,
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


def _parse_landmarks_text(text):
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
        category_match = re.search(r'(?:^|\s)[—\-]\s*(ترفيهي|تعليمي|صحي|تجاري|ديني(?: ومركزي)?|ثقافي/سياحي|حكومي/خدمي|اجتماعي/خدمي)\s*(?:[—\-]|$)', clean_name)
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
            'distance_text': f"{distance} كم" if distance is not None else None,
            'lat': None,
            'lng': None,
        })
    return landmarks


def select_map_landmark_rows(structured, limit=7):
    """Return the approved landmark rows for a map without changing their input order."""
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except (TypeError, ValueError):
            return []
    if not isinstance(structured, list):
        return []

    rows = [dict(item) for item in structured if isinstance(item, dict)]
    selected = [
        item for item in rows
        if item.get('show_on_map') is True or item.get('selected') is True
    ]
    try:
        row_limit = max(0, min(7, int(limit)))
    except (TypeError, ValueError):
        row_limit = 7
    return (selected or rows)[:row_limit]


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
    return landmarks


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
