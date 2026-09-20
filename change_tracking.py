"""Turn two versions of a presentation or a project draft into readable Arabic change lines.

The history used to record one generic sentence — «تعديل المحتوى» — so a reader could not tell what
had changed, who had changed it, or whether a slide had lost content. Nothing compared two versions
anywhere in the codebase, and AI edits were not recorded at all.

Everything here is pure: it takes the old and the new value and returns lines. That keeps it
testable without a database, a request context, or a model.
"""

import difflib
import json
import re

import db

# A slide carries markup, inline styles and placeholders. Only the parts a reader would call content
# are compared; a pure styling change is reported as such instead of as a text change.
_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')
_STYLE_RE = re.compile(r'\sstyle\s*=\s*"[^"]*"', re.IGNORECASE)
_IMG_SRC_RE = re.compile(r'<img[^>]+src\s*=\s*"([^"]+)"', re.IGNORECASE)
_BG_URL_RE = re.compile(r'url\(\s*[\'"]?([^\'")]+)', re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r'##[A-Z0-9_]+##')
_WATERMARK_RE = re.compile(
    r'<div\b[^>]*\b(?:data-slide-watermark=["\']true["\']|class=["\'][^"\']*\bslide-watermark\b)[^>]*>',
    re.IGNORECASE,
)


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
    return [item.strip() for item in found if item.strip()]


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
        if old_html != new_html:
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
    'tenantCreativeImages': {'images_signature', 'last_error', 'last_warning'},
    'tenantSlidePlan': {'source_error'},
    'visual_concept': {'chat', 'promptReady', 'promptsError', 'images_signature',
                       'last_error', 'last_warning', 'deletedInteriorSlots'},
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

# Keys that never say anything a reader cares about inside a blob.
BLOB_SKIP_KEYS = {
    'id', 'idx', 'version', 'signature', 'created_at', 'updated_at', 'localId',
    'extraction_diagnostics', 'document_processing', 'confidence',
    'slide_generation_checkpoint', 'area_cache', 'row_source',
    'sourceFileId', 'styleReferenceFileIds',
}

# Image/file slots: the stored URL is noise — a change reads as a replacement.
BLOB_IMAGE_KEYS = {
    'image', 'imageUrl', 'image_url', 'src', 'logo', 'fileId', 'file_id',
    'fileName', 'file_name', 'cover', 'plan_image', 'photo', 'thumbnail',
    'logo_path', 'image_path', 'photo_path', 'map_path', 'cover_path',
    'approvedImageUrl', 'logoFileId', 'logo_file_id',
}

_BLOB_FILE_KEY_RE = re.compile(r'(?:_path|_url|_uri|_image|_logo|_photo|_file|_src)$', re.I)


def _is_imageish_change(key, old_v, new_v):
    """File/image slot even when the key is not in BLOB_IMAGE_KEYS: a *_path /
    *_url / *_logo style key whose stored value is a file path or URL."""
    if key in BLOB_IMAGE_KEYS:
        return True
    if not _BLOB_FILE_KEY_RE.search(str(key)):
        return False

    def looks_like_file(value):
        text = str(value or '').strip()
        return text.startswith(('/uploads/', 'http://', 'https://', 'data:image', 'data:'))

    return looks_like_file(old_v) or looks_like_file(new_v)

_INTERNAL_KEY_RE = re.compile(
    r'^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}|[a-z]+_\d{6,}|plan_[a-z0-9_]+)$')
