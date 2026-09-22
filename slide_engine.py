"""
Slide Engine: Dynamic slide count & content distribution.
AI analyzes project data and proposes a balanced slide plan.
"""

import json
import math
import os
import re
import concurrent.futures
import html as html_lib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html.parser import HTMLParser
from design_templates import (
    build_design_rules, contrast_ratio, dark_surface_color, extract_slide_elements,
    normalize_hex_color, readable_text_color,
)
import db
# emoji_icons is intentionally not imported: it converted emojis into inline SVG icons, which the
# icon stripper then removed. The product rule is that no icon is ever generated.

_ICON_RE = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]')

# Renderer/plan-version stamp. Bump this whenever slide renderers, deterministic
# builders or plan normalization change: every normalized plan carries it, the
# client folds it into the generation-checkpoint fingerprint, and stored slides
# produced by older code can no longer be resumed into a new presentation.
SLIDE_ENGINE_VERSION = '2026-09-22.3'

# ─────────────────────────────────────────────────────────────────────────────
# Content Distribution Rules
# ─────────────────────────────────────────────────────────────────────────────

CONTENT_DISTRIBUTION_RULES = """
## قواعد توزيع المحتوى (إلزامية — اتبعها بدقة)
1. الغلاف أولاً، ثم فهرس الأقسام مع رقم صفحة بداية كل قسم، ثم أقسام المحتوى، والخاتمة أخيراً.
2. ترتيب الأقسام لا يتغير: نبذة عن المشروع، مكونات المشروع، تحليل الأرض، تحليل الموقع الجغرافي، تحليل السوق، الجدول الزمني، الدراسة المالية، تحليل SWOT وتحليل المخاطر، فريق العمل، المخططات، التصورات الخارجية، التصورات الداخلية، الملخص التنفيذي، الخاتمة.
3. الفهرس يعرض أسماء الأقسام فقط مع أرقام الصفحات؛ لا يعرض عناوين الشرائح الفرعية ولا يستخدم مخطط محاور أو تدفق أو بطاقات صغيرة.
4. صفحة بداية كل قسم تحمل اسم القسم وحده بلا وصف وبلا ترجمة وبلا نقاط.
5. كل شريحة لها فكرة واحدة، ويُضغط المحتوى المتكرر في جدول منظم أو عمودين قبل إضافة صفحة جديدة؛ لا يُصغّر النص لدرجة يصعب قراءتها ولا تُحذف البيانات.
6. لا تكرر المعلومة أو مكونات المشروع في أكثر من موضع. الإحالة المختصرة مسموحة، أما إعادة الجدول أو القائمة نفسها فممنوعة.
7. اختر الشكل بحسب طبيعة المحتوى: نص متصل للنبذات والملخصات، جدول للصفوف المنظمة، وصورة كبيرة للصور والمخططات. الرسوم البيانية محصورة حصراً في 4 أنواع معتمدة لـ 4 مواقع محددة (مقارنة المنافسين: horizontal_bar في دراسة السوق، وتكلفة الاستثمار: waterfall، والتدفقات النقدية: combo، ومقارنة السيناريوهات: heatmap في الدراسة المالية). أي رسم خارج هذه المواقع الأربعة والأنواع الأربعة ممنوع منعاً باتاً. استخدم البطاقات فقط لعناصر مستقلة قصيرة ومتوازية، وبحد أقصى ثلاث بطاقات عند الحاجة.
8. يوضع ملخص نهائي مستند إلى بيانات البرنامج بعد جداول كل قسم تحليلي، ولا تُضاف تحسينات إنشائية أو استرسال لا يحمل معلومة واضحة.
9. شرائح الصور تستخدم كل الرموز المحددة لها بتخطيط المجموعة المعتمد، من صورة واحدة إلى ثلاث صور؛ وكل صورة تظهر مرة واحدة فقط ولا تعاد في شريحة أخرى.
10. شرائح الموقع والخرائط تبقى داخل قسم تحليل الموقع الجغرافي، وشرائح الأرض وصورها وملخصها داخل قسم تحليل الأرض.
11. قسم تحليل السوق لا يحتوي على خرائط أو صور فوتوغرافية أو خلفيات صور. الاستثناء الوحيد هو شعار المنافس إذا كان محفوظاً ضمن بيانات ذلك المنافس، ويظهر داخل صفه في جدول المنافسين. يملك النموذج حرية اختيار التكوين البصري لبقية شرائح السوق باستخدام HTML وCSS والبيانات المعتمدة.
12. قسم تحليل السوق يحتوي على رسم بياني واحد فقط: horizontal_bar في شريحة مقارنة المنافسين. هذه الشريحة وحدها لها تخطيط ثابت: جدول المنافسين في اليمين والرسم البياني في اليسار. بقية محتوى السوق يترك للنموذج ليصممه بصرياً بما يناسب المحتوى، من دون إنشاء رسم بياني إضافي أو صور.
13. يجب نقل نطاق الدراسة، وكل صف من جدول المنافسين، والملخص التنفيذي لسوق المشروع، وملخص دراسة السوق، وكل مصدر كما هو من بيانات السوق. تقسيم البيانات على شرائح إضافية مسموح، حذفها أو اختصارها غير مسموح.
14. التوزيع المضغوط لقسم السوق إلزامي: شريحة واحدة لنطاق الدراسة، شريحة واحدة لمقارنة المنافسين، شريحة واحدة لتحليل السوق المعتمد (الفقرة الواحدة)، شريحة واحدة للمصادر، وملخص دراسة سوق العمل في شريحة أو شريحتين كحد أقصى.
15. قسم تحليل SWOT للمشروع يظهر في شريحة واحدة بعد فاصل القسم، داخل مصفوفة واضحة من أربعة محاور: نقاط القوة، نقاط الضعف، الفرص، والتهديدات. لا تعرض JSON أو أقواساً أو أسماء مفاتيح برمجية.
16. إذا وجدت بيانات مخاطر معتمدة، أضف بعدها شريحة واحدة لسجل المخاطر وطرق المعالجة. اعرض كل خطر مقابل طريقة معالجته في صف واضح، ولا تكرر مصفوفة SWOT داخلها ولا تخترع مستوى خطورة أو إجراءً غير موجود في البيانات.
17. الوسائط ليست خلفية افتراضية لكل شريحة: استخدم صورة الغلاف والخاتمة عند توفرهما، والخرائط في شرائح الموقع أو تحليل الأرض عند طلبها صراحة، والصور المرفوعة في شرائح التصورات أو الأرض أو المخططات أو الجهات التي تخصها فقط. لا تضع صورة في شريحة نص أو جدول لمجرد ملء الفراغ، ولا تختزل عرضاً كاملاً إلى صورتين إذا كانت أصول مرئية متعددة متاحة. كل أصل مرئي يظهر مرة واحدة فقط وبالرمز المخصص له.
18. مخطط «مخطط اتجاهي لحدود الأرض» عنصر أساسي عند توفر أي بيانات حدود أو اتجاهات أو واجهات في الحقول الظاهرة أو الجداول المخفية لتحليل مستندات الأرض. يُدرج في العرض الكامل، ويُدرج أيضاً عند توليد قسم تحليل الموقع وحده، وتبقى بياناته وأطواله ومجاوراته كما هي دون اختراع أو محاكاة نسب مساحية.
19. الأساسيات غير قابلة للتجاوز: اتجاه RTL للنص العربي، هيدر وفوتر وهوية الشركة تضاف من النظام، لا أيقونات أو إيموجي أو صور خارجية أو بيانات وهمية، جذر HTML واحد لكل شريحة، تباين مقروء، وتدفق طبيعي يمنع تداخل النص أو قصه. لا تجعل التصميم الحر سبباً لتغيير المحتوى أو الأرقام أو الوحدات.
20. الرسوم البيانية اختيارية وليست مطلوبة في كل عرض. لا تُستخدم إلا إذا كانت بياناتها المعتمدة موجودة وفي المواقع الأربعة المسموحة فقط، مع إبقاء الجدول المالي أو جدول المنافسين الكامل ملازماً للرسم.
"""

