# Public read-only presentation sharing: owner-side link management plus the
# unauthenticated viewer, its password gate and a share-scoped media route.
# The token is the only credential on the public side — no tenant, user or
# project data leaves the server through these routes.

import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit

import auth
import db

SHARE_EXPIRY_CHOICES = {'1d': 1, '7d': 7, '30d': 30, 'never': None}
_SHARE_MEDIA_URL_RE = re.compile(r'/(?:uploads/[^\s"\'<>()]+|api/project-files/[A-Za-z0-9_-]+)')
_SHARE_PASSWORD_WINDOW = 300
_SHARE_PASSWORD_LIMIT = 10
_SHARE_ATTEMPTS = {}
_SHARE_MEDIA_CACHE = {}
_SHARE_MEDIA_CACHE_TTL = 45


def _share_now():
    return db._utcnow()


def _share_iso(moment):
    return moment.strftime('%Y-%m-%d %H:%M:%S')


def _share_url(token):
    base = (os.environ.get('PUBLIC_BASE_URL') or request.host_url or '').rstrip('/')
    return base + '/s/' + token


def _share_owner_payload(share):
    expires_at = share.get('expires_at')
    expired = bool(expires_at) and str(expires_at) < _share_iso(_share_now())
    return {
        'id': share.get('id'),
        'token': share.get('token'),
        'url': _share_url(share.get('token') or ''),
        'hasPassword': bool(share.get('password_hash')),
        'expiresAt': expires_at,
        'createdAt': share.get('created_at'),
        'revokedAt': share.get('revoked_at'),
        'viewCount': int(share.get('view_count') or 0),
        'lastViewedAt': share.get('last_viewed_at'),
        'status': 'revoked' if share.get('revoked_at') else ('expired' if expired else 'active'),
    }


def _live_share(token):
    share = db.get_presentation_share_by_token(token)
    if not share or share.get('revoked_at'):
        return None
    expires_at = str(share.get('expires_at') or '')
    if expires_at and expires_at < _share_iso(_share_now()):
        return None
    return share


def _share_cookie_name(share_id):
    return 'wf_share_' + re.sub(r'[^A-Za-z0-9]', '', str(share_id))


def _share_cookie_value(share_id):
    return hmac.new(auth.JWT_SECRET.encode('utf-8'),
                    ('share-unlock:' + str(share_id)).encode('utf-8'),
                    hashlib.sha256).hexdigest()


def _share_unlocked(share):
    if not share.get('password_hash'):
        return True
    supplied = request.cookies.get(_share_cookie_name(share.get('id')), '')
    return bool(supplied) and hmac.compare_digest(supplied, _share_cookie_value(share.get('id')))


def _share_password_allowed(share_id):
    now = time.time()
    attempts = [at for at in _SHARE_ATTEMPTS.get(share_id, []) if now - at < _SHARE_PASSWORD_WINDOW]
    if len(attempts) >= _SHARE_PASSWORD_LIMIT:
        _SHARE_ATTEMPTS[share_id] = attempts
        return False
    attempts.append(now)
    _SHARE_ATTEMPTS[share_id] = attempts
    return True


def _share_slides(share):
    presentation = db.get_presentation(share.get('presentation_id'), tenant_id=share.get('tenant_id'))
    if not presentation:
        return None, []
    import json
    try:
        slides = json.loads(presentation.get('slides_data') or '[]')
    except (TypeError, ValueError):
        slides = []
    if not isinstance(slides, list):
        slides = []
    return presentation, slides


def _rewrite_share_urls(html, token):
    def replace(match):
        return '/s/' + token + '/media?src=' + quote(match.group(0), safe='')
    return _SHARE_MEDIA_URL_RE.sub(replace, str(html or ''))


def _share_allowed_media_urls(share):
    share_id = share.get('id')
    cached = _SHARE_MEDIA_CACHE.get(share_id)
    now = time.time()
    if cached and now - cached[0] < _SHARE_MEDIA_CACHE_TTL:
        return cached[1]
    _presentation, slides = _share_slides(share)
    allowed = set()
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        for match in _SHARE_MEDIA_URL_RE.finditer(str(slide.get('html') or '')):
            allowed.add(urlsplit(match.group(0)).path)
    _SHARE_MEDIA_CACHE[share_id] = (now, allowed)
    return allowed


def _share_font_css(tenant_id):
    try:
        from design_templates import build_font_css
        branding = db.get_branding(tenant_id) or {}
        css, _family = build_font_css(branding, tenant_id, embed=True)
        return css or ''
    except Exception:
        return ''


