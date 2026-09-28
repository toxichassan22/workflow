# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Span router for designer chat: respan/span-01-lite (OpenRouter Decisions API,
# $0 per call) scores whether a non-canned turn is design work or plain chat,
# so obvious questions never reach the paid planner. Fail-open by contract:
# every error, missing key, malformed answer or ambiguous score returns
# 'design' — a router hiccup can never swallow an edit request.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SPAN_ROUTER_MODEL = (os.environ.get('SPAN_ROUTER_MODEL') or 'respan/span-01-lite:free').strip()
SPAN_ROUTER_URL = (os.environ.get('SPAN_ROUTER_URL') or 'https://openrouter.ai/api/alpha/decisions').strip()
SPAN_ROUTER_ENABLED = (os.environ.get('SPAN_ROUTER') or '1').strip().lower() not in ('0', 'false', 'off')
try:
    SPAN_ROUTER_TIMEOUT = float(os.environ.get('SPAN_ROUTER_TIMEOUT') or 15)
except (TypeError, ValueError):
    SPAN_ROUTER_TIMEOUT = 15.0
try:
    # Local replies are only accepted at or above this probability; anything
    # murkier goes to the real planner instead of guessing a canned answer.
    SPAN_ROUTER_LOCAL_MIN = float(os.environ.get('SPAN_ROUTER_LOCAL_MIN') or 0.5)
except (TypeError, ValueError):
    SPAN_ROUTER_LOCAL_MIN = 0.5

_SPAN_QUESTIONS = {
    'needs_design_work': {
        'type': 'noul',
        'instructions': (
            'Does the user want the designer to actually change, create, delete, '
            'move or restyle slide content in this presentation, or are they '
            'confirming or continuing such an edit?'),
        'criteria': {
            'true': 'The message requests a real modification to the presentation or confirms one.',
            'false': 'The message is a question, greeting, billing inquiry, or chat that asks for no slide change.',
        },
    },
    'asks_credit_balance': {
        'type': 'noul',
        'instructions': (
            'Is the user asking how much credit, balance or money remains in '
            'their company wallet, or whether a recharge arrived?'),
        'criteria': {
            'true': 'The message asks about remaining balance, wallet credit, or recharge status.',
            'false': 'The message is not about the account balance.',
        },
    },
}


def _designer_span_state(message, history):
    """Compact transcript for the behavior model: last assistant turn for
    context, then the new user message it must score."""
    lines = []
    for entry in reversed(history if isinstance(history, list) else []):
        if not isinstance(entry, dict) or entry.get('role') != 'assistant':
            continue
        previous = str(entry.get('content') or '').strip()
        if previous:
            lines.append('المصمم: ' + previous[:300])
        break
    lines.append('المستخدم: ' + str(message or '')[:500])
    return '\n'.join(lines)


def _noul_score(answers, name):
    """One question's yes-probability from the answers dict; None when absent,
    unparsable or outside [0, 1] — callers treat None as 'unknown'."""
    entry = answers.get(name)
    if not isinstance(entry, dict):
        return None
    try:
        value = float(entry.get('noul'))
    except (TypeError, ValueError):
        return None
    return value if 0.0 <= value <= 1.0 else None


def _designer_span_route(message, history=None, usage_ctx=None):
    """Return 'balance' or 'chat' for turns a canned reply covers, else 'design'.

    Called only after the deterministic free replies missed, so 'design' means
    proceed to the real planner. Never raises and never invents a canned route:
    provider errors, absent answers and sub-threshold scores all return 'design'.
    """
    if not SPAN_ROUTER_ENABLED:
        return 'design'
    try:
        if app.config.get('TESTING'):
            return 'design'
    except Exception:
        pass
    text = str(message or '').strip()
    if not text:
        return 'design'
    # A pending assistant question makes the reply an answer (often an
    # instruction), not a fresh question — do not classify it as chat.
    if _designer_last_reply_was_question(history):
        return 'design'
    if _tenant_key_gate(usage_ctx) is not None:
        # The paid path repeats this gate and renders its message; the router
        # simply has no key to call with.
        return 'design'
    if not _has_any_openrouter_key(usage_ctx):
        return 'design'
    payload = {
        'model': SPAN_ROUTER_MODEL,
        'state': _designer_span_state(text, history),
        'questions': _SPAN_QUESTIONS,
    }
    attempt_id = _begin_ai_attempt_record(usage_ctx, SPAN_ROUTER_MODEL)
    try:
        response = requests.post(
            SPAN_ROUTER_URL,
            headers=_openrouter_headers(usage_ctx, title='Landloom designer router'),
            json=payload, timeout=SPAN_ROUTER_TIMEOUT)
        response.encoding = 'utf-8'
        try:
            data = response.json()
        except Exception:
            data = {}
    except Exception as exc:
        print(f"[SPAN-ROUTER] call failed: {exc}")
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
        return 'design'
    usage_raw = data.get('usage') if isinstance(data, dict) else None
    usage = {}
    if isinstance(usage_raw, dict):
        usage = {
            'prompt_tokens': usage_raw.get('input_tokens') or 0,
            'completion_tokens': usage_raw.get('output_tokens') or 0,
            'total_tokens': (usage_raw.get('input_tokens') or 0) + (usage_raw.get('output_tokens') or 0),
            'cost_usd': usage_raw.get('cost'),
            'cost_raw': usage_raw.get('cost'),
        }
    generation_id = data.get('id') if isinstance(data, dict) else None
    if response.status_code >= 400 or not isinstance(data, dict):
        print(f"[SPAN-ROUTER] provider error status={response.status_code} body={str(data)[:300]}")
        _settle_ai_attempt_record(attempt_id, 'error', usage, generation_id)
        return 'design'
    _settle_ai_attempt_record(attempt_id, 'ok', usage, generation_id)
    answers = data.get('answers') if isinstance(data.get('answers'), dict) else {}
    design_p = _noul_score(answers, 'needs_design_work')
    balance_p = _noul_score(answers, 'asks_credit_balance')
    # A local route requires the model to positively rule out design work; a
    # missing needs_design score means 'unknown', and unknown goes paid.
    if design_p is None or design_p >= 0.5:
        return 'design'
    if balance_p is not None and balance_p >= SPAN_ROUTER_LOCAL_MIN:
        return 'balance'
    return 'chat'
