

def data_period_bounds(period_value, from_date='', to_date='', today=None):
    """Resolve the data-period choice into an ISO [from, to] window.

    Returns {} when nothing bounds the period (custom with no dates entered),
    so callers can skip the constraint instead of printing a fake window.
    """
    today = today or date.today()
    months = _DATA_PERIOD_MONTHS.get(_norm(period_value))
    if months:
        total = today.year * 12 + (today.month - 1) - months
        start = date(total // 12, total % 12 + 1, min(today.day, 28))
        return {'from': start.isoformat(), 'to': today.isoformat()}
    start = _norm(from_date)
    end = _norm(to_date)
    if not start and not end:
        return {}
    return {'from': start, 'to': end or today.isoformat()}


def data_period_window_text(payload):
    """«من … إلى …» window text for prompts, or '' when unbounded."""
    bounds = payload.get('dataPeriodBounds') if isinstance(payload, dict) else None
    if not bounds:
        bounds = data_period_bounds(
            (payload or {}).get('dataPeriod') or (payload or {}).get('data_period'),
            (payload or {}).get('dataPeriodFrom') or (payload or {}).get('data_period_from'),
            (payload or {}).get('dataPeriodTo') or (payload or {}).get('data_period_to'),
        )
    if not bounds:
        return ''
    return f"من {bounds.get('from') or 'غير محدد'} إلى {bounds.get('to') or 'تاريخ اليوم'}"


def competitor_scope_text(payload):
    """The competitor table's distance, neighborhood or city boundary."""
    payload = payload or {}
    scope = payload.get('competitorScope') or payload.get('competitor_scope')
    scope = scope if isinstance(scope, dict) else {}
    city = _norm(payload.get('city'))
    district = _norm(payload.get('district'))
    mode = scope.get('mode')
    if mode == 'distance':
        radius = scope.get('radius_km') or scope.get('radiusKm') or scope.get('radius')
        try:
            radius = float(radius)
        except (TypeError, ValueError):
            radius = DEFAULT_COMPETITOR_RADIUS_KM
        return f'ضمن مسافة {radius:g} كم من موقع المشروع'
    if mode == 'city':
        return f'كامل مدينة {city}' if city else 'كامل المدينة'
    districts = competitor_scope_districts(scope, district)
    if len(districts) > 1:
        joined = '، '.join(districts)
        return f'أحياء {joined} في مدينة {city}' if city else f'أحياء {joined}'
    district = districts[0] if districts else ''
    return f'حي {district} في مدينة {city}' if district and city else f'حي {district}' if district else 'حي المشروع'


def competitor_scope_districts(scope, district=''):
    """The districts the competitor table is limited to — the client's own list,
    else the project's single district. Order is kept and repeats are dropped."""
    scope = scope if isinstance(scope, dict) else {}
    raw = (scope.get('districts') or scope.get('district_list')
           or scope.get('districts_list'))
    if isinstance(raw, str):
        raw = [part for part in re.split(r'[،,\n]+', raw)]
    values = []
    for item in list(raw or []) + [_norm(district)]:
        item = _norm(item)
        if item and item not in values:
            values.append(item)
    return values


def competitor_scope_unit_types(scope):
    """The property kinds the client asked to compare (فيلا، شقة، مكتب …)."""
    scope = scope if isinstance(scope, dict) else {}
    raw = (scope.get('unit_types') or scope.get('unitTypes')
           or scope.get('property_types') or scope.get('unit_type'))
    if isinstance(raw, str):
        raw = re.split(r'[،,\n]+', raw)
    values = []
    for item in raw or []:
        item = _norm(item)
        if item and item not in values:
            values.append(item)
    return values


# Words that state a property kind inside a competitor row's own text. The
# client's unit-kind picks (شقة، فيلا، مكتب …) are matched against these so a
# row that states a different kind is outside the request. A row that states no
# kind at all carries no evidence of the wrong one and is never dropped. The
# wording mirrors the aqar portal categories, because a row read from an ad and
# a row returned by the model must be judged the same way.
UNIT_TYPE_CATEGORY_TOKENS = {
    'استوديو': ('استوديو', 'ستوديو', 'studio'),
    'شقة': ('شقق', 'شقة', 'apartment', 'flat'),
    'شقة دوبلكس': ('شقة دوبلكس', 'دوبلكس', 'duplex'),
    'بنتهاوس': ('بنتهاوس', 'penthouse'),
    'دور مستقل': ('دور مستقل',),
    'ملحق سكني': ('ملحق سكني', 'ملحق'),
    'فيلا مستقلة': ('فيلا', 'فلل', 'villa'),
    'فيلا دوبلكس': ('فيلا دوبلكس', 'فيلا', 'فلل', 'villa'),
    'تاون هاوس': ('تاون هاوس', 'townhouse', 'town house'),
    'توين هاوس': ('توين هاوس', 'twin house'),
    'قصر': ('قصر', 'palace'),
    'بيت شعبي / بيت عربي': ('بيت شعبي', 'بيت عربي'),
    'عمارة سكنية': ('عمارة سكنية', 'عمارة'),
    'مجمع سكني': ('مجمع سكني', 'compound'),
    'سكن موظفين': ('سكن موظفين', 'staff housing'),
    'سكن عمال': ('سكن عمال', 'labor housing', 'labour housing'),
    'مكتب': ('مكتب', 'مكاتب', 'office'),
    'برج مكاتب': ('برج مكاتب', 'office tower', 'tower'),
    'محل تجاري': ('محل', 'محلات', 'retail', 'shop'),
    'معرض تجاري': ('معرض', 'معارض', 'showroom'),
    'مركز تجاري': ('مركز تجاري', 'mall'),
    'مستودع تجاري': ('مستودع', 'مستودعات', 'warehouse'),
}


def normalize_competitor_scope(value):
    """Normalize the competitor-only location mode and optional radius."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = {}
    scope = value if isinstance(value, dict) else {}
    mode = _norm(scope.get('mode')).lower()
    if mode not in {'district', 'city', 'distance'}:
        mode = 'district'
    result = {'mode': mode}
    if mode == 'distance':
        radius_choice = (scope.get('radius') or scope.get('radius_choice')
                         or scope.get('radiusChoice') or '10')
        custom = (scope.get('radius_custom_km') or scope.get('radiusCustomKm')
                  or scope.get('custom_km') or scope.get('customKm'))
        if scope.get('radius_km') or scope.get('radiusKm'):
            radius_choice = 'custom'
            custom = scope.get('radius_km') or scope.get('radiusKm')
        result['radius_km'] = resolve_competitor_radius_km(radius_choice, custom)
    # A district scope may name several districts; the client's list is kept
    # whole and is never widened on our side.
    districts = competitor_scope_districts(scope)
    if districts:
        result['districts'] = districts
    unit_types = competitor_scope_unit_types(scope)
    if unit_types:
        result['unit_types'] = unit_types
    return result
SUMMARY_TITLE = 'الملخص التنفيذي لسوق المشروع'
SUMMARY_WORD_TARGET = 350
SUMMARY_MIN_WORDS = 300

SUMMARY_SECTION_HINTS = {
    'market_definition': 'نطاق الملخص المحدد (وليس نطاق المنافسين)، نوع المشروع ومكوناته، وفترة البيانات — اذكر مدن/أحياء نطاق الملخص بالاسم مع التوصيف المكاني والجغرافي الدقيق لنشاط المشروع والسوق المستهدف.',
    'city_position': 'المركز الاقتصادي والاستثماري للمدينة، عدد السكان والنمو والكثافة إذا كانت مؤثرة، الأهمية الاقتصادية للمدينة، المشروعات الكبرى المحيطة والمحفزات، القوة الشرائية وأهم محركات الطلب المرتبطة بالمشروع مباشرة.',
    'sector_performance': 'أهم مؤشرات أداء النشاط العقاري المحدد داخل نطاق الملخص المحدد، عدد وقيمة الصفقات العقارية المنفذة ومؤشرات منصة المؤشرات العقارية، اتجاه الأسعار أو الإيجارات أو الإشغال في نفس النطاق، حجم الصفقات أو الطلب عليه، والمقارنة بالفترة السابقة بالأرقام الموثقة — وعند تعارض هذه القاعدة مع نطاق الملخص فالملزم هو نطاق الملخص وحده.',
    'supply': 'رصد المعروض القائم في النطاق المحدد، المشروعات المرخصة وتحت الإنشاء ومشاريع البيع على الخارطة، حجم المعروض القائم، المعروض تحت الإنشاء، المشروعات المستقبلية، ووجود فائض أو نقص وتحليل التوازن مع الأرقام التقديرية.',
    'demand': 'مستوى الطلب الفعلي، الشرائح والعملاء المستهدفون بدقة، المنتج والمساحات الأكثر طلبًا، ومعدل الامتصاص أو الإشغال عند توفره، وسرعة التأجير أو البيع مع القدرة المالية للمستفيدين.',
    'competition': 'تحليل المنافسين في النطاق المحدد: عدد المنافسين، عدد المنافسين المباشرين، نطاق الأسعار والمساحات ومستويات التشطيب والخدمات، وأهم نقاط القوة والضعف لديهم.',
    'market_gap': 'الفجوة السوقية الحقيقية غير المغطاة: المنتج غير المتوفر بشكل كاف، المساحات أو الخدمات الناقصة، والفرصة التي يستطيع المشروع استهدافها لتلبية نقص حقيقي في السوق.',
    'project_evaluation': 'تقييم محايد للمشروع كما أُدخل مقابل واقع السوق: اتساق المكونات ونموذج الاستفادة والتكلفة والعوائد المدخلة مع اتجاه السوق عبر فترة البيانات وحاضره ومستقبله المتوقع حتى سنة التشغيل؛ أين تكمن فرصة الربح فعليًا؛ وهل النموذج المدخل هو الأنسب أم يوجد أعلى جدوى — دون افتراض أن المدخل صحيح.',
    'recommendation': 'توصية استشارية متكاملة ومحددة: الاستخدام الأنسب، المكونات المقترحة، المساحات أو مزيج الوحدات، والسعر أو الإيجار أو ADR المقترح، مع شروط وجدول الطرح الأنسب.',
    'risks': 'أهم المخاطر السوقية وشروط نجاح المشروع، مع تحليل شامل لمخاطر التسعير والامتصاص والمنافسة المستقبلية وآليات التحوط الموصى بها.',
    'decision': 'صنّف الفرصة إلى إحدى قيم القرار المسموحة مع تفسير مختصر.',
}

SOURCE_PRIORITY = {
    1: [
        'الهيئة العامة للعقار rega.gov.sa',
        'منصة المؤشرات العقارية rei.rega.gov.sa — صفحة كل مدينة تحت مسار /ar/cities تعرض عدد صفقاتها وقيمتها والحي الأكثر نشاطًا؛ صفحات البحث المتقدم في المنصة تتطلب دخول نفاذ',
        'المؤشر التفصيلي لسوق الإيجار sakani.sa/reports-and-data — جداول إيجار الوحدات السكنية والتجارية حسب المدينة والحي',
        'السجل العقاري rer.sa وبيانات وزارة العدل moj.gov.sa المتاحة',
        'شبكة إيجار ejar.sa',
        'الهيئة العامة للإحصاء stats.gov.sa',
        'منصة البيانات المفتوحة السعودية open.data.gov.sa',
        'وزارة البلديات والإسكان momah.gov.sa',
        'منصة بلدي balady.gov.sa',
        'الأمانة التابعة للمدينة',
        'كود البناء السعودي sbc.gov.sa',
        'البنك المركزي السعودي sama.gov.sa',
        'برنامج وافي red.rega.gov.sa — مشاريع البيع والتأجير على الخارطة المرخصة',
        'منصة سكني sakani.sa',
        'الشركة الوطنية للإسكان NHC nhc.sa',
    ],
    2: [
        'موقع المشروع الرسمي',
        'موقع المطور الرسمي',
        'موقع المشغل الرسمي',
        'موقع العلامة الفندقية',
        'كتيب المشروع الرسمي',
        'بيانات البيع الرسمية',
        'بيانات تداول للشركات والصناديق العقارية',
        'الإعلانات الرسمية للمطور',
    ],
    3: [
        'CBRE cbre.sa', 'JLL jll.com/en-sa', 'Knight Frank knightfrank.com.sa',
        'Colliers colliers.com/en-sa', 'Savills savills.me',
        'ValuStrat valustrat.com', 'Deloitte deloitte.com/middle-east',
        'PwC pwc.com/m1', 'KPMG kpmg.com/sa', 'EY ey.com',
        'STR str.com أو CoStar costar.com للفنادق',
    ],
    4: [
        'منصة عقار aqar.fm', 'منصات المسوقين العقاريين المرخصين',
    ],
    5: [
        'Google Maps للمواقع والمسافات والخدمات maps.google.com',
        'Google Places للتقييمات والحركة المحيطة',
        'المواقع الإخبارية الموثوقة',
        'البيانات الصحفية الرسمية',
    ],
}

TYPE_ANALYSIS_POINTS = {
    'سكني': [
        'عدد سكان المدينة',
        'النمو والكثافة السكانية',
        'عدد الأسر ومتوسط حجم الأسرة',
        'النمو في تكوين الأسر',
        'عدد وقيمة الصفقات السكنية',
        'أسعار الشقق أو الفلل أو الأراضي',
        'اتجاه أسعار البيع',
        'اتجاه الإيجارات',
        'التمويل العقاري السكني',
        'حجم المعروض القائم',
        'مشروعات وافي وسكني المستقبلية',
        'أنواع الوحدات الأكثر طلبًا',
        'المساحات الأكثر طلبًا',
        'سرعة البيع ومعدل الامتصاص',
        'القدرة الشرائية والقيمة الإجمالية المناسبة',
        'المنافسين السكنيين المشابهين',
        'الفجوة في الوحدات والمساحات والخدمات',
    ],
    'مكاتب': [
        'عدد المنشآت والشركات في المدينة',
        'النمو في تسجيل الشركات',
        'العرض المكتبي القائم والمستقبلي',
        'تصنيف المكاتب A و B و C',
        'متوسط الإيجار السنوي للمتر',
        'نسبة الإشغال والشواغر',
        'المساحات المكتبية المطلوبة',
        'الطلب من الشركات المحلية والعالمية',
        'المشروعات المكتبية المستقبلية',
        'المنافسين ومزاياهم ومواقفهم وخدماتهم',
    ],
    'تجزئة': [
        'عدد السكان في نطاق الخدمة',
        'الكثافة السكانية',
        'القوة الشرائية والإنفاق الاستهلاكي',
        'أعداد الزوار',
        'المعروض التجاري القائم',
        'الإيجار السنوي للمتر',
        'نسبة الإشغال والشواغر',
        'مزيج المستأجرين',
        'المراكز التجارية القادمة',
        'كثافة المطاعم والمقاهي والمتاجر',
        'مواقف السيارات وسهولة الوصول',
        'المنافسين المباشرين ضمن نطاق الخدمة',
    ],
    'فندقي': [
        'أعداد الزوار والسياح',
        'حركة مطار المدينة',
        'المواسم والفعاليات',
        'عدد الفنادق والمنشآت المرخصة',
        'عدد الغرف والمفاتيح',
        'تصنيف الفنادق',
        'نسبة الإشغال',
        'متوسط سعر الغرفة ADR',
        'الإيراد لكل غرفة متاحة RevPAR',
        'متوسط مدة الإقامة',
        'العرض الفندقي المستقبلي',
        'العلامات الفندقية القادمة',
        'الموسمية وأشهر الذروة',
        'شرائح النزلاء',
        'الفنادق المنافسة وأسعارها وخدماتها',
        'مدى الحاجة إلى فندق أو شقق مخدومة أو منتجع',
        'الفجوة في التصنيف أو مستوى الخدمة',
    ],
    'صناعي ولوجستي': [
        'النشاط الصناعي في المدينة والمنطقة',
        'عدد المصانع والمنشآت الصناعية',
        'التراخيص الصناعية الجديدة',
        'الصناعات الرئيسية',
        'الطلب على الأراضي والمصانع والمستودعات',
        'أسعار أو مقابل إيجار الأراضي الصناعية',
        'إيجارات المستودعات والمصانع الجاهزة',
        'نسب الإشغال والتوفر',
        'توفر الكهرباء والمياه والغاز والاتصالات',
        'القرب من الموانئ والمطارات والطرق',
        'حركة البضائع والشحن',
        'توفر العمالة',
        'سلاسل الإمداد',
        'المدن والمناطق الصناعية المنافسة',
        'المناطق الاقتصادية الخاصة',
        'الحوافز والاشتراطات',
        'نوع ومساحة المنشآت المطلوبة',
        'إمكانية الوصول إلى الأسواق والعملاء',
    ],
}

TYPE_SOURCE_PRIORITY = {
    'سكني': [
        'منصة المؤشرات العقارية rei.rega.gov.sa — صفحة المدينة تحت /ar/cities: عدد الصفقات وقيمتها والحي الأكثر نشاطًا',
        'المؤشر التفصيلي لسوق الإيجار sakani.sa/reports-and-data',
        'الهيئة العامة للإحصاء stats.gov.sa',
        'البنك المركزي السعودي sama.gov.sa',
        'وافي red.rega.gov.sa',
        'سكني sakani.sa وNHC nhc.sa',
        'الأمانة وبلدي balady.gov.sa',
        'المواقع الرسمية للمطورين',
        'تقارير CBRE cbre.sa وJLL jll.com/en-sa وKnight Frank knightfrank.com.sa وColliers colliers.com/en-sa',
        'منصة عقار aqar.fm',
        'Google Maps للموقع والخدمات فقط',
    ],
    'تجاري': [
        'منصة المؤشرات العقارية rei.rega.gov.sa — صفحة المدينة تحت /ar/cities — وشبكة إيجار ejar.sa',
        'المؤشر التفصيلي لسوق الإيجار sakani.sa/reports-and-data — جداول الوحدات التجارية',
        'الهيئة العامة للإحصاء stats.gov.sa',
        'وزارة التجارة mc.gov.sa',
        'الأمانة وبلدي balady.gov.sa',
        'البنك المركزي السعودي sama.gov.sa',
        'المواقع الرسمية للمراكز والمشروعات التجارية',
        'تداول saudiexchange.sa وتقارير الصناديق العقارية',
        'CBRE cbre.sa وJLL jll.com/en-sa وKnight Frank knightfrank.com.sa وColliers colliers.com/en-sa وSavills savills.me',
        'منصة عقار aqar.fm',
        'Google Maps وGoogle Places للخدمات والتقييمات',
    ],
    'فندقي': [
        'وزارة السياحة mt.gov.sa',
        'منشورات وزارة السياحة الرسمية tourism.sa/ar/data-insights/publications',
        'الهيئة العامة للإحصاء stats.gov.sa وإحصاءات المنشآت السياحية',
        'الهيئة العامة للطيران المدني gaca.gov.sa',
        'الجهات الرسمية للفعاليات والسياحة في المدينة',
        'المواقع الرسمية للفنادق والمشغلين',
        'STR str.com أو CoStar costar.com',
        'CBRE cbre.sa وJLL jll.com/en-sa وKnight Frank knightfrank.com.sa وColliers colliers.com/en-sa',
        'مواقع الحجز لمقارنة السعر في تاريخ محدد فقط',
        'Google Maps للتقييمات والموقع والخدمات',
    ],
    'صناعي ولوجستي': [
        'وزارة الصناعة والثروة المعدنية mim.gov.sa',
        'الهيئة السعودية للمدن الصناعية ومناطق التقنية مدن modon.gov.sa',
        'خرائط مدن GIS',
        'هيئة المدن والمناطق الاقتصادية الخاصة ecza.gov.sa',
        'الهيئة العامة للإحصاء stats.gov.sa',
        'الهيئة العامة للموانئ mawani.gov.sa',
        'الهيئة العامة للطيران المدني للشحن الجوي gaca.gov.sa',
        'وزارة النقل والخدمات اللوجستية mot.gov.sa',
        'الأمانة وبلدي balady.gov.sa',
        'المواقع الرسمية للمدن الصناعية والمشروعات',
        'تقارير CBRE cbre.sa وJLL jll.com/en-sa وKnight Frank knightfrank.com.sa وColliers colliers.com/en-sa',
        'منصات المستودعات والعقارات الصناعية',
    ],
}

MANDATORY_RULES = [
    'لا تقدم تحليلًا عامًا لا يرتبط بنوع المشروع.',
    'لا تستخدم الكثافة السكانية كمؤشر رئيسي للمشروع الصناعي إلا إذا كانت مرتبطة بالعمالة أو السوق الاستهلاكي.',
    'لا تستخدم أعداد السياح لتقييم مشروع سكني إلا إذا كان المنتج سكنًا سياحيًا أو فندقيًا.',
    'لا تستخدم متوسط أسعار المدينة مباشرة لتسعير المشروع.',
    'قارن المشروع بمنافسين من النوع والفئة نفسها.',
    'افصل بين سعر الطلب وسعر الصفقة.',
    'افصل بين المساحة الإجمالية والمساحة الصافية أو التأجيرية.',
    'لا تنشئ أي رقم غير متوفر.',
    f'إذا لم تتوفر المعلومة اكتب: {MISSING_VALUE_PHRASE}.',
    'اذكر مع كل رقم: اسم المصدر، رابط الصفحة بالضبط التي ورد فيها الرقم (وليس الصفحة الرئيسية للموقع)، تاريخ البيانات، تاريخ الوصول، مستوى الموثوقية.',
    'ابدأ بالمستوى الأول، ولا تنتقل إلى مستوى أدنى إلا إذا لم تتوفر المعلومة في المستوى الأعلى، مع تسجيل سبب الانتقال.',
    'عند اختلاف المصادر استخدم المصدر الأعلى أولوية واشرح الاختلاف.',
    'لا تستخدم وسائل التواصل أو المدونات أو ويكيبيديا كمصدر مالي.',
    'لا تعتبر الإعلان العقاري صفقة منفذة.',
    'لا تعتبر سعر الحجز اليومي متوسطًا سنويًا للفندق.',
    'وضح إذا كانت البيانات تخص المدينة أو المنطقة الإدارية أو المملكة.',
    'وضح إذا كانت القيمة رسمية أو محسوبة أو تقديرية.',
    'اختم بأن الدراسة أولية استرشادية وليست تقييمًا عقاريًا معتمدًا.',
    'تعامل مع أسعار منصات الإعلانات باعتبارها أسعار طلب وليست صفقات منفذة.',
    'لا تستخدم مصادر المستوى الخامس وحدها لتحديد سعر المشروع.',
    'لا تعامل سعر ليلة واحدة في منصة حجز على أنه متوسط ADR سنوي.',
    'يُحظر تمامًا تقديم أي توصيات أو مقترحات تنطوي على إخلاء قسري، أو مساس بحقوق السكان القائمين، أو نزع ملكية، أو تمييز على أساس فئوي أو سكاني؛ واقتصر على التحليل التخطيطي والهندسي والمكاني والمالي الموضوعي المحايد.',
    'تجنب أي صور نمطية أو تعميمات غير موضوعية، مع الالتزام التام بالحياد المهني والإنصاف الأخلاقي.',
    'يُحظر تضمين أي بيانات شخصية أو معرّفات لأشخاص طبيعيين أو أرقام هويات وطنية في نتائج التحليل.',
]

RELIABILITY_LEVELS = ['رسمي حكومي', 'رسمي للمشروع', 'تقرير مهني', 'إعلان / طلب', 'مساند', 'غير متوفر']

SWOT_SECTION_HINTS = {
    'strengths': 'نقاط قوة المشروع نفسه أمام السوق والمنافسين: الموقع، النوع، المستوى، الاشتراطات، المساحة، أو أي ميزة مثبتة.',
    'weaknesses': 'نقاط ضعف المشروع نفسه: قيود الموقع، المساحة، المستوى، الفئة، المعروض المشابه، أو أي قيد مثبت.',
    'opportunities': 'فرص السوق التي يستطيع المشروع استهدافها: فجوة المنتج، الطلب غير المغطى، النمو، أو نقص المعروض المناسب.',
    'threats': 'تهديدات السوق: فائض المعروض، المنافسون الأقوى، تغيّر الأسعار أو الإشغال، المخاطر التنظيمية أو التمويلية المرتبطة بالنوع.',
}

