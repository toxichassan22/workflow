# ━━━ Scoped Q&A chat for the land/croquis section (temporary feature) ━━━
#
# One-shot chat endpoint: the model answers questions about the parcel only from
# the recorded land data (section fields, document analysis, verified regulation
# facts). When a value is not in the data or is uncertain, the prompt forces the
# reply to say so instead of guessing — «لا تضليل».

LAND_CHAT_FIELD_LABELS = (
    ('project_name', 'اسم المشروع'),
    ('project_type', 'نوع المشروع'),
    ('project_subtype', 'الأنواع الفرعية للمشروع'),
    ('project_stage', 'مرحلة المشروع الحالية'),
    ('city', 'المدينة'),
    ('district', 'الحي'),
    ('croquis_land_area', 'مساحة الأرض حسب الكروكي (م²)'),
    ('approved_financial_area', 'المساحة المعتمدة للدراسة المالية (م²)'),
    ('plot_number_croquis', 'رقم القطعة'),
    ('plan_number', 'رقم المخطط'),
    ('subdivision_number', 'رقم القسم'),
    ('deed_number', 'رقم الصك أو المرجع'),
    ('deed_date', 'تاريخ الصك'),
    ('boundary_lengths', 'أطوال الأضلاع وحدود الأرض'),
    ('surrounding_streets', 'الشوارع المحيطة وعروضها'),
    ('north_direction', 'اتجاه الشمال'),
    ('facades_count', 'عدد الواجهات المطلة على شوارع'),
    ('facades_directions', 'اتجاهات الواجهات'),
    ('zoning_code', 'كود التنظيم'),
    ('land_use', 'استخدام الأرض'),
    ('building_ratio_coverage', 'نسبة البناء والتغطية'),
    ('setbacks', 'الارتدادات'),
    ('building_ratio_setbacks', 'نسب البناء والارتدادات'),
    ('max_floors_height', 'الارتفاع أو عدد الأدوار المسموح'),
    ('approved_floor_count', 'الأدوار المعتمدة'),
    ('approved_coverage_ratio', 'التغطية المعتمدة'),
    ('approved_floor_area_ratio', 'معامل مسطح البناء المعتمد (FAR)'),
    ('allowed_uses', 'الاستخدامات المسموحة'),
    ('allowed_uses_restrictions', 'الاستخدامات والقيود التنظيمية المسجلة'),
    ('parking_requirements', 'اشتراطات المواقف'),
    ('entrances_exits_requirements', 'اشتراطات المداخل والمخارج'),
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
    '- السجل الكامل للمنطقة التنظيمية الموثقة: كل شرائح المساحات ومعاملاتها واستثناءاتها وقيودها لمنطقة القطعة إن طُبقت.\n'
    '- القواعد العامة الموثقة لاشتراطات المدينة: الجداول والقواعد المشتركة (المواقف، الارتدادات، الارتفاعات، الملاحق…) إن توفرت للمدينة.\n'
    '- نصوص الاشتراطات الموثقة من ملفات الأمانة: مقتطفات النص الكامل للوائح البلدية مختارة بحسب سؤال المستخدم.\n'
    '- القيم المعتمدة التي أدخلها العميل (المساحة المعتمدة، الأدوار المعتمدة، التغطية المعتمدة، معامل البناء المعتمد).\n'
    'قواعد إلزامية:\n'
    '- أجب بلغة سؤال المستخدم نفسها بوضوح وبإيجاز — العربية إن كتب بالعربية، والإنجليزية إن كتب بها.\n'
    '- استند فقط إلى البيانات المرفقة؛ لا تستنتج قيمة غير موجودة ولا تعمّم اشتراطات من خارجها.\n'
    '- إذا كانت المعلومة غير موجودة في البيانات أو غير مؤكدة، صرّح بذلك في الإجابة نفسها '
    '(مثل «البيانات المتاحة لا تذكر عدد الأدوار المسموح لمعامل التميّز») بدل تخمينها — ممنوع التضليل أو الافتراض.\n'
    '- فرّق دائمًا بين القيمة الموثقة في المستندات والقيمة المعتمدة التي أدخلها العميل، وسمِّ كلًا منهما عند ذكره.\n'
    '- فسّر واشرح أي اشتراط أو قيمة أو مصطلح غير واضح في البيانات عندما يطلب المستخدم، واربط الاشتراط بشريحة مساحة الأرض أو نوع المشروع عند الحاجة.\n'
    '- إن سأل المستخدم عن عدد أو كمية (عدد أدوار، مسطحات، مواقف…) فابدأ بالإجابة المباشرة برقم واضح أو مدى محدد: احسبه من البيانات المتاحة (مثال: عدد الأدوار ≈ معامل البناء × المساحة ÷ مساحة مسطح الدور بأقصى تغطية متكررة موثقة) واكتب الناتج أولاً، ثم الشروط والمحاذير في سطرين أو ثلاثة لا أكثر. ممنوع أن يتحول الرد إلى قائمة «بيانات مطلوبة» طويلة بدل الإجابة — اذكر فقط الفرضيات التي بنى عليها رقمه.\n'
    '- عند الإجابة من نصوص الاشتراطات انسبها دائمًا إلى «ملفات الأمانة» فقط، ولا تذكر أسماء ملفات أو أرقام صفحات أو مستندات داخلية إطلاقًا.\n'
    '- اكتب المعادلات كنص عادي يقرؤه الإنسان (مثال: مسطح البناء = 7.0 × المساحة = 56000 م²)، وممنوع صيغ LaTeX أو رموزها مثل $ و \\times و \\text.\n'
    '- إن كان للسؤال علاقة بتعارض أو نقطة مراجعة مسجلة فاذكرها.\n'
    '- إن كان السؤال خارج بيانات الأرض والكروكي فوضّح أن هذا الشات مخصص لقسم الأرض والكروكي فقط.\n'
    '- لا تقترح تعديلات ولا تنفذ إجراءات على البيانات — الإجابة معلوماتية فقط.'
)


