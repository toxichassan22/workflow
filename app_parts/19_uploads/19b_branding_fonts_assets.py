


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Branding fonts and tenant asset serving: the SAG font catalog, the
# per-tenant font selections and uploads, the reference-image analysis, and
# the /tenant-assets routes that serve a company's logo, watermark and
# font files.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _font_payload_from_file(file):
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in {'.ttf', '.otf', '.woff', '.woff2'}:
        return None, 'Only TTF, OTF, WOFF, and WOFF2 fonts are supported'
    raw = file.read()
    if not raw or len(raw) > 15 * 1024 * 1024:
        return None, 'Font file must be between 1 byte and 15 MB'
    fmt = {'.ttf': 'truetype', '.otf': 'opentype', '.woff': 'woff', '.woff2': 'woff2'}[ext]
    return json.dumps({'data': base64.b64encode(raw).decode('ascii'), 'format': fmt, 'ext': ext}), None


def _detect_font_metadata(raw, filename):
    stem = os.path.splitext(os.path.basename(filename or 'font'))[0]
    metadata_text = stem.replace('_', ' ').replace('-', ' ')
    scripts = set()
    family = metadata_text.strip() or 'Custom Font'
    weight = 'regular'
    try:
        from io import BytesIO
        from fontTools.ttLib import TTFont
        font = TTFont(BytesIO(raw), fontNumber=0)
        names = []
        for record in font['name'].names:
            if record.nameID in (1, 2, 4, 17):
                try:
                    names.append(record.toUnicode())
                except Exception:
                    pass
        if names:
            family = next((value for value in names if value.strip()), family).strip()
            metadata_text = ' '.join(names + [metadata_text])
        cmap = set()
        for table in font['cmap'].tables:
            cmap.update(table.cmap.keys())
        arabic_count = sum(1 for codepoint in cmap if 0x0600 <= codepoint <= 0x06FF or 0x0750 <= codepoint <= 0x077F or 0xFB50 <= codepoint <= 0xFEFF)
        latin_count = sum(1 for codepoint in cmap if 0x0041 <= codepoint <= 0x024F)
        if arabic_count:
            scripts.add('arabic')
        if latin_count:
            scripts.add('latin')
        weight_class = int(getattr(font.get('OS/2'), 'usWeightClass', 400) or 400)
        if weight_class <= 300:
            weight = 'light'
        elif weight_class <= 450:
            weight = 'regular'
        elif weight_class <= 550:
            weight = 'medium'
        elif weight_class <= 750:
            weight = 'bold'
        else:
            weight = 'black'
        font.close()
    except Exception:
        pass

    text = metadata_text.lower()
    if any(token in text for token in ('black', 'heavy', 'extrabold', 'extra bold')):
        weight = 'black'
    elif any(token in text for token in ('bold', 'semibold', 'semi bold', 'demi')):
        weight = 'bold'
    elif any(token in text for token in ('medium', 'medium')):
        weight = 'medium'
    elif any(token in text for token in ('light', 'thin', 'book')):
        weight = 'light'
    if not scripts:
        scripts.add('arabic' if re.search(r'arabic|arab|عربي|نسخ|رقعة', text) else 'latin')
    return {'family': family, 'weight': weight, 'scripts': sorted(scripts), 'source': 'font_metadata'}


@app.route('/api/admin/sag-fonts', methods=['GET'])
@require_permission('sag_admin_panel')
def api_get_sag_fonts():
    return jsonify({'success': True, 'fonts': db.get_sag_fonts(
        script=request.args.get('script'), weight=request.args.get('weight')
    )})


@app.route('/api/admin/sag-fonts', methods=['POST'])
@require_permission('sag_admin_panel')
def api_create_sag_font():
    data = request.form if request.form else (request.json or {})
    font_name = (data.get('font_name') or data.get('fontName') or '').strip()
    font_family = (data.get('font_family') or data.get('fontFamily') or '').strip()
    script = (data.get('script') or '').strip().lower()
    weight = (data.get('weight') or 'regular').strip().lower()
    if not font_name or not font_family or script not in {'arabic', 'latin'} or weight not in {'light', 'regular', 'medium', 'bold', 'black'}:
        return jsonify({'error': 'font_name, font_family, script, and a valid weight are required'}), 400
    file_data = None
    if 'font' in request.files:
        file_data, error = _font_payload_from_file(request.files['font'])
        if error:
            return jsonify({'error': error}), 400
    font_id = db.create_sag_font(
        font_name, font_family, script, weight, data.get('style', 'normal'),
        'uploaded' if file_data else 'preset', data.get('source_data') or font_family, file_data
    )
    font = db.get_sag_font(font_id) or {}
    font.pop('file_data', None)
    return jsonify({'success': True, 'font': font}), 201


