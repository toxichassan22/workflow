
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: messages-shaped OpenRouter calls with tool calls for the designer agent
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# The agent planner needs full message history (assistant turns carrying
# tool_calls, tool results) instead of the system+user pair that
# call_openrouter_chat builds. Same provider plumbing: tenant key gate, usage
# attempt record, and identical error semantics.


def call_openrouter_messages(messages, *, tools=None, tool_choice=None,
                             response_format=None, model=None, max_tokens=8000,
                             temperature=None, reasoning_effort=None,
                             provider=None, plugins=None, max_tool_calls=None,
                             timeout=300, usage_ctx=None):
    """One round-trip against /chat/completions with a caller-built message list.

    ``messages`` may contain system/user/assistant/tool roles; assistant entries
    keep their ``tool_calls`` so the response can continue a tool loop.
    Returns the raw provider dict (same shape as call_openrouter_chat).
    """
    gate = _tenant_key_gate(usage_ctx)
    if gate is not None:
        return {"error": gate}
    if not _has_any_openrouter_key(usage_ctx):
        return {"error": {"message": "OPENROUTER_KEY is missing"}}
    model_name = model or GEMINI_TEXT_MODEL
    headers = _openrouter_headers(usage_ctx)
    payload = {
        "model": model_name,
        "messages": messages if isinstance(messages, list) else [],
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if response_format:
        payload["response_format"] = response_format
    if provider:
        payload["provider"] = provider
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if plugins:
        payload["plugins"] = plugins
    if max_tool_calls:
        payload["max_tool_calls"] = max_tool_calls
    attempt_id = _begin_ai_attempt_record(usage_ctx, model_name)
    try:
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=timeout)
        response.encoding = 'utf-8'
        text = response.text or ''
        if not text.strip():
            print(f"[OPENROUTER EMPTY BODY] status={response.status_code} model={model_name} cap={max_tokens}")
            _settle_ai_attempt_record(attempt_id, 'error', {}, None)
            return {"error": {"message": f"مزوّد الذكاء الاصطناعي رد بجسم فارغ (HTTP {response.status_code})"}}
        try:
            data = response.json()
        except Exception as json_err:
            print(f"[OPENROUTER UNPARSEABLE] status={response.status_code} model={model_name} json_err={json_err} body={text[:200]!r}")
            _settle_ai_attempt_record(attempt_id, 'error', {}, None)
            return {"error": {"message": f"استجابة المزوّد ليست JSON صالحًا (HTTP {response.status_code})"}}
        if response.status_code >= 400:
            error = data.get('error', {}) if isinstance(data, dict) else data
            print(f"[OPENROUTER HTTP ERROR] status={response.status_code} model={model_name} error={error}")
            generation_id, error_usage = _extract_openrouter_usage(data)
            _settle_ai_attempt_record(attempt_id, 'error', error_usage, generation_id)
            fatal = _provider_credit_error_dict(error, response.status_code, usage_ctx)
            if fatal is not None:
                return {"error": fatal}
            if isinstance(error, dict) and 'message' in error:
                error['message'] = f"[{response.status_code}] {error['message']}"
                return {"error": error}
            return {"error": error if isinstance(error, dict) else {"message": f"[{response.status_code}] {error}"}}
        generation_id, usage = _extract_openrouter_usage(data)
        _settle_ai_attempt_record(attempt_id, 'ok', usage, generation_id)
        return data
    except requests.exceptions.Timeout:
        print(f"[OPENROUTER TIMEOUT] model={model_name} cap={max_tokens} timeout={timeout}")
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
        return {"error": {"message": f"انتهت مهلة الاتصال بالمزوّد ({timeout} ثانية)"}}
    except requests.exceptions.ConnectionError as exc:
        print(f"[OPENROUTER CONNECTION] model={model_name} {exc}")
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
        return {"error": {"message": "انقطع الاتصال بالمزوّد قبل اكتمال الطلب"}}
    except Exception as exc:
        print(f"[OPENROUTER EXCEPTION] model={model_name} {exc}")
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
        return {"error": {"message": str(exc)}}


def openrouter_response_message(response, label='AGENT'):
    """Normalize one chat-completions reply into {content, tool_calls, usage}.

    Raises RuntimeError on provider errors or empty choices, so a tool loop can
    treat every anomaly the same way. When ``content`` is empty but the model
    produced reasoning, the reasoning text is returned instead — some backends
    stream the answer only through the reasoning channel.
    """
    if not isinstance(response, dict) or 'error' in response:
        err = response.get('error') if isinstance(response, dict) else None
        fatal = _ai_fatal_error_dict(response)
        if fatal is not None:
            raise FatalAICallError(fatal.get('message'),
                                   error_code=fatal.get('error_code'),
                                   http_status=fatal.get('http_status'),
                                   provider_message=fatal.get('provider_message'))
        raise RuntimeError(f'[{label}] ' + (json.dumps(err, ensure_ascii=False)
                           if isinstance(err, dict) else str(err or 'empty provider response')))
    choices = response.get('choices')
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f'[{label}] provider returned no choices')
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get('message') if isinstance(choice.get('message'), dict) else {}
    content = message.get('content')
    if isinstance(content, list):
        content = ''.join(
            part.get('text', '') if isinstance(part, dict) else str(part)
            for part in content)
    if not (content or '').strip():
        content = message.get('reasoning') or message.get('reasoning_content') or ''
    tool_calls = []
    for call in message.get('tool_calls') or []:
        if not isinstance(call, dict):
            continue
        fn = call.get('function') if isinstance(call.get('function'), dict) else {}
        arguments = fn.get('arguments')
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (TypeError, ValueError):
                arguments = {}
        tool_calls.append({
            'id': str(call.get('id') or f'call_{len(tool_calls)}'),
            'name': str(fn.get('name') or ''),
            'arguments': arguments if isinstance(arguments, dict) else {},
        })
    return {
        'content': str(content or ''),
        'tool_calls': tool_calls,
        'usage': response.get('usage') if isinstance(response.get('usage'), dict) else {},
        'finish_reason': choice.get('finish_reason'),
        'raw_message': message,
    }


def openrouter_tool_result_message(call, content):
    """Build the ``tool`` role message that answers one tool call."""
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return {'role': 'tool', 'tool_call_id': str(call.get('id') or ''), 'content': text[:60000]}


def openrouter_assistant_tool_message(result):
    """Rebuild the assistant message for a tool loop: content + tool_calls."""
    raw = result.get('raw_message') if isinstance(result.get('raw_message'), dict) else {}
    message = {'role': 'assistant', 'content': result.get('content') or None}
    if raw.get('tool_calls'):
        message['tool_calls'] = raw['tool_calls']
    return message
