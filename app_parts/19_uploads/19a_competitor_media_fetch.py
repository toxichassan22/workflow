


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Remote imagery fetch (competitor logos, listing photos, official brand
# marks) over a pinned-HTTPS transport: every download resolves the host,
# refuses private ranges, follows redirects only inside the same site and
# caps bytes, so an AI-suggested URL can never become an SSRF probe.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


COMPETITOR_LOGO_MAX_BYTES = 2 * 1024 * 1024
COMPETITOR_LOGO_MIMES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
OFFICIAL_LOGO_PAGE_MAX_BYTES = 2 * 1024 * 1024


def _public_host_addresses(host):
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except (OSError, socket.gaierror):
        return ()
    verified = []
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return ()
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified):
            return ()
        verified.append(address)
    return tuple(sorted(verified))


def _safe_public_host(host):
    return bool(_public_host_addresses(host))


def _open_pinned_https(parsed, addresses):
    host = str(parsed.hostname).encode('idna').decode('ascii')
    path = parsed.path or '/'
    if parsed.query:
        path += '?' + parsed.query
    pool = HTTPSConnectionPool(
        addresses[0], port=443, assert_hostname=host, server_hostname=host,
        cert_reqs='CERT_REQUIRED', ca_certs=requests.certs.where(),
    )
    response = pool.urlopen(
        'GET', path, headers={'Host': host, 'User-Agent': 'Mozilla/5.0'},
        redirect=False, preload_content=False, retries=False,
        timeout=Timeout(connect=7, read=20),
    )
    return pool, response


_OFFICIAL_CDN_PREFIXES = {'cdn', 'images', 'image', 'img', 'static', 'assets', 'media', 'files'}
_TWO_LEVEL_PUBLIC_SUFFIXES = {'co.uk', 'com.sa', 'net.sa', 'org.sa', 'com.ae', 'co.za', 'com.eg'}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_OFFICIAL_FETCH_MAX_REDIRECTS = 3


def _normalized_web_host(url):
    return (urlsplit(str(url or '')).hostname or '').lower().removeprefix('www.')


def _registrable_host(host):
    parts = str(host or '').split('.')
    if len(parts) < 2:
        return str(host or '')
    suffix = '.'.join(parts[-2:])
    return '.'.join(parts[-3:]) if suffix in _TWO_LEVEL_PUBLIC_SUFFIXES and len(parts) >= 3 else suffix


def _redirect_within_site(origin_url, target_url):
    # Redirects may move inside the same registrable site — www shuffles,
    # locale prefixes, CDN subdomains. A hand-off to another registrable
    # domain is an open-redirect hop we refuse to follow.
    origin = _normalized_web_host(origin_url)
    target = _normalized_web_host(target_url)
    return bool(origin and target
                and _registrable_host(origin) == _registrable_host(target))


def _pinned_https_get(url, redirects_left=_OFFICIAL_FETCH_MAX_REDIRECTS, origin_url=None):
    """GET an HTTPS URL through the DNS-pinned pool, following redirects that
    stay inside the original site's registrable host. Returns
    (pool, response, final_url) — the caller owns pool/response cleanup — or
    (None, None, error_key_or_text) on validation/transport failure."""
    parsed = urlsplit(str(url or '').strip())
    try:
        invalid_port = parsed.port not in (None, 443)
    except ValueError:
        invalid_port = True
    if (parsed.scheme.lower() != 'https' or not parsed.hostname
            or parsed.username or invalid_port):
        return None, None, 'invalid_url'
    if origin_url and not _redirect_within_site(origin_url, url):
        return None, None, 'off_site_redirect'
    addresses = _public_host_addresses(parsed.hostname)
    if not addresses:
        return None, None, 'blocked_host'
    try:
        pool, response = _open_pinned_https(parsed, addresses)
    except Exception as exc:
        return None, None, str(exc)
    location = str((response.headers or {}).get('Location') or '').strip()
    if response.status in _REDIRECT_STATUSES and location:
        response.release_conn()
        pool.close()
        if redirects_left <= 0:
            return None, None, 'too_many_redirects'
        return _pinned_https_get(urljoin(url, location), redirects_left - 1,
                                 origin_url or url)
    return pool, response, url


