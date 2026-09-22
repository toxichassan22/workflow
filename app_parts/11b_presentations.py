


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Presentation persistence: list/get/save/update/delete with
# optimistic revision checks, provenance issue/verify, project-metadata
# freezing and the audited commit path.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@app.route('/api/presentations', methods=['GET'])
@require_permission('view_presentations')
def api_get_presentations():
    """List tenant presentations with optional project and archive filters."""
    try:
        limit = int(request.args.get('limit', 200))
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit and offset must be integers'}), 400
    accessible = db.user_accessible_draft_ids(g.user_id, g.tenant_id)
    presentations = db.get_presentations(
        g.tenant_id,
        draft_id=(request.args.get('draftId') or '').strip() or None,
        search=(request.args.get('search') or '').strip(),
        status=(request.args.get('status') or '').strip(),
        date_from=(request.args.get('from') or '').strip(),
        date_to=(request.args.get('to') or '').strip(),
        limit=limit,
        offset=offset,
        accessible_draft_ids=accessible,
    )
    total = db.count_presentations(
        g.tenant_id,
        draft_id=(request.args.get('draftId') or '').strip() or None,
        search=(request.args.get('search') or '').strip(),
        status=(request.args.get('status') or '').strip(),
        date_from=(request.args.get('from') or '').strip(),
        date_to=(request.args.get('to') or '').strip(),
        accessible_draft_ids=accessible,
    )
    result = []
    for p in presentations:
        result.append({
            'id': p['id'],
            'title': p['title'],
            'draftId': p.get('draft_id'),
            'revision': int(p.get('revision') or 0),
            'presentationScope': p.get('presentation_scope'),
            'slideCount': p.get('slide_count', 0),
            'status': p.get('status', 'draft'),
            'createdAt': p.get('created_at'),
            'updatedAt': p.get('updated_at'),
        })
    return jsonify({'success': True, 'presentations': result, 'total': total})


def _presentation_has_workflow_history(pres_id):
    """True when the presentation carries approvals, exports or downloads."""
    conn = db.get_db()
    try:
        for table in ('final_file_approvals', 'exports', 'presentation_downloads'):
            if conn.execute(
                    f'SELECT 1 FROM {table} WHERE tenant_id = ? AND presentation_id = ? LIMIT 1',
                    (g.tenant_id, pres_id)).fetchone():
                return True
        return False
    except Exception:
        return True


@app.route('/api/presentations/<pres_id>', methods=['DELETE'])
@require_permission('create_presentation')
def api_delete_presentation(pres_id):
    """Delete is cleanup for never-processed presentations only — admin-gated,
    and refused once the file carries workflow history (t18)."""
    presentation = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not presentation or not _presentation_in_scope(presentation):
        return jsonify({'error': 'Presentation not found'}), 404
    if not _landloom_actor_is_admin():
        return jsonify({'error': 'الحذف النهائي يتطلب صلاحية مدير الشركة — أو استخدم الأرشفة',
                        'error_code': 'admin_required'}), 403
    if _presentation_has_workflow_history(pres_id):
        return jsonify({'error': 'لهذا العرض مسار اعتماد محفوظ — استخدم الأرشفة بدل الحذف',
                        'error_code': 'archive_required'}), 409
    _record_change('presentation', pres_id, 'حذف العرض',
                   [f'حُذف العرض «{presentation.get("title") or "بدون عنوان"}»'])
    if not db.delete_presentation(pres_id, g.tenant_id):
        return jsonify({'error': 'Presentation not found'}), 404
    return jsonify({'success': True})


def _presentation_state(pres):
    """Serialize stored state without merging mutable draft assets into a revision."""
    state = dict(pres)
    for stored, public, default in [('project_data', 'projectData', {}), ('slides_data', 'slidesData', [])]:
        value = state.get(stored)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                value = default
        state[public] = value if isinstance(value, type(default)) else default
    state['slideCount'] = len(state['slidesData'])
    state['draftId'] = state.get('draft_id')
    state['revision'] = int(state.get('revision') or 0)
    return state


