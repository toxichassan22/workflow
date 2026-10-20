
# ── Visual concept image edit ────────────────────────────────────────────────
# The client "send edit" box used to rewrite the hidden generation prompt, so
# the next generate rebuilt the image from scratch and dropped the approved
# composition. Edits now go straight to the image model as a surgical edit of
# the slot's own current image: a fixed hidden wrapper forbids hallucination
# and any unrequested change, and the client's raw text is embedded inside it.
# A cheap text-model gate reads the request against the actual image first —
# when it is vague or misleading it returns a clarifying question instead of
# editing.


def _visual_concept_edit_base_image(data, tenant_id=None):
    """The slot's current image as a model-readable data URI.

    The client posts the card's own image url; ``blob:`` handles are dead
    outside their tab and remote urls are refused by the reference validator,
    so only durable tenant-owned uploads or inline data URIs get through.
    """
    raw = str(data.get('image') or data.get('imageUrl') or data.get('currentImage') or '').strip()
    if not raw or raw.lower().startswith('blob:'):
        return ''
    prepared = _prepare_image_reference_for_model(raw, tenant_id)
    return prepared or ''


def _visual_concept_edit_reference_uris(data, limit=5):
    """Client images pinned to this edit message — the request and its style
    references arrive together, so "use this on that element" binds to actual
    pixels instead of a name somewhere in the prompt."""
    tenant_id = getattr(g, 'tenant_id', None)
    uris = []
    for file_id in (data.get('editReferenceFileIds') or [])[:limit]:
        uri = _visual_concept_project_file_data_uri(file_id, tenant_id)
        if uri:
            uris.append(uri)
    return uris


def _visual_concept_edit_prompt(instruction, slot_id, facts, ref_count=0):
    """Hidden mandatory wrapper: the client's text slots into a fixed contract
    that forbids the model from touching anything unrequested — even when the
    client never says «don't change anything else»."""
    slot_label = _visual_concept_slot_label(slot_id, facts)
    return (
        'Edit the attached image titled "' + str(slot_label) + '". '
        'This is a surgical edit of the supplied image, not a regeneration: the attached '
        'image is the source of truth and the output must remain the same image with only '
        'the requested change applied. '
        'Do not hallucinate, invent, or add any element, object, or detail on your own. '
        'Do not delete, restyle, move, or alter anything that is not part of the request. '
        'Keep the camera angle, framing, composition, architecture, materials, colors, '
        'lighting, and every other detail of the input image identical. '
        'Any aspect of the image the request does not mention stays untouched. '
        + (f'The last {ref_count} attached images are client-supplied style references for '
           'this edit — apply their design language only to the element the request names. '
           if ref_count else '')
        + 'Requested change: ' + instruction
    )


def _visual_concept_edit_chat_tail(data, slot_id, limit=4):
    """The last few chat lines posted with the request — the clarity gate sees
    them so an element identified one message ago does not get asked again."""
    state = _visual_concept_posted_state(data)
    slot_state = (state.get('slots') or {}).get(slot_id) or {}
    chat = slot_state.get('chat')
    lines = []
    for entry in (chat if isinstance(chat, list) else [])[-limit:]:
        if not isinstance(entry, dict) or not str(entry.get('text') or '').strip():
            continue
        speaker = 'النظام' if entry.get('role') == 'assistant' else 'العميل'
        line = f'{speaker}: {str(entry["text"]).strip()[:300]}'
        attached = entry.get('attachments')
        if isinstance(attached, list) and attached:
            line += ' (مرفق: ' + '، '.join(str(name) for name in attached[:3]) + ')'
        lines.append(line)
    return lines


