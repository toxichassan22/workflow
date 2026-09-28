

@app.route('/api/designer-chat', methods=['POST'])
@require_permission('create_presentation')
def api_designer_chat():
    """Agentic designer chat operating on one slide or the complete presentation."""
    data = request.json or {}
    job_id = request.headers.get('X-Designer-Job-Id') or data.get('_job_id')
    tenant_id = g.tenant_id

    def report_designer_progress(progress_val, message_text, extra_data=None):
        _report_designer_job_progress(job_id, tenant_id, progress_val, message_text, extra_data)

    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'الطلب فارغ'}), 400
    # Free-reply preflight, without history: a turn the canned replies can
    # answer skips the wallet guard, so a zero-balance tenant can still ask
    # «كام رصيدي». Every other turn keeps ISS-037 — the guard fires before the
    # payload is probed further.
    _free_probe_uris = _normalize_designer_attached_images(data)
    _available_sar = _designer_available_sar(tenant_id)
    _free_preflight = _designer_chat_free_reply(
        message, has_attachment=bool(_free_probe_uris),
        available_sar=_available_sar)
    if _free_preflight is None:
        _billing_guard = _require_billing_balance('designer_chat')
        if _billing_guard is not None:
            return _billing_guard
    report_designer_progress(10, 'جاري تحليل الطلب وتحديد نطاق التعديل...')
    request_project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    request_creative_images = copy.deepcopy(data.get('creativeImages')) if isinstance(data.get('creativeImages'), dict) else {}
    presentation_id = data.get('presentationId')
    presentation = None
    slides = data.get('slidesData') if isinstance(data.get('slidesData'), list) else []
    current_index = data.get('slideIndex', 0)
    if isinstance(current_index, bool) or not re.fullmatch(r'\d+', str(current_index)):
        return jsonify({'success': False, 'error': 'رقم الشريحة الحالية غير صالح', 'error_code': 'DESIGNER_INVALID_TARGET'}), 422
    current_index = int(current_index)

    if presentation_id:
        presentation = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
        if not presentation:
            return jsonify({'success': False, 'error': 'العرض غير موجود أو لا يتبع هذه الشركة'}), 404
        if not slides and presentation.get('slides_data'):
            try:
                slides = json.loads(presentation['slides_data'])
            except Exception:
                slides = []

    superseded_values = []
    project_data = _designer_project_data_for_request(
        request_project_data, presentation, tenant_id,
        superseded_out=superseded_values)
    # Numbers the live draft retired since the deck snapshot: an edit that swaps
    # them for current values must not trip the missing-numbers guard.
    superseded_numbers = _superseded_number_tokens(superseded_values)
    tci = project_data.get('tenantCreativeImages')
    if isinstance(tci, str):
        try:
            tci = json.loads(tci)
        except Exception:
            tci = {}
    project_creative_images = copy.deepcopy(tci) if isinstance(tci, dict) else {}
    authoritative_project_data = copy.deepcopy(project_data)
    project_data, creative_images = _hydrate_map_assets_for_request(
        project_data, data.get('creativeImages', {}), g.tenant_id,
        presentation_id=presentation_id,
    )
    # Designer-chat requests must have the same selected team-logo manifest as full
    # presentation generation. Without this merge, the model can see a team name but
    # has no real image behind ##TEAM_LOGO_N## and falls back to the company logo.
    creative_images = _augment_generation_images(creative_images, project_data, g.tenant_id)
    project_data.update(authoritative_project_data)

    # Every designer turn is project spend: resolve the draft once so no model
    # call in this flow can land outside the project total. The client often
    # sends no draftId here, so the linked presentation is the fallback source.
    designer_draft_id = (
        data.get('draftId') or data.get('draft_id')
        or (request_project_data.get('draftId') or request_project_data.get('draft_id')
            if isinstance(request_project_data, dict) else None)
        or (project_data.get('draftId') or project_data.get('draft_id')
            if isinstance(project_data, dict) else None)
        or (presentation.get('draft_id') if isinstance(presentation, dict) else None)
    )
    if designer_draft_id:
        data.setdefault('draftId', str(designer_draft_id))
        if isinstance(project_data, dict):
            project_data.setdefault('draftId', str(designer_draft_id))

    # Backward-compatible one-slide clients still work.
    if not slides and data.get('slideHtml'):
        slides = [{'html': data.get('slideHtml'), 'title': data.get('slideTitle', ''), 'type': 'content', 'designStyle': 'cards'}]
        current_index = 0
    if not slides:
        return jsonify({'success': False, 'error': 'لا توجد شرائح مفتوحة لتنفيذ الطلب'}), 400
    if current_index >= len(slides) or any(not isinstance(s, dict) for s in slides):
        return jsonify({'success': False, 'error': 'العرض أو رقم الشريحة الحالية غير صالح', 'error_code': 'DESIGNER_INVALID_TARGET'}), 422
    # Every slide gets a stable id before the planner/runner sees the deck:
    # positions shuffle on structural edits, ids do not.
    designer_agent_ids.ensure_slide_ids(slides)

    # Kept so the history can state what the AI actually changed. An AI edit used to leave no trace
    # at all: no log entry, no version, and no record of the instruction behind it.
    slides_before = copy.deepcopy(slides)
    project_data['_designer_deck_context'] = designer_chat_context.build_deck_context(slides)

    # Only a scope explicitly selected in the UI is a constraint. The model
    # interprets natural language, including negation, corrections and numbers.
    is_all_slides_request = data.get('target') == 'all' or data.get('scope') == 'all'

    # The conversation so far. Merge the browser snapshot with the presentation copy so a stale
    # client cannot replace a complete saved conversation with only its last visible messages.
    stored_chat = project_data.get('designerChat') if isinstance(project_data.get('designerChat'), dict) else {}
    incoming_history = data.get('history') if isinstance(data.get('history'), list) else []
    history_for_turn = _merge_designer_chat_messages(stored_chat.get('messages'), incoming_history)
    memory_seed = data.get('memory') if isinstance(data.get('memory'), str) and data.get('memory') else stored_chat.get('memory')
    chat_memory, recent_history = _designer_chat_memory(
        history_for_turn, memory_seed,
        usage_ctx=_usage_ctx('designer_chat', data, presentation_id=presentation_id))
    history_lines = _designer_chat_history_lines(recent_history)
    focus_indexes = []
    for value in (data.get('focusIndexes') if isinstance(data.get('focusIndexes'), list) else []):
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= len(slides) and number not in focus_indexes:
            focus_indexes.append(number)

    # Focus is conversational context, not an instruction inferred from this turn.
    # In particular, a number may answer a value question rather than name a slide.
    preferred_indexes = list(focus_indexes)

    # Billing transparency: greetings and capability questions never reach the model.
    # The planner prompt carries the whole draft, so even «سلام» used to move the
    # provider balance. Answer those turns locally with zero tokens spent. This
    # history-aware pass can veto the preflight probe (a pending assistant
    # question turns a short reply into an instruction), so the deferred wallet
    # guard below still wraps the paid path for those turns.
    _free_text = _designer_chat_free_reply(
        message, has_attachment=bool(_free_probe_uris), history=history_for_turn,
        available_sar=_available_sar)
    if _free_text is not None:
        return _designer_chat_canned_json(
            message, _free_text, history_for_turn, chat_memory,
            focus_indexes, preferred_indexes)

    # Span router (respan/span-01-lite via the Decisions API, $0 per call): the
    # deterministic replies only cover canned phrasing, so any other turn is
    # scored design-vs-chat. Chat gets a local answer; a failure or an edit
    # signal falls through to the paid planner. Plan continuations
    # (confirm/retry/cancel) and attachments are design work by definition.
    _route = 'design'
    if not (data.get('retryTasks') or data.get('confirmPlan')
            or data.get('cancelPlan') or _free_probe_uris):
        _route = _designer_span_route(
            message, history_for_turn,
            usage_ctx=_usage_ctx('designer_chat', data, presentation_id=presentation_id))
    if _route != 'design':
        _routed_text = (_designer_balance_reply_text(_available_sar)
                        if _route == 'balance' else None) or _DESIGNER_CAPABILITY_TEXT
        return _designer_chat_canned_json(
            message, _routed_text, history_for_turn, chat_memory,
            focus_indexes, preferred_indexes)

    # A preflight-free turn that history vetoed (or that the router called
    # design work) skipped the wallet guard above — the paid path needs it here.
    if _free_preflight is not None:
        _billing_guard = _require_billing_balance('designer_chat')
        if _billing_guard is not None:
            return _billing_guard

    branding = db.get_branding(g.tenant_id) or {}
    _prepare_generation_logo_context(project_data, branding, g.tenant_id)
    training_context = db.get_training_context(g.tenant_id) or ''

    # DESIGNER_AGENT=1: per-task planner/runner path (chatplan). The legacy
    # all-at-once planner below stays untouched for DESIGNER_AGENT=0.
    if DESIGNER_AGENT:
        return _designer_agent_turn({
            'data': data, 'message': message, 'slides': slides,
            'current_index': current_index, 'project_data': project_data,
            'creative_images': creative_images,
            'request_creative_images': request_creative_images,
            'project_creative_images': project_creative_images,
            'presentation_id': presentation_id, 'presentation': presentation,
            'request_project_data': request_project_data,
            'superseded_numbers': superseded_numbers,
            'tenant_id': tenant_id, 'branding': branding,
            'training_context': training_context,
            'history_for_turn': history_for_turn, 'chat_memory': chat_memory,
            'history_lines': history_lines, 'focus_indexes': focus_indexes,
            'preferred_indexes': preferred_indexes,
            'is_all_slides_request': is_all_slides_request,
            'slides_before': slides_before, 'job_id': job_id,
            'report_progress': report_designer_progress,
        })

    summary = [{
        'index': i + 1,
        'title': s.get('title', '') if isinstance(s, dict) else '',
        'section': s.get('section_key') or s.get('sectionKey') or '',
        'type': s.get('type', 'content') if isinstance(s, dict) else 'content'
    } for i, s in enumerate(slides)]
    all_note = "\n تنبيه هام جداً: المستخدم طلب صراحة تعديل جميع الشرائح دون استثناء! يجب أن تعيد target='all' في الأداة edit_slides." if is_all_slides_request else ""
    memory_note = f"\n\n## ذاكرة المحادثة (ملخص ما سبق)\n{chat_memory}" if chat_memory else ""
    history_note = ("\n\n## آخر رسائل المحادثة بالترتيب\n" + '\n'.join(history_lines)) if history_lines else ""
    focus_note = (
        f"\n\n## نطاق الحديث السابق: {'، '.join(str(n) for n in focus_indexes)}\n"
        "هذا سياق سابق وليس أمراً جديداً. اربط الإشارات والردود القصيرة بالسؤال السابق وبالطلب "
        "غير المنفذ، واسمح للرسالة الحالية بتغيير الموضوع أو تصحيح الطلب أو إلغائه."
    ) if focus_indexes else ""
    explicit_scope_note = (
        f"\n\n## الشريحة الظاهرة في المعاينة: {current_index + 1}\n"
        "موضع المعاينة سياق فقط، وليس دليلاً أن المستخدم طلب تعديل هذه الشريحة. "
        "حدّد النية والنطاق من المحادثة والرسالة الحالية معاً."
    )
    training_note = f"\n\n## قواعد الشركة الملزمة (من التدريب — التزم بها في أي تصميم)\n{training_context}" if training_context else ""
    # Deterministic table row/column deletes never need the planner LLM. The full planner
    # prompt carries the unabridged project snapshot plus every slide HTML verbatim, which
    # exceeds the model token cap on real decks (measured 427k > 307k) and turns a local
    # surgical edit into a 402. Pre-check here: when every targeted slide deterministically
    # applies, synthesize the edit_slides plan and skip the planner call entirely. When the
    # request names a table edit but the local check cannot apply it (unknown column name,
    # ambiguous table, merged cells, ...), skip the doomed full prompt as well and route
    # straight to the slim planner retry — the failure note below tells the model exactly
    # what is missing so it can ask precisely instead of erroring with a raw 402.
    deterministic_plan = None
    slim_planner_only = False
    slim_table_indexes = None
    table_failure_note = ''
    table_probe = designer_chat_reliability.detect_table_edit_request(message)
    if table_probe.get('handled'):
        try:
            deterministic_indexes = _resolve_deterministic_table_targets(
                message, data, slides, current_index, is_all_slides_request)
        except designer_chat_targets.TargetError as _scope_err:
            # An out-of-range slide number needs no LLM call at all.
            return jsonify({'success': False, 'error': str(_scope_err),
                            'error_code': 'DESIGNER_INVALID_TARGET'}), 422
        except Exception as _det_err:
            print(f"[DESIGNER-CHAT] deterministic table precheck failed: {_det_err}")
            deterministic_indexes = None
        if deterministic_indexes is not None:
            if table_probe.get('supported') and table_probe.get('operation') == 'delete':
                precheck_ok = bool(deterministic_indexes)
                for _pre_idx in deterministic_indexes:
                    _pre_slide = slides[_pre_idx] if isinstance(slides[_pre_idx], dict) else {}
                    _pre_res = designer_chat_reliability.apply_table_delete_request(
                        _pre_slide.get('html', ''), message)
                    if not _pre_res.get('changed'):
                        precheck_ok = False
                        break
                if precheck_ok:
                    deterministic_plan = {
                        'response': 'حذف حتمي من الجدول دون نموذج تخطيط.',
                        'actions': [{
                            'tool': 'edit_slides',
                            'params': {
                                'target': 'indexes',
                                'indexes': [_i + 1 for _i in deterministic_indexes],
                                'instruction': message,
                            },
                        }],
                    }
                    print(f"[DESIGNER-CHAT] deterministic table plan skips planner for slides "
                          f"{[_i + 1 for _i in deterministic_indexes]}")
                else:
                    table_failure_note = _table_precheck_note(slides, deterministic_indexes, message)
                    slim_table_indexes = list(deterministic_indexes)
                    print(f"[DESIGNER-CHAT] table precheck blocked, using slim planner: {table_failure_note[:300]}")
                    slim_planner_only = True
            elif table_probe.get('operation') == 'delete':
                table_failure_note = _table_precheck_note(slides, deterministic_indexes, message)
                slim_table_indexes = list(deterministic_indexes)
                print(f"[DESIGNER-CHAT] table delete precheck blocked, using slim planner: {table_failure_note[:300]}")
                slim_planner_only = True
    if deterministic_plan is not None:
        plan = deterministic_plan
        actions = plan.get('actions', []) if isinstance(plan.get('actions'), list) else []
        planner_raw = json.dumps(plan, ensure_ascii=False)
    else:
        audit_note = _build_designer_section_and_asset_context(slides, project_data, current_index, creative_images)
        project_context = _designer_project_context(project_data, creative_images, tenant_id)
    watermark_note = (
        'العلامة المائية المستقلة معتمدة ومتاحة لأداة apply_watermark.'
        if branding.get('watermark_path') else
        'لا توجد علامة مائية مرفوعة في إعدادات الشركة؛ لا تستبدلها بشعار الشركة.'
    )
    # An image the user attached in the chat: a design reference, something to insert, or the
    # problem they are pointing at. The attach button used to open the training page's file input,
    # so it never reached this endpoint at all.
    chat_attached_uris = _normalize_designer_attached_images(data)
    try:
        chat_attached_urls = _persist_designer_attached_images(chat_attached_uris, tenant_id)
    except Exception as _persist_err:
        print(f"[DESIGNER-CHAT] attached persist failed: {_persist_err}")
        chat_attached_urls = list(chat_attached_uris)
    user_image_refs = [{'data_uri': uri} for uri in chat_attached_uris] or None
    if chat_attached_urls:
        attached_note = (
            f"\n\n## صور أرفقها المستخدم في هذه الرسالة ({len(chat_attached_urls)}):\n"
            "الصور متاحة بصرياً كمرفقات، وعناوينها الدائمة للإدراج الحتمي هي:\n"
            + '\n'.join(f"- الصورة {i + 1}: {url}" for i, url in enumerate(chat_attached_urls))
            + "\nاستخدم أداة insert_attached_image حصراً لإدراج أي منها: separate_slide لشريحة منفصلة جديدة، "
              "inline داخل شريحة، background كخلفية، watermark كعلامة مائية، logo كشعار إضافي. "
              "لا تولّد بديلاً بالذكاء الاصطناعي لصورة مرفوعة، ولا تضعها كشعار شركة، "
              "وإن كان دورها غير واضح فاسأل عنه بأداة ask."
        )
    else:
        attached_note = ""
    # Legacy single-image alias kept for older executors that read the first attachment.
    attached_image = chat_attached_uris[0] if chat_attached_uris else ''
    # The planner sees creative_images as raw JSON and guesses token names;
    # enumerating the real assets with their exact tokens stops invented
    # placeholders like ##AERIAL_IMAGE_3## that resolve to nothing.
    designer_image_assets = _designer_image_assets(creative_images)
    if designer_image_assets:
        assets_note = (
            "\n\n## الأصول البصرية المتاحة في المشروع\n"
            "هذه صور المشروع الوحيدة المسموح سحبها لتحديث صور الشرائح. استخدم التوكن حرفياً كما هو؛ "
            "ممنوع اختراع أو تخمين أي توكن صورة غير مدرج هنا:\n"
            + '\n'.join(f"- {asset['token']} — {asset['label']}" for asset in designer_image_assets)
        )
    else:
        assets_note = ''
    if deterministic_plan is not None:
        pass
    elif slim_planner_only:
        # The full prompt is already doomed on this deck (or the local check already named
        # the exact blocker), so go slim directly: target slides only plus brief facts and
        # the deterministic failure note. The planner can then ask precisely — or, if the
        # retry still exceeds the cap, the caller returns the note instead of a raw 402.
        _slim_snippets = []
        for _s_idx in (slim_table_indexes or [])[:3]:
            _s = slides[_s_idx] if isinstance(slides[_s_idx], dict) else {}
            _slim_snippets.append(
                f"### شريحة {_s_idx + 1}: {str(_s.get('title', ''))[:200]}\n"
                f"{str(_s.get('html', ''))[:20000]}")
        try:
            _slim_brief = slide_engine.build_project_facts(project_data, tenant_id)
        except Exception:
            _slim_brief = ''
        if table_failure_note:
            _slim_brief = (str(_slim_brief or '') + "\n\n## نتيجة الفحص الحتمي للجدول (لا تعيد اختراعها)\n"
                           + table_failure_note)[:42000]
        planner_prompt = _build_designer_slim_planner_prompt(
            branding, training_note, watermark_note, summary,
            _slim_snippets, _slim_brief, all_note, memory_note,
            history_note, focus_note, explicit_scope_note)
        if attached_note:
            planner_prompt += attached_note
        print(f"[DESIGNER-CHAT] table-blocked prompt goes slim directly ({len(planner_prompt)} chars)")
    else:
        planner_prompt = f"""{build_design_rules(branding)}{training_note}

{watermark_note}

{project_context}
أنت Landloom، كبير المصممين ومهندس العرض وجرّاح كود وتصميم (Surgical Code & Design Master). اسمك Landloom — إذا سُئلت عن اسمك أو هويتك فأجب أنك Landloom، مساعد التصميم في المنصة.
أنت تمتلك كامل الصلاحية والحرية الإبداعية والمطلقة لتعديل أو إعادة تصميم أي شريحة في العرض دون استثناء:
- حرية مطلقة لتعديل وإعادة ابتكار شرائح الفصول والأقسام الرئيسية (Section Dividers / الفصول): لك كامل الحرية في إعادة تصميمها بتخطيطات إبداعية مبهرة (إضافة كروت ملخصة لمحاور القسم، خطوط زمنية، إبراز مؤشرات أو أرقام قياسية، تقسيم الشريحة أفقياً أو عمودياً Split View، دمج صور معمارية مع بطاقات داكنة ملكية، تدرجات لونية، خطوط عريضة).
- حرية مطلقة لتعديل وتطوير شريحة الفهرس ومحتويات العرض (Index): تصميمها بشبكات عصرية أو بطاقات مرقمة فاخرة مع الحفاظ على وسم data-index-page="section_key".
- حرية تعديل شرائح الغلاف والخاتمة وجميع شرائح المحتوى والخرائط والتحليلات.
- تعديل CSS والتخطيط (رفع/تنزيل الهيدر، تغيير الأحجام، إزاحة العناصر يميناً/يساراً، تعديل الألوان والخطوط).
- تعديل جراحي فوري لمحتوى أي شريحة (إضافة بطاقات، حذف عناصر، تعديل نصوص) دون مساس ببقية الشريحة.
- إدارة دورة حياة الشرائح كاملة: حذف شريحة (delete_slide)، تكرار شريحة (duplicate_slide)، إعادة ترتيب الشرائح (reorder_slides)، تقسيم شريحة كثيفة إلى شريحتين أو أكثر (split_slide)، دمج شريحتين (merge_slides)، أو إنشاء شريحة جديدة (create_slide).
- إدراج الخرائط الأربع المعتمدة بدقة (insert_canonical_map): خريطة الموقع العام، خريطة شبكة الطرق والوصول، خريطة النطاق الجغرافي، وخريطة المعالم الحيوية.
- إدراج وتعديل المخططات والرسوم المالية المعتمدة (insert_financial_chart): شلال التدفقات، تحليل الحساسية، التدفقات المركبة، وهيكل التمويل.
- توليد صور حصرية للمكونات المعمارية والداخلية والخارجية ودمجها جراحياً داخل الشرائح مع بطاقة شرح توضيحي.
- نفّذ الطلب الواضح، واسأل سؤالاً محدداً عندما يؤثر الغموض على الإجراء أو النطاق أو القيمة. لا تخمّن تعديلاً لم يطلبه المستخدم، ولا تعتبر مجرد ذكر رقم إذناً بالتعديل.
- الرد على سؤال سابق يكمل ذلك الطلب فقط. رسالة التصحيح أو الإلغاء تلغي الاستنتاج السابق. عند اختيار edit_slides اكتب instruction مكتملة تحمل التعديل والقيمة والقيود المفهومة من المحادثة، لا تنسخ الرد القصير وحده إلى المحرر.
{all_note} أعد JSON فقط:
{{"response":"رسالة عربية تشرح ما ستفعله جراحياً", "actions":[{{"tool":"edit_slides|apply_watermark|remove_watermark|generate_image|insert_attached_image|insert_canonical_map|update_slide_image|insert_financial_chart|delete_slide|duplicate_slide|reorder_slides|split_slide|merge_slides|create_slide|ask|chat_only", "params":{{}}}}]}}

الأدوات المتاحة:
أرقام الشرائح في كل الأدوات تشير إلى ترتيب العرض في بداية هذا الطلب، حتى عند نقل أو حذف شرائح في عملية سابقة ضمن الطلب نفسه.
- edit_slides: params={{"target":"current|all|indexes", "indexes":[1-based], "instruction":"التعديل الجراحي المطلوب بدقة"}}
- insert_attached_image: params={{"image_index":1-based, "position":"separate_slide|inline|background|watermark|logo", "target":"current|all|indexes", "indexes":[1-based], "slideIndex":1, "title":"عنوان الشريحة الجديدة عند separate_slide", "caption":"تعليق تحت الصورة", "opacity":0.12, "width_px":480}} لإدراج صورة أرفقها المستخدم في هذه الرسالة فقط. separate_slide تنشئ شريحة جديدة بعد الشريحة المستهدفة وتعرض الصورة كاملة. inline تدرجها داخل الشرائح المستهدفة. background تجعلها خلفية. watermark تضعها كعلامة مائية شفافة. logo تضعها كشعار إضافي صغير أعلى الشريحة. image_index يشير لترتيب الصورة المرفقة في هذه الرسالة ويبدأ من 1. لا تستخدم هذه الأداة عند عدم وجود صور مرفقة في هذه الرسالة.
- apply_watermark: params={{"target":"current|all|indexes", "indexes":[1-based], "only_white":true, "opacity":0.045, "width_px":480}} لإظهار العلامة المائية المستقلة المعتمدة في إعدادات الشركة في خلفية الشرائح — صيغ فعّل/أظهر/إظهار/أضف تعني هذه الأداة، و«إظهار» تعني الرؤية فقط وليست تكبيرًا. النطاق الافتراضي current عند عدم تحديد أرقام؛ أرسل all فقط عند طلب كل الشرائح صراحة (كل/جميع/العرض كله)، وأرسل indexes مع الأرقام العربية أو الإنجليزية المذكورة. أرسل only_white=true فقط إذا ذكر المستخدم الشرائح البيضاء أو الفاتحة صراحة، والافتراضي opacity=0.045 وwidth_px=480. إذا ذكر المستخدم نسبة أو قيمة شفافية صريحة (مثل 50%) فأرسلها كما هي حتى 1.0 ونفّذها فورًا دون اقتراح بديل، وإذا رفض اقتراحًا سابقًا أو كرر قيمة صريحة فلا تعِد طرح نفس السؤال بأداة ask. أرسل width_px حتى 640 إذا طلب علامة أكبر
- remove_watermark: params={{"target":"current|all|indexes", "indexes":[1-based]}} لإخفاء العلامة المائية من الشرائح — صيغ اخف/إخفاء/عطّل/إلغاء التفعيل/احذف تعني هذه الأداة مع نفس قواعد النطاق أعلاه
- apply_image_descriptions: params={{"target":"current|all|indexes", "indexes":[1-based]}} لإضافة أوصاف الصور المحفوظة بالفعل دون توليد صور أو اختراع وصف
- insert_team_logo: params={{"target":"current|all|indexes", "indexes":[1-based], "team_index":1-based}} لإضافة شعار جهة فريق العمل المرفوع فعلياً
- insert_company_logo_panel: params={{"target":"current|all|indexes", "indexes":[1-based]}} لوضع شعار الشركة داخل المربع الكحلي فوق رقم سنوات الخبرة
- generate_image: params={{"prompt":"وصف دقيق للصورة المراد توليدها", "component_name":"اسم المكون إن وجد", "slideIndex":1, "position":"surgical|background|right|left|inline"}}
- insert_canonical_map: params={{"map_type":"overview|access|catchment|landmarks", "target":"current|indexes", "slideIndex":1, "refresh":true عند طلب تحديث خريطة موجودة}}
- update_slide_image: params={{"asset":"##MOODBOARD_IMAGE_3##", "image_index":1, "target":"current|indexes", "indexes":[1-based]}} لاستبدال صورة داخل الشريحة بأصل بصري من المشروع دون إعادة تصميم — asset هو التوكن الدقيق من قائمة «الأصول البصرية المتاحة» فقط، وimage_index اختياري يحدد الصورة داخل الشريحة بترتيب ظهورها (يبدأ من 1) عندما تحتوي الشريحة على أكثر من صورة.
- insert_financial_chart: params={{"chart_type":"waterfall|sensitivity|compound_flows|financing_structure", "target":"current|indexes", "slideIndex":1}}
- delete_slide: params={{"slide_number":1-based, "slide_numbers":[1-based]}}
- duplicate_slide: params={{"slide_number":1-based}}
- reorder_slides: params={{"from_index":1-based, "to_index":1-based}}
- split_slide: params={{"slide_number":1-based, "parts":2, "instruction":"تفاصيل التقسيم والتنظيم"}}
- merge_slides: params={{"slide_numbers":[1-based, 1-based], "instruction":"تفاصيل الدمج"}}
- create_slide: params={{"title":"العنوان", "type":"content|cover|divider|table|kpi", "instruction":"محتوى الشريحة وتصميمها", "position":1-based}}
- regenerate_maps: params={{"maptype":"roadmap|satellite|hybrid|terrain"}}
- ask: params={{"question":"سؤال عربي واحد قصير يحسم الغموض"}} — ينهي الدور دون تنفيذ أي تعديل.
- chat_only: params={{}} للرد أو الشرح أو تأكيد الإلغاء دون تعديل العرض.

قواعد إضافة واستخدام الخرائط:
1. ##MAP_ACCESS## : لخريطة شبكة الطرق والمحاور والوصول.
2. ##MAP_OVERVIEW## : لخريطة النظرة العامة والموقع العام.
3. ##MAP_LANDMARKS## : لخريطة المعالم والخدمات والمواقع الحيوية القريبة.
4. ##MAP_CATCHMENT## : لخريطة النطاق الجغرافي واستيعاب المنطقة.

قواعد الفهم الذكي:
1. إذا كان الطلب يتضمن تعديل كل الشرائح -> اختر target="all".
2. حدّد معنى الأرقام من السياق: قد تكون قيمة أو حجم خط أو نسبة أو عدد عناصر أو رقم شريحة. لا تختَر indexes إلا عندما يشير الكلام أو جواب السؤال السابق إلى شرائح بالفعل. ذكر شريحة وحده ليس طلب تعديل؛ إذا غاب الإجراء المطلوب اسأل عنه. أرقام indexes تبدأ من 1.
3. إذا طلب حذف شريحة (مثل: "احذف الشريحة 5") -> اختر tool="delete_slide" مع slide_number.
4. إذا طلب تكرار شريحة (مثل: "كرر الشريحة 2") -> اختر tool="duplicate_slide" مع slide_number.
5. إذا طلب تغيير ترتيب (مثل: "انقل الشريحة 8 إلى 4") -> اختر tool="reorder_slides" مع from_index و to_index.
6. إذا طلب تقسيم أو تجزئة شريحة أو محتوى شريحة معينة (مثل: "اقسم محتوى الملخص التنفيذي" أو "جزئ الشريحة 4") -> اختر tool="split_slide" مع slide_number للشريحة المستهدفة.
7. إذا طلب دمج شريحتين (مثل: "ادمج الشريحة 3 مع 4") -> اختر tool="merge_slides" مع slide_numbers.
8. إذا طلب إنشاء أو إضافة شريحة جديدة -> اختر tool="create_slide" مع العنوان والمحتوى والموضع.
9. إذا طلب خريطة الموقع أو الوصول أو المعالم -> اختر tool="insert_canonical_map".
   وإذا طلب تحديث أو إعادة تحميل أو استبدال خريطة موجودة في شريحة، أرسل refresh=true حتى تُستخدم أحدث نسخة محفوظة للخريطة نفسها.
10. إذا طلب رسم أو مخطط مالي (شلال/حساسية/عوائد) -> اختر tool="insert_financial_chart".
11. إذا طلب تغيير نوع الخريطة (شوارع/مرور/قمر صناعي/roadmap/satellite) -> اختر tool="regenerate_maps".
12. إذا كان الطلب سؤالاً لا يتطلب تعديلاً -> اختر tool="chat_only".
13. إذا طلب المستخدم شعار جهة محددة من فريق العمل، ميّزها عن شعار الشركة واستخدم tool="insert_team_logo" مع team_index الصحيح. لا تستخدم هذه الأداة إلا إذا احتوت الرسالة الحالية نفسها على كلمة شعار أو لوجو أو علامة تجارية مع اسم الجهة؛ فطلب الصورة أو الوصف ليس طلب شعار.
14. إذا طلب المستخدم نقل أو وضع شعار الشركة داخل المربع الكحلي في يمين الشريحة، استخدم tool="insert_company_logo_panel" ولا تستخدم شعار فريق العمل.
15. في سائر طلبات التعديل والتنسيق والتصميم -> اختر tool="edit_slides".
16. فرّق بدقة بين الصورة والوصف والشعار: طلب وصف أو شرح أو تعليق أو كابشن لصور موجودة (مثل: «أضف وصفاً لصور التصور البصري») يعني تعديلاً نصياً فقط عبر tool="edit_slides" مع تعليمات إضافة نص وصفي تحت الصور الموجودة، دون توليد صورة جديدة ودون أي رمز شعار (ممنوع ##TEAM_LOGO_N## و##LOGO## و##PROJECT_LOGO##). وطلب صورة أو تصميم أو توليد صور جديدة يعني tool="generate_image" لصورة معمارية جديدة وليس شعاراً. ولا تستخدم أي رمز شعار إلا عند طلب شعار صريح في الرسالة الحالية.
17. «أعد تصميم» أو «حسّن» قسم أو نطاق من الشرائح (مثل: «أعد تصميم قسم الملخص التنفيذي» أو «حسّن الشرائح 71 إلى 79») تعني tool="edit_slides" على كل شرائح ذلك النطاق — إعادة التصميم لا تعني التقسيم. لا تختر tool="split_slide" إلا إذا طلب المستخدم صراحة تقسيم شريحة أو توزيع محتواها على شرائح (مثل: «قسّم الشريحة 5 إلى شريحتين»).
- طلب تقليل عدد الشرائح أو الصفحات أو إعادة هيكلة عدة شرائح في عدد أقل أو أكبر (مثل: «قلل الصفحات» أو «اجعل القسم 5 شرائح») يحتاج قراراً من المستخدم عن الشرائح والعدد — اسأل بأداة ask ولا تستخدم split_slide ولا delete_slide تخميناً.
- احرص دائماً على الحفاظ التام على كامل الأرقام والبيانات والمؤشرات دون حذف أي تفصيل، وتوزيعها في كروت فاخرة وأقسام متوازنة مريحة بصرياً وخالية من أي إيموجي أو أيقونات.
18. حذف صف أو عمود أو سطر من جدول داخل شريحة (مثل: «احذف الصف الثالث من الجدول» أو «شيل عمود السعر») هو تعديل داخل الشريحة عبر tool="edit_slides" فقط — وليس delete_slide ولا split_slide ولا create_slide. لا تختر delete_slide إلا إذا ذكر المستخدم كلمة شريحة/سلايد صراحة مع الحذف (مثل: «احذف الشريحة 5»). قواعد الحفاظ على البيانات لا تمنع هذا الحذف: هو حذف عرضي من الشريحة فقط وبيانات المشروع الأصلية تبقى كما هي. عند اختيار edit_slides لطلب صف/عمود اكتب instruction مكتملة تحمل نوع الحذف (صف أم عمود) ورقمه أو محتواه أو اسم العمود، ولا تنسخ الرد القصير وحده.
19. الصورة المرفقة في هذه الرسالة هي أصل لا يُستبدل: طلب وضعها في شريحة منفصلة أو داخل شريحة أو كخلفية أو كعلامة مائية أو كشعار إضافي يعني حصراً tool="insert_attached_image" مع الموضع المناسب. ممنوع توليد صورة بديلة لها بـ generate_image، وممنوع استخدام apply_watermark أو insert_team_logo لها. عند غياب صور مرفقة في هذه الرسالة لا تختر insert_attached_image أبداً.
20. طلب تحديث أو استبدال أو سحب صورة موجودة في شريحة إلى صورة من أصول المشروع (تصور خارجي أو داخلي أو مخطط معماري أو صورة أرض أو الصورة الرئيسية) يعني حصراً tool="update_slide_image" مع asset التوكن الدقيق من قائمة «الأصول البصرية المتاحة». ممنوع كتابة توكنات صور من عندك داخل HTML — أي توكن غير مدرج في القائمة يُحذف وتبقى الشريحة بلا صورة.

{audit_note}{attached_note}{assets_note}

قائمة الشرائح الحالية في العرض ({len(slides)} شريحة):
{json.dumps(summary, ensure_ascii=False)}
{memory_note}{history_note}{focus_note}{explicit_scope_note}"""
        if len(slides) > 10:
            _explicit_targets = designer_chat_targets.explicit_slide_numbers(message) or ([current_index + 1] if 0 <= current_index < len(slides) else [])
            _explicit_snippets = []
            for _t_num in (_explicit_targets or [])[:5]:
                try:
                    _t_idx = designer_chat_targets.slide_number(_t_num, len(slides)) - 1
                    _t_slide = slides[_t_idx] if isinstance(slides[_t_idx], dict) else {}
                    _explicit_snippets.append(f"### محتوى الشريحة {_t_idx + 1} المستهدفة:\n" + str(_t_slide.get('html', ''))[:15000])
                except Exception:
                    pass
            if _explicit_snippets:
                planner_prompt += "\n\n## الشرائح المستهدفة في الطلب:\n" + "\n\n".join(_explicit_snippets)
        if user_image_refs and not chat_attached_urls:
            planner_prompt += ("\n\nأرفق المستخدم صورة مع رسالته. انظر إليها قبل التخطيط، وإن لم يكن دورها"
                              " واضحًا فاسأل عنه بأداة ask.")
    try:
        if deterministic_plan is not None:
            pass
        else:
            try:
                planner_raw = extract_chat_content(
                    call_zai_chat(planner_prompt, message, max_tokens=DESIGNER_PLANNER_MAX_TOKENS, model=SLIDE_TEXT_MODEL, image_references=user_image_refs, timeout=300, usage_ctx=_usage_ctx('designer_chat', data, presentation_id=presentation_id)),
                    'DESIGNER-PLANNER')
            except Exception as _planner_exc:
                if _is_company_credit_error(_planner_exc):
                    return jsonify({'success': False,
                                    'error': _COMPANY_CREDIT_EXHAUSTED_MSG,
                                    'error_code': 'INSUFFICIENT_CREDITS'}), 402
                if not _is_designer_prompt_token_error(_planner_exc):
                    raise
                print(f"[DESIGNER-CHAT] planner prompt exceeded token cap ({len(planner_prompt)} chars): {_planner_exc}")
                if slim_planner_only:
                    # Already slim and still over the cap: surface the deterministic
                    # diagnosis instead of a raw provider 402.
                    _detail = f' {table_failure_note}' if table_failure_note else ''
                    return jsonify({'success': False,
                                    'error': f'تعذر تنفيذ الطلب ضمن حد التوكنز الحالي.{_detail}',
                                    'error_code': 'DESIGNER_PROMPT_TOO_LARGE'}), 402
                # A supported table delete never needs a second LLM attempt: the local
                # surgical edit below applies it without any prompt tokens.
                _retry_probe = designer_chat_reliability.detect_table_edit_request(message)
                if _retry_probe.get('supported') and _retry_probe.get('operation') == 'delete':
                    try:
                        _retry_indexes = _resolve_deterministic_table_targets(
                            message, data, slides, current_index, is_all_slides_request)
                        _retry_ok = bool(_retry_indexes)
                        for _r_idx in _retry_indexes:
                            _r_slide = slides[_r_idx] if isinstance(slides[_r_idx], dict) else {}
                            _r_res = designer_chat_reliability.apply_table_delete_request(
                                _r_slide.get('html', ''), message)
                            if not _r_res.get('changed'):
                                _retry_ok = False
                                break
                        if _retry_ok:
                            plan = {
                                'response': 'حذف حتمي من الجدول بعد تجاوز حد التوكنز.',
                                'actions': [{
                                    'tool': 'edit_slides',
                                    'params': {
                                        'target': 'indexes',
                                        'indexes': [_i + 1 for _i in _retry_indexes],
                                        'instruction': message,
                                    },
                                }],
                            }
                            actions = plan.get('actions', [])
                            planner_raw = json.dumps(plan, ensure_ascii=False)
                        else:
                            raise
                    except Exception:
                        raise _planner_exc
                else:
                    # Slim retry: target slides only plus brief facts instead of the full deck.
                    try:
                        _slim_targets = designer_chat_targets.explicit_slide_numbers(message) or [current_index + 1]
                        _slim_valid = []
                        for _n in _slim_targets:
                            try:
                                _slim_valid.append(designer_chat_targets.slide_number(_n, len(slides)) - 1)
                            except Exception:
                                continue
                        if not _slim_valid:
                            _slim_valid = [current_index] if 0 <= current_index < len(slides) else [0]
                        _snippets = []
                        for _s_idx in _slim_valid[:3]:
                            _s = slides[_s_idx] if isinstance(slides[_s_idx], dict) else {}
                            _snippets.append(
                                f"### شريحة {_s_idx + 1}: {str(_s.get('title', ''))[:200]}\n"
                                f"{str(_s.get('html', ''))[:20000]}")
                        try:
                            _brief = slide_engine.build_project_facts(project_data, tenant_id)
                        except Exception:
                            _brief = ''
                        slim_prompt = _build_designer_slim_planner_prompt(
                            branding, training_note, watermark_note, summary,
                            _snippets, _brief, all_note, memory_note,
                            history_note, focus_note, explicit_scope_note)
                        print(f"[DESIGNER-CHAT] retrying planner slim ({len(slim_prompt)} chars, was {len(planner_prompt)} chars)")
                        planner_raw = extract_chat_content(
                            call_zai_chat(slim_prompt, message, max_tokens=DESIGNER_PLANNER_MAX_TOKENS, model=SLIDE_TEXT_MODEL, image_references=user_image_refs, timeout=300, usage_ctx=_usage_ctx('designer_chat', data, presentation_id=presentation_id)),
                            'DESIGNER-PLANNER')
                    except Exception as _slim_exc:
                        if _is_company_credit_error(_slim_exc):
                            return jsonify({'success': False,
                                            'error': _COMPANY_CREDIT_EXHAUSTED_MSG,
                                            'error_code': 'INSUFFICIENT_CREDITS'}), 402
                        if _is_designer_prompt_token_error(_slim_exc):
                            _detail = f' {table_failure_note}' if table_failure_note else ''
                            _is_explicit = bool(designer_chat_targets.explicit_slide_numbers(message))
                            _err_msg = (
                                f'تعذر إتمام تعديل الشريحة ضمن حد التوكنز الحالي للنموذج.{_detail}'
                                if _is_explicit else
                                f'العرض كبير جدًا على حد التوكنز الحالي؛ حدّد شريحة واحدة برقمها وأعد المحاولة.{_detail}'
                            )
                            return jsonify({'success': False,
                                            'error': _err_msg,
                                            'error_code': 'DESIGNER_PROMPT_TOO_LARGE'}), 402
                        raise
            plan = _designer_json_response(planner_raw)
            actions = plan.get('actions', []) if isinstance(plan.get('actions'), list) else []

        return _designer_legacy_apply(
            plan, actions, message, data, slides, project_data, presentation,
            presentation_id, branding, tenant_id, current_index, creative_images,
            request_creative_images, project_creative_images, user_image_refs,
            chat_attached_urls, history_for_turn, chat_memory, focus_indexes,
            preferred_indexes, slides_before, is_all_slides_request,
            report_designer_progress)
    except designer_chat_targets.TargetError as exc:
        return jsonify({'success': False, 'error': str(exc), 'error_code': 'DESIGNER_INVALID_TARGET'}), 422
    except Exception as exc:
        print(f'[DESIGNER-CHAT ERROR] {exc}')
        return jsonify({'success': False, 'error': _client_safe_llm_error(exc)}), 500


