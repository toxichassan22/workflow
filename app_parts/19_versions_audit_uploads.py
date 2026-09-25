# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PRESENTATION VERSIONS, AUDIT LOG & UPLOADS — version snapshots, the edit
# and audit trails, then the upload machinery: shared upload constants and
# helpers, project files with signed URLs, and the logo/watermark/reference
# image endpoints.
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
        if not _landloom_can('post_approval_edit'):
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
                      'conceptual_plan', 'project_logo', 'recharge_receipt', 'recharge_invoice',
                      'ticket_attachment'}
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
    'recharge_invoice': 'recharge_invoice',
    'ticket_attachment': 'ticket_attachment',
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


def _store_project_upload(uploaded_file, file_type, draft_id=None, project_id=None):
    if file_type not in PROJECT_FILE_TYPES:
        raise ValueError('Invalid project file type')
    original_name = os.path.basename(uploaded_file.filename or '').strip() or 'document'
    extension = os.path.splitext(original_name)[1].lower()
    mime_type = PROJECT_FILE_EXTENSIONS.get(extension)
    if not mime_type:
        # Support-ticket attachments take any extension; unknown types are
        # stored as octet-stream so downloads never render in the browser.
        if file_type != 'ticket_attachment':
            raise ValueError('Only PNG, JPG, JPEG, WEBP, and PDF files are supported')
        mime_type = 'application/octet-stream'
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
