

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
from numeric_precision import format_precise_number


# Training Data (per-tenant AI training)
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
                "model": VISION_MODEL,
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
                _usage_ctx('training_chat', tenant_id=g.tenant_id), VISION_MODEL)
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
    system_prompt = f"""أنت "وكيل الإدارة الذكي" (Super Agent) — المساعد التنفيذي لأدمن الشركة في منصة العروض التقديمية العقارية.
أنت لست مجرد chatbot — أنت وكيل تنفيذي يقرأ حالة النظام ويعدّل إعدادات الشركة مباشرة عبر الأدوات أدناه فقط.

## حالة النظام الحالية:
{system_state}

## مساحة العمل المفتوحة حالياً:
{workspace_state}

## الأدوات المتاحة لك (Tools):
يمكنك تنفيذ أي من الإجراءات التالية بإرجاع JSON action ضمن ردك.
ضع الـ action داخل بلوك ```action ... ``` في ردك.

### 1. تعديل الهوية البصرية:
```action
{{"tool": "update_branding", "params": {{"primary_color": "#HEX", "secondary_color": "#HEX", "accent_color": "#HEX", "background_color": "#HEX", "text_color": "#HEX", "font_family": "...", "font_arabic": "...", "design_template": "modern|classic|dark|corporate|luxury", "card_style": "bordered|shadow|flat|glass", "slide_ratio": "16:9|4:3", "header_enabled": 1, "footer_enabled": 1, "tagline": "...", "tagline_en": "...", "company_name": "..."}}}}
```
ملاحظة: أرسل فقط الحقول التي يريد المستخدم تعديلها، ليس كلها.
عدد الشرائح يقرره التوليد من حجم محتوى المشروع، وارتفاع الهيدر والفوتر ثابتان — لا توجد أداة لتغيير أي منها.

### 2. عرض الحقول:
```action
{{"tool": "list_fields"}}
```

### 3. إضافة حقل جديد:
```action
{{"tool": "add_field", "params": {{"field_label": "...", "field_type": "text|number|textarea|select|date", "field_options": ["اختيار 1", "اختيار 2"], "section_key": "basic|location|financial|project|swot|...", "is_required": false, "ai_hint": "...", "placeholder": "..."}}}}
```

### 4. تعديل حقل (تفعيل/تعطيل/تغيير الخيارات):
```action
{{"tool": "update_field", "params": {{"field_key": "...", "updates": {{"is_active": 1, "field_label": "...", "field_type": "select", "field_options": ["اختيار 1", "اختيار 2"], "ai_hint": "..."}}}}}}
```
ملاحظة: عند إضافة أو تحديث خيارات قائمة مسدلة (dropdown)، تأكد دائماً من تمرير "field_type": "select" و تمرير مصفوفة JSON تحتوي الخيارات بالشكل: "field_options": ["خيار 1", "خيار 2"].

### 5. حذف حقل مخصص:
```action
{{"tool": "delete_field", "params": {{"field_key": "..."}}}}
```

### 6. عرض الأقسام:
```action
{{"tool": "list_sections"}}
```

### 7. إضافة قسم جديد:
```action
{{"tool": "add_section", "params": {{"section_key": "...", "section_label": "..."}}}}
```

### 8. حذف قسم:
```action
{{"tool": "delete_section", "params": {{"section_key": "..."}}}}
```

### 9. عرض العروض التقديمية:
```action
{{"tool": "list_presentations"}}
```

### 10. حذف عرض تقديمي:
```action
{{"tool": "delete_presentation", "params": {{"presentation_id": "..."}}}}
```

### 11. إضافة قاعدة تدريب:
```action
{{"tool": "add_training", "params": {{"title": "...", "content": "...", "category": "general|design|content|style"}}}}
```

### 12. حذف سجل تدريب:
```action
{{"tool": "delete_training", "params": {{"entry_id": "..."}}}}
```

### 13. عرض سجلات التدريب:
```action
{{"tool": "list_training"}}
```

### 14. قراءة مساحة العرض المفتوح والتحقق منه:
```action
{{"tool": "inspect_workspace"}}
```
```action
{{"tool": "validate_workspace"}}
```

### 15. تعديل شريحة أو أكثر في العرض المفتوح:
```action
{{"tool": "edit_workspace_slide", "params": {{"slide_index": 0, "instruction": "..."}}}}
```
يمكن تمرير `slide_indices` كمصفوفة لتعديل أكثر من شريحة، وتنفذ الأداة التعديل لكل شريحة مع تحقق بعد كل تعديل.
عند طلب إضافة شعار الشركة أو شعار المشروع إلى شريحة، استخدم الشعار الموجود فعلياً في الهوية أو بيانات المشروع:
`##LOGO##` لشعار الشركة و`##PROJECT_LOGO##` لشعار المشروع. لا تكتب اسم الشعار كنص، ولا تستخدم رابطاً خارجياً أو صورة بديلة.
شعار جهة من فريق العمل ليس شعار الشركة: استخدم الرمز `##TEAM_LOGO_N##`، حيث يطابق `N` ترتيب الجهة في قائمة فريق العمل الحالية، ولا تستبدله بـ `##LOGO##`.
مكان شعار الشركة الافتراضي هو الهيدر المعتمد للشريحة، ويجب الحفاظ على الشعار الموجود إذا كان الهيدر يحتويه.

### 16. حفظ مساحة العمل:
```action
{{"tool": "save_workspace", "params": {{"title": "..."}}}}
```

### 17. تصدير العرض المفتوح:
```action
{{"tool": "export_workspace", "params": {{"format": "pdf|pptx"}}}}
```

### 18. توليد الشرائح من الخطة المفتوحة:
```action
{{"tool": "generate_workspace", "params": {{"regenerate": true}}}}
```

### 19. ملء بيانات المشروع في مساحة العمل من كلام المستخدم:
```action
{{"tool": "update_workspace", "params": {{"projectData": {{"project_name": "...", "project_type": "...", "location_address": "...", "budget": "..."}}}}}}
```
استخدمها عندما يعطيك المستخدم بيانات مشروع في المحادثة ويريد إنشاء عرض منها. أرسل الحقول المتوفرة فقط.

### 20. توليد خطة الشرائح من بيانات المشروع:
```action
{{"tool": "generate_slide_plan"}}
```
تتطلب projectData في مساحة العمل (استخدم update_workspace أولاً إن لزم).

### 21. عرض الخطوط المتاحة والتخصيص الحالي:
```action
{{"tool": "list_fonts"}}
```

### 22. تخصيص خط الشركة أو الرجوع للخط الافتراضي:
```action
{{"tool": "set_font", "params": {{"font_query": "اسم الخط أو عائلته من قائمة الخطوط المتاحة أو default", "weight": "regular"}}}}
```
- عند اختيار خط يدعم العربية واللاتينية يُطبَّق على الاثنين تلقائياً.
- استخدم "default" في font_query للرجوع للخط الافتراضي.
- رفع ملف خط جديد يتم فقط من إعدادات الشركة (منطقة السحب والإفلات) — إذا طلب المستخدم خطاً غير موجود في القائمة، أخبره برفعه أولاً من الإعدادات.

### 23. فريق العمل (مكتبة الشركة المشتركة):
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
- المكتبة مشتركة بين كل ملفات المشاريع، فأي تعديل هنا يظهر في كل مشروع جديد.
- الاستبعاد لملف واحد فقط يتم من صفحة فريق العمل داخل المشروع، لا من هنا.

### 24. قواعد التوليد الخاصة بالشركة (تُضاف إلى برومبت توليد الشرائح):
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

### 25. سؤال المستخدم عند عدم الوضوح:
```action
{{"tool": "ask", "params": {{"question": "سؤال عربي واحد قصير"}}}}
```

## سير العمل الكامل لإنشاء مشروع جديد من المحادثة:
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
7. إذا طلب المستخدم شيء خطير (حذف عروض)، نفذه مباشرة لكن حذّره بوضوح.
   إدارة الموظفين (إضافة، صلاحيات، تفعيل، تعطيل) خارج صلاحياتك تمامًا — يديرها مدير الشركة
   يدويًا من صفحة الموظفين؛ إذا طُلب أيًّا منها فأخبر المستخدم بذلك ولا تُخرج action لها.
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
        response = call_text_chat(system_prompt, user_prompt, max_tokens=6000,
                                 model=VISION_MODEL if attachment_images else GEMINI_TEXT_MODEL,
                                 reasoning_effort='medium' if attachment_images else TEXT_REASONING_EFFORT,
                                 image_references=attachment_images or None,
                                 usage_ctx=_usage_ctx('training_chat', data))
        reply = extract_chat_content(response, 'SUPER-AGENT')
    except Exception as e:
        print(f'[SUPER-AGENT] AI reply failed: {e}')
        if getattr(e, 'fatal_ai_error', False) or _is_company_credit_error(e):
            # A drained wallet must read as a drained wallet, not a greeting.
            reply = _client_safe_llm_error(getattr(e, 'ai_message', '') or str(e))
        else:
            reply = 'أهلاً! أنا وكيل الإدارة الذكي الخاص بشركتك. أقدر أساعدك في إعدادات الشركة — من الألوان والخطوط والحقول حتى قواعد التوليد وفريق العمل.'

    # ── Execute any actions embedded in the reply ─────────────────────────
    actions_executed = []
    parsed_actions = _extract_json_actions_from_text(reply)

    # ── Fallback intent extraction if LLM didn't format an action block ──
    if not parsed_actions and message:
        # 1. Color intent (hex codes like #7a6938, #a8a851, etc.)
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

        # 2. Revert / Reset colors intent ("رجع الألوان", "استرجع الألوان", "الألوان القديمة", "الألوان الافتراضية")
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

        # 3. Font intent ("غيّر الخط إلى X" / "استخدم خط X" / "رجّع الخط الافتراضي")
        font_words = {'خط', 'الخط', 'خطوط', 'الخطوط', 'بالخط', 'فونت', 'الفونت'}
        tokens = set(re.findall(r'[؀-ۿ]+|[A-Za-z]+', message))
        if not parsed_actions and (tokens & font_words or 'font' in message.lower()):
            msg_lower = message.lower()
            font_hits = []
            for f in db.get_sag_fonts():
                name = (f.get('font_name') or '').lower()
                family = (f.get('font_family') or '').lower()
                if (name and name in msg_lower) or (family and family in msg_lower):
                    font_hits.append(f)
            # A family match lands on whatever row sorts first — 'bold' before
            # 'regular' — so "الخط Cairo" used to latch onto the Cairo Bold row.
            # Prefer a hit whose own name is in the message at regular weight.
            named_hits = [f for f in font_hits if (f.get('font_name') or '').lower() in msg_lower]
            font_hit = next((f for f in named_hits if f.get('weight') == 'regular'), None) \
                or (named_hits[0] if named_hits else None) \
                or (font_hits[0] if font_hits else None)
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
