"""Deterministic aqar.fm advertising sample for the market summary.

The summary researchers run provider web search, which never opens the city
listing pages. aqar is open to the job's browser and its cards carry the asked
price, the unit description and the district, so one deterministic read gives
the summary a real asking-price sample instead of a "could not read aqar" gap.
Sale and rent pages stay separate; every card is an advertisement, never a
registered transaction.
"""

import re
import time


_AQAR_BLOCK_START = '## AQAR_LISTINGS ##'
_AQAR_BLOCK_END = '## END AQAR_LISTINGS ##'
_AQAR_MAX_PAGES = 6
_AQAR_MAX_CARDS_PER_PAGE = 8
_AQAR_MAX_BLOCK_CARDS = 16
_AQAR_MIN_DISTRICT_CARDS = 3
_AQAR_RESIDENTIAL_TYPES = ('فلل', 'شقق')
_AQAR_COMMERCIAL_TYPES = ('محلات',)

_AQAR_CARD_JS = """
() => {
  const out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href') || '';
    if (!/-\\d{5,}(?:\\?.*)?$/.test(href)) continue;
    const text = (a.innerText || '').trim();
    if (!text.includes('ريال')) continue;
    const ps = [...a.querySelectorAll('p')]
      .map(p => (p.innerText || '').trim()).filter(Boolean);
    const priceIndex = ps.findIndex(
      t => /[\\d\\u0660-\\u0669][\\d,\\u0660-\\u0669]*\\s*\\u00a7?\\s*ريال/.test(t));
    if (priceIndex < 0) continue;
    const price = ps[priceIndex];
    const others = ps.filter((_, i) => i !== priceIndex);
    const short = others.filter(t => t.length <= 220);
    const locs = others.filter(t => /حي\\s+[^,،]+[,،]?\\s*جدة/.test(t));
    const loc = locs.length ? locs[locs.length - 1] : (short[short.length - 1] || '');
    const desc = short.length ? short[0] : '';
    const basis = price.includes('سنوي') ? 'سنوي'
      : (price.includes('شهري') ? 'شهري' : '');
    let url = href;
    try { url = new URL(href, location.origin).href; } catch (e) { url = href; }
    out.push({url, price, basis, desc, loc});
    if (out.length >= 60) break;
  }
  return out;
}
"""

_PRICE_RE = re.compile(r'([\d\u0660-\u0669][\d,\u0660-\u0669]*)\s*\u00a7\s*ريال')
_LOCATION_RE = re.compile(r'حي\s+([^,،]+)[,،]\s*جدة')


def _aqar_norm_digits(value):
    return str(value or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))


def _aqar_price_text(value):
    match = re.search(r'[\d\u0660-\u0669][\d,\u0660-\u0669]*', str(value or ''))
    return _aqar_norm_digits(match.group(0)) if match else ''


def _aqar_district(payload):
    district = str((payload or {}).get('district') or '').strip()
    return district[3:].strip() if district.startswith('حي ') else district


def _summary_aqar_selected(payload):
    try:
        profile = market_study.summary_activity_profile(payload)
    except Exception:
        return False
    return bool(set(profile.get('kinds') or set()) & {'residential', 'commercial'})


def _summary_aqar_pages(payload):
    """The listing pages this project's activities need, sale and rent kept apart."""
    try:
        profile = market_study.summary_activity_profile(payload)
        kinds = profile.get('source_kinds') or []
        operations = market_study._payload_operations(payload) or {'بيع', 'إيجار'}
        city = str((payload or {}).get('city') or '').strip()
    except Exception:
        return []
    wanted_types = []
    if 'residential' in (profile.get('kinds') or set()):
        wanted_types.extend(_AQAR_RESIDENTIAL_TYPES)
    if 'commercial' in (profile.get('kinds') or set()):
        wanted_types.extend(_AQAR_COMMERCIAL_TYPES)
    pages = []
    try:
        for url, label in market_study._listing_urls(kinds, operations, city):
            text = str(label or '')
            if not any(kind in text for kind in wanted_types):
                continue
            pages.append({'url': url, 'label': text})
            if len(pages) >= _AQAR_MAX_PAGES:
                break
    except Exception as exc:
        print(f'[MARKET SUMMARY] aqar listing urls failed: {exc}')
        return []
    return pages


def _aqar_cards_from_page(page):
    try:
        cards = page.evaluate(_AQAR_CARD_JS)
    except Exception:
        return []
    return cards if isinstance(cards, list) else []


def _aqar_cards_from_text(text, page_url=''):
    cards = []
    found = list(_PRICE_RE.finditer(str(text or '')))
    for index, match in enumerate(found):
        end = found[index + 1].start() if index + 1 < len(found) else len(text)
        segment = text[match.end():end]
        locations = list(_LOCATION_RE.finditer(segment))
        location = locations[-1] if locations else None
        description = segment[:location.start()] if location else segment
        cards.append({
            'url': page_url,
            'price': match.group(1),
            'basis': ('سنوي' if 'سنوي' in segment[:30]
                      else ('شهري' if 'شهري' in segment[:30] else '')),
            'desc': re.sub(r'\s+', ' ', description).strip()[:240],
            'loc': re.sub(r'\s+', ' ', location.group(0)).strip() if location else '',
        })
    return cards


