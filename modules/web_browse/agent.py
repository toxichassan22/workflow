# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Browse agent loop (task A3): one Vertex generateContent conversation per
# research task. The model decides when to web_search and which pages to
# open_url; this module executes those calls against the per-run browser
# session (browser.py, task A1) and shapes the outcome into the
# OpenRouter-style dict the market verify path already parses — final text in
# choices[0].message.content and every opened page as a url_citation
# annotation, so downstream evidence handling treats genuinely-read pages as
# retrieved citations. Never raises: failures return {"error": …} plus the
# browse_trace accumulated so far.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import os


_DEFAULT_MAX_STEPS = 10
# Page text is capped twice: the model's tool result gets more room than the
# citation the answer carries downstream.
_PAGE_TEXT_TOOL_CAP = 12000
_PAGE_TEXT_CITATION_CAP = 8000

def _search_count_phrase(count):
    """Arabic count wording for the preamble's search cap — dual for two,
    an explicit number otherwise."""
    if count == 1:
        return 'عملية بحث واحدة'
    if count == 2:
        return 'عمليتي بحث'
    return f'{count} عمليات بحث'


def _agent_preamble(budget):
    # The advertised cap keeps one grace search below the hard budget, so a
    # model that genuinely needs its last lookup is not slapped by the
    # refusal — at the default budget this reads «عمليتي بحث», unchanged.
    advertised = max(1, budget - 1)
    return (
        'أنت وكيل تصفّح ويب. لديك أداتان: web_search تُرجع عناوين وروابط ومقتطفات، '
        'و open_url تقرأ نص الصفحة الفعلي. نفّذ ' + _search_count_phrase(advertised) +
        ' كحد أقصى طوال المهمة، ثم افتح أقرب نتيجة للمطلوب — ويمكنك فتح أكثر من رابط '
        'في الخطوة نفسها — وأجِب بما طُلب منك فقط دون شرح خطواتك. لا تُعِد البحث بنفس '
        'الغرض: إن شحّت النتائج فافتح أفضل ما وجدت أو أجب بما لديك.\n\n'
    )


# The preamble budgets two searches; the tool grants one grace call, then
# refuses — a weak SERP must never let the model re-phrase itself into the
# step cap (the round-2 review finding). The refusal is a directive the model
# can act on: open what you have, or answer. Callers with wider research
# tasks (the market summary) raise it via run_browse_agent's search_budget.
_SEARCH_BUDGET = 3
_SEARCH_BUDGET_REFUSAL = {
    'error': 'search_budget_exceeded',
    'notice': 'انتهت ميزانية البحث — افتح أفضل نتيجة لديك الآن أو أجِب بما وجدت، دون بحث إضافي',
}


def _tool_declarations():
    """functionDeclarations the model may call — the A1 browser surface."""
    return [{
        'functionDeclarations': [
            {
                'name': 'web_search',
                'description': 'Search the web; returns result titles, URLs and snippets.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {'type': 'string', 'description': 'Search query text'},
                        'max_results': {'type': 'integer',
                                        'description': 'Maximum results to return (default 8)'},
                    },
                    'required': ['query'],
                },
            },
            {
                'name': 'open_url',
                'description': 'Open a web page; returns its final URL, title and readable text.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'url': {'type': 'string', 'description': 'Absolute page URL'},
                    },
                    'required': ['url'],
                },
            },
        ],
    }]


def vertex_generate(contents, tools=None, model=None, max_tokens=4000, thinking='low'):
    """Indirection over vertex_client so tests patch a name on this module.

    The sibling module is imported at call time — agent.py stays importable
    before A1/A2 land and without Playwright installed.
    """
    import vertex_client
    return vertex_client.vertex_generate(contents, tools=tools, model=model,
                                         max_tokens=max_tokens, thinking=thinking)


def _browser_session():
    """Return a fresh per-run browser context manager from A1's browser.py.

    Accepts either contract shape: a browser_session() context-manager factory
    or a BrowserWorker class used as a context manager.
    """
    import browser as _browser
    factory = getattr(_browser, 'browser_session', None)
    if callable(factory):
        return factory()
    worker = getattr(_browser, 'BrowserWorker', None)
    if worker is not None:
        return worker()
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