def _official_fetch_error(kind):
    return {
        'invalid_url': 'صفحة الموقع الرسمي غير صالحة',
        'blocked_host': 'عنوان الموقع الرسمي غير مسموح',
        'off_site_redirect': 'تحويل الموقع الرسمي إلى نطاق مختلف',
        'too_many_redirects': 'تعذر قراءة صفحة الموقع الرسمي: تحويلات كثيرة',
    }.get(kind) or str(kind)


def _related_official_hosts(first_url, second_url):
    first = _normalized_web_host(first_url)
    second = _normalized_web_host(second_url)
    return bool(first and second and (
        first == second or first.endswith('.' + second) or second.endswith('.' + first)
    ))


def _same_official_host(logo_url, official_url):
    logo_host = _normalized_web_host(logo_url)
    official_host = _normalized_web_host(official_url)
    if not logo_host or not official_host:
        return False
    if logo_host == official_host or logo_host.endswith('.' + official_host):
        return True
    logo_parts = logo_host.split('.')
    return bool(len(logo_parts) >= 3 and logo_parts[0] in _OFFICIAL_CDN_PREFIXES
                and _registrable_host(logo_host) == _registrable_host(official_host))


class _OfficialLogoHTMLParser(HTMLParser):
    """Collect logo hints exposed by a company's own page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.candidates = []
        self._json_ld_depth = 0
        self._json_ld_parts = []

    def _add(self, value, priority):
        value = html_lib.unescape(str(value or '')).strip()
        if value:
            self.candidates.append((priority, value))

    def handle_starttag(self, tag, attrs):
        attributes = {str(key).lower(): str(value or '').strip() for key, value in attrs}
        tag_name = str(tag or '').lower()
        if tag_name == 'meta':
            identity = (attributes.get('property') or attributes.get('name')
                        or attributes.get('itemprop') or '').lower()
            if identity in {'og:image', 'og:image:url', 'twitter:image', 'twitter:image:src'}:
                self._add(attributes.get('content'), 3)
            elif identity == 'logo':
                self._add(attributes.get('content'), 1)
        elif tag_name == 'link':
            rel = set(re.findall(r'[a-z0-9_-]+', attributes.get('rel', '').lower()))
            if rel.intersection({'icon', 'shortcut', 'apple-touch-icon', 'logo'}):
                self._add(attributes.get('href'), 1)
        elif tag_name == 'img':
            hint = ' '.join(attributes.get(key, '') for key in ('alt', 'class', 'id', 'src')).lower()
            if any(token in hint for token in ('logo', 'brand', 'شعار')):
                image_src = attributes.get('src') or attributes.get('data-src') or attributes.get('data-lazy-src')
                if image_src.lower().startswith('data:'):
                    image_src = attributes.get('data-src') or attributes.get('data-lazy-src')
                self._add(image_src, 1)
        elif tag_name == 'script' and attributes.get('type', '').lower() == 'application/ld+json':
            self._json_ld_depth = 1
            self._json_ld_parts = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self._json_ld_depth:
            self._json_ld_parts.append(data)

    def handle_endtag(self, tag):
        if str(tag or '').lower() != 'script' or not self._json_ld_depth:
            return
        try:
            payload = json.loads(''.join(self._json_ld_parts))
        except (TypeError, ValueError):
            payload = None

        def collect(value):
            if isinstance(value, dict):
                logo = value.get('logo')
                if isinstance(logo, str):
                    self._add(logo, 0)
                elif isinstance(logo, dict):
                    self._add(logo.get('url') or logo.get('contentUrl'), 0)
                for key, item in value.items():
                    if key != 'logo' and isinstance(item, (dict, list)):
                        collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(payload)
        self._json_ld_depth = 0
        self._json_ld_parts = []


def _safe_read_official_logo_page(official_url):
    """(page_html, final_url, error) — redirects inside the same registrable
    site are followed; final_url is the page actually read so relative logo
    paths resolve against it."""
    pool, response, outcome = _pinned_https_get(official_url)
    if pool is None:
        return '', '', _official_fetch_error(outcome)
    try:
        if response.status != 200:
            return '', '', f'تعذر قراءة صفحة الموقع الرسمي: HTTP {response.status}'
        content = bytearray()
        for chunk in response.stream(64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > OFFICIAL_LOGO_PAGE_MAX_BYTES:
                return '', '', 'صفحة الموقع الرسمي أكبر من الحد المسموح'
        return bytes(content).decode('utf-8', errors='replace'), outcome, ''
    finally:
        response.release_conn()
        pool.close()


def _official_logo_candidates(official_url):
    """(candidates, error) — the error explains why nothing was extractable so the
    row warning can say so instead of a generic failure."""
    page, final_url, page_error = _safe_read_official_logo_page(official_url)
    if not page:
        return [], page_error or 'تعذر قراءة صفحة الموقع الرسمي'
    base_url = final_url or official_url
    parser = _OfficialLogoHTMLParser()
    try:
        parser.feed(page)
        parser.close()
    except Exception:
        return [], 'تعذر تحليل صفحة الموقع الرسمي'
    candidates = []
    seen = set()
    for _priority, raw_url in sorted(parser.candidates, key=lambda item: item[0]):
        candidate = urljoin(base_url, raw_url)
        parsed = urlsplit(candidate)
        if (parsed.scheme.lower() != 'https' or not parsed.hostname or parsed.username
                or not _same_official_host(candidate, base_url)):
            continue
        # Ad-license stamps (رواج / REGA) ship inside listing pages as images on
        # the same host — never a competitor's own logo.
        lowered = candidate.casefold()
        if any(token in lowered for token in ('ruwaj', 'rawaj', 'rowaj', '/rwaj', 'rega')):
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates, '' if candidates else 'لا توجد صورة شعار على الصفحة الرسمية'


def _safe_download_competitor_logo(logo_url, official_url):
    parsed = urlsplit(str(logo_url or '').strip())
    official = urlsplit(str(official_url or '').strip())
    try:
        invalid_port = parsed.port not in (None, 443) or official.port not in (None, 443)
    except ValueError:
        invalid_port = True
    if (parsed.scheme.lower() != 'https' or official.scheme.lower() != 'https'
            or not parsed.hostname or not official.hostname or parsed.username or official.username
            or invalid_port):
        return None, None, None, 'رابط الشعار الرسمي غير صالح'
    if not _same_official_host(logo_url, official_url):
        return None, None, None, 'شعار المنافس خارج الموقع الرسمي'
    if any(token in str(logo_url).casefold() for token in ('ruwaj', 'rawaj', 'rowaj', '/rwaj', 'rega')):
        return None, None, None, 'شعار منصة إعلانات وليس شعار المنافس'
    if not _public_host_addresses(official.hostname):
        return None, None, None, 'عنوان موقع الشعار غير مسموح'
    pool, response, outcome = _pinned_https_get(logo_url)
    if pool is None:
        if outcome == 'off_site_redirect':
            return None, None, None, 'تحويل الشعار إلى نطاق مختلف'
        if outcome in ('invalid_url', 'blocked_host'):
            return None, None, None, 'عنوان موقع الشعار غير مسموح'
        if outcome == 'too_many_redirects':
            return None, None, None, 'تعذر تنزيل الشعار: تحويلات كثيرة'
        return None, None, None, str(outcome)
    try:
        if response.status != 200:
            return None, None, None, f'تعذر تنزيل الشعار: HTTP {response.status}'
        mime_type = str(response.headers.get('Content-Type') or '').split(';', 1)[0].strip().lower()
        extension = COMPETITOR_LOGO_MIMES.get(mime_type)
        try:
            declared = int(response.headers.get('Content-Length') or 0)
        except (TypeError, ValueError):
            declared = 0
        if declared > COMPETITOR_LOGO_MAX_BYTES:
            return None, None, None, 'حجم شعار المنافس أكبر من الحد المسموح'
        content = bytearray()
        for chunk in response.stream(64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > COMPETITOR_LOGO_MAX_BYTES:
                return None, None, None, 'حجم شعار المنافس أكبر من الحد المسموح'
        try:
            from PIL import Image, UnidentifiedImageError
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > 16_000_000:
                    return None, None, None, 'أبعاد شعار المنافس غير صالحة'
                detected = {'PNG': ('image/png', '.png'), 'JPEG': ('image/jpeg', '.jpg'), 'WEBP': ('image/webp', '.webp')}.get((image.format or '').upper())
                if not detected:
                    # Any other PIL-readable raster (GIF, AVIF, BMP…) is a real
                    # image — re-encode it to PNG instead of rejecting it.
                    buffer = BytesIO()
                    image.convert('RGBA').save(buffer, 'PNG')
                    content = bytearray(buffer.getvalue())
                    detected = ('image/png', '.png')
                else:
                    image.verify()
                mime_type, extension = detected
        except (UnidentifiedImageError, OSError):
            return None, None, None, 'ملف شعار المنافس غير صالح'
        return bytes(content), mime_type, extension, ''
    finally:
        response.release_conn()
        pool.close()


def _download_official_favicon(official_url):
    """Last-resort logo: Google's favicon service returns the icon the official
    site itself publishes — reachable even when the site blocks direct reads
    (Cloudflare 403/timeouts). Only used once the domain is already verified
    as the competitor's official page."""
    host = _normalized_web_host(official_url)
    if not host:
        return None, None, None, ''
    # The s2 endpoint 301-redirects to gstatic faviconV2 — call it directly;
    # same-site redirects are followed by the pinned fetch anyway.
    favicon_url = ('https://t2.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON'
                   f'&fallback_opts=TYPE,SIZE,URL&url=http://{host}&size=128')
    pool, response, _outcome = _pinned_https_get(favicon_url)
    if pool is None:
        return None, None, None, ''
    try:
        if response.status != 200:
            return None, None, None, ''
        content = bytes(b''.join(response.stream(64 * 1024)))
        if not content or len(content) > COMPETITOR_LOGO_MAX_BYTES:
            return None, None, None, ''
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(BytesIO(content)) as image:
                if image.size[0] <= 0 or image.size[1] <= 0:
                    return None, None, None, ''
                mime_type, extension = {'PNG': ('image/png', '.png'), 'JPEG': ('image/jpeg', '.jpg'),
                                        'WEBP': ('image/webp', '.webp')}.get(
                                            (image.format or '').upper(), ('', ''))
                if not extension:
                    buffer = BytesIO()
                    image.convert('RGBA').save(buffer, 'PNG')
                    content = buffer.getvalue()
                    mime_type, extension = 'image/png', '.png'
                else:
                    image.verify()
        except (UnidentifiedImageError, OSError):
            return None, None, None, ''
        return content, mime_type, extension, ''
    finally:
        response.release_conn()
        pool.close()


