# OpenRouter chat and streaming request paths.
import os
import time


def _prompt_cache_enabled(model_name):
    try:
        return (os.environ.get('PROMPT_CACHE_ENABLED') or '1').strip() != '0'
    except Exception:
        return True


def _cached_system_content(system_prompt, model_name):
    """Mark the stable system prefix for Anthropic via OpenRouter.

    OpenAI and Gemini cache a stable prefix automatically; sending the Anthropic
    marker to them is unnecessary and can be rejected, so it stays provider-scoped.
    """
    text = str(system_prompt or '')
    if not text or not _prompt_cache_enabled(model_name):
        return system_prompt
    if not str(model_name or '').lower().startswith('anthropic/'):
        return system_prompt
    return [{'type': 'text', 'text': text, 'cache_control': {'type': 'ephemeral'}}]


def _cache_system_messages(messages, model_name):
    """Apply the same stable-prefix marker to a caller-built message list."""
    if not isinstance(messages, list) or not messages:
        return messages
    if not _prompt_cache_enabled(model_name):
        return messages
    if not str(model_name or '').lower().startswith('anthropic/'):
        return messages
    if not isinstance(messages[0], dict) or messages[0].get('role') != 'system':
        return messages
    copied = [dict(message) if isinstance(message, dict) else message for message in messages]
    first = copied[0]
    content = first.get('content')
    if isinstance(content, str) and content:
        first['content'] = [{'type': 'text', 'text': content,
                             'cache_control': {'type': 'ephemeral'}}]
    elif isinstance(content, list) and content:
        blocks = [dict(block) if isinstance(block, dict) else block for block in content]
        for block in reversed(blocks):
            if isinstance(block, dict) and block.get('type') == 'text':
                block['cache_control'] = {'type': 'ephemeral'}
                break
        first['content'] = blocks
    return copied


def call_openrouter_chat(system_prompt, user_content,     temperature=0.7, max_tokens=8000, model=None, timeout=300, reasoning_effort=None, response_format=None, provider=None, image_references=None, tools=None, plugins=None, max_tool_calls=None, tool_choice=None, usage_ctx=None, _credit_recovery_attempted=False, _force_platform=False):
    if not _force_platform:
        gate = _tenant_key_gate(usage_ctx)
        if gate is not None:
            return {"error": gate}
    if not _has_any_openrouter_key(usage_ctx, force_platform=_force_platform):
        return {"error": {"message": "OPENROUTER_KEY is missing"}}
    # A cancelled run must never reach the provider — the whole point of the
    # stop button is that these tokens are never spent.
    if run_control.run_is_cancelled(usage_ctx):
        return run_control.cancelled_response()
    model_name = model or GEMINI_TEXT_MODEL
    if reasoning_effort is None and model_name == GEMINI_TEXT_MODEL:
        reasoning_effort = TEXT_REASONING_EFFORT
    headers = _openrouter_headers(usage_ctx, force_platform=_force_platform)
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
            {"role": "system", "content": _cached_system_content(system_prompt, model_name)},
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
    usage_ctx = _with_context_metrics(
        usage_ctx, _context_text(system_prompt) + '\n' + _context_text(user_content))
    started = time.perf_counter()
    attempt_id = _begin_ai_attempt_record(usage_ctx, model_name)
    try:
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=timeout)
        response.encoding = 'utf-8'
        text = response.text or ''
        if not text.strip():
            print(f"[OPENROUTER EMPTY BODY] status={response.status_code} model={model_name} cap={max_tokens}")
            _settle_ai_attempt_record(attempt_id, 'error', {}, None,
                                      duration_ms=_elapsed_ms(started))
            return {"error": {"message": f"مزوّد الذكاء الاصطناعي رد بجسم فارغ (HTTP {response.status_code})"}}
        try:
            data = response.json()
        except Exception as json_err:
            print(f"[OPENROUTER UNPARSEABLE] status={response.status_code} model={model_name} json_err={json_err} body={text[:200]!r}")
            _settle_ai_attempt_record(attempt_id, 'error', {}, None,
                                      duration_ms=_elapsed_ms(started))
            return {"error": {"message": f"استجابة المزوّد ليست JSON صالحًا (HTTP {response.status_code})"}}
        if response.status_code >= 400:
            error = data.get('error', {}) if isinstance(data, dict) else data
            print(f"[OPENROUTER HTTP ERROR] status={response.status_code} model={model_name} error={error}")
            generation_id, error_usage = _extract_openrouter_usage(data)
            _settle_ai_attempt_record(attempt_id, 'error', error_usage, generation_id,
                                      duration_ms=_elapsed_ms(started))
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
                        _force_platform=_force_platform,
                    )
                if (_ai_call_uses_tenant_key(usage_ctx)
                        and not _force_platform
                        and OPENROUTER_KEY):
                    print(f"[OPENROUTER CHAT FALLBACK] Tenant key refusal ({fatal.get('error_code')}), retrying with platform key...")
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
                        _force_platform=True,
                    )
                return {"error": fatal}
            if isinstance(error, dict) and 'message' in error:
                error['message'] = f"[{response.status_code}] {error['message']}"
                return {"error": error}
            return {"error": error if isinstance(error, dict) else {"message": f"[{response.status_code}] {error}"}}
        generation_id, usage = _extract_openrouter_usage(data)
        _settle_ai_attempt_record(attempt_id, 'ok', usage, generation_id,
                                  duration_ms=_elapsed_ms(started))
        return data
    except requests.exceptions.Timeout:
        print(f"[OPENROUTER TIMEOUT] model={model_name} cap={max_tokens} timeout={timeout}")
        _settle_ai_attempt_record(attempt_id, 'error', {}, None,
                                  duration_ms=_elapsed_ms(started))
        return {"error": {"message": f"انتهت مهلة الاتصال بالمزوّد ({timeout} ثانية)"}}
    except requests.exceptions.ConnectionError as exc:
        print(f"[OPENROUTER CONNECTION] model={model_name} {exc}")
        _settle_ai_attempt_record(attempt_id, 'error', {}, None,
                                  duration_ms=_elapsed_ms(started))
        return {"error": {"message": "انقطع الاتصال بالمزوّد قبل اكتمال الطلب"}}
    except Exception as exc:
        print(f"[OPENROUTER EXCEPTION] model={model_name} {exc}")
        _settle_ai_attempt_record(attempt_id, 'error', {}, None,
                                  duration_ms=_elapsed_ms(started))
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
            if isinstance(resp, dict) and resp.get('cancelled'):
                # A stopped run is final as well: racing it would start more
                # paid attempts for work the user already cancelled.
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