def _noindex(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response.headers['Cache-Control'] = 'no-store'
    return response


def _share_page_html(token):
    token_json = __import__('json').dumps(token)
    return '''<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive">
<title>عرض تقديمي</title>
<style>
:root{--navy:#07182C;--teal:#17C8E3;--muted:#94a3b8}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:#050B14;color:#fff;
font-family:'The Sans Arabic',Tahoma,Arial,sans-serif}
#shareApp{height:100%;display:flex;align-items:center;justify-content:center;position:relative}
#shareStage{position:relative;width:1280px;height:720px;background:#fff;
transform-origin:center center;box-shadow:0 30px 90px rgba(0,0,0,.55)}
#shareStage .slide{width:1280px!important;height:720px!important;margin:0!important;transform:none!important}
#shareGate{position:fixed;inset:0;display:none;align-items:center;justify-content:center;background:#050B14;z-index:30}
#shareGate.is-open{display:flex}
.gate-card{width:min(380px,92vw);background:#fff;color:#0f172a;border-radius:16px;padding:26px;display:flex;flex-direction:column;gap:12px}
.gate-card h1{margin:0;font-size:19px;color:var(--navy)}
.gate-card label{font-size:12px;font-weight:700;color:#475569}
.gate-card input{border:1px solid #dbe3ea;border-radius:9px;padding:10px;font:inherit;font-size:14px}
.gate-card button{border:0;border-radius:9px;padding:11px;background:var(--navy);color:#fff;font:inherit;font-weight:800;cursor:pointer}
.gate-error{min-height:18px;font-size:12px;color:#b3261e}
#shareStatus{position:fixed;top:22px;right:50%;transform:translateX(50%);font-size:13px;color:#cbd5e1;z-index:20}
#shareStatus.is-error{color:#fca5a5}
#shareControls{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);display:flex;
align-items:center;gap:8px;padding:7px 10px;border-radius:999px;background:rgba(15,23,42,.82);
border:1px solid rgba(255,255,255,.14);transition:opacity .25s ease;z-index:25}
body.controls-hidden #shareControls{opacity:0;pointer-events:none}
#shareControls button{border:0;background:rgba(255,255,255,.12);color:#fff;font:inherit;
font-size:12px;font-weight:700;border-radius:999px;padding:6px 14px;cursor:pointer}
#shareControls button:hover{background:rgba(255,255,255,.24)}
#shareCounter{color:rgba(255,255,255,.82);font-size:12px;font-weight:800;direction:ltr;min-width:58px;text-align:center}
@media(max-width:700px){#shareControls button{font-size:11px;padding:6px 10px}}
</style>
__FONT_CSS__
</head>
<body>
<div id="shareStatus"></div>
<div id="shareApp"><div id="shareStage"></div></div>
<div id="shareGate" role="dialog" aria-modal="true">
  <form class="gate-card" id="shareGateForm">
    <h1>عرض محمي</h1>
    <label for="sharePassword">كلمة المرور</label>
    <input id="sharePassword" type="password" autocomplete="current-password">
    <div class="gate-error" id="shareGateError"></div>
    <button type="submit">فتح العرض</button>
  </form>
</div>
<div id="shareControls">
  <button type="button" id="sharePrev">السابق</button>
  <span id="shareCounter">1 / 1</span>
  <button type="button" id="shareNext">التالي</button>
  <button type="button" id="shareFull">ملء الشاشة</button>
</div>
<script src="/s/shared-viewer.js"></script>
</body>
</html>'''.replace('__TOKEN__', token_json).replace('__FONT_CSS__', '<style>__SHARE_FONT_CSS__</style>')


_SHARE_VIEWER_JS = r'''(function(){
  var token = (location.pathname.split('/')[2] || '');
  var apiBase = '/api/public/shares/' + encodeURIComponent(token);
  var slides = [];
  var index = 0;
  var stage = document.getElementById('shareStage');
  var status = document.getElementById('shareStatus');
  var gate = document.getElementById('shareGate');
  var gateError = document.getElementById('shareGateError');
  var counter = document.getElementById('shareCounter');
  var hideTimer = null;

  function setStatus(text, isError){
    status.textContent = text || '';
    status.classList.toggle('is-error', !!isError);
  }
  function fit(){
    var scale = Math.min(window.innerWidth / 1280, window.innerHeight / 720) * 0.94;
    stage.style.transform = 'scale(' + scale.toFixed(4) + ')';
  }
  function render(){
    if (!slides.length) return;
    stage.innerHTML = slides[index].html || '';
    counter.textContent = (index + 1) + ' / ' + slides.length;
    fit();
  }
  function step(delta){
    var next = index + delta;
    if (next < 0 || next >= slides.length) return;
    index = next;
    render();
    showControls();
  }
  function showControls(){
    document.body.classList.remove('controls-hidden');
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(function(){ document.body.classList.add('controls-hidden'); }, 2600);
  }
  function load(){
    fetch(apiBase, { credentials: 'same-origin' })
      .then(function(response){
        return response.json().then(function(body){ return { status: response.status, body: body }; });
      })
      .then(function(result){
        if (result.status === 401 && result.body && result.body.passwordRequired) {
          gate.classList.add('is-open');
          document.getElementById('sharePassword').focus();
          return;
        }
        if (!result.body || !result.body.success) {
          setStatus((result.body && result.body.error) || 'الرابط غير صالح أو منتهي الصلاحية', true);
          return;
        }
        slides = Array.isArray(result.body.slides) ? result.body.slides : [];
        if (!slides.length) { setStatus('لا توجد شرائح في هذا العرض', true); return; }
        gate.classList.remove('is-open');
        setStatus('');
        index = 0;
        render();
        showControls();
      })
      .catch(function(){ setStatus('تعذر تحميل العرض', true); });
  }
  document.getElementById('shareGateForm').addEventListener('submit', function(event){
    event.preventDefault();
    var password = document.getElementById('sharePassword').value;
    gateError.textContent = '';
    fetch(apiBase + '/unlock', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: password })
    }).then(function(response){
      return response.json().then(function(body){ return { status: response.status, body: body }; });
    }).then(function(result){
      if (result.status === 200 && result.body && result.body.success) { load(); return; }
      gateError.textContent = (result.body && result.body.error) || 'كلمة المرور غير صحيحة';
    }).catch(function(){ gateError.textContent = 'تعذر التحقق من كلمة المرور'; });
  });
  document.getElementById('sharePrev').addEventListener('click', function(){ step(-1); });
  document.getElementById('shareNext').addEventListener('click', function(){ step(1); });
  document.getElementById('shareFull').addEventListener('click', function(){
    if (document.fullscreenElement) { document.exitFullscreen(); return; }
    if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen();
  });
  document.addEventListener('keydown', function(event){
    if (event.target && (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA')) return;
    if (event.key === 'ArrowLeft' || event.key === ' ' || event.key === 'PageDown') { event.preventDefault(); step(1); }
    else if (event.key === 'ArrowRight' || event.key === 'PageUp') { event.preventDefault(); step(-1); }
    else if (event.key === 'Home') { index = 0; render(); }
    else if (event.key === 'End') { index = slides.length - 1; render(); }
  });
  document.addEventListener('mousemove', showControls);
  window.addEventListener('resize', fit);
  load();
})();
'''


@app.route('/s/shared-viewer.js', methods=['GET'])
def public_share_viewer_js():
    response = app.response_class(_SHARE_VIEWER_JS, mimetype='application/javascript')
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response


@app.route('/api/presentations/<pres_id>/shares', methods=['GET'])
@require_permission('create_presentation')
def api_list_presentation_shares(pres_id):
    presentation = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not presentation:
        return jsonify({'success': False, 'error': 'العرض غير موجود'}), 404
    shares = db.list_presentation_shares(g.tenant_id, pres_id)
    return jsonify({'success': True, 'shares': [_share_owner_payload(item) for item in shares]})


@app.route('/api/presentations/<pres_id>/shares', methods=['POST'])
@require_permission('create_presentation')
def api_create_presentation_share(pres_id):
    presentation = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not presentation:
        return jsonify({'success': False, 'error': 'العرض غير موجود'}), 404
    data = request.json or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'بيانات غير صالحة'}), 400
    expiry_key = str(data.get('expiresIn') or 'never').strip().lower()
    if expiry_key not in SHARE_EXPIRY_CHOICES:
        return jsonify({'success': False, 'error': 'مدة صلاحية غير معروفة',
                        'error_code': 'SHARE_EXPIRY_INVALID'}), 400
    password = str(data.get('password') or '')
    password_hash = auth.hash_password(password) if password else None
    days = SHARE_EXPIRY_CHOICES[expiry_key]
    expires_at = _share_iso(_share_now() + timedelta(days=days)) if days else None
    token = secrets.token_urlsafe(32)
    share = db.create_presentation_share(
        g.tenant_id, pres_id, token, password_hash=password_hash,
        expires_at=expires_at, created_by=g.user_id,
    )
    if not share:
        return jsonify({'success': False, 'error': 'تعذر إنشاء رابط المشاركة'}), 500
    return jsonify({'success': True, 'share': _share_owner_payload(share)}), 201


