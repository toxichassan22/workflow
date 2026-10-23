

import context_contracts


# ─────────────────────────────────────────────────────────────────────────────
# Slide Plan Proposal
# ─────────────────────────────────────────────────────────────────────────────

SLIDE_PLAN_PROMPT = """أنت خبير في تحليل المحتوى وتوزيعه على شرائح العروض التقديمية الاستثمارية.

## بيانات المشروع
{project_json}

## المهمة
1. حلل كمية ونوع المحتوى المتاح في بيانات المشروع
2. اقترح عدد شرائح شامل وتفصيلي يبدأ من {min_slides} شريحة كحد أدنى، والحد الأعلى مفتوح ومرن تماماً حسب حجم المشروع وتفاصيله (مثل عدد المكونات الاستثمارية، المخططات، أبعاد السوق، الجداول المالية، إلخ) بحيث تعطي كل محور حقه الكامل دون اختصار أو حصر مصطنع.
3. وزع المحتوى بحيث:
   - لا توجد شريحة فارغة أو مزدحمة
   - كل شريحة لها فكرة واحدة واضحة ومصدر بيانات محدد
   - الجداول تبقى جداول كاملة، والأرقام القابلة للمقارنة تجمع بين جدول ورسم بياني
   - النبذات والملخصات نصوص واضحة وليست شبكات مربعات
   - الصور والمخططات كبيرة وواضحة، وتستخدم كل رموز الخطة بتوزيع متوازن من صورة إلى ثلاث صور. لا تضف صورة إلى شرائح النص أو الجداول بلا حاجة، ولا تجعل كل شريحة صورة، وفي المقابل لا تحصر العرض كله في صورتين إذا كانت أصول متعددة متاحة؛ وزّع الأصول على الشرائح التي تخدمها فقط دون تكرار

{distribution_rules}

## أنواع الشرائح المسموحة
- cover: شريحة الغلاف (1 فقط، في البداية)
- index: فهرس الأقسام مع أرقام صفحات بدايتها (1 فقط، بعد الغلاف)
- content: شريحة محتوى (عدد متغير)
- section_divider: صفحة بداية قسم تحمل الاسم العربي وحده بلا وصف أو ترجمة
- moodboard: صورة خارجية كبيرة؛ يمكن توزيع الصور على أكثر من صفحة داخل قسم التصورات الخارجية
- closing: الخاتمة وبيانات التواصل (1 فقط، في النهاية)
- map_overview: خريطة الموقع + المعالم المحيطة (يتطلب إحداثيات)
- map_landmarks: خريطة + جدول أوقات القيادة (يتطلب nearby_landmarks)
- map_access: خريطة الطرق + المداخل (يتطلب main_roads)
- map_catchment: خريطة نطاق التأثير + دوائر القيادة (يتطلب catchment_areas)
- site_specs: جدول خصائص الموقع (يتطلب location data)

## أنماط تصميم الشرائح (design_style)
- dashboard: مؤشرات رقمية محدودة بمسميات الدراسة الأصلية
- cards: بطاقتان أو ثلاث فقط لعناصر مستقلة قصيرة
- timeline: مراحل زمنية مع الملاحظات الموجودة فقط
- table: جدول بيانات كامل
- chart: رسم بياني محصور حصراً في 4 أنواع معتمدة لـ 4 مواقع محددة مع جدول البيانات بجانبه (مقارنة المنافسين: horizontal_bar في دراسة السوق، وتكوين إجمالي تكلفة الاستثمار: waterfall، والتدفقات النقدية السنوية والتراكمية: combo، ومقارنة السيناريوهات المالية: heatmap في الدراسة المالية). أي نوع أو موقع آخر ممنوع منعاً باتاً
- text: فقرة أو قائمة منظمة للنبذات والملخصات
- image: صورة كبيرة + وصفها الصحيح
- flow: تسلسل نصي بسيط عند وجود خطوات فعلية
- swot: تحليل SWOT بألوان الهوية
- map: خريطة مع جدول أو ملخص دون تكرار البيانات

## تنبيه مهم
- اختر نوع الشريحة (`type`) ونمط التصميم (`design_style`) تلقائياً بناءً على بيانات المشروع وسياق التدريب الخاص بالشركة.
- لا تترك أي قرار لواجهة المستخدم بشأن النوع أو النمط.
- لا تطلب من المستخدم اختيار `type` أو `design_style` لاحقاً.

## أعد JSON فقط بالصيغة التالية:
{{
  "proposed_count": <عدد الشرائح الإجمالي>,
  "reasoning": "<سبب اختيار هذا العدد بالعربي>",
  "slides": [
    {{
      "title": "عنوان الشريحة بالعربي",
      "type": "cover|index|content|section_divider|moodboard|closing|map_overview|map_landmarks|map_access|map_catchment|site_specs",
      "section_key": "overview|components|land|location|market|timeline|financial|swot_risks|team|plans|exterior|interior|executive_summary|closing",
      "content_density": "low|medium|high",
      "design_style": "dashboard|cards|timeline|table|chart|text|image|flow|swot|map|diagram|divider",
      "chart_type": "horizontal_bar|waterfall|combo|heatmap أو فارغ",
      "bullets": ["نقطة 1", "نقطة 2", "نقطة 3"],
      "requires_image": true أو false,
      "content_source": "<الحقل أو الجدول الذي يغذي هذه الشريحة>",
      "image_tokens": ["<رموز الصور المتاحة لهذه الشريحة فقط>"]
    }}
  ]
}}

## قواعد إضافية:
- الشريحة الأولى غلاف، والثانية فهرس أقسام، والأخيرة خاتمة. لا يوجد موضع ثابت لأي صورة أو مود بورد خارج ترتيب الأقسام المحدد.
- استخدم `section_key` في كل شريحة، والتزم بترتيب الأقسام الوارد أعلاه دون تقديم أو تأخير.
- ضع `section_divider` واحدًا قبل محتوى كل قسم موجود. عنوانه هو اسم القسم العربي المعتمد فقط، وحقول `title_en` و`subtitle` غير مستخدمة ويجب ألا تظهر.
- لا تكرر مكونات المشروع أو جداول الموقع أو السوق. اعرض الجدول مرة واحدة، ثم اختم القسم بملخصه النهائي بعد الجداول.
- نبذة عن المشروع نصية ولا تستخدم رموز التصورات الخارجية؛ كل صورة خارجية محفوظة لقسم التصورات الخارجية فقط حتى تظهر مرة واحدة ولا تضيع من قسمها.
- صور الأرض تُعرض مع الوصف المحفوظ لكل صورة، ثم ملخص تحليل الأرض المعتمد. لا تستخدم صورة أرض بلا وصف إن كان الوصف متاحًا.
- عند توفر أبعاد وحدود للأرض والشوارع المحيطة، يتم تضمين شريحة «مخطط اتجاهي لحدود الأرض» بنمط diagram لتمثيل الأرض والجهات الأربع والشوارع والإطلالات بيانياً بالـ CSS و HTML النقي دون الحاجة لرسومات خارجية.
- بيانات مخطط حدود الأرض قد تكون في الحقول الظاهرة أو في `directions_table` أو نتيجة تحليل مستندات الأرض المخفية؛ اعتبرها بيانات كافية لإضافة المخطط ولا تنتظر حقلاً ظاهراً واحداً بعينه. هذا المخطط عنصر أساسي في العرض الكامل، ويُحافظ عليه أيضاً عند توليد تحليل الموقع وحده.
- عند توفر مواصفات للأرض أو اشتراطات تنظيمية (مثل رقم الصك أو المخطط أو القطعة أو المساحة أو نسبة البناء أو الارتدادات أو الارتفاعات أو الاستخدام أو المواقف)، يتم تضمين شريحة «مواصفات الأرض والاشتراطات التنظيمية» بنمط specs لعرض هذه البيانات والمعايير بدقة وتنظيم.
- قسم دراسة السوق يبدأ دائماً بفاصل قسم section_divider باسم «دراسة السوق». إذا زاد عدد المنافسين عن 4، يُقسم المنافسون على شرائح متعددة بحد أقصى 4 منافسين في كل شريحة مع الرسم البياني الأفقي المقابل لهم لضمان وضوح الأرقام ومنع الازدحام. وتحليل أبعاد السوق الستة يُوزع على شريحتين أو ثلاث بحد أقصى 3 محاور في الشريحة.
- عند توفر مراحل زمنية أو تاريخ بدء ومدة للمشروع، يتم تضمين شريحة «الجدول الزمني ومراحل التطوير» بنمط timeline لعرض المراحل التنفيذية المتسلسلة ومددها ومواعيدها بتصميم أفقي متناسق.
- الدراسة المالية تأخذ عدد الشرائح الذي تحتاجه جميع جداول تقرير المعاينة ومؤشراته، ثم يأتي الملخص المالي في نهاية القسم مقسمًا إلى شريحتين أو ثلاث. الرسوم البيانية محصورة حصراً في 4 أنواع معتمدة لـ 4 مواقع محددة فقط في كامل العرض: 1) مقارنة المنافسين (horizontal_bar) في قسم دراسة السوق، 2) تكوين إجمالي تكلفة الاستثمار (waterfall) في الدراسة المالية، 3) التدفقات النقدية السنوية والتراكمية (combo) في الدراسة المالية، 4) مقارنة السيناريوهات المالية (heatmap) في الدراسة المالية. يمنع منعاً باتاً إضافة أي رسم بياني خارج هذه المواقع الأربعة أو استخدام أي نوع آخر.
- الدراسة المالية تُسحب كما أُدخلت وحُسبت في التقرير: لا إعادة حساب أو تقريب أو تحويل وحدات أو حذف صفوف أو أعمدة أو سنوات، ولا إعادة تفسير تصميمية للمحتوى. التصميم يغيّر الهوية البصرية فقط، والرسم المالي لا يظهر إلا عند توفر بياناته المعتمدة وبجوار الجدول الكامل.
- فريق العمل يحافظ على ترتيب الجهات وحقولها كما أُدخلت، ويستخدم شعار كل جهة عند الحديث عنها. لا ينشئ فئات أو مسميات جديدة.
- كل مخطط مرفوع له صفحة مستقلة أو مساحة كبيرة مع عنوانه ووصفه؛ ممنوع جمع مخططات كثيرة في شبكة صغيرة.
- التصورات الخارجية والداخلية تستخدم كل رموز الصور المحددة لكل شريحة، من صورة إلى ثلاث، ضمن تخطيط متوازن للمجموعة كلها ودون تكرار.
- الملخصات والتحسينات لا تتجاوز الحقائق المعتمدة، ولا تستخدم عبارات عامة أو استرسالًا لا يضيف قيمة واضحة.
- الخاتمة تعرض بيانات التواصل المتاحة، وتمنع عبارات «فرصة واعدة بشروط» أو أي تقييم مشروط مشابه.
- قواعد الشركة في بداية الرسالة ملزمة ما لم تخالف ترتيب الأقسام أو دقة البيانات أو منع الأيقونات.
- {no_street_view}
"""


