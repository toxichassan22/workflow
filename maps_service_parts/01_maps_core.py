

def _assert_allowed_remote_url(url):
    """Validate scheme and host before any server-side request (SSRF guard)."""
    parsed = urlsplit(str(url or '').strip())
    host = (parsed.netloc or '').lower().removeprefix('www.')
    if parsed.scheme != 'https' or not host:
        raise ValueError(f'Blocked non-https remote URL: {url}')
    if not any(host == item or host.endswith('.' + item) for item in _ALLOWED_REMOTE_HOSTS):
        raise ValueError(f'Blocked remote host: {host}')
    return url


def _ensure_path_inside(path, base_dir):
    """Refuse any write target that escapes base_dir (path traversal guard)."""
    target = os.path.abspath(str(path))
    base = os.path.abspath(str(base_dir))
    if os.path.commonpath([base, target]) != base:
        raise ValueError(f'Blocked write target outside maps directory: {path}')
    return target

# Ensure maps directory exists
os.makedirs(MAPS_DIR, exist_ok=True)

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
CITY_LANDMARKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'city_landmarks.json')


def _load_city_landmarks():
    try:
        with open(CITY_LANDMARKS_PATH, 'r', encoding='utf-8') as source:
            data = json.load(source)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as error:
        print(f'[CITY LANDMARKS] failed to load curated data: {error}')
        return {}


CURATED_CITY_LANDMARKS = _load_city_landmarks()


def _is_real_font_file(path):
    if not path or not os.path.isfile(path) or os.path.getsize(path) < 10000:
        return False
    try:
        with open(path, 'rb') as handle:
            header = handle.read(16)
    except OSError:
        return False
    if header.startswith(b'version https://') or header.startswith(b'oid sha'):
        return False
    return header[:4] in {b'\x00\x01\x00\x00', b'OTTO', b'true', b'typ1'}


def bundled_arabic_font_path():
    """Return a real Arabic-capable font for PDF text shaping, never an LFS pointer."""
    candidates = [
        os.path.join(FONTS_DIR, 'arabic-text.bin'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'fonts', 'arabic-text.bin'),
        os.path.join(FONTS_DIR, 'BahijTheSansArabic-Bold.ttf'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'fonts', 'BahijTheSansArabic-Bold.ttf'),
        '/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf',
        '/usr/share/fonts/opentype/noto/NotoNaskhArabic-Bold.ttf',
        '/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf',
        'C:\\Windows\\Fonts\\arial.ttf',
        'C:\\Windows\\Fonts\\tahoma.ttf',
    ]
    for path in candidates:
        if _is_real_font_file(path):
            return path
    return None


def bundled_arabic_overlay_font_path():
    """Return a font with presentation-form glyphs for Pillow map overlays."""
    candidates = [
        os.path.join(FONTS_DIR, 'arabic-overlay.bin'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'fonts', 'arabic-overlay.bin'),
        os.path.join(FONTS_DIR, 'cairo-overlay.bin'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'fonts', 'cairo-overlay.bin'),
        os.path.join(FONTS_DIR, 'arabic-overlay-light.bin'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'fonts', 'arabic-overlay-light.bin'),
        os.path.join(FONTS_DIR, 'arabic-overlay.bin'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'fonts', 'arabic-overlay.bin'),
        os.path.join(FONTS_DIR, 'BahijTheSansArabic-Bold.ttf'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'fonts', 'BahijTheSansArabic-Bold.ttf'),
        'C:\\Windows\\Fonts\\arial.ttf',
        'C:\\Windows\\Fonts\\tahoma.ttf',
    ]
    for path in candidates:
        if _is_real_font_file(path):
            return path
    return bundled_arabic_font_path()


def _strip_arabic_diacritics(text):
    return re.sub(r'[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u08d3-\u08ff\u0640]', '', str(text or ''))


def _get_arabic_font(size=14):
    """Load an Arabic-compatible font for Pillow overlays.

    Layout.BASIC is mandatory: _reshape_arabic_text already produces presentation
    forms in visual order, so a Pillow built with Raqm would re-run bidi and
    reverse the label a second time, which renders the name backwards.
    """
    path = bundled_arabic_overlay_font_path()
    if path:
        try:
            return ImageFont.truetype(path, int(size), layout_engine=ImageFont.Layout.BASIC)
        except Exception as error:
            print(f"[FONT WARN] Failed loading {path}: {error}")
    return ImageFont.load_default()


_ARABIC_RESHAPER = None


def _arabic_reshaper_without_ligatures():
    global _ARABIC_RESHAPER
    if _ARABIC_RESHAPER is not None:
        return _ARABIC_RESHAPER
    import arabic_reshaper
    configuration = {
        key: arabic_reshaper.default_reshaper.configuration.get(key)
        for key in arabic_reshaper.default_reshaper.configuration
    }
    configuration['support_ligatures'] = False
    for key in configuration:
        if key.startswith('arabic ligature'):
            configuration[key] = False
    _ARABIC_RESHAPER = arabic_reshaper.ArabicReshaper(configuration=configuration)
    return _ARABIC_RESHAPER


