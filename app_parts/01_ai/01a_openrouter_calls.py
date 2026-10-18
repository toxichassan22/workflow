# OpenRouter chat and streaming request paths.

def call_openrouter_chat(system_prompt, user_content,     temperature=0.7, max_tokens=8000, model=None, timeout=300, reasoning_effort=None, response_format=None, provider=None, image_references=None, tools=None, plugins=None, max_tool_calls=None, tool_choice=None, usage_ctx=None, _credit_recovery_attempted=False):
    gate = _tenant_key_gate(usage_ctx)
    if gate is not None:
        return {"error": gate}
    if not _has_any_openrouter_key(usage_ctx):
        return {"error": {"message": "OPENROUTER_KEY is missing"}}
    model_name = model or GEMINI_TEXT_MODEL
    headers = _openrouter_headers(usage_ctx)
    user_message_content = user_content
    if image_references:
        user_message_content = [{"type": "text", "text": str(user_content)}]
        for image_reference in image_references:
            if isinstance(image_reference, dict):
                image_url = image_reference.get('data_uri') or image_reference.get('url')
            else:
                image_url = image_reference
            if isinstance(image_url, str) and image_url.startswith('data:image/'):
                user_message_content.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message_content}
        ],
        "max_tokens": max_tokens
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
    if plugins:
        payload["plugins"] = plugins
    if max_tool_calls:
        payload["max_tool_calls"] = max_tool_calls
    if tool_choice:
        payload["tool_choice"] = tool_choice
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
                if (fatal.get('error_code') == 'INSUFFICIENT_CREDITS'
                        and not _credit_recovery_attempted
                        and _repair_tenant_key_limit_after_refusal(usage_ctx)):
                    return call_openrouter_chat(
                        system_prompt, user_content,
                        temperature=temperature, max_tokens=max_tokens,
                        model=model, timeout=timeout,
                        reasoning_effort=reasoning_effort,
                        response_format=response_format, provider=provider,
                        image_references=image_references, tools=tools,
                        plugins=plugins, max_tool_calls=max_tool_calls,
                        tool_choice=tool_choice, usage_ctx=usage_ctx,
                        _credit_recovery_attempted=True,
                    )
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


def call_text_chat(system_prompt, user_content, temperature=0.7, max_tokens=8000, timeout=300,
                  reasoning_effort=None, response_format=None, model=None, image_references=None, usage_ctx=None):
    """Compatibility wrapper: text/design work uses configured models through OpenRouter."""
    if not _has_any_openrouter_key(usage_ctx):
        return {"error": {"message": "OPENROUTER_KEY is required for the text model"}}
    return call_openrouter_chat(
        system_prompt,
        user_content,
        temperature=None,
        max_tokens=max_tokens,
        model=model or LUNA_TEXT_MODEL,
        timeout=timeout,
        reasoning_effort=reasoning_effort,
        response_format=response_format,
        image_references=image_references,
        usage_ctx=usage_ctx,
    )