@app.route('/api/admin/sag-fonts/auto-upload', methods=['POST'])
@require_permission('sag_admin_panel')
def api_auto_upload_sag_font():
    file = request.files.get('font')
    if not file or not file.filename:
        return jsonify({'error': 'No font file provided'}), 400
    file_data, error = _font_payload_from_file(file)
    if error:
        return jsonify({'error': error}), 400
    raw = base64.b64decode(json.loads(file_data)['data'])
    detected = _detect_font_metadata(raw, file.filename)
    created = []
    for script in detected['scripts']:
        font_id = db.create_sag_font(
            detected['family'], detected['family'], script, detected['weight'],
            source_type='uploaded', source_data=detected['family'], file_data=file_data
        )
        created.append(font_id)
    return jsonify({'success': True, 'detected': detected, 'fontIds': created, 'fonts': db.get_sag_fonts()}), 201


@app.route('/api/admin/sag-fonts/<font_id>', methods=['PUT'])
@require_permission('sag_admin_panel')
def api_update_sag_font(font_id):
    data = request.json or {}
    if not db.update_sag_font(font_id, **data):
        return jsonify({'error': 'Font not found or no valid changes'}), 404
    return jsonify({'success': True, 'font': db.get_sag_font(font_id)})


@app.route('/api/admin/sag-fonts/<font_id>', methods=['DELETE'])
@require_permission('sag_admin_panel')
def api_delete_sag_font(font_id):
    if not db.get_sag_font(font_id):
        return jsonify({'error': 'Font not found'}), 404
    db.update_sag_font(font_id, is_active=0, is_default=0)
    return jsonify({'success': True})


def _get_tenant_uploaded_fonts(tenant_id):
    font_dir = os.path.join(UPLOADS_DIR, str(tenant_id), 'fonts')
    if not os.path.exists(font_dir):
        return []
    fonts = []
    seen = set()
    for fname in sorted(os.listdir(font_dir)):
        ext = os.path.splitext(fname)[1].lower()
        if ext in ('.ttf', '.otf', '.woff', '.woff2'):
            stem = os.path.splitext(fname)[0]
            family = re.sub(r'_(light|regular|medium|bold|black)$', '', stem, flags=re.I).replace('_', ' ').strip()
            if family and family.lower() not in seen:
                seen.add(family.lower())
                rel_path = os.path.relpath(os.path.join(font_dir, fname), os.path.dirname(__file__)).replace('\\', '/')
                fonts.append({
                    'id': f'custom_file_{len(fonts)+1}',
                    'font_family': family,
                    'font_name': family,
                    'script': 'arabic',
                    'weight': 'regular',
                    'is_custom': True,
                    'custom_font_path': rel_path
                })
    return fonts


def _public_font_selections(tenant_id):
    hidden = {'custom_font_data'}
    selections = db.get_tenant_font_selections(tenant_id)
    branding = db.get_branding(tenant_id) or {}
    tenant_family = branding.get('font_family')
    result = []
    for selection in selections:
        item = {key: value for key, value in selection.items() if key not in hidden}
        if item.get('font_id') and not item.get('font_family'):
            font = db.get_sag_font(item['font_id'])
            if font:
                item['font_family'] = font.get('font_family')
        elif item.get('custom_font_path') and not item.get('font_family'):
            if tenant_family:
                item['font_family'] = tenant_family
            else:
                path = item['custom_font_path']
                name = os.path.splitext(os.path.basename(path))[0]
                name = re.sub(r'_(light|regular|medium|bold|black)$', '', name, flags=re.I)
                item['font_family'] = name.replace('_', ' ').strip()
        result.append(item)
    return result


@app.route('/api/branding/fonts', methods=['GET'])
@require_auth
def api_get_branding_fonts():
    return jsonify({
        'success': True,
        'selections': _public_font_selections(g.tenant_id),
        'available': db.get_sag_fonts(),
        'custom_uploaded': _get_tenant_uploaded_fonts(g.tenant_id)
    })


