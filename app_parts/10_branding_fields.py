


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BRANDING ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/branding', methods=['GET'])
@require_auth
def api_get_branding():
    """Get branding settings for the current tenant."""
    branding = db.get_branding(g.tenant_id)
    if not branding:
        return jsonify({'error': 'Branding not found'}), 404
    return jsonify({'success': True, 'branding': branding})


@app.route('/api/branding', methods=['PUT'])
@require_permission('company_settings')
def api_update_branding():
    """Update branding settings for the current tenant."""
    data = request.json or {}
    # The watermark file is set only through its upload endpoint; a
    # client-sent path must never choose the file on disk.
    data = {key: value for key, value in data.items()
            if key != 'watermark_path'}
    db.update_branding(g.tenant_id, **data)
    branding = db.get_branding(g.tenant_id)
    return jsonify({'success': True, 'branding': branding})


@app.route('/api/branding/template', methods=['POST'])
@require_permission('company_settings')
def api_apply_template():
    """Apply a design template — auto-fills colors and settings."""
    data = request.json or {}
    template_key = data.get('template')
    template = get_template(template_key)
    if not template:
        return jsonify({'error': 'Invalid template'}), 400

    colors = apply_template_colors(template_key)
    updates = {
        'design_template': template_key,
        'card_style': template['card_style'],
    }
    if colors:
        updates.update(colors)

    db.update_branding(g.tenant_id, **updates)
    branding = db.get_branding(g.tenant_id)
    return jsonify({'success': True, 'branding': branding})


@app.route('/api/design-templates', methods=['GET'])
def api_design_templates():
    """List all available design templates (public, no auth needed)."""
    return jsonify({'success': True, 'templates': get_all_templates()})


@app.route('/api/branding/font-status', methods=['GET'])
@require_auth
def api_branding_font_status():
    """Say whether this company's font is really loadable, and from where.

    A font that silently falls back looks identical to a font that was never chosen, so this reports
    the resolved source instead of leaving it to guesswork: a real @font-face with an embedded or
    served file, a `src:local()` name that only works if the machine has that font installed, a
    Google import that needs the network, or nothing at all.
    """
    from design_templates import build_font_css, _load_bundled_fonts
    branding = db.get_branding(g.tenant_id) or {}
    selections = db.get_tenant_font_selections(g.tenant_id) or []
    result = build_font_css(branding, g.tenant_id, embed=False)
    css = (result[0] if result else '') or ''
    family = (result[1] if result else '') or ''
    faces = css.count('@font-face')
    embedded = css.count('base64,')
    served = len(re.findall(r"url\('/tenant-assets/", css))
    google_import = '@import' in css
    # How the glyphs actually arrive decides whether the font can be trusted: a file we ship or
    # serve always renders, a Google import needs the network, and a bare local() name renders only
    # on a machine that happens to have that font installed. The shipped Arabic safety net is not
    # counted as the company's own face, otherwise choosing Arial would report itself as embedded.
    shipped_fallback = 'platform-fallback-arabic' in css
    own_embedded = max(0, embedded - (1 if shipped_fallback else 0))
    if own_embedded:
        renders = 'embedded file'
    elif served:
        renders = 'served file'
    elif google_import:
        renders = 'google web font'
    elif 'src:local(' in css:
        renders = 'installed name only with shipped fallback' if shipped_fallback else 'installed name only'
    elif css:
        renders = 'embedded file' if embedded else 'installed name only'
    else:
        renders = 'nothing'
    local_only = renders == 'installed name only'
    if not css:
        source = 'none'
    elif selections:
        source = 'company selection'
    elif branding.get('font_file_path') or branding.get('font_file_data'):
        source = 'legacy upload'
    else:
        source = 'platform default'

    # Arabic and Latin resolve independently, and a script with no selection keeps the platform
    # default. Picking a Latin-only font therefore left every Arabic word unchanged, which read as
    # "the font does nothing" — so the resolved pair is reported.
    scripts = {}
    for script in ('arabic', 'latin'):
        chosen_faces = [item for item in selections if item.get('script') == script]
        if chosen_faces:
            names = []
            for item in chosen_faces:
                if item.get('custom_font_path') or item.get('custom_font_data'):
                    names.append(os.path.basename(str(item.get('custom_font_path') or 'خط مرفوع')))
                else:
                    font = db.get_sag_font(item.get('font_id')) or {}
                    names.append(font.get('font_name') or font.get('font_family') or 'خط مختار')
            scripts[script] = {'chosen': True, 'font': names[0],
                               'weights': sorted({item.get('weight') for item in chosen_faces if item.get('weight')})}
        else:
            defaults = [font for font in (db.get_sag_fonts(script=script) or []) if font.get('is_default')]
            default = next((font for font in defaults if font.get('weight') == 'regular'), None) or (defaults[0] if defaults else None)
            scripts[script] = {'chosen': False,
                               'font': (default or {}).get('font_name') or (default or {}).get('font_family') or 'الخط الافتراضي',
                               'weights': []}
    return jsonify({
        'success': True,
        'status': {
            'source': source,
            'familyList': family,
            'brandingFontFamily': branding.get('font_family'),
            'selections': [{'script': item.get('script'), 'weight': item.get('weight'),
                            'uploaded': bool(item.get('custom_font_path') or item.get('custom_font_data')),
                            'fontFamily': item.get('font_family')} for item in selections],
            'fontFaces': faces,
            'embeddedFiles': embedded,
            'servedFiles': served,
            'googleImport': google_import,
            'renders': renders,
            'scripts': scripts,
            'shippedArabicFallback': shipped_fallback,
            'localNameOnly': local_only,
            'cssBytes': len(css),
            'bundledFaces': sorted(_load_bundled_fonts().keys()),
            'willRenderRealFont': renders in ('embedded file', 'served file', 'google web font',
                                             'installed name only with shipped fallback'),
        },
    })