@app.route('/api/files', methods=['GET'])
def api_files():
    """Compatibility: List files"""
    return jsonify({'success': True, 'files': []})


@app.route('/api/project-data', methods=['GET'])
def api_project_data():
    """Compatibility: Get project data"""
    return jsonify({'success': True, 'data': {}})


@app.route('/api/generate-cover-prompt', methods=['POST'])
@require_permission('generate_images')
def api_generate_cover_prompt():
    """Compatibility: Generate detailed cover image prompt using GLM"""
    data = request.json
    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard
    project_data = clean_project_data(data.get('projectData', {}))

    project_name = project_data.get('projectName', '')
    project_type = project_data.get('projectType', 'سكني')
    location = project_data.get('location', 'السعودية')
    description = project_data.get('idea', '') or project_data.get('description', '')
    features = project_data.get('projectFeatures', [])
    features_text = ', '.join(features) if isinstance(features, list) else str(features)

    glm_prompt = f"""أنت متخصص في كتابة prompts لتصوير معماري احترافي.

بيانات المشروع:
- الاسم: {project_name}
- النوع: {project_type}
- الموقع: {location}
- الوصف: {description}
- المميزات: {features_text}

اكتب prompt واحد بالإنجليزي لتصوير غلاف هذا العرض التقديمي.
المطلوب:
- وصف دقيق للمبنى بناءً على نوعه وموقعه
- أسلوب تصوير معماري احترافي
- إضاءة طبيعية أو مسائية جذابة
- زاوية تصوير تُبرز فخامة المشروع
- بدون أي نصوص أو علامات مائية
- بدون أشخاص
- جودة عالية جداً

اكتب فقط البرومبت بدون أي شرح."""

    try:
        response = call_zai_chat(glm_prompt, "اكتب البرومبت.", max_tokens=500, usage_ctx=_usage_ctx('image', data))
        prompt = extract_chat_content(response, "COVER-PROMPT").strip()

        # Clean up the prompt
        prompt = prompt.strip('"').strip("'")
        if prompt.startswith('Prompt:') or prompt.startswith('prompt:'):
            prompt = prompt.split(':', 1)[1].strip()

        print(f"[COVER PROMPT] Generated: {prompt[:100]}...")
        return jsonify({'success': True, 'prompt': prompt})

    except Exception as e:
        # Fallback to basic prompt
        fallback = f"Professional architectural photography of a modern luxury {project_type} building in {location}, {project_name}. Elegant contemporary design with premium finishes, glass facade, warm golden hour lighting, landscaped surroundings. Shot from a low angle to emphasize grandeur. High resolution, no text, no watermarks, no people."
        print(f"[COVER PROMPT] GLM failed, using fallback: {str(e)}")
        return jsonify({'success': True, 'prompt': fallback})