# Aggregator/index hosts list a competitor but are never its official site —
# their og:image is the portal's own logo, so they are excluded from the
# citation-based official-page match.
_AGGREGATOR_HOST_TOKENS = (
    'sakani.', 'ejar.', 'rega.gov', 'ruwaj', 'rawaj', 'rowaj',
    'aqar.', 'aqaar.', 'aqarmap', 'wasalt.', 'bayut.',
    'dubizzle', 'propertyfinder', 'opensooq', 'haraj', 'lamudi', 'exxl',
    'estater', 'muqawil', 'dealmap', 'eqqar',
    'wikipedia', 'twitter.', 'x.com', 'facebook.', 'instagram.', 'linkedin.',
    'youtube.', 'tiktok.', 'google.', 'bing.', 'maps.',
)

# Same-name projects in other Arab markets are a constant trap: «أورا» matched
# Dubai pages and would have imported a dirham price and an off-country logo.
# Saudi competitors never live on these hosts.
_FOREIGN_ARAB_TLDS = (
    '.ae', '.eg', '.qa', '.kw', '.bh', '.om', '.jo', '.lb',
    '.ma', '.tn', '.dz', '.ly', '.iq', '.sd', '.sy', '.ps',
)
_FOREIGN_ARAB_HOST_TOKENS = (
    'dubai', 'abudhabi', 'sharjah', 'uae', 'egypt', 'cairo',
    'qatar', 'kuwait', 'bahrain', 'oman', 'jordan', 'morocco',
)