def _reshape_arabic_text(text):
    """Reshape clean Arabic text for connected RTL display in PIL."""
    if not text:
        return ""
    text_str = _strip_arabic_diacritics(text)
    try:
        # Disable optional presentation ligatures such as lam-alef: some deployed fonts
        # do not contain those compatibility glyphs and render them as square boxes.
        shaped = _arabic_reshaper_without_ligatures().reshape(text_str)
        try:
            from bidi.algorithm import get_display
            return get_display(shaped)
        except Exception as error:
            print(f"[ARABIC BIDI WARN] Ordering failed for '{text_str}': {error}")
            return shaped
    except Exception as e:
        print(f"[ARABIC RESHAPE WARN] Reshaping failed for '{text_str}': {e}")
        return text_str


def shape_arabic_for_drawing(text):
    """Public entry point for renderers that place glyphs themselves (PIL, PyMuPDF)."""
    return _reshape_arabic_text(text)


# Professional satellite map style — sepia/greyscale tone matching reference examples
# Road labels stay on in Arabic; custom overlays use the bundled Arabic presentation-form font.
SATELLITE_WITH_LABELS_STYLES = [
    'feature:all|saturation:-80|lightness:-10',
    'feature:poi|visibility:off',
    'feature:poi.business|visibility:off',
    'feature:transit|visibility:off',
    'feature:administrative|visibility:off',
    # Keep English road labels visible
    'feature:road|element:geometry|visibility:simplified',
    'feature:road.highway|element:labels|visibility:on',
    'feature:road.highway|element:labels.text.fill|color:0xffffff',
    'feature:road.highway|element:labels.text.stroke|color:0x333333|weight:3',
    'feature:road.arterial|element:labels|visibility:on',
    'feature:road.arterial|element:labels.text.fill|color:0xe0e0e0',
    'feature:road.arterial|element:labels.text.stroke|color:0x333333|weight:2',
    'feature:road.local|element:labels|visibility:off',
]

# Satellite without labels — for close-up/site-focused maps
SATELLITE_CLEAN_STYLES = [
    'feature:all|saturation:-80|lightness:-10',
    'feature:poi|visibility:off',
    'feature:poi.business|visibility:off',
    'feature:transit|visibility:off',
    'feature:labels|visibility:off',
    'feature:road|element:labels|visibility:off',
    'feature:administrative|visibility:off',
]

# Wider area map — for landmarks/catchment (lighter, more labels)
SATELLITE_WIDE_STYLES = [
    'feature:all|saturation:-70|lightness:-5',
    'feature:poi|visibility:off',
    'feature:poi.business|visibility:off',
    'feature:transit|visibility:off',
    'feature:administrative.land_parcel|visibility:off',
    'feature:road.highway|element:labels|visibility:on',
    'feature:road.highway|element:labels.text.fill|color:0xffffff',
    'feature:road.highway|element:labels.text.stroke|color:0x444444|weight:3',
    'feature:road.arterial|element:labels|visibility:on',
    'feature:road.arterial|element:labels.text.fill|color:0xdddddd',
    'feature:road.arterial|element:labels.text.stroke|color:0x444444|weight:2',
    'feature:road.local|element:labels|visibility:off',
]

# Professional maroon color palette matching reference examples
MARKER_COLOR_SITE = '#6B1C23'      # Dark maroon for site pin
MARKER_COLOR_LANDMARK = '#8B2020'  # Red-maroon for landmark pins
SITE_FILL_COLOR = (160, 50, 50, 78)     # Keep the building imagery visible beneath the highlight
SITE_BORDER_COLOR = (107, 28, 35, 230)  # Dark maroon border
COMPASS_COLOR = (107, 28, 35)       # Dark maroon for compass
ACCESS_ROADS_RENDER_VERSION = 'v14-draggable-road-labels'
MAP_HIGHLIGHT_RENDER_VERSION = 'survey-polygon-v3'
MAP_LABEL_RENDER_VERSION = 'named-labels-v3-access-context'
ACCESS_ROADMAP_STYLES = [
    'feature:poi|visibility:off',
    'feature:poi.business|visibility:off',
    'feature:transit|visibility:off',
    'feature:administrative.land_parcel|visibility:off',
    'feature:road|element:labels|visibility:off',
    'feature:road.highway|element:labels|visibility:off',
    'feature:road.arterial|element:labels|visibility:off',
    'feature:road.local|element:labels|visibility:off',
]
MAP_REGEN_ZOOM_OFFSETS = (1, -1, 2, -2, 0)
ACCESS_MAP_CONTEXT_RADIUS_KM = 0.6
_MAP_GENERATION_LOCKS = {}
_MAP_GENERATION_LOCKS_GUARD = threading.Lock()

