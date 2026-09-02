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

COMPETITOR_MIN_DIRECT = 5

SUMMARY_SECTIONS = [
    {'key': 'market_definition', 'label': 'تعريف السوق'},
    {'key': 'city_position', 'label': 'وضع المدينة'},
    {'key': 'sector_performance', 'label': 'أداء القطاع'},
    {'key': 'supply', 'label': 'العرض'},
    {'key': 'demand', 'label': 'الطلب'},
    {'key': 'competition', 'label': 'المنافسة'},
    {'key': 'market_gap', 'label': 'الفجوة السوقية'},
    {'key': 'recommendation', 'label': 'التوصية'},
    {'key': 'risks', 'label': 'المخاطر'},
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
SUMMARY_TITLE = 'الملخص التنفيذي لسوق المشروع'
SUMMARY_WORD_TARGET = 500

SOURCE_PRIORITY = {
    1: [
        'الهيئة العامة للعقار',
        'منصة المؤشرات العقارية',
        'السجل العقاري وبيانات وزارة العدل المتاحة',
        'شبكة إيجار',
        'الهيئة العامة للإحصاء',
        'منصة البيانات المفتوحة السعودية',
        'وزارة البلديات والإسكان',
        'منصة بلدي',
        'الأمانة التابعة للمدينة',
        'كود البناء السعودي',
        'البنك المركزي السعودي',
        'برنامج وافي',
        'منصة سكني',
        'الشركة الوطنية للإسكان NHC',
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
        'CBRE', 'JLL', 'Knight Frank', 'Colliers', 'Savills',
        'ValuStrat', 'Deloitte', 'PwC', 'KPMG', 'EY', 'STR', 'CoStar',
    ],
    4: [
        'منصة عقار', 'بيوت السعودية', 'وصلت', 'تطبيق ديل',
        'منصات المسوقين العقاريين المرخصين',
    ],
    5: [
        'Google Maps', 'Google Places', 'المواقع الإخبارية الموثوقة',
        'وكالة الأنباء السعودية', 'البيانات الصحفية الرسمية',
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
        'منصة المؤشرات العقارية وبيانات الصفقات الفعلية',
        'الهيئة العامة للإحصاء',
        'البنك المركزي السعودي',
        'وافي',
        'سكني وNHC',
        'الأمانة وبلدي',
        'المواقع الرسمية للمطورين',
        'تقارير CBRE وJLL وKnight Frank وColliers',
        'منصات الإعلانات العقارية',
        'Google Maps للموقع والخدمات فقط',
    ],
    'تجاري': [
        'منصة المؤشرات العقارية وشبكة إيجار',
        'الهيئة العامة للإحصاء',
        'وزارة التجارة',
        'الأمانة وبلدي',
        'البنك المركزي السعودي',
        'المواقع الرسمية للمراكز والمشروعات التجارية',
        'تداول وتقارير الصناديق العقارية',
        'CBRE وJLL وKnight Frank وColliers وSavills',
        'منصات التأجير والإعلانات',
        'Google Maps وGoogle Places للخدمات والتقييمات',
    ],
    'فندقي': [
        'وزارة السياحة',
        'الهيئة العامة للإحصاء وإحصاءات المنشآت السياحية',
        'الهيئة العامة للطيران المدني',
        'الجهات الرسمية للفعاليات والسياحة في المدينة',
        'المواقع الرسمية للفنادق والمشغلين',
        'STR أو CoStar',
        'CBRE وJLL وKnight Frank وColliers',
        'مواقع الحجز لمقارنة السعر في تاريخ محدد فقط',
        'Google Maps للتقييمات والموقع والخدمات',
    ],
    'صناعي ولوجستي': [
        'وزارة الصناعة والثروة المعدنية',
        'الهيئة السعودية للمدن الصناعية ومناطق التقنية مدن',
        'خرائط مدن GIS',
        'هيئة المدن والمناطق الاقتصادية الخاصة',
        'الهيئة العامة للإحصاء',
        'الهيئة العامة للموانئ',
        'الهيئة العامة للطيران المدني للشحن الجوي',
        'وزارة النقل والخدمات اللوجستية',
        'الأمانة وبلدي',
        'المواقع الرسمية للمدن الصناعية والمشروعات',
        'تقارير CBRE وJLL وKnight Frank وColliers',
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

SUMMARY_SECTION_HINTS = {
    'market_definition': 'المدينة، نوع المشروع، نطاق الدراسة، فترة البيانات.',
    'city_position': 'عدد السكان والنمو والكثافة إذا كانت مؤثرة، الأهمية الاقتصادية للمدينة، أهم محركات الطلب المرتبطة بالمشروع.',
    'sector_performance': 'أهم مؤشرات أداء النشاط العقاري المحدد، اتجاه الأسعار أو الإيجارات أو الإشغال، حجم الصفقات أو الطلب، المقارنة بالفترة السابقة.',
    'supply': 'حجم المعروض القائم، المعروض تحت الإنشاء، المشروعات المستقبلية، وجود فائض أو نقص.',
    'demand': 'مستوى الطلب، العملاء المستهدفون، المنتج والمساحات الأكثر طلبًا، معدل الامتصاص أو الإشغال عند توفره.',
    'competition': 'عدد المنافسين، عدد المنافسين المباشرين، نطاق الأسعار، أهم نقاط القوة والضعف لديهم.',
    'market_gap': 'المنتج غير المتوفر بشكل كاف، المساحات أو الخدمات الناقصة، الفرصة التي يستطيع المشروع استهدافها.',
    'recommendation': 'الاستخدام الأنسب، المكونات المقترحة، المساحات أو مزيج الوحدات، السعر أو الإيجار أو ADR المقترح، السيناريو الأساسي للدراسة المالية.',
    'risks': 'أهم 3 مخاطر سوقية، شروط نجاح المشروع.',
    'decision': 'صنّف الفرصة إلى: فرصة قوية، فرصة واعدة بشروط، فرصة متوسطة، فرصة مرتفعة المخاطر، أو البيانات غير كافية.',
}

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
        'row_source': source,
    }


def empty_summary():
    return {item['key']: '' for item in SUMMARY_SECTIONS}


def empty_swot():
    return {item['key']: '' for item in SWOT_SECTIONS}


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


def resolve_source_url_from_citations(url, citations):
    """Replace a homepage with the retrieved page the search actually returned.

    The model tends to quote a site's front page from memory even when the figure
    came from a deep page, and the client needs the exact page.
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
    return value


def prefer_specific_source_url(*candidates):
    values = [_norm(item) for item in candidates if _norm(item)]
    for value in values:
        if value.startswith(('http://', 'https://')) and not is_generic_source_homepage(value):
            return value
    return next((value for value in values if value.startswith(('http://', 'https://'))), values[0] if values else '')


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


def build_consultant_system_prompt():
    source_blocks = []
    labels = {
        1: 'المستوى الأول: المصادر الحكومية الرسمية — استخدمها أولًا للأرقام والمؤشرات والصفقات والاشتراطات',
        2: 'المستوى الثاني: المصادر الرسمية للمشروعات',
        3: 'المستوى الثالث: التقارير المهنية',
        4: 'المستوى الرابع: منصات الإعلانات — أسعارها أسعار طلب وليست صفقات منفذة',
        5: 'المستوى الخامس: المصادر المساندة — لا تستخدمها وحدها لتحديد سعر المشروع',
    }
    for level, title in labels.items():
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
        type_blocks.append(
            f'مصادر هذا النشاط حسب الأولوية:\n{_format_list(TYPE_SOURCE_PRIORITY[sources_key])}'
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

    summary_spec = []
    for item in SUMMARY_SECTIONS:
        summary_spec.append(f'- {item["label"]}: {SUMMARY_SECTION_HINTS[item["key"]]}')

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
        + '\n\nثالثًا التحليل حسب نوع المشروع:\n'
        + '\n\n'.join(type_blocks)
        + '\n\n' + mixed
        + '\n\nرابعًا ملخص السوق — أهم مخرج:\n'
        f'ابدأ مخرجات الدراسة بعنوان: {SUMMARY_TITLE}.\n'
        'يجب أن يكون الملخص مخصصًا لنوع المشروع وليس وصفًا عامًا للمدينة.\n'
        'يجب أن يحتوي على:\n'
        + '\n'.join(summary_spec)
        + f'\nاكتب الملخص في حدود {SUMMARY_WORD_TARGET} كلمة.\n\n'
        'بعد الملخص أعد تحليل SWOT مستقلًا للمشروع في السوق المحدد، من أربع خانات:\n'
        + '\n'.join(f'- {item["label"]}: {SWOT_SECTION_HINTS[item["key"]]}' for item in SWOT_SECTIONS)
        + '\nلا تخلط SWOT مع أقسام الملخص العشرة. كل خانة نقاط قصيرة خاصة بهذا المشروع وهذا النوع.\n'
        'لا تستخدم وصفًا عامًا للمدينة بدل تحليل المشروع.\n\n'
        'خامسًا قواعد إلزامية:\n'
        + _format_list(MANDATORY_RULES)
        + '\nالدراسة أولية استرشادية وليست تقييمًا عقاريًا معتمدًا.'
    )


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
        f"- نطاق المنافسين: {payload.get('competitorRadiusLabel') or payload.get('competitor_radius') or 'تلقائي'}",
        f"- فترة البيانات المطلوبة: {payload.get('dataPeriodLabel') or payload.get('data_period') or 'غير مدخل'}",
    ]
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
            'إن لم يكفِ العدد داخل النطاق، وسّع البحث تدريجيًا واذكر ذلك في notes. '
            'صنف كل منافس: مباشر أو غير مباشر أو مرجعي.'
        )
    price_types = '\n'.join(
        f'- {operation}: ' + '، '.join(options)
        for operation, options in PRICE_TYPE_BY_OPERATION.items()
    )
    search_protocol = (
        'بروتوكول البحث الإلزامي:\n'
        '1. ابحث أولًا عن قائمة المنافسين في المدينة والنطاق المطلوب.\n'
        '2. ثم نفّذ بحثًا منفصلًا لكل منافس على حدة عن سعره الفعلي '
        '(سعر البيع أو المتر أو الإيجار أو سعر الليلة أو ADR حسب نوع التشغيل) '
        'باستخدام اسم المنافس مع المدينة، وابدأ من مصادر المستوى الأول لهذا النشاط.\n'
        '3. area_sqm هي مساحة الوحدة القابلة للبيع أو الإيجار أو الوحدة النموذجية، مثل مساحة الشقة أو الفيلا أو المكتب أو المحل أو الغرفة أو الجناح أو المستودع. '
        'لا تستخدم مساحة الأرض أو مساحة البناء الكلية أو Tower GFA أو Gross Floor Area أو مساحة البرج أو المشروع. '
        'إذا وجدت فقط المساحة الإجمالية اترك area_sqm فارغة واكتب السبب في notes.\n'
        '4. لا تكتب سعرًا من معرفتك السابقة. السعر يُقبل فقط إذا ورد في صفحة قرأتها في هذا البحث، '
        'ويجب أن يكون رابط تلك الصفحة نفسها في source_url، مع إدراج كل الصفحات المستخدمة للمنافس في source_urls.\n'
        f'5. إذا لم تجد سعرًا بعد البحث اترك حقول السعر فارغة واكتب في source عبارة {MISSING_VALUE_PHRASE} '
        'مع بيان ما بحثت عنه في notes. الصف الناقص السعر مقبول؛ الرقم المختلق مرفوض.\n'
        '6. املأ price_type من القائمة المسموحة لنوع التشغيل، واستخدم price_from و price_to لأنواع النطاق '
        f'({"، ".join(sorted(RANGE_PRICE_TYPES))}) و price_value لغيرها.\n'
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
        '      "logo_url": "رابط صورة الشعار من الموقع الرسمي فقط أو فارغ",\n'
        '      "logo_source_url": "صفحة الموقع الرسمي التي تثبت الشعار أو فارغ",\n'
        '      "field_sources": {"name": [], "project_type": [], "area_sqm": [], "area_from": [], "area_to": [], "status": [], "classification": [], "operation_type": [], "price_type": [], "price_value": [], "price_from": [], "price_to": [], "logo_url": []},\n'
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


def build_summary_user_prompt(payload, competitors, current_summary=None, current_sources=None, current_swot=None):
    today = date.today().isoformat()
    section_keys = ', '.join(item['key'] for item in SUMMARY_SECTIONS)
    swot_keys = ', '.join(item['key'] for item in SWOT_SECTIONS)
    return (
        f'تاريخ اليوم / تاريخ الوصول للمصادر: {today}\n'
        f'ابدأ المخرجات بعنوان: {SUMMARY_TITLE}.\n'
        'اكتب الملخص التنفيذي لسوق المشروع حسب القواعد أعلاه.\n'
        'الملخص مخصص لنوع هذا المشروع وليس وصفًا عامًا للمدينة.\n'
        'أعد الأقسام العشرة بالترتيب: تعريف السوق، وضع المدينة، أداء القطاع، العرض، الطلب، المنافسة، الفجوة السوقية، التوصية، المخاطر، القرار.\n'
        'غطِّ في كل قسم جميع العناصر المطلوبة في brief النظام، ولا تستبدل أي قسم بوصف عام للمدينة.\n'
        f'اجعل مجموع أقسام الملخص في حدود {SUMMARY_WORD_TARGET} كلمة.\n'
        'كل رقم يجب أن يظهر أيضًا في جدول المصادر.\n'
        f'إذا لم تتوفر معلومة فاكتب داخل القسم: {MISSING_VALUE_PHRASE}.\n'
        'في قسم القرار اختر قيمة واحدة فقط من: '
        + '، '.join(DECISION_OPTIONS)
        + ' ثم اشرحها في نص القرار.\n'
        'بعد الملخص اكتب تحليل SWOT مستقلًا من أربع خانات: نقاط القوة، نقاط الضعف، الفرص، التهديدات.\n'
        'اجعل كل خانة نقاطًا قصيرة خاصة بهذا المشروع وهذا النوع، ولا تكرر الملخص حرفيًا.\n'
        'بعد ذلك اكتب one_block_summary كنص عربي متماسك يلخص دراسة السوق كاملة داخل حقل واحد، '
        'ويجمع المنافسين والبيانات السعرية وأقسام الملخص العشرة وSWOT والقرار. استخدم الحقائق والأرقام والمصادر الموجودة فقط، '
        'ولا تضف أي معلومة غير موجودة. حافظ داخل الحقل الواحد على عناوين واضحة وفقرات وأسطر فارغة وتنسيق مناسب للقراءة، '
        'ولا تضغط النص في سطر واحد ولا تكتب رموز فصل الأسطر حرفيًا.\n\n'
        'بيانات المشروع:\n'
        f'{_project_input_block(payload)}\n\n'
        'المنافسون المعتمدون في الجدول:\n'
        f'{json.dumps(competitors or [], ensure_ascii=False, indent=2)}\n\n'
        'ملخص حالي إن وُجد (للسياق فقط، أعد كتابة ملخص جديد كامل):\n'
        f'{json.dumps(current_summary or {}, ensure_ascii=False)}\n\n'
        'مصادر حالية إن وُجدت (للسياق فقط، أعد بناء جدول المصادر كاملًا مع كل رقم):\n'
        f'{json.dumps(current_sources or [], ensure_ascii=False)}\n\n'
        'تحليل SWOT حالي إن وُجد (للسياق فقط، أعد كتابته كاملًا):\n'
        f'{json.dumps(current_swot or {}, ensure_ascii=False)}\n\n'
        'أرجع JSON فقط بهذا الشكل:\n'
        '{\n'
        f'  "title": "{SUMMARY_TITLE}",\n'
        f'  "summary": {{ مفاتيح إلزامية: {section_keys} }},\n'
        f'  "swot": {{ مفاتيح إلزامية: {swot_keys} }},\n'
        '  "decision": "قيمة من قائمة القرار",\n'
        '  "sources": [\n'
        '    {"name": "", "url": "", "data_date": "", "accessed_at": "' + today + '", "reliability": "", "note": ""}\n'
        '  ],\n'
        '  "disclaimer": "هذه دراسة أولية استرشادية وليست تقييمًا عقاريًا معتمدًا",\n'
        '  "one_block_summary": "نص عربي متماسك يلخص الدراسة كاملة"\n'
        '}\n'
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
        'notes': _norm(row.get('notes') or row.get('note')),
        'row_source': _norm(row.get('row_source') or row.get('rowSource')) or fallback_source,
    }
    return result


def _resolve_source_urls(urls, citations):
    resolved = []
    for url in urls:
        value = resolve_source_url_from_citations(url, citations)
        if value:
            resolved.append(value)
    return _unique_values(resolved)


def apply_search_citations(rows, citations, url_key='source_url'):
    """Upgrade AI-written homepage links to the exact pages returned by the search."""
    if not citations:
        return rows
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if (row.get('row_source') or 'ai') != 'ai' and url_key == 'source_url':
            continue
        if url_key == 'source_url':
            field_sources = competitor_field_sources(row)
            resolved_field_sources = {
                field: resolved
                for field, urls in field_sources.items()
                if (resolved := _resolve_source_urls(urls, citations))
            }
            urls = competitor_source_urls(row)
            resolved_urls = _resolve_source_urls(urls, citations)
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
        for url in competitor_source_urls(competitor):
            source_fields = [
                _COMPETITOR_SOURCE_FIELD_LABELS.get(field, field)
                for field, urls in field_sources.items()
                if any(str(item).casefold() == url.casefold() for item in urls)
            ]
            field_note = 'الحقول: ' + '، '.join(source_fields) if source_fields else ''
            source_note = ' — '.join(item for item in (note, field_note) if item)
            rows.append({
                'id': str(uuid.uuid4()),
                'competitor_id': competitor_id,
                'competitor_name': name,
                'source_kind': 'competitor',
                'source_fields': source_fields,
                'name': source_name,
                'url': url,
                'data_date': '',
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
    nested = data.get('summary') if isinstance(data.get('summary'), dict) else data
    summary = {}
    for item in SUMMARY_SECTIONS:
        summary[item['key']] = _norm(nested.get(item['key'])) or MISSING_VALUE_PHRASE
    decision = _norm(data.get('decision') or nested.get('decision'))
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
            value = _norm(raw_swot.get(key) or nested.get(key) or data.get(key))
            if value:
                break
        swot[item['key']] = value
    raw_one_block = (
        data.get('one_block_summary')
        or data.get('oneBlockSummary')
        or data.get('market_summary_block')
        or data.get('executive_summary')
        or nested.get('one_block_summary')
    )
    one_block_summary = str(raw_one_block or '').strip()
    one_block_summary = one_block_summary.replace('\\r\\n', '\n').replace('\\n', '\n')
    one_block_summary = re.sub(r'[ \t]+', ' ', one_block_summary)
    one_block_summary = re.sub(r'\n{3,}', '\n\n', one_block_summary)
    return {
        'title': SUMMARY_TITLE,
        'summary': summary,
        'swot': swot,
        'decision': decision,
        'sources': sources,
        'disclaimer': disclaimer,
        'one_block_summary': one_block_summary,
    }


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
