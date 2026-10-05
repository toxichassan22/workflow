# -*- coding: utf-8 -*-
"""Per-city regulation documents: normalize, discover, cache, and gate.

The verified ``rules/`` digest and the municipal اشتراطات*.pdf pair that ship
on the server cover Jeddah only. A croquis for any other declared city must
never read them — feeding Jeddah's tables into a Riyadh analysis once made
the model reconcile two different cities' codes inside one prompt.

For a non-local city this module either supplies that city's own official
regulation PDFs and caches them under ``regulations/<city>/``, or tells the
caller plainly that no verified regulations exist. Sources are tried in two
tiers: a curated registry of known-official document URLs
(``NATIONAL_REGULATION_URLS`` + ``CITY_REGULATION_URLS``) is fetched first —
deterministically, with no model involvement — and only when the registry has
nothing for the city does an OpenRouter ``web`` plugin (Exa) search run, still
restricted to government hosts. In the failure case the model's own knowledge
stays marked as ``model_knowledge`` instead of being laundered through
another city's document.
"""
import glob
import io
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests

# The verified corpus (rules/*.json + اشتراطات*.pdf at the app root) describes
# this city's municipal code. Everything else is a foreign city.
_LOCAL_REGULATIONS_CITY = (
    os.environ.get('LOCAL_REGULATIONS_CITY') or 'jeddah').strip() or 'jeddah'

REGULATIONS_DIR = os.environ.get('REGULATIONS_DIR') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'regulations')
CITY_REGULATION_FETCH = os.environ.get('CITY_REGULATION_FETCH', '1') != '0'
CITY_REGULATION_MAX_DOCS = max(1, int(os.environ.get('CITY_REGULATION_MAX_DOCS', '2')))
CITY_REGULATION_MAX_BYTES = max(
    1 << 20, int(os.environ.get('CITY_REGULATION_MAX_BYTES', str(80 << 20))))
CITY_REGULATION_TIMEOUT = max(5, int(os.environ.get('CITY_REGULATION_TIMEOUT', '60')))
CITY_REGULATION_MAX_RESULTS = max(
    4, min(20, int(os.environ.get('CITY_REGULATION_MAX_RESULTS', '10'))))

_CITY_ALIASES = {
    'riyadh': ('الرياض', 'رياض', 'riyadh', 'ar-riyadh', 'ar riyadh', 'alriyadh', 'al riyadh'),
    'jeddah': ('جدة', 'jeddah', 'jiddah', 'jedda'),
    'makkah': ('مكة', 'مكة المكرمة', 'makkah', 'mecca', 'mekkah'),
    'madinah': ('المدينة', 'المدينة المنورة', 'madinah', 'medina', 'madina'),
    'dammam': ('الدمام', 'dammam', 'ad-dammam', 'ad dammam'),
    'khobar': ('الخبر', 'khobar', 'al-khobar', 'al khobar', 'alkhobar'),
    'taif': ('الطائف', 'taif', 'al-taif'),
    'abha': ('أبها', 'ابها', 'abha'),
    'tabuk': ('تبوك', 'tabuk'),
    'buraydah': ('بريدة', 'buraydah', 'buraidah'),
    'qassim': ('القصيم', 'qassim', 'qasim', 'al-qassim'),
    'hail': ('حائل', 'hail', 'hael'),
    'jazan': ('جازان', 'جيزان', 'jazan', 'jizan'),
    'najran': ('نجران', 'najran'),
    'baha': ('الباحة', 'baha', 'al-baha', 'al baha', 'albaha'),
    'jouf': ('الجوف', 'jouf', 'al-jouf', 'al jouf', 'سكاكا', 'skaka'),
    'ahsa': ('الأحساء', 'الاحساء', 'الهفوف', 'هفوف', 'ahsa', 'al-ahsa', 'al ahsa',
             'hofuf', 'hufuf', 'al-hofuf'),
    'yanbu': ('ينبع', 'yanbu'),
    'jubail': ('الجبيل', 'jubail'),
    'khamis': ('خميس مشيط', 'khamis', 'khamis mushait', 'khamis mushayt'),
}

_CITY_LABELS = {
    'riyadh': 'الرياض', 'jeddah': 'جدة', 'makkah': 'مكة المكرمة',
    'madinah': 'المدينة المنورة', 'dammam': 'الدمام', 'khobar': 'الخبر',
    'taif': 'الطائف', 'abha': 'أبها', 'tabuk': 'تبوك', 'buraydah': 'بريدة',
    'qassim': 'القصيم', 'hail': 'حائل', 'jazan': 'جازان', 'najran': 'نجران',
    'baha': 'الباحة', 'jouf': 'الجوف', 'ahsa': 'الأحساء', 'yanbu': 'ينبع',
    'jubail': 'الجبيل', 'khamis': 'خميس مشيط',
}

