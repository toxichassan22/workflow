import best_use_contract
import best_use_workflow
import best_use_explore
import best_use_regulations
import best_use_prices


_BEST_USE_ERRORS.update({
    'BEST_USE_WRONG_MODE': 'العملية لا تخص وضع أفضل استخدام النشط.',
    'BEST_USE_EVIDENCE_REQUIRED': 'السماح التنظيمي المستقل غير مثبت من المستندات.',
    'BEST_USE_STAGE_REQUIRED': 'بيانات المرحلة السابقة غير متوفرة أو غير صالحة.',
    'BEST_USE_ARTIFACT_CHANGED': 'نسخة المحتوى تغيرت منذ آخر قراءة.',
    'BEST_USE_SEARCH_FAILED': 'تعذر إجراء مسح أسعار حي موثق.',
})
_BEST_USE_EXPLORE_KEYS = {'best_use_explore_data', 'best_use_explore_chat', 'best_use_mode'}
db.GENERATION_INPUT_EXCLUDED_KEYS.update(_BEST_USE_EXPLORE_KEYS)
db.DRAFT_COPY_STRIPPED_KEYS.update(_BEST_USE_EXPLORE_KEYS)
slide_engine.PROMPT_SKIPPED_KEYS.update(_BEST_USE_EXPLORE_KEYS)
DRAFT_FIELD_SECTION_BLOBS.update({key: best_use.SECTION_KEY for key in _BEST_USE_EXPLORE_KEYS})
SECTION_SNAPSHOT_BLOBS[best_use.SECTION_KEY].extend(['best_use_explore_data', 'best_use_mode'])
SECTION_SNAPSHOT_EXCLUDED_KEYS.add('best_use_explore_chat')


def _best_use_active_mode(project):
    return (project or {}).get('best_use_mode') or 'guided'


def _best_use_required(project):
    if _best_use_active_mode(project) == 'guided':
        return best_use.section_required(project)
    state = best_use_contract.read_object((project or {}).get('best_use_explore_data'))
    return any(isinstance(state.get(key), dict) and state[key].get('id') and not state[key].get('rejected')
               for key in best_use_workflow.ARTIFACTS)


def _best_use_sanitize_explore(project, stored):
    for key in _BEST_USE_EXPLORE_KEYS:
        if key in (stored or {}):
            project[key] = copy.deepcopy(stored[key])
        else:
            project.pop(key, None)
    if project.get('best_use_explore_data'):
        best_use_workflow.refresh(project)


def _best_use_explore_draft(data, applying=False, mode_change=False):
    if not isinstance(data, dict):
        return None, (jsonify({'success': False, 'error_code': 'INVALID_REQUEST'}), 400)
    draft_id = data.get('draftId')
    if not isinstance(draft_id, str) or not draft_id or len(draft_id) > 120:
        return None, (jsonify({'success': False, 'error_code': 'DRAFT_ID_REQUIRED'}), 400)
    required = ('land_croquis', 'location', best_use.SECTION_KEY)
    if applying:
        required += ('section-financial-calc',)
    if any(_section_key_forbidden(key) for key in required):
        return None, (jsonify({'success': False, 'error_code': 'SECTION_FORBIDDEN'}), 403)
    draft, error = _versioned_draft_or_404(draft_id)
    if error:
        return None, (jsonify({'success': False, **error}), 404)
    if db.proposal_status_is_locked(db.normalize_proposal_status(draft.get('status'))):
        return None, _draft_locked_response(draft.get('status'))
    expected = data.get('expectedRevision')
    if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int) or expected != draft.get('revision')):
        return None, (jsonify({'success': False, 'error_code': 'DRAFT_REVISION_CONFLICT',
                               'currentRevision': draft.get('revision')}), 409)
    if not mode_change and _best_use_active_mode(draft.get('draft_data')) != 'explore':
        result, status = _best_use_error('BEST_USE_WRONG_MODE', 409)
        return None, (jsonify(result), status)
    if not mode_change:
        _best_use_merge_fields(draft, data, best_use_workflow.SOURCE_FIELDS)
    return draft, None


def _best_use_explore_response(draft, applied=False):
    project = draft.get('draft_data') or {}
    result = {'success': True, 'draftId': draft['id'], 'revision': draft.get('revision'),
              'bestUseMode': _best_use_active_mode(project),
              'explore': best_use_contract.read_object(project.get('best_use_explore_data')),
              'exploreChat': best_use_contract.read_object(project.get('best_use_explore_chat')),
              'componentsApplied': applied, 'sectionStatuses': {key: value for key, value in
                  (draft.get('section_statuses') or {}).items() if key in
                  {best_use.SECTION_KEY, 'section-financial-calc', 'section-executive-content',
                   'land_croquis', 'location'}}}
    if applied:
        result.update(financialModel=project.get('financial_study_model') or {},
                      projectComponentsData=project.get('project_components_data') or '[]',
                      financialCalcData=project.get('financial_calc_data') or '{}')
    return result