@app.route('/api/branding/font.css', methods=['GET'])
@require_auth
def api_branding_font_css():
    """Return the tenant @font-face CSS so the preview matches the exported PDF.

    The rules are scoped to .slide only, so the site UI font is unaffected.
    """
    from design_templates import build_font_css
    import hashlib as _hashlib
    branding = db.get_branding(g.tenant_id) or {}
    css, _family = build_font_css(branding, g.tenant_id, embed=False)
    body = (css or '/* no tenant font */').encode('utf-8')
    etag = '"' + _hashlib.sha1(body).hexdigest() + '"'
    if request.headers.get('If-None-Match') == etag:
        response = app.response_class('', status=304, mimetype='text/css')
        response.headers['ETag'] = etag
        response.headers['Cache-Control'] = 'no-cache'
        return response
    response = app.response_class(body, mimetype='text/css')
    response.headers['ETag'] = etag
    response.headers['Cache-Control'] = 'no-cache'
    response.headers.add('Vary', 'Accept-Encoding')
    return response


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# INPUT FIELDS ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/fields', methods=['GET'])
@require_auth
def api_get_fields():
    """Get all input fields for the current tenant."""
    db.ensure_tenant_prebuilt_fields_active(g.tenant_id)
    active_only = request.args.get('all') != '1'
    fields = db.get_fields(g.tenant_id, active_only=active_only)
    result = []
    for f in fields:
        options = None
        if f.get('field_options'):
            try:
                options = json.loads(f['field_options'])
                if isinstance(options, str):
                    options = [x.strip() for x in options.split(',') if x.strip()]
            except Exception:
                options = [x.strip() for x in str(f['field_options']).split(',') if x.strip()]

        result.append({
            'id': f['id'],
            'fieldKey': f['field_key'],
            'fieldLabel': f['field_label'],
            'fieldType': f['field_type'],
            'fieldOptions': options,
            'sectionKey': f.get('section_key', 'general'),
            'isRequired': bool(f['is_required']),
            'isActive': bool(f['is_active']),
            'isCustom': bool(f['is_custom']),
            'sortOrder': f['sort_order'],
            'placeholder': f.get('placeholder'),
            'defaultValue': f.get('default_value'),
            'aiHint': f.get('ai_hint'),
        })
    return jsonify({'success': True, 'fields': result})