def _presentation_revision_response(result):
    return {
        'success': True, 'presentationId': result['presentation_id'],
        'revision': result['revision'], 'versionId': result.get('version_id'),
        'changed': result.get('changed', True),
        'presentation': _presentation_state(result['presentation']),
    }


def _expected_presentation_revision(data, pres):
    expected = data.get('expectedRevision', int((pres or {}).get('revision') or 0))
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise ValueError('expectedRevision must be a non-negative integer')
    return expected


@app.errorhandler(db.PresentationRevisionConflict)
def _presentation_conflict(error):
    return jsonify({
        'success': False, 'error': 'تغير العرض منذ فتحه؛ لم تُحفظ هذه التغييرات',
        'error_code': 'PRESENTATION_REVISION_CONFLICT',
        'expectedRevision': error.expected_revision, 'currentRevision': error.current_revision,
    }), 409


@app.errorhandler(presentation_assets.PresentationAssetError)
def _presentation_asset_error(error):
    return jsonify({
        'success': False, 'error': 'وسائط العرض غير صالحة أو غير مصرح بها؛ لم تُحفظ التغييرات',
        'error_code': 'PRESENTATION_ASSET_REJECTED',
    }), 422


def _presentation_provenance_serializer():
    from itsdangerous import URLSafeTimedSerializer
    from auth import JWT_SECRET
    return URLSafeTimedSerializer(JWT_SECRET, salt='presentation-ai-provenance-v1')