# There is no upper limit on how many slides a project may need. The stored max_slides used to
# trim the plan — a project with more content than the number allowed simply lost the surplus
# slides, and the planner was told to obey a ceiling the prompt itself calls open.
SLIDE_COUNT_OPEN = 100000

# The slide count belongs to the planner, not to a tenant setting — the company no
# longer has a field for it. The only bounds left are platform constants: a sanity
# floor so a thin project still gets a real deck, and a fixed count just for the
# deterministic fallback plan. Stored tenant values are ignored.
PLAN_MIN_SLIDES = 8
PLAN_FALLBACK_SLIDE_COUNT = 16


def resolve_slide_bounds(branding):
    """Resolve (min_slides, max_slides, default_count) — platform constants."""
    return PLAN_MIN_SLIDES, SLIDE_COUNT_OPEN, PLAN_FALLBACK_SLIDE_COUNT


def build_fallback_plan(branding, project_data=None, offer_lang=None):
    """Build a default slide plan when AI slide planning fails.

    Uses the tenant's min/max/default slide count bounds.
    """
    lang = resolve_offer_lang(project_data, offer_lang)
    min_s, max_s, default_count = resolve_slide_bounds(branding)
    count = max(min_s, min(default_count, max_s))
    fallback_bullets = (['Approved content for this section', 'Available details from the project data',
                         'Final summary without repetition']
                        if lang == OFFER_LANG_ENGLISH else
                        ['المحتوى المعتمد لهذا القسم', 'التفاصيل المتاحة في بيانات المشروع',
                         'الملخص النهائي دون تكرار'])
    extra_bullets = (['Additional detail from the project data', 'Concise wording',
                      'Without inventing information']
                     if lang == OFFER_LANG_ENGLISH else
                     ['تفصيل إضافي من بيانات المشروع', 'صياغة موجزة', 'دون اختراع معلومات'])
    slides = [
        {'title': offer_chrome('cover', lang), 'type': 'cover', 'design_style': 'image', 'requires_image': True, 'bullets': [], 'content_density': 'low'},
        {'title': offer_chrome('index', lang), 'type': 'index', 'design_style': 'text', 'requires_image': False, 'bullets': [], 'content_density': 'low'},
    ]
    content_sections = PRESENTATION_SECTION_ORDER[:-1]
    needed = max(0, count - 3)
    for section_key in content_sections[:needed]:
        title = section_title(section_key, lang)
        slides.append({
            'title': title,
            'type': 'content',
            'section_key': section_key,
            'design_style': _suggest_design_style(title, slide_type='content'),
            'requires_image': section_key in {'plans', 'exterior', 'interior'},
            'bullets': list(fallback_bullets),
            'content_density': 'medium',
        })
    while len(slides) < count - 1:
        slides.append({
            'title': section_title('overview', lang), 'type': 'content',
            'section_key': 'overview', 'design_style': 'text', 'requires_image': False,
            'bullets': list(extra_bullets),
            'content_density': 'medium',
        })
    slides.append({'title': section_title('closing', lang), 'type': 'closing', 'section_key': 'closing', 'design_style': 'minimal', 'requires_image': False, 'bullets': [], 'content_density': 'low'})
    return {'proposed_count': len(slides), 'slides': slides}