def call_openrouter_chat_stream(system_prompt, user_content, temperature=0.7, max_tokens=8000, model=None, timeout=300, reasoning_effort=None, response_format=None, provider=None, image_references=None, tools=None, plugins=None, usage_ctx=None, on_token=None, read_timeout=60, _credit_recovery_attempted=False, _force_platform=False):
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
    if not _force_platform:
        gate = _tenant_key_gate(usage_ctx)
        if gate is not None:
            return {"error": gate}
    if not _has_any_openrouter_key(usage_ctx, force_platform=_force_platform):
        return {"error": {"message": "OPENROUTER_KEY is missing"}}
    # A cancelled run must never reach the provider.
    if run_control.run_is_cancelled(usage_ctx):
        return run_control.cancelled_response()
    model_name = model or GEMINI_TEXT_MODEL
    if reasoning_effort is None and model_name == GEMINI_TEXT_MODEL:
        reasoning_effort = TEXT_REASONING_EFFORT
    headers = _openrouter_headers(usage_ctx, force_platform=_force_platform)
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
            {"role": "system", "content": _cached_system_content(system_prompt, model_name)},
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
    usage_ctx = _with_context_metrics(
        usage_ctx, _context_text(system_prompt) + '\n' + _context_text(user_content))
    started = time.perf_counter()
    attempt_id = _begin_ai_attempt_record(usage_ctx, model_name)

    def _fail(message):
        _settle_ai_attempt_record(attempt_id, 'error', {}, None,
                                  duration_ms=_elapsed_ms(started))
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
        _settle_ai_attempt_record(attempt_id, 'error', {}, None,
                                  duration_ms=_elapsed_ms(started))
        fatal = _provider_credit_error_dict(error, response.status_code, usage_ctx)
        if fatal is not None:
            if (_ai_call_uses_tenant_key(usage_ctx)
                    and not _force_platform
                    and OPENROUTER_KEY):
                print(f"[OPENROUTER STREAM FALLBACK] Tenant key refusal ({fatal.get('error_code')}), retrying with platform key...")
                return call_openrouter_chat_stream(
                    system_prompt, user_content,
                    temperature=temperature, max_tokens=max_tokens,
                    model=model, timeout=timeout,
                    reasoning_effort=reasoning_effort,
                    response_format=response_format, provider=provider,
                    image_references=image_references, tools=tools,
                    plugins=plugins, usage_ctx=usage_ctx,
                    on_token=on_token, read_timeout=read_timeout,
                    _credit_recovery_attempted=True,
                    _force_platform=True,
                )
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
            # A stop clicked mid-generation: closing the response here ends the
            # provider's stream, so the rest of the output is never produced and
            # never billed. The tokens already produced stay metered.
            if run_control.run_is_cancelled(usage_ctx, throttle=True):
                try:
                    response.close()
                except Exception:
                    pass
                print(f"[OPENROUTER STREAM CANCELLED] model={model_name}")
                _settle_ai_attempt_record(attempt_id, 'ok', usage, generation_id,
                                          duration_ms=_elapsed_ms(started))
                return run_control.cancelled_response(''.join(content_parts))
            if not line:
                continue
            if isinstance(line, bytes):
                try:
                    text = line.decode('utf-8', errors='ignore').strip()
                except Exception:
                    text = str(line).strip()
            else:
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
    _settle_ai_attempt_record(attempt_id, 'ok', settled_usage, generation_id,
                              duration_ms=_elapsed_ms(started))
    return {"choices": [{"message": {"content": final_text}}], "usage": usage, "id": generation_id}


def call_text_chat_stream(system_prompt, user_content, temperature=0.7, max_tokens=8000, timeout=300, reasoning_effort=None, response_format=None, model=None, image_references=None, usage_ctx=None, on_token=None):
    """Streaming twin of call_text_chat: same defaults, tokens via on_token.

    A call that belongs to a run is streamed, because a stream is the only
    way a stop can cut it in the middle. A call with no run behind it takes
    the plain twin: the same request, and the credit-recovery retry that the
    streaming path does not carry.
    """
    if not _has_any_openrouter_key(usage_ctx):
        return {"error": {"message": "OPENROUTER_KEY is required for the text model"}}
    if not run_control.run_can_be_cancelled(usage_ctx):
        return call_text_chat(
            system_prompt,
            user_content,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            reasoning_effort=reasoning_effort,
            response_format=response_format,
            model=model,
            image_references=image_references,
            usage_ctx=usage_ctx,
        )
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