def _foreign_market_host(url):
    """True when a URL points at another Arab market, not Saudi."""
    host = _normalized_web_host(url)
    if not host:
        return False
    if host.endswith(_FOREIGN_ARAB_TLDS) or any(
            token in host for token in _FOREIGN_ARAB_HOST_TOKENS):
        return True
    # Namesakes abroad also hide in the path of generic .com portals
    # (aigentsrealty.com/.../dubai-silicon-oasis/...) — a Saudi competitor's
    # evidence never lives on a /dubai-/ style page.
    path = urlsplit(str(url)).path.lower()
    return any(
        re.search(r'(?:^|[^a-z0-9])' + re.escape(token) + r'(?:[^a-z0-9]|$)', path)
        for token in _FOREIGN_ARAB_HOST_TOKENS)


def _drop_foreign_competitor_urls(row):
    """Remove same-name foreign-market pages from a Saudi competitor row."""
    if not isinstance(row, dict):
        return row
    urls = market_study.competitor_source_urls(row)
    kept = [url for url in urls if not _foreign_market_host(url)]
    if len(kept) != len(urls):
        row['source_urls'] = kept
        if not kept:
            row.pop('source_urls', None)
    field_sources = market_study.competitor_field_sources(row)
    if field_sources:
        cleaned = {
            field: [url for url in urls if not _foreign_market_host(url)]
            for field, urls in field_sources.items()
        }
        row['field_sources'] = {field: urls for field, urls in cleaned.items() if urls}
        if not row['field_sources']:
            row.pop('field_sources', None)
    if _foreign_market_host(row.get('source_url')):
        row.pop('source_url', None)
    return row


