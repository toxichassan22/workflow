# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VISUAL CONCEPT SKETCH MIRROR
#
# One derived artifact per source image: the slot already carries its generated
# or uploaded picture, so this endpoint only re-draws it as a pen-and-ink
# architectural sketch. No plan-workflow gate applies — the source image cleared
# its own gates when it was produced. Plan diagrams are excluded by product
# decision (they are already schematic drawings).
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@app.route('/api/visual-concept/sketch', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_sketch():
    data = request.get_json(silent=True) or {}
    _billing_guard = _require_billing_balance('image_generation')
    if _billing_guard is not None:
        return _billing_guard
    slot_id = _visual_concept_normalize_slot(data.get('slotId') or 'cover')
    if not slot_id or _visual_concept_is_plan_slot(slot_id):
        return jsonify({'success': False, 'error': 'نوع الصورة غير معروف',
                        'error_code': 'SLOT_INVALID'}), 400
    tenant_id = getattr(g, 'tenant_id', None)
    # The source arrives as its stored /uploads/ url (generated) or as the
    # project-file id (upload mode); both resolve to a tenant-owned data URI.
    source_url = str(data.get('sourceImage') or data.get('source_image') or '').strip()
    source_ref = ''
    if source_url and not source_url.lower().startswith('blob:'):
        source_ref = _prepare_image_reference_for_model(source_url, tenant_id)
    if not source_ref:
        file_id = _visual_concept_text(data.get('sourceFileId') or data.get('source_file_id'), 80)
        if file_id:
            source_ref = _visual_concept_project_file_data_uri(file_id, tenant_id)
    if not source_ref:
        return jsonify({'success': False,
                        'error': 'لا توجد صورة أصلية صالحة لتوليد السكتش',
                        'error_code': 'SOURCE_REQUIRED'}), 400
    instruction = _visual_concept_text(data.get('instruction'), 2000)
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    project_name = _visual_concept_text(
        _visual_concept_read(project_data, 'project_name', 'projectName'), 200) or 'the project'
    prompt = (
        f'Re-draw the attached image of {project_name} as a hand-drawn architectural '
        'design-studio sketch: loose confident pen-and-pencil line work on warm '
        'cream-toned paper, visible freehand strokes, quick cross-hatching for shadows '
        'and materials, landscape and entourage in expressive sketch strokes. Preserve '
        'the exact composition, viewpoint, proportions and geometry of the source image '
        '— the same camera angle and framing with every visible architectural element. '
        'Monochrome sketch on toned paper; no photorealistic rendering, no color washes, '
        'no text, no logos, no watermarks, no people.'
        + (f' Client note to apply: {instruction}' if instruction else '')
    )
    image = call_images_api(prompt, [source_ref], model=VISUAL_CONCEPT_IMAGE_MODEL,
                            usage_ctx=_usage_ctx('image', data))
    if not image:
        fatal = _ai_fatal_http_response(last_images_api_error())
        if fatal is not None:
            return fatal
        if not _has_any_openrouter_key(tenant_id=tenant_id):
            return jsonify({'success': False,
                            'error': 'خدمة الذكاء الاصطناعي غير متاحة حاليًا — تواصل مع الدعم الفني.',
                            'error_code': 'NO_API_KEY'}), 400
        return jsonify({'success': False, 'error': 'تعذر توليد السكتش',
                        'error_code': 'IMAGE_FAILED'}), 503
    return jsonify({'success': True, 'slotId': slot_id,
                    'sketch': persist_generated_image(image, g.tenant_id)})
