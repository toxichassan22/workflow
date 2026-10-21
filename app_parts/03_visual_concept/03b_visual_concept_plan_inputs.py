def _visual_concept_collect_generation_references(facts, slot_id, cover_image='', tenant_id=None):
    tenant_id = tenant_id or getattr(g, 'tenant_id', None)
    plan_map = facts.get('plan_image_map') if isinstance(facts.get('plan_image_map'), dict) else {}
    # The exterior render is grounded directly on the approved 3D massing diagram (Plan 3)
    # as the single 3D geometric base, or falls back to both the approved site plan (Plan 1)
    # and floor uses (Plan 2) when massing is not available.
    if plan_map.get('massing'):
        plan_urls = [plan_map['massing']]
    else:
        plan_urls = [url for url in (plan_map.get('site'), plan_map.get('uses')) if url]
    # Exterior slots render the approved plans: the plan diagram leads the
    # reference set, then the map and every named style ref — 4 urls + 5 files
    # must all fit so the enumerated order matches the attached order.
    external_cap = 4 + VISUAL_CONCEPT_MAX_REFERENCE_IMAGES
    if slot_id == 'cover':
        file_ids = list(facts.get('style_reference_file_ids') or [])
        map_urls = [facts['overview_map_url']] if (facts.get('overview_map_url') and not plan_urls) else []
        if plan_urls:
            return _visual_concept_reference_uris(
                urls=plan_urls, file_ids=file_ids,
                max_images=external_cap, urls_first=True, tenant_id=tenant_id)
        file_ids = file_ids[:VISUAL_CONCEPT_MAX_REFERENCE_IMAGES]
        if len(file_ids) >= VISUAL_CONCEPT_MAX_REFERENCE_IMAGES:
            map_urls = []
        # urls_first keeps the style refs trailing the map here too, matching
        # the plans path so "the last N attached images" names them in both.
        return _visual_concept_reference_uris(
            urls=map_urls, file_ids=file_ids, urls_first=True, tenant_id=tenant_id)
    urls = [cover_image] if cover_image else []
    if _visual_concept_is_internal_slot(slot_id):
        file_ids = list(facts.get('interior_reference_file_ids') or [])[:VISUAL_CONCEPT_MAX_REFERENCE_IMAGES]
        return _visual_concept_reference_uris(
            urls=urls,
            file_ids=file_ids,
            max_images=VISUAL_CONCEPT_MAX_REFERENCE_IMAGES + 1,
            urls_first=True,
            tenant_id=tenant_id,
        )
    if _visual_concept_is_plan_slot(slot_id):
        kind = _visual_concept_plan_kind(slot_id, facts.get('plan_kind'))
        boundary_url = facts.get('plan_boundary_reference_url')
        plan_map = plan_map or {}
        urls = [plan_map[dependency]
                for dependency in _VISUAL_PLAN_KIND_DEPENDENCIES.get(kind, ())
                if plan_map.get(dependency)]
        if kind in ('site', 'massing') and boundary_url:
            urls.append(boundary_url)
        if not urls and kind == 'site':
            map_url = facts.get('overview_map_url')
            urls = [map_url] if map_url else []
        return _visual_concept_reference_uris(urls=urls, tenant_id=tenant_id)
    # Angle slots re-render the approved hero image from another viewpoint —
    # the hero already carries the style, so style references would only fight it.
    return _visual_concept_reference_uris(
        urls=plan_urls + urls,
        max_images=external_cap, urls_first=True, tenant_id=tenant_id)