def _official_citation_pages(pages, name):
    """Citation pages that look like the competitor's own site.

    A page that merely *mentions* the project is not its official page — a
    district article on a developer's site would otherwise hand that
    developer's favicon to an unrelated competitor. The page must carry ALL
    distinctive name tokens and live on a non-aggregator host.
    """
    tokens = _competitor_name_tokens(name)
    if not tokens:
        return []
    needed = len(tokens)
    matches = []
    for page in pages or []:
        url = str(page.get('url') or '').strip()
        host = _normalized_web_host(url)
        if (not host or any(token in host for token in _AGGREGATOR_HOST_TOKENS)
                or _foreign_market_host(url)):
            continue
        haystack = market_study._fold_choice(f"{page.get('title') or ''} {url}")
        if sum(1 for token in tokens if token in haystack) >= needed:
            matches.append(url)
    return matches


def _auto_import_competitor_logos(rows, payload, data, tenant_id=None, progress=None,
                                  citation_pages=None):
    """Import official logos during competitor generation — no per-row button needed.

    Pass 1 is free: rows whose source_url already verifies as the official site go
    straight to HTML extraction. Pass 1.5 is free too: citation pages the main
    search already retrieved are matched to each competitor's name and treated as
    its official page. Pass 2 runs ONE extra search call to discover the official
    site + logo for whatever remains, then extracts/downloads per row.
    """
    report = progress if callable(progress) else (lambda *_args: None)
    draft_id = payload.get('draftId') or payload.get('draft_id')
    missing = []
    total = max(1, len(rows))
    for index, row in enumerate(rows):
        if row.get('logo_file_id') or row.get('logo_path'):
            continue
        dead_keys = {str(item).strip().casefold() for item in (row.get('dead_source_urls') or [])}
        official_url = str(row.get('logo_source_url') or row.get('source_url') or '').strip()
        if official_url.strip().casefold() in dead_keys:
            official_url = ''
        verified = bool(official_url and (
            row.get('logo_official_verified')
            or market_study.official_source_reliability(
                row.get('name'), row.get('source'), official_url)))
        if not verified:
            for page_url in _official_citation_pages(citation_pages, row.get('name')):
                if page_url.casefold() in dead_keys:
                    continue
                official_url = page_url
                row['logo_source_url'] = page_url
                row['logo_official_verified'] = True
                field_sources = market_study.competitor_field_sources(row)
                urls = field_sources.setdefault('logo_url', [])
                if page_url not in urls:
                    urls.append(page_url)
                row['field_sources'] = field_sources
                row['source_urls'] = list(dict.fromkeys(
                    market_study.competitor_source_urls(row) + [page_url]))
                verified = True
                break
        if verified:
            report(74 + int(8 * index / total),
                   f'استخراج شعار «{row.get("name") or "منافس"}» من موقعه الرسمي...')
            try:
                _store_imported_competitor_logo(row, draft_id=draft_id)
            except Exception as exc:
                row['logo_import_warning'] = str(exc)
        if not row.get('logo_file_id') and not row.get('logo_path'):
            if row.get('no_search_evidence'):
                # No retrieved page even names this competitor — paying a
                # discovery call for a likely-fabricated name is wasted spend.
                row.setdefault('logo_import_warning', 'اسم المنافس غير موثق — لا يوجد موقع رسمي لاستيراد الشعار')
            else:
                missing.append(row)
    if not missing:
        return
    batch = missing[:8]
    report(82, 'البحث عن المواقع الرسمية وشعارات المنافسين المتبقية...')
    listing = json.dumps(
        [{'id': str(row.get('id') or ''), 'name': str(row.get('name') or '')} for row in batch],
        ensure_ascii=False)
    city = str(payload.get('city') or '').strip() or 'غير محددة'
    prompt = (
        f'ابحث عن الموقع الرسمي والشعار لكل مشروع منافس في القائمة التالية (المدينة: {city}):\n'
        f'{listing}\n'
        'نفّذ بحثًا منفصلًا لكل مشروع. أرجع JSON فقط بالشكل {"results": [...]} ولكل نتيجة: '
        '"id" كما وصلك، "official_url" صفحة HTTPS من الموقع الرسمي للمشروع أو مطوّره، '
        '"logo_url" رابط HTTPS مباشر لصورة PNG أو JPG أو WEBP على النطاق الرسمي أو نطاق الصور التابع له، '
        '"logo_source_url" الصفحة الرسمية التي ظهر فيها الشعار. '
        'إن لم تجد دليلًا رسميًا لمشروع أعد حقوله فارغة، ولا تخمّن أي رابط.'
    )
    response = None
    for tools_on in (False, True):
        # Plugin-only first: the multi-lookup prompt makes Gemini answer the
        # tool call with MALFORMED_FUNCTION_CALL, so the Exa plugin is the
        # reliable ground — until a deployment where it returns nothing, in
        # which case the server tool is the only remaining path to citations.
        try:
            response, _provider_error = _call_market_study_model(
                market_study.build_consultant_system_prompt(), prompt, max_tokens=4000,
                usage_ctx=_usage_ctx('market', data, tenant_id=tenant_id), server_tools=tools_on)
        except Exception:
            response = None
            continue
        if _market_search_ran(response):
            break
    if not _market_search_ran(response):
        for row in batch:
            row.setdefault('logo_import_warning', 'تعذر التحقق من الموقع الرسمي للشعار')
        return
    parsed, _parse_error = _parse_market_model_json(response)
    discovery_pages = _market_citation_pages(response)
    results = parsed.get('results') if isinstance(parsed, dict) else None
    if not isinstance(results, list):
        results = [parsed] if isinstance(parsed, dict) else []
    by_id = {str(row.get('id') or ''): row for row in batch}
    by_name = {str(row.get('name') or '').strip().casefold(): row for row in batch}

    def _trusted_official_hosts(name):
        """Hosts whose retrieved pages carry the competitor's whole name.

        The model's claimed official_url is only as good as the retrieval
        behind it: accept a host when a real retrieved page on it mentions all
        distinctive name tokens — otherwise a district article on a developer
        site would brand an unrelated project with that developer's logo.
        """
        tokens = _competitor_name_tokens(name)
        if not tokens:
            return set()
        hosts = set()
        for page in discovery_pages:
            page_url = str(page.get('url') or '')
            haystack = market_study._fold_choice(f"{page.get('title') or ''} {page_url}")
            if sum(1 for token in tokens if token in haystack) < len(tokens):
                continue
            host = _normalized_web_host(page_url)
            if host and not any(token in host for token in _AGGREGATOR_HOST_TOKENS):
                hosts.add(host)
        return hosts

    for item in results:
        if not isinstance(item, dict):
            continue
        row = by_id.get(str(item.get('id') or ''))
        if row is None:
            row = by_name.get(str(item.get('name') or '').strip().casefold())
        if row is None:
            continue
        official = str(
            item.get('official_url') or item.get('official_website') or item.get('website')
            or item.get('logo_source_url') or item.get('source_url') or item.get('url') or ''
        ).strip()
        official_host = _normalized_web_host(official)
        if not official_host or not any(
                _related_official_hosts(f'https://{official_host}', f'https://{host}')
                for host in _trusted_official_hosts(row.get('name'))):
            continue
        row['logo_url'] = str(item.get('logo_url') or '').strip()
        row['logo_source_url'] = official
        row['logo_official_verified'] = True
    # The model's JSON is only a formatter — the Exa citations carry the actual
    # retrieved pages. When the reply is malformed (Gemini emits
    # MALFORMED_FUNCTION_CALL on multi-lookup prompts) or misses a row, match
    # those pages to each competitor's name directly.
    for row in batch:
        if row.get('logo_official_verified'):
            continue
        dead_keys = {str(item).strip().casefold() for item in (row.get('dead_source_urls') or [])}
        for page_url in _official_citation_pages(discovery_pages, row.get('name')):
            if page_url.casefold() in dead_keys:
                continue
            row['logo_source_url'] = page_url
            row['logo_official_verified'] = True
            break
    for row in batch:
        if not row.get('logo_official_verified'):
            continue
        official = str(row.get('logo_source_url') or '').strip()
        field_sources = market_study.competitor_field_sources(row)
        urls = field_sources.setdefault('logo_url', [])
        if official and official not in urls:
            urls.append(official)
        row['field_sources'] = field_sources
        if official:
            row['source_urls'] = list(dict.fromkeys(
                market_study.competitor_source_urls(row) + [official]))
        report(86 + int(6 * (batch.index(row) if row in batch else 0) / max(1, len(batch))),
               f'تحميل شعار «{row.get("name") or "منافس"}»...')
        try:
            _store_imported_competitor_logo(row, draft_id=draft_id)
        except Exception as exc:
            row['logo_import_warning'] = str(exc)
    for row in batch:
        if not row.get('logo_file_id') and not row.get('logo_path'):
            row.setdefault('logo_import_warning', 'لم يُعثر على موقع رسمي موثق للشعار')
    # Portal-only competitors have no official site to brand from, but their
    # retrieved listing pages carry the property's own photo in og:image.
    for row in rows:
        if row.get('logo_file_id') or row.get('logo_path'):
            continue
        try:
            _import_competitor_listing_photo(row, draft_id=draft_id)
        except Exception as exc:
            row.setdefault('logo_import_warning', str(exc))