_LAND_CHAT_DOC_KEY_RE = re.compile(r'doc(\d+)(.*)')
_LAND_CHAT_DOC_STR_RE = re.compile(r'\bdoc(\d+)\b')
_LAND_CHAT_FILE_TOKEN_RE = re.compile(
    r'اشتراطات\s*\d+(?:\.\w+)?|[\w-]+\.pdf\b|clean_\w+')


def _land_chat_scrub_rule_refs(value):
    """Recursively drop internal citation keys (source/sources/_doc) from a
    regulation payload, rename the doc1/doc2 value keys, and rewrite file-name
    mentions inside string values, so the chat can only ever describe these
    rules as «ملفات الأمانة» — never internal file names or transcription ids."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if not isinstance(key, str):
                cleaned[key] = _land_chat_scrub_rule_refs(item)
                continue
            if key in ('source', 'sources', '_doc'):
                continue
            doc_match = _LAND_CHAT_DOC_KEY_RE.fullmatch(key)
            if doc_match:
                suffix = doc_match.group(2).replace('_', ' ').strip()
                key = 'وثيقة الأمانة ' + doc_match.group(1) + (
                    f' ({suffix})' if suffix else '')
            cleaned[key] = _land_chat_scrub_rule_refs(item)
        return cleaned
    if isinstance(value, list):
        return [_land_chat_scrub_rule_refs(item) for item in value]
    if isinstance(value, str):
        value = _LAND_CHAT_DOC_STR_RE.sub(r'وثيقة الأمانة \1', value)
        return _LAND_CHAT_FILE_TOKEN_RE.sub('ملفات الأمانة', value)
    return value


def _land_chat_regulation_evidence(message, source):
    """Top-scored page snippets from the municipal اشتراطات PDFs themselves.

    The digest covers the zone's recorded numbers; the files answer everything
    else — premium-FAR tiers, exceptions and conditional rules the digest never
    recorded. Runs only for the verified local city so Jeddah's files never
    bleed into another municipality's answers."""
    try:
        analysis = source.get('land_documents_analysis')
        if isinstance(analysis, str):
            analysis = _visual_concept_parse_json(analysis, {})
        analysis = analysis if isinstance(analysis, dict) else {}
        parcels = analysis.get('parcels') if isinstance(analysis.get('parcels'), list) else []
        parcel = parcels[0] if parcels and isinstance(parcels[0], dict) else {}
        facts_input = _visual_concept_plan_site_facts(source, analysis, parcel)
        site_city_slug, _site_city_label = city_regulations.resolve_site_city(
            facts_input.get('city'))
        if not city_regulations.is_local_city(site_city_slug):
            return ''
        records = _build_regulation_page_index()
    except Exception:
        return ''
    if not records:
        return ''
    query_tokens = _regulation_search_tokens(message, facts_input)
    scored = sorted(
        ({**record, 'score': _score_regulation_page(record['text'], query_tokens)}
         for record in records),
        key=lambda record: (-record['score'], record['page']))
    top = [record for record in scored if record['score'] > 0][:REGULATION_MAX_SNIPPETS]
    # Neutral headers only — the client must always see the source named
    # «ملفات الأمانة», never internal file names or page numbers.
    return '\n\n'.join(
        f"--- مقتطف من ملفات الأمانة ---\n"
        f"{(record['text'] or '')[:REGULATION_SNIPPET_CHARS]}"
        for record in top)


