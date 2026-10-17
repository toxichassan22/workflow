"""City and optional-district scope rules for the market-wide summary."""


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
    """Final Argon synthesis brief: whole-market, evidence-only, detailed prose."""
    en = offer_lang == 'en'
    today = date.today().isoformat()
    keys = [item['key'] for item in SUMMARY_SECTIONS]
    swot_keys = [item['key'] for item in SWOT_SECTIONS]
    evidence = str(retrieved_evidence or '').strip() or 'لا توجد صفحات مقروءة بعد.'
    local = payload.get('summaryLocalBenchmarks') or {}
    if en:
        scope_line = _summary_scope_block(payload, offer_lang)
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
            'whole market across residential, commercial, industrial/logistics, and hospitality sectors, '
            'regardless of the client project type. Use only claims supported by the retrieved evidence below. '
            'Every number must retain its exact geography, unit, period, and data date. Separate completed '
            'transactions from asking prices, signed rents from listing rents, and nightly booking quotes from '
            'annual hotel ADR/occupancy. An inaccessible, gated, missing, or stale source is a coverage gap, '
            'not permission to estimate. Do not turn national data into city data or a sampled sheet into a '
            'complete city census. Cite each used specific page in sources; never use a homepage as evidence.\n')
        local_indicator_rules = (
            'When official Saudi Census 2022 evidence is present, include the city population and household '
            'figures in city_position with the census year and exact geography; include each selected district '
            'separately only when the source reports it at district resolution. Use household counts as a '
            'residential-demand indicator, not as proof of transactions. In demand (and hospitality where '
            'relevant), use official airport passenger and flight-movement figures only as city/airport-level '
            'context, with airport and period; never allocate airport traffic to districts or describe passenger '
            'counts as ticket bookings. If any of these indicators was assigned but unavailable, state the '
            'specific source, period, or geographic-resolution gap. Do not omit a returned supported indicator. '
            'For hotel rates, prefer official data. Use Booking.com as a fallback only when official reports are '
            'unavailable or gated; if Booking.com observations were retrieved, calculate an arithmetic average only from at least three comparable '
            'properties in the same city/district, with identical stay dates and currency, comparable room and '
            'guest counts, and the same star class when available. Normalize each observed stay total by its '
            'number of nights and keep materially different meal/cancellation terms separate. Label the result '
            'an approximate average of advertised room rates in the Booking.com sample; state exact stay dates, '
            'access date, sample size, currency, and tax/inclusion basis. Keep it separate from official ADR. '
            'With fewer than three comparable observations, report the sample without an average. Never call '
            'this a historical or annual ADR, or a city-wide market standard.\n')
        local_data_rules = (
            'For reference transactions from the supplied files, use the source names exactly as listed in each '
            'group’s sources field, such as Ministry of Justice. Attribute each figure to its listed source. '
            'These records are limited to the districts, categories, and dates present in the files and do not '
            'identify named competitor projects.\n')
        narrative_rules = (
            'Write each axis as connected analytical prose with evidence, interpretation, limits, and practical '
            'implication. Avoid empty bullet lists and repeated generic statements. Keep source names out of '
            'axis prose; put citations only in sources. The competition axis may use the supplied competitor '
            'table, but all other axes analyze the complete local market, not only the project category. '
            'For project_evaluation, state where project inputs are insufficient; do not invent a financial case. '
            'Write a sequenced one_block_summary of about 250 words (150–400), without headings or lists.\n')
        decision = 'Allowed decision values: ' + ', '.join(DECISION_OPTIONS) + '.\n'
        current = (
            'Previous draft, sources, and SWOT are context only; verify every retained claim against current evidence.\n'
            + json.dumps({'summary': current_summary, 'sources': current_sources,
                          'swot': current_swot}, ensure_ascii=False, default=str) + '\n')
    else:
        scope_line = _summary_scope_block(payload, offer_lang)
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
            'أنت موديل تجميع الأدلة: لا تبحث الآن ولا تستخدم معرفتك السابقة. حلل السوق كله عبر السكني والتجاري '
            'والصناعي واللوجستي والفندقي، بصرف النظر عن نوع مشروع العميل. استخدم فقط الادعاءات التي يسندها الدليل '
            'المسترجع أدناه. احتفظ مع كل رقم بمكانه ووحدته وفترته وتاريخ بياناته. افصل الصفقات المنفذة عن أسعار '
            'الطلب، والإيجارات المسجلة عن إعلانات الإيجار، وسعر ليلة الحجز عن متوسط ADR أو الإشغال السنوي. '
            'المصدر المتعذر أو المحجوب أو الغائب أو القديم فجوة تغطية، وليس مبررًا للتقدير. لا تحوّل بيانات المملكة '
            'إلى بيانات مدينة، ولا تجعل شيتًا محدودًا تعدادًا كاملًا للمدينة. أدرج في sources كل صفحة محددة استُخدمت؛ '
            'الصفحة الرئيسية وحدها ليست دليلًا.\n')
        local_indicator_rules = (
            'إذا ظهر دليل رسمي من تعداد السعودية 2022، فأدرج عدد سكان المدينة والأسر في city_position مع سنة '
            'التعداد والنطاق الجغرافي الدقيق؛ وأدرج كل حي مدخل منفصلًا فقط إذا نشر المصدر رقمًا على مستوى الحي. '
            'استخدم عدد الأسر مؤشرًا مساعدًا للطلب السكني لا دليلًا على الصفقات. وفي demand (والضيافة عند الصلة)، '
            'استخدم أعداد المسافرين وحركة الرحلات الرسمية للمطار كسياق على مستوى المدينة/المطار فقط، مع اسم المطار '
            'والفترة؛ لا توزع حركة المطار على الأحياء ولا تسمِّ المسافرين حجوزات تذاكر. إذا تعذر أي مؤشر مكلّف به، '
            'فاذكر المصدر أو الفترة أو مستوى التفصيل الجغرافي الذي تعذر الوصول إليه. لا تسقط مؤشرًا مسندًا موجودًا '
            'في الأدلة. بالنسبة لأسعار الفنادق، فضّل البيانات الرسمية. إذا تعذرت التقارير الرسمية أو حُجبت فلا '
            'تستخدم أسعار Booking.com إلا كبديل؛ وإذا توفرت أسعار منها فاحسب متوسطًا حسابيًا فقط من ثلاث منشآت '
            'قابلة للمقارنة على الأقل في المدينة/الحي '
            'نفسه وبتواريخ إقامة وعملة واحدة وعدد غرف ونزلاء ونوع غرفة متقارب، ومن فئة النجوم نفسها عند توفرها. '
            'وحّد السعر بقسمة إجمالي الإقامة المرصود على عدد الليالي، وافصل شروط الوجبات أو الإلغاء المختلفة جوهريًا. '
            'سمّه «متوسطًا تقريبيًا لأسعار الغرف المعروضة في عينة Booking.com»، واذكر تواريخ الإقامة وتاريخ الوصول '
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
            'محور المنافسة من جدول المنافسين المرفق، لكن بقية المحاور تحلل السوق المحلي كاملًا لا فئة المشروع وحدها. '
            'في project_evaluation وضح المدخلات التي لا تكفي للحكم ولا تخترع حالة مالية. اكتب one_block_summary '
            'كتحليل متسلسل في نحو 250 كلمة (150 إلى 400)، بلا عناوين أو قوائم.\n')
        decision = 'قيم القرار المسموحة: ' + '، '.join(DECISION_OPTIONS) + '.\n'
        current = (
            'الملخص والمصادر وSWOT السابقة للسياق فقط؛ تحقق من كل معلومة ستبقيها على الدليل الحالي.\n'
            + json.dumps({'summary': current_summary, 'sources': current_sources,
                          'swot': current_swot}, ensure_ascii=False, default=str) + '\n')

    return (
        f'تاريخ الوصول: {today}\n'
        + research_rules + local_indicator_rules + scope_line
        + 'المهام المحورية: ' + ', '.join(keys) + '. حللها كلها بعمق وبلا إسقاط لأي محور.\n'
        + narrative_rules + lang + '\n' + decision
        + 'الأدلة وصفحات المصادر المفتوحة من الباحثين:\n' + evidence + '\n\n'
        + local_data_rules
        + 'بيانات الصفقات المرجعية من ملفات المالك، إن وجدت؛ يتضمن كل سجل اسم مصدره ضمن حقل sources:\n'
        + json.dumps(local, ensure_ascii=False, indent=2, default=str) + '\n\n'
        + 'مدخلات المشروع للسياق والتقييم المحايد فقط؛ لا تجعل نوع المشروع قيدًا على تحليل السوق كله:\n'
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
        'تحديدًا، فدراسة السوق الصحيحة تقيّم المشروع الفعلي ولا تكتفي بمعلومات عامة.',
        'ويظل تحليل السوق شاملًا لجميع القطاعات بصرف النظر عن نوع المشروع.')
    prompt = prompt.replace(
        'النطاق الجغرافي الملزم (حي المشروع ونطاق المنافسين المدخلان في البيانات) '
        'وفترة البيانات المحددة ملزمان لكل اقتراح ورقم: لا بيانات خارج النطاق إلا '
        'بديل الحي الأقرب الوحيد مع ذكره صراحةً، ولا مصادر خارج الفترة.',
        'نطاق المدينة والأحياء الاختيارية المحددة في بيانات الملخص وفترة البيانات ملزمة. '
        'لا تستخدم حيًا بديلًا قريبًا ولا مصادر خارج الفترة.')
    if offer_lang == 'en':
        prompt += ('Market-wide analysis is required regardless of project type. Follow the city and optional '
                   'district scope; city_position always covers the full city, while sector_performance, supply, '
                   'and demand give a concise city overview plus detailed listed districts. No nearby substitute.\n')
    else:
        prompt += ('حلل السوق كاملًا بصرف النظر عن نوع المشروع. التزم بالمدينة والأحياء الاختيارية؛ city_position '
                   'يغطي المدينة كاملة دائمًا، وsector_performance وsupply وdemand تعرض قراءة موجزة للمدينة ثم '
                   'تفصيل الأحياء المدخلة. لا تستخدم حيًا بديلًا قريبًا.\n')
    return prompt


