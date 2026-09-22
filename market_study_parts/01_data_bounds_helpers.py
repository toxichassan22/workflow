

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
    """«داخل نطاق N كم من إحداثيات المشروع» or the city label."""
    resolved = (payload or {}).get('resolvedRadiusKm')
    label = _norm((payload or {}).get('competitorRadiusLabel')) or 'تلقائي'
    try:
        km = float(resolved)
    except (TypeError, ValueError):
        km = 0
    if km > 0:
        return f'داخل نطاق {km:g} كم من موقع المشروع ({label})'
    return label
SUMMARY_TITLE = 'الملخص التنفيذي لسوق المشروع'
SUMMARY_WORD_TARGET = 350
SUMMARY_MIN_WORDS = 300

SUMMARY_SECTION_HINTS = {
    'market_definition': 'المدينة، نوع المشروع، نطاق الدراسة، فترة البيانات.',
    'city_position': 'عدد السكان والنمو والكثافة إذا كانت مؤثرة، الأهمية الاقتصادية للمدينة، أهم محركات الطلب المرتبطة بالمشروع.',
    'sector_performance': 'أهم مؤشرات أداء النشاط العقاري المحدد، اتجاه الأسعار أو الإيجارات أو الإشغال، حجم الصفقات أو الطلب، والمقارنة بالفترة السابقة.',
    'supply': 'حجم المعروض القائم، المعروض تحت الإنشاء، المشروعات المستقبلية، ووجود فائض أو نقص.',
    'demand': 'مستوى الطلب، العملاء المستهدفون، المنتج والمساحات الأكثر طلبًا، ومعدل الامتصاص أو الإشغال عند توفره.',
    'competition': 'عدد المنافسين، عدد المنافسين المباشرين، نطاق الأسعار، وأهم نقاط القوة والضعف لديهم.',
    'market_gap': 'المنتج غير المتوفر بشكل كاف، المساحات أو الخدمات الناقصة، والفرصة التي يستطيع المشروع استهدافها.',
    'project_evaluation': 'تقييم محايد للمشروع كما أُدخل مقابل واقع السوق: اتساق المكونات ونموذج الاستفادة والتكلفة والعوائد المدخلة مع اتجاه السوق عبر فترة البيانات وحاضره ومستقبله المتوقع حتى سنة التشغيل؛ أين تكمن فرصة الربح فعليًا؛ وهل النموذج المدخل هو الأنسب أم يوجد أعلى جدوى — دون افتراض أن المدخل صحيح.',
    'recommendation': 'الاستخدام الأنسب، المكونات المقترحة، المساحات أو مزيج الوحدات، والسعر أو الإيجار أو ADR المقترح.',
    'risks': 'أهم المخاطر السوقية وشروط نجاح المشروع.',
    'decision': 'صنّف الفرصة إلى إحدى قيم القرار المسموحة مع تفسير مختصر.',
}

