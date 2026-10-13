def _call_market_study_model(system_prompt, user_content, max_tokens=None, usage_ctx=None,
                             search_context=None, server_tools=True, max_search_results=8,
                             search_budget=None, reasoning_effort=None):
    """Search-backed market call with JSON, provider, and credit fallbacks.

    ``server_tools=False`` drops the openrouter:web_search tool — Gemini answers
    it with MALFORMED_FUNCTION_CALL when the prompt asks for several lookups, so
    bounded tasks (logo discovery) run on the always-on Exa plugin alone.
    """
    cap = max(2000, int(max_tokens or MARKET_STUDY_MAX_TOKENS))
    # One search cannot price several competitors, so the model is allowed a search per
    # competitor plus the market-wide ones; without max_uses it settled for a single call
    # and left every price blank.
    search_params = {'engine': MARKET_SEARCH_ENGINE,
                     'max_results': 10, 'max_uses': 10, 'max_total_results': 60,
                     # Exa's adaptive highlight is ~2-4K chars — usually too thin
                     # to carry the listing's price. Pin the excerpt budget to
                     # the 8K _market_citation_pages keeps.
                     'max_characters': 8000}
    # The engine runs the provider's native search on 'auto' — Google grounding for
    # Gemini — and user_location biases those results toward the project's city
    # (native search only; Exa ignores it, so the query itself names the city).
    context = search_context if isinstance(search_context, dict) else {}
    city = str(context.get('city') or '').strip()
    country = str(context.get('country') or 'SA').strip() or 'SA'
    if city or country:
        search_params['user_location'] = {'type': 'approximate', 'city': city, 'country': country}
    budget = search_budget if isinstance(search_budget, dict) else {}
    for key in ('max_uses', 'max_total_results'):
        if key in budget:
            search_params[key] = max(1, min(search_params[key], int(budget[key])))
    budget_engine = ''
    if budget:
        budget_engine = str(budget.get('engine') or 'exa').strip() or 'exa'
        search_params['engine'] = budget_engine
        search_params['max_results'] = min(int(budget.get('max_results') or 6),
                                           max(1, int(max_search_results)))
        if budget_engine == 'exa':
            # Bounded scans are a quick comparison, not a market study — pin Exa's
            # fastest mode so a rough price sweep does not take the deep-search
            # path. 'instant' can come back blind on thin Arabic listing pages,
            # so a caller may override with budget['mode'] for a deeper retry.
            search_params['mode'] = str(budget.get('mode') or 'instant').strip() or 'instant'
    tools = [{
        'type': 'openrouter:web_search',
        'parameters': search_params,
    }]
    # The server tool leaves the search decision to the model, which could skip
    # it entirely and answer from memory — and on Google, `auto` native
    # grounding is model-decided too, so it silently does nothing. The `web`
    # plugin with engine `exa` runs the search on OpenRouter's side for EVERY
    # request and injects the retrieved pages — real grounding is guaranteed.
    plugin_engine = (os.environ.get('MARKET_SEARCH_PLUGIN_ENGINE') or '').strip()
    if not plugin_engine:
        # A native (Google) budget grounds through the provider itself — routing
        # the always-on plugin to Exa too would just double the search latency.
        plugin_engine = 'native' if (budget and budget_engine != 'exa') else 'exa'
    plugin = {
        'id': 'web',
        'engine': plugin_engine,
        'max_results': max(4, min(20, int(max_search_results or 8))),
    }
    if budget and plugin_engine == 'exa':
        plugin['mode'] = search_params.get('mode') or 'instant'
    plugins = [plugin]
    provider = {'order': ['Google'], 'allow_fallbacks': True}
    # Gemini returns reasoning and no content when tools are combined with JSON mode, so
    # that pair silently dropped the search on every call and the model answered from
    # memory with homepage links. Search first, JSON mode only as a fallback.
    attempts = ([
        (tools, None),
        (tools, {'type': 'json_object'}),
    ] if server_tools else []) + [
        (None, {'type': 'json_object'}),
        (None, None),
    ]
    if budget:
        # The forced web_search tool call is what makes a search actually run —
        # for engine 'native' OpenRouter executes it through the provider's own
        # search (Google grounding on Gemini); the plugin alone is model-decided
        # and silently returns memory answers.
        attempts = [(tools, None), (None, None)]
    last_response = {}
    last_error = ''
    # A parseable JSON with zero executed searches is kept as a fallback, never as a
    # success — the tool attempts get retried before a memory answer is accepted.
    unverified_response = None
    for _cap_attempt in range(1 if budget else 4):
        retry_cap = None
        for index, (attempt_tools, response_format) in enumerate(attempts):
            if unverified_response is not None and not attempt_tools:
                # A parseable memory answer is already in hand — tool-less
                # attempts can only produce another unverified one, at a cost.
                break
            if index:
                print(
                    '[MARKET STUDY] retrying competitor/summary call with '
                    f'tools={bool(attempt_tools)} json_mode={bool(response_format)}: '
                    f'{_chat_error_message(last_response)}'
                )
            last_response = call_openrouter_chat(
                system_prompt,
                user_content,
                temperature=None,
                max_tokens=cap,
                model=MARKET_STUDY_MODEL,
                response_format=response_format,
                provider=provider,
                tools=attempt_tools,
                plugins=plugins,
                timeout=max(15, min(240, int(budget.get('timeout', 240)))),
                reasoning_effort=reasoning_effort or budget.get('reasoning_effort'),
                usage_ctx=usage_ctx or _usage_ctx('market'),
                max_tool_calls=max(1, min(14, int(budget.get('max_tool_calls', 14)))),
                # Bounded scans may not answer from memory: force the tool so
                # a real search executes instead of a model-decided skip.
                tool_choice='required' if attempt_tools and budget else None,
            )
            last_error = _chat_error_message(last_response)
            text = _get_chat_response_text(last_response)
            if _has_chat_choices(last_response) and parse_json_object(text):
                finish = ''
                first_choice = (last_response.get('choices') or [{}])[0]
                if isinstance(first_choice, dict):
                    finish = str(first_choice.get('native_finish_reason')
                                 or first_choice.get('finish_reason') or '')
                clean_finish = finish.lower() in ('', 'stop', 'end_turn', 'length')
                if last_response.get('error') or not clean_finish:
                    # The provider aborted the answer (e.g. MALFORMED_FUNCTION_CALL)
                    # or attached an error to it: a parseable fragment is not a
                    # usable result, and returning it with an empty error ships
                    # the failure as a silent success.
                    last_error = _chat_error_message(last_response)
                    last_response = {'error': {'message': last_error}}
                    continue
                if attempt_tools and not _market_search_ran(last_response):
                    print('[MARKET STUDY] parseable JSON but zero searches ran — '
                          'keeping it as fallback and retrying with tools')
                    if unverified_response is None:
                        unverified_response = last_response
                    continue
                return last_response, ''
            quoted = _chat_affordable_tokens(last_response) or 0
            if quoted:
                candidate = max(2000, int(quoted * 0.85))
                if candidate < cap:
                    retry_cap = candidate
                    break
        if retry_cap is None:
            break
        print(f'[MARKET STUDY] provider refused cap={cap}; retrying with cap={retry_cap}')
        cap = retry_cap
    if unverified_response is not None:
        return unverified_response, ''
    return last_response, last_error
