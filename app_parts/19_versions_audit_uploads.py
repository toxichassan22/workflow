

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PRESENTATION VERSIONS & EDIT LOG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _presentation_version_payload(version, include_snapshot=False):
    item = dict(version)
    legacy = bool(item.get('legacy')) or item.get('snapshot_kind') == 'legacy-slides'
    item['snapshotKind'] = 'legacy-slides' if legacy else 'full'
    item['label'] = 'نسخة قديمة: الشرائح فقط' if legacy else f'مراجعة {item.get("revision", 0)}'
    if include_snapshot:
        state = _presentation_state(item)
        # ISS-015: a version snapshot is draft data of its moment — hidden
        # sections stay server-side for this caller.
        state['projectData'] = _draft_data_for_response(state.get('projectData'))
        item['snapshot'] = {key: state.get(key) for key in
                            ('title', 'projectData', 'slidesData', 'slideCount', 'draftId', 'status')}
        if legacy:
            item['snapshot'] = {key: item['snapshot'][key] for key in ('slidesData', 'slideCount')}
    item.pop('slides_data', None)
    item.pop('project_data', None)
    return item


@app.route('/api/presentations/<pres_id>/versions', methods=['GET'])
@require_permission('view_presentations')
def api_get_versions(pres_id):
    """Immutable revisions and explicitly labelled slides-only legacy backups."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'Presentation not found'}), 404
    versions = db.get_presentation_revisions(pres_id, g.tenant_id)
    return jsonify({'success': True, 'currentRevision': int(pres.get('revision') or 0),
                    'versions': [_presentation_version_payload(v) for v in versions]})


@app.route('/api/presentations/<pres_id>/versions/<version_id>', methods=['GET'])
@require_permission('view_presentations')
def api_get_version(pres_id, version_id):
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'Presentation not found'}), 404
    version = db.get_presentation_revision(pres_id, version_id, g.tenant_id)
    if not version:
        return jsonify({'error': 'Version not found'}), 404
    return jsonify({'success': True, 'version': _presentation_version_payload(version, True)})


@app.route('/api/presentations/<pres_id>/versions/compare', methods=['GET'])
@require_permission('view_presentations')
def api_compare_versions(pres_id):
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'Presentation not found'}), 404
    before = db.get_presentation_revision(pres_id, request.args.get('from', ''), g.tenant_id)
    to_id = request.args.get('to') or 'current'
    after = pres if to_id == 'current' else db.get_presentation_revision(pres_id, to_id, g.tenant_id)
    if not before or not after:
        return jsonify({'error': 'Version not found'}), 404
    old, new = _presentation_state(before), _presentation_state(after)
    # ISS-015: hidden sections must not surface in the diff narrative either.
    old['projectData'] = _draft_data_for_response(old.get('projectData'))
    new['projectData'] = _draft_data_for_response(new.get('projectData'))
    changes = change_tracking.describe_slide_changes(old['slidesData'], new['slidesData'])
    if not before.get('legacy') and not after.get('legacy'):
        if old.get('title') != new.get('title'):
            changes.insert(0, f'عنوان العرض: من «{old.get("title") or ""}» إلى «{new.get("title") or ""}»')
        changes.extend(change_tracking.detail_text(item)
                       for item in change_tracking.describe_draft_changes(
                           old['projectData'], new['projectData'],
                           id_names=_draft_change_id_names()))
        if old.get('status') != new.get('status'):
            changes.append(f'حالة العرض: من «{old.get("status") or ""}» إلى «{new.get("status") or ""}»')
    return jsonify({'success': True, 'from': _presentation_version_payload(before, True),
                    'to': _presentation_version_payload(after, True), 'changes': changes})


@app.route('/api/presentations/<pres_id>/versions/<version_id>/restore', methods=['POST'])
@require_permission('create_presentation')
def api_restore_version(pres_id, version_id):
    """Restore creates a new revision of this card, not a rewrite of its source draft."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'Presentation not found'}), 404
    version = db.get_presentation_revision(pres_id, version_id, g.tenant_id)
    if not version:
        return jsonify({'error': 'Version not found'}), 404
    data = request.json or {}
    # ISS-026: restoring rewrites the same state a PUT writes, so the same
    # gates stand — a locked draft refuses it, and an approved file needs the
    # post-approval permission plus a written reason.
    locked_status = _presentation_draft_lock(pres.get('draft_id'), data, presentation_id=pres_id)
    if locked_status:
        return _draft_locked_response(locked_status)
    restore_reason = ''
    if pres.get('status') == 'approved':
        if not _omran_can('post_approval_edit'):
            return jsonify({'error': 'استرجاع ملف معتمد يتطلب صلاحية التعديل بعد الاعتماد',
                            'error_code': 'post_approval_edit_required'}), 403
        restore_reason = str(data.get('editReason') or '').strip()
        if not restore_reason:
            return jsonify({'error': 'سبب الاسترجاع بعد الاعتماد إلزامي',
                            'error_code': 'reason_required'}), 400
    try:
        expected_revision = _expected_presentation_revision(data, pres)
        result = _commit_presentation_state(
            g.tenant_id, pres_id, expected_revision=expected_revision,
            restore_version_id=version_id, action='استرجاع نسخة', source='manual',
            details=[_presentation_version_payload(version)['label']]
                    + ([f'استرجاع بعد الاعتماد — السبب: {restore_reason}'] if restore_reason else []),
        )
    except (LookupError, ValueError) as error:
        return jsonify({'error': str(error)}), 400
    payload = _presentation_revision_response(result)
    payload['slidesData'] = payload['presentation']['slidesData']
    return jsonify(payload)


