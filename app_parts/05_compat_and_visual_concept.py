# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COMPATIBILITY ENDPOINTS (Old frontend expects these)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/official-outline', methods=['POST'])
@require_auth
def api_official_outline():
    """Compatibility: Generate outline/titles following tenant slide bounds."""
    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard
    project_data = clean_project_data(request.json.get('projectData', {}))
    print(f"\n[OUTLINE] Generating outline for: {project_data.get('projectName', 'Unknown')}")

    tenant_id = getattr(g, 'tenant_id', None)
    branding = db.get_branding(tenant_id) if tenant_id else {}
    min_s, max_s, default_count = resolve_slide_bounds(branding)
    target_count = max(min_s, min(default_count, max_s))

    if target_count == 1:
        structure_lines = ['1. شريحة غلاف (type="cover")']
    elif target_count == 2:
        structure_lines = ['1. شريحة غلاف (type="cover")', '2. شريحة ختام (type="closing")']
    elif target_count == 3:
        structure_lines = ['1. شريحة غلاف (type="cover")', '2. شريحة فهرس (type="index")', '3. شريحة ختام (type="closing")']
    elif target_count == 4:
        structure_lines = ['1. شريحة غلاف (type="cover")', '2. شريحة فهرس (type="index")', '3. شريحة محتوى (type="content")', '4. شريحة ختام (type="closing")']
    else:
        structure_lines = ['1. شريحة غلاف (type="cover")', '2. شريحة فهرس (type="index")',
                           f'3-{target_count - 2}. شرائح محتوى (type="content")',
                           f'{target_count - 1}. شريحة مود بورد (type="mood_board")',
                           f'{target_count}. شريحة ختام (type="closing")']
    structure_text = '\n'.join(structure_lines)

    prompt = f"""أنت محلل مالي وعقاري ذكي. قم بإنشاء هيكل (outline) عرض تقديمي مخصص بالكامل لمشروع المستخدم.

المطلوب: {target_count} شرائح بالترتيب التالي:
{structure_text}

بيانات المشروع:
{json.dumps(project_data, ensure_ascii=False, indent=2)}

Return ONLY valid JSON: {{"titles": [{{"title": "عنوان الشريحة", "bullets": ["نقطة 1", "نقطة 2"], "type": "content"}}]}}
"""

    try:
        response = call_zai_chat(prompt, f"اكتب الهيكل المكون من {target_count} شريحة.", max_tokens=4000, usage_ctx=_usage_ctx_optional('slide_plan', request.json))
        raw = extract_chat_content(response, "OUTLINE")

        json_match = re.search(r'\{[\s\S]*"titles"[\s\S]*\}', raw)
        if not json_match:
            raise Exception("No JSON found in response")

        parsed = json.loads(json_match.group())
        titles = parsed.get('titles', [])

        if len(titles) < target_count:
            while len(titles) < target_count:
                titles.append({'title': f'شريحة {len(titles)+1}', 'bullets': [], 'type': 'content'})

        if len(titles) > target_count:
            titles = titles[:target_count]

        print(f"[OUTLINE] Generated {len(titles)} slides")
        return jsonify({'success': True, 'titles': titles})

    except Exception as e:
        print(f"[OUTLINE ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/generate-titles', methods=['POST'])
@require_auth
def api_generate_titles():
    """Compatibility: Same as official-outline"""
    return api_official_outline()


@app.route('/api/generate-main-image', methods=['POST'])
@require_permission('generate_images')
def api_generate_main_image():
    """Compatibility: Generate main cover image"""
    data = request.json or {}
    _billing_guard = _require_billing_balance('image_generation')
    if _billing_guard is not None:
        return _billing_guard
    project_data = clean_project_data(data.get('projectData', {}))
    project_name = project_data.get('project_name') or project_data.get('projectName') or 'real-estate project'
    project_type = project_data.get('project_type') or project_data.get('projectType') or 'residential project'
    location = project_data.get('location_address') or project_data.get('location') or 'Saudi Arabia'
    description = project_data.get('project_description') or project_data.get('description') or ''
    prompt = data.get('prompt', '').strip()
    if not prompt:
        prompt = (
            f"Premium architectural hero image for {project_name}, a {project_type} in {location}. "
            f"{description} Modern luxury real-estate photography, elegant materials, cinematic natural light, "
            "no people, no text, no logos, no watermark, 16:9 composition."
        )
    reference = data.get('referenceImage')
    print(f"\n[MAIN IMAGE] Generating cover image...")

    try:
        if reference:
            image = call_image_api_with_reference(reference, prompt, usage_ctx=_usage_ctx_optional('image', data))
        else:
            image = call_image_api(prompt, usage_ctx=_usage_ctx_optional('image', data))

        if image:
            return jsonify({'success': True, 'image': persist_generated_image(image, getattr(g, 'tenant_id', None))})
        else:
            # AI4: Return descriptive Arabic error based on config state
            if not _has_any_openrouter_key(tenant_id=getattr(g, 'tenant_id', None)):
                return jsonify({'success': False, 'error': 'مفتاح OpenRouter غير مُعدّ — يرجى إضافته في ملف .env', 'error_code': 'NO_API_KEY'})
            return jsonify({'success': False, 'error': 'تعذر توليد الصورة — تحقق من مفتاح OpenRouter ورصيده', 'error_code': 'IMAGE_FAILED'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



@app.route('/api/generate-slide-image', methods=['POST'])
@require_permission('generate_images')
def api_generate_slide_image():
    """Compatibility: Generate image for a specific slide"""
    _billing_guard = _require_billing_balance('image_generation')
    if _billing_guard is not None:
        return _billing_guard
    prompt = request.json.get('prompt', '')
    reference = request.json.get('referenceImage')
    print(f"\n[SLIDE IMAGE] Generating...")

    try:
        if reference:
            image = call_image_api_with_reference(reference, prompt, usage_ctx=_usage_ctx_optional('image', request.json))
        else:
            image = call_image_api(prompt, usage_ctx=_usage_ctx_optional('image', request.json))

        if image:
            return jsonify({'success': True, 'image': persist_generated_image(image, getattr(g, 'tenant_id', None))})
        else:
            if not _has_any_openrouter_key(tenant_id=getattr(g, 'tenant_id', None)):
                return jsonify({'success': False, 'error': 'مفتاح OpenRouter غير مُعدّ — يرجى إضافته في ملف .env', 'error_code': 'NO_API_KEY'})
            return jsonify({'success': False, 'error': 'تعذر توليد الصورة — تحقق من مفتاح OpenRouter ورصيده', 'error_code': 'IMAGE_FAILED'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/generate-image', methods=['POST'])
@require_permission('generate_images')
def api_generate_image_single():
    """Compatibility: Generate single image (singular)"""
    _billing_guard = _require_billing_balance('image_generation')
    if _billing_guard is not None:
        return _billing_guard
    prompt = request.json.get('prompt', '')
    reference = request.json.get('referenceImage')
    print(f"\n[IMAGE] Generating single image...")

    try:
        if reference:
            image = call_image_api_with_reference(reference, prompt, usage_ctx=_usage_ctx_optional('image', request.json))
        else:
            image = call_image_api(prompt, usage_ctx=_usage_ctx_optional('image', request.json))

        if image:
            return jsonify({'success': True, 'image': persist_generated_image(image, getattr(g, 'tenant_id', None))})
        else:
            if not _has_any_openrouter_key(tenant_id=getattr(g, 'tenant_id', None)):
                return jsonify({'success': False, 'error': 'مفتاح OpenRouter غير مُعدّ — يرجى إضافته في ملف .env', 'error_code': 'NO_API_KEY'})
            return jsonify({'success': False, 'error': 'تعذر توليد الصورة — تحقق من مفتاح OpenRouter ورصيده', 'error_code': 'IMAGE_FAILED'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



@app.route('/api/get-image-prompts', methods=['POST'])
@require_permission('generate_images')
def api_get_image_prompts():
    """Use GLM 5.1 to generate hyper-realistic, project-tailored architectural prompts for cover and moodboard images."""
    data = request.json or {}
    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard
    project_data = clean_project_data(data.get('projectData', {}))
    project_name = project_data.get('project_name') or project_data.get('projectName') or 'مشروع عقاري'
    project_type = project_data.get('project_type') or project_data.get('projectType') or 'سكني'
    location = project_data.get('location_address') or project_data.get('location') or 'المملكة العربية السعودية'
    try:
        count = max(1, min(20, int(data.get('count', 4))))
    except (TypeError, ValueError):
        count = 4

    formatted_inputs = []
    for k, v in project_data.items():
        if v and not str(k).startswith('_') and str(k) not in ('slides_data', 'plan'):
            formatted_inputs.append(f"- {k}: {v}")
    
    inputs_str = "\n".join(formatted_inputs) if formatted_inputs else f"- اسم المشروع: {project_name}\n- النوع: {project_type}\n- الموقع: {location}"

    sys_prompt = (
        "أنت خبير هندسي ومعماري ومصمم بصري محترف، متخصص في صياغة الأوصاف النصية (Image Prompts) "
        "فائقة الدقة والمطابقة لتصميم المشروع العقاري المدخل بنسبة 80% إلى 99%.\n"
        "المطلوب منك تحليل جميع بيانات ومعلومات المشروع المدخلة أدناه لإنشاء أوصاف عربية تفصيلية ومحترفة:\n"
        "1. cover_prompt: وصف تفصيلي للغلاف يصف الواجهة، المواد (مثل الحجر، الرخام، الزجاج)، الطوابق، الإضاءة، الشارع والمحيط الجغرافي الواقعي بدقة عالية.\n"
        "2. moodboard_prompts: قائمة بعدد المود بورد المطلوب تشمل لقطات واجهة رئيسية، منظور أيمن، منظور أيسر، لقطة جوية درون، وتفاصيل معمارية.\n"
        "يجب أن تعيد النتيجة بصيغة JSON حصرية فقط دون أي مقدمات أو شروحات:\n"
        '{\n  "cover_prompt": "...",\n  "moodboard_prompts": ["...", "..."]\n}'
    )

    user_msg = (
        f"بيانات ومواصفات المشروع الكاملة:\n"
        f"{inputs_str}\n"
        f"- عدد صور المود بورد المطلوبة: {count}\n\n"
        f"اكتب الأوصاف بدقة معمارية عالية جداً ومطابقة لواقع وتفاصيل هذا المشروع."
    )

    try:
        res = call_zai_chat(sys_prompt, user_msg, temperature=0.7, max_tokens=2500, usage_ctx=_usage_ctx_optional('image', data))
        if res and 'choices' in res and res['choices']:
            content = res['choices'][0]['message']['content'].strip()
            if '```json' in content:
                content = content.split('```json')[1].split('```')[0].strip()
            elif '```' in content:
                content = content.split('```')[1].split('```')[0].strip()
            
            parsed = json.loads(content)
            if 'cover_prompt' in parsed and 'moodboard_prompts' in parsed:
                moodboard_prompts = parsed['moodboard_prompts']
                while len(moodboard_prompts) < count:
                    moodboard_prompts.append(f"منظور معماري إضافي لمشروع {project_name} رقم {len(moodboard_prompts)+1}")
                return jsonify({
                    'success': True,
                    'cover_prompt': parsed['cover_prompt'],
                    'moodboard_prompts': moodboard_prompts[:count],
                    'engine': GLM_MODEL
                })
    except Exception as e:
        print(f"[IMAGE PROMPTS GLM ERROR] {e}. Falling back to rich template generator...")

    # Rich fallback generator incorporating all available fields
    arch_style = project_data.get('architectural_style') or project_data.get('style') or 'حديث وعصري'
    materials = project_data.get('materials') or project_data.get('finishes') or 'حجر فاخر، واجهات زجاجية، وألومنيوم'
    floors = project_data.get('floors_count') or project_data.get('floors') or ''
    floors_str = f"يتكون من {floors} أدوار، " if floors else ""
    desc = project_data.get('project_description') or project_data.get('description') or ''
    desc_str = f" التفاصيل: {desc}." if desc else ""

    cover_prompt = f"تصوير معماري احترافي فائق الواقعية لمشروع {project_name} ({project_type}) في {location}. المبنى {floors_str}بطراز {arch_style} واستخدام {materials}.{desc_str} إضاءة دافئة، سماء صافية، تصوير سينمائي عالي الجودة بدون نصوص."

    base_prompts = [
        f"لقطة رئيسية لواجهة مشروع {project_name} في {location}، مبنى {project_type} {floors_str}بطراز {arch_style} وإضاءة معماري مميزة",
        f"منظور جانبي أيمن لواجهة {project_name} يبرز التفاصيل المعمارية وخامات {materials}",
        f"منظور جانبي أيسر لمبنى {project_name} يوضح جماليات التصميم والفتحات المعمارية",
        f"لقطة جوية بارافيناميكية لمشروع {project_name} تظهر المبنى من الأعلى والمحيط العام في {location}",
        f"تفاصيل معمارية دقيقة للمدخل الرئيسي والبهو الخارجي لمشروع {project_name}",
        f"لقطة مسائية ليلية لمشروع {project_name} توضح إضاءة الواجهات الخارجية في وقت الغروب",
        f"تصميم داخلي فاخر لبهو الاستقبال والاستراحة في {project_name}",
        f"المساحات الخضراء والحدائق المحيطة بمبنى {project_name}"
    ]

    moodboard_prompts = base_prompts[:count]
    while len(moodboard_prompts) < count:
        moodboard_prompts.append(f"منظور معماري إضافي لمشروع {project_name} رقم {len(moodboard_prompts)+1}")

    return jsonify({
        'success': True,
        'cover_prompt': cover_prompt,
        'moodboard_prompts': moodboard_prompts,
        'engine': 'fallback'
    })
