

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Training Data (per-tenant GLM training)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/training', methods=['GET'])
@require_permission('training_data')
def api_get_training():
    """Get all training data entries for the current tenant."""
    entries = db.get_training_data(g.tenant_id)
    for entry in entries:
        if entry.get('image_path'):
            entry['imageUrl'] = f"/api/training/{entry['id']}/image"
        # Never expose the on-disk, tenant-specific storage path to the browser.
        entry.pop('image_path', None)
    return jsonify({'success': True, 'entries': entries})


@app.route('/api/training', methods=['POST'])
@require_permission('training_data')
def api_add_training():
    """Add a training data entry."""
    data = request.json or {}
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    category = data.get('category', 'general')
    if not title or not content:
        return jsonify({'error': 'title and content are required'}), 400
    entry_id = db.create_training_entry(g.tenant_id, title, content, category)
    return jsonify({'success': True, 'entryId': entry_id}), 201


@app.route('/api/training/<entry_id>', methods=['PUT'])
@require_permission('training_data')
def api_update_training(entry_id):
    """Update a training data entry."""
    data = request.json or {}
    updated = db.update_training_entry(
        g.tenant_id, entry_id,
        **{k: data[k] for k in ['title', 'content', 'category', 'is_active', 'image_description'] if k in data}
    )
    if not updated:
        return jsonify({'error': 'Training entry not found'}), 404
    return jsonify({'success': True})


@app.route('/api/training/<entry_id>', methods=['DELETE'])
@require_permission('training_data')
def api_delete_training(entry_id):
    """Delete a training data entry."""
    if not db.delete_training_entry(g.tenant_id, entry_id):
        return jsonify({'error': 'Training entry not found'}), 404
    return jsonify({'success': True})


@app.route('/api/training/upload-image', methods=['POST'])
@require_permission('training_data')
def api_upload_training_image():
    """Upload an image for training and analyze it with AI Vision.
    Accepts multipart form data with 'image' file and optional 'title' and 'category'.
    Returns the AI-generated analysis as training content."""
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    
    file = request.files['image']
    if not file.filename:
        return jsonify({'error': 'Empty filename'}), 400
    
    title = (request.form.get('title') or '').strip() or 'Training image'
    category = (request.form.get('category') or 'image_reference').strip()[:80]
    image_type = (request.form.get('imageType') or 'reference').strip().lower()
    image_description = (request.form.get('description') or '').strip()[:4000]
    consent = (request.form.get('companyDataConsent') or '').strip().lower()
    valid_image_types = {'logo', 'watermark', 'reference', 'design_sample'}
    if image_type not in valid_image_types:
        return jsonify({'error': 'imageType must be logo, watermark, reference, or design_sample'}), 400
    if consent not in {'1', 'true', 'yes', 'on'}:
        return jsonify({'error': 'Company data consent is required before uploading a training image'}), 400

    # Validate bytes with Pillow instead of trusting the extension or browser MIME type.
    try:
        from PIL import Image, UnidentifiedImageError
        image = Image.open(file.stream)
        if image.width * image.height > 30_000_000:
            return jsonify({'error': 'Image dimensions are too large'}), 400
        detected_format = (image.format or '').upper()
        image.verify()
        file.stream.seek(0)
    except (UnidentifiedImageError, OSError, ValueError):
        return jsonify({'error': 'Invalid image file'}), 400

    extension_by_format = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}
    ext = extension_by_format.get(detected_format)
    if not ext:
        return jsonify({'error': 'Unsupported image format. Use PNG, JPG, or WEBP.'}), 400

    upload_dir = os.path.join(UPLOADS_DIR, 'training', g.tenant_id)
    os.makedirs(upload_dir, exist_ok=True)
    img_filename = f"{_uuid.uuid4().hex}{ext}"
    img_path = os.path.join(upload_dir, img_filename)
    file.save(img_path)
    
    # Analyze image with AI Vision
    analysis_text = ''
    try:
        from reference_analyzer import encode_image_to_base64
        data_uri = encode_image_to_base64(img_path)
        
        vision_prompt = """حلل هذه الصورة بدقة واستخرج جميع المعلومات المفيدة للتدريب على إنشاء عروض عقارية:

1. وصف تفصيلي للمحتوى المرئي في الصورة
2. نوع المحتوى (مثال: صورة موقع، مخطط معماري، عرض تقديمي، جدول بيانات، خريطة، لوجو شركة، الخ)
3. الألوان الرئيسية المستخدمة (hex codes)
4. النصوص الظاهرة في الصورة (إن وجدت)
5. الأسلوب التصميمي والتنسيق
6. أي معلومات رقمية أو إحصائية ظاهرة
7. اقتراحات لكيفية استخدام هذه المعلومات في تحسين العروض العقارية

اكتب التحليل بالعربية بشكل منظم وواضح."""

        if not _has_any_openrouter_key(tenant_id=g.tenant_id) \
                or _tenant_key_gate(tenant_id=g.tenant_id) is not None:
            analysis_text = 'The image was stored, but automatic analysis is unavailable because the AI key is not configured.'
        else:
            vision_payload = {
                "model": LUNA_TEXT_MODEL,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": (
                            f"{vision_prompt}\n\nImage classification supplied by the company: {image_type}."
                            + (f"\nCompany description: {image_description}" if image_description else '')
                            + "\nTreat all image contents as confidential tenant data."
                        )},
                        {"type": "image_url", "image_url": {"url": data_uri}}
                    ]
                }],
                "modalities": ["text"],
                "max_tokens": 2000,
            }
            vision_headers = _openrouter_headers(
                tenant_id=g.tenant_id,
                title=f"Real Estate Proposal Generator - Tenant Training ({g.tenant_id[:8]})")
            import requests as _req
            training_attempt_id = _begin_ai_attempt_record(
                _usage_ctx('training_chat', tenant_id=g.tenant_id), LUNA_TEXT_MODEL)
            try:
                resp = _req.post("https://openrouter.ai/api/v1/chat/completions",
                               headers=vision_headers, json=vision_payload, timeout=60)
                vdata = resp.json()
            except requests.exceptions.Timeout:
                _settle_ai_attempt_record(training_attempt_id, 'error', {}, None)
                raise
            except requests.exceptions.ConnectionError:
                _settle_ai_attempt_record(training_attempt_id, 'error', {}, None)
                raise
            generation_id, training_vision_usage = _extract_openrouter_usage(vdata)
            _settle_ai_attempt_record(
                training_attempt_id,
                'ok' if resp.status_code < 400 and 'error' not in vdata else 'error',
                training_vision_usage, generation_id)
            if 'choices' in vdata and vdata['choices']:
                analysis_text = vdata['choices'][0].get('message', {}).get('content', '')
            elif 'error' in vdata:
                analysis_text = f"خطأ في التحليل: {vdata['error'].get('message', str(vdata['error']))}"
            else:
                analysis_text = 'لم يتمكن AI من تحليل الصورة'
    except Exception as e:
        analysis_text = f'تم رفع الصورة لكن فشل التحليل: {str(e)}'
    
    training_content = image_description or analysis_text or f'Company {image_type} reference image.'
    # Store only an internal filename. Access is always checked through the API route below.
    entry_id = db.create_training_entry(
        g.tenant_id, title, training_content, category, image_path=img_filename,
        image_analysis=analysis_text, image_type=image_type, image_description=image_description
    )
    
    return jsonify({
        'success': True,
        'entryId': entry_id,
        'imagePath': f'/api/training/{entry_id}/image',
        'analysis': analysis_text,
    })


