
# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def _norm(value):
    return re.sub(r'\s+', ' ', str(value or '').strip())


def _clean_numeric(value):
    text = str(value or '').strip()
    if not text:
        return ''
    text = text.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    text = text.replace('٬', '').replace('،', '').replace(',', '').replace('٫', '.').replace(' ', '')
    if not re.fullmatch(r'-?\d+(?:\.\d+)?', text):
        return str(value or '').strip()
    try:
        rounded = Decimal(text).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return text
    return str(int(rounded)) if rounded == rounded.to_integral_value() else f'{rounded:.1f}'


def _first_nonempty(*values):
    for value in values:
        if isinstance(value, (dict, list, tuple, set)):
            continue
        text = _norm(value)
        if text:
            return text
    return ''


def _iter_source_values(value):
    if isinstance(value, dict):
        for key in ('url', 'urls', 'source_url', 'source_urls', 'sourceUrl', 'sourceUrls', 'href'):
            if value.get(key):
                yield from _iter_source_values(value.get(key))
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_source_values(item)
        return
    text = _norm(value)
    if not text:
        return
    urls = re.findall(r"https?://[^\s<>\"'\[\]{}]+", text)
    if urls:
        for url in urls:
            yield url.rstrip('.,،;:!?)]}')
        return
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, (list, tuple, dict)):
        yield from _iter_source_values(parsed)
        return
    for part in re.split(r'[\r\n,،;|]+', text):
        part = part.strip()
        if part:
            yield part


