# Browser session and page tools. Executed into agent.py globals.

_BROWSE_FATAL_ERROR_CODES = {
    'INSUFFICIENT_BALANCE', 'INSUFFICIENT_CREDITS',
    'PROVIDER_CREDITS_EXHAUSTED', 'TRIAL_EXPIRED', 'NO_TENANT_KEY',
    'TENANT_KEY_CHECK_FAILED', 'BILLING_CHECK_UNAVAILABLE',
}


def _browse_fatal_provider_response(response):
    error = response.get('error') if isinstance(response, dict) else None
    if not isinstance(error, dict):
        return False
    if (error.get('fatal')
            or str(error.get('error_code') or error.get('code') or '').upper()
            in _BROWSE_FATAL_ERROR_CODES):
        return True
    try:
        return int(error.get('http_status') or error.get('status') or error.get('code') or 0) == 402
    except (TypeError, ValueError):
        return False


def _provider_affordable_token_limit(response):
    """Return a non-fatal output-token allowance quoted by OpenRouter."""
    error = response.get('error') if isinstance(response, dict) else None
    if not isinstance(error, dict):
        return None
    if _browse_fatal_provider_response(response) or error.get('error_code'):
        return None
    for value in (error.get('provider_message'), error.get('message')):
        match = re.search(r'can only afford\s+(\d+)', str(value or ''), re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return None
    return None

def _browser_session(search_provider=None):
    """Return a fresh per-run browser context manager from browser.py.

    Accepts either contract shape: a browser_session() context-manager factory
    or a BrowserWorker class used as a context manager.
    """
    import browser as _browser
    factory = getattr(_browser, 'browser_session', None)
    if callable(factory):
        return factory(search_provider=search_provider)
    worker = getattr(_browser, 'BrowserWorker', None)
    if worker is not None:
        return worker(search_provider=search_provider)
    raise ImportError('browser module exposes neither browser_session nor BrowserWorker')


def _tool_callable(session, name):
    """Tool functions are methods on the session when it exposes them, else
    module-level functions on browser.py."""
    fn = getattr(session, name, None)
    if callable(fn):
        return fn
    try:
        import browser as _browser
        fn = getattr(_browser, name, None)
        return fn if callable(fn) else None
    except Exception:
        return None


def _run_web_search(session, args, search_state, evidence_pool=None,
                    allowed_hosts=None):
    query = str(args.get('query') or '').strip()
    if not query:
        return {'error': 'empty_query'}
    scoped_query = _source_scoped_query(query, allowed_hosts)
    if not scoped_query:
        return {'error': 'allowed_sources_required'}
    cached = _pool_query(evidence_pool, scoped_query)
    if cached is not None:
        # A pooled answer costs no search — it does not consume the budget.
        _log_line(f'[BROWSE AGENT] pool hit query={scoped_query[:120]}')
        allowed_cached = [item for item in cached if isinstance(item, dict)
                          and _source_url_allowed(item.get('url'), allowed_hosts)]
        if allowed_cached:
            search_state['had_results'] = True
        return {'results': [
            {'title': str(item.get('title') or ''),
             'url': str(item.get('url') or ''),
             'snippet': str(item.get('snippet') or '')}
            for item in allowed_cached]}
    if search_state['count'] >= search_state.get('budget', _SEARCH_BUDGET):
        return dict(_SEARCH_BUDGET_REFUSAL)
    search_state['count'] += 1
    fn = _tool_callable(session, 'web_search')
    if fn is None:
        return {'error': 'web_search_unavailable'}
    try:
        max_results = int(args.get('max_results') or 0)
    except (TypeError, ValueError):
        max_results = 0
    try:
        results = (fn(scoped_query, max_results=max_results)
                   if max_results > 0 else fn(scoped_query))
    except TypeError:
        # Older/narrower signature without max_results.
        results = fn(scoped_query)
    except Exception as exc:
        return {'error': str(exc) or exc.__class__.__name__}
    compact = []
    blocked = 0
    for item in results or []:
        if not isinstance(item, dict):
            continue
        if not _source_url_allowed(item.get('url'), allowed_hosts):
            blocked += 1
            continue
        compact.append({'title': str(item.get('title') or ''),
                        'url': str(item.get('url') or ''),
                        'snippet': str(item.get('snippet') or '')})
    if compact:
        search_state['had_results'] = True
    # A real execution is recorded — an errored search is not, so a later
    # stage may retry a transiently failed lookup.
    _pool_store_query(evidence_pool, scoped_query, compact)
    return {'results': compact, 'filtered_outside_allowed_sources': blocked}


def _run_open_url(session, args, trace, pages, evidence_pool=None,
                  allowed_hosts=None):
    url = str(args.get('url') or '').strip()
    if not url:
        return {'error': 'empty_url'}
    # Rewrite before the pool lookup so a page cached without a stay cannot
    # answer a hotel open; the dated URL is also the evidence URL downstream.
    url = hotel_stay.with_booking_stay_params(url)
    if not _source_url_allowed(url, allowed_hosts):
        trace.append({'url': url, 'title': '', 'chars': 0,
                      'error': 'outside_allowed_sources'})
        return {'url': url, 'error': 'outside_allowed_sources'}
    dead = _dead_url_shape(url)
    if dead:
        trace.append({'url': url, 'title': '', 'chars': 0, 'error': dead})
        _pool_mark_failed(evidence_pool, url, dead)
        return {'url': url, 'error': dead}
    failed_reason = _pool_page_failed(evidence_pool, url)
    if failed_reason is not None:
        # The job already tried this URL and failed — same answer, no refetch.
        trace.append({'url': url, 'title': '', 'chars': 0,
                      'error': str(failed_reason), 'pool': True})
        return {'url': url, 'error': str(failed_reason)}
    pooled = _pool_page(evidence_pool, url)
    if pooled is not None:
        _log_line(f'[BROWSE AGENT] pool hit url={url[:120]}')
        title = str(pooled.get('title') or '')
        content = str(pooled.get('content') or '')
        final_url = (str(pooled.get('final_url') or pooled.get('url')
                         or url).strip() or url)
        if not _source_url_allowed(final_url, allowed_hosts):
            trace.append({'url': final_url, 'title': title, 'chars': 0,
                          'error': 'redirected_outside_allowed_sources',
                          'pool': True})
            return {'url': url, 'error': 'redirected_outside_allowed_sources'}
        trace.append({'url': final_url, 'title': title,
                      'chars': len(content), 'pool': True})
        if final_url not in pages:
            pages[final_url] = {'title': title,
                                'content': content[:_PAGE_TEXT_CITATION_CAP]}
        return {'url': final_url, 'title': title,
                'text': content[:_PAGE_TEXT_TOOL_CAP]}
    fn = _tool_callable(session, 'open_url')
    if fn is None:
        trace.append({'url': url, 'title': '', 'chars': 0, 'error': 'open_url_unavailable'})
        return {'url': url, 'error': 'open_url_unavailable'}
    try:
        result = fn(url)
    except Exception as exc:
        reason = str(exc) or exc.__class__.__name__
        trace.append({'url': url, 'title': '', 'chars': 0, 'error': reason})
        _pool_mark_failed(evidence_pool, url, reason)
        return {'url': url, 'error': 'open_failed'}
    result = result if isinstance(result, dict) else {}
    title = str(result.get('title') or '')
    text = str(result.get('text') or '')
    error = result.get('error')
    if error:
        trace.append({'url': url, 'title': title, 'chars': 0, 'error': str(error)})
        _pool_mark_failed(evidence_pool, url, str(error))
        return {'url': url, 'error': str(error)}
    final_url = str(result.get('final_url') or result.get('url') or url).strip() or url
    rate = result.get('booking_rate') if isinstance(
        result.get('booking_rate'), dict) else None
    search = result.get('booking_search') if isinstance(
        result.get('booking_search'), dict) else None
    if not _source_url_allowed(final_url, allowed_hosts):
        trace.append({'url': final_url, 'title': title, 'chars': 0,
                      'error': 'redirected_outside_allowed_sources'})
        return {'url': url, 'error': 'redirected_outside_allowed_sources'}
    trace.append({'url': final_url, 'title': title, 'chars': len(text)})
    if final_url not in pages:
        page_entry = {'title': title, 'content': text[:_PAGE_TEXT_CITATION_CAP]}
        if rate:
            page_entry['booking_rate'] = rate
        if search:
            page_entry['booking_search'] = search
        pages[final_url] = page_entry
    _pool_add_page(evidence_pool, url, title, text, final_url)
    payload = {'url': final_url, 'title': title,
               'text': text[:_PAGE_TEXT_TOOL_CAP]}
    if rate:
        payload['booking_rate'] = rate
    if search:
        payload['booking_search'] = search
    return payload
