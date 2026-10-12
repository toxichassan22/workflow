STATIC_MAP_FRAME_VERSION = 2
FIXED_MAP_VIEWPORT_SIZE = (1280, 720)


def _map_viewport_size(value):
    if not isinstance(value, dict):
        return None
    try:
        width, height = int(value.get('width')), int(value.get('height'))
    except (TypeError, ValueError, OverflowError):
        return None
    return (width, height) if 64 <= width <= 2048 and 64 <= height <= 2048 else None


def _stored_map_viewport_size(metadata):
    return _map_viewport_size(metadata.get('viewport_size')) or (1280, 720)


def _map_size_metadata(size):
    return {'width': size[0], 'height': size[1]}


def _map_frame_center(lat, lng, size):
    return {'lat': lat, 'lng': lng, **_map_size_metadata(size)}


def _stored_map_frame_center(lat, lng, metadata):
    size = _map_viewport_size(metadata.get('viewport_size'))
    return _map_frame_center(lat, lng, size) if size else {'lat': lat, 'lng': lng}


def zoom_for_extent(lat, north_km, south_km, east_km, west_km, size=(1280, 720), scale=2, fill=0.8):
    """Pick the closest zoom keeping a directional extent (km from an anchor) inside the frame."""
    try:
        lat = float(lat)
        height_m = (float(north_km) + float(south_km)) * 1000.0
        width_m = (float(east_km) + float(west_km)) * 1000.0
    except (TypeError, ValueError):
        return None
    if height_m <= 0 or width_m <= 0:
        return None
    allowed_h = size[1] * scale * fill
    allowed_w = size[0] * scale * fill
    for zoom in range(20, 7, -1):
        metres_per_pixel = 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom) / scale
        if height_m / metres_per_pixel <= allowed_h and width_m / metres_per_pixel <= allowed_w:
            return zoom
    return 8


def catchment_frame_fit(lat, lng, ring_km, landmarks, size=(1280, 720)):
    """Frame the map on the directional spread of rings + landmarks.

    The old fit wrapped a site-centred circle around the farthest landmark, so a
    checked row 60 km north of the site also dragged 60 km of empty map into the
    south of the frame. Fitting each direction on its own keeps every selected
    row drawable while the frame hugs the real spread, recentring on the content
    instead of the site. Returns (zoom, center_lat, center_lng) or None when
    there is nothing to fit.

    The ring is a full circle around the site, so it seeds every direction —
    bands past the city radius are already dropped by ``catchment_rings`` and
    the shared fit here is reused for the landmarks map with ``ring_km=0``.
    """
    try:
        lat, lng = float(lat), float(lng)
        north = south = east = west = max(0.0, float(ring_km or 0))
    except (TypeError, ValueError):
        return None
    cos_lat = math.cos(math.radians(lat))
    had_landmark = False
    for item in landmarks or []:
        try:
            item_lat = float(item.get('lat'))
            item_lng = float(item.get('lng'))
        except (TypeError, ValueError, AttributeError):
            continue
        had_landmark = True
        dlat_km = (item_lat - lat) * 111.32 * 1.1
        dlng_km = (item_lng - lng) * 111.32 * max(0.01, cos_lat) * 1.1
        north = max(north, dlat_km)
        south = max(south, -dlat_km)
        east = max(east, dlng_km)
        west = max(west, -dlng_km)
    if not had_landmark and north + south <= 0:
        return None
    # A per-direction floor keeps the anchor inside the frame and mirrors the
    # old minimum-radius behaviour for rows that cluster around the site.
    floor_km = 0.6
    north, south = max(north, floor_km), max(south, floor_km)
    east, west = max(east, floor_km), max(west, floor_km)
    zoom = zoom_for_extent(lat, north, south, east, west, size=size)
    if zoom is None:
        return None
    zoom = min(17, zoom)
    center_lat = lat + ((north - south) / 2.0) / 111.32
    center_lng = lng + ((east - west) / 2.0) / (111.32 * max(0.01, cos_lat))
    return zoom, center_lat, center_lng


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
        if not math.isfinite(km) or km <= 0:
            continue
        minutes = zone.get('minutes') or zone.get('duration_minutes') or zone.get('duration_min')
        try:
            minutes = int(float(minutes))
        except (TypeError, ValueError, OverflowError):
            minutes = None
        candidates.append({
            'km': km,
            'minutes': minutes,
            'label': zone.get('label') or zone.get('name') or '',
        })
    if not candidates:
        return []
    candidates.sort(key=lambda item: item['km'])
    # The farthest row used to set the outer band, so one 30–65 km destination
    # zoomed the frame out to a region and the site turned into a dot. Bands
    # stay inside the city radius; farther rows remain in the zones table.
    # Do not reintroduce a far ring when every row sits past the cap.
    candidates = [item for item in candidates if item['km'] <= CATCHMENT_RING_MAX_KM]
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


def _resolved_map_landmarks(items, site_lat, site_lng, maximum_distance_m=None):
    resolved = []
    for item in items or []:
        if not isinstance(item, dict) or not str(item.get('name') or '').strip():
            continue
        try:
            lat, lng = float(item.get('lat')), float(item.get('lng'))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(lat) and math.isfinite(lng) and -85 <= lat <= 85 and -180 <= lng <= 180):
            continue
        if maximum_distance_m is not None and _distance_meters(site_lat, site_lng, lat, lng) > maximum_distance_m:
            continue
        resolved.append({**item, 'lat': lat, 'lng': lng})
    return resolved


def _recompose_landmark_items(project_data, field, metadata_field, rows, site_lat, site_lng, table_field):
    items = project_data.get(field) or []
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except (TypeError, ValueError):
            items = []
    if not isinstance(items, list):
        items = []
    table_value = project_data.get(table_field)
    explicitly_empty = table_field in project_data and table_value in ([], '[]')
    if not items and not explicitly_empty:
        for row in rows:
            try:
                metadata = json.loads(row.get('metadata_json') or '{}')
            except (TypeError, ValueError):
                continue
            if isinstance(metadata, dict) and isinstance(metadata.get(metadata_field), list) and metadata[metadata_field]:
                items = metadata[metadata_field]
                break
    return _resolved_map_landmarks(items, site_lat, site_lng)


def _prepare_static_map_image(path, provider_size, factor, size):
    try:
        with Image.open(path) as source:
            if source.size != (provider_size[0] * 2, provider_size[1] * 2):
                return False
            if factor == 1:
                return True
            image = source.resize((source.width * factor, source.height * factor), Image.Resampling.LANCZOS)
        width, height = size[0] * 2, size[1] * 2
        left, top = (image.width - width) // 2, (image.height - height) // 2
        image.crop((left, top, left + width, top + height)).save(path, 'PNG')
        return True
    except (OSError, ValueError):
        return False


def _static_map_image_matches(path, size):
    try:
        with Image.open(path) as image:
            return image.size == (size[0] * 2, size[1] * 2)
    except (OSError, ValueError):
        return False