def _presentation_slides_digest(slides):
    import hashlib
    return hashlib.sha256(json.dumps(slides, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def _issue_presentation_provenance(slides, presentation_id, revision, details):
    return {'token': _presentation_provenance_serializer().dumps({
        'tenant': g.tenant_id, 'actor': g.user_id, 'presentation': presentation_id,
        'revision': revision, 'slides': _presentation_slides_digest(slides),
        'details': details,
    })}


def _verified_presentation_provenance(data, presentation_id, revision):
    """A client-supplied source or actor is not evidence of an AI edit."""
    from itsdangerous import BadData
    provenance = data.get('provenance')
    if data.get('changeSource') != 'ai' or not isinstance(provenance, dict):
        return 'manual', []
    try:
        receipt = _presentation_provenance_serializer().loads(provenance.get('token', ''), max_age=7 * 86400)
        if (receipt.get('tenant') == g.tenant_id and receipt.get('actor') == g.user_id
                and receipt.get('presentation') == presentation_id
                and receipt.get('revision') == revision):
            # The receipt proves an AI operation in this unsaved workspace, not that
            # every final byte was AI-authored. Manual edits and fitting may follow it.
            details = list(receipt.get('details') or [])
            details.insert(0, 'حفظ بمساعدة الذكاء الاصطناعي؛ قد يتضمن تعديلات يدوية')
            return 'ai', details
    except (BadData, TypeError, ValueError):
        pass
    return 'manual', []


def _freeze_presentation_project_metadata(value, freeze):
    # Private source documents are retained as metadata, never copied to public
    # revision assets. Rendered HTML still goes through the strict media freezer.
    if isinstance(value, dict):
        return {key: _freeze_presentation_project_metadata(item, freeze) for key, item in value.items()}
    if isinstance(value, list):
        return [_freeze_presentation_project_metadata(item, freeze) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(('{', '[')):
            try:
                decoded = json.loads(value)
            except (TypeError, ValueError):
                pass
            else:
                return json.dumps(_freeze_presentation_project_metadata(decoded, freeze), ensure_ascii=False)
        from urllib.parse import urlsplit
        path = urlsplit(text).path if '<' not in text and '\n' not in text else ''
        normalized_path = '/' + path.lstrip('/')
        if (normalized_path.startswith(('/api/project-files/', '/uploads/project-documents/'))
                or '/project-documents/' in normalized_path
                or re.search(r'\.(?:pdf|docx?|xlsx?|csv|txt)$', normalized_path, re.I)):
            return value
    return freeze(value)


def _commit_presentation_state(tenant_id, presentation_id=None, **kwargs):
    """All application content writes use the transactional version/history authority."""
    from presentation_assets import freeze_presentation_assets
    root = os.path.dirname(__file__)
    authorized = {}
    for row in db.get_map_images(tenant_id):
        path = row.get('file_path')
        if path:
            full_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(root, path))
            try:
                relative = '/' + os.path.relpath(full_path, root).replace('\\', '/')
            except ValueError:
                continue
            if relative.startswith('/uploads/maps/') and os.path.isfile(full_path):
                authorized[relative] = full_path
    for kind, path in [('logo', _tenant_logo_storage_path(tenant_id)),
                       ('watermark', _tenant_watermark_storage_path(tenant_id))]:
        if kind == 'logo' and not path:
            path = os.path.join(root, 'assets', 'logo.png')
        if path and os.path.isfile(path):
            authorized[f'/tenant-assets/{tenant_id}/{kind}'] = path
    for pf in db.get_project_files(tenant_id):
        storage_path = pf.get('storage_path')
        if storage_path and os.path.isfile(storage_path) and (pf.get('mime_type') or '').startswith('image/'):
            file_id = pf.get('id')
            if file_id:
                authorized[f'/api/project-files/{file_id}'] = storage_path
            try:
                rel_pf = '/' + os.path.relpath(storage_path, root).replace('\\', '/')
                authorized[rel_pf] = storage_path
            except ValueError:
                pass
    def freeze(value):
        if isinstance(value, dict):
            return {key: freeze(item) for key, item in value.items()}
        if isinstance(value, list):
            return [freeze(item) for item in value]
        # Dangling historical uploads references (files absent from this
        # server) are preserved inside the freezer per-URL; every asset that
        # exists must pass its authorization and safety checks.
        return freeze_presentation_assets(
            value, tenant_id, authorized_paths=authorized,
            allowed_origin=request.host_url.rstrip('/'),
            uploads_root=UPLOADS_DIR, preserve_missing_uploads=True)
    def freeze_snapshot(state):
        frozen = dict(state)
        parsed = _presentation_state(state)
        for stored, public in [('project_data', 'projectData'), ('slides_data', 'slidesData')]:
            frozen[stored] = (_freeze_presentation_project_metadata(parsed[public], freeze)
                              if stored == 'project_data' else freeze(parsed[public]))
        return frozen
    kwargs['snapshot_transform'] = freeze_snapshot
    kwargs.setdefault('user_id', getattr(g, 'user_id', None))
    kwargs.setdefault('user_name', getattr(g, 'user_name', None) or 'مدير الشركة')
    return db.commit_presentation_revision(tenant_id, presentation_id, **kwargs)


def _presentation_save_failure(stage, exc):
    """Answer a presentation-save crash as JSON naming the failed stage.

    The workspace lives only in the browser until the save succeeds, so a bare
    HTML 500 hides both the cause and the fact that the edits are still open.
    The exception type (never its message or the payload) travels with the
    response; the full traceback stays in the server log.
    """
    app.logger.exception(
        '[PRESENTATION SAVE] Failed at stage %s: %s: %s', stage, type(exc).__name__, exc)
    detail = f'{type(exc).__name__}: {exc}'
    for private in (os.path.dirname(__file__), UPLOADS_DIR):
        if private:
            detail = detail.replace(str(private), '[app]')
    return jsonify({
        'success': False,
        'error': 'تعذر حفظ العرض بسبب خطأ داخلي؛ تعديلاتك ما زالت مفتوحة في المتصفح ولم تُفقد',
        'error_code': 'PRESENTATION_SAVE_FAILED',
        'stage': stage,
        'reason': type(exc).__name__,
        'detail': detail[:200],
    }), 500


@app.route('/api/presentations', methods=['POST'])
@require_permission('create_presentation')
def api_save_presentation():
    """Save a new presentation."""
    data = request.json or {}
    if not isinstance(data, dict) or not isinstance(data.get('projectData', {}), dict) or not isinstance(data.get('slidesData', []), list):
        return jsonify({'error': 'projectData must be an object and slidesData an array'}), 400
    try:
        expected_revision = _expected_presentation_revision(data, None)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    title = str(data.get('title') or 'عرض بدون عنوان').strip()
    incoming_project = data.get('projectData') or {}
    locked_status = _presentation_draft_lock(
        incoming_project.get('draftId') or incoming_project.get('draft_id'), data)
    if locked_status:
        return _draft_locked_response(locked_status)
    save_stage = 'normalize'
    try:
        project_data = normalize_presentation_assets(incoming_project, g.tenant_id)
        slides_data = normalize_presentation_assets(data.get('slidesData', []), g.tenant_id)
        branding = db.get_branding(g.tenant_id) or {}
        render_project_data = copy.deepcopy(project_data)
        _prepare_generation_logo_context(render_project_data, branding, g.tenant_id)
        save_stage = 'renumber'
        slides_data = slide_engine.renumber_presentation_slides(
            slides_data, branding=branding, project_data=render_project_data,
            tenant_id=g.tenant_id,
            creative_images=_presentation_creative_images(render_project_data, g.tenant_id),
        )
        slide_count = len(slides_data)

        scope = project_data.get('presentation_scope')
        draft_id = project_data.get('draftId') or project_data.get('draft_id')
        if draft_id:
            # ISS-014: a project-scoped member cannot hang a new presentation on
            # a draft outside their scope.
            linked_draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
            if linked_draft and not db.user_may_access_draft(g.user_id, linked_draft):
                return jsonify({'error': 'Draft not found'}), 404
        creation_key = None
        if draft_id and isinstance(scope, str) and (scope == 'full' or re.fullmatch(r'(?:section|copy):[A-Za-z0-9_-]+', scope)):
            creation_key = json.dumps([str(draft_id), scope], separators=(',', ':'))
        source, provenance_details = _verified_presentation_provenance(data, None, 0)
        save_stage = 'commit'
        result = _commit_presentation_state(
            g.tenant_id, title=title, project_data=project_data, slides_data=slides_data,
            draft_id=draft_id, creation_key=creation_key,
            expected_revision=expected_revision, source=source, action='إنشاء العرض',
            details=[f'العنوان: «{title}»', f'عدد الشرائح: {slide_count}'] + provenance_details,
        )
    except (LookupError, ValueError) as error:
        return jsonify({'error': str(error)}), 400
    except Exception as exc:
        return _presentation_save_failure(save_stage, exc)
    pres_id = result['presentation_id']
    if not result.get('created', True):
        return jsonify({
            'success': False, 'error': 'يوجد عرض محفوظ لهذا القسم من المشروع؛ لم يُنشأ عرض مكرر',
            'error_code': 'PRESENTATION_SCOPE_EXISTS', 'presentationId': pres_id,
            'currentRevision': result['revision'],
        }), 409
    try:
        db.link_draft_usage_to_presentation(
            g.tenant_id, project_data.get('draftId') or project_data.get('draft_id'), pres_id)
    except Exception as link_error:
        print(f"[AI-USAGE] usage link failed for presentation {pres_id}: {link_error}")
    return jsonify(_presentation_revision_response(result)), 201


@app.route('/api/presentations/<pres_id>', methods=['GET'])
@require_permission('view_presentations')
def api_get_presentation(pres_id):
    """Get a specific presentation."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'Presentation not found'}), 404

    # ISS-030: the workspace keeps saving into the linked draft, so the client
    # needs its current revision — otherwise the next expectedRevision save
    # conflicts against a stale counter it never saw.
    draft_revision = None
    if pres.get('draft_id'):
        linked_draft = db.get_project_draft_by_id(g.tenant_id, pres['draft_id'])
        if linked_draft:
            draft_revision = int(linked_draft.get('revision') or 0)

    if int(pres.get('revision') or 0) > 0:
        state = _presentation_state(pres)
        # ISS-015: the stored projectData is a draft snapshot — hidden sections
        # stay server-side for this caller.
        state['projectData'] = _draft_data_for_response(state.get('projectData'))
        state['draftRevision'] = draft_revision
        return jsonify({'success': True, 'presentation': state})
    pres['revision'] = int(pres.get('revision') or 0)
    pres['projectData'] = json.loads(pres['project_data']) if pres.get('project_data') else {}
    pres['projectData'] = _merge_persisted_map_assets(pres['projectData'], g.tenant_id, presentation_id=pres_id)
    slides = json.loads(pres['slides_data']) if pres.get('slides_data') else []
    branding = db.get_branding(g.tenant_id) or {}
    render_project_data = copy.deepcopy(pres['projectData'])
    _prepare_generation_logo_context(render_project_data, branding, g.tenant_id)
    slides = slide_engine.renumber_presentation_slides(
        slides, branding=branding, project_data=render_project_data, tenant_id=g.tenant_id,
        creative_images=_presentation_creative_images(render_project_data, g.tenant_id),
    )
    project_logo_ref = slide_engine._project_logo_reference(render_project_data)
    for s in slides:
        if isinstance(s, dict) and 'html' in s and isinstance(s['html'], str):
            # Resolve through the engine copy: it fixes ##LOGO## tokens and broken
            # logo paths exactly like the legacy pass, but never appends the 50px
            # logo sizing over an explicit height. The legacy pass matched the
            # watermark overlay img (its src carries tenant-assets) and appended
            # max-height:50px;width:auto, collapsing width:480px to a ~50px mark
            # on every open/refresh — and the next save persisted the shrink.
            s['html'] = slide_engine.resolve_logo_in_html(
                s['html'], g.tenant_id, _branding_cache=branding,
                project_logo=project_logo_ref,
            )
    pres['slide_count'] = len(slides)
    pres['slidesData'] = slides
    pres['projectData'] = _draft_data_for_response(pres.get('projectData'))
    pres['draftRevision'] = draft_revision
    return jsonify({'success': True, 'presentation': pres})


@app.route('/api/presentations/<pres_id>', methods=['PUT'])
@require_permission('create_presentation')
def api_update_presentation(pres_id):
    """Update a presentation. Saves a version snapshot and logs the edit."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'Presentation not found'}), 404

    data = request.json or {}
    if not isinstance(data, dict) or ('projectData' in data and not isinstance(data['projectData'], dict)) or ('slidesData' in data and not isinstance(data['slidesData'], list)):
        return jsonify({'error': 'projectData must be an object and slidesData an array'}), 400
    locked_status = _presentation_draft_lock(pres.get('draft_id'), data, presentation_id=pres_id)
    if locked_status:
        return _draft_locked_response(locked_status)
    # t16: editing a finally-approved file is a privileged, reasoned action —
    # the permission plus a written reason, both recorded with the edit.
    post_approval_reason = ''
    if pres.get('status') == 'approved' and ('projectData' in data or 'slidesData' in data):
        if not _landloom_can('post_approval_edit'):
            return jsonify({'error': 'تعديل ملف معتمد يتطلب صلاحية التعديل بعد الاعتماد',
                            'error_code': 'post_approval_edit_required'}), 403
        post_approval_reason = str(data.get('editReason') or '').strip()
        if not post_approval_reason:
            return jsonify({'error': 'سبب التعديل بعد الاعتماد إلزامي',
                            'error_code': 'reason_required'}), 400
    try:
        expected_revision = _expected_presentation_revision(data, pres)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    source, provenance_details = _verified_presentation_provenance(data, pres_id, expected_revision)
    save_stage = 'normalize'
    try:
        updates = {}
        for k in ['title', 'projectData', 'slidesData']:
            if k in data:
                db_key = {'projectData': 'project_data', 'slidesData': 'slides_data'}.get(k, k)
                updates[db_key] = normalize_presentation_assets(data[k], g.tenant_id) if k in {'projectData', 'slidesData'} else str(data[k] or '').strip()
        if 'status' in data and data.get('status') in {'draft', 'edited'}:
            # Operational states (pending_approval/approved/rejected) belong to
            # the approval gates — a save payload can never walk into them.
            updates['status'] = 'draft'
        if isinstance(updates.get('project_data'), dict):
            current_project = _presentation_state(pres)['projectData']
            current_scope = current_project.get('presentation_scope')
            incoming_scope = updates['project_data'].get('presentation_scope')
            if current_scope and incoming_scope and current_scope != incoming_scope:
                return jsonify({'error': 'Presentation scope does not match', 'error_code': 'PRESENTATION_SCOPE_MISMATCH'}), 409
            if current_scope:
                updates['project_data']['presentation_scope'] = current_scope
            if pres.get('draft_id'):
                updates['draft_id'] = pres['draft_id']
                updates['project_data']['draftId'] = pres['draft_id']
                updates['project_data']['draft_id'] = pres['draft_id']
            else:
                updates['draft_id'] = (updates['project_data'].get('draftId')
                                       or updates['project_data'].get('draft_id'))
            # ISS-015: projectData is stored draft data — a section the caller
            # cannot see must survive the save unchanged, exactly like the
            # project-draft save path enforces.
            forbidden_sections, _restored = _enforce_draft_field_sections(
                updates['project_data'], current_project, None, None)
            if forbidden_sections:
                return jsonify({
                    'error': 'لا تملك صلاحية تعديل الأقسام: ' + '، '.join(forbidden_sections),
                    'error_code': 'SECTION_FORBIDDEN',
                    'sections': forbidden_sections}), 403

        if 'slides_data' in updates:
            project_data = updates.get('project_data')
            if not isinstance(project_data, dict):
                try:
                    project_data = json.loads(pres.get('project_data') or '{}')
                except (TypeError, ValueError):
                    project_data = {}
            update_branding = db.get_branding(g.tenant_id) or {}
            render_project_data = copy.deepcopy(project_data)
            _prepare_generation_logo_context(render_project_data, update_branding, g.tenant_id)
            save_stage = 'renumber'
            updates['slides_data'] = slide_engine.renumber_presentation_slides(
                updates['slides_data'], branding=update_branding,
                project_data=render_project_data, tenant_id=g.tenant_id,
                creative_images=_presentation_creative_images(render_project_data, g.tenant_id),
            )
            updates['slide_count'] = len(updates['slides_data'])

        save_stage = 'history'
        details = []
        action = 'تعديل العرض'
        if 'title' in updates and updates['title'] != pres.get('title'):
            details.append(f'عنوان العرض: من «{pres.get("title") or "بدون"}» إلى «{updates["title"]}»')
        if 'project_data' in updates:
            try:
                old_project_data = json.loads(pres.get('project_data') or '{}')
            except (TypeError, ValueError):
                old_project_data = {}
            details.extend(change_tracking.describe_draft_changes(
                old_project_data, updates['project_data'],
                id_names=_draft_change_id_names()))
        if 'slides_data' in updates:
            current_slides = change_tracking.parse_slides(pres.get('slides_data'))
            details.extend(change_tracking.describe_slide_changes(current_slides, updates['slides_data']))
            action = 'تعديل الشرائح'
        if 'status' in updates and updates['status'] != pres.get('status'):
            details.append(f'حالة العرض: من «{pres.get("status") or "مسودة"}» إلى «{updates["status"]}»')
        if post_approval_reason:
            details.append(f'تعديل بعد الاعتماد — السبب: {post_approval_reason}')
        updates.pop('slide_count', None)
        if data.get('operation') == 'generation':
            action = 'توليد العرض'
        save_stage = 'commit'
        result = _commit_presentation_state(
            g.tenant_id, pres_id, expected_revision=expected_revision,
            source=source, action=action, details=details + provenance_details, **updates)
    except db.PresentationRevisionConflict:
        raise
    except (LookupError, ValueError) as error:
        return jsonify({'error': str(error)}), 400
    except Exception as exc:
        return _presentation_save_failure(save_stage, exc)
    return jsonify(_presentation_revision_response(result))
