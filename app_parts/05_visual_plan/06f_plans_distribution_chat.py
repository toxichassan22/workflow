import chat_memory

PLANS_DISTRIBUTION_CHAT_SYSTEM_PROMPT = (
    'أنت مهندس معماري مسؤول عن توزيع مكونات المشروع على المباني والأدوار داخل منصة «لاندلوم» (Landloom). '
    'أنت الطرف الوحيد الذي يقترح التوزيع ويشرحه ويعدّله بناءً على كلام العميل — ولا يوجد محرك هندسي '
    'يحسب أو يرفض بدلًا منك: كل الاستنتاج الهندسي مسؤوليتك.\n'
    'قواعد إلزامية:\n'
    '- ابدأ من الجدول الحالي المرفق إن وُجد: هو مصدر الحقيقة الوحيد للأرقام. لا تعِد توزيعًا من الصفر '
    'إلا إذا كان الجدول فارغًا أو طلب العميل ذلك صراحة.\n'
    '- أي تعديل ينطبق على الجدول المرفق: عدّل الصفوف المطلوبة فقط واترك الباقي كما هو، ثم أعد الجدول كاملًا '
    'بعد التعديل.\n'
    '- لا تخترع مكوّنًا غير موجود في بيانات المشروع المعتمدة، ولا تسقط مكوّنًا معتمدًا إلا بطلب صريح من '
    'العميل — وأذكر المكوّن المسقط في removedComponents.\n'
    '- الصيغ ملزمة: floor_range بالعربية فقط ("أرضي"، "ميزانين"، "بدروم 1"، "بدروم 1-3"، "1-4"، "ملحق علوي"، '
    '"مساحة مفتوحة")، وcomponent هو اسم المكوّن كما ورد في بيانات المشروع حرفيًا بلا ترجمة، '
    'وbuilding هو المبنى أو المجمع الذي يقع فيه الصف.\n'
    '- التزم بسقوف الارتفاع ونسبة التغطية والارتدادات وبرنامج الوحدات والمساحات المعتمد، '
    'وراعِ العلاقات بين الاستخدامات (فصل مداخل الفندق عن السكن، الخدمات أسفلًا أو على السطح).\n'
    '- لكل مكوّن نوعه «مساحة مفتوحة» (لاندسكيب، ممرات مشاة، مواقف سطحية) يُسجَّل بصيغة "مساحة مفتوحة" '
    'لا "أرضي" ولا نطاق أدوار.\n'
    '- احكم على كل بند فحص آلي مرقّم: «متعارض» لمخالفة حقيقية تمنع الاعتماد، «يحتاج تأكيد» تستدعي مراجعة '
    'العميل دون منع، «مطابق» إنذار كاذب لأن التوزيع سليم فعلًا. البند الذي لا تحكم عليه يبقى على حكمه الآلي.\n'
    '- ذاكرة المحادثة إلزامية: لا تخالف ما اتُّفق عليه سابقًا ولا تعِد اقتراحًا رُفض، وإذا غيّر العميل قرارًا '
    'سابقًا فاذكر التغيير صراحة في الرد.\n'
    '- لا تذكر أسماء ملفات أو أرقام صفحات أو مصادر داخلية؛ استخدم «البيانات التنظيمية الموثقة».\n'
    '- ممنوع تنسيق Markdown تمامًا (لا ** ولا ### ولا جداول) — نص عادي ونقاط قصيرة فقط.\n'
    'أعد JSON فقط: {"reply":"","action":"explain|update","rows":[],"removedComponents":[],'
    '"reviews":[{"index":0,"result":"متعارض|يحتاج تأكيد|مطابق","detail":"","fixable":true}],'
    '"issues":[{"title":"","points":[""],"suggestion":"","action":"","severity":"high"}],'
    '"memory":"","decisions":[]}'
)


