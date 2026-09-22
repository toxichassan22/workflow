

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI Rules Management
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AI_RULE_FIELDS = {
    # Design rules (editable branding fields)
    'primary_color': {'label': 'اللون الرئيسي', 'category': 'design', 'risk': 'green'},
    'secondary_color': {'label': 'اللون الثانوي', 'category': 'design', 'risk': 'green'},
    'accent_color': {'label': 'لون التمييز', 'category': 'design', 'risk': 'green'},
    'background_color': {'label': 'لون الخلفية', 'category': 'design', 'risk': 'green'},
    'text_color': {'label': 'لون النص', 'category': 'design', 'risk': 'green'},
    'font_family': {'label': 'الخط', 'category': 'design', 'risk': 'green'},
    'font_arabic': {'label': 'الخط العربي', 'category': 'design', 'risk': 'green'},
    'design_template': {'label': 'قالب التصميم', 'category': 'design', 'risk': 'yellow'},
    'card_style': {'label': 'نمط البطاقات', 'category': 'design', 'risk': 'green'},
    'slide_ratio': {'label': 'نسبة العرض', 'category': 'design', 'risk': 'yellow'},
    'header_enabled': {'label': 'تفعيل الهيدر', 'category': 'design', 'risk': 'red'},
    'footer_enabled': {'label': 'تفعيل الفوتر', 'category': 'design', 'risk': 'red'},
    'header_height': {'label': 'ارتفاع الهيدر', 'category': 'design', 'risk': 'yellow'},
    'footer_height': {'label': 'ارتفاع الفوتر', 'category': 'design', 'risk': 'yellow'},
    'moodboard_enabled': {'label': 'تفعيل المود بورد', 'category': 'design', 'risk': 'yellow'},
    'cover_image_enabled': {'label': 'تفعيل صورة الغلاف', 'category': 'design', 'risk': 'green'},
    'default_slide_count': {'label': 'عدد الشرائح الافتراضي', 'category': 'content', 'risk': 'yellow'},
    'min_slides': {'label': 'الحد الأدنى للشرائح', 'category': 'content', 'risk': 'red'},
    'max_slides': {'label': 'الحد الأقصى للشرائح', 'category': 'content', 'risk': 'red'},
}

DEFAULT_BRANDING_VALUES = {
    'primary_color': '#3B6E91',
    'secondary_color': '#254B66',
    'accent_color': '#6DA3C3',
    'background_color': '#F4F9FC',
    'text_color': '#333333',
    'font_family': 'The Sans Arabic',
    'font_arabic': 'The Sans Arabic',
    'design_template': 'modern',
    'card_style': 'bordered',
    'slide_ratio': '16:9',
    'header_enabled': 1,
    'footer_enabled': 1,
    'header_height': 56,
    'footer_height': 36,
    'moodboard_enabled': 1,
    'cover_image_enabled': 1,
    'default_slide_count': 16,
    'lock_slide_count': 0,
    'min_slides': 8,
    'max_slides': 30,
}


@app.route('/api/ai-rules', methods=['GET'])
@require_permission('ai_rules')
def api_get_ai_rules():
    """Get all AI rules for the tenant: design, content, training, log."""
    branding = db.get_branding(g.tenant_id) or {}
    design_rules = []
    for key, meta in AI_RULE_FIELDS.items():
        value = branding.get(key, DEFAULT_BRANDING_VALUES.get(key, ''))
        design_rules.append({
            'key': key,
            'label': meta['label'],
            'category': meta['category'],
            'risk': meta['risk'],
            'value': value,
            'defaultValue': DEFAULT_BRANDING_VALUES.get(key),
        })

    return jsonify({
        'success': True,
        'designRules': design_rules,
        'contentRules': CONTENT_DISTRIBUTION_RULES,
        'training': db.get_training_data(g.tenant_id),
        'log': db.get_ai_rules_log(g.tenant_id, limit=20),
    })


@app.route('/api/ai-rules', methods=['POST'])
@require_permission('ai_rules')
def api_update_ai_rule():
    """Update a single AI rule and log the change."""
    data = request.json or {}
    key = data.get('key')
    value = data.get('value')

    if not key or key not in AI_RULE_FIELDS:
        return jsonify({'error': 'Invalid rule key'}), 400

    meta = AI_RULE_FIELDS[key]
    if meta['category'] == 'design':
        # Get current value for audit log
        branding = db.get_branding(g.tenant_id) or {}
        old_value = branding.get(key)
        db.update_branding(g.tenant_id, **{key: value})
        db.log_ai_rule_change(
            tenant_id=g.tenant_id,
            rule_category='design',
            rule_key=key,
            old_value=old_value,
            new_value=value,
            risk_level=meta['risk'],
            user_id=g.user_id,
            user_name=g.user_name or 'Admin'
        )
    else:
        return jsonify({'error': 'Content rules are read-only in this endpoint'}), 400

    return jsonify({'success': True})


