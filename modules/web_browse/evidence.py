# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Evidence pool: one per market job, shared by every browse call and fetch.
# Search results and opened pages are stored once — later stages (expansion,
# verify, logos, summary) ask the pool before paying for a new lookup, so the
# same folded query never runs twice and a redirected URL dedupes under its
# final_url. Thread-safe (the ×4 verify pool shares it); pure stdlib and free
# of Flask/db/network so the module stays importable standalone, same rule as
# agent.py — it must NOT import the market study module.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import re
import threading


# Alef/ya/taa-marbuta folding mirrors the market pipeline's _fold_choice, kept
# local because the pool cannot import the market study module. App-side token
# extraction (_competitor_name_tokens) already folds ة→ه and alef variants, so
# page text must fold identically — skipping any of these would make name
# matching miss pages that genuinely carry the token. Tatweel is decoration:
# removed.
_FOLD_TABLE = str.maketrans({
    'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا',
    'ى': 'ي',
    'ة': 'ه',
    'ـ': None,
})
_WHITESPACE = re.compile(r'\s+')


def _fold_text(value):
    """The pool's own normalizer: tatweel stripped, alef/ya variants folded,
    whitespace collapsed, casefolded."""
    text = str(value or '').translate(_FOLD_TABLE).casefold()
    return _WHITESPACE.sub(' ', text).strip()


def _compact_results(results):
    """Search results kept in the shape _run_web_search emits downstream —
    only the three fields the tool contract carries, coerced to str."""
    compact = []
    for item in results or []:
        if not isinstance(item, dict):
            continue
        compact.append({'title': str(item.get('title') or ''),
                        'url': str(item.get('url') or ''),
                        'snippet': str(item.get('snippet') or '')})
    return compact