@app.route('/api/presentations/<pres_id>/edit-log', methods=['GET'])
@require_permission('view_presentations')
def api_get_edit_log(pres_id):
    """Get edit history for a presentation: who changed what, by hand or by the AI."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'Presentation not found'}), 404
    return jsonify({'success': True, 'log': db.get_change_log(g.tenant_id, 'presentation', pres_id)})


@app.route('/api/project-draft/<draft_id>/edit-log', methods=['GET'])
@require_auth
def api_get_draft_edit_log(draft_id):
    """Edit history for one project file. Drafts had no history at all before."""
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if not draft or not db.user_may_access_draft(g.user_id, draft):
        return jsonify({'error': 'Draft not found'}), 404
    return jsonify({'success': True, 'log': db.get_change_log(g.tenant_id, 'draft', draft_id),
                    'title': draft.get('title') or ''})


@app.route('/api/presentations/<pres_id>/log', methods=['POST'])
@require_permission('create_presentation')
def api_log_presentation_edit(pres_id):
    """Record a single edit log entry (used by inline text editing)."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'Presentation not found'}), 404
    data = request.json or {}
    action = data.get('action', 'edit')
    details = data.get('details', '')
    lines = details if isinstance(details, list) else [details]
    _record_change('presentation', pres_id, action, lines, source='manual')
    return jsonify({'success': True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLATFORM AUDIT LOG (AuditEvent) - Immutable unified audit ledger
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/audit-log', methods=['GET'])
@require_permission('audit_log')
def api_list_audit_log():
    """Query immutable audit events with filtering and pagination."""
    entity_type = request.args.get('entityType') or request.args.get('entity_type') or None
    entity_id = request.args.get('entityId') or request.args.get('entity_id') or None
    action = request.args.get('action') or None
    user_id = request.args.get('userId') or request.args.get('user_id') or None
    from_date = request.args.get('fromDate') or request.args.get('from_date') or None
    to_date = request.args.get('toDate') or request.args.get('to_date') or None
    limit = request.args.get('limit', 50)
    offset = request.args.get('offset', 0)

    result = db.list_audit_events(
        tenant_id=g.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        user_id=user_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    return jsonify({'success': True, **result})


@app.route('/api/audit-log/<event_id>', methods=['GET'])
@require_permission('audit_log')
def api_get_audit_event(event_id):
    """Fetch a single immutable audit event."""
    event = db.get_audit_event(g.tenant_id, event_id)
    if not event:
        return jsonify({'error': 'Audit event not found'}), 404
    return jsonify({'success': True, 'event': event})


@app.route('/api/audit-log/export', methods=['GET'])
@require_permission('audit_log')
def api_export_audit_log():
    """Export corporate audit events report as UTF-8 CSV with BOM."""
    entity_type = request.args.get('entityType') or request.args.get('entity_type') or None
    entity_id = request.args.get('entityId') or request.args.get('entity_id') or None
    action = request.args.get('action') or None
    user_id = request.args.get('userId') or request.args.get('user_id') or None
    from_date = request.args.get('fromDate') or request.args.get('from_date') or None
    to_date = request.args.get('toDate') or request.args.get('to_date') or None

    csv_data = db.export_audit_events_csv(
        tenant_id=g.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        user_id=user_id,
        from_date=from_date,
        to_date=to_date,
    )
    return Response(
        csv_data,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=audit-log.csv'}
    )


@app.route('/api/audit-log', methods=['POST', 'PUT', 'PATCH', 'DELETE'])
@app.route('/api/audit-log/<path:sub>', methods=['POST', 'PUT', 'PATCH', 'DELETE'])
def api_audit_log_immutable(sub=None):
    """Refuse any modification or deletion of immutable audit events."""
    return jsonify({
        'error': 'Audit log is strictly immutable and cannot be modified or deleted',
        'error_code': 'AUDIT_LOG_IMMUTABLE'
    }), 405


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FILE UPLOAD ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

UPLOADS_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
# Watermark is a small branding silhouette, not a photo: cap bytes and pixels so a
# huge upload cannot exhaust disk or memory. The saved file keeps its own bytes,
# so a PNG alpha channel is preserved as uploaded.
TENANT_WATERMARK_MAX_BYTES = 5 * 1024 * 1024
TENANT_WATERMARK_MAX_DIMENSION = 4000


def _save_tenant_image(uploaded_file, base_name):
    from PIL import Image, UnidentifiedImageError

    # The stored filename is always <base_name><extension>; the client filename
    # only supplies the extension. A client-sent path can never choose where
    # the file lands, and SVG is rejected here by the extension allow-list.
    extension = os.path.splitext(uploaded_file.filename or '')[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError('Only PNG, JPG, JPEG, and WEBP images are supported')
    try:
        uploaded_file.stream.seek(0)
        raw_bytes = uploaded_file.stream.read()
        uploaded_file.stream.seek(0)
    except (OSError, ValueError):
        raise ValueError('Invalid image file')
    if base_name == 'watermark' and len(raw_bytes) > TENANT_WATERMARK_MAX_BYTES:
        raise ValueError('Image exceeds the 5MB watermark limit')
    try:
        image = Image.open(BytesIO(raw_bytes))
        actual_format = str(image.format or '').upper()
        image.load()
        width, height = image.size
    except (UnidentifiedImageError, OSError):
        raise ValueError('Invalid image file')
    if actual_format not in ('PNG', 'JPEG', 'JPG', 'WEBP'):
        raise ValueError('Invalid image file')
    if base_name == 'watermark' and max(width, height) > TENANT_WATERMARK_MAX_DIMENSION:
        raise ValueError('Image dimensions exceed the 4000px watermark limit')
    try:
        uploaded_file.stream.seek(0)
    except (OSError, ValueError):
        pass

    tenant_dir = os.path.join(UPLOADS_DIR, g.tenant_id)
    os.makedirs(tenant_dir, exist_ok=True)
    normalized_extension = '.jpg' if extension == '.jpeg' else extension
    file_path = os.path.join(tenant_dir, f'{base_name}{normalized_extension}')
    uploaded_file.save(file_path)
    # The public branding URLs omit the extension. Keep exactly one current
    # source file so changing PNG to WEBP cannot serve an older sibling.
    target_path = os.path.realpath(file_path)
    for stale_path in _tenant_image_storage_candidates(g.tenant_id, base_name):
        if os.path.realpath(stale_path) == target_path or not os.path.isfile(stale_path):
            continue
        try:
            os.unlink(stale_path)
        except OSError as error:
            print(f'[TENANT IMAGE] could not remove stale {base_name} file: {error}')
    return file_path, normalized_extension


PROJECT_FILE_EXTENSIONS = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.webp': 'image/webp', '.pdf': 'application/pdf'
}
PROJECT_FILE_TYPES = {'land_document', 'land_image', 'croquis', 'building_license',
                      'regulation_reference', 'team_logo', 'competitor_logo', 'visual_reference',
                      'conceptual_plan', 'project_logo', 'recharge_receipt'}
# Types that must be real images: they are rendered in <img> thumbnails, where a PDF shows nothing.
PROJECT_IMAGE_ONLY_TYPES = {'land_image', 'team_logo', 'competitor_logo', 'visual_reference', 'project_logo'}
PROJECT_FILE_MAX_BYTES = 30 * 1024 * 1024
# d10: the upload `fileType` resolves to a file_type_registry rule; where a rule
# exists it governs the accepted extensions and the size ceiling, and the
# tenant's active package can tighten the ceiling further via limits_json.
_UPLOAD_TYPE_REGISTRY_KEY = {
    'land_document': 'deed_file',
    'croquis': 'croquis_file',
    'building_license': 'land_documents_files',
    'regulation_reference': 'land_documents_files',
    'land_image': 'land_photos',
    'conceptual_plan': 'land_documents_files',
    'team_logo': 'team_logo',
    'competitor_logo': 'competitor_logo',
    'visual_reference': 'land_photos',
    'project_logo': 'project_logo',
    'recharge_receipt': 'recharge_receipt',
}


def _upload_file_rule(file_type):
    """Effective upload rule for a file type: registry row plus the tenant's
    package limit when one is set. Returns (allowed_extensions, max_bytes)."""
    registry_key = _UPLOAD_TYPE_REGISTRY_KEY.get(file_type)
    allowed_exts = None
    max_bytes = PROJECT_FILE_MAX_BYTES
    rule = None
    if registry_key:
        try:
            rule = db.get_file_type_rule(registry_key)
        except Exception:
            rule = None
    if rule:
        exts = rule.get('allowed_extensions') or []
        if isinstance(exts, list) and exts:
            allowed_exts = {str(e).lower() for e in exts}
        try:
            rule_mb = float(rule.get('max_size_mb') or 0)
        except (TypeError, ValueError):
            rule_mb = 0
        if rule_mb > 0:
            max_bytes = min(max_bytes, int(rule_mb * 1024 * 1024))
    package_limit_mb = 0
    try:
        limits = db.current_package_limits(g.tenant_id)
        package_limit_mb = float((limits or {}).get('max_file_mb') or 0)
    except Exception:
        package_limit_mb = 0
    if package_limit_mb > 0:
        max_bytes = min(max_bytes, int(package_limit_mb * 1024 * 1024))
    return allowed_exts, max_bytes
COMPETITOR_LOGO_MAX_BYTES = 2 * 1024 * 1024
COMPETITOR_LOGO_MIMES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
OFFICIAL_LOGO_PAGE_MAX_BYTES = 2 * 1024 * 1024


def _public_host_addresses(host):
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except (OSError, socket.gaierror):
        return ()
    verified = []
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return ()
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified):
            return ()
        verified.append(address)
    return tuple(sorted(verified))


def _safe_public_host(host):
    return bool(_public_host_addresses(host))


def _open_pinned_https(parsed, addresses):
    host = str(parsed.hostname).encode('idna').decode('ascii')
    path = parsed.path or '/'
    if parsed.query:
        path += '?' + parsed.query
    pool = HTTPSConnectionPool(
        addresses[0], port=443, assert_hostname=host, server_hostname=host,
        cert_reqs='CERT_REQUIRED', ca_certs=requests.certs.where(),
    )
    response = pool.urlopen(
        'GET', path, headers={'Host': host, 'User-Agent': 'Mozilla/5.0'},
        redirect=False, preload_content=False, retries=False,
        timeout=Timeout(connect=7, read=20),
    )
    return pool, response


_OFFICIAL_CDN_PREFIXES = {'cdn', 'images', 'image', 'img', 'static', 'assets', 'media', 'files'}
_TWO_LEVEL_PUBLIC_SUFFIXES = {'co.uk', 'com.sa', 'net.sa', 'org.sa', 'com.ae', 'co.za', 'com.eg'}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_OFFICIAL_FETCH_MAX_REDIRECTS = 3


def _normalized_web_host(url):
    return (urlsplit(str(url or '')).hostname or '').lower().removeprefix('www.')


def _registrable_host(host):
    parts = str(host or '').split('.')
    if len(parts) < 2:
        return str(host or '')
    suffix = '.'.join(parts[-2:])
    return '.'.join(parts[-3:]) if suffix in _TWO_LEVEL_PUBLIC_SUFFIXES and len(parts) >= 3 else suffix


def _redirect_within_site(origin_url, target_url):
    # Redirects may move inside the same registrable site — www shuffles,
    # locale prefixes, CDN subdomains. A hand-off to another registrable
    # domain is an open-redirect hop we refuse to follow.
    origin = _normalized_web_host(origin_url)
    target = _normalized_web_host(target_url)
    return bool(origin and target
                and _registrable_host(origin) == _registrable_host(target))


def _pinned_https_get(url, redirects_left=_OFFICIAL_FETCH_MAX_REDIRECTS, origin_url=None):
    """GET an HTTPS URL through the DNS-pinned pool, following redirects that
    stay inside the original site's registrable host. Returns
    (pool, response, final_url) — the caller owns pool/response cleanup — or
    (None, None, error_key_or_text) on validation/transport failure."""
    parsed = urlsplit(str(url or '').strip())
    try:
        invalid_port = parsed.port not in (None, 443)
    except ValueError:
        invalid_port = True
    if (parsed.scheme.lower() != 'https' or not parsed.hostname
            or parsed.username or invalid_port):
        return None, None, 'invalid_url'
    if origin_url and not _redirect_within_site(origin_url, url):
        return None, None, 'off_site_redirect'
    addresses = _public_host_addresses(parsed.hostname)
    if not addresses:
        return None, None, 'blocked_host'
    try:
        pool, response = _open_pinned_https(parsed, addresses)
    except Exception as exc:
        return None, None, str(exc)
    location = str((response.headers or {}).get('Location') or '').strip()
    if response.status in _REDIRECT_STATUSES and location:
        response.release_conn()
        pool.close()
        if redirects_left <= 0:
            return None, None, 'too_many_redirects'
        return _pinned_https_get(urljoin(url, location), redirects_left - 1,
                                 origin_url or url)
    return pool, response, url


def _official_fetch_error(kind):
    return {
        'invalid_url': 'صفحة الموقع الرسمي غير صالحة',
        'blocked_host': 'عنوان الموقع الرسمي غير مسموح',
        'off_site_redirect': 'تحويل الموقع الرسمي إلى نطاق مختلف',
        'too_many_redirects': 'تعذر قراءة صفحة الموقع الرسمي: تحويلات كثيرة',
    }.get(kind) or str(kind)


def _related_official_hosts(first_url, second_url):
    first = _normalized_web_host(first_url)
    second = _normalized_web_host(second_url)
    return bool(first and second and (
        first == second or first.endswith('.' + second) or second.endswith('.' + first)
    ))


def _same_official_host(logo_url, official_url):
    logo_host = _normalized_web_host(logo_url)
    official_host = _normalized_web_host(official_url)
    if not logo_host or not official_host:
        return False
    if logo_host == official_host or logo_host.endswith('.' + official_host):
        return True
    logo_parts = logo_host.split('.')
    return bool(len(logo_parts) >= 3 and logo_parts[0] in _OFFICIAL_CDN_PREFIXES
                and _registrable_host(logo_host) == _registrable_host(official_host))


class _OfficialLogoHTMLParser(HTMLParser):
    """Collect logo hints exposed by a company's own page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.candidates = []
        self._json_ld_depth = 0
        self._json_ld_parts = []

    def _add(self, value, priority):
        value = html_lib.unescape(str(value or '')).strip()
        if value:
            self.candidates.append((priority, value))

    def handle_starttag(self, tag, attrs):
        attributes = {str(key).lower(): str(value or '').strip() for key, value in attrs}
        tag_name = str(tag or '').lower()
        if tag_name == 'meta':
            identity = (attributes.get('property') or attributes.get('name')
                        or attributes.get('itemprop') or '').lower()
            if identity in {'og:image', 'og:image:url', 'twitter:image', 'twitter:image:src'}:
                self._add(attributes.get('content'), 3)
            elif identity == 'logo':
                self._add(attributes.get('content'), 1)
        elif tag_name == 'link':
            rel = set(re.findall(r'[a-z0-9_-]+', attributes.get('rel', '').lower()))
            if rel.intersection({'icon', 'shortcut', 'apple-touch-icon', 'logo'}):
                self._add(attributes.get('href'), 1)
        elif tag_name == 'img':
            hint = ' '.join(attributes.get(key, '') for key in ('alt', 'class', 'id', 'src')).lower()
            if any(token in hint for token in ('logo', 'brand', 'شعار')):
                image_src = attributes.get('src') or attributes.get('data-src') or attributes.get('data-lazy-src')
                if image_src.lower().startswith('data:'):
                    image_src = attributes.get('data-src') or attributes.get('data-lazy-src')
                self._add(image_src, 1)
        elif tag_name == 'script' and attributes.get('type', '').lower() == 'application/ld+json':
            self._json_ld_depth = 1
            self._json_ld_parts = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self._json_ld_depth:
            self._json_ld_parts.append(data)

    def handle_endtag(self, tag):
        if str(tag or '').lower() != 'script' or not self._json_ld_depth:
            return
        try:
            payload = json.loads(''.join(self._json_ld_parts))
        except (TypeError, ValueError):
            payload = None

        def collect(value):
            if isinstance(value, dict):
                logo = value.get('logo')
                if isinstance(logo, str):
                    self._add(logo, 0)
                elif isinstance(logo, dict):
                    self._add(logo.get('url') or logo.get('contentUrl'), 0)
                for key, item in value.items():
                    if key != 'logo' and isinstance(item, (dict, list)):
                        collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(payload)
        self._json_ld_depth = 0
        self._json_ld_parts = []


def _safe_read_official_logo_page(official_url):
    """(page_html, final_url, error) — redirects inside the same registrable
    site are followed; final_url is the page actually read so relative logo
    paths resolve against it."""
    pool, response, outcome = _pinned_https_get(official_url)
    if pool is None:
        return '', '', _official_fetch_error(outcome)
    try:
        if response.status != 200:
            return '', '', f'تعذر قراءة صفحة الموقع الرسمي: HTTP {response.status}'
        content = bytearray()
        for chunk in response.stream(64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > OFFICIAL_LOGO_PAGE_MAX_BYTES:
                return '', '', 'صفحة الموقع الرسمي أكبر من الحد المسموح'
        return bytes(content).decode('utf-8', errors='replace'), outcome, ''
    finally:
        response.release_conn()
        pool.close()


def _official_logo_candidates(official_url):
    """(candidates, error) — the error explains why nothing was extractable so the
    row warning can say so instead of a generic failure."""
    page, final_url, page_error = _safe_read_official_logo_page(official_url)
    if not page:
        return [], page_error or 'تعذر قراءة صفحة الموقع الرسمي'
    base_url = final_url or official_url
    parser = _OfficialLogoHTMLParser()
    try:
        parser.feed(page)
        parser.close()
    except Exception:
        return [], 'تعذر تحليل صفحة الموقع الرسمي'
    candidates = []
    seen = set()
    for _priority, raw_url in sorted(parser.candidates, key=lambda item: item[0]):
        candidate = urljoin(base_url, raw_url)
        parsed = urlsplit(candidate)
        if (parsed.scheme.lower() != 'https' or not parsed.hostname or parsed.username
                or not _same_official_host(candidate, base_url)):
            continue
        # Ad-license stamps (رواج / REGA) ship inside listing pages as images on
        # the same host — never a competitor's own logo.
        lowered = candidate.casefold()
        if any(token in lowered for token in ('ruwaj', 'rawaj', 'rowaj', '/rwaj', 'rega')):
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates, '' if candidates else 'لا توجد صورة شعار على الصفحة الرسمية'


def _safe_download_competitor_logo(logo_url, official_url):
    parsed = urlsplit(str(logo_url or '').strip())
    official = urlsplit(str(official_url or '').strip())
    try:
        invalid_port = parsed.port not in (None, 443) or official.port not in (None, 443)
    except ValueError:
        invalid_port = True
    if (parsed.scheme.lower() != 'https' or official.scheme.lower() != 'https'
            or not parsed.hostname or not official.hostname or parsed.username or official.username
            or invalid_port):
        return None, None, None, 'رابط الشعار الرسمي غير صالح'
    if not _same_official_host(logo_url, official_url):
        return None, None, None, 'شعار المنافس خارج الموقع الرسمي'
    if any(token in str(logo_url).casefold() for token in ('ruwaj', 'rawaj', 'rowaj', '/rwaj', 'rega')):
        return None, None, None, 'شعار منصة إعلانات وليس شعار المنافس'
    if not _public_host_addresses(official.hostname):
        return None, None, None, 'عنوان موقع الشعار غير مسموح'
    pool, response, outcome = _pinned_https_get(logo_url)
    if pool is None:
        if outcome == 'off_site_redirect':
            return None, None, None, 'تحويل الشعار إلى نطاق مختلف'
        if outcome in ('invalid_url', 'blocked_host'):
            return None, None, None, 'عنوان موقع الشعار غير مسموح'
        if outcome == 'too_many_redirects':
            return None, None, None, 'تعذر تنزيل الشعار: تحويلات كثيرة'
        return None, None, None, str(outcome)
    try:
        if response.status != 200:
            return None, None, None, f'تعذر تنزيل الشعار: HTTP {response.status}'
        mime_type = str(response.headers.get('Content-Type') or '').split(';', 1)[0].strip().lower()
        extension = COMPETITOR_LOGO_MIMES.get(mime_type)
        try:
            declared = int(response.headers.get('Content-Length') or 0)
        except (TypeError, ValueError):
            declared = 0
        if declared > COMPETITOR_LOGO_MAX_BYTES:
            return None, None, None, 'حجم شعار المنافس أكبر من الحد المسموح'
        content = bytearray()
        for chunk in response.stream(64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > COMPETITOR_LOGO_MAX_BYTES:
                return None, None, None, 'حجم شعار المنافس أكبر من الحد المسموح'
        try:
            from PIL import Image, UnidentifiedImageError
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > 16_000_000:
                    return None, None, None, 'أبعاد شعار المنافس غير صالحة'
                detected = {'PNG': ('image/png', '.png'), 'JPEG': ('image/jpeg', '.jpg'), 'WEBP': ('image/webp', '.webp')}.get((image.format or '').upper())
                if not detected:
                    # Any other PIL-readable raster (GIF, AVIF, BMP…) is a real
                    # image — re-encode it to PNG instead of rejecting it.
                    buffer = BytesIO()
                    image.convert('RGBA').save(buffer, 'PNG')
                    content = bytearray(buffer.getvalue())
                    detected = ('image/png', '.png')
                else:
                    image.verify()
                mime_type, extension = detected
        except (UnidentifiedImageError, OSError):
            return None, None, None, 'ملف شعار المنافس غير صالح'
        return bytes(content), mime_type, extension, ''
    finally:
        response.release_conn()
        pool.close()


def _download_official_favicon(official_url):
    """Last-resort logo: Google's favicon service returns the icon the official
    site itself publishes — reachable even when the site blocks direct reads
    (Cloudflare 403/timeouts). Only used once the domain is already verified
    as the competitor's official page."""
    host = _normalized_web_host(official_url)
    if not host:
        return None, None, None, ''
    # The s2 endpoint 301-redirects to gstatic faviconV2 — call it directly;
    # same-site redirects are followed by the pinned fetch anyway.
    favicon_url = ('https://t2.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON'
                   f'&fallback_opts=TYPE,SIZE,URL&url=http://{host}&size=128')
    pool, response, _outcome = _pinned_https_get(favicon_url)
    if pool is None:
        return None, None, None, ''
    try:
        if response.status != 200:
            return None, None, None, ''
        content = bytes(b''.join(response.stream(64 * 1024)))
        if not content or len(content) > COMPETITOR_LOGO_MAX_BYTES:
            return None, None, None, ''
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(BytesIO(content)) as image:
                if image.size[0] <= 0 or image.size[1] <= 0:
                    return None, None, None, ''
                mime_type, extension = {'PNG': ('image/png', '.png'), 'JPEG': ('image/jpeg', '.jpg'),
                                        'WEBP': ('image/webp', '.webp')}.get(
                                            (image.format or '').upper(), ('', ''))
                if not extension:
                    buffer = BytesIO()
                    image.convert('RGBA').save(buffer, 'PNG')
                    content = buffer.getvalue()
                    mime_type, extension = 'image/png', '.png'
                else:
                    image.verify()
        except (UnidentifiedImageError, OSError):
            return None, None, None, ''
        return content, mime_type, extension, ''
    finally:
        response.release_conn()
        pool.close()


# Aggregator/index hosts list a competitor but are never its official site —
# their og:image is the portal's own logo, so they are excluded from the
# citation-based official-page match.
_AGGREGATOR_HOST_TOKENS = (
    'sakani.', 'ejar.', 'rega.gov', 'ruwaj', 'rawaj', 'rowaj',
    'aqar.', 'aqaar.', 'aqarmap', 'wasalt.', 'bayut.',
    'dubizzle', 'propertyfinder', 'opensooq', 'haraj', 'lamudi', 'exxl',
    'estater', 'muqawil', 'dealmap', 'eqqar',
    'wikipedia', 'twitter.', 'x.com', 'facebook.', 'instagram.', 'linkedin.',
    'youtube.', 'tiktok.', 'google.', 'bing.', 'maps.',
)

# Same-name projects in other Arab markets are a constant trap: «أورا» matched
# Dubai pages and would have imported a dirham price and an off-country logo.
# Saudi competitors never live on these hosts.
_FOREIGN_ARAB_TLDS = (
    '.ae', '.eg', '.qa', '.kw', '.bh', '.om', '.jo', '.lb',
    '.ma', '.tn', '.dz', '.ly', '.iq', '.sd', '.sy', '.ps',
)
_FOREIGN_ARAB_HOST_TOKENS = (
    'dubai', 'abudhabi', 'sharjah', 'uae', 'egypt', 'cairo',
    'qatar', 'kuwait', 'bahrain', 'oman', 'jordan', 'morocco',
)


def _foreign_market_host(url):
    """True when a URL points at another Arab market, not Saudi."""
    host = _normalized_web_host(url)
    if not host:
        return False
    if host.endswith(_FOREIGN_ARAB_TLDS) or any(
            token in host for token in _FOREIGN_ARAB_HOST_TOKENS):
        return True
    # Namesakes abroad also hide in the path of generic .com portals
    # (aigentsrealty.com/.../dubai-silicon-oasis/...) — a Saudi competitor's
    # evidence never lives on a /dubai-/ style page.
    path = urlsplit(str(url)).path.lower()
    return any(
        re.search(r'(?:^|[^a-z0-9])' + re.escape(token) + r'(?:[^a-z0-9]|$)', path)
        for token in _FOREIGN_ARAB_HOST_TOKENS)


def _drop_foreign_competitor_urls(row):
    """Remove same-name foreign-market pages from a Saudi competitor row."""
    if not isinstance(row, dict):
        return row
    urls = market_study.competitor_source_urls(row)
    kept = [url for url in urls if not _foreign_market_host(url)]
    if len(kept) != len(urls):
        row['source_urls'] = kept
        if not kept:
            row.pop('source_urls', None)
    field_sources = market_study.competitor_field_sources(row)
    if field_sources:
        cleaned = {
            field: [url for url in urls if not _foreign_market_host(url)]
            for field, urls in field_sources.items()
        }
        row['field_sources'] = {field: urls for field, urls in cleaned.items() if urls}
        if not row['field_sources']:
            row.pop('field_sources', None)
    if _foreign_market_host(row.get('source_url')):
        row.pop('source_url', None)
    return row


def _official_citation_pages(pages, name):
    """Citation pages that look like the competitor's own site.

    A page that merely *mentions* the project is not its official page — a
    district article on a developer's site would otherwise hand that
    developer's favicon to an unrelated competitor. The page must carry ALL
    distinctive name tokens and live on a non-aggregator host.
    """
    tokens = _competitor_name_tokens(name)
    if not tokens:
        return []
    needed = len(tokens)
    matches = []
    for page in pages or []:
        url = str(page.get('url') or '').strip()
        host = _normalized_web_host(url)
        if (not host or any(token in host for token in _AGGREGATOR_HOST_TOKENS)
                or _foreign_market_host(url)):
            continue
        haystack = market_study._fold_choice(f"{page.get('title') or ''} {url}")
        if sum(1 for token in tokens if token in haystack) >= needed:
            matches.append(url)
    return matches


def _auto_import_competitor_logos(rows, payload, data, tenant_id=None, progress=None,
                                  citation_pages=None):
    """Import official logos during competitor generation — no per-row button needed.

    Pass 1 is free: rows whose source_url already verifies as the official site go
    straight to HTML extraction. Pass 1.5 is free too: citation pages the main
    search already retrieved are matched to each competitor's name and treated as
    its official page. Pass 2 runs ONE extra search call to discover the official
    site + logo for whatever remains, then extracts/downloads per row.
    """
    report = progress if callable(progress) else (lambda *_args: None)
    draft_id = payload.get('draftId') or payload.get('draft_id')
    missing = []
    total = max(1, len(rows))
    for index, row in enumerate(rows):
        if row.get('logo_file_id') or row.get('logo_path'):
            continue
        dead_keys = {str(item).strip().casefold() for item in (row.get('dead_source_urls') or [])}
        official_url = str(row.get('logo_source_url') or row.get('source_url') or '').strip()
        if official_url.strip().casefold() in dead_keys:
            official_url = ''
        verified = bool(official_url and (
            row.get('logo_official_verified')
            or market_study.official_source_reliability(
                row.get('name'), row.get('source'), official_url)))
        if not verified:
            for page_url in _official_citation_pages(citation_pages, row.get('name')):
                if page_url.casefold() in dead_keys:
                    continue
                official_url = page_url
                row['logo_source_url'] = page_url
                row['logo_official_verified'] = True
                field_sources = market_study.competitor_field_sources(row)
                urls = field_sources.setdefault('logo_url', [])
                if page_url not in urls:
                    urls.append(page_url)
                row['field_sources'] = field_sources
                row['source_urls'] = list(dict.fromkeys(
                    market_study.competitor_source_urls(row) + [page_url]))
                verified = True
                break
        if verified:
            report(74 + int(8 * index / total),
                   f'استخراج شعار «{row.get("name") or "منافس"}» من موقعه الرسمي...')
            try:
                _store_imported_competitor_logo(row, draft_id=draft_id)
            except Exception as exc:
                row['logo_import_warning'] = str(exc)
        if not row.get('logo_file_id') and not row.get('logo_path'):
            if row.get('no_search_evidence'):
                # No retrieved page even names this competitor — paying a
                # discovery call for a likely-fabricated name is wasted spend.
                row.setdefault('logo_import_warning', 'اسم المنافس غير موثق — لا يوجد موقع رسمي لاستيراد الشعار')
            else:
                missing.append(row)
    if not missing:
        return
    batch = missing[:8]
    report(82, 'البحث عن المواقع الرسمية وشعارات المنافسين المتبقية...')
    listing = json.dumps(
        [{'id': str(row.get('id') or ''), 'name': str(row.get('name') or '')} for row in batch],
        ensure_ascii=False)
    city = str(payload.get('city') or '').strip() or 'غير محددة'
    prompt = (
        f'ابحث عن الموقع الرسمي والشعار لكل مشروع منافس في القائمة التالية (المدينة: {city}):\n'
        f'{listing}\n'
        'نفّذ بحثًا منفصلًا لكل مشروع. أرجع JSON فقط بالشكل {"results": [...]} ولكل نتيجة: '
        '"id" كما وصلك، "official_url" صفحة HTTPS من الموقع الرسمي للمشروع أو مطوّره، '
        '"logo_url" رابط HTTPS مباشر لصورة PNG أو JPG أو WEBP على النطاق الرسمي أو نطاق الصور التابع له، '
        '"logo_source_url" الصفحة الرسمية التي ظهر فيها الشعار. '
        'إن لم تجد دليلًا رسميًا لمشروع أعد حقوله فارغة، ولا تخمّن أي رابط.'
    )
    response = None
    for tools_on in (False, True):
        # Plugin-only first: the multi-lookup prompt makes Gemini answer the
        # tool call with MALFORMED_FUNCTION_CALL, so the Exa plugin is the
        # reliable ground — until a deployment where it returns nothing, in
        # which case the server tool is the only remaining path to citations.
        try:
            response, _provider_error = _call_market_study_model(
                market_study.build_consultant_system_prompt(), prompt, max_tokens=4000,
                usage_ctx=_usage_ctx('market', data, tenant_id=tenant_id), server_tools=tools_on)
        except Exception:
            response = None
            continue
        if _market_search_ran(response):
            break
    if not _market_search_ran(response):
        for row in batch:
            row.setdefault('logo_import_warning', 'تعذر التحقق من الموقع الرسمي للشعار')
        return
    parsed, _parse_error = _parse_market_model_json(response)
    discovery_pages = _market_citation_pages(response)
    results = parsed.get('results') if isinstance(parsed, dict) else None
    if not isinstance(results, list):
        results = [parsed] if isinstance(parsed, dict) else []
    by_id = {str(row.get('id') or ''): row for row in batch}
    by_name = {str(row.get('name') or '').strip().casefold(): row for row in batch}

    def _trusted_official_hosts(name):
        """Hosts whose retrieved pages carry the competitor's whole name.

        The model's claimed official_url is only as good as the retrieval
        behind it: accept a host when a real retrieved page on it mentions all
        distinctive name tokens — otherwise a district article on a developer
        site would brand an unrelated project with that developer's logo.
        """
        tokens = _competitor_name_tokens(name)
        if not tokens:
            return set()
        hosts = set()
        for page in discovery_pages:
            page_url = str(page.get('url') or '')
            haystack = market_study._fold_choice(f"{page.get('title') or ''} {page_url}")
            if sum(1 for token in tokens if token in haystack) < len(tokens):
                continue
            host = _normalized_web_host(page_url)
            if host and not any(token in host for token in _AGGREGATOR_HOST_TOKENS):
                hosts.add(host)
        return hosts

    for item in results:
        if not isinstance(item, dict):
            continue
        row = by_id.get(str(item.get('id') or ''))
        if row is None:
            row = by_name.get(str(item.get('name') or '').strip().casefold())
        if row is None:
            continue
        official = str(
            item.get('official_url') or item.get('official_website') or item.get('website')
            or item.get('logo_source_url') or item.get('source_url') or item.get('url') or ''
        ).strip()
        official_host = _normalized_web_host(official)
        if not official_host or not any(
                _related_official_hosts(f'https://{official_host}', f'https://{host}')
                for host in _trusted_official_hosts(row.get('name'))):
            continue
        row['logo_url'] = str(item.get('logo_url') or '').strip()
        row['logo_source_url'] = official
        row['logo_official_verified'] = True
    # The model's JSON is only a formatter — the Exa citations carry the actual
    # retrieved pages. When the reply is malformed (Gemini emits
    # MALFORMED_FUNCTION_CALL on multi-lookup prompts) or misses a row, match
    # those pages to each competitor's name directly.
    for row in batch:
        if row.get('logo_official_verified'):
            continue
        dead_keys = {str(item).strip().casefold() for item in (row.get('dead_source_urls') or [])}
        for page_url in _official_citation_pages(discovery_pages, row.get('name')):
            if page_url.casefold() in dead_keys:
                continue
            row['logo_source_url'] = page_url
            row['logo_official_verified'] = True
            break
    for row in batch:
        if not row.get('logo_official_verified'):
            continue
        official = str(row.get('logo_source_url') or '').strip()
        field_sources = market_study.competitor_field_sources(row)
        urls = field_sources.setdefault('logo_url', [])
        if official and official not in urls:
            urls.append(official)
        row['field_sources'] = field_sources
        if official:
            row['source_urls'] = list(dict.fromkeys(
                market_study.competitor_source_urls(row) + [official]))
        report(86 + int(6 * (batch.index(row) if row in batch else 0) / max(1, len(batch))),
               f'تحميل شعار «{row.get("name") or "منافس"}»...')
        try:
            _store_imported_competitor_logo(row, draft_id=draft_id)
        except Exception as exc:
            row['logo_import_warning'] = str(exc)
    for row in batch:
        if not row.get('logo_file_id') and not row.get('logo_path'):
            row.setdefault('logo_import_warning', 'لم يُعثر على موقع رسمي موثق للشعار')
    # Portal-only competitors have no official site to brand from, but their
    # retrieved listing pages carry the property's own photo in og:image.
    for row in rows:
        if row.get('logo_file_id') or row.get('logo_path'):
            continue
        try:
            _import_competitor_listing_photo(row, draft_id=draft_id)
        except Exception as exc:
            row.setdefault('logo_import_warning', str(exc))


def _store_imported_competitor_logo(row, draft_id=None):
    logo_url = str((row or {}).get('logo_url') or '').strip()
    official_url = str((row or {}).get('logo_source_url') or (row or {}).get('source_url') or '').strip()
    name = str((row or {}).get('name') or 'competitor').strip()
    if not official_url:
        return row
    if not (row or {}).get('logo_official_verified') and not market_study.official_source_reliability(
            name, (row or {}).get('source'), official_url):
        return row
    content = mime_type = extension = None
    error = ''
    candidates = [logo_url] if logo_url else []
    seen = set()
    for candidate in candidates:
        key = str(candidate or '').strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        content, mime_type, extension, error = _safe_download_competitor_logo(candidate, official_url)
        if content:
            logo_url = candidate
            row['logo_url'] = candidate
            break
    if not content:
        candidates, page_error = _official_logo_candidates(official_url)
        for candidate in candidates:
            key = str(candidate or '').strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            content, mime_type, extension, error = _safe_download_competitor_logo(candidate, official_url)
            if content:
                logo_url = candidate
                row['logo_url'] = candidate
                break
        if not content and page_error:
            error = page_error
    if not content:
        favicon_content, favicon_mime, favicon_ext, _favicon_error = _download_official_favicon(official_url)
        if favicon_content:
            content, mime_type, extension = favicon_content, favicon_mime, favicon_ext
            logo_url = ('https://t2.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON'
                        f'&fallback_opts=TYPE,SIZE,URL&url=http://{_normalized_web_host(official_url)}&size=128')
            row['logo_url'] = logo_url
            row['logo_low_res'] = True
            row['logo_favicon_host'] = _normalized_web_host(official_url)
            error = ''
    if error or not content:
        row['logo_import_warning'] = error or 'تعذر استيراد شعار المنافس'
        return row
    from werkzeug.datastructures import FileStorage
    upload = FileStorage(
        stream=BytesIO(content), filename='competitor-logo' + extension, content_type=mime_type,
    )
    stored = _store_project_upload(
        upload, 'competitor_logo', draft_id=draft_id, project_id=str(row.get('id') or '') or None,
    )
    published = _publish_project_file_as_creative_image(stored['id'])
    row['logo_file_id'] = stored['id']
    row['logo_path'] = published or ('/api/project-files/' + stored['id'])
    row['logo_source_url'] = official_url
    row.pop('logo_import_warning', None)
    return row


_LISTING_IMAGE_META_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::url)?|og:image:secure_url'
    r'|twitter:image(?::src)?)["\'][^>]*?content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]*?(?:property|name)=["\']'
    r'(?:og:image(?::url)?|og:image:secure_url|twitter:image(?::src)?)["\']',
    re.IGNORECASE)