SOURCE_PRIORITY = {
    1: [
        'الهيئة العامة للعقار rega.gov.sa',
        'منصة المؤشرات العقارية rei.rega.gov.sa — صفقات البيع المنفذة rei.rega.gov.sa/ar/advanced-search/deals ومتوسط سعر المتر حسب الحي ونوع العقار',
        'المؤشرات اللحظية rei.rega.gov.sa/ar/advanced-search/live — أسعار السوق الحالية',
        'مؤشر سوق الإيجار التفصيلي rei.rega.gov.sa/ar/advanced-search/rental-market/detailed-indicator — ومقارنة الأحياء rei.rega.gov.sa/ar/advanced-search/rental-market/comparison',
        'معروض الإعلانات rei.rega.gov.sa/ar/advanced-search/ads-supply-market — أسعار الطلب المعروضة',
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
        'منصة عقار aqar.fm', 'بيوت السعودية bayut.sa', 'وصلت wasalt.sa',
        'تطبيق ديل dealapp.sa', 'منصات المسوقين العقاريين المرخصين',
    ],
    5: [
        'Google Maps للمواقع والمسافات والخدمات maps.google.com',
        'Google Places للتقييمات والحركة المحيطة',
        'المواقع الإخبارية الموثوقة',
        'وكالة الأنباء السعودية spa.gov.sa',
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
        'منصة المؤشرات العقارية rei.rega.gov.sa/ar/advanced-search — صفقات البيع المنفذة deals ومؤشر سوق الإيجار rental-market',
        'المؤشر التفصيلي لسوق الإيجار sakani.sa/reports-and-data',
        'الهيئة العامة للإحصاء stats.gov.sa',
        'البنك المركزي السعودي sama.gov.sa',
        'وافي red.rega.gov.sa',
        'سكني sakani.sa وNHC nhc.sa',
        'الأمانة وبلدي balady.gov.sa',
        'المواقع الرسمية للمطورين',
        'تقارير CBRE cbre.sa وJLL jll.com/en-sa وKnight Frank knightfrank.com.sa وColliers colliers.com/en-sa',
        'منصات الإعلانات العقارية aqar.fm وbayut.sa وwasalt.sa',
        'Google Maps للموقع والخدمات فقط',
    ],
    'تجاري': [
        'منصة المؤشرات العقارية rei.rega.gov.sa/ar/advanced-search — صفقات البيع المنفذة deals ومؤشر سوق الإيجار rental-market — وشبكة إيجار ejar.sa',
        'المؤشر التفصيلي لسوق الإيجار sakani.sa/reports-and-data — جداول الوحدات التجارية',
        'الهيئة العامة للإحصاء stats.gov.sa',
        'وزارة التجارة mc.gov.sa',
        'الأمانة وبلدي balady.gov.sa',
        'البنك المركزي السعودي sama.gov.sa',
        'المواقع الرسمية للمراكز والمشروعات التجارية',
        'تداول saudiexchange.sa وتقارير الصناديق العقارية',
        'CBRE cbre.sa وJLL jll.com/en-sa وKnight Frank knightfrank.com.sa وColliers colliers.com/en-sa وSavills savills.me',
        'منصات التأجير والإعلانات aqar.fm وbayut.sa وwasalt.sa',
        'Google Maps وGoogle Places للخدمات والتقييمات',
    ],
    'فندقي': [
        'وزارة السياحة mt.gov.sa',
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
]

RELIABILITY_LEVELS = ['رسمي حكومي', 'رسمي للمشروع', 'تقرير مهني', 'إعلان / طلب', 'مساند', 'غير متوفر']

SWOT_SECTION_HINTS = {
    'strengths': 'نقاط قوة المشروع نفسه أمام السوق والمنافسين: الموقع، النوع، المستوى، الاشتراطات، المساحة، أو أي ميزة مثبتة.',
    'weaknesses': 'نقاط ضعف المشروع نفسه: قيود الموقع، المساحة، المستوى، الفئة، المعروض المشابه، أو أي قيد مثبت.',
    'opportunities': 'فرص السوق التي يستطيع المشروع استهدافها: فجوة المنتج، الطلب غير المغطى، النمو، أو نقص المعروض المناسب.',
    'threats': 'تهديدات السوق: فائض المعروض، المنافسون الأقوى، تغيّر الأسعار أو الإشغال، المخاطر التنظيمية أو التمويلية المرتبطة بالنوع.',
}


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def _norm(value):
    return re.sub(r'\s+', ' ', str(value or '').strip())


def _clean_numeric(value):
    text = str(value or '').strip()
    if not text:
        return ''
    text = text.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    text = text.replace('٬', '').replace('،', '').replace(',', '').replace('٫', '.').replace(' ', '')
    if not re.fullmatch(r'-?\d+(?:\.\d+)?', text):
        return str(value or '').strip()
    try:
        rounded = Decimal(text).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return text
    return str(int(rounded)) if rounded == rounded.to_integral_value() else f'{rounded:.1f}'


def _first_nonempty(*values):
    for value in values:
        if isinstance(value, (dict, list, tuple, set)):
            continue
        text = _norm(value)
        if text:
            return text
    return ''


def _iter_source_values(value):
    if isinstance(value, dict):
        for key in ('url', 'urls', 'source_url', 'source_urls', 'sourceUrl', 'sourceUrls', 'href'):
            if value.get(key):
                yield from _iter_source_values(value.get(key))
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_source_values(item)
        return
    text = _norm(value)
    if not text:
        return
    urls = re.findall(r"https?://[^\s<>\"'\[\]{}]+", text)
    if urls:
        for url in urls:
            yield url.rstrip('.,،;:!?)]}')
        return
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, (list, tuple, dict)):
        yield from _iter_source_values(parsed)
        return
    for part in re.split(r'[\r\n,،;|]+', text):
        part = part.strip()
        if part:
            yield part