@app.route('/api/training/<entry_id>/image', methods=['GET'])
@require_permission('training_data')
def api_get_training_image(entry_id):
    """Serve one training image only to users in its owning company."""
    entry = db.get_training_entry(g.tenant_id, entry_id)
    if not entry or not entry.get('image_path'):
        return jsonify({'error': 'Training image not found'}), 404

    filename = os.path.basename(str(entry['image_path']))
    if not filename or filename != entry['image_path']:
        # Legacy entries may contain a former URL; accept its filename but never its path.
        filename = os.path.basename(str(entry['image_path']).replace('\\', '/'))
    tenant_dir = os.path.abspath(os.path.join(UPLOADS_DIR, 'training', g.tenant_id))
    image_path = os.path.abspath(os.path.join(tenant_dir, filename))
    if os.path.commonpath([tenant_dir, image_path]) != tenant_dir or not os.path.isfile(image_path):
        return jsonify({'error': 'Training image not found'}), 404

    mimetype = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}.get(
        os.path.splitext(filename)[1].lower(), 'application/octet-stream'
    )
    response = send_file(image_path, mimetype=mimetype, conditional=True)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def _agent_attachment_context(data):
    """Read what the admin attached to a chat message: an image to look at, or a PDF to read.

    Returns a prompt note and the image references for the model. Reading the file is the point:
    the agent is asked to act on documents, and it cannot act on a file it never received.
    """
    notes = []
    images = []
    image_uri = str(data.get('attachedImage') or '').strip()
    if image_uri.startswith('data:image/'):
        images.append({'data_uri': image_uri})
        notes.append('أرفق المستخدم صورة مع رسالته. انظر إليها قبل الرد.')

    document = data.get('attachedFile') if isinstance(data.get('attachedFile'), dict) else {}
    name = str(document.get('name') or 'ملف').strip()
    document_uri = str(document.get('dataUri') or '').strip()
    if document_uri.startswith('data:application/pdf'):
        try:
            payload = base64.b64decode(document_uri.split(',', 1)[1])
            import fitz
            with fitz.open(stream=payload, filetype='pdf') as pdf:
                pages = [page.get_text() for page in pdf]
            text = '\n'.join(pages).strip()
            if text:
                notes.append(f'## محتوى الملف المرفق «{name}» ({len(pages)} صفحة)\n'
                             f'{text[:20000]}')
            else:
                notes.append(f'الملف المرفق «{name}» لا يحتوي نصًا قابلًا للقراءة (صور ممسوحة).')
        except Exception as exc:
            print(f'[SUPER-AGENT] Could not read the attached PDF: {exc}')
            notes.append(f'تعذر قراءة الملف المرفق «{name}».')
    elif document_uri.startswith('data:text/'):
        try:
            payload = base64.b64decode(document_uri.split(',', 1)[1]).decode('utf-8', 'replace')
            notes.append(f'## محتوى الملف المرفق «{name}»\n{payload[:20000]}')
        except Exception as exc:
            print(f'[SUPER-AGENT] Could not read the attached text file: {exc}')

    return ('\n\n'.join(notes), images)


