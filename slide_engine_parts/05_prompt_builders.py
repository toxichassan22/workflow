

def build_slide_user_msg(slide, slide_num, total_slides, branding, project_data=None, offer_lang=None):
    """Build the user message for generating a single slide."""
    lang = resolve_offer_lang(project_data, offer_lang)
    title = slide.get('title', (f'Slide {slide_num}' if lang == OFFER_LANG_ENGLISH else f'شريحة {slide_num}'))
    slide_type = slide.get('type', 'content')
    design_style = slide.get('design_style', 'cards')
    chart_type = str(slide.get('chart_type') or '').strip().lower()
    canonical_type = canonicalize_chart_type(chart_type)
    chart_type = canonical_type or chart_type
    bullets = slide.get('bullets', [])
    density = slide.get('content_density', 'medium')
    section_key = _slide_section_key(slide)
    free_market_slide = section_key == 'market' and canonical_type != 'horizontal_bar'
    if free_market_slide:
        # The source may be structured data, but that does not make a table the
        # requested visual treatment. Keep the plan's data contract while
        # telling SOL that this is an editorial composition brief.
        design_style = 'editorial'
    background = normalize_hex_color((branding or {}).get('background_color'), '#f8fafc')
    preferred_text = normalize_hex_color((branding or {}).get('text_color'), '#1e293b')
    readable_body = readable_text_color(preferred_text, background)
    readable_heading = readable_text_color((branding or {}).get('primary_color'), background, (readable_body,))

    bullets_text = '\n'.join(f'- {b}' for b in bullets) if bullets else (
        '(No fixed points — extract from the project data)'
        if lang == OFFER_LANG_ENGLISH else '(لا توجد نقاط محددة — استخرج من بيانات المشروع)')

    style_instructions = {
        'dashboard': 'لوحة مؤشرات مالية تعتمد جداول HTML نظامية كاملة للتكاليف والاستثمار ومؤشرات العائد مرصوصة رأسياً تحت بعضها بنفس تصميم ومساحات تقرير PDF مع منع الكروت العائمة والمربعات الإحصائية',
        'cards': 'بطاقتان أو ثلاث فقط لعناصر مستقلة عريضة وغنية؛ استخدم الفقرات النصية أو الجداول بدلاً من التقطيع المفرط إلى مربعات صغيرة',
        'timeline': 'مراحل زمنية واضحة ومسار تدفق زمني، واعرض الملاحظة فقط تحت المرحلة التي تحتوي ملاحظة فعلية',
        'table': 'جدول احترافي كامل مطابق لتصميم تقرير PDF المالي بحدود واضحة 1px solid ورؤوس مظللة بألوان الهوية وفواصل آلاف للأرقام ومنع تحويل الجدول إلى كروت عائمة',
        'chart': 'رسم بياني احترافي حصراً من الأنواع الأربعة المعتمدة (مقارنة المنافسين: horizontal_bar في دراسة السوق، تكوين إجمالي تكلفة الاستثمار: waterfall، التدفقات النقدية السنوية والتراكمية: combo، مقارنة السيناريوهات المالية: heatmap في المالية) بـ HTML و CSS النقي مع جدول الأرقام بجانبه وبألوان الهوية ومنع أي نوع آخر',
        'text': 'عنوان وفقرة غنية ووافية أو قائمة منظمة تشرح الفكرة بالكامل بلا اختصار مخل وبلا تجزئة لمربعات فارغة',
        'editorial': 'تكوين تحليلي تحريري راقٍ يبرز فكرة محورية ثم يوزع الأدلة حولها بهرمية بصرية متنوعة؛ لا تبدأ بجدول HTML خام',
        'image': 'استخدم جميع رموز الصور المحددة في الخطة بتوزيع متوازن واحد للمجموعة، وبحد أقصى ثلاث صور في الشريحة',
        'flow': 'مخطط تدفق بصري هندسي راقٍ (Flowchart / Visual Pipeline) يربط الكتل بمسارات تدفق واضحة وبألوان الهوية مع إبراز القيم والمراحل والمبالغ',
        'diagram': 'مخطط اتجاهي هندسي راقٍ (Directional Diagram) لأرض المشروع وحدودها الأربعة والواجهات والشوارع المحيطة والإطلالة وفق الهيكل المعتمد',
        'swot': 'مصفوفة SWOT واضحة من أربعة محاور بألوان الهوية وحدها',
        'risk': 'سجل مخاطر منظم يضع كل خطر مقابل طريقة معالجته في صف واضح دون تكرار SWOT أو اختراع تقييمات',
        'map': 'خريطة كاملة بلا قص باستخدام contain ومضبوطة في المنتصف تماماً (center center) مع جدول أو ملخص واحد دون إعادة الأرقام في أكثر من شكل',
        'grid': 'استخدم جميع رموز الصور المحددة في الخطة بتوزيع متوازن من صورة إلى ثلاث صور',
        'minimal': 'خاتمة بسيطة تتضمن بيانات التواصل المتاحة بلا تقييمات أو عبارات مشروطة',
    }.get(design_style, 'نص منظم يناسب طبيعة المحتوى')
    if section_key == 'market' and chart_type != 'horizontal_bar':
        style_instructions = (
            'هذا النمط يصف نوع المحتوى فقط وليس قالباً بصرياً ملزماً. ابتكر التكوين والهرمية والمساحات والتفاصيل البصرية الأنسب لهذه الشريحة '
            'بـ HTML وCSS راقٍ، مع الحفاظ على البيانات المعتمدة ومنع الخرائط والصور الفوتوغرافية والرسوم البيانية الإضافية.'
        )
    primary_color = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    secondary_color = normalize_hex_color((branding or {}).get('secondary_color'), '#0ea5e9')
    chart_instructions = {
        'horizontal_bar': (
            'مخطط الأعمدة الأفقية (Horizontal Bar Chart) لمقارنة المنافسين: '
            'قائمة أعمدة أفقية مرتبة تنازلياً حسب السعر (من الأعلى إلى الأقل) مستخرجة من بيانات المنافسين المرفقة. '
            'الهيكل الإلزامي الوحيد لهذه الشريحة: قسّمها إلى عمودين متجاورين متساويين، جدول المنافسين في العمود الأيمن والرسم البياني في العمود الأيسر (50% لكل منهما). '
            'استخدم direction: rtl مع grid-template-areas: "table chart" وgrid-template-columns: 1fr 1fr وgap: 24px داخل حاوية display: grid; height: 500px; align-items: start. '
            'لا تعكس ترتيب العمودين ولا تنقل الجدول إلى اليسار. '
            'في جانب الرسم (حاوية بخلفية #f8fafc وبودر 1px solid #e2e8f0 وبادينغ 16px وراديوس 8px): '
            'رص أشرطة المنافسين رأسياً (display: flex; flex-direction: column; gap: 12px;). '
            'لكل منافس صف أفقي يتضمن: اسم المنافس يميناً (font-size: 11px; font-weight: 600; min-width: 110px; color: #1e293b;)، '
            'مسار الشريط (flex: 1; background: #e2e8f0; height: 18px; border-radius: 4px; overflow: hidden; position: relative;) '
            f'وبداخله شريط العرض الفعلي بعرض bar_width_pct% بلون {secondary_color} (أو {primary_color} للمشروع)، '
            'وقيمة السعر والوحدة يساراً بخط عريض (font-size: 11px; font-weight: 700; width: 100px; text-align: left;). '
            f'يجب تمييز شريط مشروعنا بلون الهوية الرئيسي ({primary_color}) وبإطار بارز وبادينغ خاص لتمييزه فوراً عن المنافسين.'
        ),
        'waterfall': (
            'المخطط الشلالي (Waterfall Chart) لتكوين إجمالي تكلفة المشروع: '
            'يوضح مساهمة كل بند تكلفة من القائمة المرفقة (بما يشمل تكلفة المطور وتكاليف الصندوق والتمويل عند توفرها) وصولاً لعمود إجمالي تكلفة المشروع النهائي. '
            'الهيكل الإلزامي: قسّم الشريحة إلى عمودين متجاورين متساويين (50% لجدول التكاليف، 50% للمخطط الشلالي) '
            'داخل حاوية display: grid; grid-template-columns: 1fr 1fr; gap: 24px; height: 500px; align-items: start;. '
            'في جانب الرسم: حاوية رسم بخلفية #f8fafc وبودر 1px solid #e2e8f0 وبادينغ 16px وراديوس 8px بارتفاع كلي 380px، '
            'تتضمن بالأعلى عنوان المخطط، ثم يمكنك إدراج كود SVG الجاهز والمحسوب بدقة من summary.svg_code أو بنائه كأعمدة عائمة: '
            'لكل بند تكلفة من قائمة البيانات المرفقة (waterfall_chart_data.items): '
            'عمود رأسي عائم (flex: 1; height: 100%; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; position: relative;): '
            f'1. قيمة البند بالأعلى: (<span style="position: absolute; bottom: calc(offset_pct% + height_pct% + 4px); font-size: 10px; font-weight: 700; color: {primary_color}; white-space: nowrap;">display</span>). '
            f'2. الشريط العائم: (div style="position: absolute; bottom: offset_pct%; height: height_pct%; width: 75%; background: {secondary_color}; border-radius: 3px;"). '
            '3. اسم البند أسفل خط الأساس: (<span style="position: absolute; top: 100%; padding-top: 6px; font-size: 10px; font-weight: 600; color: #475569; text-align: center; line-height: 1.2; word-break: break-word;">name</span>). '
            'العمود الأخير هو عمود إجمالي تكلفة المشروع (waterfall_chart_data.total): '
            f'عمود كامل يستند إلى خط الأساس مباشرة (position: absolute; bottom: 0; height: height_pct%; width: 85%; background: {primary_color}; border-radius: 3px;) '
            f'مع قيمته الإجمالية بأعلاه وتسميته بالأسفل بلون عريض {primary_color}.'
        ),
        'combo': (
            'المخطط المركب: أعمدة وخط (Combo Chart) للتدفقات النقدية السنوية والتراكمية: '
            'أعمدة رأسية لصافي التدفق السنوي (Net Cash Flow) لكل سنة مع مسار ونقاط بارزة للرصيد التراكمي (Cumulative Balance). '
            'الهيكل الإلزامي: قسّم الشريحة إلى عمودين متجاورين متساويين (50% لجدول التدفقات، 50% للرسم البياني) '
            'داخل حاوية display: grid; grid-template-columns: 1fr 1fr; gap: 24px; height: 500px; align-items: start;. '
            'في جانب الرسم: حاوية رسم بخلفية #f8fafc وبودر 1px solid #e2e8f0 وبادينغ 16px وراديوس 8px بارتفاع كلي 380px، '
            'تتضمن بالأعلى عنوان المخطط ومفتاح الألوان (تدفق موجب #10b981، تدفق سالب #ef4444، الرصيد التراكمي خط الهوية). '
            'منطقة الرسم المشتركة بارتفاع 240px وبموقع نسبي (position: relative; height: 240px;): '
            '1. خط الصفر الأفقي يقطع المنتصف (position: absolute; top: 50%; left: 0; right: 0; border-top: 1px dashed #94a3b8; z-index: 1;). '
            '2. رص أعمدة السنوات (display: flex; height: 100%; position: relative; z-index: 2; gap: 4px;): '
            'لكل سنة من combo_chart_data.items، عمود نسبي (flex: 1; height: 100%; position: relative; display: flex; justify-content: center;): '
            'إذا كان التدفق موجباً: شريط للأعلى (position: absolute; bottom: 50%; height: bar_height_pct%; width: 60%; background: #10b981; border-radius: 2px;). '
            'إذا كان التدفق سالباً: شريط للأسفل (position: absolute; top: 50%; height: bar_height_pct%; width: 60%; background: #ef4444; border-radius: 2px;). '
            'وتسمية السنة بالأسفل (position: absolute; bottom: -22px; font-size: 9px; font-weight: 600; color: #64748b; white-space: nowrap;). '
            '3. طبقة مسار الرصيد التراكمي فوق الأعمدة (position: absolute; inset: 0; width: 100%; height: 100%; z-index: 3; pointer-events: none;): '
            f'عنصر svg كامل ومغلق بنطاق عرض viewBox="0 0 500 200" style="position: absolute; inset: 0; width: 100%; height: 100%; z-index: 3; pointer-events: none;" يحتوي بدقة على: '
            f'<polyline fill="none" stroke="{primary_color}" stroke-width="2.5" stroke-linejoin="round" points="انسخ قيمة summary.svg_polyline_points حرفياً" /> '
            f'ودوائر نقاط للسنوات بالإحداثيات المحسوبة لكل سنة: <circle cx="item.cx" cy="item.cy" r="3.5" fill="{primary_color}" stroke="#ffffff" stroke-width="1.5" />. تأكد من إغلاق وسم </svg> دائماً. '
            'ملاحظة هامة: في العمود الأول اعرض جدول التدفقات المعتمد (السنة، صافي التدفق السنوي، الرصيد التراكمي) من combo_chart_data.items، وفي العمود الثاني المخطط المركب، ولا تضف أي جداول أخرى خارج العمودين.'
        ),
        'heatmap': (
            'الخريطة الحرارية (Heatmap Matrix) لمقارنة السيناريوهات المالية: '
            'مصفوفة مقارنة بصرية للسيناريوهات الثلاثة (المتحفظ، الأساسي، المتفائل) لنتائج وحساسية الدراسة المالية. '
            'الهيكل الإلزامي: اعرض مصفوفة الخريطة الحرارية كاملة بعرض مريح يبرز المؤشرات المالية السبعة (الإيرادات، تكلفة المشروع، صافي الربح، ROI، Project IRR، Equity IRR، فترة الاسترداد). '
            'تلوين اتجاهي ذكي ثلاثي المستويات بحسب طبيعة المؤشر (Directional Polarity-Aware Coloring): '
            '1. الأعلى أفضل لمؤشرات الإيرادات وصافي الربح ومعدلات العائد (الأعلى = أخضر، المتوسط = أصفر، الأقل = أحمر). '
            '2. الأقل أفضل لمؤشرات التكلفة وفترة الاسترداد (الأقل = أخضر، المتوسط = أصفر، الأعلى = أحمر). '
            '3. استخدم الأنماط الجاهزة المرفقة (conservative_style, base_style, optimistic_style) أو قم بتضمين كود html_matrix الجاهز مباشرة. '
            '4. ضع مفتاح التقييم الاتجاهي أسفل المصفوفة (الأفضل أخضر، المتوسط أصفر، الأقل أحمر) بدون أي أيقونات أو إيموجي نهائياً.'
        ),
    }
    chart_note = chart_instructions.get(chart_type, '')

    density_instructions = {
        'low': 'محتوى خفيف — صورة كبيرة أو عنصران وافيان مع شرح تفصيلي',
        'medium': 'محتوى متوسط — نص غني أو جدول كامل ممتلئ بصرياً',
        'high': 'محتوى كثيف — جدول بيانات متكامل أو مخطط تدفق شامل بدون ازدحام',
    }.get(density, 'محتوى متوسط')
    if free_market_slide:
        density_instructions = (
            'محتوى تحليلي كثيف — وزّع جميع الحقائق داخل تكوين تحريري واضح من طبقتين أو ثلاث، '
            'مع نقطة ارتكاز بصرية ومساحات بيضاء وفواصل هادئة؛ لا تعرضه كسجل صفوف تقليدي.'
        )

    # Explicit image/map placeholder for this slide
    placeholder_note = ''
    image_tokens = [str(token) for token in (slide.get('image_tokens') or []) if str(token or '').strip()]
    if slide_type == 'cover':
        placeholder_note = 'يجب استخدام ##IMAGE_COVER## كخلفية كاملة على كامل الشريحة (Full Bleed Background)، ووضع طبقة فوقها تحمل data-cover-overlay. لون الطبقة سيُثبت من اللون الأساسي للهوية؛ ممنوع كحلي ثابت أو لون خارج الهوية. ممنوع منعاً باتاً وضع أي بطاقة صورة أو وسم <img> إضافي لصورة المشروع داخل الشريحة؛ الصورة كخلفية كاملة فقط.'
    elif slide_type == 'map_overview':
        placeholder_note = 'يجب استخدام ##MAP_OVERVIEW## كخلفية رئيسية لهذه الشريحة مع ضبط الصورة في المنتصف تماماً (center center) بدون أي إزاحة أو قطع.'
    elif slide_type == 'map_landmarks':
        placeholder_note = 'يجب استخدام ##MAP_LANDMARKS## كخلفية مع ضبطها في المنتصف (center center) مع جدول أوقات القيادة والمسافات من البيانات.'
    elif slide_type == 'map_access':
        placeholder_note = 'يجب استخدام ##MAP_ACCESS## لعرض خريطة الطرق والمداخل مع ضبط الصورة في المنتصف (center center).'
    elif slide_type == 'map_catchment':
        placeholder_note = 'يجب استخدام ##MAP_CATCHMENT## لعرض دوائر نطاق التأثير مع ضبط الصورة في المنتصف (center center).'
    elif slide_type == 'site_specs':
        placeholder_note = 'استخدم جدول بيانات احترافي لخصائص الموقع.'
    elif slide_type == 'moodboard':
        placeholder_note = 'استخدم كل رموز صور التصورات الخارجية المحددة للشريحة وفق التخطيط المعتمد، دون حذف أو تكرار.'
    elif image_tokens:
        placeholder_note = 'استخدم كل رموز الصور التالية مرة واحدة وبحجم واضح، ولا تستبدلها بصورة الغلاف: ' + '، '.join(image_tokens)
        if slide.get('image_layout'):
            placeholder_note += f". التخطيط المعتمد لهذه المجموعة هو {slide.get('image_layout')} ولا تغيّر عدد الصور"
        caps = slide.get('captions') or ([slide.get('description')] if slide.get('description') else [])
        if caps:
            caps_list = [str(c).strip() for c in caps if str(c).strip()]
            if caps_list:
                placeholder_note += f". ضع بطاقة شرح وتسمية توضيحية أسفل كل صورة نصها المعتمد: {' — '.join(caps_list)}"
    elif design_style == 'image':
        placeholder_note = 'لا تستخدم صورة ما لم يكن رمزها محددًا في خطة هذه الشريحة أو في الصور المتوفرة لموضوعها.'
    if section_key == 'market' and slide_type not in ('cover', 'index', 'closing', 'section_divider'):
        if canonicalize_chart_type((slide or {}).get('chart_type')) == 'horizontal_bar':
            if lang == OFFER_LANG_ENGLISH:
                placeholder_note = (
                    'This is the fixed-layout competitor-comparison slide: the competitors table on the LEFT and the chart on the RIGHT. '
                    'No maps, photos or photo backgrounds; place each competitor logo inside its row in the competitors table when available.'
                )
            else:
                placeholder_note = (
                    'هذه شريحة مقارنة المنافسين ذات التخطيط الثابت: جدول المنافسين في اليمين والرسم البياني في اليسار. '
                    'ممنوع استخدام الخرائط أو الصور أو خلفيات الصور؛ ضع شعار كل منافس داخل صفه في جدول المنافسين إذا كان الشعار متوفراً.'
                )
        else:
            placeholder_note = (
                'هذه شريحة من قسم دراسة السوق: ممنوع استخدام الخرائط أو الصور الفوتوغرافية أو خلفيات الصور. '
                'لـ SOL حرية كاملة في ابتكار التكوين البصري والهرمية والمساحات باستخدام HTML وCSS؛ لا تفرض جدولاً أو بطاقات أو شبكة بعينها، واختر الشكل الذي يخدم طبيعة المحتوى مع الحفاظ على كل البيانات المعتمدة.'
            )

    notes = [
        f'أنشئ فقط الشريحة {slide_num} لا غير',
        'اكتب HTML في div class="slide" واحد فقط',
        'لا تكتب شرح أو markdown أو كود إضافي',
        'استخدم خط الشركة نفسه في كل العناصر من دون font-family، بوزن 800 للعناوين الرئيسية والأرقام والمؤشرات الكبرى، و700 للعناوين الفرعية ورؤوس الجداول، و600 للتسميات، و400 للنصوص مع إبراز الكلمات المفتاحية بوزن 700',
        f'استخدم {readable_heading} للعناوين و{readable_body} للنص فوق الخلفية {background}. لا تستخدم أي لون نص قبل التحقق أن نسبة تباينه مع خلفيته 4.5:1 على الأقل، ولا تضع نصًا داكنًا فوق مساحة داكنة أو نصًا فاتحًا فوق مساحة فاتحة',
        'لا تختصر الكلام اختصاراً مخلاً ولا تقسم الشريحة إلى 4 أو 6 مربعات صغيرة فارغة؛ اعتمد على فقرات وافية وجداول متكاملة وتدفقات بصرية منظمة',
        'لا تكرر معلومة وردت في شريحة أخرى أو قسم آخر؛ تحليل SWOT يستخدم مصدر market_study_data.swot مرة واحدة فقط، والمكونات في قسم المكونات فقط',
        'ممنوع وضع شارات أو بطاقات مكررة مثل «* مشروع متعدد الاستخدامات *» أو شارات تصنيف عامة أعلى شرائح المحتوى العادية',
        'الرسوم البيانية محصورة حصراً في 4 أنواع معتمدة لـ 4 مواقع محددة (مقارنة المنافسين: horizontal_bar في السوق، وتكلفة الاستثمار: waterfall، والتدفقات النقدية: combo، ومقارنة السيناريوهات: heatmap في المالية) وأي رسم خارجها ممنوع منعاً باتاً؛ ولا تستخدم البطاقات إلا لعناصر مستقلة عريضة وبحد أقصى ثلاث',
        'الصور ليست عنصراً افتراضياً في كل شريحة: استخدم فقط الصور والخرائط والرموز التي تنص عليها الخطة لهذه الشريحة. لا تضف صورة إلى شريحة نص أو جدول بلا حاجة، ولا تكرر أصلاً مرئياً في موضع آخر، مع الحفاظ على توزيع معقول للصور المتاحة عبر العرض الكامل',
        'الخرائط مسموحة في شرائح تحليل الموقع الجغرافي أو تحليل الأرض عند طلبها صراحة، أو في ملخص الموقع/الخريطة التنفيذي المحدد صراحة. في الجدول الزمني والدراسة المالية والمخططات والتصورات الخارجية والداخلية وفريق العمل وبقية الأقسام: ممنوع استخدام ##MAP_OVERVIEW## أو ##MAP_LANDMARKS## أو ##MAP_ACCESS## أو ##MAP_CATCHMENT## أو أي صورة من /uploads/maps/',
        'التزم بأساسيات التوليد دون استثناء: ' + ('LTR' if lang == OFFER_LANG_ENGLISH else 'RTL') + '، هوية الشركة، الهيدر والفوتر النظاميان، جذر slide واحد، تباين واضح، تدفق طبيعي بلا تداخل أو قص، وعدم اختراع أرقام أو نصوص أو صور أو أيقونات',
        'سطح شرائح المحتوى والفهرس والتحليلات فاتح وموحد: استخدم background أبيض أو فاتح لجذر slide مع نص داكن مقروء، ولا تضع إطاراً داكناً حول صفحة بيضاء ولا تحول الشريحة إلى واجهة داكنة. الخلفية الداكنة الكاملة محجوزة للغلاف والخاتمة وفواصل الأقسام ذات الصورة، وخلفية كل شعار مستقلة حسب تباين الشعار ولا تتغير بتغيير سطح الشريحة',
        'في قسم دراسة السوق استخدم horizontal_bar واحداً فقط في مقارنة المنافسين. ' + (
            'ثبّت في هذه الشريحة الجدول يساراً والرسم يميناً، واترك لـ SOL حرية ابتكار التصميم البصري لبقية شرائح السوق من دون فرض جداول أو بطاقات أو شبكة محددة، ومن دون خرائط أو صور فوتوغرافية أو رسوم إضافية.'
            if lang == OFFER_LANG_ENGLISH else
            'ثبّت في هذه الشريحة الجدول يميناً والرسم يساراً، واترك لـ SOL حرية ابتكار التصميم البصري لبقية شرائح السوق من دون فرض جداول أو بطاقات أو شبكة محددة، ومن دون خرائط أو صور فوتوغرافية أو رسوم إضافية.'
        ) + ' انقل كل البيانات الواردة في نطاق الدراسة والمنافسين والملخص التنفيذي لسوق المشروع وملخص دراسة السوق والمصادر دون حذف أو إعادة صياغة للأرقام.',
        'لا تنشئ شريحة كاملة لإجابة قصيرة أو قيمة واحدة؛ ادمجها مع أقرب محتوى منطقي داخل المحور نفسه',
        'استخدم فواصل الآلاف بصريًا للمبالغ والمساحات والكميات دون تقريب، ولا تستخدمها للسنوات أو الهواتف أو الوثائق أو المعرفات أو الإحداثيات',
        'املأ الشريحة بالمحتوى الضروري والوافي؛ وشرائح الملخص المالي تستخدم جداول التقرير نفسها دون ضغط أو حذف',
        'جداول الدراسة المالية يجب أن تكون متناسقة ومضغوطة بأناقة (Compact & Fitted): ممنوع تمديد الجدول رأسياً بملء الشريحة (لا تضع height: 100% أو height: 480px على الجدول لتفادي الصفوف العملاقة والفراغات المفرطة)، واجعل ارتفاع الصفوف طبيعياً ومريحاً (padding: 7px 12px;). جداول العمودين (مثل البند والقيمة) توضع في بطاقة أنيقة بعرض متناسب مريح (max-width: 820px; margin: 0 auto;). في الشرائح المالية العادية غير الرسومية، عند وجود أكثر من جدول مالي رصها كلها رأسياً تحت بعضها، ولا تضع جدولين بجانب بعضهما؛ وإذا لم تتسع المساحة فانقل البقية إلى الشريحة التالية دون قص أو حذف.',
    ]
    company_tone = str((project_data or {}).get('_company_logo_tone') or (branding or {}).get('_logo_tone') or '').strip().lower()
    project_tone = str((project_data or {}).get('_project_logo_tone') or '').strip().lower()
    logo_dark_background = dark_surface_color(
        (branding or {}).get('primary_color'), (branding or {}).get('secondary_color'))
    if company_tone == 'light':
        notes.append(f'شعار الشركة فاتح: ضع ##LOGO## على خلفية {logo_dark_background} فقط، ولا تعكس القرار ولا تضعه على الأبيض')
    elif company_tone == 'dark':
        notes.append('شعار الشركة داكن: ضع ##LOGO## على خلفية #ffffff فقط، ولا تعكس القرار ولا تضعه على خلفية داكنة')
    if project_tone == 'light':
        notes.append(f'شعار المشروع فاتح: ضع ##PROJECT_LOGO## على خلفية {logo_dark_background} مستقلة عن شعار الشركة')
    elif project_tone == 'dark':
        notes.append('شعار المشروع داكن: ضع ##PROJECT_LOGO## على خلفية #ffffff مستقلة عن شعار الشركة')
    if placeholder_note:
        notes.insert(0, placeholder_note)
    source_note = _slide_source_data_note(slide, project_data, lang)
    if _is_visual_concept_media_slide(slide):
        notes.insert(0, 'هذه شريحة وسائط فقط: اعرض رموز الصور المحددة كما هي، بلا عنوان أو وصف أو نقاط أو جدول أو خريطة أو صورة إضافية. تُحافظ المنظومة على الهيدر والفوتر والهوية آليًا.')
    if source_note:
        notes.append(source_note)
    content_source = str(slide.get('content_source') or '')
    if content_source == 'site_analysis' and str((project_data or {}).get('site_analysis') or '').strip():
        notes.append(
            'هذه شريحة تحليل AI للموقع: انقل نص حقل تحليل AI للموقع المعتمد كاملاً كما هو، '
            'دون تلخيص أو إعادة صياغة أو استبدال فقراته بنص جديد. يجب أن يظهر النص نفسه مرئياً داخل الشريحة.'
        )
    if re.fullmatch(r'executive_content\.(?:summary|opportunity|features)(?::\d+:\d+)?', content_source):
        notes.append(
            'هذه شريحة من قسم المحتوى التنفيذي (نص فقط، بلا صور أو خرائط). الكانفس 1280×720 بكسل: '
            'المحتوى يبدأ تحت هيدر النظام (~68px) وينتهي قبل الفوتر (~40px)، أي مساحة صالحة ~600px بعرض كامل. '
            'لـ SOL حرية كاملة في ابتكار تكوين تحريري جذاب بصرياً — هرمية واضحة، مساحات بيضاء مدروسة، '
            'أرقام ومؤشرات مميزة باللون الذهبي، تقسيم النص على عمودين عند طوله. '
            'ممنوع حشر النص كله في بطاقة واحدة أو شبكة بطاقات متشابهة، وممنوع ترك مساحة كبيرة فارغة بجانب كتلة نصية ضيقة — '
            'وزّع المحتوى على عرض الشريحة كاملاً. '
            'سطر «المعتمد دون إضافة أو تكرار» تعليمة داخلية وليس جزءاً من المحتوى — لا تعرضه. '
            'النص المعتمد يظهر كاملاً حرفياً دون حذف أو اختصار.'
        )
    if content_source in ('site_analysis', 'executive_content.summary') and '##MAP_OVERVIEW##' in (slide.get('image_tokens') or []):
        marker_side = str((project_data or {}).get('_map_marker_side') or 'right')
        if marker_side == 'left':
            notes.append('ضع ##MAP_OVERVIEW## في عنصر يحمل data-map-summary-background، وعلامة الموقع في النصف الأيسر؛ ضع بطاقة الملخص كطبقة في اليمين تحمل data-map-summary-card ولا تغط العلامة.')
        else:
            notes.append('ضع ##MAP_OVERVIEW## في عنصر يحمل data-map-summary-background، وعلامة الموقع في النصف الأيمن؛ ضع بطاقة الملخص في اليسار تحمل data-map-summary-card ولا تغط العلامة.')
    if section_key == 'overview':
        notes.append('اعرض نبذة المشروع المعتمدة كنص واضح بلا أي رمز صورة؛ صور التصورات الخارجية مخصصة لقسمها فقط، وبلا تكرار مكونات المشروع التفصيلية.')
    if section_key in ('land', 'location', 'market'):
        notes.append('بعد الجداول أو البيانات، اكتب الملخص النهائي المحفوظ لهذا القسم مرة واحدة في نهاية الشريحة أو في آخر شريحة من القسم.')
    if section_key != 'financial' and len([t for t in (slide.get('table_group_titles') or []) if str(t or '').strip()]) > 1:
        group_titles = [str(t).strip() for t in slide.get('table_group_titles') or [] if str(t or '').strip()]
        notes.append(
            'هذه الشريحة تجمع جداول مترابطة من نفس القسم. اجعل الجداول ذات الترويسة والأعمدة المتطابقة جدولاً واحداً متصلاً، '
            'وارص أي جدول مختلف تحته بتباعد واضح، مع نقل جميع البيانات من العناوين التالية دون حذف: '
            + ' — '.join(group_titles)
        )
    if section_key == 'closing':
        if lang == OFFER_LANG_ENGLISH:
            notes.append('Use the hero image clearly as a full background or side image, and show the company and project logos at the same large size. Show only the entered contact fields as they are; if empty, show only a brief thanks and the project name with no invented data. Do not write investment verdicts.')
        else:
            notes.append('استخدم الصورة الرئيسية بوضوح كخلفية كاملة أو صورة جانبية، واعرض شعاري الشركة والمشروع بالحجم الكبير نفسه. اعرض حقول التواصل المدخلة فقط كما هي؛ وإذا كانت فارغة فاقتصر على شكر موجز واسم المشروع دون أي بيانات وهمية. ممنوع كتابة «فرصة واعدة بشروط» أو أي تقييم استثماري.')
    if design_style == 'diagram' or slide.get('content_source') == 'land_boundary_diagram' or re.search(r'(?:مخطط اتجاهي|حدود الأرض|اتجاهي|directional|plot boundary|boundary diagram)', title, re.IGNORECASE):
        if lang == OFFER_LANG_ENGLISH:
            notes.append(
                'For the directional plot-boundary slide: design a coherent, premium directional structure in pure HTML/CSS using brand colors only, no icons or emoji. '
                'Center a wide box representing "Project Land" with the four side lengths on its edges and the facade summary in its middle, '
                'surrounded by clear cards for the four directions (North, South, East, West) showing side lengths, neighbours, street widths and facades, highlighting streets in the accent color (e.g. gold), '
                'with a prominent card for any sea view or main road, '
                'writing "Dimensions in meters" in the top corner opposite the title, and an explanatory note at the bottom: "The reading shows boundary directions and street relations without simulating area proportions."'
            )
        else:
            notes.append(
                'في شريحة المخطط الاتجاهي لحدود الأرض: صمّم هيكلاً اتجاهياً متناسقاً وراقياً بـ HTML و CSS النقي بألوان الهوية فقط ودون أيقونات أو إيموجي. '
                'يتوسط الشريحة صندوق عريض يمثل «أرض المشروع» مع أطوال الأضلاع الأربعة على حوافه وملخص الواجهات في وسطه، '
                'وتحيط به بطاقات واضحة للاتجاهات الأربعة (شمال، جنوب، شرق، غرب) توضح أطوال الأضلاع والمجاورات وعروض الشوارع والواجهات مع تمييز الشوارع بلون التمييز (مثل الذهبي)، '
                'وبطاقة بارزة ومميزة لجهة الإطلالة البحرية أو الطريق الرئيسي إن وجدت، '
                'مع كتابة «الأبعاد بالمتر» في الزاوية العلوية المقابلة للعنوان، وملاحظة توضيحية أسفل الشريحة: «تمثل القراءة اتجاهات الحدود وعلاقتها بالشوارع دون محاكاة مساحية للنسب.»'
            )
    if design_style == 'timeline' or re.search(r'(?:خطة|زمن|جدول|مراحل|timeline|schedule|phases|plan|stages)', title, re.IGNORECASE):
        notes.append('اعرض مراحل الجدول الزمني كما وردت. أظهر الملاحظة بجانب مرحلتها فقط عندما يكون نصها موجودًا، ولا تنشئ حقل ملاحظات فارغًا لأي مرحلة.')
        timeline_note = _timeline_data_note(project_data)
        if timeline_note:
            notes.append(timeline_note.strip())
    if section_key == 'financial':
        notes.append('قالب تقرير الدراسة المالية ملزم: انقل جميع الجداول والمؤشرات المطلوبة بمسمياتها الأصلية وبالقيم والوحدات والترتيب نفسها، ولا تغيّر إلا ألوان الهوية والتنسيق المحدود.')
        notes.append('تصميم جداول تقرير PDF المالي هو التصميم الأساسي والإلزامي: انقل جميع الجداول والمؤشرات بمسمياتها الأصلية وبالقيم والترتيب نفسها، وطبّق ألوان الهوية فقط دون تغيير هيكل الجدول أو مساحاته.')
        notes.append('ممنوع منعاً باتاً: تحويل الجداول المالية إلى كروت عائمة (cards)، أو شبكة مربعات إحصائية (KPI boxes)، أو تصميم الشريحة على شكل 4 خانات عائمة أو شريحة بها خانة واحدة. يجب استخدام وسم <table> نظامي كامل بحدود واضحة 1px solid وخلفيات ترويسة هادئة.')
        notes.append('لجداول المؤشرات والملخصات (Key-Value): استخدم جدولاً بعمودين (<table class="summary-table">) بعرض 35%-40% لعمود اسم البند بخلفية هادئة بلون الهوية، وعمود القيمة بخط عريض bold وفواصل آلاف للأرقام. عند وجود أكثر من جدول مالي، رص الجداول كلها تحت بعضها رأسياً بترتيبها، ولا تستخدم display:grid أو grid-template-columns لوضع جدولين متجاورين.')
        stacked_sources = [s for s in (slide.get('content_sources') or []) if str(s or '').strip()]
        stacked_titles = [t for t in (slide.get('table_group_titles') or []) if str(t or '').strip()]
        if (len(stacked_sources) > 1 or len(stacked_titles) > 1) and not chart_type:
            notes.append('هذه الشريحة المالية العادية تضم عدة جداول: اعرض كل جدول مستقلاً، ورص جميع الجداول رأسياً تحت بعضها بتباعد 18px، مع عنوان صغير فوق كل جدول وبقاء كل صف وعمود كاملاً دون اختصار. لا تضع أي جدول بجانب جدول آخر، وإذا لم تتسع المساحة فانقل بقية الجداول إلى الشريحة التالية دون قص أو حذف.')
            if stacked_titles:
                notes.append('عناوين جداول هذه المجموعة كما وردت في الخطة: ' + ' — '.join(stacked_titles))
        notes.append('نسّق الأعداد بفواصل الآلاف للعرض فقط، من دون تقريب أو تحويل إلى ألف أو مليون أو تغيير عدد الخانات العشرية.')
        if chart_type:
            notes.append(
                f'هذه الشريحة مخصصة للرسم المالي المعتمد ({chart_type}: {chart_note}). '
                'قسّم الشريحة إلى عمودين متجاورين متناسقين (50% لجدول البيانات، و50% للرسم البياني) '
                'باستخدام display: grid; grid-template-columns: 1fr 1fr; gap: 24px; داخل الشريحة، '
                'مع بقاء جدول البيانات كاملاً ومقروءاً على أحد الجانبين، والرسم البياني واضحاً بكامل عناصره على الجانب الآخر، ومنع استخدام position: absolute.'
            )
        else:
            notes.append('هذه الشريحة ليست واحدة من الرسوم المالية الثلاثة المعتمدة (waterfall, combo, heatmap)؛ اعرض جدول التقرير فقط وممنوع إضافة أي رسم بياني.')
        notes.append('الجدول لا يقل عن 12px ولا يزيد على 6 أعمدة في الشريحة، وتُرص الجداول المالية العادية تحت بعضها حتى تمتلئ المساحة المتاحة. عند انتهاء المساحة، تُستكمل الجداول في شرائح مالية تالية بدل التصغير أو القص أو ترك شريحة شبه فارغة بجدول واحد فقط.')
        financial_note = _financial_data_note(project_data)
        if financial_note and not source_note:
            notes.append(financial_note.strip())
    elif section_key == 'market':
        notes.append('الهيدر والفوتر ثابتان وتتم إضافتهما آلياً؛ اجعل مساحة الإبداع داخل منطقة المحتوى فقط.')
        market_design_reference = (
            'المرجع البصري لقسم دراسة السوق هو تقرير استثماري تحليلي راقٍ: خلفية بيضاء ومساحات هادئة، '
            'ألوان الهوية الأساسية مع لمسات ذهبية، عناوين كبيرة، فواصل رفيعة، حاويات ذات حواف مستديرة، '
            'وتباين واضح بين العنوان والمعلومة والخلاصة. هذه مراجع نبرة وهوية فقط وليست قالباً إلزامياً؛ '
            'دع SOL يختار بين فقرة تحريرية، تسلسل بصري، مخطط مفاهيمي أو أي تكوين مناسب للبيانات، ولا تفرض جدولاً أو بطاقات أو عدد أعمدة معيناً. '
            'لا تستخدم أيقونات أو رموزاً زخرفية أو ظلالاً ثقيلة. الحركة البصرية هنا تعني تدفق العين بين كتل المحتوى، '
            'وليس CSS animation قد لا يظهر في PDF.'
        )
        notes.append(market_design_reference)
        if chart_type == 'horizontal_bar':
            if lang == OFFER_LANG_ENGLISH:
                notes.append(
                    f'This slide is dedicated to the approved competitor-comparison chart ({chart_type}: {chart_note}). '
                    'Fixed layout: the competitors table on the LEFT and the horizontal bar chart on the RIGHT. '
                    'Use direction: ltr; grid-template-areas: "table chart"; grid-template-columns: 1fr 1fr; gap: 24px; inside a display: grid container, '
                    'keeping the full readable competitors table with the chart showing all its bars and prices, highlighting our project in the brand color without inventing figures or assumed averages.'
                )
            else:
                notes.append(
                    f'هذه الشريحة مخصصة لرسم مقارنة المنافسين المعتمد ({chart_type}: {chart_note}). '
                    'التخطيط ثابت: جدول المنافسين في اليمين ورسم الأعمدة الأفقية في اليسار. '
                    'استخدم direction: rtl; grid-template-areas: "table chart"; grid-template-columns: 1fr 1fr; gap: 24px; داخل حاوية display: grid، '
                    'مع بقاء جدول المنافسين كاملاً ومقروءاً، والرسم البياني واضحاً بكامل أشرطته وأسعاره مع إبراز مشروعنا بلون الهوية، ومنع اختراع أرقام أو متوسطات افتراضية.'
                )
        else:
            notes.append(
                'هذه شريحة سوق غير ثابتة: صمّم التكوين البصري والهرمية والمساحات بحرية كاملة بما يخدم البيانات المعتمدة. '
                'لا تكرر قالباً واحداً بين الشرائح ولا تحول المحتوى تلقائياً إلى جدول أو بطاقات. لا تستخدم وسم <table> '
                'إلا إذا كانت المقارنة الصفية هي الطريقة الوحيدة الواضحة للمعلومة؛ وفي غير ذلك استخدم تكويناً تحريرياً مثل '
                'عنوان محوري كبير، رقم أو خلاصة بارزة، فواصل بينية، كتل غير متناظرة، مسار بصري رأسي، أو شرائط CSS بسيطة مبنية بـ flex. '
                'أنشئ طبقتين بصريتين مختلفتين على الأقل، واجعل لكل شريحة شخصية مستقلة. استخدم تدفق HTML طبيعي بلا '
                'position:absolute أو ارتفاعات ثابتة لمنطقة النص، ووازن المساحة داخل منطقة المحتوى بحيث لا يتداخل أي نص أو يخرج من الشريحة.'
            )
    else:
        notes.append('الرسوم البيانية ممنوعة تماماً في هذا القسم؛ اعرض المحتوى بالجداول أو النصوص أو الصور حسب النمط المحدد.')
    notes_text = '\n'.join(f'- {n}' for n in notes)

    message = f"""أنشئ شريحة {slide_num}/{total_slides}: {title}
النوع: {slide_type}
نمط التصميم: {design_style} — {style_instructions}
{f'نوع الرسم المطلوب: {chart_type} — {chart_note}' if chart_note else ''}
كثافة المحتوى: {density} — {density_instructions}

النقاط الأساسية:
{bullets_text}

ملاحظات:
{notes_text}"""
    if lang == OFFER_LANG_ENGLISH:
        message += '\n\n' + OFFER_LANGUAGE_DIRECTIVE_EN
    return message


