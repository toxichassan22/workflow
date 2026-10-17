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
import re
import time
from pathlib import Path


_DEFAULT_MAX_STEPS = 10
# Page text is capped twice: the model's tool result gets more room than the
# citation the answer carries downstream.
_PAGE_TEXT_TOOL_CAP = 12000
_PAGE_TEXT_CITATION_CAP = 8000
# One tool-result message never outgrows the transcript.
_TOOL_MESSAGE_CAP = 60000

# Context compaction: once the transcript passes this size, older tool
# results shrink to a digest — the model keeps the url and a head of the
# text for citing, never the same page twice at full length.
_HISTORY_COMPACT_CHARS = 90000
_KEEP_FULL_TOOL_MESSAGES = 4    # freshest tool results stay verbatim
_COMPACT_TOOL_CAP = 600

# One automatic squeeze when the model's answer ran into the output cap:
# it re-issues the same result compressed instead of failing on half a JSON.
_COMPACT_REPLY_PROMPT = (
    'إجابتك السابقة قُطعت عند حد الإخراج. أعد النتيجة نفسها الآن في صيغة '
    'أقصر: نفس بنية JSON والحقول، قيم مختصرة، بلا شرح أو تكرار.')

# Answering straight off search snippets leaves every source "unverified"
# downstream — nothing was ever read. When a run had real results to open
# but produced a final answer with zero pages, spend one step forcing it.
_OPEN_BEFORE_ANSWER_PROMPT = (
    'أجبت دون فتح أي صفحة من نتائج البحث — إجابة لم تقرأ صفحة واحدة لا تُقبل. '
    'افتح الآن بـ open_url أقرب رابط أو اثنين من النتائج للمطلوب، '
    'ثم أعد إجابتك معتمدًا على الصفحة المقروءة.')

# One provider hiccup must not kill a multi-minute job: an overloaded upstream,
# a rate limit, a 5xx or a dropped/timed-out transport re-issues the round in
# place a couple of times with backoff. Fatal refusals (tenant key, wallet,
# trial) and unrecognized errors never retry — a 400 or an auth rejection
# retried is just the job's deadline burning.
_TRANSIENT_MAX_RETRIES = 2
_TRANSIENT_BACKOFF_S = (4.0, 12.0)
_TRANSIENT_RETRY_CODES = {408, 409, 425, 429, 500, 502, 503, 504, 529}
_TRANSIENT_RETRY_TOKENS = (
    'overload', 'rate limit', 'rate_limit', 'too many request', 'temporar',
    'unavailable', 'capacity', 'timeout', 'timed out', 'connection',
    'مهلة', 'انقطع',
)

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


# Native-search runs declare no local browser tools — the model researches
# through provider-native search (e.g. Google grounding via the OpenRouter
# server tool) inside the request itself, so the preamble must not name
# web_search/open_url: those tools do not exist on the wire in this mode.
_NATIVE_PREAMBLE = (
    'أنت محلل سوق يعمل ببحث جوجل الأصلي. ابحث عبر البحث الأصلي أولًا — '
    'لا تجب من الذاكرة: نفّذ بحثًا منفصلًا لكل محور مطلوب في المهمة، ثم أجب '
    'بما طُلب منك فقط دون شرح خطواتك. الأرقام التقريبية من نتائج البحث مقبولة؛ '
    'رقم بلا بحث مرفوض.\n\n'
)


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

# URL shapes measured to cost a browser wait for zero evidence — path-level,
# not host bans: REGA's advanced-search grids sit behind Nafath (268-char
# login shell) and spa.gov.sa's non-/ar/ paths hang past the navigation
# timeout (22s -> 0 chars) while its /ar/ articles load normally. A match is
# refused before the browser launches, so a free-search pick cannot burn the
# job's deadline on a page that can never be read.
_DEAD_URL_SHAPES = (
    re.compile(r'rega\.gov\.sa/ar/advanced-search', re.I),
    re.compile(r'spa\.gov\.sa(?:/(?!ar/)|/?$)', re.I),
)


def _dead_url_shape(url):
    """The skip reason for a URL proven unreadable, or None."""
    for shape in _DEAD_URL_SHAPES:
        if shape.search(str(url or '')):
            return 'dead_source'
    return None