_ALEF_VARIANTS = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي'})

# Official hosts outside the *.gov.sa suffix that still count as government
# sources; extra domains can be appended via CITY_REGULATION_EXTRA_HOSTS.
_OFFICIAL_HOSTS = {'riyadh.sa', 'www.riyadh.sa', 'momrah.net', 'www.momrah.net'}

# Curated registry of verified official documents, fetched before any search.
# The national ministry document (قرار وزاري 4500943139, اشتراطات إنشاء
# المباني السكنية 1446هـ) states it is binding on all amanat, so it ships as
# the baseline for every foreign city; city entries add that amanah's own
# official code volumes. Extend a city list rather than trusting search.
NATIONAL_REGULATION_URLS = (
    'https://momah.gov.sa/sites/default/files/2024-07/'
    'ashtratat%20a%27nsha%20almbany%20alsknyt%20m%60%20alqrar.pdf',
)
CITY_REGULATION_URLS = {
    'riyadh': (
        'https://eservices.alriyadh.gov.sa/Documents/BuildingCodes/T3.1%20v2.2.pdf',
        'https://cts.alriyadh.gov.sa/Documents/BuildingCodes/T5.2%20v2.0.pdf',
    ),
}

# Known official amanah/authority domains per city. Domains are not uniform
# (الرياض is alriyadh.gov.sa, مكة is holymakkah.gov.sa), so per-city seeds are
# probed first and generic patterns ({slug}.gov.sa, al{slug}.gov.sa, …) are
# generated for every slug — whichever answers HTTPS is that city's official
# host and discovery is scoped to it.
CITY_AMANA_HOSTS = {
    'jeddah': ('jeddah.gov.sa',),
    'riyadh': ('alriyadh.gov.sa', 'eservices.alriyadh.gov.sa',
               'cts.alriyadh.gov.sa', 'trc.alriyadh.gov.sa', 'riyadh.sa'),
    'makkah': ('holymakkah.gov.sa', 'makkah.gov.sa'),
    'madinah': ('amana-md.gov.sa', 'madinah.gov.sa'),
    'dammam': ('eamana.gov.sa',),
    'khobar': ('eamana.gov.sa',),
    'ahsa': ('eamana.gov.sa', 'ahsa.gov.sa'),
    'taif': ('taif.gov.sa',),
    'tabuk': ('tabuk.gov.sa',),
    'buraydah': ('qassim.gov.sa',),
    'qassim': ('qassim.gov.sa',),
    'hail': ('hail.gov.sa',),
    'jazan': ('jazan.gov.sa',),
    'najran': ('najran.gov.sa',),
    'baha': ('baha.gov.sa',),
    'jouf': ('jouf.gov.sa', 'joufamana.gov.sa'),
    'yanbu': ('rcyb.gov.sa',),
    'jubail': ('rcjy.gov.sa',),
    'khamis': ('asir.gov.sa',),
    'abha': ('asir.gov.sa', 'abha.gov.sa'),
}
_AMANA_PROBE_TIMEOUT = max(3, int(os.environ.get('CITY_AMANA_PROBE_TIMEOUT', '8')))
_AMANA_HOSTS_TTL_SECONDS = 24 * 3600

# A downloaded file only counts as a regulation document when its text
# mentions regulation vocabulary; an unrelated government PDF is rejected.
_REGULATION_KEYWORDS = (
    'اشتراط', 'إشتراط', 'نظام', 'ضوابط', 'لائحة', 'لايحة',
    'كود البناء', 'الأمانة', 'الامانة', 'البلدية',
)

_FILENAME_SAFE = re.compile(r'[^\w.\-]+', re.UNICODE)


def _fold(text):
    return str(text or '').translate(_ALEF_VARIANTS).casefold()


def normalize_city(value):
    """Arabic/English city spellings → a canonical slug ('riyadh', …) or ''."""
    text = re.sub(r'\s+', ' ', _fold(value)).strip()
    if not text:
        return ''
    for slug, aliases in _CITY_ALIASES.items():
        for alias in aliases:
            folded = _fold(alias)
            if text == folded or folded in text:
                return slug
    return ''


def city_label(slug):
    return _CITY_LABELS.get(slug, slug)


def local_regulations_city():
    return _LOCAL_REGULATIONS_CITY


