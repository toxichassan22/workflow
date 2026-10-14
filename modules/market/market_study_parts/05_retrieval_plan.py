

# ---------------------------------------------------------------------------
# Retrieval planner — the deterministic "known sources first" fetch plan.
#
# build_source_plan() turns the source catalog (SOURCE_PRIORITY /
# TYPE_SOURCE_PRIORITY / _PORTAL_DATASET_PAGES) plus the project's city into
# an ordered list of concrete URLs the job reads BEFORE any free-form web
# search; run_source_plan() executes it into the job's shared EvidencePool —
# plain HTTP first, the caller's Chromium session only for SPA/bot-walled
# targets or pages whose fetched text is too thin to count as evidence.
# This module does zero network I/O itself: fetch_http and the session are
# injected (app side passes a _read_market_source_page-backed fetcher and the
# job's browser_session()).
# ---------------------------------------------------------------------------

import time
from urllib.parse import quote

# Fetched page text under this size is a shell, not evidence — the entry falls
# back to the browser instead of being stored.
_THIN_TEXT_CHARS = 800

# The browser worker's own navigation timeout (mirrors browser.DEFAULT_TIMEOUT;
# kept local so this module never imports the browser layer).
_PLAN_BROWSER_TIMEOUT = 20

# Fallback progress percent for the (pct, msg) report shape — the plan runs
# inside the executor's "searching" stage (report(18, ...)), so entry updates
# keep that percent and only move the message.
_PLAN_PROGRESS_PCT = 18

# Hosts whose data pages are client-rendered apps or bot-walled — a plain GET
# buys nothing, so their entries are born needs_browser=True and go straight
# to the session. If the session still returns a shell they are marked
# 'needs_interaction' — the plan never enters a click loop.
_BROWSER_ONLY_HOSTS = {
    'rei.rega.gov.sa', 'red.rega.gov.sa', 'sakani.sa', 'ejar.sa',
    'saudiexchange.sa', 'aqar.fm', 'bayut.sa', 'wasalt.sa', 'dealapp.sa',
}

# Hosts that can never yield text evidence — never planned.
_SKIP_PLAN_HOSTS = {'maps.google.com', 'google.com', 'places.google.com'}

# Classifieds portals — a bare homepage carries no figures, so catalog
# homepage entries for them are dropped in favour of the city listing pages.
_LISTING_PORTAL_HOSTS = {'aqar.fm', 'sa.aqar.fm', 'bayut.sa', 'wasalt.sa', 'dealapp.sa'}

# Official data hosts that appear only inside TYPE_SOURCE_PRIORITY (never in
# the tiered SOURCE_PRIORITY list) but are still tier-1 official sources.
_HOST_TIER_EXTRAS = {'saudiexchange.sa': 1}

# Domain tokens inside the catalog lines. The TLD allowlist keeps Arabic
# prose and tokens like '3PL' or '2026' from ever becoming URLs.
_CATALOG_URL_RE = re.compile(
    r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+'
    r'(?:com|sa|net|org|gov|edu|me|fm|io|co|info)\b'
    r'(?:/[a-zA-Z0-9._~%/=-]*)?', re.I)

# Structured-component use keys mapped onto TYPE_SOURCE_PRIORITY keys.
_USE_TO_SOURCE_KIND = {
    'residential': 'سكني',
    'office': 'تجاري', 'retail': 'تجاري', 'commercial': 'تجاري',
    'hospitality': 'فندقي',
    'industrial': 'صناعي ولوجستي', 'logistics': 'صناعي ولوجستي',
}

# Listing category slug per source kind on aqar.fm — the only classifieds
# portal planned; its paths are Arabic ({cat}-للبيع/{city}).
_LISTING_CATEGORIES = {
    'سكني': ['شقق'],
    'تجاري': ['مكاتب', 'محلات'],
    'فندقي': ['شقق'],
    'صناعي ولوجستي': ['مستودعات'],
    '_default': ['شقق'],
}

