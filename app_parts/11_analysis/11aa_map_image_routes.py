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
    # Maps are Google-rendered data, not AI content: no approval gates here.
    # Scope checks stay — the caller must still own the presentation/draft.
    presentation = None
    if presentation_id:
        presentation = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
        if not presentation or not _presentation_in_scope(presentation):
            return jsonify({'error': 'Presentation not found'}), 404
    elif draft_id:
        stored_draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
        if stored_draft and not db.user_may_access_draft(g.user_id, stored_draft):
            return jsonify({'success': False, 'error': 'المشروع غير موجود'}), 404
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
        # Slides live in slides_data — the embedded copy is storage waste.
        updated_project.pop('tenantSlidesData', None)
        updated_project['map_placeholders'] = {**old_placeholders, **placeholders}
        # Persist the generated map's own frame and resolved items with it —
        # the follow-up client save used to be the only writer, so a reload
        # before it landed reopened the previous frame.
        creative = dict(old_creative) if isinstance(old_creative, dict) else {}
        creative['map_placeholders'] = updated_project['map_placeholders']
        if (result.get('zooms') or {}).get(map_type) is not None:
            creative['map_zooms'] = {
                **(creative.get('map_zooms') if isinstance(creative.get('map_zooms'), dict) else {}),
                map_type: result['zooms'][map_type],
            }
        if isinstance((result.get('centers') or {}).get(map_type), dict):
            creative['map_centers'] = {
                **(creative.get('map_centers') if isinstance(creative.get('map_centers'), dict) else {}),
                map_type: result['centers'][map_type],
            }
        # The rendered frame is the truth the interactive preview's dirty flag
        # compares against — a stored-but-unbaked viewport override must stay
        # distinguishable after a reload, and map_zooms/map_centers can no
        # longer tell them apart once the live map writes into them.
        if (result.get('zooms') or {}).get(map_type) is not None \
                or isinstance((result.get('centers') or {}).get(map_type), dict):
            _baked_zoom = (result.get('zooms') or {}).get(map_type)
            _baked_center = (result.get('centers') or {}).get(map_type) or {}
            _prev_baked = (creative.get('map_baked_frames') or {}).get(map_type) or {}
            creative['map_baked_frames'] = {
                **(creative.get('map_baked_frames') if isinstance(creative.get('map_baked_frames'), dict) else {}),
                map_type: {
                    'zoom': _baked_zoom if _baked_zoom is not None else _prev_baked.get('zoom'),
                    'lat': _baked_center.get('lat', _prev_baked.get('lat')),
                    'lng': _baked_center.get('lng', _prev_baked.get('lng')),
                    **{axis: _baked_center[axis] for axis in ('width', 'height') if axis in _baked_center},
                },
            }
            # A fresh raster voids the map's stored approval — the flag must
            # be re-earned against the new image, not carried onto it.
            creative['map_approvals'] = {
                **(creative.get('map_approvals') if isinstance(creative.get('map_approvals'), dict) else {}),
                map_type: False,
            }
        if 'highlightSite' in data:
            creative['map_highlight_site'] = bool(highlight_site)
        creative['maps_persisted'] = True
        creative['map_renderer_version'] = maps_service.MAP_LABEL_RENDER_VERSION
        creative['map_render_versions'] = {
            **(creative.get('map_render_versions') if isinstance(creative.get('map_render_versions'), dict) else {}),
            map_type: maps_service.MAP_LABEL_RENDER_VERSION,
        }
        # Recompose responses carry only their map's resolved key, so a missing
        # key means "not redrawn" — never store the empty fallback over it.
        if map_type == 'landmarks':
            if 'landmark_map_items' in result or 'landmarks' in result:
                landmark_items = result.get('landmark_map_items') or result.get('landmarks') or []
                creative['map_landmark_items'] = landmark_items
                updated_project['landmark_map_items'] = landmark_items
            if 'landmarks_matrix' in result:
                landmarks_matrix = result.get('landmarks_matrix') or []
                creative['map_landmarks'] = landmarks_matrix
                updated_project['landmarks_matrix'] = landmarks_matrix
        elif map_type == 'access' and 'access_roads' in result:
            access_roads = result.get('access_roads') or []
            creative['map_access_roads'] = access_roads
            updated_project['access_roads_data'] = access_roads
        elif map_type == 'catchment' and 'catchment_landmarks' in result:
            catchment_landmarks = result.get('catchment_landmarks') or []
            creative['map_catchment_landmarks'] = catchment_landmarks
            updated_project['catchment_map_landmarks'] = catchment_landmarks
        elif map_type == 'overview' and result.get('site_polygon') \
                and project_data.get('location_polygon_source') not in ('manual', 'cleared'):
            # The regenerated boundary feeds the client's polygon too; a drawn
            # or cleared boundary keeps the version the client sent.
            polygon_text = ';'.join(
                f"{point[0]},{point[1]}" for point in result['site_polygon']
                if isinstance(point, (list, tuple)) and len(point) >= 2
            )
            if polygon_text:
                updated_project['location_polygon'] = polygon_text
                updated_project['location_polygon_source'] = 'auto'
        updated_project['tenantCreativeImages'] = creative
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
        'mapRenderVersion': maps_service.MAP_LABEL_RENDER_VERSION,
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


@app.route('/api/maps/interactive-config', methods=['GET'])
@require_auth
def api_maps_interactive_config():
    """Browser-side Maps JS bootstrap for the live preview map.

    The browser key is public in the page by design — it must be the dedicated
    GOOGLE_MAPS_BROWSER_API_KEY, HTTP-referrer restricted in Cloud Console. The
    server-side GOOGLE_MAPS_API_KEY is never served here: a missing browser key
    just keeps the client on the generated static image.
    """
    key = GOOGLE_MAPS_BROWSER_API_KEY or ''
    if not key:
        return jsonify({'success': False, 'error_code': 'INTERACTIVE_MAPS_KEY_MISSING'}), 404
    return jsonify({'success': True, 'key': key})


@app.route('/api/maps/interactive-load', methods=['POST'])
@require_auth
def api_maps_interactive_load():
    """Meter one Dynamic Maps load (~$7/1000). Pans/zooms inside the mounted
    map are free, so the client posts once per map instance — the count is a
    client-reported estimate bounded by the tenant rate limit, matching the
    estimate-based metering the rest of the Maps spend tracking uses.
    """
    data = request.json or {}
    map_type = str(data.get('mapType') or '').strip().lower()
    flow = map_type if map_type in maps_service.MAPS_USAGE_FLOWS else 'maps'
    rate_error = maps_service._check_maps_rate_limit(g.tenant_id)
    if rate_error:
        return jsonify({'success': False, **rate_error}), 429
    maps_service._record_maps_call(g.tenant_id)
    maps_service._record_maps_usage(
        maps_service.maps_usage_ctx(
            flow, tenant_id=g.tenant_id,
            draft_id=data.get('draftId') or data.get('draft_id') or None,
            presentation_id=data.get('presentationId') or data.get('presentation_id') or None,
        ),
        'dynamic_map',
    )
    return jsonify({'success': True})


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
