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


def _cancelled_run_response(partial=None):
    """The answer an inline generation gives when its run was stopped.

    It is a stop, not a failure: the client reads ``cancelled`` and shows the
    task as stopped, and whatever the request already produced rides in
    ``partial`` instead of being thrown away.
    """
    payload = run_control.cancelled_job_patch()
    if partial is not None:
        payload['partial'] = partial
    return jsonify(payload), 409


@app.before_request
def _bind_request_run():
    """Put an inline request under the run handle its client sent.

    A queued job is stoppable because the server issued its id. A request that
    does the paid work inline — a set of images, a landmark sweep, one text —
    used to be unstoppable: the client's stop had no handle to name, so the
    work ran to the end even after the card was closed. The client now brings
    the id in ``X-Run-Id``; binding it here makes every provider call inside
    the request refuse to start once that id is cancelled.
    """
    if request.method != 'POST':
        return None
    run_id = run_control.request_run_id(request.headers.get(run_control.REQUEST_RUN_HEADER))
    if not run_id:
        return None
    run_control.bind_run(run_id, None)
    return None


@app.teardown_request
def _unbind_request_run(_exc=None):
    """The thread goes back to the pool unbound, so the next request starts clean."""
    run_control.unbind_run()
    return None


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