def _store_imported_competitor_logo(row, draft_id=None):
    logo_url = str((row or {}).get('logo_url') or '').strip()
    official_url = str((row or {}).get('logo_source_url') or (row or {}).get('source_url') or '').strip()
    name = str((row or {}).get('name') or 'competitor').strip()
    if not official_url:
        return row
    if not (row or {}).get('logo_official_verified') and not market_study.official_source_reliability(
            name, (row or {}).get('source'), official_url):
        return row
    content = mime_type = extension = None
    error = ''
    candidates = [logo_url] if logo_url else []
    seen = set()
    for candidate in candidates:
        key = str(candidate or '').strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        content, mime_type, extension, error = _safe_download_competitor_logo(candidate, official_url)
        if content:
            logo_url = candidate
            row['logo_url'] = candidate
            break
    if not content:
        candidates, page_error = _official_logo_candidates(official_url)
        for candidate in candidates:
            key = str(candidate or '').strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            content, mime_type, extension, error = _safe_download_competitor_logo(candidate, official_url)
            if content:
                logo_url = candidate
                row['logo_url'] = candidate
                break
        if not content and page_error:
            error = page_error
    if not content:
        favicon_content, favicon_mime, favicon_ext, _favicon_error = _download_official_favicon(official_url)
        if favicon_content:
            content, mime_type, extension = favicon_content, favicon_mime, favicon_ext
            logo_url = ('https://t2.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON'
                        f'&fallback_opts=TYPE,SIZE,URL&url=http://{_normalized_web_host(official_url)}&size=128')
            row['logo_url'] = logo_url
            row['logo_low_res'] = True
            row['logo_favicon_host'] = _normalized_web_host(official_url)
            error = ''
    if error or not content:
        row['logo_import_warning'] = error or 'تعذر استيراد شعار المنافس'
        return row
    from werkzeug.datastructures import FileStorage
    upload = FileStorage(
        stream=BytesIO(content), filename='competitor-logo' + extension, content_type=mime_type,
    )
    stored = _store_project_upload(
        upload, 'competitor_logo', draft_id=draft_id, project_id=str(row.get('id') or '') or None,
    )
    published = _publish_project_file_as_creative_image(stored['id'])
    row['logo_file_id'] = stored['id']
    row['logo_path'] = published or ('/api/project-files/' + stored['id'])
    row['logo_source_url'] = official_url
    row.pop('logo_import_warning', None)
    return row