def _block_external_images(html):
    """Block external image URLs (http/https) except allowed placeholders."""
    if not html:
        return html
    # ##STREET_VIEW_N## is deliberately absent: no such image exists, so an <img> carrying one is
    # removed here instead of surviving to be blanked into an empty frame.
    allowed = {'##MAP_OVERVIEW##', '##MAP_LANDMARKS##', '##MAP_ACCESS##', '##MAP_CATCHMENT##',
               '##IMAGE_COVER##', '##LOGO##', '##PROJECT_LOGO##', '##MOODBOARD_IMAGE_1##', '##MOODBOARD_IMAGE_2##',
               '##MOODBOARD_IMAGE_3##', '##MOODBOARD_IMAGE_4##'}

    def _replace_src(match):
        url = match.group(1)
        if any(url.startswith(p) for p in allowed) or url.startswith('##INTERIOR_') or url.startswith('##PLAN_IMAGE_') or url.startswith('##2D_PLAN_') or url.startswith('/uploads/') or url.startswith('/assets/'):
            return match.group(0)
        if url.startswith('http://') or url.startswith('https://') or url.startswith('data:'):
            return ''
        return match.group(0)

    # Remove <img src="external"> tags
    html = re.sub(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', _replace_src, html, flags=re.IGNORECASE)
    # Remove external background-image CSS values
    html = re.sub(r'background-image\s*:\s*url\(["\']?(https?://[^"\')]+|data:[^"\')]+)["\']?\)', '', html, flags=re.IGNORECASE)
    return html


def _ensure_map_placeholder(html, slide_type):
    """Ensure map slides contain the expected placeholder."""
    expected = {
        'map_overview': '##MAP_OVERVIEW##',
        'map_landmarks': '##MAP_LANDMARKS##',
        'map_access': '##MAP_ACCESS##',
        'map_catchment': '##MAP_CATCHMENT##',
    }
    if slide_type not in expected:
        return html
    marker = expected[slide_type]
    if marker in html:
        return html
    def apply(match):
        return _set_tag_style(
            match.group(0), ('background-image', 'background-size', 'background-position', 'background-repeat'),
            f'background-image:url({marker})!important;background-size:contain!important;'
            'background-position:center center!important;background-repeat:no-repeat!important;')

    html = re.sub(r'<div\b(?=[^>]*\bclass\s*=\s*["\'][^"\']*\bslide\b)[^>]*>',
                  apply, html, count=1, flags=re.IGNORECASE)
    print(f"[POST] Injected fallback placeholder {marker} into slide background")
    return html


def _map_media_allowed(slide_type, content_source, slide_title='', allow_all_maps=False):
    """Return whether a slide is explicitly allowed to carry a generated map."""
    if allow_all_maps:
        return True
    slide_type = str(slide_type or '').strip().lower()
    content_source = str(content_source or '').strip().lower()
    slide_title = str(slide_title or '').strip().lower()
    if slide_type in ('map_overview', 'map_landmarks', 'map_access', 'map_catchment'):
        return True
    if content_source == 'site_analysis' or (isinstance(content_source, str) and content_source.startswith('site_analysis:0')):
        return True
    if content_source in {
        'location_polygon', 'main_roads', 'catchment_areas', 'nearby_landmarks',
        'location_detail', 'executive_content.summary',
    }:
        return True
    # Land analysis may deliberately show the approved overview map beside the
    # parcel facts. Keep this narrow so timeline, finance and visual-concept
    # slides remain blocked.
    if content_source.startswith('land_') or content_source in {'land', 'croquis'}:
        return True
    return bool(re.search(
        r'(?:تحليل\s*الأرض|الأرض\s*والاشتراطات|الأرض\s*والكروكي|حدود\s*الأرض|الكروكي|land analysis|land/croquis|croquis|خريطة|خرائط|موقع|الموقع|طرق|وصول|معالم|نطاق)',
        slide_title, flags=re.IGNORECASE,
    ))


def _strip_unplanned_map_media(html, slide_type, content_source=None, slide_title=None,
                               strip_resolved=True, allow_all_maps=False):
    """Remove map tokens and resolved map assets from slides that do not own maps.

    The model receives the available map tokens as context. Without this final
    boundary it could place a valid map token in a timeline, finance, plans,
    exterior or interior slide and the resolver would turn that token into a
    real map image.
    """
    if not html or allow_all_maps or _map_media_allowed(slide_type, content_source, slide_title, allow_all_maps=allow_all_maps):
        return html

    # Map variants include forms such as _SATELLITE, _ROADMAP and
    # _SATELLITE_EDITABLE. Keep the suffix open-ended so no variant can leak
    # into a non-location slide and later resolve into a real map image.
    map_token_ref = r'##MAP_(?:OVERVIEW|LANDMARKS|ACCESS|CATCHMENT)(?:_[A-Z0-9]+)*##'
    resolved_map_ref = r'/uploads/maps/|/api/map-images/'
    map_ref = (
        rf'(?:{map_token_ref}|{resolved_map_ref})'
        if strip_resolved else map_token_ref
    )
    html = re.sub(
        rf'<img\b[^>]*(?:src\s*=\s*["\'][^"\']*{map_ref}[^"\']*["\']|{map_ref})[^>]*>',
        '', html, flags=re.IGNORECASE,
    )
    html = re.sub(
        rf'(?:background(?:-image)?\s*:\s*)[^;}}]*(?:{map_ref})[^;}}]*;?',
        '', html, flags=re.IGNORECASE,
    )
    html = re.sub(r'\sdata-map-summary-(?:background|card)(?:\s*=\s*["\'][^"\']*["\'])?', '', html, flags=re.IGNORECASE)
    html = re.sub(map_token_ref, '', html, flags=re.IGNORECASE)
    return html


def _set_tag_style(tag, property_names, declarations):
    style_match = re.search(r'style\s*=\s*(["\'])(.*?)\1', tag, re.IGNORECASE)
    if style_match:
        style = style_match.group(2)
        # Remove one property at a time.  A single alternation used to consume
        # the separator after every other declaration, leaving duplicate inline
        # rules after a second normalization pass.
        for property_name in property_names:
            style = re.sub(
                rf'(^|;)\s*{re.escape(property_name)}\s*:[^;]*;?',
                r'\1', style, flags=re.IGNORECASE
            )
        style = style.strip('; ')
        style = (style + ';' if style else '') + declarations
        return tag[:style_match.start(2)] + style + tag[style_match.end(2):]
    if tag.rstrip().endswith('/>'):
        position = tag.rfind('/>')
        return tag[:position].rstrip() + f' style="{declarations}" />'
    return tag.replace('>', f' style="{declarations}">', 1)


def _map_media_contain(html):
    indicators = ('MAP_', '/uploads/maps/', '/api/map-images/')

    def normalize_img(match):
        tag = match.group(0)
        if not any(indicator.lower() in tag.lower() for indicator in indicators):
            return tag
        return _set_tag_style(
            tag, ('object-fit', 'object-position', 'object-position-x', 'object-position-y'),
            'object-fit:contain!important;object-position:center center!important;')

    def normalize_background(match):
        tag = match.group(0)
        lowered = tag.lower()
        if 'background' not in lowered or not any(indicator.lower() in lowered for indicator in indicators):
            return tag
        return _set_tag_style(
            tag, ('background-size', 'background-position', 'background-position-x',
                  'background-position-y', 'background-repeat'),
            'background-size:contain!important;background-position:center center!important;'
            'background-repeat:no-repeat!important;')

    html = re.sub(r'<img\b[^>]*>', normalize_img, html, flags=re.IGNORECASE)
    return re.sub(r'<[a-z][^>]*\bstyle\s*=\s*["\'][^"\']*["\'][^>]*>',
                  normalize_background, html, flags=re.IGNORECASE)


def _ensure_map_summary_structure(html):
    opening_end = html.find('>')
    closing_start = html.rfind('</div>')
    if opening_end < 0 or closing_start <= opening_end:
        return html
    opening = html[:opening_end + 1]
    inner = html[opening_end + 1:closing_start]
    closing = html[closing_start:]
    inner = re.sub(r'<img\b[^>]*(?:##MAP_OVERVIEW##|/uploads/maps/|/api/map-images/)[^>]*>',
                   '', inner, flags=re.IGNORECASE)
    if 'data-map-summary-card' not in inner:
        inner = f'<div data-map-summary-card>{inner}</div>'
    background = ('<div data-map-summary-background '
                  'style="background-image:url(##MAP_OVERVIEW##);"></div>')
    return opening + background + inner + closing


def _location_data_timestamp(project_data):
    value = str((project_data or {}).get('location_data_fetched_at') or '').strip()
    if not value:
        return ''
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        saudi = parsed.astimezone(timezone(timedelta(hours=3)))
        hour = saudi.hour % 12 or 12
        period = 'ص' if saudi.hour < 12 else 'م'
        return (
            f'{saudi.day:02d} / {saudi.month:02d} / {saudi.year:04d} م '
            f'(م = ميلادي) الساعة {hour:02d}:{saudi.minute:02d} {period}'
        )
    except (TypeError, ValueError):
        return value


def _inject_location_data_timestamp(html, project_data):
    timestamp = _location_data_timestamp(project_data)
    if not timestamp or timestamp in html:
        return html
    label = html_lib.escape('تم قياس زمن القيادة بتاريخ ' + timestamp)
    marker = (f'<div data-location-data-timestamp style="position:absolute;bottom:40px;right:24px;z-index:20;'
              f'font-size:11px;background:#ffffff;color:#172033;padding:4px 8px;border-radius:5px;">{label}</div>')
    return re.sub(r'(</div>\s*)$', marker + r'\1', html, count=1)


def _normalize_map_summary_layout(html, marker_side='right', full_width=False):
    def normalize_background(match):
        return _set_tag_style(
            match.group(0),
            ('position', 'top', 'right', 'bottom', 'left', 'width', 'height', 'object-fit',
             'object-position', 'background-size', 'background-position', 'background-repeat', 'z-index'),
            'position:absolute!important;top:56px!important;right:0!important;bottom:36px!important;'
            'left:0!important;width:100%!important;height:calc(100% - 92px)!important;object-fit:contain!important;'
            'object-position:center center!important;background-size:contain!important;'
            'background-position:center center!important;background-repeat:no-repeat!important;z-index:0!important;')

    card_side = ('right:24px!important;left:auto!important;' if marker_side == 'left'
                 else 'left:24px!important;right:auto!important;')

    def normalize_card(match):
        card_is_full_width = full_width or bool(
            re.search(r'\bdata-site-analysis-full\b', match.group(0), flags=re.IGNORECASE)
        )
        if card_is_full_width:
            return _set_tag_style(
                match.group(0), ('position', 'top', 'right', 'bottom', 'left', 'width', 'max-height', 'z-index'),
                'position:absolute!important;top:76px!important;right:24px!important;bottom:56px!important;'
                'left:24px!important;width:auto!important;max-height:588px!important;z-index:2!important;')
        return _set_tag_style(
            match.group(0), ('position', 'top', 'right', 'bottom', 'left', 'width', 'max-height', 'z-index'),
            'position:absolute!important;top:76px!important;bottom:56px!important;width:40%!important;'
            f'max-height:588px!important;z-index:2!important;{card_side}')

    html = re.sub(r'<[a-z][^>]*\bdata-map-summary-background\b[^>]*>',
                  normalize_background, html, flags=re.IGNORECASE)
    return re.sub(r'<[a-z][^>]*\bdata-map-summary-card\b[^>]*>',
                  normalize_card, html, flags=re.IGNORECASE)


def _has_real_map_background(html):
    if not html:
        return False
    if re.search(r'##MAP_[A-Z0-9_]+##', html, re.I):
        return True
    for m in re.finditer(r'data-map-summary-background[^>]*style=[\'"]([^\'"]+)[\'"]', html, re.I):
        style = m.group(1)
        url_match = re.search(r'url\(\s*[\'"]?([^\'"\)]+)[\'"]?\s*\)', style, re.I)
        if url_match:
            val = url_match.group(1).strip()
            if val and val.lower() != 'none':
                return True
    for m in re.finditer(r'<img\b[^>]*\bdata-map-summary-background\b[^>]*src=[\'"]([^\'"]+)[\'"]', html, re.I):
        val = m.group(1).strip()
        if val:
            return True
    return False


def _unwrap_spurious_map_summary_cards(html):
    """Unwrap data-map-summary-card wrappers when there is no real map background."""
    if not html or 'data-map-summary-card' not in html:
        return html
    if _has_real_map_background(html):
        return html
    html = re.sub(r'<div\b[^>]*\bdata-map-summary-background\b[^>]*>\s*</div>', '', html, flags=re.I)
    html = re.sub(r'<img\b[^>]*\bdata-map-summary-background\b[^>]*>', '', html, flags=re.I)
    while True:
        card_open = re.search(r'<div\b[^>]*\bdata-map-summary-card\b[^>]*>', html, re.I)
        if not card_open:
            break
        start_pos = card_open.start()
        content_start = card_open.end()
        depth = 1
        content_end = None
        match_end = None
        div_pattern = re.compile(r'<\s*(/)?\s*div\b[^>]*>', re.I)
        for m in div_pattern.finditer(html, content_start):
            if m.group(1):
                depth -= 1
                if depth == 0:
                    content_end = m.start()
                    match_end = m.end()
                    break
            else:
                depth += 1
        if content_end is not None and match_end is not None:
            inner = html[content_start:content_end]
            html = html[:start_pos] + inner + html[match_end:]
        else:
            html = html[:start_pos] + html[content_start:]
            break
    return html


_PRESENTATION_EXACT_NUMBER_CONTEXT = re.compile(
    r'تاريخ|هاتف|جوال|وثيقة|صك|مخطط|قطعة|معرف|إحداث|خط العرض|خط الطول|'
    r'phone|mobile|date|document|identifier|latitude|longitude|\blat\b|\blng\b|\bid\b',
    re.IGNORECASE,
)


def _format_presentation_numeric_text(html):
    parts = re.split(r'(<[^>]+>)', html)
    ignored = False
    number_pattern = re.compile(r'(?<![\d,٬])(-?(?:\d{4,}(?:\.\d+)?|\d+\.\d{2,}))(?![\d,٬])')

    def format_text(text, prefix=''):
        numeric_only = bool(re.fullmatch(r'\s*-?\d+(?:\.\d+)?%?\s*', text or ''))

        def format_number(match):
            value = match.group(1)
            window = (prefix[-64:] if numeric_only else '') + text[max(0, match.start() - 48):match.end() + 24]
            if _PRESENTATION_EXACT_NUMBER_CONTEXT.search(window):
                return value
            if '.' not in value and 1900 <= abs(int(value)) <= 2100:
                return value
            if '.' not in value and value.lstrip('-').startswith('0') and len(value.lstrip('-')) >= 7:
                return value
            try:
                rounded = Decimal(value).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
            except (InvalidOperation, ValueError):
                return value
            if rounded == rounded.to_integral_value():
                return f'{int(rounded):,}'
            return f'{rounded:,.1f}'

        return number_pattern.sub(format_number, text)

    recent_text = ''
    for index, part in enumerate(parts):
        if part.startswith('<'):
            if re.match(r'<\s*(?:style|script)\b', part, flags=re.IGNORECASE):
                ignored = True
            elif re.match(r'<\s*/\s*(?:style|script)\b', part, flags=re.IGNORECASE):
                ignored = False
        elif not ignored:
            parts[index] = format_text(part, recent_text)
            recent_text = (recent_text + ' ' + part)[-160:]
    return ''.join(parts)


def _normalize_table_readability(html):
    # Strip height stretch from wrapper containers around tables
    def _strip_table_wrapper_stretch(h):
        """Remove height:100%, height:NNNpx, flex:1 from divs that wrap tables."""
        def deflate_wrapper(m):
            tag = m.group(0)
            tag = re.sub(r'height\s*:\s*(?:100%|\d{3,}px)\s*;?', '', tag, flags=re.IGNORECASE)
            tag = re.sub(r'flex\s*:\s*1\s*;?', '', tag, flags=re.IGNORECASE)
            return tag
        # Match opening div tags that precede a <table
        return re.sub(r'<div\b[^>]*>(?=\s*<table\b)', deflate_wrapper, h, flags=re.IGNORECASE)
    html = _strip_table_wrapper_stretch(html)

    def _count_columns(table_html):
        """Count the max columns in the first row of a table."""
        row_match = re.search(r'<tr\b[^>]*>(.*?)</tr>', table_html, re.IGNORECASE | re.S)
        if not row_match:
            return 0
        cells = re.findall(r'<(?:th|td)\b', row_match.group(1), re.IGNORECASE)
        return len(cells)

    def normalize_header(match):
        return _set_tag_style(
            match.group(0), ('font-size', 'line-height', 'padding', 'overflow-wrap'),
            'font-size:13px!important;line-height:1.35!important;padding:8px 12px!important;overflow-wrap:anywhere!important;')

    def normalize_cell(match):
        tag = re.sub(r'height\s*:\s*(?:100%|\d{2,}px)\s*;?', '', match.group(0), flags=re.IGNORECASE)
        return _set_tag_style(
            tag, ('font-size', 'line-height', 'padding', 'vertical-align', 'overflow-wrap'),
            'font-size:12px!important;line-height:1.35!important;padding:7px 12px!important;vertical-align:middle!important;overflow-wrap:anywhere!important;')

    # Per-table normalization: count columns and apply width constraint
    def normalize_full_table(match):
        table_html = match.group(0)
        table_tag_match = re.match(r'<table\b[^>]*>', table_html, re.IGNORECASE)
        if not table_tag_match:
            return table_html
        old_tag = table_tag_match.group(0)

        # Preserve custom density if explicitly flagged
        if 'data-preserve-density' in old_tag:
            return table_html

        cols = _count_columns(table_html)
        if cols <= 2:
            max_w = '820px'
        elif cols <= 4:
            max_w = '1080px'
        else:
            max_w = '1200px'
        # Strip width:100% and excessive height from the <table> tag
        new_tag = re.sub(r'width\s*:\s*100%\s*;?', '', old_tag, flags=re.IGNORECASE)
        new_tag = re.sub(r'height\s*:\s*(?:100%|\d{3,}px)\s*;?', '', new_tag, flags=re.IGNORECASE)
        new_tag = _set_tag_style(
            new_tag, ('border-collapse', 'max-width', 'margin-left', 'margin-right'),
            f'border-collapse:collapse!important;max-width:{max_w}!important;margin-left:auto!important;margin-right:auto!important;')
        table_html = new_tag + table_html[table_tag_match.end():]

        table_html = re.sub(r'<th\b[^>]*>', normalize_header, table_html, flags=re.IGNORECASE)
        table_html = re.sub(r'<td\b[^>]*>', normalize_cell, table_html, flags=re.IGNORECASE)
        return table_html

    html = re.sub(r'<table\b[^>]*>.*?</table>', normalize_full_table, html, flags=re.IGNORECASE | re.S)

    def normalize_numeric_cell(match):
        opening, body = match.group(1), match.group(2)
        plain = html_lib.unescape(re.sub(r'<[^>]*>', '', body)).strip()
        compact = re.sub(r'[\d٠-٩\s,٬.٫%٪()\-+/:]', '', plain)
        for word in ('ريال', 'ر.س', 'سنة', 'عام', 'مؤشر', 'مرة'):
            compact = compact.replace(word, '')
        if re.search(r'[\d٠-٩]', plain) and not re.search(r'[A-Za-z\u0600-\u06ff]', compact):
            opening = _set_tag_style(
                opening, ('text-align', 'direction'),
                'text-align:center!important;direction:ltr!important;'
            )
        return opening + body + '</td>'

    return re.sub(r'(<td\b[^>]*>)([\s\S]*?)</td\s*>', normalize_numeric_cell,
                  html, flags=re.IGNORECASE)


def _normalize_brand_overlay(html, branding):
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    value = primary.lstrip('#')
    red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    html = re.sub(r'rgba\(\s*11\s*,\s*31\s*,\s*51\s*,\s*([0-9.]+)\s*\)',
                  lambda match: f'rgba({red},{green},{blue},{match.group(1)})', html, flags=re.IGNORECASE)
    return re.sub(r'#0b1f33\b', primary, html, flags=re.IGNORECASE)


def _normalize_cover_overlay_element(html, branding):
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    value = primary.lstrip('#')
    red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))

    def normalize_overlay(match):
        return _set_tag_style(
            match.group(0), ('position', 'inset', 'background', 'z-index'),
            f'position:absolute!important;inset:0!important;background:linear-gradient(135deg,'
            f'rgba({red},{green},{blue},0.88) 0%,rgba({red},{green},{blue},0.55) 50%,'
            f'rgba({red},{green},{blue},0.92) 100%)!important;z-index:1!important;')

    return re.sub(r'<[a-z][^>]*\bdata-cover-overlay\b[^>]*>',
                  normalize_overlay, html, flags=re.IGNORECASE)


