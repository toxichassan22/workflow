"""Deterministic reader for aqar.fm's named real-estate projects.

Residential and commercial competitors are named projects, and aqar's
projects directory lists them with a start price and the project's own
address; each project page carries the full price and area ranges. The
directory is a bot-walled SPA, so it is read through our managed browser
with the desktop UA (never a plain HTTP call).
"""

import html as html_module
import re
import time
from urllib.parse import unquote, urljoin, urlsplit

import booking_search
from numeric_precision import format_precise_number

BASE = 'https://sa.aqar.fm'
PROJECTS_PATH = '/المشاريع-العقارية'
_PROJECT_PATH_RE = re.compile(r'^/المشاريع-العقارية/[^/]+/[^/]+/?$')
_ANCHOR_RE = re.compile(r'<a\b([^>]*)>(.*?)</a>', re.I | re.S)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_TAG_RE = re.compile(r'<[^>]+>')
_PRICE_RE = re.compile(r'يبدأ\s+من\s*([\d.,]+)\s*(ألف|مليون)?', re.I)
_AREA_RE = re.compile(
    r'المساحات\s*من\s*([\d.,]+)\s*م²\s*إلى\s*([\d.,]+)\s*م²', re.S)
_RANGE_PRICE_RE = re.compile(
    r'الأسعار\s*من\s*([\d.,]+)\s*إلى\s*([\d.,]+)', re.S)
_UNITS_RE = re.compile(r'الوحدات\s*(\d{1,6})')
_ADDRESS_RE = re.compile(r'(?:شارع[^،\n]*،\s*)?(حي\s+[^،\n]+)'
                         r'(?:\s*،\s*([^،\n]+))?')

# Client-selected property kinds → the words aqar prints in the card's own
# type line. A card that names no recognised category is kept (unknown), and a
# card that names a different category is dropped instead of being guessed.
_UNIT_TYPE_CATEGORY_TOKENS = {
    'استوديو': ('شقق', 'شقة', 'وحدات سكنية'),
    'شقة': ('شقق', 'شقة', 'وحدات سكنية'),
    'شقة دوبلكس': ('شقق', 'شقة', 'وحدات سكنية'),
    'بنتهاوس': ('شقق', 'شقة', 'وحدات سكنية'),
    'دور مستقل': ('أدوار', 'دور', 'شقق'),
    'ملحق سكني': ('أدوار', 'دور', 'شقق'),
    'فيلا مستقلة': ('فلل', 'فيلا', 'بيت'),
    'فيلا دوبلكس': ('فلل', 'فيلا', 'بيت'),
    'تاون هاوس': ('فلل', 'فيلا', 'بيت'),
    'توين هاوس': ('فلل', 'فيلا', 'بيت'),
    'قصر': ('فلل', 'فيلا', 'بيت'),
    'بيت شعبي / بيت عربي': ('فلل', 'فيلا', 'بيت'),
    'عمارة سكنية': ('شقق', 'شقة', 'عمار', 'وحدات سكنية'),
    'مجمع سكني': ('شقق', 'شقة', 'وحدات سكنية'),
    'سكن موظفين': ('شقق', 'شقة', 'وحدات سكنية'),
    'سكن عمال': ('شقق', 'شقة', 'وحدات سكنية'),
    'مكتب': ('مكاتب', 'مكتب'),
    'برج مكاتب': ('مكاتب', 'مكتب', 'برج'),
    'محل تجاري': ('محلات', 'محل'),
    'معرض تجاري': ('معارض', 'معرض', 'محلات', 'محل'),
    'مركز تجاري': ('محلات', 'محل', 'مركز تجاري'),
    'مستودع تجاري': ('مستودعات', 'مستودع'),
}
_ALL_UNIT_CATEGORY_TOKENS = {
    token for tokens in _UNIT_TYPE_CATEGORY_TOKENS.values()
    for token in tokens
}


def _selected_category_tokens(unit_types):
    tokens = set()
    for item in unit_types or []:
        tokens.update(_UNIT_TYPE_CATEGORY_TOKENS.get(
            _text(item), ()))
    return tokens


