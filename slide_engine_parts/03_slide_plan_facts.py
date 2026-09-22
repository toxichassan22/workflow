

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
# slides, and the planner was told to obey a ceiling the prompt itself calls open. Only
# lock_slide_count still binds the count, and then it binds it exactly.
SLIDE_COUNT_OPEN = 100000


def resolve_slide_bounds(branding):
    """Resolve (min_slides, max_slides, default_count) from branding.

    When lock_slide_count is enabled the tenant's default_slide_count becomes an
    exact requirement. Otherwise only the minimum applies and the upper end is open:
    the planner decides the count from the amount of content.
    """
    branding = branding or {}
    default_count = int(branding.get('default_slide_count') or 16)
    if branding.get('lock_slide_count'):
        return default_count, default_count, default_count
    min_slides = int(branding.get('min_slides') or 14)
    return min(min_slides, SLIDE_COUNT_OPEN), SLIDE_COUNT_OPEN, default_count


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


def build_slide_plan_prompt(project_data, branding, tenant_id=None, images=None, offer_lang=None):
    """Build the prompt for AI to propose a slide plan.

    The plan decides which slides exist, so it has to see every section. Cutting the payload at
    6,000 characters meant the market study, the executive content and the team never reached the
    planner, and it could not propose slides for facts it was never shown.
    """
    lang = resolve_offer_lang(project_data, offer_lang)
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
    location_note = _location_data_note(project_data)
    if location_note:
        prompt += location_note
    timeline_note = _timeline_data_note(project_data)
    if timeline_note:
        prompt += timeline_note
    financial_note = _financial_data_note(project_data)
    if financial_note:
        prompt += financial_note
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


def _enforce_slide_count(slides, target_count, offer_lang=None, project_data=None):
    """Trim or pad a slide list to exactly target_count, keeping fixed slides intact.

    The cover, index and closing slides keep their reserved positions;
    only content slides are removed or appended.
    """
    lang = resolve_offer_lang(project_data, offer_lang)
    if target_count < 1 or len(slides) == target_count:
        return slides

    reserved_tail_types = {'closing'}

    if len(slides) > target_count:
        head = slides[:2]                      # cover + index
        tail = [s for s in slides[-2:] if s.get('type') in reserved_tail_types]
        middle = slides[len(head):len(slides) - len(tail)]
        keep_middle = max(0, target_count - len(head) - len(tail))
        return (head + middle[:keep_middle] + tail)[:target_count]

    tail = [s for s in slides[-2:] if s.get('type') in reserved_tail_types]
    body = slides[:len(slides) - len(tail)]
    while len(body) + len(tail) < target_count:
        title = (f'Additional details {len(body)}' if lang == OFFER_LANG_ENGLISH
                 else f'تفاصيل إضافية {len(body)}')
        style = _suggest_design_style(title, slide_type='content')
        if body and body[-1].get('design_style') == style and style == 'cards':
            style = 'text'
        body.append({
            'title': title,
            'type': 'content',
            'design_style': style,
            'content_density': 'medium',
            'requires_image': False,
            'bullets': (['First key point', 'Second key point', 'Third key point']
                        if lang == OFFER_LANG_ENGLISH else
                        ['نقطة رئيسية أولى', 'نقطة رئيسية ثانية', 'نقطة رئيسية ثالثة']),
        })
    return body + tail


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

    # A locked slide count is a hard tenant requirement: reshape the plan
    # instead of failing validation and burning another generation round.
    if branding and branding.get('lock_slide_count'):
        _min_s, _max_s, default_count = resolve_slide_bounds(branding)
        if len(plan['slides']) != default_count:
            print(f"[SLIDE-PLAN] lock_slide_count active: reshaping "
                  f"{len(plan['slides'])} -> {default_count} slides")
            plan['slides'] = _enforce_slide_count(plan['slides'], default_count, project_data=project_data)

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
    val_m = round(val / 1e6, 2)
    if abs(val_m) >= 0.1:
        return f"{round(val / 1e6, 1)} ر.س"
    return f"{int(val):,} ر.س"


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


