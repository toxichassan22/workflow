

def _build_designer_attached_slide_html(image_url, title='', caption='', branding=None):
    """Build a standalone slide that shows one attached image full-width, no model needed."""
    safe_url = html_lib.escape(str(image_url or ''), quote=True)
    safe_title = html_lib.escape(str(title or 'صورة مرفقة')[:160])
    safe_caption = html_lib.escape(str(caption or '')[:300])
    primary = '#0f2a44'
    try:
        primary = str((branding or {}).get('primary_color') or primary)
    except Exception:
        pass
    caption_block = (
        f'<div style="font-size:15px;color:#4a5568;line-height:1.9;text-align:center;max-width:900px;">{safe_caption}</div>'
        if safe_caption else ''
    )
    return (
        '<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;box-sizing:border-box;'
        'overflow:hidden;background:#ffffff;display:flex;flex-direction:column;align-items:center;'
        'justify-content:center;gap:18px;padding:48px;">'
        f'<div style="font-size:30px;font-weight:800;color:{primary};text-align:center;">{safe_title}</div>'
        f'<img src="{safe_url}" alt="" style="max-width:960px;max-height:460px;object-fit:contain;border-radius:14px;">'
        f'{caption_block}</div>'
    )


def _is_watermark_removal_instruction(instruction):
    """Check whether an edit instruction asks to remove the watermark itself."""
    normalized = normalize_arabic_digits_py(str(instruction or '').strip().lower())
    if not re.search(r'(?:احذف|حذف|امسح|إزالة|ازالة|ازل|شيل|اخف|إخفاء|اخفاء|خف|عطل|عطّل|تعطيل|لغاء\s*(?:ال)?تفعيل|ايقاف|إيقاف)', normalized):
        return False
    return bool(re.search(r'(?:watermark|الوترمارك|الووترمارك|العلامة|علامة\s*مائي|لوجو|شعار)', normalized))


def _designer_deterministic_plan(message, slides, current_index, target_indexes):
    """Handle unambiguous structural commands without spending a planner turn first."""
    if not message or not slides:
        return None
    normalized = normalize_arabic_digits_py(str(message).strip().lower())
    numbers = [idx + 1 for idx in (target_indexes or [])]

    if is_watermark_request(message):
        is_remove = bool(re.search(r'(?:احذف|حذف|امسح|إزالة|ازالة|ازل|شيل|اخف|إخفاء|اخفاء|خف|عطّل|عطل|تعطيل|لغاء\s*(?:ال)?تفعيل|ايقاف|إيقاف)', normalized))
        only_white = bool(re.search(r'(?:البيضاء|البيضه|الابيض|الأبيض|white|الفاتحة|الفاتحه)', normalized))
        all_match = any(kw in normalized for kw in ('كل', 'جميع', 'كافة', 'العرض كامل', 'العرض كله', 'الشرائح كلها', 'الشرايح كلها'))
        # No scope named: the current slide only. "All" needs an explicit كل/جميع.
        target_mode = 'all' if all_match else ('indexes' if numbers else 'current')
        action_tool = 'remove_watermark' if is_remove else 'apply_watermark'
        # «إظهار» names visibility, never size: only an explicit bigger/clearer
        # request grows the mark.
        size_up = bool(re.search(r'(?:أكبر|اكبر|كبّر|كبر|واضح|واضحه|أوضح|اوضح|ظاهر|أجلى|اجلى|bigger|\bbig\b|\bclear\b|clearer)', normalized))
        size_down = bool(re.search(r'(?:أصغر|اصغر|صغّر|صغر|أخف|اخف|خفيف|خفيفه|شفاف|أفتح|افتح|smaller|\bsmall\b|\bfaint\b)', normalized))
        if size_up and not size_down:
            wm_opacity, wm_width = 0.10, 640
        elif size_down and not size_up:
            wm_opacity, wm_width = 0.03, 400
        else:
            wm_opacity, wm_width = 0.045, 480
        if is_remove:
            resp_text = 'سأنفذ حذف العلامة المائية مع الحفاظ على كامل محتوى الشرائح.'
        elif size_up and not size_down:
            resp_text = 'سأجعل العلامة المائية أكبر وأوضح في خلفية الشرائح مع الحفاظ التام على النصوص والتصميم.'
        elif only_white:
            resp_text = 'سأضيف العلامة المائية المعتمدة في خلفية الشرائح البيضاء مع الحفاظ التام على النصوص والتصميم.'
        else:
            resp_text = 'سأضيف العلامة المائية المعتمدة في خلفية الشرائح المحددة بأناقة وتناسق بصري تام.'
        return {
            'response': resp_text,
            'actions': [{
                'tool': action_tool,
                'params': {
                    'target': target_mode,
                    'indexes': numbers if target_mode == 'indexes' else [],
                    'only_white': only_white,
                    'opacity': wm_opacity,
                    'width_px': wm_width,
                },
            }],
        }

    is_map_reload = bool(
        re.search(r'(?:إعادة|اعادة|اعاده|أعد|اعد|عيد|رجع|رجّع|حدّث|حدث|تحديث|جدّد|جدد|استبدل|استبدال)', normalized)
        and re.search(r'(?:خريطة|الخريطة|الخريطه|map)', normalized)
    )
    if is_map_reload:
        number = numbers[0] if numbers else current_index + 1
        index = number - 1
        map_type = _canonical_map_type_for_slide(slides[index]) if 0 <= index < len(slides) else ''
        if map_type:
            return {
                'response': f'سأحدّث خريطة الشريحة رقم {number} من أحدث نسخة محفوظة، دون طلب خريطة جديدة من جوجل.',
                'actions': [{'tool': 'insert_canonical_map', 'params': {
                    'target': 'indexes', 'indexes': [number], 'map_type': map_type,
                    'refresh': True,
                }}],
            }

    # Creative, redesign, or multi-slide generative requests belong to the AI agent
    creative_patterns = (
        r'(?:اعد|أعد|اعادة|إعادة)\s*(?:توليد|تصميم|صياغة|بناء|ابتكار)',
        r'(?:صمم|ابتكر|طور|تطوير|حدث|تحديث)',
        r'(?:مصمم[ةه]|قوي[ةه]|بصري[ااً]|ابداع|فخم|فخم[ةه]|عصري|احترافي)',
        r'(?:اكثر|أكثر)\s*من\s*شريح[ةه]',
        r'علي\s*اكثر|على\s*أكثر|على\s*اكثر|علي\s*أكثر',
        r'شرايح\s*متعدد[ةه]|شرائح\s*متعدد[ةه]',
        r'(?:تحسين|تطوير|تجديد|ابتكار)\s*(?:التصميم|الشكل|المظهر)',
    )
    if any(re.search(pat, normalized) for pat in creative_patterns):
        return None

    if re.search(r'(?:احذف|حذف|امسح|إزالة|ازالة)\s*(?:الشريحة|شريحة|السلايد|سلايد)', normalized):
        targets = sorted(set(numbers or [current_index + 1]), reverse=True)
        return {
            'response': 'سأنفذ حذف الشرائح المحددة مع الحفاظ على ترتيب بقية العرض.',
            'actions': [{'tool': 'delete_slide', 'params': {'slide_number': number}} for number in targets],
        }

    if re.search(r'(?:كرر|تكرار|انسخ|استنسخ|استنساخ|دبلر)\s*(?:الشريحة|شريحة|السلايد|سلايد)', normalized):
        number = numbers[0] if numbers else current_index + 1
        return {
            'response': f'سأنشئ نسخة من الشريحة رقم {number} مع إبقاء النسخة الأصلية.',
            'actions': [{'tool': 'duplicate_slide', 'params': {'slide_number': number}}],
        }

    move_match = re.search(
        r'(?:انقل|حرك|غيّر\s*ترتيب|غير\s*ترتيب)\s*(?:الشريحة|شريحة|السلايد|سلايد)?\s*(\d+)\s*'
        r'(?:إلى|الى|لمكان|مكان|لتصبح|لتكون)\s*(?:الشريحة|شريحة|السلايد|سلايد)?\s*(\d+)',
        normalized,
    )
    if move_match:
        from_number, to_number = int(move_match.group(1)), int(move_match.group(2))
        return {
            'response': f'سأنقل الشريحة رقم {from_number} إلى الموضع رقم {to_number}.',
            'actions': [{'tool': 'reorder_slides', 'params': {
                'from_index': from_number, 'to_index': to_number,
            }}],
        }

    if designer_chat_reliability.is_split_request(message):
        detected = detect_slide_indexes_from_message_py(message, slides)
        number = numbers[0] if numbers else ((detected[0] + 1) if detected else current_index + 1)
        return {
            'response': f'سأقسم محتوى الشريحة رقم {number} إلى أجزاء متوازنة مع الحفاظ على كامل المحتوى دون فقد أي تفاصيل.',
            'actions': [{'tool': 'split_slide', 'params': {'slide_number': number, 'instruction': message}}],
        }
    return None