def _card_matches_unit_types(card, wanted_tokens):
    """True when the card names a selected kind, or names no recognised kind."""
    if not wanted_tokens:
        return True
    text = _text((card or {}).get('type_line'))
    if not text:
        return True
    stated = {token for token in _ALL_UNIT_CATEGORY_TOKENS if token in text}
    return not stated or bool(stated & wanted_tokens)


_FLAGS = {'مميز', 'متاح', 'على الخارطة', 'وحدات جاهزة', 'جديد', 'عرض خاص'}
_RESIDENTIAL_HINTS = ('شقق', 'شقة', 'فلل', 'فيلا', 'أدوار', 'دور', 'عمارات',
                      'عمارة', 'استوديو', 'منازل', 'سكني', 'وحدات سكنية')
_COMMERCIAL_HINTS = ('مكاتب', 'مكتب', 'محلات', 'محل', 'تجاري', 'معارض',
                     'معرض', 'مستودعات', 'مستودع')
_OPERATION_BY_HINT = (('للبيع', 'بيع'), ('للإيجار', 'إيجار'))


def build_projects_url(city):
    return f'{BASE}{PROJECTS_PATH}/' + str(city or '').strip()


def _text(value):
    value = _TAG_RE.sub(' ', str(value or ''))
    value = html_module.unescape(value).replace('\u00a0', ' ')
    return ' '.join(value.split())


def _lines(inner_html):
    text = _TAG_RE.sub('\n', str(inner_html or ''))
    text = html_module.unescape(text).replace('\u00a0', ' ')
    return [line.strip() for line in text.split('\n') if line.strip()]


def _normalize_digits(value):
    return str(value or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))


def _amount(raw, unit=''):
    text = _normalize_digits(raw).replace(',', '').replace('٬', '').strip()
    if not text:
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if unit == 'ألف':
        value *= 1000
    elif unit == 'مليون':
        value *= 1000000
    if value <= 0 or value > 1e12:
        return None
    return value


def _display(value):
    if value in (None, ''):
        return ''
    return format_precise_number(float(value), grouped=False)


def _type_and_operation(type_line):
    line = _text(type_line)
    project_type = ''
    if any(hint in line for hint in _RESIDENTIAL_HINTS):
        project_type = 'سكني'
    elif any(hint in line for hint in _COMMERCIAL_HINTS):
        project_type = 'تجاري'
    operation = ''
    for hint, value in _OPERATION_BY_HINT:
        if hint in line:
            operation = value
            break
    if not operation:
        if 'للبيع' in line:
            operation = 'بيع'
        elif 'للإيجار' in line:
            operation = 'إيجار'
    return project_type, operation


def _address(lines):
    for line in reversed(lines):
        if '،' not in line:
            continue
        parts = [part.strip() for part in line.split('،') if part.strip()]
        district = next((part.replace('حي ', '', 1) for part in parts
                         if part.startswith('حي ')), '')
        city = ''
        if district:
            index = next((i for i, part in enumerate(parts)
                          if part.startswith('حي ')), -1)
            if 0 <= index + 1 < len(parts):
                city = parts[index + 1]
        elif len(parts) >= 2:
            city = parts[-2]
        return district, city
    return '', ''


def _slug_text(segment):
    return _text(unquote(segment).replace('-', ' '))


