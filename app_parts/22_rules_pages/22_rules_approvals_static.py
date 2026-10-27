

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
@require_auth
def api_get_approvals():
    """Get all pending approvals for the current tenant — permission holders
    or users holding an approver assignment."""
    if not _landloom_can('approvals') and not _landloom_has_approver_assignment():
        return _landloom_forbidden()
    approvals = db.get_pending_approvals(
        g.tenant_id, accessible_draft_ids=db.user_accessible_draft_ids(g.user_id, g.tenant_id))
    if not _landloom_actor_is_admin() and g.user_id:
        # A draft with a named approver waits on that approver — the rest of
        # the pool does not see it in their queue.
        filtered = []
        for row in approvals:
            did = row.get('draft_id')
            try:
                assigned = db.assigned_approver(g.tenant_id, did) if did else None
            except Exception:
                assigned = None
            if assigned and str(assigned.get('user_id') or '') != str(g.user_id):
                continue
            filtered.append(row)
        approvals = filtered
    return jsonify({'success': True, 'approvals': approvals})


@app.route('/api/approvals/<approval_id>/review', methods=['POST'])
@require_auth
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
    if not _landloom_can_decide('approvals', (pres or {}).get('draft_id')):
        return _landloom_forbidden()
    if not _presentation_in_scope(pres):
        return jsonify({'error': 'Approval not found'}), 404
    result = db.review_approval(approval_id, g.tenant_id, status, g.user_id, g.user_name or 'Admin',
                                note, allow_self=_landloom_actor_is_admin())
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
# The bare "/" no longer serves the SPA: it is the public landing page in
# 22a_public_pages.py. The shell itself stays reachable through /app, /c/<slug>,
# /superadmin and /invite/<token>, which all call index().
def index():
    resp = send_from_directory(os.path.dirname(__file__), 'index.html', conditional=False)
    # Bundle URLs carry a version derived from their source files, so browsers
    # can keep those large assets between refreshes without serving stale code
    # after a deploy. Include the same versions in the shell ETag so a changed
    # bundle forces the small shell response to refresh too.
    try:
        versions = {
            'i18n': _frontend_bundle_asset_version('i18n'),
            'css': _frontend_bundle_asset_version('css'),
            'js': _frontend_bundle_asset_version('js'),
        }
        replacements = (
            (b'/assets/i18n.bundle.js', 'i18n'),
            (b'/assets/app.bundle.css', 'css'),
            (b'/assets/app.bundle.js', 'js'),
        )
        resp.direct_passthrough = False
        body = resp.get_data()
        for asset_path, kind in replacements:
            version = versions.get(kind)
            if version:
                body = body.replace(asset_path, asset_path + b'?v=' + version.encode('ascii'))
        resp.set_data(body)
        resp.set_etag(hashlib.sha1(body).hexdigest())
        resp.make_conditional(request)
    except Exception:
        app.logger.warning('Could not version frontend bundle URLs', exc_info=True)
    # "no-cache" means revalidate before use, which is what a SPA shell needs so a deploy is picked
    # up immediately. It was "no-store" as well, which forbids keeping a copy at all and forced the
    # full ~740KB down the wire on every single load. The ETag covers both the shell and bundle
    # versions, so unchanged refreshes answer 304 while a changed frontend gets fresh URLs.
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