def _plans_distribution_chat_component_keys(rows):
    keys = set()
    for row in (rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        name = _visual_concept_plan_sanitize_text(row.get('component') or row.get('use'))
        if not name:
            continue
        base = _visual_concept_plan_component_base(name)
        key = _visual_concept_plan_component_key(base) or _visual_concept_plan_component_key(name)
        keys.add(key or name)
    return keys


def _plans_distribution_chat_dropped_components(current_rows, new_rows, removed):
    """The components that vanished from the table without the client asking.

    A model that quietly drops an approved component is a broken proposal, so
    the update is refused instead of shipped.
    """
    before = _plans_distribution_chat_component_keys(current_rows)
    after = _plans_distribution_chat_component_keys(new_rows)
    dropped = before - after
    if not dropped:
        return []
    allowed = set()
    for item in (removed if isinstance(removed, list) else []):
        name = _visual_concept_plan_sanitize_text(item)
        if not name:
            continue
        base = _visual_concept_plan_component_base(name)
        allowed.add(_visual_concept_plan_component_key(base)
                    or _visual_concept_plan_component_key(name) or name)
    return sorted(dropped - allowed)


def _plans_distribution_chat_state(data, workflow):
    """The stored chat state: turns, memory and the agreed points."""
    stored = workflow.get('distributionChat') if isinstance(workflow.get('distributionChat'), dict) else {}
    turns = data.get('history') if isinstance(data.get('history'), list) else stored.get('turns')
    memory = data.get('memory') if isinstance(data.get('memory'), str) else stored.get('memory')
    decisions = data.get('decisions') if isinstance(data.get('decisions'), list) else stored.get('decisions')
    return {
        'turns': chat_memory.normalize_turns(turns),
        'memory': str(memory or ''),
        'decisions': chat_memory.normalize_decisions(decisions),
    }


@app.route('/api/visual-concept/plans-distribution-chat', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plans_distribution_chat():
    """One conversation owns the floor distribution: propose, explain, edit, check.

    The chat replaces the separate proposal / notes / revision / conflict-check
    controls. The table stays the single source of truth — it travels with the
    request and the answer carries the whole edited table back, so the client
    never has to merge a partial patch.
    """
    data = request.get_json(silent=True) or {}
    workflow_error = _visual_concept_plan_workflow_error(data, 'plan_site')
    if workflow_error:
        return jsonify(workflow_error), 400
    _billing_guard = _require_billing_balance('visual_concept')
    if _billing_guard is not None:
        return _billing_guard
    message = _visual_concept_text(data.get('message'), 4000)
    if not message:
        return jsonify({'success': False, 'error': 'اكتب طلبك أولاً',
                        'error_code': 'MESSAGE_REQUIRED'}), 400
    project_data, workflow, _boundary, _points, context = _visual_concept_plans_context_from_request(data)
    regulations = context.get('regulations') if isinstance(context.get('regulations'), dict) else {}
    posted = (data.get('distribution') if isinstance(data.get('distribution'), dict)
              else (workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {}))
    current = _visual_concept_plan_normalize_distribution(posted, context, regulations)
    current_rows = current['rows']
    state = _plans_distribution_chat_state(data, workflow)
    conversation = chat_memory.build_context(
        state['turns'], memory=state['memory'], decisions=state['decisions'])
    indexed_checks = [
        {'index': index, 'item': check.get('item'), 'detail': check.get('detail'),
         'result': check.get('result')}
        for index, check in enumerate(current['checks'])
    ]
    wishes = _visual_concept_text(workflow.get('distributionNotes'), 1000000)
    user_prompt = (
        'بيانات المشروع المعتمدة الوحيدة المسموح الاعتماد عليها:\n'
        + _visual_concept_plan_context_text(context, diagram_rules=False)
        + '\n\nالجدول الحالي للتوزيع (المصدر الوحيد للأرقام):\n'
        + json.dumps({'rows': current_rows, 'totals': current['totals']}, ensure_ascii=False)
        + '\n\nبنود الفحص الآلي المطلوب الحكم عليها كلها:\n'
        + json.dumps(indexed_checks, ensure_ascii=False)
        + ('\n\nملاحظات العميل على التوزيع — رغبات تُطبَّق ضمن حدود الاشتراطات والبيانات '
           'المعتمدة ولا تجاوزها:\n' + wishes if wishes else '')
        + '\n\n' + chat_memory.prompt_block(conversation)
        + '\n\nطلب العميل الحالي:\n' + message
    )
    try:
        response = call_openrouter_chat(
            PLANS_DISTRIBUTION_CHAT_SYSTEM_PROMPT, user_prompt, temperature=None, max_tokens=8000,
            model=VISUAL_PLAN_DISTRIBUTION_MODEL, reasoning_effort='max',
            response_format={'type': 'json_object'}, usage_ctx=_usage_ctx('image', data))
    except Exception:
        response = {}
    fatal = _ai_fatal_error_dict(response)
    if fatal is not None:
        fatal_response = _ai_fatal_http_response(response)
        if fatal_response is not None:
            return fatal_response
        return jsonify({'success': False, 'error': _client_safe_llm_error(fatal.get('message'))}), 503
    if isinstance(response, dict) and response.get('error'):
        return jsonify({'success': False, 'error': _client_safe_llm_error(_chat_error_message(response))}), 503
    parsed = parse_json_object(_get_chat_response_text(response))
    if not isinstance(parsed, dict):
        parsed = {}
    reply = _visual_concept_plan_sanitize_text(parsed.get('reply'))[:6000]
    action = 'update' if str(parsed.get('action') or '').lower() == 'update' else 'explain'
    rows = current_rows
    totals = current['totals']
    checks = current['checks']
    issues = current['issues']
    if action == 'update':
        candidate = parsed.get('rows') if isinstance(parsed.get('rows'), list) else []
        normalized = _visual_concept_plan_normalize_distribution(
            {'rows': candidate}, context, regulations, backfill=not current_rows)
        dropped = _plans_distribution_chat_dropped_components(
            current_rows, normalized['rows'], parsed.get('removedComponents'))
        if not normalized['rows']:
            action = 'explain'
            reply = (reply + '\n' if reply else '') + 'لم يُعد الجدول كاملًا — لم يتغير شيء.'
        elif dropped:
            action = 'explain'
            reply = ((reply + '\n') if reply else '') + (
                'لم يُطبَّق التعديل: المكوّنات ' + '، '.join(dropped)
                + ' موجودة في بيانات المشروع ولم يطلب العميل حذفها — الجدول كما هو.')
        else:
            rows = normalized['rows']
            totals = normalized['totals']
            checks = normalized['checks']
            issues = normalized['issues']
    reviews = parsed.get('reviews') if isinstance(parsed.get('reviews'), list) else []
    if reviews:
        checks = _visual_concept_plan_adjudicate_checks(checks, reviews)
    model_issues = _visual_concept_plan_normalize_issues(parsed.get('issues') or [])
    if model_issues:
        issues = model_issues
    can_proceed = not any(check.get('result') == 'متعارض' for check in checks)
    chat_memory.apply_model_memory(conversation, parsed)
    return jsonify({
        'success': True,
        'reply': reply,
        'action': action,
        'rows': rows,
        'totals': totals,
        'checks': checks,
        'issues': issues,
        'canProceed': can_proceed,
        'memory': conversation['memory'],
        'decisions': conversation['decisions'],
    })
