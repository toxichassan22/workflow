# ━━━ Scoped Q&A chat for the land/croquis section (temporary feature) ━━━
#
# One-shot chat endpoint: the model answers questions about the parcel only from
# the recorded land data (section fields, document analysis, verified regulation
# facts). When a value is not in the data or is uncertain, the prompt forces the
# reply to say so instead of guessing — «لا تضليل».

LAND_CHAT_FIELD_LABELS = (
    ('project_name', 'اسم المشروع'),
    ('project_type', 'نوع المشروع'),
    ('city', 'المدينة'),
    ('district', 'الحي'),
    ('croquis_land_area', 'مساحة الأرض حسب الكروكي (م²)'),
    ('approved_financial_area', 'المساحة المعتمدة للدراسة المالية (م²)'),
    ('plot_number_croquis', 'رقم القطعة'),
    ('plan_number', 'رقم المخطط'),
    ('deed_number', 'رقم الصك أو المرجع'),
    ('deed_date', 'تاريخ الصك'),
    ('boundary_lengths', 'أطوال الأضلاع وحدود الأرض'),
    ('surrounding_streets', 'الشوارع المحيطة وعروضها'),
    ('north_direction', 'اتجاه الشمال'),
    ('facades_count', 'عدد الواجهات المطلة على شوارع'),
    ('facades_directions', 'اتجاهات الواجهات'),
    ('building_ratio_coverage', 'نسبة البناء والتغطية'),
    ('setbacks', 'الارتدادات'),
    ('building_ratio_setbacks', 'نسب البناء والارتدادات'),
    ('max_floors_height', 'الارتفاع أو عدد الأدوار المسموح'),
    ('approved_floor_count', 'الأدوار المعتمدة'),
    ('approved_coverage_ratio', 'التغطية المعتمدة'),
    ('approved_floor_area_ratio', 'معامل مسطح البناء المعتمد (FAR)'),
    ('allowed_uses', 'الاستخدامات المسموحة'),
    ('land_use_status', 'حالة استخدام المشروع'),
    ('regulatory_constraints', 'القيود التنظيمية'),
    ('land_and_building_summary', 'ملخص بيانات الأرض والاشتراطات'),
)

LAND_CHAT_SYSTEM_PROMPT = (
    'أنت مساعد متخصص في بيانات قسم «الأرض والكروكي» داخل منصة لاندروم.\n'
    'تجيب على أسئلة المستخدم حول الأرض والكروكي اعتمادًا على البيانات المرفقة حصريًا:\n'
    '- حقول القسم: بيانات القطعة والصك والمساحة والحدود والشوارع والواجهات والارتدادات والاستخدامات والقيود.\n'
    '- الإحداثيات وجدول الاتجاهات كما سُجلّا.\n'
    '- تحليل مستندات الأرض: القيم المستخرجة من الكروكي والرخصة والاشتراطات (نسب البناء والتغطية، معاملات FAR والأدوار الموثقة لكل شريحة) مع التعارضات المسجلة.\n'
    '- الحقائق التنظيمية الموثقة: قواعد المنطقة الرسمية إن وُجدت ونقاط المراجعة.\n'
    '- القيم المعتمدة التي أدخلها العميل (المساحة المعتمدة، الأدوار المعتمدة، التغطية المعتمدة، معامل البناء المعتمد).\n'
    'قواعد إلزامية:\n'
    '- أجب بالعربية بوضوح وبإيجاز.\n'
    '- استند فقط إلى البيانات المرفقة؛ لا تستنتج قيمة غير موجودة ولا تعمّم اشتراطات من خارجها.\n'
    '- إذا كانت المعلومة غير موجودة في البيانات أو غير مؤكدة، صرّح بذلك في الإجابة نفسها '
    '(مثل «البيانات المتاحة لا تذكر عدد الأدوار المسموح لمعامل التميّز») بدل تخمينها — ممنوع التضليل أو الافتراض.\n'
    '- فرّق دائمًا بين القيمة الموثقة في المستندات والقيمة المعتمدة التي أدخلها العميل، وسمِّ كلًا منهما عند ذكره.\n'
    '- إن كان للسؤال علاقة بتعارض أو نقطة مراجعة مسجلة فاذكرها.\n'
    '- لا تقترح تعديلات ولا تنفذ إجراءات على البيانات — الإجابة معلوماتية فقط.'
)