# A stored row reference such as «p_1789906384606_497620a2685448» or a uuid —
# never readable on screen; resolve it to the referenced row's name instead.
_INTERNAL_ID_VALUE_RE = re.compile(
    r'^(?:[a-z]+_\d{6,}(?:_[0-9a-z]{4,})?|'
    r'(?=[a-z0-9_]*\d{4,})[a-z]+(?:_[a-z0-9]+)+|'
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$', re.I)
_URL_BUSTER_RE = re.compile(r'([?&](?:t|v|cb)=)[^&\s]+')
_MISSING = object()


def _parse_jsonish(value):
    """A stored JSON string behaves like the object it encodes."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if len(text) < 2 or text[0] not in '{[':
        return value
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return value
    return parsed if isinstance(parsed, (dict, list)) else value


def _norm_scalar(value):
    """Numbers compare by value; text compares normalized (cache-busters and spacing out)."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = _WS_RE.sub(' ', _URL_BUSTER_RE.sub(r'\1', value)).strip()
        try:
            return float(text.replace(',', ''))
        except ValueError:
            return text
    return _MISSING


def _values_equal(old, new):
    if old == new:
        return True
    old_n, new_n = _norm_scalar(old), _norm_scalar(new)
    if old_n is not _MISSING and new_n is not _MISSING:
        return old_n == new_n
    old_p, new_p = _parse_jsonish(old), _parse_jsonish(new)
    if (old_p, new_p) != (old, new):
        return _values_equal(old_p, new_p)
    return False


def _is_empty_value(value):
    return value is None or value == '' or value == {} or value == []


# Dict keys that are generated ids rather than names — search form so ids
# nested inside a longer key («interior_p_1789906…_1») are caught too.
_MACHINE_KEY_RE = re.compile(r'[a-z]+_\d{6,}|[0-9a-f]{8}-[0-9a-f]{4}|[a-z]+_[0-9a-f]{10,}', re.I)


def _child_row_name(child):
    """Display name carried inside a dict child (slots keep it in «label»)."""
    if not isinstance(child, dict):
        return ''
    for name_key in ('name', 'title', 'label', 'direction', 'point', 'street_name',
                     'milestone', 'task', 'company', 'role', 'year'):
        text = _blob_text(child.get(name_key))
        if text:
            return text
    return ''


def _blob_label(key, child=None):
    if key in BLOB_KEY_LABELS:
        return BLOB_KEY_LABELS[key]
    key_text = str(key)
    parsed = _parse_jsonish(child)
    # A machine-generated dict key («plan_site», a uuid, or a slot id like
    # «interior_p_1789906…_1») — or a key that is simply the child's own id
    # («right» → {id: 'right'}): the key is a row identifier, so name the row
    # instead — «الخانات › «الصورة الرئيسية»» rather than «أحد العناصر».
    if isinstance(parsed, dict):
        child_id = str(parsed.get('id') or parsed.get('key') or '').strip()
        if (_INTERNAL_KEY_RE.match(key_text) or _MACHINE_KEY_RE.search(key_text)
                or (child_id and child_id == key_text)):
            name = _child_row_name(parsed)
            return f'«{name}»' if name else 'أحد العناصر'
    if _INTERNAL_KEY_RE.match(key_text) or _MACHINE_KEY_RE.search(key_text):
        return 'أحد العناصر'
    return key_text


def _blob_text(value):
    """Readable text for one leaf value; '' for empty or unprintable values."""
    if _is_empty_value(value):
        return ''
    if isinstance(value, bool):
        return 'نعم' if value else 'لا'
    if isinstance(value, (int, float)):
        number = float(value)
        return str(int(number)) if number.is_integer() else str(value)
    if isinstance(value, (dict, list)):
        return ''
    text = str(value).strip()
    if not text or text.startswith('data:') or text.startswith('/uploads/'):
        return ''
    if _parse_jsonish(text) is not text:
        return ''
    return BLOB_VALUE_LABELS.get(text, _shorten(text))


def _collect_id_names(*roots):
    """id/key → display name for every row dict in the structures, so a stored
    reference («الإيراد المشمول: من «p_…» إلى «p_…»») reads as the row it points
    at. Both snapshots are scanned so a deleted row still resolves."""
    id_map = {}
    stack = [root for root in roots if isinstance(root, (dict, list))]
    while stack and len(id_map) < 1000:
        node = stack.pop()
        if isinstance(node, dict):
            row_id = str(node.get('id') or node.get('key')
                         or node.get('localId') or '').strip()
            if row_id and row_id not in id_map:
                for name_key in ('name', 'title', 'label', 'direction', 'point',
                                 'street_name', 'milestone', 'task', 'company',
                                 'role', 'year'):
                    text = _blob_text(node.get(name_key))
                    if text:
                        id_map[row_id] = text
                        break
            parsed_items = [(child_key, _parse_jsonish(child))
                            for child_key, child in node.items()]
            for child_key, child in parsed_items:
                # Slot-style dicts are keyed by the row id itself
                # («slots: {interior_p_…: {label: …}}») — map the key too, so a
                # bare id in a list («الخانات المحذوفة») still resolves.
                if isinstance(child, dict) and child_key not in id_map:
                    name = _child_row_name(child)
                    if name:
                        id_map[child_key] = name
            stack.extend(v for _, v in parsed_items if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            stack.extend(v for v in node if isinstance(v, (dict, list)))
    return id_map


def _ref_text(value, id_map, deleted=False, fallback=None):
    """Readable text for a leaf value, resolving stored row references to the
    referenced row's name. An unresolvable internal id reads as a removed/added
    item rather than dumping «p_1789906…» on screen."""
    raw = str(value or '').strip()
    if raw:
        if raw in id_map:
            return id_map[raw]
        if _INTERNAL_ID_VALUE_RE.match(raw):
            return 'عنصر محذوف' if deleted else 'عنصر مضاف'
    return (fallback or _blob_text)(value)


def _row_key(item):
    """Stable identity for a table row: its stored id, else its display name."""
    if isinstance(item, dict):
        explicit = str(item.get('id') or item.get('key')
                       or item.get('localId') or '').strip()
        if explicit:
            return 'id:' + explicit
        for key in ('name', 'title', 'label', 'direction', 'point', 'street_name',
                    'milestone', 'task', 'company', 'role', 'year'):
            value = str(item.get(key) or '').strip()
            if value:
                return 'name:' + value
    return None


def _row_label(item, index):
    if isinstance(item, dict):
        for key in ('name', 'title', 'label', 'direction', 'point', 'street_name',
                    'milestone', 'task', 'company', 'role', 'year'):
            text = _blob_text(item.get(key))
            if text:
                return f'«{text}»'
    return f'صف {index + 1}'


def _has_row_id(item):
    """A stored id/key is strong identity: an unmatched one means another row."""
    return isinstance(item, dict) and bool(
        str(item.get('id') or item.get('key')
            or item.get('localId') or '').strip())


def _match_rows(old_items, new_items):
    """Pair rows by id, then by name, then by order; report the leftovers."""
    pairs, remaining_new = [], set(range(len(new_items)))
    buckets = {}
    for index, item in enumerate(new_items):
        key = _row_key(item)
        if key:
            buckets.setdefault(key, []).append(index)
    unmatched_old = []
    for index, item in enumerate(old_items):
        key = _row_key(item)
        candidates = buckets.get(key) if key else None
        while candidates and candidates[0] not in remaining_new:
            candidates.pop(0)
        if candidates:
            match = candidates.pop(0)
            remaining_new.discard(match)
            pairs.append((index, match))
        else:
            unmatched_old.append(index)
    # Leftovers pair only at the same position (an in-place row edit); a row
    # removed mid-table or appended elsewhere reports as removed/added instead
    # of a fake rename between unrelated rows. Two leftover rows that both
    # carry ids are never the same row — a delete plus an insert at the same
    # position stays a removal and an addition, not a rename.
    if len(old_items) == len(new_items):
        for index in unmatched_old:
            if (index in remaining_new
                    and not (_has_row_id(old_items[index]) and _has_row_id(new_items[index]))):
                remaining_new.discard(index)
                pairs.append((index, index))
    matched_old = {index for index, _ in pairs}
    removed = [index for index in range(len(old_items)) if index not in matched_old]
    return sorted(pairs, key=lambda pair: pair[1]), removed, sorted(remaining_new)


def _path_head(path):
    return path[0] if path else ''


def _path_tail(path):
    return ' › '.join(part for part in path[1:] if part)


def _emit(out, path, text=None, field=None, old=None, new=None, kind='info'):
    if len(out) >= MAX_LINES:
        return
    item = {'group': _path_head(path), 'path': _path_tail(path), 'kind': kind}
    if field:
        item['field'] = field
        item['old'] = old or ''
        item['new'] = new or ''
        item['kind'] = 'change'
    if text:
        item['text'] = text
    out.append(item)


def _diff_blob(old, new, path, out, depth=0, extra_skip=(), state=None,
               list_verbs=None, verbs=None):
    """Walk two structured values and emit one detail item per real change."""
    if len(out) >= MAX_LINES or depth > 7:
        return
    old, new = _parse_jsonish(old), _parse_jsonish(new)
    if _values_equal(old, new):
        return
    id_map = state.get('id_map') if state else {}
    if isinstance(old, dict) and isinstance(new, dict):
        skip = set(BLOB_SKIP_KEYS) | set(extra_skip)
        for key in sorted(set(old) | set(new)):
            if (key in skip or str(key).startswith('_')
                    or str(key).endswith(('_file_meta', '_file_ids', '_file_id', '_signature'))):
                continue
            old_v, new_v = old.get(key), new.get(key)
            if _values_equal(old_v, new_v):
                continue
            # A difference at a describable key: even if no line survives below,
            # the caller's fallback knows this was a real change, not churn.
            if state is not None:
                state['saw'] = True
            # A key that is itself a stored row id («roles: {entity-uuid: role}»)
            # names the row it points at instead of printing the raw id.
            ref_name = id_map.get(str(key))
            label = (f'«{ref_name}»' if ref_name else
                     _blob_label(key, new_v if not _is_empty_value(_parse_jsonish(new_v)) else old_v))
            child_path = path + ([label] if label else [])
            if isinstance(_parse_jsonish(old_v), (dict, list)) or isinstance(_parse_jsonish(new_v), (dict, list)):
                _diff_blob(old_v, new_v, child_path, out, depth + 1,
                           extra_skip=extra_skip, state=state,
                           list_verbs=list_verbs,
                           verbs=(list_verbs or {}).get(key))
            elif _is_imageish_change(key, old_v, new_v):
                _emit(out, child_path, text='استُبدلت', kind='info')
            else:
                old_t = _ref_text(old_v, id_map, deleted=True)
                new_t = _ref_text(new_v, id_map)
                if not old_t and not new_t:
                    _emit(out, child_path, text='تغيّرت قيمة', kind='info')
                    continue
                if max(len(str(old_v or '')), len(str(new_v or ''))) > 160:
                    for text_line in _text_difference_lines(str(old_v or ''), str(new_v or '')):
                        _emit(out, child_path, text=text_line, kind='info')
                else:
                    _emit(out, path, field=label or 'القيمة', old=old_t, new=new_t,
                          kind='change')
        return
    if isinstance(old, list) and isinstance(new, list):
        if state is not None:
            state['saw'] = True
        _diff_list(old, new, path, out, depth, state=state, verbs=verbs)
        return
    had, has = not _is_empty_value(old), not _is_empty_value(new)
    if has and not had:
        text = 'أُضيفت البيانات'
    elif had and not has:
        text = 'أُزيلت البيانات'
    else:
        text = 'تغيّرت البيانات'
    if state is not None:
        state['saw'] = True
    _emit(out, path, text=text, kind='info')


def _diff_list(old_items, new_items, path, out, depth, state=None, verbs=None):
    if len(out) >= MAX_LINES:
        return
    if (old_items or new_items) and all(isinstance(item, dict)
                                        for item in list(old_items) + list(new_items)):
        pairs, removed, added = _match_rows(old_items, new_items)
        for old_index, new_index in pairs:
            _diff_blob(old_items[old_index], new_items[new_index],
                       path + [_row_label(new_items[new_index], new_index)],
                       out, depth + 1, state=state)
        for index in removed:
            _emit(out, path, text='حُذف ' + _row_label(old_items[index], index),
                  kind='removed')
        for index in added:
            _emit(out, path, text='أُضيف ' + _row_label(new_items[index], index),
                  kind='added')
        if pairs and not removed and not added:
            order = [old_index for old_index, _ in pairs]
            if order != sorted(order):
                _emit(out, path, text='أُعيد ترتيب الصفوف', kind='info')
        return
    from collections import Counter
    id_map = state.get('id_map') if state else {}
    old_counter = Counter(text for text in
                          (_ref_text(item, id_map, deleted=True) for item in old_items) if text)
    new_counter = Counter(text for text in
                          (_ref_text(item, id_map) for item in new_items) if text)
    removed = list((old_counter - new_counter).elements())
    added = list((new_counter - old_counter).elements())
    removed_verb, added_verb = verbs or ('حُذف', 'أُضيف')
    if removed:
        _emit(out, path, text=removed_verb + ': ' + '، '.join(removed[:6])
              + (f' و{len(removed) - 6} أخرى' if len(removed) > 6 else ''),
              kind='removed')
    if added:
        _emit(out, path, text=added_verb + ': ' + '، '.join(added[:6])
              + (f' و{len(added) - 6} أخرى' if len(added) > 6 else ''),
              kind='added')
    if not removed and not added and old_items != new_items:
        _emit(out, path, text='تغيّرت القائمة', kind='info')


def detail_text(item):
    """One readable line out of a stored detail item, dict or plain string."""
    if not isinstance(item, dict):
        return str(item)
    head = ' › '.join(part for part in (item.get('group'), item.get('path')) if part)
    if item.get('field'):
        old, new = str(item.get('old') or ''), str(item.get('new') or '')
        if old and new:
            phrase = f'من «{old}» إلى «{new}»'
        elif new:
            phrase = f'أُضيف «{new}»'
        else:
            phrase = f'أُفرغ (كان «{old}»)'
        return f'{head}: {item["field"]}: {phrase}' if head else f'{item["field"]}: {phrase}'
    text = str(item.get('text') or '')
    return f'{head}: {text}' if head else text


def _draft_field_labels():
    labels = {}
    for field in getattr(db, 'PREBUILT_FIELDS', []) or []:
        key = field.get('key')
        if key:
            labels[key] = field.get('label') or key
    return labels


def _draft_field_groups():
    """Section label per known draft field, so scalar edits group under their form section."""
    section_labels = {section['key']: section['label']
                      for section in (getattr(db, 'FIELD_SECTIONS', []) or [])}
    groups = {}
    for field in getattr(db, 'PREBUILT_FIELDS', []) or []:
        key = field.get('key')
        if key:
            groups[key] = section_labels.get(field.get('section_key'), '')
    return groups


def _readable_value(value):
    if value is None or value == '':
        return ''
    if isinstance(value, bool):
        return 'نعم' if value else 'لا'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return ''
    text = str(value).strip()
    if text.startswith('data:'):
        return ''
    return _shorten(text)


def _is_blob(value):
    if isinstance(value, (dict, list)):
        return True
    text = str(value or '').strip()
    return text.startswith('{') or text.startswith('[')


def describe_draft_changes(old_data, new_data, field_labels=None, id_names=None):
    """Readable detail items for what changed between two saves of a project file.

    Each item is either a plain string (legacy wording, slide lines) or a dict
    {group, path, field, old, new, kind} — the log page groups dicts under their
    section and renders a before/after, while detail_text() flattens any item
    back into one sentence for plain-text consumers.
    """
    old_data = old_data if isinstance(old_data, dict) else {}
    new_data = new_data if isinstance(new_data, dict) else {}
    labels = dict(field_labels or _draft_field_labels())
    labels.update(DRAFT_SCALAR_LABELS)
    labels.update(DRAFT_BLOB_LABELS)
    groups = _draft_field_groups()
    state = {'id_map': _collect_id_names(old_data, new_data)}
    # Rows that live outside draft_data (the company team library): the caller
    # hands their id-to-name map so references inside the draft still resolve.
    if id_names:
        state['id_map'].update({str(k): str(v) for k, v in id_names.items() if v})
    lines = []

    for key in sorted(set(old_data) | set(new_data)):
        if (key in DRAFT_IGNORED_KEYS or str(key).startswith('_')
                or str(key).endswith(DRAFT_IGNORED_SUFFIXES)):
            continue
        old_value, new_value = old_data.get(key), new_data.get(key)
        if _values_equal(old_value, new_value):
            continue
        label = labels.get(key, key)
        old_blob, new_blob = _parse_jsonish(old_value), _parse_jsonish(new_value)
        if key in DRAFT_BLOB_QUIET:
            _emit(lines, [label], text=DRAFT_BLOB_QUIET[key], kind='info')
            continue
        if key in DRAFT_BLOB_LABELS or isinstance(old_blob, (dict, list)) or isinstance(new_blob, (dict, list)):
            if key == 'tenantSlidesData':
                slide_lines = describe_slide_changes(
                    old_blob if isinstance(old_blob, list) else [],
                    new_blob if isinstance(new_blob, list) else [])
                for slide_line in slide_lines:
                    _emit(lines, [label], text=slide_line, kind='info')
                continue
            _diff_blob(old_blob, new_blob, [label], lines,
                       extra_skip=DRAFT_BLOB_INNER_SKIP.get(key, ()), state=state,
                       list_verbs=DRAFT_BLOB_LIST_VERBS.get(key))
            continue
        old_text = _ref_text(old_value, state['id_map'], deleted=True, fallback=_readable_value)
        new_text = _ref_text(new_value, state['id_map'], fallback=_readable_value)
        if not old_text and not new_text:
            continue
        _emit(lines, [groups.get(key) or 'بيانات المشروع'],
              field=label, old=old_text, new=new_text, kind='change')

    if len(lines) > MAX_LINES:
        remaining = len(lines) - MAX_LINES
        lines = lines[:MAX_LINES] + [f'و{remaining} تغييرًا آخر']
    return lines


def describe_section_status_changes(old_statuses, new_statuses, section_labels=None):
    """Readable lines for approvals of the project sections."""
    old_statuses = old_statuses if isinstance(old_statuses, dict) else {}
    new_statuses = new_statuses if isinstance(new_statuses, dict) else {}
    labels = dict(section_labels or {item['key']: item['label']
                                     for item in (getattr(db, 'FIELD_SECTIONS', []) or [])})
    words = {'approved': 'معتمد', 'draft': 'مسودة', 'pending': 'قيد المراجعة'}
    lines = []
    for key in sorted(set(old_statuses) | set(new_statuses)):
        before, after = old_statuses.get(key), new_statuses.get(key)
        if before == after:
            continue
        label = labels.get(key, key)
        lines.append(f'{label}: من «{words.get(before, before or "غير محدد")}» '
                     f'إلى «{words.get(after, after or "غير محدد")}»')
    return lines


def parse_slides(raw):
    """Slides as a list, whether they arrive as JSON text or already decoded."""
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return decoded if isinstance(decoded, list) else []