@app.route('/api/fields', methods=['POST'])
@require_permission('custom_fields')
def api_add_field():
    """Add a custom input field."""
    data = request.json or {}
    field_label = (data.get('fieldLabel') or '').strip()
    field_type = data.get('fieldType', 'text')

    if not field_label:
        return jsonify({'error': 'fieldLabel is required'}), 400

    # Auto-generate field_key from label if not provided
    field_key = (data.get('fieldKey') or '').strip()
    if not field_key:
        import re as _re
        # Try transliteration of common Arabic patterns, fallback to field_N
        # Map common Arabic letters to approximate English
        ar_map = {
            'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th',
            'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z',
            'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
            'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
            'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ئ': 'y', 'ة': 'a', 'ء': '',
            ' ': '_', 'ـ': '',
        }
        transliterated = ''
        for ch in field_label:
            transliterated += ar_map.get(ch, ch)
        # Clean: lowercase, replace non-alphanumeric with _, strip leading/trailing _
        field_key = _re.sub(r'[^a-zA-Z0-9_]', '_', transliterated.lower()).strip('_')
        if not field_key:
            field_key = f'field_{_uuid.uuid4().hex[:6]}'

    valid_types = ['text', 'number', 'textarea', 'select', 'date', 'image']
    if field_type not in valid_types:
        return jsonify({'error': f'Invalid fieldType. Must be one of: {valid_types}'}), 400

    # A field must belong to one of this tenant's visible sections.  Keep
    # ``general`` as a backwards-compatible fallback for older custom fields
    # and for fields whose custom section was deleted.
    section_key = data.get('sectionKey', 'general')
    if not isinstance(section_key, str):
        return jsonify({'error': 'sectionKey must be a string'}), 400
    section_key = section_key.strip()
    valid_section_keys = {'general'} | {section['key'] for section in db.get_all_sections(g.tenant_id)}
    if section_key not in valid_section_keys:
        return jsonify({'error': 'Invalid sectionKey for this company'}), 400

    raw_opts = (
        data.get('fieldOptions') or data.get('field_options') or 
        data.get('options') or data.get('choices')
    )
    field_options = db._normalize_options_list(raw_opts)
    if field_options and field_type != 'select':
        field_type = 'select'

    field_id = db.add_custom_field(
        tenant_id=g.tenant_id,
        field_key=field_key,
        field_label=field_label,
        field_type=field_type,
        field_options=field_options,
        is_required=data.get('isRequired', False),
        placeholder=data.get('placeholder'),
        default_value=data.get('defaultValue'),
        ai_hint=data.get('aiHint'),
        sort_order=data.get('sortOrder', 100),
        section_key=section_key,
    )
    return jsonify({'success': True, 'fieldId': field_id}), 201