def parse_cards(html):
    """Project cards from the projects directory page."""
    cards = []
    seen = set()
    for attrs, inner in _ANCHOR_RE.findall(str(html or '')):
        href_match = _HREF_RE.search(attrs)
        if not href_match:
            continue
        href = unquote(html_module.unescape(href_match.group(1))).strip()
        path = urlsplit(href).path
        if not _PROJECT_PATH_RE.match(path):
            continue
        url = urljoin(BASE, path)
        if url in seen:
            continue
        seen.add(url)
        lines = _lines(inner)
        rebuilt = ' '.join(lines)
        price_match = _PRICE_RE.search(rebuilt)
        if not price_match:
            continue
        price_line = next((index for index, line in enumerate(lines)
                           if 'يبدأ' in line), -1)
        if price_line < 0:
            continue
        name = ''
        for index in range(price_line - 1, -1, -1):
            line = lines[index]
            if (not line or line in _FLAGS
                    or 'للبيع' in line or 'للإيجار' in line):
                continue
            name = line
            break
        if not name:
            continue
        type_line = next((line for line in lines
                          if 'للبيع' in line or 'للإيجار' in line), '')
        project_type, operation = _type_and_operation(type_line)
        district, city = _address(lines)
        segments = [part for part in path.strip('/').split('/') if part]
        developer = _slug_text(segments[1]) if len(segments) > 1 else ''
        developer = re.sub(r'\s+\d+$', '', developer).strip()
        cards.append({
            'name': name,
            'url': url,
            'project_type': project_type,
            'operation': operation,
            'type_line': type_line,
            'price_from': _amount(price_match.group(1),
                                  price_match.group(2) or ''),
            'district': district,
            'city': city,
            'developer': developer,
            'flags': [line for line in lines if line in _FLAGS],
        })
    return cards


def parse_detail(text):
    """Price/area ranges and address from a project page's readable text."""
    cleaned = ' '.join(str(text or '').replace('\u00a0', ' ').split())
    areas = _AREA_RE.search(cleaned)
    prices = _RANGE_PRICE_RE.search(cleaned)
    units = _UNITS_RE.search(cleaned)
    address = _ADDRESS_RE.search(cleaned)
    district = ''
    city = ''
    if address:
        district = address.group(1).replace('حي ', '', 1).strip()
        city = (address.group(2) or '').strip()
    return {
        'area_from': _amount(areas.group(1)) if areas else None,
        'area_to': _amount(areas.group(2)) if areas else None,
        'price_from': _amount(prices.group(1)) if prices else None,
        'price_to': _amount(prices.group(2)) if prices else None,
        'units': int(_normalize_digits(units.group(1))) if units else None,
        'district': district,
        'city': city,
    }


def _district_key(value):
    return booking_search.normalize_label(
        str(value or '').replace('حي ', '', 1))


# Words that describe a unit or a building without naming the project. Two
# different projects both called «برج» are not the same competitor.
_GENERIC_PROJECT_TOKENS = {
    'مشروع', 'مشاريع', 'وحدات', 'وحدة', 'سكني', 'سكنية', 'تجاري', 'تجارية',
    'برج', 'بروج', 'مجمع', 'مجمعات', 'كمبوند', 'عمارة', 'عمارات',
    'شقة', 'شقق', 'فيلا', 'فلل', 'دور', 'أدوار', 'مكتب', 'مكاتب',
    'محل', 'محلات', 'معرض', 'معارض', 'مستودع', 'مستودعات', 'أرض', 'أراضي',
    'project', 'projects', 'tower', 'towers', 'residence', 'residences',
    'suites', 'apartments', 'the', 'and', 'of', 'by',
}


def project_name_tokens(value):
    """The words of a project name that actually identify it.

    The definite article is dropped before the generic words are checked, so
    «السكني» is the same descriptor as «سكني» and never identifies a project.
    """
    folded = booking_search.normalize_label(value)
    tokens = []
    for token in folded.split():
        if token.startswith('ال') and len(token) > 3:
            token = token[2:]
        if len(token) >= 3 and token not in _GENERIC_PROJECT_TOKENS:
            tokens.append(token)
    return tokens


def parse_listing_links(html):
    """Listing cards on a city page: the ad's own link and its card text.

    A named competitor that is one advertised unit (not a project in the
    directory) lives here; the card text names it, and the listing page behind
    the link carries its price and area.
    """
    links = []
    seen = set()
    for attrs, inner in _ANCHOR_RE.findall(str(html or '')):
        href_match = _HREF_RE.search(attrs)
        if not href_match:
            continue
        href = unquote(html_module.unescape(href_match.group(1))).strip()
        parts = urlsplit(href)
        if parts.netloc and 'aqar.fm' not in parts.netloc:
            continue
        path = parts.path
        if not path or _PROJECT_PATH_RE.match(path):
            continue
        text = _text(inner)[:300]
        if len(text) < 8:
            continue
        url = urljoin(BASE, path)
        if url in seen:
            continue
        seen.add(url)
        links.append({'url': url, 'text': text})
    return links