def _css_solid_color(value):
    text = re.sub(r'\s*!important\s*$', '', str(value or '').strip().lower())
    named = {'white': '#ffffff', 'black': '#000000', 'navy': '#000080'}
    if text in named:
        return named[text]
    if re.fullmatch(r'#[0-9a-f]{3}|#[0-9a-f]{6}', text):
        return normalize_hex_color(text)
    match = re.fullmatch(r'rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*([\d.]+))?\s*\)', text)
    if not match or (match.group(4) is not None and float(match.group(4)) < 0.95):
        return None
    channels = [max(0, min(255, int(match.group(index)))) for index in (1, 2, 3)]
    return '#' + ''.join(f'{channel:02x}' for channel in channels)


def _inline_style_properties(style):
    properties = {}
    for declaration in str(style or '').split(';'):
        if ':' not in declaration:
            continue
        name, value = declaration.split(':', 1)
        properties[name.strip().lower()] = value.strip()
    return properties


def _compile_slide_selector(selector):
    """Compile a simple CSS selector into compounds of (tag, classes, id).

    Only tag/.class/#id compounds joined by descendant or child combinators are
    supported. Pseudo-classes, attribute selectors and anything else return
    None so the rule is ignored rather than misapplied.
    """
    selector = str(selector or '').strip()
    if not selector or re.search(r'[:*~\[\]|+@]', selector):
        return None
    compounds = []
    for part in re.split(r'[\s>]+', selector):
        if not part:
            continue
        if not re.fullmatch(r'(?:[a-zA-Z][\w-]*)?(?:[.#][\w-]+)*', part):
            return None
        tag_match = re.match(r'[a-zA-Z][\w-]*', part)
        compounds.append((
            tag_match.group(0).lower() if tag_match else '',
            frozenset(re.findall(r'\.([\w-]+)', part)),
            (re.findall(r'#([\w-]+)', part) or [''])[0],
        ))
    return compounds or None