def _designer_team_logo_search_text(value):
    """Normalize a team name or chat text for explicit logo matching."""
    normalized = normalize_arabic_digits_py(str(value or '').casefold())
    normalized = re.sub(r'[^\w\u0600-\u06ff]+', ' ', normalized, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', normalized).strip()


def _designer_company_logo_requested(message):
    """Recognize an explicit company-brand request before consulting older team-logo context.

    Only the definite «الشركة» or the tenant's own proper nouns count as the company.
    A bare «شركة» also starts team entity names («شركة الأصالة») and must stay on the
    team-logo path when the message names that entity.
    """
    text = _designer_team_logo_search_text(message)
    has_logo_word = bool(re.search(r'(?:logo|لوجو|شعار|علامة\s*تجارية)', text, flags=re.IGNORECASE))
    has_company_word = bool(re.search(
        r'(?:الشركة|company|branding|بوابة\s*الرؤية|الرؤية\s*للتطوير)',
        text, flags=re.IGNORECASE,
    ))
    return has_logo_word and has_company_word


def _designer_team_logo_context(creative_images):
    """Describe the selected team logos to the designer without conflating them with branding."""
    members = creative_images.get('team_members') if isinstance(creative_images, dict) else []
    lines = []
    for index, member in enumerate(members or [], 1):
        if not isinstance(member, dict):
            continue
        name = str(member.get('name') or f'الجهة {index}').strip()
        role = str(member.get('role') or '').strip()
        token = f'##TEAM_LOGO_{index}##'
        suffix = f' — {role}' if role else ''
        if member.get('logo'):
            lines.append(f'- {name}{suffix}: الشعار متوفر؛ استخدم {token} عند طلب شعار هذه الجهة.')
        else:
            lines.append(f'- {name}{suffix}: لا يوجد شعار مرفوع؛ لا تنشئ بديلاً.')
    if not lines:
        return 'لا توجد شعارات جهات فريق عمل متاحة في هذا المشروع.'
    return '\n'.join(lines)


def _find_designer_team_logo_request(message, history, creative_images):
    """Resolve a named team entity in a logo request to its exact TEAM_LOGO token.

    The current message alone must carry logo intent (شعار/لوجو/logo). Older turns
    only resolve *which* entity a follow-up means («لم تتم إضافة اللوجو حل المشكلة»),
    so a later «أضف وصفاً للصور» or «أعد تصميم الشريحة» never inherits a previous
    logo request. A description/caption request (وصف/شرح/تعليق) and a generic image
    request (صورة/تصميم/توليد) are not logo requests.
    """
    if _designer_company_logo_requested(message):
        return None
    members = creative_images.get('team_members') if isinstance(creative_images, dict) else []
    if not isinstance(members, list) or not members:
        return None
    current_search = _designer_team_logo_search_text(message)
    if not re.search(r'(?:logo|لوجو|شعار|علامة\s*تجارية)', current_search, flags=re.IGNORECASE):
        return None
    with_logo = [
        (index, member)
        for index, member in enumerate(members, 1)
        if isinstance(member, dict) and member.get('logo')
    ]
    if not with_logo:
        return None
    for index, member in with_logo:
        name = str(member.get('name') or '').strip()
        name_key = _designer_team_logo_search_text(name)
        if name_key and len(name_key) >= 3 and name_key in current_search:
            return {
                'index': index,
                'name': name,
                'role': str(member.get('role') or '').strip(),
                'logo': str(member.get('logo') or '').strip(),
                'token': f'##TEAM_LOGO_{index}##',
            }
    # Follow-up without repeating the name («ضيف الشعار»، «لم تتم إضافة اللوجو حلها»):
    # resolve to the most recently named entity in earlier user turns.
    user_turns = [
        str(item.get('content') or '')
        for item in history if isinstance(item, dict) and item.get('role') == 'user'
    ]
    for past in reversed(user_turns):
        past_search = _designer_team_logo_search_text(past)
        if not past_search:
            continue
        for index, member in with_logo:
            name = str(member.get('name') or '').strip()
            name_key = _designer_team_logo_search_text(name)
            if name_key and len(name_key) >= 3 and name_key in past_search:
                return {
                    'index': index,
                    'name': name,
                    'role': str(member.get('role') or '').strip(),
                    'logo': str(member.get('logo') or '').strip(),
                    'token': f'##TEAM_LOGO_{index}##',
                }
    return None


def _inject_team_logo_fallback(html, team_logo, team_index):
    """Keep a named team logo visible if the model returned valid HTML without inserting it."""
    if not html or not team_logo or team_logo in html:
        return html
    safe_url = html_lib.escape(str(team_logo), quote=True)
    markup = (
        f'<div data-team-logo-placement="{int(team_index)}" '
        'style="position:absolute;left:44px;top:94px;width:188px;height:72px;'
        'display:flex;align-items:center;justify-content:center;z-index:4;overflow:hidden;'
        'padding:8px 12px;box-sizing:border-box;background:#0c2340;border-radius:8px;">'
        f'<img class="team-logo" src="{safe_url}" alt="" '
        'style="width:100%;height:100%;max-width:100%;max-height:100%;object-fit:contain;object-position:center center;">'
        '</div>'
    )
    closing = re.search(r'</div>\s*$', html, flags=re.IGNORECASE)
    if not closing:
        return html
    return html[:closing.start()] + markup + html[closing.start():]


def _inject_company_logo_panel_fallback(html, logo_url):
    """Put the company logo in the right content panel when the model omitted the requested move."""
    if not html:
        return html
    existing_logo_tags = [
        tag for tag in re.findall(r'<img\b[^>]*>', html, flags=re.IGNORECASE)
        if logo_url and logo_url in tag and 'presentation-chrome-logo' not in tag.lower()
    ]
    if existing_logo_tags or 'data-company-logo-placement="right-panel"' in html:
        return html
    source = html_lib.escape(str(logo_url or '##LOGO##'), quote=True)
    markup = (
        '<div data-company-logo-placement="right-panel" '
        'style="position:absolute;right:54px;top:92px;width:180px;height:62px;'
        'display:flex;align-items:center;justify-content:center;z-index:6;overflow:hidden;'
        'padding:6px 10px;box-sizing:border-box;background:#0c2340;border-radius:8px;">'
        f'<img class="company-content-logo" src="{source}" alt="" '
        'style="width:100%;height:100%;max-width:100%;max-height:100%;object-fit:contain;object-position:center center;">'
        '</div>'
    )
    closing = re.search(r'</div>\s*$', html, flags=re.IGNORECASE)
    if not closing:
        return html
    return html[:closing.start()] + markup + html[closing.start():]


def _find_component_reference_image(component_query, project_data, creative_images=None):
    """Search project and creative data for reference images belonging to a component or query."""
    if not component_query:
        return []
    query_str = str(component_query).strip().lower()
    creative = _designer_creative_images(project_data, creative_images) if isinstance(project_data, dict) else (creative_images or {})
    references = []

    # 1. Search interior components in creative_images and project_data
    int_comps = creative.get('interior_components') or (project_data.get('interior_components') if isinstance(project_data, dict) else []) or (project_data.get('interiorComponents') if isinstance(project_data, dict) else [])
    if isinstance(int_comps, list):
        for comp in int_comps:
            if not isinstance(comp, dict):
                continue
            name = str(comp.get('name') or '').strip().lower()
            if name and (name in query_str or query_str in name):
                for img in comp.get('images') or []:
                    uri = img.get('data_uri') or img.get('url') or img.get('file_path') or (img if isinstance(img, str) else '')
                    if uri and uri not in references:
                        references.append(uri)

    # 2. Search project components list
    proj_comps = (project_data.get('project_components') or project_data.get('components') or project_data.get('components_data')) if isinstance(project_data, dict) else []
    if isinstance(proj_comps, list):
        for comp in proj_comps:
            if not isinstance(comp, dict):
                continue
            name = str(comp.get('name') or comp.get('title') or '').strip().lower()
            if name and (name in query_str or query_str in name):
                for key in ('image', 'image_url', 'reference_image', 'data_uri'):
                    val = comp.get(key)
                    if val and val not in references:
                        references.append(val)

    # 3. Search moodboard / exterior
    moodboard = creative.get('moodboard') or (project_data.get('moodboard') if isinstance(project_data, dict) else [])
    moodboard_meta = creative.get('moodboard_meta') or (project_data.get('moodboard_meta') if isinstance(project_data, dict) else [])
    if isinstance(moodboard, list) and isinstance(moodboard_meta, list):
        for idx, img in enumerate(moodboard):
            meta = moodboard_meta[idx] if idx < len(moodboard_meta) and isinstance(moodboard_meta[idx], dict) else {}
            lbl = str(meta.get('label') or meta.get('caption') or '').strip().lower()
            if lbl and (lbl in query_str or query_str in lbl):
                if img and img not in references:
                    references.append(img)

    # 4. Search plans
    plans = creative.get('plans') or (project_data.get('plans') if isinstance(project_data, dict) else [])
    plan_meta = creative.get('plan_meta') or (project_data.get('plan_meta') if isinstance(project_data, dict) else [])
    if isinstance(plans, list) and isinstance(plan_meta, list):
        for idx, img in enumerate(plans):
            meta = plan_meta[idx] if idx < len(plan_meta) and isinstance(plan_meta[idx], dict) else {}
            lbl = str(meta.get('title') or meta.get('name') or meta.get('description') or '').strip().lower()
            if lbl and (lbl in query_str or query_str in lbl):
                if img and img not in references:
                    references.append(img)

    return references[:VISUAL_CONCEPT_MAX_REFERENCE_IMAGES]


def _build_designer_section_and_asset_context(slides, project_data, current_index, creative_images=None):
    """Build full situational and section asset audit context for Sol the designer."""
    slides_count = len(slides)
    cur_slide = slides[current_index] if 0 <= current_index < slides_count and isinstance(slides[current_index], dict) else {}
    cur_title = cur_slide.get('title', f'شريحة {current_index + 1}')

    # Audit map usage across slides
    map_usage = {
        '##MAP_OVERVIEW##': 0,
        '##MAP_ACCESS##': 0,
        '##MAP_CATCHMENT##': 0,
        '##MAP_LANDMARKS##': 0,
    }
    for s in slides:
        html = s.get('html', '') if isinstance(s, dict) else ''
        for k in map_usage:
            if k in html:
                map_usage[k] += 1

    audit_lines = [
        f"## الموقف التنفيذي وتدقيق الأصول المتاحة للعرض ({slides_count} شريحة):",
        f"- الشريحة الحالية المعروضة أمام المستخدم: [{current_index + 1}] '{cur_title}'",
        "- حالة الخرائط الأربع الرئيسية في العرض:",
        f"  1. خريطة النظرة العامة (##MAP_OVERVIEW##): مستخدمة {map_usage['##MAP_OVERVIEW##']} مرة",
        f"  2. خريطة شبكة الطرق والوصول (##MAP_ACCESS##): مستخدمة {map_usage['##MAP_ACCESS##']} مرة",
        f"  3. خريطة النطاق الجغرافي واستيعاب المنطقة (##MAP_CATCHMENT##): مستخدمة {map_usage['##MAP_CATCHMENT##']} مرة",
        f"  4. خريطة المعالم الحيوية القريبة (##MAP_LANDMARKS##): مستخدمة {map_usage['##MAP_LANDMARKS##']} مرة",
        "- تنبيه الخرائط: يمكنك استخدام أي من هذه الخرائط الأربع في أي شريحة من العرض بحرية تامة بتضمين الرمز المقابل.",
    ]

    audit_lines.extend([
        "- تمييز الشعارات: ##LOGO## للشركة فقط، ##PROJECT_LOGO## لشعار المشروع فقط، وشعارات جهات فريق العمل تستخدم ##TEAM_LOGO_N## حسب ترتيب القائمة التالية. ممنوع إدراج أي شعار إلا إذا طلب المستخدم ذلك صراحة بكلمة شعار أو لوجو أو علامة تجارية في رسالته الحالية؛ فالصورة والوصف والشعار ثلاثة أشياء مختلفة: الوصف نص يضاف لصور موجودة، والصورة توليد معماري جديد، والشعار رمز جهة مرفوع.",
        "## شعارات جهات فريق العمل المتاحة:",
        _designer_team_logo_context(creative_images),
    ])

    # Components list
    comps = (project_data.get('interior_components') or project_data.get('components') or []) if isinstance(project_data, dict) else []
    if isinstance(comps, list) and comps:
        comp_names = [str(c.get('name') or c.get('title') or '').strip() for c in comps if isinstance(c, dict) and (c.get('name') or c.get('title'))]
        if comp_names:
            audit_lines.append(f"- مكونات المشروع المسجلة: {', '.join(comp_names[:12])}")

    return "\n".join(audit_lines)


def _sanitize_designer_output(html):
    """Sanitize designer output strictly according to platform quality and compliance rules (Pillar 7).
    
    1. Zero emojis (stripped).
    2. Zero icon fonts, icon glyphs, or decorative SVGs.
    3. Replaces direction arrows with explicit Arabic words.
    4. Strips any how-to instructional hints.
    5. Ensures standard slide container bounds (1280x720, overflow:hidden).
    """
    if not html:
        return html

    # Replace arrow glyphs with explicit Arabic words
    arrow_replacements = {
        '\u2191': 'أعلى',
        '\u2193': 'أسفل',
        '\u2192': 'يمين',
        '\u2190': 'يسار',
        '\u25B2': 'أعلى',
        '\u25BC': 'أسفل',
        '\u25BA': 'يمين',
        '\u25C4': 'يسار',
        '\u27A4': 'يمين',
        '\u279C': 'يمين',
        '\u2B06': 'أعلى',
        '\u2B07': 'أسفل',
        '\u27A1': 'يمين',
        '\u2B05': 'يسار',
    }
    for arrow_char, ar_word in arrow_replacements.items():
        if arrow_char in html:
            html = html.replace(arrow_char, ar_word)

    # Strip emojis and decorative icon markup
    html = slide_engine._strip_presentation_icons(html)

    # Strip instructional how-to phrasing if any was generated
    how_to_patterns = [
        r'اضغط\s+على\s+[^<]+',
        r'اضغط\s+هنا\s+[^<]*',
        r'اختر\s+من\s+القائمة\s+[^<]*',
        r'راجع\s+أولاً\s+[^<]*',
        r'يرجى\s+مراجعة\s+[^<]*',
        r'قم\s+بالضغط\s+[^<]*',
    ]
    for pat in how_to_patterns:
        html = re.sub(pat, '', html, flags=re.IGNORECASE)

    return html


def _is_land_boundary_diagram_slide(title=None, content_source=None, html=None):
    """Detect the deterministic land-boundary diagram slide.

    It is the only slide the system rebuilds from documented land facts
    (content_source == 'land_boundary_diagram'), so the designer model must
    receive those facts explicitly — otherwise it claims success without any
    visible change.
    """
    if str(content_source or '').strip() == 'land_boundary_diagram':
        return True
    title_text = str(title or '')
    if 'مخطط اتجاهي' in title_text or 'حدود الأرض' in title_text:
        return True
    html_text = str(html or '')
    if 'data-boundary-diagram' in html_text or 'data-boundary-direction' in html_text:
        return True
    return False


def _designer_boundary_facts_note(project_data):
    """Render the documented boundary facts for the designer-chat prompt."""
    try:
        data = slide_engine._extract_land_boundary_diagram_data(
            project_data if isinstance(project_data, dict) else {}
        )
    except Exception:
        return ''
    if not isinstance(data, dict):
        return ''
    lines = []
    for key, label in (('north', 'الشمال'), ('south', 'الجنوب'),
                       ('east', 'الشرق'), ('west', 'الغرب')):
        raw_item = data.get(key)
        item = raw_item if isinstance(raw_item, dict) else {}
        length = str(item.get('length') or '').strip() or 'غير موثق'
        neighbour = str(item.get('street_name') or item.get('description') or '').strip() or 'غير موثق'
        width = str(item.get('street_width') or '').strip() or 'غير موثق'
        facade = 'واجهة على شارع' if item.get('is_facade') else 'جار'
        lines.append(f'- {label}: طول الحد {length}، البيان الموثق {neighbour}، عرض الشارع {width}، التصنيف {facade}')
    facades_summary = str(data.get('facades_summary') or '').strip() or 'غير موثق'
    key_view = str(data.get('key_view') or '').strip() or 'غير موثق'
    return (
        "\n\n## بيانات الحدود الموثقة لهذه الشريحة (المصدر الوحيد — ممنوع الاختراع)\n"
        + "\n".join(lines)
        + f"\n- ملخص الواجهات الموثق: {facades_summary}"
        + f"\n- الجهة المميزة الموثقة: {key_view}"
        + "\nقواعد ملزمة عند تعديل شريحة مخطط الحدود:"
        + "\n- المواضع الجغرافية ثابتة: الشمال أعلى، الجنوب أسفل، الشرق والغرب على الجانبين."
        + " لا تبدل الاتجاهات ولا تنقل بطاقة من موضعها."
        + "\n- حافظ على وسم data-boundary-direction لكل اتجاه كما هو."
        + "\n- اعرض طول كل حد ووصف الشارع أو الجار وعرض الشارع من البيانات أعلاه فقط."
        + " أي بيان مكتوب «غير موثق» اترك خانته كما هي ولا تخترع له نصاً."
        + "\n- إن طلب المستخدم إضافة بيان غير موجود في القائمة أعلاه، نفذ ما يمكن تنفيذه"
        + " من تنسيق، واذكر في الرد بوضوح أن البيان المطلوب غير موثق في بيانات المشروع"
        + " بدل ادعاء إضافته."
    )


def _designer_project_context(project_data, creative_images=None, tenant_id=None, max_deck_chars=60000):
    """Give the planner and every slide edit the complete project source of truth."""
    source = project_data if isinstance(project_data, dict) else {}
    parts = [
        "## ملف بيانات المشروع الكامل — مصدر الحقيقة الملزم",
        "هذه أحدث بيانات متاحة لملف المشروع. استخدم كل حقل مطلوب كما هو، ولا تقل إن المعلومة غير موجودة قبل البحث في هذا الملف كاملًا. إذا ورد رابط Google Maps فهو رابط المشروع الفعلي ويمكن إدراجه نصيًا عند طلب المستخدم.",
        designer_chat_context.build_project_context(source, creative_images, tenant_id),
    ]
    for note in (
        _designer_boundary_facts_note(source),
        slide_engine._timeline_data_note(source),
        slide_engine._financial_data_note(source),
    ):
        if str(note or '').strip():
            parts.append(str(note).strip())
    asset_note = _get_images_info(creative_images or {}, source)
    if str(asset_note or '').strip():
        parts.append("## الأصول والخرائط والصور المتاحة فعليًا\n" + asset_note.strip())
    deck_context = source.get('_designer_deck_context')
    if deck_context:
        if len(deck_context) <= max_deck_chars:
            parts.append('## العرض الحالي الكامل: مرجع للسياق وليس إذنًا بتعديل الشرائح الأخرى\n' + deck_context)
        else:
            print(f"[DESIGNER-CHAT] skipping oversized deck context in planner ({len(deck_context)} chars > {max_deck_chars})")
    return '\n\n'.join(parts)


def _is_openrouter_credit_error(exc_or_msg):
    """True when an LLM failure is strictly due to lack of credits/funds or key limits in OpenRouter."""
    text = str(exc_or_msg or '').lower()
    if not text:
        return False
    if 'insufficient_credits' in text or 'user credits exceeded' in text or 'key has insufficient credits' in text:
        return True
    if 'key limit exceeded' in text or 'monthly limit' in text or 'credit limit' in text or 'key limit' in text:
        return True
    if '402' in text and any(m in text for m in ('credit', 'balance', 'payment required', 'insufficient')) and not ('>' in text or 'can only afford' in text or 'tokens limit' in text):
        return True
    if '403' in text and any(m in text for m in ('limit', 'key', 'credit', 'monthly')):
        return True
    return False


def _is_designer_prompt_token_error(exc_or_msg):
    """True when an LLM failure is a prompt/context token limit, not a real model or credit error."""
    text = str(exc_or_msg or '').lower()
    if not text:
        return False
    if _is_openrouter_credit_error(text):
        return False
    markers = (
        'prompt tokens limit exceeded',
        'prompt token',
        'tokens limit exceeded',
        'context length',
        'context_length',
        'max prompt',
        'prompt is too long',
        'prompt too large',
        'input tokens',
        'too many tokens',
    )
    if any(marker in text for marker in markers):
        return True
    # OpenRouter quotes the cap as [402] / 402 with a token comparison (427914 > 307449) or "can only afford".
    if '402' in text and ('>' in text or 'can only afford' in text or 'tokens' in text):
        return True
    return False


def _resolve_deterministic_table_targets(message, data, slides, current_index, is_all_slides_request=False):
    """Resolve 0-based slide indexes for a supported table row/column delete without an LLM.

    Mirrors designer_chat_targets.prepare_actions scoping: an explicit UI target wins,
    otherwise an explicit slide number in the message wins, otherwise the current preview
    slide is the target. Raises designer_chat_targets.TargetError when the scope is invalid
    so the caller falls through to the planner instead of editing the wrong slide.
    """
    count = len(slides) if isinstance(slides, list) else 0
    if count <= 0:
        raise designer_chat_targets.TargetError('لا توجد شرائح مفتوحة لتنفيذ الطلب')
    if is_all_slides_request:
        return list(range(count))
    payload = data if isinstance(data, dict) else {}
    if payload.get('target') == 'current' or payload.get('scope') == 'current':
        return [designer_chat_targets.slide_number(current_index + 1, count) - 1]
    explicit_raw = payload.get('indexes')
    if isinstance(explicit_raw, list) and explicit_raw:
        return [designer_chat_targets.slide_number(n, count) - 1 for n in explicit_raw]
    explicit_numbers = designer_chat_targets.explicit_slide_numbers(message)
    if explicit_numbers:
        return [designer_chat_targets.slide_number(n, count) - 1 for n in explicit_numbers]
    return [designer_chat_targets.slide_number(current_index + 1, count) - 1]


def _build_designer_slim_planner_prompt(branding, training_note, watermark_note, summary,
                                        target_html_snippets, project_facts_brief,
                                        all_note, memory_note, history_note, focus_note,
                                        explicit_scope_note, audit_note=''):
    """Small planner prompt used only after the full prompt exceeds the model token cap.

    The full planner carries the unabridged project snapshot plus every slide HTML verbatim,
    which grows past 400k prompt tokens on real decks. The planner only decides the tool and
    the target slides, so the retry carries the slide index list, the target slide HTML only,
    and the brief section-grouped facts instead of the full deck.
    """
    targets_note = ''
    if target_html_snippets:
        joined = '\n\n'.join(target_html_snippets)
        # Keep the retry bounded even when one table slide is itself large.
        targets_note = '\n\n## الشرائح المستهدفة (HTML مختصر للقرار فقط)\n' + joined[:60000]
    facts_note = ''
    if str(project_facts_brief or '').strip():
        facts_note = '\n\n## حقائق المشروع المختصرة\n' + str(project_facts_brief)[:40000]
    audit_part = f'\n\n{audit_note}' if str(audit_note or '').strip() else ''
    return f"""{build_design_rules(branding)}{training_note}

{watermark_note}
{facts_note}{targets_note}
أنت Sol، كبير المصممين. حدّد الأداة والشرائح المستهدفة فقط وأعد JSON فقط:
{{"response":"رسالة عربية تشرح ما ستفعله جراحياً", "actions":[{{"tool":"edit_slides|delete_slide|duplicate_slide|reorder_slides|split_slide|merge_slides|create_slide|ask|chat_only", "params":{{}}}}]}}
- حذف صف أو عمود من جدول داخل شريحة هو edit_slides فقط وليس delete_slide. لا تختر delete_slide إلا إذا ذكر المستخدم كلمة شريحة/سلايد صراحة مع الحذف.
{all_note}
قائمة الشرائح الحالية في العرض:
{json.dumps(summary, ensure_ascii=False)}{audit_part}
{memory_note}{history_note}{focus_note}{explicit_scope_note}"""


_TABLE_PRECHECK_ARABIC_REASONS = {
    'column_name_not_found': 'اسم العمود غير موجود في ترويسة الجدول',
    'row_name_not_found': 'اسم الصف غير موجود في الجدول',
    'column_number_out_of_range': 'رقم العمود خارج الجدول',
    'row_number_out_of_range': 'رقم الصف خارج الجدول',
    'table_not_found': 'تعذر تحديد الجدول المقصود',
    'ambiguous_table': 'يوجد أكثر من جدول في الشريحة وتعذر تحديد المقصود',
    'ambiguous_table_target': 'الاسم المطلوب مكرر في أكثر من موضع',
    'no_table_in_slide': 'لا يوجد جدول في الشريحة المستهدفة',
    'merged_cells_unsupported': 'الجدول يحوي خلايا مدمجة والحذف الحتمي مرفوض عليها',
    'nested_table_unsupported': 'الجدول متداخل والحذف الحتمي مرفوض عليه',
    'malformed_table': 'بنية الجدول غير سليمة والحذف الحتمي مرفوض عليه',
    'non_rectangular_table': 'صفوف الجدول غير متساوية الأعمدة والحذف الحتمي مرفوض عليه',
    'column_layout_unsupported': 'الجدول يستخدم تخطيط أعمدة والحذف الحتمي مرفوض عليه',
    'would_empty_table': 'الحذف المطلوب سيفرغ الجدول بالكامل وهو مرفوض',
    'missing_table_target': 'لم يحدد رقم أو اسم الصف أو العمود',
    'ambiguous_table_request': 'الطلب غامض ويحتاج توضيح الصف أو العمود',
    'ambiguous_table_selector': 'محدد الجدول غامض',
    'compound_table_request': 'الطلب مركب ويحتاج تنفيذه على خطوات',
    'negated_or_conditional_request': 'الطلب منفي أو مشروط',
    'unsupported_table_edit': 'هذا النوع من تعديل الجدول غير مدعوم حتميًا',
}


def _table_precheck_note(slides, indexes, message):
    """Short Arabic note naming why the local table edit cannot apply, without any LLM call.

    Used when the planner prompt itself exceeds the token cap: instead of surfacing a raw
    402, the user learns which slide failed, why, and — for a missing column — which headers
    actually exist so the retry can name one of them.
    """
    for idx in list(indexes or [])[:3]:
        slide = slides[idx] if isinstance(slides[idx], dict) else {}
        try:
            res = designer_chat_reliability.apply_table_delete_request(slide.get('html', ''), message)
        except Exception:
            continue
        if res.get('changed'):
            continue
        reason = str(res.get('reason') or 'unknown')
        arabic = _TABLE_PRECHECK_ARABIC_REASONS.get(reason, reason)
        suffix = ''
        try:
            request = res.get('request') if isinstance(res.get('request'), dict) else {}
            if request.get('kind') == 'column':
                headers = []
                for match in re.finditer(r'<th\b[^>]*>(.*?)</th>', str(slide.get('html', '')),
                                         flags=re.IGNORECASE | re.DOTALL):
                    text = re.sub(r'<[^>]+>', ' ', html_lib.unescape(match.group(1)))
                    text = re.sub(r'\s+', ' ', text).strip()
                    if text:
                        headers.append(text)
                if headers:
                    suffix = '؛ الأعمدة المتاحة: ' + '، '.join(headers[:12])
        except Exception:
            suffix = ''
        return f'تعذر الحذف الحتمي في الشريحة {idx + 1}: {arabic}{suffix}'
    return ''


def _designer_project_data_for_request(request_project_data, presentation, tenant_id):
    """Merge the presentation snapshot with its latest saved draft and current request.

    The linked draft is loaded by id so opening an older presentation never sends Sol stale
    project facts, while an unrelated newer project owned by the same user is never mixed in.
    Current browser values win because they may contain edits made after the last explicit save.
    """
    cleaned_request = copy.deepcopy(request_project_data) if isinstance(request_project_data, dict) else {}
    request_data = cleaned_request if isinstance(cleaned_request, dict) else {}
    presentation_data = {}
    if isinstance(presentation, dict):
        raw = presentation.get('project_data')
        if isinstance(raw, dict):
            cleaned_presentation = copy.deepcopy(raw)
            presentation_data = cleaned_presentation if isinstance(cleaned_presentation, dict) else {}
        elif isinstance(raw, str) and raw.strip():
            try:
                decoded = json.loads(raw)
                cleaned_presentation = decoded if isinstance(decoded, dict) else {}
                presentation_data = cleaned_presentation if isinstance(cleaned_presentation, dict) else {}
            except (TypeError, ValueError):
                presentation_data = {}
    presentation_draft_id = presentation.get('draft_id') if isinstance(presentation, dict) else None
    draft_id = (
        presentation_draft_id
        or presentation_data.get('draftId') or presentation_data.get('draft_id')
        or request_data.get('draftId') or request_data.get('draft_id')
    )
    draft_data = {}
    if tenant_id and draft_id:
        try:
            draft = db.get_project_draft_by_id(tenant_id, str(draft_id))
            if isinstance(draft, dict) and isinstance(draft.get('draft_data'), dict):
                cleaned_draft = copy.deepcopy(draft['draft_data'])
                draft_data = cleaned_draft if isinstance(cleaned_draft, dict) else {}
        except Exception as exc:
            print(f'[DESIGNER-CHAT] Could not load linked draft {draft_id}: {exc}')
    merged = {**presentation_data, **draft_data, **request_data}
    if draft_id:
        merged['draftId'] = str(draft_id)
    return merged


def _designer_requests_boundary_data(instruction):
    text = str(instruction or '').casefold()
    return any(word in text for word in (
        'حدود', 'شارع', 'شوارع', 'جار', 'جيران', 'اتجاه',
        'طول', 'واجهة',
    ))


def _designer_requests_google_maps_link(instruction):
    text = str(instruction or '').casefold()
    return 'رابط' in text and any(word in text for word in ('جوجل', 'google', 'خرائط', 'ماب'))


def _designer_project_maps_link(project_data):
    source = project_data if isinstance(project_data, dict) else {}
    for key in ('location_address', 'location_maps_link', 'maps_link'):
        value = str(source.get(key) or '').strip()
        if re.match(r'^https?://', value, flags=re.IGNORECASE):
            return value
    return ''


def _inject_designer_project_maps_link(html, link):
    """Insert the exact stored map link when the user explicitly asks for it."""
    if not html or not link:
        return html, False
    safe_link = html_lib.escape(str(link), quote=True)
    markup = (
        '<a data-project-map-link="1" href="' + safe_link + '" target="_blank" rel="noopener" '
        'style="position:absolute;left:220px;right:220px;bottom:38px;z-index:8;'
        'font-size:11px;line-height:1.4;font-weight:700;text-align:center;color:#0c5670;'
        'text-decoration:underline;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;">'
        'رابط موقع المشروع على Google Maps</a>'
    )
    existing = re.search(
        r'<a\b[^>]*\bdata-project-map-link=["\'][^"\']+["\'][^>]*>[\s\S]*?</a>',
        str(html), flags=re.IGNORECASE,
    )
    if existing:
        updated = str(html)[:existing.start()] + markup + str(html)[existing.end():]
        return updated, updated != html
    closing = re.search(r'</div>\s*$', str(html), flags=re.IGNORECASE)
    if not closing:
        return html, False
    return str(html)[:closing.start()] + markup + str(html)[closing.start():], True


def _designer_edit_failure_detail(reasons):
    unique = list(dict.fromkeys(str(reason or '') for reason in reasons if reason))
    if 'dropped_boundary_data' in unique:
        return 'نتيجة المصمم أسقطت أطوال حدود موثقة، فتم رفضها لحماية بيانات المشروع.'
    if unique and set(unique) == {'no_material_change'}:
        return 'أعاد المصمم الشريحة نفسها دون تغيير قابل للتحقق.'
    if 'invalid_html' in unique:
        return 'لم يُرجع المصمم شريحة HTML صالحة يمكن تطبيقها.'
    if 'provider_error' in unique:
        return 'تعذر الحصول على نتيجة صالحة من مزود التصميم بعد المحاولات المتاحة.'
    if 'maps_link_missing' in unique:
        return 'لا يوجد رابط Google Maps محفوظ في بيانات هذا المشروع.'
    if 'boundary_data_unchanged' in unique:
        return 'أحدث بيانات الحدود مطابقة لما هو ظاهر بالفعل في الشريحة.'
    return 'لم تنتج المحاولات تغييرًا فعليًا صالحًا للتطبيق.'


def _designer_edit_slide(html, title, instruction, slide_index, project_data, presentation_id, branding, tenant_id=None, creative_images=None, user_image_refs=None, slide_type='content', total_slides=None, content_source=None, skip_vision=False, progress_callback=None):
    """Ask GLM/Sol for one complete slide and retry malformed responses with Playwright Vision guidance."""
    if not tenant_id:
        try:
            tenant_id = g.tenant_id
        except Exception:
            tenant_id = None

    table_edit = designer_chat_reliability.apply_table_delete_request(html, instruction)
    if table_edit['changed']:
        return table_edit['html'], table_edit['description']
    is_slide_redesign = bool(re.search(
        r'(?:اعد\s*تصميم|إعادة\s*تصميم|غير\s*تصميم|تصميم|تنسيق|شريحة|سلايد|redesign|layout|style)',
        str(instruction or ''),
        re.IGNORECASE
    ))
    if not is_slide_redesign and table_edit['handled'] and table_edit.get('reason') in ('would_empty_table', 'negated_or_conditional_request'):
        reason_text = _TABLE_PRECHECK_ARABIC_REASONS.get(table_edit['reason'], table_edit['reason'])
        return html, (table_edit['description'] or f'تعذر تحديد تعديل الجدول بأمان: {reason_text}')
    if designer_chat_colors.is_color_only_request(instruction):
        color_html, color_message = designer_chat_colors.apply_color_edit(html, instruction)
        return color_html or html, color_message

    rules = build_design_rules(branding)
    training_context = ''
    if tenant_id:
        try:
            training_context = db.get_training_context(tenant_id) or ''
        except Exception:
            training_context = ''
    training_note = (
        f"\n\n## قواعد الشركة الملزمة (من التدريب — التزم بها في التصميم)\n{training_context}"
        if training_context else ''
    )
    team_logo_note = (
        "\n\n## شعارات فريق العمل في هذا المشروع\n"
        + _designer_team_logo_context(creative_images)
        + "\nلا تضع شعار جهة فريق العمل في هيدر الشركة، ولا تستبدله بـ ##LOGO## أو ##PROJECT_LOGO##. "
          "عند طلب شعار جهة محددة، أدرج الرمز المطابق داخل موضع محتوى مناسب في الشريحة. "
          "ممنوع إدراج أي شعار (شركة أو مشروع أو فريق عمل) إلا إذا طلب المستخدم ذلك صراحة بكلمة "
          "شعار أو لوجو أو علامة تجارية في رسالته الحالية. طلب وصف أو شرح أو تعليق على صور موجودة "
          "يعني إضافة نص وصفي فقط دون أي شعار ودون توليد صورة جديدة، وطلب صورة أو تصميم أو توليد "
          "يعني صورة معمارية جديدة وليس شعاراً."
    )

    # Capture Playwright vision screenshot of the current slide if available (skip in large bulk edits for speed)
    vision_image_uri = None
    vision_error = ''
    if not skip_vision:
        try:
            import generate_pdf_from_preview as renderer
            vision_image_uri = renderer.render_slide_to_image_base64(html, branding=branding, tenant_id=tenant_id)
            if not vision_image_uri:
                vision_error = getattr(renderer, 'LAST_VISION_ERROR', '') or 'no_snapshot'
        except Exception as ve:
            vision_error = str(ve)
            print(f"[DESIGNER-EDIT VISION] Screenshot failed: {ve}")
    else:
        vision_error = 'skipped_batch'
    _record_slide_vision_state(bool(vision_image_uri), vision_error)
    if vision_error:
        # Without the snapshot the model edits the markup blind, and it still claims success. The
        # user was left believing a layout was inspected and fixed when it was never seen.
        print(f"[DESIGNER-EDIT VISION] Editing slide {slide_index + 1} without a visual snapshot ({vision_error})")

    image_refs = None
    vision_note = ""
    if vision_image_uri:
        image_refs = [{"data_uri": vision_image_uri}]
        vision_note = (
            "\n\n## الرؤية البصرية للشريحة الحالية (Visual Vision Snapshot):\n"
            "لقد تم تزويدك بلقطة شاشة مرئية فعلية للشريحة الحالية بدقة 1280x720 كما تظهر للمستخدم تماماً.\n"
            "- انظر بدقة إلى اللقطة المرفقة لتفهم:\n"
            "  1. التوزيع البصري، الهوامش، والمسافات البينية (spacing / padding / margins).\n"
            "  2. أحجام الخطوط والتسلسل الهرمي للنصوص وعناوين البطاقات.\n"
            "  3. تموضع وحجم الصور والبطاقات والشعارات.\n"
            "  4. درجات الألوان وتناسق الخلفية مع النصوص والبطاقات.\n"
            "- نفّذ التعديل المطلوب بدقة جراحية مع الحفاظ على التناسق البصري والجمالي والتوازن وبدون تداخل نصوص."
        )

    if user_image_refs:
        # The user's own attachment comes after the snapshot, so the order matches the note below.
        image_refs = (image_refs or []) + list(user_image_refs)
        vision_note += (
            "\n\n## صورة أرفقها المستخدم مع طلبه\n"
            "الصورة الأخيرة المرفقة هي صورة المستخدم، لا لقطة الشريحة. استخدمها كما يوضح طلبه"
            " (مرجع تصميم أو محتوى مطلوب أو خلل يشير إليه)، ولا تنسخ نصوصها إلى الشريحة إلا إن طلب ذلك."
        )

    # Store base64 data URIs to avoid inflating prompt with hundreds of thousands of tokens
    base64_map = {}
    def _preserve_base64(match):
        idx = len(base64_map)
        ph = f"##PRESERVED_BASE64_{idx}##"
        base64_map[ph] = match.group(0)
        return ph

    clean_html = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', _preserve_base64, html or '')

    surface_note = '' if slide_type in ('cover', 'closing', 'section_divider', 'moodboard') else (
        "\n\n## عقد سطح شريحة المحتوى\n"
        "هذه شريحة محتوى عادية ويجب أن تبقى على canvas أبيض أو فاتح موحد، لا على إطار داكن حول صفحة بيضاء. "
        "استخدم اللون الأساسي في العناوين ورؤوس الجداول والمساحات المحدودة فقط، واترك الخلفية الداكنة الكاملة للغلاف والخاتمة وفواصل الأقسام ذات الصورة. "
        "خلفية شعار الشركة وشعار المشروع مستقلة لكل شعار حسب لونه وتباينه؛ لا تغيّرها عند تغيير خلفية الشريحة."
    )

    is_boundary_slide = _is_land_boundary_diagram_slide(
        title=title, content_source=content_source, html=html)
    boundary_data_request = is_boundary_slide and _designer_requests_boundary_data(instruction)
    requested_maps_link = is_boundary_slide and _designer_requests_google_maps_link(instruction)
    project_maps_link = _designer_project_maps_link(project_data) if requested_maps_link else ''
    canonical_boundary_html = ''
    if boundary_data_request and slide_engine._has_land_boundary_data(project_data):
        try:
            canonical_boundary_html = slide_engine._build_land_boundary_diagram_slide(
                {
                    'title': title,
                    'type': slide_type or 'content',
                    'content_source': content_source or 'land_boundary_diagram',
                },
                project_data,
                branding,
                slide_num=slide_index + 1,
                total_slides=total_slides or (slide_index + 1),
            )
            canonical_boundary_html = resolve_designer_chat_placeholders(
                canonical_boundary_html, project_data, presentation_id, tenant_id, creative_images)
            canonical_boundary_html = slide_engine.finalize_designer_slide_html(
                canonical_boundary_html, slide_type or 'content', project_data, branding,
                creative_images=creative_images, tenant_id=tenant_id,
                slide_num=slide_index + 1, slide_title=title,
                total_slides=total_slides or (slide_index + 1), content_source=content_source,
                allow_all_maps=True,
            )
            canonical_boundary_html = _sanitize_designer_output(canonical_boundary_html)
            if not _is_watermark_removal_instruction(instruction):
                canonical_boundary_html = _carry_slide_watermark(html, canonical_boundary_html)
        except Exception:
            canonical_boundary_html = ''
            app.logger.exception(
                '[DESIGNER-EDIT] deterministic boundary build failed for slide %s', slide_index + 1)
    project_context = _designer_project_context(project_data, creative_images, tenant_id)

    prompt = f"""{rules}{training_note}{team_logo_note}{vision_note}{surface_note}

{project_context}
أنت Sol، كبير المصممين ومهندس العرض وجرّاح كود وتصميم (Surgical Code & Design Master). عدّل الشريحة بدقة جراحية متناهية حسب الطلب:
1. قواعد الإزاحات والتخطيط الجراحي (Spatial & Layout Precision):
   - تحكّم دقيق بكسلي ونسبية في CSS: رفع أو تنزيل الهيدر، ضبط هوامش البطاقات الداخلية (padding) والخارجية (margins)، وتغيير حجم البطاقات والمسافات البينية (gap).
   - تحويل التخطيط بسلاسة بين عمودين أو ثلاثة أعمدة أو شبكة غير متماثلة (Asymmetric Grid) مع الحفاظ التام على انسيابية العناصر.
   - ضبط المحاذاة العمودية والأفقية والتوزيع المتوازن (align-items / justify-content).
2. النظم الجمالية والهوية المعتمدة (Design System & Tokens):
   - حافظ على خط الشركة المحمل؛ لا تكتب اسم خط ثابت ولا تغيره في طلب لون أو محتوى.
   - ألوان الشركة أعلاه هي الافتراضية. تغيير اللون الصريح من المستخدم يطبق على العناصر المطلوبة فقط دون إعادة تلوين باقي الشريحة.
   - تحقيق تباين لوني عالي (Contrast Ratio >= 4.5:1) لضمان سهولة القراءة الفائقة.
3. التعديل الجراحي الموضعي (Surgical Modifications):
   - إضافة أو حذف أو تعديل بطاقة أو نص أو مكون محدد دون مساس بباقي محتويات الشريحة، ودون إعادة بناء من الصفر، ودون تدمير التنسيق.
   - حذف صف أو عمود من جدول داخل الشريحة هو تعديل جراحي عادي: احذف <tr> الصف المطلوب أو خلية العمود من كل صف بما فيها الرأس، وحافظ على البقية.
4. إدراج الخرائط والمكونات المعمارية:
   - يمكنك إدراج أو استبدال أي خريطة من الخرائط الأربع المعتمدة (##MAP_OVERVIEW##, ##MAP_ACCESS##, ##MAP_CATCHMENT##, ##MAP_LANDMARKS##) أو صور المكونات مع ضبط موضعها وأبعادها بدقة.
5. الصياغة العقارية والاستثمارية الرفيعة (Saudi Real Estate Phrasing):
   - نبرة رسمية استثمارية رفيعة المستوى تخاطب المستثمرين واللجان التمويلية.
   - استخدام المصطلحات العقارية السعودية الدقيقة (معامل البناء، الارتدادات، الصك الإلكتروني، كود البناء السعودي).
6. الامتثال الصارم (Strict Compliance):
   - ممنوع منعاً باتاً وضع أي أيقونات أو إيموجي أو رموز تعبيرية (No icons, no emojis).
   - ممنوع وضع أي رموز أسهم (استخدم كلمات: أعلى، أسفل، يمين، يسار).
   - خلو الشريحة تماماً من أي نص تعليمي (No How-To text).
   - الحفاظ على مقاس الشريحة القياسي 1280x720 و overflow:hidden دون أشرطة تمرير.
   - سطح الشريحة: شرائح المحتوى العادية فاتحة وموحدة، ولا تُبنى كواجهة داكنة أو كإطار داكن حول صفحة بيضاء. حافظ على خلفية كل شعار مستقلة حسب لونه.
7. حرية إبداعية وتصميمية مطلقة لجميع أنواع الشرائح (Full Creative Freedom):
   - تمتلك كامل الصلاحية والحرية المطلقة لتعديل أو إعادة ابتكار وتصميم أي شريحة يطلبها المستخدم بلا أي استثناء أو قيود نوعية:
     * شرائح الفصول والأقسام الرئيسية (Section Dividers / الفصول): لك مطلق الحرية في إعادة تصميمها بتخطيطات إبداعية كاملة (مثل: إضافة كروت ملخصة لمحاور القسم، خطوط زمنية، إبراز مؤشرات أو أرقام قياسية، تقسيم الشريحة أفقياً أو عمودياً Split View، دمج صورة معمارية مع بطاقة داكنة ملكية، تدرجات لونية، خطوط عريضة، إلخ).
     * شريحة الفهرس (Index Slide): لك الحرية في تصميمها بشبكات عصرية أو بطاقات مرقمة فاخرة، مع الحفاظ على وسم data-index-page="section_key" لكل قسم لربط أرقام الصفحات.
     * شرائح الغلاف والخاتمة (Cover & Closing): كامل الحرية في إعادة توزيع العناصر وتنسيق المقدمة والخاتمة.
     * شرائح المحتوى، الخرائط، والتحليلات.
   - لا ترفض ولا تعتذر عن تعديل أي شريحة مهما كان نوعها، ونفّذ أي فكرة تصميمية يطلبها المستخدم بحرية مطلقة وإتقان واحترافية.
أعد JSON فقط بالشكل:
{{"html":"<div class=\\"slide\\">...</div>","response":"شرح عربي موجز ودقيق لما قمت به جراحياً"}}
عنوان الشريحة: {title}
HTML الحالي:
{clean_html}
الطلب:
{instruction}"""

    failure_reasons = []
    for attempt in range(1, 4):
        if callable(progress_callback):
            try:
                progress_callback(attempt, 3)
            except Exception as progress_error:
                app.logger.warning('[DESIGNER-EDIT] progress callback failed: %s', progress_error)
        try:
            raw = extract_chat_content(call_zai_chat(prompt, instruction, max_tokens=DESIGNER_EDIT_MAX_TOKENS, model=SLIDE_TEXT_MODEL, image_references=image_refs, timeout=300, usage_ctx=_usage_ctx('designer_chat', project_data, presentation_id=presentation_id)), 'DESIGNER-EDIT')
            parsed = _designer_json_response(raw)
            output = parsed.get('html') or parsed.get('content') or parsed.get('slide_html')
            if not output and raw and '<div' in raw and 'slide' in raw:
                div_m = re.search(r'<div\b[^>]*class=["\']slide["\'][\s\S]*?</div>', raw, flags=re.IGNORECASE)
                if div_m:
                    output = div_m.group(0)
            if output and ('slide' in output and '<div' in output):
                if 'class="slide"' not in output and "class='slide'" not in output:
                    output = f'<div class="slide" style="width:1280px;height:720px;position:relative;box-sizing:border-box;overflow:hidden;">{output}</div>'
                
                # Restore any preserved base64 images
                for ph, b64_str in base64_map.items():
                    output = output.replace(ph, b64_str)
                model_changed = designer_chat_reliability.materially_changed(
                    html, output, parsed.get('response'))
                if (not model_changed and not canonical_boundary_html
                        and not (requested_maps_link and project_maps_link)):
                    failure_reasons.append('no_material_change')
                    print(f'[DESIGNER-EDIT] model returned no change on attempt {attempt}')
                    continue

                output = resolve_designer_chat_placeholders(output, project_data, presentation_id,
                                                           tenant_id, creative_images)
                # A rebuilt slide that kept its old map <img> kept the old map:
                # stored sources are frozen revision URLs the model preserves
                # verbatim, so any persisted-map source is repointed at the
                # current file for its canonical type before it is kept.
                output = _refresh_slide_map_sources(
                    output, project_data, tenant_id, presentation_id=presentation_id,
                    creative_images=creative_images)
                # Same staleness problem for chat-placed asset images: the
                # stamped tag's token is authoritative, its stored src is not.
                output = _refresh_slide_asset_sources(
                    output,
                    _designer_image_assets(
                        _designer_creative_images(project_data, creative_images)))
                output = slide_engine.finalize_designer_slide_html(
                    output, slide_type or 'content', project_data, branding,
                    creative_images=creative_images, tenant_id=tenant_id,
                    slide_num=slide_index + 1, slide_title=title,
                    total_slides=total_slides or (slide_index + 1), content_source=content_source,
                    allow_all_maps=True,
                )
                output = _sanitize_designer_output(output)
                # The model rebuilds the slide and drops the watermark overlay div.
                # Carry it over so any later AI edit cannot silently delete it.
                if not _is_watermark_removal_instruction(instruction):
                    output = _carry_slide_watermark(html, output)
                # Content requests on this system-owned slide always use the canonical builder.
                # Sol may choose the operation, but it cannot relocate directions, omit documented
                # neighbours or substitute stale data in the resulting boundary diagram.
                if canonical_boundary_html:
                    output = canonical_boundary_html
                if is_boundary_slide:
                    # The boundary diagram is rebuilt from documented facts: a model
                    # reply that drops a documented length corrupts the slide, and a
                    # data-add request with no visible text change is a false success.
                    # Retry instead of returning either.
                    try:
                        boundary_data = slide_engine._extract_land_boundary_diagram_data(
                            project_data if isinstance(project_data, dict) else {}
                        )
                    except Exception:
                        boundary_data = {}
                    if isinstance(boundary_data, dict):
                        dropped = []
                        for _dir_key in ('north', 'south', 'east', 'west'):
                            _raw_item = boundary_data.get(_dir_key)
                            _item = _raw_item if isinstance(_raw_item, dict) else {}
                            _length = str(_item.get('length') or '').strip()
                            _number = re.search(r'\d+(?:\.\d+)?', _length)
                            if _number and _number.group(0) not in str(output or ''):
                                dropped.append(_dir_key)
                        if dropped:
                            failure_reasons.append('dropped_boundary_data')
                            print(f'[DESIGNER-EDIT] boundary slide dropped lengths {dropped} on attempt {attempt}')
                            continue
                    if boundary_data_request:
                        _strip_tags = lambda value: re.sub(
                            r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(value or ''))).strip()
                        if _strip_tags(output) == _strip_tags(html) and not requested_maps_link:
                            failure_reasons.append('boundary_data_unchanged')
                            print(f'[DESIGNER-EDIT] boundary data already current on attempt {attempt}')
                            return output, (
                                f'تم الحفاظ على تصميم الشريحة {slide_index + 1}. '
                                'أحدث بيانات الحدود مطابقة لما هو ظاهر بالفعل في الشريحة.'
                            )
                inserted_requested_maps_link = False
                if requested_maps_link:
                    if not project_maps_link:
                        failure_reasons.append('maps_link_missing')
                        print(f'[DESIGNER-EDIT] no stored Google Maps link for slide {slide_index + 1}')
                        continue
                    output, inserted_requested_maps_link = _inject_designer_project_maps_link(
                        output, project_maps_link)
                    if 'data-project-map-link="1"' not in output:
                        failure_reasons.append('invalid_html')
                        print(f'[DESIGNER-EDIT] could not insert Google Maps link on attempt {attempt}')
                        continue
                response_text = (
                    'تم تحديث مخطط الحدود من أحدث بيانات المشروع الموثقة.'
                    if canonical_boundary_html
                    else (parsed.get('response') or 'تم تحديث الشريحة بنجاح.')
                )
                if inserted_requested_maps_link:
                    if not model_changed and not canonical_boundary_html:
                        response_text = 'تمت إضافة رابط Google Maps المحفوظ للمشروع.'
                    else:
                        response_text += ' تمت إضافة رابط Google Maps المحفوظ للمشروع.'
                if vision_error:
                    response_text += ' التعديل جرى على الكود بدون معاينة بصرية للشريحة.'
                return output, response_text
            failure_reasons.append('invalid_html')
            print(f'[DESIGNER-EDIT] invalid HTML on attempt {attempt}')
        except Exception as edit_exc:
            if _is_openrouter_credit_error(edit_exc):
                return html, 'رصيد مفتاح الذكاء الاصطناعي (OpenRouter) غير كافٍ أو تم تجاوز الحد الشهري للمفتاح؛ يرجى مراجعة إعدادات المفتاح أو شحن الرصيد.'
            failure_reasons.append('provider_error')
            app.logger.exception('[DESIGNER-EDIT] attempt %s failed for slide %s', attempt, slide_index + 1)

    fallback = html

    # The boundary diagram is a deterministic system slide. If Sol cannot safely edit it, rebuild
    # it from the newest linked-draft facts instead of returning the old snapshot. This gives new
    # streets, neighbours, widths and lengths a reliable path without weakening the no-op guard.
    deterministic = canonical_boundary_html or fallback
    rebuilt_boundary = bool(canonical_boundary_html) and designer_chat_reliability.materially_changed(
        html, deterministic, 'إعادة بناء شريحة الحدود من أحدث بيانات المشروع')
    if canonical_boundary_html and not rebuilt_boundary:
        failure_reasons.append('boundary_data_unchanged')

    inserted_maps_link = False
    if requested_maps_link:
        if project_maps_link:
            deterministic, inserted_maps_link = _inject_designer_project_maps_link(
                deterministic, project_maps_link)
        else:
            failure_reasons.append('maps_link_missing')

    if (rebuilt_boundary or inserted_maps_link) and designer_chat_reliability.materially_changed(
            html, deterministic, 'تحديث حتمي من بيانات المشروع'):
        completed = []
        if rebuilt_boundary:
            completed.append('تم تحديث مخطط الحدود من أحدث بيانات المشروع الموثقة')
        if inserted_maps_link:
            completed.append('تمت إضافة رابط Google Maps المحفوظ للمشروع')
        return deterministic, '، و'.join(completed) + '.'

    detail = _designer_edit_failure_detail(failure_reasons)
    print(f'[DESIGNER-EDIT] slide {slide_index + 1} rejected after 3 attempts: {failure_reasons}')
    return fallback, f'تم الحفاظ على تصميم الشريحة {slide_index + 1} لتعذر التعديل التلقائي عليها. {detail}'