@app.route('/api/training-chat', methods=['POST'])
@require_permission('training_data')
def api_training_chat():
    """Super Agent — full server-aware AI assistant for company admin.
    Understands and can modify: branding, fields, slides, moodboard, users,
    permissions, sections, presentations, and training data."""
    data = request.json or {}
    _billing_guard = _require_billing_balance('designer_chat')
    if _billing_guard is not None:
        return _billing_guard
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'error': 'message is required'}), 400

    history = data.get('history') or []
    workspace = data.get('workspace') or {}
    if isinstance(workspace, dict) and workspace.get('presentationId'):
        workspace_presentation = db.get_presentation(workspace['presentationId'], tenant_id=g.tenant_id)
        if not workspace_presentation:
            return jsonify({'error': 'Presentation not found'}), 404
        try:
            workspace['expectedRevision'] = _expected_presentation_revision(workspace, workspace_presentation)
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
    history_lines = []
    for turn in history[-12:]:
        role = 'المستخدم' if turn.get('role') == 'user' else 'المساعد'
        history_lines.append(f"{role}: {turn.get('text', '')}")
    context = '\n'.join(history_lines)

    # A file the admin attached to this message. Images used to be analysed by a separate endpoint
    # and stored as training text, so the agent answering the message never saw them, and a PDF
    # could not be attached at all.
    attachment_note, attachment_images = _agent_attachment_context(data)

    # ── Build real-time system state ──────────────────────────────────────
    system_state = _build_agent_system_state(g.tenant_id)
    workspace_state = _summarize_agent_workspace(workspace, g.tenant_id)

    # ── System prompt ─────────────────────────────────────────────────────
    system_prompt = f"""أنت "وكيل الإدارة الذكي" (Super Agent) — المساعد التنفيذي الكامل لأدمن الشركة في منصة العروض التقديمية العقارية.
أنت لست مجرد chatbot — أنت وكيل تنفيذي يمتلك صلاحيات كاملة لقراءة وتعديل جميع إعدادات النظام مباشرة.

## حالة النظام الحالية:
{system_state}

## مساحة العمل المفتوحة حالياً:
{workspace_state}

## الأدوات المتاحة لك (Tools):
يمكنك تنفيذ أي من الإجراءات التالية بإرجاع JSON action ضمن ردك.
ضع الـ action داخل بلوك ```action ... ``` في ردك.

### 1. تعديل الهوية البصرية:
```action
{{"tool": "update_branding", "params": {{"primary_color": "#HEX", "secondary_color": "#HEX", "accent_color": "#HEX", "background_color": "#HEX", "text_color": "#HEX", "font_family": "...", "font_arabic": "...", "design_template": "modern|classic|dark|corporate|luxury", "card_style": "bordered|shadow|flat|glass", "slide_ratio": "16:9|4:3", "header_enabled": 1, "footer_enabled": 1, "header_height": 56, "footer_height": 36, "moodboard_enabled": 1, "cover_image_enabled": 1, "tagline": "..."}}}}
```
ملاحظة: أرسل فقط الحقول التي يريد المستخدم تعديلها، ليس كلها.

### 2. تعديل إعدادات الشرائح:
```action
{{"tool": "update_branding", "params": {{"min_slides": N, "default_slide_count": N, "lock_slide_count": 0, "moodboard_count": N}}}}
```
ملاحظة: لا يوجد حد أعلى لعدد الشرائح؛ `min_slides` هو الحد الأدنى فقط والعدد النهائي يتبع حجم محتوى المشروع. لقفل العدد على رقم بالضبط استخدم `lock_slide_count: 1` مع `default_slide_count`.

### 3. عرض الحقول:
```action
{{"tool": "list_fields"}}
```

### 4. إضافة حقل جديد:
```action
{{"tool": "add_field", "params": {{"field_label": "...", "field_type": "text|number|textarea|select|date", "field_options": ["اختيار 1", "اختيار 2"], "section_key": "basic|location|financial|project|swot|...", "is_required": false, "ai_hint": "...", "placeholder": "..."}}}}
```

### 5. تعديل حقل (تفعيل/تعطيل/تغيير الخيارات):
```action
{{"tool": "update_field", "params": {{"field_key": "...", "updates": {{"is_active": 1, "field_label": "...", "field_type": "select", "field_options": ["اختيار 1", "اختيار 2"], "ai_hint": "..."}}}}}}
```
ملاحظة: عند إضافة أو تحديث خيارات قائمة مسدلة (dropdown)، تأكد دائماً من تمرير "field_type": "select" و تمرير مصفوفة JSON تحتوي الخيارات بالشكل: "field_options": ["خيار 1", "خيار 2"].

### 6. حذف حقل مخصص:
```action
{{"tool": "delete_field", "params": {{"field_key": "..."}}}}
```

### 7. عرض المستخدمين:
```action
{{"tool": "list_users"}}
```

### 8. تعديل صلاحيات موظف:
```action
  {{"tool": "set_permission", "params": {{"user_email": "...", "permission": "dashboard|create_presentation|view_presentations|generate_images|generate_maps|company_settings|custom_fields|manage_users|ai_rules|training_data|approvals|export_files", "granted": true}}}}
```

### 9. تفعيل/تعطيل موظف:
```action
{{"tool": "toggle_user", "params": {{"user_email": "...", "is_active": true}}}}
```
ولإضافة موظف جديد:
```action
{{"tool": "add_user", "params": {{"name": "...", "email": "...", "role": "employee", "password": "..."}}}}
```
- `password` اختياري؛ إن أُرسل فيجب أن يطابق سياسة المنصة (10 أحرف على الأقل وتشمل حروفًا وأرقامًا).
- بدون `password` يُنشأ الحساب برابط تعيين كلمة مرور لمرة واحدة يعود في النتيجة — لا تخترع كلمة مرور افتراضية أبدًا.
- لا تعرض كلمة المرور ولا تكررها في الرد؛ النتيجة نفسها لا تحملها.

### 10. عرض الأقسام:
```action
{{"tool": "list_sections"}}
```

### 11. إضافة قسم جديد:
```action
{{"tool": "add_section", "params": {{"section_key": "...", "section_label": "..."}}}}
```

### 12. حذف قسم:
```action
{{"tool": "delete_section", "params": {{"section_key": "..."}}}}
```

### 13. عرض العروض التقديمية:
```action
{{"tool": "list_presentations"}}
```

### 14. حذف عرض تقديمي:
```action
{{"tool": "delete_presentation", "params": {{"presentation_id": "..."}}}}
```

### 15. إضافة قاعدة تدريب:
```action
{{"tool": "add_training", "params": {{"title": "...", "content": "...", "category": "general|design|content|style"}}}}
```

### 16. حذف سجل تدريب:
```action
{{"tool": "delete_training", "params": {{"entry_id": "..."}}}}
```

### 17. عرض سجلات التدريب:
```action
{{"tool": "list_training"}}
```

### 18. قراءة مساحة العرض المفتوح والتحقق منه:
```action
{{"tool": "inspect_workspace"}}
```
```action
{{"tool": "validate_workspace"}}
```

### 19. تعديل شريحة أو أكثر في العرض المفتوح:
```action
{{"tool": "edit_workspace_slide", "params": {{"slide_index": 0, "instruction": "..."}}}}
```
يمكن تمرير `slide_indices` كمصفوفة لتعديل أكثر من شريحة، وتنفذ الأداة التعديل لكل شريحة مع تحقق بعد كل تعديل.
عند طلب إضافة شعار الشركة أو شعار المشروع إلى شريحة، استخدم الشعار الموجود فعلياً في الهوية أو بيانات المشروع:
`##LOGO##` لشعار الشركة و`##PROJECT_LOGO##` لشعار المشروع. لا تكتب اسم الشعار كنص، ولا تستخدم رابطاً خارجياً أو صورة بديلة.
شعار جهة من فريق العمل ليس شعار الشركة: استخدم الرمز `##TEAM_LOGO_N##`، حيث يطابق `N` ترتيب الجهة في قائمة فريق العمل الحالية، ولا تستبدله بـ `##LOGO##`.
مكان شعار الشركة الافتراضي هو الهيدر المعتمد للشريحة، ويجب الحفاظ على الشعار الموجود إذا كان الهيدر يحتويه.

### 20. حفظ مساحة العمل:
```action
{{"tool": "save_workspace", "params": {{"title": "..."}}}}
```

### 21. تصدير العرض المفتوح:
```action
{{"tool": "export_workspace", "params": {{"format": "pdf|pptx"}}}}
```

### 22. توليد الشرائح من الخطة المفتوحة:
```action
{{"tool": "generate_workspace", "params": {{"regenerate": true}}}}
```

### 23. ملء بيانات المشروع في مساحة العمل من كلام المستخدم:
```action
{{"tool": "update_workspace", "params": {{"projectData": {{"project_name": "...", "project_type": "...", "location_address": "...", "budget": "..."}}}}}}
```
استخدمها عندما يعطيك المستخدم بيانات مشروع في المحادثة ويريد إنشاء عرض منها. أرسل الحقول المتوفرة فقط.

### 24. توليد خطة الشرائح من بيانات المشروع:
```action
{{"tool": "generate_slide_plan"}}
```
تتطلب projectData في مساحة العمل (استخدم update_workspace أولاً إن لزم).

### 25. عرض الخطوط المتاحة والتخصيص الحالي:
```action
{{"tool": "list_fonts"}}
```

### 26. تخصيص خط الشركة أو الرجوع للخط الافتراضي:
```action
{{"tool": "set_font", "params": {{"font_query": "اسم الخط أو عائلته من قائمة الخطوط المتاحة أو default", "weight": "regular"}}}}
```
- عند اختيار خط يدعم العربية واللاتينية يُطبَّق على الاثنين تلقائياً.
- استخدم "default" في font_query للرجوع للخط الافتراضي.
- رفع ملف خط جديد يتم فقط من إعدادات الشركة (منطقة السحب والإفلات) — إذا طلب المستخدم خطاً غير موجود في القائمة، أخبره برفعه أولاً من الإعدادات.

### 27. فريق العمل (مكتبة الشركة المشتركة):
```action
{{"tool": "list_team"}}
```
```action
{{"tool": "add_team_entity", "params": {{"name": "...", "role": "...", "brief": "...", "experience_years": "...", "notable_projects": "..."}}}}
```
```action
{{"tool": "update_team_entity", "params": {{"name": "الاسم الحالي أو معرفه", "updates": {{"role": "...", "brief": "...", "experience_years": "...", "notable_projects": "..."}}}}}}
```
```action
{{"tool": "delete_team_entity", "params": {{"name": "الاسم أو المعرف"}}}}
```
- المكتبة مشتركة بين كل ملفات المشاريع، فأي تعديل هنا يظهر في كل عرض جديد.
- الاستبعاد لملف واحد فقط يتم من صفحة فريق العمل داخل المشروع، لا من هنا.

### 28. قواعد التوليد الخاصة بالشركة (تُضاف إلى برومبت توليد الشرائح):
```action
{{"tool": "get_generation_rules"}}
```
```action
{{"tool": "set_generation_rules", "params": {{"rules": "نص القواعد الملزمة لتوليد الشرائح"}}}}
```
- هذه القواعد تُرسل حرفيًا مع كل توليد شريحة وكل تعديل تصميم، فوق قواعد التصميم الأساسية.
- اكتبها أوامر واضحة وقابلة للتنفيذ (ترتيب المحاور، ما يُعرض وما لا يُعرض، صيغة الأرقام، لغة العناوين).
- ممنوع أن تخالف قواعد المنصة الثابتة: ممنوع اختراع معلومة، وممنوع الأيقونات والإيموجي، والأرقام تُنقل كما هي.
- استخدم set_generation_rules لتعديل «برومبت التوليد»؛ لا توجد طريقة أخرى لتغييره.

### 29. سؤال المستخدم عند عدم الوضوح:
```action
{{"tool": "ask", "params": {{"question": "سؤال عربي واحد قصير"}}}}
```

## سير العمل الكامل لإنشاء عرض جديد من المحادثة:
1. اجمع بيانات المشروع من كلام المستخدم (اسم المشروع، النوع، الموقع، المساحات، الميزانية...) ونفّذ `update_workspace`
2. نفّذ `generate_slide_plan` لإنشاء خطة الشرائح
3. نفّذ `generate_workspace` لتوليد الشرائح فعلياً
4. أخبر المستخدم أن العرض جاهز في صفحة معاينة الشرائح
إذا كان مساحة العمل تحتوي بيانات وخطة مسبقاً، تجاوز الخطوتين 1-2 مباشرة إلى 3.
لا تنفذ التوليد أو التعديل أو التصدير إذا لم تتوفر مساحة عمل صالحة. نفذ الأدوات بالترتيب: inspect ثم التنفيذ ثم validate ثم save/export عند طلب المستخدم.

## قواعد مهمة وحاسمة:
1.  الفرق بين "الشرائح" (Slides) و "حقول الإدخال" (Input Fields):
   - عندما يطلب المستخدم إضافة أو وصف أو تعديل **شريحة** (مثل: "شريحة للجداول"، "شريحة للدراسات"، "شريحة الخريطة"، "أضف شريحة كذا")، فهذا يخص **العرض التقديمي والشرائح** فقط. **يُمنع منعاً باتاً** استخدام أدوات إنشاء أو تعديل الحقول (`add_field` / `update_field`)!
   - تُنشأ وتعدل الحقول (`add_field`/`update_field`) **فقط وفقط** إذا طلب المستخدم صراحة كلمة "حقل" أو "حقل إدخال جديد" أو "تعديل حقل" في استمارة البيانات!
2. عند الاستفسار: أجب بدقة بناءً على حالة النظام الفعلية أعلاه.
3. عند التعديل: نفّذ التعديل بإرجاع بلوك ```action``` ثم اشرح ما تم.
4. يمكنك تنفيذ عدة actions في رد واحد (كل واحدة في بلوك ```action``` منفصل).
5. كن مباشراً، ودياً، وذكياً. لا تتظاهر بعدم معرفة النظام.
6. بعد تنفيذ أي action اذكر القيمة القديمة والجديدة.
7. إذا طلب المستخدم شيء خطير (حذف عروض، تعطيل موظفين)، نفذه مباشرة لكن حذّره بوضوح.
   آخر مدير شركة نشط لا يمكن تعطيله؛ إذا طُلب ذلك فأخبر المستخدم أنه مرفوض بدل تنفيذه.
8. **اسأل بدل أن تخمّن:** إذا كان الطلب غامضًا أو يقبل تنفيذين مختلفين، أو لم تعرف الحقل أو القسم أو
   الجهة أو الموظف المقصود، أو كان التنفيذ سيحذف أو يستبدل شيئًا قائمًا ولست متأكدًا أنه مقصود، أو
   أرفق المستخدم ملفًا دون أن يوضح المطلوب منه — أعد `ask` بسؤال واحد محدد ولا تنفّذ أي action آخر
   في نفس الرد. تنفيذ خاطئ على إعدادات الشركة أسوأ من سؤال واحد.
9. **الحقول الأصلية للنظام لا تُحذف.** `delete_field` تعمل على الحقول المضافة فقط؛ الحقل الأصلي
   يُعطَّل بـ `update_field` مع `is_active: 0` ويمكن إعادة تفعيله. لا تَعِد المستخدم بحذف حقل أصلي.
10. عند طلب تعديل «شكل العرض» أو «قواعد التوليد» أو «برومبت التوليد» استخدم `set_generation_rules`،
   وعند طلب تعديل الألوان والخطوط وأبعاد الشريحة استخدم `update_branding`. لا تخلط بينهما.
11. إذا أرفق المستخدم ملفًا أو صورة: اقرأها فعلًا واستخرج منها ما يخص الطلب، واذكر في ردك ما فهمته
   منها قبل التنفيذ. إن كان الملف غير مقروء فقل ذلك بصراحة ولا تخمّن محتواه.
"""

    if attachment_note:
        system_prompt += f'\n\n## ملف أرفقه المستخدم مع رسالته\n{attachment_note}'

    user_prompt = (context + '\n\nالمستخدم: ' + message + '\n\nوكيل الإدارة:') if context else ('المستخدم: ' + message + '\n\nوكيل الإدارة:')

    try:
        # This agent changes the company's settings, so it runs on the strong model with real
        # reasoning instead of the fast text model, and with room to plan several tool calls.
        response = call_zai_chat(system_prompt, user_prompt, max_tokens=6000,
                                 model=SLIDE_TEXT_MODEL, reasoning_effort='medium',
                                 image_references=attachment_images or None,
                                 usage_ctx=_usage_ctx('training_chat', data))
        reply = extract_chat_content(response, 'SUPER-AGENT')
    except Exception as e:
        print(f'[SUPER-AGENT] AI reply failed: {e}')
        reply = 'أهلاً! أنا وكيل الإدارة الذكي الخاص بشركتك. أقدر أساعدك في أي إعداد — من الألوان والحقول حتى الموظفين والصلاحيات.'

    # ── Execute any actions embedded in the reply ─────────────────────────
    actions_executed = []
    parsed_actions = _extract_json_actions_from_text(reply)

    # ── Fallback intent extraction if LLM didn't format an action block ──
    if not parsed_actions and message:
        # 1. Moodboard count intent
        mb_match = re.search(r'(?:مود\s*بورد|مودبورد|صور|عدد الصور).+?(\d+)', message) or re.search(r'(\d+).+?(?:مود\s*بورد|مودبورد|صور)', message)
        if mb_match:
            try:
                num = int(mb_match.group(1))
                if 1 <= num <= 20:
                    parsed_actions.append({
                        'tool': 'update_branding',
                        'params': {'moodboard_count': num}
                    })
                    reply = f"تم التعديل!  عدد صور المود بورد تم تغييره إلى **{num} صور**. الآن كل عرض تقديمي سيتم إنشاؤه سيضم {num} صور في شريحة المود بورد."
            except ValueError:
                pass

        # 2. Slide count intent
        slide_match = re.search(r'(?:شرائح|شريحة|عدد الشرائح).+?(\d+)', message) or re.search(r'(\d+).+?(?:شرائح|شريحة)', message)
        if not parsed_actions and slide_match:
            try:
                num = int(slide_match.group(1))
                if 1 <= num <= 50:
                    # Only the minimum binds the planner; the upper end is open, so a requested
                    # number is stored as the default and the floor, never as a ceiling.
                    parsed_actions.append({
                        'tool': 'update_branding',
                        'params': {'default_slide_count': num, 'min_slides': num}
                    })
                    reply = f"تم التعديل!  عدد الشرائح الافتراضي تم تغييره إلى **{num} شريحة**، وهو الحد الأدنى أيضًا. لا يوجد حد أعلى: العدد النهائي يتبع حجم محتوى المشروع، ولقفله على {num} بالضبط فعّل «قفل عدد الشرائح»."
            except ValueError:
                pass

        # 3. Color intent (hex codes like #7a6938, #a8a851, etc.)
        hex_matches = re.findall(r'#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b', message)
        if not parsed_actions and hex_matches:
            full_hexes = [f"#{h}" for h in hex_matches]
            color_params = {}

            lines = message.split('\n')
            for line in lines:
                line_hexes = re.findall(r'#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b', line)
                if not line_hexes:
                    continue
                hex_val = f"#{line_hexes[0]}"
                line_lower = line.lower()
                if 'primary' in line_lower or 'أساسي' in line_lower or 'الأساسي' in line_lower or 'الرئيسي' in line_lower:
                    color_params['primary_color'] = hex_val
                elif 'secondary' in line_lower or 'ثانوي' in line_lower or 'الثانوي' in line_lower or 'فرعي' in line_lower:
                    color_params['secondary_color'] = hex_val
                elif 'accent' in line_lower or 'أكسنت' in line_lower or 'تمييز' in line_lower:
                    color_params['accent_color'] = hex_val
                elif 'background' in line_lower or 'خلفية' in line_lower or 'الخلفية' in line_lower:
                    color_params['background_color'] = hex_val
                elif 'text' in line_lower or 'نص' in line_lower or 'النص' in line_lower:
                    color_params['text_color'] = hex_val

            if not color_params and len(full_hexes) >= 1:
                color_params['primary_color'] = full_hexes[0]
                if len(full_hexes) >= 2:
                    color_params['secondary_color'] = full_hexes[1]
                if len(full_hexes) >= 3:
                    color_params['accent_color'] = full_hexes[2]

            if color_params:
                parsed_actions.append({
                    'tool': 'update_branding',
                    'params': color_params
                })
                desc = ', '.join([f"{k}: {v}" for k, v in color_params.items()])
                reply = f"تم التعديل!  تم تحديث ألوان الهوية البصرية للشركة: ({desc})."

        # 4. Revert / Reset colors intent ("رجع الألوان", "استرجع الألوان", "الألوان القديمة", "الألوان الافتراضية")
        if not parsed_actions and any(kw in message for kw in ['رجع الالوان', 'رجع الألوان', 'الالوان القديمه', 'الألوان القديمة', 'الالوان السابقة', 'الألوان السابقة', 'استرجاع الالوان', 'استرجاع الألوان', 'الالوان الافتراضية', 'الألوان الافتراضية', 'القديمة', 'القديمه']):
            default_colors = {
                'primary_color': '#3B6E91',
                'secondary_color': '#254B66',
                'accent_color': '#D97706',
                'background_color': '#F8FAFC',
                'text_color': '#1E293B'
            }
            parsed_actions.append({
                'tool': 'update_branding',
                'params': default_colors
            })
            reply = "تم استرجاع الألوان القديمة والافتراضية للهوية البصرية بنجاح!  (Primary: #3B6E91, Secondary: #254B66)."

        # 5. Font intent ("غيّر الخط إلى X" / "استخدم خط X" / "رجّع الخط الافتراضي")
        font_words = {'خط', 'الخط', 'خطوط', 'الخطوط', 'بالخط', 'فونت', 'الفونت'}
        tokens = set(re.findall(r'[؀-ۿ]+|[A-Za-z]+', message))
        if not parsed_actions and (tokens & font_words or 'font' in message.lower()):
            msg_lower = message.lower()
            font_hit = None
            for f in db.get_sag_fonts():
                name = (f.get('font_name') or '').lower()
                family = (f.get('font_family') or '').lower()
                if (name and name in msg_lower) or (family and family in msg_lower):
                    font_hit = f
                    break
            if font_hit:
                parsed_actions.append({'tool': 'set_font', 'params': {'font_query': font_hit['font_name']}})
                reply = f"تم تخصيص خط الشركة إلى **{font_hit['font_name']}**. "
            elif any(kw in message for kw in ['الخط الافتراضي', 'رجع الخط', 'رجّع الخط', 'استرجاع الخط']):
                parsed_actions.append({'tool': 'set_font', 'params': {'font_query': 'default'}})
                reply = 'تم الرجوع للخط الافتراضي للشركة. '

    # A question is the whole answer: nothing else runs in that turn, so an ambiguous request cannot
    # half-apply while the agent is still asking what was meant.
    question = next((action for action in parsed_actions
                     if isinstance(action, dict) and action.get('tool') == 'ask'), None)
    if question:
        parsed_actions = [question]

    for action in parsed_actions:
        try:
            result = _execute_agent_action(g.tenant_id, action, reply_text=reply, workspace=workspace)
            actions_executed.append(result)
            # Chain workspace mutations so sequential tools in the same reply
            # (update_workspace إلى generate_slide_plan إلى generate_workspace) see updates.
            rdata = result.get('data') if isinstance(result, dict) else None
            if isinstance(rdata, dict):
                if isinstance(rdata.get('projectData'), dict):
                    workspace['projectData'] = rdata['projectData']
                if isinstance(rdata.get('slidePlan'), dict):
                    workspace['slidePlan'] = rdata['slidePlan']
                if isinstance(rdata.get('slidesData'), list):
                    workspace['slidesData'] = rdata['slidesData']
            print(f'[SUPER-AGENT] Executed: {action.get("tool")} إلى {result.get("status")}')
        except Exception as ex:
            print(f'[SUPER-AGENT] Action execution error: {ex}')
            actions_executed.append({'status': 'error', 'message': str(ex)})

    # ── Clean action blocks from the display reply ────────────────────────
    clean_reply = re.sub(r'```action\s*\n?[\s\S]*?```', '', reply).strip()
    # Remove leftover empty lines
    clean_reply = re.sub(r'\n{3,}', '\n\n', clean_reply).strip()

    if question:
        asked = next((item.get('message') for item in actions_executed
                      if isinstance(item, dict) and item.get('status') == 'question'), '')
        if asked and asked not in clean_reply:
            clean_reply = (clean_reply + '\n\n' + asked).strip() if clean_reply else asked
    denied = [item for item in actions_executed
              if isinstance(item, dict) and item.get('error_code') == 'AGENT_PERMISSION_DENIED']
    if not clean_reply and actions_executed:
        clean_reply = '' if len(denied) == len(actions_executed) else ' تم تنفيذ الإجراء بنجاح.'
    if denied:
        note = ('لم تُنفَّذ الإجراءات المطلوبة لأنها تتجاوز صلاحيات حسابك.'
                if len(denied) == len(actions_executed)
                else 'بعض الإجراءات لم تُنفَّذ لأنها تتجاوز صلاحيات حسابك.')
        clean_reply = (clean_reply + '\n\n' + note).strip() if clean_reply else note

    # Persist the turn so platform support can later review exactly what the
    # company asked and what the agent answered and ran (super-admin surface).
    try:
        db.log_agent_chat(
            g.tenant_id, g.user_id, g.user_name, message, clean_reply,
            [{'tool': item.get('tool'), 'status': item.get('status'),
              'error_code': item.get('error_code'),
              'message': item.get('message')}
             for item in actions_executed if isinstance(item, dict)],
        )
    except Exception as log_exc:
        print(f'[SUPER-AGENT] chat log write failed: {log_exc}')

    return jsonify({
        'success': True,
        'reply': clean_reply,
        'actions': actions_executed,
        'awaitingAnswer': bool(question),
    })


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
- الهيدر: {'مفعل' if branding.get('header_enabled') else 'معطل'} (ارتفاع {branding.get('header_height', 56)}px)
- الفوتر: {'مفعل' if branding.get('footer_enabled') else 'معطل'} (ارتفاع {branding.get('footer_height', 36)}px)
- اللوجو: {'موجود' if branding.get('logo_path') else 'غير مرفوع'}