def _parse_slide_style_rules(html):
    """Ordered (compounds, properties) rules collected from <style> blocks."""
    rules = []
    for block in re.findall(r'<style\b[^>]*>([\s\S]*?)</style\s*>', str(html or ''), flags=re.IGNORECASE):
        body = re.sub(r'/\*[\s\S]*?\*/', '', block)
        for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', body):
            properties = _inline_style_properties(match.group(2))
            if not properties:
                continue
            for selector in str(match.group(1)).split(','):
                compounds = _compile_slide_selector(selector)
                if compounds:
                    rules.append((compounds, properties))
    return rules


def _compound_matches(compound, element):
    tag, classes, element_id = compound
    if tag and element[0] != tag:
        return False
    if classes and not classes.issubset(element[1]):
        return False
    if element_id and element[2] != element_id:
        return False
    return True


def _selector_matches(compounds, element, ancestors):
    """Greedy descendant match: last compound is the element itself."""
    if not compounds or not _compound_matches(compounds[-1], element):
        return False
    cursor = len(ancestors) - 1
    for compound in reversed(compounds[:-1]):
        while cursor >= 0 and not _compound_matches(compound, ancestors[cursor]):
            cursor -= 1
        if cursor < 0:
            return False
        cursor -= 1
    return True


class _SlideContrastAudit(HTMLParser):
    _VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    _MEDIA_TAGS = {'img', 'video', 'canvas', 'svg', 'picture'}

    def __init__(self, rules=None, html=''):
        super().__init__(convert_charrefs=True)
        self.rules = rules or []
        self.stack = []
        self.issues = []
        self._line_offsets = [0]
        for match in re.finditer('\n', str(html or '')):
            self._line_offsets.append(match.end())

    def _tag_span(self):
        """Absolute (start, end) offsets of the current opening tag."""
        line, column = self.getpos()
        if line < 1 or line > len(self._line_offsets):
            return (0, 0)
        start = self._line_offsets[line - 1] + column
        return (start, start + len(self.get_starttag_text() or ''))

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1] if self.stack else None
        foreground = parent['fg'] if parent else '#000000'
        background = parent['bg'] if parent else '#ffffff'
        attributes = dict(attrs)
        element = (
            tag.lower(),
            frozenset(str(attributes.get('class') or '').split()),
            str(attributes.get('id') or ''),
        )
        ancestors = [frame['element'] for frame in self.stack]
        styles = {}
        for compounds, properties in self.rules:
            if _selector_matches(compounds, element, ancestors):
                styles.update(properties)
        styles.update(_inline_style_properties(attributes.get('style')))
        if 'color' in styles:
            foreground = _css_solid_color(styles['color'])
        background_value = styles.get('background-color') or styles.get('background')
        if background_value and background_value.lower().strip() != 'transparent':
            background = _css_solid_color(background_value)
        if element[0] in self._MEDIA_TAGS and self.stack:
            self.stack[-1]['contains_media'] = True
        if tag.lower() not in self._VOID_TAGS:
            self.stack.append({
                'element': element,
                'fg': foreground,
                'bg': background,
                'positioned': str(styles.get('position') or '').strip().lower() in ('absolute', 'fixed'),
                'contains_media': False,
                'span': self._tag_span(),
            })

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        lowered = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]['element'][0] == lowered:
                popped = self.stack[index:]
                del self.stack[index:]
                if self.stack and any(frame['contains_media'] for frame in popped):
                    self.stack[-1]['contains_media'] = True
                break

    def _over_media(self):
        """Whether the current text sits in a positioned layer over an image.

        The nearest absolutely/fixed-positioned ancestor (or self) defines the
        local context; text there is indeterminate when that layer or its parent
        holds an image, so it is neither flagged nor repaired.
        """
        for index in range(len(self.stack) - 1, -1, -1):
            frame = self.stack[index]
            if frame['positioned']:
                parent = self.stack[index - 1] if index else None
                return bool(frame['contains_media'] or (parent and parent['contains_media']))
        return False

    def _on_contrast_issue(self):
        """Hook for subclasses; receives the flagged innermost frame on top of the stack."""

    def handle_data(self, data):
        text = re.sub(r'\s+', ' ', data).strip()
        if not text or not self.stack or self.stack[-1]['element'][0] in ('style', 'script'):
            return
        foreground, background = self.stack[-1]['fg'], self.stack[-1]['bg']
        if not foreground or not background or self._over_media():
            return
        ratio = contrast_ratio(foreground, background)
        if ratio < 4.5:
            self.issues.append((text[:40], foreground, background, ratio))
            self._on_contrast_issue()


