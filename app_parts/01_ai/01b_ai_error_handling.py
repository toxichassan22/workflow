
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Deterministic AI refusals — wallet / key / trial
#
# A provider call can fail for a deterministic reason the retry/fallback layers
# used to bury behind a vague «تعذر التوليد»: the company wallet or its provider
# key ran out of credit, the trial expired, or the managed key is missing. These
# helpers carry that refusal through response dicts (`'fatal': True` +
# `error_code` + `http_status`) and exceptions (duck-typed `fatal_ai_error`)
# until a route turns it into the client-facing HTTP response — so a balance
# failure always reads as a balance failure.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class FatalAICallError(RuntimeError):
    """A deterministic AI refusal raised through layers that catch Exception.

    Subclasses RuntimeError so the agent/tool loops that already catch
    RuntimeError keep working; the attrs let _ai_fatal_http_response rebuild
    the structured refusal. The slide engine raises its own lookalike — it
    cannot import app globals — so detection is duck-typed on these attrs.
    """
    fatal_ai_error = True

    def __init__(self, message, error_code=None, http_status=None, provider_message=None):
        super().__init__(str(message or 'تعذر تنفيذ الطلب الآن'))
        self.error_code = error_code
        self.http_status = http_status
        self.ai_message = str(message or '')
        # The provider's own wording stays for cap-retry parsers (the
        # 'can only afford' paths) — never client-facing.
        self.provider_message = str(provider_message or '')


# error_code values a client must see verbatim rather than a generic
# generation-failed banner. INSUFFICIENT_BALANCE comes from the wallet
# preflight; the rest are produced inside the provider call path.
_FATAL_AI_ERROR_CODES = {
    'INSUFFICIENT_BALANCE',
    'INSUFFICIENT_CREDITS',
    'PROVIDER_CREDITS_EXHAUSTED',
    'TRIAL_EXPIRED',
    'NO_TENANT_KEY',
    'TENANT_KEY_CHECK_FAILED',
    'BILLING_CHECK_UNAVAILABLE',
}


def _ai_call_uses_tenant_key(usage_ctx):
    """True when the call resolves to the company's own provider key.

    A managed key's spend cap mirrors the wallet, so its refusal is a wallet
    issue the client fixes by recharging; the platform key's refusal is a
    platform-side funding issue the company cannot fix, and the wording must
    not pretend a recharge helps.
    """
    tid = _tenant_id_from_usage_ctx(usage_ctx)
    if not tid:
        return False
    with _worker_app_context():
        try:
            return bool(db.get_tenant_openrouter_key_raw(tid))
        except Exception:
            return False


def _provider_credit_error_dict(error, status_code, usage_ctx=None):
    """Normalize a provider spend-capacity refusal into a fatal error dict.

    Returns None for unrelated provider failures so callers keep their
    existing wording. A tenant-key refusal lands INSUFFICIENT_CREDITS with
    the company-wallet message; a platform-key refusal still says the AI
    credit ran out (it did) without implying the client's recharge fixes it.
    """
    msg = code = ''
    if isinstance(error, dict):
        msg = str(error.get('message') or '')
        code = str(error.get('code') or '')
    elif error:
        msg = str(error)
    combined = f'{status_code or ""} {code} {msg}'
    credit = _is_company_credit_error(combined)
    disabled = (int(status_code or 0) in (401, 403)
                and 'disabled' in combined.lower())
    if not (credit or disabled):
        return None
    refusal = {'fatal': True, 'provider_message': msg or combined}
    if _ai_call_uses_tenant_key(usage_ctx):
        refusal.update({'message': _COMPANY_CREDIT_EXHAUSTED_MSG,
                        'error_code': 'INSUFFICIENT_CREDITS',
                        'http_status': 402})
    else:
        refusal.update({'message': 'استُنفد رصيد خدمة الذكاء الاصطناعي لدى المزود — جارٍ معالجتها، أعد المحاولة لاحقًا',
                        'error_code': 'PROVIDER_CREDITS_EXHAUSTED',
                        'http_status': 503})
    return refusal


def _ai_fatal_error_dict(response):
    """The fatal-marked error inside a provider response dict, else None."""
    if not isinstance(response, dict):
        return None
    err = response.get('error')
    if isinstance(err, dict) and (
            err.get('fatal') or err.get('error_code') in _FATAL_AI_ERROR_CODES):
        return err
    return None


def _ai_fatal_http_response(exc_or_response):
    """(jsonify, status) for a deterministic AI refusal; None otherwise.

    Routes call this before their generic failure wording so a wallet/key/
    trial refusal reaches the client with its own message, code and status
    instead of collapsing into «تعذر التوليد».
    """
    if isinstance(exc_or_response, dict):
        err = _ai_fatal_error_dict(exc_or_response)
        if err is None and (exc_or_response.get('fatal')
                            or exc_or_response.get('error_code') in _FATAL_AI_ERROR_CODES):
            # A bare error dict (e.g. last_images_api_error()) rather than a
            # provider response that wraps one.
            err = exc_or_response
    elif getattr(exc_or_response, 'fatal_ai_error', False) or \
            getattr(exc_or_response, 'error_code', None) in _FATAL_AI_ERROR_CODES:
        err = {
            'message': getattr(exc_or_response, 'ai_message', '') or str(exc_or_response),
            'error_code': getattr(exc_or_response, 'error_code', None),
            'http_status': getattr(exc_or_response, 'http_status', None),
        }
    else:
        return None
    if not err:
        return None
    code = err.get('error_code')
    status = err.get('http_status')
    if not isinstance(status, int):
        status = (402 if code in ('INSUFFICIENT_BALANCE', 'INSUFFICIENT_CREDITS')
                  else 403 if code == 'TRIAL_EXPIRED' else 503)
    return jsonify({
        'success': False,
        'error': _client_safe_llm_error(err.get('message') or ''),
        'error_code': code or 'GENERATION_FAILED',
    }), status


def _chat_affordable_tokens(response_or_text):
    """The provider's 'can only afford N' budget quote, else None.

    Reads the preserved provider_message on normalized refusals so the
    max_tokens cap-retry loops still see the allowance the provider quoted
    after the client-facing message was reworded.
    """
    if isinstance(response_or_text, dict):
        err = response_or_text.get('error')
        if isinstance(err, dict):
            quoted = _AFFORDABLE_TOKENS_RE.search(str(err.get('provider_message') or ''))
            if quoted:
                return int(quoted.group(1))
            quoted = _AFFORDABLE_TOKENS_RE.search(str(err.get('message') or ''))
            return int(quoted.group(1)) if quoted else None
        quoted = _AFFORDABLE_TOKENS_RE.search(_chat_error_message(response_or_text) or '')
        return int(quoted.group(1)) if quoted else None
    quoted = _AFFORDABLE_TOKENS_RE.search(str(response_or_text or ''))
    return int(quoted.group(1)) if quoted else None


# call_images_api returns None for API shape compatibility, so it records the
# last failure per thread; the route reads it back to answer with the real
# reason instead of the generic «تعذر توليد الصورة».
_IMAGES_API_ERRORS = threading.local()


def last_images_api_error():
    """The error dict the last call_images_api on this thread recorded."""
    err = getattr(_IMAGES_API_ERRORS, 'value', None)
    return err if isinstance(err, dict) else None


def _images_api_fail(error_dict, log=None):
    _IMAGES_API_ERRORS.value = dict(error_dict or {})
    if log:
        print(log)
    return None