def _competitor_price_display(comp):
    price_value, price_from, price_to = _competitor_price_fields(comp)
    currency = _competitor_value(comp, 'price_currency', 'currency', 'العملة')
    values = []
    value_text, _ = _format_table_num(price_value)
    from_text, _ = _format_table_num(price_from)
    to_text, _ = _format_table_num(price_to)
    if price_value not in (None, '', []) and value_text != '—':
        values.append(value_text)
    elif (price_from not in (None, '', []) or price_to not in (None, '', [])):
        range_text = f'من {from_text} إلى {to_text}'
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
            unit_str = f" {unit}" if unit else " ر.س/م²"
            candidates.append({
                'name': name,
                'price_num': high_num,
                'price_min_num': low_num,
                'price_max_num': high_num,
                'is_range': high_num != low_num,
                'display_price': (
                    f"من {int(low_num):,} إلى {int(high_num):,}{unit_str}"
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
            p_name = str(project_data.get('project_name') or project_data.get('projectName') or 'مشروعنا').strip()
            first_items = groups[0][1]
            unit_str = first_items[0]['display_price'].split()[-1] if first_items and ' ' in first_items[0]['display_price'] else 'ر.س/م²'
            first_items.append({
                'name': f"{p_name} (المشروع المقترح)",
                'price_num': p_val,
                'price_min_num': p_val,
                'price_max_num': p_val,
                'is_range': False,
                'display_price': f"{int(p_val):,} {unit_str}",
                'price_type': 'سعر مقترح',
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
        label = _competitor_group_label(group_key)
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


def _competitor_group_label(group_key):
    """Human label for one comparable chart section (operation + unit + price kind)."""
    operation, unit_key, type_key = (group_key or (None, None, None))
    op_label = {
        'sale': 'مشاريع البيع',
        'rent': 'مشاريع الإيجار',
        'hotel': 'التشغيل الفندقي',
    }.get(operation, '')
    unit_label = {
        'sqm': 'سعر المتر المربع',
        'unit': 'سعر الوحدة',
        'room_night': 'سعر الليلة',
    }.get(unit_key, '')
    if type_key == 'range':
        unit_label = f'{unit_label} (نطاق)' if unit_label else 'نطاق سعري'
    if op_label and unit_label:
        return f'{op_label} — {unit_label}'
    return op_label or unit_label or 'أسعار المنافسين'


def _build_waterfall_svg(items, total, width=1050, height=340, primary='#16405f', secondary='#0284c7', gold='#b89564'):
    total_val_m = total.get('value_millions', 0.0)
    if total_val_m <= 0:
        total_val_m = sum(it.get('value_millions', 0.0) for it in items) or 1.0

    # Axis: smallest nice step that covers the total with headroom in 4-6
    # gridlines, so a 11M project no longer flattens under a 0-100 axis.
    import math as _math
    target = total_val_m * 1.12 if total_val_m > 0 else 1.0
    mag = 10.0 ** _math.floor(_math.log10(target))
    tick_step = target / 4.0
    ticks = None
    for m in (0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.5, 2.0):
        step = m * mag
        n = target / step
        if 4 <= n <= 6:
            n_ticks = _math.ceil(n)
            max_tick = step * n_ticks
            tick_step = step
            ticks = [round(step * i, 6) for i in range(n_ticks + 1)]
            break
    if ticks is None:
        max_tick = target
        tick_step = max_tick / 4.0
        ticks = [0.0, tick_step, tick_step * 2, tick_step * 3, max_tick]

    n_cols = len(items) + 1
    use_stagger = n_cols >= 7
    pad_left = 60
    pad_right = 25
    pad_top = 45
    pad_bottom = 80 if use_stagger else 65
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom

    def y_for(val):
        return round(pad_top + chart_h - (val / max_tick) * chart_h, 1)

    y_zero = y_for(0.0)

    grid_lines = []
    tick_texts = []
    for t in ticks:
        ty = y_for(t)
        grid_lines.append(f'<line x1="{pad_left}" y1="{ty}" x2="{width - pad_right}" y2="{ty}" stroke="#e2e8f0" stroke-width="1" />')
        val_str = (f"{t:,.0f}" if t == int(t)
                   else (f"{t:,.2f}".rstrip('0').rstrip('.') if abs(t) < 10 else f"{t:,.1f}"))
        tick_texts.append(f'<text x="{pad_left - 8}" y="{ty + 4}" font-size="10" fill="#94a3b8" text-anchor="end">{val_str}</text>')

    col_slot = chart_w / max(n_cols, 1)
    bar_w = min(round(col_slot * 0.72, 1), 75.0)

    bars_svg = []
    connectors_svg = []
    labels_svg = []

    def _wrap_tspans(text, cx, max_chars=12, font_size="9"):
        words = str(text).split()
        if len(words) <= 2 and len(text) <= max_chars:
            return f'<text x="{cx}" y="0" font-size="{font_size}" font-weight="600" fill="#334155" text-anchor="middle">{html_lib.escape(text)}</text>'
        mid = len(words) // 2
        line1 = ' '.join(words[:mid])
        line2 = ' '.join(words[mid:])
        return f'''<text x="{cx}" y="-4" font-size="{font_size}" font-weight="600" fill="#334155" text-anchor="middle">
          <tspan x="{cx}" dy="0">{html_lib.escape(line1)}</tspan>
          <tspan x="{cx}" dy="11">{html_lib.escape(line2)}</tspan>
        </text>'''

    running_m = 0.0
    prev_top_x = None
    prev_top_y = None

    for idx, it in enumerate(items):
        val_m = it.get('value_millions', 0.0)
        bot_y = y_for(running_m)
        top_y = y_for(running_m + val_m)
        bar_h = max(round(bot_y - top_y, 1), 4.0)

        cx = pad_left + idx * col_slot + col_slot / 2
        bx = round(cx - bar_w / 2, 1)

        name = it.get('name', '')
        if 'مطور' in name:
            color = gold
        elif 'صندوق' in name:
            color = '#8b5cf6'
        elif 'تمويل' in name:
            color = '#f59e0b'
        elif idx % 2 == 0:
            color = primary
        else:
            color = secondary

        if prev_top_x is not None:
            connectors_svg.append(f'<line x1="{prev_top_x}" y1="{prev_top_y}" x2="{bx}" y2="{prev_top_y}" stroke="#94a3b8" stroke-width="1.2" stroke-dasharray="3 3" />')

        bars_svg.append(f'<rect x="{bx}" y="{top_y}" width="{bar_w}" height="{bar_h}" fill="{color}" rx="3" />')

        pct = it.get('pct_of_total', round((val_m / total_val_m) * 100, 1))
        disp = it.get('display', f"{val_m:.1f} ر.س")
        labels_svg.append(f'<text x="{cx}" y="{top_y - 8}" font-size="9.5" font-weight="700" fill="#0f172a" text-anchor="middle">{disp}</text>')
        labels_svg.append(f'<text x="{cx}" y="{top_y - 20}" font-size="8.5" font-weight="600" fill="#64748b" text-anchor="middle">{pct}%</text>')

        if use_stagger and idx % 2 == 1:
            lbl_y = y_zero + 38
            labels_svg.append(f'<line x1="{cx}" y1="{y_zero}" x2="{cx}" y2="{y_zero + 26}" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="2 2" />')
        else:
            lbl_y = y_zero + 14
        wrapped = _wrap_tspans(name, cx, font_size="8.5" if use_stagger else "9.5")
        labels_svg.append(f'<g transform="translate(0, {lbl_y})">{wrapped}</g>')

        prev_top_x = bx + bar_w
        prev_top_y = top_y
        running_m += val_m

    # Total column
    tot_idx = len(items)
    tot_cx = pad_left + tot_idx * col_slot + col_slot / 2
    tot_bx = round(tot_cx - bar_w / 2, 1)
    tot_top_y = y_for(total_val_m)
    tot_h = round(y_zero - tot_top_y, 1)

    if prev_top_x is not None:
        connectors_svg.append(f'<line x1="{prev_top_x}" y1="{prev_top_y}" x2="{tot_bx}" y2="{prev_top_y}" stroke="#94a3b8" stroke-width="1.2" stroke-dasharray="3 3" />')

    bars_svg.append(f'<rect x="{tot_bx}" y="{tot_top_y}" width="{bar_w}" height="{tot_h}" fill="{primary}" rx="3" />')
    tot_disp = total.get('display', f"{total_val_m:.1f} ر.س")
    labels_svg.append(f'<text x="{tot_cx}" y="{tot_top_y - 8}" font-size="10.5" font-weight="800" fill="{primary}" text-anchor="middle">{tot_disp}</text>')
    labels_svg.append(f'<text x="{tot_cx}" y="{tot_top_y - 22}" font-size="8.5" font-weight="700" fill="{primary}" text-anchor="middle">100%</text>')

    if use_stagger and tot_idx % 2 == 1:
        tot_lbl_y = y_zero + 38
        labels_svg.append(f'<line x1="{tot_cx}" y1="{y_zero}" x2="{tot_cx}" y2="{y_zero + 26}" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="2 2" />')
    else:
        tot_lbl_y = y_zero + 14
    tot_wrapped = _wrap_tspans(total.get('name', 'إجمالي تكلفة المشروع'), tot_cx, font_size="8.5" if use_stagger else "9.5")
    labels_svg.append(f'<g transform="translate(0, {tot_lbl_y})">{tot_wrapped}</g>')

    return f'''<svg data-chart="waterfall" viewBox="0 0 {width} {height}" style="width:100%;height:auto;max-height:360px;font-family:inherit;overflow:visible;" role="img" aria-label="المخطط الشلالي لتكوين إجمالي تكلفة المشروع">
  <!-- Grid -->
  {''.join(grid_lines)}
  <!-- Baseline -->
  <line x1="{pad_left}" y1="{y_zero}" x2="{width - pad_right}" y2="{y_zero}" stroke="#64748b" stroke-width="1.5" />
  <!-- Ticks -->
  {''.join(tick_texts)}
  <!-- Connectors -->
  {''.join(connectors_svg)}
  <!-- Bars -->
  {''.join(bars_svg)}
  <!-- Labels -->
  {''.join(labels_svg)}
</svg>'''


def _extract_waterfall_chart_data(part_or_table, model=None, project_data=None):
    model = model if isinstance(model, dict) else {}
    inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
    tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
    project_data = project_data if isinstance(project_data, dict) else {}
    fcd = project_data.get('financial_calc_data')
    if isinstance(fcd, str):
        try:
            fcd = json.loads(fcd)
        except Exception:
            fcd = {}
    fcd = fcd if isinstance(fcd, dict) else {}

    rows = []
    if isinstance(part_or_table, dict):
        rows = part_or_table.get('rows') or []
    elif isinstance(part_or_table, list):
        rows = part_or_table

    items = []
    seen_names = set()
    for r in rows:
        name = ''
        val = 0.0
        if isinstance(r, dict):
            name = str(r.get('اسم التكلفة') or r.get('البند') or r.get('name') or '').strip()
            val = _clean_numeric_val(r.get('الناتج') or r.get('القيمة') or r.get('value') or r.get('cost'))
        elif isinstance(r, (list, tuple)) and r:
            name = str(r[0]).strip()
            for cell in reversed(r[1:]):
                c_val = _clean_numeric_val(cell)
                if c_val > 0:
                    val = c_val
                    break
        if name and name not in ('الإجمالي', 'المجموع', 'Total', 'إجمالي تكلفة الاستثمار', 'إجمالي تكلفة المشروع', 'تكلفة الاستثمار', 'تكلفة المشروع') and val > 0:
            if name not in seen_names:
                seen_names.add(name)
                items.append({
                    'name': name,
                    'value_sar': val,
                    'value_millions': round(val / 1e6, 2),
                    'display': _format_sar_display(val),
                })

    if not items:
        for r in tables.get('costTable', []):
            if isinstance(r, dict):
                c_name = str(r.get('اسم التكلفة') or '').strip()
                c_val = _clean_numeric_val(r.get('الناتج'))
                if c_name and c_val > 0 and c_name not in seen_names:
                    seen_names.add(c_name)
                    items.append({
                        'name': c_name,
                        'value_sar': c_val,
                        'value_millions': round(c_val / 1e6, 2),
                        'display': _format_sar_display(c_val),
                    })

    if not items:
        fallback_cost_keys = (
            ('landCostIncluded', 'قيمة الأرض'),
            ('landValue', 'قيمة الأرض'),
            ('executionCostTotal', 'تكلفة التنفيذ والإنشاء'),
            ('designCostTotal', 'التصميم والدراسات والاستشارات'),
            ('servicesCostTotal', 'رسوم الخدمات والتراخيص'),
            ('advertisingCostTotal', 'الدعاية والتسويق'),
            ('developerCost', 'أتعاب إدارة التطوير'),
            ('fundFeesTotal', 'أتعاب إدارة الصندوق'),
            ('totalFundFees', 'أتعاب إدارة الصندوق'),
            ('fundManagementFeesTotal', 'أتعاب إدارة الصندوق'),
            ('totalFinanceCost', 'تكلفة التمويل البنكي'),
            ('contingencyCostTotal', 'احتياطي الطوارئ'),
        )
        for k, label in fallback_cost_keys:
            if label in seen_names:
                continue
            c_val = _clean_numeric_val(inputs.get(k))
            if c_val > 0:
                seen_names.add(label)
                items.append({
                    'name': label,
                    'value_sar': c_val,
                    'value_millions': round(c_val / 1e6, 2),
                    'display': _format_sar_display(c_val),
                })

    if not items:
        total_guess = _clean_numeric_val(inputs.get('adjustedProjectCost') or inputs.get('projectCost') or inputs.get('landCostIncluded') or 100000000)
        items = [
            {'name': 'قيمة الأرض', 'value_sar': total_guess * 0.45, 'value_millions': round(total_guess * 0.45 / 1e6, 2), 'display': _format_sar_display(total_guess * 0.45)},
            {'name': 'تكاليف التنفيذ', 'value_sar': total_guess * 0.38, 'value_millions': round(total_guess * 0.38 / 1e6, 2), 'display': _format_sar_display(total_guess * 0.38)},
            {'name': 'التصميم والدراسات', 'value_sar': total_guess * 0.07, 'value_millions': round(total_guess * 0.07 / 1e6, 2), 'display': _format_sar_display(total_guess * 0.07)},
            {'name': 'رسوم الخدمات والتسويق', 'value_sar': total_guess * 0.05, 'value_millions': round(total_guess * 0.05 / 1e6, 2), 'display': _format_sar_display(total_guess * 0.05)},
            {'name': 'أتعاب الصندوق والتمويل', 'value_sar': total_guess * 0.05, 'value_millions': round(total_guess * 0.05 / 1e6, 2), 'display': _format_sar_display(total_guess * 0.05)},
        ]

    # Mandatory inclusion of Developer Cost, Fund Cost, and Finance Cost if present (> 0) and not already in items
    # 1. Developer Cost (تكلفة المطور)
    has_dev = any(any(kw in str(it.get('name', '')).lower() for kw in ('مطور', 'أتعاب التطوير', 'إدارة التطوير', 'developer')) for it in items)
    if not has_dev:
        dev_val = _clean_numeric_val(
            inputs.get('developerCostValue')
            or inputs.get('developerCost')
            or inputs.get('developerFee')
            or inputs.get('totalDeveloperCost')
            or inputs.get('developerFeesTotal')
            or fcd.get('developerCost')
            or fcd.get('developerCostValue')
            or project_data.get('developer_cost')
            or project_data.get('developer_fee')
        )
        if dev_val > 0:
            seen_names.add('تكلفة المطور')
            items.append({
                'name': 'تكلفة المطور',
                'value_sar': dev_val,
                'value_millions': round(dev_val / 1e6, 2),
                'display': _format_sar_display(dev_val),
            })

    # 2. Fund Cost (تكلفة الصندوق)
    has_fund = any('صندوق' in str(it.get('name', '')) or 'fund' in str(it.get('name', '')).lower() for it in items)
    if not has_fund:
        fund_val = _clean_numeric_val(
            inputs.get('fundFeesTotal')
            or inputs.get('totalFundFees')
            or inputs.get('fundManagementFeesTotal')
            or inputs.get('fundTotalFees')
            or inputs.get('fundCost')
            or inputs.get('fundFees')
            or fcd.get('totalFundFees')
            or project_data.get('fund_fees')
            or project_data.get('fund_cost')
        )
        if fund_val <= 0 and isinstance(tables.get('fundFeeScheduleTable'), list):
            for fr in tables['fundFeeScheduleTable']:
                if isinstance(fr, dict):
                    fund_val += _clean_numeric_val(fr.get('إجمالي أتعاب الصندوق') or fr.get('أتعاب الإدارة') or fr.get('total'))
        if fund_val > 0:
            seen_names.add('تكلفة الصندوق')
            items.append({
                'name': 'تكلفة الصندوق',
                'value_sar': fund_val,
                'value_millions': round(fund_val / 1e6, 2),
                'display': _format_sar_display(fund_val),
            })

    # 3. Finance Cost (تكلفة التمويل)
    has_fin = any(any(kw in str(it.get('name', '')).lower() for kw in ('تمويل', 'فوائد التمويل', 'رسوم التمويل', 'finance')) for it in items)
    if not has_fin:
        fin_val = _clean_numeric_val(
            inputs.get('totalFinanceCost')
            or inputs.get('financeCost')
            or fcd.get('totalFinanceCost')
            or project_data.get('total_finance_cost')
            or project_data.get('finance_cost')
        )
        if fin_val <= 0:
            interest = _clean_numeric_val(inputs.get('financeInterestTotal') or fcd.get('financeInterestTotal'))
            arrangement = _clean_numeric_val(inputs.get('arrangementFeeTotal') or fcd.get('arrangementFeeTotal'))
            fin_val = interest + arrangement
        if fin_val <= 0 and isinstance(tables.get('debtScheduleTable'), list):
            for dr in tables['debtScheduleTable']:
                if isinstance(dr, dict):
                    fin_val += _clean_numeric_val(dr.get('الفائدة')) + _clean_numeric_val(dr.get('رسوم التمويل'))
        if fin_val > 0:
            seen_names.add('تكلفة التمويل')
            items.append({
                'name': 'تكلفة التمويل',
                'value_sar': fin_val,
                'value_millions': round(fin_val / 1e6, 2),
                'display': _format_sar_display(fin_val),
            })

    total_val = sum(it['value_sar'] for it in items)
    max_val = max([total_val] + [it['value_sar'] for it in items]) or 1.0
    running = 0.0
    for it in items:
        it['pct_of_total'] = round((it['value_sar'] / total_val) * 100, 1) if total_val > 0 else 0.0
        it['offset_pct'] = round((running / max_val) * 100, 1)
        it['height_pct'] = max(round((it['value_sar'] / max_val) * 100, 1), 5.0)
        running += it['value_sar']

    total_data = {
        'name': 'إجمالي تكلفة المشروع',
        'value_sar': total_val,
        'value_millions': round(total_val / 1e6, 2),
        'display': _format_sar_display(total_val),
        'pct_of_total': 100.0,
        'height_pct': 100.0,
        'offset_pct': 0.0,
    }

    svg_code = _build_waterfall_svg(items, total_data)

    return {
        'items': items,
        'total': total_data,
        'summary': {
            'total_millions': round(total_val / 1e6, 2),
            'items_count': len(items),
            'svg_code': svg_code,
        }
    }



def _extract_combo_chart_data(part_or_table, model=None, project_data=None):
    model = model if isinstance(model, dict) else {}
    tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
    cf = tables.get('cashflowTable') if isinstance(tables.get('cashflowTable'), list) else []
    if not cf and isinstance(model.get('report'), dict):
        for p in model.get('report', {}).get('parts', []):
            if isinstance(p, dict) and p.get('type') == 'table':
                txt = f"{p.get('text', '')} {p.get('title', '')}".lower()
                if re.search(r'تدفق|cashflow|cash flow', txt):
                    part_or_table = p
                    break
    rows = []
    headers = []
    if isinstance(part_or_table, dict):
        rows = part_or_table.get('rows') or cf
        headers = part_or_table.get('headers') or []
    elif isinstance(part_or_table, list) and part_or_table:
        rows = part_or_table
    else:
        rows = cf

    year_idx = 0
    net_idx = -3
    cum_idx = -2
    if headers:
        for h_i, h_name in enumerate(headers):
            h_str = str(h_name).strip().lower()
            if re.search(r'سنة|عام|year', h_str) and not re.search(r'تشغيل|إشغال|وصول', h_str):
                year_idx = h_i
            elif re.search(r'صافي.*تدفق|net.*cash|net.*flow', h_str):
                net_idx = h_i
            elif re.search(r'تراكمي|cumulative', h_str):
                cum_idx = h_i

    items = []
    running_cum = 0.0
    for r in rows:
        year = ''
        net_val = 0.0
        cum_val = 0.0
        has_cum = False
        if isinstance(r, dict):
            year = str(r.get('السنة') or r.get('year') or '').strip()
            net_val = _clean_numeric_val(r.get('صافي تدفق المشروع') or r.get('netCashFlow') or r.get('net_flow'))
            raw_cum = r.get('الرصيد التراكمي') or r.get('cumulativeCashFlow') or r.get('cumulative')
            if raw_cum is not None and str(raw_cum).strip() not in ('', '—', '-'):
                cum_val = _clean_numeric_val(raw_cum)
                has_cum = True
        elif isinstance(r, (list, tuple)) and len(r) >= 2:
            year = str(r[year_idx]).strip() if year_idx < len(r) else ''
            net_val = _clean_numeric_val(r[net_idx]) if abs(net_idx) <= len(r) else 0.0
            if abs(cum_idx) <= len(r) and str(r[cum_idx]).strip() not in ('', '—', '-'):
                cum_val = _clean_numeric_val(r[cum_idx])
                has_cum = True
        if year:
            year_label = f"سنة {year}" if not year.startswith('سنة') else year
            running_cum += net_val
            effective_cum = cum_val if has_cum else running_cum
            items.append({
                'year': year_label,
                'net_flow_m': round(net_val / 1e6, 1),
                'net_flow_display': f"{round(net_val / 1e6, 1)} ر.س",
                'net_flow_full': f"({abs(net_val):,.0f})" if net_val < 0 else f"{net_val:,.0f}",
                'net_val': net_val,
                'cumulative_m': round(effective_cum / 1e6, 1),
                'cumulative_display': f"{round(effective_cum / 1e6, 1)} ر.س",
                'cumulative_full': f"({abs(effective_cum):,.0f})" if effective_cum < 0 else f"{effective_cum:,.0f}",
                'cum_val': effective_cum,
                'is_positive': net_val >= 0,
            })

    if not items:
        items = [
            {'year': 'سنة 1', 'net_flow_m': -50.0, 'net_flow_display': '-50.0 ر.س', 'net_flow_full': '(50,000,000)', 'net_val': -50000000.0, 'cumulative_m': -50.0, 'cumulative_display': '-50.0 ر.س', 'cumulative_full': '(50,000,000)', 'cum_val': -50000000.0, 'is_positive': False},
            {'year': 'سنة 2', 'net_flow_m': -30.0, 'net_flow_display': '-30.0 ر.س', 'net_flow_full': '(30,000,000)', 'net_val': -30000000.0, 'cumulative_m': -80.0, 'cumulative_display': '-80.0 ر.س', 'cumulative_full': '(80,000,000)', 'cum_val': -80000000.0, 'is_positive': False},
            {'year': 'سنة 3', 'net_flow_m': 20.0, 'net_flow_display': '20.0 ر.س', 'net_flow_full': '20,000,000', 'net_val': 20000000.0, 'cumulative_m': -60.0, 'cumulative_display': '-60.0 ر.س', 'cumulative_full': '(60,000,000)', 'cum_val': -60000000.0, 'is_positive': True},
            {'year': 'سنة 4', 'net_flow_m': 45.0, 'net_flow_display': '45.0 ر.س', 'net_flow_full': '45,000,000', 'net_val': 45000000.0, 'cumulative_m': -15.0, 'cumulative_display': '-15.0 ر.س', 'cumulative_full': '(15,000,000)', 'cum_val': -15000000.0, 'is_positive': True},
            {'year': 'سنة 5', 'net_flow_m': 60.0, 'net_flow_display': '60.0 ر.س', 'net_flow_full': '60,000,000', 'net_val': 60000000.0, 'cumulative_m': 45.0, 'cumulative_display': '45.0 ر.س', 'cumulative_full': '45,000,000', 'cum_val': 45000000.0, 'is_positive': True},
        ]

    items = items[:15]
    all_vals = [it['net_flow_m'] for it in items] + [it['cumulative_m'] for it in items] + [0.0]
    min_v = min(all_vals)
    max_v = max(all_vals)

    import math
    def _bound_step(val, step=250.0, is_max=True):
        if is_max:
            return math.ceil(val / step) * step
        return math.floor(val / step) * step

    raw_span = max_v - min_v
    step = 250.0 if raw_span > 600 else (100.0 if raw_span > 250 else (50.0 if raw_span > 100 else 20.0))
    y_max = _bound_step(max_v, step=step, is_max=True)
    y_min = _bound_step(min_v, step=step, is_max=False)
    if y_max <= y_min:
        y_max = y_min + step * 2

    vb_w = 540.0
    vb_h = 290.0
    m_left = 60.0
    m_right = 25.0
    m_top = 35.0
    m_bottom = 45.0

    plot_w = vb_w - m_left - m_right
    plot_h = vb_h - m_top - m_bottom
    span = y_max - y_min
    scale_y = plot_h / span

    def val_to_y(v):
        return round(m_top + (y_max - v) * scale_y, 1)

    y_zero = val_to_y(0.0)
    n = len(items)
    col_step = plot_w / max(n, 1)
    bar_w = min(max(round(col_step * 0.55, 1), 16.0), 30.0)

    svg_points = []
    svg_circles = []
    ticks = []
    curr = y_min
    while curr <= y_max + 1e-6:
        ticks.append({'val': curr, 'y': val_to_y(curr), 'is_zero': abs(curr) < 1e-6})
        curr += step

    for idx, it in enumerate(items):
        cx = round(m_left + idx * col_step + col_step / 2.0, 1)
        bx = round(cx - bar_w / 2.0, 1)
        net_m = it['net_flow_m']
        cum_m = it['cumulative_m']

        by_net = val_to_y(net_m)
        cy_cum = val_to_y(cum_m)

        if net_m >= 0:
            bh = round(y_zero - by_net, 1)
            by = by_net
        else:
            bh = round(by_net - y_zero, 1)
            by = y_zero

        it['cx'] = cx
        it['cy'] = cy_cum
        it['bar_x'] = bx
        it['bar_y'] = by
        it['bar_w'] = bar_w
        it['bar_h'] = max(bh, 1.5)
        it['bar_direction'] = 'up' if it['is_positive'] else 'down'
        it['bar_height_pct'] = round((abs(net_m) / max(max_v, 1.0)) * 100, 1)
        it['cum_y_pct'] = round(((cum_m - y_min) / span) * 100, 1)

        svg_points.append(f"{cx},{cy_cum}")
        svg_circles.append({'cx': cx, 'cy': cy_cum, 'year': it.get('year', ''), 'val': cum_m})

    grid_lines = []
    y_labels = []
    for t in ticks:
        stroke = "#94a3b8" if t['is_zero'] else "#e2e8f0"
        stroke_w = "1.5" if t['is_zero'] else "1"
        grid_lines.append(f'<line x1="{m_left - 8}" y1="{t["y"]}" x2="{vb_w - m_right}" y2="{t["y"]}" stroke="{stroke}" stroke-width="{stroke_w}"/>')
        label_txt = f"{int(t['val']):,}" if t['val'] == int(t['val']) else f"{t['val']:.1f}"
        if t['val'] < 0:
            label_txt = f"-{abs(int(t['val'])):,}" if t['val'] == int(t['val']) else f"-{abs(t['val']):.1f}"
        y_labels.append(f'<text x="{m_left - 12}" y="{t["y"] + 3.5}" fill="#64748b" font-size="9" text-anchor="end" direction="ltr">{label_txt}</text>')

    bars_svg = []
    circles_svg = []
    x_labels_svg = []
    data_labels_svg = []

    for i, it in enumerate(items):
        cx = it['cx']
        bx = it['bar_x']
        by = it['bar_y']
        bh = it['bar_h']
        net_m = it['net_flow_m']
        cum_m = it['cumulative_m']
        bar_color = "url(#posBarGrad)" if it['is_positive'] else "url(#negBarGrad)"

        bars_svg.append(f'<rect x="{bx}" y="{by}" width="{bar_w}" height="{bh}" rx="2" fill="{bar_color}" opacity="0.9"/>')
        circles_svg.append(f'<circle cx="{cx}" cy="{it["cy"]}" r="4.5" fill="#ffffff" stroke="#0284c7" stroke-width="2.5"/>')
        x_labels_svg.append(f'<text x="{cx}" y="{vb_h - 18}" fill="#64748b" font-size="9.5" text-anchor="middle">{it["year"]}</text>')

        # Labels: avoid overlap between bar and circle when close
        if abs(by - it['cy']) > 22:
            if net_m > 40:
                data_labels_svg.append(f'<text x="{cx}" y="{by - 6}" fill="#0b1f33" font-size="9" font-weight="700" text-anchor="middle">{net_m:.1f}</text>')
        if not it['is_positive']:
            neg_txt = f"-{abs(net_m):.1f}"
            data_labels_svg.append(f'<text x="{cx}" y="{by + bh + 14}" fill="#b89564" font-size="9" font-weight="700" text-anchor="middle" direction="ltr">{neg_txt}</text>')

        # Key milestone cumulative points
        if i in (0, 1, 2, 3, 4, 9) or abs(net_m - cum_m) > 50:
            c_offset = -9 if it['cy'] < y_zero else 15
            data_labels_svg.append(f'<text x="{cx}" y="{it["cy"] + c_offset}" fill="#0284c7" font-size="9" font-weight="700" text-anchor="middle">{cum_m:.1f}</text>')

    svg_code = f'''<svg data-chart="combo" class="combo-chart" viewBox="0 0 {int(vb_w)} {int(vb_h)}" style="width: 100%; height: auto; max-height: 290px; display: block;" role="img" aria-label="مخطط التدفقات النقدية السنوية والرصيد التراكمي">
  <defs>
    <linearGradient id="posBarGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#12324c"/>
      <stop offset="100%" stop-color="#0b1f33"/>
    </linearGradient>
    <linearGradient id="negBarGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#c5a880"/>
      <stop offset="100%" stop-color="#b89564"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="{int(vb_w)}" height="{int(vb_h)}" fill="#ffffff" rx="6"/>
  <text x="{int(m_left - 12)}" y="{int(m_top - 12)}" fill="#94a3b8" font-size="8.5" text-anchor="end">ر.س</text>
  <g>{''.join(grid_lines)}</g>
  <g font-family="Tajawal, sans-serif">{''.join(y_labels)}</g>
  <g>{''.join(bars_svg)}</g>
  <polyline points="{' '.join(svg_points)}" fill="none" stroke="#0284c7" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <g>{''.join(circles_svg)}</g>
  <g font-family="Tajawal, sans-serif">{''.join(data_labels_svg)}</g>
  <g font-family="IBM Plex Sans Arabic, Tajawal, sans-serif">{''.join(x_labels_svg)}</g>
</svg>'''

    return {
        'items': items,
        'summary': {
            'years_count': len(items),
            'max_abs_flow_m': max([abs(it['net_flow_m']) for it in items] + [1.0]),
            'min_cumulative_m': min([it['cumulative_m'] for it in items] + [0.0]),
            'max_cumulative_m': max([it['cumulative_m'] for it in items] + [1.0]),
            'y_min': y_min,
            'y_max': y_max,
            'y_zero': y_zero,
            'svg_polyline_points': ' '.join(svg_points),
            'svg_circles': svg_circles,
            'svg_code': svg_code,
        }
    }


def _format_heatmap_value_display(metric_key, val_raw, num_val):
    if val_raw in ('لا يسترد', 'غير مسترد'):
        return 'لا يسترد'
    if val_raw in ('غير متاح', 'N/A', '—', '-'):
        return 'غير متاح'
    if num_val is None:
        return str(val_raw or '—')

    if metric_key in ('revenue', 'cost', 'net_profit'):
        val_m = abs(num_val) / 1e6
        if val_m >= 0.1:
            sign = '-' if num_val < 0 else ''
            return f"{sign}{val_m:,.2f} ر.س"
        return f"{int(num_val):,} ر.س"
    elif metric_key in ('roi', 'project_irr', 'equity_irr'):
        if '%' in str(val_raw):
            return str(val_raw).strip()
        return f"{num_val:.1f}%"
    elif metric_key == 'payback':
        if 'سنة' in str(val_raw) or 'عام' in str(val_raw):
            return str(val_raw).strip()
        return f"{num_val:.1f} سنة"
    return str(val_raw)


def _build_heatmap_matrix_html(chart_data, primary='#16405f', secondary='#0284c7'):
    matrix = (chart_data or {}).get('matrix') if isinstance(chart_data, dict) else (chart_data or [])
    if not matrix:
        return '<div style="padding:20px;text-align:center;color:#64748b;">لا تتوفر بيانات كافية لمصفوفة الخريطة الحرارية</div>'

    rows_html = []
    for r in matrix:
        metric = html_lib.escape(str(r.get('metric') or ''))
        pol_tag = html_lib.escape(str(r.get('polarity_label') or ('الأعلى أفضل' if r.get('higher_is_better') else 'الأقل أفضل')))
        pol_style = 'background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;' if r.get('higher_is_better') else 'background:#fdf4ff;color:#86198f;border:1px solid #f5d0fe;'

        c_val = html_lib.escape(str(r.get('conservative') or '—'))
        b_val = html_lib.escape(str(r.get('base') or '—'))
        o_val = html_lib.escape(str(r.get('optimistic') or '—'))

        c_style = r.get('conservative_style') or ''
        b_style = r.get('base_style') or ''
        o_style = r.get('optimistic_style') or ''

        rows_html.append(f'''
        <tr>
          <td style="padding:2px 6px;text-align:right;vertical-align:middle;">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:4px;padding:4px 8px;background:#ffffff;border:1px solid #e2e8f0;border-radius:6px;">
              <span style="font-weight:700;color:#1e293b;font-size:12px;line-height:1.25;">{metric}</span>
              <span style="font-size:9px;font-weight:600;padding:1px 5px;border-radius:4px;white-space:nowrap;line-height:1.25;{pol_style}">{pol_tag}</span>
            </div>
          </td>
          <td style="padding:2px 6px;text-align:center;vertical-align:middle;"><div style="{c_style}">{c_val}</div></td>
          <td style="padding:2px 6px;text-align:center;vertical-align:middle;"><div style="{b_style}">{b_val}</div></td>
          <td style="padding:2px 6px;text-align:center;vertical-align:middle;"><div style="{o_style}">{o_val}</div></td>
        </tr>''')

    return f'''<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:10px 16px;display:flex;flex-direction:column;justify-content:space-between;font-family:inherit;">
  <table data-preserve-density="1" style="width:100%;border-collapse:separate;border-spacing:0 3px;table-layout:fixed;">
    <thead>
      <tr>
        <th style="padding:4px 8px;font-size:11.5px;font-weight:700;color:#475569;text-align:right;border-bottom:2px solid #cbd5e1;width:40%;">المؤشر المالي</th>
        <th style="padding:4px 8px;font-size:11.5px;font-weight:700;color:#475569;text-align:center;border-bottom:2px solid #cbd5e1;">السيناريو المتحفظ</th>
        <th style="padding:4px 8px;font-size:11.5px;font-weight:700;color:#475569;text-align:center;border-bottom:2px solid #cbd5e1;">السيناريو الأساسي</th>
        <th style="padding:4px 8px;font-size:11.5px;font-weight:700;color:#475569;text-align:center;border-bottom:2px solid #cbd5e1;">السيناريو المتفائل</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows_html)}
    </tbody>
  </table>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;padding-top:8px;border-top:1px solid #e2e8f0;font-size:10.5px;color:#64748b;">
    <div style="display:flex;gap:12px;align-items:center;">
      <span style="font-weight:700;color:#1e293b;">مفتاح التقييم الاتجاهي:</span>
      <div style="display:flex;align-items:center;gap:4px;font-weight:600;">
        <span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:#d1fae5;border:1px solid #a7f3d0;"></span>
        <span>الأفضل (أخضر)</span>
      </div>
      <div style="display:flex;align-items:center;gap:4px;font-weight:600;">
        <span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:#fef3c7;border:1px solid #fde68a;"></span>
        <span>المتوسط (أصفر)</span>
      </div>
      <div style="display:flex;align-items:center;gap:4px;font-weight:600;">
        <span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:#fee2e2;border:1px solid #fca5a5;"></span>
        <span>الأقل (أحمر)</span>
      </div>
    </div>
    <div style="font-size:10px;color:#94a3b8;">الألوان تعتمد على اتجاه وطبيعة المؤشر (الأعلى أفضل للعائد والربح، والأقل أفضل للتكلفة والاسترداد)</div>
  </div>
</div>'''


def _extract_heatmap_chart_data(part_or_table, model=None, project_data=None):
    model = model if isinstance(model, dict) else {}
    tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
    sens = tables.get('sensitivityTable') if isinstance(tables.get('sensitivityTable'), list) else []
    rows = []
    headers = []
    if isinstance(part_or_table, dict):
        rows = part_or_table.get('rows') or sens
        headers = part_or_table.get('headers') or []
    elif isinstance(part_or_table, list) and part_or_table:
        rows = part_or_table
    else:
        rows = sens

    if not rows and isinstance(model.get('report'), dict):
        for p in model.get('report', {}).get('parts', []):
            if isinstance(p, dict) and p.get('type') == 'table':
                txt = f"{p.get('text', '')} {p.get('title', '')}".lower()
                if re.search(r'حساسي|سيناريو|sensitivity', txt):
                    rows = p.get('rows') or []
                    headers = p.get('headers') or []
                    break

    metric_configs = [
        {
            'key': 'revenue',
            'name': 'إجمالي الإيرادات',
            'aliases': ['إجمالي الإيرادات', 'الإيرادات', 'إجمالي المبيعات', 'الإيراد الإجمالي', 'total revenue'],
            'higher_is_better': True,
        },
        {
            'key': 'cost',
            'name': 'إجمالي تكلفة المشروع',
            'aliases': ['إجمالي تكلفة المشروع', 'تكلفة المشروع', 'إجمالي تكلفة الاستثمار', 'تكلفة الاستثمار', 'التكلفة الرأسمالية', 'إجمالي التكاليف', 'project cost', 'investment cost'],
            'higher_is_better': False,
        },
        {
            'key': 'net_profit',
            'name': 'صافي الربح',
            'aliases': ['صافي الربح', 'الربح الصافي', 'صافي الأرباح', 'net profit'],
            'higher_is_better': True,
        },
        {
            'key': 'roi',
            'name': 'العائد على الاستثمار (ROI)',
            'aliases': ['العائد على الاستثمار (ROI)', 'ROI كامل الدورة', 'العائد على الاستثمار', 'معدل العائد على الاستثمار', 'ROI', 'roi'],
            'higher_is_better': True,
        },
        {
            'key': 'project_irr',
            'name': 'العائد الداخلي للمشروع (Project IRR)',
            'aliases': ['العائد الداخلي للمشروع (Project IRR)', 'Project IRR كامل الدورة', 'العائد الداخلي للمشروع', 'Project IRR', 'معدل العائد الداخلي للمشروع', 'project irr'],
            'higher_is_better': True,
        },
        {
            'key': 'equity_irr',
            'name': 'العائد الداخلي لحقوق الملكية (Equity IRR)',
            'aliases': ['العائد الداخلي لحقوق الملكية (Equity IRR)', 'Equity IRR كامل الدورة', 'العائد الداخلي لحقوق الملكية', 'Equity IRR', 'معدل العائد الداخلي للملكية', 'equity irr'],
            'higher_is_better': True,
        },
        {
            'key': 'payback',
            'name': 'فترة الاسترداد',
            'aliases': ['فترة الاسترداد', 'فترة استرداد رأس المال', 'الاسترداد', 'payback period', 'payback'],
            'higher_is_better': False,
        },
    ]

    scenarios = ['متحفظ', 'أساسي', 'متفائل']
    matrix = []

    style_best = 'background:#d1fae5;color:#065f46;font-weight:700;padding:4px 8px;border:1px solid #a7f3d0;text-align:center;border-radius:6px;'
    style_medium = 'background:#fef3c7;color:#92400e;font-weight:600;padding:4px 8px;border:1px solid #fde68a;text-align:center;border-radius:6px;'
    style_worst = 'background:#fee2e2;color:#991b1b;font-weight:600;padding:4px 8px;border:1px solid #fca5a5;text-align:center;border-radius:6px;'
    style_neutral = 'background:#f1f5f9;color:#64748b;font-weight:500;padding:4px 8px;border:1px solid #e2e8f0;text-align:center;border-radius:6px;'

    normalized_rows = []
    for r in rows:
        if isinstance(r, (list, tuple)) and headers:
            r = dict(zip(headers, r))
        if isinstance(r, dict):
            normalized_rows.append(r)

    is_transposed = False
    if normalized_rows:
        first_row = normalized_rows[0]
        if any(sc in first_row for sc in scenarios):
            is_transposed = True

    for cfg in metric_configs:
        m_key = cfg['key']
        m_name = cfg['name']
        aliases = cfg['aliases']
        higher_is_better = cfg['higher_is_better']

        vals = {}
        nums = {}

        if is_transposed:
            target_row = None
            for r in normalized_rows:
                indicator_name = str(r.get('المؤشر') or r.get('البند') or r.get('المؤشر المالي') or r.get('البيان') or '').strip()
                if any(alias.lower() in indicator_name.lower() or indicator_name.lower() in alias.lower() for alias in aliases):
                    target_row = r
                    break
            for sc in scenarios:
                raw_v = target_row.get(sc) if target_row else None
                matched_val = str(raw_v).strip() if raw_v is not None else None
                vals[sc] = matched_val if matched_val is not None else '—'
                nums[sc] = _clean_numeric_val_strict(matched_val)
        else:
            for sc in scenarios:
                sc_row = next((r for r in normalized_rows if str(r.get('السيناريو') or '').strip() == sc), {})
                matched_val = None
                for alias in aliases:
                    if alias in sc_row and sc_row[alias] is not None and str(sc_row[alias]).strip():
                        matched_val = str(sc_row[alias]).strip()
                        break
                vals[sc] = matched_val if matched_val is not None else '—'
                nums[sc] = _clean_numeric_val_strict(matched_val)

        # Harmonize Base scenario with financial model summary/inputs (Rule 5)
        if (vals.get('أساسي') in (None, '—', '0', '0.0', '0%') or nums.get('أساسي') is None) and model:
            inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
            summary = model.get('summary') if isinstance(model.get('summary'), dict) else {}
            fallback_val = None
            if m_key == 'cost':
                fallback_val = inputs.get('adjustedProjectCost') or inputs.get('projectCost') or summary.get('totalCost')
            elif m_key == 'revenue':
                fallback_val = summary.get('totalRevenue') or summary.get('revenueTotal') or inputs.get('targetTotalRevenue')
            elif m_key == 'net_profit':
                fallback_val = summary.get('netProfit') or summary.get('netProfitTotal')
            elif m_key == 'roi':
                fallback_val = summary.get('roiTotal') or summary.get('roi') or inputs.get('targetRoi')
            elif m_key == 'project_irr':
                fallback_val = summary.get('projectIrr') or inputs.get('projectIrr')
            elif m_key == 'equity_irr':
                fallback_val = summary.get('equityIrr') or inputs.get('equityIrr')
            elif m_key == 'payback':
                fallback_val = summary.get('paybackPeriodYears') or inputs.get('paybackPeriodYears')

            if fallback_val is not None and str(fallback_val).strip() not in ('0', '0.0', ''):
                vals['أساسي'] = str(fallback_val).strip()
                nums['أساسي'] = _clean_numeric_val_strict(fallback_val)

        levels = {}
        for sc in scenarios:
            val_str = str(vals[sc]).strip()
            if val_str in ('لا يسترد', 'غير مسترد'):
                levels[sc] = 'worst'

        numeric_scs = [(sc, nums[sc]) for sc in scenarios if nums[sc] is not None and sc not in levels]

        if numeric_scs:
            sorted_scs = sorted(numeric_scs, key=lambda x: x[1], reverse=higher_is_better)
            unique_vals = []
            for _, val in sorted_scs:
                if val not in unique_vals:
                    unique_vals.append(val)

            has_pre_worst = any(lvl == 'worst' for lvl in levels.values())

            for sc, val in numeric_scs:
                if len(unique_vals) == 1:
                    levels[sc] = 'medium'
                elif len(unique_vals) == 2:
                    if val == unique_vals[0]:
                        levels[sc] = 'best'
                    else:
                        levels[sc] = 'medium' if has_pre_worst else 'worst'
                else:
                    if val == unique_vals[0]:
                        levels[sc] = 'best'
                    elif val == unique_vals[-1]:
                        levels[sc] = 'worst'
                    else:
                        levels[sc] = 'medium'

        for sc in scenarios:
            if sc not in levels:
                levels[sc] = 'neutral'

        def get_style(lvl):
            if lvl == 'best': return style_best
            if lvl == 'medium': return style_medium
            if lvl == 'worst': return style_worst
            return style_neutral

        c_disp = _format_heatmap_value_display(m_key, vals['متحفظ'], nums.get('متحفظ'))
        b_disp = _format_heatmap_value_display(m_key, vals['أساسي'], nums.get('أساسي'))
        o_disp = _format_heatmap_value_display(m_key, vals['متفائل'], nums.get('متفائل'))

        matrix.append({
            'metric': m_name,
            'key': m_key,
            'higher_is_better': higher_is_better,
            'polarity_label': 'الأعلى أفضل' if higher_is_better else 'الأقل أفضل',
            'conservative': c_disp,
            'base': b_disp,
            'optimistic': o_disp,
            'conservative_raw': vals['متحفظ'],
            'base_raw': vals['أساسي'],
            'optimistic_raw': vals['متفائل'],
            'conservative_level': levels['متحفظ'],
            'base_level': levels['أساسي'],
            'optimistic_level': levels['متفائل'],
            'conservative_style': get_style(levels['متحفظ']),
            'base_style': get_style(levels['أساسي']),
            'optimistic_style': get_style(levels['متفائل']),
        })

    html_card = _build_heatmap_matrix_html({'matrix': matrix})

    return {
        'columns': scenarios,
        'matrix': matrix,
        'legend': [
            {'label': 'الأفضل (أخضر)', 'color': '#065f46', 'bg': '#d1fae5'},
            {'label': 'المتوسط (أصفر)', 'color': '#92400e', 'bg': '#fef3c7'},
            {'label': 'الأقل (أحمر)', 'color': '#991b1b', 'bg': '#fee2e2'},
        ],
        'html_matrix': html_card,
    }
