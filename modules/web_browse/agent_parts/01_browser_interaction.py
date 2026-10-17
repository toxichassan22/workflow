# Browser session and page tools. Executed into agent.py globals.

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


def _run_web_search(session, args, search_state, evidence_pool=None):
    query = str(args.get('query') or '').strip()
    if not query:
        return {'error': 'empty_query'}
    cached = _pool_query(evidence_pool, query)
    if cached is not None:
        # A pooled answer costs no search — it does not consume the budget.
        _log_line(f'[BROWSE AGENT] pool hit query={query[:120]}')
        if cached:
            search_state['had_results'] = True
        return {'results': [
            {'title': str(item.get('title') or ''),
             'url': str(item.get('url') or ''),
             'snippet': str(item.get('snippet') or '')}
            for item in cached if isinstance(item, dict)]}
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
        results = fn(query, max_results=max_results) if max_results > 0 else fn(query)
    except TypeError:
        # Older/narrower signature without max_results.
        results = fn(query)
    except Exception as exc:
        return {'error': str(exc) or exc.__class__.__name__}
    compact = []
    for item in results or []:
        if not isinstance(item, dict):
            continue
        compact.append({'title': str(item.get('title') or ''),
                        'url': str(item.get('url') or ''),
                        'snippet': str(item.get('snippet') or '')})
    if compact:
        search_state['had_results'] = True
    # A real execution is recorded — an errored search is not, so a later
    # stage may retry a transiently failed lookup.
    _pool_store_query(evidence_pool, query, compact)
    return {'results': compact}


def _run_open_url(session, args, trace, pages, evidence_pool=None):
    url = str(args.get('url') or '').strip()
    if not url:
        return {'error': 'empty_url'}
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
    trace.append({'url': final_url, 'title': title, 'chars': len(text)})
    if final_url not in pages:
        pages[final_url] = {'title': title, 'content': text[:_PAGE_TEXT_CITATION_CAP]}
    _pool_add_page(evidence_pool, url, title, text, final_url)
    return {'url': final_url, 'title': title, 'text': text[:_PAGE_TEXT_TOOL_CAP]}