@app.route('/api/branding/fonts', methods=['PUT'])
@require_permission('company_settings')
def api_set_branding_font():
    data = request.json or {}
    script = (data.get('script') or '').strip().lower()
    weight = (data.get('weight') or '').strip().lower()
    font_id = data.get('font_id') or data.get('fontId')
    custom_font_path = data.get('custom_font_path')
    if script not in {'arabic', 'latin'} or weight not in {'light', 'regular', 'medium', 'bold', 'black'}:
        return jsonify({'error': 'Invalid script or weight'}), 400
    if font_id and not db.get_sag_font(font_id):
        return jsonify({'error': 'Font not found'}), 404
    if font_id:
        db.set_tenant_font_selection(g.tenant_id, script, weight, font_id=font_id)
    elif custom_font_path:
        db.set_tenant_font_selection(g.tenant_id, script, weight, custom_font_path=custom_font_path)
    else:
        db.delete_tenant_font_selection(g.tenant_id, script, weight)
    return jsonify({'success': True, 'selections': _public_font_selections(g.tenant_id)})


@app.route('/api/branding/fonts/upload', methods=['POST'])
@require_permission('company_settings')
def api_upload_branding_font_variant():
    script = (request.form.get('script') or '').strip().lower()
    weight = (request.form.get('weight') or 'regular').strip().lower()
    if script not in {'arabic', 'latin'} or weight not in {'light', 'regular', 'medium', 'bold', 'black'}:
        return jsonify({'error': 'Invalid script or weight'}), 400
    file = request.files.get('font')
    if not file or not file.filename:
        return jsonify({'error': 'No font file provided'}), 400
    file_data, error = _font_payload_from_file(file)
    if error:
        return jsonify({'error': error}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {'.ttf', '.otf', '.woff', '.woff2'}:
        return jsonify({'error': 'Invalid font file extension'}), 400
    safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', os.path.splitext(file.filename)[0])
    safe_tenant = re.sub(r'[^A-Za-z0-9_-]', '', str(g.tenant_id)) or 'public'
    font_dir = os.path.join(UPLOADS_DIR, safe_tenant, 'fonts')
    os.makedirs(font_dir, exist_ok=True)
    filename = f'{safe_name}_{script}_{weight}{ext}'
    filepath = os.path.abspath(os.path.join(font_dir, filename))
    if os.path.commonpath([os.path.abspath(font_dir), filepath]) != os.path.abspath(font_dir):
        return jsonify({'error': 'Invalid font filename'}), 400
    with open(filepath, 'wb') as font_file:
        font_file.write(base64.b64decode(json.loads(file_data)['data']))
    stored_path = os.path.relpath(filepath, os.path.dirname(__file__)).replace('\\', '/')
    db.set_tenant_font_selection(g.tenant_id, script, weight, custom_font_path=stored_path, custom_font_data=file_data)
    return jsonify({'success': True, 'selections': _public_font_selections(g.tenant_id)})


@app.route('/api/branding/fonts/auto-upload', methods=['POST'])
@require_permission('company_settings')
def api_auto_upload_branding_font():
    file = request.files.get('font')
    if not file or not file.filename:
        return jsonify({'error': 'No font file provided'}), 400
    file_data, error = _font_payload_from_file(file)
    if error:
        return jsonify({'error': error}), 400
    parsed = json.loads(file_data)
    raw = base64.b64decode(parsed['data'])
    detected = _detect_font_metadata(raw, file.filename)
    ext = parsed['ext']
    if ext not in {'.ttf', '.otf', '.woff', '.woff2'}:
        return jsonify({'error': 'Invalid font file extension'}), 400
    safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', os.path.splitext(file.filename)[0])
    safe_tenant = re.sub(r'[^A-Za-z0-9_-]', '', str(g.tenant_id)) or 'public'
    font_dir = os.path.join(UPLOADS_DIR, safe_tenant, 'fonts')
    os.makedirs(font_dir, exist_ok=True)
    filename = f'{safe_name}_{detected["weight"]}{ext}'
    filepath = os.path.abspath(os.path.join(font_dir, filename))
    if os.path.commonpath([os.path.abspath(font_dir), filepath]) != os.path.abspath(font_dir):
        return jsonify({'error': 'Invalid font filename'}), 400
    with open(filepath, 'wb') as font_file:
        font_file.write(raw)
    stored_path = os.path.relpath(filepath, os.path.dirname(__file__)).replace('\\', '/')
    current_branding = db.get_branding(g.tenant_id) or {}
    current_family = (current_branding.get('font_family') or '').strip().lower()
    detected_family = (detected.get('family') or '').strip().lower()
    target_scripts = list(set(detected.get('scripts', []) + ['arabic', 'latin']))
    if not current_family or (detected_family and current_family != detected_family):
        for script in ('arabic', 'latin'):
            for old_weight in ('light', 'regular', 'medium', 'bold', 'black'):
                db.delete_tenant_font_selection(g.tenant_id, script, old_weight)
    for script in target_scripts:
        db.set_tenant_font_selection(
            g.tenant_id,
            script,
            detected['weight'],
            custom_font_path=stored_path,
            custom_font_data=file_data,
        )
    family_name = detected.get('family') or os.path.splitext(file.filename)[0].replace('_', ' ').strip()
    db.update_branding(g.tenant_id, font_family=family_name, font_arabic=family_name)
    return jsonify({
        'success': True,
        'detected': detected,
        'selections': _public_font_selections(g.tenant_id),
    })


@app.route('/api/branding/fonts/<script>/<weight>', methods=['DELETE'])
@require_permission('company_settings')
def api_delete_branding_font(script, weight):
    if script not in {'arabic', 'latin'} or weight not in {'light', 'regular', 'medium', 'bold', 'black'}:
        return jsonify({'error': 'Invalid script or weight'}), 400
    db.delete_tenant_font_selection(g.tenant_id, script, weight)
    return jsonify({'success': True})


@app.route('/api/upload-font', methods=['POST'])
@app.route('/api/branding/font', methods=['POST'])
@require_permission('company_settings')
def api_upload_font():
    """Upload a custom font file (TTF/OTF/WOFF/WOFF2) to uploads/fonts/<tenant_id>/."""
    if 'font' not in request.files:
        return jsonify({'error': 'No font file provided'}), 400
    file = request.files['font']
    if not file.filename:
        return jsonify({'error': 'No filename'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.ttf', '.otf', '.woff', '.woff2'):
        return jsonify({'error': 'Only TTF, OTF, WOFF, WOFF2 are supported'}), 400

    font_dir = os.path.join('uploads', g.tenant_id, 'fonts')
    os.makedirs(font_dir, exist_ok=True)

    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', os.path.splitext(file.filename)[0])
    filename = f"{safe_name}{ext}"
    filepath = os.path.join(font_dir, filename)
    file.save(filepath)

    # Also persist the font bytes in the DB so exports still work if uploads/ is ephemeral
    try:
        with open(filepath, 'rb') as f:
            font_bytes = f.read()
        fmt = {'.ttf': 'truetype', '.otf': 'opentype', '.woff': 'woff', '.woff2': 'woff2'}.get(ext, 'truetype')
        font_file_data = json.dumps({
            'data': base64.b64encode(font_bytes).decode('ascii'),
            'format': fmt,
            'ext': ext
        })
    except Exception as e:
        print(f"[FONT UPLOAD] failed to read font bytes for persistence: {e}")
        font_file_data = None

    font_file_path = os.path.relpath(filepath, os.path.dirname(__file__)).replace('\\', '/')
    font_url = f"/tenant-assets/{g.tenant_id}/fonts/{filename}"
    font_name = safe_name.replace('_', ' ').title()
    updates = {'font_file_path': font_file_path, 'font_family': font_name}
    if font_file_data:
        updates['font_file_data'] = font_file_data
    db.update_branding(g.tenant_id, **updates)
    return jsonify({'success': True, 'font_url': font_url, 'font_file_path': font_file_path, 'font_name': font_name})


@app.route('/api/branding/analyze-reference', methods=['POST'])
@require_permission('company_settings')
def api_analyze_reference():
    """
    Analyze the uploaded reference image using Gemini Vision.
    Extracts colors, design style, and layout — then auto-applies to branding.
    """
    from reference_analyzer import analyze_reference_image, VISION_MODEL as REFERENCE_VISION_MODEL

    branding = db.get_branding(g.tenant_id)
    ref_path = branding.get('reference_image_path') if branding else None

    if not ref_path:
        return jsonify({'error': 'No reference image uploaded. Upload one first via /api/upload/reference-image'}), 400

    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard

    # Convert relative path to absolute
    abs_path = os.path.join(os.path.dirname(__file__), ref_path.lstrip('/'))
    if not os.path.exists(abs_path):
        return jsonify({'error': 'Reference image file not found on disk'}), 404

    try:
        recorded = {}

        def _record_reference_metering(metering):
            if recorded.get('done'):
                return
            recorded['done'] = True
            try:
                metering = metering or {}
                _record_ai_usage(
                    _usage_ctx('image', tenant_id=g.tenant_id), REFERENCE_VISION_MODEL,
                    'ok', metering.get('usage') or {}, metering.get('generation_id'))
            except Exception as exc:
                print(f"[AI-USAGE] reference metering failed: {exc}")

        gate = _tenant_key_gate(tenant_id=g.tenant_id)
        if gate is not None:
            return jsonify({'success': False, 'error': gate['message'],
                            'error_code': gate['error_code']}), 402
        analysis, metering = analyze_reference_image(
            abs_path, _resolve_openrouter_key(tenant_id=g.tenant_id),
            on_metering=_record_reference_metering)
        metering = metering or {}
        if not recorded.get('done'):
            _record_reference_metering(metering)

        # Auto-apply extracted colors and style to branding
        updates = {}
        colors = analysis.get('colors', {})
        if colors:
            for k in ['primary', 'secondary', 'accent', 'background', 'text']:
                if colors.get(k):
                    updates[f'{k}_color'] = colors[k]

        if analysis.get('design_style'):
            updates['design_template'] = analysis['design_style']
        if analysis.get('card_style'):
            updates['card_style'] = analysis['card_style']

        if updates:
            db.update_branding(g.tenant_id, **updates)

        updated_branding = db.get_branding(g.tenant_id)
        return jsonify({
            'success': True,
            'analysis': analysis,
            'branding': updated_branding,
        })
    except Exception as e:
        print(f"[ANALYZE-REFERENCE ERROR] {e}")
        try:
            if not recorded.get('done'):
                _record_ai_usage(
                    _usage_ctx('image', tenant_id=g.tenant_id), REFERENCE_VISION_MODEL,
                    'error', {}, None)
                recorded['done'] = True
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500


@app.route('/tenant-assets/<tenant_id>/logo')
def serve_tenant_logo(tenant_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(tenant_id or '')):
        return jsonify({'error': 'Logo not found'}), 404
    logo_path = _tenant_logo_storage_path(tenant_id)
    tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, tenant_id))
    if logo_path and os.path.commonpath([tenant_root, os.path.realpath(logo_path)]) == tenant_root:
        extension = os.path.splitext(logo_path)[1].lower()
        mimetype = 'image/png' if extension == '.png' else 'image/jpeg' if extension in ('.jpg', '.jpeg') else 'image/webp'
        resp = send_file(logo_path, mimetype=mimetype)
        resp.headers['Cache-Control'] = 'no-cache, must-revalidate'
        return resp
    # Fallback to default system logo if no tenant logo was uploaded yet
    default_logo = os.path.join(os.path.dirname(__file__), 'assets', 'logo.png')
    if os.path.isfile(default_logo):
        resp = send_file(default_logo, mimetype='image/png')
        resp.headers['Cache-Control'] = 'no-cache, must-revalidate'
        return resp
    return jsonify({'error': 'Logo not found'}), 404


@app.route('/tenant-assets/<tenant_id>/watermark')
def serve_tenant_watermark(tenant_id):
    """Serve only an explicitly uploaded watermark; never fall back to a logo."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(tenant_id or '')):
        return jsonify({'error': 'Watermark not found'}), 404
    branding = db.get_branding(tenant_id) or {}
    if not str(branding.get('watermark_path') or '').strip():
        return jsonify({'error': 'Watermark not found'}), 404
    watermark_path = _tenant_watermark_storage_path(tenant_id)
    tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, tenant_id))
    try:
        inside_tenant = bool(watermark_path) and os.path.commonpath(
            [tenant_root, os.path.realpath(watermark_path)]) == tenant_root
    except ValueError:
        inside_tenant = False
    if not inside_tenant:
        return jsonify({'error': 'Watermark not found'}), 404
    extension = os.path.splitext(watermark_path)[1].lower()
    mimetype = 'image/png' if extension == '.png' else 'image/jpeg' if extension in ('.jpg', '.jpeg') else 'image/webp'
    resp = send_file(watermark_path, mimetype=mimetype)
    resp.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return resp


@app.route('/tenant-assets/<tenant_id>/fonts/<filename>')
def serve_tenant_font(tenant_id, filename):
    """Serve uploaded tenant font files."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(tenant_id or '')):
        return jsonify({'error': 'Font not found'}), 404
    safe_name = os.path.basename(filename)
    if '..' in safe_name or safe_name.startswith('.') or not safe_name:
        return jsonify({'error': 'Invalid font filename'}), 400
    ext = os.path.splitext(safe_name)[1].lower()
    mime_map = {'.ttf': 'font/ttf', '.otf': 'font/otf', '.woff': 'font/woff', '.woff2': 'font/woff2'}
    mimetype = mime_map.get(ext)
    if not mimetype:
        return jsonify({'error': 'Invalid font filename'}), 400
    font_path = os.path.join(UPLOADS_DIR, str(tenant_id), 'fonts', safe_name)
    if not os.path.isfile(font_path):
        return jsonify({'error': 'Font not found'}), 404
    resp = send_file(font_path, mimetype=mimetype)
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp
