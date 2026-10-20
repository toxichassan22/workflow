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
    '- أي طلب يقترح توزيعًا أو يعدّله = "action":"update" مع الجدول كاملًا (كل الصفوف، لا الصفوف '
    'المتغيرة فقط). الوصف في "reply" لا يعوّض الجدول: العميل يعدّل الجدول من "rows" وحده. '
    'وإذا لم تستطع بناء جدول كامل، أرجع "action":"explain" واذكر السبب في "reply".\n'
    '- «اعتمد التوزيع» أو «طبّق التوزيع» أو «اعتماد التوزيع» = "action":"update": العميل يطبّق '
    'الجدول من "rows" لا من الوصف، فالرد الذي يشرح التوزيع بلا جدول لا يغيّر شيئًا.\n'
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

# Why the answer is not usable. Every failure carries a name, so the client can
# tell a failed request from a silent one: the provider error used to be
# swallowed and the route answered 200 with an empty body, and the table simply
# never changed while the screen said «تعذر تنفيذ الطلب على التوزيع».
PLANS_DISTRIBUTION_ERROR_TIMEOUT = 'PLANS_PROVIDER_TIMEOUT'
PLANS_DISTRIBUTION_ERROR_PROVIDER = 'PLANS_PROVIDER_FAILED'
PLANS_DISTRIBUTION_ERROR_UNREADABLE = 'PLANS_ANSWER_UNREADABLE'
PLANS_DISTRIBUTION_ERROR_EMPTY = 'PLANS_ANSWER_EMPTY'


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


def _plans_distribution_chat_prompt(data, workflow, context, current, state, reset):
    """The prompt for one turn: the approved facts, the table, the checks, the thread."""
    indexed_checks = [
        {'index': index, 'item': check.get('item'), 'detail': check.get('detail'),
         'result': check.get('result')}
        for index, check in enumerate(current['checks'])
    ]
    wishes = _visual_concept_text(workflow.get('distributionNotes'), 1000000)
    conversation = chat_memory.build_context(
        state['turns'], memory=state['memory'], decisions=state['decisions'])
    prompt = (
        'بيانات المشروع المعتمدة الوحيدة المسموح الاعتماد عليها:\n'
        + _visual_concept_plan_context_text(context, diagram_rules=False)
        + '\n\nالجدول الحالي للتوزيع (المصدر الوحيد للأرقام):\n'
        + json.dumps({'rows': current['rows'], 'totals': current['totals']}, ensure_ascii=False)
        + '\n\nبنود الفحص الآلي المطلوب الحكم عليها كلها:\n'
        + json.dumps(indexed_checks, ensure_ascii=False)
        + ('\n\nملاحظات العميل على التوزيع — رغبات تُطبَّق ضمن حدود الاشتراطات والبيانات '
           'المعتمدة ولا تجاوزها:\n' + wishes if wishes else '')
        + '\n\n' + chat_memory.prompt_block(conversation)
        + '\n\nطلب العميل الحالي:\n' + str(data.get('message') or '')
    )
    if reset:
        prompt += (
            '\n\nالعميل طلب بدء التوزيع من جديد: لا تعتمد على أي توزيع سابق ولا على أي قرار '
            'سابق، واقترح توزيعًا كاملًا من بيانات المشروع المعتمدة وحدها.')
    return prompt, conversation