@app.route('/api/presentations/<pres_id>/shares/<share_id>/revoke', methods=['POST'])
@require_permission('create_presentation')
def api_revoke_presentation_share(pres_id, share_id):
    revoked = db.revoke_presentation_share(g.tenant_id, pres_id, share_id)
    if not revoked:
        return jsonify({'success': False, 'error': 'الرابط غير موجود أو ملغى مسبقًا'}), 404
    return jsonify({'success': True})


@app.route('/api/public/shares/<token>', methods=['GET'])
def api_public_share(token):
    share = _live_share(token)
    if not share:
        return _noindex(jsonify({'success': False, 'error': 'الرابط غير صالح أو منتهي الصلاحية',
                                 'error_code': 'SHARE_UNAVAILABLE'})), 404
    if not _share_unlocked(share):
        return _noindex(jsonify({'success': False, 'passwordRequired': True,
                                 'error': 'هذا العرض محمي بكلمة مرور',
                                 'error_code': 'SHARE_PASSWORD_REQUIRED'})), 401
    presentation, slides = _share_slides(share)
    if presentation is None:
        return _noindex(jsonify({'success': False, 'error': 'العرض غير موجود'})), 404
    public_slides = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        public_slides.append({
            'html': _rewrite_share_urls(slide.get('html') or '', token),
            'type': slide.get('type') or 'content',
        })
    db.touch_presentation_share(share.get('id'))
    return _noindex(jsonify({
        'success': True,
        'title': presentation.get('title') or '',
        'slides': public_slides,
    }))


