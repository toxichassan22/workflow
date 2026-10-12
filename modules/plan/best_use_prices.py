import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from best_use_contract import ProposalError, text, rounded, USE_TERMS, DIGITS, digest
from best_use_geometry import number


MIN_OBSERVATIONS = 3
MAX_AGE_DAYS = 180
MODE_TERMS = {'sale': r'للبيع|بيع|sale', 'rent': r'إيجار|ايجار|تأجير|rent|lease'}
UNIT_TERMS = {'sqm': r'للمتر|لكل متر مربع|(?:per|/)\s*(?:sqm|m2|m²|م²|م2)',
              'unit': r'للوحدة|per unit', 'room': r'للغرفة|per room'}
PERIOD_TERMS = {'year': r'سنوي|سنويا|السنة|سنة|annual|year',
                'month': r'شهري|الشهر|شهر|monthly|month', 'night': r'ليلة|ليلي|night'}
CURRENCY_TERMS = r'ريال\s+سعودي|SAR|Saudi riyal|ر\.\s*س'


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0
        self.published = None

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if tag == 'meta':
            values = dict(attrs)
            identity = values.get('property') or values.get('name') or values.get('itemprop')
            if identity in ('article:published_time', 'datePublished', 'datepublished'):
                value = values.get('content') or ''
                if re.match(r'^\d{4}-\d{2}-\d{2}', value):
                    self.published = value[:10]

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.skip = max(0, self.skip - 1)
        if tag in ('p', 'div', 'li', 'tr', 'h1', 'h2', 'br'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def result(self):
        return {'content': re.sub(r'[ \t]+', ' ', ' '.join(self.parts)), 'publishedAt': self.published}


def clean_url(value):
    try:
        parsed = urlsplit(str(value or '').strip())
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            return ''
        query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                 if not key.lower().startswith('utm_') and key.lower() not in {'gclid', 'fbclid'}]
        if parsed.path in ('', '/'):
            return ''
        return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, urlencode(query), ''))
    except ValueError:
        return ''


def normalize_text(value):
    return re.sub(r'\s+', ' ', str(value or '').translate(DIGITS)).strip()


