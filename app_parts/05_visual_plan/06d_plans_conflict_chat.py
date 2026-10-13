PLANS_CONFLICT_CHAT_SYSTEM_PROMPT = (
    'أنت مساعد توضيحي لنتائج فحص التعارضات في قسم المخططات داخل منصة «لاندلوم» (Landloom).\n'
    'مهمتك الوحيدة شرح نتيجة الفحص للمستخدم: ما التعارض، أين يقع (اسم القسم والحقل)، لماذا سُجّل، '
    'وما التعديل المطلوب بالقيم عند توفرها.\n'
    'قواعد إلزامية:\n'
    '- أجب بلغة سؤال المستخدم نفسها، والرد الافتراضي قصير ومباشر: الإجابة أولاً ثم السبب في سطر أو سطرين.\n'
    '- استند حصريًا إلى نتائج الفحص والبيانات المرفقة؛ لا تستنتج قيمة غير موجودة ولا تخمّن، '
    'وإن نقصت المعلومات صرّح بذلك بدل التخمين.\n'
    '- عند اقتراح تعديل اذكر القسم والحقل والقيمة الحالية والقيمة المقترحة، '
    'وسمِّ دائمًا القيمة الموثقة مقابل قيمة المشروع.\n'
    '- كل اقتراح إرشاد يقرره العميل ويطبقه بنفسه — ممنوع الادعاء بأنك عدّلت شيئًا أو أنك تستطيع.\n'
    '- لا تذكر أسماء ملفات أو أرقام صفحات أو مصادر داخلية؛ استخدم «البيانات التنظيمية الموثقة» '
    'أو «نتائج الفحص».\n'
    '- هذا النقاش مخصص لنتائج الفحص المرفقة فقط؛ إن سُئلت عن شيء خارجها فوضّح ذلك باختصار.\n'
    '- ممنوع تنسيق Markdown تمامًا (لا ** ولا ### ولا جداول) — نص عادي ونقاط قصيرة فقط.\n'
)


def _plans_conflict_chat_history(raw):
    history = []
    for item in (raw if isinstance(raw, list) else [])[-8:]:
        if not isinstance(item, dict):
            continue
        content = _visual_concept_text(item.get('content'), 2000)
        if content:
            history.append({'role': 'user' if item.get('role') == 'user' else 'assistant',
                            'content': content})
    return history


@app.route('/api/visual-concept/plans-conflict-chat', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plans_conflict_chat():
    data = request.get_json(silent=True) or {}
    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard
    question = _visual_concept_text(data.get('question'), 2000)
    if not question:
        return jsonify({'success': False, 'error': 'اكتب السؤال أولاً',
                        'error_code': 'MESSAGE_REQUIRED'}), 400
    scope = 'distribution' if _visual_concept_text(data.get('scope'), 20) == 'distribution' else 'verify'
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    verification = workflow.get('verification') if isinstance(workflow.get('verification'), dict) else {}
    distribution = workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {}
    source = distribution if scope == 'distribution' else verification
    checks = source.get('checks') if isinstance(source.get('checks'), list) else []
    issues = source.get('issues') if isinstance(source.get('issues'), list) else []
    if not checks and not issues:
        return jsonify({'success': False, 'error': 'لا توجد نتائج فحص لمناقشتها بعد',
                        'error_code': 'CONFLICT_CHAT_EMPTY'}), 400
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    context = _visual_concept_plan_context(project_data)
    findings = {'checks': checks[:40], 'issues': issues[:30]}
    rows = distribution.get('rows') if isinstance(distribution.get('rows'), list) else []
    totals = distribution.get('totals') if isinstance(distribution.get('totals'), list) else []
    if rows or totals:
        findings['distribution_rows'] = rows
        findings['distribution_totals'] = totals
    distribution_notes = _visual_concept_text(workflow.get('distributionNotes'), 2000)
    if distribution_notes:
        findings['client_distribution_notes'] = distribution_notes
    if scope == 'verify':
        summary = _visual_concept_text(verification.get('summary'), 1600)
        if summary:
            findings['summary'] = summary
    prior = ''
    history = _plans_conflict_chat_history(data.get('history'))
    if history:
        prior = 'سياق النقاش السابق:\n' + '\n'.join(
            ('المستخدم: ' if turn['role'] == 'user' else 'المساعد: ') + turn['content']
            for turn in history) + '\n\n'
    scope_label = ('نتائج فحص توزيع المكونات على الأدوار' if scope == 'distribution'
                   else 'نتائج التحقق من التضارب')
    user_content = (
        scope_label + ':\n' +
        json.dumps(findings, ensure_ascii=False, default=str) +
        '\n\nبيانات المشروع والبيانات التنظيمية الموثقة:\n' +
        json.dumps(_visual_concept_plan_regulation_input(project_data, context),
                   ensure_ascii=False, default=str) +
        '\n\n' + prior + 'سؤال المستخدم: ' + question
    )
    try:
        # Thinking models count reasoning tokens toward max_tokens, so a short
        # cap can still cut the visible answer mid-sentence — retry once with
        # headroom on finish_reason=length (same pattern as land analysis).
        cap = 6000
        response = None
        for attempt in range(2):
            response = call_text_chat(
                PLANS_CONFLICT_CHAT_SYSTEM_PROMPT, user_content, max_tokens=cap,
                model=SLIDE_TEXT_MODEL,
                usage_ctx=_usage_ctx_optional('ai_text', data))
            choices = response.get('choices') if isinstance(response, dict) else None
            first = choices[0] if choices and isinstance(choices[0], dict) else {}
            finish = first.get('finish_reason') or first.get('native_finish_reason')
            if finish != 'length' or attempt == 1:
                break
            app.logger.warning('Plans conflict chat truncated at cap=%s; retrying', cap)
            cap = 12000
        reply = _land_chat_clean_reply(
            extract_chat_content(response, 'PLANS-CONFLICT-CHAT'))
    except Exception as exc:
        app.logger.exception('Plans conflict chat failed')
        fatal = _ai_fatal_http_response(exc)
        if fatal is not None:
            return fatal
        return jsonify({'success': False, 'error': 'تعذر الحصول على إجابة',
                        'error_code': 'TEXT_PROVIDER_FAILED'}), 503
    return jsonify({'success': True, 'reply': reply})
