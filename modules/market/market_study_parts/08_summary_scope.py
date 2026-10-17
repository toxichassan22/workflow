"""Geographic and project-activity scope rules for market summaries."""


def summary_activity_profile(payload):
    """Resolve only the project's selected activities, excluding comparison filters."""
    source = dict(payload or {})
    nested = source.get('projectData') or source.get('project_data')
    if isinstance(nested, dict):
        for key in ('projectType', 'project_type', 'projectSubtype', 'project_subtype',
                    'projectComponents', 'project_components', 'project_mixed_components',
                    'components'):
            if not source.get(key) and nested.get(key):
                source[key] = nested[key]
    source.pop('comparisonTypes', None)
    source.pop('comparison_types', None)

    activities = []
    kinds = set()
    axes = project_competitor_axes(source)
    for axis in axes:
        base = str(axis.get('base') or axis.get('key') or '')
        if base == 'general':
            continue
        names = axis.get('names') if isinstance(axis.get('names'), list) else []
        for name in names or [axis.get('label') or axis.get('label_en')]:
            text = str(name or '').strip()
            if text and text not in activities:
                activities.append(text)
        if base in {'residential'}:
            kinds.add('residential')
        elif base in {'office', 'retail', 'commercial'}:
            kinds.add('commercial')
        elif base == 'hospitality':
            kinds.add('hospitality')
        elif base in {'industrial', 'logistics'}:
            kinds.add('industrial')
        elif base == 'entertainment':
            kinds.add('entertainment')

    if not activities:
        for key in ('projectSubtype', 'project_subtype', 'projectComponents',
                    'project_components', 'project_mixed_components'):
            for value in _split_multi_values(source.get(key)):
                if value and value not in activities and value not in {'متعدد الاستخدامات', 'mixed use'}:
                    activities.append(value)
        if not activities:
            main_type = str(source.get('projectType') or source.get('project_type') or '').strip()
            if main_type and main_type not in {'متعدد الاستخدامات', 'mixed use'}:
                activities.append(main_type)

    for activity in activities:
        folded = activity.casefold()
        if any(token in folded for token in (
                'فندق', 'فندقي', 'شقق مخدومة', 'منتجع', 'hotel', 'hospitality', 'resort')):
            kinds.add('hospitality')
        if any(token in folded for token in (
                'صناعي', 'مصنع', 'مستودع', 'لوجست', 'industrial', 'warehouse', 'logistic')):
            kinds.add('industrial')
        if any(token in folded for token in (
                'سكن', 'شقق سكنية', 'residential', 'housing')):
            kinds.add('residential')
        if any(token in folded for token in (
                'تجاري', 'مكتب', 'تجزئة', 'محل', 'مطعم', 'مقهى', 'retail', 'office',
                'commercial', 'restaurant', 'shop', 'mall')):
            kinds.add('commercial')
        if any(token in folded for token in ('ترفيه', 'entertainment', 'leisure')):
            kinds.add('entertainment')

    source_kinds = []
    for kind, source_kind in (
            ('residential', 'سكني'), ('commercial', 'تجاري'),
            ('hospitality', 'فندقي'), ('industrial', 'صناعي ولوجستي')):
        if kind in kinds:
            source_kinds.append(source_kind)
    if 'entertainment' in kinds and 'تجاري' not in source_kinds:
        source_kinds.append('تجاري')
    return {'activities': activities, 'kinds': kinds, 'source_kinds': source_kinds}


def _summary_activity_scope_block(payload, offer_lang=None):
    profile = summary_activity_profile(payload)
    activities = profile['activities']
    if offer_lang == 'en':
        selected = ', '.join(activities) if activities else 'not specified in the project inputs'
        return (
            'Binding project activity scope:\n- Selected activities and revenue-bearing components: '
            + selected + '\nAnalyze all applicable market dimensions only for these selected activities. '
            'Do not add standalone analysis of unrelated sectors. Use population, airport, tourism, or other '
            'cross-sector indicators only when they materially support a selected activity, and label them as '
            'context. If the inputs do not identify an activity, state that limitation instead of assuming '
            'every sector.\n')
    selected = '، '.join(activities) if activities else 'غير محددة في مدخلات المشروع'
    return (
        'نطاق أنشطة المشروع الملزم:\n- الأنشطة والمكونات الاستثمارية المحددة: ' + selected + '\n'
        'حلل أبعاد السوق المطلوبة لهذه الأنشطة المحددة فقط، ولا تضف تحليلًا مستقلًا لقطاعات أخرى. '
        'استخدم السكان أو حركة المطار أو السياحة أو غيرها من المؤشرات العابرة للقطاعات كسياق فقط إذا كانت '
        'تخدم نشاطًا محددًا بوضوح، وسمّها مؤشرات مساندة. إذا لم تحدد المدخلات نشاطًا، اذكر هذا القيد ولا '
        'تفترض أن المطلوب تحليل كل القطاعات.\n')