_LISTING_IMAGE_SKIP_TOKENS = (
    'logo', 'brand', 'icon', 'sprite', 'favicon', 'placeholder', 'default',
    'share', 'watermark', 'ruwaj', 'rawaj', 'rowaj', '/rwaj', 'rega',
)


def _download_listing_image(image_url):
    """(content, mime, ext) — fetch a listing photo from any public HTTPS host.

    Unlike _safe_download_competitor_logo there is no same-host rule: portal
    CDNs (images.bayut.com) are intentionally different hosts — the file is
    the competitor's own property photo, not the portal's branding."""
    parsed = urlsplit(str(image_url or '').strip())
    try:
        invalid_port = parsed.port not in (None, 443)
    except ValueError:
        invalid_port = True
    if (parsed.scheme.lower() != 'https' or not parsed.hostname
            or parsed.username or invalid_port):
        return None, None, None
    lowered = str(image_url).casefold()
    if any(token in lowered for token in _LISTING_IMAGE_SKIP_TOKENS):
        return None, None, None
    if not _public_host_addresses(parsed.hostname):
        return None, None, None
    pool, response, _outcome = _pinned_https_get(image_url)
    if pool is None:
        return None, None, None
    try:
        if response.status != 200:
            return None, None, None
        mime_type = str(response.headers.get('Content-Type') or '').split(';', 1)[0].strip().lower()
        extension = COMPETITOR_LOGO_MIMES.get(mime_type)
        if not extension:
            return None, None, None
        content = bytearray()
        for chunk in response.stream(64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > COMPETITOR_LOGO_MAX_BYTES:
                return None, None, None
        return bytes(content), mime_type, extension
    except Exception:
        return None, None, None
    finally:
        response.release_conn()
        pool.close()


def _import_competitor_listing_photo(row, draft_id=None):
    """Last-resort competitor image: the retrieved listing page's own photo.

    Portal-only competitors have no official site to brand from, but their
    retrieved listing pages carry the property's photo in og:image. Stored
    through the same upload path and marked logo_listing_photo so it never
    pretends to be an official logo."""
    dead = {str(item).strip().casefold() for item in (row.get('dead_source_urls') or [])}
    misses = []
    for page_url in list(dict.fromkeys(market_study.competitor_source_urls(row)))[:4]:
        if str(page_url).strip().casefold() in dead:
            continue
        html, _err = _read_market_source_page(page_url)
        if not html:
            misses.append(f'{_normalized_web_host(page_url)}:unreadable')
            continue
        found_meta = False
        for match in _LISTING_IMAGE_META_RE.finditer(html):
            found_meta = True
            image_url = urljoin(page_url, match.group(1) or match.group(2) or '')
            content, mime_type, extension = _download_listing_image(image_url)
            if not content:
                misses.append(f'{_normalized_web_host(page_url)}:image-rejected')
                continue
            from werkzeug.datastructures import FileStorage
            upload = FileStorage(
                stream=BytesIO(content), filename='competitor-photo' + extension,
                content_type=mime_type)
            stored = _store_project_upload(
                upload, 'competitor_logo', draft_id=draft_id,
                project_id=str(row.get('id') or '') or None)
            published = _publish_project_file_as_creative_image(stored['id'])
            row['logo_file_id'] = stored['id']
            row['logo_path'] = published or ('/api/project-files/' + stored['id'])
            row['logo_url'] = image_url
            row['logo_source_url'] = page_url
            row['logo_listing_photo'] = True
            row.pop('logo_import_warning', None)
            field_sources = market_study.competitor_field_sources(row)
            urls = field_sources.setdefault('logo_url', [])
            if page_url not in urls:
                urls.append(page_url)
            row['field_sources'] = field_sources
            return
        if not found_meta:
            misses.append(f'{_normalized_web_host(page_url)}:no-og-image')
    if misses:
        print(f"[MARKET STUDY] «{row.get('name') or 'منافس'}» no listing photo: "
              + ', '.join(misses))


def _store_project_upload(uploaded_file, file_type, draft_id=None, project_id=None):
    if file_type not in PROJECT_FILE_TYPES:
        raise ValueError('Invalid project file type')
    original_name = os.path.basename(uploaded_file.filename or '').strip() or 'document'
    extension = os.path.splitext(original_name)[1].lower()
    mime_type = PROJECT_FILE_EXTENSIONS.get(extension)
    if not mime_type:
        raise ValueError('Only PNG, JPG, JPEG, WEBP, and PDF files are supported')
    if file_type in PROJECT_IMAGE_ONLY_TYPES and not mime_type.startswith('image/'):
        raise ValueError('هذا الحقل يقبل الصور فقط (PNG أو JPG أو WEBP)')
    allowed_exts, max_bytes = _upload_file_rule(file_type)
    if allowed_exts and extension not in allowed_exts:
        raise ValueError('امتداد الملف غير مسموح لهذا النوع')

    document_dir = os.path.join(UPLOADS_DIR, re.sub(r'[^A-Za-z0-9_-]', '', str(g.tenant_id)) or 'public', 'project-documents')
    os.makedirs(document_dir, exist_ok=True)
    temp_path = os.path.join(document_dir, f'.upload-{_uuid.uuid4().hex}.tmp')
    digest = hashlib.sha256()
    total = 0
    try:
        with open(temp_path, 'wb') as output:
            while True:
                chunk = uploaded_file.stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f'Project files must be {max_bytes // (1024 * 1024)} MB or smaller')
                digest.update(chunk)
                output.write(chunk)

        with open(temp_path, 'rb') as source:
            signature = source.read(8)
        if mime_type == 'application/pdf' and not signature.startswith(b'%PDF'):
            raise ValueError('Invalid PDF file')
        if mime_type.startswith('image/'):
            try:
                from PIL import Image, UnidentifiedImageError
                with Image.open(temp_path) as image:
                    image.verify()
            except (UnidentifiedImageError, OSError):
                raise ValueError('Invalid image file')

        sha256 = digest.hexdigest()
        final_name = f'{sha256}{extension}'
        final_path = os.path.join(document_dir, final_name)
        if not os.path.exists(final_path):
            os.replace(temp_path, final_path)
        else:
            os.unlink(temp_path)
        try:
            relative_path = os.path.relpath(final_path, os.path.dirname(__file__)).replace('\\', '/')
        except ValueError:
            relative_path = f'uploads/{g.tenant_id}/project-documents/{final_name}'
        file_id = db.create_project_file(
            g.tenant_id, file_type, original_name, final_path, mime_type, total, sha256,
            draft_id=draft_id, project_id=project_id
        )
        return {
            'id': file_id,
            'fileType': file_type,
            'originalName': original_name,
            'mimeType': mime_type,
            'fileSize': total,
            'sha256': sha256,
            'path': relative_path,
        }
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def _project_file_in_scope(stored):
    """ISS-014: a project file follows the scope of the draft it belongs to.

    Files with no live draft link stay reachable, matching the NULL-draft
    presentations convention; a file whose draft exists but sits outside the
    caller's scope is refused as not found.
    """
    if not stored:
        return False
    draft_id = stored.get('draft_id')
    if not draft_id:
        return True
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if not draft:
        return True
    return db.user_may_access_draft(g.user_id, draft)