BUILD_FINGERPRINT_FILES = ('app.py', 'index.html', 'modules/slides/slide_engine.py',
                           'modules/slides/design_templates.py',
                           'modules/pdf/generate_pdf_from_preview.py', 'modules/db/db.py',
                           'assets/i18n.js', 'assets/i18n',
                           'assets/css/base', 'assets/css/project-form',
                           'assets/js/00-core.js', 'assets/js/01-nav-auth.js',
                           'assets/js/02-settings-branding',
                           'assets/js/03-executive-classification.js',
                           'assets/js/04-market.js', 'assets/js/04-market',
                           'assets/js/05-market-competitors.js',
                           'assets/js/05-market-competitors',
                           'assets/js/05a-market-summary-chat.js',
                           'assets/js/06-team.js', 'assets/js/07-project-form',
                           'assets/js/08-location-maps', 'assets/js/09-financial',
                           'assets/js/10-financial-report-timeline',
                           'assets/js/11-land-croquis', 'assets/js/12-files-media',
                           'assets/js/13-visual', 'assets/js/14-slides-gen',
                           'assets/js/15-slide-edit-chat',
                           'assets/js/16-presentations-export',
                           'assets/js/17-admin-boot')


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
            data = b''
            if os.path.isdir(path):
                for dirpath, dirnames, filenames in os.walk(path):
                    dirnames.sort()
                    for part in sorted(filenames):
                        with open(os.path.join(dirpath, part), 'rb') as part_source:
                            data += part_source.read().replace(b'\r\n', b'\n')
            else:
                with open(path, 'rb') as source:
                    # Line endings are normalised: a Windows checkout is CRLF and the server is LF, so
                    # the raw hash reported a difference where the code was identical.
                    data = source.read().replace(b'\r\n', b'\n')
                # Split modules: the top-level file is only a loader, so fold every
                # ordered part into the same key — a part edit must move the fingerprint.
                parts_dir = os.path.join(root, name[:-3] + '_parts')
                if name.endswith('.py') and os.path.isdir(parts_dir):
                    part_paths = []
                    for dirpath, dirnames, filenames in os.walk(parts_dir):
                        for filename in filenames:
                            if filename.endswith('.py'):
                                part_paths.append(os.path.join(dirpath, filename))
                    for part_path in sorted(part_paths, key=lambda p: (os.path.basename(p), p)):
                        with open(part_path, 'rb') as part_source:
                            data += part_source.read().replace(b'\r\n', b'\n')
            fingerprint[name] = hashlib.sha256(data).hexdigest()[:12]
        except OSError:
            fingerprint[name] = 'missing'
    return fingerprint


def _diagnostic_request_is_admin():
    """Bearer-token platform admin check for the diagnostic endpoints.

    /health and /api/build must stay publicly reachable (watchdogs and the
    deploy workflows poll them), so the verbose internals are only attached
    when a platform-admin session token is supplied.
    """
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return False
    payload = decode_token(header[7:].strip())
    if not payload or not payload.get('sub'):
        return False
    tenant = db.get_tenant_by_id(payload['sub'])
    if not tenant:
        return False
    return bool(_is_platform_admin_session(tenant, payload))


@app.route('/api/build', methods=['GET'])
def api_build():
    """Which build is actually live.

    «هل نزل الإصلاح؟» had no answer but guessing: the frontend could be checked by fetching the
    page, and a server-side fix could not be checked at all. The per-file fingerprint map is
    admin-only — it discloses the exact deployed revision of every source file.
    """
    body = {'commit': _build_commit(), 'startedAt': APP_STARTED_AT}
    if _diagnostic_request_is_admin():
        body['sources'] = _build_fingerprint()
    return jsonify(body)


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
    body = {
        'status': 'ok',
        'commit': metadata.get('commit', 'unknown'),
        'deployed_commit': metadata.get('deployed_commit', 'unknown'),
        'deployed_at': metadata.get('deployed_at'),
        'deployment_source': metadata.get('source'),
        'last_deploy': _read_deploy_status(),
        'map_label_font': os.path.basename(maps_service.bundled_arabic_overlay_font_path() or ''),
    }
    # Model/config internals and the chromium probe stay behind a platform-admin
    # token: public, they disclosed deployment config and let anyone trigger a
    # CPU-heavy headless render via ?vision=1.
    if _diagnostic_request_is_admin():
        if request.args.get('vision'):
            _slide_vision_probe(force=True)
        body.update({
            'slide_vision': dict(_SLIDE_VISION_STATE) or _deployed_vision_status(),
            'model': GEMINI_TEXT_MODEL,
            'vision_model': VISION_MODEL,
            'image_model': IMAGE_MODEL,
            'designer_agent': DESIGNER_AGENT,
            'designer_agent_planner_model': DESIGNER_AGENT_PLANNER_MODEL if DESIGNER_AGENT else None,
        })
    return jsonify(body)

@app.route('/preview')
def preview():
    return send_from_directory(os.path.dirname(__file__), 'preview.html')

# Install queued designer-chat execution and deterministic reliability handlers.
designer_chat_reliability.install(app, globals())
