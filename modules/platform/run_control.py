"""Run control — the cancel registry every long generation shares.

One "run" is one paid operation: a slide job, a slide plan, a market study, a
single visual-concept image, one chat turn. When the client asks the server to
stop a run, the server must honour it *before* it spends the next token —
otherwise a user who notices the wrong prompt halfway through pays for the
whole thing twice.

The registry is a directory of marker files, not a database row. The marker is
written by one worker and read by another, and a marker file can never be lost
by a job-file rewrite racing it — the same reason the designer agent keeps its
own ``.cancel`` file next to its job file.

Layout::

    <root>/<tenant>/<run_id>.cancel

The root comes from a provider so the app can point the registry at the
uploads directory it actually uses; tests move that directory, and the
registry has to follow it instead of hard-coding a path.

Usage in a worker thread::

    run_control.bind_run(job_id, tenant_id)
    try:
        ...
    finally:
        run_control.unbind_run()

and in the AI layer::

    if run_control.run_is_cancelled(usage_ctx):
        return run_control.cancelled_response()

A cancelled call never reaches the provider, so it costs nothing. A call that
was already in flight cannot be un-billed — the saving always comes from the
work that never starts.
"""
import os
import re
import threading
import time
import uuid

CANCELLED_ERROR_CODE = 'RUN_CANCELLED'
CANCELLED_MESSAGE = 'أُلغيت المهمة قبل تنفيذها'

# A run id is an opaque handle the client already holds (a job id). It is
# never a path component without this check.
_RUN_ID_RE = re.compile(r'[A-Za-z0-9_-]{6,80}\Z')
# Tenant ids come from the database, but the registry still refuses anything
# that could escape its own directory.
_TENANT_RE = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')

# How often a streaming call re-checks the registry. The marker is a stat()
# call, so checking on every chunk would be wasteful; a cancelled run still
# stops within this window.
CANCEL_CHECK_INTERVAL = 0.4

_ROOT_PROVIDER = None
_THREAD = threading.local()


def set_root_provider(provider):
    """Point the registry at a directory. The provider is called per lookup so
    a test that moves the uploads directory keeps the registry with it."""
    global _ROOT_PROVIDER
    _ROOT_PROVIDER = provider


def _default_root():
    # <repo>/modules/platform/run_control.py -> <repo>/uploads/.cancel
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(repo_root, 'uploads', '.cancel')


def _root():
    provider = _ROOT_PROVIDER
    if provider is not None:
        try:
            root = provider()
        except Exception:
            root = None
        if root:
            return str(root)
    return _default_root()


def new_run_id():
    """A fresh run handle. The client keeps it and can cancel with it."""
    return uuid.uuid4().hex


def _valid_run_id(run_id):
    return bool(run_id) and bool(_RUN_ID_RE.match(str(run_id)))


def _tenant_key(tenant_id):
    if tenant_id is None:
        return None
    text = str(tenant_id).strip()
    if not text or not _TENANT_RE.match(text):
        return None
    return text


def cancel_path(run_id, tenant_id=None):
    """The marker path for one run, or None when the handle is unusable."""
    if not _valid_run_id(run_id):
        return None
    tenant = _tenant_key(tenant_id)
    if tenant is None:
        return None
    return os.path.join(_root(), tenant, f'{run_id}.cancel')


def cancel_run(run_id, tenant_id=None):
    """Ask a run to stop. Returns False when the handle is unusable."""
    path = cancel_path(run_id, tenant_id)
    if not path:
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(str(time.time()))
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        return True
    except OSError:
        return False


def is_run_cancelled(run_id, tenant_id=None):
    path = cancel_path(run_id, tenant_id)
    if not path:
        return False
    try:
        return os.path.isfile(path)
    except OSError:
        return False


def clear_run_cancel(run_id, tenant_id=None):
    """Drop a stale marker so a reused handle starts clean."""
    path = cancel_path(run_id, tenant_id)
    if not path:
        return False
    try:
        if os.path.isfile(path):
            os.unlink(path)
        return True
    except OSError:
        return False


def bind_run(run_id, tenant_id=None):
    """Claim the current thread for one run. Job workers call this first."""
    _THREAD.run_id = run_id if _valid_run_id(run_id) else None
    _THREAD.tenant_id = tenant_id
    _THREAD.last_check = 0.0
    _THREAD.checked_run = None