@app.route('/api/project-files', methods=['POST'])
@require_permission('create_presentation')
def api_upload_project_file():
    uploaded_file = request.files.get('file')
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({'success': False, 'error': 'No project file provided'}), 400
    file_type = (request.form.get('fileType') or '').strip().lower()
    draft_id = (request.form.get('draftId') or '').strip() or None
    if draft_id:
        draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
        if draft and not db.user_may_access_draft(g.user_id, draft):
            return jsonify({'success': False, 'error': 'Draft not found'}), 404
    project_id = (request.form.get('projectId') or '').strip() or None
    try:
        result = _store_project_upload(uploaded_file, file_type, draft_id=draft_id, project_id=project_id)
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400
    except OSError as error:
        return jsonify({'success': False, 'error': f'Could not store project file: {error}'}), 500
    if file_type == 'competitor_logo' and draft_id:
        _record_change('draft', draft_id, 'رفع شعار منافس',
                       [f'رُفع الملف «{result.get("originalName") or "شعار منافس"}»'])
    return jsonify({'success': True, 'file': result}), 201


@app.route('/api/project-files/<file_id>', methods=['GET'])
@require_auth
def api_get_project_file(file_id):
    """Stream a previously uploaded project document back so the client can preview it.

    Uploads are only reachable through this route: the record is looked up inside the
    caller's tenant, and the stored path must resolve inside that tenant's upload folder.
    A super admin previewing another company falls back to a cross-tenant lookup; the
    path is still confined inside the owning tenant's folder.
    """
    stored = db.get_project_file(g.tenant_id, str(file_id))
    resolve_tenant = g.tenant_id
    if not stored and getattr(g, 'is_admin', False):
        stored = db.get_project_file_by_id(str(file_id))
        resolve_tenant = (stored or {}).get('tenant_id') or g.tenant_id
        if stored:
            # d07: cross-tenant file reads need an active client-approved grant.
            grant = _require_admin_content_access(
                resolve_tenant, scope='file', target_id=str(file_id))
            if isinstance(grant, tuple):
                return grant
    if not stored or not stored.get('storage_path'):
        return jsonify({'success': False, 'error': 'الملف غير موجود'}), 404
    if resolve_tenant == g.tenant_id and not _project_file_in_scope(stored):
        return jsonify({'success': False, 'error': 'الملف غير موجود'}), 404
    return _send_project_file_response(stored, resolve_tenant)


