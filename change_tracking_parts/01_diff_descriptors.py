

def _watermark_state(html):
    """Visible/hidden/absent state of the per-slide watermark layer."""
    source = str(html or '')
    match = _WATERMARK_RE.search(source)
    if not match:
        return 'absent'
    tag = match.group(0)
    visible_attr = re.search(r'data-watermark-visible\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
    if visible_attr and visible_attr.group(1).strip().lower() == 'false':
        return 'hidden'
    if re.search(r'display\s*:\s*none', tag, re.IGNORECASE):
        return 'hidden'
    return 'visible'

MAX_LINES = 60
MAX_TEXT_IN_LINE = 120


def _text_of(html):
    """The reading text of a slide, with markup and inline CSS removed."""
    text = _TAG_RE.sub(' ', str(html or ''))
    text = text.replace('&nbsp;', ' ')
    return _WS_RE.sub(' ', text).strip()


def _images_of(html):
    source = str(html or '')
    # The watermark overlay carries its own <img>; it is reported as a
    # watermark line above, never as a generic photo count change.
    source = re.sub(
        r'<div\b[^>]*\bdata-slide-watermark=["\']true["\'][^>]*>[\s\S]*?</div\s*>',
        '', source, flags=re.IGNORECASE,
    )
    source = re.sub(
        r'<div\b[^>]*\bclass=["\'][^"\']*\bslide-watermark\b[^"\']*["\'][^>]*>[\s\S]*?</div\s*>',
        '', source, flags=re.IGNORECASE,
    )
    found = _IMG_SRC_RE.findall(source) + _BG_URL_RE.findall(source)
    return [_URL_BUSTER_RE.sub('', item.strip()) for item in found if item.strip()]


def _shorten(text, limit=MAX_TEXT_IN_LINE):
    text = _WS_RE.sub(' ', str(text or '')).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + '…'


def _sentences(text):
    parts = re.split(r'(?<=[.!؟?])\s+|\n+|\s{2,}|\s*\|\s*', str(text or ''))
    return [part.strip() for part in parts if part.strip()]


def _text_difference_lines(old_text, new_text):
    """Which phrases left and which arrived, rather than a character-level diff."""
    old_parts = _sentences(old_text)
    new_parts = _sentences(new_text)
    if not old_parts and not new_parts:
        return []
    matcher = difflib.SequenceMatcher(None, old_parts, new_parts)
    removed, added = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ('replace', 'delete'):
            removed.extend(old_parts[i1:i2])
        if tag in ('replace', 'insert'):
            added.extend(new_parts[j1:j2])
    lines = []
    if removed:
        lines.append('حُذف نص: ' + _shorten(' | '.join(removed)))
    if added:
        lines.append('أُضيف نص: ' + _shorten(' | '.join(added)))
    return lines


def _slide_label(index, slide):
    title = ''
    if isinstance(slide, dict):
        title = str(slide.get('title') or '').strip()
    return f'الشريحة {index + 1}' + (f' ({_shorten(title, 40)})' if title else '')


def _slide_html(slide):
    return str(slide.get('html') or '') if isinstance(slide, dict) else str(slide or '')


def describe_slide_changes(old_slides, new_slides):
    """Readable lines for what changed between two decks."""
    old_list = old_slides if isinstance(old_slides, list) else []
    new_list = new_slides if isinstance(new_slides, list) else []
    lines = []

    def slide_identity(slide):
        item = slide if isinstance(slide, dict) else {}
        explicit = str(item.get('id') or item.get('slideId') or '').strip()
        if explicit:
            return 'id:' + explicit
        return '|'.join((
            str(item.get('title') or '').strip(),
            str(item.get('type') or '').strip(),
            str(item.get('content_source') or item.get('contentSource') or '').strip(),
        ))

    old_order = [slide_identity(slide) for slide in old_list]
    new_order = [slide_identity(slide) for slide in new_list]
    if (len(old_order) == len(new_order) and old_order != new_order
            and sorted(old_order) == sorted(new_order) and all(old_order)):
        lines.append('أُعيد ترتيب الشرائح')
        for new_index, identity in enumerate(new_order):
            old_index = old_order.index(identity)
            if old_index != new_index:
                lines.append(f'{_slide_label(new_index, new_list[new_index])}: نُقلت من الموضع {old_index + 1} إلى {new_index + 1}')

    if len(new_list) != len(old_list):
        lines.append(f'عدد الشرائح: من {len(old_list)} إلى {len(new_list)}')

    for index in range(min(len(old_list), len(new_list))):
        old_slide = old_list[index] if isinstance(old_list[index], dict) else {}
        new_slide = new_list[index] if isinstance(new_list[index], dict) else {}
        label = _slide_label(index, new_slide or old_slide)
        slide_lines = []

        old_title = str(old_slide.get('title') or '').strip()
        new_title = str(new_slide.get('title') or '').strip()
        if old_title != new_title:
            slide_lines.append(f'العنوان: من «{_shorten(old_title, 60) or "بدون"}» '
                               f'إلى «{_shorten(new_title, 60) or "بدون"}»')

        old_html = _slide_html(old_slide)
        new_html = _slide_html(new_slide)
        # Compare without media signatures/cache-busters: the same slide re-saved
        # after a fresh round of ?s= signing is not a content change.
        if _URL_BUSTER_RE.sub('', old_html) != _URL_BUSTER_RE.sub('', new_html):
            old_mark, new_mark = _watermark_state(old_html), _watermark_state(new_html)
            if old_mark != new_mark:
                if old_mark == 'absent' and new_mark == 'visible':
                    slide_lines.append('العلامة المائية: أُظهرت')
                elif old_mark == 'hidden' and new_mark == 'visible':
                    slide_lines.append('العلامة المائية: أُظهرت مجددًا')
                elif new_mark == 'hidden' and old_mark == 'visible':
                    slide_lines.append('العلامة المائية: أُخفيت')
                elif new_mark == 'absent' and old_mark in ('visible', 'hidden'):
                    slide_lines.append('العلامة المائية: أُزيلت')
                elif old_mark == 'absent' and new_mark == 'hidden':
                    slide_lines.append('العلامة المائية: أُضيفت مخفية')
            old_text, new_text = _text_of(old_html), _text_of(new_html)
            if old_text != new_text:
                slide_lines.extend(_text_difference_lines(old_text, new_text))
            old_images, new_images = _images_of(old_html), _images_of(new_html)
            if old_images != new_images:
                if len(new_images) > len(old_images):
                    slide_lines.append(f'الصور: من {len(old_images)} إلى {len(new_images)}')
                elif len(new_images) < len(old_images):
                    slide_lines.append(f'الصور: من {len(old_images)} إلى {len(new_images)}')
                else:
                    slide_lines.append('استُبدلت صورة أو خريطة')
            old_marks = set(_PLACEHOLDER_RE.findall(old_html))
            new_marks = set(_PLACEHOLDER_RE.findall(new_html))
            if new_marks - old_marks:
                slide_lines.append('أُضيف عنصر: ' + '، '.join(sorted(new_marks - old_marks)))
            if old_marks - new_marks:
                slide_lines.append('أُزيل عنصر: ' + '، '.join(sorted(old_marks - new_marks)))
            if not slide_lines:
                # Same text, same images: only the styling moved.
                styled_old = _STYLE_RE.sub('', old_html)
                styled_new = _STYLE_RE.sub('', new_html)
                slide_lines.append('تغيّر التنسيق والألوان بدون تغيير النص'
                                   if styled_old == styled_new else 'تغيّر تخطيط الشريحة')

        old_style = str(old_slide.get('designStyle') or old_slide.get('design_style') or '')
        new_style = str(new_slide.get('designStyle') or new_slide.get('design_style') or '')
        if old_style != new_style and (old_style or new_style):
            slide_lines.append(f'نمط التصميم: من «{old_style or "غير محدد"}» إلى «{new_style or "غير محدد"}»')

        for line in slide_lines:
            lines.append(f'{label}: {line}')

    for index in range(len(old_list), len(new_list)):
        lines.append(f'أُضيفت {_slide_label(index, new_list[index])}')
    for index in range(len(new_list), len(old_list)):
        lines.append(f'حُذفت {_slide_label(index, old_list[index])}')

    if len(lines) > MAX_LINES:
        remaining = len(lines) - MAX_LINES
        lines = lines[:MAX_LINES] + [f'و{remaining} تغييرًا آخر']
    return lines


# Draft keys that carry machinery rather than a fact the reader entered. Their change is reported as
# one line naming the area, never as a value.
DRAFT_BLOB_LABELS = {
    'financial_study_model': 'الدراسة المالية',
    'financial_calc_data': 'حسابات الدراسة المالية',
    'market_study_data': 'دراسة السوق',
    'executive_content': 'المحتوى التنفيذي',
    'team_selection': 'فريق العمل',
    'visual_concept': 'التصور البصري',
    'land_documents_analysis': 'تحليل مستندات الأرض',
    'timeline_table_data': 'الجدول الزمني',
    'project_components_data': 'مكونات المشروع',
    'nearby_landmarks_data': 'المعالم القريبة',
    'coordinate_tables': 'جداول الإحداثيات',
    'survey_coordinates': 'إحداثيات المساحة',
    'directions_table': 'جدول الحدود والأطوال',
    'tenantCreativeImages': 'صور العرض',
    'tenantSlidesData': 'شرائح العرض',
    'tenantSlidePlan': 'هيكل العرض',
    'pageDrafts': 'حالة الصفحات',
    'map_styles': 'أنماط الخرائط',
    'landmarks_matrix': 'مسافات المعالم',
    'site_analysis': 'تحليل الموقع',
    'location_detail': 'تفاصيل الموقع',
    'location_polygon': 'مضلع الموقع',
    'parcels': 'قطع الأرض',
    'warnings': 'التنبيهات',
    'regulation_evidence': 'الأدلة التنظيمية',
    'access_roads_data': 'بيانات طرق الوصول',
    'main_roads_data': 'بيانات الطرق الرئيسية',
    'city_landmarks_data': 'بيانات معالم المدينة',
    'catchment_map_landmarks': 'معالم خريطة التغطية',
    'landmark_map_items': 'عناصر خريطة المعالم',
    'manual_road_paths': 'مسارات الطرق اليدوية',
    'source_priority': 'أولوية المصادر',
    'land_use': 'استخدام الأرض',
}

# Scalar draft keys with no PREBUILT_FIELDS row of their own — still worth a readable name.
DRAFT_SCALAR_LABELS = {
    'timeline_start_date': 'تاريخ بداية المشروع',
    'timeline_start_year': 'سنة بداية المشروع',
    'timeline_years': 'عدد سنوات المشروع',
}

DRAFT_IGNORED_KEYS = {
    'draftId', 'draft_id', 'sectionStatuses', 'regen_seed', 'refresh_maps',
    'updated_at', 'created_at', 'revision',
    # Machinery that is rewritten on every save or chat turn — its churn used to
    # fill the log with «تم تحديث البيانات» lines that said nothing.
    'designerChat', 'slide_generation_checkpoint', 'calculate_landmark_driving',
    # The ##MAP_*## token → url map: regenerated maps re-stamp it, and real map
    # work already lands in the log through its own «توليد خريطة» entries.
    'map_placeholders',
    # Rebuilt from other blobs on every save (section statuses mirror, cover,
    # moodboard, slides flags) — a second copy of changes already diffed at
    # their source.
    'pageDrafts',
}

# Draft keys ending like this are bookkeeping, not reader content.
DRAFT_IGNORED_SUFFIXES = ('_file_meta', '_file_ids', '_file_id', '_label_positions',
                          '_label_sizes', '_signature')

# Blobs that mirror data already diffed elsewhere — one honest line at most,
# never a second copy of the same table changes.
DRAFT_BLOB_QUIET = {
    'financial_calc_data': 'أُعيد احتساب نتائج الدراسة',
}

# Per-blob wording for list-of-strings diffs: key maps to (removed verb, added verb).
# «excluded» gains an id when an entity leaves the file and loses one when it
# comes back — plain حُذف/أُضيف would read backwards there.
DRAFT_BLOB_LIST_VERBS = {
    'team_selection': {'excluded': ('أُعيدت للملف', 'استُبعدت من الملف')},
}

# Sub-keys inside a blob that are computed output, not entered data.
DRAFT_BLOB_INNER_SKIP = {
    'financial_study_model': {'financialCalcData', 'projection', 'tables'},
    'land_documents_analysis': {'extraction_diagnostics', 'document_processing', 'confidence'},
    'tenantCreativeImages': {'images_signature', 'last_error', 'last_warning',
                             'map_placeholders'},
    'tenantSlidePlan': {'source_error'},
    'visual_concept': {'chat', 'promptReady', 'promptsError', 'images_signature',
                       'last_error', 'last_warning', 'deletedInteriorSlots',
                       # A slot's status only mirrors its approvedImageUrl
                       # transitions — the approval line already says it.
                       'status'},
}

# Labels for keys inside structured blobs: table names, row fields and the
# financial study inputs (mirroring the form labels in 09-financial.js).
BLOB_KEY_LABELS = {
    # financial study structure
    'dynamicRows': '',  # flat wrapper: its children carry the real table names
    'components': 'جدول المكونات', 'revenue': 'جدول الإيرادات', 'revenues': 'جدول الإيرادات',
    'costs': 'جدول التكاليف', 'opex': 'جدول المصروفات التشغيلية',
    'schedule': 'جدول مراحل التطوير', 'external': 'البنود الخارجية',
    'financeDraw': 'جدول سحب التمويل', 'financeRepayment': 'جدول سداد التمويل',
    'fundAdditionalFees': 'رسوم الصندوق الإضافية', 'graceSchedule': 'جدول فترة السماح',
    'occupancyRamp': 'جدول الوصول للإشغال', 'sensitivity': 'تحليل الحساسية',
    'sensitivityAssumptionsTable': 'جدول افتراضات الحساسية',
    'inputs': 'مدخلات الدراسة',
    # financial inputs
    'unitRevenueMode': 'نمط وحدات المشروع (بيعية/تأجيرية)',
    'developmentYears': 'مدة تطوير المشروع (سنة)', 'salesStartYear': 'سنة بدء بيع الوحدات',
    'salesYears': 'عدد سنوات بيع الوحدات', 'operationYears': 'عدد سنوات التشغيل',
    'operationStartYear': 'سنة بدء التشغيل', 'landArea': 'مساحة الأرض م²',
    'coverageRate': 'نسبة التغطية %', 'floorCount': 'عدد الطوابق',
    'builtUpAreaAbove': 'مسطحات البناء فوق الأرض م²', 'basementArea': 'مساحة البدرومات م²',
    'totalBuiltUpArea': 'إجمالي مسطحات البناء م²', 'coveredArea': 'المساحة المغطاة م²',
    'openArea': 'المساحات المفتوحة م²', 'landValueMethod': 'طريقة احتساب قيمة الأرض',
    'manualLandValue': 'قيمة الأرض اليدوية', 'landStatus': 'حالة الأرض',
    'landContributionType': 'معالجة الأرض في التدفقات', 'landContributionYear': 'سنة تسجيل الأرض',
    'landRentMethod': 'طريقة احتساب إيجار الأرض', 'landRentRate': 'نسبة إيجار الأرض السنوي %',
    'manualAnnualLandRent': 'إيجار الأرض السنوي', 'monthlyLandRent': 'إيجار الأرض الشهري',
    'landValue': 'قيمة الأرض المحسوبة', 'annualLandRent': 'إيجار الأرض السنوي المحسوب',
    'graceEnabled': 'تطبيق فترة سماح', 'graceMethod': 'طريقة احتساب السماح',
    'graceScope': 'نطاق فترة السماح', 'graceRevenueId': 'الإيراد المشمول',
    'graceStartYear': 'سنة بداية السماح', 'graceDurationMonths': 'مدة السماح (شهر)',
    'graceDiscountRate': 'نسبة الخصم خلال السماح %', 'graceTotalDiscount': 'إجمالي خصم فترة السماح',
    'developerRate': 'نسبة المطور %', 'developerBase': 'أساس احتساب نسبة المطور',
    'developerBaseAmount': 'قيمة أساس المطور', 'developerCostValue': 'إجمالي أتعاب المطور',
    'developerPaymentsEnabled': 'مراحل تطوير ودفعات المطور',
    'developerBonusEnabled': 'علاوة حسن أداء المطور', 'developerUpliftShare': 'نسبة المطور من الزيادة في سعر البيع %',
    'executionCostTotal': 'إجمالي تكلفة التنفيذ', 'designCostTotal': 'التصميم والدراسات',
    'servicesCostTotal': 'رسوم الخدمات', 'advertisingCostTotal': 'الدعاية والإعلان',
    'landCostIncluded': 'قيمة الأرض داخل التكلفة', 'landRentSummary': 'إيجار الأرض السنوي',
    'financeEnabled': 'استخدام تمويل', 'financeBase': 'أساس احتساب التمويل',
    'financingRate': 'نسبة التمويل من تكلفة المشروع %', 'financeArrangementFeeRate': 'رسوم ترتيب التمويل %',
    'financeInterestMethod': 'طريقة احتساب الفائدة', 'annualFinanceRate': 'معدل الفائدة السنوي %',
    'financeDrawYears': 'عدد سنوات سحب التمويل', 'financeRepaymentStartYear': 'سنة بدء سداد التمويل',
    'financeRepaymentYears': 'عدد سنوات التمويل والسداد', 'financeBaseAmount': 'قيمة أساس التمويل',
    'facilityAmount': 'قيمة التسهيل التمويلي', 'arrangementFeeTotal': 'رسوم ترتيب التمويل',
    'financeInterestTotal': 'إجمالي فوائد التمويل', 'landEquityContribution': 'مساهمة الأرض العينية',
    'cashEquityRequired': 'الضخ النقدي المطلوب', 'equityRequired': 'إجمالي حقوق الملكية',
    'fundEnabled': 'وجود صندوق للمشروع', 'fundFeesEnabled': 'تطبيق أتعاب إدارة الصندوق',
    'fundFeeBase': 'أساس احتساب الأتعاب', 'fundCapitalInput': 'رأس مال الصندوق',
    'fundNavInput': 'صافي قيمة الأصول NAV', 'fundManagementRate': 'نسبة أتعاب الإدارة السنوية %',
    'fundFixedAnnualFee': 'مبلغ الأتعاب السنوي الثابت', 'fundFeeStartYear': 'سنة بداية الاحتساب',
    'fundFeeEndYear': 'سنة نهاية الاحتساب', 'fundFeeFrequency': 'دورية السداد',
    'fundFeeTiming': 'توقيت السداد', 'fundFeeGrowthRate': 'نسبة الزيادة السنوية في الأتعاب %',
    'fundManagementFeesTotal': 'إجمالي أتعاب الإدارة المحسوبة', 'fundExitFeeEnabled': 'تطبيق أتعاب التخارج',
    'fundExitFeeBase': 'أساس احتساب أتعاب التخارج', 'fundExitFeeRate': 'نسبة أتعاب التخارج %',
    'fundExitFixedFee': 'مبلغ أتعاب التخارج الثابت', 'fundFeesTotal': 'إجمالي تكاليف الصندوق',
    'performanceFeeEnabled': 'تطبيق حافز أداء', 'hurdleRate': 'الحد الأدنى للعائد %',
    'hurdleMethod': 'طريقة احتساب الحد الأدنى', 'performanceFeeRate': 'نسبة حافز الأداء %',
    'performanceFeeBase': 'أساس الاحتساب', 'catchupEnabled': 'تطبيق الاستدراك',
    'catchupRate': 'نسبة الاستدراك %', 'performanceCrystallizationYear': 'سنة احتساب حافز الأداء',
    'performanceFeeTotal': 'إجمالي حافز الأداء المحسوب', 'externalEnabled': 'بنود خارجية مرنة',
    'exitEnabled': 'تطبيق التخارج', 'saleExitMethod': 'طريقة التخارج البيعي',
    'saleExitYear': 'سنة التخارج البيعي', 'saleExitRemainingArea': 'المساحة البيعية المتبقية م²',
    'saleExitAreaReference': 'المساحة البيعية في بنود الإيرادات م²',
    'saleExitFixedValue': 'قيمة التخارج البيعي الثابتة', 'saleExitCostRate': 'تكاليف التخارج البيعي %',
    'exitMethod': 'طريقة التخارج التشغيلي', 'operatingExitYear': 'سنة التخارج التشغيلي',
    'exitInput': 'معدل الرسملة / المضاعف / القيمة', 'operatingExitCostRate': 'تكاليف التخارج التشغيلي %',
    'settleDebtAtExit': 'سداد رصيد التمويل عند التخارج', 'roiPeriod': 'فترة احتساب ROI',
    'roiEndYear': 'آخر سنة في ROI', 'irrPeriod': 'فترة احتساب IRR',
    'irrEndYear': 'آخر سنة في IRR', 'sensitivityVariableSelect': 'المتغير المراد اختباره',
    'financialClarifications': 'الإيضاحات',
    # row fields shared by the dynamic tables
    'name': 'الاسم', 'useType': 'نوع الاستخدام', 'units': 'عدد الوحدات',
    'unitArea': 'مساحة الوحدة', 'builtArea': 'المساحة المبنية',
    'revenueArea': 'المساحة البيعية / التأجيرية', 'totalArea': 'المساحة الإجمالية',
    'investmentModel': 'نموذج الاستفادة', 'leasable': 'قابل للتأجير',
    'qty': 'الكمية', 'qtySource': 'مصدر الكمية', 'price': 'السعر',
    'period': 'الفترة', 'method': 'طريقة الاحتساب', 'formula': 'المعادلة',
    'customFormula': 'المعادلة المخصصة', 'component': 'المكون المرتبط',
    'componentId': 'المكون المرتبط', 'occupancy': 'نسبة الإشغال',
    'year': 'السنة', 'startYear': 'سنة البداية', 'endYear': 'سنة النهاية',
    'drawPct': 'نسبة السحب', 'repaymentPct': 'نسبة السداد', 'costPct': 'نسبة التكلفة',
    'devPct': 'نسبة التطوير', 'operationYear': 'سنة التشغيل', 'studyYear': 'سنة الدراسة',
    'reachPct': 'نسبة الوصول', 'class': 'الفئة', 'duration': 'المدة',
    'recurrence': 'التكرار', 'value': 'القيمة', 'key': 'المتغير',
    'low': 'متحفظ', 'high': 'متفائل', 'quarter': 'الربع', 'endQuarter': 'ربع النهاية',
    'amount': 'المبلغ', 'base': 'الأساس', 'growth': 'نسبة النمو السنوي %',
    'notes': 'ملاحظات',
    # land / croquis tables
    'rows': 'الصفوف', 'point': 'النقطة', 'eastings': 'الإحداثي الشرقي',
    'northings': 'الإحداثي الشمالي', 'parcel_id': 'القطعة', 'source': 'المصدر',
    'direction': 'الاتجاه', 'label': 'الاسم', 'regulation_text': 'النص التنظيمي',
    'boundary_length_m': 'طول الحد', 'street_name': 'اسم الشارع',
    'issues': 'الملاحظات', 'distribution': 'التوزيع', 'boundary': 'حدود الأرض',
    'points': 'النقاط', 'floorRange': 'الأدوار', 'building': 'المبنى',
    'floors': 'عدد الأدوار', 'area': 'المساحة', 'prompts': 'الطلبات',
    'street_width_m': 'عرض الشارع', 'parcels': 'القطع', 'conflicts': 'التعارضات',
    'document_summary': 'ملخص المستندات',
    # market study
    'competitors': 'المنافسون', 'summary': 'الملخص', 'swot': 'تحليل SWOT',
    'sources': 'المصادر', 'decision': 'القرار', 'one_block_summary': 'الملخص المختصر',
    'disclaimer': 'إخلاء المسؤولية', 'competitor_radius': 'نطاق البحث عن المنافسين',
    'competitor_radius_custom_km': 'نطاق البحث المخصص (كم)', 'data_period': 'فترة البيانات',
    'data_period_from': 'بداية الفترة', 'data_period_to': 'نهاية الفترة',
    'project_type': 'نوع المشروع', 'status': 'الحالة', 'strengths': 'نقاط القوة',
    'weaknesses': 'نقاط الضعف', 'opportunities': 'الفرص', 'threats': 'التهديدات',
    'distance_km': 'المسافة (كم)', 'distance_text': 'المسافة',
    'duration_min': 'المدة (دقيقة)', 'duration_minutes': 'المدة (دقيقة)',
    'category': 'الفئة', 'show_on_map': 'يظهر على الخريطة', 'in_traffic': 'داخل الزحام',
    'area_sqm': 'المساحة (م²)', 'area_mode': 'نمط المساحة', 'area_from': 'المساحة من',
    'area_to': 'المساحة إلى',
    # executive content / team / misc
    'brief': 'النبذة', 'opportunity': 'الفرصة الاستثمارية', 'features': 'المميزات',
    'risks': 'المخاطر', 'roles': 'دور الجهة في الملف', 'excluded': 'الجهات',
    'local': 'جهات خاصة بالمشروع', 'role': 'الدور', 'company': 'الشركة',
    'experienceYears': 'سنوات الخبرة', 'notableProjects': 'أبرز المشاريع',
    'logoFileId': 'الشعار',
    'title': 'العنوان', 'description': 'الوصف', 'task': 'المهمة',
    'milestone': 'المرحلة', 'owner': 'المسؤول', 'progress': 'التقدم',
    'start': 'البداية', 'end': 'النهاية', 'approved': 'معتمد',
    'image': 'الصورة', 'prompt': 'الوصف', 'access': 'خريطة الوصول',
    'catchment': 'خريطة التغطية', 'landmarks': 'خريطة المعالم', 'overview': 'الخريطة العامة',
    'enabled': 'مفعّل', 'visible': 'ظاهر', 'slides': 'الشرائح',
    'proposed_count': 'عدد الشرائح المقترح', 'type': 'النوع', 'audience': 'الفئة المستهدفة',
    # generated-asset state (pageDrafts / visual_concept / creative images)
    'mainImage': 'الصورة الرئيسية', 'moodboard': 'لوحة المزاج', 'project': 'المشروع',
    'cover': 'الغلاف', 'competitor_logos': 'شعارات المنافسين', 'interior': 'اللقطات الداخلية',
    'interior_components': 'المكونات الداخلية', 'land_photos': 'صور الأرض',
    'map_access_roads': 'خريطة طرق الوصول', 'map_approvals': 'اعتمادات الخرائط',
    'map_catchment_landmarks': 'خريطة معالم التغطية', 'plans2d': 'المخططات ثنائية الأبعاد',
    'plansWorkflow': 'سير المخططات', 'slots': 'الخانات', 'deletedInteriorSlots': 'الخانات المحذوفة',
    'selectedInteriorComponentId': 'المكون الداخلي المحدد', 'styleReferenceName': 'النمط المرجعي',
    'styleReferenceNames': 'الأنماط المرجعية', 'images': 'الصور', 'urls': 'الروابط',
    'map_overview': 'الخريطة العامة', 'croquis': 'الكروكي',
    # file/image slots that can appear under row names
    'logo': 'الشعار', 'logo_path': 'الشعار', 'logo_url': 'الشعار',
    'image_path': 'الصورة', 'photo_path': 'الصورة', 'cover_path': 'الغلاف',
    'map_path': 'الخريطة', 'file_path': 'الملف',
    'imageUrl': 'الصورة', 'approvedImageUrl': 'الصورة المعتمدة',
    'caption': 'التسمية', 'mode': 'النمط', 'sourceFileName': 'الملف المرفوع',
    'styleReferenceNames': 'الصور المرجعية',
}

# Stored enum codes read back as the same Arabic words the form shows.
BLOB_VALUE_LABELS = {
    'sale': 'بيع وحدات', 'dailyRent': 'إيجار يومي', 'monthlyRent': 'إيجار شهري',
    'annualRent': 'إيجار سنوي', 'operating': 'تأجير آخر', 'nonRevenue': 'بدون إيراد',
    'residential': 'سكني', 'commercial': 'تجاري', 'offices': 'مكاتب',
    'retail': 'تجزئة', 'hotel': 'فندقي', 'hospitality': 'فندقي',
    'mixed': 'مختلط', 'services': 'خدمات', 'industrial': 'صناعي',
    'manual': 'إدخال يدوي', 'componentRevenueArea': 'المساحة البيعية / التأجيرية',
    'componentArea': 'المساحة البيعية / التأجيرية', 'componentBuiltArea': 'المساحة المبنية',
    'componentUnits': 'عدد الوحدات', 'yes': 'نعم', 'no': 'لا',
    'auto': 'تلقائي', 'fixed': 'ثابت', 'north': 'شمال', 'south': 'جنوب',
    'east': 'شرق', 'west': 'غرب', 'approved': 'معتمد', 'pending': 'قيد المراجعة',
    'draft': 'مسودة', 'ai': 'الذكاء الاصطناعي', 'user': 'يدوي',
    'upload': 'رفع ملف', 'replaced': 'استُبدلت',
}
