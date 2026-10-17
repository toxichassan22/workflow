"""Sync and extract official Ministry of Tourism PDF publications for market research.

The CMS endpoint is used only as a document directory. Numeric evidence is
attached to the official PDF URL on cdn.mt.gov.sa, and no model is given access
to another source through this adapter.
"""

from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urljoin, urlparse, urlunparse


PUBLICATIONS_PAGE = 'https://tourism.sa/ar/data-insights/publications'
PUBLICATIONS_API = 'https://cms.tourism.sa/api/publications'
REPORT_CACHE_DIR = Path(__file__).resolve().parent / 'market_data' / 'tourism_reports'
PDF_HOST = 'cdn.mt.gov.sa'
CATALOG_MAX_PAGES = 5
MAX_REPORTS = 14
MAX_PDF_BYTES = 55 * 1024 * 1024
MAX_TOTAL_DOWNLOAD_BYTES = 160 * 1024 * 1024
MAX_EVIDENCE_PAGES = 12
MAX_PAGES_PER_REPORT = 2
MAX_PAGE_TEXT_CHARS = 2400
RESEARCH_CONTEXT_MAX_CHARS = 26000
REPORT_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

_RELEVANT_TITLE_TERMS = (
    'أداء قطاع الضيافة', 'أداء قطاع السياحة', 'الإحصاءات السياحية',
    'إحصاءات سياحية', 'مؤشرات السياحة', 'المؤشرات السياحية',
    'السياحة الوافدة', 'السياحة المحلية', 'الاستثمارات العالمية في السياحة',
    'استثمارات السياحة', 'tourism statistics', 'tourism indicators',
    'tourism performance', 'tourism demand', 'hospitality performance',
    'inbound tourism', 'domestic tourism',
)
_RELEVANT_PAGE_TERMS = (
    'السياح', 'سياح', 'السياحة', 'الضيافة', 'الفنادق', 'فندق', 'الإشغال',
    'اشغال', 'الغرف', 'الزوار', 'السائح', 'السياحة الوافدة', 'السياحة المحلية',
    'الإنفاق السياحي', 'انفاق سياحي', 'متوسط السعر', 'سعر الغرفة', 'adr',
    'revpar', 'occupancy', 'hotel', 'room', 'visitor', 'tourist',
)
_CATEGORY_TERMS = ('التقارير', 'الرسوم البيانية', 'reports', 'infographics')
_ARABIC_DIACRITICS = re.compile(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]')
_WHITESPACE = re.compile(r'\s+')