DESIGNER_CHAT_VERBATIM_TURNS = 10
DESIGNER_CHAT_MEMORY_CHARS = 6000
DESIGNER_CHAT_MEMORY_MAX = 1800
DESIGNER_CHAT_STORED_TURNS = 40


def _normalize_designer_chat_messages(messages):
    """Keep chat entries in one comparable shape before merging browser and DB history."""
    normalized = []
    for entry in messages if isinstance(messages, list) else []:
        if not isinstance(entry, dict) or not str(entry.get('content') or '').strip():
            continue
        normalized.append({
            'role': 'user' if entry.get('role') == 'user' else 'assistant',
            'content': str(entry.get('content') or '')[:2000],
            'slides': entry.get('slides') if isinstance(entry.get('slides'), list) else [],
        })
    return normalized


def _merge_designer_chat_messages(stored_messages, incoming_messages):
    """Merge a browser snapshot into saved history without replacing older turns."""
    stored = _normalize_designer_chat_messages(stored_messages)
    incoming = _normalize_designer_chat_messages(incoming_messages)
    if not stored:
        return incoming
    if not incoming:
        return stored
    if incoming == stored or len(incoming) <= len(stored):
        for start in range(len(stored) - len(incoming) + 1):
            if stored[start:start + len(incoming)] == incoming:
                return stored
    if len(stored) <= len(incoming):
        for start in range(len(incoming) - len(stored) + 1):
            if incoming[start:start + len(stored)] == stored:
                return incoming
    max_overlap = min(len(stored), len(incoming))
    for overlap in range(max_overlap, 0, -1):
        if stored[-overlap:] == incoming[:overlap]:
            return stored + incoming[overlap:]
    return stored + incoming