def _send_project_file_response(stored, resolve_tenant):
    storage_path = _resolve_project_file_storage_path(stored, resolve_tenant)
    if not storage_path:
        tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, str(resolve_tenant)))
        raw_target = os.path.realpath(stored.get('storage_path') or '')
        try:
            inside = os.path.commonpath([tenant_root, raw_target]) == tenant_root
        except ValueError:
            inside = False
        if not inside:
            print(f"[PROJECT FILE] rejected out-of-tenant path for {stored.get('id')}")
            return jsonify({'success': False, 'error': 'مسار الملف غير مسموح'}), 403
        return jsonify({'success': False, 'error': 'الملف غير متاح على السيرفر'}), 404

    mime_type = stored.get('mime_type') or 'application/octet-stream'
    # PDFs and images render inline; anything else downloads instead of executing.
    inline = mime_type == 'application/pdf' or mime_type.startswith('image/')
    response = send_file(
        storage_path,
        mimetype=mime_type,
        as_attachment=not inline,
        download_name=stored.get('original_name') or os.path.basename(storage_path),
        conditional=True,
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'none'; object-src 'none'"
    response.headers['Cache-Control'] = 'private, max-age=300'
    return response


@app.route('/api/project-files/<file_id>/signed-url', methods=['POST'])
@require_permission('create_presentation')
def api_project_file_signed_url(file_id):
    """t61: mint a short-lived signed URL for a file inside the caller's tenant."""
    stored = db.get_project_file(g.tenant_id, str(file_id))
    if not stored or not stored.get('storage_path'):
        return jsonify({'success': False, 'error': 'الملف غير موجود'}), 404
    if not _project_file_in_scope(stored):
        return jsonify({'success': False, 'error': 'الملف غير موجود'}), 404
    token = auth.create_signed_download_token(str(file_id), g.tenant_id)
    return jsonify({'success': True, 'url': f'/api/files/signed/{token}'})


@app.route('/api/files/signed/<token>', methods=['GET'])
def api_signed_file_download(token):
    """Serve a project file by signed token — the token itself is the auth."""
    claims = auth.verify_signed_download_token(token)
    if not claims:
        return jsonify({'success': False, 'error': 'الرابط غير صالح أو منتهي'}), 403
    stored = db.get_project_file(claims['tenant_id'], claims['file_id'])
    if not stored or not stored.get('storage_path'):
        return jsonify({'success': False, 'error': 'الملف غير موجود'}), 404
    return _send_project_file_response(stored, claims['tenant_id'])


@app.route('/api/project-files/<file_id>', methods=['DELETE'])
@require_permission('create_presentation')
def api_delete_project_file(file_id):
    stored = db.get_project_file(g.tenant_id, str(file_id))
    if not stored:
        return jsonify({'success': False, 'error': 'الملف غير موجود'}), 404
    if not _project_file_in_scope(stored):
        return jsonify({'success': False, 'error': 'الملف غير موجود'}), 404
    if stored.get('file_type') != 'competitor_logo':
        return jsonify({'success': False, 'error': 'لا يمكن حذف هذا النوع من الملفات من هنا'}), 400

    storage_path = _resolve_project_file_storage_path(stored, g.tenant_id)
    if not storage_path:
        tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, str(g.tenant_id)))
        raw_target = os.path.realpath(stored.get('storage_path') or '')
        try:
            inside = os.path.commonpath([tenant_root, raw_target]) == tenant_root
        except ValueError:
            inside = False
        if not inside:
            print(f"[PROJECT FILE] rejected delete outside tenant path for {file_id}")
            return jsonify({'success': False, 'error': 'مسار الملف غير مسموح'}), 403
    try:
        # Copied drafts share the same storage path — the physical file is
        # removed only when this row is its last reference.
        shared = db.get_db().execute(
            'SELECT COUNT(*) AS c FROM project_files WHERE storage_path = ? AND id != ?',
            (stored.get('storage_path') or '', str(file_id))).fetchone()
        if storage_path and os.path.isfile(storage_path) and not (shared and shared['c']):
            os.unlink(storage_path)
    except OSError as error:
        print(f"[PROJECT FILE] could not remove logo file {file_id}: {error}")
    deleted = db.delete_project_file(g.tenant_id, str(file_id))
    return jsonify({'success': bool(deleted), 'fileId': str(file_id)})


