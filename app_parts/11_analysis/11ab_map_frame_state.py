def _merge_persisted_map_assets(project_data, tenant_id, presentation_id=None, draft_id=None):
    if not isinstance(project_data, dict):
        return project_data or {}
    records = db.get_map_images(tenant_id, presentation_id=presentation_id, draft_id=draft_id)
    if not records:
        return project_data
    creative = project_data.get('tenantCreativeImages')
    if not isinstance(creative, dict):
        creative = {}
    placeholders = {}
    map_zooms = {}
    map_centers = {}
    map_render_versions = {}
    map_highlight_site = None
    seen_types = set()
    seen_placeholders = set()
    for record in records:
        path = record.get('file_path')
        placeholder = record.get('placeholder')
        image_type = record.get('image_type') or ''
        if not path or not placeholder or not os.path.exists(path):
            continue
        try:
            metadata = json.loads(record.get('metadata_json') or '{}')
        except (TypeError, ValueError):
            metadata = {}
        if image_type in seen_types or placeholder in seen_placeholders:
            continue
        seen_types.add(image_type)
        seen_placeholders.add(placeholder)
        try:
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
        except ValueError:
            rel_path = 'uploads/maps/' + os.path.basename(path)
        placeholders[placeholder] = '/' + rel_path
        base_type = image_type.split('_', 1)[0]
        if base_type in {'overview', 'access', 'catchment', 'landmarks'}:
            map_render_versions.setdefault(base_type, metadata.get('map_label_version'))

        # Frame geometry (site pin, zoom, center) is a fact about the persisted file
        # itself, so it stays trustworthy even when a later renderer version changed
        # the overlay drawing.  Restoring it unconditionally keeps reopened
        # presentations from falling back to a wildly wrong default zoom.
        if metadata.get('lat') is not None:
            creative['map_lat'] = metadata['lat']
        if metadata.get('lng') is not None:
            creative['map_lng'] = metadata['lng']
        if metadata.get('zoom') is not None:
            base_type = image_type
            for suffix in ('_editable', '_satellite', '_roadmap'):
                if base_type.endswith(suffix):
                    base_type = base_type[:-len(suffix)]
            map_zooms.setdefault(base_type, metadata['zoom'])
        if metadata.get('center_lat') is not None and metadata.get('center_lng') is not None:
            base_type = image_type
            for suffix in ('_editable', '_satellite', '_roadmap'):
                if base_type.endswith(suffix):
                    base_type = base_type[:-len(suffix)]
            if base_type in {'overview', 'access', 'catchment', 'landmarks'}:
                map_centers.setdefault(base_type, maps_service._stored_map_frame_center(
                    metadata['center_lat'], metadata['center_lng'], metadata))
        if metadata.get('highlight_site') is not None:
            map_highlight_site = bool(metadata.get('highlight_site'))
        # The file itself remains a valid persisted map even when a later
        # renderer version changed its overlays or labels.  Keep importing that
        # image so slide generation never produces an empty map frame.  Only
        # trust the attached metadata for marker-aware layout when both versions
        # match the renderer that produced the current map implementation.
        current_map_metadata = (
            metadata.get('map_highlight_version') == maps_service.MAP_HIGHLIGHT_RENDER_VERSION
            and metadata.get('map_label_version') == maps_service.MAP_LABEL_RENDER_VERSION
        )
        if not current_map_metadata:
            continue
        # The map row is the source of truth for the image that was actually
        # approved.  Project JSON can lag behind it when a user edits a map and
        # immediately starts presentation generation, so do not let stale JSON
        # metadata survive a hydration pass.
        if 'landmarks_matrix' in metadata:
            creative['map_landmarks'] = metadata['landmarks_matrix']
        if 'access_roads' in metadata:
            project_data['access_roads_data'] = metadata['access_roads']
            creative['map_access_roads'] = metadata['access_roads']
        if 'catchment_landmarks' in metadata:
            project_data['catchment_map_landmarks'] = metadata['catchment_landmarks']
            creative['map_catchment_landmarks'] = metadata['catchment_landmarks']
        if 'landmark_map_items' in metadata:
            project_data['landmark_map_items'] = metadata['landmark_map_items']
            creative['map_landmark_items'] = metadata['landmark_map_items']
    existing_placeholders = creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {}
    merged_placeholders = {key: value for key, value in existing_placeholders.items() if key and value}
    merged_placeholders.update(placeholders)
    creative['map_placeholders'] = merged_placeholders
    creative['maps_persisted'] = bool(merged_placeholders)
    creative['map_renderer_version'] = maps_service.MAP_LABEL_RENDER_VERSION
    creative['map_render_versions'] = {
        **(creative.get('map_render_versions') if isinstance(creative.get('map_render_versions'), dict) else {}),
        **map_render_versions,
    }
    if map_highlight_site is not None:
        creative['map_highlight_site'] = map_highlight_site
    if map_zooms:
        creative['map_zooms'] = map_zooms
    if map_centers:
        creative['map_centers'] = map_centers
        creative['map_baked_frames'] = {
            **(creative.get('map_baked_frames') if isinstance(creative.get('map_baked_frames'), dict) else {}),
            **{map_type: {**center, 'zoom': map_zooms[map_type]}
               for map_type, center in map_centers.items() if map_type in map_zooms},
        }
    project_data['tenantCreativeImages'] = creative
    return project_data


def _frame_matches_baked(creative, map_type):
    """True when a stored viewport override still describes the baked raster.

    A map approval certifies the rendered frame — a live-camera override that
    diverges from ``map_baked_frames`` means the flag covers a view nobody
    baked, so the claim is refused."""
    overrides = creative.get('map_viewport_overrides')
    if not isinstance(overrides, dict) or not overrides.get(map_type):
        return True
    baked = (creative.get('map_baked_frames') or {}).get(map_type) or {}
    zooms = creative.get('map_zooms') or {}
    centers = creative.get('map_centers') or {}
    zoom = zooms.get(map_type)
    center = centers.get(map_type) or {}
    if any(axis in center for axis in ('width', 'height')):
        size = maps_service._map_viewport_size(center)
        if size is None or size != maps_service._map_viewport_size(baked):
            return False
    try:
        if zoom is not None and baked.get('zoom') is not None \
                and int(round(float(zoom))) != int(round(float(baked['zoom']))):
            return False
        for axis in ('lat', 'lng'):
            live_val, baked_val = center.get(axis), baked.get(axis)
            if live_val is not None and baked_val is not None \
                    and not abs(float(live_val) - float(baked_val)) <= 1e-6:
                return False
    except (TypeError, ValueError, OverflowError):
        return False
    return True