PRESENTATION_SECTION_ORDER = (
    'overview', 'components', 'land', 'location', 'market', 'timeline', 'financial',
    'swot_risks', 'team', 'plans', 'exterior', 'interior', 'executive_summary', 'closing',
)

PRESENTATION_SECTION_TITLES = {
    'overview': 'نبذة عن المشروع',
    'components': 'مكونات المشروع',
    'land': 'تحليل الأرض',
    'location': 'تحليل الموقع الجغرافي',
    'market': 'تحليل السوق',
    'timeline': 'الجدول الزمني',
    'financial': 'الدراسة المالية',
    'swot_risks': 'تحليل SWOT وتحليل المخاطر',
    'team': 'فريق العمل',
    'plans': 'المخططات',
    'exterior': 'التصورات الخارجية',
    'interior': 'التصورات الداخلية',
    'executive_summary': 'الملخص التنفيذي',
    'closing': 'الخاتمة',
}

OFFER_LANG_ARABIC = 'ar'
OFFER_LANG_ENGLISH = 'en'

PRESENTATION_SECTION_TITLES_EN = {
    'overview': 'Project Overview',
    'components': 'Project Components',
    'land': 'Land Analysis',
    'location': 'Location Analysis',
    'market': 'Market Analysis',
    'timeline': 'Project Timeline',
    'financial': 'Financial Study',
    'swot_risks': 'SWOT & Risk Analysis',
    'team': 'Project Team',
    'plans': 'Drawings & Plans',
    'exterior': 'Exterior Visualizations',
    'interior': 'Interior Visualizations',
    'executive_summary': 'Executive Summary',
    'closing': 'Conclusion',
}