_legacy_summary_chat_turn_prompt = build_summary_chat_turn_prompt


def build_summary_chat_turn_prompt(payload, axis, message, history, state):
    prompt = _legacy_summary_chat_turn_prompt(payload, axis, message, history, state)
    return (prompt + '\n' + _summary_scope_block(payload) +
            'حلل السوق كاملًا بصرف النظر عن نوع المشروع.\n'
            'Market-wide analysis applies across all sectors regardless of project type.\n')


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
            'Each source row needs a specific opened URL, data date, geography, and reliability. Market context '
            'covers all sectors regardless of project type.\n')
    else:
        instructions = (
            'استخدم أدوات متصفح Playwright المحلي مع SearXNG. افتح صفحات النتائج وتفاعل مع عناصر الموقع عندما '
            'تتطلب البيانات اختيار مدينة أو حي أو تاريخ أو فئة: افحص الصفحة، واكتب القيم عبر type_text، واضغط '
            'عبر click_element، ومرر الصفحة عبر scroll_page لقراءة النتائج. لا تجب من مقتطفات البحث وحدها أو من الذاكرة. '
            'أعد ادعاءات مسندة فقط، واذكر تعذر البيانات كفجوة. كل مصدر يحتاج رابط صفحة مفتوحة محددة وتاريخ '
            'بيانات ومكانًا ومستوى موثوقية. حلل سياق السوق في جميع القطاعات بصرف النظر عن نوع المشروع.\n')
    return (
        _summary_chat_context_block(payload, axis, str(message or ''), history,
                                    state if isinstance(state, dict) else {})
        + '\nQueries requested by the discussion turn:\n' + query_lines + '\n\n'
        + _summary_scope_block(payload, offer_lang) + instructions
        + 'أرجع JSON فقط:\n{"reply":"...","ops":[],"sources_add":'
        '[{"name":"","url":"","data_date":"","note":"","reliability":""}]}\n'
        + _SUMMARY_CHAT_OPS_SPEC
        + 'قيم set_decision المسموحة حصرًا: ' + '، '.join(DECISION_OPTIONS) + '.\n')