def _land_chat_context(project_data, message=''):
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
        context['الحقائق التنظيمية الموثقة'] = _land_chat_scrub_rule_refs(facts)
        if facts.get('regulatory_zone'):
            # The digest matched a verified zone — feed the whole zone record,
            # not only the matched row, so the other bands and exceptions
            # (premium FAR tiers, road rules…) stay answerable.
            try:
                zone_record = regulation_digest.zone_rules(facts.get('regulatory_zone'))
            except Exception:
                zone_record = None
            if isinstance(zone_record, dict) and zone_record:
                context['السجل الكامل للمنطقة التنظيمية الموثقة'] = (
                    _land_chat_scrub_rule_refs(zone_record))
            # The shared city rules apply to this parcel too — without them the
            # chat can quote a value but never explain the regulation behind it.
            try:
                general = regulation_digest.general_rules()
            except Exception:
                general = None
            if isinstance(general, dict) and general:
                context['القواعد العامة الموثقة لاشتراطات المدينة'] = (
                    _land_chat_scrub_rule_refs(general))
    evidence = _land_chat_regulation_evidence(message, source)
    if evidence:
        context['نصوص الاشتراطات الموثقة من ملفات الأمانة'] = evidence
    return context


def _land_chat_plain_math(text):
    """The chat UI renders plain text — the model sometimes emits LaTeX
    ($…$, \\text{…}, \\times) which reads as code to a human. Unwrap the
    common forms into readable inline math."""
    if not isinstance(text, str) or ('$' not in text and '\\' not in text):
        return text
    text = re.sub(r'\\\\', ' ', text)
    text = re.sub(
        r'\\(?:text|mathrm|mathbf|mathit|mathsf|textbf|operatorname|rm)'
        r'\{([^{}]*)\}', r'\1', text)
    text = re.sub(r'\\frac\{([^{}]*)\}\{([^{}]*)\}', r'\1/\2', text)
    text = re.sub(r'\\sqrt\{([^{}]*)\}', r'√(\1)', text)
    text = re.sub(
        r'\\(times|cdot|div|leq|geq|neq|approx|pm)\b',
        lambda m: {'times': '×', 'cdot': '×', 'div': '÷', 'leq': '≤',
                   'geq': '≥', 'neq': '≠', 'approx': '≈', 'pm': '±'}[m.group(1)],
        text)
    text = re.sub(r'\\le\b', '≤', text)
    text = re.sub(r'\\ge\b', '≥', text)
    text = re.sub(r'\\left|\\right', '', text)
    text = text.replace('\\%', '%').replace('\\&', '&')
    text = re.sub(r'\$\$([\s\S]*?)\$\$', r'\1', text)
    text = re.sub(r'\$([^$]+)\$', r'\1', text)
    text = re.sub(r'\\[\[\](){}]', '', text)
    text = re.sub(r'\\[a-zA-Z]+', ' ', text)
    text = text.replace('$', '')
    text = re.sub(r'[{}]', '', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


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
    context_json = json.dumps(_land_chat_context(project_data, message), ensure_ascii=False, default=str)[:60000]
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
        reply = _land_chat_plain_math(extract_chat_content(response, 'LAND-CHAT'))
    except Exception as exc:
        app.logger.exception('Land chat failed')
        fatal = _ai_fatal_http_response(exc)
        if fatal is not None:
            return fatal
        return jsonify({'success': False, 'error': 'تعذر الحصول على إجابة',
                        'error_code': 'TEXT_PROVIDER_FAILED'}), 503
    return jsonify({'success': True, 'reply': reply})