def _run_web_search(session, args, search_state):
    if search_state['count'] >= search_state.get('budget', _SEARCH_BUDGET):
        return dict(_SEARCH_BUDGET_REFUSAL)
    search_state['count'] += 1
    query = str(args.get('query') or '').strip()
    if not query:
        return {'error': 'empty_query'}
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
    return {'results': compact}


def _run_open_url(session, args, trace, pages):
    url = str(args.get('url') or '').strip()
    if not url:
        return {'error': 'empty_url'}
    fn = _tool_callable(session, 'open_url')
    if fn is None:
        trace.append({'url': url, 'title': '', 'chars': 0, 'error': 'open_url_unavailable'})
        return {'url': url, 'error': 'open_url_unavailable'}
    try:
        result = fn(url)
    except Exception as exc:
        trace.append({'url': url, 'title': '', 'chars': 0,
                      'error': str(exc) or exc.__class__.__name__})
        return {'url': url, 'error': 'open_failed'}
    result = result if isinstance(result, dict) else {}
    title = str(result.get('title') or '')
    text = str(result.get('text') or '')
    error = result.get('error')
    if error:
        trace.append({'url': url, 'title': title, 'chars': 0, 'error': str(error)})
        return {'url': url, 'error': str(error)}
    final_url = str(result.get('final_url') or result.get('url') or url).strip() or url
    trace.append({'url': final_url, 'title': title, 'chars': len(text)})
    if final_url not in pages:
        pages[final_url] = {'title': title, 'content': text[:_PAGE_TEXT_CITATION_CAP]}
    return {'url': final_url, 'title': title, 'text': text[:_PAGE_TEXT_TOOL_CAP]}


def _log_step(step, tool_name, hint):
    """Terse progress line. Logging must never kill a run — cp1252 consoles
    cannot encode the Arabic hints, so fall back to an escaped form."""
    line = f"[BROWSE AGENT] step {step}: tool={tool_name} url/query={hint}"
    try:
        print(line)
    except UnicodeEncodeError:
        try:
            print(line.encode('ascii', 'backslashreplace').decode('ascii'))
        except Exception:
            pass
    except Exception:
        pass


def _execute_tool(session, name, args, trace, pages, search_state):
    """Dispatch one model functionCall. Returns the compact functionResponse
    payload — errors are data, never exceptions."""
    name = str(name or '').strip()
    args = args if isinstance(args, dict) else {}
    if name == 'web_search':
        return _run_web_search(session, args, search_state)
    if name == 'open_url':
        return _run_open_url(session, args, trace, pages)
    return {'error': 'unknown_tool'}


def _record_agent_usage(usage_ctx, model, status, usage):
    """Meter the whole run once through the app's ai_usage path.

    Best-effort only: meters only when the app is already loaded (the running
    server and the test suite), so a standalone probe neither boots Flask nor
    writes billing rows. A Vertex call carries no generation id, so the row
    stays cost-unresolved — honest, since billing settles on GCP not OpenRouter.
    """
    try:
        import sys
        _app = sys.modules.get('app')
        recorder = getattr(_app, '_record_ai_usage', None) if _app is not None else None
        if callable(recorder):
            recorder(usage_ctx, model, status=status, usage=usage)
    except Exception:
        pass