def is_local_city(slug):
    """'' (undeclared) keeps the legacy local-documents behavior; anything
    resolvable to another city is foreign."""
    return not slug or slug == _LOCAL_REGULATIONS_CITY


def resolve_site_city(value):
    """(slug, display_label) for the declared city.

    A city we do not know still becomes foreign: it gets a filesystem-safe
    slug derived from the raw text so its fetched documents cache separately
    instead of silently falling back to Jeddah's files."""
    slug = normalize_city(value)
    if slug:
        return slug, _CITY_LABELS[slug]
    raw = re.sub(r'\s+', ' ', str(value or '')).strip()
    if not raw:
        return '', ''
    safe = _FILENAME_SAFE.sub('-', raw).strip('-').lower()[:48]
    return safe, raw


def city_docs_dir(slug):
    return os.path.join(REGULATIONS_DIR, slug)


def cached_city_pdf_paths(slug):
    directory = city_docs_dir(slug)
    if not slug or not os.path.isdir(directory):
        return []
    return sorted(
        path for path in glob.glob(os.path.join(directory, '*.pdf'))
        if os.path.isfile(path))


def _sources_path(slug):
    return os.path.join(city_docs_dir(slug), 'sources.json')


def load_city_sources(slug):
    """{filename: {'url', 'fetched_at'}} for provenance metadata."""
    try:
        with open(_sources_path(slug), encoding='utf-8') as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_city_sources(slug, sources):
    try:
        os.makedirs(city_docs_dir(slug), exist_ok=True)
        with open(_sources_path(slug), 'w', encoding='utf-8') as handle:
            json.dump(sources, handle, ensure_ascii=False, indent=2)
    except OSError:
        pass


def is_official_regulation_url(url):
    """Only government domains may feed regulation values."""
    try:
        parts = urlsplit(str(url or '').strip())
    except Exception:
        return False
    if parts.scheme not in ('http', 'https'):
        return False
    host = (parts.hostname or '').lower()
    if not host:
        return False
    if host == 'gov.sa' or host.endswith('.gov.sa'):
        return True
    extra = {
        item.strip().lower()
        for item in os.environ.get('CITY_REGULATION_EXTRA_HOSTS', '').split(',')
        if item.strip()
    }
    return host in _OFFICIAL_HOSTS or host in extra


def _amana_host_candidates(slug):
    """Ordered official-host candidates: seeded domains then slug patterns."""
    candidates = list(CITY_AMANA_HOSTS.get(slug) or ())
    candidates += [
        f'{slug}.gov.sa', f'al{slug}.gov.sa',
        f'amana{slug}.gov.sa', f'amana-{slug}.gov.sa',
    ]
    seen, ordered = set(), []
    for host in candidates:
        host = str(host or '').strip().lower()
        if host and host not in seen:
            seen.add(host)
            ordered.append(host)
    return ordered


def _probe_amana_host(host):
    """Return the host when it answers HTTPS on an official domain."""
    url = f'https://{host}/'
    for method in (requests.head, requests.get):
        try:
            resp = method(url, timeout=_AMANA_PROBE_TIMEOUT,
                          allow_redirects=True, stream=True)
            resp.close()
        except Exception:
            continue
        if resp.status_code >= 500:
            return None
        if is_official_regulation_url(resp.url or url):
            return host
        return None
    return None


def resolve_city_amana_hosts(slug):
    """Live official amanah hosts for the city — probed once, cached 24h."""
    if not slug:
        return []
    sources = load_city_sources(slug)
    cached = sources.get('_amana_hosts')
    if isinstance(cached, dict):
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(str(cached.get('probed_at') or ''))
                   ).total_seconds()
        except ValueError:
            age = _AMANA_HOSTS_TTL_SECONDS + 1
        if age < _AMANA_HOSTS_TTL_SECONDS:
            return [h for h in cached.get('hosts') or [] if isinstance(h, str)]
    candidates = _amana_host_candidates(slug)
    if not candidates:
        return []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as pool:
        found = [host for host in pool.map(_probe_amana_host, candidates) if host]
    sources['_amana_hosts'] = {
        'hosts': found,
        'probed_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    _save_city_sources(slug, sources)
    if found:
        print(f'[CITY REGULATIONS] {slug}: official host(s) '
              + ', '.join(found))
    return found


def _response_text(res):
    try:
        content = res['choices'][0]['message'].get('content')
    except Exception:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(
            str(part.get('text') or '') for part in content if isinstance(part, dict))
    return ''


def _parse_json_block(text):
    match = re.search(r'\{.*\}', str(text or ''), re.S)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}