def _visual_concept_edit_clarity(slot_id, facts, instruction, base_image, usage_ctx=None,
                                 extra_images=None, chat_tail=None):
    """Gate the edit before it costs an image call: the text model sees the
    actual image plus the request and decides whether the request is a clear,
    directly executable visual edit. Returns a dict {clear, question} or None
    when the check itself failed — the edit then proceeds anyway because the
    hidden wrapper already constrains the outcome."""
    slot_label = _visual_concept_slot_label(slot_id, facts)
    system_prompt = (
        'أنت حارس جودة لطلبات تعديل صورة معمارية واحدة قبل إرسالها إلى محرر الصور. '
        'محرر الصور ينفذ طلب العميل حرفيًا على الصورة المرفقة ولا يغيّر شيئًا آخر. '
        'مهمتك فقط الحكم على وضوح الطلب: هل هو تعديل بصري محدد قابل للتنفيذ مباشرة على هذه الصورة؟ '
        'اعتبر الطلب غير واضح إذا كان فضفاضًا لا يحدد ما الذي يتغير، أو مضللًا يشير إلى عنصر '
        'غير موجود في الصورة أو موجود بتكرار دون تحديد المقصود، أو ليس تعديلًا على الصورة أصلًا '
        'كأن يكون سؤالًا أو طلب معلومات أو رأيًا. '
        'قد يصل العميل صورًا مرجعية إضافية بعد الصورة الأساسية — عبارات مثل «الصورة المرفوعة» '
        'أو «الصورة المرجعية» تعنيها، ووجود مرجع مرفق مع عنصر محدد يجعل الطلب واضحًا تمامًا؛ '
        'لا تسأل عن عناصر النقل من المرجع ولا عن الصورة نفسها. '
        'وإذا كان العميل قد حدّد العنصر في رسالة سابقة من المحادثة فلا تسأل عنه مجددًا. '
        'عند عدم الوضوح اكتب سؤالًا عربيًا واحدًا قصيرًا يطلب بالضبط ما تحتاجه لتنفيذ التعديل، '
        'ولا تسأل عمّا هو واضح أصلًا. أعد JSON فقط: {"clear":true|false,"question":""}.'
    )
    context = ''
    if chat_tail:
        context = 'آخر رسائل المحادثة بين العميل والنظام:\n' + '\n'.join(chat_tail) + '\n'
    ref_count = len(extra_images or [])
    user_prompt = (
        'الصورة الأولى المرفقة هي «' + str(slot_label) + '» للمشروع.\n'
        + context
        + (f'العميل أرفق {ref_count} صورة مرجعية مع طلبه (الصور بعد الأساسية).\n' if ref_count else '')
        + 'طلب التعديل من العميل:\n' + instruction
    )
    try:
        response = call_openrouter_chat(
            system_prompt, user_prompt, temperature=None, max_tokens=1200,
            model=GEMINI_TEXT_MODEL, reasoning_effort='low',
            response_format={'type': 'json_object'},
            image_references=([base_image] + list(extra_images or [])) if base_image else None,
            usage_ctx=usage_ctx or _usage_ctx('image'))
        parsed = parse_json_object(_get_chat_response_text(response))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