def _summary_scope_block(payload, offer_lang=None):
    en = offer_lang == 'en'
    scope = normalize_summary_scope(
        (payload or {}).get('summaryScope') or (payload or {}).get('summary_scope'),
        (payload or {}).get('city'))
    if en:
        rows = [f"- {city['name']}: " +
                (', '.join(city['districts']) if city['districts'] else 'full city')
                for city in scope['cities']]
        return (
            'Binding geographic scope:\n' + '\n'.join(rows) + '\n'
            'An empty district list means the full city. For ordinary scope-bound axes, when districts '
            'are listed use only those districts. city_position always covers the full city. Each of '
            'sector_performance, supply, and demand must give a concise overview of the full city, then '
            'separate detailed analysis for each listed district; if no districts are listed, give detailed '
            'city-wide analysis. Never mix cities or districts, infer a district, or substitute nearby places. '
            'If evidence is missing, state that it is unavailable. The competitors radius applies only to '
            'the competitors table. National or regional figures are context only and must be labeled.\n')
    rows = [f"- {city['name']}: " +
            ('، '.join(city['districts']) if city['districts'] else 'كامل المدينة')
            for city in scope['cities']]
    return (
        'نطاق السوق الجغرافي الملزم:\n' + '\n'.join(rows) + '\n'
        'ترك الأحياء فارغة يعني تحليل المدينة كاملة. في المحاور العادية المقيدة بالنطاق، إذا ذُكرت أحياء '
        'فاستخدم هذه الأحياء وحدها. محور city_position يغطي المدينة كاملة دائمًا. وفي كل من '
        'sector_performance وsupply وdemand قدّم قراءة موجزة للمدينة كاملة، ثم تحليلًا مفصلًا منفصلًا '
        'لكل حي مدخل؛ وإن لم تُذكر أحياء فحلل المدينة كاملة بتفصيل. لا تخلط المدن أو الأحياء ولا تستنتج '
        'حيًا ولا تستبدله بمكان قريب. عند غياب الدليل صرّح بعدم توفره. نطاق المنافسين يخص جدول المنافسين '
        'فقط. أرقام المملكة أو المنطقة خلفية فقط ويجب وصفها بذلك صراحةً.\n')


