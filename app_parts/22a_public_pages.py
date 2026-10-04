

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


@app.route('/terms')
def public_terms():
    return _serve_public_page('terms.html')


@app.route('/privacy')
def public_privacy():
    return _serve_public_page('privacy.html')


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