@app.route('/api/visual-concept/edit', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_edit():
    data = request.get_json(silent=True) or {}
    _billing_guard = _require_billing_balance('image_generation')
    if _billing_guard is not None:
        return _billing_guard
    slot_id = _visual_concept_normalize_slot(data.get('slotId') or 'cover')
    if not slot_id:
        return jsonify({'success': False, 'error': 'نوع الصورة غير معروف', 'error_code': 'SLOT_INVALID'}), 400
    workflow_error = _visual_concept_plan_workflow_error(
        data, slot_id, require_distribution=True)
    if workflow_error:
        return jsonify(workflow_error), 400
    if _visual_concept_plan_kind(slot_id):
        if slot_id == 'plan_site':
            return _visual_plan_dispatch('site_edit', data, slot_id)
        return _visual_plan_dispatch('edit', data, slot_id)
    instruction = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if not instruction:
        return jsonify({'success': False, 'error': 'اكتب طلب التعديل أولاً', 'error_code': 'MESSAGE_REQUIRED'}), 400
    _project_data, facts, missing = _visual_concept_request_bundle(data, slot_id)
    if missing:
        return jsonify({
            'success': False,
            'error': 'أكمل الحقول الناقصة قبل تعديل التصور البصري',
            'error_code': 'VISUAL_CONCEPT_DATA_INCOMPLETE',
            'missingFields': missing,
        }), 400
    external_gate = _visual_concept_external_gate(data, slot_id)
    if external_gate:
        return jsonify(external_gate), 400
    cover_image = _visual_concept_cover_image(data)
    if slot_id != 'cover' and not _visual_concept_is_plan_slot(slot_id) and not cover_image:
        return jsonify({
            'success': False,
            'error': 'اعتمد الصورة الرئيسية قبل تعديل التصور البصري',
            'error_code': 'COVER_REQUIRED',
        }), 400
    section_gate = _visual_concept_section_gate(data, _visual_concept_section_requirement(slot_id))
    if section_gate:
        return jsonify(section_gate), 400
    base_image = _visual_concept_edit_base_image(data, tenant_id=getattr(g, 'tenant_id', None))
    if not base_image:
        return jsonify({
            'success': False,
            'error': 'لا توجد صورة حالية قابلة للتعديل في هذا الحقل',
            'error_code': 'IMAGE_REQUIRED',
        }), 400
    # The paid half runs in a job: the stop button has to reach it.
    return _visual_plan_dispatch('edit_image', data, slot_id)


def _visual_concept_edit_result(data, slot_id):
    """The paid half of a visual-concept edit: the check and the new image.

    It runs inside a job so the stop button reaches it, and the inputs are
    re-checked because the job may start after the request was answered.
    """
    instruction = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if not instruction:
        return {'success': False, 'error': 'اكتب طلب التعديل أولاً',
                'error_code': 'MESSAGE_REQUIRED'}, 400
    _project_data, facts, missing = _visual_concept_request_bundle(data, slot_id)
    if missing:
        return {'success': False,
                'error': 'أكمل الحقول الناقصة قبل تعديل التصور البصري',
                'error_code': 'VISUAL_CONCEPT_DATA_INCOMPLETE',
                'missingFields': missing}, 400
    base_image = _visual_concept_edit_base_image(data, tenant_id=getattr(g, 'tenant_id', None))
    if not base_image:
        return {'success': False,
                'error': 'لا توجد صورة حالية قابلة للتعديل في هذا الحقل',
                'error_code': 'IMAGE_REQUIRED'}, 400
    ref_uris = _visual_concept_edit_reference_uris(data)
    usage_ctx = _usage_ctx('image', data)
    clarity = _visual_concept_edit_clarity(
        slot_id, facts, instruction, base_image, usage_ctx, ref_uris,
        _visual_concept_edit_chat_tail(data, slot_id))
    if isinstance(clarity, dict) and clarity.get('clear') is False:
        question = _visual_concept_text(clarity.get('question'), 600) or 'حدد ما الذي تريد تغييره في الصورة بالضبط.'
        return {
            'success': True,
            'slotId': slot_id,
            'needsClarification': True,
            'question': question,
        }, 200
    edit_prompt = _visual_concept_edit_prompt(instruction, slot_id, facts, len(ref_uris))
    image = call_images_api(edit_prompt, [base_image] + ref_uris, model=VISUAL_CONCEPT_IMAGE_MODEL,
                            usage_ctx=usage_ctx)
    if not image:
        error = last_images_api_error() or {}
        if error.get('cancelled') or error.get('fatal') or error.get('error_code') in _FATAL_AI_ERROR_CODES:
            status = error.get('http_status') if isinstance(error.get('http_status'), int) else 503
            return {'success': False, 'error': _client_safe_llm_error(error.get('message') or ''),
                    'error_code': error.get('error_code') or 'IMAGE_FAILED'}, status
        if not _has_any_openrouter_key(tenant_id=getattr(g, 'tenant_id', None)):
            return {'success': False,
                    'error': 'خدمة الذكاء الاصطناعي غير متاحة حاليًا — تواصل مع الدعم الفني.',
                    'error_code': 'NO_API_KEY'}, 400
        return {'success': False, 'error': 'تعذر تعديل الصورة',
                'error_code': 'IMAGE_FAILED'}, 503
    return {
        'success': True,
        'slotId': slot_id,
        'image': persist_generated_image(image, g.tenant_id),
        'reply': 'تم تعديل الصورة حسب طلبك.',
        'model': VISUAL_CONCEPT_IMAGE_MODEL,
    }, 200