def _compact_tool_history(messages):
    """Shrink older tool results once the transcript runs long.

    Every tool message but the freshest ``_KEEP_FULL_TOOL_MESSAGES`` keeps
    its url/title plus a head of the text — enough to cite, small enough
    that a long browse run never pushes the next round over the edge.
    Returns True when anything was compacted.
    """
    total = 0
    for msg in messages:
        content = msg.get('content')
        total += len(content) if isinstance(content, str) \
            else len(json.dumps(content, ensure_ascii=False, default=str))
    if total <= _HISTORY_COMPACT_CHARS:
        return False
    tool_indexes = [i for i, msg in enumerate(messages)
                    if msg.get('role') == 'tool']
    if len(tool_indexes) <= _KEEP_FULL_TOOL_MESSAGES:
        return False
    compacted = False
    for index in tool_indexes[:-_KEEP_FULL_TOOL_MESSAGES]:
        content = messages[index].get('content')
        if not isinstance(content, str) or len(content) <= _COMPACT_TOOL_CAP:
            continue
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            for key in ('text', 'content', 'snippet'):
                value = parsed.get(key)
                if isinstance(value, str) and len(value) > _COMPACT_TOOL_CAP:
                    parsed[key] = value[:_COMPACT_TOOL_CAP] + ' ...'
            if isinstance(parsed.get('results'), list):
                parsed['results'] = parsed['results'][:5]
            parsed.pop('elements', None)
            new_content = json.dumps(parsed, ensure_ascii=False)
        else:
            new_content = content[:_COMPACT_TOOL_CAP] + ' ...'
        if len(new_content) < len(content):
            messages[index]['content'] = new_content
            compacted = True
    if compacted:
        _log_line('[BROWSE AGENT] compacted tool history')
    return compacted


def _truncated_reply(response):
    """The reply hit the output cap — finish_reason length/max_tokens."""
    if not isinstance(response, dict):
        return False
    choice = (response.get('choices') or [{}])[0]
    if not isinstance(choice, dict):
        return False
    finish = str(choice.get('native_finish_reason')
                 or choice.get('finish_reason') or '').lower()
    return finish in ('length', 'max_tokens')


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


def _transient_provider_error(payload):
    """True only for the retryable provider failures.

    The status may arrive as ``http_status``/``code`` on the error dict or as
    the ``[429]`` prefix the app transport stamps onto the message; wording
    covers the rest (OpenRouter's upstream 'Overloaded', Arabic transport
    messages). Anything fatal or unrecognized stays fatal.
    """
    if not isinstance(payload, dict) \
            or payload.get('fatal') or payload.get('error_code'):
        return False
    for key in ('http_status', 'code', 'status'):
        try:
            if int(payload.get(key) or 0) in _TRANSIENT_RETRY_CODES:
                return True
        except (TypeError, ValueError):
            pass
    text = str(payload.get('message') or '')
    prefixed = re.match(r'\[\s*(\d{3})\s*\]', text)
    if prefixed and int(prefixed.group(1)) in _TRANSIENT_RETRY_CODES:
        return True
    lowered = text.casefold()
    return any(token in lowered for token in _TRANSIENT_RETRY_TOKENS)


def _log_line(line):
    """Terse progress line. Logging must never kill a run — cp1252 consoles
    cannot encode the Arabic hints, so fall back to an escaped form. flush=True
    forces the line through gunicorn's block-buffered stdout so tail -f sees
    it as it happens instead of a burst when the 8KB buffer fills."""
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        try:
            print(line.encode('ascii', 'backslashreplace').decode('ascii'), flush=True)
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
        dead = _dead_url_shape(url)
        if dead:
            trace.append({'url': url, 'title': '', 'chars': 0,
                          'error': dead})
            _pool_mark_failed(evidence_pool, url, dead)
            return {'url': url, 'error': dead}
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




_AGENT_PARTS_DIR = Path(__file__).with_name('agent_parts')
for _agent_part_path in sorted(
        _AGENT_PARTS_DIR.rglob('*.py'), key=lambda path: path.name):
    _agent_part_source = _agent_part_path.read_text(encoding='utf-8')
    exec(compile(_agent_part_source, str(_agent_part_path), 'exec'), globals())