def discover_city_regulation_urls(slug, city, chat_fn, usage_ctx=None, hosts=None):
    """Direct official PDF URLs for a city's building regulations.

    The ``web`` plugin (Exa) executes the search on OpenRouter's side for
    every request — unlike the provider's native tool, which the model is
    free to skip. The model only picks which returned links are official
    PDFs; it never invents a URL. When ``hosts`` carries the city's probed
    amanah domain(s), results on those domains take priority over any other
    government host."""
    label = city or slug
    host_hint = ''
    if hosts:
        host_hint = (
            f"الدومين الرسمي لأمانة المدينة هو {' / '.join(hosts)} — "
            "أعطِ أولوية قصوى للروابط المستضافة عليه.")
    system_prompt = (
        "أنت باحث وثائق حكومية سعودية. أعد JSON فقط بهذا الشكل: "
        "{\"pdf_urls\":[\"https://...\"]} — بدون أي نص أو شرح إضافي.")
    user_prompt = (
        f"ابحث في نتائج البحث المرفقة عن روابط مباشرة لملفات PDF رسمية تحتوي "
        f"أنظمة وضوابط البناء / الاشتراطات البلدية / المخطط المحلي الصادرة عن "
        f"أمانة {label} أو الجهة المختصة في مدينة {label} بالسعودية. "
        "اقبل الروابط من المواقع الحكومية الرسمية فقط (gov.sa أو موقع الأمانة). "
        f"{host_hint} "
        "استبعد صفحات HTML والأخبار والمقالات والمواقع التجارية. "
        "أعِد حتى 4 روابط — وثيقة الأنظمة والضوابط واللائحة التنفيذية أولوية — "
        "وإن لم تجد ملف PDF رسميًا أعد {\"pdf_urls\":[]}.")
    try:
        res = chat_fn(
            system_prompt, user_prompt,
            temperature=None, max_tokens=1200,
            response_format={'type': 'json_object'},
            plugins=[{'id': 'web', 'engine': 'exa',
                      'max_results': CITY_REGULATION_MAX_RESULTS}],
            timeout=180, usage_ctx=usage_ctx)
    except Exception as error:
        return [], [f'تعذر البحث عن اشتراطات «{label}»: {error}']
    parsed = _parse_json_block(_response_text(res))
    urls = []
    for value in parsed.get('pdf_urls') or parsed.get('urls') or []:
        url = str(value or '').strip()
        if url and url not in urls:
            urls.append(url)
    return urls, []


def _safe_pdf_name(url, slug, index):
    base = os.path.basename(urlsplit(url).path or '') or ''
    base = _FILENAME_SAFE.sub('-', base).strip('-.') or f'{slug}-{index}.pdf'
    if not base.lower().endswith('.pdf'):
        base += '.pdf'
    return base[:96]


def _pdf_looks_like_regulations(data):
    """Reject government PDFs that are not regulation documents.

    Some hosts serve scanned/image PDFs whose text layer is empty; those pass
    on name hints so a genuine scanned لائحة is not dropped for lacking text.
    """
    try:
        import fitz
        doc = fitz.open(stream=data, filetype='pdf')
        try:
            text = ' '.join(
                doc[index].get_text() for index in range(min(3, len(doc))))
        finally:
            doc.close()
    except Exception:
        return False
    if not text.strip():
        return True
    return any(keyword in text for keyword in _REGULATION_KEYWORDS)