def _plan_asset_note(images):
    if not isinstance(images, dict):
        return ''
    moodboard = _available_asset_items(images.get('moodboard'))
    land_photos = _available_asset_items(images.get('land_photos'))
    plans = _available_asset_items(images.get('plans'))
    interiors = []
    for component_index, component in enumerate(images.get('interior_components') or [], 1):
        if not isinstance(component, dict):
            continue
        for image_index, item in _available_asset_items(component.get('images')):
            interiors.append({
                'component': component.get('name') or f'المكون {component_index}',
                'token': f'##INTERIOR_COMP_{component_index}_IMG_{image_index}##',
                'label': item.get('label') or '', 'caption': item.get('caption') or '',
            })
    summary = {
        'التصورات الخارجية': [f'##MOODBOARD_IMAGE_{index}##' for index, _item in moodboard],
        'صور الأرض': [{
            'token': f'##LAND_PHOTO_{index}##',
            'description': item.get('description') or item.get('caption') or '',
        } for index, item in land_photos],
        'المخططات': [f'##PLAN_IMAGE_{index}##' for index, _item in plans],
        'التصورات الداخلية': interiors,
        'فريق العمل': [{
            'name': item.get('name') or '', 'has_logo': bool(item.get('logo')),
            'token': f'##TEAM_LOGO_{index}##' if item.get('logo') else '',
        } for index, item in enumerate(images.get('team_members') or [], 1) if isinstance(item, dict)],
    }
    if not any(summary.values()):
        return ''
    return '\n\n## وسائط العرض المتوفرة وتوزيعها الإلزامي\n' + json.dumps(summary, ensure_ascii=False, indent=2)