def _visual_concept_exterior_conformity_suffix(prompt, facts, slot_id):
    """State the rule the exterior render must hold whatever the prompt says.

    The stored slot prompt is client text, so the server states the rule that
    cannot be negotiated: the approved diagram fixes the footprints and positions,
    and nothing may be added, moved or resized.
    """
    if slot_id not in VISUAL_CONCEPT_EXTERNAL_SLOTS:
        return prompt
    plan_map = facts.get('plan_image_map') if isinstance(facts.get('plan_image_map'), dict) else {}
    if plan_map.get('massing'):
        return (
            f'{prompt} The first attached image is the approved massing diagram (Plan 3) of this project. '
            'Your task is direct image-to-image architectural rendering: render the finished architectural design directly ONTO this exact 3D diagram, converting it into a finished, photorealistic architectural photograph. '
            'MANDATORY GEOMETRIC INTEGRITY RULES: '
            '1. DO NOT CHANGE THE CAMERA ANGLE: Maintain the exact same camera angle, elevation, viewpoint, and perspective as Plan 3. Do not rotate, flip, tilt, or alter the camera position. '
            '2. BUILD STRICTLY ON THE PLOT: Build the architecture strictly within the surveyed plot boundary shown in the diagram; do not expand or improvise beyond it. '
            '3. DO NOT REDISTRIBUTE, RESTRUCTURE, OR RE-PARTITION: Do not rearrange, re-partition, split, merge, move, or resize any building mass or site feature, and do not change any count, number, dimension or area. Do not invent anything that is not in it. The exact positions, footprints, counts, and heights of the tower, villas, swimming pool, padel courts, and parking lots on the parcel are strictly fixed. '
            '4. DIRECT ARCHITECTURAL SKINNING: Dress the exact 3D masses on the parcel with photorealistic materials (glass curtain walls, limestone, warm wood accents, asphalt roads, lush landscaping, clear pool water). '
            '5. NO TEXT OR GRAPHICS: Do not render any text, signs, building names (e.g. "THE ICONIC"), street labels, titles, "CONCEPTUAL 3D MASSING", or diagram overlays anywhere in the image.'
        )
    if plan_map.get('site') and plan_map.get('uses'):
        return (
            f'{prompt} The attached reference images include the approved master site plan (Plan 1) '
            'and the approved vertical program distribution diagram (Plan 2): '
            'place the building masses, entries, and surface parking lots exactly within the footprints, '
            'frontages, and site arrangement shown in Plan 1. Extrude them into realistic 3D architectural '
            'volumes following the approved floor counts, heights, and vertical uses established in Plan 2. '
            'Do not alter building positions or parking locations shown in Plan 1. The other attached images '
            'are reference material only — the site map and client style references: they set the architectural '
            'facade design language and materials. '
            'CRITICAL ARCHITECTURAL RENDERING RULES: Render this as a breathtaking, photorealistic architectural '
            'perspective photograph. NEVER include any text, titles, labels, legends, or 2D diagram overlays.'
        )
    if plan_map.get('site'):
        return (
            f'{prompt} The first attached image is the approved master site plan (Plan 1) of this project: '
            'place the building masses exactly within the footprints, boundaries and site arrangement '
            'shown in this plan. Extrude them into realistic 3D architectural volumes following the approved '
            'floors and heights. The other attached images are reference material only — the site map and '
            'client style references: they set the architectural facade design language and materials. '
            'CRITICAL ARCHITECTURAL RENDERING RULES: Render this as a pure photorealistic architectural photograph without text or diagram boxes.'
        )
    return prompt


def _visual_concept_attach_style_reference_suffix(prompt, facts, slot_id):
    """The stored cover prompt may predate the client naming the style
    references — it is hidden, so nothing regenerates it. Re-state the ordered
    name map right before the image call so the current assignment always
    reaches the model; cover always attaches the style refs last."""
    if slot_id != 'cover':
        return prompt
    meta = list(facts.get('style_references') or [])
    if not any(item.get('name') or item.get('description') for item in meta):
        return prompt
    mapping = '; '.join(
        f"{index}) \"{item.get('name') or 'unnamed'}\""
        + (f" — {item['description']}" if item.get('description') else '')
        for index, item in enumerate(meta, 1))
    return (
        f"{prompt} The last {len(meta)} attached images are client style references, in order: {mapping}."
        " Apply each named reference's design language only to the project element its name describes."
    )