def _land_chat_context(project_data):
    """Everything the land chat may answer from, grouped for the prompt."""
    source = project_data if isinstance(project_data, dict) else {}
    context = {}
    fields = {}
    for key, label in LAND_CHAT_FIELD_LABELS:
        value = source.get(key)
        if value in (None, '', [], {}):
            continue
        fields[label] = _visual_concept_text(value, 3000)
    if fields:
        context['حقول قسم الأرض والكروكي'] = fields
    for key, label in (('survey_coordinates', 'إحداثيات المساحة'),
                       ('directions_table', 'جدول الاتجاهات')):
        rows = source.get(key)
        if isinstance(rows, str):
            rows = _visual_concept_parse_json(rows, [])
        if isinstance(rows, list) and rows:
            context[label] = rows[:60]
    analysis = source.get('land_documents_analysis')
    if isinstance(analysis, str):
        analysis = _visual_concept_parse_json(analysis, None)
    if isinstance(analysis, dict) and analysis:
        context['تحليل مستندات الأرض'] = analysis
    component_source = dict(source)
    if isinstance(component_source.get('financial_study_model'), str):
        component_source['financial_study_model'] = _visual_concept_parse_json(
            component_source['financial_study_model'], {})
    components = _visual_concept_components(component_source)
    if components:
        context['مكونات المشروع المعتمدة'] = components
    concept = _visual_concept_parse_json(source.get('visual_concept'), None)
    if not isinstance(concept, dict):
        concept = {}
    plans = concept.get('plansWorkflow') or concept.get('plans_workflow') or {}
    if not isinstance(plans, dict):
        plans = {}
    distribution = plans.get('distribution') or {}
    if not isinstance(distribution, dict):
        distribution = {}
    distribution_payload = {}
    for key in ('rows', 'totals', 'checks', 'issues'):
        rows = distribution.get(key)
        if isinstance(rows, list) and rows:
            distribution_payload[key] = rows[:60]
    if distribution.get('approved'):
        distribution_payload['approved'] = True
    if distribution_payload:
        context['توزيع المخطط التصوري على الأدوار'] = distribution_payload
    verification = plans.get('verification') or {}
    if not isinstance(verification, dict):
        verification = {}
    verification_issues = verification.get('issues')
    if isinstance(verification_issues, list) and verification_issues:
        context['نقاط مراجعة التحقق من المخطط'] = verification_issues[:30]
    try:
        facts = _visual_concept_plan_regulation_facts(source)
    except Exception:
        facts = {}
    if isinstance(facts, dict) and facts:
        facts.pop('survey_coordinate_count', None)
        context['الحقائق التنظيمية الموثقة'] = facts
    return context


def _land_chat_history(raw):
    history = []
    for item in (raw if isinstance(raw, list) else [])[-10:]:
        if not isinstance(item, dict):
            continue
        content = _visual_concept_text(item.get('content'), 2000)
        if content:
            history.append({'role': 'user' if item.get('role') == 'user' else 'assistant',
                            'content': content})
    return history


@app.route('/api/land-chat', methods=['POST'])
@require_auth
def api_land_chat():
    data = request.get_json(silent=True) or {}
    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard
    message = _visual_concept_text(data.get('message'), 4000)
    if not message:
        return jsonify({'success': False, 'error': 'اكتب السؤال أولاً',
                        'error_code': 'MESSAGE_REQUIRED'}), 400
    project_data = clean_project_data(data.get('projectData') or {})
    context_json = json.dumps(_land_chat_context(project_data), ensure_ascii=False, default=str)[:14000]
    prior = ''
    history = _land_chat_history(data.get('history'))
    if history:
        prior = 'سياق المحادثة السابقة:\n' + '\n'.join(
            f"{'المستخدم' if turn['role'] == 'user' else 'المساعد'}: {turn['content']}"
            for turn in history) + '\n\n'
    user_content = f"{prior}بيانات الأرض والكروكي المتاحة:\n{context_json}\n\nسؤال المستخدم: {message}"
    try:
        response = call_text_chat(
            LAND_CHAT_SYSTEM_PROMPT, user_content, max_tokens=2500,
            usage_ctx=_usage_ctx_optional('ai_text', data))
        reply = extract_chat_content(response, 'LAND-CHAT')
    except Exception as exc:
        app.logger.exception('Land chat failed')
        fatal = _ai_fatal_http_response(exc)
        if fatal is not None:
            return fatal
        return jsonify({'success': False, 'error': 'تعذر الحصول على إجابة',
                        'error_code': 'TEXT_PROVIDER_FAILED'}), 503
    return jsonify({'success': True, 'reply': reply})