# Rate limiting: max calls per tenant per window (default 60 calls / 10 minutes)
MAPS_RATE_LIMIT = int(os.environ.get('MAPS_RATE_LIMIT', 60))
MAPS_RATE_WINDOW = int(os.environ.get('MAPS_RATE_WINDOW', 600))  # seconds
_maps_call_log = {}  # tenant_id -> list of timestamps


def _record_maps_call(tenant_id):
    """Record a Google Maps API call for rate limiting."""
    now = time.time()
    log = _maps_call_log.setdefault(tenant_id, [])
    cutoff = now - MAPS_RATE_WINDOW
    while log and log[0] < cutoff:
        log.pop(0)
    log.append(now)


def _check_maps_rate_limit(tenant_id):
    """Return error dict if tenant exceeded rate limit, else None."""
    now = time.time()
    log = _maps_call_log.setdefault(tenant_id, [])
    cutoff = now - MAPS_RATE_WINDOW
    while log and log[0] < cutoff:
        log.pop(0)
    if len(log) >= MAPS_RATE_LIMIT:
        return {'error': 'Rate limit exceeded: too many map requests. Please try again later.'}
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Maps spend metering: Google returns no per-call cost, so every billable
# request is counted here with its SKU and a unit price in dollars. Prices are
# the first-tier list prices from the public Maps Platform price list
# (global, updated 2026-09-01) at dollars per billable event, matching the
# SKU ids on the invoice: Directions 28A8-3EB4-4595 at $5.00/1000,
# Distance Matrix Advanced DFAE-763F-CF6E at $10.00/1000 elements,
# Static Maps 3C2D-B525-2E5F at $2.00/1000, Roads Nearest Road at
# $10.00/1000, Dynamic Maps at $7.00/1000 loads (client-reported via
# /api/maps/interactive-load). Free usage caps (10,000 Essentials, 5,000 Pro, 1,000
# Enterprise) and the monthly credit are NOT subtracted: verify prices
# against Cloud Billing and override with the MAPS_SKU_PRICES env var (a JSON
# object mapping SKU names to dollars). The unit price is stored on each row,
# so a later price change never rewrites history. Only completed provider
# requests are recorded: served-from-cache reads and failed calls carry no
# spend. Google free usage caps are intentionally NOT subtracted: the recorded
# cost is the billable figure and any free allowance stays a platform margin.
# ─────────────────────────────────────────────────────────────────────────────
MAPS_SKU_UNIT_PRICES = {
    'geocode': 0.005,
    'staticmap': 0.002,
    'places_text': 0.035,
    'places_nearby': 0.040,
    'distance_matrix': 0.010,
    'directions': 0.005,
    'streetview': 0.007,
    'roads': 0.01,
    'dynamic_map': 0.007,
}
try:
    _maps_price_overrides = json.loads(os.environ.get('MAPS_SKU_PRICES') or '{}')
    if isinstance(_maps_price_overrides, dict):
        for _sku, _price in _maps_price_overrides.items():
            if _sku in MAPS_SKU_UNIT_PRICES:
                MAPS_SKU_UNIT_PRICES[_sku] = float(_price)
except Exception as _price_error:
    print(f"[MAPS USAGE] ignoring invalid MAPS_SKU_PRICES: {_price_error}")

MAPS_USAGE_FLOWS = (
    'overview', 'access', 'catchment', 'landmarks', 'site', 'geocode',
    'places', 'matrix', 'maps', 'other',
)

_maps_usage_local = threading.local()


def maps_usage_ctx(flow, tenant_id=None, draft_id=None, presentation_id=None, data=None):
    """Build the metering context for Maps calls. Unknown ids stay None."""
    if isinstance(data, dict):
        project_data = data.get('projectData')
        if draft_id is None:
            draft_id = data.get('draftId') or data.get('draft_id')
            if draft_id is None and isinstance(project_data, dict):
                draft_id = project_data.get('draftId') or project_data.get('draft_id')
        if presentation_id is None:
            presentation_id = data.get('presentationId') or data.get('presentation_id')
    return {
        'tenant_id': tenant_id,
        'draft_id': draft_id,
        'presentation_id': presentation_id,
        'flow': flow if flow in MAPS_USAGE_FLOWS else 'other',
    }


class maps_usage_scope:
    """Thread-local metering context: every metered call inside the block
    inherits the tenant, draft, presentation and flow unless it carries its
    own explicit context."""

    def __init__(self, ctx):
        self.ctx = dict(ctx) if isinstance(ctx, dict) else {}
        self.previous = None

    def __enter__(self):
        self.previous = getattr(_maps_usage_local, 'ctx', None)
        _maps_usage_local.ctx = self.ctx
        return self.ctx

    def __exit__(self, *exc):
        _maps_usage_local.ctx = self.previous
        return False


def _current_maps_ctx():
    ctx = getattr(_maps_usage_local, 'ctx', None)
    return dict(ctx) if isinstance(ctx, dict) else {}