@app.route('/api/project-files/<file_id>/publish-image', methods=['POST'])
@require_permission('create_presentation')
def api_publish_project_file_image(file_id):
    """Return a durable URL for an uploaded image so a saved draft can point at it.

    The preview route needs an Authorization header, so the client had to read it into a
    ``blob:`` URL — which dies with the tab. This publishes the same bytes under
    ``/uploads/creative/<tenant>/`` exactly like a generated image.
    """
    stored = db.get_project_file(g.tenant_id, str(file_id))
    if not stored or not _project_file_in_scope(stored):
        return jsonify({'success': False, 'error': 'الملف غير موجود'}), 404
    url = _publish_project_file_as_creative_image(file_id)
    if not url:
        return jsonify({'success': False, 'error': 'الملف غير متاح أو ليس صورة'}), 404
    return jsonify({'success': True, 'url': url})


@app.route('/api/upload/logo', methods=['POST'])
@require_permission('company_settings')
def api_upload_logo():
    """Upload company logo."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No filename'}), 400

    try:
        logo_path, extension = _save_tenant_image(file, 'logo')
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    relative_path = f'/tenant-assets/{g.tenant_id}/logo'
    db.update_branding(g.tenant_id, logo_path=relative_path)
    return jsonify({'success': True, 'logoPath': relative_path})


@app.route('/api/upload/watermark', methods=['POST'])
@require_permission('company_settings')
def api_upload_watermark():
    """Upload the company's watermark as a branding asset separate from its logo."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No filename'}), 400

    try:
        _save_tenant_image(file, 'watermark')
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    relative_path = f'/tenant-assets/{g.tenant_id}/watermark'
    db.update_branding(g.tenant_id, watermark_path=relative_path)
    return jsonify({
        'success': True,
        'watermarkPath': relative_path,
        'branding': db.get_branding(g.tenant_id),
    })


@app.route('/api/upload/watermark', methods=['DELETE'])
@require_permission('company_settings')
def api_delete_watermark():
    """Clear the configured watermark without changing the company logo."""
    for watermark_path in _tenant_image_storage_candidates(g.tenant_id, 'watermark'):
        if not os.path.isfile(watermark_path):
            continue
        try:
            os.unlink(watermark_path)
        except OSError as error:
            print(f'[TENANT IMAGE] could not remove watermark file: {error}')
    db.update_branding(g.tenant_id, watermark_path=None)
    return jsonify({'success': True, 'branding': db.get_branding(g.tenant_id)})


@app.route('/api/upload/reference-image', methods=['POST'])
@require_permission('company_settings')
def api_upload_reference():
    """Upload a reference design image."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No filename'}), 400

    try:
        ref_path, extension = _save_tenant_image(file, 'reference')
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    stored_path = os.path.relpath(ref_path, os.path.dirname(__file__)).replace('\\', '/')
    db.update_branding(g.tenant_id, reference_image_path=stored_path)
    return jsonify({'success': True, 'referenceImageUploaded': True})


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
