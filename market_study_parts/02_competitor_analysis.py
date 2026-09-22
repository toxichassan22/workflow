

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
        return f"{num / 1_000_000:,.1f} مليون ريال"
    return f"{num:,.0f} ريال"


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
        rows.append(f"- نسبة التغطية المعتمدة: {coverage}")
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
        f"- نطاق المنافسين: {competitor_scope_text(payload)}",
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
    return '\n'.join(lines)


def build_competitors_user_prompt(payload, existing_competitors, mode='generate'):
    existing = existing_competitors if isinstance(existing_competitors, list) else []
    named = [row for row in existing if _norm(row.get('name'))]

    def is_complete(row):
        price_type = _norm(row.get('price_type'))
        price_complete = (bool(_norm(row.get('price_from'))) and bool(_norm(row.get('price_to')))
                          if price_uses_range(price_type) else bool(_norm(row.get('price_value'))))
        area_mode = 'range' if _norm(row.get('area_mode')) == 'range' or row.get('area_from') or row.get('area_to') else 'fixed'
        area_complete = (bool(_norm(row.get('area_from'))) and bool(_norm(row.get('area_to')))
                         if area_mode == 'range' else bool(_norm(row.get('area_sqm'))))
        return all(_norm(row.get(key)) for key in (
            'project_type', 'status', 'classification', 'operation_type', 'price_type', 'source'
        )) and area_complete and price_complete

    incomplete = [row for row in named if not is_complete(row)]
    today = date.today().isoformat()
    if mode == 'fill':
        task = (
            'المستخدم كتب أسماء منافسين وطلب إكمال بياناتهم. '
            'أبق الاسم كما هو، ولا تحذف صفًا، واملأ الحقول الناقصة فقط من مصادر موثوقة. '
            'إن لم تجد معلومة اترك الحقل فارغًا أو اكتب غير متوفر من مصدر موثوق في المصدر.'
        )
    else:
        task = (
            'ولّد قائمة منافسين جديدة كاملة تحل محل الجدول الحالي. '
            f'أرجع {COMPETITOR_MIN_DIRECT} منافسين مباشرين على الأقل إن أمكن. '
            'اقتصر على مشاريع مذكورة بالاسم في صفحات نتائج البحث المسترجعة — ابحث عن قوائم '
            'ومقالات وصفحات مطوّرين تسمّي مجمعات ومشاريع حقيقية في المدينة، ولا تكتب اسمًا '
            'من ذاكرتك: كل صف يُفحص آليًا، وأي اسم لا يظهر في أي صفحة مسترجعة يُعلَّم '
            'كغير موثق ولا يُعتمد. إن لم يكفِ العدد داخل النطاق، وسّع البحث تدريجيًا '
            'واذكر ذلك في notes. صنف كل منافس: مباشر أو غير مباشر أو مرجعي.'
        )
    price_types = '\n'.join(
        f'- {operation}: ' + '، '.join(options)
        for operation, options in PRICE_TYPE_BY_OPERATION.items()
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
        'وتحمل بياناته مصدر مقبول لصفّه — موقع المطور أو المشغل، منصات الإعلانات، '
        'الأخبار والتقارير — ولا يُشترط مصدر رسمي لكل حقل.\n'
        '3. area_sqm هي مساحة الوحدة القابلة للبيع أو الإيجار أو الوحدة النموذجية، مثل مساحة الشقة أو الفيلا أو المكتب أو المحل أو الغرفة أو الجناح أو المستودع. '
        'لا تستخدم مساحة الأرض أو مساحة البناء الكلية أو Tower GFA أو Gross Floor Area أو مساحة البرج أو المشروع. '
        'إذا وجدت فقط المساحة الإجمالية اترك area_sqm فارغة واكتب السبب في notes.\n'
        '4. لا تكتب سعرًا من معرفتك السابقة. السعر يُقبل فقط إذا ورد في صفحة قرأتها في هذا البحث، '
        'ويجب أن يكون رابط تلك الصفحة نفسها في source_url، مع إدراج كل الصفحات المستخدمة للمنافس في source_urls.\n'
        f'5. إذا لم تجد سعرًا بعد البحث اترك حقول السعر فارغة واكتب في source عبارة {MISSING_VALUE_PHRASE} '
        'مع بيان ما بحثت عنه في notes. الصف الناقص السعر مقبول؛ الرقم المختلق مرفوض.\n'
        '6. املأ price_type من القائمة المسموحة لنوع التشغيل، واستخدم price_from و price_to لأنواع النطاق '
        f'({"، ".join(sorted(RANGE_PRICE_TYPES))}) و price_value لغيرها.\n'
        '7. النطاق الجغرافي ملزم: ابحث عن منافسين داخل النطاق المكتوب في بيانات المشروع فقط. '
        'لكل منافس اكتب حيه في district ومسافته التقريبية من موقع المشروع بالكيلومتر في distance_km '
        'وإحداثياته في lat وlng إن ظهرت في المصدر. '
        'إن لم يكفِ عدد المنافسين داخل النطاق وسّع البحث تدريجيًا وفعّل searchExpanded '
        'واذكر أقصى مسافة وصلت إليها في expansionNote.\n'
        '8. فترة البيانات الملزمة مكتوبة في بيانات المشروع: ارفض أي سعر أو مساحة مصدرها أقدم من '
        'بداية الفترة، واكتب تاريخ البيانات التي وجدتها لكل صف داخل notes.\n'
        '9. مصادر المؤشرات الرسمية إلزامية عند الارتباط: إن كان المشروع أو أي من منافسيه '
        'للإيجار فابحث في المؤشر التفصيلي لسوق الإيجار من سكني '
        '(site:sakani.sa/reports-and-data) وفي مؤشر سوق الإيجار التفصيلي ومقارنة الأحياء '
        '(rei.rega.gov.sa/ar/advanced-search/rental-market/detailed-indicator '
        'و/rental-market/comparison) واسحب جداول الوحدات السكنية أو التجارية أو كلتيهما '
        'حسب مكونات المشروع. وإن كان البيع هو نوع التشغيل فابحث في صفقات منصة المؤشرات '
        'العقارية (rei.rega.gov.sa/ar/advanced-search/deals) والمؤشرات اللحظية '
        '(rei.rega.gov.sa/ar/advanced-search/live) عن صفقات المدينة ومتوسط سعر المتر '
        'حسب الحي ونوع العقار، واستخدم نتائجها كمرجعية رسمية للأسعار. هذه المرجعية '
        'لسياق السوق؛ أما مصادر صفوف المنافسين فيقبل فيها أي موقع يذكر المشروع '
        'بالاسم — إعلانًا تفصيليًا أو خبرًا أو تقريرًا أو موقع مطوّر.\n'
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
        '      "project_type": "سكني أو تجاري أو فندقي أو صناعي ولوجستي أو متعدد الاستخدامات أو أخرى",\n'
        '      "area_mode": "fixed أو range حسب المصدر",\n'
        '      "area_sqm": "القيمة الثابتة أو فارغ للنطاق",\n'
        '      "area_from": "بداية النطاق أو فارغ للقيمة الثابتة",\n'
        '      "area_to": "نهاية النطاق أو فارغ للقيمة الثابتة",\n'
        '      "status": "قائم أو تحت الإنشاء أو على الخارطة",\n'
        '      "classification": "مباشر أو غير مباشر أو مرجعي",\n'
        '      "operation_type": "بيع أو إيجار أو تشغيل فندقي أو أخرى",\n'
        '      "price_type": "",\n'
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
        'إذا وجدت سعرًا في البحث فأعد operation_type وprice_type والقيمة أو النطاق معًا، ولا تترك أيًا منها فارغًا. '
        'إذا لم تجد سعرًا اترك حقول السعر فارغة واذكر المصدر إن وُجد.\n'
        'في source_urls ضع كل روابط الصفحات التي قرأتها واستخدمت منها أي معلومة لهذا المنافس، رابطًا لكل صفحة، '
        'ولا تكتف برابط واحد إذا استخدمت أكثر من صفحة. اجعل source_url هو الرابط الأهم للتوافق مع البيانات القديمة. '
        'في field_sources اربط كل حقل أعدت له قيمة بروابط الصفحات التي تثبته، وبالأخص area_sqm، area_from، area_to، status، classification، operation_type، price_type، price_value، price_from، price_to، وlogo_url. '
        'logo_url مقبول فقط عندما يكون logo_source_url صفحة رسمية للمشروع أو المطور، وإلا اترك الحقلين فارغين. '
        'اجعل source_urls اتحاد جميع روابط field_sources. '
        'في source_url وsource_urls ضع روابط الصفحات المحددة من نتائج البحث، وليس رابط الصفحة الرئيسية للموقع. '
        'رابط النطاق وحده أو الصفحة الرئيسية غير مقبول؛ إن لم تتوفر صفحة محددة '
        f'اترك source_url وsource_urls فارغين واكتب في source عبارة {MISSING_VALUE_PHRASE}.'
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
    return (
        f'تاريخ اليوم / تاريخ الوصول للمصادر: {today}\n'
        f'ابدأ المخرجات بعنوان: {SUMMARY_TITLE}.\n'
        + ('Write the detailed market analysis inside summary as organized axes, one independent value per axis, specific to this project — not a generic city description.\n'
           if en else
           'اكتب تحليل السوق التفصيلي داخل summary على شكل محاور منظمة، قيمة مستقلة لكل محور، مع تحليل خاص بهذا المشروع وليس وصفًا عامًا للمدينة.\n')
        + f'المفاتيح الإلزامية لمحاور summary بالترتيب: {section_keys}.\n'
        + ('Cover each axis with the brief elements, using short bullets inside an axis value when needed. Never put the detailed analysis in one paragraph or mix its axes.\n'
           if en else
           'غطِّ في كل محور عناصر brief النظام، واستخدم نقاطًا قصيرة داخل قيمة المحور عند الحاجة. لا تضع تحليل السوق التفصيلي في فقرة واحدة ولا تخلط محاوره.\n')
        + 'كل رقم يجب أن يظهر أيضًا في جدول المصادر.\n'
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
        + 'صفقات منصة المؤشرات العقارية (rei.rega.gov.sa/ar/advanced-search/deals) والمؤشرات '
        + 'اللحظية (rei.rega.gov.sa/ar/advanced-search/live — متوسط سعر المتر حسب الحي ونوع '
        + 'العقار)، ولمؤشرات الإيجار استخدم المؤشر التفصيلي لسوق الإيجار من سكني '
        + '(site:sakani.sa/reports-and-data) ومؤشر سوق الإيجار التفصيلي '
        + '(rei.rega.gov.sa/ar/advanced-search/rental-market/detailed-indicator) — جداول '
        + 'الوحدات السكنية أو التجارية أو كلتيهما حسب مكونات المشروع.\n'
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


def normalize_competitor_row(row, fallback_source='ai'):
    if not isinstance(row, dict):
        return None
    name = _norm(row.get('name') or row.get('project_name') or row.get('projectName'))
    if not name:
        return None
    project_type = _norm(row.get('project_type') or row.get('projectType') or row.get('نوع المشروع'))
    price_payload = row.get('price') if isinstance(row.get('price'), dict) else {}
    raw_price_type = _first_nonempty(
        row.get('price_type'), row.get('priceType'), row.get('نوع السعر'), row.get('نوع التسعير'),
        price_payload.get('type'), price_payload.get('price_type'), price_payload.get('priceType'),
        price_payload.get('نوع السعر'),
    )
    price_value = _first_nonempty(
        row.get('price_value'), row.get('priceValue'), row.get('value'),
        row.get('القيمة'), row.get('السعر'), row.get('المبلغ'), row.get('amount'),
        price_payload.get('value'), price_payload.get('price_value'), price_payload.get('priceValue'),
        price_payload.get('القيمة'), price_payload.get('السعر'), price_payload.get('amount'),
        row.get('price') if not price_payload else '',
    )
    price_from = _first_nonempty(
        row.get('price_from'), row.get('priceFrom'), row.get('price_min'), row.get('priceMin'),
        row.get('min_price'), row.get('minPrice'), row.get('from'), row.get('من'), row.get('الحد الأدنى'),
        price_payload.get('from'), price_payload.get('price_from'), price_payload.get('priceFrom'),
        price_payload.get('من'), price_payload.get('min'), price_payload.get('minimum'),
    )
    price_to = _first_nonempty(
        row.get('price_to'), row.get('priceTo'), row.get('price_max'), row.get('priceMax'),
        row.get('max_price'), row.get('maxPrice'), row.get('to'), row.get('إلى'), row.get('الى'), row.get('الحد الأعلى'),
        price_payload.get('to'), price_payload.get('price_to'), price_payload.get('priceTo'),
        price_payload.get('إلى'), price_payload.get('الى'), price_payload.get('max'), price_payload.get('maximum'),
    )
    price_value = _clean_numeric(price_value)
    price_from = _clean_numeric(price_from)
    price_to = _clean_numeric(price_to)
    area_cache = row.get('area_cache') if isinstance(row.get('area_cache'), dict) else {}
    area_sqm = _clean_numeric(_first_nonempty(
        row.get('area_sqm'), row.get('areaSqm'), row.get('area'), row.get('المساحة'), area_cache.get('area_sqm')))
    area_from = _clean_numeric(_first_nonempty(
        row.get('area_from'), row.get('areaFrom'), row.get('المساحة من'), area_cache.get('area_from')))
    area_to = _clean_numeric(_first_nonempty(
        row.get('area_to'), row.get('areaTo'), row.get('المساحة إلى'), area_cache.get('area_to')))
    requested_area_mode = _norm(row.get('area_mode') or row.get('areaMode'))
    area_mode = ('range' if requested_area_mode == 'range' else 'fixed'
                 if requested_area_mode == 'fixed' else 'range' if area_from or area_to else 'fixed')
    operation = _canonical_operation(
        row.get('operation_type') or row.get('operationType') or row.get('operation') or row.get('نوع العملية')
        or row.get('نوع التشغيل') or row.get('التشغيل'),
        raw_price_type,
        project_type,
    )
    price_type = _canonical_price_type(raw_price_type, operation, price_from, price_to, price_value)
    classification = _norm(row.get('classification') or row.get('class') or row.get('تصنيف'))
    status = _norm(row.get('status') or row.get('project_status') or row.get('حالة المشروع'))
    field_sources = competitor_field_sources(row)
    source_urls = competitor_source_urls(row)
    price_source_urls = (
        field_sources.get('price_value', [])
        + field_sources.get('price_from', [])
        + field_sources.get('price_to', [])
    )
    source_url = prefer_specific_source_url(
        row.get('source_url'), row.get('sourceUrl'), row.get('url'),
        *price_source_urls,
        *source_urls,
    )
    logo_url = _norm(row.get('logo_url') or row.get('logoUrl'))
    logo_source_url = prefer_specific_source_url(
        row.get('logo_source_url'), row.get('logoSourceUrl'),
        *(field_sources.get('logo_url') or []),
    )
    district = _norm(row.get('district') or row.get('neighborhood') or row.get('الحي'))
    distance_km = _clean_numeric(_first_nonempty(
        row.get('distance_km'), row.get('distanceKm'), row.get('distance'), row.get('المسافة')))
    lat = _clean_numeric(_first_nonempty(row.get('lat'), row.get('latitude'), row.get('خط العرض')))
    lng = _clean_numeric(_first_nonempty(
        row.get('lng'), row.get('lon'), row.get('longitude'), row.get('خط الطول')))
    conflict_warnings = row.get('conflict_warnings') if isinstance(row.get('conflict_warnings'), list) else []
    result = {
        'id': _norm(row.get('id')) or str(uuid.uuid4()),
        'name': name,
        'project_type': project_type,
        'area_mode': area_mode,
        'area_sqm': area_sqm if area_mode == 'fixed' else '',
        'area_from': area_from if area_mode == 'range' else '',
        'area_to': area_to if area_mode == 'range' else '',
        'area_cache': {'area_sqm': area_sqm, 'area_from': area_from, 'area_to': area_to},
        'status': status,
        'classification': classification,
        'logo_file_id': _norm(row.get('logo_file_id') or row.get('logoFileId')),
        'logo_path': _norm(row.get('logo_path') or row.get('logoPath')),
        'logo_url': logo_url,
        'logo_source_url': logo_source_url,
        'district': district,
        'distance_km': distance_km,
        'lat': lat,
        'lng': lng,
        'conflict_warnings': list(conflict_warnings),
        'operation_type': operation,
        'price_type': price_type,
        'price_value': price_value,
        'price_from': price_from,
        'price_to': price_to,
        'price_cache': row.get('price_cache') if isinstance(row.get('price_cache'), dict) else {},
        'source': _norm(row.get('source') or row.get('source_name') or row.get('sourceName')),
        'source_url': source_url,
        'source_urls': source_urls,
        'field_sources': field_sources,
        'data_date': _norm(row.get('data_date') or row.get('dataDate')),
        'notes': _norm(row.get('notes') or row.get('note')),
        'verify_state': _norm(row.get('verify_state') or row.get('verifyState')),
        'verify_provider_error': _norm(row.get('verify_provider_error') or row.get('verifyProviderError')),
        'row_source': _norm(row.get('row_source') or row.get('rowSource')) or fallback_source,
    }
    return result


def _resolve_source_urls(urls, citations, operation=''):
    resolved = []
    for url in urls:
        value = resolve_source_url_from_citations(url, citations, operation)
        if value:
            resolved.append(value)
    return _unique_values(resolved)


def canonicalize_competitor_source_urls(row):
    """Normalize portal-homepage links on a competitor row to the dataset page.

    Citation resolution upgrades a homepage only when the search retrieved a
    deeper page on the same host; this pass catches the rows the retrieval left
    behind, including links merged in by the per-competitor verification.
    """
    if not isinstance(row, dict):
        return row
    operation = _norm(
        row.get('operation_type') or row.get('operationType') or row.get('operation'))
    urls = competitor_source_urls(row)
    resolved = _unique_values(canonical_index_source_url(item, operation) for item in urls)
    if resolved:
        row['source_urls'] = resolved
    field_sources = competitor_field_sources(row)
    if field_sources:
        row['field_sources'] = {
            field: _unique_values(canonical_index_source_url(item, operation) for item in urls)
            for field, urls in field_sources.items()
        }
    source_url = _norm(row.get('source_url'))
    if source_url:
        row['source_url'] = canonical_index_source_url(source_url, operation)
    return row


def apply_search_citations(rows, citations, url_key='source_url'):
    """Upgrade AI-written homepage links to the exact pages returned by the search.

    Runs even with an empty citation set: known indicator portals still resolve
    their bare homepage to the fixed dataset page for the row's operation.
    """
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if (row.get('row_source') or 'ai') != 'ai' and url_key == 'source_url':
            continue
        if url_key == 'source_url':
            operation = _norm(
                row.get('operation_type') or row.get('operationType') or row.get('operation'))
            field_sources = competitor_field_sources(row)
            resolved_field_sources = {
                field: resolved
                for field, urls in field_sources.items()
                if (resolved := _resolve_source_urls(urls, citations, operation))
            }
            urls = competitor_source_urls(row)
            resolved_urls = _resolve_source_urls(urls, citations, operation)
            if resolved_urls:
                row['source_urls'] = resolved_urls
                price_urls = (
                    resolved_field_sources.get('price_value', [])
                    + resolved_field_sources.get('price_from', [])
                    + resolved_field_sources.get('price_to', [])
                )
                row['source_url'] = prefer_specific_source_url(*price_urls, *resolved_urls)
            if resolved_field_sources:
                row['field_sources'] = resolved_field_sources
            continue
        resolved = resolve_source_url_from_citations(row.get(url_key), citations)
        if resolved:
            row[url_key] = resolved
    return rows


def competitor_source_rows(competitors):
    rows = []
    for competitor in competitors or []:
        if not isinstance(competitor, dict):
            continue
        name = _norm(competitor.get('name'))
        if not name:
            continue
        source_name = _norm(competitor.get('source')) or 'مصدر المنافس'
        note = _norm(competitor.get('notes') or competitor.get('note'))
        competitor_id = _norm(competitor.get('id'))
        field_sources = competitor_field_sources(competitor)
        dead_keys = {str(item).casefold() for item in (competitor.get('dead_source_urls') or [])}
        for url in competitor_source_urls(competitor):
            source_fields = [
                _COMPETITOR_SOURCE_FIELD_LABELS.get(field, field)
                for field, urls in field_sources.items()
                if any(str(item).casefold() == url.casefold() for item in urls)
            ]
            field_note = 'الحقول: ' + '، '.join(source_fields) if source_fields else ''
            unverified_note = 'رابط غير موثق — لم يصل من نتائج البحث' if competitor.get('sources_unverified') else ''
            dead_note = 'الرابط لم يعد يعمل' if str(url).casefold() in dead_keys else ''
            source_note = ' — '.join(item for item in (note, field_note, unverified_note, dead_note) if item)
            rows.append({
                'id': str(uuid.uuid4()),
                'competitor_id': competitor_id,
                'competitor_name': name,
                'source_kind': 'competitor',
                'source_fields': source_fields,
                'name': source_name,
                'url': url,
                'data_date': _norm(competitor.get('data_date')),
                'accessed_at': date.today().isoformat(),
                'reliability': official_source_reliability(name, source_name, url),
                'note': source_note,
            })
    return rows


def _competitor_value_filled(value):
    if value is None:
        return False
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return bool(_norm(value))


def _competitor_values_equal(left, right):
    if isinstance(left, (dict, list)) or isinstance(right, (dict, list)):
        return left == right
    return _norm(left).casefold() == _norm(right).casefold()


def merge_generated_competitors(existing, generated, mode='generate'):
    current = []
    for row in existing or []:
        if not isinstance(row, dict):
            continue
        normalized = normalize_competitor_row(
            row, fallback_source=_norm(row.get('row_source')) or 'manual')
        if normalized:
            current.append(normalized)
    if mode != 'fill':
        replaced = []
        for raw in generated or []:
            incoming = normalize_competitor_row(raw)
            if incoming:
                replaced.append(incoming)
        return replaced, len(replaced), 0
    by_id = {str(row.get('id')): index for index, row in enumerate(current)}
    by_name = {_norm(row.get('name')).casefold(): index for index, row in enumerate(current)}
    updated = 0
    protected = {
        'id', 'name', 'row_source', 'field_sources', 'source_urls', 'conflict_warnings',
        'area_mode', 'area_sqm', 'area_from', 'area_to', 'area_cache',
    }
    for raw in generated or []:
        incoming = normalize_competitor_row(raw)
        if not incoming:
            continue
        index = by_id.get(incoming['id'])
        if index is None:
            index = by_name.get(incoming['name'].casefold())
        if index is None:
            continue
        target = current[index]
        target_sources = competitor_field_sources(target)
        incoming_sources = competitor_field_sources(incoming)
        warnings = list(target.get('conflict_warnings') or [])
        has_manual_logo = bool(target.get('logo_file_id') or target.get('logo_path'))
        target_has_area = any(_competitor_value_filled(target.get(key))
                              for key in ('area_sqm', 'area_from', 'area_to'))
        incoming_has_area = any(_competitor_value_filled(incoming.get(key))
                                for key in ('area_sqm', 'area_from', 'area_to'))
        if incoming_has_area and not target_has_area:
            for key in ('area_mode', 'area_sqm', 'area_from', 'area_to', 'area_cache'):
                target[key] = incoming.get(key)
            for key in ('area_sqm', 'area_from', 'area_to'):
                if incoming_sources.get(key):
                    target_sources[key] = _unique_values(incoming_sources[key])
            updated += 1
        elif incoming_has_area and target_has_area:
            target_area = (target.get('area_mode'), target.get('area_sqm'), target.get('area_from'), target.get('area_to'))
            incoming_area = (incoming.get('area_mode'), incoming.get('area_sqm'), incoming.get('area_from'), incoming.get('area_to'))
            area_urls = _unique_values(
                (incoming_sources.get('area_sqm') or [])
                + (incoming_sources.get('area_from') or [])
                + (incoming_sources.get('area_to') or [])
            )
            official_url = next((url for url in area_urls if official_source_reliability(
                incoming.get('name'), incoming.get('source'), url)), '')
            if target_area != incoming_area and official_url:
                warnings.append({
                    'field': 'area_mode', 'existing': target_area, 'incoming': incoming_area,
                    'source': incoming.get('source') or 'مصدر رسمي للجهة', 'source_url': official_url,
                })
        for key, value in incoming.items():
            if key in protected or (has_manual_logo and key in {'logo_url', 'logo_source_url'}):
                continue
            current_value = target.get(key)
            if _competitor_value_filled(value) and not _competitor_value_filled(current_value):
                target[key] = value
                if incoming_sources.get(key):
                    target_sources[key] = _unique_values(
                        (target_sources.get(key) or []) + incoming_sources[key]
                    )
                updated += 1
                continue
            if not (_competitor_value_filled(value) and _competitor_value_filled(current_value)):
                continue
            if _competitor_values_equal(current_value, value):
                continue
            urls = incoming_sources.get(key) or []
            official_url = next((url for url in urls if official_source_reliability(
                incoming.get('name'), incoming.get('source'), url)), '')
            if official_url:
                warning = {
                    'field': key,
                    'existing': current_value,
                    'incoming': value,
                    'source': incoming.get('source') or 'مصدر رسمي للجهة',
                    'source_url': official_url,
                }
                signature = (key, str(current_value), str(value), official_url)
                existing_signatures = {
                    (item.get('field'), str(item.get('existing')), str(item.get('incoming')), item.get('source_url'))
                    for item in warnings if isinstance(item, dict)
                }
                if signature not in existing_signatures:
                    warnings.append(warning)
        target['field_sources'] = target_sources
        target['source_urls'] = _unique_values(competitor_source_urls(target) + competitor_source_urls(incoming))
        target['source_url'] = prefer_specific_source_url(target.get('source_url'), *target['source_urls'])
        target['conflict_warnings'] = warnings
    return current, 0, updated


def normalize_summary(raw):
    data = raw if isinstance(raw, dict) else {}
    raw_summary = data.get('summary')
    summary_source = raw_summary if isinstance(raw_summary, dict) else None
    if summary_source is None:
        top_level = {item['key']: data.get(item['key']) for item in SUMMARY_SECTIONS}
        if any(_norm(value) for value in top_level.values()):
            summary_source = top_level
    if isinstance(summary_source, dict):
        summary = {
            item['key']: _norm(summary_source.get(item['key'])) or MISSING_VALUE_PHRASE
            for item in SUMMARY_SECTIONS
        }
    else:
        # Keep a paragraph returned by an older model readable until the next
        # generation. New responses always use the structured object above.
        summary = _norm(raw_summary) if isinstance(raw_summary, str) else {}
    decision = _norm(data.get('decision'))
    if decision not in DECISION_OPTIONS:
        matched = next((option for option in DECISION_OPTIONS if option in decision), '')
        decision = matched or 'البيانات غير كافية'
    sources = []
    raw_sources = data.get('sources')
    if isinstance(raw_sources, list):
        for row in raw_sources:
            if not isinstance(row, dict):
                continue
            name = _norm(row.get('name'))
            if not name:
                continue
            url = prefer_specific_source_url(row.get('url'), row.get('source_url'), row.get('sourceUrl'))
            sources.append({
                'id': _norm(row.get('id')) or str(uuid.uuid4()),
                'name': name,
                'url': url,
                'data_date': _norm(row.get('data_date') or row.get('dataDate')),
                'accessed_at': _norm(row.get('accessed_at') or row.get('accessedAt')) or date.today().isoformat(),
                'reliability': _norm(row.get('reliability')) or official_source_reliability('', name, url),
                'note': _norm(row.get('note')),
            })
    disclaimer = _norm(data.get('disclaimer')) or (
        'هذه دراسة أولية استرشادية وليست تقييمًا عقاريًا معتمدًا.'
    )
    raw_swot = data.get('swot') if isinstance(data.get('swot'), dict) else {}
    swot = {}
    aliases = {
        'strengths': ('strengths', 'swot_strengths', 'نقاط القوة'),
        'weaknesses': ('weaknesses', 'swot_weaknesses', 'نقاط الضعف'),
        'opportunities': ('opportunities', 'swot_opportunities', 'الفرص'),
        'threats': ('threats', 'swot_threats', 'التهديدات'),
    }
    for item in SWOT_SECTIONS:
        value = ''
        for key in aliases[item['key']]:
            value = _norm(raw_swot.get(key) or data.get(key))
            if value:
                break
        swot[item['key']] = value
    raw_one_block = (
        data.get('one_block_summary')
        or data.get('oneBlockSummary')
        or data.get('market_summary_block')
        or data.get('executive_summary')
    )
    one_block_summary = str(raw_one_block or '').strip()
    one_block_summary = one_block_summary.replace('\\r\\n', '\n').replace('\\n', '\n')
    one_block_summary = re.sub(r'[ \t]+', ' ', one_block_summary)
    one_block_summary = re.sub(r'\n{3,}', '\n\n', one_block_summary)
    if one_block_summary and not is_market_summary_paragraph(one_block_summary):
        fallback_paragraph = summary_prose(summary)
        if isinstance(raw_summary, str) and raw_summary.strip():
            fallback_paragraph = raw_summary.strip()
        one_block_summary = fallback_paragraph
    if not one_block_summary:
        one_block_summary = summary_prose(summary)
    one_block_summary = re.sub(r'\s+', ' ', one_block_summary).strip()
    return {
        'title': SUMMARY_TITLE,
        'summary': summary,
        'swot': swot,
        'decision': decision,
        'sources': sources,
        'disclaimer': disclaimer,
        'one_block_summary': one_block_summary,
    }


def _number_in_text(value):
    """First number inside a possibly unit-suffixed string («3.5 كم» → 3.5)."""
    text = str(value or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    match = re.search(r'\d+(?:[.,]\d+)?', text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(',', '.'))
    except ValueError:
        return None


def flag_out_of_radius(competitors, resolved_km):
    """Mark AI rows whose self-declared distance escapes the chosen radius.

    The model declares each row's distance; when it places a competitor beyond
    the bound the row stays (the user may still want it) but carries an
    ``out_of_radius`` flag and a conflict warning that surfaces in the UI.
    A 25% slack absorbs the model's approximate distance estimates.
    """
    try:
        limit = float(resolved_km)
    except (TypeError, ValueError):
        limit = 0
    if not limit or limit <= 0:
        return 0
    flagged = 0
    for row in competitors or []:
        if not isinstance(row, dict):
            continue
        if _norm(row.get('row_source')) != 'ai':
            continue
        distance = _number_in_text(row.get('distance_km'))
        if distance is None or distance <= limit * 1.25:
            continue
        warnings = list(row.get('conflict_warnings') or [])
        signature = ('distance_km', str(distance))
        if not any(isinstance(item, dict) and (item.get('field'), str(item.get('incoming'))) == signature
                   for item in warnings):
            warnings.append({
                'field': 'distance_km',
                'existing': f'نطاق {limit:g} كم',
                'incoming': f'{distance:g} كم',
                'source': 'خارج نطاق المنافسين',
                'source_url': '',
            })
        row['conflict_warnings'] = warnings
        row['out_of_radius'] = True
        flagged += 1
    return flagged


def flag_out_of_period_sources(sources, bounds):
    """Mark source rows whose data_date escapes the binding period window.

    ``data_date`` arrives as free text («2025», «الربع الأول 2025»,
    «2025-03»); the honest granularity is the year, so a row is flagged only
    when a stated year clearly falls outside the window.
    """
    if not isinstance(bounds, dict) or not bounds:
        return 0
    start_year = int(str(bounds.get('from') or '0000')[:4] or 0)
    end_year = int(str(bounds.get('to') or '9999')[:4] or 9999)
    if not start_year and end_year == 9999:
        return 0
    flagged = 0
    for row in sources or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get('data_date') or '').translate(
            str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
        years = [int(item) for item in re.findall(r'(?<!\d)(19\d{2}|20\d{2})(?!\d)', text)]
        if not years:
            continue
        if any(year < start_year or year > end_year for year in years):
            row['outside_data_period'] = True
            note = _norm(row.get('note'))
            marker = 'خارج فترة البيانات المحددة'
            if marker not in note:
                row['note'] = f'{note} — {marker}' if note else marker
            flagged += 1
    return flagged


def flag_unverified_competitor_sources(row):
    """Mark AI-written links from a search-less answer without deleting them.

    When the response reports zero executed searches and no citations, every
    ``source_url`` the model wrote is memory rather than retrieved evidence.
    The links stay on the row — the owner reviews them and decides to keep or
    reject — while ``sources_unverified`` makes sure they are never passed off
    as sourced results.
    """
    if isinstance(row, dict):
        row['sources_unverified'] = True
    return row


def extract_city_district(address_components, formatted_address=''):
    """Pull Arabic city / district names from Google address components."""
    components = address_components if isinstance(address_components, list) else []
    city = ''
    district = ''
    city_types = {'locality', 'postal_town', 'administrative_area_level_2'}
    district_types = {'sublocality', 'sublocality_level_1', 'neighborhood', 'political'}
    for component in components:
        types = set(component.get('types') or [])
        name = _norm(component.get('long_name') or component.get('short_name'))
        if not name:
            continue
        if not city and types & city_types:
            city = name
        if not district and types & district_types and 'locality' not in types:
            district = name
    if not city:
        for component in components:
            types = set(component.get('types') or [])
            if 'administrative_area_level_1' in types:
                city = _norm(component.get('long_name'))
                break
    if not district:
        formatted = _norm(formatted_address)
        if formatted:
            parts = [part.strip() for part in formatted.split(',') if part.strip()]
            if len(parts) >= 2 and not district:
                district = parts[0]
            if not city and len(parts) >= 2:
                city = parts[-2] if len(parts) > 2 else parts[-1]
    return {'city': city, 'district': district}