def _record_maps_usage(usage_ctx, sku, units=1):
    """Persist one billable Google call. Never raises: metering must not break mapping."""
    try:
        ctx = dict(usage_ctx) if isinstance(usage_ctx, dict) else _current_maps_ctx()
        units = max(0, int(units or 0))
        if units <= 0:
            return None
        flow = ctx.get('flow') or 'other'
        if flow not in MAPS_USAGE_FLOWS:
            flow = 'other'
        import db as _db
        try:
            return _db.record_maps_usage_event(
                ctx.get('tenant_id'), sku, units,
                MAPS_SKU_UNIT_PRICES.get(sku, 0.0),
                flow=flow, draft_id=ctx.get('draft_id'),
                presentation_id=ctx.get('presentation_id'),
            )
        except RuntimeError:
            import app as _flask_app
            with _flask_app.app.app_context():
                return _db.record_maps_usage_event(
                    ctx.get('tenant_id'), sku, units,
                    MAPS_SKU_UNIT_PRICES.get(sku, 0.0),
                    flow=flow, draft_id=ctx.get('draft_id'),
                    presentation_id=ctx.get('presentation_id'),
                )
    except Exception as exc:
        print(f"[MAPS USAGE] record failed: {exc}")
        return None


def _get_api_key():
    return os.environ.get('GOOGLE_MAPS_API_KEY', '') or GOOGLE_API_KEY


def _discovery_cache_key(tenant_id, kind, lat=None, lng=None, extra=''):
    """Stable key for one Google discovery answer. None when unkeyable."""
    try:
        lat_part = f"{round(float(lat), 4):.4f}" if lat is not None else '-'
        lng_part = f"{round(float(lng), 4):.4f}" if lng is not None else '-'
    except (TypeError, ValueError):
        return None
    return f"maps:{kind}:{str(tenant_id or 'shared')}:{lat_part}:{lng_part}:{extra}"


def _in_flask_context():
    try:
        from flask import has_app_context
        return bool(has_app_context())
    except Exception:
        return False


def _with_flask_context(func, *args, **kwargs):
    """Run a db helper with a Flask context, borrowing the app in workers."""
    if _in_flask_context():
        return func(*args, **kwargs)
    import app as _flask_app
    with _flask_app.app.app_context():
        return func(*args, **kwargs)


def _discovery_cache_get(tenant_id, cache_key):
    """Cached discovery payload, or None. A hit must skip Google entirely."""
    if not cache_key:
        return None
    try:
        import db as _db
        return _with_flask_context(_db.get_maps_discovery_cache, tenant_id, cache_key)
    except Exception:
        return None


def _discovery_cache_put(tenant_id, cache_key, payload, ttl_days=30):
    """Persist one discovery payload for later runs. Never raises."""
    if not cache_key:
        return False
    try:
        import db as _db
        return bool(_with_flask_context(
            _db.set_maps_discovery_cache, tenant_id, cache_key, payload, ttl_days))
    except Exception:
        return False


def _has_api_key():
    key = _get_api_key()
    return bool(key and key.startswith('AIza'))


def _api_key_error():
    return {
        'success': False,
        'error': 'Google Maps API key not configured',
        'error_code': 'GOOGLE_MAPS_API_KEY_MISSING',
    }


def _distance_meters(lat_a, lng_a, lat_b, lng_b):
    """Great-circle distance used to keep nearby landmarks genuinely nearby."""
    earth_radius_m = 6_371_000
    lat1, lat2 = math.radians(float(lat_a)), math.radians(float(lat_b))
    dlat = lat2 - lat1
    dlng = math.radians(float(lng_b) - float(lng_a))
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * earth_radius_m * math.asin(math.sqrt(a))