def slide_contrast_issues(html):
    html = str(html or '')
    parser = _SlideContrastAudit(rules=_parse_slide_style_rules(html), html=html)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return []
    return parser.issues


class _SlideContrastRepair(_SlideContrastAudit):
    """Records opening-tag spans for elements whose effective text is unreadable."""

    def __init__(self, html):
        super().__init__(rules=_parse_slide_style_rules(html), html=html)
        self.repairs = {}

    def _on_contrast_issue(self):
        frame = self.stack[-1]
        start, end = frame['span']
        if end <= start or start in self.repairs:
            return
        color = readable_text_color('#1e293b', frame['bg'], ('#0f172a', '#334155'))
        self.repairs[start] = (start, end, color)


def _repair_slide_text_contrast(html):
    """Patch elements whose effective text color fails 4.5:1 against the surface below.

    Effective color accounts for inherited inline styles and the simple
    <style>-block selectors a model emits, so a rule like ``td{color:#fff}`` on
    the white content canvas is repaired exactly like an inline declaration.
    Text over images or gradients is left alone — the surface is indeterminate
    there. Each patched element receives ``color:...!important`` so the fix wins
    over the offending rule.
    """
    html = str(html or '')
    if not html:
        return html
    parser = _SlideContrastRepair(html)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return html
    for start in sorted(parser.repairs, reverse=True):
        start, end, color = parser.repairs[start]
        tag = html[start:end]
        if not tag.startswith('<'):
            continue
        patched = _set_tag_style(tag, ('color',), f'color:{color}!important;')
        html = html[:start] + patched + html[end:]
    return html