def build_summary_user_prompt(payload, competitors, current_summary=None,
                              current_sources=None, current_swot=None,
                              offer_lang=None, retrieved_evidence=None):
    """Final Argon synthesis brief: project-activity-scoped, evidence-only prose."""
    en = offer_lang == 'en'
    today = date.today().isoformat()
    keys = [item['key'] for item in SUMMARY_SECTIONS]
    swot_keys = [item['key'] for item in SWOT_SECTIONS]
    evidence = str(retrieved_evidence or '').strip() or 'لا توجد صفحات مقروءة بعد.'
    local = payload.get('summaryLocalBenchmarks') or {}
    if en:
        scope_line = _summary_scope_block(payload, offer_lang)
        activity_scope_line = _summary_activity_scope_block(payload, offer_lang)
        lang = 'Write all narrative values in professional English.'
        output = (
            '{\n"title":"Market Study",\n"summary":{' +
            ','.join(f'"{key}":"Detailed analysis"' for key in keys) +
            '},\n"swot":{' + ','.join(f'"{key}":"..."' for key in swot_keys) +
            '},\n"decision":"one allowed decision value",\n"sources":['
            '{"name":"","url":"","data_date":"","accessed_at":"' + today +
            '","reliability":"","note":""}],\n"disclaimer":"Preliminary indicative study; not a certified valuation appraisal",\n'
            '"one_block_summary":"One cohesive professional market analysis paragraph"\n}')
        research_rules = (
            'Parallel Argon researchers have used Playwright with SearXNG and opened assigned source pages. '
            'You are the evidence synthesis model; do not browse and do not use prior knowledge. Analyze the '
            'local market only for the project activities and revenue-bearing components listed in the binding '
            'activity scope below; do not create standalone analyses of unrelated sectors. Use only claims '
            'supported by the retrieved evidence below. '
            'Every number must retain its exact geography, unit, period, and data date. Separate completed '
            'transactions from asking prices, signed rents from listing rents, and nightly booking quotes from '
            'annual hotel operating indicators such as ADR/occupancy. An inaccessible, gated, missing, or stale source is a coverage gap, '
            'not permission to estimate. Do not turn national data into city data or a sampled sheet into a '
            'complete city census. Cite each used specific page in sources; never use a homepage as evidence.\n')
        local_indicator_rules = (
            'Use official Saudi Census 2022 population and household figures only when they materially support '
            'a selected project activity; label the census year and exact geography, and include district values '
            'only at district resolution. Do not create a separate residential-market analysis unless residential '
            'is a selected activity. Use airport passenger and flight-movement figures only when a selected '
            'hospitality/tourism activity or another selected activity is materially served by them; keep them '
            'at city/airport level, with airport and period, and never call them ticket bookings or allocate them '
            'to districts; never allocate airport traffic to districts. State specific source or coverage gaps for relevant assigned indicators. Do not omit '
            'returned evidence that supports a selected activity. For hotel rates, prefer official data. In Arabic, '
            'call an arithmetic mean «المتوسط الحسابي» and never «وسيط»; reserve «الوسيط الإحصائي» for an actual '
            'median calculation. Use '
            'Booking.com as a fallback only when a hospitality activity is selected and official reports are '
            'unavailable or gated; if Booking.com observations were retrieved, calculate an arithmetic average '
            'only from at least three comparable properties in the same city/district, with identical stay dates '
            'and currency, comparable room and guest counts, and the same star class when available. Normalize '
            'each observed stay total by its number of nights and keep materially different meal/cancellation '
            'terms separate. Label it an approximate average of advertised room rates in the Booking.com sample; '
            'state exact stay dates, access date, sample size, currency, and tax/inclusion basis. Keep it separate '
            'from official ADR. With fewer than three comparable observations, report the sample without an '
            'average. Never call this a historical or annual ADR, or a city-wide market standard.\n')
        local_data_rules = (
            'For reference transactions from the supplied files, use the source names exactly as listed in each '
            'group’s sources field, such as Ministry of Justice. Attribute each figure to its listed source. '
            'These records are limited to the districts, categories, and dates present in the files and do not '
            'identify named competitor projects.\n')
        narrative_rules = (
            'Write each axis as connected analytical prose with evidence, interpretation, limits, and practical '
            'implication. Avoid empty bullet lists and repeated generic statements. Keep source names out of '
            'axis prose; put citations only in sources. The competition axis may use the supplied competitor '
            'table; every other axis analyzes only selected project activities and components in the binding '
            'activity scope. Include another sector only as brief context when it materially supports a '
            'selected activity. '
            'For project_evaluation, state where project inputs are insufficient; do not invent a financial case. '
            'Write a sequenced one_block_summary of about 250 words (150–400), without headings or lists.\n')
        decision = 'Allowed decision values: ' + ', '.join(DECISION_OPTIONS) + '.\n'
        current = (
            'Previous draft, sources, and SWOT are context only; verify every retained claim against current evidence.\n'
            + json.dumps({'summary': current_summary, 'sources': current_sources,
                          'swot': current_swot}, ensure_ascii=False, default=str) + '\n')
    else:
        scope_line = _summary_scope_block(payload, offer_lang)
        activity_scope_line = _summary_activity_scope_block(payload, offer_lang)
        lang = 'اكتب كل القيم النصية بالعربية المهنية الواضحة.'
        output = (
            '{\n"title":"دراسة السوق",\n"summary":{' +
            ','.join(f'"{key}":"تحليل تفصيلي"' for key in keys) +
            '},\n"swot":{' + ','.join(f'"{key}":"..."' for key in swot_keys) +
            '},\n"decision":"قيمة واحدة من قائمة القرار",\n"sources":['
            '{"name":"","url":"","data_date":"","accessed_at":"' + today +
            '","reliability":"","note":""}],\n"disclaimer":"هذه دراسة أولية استرشادية وليست تقييمًا عقاريًا معتمدًا",\n'
            '"one_block_summary":"فقرة تحليل سوق متماسكة ومهنية"\n}')
        research_rules = (
            'نفّذ باحثين متوازيين باستخدام Argon ومتصفح Playwright عبر SearXNG، وقد فتحوا صفحات المصادر الموكلة. '
            'أنت موديل تجميع الأدلة: لا تبحث الآن ولا تستخدم معرفتك السابقة. حلل السوق المحلي للأنشطة والمكونات '
            'الاستثمارية المحددة في نطاق المشروع الملزم أدناه فقط، ولا تنشئ تحليلًا مستقلًا لقطاعات غير مختارة. '
            'استخدم فقط الادعاءات التي يسندها الدليل '
            'المسترجع أدناه. احتفظ مع كل رقم بمكانه ووحدته وفترته وتاريخ بياناته. افصل الصفقات المنفذة عن أسعار '
            'الطلب، والإيجارات المسجلة عن إعلانات الإيجار، وسعر ليلة الحجز عن متوسط ADR أو الإشغال السنوي. '
            'المصدر المتعذر أو المحجوب أو الغائب أو القديم فجوة تغطية، وليس مبررًا للتقدير. لا تحوّل بيانات المملكة '
            'إلى بيانات مدينة، ولا تجعل شيتًا محدودًا تعدادًا كاملًا للمدينة. أدرج في sources كل صفحة محددة استُخدمت؛ '
            'الصفحة الرئيسية وحدها ليست دليلًا.\n')
        local_indicator_rules = (
            'استخدم أرقام تعداد السعودية 2022 للسكان والأسر فقط إذا كانت تخدم نشاطًا محددًا في المشروع، مع ذكر '
            'سنة التعداد والنطاق الجغرافي الدقيق. إذا كان المؤشر يخدم النشاط المختار، أدرج عدد سكان المدينة والأسر '
            'في city_position، واذكر كل حي مدخل منفصلًا عندما ينشر المصدر بياناته على مستوى الحي؛ وإلا فصرّح '
            'بمستوى التفصيل الجغرافي الذي تعذر الوصول إليه. '
            'لا تنشئ تحليلًا منفصلًا للسوق السكني ما لم يكن النشاط السكني ضمن الاختيارات. استخدم أعداد المسافرين '
            'وحركة الرحلات الرسمية للمطار فقط إذا كان نشاط فندقي/سياحي مختار أو كان نشاط مختار آخر يخدمه هذا '
            'المؤشر بوضوح، وعلى مستوى المدينة/المطار مع اسم المطار والفترة؛ لا توزع حركة المطار على الأحياء ولا تسمِّ '
            'المسافرين حجوزات تذاكر. اذكر فجوة المصدر أو الفترة للمؤشرات ذات الصلة التي تعذرت. لا تسقط دليلًا '
            'يدعم نشاطًا مختارًا. استخدم المصطلح «المتوسط الحسابي» عند حساب arithmetic mean، ولا تستخدم '
            '«وسيط» لهذا المعنى؛ فـ«الوسيط الإحصائي» هو median ولا يقال إلا عند حسابه فعلًا. بالنسبة لأسعار '
            'الفنادق، فضّل البيانات الرسمية. لا تستخدم أسعار Booking.com إلا كبديل للنشاط الفندقي المختار، '
            'وفقط إذا تعذرت التقارير الرسمية أو حُجبت؛ وإذا توفرت أسعار منها فاحسب المتوسط الحسابي فقط من ثلاث منشآت '
            'قابلة للمقارنة على الأقل في المدينة/الحي '
            'نفسه وبتواريخ إقامة وعملة واحدة وعدد غرف ونزلاء ونوع غرفة متقارب، ومن فئة النجوم نفسها عند توفرها. '
            'وحّد السعر بقسمة إجمالي الإقامة المرصود على عدد الليالي، وافصل شروط الوجبات أو الإلغاء المختلفة جوهريًا. '
            'سمّه «متوسطًا حسابيًا تقريبيًا لأسعار الغرف المعروضة في عينة Booking.com»، واذكر تواريخ الإقامة وتاريخ الوصول '
            'وحجم العينة والعملة وأساس احتساب الضرائب والخدمات. اعرضه منفصلًا عن ADR الرسمي. إذا قلّت العينة عن '
            'ثلاث أسعار قابلة للمقارنة، اعرض المشاهدات دون متوسط. لا تسمّه ADR تاريخيًا أو سنويًا أو معيارًا للسوق '
            'كله.\n')
        local_data_rules = (
            'انسب صفقات الملفات إلى أسماء المصادر كما تظهر حرفيًا في حقل sources لكل مجموعة؛ إذا ظهر «وزارة العدل» '
            'فسمّها «صفقات وزارة العدل». هذه سجلات مرجعية محدودة بالأحياء والفئات والتواريخ الموجودة في الملفات، '
            'ولا تحدد أسماء مشاريع منافسة.\n')
        narrative_rules = (
            'اكتب كل محور كنص تحليلي مترابط يوضح الدليل ثم دلالته وحدوده وأثره العملي. تجنب قوائم النقاط الجافة '
            'والعبارات العامة المتكررة. لا تذكر أسماء المصادر داخل نص المحاور؛ اجمعها في sources فقط. يجوز أن يستفيد '
            'محور المنافسة من جدول المنافسين المرفق؛ أما بقية المحاور فتحلل الأنشطة والمكونات المحددة في نطاق المشروع '
            'الملزم فقط. اذكر قطاعًا آخر كسياق موجز فقط إذا كان يخدم نشاطًا مختارًا بوضوح. '
            'في project_evaluation وضح المدخلات التي لا تكفي للحكم ولا تخترع حالة مالية. اكتب one_block_summary '
            'كتحليل متسلسل في نحو 250 كلمة (150 إلى 400)، بلا عناوين أو قوائم.\n')
        decision = 'قيم القرار المسموحة: ' + '، '.join(DECISION_OPTIONS) + '.\n'
        current = (
            'الملخص والمصادر وSWOT السابقة للسياق فقط؛ تحقق من كل معلومة ستبقيها على الدليل الحالي.\n'
            + json.dumps({'summary': current_summary, 'sources': current_sources,
                          'swot': current_swot}, ensure_ascii=False, default=str) + '\n')

    return (
        f'تاريخ الوصول: {today}\n'
        + research_rules + local_indicator_rules + activity_scope_line + scope_line
        + 'المهام المحورية: ' + ', '.join(keys) + '. حللها كلها بعمق وبلا إسقاط لأي محور.\n'
        + narrative_rules + lang + '\n' + decision
        + 'الأدلة وصفحات المصادر المفتوحة من الباحثين:\n' + evidence + '\n\n'
        + local_data_rules
        + 'بيانات الصفقات المرجعية من ملفات المالك، إن وجدت؛ يتضمن كل سجل اسم مصدره ضمن حقل sources:\n'
        + json.dumps(local, ensure_ascii=False, indent=2, default=str) + '\n\n'
        + 'مدخلات المشروع لتحديد النشاط والنطاق والتقييم المحايد:\n'
        + _project_input_block(payload) + '\n\n'
        + 'المنافسون، لمحور competition فقط:\n'
        + json.dumps(competitors or [], ensure_ascii=False, indent=2, default=str) + '\n\n'
        + current + '\nأرجع JSON فقط بهذا الشكل، مع كل المفاتيح وعدم إضافة نص خارجه:\n'
        + output + '\n'
        + 'لكل رقم أو ادعاء في sources: ضع اسم المصدر ورابط الصفحة المفتوحة المحددة وتاريخ البيانات وتاريخ الوصول '
        + 'ومستوى الموثوقية وملاحظة تشرح التغطية والوحدة. لا تخترع رقمًا ولا مصدرًا.\n')