@app.route('/api/fields/<field_id>', methods=['PUT'])
@require_permission('custom_fields')
def api_update_field(field_id):
    """Update an input field."""
    field = db.get_field_by_id(field_id)
    if not field or field['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'Field not found'}), 404

    data = request.json or {}
    if 'sectionKey' in data:
        section_key = data['sectionKey']
        if not isinstance(section_key, str):
            return jsonify({'error': 'sectionKey must be a string'}), 400
        section_key = section_key.strip()
        valid_section_keys = {'general'} | {section['key'] for section in db.get_all_sections(g.tenant_id)}
        if section_key not in valid_section_keys:
            return jsonify({'error': 'Invalid sectionKey for this company'}), 400
        # Persist the normalized key rather than the untrimmed request value.
        data['sectionKey'] = section_key

    updates = {}
    for k in ['fieldKey', 'field_key', 'fieldLabel', 'field_label', 'fieldType', 'field_type',
              'fieldOptions', 'field_options', 'options', 'choices', 'sectionKey', 'section_key',
              'isRequired', 'is_required', 'isActive', 'is_active', 'sortOrder', 'sort_order',
              'placeholder', 'defaultValue', 'default_value', 'aiHint', 'ai_hint']:
        if k in data:
            db_key = {
                'fieldKey': 'field_key', 'field_key': 'field_key',
                'fieldLabel': 'field_label', 'field_label': 'field_label',
                'fieldType': 'field_type', 'field_type': 'field_type',
                'fieldOptions': 'field_options', 'field_options': 'field_options',
                'options': 'field_options', 'choices': 'field_options',
                'sectionKey': 'section_key', 'section_key': 'section_key',
                'isRequired': 'is_required', 'is_required': 'is_required',
                'isActive': 'is_active', 'is_active': 'is_active',
                'sortOrder': 'sort_order', 'sort_order': 'sort_order',
                'defaultValue': 'default_value', 'default_value': 'default_value',
                'aiHint': 'ai_hint', 'ai_hint': 'ai_hint',
            }.get(k, k)
            updates[db_key] = data[k]

    if 'field_options' in updates:
        updates['field_options'] = db._normalize_options_list(updates['field_options'])
        if updates['field_options']:
            updates['field_type'] = 'select'

    db.update_field(field_id, **updates)
    return jsonify({'success': True})


@app.route('/api/fields/<field_id>', methods=['DELETE'])
@require_permission('custom_fields')
def api_delete_field(field_id):
    """Delete an input field."""
    field = db.get_field_by_id(field_id)
    if not field or field['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'Field not found'}), 404
    db.delete_field(field_id)
    return jsonify({'success': True})


@app.route('/api/fields/<field_id>/toggle', methods=['POST'])
@require_permission('custom_fields')
def api_toggle_field(field_id):
    """Toggle active/inactive state of a field."""
    field = db.get_field_by_id(field_id)
    if not field or field['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'Field not found'}), 404
    new_state = 0 if field['is_active'] else 1
    db.update_field(field_id, is_active=new_state)
    return jsonify({'success': True, 'isActive': bool(new_state)})


@app.route('/api/fields/reorder', methods=['PUT'])
@require_permission('custom_fields')
def api_reorder_fields():
    """Reorder fields. Expects: {fieldIds: ['id1', 'id2', ...]}"""
    data = request.json or {}
    field_ids = data.get('fieldIds', [])
    if not isinstance(field_ids, list):
        return jsonify({'error': 'fieldIds must be a list'}), 400

    if not db.reorder_fields(g.tenant_id, field_ids):
        return jsonify({'error': 'One or more fields do not belong to this company'}), 403
    return jsonify({'success': True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI INPUT BUILDER
# يقترح AI حقول الإدخال المناسبة للشركة بناءً على وصف المشروع + بيانات التدريب
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _flatten_ai_fields(parsed):
    """Normalize an LLM response into a list of field/section dicts."""
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for k in ('fields', 'sections', 'suggestions', 'data', 'items'):
            if k in parsed:
                return parsed[k]
    return []


def _parse_ai_fields_json(text):
    """Extract the first JSON array (or object with fields/sections) from LLM text."""
    # Try code block first
    cb = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)
    if cb:
        try:
            parsed = json.loads(cb.group(1).strip())
            flattened = _flatten_ai_fields(parsed)
            if flattened:
                return flattened
        except (json.JSONDecodeError, ValueError):
            pass
    # Try balanced bracket scan for array
    start = text.find('[')
    if start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
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
                if c == '[':
                    depth += 1
                elif c == ']':
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(text[start:i+1])
                            flattened = _flatten_ai_fields(parsed)
                            if flattened:
                                return flattened
                        except (json.JSONDecodeError, ValueError):
                            pass
                        break
    # Fallback: whole text
    try:
        parsed = json.loads(text.strip())
        flattened = _flatten_ai_fields(parsed)
        if flattened:
            return flattened
    except (json.JSONDecodeError, ValueError):
        pass
    return []


@app.route('/api/ai-input-builder', methods=['POST'])
@require_permission('custom_fields')
def api_ai_input_builder():
    """
    AI suggests input fields for a project based on tenant training context.
    Input: { description: 'مشروع سكني في الرياض...', existingKeys: ['project_name'] }
    Output: { suggestions: [{ fieldKey, fieldLabel, fieldType, sectionKey, fieldOptions, isRequired, placeholder, defaultValue, aiHint, reason }] }
    """
    data = request.json or {}
    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard
    description = (data.get('description') or '').strip()
    if not description:
        return jsonify({'error': 'description is required'}), 400

    existing = db.get_fields(g.tenant_id, active_only=False)
    existing_keys = [f['field_key'] for f in existing] + (data.get('existingKeys') or [])
    training_context = db.get_training_context(g.tenant_id) or ''
    section_keys = [s['key'] for s in db.get_all_sections(g.tenant_id)]

    system_prompt = """أنت مساعد ذكي لمنصة توليد عروض تقديمية عقارية. مهمتك اقتراح حقول إدخال (input fields) مناسبة لمشروع عقاري معيّن بناءً على:
- وصف المشروع.
- نوع الشركة وطبيعة أعمالها (من بيانات التدريب).
- أفضل الممارسات لعروض الاستثمار العقاري.

أعد الرد كـ JSON array فقط، بدون أي شرح إضافي. كل عنصر يمثل حقل إدخال واحد."""

    user_prompt = f"""اقترح حقول إدخال للمشروع التالي:

{description}

البيانات التدريبية الخاصة بالشركة:
{training_context[:2000] if training_context else 'لا يوجد تدريب خاص بالشركة بعد.'}

الحقول الموجودة حالياً (لا تكررها): {', '.join(existing_keys) if existing_keys else 'لا يوجد حقول'}

الأنواع المسموح بها فقط: text, textarea, number, select, date, image.
الأقسام المسموح بها فقط: {', '.join(section_keys)} (أو general إذا لم ينطبق).

المخرجات المطلوبة: JSON array فقط. كل عنصر به هذه المفاتيح:
- fieldKey: مفتاح إنجليزي صغير بدون مسافات (snake_case).
- fieldLabel: اسم الحقل بالعربي.
- fieldType: أحد الأنواع المسموح بها.
- sectionKey: أحد الأقسام المسموح بها.
- fieldOptions: array من strings (إذا كان fieldType = select)، وإلا null.
- isRequired: true/false.
- placeholder: نص توضيحي داخل الحقل (اختياري).
- defaultValue: قيمة افتراضية (اختياري).
- aiHint: توجيه للـ AI عند توليد الشرائح (اختياري).
- reason: جملة قصيرة تبرر لماذا هذا الحقل مهم.

قواعد:
- لا تُرجع أكثر من 8 حقول (لضمان جودة الرد بدون قطع).
- اجعل الرد مدمجاً: لا تكرر الوصف الطويل، واستخدم قيم قصيرة.
- ركّز على حقول تؤثر في العرض التقديمي المالي والتسويقي.
- تجنب الحقول العامة مثل "اسم المشروع" إذا كان موجوداً بالفعل.
- fieldKey يجب أن يكون فريداً وsnake_case.
"""

    try:
        response = call_zai_chat(system_prompt, user_prompt, temperature=0.7, max_tokens=4000, usage_ctx=_usage_ctx('project_data', data))
        content = extract_chat_content(response, "AI-INPUT-BUILDER")
        suggestions = _parse_ai_fields_json(content)

        valid_types = {'text', 'textarea', 'number', 'select', 'date', 'image'}
        valid_sections = set(section_keys) | {'general'}
        cleaned = []
        seen_keys = set()
        for s in suggestions:
            if not isinstance(s, dict):
                continue
            key = re.sub(r'[^a-z0-9_]', '_', (s.get('fieldKey') or '').strip().lower()).strip('_')
            if not key or key in seen_keys or key in existing_keys:
                continue
            seen_keys.add(key)
            ftype = s.get('fieldType', 'text')
            if ftype not in valid_types:
                ftype = 'text'
            section = s.get('sectionKey', 'general')
            if section not in valid_sections:
                section = 'general'
            opts = s.get('fieldOptions') if isinstance(s.get('fieldOptions'), list) else None
            cleaned.append({
                'fieldKey': key,
                'fieldLabel': (s.get('fieldLabel') or key).strip(),
                'fieldType': ftype,
                'sectionKey': section,
                'fieldOptions': opts,
                'isRequired': bool(s.get('isRequired')),
                'placeholder': str(s.get('placeholder') or '').strip(),
                'defaultValue': str(s.get('defaultValue') or '').strip(),
                'aiHint': str(s.get('aiHint') or s.get('reason') or '').strip(),
                'reason': str(s.get('reason') or '').strip(),
            })

        return jsonify({'success': True, 'suggestions': cleaned})
    except Exception as e:
        print(f"[AI-INPUT-BUILDER ERROR] {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai-build-fields', methods=['POST'])
@require_permission('custom_fields')
def api_ai_build_fields():
    """
    AI suggests input fields and auto-creates them in DB (with sections).
    Input: { description: '...' }
    Output: { created: [...], errors: [] }
    """
    data = request.json or {}
    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard
    description = (data.get('description') or '').strip()
    if not description:
        return jsonify({'error': 'description is required'}), 400

    existing = db.get_fields(g.tenant_id, active_only=False)
    existing_keys = [f['field_key'] for f in existing]
    existing_labels = {f['field_label'].strip().lower() for f in existing}
    training_context = db.get_training_context(g.tenant_id) or ''
    section_keys = {s['key'] for s in db.get_all_sections(g.tenant_id)}

    system_prompt = """أنت مساعد ذكي لمنصة توليد عروض تقديمية عقارية. مهمتك اقتراح وبناء حقول إدخال (input fields) مناسبة لمشروع عقاري أو شركة معيّنة.

أعد الرد كـ JSON array فقط. كل عنصر يمثل قسماً أو حقل إدخال واحد."""

    user_prompt = f"""ابنِ حقول إدخال مناسبة للوصف التالي:

{description}

بيانات التدريب الخاصة بالشركة:
{training_context[:2000] if training_context else 'لا يوجد تدريب خاص بالشركة بعد.'}

الحقول الموجودة حالياً (لا تكررها): {', '.join(existing_keys) if existing_keys else 'لا يوجد حقول'}

الأنواع المسموح بها فقط: text, textarea, number, select, date, image.

المخرجات المطلوبة: JSON array فقط. كل عنصر بهذه المفاتيح:
- sectionKey: مفتاح القسم (snake_case). استخدم قسماً منطقيًا مثل: basic, location, financial, features, swot, marketing, timeline, compliance.
- sectionLabel: اسم القسم بالعربي (إذا كان القسم جديدًا).
- fieldKey: مفتاح إنجليزي صغير بدون مسافات (snake_case).
- fieldLabel: اسم الحقل بالعربي.
- fieldType: أحد الأنواع المسموح بها.
- fieldOptions: array من strings (إذا كان fieldType = select)، وإلا null.
- isRequired: true/false.
- placeholder: نص توضيحي داخل الحقل (اختياري).
- defaultValue: قيمة افتراضية (اختياري).
- aiHint: توجيه للـ AI عند توليد الشرائح (اختياري).

قواعد:
- لا تُرجع أكثر من 12 حقل (لضمان جودة الرد).
- اجعل الرد مدمجاً: لا تكرر الوصف الطويل، واستخدم قيم قصيرة.
- fieldKey يجب أن يكون فريداً وsnake_case.
- إذا كان القسم غير موجود في الأقسام المعروفة، سيتم إنشاؤه تلقائياً باستخدام sectionLabel.
"""

    try:
        response = call_zai_chat(system_prompt, user_prompt, temperature=0.7, max_tokens=4000, usage_ctx=_usage_ctx('project_data', data))
        content = extract_chat_content(response, "AI-BUILD-FIELDS")
        suggestions = _parse_ai_fields_json(content)

        valid_types = {'text', 'textarea', 'number', 'select', 'date', 'image'}
        created = []
        errors = []
        for s in suggestions:
            if not isinstance(s, dict):
                continue
            # Expand a section that contains a nested 'fields' list.
            nested = s.get('fields') if isinstance(s.get('fields'), list) else None
            items = nested if nested else [s]
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = re.sub(r'[^a-z0-9_]', '_', (item.get('fieldKey') or item.get('field_key') or '').strip().lower()).strip('_')
                label = (item.get('fieldLabel') or item.get('field_label') or key).strip()
                if not key or not label or key in existing_keys or label.lower() in existing_labels:
                    continue
                ftype = item.get('fieldType') or item.get('field_type') or 'text'
                if ftype not in valid_types:
                    ftype = 'text'
                section = (item.get('sectionKey') or item.get('section_key') or 'general').strip().lower()
                section_label = (item.get('sectionLabel') or item.get('section_label') or section).strip()
                if section not in section_keys and section_label:
                    try:
                        db.add_custom_section(g.tenant_id, section, section_label)
                        section_keys.add(section)
                    except Exception as se:
                        print(f"[AI-BUILD-FIELDS] section creation failed: {se}")
                        section = 'general'
                opts = item.get('fieldOptions') if isinstance(item.get('fieldOptions'), list) else (item.get('field_options') if isinstance(item.get('field_options'), list) else None)
                try:
                    field_id = db.add_custom_field(
                        g.tenant_id, key, label, ftype,
                        field_options=opts,
                        is_required=bool(item.get('isRequired') or item.get('is_required')),
                        placeholder=str(item.get('placeholder') or '').strip() or None,
                        default_value=str(item.get('defaultValue') or item.get('default_value') or '').strip() or None,
                        ai_hint=str(item.get('aiHint') or item.get('ai_hint') or '').strip() or None,
                        section_key=section
                    )
                    created.append({'id': field_id, 'field_key': key, 'field_label': label, 'section_key': section})
                    existing_keys.append(key)
                    existing_labels.add(label.lower())
                except Exception as fe:
                    print(f"[AI-BUILD-FIELDS] field creation failed: {fe}")
                    errors.append(f"{label}: {fe}")

        return jsonify({'success': True, 'created': created, 'errors': errors, 'count': len(created)})
    except Exception as e:
        print(f"[AI-BUILD-FIELDS ERROR] {e}")
        return jsonify({'error': str(e)}), 500
