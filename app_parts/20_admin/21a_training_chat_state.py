# Training chat system state and workspace validation.

def _build_agent_system_state(tenant_id):
    """Build comprehensive real-time system state for the Super Agent."""
    branding = db.get_branding(tenant_id) or {}
    fields = db.get_fields(tenant_id, active_only=False)
    active_fields = [f for f in fields if f.get('is_active')]
    inactive_fields = [f for f in fields if not f.get('is_active')]
    users = db.get_users_by_tenant(tenant_id)
    sections = db.get_all_sections(tenant_id)
    custom_sections = db.get_custom_sections(tenant_id)
    presentations = db.get_presentations(tenant_id)
    training_data = db.get_training_data(tenant_id)
    active_training = [t for t in training_data if t.get('is_active')]
    templates = db.get_slide_templates(tenant_id)

    field_lines = []
    for f in active_fields[:40]:
        req = ' إلزامي' if f.get('is_required') else 'اختياري'
        custom = ' (مخصص)' if f.get('is_custom') else ' (أساسي)'
        field_lines.append(f"  • {f['field_label']} [{f['field_key']}] — نوع: {f['field_type']}, قسم: {f.get('section_key', 'general')}, {req}{custom}")

    inactive_field_lines = []
    for f in inactive_fields[:15]:
        inactive_field_lines.append(f"  • {f['field_label']} [{f['field_key']}] — معطل")

    user_lines = []
    for u in users:
        status = ' نشط' if u.get('is_active') else ' معطل'
        user_lines.append(f"  • {u['name']} ({u['email']}) — دور: {u['role']}, {status}")

    section_lines = []
    for s in sections:
        custom_tag = ' (مخصص)' if s.get('custom') else ' (أساسي)'
        section_lines.append(f"  • {s.get('label', s['key'])} [{s['key']}]{custom_tag}")

    pres_summary = f"{len(presentations)} عرض"
    if presentations:
        recent = presentations[:5]
        pres_lines = [f"  • {p.get('title', 'بدون عنوان')} — {p.get('slide_count', '?')} شريحة — {p.get('status', 'draft')} — {p.get('created_at', '')[:10]}" for p in recent]
        pres_summary += '\n' + '\n'.join(pres_lines)

    training_lines = []
    for t in active_training[:10]:
        training_lines.append(f"  • [{t['id'][:8]}] {t.get('title', 'بدون عنوان')} — فئة: {t.get('category', 'general')} — {t.get('created_at', '')[:10]}")

    font_selections = db.get_tenant_font_selections(tenant_id)
    current_font_lines = []
    for sel in font_selections:
        if sel.get('font_id'):
            src = db.get_sag_font(sel['font_id']) or {}
            font_label = src.get('font_name') or 'خط مركزي'
        else:
            font_label = os.path.basename(sel.get('custom_font_path') or 'خط مخصص')
        script_label = 'عربي' if sel.get('script') == 'arabic' else 'لاتيني'
        current_font_lines.append(f"  • {script_label} / {sel.get('weight', 'regular')}: {font_label}")

    # The team library and the company generation rules are things the agent can change, so it has
    # to see their current state instead of guessing that they are empty.
    team_entities = db.get_team_entities(tenant_id) or []
    team_lines = [f"  • {item.get('name')} — {item.get('role') or 'بدون دور محدد'}"
                  f"{(' — خبرة ' + str(item.get('experienceYears'))) if item.get('experienceYears') else ''}"
                  for item in team_entities[:20]]
    generation_rules = str(branding.get('generation_rules') or '').strip()

    available_fonts = db.get_sag_fonts()
    available_font_lines = []
    seen_families = set()
    for f in available_fonts:
        family_key = f.get('font_family') or f.get('font_name')
        if family_key in seen_families:
            continue
        seen_families.add(family_key)
        script_label = 'عربي' if f.get('script') == 'arabic' else 'لاتيني'
        default_tag = ' (افتراضي النظام)' if f.get('is_default') else ''
        available_font_lines.append(f"  • {f.get('font_name')} ({script_label}){default_tag}")

    return f"""###  معلومات الشركة:
- اسم الشركة: {branding.get('company_name', 'غير محدد')}
- الشعار النصي: {branding.get('tagline', 'غير محدد')}
- الشعار النصي بالإنجليزية: {branding.get('tagline_en') or 'غير محدد'}

###  الهوية البصرية:
- اللون الرئيسي: {branding.get('primary_color', '#3B6E91')}
- اللون الثانوي: {branding.get('secondary_color', '#254B66')}
- لون التمييز: {branding.get('accent_color', '#6DA3C3')}
- لون الخلفية: {branding.get('background_color', '#F4F9FC')}
- لون النص: {branding.get('text_color', '#333333')}
- الخط: {branding.get('font_family', 'The Sans Arabic')}
- الخط العربي: {branding.get('font_arabic', 'The Sans Arabic')}
- قالب التصميم: {branding.get('design_template', 'modern')}
- نمط البطاقات: {branding.get('card_style', 'bordered')}
- نسبة العرض: {branding.get('slide_ratio', '16:9')}
- الهيدر: {'مفعل' if branding.get('header_enabled') else 'معطل'}
- الفوتر: {'مفعل' if branding.get('footer_enabled') else 'معطل'}
- اللوجو: {'موجود' if branding.get('logo_path') else 'غير مرفوع'}

###  الخطوط:
- التخصيص الحالي: {'الخط الافتراضي (لم يتم تخصيص خط)' if not current_font_lines else ''}
{chr(10).join(current_font_lines) if current_font_lines else ''}
- الخطوط المتاحة للتخصيص ({len(seen_families)} خط):
{chr(10).join(available_font_lines) if available_font_lines else '  لا توجد خطوط مركزية — يمكن للأدمن رفع خط مخصص من صفحة الإعدادات.'}

###  إعدادات الشرائح:
- عدد الشرائح يقرره التوليد تلقائيًا من حجم محتوى المشروع — لا يوجد إعداد له.

###  حقول الإدخال النشطة ({len(active_fields)} حقل):
{chr(10).join(field_lines) if field_lines else '  لا توجد حقول نشطة.'}

###  حقول معطلة ({len(inactive_fields)}):
{chr(10).join(inactive_field_lines) if inactive_field_lines else '  لا توجد حقول معطلة.'}

###  أقسام البيانات ({len(sections)} قسم):
{chr(10).join(section_lines) if section_lines else '  لا توجد أقسام.'}

###  الموظفين ({len(users)} موظف):
{chr(10).join(user_lines) if user_lines else '  لا يوجد موظفين.'}

###  العروض التقديمية:
{pres_summary}

###  سجلات التدريب ({len(active_training)} سجل نشط):
{chr(10).join(training_lines) if training_lines else '  لا توجد سجلات تدريب.'}

###  قوالب الشرائح المخصصة ({len(templates)} قالب):
{chr(10).join([f"  • {t.get('slide_name', t.get('slide_type', '?'))}" for t in templates[:10]]) if templates else '  لا توجد قوالب مخصصة.'}

###  مكتبة فريق العمل ({len(team_entities)} جهة):
{chr(10).join(team_lines) if team_lines else '  لا توجد جهات في المكتبة.'}

###  رصيد الشركة:
- رصيد المحفظة: {format_precise_number(db.get_tenant_balance(tenant_id), grouped=False)} نقطة
- المتبقي من الباقة: {format_precise_number(db.get_package_remaining_sar(tenant_id), grouped=False)} نقطة
- المتاح للإنفاق الإجمالي: {format_precise_number(db.get_tenant_balance(tenant_id) + db.get_package_remaining_sar(tenant_id), grouped=False)} نقطة

###  قواعد التوليد الخاصة بالشركة (تُرسل مع كل توليد شريحة):
{generation_rules if generation_rules else '  لا توجد قواعد مخصصة — التوليد يتبع قواعد المنصة فقط.'}
"""