def download_city_regulation_pdfs(urls, slug, tier='search', cap=None):
    """Fetch bounded PDF bodies for official URLs into the city cache dir."""
    directory = city_docs_dir(slug)
    os.makedirs(directory, exist_ok=True)
    saved = []
    warnings = []
    sources = load_city_sources(slug)
    limit = cap or CITY_REGULATION_MAX_DOCS
    for index, url in enumerate(urls[:limit]):
        try:
            with requests.get(
                    url, timeout=CITY_REGULATION_TIMEOUT, stream=True,
                    headers={'User-Agent': 'Landloom-RegulationFetch/1.0'}) as resp:
                if resp.status_code != 200:
                    warnings.append(f'تعذر تنزيل ملف اشتراطات (HTTP {resp.status_code}): {url}')
                    continue
                # A redirect may leave the approved host — re-check the final URL.
                if not is_official_regulation_url(resp.url or url):
                    warnings.append(
                        f'تم رفض ملف اشتراطات لأن رابطه النهائي ليس حكوميًا: '
                        f'{resp.url or url}')
                    continue
                buffer = io.BytesIO()
                for chunk in resp.iter_content(65536):
                    buffer.write(chunk)
                    if buffer.tell() > CITY_REGULATION_MAX_BYTES:
                        buffer = None
                        break
                if buffer is None:
                    warnings.append(f'ملف اشتراطات أكبر من الحد المسموح فتم تخطيه: {url}')
                    continue
                data = buffer.getvalue()
                final_url = resp.url or url
        except Exception as error:
            warnings.append(f'تعذر تنزيل ملف اشتراطات: {error}')
            continue
        if not data.startswith(b'%PDF'):
            warnings.append(f'الرابط لا يشير إلى ملف PDF صالح فتم تخطيه: {url}')
            continue
        if not _pdf_looks_like_regulations(data):
            warnings.append(
                f'الملف الحكومي ليس مستند اشتراطات فتم تخطيه: {url}')
            continue
        filename = _safe_pdf_name(url, slug, index + 1)
        path = os.path.join(directory, filename)
        try:
            with open(path, 'wb') as handle:
                handle.write(data)
        except OSError as error:
            warnings.append(f'تعذر حفظ ملف الاشتراطات: {error}')
            continue
        import hashlib
        sources[filename] = {
            'url': url,
            'final_url': final_url,
            'host': urlsplit(final_url).hostname or '',
            'city': slug,
            'tier': tier,
            'sha256': hashlib.sha256(data).hexdigest(),
            'size_bytes': len(data),
            'fetched_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        saved.append(path)
    if sources:
        _save_city_sources(slug, sources)
    return saved, warnings


def ensure_city_regulation_paths(slug, city, chat_fn=None, usage_ctx=None):
    """(paths, warnings) — cached city PDFs or a fresh official-source fetch.

    Never returns another city's documents: an empty list means no verified
    regulations exist for this city and the caller must say so."""
    cached = cached_city_pdf_paths(slug)
    if cached:
        return cached, []
    label = city or slug
    if not CITY_REGULATION_FETCH:
        return [], [
            f'لا توجد اشتراطات موثقة لمدينة «{label}» والجلب التلقائي معطل '
            '(CITY_REGULATION_FETCH=0).']
    registry_urls = []
    for url in (list(CITY_REGULATION_URLS.get(slug) or ())
                + list(NATIONAL_REGULATION_URLS)):
        if url not in registry_urls:
            registry_urls.append(url)
    warnings = []
    paths = []
    if registry_urls:
        paths, registry_warnings = download_city_regulation_pdfs(
            registry_urls, slug, tier='registry', cap=len(registry_urls))
        warnings.extend(registry_warnings)
        if paths:
            print(f'[CITY REGULATIONS] {slug}: fetched {len(paths)} '
                  'official registry document(s): '
                  + ', '.join(os.path.basename(path) for path in paths))
            return paths, warnings
        warnings.append(
            f'تعذر تنزيل مستندات الاشتراطات الرسمية المسجلة لمدينة «{label}»؛ '
            'سيتم تجربة البحث عن بديل رسمي.')
    if chat_fn is None:
        warnings.append('جلب اشتراطات المدينة غير متاح في هذا السياق.')
        return [], warnings
    hosts = resolve_city_amana_hosts(slug)
    urls, search_warnings = discover_city_regulation_urls(
        slug, label, chat_fn, usage_ctx=usage_ctx, hosts=hosts)
    warnings.extend(search_warnings)
    official = [url for url in urls if is_official_regulation_url(url)]
    if hosts:
        host_set = {host.lower() for host in hosts}
        official.sort(key=lambda url: 0 if (
            urlsplit(url).hostname or '').lower() in host_set else 1)
    dropped = len(urls) - len(official)
    if dropped:
        warnings.append(f'تم استبعاد {dropped} رابط اشتراطات من مصادر غير حكومية رسمية.')
    if not official:
        warnings.append(
            f'لم يُعثر على ملف اشتراطات رسمي لمدينة «{label}»؛ '
            'قيم الاشتراطات ستبقى مبنية على معرفة النموذج غير الموثقة.')
        return [], warnings
    paths, download_warnings = download_city_regulation_pdfs(
        official, slug, tier='search')
    warnings.extend(download_warnings)
    if not paths:
        warnings.append(
            f'تعذر تنزيل أي ملف اشتراطات لمدينة «{label}»؛ '
            'قيم الاشتراطات ستبقى مبنية على معرفة النموذج غير الموثقة.')
        return [], warnings
    print(f'[CITY REGULATIONS] {slug}: fetched {len(paths)} document(s): '
          + ', '.join(os.path.basename(path) for path in paths))
    return paths, warnings