_DATASET_LABELS = {
    'بيع': 'صفقات البيع المنفذة', 'إيجار': 'مؤشر سوق الإيجار',
    'default': 'المؤشرات اللحظية',
}

_HTML_BLOCK_RE = re.compile(
    r'<\s*(script|style|noscript|template|svg|head|form)\b[^>]*>.*?</\s*\1\s*>',
    re.I | re.S)
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_HTML_TITLE_RE = re.compile(r'<\s*title[^>]*>(.*?)</\s*title\s*>', re.I | re.S)
_HTML_ENTITIES = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'",
                  'nbsp': ' ', '#39': "'", '#x27': "'", '#x2f': '/'}


def _catalog_urls(text):
    """Absolute https URLs for the domain tokens embedded in a catalog line."""
    urls = []
    for match in _CATALOG_URL_RE.finditer(str(text or '')):
        url = 'https://' + match.group(0).rstrip('/.').lower()
        if url not in urls:
            urls.append(url)
    return urls


_HOST_TIERS_CACHE = None


def _registrable_host(host):
    """Drop subdomains: 'sa.aqar.fm' → 'aqar.fm'; 'rei.rega.gov.sa' keeps
    three labels since '.gov.sa' is a suffix, not a host."""
    parts = [part for part in str(host or '').split('.') if part]
    if len(parts) > 2 and parts[-2:] == ['gov', 'sa']:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:]) if len(parts) > 2 else str(host or '')


def _host_in(host, collection):
    return host in collection or _registrable_host(host) in collection


def _catalog_host_tiers():
    """host → SOURCE_PRIORITY tier, built once from the catalog itself."""
    global _HOST_TIERS_CACHE
    if _HOST_TIERS_CACHE is None:
        tiers = dict(_HOST_TIER_EXTRAS)
        for tier, lines in SOURCE_PRIORITY.items():
            for line in lines:
                for url in _catalog_urls(line):
                    tiers.setdefault(_source_host(url), tier)
        _HOST_TIERS_CACHE = tiers
    return _HOST_TIERS_CACHE


def _source_tier(url):
    """The SOURCE_PRIORITY tier a URL belongs to — government domains are
    tier 1, unlisted professional sources default to tier 3."""
    host = _source_host(url)
    tier = _catalog_host_tiers().get(host) or _catalog_host_tiers().get(
        _registrable_host(host))
    if tier:
        return tier
    if '.gov.' in host or host.endswith('.gov'):
        return 1
    return 3


def _payload_operations(payload):
    """{'بيع','إيجار'} — the transaction kinds this project actually trades.
    Empty means unknown; callers treat it as both."""
    ops = set()
    for component in _iter_payload_components(payload):
        model = _fold_choice(
            component.get('investmentModel') or component.get('investment_model'))
        if model == 'sale':
            ops.add('بيع')
        elif model == 'mixed':
            ops.update(('بيع', 'إيجار'))
        elif model in ('dailyrent', 'monthlyrent', 'annualrent', 'operating',
                       'rent', 'rental'):
            ops.add('إيجار')
    fin = payload.get('financial') if isinstance(payload.get('financial'), dict) else {}
    mode = _fold_choice(fin.get('unitRevenueMode') or payload.get('unitRevenueMode'))
    if mode == 'sale':
        ops.add('بيع')
    elif mode == 'rental':
        ops.add('إيجار')
    elif mode == 'mixed':
        ops.update(('بيع', 'إيجار'))
    return ops


