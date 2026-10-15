

def canonical_index_source_url(url, operation=''):
    """Map a portal homepage to the dataset page that actually carries its data."""
    value = _norm(url)
    if not value or not is_generic_source_homepage(value):
        return value
    pages = _PORTAL_DATASET_PAGES.get(_source_host(value))
    if not pages:
        return value
    return pages.get(_canonical_operation(operation), '') or pages['default']


def official_source_reliability(entity_name='', source_name='', url=''):
    source = _fold_choice(source_name)
    if any(token in source for token in ('رسمي', 'المشروع', 'المطور', 'official')) and _source_host(url):
        return 'مصدر رسمي للجهة'
    entity_tokens = [token for token in re.findall(r'[a-z0-9]+', _fold_choice(entity_name)) if len(token) >= 4]
    host = _source_host(url)
    return 'مصدر رسمي للجهة' if host and entity_tokens and any(token in host for token in entity_tokens) else ''


def remove_url_from_competitor(competitor, url):
    result = dict(competitor or {})
    target = str(url or '').strip().casefold()
    result['source_urls'] = [item for item in competitor_source_urls(result)
                             if str(item).strip().casefold() != target]
    result['source_url'] = (result['source_urls'][0] if str(result.get('source_url') or '').strip().casefold() == target
                            and result['source_urls'] else '' if str(result.get('source_url') or '').strip().casefold() == target
                            else result.get('source_url', ''))
    fields = {}
    for field, values in competitor_field_sources(result).items():
        remaining = [item for item in values if str(item).strip().casefold() != target]
        if remaining:
            fields[field] = remaining
    result['field_sources'] = fields
    return result


def empty_source_row():
    return {
        'id': str(uuid.uuid4()),
        'name': '',
        'url': '',
        'data_date': '',
        'accessed_at': date.today().isoformat(),
        'reliability': '',
        'note': '',
    }


def catalog_payload():
    return {
        'projectTypes': PROJECT_TYPE_MAIN,
        'subtypes': PROJECT_TYPE_SUBTYPES,
        'mixedUseComponents': MIXED_USE_COMPONENT_OPTIONS,
        'levels': PROJECT_LEVELS,
        'activityClassByType': ACTIVITY_CLASS_BY_TYPE,
        'generalAudience': GENERAL_TARGET_AUDIENCE,
        'audienceByKind': TARGET_AUDIENCE_BY_KIND,
        'sourcePriority': SOURCE_PRIORITY,
        'typeSourcePriority': TYPE_SOURCE_PRIORITY,
        'competitorRadiusOptions': COMPETITOR_RADIUS_OPTIONS,
        'defaultCompetitorRadiusKm': DEFAULT_COMPETITOR_RADIUS_KM,
        'dataPeriodOptions': DATA_PERIOD_OPTIONS,
        'competitorStatuses': COMPETITOR_STATUS_OPTIONS,
        'competitorClasses': COMPETITOR_CLASS_OPTIONS,
        'competitorOperations': COMPETITOR_OPERATION_OPTIONS,
        'priceTypesByOperation': PRICE_TYPE_BY_OPERATION,
        'rangePriceTypes': sorted(RANGE_PRICE_TYPES),
        'competitorStatusesEn': COMPETITOR_STATUS_OPTIONS_EN,
        'competitorClassesEn': COMPETITOR_CLASS_OPTIONS_EN,
        'competitorOperationsEn': COMPETITOR_OPERATION_OPTIONS_EN,
        'priceTypesByOperationEn': PRICE_TYPE_BY_OPERATION_EN,
        'rangePriceTypesEn': sorted(RANGE_PRICE_TYPES_EN),
        'summaryTitle': SUMMARY_TITLE,
        'summaryWordTarget': SUMMARY_WORD_TARGET,
        'summaryLabel': SUMMARY_LABEL,
        'summarySections': SUMMARY_SECTIONS,
        'summarySectionHints': SUMMARY_SECTION_HINTS,
        'mandatoryRules': MANDATORY_RULES,
        'swotSections': SWOT_SECTIONS,
        'decisionOptions': DECISION_OPTIONS,
        'swotSectionHints': SWOT_SECTION_HINTS,
        'currency': CURRENCY_LABEL,
        'missingValuePhrase': MISSING_VALUE_PHRASE,
        'minDirectCompetitors': COMPETITOR_MIN_DIRECT,
    }


# ---------------------------------------------------------------------------
# Prompt construction (full PDF brief)
# ---------------------------------------------------------------------------

def _format_list(items, numbered=True):
    lines = []
    for index, item in enumerate(items, 1):
        lines.append(f'{index}. {item}' if numbered else f'- {item}')
    return '\n'.join(lines)