###  الخطوط:
- التخصيص الحالي: {'الخط الافتراضي (لم يتم تخصيص خط)' if not current_font_lines else ''}
{chr(10).join(current_font_lines) if current_font_lines else ''}
- الخطوط المتاحة للتخصيص ({len(seen_families)} خط):
{chr(10).join(available_font_lines) if available_font_lines else '  لا توجد خطوط مركزية — يمكن للأدمن رفع خط مخصص من صفحة الإعدادات.'}

###  إعدادات الشرائح والصور:
- عدد الشرائح الافتراضي: {branding.get('default_slide_count', 16)}
- الحد الأدنى: {branding.get('min_slides', 8)}
- الحد الأقصى: {f"مقفل على {branding.get('default_slide_count', 16)} شريحة بالضبط" if branding.get('lock_slide_count') else 'لا يوجد حد أعلى — العدد يتبع حجم المحتوى'}
- عدد صور المود بورد: {branding.get('moodboard_count', 4)}
- المود بورد: {'مفعل' if branding.get('moodboard_enabled') else 'معطل'}
- صورة الغلاف: {'مفعلة' if branding.get('cover_image_enabled') else 'معطلة'}

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

###  إعدادات الخرائط:
- نوع الخريطة الافتراضي: {branding.get('default_map_type', 'satellite')}
- نظرة عامة/معالم/طرق/نطاق: {branding.get('map_style_overview', 'satellite')} / {branding.get('map_style_landmarks', 'satellite')} / {branding.get('map_style_access', 'satellite')} / {branding.get('map_style_catchment', 'satellite')}
- بوصلة: {'مفعلة' if branding.get('draw_compass') else 'معطلة'} — خريطة مصغّرة: {'مفعلة' if branding.get('draw_inset') else 'معطلة'}

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
    'list_users': 'manage_users',
    'add_user': 'manage_users',
    'set_permission': 'manage_users',
    'toggle_user': 'manage_users',
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
    'manage_users': 'إدارة الموظفين',
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
                'slide_ratio', 'header_enabled', 'footer_enabled', 'header_height',
                'footer_height', 'moodboard_enabled', 'cover_image_enabled', 'moodboard_count',
                'default_slide_count', 'min_slides', 'max_slides', 'tagline', 'company_name',
                # Map appearance is a company setting like any other; it was in the database and in
                # db.update_branding, but the agent could not reach it.
                'default_map_type', 'map_style_overview', 'map_style_landmarks',
                'map_style_access', 'map_style_catchment', 'draw_compass', 'draw_inset',
                'lock_slide_count',
            }
            updates = {}
            for k, v in params.items():
                if k in allowed_keys:
                    # Cast integers for boolean/numeric fields
                    if k in ('header_enabled', 'footer_enabled', 'moodboard_enabled',
                             'cover_image_enabled', 'draw_compass', 'draw_inset', 'lock_slide_count'):
                        v = 1 if v in (True, 1, '1', 'true', 'نعم') else 0
                    elif k in ('header_height', 'footer_height', 'moodboard_count', 'default_slide_count', 'min_slides', 'max_slides'):
                        try:
                            v = int(v)
                        except (ValueError, TypeError):
                            continue
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

        # ── List Users ────────────────────────────────────────────────
        elif tool == 'list_users':
            users = db.get_users_by_tenant(tenant_id)
            result['data'] = [{
                'name': u['name'], 'email': u['email'], 'role': u['role'],
                'is_active': bool(u['is_active']),
            } for u in users]
            result['message'] = f'{len(users)} موظف في الشركة'

        # ── Add User ──────────────────────────────────────────────────
        elif tool == 'add_user':
            name = (params.get('name') or params.get('user_name') or '').strip()
            email = (params.get('email') or params.get('user_email') or '').strip().lower()
            password = (params.get('password') or '').strip()
            role = (params.get('role') or 'employee').strip()
            password_error = _password_validation_error(password) if password else None
            if not name or not email:
                result['status'] = 'error'
                result['message'] = 'name و email مطلوبان لإضافة الموظف'
            elif role not in db.USER_ROLES:
                result['status'] = 'error'
                result['message'] = f'الدور "{role}" غير معروف. الأدوار المتاحة: {", ".join(db.USER_ROLES)}'
            elif password_error:
                result['status'] = 'error'
                result['message'] = password_error
            else:
                existing = db.get_user_by_email(email)
                if existing:
                    result['status'] = 'error'
                    result['message'] = f'الموظف بالإيميل "{email}" موجود بالفعل'
                else:
                    # No default password: when none is supplied the account is
                    # created behind a one-time setup link and stays locked to
                    # password login until the employee sets their own.
                    if password:
                        pw_hash = auth.hash_password(password)
                        require_change = False
                    else:
                        pw_hash = auth.hash_password(_generate_secure_password())
                        require_change = True
                    user_id = db.create_user(tenant_id, name, email, pw_hash, role=role,
                                             require_password_change=require_change)
                    setup_url = None
                    if require_change:
                        setup_url = _password_setup_url(
                            db.create_password_setup_token(tenant_id, user_id))
                    db.log_ai_rule_change(tenant_id, 'agent_user', 'add_user', None, f'{name} ({email})', risk_level='yellow')
                    result['user_id'] = user_id
                    if setup_url:
                        result['data'] = {'setupUrl': setup_url}
                        result['message'] = (f'تم إضافة الموظف "{name}" ({email}). '
                                             f'رابط تعيين كلمة المرور: {setup_url}')
                    else:
                        result['message'] = f'تم إضافة الموظف "{name}" ({email}) بنجاح.'

        # ── Set Permission ────────────────────────────────────────────
        elif tool == 'set_permission':
            email = (params.get('user_email') or '').lower()
            perm = params.get('permission', '')
            granted = params.get('granted', True)
            users = db.get_users_by_tenant(tenant_id)
            target_user = next((u for u in users if u['email'] == email), None)
            if not target_user:
                result['status'] = 'error'
                result['message'] = f'الموظف "{email}" غير موجود'
            elif perm not in db.PERMISSION_KEYS:
                result['status'] = 'error'
                result['message'] = f'الصلاحية "{perm}" غير صالحة. الصلاحيات المتاحة: {", ".join(db.PERMISSION_KEYS)}'
            else:
                granted_val = 1 if granted in (True, 1, '1', 'true') else 0
                db.set_user_permission(target_user['id'], perm, granted_val)
                db.log_ai_rule_change(tenant_id, 'agent_permission', f'{email}:{perm}', 'unknown', granted_val, risk_level='red')
                status_text = 'منح' if granted_val else 'سحب'
                target_label = 'للموظف' if granted_val else 'من الموظف'
                target_name = target_user["name"]
                result['message'] = f'تم {status_text} صلاحية "{perm}" {target_label} {target_name}'

        # ── Toggle User ───────────────────────────────────────────────
        elif tool == 'toggle_user':
            email = (params.get('user_email') or '').lower()
            is_active = params.get('is_active', True)
            users = db.get_users_by_tenant(tenant_id)
            target_user = next((u for u in users if u['email'] == email), None)
            if not target_user:
                result['status'] = 'error'
                result['message'] = f'الموظف "{email}" غير موجود'
            else:
                active_val = 1 if is_active in (True, 1, '1', 'true') else 0
                # The agent is bound by the same primary-admin guard as the user routes.
                if not active_val and db.is_primary_company_admin(tenant_id, target_user['id']):
                    result['status'] = 'error'
                    result['message'] = 'لا يمكن تعطيل مدير الشركة الأساسي'
                else:
                    db.update_user(target_user['id'], is_active=active_val)
                    db.log_ai_rule_change(tenant_id, 'agent_user', f'toggle_{email}', target_user.get('is_active'), active_val, risk_level='red')
                    status_text = 'تفعيل' if active_val else 'تعطيل'
                    result['message'] = f'تم {status_text} حساب الموظف {target_user["name"]}'

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
                    response = call_zai_chat(edit_prompt, instruction, max_tokens=6000, usage_ctx=_usage_ctx('training_chat', workspace, tenant_id=tenant_id))
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
                training_context = db.get_training_context(tenant_id) or ''
                plan_prompt = slide_engine.build_slide_plan_prompt(
                    project_data, plan_branding, tenant_id=tenant_id)
                if training_context:
                    plan_prompt = f"## بيانات خاصة بالشركة\n{training_context}\n\n---\n\n{plan_prompt}"
                plan = None
                last_plan_err = None
                for _attempt in range(3):
                    try:
                        plan_resp = call_zai_chat_parallel(
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
                training_context = db.get_training_context(tenant_id) or ''
                def call_glm_fn(sys_prompt, user_msg, max_tokens=6000):
                    if training_context:
                        sys_prompt = f"{sys_prompt}\n\n## بيانات خاصة بالشركة\n{training_context}"
                    return call_zai_chat_parallel(sys_prompt, user_msg, max_tokens=max_tokens, attempts=2, usage_ctx=_usage_ctx('training_chat', workspace, tenant_id=tenant_id))
                htmls = generate_all_slides(
                    slide_plan, project_data, branding, _get_images_info(images, project_data), call_glm_fn,
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
                project_data = workspace.get('projectData') if isinstance(workspace.get('projectData'), dict) else {}
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
