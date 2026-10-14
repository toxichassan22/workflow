# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Browse agent loop: one chat-completions conversation per research task. The
# task's own model (the big mind — MARKET_STUDY_MODEL for market work) decides
# when to web_search and which pages to open_url — and, for pages a passive
# read cannot serve, inspect_page/click_element/type_text/scroll_page let it
# operate the page like a user. This module executes those
# tool calls locally against the per-run headless-Chromium session
# (browser.py) and feeds each result back as a ``tool`` message, then
# repackages the outcome into the OpenRouter-shaped dict the market pipeline
# already parses — final text in choices[0].message.content and every opened
# page as a url_citation annotation, so downstream evidence handling treats
# genuinely-read pages as retrieved citations. Never raises: failures return
# {"error": …} plus the browse_trace accumulated so far.
#
# Optional run controls: a shared ``evidence_pool`` answers repeated queries
# and page opens from the job's stored evidence instead of re-driving the
# browser; ``deadline`` stops the loop cleanly when the job's time budget is
# spent; ``session`` lets the caller hand in a browser worker it owns (the
# agent never closes a session it did not open itself).
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import json
import os
import time


_DEFAULT_MAX_STEPS = 10
# Page text is capped twice: the model's tool result gets more room than the
# citation the answer carries downstream.
_PAGE_TEXT_TOOL_CAP = 12000
_PAGE_TEXT_CITATION_CAP = 8000
# One tool-result message never outgrows the transcript.
_TOOL_MESSAGE_CAP = 60000

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
        'أنت وكيل تصفّح ويب. أدواتك: web_search تُرجع عناوين وروابط ومقتطفات، '
        'و open_url تقرأ نص الصفحة الفعلي، و inspect_page تعرض عناصر الصفحة '
        'التفاعلية مرقّمة، و click_element و type_text و scroll_page تنفّذ عليها '
        '(أرقام العناصر تخص آخر نتيجة فقط). استخدم open_url للقراءة المباشرة، '
        'وأدوات التفاعل فقط حين تحتاج الصفحة إدخالًا أو ضغطًا أو تمريرًا. نفّذ '
        + _search_count_phrase(advertised) +
        ' كحد أقصى طوال المهمة، ثم افتح أقرب نتيجة للمطلوب — ويمكنك فتح أكثر من رابط '
        'في الخطوة نفسها — وأجِب بما طُلب منك فقط دون شرح خطواتك. لا تُعِد البحث بنفس '
        'الغرض: إن شحّت النتائج فافتح أفضل ما وجدت أو أجب بما لديك.\n\n'
    )


# The preamble budgets searches; the tool grants one grace call, then refuses —
# a weak SERP must never let the model re-phrase itself into the step cap (the
# round-2 review finding). The refusal is a directive the model can act on:
# open what you have, or answer. Callers with wider research tasks (the market
# summary) raise it via run_browse_agent's search_budget.
_SEARCH_BUDGET = 3
_SEARCH_BUDGET_REFUSAL = {
    'error': 'search_budget_exceeded',
    'notice': 'انتهت ميزانية البحث — افتح أفضل نتيجة لديك الآن أو أجِب بما وجدت، دون بحث إضافي',
}