def build_consultant_system_prompt(offer_lang=None):
    en = (offer_lang == 'en')
    source_blocks = []
    labels = {
        1: 'المستوى الأول: المصادر الحكومية الرسمية — استخدمها أولًا للأرقام والمؤشرات والصفقات والاشتراطات',
        2: 'المستوى الثاني: المصادر الرسمية للمشروعات',
        3: 'المستوى الثالث: التقارير المهنية',
        4: 'المستوى الرابع: منصات الإعلانات — أسعارها أسعار طلب وليست صفقات منفذة',
        5: 'المستوى الخامس: المصادر المساندة — لا تستخدمها وحدها لتحديد سعر المشروع',
    }
    for level, title in labels.items():
        if SOURCE_PRIORITY[level]:
            source_blocks.append(title + ':\n' + _format_list(SOURCE_PRIORITY[level], numbered=False))

    type_blocks = []
    for key, title in (
        ('سكني', 'إذا كان المشروع سكنيًا حلل'),
        ('مكاتب', 'للمكاتب حلل'),
        ('تجزئة', 'للتجزئة والمراكز التجارية حلل'),
        ('فندقي', 'إذا كان المشروع فندقيًا حلل'),
        ('صناعي ولوجستي', 'إذا كان المشروع صناعيًا أو لوجستيًا حلل'),
    ):
        type_blocks.append(title + ':\n' + _format_list(TYPE_ANALYSIS_POINTS[key]))
        sources_key = 'تجاري' if key in ('مكاتب', 'تجزئة') else key
        type_sources = TYPE_SOURCE_PRIORITY[sources_key]
        if type_sources:
            type_blocks.append(
                f'مصادر هذا النشاط حسب الأولوية:\n{_format_list(type_sources)}'
            )

    mixed = (
        'إذا كان المشروع متعدد الاستخدامات:\n'
        '1. حلل كل مكون بشكل منفصل\n'
        '2. استخدم مصادر ومؤشرات كل نشاط\n'
        '3. لا تخلط أسعار أو مؤشرات الأنشطة\n'
        '4. وضح علاقة المكونات ببعضها\n'
        '5. حدد أي مكون هو المحرك الرئيسي للمشروع\n'
        '6. حدد المكونات المساندة\n'
        '7. قيّم مخاطر زيادة المساحات في أي نشاط\n'
        '8. قدم توصية بتوزيع المساحات حسب الطلب المتوقع'
    )

    summary_spec = '\n'.join(
        f'- {item["label"]}: {SUMMARY_SECTION_HINTS[item["key"]]}'
        for item in SUMMARY_SECTIONS
    )
    if en:
        axes_sentence = ('\nWrite each axis in clear analytical prose; short bullets inside an axis value '
                         'are allowed when needed. Never compress the axes into one paragraph or merge them '
                         'into a single field.\n')
        one_block_sentence = (
            f'Field one_block_summary is {SUMMARY_TITLE} itself: one cohesive, polished English paragraph '
            f'about this project\'s market, about {SUMMARY_WORD_TARGET} words, never fewer than {SUMMARY_MIN_WORDS} '
            'words and no more than 400 words. Cover the market, city, sector, supply, demand, competition, '
            'gap, recommendation and decision conditions with sufficient detail in one flow, with no subheadings, '
            'numbering or lists. Make it a complete summary, not a short abstract, with no SWOT list and no '
            'sources list.\n\n'
        )
    else:
        axes_sentence = ('\nاكتب كل محور بصياغة تحليلية واضحة، ويمكن تنظيم التفاصيل داخله في نقاط قصيرة عند الحاجة. '
                         'لا تختصر المحاور في فقرة واحدة ولا تدمجها في حقل واحد.\n')
        one_block_sentence = (
            f'حقل one_block_summary هو {SUMMARY_TITLE} نفسه: فقرة عربية واحدة متماسكة ومحترمة عن سوق هذا المشروع، '
            f'في حدود {SUMMARY_WORD_TARGET} كلمة، على ألا تقل عن {SUMMARY_MIN_WORDS} كلمة وألا تتجاوز 400 كلمة. '
            'اشرح السوق والمدينة والقطاع والعرض والطلب والمنافسة والفجوة والتوصية وشروط القرار بتفصيل كافٍ داخل '
            'سياق واحد، بلا عناوين فرعية ولا ترقيم ولا نقاط. اجعلها ملخصًا كاملًا لا مجرد خلاصة قصيرة، ولا تضع '
            'فيها قائمة SWOT أو قائمة مصادر.\n\n'
        )

    return (
        'أنت مستشار متخصص في دراسات السوق العقاري في المملكة العربية السعودية.\n'
        'مهمتك إعداد دراسة سوق أولية استرشادية لفرصة عقارية، على أن يتغير التحليل '
        'والمؤشرات والمصادر والمنافسون حسب نوع المشروع.\n\n'
        'أولًا التعامل مع المنافسين:\n'
        'إذا طُلب إكمال بيانات المنافسين بالاسم:\n'
        '1. أبق كل صف موجود كما هو ولا تضف منافسًا جديدًا ولا تحذف أحدًا.\n'
        '2. املأ الحقول الناقصة فقط من مصادر موثوقة.\n'
        'إذا طُلب توليد المنافسين بالذكاء الاصطناعي:\n'
        '1. ابحث عن قائمة منافسين جديدة كاملة داخل النطاق المحدد.\n'
        '2. أعد قائمة جديدة تحل محل الجدول الحالي بالكامل.\n'
        '3. اختر المنافسين الأقرب من حيث: نوع الاستخدام، مستوى المشروع، الموقع، المساحات، الأسعار، حالة المشروع.\n'
        f'4. حاول توفير {COMPETITOR_MIN_DIRECT} منافسين مباشرين على الأقل إذا كانوا متاحين.\n'
        '   وللمشروع متعدد المحاور يكون هذا الحد لكل محور من محاور مكوناته على حدة، مع تعليم كل منافس بالمحور الذي يقيسه.\n'
        '5. إذا لم يتوفر العدد الكافي وسّع نطاق البحث تدريجيًا مع توضيح ذلك.\n'
        '6. صنّف المنافسين إلى: منافس مباشر، منافس غير مباشر، مشروع مرجعي.\n'
        '7. اذكر سبب اختيار كل منافس داخليًا في التحليل حتى لو لم يظهر عمود السبب في الجدول.\n'
        '8. لكل منافس أعد جميع روابط الصفحات التي استخدمت منها البيانات في source_urls، وليس رابطًا واحدًا فقط.\n'
        '9. مساحة الوحدة تكون area_mode=fixed مع area_sqm عندما يثبت المصدر قيمة واحدة، أو area_mode=range مع area_from وarea_to عندما يثبت المصدر نطاقًا؛ ولا تستخدم مساحة الأرض أو المبنى أو البرج أو المشروع الكلية.\n'
        '10. في الفندق استخدم مساحة الغرفة أو الجناح أو الشقة الفندقية، وإذا لم توجد مساحة وحدة موثوقة اترك area_sqm فارغة ولا تستخدم Tower GFA أو Gross Floor Area.\n'
        'إذا كان الطلب تحليلًا أو ملخصًا والسوق يعتمد على جدول المنافسين الحالي:\n'
        '1. اعتمد قائمة المنافسين الموجودة في الجدول ولا تحذف أي منافس منها.\n'
        '2. استخدم البيانات التي أدخلها العميل أو وُلدت سابقًا كأساس للتحليل.\n\n'
        'ثانيًا ترتيب أولوية المصادر:\n'
        'الموقع الرسمي للمشروع أو المطور مصدر موثوق لبيانات الجهة نفسها، وسجّل موثوقيته «مصدر رسمي للجهة».\n'
        + '\n\n'.join(source_blocks)
        + '\n\nيمكنك استخدام مواقع المشاريع نفسها إن وُجدت.'
        + '\n\nثالثًا التحليل حسب نوع المشروع:\n'
        + '\n\n'.join(type_blocks)
        + '\n\n' + mixed
        + '\n\nرابعًا مخرجات ملخص السوق — حقلا التحليل والملخص مختلفان:\n'
        f'ابدأ مخرجات الدراسة بعنوان: {SUMMARY_TITLE}.\n'
        'يجب أن يكون التحليل مخصصًا لنوع المشروع وليس وصفًا عامًا للمدينة.\n'
        'حقل summary هو تحليل السوق التفصيلي المنظم، وأعد فيه كل محور في قيمة مستقلة حسب الترتيب التالي:\n'
        + summary_spec
        + axes_sentence
        + one_block_sentence
        + 'بعد التحليل أعد تحليل SWOT مستقلًا للمشروع في السوق المحدد، من أربع خانات:\n'
        + '\n'.join(f'- {item["label"]}: {SWOT_SECTION_HINTS[item["key"]]}' for item in SWOT_SECTIONS)
        + '\nلا تخلط SWOT مع تحليل السوق. كل خانة نقاط قصيرة خاصة بهذا المشروع وهذا النوع.\n'
        'لا تستخدم وصفًا عامًا للمدينة بدل تحليل المشروع.\n\n'
        'خامسًا قواعد إلزامية:\n'
        + _format_list(MANDATORY_RULES)
        + '\nالدراسة أولية استرشادية وليست تقييمًا عقاريًا معتمدًا.'
    )


REVENUE_MODE_LABELS = {
    'sale': 'وحدات بيعية فقط',
    'rental': 'وحدات تأجيرية فقط',
    'mixed': 'مختلطة: وحدات بيعية ووحدات تأجيرية',
    'nonRevenue': 'بدون إيراد (مشروع غير بيعي ولا تأجيري)',
}
INVESTMENT_MODEL_LABELS = {
    'sale': 'بيع وحدات',
    'dailyRent': 'إيجار يومي',
    'monthlyRent': 'إيجار شهري',
    'annualRent': 'إيجار سنوي',
    'operating': 'تأجير/تشغيل آخر',
    'nonRevenue': 'بدون إيراد',
}