def verify_observation(raw, pages, retrieved_at, today=None):
    if not isinstance(raw, dict):
        raise ProposalError('price_evidence_invalid')
    url = clean_url(raw.get('url'))
    page = next((page for page in pages if clean_url(page.get('url')) == url and url), None)
    excerpt = normalize_text(raw.get('excerpt'))
    if not page or not excerpt or excerpt not in normalize_text(page.get('content')):
        raise ProposalError('price_evidence_not_retrieved')
    if re.search(r'متوسط|يبدأ من|ابتداء|نطاق سعري|average|starting from|between', excerpt, re.I):
        raise ProposalError('price_not_individual_observation')
    use, mode = text(raw.get('use'), 40), text(raw.get('revenueMode'), 20)
    unit, period = text(raw.get('unit'), 20), text(raw.get('period'), 20)
    value = number(raw.get('value'))
    city, district = text(raw.get('city'), 150), text(raw.get('district'), 150)
    if use not in USE_TERMS or mode not in MODE_TERMS or unit not in UNIT_TERMS or value is None or value <= 0:
        raise ProposalError('price_dimensions_invalid')
    if raw.get('currency') != 'SAR' or not re.search(CURRENCY_TERMS, excerpt, re.I):
        raise ProposalError('price_currency_unproven')
    if not city or normalize_text(city) not in excerpt or (district and normalize_text(district) not in excerpt):
        raise ProposalError('price_geography_unproven')
    if not re.search(USE_TERMS[use], excerpt, re.I) or not re.search(MODE_TERMS[mode], excerpt, re.I):
        raise ProposalError('price_use_or_operation_unproven')
    other_mode = 'rent' if mode == 'sale' else 'sale'
    if re.search(MODE_TERMS[other_mode], excerpt, re.I):
        raise ProposalError('price_operation_ambiguous')
    if mode == 'rent' and (period not in PERIOD_TERMS or not re.search(PERIOD_TERMS[period], excerpt, re.I)):
        raise ProposalError('price_period_unproven')
    if mode == 'sale' and period != 'oneOff':
        raise ProposalError('price_period_invalid')
    number_matches = [match for match in re.finditer(r'(?<![\d.,])[\d]+(?:[,٬][\d]{3})*(?:[.٫][\d]+)?', excerpt)
                      if number(match.group(0)) == value]
    if not any(re.search(CURRENCY_TERMS, excerpt[match.end():match.end() + 25], re.I)
               and re.search(UNIT_TERMS[unit], excerpt[match.end():match.end() + 75], re.I)
               for match in number_matches):
        raise ProposalError('price_value_unit_binding_unproven')
    published = raw.get('publishedAt') or None
    if published:
        proven_date = page.get('publishedAt') == published or bool(re.search(
            r'(?:نشر|تاريخ الإعلان|published)\s*[:：]?\s*' + re.escape(str(published)), excerpt, re.I))
        if not proven_date:
            published = None
    today = today or date.fromisoformat(retrieved_at[:10])
    freshness = 'unknown'
    if published:
        try:
            age = (today - date.fromisoformat(str(published)[:10])).days
            freshness = 'fresh' if 0 <= age <= MAX_AGE_DAYS else 'stale'
        except ValueError:
            published = None
    property_id = text(raw.get('propertyId'), 150)
    found_ids = set(re.findall(r'(?:رقم الإعلان|رقم العقار|listing id|property id)\s*[:：]?\s*([\w/-]+)', excerpt, re.I))
    if property_id and (property_id not in found_ids or len(found_ids) != 1):
        property_id = ''
    entity = text(raw.get('entityName'), 200)
    named = re.search(r'(?:اسم المشروع|المشروع|project name|project)\s*[:：]\s*'
                      + re.escape(normalize_text(entity)) + r'(?=\s*[,،;.\n]|$)', excerpt, re.I) if entity else None
    if entity and not named:
        entity = ''
    identity = ('property:' + property_id if property_id else 'entity:' + normalize_text(entity).casefold()
                if entity else 'unidentified:' + digest({
                    'use': use, 'mode': mode, 'city': city, 'district': district,
                    'value': value, 'unit': unit, 'period': period, 'publishedAt': published}))
    return {'id': digest({'url': url, 'identity': identity})[:24], 'url': url, 'excerpt': text(raw.get('excerpt'), 5000),
            'use': use, 'revenueMode': mode, 'value': value, 'currency': 'SAR', 'unit': unit, 'period': period,
            'city': city, 'district': district, 'publishedAt': published, 'retrievedAt': retrieved_at,
            'freshnessStatus': freshness, 'observationKind': 'listing', 'propertyId': property_id,
            'identity': identity, 'entityName': entity,
            'independenceStatus': 'identified' if property_id or entity else 'unknown'}


def build_scan(uses, candidates, pages, retrieved_at, city, district, search_ran=True):
    if not search_ran:
        raise ProposalError('price_search_not_run')
    observations, rejected, seen = [], [], set()
    for raw in candidates[:80]:
        try:
            observation = verify_observation(raw, pages, retrieved_at)
            if observation['use'] not in uses:
                raise ProposalError('price_use_not_permitted')
            identity = tuple(observation[key] for key in ('identity', 'use', 'revenueMode', 'unit', 'period'))
            if identity not in seen:
                seen.add(identity)
                observations.append(observation)
        except ProposalError as error:
            rejected.append({'url': clean_url(raw.get('url')) if isinstance(raw, dict) else '', 'reason': str(error)})
    table = []
    for use in sorted(uses):
        entry = {'use': use, 'salePerSqm': None, 'rentPerSqmYear': None, 'currency': 'SAR',
                 'saleUnit': 'sqm', 'rentUnit': 'sqm', 'rentPeriod': 'year',
                 'city': city, 'district': district, 'priceStatus': 'missing', 'sources': [], 'metrics': {}}
        for mode, key, period in (('sale', 'salePerSqm', 'oneOff'), ('rent', 'rentPerSqmYear', 'year')):
            eligible = [item for item in observations if item['use'] == use and item['revenueMode'] == mode
                        and item['unit'] == 'sqm' and item['period'] == period and item['city'] == city
                        and item['district'] == district and item['freshnessStatus'] == 'fresh'
                        and item['independenceStatus'] == 'identified']
            metric = {'value': None, 'count': len(eligible), 'method': None, 'min': None, 'max': None,
                      'sourceIds': [item['id'] for item in eligible]}
            if len(eligible) >= MIN_OBSERVATIONS:
                values = [item['value'] for item in eligible]
                metric.update(value=rounded(sum(values) / len(values)), method='arithmetic_mean',
                              min=min(values), max=max(values))
                entry[key] = metric['value']
            entry['metrics'][mode] = metric
        entry['sources'] = [item for item in observations if item['use'] == use]
        entry['priceStatus'] = ('available' if entry['salePerSqm'] is not None or entry['rentPerSqmYear'] is not None else
                                'insufficient_observations' if entry['sources'] else 'missing')
        table.append(entry)
    return {'retrievedAt': retrieved_at, 'city': city, 'district': district, 'table': table,
            'observations': observations, 'rejectedEvidence': rejected, 'searchRan': search_ran,
            'status': 'partial' if any(row['priceStatus'] != 'available' for row in table) else 'complete',
            'minimumObservations': MIN_OBSERVATIONS, 'maxAgeDays': MAX_AGE_DAYS}