def match_listing_link(links, name, city=''):
    """The city listing whose own card names this typed competitor.

    A card always names the unit and its location, so a single distinctive
    word is never enough — «النخبة» is a district as often as a building. The
    row needs two distinctive words, all present in the card, and the closest
    card (the one with the least surrounding text) wins.
    """
    city_tokens = set(project_name_tokens(city))
    wanted = [token for token in project_name_tokens(name)
              if token not in city_tokens]
    if len(set(wanted)) < 2:
        return None
    best = None
    for link in links or []:
        if not isinstance(link, dict):
            continue
        folded = booking_search.normalize_label(link.get('text'))
        if not all(token in folded for token in wanted):
            continue
        score = len(folded)
        if best is None or score < best[0]:
            best = (score, link)
    return best[1] if best else None


def listing_page_names(title, text, name, city=''):
    """True when the opened page is the listing this row names."""
    city_tokens = set(project_name_tokens(city))
    wanted = [token for token in project_name_tokens(name)
              if token not in city_tokens]
    if not wanted:
        return False
    folded = booking_search.normalize_label(
        f'{title} {str(text or "")[:2000]}')
    return all(token in folded for token in wanted)


def match_project_link(links, name, city=''):
    """The directory entry whose own project name is this typed competitor.

    Aqar slugs carry the project's own name, so matching is on those words:
    every distinctive word of the typed name must appear, with the city and
    the generic property words («برج»، «شقق»، «مشروع»…) left out. A name with a
    single distinctive word matches only an entry whose own name has that one
    word too, so one shared word never claims a different project.
    """
    city_tokens = set(project_name_tokens(city))
    wanted = [token for token in project_name_tokens(name)
              if token not in city_tokens]
    if not wanted:
        return None
    wanted_set = set(wanted)
    best = None
    for link in links or []:
        if not isinstance(link, dict):
            continue
        have = {token for token in project_name_tokens(link.get('name'))
                if token not in city_tokens}
        if not have:
            continue
        if len(wanted_set) == 1:
            if have != wanted_set:
                continue
        elif not wanted_set <= have:
            continue
        # The closest entry wins: fewest extra words around the same name.
        score = len(have - wanted_set)
        if best is None or score < best[0]:
            best = (score, link)
    return best[1] if best else None


def price_fields(card, detail):
    """The project's price exactly as its own page states it.

    The directory card prints «يبدأ من …», which is a single starting number,
    not a spread. Reading it as a two-sided range put the same figure in both
    cells and made the table claim a range the page never showed; the project
    page's own «الأسعار من … إلى …» is the only real range.
    """
    detail_from = detail.get('price_from')
    detail_to = detail.get('price_to')
    if detail_from is not None and detail_to is not None:
        if detail_to != detail_from:
            return {'price_type': 'نطاق سعري', 'price_value': None,
                    'price_from': detail_from, 'price_to': detail_to}
        detail_to = None
    if detail_from is not None:
        return {'price_type': 'يبدأ من', 'price_value': detail_from,
                'price_from': None, 'price_to': None}
    card_from = card.get('price_from')
    if card_from is not None:
        return {'price_type': 'يبدأ من', 'price_value': card_from,
                'price_from': None, 'price_to': None}
    return {'price_type': '', 'price_value': None,
            'price_from': None, 'price_to': None}


