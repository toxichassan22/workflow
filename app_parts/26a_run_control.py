# Run control — one stop button for every long generation.
#
# Every long operation runs under a run handle (the job id the client already
# holds). The client posts that handle here to stop it; the marker file the AI
# layer reads lives in the run's own tenant namespace, so a handle from
# another company can never be stopped from this one.
#
# Stopping a run never deletes what it already produced: the slide run keeps
# its checkpoint and stays resumable, and an image run keeps the slots it
# already generated.


RUN_CANCEL_PERMISSIONS = ('create_presentation', 'generate_images', 'generate_maps')


def _run_cancel_allowed():
    """Cancelling needs the same authority as starting a generation."""
    if getattr(g, 'is_admin', False):
        return True
    if getattr(g, 'user_id', None) is None:
        # The company admin — the tenant-direct session.
        return True
    permissions = getattr(g, 'user_permissions', None) or {}
    return any(permissions.get(key) for key in RUN_CANCEL_PERMISSIONS)


@app.route('/api/runs/<run_id>/cancel', methods=['POST'])
@require_auth
def api_cancel_run(run_id):
    """Ask one run to stop before it spends the next token."""
    if not _run_cancel_allowed():
        return jsonify({
            'success': False,
            'error': 'الصلاحية غير كافية لإيقاف المهمة',
            'error_code': 'PERMISSION_DENIED',
        }), 403
    if run_control.cancel_path(run_id, g.tenant_id) is None:
        return jsonify({
            'success': False,
            'error': 'معرف المهمة غير صالح',
            'error_code': 'RUN_INVALID',
        }), 400
    if not run_control.cancel_run(run_id, g.tenant_id):
        return jsonify({
            'success': False,
            'error': 'تعذر تسجيل طلب الإيقاف',
            'error_code': 'RUN_CANCEL_FAILED',
        }), 500
    return jsonify({
        'success': True,
        'runId': run_id,
        'cancelRequested': True,
        'message': 'تم تسجيل طلب الإيقاف',
    })


@app.route('/api/runs/<run_id>', methods=['GET'])
@require_auth
def api_run_status(run_id):
    """Whether a run was asked to stop. The client polls this to settle its UI."""
    if run_control.cancel_path(run_id, g.tenant_id) is None:
        return jsonify({
            'success': False,
            'error': 'معرف المهمة غير صالح',
            'error_code': 'RUN_INVALID',
        }), 400
    return jsonify({
        'success': True,
        'runId': run_id,
        'cancelled': run_control.is_run_cancelled(run_id, g.tenant_id),
    })
