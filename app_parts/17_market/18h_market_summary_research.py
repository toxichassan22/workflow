"""Parallel, evidence-first research and Argon synthesis for market summaries."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote


_SUMMARY_RESEARCH_GROUPS = (
    {
        'key': 'transactions_and_rents',
        'label': 'الصفقات والإيجارات والمؤشرات العقارية',
        'hosts': {'rega.gov.sa', 'sakani.sa', 'ejar.sa', 'rer.sa', 'moj.gov.sa',
                  'aqar.fm', 'bayut.sa', 'wasalt.sa', 'dealapp.sa'},
        'focus': ('REGA city indicators and transaction activity; Sakani detailed rental indicators; '
                  'Ejar and available official records; current residential, commercial and industrial '
                  'asking listings. Separate realized transaction values from advertised asking prices.'),
    },
    {
        'key': 'development_and_supply',
        'label': 'المعروض والمشروعات والتخطيط',
        'hosts': {'momah.gov.sa', 'balady.gov.sa', 'nhc.sa', 'sbc.gov.sa'},
        'focus': ('Current and pipeline supply, licensed off-plan projects, permits and planning, '
                  'official city/developer project announcements, delivery timing, and type/use where '
                  'published. Do not treat announcements as delivered stock.'),
    },
    {
        'key': 'hospitality_and_tourism',
        'label': 'السياحة والفنادق والضيافة',
        'hosts': {'mt.gov.sa', 'str.com', 'costar.com', 'gaca.gov.sa', 'booking.com'},
        'focus': ('Ministry of Tourism and GASTAT performance reports, visitor flows and seasonality, '
                  'airport passenger and flight movement, licensed establishments, rooms, occupancy, ADR and RevPAR when '
                  'published; city-level tourism events and hotel supply. Always use Booking.com for a '
                  'date-specific sample of currently advertised hotel and, when relevant to the selected '
                  'activity, serviced-apartment or short-stay apartment/villa prices. Keep accommodation '
                  'types separate; never present booking prices as annual ADR or long-term residential rent.'),
    },
    {
        'key': 'economy_commercial_industrial',
        'label': 'الاقتصاد والتجاري والصناعة واللوجستيات',
        'hosts': {'stats.gov.sa', 'open.data.gov.sa', 'sama.gov.sa', 'mc.gov.sa',
                  'mim.gov.sa', 'modon.gov.sa', 'ecza.gov.sa', 'mawani.gov.sa',
                  'mot.gov.sa'},
        'focus': ('Population, households, businesses and purchasing capacity; office and retail demand; '
                  'industrial licenses and activity, industrial cities, special economic zones, ports, '
                  'freight and transport links. Label every metric city, region or national.'),
    },
    {
        'key': 'professional_and_city_context',
        'label': 'التقارير المهنية والمصادر الرسمية المساندة',
        'hosts': set(),
        'focus': ('Use every remaining source category from the market source catalog, including official '
                  'project/developer/operator pages, Tadawul, CBRE, JLL, Knight Frank, Colliers, Savills, '
                  'ValuStrat, Deloitte, PwC, KPMG, EY, SPA, municipal pages and location services. Use '
                  'maps only for city context/accessibility, never as a price or transaction source.'),
    },
)

_SUMMARY_RESEARCH_MAX_STEPS = 1000
_SUMMARY_RESEARCH_SEARCH_BUDGET = 1000
# Source researchers return the complete evidence they opened. The aggregator
# handles synthesis separately; do not truncate source findings at a small cap.
_SUMMARY_RESEARCHER_MODEL = 'anthropic/claude-haiku-5.5'
_SUMMARY_RESEARCH_MAX_OUTPUT_TOKENS = 66000
_SUMMARY_AGGREGATOR_MAX_OUTPUT_TOKENS = 66000
_SUMMARY_AGGREGATOR_MODEL = (os.environ.get('SUMMARY_AGGREGATOR_MODEL') or 'anthropic/claude-sonnet-5.5').strip()
_SUMMARY_AGGREGATOR_REASONING_EFFORT = (os.environ.get('SUMMARY_AGGREGATOR_REASONING_EFFORT') or '').strip() or None
try:
    _SUMMARY_AGGREGATOR_TIMEOUT = max(60, int(os.environ.get('SUMMARY_AGGREGATOR_TIMEOUT') or 3600))
except (TypeError, ValueError):
    _SUMMARY_AGGREGATOR_TIMEOUT = 3600
_SUMMARY_RESEARCH_REQUIRED_URLS = {
    'rei.rega.gov.sa': [
        'https://rei.rega.gov.sa',
        'https://rei.rega.gov.sa/ar/advanced-search',
        'https://rei.rega.gov.sa/ar/advanced-search/deals',
        'https://rei.rega.gov.sa/ar/advanced-search/live',
        'https://rei.rega.gov.sa/ar/advanced-search/rental-market/detailed-indicator',
        'https://rei.rega.gov.sa/ar/advanced-search/rental-market/comparison',
        'https://rei.rega.gov.sa/ar/advanced-search/ads-supply-market',
    ],
    'sakani.sa': ['https://sakani.sa/reports-and-data'],
    'geo.stats.gov.sa': [
        'https://geo.stats.gov.sa/portal/apps/experiencebuilder/experience/?id=64be425670be40c5881b37ee7ee5cf17&page=Population',
        'https://geo.stats.gov.sa/portal/apps/experiencebuilder/experience/?id=814450be664242f0be3d6da1f906024f&page=Household',
    ],
    'gaca.gov.sa': [
        'https://www.gaca.gov.sa/ar/Open-Data/OpenDataLibrary',
        'https://gaca.gov.sa/en/Reports-Categories/Air-Traffic-Reports?pageIndex=0',
    ],
    'booking.com': ['https://www.booking.com/'],
}

_SUMMARY_RESEARCH_PROMPT_VERSIONS = {
    ('hospitality_and_tourism', 'gaca.gov.sa'): 4,
    ('hospitality_and_tourism', 'booking.com'): 4,
    ('transactions_and_rents', 'sakani.sa'): 4,
    ('economy_commercial_industrial', 'stats.gov.sa'): 4,
    ('economy_commercial_industrial', 'geo.stats.gov.sa'): 4,
}


def _summary_research_sources_by_group():
    lines = [line for tier_lines in market_study.SOURCE_PRIORITY.values()
             for line in tier_lines]
    for source_lines in market_study.TYPE_SOURCE_PRIORITY.values():
        lines.extend(source_lines)
    domains = sorted({market_study._source_host(url)
                      for line in lines
                      for url in market_study._catalog_urls(line)
                      if market_study._source_host(url)})
    result = {item['key']: [] for item in _SUMMARY_RESEARCH_GROUPS}
    for host in domains:
        registrable = market_study._registrable_host(host)
        targets = [item for item in _SUMMARY_RESEARCH_GROUPS[:-1]
                   if host in item['hosts'] or registrable in item['hosts']]
        if not targets:
            targets = [_SUMMARY_RESEARCH_GROUPS[-1]]
        for target in targets:
            result[target['key']].append(host)
    # These sites are required by the owner even if a future catalog edit
    # temporarily omits a deep link for them.
    result['transactions_and_rents'] = sorted(set(
        result['transactions_and_rents'] + ['rei.rega.gov.sa', 'sakani.sa', 'ejar.sa']))
    result['development_and_supply'] = sorted(set(
        result['development_and_supply'] + ['red.rega.gov.sa', 'nhc.sa', 'momah.gov.sa']))
    result['hospitality_and_tourism'] = sorted(set(
        result['hospitality_and_tourism'] +
        ['mt.gov.sa', 'stats.gov.sa', 'gaca.gov.sa', 'booking.com']))
    result['economy_commercial_industrial'] = sorted(set(
        result['economy_commercial_industrial'] +
        ['stats.gov.sa', 'geo.stats.gov.sa', 'open.data.gov.sa']))
    return result


def _summary_research_catalog_urls_by_host():
    lines = [line for tier_lines in market_study.SOURCE_PRIORITY.values()
             for line in tier_lines]
    for source_lines in market_study.TYPE_SOURCE_PRIORITY.values():
        lines.extend(source_lines)
    urls_by_host = {}
    for line in lines:
        for url in market_study._catalog_urls(line):
            host = market_study._source_host(url)
            if host:
                urls_by_host.setdefault(host, set()).add(url)
    for host, required_urls in _SUMMARY_RESEARCH_REQUIRED_URLS.items():
        urls_by_host.setdefault(host, set()).update(required_urls)
    return {host: sorted(urls) for host, urls in urls_by_host.items()}


def _summary_research_activity_hosts(payload):
    """Catalog hosts allowed by the project's explicitly selected activities."""
    profile = market_study.summary_activity_profile(payload)
    kinds = profile.get('source_kinds') or []
    if not kinds:
        return set()
    hosts = set()
    for kind in kinds:
        for line in market_study.TYPE_SOURCE_PRIORITY.get(kind) or []:
            hosts.update(market_study._source_host(url)
                         for url in market_study._catalog_urls(line))
    # Census is cross-sector context for customer-facing activities, not an
    # invitation to add a residential-market section to other project types.
    if profile.get('kinds') and profile['kinds'].intersection(
            {'residential', 'commercial', 'hospitality', 'entertainment'}):
        hosts.add('geo.stats.gov.sa')
    if (profile.get('kinds') or set()).intersection({'hospitality', 'residential'}):
        hosts.add('booking.com')
    return {host for host in hosts if host}