@app.route('/api/public/shares/<token>/unlock', methods=['POST'])
def api_public_share_unlock(token):
    share = _live_share(token)
    if not share:
        return _noindex(jsonify({'success': False, 'error': 'الرابط غير صالح أو منتهي الصلاحية'})), 404
    if not share.get('password_hash'):
        return _noindex(jsonify({'success': True}))
    if not _share_password_allowed(share.get('id')):
        return _noindex(jsonify({'success': False, 'error': 'محاولات كثيرة — حاول بعد قليل'})), 429
    data = request.json or {}
    password = str(data.get('password') or '')
    if not password or not auth.verify_password(password, share.get('password_hash')):
        return _noindex(jsonify({'success': False, 'error': 'كلمة المرور غير صحيحة'})), 403
    response = _noindex(jsonify({'success': True}))
    response.set_cookie(
        _share_cookie_name(share.get('id')), _share_cookie_value(share.get('id')),
        max_age=12 * 3600, httponly=True, samesite='Lax', secure=request.is_secure,
    )
    return response


@app.route('/s/<token>/media', methods=['GET'])
def public_share_media(token):
    share = _live_share(token)
    if not share:
        return jsonify({'error': 'Not found'}), 404
    if not _share_unlocked(share):
        return jsonify({'error': 'Not found'}), 404
    src = str(request.args.get('src') or '')
    path = urlsplit(src).path
    if path not in _share_allowed_media_urls(share):
        return jsonify({'error': 'Not found'}), 404
    tenant_id = str(share.get('tenant_id') or '')
    if path.startswith('/api/project-files/'):
        file_id = path.rsplit('/', 1)[-1]
        stored = db.get_project_file(tenant_id, file_id)
        if not stored or not stored.get('storage_path'):
            return jsonify({'error': 'Not found'}), 404
        try:
            return _send_project_file_response(stored, tenant_id)
        except NameError:
            return jsonify({'error': 'Not found'}), 404
    rel = path[len('/uploads/'):]
    target = os.path.realpath(os.path.join(UPLOADS_DIR, rel))
    allowed_roots = [
        os.path.realpath(os.path.join(UPLOADS_DIR, 'maps')),
        os.path.realpath(os.path.join(UPLOADS_DIR, 'creative', tenant_id)),
        os.path.realpath(os.path.join(UPLOADS_DIR, tenant_id)),
    ]
    inside = False
    for root in allowed_roots:
        try:
            inside = inside or os.path.commonpath([root, target]) == root
        except ValueError:
            continue
    if not inside or not os.path.isfile(target):
        return jsonify({'error': 'Not found'}), 404
    from flask import send_file
    return send_file(target, conditional=True, max_age=3600)


@app.route('/s/<token>', methods=['GET'])
def public_share_viewer(token):
    share = _live_share(token)
    if not share:
        return _noindex(app.response_class(
            '<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
            '<meta name="robots" content="noindex, nofollow"><title>عرض تقديمي</title></head>'
            '<body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;'
            'background:#050B14;color:#fff;font-family:Tahoma,Arial,sans-serif;font-size:16px">'
            'الرابط غير صالح أو منتهي الصلاحية</body></html>',
            mimetype='text/html')), 404
    html = _share_page_html(token)
    html = html.replace('<style>__SHARE_FONT_CSS__</style>',
                        '<style>' + _share_font_css(share.get('tenant_id')) + '</style>')
    return _noindex(app.response_class(html, mimetype='text/html'))