def _nearby_landmark_table_rows(project_data, limit=7):
    """Return the same four visible columns used by the nearby-landmarks table."""
    source = project_data if isinstance(project_data, dict) else {}
    canonical = source.get('nearby_landmarks_data')
    legacy = source.get('landmarks_matrix')
    rows = canonical if isinstance(canonical, list) and canonical else legacy
    if not isinstance(rows, list):
        return []
    rows = [row for row in rows if isinstance(row, dict)]

    def is_selected(row):
        value = row.get('show_on_map', row.get('selected'))
        return value is True or str(value or '').strip().lower() in {'true', '1', 'yes'}

    selected = [row for row in rows if is_selected(row)]
    rows = selected if selected else rows

    def first_value(row, *keys):
        for key in keys:
            value = row.get(key)
            if value not in (None, '', []):
                return value
        return ''

    result = []
    for row in rows:
        name = first_value(row, 'name', 'title', 'landmark', 'displayName')
        if name in (None, ''):
            continue
        result.append([
            name,
            first_value(row, 'category', 'type'),
            first_value(row, 'distance_km', 'distance', 'distance_text'),
            first_value(row, 'duration_minutes', 'duration_min', 'duration', 'minutes', 'duration_text'),
        ])
        if limit is not None and len(result) >= limit:
            break
    return result