def call_text_chat_parallel(system_prompt, user_content, temperature=0.7, max_tokens=8000, attempts=2, timeout=300, model=None, image_references=None, usage_ctx=None):
    """
    Race multiple identical model calls in parallel and return the first valid response.
    Helps when a single model invocation is slow or returns malformed/empty content.
    Every attempt is metered separately: the provider bills each one.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _attempt():
        try:
            resp = call_text_chat(system_prompt, user_content, temperature, max_tokens, timeout=timeout, model=model, image_references=image_references, usage_ctx=usage_ctx)
            if _ai_fatal_error_dict(resp) is not None:
                # A deterministic refusal (wallet/key/trial) cannot be raced
                # around — every parallel attempt hits it identically.
                return resp
            if not _has_chat_choices(resp):
                return None
            content = extract_chat_content(resp, 'TEXT-PARALLEL')
            return resp if content.strip() else None
        except Exception as e:
            print(f"[TEXT PARALLEL] attempt failed: {e}")
            return None

    executor = ThreadPoolExecutor(max_workers=max(1, attempts))
    futures = [executor.submit(_attempt) for _ in range(max(1, attempts))]
    try:
        for future in as_completed(futures):
            result = future.result()
            if result:
                for pending in futures:
                    pending.cancel()
                print(f"[TEXT PARALLEL] Valid response received after racing {attempts} calls")
                return result
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    raise Exception(f"All {attempts} parallel text attempts failed")


def call_openrouter_chat_stream(system_prompt, user_content, temperature=0.7, max_tokens=8000, model=None, timeout=300, reasoning_effort=None, response_format=None, provider=None, image_references=None, tools=None, plugins=None, usage_ctx=None, on_token=None, read_timeout=60):
    """Streaming twin of call_openrouter_chat: identical request, tokens via on_token.

    The payload carries the same model, messages and limits with stream mode on,
    so the provider generates the same completion it would for the non-stream
    call. Deltas are concatenated and returned in the same choices shape, so
    callers that read response['choices'][0]['message']['content'] work
    unchanged, and metering settles exactly once from the stream's usage chunk
    (falling back to an empty usage record exactly like the non-stream error
    paths when the provider sends none). Transport and HTTP failures return the
    same {"error": ...} shape; only on_token is new, and it must never raise.
    """
    import time as _time
    gate = _tenant_key_gate(usage_ctx)
    if gate is not None:
        return {"error": gate}
    if not _has_any_openrouter_key(usage_ctx):
        return {"error": {"message": "OPENROUTER_KEY is missing"}}
    model_name = model or GEMINI_TEXT_MODEL
    headers = _openrouter_headers(usage_ctx)
    user_message_content = user_content
    if image_references:
        user_message_content = [{"type": "text", "text": str(user_content)}]
        for image_reference in image_references:
            if isinstance(image_reference, dict):
                image_url = image_reference.get('data_uri') or image_reference.get('url')
            else:
                image_url = image_reference
            if isinstance(image_url, str) and image_url.startswith('data:image/'):
                user_message_content.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message_content}
        ],
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "usage": {"include": True},
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
    if plugins:
        payload["plugins"] = plugins
    attempt_id = _begin_ai_attempt_record(usage_ctx, model_name)

    def _fail(message):
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
        return {"error": {"message": message}}

    def _delta_text(delta, *keys):
        for key in keys:
            piece = delta.get(key)
            if isinstance(piece, list):
                piece = ' '.join(
                    part.get('text', '') if isinstance(part, dict) else str(part)
                    for part in piece
                )
            if piece:
                return str(piece)
        return ''

    start = _time.monotonic()
    try:
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=(15, read_timeout), stream=True)
        response.encoding = 'utf-8'
    except requests.exceptions.Timeout:
        print(f"[OPENROUTER STREAM TIMEOUT] model={model_name} cap={max_tokens}")
        return _fail(f"انتهت مهلة الاتصال بالمزوّد ({timeout} ثانية)")
    except requests.exceptions.ConnectionError as exc:
        print(f"[OPENROUTER STREAM CONNECTION] model={model_name} {exc}")
        return _fail("انقطع الاتصال بالمزوّد قبل اكتمال الطلب")
    except Exception as exc:
        print(f"[OPENROUTER STREAM EXCEPTION] model={model_name} {exc}")
        return _fail(str(exc))
    if response.status_code >= 400:
        try:
            data = response.json()
        except Exception:
            data = {}
        try:
            response.close()
        except Exception:
            pass
        error = data.get('error', {}) if isinstance(data, dict) else data
        print(f"[OPENROUTER STREAM HTTP ERROR] status={response.status_code} model={model_name} error={error}")
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
        fatal = _provider_credit_error_dict(error, response.status_code, usage_ctx)
        if fatal is not None:
            return {"error": fatal}
        if isinstance(error, dict) and 'message' in error:
            error['message'] = f"[{response.status_code}] {error['message']}"
            return {"error": error}
        return {"error": error if isinstance(error, dict) else {"message": f"[{response.status_code}] {error}"}}
    content_parts = []
    reasoning_parts = []
    generation_id = None
    usage = {}
    try:
        for line in response.iter_lines(decode_unicode=True):
            if _time.monotonic() - start > timeout:
                try:
                    response.close()
                except Exception:
                    pass
                return _fail(f"انتهت مهلة الاتصال بالمزوّد ({timeout} ثانية)")
            if not line:
                continue
            text = line.strip()
            if not text.startswith('data:'):
                continue
            text = text[5:].strip()
            if text == '[DONE]':
                break
            try:
                chunk = json.loads(text)
            except Exception:
                continue
            if not isinstance(chunk, dict):
                continue
            if generation_id is None and isinstance(chunk.get('id'), str) and chunk.get('id'):
                generation_id = chunk.get('id')
            if isinstance(chunk.get('usage'), dict):
                usage = chunk.get('usage')
            choices = chunk.get('choices')
            choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
            delta = choice.get('delta')
            if not isinstance(delta, dict):
                continue
            piece = _delta_text(delta, 'content')
            if piece:
                content_parts.append(piece)
            else:
                for key in ('reasoning_content', 'reasoning', 'reasoning_details'):
                    rpiece = _delta_text(delta, key)
                    if rpiece:
                        reasoning_parts.append(rpiece)
                        break
            if on_token and content_parts:
                try:
                    on_token(''.join(content_parts))
                except Exception:
                    pass
        try:
            response.close()
        except Exception:
            pass
    except requests.exceptions.Timeout:
        print(f"[OPENROUTER STREAM STALL] model={model_name} cap={max_tokens}")
        return _fail(f"انتهت مهلة الاتصال بالمزوّد ({timeout} ثانية)")
    except requests.exceptions.ConnectionError as exc:
        print(f"[OPENROUTER STREAM CONNECTION] model={model_name} {exc}")
        return _fail("انقطع الاتصال بالمزوّد قبل اكتمال الطلب")
    except Exception as exc:
        print(f"[OPENROUTER STREAM EXCEPTION] model={model_name} {exc}")
        return _fail(str(exc))
    final_text = ''.join(content_parts)
    if not final_text.strip() and reasoning_parts:
        final_text = ''.join(reasoning_parts)
    _, settled_usage = _extract_openrouter_usage({'id': generation_id, 'usage': usage})
    _settle_ai_attempt_record(attempt_id, 'ok', settled_usage, generation_id)
    return {"choices": [{"message": {"content": final_text}}], "usage": usage, "id": generation_id}


def call_text_chat_stream(system_prompt, user_content, temperature=0.7, max_tokens=8000, timeout=300, reasoning_effort=None, response_format=None, model=None, image_references=None, usage_ctx=None, on_token=None):
    """Streaming twin of call_text_chat: same defaults, tokens via on_token."""
    if not _has_any_openrouter_key(usage_ctx):
        return {"error": {"message": "OPENROUTER_KEY is required for the text model"}}
    return call_openrouter_chat_stream(
        system_prompt,
        user_content,
        temperature=None,
        max_tokens=max_tokens,
        model=model or LUNA_TEXT_MODEL,
        timeout=timeout,
        reasoning_effort=reasoning_effort,
        response_format=response_format,
        image_references=image_references,
        usage_ctx=usage_ctx,
        on_token=on_token,
    )


def _slide_stream_progress(tenant_id, job_id, interval=1.0):
    """Throttle live slide previews: at most one job-file publish per interval.

    The callback only ever writes the in-progress text; the completed job body
    keeps today's shape, so clients that ignore unknown keys see no change.
    """
    import time as _time
    state = {'last': 0.0}

    def _on_token(full_text):
        now = _time.monotonic()
        if now - state['last'] < interval:
            return
        state['last'] = now
        try:
            _write_job('.slide_jobs', tenant_id, job_id, {
                'status': 'running',
                'success': True,
                'message': 'جاري توليد الشريحة...',
                'partial': full_text,
            })
        except Exception as exc:
            print(f'[SLIDE STREAM] partial write failed: {exc}')

    return _on_token