def extract_coords_from_maps_link(url):
    """Extract lat/lng from a Google Maps link (shortened or full).
    
    Supports:
    - Short links: https://maps.app.goo.gl/...
    - Full links: https://www.google.com/maps/@lat,lng,zoom
    - Place links: https://www.google.com/maps/place/.../@lat,lng
    - Data links: !3d for lat, !4d for lng
    
    Returns dict with lat, lng on success or None.
    """
    if not url:
        return None
    
    url = requests.utils.unquote(url.strip())
    if not url.startswith('http'):
        return None
    
    # Step 1: Follow shortened links (maps.app.goo.gl). Each hop is validated
    # against the provider allow-list; redirects are followed manually so a
    # link can never bounce the server toward an arbitrary host.
    try:
        host = (urlsplit(url).netloc or '').lower()
        if host.endswith(('maps.app.goo.gl', 'goo.gl', 'maps.google.com')):
            current = url
            for _hop in range(5):
                resp = requests.get(
                    _assert_allowed_remote_url(current), timeout=10,
                    allow_redirects=False, headers={'User-Agent': 'Mozilla/5.0'})
                location = resp.headers.get('Location') if resp.is_redirect or resp.is_permanent_redirect else None
                if not location:
                    break
                current = urljoin(current, location)
            url = current
            print(f"[MAPS LINK] Resolved shortened URL to: {url}")
    except Exception as e:
        print(f"[MAPS LINK] Failed to resolve shortened URL: {e}")
    
    # Step 2: Try to extract coordinates from the resolved URL
    # Pattern 1: !3d(lat)!4d(lng) (exact place coordinates, more reliable than @ map center)
    lat_match = re.search(r'!3d(-?\d+(?:\.\d+)?)', url)
    lng_match = re.search(r'!4d(-?\d+(?:\.\d+)?)', url)
    if lat_match and lng_match:
        return {'lat': float(lat_match.group(1)), 'lng': float(lng_match.group(1))}

    # Pattern 2: /@lat,lng,zoom (map view center, fallback only)
    match = re.search(r'@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)(?:,\d+(?:\.\d+)?z)?', url)
    if match:
        return {'lat': float(match.group(1)), 'lng': float(match.group(2))}
    
    # Pattern 3: q=lat,lng or query=lat,lng (query parameter)
    match = re.search(r'[?&](?:q|query)=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)', url)
    if match:
        return {'lat': float(match.group(1)), 'lng': float(match.group(2))}
    
    # Pattern 4: center=lat,lng (center parameter)
    match = re.search(r'center=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)', url)
    if match:
        return {'lat': float(match.group(1)), 'lng': float(match.group(2))}
    
    # Pattern 5: ll=lat,lng (ll parameter)
    match = re.search(r'll=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)', url)
    if match:
        return {'lat': float(match.group(1)), 'lng': float(match.group(2))}
    
    # Pattern 7: Place name fallback from /maps/place/Place+Name/...
    place_match = re.search(r'/maps/place/([^/@?]+)', url)
    if place_match:
        try:
            place_name = requests.utils.unquote(place_match.group(1).replace('+', ' '))
            if place_name:
                print(f"[MAPS LINK] Attempting geocode for place name from link: {place_name}")
                geo = geocode_address(place_name)
                if geo.get('success'):
                    return {'lat': geo['lat'], 'lng': geo['lng']}
        except Exception as e:
            print(f"[MAPS LINK] Failed place name geocode fallback: {e}")

    print(f"[MAPS LINK] Could not extract coordinates from URL: {url}")
    return None


def geocode_address(address, tenant_id=None, usage_ctx=None):
    """Convert address string to lat/lng using Geocoding API.
    Prefers ROOFTOP precision results when available."""
    if not _has_api_key():
        return _api_key_error()

    if tenant_id:
        limit_error = _check_maps_rate_limit(tenant_id)
        if limit_error:
            return limit_error

    normalized = re.sub(r'\s+', ' ', str(address or '').strip().casefold())
    cache_key = _discovery_cache_key(tenant_id, 'geocode', extra=normalized)
    cached = _discovery_cache_get(tenant_id, cache_key)
    if isinstance(cached, dict) and cached.get('success'):
        return cached

    url = 'https://maps.googleapis.com/maps/api/geocode/json'
    params = {'address': address, 'key': _get_api_key()}
    try:
        response = requests.get(_assert_allowed_remote_url(url), params=params, timeout=15)
        data = response.json()
        if data.get('status') != 'OK':
            return {'error': f"Geocoding API error: {data.get('status')}", 'details': data}

        # Prefer ROOFTOP results for highest precision
        results = data['results']
        rooftop = [r for r in results if r.get('geometry', {}).get('location_type') == 'ROOFTOP']
        result = rooftop[0] if rooftop else results[0]
        loc = result['geometry']['location']
        location_type = result.get('geometry', {}).get('location_type', 'APPROXIMATE')
        viewport = result.get('geometry', {}).get('viewport')
        viewport_polygon = None
        if viewport:
            ne = viewport.get('northeast', {})
            sw = viewport.get('southwest', {})
            if ne and sw:
                viewport_polygon = ';'.join([
                    f"{ne['lat']},{ne['lng']}",
                    f"{sw['lat']},{ne['lng']}",
                    f"{sw['lat']},{sw['lng']}",
                    f"{ne['lat']},{sw['lng']}",
                ])
        if tenant_id:
            _record_maps_call(tenant_id)
        _record_maps_usage(
            usage_ctx or maps_usage_ctx('geocode', tenant_id=tenant_id),
            'geocode', 1)
        resolved = {
            'success': True,
            'lat': loc['lat'],
            'lng': loc['lng'],
            'formatted_address': result.get('formatted_address'),
            'place_id': result.get('place_id'),
            'viewport_polygon': viewport_polygon,
            'location_type': location_type,
            'precision': 'high' if location_type == 'ROOFTOP' else 'medium' if location_type == 'RANGE_INTERPOLATED' else 'low',
        }
        _discovery_cache_put(tenant_id, cache_key, resolved, ttl_days=30)
        return resolved
    except Exception as e:
        return {'error': f"Geocoding request failed: {str(e)}"}