def _best_use_explore_store(draft, project, statuses, action, applied=False):
    try:
        db.save_project_draft(g.tenant_id, draft.get('user_id') or _project_draft_actor_id(), project,
                              statuses, draft_id=draft['id'], expected_revision=draft.get('revision'), existing_row=draft)
    except db.DraftRevisionConflict as conflict:
        return {'success': False, 'error_code': 'DRAFT_REVISION_CONFLICT',
                'currentRevision': conflict.current_revision}, 409
    except db.DraftLocked as locked:
        response = app.make_response(_draft_locked_response(locked.status))
        return response.get_json(), response.status_code
    try:
        # The request fields were just persisted: a gated section whose content
        # drifted from its approved snapshot can no longer stand as approved.
        _void_stale_section_approvals(
            g.tenant_id, draft['id'], project, statuses=statuses)
    except Exception:
        pass
    _record_change('draft', draft['id'], action, [action], source='ai' if action.startswith('توليد') else 'manual')
    _bill_tenant_unbilled_usage_async(g.tenant_id)
    return _best_use_explore_response(db.get_project_draft_by_id(g.tenant_id, draft['id']), applied), 200


def _best_use_explore_readiness(draft):
    project = draft.get('draft_data') or {}
    missing = best_use_workflow.missing_inputs(project, draft.get('section_statuses') or {})
    if not _best_use_documents_backed(draft):
        missing.append('croquis')
    gated = ('land_croquis', 'location')
    states = _section_gate_states(draft, gated)
    for key in states:
        missing.append(key)
    if not missing:
        return None
    return _best_use_error('BEST_USE_PREREQUISITES_REQUIRED', missing=list(dict.fromkeys(missing)),
                           sectionStatuses=_section_gate_statuses(draft, gated), sectionStates=states)


@app.route('/api/best-use/mode', methods=['POST'])
@require_permission('create_presentation')
def api_best_use_mode():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or not isinstance(data.get('mode'), str) or data['mode'] not in {'guided', 'explore'}:
        return jsonify({'success': False, 'error_code': 'BEST_USE_MODE_REQUIRED'}), 400
    draft, error = _best_use_explore_draft(data, mode_change=True)
    if error is not None:
        return error
    if data['mode'] == 'guided' and any(_section_key_forbidden(key) for key in _BEST_USE_SOURCE_SECTIONS):
        return jsonify({'success': False, 'error_code': 'SECTION_FORBIDDEN'}), 403
    if (draft.get('section_statuses') or {}).get(best_use.SECTION_KEY) == 'approved':
        result, status = _best_use_error('BEST_USE_APPROVAL_LOCKED', 409)
        return jsonify(result), status
    project = copy.deepcopy(draft.get('draft_data') or {})
    if _best_use_active_mode(project) == data['mode']:
        return jsonify(_best_use_explore_response(draft))
    # A mode switch flips the server-owned flag only. It is not an input edit:
    # the guided proposal and the explore artifacts keep their approval and
    # freshness — real input changes are caught by the save-path sanitizers,
    # which re-verify hashes and mark inputsChanged only when they diverge.
    explore = best_use_contract.read_object(project.get('best_use_explore_data'))
    explore.setdefault('mode', 'explore')
    project.update(best_use_mode=data['mode'], best_use_explore_data=explore)
    # Heal stale markers left over from earlier behaviour: artifacts whose
    # hashes still verify are current again, genuinely stale ones stay flagged.
    best_use_workflow.refresh(project)
    guided = best_use.read_object(project.get('best_use_data'))
    if guided.get('id') and best_use.proposal_current(project, guided):
        guided.pop('inputsChanged', None)
        project['best_use_data'] = guided
    statuses = dict(draft.get('section_statuses') or {})
    if _best_use_required(project):
        statuses[best_use.SECTION_KEY] = 'draft'
    else:
        statuses.pop(best_use.SECTION_KEY, None)
    result, status = _best_use_explore_store(draft, project, statuses, 'تغيير وضع أفضل استخدامات')
    if data['mode'] == 'guided':
        result['bestUse'] = guided
        result['chat'] = best_use.read_object(project.get('best_use_chat'))
    return jsonify(result), status