def _designer_chat_history_lines(history):
    """The conversation as prompt lines, with each turn's slide numbers attached."""
    lines = []
    for entry in history if isinstance(history, list) else []:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get('content') or '').strip()
        if not text:
            continue
        role = 'المستخدم' if entry.get('role') == 'user' else 'المصمم'
        slides = [str(int(n)) for n in (entry.get('slides') or []) if str(n).strip().isdigit()]
        scope = f" [شرائح: {'، '.join(slides)}]" if slides else ''
        lines.append(f"{role}{scope}: {text[:1500]}")
    return lines


def _designer_chat_memory(history, memory, usage_ctx=None):
    """Keep the conversation whole: recent turns verbatim, older ones kept as tail text.

    The chat used to receive nothing but the current message, so it asked «أي شريحة؟», the user
    answered «8», and the next turn had no idea what «8» referred to. History is now carried, and
    once it grows past DESIGNER_CHAT_MEMORY_CHARS the older half is folded into the memory string.

    Billing rule: this helper never calls the model. A previous version summarized the older
    turns with an extra AI call on every long-history turn, so a simple message was billed for
    work the user never asked for. The tail of the raw conversation is kept instead, which
    preserves slide numbers and decisions without any hidden spend. ``usage_ctx`` is kept only
    for caller compatibility.
    """
    _ = usage_ctx
    memory = str(memory or '').strip()
    entries = [e for e in (history if isinstance(history, list) else []) if isinstance(e, dict)]
    recent = entries[-DESIGNER_CHAT_VERBATIM_TURNS:]
    older = entries[:-DESIGNER_CHAT_VERBATIM_TURNS] if len(entries) > DESIGNER_CHAT_VERBATIM_TURNS else []
    older_lines = _designer_chat_history_lines(older)
    if not older_lines:
        return memory, recent

    older_text = '\n'.join(older_lines)
    if len(memory) + len(older_text) <= DESIGNER_CHAT_MEMORY_CHARS:
        merged = (memory + '\n' + older_text).strip() if memory else older_text
        return merged[-DESIGNER_CHAT_MEMORY_CHARS:], recent

    # No model summarization here: keep the newest older text within the cap.
    merged = (memory + '\n' + older_text).strip() if memory else older_text
    return merged[-DESIGNER_CHAT_MEMORY_MAX:], recent