def build_slide_plan_prompt(project_data, branding, tenant_id=None, images=None, offer_lang=None,
                            section_keys=None):
    """Build the prompt for AI to propose a slide plan.

    The plan decides which slides exist, so it has to see every section. Cutting the payload at
    6,000 characters meant the market study, the executive content and the team never reached the
    planner, and it could not propose slides for facts it was never shown.

    ``section_keys`` is a section-mode scope (deck or project keys). The full
    deck leaves it ``None`` so the historical brief stays byte-identical.
    """
    lang = resolve_offer_lang(project_data, offer_lang)
    fact_sections = context_contracts.fact_section_keys(section_keys)
    if fact_sections:
        project_json = build_project_facts(project_data, tenant_id, section_keys=fact_sections)
    else:
        project_json = build_project_facts(project_data, tenant_id)

    min_slides, max_slides, _default_count = resolve_slide_bounds(branding)

    prompt = SLIDE_PLAN_PROMPT.format(
        project_json=project_json,
        min_slides=min_slides,
        max_slides=max_slides,
        distribution_rules=CONTENT_DISTRIBUTION_RULES,
        no_street_view=NO_STREET_VIEW_RULE,
    )
    if lang == OFFER_LANG_ENGLISH:
        prompt = prompt.replace(
            '- section_divider: صفحة بداية قسم تحمل الاسم العربي وحده بلا وصف أو ترجمة',
            '- section_divider: a section opener carrying the approved English section name alone, no description or translation')
        prompt = prompt.replace(
            '"title": "عنوان الشريحة بالعربي"',
            '"title": "Slide title in English"')
        prompt = prompt.replace(
            '"bullets": ["نقطة 1", "نقطة 2", "نقطة 3"]',
            '"bullets": ["Point 1", "Point 2", "Point 3"]')
        prompt = prompt.replace(
            'عنوانه هو اسم القسم العربي المعتمد فقط',
            'its title is the approved English section name only')
        prompt = prompt.replace(
            'يتم تضمين شريحة «مخطط اتجاهي لحدود الأرض» بنمط diagram',
            'include a "Directional Plot Boundary Diagram" slide with the diagram style')
        prompt = prompt.replace(
            'وتمنع عبارات «فرصة واعدة بشروط» أو أي تقييم مشروط مشابه',
            'and never write investment verdicts or similar conditional assessments')
        prompt += '\n\n' + OFFER_LANGUAGE_DIRECTIVE_EN
    asset_note = _plan_asset_note(images)
    if asset_note:
        prompt += asset_note
    if context_contracts.note_in_scope(section_keys, 'location'):
        location_note = _location_data_note(project_data)
        if location_note:
            prompt += location_note
    if context_contracts.note_in_scope(section_keys, 'timeline'):
        timeline_note = _timeline_data_note(project_data)
        if timeline_note:
            prompt += timeline_note
    financial_note = ''
    if context_contracts.note_in_scope(section_keys, 'financial'):
        financial_note = _financial_data_note(project_data)
        if financial_note:
            prompt += financial_note
    if ((not financial_note or financial_note == FINANCIAL_ABSENT_NOTE)
            and context_contracts.scope_needs_components(section_keys)):
        components_note = _project_components_note(project_data)
        if components_note:
            prompt += components_note
    return prompt