CITY_ALIASES = {
    'جدة': 'جدة', 'jeddah': 'جدة',
    'مكة': 'مكة', 'مكة المكرمة': 'مكة', 'mecca': 'مكة', 'makkah': 'مكة',
    'الرياض': 'الرياض', 'riyadh': 'الرياض',
}
_CURATED_GEOCODE_CACHE = {}


def _normalize_city_name(value):
    normalized = re.sub(r'\s+', ' ', str(value or '').strip().casefold())
    return CITY_ALIASES.get(normalized)


def reverse_geocode_location(lat, lng, tenant_id=None, language='en', usage_ctx=None):
    if not _has_api_key():
        return {}
    cache_key = _discovery_cache_key(tenant_id, 'revgeo', lat, lng, extra=str(language or 'en'))
    cached = _discovery_cache_get(tenant_id, cache_key)
    if isinstance(cached, dict) and cached.get('formatted_address'):
        return cached
    try:
        response = requests.get(
            'https://maps.googleapis.com/maps/api/geocode/json',
            params={'latlng': f'{lat},{lng}', 'key': _get_api_key(), 'language': language, 'region': 'SA'},
            timeout=15,
        )
        payload = response.json()
        if payload.get('status') != 'OK' or not payload.get('results'):
            return {}
        result = payload['results'][0]
        if tenant_id:
            _record_maps_call(tenant_id)
        _record_maps_usage(
            usage_ctx or maps_usage_ctx('geocode', tenant_id=tenant_id),
            'geocode', 1)
        resolved = {
            'formatted_address': result.get('formatted_address', ''),
            'place_id': result.get('place_id'),
            'address_components': result.get('address_components', []),
        }
        if resolved.get('formatted_address'):
            _discovery_cache_put(tenant_id, cache_key, resolved, ttl_days=30)
        return resolved
    except Exception as error:
        print(f'[REVERSE GEOCODE] failed: {error}')
        return {}


def detect_curated_city(lat, lng, tenant_id=None):
    location = reverse_geocode_location(lat, lng, tenant_id=tenant_id, language='en')
    if not location:
        return None
    try:
        candidates = []
        for result in [location]:
            candidates.append(result.get('formatted_address', ''))
            for component in result.get('address_components', []):
                if set(component.get('types', [])) & {'locality', 'postal_town', 'administrative_area_level_2'}:
                    candidates.extend([component.get('long_name', ''), component.get('short_name', '')])
        for candidate in candidates:
            lowered = str(candidate).casefold()
            for alias, canonical in CITY_ALIASES.items():
                if alias in lowered:
                    return canonical
    except Exception as error:
        print(f'[CITY DETECTION] failed: {error}')
    return None


def get_nearest_category_landmarks(lat, lng, radius=20000, tenant_id=None, language='ar'):
    ambient_ctx = _current_maps_ctx()
    language = _lang_norm(language)
    places = get_nearby_landmarks(
        lat,
        lng,
        radius=radius,
        max_results=20,
        include_all=True,
        included_types=['shopping_mall', 'university', 'hospital'],
        usage_ctx=ambient_ctx or maps_usage_ctx('places', tenant_id=tenant_id),
        language=language,
    )
    if not places.get('success'):
        return []
    category_specs = (
        ('shopping_mall', 'Shopping' if language == 'en' else 'التسوق'),
        ('university', 'Education' if language == 'en' else 'التعليم'),
        ('hospital', 'Health' if language == 'en' else 'الصحة'),
    )
    selected = []
    seen_categories = set()
    for place in places.get('landmarks', []):
        types = set(place.get('types') or [])
        matched = next(((type_name, label) for type_name, label in category_specs if type_name in types), None)
        if not matched or matched[0] in seen_categories:
            continue
        seen_categories.add(matched[0])
        selected.append({
            **place,
            'category': matched[1],
            'source': 'nearest_category',
        })
    matrix = get_drive_matrix(
        (lat, lng), selected,
        usage_ctx=ambient_ctx or maps_usage_ctx('matrix', tenant_id=tenant_id),
        language=language) if selected else []
    for index, item in enumerate(selected):
        if index >= len(matrix) or not isinstance(matrix[index], dict):
            continue
        item['distance_km'] = matrix[index].get('distance_km')
        item['distance_text'] = matrix[index].get('distance_text')
        item['duration_minutes'] = matrix[index].get('duration_min')
    return selected