DESIGNER_CHAT_MAX_ATTACHED_IMAGES = 3
DESIGNER_CHAT_ATTACHED_IMAGE_LIMIT = 4 * 1024 * 1024


def _designer_chat_free_reply(message, has_attachment=False):
    """Deterministic no-AI reply for greetings and capability questions.

    These turns used to run the full planner prompt (the whole draft as context) just to
    answer «سلام» or «بتعمل ايه», so the tenant's provider balance moved on a message that
    requested no work. Returning a canned answer here spends zero tokens: no planner call,
    no edit call and no memory call. Returns the reply text, or None when the turn needs
    the planner.
    """
    if has_attachment:
        return None
    text = normalize_arabic_digits_py(str(message or '').strip().lower())
    if not text:
        return None
    if len(text) > 60:
        return None
    if designer_chat_targets.explicit_slide_numbers(message):
        return None
    edit_markers = (
        'عدل', 'عدّل', 'غير', 'غيّر', 'احذف', 'امسح', 'ضيف', 'أضف', 'اضف', 'حط', 'ضع',
        'انقل', 'كرر', 'ادمج', 'اقسم', 'جزئ', 'شريحة', 'شريحه', 'سلايد', 'صورة', 'صوره',
        'خريطة', 'خريط', 'شعار', 'لوجو', 'علامة', 'watermark', 'لون', 'خط', 'جدول',
        'صف', 'عمود', 'مخطط', 'رسم',
    )
    if any(marker in text for marker in edit_markers):
        return None
    greetings = (
        'سلام', 'مرحبا', 'مرحب', 'اهلا', 'أهلا', 'هلا', 'هاي', 'هاى', 'ازيك', 'ازيك؟',
        'عامل ايه', 'عامل إيه', 'صباح الخير', 'مساء الخير', 'مساء النور', 'صباح النور',
        'شكرا', 'شكرًا', 'تسلم', 'تمام', 'ماشي', 'ماشى', 'اوك', 'أوك', 'طيب', 'اه',
        'hello', 'hi', 'thanks', 'thank you', 'ok',
    )
    if any(greet in text for greet in greetings):
        return (
            'أهلاً بك. أخبرني بالتعديل المطلوب على العرض، وسأنفذه مباشرة. '
            'هذه التحية لم تستهلك أي رصيد.'
        )
    help_markers = (
        'بتعمل ايه', 'بتعمل إيه', 'ايه قدراتك', 'إيه قدراتك', 'ممكن تعمل ايه',
        'تقدر تعمل ايه', 'مساعدة', 'مساعده', 'help', 'قدراتك', 'ازاي استخدم',
        'كيف استخدم', 'بتسحب رصيد', 'الرصيد', 'بتكلف',
    )
    if any(marker in text for marker in help_markers):
        return (
            'أنا مساعد التصميم لهذا العرض. أنفذ التعديلات على الشرائح المفتوحة فقط، '
            'ولا أقرأ المسودة ولا أستهلك رصيداً إلا بعد طلب تعديل واضح منك. '
            'يمكنك طلب تعديل شريحة، إنشاء شريحة جديدة، أو إرفاق صورة ثم طلب وضعها '
            'في شريحة منفصلة أو داخل شريحة أو كعلامة مائية أو كشعار إضافي.'
        )
    return None