@app.route('/api/ai-rules/reset', methods=['POST'])
@require_permission('ai_rules')
def api_reset_ai_rules():
    """Reset all design rules to default values and log the reset."""
    keys = list(DEFAULT_BRANDING_VALUES.keys())
    branding = db.get_branding(g.tenant_id) or {}

    # Log old values for changed keys
    for key in keys:
        old_value = branding.get(key)
        new_value = DEFAULT_BRANDING_VALUES[key]
        if old_value != new_value:
            db.log_ai_rule_change(
                tenant_id=g.tenant_id,
                rule_category='design',
                rule_key=key,
                old_value=old_value,
                new_value=new_value,
                risk_level='red',
                user_id=g.user_id,
                user_name=g.user_name or 'Admin'
            )

    db.update_branding(g.tenant_id, **DEFAULT_BRANDING_VALUES)
    return jsonify({'success': True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Presentation Approvals
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/presentations/<pres_id>/request-approval', methods=['POST'])
@require_auth
def api_request_approval(pres_id):
    """Request approval for a presentation (employee submits for review)."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'Presentation not found'}), 404
    existing = db.get_approval_status(pres_id, tenant_id=g.tenant_id)
    if existing and existing['status'] == 'pending':
        return jsonify({'error': 'Approval already requested'}), 400
    requested = db.create_approval(pres_id, g.tenant_id, g.user_id, g.user_name or 'Unknown')
    if requested.get('error') == 'use_final_approval_gate':
        return jsonify({'error': 'هذا الملف يتبع بوابة اعتماد الملف النهائي',
                        'error_code': 'use_final_approval_gate'}), 409
    if requested.get('error'):
        return jsonify({'error': 'العرض غير موجود'}), 404
    _record_change('presentation', pres_id, 'طلب تعميد العرض', ['أُرسل العرض للمراجعة'])
    return jsonify({'success': True, 'approvalId': requested['approval_id']})


@app.route('/api/approvals', methods=['GET'])
@require_permission('approvals')
def api_get_approvals():
    """Get all pending approvals for the current tenant."""
    approvals = db.get_pending_approvals(
        g.tenant_id, accessible_draft_ids=db.user_accessible_draft_ids(g.user_id, g.tenant_id))
    return jsonify({'success': True, 'approvals': approvals})


@app.route('/api/approvals/<approval_id>/review', methods=['POST'])
@require_permission('approvals')
def api_review_approval(approval_id):
    """Approve or reject a presentation."""
    data = request.json or {}
    status = data.get('status')
    if status not in ('approved', 'rejected'):
        return jsonify({'error': 'status must be approved or rejected'}), 400
    note = data.get('note')
    approval = db.get_approval(approval_id, g.tenant_id)
    if not approval:
        return jsonify({'error': 'Approval not found'}), 404
    # ISS-014: a scoped reviewer can only decide approvals inside their scope.
    pres = db.get_presentation(approval['presentation_id'], tenant_id=g.tenant_id)
    if not _presentation_in_scope(pres):
        return jsonify({'error': 'Approval not found'}), 404
    result = db.review_approval(approval_id, g.tenant_id, status, g.user_id, g.user_name or 'Admin',
                                note, allow_self=_omran_actor_is_admin())
    if not result or result.get('error'):
        code = (result or {}).get('error')
        if code == 'approval_not_found':
            return jsonify({'error': 'Approval not found'}), 404
        if code == 'use_final_approval_gate':
            return jsonify({'error': 'هذا الملف يتبع بوابة اعتماد الملف النهائي',
                            'error_code': 'use_final_approval_gate'}), 409
        if code == 'self_approval_not_allowed':
            return jsonify({'error': 'لا يمكنك اتخاذ قرار على طلب قدّمته بنفسك',
                            'error_code': 'self_approval_not_allowed'}), 403
        if code == 'content_changed':
            return jsonify({'error': 'محتوى العرض تغيّر بعد إرساله — أعد طلب الاعتماد',
                            'error_code': 'content_changed'}), 409
        if code == 'note_required':
            return jsonify({'error': 'سبب الرفض إلزامي',
                            'error_code': 'note_required'}), 400
        return jsonify({'error': 'الاعتماد لم يعد بانتظار القرار',
                        'error_code': 'approval_not_pending'}), 409
    action = 'اعتماد العرض' if status == 'approved' else 'إعادة العرض للتعديل'
    _record_change('presentation', approval['presentation_id'], action,
                   [str(note).strip()] if str(note or '').strip() else [action])
    return jsonify({'success': True})


@app.route('/api/presentations/<pres_id>/approval-status', methods=['GET'])
@require_auth
def api_approval_status(pres_id):
    """Get approval status for a presentation."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'Presentation not found'}), 404
    approval = db.get_approval_status(pres_id, tenant_id=g.tenant_id)
    return jsonify({'success': True, 'approval': approval})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Static Files + Health
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/')
def index():
    resp = send_from_directory(os.path.dirname(__file__), 'index.html')
    # "no-cache" means revalidate before use, which is what a SPA shell needs so a deploy is picked
    # up immediately. It was "no-store" as well, which forbids keeping a copy at all and forced the
    # full ~740KB down the wire on every single load. With the ETag that send_from_directory sets,
    # an unchanged shell now answers 304 with no body.
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers.pop('Pragma', None)
    resp.headers.pop('Expires', None)
    return resp


@app.route('/app', methods=['GET'])
@app.route('/app/<path:page>')
def tenant_app_page(page=''):
    """Serve the SPA shell for bookmarkable tenant workspace pages (legacy prefix)."""
    return index()


@app.route('/superadmin', methods=['GET'])
@app.route('/superadmin/<path:page>')
def superadmin_app_page(page=''):
    """Serve the SPA shell for the super-admin workspace (role guard runs client-side)."""
    return index()


@app.route('/c/<slug>', methods=['GET'])
@app.route('/c/<slug>/<path:page>')
def company_app_page(slug='', page=''):
    """Serve the SPA shell for a company workspace; slug mismatch redirects client-side."""
    try:
        _, redirect_slug = db.resolve_company_slug(slug)
        if redirect_slug:
            target = '/c/' + redirect_slug + ('/' + page if page else '')
            return redirect(target, code=301)
    except Exception:
        pass
    return index()


@app.route('/invite/<token>')
def invite_page(token):
    resp = send_from_directory(os.path.dirname(__file__), 'index.html')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


# Reserved prefixes must keep their own 404s; everything else is a client-side route and has to
# return the SPA shell, otherwise reloading or sharing a deep link drops the user on an error page.
SPA_RESERVED_PREFIXES = ('api/', 'uploads/', 'assets/', 'tenant-assets/', 'outputs/', 'static/')


@app.errorhandler(404)
def spa_fallback(error):
    path = (request.path or '/').lstrip('/')
    if request.method not in ('GET', 'HEAD') or path.startswith(SPA_RESERVED_PREFIXES):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    if 'text/html' not in (request.headers.get('Accept') or ''):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return index()

# The SPA shell references two bundles instead of twenty part files, so a cold
# load costs four static requests (shell, i18n, one JS bundle, one CSS bundle)
# instead of twenty-two. The part files stay the source of truth: edit them,
# never the bundle, and never reference a part file from the shell. This tuple
# is the single order authority shared with scripts/verify-frontend.js and the
# test suites that pin FRONTEND_JS_ORDER.
FRONTEND_CSS_ORDER = ('base.css', 'project-form.css')
FRONTEND_JS_ORDER = (
    '00-core.js', '01-nav-auth.js', '02-settings-branding.js',
    '03-executive-classification.js', '04-market.js', '05-market-competitors.js',
    '06-team.js', '07-project-form.js', '08-location-maps.js', '09-financial.js',
    '10-financial-report-timeline.js', '11-land-croquis.js', '12-files-media.js',
    '13-visual.js', '14-slides-gen.js', '15-slide-edit-chat.js',
    '16-presentations-export.js', '17-admin-boot.js', '18-omran-ops.js',
    '19-notifications.js',
)

_FRONTEND_BUNDLE_CACHE = {}


def _build_frontend_bundle(kind):
    """Concatenate part files in load order with markers, cached by content.

    The cache key is the per-file size/mtime signature, so editing a part file
    rebuilds the bundle on the next request with no build step and no restart.
    Returns (etag, raw_bytes, gzipped_bytes, content_type).
    """
    import gzip as _gzip
    import hashlib as _hashlib
    root = os.path.dirname(os.path.abspath(__file__))
    if kind == 'js':
        names, subdir, content_type = FRONTEND_JS_ORDER, 'js', 'application/javascript'
    else:
        names, subdir, content_type = FRONTEND_CSS_ORDER, 'css', 'text/css'
    paths = [os.path.join(root, 'assets', subdir, name) for name in names]
    try:
        sig = tuple((name, os.path.getsize(path), os.path.getmtime(path))
                    for name, path in zip(names, paths))
    except OSError:
        return None
    cached = _FRONTEND_BUNDLE_CACHE.get(kind)
    if cached and cached[0] == sig:
        return cached[1]
    chunks = []
    for name, path in zip(names, paths):
        with open(path, 'r', encoding='utf-8') as fh:
            content = fh.read()
        if kind == 'js':
            # A leading semicolon keeps a file ending without one from merging
            # into the next file's first expression. The marker names the part
            # for stack traces and for the bundle-composition checks.
            chunks.append('\n;\n/*__PART:' + name + '*/\n' + content)
        else:
            chunks.append('\n/*__PART:' + name + '*/\n' + content)
    raw = (''.join(chunks)).encode('utf-8')
    etag = '"' + _hashlib.sha1(raw).hexdigest() + '"'
    bundle = (etag, raw, _gzip.compress(raw, 6), content_type)
    _FRONTEND_BUNDLE_CACHE[kind] = (sig, bundle)
    return bundle


def _serve_frontend_bundle(kind):
    bundle = _build_frontend_bundle(kind)
    if bundle is None:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    etag, raw, gzipped, content_type = bundle
    if request.headers.get('If-None-Match') == etag:
        resp = app.response_class('', status=304, mimetype=content_type)
        resp.headers['ETag'] = etag
        resp.headers['Cache-Control'] = 'no-cache'
        return resp
    use_gzip = 'gzip' in (request.headers.get('Accept-Encoding') or '').lower()
    body = gzipped if use_gzip else raw
    resp = app.response_class(body, mimetype=content_type)
    resp.headers['ETag'] = etag
    # Same revalidate policy as the shell and the former part files: a deploy
    # changes the bytes, the ETag changes with them, and repeat loads are 304s.
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers.add('Vary', 'Accept-Encoding')
    if use_gzip:
        resp.headers['Content-Encoding'] = 'gzip'
    return resp


@app.route('/assets/app.bundle.js')
def frontend_js_bundle():
    return _serve_frontend_bundle('js')


@app.route('/assets/app.bundle.css')
def frontend_css_bundle():
    return _serve_frontend_bundle('css')


@app.route('/assets/<path:path>')
def static_assets(path):
    resp = send_from_directory(os.path.join(os.path.dirname(__file__), 'assets'), path)
    # Same revalidate policy as the SPA shell: the shell now references
    # assets/css + assets/js, so a stale cached script would break a fresh
    # shell after a deploy. ETag revalidation keeps repeat loads cheap.
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

MEDIA_URL_MAX_AGE = 7 * 86400
_MEDIA_URL_RE = re.compile(r"/uploads/[^\s<>'\"`\\),\]\[]+")


def _media_url_serializer():
    from itsdangerous import URLSafeTimedSerializer
    from auth import JWT_SECRET
    return URLSafeTimedSerializer(JWT_SECRET, salt='media-url-v1')


def _media_url_owned(path, tenant_id, map_basenames):
    """Whether this uploads path belongs to the tenant's own media."""
    pieces = path.lstrip('/').split('/')
    if pieces[:2] == ['uploads', 'creative'] and len(pieces) >= 4:
        return pieces[2] == tenant_id
    if pieces[:2] == ['uploads', 'maps'] and len(pieces) == 3:
        return pieces[2] in map_basenames
    if len(pieces) == 2:
        return pieces[1] in map_basenames
    return False


def _media_map_basenames(tenant_id):
    names = {os.path.basename(str(row.get('file_path') or ''))
             for row in db.get_map_images(tenant_id)}
    names.discard('')
    return names


def _sign_media_url(url, tenant_id, state):
    original_url = url
    url = re.sub(r'&(?:amp|#0*38|#x0*26);', '&', url, flags=re.IGNORECASE)
    path = url.split('?', 1)[0].split('#', 1)[0]
    pieces = path.lstrip('/').split('/')
    if getattr(g, 'is_admin', False):
        owned = True
    elif pieces[:2] == ['uploads', 'creative']:
        owned = len(pieces) >= 4 and pieces[2] == tenant_id
    else:
        if state['maps'] is None:
            state['maps'] = _media_map_basenames(tenant_id)
        owned = _media_url_owned(path, tenant_id, state['maps'])
    if not owned:
        return original_url
    sig = _media_url_serializer().dumps({'p': path})
    if '#' in url:
        base, frag = url.split('#', 1)
        frag = '#' + frag
    else:
        base, frag = url, ''
    if '?' in base:
        bare, query = base.split('?', 1)
        kept = '&'.join(p for p in re.split(r'&|;(?=s=)', query)
                        if p and not p.startswith('s='))
        return bare + '?' + (kept + '&' if kept else '') + 's=' + sig + frag
    return base + '?s=' + sig + frag


def _sign_media_refs(value, tenant_id, state):
    if isinstance(value, dict):
        return {key: _sign_media_refs(item, tenant_id, state) for key, item in value.items()}
    if isinstance(value, list):
        return [_sign_media_refs(item, tenant_id, state) for item in value]
    if not isinstance(value, str) or '/uploads/' not in value:
        return value
    def replace(match):
        signed = _sign_media_url(match.group(0), tenant_id, state)
        if signed != match.group(0):
            state['changed'] = True
        return signed
    return _MEDIA_URL_RE.sub(replace, value)


@app.after_request
def sign_media_urls(response):
    """Attach an expiring signature to the tenant's own uploads URLs in JSON.

    The media routes require either this signature or a matching session token,
    so a link copied out of a response stops working instead of staying public
    forever. Foreign or unowned references are left unsigned, which keeps them
    unservable rather than laundering access through the signer.
    """
    tenant = getattr(g, 'tenant_id', None)
    if (not tenant or not (200 <= response.status_code < 300)
            or response.mimetype != 'application/json'):
        return response
    try:
        body = response.get_data(as_text=True)
    except Exception:
        return response
    if not body or '/uploads/' not in body:
        return response
    try:
        payload = json.loads(body)
    except ValueError:
        return response
    state = {'maps': None, 'changed': False}
    signed = _sign_media_refs(payload, tenant, state)
    if state['changed']:
        response.set_data(json.dumps(signed, ensure_ascii=False))
    return response


def _media_request_authorized(path):
    """A valid expiring signature, or a session token for the owning tenant."""
    sig = request.args.get('s') or ''
    if sig:
        try:
            payload = _media_url_serializer().loads(sig, max_age=MEDIA_URL_MAX_AGE)
            if isinstance(payload, dict) and payload.get('p') == path:
                return True
        except Exception:
            pass
    header = request.headers.get('Authorization', '')
    if header.startswith('Bearer '):
        payload = decode_token(header[7:].strip())
        if payload and payload.get('sub'):
            tenant = db.get_tenant_by_id(payload['sub'])
            if tenant and tenant.get('is_active'):
                user_row, user_error = _load_token_user(payload, tenant)
                if not user_error and not _session_state_error(payload, tenant, user_row):
                    if _is_platform_admin_session(tenant, payload):
                        return True
                    return _media_url_owned(path, payload['sub'],
                                            _media_map_basenames(payload['sub']))
    return False


@app.route('/uploads/maps/<path:path>')
def static_map_uploads(path):
    """Serve persisted map assets; generation is available only via explicit APIs."""
    if not _media_request_authorized(request.path):
        return jsonify({'error': 'Not found'}), 404
    maps_dir = os.path.join(UPLOADS_DIR, 'maps')
    full_path = os.path.join(maps_dir, path)
    if os.path.isfile(full_path):
        return send_from_directory(maps_dir, path, max_age=3600)
    return jsonify({'error': 'Map image not found', 'error_code': 'MAP_ASSET_MISSING'}), 404


@app.route('/uploads/creative/<tenant_id>/<path:filename>')
def static_creative_upload(tenant_id, filename):
    """Serve generated creative images without exposing arbitrary upload paths."""
    safe_tenant = re.sub(r'[^A-Za-z0-9_-]', '', tenant_id)
    if not _media_request_authorized(request.path):
        return jsonify({'error': 'Not found'}), 404
    safe_filename = os.path.basename(filename)
    revision_asset = bool(re.fullmatch(r'revisions/[a-f0-9]{64}\.(?:png|jpg|jpeg|webp|gif|avif|bmp|ico|svg|ttf|otf|woff|woff2)', filename))
    if safe_tenant != tenant_id or (safe_filename != filename and not revision_asset):
        return jsonify({'error': 'Not found'}), 404
    if revision_asset:
        safe_filename = filename
    creative_dir = os.path.join(UPLOADS_DIR, 'creative', safe_tenant)
    if revision_asset:
        revision_path = os.path.realpath(os.path.join(creative_dir, safe_filename))
        if not revision_path.startswith(os.path.realpath(creative_dir) + os.sep):
            return jsonify({'error': 'Not found'}), 404
    if not os.path.isfile(os.path.join(creative_dir, safe_filename)):
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory(creative_dir, safe_filename, max_age=86400)


@app.route('/uploads/<path:path>')
def static_uploads(path):
    """Serve map images or static presentation assets."""
    if not _media_request_authorized(request.path):
        return jsonify({'error': 'Not found'}), 404
    maps_dir = os.path.join(UPLOADS_DIR, 'maps')
    filename = os.path.basename(path)
    possible_map = os.path.join(maps_dir, filename)
    if os.path.isfile(possible_map):
        return send_from_directory(maps_dir, filename, max_age=3600)
    return jsonify({'error': 'Not found'}), 404

APP_STARTED_AT = datetime.now(timezone.utc).isoformat()
_BUILD_COMMIT = None


def _build_commit():
    """The commit the running code came from, read once."""
    global _BUILD_COMMIT
    if _BUILD_COMMIT is None:
        try:
            _BUILD_COMMIT = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                stderr=subprocess.DEVNULL, timeout=5).decode().strip()
        except Exception:
            metadata = _read_deployment_metadata()
            deployed = metadata.get('deployed_commit') or metadata.get('commit')
            _BUILD_COMMIT = str(os.environ.get('DEPLOY_COMMIT') or deployed or 'unknown')[:7]
    return _BUILD_COMMIT


BUILD_FINGERPRINT_FILES = ('app.py', 'index.html', 'slide_engine.py', 'design_templates.py',
                           'generate_pdf_from_preview.py', 'db.py',
                           'assets/i18n.js',
                           'assets/css/base.css', 'assets/css/project-form.css',
                           'assets/js/00-core.js', 'assets/js/01-nav-auth.js',
                           'assets/js/02-settings-branding.js',
                           'assets/js/03-executive-classification.js',
                           'assets/js/04-market.js', 'assets/js/05-market-competitors.js',
                           'assets/js/06-team.js', 'assets/js/07-project-form.js',
                           'assets/js/08-location-maps.js', 'assets/js/09-financial.js',
                           'assets/js/10-financial-report-timeline.js',
                           'assets/js/11-land-croquis.js', 'assets/js/12-files-media.js',
                           'assets/js/13-visual.js', 'assets/js/14-slides-gen.js',
                           'assets/js/15-slide-edit-chat.js',
                           'assets/js/16-presentations-export.js',
                           'assets/js/17-admin-boot.js')


def _build_fingerprint():
    """A hash per source file, so the live code can be compared with a checkout.

    The commit alone is not enough: the deploy checks the tree out without a `.git` beside it, so
    `git rev-parse` on the server answers nothing and «هل نزل الإصلاح؟» stayed unanswered.
    """
    fingerprint = {}
    root = os.path.dirname(os.path.abspath(__file__))
    for name in BUILD_FINGERPRINT_FILES:
        path = os.path.join(root, name)
        try:
            with open(path, 'rb') as source:
                # Line endings are normalised: a Windows checkout is CRLF and the server is LF, so
                # the raw hash reported a difference where the code was identical.
                data = source.read().replace(b'\r\n', b'\n')
            # Split modules: the top-level file is only a loader, so fold every
            # ordered part into the same key — a part edit must move the fingerprint.
            parts_dir = os.path.join(root, name[:-3] + '_parts')
            if name.endswith('.py') and os.path.isdir(parts_dir):
                for part in sorted(p for p in os.listdir(parts_dir) if p.endswith('.py')):
                    with open(os.path.join(parts_dir, part), 'rb') as part_source:
                        data += part_source.read().replace(b'\r\n', b'\n')
            fingerprint[name] = hashlib.sha256(data).hexdigest()[:12]
        except OSError:
            fingerprint[name] = 'missing'
    return fingerprint


@app.route('/api/build', methods=['GET'])
def api_build():
    """Which build is actually live.

    «هل نزل الإصلاح؟» had no answer but guessing: the frontend could be checked by fetching the
    page, and a server-side fix could not be checked at all.
    """
    return jsonify({'commit': _build_commit(), 'startedAt': APP_STARTED_AT,
                    'sources': _build_fingerprint()})


@app.route('/api/deploy-webhook', methods=['GET', 'POST'])
def deploy_webhook():
    """Endpoint for GitHub or cPanel webhook to trigger automated deployment after commits."""
    env_secret = os.environ.get('DEPLOY_WEBHOOK_SECRET')
    if not env_secret:
        return jsonify({'error': 'DEPLOY_WEBHOOK_SECRET not configured in environment'}), 403

    secret = request.args.get('secret') or request.headers.get('X-Deploy-Secret') or (request.json.get('secret') if (request.is_json and request.json) else None)
    if not secret or secret != env_secret:
        return jsonify({'error': 'Unauthorized'}), 401

    requested_commit = request.args.get('commit') or (
        request.json.get('commit') if (request.is_json and request.json) else None
    )
    if requested_commit and not re.fullmatch(r'[0-9a-fA-F]{40}', str(requested_commit)):
        return jsonify({'error': 'Invalid deployment commit'}), 400
    
    deploy_script = '/home/landloom/proposal-generator/deploy.sh'
    if not os.path.exists(deploy_script):
        deploy_script = os.path.join(os.path.dirname(__file__), 'deploy.sh')

    if os.path.exists(deploy_script):
        try:
            import subprocess
            command = ['bash', deploy_script]
            if requested_commit:
                command.append(str(requested_commit))
            
            deploy_log_path = '/home/landloom/proposal-generator/deploy.log'
            if not os.path.exists(os.path.dirname(deploy_log_path)):
                deploy_log_path = os.path.join(os.path.dirname(__file__), 'deploy.log')
            
            log_fh = None
            try:
                log_fh = open(deploy_log_path, 'a', encoding='utf-8')
                log_fh.write(f"\n--- Deployment triggered at {db._utcnow().isoformat()} for commit {requested_commit or 'latest'} ---\n")
                log_fh.flush()
            except OSError:
                log_fh = None
            
            popen_kwargs = {'start_new_session': True}
            if log_fh is not None:
                popen_kwargs['stdout'] = log_fh
                popen_kwargs['stderr'] = subprocess.STDOUT

            try:
                subprocess.Popen(command, **popen_kwargs)
            finally:
                if log_fh is not None:
                    log_fh.close()
            return jsonify({'status': 'Deployment triggered successfully',
                            'expected_commit': requested_commit,
                            'timestamp': db._utcnow().isoformat()}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    return jsonify({'error': 'deploy.sh not found'}), 404


@app.route('/api/deploy-webhook-staging', methods=['GET', 'POST'])
def deploy_webhook_staging():
    """Staging counterpart of deploy_webhook: deploys origin/lab into the
    separate proposal-generator-staging directory. Production paths are never
    touched here, so lab experiments cannot overwrite client data."""
    env_secret = os.environ.get('DEPLOY_WEBHOOK_SECRET_STAGING') or os.environ.get('DEPLOY_WEBHOOK_SECRET')
    if not env_secret:
        return jsonify({'error': 'DEPLOY_WEBHOOK_SECRET not configured in environment'}), 403

    secret = request.args.get('secret') or request.headers.get('X-Deploy-Secret') or (request.json.get('secret') if (request.is_json and request.json) else None)
    if not secret or secret != env_secret:
        return jsonify({'error': 'Unauthorized'}), 401

    requested_commit = request.args.get('commit') or (
        request.json.get('commit') if (request.is_json and request.json) else None
    )
    if requested_commit and not re.fullmatch(r'[0-9a-fA-F]{40}', str(requested_commit)):
        return jsonify({'error': 'Invalid deployment commit'}), 400

    deploy_script = '/home/landloom/proposal-generator-staging/deploy-staging.sh'
    if not os.path.exists(deploy_script):
        deploy_script = os.path.join(os.path.dirname(__file__), 'deploy-staging.sh')

    if os.path.exists(deploy_script):
        try:
            import subprocess
            command = ['bash', deploy_script]
            if requested_commit:
                command.append(str(requested_commit))

            deploy_log_path = '/home/landloom/proposal-generator-staging/deploy.log'
            if not os.path.exists(os.path.dirname(deploy_log_path)):
                deploy_log_path = os.path.join(os.path.dirname(__file__), 'deploy-staging.log')

            log_fh = None
            try:
                log_fh = open(deploy_log_path, 'a', encoding='utf-8')
                log_fh.write(f"\n--- Staging deployment triggered at {db._utcnow().isoformat()} for commit {requested_commit or 'latest'} ---\n")
                log_fh.flush()
            except OSError:
                log_fh = None

            popen_kwargs = {'start_new_session': True}
            if log_fh is not None:
                popen_kwargs['stdout'] = log_fh
                popen_kwargs['stderr'] = subprocess.STDOUT

            try:
                subprocess.Popen(command, **popen_kwargs)
            finally:
                if log_fh is not None:
                    log_fh.close()
            return jsonify({'status': 'Staging deployment triggered successfully',
                            'target': 'staging',
                            'expected_commit': requested_commit,
                            'timestamp': db._utcnow().isoformat()}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    return jsonify({'error': 'deploy-staging.sh not found'}), 404


@app.route('/favicon.ico')
def favicon():
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'favicon.ico')):
        return send_from_directory(os.path.dirname(__file__), 'favicon.ico', mimetype='image/vnd.microsoft.icon')
    return ('', 204)


def _read_deployment_metadata():
    metadata = {'commit': 'unknown', 'deployed_commit': 'unknown', 'deployed_at': None, 'source': 'git'}
    try:
        with open(DEPLOYMENT_MARKER_PATH, 'r', encoding='utf-8') as marker:
            raw = marker.read().strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    metadata.update({key: value for key, value in parsed.items() if value is not None})
                else:
                    metadata['deployed_commit'] = raw
            except (TypeError, ValueError):
                metadata['deployed_commit'] = raw
            if metadata.get('source') == 'git':
                metadata['source'] = 'deployment_marker'
    except OSError:
        pass

    stored_deployed_commit = metadata.get('deployed_commit')
    if not stored_deployed_commit or stored_deployed_commit == 'unknown':
        stored_deployed_commit = metadata.get('commit')
    deployed_commit = str(stored_deployed_commit or 'unknown')
    metadata['deployed_commit'] = deployed_commit
    if deployed_commit != 'unknown':
        metadata['commit'] = deployed_commit[:7]
        return metadata
    try:
        commit_hash = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=os.path.dirname(__file__),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if commit_hash:
            metadata['commit'] = commit_hash
            metadata['deployed_commit'] = commit_hash
    except Exception:
        pass
    return metadata


def _deployed_vision_status():
    """What the deployment recorded about the slide renderer, including the install log tail."""
    for directory in ('/home/landloom/proposal-generator', os.path.dirname(__file__)):
        path = os.path.join(directory, '.vision_status')
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8') as handle:
                status = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(status, dict):
            return {
                'available': bool(status.get('available')),
                'error': str(status.get('error') or '')[:400],
                'installLog': str(status.get('installLog') or '')[:600],
                'source': 'deploy',
            }
    return None


def _slide_vision_probe(force=False):
    """Whether this host can render a slide to an image at all.

    `deploy.sh` installs Chromium best-effort and logs a failure to /tmp, and a missing snapshot
    only ever reached the server log, so nobody could tell whether the designer was editing with
    vision or blind. The probe is cached, and every real edit records its outcome here.
    """
    if _SLIDE_VISION_STATE and not force:
        return dict(_SLIDE_VISION_STATE)
    state = {'available': False, 'error': '', 'source': 'probe'}
    try:
        import generate_pdf_from_preview as renderer
        state['available'] = bool(renderer.render_slide_to_image_base64(
            '<div class="slide" style="width:1280px;height:720px;">فحص</div>'))
        if not state['available']:
            state['error'] = getattr(renderer, 'LAST_VISION_ERROR', '') or 'renderer_returned_nothing'
    except Exception as exc:
        state['error'] = renderer.short_browser_error(exc)
    _record_slide_vision_state(state['available'], state['error'], source='probe')
    return dict(_SLIDE_VISION_STATE)


@app.route('/health')
def health():
    metadata = _read_deployment_metadata()
    if request.args.get('vision'):
        _slide_vision_probe(force=True)
    return jsonify({
        'status': 'ok',
        'slide_vision': dict(_SLIDE_VISION_STATE) or _deployed_vision_status(),
        'commit': metadata.get('commit', 'unknown'),
        'deployed_commit': metadata.get('deployed_commit', 'unknown'),
        'deployed_at': metadata.get('deployed_at'),
        'deployment_source': metadata.get('source'),
        'map_label_font': os.path.basename(maps_service.bundled_arabic_overlay_font_path() or ''),
        'model': GLM_MODEL,
        'image_model': IMAGE_MODEL,
    })

@app.route('/preview')
def preview():
    return send_from_directory(os.path.dirname(__file__), 'preview.html')

# Install queued designer-chat execution and deterministic reliability handlers.
designer_chat_reliability.install(app, globals())