_LISTING_IMAGE_META_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::url)?|og:image:secure_url'
    r'|twitter:image(?::src)?)["\'][^>]*?content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]*?(?:property|name)=["\']'
    r'(?:og:image(?::url)?|og:image:secure_url|twitter:image(?::src)?)["\']',
    re.IGNORECASE)
_LISTING_IMAGE_SKIP_TOKENS = (
    'logo', 'brand', 'icon', 'sprite', 'favicon', 'placeholder', 'default',
    'share', 'watermark', 'ruwaj', 'rawaj', 'rowaj', '/rwaj', 'rega',
)


def _download_listing_image(image_url):
    """(content, mime, ext) — fetch a listing photo from any public HTTPS host.

    Unlike _safe_download_competitor_logo there is no same-host rule: portal
    CDNs (images.bayut.com) are intentionally different hosts — the file is
    the competitor's own property photo, not the portal's branding."""
    parsed = urlsplit(str(image_url or '').strip())
    try:
        invalid_port = parsed.port not in (None, 443)
    except ValueError:
        invalid_port = True
    if (parsed.scheme.lower() != 'https' or not parsed.hostname
            or parsed.username or invalid_port):
        return None, None, None
    lowered = str(image_url).casefold()
    if any(token in lowered for token in _LISTING_IMAGE_SKIP_TOKENS):
        return None, None, None
    if not _public_host_addresses(parsed.hostname):
        return None, None, None
    pool, response, _outcome = _pinned_https_get(image_url)
    if pool is None:
        return None, None, None
    try:
        if response.status != 200:
            return None, None, None
        mime_type = str(response.headers.get('Content-Type') or '').split(';', 1)[0].strip().lower()
        extension = COMPETITOR_LOGO_MIMES.get(mime_type)
        if not extension:
            return None, None, None
        content = bytearray()
        for chunk in response.stream(64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > COMPETITOR_LOGO_MAX_BYTES:
                return None, None, None
        return bytes(content), mime_type, extension
    except Exception:
        return None, None, None
    finally:
        response.release_conn()
        pool.close()


def _import_competitor_listing_photo(row, draft_id=None):
    """Last-resort competitor image: the retrieved listing page's own photo.

    Portal-only competitors have no official site to brand from, but their
    retrieved listing pages carry the property's photo in og:image. Stored
    through the same upload path and marked logo_listing_photo so it never
    pretends to be an official logo."""
    dead = {str(item).strip().casefold() for item in (row.get('dead_source_urls') or [])}
    misses = []
    for page_url in list(dict.fromkeys(market_study.competitor_source_urls(row)))[:4]:
        if str(page_url).strip().casefold() in dead:
            continue
        html, _err = _read_market_source_page(page_url)
        if not html:
            misses.append(f'{_normalized_web_host(page_url)}:unreadable')
            continue
        found_meta = False
        for match in _LISTING_IMAGE_META_RE.finditer(html):
            found_meta = True
            image_url = urljoin(page_url, match.group(1) or match.group(2) or '')
            content, mime_type, extension = _download_listing_image(image_url)
            if not content:
                misses.append(f'{_normalized_web_host(page_url)}:image-rejected')
                continue
            from werkzeug.datastructures import FileStorage
            upload = FileStorage(
                stream=BytesIO(content), filename='competitor-photo' + extension,
                content_type=mime_type)
            stored = _store_project_upload(
                upload, 'competitor_logo', draft_id=draft_id,
                project_id=str(row.get('id') or '') or None)
            published = _publish_project_file_as_creative_image(stored['id'])
            row['logo_file_id'] = stored['id']
            row['logo_path'] = published or ('/api/project-files/' + stored['id'])
            row['logo_url'] = image_url
            row['logo_source_url'] = page_url
            row['logo_listing_photo'] = True
            row.pop('logo_import_warning', None)
            field_sources = market_study.competitor_field_sources(row)
            urls = field_sources.setdefault('logo_url', [])
            if page_url not in urls:
                urls.append(page_url)
            row['field_sources'] = field_sources
            return
        if not found_meta:
            misses.append(f'{_normalized_web_host(page_url)}:no-og-image')
    if misses:
        print(f"[MARKET STUDY] «{row.get('name') or 'منافس'}» no listing photo: "
              + ', '.join(misses))
