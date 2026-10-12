# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Designer agent — failure journal
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Every task that ends «تعذّرت» leaves one JSON record: the request, the task,
# each attempt's raw reason and feedback, the source slide and the rejected
# result. Before this a client-reported failure could not be diagnosed: the job
# file kept one reason code and was overwritten by the final response, nothing
# reached the server log, and the only way to learn why a check fired was to
# reproduce the client's deck by hand.
#
# GET /api/admin/designer-failures lists recent records with a count per reason
# code, so a new failure class shows up on the platform side before a client
# reports it. The detail route replays the verification against the current
# build — after a fix ships, an old record reads «would pass now».
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from collections import Counter

_AGENT_FAILURE_NS = '.designer_agent_failures'
_AGENT_FAILURE_KEEP = 300
_AGENT_FAILURE_HTML_CAP = 120000
_AGENT_FAILURE_ID_RE = re.compile(r'^\d{13}-[0-9a-f]{6}$')
_AGENT_FAILURE_TENANT_RE = re.compile(r'^[A-Za-z0-9_-]{1,80}$')
_AGENT_FAILURE_BASE64_RE = re.compile(r'data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+')


def _agent_failure_dir(tenant_id):
    tenant_id = str(tenant_id or '')
    if not _AGENT_FAILURE_TENANT_RE.match(tenant_id):
        return None
    return os.path.join(UPLOADS_DIR, _AGENT_FAILURE_NS, tenant_id)


def _agent_failure_html(html):
    """Slide HTML small enough to keep: inline images carry no fact the
    verification reads, so they are replaced; the text stays verbatim."""
    return _AGENT_FAILURE_BASE64_RE.sub('data:image/omitted', str(html or ''))[:_AGENT_FAILURE_HTML_CAP]


def _agent_failure_request_text(ctx, task):
    return '\n'.join(str(part) for part in (
        ctx.get('message'), task.get('_instruction'), task.get('exact_text')) if part)


def _agent_record_failure(ctx, task, reason, before_htmls, attempts):
    """Persist one failed task. Never raises: the journal must not turn a
    failed task into a failed turn."""
    try:
        folder = _agent_failure_dir(ctx.get('tenant_id'))
        if not folder:
            return None
        failure_id = f'{int(time.time() * 1000):013d}-{os.urandom(3).hex()}'
        user_id = user_name = None
        if has_request_context():
            user_id = getattr(g, 'user_id', None)
            user_name = getattr(g, 'user_name', None)
        data = ctx.get('data') if isinstance(ctx.get('data'), dict) else {}
        record = {
            'id': failure_id,
            'at': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec='seconds'),
            'build': _build_commit(),
            'tenantId': str(ctx.get('tenant_id')),
            'presentationId': ctx.get('presentation_id'),
            'draftId': data.get('draftId'),
            'jobId': ctx.get('job_id'),
            'userId': user_id,
            'userName': user_name,
            'workerModel': DESIGNER_AGENT_WORKER_MODEL,
            'message': str(ctx.get('message') or '')[:2000],
            'task': {key: task.get(key) for key in (
                'n', 'op', 'slides', 'titles', 'instruction', 'style_brief', 'params',
                'parts', 'target_count', 'after', 'title', 'type', 'exact_text')},
            'workerInstruction': str(task.get('_instruction') or '')[:4000],
            'requestText': _agent_failure_request_text(ctx, task)[:6000],
            'allowedNumbers': sorted(str(n) for n in (ctx.get('superseded_numbers') or ())),
            'reason': str(reason or '')[:400],
            'reasonCodes': designer_agent_ops.reason_codes(reason),
            'reasonText': designer_agent_ops.failure_reason_text(reason),
            'sourceHtml': [_agent_failure_html(html) for html in before_htmls or []],
            'attempts': [{
                'attempt': item.get('attempt'),
                'reason': item.get('reason'),
                'feedback': item.get('feedback') or '',
                'resultHtml': [_agent_failure_html(html) for html in item.get('resultHtml') or []],
            } for item in attempts or []],
        }
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, failure_id + '.json')
        with open(path + '.tmp', 'w', encoding='utf-8') as fh:
            json.dump(record, fh, ensure_ascii=False)
        os.replace(path + '.tmp', path)
        names = sorted(name for name in os.listdir(folder) if name.endswith('.json'))
        for name in names[:-_AGENT_FAILURE_KEEP]:
            try:
                os.unlink(os.path.join(folder, name))
            except OSError:
                pass
        print(f"[DESIGNER-AGENT] task {task.get('n')} ({task.get('op')}) failed after "
              f"{len(attempts or [])} attempt(s): {record['reason']} — journal {failure_id}")
        return failure_id
    except Exception as exc:
        print(f"[DESIGNER-AGENT] failure journal write failed: {exc}")
        return None