class EvidencePool:
    """One shared evidence store per market job.

    Queries are keyed by folded text so «دراسة  السوق» and «دراسة السوق»
    dedupe to a single run; pages are keyed by ``final_url`` (falling back to
    the requested ``url``) so a redirect never fetches twice. Public getters
    emit the ``{url, title, content}`` shape ``_market_citation_pages``
    produces — pages plug straight into the existing citation pipeline.
    """

    PAGE_TEXT_CAP = 8000        # same as agent._PAGE_TEXT_CITATION_CAP
    MAX_PAGES = 250

    def __init__(self):
        self._lock = threading.Lock()
        self._queries = {}      # folded query -> {'query': raw, 'results': [...]}
        self._pages = {}        # canonical key (final_url) -> {url,title,content,via}
        self._aliases = {}      # requested url -> canonical key
        self._failures = {}     # url -> reason
        self._pool_hits = 0

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def add_query(self, query, results):
        """Record that ``query`` ran with ``results`` — returns how many were
        stored; 0 when the folded query already ran (first run wins)."""
        raw = str(query or '').strip()
        if not raw:
            return 0
        key = _fold_text(raw)
        compact = _compact_results(results)
        with self._lock:
            if key in self._queries:
                return 0
            self._queries[key] = {'query': raw, 'results': compact}
            return len(compact)

    def query_results(self, query):
        """Cached results for a folded query — None when it never ran, [] when
        it ran and got zero hits. Serving a cached answer counts a pool hit."""
        key = _fold_text(query)
        with self._lock:
            record = self._queries.get(key)
            if record is None:
                return None
            self._pool_hits += 1
            return [dict(item) for item in record['results']]

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    def add_page(self, url, title='', content='', final_url='', via='browser'):
        """Store one fetched page under its final_url; merges title/content
        into the existing record when the key already exists. Returns the
        canonical key, or None when no URL at all was given."""
        url = str(url or '').strip()
        key = str(final_url or '').strip() or url
        if not key:
            return None
        with self._lock:
            page = self._pages.get(key)
            if page is None:
                if len(self._pages) >= self.MAX_PAGES:
                    evicted = next(iter(self._pages))
                    del self._pages[evicted]
                    self._drop_aliases(evicted)
                    self._failures.pop(evicted, None)
                page = {'url': key, 'title': '', 'content': '', 'via': ''}
                self._pages[key] = page
            title = str(title or '').strip()
            if title and not page['title']:
                page['title'] = title
            content = str(content or '')
            if content:
                merged = page['content'] + '\n' + content
                page['content'] = merged.strip()[:self.PAGE_TEXT_CAP]
            if via:
                page['via'] = str(via)
            if url and url != key:
                self._aliases[url] = key
            # A successful fetch supersedes any earlier failure on this URL.
            self._failures.pop(url, None)
            self._failures.pop(key, None)
            return key

    def mark_failed(self, url, reason):
        """Record why a URL could not be fetched. A page that already carries
        evidence keeps it — a later transient failure does not un-fetch it."""
        url = str(url or '').strip()
        if not url:
            return
        with self._lock:
            if self._resolve(url) in self._pages:
                return
            self._failures[url] = str(reason or 'failed')

    def get_page(self, url):
        """The stored page for a URL (alias-resolved), or None."""
        with self._lock:
            page = self._pages.get(self._resolve(url))
            return self._public_page(page) if page else None

    def page_failed(self, url):
        """The recorded failure reason for a URL (alias-resolved), or None."""
        url = str(url or '').strip()
        with self._lock:
            reason = self._failures.get(url)
            if reason is None:
                reason = self._failures.get(self._aliases.get(url, ''))
            return reason

    def pages(self):
        """Every stored page as {url, title, content} — insertion order."""
        with self._lock:
            return [self._public_page(page) for page in self._pages.values()]

    def pages_for_name(self, tokens, needed):
        """Pages whose folded title+url+content carry at least ``needed``
        distinct tokens. Tokens are re-folded under the pool's own normalizer
        so callers may pass raw or _competitor_name_tokens output alike."""
        folded = {_fold_text(token) for token in (tokens or [])}
        folded.discard('')
        if not folded:
            return []
        try:
            needed = max(1, int(needed))
        except (TypeError, ValueError):
            needed = 1
        matched = []
        with self._lock:
            for page in self._pages.values():
                haystack = _fold_text(
                    f"{page['title']} {page['url']} {page['content']}")
                if sum(1 for token in folded if token in haystack) >= needed:
                    matched.append(self._public_page(page))
        return matched

    # ------------------------------------------------------------------
    # Stats + serialization (to_dict/from_dict exist for tests — the pool is
    # in-memory for v1; nothing consumes the serialized form at runtime yet)
    # ------------------------------------------------------------------
    def stats(self):
        with self._lock:
            return {'queries': len(self._queries),
                    'pages': len(self._pages),
                    'pool_hits': self._pool_hits}

    def to_dict(self):
        with self._lock:
            return {
                'version': 1,
                'queries': {key: {'query': record['query'],
                                  'results': [dict(item) for item in record['results']]}
                            for key, record in self._queries.items()},
                'pages': [dict(page) for page in self._pages.values()],
                'failures': dict(self._failures),
                'aliases': dict(self._aliases),
                'pool_hits': self._pool_hits,
            }

    @classmethod
    def from_dict(cls, data):
        pool = cls()
        data = data if isinstance(data, dict) else {}
        for key, record in (data.get('queries') or {}).items():
            results = record if isinstance(record, list) else (
                (record or {}).get('results') if isinstance(record, dict) else [])
            raw = record.get('query') if isinstance(record, dict) else None
            pool._queries[str(key)] = {'query': str(raw or key),
                                       'results': _compact_results(results)}
        for record in (data.get('pages') or []):
            if not isinstance(record, dict):
                continue
            key = str(record.get('url') or '').strip()
            if not key:
                continue
            pool._pages[key] = {
                'url': key,
                'title': str(record.get('title') or ''),
                'content': str(record.get('content') or '')[:cls.PAGE_TEXT_CAP],
                'via': str(record.get('via') or ''),
            }
        for url, reason in (data.get('failures') or {}).items():
            pool._failures[str(url)] = str(reason or 'failed')
        for alias, target in (data.get('aliases') or {}).items():
            pool._aliases[str(alias)] = str(target)
        try:
            pool._pool_hits = max(0, int(data.get('pool_hits') or 0))
        except (TypeError, ValueError):
            pool._pool_hits = 0
        return pool

    # ------------------------------------------------------------------
    # Internals (must run under self._lock)
    # ------------------------------------------------------------------
    def _resolve(self, url):
        """Requested URL → canonical page key, following the stored alias."""
        url = str(url or '').strip()
        return self._aliases.get(url, url)

    def _drop_aliases(self, key):
        for alias, target in list(self._aliases.items()):
            if target == key:
                del self._aliases[alias]

    @staticmethod
    def _public_page(page):
        return {'url': page['url'], 'title': page['title'],
                'content': page['content']}