def _plans_distribution_chat_execute(data):
    """One turn of the distribution conversation: (result, status).

    The turn runs as a queued job (the model thinks for minutes at maximum
    reasoning effort, and the hosting proxy drops a request that stays open
    that long), so this function owns the work and the job owns the waiting.
    """
    message = _visual_concept_text(data.get('message'), 4000)
    if not message:
        return {'success': False, 'error': 'اكتب طلبك أولاً',
                'error_code': 'MESSAGE_REQUIRED'}, 400
    reset = bool(data.get('reset'))
    _project_data, workflow, _boundary, _points, context = _visual_concept_plans_context_from_request(data)
    regulations = context.get('regulations') if isinstance(context.get('regulations'), dict) else {}
    posted = (data.get('distribution') if isinstance(data.get('distribution'), dict)
              else (workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {}))
    current = _visual_concept_plan_normalize_distribution(posted, context, regulations)
    if reset:
        # A clean start has no table to continue and no thread to inherit: the
        # new proposal must not be weighed against a decision the client dropped.
        current = dict(current, rows=[], totals=[])
    state = _plans_distribution_chat_state(data, workflow)
    if reset:
        state = {'turns': [], 'memory': '', 'decisions': []}
    user_prompt, conversation = _plans_distribution_chat_prompt(
        data, workflow, context, current, state, reset)
    try:
        call_timeout = _visual_plan_job_call_timeout(900)
    except Exception:
        return {'success': False, 'error': 'انتهت مهلة تنفيذ الطلب على التوزيع.',
                'error_code': 'PLANS_JOB_EXPIRED'}, 503
    try:
        response = call_openrouter_chat(
            PLANS_DISTRIBUTION_CHAT_SYSTEM_PROMPT, user_prompt, temperature=None, max_tokens=128000,
            model=VISUAL_PLAN_DISTRIBUTION_MODEL, reasoning_effort='max', timeout=call_timeout,
            response_format={'type': 'json_object'}, usage_ctx=_usage_ctx('image', data))
    except Exception as error:
        # A raised provider error used to be swallowed here, and the route
        # answered 200 with an empty body: the client could not tell a failed
        # request from a silent one, and the table never changed.
        app.logger.warning('Distribution chat failed: %s', type(error).__name__)
        return {'success': False, 'error': 'تعذر تنفيذ الطلب على التوزيع.',
                'error_code': PLANS_DISTRIBUTION_ERROR_PROVIDER}, 503
    # The raw answer is the only way to see what the model actually said: a
    # truncated JSON (the reasoning shares the token budget) or a missing table
    # used to look exactly like a finished turn.
    raw_text = _get_chat_response_text(response)
    print(f'[DISTRIBUTION CHAT] chars={len(raw_text or "")} raw={(raw_text or "")[:1500]!r}')
    fatal = _ai_fatal_error_dict(response)
    if fatal is not None:
        fatal_response = _ai_fatal_http_response(response)
        if fatal_response is not None:
            return fatal_response.get_json(), fatal_response.status_code
        return {'success': False, 'error': _client_safe_llm_error(fatal.get('message')),
                'error_code': fatal.get('error_code') or PLANS_DISTRIBUTION_ERROR_PROVIDER}, 503
    if isinstance(response, dict) and response.get('error'):
        provider_message = _chat_error_message(response)
        timed_out = 'انتهت مهلة' in str(provider_message)
        return {'success': False, 'error': _client_safe_llm_error(provider_message),
                'error_code': (PLANS_DISTRIBUTION_ERROR_TIMEOUT if timed_out
                               else PLANS_DISTRIBUTION_ERROR_PROVIDER)}, 503
    parsed = parse_json_object(raw_text)
    if not isinstance(parsed, dict) or not parsed:
        return {'success': False,
                'error': 'ما جا رد مفهوم من النموذج — لم يتغير التوزيع.',
                'error_code': PLANS_DISTRIBUTION_ERROR_UNREADABLE}, 503
    reply = _visual_concept_plan_sanitize_text(parsed.get('reply'))[:6000]
    action = 'update' if str(parsed.get('action') or '').lower() == 'update' else 'explain'
    rows = current['rows']
    totals = current['totals']
    checks = current['checks']
    issues = current['issues']
    if action == 'update':
        candidate = parsed.get('rows') if isinstance(parsed.get('rows'), list) else []
        normalized = _visual_concept_plan_normalize_distribution(
            {'rows': candidate}, context, regulations, backfill=not current['rows'])
        dropped = _plans_distribution_chat_dropped_components(
            current['rows'], normalized['rows'], parsed.get('removedComponents'))
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
    if not reply and not parsed.get('rows'):
        # A silent answer is a failed turn, not an empty success.
        return {'success': False, 'error': 'لم يرد النموذج بجواب — لم يتغير التوزيع.',
                'error_code': PLANS_DISTRIBUTION_ERROR_EMPTY}, 503
    reviews = parsed.get('reviews') if isinstance(parsed.get('reviews'), list) else []
    if reviews:
        checks = _visual_concept_plan_adjudicate_checks(checks, reviews)
    model_issues = _visual_concept_plan_normalize_issues(parsed.get('issues') or [])
    if model_issues:
        issues = model_issues
    can_proceed = not any(check.get('result') == 'متعارض' for check in checks)
    chat_memory.apply_model_memory(conversation, parsed)
    # Whether the table actually changed: a finished turn that leaves the floors
    # as they were must not look like an applied layout.
    table_changed = bool(action == 'update' and rows)
    print(f'[DISTRIBUTION CHAT] action={action} rows={len(rows)} table_changed={table_changed}')
    return {
        'success': True,
        'reply': reply,
        'action': action,
        'rows': rows,
        'totals': totals,
        'checks': checks,
        'issues': issues,
        'canProceed': can_proceed,
        'tableChanged': table_changed,
        'memory': conversation['memory'],
        'decisions': conversation['decisions'],
        'reset': reset,
    }, 200


@app.route('/api/visual-concept/plans-distribution-chat', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plans_distribution_chat():
    """One conversation owns the floor distribution: propose, explain, edit, check.

    The chat replaces the separate proposal / notes / revision / conflict-check
    controls. The table stays the single source of truth — it travels with the
    request and the answer carries the whole edited table back, so the client
    never has to merge a partial patch.

    The turn is queued and polled: the model thinks for minutes at maximum
    reasoning effort, and the hosting proxy drops a request that stays open
    that long, so a held request used to end in a timeout with no answer.
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error_code': 'INVALID_REQUEST'}), 400
    workflow_error = _visual_concept_plan_workflow_error(data, 'plan_site')
    if workflow_error:
        return jsonify(workflow_error), 400
    _billing_guard = _require_billing_balance('visual_concept')
    if _billing_guard is not None:
        return _billing_guard
    return _visual_plan_dispatch('distribution', data)