# Keep chat research on the same browser/search path and the same city/district rules.
_legacy_summary_chat_system = build_summary_chat_system


def build_summary_chat_system(offer_lang=None):
    prompt = _legacy_summary_chat_system(offer_lang)
    prompt = prompt.replace(
        'النطاق الجغرافي الملزم (حي المشروع ونطاق المنافسين المدخلان في البيانات) '
        'وفترة البيانات المحددة ملزمان لكل اقتراح ورقم: لا بيانات خارج النطاق إلا '
        'بديل الحي الأقرب الوحيد مع ذكره صراحةً، ولا مصادر خارج الفترة.',
        'نطاق المدينة والأحياء الاختيارية المحددة في بيانات الملخص وفترة البيانات ملزمة. '
        'لا تستخدم حيًا بديلًا قريبًا ولا مصادر خارج الفترة.')
    if offer_lang == 'en':
        prompt += ('Analyze this project’s selected activities and components only. Follow the city and optional '
                   'district scope; city_position always covers the full city, while sector_performance, supply, '
                   'and demand give a concise city overview plus detailed listed districts. No nearby substitute. '
                   'In Arabic output, use «المتوسط الحسابي» for arithmetic mean; use «الوسيط الإحصائي» only for a '
                   'median that was actually calculated.\n')
    else:
        prompt += ('حلل الأنشطة والمكونات المختارة في هذا المشروع فقط. التزم بالمدينة والأحياء الاختيارية؛ city_position '
                   'يغطي المدينة كاملة دائمًا، وsector_performance وsupply وdemand تعرض قراءة موجزة للمدينة ثم '
                   'تفصيل الأحياء المدخلة. لا تستخدم حيًا بديلًا قريبًا. عند حساب المتوسط الحسابي لا تستخدم كلمة '
                   '«وسيط»؛ فالوسيط الإحصائي مقياس مختلف ولا يقال إلا إذا حُسب فعلًا.\n')
    return prompt