def revenue_potential(components, scan):
    sale, rent, issues, source_ids = 0.0, 0.0, [], set()
    modes = set()
    for row in components:
        mode = row.get('investmentModel')
        if mode == 'nonRevenue':
            continue
        mode = 'sale' if mode == 'sale' else 'rent' if mode == 'annualRent' else 'unsupported'
        modes.add(mode)
        evidence = next((item for item in scan.get('table') or [] if item['use'] == row.get('useType')), {})
        metric = (evidence.get('metrics') or {}).get(mode) or {}
        amount = number(row.get('revenueArea'))
        if mode == 'unsupported' or metric.get('value') is None or amount is None or not row.get('revenueAreaBasis'):
            issues.append({'component': row.get('name'), 'reason': 'insufficient_or_incompatible_price_or_area'})
            continue
        value = amount * metric['value']
        if mode == 'sale':
            sale += value
        else:
            rent += value
        source_ids.update(metric.get('sourceIds') or [])
    comparable = bool(modes) and len(modes) == 1 and not issues and 'unsupported' not in modes
    return {'metric': 'revenue_potential', 'currency': 'SAR',
            'saleTotal': rounded(sale) if 'sale' in modes and not issues else None,
            'annualRentTotal': rounded(rent) if 'rent' in modes and not issues else None,
            'revenueMode': next(iter(modes)) if comparable else None,
            'period': ('oneOff' if modes == {'sale'} else 'year') if comparable else None,
            'value': rounded(sale if modes == {'sale'} else rent) if comparable else None,
            'comparisonStatus': 'comparable' if comparable else 'insufficient_data' if issues else 'mixed_basis',
            'rank': None, 'issues': issues, 'sourceIds': sorted(source_ids),
            'areaStatus': 'planning_assumption', 'excludesCostsAndROI': True}


def evidence_current(scan, today=None):
    import db
    today = today or db._utcnow().date()
    by_id = {item.get('id'): item for item in scan.get('observations') or []}
    for row in scan.get('table') or []:
        for metric in (row.get('metrics') or {}).values():
            if metric.get('value') is None:
                continue
            ids = metric.get('sourceIds') or []
            if len(ids) < MIN_OBSERVATIONS:
                return False
            for source_id in ids:
                item = by_id.get(source_id) or {}
                try:
                    age = (today - date.fromisoformat(str(item.get('publishedAt'))[:10])).days
                except ValueError:
                    return False
                if not 0 <= age <= MAX_AGE_DAYS:
                    return False
    return True


def rank_concepts(concepts):
    groups = {}
    for item in concepts:
        metric = item['revenuePotential']
        if metric['comparisonStatus'] == 'comparable':
            groups.setdefault((metric['currency'], metric['revenueMode'], metric['period']), []).append(item)
    for basis, group in groups.items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda item: item['revenuePotential']['value'], reverse=True)
        last_value, rank = None, 0
        for index, item in enumerate(ordered, 1):
            value = item['revenuePotential']['value']
            if value != last_value:
                rank = index
            item['revenuePotential'].update(rank=rank, comparisonGroup=':'.join(basis))
            last_value = value
    return concepts
