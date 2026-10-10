"""Market-study specification and helpers.

The full brief lives in ``تحليل السوق .pdf``. This module keeps that brief as
code so the UI, the AI prompts, and the tests stay aligned. Do not drop a
required indicator, source-priority rule, or input option from the PDF.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlsplit, urlunsplit
import json
import math
import os
import re
import uuid


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

PROJECT_TYPE_MAIN = [
    'سكني',
    'تجاري',
    'فندقي',
    'صناعي ولوجستي',
    'متعدد الاستخدامات',
]

PROJECT_TYPE_SUBTYPES = {
    'سكني': [],
    'تجاري': ['مكاتب', 'تجزئة ومحلات', 'مطاعم ومقاهي', 'مركز تجاري'],
    'فندقي': ['فندق', 'شقق مخدومة', 'منتجع', 'مساكن فندقية'],
    'صناعي ولوجستي': ['مصنع', 'مستودعات', 'مركز لوجستي', 'مجمع صناعي'],
    'متعدد الاستخدامات': [
        'سكني', 'مكاتب', 'تجزئة ومحلات', 'مطاعم ومقاهي', 'مركز تجاري',
        'فندق', 'شقق مخدومة', 'منتجع', 'مساكن فندقية', 'مصنع', 'مستودعات',
        'مركز لوجستي', 'مجمع صناعي',
    ],
}

MIXED_USE_COMPONENT_OPTIONS = PROJECT_TYPE_SUBTYPES['متعدد الاستخدامات'][:]

PROJECT_LEVELS = [
    {'value': 'economy', 'label': 'اقتصادي', 'description': 'أقل تكلفة وسعر، خدمات أساسية'},
    {'value': 'mid_market', 'label': 'متوسط', 'description': 'منتج عملي للفئة المتوسطة'},
    {'value': 'upper_mid_market', 'label': 'فوق المتوسط', 'description': 'جودة وخدمات أعلى من المتوسط'},
    {'value': 'premium', 'label': 'متميز', 'description': 'منتج عالي الجودة دون الوصول للفخامة'},
    {'value': 'luxury', 'label': 'فاخر', 'description': 'موقع وتشطيبات وخدمات فاخرة'},
    {'value': 'ultra_luxury', 'label': 'فائق الفخامة', 'description': 'منتج حصري وعلامات عالمية'},
    {'value': 'not_defined', 'label': 'أخرى', 'description': 'يستكمل لاحقًا'},
]

ACTIVITY_CLASS_BY_TYPE = {
    'فندقي': [
        'غير مصنف', 'نجمة واحدة', 'نجمتان', '3 نجوم', '4 نجوم', '5 نجوم',
        '5 نجوم فاخر', 'منتجع', 'فندق بوتيك', 'شقق مخدومة اقتصادية',
        'شقق مخدومة متوسطة', 'شقق مخدومة فاخرة', 'أخرى',
    ],
    'مكاتب': [
        'فئة C', 'فئة B', 'فئة B+', 'فئة A', 'فئة A+ أو مكاتب مميزة',
        'مكاتب مرنة ومشتركة', 'أخرى',
    ],
    'صناعي ولوجستي': [
        'أساسي', 'قياسي', 'متقدم', 'عالي المواصفات', 'متخصص حسب النشاط',
        'منشأة مؤتمتة أو ذكية', 'أخرى',
    ],
}

GENERAL_TARGET_AUDIENCE = [
    'أفراد', 'عائلات', 'مستثمرون', 'شركات', 'جهات حكومية',
    'سياح وزوار', 'مشغلون ومستأجرون',
]

TARGET_AUDIENCE_BY_KIND = {
    'سكني': [
        'أفراد', 'حديثو الزواج', 'العائلات الصغيرة', 'العائلات المتوسطة',
        'العائلات الكبيرة', 'كبار السن', 'الطلاب', 'الموظفون',
        'التنفيذيون ورجال الأعمال', 'أصحاب الدخل المحدود', 'أصحاب الدخل المتوسط',
        'أصحاب الدخل فوق المتوسط', 'أصحاب الدخل المرتفع', 'أصحاب الثروات',
        'السعوديون', 'المقيمون', 'الأجانب المؤهلون للتملك', 'زوار المدينة',
        'الباحثون عن منزل ثان', 'الباحثون عن مساكن فندقية',
        'موظفو الشركات القريبة',
    ],
    'مكاتب': [
        'رواد الأعمال', 'الشركات الناشئة', 'المنشآت الصغيرة', 'المنشآت المتوسطة',
        'الشركات الكبيرة', 'الشركات العالمية', 'المقرات الإقليمية',
        'الجهات الحكومية', 'الجهات شبه الحكومية', 'الشركات المهنية والاستشارية',
        'شركات التقنية', 'الشركات المالية', 'شركات العقار والإنشاءات',
        'الشركات الطبية', 'مكاتب المحاماة والمحاسبة', 'مشغلو المكاتب المشتركة',
        'المستقلون', 'المستثمرون العقاريون',
    ],
    'تجزئة': [
        'متاجر محلية', 'علامات تجارية عالمية', 'مطاعم ومقاهي', 'متاجر فاخرة',
        'سوبرماركت', 'صيدليات', 'خدمات يومية', 'مراكز ترفيه', 'عيادات',
        'نواد رياضية', 'بنوك وخدمات مالية', 'مشغلو التجزئة',
    ],
    'فندقي': [
        'سياح الترفيه', 'سياح الأعمال', 'رجال الأعمال والتنفيذيون', 'العائلات',
        'الأزواج', 'الزوار الدوليون', 'الزوار المحليون', 'الزوار الخليجيون',
        'الحجاج والمعتمرون', 'زوار الفعاليات والمواسم', 'زوار المؤتمرات والمعارض',
        'المجموعات السياحية', 'أصحاب الدخل المتوسط', 'أصحاب الدخل المرتفع',
        'فئة الفخامة', 'أصحاب الثروات', 'نزلاء الإقامة الطويلة',
        'نزلاء الإقامة القصيرة', 'مسافرو الترانزيت', 'أطقم شركات الطيران',
        'الرياضيون والفرق الرياضية', 'المرضى ومرافقوهم', 'موظفو الشركات',
        'الجهات الحكومية', 'منظمو المؤتمرات والفعاليات', 'مشترو المساكن الفندقية',
    ],
    'صناعي ولوجستي': [
        'المصانع الصغيرة والمتوسطة', 'الشركات الصناعية الكبرى',
        'المستثمرون الصناعيون', 'المصنعون المحليون', 'المصنعون الدوليون',
        'شركات الخدمات اللوجستية', 'مشغلو الطرف الثالث 3PL',
        'شركات التجارة الإلكترونية', 'شركات التوزيع', 'شركات الاستيراد والتصدير',
        'شركات الشحن', 'مشغلو الميل الأخير', 'شركات التخزين الجاف',
        'شركات التخزين المبرد', 'الصناعات الغذائية', 'الصناعات الدوائية',
        'الصناعات الطبية', 'الصناعات الخفيفة', 'الصناعات المتوسطة',
        'الصناعات الثقيلة', 'الصناعات التقنية والإلكترونية',
        'صناعة السيارات وقطع الغيار', 'مواد البناء', 'الشركات المرتبطة بالموانئ',
        'الشركات المرتبطة بالمطارات', 'الجهات الحكومية', 'المستأجرون الصناعيون',
        'مشترو المستودعات أو المصانع',
    ],
}

COMPETITOR_RADIUS_OPTIONS = [
    {'value': '3', 'label': '3 كم'},
    {'value': '5', 'label': '5 كم'},
    {'value': '10', 'label': '10 كم'},
    {'value': 'city', 'label': 'كامل المدينة'},
    {'value': 'custom', 'label': 'نطاق مخصص'},
]

DEFAULT_COMPETITOR_RADIUS_KM = 10

DATA_PERIOD_OPTIONS = [
    {'value': '12m', 'label': 'آخر 12 شهرًا'},
    {'value': '24m', 'label': 'آخر 24 شهرًا'},
    {'value': '3y', 'label': 'آخر 3 سنوات'},
    {'value': '5y', 'label': 'آخر 5 سنوات'},
    {'value': 'custom', 'label': 'فترة مخصصة'},
]

COMPETITOR_STATUS_OPTIONS = ['قائم', 'تحت الإنشاء', 'على الخارطة']
COMPETITOR_CLASS_OPTIONS = ['مباشر', 'غير مباشر', 'مرجعي']
COMPETITOR_OPERATION_OPTIONS = ['بيع', 'إيجار', 'تشغيل فندقي', 'أخرى']

PRICE_TYPE_BY_OPERATION = {
    'بيع': [
        'سعر الوحدة', 'سعر المتر المربع', 'متوسط سعر الوحدة', 'متوسط سعر المتر',
        'يبدأ من', 'نطاق سعري', 'أخرى',
    ],
    'إيجار': [
        'إيجار الوحدة الشهري', 'إيجار الوحدة السنوي', 'إيجار المتر الشهري',
        'إيجار المتر السنوي', 'متوسط إيجار الوحدة', 'متوسط إيجار المتر',
        'يبدأ من', 'نطاق سعري', 'أخرى',
    ],
    'تشغيل فندقي': [
        'سعر الليلة', 'متوسط سعر الغرفة ADR', 'الإيراد لكل غرفة RevPAR',
        'متوسط الإقامة الشهرية', 'يبدأ من', 'نطاق أسعار الغرف', 'أخرى',
    ],
    'أخرى': ['قيمة واحدة', 'نطاق سعري', 'أخرى'],
}

RANGE_PRICE_TYPES = {'نطاق سعري', 'نطاق أسعار الغرف'}

# English enum twins — an English-language project stores English values so the
# review table, executive content and generated slides all display them verbatim.
COMPETITOR_STATUS_OPTIONS_EN = ['Operating', 'Under Construction', 'Off-Plan']
COMPETITOR_CLASS_OPTIONS_EN = ['Direct', 'Indirect', 'Benchmark']
COMPETITOR_OPERATION_OPTIONS_EN = ['Sale', 'Rent', 'Hotel Operation', 'Other']
COMPETITOR_PROJECT_TYPE_OPTIONS_EN = [
    'Residential', 'Commercial', 'Hospitality',
    'Industrial & Logistics', 'Mixed-Use', 'Other',
]

PRICE_TYPE_BY_OPERATION_EN = {
    'Sale': [
        'Unit Price', 'Price per SQM', 'Average Unit Price', 'Average Price per SQM',
        'Starting From', 'Price Range', 'Other',
    ],
    'Rent': [
        'Monthly Unit Rent', 'Annual Unit Rent', 'Monthly Rent per SQM',
        'Annual Rent per SQM', 'Average Unit Rent', 'Average Rent per SQM',
        'Starting From', 'Price Range', 'Other',
    ],
    'Hotel Operation': [
        'Nightly Rate', 'Average Daily Rate (ADR)', 'RevPAR',
        'Average Monthly Stay', 'Starting From', 'Room Price Range', 'Other',
    ],
    'Other': ['Single Value', 'Price Range', 'Other'],
}

RANGE_PRICE_TYPES_EN = {'Price Range', 'Room Price Range'}

OPERATION_EN_BY_AR = dict(zip(COMPETITOR_OPERATION_OPTIONS, COMPETITOR_OPERATION_OPTIONS_EN))
OPERATION_AR_BY_EN = {en: ar for ar, en in OPERATION_EN_BY_AR.items()}
STATUS_EN_BY_AR = dict(zip(COMPETITOR_STATUS_OPTIONS, COMPETITOR_STATUS_OPTIONS_EN))
CLASS_EN_BY_AR = dict(zip(COMPETITOR_CLASS_OPTIONS, COMPETITOR_CLASS_OPTIONS_EN))

_PRICE_TYPE_PAIRS = tuple(
    (ar, en)
    for ar_op, en_op in OPERATION_EN_BY_AR.items()
    for ar, en in zip(PRICE_TYPE_BY_OPERATION[ar_op], PRICE_TYPE_BY_OPERATION_EN[en_op])
)
PRICE_TYPE_EN_BY_AR = dict(_PRICE_TYPE_PAIRS)
PRICE_TYPE_AR_BY_EN = {en: ar for ar, en in _PRICE_TYPE_PAIRS}

MISSING_VALUE_PHRASE_EN = 'not available from a reliable source'

COMPETITOR_MIN_DIRECT = 5

# Benchmark axes — every revenue-bearing project component is an axis the
# competitor table must cover with COMPETITOR_MIN_DIRECT direct competitors of
# its own, each tagged in the row's benchmarks field. 'search' seeds the
# targeted expansion query for a deficient axis.
COMPONENT_USE_AXES = {
    'residential': {'label': 'سكني', 'label_en': 'Residential',
                    'search': 'مشاريع ومجمعات سكنية مسمّاة (أبراج سكنية، كمبوندات، مخططات)'},
    'office': {'label': 'مكاتب', 'label_en': 'Offices',
               'search': 'أبراج ومجمعات مكاتب إدارية مسمّاة'},
    'retail': {'label': 'تجزئة ومحلات', 'label_en': 'Retail',
               'search': 'مراكز تجارية ومشاريع تجزئة ومحلات مسمّاة'},
    'hospitality': {'label': 'فندقي', 'label_en': 'Hospitality',
                    'search': 'فنادق وشقق مخدومة ومنتجعات مسمّاة'},
    'industrial': {'label': 'صناعي', 'label_en': 'Industrial',
                   'search': 'مشاريع ومجمعات صناعية مسمّاة'},
    'logistics': {'label': 'لوجستي', 'label_en': 'Logistics',
                  'search': 'مستودعات ومراكز لوجستية مسمّاة'},
    'entertainment': {'label': 'ترفيهي', 'label_en': 'Entertainment',
                      'search': 'وجهات ومشاريع ترفيهية مسمّاة'},
    'commercial': {'label': 'تجاري', 'label_en': 'Commercial',
                   'search': 'مشاريع تجارية مسمّاة (مكاتب، مراكز تجارية، تجزئة)'},
    'other': {'label': 'أخرى', 'label_en': 'Other',
              'search': 'مشاريع عقارية مسمّاة من النشاط نفسه'},
    'general': {'label': 'عام', 'label_en': 'General',
                'search': 'مشاريع عقارية مسمّاة من النوع نفسه'},
}

# Component uses that never need their own competitors (support facilities).
COMPONENT_NON_COMPETING_USES = ('parking', 'services', 'openarea', 'basement')

# Mixed-use subtype labels and project main types mapped onto axis keys — the
# fallback sources when the components table is empty.
MIXED_COMPONENT_AXIS_KEYS = {
    'سكني': 'residential',
    'مكاتب': 'office',
    'تجزئة ومحلات': 'retail', 'مطاعم ومقاهي': 'retail', 'مركز تجاري': 'retail',
    'فندق': 'hospitality', 'شقق مخدومة': 'hospitality', 'منتجع': 'hospitality',
    'مساكن فندقية': 'hospitality',
    'مصنع': 'industrial', 'مجمع صناعي': 'industrial',
    'مستودعات': 'logistics', 'مركز لوجستي': 'logistics',
}
PROJECT_MAIN_AXIS_KEYS = {
    'سكني': 'residential', 'تجاري': 'commercial', 'فندقي': 'hospitality',
    'صناعي ولوجستي': 'industrial',
}

# Values the model may write in a row's benchmarks field (matched after
# _fold_choice, so Arabic and English both land).
BENCHMARK_AXIS_ALIASES = {
    'residential': {'سكني', 'سكنية', 'إسكان', 'وحدات سكنية', 'شقق سكنية',
                    'residential', 'housing', 'residential units'},
    'office': {'مكاتب', 'مكتب', 'إداري', 'مكاتب إدارية',
               'office', 'offices', 'office space'},
    'retail': {'تجزئة', 'تجزئة ومحلات', 'محلات', 'تجاري', 'مركز تجاري', 'مول',
               'مطاعم', 'مطاعم ومقاهي', 'مقاهي',
               'retail', 'mall', 'shops', 'restaurants', 'f&b'},
    'commercial': {'تجاري', 'مكاتب', 'تجزئة', 'محلات', 'مركز تجاري', 'مطاعم',
                   'commercial', 'office', 'retail'},
    'hospitality': {'فندقي', 'فندق', 'فنادق', 'شقق مخدومة', 'منتجع', 'مساكن فندقية',
                    'hospitality', 'hotel', 'hotels', 'serviced apartments', 'resort'},
    'industrial': {'صناعي', 'مصنع', 'مصانع', 'مجمع صناعي', 'صناعي ولوجستي',
                   'industrial', 'factory', 'factories'},
    'logistics': {'لوجستي', 'مستودعات', 'مخازن', 'مركز لوجستي', 'لوجستية',
                  'logistics', 'warehouse', 'warehouses'},
    'entertainment': {'ترفيهي', 'ترفيه', 'ترفيهية', 'entertainment'},
    'general': {'عام', 'general'},
}

# A competitor row that never got benchmarks tagged is attributed by its
# project_type instead; 'متعدد الاستخدامات' benchmarks every axis.
BENCHMARK_PROJECT_TYPE_FALLBACK = {
    'سكني': {'residential'},
    'residential': {'residential'},
    'تجاري': {'office', 'retail', 'commercial'},
    'commercial': {'office', 'retail', 'commercial'},
    'فندقي': {'hospitality'},
    'hospitality': {'hospitality'},
    'hotel': {'hospitality'},
    'صناعي ولوجستي': {'industrial', 'logistics'},
    'industrial & logistics': {'industrial', 'logistics'},
    'industrial and logistics': {'industrial', 'logistics'},
    'متعدد الاستخدامات': '*',
    'mixed-use': '*',
    'mixed use': '*',
}

SUMMARY_LABEL = 'تحليل السوق'
SUMMARY_SECTIONS = [
    {'key': 'market_definition', 'label': 'تعريف السوق'},
    {'key': 'city_position', 'label': 'وضع المدينة'},
    {'key': 'sector_performance', 'label': 'أداء القطاع'},
    {'key': 'supply', 'label': 'العرض'},
    {'key': 'demand', 'label': 'الطلب'},
    {'key': 'competition', 'label': 'المنافسة'},
    {'key': 'market_gap', 'label': 'الفجوة السوقية'},
    {'key': 'project_evaluation', 'label': 'تقييم المشروع'},
    {'key': 'recommendation', 'label': 'التوصية'},
    {'key': 'risks', 'label': 'المخاطر'},
]

# Older drafts included the decision inside summary. Keep the complete order
# available only for compatibility when converting those drafts.
LEGACY_SUMMARY_SECTIONS = [
    *SUMMARY_SECTIONS,
    {'key': 'decision', 'label': 'القرار'},
]

SWOT_SECTIONS = [
    {'key': 'strengths', 'label': 'نقاط القوة'},
    {'key': 'weaknesses', 'label': 'نقاط الضعف'},
    {'key': 'opportunities', 'label': 'الفرص'},
    {'key': 'threats', 'label': 'التهديدات'},
]

DECISION_OPTIONS = [
    'فرصة قوية',
    'فرصة واعدة بشروط',
    'فرصة متوسطة',
    'فرصة مرتفعة المخاطر',
    'البيانات غير كافية',
]

MISSING_VALUE_PHRASE = 'غير متوفر من مصدر موثوق'
CURRENCY_LABEL = 'ريال سعودي'

# The chosen data period becomes a hard publication-date window; the model is
# ordered to refuse figures sourced outside it, and flag_out_of_period_sources
# marks any source row whose date escapes the window.
_DATA_PERIOD_MONTHS = {'12m': 12, '24m': 24, '3y': 36, '5y': 60}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew too large to edit comfortably, so its body
# lives in ordered files under market_study_parts/, exec'd into this module's own
# namespace. Globals, monkeypatching (patch.object(market_study, 'name')) and
# tracebacks are unchanged: parts are compiled with their real path so frames
# point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'market_study_parts')
for _part_name in sorted(_n for _n in os.listdir(_PARTS_DIR) if _n.endswith('.py')):
    _part_path = os.path.join(_PARTS_DIR, _part_name)
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_name
except NameError:
    pass
del _PARTS_DIR