def unbind_run():
    _THREAD.run_id = None
    _THREAD.tenant_id = None
    _THREAD.last_check = 0.0
    _THREAD.checked_run = None


def current_run():
    """The run this thread is executing, as (run_id, tenant_id)."""
    return (getattr(_THREAD, 'run_id', None), getattr(_THREAD, 'tenant_id', None))


def _resolve_run(usage_ctx=None):
    run_id = None
    tenant_id = None
    if isinstance(usage_ctx, dict):
        run_id = usage_ctx.get('run_id')
        tenant_id = usage_ctx.get('tenant_id')
    if not run_id:
        run_id = getattr(_THREAD, 'run_id', None)
    if not tenant_id:
        tenant_id = getattr(_THREAD, 'tenant_id', None)
    return run_id, tenant_id


def _check_due(run_id, interval=None):
    if interval is None:
        interval = CANCEL_CHECK_INTERVAL
    now = time.monotonic()
    if getattr(_THREAD, 'checked_run', None) != run_id:
        # A new run in this thread must be checked immediately — the previous
        # run's timestamp must never suppress the first check of this one.
        _THREAD.checked_run = run_id
        _THREAD.last_check = 0.0
    last = getattr(_THREAD, 'last_check', 0.0)
    if now - last < interval:
        return False
    _THREAD.last_check = now
    return True


def run_is_cancelled(usage_ctx=None, throttle=False):
    """True when the run behind this call was cancelled.

    The explicit ``run_id`` in the metering context wins; otherwise the
    thread's bound run is used, which is how a job worker covers every AI
    call it makes without threading a handle through every signature.
    """
    run_id, tenant_id = _resolve_run(usage_ctx)
    if not run_id:
        return False
    if throttle and not _check_due(run_id):
        return False
    return is_run_cancelled(run_id, tenant_id)


def current_run_cancelled():
    """True when the run this thread is executing was cancelled."""
    run_id, tenant_id = current_run()
    if not run_id:
        return False
    return is_run_cancelled(run_id, tenant_id)


def run_can_be_cancelled(usage_ctx=None):
    """True when a run handle is attached to this call.

    A call without a run cannot be stopped, so the caller may take the plain
    path. A call with one can be cut in the middle, so it must be streamed.
    """
    run_id, _tenant_id = _resolve_run(usage_ctx)
    return bool(run_id)


def cancelled_response(partial=None):
    """The shared answer for a call that must not reach the provider."""
    payload = {
        'error': {'message': CANCELLED_MESSAGE},
        'error_code': CANCELLED_ERROR_CODE,
        'errorCode': CANCELLED_ERROR_CODE,
        'cancelled': True,
        'success': False,
    }
    if partial is not None:
        payload['partial'] = partial
    return payload


class RunCancelledError(Exception):
    """The run was stopped before this call reached the provider.

    Duck-typed with the app's fatal AI errors: the slide engine re-raises any
    exception carrying ``fatal_ai_error`` instead of quietly shipping its
    deterministic fallback, and a cancelled run must never be replaced by a
    fallback slide.
    """

    fatal_ai_error = True
    error_code = CANCELLED_ERROR_CODE
    http_status = 409

    def __init__(self, message=None):
        super().__init__(str(message or CANCELLED_MESSAGE))
        self.ai_message = str(message or CANCELLED_MESSAGE)


def raise_if_cancelled(response):
    """Turn a cancelled provider answer into the exception the callers expect.

    Every generation path must stop at a cancelled answer instead of retrying
    it or falling back to a deterministic page: the user asked for the work to
    stop, and a fallback would be a slide nobody asked for.
    """
    if isinstance(response, dict) and response.get('cancelled'):
        raise RunCancelledError((response.get('error') or {}).get('message'))
    return response


def attach_run(usage_ctx, run_id, tenant_id=None):
    """Copy a metering context with an explicit run handle attached."""
    ctx = dict(usage_ctx) if isinstance(usage_ctx, dict) else {}
    if _valid_run_id(run_id):
        ctx['run_id'] = run_id
    if tenant_id is not None:
        ctx['tenant_id'] = tenant_id
    return ctx
