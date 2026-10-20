PLANS_CONFLICT_CHAT_SYSTEM_PROMPT = (
    'أنت مساعد توضيحي لقسم المخططات داخل منصة «لاندلوم» (Landloom).\n'
    'مهمتك شرح نتائج الفحص والتوزيع المقترح المرفقين للمستخدم: ما التعارض، أين يقع (اسم القسم '
    'والحقل)، لماذا سُجّل، وما التعديل المطلوب بالقيم عند توفرها — وإن لم تُسجَّل تعارضات '
    'فأجب عن التوزيع المرفق نفسه ومكوناته وأرقامه.\n'
    'قواعد إلزامية:\n'
    '- أجب بلغة سؤال المستخدم نفسها، والرد الافتراضي قصير ومباشر: الإجابة أولاً ثم السبب في سطر أو سطرين.\n'
    '- استند حصريًا إلى نتائج الفحص والتوزيع والبيانات المرفقة؛ لا تستنتج قيمة غير موجودة ولا تخمّن، '
    'وإن نقصت المعلومات صرّح بذلك بدل التخمين.\n'
    '- عند اقتراح تعديل اذكر القسم والحقل والقيمة الحالية والقيمة المقترحة، '
    'وسمِّ دائمًا القيمة الموثقة مقابل قيمة المشروع.\n'
    '- كل اقتراح إرشاد يقرره العميل ويطبقه بنفسه — ممنوع الادعاء بأنك عدّلت شيئًا أو أنك تستطيع.\n'
    '- لا تذكر أسماء ملفات أو أرقام صفحات أو مصادر داخلية؛ استخدم «البيانات التنظيمية الموثقة» '
    'أو «نتائج الفحص».\n'
    '- هذا النقاش مخصص لنتائج الفحص والتوزيع المرفقين فقط؛ إن سُئلت عن شيء خارجها فوضّح ذلك باختصار.\n'
    '- ذاكرة المحادثة إلزامية: لا تخالف ما اتُّفق عليه سابقًا ولا تعِد اقتراحًا رُفض، '
    'وإذا غيّر العميل قرارًا سابقًا فاذكر التغيير صراحة.\n'
    '- ممنوع تنسيق Markdown تمامًا (لا ** ولا ### ولا جداول) — نص عادي ونقاط قصيرة فقط.\n'
)


def _plans_conflict_chat_history(raw):
    """The conversation as it travelled — the whole thing, not the last eight turns."""
    return chat_memory.normalize_turns(raw)


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
    rows = distribution.get('rows') if isinstance(distribution.get('rows'), list) else []
    totals = distribution.get('totals') if isinstance(distribution.get('totals'), list) else []
    # The chat discusses whatever the stage already produced: verify needs its
    # findings (or a run verification), distribution only needs the proposed
    # table — a clean check with zero conflicts must still be discussable.
    if scope == 'verify':
        has_material = bool(checks or issues
                            or _visual_concept_text(verification.get('summary'))
                            or verification.get('approved'))
    else:
        has_material = bool(checks or issues or rows or totals)
    if not has_material:
        message = ('لا يوجد توزيع مقترح لمناقشته بعد' if scope == 'distribution'
                   else 'لا توجد نتائج فحص لمناقشتها بعد')
        return jsonify({'success': False, 'error': message,
                        'error_code': 'CONFLICT_CHAT_EMPTY'}), 400
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    context = _visual_concept_plan_context(project_data)
    findings = {'checks': checks[:40], 'issues': issues[:30]}
    if rows or totals:
        findings['distribution_rows'] = rows
        findings['distribution_totals'] = totals
    if scope == 'distribution' and not (checks or issues):
        findings['check_state'] = ('الفحص اكتمل دون تسجيل تعارضات' if distribution.get('aiReviewed')
                                   else 'لم يُجرَّ فحص للتوزيع بعد')
    distribution_notes = _visual_concept_text(workflow.get('distributionNotes'), 1000000)
    if distribution_notes:
        findings['client_distribution_notes'] = distribution_notes
    if scope == 'verify':
        summary = _visual_concept_text(verification.get('summary'), 1600)
        if summary:
            findings['summary'] = summary
    prior = ''
    history = _plans_conflict_chat_history(data.get('history'))
    memory = data.get('memory') if isinstance(data.get('memory'), str) else ''
    conversation = chat_memory.build_context(history, memory=memory)
    prior = chat_memory.prompt_block(conversation)
    if prior:
        prior = prior + '\n\n'
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
                model=GEMINI_TEXT_MODEL,
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
    return jsonify({'success': True, 'reply': reply,
                    'memory': conversation['memory'],
                    'decisions': conversation['decisions']})
