# -*- coding: utf-8 -*-
"""Per-city regulation documents: normalize, discover, cache, and gate.

The verified ``rules/`` digest and the municipal اشتراطات*.pdf pair that ship
on the server cover Jeddah only. A croquis for any other declared city must
never read them — feeding Jeddah's tables into a Riyadh analysis once made
the model reconcile two different cities' codes inside one prompt.

For a non-local city this module either supplies that city's own official
regulation PDFs — discovered once through the OpenRouter ``web`` plugin
(Exa engine, which runs the search on OpenRouter's side for every request)
and cached under ``regulations/<city>/`` — or tells the caller plainly that
no verified regulations exist. In the second case the model's own knowledge
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


def discover_city_regulation_urls(slug, city, chat_fn, usage_ctx=None):
    """Direct official PDF URLs for a city's building regulations.

    The ``web`` plugin (Exa) executes the search on OpenRouter's side for
    every request — unlike the provider's native tool, which the model is
    free to skip. The model only picks which returned links are official
    PDFs; it never invents a URL."""
    label = city or slug
    system_prompt = (
        "أنت باحث وثائق حكومية سعودية. أعد JSON فقط بهذا الشكل: "
        "{\"pdf_urls\":[\"https://...\"]} — بدون أي نص أو شرح إضافي.")
    user_prompt = (
        f"ابحث في نتائج البحث المرفقة عن روابط مباشرة لملفات PDF رسمية تحتوي "
        f"أنظمة وضوابط البناء / الاشتراطات البلدية / المخطط المحلي الصادرة عن "
        f"أمانة {label} أو الجهة المختصة في مدينة {label} بالسعودية. "
        "اقبل الروابط من المواقع الحكومية الرسمية فقط (gov.sa أو موقع الأمانة). "
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


def download_city_regulation_pdfs(urls, slug):
    """Fetch bounded PDF bodies for official URLs into the city cache dir."""
    directory = city_docs_dir(slug)
    os.makedirs(directory, exist_ok=True)
    saved = []
    warnings = []
    sources = load_city_sources(slug)
    for index, url in enumerate(urls[:CITY_REGULATION_MAX_DOCS]):
        try:
            with requests.get(
                    url, timeout=CITY_REGULATION_TIMEOUT, stream=True,
                    headers={'User-Agent': 'Landloom-RegulationFetch/1.0'}) as resp:
                if resp.status_code != 200:
                    warnings.append(f'تعذر تنزيل ملف اشتراطات (HTTP {resp.status_code}): {url}')
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
        except Exception as error:
            warnings.append(f'تعذر تنزيل ملف اشتراطات: {error}')
            continue
        if not data.startswith(b'%PDF'):
            warnings.append(f'الرابط لا يشير إلى ملف PDF صالح فتم تخطيه: {url}')
            continue
        filename = _safe_pdf_name(url, slug, index + 1)
        path = os.path.join(directory, filename)
        try:
            with open(path, 'wb') as handle:
                handle.write(data)
        except OSError as error:
            warnings.append(f'تعذر حفظ ملف الاشتراطات: {error}')
            continue
        sources[filename] = {
            'url': url,
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
    if chat_fn is None:
        return [], ['جلب اشتراطات المدينة غير متاح في هذا السياق.']
    urls, warnings = discover_city_regulation_urls(
        slug, label, chat_fn, usage_ctx=usage_ctx)
    official = [url for url in urls if is_official_regulation_url(url)]
    dropped = len(urls) - len(official)
    if dropped:
        warnings.append(f'تم استبعاد {dropped} رابط اشتراطات من مصادر غير حكومية رسمية.')
    if not official:
        warnings.append(
            f'لم يُعثر على ملف اشتراطات رسمي لمدينة «{label}»؛ '
            'قيم الاشتراطات ستبقى مبنية على معرفة النموذج غير الموثقة.')
        return [], warnings
    paths, download_warnings = download_city_regulation_pdfs(official, slug)
    warnings.extend(download_warnings)
    if not paths:
        warnings.append(
            f'تعذر تنزيل أي ملف اشتراطات لمدينة «{label}»؛ '
            'قيم الاشتراطات ستبقى مبنية على معرفة النموذج غير الموثقة.')
        return [], warnings
    print(f'[CITY REGULATIONS] {slug}: fetched {len(paths)} document(s): '
          + ', '.join(os.path.basename(path) for path in paths))
    return paths, warnings