def _required_slide_texts(slide, project_data):
    content_sources = (slide or {}).get('content_sources') if isinstance(slide, dict) else None
    if isinstance(content_sources, list) and content_sources:
        required = []
        for content_source in content_sources:
            item = dict(slide)
            item.pop('content_sources', None)
            item['content_source'] = content_source
            required.extend(_required_slide_texts(item, project_data))
        return list(dict.fromkeys(required))
    source = str((slide or {}).get('content_source') or '')
    chart_type = canonicalize_chart_type((slide or {}).get('chart_type'))
    project_data = project_data if isinstance(project_data, dict) else {}
    model = _parse_financial_dict(project_data.get('financial_study_model'))
    chart_source = _financial_chart_source(slide, model)
    if chart_type == 'combo':
        c_data = _extract_combo_chart_data(chart_source, model, project_data)
        items = c_data.get('items') or []
        return [str(it.get('year') or '') for it in items if str(it.get('year') or '').strip()]
    if chart_type == 'waterfall':
        w_data = _extract_waterfall_chart_data(chart_source, model, project_data)
        items = w_data.get('items') or []
        res = [str(it.get('name') or '') for it in items if str(it.get('name') or '').strip()]
        if w_data.get('total', {}).get('name'):
            res.append(str(w_data['total']['name']))
        return res
    if chart_type == 'heatmap':
        h_data = _extract_heatmap_chart_data(chart_source, model, project_data)
        matrix = h_data.get('matrix') or []
        return [str(r.get('metric') or '') for r in matrix if str(r.get('metric') or '').strip()]
    if (slide or {}).get('type') == 'map_landmarks' or source == 'nearby_landmarks':
        rows = _nearby_landmark_table_rows(project_data)
        if rows:
            return list(dict.fromkeys(
                str(value).strip()
                for row in rows
                for value in row
                if str(value or '').strip()
            ))
        value = str(project_data.get('nearby_landmarks') or '').strip()
        return [item.strip() for item in re.split(r'[\n|]', value) if item.strip()]
    if str(source or '').startswith('site_analysis'):
        value = str(project_data.get('site_analysis') or '').strip()
        paragraphs = [p.strip() for p in re.split(r'\r?\n\s*\r?\n', value) if p.strip()]
        if not paragraphs:
            paragraphs = [p.strip() for p in value.splitlines() if p.strip()] or [value]
        if ':' in str(source):
            parts = str(source).split(':')
            if len(parts) >= 3:
                start = int(parts[1]) if parts[1].isdigit() else 0
                end = int(parts[2]) if parts[2].isdigit() else len(paragraphs)
                paragraphs = paragraphs[start:end]
        return [p for p in paragraphs if len(p) > 15]
    def _req_row_range():
        start = (slide or {}).get('market_row_start')
        end = (slide or {}).get('market_row_end')
        if start is None or end is None:
            return None
        return max(int(start), 0), max(int(end), 0)

    opp_match = re.fullmatch(r'executive_content\.opportunity(?::(\d+):(\d+))?', str(source or ''))
    if opp_match:
        executive = _decode_json_fact(project_data.get('executive_content'))
        value = str(executive.get('opportunity') or '').strip() if isinstance(executive, dict) else ''
        explicit = _req_row_range()
        if not value:
            return []
        chunks = _exec_text_chunks(value)
        if explicit is not None or opp_match.group(1) is not None:
            start, end = explicit or (int(opp_match.group(1)), int(opp_match.group(2)))
            return chunks[start:end]
        pages = _budget_row_pages([('', chunk) for chunk in chunks])
        return [chunk for _, chunk in (pages[0][1] if pages else [('', value)])]
    feat_match = re.fullmatch(r'executive_content\.features(?::(\d+):(\d+))?', str(source or ''))
    if feat_match:
        items = _executive_feature_items(project_data)
        explicit = _req_row_range()
        if explicit is not None or feat_match.group(1) is not None:
            start, end = explicit or (int(feat_match.group(1)), int(feat_match.group(2)))
            items = items[start:end]
        else:
            ranges = _balanced_row_ranges(len(items), _executive_feature_page_size(items))
            if ranges:
                items = items[ranges[0][0]:ranges[0][1]]
        return items
    summary_match = re.fullmatch(r'executive_content\.summary(?::(\d+):(\d+))?', str(source or ''))
    if summary_match:
        explicit = _req_row_range()
        if explicit is not None or summary_match.group(1) is not None:
            sections = _executive_summary_sections(project_data)
            start, end = explicit or (int(summary_match.group(1)), int(summary_match.group(2)))
            return [f'{label}\n{text}' if label else text for label, text in sections[start:end]]
        pages = _executive_summary_pages(project_data)
        first = pages[0][1] if pages else _executive_summary_sections(project_data)
        return [f'{label}\n{text}' if label else text for label, text in first]
    if source in {
        'executive_content.risks', 'market_study_data.risk_analysis',
        'market_study_data.risk_register', 'market_study_data.risks',
        'market_study_data.summary.risks',
    }:
        risk_source, risk_items = _risk_analysis_source(project_data)
        return [
            str(value).strip()
            for item in risk_items
            for value in (item.get('risk'), item.get('mitigation'))
            if str(value or '').strip()
        ] if source == risk_source else []
    if source == 'market_study_data.swot':
        market = _decode_json_fact(project_data.get('market_study_data'))
        swot = market.get('swot') if isinstance(market, dict) and isinstance(market.get('swot'), dict) else {}
        return [str(value).strip() for value in swot.values() if str(value or '').strip()]
    if source == 'market_study_data.scope':
        market = _market_state(project_data)
        return [str(value).strip() for row in _market_scope_rows(market) for value in row if str(value or '').strip()]
    summary_match = re.fullmatch(r'market_study_data\.summary(?::(\d+):(\d+))?', source)
    if summary_match:
        market = _market_state(project_data)
        rows, _row_offset = _market_rows_for_slide(
            slide, 'market_study_data.summary', _market_summary_rows(market)
        )
        return [str(value).strip() for row in rows for value in row if str(value or '').strip()]
    one_block_match = re.fullmatch(r'market_study_data\.one_block_summary(?::(\d+):(\d+))?', source)
    if one_block_match:
        market = _market_state(project_data)
        value = _market_one_block_paragraph(market)
        if one_block_match.group(1) is not None:
            value = value[int(one_block_match.group(1)):int(one_block_match.group(2))]
        return [value] if value else []
    sources_match = re.fullmatch(r'market_study_data\.sources(?::(\d+):(\d+))?', source)
    if sources_match:
        market = _market_state(project_data)
        rows = _market_source_rows(market)
        if sources_match.group(1) is not None:
            rows = rows[int(sources_match.group(1)):int(sources_match.group(2))]
        return [str(value).strip() for row in rows for value in row if str(value or '').strip()]
    if source == 'market_study_data.competitors' or 'competitors' in source:
        market = _decode_json_fact(project_data.get('market_study_data')) if isinstance(project_data.get('market_study_data'), (str, dict)) else {}
        competitors = market.get('competitors') if isinstance(market, dict) else []
        competitors = [c for c in competitors if isinstance(c, dict) and _competitor_name(c)]
        c_start = (slide or {}).get('competitor_start')
        c_end = (slide or {}).get('competitor_end')
        cs = str(source or '')
        if c_start is not None and c_end is not None:
            competitors = competitors[c_start:c_end]
        elif ':' in cs:
            parts = cs.split(':')
            if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
                competitors = competitors[int(parts[-2]):int(parts[-1])]
        items = _extract_competitor_chart_data(competitors, project_data)
        return [str(it.get('name') or '').strip() for it in items if str(it.get('name') or '').strip()]
    if source == 'contact_closing':
        values = [str(project_data.get(key) or '').strip() for key in (
            'contact_name', 'contact_position', 'contact_phone', 'contact_email',
            'contact_website', 'contact_address', 'contact_social_media')]
        entered = [value for value in values if value]
        return entered or [str(project_data.get('project_name') or 'المشروع').strip(), 'شكر']

    def row_values(row):
        values = []
        if isinstance(row, dict):
            for k, v in row.items():
                if str(k).strip() in ('ترتيب / حذف', 'ترتيب', 'حذف', 'إجراءات', 'actions', 'id', 'row_id'):
                    continue
                if str(v).strip() in ('أعلىأسفلحذف', 'أعلى', 'أسفل', 'حذف', '—', '-', '0', '0.0'):
                    continue
                values.append(v)
        elif isinstance(row, (list, tuple)):
            for v in row:
                if str(v).strip() in ('أعلىأسفلحذف', 'أعلى', 'أسفل', 'حذف', '—', '-', '0', '0.0'):
                    continue
                values.append(v)
        return [str(value).strip() for value in values if str(value or '').strip()]

    def row_anchor(row):
        return next(iter(row_values(row)), '')

    match = re.fullmatch(r'project_components:(\d+):(\d+)', source)
    if match:
        start, end = map(int, match.groups())
        return [str(row.get('اسم المكون') or '').strip()
                for row in _project_component_rows(project_data)[start:end]
                if str(row.get('اسم المكون') or '').strip()]
    match = re.fullmatch(r'financial_report:(\d+):(\d+):(\d+)(?::(\d+):(\d+))?', source)
    if match:
        part_index, start, end = map(int, match.groups()[:3])
        column_start = int(match.group(4)) if match.group(4) is not None else None
        column_end = int(match.group(5)) if match.group(5) is not None else None
        report = model.get('report') if isinstance(model.get('report'), dict) else {}
        parts = report.get('parts') if isinstance(report.get('parts'), list) else []
        if part_index >= len(parts) or not isinstance(parts[part_index], dict):
            return []
        part = _financial_report_part_slice(parts[part_index], start, end, column_start, column_end)
        required = [str(header).strip() for header in (part.get('headers') or []) if str(header or '').strip()]
        required.extend(value for row in (part.get('rows') or []) for value in row_values(row))
        return list(dict.fromkeys(required))
    match = re.fullmatch(r'financial_table:([^:]+):(\d+):(\d+)', source)
    if match:
        table_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
        return list(dict.fromkeys(value for row in rows[start:end] for value in row_values(row)))
    match = re.fullmatch(r'financial_summary:(costs|returns):(\d+):(\d+)', source)
    if match:
        group_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        group_name = 'التكاليف والاستثمار' if group_key == 'costs' else 'مؤشرات العائد والاسترداد'
        rows = _financial_summary_from_report(model).get(group_name, [])[start:end]
        return list(dict.fromkeys(value for row in rows for value in row_values(row)))
    if source == 'financial_indicators':
        summary = _financial_summary_from_report(model)
        return list(dict.fromkeys(value for rows in summary.values() for row in rows for value in row_values(row)))
    return []