def _aqar_cards(page, opened, page_url):
    page_cards = _aqar_cards_from_page(page) if page is not None else []
    if page_cards:
        return page_cards
    return _aqar_cards_from_text(
        (opened or {}).get('text') or '', page_url=page_url)


def _aqar_label_parts(label):
    text = str(label or '')
    kind = next((kind for kind in ('فلل', 'شقق', 'محلات', 'مكاتب', 'أدوار')
                 if kind in text), '')
    operation = 'بيع' if 'بيع' in text else ('إيجار' if 'إيجار' in text else '')
    return kind, operation


def _summary_aqar_evidence(payload, session, deadline=None):
    """Read the project's aqar listing pages into one evidence block."""
    if session is None or not _summary_aqar_selected(payload):
        return None
    pages = _summary_aqar_pages(payload)
    if not pages:
        return None
    district = _aqar_district(payload)
    readings = []
    for page_spec in pages:
        if deadline is not None and time.time() >= float(deadline):
            break
        opened = session.open_url(page_spec['url'])
        opened = opened if isinstance(opened, dict) else {}
        if opened.get('error'):
            print(f"[MARKET SUMMARY] aqar page failed {page_spec['url']}: "
                  f"{opened.get('error')}")
            continue
        page = getattr(session, '_page', None)
        cards = _aqar_cards(page, opened, page_spec['url'])
        if not cards:
            continue
        district_cards = [card for card in cards
                          if district and (
                              district in (card.get('loc') or '')
                              or district in (card.get('desc') or ''))]
        chosen = (district_cards
                  if len(district_cards) >= _AQAR_MIN_DISTRICT_CARDS
                  else cards)
        readings.append({
            'label': page_spec['label'],
            'url': page_spec['url'],
            'text': str(opened.get('text') or ''),
            'cards': chosen[:_AQAR_MAX_CARDS_PER_PAGE],
            'city_only': chosen is cards and bool(district),
        })
    if not readings:
        return None
    return {
        'readings': readings,
        'rows': sum(len(item['cards']) for item in readings),
        'block': _summary_aqar_block(readings, payload),
    }


def _summary_aqar_block(readings, payload):
    city = str((payload or {}).get('city') or '').strip()
    district = _aqar_district(payload)
    lines = [
        _AQAR_BLOCK_START,
        'source: عقار aqar.fm',
        f'scope: {city}' + (f' — حي {district}' if district else ''),
        'note: إعلانات طلب معروضة (أسعار مطلوبة) وليست صفقات منفذة؛ '
        'السعر كما يظهر في الإعلان، والبيع والإيجار منفصلان.',
        'priority: هذه عينة الإعلانات الحتمية المعتمدة لمدينة المشروع — '
        'استخدم أسعارها وأحياءها في محاور العرض والطلب والتسعير.',
    ]
    index = 0
    for reading in readings:
        kind, operation = _aqar_label_parts(reading['label'])
        header = ' '.join(part for part in (kind, operation) if part) or reading['label']
        lines.append(f'\n[{header}] {reading["label"]}'
                     + (' — نتائج المدينة كاملة (إعلانات الحي غير كافية)'
                        if reading.get('city_only') else ''))
        for card in reading['cards']:
            index += 1
            if index > _AQAR_MAX_BLOCK_CARDS:
                break
            price = _aqar_price_text(card.get('price'))
            description = str(card.get('desc') or '').strip()
            location = str(card.get('loc') or '').strip()
            lines.append(f'{index}. price_sar: {price or "غير ظاهر"}')
            basis = str(card.get('basis') or '').strip()
            if basis:
                lines.append(f'   price_basis: {basis}')
            if description:
                lines.append(f'   description: {description[:180]}')
            if location:
                lines.append(f'   location: {location[:120]}')
            ad_url = str(card.get('url') or '').strip()
            if ad_url:
                lines.append(f'   ad_url: {ad_url}')
        lines.append(f'list_page: {reading["url"]}')
    lines.append(_AQAR_BLOCK_END)
    return '\n'.join(lines)


def _summary_aqar_evidence_into(payload, session, evidence_pool,
                                deadline=None, report=None):
    """Store the aqar advertising sample in the summary evidence pool."""
    if evidence_pool is None:
        return None
    report = report if callable(report) else (lambda *_args: None)
    report(22, 'جاري قراءة إعلانات عقار لمدينة المشروع...')
    result = _summary_aqar_evidence(payload, session, deadline=deadline)
    if not result:
        return None
    try:
        for reading in result['readings']:
            content = (result['block']
                       + '\n\n---\nنص صفحة عقار كما قُرئ:\n'
                       + reading.get('text', ''))[:12000]
            evidence_pool.add_page(
                reading['url'], title=reading['label'], content=content,
                final_url=reading['url'], via='aqar_sample')
    except Exception as exc:
        print(f'[MARKET SUMMARY] aqar evidence store failed: {exc}')
    payload['_summaryAqarSample'] = {'rows': result['rows'],
                                     'pages': len(result['readings'])}
    report(22, f"قرأت عقار {result['rows']} إعلانًا من "
               f"{len(result['readings'])} صفحة إعلانات.")
    return result