def _extract_json_actions_from_text(raw_text):
    """Extract all valid JSON objects containing a 'tool' key from text,
    handling code blocks, multi-JSON blocks, trailing text, and formatting quirks."""
    actions = []
    if not raw_text:
        return actions

    # 1. Find blocks inside ```action ... ``` or ```json ... ``` or use full text
    blocks = re.findall(r'```(?:action|json)?\s*\n?([\s\S]*?)```', raw_text)
    if not blocks:
        blocks = [raw_text]

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # Try direct parse first
        try:
            parsed = json.loads(block)
            if isinstance(parsed, dict) and 'tool' in parsed:
                actions.append(parsed)
                continue
            elif isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and 'tool' in item:
                        actions.append(item)
                continue
        except (json.JSONDecodeError, ValueError):
            pass

        # Balanced brace scanner for concatenated or noisy JSONs
        idx = 0
        while idx < len(block):
            start = block.find('{', idx)
            if start == -1:
                break
            depth = 0
            in_str = False
            esc = False
            end = -1
            for i in range(start, len(block)):
                c = block[i]
                if esc:
                    esc = False
                    continue
                if c == '\\' and in_str:
                    esc = True
                    continue
                if c == '"' and not esc:
                    in_str = not in_str
                    continue
                if not in_str:
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
            if end != -1:
                candidate = block[start:end]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict) and 'tool' in parsed:
                        actions.append(parsed)
                except (json.JSONDecodeError, ValueError):
                    pass
                idx = end
            else:
                idx = start + 1

    return actions