def _missing_required_slide_texts(html, slide, project_data):
    visible = html_lib.unescape(re.sub(r'<[^>]+>', ' ', str(html or '')))

    def normalized(value):
        value = str(value or '').replace(',', '').replace('٬', '').replace('\u00a0', ' ')
        return re.sub(r'\s+', ' ', value).strip()

    compact = normalized(visible)
    required = _required_slide_texts(slide, project_data)
    if (slide or {}).get('chart_type'):
        required = [text for text in required if not re.match(r'^-?\d+(?:\.\d+)?$', normalized(text))]
    return [text for text in required
            if normalized(text) and normalized(text) not in compact]


def _financial_chart_source(slide, model):
    """Resolve the exact report/table slice that feeds a financial chart."""
    source = str((slide or {}).get('content_source') or '')
    report = model.get('report') if isinstance(model.get('report'), dict) else {}
    parts = report.get('parts') if isinstance(report.get('parts'), list) else []
    match = re.fullmatch(r'financial_report:(\d+):(\d+):(\d+)(?::(\d+):(\d+))?', source)
    if match:
        part_index, start, end = map(int, match.groups()[:3])
        column_start = int(match.group(4)) if match.group(4) is not None else None
        column_end = int(match.group(5)) if match.group(5) is not None else None
        if part_index < len(parts) and isinstance(parts[part_index], dict):
            return _financial_report_part_slice(parts[part_index], start, end, column_start, column_end)
    match = re.fullmatch(r'financial_chart:[^:]+:(\d+)', source)
    if match:
        part_index = int(match.group(1))
        if part_index < len(parts) and isinstance(parts[part_index], dict):
            return parts[part_index]
    match = re.fullmatch(r'financial_table:([^:]+):(\d+):(\d+)', source)
    if match:
        table_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
        if not rows:
            aliases = {
                'cashflowTable': ('cashflow',),
                'sensitivityTable': ('sensitivity',),
                'sensitivityAssumptionsTable': ('sensitivity',),
            }
            rows = next((tables.get(alias) for alias in aliases.get(table_key, ())
                         if isinstance(tables.get(alias), list)), [])
        return {'rows': rows[start:end]}
    return None