def _fmt_money(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return ''
    if not math.isfinite(num) or num <= 0:
        return ''
    if num >= 1_000_000:
        return f"{num / 1_000_000:,.1f} مليون ريال سعودي"
    return f"{num:,.0f} ريال سعودي"


def _fmt_area(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return ''
    if not math.isfinite(num) or num <= 0:
        return ''
    return f"{num:,.0f} م²"


def _fmt_pct(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return ''
    if not math.isfinite(num):
        return ''
    if abs(num) <= 1.5:
        num *= 100
    return f"{num:.1f}%"


def _fmt_years(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return ''
    if not math.isfinite(num) or num <= 0:
        return ''
    return f"{num:g} سنة"


def _fmt_count(value, prefix=''):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return ''
    if not math.isfinite(num) or num <= 0:
        return ''
    return f"{prefix}{num:g}"


def _financial_input_lines(payload):
    fin = payload.get('financial')
    if not isinstance(fin, dict):
        fin = payload.get('financial_model') if isinstance(payload.get('financial_model'), dict) else {}
    if not fin:
        return []
    mode = _norm(fin.get('unitRevenueMode'))
    rows = [
        ('إجمالي تكلفة المشروع', _fmt_money(fin.get('projectCost'))),
        ('التكلفة مع التمويل', _fmt_money(fin.get('projectCostWithFinance') or fin.get('adjustedProjectCost'))),
        ('إجمالي إيرادات البيع', _fmt_money(fin.get('saleRevenueTotal'))),
        ('إيراد التشغيل للسنة الأولى', _fmt_money(fin.get('revenueY1'))),
        ('صافي دخل التشغيل (NOI) للسنة الأولى', _fmt_money(fin.get('noiY1'))),
        ('الإيراد عند الإشغال الكامل', _fmt_money(fin.get('fullOccupancyRevenue'))),
        ('العائد على الاستثمار ROI', _fmt_pct(fin.get('roi'))),
        ('معدل العائد الداخلي للمشروع IRR', _fmt_pct(fin.get('projectIrr'))),
        ('معدل العائد الداخلي للملكية Equity IRR', _fmt_pct(fin.get('equityIrr'))),
        ('فترة استرداد رأس المال', _fmt_years(fin.get('payback'))),
        ('قيمة التخارج البيعي', _fmt_money(fin.get('saleExitValue'))),
        ('قيمة التخارج التشغيلي', _fmt_money(fin.get('operatingExitValue'))),
        ('مدة التطوير', _fmt_years(fin.get('developmentYears'))),
        ('سنة بدء البيع', _fmt_count(fin.get('salesStartYear'), prefix='السنة ')),
        ('سنوات التشغيل', _fmt_years(fin.get('operationYears'))),
        ('عدد الأدوار', _fmt_count(fin.get('floorCount'))),
        ('نسبة التغطية', _fmt_pct(fin.get('coverageRate'))),
        ('المساحة المبنية فوق الأرض', _fmt_area(fin.get('builtUpAreaAbove'))),
        ('مساحة القبو', _fmt_area(fin.get('basementArea'))),
    ]
    lines = [f"- {label}: {value}" for label, value in rows if value]
    if mode:
        lines.insert(0, f"- طبيعة الإيرادات: {REVENUE_MODE_LABELS.get(mode, mode)}")
    return lines


def _site_context_lines(payload):
    rows = []
    floors = payload.get('approvedFloorCount') or payload.get('approved_floor_count')
    coverage = payload.get('approvedCoverageRatio') or payload.get('approved_coverage_ratio')
    if floors:
        rows.append(f"- عدد الأدوار المعتمدة: {floors}")
    if coverage:
        rows.append(f"- نسبة تغطية البناء المعتمدة: {coverage}")
    floor_area_ratio = payload.get('approvedFloorAreaRatio') or payload.get('approved_floor_area_ratio')
    if floor_area_ratio:
        rows.append(f"- معامل مسطح البناء المعتمد (FAR): {floor_area_ratio}")
    setbacks = payload.get('setbacks')
    if isinstance(setbacks, str) and setbacks.strip():
        rows.append(f"- الارتدادات: {setbacks.strip()}")
    roads = payload.get('mainRoads') or payload.get('main_roads')
    if isinstance(roads, str) and roads.strip():
        rows.append(f"- الطرق الرئيسية المحيطة: {'، '.join(roads.splitlines()) if chr(10) in roads else roads}")
    landmarks = payload.get('nearbyLandmarks') or payload.get('nearby_landmarks')
    if isinstance(landmarks, list) and landmarks:
        rows.append(f"- المعالم القريبة: {'، '.join(str(item) for item in landmarks if item)}")
    elif isinstance(landmarks, str) and landmarks.strip():
        rows.append(f"- المعالم القريبة: {landmarks.strip()}")
    return rows


def _project_input_block(payload):
    components = payload.get('components')
    if isinstance(components, list) and components:
        components_text = json.dumps(components, ensure_ascii=False)
    else:
        components_text = str(
            payload.get('projectComponents')
            or payload.get('project_components')
            or 'غير مدخل'
        )
    audience = payload.get('targetAudience') or payload.get('target_audience') or []
    if isinstance(audience, list):
        audience_text = '، '.join(str(item) for item in audience if item)
    elif isinstance(audience, dict):
        audience_text = json.dumps(audience, ensure_ascii=False)
    else:
        audience_text = str(audience or '')
    lines = [
        f"- اسم المشروع: {payload.get('projectName') or payload.get('project_name') or 'غير مدخل'}",
        f"- نوع المشروع الرئيسي: {payload.get('projectType') or payload.get('project_type') or 'غير مدخل'}",
        f"- نوع المشروع الفرعي: {payload.get('projectSubtype') or payload.get('project_subtype') or 'غير مدخل'}",
        f"- المدينة: {payload.get('city') or 'غير مدخل'}",
        f"- الحي: {payload.get('district') or payload.get('neighborhood') or 'غير مدخل'}",
        f"- الإحداثيات: {payload.get('locationLat') or payload.get('location_lat') or ''} , {payload.get('locationLng') or payload.get('location_lng') or ''}",
        f"- مساحة الأرض: {payload.get('landArea') or payload.get('approved_financial_area') or payload.get('croquis_land_area') or 'غير مدخل'}",
        f"- مساحة البناء المتاحة: {payload.get('builtArea') or payload.get('built_area') or 'غير مدخل'}",
        f"- الأنشطة المسموح بها: {payload.get('allowedUses') or payload.get('allowed_uses') or 'غير مدخل'}",
        f"- المكونات الأولية: {components_text or payload.get('projectComponents') or payload.get('project_components') or 'غير مدخل'}",
        f"- مستوى المشروع: {payload.get('projectLevel') or payload.get('project_level') or 'غير مدخل'}",
        f"- الفئة المستهدفة: {audience_text or 'غير مدخل'}",
        f"- نطاق المنافسين (لجدول المنافسين فقط): {competitor_scope_text(payload)}",
        f"- نطاق الملخص (الملزم لمحاور الملخص): {summary_scope_label(normalize_summary_scope(payload.get('summaryScope') or payload.get('summary_scope')))}",
        f"- فترة البيانات المطلوبة: {payload.get('dataPeriodLabel') or payload.get('data_period') or 'غير مدخل'}",
        f"- فترة البيانات الملزمة (تاريخ نشر المصدر): {data_period_window_text(payload) or 'غير مقيدة'}",
    ]
    site_lines = _site_context_lines(payload)
    if site_lines:
        lines.append('### خصائص الأرض ومحيط الموقع')
        lines.extend(site_lines)
    financial_lines = _financial_input_lines(payload)
    if financial_lines:
        lines.append('### مؤشرات الدراسة المالية للمشروع (مدخلات موثقة — لا تخمّنها)')
        lines.extend(financial_lines)
        lines.append(
            '- مفتاح investmentModel في المكونات: ' +
            '، '.join(f'{key} = {label}' for key, label in INVESTMENT_MODEL_LABELS.items())
        )
    # Market-side calls are the only ones that see the whole project file —
    # every other flow gets a hand-picked slice, but a market study cannot
    # evaluate a project it cannot see. The server fills projectFacts with a
    # bounded, section-grouped brief; the chat and both research tasks share it.
    project_facts = _norm(payload.get('projectFacts'))
    if project_facts:
        lines.append('### سياق ملف المشروع الكامل — كل الأقسام المعبأة (سياق موثوق للفهم والربط)')
        lines.append(project_facts)
    return '\n'.join(lines)


def build_competitors_user_prompt(payload, existing_competitors, mode='generate', offer_lang='ar'):
    existing = existing_competitors if isinstance(existing_competitors, list) else []
    named = [row for row in existing if _norm(row.get('name'))]
    axes = project_competitor_axes(payload)
    axis_labels = [benchmark_axis_label(axis, offer_lang) for axis in axes]
    axis_list = '، '.join(axis_labels)
    multi_axis = len(axes) > 1
    needs_benchmarks = any(axis['key'] != 'general' for axis in axes)

    def is_complete(row):
        price_type = _norm(row.get('price_type'))
        price_complete = (bool(_norm(row.get('price_from'))) and bool(_norm(row.get('price_to')))
                          if price_uses_range(price_type) else bool(_norm(row.get('price_value'))))
        area_mode = 'range' if _norm(row.get('area_mode')) == 'range' or row.get('area_from') or row.get('area_to') else 'fixed'
        area_complete = (bool(_norm(row.get('area_from'))) and bool(_norm(row.get('area_to')))
                         if area_mode == 'range' else bool(_norm(row.get('area_sqm'))))
        return (all(_norm(row.get(key)) for key in (
            'project_type', 'status', 'classification', 'operation_type', 'price_type', 'source'
        )) and area_complete and price_complete
            and (not needs_benchmarks or bool(row.get('benchmarks'))))

    incomplete = [row for row in named if not is_complete(row)]
    today = date.today().isoformat()
    en = offer_lang == 'en'
    missing_phrase = MISSING_VALUE_PHRASE_EN if en else MISSING_VALUE_PHRASE
    enum = {
        'project_type': ' or '.join(COMPETITOR_PROJECT_TYPE_OPTIONS_EN) if en
        else 'سكني أو تجاري أو فندقي أو صناعي ولوجستي أو متعدد الاستخدامات أو أخرى',
        'status': ' or '.join(COMPETITOR_STATUS_OPTIONS_EN) if en
        else 'قائم أو تحت الإنشاء أو على الخارطة',
        'classification': ' or '.join(COMPETITOR_CLASS_OPTIONS_EN) if en
        else 'مباشر أو غير مباشر أو مرجعي',
        'operation_type': ' or '.join(COMPETITOR_OPERATION_OPTIONS_EN) if en
        else 'بيع أو إيجار أو تشغيل فندقي أو أخرى',
    }
    language_directive = (
        'OUTPUT LANGUAGE: this project is English. Author EVERY field value in '
        'professional English — status/classification/operation_type/price_type '
        'use exactly the allowed English values below; district, source, notes, '
        'data_date and expansionNote are written in English. Keep the competitor '
        'name verbatim in its source spelling.\n\n'
        if en else ''
    )
    benchmark_directive = (
        f'لكل منافس املأ benchmarks بقيمة أو أكثر حصرًا من محاور مشروعنا: {axis_list} — '
        'المحور الذي يقيسه المنافس من مكونات مشروعنا، والمنافس متعدد الاستخدامات يحمل أكثر من قيمة. '
        if needs_benchmarks else ''
    )
    if mode == 'fill':
        task = (
            'المستخدم كتب أسماء منافسين وطلب إكمال بياناتهم. '
            'أبق الاسم كما هو، ولا تحذف صفًا، واملأ الحقول الناقصة فقط من مصادر موثوقة. '
            'إن لم تجد معلومة اترك الحقل فارغًا أو اكتب غير متوفر من مصدر موثوق في المصدر.'
            + benchmark_directive
        )
    else:
        axis_requirement = (
            f'المشروع متعدد المحاور — أرجع {COMPETITOR_MIN_DIRECT} منافسين مباشرين على الأقل '
            f'لكل محور ({"، ".join(f"{label}: {COMPETITOR_MIN_DIRECT}" for label in axis_labels)}) إن أمكن. '
            if multi_axis else
            f'أرجع {COMPETITOR_MIN_DIRECT} منافسين مباشرين على الأقل إن أمكن. '
        )
        task = (
            'ولّد قائمة منافسين جديدة كاملة تحل محل الجدول الحالي. '
            + axis_requirement + benchmark_directive +
            'اقتصر على مشاريع مذكورة بالاسم في صفحات نتائج البحث المسترجعة — ابحث عن قوائم '
            'ومقالات وصفحات مطوّرين تسمّي مجمعات ومشاريع حقيقية في المدينة، ولا تكتب اسمًا '
            'من ذاكرتك: كل صف يُفحص آليًا، وأي اسم لا يظهر في أي صفحة مسترجعة يُعلَّم '
            'كغير موثق ولا يُعتمد. إن لم يكفِ العدد داخل النطاق، وسّع البحث تدريجيًا '
            'واذكر ذلك في notes. صنف كل منافس: مباشر أو غير مباشر أو مرجعي.'
        )
    price_types = '\n'.join(
        f'- {operation}: ' + ', '.join(options)
        for operation, options in (
            PRICE_TYPE_BY_OPERATION_EN if en else PRICE_TYPE_BY_OPERATION
        ).items()
    )
    search_protocol = (
        'بروتوكول البحث الإلزامي:\n'
        '1. ابحث أولًا عن قائمة المنافسين في المدينة والنطاق المطلوب — صفحات القوائم '
        'ومقالات «أفضل المجمعات/المشاريع» ومواقع المطوّرين هي التي تسمّي المشاريع '
        'بأسمائها. اسم كل منافس يجب أن يظهر حرفيًا في صفحة مسترجعة، ورابط تلك الصفحة '
        'يوضع في source_urls للصف.\n'
        '2. ثم نفّذ بحثًا منفصلًا لكل منافس على حدة عن سعره الفعلي '
        '(سعر البيع أو المتر أو الإيجار أو سعر الليلة أو ADR حسب نوع التشغيل) '
        'باستخدام اسم المنافس مع المدينة. أي صفحة مسترجعة تذكر المنافس بالاسم '
        'وتحمل بياناته مصدر مقبول لصفّه — موقع المطور أو المشغل، إعلان على منصة '
        'عقار (sa.aqar.fm) — وهي منصة الإعلانات الوحيدة المقبولة — أو تريفاجو '
        'للمنافس الفندقي، والأخبار والتقارير — ولا يُشترط مصدر رسمي لكل حقل. '
        'روابط منصات الإعلانات الأخرى (bayut.sa، wasalt.sa، dealapp.sa، dubizzle '
        'وغيرها) ممنوعة وتُسقط آليًا من الصف، وكذلك روابط التواصل الاجتماعي '
        '(إنستغرام، فيسبوك، تيك توك، إكس، يوتيوب وغيرها) — ليست مصدرًا للمنافس '
        'ولا لسعره.\n'
        '3. area_sqm هي مساحة الوحدة القابلة للبيع أو الإيجار أو الوحدة النموذجية، مثل مساحة الشقة أو الفيلا أو المكتب أو المحل أو الغرفة أو الجناح أو المستودع. '
        'لا تستخدم مساحة الأرض أو مساحة البناء الكلية أو Tower GFA أو Gross Floor Area أو مساحة البرج أو المشروع. '
        'إذا وجدت فقط المساحة الإجمالية اترك area_sqm فارغة واكتب السبب في notes.\n'
        '4. لا تكتب سعرًا من معرفتك السابقة. السعر يُقبل فقط إذا ورد في صفحة قرأتها في هذا البحث، '
        'ويجب أن يكون رابط تلك الصفحة نفسها في source_url، مع إدراج كل الصفحات المستخدمة للمنافس في source_urls.\n'
        f'5. إذا لم تجد سعرًا بعد البحث اترك حقول السعر فارغة واكتب في source عبارة {missing_phrase} '
        'مع بيان ما بحثت عنه في notes. الصف الناقص السعر مقبول؛ الرقم المختلق مرفوض.\n'
        '6. املأ price_type من القائمة المسموحة لنوع التشغيل، واستخدم price_from و price_to لأنواع النطاق '
        f'({", ".join(sorted(RANGE_PRICE_TYPES_EN) if en else sorted(RANGE_PRICE_TYPES))}) و price_value لغيرها.\n'
        'اكتب في price_currency عملة السعر كما ظهرت في الصفحة (SAR للريال): إذا سعّرت '
        'الصفحة بعملة أخرى — كأسعار منصات الحجز باليورو أو الدولار — اكتب رمزها في '
        'price_currency ولا تحوّلها ولا تسقط السعر لأجل عملته؛ وسعر ليلة معروض على '
        'تريفاجو — منصة الحجز الوحيدة المقبولة — يُقبل لنوع تشغيل فندقي مع ذكر '
        'المصدر والتاريخ في notes.\n'
        '7. النطاق الجغرافي ملزم: ابحث عن منافسين داخل النطاق المكتوب في بيانات المشروع فقط. '
        'لكل منافس اكتب حيه في district ومسافته التقريبية من موقع المشروع بالكيلومتر في distance_km '
        'وإحداثياته في lat وlng إن ظهرت في المصدر. '
        'district وdistance_km وlat وlng تقديرات جغرافية تكتبها أنت من اسم المنافس وحيه — '
        'لا تُشترط صفحة تذكر المسافة أو الإحداثيات حرفيًا، فنادرًا ما تُكتب في المصادر. '
        'مشروع مسمّى داخل حي المشروع أو حي مجاور يُحسب داخل النطاق، وإن قدّرت مسافته أكبر '
        'من النطاق فأدرجه مع المسافة الحقيقية بدل حذفه — الصفوف الخارجة تُعلَّم للمراجعة '
        'ولا يُحذف منافس لأن مصدره لم يكتب مسافة. '
        'إن لم يكفِ عدد المنافسين داخل النطاق وسّع البحث تدريجيًا وفعّل searchExpanded '
        'واذكر أقصى مسافة وصلت إليها في expansionNote.\n'
        '8. فترة البيانات الملزمة مكتوبة في بيانات المشروع: ارفض أي سعر أو مساحة مصدرها أقدم من '
        'بداية الفترة، واكتب تاريخ البيانات التي وجدتها لكل صف داخل notes.\n'
        '9. مصادر المؤشرات الرسمية إلزامية عند الارتباط: إن كان المشروع أو أي من منافسيه '
        'للإيجار فابحث في المؤشر التفصيلي لسوق الإيجار من سكني '
        '(site:sakani.sa/reports-and-data) واسحب جداول الوحدات السكنية أو التجارية أو '
        'كلتيهما حسب مكونات المشروع. واستخدم صفحة مدينة المشروع في منصة المؤشرات '
        'العقارية (rei.rega.gov.sa/ar/cities) كمرجعية رسمية لعدد صفقات المدينة '
        'وقيمتها والحي الأكثر نشاطًا — صفحات البحث المتقدم في المنصة تتطلب دخول '
        'نفاذ فلا تعتمد عليها. هذه المرجعية '
        'لسياق السوق؛ أما مصادر صفوف المنافسين فيقبل فيها أي موقع يذكر المشروع '
        'بالاسم — إعلانًا تفصيليًا على عقار أو تريفاجو للفندقي، خبرًا أو تقريرًا '
        'أو موقع مطوّر — ولا يقبل فيها إعلان على أي منصة أخرى.\n'
        '10. طبيعة الإيرادات في بيانات المشروع ملزمة ولا تخمَّن: المشروع البيعي يقارَن بمنافسين '
        'بيعيين (سعر وحدة/متر)، والتأجيري بتأجيريين (إيجار/ليلة/ADR حسب نموذج الاستفادة)، '
        'والمختلط يقارَن بالنوعين مع مطابقة كل منافس لنموذج استفادة مكوّنه.\n'
        '11. المنافس مشروع حقيقي مسمّى (برج، مجمع سكني، مشروع مطوّر معلن). صفحات المؤشرات '
        'الرسمية (سكني، شبكة إيجار، منصة المؤشرات العقارية) ومواقع البيانات الإجمالية ليست '
        'منافسين: استخدمها مصدرَ سعر داخل source_urls للصفوف الحقيقية وفي مصادر الملخص، '
        'ولا تُنشئ صف منافس باسم مؤشر أو صفحة بيانات إحصائية. ويجب أن يحمل source_urls '
        'كل منافس صفحةً تخص المشروع نفسه — موقع المطور أو المشغل أو إعلانًا تفصيليًا '
        'يذكره بالاسم — فروابط المؤشرات العامة وحدها لا توثّق هوية المنافس ولا سعره.\n'
        'أنواع السعر المسموحة حسب نوع التشغيل:\n'
        f'{price_types}\n'
    )
    return (
        language_directive +
        f'تاريخ اليوم: {today}\n'
        f'المهمة: {task}\n\n'
        f'{search_protocol}\n'
        'بيانات المشروع:\n'
        f'{_project_input_block(payload)}\n\n'
        + (
            'المنافسون الحاليون (أبقهم جميعًا واملأ الناقص فقط):\n'
            if mode == 'fill' else
            'المنافسون الحاليون للسياق فقط. أعد قائمة جديدة تحل محلهم بالكامل:\n'
        )
        + f'{json.dumps(existing, ensure_ascii=False, indent=2)}\n\n'
        'الصفوف التي تحتاج إكمالًا إن وُجدت:\n'
        f'{json.dumps(incomplete, ensure_ascii=False, indent=2)}\n\n'
        'أرجع JSON فقط بهذا الشكل:\n'
        '{\n'
        '  "competitors": [\n'
        '    {\n'
        '      "id": "أبق المعرف إن وُجد وإلا اتركه فارغًا",\n'
        '      "name": "",\n'
        f'      "project_type": "{enum["project_type"]}",\n'
        '      "area_mode": "fixed أو range حسب المصدر",\n'
        '      "area_sqm": "القيمة الثابتة أو فارغ للنطاق",\n'
        '      "area_from": "بداية النطاق أو فارغ للقيمة الثابتة",\n'
        '      "area_to": "نهاية النطاق أو فارغ للقيمة الثابتة",\n'
        f'      "status": "{enum["status"]}",\n'
        f'      "classification": "{enum["classification"]}",\n'
        f'      "benchmarks": ["{axis_labels[0]}"]' + (f' — قيم حصرية من: {axis_list}' if needs_benchmarks else '') + ',\n'
        f'      "operation_type": "{enum["operation_type"]}",\n'
        '      "price_type": "",\n'
        '      "price_currency": "SAR",\n'
        '      "price_value": "",\n'
        '      "price_from": "",\n'
        '      "price_to": "",\n'
        '      "source": "",\n'
        '      "source_url": "",\n'
        '      "source_urls": [],\n'
        '      "district": "حي المشروع المنافس",\n'
        '      "distance_km": "المسافة التقريبية من موقع المشروع بالكيلومتر — رقم",\n'
        '      "lat": "خط العرض أو فارغ",\n'
        '      "lng": "خط الطول أو فارغ",\n'
        '      "logo_url": "رابط صورة الشعار من الموقع الرسمي فقط أو فارغ",\n'
        '      "logo_source_url": "صفحة الموقع الرسمي التي تثبت الشعار أو فارغ",\n'
        '      "field_sources": {"name": [], "project_type": [], "district": [], "distance_km": [], "area_sqm": [], "area_from": [], "area_to": [], "status": [], "classification": [], "operation_type": [], "price_type": [], "price_value": [], "price_from": [], "price_to": [], "logo_url": []},\n'
        '      "data_date": "تاريخ بيانات الصف كما ورد في المصدر — سنة أو شهر/سنة",\n'
        '      "notes": "",\n'
        '      "row_source": "ai"\n'
        '    }\n'
        '  ],\n'
        '  "searchExpanded": false,\n'
        '  "expansionNote": "",\n'
        '  "notes": ""\n'
        '}\n'
        'أعد كل المفاتيح المذكورة لكل منافس ولا تحذف operation_type أو price_type أو price_value أو price_from أو price_to. '
        'إذا وجدت سعرًا في البحث فأعد operation_type وprice_type والقيمة أو النطاق وprice_currency معًا، ولا تترك أيًا منها فارغًا. '
        'إذا لم تجد سعرًا اترك حقول السعر فارغة واذكر المصدر إن وُجد.\n'
        'في source_urls ضع كل روابط الصفحات التي قرأتها واستخدمت منها أي معلومة لهذا المنافس، رابطًا لكل صفحة، '
        'ولا تكتف برابط واحد إذا استخدمت أكثر من صفحة. اجعل source_url هو الرابط الأهم للتوافق مع البيانات القديمة. '
        'في field_sources اربط كل حقل أعدت له قيمة بروابط الصفحات التي تثبته، وبالأخص area_sqm، area_from، area_to، status، classification، operation_type، price_type، price_value، price_from، price_to، وlogo_url. '
        'أما district وdistance_km وlat وlng فهي تقديراتك الجغرافية — اربطها بالصفحة التي تسمّي المنافس إن وُجدت وإلا اتركها بلا رابط، ولا ترفض صفًا لأن المسافة أو الإحداثيات بلا مصدر مكتوب. '
        'logo_url مقبول فقط عندما يكون logo_source_url صفحة رسمية للمشروع أو المطور، وإلا اترك الحقلين فارغين. '
        'اجعل source_urls اتحاد جميع روابط field_sources. '
        'في source_url وsource_urls ضع روابط الصفحات المحددة من نتائج البحث، وليس رابط الصفحة الرئيسية للموقع. '
        'رابط النطاق وحده أو الصفحة الرئيسية غير مقبول؛ إن لم تتوفر صفحة محددة '
        f'اترك source_url وsource_urls فارغين واكتب في source عبارة {missing_phrase}.'
    )


def _summary_scope_block(payload, offer_lang=None):
    """The binding geographic frame of the market summary, per its own scope
    mode — separate from the competitors radius. 'distance' binds to the
    summary's own distance setting (district plus that distance); 'city' /
    'district' bind the analysis to the user-entered place list instead,
    with the same listed-only discipline and no invented substitutes. The
    competitors radius never widens the summary frame."""
    en = (offer_lang == 'en')
    scope = normalize_summary_scope(
        (payload or {}).get('summaryScope') or (payload or {}).get('summary_scope'))
    mode = scope.get('mode')
    scope_label = summary_scope_label(scope)
    if mode in ('city', 'district'):
        places = '، '.join(scope.get('places') or [])
        if en:
            unit = 'cities' if mode == 'city' else 'districts'
            single = 'city' if mode == 'city' else 'district'
            return (
                f'The binding summary scope is these {unit} only: {places}. '
                f'Analyze each {single} by name inside the relevant axes — never mix '
                f'one {single}\'s figures into another\'s. Every figure, deal and price '
                f'must belong to one of these {unit} exclusively; a source describing '
                f'any other place is excluded. Do not analyze unlisted {unit} and do not '
                f'invent substitutes — if a {single} has no data for an axis, write that '
                f'the data is unavailable. This rule overrides any axis hint about the project district, '
                f'the competitors radius, or a single nearest-district fallback. In market_definition, '
                f'state these {unit} by name as the market and never cite the competitors scope there. '
                f'Country-level figures may appear only as '
                f'clearly-labeled background, never as the basis of a judgment on '
                f'this project\'s market.\n'
            )
        unit = 'المدن' if mode == 'city' else 'الأحياء'
        single = 'مدينة' if mode == 'city' else 'حي'
        return (
            f'نطاق الملخص المحدد ملزم في كل محاور التحليل: سوق هذا المشروع هو '
            f'هذه {unit} وحدها: {places}. حلل كل {single} باسمها داخل المحاور ذات '
            f'الصلة — لا تخلط أرقام {single} بأخرى. كل رقم أو صفقة أو سعر يجب أن '
            f'يخص واحدة من هذه {unit} حصرًا، والمصدر الذي يصف مكانًا خارجها '
            f'يُستبعد. لا تحلل {unit} غير مدخلة ولا تخترع بدائل من عندك — وإن لم '
            f'تتوفر بيانات {single} لمحور فاكتب أنها غير متوفرة. هذه القاعدة تلغي ما يخالفها في وصف المحاور '
            f'(تعريف السوق وأداء القطاع): لا تستخدم حي المشروع ولا نطاق المنافسين كنطاق للتحليل ولا قاعدة الحي الأقرب الوحيد. '
            f'وفي محور تعريف السوق اذكر هذه {unit} بالاسم كنطاق السوق ولا تذكر نطاق المنافسين هناك. '
            f'أرقام المملكة '
            f'العامة تصلح خلفيةً مذكورة صراحةً فقط، ولا تُبنى عليها أحكام سوق '
            f'المشروع.\n'
        )
    scope_suffix = f' ({scope_label})' if scope_label else ''
    return (
        'The geographic scope is binding on every axis: this project\'s market is the district '
        f'entered in the project data and the summary scope{scope_suffix} stated here (or the stated summary '
        'scope alone when no district is entered). The competitors scope in the project data covers '
        'the competitors table only and never widens this summary frame. Do not analyze distant districts or wider areas — '
        'not in sector performance, supply, demand, competition or the market gap. Only if the '
        'project scope has too little data to read an axis may you extend to ONE single '
        'substitute: the district physically closest to the project location. At most one '
        'neighboring district may appear in the whole output — the same closest district '
        'wherever in-scope data is missing; naming two different neighboring districts is '
        'forbidden. If that closest district also lacks data for an axis, write that the data '
        'is unavailable — do not move on to a second district. State the fallback openly in '
        'the axis, e.g. "the entered district lacks data on X; figures shown are from district '
        'Y, the nearest area to the site". Never jump to farther areas just because they '
        'publish more data, and never present a neighboring district\'s figures as if they '
        'were the project district\'s own. Every figure, deal and price must belong to that '
        'scope or its single nearest substitute; a source describing any other district is '
        'excluded. City-level figures may appear only as clearly-labeled background, never '
        'as the basis of a judgment on this project\'s market. In market_definition, state the entered district '
        'with its summary scope and never cite the competitors scope as the market.\n'
        if en else
        'النطاق الجغرافي ملزم في كل محاور التحليل: سوق هذا المشروع هو الحي المدخل في بيانات '
        f'المشروع ونطاق الملخص المحدد هنا{(" (" + scope_label + ")") if scope_label else ""} (أو نطاق الملخص وحده إن لم يُدخل حي). نطاق المنافسين في بيانات المشروع يخص جدول المنافسين فقط ولا يوسع نطاق الملخص. لا تحلل '
        'أحياء بعيدة ولا نطاقات أوسع من المدخل — لا في أداء القطاع ولا في العرض أو الطلب أو '
        'المنافسة أو الفجوة. وإن لم توجد داخل نطاق المشروع بيانات كافية لقراءة محور، وسّع إلى '
        'بديل واحد فقط: أقرب حي لموقع المشروع فعليًا. الحد الأقصى حي مجاور واحد في المخرجات '
        'كلها — نفس الحي الأقرب أينما نقصت البيانات، وذكر حيين مجاورين مختلفين ممنوع. وإن لم '
        'يتوفر لدى أقرب حي بيانات المحور أيضًا فاكتب أنها غير متوفرة — لا تنتقل إلى حي ثانٍ. '
        'واكتب الاستعانة صراحةً داخل المحور، مثل: «لم تتوفر داخل حي المشروع بيانات عن كذا؛ '
        'والأرقام المعروضة من حي كذا كأقرب نطاق لموقع المشروع» — ولا تقفز إلى مناطق أبعد '
        'لمجرد توفر بياناتها، ولا تعرض أرقام حي مجاور على أنها أرقام حي المشروع نفسه. كل رقم '
        'أو صفقة أو سعر يجب أن يخص نفس النطاق أو بديله الأقرب الوحيد، والمصدر الذي يصف أي '
        'حي آخر يُستبعد. أرقام المدينة العامة تصلح خلفيةً مذكورة صراحةً فقط، ولا تُبنى عليها '
        'أحكام سوق المشروع. وفي محور تعريف السوق اذكر الحي المدخل ونطاق الملخص الخاص به ولا تذكر نطاق المنافسين كنطاق السوق.\n'
    )


def build_summary_user_prompt(payload, competitors, current_summary=None, current_sources=None, current_swot=None, offer_lang=None):
    en = (offer_lang == 'en')
    today = date.today().isoformat()
    section_keys = ', '.join(item['key'] for item in SUMMARY_SECTIONS)
    swot_keys = ', '.join(item['key'] for item in SWOT_SECTIONS)
    if en:
        shape_example = (
            '  "summary": {\n'
            '    "market_definition": "Market-definition axis analysis",\n'
            '    "city_position": "City-position axis analysis",\n'
            '    "sector_performance": "Sector-performance axis analysis",\n'
            '    "supply": "Supply axis analysis",\n'
            '    "demand": "Demand axis analysis",\n'
            '    "competition": "Competition axis analysis",\n'
            '    "market_gap": "Market-gap axis analysis",\n'
            '    "project_evaluation": "Unbiased project-evaluation axis analysis",\n'
            '    "recommendation": "Recommendation axis analysis",\n'
            '    "risks": "Risks axis analysis"\n'
            '  },\n'
        )
        decision_example = '"decision": "A value from the decision list",\n'
        disclaimer_example = '"disclaimer": "This is a preliminary indicative study, not a certified valuation appraisal",\n'
        one_block_example = '"one_block_summary": "One cohesive English paragraph covering the full project market, no headings, numbering or lists"\n'
    else:
        shape_example = (
            '  "summary": {\n'
            '    "market_definition": "تحليل محور تعريف السوق",\n'
            '    "city_position": "تحليل محور وضع المدينة",\n'
            '    "sector_performance": "تحليل محور أداء القطاع",\n'
            '    "supply": "تحليل محور العرض",\n'
            '    "demand": "تحليل محور الطلب",\n'
            '    "competition": "تحليل محور المنافسة",\n'
            '    "market_gap": "تحليل محور الفجوة السوقية",\n'
            '    "project_evaluation": "تحليل محور تقييم المشروع",\n'
            '    "recommendation": "تحليل محور التوصية",\n'
            '    "risks": "تحليل محور المخاطر"\n'
            '  },\n'
        )
        decision_example = '"decision": "قيمة من قائمة القرار",\n'
        disclaimer_example = '"disclaimer": "هذه دراسة أولية استرشادية وليست تقييمًا عقاريًا معتمدًا",\n'
        one_block_example = '"one_block_summary": "فقرة عربية واحدة متماسكة تلخص سوق المشروع كاملًا بلا عناوين ولا ترقيم ولا نقاط"\n'
    if en:
        search_protocol = (
            'Mandatory search protocol (native Google search):\n'
            '1. Search through native Google search first — never answer from memory: run a separate '
            'search for each axis group (city sale deals and indicators, '
            'rent index, supply and demand with listings, competition and news) '
            'using the city, district and project type, and base every figure on its results.\n'
            '2. Approximate figures from the search results are acceptable — no exact official '
            'figure is required — but every figure must come from the search, never from prior '
            'knowledge; a missing figure stays unavailable instead of an invented number.\n'
            '3. Put the result pages underpinning each figure in the sources table with their '
            'data_date; bare homepages alone are not acceptable.\n'
        )
    else:
        search_protocol = (
            'بروتوكول البحث الإلزامي (بحث جوجل الأصلي):\n'
            '1. ابحث عبر بحث جوجل الأصلي أولًا — لا تجب من الذاكرة: نفّذ بحثًا منفصلًا '
            'لكل مجموعة محاور (صفقات البيع ومؤشرات المدينة، مؤشر الإيجار، العرض '
            'والطلب والقوائم، المنافسة والأخبار) باسم المدينة والحي ونوع المشروع، '
            'وابنِ كل رقم على نتائجه.\n'
            '2. الأرقام التقريبية من نتائج البحث مقبولة — لا يُشترط رقم رسمي مطابق — '
            'لكن كل رقم يجب أن يأتي من البحث لا من معرفتك السابقة، والمعلومة الغائبة تبقى '
            '«غير متوفر من مصدر موثوق» بدل الرقم المختلق.\n'
            '3. ضع في جدول sources روابط صفحات النتائج التي استند إليها كل رقم مع data_date؛ '
            'روابط الصفحة الرئيسية وحدها غير مقبولة.\n'
        )
    return (
        f'تاريخ اليوم / تاريخ الوصول للمصادر: {today}\n'
        f'ابدأ المخرجات بعنوان: {SUMMARY_TITLE}.\n'
        + search_protocol
        + ('Write the detailed market analysis inside summary as organized axes, one independent value per axis, specific to this project — not a generic city description.\n'
           if en else
           'اكتب تحليل السوق التفصيلي داخل summary على شكل محاور منظمة، قيمة مستقلة لكل محور، مع تحليل خاص بهذا المشروع وليس وصفًا عامًا للمدينة.\n')
         + f'المفاتيح الإلزامية لمحاور summary بالترتيب: {section_keys}.\n'
         + ('Cover each axis with the brief elements, using short bullets inside an axis value when needed. Never put the detailed analysis in one paragraph or mix its axes.\n'
            if en else
            'غطِّ في كل محور عناصر brief النظام، واستخدم نقاطًا قصيرة داخل قيمة المحور عند الحاجة. لا تضع تحليل السوق التفصيلي في فقرة واحدة ولا تخلط محاوره.\n')
         + _summary_scope_block(payload, offer_lang)
         + 'كل رقم يجب أن يظهر أيضًا في جدول المصادر.\n'
        + ('Never name sources, websites or bodies inside the axis values or inside '
           'one_block_summary — no "according to", "per", "source:" or site-name mentions in the '
           'text at all; sources are only collected into the sources table, which is already '
           'displayed beneath the summary.\n'
           if en else
           'ممنوع ذكر المصادر أو أسماء المواقع أو الجهات داخل نص المحاور وداخل one_block_summary — '
           'لا «وفقًا» ولا «بحسب» ولا «المصدر» ولا اسم موقع في النص إطلاقًا؛ المصادر تُجمّع في '
           'جدول sources فقط وهي ظاهرة تحت الملخص أصلًا.\n')
        + 'البعد الزمني ملزم في التحليل: لكل محور اربط القراءة بثلاث نقاط — ماضٍ داخل '
        + 'فترة البيانات المحددة (اتجاه الأسعار والطلب والمعروض عبرها)، وحاضر كما هو '
        + 'اليوم، ومستقبل متوقع حتى سنة بدء التشغيل المدخلة في بيانات المشروع. لا '
        + 'تكتفِ بوصف الوضع الراهن، ولا تكرر عبارات عامة عن السوق.\n'
        + 'محور تقييم المشروع ملزم بالحياد الكامل: قيّم المشروع كما أُدخل — مكوناته '
        + 'ونموذج استفادته وتكلفته وعوائده المدخلة — مقابل أرقام السوق الموثقة، ولا '
        + 'تفترض أن المدخل هو الأنسب. قارن نماذج الاستفادة البديلة (بيع، إيجار سنوي '
        + 'أو شهري أو يومي، تشغيل فندقي، مختلط) وحدد صراحةً أين تكمن فرصة الربح '
        + 'الفعلية وأي نموذج أعلى جدوى ولو كان مختلفًا عما أدخله المستخدم، مع السبب '
        + 'والأرقام. إن كان النموذج المدخل أضعف من بديل فاذكر ذلك صراحةً.\n'
        + 'مصادر المؤشرات الرسمية إلزامية عند الارتباط: لمؤشرات البيع وصفقات المدينة استخدم '
        + 'صفحة مدينة المشروع في منصة المؤشرات العقارية (rei.rega.gov.sa/ar/cities — عدد '
        + 'الصفقات وقيمتها والحي الأكثر نشاطًا)، ولمؤشرات الإيجار استخدم المؤشر التفصيلي '
        + 'لسوق الإيجار من سكني (site:sakani.sa/reports-and-data) — جداول '
        + 'الوحدات السكنية أو التجارية أو كلتيهما حسب مكونات المشروع. صفحات البحث '
        + 'المتقدم في rei.rega.gov.sa تتطلب دخول نفاذ فلا تعتمد عليها.\n'
        + 'فترة البيانات الملزمة مكتوبة في بيانات المشروع: كل رقم أو مؤشر يجب أن يأتي من مصدر '
        + 'نُشر داخل تلك الفترة، ويُكتب تاريخ بياناته في data_date بصيغة YYYY-MM-DD أو YYYY-MM أو سنة. '
        + 'أي مصدر خارج الفترة غير مقبول — لا تستخدمه ولا تدرجه في sources.\n'
        + f'إذا لم تتوفر معلومة فاكتب داخل المحور: {MISSING_VALUE_PHRASE}.\n'
        'حقل القرار يجب أن يكون قيمة واحدة فقط من: '
        + '، '.join(DECISION_OPTIONS)
        + '. لا تختر «البيانات غير كافية» إلا إذا تعذر كتابة أغلب المحاور فعلًا؛ '
        + 'وجود منافسين وأسعار ومصادر في الجدول يعني أن البيانات كافية لتصنيف حقيقي.\n'
        + ('After the market-analysis axes, write an independent SWOT in four cells: Strengths, Weaknesses, Opportunities, Threats.\n'
           if en else
           'بعد محاور تحليل السوق اكتب تحليل SWOT مستقلًا من أربع خانات: نقاط القوة، نقاط الضعف، الفرص، التهديدات.\n')
        + 'اجعل كل خانة نقاطًا قصيرة خاصة بهذا المشروع وهذا النوع، ولا تكرر التحليل حرفيًا.\n'
        + (f'Write one_block_summary as {SUMMARY_TITLE}: one cohesive, polished English paragraph covering the full project market in about {SUMMARY_WORD_TARGET} words, never fewer than {SUMMARY_MIN_WORDS} words and no more than 400 words. Not a short multi-sentence abstract; cover market definition, city position, sector performance, supply, demand, competition, market gap, recommendation and decision conditions in a sequenced analysis. No subheadings, numbering or lists; use only the existing facts, figures and sources, with no SWOT and no sources list.\n\n'
           if en else
           f'اكتب one_block_summary باعتباره {SUMMARY_TITLE}: فقرة عربية واحدة محترمة ومتماسكة تلخص سوق المشروع كاملًا، في حدود {SUMMARY_WORD_TARGET} كلمة، على ألا تقل عن {SUMMARY_MIN_WORDS} كلمة وألا تتجاوز 400 كلمة. لا تكتب خلاصة قصيرة من عدة جمل؛ اشرح داخل الفقرة تعريف السوق ووضع المدينة وأداء القطاع والمعروض والطلب والمنافسة والفجوة السوقية وتقييم المشروع والتوصية وشروط القرار، واربطها بتحليل متسلسل. بلا عناوين فرعية ولا ترقيم ولا نقاط، واستخدم الحقائق والأرقام والمصادر الموجودة فقط، ولا تضع فيها SWOT أو قائمة مصادر.\n\n')
        + 'بيانات المشروع:\n'
        f'{_project_input_block(payload)}\n\n'
        'المنافسون المعتمدون في الجدول:\n'
        f'{json.dumps(competitors or [], ensure_ascii=False, indent=2)}\n\n'
        'تحليل السوق الحالي إن وُجد (للسياق فقط، أعد كتابة المحاور كاملة):\n'
        f'{json.dumps(current_summary, ensure_ascii=False) if isinstance(current_summary, (dict, list)) else str(current_summary or "")}\n\n'
        'مصادر حالية إن وُجدت (للسياق فقط، أعد بناء جدول المصادر كاملًا مع كل رقم):\n'
        f'{json.dumps(current_sources or [], ensure_ascii=False)}\n\n'
        'تحليل SWOT حالي إن وُجد (للسياق فقط، أعد كتابته كاملًا):\n'
        f'{json.dumps(current_swot or {}, ensure_ascii=False)}\n\n'
        'أرجع JSON فقط بهذا الشكل:\n'
        '{\n'
        f'  "title": "{SUMMARY_TITLE}",\n'
        + shape_example
        + f'  "swot": {{ مفاتيح إلزامية: {swot_keys} }},\n'
        + decision_example
        + '  "sources": [\n'
        '    {"name": "", "url": "", "data_date": "", "accessed_at": "' + today + '", "reliability": "", "note": ""}\n'
        '  ],\n'
        + disclaimer_example
        + one_block_example
        + '}\n'
        'في url ضع رابط الصفحة المحددة التي ظهر فيها الرقم أو المعلومة، وليس رابط الصفحة الرئيسية للموقع.\n'
    )


