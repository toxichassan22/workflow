"""Geographic and project-activity scope rules for market summaries."""

import os

_MARKET_STUDY_PROMPT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    'prompts', 'market_study_prompt.txt')


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
            'separate detailed analysis for each listed district by name without omitting any entered district; if a district has transaction data detail its figures, and if a listed district had no completed sales in the period state that explicitly; if no districts are listed, give detailed '
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
        'لكل حي مدخل بالاسم دون استثناء أي حي؛ الحي الذي يحتوي بيانات بيع فصّل أرقامه، والحي الذي لا يحتوي صفقات بيع منفذة في الفترة صرّح بعدم تسجيل صفقات منفذة فيه خلال الفترة المحددة؛ وإن لم تُذكر أحياء فحلل المدينة كاملة بتفصيل. لا تخلط المدن أو الأحياء ولا تستنتج '
        'حيًا ولا تستبدله بمكان قريب. عند غياب الدليل صرّح بعدم توفره. نطاق المنافسين يخص جدول المنافسين '
        'فقط. أرقام المملكة أو المنطقة خلفية فقط ويجب وصفها بذلك صراحةً.\n')


def build_summary_user_prompt(payload, competitors, current_summary=None,
                              current_sources=None, current_swot=None,
                              offer_lang=None, retrieved_evidence=None):
    """Final model synthesis brief: project-activity-scoped, evidence-only prose."""
    en = offer_lang == 'en'
    today = date.today().isoformat()
    keys = [item['key'] for item in SUMMARY_SECTIONS]
    swot_keys = [item['key'] for item in SWOT_SECTIONS]
    evidence = str(retrieved_evidence or '').strip() or 'لا توجد صفحات مقروءة بعد.'
    local = payload.get('summaryLocalBenchmarks') or {}
    activity_kinds = summary_activity_profile(payload).get('kinds') or set()
    if en:
        transaction_detail_rules = (
            'When selected residential or commercial activities have retrieved completed-sale data broken '
            'down by property type or apartment bedroom count, preserve each available category in '
            'sector_performance with its transaction count, arithmetic mean, highest observed price, exact '
            'geography and period. Do not collapse supplied bedroom buckets into one overall average. If a '
            'category is absent from the evidence, omit it from the user-facing analysis; do not describe the '
            'missing category or replace it with advertised prices.\n'
            if activity_kinds.intersection({'residential', 'commercial'}) else '')
    else:
        transaction_detail_rules = (
            'إذا وفر الدليل صفقات بيع منفذة للنشاط السكني أو التجاري المختار ومقسمة حسب نوع العقار أو عدد '
            'غرف نوم الشقق، فأبقِ كل فئة متاحة في sector_performance مع عدد الصفقات والمتوسط الحسابي وأعلى '
            'سعر مرصود والنطاق الجغرافي والفترة. لا تدمج فئات غرف النوم في متوسط واحد. اعرض كل فئة موجودة '
            'في الأدلة فقط؛ واحذف الفئات الغائبة دون ذكر غيابها، ولا تستبدلها بأسعار الإعلانات.\n'
            if activity_kinds.intersection({'residential', 'commercial'}) else '')
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
            'Parallel source researchers used Playwright browser search, preferring SearXNG and falling back '
            'to other browser search providers when needed. Check each research report’s opened_evidence and '
            'coverage_status; retrieved source-plan pages are evidence but do not prove exhaustive coverage. '
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
            'to districts; never allocate airport traffic to districts. Keep source or coverage gaps in internal reasoning only; omit missing indicators from the final user-facing summary. Do not omit '
            'returned evidence that supports a selected activity. In demand and market_gap, leverage housing preference data (villa vs apartment ratios, demand by unit size bracket from housing statistics and census) to evaluate project residential unit sizing and identify market gaps. Leverage commercial registrations, business formation figures, and Ejar commercial lease contract growth rates to substantiate institutional demand for office components. For hotel rates, prefer official data. '
            'Never write the Arabic word «وسيط» in any user-facing value. Use «متوسط حسابي» only for a true '
            'arithmetic mean; omit a reported median rather than relabeling it as an average. For every selected '
            'hospitality activity, collect official operating data and Booking.com hotel prices. For every '
            'selected residential activity, also collect Booking.com prices for bookable serviced apartments, '
            'short-stay apartments, and villas when listed. Keep accommodation types separate from each other, '
            'hotel prices, apartment/villa sales, and long-term rents. For applicable Booking.com samples, '
            'calculate an arithmetic average '
            'only from at least three comparable properties in the same city/district, with identical stay dates '
            'and currency, comparable room and guest counts, and the same star class when available. Normalize '
            'each observed stay total by its number of nights and keep materially different meal/cancellation '
            'terms separate. Label it an approximate average of advertised room rates in the Booking.com sample; '
            'state exact stay dates, source publication/data date when available, sample size, SAR currency, and tax/inclusion basis. '
            'Convert every foreign-currency amount to SAR using a verified rate for its data date; omit the amount if no rate can be verified. Keep it separate '
            'from official ADR. With fewer than three comparable observations, report the sample without an '
            'average. Never call this a historical or annual ADR, or a city-wide market standard.\n')
        local_data_rules = (
            'For reference transactions from the supplied files, use the source names exactly as listed in each '
            'group’s sources field, such as Ministry of Justice. Attribute each figure to its listed source. '
            'Dynamic District Rule: For every district present in summaryLocalBenchmarks groups, provide a dedicated, '
            'standalone analytical paragraph detailing its transaction count, average price per sqm, price range (min to max), '
            'and average deal value with investment takeaways. Never merge two districts into a joint paragraph or condense any '
            'district into a footnote. If data exists for only one district, analyze that district alone. '
            'All Entered Districts Rule: When specific districts are listed in the geographic scope (summaryScope), every listed district must appear by name across sector_performance, supply, and demand. For districts with recorded sales transactions, provide their detailed metrics as specified above. For any listed district with no recorded completed sales in the period, state clearly that no completed sales were recorded for it in the period along with its comparative context, rather than dropping the district from the narrative. '
            'Rental Benchmark Rule: In rental_groups from Ejar and Sakani, state for each property category both its transaction count '
            'and its average annual rental value without dropping rental amounts. '
            'Future Pipeline and Mega-Projects Rule: In supply, include all major planned and under-development masterplans and destinations retrieved in evidence (such as National Housing Company NHC destinations: Al-Sadan, Jeddah Heights, Al-Wurayf, and other major developer pipelines) as the future competitive supply pipeline upon delivery; state their announced unit counts, areas, and investment volumes, and never drop them on the pretext that they are under development and not yet delivered. '
            'Regional Price Benchmarks Rule: In sector_performance, when price indicators are retrieved across city zones (e.g. North Jeddah, specific districts like Al-Nahdah or Obhur, compared to South/Central from professional reports like Knight Frank or CBRE), incorporate these full price benchmarks to establish the geographical pricing context for the project. Do not restrict pricing to single transactions and discard retrieved zonal benchmarks. '
            'Market Scale & Housing Stock Rule: In city_position and demand, incorporate total residential transaction volumes and values with YoY growth, as well as total existing housing stock and projected future pipeline (e.g. 2027 and 2030) from professional market reports to reflect market depth and absorption capacity.\n')
        narrative_rules = (
            'Write each axis in formal, professional advisory language with fluid executive prose. '
            'Avoid robotic colon-separated bullet headers (e.g. avoid starting paragraphs with "Sector Performance:", "Sales Transactions:"). '
            'Instead, weave findings into cohesive analytical paragraphs connecting pricing and demand trends to the project concept and site. '
            'Adopt a constructive, actionable advisory tone that uses available figures to formulate investment and pricing hypotheses instead of consuming narrative space with repetitive defensive disclaimers, excuses, or pretexts for discarding returned evidence. State methodological limitations concisely and focus on the investment interpretation of the numbers. '
            'Separate each selected activity, property type, and available unit category. Give '
            'apartments, villas, hotels, and every other selected activity comparable analytical depth when the '
            'evidence supports it; do not compress any available category into a one-line mention. Preserve every '
            'useful statistic and its interpretation, with no fixed word limit. Keep source names out of '
            'axis prose; put citations only in sources. The competition axis may use the supplied competitor '
            'table; every other axis analyzes only selected project activities and components in the binding '
            'activity scope. Include another sector only as brief context when it materially supports a '
            'selected activity. '
            'For project_evaluation, state where project inputs are insufficient; do not invent a financial case. '
            'The one_block_summary is a separate, cohesive executive paragraph with no fixed word limit; keep the '
            'detailed axis analysis clearly divided into lines.\n')
        decision = 'Allowed decision values: ' + ', '.join(DECISION_OPTIONS) + '.\n'
        prompt_file = str(globals().get('_MARKET_STUDY_PROMPT_FILE') or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            'prompts', 'market_study_prompt.txt'))
        if os.path.exists(prompt_file):
            try:
                with open(prompt_file, 'r', encoding='utf-8') as pf:
                    lines = [l for l in pf.readlines() if not l.strip().startswith('#')]
                    custom_market = ''.join(lines).strip()
                    if custom_market:
                        narrative_rules = custom_market + '\n' + narrative_rules
            except Exception:
                pass
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
            'نفّذ باحثون متوازيون البحث عبر متصفح Playwright مع تفضيل SearXNG واستخدام محركات المتصفح البديلة '
            'عند تعذره. راجع opened_evidence وcoverage_status في كل تقرير بحث؛ صفحات خطة المصادر دليل مسترجع '
            'لكنها لا تثبت استنفاد المصدر أو اكتمال تغطيته. '
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
            'في city_position، واذكر كل حي مدخل منفصلًا عندما ينشر المصدر بياناته على مستوى الحي؛ واحذف '
            'تفاصيل الحي غير المنشورة دون ذكر تعذر الوصول إليها. '
            'لا تنشئ تحليلًا منفصلًا للسوق السكني ما لم يكن النشاط السكني ضمن الاختيارات. استخدم أعداد المسافرين '
            'وحركة الرحلات الرسمية للمطار فقط إذا كان نشاط فندقي/سياحي مختار أو كان نشاط مختار آخر يخدمه هذا '
            'المؤشر بوضوح، وعلى مستوى المدينة/المطار مع اسم المطار والفترة؛ لا توزع حركة المطار على الأحياء ولا تسمِّ '
            'المسافرين حجوزات تذاكر. احتفظ بفجوات المصدر أو الفترة للتتبع الداخلي فقط، واحذف المؤشر غير المتاح من '
            'النص النهائي. لا تسقط دليلًا يدعم نشاطًا مختارًا. '
            'وظّف بيانات تفضيل نمط المسكن (نسبة سكان الفلل مقابل الشقق، وتوزيع المساحات الأكثر طلباً من إحصاءات المساكن والتعداد) في تقييم ملاءمة مساحات وحدات المشروع السكني وفهم الفجوة السوقية. واستفد من مؤشرات تأسيس الأعمال والسجلات التجارية ونمو عقود المكاتب الموثقة في منصة إيجار وتقارير المكاتب المهنية في إثبات وتفسير الطلب المؤسسي على المكون الإداري. لا تسقط هذه المؤشرات المسترجعة في الأدلة. '
            'لا تكتب كلمة «وسيط» في أي نص ظاهر للمستخدم. '
            'استخدم «متوسطًا حسابيًا» فقط للمقياس الذي يمثل متوسطًا حسابيًا فعلًا، وأسقط قيمة المقياس الآخر بدل '
            'إعادة تسميتها متوسطًا. بالنسبة لأسعار '
            'الفنادق، اجمع البيانات التشغيلية الرسمية وأسعار الفنادق في Booking.com لكل نشاط فندقي مختار. '
            'ولكل نشاط سكني مختار، اجمع أسعار Booking.com للشقق المخدومة والشقق والفلل المعروضة للإقامة القصيرة '
            'متى كانت متاحة. اعرض أنواع الإقامة كلًا على حدة وافصلها عن أسعار الفنادق وصفقات بيع الشقق/الفلل '
            'وإيجاراتها طويلة الأجل. إذا توفرت أسعار Booking.com فاحسب المتوسط الحسابي فقط من ثلاث منشآت '
            'قابلة للمقارنة على الأقل في المدينة/الحي '
            'نفسه وبتواريخ إقامة وعملة واحدة وعدد غرف ونزلاء ونوع غرفة متقارب، ومن فئة النجوم نفسها عند توفرها. '
            'وحّد السعر بقسمة إجمالي الإقامة المرصود على عدد الليالي، وافصل شروط الوجبات أو الإلغاء المختلفة جوهريًا. '
            'سمّه «متوسطًا حسابيًا تقريبيًا لأسعار الغرف المعروضة في عينة Booking.com»، واذكر تواريخ الإقامة وتاريخ '
            'نشر أو بيانات المصدر إن توفر وحجم العينة والعملة بالريال السعودي وأساس احتساب الضرائب والخدمات. '
            'حوّل كل مبلغ أجنبي إلى الريال بسعر صرف موثق لتاريخ بياناته؛ واحذف المبلغ إن تعذر توثيق السعر. اعرضه منفصلًا عن ADR الرسمي. إذا قلّت العينة عن '
            'ثلاث أسعار قابلة للمقارنة، اعرض المشاهدات دون متوسط. لا تسمّه ADR تاريخيًا أو سنويًا أو معيارًا للسوق '
            'كله.\n')
        local_data_rules = (
            'انسب صفقات الملفات إلى أسماء المصادر كما تظهر حرفيًا في حقل sources لكل مجموعة؛ إذا ظهر «وزارة العدل» '
            'فسمّها «صفقات وزارة العدل»، وإذا ظهر «منصة سكني - شبكة إيجار» فسمّها «المؤشر الإيجاري لشبكة إيجار ومنصة سكني». '
            'استفد من صفقات البيع المنفذة وصفقات المؤشر الإيجاري الموثقة للأنشطة السكنية والتجارية (المعارض، المكاتب، المحلات، الفلل، الشقق) '
            'في إثراء أداء القطاع والعرض والطلب وتحديد الأسعار المرجعية. '
            'قاعدة تحليل الأحياء في الصفقات المرجعية (قاعدة ديناميكية وشاملة): '
            'لكل حي يظهر له سجل في صفقات البيع المرجعية المرفقة (summaryLocalBenchmarks)، أفرده بفقرة تحليلية مستقلة وكاملة '
            'تفصل أداءه (اسم الحي، عدد الصفقات، المتوسط الحسابي لسعر المتر المربع المنفذ، النطاق السعري من الأدنى إلى الأعلى، '
            'والمتوسط الحسابي لقيمة الصفقة) مع الدلالة الاستثمارية. يُمنع منعًا باتًا دمج أي حيين واردين في البيانات داخل فقرة واحدة '
            'أو اختزال أي حي في جملة عابرة أو ملحقة مهما تفاوت عدد صفقاته؛ فكل حي في البيانات يمثل عينة مستقلة تستوجب قراءة متكاملة. '
            'وإن تضمنت البيانات حيًا واحدًا فقط فحلل ذلك الحي وحده. '
            'قاعدة شمولية كل الأحياء المدخلة في نطاق الدراسة: '
            'إذا حدد المستخدم أحياء في نطاق ملخص السوق (summaryScope)، فيجب أن تُغطى جميع الأحياء المدخلة بالاسم في كل من أداء القطاع والعرض والطلب؛ '
            'الحي الذي توفرت له صفقات بيع منفذة للفترة يُفرد بفقرته التحليلية وأرقامه كاملة كما ورد أعلاه، وأي حي مدخل آخر لم تُسجل له صفقات بيع منفذة خلال الفترة المحددة صرّح بوضوح: «وفي حي [اسم الحي] لم تُسجل صفقات بيع منفذة خلال الفترة، [مع بيان موقعه أو وضعه المقارن]»، ولا تُسقط أي حي مدخل بصمت أبداً، ولا تخلط حي المشروع بأحياء المقارنة المحيطة بل وضّح موقع المشروع وحالة المعروض والطلب في كل حي من الأحياء المدخلة. '
            'قاعدة المؤشر الإيجاري لشبكة إيجار وسكني (شمولية القيمة والعدد): '
            'عند استعراض مؤشرات الإيجار السنوي لشبكة إيجار ومنصة سكني المرفقة (rental_groups)، اذكر لكل فئة عقارية معروضة '
            '(المعارض، المحلات، المكاتب، الفلل، الشقق، الدوبلكس، الاستوديوهات) عدد صفقاتها ومتوسط قيمتها الإيجارية السنوية الموثقة '
            '(سواء بالريال/م² للتجاري أو بالريال للسكني) بدقة واكتمال دون إسقاط القيمة الإيجارية لأي فئة. '
            'قاعدة المعروض المستقبلي ومشاريع التطوير الكبرى (Future Pipeline): في محور المعروض supply، يجب إدراج مشاريع التطوير السكني الكبرى والوجهات المخططة وقيد التنفيذ في المدينة الواردة في الأدلة (مثل مشاريع الشركة الوطنية للإسكان NHC: وجهات السدن، جدة هايتس، الوريف، وغيرها) بوصفها معروضًا مستقبليًا ومشاريع قيد التطوير تنافس عند التسليم، مع ذكر عدد وحداتها وقيمتها الاستثمارية، ويُمنع منعًا باتًا إسقاطها بحجة أنها غير مسلّمة حاليًا؛ فالمعروض المستقبلي ركن أساسي في دراسة السوق. '
            'قاعدة النطاقات السعرية الجغرافية المرجعية: في محور أداء القطاع sector_performance، عند توفر مؤشرات أسعار مقسمة لمناطق المدينة (مثل شمال جدة، أو أحياء محددة كالنهضة وأبحر، ومقارنتها بالجنوب والوسط من تقارير نايت فرانك أو CBRE)، يجب إدراج هذه المتوسطات السعرية كاملة لتشكيل خريطة سعرية مرجعية تخدم تموضع المشروع السعري، ولا يجوز قصر التسعير على صفقات مفردة وإسقاط النطاقات السعرية الإقليمية المتاحة في الأدلة. '
            'قاعدة حجم السوق الكلي ومخزون الوحدات: في محوري وضع المدينة city_position والطلب demand، يجب إدراج إجمالي حجم المعاملات السكنية في المدينة وقيمتها المالية الإجمالية ومعدل نموها السنوي، بالإضافة إلى إجمالي المخزون السكني القائم وتوقعاته المستقبلية (2027 و2030) من تقارير السوق المهنية المعتمدة لبيان اتساع السوق ومعدل استيعابه.\n')
        narrative_rules = (
            'اكتب كل محور بلغة استشارية عقارية رسمية وفورمال ومسترسلة (Professional Fluent Advisory Tone). '
            'اجعل الصياغة متماسكة ومترابطة تحلل السوق بعين استثمارية خبيرة وتربط مؤشرات الأسعار والصفقات بمكونات المشروع وجدواه، '
            'مع تجنب التقطيع الآلي أو رص البيانات الجافة كعناوين نقطية منعزلة تنتهي بنقطتين رأسيين (تجنب عناوين مثل «أداء قطاع...:»، «صفقات بيع...:»)، '
            'بل اسرد التحليل بفقرات متماسكة تبدأ بجمل افتتاحية استشارية متصلة وتربط حركة الأسعار والطلب بالسياق العقاري العام وموقع المشروع. '
            'تبنّ لغة استشارية تحليلية شجاعة وبناءة توظف الأرقام المتاحة في صياغة فرضيات الاستثمار والتسعير بدلاً من استهلاك النص في عبارات التبرؤ الدفاعي أو الاعتذار المتكرر ومبررات عدم كفاية البيانات؛ اذكر القيود المنهجية باقتضاب وركّز على استخلاص الدلالات الاستثمارية للأرقام المتاحة. '
            'امنح الشقق والفلل والفنادق والمعارض وكل نشاط مختار عمقًا تحليليًا متقاربًا بحسب الأدلة، '
            'مع إدراج كل الأرقام المتاحة دون حد للكلمات أو اختصار مخل. اشرح دلالة الدليل وأثره العملي في سياق سردي متدفق. '
            'لا تذكر أسماء المصادر داخل نص المحاور؛ اجمعها في sources فقط. يجوز أن يستفيد '
            'محور المنافسة من جدول المنافسين المرفق؛ أما بقية المحاور فتحلل الأنشطة والمكونات المحددة في نطاق المشروع '
            'الملزم فقط. اذكر قطاعًا آخر كسياق موجز فقط إذا كان يخدم نشاطًا مختارًا بوضوح. '
            'في project_evaluation وضح المدخلات التي لا تكفي للحكم ولا تخترع حالة مالية. اجعل one_block_summary '
            'فقرة تنفيذية متماسكة ومسترسلة رفيعة الصياغة بلا حد للكلمات؛ وتبقى محاور التحليل التفصيلية متدفقة ومكتملة الأركان.\n')
        decision = 'قيم القرار المسموحة: ' + '، '.join(DECISION_OPTIONS) + '.\n'
        prompt_file = str(globals().get('_MARKET_STUDY_PROMPT_FILE') or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            'prompts', 'market_study_prompt.txt'))
        if os.path.exists(prompt_file):
            try:
                with open(prompt_file, 'r', encoding='utf-8') as pf:
                    lines = [l for l in pf.readlines() if not l.strip().startswith('#')]
                    custom_market = ''.join(lines).strip()
                    if custom_market:
                        narrative_rules = custom_market + '\n' + narrative_rules
            except Exception:
                pass
        current = (
            'الملخص والمصادر وSWOT السابقة للسياق فقط؛ تحقق من كل معلومة ستبقيها على الدليل الحالي.\n'
            + json.dumps({'summary': current_summary, 'sources': current_sources,
                          'swot': current_swot}, ensure_ascii=False, default=str) + '\n')

    if en:
        final_output_rules = (
            '\nFinal output rules override any earlier conflicting instruction. Use a formal real-estate advisory tone. '
            'Keep the narrative cohesive, fluent, and well-structured, with every selected activity and property type thoroughly analyzed. '
            'Ensure natural phrasing for monetary figures in SAR without mechanical currency repetitions. '
            'Round all numbers, monetary amounts, and percentages to whole integers or at most two decimal places (e.g. 218.76 or 219); never output long floating-point decimals or unrounded fractions like 218.763680126269923099. '
            'Strictly forbid performing unrequested ad-hoc mathematical divisions or fabricating derived per-capita or per-visitor ratios (e.g. dividing total tourism spend by visitor count); with the specific exception in competition analysis of calculating the indicative price per square meter for direct competitor units by dividing unit price by unit area (Price ÷ Area = SAR/sqm) when both are supplied, to enable direct unit-level pricing comparison with the project. Report all other figures and totals exactly as published in official sources with their original units without manual division. '
            'Maintain an actionable real-estate advisory tone that uses all retrieved numbers constructively; do not consume narrative space with repetitive defensive disclaimers, excuses, or pretexts for discarding returned evidence. State methodological limitations concisely and focus on investment interpretation. '
            'In competition: strictly separate geographic distance in km (distance_km) from pricing; never place distance into price descriptions or append currency to distances. '
            'Express all findings in fluent, coherent, and grammatically complete sentences without stacking raw disconnected tags or table headers. '
            'Every district present in summaryLocalBenchmarks must have its own standalone analytical paragraph. '
            'Every rental category in rental_groups must include both its transaction count and its average annual rental value. '
            'Give every evidence-supported category comparable depth and include all useful figures; impose no word limit. '
            'Omit unavailable subcategories without saying they were missing, inaccessible, or unavailable; use an empty string for an axis with no evidence. '
            'All monetary values in the study and source notes must be SAR. Convert other currencies using a verified exchange rate for the data date; omit an amount when the rate cannot be verified. '
            'Never mention the access date in narrative or source notes. State the study issue date and source publication/data date when available; accessed_at is metadata only.\n')
    else:
        final_output_rules = (
            '\nقواعد الإخراج النهائية تتقدم على أي تعليمات سابقة تتعارض معها. استخدم صياغة استشارية عقارية رسمية وفورمال ومسترسلة. '
            'حافظ على ترابط الفقرات وتدفقها السلس مع إبراز كل نشاط ونوع عقار وفئة وحدات دون تجزئة جافة مخلة. '
            'اكتب بأسلوب لغوي عربي سليم ومترابط وفصيح؛ يُمنع منعًا باتًا رصف الكلمات أو الأعمدة أو التصنيفات بدون صياغة جملية متماسكة (مثل تجنب صياغات عشوائية كـ «مبيت زائر سائح محلي» أو «توزعوا بـ ...»). '
            'قرّب جميع المبالغ المالية والأرقام والنسب الإحصائية إلى أرقام صحيحة أو منزلتين عشريتين كحد أقصى (مثال: 218.76 ألف ريال أو 219 ألف ريال)، ويُمنع منعًا باتًا كتابة أرقام بفواصل عائمة طويلة أو كسور غير مقربة مثل 218.763680126269923099. '
            'يُمنع منعًا باتًا إجراء أي عمليات قسمة حسابية يدوية أو اختراع نسب ومتوسطات مشتقة لم تُطلب منك صراحة (مثل قسمة إجمالي الإنفاق السياحي على عدد الزوار، أو قسمة إجمالي المساحات والسكان لاختراع معدلات فردية غير منشورة)؛ ويُستثنى من ذلك في محور المنافسة competition حساب سعر المتر المربع الاسترشادي لوحدات المنافسين المباشرين بقسمة سعر الوحدة على مساحتها (سعر الوحدة ÷ مساحة الوحدة = ريال/م²) عند توفرهما لتسهيل المقارنة السعرية مع المشروع مع ذكر أساس الحساب. انقل بقية الأرقام والمؤشرات كما وردت في مصادرها حرفيًا وبوحداتها الأصلية المعتمدة دون أي قسمة اجتهادية. '
            'حافظ على لغة استشارية تركز على توظيف الأرقام المتاحة استثمارياً؛ لا تستهلك النص في عبارات الاعتذار أو التبرؤ المتكرر من الأرقام، واذكر القيود المنهجية بإيجاز دون إسقاط أي رقم مسترجع في الأدلة. '
            'في محور المنافسة competition: افصل تمامًا وبدقة بين مسافة المنافس بالكيلومتر distance_km وبين أسعار الوحدات؛ فالمسافة تخص البُعد الجغرافي فقط ولا توضع إطلاقًا داخل جملة السعر ولا يلحق بها اسم العملة ريال. '
            'اكتب اسم العملة «ريال» أو «ريال سعودي» بأسلوب لغوي سليم، وتجنب تماماً أي تكرار ميكانيكي أو لفظي مثل «ريال سعودي سعوديًا». '
            'لكل حي يظهر في الصفقات المرجعية المرفقة فقرة تحليلية مستقلة ببياناته الكاملة دون دمج حيين معًا. '
            'ولكل فئة إيجارية في المؤشر الإيجاري اذكر عدد الصفقات ومتوسط القيمة الإيجارية السنوية معًا. '
            'امنح كل فئة تدعمها الأدلة عمقًا متقاربًا، وأدرج الأرقام المفيدة كاملة دون حد للكلمات. '
            'احذف الفئات الفرعية غير المتاحة دون القول إنها مفقودة أو متعذرة أو غير متاحة؛ وأعد قيمة فارغة للمحور الذي لا يسنده دليل. '
            'كل القيم المالية في الدراسة وملاحظات المصادر بالريال السعودي. حوّل العملات الأخرى بسعر صرف موثق لتاريخ البيانات؛ واحذف المبلغ إذا تعذر التحقق من السعر. '
            'لا تذكر تاريخ الوصول داخل النص أو ملاحظات المصادر. اذكر تاريخ إصدار الدراسة وتاريخ نشر/بيانات المصدر عند توفره؛ حقل accessed_at للتوثيق فقط. '
            'لا تكتب كلمة «وسيط» في أي نص ظاهر للمستخدم. استخدم «متوسط حسابي» فقط للمعدل الحسابي الحقيقي، واحذف قيمة أي مقياس آخر بدل تسميته متوسطًا.\n')

    period_bounds = (payload.get('summaryPeriodBounds')
                     or payload.get('dataPeriodBounds'))
    if isinstance(period_bounds, dict) and period_bounds:
        period_from = str(period_bounds.get('from') or '').strip() or ('unbounded' if en else 'غير محدد')
        period_to = str(period_bounds.get('to') or '').strip() or ('today' if en else 'تاريخ اليوم')
        period_line = (
            f'Binding summary data period: {period_from} through {period_to}. '
            'Every figure and source must fall inside it; older data is excluded.\n'
            if en else
            f'فترة بيانات الملخص الملزمة: من {period_from} إلى {period_to}. '
            'كل رقم ومصدر يجب أن يقع داخلها، وتُستبعد البيانات الأقدم.\n')
    else:
        period_line = (
            'No bounded data period was supplied; state each source period and do not imply a window.\n'
            if en else
            'لم تُحدد فترة بيانات ملزمة؛ اذكر فترة كل مصدر ولا توحِ بنطاق زمني.\n')

    return (
        f'تاريخ إصدار الدراسة: {today}\n'
        + research_rules + local_indicator_rules + transaction_detail_rules
        + activity_scope_line + scope_line + period_line
        + 'المهام المحورية: ' + ', '.join(keys) + '. حللها كلها بعمق وبلا إسقاط لأي محور.\n'
        + narrative_rules + lang + '\n' + decision
        + 'الأدلة وصفحات المصادر المفتوحة من الباحثين:\n' + evidence + '\n\n'
        + local_data_rules
        + 'بيانات الصفقات المرجعية والمؤشرات الرسمية من ملفات المالك وشبكة إيجار وسكني، إن وجدت؛ يتضمن كل سجل اسم مصدره ضمن حقل sources:\n'
        + json.dumps(local, ensure_ascii=False, indent=2, default=str) + '\n\n'
        + 'مدخلات المشروع لتحديد النشاط والنطاق والتقييم المحايد:\n'
        + _project_input_block(payload) + '\n\n'
        + 'المنافسون، لمحور competition فقط:\n'
        + json.dumps(competitors or [], ensure_ascii=False, indent=2, default=str) + '\n\n'
        + current + '\nأرجع JSON فقط بهذا الشكل، مع كل المفاتيح وعدم إضافة نص خارجه:\n'
        + output + '\n'
        + 'لكل رقم أو ادعاء في sources: ضع اسم المصدر ورابط الصفحة المفتوحة المحددة وتاريخ البيانات ومستوى الموثوقية وملاحظة المنهج والوحدة.\n'
        + final_output_rules)


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
                   'Use a formal advisory tone. Omit unavailable subcategories without saying they are missing. '
                   'Show all monetary values in SAR after verified conversion; never mention access dates in narrative. '
                   'Round all numbers to whole integers or at most two decimal places and avoid long floating-point decimals.\n')
    else:
        prompt += ('حلل الأنشطة والمكونات المختارة في هذا المشروع فقط. التزم بالمدينة والأحياء الاختيارية؛ city_position '
                   'يغطي المدينة كاملة دائمًا، وsector_performance وsupply وdemand تعرض قراءة موجزة للمدينة ثم '
                   'تفصيل الأحياء المدخلة. لا تستخدم حيًا بديلًا قريبًا. استخدم صياغة استشارية رسمية. احذف الفئات '
                   'الفرعية غير المتاحة دون ذكر غيابها. اعرض كل مبلغ بالريال السعودي بعد تحويل موثوق، ولا تذكر تاريخ '
                   'الوصول في النص. قرّب الأرقام لمنزلتين عشريتين كحد أقصى وتجنب الفواصل العائمة الطويلة. '
                   'لا تكتب كلمة «وسيط»؛ استخدم «متوسطًا حسابيًا» فقط عند حسابه فعلًا.\n')
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
            'Use the local Playwright browser search, starting with SearXNG and continuing with the available '
            'browser search providers if it fails. Open relevant result pages and interact with '
            'site controls when data requires city, district, date, or category selection: inspect the page, '
            'use type_text to enter values, click_element to apply/search, and scroll_page to read results. Do not answer from '
            'snippets alone or memory. Return only evidence-backed claims; omit inaccessible details from the user-facing reply. '
            'Each source row needs a specific opened URL, data date, geography, and reliability. Cover the selected '
            'project activities only; other-sector facts are brief context only when they support a selected activity.\n')
    else:
        instructions = (
            'استخدم بحث متصفح Playwright المحلي مع تفضيل SearXNG، واستمر بمحركات البحث المتاحة إذا تعذر. '
            'افتح صفحات النتائج وتفاعل مع عناصر الموقع عندما '
            'تتطلب البيانات اختيار مدينة أو حي أو تاريخ أو فئة: افحص الصفحة، واكتب القيم عبر type_text، واضغط '
            'عبر click_element، ومرر الصفحة عبر scroll_page لقراءة النتائج. لا تجب من مقتطفات البحث وحدها أو من الذاكرة. '
            'أعد ادعاءات مسندة فقط، واحتفظ بتعذر البيانات للتتبع الداخلي ولا تذكر المعلومة الغائبة في الرد. كل مصدر يحتاج رابط صفحة مفتوحة محددة وتاريخ '
            'بيانات ومكانًا ومستوى موثوقية. غطِّ أنشطة المشروع المختارة فقط؛ ولا تذكر قطاعًا آخر إلا كسياق موجز '
            'يخدم نشاطًا محددًا.\n')
    return (
        _summary_chat_context_block(payload, axis, str(message or ''), history,
                                    state if isinstance(state, dict) else {})
        + '\nQueries requested by the discussion turn:\n' + query_lines + '\n\n'
        + _summary_activity_scope_block(payload, offer_lang)
        + _summary_scope_block(payload, offer_lang) + instructions
        + ('Use SAR for all monetary values, converting foreign amounts with a verified rate tied to the data date. Omit an amount when no verified rate is available. Use formal advisory language and do not mention access dates in the reply.\n'
           if en else
           'اعرض كل مبلغ بالريال السعودي بعد تحويل موثق مرتبط بتاريخ البيانات، واحذف المبلغ إن تعذر توثيق سعر التحويل. استخدم صياغة استشارية رسمية ولا تذكر تاريخ الوصول في الرد.\n')
        + 'أرجع JSON فقط:\n{"reply":"...","ops":[],"sources_add":'
        '[{"name":"","url":"","data_date":"","note":"","reliability":""}]}\n'
        + _SUMMARY_CHAT_OPS_SPEC
        + 'قيم set_decision المسموحة حصرًا: ' + '، '.join(DECISION_OPTIONS) + '.\n')
