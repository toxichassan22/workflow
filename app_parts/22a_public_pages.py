

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Public marketing surface: the landing page, the legal pages and the open
# "request access" intake. These routes carry no authentication — the app
# itself lives at /app, /c/<slug>, /superadmin and /invite/<token>, all of
# which still serve index() below. Everything here is static HTML plus one
# rate-limited POST; the pages share no SPA assets so first paint stays light.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _serve_public_page(name):
    """Static public pages get the same revalidate policy as the SPA shell."""
    resp = send_from_directory(
        os.path.join(os.path.dirname(__file__), 'pages'), name)
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/')
def public_landing():
    return _serve_public_page('landing.html')


@app.route('/pages/<path:path>')
def public_page_assets(path):
    return _serve_public_page(path)


# ── Editable legal pages ────────────────────────────────────────────────────
# terms.html / privacy.html carry the default copy between LEGAL_*_START/END
# markers inside lang="ar"/lang="en" divs. A desk-saved override lives in
# platform_settings under legal_<name> ({'ar': html, 'en': html, ...}) and is
# spliced in at serve time — no client fetch, no flash of stale text, and the
# baked copy stays the fallback when nothing is stored.

LEGAL_DOCS = ('terms', 'privacy')
_LEGAL_MARKERS = {
    'ar': ('<!--LEGAL_AR_START-->', '<!--LEGAL_AR_END-->'),
    'en': ('<!--LEGAL_EN_START-->', '<!--LEGAL_EN_END-->'),
}


def _legal_setting_key(name):
    return 'legal_' + name


def _serve_legal_page(name):
    path = os.path.join(os.path.dirname(__file__), 'pages', name + '.html')
    with open(path, encoding='utf-8') as fh:
        html = fh.read()
    stored = db.get_platform_setting(_legal_setting_key(name))
    if isinstance(stored, dict):
        for lang, (start, end) in _LEGAL_MARKERS.items():
            body = stored.get(lang)
            if not isinstance(body, str) or not body.strip():
                continue
            i, j = html.find(start), html.find(end)
            if i != -1 and j != -1 and j > i:
                html = html[:i + len(start)] + '\n' + body + '\n      ' + html[j:]
    resp = Response(html, mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/terms')
def public_terms():
    return _serve_legal_page('terms')


@app.route('/privacy')
def public_privacy():
    return _serve_legal_page('privacy')


@app.route('/api/admin/legal/<name>', methods=['PUT'])
@require_admin
def api_admin_save_legal(name):
    """Desk-edited Arabic/English copy for a public legal page."""
    if name not in LEGAL_DOCS:
        return jsonify({'error': 'Unknown document'}), 404
    data = request.json or {}
    doc = {}
    for lang in ('ar', 'en'):
        body = data.get(lang)
        if not isinstance(body, str) or not body.strip():
            return jsonify({'error': 'Arabic and English content are both required'}), 400
        if len(body) > 200000:
            return jsonify({'error': 'Content is too large'}), 400
        doc[lang] = body
    doc['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    doc['updated_by'] = _landloom_actor_name() or ''
    saved = db.set_platform_setting(_legal_setting_key(name), doc)
    _record_audit_event('legal.updated', 'platform_settings', _legal_setting_key(name))
    return jsonify({'success': True, 'document': saved})


@app.route('/about')
def public_about():
    return _serve_public_page('about.html')


@app.route('/api/join-requests', methods=['POST'])
def api_join_request():
    """The landing page's public "request access" intake.

    Accounts stay provisioned by the desk — this only records the lead and
    notifies every super admin. The hidden ``website`` field is a bot
    honeypot: a filled value gets a fake success and stores nothing, so
    spammers cannot tell they were dropped.
    """
    limited = _rate_limit_attempt('join:ip', _rate_limit_client_ip())
    if limited:
        return limited
    data = request.json or {}
    if (data.get('website') or '').strip():
        return jsonify({'success': True}), 201
    name = (data.get('name') or '').strip()
    company = (data.get('company') or '').strip()
    email = (data.get('email') or '').strip().lower()
    phone = (data.get('phone') or '').strip()
    message = (data.get('message') or '').strip()
    if not name or not company or not email:
        return jsonify({'error': 'name, company, and email are required'}), 400
    if len(name) > 120 or len(company) > 120:
        return jsonify({'error': 'Name is too long'}), 400
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return jsonify({'error': 'Invalid email address'}), 400
    if len(phone) > 40 or len(message) > 2000:
        return jsonify({'error': 'Message is too long'}), 400

    row = db.create_join_request(name, company, email, phone=phone, message=message)
    _notify_super_admins(
        'طلب انضمام جديد إلى المنصة',
        '«{}» — {} — {}{}{}'.format(
            company, name, email,
            ' — ' + phone if phone else '',
            ' — ' + message[:160] if message else ''),
        entity_type='join_request', entity_id=row['id'])
    return jsonify({'success': True}), 201


@app.route('/api/admin/join-requests', methods=['GET'])
@require_admin
def api_admin_list_join_requests():
    """Recorded leads for the desk; a listing UI can sit on this later."""
    rows = db.list_join_requests(status=request.args.get('status'))
    return jsonify({'success': True, 'requests': rows})


JOIN_REQUEST_STATUSES = ('new', 'contacted', 'closed')


@app.route('/api/admin/join-requests/<request_id>/status', methods=['POST'])
@require_admin
def api_admin_update_join_request(request_id):
    """Desk triage for access leads: new -> contacted -> closed."""
    status = (request.json or {}).get('status')
    if status not in JOIN_REQUEST_STATUSES:
        return jsonify({'error': 'Invalid status'}), 400
    row = db.update_join_request_status(request_id, status)
    if not row:
        return jsonify({'error': 'Not found'}), 404
    _record_audit_event('join_request.status', 'join_request', request_id,
                        metadata={'status': status})
    return jsonify({'success': True, 'request': row})