# English labels for the curated city_landmarks.json categories — the catalog is
# Arabic-keyed, so English decks map each label instead of carrying Arabic words
# into the catchment table.
_CURATED_CATEGORY_EN = {
    'النقل': 'Transport',
    'النقل العام': 'Public transit',
    'المحاور': 'Main corridor',
    'الواجهة البحرية': 'Waterfront',
    'التطوير المستقبلي': 'Future development',
    'التراث والسياحة': 'Heritage & tourism',
    'الأعمال واللوجستيات': 'Business & logistics',
    'الترفيه': 'Leisure',
    'الرياضة والفعاليات': 'Sports & events',
    'الفعاليات': 'Events',
    'المناطق الساحلية': 'Coastal areas',
    'التسوق': 'Shopping',
    'التعليم': 'Education',
    'الصحة': 'Health',
    'ديني ومركزي': 'Religious & central',
    'ديني': 'Religious',
    'المشاعر': 'Holy sites',
    'المشاريع الكبرى': 'Major projects',
    'السياحة الدينية': 'Religious tourism',
    'الأعمال والمال': 'Business & finance',
    'الأعمال والتقنية': 'Business & tech',
    'الأعمال والحكومة': 'Business & government',
    'مركز المدينة': 'City center',
    'السياحة والمعالم': 'Tourism & landmarks',
    'المعارض والفعاليات': 'Exhibitions & events',
    'الطبيعة والترفيه': 'Nature & leisure',
    'اللوجستيات': 'Logistics',
    'الصناعة واللوجستيات': 'Industry & logistics',
    'معلم رئيسي': 'Major landmark',
}


def get_curated_city_landmarks(city, lat, lng, tenant_id=None, language='ar'):
    language = _lang_norm(language)
    entries = CURATED_CITY_LANDMARKS.get(city, [])
    if not entries:
        return []
    landmarks = []
    seen = set()
    entries_to_resolve = []
    for entry in entries:
        name = str(entry.get('name') or '').strip()
        lowered_name = name.casefold()
        if any(marker in lowered_name for marker in ('أقرب مركز تجاري', 'أقرب جامعة', 'أقرب مستشفى')):
            continue
        if not name or lowered_name in seen:
            continue
        seen.add(lowered_name)
        entries_to_resolve.append((name, entry))

    ambient_ctx = _current_maps_ctx()

    def resolve_entry(item):
        name, entry = item
        cache_key = (city, name.casefold(), language)
        geo = _CURATED_GEOCODE_CACHE.get(cache_key)
        if geo is None:
            geo = geocode_address(f'{name}, {city}, Saudi Arabia', tenant_id=tenant_id,
                                  usage_ctx=ambient_ctx)
            if geo.get('success') and (language == 'en' or is_road_name(name)):
                # Google's own English display name for the landmark — the deck
                # then carries "King Abdulaziz International Airport" rather
                # than the Arabic curated label. Roads run this check in every
                # language too: the geocoder's single point can sit at a remote
                # endpoint, while the Places candidate nearest the site is the
                # stretch this map means.
                place = find_place_near(name, lat, lng, radius_m=80000, language=language,
                                        usage_ctx=ambient_ctx)
                if place and place.get('name'):
                    geo = dict(geo)
                    if language == 'en':
                        geo['localized_name'] = place['name']
                    if place.get('lat') is not None and place.get('lng') is not None:
                        geo['lat'] = place['lat']
                        geo['lng'] = place['lng']
            if geo.get('success'):
                _CURATED_GEOCODE_CACHE[cache_key] = geo
        if not geo.get('success'):
            return None
        category = entry.get('category') or 'معلم رئيسي'
        if language == 'en':
            category = _CURATED_CATEGORY_EN.get(category, 'Major landmark')
        return {
            'name': geo.get('localized_name') or name,
            'category': category,
            'lat': geo.get('lat'),
            'lng': geo.get('lng'),
            'types': [],
            'source': 'curated',
            'city': city,
        }

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        resolved_entries = list(executor.map(resolve_entry, entries_to_resolve))
    for item in resolved_entries:
        if not item or item.get('lat') is None or item.get('lng') is None:
            continue
        item['distance_meters'] = round(_distance_meters(lat, lng, item['lat'], item['lng']))
        landmarks.append(item)
    for item in get_nearest_category_landmarks(lat, lng, radius=20000, tenant_id=tenant_id, language=language):
        key = item.get('name', '').casefold()
        if key in seen:
            continue
        seen.add(key)
        landmarks.append(item)
    destinations = [item for item in landmarks if item.get('lat') is not None and item.get('lng') is not None]
    matrix = get_drive_matrix((lat, lng), destinations, language=language) if destinations else []
    for index, item in enumerate(destinations):
        if index >= len(matrix):
            break
        entry = matrix[index]
        item['distance_km'] = entry.get('distance_km')
        item['distance_text'] = entry.get('distance_text')
        item['duration_minutes'] = entry.get('duration_min')
    return landmarks


def _download_image(url, params, output_path):
    """Download image from Google Maps Static API and save to disk."""
    try:
        _assert_allowed_remote_url(url)
        target = _ensure_path_inside(output_path, MAPS_DIR)
        response = requests.get(url, params=params, timeout=30)
        if response.status_code != 200:
            return {'error': f"Image request failed: HTTP {response.status_code}", 'content': response.text[:200]}
        with open(target, 'wb') as f:
            f.write(response.content)
        return {'success': True, 'path': target, 'size': len(response.content)}
    except Exception as e:
        return {'error': f"Image download failed: {str(e)}"}