def run_browse_agent(task, max_steps=None, usage_ctx=None,
                     search_budget=None, max_tokens=None, thinking=None):
    """Drive one Vertex tool-use loop against a real browser session.

    Returns an OpenRouter-shaped dict: choices[0].message.content holds the
    model's final text, every successfully opened page becomes a url_citation
    annotation ({url, title, content} — text capped at 8K) and browse_trace
    lists every open attempt including failures. Transport errors and a step
    cap without final text return {"error": …} instead of raising.

    ``search_budget`` raises/lowers the hard web_search cap (default 3 — one
    more than the preamble advertises); ``max_tokens`` is the per-call output
    cap (default 4000 — a market-summary JSON needs MARKET_STUDY_MAX_TOKENS);
    ``thinking`` passes to generationConfig.thinkingLevel (default 'low').
    """
    trace = []
    pages = {}
    prompt_tokens = 0
    completion_tokens = 0
    model_seen = None
    final_text = ''
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
    thinking = str(thinking or 'low').strip() or 'low'

    contents = [{'role': 'user',
                 'parts': [{'text': _agent_preamble(budget) + str(task or '')}]}]
    session_cm = None
    session = None
    search_state = {'count': 0, 'budget': budget}
    try:
        for step in range(max_steps):
            response = vertex_generate(contents, tools=_tool_declarations(),
                                       max_tokens=out_cap, thinking=thinking)
            if not isinstance(response, dict):
                error = {'message': 'vertex transport returned a non-dict response'}
                break
            model_seen = response.get('modelVersion') or model_seen
            meta = response.get('usageMetadata') or {}
            try:
                prompt_tokens += int(meta.get('promptTokenCount') or 0)
                completion_tokens += int(meta.get('candidatesTokenCount') or 0)
            except (TypeError, ValueError):
                pass
            transport_error = response.get('error')
            if transport_error:
                error = transport_error if isinstance(transport_error, dict) \
                    else {'message': str(transport_error)}
                break
            candidates = response.get('candidates') or []
            content = ((candidates[0] or {}).get('content') or {}) if candidates else {}
            parts = [p for p in (content.get('parts') or []) if isinstance(p, dict)]
            calls = [p.get('functionCall') for p in parts
                     if isinstance(p.get('functionCall'), dict)]
            if not calls:
                final_text = '\n'.join(str(p.get('text')) for p in parts
                                       if p.get('text')).strip()
                if not final_text:
                    error = {'message': 'model returned no text and no tool call'}
                break
            if session is None:
                session_cm = _browser_session()
                session = session_cm.__enter__()
            # Echo the model's parts verbatim (keeps any signature fields the
            # API attaches), then the tool results as one user turn.
            contents.append({'role': 'model', 'parts': parts})
            replies = []
            for call in calls:
                tool_name = str(call.get('name') or '').strip()
                tool_args = call.get('args') if isinstance(call.get('args'), dict) else {}
                hint = str(tool_args.get('url') or tool_args.get('query') or '')[:120]
                _log_step(step + 1, tool_name or '?', hint)
                replies.append({'functionResponse': {
                    'name': tool_name or 'unknown',
                    'response': _execute_tool(session, tool_name, tool_args,
                                              trace, pages, search_state)}})
            contents.append({'role': 'user', 'parts': replies})
        else:
            error = {'message': f'max_steps reached ({max_steps}) without a final answer'}
    except Exception as exc:
        error = {'message': str(exc) or exc.__class__.__name__}
    finally:
        if session_cm is not None:
            try:
                session_cm.__exit__(None, None, None)
            except Exception:
                pass

    usage = {'prompt_tokens': prompt_tokens,
             'completion_tokens': completion_tokens,
             'total_tokens': prompt_tokens + completion_tokens}
    model_name = model_seen or os.environ.get('BROWSER_AGENT_MODEL') or 'browser-agent'
    _record_agent_usage(usage_ctx, model_name, 'error' if error else 'ok', usage)
    try:
        print(f"[BROWSE AGENT] done: pages={len(pages)} trace={len(trace)} "
              f"{'error=' + str((error or {}).get('message')) if error else 'ok'}")
    except Exception:
        pass
    if error:
        return {'error': error, 'usage': usage, 'browse_trace': trace}
    annotations = [{'url_citation': {'url': url, 'title': page['title'],
                                     'content': page['content']}}
                   for url, page in pages.items()]
    return {'choices': [{'message': {'role': 'assistant',
                                    'content': final_text,
                                    'annotations': annotations}}],
            'usage': usage,
            'browse_trace': trace}
