# Browse-agent multi-round model and tool loop.

def run_browse_agent(task, max_steps=None, usage_ctx=None, search_budget=None,
                     max_tokens=None, reasoning_effort=None, model=None,
                     evidence_pool=None, deadline=None, session=None,
                     on_event=None, server_tools=None, local_tools=True,
                     tool_choice=None, search_provider=None, cancel_event=None,
                     research_mode=False, allowed_hosts=None):
    """Drive one OpenRouter tool-call loop against a real browser session.

    ``model`` is the caller's own task model — the same model that would have
    answered the request without tools (MARKET_STUDY_MODEL for market work);
    ``None`` leaves the transport's default. ``search_budget`` raises/lowers
    the hard web_search cap (default 3 — one more than the preamble
    advertises); ``max_tokens`` is the per-round output cap (default 4000). A
    non-fatal output-cap quote can lower that cap for the same round; fatal
    balance refusals stop the run immediately. ``reasoning_effort`` passes
    straight through and is dropped for the rest of the run if the provider
    refuses it.

    ``server_tools`` are provider-executed tools (e.g. the OpenRouter
    ``openrouter:web_search`` server tool) declared alongside — or, with
    ``local_tools=False``, instead of — the local browser tools. A native-only
    run researches through provider search inside the request itself: no
    Chromium opens, and the reply's url_citation annotations are the evidence.
    ``tool_choice`` forwards OpenRouter's tool-choice verbatim; naming a
    server tool there (``{"type": "openrouter:web_search"}``) forces the
    search instead of leaving it to the model's discretion.

    ``evidence_pool`` (an ``EvidencePool`` from evidence.py) is the job's
    shared evidence store: a query the pool already ran is answered from its
    stored results and an already-fetched page answers open_url without
    touching the browser, while every real search/fetch/failure lands back in
    the pool. ``deadline`` is a unix timestamp shared by the whole job — it is
    checked before each model round and before each tool execution, and on
    expiry the loop stops and returns
    ``{'error': {'message': 'deadline_exceeded'}, ...}`` with the pages it had
    collected. ``session`` is a caller-owned browser worker (a BrowserWorker
    or the ``browser_session()`` yield) used for all tool execution; only a
    session this function opened itself is closed on exit.

    ``on_event`` is an optional callable fired with structured progress dicts
    so a caller's UI bar moves with the run instead of only between stages:
    ``{'phase': 'round', 'step', 'max_steps', 'searches', 'pages'}`` before each
    model round, ``{'phase': 'tool', ..., 'tool', 'hint'}`` before each tool
    executes, ``{'phase': 'tool_done', ..., 'ok'}`` after it, and
    ``{'phase': 'done', 'steps', 'pages', 'searches', 'ok'}`` once at the end.
    A raising callback is ignored — reporting never kills a run.

    ``cancel_event`` is an optional shared threading event used by parallel
    research workers to stop after a sibling reports a fatal billing refusal.

    Returns an OpenRouter-shaped dict: choices[0].message.content holds the
    model's final text, every successfully opened page becomes a url_citation
    annotation ({url, title, content} — text capped at 8K) and browse_trace
    lists every open attempt including failures. Transport errors and a step
    cap without final text return {"error": …} instead of raising.
    """
    trace = []
    pages = {}
    prompt_tokens = 0
    completion_tokens = 0
    final_text = ''
    final_finish = ''
    msg = None
    error = None
    if max_steps is None:
        try:
            max_steps = int(os.environ.get('BROWSER_MAX_STEPS') or _DEFAULT_MAX_STEPS)
        except (TypeError, ValueError):
            max_steps = _DEFAULT_MAX_STEPS
    try:
        max_steps = max(1, int(max_steps))
    except (TypeError, ValueError):
        max_steps = _DEFAULT_MAX_STEPS
    try:
        budget = max(1, int(search_budget)) if search_budget else _SEARCH_BUDGET
    except (TypeError, ValueError):
        budget = _SEARCH_BUDGET
    try:
        out_cap = max(1, int(max_tokens)) if max_tokens else 4000
    except (TypeError, ValueError):
        out_cap = 4000
    effort = str(reasoning_effort or '').strip() or None
    effort_disabled = False
    compact_retried = False
    open_nudged = False
    try:
        deadline = float(deadline) if deadline is not None else None
    except (TypeError, ValueError):
        deadline = None

    def _deadline_hit():
        return deadline is not None and time.time() >= deadline

    messages = [
        {'role': 'system', 'content': _agent_preamble(
            budget, research_mode=research_mode) if local_tools else _NATIVE_PREAMBLE},
        {'role': 'user', 'content': str(task or '')},
    ]
    request_tools = [] if allowed_hosts is not None else list(server_tools or [])
    if local_tools:
        request_tools = list(_BROWSER_TOOLS) + request_tools
    session_cm = None
    search_state = {'count': 0, 'budget': budget, 'current_url': None}

    def _emit(event):
        if not callable(on_event):
            return
        try:
            on_event(event)
        except Exception:
            pass

    def _cancel_requested():
        try:
            return bool(cancel_event and cancel_event.is_set())
        except Exception:
            return False

    def _round():
        round_cap = out_cap
        response = None
        for _cap_attempt in range(4):
            if _cancel_requested():
                return {'error': {
                    'message': 'cancelled_after_parallel_fatal_refusal'}}
            kwargs = {'max_tokens': round_cap, 'usage_ctx': usage_ctx}
            if request_tools:
                kwargs['tools'] = request_tools
            if tool_choice is not None:
                kwargs['tool_choice'] = tool_choice
            if model:
                kwargs['model'] = model
            if effort and not effort_disabled:
                kwargs['reasoning_effort'] = effort
            response = openrouter_chat(messages, **kwargs)
            if _browse_fatal_provider_response(response):
                if cancel_event is not None:
                    try:
                        cancel_event.set()
                    except Exception:
                        pass
                return response
            affordable_cap = _provider_affordable_token_limit(response)
            if (not affordable_cap or affordable_cap >= round_cap
                    or _deadline_hit() or _cancel_requested()):
                return response
            round_cap = max(1, affordable_cap)
            _log_line(f'[BROWSE AGENT] retrying with provider affordable cap={round_cap}')
        return response

    try:
        for step in range(max_steps):
            if _cancel_requested():
                error = {'message': 'cancelled_after_parallel_fatal_refusal'}
                break
            if _deadline_hit():
                error = {'message': 'deadline_exceeded'}
                break
            _compact_tool_history(messages)
            _emit({'phase': 'round', 'step': step + 1, 'max_steps': max_steps,
                   'searches': search_state['count'], 'pages': len(pages)})
            response = _round()
            fatal_response = _browse_fatal_provider_response(response)
            if _cancel_requested() and not fatal_response:
                error = {'message': 'cancelled_after_parallel_fatal_refusal'}
                break
            if (not fatal_response and effort and not effort_disabled
                    and _effort_refusal(response)):
                # The hint is model-specific — a provider that rejects it gets
                # the rest of the run without it, same model either way.
                if _deadline_hit():
                    error = {'message': 'deadline_exceeded'}
                    break
                effort_disabled = True
                response = _round()
                fatal_response = _browse_fatal_provider_response(response)
                if _cancel_requested() and not fatal_response:
                    error = {'message': 'cancelled_after_parallel_fatal_refusal'}
                    break
            # A transient provider failure re-issues the same round after a
            # short backoff — the retry lives inside this step so it never
            # burns the step cap or the remaining tool-call budget.
            msg = None
            reply_error = None
            for _attempt in range(_TRANSIENT_MAX_RETRIES + 1):
                try:
                    msg = _normalize_reply(response)
                    reply_error = None
                    break
                except _ReplyError as exc:
                    reply_error = exc.payload
                    if (_attempt >= _TRANSIENT_MAX_RETRIES
                            or not _transient_provider_error(reply_error)):
                        break
                    wait = _TRANSIENT_BACKOFF_S[
                        min(_attempt, len(_TRANSIENT_BACKOFF_S) - 1)]
                    if deadline is not None:
                        wait = min(wait, deadline - time.time() - 1.0)
                    if wait <= 0:
                        break
                    _log_line(f"[BROWSE AGENT] transient provider error "
                              f"{reply_error.get('message')!r}; retry "
                              f"{_attempt + 1} in {wait:.0f}s")
                    _emit({'phase': 'retry', 'step': step + 1,
                           'max_steps': max_steps, 'attempt': _attempt + 1,
                           'wait': wait, 'searches': search_state['count'],
                           'pages': len(pages)})
                    time.sleep(wait)
                    if _cancel_requested():
                        reply_error = {
                            'message': 'cancelled_after_parallel_fatal_refusal'}
                        break
                    if _deadline_hit():
                        reply_error = {'message': 'deadline_exceeded'}
                        break
                    response = _round()
            if reply_error is not None or msg is None:
                error = reply_error or {'message': 'provider returned no usable reply'}
                break
            usage_meta = (response.get('usage')
                          if isinstance(response, dict) else None) or {}
            try:
                prompt_tokens += int(usage_meta.get('prompt_tokens') or 0)
                completion_tokens += int(usage_meta.get('completion_tokens') or 0)
            except (TypeError, ValueError):
                pass
            if not msg['tool_calls']:
                final_text = str(msg.get('content') or '').strip()
                if (not compact_retried and _truncated_reply(response)
                        and not _deadline_hit()):
                    # The answer ran into the output cap mid-JSON — spend one
                    # step asking for the same result compressed instead of
                    # surfacing a truncated parse failure downstream.
                    compact_retried = True
                    final_text = ''
                    messages.append(_assistant_echo(msg))
                    messages.append(
                        {'role': 'user', 'content': _COMPACT_REPLY_PROMPT})
                    continue
                if (not open_nudged and not pages and not trace
                        and search_state.get('had_results')
                        and not _deadline_hit() and step + 1 < max_steps):
                    # Final answer off snippets alone: searches returned
                    # openable URLs but no page was ever read — downstream
                    # marks every source unverified. One forced open round.
                    open_nudged = True
                    final_text = ''
                    messages.append(_assistant_echo(msg))
                    messages.append({'role': 'user',
                                     'content': _OPEN_BEFORE_ANSWER_PROMPT})
                    continue
                if not final_text:
                    error = {'message': 'model returned no text and no tool call'}
                choice = (response.get('choices') or [{}])[0] \
                    if isinstance(response, dict) else {}
                final_finish = str((choice or {}).get('native_finish_reason')
                                   or (choice or {}).get('finish_reason') or '')
                break
            if session is None:
                # No point launching the caller's browser once the budget is
                # spent — the deadline wins over a pending tool call.
                if _deadline_hit():
                    error = {'message': 'deadline_exceeded'}
                    break
                session_cm = _browser_session(search_provider=search_provider)
                session = session_cm.__enter__()
            # Echo the model's message (raw tool_calls keep their serialized
            # arguments), then answer each call with a tool result message.
            messages.append(_assistant_echo(msg))
            for call in msg['tool_calls']:
                if _cancel_requested():
                    error = {'message': 'cancelled_after_parallel_fatal_refusal'}
                    break
                if _deadline_hit():
                    error = {'message': 'deadline_exceeded'}
                    break
                args = call['arguments']
                hint = str(args.get('purpose') or args.get('url') or args.get('query')
                           or args.get('text') or args.get('direction') or '')[:120]
                _log_step(step + 1, call['name'] or '?', hint)
                _emit({'phase': 'tool', 'step': step + 1, 'max_steps': max_steps,
                       'tool': call['name'] or '', 'hint': hint,
                       'arguments': dict(args),
                       'searches': search_state['count'], 'pages': len(pages)})
                result = _execute_tool(session, call['name'], args,
                                       trace, pages, search_state,
                                       evidence_pool,
                                       allowed_hosts=allowed_hosts)
                _emit({'phase': 'tool_done', 'step': step + 1,
                       'max_steps': max_steps, 'tool': call['name'] or '',
                       'hint': hint, 'searches': search_state['count'],
                       'pages': len(pages),
                       'arguments': dict(args),
                       'result': result,
                       'ok': not bool((result or {}).get('error'))})
                messages.append(_tool_message(call, result))
            if error is not None:
                break
        else:
            error = {'message': f'max_steps reached ({max_steps}) without a final answer'}
    except Exception as exc:
        error = {'message': str(exc) or exc.__class__.__name__}
    finally:
        # Only a session this run opened is closed — a caller-provided
        # ``session`` stays the caller's problem to release.
        if session_cm is not None:
            try:
                session_cm.__exit__(None, None, None)
            except Exception:
                pass

    usage = {'prompt_tokens': prompt_tokens,
             'completion_tokens': completion_tokens,
             'total_tokens': prompt_tokens + completion_tokens}
    _emit({'phase': 'done', 'pages': len(pages), 'searches': search_state['count'],
           'ok': error is None})
    _log_line(f"[BROWSE AGENT] done: pages={len(pages)} trace={len(trace)} "
              f"{'error=' + str((error or {}).get('message')) if error else 'ok'}")
    annotations = [{'url_citation': {'url': url, 'title': page['title'],
                                     'content': page['content']}}
                   for url, page in pages.items()]
    # Provider-native citations (a server-tool search cites without any page
    # open) ride on the final message itself — union them so a native-only run
    # keeps its evidence instead of shipping an empty annotation list.
    _seen_urls = set(pages)
    for _ann in ((msg or {}).get('raw_message') or {}).get('annotations') or []:
        _ann = _ann if isinstance(_ann, dict) else {}
        _cit = _ann.get('url_citation')
        _cit = _cit if isinstance(_cit, dict) else {}
        _url = str(_cit.get('url') or _ann.get('url') or '').strip()
        if allowed_hosts is not None and not _source_url_allowed(_url, allowed_hosts):
            continue
        if _url and _url not in _seen_urls:
            _seen_urls.add(_url)
            annotations.append({'url_citation': {
                'url': _url, 'title': str(_cit.get('title') or ''),
                'content': str(_cit.get('content') or '')}})
    if error:
        result = {'error': error, 'usage': usage, 'browse_trace': trace}
        if annotations:
            # Pages gathered before the failure stay visible to the caller —
            # a deadline stops the loop, it does not throw away evidence.
            result['annotations'] = annotations
        return result
    final_choice = {'message': {'role': 'assistant',
                                'content': final_text,
                                'annotations': annotations}}
    if final_finish:
        # The downstream error reporter reads the choice's finish reason — a
        # still-truncated retry must surface as MAX_TOKENS, not a mystery.
        final_choice['finish_reason'] = final_finish
    return {'choices': [final_choice],
            'usage': usage,
            'browse_trace': trace}
