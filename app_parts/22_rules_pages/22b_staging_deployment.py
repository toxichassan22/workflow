def _staging_deploy_authorized():
    expected = os.environ.get('DEPLOY_WEBHOOK_SECRET_STAGING') or os.environ.get('DEPLOY_WEBHOOK_SECRET')
    supplied = request.headers.get('X-Deploy-Secret', '')
    return bool(expected and supplied and secrets.compare_digest(supplied.encode(), expected.encode()))


def _staging_deploy_app_dir():
    return os.environ.get('STAGING_APP_DIR') or '/home/landloom/proposal-generator-staging'


@app.route('/api/deploy-webhook-staging', methods=['GET', 'POST'])
def deploy_webhook_staging():
    """Staging counterpart of deploy_webhook: deploys origin/lab into the
    separate proposal-generator-staging directory. Production paths are never
    touched here, so lab experiments cannot overwrite client data."""
    env_secret = os.environ.get('DEPLOY_WEBHOOK_SECRET_STAGING') or os.environ.get('DEPLOY_WEBHOOK_SECRET')
    if not env_secret:
        return jsonify({'error': 'DEPLOY_WEBHOOK_SECRET not configured in environment'}), 403

    secret = request.args.get('secret') or request.headers.get('X-Deploy-Secret') or (request.json.get('secret') if (request.is_json and request.json) else None)
    if not secret or not secrets.compare_digest(str(secret).encode(), env_secret.encode()):
        return jsonify({'error': 'Unauthorized'}), 401

    requested_commit = request.args.get('commit') or (
        request.json.get('commit') if (request.is_json and request.json) else None
    )
    if requested_commit and not re.fullmatch(r'[0-9a-fA-F]{40}', str(requested_commit)):
        return jsonify({'error': 'Invalid deployment commit'}), 400
    request_id = request.headers.get('X-Deploy-Request-ID') or _uuid.uuid4().hex
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', request_id):
        return jsonify({'error': 'Invalid deployment request ID'}), 400

    app_dir = _staging_deploy_app_dir()
    deploy_script = os.path.join(app_dir, 'deploy-staging.sh')
    if not os.path.isfile(deploy_script):
        return jsonify({'error': 'deploy-staging.sh not found'}), 404
    if staging_deploy_runtime.read_status(app_dir, request_id):
        return jsonify({'error': 'Deployment request already exists', 'request_id': request_id}), 409

    log_fh = None
    try:
        if not staging_deploy_runtime.claim_request(app_dir, request_id):
            return jsonify({'error': 'Deployment request already exists', 'request_id': request_id}), 409
        import subprocess
        command = ['bash', deploy_script]
        if requested_commit:
            command.append(str(requested_commit))
        staging_deploy_runtime.write_status(app_dir, requested_commit or 'latest', 'queued', 'start',
                                           request_id=request_id)
        deploy_log_path = os.path.join(app_dir, 'deploy.log')
        log_fh = open(deploy_log_path, 'a', encoding='utf-8')
        log_fh.write(f"\n--- Staging deployment triggered at {db._utcnow().isoformat()} for commit {requested_commit or 'latest'} ---\n")
        log_fh.flush()
        environment = dict(os.environ, STAGING_DEPLOY_REQUEST_ID=request_id,
                           STAGING_APP_DIR=app_dir)
        subprocess.Popen(command, start_new_session=True, env=environment,
                         stdout=log_fh, stderr=subprocess.STDOUT)
        return jsonify({'status': 'Staging deployment triggered successfully',
                        'target': 'staging', 'expected_commit': requested_commit,
                        'request_id': request_id, 'timestamp': db._utcnow().isoformat()}), 200
    except Exception as exc:
        error = staging_deploy_runtime.sanitize_error(str(exc))
        staging_deploy_runtime.write_status(app_dir, requested_commit or 'latest', 'failed', 'start',
                                           exit_code=1, request_id=request_id, error=error)
        return jsonify({'error': error, 'request_id': request_id}), 500
    finally:
        if log_fh is not None:
            log_fh.close()


@app.route('/api/deploy-status-staging/<request_id>', methods=['GET'])
def staging_deploy_status(request_id):
    if not _staging_deploy_authorized():
        return jsonify({'error': 'Unauthorized'}), 401
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', request_id):
        return jsonify({'error': 'Invalid deployment request ID'}), 400
    status = staging_deploy_runtime.read_status(_staging_deploy_app_dir(), request_id)
    if not status:
        return jsonify({'error': 'Deployment request not found'}), 404
    response = jsonify(status)
    response.headers['Cache-Control'] = 'no-store'
    return response


def _read_deploy_status():
    """Outcome of the last deploy script run, when the script recorded one.

    deploy-staging.sh writes .deploy_status next to .deployed_commit on every
    exit, so a half-finished deploy stops looking like a successful old one.
    Only the step name and status ride /health — never stderr or env details.
    """
    data = staging_deploy_runtime.read_status(os.path.dirname(DEPLOYMENT_MARKER_PATH))
    if not data:
        return None
    return {key: data.get(key) for key in
            ('commit', 'status', 'step', 'exit_code', 'finished_at')}