# Fixed deck-chrome labels that are not project data (cover/index/closing markers).
OFFER_CHROME_AR = {
    'cover': 'الغلاف',
    'index': 'محتويات العرض',
    'index_heading': 'محتويات العرض',
}
OFFER_CHROME_EN = {
    'cover': 'Cover',
    'index': 'Table of Contents',
    'index_heading': 'Table of Contents',
}

OFFER_LANGUAGE_DIRECTIVE_EN = (
    "OUTPUT LANGUAGE — ENGLISH:\n"
    "Author every generated word — titles, headings, paragraphs, lists, captions, table notes, "
    "summaries — in clear professional English. Copy every source value (names, figures, labels, "
    "dates, URLs) VERBATIM; never translate proper names and never recompute or reformat numbers. "
    "Keep the brief, rules and data above exactly as given; only the authored output language changes. "
    'Set dir="ltr" on generated slide roots.'
)

_ARABIC_SCRIPT_RE = re.compile(r'[\u0600-\u06FF]')
_LATIN_LETTER_RE = re.compile(r'[A-Za-z]')


# Draft keys that carry machine noise (ids, URLs, tokens, files, coordinates)
# rather than human prose. Skipped during offer-language detection so a short
# Arabic text can never be drowned by Latin identifiers.
_MACHINE_OFFER_KEY_RE = re.compile(
    r'(?:^map_|^regen_|^_|^image|^logo|^file|^http|^tenant|section_?status|page_?draft'
    r'|_id$|^id$|_url$|^url$|_path$|_token$|_file$|_meta$|_slug$|^slug$|_email$|^email$'
    r'|_hash$|^phone$|^username$|^domain$|^latitude$|^longitude$|^lat$|^lng$'
    r'|^draftid$|^draft_id$)',
    re.IGNORECASE,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew past 30k lines, so its body lives in ordered
# files under slide_engine_parts/, exec'd into this module's own namespace. Globals,
# monkeypatching (patch.object(slide_engine, 'name')) and tracebacks are unchanged:
# part files are compiled with their real path so frames point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'slide_engine_parts')
for _part_name in sorted(_n for _n in os.listdir(_PARTS_DIR) if _n.endswith('.py')):
    _part_path = os.path.join(_PARTS_DIR, _part_name)
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_name
except NameError:
    pass
del _PARTS_DIR