def _payload_source_kinds(payload):
    """Ordered TYPE_SOURCE_PRIORITY keys this project draws evidence from —
    analysis kinds folded onto the catalog keys, then the structured
    components' useType, then the main type itself."""
    kinds = []

    def _add(kind):
        kind = {'مكاتب': 'تجاري', 'تجزئة': 'تجاري'}.get(kind, kind)
        if kind in TYPE_SOURCE_PRIORITY and kind not in kinds:
            kinds.append(kind)

    for kind in analysis_kind_for_project(
            payload.get('projectType') or payload.get('project_type'),
            payload.get('projectSubtype') or payload.get('project_subtype'),
            payload.get('projectComponents') or payload.get('project_components')
            or payload.get('project_mixed_components')):
        _add(kind)
    for component in _iter_payload_components(payload):
        model = _fold_choice(
            component.get('investmentModel') or component.get('investment_model'))
        if model == 'nonrevenue':
            continue
        _add(_USE_TO_SOURCE_KIND.get(
            _norm(component.get('useType') or component.get('use_type')).lower()))
    if not kinds:
        _add(_norm(payload.get('projectType') or payload.get('project_type')))
    if not kinds:
        kinds.append('سكني')
    return kinds


def _listing_urls(kinds, ops, city):
    """City-scoped aqar.fm listing pages — the current asking-price stock a
    resident actually sees. aqar is a bot-walled SPA, so callers always emit
    these needs_browser=True."""
    categories = []
    for kind in kinds or ['_default']:
        for cat in (_LISTING_CATEGORIES.get(kind) or _LISTING_CATEGORIES['_default']):
            if cat not in categories:
                categories.append(cat)
    for op in sorted(ops):
        rent = op == 'إيجار'
        for cat in categories:
            yield (f'https://sa.aqar.fm/{quote(cat + ("-للإيجار" if rent else "-للبيع"))}/{quote(city)}',
                   f'aqar.fm — {cat} {op} — {city}')


def build_source_plan(payload, offer_lang='ar'):
    """Ordered [{purpose, url, tier, needs_browser, label}] fetch plan.

    Known sources first: the portal dataset pages that actually expose the
    catalog's figures, then every concrete URL named in SOURCE_PRIORITY and
    the project's TYPE_SOURCE_PRIORITY lists, then city-scoped listing pages
    on the classifieds portals. Free-form web search is the gap-filler after
    this plan runs — never the first move.
    """
    payload = payload if isinstance(payload, dict) else {}
    entries = []
    seen = {}

    def _add(url, purpose, label='', needs_browser=False):
        url = str(url or '').strip()
        if not url.startswith(('http://', 'https://')):
            return
        host = _source_host(url)
        if not host or _host_in(host, _SKIP_PLAN_HOSTS):
            return
        parsed = urlsplit(url)
        key = (host + parsed.path.rstrip('/') + '?' + parsed.query).casefold()
        existing = seen.get(key)
        if existing is not None:
            if needs_browser:
                existing['needs_browser'] = True
            tier = _source_tier(url)
            if tier < existing['tier']:
                existing['tier'] = tier
            return
        entry = {'purpose': purpose, 'url': url, 'tier': _source_tier(url),
                 'needs_browser': bool(needs_browser or _host_in(host, _BROWSER_ONLY_HOSTS)),
                 'label': _norm(label)}
        seen[key] = entry
        entries.append(entry)

    # 1) The indicator portals' dataset pages — the fixed views where their
    #    figures actually live (a homepage on these hosts is a nav shell).
    for host, pages in (_PORTAL_DATASET_PAGES or {}).items():
        for op_key, url in pages.items():
            _add(url, 'dataset',
                 label=f'{host} — {_DATASET_LABELS.get(op_key, op_key)}')

    # 2) Catalog deep links: the universal priority list plus the lists of
    #    this project's kinds (mixed-use draws on every component's list).
    kinds = _payload_source_kinds(payload)
    lines = [line for tier_lines in SOURCE_PRIORITY.values() for line in tier_lines]
    for kind in kinds:
        lines.extend(TYPE_SOURCE_PRIORITY.get(kind) or [])
    for line in lines:
        for url in _catalog_urls(line):
            # A bare homepage is a nav shell, not evidence — its fetch just
            # burns a full page timeout (the plan's failures run ~80% homepages).
            # The catalog line still steers free search at this domain's deep
            # pages; the city listing pages below carry the portals' evidence.
            if is_generic_source_homepage(url):
                continue
            _add(url, 'catalog', label=line)

    # 3) City-scoped pages: the indicators portal's public city page carries
    #    deal counts and values (its advanced-search grids are Nafath-gated),
    #    then classifieds listings for current asking prices.
    ops = _payload_operations(payload) or {'بيع', 'إيجار'}
    city = _norm(payload.get('city'))
    if city:
        _add(f'https://rei.rega.gov.sa/ar/cities/{quote(city)}', 'dataset',
             label='المؤشرات العقارية — صفحة المدينة', needs_browser=True)
        for url, label in _listing_urls(kinds, ops, city):
            _add(url, 'listing', label=label, needs_browser=True)

    entries.sort(key=lambda item: item['tier'])   # stable — catalog order survives inside a tier
    return entries


