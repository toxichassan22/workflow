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


def project_row(card, detail):
    price_from = detail.get('price_from')
    price_to = detail.get('price_to')
    if price_from is None:
        price_from = card.get('price_from')
        price_to = price_from
    area_from = detail.get('area_from')
    area_to = detail.get('area_to')
    url = card.get('url') or ''
    notes = 'نطاق الأسعار والمساحات من صفحة المشروع على عقار'
    if price_from is None:
        notes += '؛ لم تُظهر الصفحة نطاقًا سعريًا'
    if area_from is None:
        notes += '؛ لم تُظهر الصفحة مساحات الوحدات'
    flags = card.get('flags') or []
    return {
        'name': card.get('name') or '',
        'project_type': card.get('project_type') or '',
        'operation_type': card.get('operation') or '',
        'price_type': 'نطاق سعري' if price_from is not None else '',
        'price_value': '',
        'price_from': _display(price_from),
        'price_to': _display(price_to),
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
            'price_from': [url],
            'price_to': [url],
            'area_from': [url] if area_from is not None else [],
            'area_to': [url] if area_to is not None else [],
        },
    }


def scan(session, city, district='', pairs=(), limit=12,
         budget_seconds=90, progress=None):
    """Read the city's projects and complete up to ``limit`` of them.

    ``pairs`` are the requested (project_type, operation) Arabic pairs;
    an empty set reads every mapped project. A district scope keeps only
    cards whose own address names that district — never widened.
    """
    report = progress if callable(progress) else (lambda *_args: None)
    start = time.time()
    page = session.fetch_html(build_projects_url(city), timeout=45)
    html = (page or {}).get('html') or ''
    cards = parse_cards(html)
    report(24, f'قراءة مشاريع عقار — {len(cards)} مشروعًا في {city}...')
    wanted = {tuple(pair) for pair in pairs or []}
    wanted_district = _district_key(district) if district else ''
    picked = []
    for card in cards:
        if not card.get('project_type') or not card.get('operation'):
            continue
        if wanted and (card['project_type'], card['operation']) not in wanted:
            continue
        if wanted_district and _district_key(card.get('district')) != wanted_district:
            continue
        picked.append(card)
    rows = []
    limit_value = max(1, int(limit or 1))
    for card in picked[:limit_value]:
        if time.time() - start > float(budget_seconds or 90):
            break
        detail_page = session.open_url(card['url'])
        detail = parse_detail((detail_page or {}).get('text') or '')
        row = project_row(card, detail)
        if district:
            # The row must carry the client's own district text so the
            # downstream scope filter (exact folded match) accepts it.
            row['district'] = district
        rows.append(row)
        report(24, f'قراءة مشروع «{card["name"]}» من عقار '
                   f'({len(rows)} من {min(len(picked), limit_value)})...')
    return {
        'cards': len(cards),
        'matched': len(picked),
        'rows': rows,
        'error': str((page or {}).get('error') or ''),
    }