def project_row(card, detail, offer_lang='ar'):
    price = price_fields(card, detail)
    area_from = detail.get('area_from')
    area_to = detail.get('area_to')
    url = card.get('url') or ''
    is_range = price['price_type'] == 'نطاق سعري'
    if offer_lang == 'en':
        if is_range:
            notes = 'Price range and unit areas from the project page on aqar'
        elif price['price_type']:
            notes = ('Starting price and unit areas from the project page on aqar')
        else:
            notes = 'The project page on aqar showed no price'
        if area_from is None:
            notes += '; the page showed no unit areas'
    else:
        if is_range:
            notes = 'نطاق الأسعار والمساحات من صفحة المشروع على عقار'
        elif price['price_type']:
            notes = 'سعر البداية والمساحات من صفحة المشروع على عقار'
        else:
            notes = 'لم تُظهر صفحة المشروع على عقار سعرًا'
        if area_from is None:
            notes += '؛ لم تُظهر الصفحة مساحات الوحدات'
    flags = card.get('flags') or []
    return {
        'name': card.get('name') or '',
        'project_type': card.get('project_type') or '',
        'operation_type': card.get('operation') or '',
        'price_type': price['price_type'],
        'price_value': _display(price['price_value']),
        'price_from': _display(price['price_from']),
        'price_to': _display(price['price_to']),
        'price_currency': 'SAR',
        'area_mode': 'range' if area_from is not None else '',
        'area_sqm': '',
        'area_from': _display(area_from),
        'area_to': _display(area_to),
        'district': card.get('district') or detail.get('district') or '',
        'city': card.get('city') or detail.get('city') or '',
        'status': 'على الخارطة' if 'على الخارطة' in flags else 'قائم',
        'source': 'عقار',
        'source_url': url,
        'source_urls': [url],
        'row_source': 'aqar',
        'verify_state': 'verified',
        'developer': card.get('developer') or '',
        'notes': notes,
        'field_sources': {
            'name': [url],
            'price_value': ([url] if price['price_value'] is not None else []),
            'price_from': ([url] if price['price_from'] is not None else []),
            'price_to': ([url] if price['price_to'] is not None else []),
            'area_from': [url] if area_from is not None else [],
            'area_to': [url] if area_to is not None else [],
        },
    }


def _project_slug_name(path):
    segments = [part for part in str(path or '').strip('/').split('/') if part]
    if len(segments) < 3:
        return ''
    return re.sub(r'\s+\d+$', '', _slug_text(segments[2])).strip()


def parse_project_links(html):
    """Every named project on the directory page: its URL and its own name.

    The card name depends on a price line being present, so a project listed
    without one used to disappear completely. Its URL slug carries the same
    name, which is all a per-name lookup needs.
    """
    links = []
    seen = set()
    for attrs, _inner in _ANCHOR_RE.findall(str(html or '')):
        href_match = _HREF_RE.search(attrs)
        if not href_match:
            continue
        href = unquote(html_module.unescape(href_match.group(1))).strip()
        path = urlsplit(href).path
        if not _PROJECT_PATH_RE.match(path):
            continue
        url = urljoin(BASE, path)
        if url in seen:
            continue
        name = _project_slug_name(path)
        if not name:
            continue
        seen.add(url)
        links.append({'url': url, 'name': name})
    return links


def _page_error(page):
    """The reason a fetched page is not evidence: transport, refusal or block.

    ``fetch_html`` already reports a refused status, but older session doubles
    and cached responses may only carry the status — a 403 block page used to
    parse as an empty directory with no error at all.
    """
    page = page if isinstance(page, dict) else {}
    error = str(page.get('error') or '').strip()
    if error:
        return error
    try:
        status = int(page.get('status') or 0)
    except (TypeError, ValueError):
        status = 0
    if status >= 400:
        return 'blocked' if status in (401, 403, 429) else f'http_{status}'
    html = str(page.get('html') or '')
    head = html[:8000]
    if ('You have been blocked' in head or 'تم حظرك' in head
            or 'Just a moment' in head or 'Checking your browser' in head):
        return 'blocked'
    return ''


def load_projects(session, city):
    """The city's project directory: named project links plus price cards."""
    url = build_projects_url(city)
    page = session.fetch_html(url, timeout=45)
    error = _page_error(page)
    if error:
        # One fresh navigation on the same host clears aqar's intermittent
        # cold-navigation refusal; a real block still comes back as an error.
        page = session.fetch_html(url, timeout=45)
        error = _page_error(page)
    html = (page or {}).get('html') or ''
    return {
        'links': parse_project_links(html) if not error else [],
        'cards': parse_cards(html) if not error else [],
        'error': error,
    }