def _find_target_field(fields, search_str):
    """Smart field matcher by key, label, transliteration, or partial substring."""
    if not search_str or not fields:
        return None
    search_clean = str(search_str).strip().lower()
    search_key = re.sub(r'[^a-zA-Z0-9_]', '_', search_clean).strip('_')

    # 1. Exact key match
    for f in fields:
        if f['field_key'].lower() == search_clean or (search_key and f['field_key'].lower() == search_key):
            return f

    # 2. Exact label match
    for f in fields:
        if f['field_label'].strip().lower() == search_clean:
            return f

    # 3. Transliterated label match
    ar_map = {
        'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th',
        'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z',
        'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
        'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
        'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ئ': 'y', 'ة': 'a', 'ء': '',
        ' ': '_', 'ـ': '',
    }
    for f in fields:
        label_trans = ''.join(ar_map.get(ch, ch) for ch in f['field_label'].lower())
        label_trans_clean = re.sub(r'[^a-zA-Z0-9_]', '_', label_trans).strip('_')
        if search_key and (search_key == label_trans_clean or label_trans_clean in search_key or search_key in label_trans_clean):
            return f

    # 4. Partial substring match in key or label
    for f in fields:
        if search_clean and (search_clean in f['field_key'].lower() or search_clean in f['field_label'].lower()):
            return f

    return None


def _summarize_agent_workspace(workspace, tenant_id):
    """Return a bounded, non-HTML workspace summary for the agent prompt."""
    if not isinstance(workspace, dict):
        return 'لا توجد مساحة عمل مرسلة من الواجهة.'
    slides = workspace.get('slidesData') if isinstance(workspace.get('slidesData'), list) else []
    plan = workspace.get('slidePlan') if isinstance(workspace.get('slidePlan'), dict) else {}
    presentation_id = workspace.get('presentationId')
    owned = db.get_presentation(presentation_id, tenant_id=tenant_id) if presentation_id else None
    slide_lines = []
    for i, slide in enumerate(slides[:40]):
        if isinstance(slide, dict):
            html = slide.get('html') or ''
            slide_lines.append(f"  • {i + 1}: {slide.get('title', 'بدون عنوان')} — {'HTML موجود' if html else 'HTML مفقود'}")
    return '\n'.join([
        f"- presentationId: {presentation_id or 'غير محفوظ'}",
        f"- العرض يخص الشركة الحالية: {'نعم' if owned else 'لا/غير محفوظ'}",
        f"- عدد الشرائح: {len(slides)}",
        f"- عدد شرائح الخطة: {len(plan.get('slides', [])) if isinstance(plan.get('slides'), list) else 0}",
        '\n'.join(slide_lines) if slide_lines else '  لا توجد شرائح مفتوحة.',
    ])