def _normalize_text(value):
    text = _ARABIC_DIACRITICS.sub('', str(value or '')).lower()
    text = text.translate(str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي'}))
    return _WHITESPACE.sub(' ', text).strip()


def _safe_https_url(url, allowed_host):
    parsed = urlparse(str(url or '').strip())
    try:
        has_port = bool(parsed.port)
    except ValueError:
        return ''
    if (parsed.scheme.lower() != 'https' or not parsed.hostname
            or parsed.hostname.lower() != allowed_host
            or parsed.username or parsed.password or has_port):
        return ''
    return urlunparse(('https', allowed_host, parsed.path or '/',
                       '', parsed.query, ''))


def _field_text(value):
    if isinstance(value, dict):
        for key in ('name', 'title', 'label', 'value'):
            if value.get(key):
                return _field_text(value[key])
        for key in ('attributes', 'data'):
            if value.get(key) is not None:
                return _field_text(value[key])
    if isinstance(value, list):
        return ' '.join(_field_text(item) for item in value)
    return str(value or '').strip()


def _asset_url(record):
    fields = record.get('attributes') if isinstance(record.get('attributes'), dict) else record
    for key in ('file', 'document', 'attachment', 'pdf'):
        asset = fields.get(key) if isinstance(fields, dict) else None
        for _ in range(5):
            if isinstance(asset, str):
                return asset.strip()
            if not isinstance(asset, dict):
                break
            if asset.get('url'):
                return str(asset['url']).strip()
            asset = asset.get('data') or asset.get('attributes') or asset.get('file')
    return ''


def _record_date(fields, title):
    raw_year = fields.get('year') or fields.get('reportYear') or fields.get('report_year')
    year_match = re.search(r'\b(20\d{2})\b', str(raw_year or ''))
    if not year_match:
        year_match = re.search(r'\b(20\d{2})\b', title)
    raw_date = (fields.get('publishedDate') or fields.get('published_date')
                or fields.get('publishedAt') or fields.get('published_at') or '')
    date_text = str(raw_date or '')[:10]
    try:
        parsed_date = date.fromisoformat(date_text)
    except (TypeError, ValueError):
        parsed_date = None
    year = int(year_match.group(1)) if year_match else (parsed_date.year if parsed_date else 0)
    sort_date = parsed_date.isoformat() if parsed_date else f'{year:04d}-01-01'
    return year, sort_date


def _normalize_publication(item, today=None):
    if not isinstance(item, dict):
        return None
    fields = item.get('attributes') if isinstance(item.get('attributes'), dict) else item
    title = _field_text(fields.get('title') or fields.get('name') or fields.get('publicationTitle'))
    category = _field_text(fields.get('category') or fields.get('type'))
    file_url = _asset_url(item)
    if file_url.startswith('/'):
        file_url = urljoin(f'https://{PDF_HOST}/', file_url.lstrip('/'))
    else:
        file_url = urljoin(f'https://{PDF_HOST}/', file_url)
    file_url = _safe_https_url(file_url, PDF_HOST)
    if not title or not file_url:
        return None
    normalized_title = _normalize_text(title)
    normalized_category = _normalize_text(category)
    if not any(_normalize_text(term) in normalized_title for term in _RELEVANT_TITLE_TERMS):
        return None
    if category and not any(_normalize_text(term) in normalized_category for term in _CATEGORY_TERMS):
        return None
    year, published_date = _record_date(fields, title)
    current_year = (today or date.today()).year
    if not year or year < current_year - 3 or year > current_year + 1:
        return None
    identifier = str(item.get('id') or fields.get('id') or sha256(file_url.encode()).hexdigest()[:12])
    return {
        'id': identifier[:80], 'title': title[:500], 'category': category[:100],
        'year': year, 'published_date': published_date,
        'url': file_url,
    }


def _catalog_rows(payload):
    if isinstance(payload, list):
        return payload, 1
    if not isinstance(payload, dict):
        return [], 1
    rows = payload.get('data')
    if not isinstance(rows, list):
        rows = payload.get('publications')
    rows = rows if isinstance(rows, list) else []
    meta = payload.get('meta') if isinstance(payload.get('meta'), dict) else {}
    pagination = meta.get('pagination') if isinstance(meta.get('pagination'), dict) else {}
    try:
        page_count = min(CATALOG_MAX_PAGES, max(1, int(pagination.get('pageCount') or 1)))
    except (TypeError, ValueError):
        page_count = 1
    return rows, page_count


def _dedupe_publications(reports):
    """Keep the newest record when the CMS lists duplicate PDF editions."""
    selected = {}
    for report in reports:
        title_key = _normalize_text(report.get('title'))
        title_key = re.sub(
            r'نسخ[هة]\s+(?:جوال\s+)?تفاعلي[هة]|نسخ[هة]\s+جوال|\bmobile\b|\binteractive\b',
            '', title_key)
        title_key = _WHITESPACE.sub(' ', title_key).strip()
        key = (report.get('year'), title_key or report.get('url'))
        current = selected.get(key)
        if current is None or report.get('published_date', '') > current.get('published_date', ''):
            selected[key] = report
    return list(selected.values())


def _select_publications(reports, max_reports=MAX_REPORTS):
    """Keep recent evidence plus annual-statistics baselines for comparison."""
    ordered = sorted(reports or [],
                     key=lambda item: (item.get('published_date', ''),
                                       item.get('year', 0), item.get('id', '')),
                     reverse=True)
    annual_by_year = {}
    for report in ordered:
        title = _normalize_text(report.get('title'))
        if 'التقرير الاحصائي السنوي' not in title and 'annual tourism statistics' not in title:
            continue
        year = report.get('year')
        if year and year not in annual_by_year:
            annual_by_year[year] = report
    keep = {report['url'] for report in
            sorted(annual_by_year.values(), key=lambda item: item['year'], reverse=True)}
    selected = [report for report in ordered if report.get('url') in keep]
    for report in ordered:
        if report.get('url') not in keep and len(selected) < max_reports:
            selected.append(report)
            keep.add(report.get('url'))
    selected.sort(key=lambda item: (item.get('published_date', ''),
                                    item.get('year', 0), item.get('id', '')),
                  reverse=True)
    return selected[:max_reports]


def _fetch_catalog(session, trace=None):
    rows = []
    for page in range(1, CATALOG_MAX_PAGES + 1):
        response = session.get(
            PUBLICATIONS_API,
            params={'populate': '*', 'pagination[page]': page,
                    'pagination[pageSize]': 100, 'locale': 'ar'},
            timeout=(8, 30), allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError(f'catalog_http_{response.status_code}')
        payload = response.json()
        page_rows, page_count = _catalog_rows(payload)
        rows.extend(page_rows)
        if page >= page_count or len(page_rows) < 100:
            break
    if callable(trace):
        trace({'event': 'tourism_catalog_loaded', 'source': PUBLICATIONS_PAGE,
               'records_seen': len(rows)})
    return rows


def _source_manifest_files(cache_dir):
    manifest_path = cache_dir / 'source_manifest.json'
    try:
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {}
    result = {}
    for report in data.get('reports', []) if isinstance(data, dict) else []:
        if not isinstance(report, dict):
            continue
        source_url = _safe_https_url(report.get('source_url'), PDF_HOST)
        name = Path(str(report.get('file_name') or '')).name
        if source_url and name and name == str(report.get('file_name') or ''):
            candidate = cache_dir / name
            if candidate.is_file():
                result[source_url] = candidate
    return result


def _cache_path(report, cache_dir):
    digest = sha256(report['url'].encode('utf-8')).hexdigest()[:12]
    safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', report['id'])[:32]
    return cache_dir / f'ministry_{safe_id}_{digest}.pdf'


def _is_cached_pdf(path, now=None):
    try:
        stat = path.stat()
        if not path.is_file() or stat.st_size < 8 or stat.st_size > MAX_PDF_BYTES:
            return False
        if (now or datetime.now().timestamp()) - stat.st_mtime > REPORT_CACHE_TTL_SECONDS:
            return False
        with path.open('rb') as handle:
            return handle.read(5) == b'%PDF-'
    except OSError:
        return False


def _download_pdf(session, url, target, max_bytes=MAX_PDF_BYTES):
    current_url = _safe_https_url(url, PDF_HOST)
    if not current_url:
        raise RuntimeError('pdf_url_not_allowed')
    for _redirect in range(4):
        response = session.get(current_url, stream=True, timeout=(8, 60),
                               allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get('Location') or response.headers.get('location')
            response.close()
            next_url = _safe_https_url(urljoin(current_url, location or ''), PDF_HOST)
            if not next_url:
                raise RuntimeError('pdf_redirect_not_allowed')
            current_url = next_url
            continue
        if response.status_code != 200:
            response.close()
            raise RuntimeError(f'pdf_http_{response.status_code}')
        total = 0
        first = b''
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode='wb', dir=str(target.parent), suffix='.part',
                    delete=False) as handle:
                temp_path = Path(handle.name)
                for chunk in response.iter_content(chunk_size=128 * 1024):
                    if not chunk:
                        continue
                    if not first:
                        first = chunk[:5]
                    total += len(chunk)
                    if total > min(MAX_PDF_BYTES, max_bytes):
                        raise RuntimeError('pdf_or_download_budget_exceeded')
                    handle.write(chunk)
            if first != b'%PDF-':
                raise RuntimeError('pdf_signature_invalid')
            os.replace(temp_path, target)
            return total
        except Exception:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        finally:
            response.close()
    raise RuntimeError('pdf_redirect_limit')


def _page_score(text, city='', district=''):
    folded = _normalize_text(text)
    cities = city if isinstance(city, (list, tuple, set)) else [city]
    districts = district if isinstance(district, (list, tuple, set)) else [district]
    score = 0
    score += sum(30 for item in districts
                 if _normalize_text(item) and _normalize_text(item) in folded)
    score += sum(18 for item in cities
                 if _normalize_text(item) and _normalize_text(item) in folded)
    score += sum(4 for term in _RELEVANT_PAGE_TERMS
                 if _normalize_text(term) in folded)
    if re.search(r'\d[\d,.٪%]*', folded):
        score += 1
    if any(term in folded for term in ('إخلاء مسؤولية', 'اخلاء مسؤوليه', 'المقدمة')):
        score -= 4
    return score


def _extract_pdf_pages(path, city='', district=''):
    try:
        import fitz
    except Exception as exc:
        raise RuntimeError('pymupdf_unavailable') from exc
    try:
        with fitz.open(str(path)) as document:
            candidates = []
            for page_index in range(len(document)):
                text = _WHITESPACE.sub(' ', document[page_index].get_text('text') or '').strip()
                if not text:
                    continue
                score = _page_score(text, city=city, district=district)
                if score > 0:
                    candidates.append({
                        'page_number': page_index + 1,
                        'score': score,
                        'content': text[:MAX_PAGE_TEXT_CHARS],
                    })
            candidates.sort(key=lambda item: (-item['score'], item['page_number']))
            return len(document), candidates
    except Exception as exc:
        raise RuntimeError('pdf_parse_failed') from exc


def _add_page_to_pool(pool, report, page):
    if pool is None or not callable(getattr(pool, 'add_page', None)):
        return False
    page_number = int(page['page_number'])
    source_url = f"{report['url']}#page={page_number}"
    title = f"{report['title']} — الصفحة {page_number} ({report['year']})"
    pool.add_page(source_url, title=title, content=page['content'],
                  final_url=source_url, via='ministry_pdf')
    return True


def sync_ministry_tourism_reports(evidence_pool=None, city='', district='',
                                  cache_dir=None, session=None, trace=None,
                                  today=None):
    """Find current ministry PDFs, cache them locally, and add relevant pages.

    Network, PDF parsing and per-report failures are returned as diagnostics;
    they never abort the rest of the market study. The metadata API host and
    every PDF/redirect host are checked against exact official allowlists.
    """
    cache_dir = Path(cache_dir or REPORT_CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    owns_session = session is None
    if owns_session:
        import requests
        session = requests.Session()
    result = {'source_page': PUBLICATIONS_PAGE, 'reports': [], 'errors': [],
              'records_seen': 0, 'pages_added': 0, 'pages_selected': 0}

    def close_owned_session():
        if owns_session:
            try:
                session.close()
            except Exception:
                pass

    try:
        rows = _fetch_catalog(session, trace=trace)
    except Exception as exc:
        result['errors'].append(str(exc)[:200])
        if callable(trace):
            trace({'event': 'tourism_catalog_failed', 'reason': str(exc)[:200]})
        close_owned_session()
        return result
    result['records_seen'] = len(rows)
    today = today or date.today()
    reports = _dedupe_publications([
        report for report in
        (_normalize_publication(item, today=today) for item in rows)
        if report])
    reports = _select_publications(reports)
    existing = _source_manifest_files(cache_dir)
    candidates = []
    downloaded_total = 0
    for report in reports:
        cache_path = _cache_path(report, cache_dir)
        source_path = existing.get(report['url'])
        if source_path and _is_cached_pdf(source_path):
            cache_path = source_path
            cached = True
        else:
            cached = _is_cached_pdf(cache_path)
        try:
            if not cached:
                remaining_bytes = MAX_TOTAL_DOWNLOAD_BYTES - downloaded_total
                if remaining_bytes <= 0:
                    raise RuntimeError('total_download_budget_exceeded')
                downloaded_bytes = _download_pdf(
                    session, report['url'], cache_path, max_bytes=remaining_bytes)
                downloaded_total += downloaded_bytes
            else:
                downloaded_bytes = 0
            page_count, pages = _extract_pdf_pages(
                cache_path, city=city, district=district)
            report_result = {
                **report,
                'page_count': page_count,
                'downloaded': bool(downloaded_bytes),
                'cached': bool(cached),
                'downloaded_bytes': downloaded_bytes,
                'pages': pages[:MAX_PAGES_PER_REPORT],
            }
            candidates.extend((page['score'], report['published_date'], report_result, page)
                              for page in report_result['pages'])
            result['reports'].append(report_result)
            if callable(trace):
                trace({
                    'event': 'tourism_pdf_processed', 'title': report['title'],
                    'url': report['url'], 'year': report['year'],
                    'page_count': page_count, 'selected_pages': [
                        page['page_number'] for page in report_result['pages']],
                    'extracted_page_count': len(pages),
                    'downloaded': bool(downloaded_bytes),
                    'downloaded_bytes': downloaded_bytes,
                })
        except Exception as exc:
            reason = str(exc)[:200]
            result['errors'].append({'title': report['title'], 'url': report['url'],
                                     'reason': reason})
            if callable(trace):
                trace({'event': 'tourism_pdf_failed', 'title': report['title'],
                       'url': report['url'], 'reason': reason})
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen = []
    per_report = {}
    for score, published_date, report, page in candidates:
        if per_report.get(report['url'], 0) >= MAX_PAGES_PER_REPORT:
            continue
        chosen.append((score, published_date, report, page))
        per_report[report['url']] = per_report.get(report['url'], 0) + 1
        if len(chosen) >= MAX_EVIDENCE_PAGES:
            break
    selected_by_url = {}
    for _score, _published_date, report, page in chosen:
        if _add_page_to_pool(evidence_pool, report, page):
            result['pages_added'] += 1
        selected_by_url.setdefault(report['url'], set()).add(page['page_number'])
        result['pages_selected'] += 1
    for report in result['reports']:
        selected = selected_by_url.get(report['url'], set())
        report['pages'] = [page for page in report['pages']
                           if page['page_number'] in selected]
    if callable(trace):
        trace({'event': 'tourism_sync_complete', 'reports_processed': len(result['reports']),
               'pages_added': result['pages_added'],
               'pages_selected': result['pages_selected'],
               'errors': len(result['errors'])})
    close_owned_session()
    return result


def format_research_context(reports, hosts, offer_lang='ar'):
    """Add bounded official PDF text and direct report URLs to the ministry researcher."""
    if not any(str(host).lower() in ('mt.gov.sa', 'cdn.mt.gov.sa')
               or str(host).lower().endswith('.mt.gov.sa') for host in hosts or []):
        return ''
    reports = reports if isinstance(reports, list) else []
    if not reports:
        return ''
    english = str(offer_lang or 'ar').lower().startswith('en')
    header = ('Official Ministry of Tourism PDF reports already retrieved from the approved source list. '
              'Open the direct PDF links when possible, compare the extracted report pages below, and '
              'cite only the official report URL. These are Saudi Arabia or city-level values only where '
              'the report explicitly shows that geography; never turn a national value into a city value.\n'
              if english else
              'تقارير وزارة السياحة الرسمية المسترجعة من قائمة المصادر المعتمدة. افتح روابط PDF المباشرة '
              'إن أمكن، وقارن صفحات التقارير المستخرجة أدناه، واستشهد برابط التقرير الرسمي فقط. هذه '
              'بيانات للمملكة أو للمدينة فقط عندما يحدد التقرير ذلك صراحة؛ لا تنسب رقمًا وطنيًا إلى المدينة.\n')
    blocks = []
    total = len(header)
    for report in reports:
        if not isinstance(report, dict):
            continue
        url = _safe_https_url(report.get('url'), PDF_HOST)
        if not url:
            continue
        title = str(report.get('title') or url).strip()[:500]
        year = str(report.get('year') or '').strip()
        url_label = 'URL' if english else 'الرابط'
        page_label = 'Page' if english else 'الصفحة'
        block = f"\n## {title} ({year})\n{url_label}: {url}\n"
        for page in report.get('pages') or []:
            if not isinstance(page, dict):
                continue
            try:
                page_number = int(page.get('page_number'))
            except (TypeError, ValueError):
                continue
            page_text = str(page.get('content') or '').strip()[:MAX_PAGE_TEXT_CHARS]
            if not page_text:
                continue
            block += f"{page_label} {page_number}: {page_text}\n"
        if total + len(block) > RESEARCH_CONTEXT_MAX_CHARS:
            remaining = RESEARCH_CONTEXT_MAX_CHARS - total
            if remaining > 250:
                blocks.append(block[:remaining])
            break
        blocks.append(block)
        total += len(block)
    return header + ''.join(blocks) if blocks else ''