def _visual_concept_request_bundle(data, slot_id):
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    creative = data.get('creativeImages') if isinstance(data.get('creativeImages'), dict) else {}
    if creative:
        existing = project_data.get('tenantCreativeImages') if isinstance(project_data.get('tenantCreativeImages'), dict) else {}
        project_data = {
            **project_data,
            'tenantCreativeImages': {**existing, **creative},
            'map_placeholders': creative.get('map_placeholders') or project_data.get('map_placeholders'),
        }
    facts = _visual_concept_facts(project_data)
    facts['slot_label'] = _visual_concept_text(data.get('slotLabel') or data.get('slot_label'), 80)
    requested_component_id = _visual_concept_text(data.get('componentId') or data.get('component_id'), 80)
    if _visual_concept_is_internal_slot(slot_id):
        if not requested_component_id:
            requested_component_id = _visual_concept_interior_component_id(slot_id)
        selected = next((item for item in (facts.get('components') or []) if item.get('id') == requested_component_id), None)
        if not selected and requested_component_id:
            selected = next((item for item in (facts.get('components') or []) if item.get('name') == requested_component_id), None)
        if not selected and (facts.get('components') or []):
            selected = facts['components'][0]
        facts['selected_component'] = selected or {}
        facts['interior_reference_file_ids'] = _visual_concept_list(
            data.get('referenceFileIds') or data.get('interiorReferenceFileIds')
        )[:VISUAL_CONCEPT_MAX_REFERENCE_IMAGES]
    is_plan = _visual_concept_is_plan_slot(slot_id)
    if is_plan or slot_id in VISUAL_CONCEPT_EXTERNAL_SLOTS:
        workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
        boundary = workflow.get('boundary') if isinstance(workflow.get('boundary'), dict) else {}
        boundary_points = _visual_concept_plan_recorded_points(
            project_data, boundary.get('points') or data.get('planBoundaryPoints'))
        context = workflow.get('planContext') if isinstance(workflow.get('planContext'), dict) else None
        context = context or _visual_concept_plan_context(project_data, boundary_points, workflow.get('verification'))
        context['boundary_points'] = boundary_points or context.get('boundary_points') or []
        _financial_parking_refresh_context(context, project_data)
        _visual_concept_plan_context_ensure_idea(context, project_data)
        if is_plan:
            context['client_notes'] = _visual_plan_notes(data)
            facts['plan_scene'] = workflow.get('scene') if isinstance(workflow.get('scene'), dict) else None
            facts['plan_description'] = _visual_concept_text(
                data.get('planDescription') or data.get('plan_description'), 2000)
            facts['plan_kind'] = _visual_concept_plan_kind(slot_id, data.get('planKind'))
            facts['approved_plan_context'] = _visual_concept_plan_context_text(context)
            stored_prompts = workflow.get('prompts') if isinstance(workflow.get('prompts'), dict) else {}
            stored_draft = _visual_concept_text(stored_prompts.get(facts['plan_kind']), 64000)
            if stored_draft:
                facts['plan_prompt_draft'] = stored_draft
            else:
                distribution = (workflow.get('distribution')
                                if isinstance(workflow.get('distribution'), dict) else {})
                model = _visual_concept_plan_model_from_distribution(
                    distribution, context, context.get('regulations') or {})
                facts['plan_prompt_draft'] = (
                    _visual_concept_plan_drawing_prompt(facts['plan_kind'], context, model=model)
                    if facts['plan_kind'] else '')
            facts['plan_boundary_reference_url'] = _visual_concept_text(
                boundary.get('referenceUrl') or data.get('planBoundaryReferenceUrl'), 500)
        elif _visual_concept_plan_context_has_measurements(context):
            # Exterior renders ground on the same deterministic measurements the
            # plan diagrams draw from — the spec text only, never the diagram's
            # color legend or labelling rules.
            facts['approved_plan_context'] = _visual_concept_plan_context_text(context, diagram_rules=False)
    if slot_id in VISUAL_CONCEPT_EXTERNAL_SLOTS:
        facts['plan_image_urls'] = _visual_concept_plan_image_urls(data)
        # The exterior render is grounded on the massing diagram alone, so the
        # per-kind map is what the reference set and the prompt read.
        facts['plan_image_map'] = _visual_concept_plan_image_map(data)
    elif is_plan:
        facts['plan_image_map'] = _visual_concept_plan_image_map(data)
    missing = _visual_concept_missing_fields(facts, slot_id)
    if _visual_concept_is_internal_slot(slot_id) and not (facts.get('selected_component') or {}).get('name'):
        missing.append({'key': 'project_components_data', 'label': 'اختر مكونًا فعليًا من الدراسة المالية'})
    return project_data, facts, missing