def _workspace_slides(workspace):
    slides = workspace.get('slidesData') if isinstance(workspace, dict) else None
    return slides if isinstance(slides, list) else []


def _validate_workspace_data(workspace):
    slides = _workspace_slides(workspace)
    errors = []
    slide_div_re = re.compile(r'<div\b[^>]*\bclass\s*=\s*["\'][^"\']*\bslide\b[^"\']*["\']', re.IGNORECASE)
    for index, slide in enumerate(slides):
        html = slide.get('html') if isinstance(slide, dict) else ''
        if not isinstance(html, str) or not html.strip():
            errors.append({'slide_index': index, 'message': 'محتوى الشريحة فارغ'})
            continue
        matches = slide_div_re.findall(html)
        if len(matches) != 1:
            if html.count('class="slide"') == 1 or html.count("class='slide'") == 1:
                continue
            errors.append({'slide_index': index, 'message': 'يجب أن تحتوي الشريحة على div class="slide" واحد فقط'})
    return {'valid': bool(slides) and not errors, 'slide_count': len(slides), 'errors': errors}


# The chat route is gated by `training_data` alone, while several tools reach
# surfaces that carry their own dedicated permission. Every such tool re-checks
# the permission its equivalent route demands, so granting a staff member
# training management cannot widen their authority through model-generated
# actions. Read-only tools any signed-in user may already call stay unmapped.
AGENT_TOOL_PERMISSIONS = {
    'update_branding': 'company_settings',
    'set_font': 'company_settings',
    'set_generation_rules': 'company_settings',
    'add_team_entity': 'company_settings',
    'update_team_entity': 'company_settings',
    'delete_team_entity': 'company_settings',
    'add_field': 'custom_fields',
    'update_field': 'custom_fields',
    'delete_field': 'custom_fields',
    'add_section': 'custom_fields',
    'delete_section': 'custom_fields',
    'update_workspace': 'create_presentation',
    'edit_workspace_slide': 'create_presentation',
    'generate_slide_plan': 'create_presentation',
    'generate_workspace': 'create_presentation',
    'inspect_workspace': 'create_presentation',
    'validate_workspace': 'create_presentation',
    'save_workspace': 'create_presentation',
    'delete_presentation': 'create_presentation',
    'list_presentations': 'view_presentations',
    'export_workspace': 'export_files',
    'add_training': 'training_data',
    'delete_training': 'training_data',
    'list_training': 'training_data',
}

AGENT_PERMISSION_LABELS = {
    'create_presentation': 'إنشاء العروض',
    'view_presentations': 'عرض العروض',
    'company_settings': 'إعدادات الشركة',
    'custom_fields': 'إدارة الحقول',
    'training_data': 'إدارة بيانات التدريب',
    'export_files': 'تصدير الملفات',
}


def _agent_requester_permission_granted(permission_key):
    """Does the user who sent this agent request hold `permission_key`?

    Mirrors require_permission(): the platform super admin, a company admin and
    the tenant-direct login pass every check; anyone else needs the key granted
    on their account. With no request context (tests and internal calls) there
    is no external actor to restrict.
    """
    if not has_request_context():
        return True
    if getattr(g, 'is_admin', False):
        return True
    user_id = getattr(g, 'user_id', None)
    user_role = getattr(g, 'user_role', None)
    if not user_id:
        return True
    permissions = getattr(g, 'user_permissions', None)
    if permissions is None:
        permissions = db.get_user_permissions(user_id, user_role or 'employee')
    return bool(permissions.get(permission_key))