def _unique_values(values):
    result = []
    seen = set()
    for value in values:
        text = _norm(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


# A competitor price is stored exactly as the source page printed it — the
# row's price_currency keeps that figure honest instead of silently reading
# as SAR. Common spellings fold to ISO codes; an unknown token is dropped
# rather than invented (the cell then shows the SAR default).
_PRICE_CURRENCY_ALIASES = {
    'sar': 'SAR', 'ر.س': 'SAR', 'رس': 'SAR', 'ريال': 'SAR', 'ريال سعودي': 'SAR',
    'sr': 'SAR', 'sar.': 'SAR',
    'eur': 'EUR', '€': 'EUR', 'يورو': 'EUR',
    'usd': 'USD', '$': 'USD', 'us$': 'USD', 'دولار': 'USD',
    'دولار امريكي': 'USD',
    'aed': 'AED', 'درهم': 'AED', 'درهم اماراتي': 'AED',
    'gbp': 'GBP', '£': 'GBP', 'جنيه استرليني': 'GBP',
    'kwd': 'KWD', 'دينار': 'KWD', 'دينار كويتي': 'KWD', 'د.ك': 'KWD',
    'qar': 'QAR', 'ريال قطري': 'QAR', 'ر.ق': 'QAR', 'رق': 'QAR',
    'bhd': 'BHD', 'دينار بحريني': 'BHD', 'د.ب': 'BHD',
    'omr': 'OMR', 'ريال عماني': 'OMR', 'ر.ع': 'OMR',
    'egp': 'EGP', 'جنيه': 'EGP', 'جنيه مصري': 'EGP', 'ج.م': 'EGP',
    'jod': 'JOD', 'دينار اردني': 'JOD', 'jd': 'JOD',
    'try': 'TRY', '₺': 'TRY', 'ليره تركيه': 'TRY', 'ل.ت': 'TRY',
    'chf': 'CHF', 'فرنك سويسري': 'CHF',
    'lbp': 'LBP', 'ليره لبنانيه': 'LBP', 'ل.ل': 'LBP',
    'syp': 'SYP', 'ليره سوريه': 'SYP', 'ل.س': 'SYP',
    'iqd': 'IQD', 'دينار عراقي': 'IQD', 'د.ع': 'IQD',
    'lyd': 'LYD', 'دينار ليبي': 'LYD', 'د.ل': 'LYD',
    'tnd': 'TND', 'دينار تونسي': 'TND', 'د.ت': 'TND',
    'mad': 'MAD', 'درهم مغربي': 'MAD', 'د.م': 'MAD',
    'dzd': 'DZD', 'دينار جزائري': 'DZD', 'د.ج': 'DZD',
    'jpy': 'JPY', 'ين ياباني': 'JPY',
    'cny': 'CNY', 'يوان': 'CNY',
    'inr': 'INR', 'روبيه': 'INR',
    # د.إ / د.أ / د.ا stay unmapped on purpose — the fold below turns both the
    # Emirati dirham and the Jordanian dinar abbreviations into the same
    # «د.ا», and converting dirhams at the dinar rate is worse than no match.
}


def _canonical_price_currency(value):
    """ISO code for a competitor row's price_currency, '' when unknowable."""
    text = _norm(value)
    if not text:
        return ''
    folded = (text.casefold()
              .replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
              .replace('ة', 'ه').rstrip('.'))
    if folded in _PRICE_CURRENCY_ALIASES:
        return _PRICE_CURRENCY_ALIASES[folded]
    if re.fullmatch(r'[A-Za-z]{3}', text):
        return text.upper()
    return ''


# A source price printed in another currency is converted to SAR for the
# (ر.س) column — the (ر.س) figure is what the table displays, the original
# stays in price_cache as original_*. Rate precedence: an FX_SAR_<CCY> env
# override, then the live ER table, then this built-in fallback. Dollar-
# pegged GCC entries are exact; floating rows drift until the next edit —
# the live table is what keeps «any currency at the current rate» true.
_PRICE_FX_TO_SAR = {
    'USD': 3.75, 'AED': 1.0207, 'QAR': 1.0302, 'BHD': 9.9474, 'OMR': 9.7403,
    'EUR': 4.05, 'GBP': 4.85, 'KWD': 12.25, 'JOD': 5.29, 'EGP': 0.0765,
    'CHF': 4.70, 'TRY': 0.089, 'JPY': 0.025, 'CNY': 0.52, 'INR': 0.045,
    'LBP': 0.000042, 'SYP': 0.0003, 'IQD': 0.0029, 'LYD': 0.77,
    'TND': 1.27, 'MAD': 0.41, 'DZD': 0.028,
}

# One request per process covers every ISO currency — a live fetch per
# mention would be madness, so the whole SAR-based table caches for 12h
# (10min on failure, so a transient outage doesn't disable the run).
_PRICE_FX_LIVE = {'at': 0.0, 'rates': {}, 'ok': False}
_PRICE_FX_LIVE_OK_TTL = 12 * 3600
_PRICE_FX_LIVE_FAIL_TTL = 10 * 60


def _live_fx_rates():
    """{ISO: SAR-per-unit} from the open ER API; {} when unreachable."""
    import time
    import urllib.request
    cache = _PRICE_FX_LIVE
    now = time.time()
    ttl = _PRICE_FX_LIVE_OK_TTL if cache['ok'] else _PRICE_FX_LIVE_FAIL_TTL
    if cache['at'] and now - cache['at'] < ttl:
        return cache['rates']
    try:
        req = urllib.request.Request(
            'https://open.er-api.com/v6/latest/SAR',
            headers={'User-Agent': 'landloom-market/1.0'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            payload = json.loads(resp.read() or b'{}')
        rates = payload.get('rates') if isinstance(payload, dict) else {}
        cache['rates'] = {str(k).upper(): 1.0 / float(v)
                          for k, v in (rates or {}).items() if float(v) > 0}
        cache['ok'] = True
    except Exception:
        cache['rates'], cache['ok'] = {}, False
    cache['at'] = now
    return cache['rates']


def price_fx_to_sar(currency):
    """SAR multiplier for a source currency — 1.0 for SAR, None when the
    rate is unknowable. env override > live rate > static fallback."""
    code = _canonical_price_currency(currency)
    if code == 'SAR':
        return 1.0
    if not code:
        return None
    try:
        env_rate = float(os.environ.get(f'FX_SAR_{code}') or 0)
    except (TypeError, ValueError):
        env_rate = 0.0
    if env_rate > 0:
        return env_rate
    return _live_fx_rates().get(code) or _PRICE_FX_TO_SAR.get(code)


_COMPETITOR_SOURCE_FIELD_ALIASES = {
    'name': 'name',
    'project_name': 'name',
    'projectName': 'name',
    'اسم المشروع': 'name',
    'project_type': 'project_type',
    'projectType': 'project_type',
    'نوع المشروع': 'project_type',
    'area': 'area_sqm',
    'area_sqm': 'area_sqm',
    'areaSqm': 'area_sqm',
    'المساحة': 'area_sqm',
    'area_from': 'area_from',
    'areaFrom': 'area_from',
    'المساحة من': 'area_from',
    'area_to': 'area_to',
    'areaTo': 'area_to',
    'المساحة إلى': 'area_to',
    'status': 'status',
    'project_status': 'status',
    'حالة المشروع': 'status',
    'classification': 'classification',
    'تصنيف': 'classification',
    'logo_url': 'logo_url',
    'logoUrl': 'logo_url',
    'شعار المنافس': 'logo_url',
    'operation_type': 'operation_type',
    'operationType': 'operation_type',
    'operation': 'operation_type',
    'نوع العملية': 'operation_type',
    'price_type': 'price_type',
    'priceType': 'price_type',
    'نوع السعر': 'price_type',
    'price_value': 'price_value',
    'priceValue': 'price_value',
    'value': 'price_value',
    'price_from': 'price_from',
    'priceFrom': 'price_from',
    'price_to': 'price_to',
    'priceTo': 'price_to',
    'district': 'district',
    'neighborhood': 'district',
    'الحي': 'district',
    'distance_km': 'distance_km',
    'distanceKm': 'distance_km',
    'distance': 'distance_km',
    'المسافة': 'distance_km',
    'المسافة بالكيلومتر': 'distance_km',
    'lat': 'lat',
    'latitude': 'lat',
    'خط العرض': 'lat',
    'lng': 'lng',
    'lon': 'lng',
    'longitude': 'lng',
    'خط الطول': 'lng',
    'benchmarks': 'benchmarks',
    'benchmark_axes': 'benchmarks',
    'measured_against': 'benchmarks',
    'يُقاس على': 'benchmarks',
    'يقاس على': 'benchmarks',
}

_COMPETITOR_SOURCE_FIELD_LABELS = {
    'name': 'اسم المشروع',
    'project_type': 'نوع المشروع',
    'area_sqm': 'مساحة الوحدة',
    'area_from': 'مساحة الوحدة من',
    'area_to': 'مساحة الوحدة إلى',
    'status': 'الحالة',
    'classification': 'التصنيف',
    'logo_url': 'شعار المنافس',
    'operation_type': 'نوع العملية',
    'price_type': 'نوع السعر',
    'price_value': 'قيمة السعر',
    'price_from': 'حد السعر الأدنى',
    'price_to': 'حد السعر الأعلى',
    'district': 'الحي',
    'distance_km': 'المسافة من موقع المشروع',
    'lat': 'خط العرض',
    'lng': 'خط الطول',
    'benchmarks': 'يُقاس على',
}


def _canonical_source_field(value):
    text = _norm(value)
    return _COMPETITOR_SOURCE_FIELD_ALIASES.get(text, text)


def _http_source_urls(value):
    return _unique_values(
        item for item in _iter_source_values(value)
        if str(item).strip().lower().startswith(('http://', 'https://'))
    )


def competitor_field_sources(row):
    if not isinstance(row, dict):
        return {}
    raw = row.get('field_sources') or row.get('fieldSources') or {}
    entries = []
    if isinstance(raw, dict):
        entries = raw.items()
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            field = item.get('field') or item.get('key') or item.get('name')
            urls = item.get('urls') or item.get('source_urls') or item.get('sourceUrls') or item.get('url')
            if field:
                entries.append((field, urls))
    result = {}
    for field, value in entries:
        key = _canonical_source_field(field)
        urls = _http_source_urls(value)
        if key and urls:
            result[key] = _unique_values((result.get(key) or []) + urls)
    return result


def competitor_source_urls(row):
    if not isinstance(row, dict):
        return []
    values = []
    for key in ('source_urls', 'sourceUrls', 'urls', 'source_url', 'sourceUrl', 'url', 'sources', 'source'):
        values.extend(_http_source_urls(row.get(key)))
    for urls in competitor_field_sources(row).values():
        values.extend(urls)
    return _unique_values(values)


def _fold_choice(value):
    return re.sub(r'\s+', ' ', _norm(value).replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه')).casefold()


def _canonical_operation_ar(value, price_type='', project_type=''):
    """Canonical Arabic operation — the historical normalizer kept intact."""
    text = _norm(value)
    if text in COMPETITOR_OPERATION_OPTIONS:
        return text
    if text in OPERATION_AR_BY_EN:
        return OPERATION_AR_BY_EN[text]
    folded = _fold_choice(text)
    if folded in {'sale', 'sell', 'selling'} or any(token in folded for token in ('بيع', 'شراء', 'تمليك')):
        return 'بيع'
    if folded in {'rent', 'rental', 'leasing'} or any(token in folded for token in ('ايجار', 'تاجير', 'تأجير')):
        return 'إيجار'
    if folded in {'hotel', 'hospitality'} or any(token in folded for token in ('فندقي', 'فندق', 'ليله', 'hotel', 'hospital')):
        return 'تشغيل فندقي'
    if folded in {'تشغيل', 'تشغيل فندقي', 'hotel operation'} or folded.startswith('تشغيل '):
        return 'تشغيل فندقي'
    if text:
        return 'أخرى'
    price_folded = _fold_choice(price_type)
    if any(token in price_folded for token in ('ايجار', 'تاجير', 'rent')):
        return 'إيجار'
    if any(token in price_folded for token in ('ليله', 'adr', 'revpar', 'غرفه', 'hotel')):
        return 'تشغيل فندقي'
    if any(token in price_folded for token in ('بيع', 'سعر الوحدة', 'سعر الوحده', 'سعر المتر', 'sale', 'sell')):
        return 'بيع'
    if _fold_choice(project_type) == 'فندقي':
        return 'تشغيل فندقي'
    return ''


def _canonical_operation(value, price_type='', project_type='', offer_lang='ar'):
    canonical = _canonical_operation_ar(value, price_type, project_type)
    if canonical and offer_lang == 'en':
        canonical = OPERATION_EN_BY_AR.get(canonical, 'Other')
    return canonical


def _canonical_price_type(value, operation, price_from='', price_to='', price_value='', offer_lang='ar'):
    en = offer_lang == 'en'
    text = _norm(value)
    if en:
        operation = OPERATION_EN_BY_AR.get(_norm(operation), _norm(operation))
    options = (PRICE_TYPE_BY_OPERATION_EN if en else PRICE_TYPE_BY_OPERATION).get(
        operation or ('Other' if en else 'أخرى'),
        (PRICE_TYPE_BY_OPERATION_EN if en else PRICE_TYPE_BY_OPERATION)['Other' if en else 'أخرى'])
    if text in options:
        return text
    text = PRICE_TYPE_EN_BY_AR.get(text, text) if en else text
    if text in options:
        return text
    op_ar = OPERATION_AR_BY_EN.get(operation, operation) if en else operation
    folded = _fold_choice(text)
    if any(token in folded for token in ('نطاق', 'range')) or price_from or price_to:
        return ('Room Price Range' if en else 'نطاق أسعار الغرف') if op_ar == 'تشغيل فندقي' else ('Price Range' if en else 'نطاق سعري')
    if any(token in folded for token in ('adr', 'متوسط سعر الغرف')):
        return ('Average Daily Rate (ADR)' if en else 'متوسط سعر الغرفة ADR') if op_ar == 'تشغيل فندقي' else text
    if 'revpar' in folded or 'الايراد لكل غرفه' in folded:
        return ('RevPAR' if en else 'الإيراد لكل غرفة RevPAR') if op_ar == 'تشغيل فندقي' else text
    if any(token in folded for token in ('ليله', 'night', 'nightly')):
        return ('Nightly Rate' if en else 'سعر الليلة') if op_ar == 'تشغيل فندقي' else text
    if 'يبدأ' in text or 'starting' in folded:
        return ('Starting From' if en else 'يبدأ من') if op_ar in ('بيع', 'إيجار') else text
    if 'سعر المتر المربع' in text or 'سعر المتر' in text or 'price per sqm' in folded or 'per sqm' in folded or 'sqm' in folded:
        if op_ar == 'بيع':
            return 'Price per SQM' if en else 'سعر المتر المربع'
        if op_ar == 'إيجار':
            annual = any(token in folded for token in ('سنوي', 'annual', 'year'))
            if en:
                return 'Annual Rent per SQM' if annual else 'Monthly Rent per SQM'
            return 'إيجار المتر السنوي' if annual else 'إيجار المتر الشهري'
    if 'الوحدة' in text or 'unit' in folded:
        if op_ar == 'بيع':
            return 'Unit Price' if en else 'سعر الوحدة'
        if op_ar == 'إيجار':
            annual = any(token in folded for token in ('سنوي', 'annual', 'year'))
            if en:
                return 'Annual Unit Rent' if annual else 'Monthly Unit Rent'
            return 'إيجار الوحدة السنوي' if annual else 'إيجار الوحدة الشهري'
    if text:
        return text
    if price_value:
        return 'Other' if en else 'أخرى'
    return ''


def audience_kind_for_label(label):
    text = _norm(label)
    if text in ('مكاتب', 'إداري'):
        return 'مكاتب'
    if text in ('تجزئة ومحلات', 'مطاعم ومقاهي', 'مركز تجاري', 'تجاري'):
        return 'تجزئة'
    if text in ('فندق', 'شقق مخدومة', 'منتجع', 'مساكن فندقية', 'فندقي'):
        return 'فندقي'
    if text in ('مصنع', 'مستودعات', 'مركز لوجستي', 'مجمع صناعي', 'صناعي ولوجستي', 'صناعي', 'لوجستي'):
        return 'صناعي ولوجستي'
    if text == 'سكني':
        return 'سكني'
    return ''


def analysis_kind_for_project(main_type, subtype='', components=None):
    main = _norm(main_type)
    if main == 'أخرى':
        main = 'متعدد الاستخدامات'
    sub = _norm(subtype)
    subtype_list = parse_selected_list(sub)
    extra = parse_selected_list(components)
    kinds = []

    def add_kind(label):
        kind = audience_kind_for_label(label)
        if kind and kind not in kinds:
            kinds.append(kind)

    if main == 'متعدد الاستخدامات':
        for item in extra or subtype_list:
            add_kind(item)
        return kinds
    if main == 'تجاري':
        for item in subtype_list:
            add_kind(item)
        return kinds
    if main == 'فندقي':
        return ['فندقي'] if subtype_list else []
    if main == 'صناعي ولوجستي':
        return ['صناعي ولوجستي'] if subtype_list else []
    if main == 'سكني':
        return ['سكني']
    add_kind(sub or main)
    return kinds


def activity_class_options(main_type, subtype='', components=None):
    kinds = analysis_kind_for_project(main_type, subtype, components)
    options = []
    seen = set()
    mapping = {
        'فندقي': ACTIVITY_CLASS_BY_TYPE['فندقي'],
        'مكاتب': ACTIVITY_CLASS_BY_TYPE['مكاتب'],
        'صناعي ولوجستي': ACTIVITY_CLASS_BY_TYPE['صناعي ولوجستي'],
    }
    specialized = False
    for kind in kinds:
        for option in mapping.get(kind, []):
            specialized = True
            if option not in seen:
                seen.add(option)
                options.append(option)
    if specialized:
        return options
    return [item['label'] for item in PROJECT_LEVELS]


def target_audience_options(main_type, subtype='', components=None):
    kinds = analysis_kind_for_project(main_type, subtype, components)
    if not kinds:
        return list(GENERAL_TARGET_AUDIENCE)
    options = []
    seen = set()
    for kind in kinds:
        for option in TARGET_AUDIENCE_BY_KIND.get(kind, []):
            if option not in seen:
                seen.add(option)
                options.append(option)
    return options


def price_types_for_operation(operation, offer_lang='ar'):
    if offer_lang == 'en':
        operation = OPERATION_EN_BY_AR.get(_norm(operation), _norm(operation))
        return list(PRICE_TYPE_BY_OPERATION_EN.get(operation, PRICE_TYPE_BY_OPERATION_EN['Other']))
    return list(PRICE_TYPE_BY_OPERATION.get(_norm(operation), PRICE_TYPE_BY_OPERATION['أخرى']))


def price_uses_range(price_type):
    text = _norm(price_type)
    return text in RANGE_PRICE_TYPES or text in RANGE_PRICE_TYPES_EN


def resolve_competitor_radius_km(radius_value, custom_km=None):
    value = _norm(radius_value) or '10'
    if value == 'auto':
        value = '10'
    if value == 'city':
        return None
    if value == 'custom':
        try:
            number = float(custom_km)
        except (TypeError, ValueError):
            return DEFAULT_COMPETITOR_RADIUS_KM
        return number if number > 0 else DEFAULT_COMPETITOR_RADIUS_KM
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_COMPETITOR_RADIUS_KM
    return number if number > 0 else DEFAULT_COMPETITOR_RADIUS_KM


# Summary-scope modes: the market summary's own geographic frame, separate
# from the competitors radius. 'distance' is the historical behaviour
# (entered district + radius scope, single nearest-district substitute);
# 'city' / 'district' cover an explicit user-entered place list instead.
SUMMARY_SCOPE_MODES = ('distance', 'city', 'district')
SUMMARY_SCOPE_MAX_PLACES = 12


def normalize_summary_scope(value):
    """Cleaned {mode, distance, distance_custom_km, places} summary scope.

    Anything unrecognized falls back to the historical distance behaviour,
    so old drafts without the field generate exactly as before. A listed
    mode with an empty place list also falls back — a scope with no names
    cannot bind any figure.
    """
    scope = {'mode': 'distance', 'distance': '10',
             'distance_custom_km': '', 'places': []}
    if not isinstance(value, dict):
        return scope
    mode = _norm(value.get('mode'))
    if mode in ('city', 'district'):
        scope['mode'] = mode
    distance = _norm(value.get('distance') or value.get('radius') or '')
    if distance in ('3', '5', '10', 'city', 'custom'):
        scope['distance'] = distance
    custom_km = _norm(value.get('distance_custom_km')
                      or value.get('distanceCustomKm')
                      or value.get('custom_km') or '')
    if custom_km:
        scope['distance_custom_km'] = custom_km
    raw_places = value.get('places')
    if isinstance(raw_places, str):
        raw_places = re.split(r'[,،\n;|]+', raw_places)
    places = []
    if isinstance(raw_places, (list, tuple)):
        for item in raw_places:
            name = _norm(item)
            if name and name not in places:
                places.append(name)
            if len(places) >= SUMMARY_SCOPE_MAX_PLACES:
                break
    scope['places'] = places
    if scope['mode'] in ('city', 'district') and not places:
        scope['mode'] = 'distance'
    return scope


def summary_scope_label(scope):
    """Short Arabic label of a normalized summary scope for prompts."""
    scope = scope if isinstance(scope, dict) else {}
    mode = scope.get('mode')
    if mode == 'city':
        return 'مدن محددة: ' + '، '.join(scope.get('places') or [])
    if mode == 'district':
        return 'أحياء محددة: ' + '، '.join(scope.get('places') or [])
    distance = _norm(scope.get('distance')) or '10'
    if distance == 'custom':
        custom = _norm(scope.get('distance_custom_km'))
        return f'نطاق {custom} كم'.strip() if custom else 'نطاق مخصص'
    if distance == 'city':
        return 'كامل المدينة'
    return f'نطاق {distance} كم'


def parse_selected_list(value):
    if isinstance(value, list):
        return [_norm(item) for item in value if _norm(item)]
    text = _norm(value)
    if not text:
        return []
    if text.startswith('['):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [_norm(item) for item in parsed if _norm(item)]
        except Exception:
            pass
    return [part.strip() for part in re.split(r'[,،\n;|]', text) if part.strip()]


def empty_competitor(source='manual'):
    return {
        'id': str(uuid.uuid4()),
        'name': '',
        'project_type': '',
        'area_mode': 'fixed',
        'area_sqm': '',
        'area_from': '',
        'area_to': '',
        'status': '',
        'classification': '',
        'logo_file_id': '',
        'logo_path': '',
        'logo_url': '',
        'logo_source_url': '',
        'district': '',
        'distance_km': '',
        'lat': '',
        'lng': '',
        'conflict_warnings': [],
        'operation_type': '',
        'price_type': '',
        'price_value': '',
        'price_from': '',
        'price_to': '',
        'source': '',
        'source_url': '',
        'source_urls': [],
        'field_sources': {},
        'data_date': '',
        'row_source': source,
    }


def empty_summary():
    return {item['key']: '' for item in SUMMARY_SECTIONS}


def empty_swot():
    return {item['key']: '' for item in SWOT_SECTIONS}


def summary_prose(value):
    """The market summary as one prose paragraph.

    This helper creates the executive paragraph from either the new structured
    analysis or an older paragraph/string value. It skips empty placeholders
    and the decision, which remains in its own field.
    """
    if isinstance(value, str):
        return re.sub(r'\s+', ' ', str(value)).strip()
    if isinstance(value, dict):
        parts = []
        for item in SUMMARY_SECTIONS:
            text = _norm(value.get(item['key']))
            if text and text != MISSING_VALUE_PHRASE:
                parts.append(re.sub(r'\s+', ' ', text))
        return ' '.join(parts).strip()
    return ''


def summary_has_content(value):
    """Return whether the detailed market analysis has a real value."""
    if isinstance(value, dict):
        return any(
            _norm(value.get(item['key'])) and _norm(value.get(item['key'])) != MISSING_VALUE_PHRASE
            for item in SUMMARY_SECTIONS
        )
    text = _norm(value)
    return bool(text and text != MISSING_VALUE_PHRASE)


def is_market_summary_paragraph(value):
    """Identify the prose executive summary versus the old headed block."""
    text = str(value or '').replace('\\r\\n', '\n').replace('\\n', '\n').strip()
    if not text:
        return False
    if re.search(r'(?m)^\s*\d+[.)]\s+', text):
        return False
    headings = {
        'نطاق دراسة السوق', 'نطاق الدراسة', 'المنافسون', 'تحليل السوق',
        'تحليل SWOT', 'المصادر', 'مصادر دراسة السوق', 'القرار',
        'إخلاء المسؤولية', 'ملخص دراسة سوق العمل', SUMMARY_TITLE,
    }
    return not any(line.strip().rstrip(':：') in headings for line in text.splitlines() if line.strip())


_GENERIC_SOURCE_PATHS = {
    '', '/', '/en', '/ar', '/en/', '/ar/', '/index.html', '/index.php',
    '/home', '/home/', '/ar/home', '/en/home',
}


def is_generic_source_homepage(url):
    text = str(url or '').strip()
    if not text:
        return False
    parsed = urlsplit(text)
    if not parsed.netloc:
        return False
    path = (parsed.path or '').rstrip('/') or '/'
    return (path.lower() in _GENERIC_SOURCE_PATHS or path.lower() in {'/', ''}) and not parsed.query and not parsed.fragment


def _source_host(url):
    return (urlsplit(str(url or '')).netloc or '').lower().removeprefix('www.')


# Classifieds/booking portals banned as competitor evidence. Aqar is the only
# classifieds portal for residential/commercial rows; Booking.com is allowed
# for hotel rows alone. Every other portal link is stripped from the row.
_BANNED_LISTING_HOST_TOKENS = (
    'bayut.', 'wasalt.', 'dealapp.', 'dealmap', 'dubizzle', 'propertyfinder',
    'opensooq', 'haraj', 'lamudi', 'exxl', 'estater', 'muqawil', 'eqqar',
    'aqaar.', 'aqarmap', 'trivago.', 'airbnb.', 'hotels.', 'expedia.',
    'agoda.', 'vrbo', 'tripadvisor.',
    # Social networks are never competitor evidence — a bio or a reel caption
    # carries an unverifiable figure, and an Instagram profile's title IS the
    # competitor's name so it slips past the name-in-title gate. The '='
    # prefix pins the match to the domain itself or a subdomain, so «x.com»
    # can never swallow a real host like fox.com.
    '=instagram.com', '=facebook.com', '=fb.com', '=fb.me', '=messenger.com',
    '=tiktok.com', '=twitter.com', '=x.com', '=t.co', '=youtube.com',
    '=youtu.be', '=snapchat.com', '=pinterest.com', '=threads.net',
    '=t.me', '=telegram.me', '=wa.me', '=whatsapp.com', '=linkedin.com',
)
_HOTEL_LISTING_HOST_TOKENS = ('=booking.com',)


def _banned_listing_host_token(host, token):
    if token.startswith('='):
        dom = token[1:]
        return host == dom or host.endswith('.' + dom)
    return token in host


def banned_competitor_listing_host(url, operation=''):
    """True when a URL lives on a banned classifieds/booking portal.

    aqar.fm passes for every operation; Booking.com passes only on hotel rows.
    Foreign-market pages are the separate concern of
    _foreign_market_host — this list is the Saudi-market complement.
    """
    host = _source_host(url)
    if not host:
        return False
    if any(_banned_listing_host_token(host, token)
           for token in _HOTEL_LISTING_HOST_TOKENS):
        op = _fold_choice(operation)
        return 'فندقي' not in op and 'hotel' not in op
    return any(_banned_listing_host_token(host, token)
               for token in _BANNED_LISTING_HOST_TOKENS)


def resolve_source_url_from_citations(url, citations, operation=''):
    """Replace a homepage with the retrieved page the search actually returned.

    The model tends to quote a site's front page from memory even when the figure
    came from a deep page, and the client needs the exact page. When no deeper
    same-host page was retrieved, known indicator portals still resolve to the
    fixed dataset view matching the row's operation.
    """
    value = _norm(url)
    pages = [_norm(item) for item in (citations or []) if _norm(item).startswith(('http://', 'https://'))]
    pages = [item for item in pages if not is_generic_source_homepage(item)]
    if value and not is_generic_source_homepage(value):
        return value
    host = _source_host(value)
    if host:
        same_host = next((item for item in pages if _source_host(item) == host), '')
        if same_host:
            return same_host
    return canonical_index_source_url(value, operation)


def prefer_specific_source_url(*candidates):
    values = [_norm(item) for item in candidates if _norm(item)]
    for value in values:
        if value.startswith(('http://', 'https://')) and not is_generic_source_homepage(value):
            return value
    return next((value for value in values if value.startswith(('http://', 'https://'))), values[0] if values else '')


# Indicator portals whose homepage is a navigation shell: the figures live on a
# fixed dataset page, so a bare-domain citation is normalized to the page that
# actually exposes the row's numbers instead of a shell that shows nothing.
_PORTAL_DATASET_PAGES = {
    'sakani.sa': {
        'default': 'https://sakani.sa/reports-and-data',
    },
}