def _summary_research_activity_signature(payload):
    profile = market_study.summary_activity_profile(payload)
    if not profile.get('activities'):
        return ''
    return json.dumps({
        'activities': profile.get('activities') or [],
        'sourceKinds': profile.get('source_kinds') or [],
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _summary_research_prompt(payload, group, hosts, city, district='',
                             offer_lang='ar'):
    requested_sites = '\n'.join(f'- {host}' for host in hosts) or 'ابحث في المصادر المهنية والرسمية المساندة.'
    catalog_urls = sorted({url for host in hosts
                           for url in _summary_research_catalog_urls_by_host().get(host, [])})
    if 'rei.rega.gov.sa' in hosts and city:
        city_url = 'https://rei.rega.gov.sa/ar/cities/' + quote(str(city).strip())
        if city_url not in catalog_urls:
            catalog_urls.append(city_url)
            catalog_urls.sort()
    requested_pages = ('\nالروابط المحددة في قائمة مصادر دراسة السوق لهذا الموقع؛ افتح كل رابط منها '
                       'وابحث في البيانات المرتبطة بمهمتك داخل كل صفحة:\n'
                       + '\n'.join(f'- {url}' for url in catalog_urls) + '\n'
                       if catalog_urls else '')
    site_queries = '، '.join(f'site:{host}' for host in hosts)
    place = f'حي {district}، مدينة {city}' if district else f'مدينة {city} كاملة'
    bounds = ((payload or {}).get('summaryPeriodBounds')
              or (payload or {}).get('dataPeriodBounds') or {})
    period_from = str(bounds.get('from') or '').strip() if isinstance(bounds, dict) else ''
    period_to = str(bounds.get('to') or '').strip() if isinstance(bounds, dict) else ''
    if offer_lang == 'en':
        period_rules = (
            f'Required data period: {period_from} through {period_to}. '
            'Search and apply source filters for these dates. For every result, record the actual period '
            'shown by the source. If the source only exposes a different or default period, label it as '
            'context and report the requested-period gap; never present it as covering this period. '
            'Current asking listings are access-date snapshots, not completed historical transactions.\n'
            if period_from or period_to else
            'No bounded data period was supplied. Record each source’s actual period and do not imply '
            'that its latest result covers a specific historical window.\n')
    else:
        period_rules = (
            f'فترة البيانات المطلوبة إلزاميًا: من {period_from or "غير محدد"} إلى {period_to or "غير محدد"}. '
            'أدخل التاريخين في فلاتر المصدر إن كانت متاحة، وسجّل الفترة الفعلية التي يعرضها المصدر لكل نتيجة. '
            'إذا لم يعرض المصدر إلا فترة مختلفة أو افتراضية، فاعرضها كسياق مؤرخ وسجّل فجوة الفترة المطلوبة؛ '
            'لا تنسبها إلى الفترة المطلوبة. إعلانات الطلب الحالية لقطة بتاريخ الوصول وليست صفقات تاريخية منفذة.\n'
            if period_from or period_to else
            'لم تُحدد فترة بيانات مقيدة. سجّل الفترة الفعلية لكل مصدر، ولا توحِ بأن أحدث نتيجة تغطي فترة '
            'تاريخية بعينها.\n')
    activity_profile = market_study.summary_activity_profile(payload)
    transaction_detail_rules = ''
    selected_kinds = activity_profile.get('kinds') or set()
    if (group.get('key') == 'transactions_and_rents'
            and selected_kinds.intersection({'residential', 'commercial'})):
        if offer_lang == 'en':
            bedroom_axis = (
                ' and by apartment bedroom count (studio, 1, 2, 3, 4, and 5+ bedrooms)'
                if 'residential' in selected_kinds else '')
            transaction_detail_rules = (
                'For selected residential or commercial activities, exhaust every available transaction '
                'breakdown in the assigned source, not only its headline total. For completed sales, capture '
                'count, total value, arithmetic mean price, highest observed price, and price per sqm when '
                'published, split by property type' + bedroom_axis +
                ' whenever the source exposes those dimensions. Return a separate finding for each '
                'metric and category and record the exact city/district, requested and actual period, record '
                'count, and whether the source exposed all matching records or only a paginated/sample view. '
                'Never calculate a city-wide total from a partial page, and never substitute asking listings '
                'for completed transactions. Record missing fields and access barriers only in coverage and '
                'coverage_gaps for internal evidence tracking; omit those absent categories from the final '
                'user-facing analysis.\n')
        else:
            bedroom_axis = (
                ' وعدد غرف نوم الشقة (استوديو، غرفة، غرفتان، 3، 4، و5 فأكثر)'
                if 'residential' in selected_kinds else '')
            transaction_detail_rules = (
                'للأنشطة السكنية أو التجارية المختارة، استنفد كل تقسيم للصفقات يعرضه المصدر الموكّل، ولا '
                'تكتفِ برقم إجمالي العنوان. في الصفقات المنفذة استخرج العدد والقيمة الإجمالية والمتوسط الحسابي '
                'للسعر وأعلى سعر مرصود وسعر المتر المربع عند نشره، وافصل حسب نوع العقار' + bedroom_axis +
                ' متى عرض المصدر هذا التقسيم. أعد نتيجة مستقلة لكل '
                'مقياس وفئة، وسجّل المدينة/الحي والفترة المطلوبة والفعلية وعدد السجلات، وهل أتاح المصدر جميع '
                'السجلات المطابقة أم صفحة أو عينة فقط. لا تحسب إجماليًا للمدينة من صفحة جزئية، ولا تستبدل '
                'الإعلانات بطلبات البيع محل الصفقات المنفذة. إذا لم يعرض المصدر التقسيم أو كان خلف نفاذ، '
                'سجّل الحقول غير المنشورة وحاجز الوصول في coverage وcoverage_gaps للتتبع الداخلي فقط؛ '
                'واحذف الفئات الغائبة من التحليل النهائي الموجه للمستخدم.\n')
    listing_urls = []
    activity_profile = market_study.summary_activity_profile(payload)
    if any(market_study._registrable_host(host) == 'aqar.fm' for host in hosts):
        listing_kinds = activity_profile.get('source_kinds') or []
        if listing_kinds:
            operations = market_study._payload_operations(payload) or {'بيع', 'إيجار'}
            listing_urls = [url for url, _label in market_study._listing_urls(
                listing_kinds, operations, city)]
    listings_block = ('\nروابط قوائم المدينة للمقارنة في الأسعار المطلوبة:\n'
                      + '\n'.join(f'- {url}' for url in listing_urls)
                      + '\nاستخدم فلتر الحي داخل الصفحة عند تحليل حي محدد.\n'
                      if listing_urls else '')
    scoped_population_rules = ''
    scoped_demographic_growth_rules = ''
    if ('residential' in selected_kinds and 'stats.gov.sa' in hosts):
        if offer_lang == 'en':
            scoped_demographic_growth_rules = (
                'For a selected residential activity, search GASTAT for the newest city-level time series '
                'and official projections on population and household growth, household formation, age '
                'structure, and housing units or permits where published. Record the year, geography, '
                'definition, and whether each value is observed or projected. Relate demand to verified '
                'residential supply, completions, and pipeline from the assigned official sources; do not '
                'derive housing demand from population growth alone or treat a national rate as a Jeddah rate.\n')
        else:
            scoped_demographic_growth_rules = (
                'للنشاط السكني المختار، ابحث في الهيئة العامة للإحصاء عن أحدث سلسلة زمنية وتوقعات رسمية '
                'لنمو سكان المدينة والأسر، وتكوّن الأسر، والتركيب العمري، والوحدات السكنية أو الرخص عند '
                'نشرها. سجّل السنة والنطاق الجغرافي وتعريف المؤشر وهل الرقم مرصود أم متوقع. اربط الطلب '
                'بالمعروض السكني المنفذ والمكتمل والمخطط الذي تثبته المصادر الرسمية الموكلة؛ لا تستنتج '
                'الطلب السكني من نمو السكان وحده ولا تنقل معدلًا وطنيًا إلى جدة.\n')
    if 'geo.stats.gov.sa' in hosts:
        summary_scope = market_study.normalize_summary_scope(
            (payload or {}).get('summaryScope'), (payload or {}).get('city'))
        city_scope = next((item for item in summary_scope['cities']
                           if item.get('name') == city), {})
        districts = city_scope.get('districts') or []
        districts_text = '، '.join(districts) if districts else 'لا توجد أحياء محددة'
        if offer_lang == 'en':
            scoped_population_rules = (
                'Open the official Saudi Census 2022 population and household maps listed above. '
                f'Report {city} and, when available at the map resolution, each selected district: '
                f'{districts_text}. Capture population, households, average household size, and '
                'occupied housing units where published. State the census year (2022) and the exact '
                'geographic resolution. Do not substitute regional or city totals for district values; '
                'mark unavailable when the official map does not expose the requested geography.\n')
        else:
            scoped_population_rules = (
                'افتح خريطتي تعداد السعودية 2022 الرسميتين للسكان والأسر الواردتين أعلاه، وافحص '
                f'مدينة {city} وكل حي محدد إذا كان متاحًا بمستوى الخريطة: {districts_text}. '
                'استخرج عدد السكان والأسر ومتوسط حجم الأسرة والمساكن المشغولة حيث تنشرها الخريطة. '
                'اذكر سنة التعداد 2022 والدقة الجغرافية الفعلية. لا تستبدل رقم المنطقة أو المدينة '
                'برقم الحي؛ سجّل عدم التوفر إذا لم تعرض الخريطة ذلك النطاق.\n')
    sakani_rules = ''
    if 'sakani.sa' in hosts and selected_kinds.intersection(
            {'residential', 'commercial'}):
        if offer_lang == 'en':
            sakani_rules = (
                'Treat Sakani reports and data as a required primary source. Open every assigned report/data '
                'page, inspect its tables and controls, select the requested city, district, period, property '
                'use and transaction/rent type, and apply filters. For commercial activity, inspect the '
                'commercial-unit rental tables explicitly; for residential activity, inspect residential '
                'unit and bedroom breakdowns where offered. Capture all visible matching rows, pagination, '
                'totals, averages, maxima, and record counts.\n')
        else:
            sakani_rules = (
                'منصة سكني مصدر أساسي إلزامي لهذه الدراسة. افتح كل صفحة تقارير وبيانات موكلة، وافحص '
                'الجداول وعناصر التصفية، وحدد المدينة والحي والفترة ونوع الاستخدام ونوع العملية ثم طبّق '
                'الفلاتر. في النشاط التجاري افحص جداول إيجار الوحدات التجارية تحديدًا؛ وفي السكني افحص '
                'تقسيم الوحدات السكنية وغرف النوم حيث يظهر. اجمع كل الصفوف المطابقة الظاهرة وصفحاتها '
                'وإجمالياتها ومتوسطاتها وأعلى قيمها وأعداد سجلاتها.\n')
    scoped_aviation_rules = ''
    if 'gaca.gov.sa' in hosts:
        if offer_lang == 'en':
            scoped_aviation_rules = (
                'For the city airport, extract the latest official airport-level passenger totals and '
                'flight movements, arrivals/departures, and routes when published, preserving period '
                'and airport. Search the GACA air-traffic open-data library and reports above. These are '
                'airport/city indicators, never neighborhood counts. Report ticket bookings or tickets '
                'sold only when an official source explicitly publishes those counts; never infer them '
                'from passengers, flights, seats, schedules, or hotel bookings. If the requested period '
                'has no publication, give the latest older period only as labeled context and record the gap.\n')
        else:
            scoped_aviation_rules = (
                f'ابحث عن أحدث بيانات رسمية لمطار مدينة {city} في مكتبة بيانات وتقارير الحركة الجوية '
                'للهيئة أعلاه: أعداد المسافرين وحركات الرحلات والقدوم والمغادرة والمسارات عند نشرها، '
                'مع تثبيت اسم المطار والفترة. هذه مؤشرات للمطار والمدينة وليست أعدادًا للأحياء. لا تذكر '
                'حجوزات أو تذاكر مباعة إلا إذا نشر مصدر رسمي عددها صراحة؛ لا تستنتجها من المسافرين أو '
                'الرحلات أو المقاعد أو الجداول أو حجوزات الفنادق. إذا لم تنشر بيانات للفترة المطلوبة، '
                'اعرض أحدث فترة أقدم كسياق مؤرخ وسجّل فجوة الفترة المطلوبة.\n')
    booking_price_rules = ''
    if 'booking.com' in hosts:
        has_hospitality = 'hospitality' in selected_kinds
        has_residential = 'residential' in selected_kinds
        if has_hospitality and has_residential:
            booking_target_en = ('hotels plus separate samples of serviced apartments and bookable '
                                'short-stay apartments/villas')
            booking_target_ar = ('الفنادق، مع عينات منفصلة للشقق المخدومة والشقق/الفلل '
                                'المعروضة للإقامة القصيرة')
        elif has_residential:
            booking_target_en = 'bookable serviced apartments and short-stay apartments/villas'
            booking_target_ar = 'الشقق المخدومة والشقق/الفلل المعروضة للإقامة القصيرة'
        else:
            booking_target_en = 'hotels'
            booking_target_ar = 'الفنادق'
        today = market_study.date.today()
        check_in = market_study.date.fromordinal(today.toordinal() + 14)
        check_out = market_study.date.fromordinal(check_in.toordinal() + 2)
        if offer_lang == 'en':
            booking_price_rules = (
                'Booking.com research is mandatory when hospitality or residential is selected, even when official '
                'operating reports are available; official indicators and booking observations answer different '
                'questions and must both be reported separately. These are current advertised rates, not official '
                'operating data. Search the exact same stay '
                f'for every property: check-in {check_in.isoformat()}, check-out {check_out.isoformat()}, one room, '
                'two adults, no children, and SAR display currency. Target five comparable properties for each '
                f'applicable type ({booking_target_en}) in this assigned city or '
                'district; calculate an arithmetic mean only from at least three comparable available properties '
                'in the same geographic scope and, when shown, the same star class. Keep room type and visible '
                'meal/cancellation terms comparable; prefer a standard double/twin room and do not mix suites, '
                'serviced apartments, or family rooms into that sample. Capture property name, exact booking URL, displayed total, '
                'nights, normalized SAR per room per night (divide the observed two-night total by two), taxes and '
                'included services, star class, and the source publication/data date when available. If the page '
                'shows a non-SAR price, convert it to SAR using a verified rate for the source data date; keep the '
                'original amount and conversion rate in internal evidence fields only. Do not mix dates, currencies, star classes, room '
                'types, or materially different terms. Keep each applicable accommodation type in its own '
                'comparable sample; never mix hotels, serviced apartments, apartments, or villas with one another '
                'or with sale/annual-rent evidence. If fewer than three comparable rates are visible, report the '
                'individual observations and sample size without an average. Call a computed result the approximate '
                'average advertised room rate for this Booking.com sample and exact stay dates; never call it ADR, '
                'an annual average, a historical rate, or the market standard.\n')
        else:
            booking_price_rules = (
                'استخدام Booking.com إلزامي عند اختيار نشاط فندقي أو سكني حتى عند توفر التقارير الرسمية؛ فالمؤشرات '
                'التشغيلية الرسمية وأسعار الحجز تقيسان أمرين مختلفين ويجب عرضهما منفصلين. هذه أسعار طلب '
                'معروضة حاليًا وليست بيانات تشغيل رسمية. ابحث عن الإقامة نفسها لكل منشأة: '
                f'الدخول {check_in.isoformat()} والخروج {check_out.isoformat()}، غرفة واحدة، بالغان، دون أطفال، '
                'والعملة المطلوبة ريال سعودي. استهدف خمسة عقارات قابلة للمقارنة لكل نوع مناسب '
                f'({booking_target_ar}) داخل المدينة أو الحي المكلّف؛ لا تخلط أنواع الإقامة ببعضها أو بصفقات البيع '
                'والإيجار السكني السنوي. إذا عرض الموقع السعر بعملة أخرى فحوّله إلى الريال بسعر صرف موثق '
                'لتاريخ البيانات، واحتفظ بالعملة الأصلية وسعر التحويل في حقول الدليل الداخلية فقط. ولا تحسب متوسطًا '
                'حسابيًا إلا من ثلاث منشآت متاحة قابلة للمقارنة على الأقل ضمن النطاق الجغرافي نفسه، ومن فئة النجوم '
                'نفسها متى ظهرت. اعتمد غرفة قياسية مزدوجة/توأم، ولا تخلط الأجنحة أو الشقق المخدومة أو الغرف '
                'العائلية في العينة. وحّد شروط الوجبات والإلغاء الظاهرة قدر الإمكان. سجّل اسم الفندق ورابط '
                'الحجز المحدد والإجمالي المعروض وعدد الليالي وسعر الغرفة للّيلة بعد قسمة إجمالي الليلتين المرصود '
                'على اثنتين والضرائب والخدمات المشمولة وفئة النجوم وتاريخ نشر أو بيانات المصدر إن توفر. لا تخلط التواريخ أو العملات أو '
                'فئات النجوم أو أنواع الغرف أو الشروط المختلفة جوهريًا. إذا قلّت الأسعار القابلة للمقارنة عن ثلاثة، '
                'اعرض الأسعار الفردية وحجم العينة دون متوسط. سمِّ الناتج «متوسطًا حسابيًا تقريبيًا لأسعار الغرف المعروضة '
                'في عينة Booking.com لتواريخ الإقامة المحددة»؛ لا تسمّه ADR أو متوسطًا سنويًا أو تاريخيًا أو سعرًا '
                'معياريًا للسوق. لا تكتب كلمة «وسيط» في أي نص ظاهر للمستخدم؛ استخدم «متوسطًا حسابيًا» فقط '
                'عندما يكون المقياس متوسطًا حسابيًا فعلًا، وأسقط أي قيمة منشورة بمقياس مختلف بدل تسميتها متوسطًا.\n')
    return (
        f"أنت باحث متخصص في {group['label']} ضمن دراسة سوق سعودية مهنية. هذا بحث منفصل عن بقية الباحثين؛ "
        'قدّم أدلة خامًا دقيقة ومهيكلة، ولا تكتب دراسة سوق عامة.\n'
        + market_study._summary_activity_scope_block(payload, offer_lang)
        + f'النطاق الجغرافي الموكّل لهذا البحث فقط: {place}. لا تبحث في مدينة أو حي آخر.\n'
        + ('جميع القيم المالية في المخرجات تكون بالريال السعودي. إذا عرض المصدر مبلغًا بعملة أخرى، '
           'حوّله إلى SAR بمعدل صرف موثوق ومرتبط بتاريخ البيانات، وأضف original_value و'
           'original_currency وfx_rate_sar_per_unit إلى سجل الدليل الداخلي. إذا تعذر توثيق المعدل، '
           'لا تُخرج المبلغ. لا تكتب عملة أجنبية في أي قيمة معدّة للملخص.\n'
           if offer_lang != 'en' else
           'All monetary findings must be in Saudi riyals (SAR). Convert any source amount in another '
           'currency using a verified rate tied to the source data date, and add original_value, '
           'original_currency, and fx_rate_sar_per_unit to the internal finding. If the rate cannot be '
           'verified, omit the amount. Do not put a foreign currency in any summary-ready value.\n')
        + period_rules + transaction_detail_rules
        + 'نطاق المهمة: ' + group['focus'] + '\n'
        + scoped_population_rules + scoped_demographic_growth_rules
        + scoped_aviation_rules + sakani_rules + booking_price_rules
        + 'هذا الباحث مسؤول عن مصدر محدد؛ ابحث داخله أولًا وحاول الوصول إلى صفحة البيانات أو التقرير ذات الصلة، '
        'ولا تكتفِ بالصفحة الرئيسية. إذا لم يعرض المصدر بيانات لهذا المكان أو الفترة فسجّل فجوة تغطية.\n'
        'المصدر الموكّل لهذا الباحث:\n' + requested_sites + '\n'
        + requested_pages
        + listings_block
        + ('فتح الموقع أو الرابط وحده لا يُعد بحثًا مكتملًا. تفاعل فعليًا مع المصدر واجمع كل البيانات ذات الصلة '
           'بالمدينة/الحي والفترة والنشاط الموكّل لك: افتح كل صفحة محددة، افحص عناصرها، اكتب المدينة أو الحي '
           'والتاريخ ونوع المؤشر في الحقول، اختر القيم من القوائم، واضغط بحث/تطبيق. افحص كل التبويبات والجداول '
           'والرسوم، افتح التفاصيل، تنقّل بين الصفحات والنتائج، ووسّع الفلاتر ذات الصلة حتى تستنفد البيانات '
           'المتاحة للنطاق. استخدم click_element وtype_text مع submit=true وscroll_page وinspect_page؛ '
           'لا تكتفِ بالمقتطفات أو أول صفحة ولا تنتقِ رقمًا واحدًا إذا كان المصدر يعرض مؤشرات أخرى.\n'
           if os.environ.get('BROWSER_USE_LOCAL_TOOLS', '').strip() in ('1', 'true', 'yes') else
           'ابحث في المصادر الموكلة إليك واجمع كل البيانات والمؤشرات ذات الصلة بالمدينة/الحي والفترة والنشاط الموكّل لك. '
           'في كل استعلام بحث قيّد البحث بواحد من هذه النطاقات: ' + site_queries + '. '
           'استخرج أحدث المؤشرات والأرقام والصفقات المنشورة والروابط المحددة.\n')
        + 'سجّل كل المؤشرات والتقسيمات ذات الصلة، والفترة وعدد السجلات أو الصفحات التي ظهرت. إذا تعذّر '
        'استنفاد النتائج أو تصديرها، حدّد ما جُمِع وما بقي غير متاح بدل ادعاء اكتمال المصدر. '
        'في كل محرك بحث قيّد الاستعلام بواحد من هذه النطاقات: ' + site_queries + '. لا تدّعِ '
        'استخراج نتائج من لوحة لم تعرضها الصفحة فعلًا. ابدأ بالصفحات الحكومية والمصدر الأصلي، واستخدم مصدرًا '
        'مهنيًا أو إعلانًا فقط لقياس النوع الذي يتيحه.\n'
        + 'لكل دليل أعد: القيمة بعد تحويلها إلى الريال عند الحاجة، الوحدة، المدينة والحي أو المستوى الجغرافي، الفترة، تاريخ البيانات، '
        'اسم المصدر، رابط الصفحة المفتوحة المحددة، مستوى الموثوقية، وملاحظة المنهج/القيود. افصل الصفقة المنفذة '
        'عن سعر الطلب والإيجار المعلن، ولا تستنتج متوسطًا من عينة صغيرة. لا تستخدم معلومات من الذاكرة. إذا كانت '
        'صفحة تتطلب نفاذ أو لا تعرض نتائج أو بيانات حديثة، سجّل فجوة التغطية بوضوح.\n'
        + 'أرجع JSON فقط: {"group":"' + group['key'] + '","coverage":[{"url":"",'
        '"interaction_steps":[],"datasets_opened":[],"records_or_pages_seen":"",'
        '"completeness":"complete|partial|unavailable","gaps":""}],"findings":[{"metric":"","value":"",'
        '"unit":"","property_type":"","bedroom_count":"","sample_size":"",'
        '"city":"","district":"","period":"","data_date":"","original_value":"",'
        '"original_currency":"","fx_rate_sar_per_unit":"","source_name":"",'
        '"source_url":"","reliability":"","limitations":""}],"sources":[{"name":"","url":"",'
        '"data_date":"","reliability":"","note":""}],"coverage_gaps":[]}\n'
        + ("Write the JSON text values in English. Search around " + place + '.\n'
           if offer_lang == 'en' else '')
    )


def _run_summary_researcher(group, hosts, payload, city, district,
                            usage_ctx, deadline, offer_lang='ar',
                            cancel_event=None, on_event=None):
    worker_pool = _new_evidence_pool()
    shared_pages = (payload or {}).get('_summaryEvidencePages') or []
    if worker_pool is not None:
        for page in shared_pages:
            if not isinstance(page, dict) or not page.get('url'):
                continue
            if not _summary_source_url_allowed(page.get('url'), hosts):
                continue
            try:
                worker_pool.add_page(
                    page.get('url'), title=page.get('title') or '',
                    content=page.get('content') or '',
                    final_url=page.get('url'), via='job_evidence')
            except Exception:
                continue
    prompt = _summary_research_prompt(payload, group, hosts, city, district,
                                      offer_lang=offer_lang)
    use_local = os.environ.get('BROWSER_USE_LOCAL_TOOLS', '').strip() in ('1', 'true', 'yes')
    system_prompt = (
        'أنت باحث ويب تستخدم أدوات المتصفح المحلي. لا تخترع نتائج ولا تنهِ المهمة قبل فتح صفحات مصادر.'
        if use_local else
        'أنت باحث سوق تستخدم بحث الويب المباشر. استخرج أرقامًا وبيانات محددة من المصادر الموكلة إليك واذكر الروابط المحددة.'
    )
    browse_kwargs = {
        'model': _SUMMARY_RESEARCHER_MODEL,
        'evidence_pool': worker_pool,
        'deadline': deadline,
        'local_tools': use_local,
        'search_budget': _SUMMARY_RESEARCH_SEARCH_BUDGET,
        'max_steps': _SUMMARY_RESEARCH_MAX_STEPS,
        'max_tokens': _SUMMARY_RESEARCH_MAX_OUTPUT_TOKENS,
        'reasoning_effort': 'low',
        'cancel_event': cancel_event,
        'research_mode': True,
        'allowed_hosts': hosts,
        'on_event': on_event,
    }
    if use_local:
        browse_kwargs['search_provider'] = 'searxng'
    else:
        browse_kwargs['plugins'] = [{'id': 'web', 'max_results': 5}]
    result = _browse_agent_call(
        system_prompt, prompt, dict(usage_ctx or {}), **browse_kwargs)
    pages = worker_pool.pages() if worker_pool is not None else []
    parsed, parse_error = _parse_market_model_json(result)
    parsed, filtered_sources = _summary_restrict_research_result(parsed, hosts)
    pages = [page for page in pages if _summary_source_url_allowed(
        page.get('url'), hosts)]
    searched = _market_search_ran(result) or bool(pages)
    return {
        'key': group['key'], 'label': group['label'], 'city': city,
        'district': district, 'hosts': list(hosts), 'result': result,
        'parsed': parsed, 'parse_error': parse_error, 'pages': pages,
        'filtered_sources': filtered_sources, 'searched': searched,
    }


def _summary_research_task_id(group, hosts, city, district,
                              activity_signature=None):
    group_key = str(group.get('key') or '')
    host_names = sorted(str(host) for host in (hosts or []))
    task = [group_key, host_names, str(city or ''), str(district or '')]
    prompt_version = max(
        (_SUMMARY_RESEARCH_PROMPT_VERSIONS.get((group_key, host), 3)
         for host in host_names), default=3)
    if prompt_version > 1:
        task.append(f'prompt-v{prompt_version}')
    if activity_signature:
        task.append('activity-' + str(activity_signature))
    return json.dumps(task, ensure_ascii=False, separators=(',', ':'))


def _summary_research_checkpoint(outcomes, evidence_pool):
    """Keep completed researchers and bounded browser evidence for continuation."""
    researchers = {}
    for item in outcomes or []:
        if not isinstance(item, dict) or not item.get('searched'):
            continue
        result = item.get('result') if isinstance(item.get('result'), dict) else {}
        if result.get('error'):
            continue
        parsed = item.get('parsed')
        parsed = parsed if isinstance(parsed, dict) else {}
        citations = _market_citation_urls(result)
        researchers[_summary_research_task_id(
            {'key': item.get('key')}, item.get('hosts'), item.get('city'),
            item.get('district'), item.get('activitySignature'))] = {
                'key': item.get('key'), 'label': item.get('label'),
                'city': item.get('city'), 'district': item.get('district'),
                'hosts': list(item.get('hosts') or []), 'parsed': parsed,
                'activitySignature': item.get('activitySignature') or '',
                'rawOutput': _get_chat_response_text(result),
                'searched': True, 'citationUrls': citations,
            }
    return {
        'researchers': researchers,
        'evidencePages': _pool_evidence_snapshot(evidence_pool),
    }


def _summary_research_restore(saved):
    """Rebuild the small response shape used by the synthesis path."""
    if not isinstance(saved, dict):
        return None
    parsed = saved.get('parsed')
    if not isinstance(parsed, dict) or not saved.get('searched'):
        return None
    raw_output = str(saved.get('rawOutput') or '').strip()
    if not raw_output and not parsed:
        return None
    annotations = [
        {'url_citation': {'url': str(url), 'title': 'مصدر مسترجع', 'content': ''}}
        for url in (saved.get('citationUrls') or []) if str(url).startswith('http')
    ]
    result = {'choices': [{'message': {
        'content': raw_output or json.dumps(parsed, ensure_ascii=False),
        'annotations': annotations,
    }}]}
    return {
        'key': str(saved.get('key') or ''),
        'label': str(saved.get('label') or ''),
        'city': str(saved.get('city') or ''),
        'district': str(saved.get('district') or ''),
        'hosts': list(saved.get('hosts') or []),
        'activitySignature': str(saved.get('activitySignature') or ''),
        'result': result, 'parsed': parsed, 'parse_error': '',
        'pages': [], 'searched': True,
    }


def _run_market_summary_research(payload, usage_ctx, evidence_pool, deadline,
                                 report=None, offer_lang='ar',
                                 resume_state=None, checkpoint=None,
                                 trace_writer=None):
    """Run source-specific Playwright/SearXNG researchers concurrently."""
    report = report if callable(report) else (lambda *_args: None)
    source_map = _summary_research_sources_by_group()
    allowed_activity_hosts = _summary_research_activity_hosts(payload)
    activity_profile = market_study.summary_activity_profile(payload)
    scope_activities_selected = bool(activity_profile.get('source_kinds'))
    activity_signature = _summary_research_activity_signature(payload)
    scope = market_study.normalize_summary_scope(
        payload.get('summaryScope'), payload.get('city'))
    jobs = []
    for city_scope in scope['cities']:
        locations = [('', city_scope['name'])]
        locations.extend((district, city_scope['name'])
                         for district in city_scope['districts'])
        for district, city in locations:
            for group in _SUMMARY_RESEARCH_GROUPS:
                for host in source_map.get(group['key']) or []:
                    if scope_activities_selected and not market_study._host_in(
                            host, allowed_activity_hosts):
                        continue
                    if district and host in {'gaca.gov.sa', 'geo.stats.gov.sa'}:
                        continue
                    jobs.append((group, [host], city, district))
    if not jobs:
        return {'success': False, 'error': 'summary_scope_required',
                'outcomes': [], 'citation_urls': []}
    report(12, f'بدء {len(jobs)} مهمة بحث للمصادر بالتوازي؛ باحث مستقل لكل مصدر ونطاق')
    if callable(trace_writer):
        trace_writer({'event': 'research_started', 'researcher_count': len(jobs),
                      'sources_by_group': source_map,
                      'cities': scope.get('cities') or []})
    outcomes = []
    resume_state = resume_state if isinstance(resume_state, dict) else {}
    saved_researchers = (resume_state.get('researchers')
                         if isinstance(resume_state.get('researchers'), dict) else {})
    saved_pages = resume_state.get('evidencePages')
    if evidence_pool is not None and isinstance(saved_pages, list):
        for page in saved_pages:
            if not isinstance(page, dict):
                continue
            url = str(page.get('url') or '').strip()
            if not url.startswith('http'):
                continue
            try:
                evidence_pool.add_page(
                    url, title=str(page.get('title') or ''),
                    content=str(page.get('content') or ''), final_url=url,
                    via='resumed')
            except Exception:
                continue
    progress_lock = threading.Lock()
    worker_progress = [
        {'started': False, 'searches': 0, 'pages': 0, 'current': ''}
        for _ in jobs
    ]
    completed_jobs = set()
    for job_index, (group, hosts, city, district) in enumerate(jobs):
        saved = saved_researchers.get(
            _summary_research_task_id(
                group, hosts, city, district, activity_signature))
        restored = _summary_research_restore(saved)
        if restored is None:
            continue
        outcomes.append(restored)
        completed_jobs.add(job_index)
        for url in _market_citation_urls(restored['result']):
            if evidence_pool is not None:
                try:
                    evidence_pool.add_page(url, via='resumed')
                except Exception:
                    pass
    last_progress = 12
    last_report_at = 0.0
    last_report_pct = 12
    reports_open = True

    def report_research_progress(job_index, event=None, completed=False):
        """Reflect browser activity before each source researcher finishes."""
        nonlocal last_progress, last_report_at, last_report_pct
        with progress_lock:
            if not reports_open:
                return
            state = worker_progress[job_index]
            phase = ''
            if event:
                state['started'] = True
                phase = str(event.get('phase') or '')
                tool = str(event.get('tool') or '')
                hint = str(event.get('hint') or '').strip()
                if phase == 'tool':
                    activity = {
                        'web_search': 'يجري البحث',
                        'open_url': 'يجري فتح صفحة',
                        'click_element': 'يجري فحص الصفحة',
                        'type_text': 'يجري إدخال بيانات البحث',
                        'scroll_page': 'يجري فحص الصفحة',
                        'inspect_page': 'يجري فحص الصفحة',
                    }.get(tool, 'يجري تنفيذ خطوة بحث')
                    state['current'] = f'{activity}: {hint}' if hint else activity
                elif phase == 'tool_done':
                    state['searches'] = max(
                        state['searches'], int(event.get('searches') or 0))
                    state['pages'] = max(
                        state['pages'], int(event.get('pages') or 0))
                    activity = {
                        'web_search': 'اكتمل البحث',
                        'open_url': 'اكتمل فتح الصفحة',
                        'click_element': 'اكتمل فحص الصفحة',
                        'type_text': 'اكتمل إدخال بيانات البحث',
                        'scroll_page': 'اكتمل فحص الصفحة',
                        'inspect_page': 'اكتمل فحص الصفحة',
                    }.get(tool, 'اكتملت خطوة البحث')
                    state['current'] = f'{activity}: {hint}' if hint else activity
                elif phase == 'round':
                    state['current'] = 'يجري تحليل نتائج البحث'
            if completed:
                completed_jobs.add(job_index)
                state['current'] = ''

            activity_credit = sum(
                1.0 if index in completed_jobs else
                min(0.8, 0.1 * min(8, worker['searches'] + worker['pages']))
                for index, worker in enumerate(worker_progress))
            pct = 12 + int(56 * activity_credit / max(1, len(jobs)))
            last_progress = max(last_progress, pct)
            started = sum(1 for worker in worker_progress if worker['started'])
            active = max(0, started - len(completed_jobs))
            searches = sum(worker['searches'] for worker in worker_progress)
            pages = sum(worker['pages'] for worker in worker_progress)
            group, _hosts, city, district = jobs[job_index]
            current = worker_progress[job_index]['current']
            message = (f'تقدم البحث: اكتملت {len(completed_jobs)} من {len(jobs)} مهمة؛ '
                       f'{searches} عملية بحث و{pages} صفحة من {active} باحث نشط.')
            location = f'{group["label"]} — {city}'
            if district:
                location += f' — {district}'
            if current:
                message += f' {location}: {current}.'
            should_report = completed or phase in ('tool', 'tool_done')
            now = time.monotonic()
            if (not should_report or
                    (not completed and pct == last_report_pct
                     and now - last_report_at < 0.5)):
                return
            last_report_at = now
            last_report_pct = last_progress
            report(last_progress, message)

    cancel_event = threading.Event()
    source_worker_count = len({
        host for _group, hosts, _city, _district in jobs for host in hosts
    })
    executor = ThreadPoolExecutor(
        max_workers=max(1, source_worker_count),
        thread_name_prefix='market-research')
    futures = {}
    fatal_found = False

    def persist_checkpoint(force=False):
        if not callable(checkpoint):
            return
        usable = sum(1 for item in outcomes
                     if item.get('searched')
                     and not (item.get('result') or {}).get('error'))
        if not force and usable % 4:
            return
        try:
            checkpoint(_summary_research_checkpoint(outcomes, evidence_pool))
        except Exception as exc:
            print(f'[MARKET SUMMARY] researcher checkpoint failed: {exc}')

    try:
        researcher_payload = dict(payload or {})
        researcher_payload['_summaryEvidencePages'] = (
            evidence_pool.pages() if evidence_pool is not None else [])
        for job_index, (group, hosts, city, district) in enumerate(jobs):
            if job_index in completed_jobs:
                continue
            def on_event(event, index=job_index, group=group, hosts=hosts,
                         city=city, district=district):
                report_research_progress(index, event=event)
                if callable(trace_writer):
                    trace_writer({
                        'event': 'browser_step', 'researcher': group['key'],
                        'label': group['label'], 'hosts': hosts,
                        'city': city, 'district': district,
                        **(event if isinstance(event, dict) else {}),
                    })
            future = executor.submit(
                _run_summary_researcher, group, hosts, researcher_payload,
                city, district, usage_ctx, deadline, offer_lang,
                cancel_event=cancel_event, on_event=on_event)
            futures[future] = job_index
        for future in as_completed(futures):
            if future.cancelled():
                continue
            job_index = futures[future]
            group, hosts, city, district = jobs[job_index]
            try:
                outcome = future.result()
            except Exception as exc:
                outcome = {'key': group['key'], 'label': group['label'],
                           'city': city, 'district': district,
                           'hosts': list(hosts),
                           'result': {'error': {'message': str(exc)}},
                           'parsed': {}, 'parse_error': 'worker_error',
                           'pages': [], 'searched': False}
            outcome['activitySignature'] = activity_signature
            outcomes.append(outcome)
            if callable(trace_writer):
                trace_writer({
                    'event': 'researcher_result', 'researcher': group['key'],
                    'label': group['label'], 'hosts': hosts, 'city': city,
                    'district': district, 'searched': outcome.get('searched'),
                    'parsed': outcome.get('parsed'),
                    'parse_error': outcome.get('parse_error'),
                    'filtered_sources': outcome.get('filtered_sources', 0),
                    'error': (outcome.get('result') or {}).get('error'),
                    'opened_pages': outcome.get('pages') or [],
                    'citation_urls': _market_citation_urls(
                        outcome.get('result') or {}),
                })
            report_research_progress(job_index, completed=True)
            fatal = _ai_fatal_error_dict(outcome.get('result') or {})
            if fatal is not None:
                fatal_found = True
                cancel_event.set()
                with progress_lock:
                    reports_open = False
                for pending in futures:
                    if pending is not future:
                        pending.cancel()
                persist_checkpoint(force=True)
                break
            if evidence_pool is not None:
                for page in outcome.get('pages') or []:
                    evidence_pool.add_page(page.get('url'), page.get('title'),
                                           page.get('content'), final_url=page.get('url'),
                                           via='parallel_browser')
            if outcome.get('searched') and not (outcome.get('result') or {}).get('error'):
                persist_checkpoint()
            report(12 + int(56 * len(outcomes) / max(1, len(jobs))),
                   f"اكتملت مهمة البحث {len(outcomes)} من {len(jobs)}: "
                   f"{outcome['label']} — {city}" + (f' — {district}' if district else ''))
    finally:
        executor.shutdown(wait=not fatal_found, cancel_futures=fatal_found)
    if not fatal_found:
        persist_checkpoint(force=True)
    fatal = next((_ai_fatal_error_dict(item.get('result') or {})
                  for item in outcomes
                  if _ai_fatal_error_dict(item.get('result') or {})), None)
    if fatal is not None:
        return {'success': False, 'error': fatal.get('message') or
                'insufficient_credit', 'outcomes': outcomes,
                'citation_urls': []}
    outcomes.sort(key=lambda item: next(
        (index for index, group in enumerate(_SUMMARY_RESEARCH_GROUPS)
         if group['key'] == item['key']), len(_SUMMARY_RESEARCH_GROUPS)))
    opened = [item for item in outcomes if item.get('searched')]
    if not opened:
        planned_pages = [page for page in (evidence_pool.pages()
                                           if evidence_pool is not None else [])
                         if isinstance(page, dict) and page.get('url')]
        if not planned_pages:
            return {'success': False, 'error': 'لم ينجح أي مسار في فتح دليل ويب',
                    'outcomes': outcomes, 'citation_urls': []}
        # The catalog fetch is real retrieved evidence even when every
        # browser researcher fails. Synthesis can use those pages while
        # reporting that interactive source coverage is still partial.
        plan_report = {
            'research_group': 'source_plan',
            'source_hosts': [],
            'city': '',
            'district': '',
            'opened_evidence': True,
            'coverage_status': 'partial',
            'research_output': 'صفحات جرى استرجاعها من خطة المصادر المعتمدة.',
            'coverage_gap': ('تعذر على الباحثين فتح صفحات تفاعلية؛ الأدلة المتاحة هنا مقتصرة على '
                             'الصفحات التي استرجعتها خطة المصادر، ولا تثبت اكتمال النتائج أو تفاصيلها.'),
        }
        return {
            'success': True,
            'outcomes': outcomes,
            'reports': [plan_report],
            'citation_urls': list(dict.fromkeys(
                str(page.get('url') or '').strip() for page in planned_pages
                if str(page.get('url') or '').strip())),
        }
    reports = []
    citations = []
    for item in outcomes:
        parsed = item.get('parsed') if isinstance(item.get('parsed'), dict) else {}
        coverage = parsed.get('coverage') if isinstance(parsed.get('coverage'), list) else []
        declared_gaps = parsed.get('coverage_gaps')
        declared_gaps = ([str(gap).strip() for gap in declared_gaps if str(gap).strip()]
                         if isinstance(declared_gaps, list) else [])
        incomplete = [row for row in coverage if not isinstance(row, dict)
                      or str(row.get('completeness') or '').strip().lower() != 'complete'
                      or str(row.get('gaps') or '').strip()]
        coverage_status = (
            'unavailable' if not item.get('searched') else
            'complete' if coverage and not incomplete and not declared_gaps else 'partial')
        coverage_gap = ''
        if coverage_status == 'unavailable':
            coverage_gap = 'لم يفتح هذا المصدر دليلًا؛ اعتبر بياناته فجوة تغطية.'
        elif coverage_status == 'partial':
            coverage_gap = ('لم يثبت الباحث استنفاد البيانات المرتبطة بالمهمة داخل المصدر؛ '
                            'تحقق من تفاصيل التغطية والفجوات.')
        if item.get('parse_error'):
            coverage_gap = (coverage_gap + ' ' if coverage_gap else '') + (
                'تعذر تحليل نتيجة الباحث المهيكلة؛ لم تُستخدم نتيجة غير قابلة للتحقق.')
        if incomplete or declared_gaps:
            details = [str(row.get('gaps') or '').strip() for row in incomplete
                       if isinstance(row, dict) and str(row.get('gaps') or '').strip()]
            details.extend(declared_gaps)
            if details:
                coverage_gap += ' ' + '؛ '.join(dict.fromkeys(details))
        reports.append({
            'research_group': item['key'],
            'source_hosts': item.get('hosts') or [],
            'city': item.get('city'), 'district': item.get('district'),
            'opened_evidence': bool(item.get('searched')),
            'coverage_status': coverage_status,
            'research_output': parsed or {
                'coverage': [], 'findings': [], 'sources': [],
                'coverage_gaps': ['تعذر تحليل نتيجة الباحث المهيكلة.'],
            },
            'coverage_gap': coverage_gap,
        })
        citations.extend(_market_citation_urls(item.get('result') or {}))
        citations.extend(page.get('url') for page in item.get('pages') or [])
    if evidence_pool is not None:
        citations.extend(page.get('url') for page in evidence_pool.pages()
                         if isinstance(page, dict))
    local_bench = payload.get('summaryLocalBenchmarks') or {}
    for local_group in (local_bench.get('groups') or []) + (local_bench.get('rental_groups') or []):
        citations.extend(local_group.get('source_urls') or [])
    return {
        'success': True,
        'outcomes': outcomes,
        'reports': reports,
        'citation_urls': list(dict.fromkeys(url for url in citations if url)),
    }


def _run_market_summary_aggregator(system_prompt, prompt, usage_ctx,
                                   research, deadline=None):
    remaining = None
    if deadline is not None:
        remaining = max(1, int(float(deadline) - time.time()))
        if remaining <= 1:
            return {'error': {'message': 'deadline_exceeded'}}
    cap = min(_SUMMARY_AGGREGATOR_MAX_OUTPUT_TOKENS,
              int(MARKET_STUDY_MAX_TOKENS))
    result = None
    for _attempt in range(4):
        if deadline is not None:
            remaining = max(1, int(float(deadline) - time.time()))
            if remaining <= 1:
                return {'error': {'message': 'deadline_exceeded'}}
        # The streamed aggregator can be cut mid-answer, so a stop saves the
        # rest of the summary instead of paying for all of it — and it is not
        # retried, because a stopped run is final.
        result = run_control.raise_if_cancelled(call_text_chat_stream(
            system_prompt, prompt, model=_SUMMARY_AGGREGATOR_MODEL,
            max_tokens=cap, reasoning_effort=_SUMMARY_AGGREGATOR_REASONING_EFFORT,
            timeout=min(_SUMMARY_AGGREGATOR_TIMEOUT, remaining or _SUMMARY_AGGREGATOR_TIMEOUT), usage_ctx=usage_ctx))
        if _ai_fatal_error_dict(result) is not None:
            return result
        error = result.get('error') if isinstance(result, dict) else None
        if isinstance(error, dict):
            code = str(error.get('code') or '').upper()
            if (error.get('fatal') or error.get('error_code')
                    or code in {'INSUFFICIENT_BALANCE', 'INSUFFICIENT_CREDITS',
                                'PROVIDER_CREDITS_EXHAUSTED'}):
                return result
            try:
                if int(error.get('http_status') or error.get('status') or error.get('code') or 0) == 402:
                    return result
            except (TypeError, ValueError):
                pass
        affordable = (_chat_affordable_tokens(result)
                      if isinstance(result, dict) and result.get('error') else None)
        if not affordable or affordable >= cap:
            break
        cap = max(1, int(affordable * 0.9))
        print(f'[MARKET SUMMARY] retrying aggregator with provider affordable cap={cap}')
    if not isinstance(result, dict):
        return {'error': {'message': 'aggregator returned an empty response'}}
    choices = result.get('choices') or []
    if choices:
        message = choices[0].setdefault('message', {})
        annotations = message.setdefault('annotations', [])
        seen = {str(((item or {}).get('url_citation') or {}).get('url') or '')
                for item in annotations if isinstance(item, dict)}
        for url in research.get('citation_urls') or []:
            if url and url not in seen:
                annotations.append({'url_citation': {'url': url, 'title': 'مصدر مفتوح أثناء البحث', 'content': ''}})
                seen.add(url)
    result['browse_trace'] = [{'url': url, 'title': '', 'chars': 0} for url in research.get('citation_urls') or []]
    return result