def _normalize_designer_attached_images(data):
    """Collect user-attached chat images as data URIs, newest protocol first.

    Accepts the legacy ``attachedImage`` string plus the newer ``attachedImages`` list
    (strings or {data_uri/url, name} dicts). Only PNG/JPEG/WEBP data URIs within the
    size limit are kept, up to DESIGNER_CHAT_MAX_ATTACHED_IMAGES, so one oversized
    attachment cannot blow up the planner prompt.
    """
    uris = []
    if not isinstance(data, dict):
        return uris

    def _take(value):
        if not isinstance(value, str):
            return
        text = value.strip()
        if not text.startswith('data:image/'):
            return
        header = text.split(',', 1)[0].lower()
        if ';base64,' not in text:
            return
        if not any(kind in header for kind in ('image/png', 'image/jpeg', 'image/jpg', 'image/webp')):
            return
        try:
            raw = base64.b64decode(text.split(',', 1)[1], validate=True)
        except Exception:
            return
        if len(raw) > DESIGNER_CHAT_ATTACHED_IMAGE_LIMIT or len(raw) == 0:
            return
        if text not in uris:
            uris.append(text)

    legacy = data.get('attachedImage')
    _take(legacy if isinstance(legacy, str) else '')
    newer = data.get('attachedImages')
    if isinstance(newer, list):
        for item in newer:
            if isinstance(item, str):
                _take(item)
            elif isinstance(item, dict):
                candidate = item.get('data_uri') or item.get('dataUri') or item.get('url') or ''
                _take(candidate if isinstance(candidate, str) else '')
            if len(uris) >= DESIGNER_CHAT_MAX_ATTACHED_IMAGES:
                break
    return uris[:DESIGNER_CHAT_MAX_ATTACHED_IMAGES]