def _agent_read_failure(tenant_id, failure_id):
    folder = _agent_failure_dir(tenant_id)
    if not folder or not _AGENT_FAILURE_ID_RE.match(str(failure_id or '')):
        return None
    try:
        with open(os.path.join(folder, f'{failure_id}.json'), encoding='utf-8') as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _agent_replay_failure(record):
    """Re-run the verification on the last rejected result with THIS build's
    checks. Layout measurement needs a browser and is not replayed."""
    task = record.get('task') if isinstance(record.get('task'), dict) else {}
    op = str(task.get('op') or '')
    result = next((item.get('resultHtml') for item in reversed(record.get('attempts') or [])
                   if isinstance(item, dict) and item.get('resultHtml')), None)
    if not op or not result:
        return None
    ok, reasons = designer_agent_ops.verify_task_result(
        op, record.get('sourceHtml') or [], result,
        allowed_numbers=set(record.get('allowedNumbers') or []),
        request_text=record.get('requestText') or '')
    return {'ok': ok, 'reasons': reasons,
            'reasonText': designer_agent_ops.failure_reason_text(';'.join(reasons)) if reasons else ''}


@app.route('/api/admin/designer-failures', methods=['GET'])
@require_admin
def api_admin_designer_failures():
    """Recent failed designer tasks, newest first, with a count per reason
    code over the listed window. Summaries only — slide HTML stays in the
    per-failure record."""
    tenant_filter = str(request.args.get('tenantId') or '').strip()
    code_filter = str(request.args.get('reason') or '').strip()
    try:
        limit = max(1, min(int(request.args.get('limit') or 50), 500))
    except (TypeError, ValueError):
        limit = 50
    root = os.path.join(UPLOADS_DIR, _AGENT_FAILURE_NS)
    try:
        tenant_dirs = os.listdir(root)
    except OSError:
        tenant_dirs = []
    entries = []
    for tenant_dir in tenant_dirs:
        if not _AGENT_FAILURE_TENANT_RE.match(tenant_dir) or (tenant_filter and tenant_dir != tenant_filter):
            continue
        try:
            names = os.listdir(os.path.join(root, tenant_dir))
        except OSError:
            continue
        entries.extend((name[:-5], tenant_dir) for name in names
                       if name.endswith('.json') and _AGENT_FAILURE_ID_RE.match(name[:-5]))
    entries.sort(reverse=True)
    by_reason = Counter()
    tenant_names = {}
    failures = []
    for failure_id, tenant_dir in entries:
        if len(failures) >= limit:
            break
        record = _agent_read_failure(tenant_dir, failure_id)
        if not record:
            continue
        codes = record.get('reasonCodes') or []
        if code_filter and code_filter not in codes:
            continue
        by_reason.update(codes)
        if tenant_dir not in tenant_names:
            tenant = db.get_tenant_by_id(tenant_dir) or {}
            tenant_names[tenant_dir] = tenant.get('company_name') or ''
        task = record.get('task') if isinstance(record.get('task'), dict) else {}
        failures.append({
            'id': failure_id, 'tenantId': tenant_dir, 'tenantName': tenant_names[tenant_dir],
            'at': record.get('at'), 'build': record.get('build'),
            'presentationId': record.get('presentationId'),
            'op': task.get('op'), 'titles': task.get('titles') or [],
            'message': str(record.get('message') or '')[:300],
            'reason': record.get('reason'), 'reasonCodes': codes,
            'reasonText': record.get('reasonText'),
            'attempts': len(record.get('attempts') or []),
        })
    return jsonify({'success': True, 'failures': failures, 'total': len(entries),
                    'byReason': dict(by_reason.most_common())})


@app.route('/api/admin/designer-failures/<tenant_id>/<failure_id>', methods=['GET'])
@require_admin
def api_admin_designer_failure(tenant_id, failure_id):
    """One full failure record plus a replay of its verification on the
    current build."""
    record = _agent_read_failure(tenant_id, failure_id)
    if not record:
        return jsonify({'success': False, 'error': 'سجل الإخفاق غير موجود'}), 404
    try:
        replay = _agent_replay_failure(record)
    except Exception as exc:
        replay = {'ok': False, 'reasons': [f'replay_failed:{type(exc).__name__}']}
    return jsonify({'success': True, 'failure': record, 'replay': replay})
