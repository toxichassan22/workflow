# Training chat tool actions.

def _execute_agent_action(tenant_id, action, reply_text=None, workspace=None):
    """Execute a single agent action and return the result."""
    tool = action.get('tool', '')
    params = action.get('params', {})
    workspace = workspace if isinstance(workspace, dict) else {}
    result = {'tool': tool, 'status': 'success', 'changes': {}}

    required_permission = AGENT_TOOL_PERMISSIONS.get(tool)
    if required_permission and not _agent_requester_permission_granted(required_permission):
        result['status'] = 'error'
        result['error_code'] = 'AGENT_PERMISSION_DENIED'
        label = AGENT_PERMISSION_LABELS.get(required_permission, required_permission)
        result['message'] = f'لم يُنفَّذ الإجراء: حسابك لا يملك صلاحية «{label}»'
        return result

    try:
        # ── Branding ──────────────────────────────────────────────────
        if tool == 'update_branding':
            old_branding = db.get_branding(tenant_id) or {}
            # Filter to allowed branding fields only
            allowed_keys = {
                'primary_color', 'secondary_color', 'accent_color', 'background_color',
                'text_color', 'font_family', 'font_arabic', 'design_template', 'card_style',
                'slide_ratio', 'header_enabled', 'footer_enabled', 'tagline', 'tagline_en', 'company_name',
            }
            updates = {}
            for k, v in params.items():
                if k in allowed_keys:
                    if k in ('header_enabled', 'footer_enabled'):
                        v = 1 if v in (True, 1, '1', 'true', 'نعم') else 0
                    updates[k] = v

            if updates:
                db.update_branding(tenant_id, **updates)
                # Log each change
                for k, new_val in updates.items():
                    old_val = old_branding.get(k)
                    if str(old_val) != str(new_val):
                        db.log_ai_rule_change(tenant_id, 'agent_branding', k, old_val, new_val, risk_level='yellow')
                        result['changes'][k] = {'old': old_val, 'new': new_val}
                result['message'] = f'تم تحديث {len(updates)} إعداد في الهوية البصرية'
            else:
                result['status'] = 'no_changes'
                result['message'] = 'لم يتم تحديد حقول صالحة للتعديل'

        # ── List Fields ───────────────────────────────────────────────
        elif tool == 'list_fields':
            fields = db.get_fields(tenant_id, active_only=False)
            result['data'] = [{
                'field_key': f['field_key'], 'field_label': f['field_label'],
                'field_type': f['field_type'], 'section_key': f.get('section_key', 'general'),
                'is_active': bool(f['is_active']), 'is_custom': bool(f['is_custom']),
                'is_required': bool(f['is_required']),
            } for f in fields]
            result['message'] = f'{len(fields)} حقل في النظام'

        # ── Add Field ─────────────────────────────────────────────────
        elif tool == 'add_field':
            label = (params.get('field_label') or params.get('fieldLabel') or '').strip()
            if not label:
                result['status'] = 'error'
                result['message'] = 'field_label مطلوب'
            else:
                fields = db.get_fields(tenant_id, active_only=False)
                existing = _find_target_field(fields, label) or (
                    _find_target_field(fields, params.get('field_key') or params.get('fieldKey'))
                )
                if existing:
                    key = existing['field_key']
                else:
                    ar_map = {
                        'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th',
                        'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z',
                        'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
                        'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
                        'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ئ': 'y', 'ة': 'a', 'ء': '',
                        ' ': '_', 'ـ': '',
                    }
                    key = params.get('field_key') or params.get('fieldKey') or ''.join(ar_map.get(ch, ch) for ch in label)
                    key = re.sub(r'[^a-zA-Z0-9_]', '_', key.lower()).strip('_')
                    if not key:
                        key = f'field_{_uuid.uuid4().hex[:6]}'

                section_key = params.get('section_key') or params.get('sectionKey') or (existing.get('section_key') if existing else 'general')
                valid_keys = {'general'} | {s['key'] for s in db.get_all_sections(tenant_id)}
                if section_key not in valid_keys and section_key not in {s['key'] for s in db.FIELD_SECTIONS}:
                    db.add_custom_section(tenant_id, section_key, section_key.replace('_', ' ').title())

                raw_opts = (
                    params.get('field_options') or params.get('fieldOptions') or
                    params.get('options') or params.get('choices') or params.get('values')
                )
                options = db._normalize_options_list(raw_opts)
                if not options and reply_text:
                    extracted = re.findall(r'^\s*[\d\-\*\•][\.\)\:]?\s*(.+)$', reply_text, re.MULTILINE)
                    if extracted and len(extracted) >= 2:
                        options = db._normalize_options_list([x for x in extracted if len(x.strip()) < 100])
                    else:
                        match = re.search(r'(?:خيارات|الخيارات|القيمة الجديدة|القيم)[:\s]*([^\n]+)', reply_text)
                        if match:
                            options = db._normalize_options_list(match.group(1))

                field_type = params.get('field_type') or params.get('fieldType') or ('select' if options else 'text')
                if options:
                    field_type = 'select'

                field_id = db.add_custom_field(
                    tenant_id=tenant_id, field_key=key, field_label=label,
                    field_type=field_type,
                    field_options=options,
                    is_required=params.get('is_required') or params.get('isRequired') or False,
                    ai_hint=params.get('ai_hint') or params.get('aiHint') or '',
                    placeholder=params.get('placeholder') or '',
                    section_key=section_key,
                )
                db.log_ai_rule_change(tenant_id, 'agent_field', 'add_field', None, f'{label} [{key}]', risk_level='yellow')
                result['message'] = f'تم تحديث/إضافة حقل "{label}" (المفتاح: {key}) في قسم {section_key}'
                result['field_id'] = field_id

        # ── Update Field ──────────────────────────────────────────────
        elif tool == 'update_field':
            field_key = params.get('field_key') or params.get('fieldKey') or ''
            field_label = params.get('field_label') or params.get('fieldLabel') or ''
            query = field_key or field_label or ''

            raw_updates = params.get('updates', {})
            updates = raw_updates.copy() if isinstance(raw_updates, dict) else {}

            for k, v in params.items():
                if k != 'updates' and k not in updates:
                    updates[k] = v

            fields = db.get_fields(tenant_id, active_only=False)
            target = _find_target_field(fields, query) or _find_target_field(fields, updates.get('field_label') or updates.get('fieldLabel'))

            raw_opts = (
                updates.get('field_options') or updates.get('fieldOptions') or
                updates.get('options') or updates.get('choices') or updates.get('values') or
                params.get('field_options') or params.get('fieldOptions') or
                params.get('options') or params.get('choices') or params.get('values')
            )
            options = db._normalize_options_list(raw_opts)

            if not options and reply_text and (not target or target.get('field_type') == 'select' or 'select' in str(updates.get('field_type') or updates.get('fieldType')).lower()):
                extracted = re.findall(r'^\s*[\d\-\*\•][\.\)\:]?\s*(.+)$', reply_text, re.MULTILINE)
                if extracted and len(extracted) >= 2:
                    options = db._normalize_options_list([x for x in extracted if len(x.strip()) < 100])
                else:
                    match = re.search(r'(?:خيارات|الخيارات|القيمة الجديدة|القيم)[:\s]*([^\n]+)', reply_text)
                    if match:
                        options = db._normalize_options_list(match.group(1))

            if not target:
                label = updates.get('field_label') or updates.get('fieldLabel') or params.get('field_label') or field_key.replace('_', ' ').title()
                field_type = updates.get('field_type') or updates.get('fieldType') or ('select' if options else 'select')
                section_key = updates.get('section_key') or updates.get('sectionKey') or 'compliance'
                ai_hint = updates.get('ai_hint') or updates.get('aiHint') or ''

                ar_map = {
                    'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th',
                    'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z',
                    'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
                    'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
                    'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ئ': 'y', 'ة': 'a', 'ء': '',
                    ' ': '_', 'ـ': '',
                }
                new_key = ''.join(ar_map.get(ch, ch) for ch in label)
                new_key = re.sub(r'[^a-zA-Z0-9_]', '_', new_key.lower()).strip('_')
                if not new_key:
                    new_key = field_key if field_key else f'field_{_uuid.uuid4().hex[:6]}'

                field_id = db.add_custom_field(
                    tenant_id=tenant_id, field_key=new_key, field_label=label,
                    field_type='select' if options else field_type, field_options=options,
                    is_required=updates.get('is_required') or updates.get('isRequired') or False,
                    ai_hint=ai_hint, section_key=section_key
                )
                target = db.get_field_by_id(field_id)

            if target:
                db_updates = {}
                key_map = {
                    'field_label': 'field_label', 'fieldLabel': 'field_label',
                    'is_active': 'is_active', 'isActive': 'is_active',
                    'is_required': 'is_required', 'isRequired': 'is_required',
                    'ai_hint': 'ai_hint', 'aiHint': 'ai_hint',
                    'placeholder': 'placeholder', 'default_value': 'default_value', 'defaultValue': 'default_value',
                    'section_key': 'section_key', 'sectionKey': 'section_key',
                    'field_type': 'field_type', 'fieldType': 'field_type',
                }
                for k, v in updates.items():
                    if k in key_map:
                        if key_map[k] in ('is_active', 'is_required'):
                            v = 1 if v in (True, 1, '1', 'true') else 0
                        db_updates[key_map[k]] = v

                if options:
                    db_updates['field_options'] = options
                    db_updates['field_type'] = 'select'

                if db_updates:
                    db.update_field(target['id'], **db_updates)
                    db.log_ai_rule_change(tenant_id, 'agent_field', f'update_{target["field_key"]}', str(target), str(db_updates), risk_level='yellow')
                    result['message'] = f'تم تحديث حقل "{target["field_label"]}" بنجاح'
                    result['changes'] = db_updates
                else:
                    result['message'] = f'حقل "{target["field_label"]}" تم إعداده بنجاح'

        # ── Delete Field ──────────────────────────────────────────────
        elif tool == 'delete_field':
            query = (
                params.get('field_key') or params.get('field_label') or
                params.get('fieldKey') or params.get('fieldLabel') or ''
            )
            fields = db.get_fields(tenant_id, active_only=False)
            target = _find_target_field(fields, query)
            if not target:
                result['status'] = 'error'
                result['message'] = f'الحقل "{query}" غير موجود'
            elif not target.get('is_custom'):
                result['status'] = 'error'
                result['message'] = f'لا يمكن حذف الحقل الأساسي "{target["field_label"]}". يمكنك تعطيله فقط.'
            else:
                db.delete_field(target['id'])
                db.log_ai_rule_change(tenant_id, 'agent_field', 'delete_field', target['field_label'], None, risk_level='red')
                result['message'] = f'تم حذف الحقل "{target["field_label"]}" ({target["field_key"]}) نهائياً'

        # ── Team library ──────────────────────────────────────────────
        # The company team is shared by every project file, and the agent had no way to touch it
        # although the database functions and the REST endpoints already existed.
        elif tool == 'list_team':
            entities = db.get_team_entities(tenant_id) or []
            result['data'] = [{
                'id': item.get('id'),
                'name': item.get('name'),
                'role': item.get('role'),
                'experienceYears': item.get('experienceYears'),
            } for item in entities]
            result['message'] = f'عدد جهات فريق العمل: {len(entities)}'

        elif tool == 'add_team_entity':
            name = str(params.get('name') or params.get('entity_name') or '').strip()
            if not name:
                result['status'] = 'error'
                result['message'] = 'اسم الجهة مطلوب'
            else:
                entity_id = db.create_team_entity(
                    tenant_id, name,
                    role=str(params.get('role') or '').strip() or None,
                    brief=str(params.get('brief') or '').strip(),
                    experience_years=params.get('experience_years') or params.get('experienceYears'),
                    notable_projects=params.get('notable_projects') or params.get('notableProjects'),
                )
                db.log_ai_rule_change(tenant_id, 'agent_team', 'add_team_entity', None, name, risk_level='yellow')
                result['data'] = {'id': entity_id, 'name': name}
                result['message'] = f'تمت إضافة «{name}» إلى مكتبة فريق العمل'

        elif tool in ('update_team_entity', 'delete_team_entity'):
            query = str(params.get('name') or params.get('entity_id') or params.get('id') or '').strip()
            entities = db.get_team_entities(tenant_id) or []
            target = next((item for item in entities if str(item.get('id')) == query), None)
            if not target:
                normalized = query.casefold()
                target = next((item for item in entities
                               if str(item.get('name') or '').strip().casefold() == normalized), None)
            if not target:
                result['status'] = 'error'
                result['message'] = f'الجهة «{query}» غير موجودة في مكتبة فريق العمل'
            elif tool == 'delete_team_entity':
                db.delete_team_entity(tenant_id, target['id'])
                db.log_ai_rule_change(tenant_id, 'agent_team', 'delete_team_entity', target.get('name'), None, risk_level='red')
                result['message'] = f'تم حذف «{target.get("name")}» من مكتبة فريق العمل'
            else:
                updates = params.get('updates') if isinstance(params.get('updates'), dict) else {}
                key_map = {
                    'role': 'role', 'brief': 'brief', 'sort_order': 'sort_order',
                    'experience_years': 'experience_years', 'experienceYears': 'experience_years',
                    'notable_projects': 'notable_projects', 'notableProjects': 'notable_projects',
                }
                fields = {key_map[key]: value for key, value in updates.items() if key in key_map}
                if not fields:
                    result['status'] = 'no_changes'
                    result['message'] = 'لم يتم تحديد بيانات صالحة للتعديل'
                else:
                    db.update_team_entity(tenant_id, target['id'], **fields)
                    db.log_ai_rule_change(tenant_id, 'agent_team', f'update_{target.get("name")}',
                                          str({k: target.get(k) for k in fields}), str(fields), risk_level='yellow')
                    result['changes'] = fields
                    result['message'] = f'تم تحديث بيانات «{target.get("name")}»'

        # ── Generation rules that ride with every slide prompt ────────
        elif tool == 'get_generation_rules':
            rules = (db.get_branding(tenant_id) or {}).get('generation_rules') or ''
            result['data'] = {'rules': rules}
            result['message'] = ('قواعد التوليد الحالية:\n' + rules) if rules else 'لا توجد قواعد توليد مخصصة بعد'

        elif tool == 'set_generation_rules':
            rules = str(params.get('rules') or params.get('text') or '').strip()
            old_rules = (db.get_branding(tenant_id) or {}).get('generation_rules') or ''
            db.update_branding(tenant_id, generation_rules=rules[:8000])
            db.log_ai_rule_change(tenant_id, 'agent_generation_rules', 'set_generation_rules',
                                  old_rules[:500] or None, rules[:500] or None, risk_level='yellow')
            result['changes'] = {'generation_rules': {'old': old_rules, 'new': rules}}
            result['message'] = 'تم تحديث قواعد التوليد الخاصة بالشركة' if rules else 'تم إلغاء قواعد التوليد المخصصة'

        # ── Ask instead of guessing ───────────────────────────────────
        elif tool == 'ask':
            result['status'] = 'question'
            result['message'] = str(params.get('question') or '').strip() or 'وضّح المطلوب.'

        # ── List Sections ─────────────────────────────────────────────
        elif tool == 'list_sections':
            sections = db.get_all_sections(tenant_id)
            result['data'] = sections
            result['message'] = f'{len(sections)} قسم في النظام'

        # ── Add Section ───────────────────────────────────────────────
        elif tool == 'add_section':
            key = params.get('section_key', '').strip()
            label = params.get('section_label', '').strip()
            if not key or not label:
                result['status'] = 'error'
                result['message'] = 'section_key و section_label مطلوبان'
            else:
                section_id = db.add_custom_section(tenant_id, key, label)
                if section_id:
                    db.log_ai_rule_change(tenant_id, 'agent_section', 'add_section', None, f'{label} [{key}]', risk_level='yellow')
                    result['message'] = f'تم إضافة قسم "{label}" بنجاح'
                else:
                    result['status'] = 'error'
                    result['message'] = f'القسم "{key}" موجود بالفعل'

        # ── Delete Section ────────────────────────────────────────────
        elif tool == 'delete_section':
            key = params.get('section_key', '').strip()
            deleted = db.delete_custom_section(tenant_id, key)
            if deleted:
                db.log_ai_rule_change(tenant_id, 'agent_section', 'delete_section', key, None, risk_level='red')
                result['message'] = f'تم حذف القسم "{key}" وتم نقل حقوله لقسم "عام"'
            else:
                result['status'] = 'error'
                result['message'] = f'القسم "{key}" غير موجود أو لا يمكن حذفه'

        # ── Edit one or more workspace slides ─────────────────────────
        elif tool == 'edit_workspace_slide':
            slides = _workspace_slides(workspace)
            instruction = (params.get('instruction') or params.get('message') or '').strip()
            raw_indices = params.get('slide_indices')
            if raw_indices is None:
                raw_indices = [params.get('slide_index', 0)]
            if not isinstance(raw_indices, list):
                raw_indices = [raw_indices]
            try:
                indices = sorted(set(int(i) for i in raw_indices))
            except (TypeError, ValueError):
                indices = []
            if not instruction or not indices:
                result['status'] = 'error'
                result['message'] = 'instruction و slide_index أو slide_indices مطلوبان'
            elif any(i < 0 or i >= len(slides) for i in indices):
                result['status'] = 'error'
                result['message'] = 'رقم شريحة خارج نطاق مساحة العمل'
            else:
                branding = db.get_branding(tenant_id) or {}
                # Workspace editing used to stop at the raw model HTML. That bypassed the
                # generation finalizer, so a requested company/project logo stayed as a token,
                # or the managed header was rebuilt without the project's logo. Use the same
                # project-aware finalization path as normal generation before returning the slide.
                project_data = workspace.get('projectData') if isinstance(workspace.get('projectData'), dict) else {}
                project_data = dict(project_data)
                creative_images = workspace.get('creativeImages') or workspace.get('images') or {}
                if not isinstance(creative_images, dict):
                    creative_images = {}
                _prepare_generation_logo_context(project_data, branding, tenant_id)
                creative_images = _augment_generation_images(creative_images, project_data, tenant_id)
                team_logo_lines = []
                for team_index, member in enumerate(creative_images.get('team_members') or [], 1):
                    if not isinstance(member, dict):
                        continue
                    name = str(member.get('name') or f'الجهة {team_index}').strip()
                    role = str(member.get('role') or '').strip()
                    token = f'##TEAM_LOGO_{team_index}##'
                    if member.get('logo'):
                        team_logo_lines.append(
                            f'- {name}' + (f' — {role}' if role else '')
                            + f': الشعار متوفر ويجب استخدام {token} عند طلب شعار هذه الجهة.'
                        )
                    else:
                        team_logo_lines.append(
                            f'- {name}' + (f' — {role}' if role else '')
                            + ': لا يوجد شعار مرفوع لهذه الجهة؛ لا تنشئ بديلاً.'
                        )
                team_logo_context = (
                    '\n'.join(team_logo_lines)
                    if team_logo_lines else 'لا توجد شعارات جهات فريق عمل متاحة في مساحة هذا المشروع.'
                )
                dynamic_rules = build_design_rules(branding)
                edited = []
                for index in indices:
                    slide = slides[index]
                    current_html = slide.get('html', '') if isinstance(slide, dict) else ''
                    if not current_html:
                        result['status'] = 'error'
                        result['message'] = f'الشريحة {index + 1} لا تحتوي HTML صالحاً للتعديل'
                        break
                    edit_prompt = f"""{dynamic_rules}

مهمتك تعديل شريحة HTML واحدة فقط.
أعد JSON صالحاً فقط بالمفتاحين html و response.
html يجب أن يكون div class=\"slide\" واحداً كاملاً، بلا markdown أو شرح خارجه.
حافظ على المحتوى غير المطلوب تغييره، ولا تستخدم صوراً خارجية.

قواعد الشعارات:
- شعار الشركة المعتمد يُستخدم بالرمز `##LOGO##` فقط، وتقوم المنظومة باستبداله تلقائياً بالشعار المرفوع للشركة.
- شعار المشروع يُستخدم بالرمز `##PROJECT_LOGO##` فقط عند توفره، ولا تستبدله بشعار الشركة.
- شعار جهة فريق العمل يُستخدم بالرمز `##TEAM_LOGO_N##` حسب ترتيب الجهة في القائمة التالية، ولا تستخدم `##LOGO##` له:
{team_logo_context}
- عند طلب إضافة شعار، ضعه في موضع الهوية المخصص داخل الهيدر أو الموضع الذي طلبه المستخدم، مع الحفاظ على أبعاده وتباينه.
- لا تكتب اسم الشعار كنص ولا تنشئ رابطاً خارجياً ولا تستخدم صورة بديلة.

عنوان الشريحة: {slide.get('title', '')}
الطلب: {instruction}
HTML الحالي:
{current_html}"""
                    response = call_text_chat(edit_prompt, instruction, max_tokens=6000, model=GEMINI_TEXT_MODEL, usage_ctx=_usage_ctx('training_chat', workspace, tenant_id=tenant_id))
                    raw = extract_chat_content(response, 'SUPER-AGENT-SLIDE-EDIT').strip()
                    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw).strip()
                    parsed = None
                    try:
                        parsed = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        match = re.search(r'\{[\s\S]*\}', raw)
                        if match:
                            try:
                                parsed = json.loads(match.group(0))
                            except (json.JSONDecodeError, TypeError):
                                parsed = None
                    html = (parsed.get('html') or '') if isinstance(parsed, dict) else ''
                    if not html and isinstance(parsed, str):
                        html = parsed
                    if not html:
                        match_slide = re.search(r'<div\b[^>]*\bclass\s*=\s*["\'][^"\']*\bslide\b[^"\']*["\'][\s\S]*?</div>\s*$', raw, re.IGNORECASE)
                        if match_slide:
                            html = match_slide.group(0)
                    matches = re.findall(r'<div\b[^>]*\bclass\s*=\s*["\'][^"\']*\bslide\b[^"\']*["\']', html or '', re.IGNORECASE)
                    if not isinstance(html, str) or (len(matches) != 1 and html.count('class="slide"') != 1 and html.count("class='slide'") != 1):
                        result['status'] = 'error'
                        result['message'] = f'فشل التحقق من HTML للشريحة {index + 1}; لم يتم حفظ التعديل'
                        break
                    slide['html'] = slide_engine.finalize_slide_html(
                        html,
                        slide.get('type') or 'content',
                        project_data,
                        branding,
                        creative_images=creative_images,
                        tenant_id=tenant_id,
                        slide_num=index + 1,
                        slide_title=slide.get('title', ''),
                        total_slides=len(slides),
                        content_source=slide.get('content_source'),
                        allow_all_maps=True,
                    )
                    if isinstance(parsed, dict) and parsed.get('response'):
                        slide['agentResponse'] = parsed['response']
                    edited.append(index)
                if edited and result['status'] == 'success':
                    result['changes'] = {'slide_indices': edited}
                    result['data'] = {'slidesData': slides, 'slideCount': len(slides)}
                    result['message'] = f'تم تعديل الشرائح: {", ".join(str(i + 1) for i in edited)}'

        # ── Update workspace project data from chat ───────────────────
        elif tool == 'update_workspace':
            new_data = params.get('projectData')
            if not isinstance(new_data, dict) or not new_data:
                result['status'] = 'error'
                result['message'] = 'أرسل projectData ككائن يحتوي بيانات المشروع'
            else:
                merged = workspace.get('projectData') if isinstance(workspace.get('projectData'), dict) else {}
                merged = {**merged, **new_data}
                result['data'] = {'projectData': merged}
                result['message'] = f'تم تحديث بيانات المشروع ({len(new_data)} حقل)'

        # ── Generate slide plan from workspace project data ───────────
        elif tool == 'generate_slide_plan':
            project_data = clean_project_data(workspace.get('projectData') or {})
            if not project_data:
                result['status'] = 'error'
                result['message'] = 'لا توجد بيانات مشروع في مساحة العمل. استخدم update_workspace أولاً لملء بيانات المشروع من كلام المستخدم.'
            else:
                plan_branding = db.get_branding(tenant_id) or {}
                training_context = db.get_training_context(
                    tenant_id, offer_lang=slide_engine.resolve_offer_lang(project_data)) or ''
                plan_prompt = slide_engine.build_slide_plan_prompt(
                    project_data, plan_branding, tenant_id=tenant_id)
                if training_context:
                    plan_prompt = f"## بيانات خاصة بالشركة\n{training_context}\n\n---\n\n{plan_prompt}"
                plan = None
                last_plan_err = None
                for _attempt in range(3):
                    try:
                        plan_resp = call_text_chat_parallel(
                            "أنت خبير في تحليل المحتوى وتوزيعه على شرائح العروض التقديمية الاستثمارية.",
                            plan_prompt,
                            max_tokens=6000,
                            attempts=2,
                            timeout=45,
                            model=SLIDE_TEXT_MODEL,
                            usage_ctx=_usage_ctx('training_chat', tenant_id=tenant_id)
                        )
                        plan = slide_engine.parse_slide_plan(extract_chat_content(plan_resp, "AGENT-SLIDE-PLAN"), plan_branding, project_data)
                        break
                    except Exception as plan_err:
                        last_plan_err = plan_err
                        time.sleep(1)
                if plan is None:
                    result['status'] = 'error'
                    result['message'] = f'فشل توليد خطة الشرائح: {last_plan_err}'
                else:
                    result['data'] = {'slidePlan': plan}
                    result['message'] = f'تم توليد خطة من {len(plan.get("slides", []))} شريحة — راجعها ثم نفّذ generate_workspace'

        # ── Generate workspace slides from the supplied plan ──────────
        elif tool == 'generate_workspace':
            project_data = clean_project_data(workspace.get('projectData') or {})
            slide_plan = workspace.get('slidePlan') or {}
            slide_plan = slide_engine.normalize_market_section_plan(slide_plan, project_data) or slide_plan
            images = workspace.get('creativeImages') or workspace.get('images') or {}
            plan_slides = slide_plan.get('slides') if isinstance(slide_plan, dict) else None
            if not project_data or not isinstance(plan_slides, list) or not plan_slides:
                result['status'] = 'error'
                missing = []
                if not project_data:
                    missing.append('بيانات المشروع (projectData)')
                if not isinstance(plan_slides, list) or not plan_slides:
                    missing.append('خطة الشرائح (slidePlan)')
                result['message'] = (
                    'مساحة العمل تنقصها: ' + ' و '.join(missing) +
                    '. الخطوات: 1) اجمع بيانات المشروع من المستخدم ونفّذ update_workspace '
                    '2) نفّذ generate_slide_plan لإنشاء الخطة 3) أعد المحاولة.'
                )
            else:
                branding = db.get_branding(tenant_id) or {}
                _prepare_generation_logo_context(project_data, branding, tenant_id)
                training_context = db.get_training_context(
                    tenant_id, offer_lang=slide_engine.resolve_offer_lang(project_data)) or ''
                def call_text_fn(sys_prompt, user_msg, max_tokens=6000):
                    if training_context:
                        sys_prompt = f"{sys_prompt}\n\n## بيانات خاصة بالشركة\n{training_context}"
                    return call_text_chat_parallel(sys_prompt, user_msg, max_tokens=max_tokens, attempts=2, usage_ctx=_usage_ctx('training_chat', workspace, tenant_id=tenant_id))
                htmls = generate_all_slides(
                    slide_plan, project_data, branding, _get_images_info(images, project_data), call_text_fn,
                    map_placeholders=(images.get('map_placeholders', {}) if isinstance(images, dict) else {}),
                    creative_images=images,
                )
                generated = []
                for i, html in enumerate(htmls):
                    info = plan_slides[i] if i < len(plan_slides) else {}
                    generated.append({
                        'html': postprocess_slide(html or '', i + 1, tenant_id),
                        'title': info.get('title', f'شريحة {i + 1}'),
                        'type': info.get('type', 'content'),
                        'designStyle': info.get('design_style', 'cards'),
                    })
                validation = _validate_workspace_data({'slidesData': generated})
                if not validation['valid'] or len(generated) != len(plan_slides):
                    result['status'] = 'error'
                    result['data'] = {'slidesData': generated, 'validation': validation}
                    result['message'] = 'فشل التحقق من التوليد؛ لم يتم اعتماد عرض ناقص'
                else:
                    result['data'] = {'slidesData': generated, 'slideCount': len(generated)}
                    result['changes'] = {'slide_count': len(generated)}
                    result['message'] = f'تم توليد والتحقق من {len(generated)} شريحة'

        # ── Workspace inspection and validation ───────────────────────
        elif tool == 'inspect_workspace':
            slides = _workspace_slides(workspace)
            result['data'] = {
                'presentation_id': workspace.get('presentationId'),
                'title': workspace.get('projectData', {}).get('project_name', 'عرض بدون عنوان') if isinstance(workspace.get('projectData'), dict) else 'عرض بدون عنوان',
                'slide_count': len(slides),
                'slides': [{'index': i, 'title': s.get('title', ''), 'has_html': bool(s.get('html'))} for i, s in enumerate(slides) if isinstance(s, dict)],
            }
            result['message'] = f'تم فحص مساحة العمل: {len(slides)} شريحة'
        elif tool == 'validate_workspace':
            validation = _validate_workspace_data(workspace)
            result['data'] = validation
            if not validation['valid']:
                result['status'] = 'error'
                result['message'] = f"فشل التحقق: {len(validation['errors'])} مشكلة" if validation['errors'] else 'لا توجد شرائح للتحقق'
            else:
                result['message'] = f"التحقق ناجح: {validation['slide_count']} شريحة مكتملة"

        # ── List Presentations ────────────────────────────────────────
        elif tool == 'list_presentations':
            presentations = db.get_presentations(tenant_id)
            result['data'] = [{
                'id': p['id'], 'title': p.get('title', 'بدون عنوان'),
                'slide_count': p.get('slide_count', 0), 'status': p.get('status', 'draft'),
                'created_at': p.get('created_at', ''),
            } for p in presentations[:20]]
            result['message'] = f'{len(presentations)} عرض تقديمي في النظام'

        # ── Save workspace ────────────────────────────────────────────
        elif tool == 'save_workspace':
            validation = _validate_workspace_data(workspace)
            if not validation['valid']:
                result['status'] = 'error'
                result['message'] = 'تم منع الحفظ لأن مساحة العمل غير مكتملة أو تحتوي شرائح غير صالحة'
            else:
                title = (params.get('title') or workspace.get('title') or
                         (workspace.get('projectData') or {}).get('project_name') or 'عرض بدون عنوان').strip()
                slides = _workspace_slides(workspace)
                project_data = dict(workspace.get('projectData')) if isinstance(workspace.get('projectData'), dict) else {}
                # Slides live in slides_data — drop the embedded duplicate.
                project_data.pop('tenantSlidesData', None)
                slides = slide_engine.renumber_presentation_slides(
                    slides, branding=db.get_branding(tenant_id), project_data=project_data,
                    tenant_id=tenant_id,
                    creative_images=_presentation_creative_images(project_data, tenant_id),
                )
                pres_id = workspace.get('presentationId')
                existing = db.get_presentation(pres_id, tenant_id=tenant_id) if pres_id else None
                if pres_id and not existing:
                    raise LookupError('Presentation not found')
                expected_revision = _expected_presentation_revision(workspace, existing)
                saved_revision = _commit_presentation_state(
                    tenant_id, pres_id, title=title, project_data=project_data, slides_data=slides,
                    draft_id=(project_data or {}).get('draftId') or (project_data or {}).get('draft_id') or (existing or {}).get('draft_id'),
                    expected_revision=expected_revision, source='ai', action='حفظ بواسطة وكيل الإدارة',
                    details=['أداة التصميم: save_workspace'],
                )
                pres_id = saved_revision['presentation_id']
                workspace['presentationId'] = pres_id
                workspace['expectedRevision'] = saved_revision['revision']
                if not existing:
                    try:
                        db.link_draft_usage_to_presentation(
                            tenant_id,
                            (project_data or {}).get('draftId') or (project_data or {}).get('draft_id'),
                            pres_id)
                    except Exception as link_error:
                        print(f"[AI-USAGE] usage link failed for presentation {pres_id}: {link_error}")
                result['presentationId'] = pres_id
                result['data'] = {
                    **_presentation_revision_response(saved_revision),
                    'slidesData': _presentation_state(saved_revision['presentation'])['slidesData'],
                    'slideCount': len(slides),
                }
                result['message'] = f'تم حفظ العرض "{title}" وعدد شرائحه {len(slides)}'

        # ── Delete Presentation ───────────────────────────────────────
        elif tool == 'delete_presentation':
            pres_id = params.get('presentation_id', '')
            deleted = db.delete_presentation(pres_id, tenant_id=tenant_id)
            if deleted:
                db.log_ai_rule_change(tenant_id, 'agent_presentation', 'delete', pres_id, None, risk_level='red')
                result['message'] = 'تم حذف العرض التقديمي'
            else:
                result['status'] = 'error'
                result['message'] = 'العرض غير موجود أو لا ينتمي لشركتك'

        # ── Export workspace ──────────────────────────────────────────
        elif tool == 'export_workspace':
            validation = _validate_workspace_data(workspace)
            if not validation['valid']:
                result['status'] = 'error'
                result['message'] = 'تم منع التصدير لأن العرض غير مكتمل أو غير صالح'
            else:
                fmt = (params.get('format') or 'pdf').lower()
                if fmt not in {'pdf', 'pptx'}:
                    result['status'] = 'error'
                    result['message'] = 'صيغة التصدير يجب أن تكون pdf أو pptx'
                else:
                    presentation_id = workspace.get('presentationId')
                    if not presentation_id or not db.get_presentation(presentation_id, tenant_id=tenant_id):
                        result['status'] = 'error'
                        result['message'] = 'يجب حفظ العرض أولاً قبل تصديره، ومعرّف العرض غير صالح لهذه الشركة'
                    else:
                        branding = db.get_branding(tenant_id) or {}
                        output_dir = os.path.join(OUTPUT_DIR, tenant_id)
                        os.makedirs(output_dir, exist_ok=True)
                        title = (workspace.get('projectData') or {}).get('project_name', 'presentation')
                        if fmt == 'pdf':
                            from exports.pdf_export import generate_pdf
                            path = generate_pdf(
                                '\n'.join(s.get('html', '') for s in _workspace_slides(workspace)),
                                title, branding, output_dir
                            )
                        else:
                            from exports.pptx_export import generate_pptx
                            path = generate_pptx(_workspace_slides(workspace), title, branding, output_dir)
                        export_id = db.create_export(presentation_id, tenant_id, fmt, path)
                        result['data'] = {
                            'exportId': export_id,
                            'url': f'/api/exports/{export_id}/download',
                            'format': fmt,
                            'presentationId': presentation_id,
                        }
                        result['message'] = f'تم تصدير العرض بصيغة {fmt.upper()}'

        # ── Add Training ──────────────────────────────────────────────
        elif tool == 'add_training':
            title = params.get('title', '').strip()
            content = params.get('content', '').strip()
            if not title or not content:
                result['status'] = 'error'
                result['message'] = 'title و content مطلوبان'
            else:
                entry_id = db.create_training_entry(
                    tenant_id, title, content,
                    category=params.get('category', 'general')
                )
                result['message'] = f'تم إضافة قاعدة تدريب "{title}"'
                result['entry_id'] = entry_id

        # ── Delete Training ───────────────────────────────────────────
        elif tool == 'delete_training':
            entry_id = params.get('entry_id', '')
            deleted = db.delete_training_entry(tenant_id, entry_id)
            if deleted:
                result['message'] = 'تم حذف سجل التدريب'
            else:
                result['status'] = 'error'
                result['message'] = 'سجل التدريب غير موجود'

        # ── List Training ─────────────────────────────────────────────
        elif tool == 'list_training':
            entries = db.get_training_data(tenant_id)
            result['data'] = [{
                'id': t['id'], 'title': t.get('title', ''), 'category': t.get('category', 'general'),
                'is_active': bool(t.get('is_active', 1)), 'created_at': t.get('created_at', ''),
                'has_image': bool(t.get('image_path')),
            } for t in entries]
            result['message'] = f'{len(entries)} سجل تدريب'

        # ── List Fonts ────────────────────────────────────────────────
        elif tool == 'list_fonts':
            selections = db.get_tenant_font_selections(tenant_id)
            fonts = db.get_sag_fonts()
            result['data'] = {
                'current': [{
                    'script': s['script'], 'weight': s['weight'],
                    'font_id': s.get('font_id'),
                    'custom': bool(s.get('custom_font_path')),
                } for s in selections],
                'available': [{
                    'id': f['id'], 'font_name': f['font_name'], 'font_family': f['font_family'],
                    'script': f['script'], 'weight': f['weight'],
                } for f in fonts],
            }
            result['message'] = f'{len(fonts)} خط متاح، {len(selections)} تخصيص حالي'

        # ── Set Font ──────────────────────────────────────────────────
        elif tool == 'set_font':
            query = (params.get('font_query') or params.get('font_name') or params.get('font_family') or params.get('query') or '').strip()
            weight = (params.get('weight') or 'regular').strip().lower()
            if weight not in {'light', 'regular', 'medium', 'bold', 'black'}:
                weight = 'regular'
            script_filter = (params.get('script') or 'both').strip().lower()
            if not query:
                result['status'] = 'error'
                result['message'] = 'font_query مطلوب (اسم الخط أو default)'
            elif query.lower() in {'default', 'reset', 'الافتراضي', 'الخط الافتراضي'}:
                for script in ('arabic', 'latin'):
                    db.delete_tenant_font_selection(tenant_id, script, weight)
                db.log_ai_rule_change(tenant_id, 'agent_font', 'font_reset', query, 'default', risk_level='yellow')
                result['message'] = 'تم الرجوع للخط الافتراضي'
            else:
                fonts = db.get_sag_fonts()
                q = query.lower()
                matches = [
                    f for f in fonts
                    if q in (f.get('font_name') or '').lower()
                    or q in (f.get('font_family') or '').lower()
                    or ((f.get('font_name') or '').lower() and (f.get('font_name') or '').lower() in q)
                    or ((f.get('font_family') or '').lower() and (f.get('font_family') or '').lower() in q)
                ]
                if not matches:
                    result['status'] = 'error'
                    result['message'] = f'الخط "{query}" غير موجود ضمن الخطوط المتاحة'
                else:
                    exact = [f for f in matches if (f.get('font_family') or '').lower() == q or (f.get('font_name') or '').lower() == q]
                    pool = exact or matches
                    chosen = [f for f in pool if f.get('weight') == weight] or pool
                    applied = []
                    for f in chosen:
                        if script_filter in ('arabic', 'latin') and f['script'] != script_filter:
                            continue
                        db.set_tenant_font_selection(tenant_id, f['script'], weight, font_id=f['id'])
                        applied.append(f)
                    if not applied:
                        result['status'] = 'error'
                        result['message'] = f'الخط "{query}" لا يدعم السكربت المطلوب ({script_filter})'
                    else:
                        names = '، '.join(sorted({f['font_name'] for f in applied}))
                        scripts = ' و '.join('عربي' if s == 'arabic' else 'لاتيني' for s in sorted({f['script'] for f in applied}))
                        db.log_ai_rule_change(tenant_id, 'agent_font', 'set_font', query, names, risk_level='yellow')
                        result['changes']['font'] = {'query': query, 'applied': names}
                        result['message'] = f'تم تخصيص الخط "{names}" ({scripts}) بوزن {weight}'

        # ── Unknown tool ──────────────────────────────────────────────
        else:
            result['status'] = 'error'
            result['message'] = f'أداة غير معروفة: {tool}'

    except db.PresentationRevisionConflict as error:
        result['status'] = 'error'
        result['error_code'] = 'PRESENTATION_REVISION_CONFLICT'
        result['currentRevision'] = error.current_revision
        result['expectedRevision'] = error.expected_revision
        result['message'] = 'تغير العرض منذ فتحه؛ لم تُحفظ هذه التغييرات'
    except Exception as e:
        result['status'] = 'error'
        result['message'] = str(e)
        print(f'[SUPER-AGENT] Action error ({tool}): {e}')

    return result