# OpenAI/OpenRouter tool declarations — executed locally by this module, never
# by the provider: only pages open_url actually read become citations.
_BROWSER_TOOLS = [
    {
        'type': 'function',
        'function': {
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
    },
    {
        'type': 'function',
        'function': {
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
    },
    # The interaction surface — for pages a passive read cannot serve (SPA
    # filters, site search boxes, lazy listings). Element indexes come from
    # the latest inspect_page/action result only.
    {
        'type': 'function',
        'function': {
            'name': 'inspect_page',
            'description': ('Open a page (or re-read the current one when url is '
                            'omitted) and return its interactive elements '
                            'numbered, alongside the readable text. Use when a '
                            'page needs input, a click or scrolling — filters, '
                            'search boxes, tabs, menus.'),
            'parameters': {
                'type': 'object',
                'properties': {
                    'url': {'type': 'string',
                            'description': 'Absolute page URL to open first (optional)'},
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'click_element',
            'description': ('Click the element carrying this number in the latest '
                            'inspect_page/action result. Returns the updated page '
                            'state with fresh element numbers.'),
            'parameters': {
                'type': 'object',
                'properties': {
                    'index': {'type': 'integer',
                              'description': 'Element number from the latest element list'},
                },
                'required': ['index'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'type_text',
            'description': ('Fill the input element carrying this number with text; '
                            'set submit=true to press Enter afterwards (site search '
                            'boxes). Returns the updated page state.'),
            'parameters': {
                'type': 'object',
                'properties': {
                    'index': {'type': 'integer',
                              'description': 'Input element number from the latest list'},
                    'text': {'type': 'string', 'description': 'Text to type'},
                    'submit': {'type': 'boolean',
                               'description': 'Press Enter after typing (default false)'},
                },
                'required': ['index', 'text'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'scroll_page',
            'description': ("Scroll the current page ('down' default, or 'up') to "
                            'reveal lazy-loaded content. Returns the updated page '
                            'state.'),
            'parameters': {
                'type': 'object',
                'properties': {
                    'direction': {'type': 'string', 'enum': ['down', 'up']},
                },
            },
        },
    },
]

# Soft pool failure reasons an interactive open may retry: both mean "the
# passive read got a shell", which is exactly what inspect_page exists for.
# Hard failures (timeout, http_*, blocked) still short-circuit.
_RETRYABLE_PAGE_FAILURES = {'needs_interaction', 'thin_content'}
_ACTION_TOOLS = ('click_element', 'type_text', 'scroll_page')


def openrouter_chat(messages, **kwargs):
    """Indirection over the app's messages transport so tests patch this name.

    ``call_openrouter_messages`` lives in the app namespace — it carries the
    tenant-key gate and per-round usage metering, so it is resolved from
    ``sys.modules`` at call time and this module stays importable standalone.
    Transport exceptions collapse into the agent's never-raise contract.
    """
    import sys
    _app = sys.modules.get('app')
    fn = getattr(_app, 'call_openrouter_messages', None) if _app is not None else None
    if not callable(fn):
        return {'error': {'message': 'openrouter messages transport unavailable'}}
    try:
        return fn(messages, **kwargs)
    except Exception as exc:
        return {'error': {'message': str(exc) or exc.__class__.__name__}}


class _ReplyError(Exception):
    """A provider-level failure; ``payload`` keeps the response's error dict —
    including fatal refusal fields — so callers see the real refusal."""

    def __init__(self, payload):
        payload = payload if isinstance(payload, dict) else {'message': str(payload)}
        super().__init__(str(payload.get('message') or 'provider error'))
        self.payload = payload


def _normalize_reply(response):
    """{content, tool_calls, raw_message} out of one chat-completions reply."""
    if not isinstance(response, dict):
        raise _ReplyError({'message': 'provider returned a non-dict response'})
    err = response.get('error')
    if err:
        raise _ReplyError(err)
    choices = response.get('choices')
    if not isinstance(choices, list) or not choices:
        raise _ReplyError({'message': 'provider returned no choices'})
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get('message') if isinstance(choice.get('message'), dict) else {}
    content = message.get('content')
    if isinstance(content, list):
        content = ''.join(
            part.get('text', '') if isinstance(part, dict) else str(part)
            for part in content)
    if not str(content or '').strip():
        # Some backends stream the answer only through the reasoning channel.
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
    return {'content': str(content or ''), 'tool_calls': tool_calls,
            'raw_message': message}


def _assistant_echo(msg):
    """Rebuild the assistant turn for the wire: original tool_calls verbatim
    (arguments stay serialized), reasoning_details ride along when present."""
    out = {'role': 'assistant', 'content': msg.get('content') or None}
    raw = msg.get('raw_message') or {}
    if raw.get('tool_calls'):
        out['tool_calls'] = raw['tool_calls']
    if raw.get('reasoning_details'):
        out['reasoning_details'] = raw['reasoning_details']
    return out


def _tool_message(call, result):
    """The ``tool`` role message answering one tool call."""
    return {'role': 'tool',
            'tool_call_id': str(call.get('id') or ''),
            'content': json.dumps(result, ensure_ascii=False)[:_TOOL_MESSAGE_CAP]}


def _effort_refusal(response):
    """Provider rejected the reasoning effort knob — retry once without it."""
    err = response.get('error') if isinstance(response, dict) else None
    if not err:
        return False
    text = json.dumps(err, ensure_ascii=False, default=str).lower()
    return 'reasoning' in text or 'effort' in text or 'thinking' in text


def _browser_session():
    """Return a fresh per-run browser context manager from browser.py.

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


def _run_web_search(session, args, search_state, evidence_pool=None):
    query = str(args.get('query') or '').strip()
    if not query:
        return {'error': 'empty_query'}
    cached = _pool_query(evidence_pool, query)
    if cached is not None:
        # A pooled answer costs no search — it does not consume the budget.
        _log_line(f'[BROWSE AGENT] pool hit query={query[:120]}')
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
    # A real execution is recorded — an errored search is not, so a later
    # stage may retry a transiently failed lookup.
    _pool_store_query(evidence_pool, query, compact)
    return {'results': compact}


def _run_open_url(session, args, trace, pages, evidence_pool=None):
    url = str(args.get('url') or '').strip()
    if not url:
        return {'error': 'empty_url'}
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


def _log_line(line):
    """Terse progress line. Logging must never kill a run — cp1252 consoles
    cannot encode the Arabic hints, so fall back to an escaped form."""
    try:
        print(line)
    except UnicodeEncodeError:
        try:
            print(line.encode('ascii', 'backslashreplace').decode('ascii'))
        except Exception:
            pass
    except Exception:
        pass


def _log_step(step, tool_name, hint):
    _log_line(f"[BROWSE AGENT] step {step}: tool={tool_name} url/query={hint}")


# Evidence-pool glue. The pool (modules/web_browse/evidence.py) is optional
# and duck-typed — this module must stay importable standalone, so every call
# goes through a guard that treats a missing/broken pool as "nothing cached"
# and never lets pool bookkeeping kill a run.
def _pool_query(evidence_pool, query):
    """Stored results for this query — None means the pool never ran it."""
    getter = getattr(evidence_pool, 'query_results', None)
    if not callable(getter):
        return None
    try:
        return getter(query)
    except Exception:
        return None


def _pool_store_query(evidence_pool, query, results):
    add = getattr(evidence_pool, 'add_query', None)
    if callable(add):
        try:
            add(query, results)
        except Exception:
            pass


def _pool_page(evidence_pool, url):
    getter = getattr(evidence_pool, 'get_page', None)
    if not callable(getter):
        return None
    try:
        page = getter(url)
    except Exception:
        return None
    return page if isinstance(page, dict) else None


def _pool_page_failed(evidence_pool, url):
    getter = getattr(evidence_pool, 'page_failed', None)
    if not callable(getter):
        return None
    try:
        return getter(url)
    except Exception:
        return None


def _pool_add_page(evidence_pool, url, title, content, final_url):
    add = getattr(evidence_pool, 'add_page', None)
    if callable(add):
        try:
            add(url, title=title, content=content,
                final_url=final_url, via='browser')
        except Exception:
            pass


def _pool_mark_failed(evidence_pool, url, reason):
    mark = getattr(evidence_pool, 'mark_failed', None)
    if callable(mark):
        try:
            mark(url, reason)
        except Exception:
            pass


def _absorb_state(result, url, trace, pages, evidence_pool=None,
                  action=None):
    """Shared tail for the interaction tools: an errored result is traced and
    pooled as a failure; a successful one is a genuinely-read page — it lands
    in the run's citation set and the job's evidence pool, and the tool gets
    back url/title/text plus the fresh numbered-elements list."""
    result = result if isinstance(result, dict) else {}
    title = str(result.get('title') or '')
    text = str(result.get('text') or '')
    final_url = str(result.get('final_url') or result.get('url')
                    or url).strip() or url
    error = result.get('error')
    entry = {'url': final_url, 'title': title, 'chars': len(text)}
    if action:
        entry['action'] = action
    if error:
        entry['error'] = str(error)
        trace.append(entry)
        if final_url.startswith('http'):
            _pool_mark_failed(evidence_pool, final_url, str(error))
        return {'url': final_url or url, 'error': str(error)}
    trace.append(entry)
    if final_url.startswith('http'):
        pages[final_url] = {'title': title,
                            'content': text[:_PAGE_TEXT_CITATION_CAP]}
        _pool_add_page(evidence_pool, final_url, title, text, final_url)
    out = {'url': final_url, 'title': title,
           'text': text[:_PAGE_TEXT_TOOL_CAP]}
    elements = result.get('elements')
    if isinstance(elements, list):
        out['elements'] = elements
    return out


def _run_inspect_page(session, args, trace, pages, evidence_pool=None):
    """The interactive open: numbered elements + text. A URL the pool marked
    'needs_interaction'/'thin_content' is exactly what this tool exists for —
    those soft failures are bypassed; hard failures still short-circuit."""
    url = str(args.get('url') or '').strip()
    if url:
        failed_reason = _pool_page_failed(evidence_pool, url)
        if failed_reason is not None \
                and str(failed_reason) not in _RETRYABLE_PAGE_FAILURES:
            trace.append({'url': url, 'title': '', 'chars': 0,
                          'error': str(failed_reason), 'pool': True})
            return {'url': url, 'error': str(failed_reason)}
    fn = _tool_callable(session, 'inspect_page')
    if fn is None:
        return {'error': 'inspect_page_unavailable'}
    try:
        result = fn(url) if url else fn()
    except TypeError:
        # A narrower fake/older session without the url parameter.
        try:
            result = fn()
        except Exception as exc:
            return {'error': str(exc) or exc.__class__.__name__}
    except Exception as exc:
        return {'error': str(exc) or exc.__class__.__name__}
    return _absorb_state(result, url, trace, pages, evidence_pool,
                         action='inspect_page' if url else None)


def _run_page_action(session, name, args, trace, pages, evidence_pool=None):
    """click_element / type_text / scroll_page on the worker's live page."""
    fn = _tool_callable(session, name)
    if fn is None:
        return {'error': f'{name}_unavailable'}
    try:
        if name == 'click_element':
            result = fn(int(args.get('index')))
        elif name == 'type_text':
            result = fn(int(args.get('index')), str(args.get('text') or ''),
                        submit=bool(args.get('submit')))
        elif name == 'scroll_page':
            result = fn(str(args.get('direction') or 'down'))
        else:
            return {'error': 'unknown_tool'}
    except (TypeError, ValueError):
        return {'error': 'invalid_arguments'}
    except Exception as exc:
        return {'error': str(exc) or exc.__class__.__name__}
    return _absorb_state(result, '', trace, pages, evidence_pool,
                         action=name)


def _execute_tool(session, name, args, trace, pages, search_state,
                  evidence_pool=None):
    """Dispatch one model tool call. Returns the compact tool-result payload —
    errors are data, never exceptions."""
    name = str(name or '').strip()
    args = args if isinstance(args, dict) else {}
    if name == 'web_search':
        return _run_web_search(session, args, search_state, evidence_pool)
    if name == 'open_url':
        return _run_open_url(session, args, trace, pages, evidence_pool)
    if name == 'inspect_page':
        return _run_inspect_page(session, args, trace, pages, evidence_pool)
    if name in _ACTION_TOOLS:
        return _run_page_action(session, name, args, trace, pages,
                                evidence_pool)
    return {'error': 'unknown_tool'}


def run_browse_agent(task, max_steps=None, usage_ctx=None, search_budget=None,
                     max_tokens=None, reasoning_effort=None, model=None,
                     evidence_pool=None, deadline=None, session=None):
    """Drive one OpenRouter tool-call loop against a real browser session.

    ``model`` is the caller's own task model — the same model that would have
    answered the request without tools (MARKET_STUDY_MODEL for market work);
    ``None`` leaves the transport's default. ``search_budget`` raises/lowers
    the hard web_search cap (default 3 — one more than the preamble
    advertises); ``max_tokens`` is the per-round output cap (default 4000 — a
    market-summary JSON needs MARKET_STUDY_MAX_TOKENS); ``reasoning_effort``
    passes straight through and is dropped for the rest of the run if the
    provider refuses it.

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
    try:
        deadline = float(deadline) if deadline is not None else None
    except (TypeError, ValueError):
        deadline = None

    def _deadline_hit():
        return deadline is not None and time.time() >= deadline

    messages = [
        {'role': 'system', 'content': _agent_preamble(budget)},
        {'role': 'user', 'content': str(task or '')},
    ]
    session_cm = None
    search_state = {'count': 0, 'budget': budget}

    def _round():
        kwargs = {'tools': _BROWSER_TOOLS, 'max_tokens': out_cap,
                  'usage_ctx': usage_ctx}
        if model:
            kwargs['model'] = model
        if effort and not effort_disabled:
            kwargs['reasoning_effort'] = effort
        return openrouter_chat(messages, **kwargs)

    try:
        for step in range(max_steps):
            if _deadline_hit():
                error = {'message': 'deadline_exceeded'}
                break
            response = _round()
            if effort and not effort_disabled and _effort_refusal(response):
                # The hint is model-specific — a provider that rejects it gets
                # the rest of the run without it, same model either way.
                if _deadline_hit():
                    error = {'message': 'deadline_exceeded'}
                    break
                effort_disabled = True
                response = _round()
            usage_meta = (response.get('usage')
                          if isinstance(response, dict) else None) or {}
            try:
                prompt_tokens += int(usage_meta.get('prompt_tokens') or 0)
                completion_tokens += int(usage_meta.get('completion_tokens') or 0)
            except (TypeError, ValueError):
                pass
            try:
                msg = _normalize_reply(response)
            except _ReplyError as exc:
                error = exc.payload
                break
            if not msg['tool_calls']:
                final_text = str(msg.get('content') or '').strip()
                if not final_text:
                    error = {'message': 'model returned no text and no tool call'}
                break
            if session is None:
                # No point launching the caller's browser once the budget is
                # spent — the deadline wins over a pending tool call.
                if _deadline_hit():
                    error = {'message': 'deadline_exceeded'}
                    break
                session_cm = _browser_session()
                session = session_cm.__enter__()
            # Echo the model's message (raw tool_calls keep their serialized
            # arguments), then answer each call with a tool result message.
            messages.append(_assistant_echo(msg))
            for call in msg['tool_calls']:
                if _deadline_hit():
                    error = {'message': 'deadline_exceeded'}
                    break
                args = call['arguments']
                hint = str(args.get('url') or args.get('query') or '')[:120]
                _log_step(step + 1, call['name'] or '?', hint)
                result = _execute_tool(session, call['name'], args,
                                       trace, pages, search_state,
                                       evidence_pool)
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
    _log_line(f"[BROWSE AGENT] done: pages={len(pages)} trace={len(trace)} "
              f"{'error=' + str((error or {}).get('message')) if error else 'ok'}")
    annotations = [{'url_citation': {'url': url, 'title': page['title'],
                                     'content': page['content']}}
                   for url, page in pages.items()]
    if error:
        result = {'error': error, 'usage': usage, 'browse_trace': trace}
        if annotations:
            # Pages gathered before the failure stay visible to the caller —
            # a deadline stops the loop, it does not throw away evidence.
            result['annotations'] = annotations
        return result
    return {'choices': [{'message': {'role': 'assistant',
                                    'content': final_text,
                                    'annotations': annotations}}],
            'usage': usage,
            'browse_trace': trace}