def _persist_designer_attached_images(data_uris, tenant_id):
    """Store chat attachments on disk and return durable URLs for slide HTML.

    Slides must reference a server URL, never a data URI: a data URI in saved HTML
    bloats every later planner prompt and breaks on reload. Falls back to the data
    URI itself only when persisting fails, so the turn can still show the image.
    """
    urls = []
    for uri in data_uris or []:
        try:
            stored = persist_generated_image(uri, tenant_id)
        except Exception:
            stored = uri
        urls.append(stored if isinstance(stored, str) and stored else uri)
    return urls


def _report_designer_job_progress(job_id, tenant_id, progress_val, message_text, extra_data=None):
    """Update background designer job progress file thread-safely for client polling."""
    if not job_id or not tenant_id:
        return
    try:
        current_job = _read_job('.designer_chat_jobs', tenant_id, job_id) or {}
        updated_job = {
            **current_job,
            'status': 'running',
            'success': True,
            'progress': max(1, min(99, int(progress_val))),
            'message': str(message_text or 'جاري معالجة الطلب...'),
        }
        if extra_data and isinstance(extra_data, dict):
            updated_job.update(extra_data)
        _write_job('.designer_chat_jobs', tenant_id, job_id, updated_job)
    except Exception as err:
        print(f"[JOB PROGRESS ERROR] {err}")