def _unique_values(values):
    result = []
    seen = set()
    for value in values:
        text = _norm(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


_COMPETITOR_SOURCE_FIELD_ALIASES = {
    'name': 'name',
    'project_name': 'name',
    'projectName': 'name',
    'اسم المشروع': 'name',
    'project_type': 'project_type',
    'projectType': 'project_type',
    'نوع المشروع': 'project_type',
    'area': 'area_sqm',
    'area_sqm': 'area_sqm',
    'areaSqm': 'area_sqm',
    'المساحة': 'area_sqm',
    'area_from': 'area_from',
    'areaFrom': 'area_from',
    'المساحة من': 'area_from',
    'area_to': 'area_to',
    'areaTo': 'area_to',
    'المساحة إلى': 'area_to',
    'status': 'status',
    'project_status': 'status',
    'حالة المشروع': 'status',
    'classification': 'classification',
    'تصنيف': 'classification',
    'logo_url': 'logo_url',
    'logoUrl': 'logo_url',
    'شعار المنافس': 'logo_url',
    'operation_type': 'operation_type',
    'operationType': 'operation_type',
    'operation': 'operation_type',
    'نوع العملية': 'operation_type',
    'price_type': 'price_type',
    'priceType': 'price_type',
    'نوع السعر': 'price_type',
    'price_value': 'price_value',
    'priceValue': 'price_value',
    'value': 'price_value',
    'price_from': 'price_from',
    'priceFrom': 'price_from',
    'price_to': 'price_to',
    'priceTo': 'price_to',
    'district': 'district',
    'neighborhood': 'district',
    'الحي': 'district',
    'distance_km': 'distance_km',
    'distanceKm': 'distance_km',
    'distance': 'distance_km',
    'المسافة': 'distance_km',
    'المسافة بالكيلومتر': 'distance_km',
    'lat': 'lat',
    'latitude': 'lat',
    'خط العرض': 'lat',
    'lng': 'lng',
    'lon': 'lng',
    'longitude': 'lng',
    'خط الطول': 'lng',
}

_COMPETITOR_SOURCE_FIELD_LABELS = {
    'name': 'اسم المشروع',
    'project_type': 'نوع المشروع',
    'area_sqm': 'مساحة الوحدة',
    'area_from': 'مساحة الوحدة من',
    'area_to': 'مساحة الوحدة إلى',
    'status': 'الحالة',
    'classification': 'التصنيف',
    'logo_url': 'شعار المنافس',
    'operation_type': 'نوع العملية',
    'price_type': 'نوع السعر',
    'price_value': 'قيمة السعر',
    'price_from': 'حد السعر الأدنى',
    'price_to': 'حد السعر الأعلى',
    'district': 'الحي',
    'distance_km': 'المسافة من موقع المشروع',
    'lat': 'خط العرض',
    'lng': 'خط الطول',
}


def _canonical_source_field(value):
    text = _norm(value)
    return _COMPETITOR_SOURCE_FIELD_ALIASES.get(text, text)


def _http_source_urls(value):
    return _unique_values(
        item for item in _iter_source_values(value)
        if str(item).strip().lower().startswith(('http://', 'https://'))
    )


def competitor_field_sources(row):
    if not isinstance(row, dict):
        return {}
    raw = row.get('field_sources') or row.get('fieldSources') or {}
    entries = []
    if isinstance(raw, dict):
        entries = raw.items()
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            field = item.get('field') or item.get('key') or item.get('name')
            urls = item.get('urls') or item.get('source_urls') or item.get('sourceUrls') or item.get('url')
            if field:
                entries.append((field, urls))
    result = {}
    for field, value in entries:
        key = _canonical_source_field(field)
        urls = _http_source_urls(value)
        if key and urls:
            result[key] = _unique_values((result.get(key) or []) + urls)
    return result


def competitor_source_urls(row):
    if not isinstance(row, dict):
        return []
    values = []
    for key in ('source_urls', 'sourceUrls', 'urls', 'source_url', 'sourceUrl', 'url', 'sources', 'source'):
        values.extend(_http_source_urls(row.get(key)))
    for urls in competitor_field_sources(row).values():
        values.extend(urls)
    return _unique_values(values)


def _fold_choice(value):
    return re.sub(r'\s+', ' ', _norm(value).replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه')).casefold()


def _canonical_operation(value, price_type='', project_type=''):
    text = _norm(value)
    if text in COMPETITOR_OPERATION_OPTIONS:
        return text
    folded = _fold_choice(text)
    if folded in {'sale', 'sell', 'selling'} or any(token in folded for token in ('بيع', 'شراء', 'تمليك')):
        return 'بيع'
    if folded in {'rent', 'rental', 'leasing'} or any(token in folded for token in ('ايجار', 'تاجير', 'تأجير')):
        return 'إيجار'
    if folded in {'hotel', 'hospitality'} or any(token in folded for token in ('فندقي', 'فندق', 'ليله', 'hotel')):
        return 'تشغيل فندقي'
    if folded in {'تشغيل', 'تشغيل فندقي', 'hotel operation'} or folded.startswith('تشغيل '):
        return 'تشغيل فندقي'
    if text:
        return 'أخرى'
    price_folded = _fold_choice(price_type)
    if any(token in price_folded for token in ('ايجار', 'تاجير', 'rent')):
        return 'إيجار'
    if any(token in price_folded for token in ('ليله', 'adr', 'revpar', 'غرفه', 'hotel')):
        return 'تشغيل فندقي'
    if any(token in price_folded for token in ('بيع', 'سعر الوحدة', 'سعر الوحده', 'سعر المتر', 'sale', 'sell')):
        return 'بيع'
    if _fold_choice(project_type) == 'فندقي':
        return 'تشغيل فندقي'
    return ''


def _canonical_price_type(value, operation, price_from='', price_to='', price_value=''):
    text = _norm(value)
    options = PRICE_TYPE_BY_OPERATION.get(operation or 'أخرى', PRICE_TYPE_BY_OPERATION['أخرى'])
    if text in options:
        return text
    folded = _fold_choice(text)
    if any(token in folded for token in ('نطاق', 'range')) or price_from or price_to:
        return 'نطاق أسعار الغرف' if operation == 'تشغيل فندقي' else 'نطاق سعري'
    if any(token in folded for token in ('adr', 'متوسط سعر الغرف')):
        return 'متوسط سعر الغرفة ADR' if operation == 'تشغيل فندقي' else text
    if 'revpar' in folded or 'الايراد لكل غرفه' in folded:
        return 'الإيراد لكل غرفة RevPAR' if operation == 'تشغيل فندقي' else text
    if any(token in folded for token in ('ليله', 'night')):
        return 'سعر الليلة' if operation == 'تشغيل فندقي' else text
    if 'يبدأ' in text or 'starting' in folded:
        return 'يبدأ من' if operation in ('بيع', 'إيجار') else text
    if 'سعر المتر المربع' in text or 'سعر المتر' in text or 'price per sqm' in folded:
        if operation == 'بيع':
            return 'سعر المتر المربع'
        if operation == 'إيجار':
            return 'إيجار المتر السنوي' if any(token in folded for token in ('سنوي', 'annual', 'year')) else 'إيجار المتر الشهري'
    if 'الوحدة' in text or 'unit' in folded:
        if operation == 'بيع':
            return 'سعر الوحدة'
        if operation == 'إيجار':
            return 'إيجار الوحدة السنوي' if any(token in folded for token in ('سنوي', 'annual', 'year')) else 'إيجار الوحدة الشهري'
    if text:
        return text
    if price_value:
        return 'أخرى'
    return ''


def audience_kind_for_label(label):
    text = _norm(label)
    if text in ('مكاتب', 'إداري'):
        return 'مكاتب'
    if text in ('تجزئة ومحلات', 'مطاعم ومقاهي', 'مركز تجاري', 'تجاري'):
        return 'تجزئة'
    if text in ('فندق', 'شقق مخدومة', 'منتجع', 'مساكن فندقية', 'فندقي'):
        return 'فندقي'
    if text in ('مصنع', 'مستودعات', 'مركز لوجستي', 'مجمع صناعي', 'صناعي ولوجستي', 'صناعي', 'لوجستي'):
        return 'صناعي ولوجستي'
    if text == 'سكني':
        return 'سكني'
    return ''


def analysis_kind_for_project(main_type, subtype='', components=None):
    main = _norm(main_type)
    if main == 'أخرى':
        main = 'متعدد الاستخدامات'
    sub = _norm(subtype)
    subtype_list = parse_selected_list(sub)
    extra = parse_selected_list(components)
    kinds = []

    def add_kind(label):
        kind = audience_kind_for_label(label)
        if kind and kind not in kinds:
            kinds.append(kind)

    if main == 'متعدد الاستخدامات':
        for item in extra or subtype_list:
            add_kind(item)
        return kinds
    if main == 'تجاري':
        for item in subtype_list:
            add_kind(item)
        return kinds
    if main == 'فندقي':
        return ['فندقي'] if subtype_list else []
    if main == 'صناعي ولوجستي':
        return ['صناعي ولوجستي'] if subtype_list else []
    if main == 'سكني':
        return ['سكني']
    add_kind(sub or main)
    return kinds


def activity_class_options(main_type, subtype='', components=None):
    kinds = analysis_kind_for_project(main_type, subtype, components)
    options = []
    seen = set()
    mapping = {
        'فندقي': ACTIVITY_CLASS_BY_TYPE['فندقي'],
        'مكاتب': ACTIVITY_CLASS_BY_TYPE['مكاتب'],
        'صناعي ولوجستي': ACTIVITY_CLASS_BY_TYPE['صناعي ولوجستي'],
    }
    specialized = False
    for kind in kinds:
        for option in mapping.get(kind, []):
            specialized = True
            if option not in seen:
                seen.add(option)
                options.append(option)
    if specialized:
        return options
    return [item['label'] for item in PROJECT_LEVELS]


def target_audience_options(main_type, subtype='', components=None):
    kinds = analysis_kind_for_project(main_type, subtype, components)
    if not kinds:
        return list(GENERAL_TARGET_AUDIENCE)
    options = []
    seen = set()
    for kind in kinds:
        for option in TARGET_AUDIENCE_BY_KIND.get(kind, []):
            if option not in seen:
                seen.add(option)
                options.append(option)
    return options


def price_types_for_operation(operation):
    return list(PRICE_TYPE_BY_OPERATION.get(_norm(operation), PRICE_TYPE_BY_OPERATION['أخرى']))


def price_uses_range(price_type):
    return _norm(price_type) in RANGE_PRICE_TYPES


def resolve_competitor_radius_km(radius_value, custom_km=None):
    value = _norm(radius_value) or '10'
    if value == 'auto':
        value = '10'
    if value == 'city':
        return None
    if value == 'custom':
        try:
            number = float(custom_km)
        except (TypeError, ValueError):
            return DEFAULT_COMPETITOR_RADIUS_KM
        return number if number > 0 else DEFAULT_COMPETITOR_RADIUS_KM
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_COMPETITOR_RADIUS_KM
    return number if number > 0 else DEFAULT_COMPETITOR_RADIUS_KM


def parse_selected_list(value):
    if isinstance(value, list):
        return [_norm(item) for item in value if _norm(item)]
    text = _norm(value)
    if not text:
        return []
    if text.startswith('['):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [_norm(item) for item in parsed if _norm(item)]
        except Exception:
            pass
    return [part.strip() for part in re.split(r'[,،\n;|]', text) if part.strip()]


def empty_competitor(source='manual'):
    return {
        'id': str(uuid.uuid4()),
        'name': '',
        'project_type': '',
        'area_mode': 'fixed',
        'area_sqm': '',
        'area_from': '',
        'area_to': '',
        'status': '',
        'classification': '',
        'logo_file_id': '',
        'logo_path': '',
        'logo_url': '',
        'logo_source_url': '',
        'district': '',
        'distance_km': '',
        'lat': '',
        'lng': '',
        'conflict_warnings': [],
        'operation_type': '',
        'price_type': '',
        'price_value': '',
        'price_from': '',
        'price_to': '',
        'source': '',
        'source_url': '',
        'source_urls': [],
        'field_sources': {},
        'data_date': '',
        'row_source': source,
    }


def empty_summary():
    return {item['key']: '' for item in SUMMARY_SECTIONS}


def empty_swot():
    return {item['key']: '' for item in SWOT_SECTIONS}


def summary_prose(value):
    """The market summary as one prose paragraph.

    This helper creates the executive paragraph from either the new structured
    analysis or an older paragraph/string value. It skips empty placeholders
    and the decision, which remains in its own field.
    """
    if isinstance(value, str):
        return re.sub(r'\s+', ' ', str(value)).strip()
    if isinstance(value, dict):
        parts = []
        for item in SUMMARY_SECTIONS:
            text = _norm(value.get(item['key']))
            if text and text != MISSING_VALUE_PHRASE:
                parts.append(re.sub(r'\s+', ' ', text))
        return ' '.join(parts).strip()
    return ''


def summary_has_content(value):
    """Return whether the detailed market analysis has a real value."""
    if isinstance(value, dict):
        return any(
            _norm(value.get(item['key'])) and _norm(value.get(item['key'])) != MISSING_VALUE_PHRASE
            for item in SUMMARY_SECTIONS
        )
    text = _norm(value)
    return bool(text and text != MISSING_VALUE_PHRASE)


def is_market_summary_paragraph(value):
    """Identify the prose executive summary versus the old headed block."""
    text = str(value or '').replace('\\r\\n', '\n').replace('\\n', '\n').strip()
    if not text:
        return False
    if re.search(r'(?m)^\s*\d+[.)]\s+', text):
        return False
    headings = {
        'نطاق دراسة السوق', 'نطاق الدراسة', 'المنافسون', 'تحليل السوق',
        'تحليل SWOT', 'المصادر', 'مصادر دراسة السوق', 'القرار',
        'إخلاء المسؤولية', 'ملخص دراسة سوق العمل', SUMMARY_TITLE,
    }
    return not any(line.strip().rstrip(':：') in headings for line in text.splitlines() if line.strip())


_GENERIC_SOURCE_PATHS = {
    '', '/', '/en', '/ar', '/en/', '/ar/', '/index.html', '/index.php',
    '/home', '/home/', '/ar/home', '/en/home',
}


def is_generic_source_homepage(url):
    text = str(url or '').strip()
    if not text:
        return False
    parsed = urlsplit(text)
    if not parsed.netloc:
        return False
    path = (parsed.path or '').rstrip('/') or '/'
    return (path.lower() in _GENERIC_SOURCE_PATHS or path.lower() in {'/', ''}) and not parsed.query and not parsed.fragment


def _source_host(url):
    return (urlsplit(str(url or '')).netloc or '').lower().removeprefix('www.')


def resolve_source_url_from_citations(url, citations, operation=''):
    """Replace a homepage with the retrieved page the search actually returned.

    The model tends to quote a site's front page from memory even when the figure
    came from a deep page, and the client needs the exact page. When no deeper
    same-host page was retrieved, known indicator portals still resolve to the
    fixed dataset view matching the row's operation.
    """
    value = _norm(url)
    pages = [_norm(item) for item in (citations or []) if _norm(item).startswith(('http://', 'https://'))]
    pages = [item for item in pages if not is_generic_source_homepage(item)]
    if value and not is_generic_source_homepage(value):
        return value
    host = _source_host(value)
    if host:
        same_host = next((item for item in pages if _source_host(item) == host), '')
        if same_host:
            return same_host
    return canonical_index_source_url(value, operation)


def prefer_specific_source_url(*candidates):
    values = [_norm(item) for item in candidates if _norm(item)]
    for value in values:
        if value.startswith(('http://', 'https://')) and not is_generic_source_homepage(value):
            return value
    return next((value for value in values if value.startswith(('http://', 'https://'))), values[0] if values else '')


# Indicator portals whose homepage is a navigation shell: the figures live on a
# fixed dataset page, so a bare-domain citation is normalized to the page that
# actually exposes the row's numbers instead of a shell that shows nothing.
_PORTAL_DATASET_PAGES = {
    'rei.rega.gov.sa': {
        'بيع': 'https://rei.rega.gov.sa/ar/advanced-search/deals',
        'إيجار': 'https://rei.rega.gov.sa/ar/advanced-search/rental-market/detailed-indicator',
        'default': 'https://rei.rega.gov.sa/ar/advanced-search/live',
    },
    'sakani.sa': {
        'default': 'https://sakani.sa/reports-and-data',
    },
}