def project_for_link(session, link, offer_lang='ar', cards=()):
    """Build a project row from its own page; None when the page is empty."""
    url = str((link or {}).get('url') or '').strip()
    if not url:
        return None
    opened = session.open_url(url)
    text = str((opened or {}).get('text') or '')
    if not text:
        return None
    card = next((item for item in cards or []
                 if str((item or {}).get('url') or '') == url), None)
    if card is None:
        card = {'name': str((link or {}).get('name') or ''), 'url': url,
                'project_type': '', 'operation': '', 'flags': []}
    return project_row(card, parse_detail(text), offer_lang=offer_lang)


def scan(session, city, district='', pairs=(), limit=12,
         budget_seconds=90, progress=None, offer_lang='ar', districts=(),
         unit_types=()):
    """Read the city's projects and complete up to ``limit`` of them.

    ``pairs`` are the requested (project_type, operation) Arabic pairs;
    an empty set reads every mapped project. ``unit_types`` narrows the cards
    to the property kinds the client picked: a card naming a different kind is
    dropped, one naming no recognised kind is kept. A district scope keeps
    only projects whose own address names one of the client's districts — the
    card's address when it prints one, otherwise the project page's — and is
    never widened to another district.
    """
    report = progress if callable(progress) else (lambda *_args: None)
    start = time.time()
    catalog = load_projects(session, city)
    cards = catalog['cards']
    report(24, f'قراءة مشاريع عقار — {len(cards)} مشروعًا في {city}...')
    wanted = {tuple(pair) for pair in pairs or []}
    scope_districts = []
    for item in list(districts or []) + [district]:
        text = str(item or '').strip()
        if text and text not in scope_districts:
            scope_districts.append(text)
    wanted_keys = {_district_key(item) for item in scope_districts if _district_key(item)}
    wanted_unit_tokens = _selected_category_tokens(unit_types)
    picked = []
    dropped_unit_types = 0
    for card in cards:
        if not card.get('project_type') or not card.get('operation'):
            continue
        if wanted and (card['project_type'], card['operation']) not in wanted:
            continue
        if not _card_matches_unit_types(card, wanted_unit_tokens):
            dropped_unit_types += 1
            continue
        card_district = _district_key(card.get('district'))
        # A district scope never widens. A card that names a different
        # district is dropped without a page read; one that names no district
        # is confirmed from the project's own address below, because the
        # directory card often prints only the city — dropping those cards
        # returned zero projects for every district scope.
        if wanted_keys and card_district and card_district not in wanted_keys:
            continue
        picked.append(card)
    rows = []
    limit_value = max(1, int(limit or 1))
    for card in picked:
        if len(rows) >= limit_value:
            break
        if time.time() - start > float(budget_seconds or 90):
            break
        detail_page = session.open_url(card['url'])
        detail = parse_detail((detail_page or {}).get('text') or '')
        found_district = (_district_key(card.get('district'))
                          or _district_key(detail.get('district')))
        if wanted_keys:
            if found_district not in wanted_keys:
                continue
        row = project_row(card, detail, offer_lang=offer_lang)
        if scope_districts:
            # The row must carry the client's own district text so the
            # downstream scope filter (exact folded match) accepts it.
            row['district'] = next(
                (text for text in scope_districts
                 if _district_key(text) == found_district),
                scope_districts[0])
        rows.append(row)
        report(24, f'قراءة مشروع «{card["name"]}» من عقار '
                   f'({len(rows)} من {min(len(picked), limit_value)})...')
    if dropped_unit_types:
        report(24, f'استُبعد {dropped_unit_types} مشروعًا من عقار لنوع عقار '
                   f'مختلف عن المختار...')
    return {
        'cards': len(cards),
        'matched': len(rows),
        'filtered_unit_types': dropped_unit_types,
        'rows': rows,
        'card_rows': cards,
        'project_links': catalog['links'],
        'error': catalog['error'],
    }
