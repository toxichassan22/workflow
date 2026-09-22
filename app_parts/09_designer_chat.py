

@app.route('/api/designer-chat', methods=['POST'])
@require_permission('create_presentation')
def api_designer_chat():
    """Agentic designer chat operating on one slide or the complete presentation."""
    data = request.json or {}
    _billing_guard = _require_billing_balance('designer_chat')
    if _billing_guard is not None:
        return _billing_guard
    job_id = request.headers.get('X-Designer-Job-Id') or data.get('_job_id')
    tenant_id = g.tenant_id

    def report_designer_progress(progress_val, message_text, extra_data=None):
        _report_designer_job_progress(job_id, tenant_id, progress_val, message_text, extra_data)

    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'الطلب فارغ'}), 400
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

    project_data = _designer_project_data_for_request(
        request_project_data, presentation, tenant_id)
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
    # provider balance. Answer those turns locally with zero tokens spent.
    _free_probe_uris = _normalize_designer_attached_images(data)
    _free_text = _designer_chat_free_reply(message, has_attachment=bool(_free_probe_uris))
    if _free_text is not None:
        _free_messages = list(history_for_turn)
        if not _free_messages or _free_messages[-1].get('content') != message or _free_messages[-1].get('role') != 'user':
            _free_messages.append({'role': 'user', 'content': message[:2000], 'slides': preferred_indexes[:]})
        _free_messages.append({'role': 'assistant', 'content': _free_text[:2000], 'slides': preferred_indexes[:]})
        _free_trimmed = _normalize_designer_chat_messages(_free_messages)[-DESIGNER_CHAT_STORED_TURNS * 2:]
        return jsonify({'success': True, 'data': {
            'action': 'chat_only', 'response': _free_text, 'actions': [],
            'memory': chat_memory, 'focusIndexes': focus_indexes,
            'chatHistory': _free_trimmed, 'saved': False,
            'ai_calls': 0, 'billed': False,
        }})

    branding = db.get_branding(g.tenant_id) or {}
    _prepare_generation_logo_context(project_data, branding, g.tenant_id)
    training_context = db.get_training_context(g.tenant_id) or ''
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
أنت Sol، كبير المصممين ومهندس العرض وجرّاح كود وتصميم (Surgical Code & Design Master).
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
17. إذا طلب المستخدم إعادة توليد أو تصميم قسم كامل أو توزيع محتوى شريحة على عدة شرائح (مثل: «أعد توليد قسم الملخص التنفيذي على أكثر من شريحة مصممة جيداً وقوية بصرياً»):
- أنت Agent كامل الصلاحية: اختر الشريحة أو الشرائح المناسبة من قائمة الشرائح، ونفذ التقسيم والتوزيع الفاخر عبر tool="split_slide" مع تحديد slide_number و parts وتضمين تعليمات التصميم الجمالي والتوزيع المتناسق في instruction، أو ادمج بين edit_slides و create_slide.
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
                if _is_openrouter_credit_error(_planner_exc):
                    return jsonify({'success': False,
                                    'error': 'رصيد مفتاح الذكاء الاصطناعي (OpenRouter) غير كافٍ أو تم تجاوز الحد الشهري للمفتاح؛ يرجى مراجعة إعدادات المفتاح أو شحن الرصيد.',
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
                        if _is_openrouter_credit_error(_slim_exc):
                            return jsonify({'success': False,
                                            'error': 'رصيد مفتاح الذكاء الاصطناعي (OpenRouter) غير كافٍ أو تم تجاوز الحد الشهري للمفتاح؛ يرجى مراجعة إعدادات المفتاح أو شحن الرصيد.',
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

        # A question is an answer on its own: nothing is edited until the user replies.
        question = ''
        for action in actions if isinstance(actions, list) else []:
            if isinstance(action, dict) and action.get('tool') == 'ask':
                params = action.get('params') if isinstance(action.get('params'), dict) else {}
                question = str(params.get('question') or '').strip()
                if question:
                    break
        if question:
            ask_messages = list(history_for_turn)
            if not ask_messages or ask_messages[-1].get('content') != message or ask_messages[-1].get('role') != 'user':
                ask_messages.append({'role': 'user', 'content': message[:2000], 'slides': preferred_indexes[:]})
            ask_messages.append({'role': 'assistant', 'content': question[:2000], 'slides': preferred_indexes[:]})
            ask_chat = {
                'presentationId': presentation_id or None,
                'messages': ask_messages[-DESIGNER_CHAT_STORED_TURNS * 2:],
                'memory': chat_memory,
                'focusIndexes': preferred_indexes[:],
            }
            ask_project_data = dict(project_data)
            ask_project_data['designerChat'] = ask_chat
            return jsonify({'success': True, 'data': {
                'action': 'ask',
                'response': question,
                'slidesData': slides,
                'creativeImages': data.get('creativeImages') if isinstance(data.get('creativeImages'), dict) else {},
                'actions': [{'tool': 'ask', 'status': 'success'}],
                'memory': chat_memory,
                'focusIndexes': focus_indexes,
                'chatHistory': ask_chat['messages'],
                'saved': False,
            }})

        if not actions or any(not isinstance(action, dict) for action in actions):
            return jsonify({'success': False, 'error': 'لم تصل خطة تنفيذ صالحة؛ لم يتغير العرض.',
                            'error_code': 'DESIGNER_INVALID_PLAN'}), 502

        if all(action.get('tool') == 'chat_only' for action in actions):
            response_text = str(plan.get('response') or '').strip()
            chat_messages = list(history_for_turn)
            chat_messages.append({'role': 'user', 'content': message[:2000], 'slides': []})
            chat_messages.append({'role': 'assistant', 'content': response_text[:2000], 'slides': []})
            return jsonify({'success': True, 'data': {
                'action': 'chat_only', 'response': response_text, 'actions': [],
                'memory': chat_memory, 'focusIndexes': focus_indexes,
                'chatHistory': chat_messages[-DESIGNER_CHAT_STORED_TURNS * 2:], 'saved': False,
            }})

        try:
            actions = designer_chat_targets.prepare_actions(actions, data, message, slides, current_index)
        except designer_chat_targets.TargetError as _plan_scope_err:
            # The planner named slides outside the explicit request (e.g. it followed an older
            # focus instead of «شريحة 13»). For a supported table row/column delete the message
            # itself already resolves the targets, and the executor below applies the edit
            # deterministically — so fall back to those slides instead of failing the turn
            # with «خطة التعديل لا تطابق الشرائح المحددة» and changing nothing.
            _scope_probe = designer_chat_reliability.detect_table_edit_request(message)
            _scope_fallback = None
            if _scope_probe.get('supported') and _scope_probe.get('operation') == 'delete':
                try:
                    _scope_indexes = _resolve_deterministic_table_targets(
                        message, data, slides, current_index, is_all_slides_request)
                    if _scope_indexes:
                        _scope_fallback = [{
                            'tool': 'edit_slides',
                            'params': {
                                'target': 'indexes',
                                'indexes': [_i + 1 for _i in _scope_indexes],
                                'instruction': message,
                            },
                        }]
                        print(f"[DESIGNER-CHAT] planner scope rejected ({_plan_scope_err}); "
                              f"falling back to message-resolved slides {[_i + 1 for _i in _scope_indexes]}")
                except Exception as _scope_resolve_err:
                    print(f"[DESIGNER-CHAT] scope fallback resolve failed: {_scope_resolve_err}")
                    _scope_fallback = None
            if _scope_fallback is None:
                raise
            actions = _scope_fallback
        original_slide_objects = list(slides)
        executed = []
        assistant_messages = []
        tenant_id = g.tenant_id
        for action_number, planned_action in enumerate(actions):
            action = designer_chat_targets.remap_action(planned_action, original_slide_objects, slides)
            tool = action.get('tool') if isinstance(action, dict) else ''
            params = action.get('params') if isinstance(action.get('params'), dict) else {}
            if tool in ('ask', 'chat_only', 'validate_design_workspace', 'save_design_workspace'):
                continue
            if tool == 'apply_image_descriptions':
                indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                descriptions = designer_chat_reliability.collect_image_descriptions(project_data, creative_images)
                changed = []
                for idx in indexes:
                    report_designer_progress(35, f'جاري تعديل الشريحة {idx + 1}...',
                                            {'phase': 'editing', 'activeSlideIndex': idx, 'actionNumber': action_number})
                    updated, count, _ = designer_chat_reliability.add_missing_image_descriptions(slides[idx].get('html', ''), descriptions)
                    if count:
                        slides[idx].update(html=updated, _designer_keep_html=True, is_custom=True)
                        changed.append(idx)
                executed.append({'tool': tool, 'status': 'success' if changed else 'noop', 'indexes': changed})
                assistant_messages.append(f'أضيفت الأوصاف المحفوظة إلى {len(changed)} شريحة.' if changed else 'لا توجد أوصاف محفوظة ناقصة ومطابقة للصور المستهدفة.')
            elif tool in ('apply_watermark', 'remove_watermark'):
                indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                # Default off: without an explicit white-only request every targeted
                # slide gets the watermark, otherwise dark slides were silently skipped.
                only_white = params.get('only_white', False)
                is_remove = (tool == 'remove_watermark')
                watermark_url = str(branding.get('watermark_path') or '').strip()
                if not is_remove and not watermark_url:
                    assistant_messages.append('لا توجد علامة مائية مرفوعة في إعدادات الشركة؛ لم تتغير أي شريحة.')
                    executed.append({
                        'tool': tool, 'status': 'failed', 'indexes': [],
                        'reason': 'watermark_missing',
                    })
                    continue
                affected_indexes = []
                skipped_dark_indexes = []
                total_target = max(1, len(indexes))
                report_designer_progress(20, 'جاري معالجة العلامة المائية للشرائح...')
                for i, idx in enumerate(indexes):
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    if only_white and not _is_white_or_light_slide(slide):
                        skipped_dark_indexes.append(idx)
                        continue
                    report_designer_progress(25, f'جاري تعديل الشريحة {idx + 1}...',
                                            {'phase': 'editing', 'activeSlideIndex': idx, 'actionNumber': action_number})
                    current_slide_html = slide.get('html', '')
                    if is_remove:
                        # Hiding keeps the saved position/size/opacity so a later
                        # show restores exactly what the user had.
                        new_html = _set_slide_watermark_visible(current_slide_html, False)
                    else:
                        try:
                            wm_opacity = float(params.get('opacity', 0.045))
                        except (TypeError, ValueError):
                            wm_opacity = 0.045
                        try:
                            wm_width = int(params.get('width_px', 480))
                        except (TypeError, ValueError):
                            wm_width = 480
                        new_html = _apply_slide_watermark(current_slide_html, watermark_url, opacity=wm_opacity, width_px=wm_width)
                    slide['html'] = new_html
                    slide['_designer_keep_html'] = True
                    slide['is_custom'] = True
                    slides[idx] = slide
                    affected_indexes.append(idx)
                    pct = int(20 + 75 * ((i + 1) / total_target))
                    report_designer_progress(pct, f"تمت معالجة الشريحة {i + 1} من {total_target}...")

                executed.append({
                    'tool': tool,
                    'status': 'success',
                    'indexes': affected_indexes,
                    'count': len(affected_indexes),
                    'skipped_indexes': [idx + 1 for idx in skipped_dark_indexes],
                    'skipped_count': len(skipped_dark_indexes),
                })
                action_desc = 'حذف' if is_remove else 'إضافة'
                if (not is_remove) and only_white:
                    skipped_dark = len(skipped_dark_indexes)
                    if skipped_dark > 0:
                        skipped_numbers = ', '.join(str(idx + 1) for idx in sorted(skipped_dark_indexes)[:20])
                        if skipped_dark > 20:
                            skipped_numbers += f' وغيرها ({skipped_dark} إجمالاً)'
                        assistant_messages.append(
                            f"تم {action_desc} العلامة المائية بنجاح في خلفية {len(affected_indexes)} شريحة بيضاء "
                            f"وتخطي {skipped_dark} شريحة داكنة (أرقام: {skipped_numbers}) "
                            f"مع الحفاظ الكامل على النصوص والتصميم."
                        )
                    else:
                        assistant_messages.append(
                            f"تم {action_desc} العلامة المائية بنجاح في خلفية {len(affected_indexes)} شريحة مع الحفاظ الكامل على النصوص والتصميم."
                        )
                else:
                    assistant_messages.append(
                        f"تم {action_desc} العلامة المائية بنجاح في خلفية {len(affected_indexes)} شريحة مع الحفاظ الكامل على النصوص والتصميم."
                    )
            elif tool == 'insert_attached_image':
                # Deterministic insertion of a user-uploaded chat image: no model call.
                try:
                    _image_index = int(params.get('image_index') or params.get('imageIndex') or 1)
                except (TypeError, ValueError):
                    _image_index = 1
                if not chat_attached_urls or _image_index < 1 or _image_index > len(chat_attached_urls):
                    assistant_messages.append(
                        'لا توجد صورة مرفقة بهذه الرسالة بالترتيب المطلوب؛ أرفق الصورة مع نفس الرسالة ثم أعد الطلب.')
                    executed.append({'tool': tool, 'status': 'failed', 'reason': 'attached_image_missing'})
                    continue
                _image_url = chat_attached_urls[_image_index - 1]
                _position = _designer_attached_image_position(message, params)
                try:
                    _opacity = float(params.get('opacity', 0.12 if _position == 'watermark' else 1.0))
                except (TypeError, ValueError):
                    _opacity = 0.12 if _position == 'watermark' else 1.0
                try:
                    _width = int(params.get('width_px', params.get('widthPx', 480 if _position == 'watermark' else 140)))
                except (TypeError, ValueError):
                    _width = 480 if _position == 'watermark' else 140
                _caption = str(params.get('caption') or '')[:160]
                _title = str(params.get('title') or message or 'صورة مرفقة')[:160]
                if _position == 'separate_slide':
                    try:
                        _targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                    except designer_chat_targets.TargetError:
                        _targets = [current_index] if 0 <= current_index < len(slides) else [len(slides) - 1]
                    _insert_at = max(_targets) + 1 if _targets else len(slides)
                    _new_html = _build_designer_attached_slide_html(_image_url, title=_title, caption=_caption, branding=branding)
                    try:
                        _new_html = resolve_designer_chat_placeholders(
                            _new_html, project_data, presentation_id, tenant_id, creative_images)
                        _new_html = slide_engine.finalize_designer_slide_html(
                            _new_html, 'content', project_data, branding,
                            creative_images=creative_images, tenant_id=tenant_id,
                            slide_num=_insert_at + 1, slide_title=_title,
                            total_slides=len(slides) + 1, content_source='designer_attached_image',
                            allow_all_maps=True)
                    except Exception as _fin_err:
                        print(f"[DESIGNER-CHAT] attached slide finalize failed: {_fin_err}")
                    _new_slide = {'html': _new_html, 'title': _title, 'type': 'content',
                                  'content_source': 'designer_attached_image',
                                  'section_key': '', '_designer_keep_html': True, 'is_custom': True}
                    slides.insert(min(_insert_at, len(slides)), _new_slide)
                    report_designer_progress(60, f'تم إنشاء شريحة جديدة للصورة المرفقة بعد الشريحة {_insert_at}...')
                    executed.append({'tool': tool, 'status': 'success', 'position': _position,
                                     'image_index': _image_index, 'inserted_at': _insert_at + 1})
                    assistant_messages.append(f'تم وضع الصورة المرفقة في شريحة منفصلة جديدة رقم {_insert_at + 1}.')
                else:
                    _indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                    for _i, _idx in enumerate(_indexes):
                        _slide = slides[_idx] if isinstance(slides[_idx], dict) else {}
                        _slide['html'] = _insert_designer_attached_image(
                            _slide.get('html', ''), _image_url, position=_position,
                            opacity=_opacity, width_px=_width, caption=_caption)
                        _slide['_designer_keep_html'] = True
                        _slide['is_custom'] = True
                        slides[_idx] = _slide
                        report_designer_progress(
                            int(20 + 60 * ((_i + 1) / max(1, len(_indexes)))),
                            f'تم إدراج الصورة المرفقة في الشريحة {_idx + 1}...')
                    executed.append({'tool': tool, 'status': 'success', 'position': _position,
                                     'image_index': _image_index, 'indexes': _indexes})
                    _pos_names = {'inline': 'داخل الشريحة', 'background': 'كخلفية للشريحة',
                                  'watermark': 'كعلامة مائية', 'logo': 'كشعار إضافي'}
                    assistant_messages.append(
                        f"تم وضع الصورة المرفقة {_pos_names.get(_position, 'داخل الشريحة')} "
                        f"في {len(_indexes)} شريحة.")
            elif tool in ('edit_slides', 'edit_design_slide', 'edit_design_slides'):
                indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                instruction = params.get('instruction') or message
                original_table_request = designer_chat_reliability.detect_table_edit_request(message)
                if original_table_request.get('supported') and original_table_request.get('operation') == 'delete':
                    instruction = message
                changed_indexes = []
                if indexes:
                    report_designer_progress(20, f'جاري تعديل الشريحة {indexes[0] + 1}...',
                                            {'phase': 'editing', 'activeSlideIndex': indexes[0], 'actionNumber': action_number})
                if len(indexes) > 1:
                    skip_vision = len(indexes) > 3
                    def _edit_worker(idx):
                        with app.app_context():
                            slide_item = slides[idx] if isinstance(slides[idx], dict) else {}
                            h, r = _designer_edit_slide(
                                slide_item.get('html', ''),
                                slide_item.get('title', f'شريحة {idx + 1}'),
                                instruction,
                                idx,
                                project_data,
                                presentation_id,
                                branding,
                                tenant_id=tenant_id,
                                creative_images=creative_images,
                                user_image_refs=user_image_refs,
                                slide_type=slide_item.get('type', 'content'),
                                total_slides=len(slides),
                                content_source=slide_item.get('content_source') or slide_item.get('contentSource'),
                                skip_vision=skip_vision,
                            )
                            return idx, h, r

                    max_workers = min(4, len(indexes))
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = [executor.submit(_edit_worker, idx) for idx in indexes]
                        completed_count = 0
                        total_slides_count = len(indexes)
                        for future in concurrent.futures.as_completed(futures):
                            completed_count += 1
                            try:
                                idx_res, updated_html_res, resp_text_res = future.result()
                                original_html_res = slides[idx_res].get('html', '')
                                if designer_chat_reliability.materially_changed(
                                        original_html_res, updated_html_res, resp_text_res):
                                    slides[idx_res]['html'] = updated_html_res
                                    slides[idx_res]['_designer_keep_html'] = True
                                    slides[idx_res]['is_custom'] = True
                                    changed_indexes.append(idx_res)
                                    extracted_caps = slide_engine._extract_visual_concept_captions(updated_html_res)
                                    if extracted_caps:
                                        slides[idx_res]['captions'] = extracted_caps
                                if resp_text_res:
                                    assistant_messages.append(resp_text_res)
                            except Exception as exc:
                                print(f"[PARALLEL EDIT ERROR] Slide edit failed: {exc}")
                            pct = int(15 + 75 * (completed_count / total_slides_count))
                            report_designer_progress(pct, f"تمت معالجة الشريحة {completed_count} من {total_slides_count}...")
                else:
                    for idx in indexes:
                        slide = slides[idx] if isinstance(slides[idx], dict) else {}
                        original_html = slide.get('html', '')
                        report_designer_progress(40, f"جاري تعديل الشريحة {idx + 1}...")
                        html, response_text = _designer_edit_slide(
                            original_html, slide.get('title', f'شريحة {idx + 1}'),
                            instruction, idx, project_data, presentation_id, branding,
                            tenant_id=tenant_id, creative_images=creative_images,
                            user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                            total_slides=len(slides),
                            content_source=slide.get('content_source') or slide.get('contentSource'),
                            progress_callback=lambda attempt, total: report_designer_progress(
                                min(78, 35 + attempt * 12),
                                f"جاري تنفيذ محاولة تعديل الشريحة {attempt} من {total}...",
                            ),
                        )
                        if designer_chat_reliability.materially_changed(original_html, html, response_text):
                            slide['html'] = html
                            slide['_designer_keep_html'] = True
                            slide['is_custom'] = True
                            changed_indexes.append(idx)
                            extracted_caps = slide_engine._extract_visual_concept_captions(html)
                            if extracted_caps:
                                slide['captions'] = extracted_caps
                            slides[idx] = slide
                        if response_text:
                            assistant_messages.append(response_text)
                        report_designer_progress(85, f"تم الانتهاء من معالجة الشريحة {idx + 1}...")
                executed.append({
                    'tool': tool,
                    'status': 'success' if len(changed_indexes) == len(indexes) and indexes else 'failed',
                    'reason': None if len(changed_indexes) == len(indexes) and indexes else 'incomplete_edit',
                    'indexes': sorted(changed_indexes),
                    'requested_indexes': indexes,
                })
            elif tool == 'insert_team_logo':
                raw_team_index = params.get('team_index') or params.get('teamIndex') or 0
                try:
                    team_index = int(raw_team_index)
                except (TypeError, ValueError):
                    team_index = 0
                team_members = creative_images.get('team_members') if isinstance(creative_images, dict) else []
                team_member = (
                    team_members[team_index - 1]
                    if isinstance(team_members, list) and 0 < team_index <= len(team_members)
                    and isinstance(team_members[team_index - 1], dict)
                    else None
                )
                if not team_member or not team_member.get('logo'):
                    assistant_messages.append('لا يوجد شعار مرفوع للجهة المحددة في فريق العمل؛ لم يتم إنشاء شعار بديل.')
                    executed.append({'tool': tool, 'status': 'failed', 'reason': 'team_logo_missing'})
                    continue
                indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                team_name = str(team_member.get('name') or f'الجهة {team_index}').strip()
                team_token = f'##TEAM_LOGO_{team_index}##'
                team_instruction = (
                    f"أدرج شعار جهة فريق العمل «{team_name}» داخل موضع محتوى مناسب ومرئي في هذه الشريحة، "
                    f"باستخدام الرمز {team_token} فقط؛ يجب أن يتحول الرمز إلى الشعار المرفوع فعلياً. "
                    "لا تستخدم ##LOGO## ولا ##PROJECT_LOGO## لهذا الطلب، ولا تضع شعار الجهة في هيدر شعار الشركة، "
                    "وحافظ على شعار الشركة الموجود وبقية محتوى الشريحة وتوازنها البصري."
                )
                successful_indexes = []
                for i, idx in enumerate(indexes):
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    updated_html, response_text = _designer_edit_slide(
                        slide.get('html', ''), slide.get('title', f'شريحة {idx + 1}'),
                        team_instruction, idx, project_data, presentation_id, branding,
                        tenant_id=tenant_id, creative_images=creative_images,
                        user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                        total_slides=len(slides),
                        content_source=slide.get('content_source') or slide.get('contentSource'),
                    )
                    updated_html = _inject_team_logo_fallback(
                        updated_html, str(team_member.get('logo') or ''), team_index
                    )
                    slide['html'] = updated_html
                    slide['_designer_keep_html'] = True
                    slide['is_custom'] = True
                    slides[idx] = slide
                    successful_indexes.append(idx)
                    if response_text:
                        assistant_messages.append(response_text)
                    pct = int(15 + 75 * ((i + 1) / max(1, len(indexes))))
                    report_designer_progress(pct, f"تم إدراج الشعار في الشريحة {i + 1} من {len(indexes)}...")
                executed.append({'tool': tool, 'status': 'success' if successful_indexes else 'failed',
                                 'indexes': successful_indexes, 'team_index': team_index,
                                 'token': team_token})
            elif tool == 'insert_company_logo_panel':
                indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                company_logo_url = str(
                    branding.get('logo_path') or branding.get('logo') or branding.get('logo_url') or '/assets/logo.png'
                ).strip()
                company_instruction = (
                    'انقل شعار الشركة المعتمد باستخدام الرمز ##LOGO## إلى داخل المربع الكحلي الموجود في يمين الشريحة، '
                    'واجعله فوق رقم سنوات الخبرة مباشرة داخل نفس المربع. لا تستخدم ##TEAM_LOGO_N## ولا شعار جهة من فريق العمل، '
                    'ولا تضع الشعار في أعلى يسار الشريحة. حافظ على الرقم 55 وبقية النصوص والتنسيق.'
                )
                successful_indexes = []
                for i, idx in enumerate(indexes):
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    updated_html, response_text = _designer_edit_slide(
                        slide.get('html', ''), slide.get('title', f'شريحة {idx + 1}'),
                        company_instruction, idx, project_data, presentation_id, branding,
                        tenant_id=tenant_id, creative_images=creative_images,
                        user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                        total_slides=len(slides),
                        content_source=slide.get('content_source') or slide.get('contentSource'),
                    )
                    updated_html = _inject_company_logo_panel_fallback(updated_html, company_logo_url)
                    slide['html'] = updated_html
                    slide['_designer_keep_html'] = True
                    slide['is_custom'] = True
                    slides[idx] = slide
                    successful_indexes.append(idx)
                    if response_text:
                        assistant_messages.append(response_text)
                    pct = int(15 + 75 * ((i + 1) / max(1, len(indexes))))
                    report_designer_progress(pct, f"تم وضع الشعار في الشريحة {i + 1} من {len(indexes)}...")
                executed.append({'tool': tool, 'status': 'success' if successful_indexes else 'failed',
                                 'indexes': successful_indexes, 'placement': 'right_panel_above_experience_years'})
            elif tool in ('generate_image', 'generate_design_image', 'insert_image_into_slide'):
                prompt = params.get('prompt') or message
                comp_name = params.get('component_name') or params.get('component') or ''
                if not comp_name and current_index < len(slides):
                    cur_title = slides[current_index].get('title', '')
                    comps = (project_data.get('interior_components') or project_data.get('components') or []) if isinstance(project_data, dict) else []
                    for c in comps:
                        c_title = (c.get('name') or c.get('title') or '') if isinstance(c, dict) else ''
                        if c_title and c_title in cur_title:
                            comp_name = c_title
                            break

                ref_images = _find_component_reference_image(comp_name or prompt or message, project_data, creative_images)
                designer_image_ctx = _usage_ctx('image', project_data, presentation_id=presentation_id, tenant_id=tenant_id)
                if ref_images:
                    image_raw = call_image_api_with_references(prompt, references=ref_images, usage_ctx=designer_image_ctx)
                else:
                    image_raw = call_image_api(prompt, usage_ctx=designer_image_ctx)

                image = persist_generated_image(image_raw, tenant_id)
                if not image:
                    raise RuntimeError('تعذر توليد الصورة. تحقق من إعداد OpenRouter ورصيده.')
                targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                position = params.get('position', 'surgical')
                for idx in targets:
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    orig_html = slide.get('html', '')
                    caption_text = comp_name or prompt[:60]
                    caption_markup = f'<div data-visual-media-caption="1" style="font-size:12px;color:#c5a059;margin-top:6px;font-weight:600;text-align:center;">{caption_text}</div>'
                    if position in ('surgical', 'inline') or not position:
                        instruction_img = (
                            f"أدرج الصورة الجديدة ({image}) في تصميم الشريحة كعنصر مرئي رئيسي متناسق وجميل مع بطاقة شرح توضيحي ({caption_markup}). "
                            f"حافظ على جميع النصوص والبطاقات واضبط مكان الصورة باحترافية وتوازن بدون أي إيموجي أو أيقونات."
                        )
                        updated_html, r_msg = _designer_edit_slide(
                            orig_html, slide.get('title', f'شريحة {idx + 1}'),
                            instruction_img, idx, project_data, presentation_id, branding,
                            tenant_id=tenant_id, creative_images=creative_images,
                            user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                            total_slides=len(slides),
                            content_source=slide.get('content_source') or slide.get('contentSource'),
                        )
                        slide['html'] = updated_html
                        slide['_designer_keep_html'] = True
                        if r_msg:
                            assistant_messages.append(r_msg)
                    elif position == 'background':
                        tag = f'<div aria-hidden="true" style="position:absolute;inset:0;background-image:url(\'{image}\');background-size:cover;background-position:center;z-index:0;"></div>'
                        slide['html'] = re.sub(r'(</div>\s*)$', tag + r'\1', orig_html or '', count=1)
                        slide['_designer_keep_html'] = True
                    else:
                        side = 'right:40px' if position != 'left' else 'left:40px'
                        tag = f'<div style="position:absolute;{side};top:120px;width:38%;z-index:2;"><img src="{image}" alt="" style="width:100%;max-height:460px;object-fit:cover;border-radius:8px;">{caption_markup}</div>'
                        slide['html'] = re.sub(r'(</div>\s*)$', tag + r'\1', orig_html or '', count=1)
                        slide['_designer_keep_html'] = True
                    slides[idx] = slide
                creative_images.setdefault('generated', []).append(image)
                executed.append({'tool': tool, 'status': 'success', 'indexes': targets, 'image': image})
            elif tool in ('insert_canonical_map', 'insert_map'):
                map_type = str(params.get('map_type') or 'overview').lower()
                refresh_requested = params.get('refresh') is True or params.get('use_latest') is True
                token_map = {
                    'overview': ('##MAP_OVERVIEW##', 'خريطة الموقع العام ونظرة جوية للأرض'),
                    'access': ('##MAP_ACCESS##', 'خريطة شبكة الطرق والمحاور الرئيسية للوصول'),
                    'catchment': ('##MAP_CATCHMENT##', 'خريطة النطاق الجغرافي واستيعاب المنطقة'),
                    'landmarks': ('##MAP_LANDMARKS##', 'خريطة المعالم الحيوية والخدمات وأوقات القيادة'),
                }
                token, label = token_map.get(map_type, ('##MAP_OVERVIEW##', 'خريطة الموقع العام'))
                targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                map_url = (_latest_canonical_map_url(
                    map_type, project_data, creative_images,
                    tenant_id=tenant_id, presentation_id=presentation_id,
                    preferred_images=[request_creative_images, project_creative_images],
                ) if refresh_requested else _approved_canonical_map_url(map_type, project_data, creative_images))
                if not map_url:
                    missing_text = (
                        f'لا توجد نسخة محفوظة حديثة من خريطة {label} لتحديثها.'
                        if refresh_requested else
                        f'لا توجد نسخة معتمدة محفوظة من خريطة {label} لإعادة إدراجها؛ لم يتم طلب خريطة جديدة من جوجل.'
                    )
                    assistant_messages.append(missing_text)
                    executed.append({'tool': tool, 'status': 'failed', 'indexes': targets,
                                     'map_type': map_type, 'reason': 'approved_map_missing'})
                    continue
                # Saved slides freeze map sources into revision URLs that no
                # longer look like map paths, so the existing slot is found by
                # the canonical attribute and persisted-file marks, not by URL.
                map_marks = _persisted_map_source_marks(
                    tenant_id, presentation_id=presentation_id,
                    draft_id=None if presentation_id else (
                        project_data.get('draftId') or project_data.get('draft_id')
                        if isinstance(project_data, dict) else None))
                successful_targets = []
                for idx in targets:
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    updated_html, replaced = _replace_slide_with_approved_map(
                        slide.get('html', ''), map_type, map_url, map_marks=map_marks
                    )
                    if not replaced:
                        assistant_messages.append(f'تعذر العثور على موضع خريطة {label} في الشريحة رقم {idx + 1}؛ لم يتم تغيير الشريحة.')
                        continue
                    updated_html = resolve_designer_chat_placeholders(
                        updated_html, project_data, presentation_id, tenant_id, creative_images
                    )
                    # A chat map refresh is a source swap, not a slide regeneration.
                    # Keep the existing HTML/layout and carry the exact marked image
                    # from the project section into the existing map slot.
                    slide['html'] = updated_html
                    slides[idx] = slide
                    successful_targets.append(idx)
                if successful_targets:
                    assistant_messages.append(
                        f"تم تحديث خريطة {label} في الشرائح المحددة من أحدث نسخة محفوظة دون توليد نسخة من جوجل."
                        if refresh_requested else
                        f'تمت إعادة إدراج خريطة {label} المعتمدة في الشرائح المحددة دون توليد نسخة من جوجل.'
                    )
                executed.append({'tool': tool, 'status': 'success' if successful_targets else 'failed',
                                 'indexes': successful_targets, 'map_type': map_type,
                                 'source': 'latest_persisted_map' if refresh_requested else 'approved_persisted_map'})
            elif tool == 'update_slide_image':
                # Deterministic project-asset swap: the planner names an exact
                # token from the enumerated asset list, the URL resolves from
                # the current creative state, and the slide's image slot is
                # rewritten in place without a model rebuild.
                raw_asset = str(params.get('asset') or params.get('token')
                                or params.get('placeholder') or params.get('image_token') or '').strip()
                asset_url, asset = _designer_image_asset_url(raw_asset, designer_image_assets)
                targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                if not asset_url:
                    assistant_messages.append(
                        f'لا توجد صورة مشروع بالرمز {raw_asset or "المطلوب"} ضمن الأصول المتاحة؛ لم يتغير العرض.')
                    executed.append({'tool': tool, 'status': 'failed', 'indexes': targets,
                                     'asset': raw_asset, 'reason': 'asset_missing'})
                    continue
                raw_index = params.get('image_index', params.get('imageIndex'))
                try:
                    image_index = int(raw_index) if raw_index not in (None, '') else None
                except (TypeError, ValueError):
                    image_index = None
                asset_label = str(asset.get('label') or raw_asset).strip() if isinstance(asset, dict) else raw_asset
                successful_targets = []
                for idx in targets:
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    updated_html, replaced = _replace_slide_image_with_asset(
                        slide.get('html', ''), asset_url,
                        asset_token=asset['token'], image_index=image_index)
                    if not replaced:
                        assistant_messages.append(
                            f'تعذر العثور على موضع صورة في الشريحة رقم {idx + 1}؛ لم يتم تغيير الشريحة.')
                        continue
                    updated_html = resolve_designer_chat_placeholders(
                        updated_html, project_data, presentation_id, tenant_id, creative_images)
                    slide['html'] = updated_html
                    slides[idx] = slide
                    successful_targets.append(idx)
                if successful_targets:
                    assistant_messages.append(
                        f'تم تحديث الصورة في الشرائح المحددة إلى «{asset_label}» من أصول المشروع دون إعادة تصميم.')
                executed.append({'tool': tool, 'status': 'success' if successful_targets else 'failed',
                                 'indexes': successful_targets, 'asset': asset['token'],
                                 'source': 'project_asset'})
            elif tool in ('insert_financial_chart', 'update_financial_chart'):
                chart_type = str(params.get('chart_type') or 'waterfall').lower()
                targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                chart_desc = {
                    'waterfall': 'مخطط شلال التدفقات النقدية والأرباح الصافية',
                    'sensitivity': 'مخطط تحليل الحساسية للإيرادات ونسب الإشغال',
                    'compound_flows': 'مخطط التدفقات التراكمية وصافي القيمة الحالية (NPV)',
                    'financing_structure': 'مخطط توزيع هيكل التمويل والنفقات الرأسمالية والتشغيلية',
                }.get(chart_type, 'مخطط التحليل المالي والاستثماري')
                instruction_chart = (
                    f"أدرج رسم بياني مالي احترافي متناسق يوضح «{chart_desc}» معتمد على الأرقام والمؤشرات المالية للمشروع. "
                    f"حافظ على ألوان الهوية الرسمية (الكحلي الملكي والذهبي الاستثماري) والتباين العالي وخلو الشريحة من أي إيموجي أو أيقونات."
                )
                for idx in targets:
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    orig_html = slide.get('html', '')
                    updated_html, r_msg = _designer_edit_slide(
                        orig_html, slide.get('title', f'شريحة {idx + 1}'),
                        instruction_chart, idx, project_data, presentation_id, branding,
                        tenant_id=tenant_id, creative_images=creative_images,
                        user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                        total_slides=len(slides),
                        content_source=slide.get('content_source') or slide.get('contentSource'),
                    )
                    slide['html'] = updated_html
                    slide['_designer_keep_html'] = True
                    slides[idx] = slide
                    if r_msg:
                        assistant_messages.append(r_msg)
                executed.append({'tool': tool, 'status': 'success', 'indexes': targets, 'chart_type': chart_type})
            elif tool in ('delete_slide', 'remove_slide'):
                raw_nums = params.get('slide_numbers') or params.get('slide_number') or params.get('slide_index') or params.get('index')
                if not isinstance(raw_nums, list):
                    raw_nums = [raw_nums]
                target_nums = [designer_chat_targets.slide_number(value, len(slides)) for value in raw_nums]
                del_indexes = sorted(set(n - 1 for n in target_nums), reverse=True)
                if len(slides) - len(del_indexes) >= 1:
                    removed_titles = []
                    for d_idx in del_indexes:
                        removed = slides.pop(d_idx)
                        removed_titles.append(f'«{removed.get("title", f"شريحة {d_idx + 1}")}»')
                    assistant_messages.append(f'تم حذف {len(del_indexes)} شريحة بنجاح ({", ".join(removed_titles)}).')
                    executed.append({'tool': tool, 'status': 'success', 'deleted_indexes': del_indexes})
                else:
                    assistant_messages.append('لا يمكن حذف جميع الشرائح المتبقية في العرض.')
                    executed.append({'tool': tool, 'status': 'rejected', 'reason': 'single_slide'})
            elif tool in ('duplicate_slide', 'clone_slide'):
                raw_num = params.get('slide_number') or params.get('slide_index') or params.get('index')
                target_num = designer_chat_targets.slide_number(raw_num, len(slides))
                dup_idx = target_num - 1
                cloned = copy.deepcopy(slides[dup_idx])
                cur_title = cloned.get('title', '')
                cloned['title'] = cur_title + ' (نسخة)' if not cur_title.endswith('(نسخة)') else cur_title
                slides.insert(dup_idx + 1, cloned)
                assistant_messages.append(f'تم تكرار الشريحة رقم {target_num} بنجاح.')
                executed.append({'tool': tool, 'status': 'success', 'duplicated_index': dup_idx + 1})
            elif tool in ('reorder_slides', 'move_slide'):
                from_num = params.get('from_index') or params.get('from')
                to_num = params.get('to_index') or params.get('to')
                f_idx = designer_chat_targets.slide_number(from_num, len(slides)) - 1
                t_idx = designer_chat_targets.slide_number(to_num, len(slides)) - 1
                if f_idx == t_idx:
                    raise designer_chat_targets.TargetError('موضعا النقل متطابقان؛ لم يتغير العرض.')
                moved = slides.pop(f_idx)
                slides.insert(t_idx, moved)
                assistant_messages.append(f'تم نقل الشريحة من الترتيب {f_idx + 1} إلى الترتيب {t_idx + 1} بنجاح.')
                executed.append({'tool': tool, 'status': 'success', 'from_index': f_idx, 'to_index': t_idx})
            elif tool in ('split_slide', 'split_dense_slide', 'merge_slides', 'combine_slides',
                          'create_slide', 'create_design_slide'):
                import designer_chat_safety

                def render_structure_slide(html, title, instruction, index, kind, total, source):
                    return _designer_edit_slide(
                        html, title, instruction, index, project_data, presentation_id, branding,
                        tenant_id=tenant_id, creative_images=creative_images,
                        user_image_refs=user_image_refs, slide_type=kind, total_slides=total,
                        content_source=source,
                    )

                structural_result, structural_message = designer_chat_safety.execute_structure(
                    tool, params, slides, message, edit_slide=render_structure_slide,
                    reliability=designer_chat_reliability, carry_watermark=_carry_slide_watermark,
                    progress=report_designer_progress,
                )
                executed.append(structural_result)
                assistant_messages.append(structural_message)
            elif tool in ('regenerate_maps', 'update_map_style', 'change_map_type'):
                maptype = params.get('maptype') or params.get('style') or 'roadmap'
                executed.append({'tool': tool, 'status': 'deferred', 'maptype': maptype})
                assistant_messages.append('لم تتغير خرائط الموقع المعتمدة؛ توليد الخرائط منفصل لكل خريطة.')
            else:
                executed.append({'tool': tool, 'status': 'skipped', 'message': 'أداة غير معروفة'})

        failed_actions = [item for item in executed if item.get('status') in ('failed', 'rejected', 'deferred', 'skipped', 'noop')]
        structural_failure = any(item.get('tool') in designer_chat_targets.STRUCTURAL_TOOLS for item in failed_actions)
        partial_batch_failure = any(
            item.get('tool') in designer_chat_targets.EDIT_TOOLS
            and len(item.get('requested_indexes') or []) > 1
            and len(item.get('indexes') or []) != len(item.get('requested_indexes') or [])
            for item in failed_actions
        )
        if failed_actions and (structural_failure or partial_batch_failure or len(actions) > 1):
            return jsonify({'success': False, 'error': 'لم يُطبق الطلب لأن إحدى عملياته لم تنجح. ' + ' '.join(dict.fromkeys(assistant_messages)),
                            'error_code': 'DESIGNER_ATOMIC_EDIT_FAILED', 'actions': executed, 'slidesData': slides_before}), 422
        structural_change = any(item.get('tool') in designer_chat_targets.STRUCTURAL_TOOLS
                                and item.get('status') == 'success' for item in executed)
        structural_change = structural_change or any(
            isinstance(item, dict) and item.get('tool') == 'insert_attached_image'
            and item.get('status') == 'success' and item.get('position') == 'separate_slide'
            for item in executed)
        if structural_change:
            slides = slide_engine.renumber_presentation_slides(
                slides, branding=branding, project_data=project_data, tenant_id=tenant_id,
                allow_all_maps=True, creative_images=creative_images, preserve_html=True,
            )
        validation = _validate_workspace_data({'slidesData': slides})
        if not validation['valid']:
            return jsonify({'success': False, 'error': 'تم رفض التعديل لأن العرض يحتوي على شرائح غير صالحة', 'validation': validation}), 422
        slide_changes = change_tracking.describe_slide_changes(slides_before, slides)
        touched = [item.get('index') + 1 for item in executed
                   if isinstance(item, dict) and isinstance(item.get('index'), int)]
        touched += [n + 1 for item in executed if isinstance(item, dict)
                    for n in (item.get('indexes') or []) if isinstance(n, int)]
        touched += [int(item.get('inserted_at')) for item in executed
                    if isinstance(item, dict) and isinstance(item.get('inserted_at'), int)]
        turn_focus = sorted(dict.fromkeys(touched)) or focus_indexes
        successful_execution = any(
            isinstance(item, dict) and item.get('status') == 'success'
            for item in executed
        )
        failure_reason = None
        if successful_execution:
            response_text = 'تم تطبيق التعديل المطلوب.'
            if assistant_messages:
                response_text += ' ' + ' '.join(dict.fromkeys(assistant_messages))
        else:
            failure_reason = next((
                item.get('reason') for item in executed
                if isinstance(item, dict) and item.get('reason')
            ), 'no_verified_change')
            detail = ' '.join(dict.fromkeys(assistant_messages)).strip()
            response_text = 'لم يتم تنفيذ أي تعديل على العرض.' + (f' {detail}' if detail else '')
        # Return the updated conversation beside the edited workspace. The browser keeps both in
        # memory until the user explicitly presses save; writing here would make a failed edit
        # impossible to discard with a refresh.
        persisted_messages = _normalize_designer_chat_messages(history_for_turn)[-DESIGNER_CHAT_STORED_TURNS * 2:]
        if not persisted_messages or persisted_messages[-1].get('content') != message or persisted_messages[-1].get('role') != 'user':
            persisted_messages.append({'role': 'user', 'content': message[:2000], 'slides': preferred_indexes[:]})
        persisted_messages.append({'role': 'assistant', 'content': response_text[:2000], 'slides': preferred_indexes[:]})
        persisted_project_data = dict(project_data)
        persisted_project_data['tenantSlidesData'] = slides
        persisted_project_data['designerChat'] = {
            'messages': persisted_messages[-DESIGNER_CHAT_STORED_TURNS * 2:],
            'memory': chat_memory,
            'focusIndexes': turn_focus or preferred_indexes,
        }
        # The slides this turn actually touched become the conversation's focus, so the next
        # message («وطلعها أوضح») lands on them without asking again.
        # Both keys carry 0-based indexes; the chat speaks in 1-based slide numbers.
        persisted_project_data['designerChat']['focusIndexes'] = turn_focus
        # ``creative_images`` is the generation view and intentionally aliases
        # editable placeholders to the marked canonical image. Do not send that
        # alias back to the browser: the location editor needs the persisted
        # clean sidecar so its HTML labels are not drawn over raster labels.
        response_creative_images = copy.deepcopy(creative_images)
        source_creative_images = request_creative_images or project_creative_images
        if isinstance(source_creative_images, dict) and isinstance(source_creative_images.get('map_placeholders'), dict):
            returned_placeholders = response_creative_images.get('map_placeholders')
            returned_placeholders = dict(returned_placeholders) if isinstance(returned_placeholders, dict) else {}
            returned_placeholders.update(source_creative_images['map_placeholders'])
            response_creative_images['map_placeholders'] = returned_placeholders
        response_data = {
            'action': 'workspace_update', 'response': response_text,
            'slidesData': slides, 'creativeImages': response_creative_images,
            'actions': executed, 'validation': validation,
            'memory': chat_memory, 'focusIndexes': turn_focus,
            'chatHistory': persisted_project_data['designerChat']['messages'],
            'saved': False,
        }
        if successful_execution and slide_changes:
            response_data['changeSource'] = 'ai'
            response_data['provenance'] = _issue_presentation_provenance(
                slides, presentation_id, int((presentation or {}).get('revision') or 0),
                [f'طلب التصميم: {message[:2000]}'] + [
                    f'أداة التصميم: {item.get("tool")}' for item in executed
                    if isinstance(item, dict) and item.get('status') == 'success'
                ],
            )
        if failure_reason:
            response_data['failureReason'] = failure_reason
        return jsonify({'success': True, 'data': response_data})
    except designer_chat_targets.TargetError as exc:
        return jsonify({'success': False, 'error': str(exc), 'error_code': 'DESIGNER_INVALID_TARGET'}), 422
    except Exception as exc:
        print(f'[DESIGNER-CHAT ERROR] {exc}')
        return jsonify({'success': False, 'error': str(exc)}), 500


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