def _map_cache_path(lat, lng, maptype, zoom, markers=None, paths=None, size=None, styles=None, language='ar'):
    """Deterministic cache path for a raw static map.

    Every parameter that changes the rendered pixels must be part of the key,
    otherwise different maps (overview/landmarks/access/catchment) at the same
    coordinates would collide and reuse each other's image. Language changes the
    provider's baked tile labels, so it is part of the key too.
    """
    raw = json.dumps(
        [lat, lng, maptype, zoom, markers, paths, size, styles, _lang_norm(language), STATIC_MAP_FRAME_VERSION],
        ensure_ascii=False, sort_keys=True, default=str
    )
    key = hashlib.md5(raw.encode('utf-8')).hexdigest()
    return os.path.join(MAPS_DIR, f"map_{key}.png")


def get_static_map(lat, lng, zoom=14, markers=None, paths=None, size=(1280, 720), output_path=None,
                   maptype='satellite', styles=None, use_google_markers=False, language='ar',
                   bypass_cache=False, usage_ctx=None):
    """Generate a static map image with optional markers and paths (cached by lat,lng,maptype,zoom)."""
    if not _has_api_key():
        return _api_key_error()
    try:
        size = tuple(map(int, size))
        provider_zoom = int(zoom)
        if len(size) != 2 or not all(1 <= dimension <= 2048 for dimension in size) or not 0 <= provider_zoom <= 20:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return {'success': False, 'error': 'Invalid static map frame'}
    factor = 1
    while max(size) > 640 * factor:
        factor *= 2
        provider_zoom -= 1
    if provider_zoom < 0:
        return {'success': False, 'error': 'Invalid static map frame'}
    provider_size = tuple(math.ceil(dimension / factor) for dimension in size)

    language = _lang_norm(language)
    chosen_styles = styles or SATELLITE_WITH_LABELS_STYLES
    cache_markers = markers if use_google_markers else None
    cache_path = _map_cache_path(lat, lng, maptype, zoom, cache_markers, paths, size, chosen_styles, language=language)
    if output_path is None:
        output_path = cache_path

    # Re-use cached raw map image if available
    if not bypass_cache and os.path.exists(cache_path) and _static_map_image_matches(cache_path, size):
        if output_path != cache_path:
            shutil.copyfile(cache_path, output_path)
        return {'success': True, 'path': output_path, 'size': os.path.getsize(output_path), 'cached': True}

    url = 'https://maps.googleapis.com/maps/api/staticmap'
    params = {
        'center': f"{lat},{lng}",
        'zoom': provider_zoom,
        'size': f"{provider_size[0]}x{provider_size[1]}",
        'maptype': maptype,
        'key': _get_api_key(),
        'scale': 2,
        'language': language,
    }

    params['style'] = chosen_styles

    if markers and use_google_markers:
        params['markers'] = markers
    if paths:
        params['path'] = paths

    res = _download_image(url, params, cache_path)
    if not res.get('success'):
        return res
    _record_maps_usage(usage_ctx, 'staticmap', 1)
    if not _prepare_static_map_image(cache_path, provider_size, factor, size):
        return {'success': False, 'error': 'Static map image does not match the requested frame'}
    if output_path != cache_path:
        shutil.copyfile(cache_path, output_path)
    return {'success': True, 'path': output_path, 'size': os.path.getsize(output_path), 'cached': False}


def _latlng_to_pixel_offset(lat, lng, center_lat, center_lng, zoom, scale=2):
    """Convert lat/lng to pixel offset from image center for a static map using exact Web Mercator projection."""
    world_width = 256 * (2 ** zoom) * scale
    x_offset = (lng - center_lng) * world_width / 360.0

    lat_rad = math.radians(lat)
    center_lat_rad = math.radians(center_lat)
    # Exact Web Mercator formula for vertical pixel displacement
    y_lat = math.log(math.tan(math.pi / 4.0 + lat_rad / 2.0))
    y_center = math.log(math.tan(math.pi / 4.0 + center_lat_rad / 2.0))
    y_offset = -(y_lat - y_center) * (world_width / (2.0 * math.pi))

    return x_offset, y_offset


def _pixel_to_latlng(px, py, image_width, image_height, center_lat, center_lng, zoom, scale=2):
    world = 256 * (2 ** zoom) * scale
    center_x = (center_lng + 180.0) / 360.0 * world
    center_lat_rad = math.radians(center_lat)
    center_y = (1.0 - math.log(math.tan(math.pi / 4.0 + center_lat_rad / 2.0)) / math.pi) / 2.0 * world
    target_x = center_x + px - image_width / 2
    target_y = center_y + py - image_height / 2
    lng = target_x / world * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * target_y / world))))
    return lat, lng