def _html_title(markup):
    match = _HTML_TITLE_RE.search(str(markup or ''))
    return _norm(_HTML_TAG_RE.sub(' ', match.group(1))) if match else ''


def _html_to_text(markup):
    """Readable text out of fetched markup — scripts/styles stripped so an
    SPA shell measures thin instead of masquerading as a long page."""
    text = _HTML_BLOCK_RE.sub(' ', str(markup or ''))
    text = _HTML_TAG_RE.sub(' ', text)
    text = re.sub(r'&([a-zA-Z]+|#[a-zA-Z0-9]+);',
                  lambda m: _HTML_ENTITIES.get(m.group(1).lower(), ' '), text)
    text = re.sub(r'[ \t\r\f\v]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _call_fetch_http(fetch_http, url):
    """Run the injected fetcher; normalize to (body, error).

    The app side passes a _read_market_source_page-backed callable returning
    (html, error); plain-string and dict-shaped returns are accepted so tests
    can inject trivial fakes.
    """
    if not callable(fetch_http):
        return '', 'fetch_http_unavailable'
    try:
        result = fetch_http(url)
    except Exception as exc:
        return '', str(exc) or exc.__class__.__name__
    if isinstance(result, tuple):
        pair = list(result) + [None]
        return str(pair[0] or ''), str(pair[1] or '')
    if isinstance(result, dict):
        return (str(result.get('text') or result.get('content') or result.get('body') or ''),
                str(result.get('error') or ''))
    return (str(result), '') if result else ('', 'empty_response')


def _browser_open(session, url, deadline=None):
    """open_url on the caller's session — never raises, returns a dict."""
    opener = getattr(session, 'open_url', None)
    if not callable(opener):
        return {'error': 'browser_unavailable'}
    kwargs = {}
    if deadline is not None:
        remaining = float(deadline) - time.time()
        if remaining <= 0:
            return {'error': 'deadline_exceeded'}
        kwargs['timeout'] = max(1, min(_PLAN_BROWSER_TIMEOUT, int(remaining)))
    try:
        result = opener(url, **kwargs)
    except TypeError:
        # A narrower fake/older session without the timeout kwarg.
        try:
            result = opener(url)
        except Exception as exc:
            return {'error': str(exc) or exc.__class__.__name__}
    except Exception as exc:
        return {'error': str(exc) or exc.__class__.__name__}
    return result if isinstance(result, dict) else {'error': 'open_failed'}


def _store_browser_page(pool, url, session, deadline, spa_target):
    """Browser-open one URL into the pool; '' on success else the reason."""
    result = _browser_open(session, url, deadline=deadline)
    error = str(result.get('error') or '').strip()
    if error:
        pool.mark_failed(url, error)
        return error
    text = str(result.get('text') or '').strip()
    if len(text) >= _THIN_TEXT_CHARS:
        final_url = str(result.get('final_url') or result.get('url') or url).strip() or url
        pool.add_page(url, title=str(result.get('title') or ''), content=text,
                      final_url=final_url, via='browser')
        return ''
    # An SPA target that still returns a shell needs user interaction — mark
    # it instead of entering a click loop or storing nav junk as evidence.
    reason = 'needs_interaction' if spa_target else 'thin_content'
    pool.mark_failed(url, reason)
    return reason


def _emit_plan_event(report, entry, status, via='', reason=''):
    """Per-entry progress. ``report`` may be the dict-event sink tests inject
    or the job's (percent, message) UI progress callable — try the structured
    event first, fall back to the progress shape on a signature mismatch."""
    if not callable(report):
        return
    event = {'url': str(entry.get('url') or ''),
             'purpose': str(entry.get('purpose') or ''),
             'label': str(entry.get('label') or ''),
             'status': status, 'via': via, 'reason': reason}
    try:
        report(event)
        return
    except TypeError:
        pass
    except Exception:
        return
    try:
        report(_PLAN_PROGRESS_PCT,
               str(entry.get('label') or entry.get('url') or status))
    except Exception:
        pass


def run_source_plan(plan, pool, fetch_http, session=None, deadline=None, report=None):
    """Execute a build_source_plan() plan into the job's shared evidence pool.

    Entries are processed tier-first; a URL the pool already holds (fetched
    or failed) is skipped. HTTP first unless the entry is needs_browser — the
    browser opens a page only when HTTP text is too thin or the target is a
    known SPA/bot-walled host. Returns {'fetched': n, 'skipped': n, 'failed': m};
    a deadline stop leaves the remaining entries untouched and reports a
    'deadline' event.
    """
    counts = {'fetched': 0, 'skipped': 0, 'failed': 0}
    entries = [entry for entry in (plan or []) if isinstance(entry, dict)]

    def _tier(entry):
        try:
            return int(entry.get('tier') or 9)
        except (TypeError, ValueError):
            return 9

    entries.sort(key=_tier)
    for entry in entries:
        url = str(entry.get('url') or '').strip()
        if not url:
            continue
        if deadline is not None and time.time() >= float(deadline):
            _emit_plan_event(report, entry, 'deadline')
            break
        if pool.get_page(url) or pool.page_failed(url):
            counts['skipped'] += 1
            _emit_plan_event(report, entry, 'skipped', via='pool')
            continue
        spa_host = _host_in(_source_host(url), _BROWSER_ONLY_HOSTS)
        if entry.get('needs_browser') or spa_host:
            if session is None:
                reason = 'browser_unavailable'
                pool.mark_failed(url, reason)
            else:
                reason = _store_browser_page(pool, url, session, deadline,
                                             spa_target=True)
            counts['failed' if reason else 'fetched'] += 1
            _emit_plan_event(report, entry, 'failed' if reason else 'fetched',
                             via='browser', reason=reason)
            continue
        body, error = _call_fetch_http(fetch_http, url)
        if error:
            pool.mark_failed(url, error)
            counts['failed'] += 1
            _emit_plan_event(report, entry, 'failed', via='http', reason=error)
            continue
        text = _html_to_text(body)
        if len(text) >= _THIN_TEXT_CHARS:
            pool.add_page(url, title=_html_title(body), content=text,
                          final_url=url, via='http')
            counts['fetched'] += 1
            _emit_plan_event(report, entry, 'fetched', via='http')
            continue
        if session is None:
            reason = 'needs_interaction' if spa_host else 'thin_content'
            pool.mark_failed(url, reason)
            counts['failed'] += 1
            _emit_plan_event(report, entry, 'failed', via='http', reason=reason)
            continue
        reason = _store_browser_page(pool, url, session, deadline,
                                     spa_target=spa_host)
        counts['failed' if reason else 'fetched'] += 1
        _emit_plan_event(report, entry, 'failed' if reason else 'fetched',
                         via='browser', reason=reason)
    return counts