def _extract_json_from_text(response_text):
    """Robustly extract the first JSON object from AI response text."""
    if not response_text:
        return None

    # Try markdown code blocks first
    code_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', response_text)
    if code_match:
        candidate = code_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # Balanced brace parser: find the outermost { } object
    start = response_text.find('{')
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(response_text)):
            ch = response_text[i]
            if in_string:
                if escape:
                    escape = False
                    continue
                if ch == '\\':
                    escape = True
                    continue
                if ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = response_text[start:i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break

    # Fallback to greedy regex
    json_match = re.search(r'\{[\s\S]*\}', response_text)
    if json_match:
        return json_match.group()

    return None


def parse_slide_plan(response_text, branding=None, project_data=None):
    """Parse the AI response into a slide plan dict."""
    json_text = _extract_json_from_text(response_text)
    if not json_text:
        raise ValueError("No JSON found in AI response")

    try:
        plan = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    # Validate structure
    if 'slides' not in plan or not isinstance(plan['slides'], list):
        raise ValueError("Missing 'slides' array in response")

    plan['proposed_count'] = len(plan['slides'])

    # Ensure first slide is cover and last is closing
    if plan['slides']:
        plan['slides'][0]['type'] = 'cover'
        plan['slides'][-1]['type'] = 'closing'

    # Ensure second slide is index when there are at least three slides
    if len(plan['slides']) > 2:
        plan['slides'][1]['type'] = 'index'

    # If location data exists but the AI marked a location slide as plain content,
    # convert it to the appropriate map type so the map image is actually used.
    if project_data:
        for slide in plan['slides']:
            if slide.get('type') == 'content':
                map_type = _maybe_map_slide_type(slide.get('title'), project_data)
                if map_type:
                    slide['type'] = map_type
                    if 'design_style' not in slide or slide.get('design_style') == 'cards':
                        slide['design_style'] = 'map'
                    if 'requires_image' not in slide:
                        slide['requires_image'] = True

    # Fill defaults for any missing slide metadata, and avoid long runs of 4-card layouts
    prev_content_style = None
    for slide in plan['slides']:
        slide_type = slide.get('type', 'content')
        if 'design_style' not in slide:
            slide['design_style'] = _suggest_design_style(
                slide.get('title'), slide.get('bullets', []), slide_type
            )
        if slide_type == 'content':
            if slide.get('design_style') == prev_content_style and prev_content_style == 'cards':
                slide['design_style'] = 'text'
            prev_content_style = slide.get('design_style')
        if 'content_density' not in slide:
            slide['content_density'] = 'medium'
        if 'requires_image' not in slide:
            slide['requires_image'] = (
                slide_type in ('cover', 'moodboard', 'section_divider')
                or slide_type.startswith('map_')
                or slide.get('design_style') == 'image'
            )

    return plan


def validate_slide_plan(plan, branding):
    """
    Validate the slide plan against content distribution rules.
    Returns (is_valid, issues_list).
    """
    issues = []
    slides = plan.get('slides', [])

    if not slides:
        issues.append("No slides in plan")
        return False, issues

    # Check min/max slides
    min_s, max_s, _default_count = resolve_slide_bounds(branding)
    count = len(slides)
    if count < min_s:
        issues.append(f"Too few slides: {count} (min: {min_s})")
    if count > max_s:
        issues.append(f"Too many slides: {count} (max: {max_s})")

    # Check fixed-position slides
    valid_types = {'cover', 'index', 'content', 'section_divider', 'moodboard', 'closing',
                   'map_overview', 'map_landmarks', 'map_access', 'map_catchment',
                   'site_specs'}

    if slides[0].get('type') != 'cover':
        issues.append("First slide must be 'cover'")
    if len(slides) > 1 and slides[1].get('type') != 'index':
        issues.append("Second slide must be 'index'")
    if slides[-1].get('type') != 'closing':
        issues.append("Last slide must be 'closing'")

    # Check each slide type and content
    for i, slide in enumerate(slides):
        slide_type = slide.get('type', 'content')
        if slide_type not in valid_types:
            issues.append(f"Slide {i+1} has unknown type '{slide_type}'")

        if slide_type in ('content', 'site_specs', 'map_landmarks'):
            bullets = slide.get('bullets', [])
            has_structured_source = bool(slide.get('content_source') or slide.get('source_table') or slide.get('image_tokens'))
            if len(bullets) < 3 and not has_structured_source:
                issues.append(f"Slide {i+1} '{slide.get('title', '?')}' has only {len(bullets)} bullets (min: 3)")
            if len(bullets) > 6:
                issues.append(f"Slide {i+1} '{slide.get('title', '?')}' has {len(bullets)} bullets (max: 6)")

    return len(issues) == 0, issues


def _clean_numeric_val(val):
    if val is None:
        return 0.0
    s = str(val).strip()
    if not s or s in ('—', '-', 'غير متاح', 'N/A'):
        return 0.0
    neg = '(' in s or '-' in s
    cleaned = re.sub(r'[^\d.]', '', s.replace(',', ''))
    try:
        n = float(cleaned)
        return -n if neg else n
    except (ValueError, TypeError):
        return 0.0


def _clean_numeric_val_strict(val):
    if val is None:
        return None
    s = str(val).strip()
    if not s or s in ('—', '-', 'غير متاح', 'N/A', 'لا يسترد', 'غير مسترد', 'none', 'null'):
        return None
    neg = '(' in s or '-' in s
    cleaned = re.sub(r'[^\d.]', '', s.replace(',', ''))
    try:
        n = float(cleaned)
        return -n if neg else n
    except (ValueError, TypeError):
        return None


def _format_sar_display(val):
    val_m = val / 1e6
    if abs(val_m) >= 0.1:
        # Millions are a display unit, not a new value: the amount is rounded
        # half-up to the hundredth so the label reads like the financial study.
        return f"{format_millions(val_m)} مليون ر.س"
    return f"{format_financial_number(val)} ر.س"


def _competitor_candidates(comp):
    if not isinstance(comp, dict):
        return []
    candidates = [comp]
    for key in ('pricing', 'price_data', 'price_details', 'area_data', 'details'):
        nested = comp.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    return candidates


def _competitor_value(comp, *keys):
    for candidate in _competitor_candidates(comp):
        for key in keys:
            value = candidate.get(key)
            if value not in (None, '', [], {}):
                return value
    return ''


def _competitor_name(comp):
    value = _competitor_value(comp, 'name', 'competitor_name', 'project_name', 'اسم المشروع')
    return str(value or '').strip() if not isinstance(value, (dict, list)) else ''


def _competitor_price_fields(comp):
    price_value = _competitor_value(comp, 'price_value', 'value', 'القيمة', 'price')
    price_from = _competitor_value(comp, 'price_from', 'min_price', 'from', 'من')
    price_to = _competitor_value(comp, 'price_to', 'max_price', 'to', 'إلى')
    if isinstance(price_value, dict):
        price_value = _competitor_value(price_value, 'price_value', 'value', 'القيمة', 'amount')
    if isinstance(price_from, dict):
        price_from = _competitor_value(price_from, 'price_from', 'min_price', 'from', 'من', 'value')
    if isinstance(price_to, dict):
        price_to = _competitor_value(price_to, 'price_to', 'max_price', 'to', 'إلى', 'value')
    return price_value, price_from, price_to


def _competitor_logo_token(comp, index):
    if isinstance(comp, dict) and any(comp.get(key) for key in ('logo_file_id', 'logo_path', 'logo_url')):
        return f'##COMPETITOR_LOGO_{index}##'
    return ''


def _competitor_display_text(value, fallback='—'):
    if isinstance(value, list):
        value = '، '.join(str(item).strip() for item in value if str(item).strip())
    elif isinstance(value, dict):
        value = '، '.join(f'{key}: {val}' for key, val in value.items()
                          if val not in (None, '', [], {}))
    text = str(value or '').strip()
    return text or fallback


def _competitor_price_display(comp, offer_lang='ar'):
    en = offer_lang == 'en'
    price_value, price_from, price_to = _competitor_price_fields(comp)
    currency = _competitor_value(comp, 'price_currency', 'currency', 'العملة')
    values = []
    value_text, _ = _format_table_num(price_value)
    from_text, _ = _format_table_num(price_from)
    to_text, _ = _format_table_num(price_to)
    if price_value not in (None, '', []) and value_text != '—':
        values.append(value_text)
    elif (price_from not in (None, '', []) or price_to not in (None, '', [])):
        range_text = (f'{from_text} – {to_text}' if en
                      else f'من {from_text} إلى {to_text}')
        values.append(range_text)
    if currency and values:
        values[-1] = f'{values[-1]} {str(currency).strip()}'
    price_type = _competitor_value(comp, 'price_type', 'pricing_type', 'نوع السعر', 'type')
    if price_type:
        values.insert(0, _competitor_display_text(price_type))
    return ' | '.join(values) if values else '—'


def _competitor_chart_group(comp):
    """Return comparable unit/type keys required by the approved chart spec."""
    operation = str(_competitor_value(comp, 'operation_type', 'operation', 'نوع العملية') or '').strip().lower()
    operation = re.sub(r'\s+', ' ', operation)
    if any(token in operation for token in ('بيع', 'sale')):
        operation = 'sale'
    elif any(token in operation for token in ('إيجار', 'ايجار', 'rent')):
        operation = 'rent'
    elif any(token in operation for token in ('فندقي', 'تشغيل', 'hotel')):
        operation = 'hotel'

    price_type = str(_competitor_value(comp, 'price_type', 'pricing_type', 'نوع السعر') or '').strip().lower()
    unit = str(_competitor_value(comp, 'unit') or
               (comp.get('area_cache') if isinstance(comp.get('area_cache'), dict) else {}).get('unit') or '').strip().lower()
    if any(token in (price_type + ' ' + unit) for token in ('متر', 'م²', 'm²', 'sqm', 'sq m')):
        unit_key = 'sqm'
    elif any(token in (price_type + ' ' + unit) for token in ('وحدة', 'unit')):
        unit_key = 'unit'
    elif any(token in (price_type + ' ' + unit) for token in ('ليلة', 'غرفة', 'adr', 'revpar', 'night', 'room')):
        unit_key = 'room_night'
    else:
        unit_key = unit or 'unspecified'

    if any(token in price_type for token in ('نطاق', 'range', 'من', 'إلى')):
        type_key = 'range'
    elif unit_key == 'sqm':
        type_key = 'per_sqm'
    elif unit_key == 'unit':
        type_key = 'per_unit'
    elif unit_key == 'room_night':
        type_key = 'room_night'
    else:
        type_key = re.sub(r'[^a-z0-9ء-ي]+', '', price_type) or 'unspecified'
    return operation, unit_key, type_key


def _extract_competitor_chart_data(competitors, project_data=None):
    project_data = project_data if isinstance(project_data, dict) else {}
    en = resolve_offer_lang(project_data) == OFFER_LANG_ENGLISH
    candidates = []
    for comp in (competitors or []):
        if not isinstance(comp, dict):
            continue
        name = _competitor_name(comp)
        price_val, p_from, p_to = _competitor_price_fields(comp)
        p_type = str(_competitor_value(comp, 'price_type', 'pricing_type', 'نوع السعر', 'type') or '').strip()
        unit = str(_competitor_value(comp, 'unit') or
                   (comp.get('area_cache') if isinstance(comp.get('area_cache'), dict) else {}).get('unit') or '').strip()

        value_num = _clean_numeric_val(price_val)
        from_num = _clean_numeric_val(p_from)
        to_num = _clean_numeric_val(p_to)
        if value_num <= 0 and from_num <= 0 and to_num <= 0:
            continue
        if value_num > 0:
            low_num = high_num = value_num
        else:
            valid_range = [value for value in (from_num, to_num) if value > 0]
            if not valid_range:
                continue
            low_num = min(valid_range)
            high_num = max(valid_range)
        if name:
            unit_str = f" {unit}" if unit else (" SAR/m²" if en else " ر.س/م²")
            candidates.append({
                'name': name,
                'price_num': high_num,
                'price_min_num': low_num,
                'price_max_num': high_num,
                'is_range': high_num != low_num,
                'display_price': (
                    (f"{int(low_num):,} – {int(high_num):,}{unit_str}" if en
                     else f"من {int(low_num):,} إلى {int(high_num):,}{unit_str}")
                    if high_num != low_num else f"{int(high_num):,}{unit_str}"
                ),
                'price_type': p_type,
                'unit': unit,
                'chart_group': _competitor_chart_group(comp),
                'is_project': False,
            })

    # Never mix sale/rent, per-unit/per-square-metre, or range/point price
    # types on one axis. Every populated comparable group is kept as its own
    # labelled chart section so no named competitor disappears silently.
    grouped = {}
    for item in candidates:
        grouped.setdefault(item.get('chart_group'), []).append(item)
    groups = sorted(
        grouped.items(),
        key=lambda pair: (len(pair[1]), max(item['price_num'] for item in pair[1])),
        reverse=True,
    )

    proj_price_raw = project_data.get('proposed_price') or project_data.get('project_price')
    market = _decode_json_fact(project_data.get('market_study_data')) if isinstance(project_data.get('market_study_data'), (str, dict)) else {}
    if not proj_price_raw and isinstance(market, dict):
        proj_price_raw = market.get('proposed_price') or market.get('project_price')
    if proj_price_raw and groups:
        p_val = _clean_numeric_val(proj_price_raw)
        if p_val > 0:
            p_name = str(project_data.get('project_name') or project_data.get('projectName')
                         or ('Our Project' if en else 'مشروعنا')).strip()
            first_items = groups[0][1]
            unit_str = first_items[0]['display_price'].split()[-1] if first_items and ' ' in first_items[0]['display_price'] else ('SAR/m²' if en else 'ر.س/م²')
            first_items.append({
                'name': f"{p_name} ({'Proposed Project' if en else 'المشروع المقترح'})",
                'price_num': p_val,
                'price_min_num': p_val,
                'price_max_num': p_val,
                'is_range': False,
                'display_price': f"{int(p_val):,} {unit_str}",
                'price_type': 'Proposed Price' if en else 'سعر مقترح',
                'chart_group': groups[0][0],
                'is_project': True,
            })

    items = []
    for group_key, group_items in groups:
        group_items = list(group_items)
        group_items.sort(key=lambda x: x['price_num'], reverse=True)
        has_range = any(item.get('is_range') for item in group_items)
        max_p = max((x['price_max_num'] for x in group_items), default=1.0)
        if has_range:
            axis_min = min((x['price_min_num'] for x in group_items), default=0.0)
            span = max(max_p - axis_min, 1.0)
            for it in group_items:
                it['bar_start_pct'] = max(round(((it['price_min_num'] - axis_min) / span) * 100, 1), 0.0)
                it['bar_width_pct'] = max(round(((it['price_max_num'] - it['price_min_num']) / span) * 100, 1), 2.0)
        else:
            for it in group_items:
                it['bar_start_pct'] = 0.0
                it['bar_width_pct'] = max(round((it['price_max_num'] / max_p) * 100, 1), 15.0)
        label = _competitor_group_label(group_key, 'en' if en else 'ar')
        for position, it in enumerate(group_items):
            it['group_key'] = group_key
            it['group_label'] = label
            it['group_first'] = position == 0
            items.append(it)

    if len(items) > 8:
        project_item = next((it for it in items if it.get('is_project')), None)
        items = items[:8]
        if project_item and project_item not in items:
            items[-1] = project_item

    return items


def _competitor_group_label(group_key, offer_lang='ar'):
    """Human label for one comparable chart section (operation + unit + price kind)."""
    en = offer_lang == 'en'
    operation, unit_key, type_key = (group_key or (None, None, None))
    op_label = {
        'sale': 'Sale Projects' if en else 'مشاريع البيع',
        'rent': 'Rental Projects' if en else 'مشاريع الإيجار',
        'hotel': 'Hotel Operations' if en else 'التشغيل الفندقي',
    }.get(operation, '')
    unit_label = {
        'sqm': 'Price per SQM' if en else 'سعر المتر المربع',
        'unit': 'Unit Price' if en else 'سعر الوحدة',
        'room_night': 'Nightly Rate' if en else 'سعر الليلة',
    }.get(unit_key, '')
    if type_key == 'range':
        unit_label = (f'{unit_label} (Range)' if unit_label else 'Price Range') if en \
            else (f'{unit_label} (نطاق)' if unit_label else 'نطاق سعري')
    if op_label and unit_label:
        return f'{op_label} — {unit_label}'
    return op_label or unit_label or ('Competitor Prices' if en else 'أسعار المنافسين')