_legacy_summary_chat_turn_prompt = build_summary_chat_turn_prompt


def build_summary_chat_turn_prompt(payload, axis, message, history, state):
    prompt = _legacy_summary_chat_turn_prompt(payload, axis, message, history, state)
    return (prompt + '\n' + _summary_activity_scope_block(payload) +
            _summary_scope_block(payload))


def build_summary_chat_research_prompt(payload, axis, message, history, state, queries,
                                       offer_lang=None):
    en = offer_lang == 'en'
    query_lines = '\n'.join(f'- {str(query).strip()}' for query in (queries or [])
                            if str(query or '').strip()) or 'بحث المحور المحدد'
    if en:
        instructions = (
            'Use the local Playwright browser tools with SearXNG. Open relevant result pages and interact with '
            'site controls when data requires city, district, date, or category selection: inspect the page, '
            'use type_text to enter values, click_element to apply/search, and scroll_page to read results. Do not answer from '
            'snippets alone or memory. Return only evidence-backed claims; report inaccessible data as a gap. '
            'Each source row needs a specific opened URL, data date, geography, and reliability. Cover the selected '
            'project activities only; other-sector facts are brief context only when they support a selected activity.\n')
    else:
        instructions = (
            'استخدم أدوات متصفح Playwright المحلي مع SearXNG. افتح صفحات النتائج وتفاعل مع عناصر الموقع عندما '
            'تتطلب البيانات اختيار مدينة أو حي أو تاريخ أو فئة: افحص الصفحة، واكتب القيم عبر type_text، واضغط '
            'عبر click_element، ومرر الصفحة عبر scroll_page لقراءة النتائج. لا تجب من مقتطفات البحث وحدها أو من الذاكرة. '
            'أعد ادعاءات مسندة فقط، واذكر تعذر البيانات كفجوة. كل مصدر يحتاج رابط صفحة مفتوحة محددة وتاريخ '
            'بيانات ومكانًا ومستوى موثوقية. غطِّ أنشطة المشروع المختارة فقط؛ ولا تذكر قطاعًا آخر إلا كسياق موجز '
            'يخدم نشاطًا محددًا.\n')
    return (
        _summary_chat_context_block(payload, axis, str(message or ''), history,
                                    state if isinstance(state, dict) else {})
        + '\nQueries requested by the discussion turn:\n' + query_lines + '\n\n'
        + _summary_activity_scope_block(payload, offer_lang)
        + _summary_scope_block(payload, offer_lang) + instructions
        + 'أرجع JSON فقط:\n{"reply":"...","ops":[],"sources_add":'
        '[{"name":"","url":"","data_date":"","note":"","reliability":""}]}\n'
        + _SUMMARY_CHAT_OPS_SPEC
        + 'قيم set_decision المسموحة حصرًا: ' + '، '.join(DECISION_OPTIONS) + '.\n')
