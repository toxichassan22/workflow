"""
Google Maps service for generating map images and location data.
Uses direct HTTP requests to Google Maps APIs.
"""

import sys
import os
import json
import math
import uuid
import time
import requests
import re
import hashlib
import shutil
import threading
from urllib.parse import urlparse

# Force UTF-8 stdout so Arabic/unicode OSM tag names don't crash on Windows cp1252
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from datetime import datetime
from urllib.parse import urlencode

from PIL import Image, ImageDraw, ImageFont

GOOGLE_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
MAPS_DIR = os.path.join(os.path.dirname(__file__), 'uploads', 'maps')

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
LANDMARKS_MAX_RADIUS_KM = 8.0
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


def _get_api_key():
    return os.environ.get('GOOGLE_MAPS_API_KEY', '') or GOOGLE_API_KEY


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
    
    # Step 1: Follow shortened links (maps.app.goo.gl)
    try:
        if 'maps.app.goo.gl' in url or 'goo.gl/maps' in url or 'maps.google.com' in url:
            resp = requests.get(url, timeout=10, allow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'})
            url = resp.url
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


def geocode_address(address, tenant_id=None):
    """Convert address string to lat/lng using Geocoding API.
    Prefers ROOFTOP precision results when available."""
    if not _has_api_key():
        return _api_key_error()

    if tenant_id:
        limit_error = _check_maps_rate_limit(tenant_id)
        if limit_error:
            return limit_error

    url = 'https://maps.googleapis.com/maps/api/geocode/json'
    params = {'address': address, 'key': _get_api_key()}
    try:
        response = requests.get(url, params=params, timeout=15)
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
        return {
            'success': True,
            'lat': loc['lat'],
            'lng': loc['lng'],
            'formatted_address': result.get('formatted_address'),
            'place_id': result.get('place_id'),
            'viewport_polygon': viewport_polygon,
            'location_type': location_type,
            'precision': 'high' if location_type == 'ROOFTOP' else 'medium' if location_type == 'RANGE_INTERPOLATED' else 'low',
        }
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


def reverse_geocode_location(lat, lng, tenant_id=None, language='en'):
    if not _has_api_key():
        return {}
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
        return {
            'formatted_address': result.get('formatted_address', ''),
            'place_id': result.get('place_id'),
            'address_components': result.get('address_components', []),
        }
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


def get_nearest_category_landmarks(lat, lng, radius=20000, tenant_id=None):
    places = get_nearby_landmarks(
        lat,
        lng,
        radius=radius,
        max_results=20,
        include_all=True,
        included_types=['shopping_mall', 'university', 'hospital'],
    )
    if not places.get('success'):
        return []
    category_specs = (
        ('shopping_mall', 'التسوق'),
        ('university', 'التعليم'),
        ('hospital', 'الصحة'),
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
    matrix = get_drive_matrix((lat, lng), selected) if selected else []
    for index, item in enumerate(selected):
        if index >= len(matrix) or not isinstance(matrix[index], dict):
            continue
        item['distance_km'] = matrix[index].get('distance_km')
        item['distance_text'] = matrix[index].get('distance_text')
        item['duration_minutes'] = matrix[index].get('duration_min')
    return selected


def get_curated_city_landmarks(city, lat, lng, tenant_id=None):
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

    def resolve_entry(item):
        name, entry = item
        cache_key = (city, name.casefold())
        geo = _CURATED_GEOCODE_CACHE.get(cache_key)
        if geo is None:
            geo = geocode_address(f'{name}, {city}, Saudi Arabia', tenant_id=tenant_id)
            if geo.get('success'):
                _CURATED_GEOCODE_CACHE[cache_key] = geo
        if not geo.get('success'):
            return None
        return {
            'name': name,
            'category': entry.get('category') or 'معلم رئيسي',
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
    for item in get_nearest_category_landmarks(lat, lng, radius=20000, tenant_id=tenant_id):
        key = item.get('name', '').casefold()
        if key in seen:
            continue
        seen.add(key)
        landmarks.append(item)
    destinations = [item for item in landmarks if item.get('lat') is not None and item.get('lng') is not None]
    matrix = get_drive_matrix((lat, lng), destinations) if destinations else []
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
        response = requests.get(url, params=params, timeout=30)
        if response.status_code != 200:
            return {'error': f"Image request failed: HTTP {response.status_code}", 'content': response.text[:200]}
        with open(output_path, 'wb') as f:
            f.write(response.content)
        return {'success': True, 'path': output_path, 'size': len(response.content)}
    except Exception as e:
        return {'error': f"Image download failed: {str(e)}"}


def _map_cache_path(lat, lng, maptype, zoom, markers=None, paths=None, size=None, styles=None):
    """Deterministic cache path for a raw static map.

    Every parameter that changes the rendered pixels must be part of the key,
    otherwise different maps (overview/landmarks/access/catchment) at the same
    coordinates would collide and reuse each other's image.
    """
    raw = json.dumps(
        [lat, lng, maptype, zoom, markers, paths, size, styles],
        ensure_ascii=False, sort_keys=True, default=str
    )
    key = hashlib.md5(raw.encode('utf-8')).hexdigest()
    return os.path.join(MAPS_DIR, f"map_{key}.png")


def get_static_map(lat, lng, zoom=14, markers=None, paths=None, size=(1280, 720), output_path=None,
                   maptype='satellite', styles=None, use_google_markers=False, language='ar',
                   bypass_cache=False):
    """Generate a static map image with optional markers and paths (cached by lat,lng,maptype,zoom)."""
    if not _has_api_key():
        return _api_key_error()

    chosen_styles = styles or SATELLITE_WITH_LABELS_STYLES
    cache_markers = markers if use_google_markers else None
    cache_path = _map_cache_path(lat, lng, maptype, zoom, cache_markers, paths, size, chosen_styles)
    if output_path is None:
        output_path = cache_path

    # Re-use cached raw map image if available
    if not bypass_cache and os.path.exists(cache_path):
        if output_path != cache_path:
            shutil.copyfile(cache_path, output_path)
        return {'success': True, 'path': output_path, 'size': os.path.getsize(output_path), 'cached': True}

    url = 'https://maps.googleapis.com/maps/api/staticmap'
    params = {
        'center': f"{lat},{lng}",
        'zoom': zoom,
        'size': f"{size[0]}x{size[1]}",
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


def _draw_pin_marker(color='#6B1C23', label=None, size=44, is_site=False, label_text=None):
    """Generate a high-quality, anti-aliased pin marker Image using high-res rendering and Lanczos downscaling."""
    canvas_size = size * 6
    canvas = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    
    ccx = canvas_size // 2
    _r, _g, _b = _parse_color(color)
    
    if is_site:
        pin_r = (size // 3) * 4
        tri_h = pin_r
        ccy = canvas_size - 20 - pin_r - tri_h
        
        # Drop shadow
        shadow_w = pin_r
        shadow_h = pin_r // 3
        draw.ellipse([ccx - shadow_w, canvas_size - 25 - shadow_h, ccx + shadow_w, canvas_size - 25], fill=(0, 0, 0, 50))
                     
        # Triangle pointer
        draw.polygon([(ccx - pin_r // 2, ccy + pin_r - 8),
                      (ccx + pin_r // 2, ccy + pin_r - 8),
                      (ccx, ccy + pin_r + tri_h)], fill=color)
                      
        # Outer white border
        border_w = 8
        draw.ellipse([ccx - pin_r - border_w, ccy - pin_r - border_w,
                      ccx + pin_r + border_w, ccy + pin_r + border_w], fill='#FFFFFF')
                      
        # Main circle body
        draw.ellipse([ccx - pin_r, ccy - pin_r, ccx + pin_r, ccy + pin_r], fill=color)
        
        # Inner white inverted triangle
        inner_size = pin_r // 2
        draw.polygon([(ccx - inner_size, ccy - inner_size // 2 - 8),
                      (ccx + inner_size, ccy - inner_size // 2 - 8),
                      (ccx, ccy + inner_size // 2 - 8)], fill='#FFFFFF')
                      
        if label_text:
            font = _get_arabic_font(60)
            shaped_label = _reshape_arabic_text(label_text)
            bbox = draw.textbbox((0, 0), shaped_label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = ccx - tw // 2
            ty = ccy + pin_r + tri_h + 10
            pad = 20
            draw.rounded_rectangle([tx - pad, ty - 8, tx + tw + pad, ty + th + 12], radius=16, fill=color)
            draw.text((tx, ty), shaped_label, fill='#FFFFFF', font=font)
    else:
        pin_r = (size // 4) * 4
        tri_h = (pin_r * 2) // 3
        ccy = canvas_size - 20 - pin_r - tri_h
        
        # Drop shadow
        shadow_w = pin_r
        shadow_h = pin_r // 3
        draw.ellipse([ccx - shadow_w, canvas_size - 25 - shadow_h, ccx + shadow_w, canvas_size - 25], fill=(0, 0, 0, 50))
                     
        # Triangle pointer
        draw.polygon([(ccx - pin_r // 2, ccy + pin_r - 8),
                      (ccx + pin_r // 2, ccy + pin_r - 8),
                      (ccx, ccy + pin_r + tri_h)], fill=color)
                      
        # Outer white border
        border_w = 6
        draw.ellipse([ccx - pin_r - border_w, ccy - pin_r - border_w,
                      ccx + pin_r + border_w, ccy + pin_r + border_w], fill='#FFFFFF')
                      
        # Main circle body
        draw.ellipse([ccx - pin_r, ccy - pin_r, ccx + pin_r, ccy + pin_r], fill=color)
        
        if label:
            font = _get_arabic_font(int(pin_r * 1.1))
            bbox = draw.textbbox((0, 0), str(label), font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = ccx - tw // 2
            ty = ccy - th // 2 - 8
            draw.text((tx, ty), str(label), fill='#FFFFFF', font=font)
            
    resized = canvas.resize((size, size), Image.Resampling.LANCZOS)
    return resized


def _parse_color(color):
    """Parse hex color string to (r, g, b) tuple."""
    color = color.lstrip('#')
    try:
        return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    except Exception:
        return 192, 57, 43


def _apply_map_overlay(image_path, dark_factor=0.35, gradient=True):
    """Apply a dark overlay/gradient to a map image for better text readability."""
    try:
        img = Image.open(image_path).convert('RGBA')
        width, height = img.size
        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        if gradient:
            # Dark gradient from bottom to middle
            for i in range(height // 2):
                alpha = int(dark_factor * 255 * (1 - i / (height / 2)) * 0.7)
                draw.line([(0, height - i - 1), (width, height - i - 1)], fill=(0, 0, 0, alpha))
            # Slight darkening on top-right for cards area
            for i in range(height // 3):
                alpha = int(dark_factor * 255 * (1 - i / (height / 3)) * 0.25)
                draw.line([(0, i), (width, i)], fill=(0, 0, 0, alpha))
        else:
            draw.rectangle([0, 0, width, height], fill=(0, 0, 0, int(dark_factor * 255)))
        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[MAP OVERLAY ERROR] {e}")
        return False


def _draw_marker_name_label(draw, px, anchor_y, text, img_w, img_h, occupied, preferred_point=None):
    clean_text = _strip_arabic_diacritics(str(text or '').strip())
    if not clean_text:
        return None

    max_text_width = min(360, max(180, img_w - 48))
    font = None
    shaped_text = ''
    text_bbox = None
    for font_size in (22, 20, 18, 16, 14):
        candidate_font = _get_arabic_font(font_size)
        candidate_text = _reshape_arabic_text(clean_text)
        candidate_bbox = draw.textbbox((0, 0), candidate_text, font=candidate_font)
        if candidate_bbox[2] - candidate_bbox[0] <= max_text_width:
            font = candidate_font
            shaped_text = candidate_text
            text_bbox = candidate_bbox
            break
    if font is None:
        font = _get_arabic_font(14)
        shaped_text = _reshape_arabic_text(clean_text)
        text_bbox = draw.textbbox((0, 0), shaped_text, font=font)

    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    pad_x = 12
    pad_y = 7
    label_width = text_width + pad_x * 2
    label_height = text_height + pad_y * 2
    candidates = [
        (px - label_width / 2, anchor_y + 12),
        (px - label_width / 2, anchor_y - label_height - 52),
        (px + 52, anchor_y - label_height / 2),
        (px - label_width - 52, anchor_y - label_height / 2),
        (px + 52, anchor_y + 42),
        (px - label_width - 52, anchor_y + 42),
        (px + 52, anchor_y - label_height - 64),
        (px - label_width - 52, anchor_y - label_height - 64),
    ]
    rect = None
    if preferred_point:
        left = max(8, min(img_w - label_width - 8, preferred_point[0] - label_width / 2))
        top = max(8, min(img_h - label_height - 8, preferred_point[1] - label_height / 2))
        rect = (left, top, left + label_width, top + label_height)
    else:
        for left, top in candidates:
            left = max(8, min(img_w - label_width - 8, left))
            top = max(8, min(img_h - label_height - 8, top))
            candidate_rect = (left, top, left + label_width, top + label_height)
            if not any(
                not (candidate_rect[2] < other[0] or candidate_rect[0] > other[2]
                     or candidate_rect[3] < other[1] or candidate_rect[1] > other[3])
                for other in occupied
            ):
                rect = candidate_rect
                break
    if rect is None:
        for distance in (90, 140, 200, 270):
            for angle in range(0, 360, 45):
                radians = math.radians(angle)
                left = max(8, min(img_w - label_width - 8, px + math.cos(radians) * distance - label_width / 2))
                top = max(8, min(img_h - label_height - 8, anchor_y + math.sin(radians) * distance - label_height / 2))
                candidate_rect = (left, top, left + label_width, top + label_height)
                if not any(
                    not (candidate_rect[2] < other[0] or candidate_rect[0] > other[2]
                         or candidate_rect[3] < other[1] or candidate_rect[1] > other[3])
                    for other in occupied
                ):
                    rect = candidate_rect
                    break
            if rect is not None:
                break
    if rect is None:
        left = max(8, min(img_w - label_width - 8, px - label_width / 2))
        top = max(8, min(img_h - label_height - 8, anchor_y + 12))
        rect = (left, top, left + label_width, top + label_height)

    left, top, right, bottom = [int(round(value)) for value in rect]
    draw.rounded_rectangle(
        [left, top, right, bottom],
        radius=8,
        fill=(37, 75, 102, 245),
        outline=(240, 230, 210, 255),
        width=2,
    )
    draw.text(
        (left + pad_x - text_bbox[0], top + pad_y - text_bbox[1]),
        shaped_text,
        fill='#FFFFFF',
        font=font,
    )
    occupied.append((left, top, right, bottom))
    return ((left + right) / 2, (top + bottom) / 2)


def _overlay_markers(image_path, center_lat, center_lng, zoom, markers_list, size=(1280, 720), scale=2):
    """
    Overlay custom markers on a map image.
    markers_list: list of dicts with keys: lat, lng, color, label, name, type ('site' or 'landmark')
    """
    try:
        img = Image.open(image_path).convert('RGBA')
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        img_w, img_h = img.size
        center_x, center_y = img_w // 2, img_h // 2
        rendered_markers = []
        occupied_labels = []
        for m in markers_list:
            m_lat = m.get('lat')
            m_lng = m.get('lng')
            if m_lat is None or m_lng is None:
                continue
            dx, dy = _latlng_to_pixel_offset(m_lat, m_lng, center_lat, center_lng, zoom, scale=scale)
            px = center_x + dx
            py = center_y + dy
            if 0 <= px <= img_w and 0 <= py <= img_h:
                color = m.get('color', '#C0392B')
                label = m.get('label')
                name = m.get('name') or m.get('label_text')
                is_site = m.get('type') == 'site'
                pin_size = 120 if is_site else 72
                pin_img = _draw_pin_marker(color=color, label=label, size=pin_size, is_site=is_site)

                px_paste = int(px - pin_size // 2)
                py_paste = int(py - pin_size)
                overlay.paste(pin_img, (px_paste, py_paste), pin_img)
                occupied_labels.append((px_paste, py_paste, px_paste + pin_size, py_paste + pin_size))
                rendered_markers.append((px, py_paste, name, is_site))

        for px, py_paste, name, is_site in rendered_markers:
            if name and not is_site:
                _draw_marker_name_label(draw, px, py_paste, name, img_w, img_h, occupied_labels)
        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[MAP MARKERS ERROR] {e}")
        return False


def _draw_catchment_markers(image_path, center_lat, center_lng, zoom, landmarks, label_positions=None, scale=2,
                            site_lat=None, site_lng=None):
    try:
        img = Image.open(image_path).convert('RGBA')
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        img_w, img_h = img.size
        center_x, center_y = img_w // 2, img_h // 2
        positions = label_positions or {}
        if isinstance(positions, str):
            try:
                positions = json.loads(positions)
            except (TypeError, ValueError):
                positions = {}
        marker_items = _build_markers(
            site_lat if site_lat is not None else center_lat,
            site_lng if site_lng is not None else center_lng,
            landmarks,
        )
        occupied = []
        rendered = []
        for marker in marker_items:
            marker_lat = marker.get('lat')
            marker_lng = marker.get('lng')
            if marker_lat is None or marker_lng is None:
                continue
            dx, dy = _latlng_to_pixel_offset(marker_lat, marker_lng, center_lat, center_lng, zoom, scale=scale)
            px = center_x + dx
            py = center_y + dy
            if not (0 <= px <= img_w and 0 <= py <= img_h):
                continue
            is_site = marker.get('type') == 'site'
            pin_size = 120 if is_site else 72
            pin = _draw_pin_marker(
                color=marker.get('color', MARKER_COLOR_LANDMARK),
                label=marker.get('label'),
                size=pin_size,
                is_site=is_site,
            )
            left = int(px - pin_size // 2)
            top = int(py - pin_size)
            overlay.paste(pin, (left, top), pin)
            occupied.append((left, top, left + pin_size, top + pin_size))
            if is_site or not marker.get('name'):
                continue
            preferred = positions.get(marker['name']) if isinstance(positions, dict) else None
            preferred_point = None
            if isinstance(preferred, (list, tuple)) and len(preferred) >= 2:
                try:
                    label_dx, label_dy = _latlng_to_pixel_offset(
                        float(preferred[0]), float(preferred[1]), center_lat, center_lng, zoom, scale=scale
                    )
                    preferred_point = (center_x + label_dx, center_y + label_dy)
                except (TypeError, ValueError):
                    preferred_point = None
            label_pixel = _draw_marker_name_label(
                draw, px, py, marker['name'], img_w, img_h, occupied, preferred_point=preferred_point
            )
            item = next((dict(value) for value in landmarks if value.get('name') == marker['name']), {'name': marker['name']})
            if label_pixel:
                item['label_point'] = list(_pixel_to_latlng(
                    label_pixel[0], label_pixel[1], img_w, img_h, center_lat, center_lng, zoom, scale=scale
                ))
            rendered.append(item)
        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        return rendered
    except Exception as error:
        print(f'[CATCHMENT MARKERS ERROR] {error}')
        return []


def classify_landmark_category(types):
    types = set(types or [])
    categories = (
        ('ترفيهي', {'amusement_park', 'aquarium', 'zoo', 'park', 'garden', 'sports_complex', 'golf_course', 'swimming_pool', 'movie_theater', 'performing_arts_theater', 'concert_hall', 'event_venue'}),
        ('تعليمي', {'school', 'university', 'library', 'preschool', 'primary_school', 'secondary_school'}),
        ('صحي', {'hospital', 'doctor', 'dentist', 'pharmacy', 'veterinary_care'}),
        ('تجاري', {'shopping_mall', 'department_store', 'supermarket', 'market', 'store'}),
        ('ديني', {'mosque', 'church', 'hindu_temple', 'synagogue', 'place_of_worship'}),
        ('ثقافي/سياحي', {'tourist_attraction', 'landmark', 'historical_landmark', 'museum', 'art_gallery'}),
        ('حكومي/خدمي', {'city_hall', 'government_office', 'embassy', 'police', 'fire_station'}),
    )
    for label, matched_types in categories:
        if types & matched_types:
            return label
    return 'اجتماعي/خدمي'


def find_place_near(name, lat, lng, radius_m=20000, language='ar'):
    """Locate a named landmark around the site with Places text search.

    Geocoding a landmark name together with the project address returns the *address*,
    so every named landmark landed on the site itself and was then dropped as a duplicate.
    A text search with a location bias resolves the place instead.
    """
    query = str(name or '').strip()
    if not query or not _has_api_key():
        return None
    try:
        response = requests.post(
            'https://places.googleapis.com/v1/places:searchText',
            headers={
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': _get_api_key(),
                'X-Goog-FieldMask': 'places.displayName,places.location,places.formattedAddress',
            },
            json={
                'textQuery': query,
                'languageCode': language,
                'maxResultCount': 1,
                'locationBias': {
                    'circle': {
                        'center': {'latitude': float(lat), 'longitude': float(lng)},
                        'radius': float(radius_m),
                    }
                },
            },
            timeout=15,
        )
        data = response.json() if response.content else {}
        if response.status_code >= 400:
            print(f"[PLACES TEXT] {query}: {(data.get('error') or {}).get('message', response.status_code)}")
            return None
        places = data.get('places') or []
        if not places:
            return None
        location = (places[0] or {}).get('location') or {}
        latitude, longitude = location.get('latitude'), location.get('longitude')
        if latitude is None or longitude is None:
            return None
        return {
            'lat': float(latitude),
            'lng': float(longitude),
            'name': ((places[0].get('displayName') or {}).get('text') or query),
        }
    except Exception as error:
        print(f'[PLACES TEXT ERROR] {query}: {error}')
        return None


def get_nearby_landmarks(lat, lng, radius=1500, keyword=None, max_results=8, include_all=False, included_types=None):
    """Find nearby landmarks using Places API (New).
    Filters out irrelevant place types like gas stations, parking, ATMs, etc."""
    if not _has_api_key():
        return _api_key_error()
    IRRELEVANT_TYPES = {
        'gas_station', 'parking', 'atm', 'bank', 'post_office', 'courier',
        'laundry', 'dry_cleaning', 'hair_care', 'beauty_salon', 'barber_shop',
        'car_wash', 'car_repair', 'car_dealer', 'tire_shop', 'storage',
        'self_storage_laundry', 'electric_vehicle_charging_station',
        'convenience_store', 'supermarket', 'grocery_store', 'bakery',
        'florist', 'hardware_store', 'furniture_store', 'clothing_store',
        'shoe_store', 'jewelry_store', 'pet_store', 'book_store',
        'electronics_store', 'home_goods_store', 'department_store',
        'discount_store', 'dollar_store', 'liquor_store', 'tobacco_shop',
        'meal_takeaway', 'meal_delivery', 'food_delivery', 'restaurant',
        'cafe', 'bar', 'night_club',
        'travel_agency', 'car_rental',
        'bus_stop', 'subway_station', 'transit_station', 'light_rail_station',
        'train_station', 'taxi_stand',
        'pharmacy', 'doctor', 'dentist', 'veterinary_care',
        'plumber', 'electrician', 'roofing_contractor', 'general_contractor',
        'real_estate_agency', 'insurance_agency', 'accounting', 'lawyer',
        'notary_public', 'post_box', 'public_phone',
    }

    PREFERRED_TYPES = {
        'school', 'university', 'hospital', 'shopping_mall', 'stadium',
        'mosque', 'church', 'hindu_temple', 'synagogue', 'place_of_worship',
        'city_hall', 'embassy', 'museum', 'library', 'art_gallery',
        'amusement_park', 'aquarium', 'zoo', 'park', 'garden',
        'sports_complex', 'golf_course', 'swimming_pool',
        'tourist_attraction', 'landmark', 'historical_landmark',
        'cemetery', 'monument', 'civic_center', 'city_hall',
        'primary_school', 'secondary_school', 'preschool',
        'movie_theater', 'performing_arts_theater', 'concert_hall',
        'convention_center', 'event_venue', 'wedding_venue',
        'government_office', 'police', 'fire_station',
    }

    url = 'https://places.googleapis.com/v1/places:searchNearby'
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': _get_api_key(),
        'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.id,places.types,places.rating',
    }
    body = {
        'locationRestriction': {
            'circle': {
                'center': {'latitude': lat, 'longitude': lng},
                'radius': radius,
            }
        },
        'maxResultCount': min(max_results * 3, 20),
    }
    if included_types:
        body['includedTypes'] = list(included_types)

    try:
        response = requests.post(url, headers=headers, json=body, timeout=15)
        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code >= 400:
            provider_error = data.get('error') if isinstance(data, dict) else {}
            if isinstance(provider_error, dict):
                message = provider_error.get('message') or 'Unknown Google Places error'
                provider_status = provider_error.get('status')
            else:
                message = str(provider_error or 'Unknown Google Places error')
                provider_status = None
            safe_error = {
                'success': False,
                'error': f'Google Places API HTTP {response.status_code}: {message}',
                'error_code': 'GOOGLE_PLACES_HTTP_ERROR',
                'provider_status': provider_status,
                'http_status': response.status_code,
            }
            print(f"[GOOGLE PLACES ERROR] http={response.status_code} status={provider_status or 'unknown'} message={message}")
            return safe_error

        # Places API (New) answers a valid search that matches nothing with HTTP 200 and an empty
        # body, "{}", omitting the places key entirely. Treating that as a provider error turned a
        # quiet area into "invalid response" and hid the caller's own "no landmarks found" message,
        # which is only reachable on success. Any non-2xx case already returned above.
        if 'places' not in data:
            if not isinstance(data, dict) or data:
                message = 'Google Places returned an unexpected response without places'
                print(f'[GOOGLE PLACES ERROR] http={response.status_code} message={message}')
                return {
                    'success': False,
                    'error': message,
                    'error_code': 'GOOGLE_PLACES_INVALID_RESPONSE',
                    'http_status': response.status_code,
                }
            return {'success': True, 'landmarks': []}

        places = []
        for p in data.get('places', []):
            loc = p.get('location', {})
            p_types = set(p.get('types', []))
            
            if not include_all and p_types & IRRELEVANT_TYPES:
                continue

            is_preferred = bool(p_types & PREFERRED_TYPES)
            place_lat = loc.get('latitude')
            place_lng = loc.get('longitude')
            if place_lat is None or place_lng is None:
                continue
            distance_meters = _distance_meters(lat, lng, place_lat, place_lng)
            # Nearby Search can return edge results; do not label a distant place as nearby.
            if distance_meters > radius:
                continue
            
            places.append({
                'name': p.get('displayName', {}).get('text', 'Unknown'),
                'address': p.get('formattedAddress', ''),
                'lat': place_lat,
                'lng': place_lng,
                'place_id': p.get('id'),
                'types': p.get('types', []),
                'category': classify_landmark_category(p.get('types', [])),
                'rating': p.get('rating', 0),
                'preferred': is_preferred,
                'distance_meters': round(distance_meters),
            })
        
        places.sort(key=lambda x: (not x.get('preferred', False), x.get('distance_meters', float('inf')), -(x.get('rating') or 0)))
        places = places[:max_results]
        
        return {'success': True, 'landmarks': places}
    except requests.exceptions.Timeout:
        print('[GOOGLE PLACES ERROR] request timed out after 15 seconds')
        return {
            'success': False,
            'error': 'انتهت مهلة Google Places أثناء جلب المعالم القريبة',
            'error_code': 'GOOGLE_PLACES_TIMEOUT',
        }
    except requests.exceptions.RequestException as e:
        print(f'[GOOGLE PLACES ERROR] request failed: {e}')
        return {
            'success': False,
            'error': f'تعذر الاتصال بخدمة Google Places: {str(e)}',
            'error_code': 'GOOGLE_PLACES_REQUEST_ERROR',
        }
    except Exception as e:
        print(f'[GOOGLE PLACES ERROR] unexpected failure: {e}')
        return {
            'success': False,
            'error': f'فشل طلب Google Places: {str(e)}',
            'error_code': 'GOOGLE_PLACES_UNEXPECTED_ERROR',
        }


def get_driving_times(origin_lat, origin_lng, destinations):
    """Backwards-compatible wrapper around get_drive_matrix.

    Kept so older callers keep working, but the numbers come from a single
    source of truth (get_drive_matrix) to avoid divergent results.
    """
    if not _has_api_key():
        return _api_key_error()

    if not destinations:
        return {'success': True, 'times': []}

    matrix = get_drive_matrix({'lat': origin_lat, 'lng': origin_lng}, destinations)
    times = []
    for i, dest in enumerate(destinations):
        entry = matrix[i] if i < len(matrix) else None
        times.append({
            'landmark': dest,
            'duration_minutes': entry['duration_min'] if entry else None,
            'distance_text': f"{entry['distance_km']} km" if entry else None,
            'status': 'OK' if entry else 'NOT_FOUND',
        })
    return {'success': True, 'times': times}


def get_drive_matrix(origin, destinations):
    """Return driving metrics in chunks so large curated landmark lists remain supported."""
    if not destinations:
        return []
    chunk_size = 25
    combined = []
    for start in range(0, len(destinations), chunk_size):
        combined.extend(_get_drive_matrix_chunk(origin, destinations[start:start + chunk_size]))
    return combined


def _get_drive_matrix_chunk(origin, destinations):
    """Return [{name, distance_km, duration_min}] for one driving matrix request.

    origin may be (lat, lng) or a dict with lat/lng keys.
    """
    if not _has_api_key():
        return []

    if not destinations:
        return []

    if isinstance(origin, (tuple, list)) and len(origin) >= 2:
        origin_str = f"{origin[0]},{origin[1]}"
    else:
        origin_str = f"{origin.get('lat')},{origin.get('lng')}"

    points = []
    names = []
    for d in destinations:
        lat = d.get('lat') if isinstance(d, dict) else d[0]
        lng = d.get('lng') if isinstance(d, dict) else d[1]
        if lat is None or lng is None:
            return []  # index alignment with destinations must be preserved
        points.append(f"{lat},{lng}")
        names.append(d.get('name', '') if isinstance(d, dict) else '')

    if not points:
        return []

    url = 'https://maps.googleapis.com/maps/api/distancematrix/json'
    params = {
        'origins': origin_str,
        'destinations': '|'.join(points),
        'mode': 'driving',
        'language': 'ar',
        'region': 'SA',
        # Live traffic: without departure_time Google returns free-flow duration,
        # which is what made our numbers lower than the Google Maps app.
        'departure_time': 'now',
        'traffic_model': 'best_guess',
        'key': _get_api_key(),
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        if data.get('status') != 'OK':
            print(f"[DRIVE MATRIX] API error: {data.get('status')}")
            return []

        rows = data.get('rows', [])
        if not rows:
            return []

        elements = rows[0].get('elements', [])
        result = []
        for i, elem in enumerate(elements):
            distance_km = None
            duration_min = None
            in_traffic = False
            if elem.get('status') == 'OK' and elem.get('duration') and elem.get('distance'):
                distance_km = round(elem['distance']['value'] / 1000.0, 1)
                # Prefer the traffic-aware duration; fall back to free-flow.
                traffic = elem.get('duration_in_traffic') or {}
                seconds = traffic.get('value') or elem['duration']['value']
                in_traffic = bool(traffic.get('value'))
                duration_min = math.ceil(seconds / 60)
            # One entry per destination, in order, so callers can zip by index.
            result.append({
                'name': names[i] if i < len(names) else '',
                'distance_km': distance_km,
                'duration_min': duration_min,
                'distance_text': f"{distance_km} كم" if distance_km is not None else None,
                'in_traffic': in_traffic,
            })
        return result
    except Exception as e:
        print(f"[DRIVE MATRIX] request failed: {e}")
        return []


def get_street_view(lat, lng, heading=None, pitch=0, fov=90, size=(640, 480), output_path=None):
    """Download a Street View static image."""
    if not _has_api_key():
        return _api_key_error()

    if output_path is None:
        filename = f"streetview_{uuid.uuid4().hex}.jpg"
        output_path = os.path.join(MAPS_DIR, filename)

    url = 'https://maps.googleapis.com/maps/api/streetview'
    params = {
        'location': f"{lat},{lng}",
        'size': f"{size[0]}x{size[1]}",
        'key': _get_api_key(),
        'pitch': pitch,
        'fov': fov,
    }
    if heading is not None:
        params['heading'] = heading

    return _download_image(url, params, output_path)


def _build_markers(lat, lng, landmarks=None, label_start=1):
    """Build custom marker overlay list for a map."""
    markers = [{'lat': lat, 'lng': lng, 'color': MARKER_COLOR_SITE, 'type': 'site', 'label': None}]
    if landmarks:
        for i, lm in enumerate(landmarks):
            label = str((label_start + i) % 100)
            markers.append({
                'lat': lm['lat'],
                'lng': lm['lng'],
                'color': MARKER_COLOR_LANDMARK,
                'type': 'landmark',
                'label': label,
                'name': str(lm.get('name') or '').strip(),
            })
    return markers


def _build_catchment_paths(lat, lng, zones):
    """Build path strings for catchment area circles."""
    paths = []
    # Professional maroon-red colors matching the theme
    colors = ['0x6B1C23', '0x8B2020', '0xA63A3A']
    for i, zone in enumerate(zones):
        radius_km = zone.get('km', zone.get('minutes', 5) * 0.8 / 1.60934)
        points = []
        for angle in range(0, 360, 10):
            rad = math.radians(angle)
            # Approximate degree offset for radius
            lat_offset = (radius_km / 111.32) * math.cos(rad)
            lng_offset = (radius_km / (111.32 * math.cos(math.radians(lat)))) * math.sin(rad)
            points.append(f"{lat + lat_offset},{lng + lng_offset}")
        color = colors[i % len(colors)]
        # Use 20 (hex) opacity for fillcolor for a subtle transparent overlay
        paths.append(f"weight:2|color:{color}|fillcolor:{color}20|{ '|'.join(points)}")
    return paths if paths else None


def normalize_access_road_names(value):
    values = value if isinstance(value, list) else re.split(r'[\n,،;|]+', str(value or ''))
    result = []
    seen = set()
    for raw in values:
        name = str(raw or '').strip()
        if not name:
            continue
        name = re.split(r'\s+[—–-]\s+(?=\d|\d*[.]\d|\D*دقيقة)', name, maxsplit=1)[0].strip()
        prefix_match = re.match(r'^(طريق|شارع|جادة|ممر)\s+', name)
        prefix = prefix_match.group(1) if prefix_match else ''
        parts = [part.strip() for part in re.split(r'\s+و(?=\s|ال|شارع|طريق|جادة|ممر)\s*', name) if part.strip()]
        for part in parts:
            if prefix and not re.match(r'^(طريق|شارع|جادة|ممر)\s+', part):
                part = f'{prefix} {part}'
            key = re.sub(r'^(?:طريق|شارع|جادة|ممر)\s+', '', part)
            key = re.sub(r'[\sـ]+', ' ', key).strip().casefold()
            if key and key not in seen:
                seen.add(key)
                result.append(part)
    return result


def _build_road_paths(lat, lng, main_roads=None, secondary_roads=None):
    """No longer draws random lines. Roads are highlighted via map styles instead."""
    # Previously this drew star-pattern lines from center which looked terrible.
    # Now we rely on ACCESS_MAP_STYLES to highlight roads on the map itself.
    return None


def _build_site_area_path(lat, lng, zoom, area_radius_m=300):
    """Build a filled rectangle path around the site to highlight the project area."""
    # Convert radius in meters to approximate degree offsets
    lat_offset = area_radius_m / 111320.0
    lng_offset = area_radius_m / (111320.0 * math.cos(math.radians(lat)))
    # Build a rectangle (4 corners)
    corners = [
        f"{lat - lat_offset},{lng - lng_offset}",
        f"{lat + lat_offset},{lng - lng_offset}",
        f"{lat + lat_offset},{lng + lng_offset}",
        f"{lat - lat_offset},{lng + lng_offset}",
        f"{lat - lat_offset},{lng - lng_offset}",
    ]
    return f"weight:3|color:0xC0392B|fillcolor:0xC0392B30|{'|'.join(corners)}"


def _approx_polygon_area_sqm(coords):
    """Approximate polygon area using the Shoelace formula with degree-to-meter conversion."""
    n = len(coords)
    if n < 3:
        return 0
    avg_lat = sum(c[0] for c in coords) / n
    m_per_deg_lat = 111320.0
    m_per_deg_lng = 111320.0 * math.cos(math.radians(avg_lat))
    
    area = 0
    for i in range(n):
        j = (i + 1) % n
        x_i = coords[i][1] * m_per_deg_lng
        y_i = coords[i][0] * m_per_deg_lat
        x_j = coords[j][1] * m_per_deg_lng
        y_j = coords[j][0] * m_per_deg_lat
        area += x_i * y_j - x_j * y_i
    return abs(area) / 2.0


def _point_in_polygon(lat, lng, coords):
    """Return True only when the requested site point lies inside a polygon.

    Geocoding an address frequently returns the centre of a street or district.
    Selecting the nearest OSM building in that situation creates a misleading,
    apparently random highlight. Containment is the safe condition for an
    automatically selected footprint.
    """
    if len(coords) < 3:
        return False
    inside = False
    previous_lat, previous_lng = coords[-1]
    for current_lat, current_lng in coords:
        crosses = (current_lat > lat) != (previous_lat > lat)
        if crosses:
            boundary_lng = (previous_lng - current_lng) * (lat - current_lat) / (previous_lat - current_lat) + current_lng
            if lng < boundary_lng:
                inside = not inside
        previous_lat, previous_lng = current_lat, current_lng
    return inside


def _is_viewport_rectangle(coords):
    """Check if coordinates form a 4-point geocoding viewport bounding rectangle."""
    if not coords or len(coords) != 4:
        return False
    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    unique_lats = {round(lat, 5) for lat in lats}
    unique_lngs = {round(lng, 5) for lng in lngs}
    return len(unique_lats) == 2 and len(unique_lngs) == 2


def _point_to_segment_dist_m(plat, plng, alat, alng, blat, blng):
    """Shortest distance in meters from a point to a line segment between two vertices."""
    mlat = math.radians((plat + alat + blat) / 3.0)
    mx = 111320.0 * math.cos(mlat)
    my = 110540.0
    px, py = plng * mx, plat * my
    ax, ay = alng * mx, alat * my
    bx, by = blng * mx, blat * my
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _min_dist_to_polygon_m(plat, plng, coords):
    """Shortest distance from point to polygon perimeter (edges, not just vertices)."""
    best = float('inf')
    for i in range(len(coords)):
        a = coords[i]
        b = coords[(i + 1) % len(coords)]
        d = _point_to_segment_dist_m(plat, plng, a[0], a[1], b[0], b[1])
        if d < best:
            best = d
    return best


def utm_to_latlng(easting, northing, zone, northern=True):
    """Inverse UTM on WGS84 so croquis eastings/northings can be drawn on a map."""
    a = 6378137.0
    f = 1 / 298.257223563
    k0 = 0.9996
    e2 = f * (2 - f)
    e_prime2 = e2 / (1 - e2)
    x = easting - 500000.0
    y = northing if northern else northing - 10000000.0
    m = y / k0
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
        + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
        + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
        + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
    )
    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    tan_phi1 = math.tan(phi1)
    c1 = e_prime2 * cos_phi1 ** 2
    t1 = tan_phi1 ** 2
    n1 = a / math.sqrt(1 - e2 * sin_phi1 ** 2)
    r1 = a * (1 - e2) / (1 - e2 * sin_phi1 ** 2) ** 1.5
    d = x / (n1 * k0)
    latitude = phi1 - (n1 * tan_phi1 / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * e_prime2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * e_prime2 - 3 * c1 ** 2) * d ** 6 / 720
    )
    longitude = (
        d
        - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * e_prime2 + 24 * t1 ** 2) * d ** 5 / 120
    ) / cos_phi1
    central_meridian = (zone - 1) * 6 - 180 + 3
    return math.degrees(latitude), central_meridian + math.degrees(longitude)


def utm_zone_for_longitude(longitude):
    return int((float(longitude) + 180) / 6) + 1


def _survey_points(project_data):
    """Read the croquis coordinates table, whatever shape the draft stored it in."""
    raw = (project_data or {}).get('survey_coordinates')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        easting = item.get('eastings') or item.get('easting') or item.get('x')
        northing = item.get('northings') or item.get('northing') or item.get('y')
        try:
            easting = float(str(easting).replace(',', '').strip())
            northing = float(str(northing).replace(',', '').strip())
        except (TypeError, ValueError):
            continue
        if easting <= 0 or northing <= 0:
            continue
        rows.append({
            'easting': easting,
            'northing': northing,
            'parcel_id': str(item.get('parcel_id') or item.get('parcelId') or '').strip(),
        })
    return rows


def survey_polygon_from_project(project_data, site_lat, site_lng, tolerance_km=8.0):
    """Build the site boundary from the croquis survey coordinates.

    No Google Maps API returns a building footprint or a parcel outline — Geocoding and
    Places expose only a bounds rectangle — so the croquis table is the one authoritative
    boundary the system actually receives, and it is already in the draft.
    """
    rows = _survey_points(project_data)
    if len(rows) < 3:
        return None
    try:
        zone = utm_zone_for_longitude(site_lng)
        northern = float(site_lat) >= 0
    except (TypeError, ValueError):
        return None
    parcels = {}
    for row in rows:
        parcels.setdefault(row['parcel_id'], []).append(row)
    best = None
    for parcel_id, points in parcels.items():
        if len(points) < 3:
            continue
        coords = []
        for point in points:
            try:
                coords.append(utm_to_latlng(point['easting'], point['northing'], zone, northern))
            except (ValueError, ZeroDivisionError, OverflowError):
                coords = []
                break
        if len(coords) < 3:
            continue
        center_lat = sum(item[0] for item in coords) / len(coords)
        center_lng = sum(item[1] for item in coords) / len(coords)
        offset_km = math.hypot(
            (center_lat - float(site_lat)) * 111.32,
            (center_lng - float(site_lng)) * 111.32 * math.cos(math.radians(float(site_lat))),
        )
        # A local or municipal grid converts to somewhere else entirely; reject it rather
        # than highlighting the wrong place.
        if offset_km > tolerance_km:
            print(f'[SURVEY POLYGON] parcel {parcel_id or "-"} lands {offset_km:.1f} km away; ignored')
            continue
        if best is None or offset_km < best[0]:
            best = (offset_km, parcel_id, coords)
    if not best:
        return None
    offset_km, parcel_id, coords = best
    print(
        f'[SURVEY POLYGON] parcel {parcel_id or "-"}: {len(coords)} croquis points, '
        f'centre {offset_km * 1000:.0f} m from the site pin'
    )
    return coords


def _google_bounds_polygon(lat, lng, tenant_id=None, max_span_m=400):
    """Last automatic resort: the Geocoding bounds rectangle for the address.

    This is a rectangle, not a real outline, so it is only accepted when it is small
    enough to plausibly be one plot.
    """
    if not _has_api_key():
        return None
    try:
        response = requests.get(
            'https://maps.googleapis.com/maps/api/geocode/json',
            params={'latlng': f'{lat},{lng}', 'key': _get_api_key(), 'language': 'ar'}, timeout=15
        )
        data = response.json()
        if data.get('status') != 'OK':
            return None
        for result in data.get('results', []):
            geometry = result.get('geometry') or {}
            bounds = geometry.get('bounds')
            if not bounds:
                continue
            northeast = bounds.get('northeast') or {}
            southwest = bounds.get('southwest') or {}
            try:
                north, east = float(northeast['lat']), float(northeast['lng'])
                south, west = float(southwest['lat']), float(southwest['lng'])
            except (KeyError, TypeError, ValueError):
                continue
            height_m = abs(north - south) * 111320.0
            width_m = abs(east - west) * 111320.0 * math.cos(math.radians(lat))
            if max(height_m, width_m) > max_span_m or min(height_m, width_m) <= 0:
                continue
            print(f'[GOOGLE BOUNDS] rectangle {width_m:.0f}m x {height_m:.0f}m from geocoding')
            return [(south, west), (south, east), (north, east), (north, west)]
    except Exception as error:
        print(f'[GOOGLE BOUNDS ERROR] {error}')
    return None


def _fetch_osm_polygon(lat, lng, radius_m=400):
    """Fetch the real building/compound polygon from OpenStreetMap via Overpass API in a single optimized query."""
    
    overpass_servers = [
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    
    headers = {
        'User-Agent': 'RealEstateProposalGenerator/1.0'
    }
    
    query = f"""[out:json][timeout:15];
    (
      way(around:{radius_m},{lat},{lng})["building"];
      relation(around:{radius_m},{lat},{lng})["building"];
    );
    out geom;"""
    
    data = None
    for server_url in overpass_servers:
        try:
            resp = requests.post(server_url, data={'data': query}, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                break
        except Exception as e:
            print(f"[OSM POLYGON] Server {server_url} failed: {e}")
            continue
            
    if not data:
        return None
        
    elements = data.get('elements', [])
    if not elements:
        return None
        
    MAX_BUILDING_AREA_SQM = 100000

    print(f"[OSM POLYGON] Overpass returned {len(elements)} building elements near ({lat}, {lng})")
    rejected = {'no_tag': 0, 'too_large': 0, 'too_small': 0, 'too_far': 0}

    best_el = None
    best_sort_key = None

    for el in elements:
        geom = el.get('geometry', [])
        if len(geom) < 3:
            continue
            
        coords = [(p['lat'], p['lon']) for p in geom]
        area_sqm = _approx_polygon_area_sqm(coords)
        tags = el.get('tags', {})
        
        if 'building' not in tags:
            rejected['no_tag'] += 1
            continue
        tag_type = "building:" + str(tags['building'])

        if area_sqm > MAX_BUILDING_AREA_SQM:
            rejected['too_large'] += 1
            continue
        if area_sqm < 10:
            rejected['too_small'] += 1
            continue
            
        min_dist_to_vertex = _min_dist_to_polygon_m(lat, lng, coords)
        is_inside = _point_in_polygon(lat, lng, coords)
        
        if not is_inside:
            rejected['too_far'] += 1
            print(f"[OSM CANDIDATE] rejected-outside {tag_type}: {area_sqm:.0f} sqm, {min_dist_to_vertex:.1f} m")
            continue

        print(f"[OSM CANDIDATE] accepted {tag_type}: {area_sqm:.0f} sqm, {min_dist_to_vertex:.1f} m, inside={is_inside}")
            
        # Prefer the smallest building footprint that contains the exact coordinate.
        sort_key = (area_sqm, min_dist_to_vertex)
        if best_sort_key is None or sort_key < best_sort_key:
            best_sort_key = sort_key
            best_el = el
            
    if best_el and best_el.get('geometry'):
        coords = [(p['lat'], p['lon']) for p in best_el['geometry']]
        tags = best_el.get('tags', {})
        area_sqm = _approx_polygon_area_sqm(coords)
        tag_name = tags.get('name', '')
        tag_type = tags.get('leisure', tags.get('building', tags.get('amenity', tags.get('landuse', 'polygon'))))
        is_inside_str = "containing"
        try:
            print(f"[OSM POLYGON] Found {is_inside_str} {tag_type} '{tag_name}' ({best_sort_key[1]:.0f} sqm), ~{area_sqm:.0f} sqm")
        except Exception:
            safe_name = str(tag_name).encode('ascii', errors='ignore').decode('ascii')
            print(f"[OSM POLYGON] Found {is_inside_str} {tag_type} '{safe_name}' ({best_sort_key[1]:.0f} sqm), ~{area_sqm:.0f} sqm")
        return coords
        
    print(f"[OSM POLYGON] No suitable polygon found near ({lat}, {lng}) | rejected={rejected}")
    return None


def _fetch_osm_neighborhood(lat, lng, radius_m=2000):
    """Fetch a neighborhood/suburb/district boundary from OpenStreetMap for sites without building footprints."""

    overpass_servers = [
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]

    headers = {
        'User-Agent': 'RealEstateProposalGenerator/1.0'
    }

    query = f"""[out:json][timeout:20];
    (
      way(around:{radius_m},{lat},{lng})["place"~"suburb|neighbourhood|quarter|district|city_block|locality"];
      relation(around:{radius_m},{lat},{lng})["place"~"suburb|neighbourhood|quarter|district|city_block|locality"];
      relation(around:{radius_m},{lat},{lng})["boundary"="administrative"]["admin_level"="8"];
      relation(around:{radius_m},{lat},{lng})["boundary"="administrative"]["admin_level"="9"];
      relation(around:{radius_m},{lat},{lng})["boundary"="administrative"]["admin_level"="10"];
    );
    out geom;"""

    data = None
    for server_url in overpass_servers:
        try:
            resp = requests.post(server_url, data={'data': query}, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                break
        except Exception as e:
            print(f"[OSM NEIGHBORHOOD] Server {server_url} failed: {e}")
            continue

    if not data:
        return None

    elements = data.get('elements', [])
    if not elements:
        return None

    candidates = []
    for el in elements:
        el_type = el.get('type')
        tags = el.get('tags', {})
        if el_type == 'relation':
            for member in el.get('members', []):
                if member.get('type') == 'way' and member.get('role') == 'outer' and member.get('geometry'):
                    outer = [(p['lat'], p['lon']) for p in member['geometry'] if 'lat' in p and 'lon' in p]
                    if len(outer) >= 3:
                        candidates.append({'coords': outer, 'tags': tags})
        elif el_type == 'way' and el.get('geometry'):
            outer = [(p['lat'], p['lon']) for p in el['geometry'] if 'lat' in p and 'lon' in p]
            if len(outer) >= 3:
                candidates.append({'coords': outer, 'tags': tags})

    if not candidates:
        return None

    MAX_NEIGHBORHOOD_AREA_SQM = 50_000_000  # 50 km²
    MIN_NEIGHBORHOOD_AREA_SQM = 10_000      # 1 hectare

    best = None
    best_key = None
    best_area = 0
    for cand in candidates:
        area_sqm = _approx_polygon_area_sqm(cand['coords'])
        if area_sqm > MAX_NEIGHBORHOOD_AREA_SQM or area_sqm < MIN_NEIGHBORHOOD_AREA_SQM:
            continue
        inside = _point_in_polygon(lat, lng, cand['coords'])
        dist = _min_dist_to_polygon_m(lat, lng, cand['coords'])
        # Prefer containing, then smallest containing, then closest non-containing
        key = (0 if inside else 1, area_sqm if inside else dist, dist if inside else area_sqm)
        if best is None or key < best_key:
            best = cand['coords']
            best_key = key
            best_area = area_sqm

    if best:
        print(f"[OSM NEIGHBORHOOD] Found neighborhood {best_area:.0f} sqm, inside={best_key[0] == 0}")
        return best

    return None


# Cache for OSM polygons to avoid re-querying for the same location across map types
_osm_polygon_cache = {}

# Cache for OSM neighborhood boundaries
_osm_neighborhood_cache = {}


def _draw_site_highlight(image_path, center_lat, center_lng, zoom, area_radius_m=300, size=(1280, 720), scale=2,
                         polygon_coords=None, auto_detect_polygon=True, auto_detected=True, rotation_deg=18.0):
    """Draw the site highlight using the real building shape.
    Priority: 1) Real user polygon, 2) Auto-detected building/neighborhood polygon from OSM, 3) Styled site circle fallback.
    auto_detected=False skips the 4-point viewport-rectangle filter, preserving user-drawn rectangles."""
    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        cx, cy = img_w // 2, img_h // 2

        overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        fill_color = SITE_FILL_COLOR
        border_color = SITE_BORDER_COLOR

        # Ignore 4-point geocoding viewport rectangles so real OSM building shapes are preferred.
        # Only apply to auto-detected (OSM) polygons; user-drawn rectangles must be preserved.
        if auto_detected and polygon_coords and _is_viewport_rectangle(polygon_coords):
            polygon_coords = None

        # Priority 1 & 2: Real building polygon
        if auto_detect_polygon and (not polygon_coords or len(polygon_coords) < 3):
            cache_key = f"{center_lat:.6f},{center_lng:.6f}"
            if cache_key in _osm_polygon_cache:
                osm_poly = _osm_polygon_cache[cache_key]
            else:
                osm_poly = _fetch_osm_polygon(center_lat, center_lng, radius_m=400)
                if osm_poly:
                    _osm_polygon_cache[cache_key] = osm_poly
            
            if osm_poly and len(osm_poly) >= 3:
                polygon_coords = osm_poly

        if polygon_coords and len(polygon_coords) >= 3:
            pixel_points = []
            for p_lat, p_lng in polygon_coords:
                dx, dy = _latlng_to_pixel_offset(p_lat, p_lng, center_lat, center_lng, zoom, scale=scale)
                px = int(cx + dx)
                py = int(cy + dy)
                pixel_points.append((px, py))
            
            overlay_draw.polygon(pixel_points, fill=fill_color, outline=border_color, width=5)
            overlay_draw.polygon(pixel_points, fill=None, outline=(255, 255, 255, 160), width=3)
        else:
            # Priority 3: Compact exact-point halo when no building polygon exists
            r = 14 if zoom >= 16 else 10
            overlay_draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(160, 50, 50, 45), outline=border_color, width=3)
            overlay_draw.line([(cx - r - 5, cy), (cx + r + 5, cy)], fill=(255, 255, 255, 180), width=2)
            overlay_draw.line([(cx, cy - r - 5), (cx, cy + r + 5)], fill=(255, 255, 255, 180), width=2)

        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[SITE HIGHLIGHT ERROR] {e}")
        return False


def catchment_rings(zones, limit=3):
    """Collapse the catchment rows into a few concentric drive-time bands.

    The rows the user fills are destinations (airport, station, corniche), not zones, so
    drawing one ring per row produced nine overlapping circles up to 31 km wide whose
    labels were unreadable.
    """
    candidates = []
    for zone in zones or []:
        if not isinstance(zone, dict):
            continue
        try:
            km = float(zone.get('km') or zone.get('distance_km') or zone.get('distance'))
        except (TypeError, ValueError):
            continue
        if km <= 0:
            continue
        minutes = zone.get('minutes') or zone.get('duration_minutes') or zone.get('duration_min')
        try:
            minutes = int(float(minutes))
        except (TypeError, ValueError):
            minutes = None
        candidates.append({
            'km': km,
            'minutes': minutes,
            'label': zone.get('label') or zone.get('name') or '',
        })
    if not candidates:
        return []
    candidates.sort(key=lambda item: item['km'])
    if len(candidates) <= limit:
        chosen = candidates
    else:
        indexes = {0, len(candidates) // 2, len(candidates) - 1}
        chosen = [candidates[index] for index in sorted(indexes)][:limit]
    rings = []
    for item in chosen:
        minutes = item['minutes']
        name = str(item.get('label') or item.get('name') or '').strip()
        time_label = f'{minutes} دقائق' if minutes else f'{item["km"]:.1f} كم'
        label = f'{name} — {time_label}' if name else time_label
        rings.append({'km': item['km'], 'minutes': minutes or 0, 'name': name, 'label': label})
    return rings


def zoom_for_radius_km(lat, radius_km, size=(1280, 720), scale=2, fill=0.8):
    """Pick the closest zoom that still keeps a radius fully inside the frame."""
    try:
        radius_m = float(radius_km) * 1000.0
    except (TypeError, ValueError):
        return None
    if radius_m <= 0:
        return None
    allowed_px = min(size[0], size[1]) * scale * 0.5 * fill
    for zoom in range(20, 7, -1):
        metres_per_pixel = 156543.03392 * math.cos(math.radians(float(lat))) / (2 ** zoom) / scale
        if radius_m / metres_per_pixel <= allowed_px:
            return zoom
    return 8


def access_map_zoom(lat, base_zoom):
    try:
        base = int(base_zoom)
    except (TypeError, ValueError):
        base = 17
    context_zoom = zoom_for_radius_km(lat, ACCESS_MAP_CONTEXT_RADIUS_KM)
    if context_zoom is None:
        return max(15, min(17, base))
    return max(15, min(17, base, context_zoom))


def _draw_catchment_zones(image_path, center_lat, center_lng, zoom, zones, scale=2):
    """Draw smooth, anti-aliased concentric catchment rings and elegant label pills using PIL."""
    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        cx, cy = img_w // 2, img_h // 2
        
        # Create a high-res canvas for anti-aliasing
        canvas_scale = 4
        canvas_w = img_w * canvas_scale
        canvas_h = img_h * canvas_scale
        canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        
        ccx = canvas_w // 2
        ccy = canvas_h // 2
        
        # Theme colors: Gold/Maroon/Teal for premium look
        # [Inner, Middle, Outer]
        fill_colors = [
            (107, 28, 35, 20),   # Subtle dark maroon fill (alpha 20)
            (171, 131, 75, 15),  # Subtle bronze/gold fill (alpha 15)
            (37, 75, 102, 12),   # Subtle dark blue/teal fill (alpha 12)
        ]
        border_colors = [
            (107, 28, 35, 160),  # Dark maroon
            (171, 131, 75, 150), # Bronze/gold
            (37, 75, 102, 130),  # Teal/blue
        ]
        
        # Sort zones from largest radius to smallest, so smaller ones are drawn on top
        sorted_zones = sorted(zones, key=lambda z: z.get('km', z.get('minutes', 5) * 0.8), reverse=True)
        
        for idx, zone in enumerate(sorted_zones):
            radius_km = zone.get('km', zone.get('minutes', 5) * 0.8 / 1.60934)
            radius_m = radius_km * 1000.0
            
            # Get latitude offset for radius
            lat_offset = radius_m / 111320.0
            _, dy = _latlng_to_pixel_offset(center_lat + lat_offset, center_lng, center_lat, center_lng, zoom, scale=scale)
            
            # Scale to canvas coordinates
            r = int(abs(dy) * canvas_scale)
            
            color_idx = idx % len(fill_colors)
            fill_c = fill_colors[color_idx]
            border_c = border_colors[color_idx]
            
            # Draw catchment circle
            draw.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=fill_c, outline=border_c, width=3 * canvas_scale)
            # Add thin white inner edge for premium glassmorphism glow
            draw.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=None, outline=(255, 255, 255, 60), width=1 * canvas_scale)
            
            # Draw elegant label pill for each zone
            label = zone.get('label') or f"{zone.get('minutes', 5)} دقائق"
            font = _get_arabic_font(14 * canvas_scale)
            reshaped = _reshape_arabic_text(label)
                
            bbox = draw.textbbox((0, 0), reshaped, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            
            # Spread the pills around the circle: stacking them all straight above the centre
            # buried the innermost label under the site pin.
            pad_x = 10 * canvas_scale
            pad_y = 5 * canvas_scale
            angle = math.radians(90 + 35 * (idx % 3))
            lx = int(ccx + r * math.cos(angle))
            ly = int(ccy - r * math.sin(angle))
            
            label_width = tw + pad_x * 2
            label_height = th + pad_y * 2
            rect_left = max(8 * canvas_scale, min(canvas_w - label_width - 8 * canvas_scale, lx - label_width // 2))
            rect_top = max(8 * canvas_scale, min(canvas_h - label_height - 8 * canvas_scale, ly - label_height // 2))
            rect = [rect_left, rect_top, rect_left + label_width, rect_top + label_height]

            # Draw pill background and border
            draw.rounded_rectangle(rect, radius=4 * canvas_scale, fill=border_c, outline=(255, 255, 255, 200), width=1 * canvas_scale)
            draw.text((rect_left + pad_x - bbox[0], rect_top + pad_y - bbox[1]), reshaped, fill='#FFFFFF', font=font)

        # Downsample with LANCZOS
        resized = canvas.resize((img_w, img_h), Image.Resampling.LANCZOS)
        img = Image.alpha_composite(img, resized)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[DRAW CATCHMENT ERROR] {e}")
        return False


def _post_process_streetview(image_path, heading, index):
    """Apply professional enhancements to Street View images: vignette, contrast, elegant borders, and direction labels."""
    try:
        from PIL import ImageEnhance
        img = Image.open(image_path).convert('RGBA')
        w, h = img.size
        
        # 1. Enhance Contrast & Color Saturation slightly for a professional architectural photo look
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.15)
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(1.05)
        
        # 2. Add subtle warm sepia-like color balance
        r, g, b, a = img.split()
        grey = img.convert('L')
        # Warm golden-cream tint
        sepia_r = grey.point(lambda x: min(255, int(x * 1.05)))
        sepia_g = grey.point(lambda x: min(255, int(x * 1.00)))
        sepia_b = grey.point(lambda x: min(255, int(x * 0.92)))
        sepia = Image.merge('RGBA', (sepia_r, sepia_g, sepia_b, a))
        img = Image.blend(img, sepia, 0.15) # Subtle blending
        
        # 3. Create a professional vignette (darkening towards corners)
        vignette = Image.new('L', (w, h), 255)
        v_draw = ImageDraw.Draw(vignette)
        # Draw a radial gradient centered
        for i in range(min(w, h) // 2):
            alpha = int(120 * (i / (min(w, h) // 2)) ** 2) # quadratic scaling for smooth transition
            v_draw.ellipse([i, i, w - i, h - i], outline=255 - alpha)
        
        # Apply vignette as alpha mask on black overlay
        black_overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        for x in range(w):
            for y in range(h):
                val = vignette.getpixel((x, y))
                if val < 255:
                    black_overlay.putpixel((x, y), (0, 0, 0, int((255 - val) * 0.4)))
        img = Image.alpha_composite(img, black_overlay)
        
        # 4. Draw elegant thin gold/cream border and white inner frame
        draw = ImageDraw.Draw(img)
        border_w = 4
        # Outer gold/bronze border
        gold_color = (171, 131, 75, 230)
        draw.rectangle([0, 0, w - 1, h - 1], outline=gold_color, width=border_w)
        # Inner thin white line
        draw.rectangle([border_w + 2, border_w + 2, w - border_w - 3, h - border_w - 3], outline=(255, 255, 255, 120), width=1)
        
        # 5. Add an elegant direction label pill at the bottom-right
        directions = {
            0: "إطلالة الشمال",
            90: "إطلالة الشرق",
            180: "إطلالة الجنوب",
            270: "إطلالة الغرب"
        }
        dir_text = directions.get(heading, f"إطلالة {heading} درجة")
        font = _get_arabic_font(14)
        reshaped = _reshape_arabic_text(dir_text)
            
        bbox = draw.textbbox((0, 0), reshaped, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        
        pad_x = 12
        pad_y = 6
        rx = w - border_w - 15 - tw - pad_x * 2
        ry = h - border_w - 15 - th - pad_y * 2
        
        rect = [rx, ry, w - border_w - 15, h - border_w - 15]
        
        # Dark transculent background for label
        draw.rounded_rectangle(rect, radius=5, fill=(37, 75, 102, 210), outline=gold_color, width=1)
        draw.text((rx + pad_x, ry + pad_y - 2), reshaped, fill='#FFFFFF', font=font)
        
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[STREETVIEW ENHANCE ERROR] {e}")
        return False


def _draw_compass(image_path, position='top-right', compass_size=60):
    """Draw a professional compass indicator (ش = North) matching reference examples."""
    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Position compass
        margin = 30
        if position == 'top-right':
            comp_cx = img_w - margin - compass_size // 2
            comp_cy = margin + compass_size // 2
        else:
            comp_cx = margin + compass_size // 2
            comp_cy = margin + compass_size // 2

        r = compass_size // 2
        # Outer circle (cream/beige)
        draw.ellipse([comp_cx - r, comp_cy - r, comp_cx + r, comp_cy + r],
                     fill=(240, 230, 210, 220), outline=COMPASS_COLOR + (255,), width=3)

        font = _get_arabic_font(compass_size // 2)
        text = _reshape_arabic_text('ش')
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((comp_cx - tw // 2, comp_cy - th // 2 - 2), text,
                  fill=COMPASS_COLOR + (255,), font=font)

        # Small triangle pointing up (North indicator)
        tri_size = 8
        draw.polygon([(comp_cx, comp_cy - r + 6),
                      (comp_cx - tri_size // 2, comp_cy - r + 6 + tri_size),
                      (comp_cx + tri_size // 2, comp_cy - r + 6 + tri_size)],
                     fill=COMPASS_COLOR + (255,))

        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[COMPASS ERROR] {e}")
        return False


def _apply_sepia_tone(image_path, intensity=0.3):
    """Apply a warm sepia tone to satellite imagery matching reference examples."""
    try:
        img = Image.open(image_path).convert('RGBA')
        r, g, b, a = img.split()
        # Convert to greyscale
        grey = img.convert('L')
        # Create sepia channels (warm brown tone)
        sepia_r = grey.point(lambda x: min(255, int(x * (1 + 0.2 * intensity))))
        sepia_g = grey.point(lambda x: min(255, int(x * (1 + 0.05 * intensity))))
        sepia_b = grey.point(lambda x: min(255, int(x * (1 - 0.1 * intensity))))
        sepia = Image.merge('RGBA', (sepia_r, sepia_g, sepia_b, a))
        # Blend original with sepia
        result = Image.blend(img, sepia, intensity)
        result.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[SEPIA ERROR] {e}")
        return False


def _draw_inset_map(image_path, center_lat, center_lng, inset_size=180):
    """Draw a small inset/overview map in the bottom-right corner."""
    try:
        # Download a smaller wide-area map
        inset_path = image_path + '.inset.png'
        inset_res = get_static_map(center_lat, center_lng, zoom=9,
                                    size=(inset_size, inset_size),
                                    output_path=inset_path,
                                    styles=SATELLITE_CLEAN_STYLES)
        if not inset_res.get('success'):
            return False

        img = Image.open(image_path).convert('RGBA')
        inset = Image.open(inset_path).convert('RGBA')
        # Resize inset (scale=2 makes it 2x, resize down)
        inset = inset.resize((inset_size, inset_size), Image.LANCZOS)

        img_w, img_h = img.size
        # Position: bottom-right with margin
        margin = 20
        ix = img_w - inset_size - margin
        iy = img_h - inset_size - margin

        # Draw border around inset
        border = Image.new('RGBA', (inset_size + 6, inset_size + 6), (240, 230, 210, 200))
        img.paste(border, (ix - 3, iy - 3), border)
        img.paste(inset, (ix, iy), inset)

        # Draw site marker on inset (center dot)
        draw = ImageDraw.Draw(img)
        inset_cx = ix + inset_size // 2
        inset_cy = iy + inset_size // 2
        # Small maroon triangle pin
        pin_s = 10
        draw.polygon([(inset_cx - pin_s, inset_cy - pin_s // 2),
                      (inset_cx + pin_s, inset_cy - pin_s // 2),
                      (inset_cx, inset_cy + pin_s)],
                     fill=MARKER_COLOR_SITE)

        img.save(image_path, 'PNG')

        # Cleanup temp inset file
        try:
            os.remove(inset_path)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[INSET MAP ERROR] {e}")
        return False


def _decode_polyline(polyline_str):
    """Decode Google Maps encoded polyline string into lat/lng list."""
    index = 0
    lat = 0
    lng = 0
    coordinates = []
    try:
        while index < len(polyline_str):
            b = 0
            shift = 0
            result = 0
            while True:
                b = ord(polyline_str[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if not b >= 0x20:
                     break
            dlat = ~(result >> 1) if (result & 1) else (result >> 1)
            lat += dlat

            shift = 0
            result = 0
            while True:
                b = ord(polyline_str[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if not b >= 0x20:
                     break
            dlng = ~(result >> 1) if (result & 1) else (result >> 1)
            lng += dlng
            coordinates.append((lat / 1e5, lng / 1e5))
    except Exception as e:
        print(f"[POLYLINE DECODE ERROR] {e}")
    return coordinates


def _snap_to_roads(lat, lng, tenant_id=None):
    """Snap coordinates to nearest road using Google Roads API for precision."""
    if not _has_api_key():
        return None
    url = 'https://roads.googleapis.com/v1/nearestRoads'
    params = {
        'points': f"{lat},{lng}",
        'key': _get_api_key(),
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if 'snappedPoints' in data and data['snappedPoints']:
            sp = data['snappedPoints'][0]
            loc = sp.get('location', {})
            if loc.get('latitude') and loc.get('longitude'):
                if tenant_id:
                    _record_maps_call(tenant_id)
                return {
                    'lat': loc['latitude'],
                    'lng': loc['longitude'],
                    'place_id': sp.get('placeId'),
                }
    except Exception as e:
        print(f"[ROADS API ERROR] {e}")
    return None


def _google_directions_route(origin_lat, origin_lng, destination_lat, destination_lng, tenant_id=None):
    """Return Google Maps road geometry; never fall back to a third-party router."""
    if not _has_api_key():
        return None
    params = {
        'origin': f'{origin_lat},{origin_lng}',
        'destination': f'{destination_lat},{destination_lng}',
        'mode': 'driving',
        'alternatives': 'false',
        'language': 'ar',
        'region': 'sa',
        'key': _get_api_key(),
    }
    try:
        response = requests.get('https://maps.googleapis.com/maps/api/directions/json', params=params, timeout=15)
        data = response.json()
        if data.get('status') != 'OK' or not data.get('routes'):
            err_msg = data.get('error_message', '')
            print(f"[GOOGLE DIRECTIONS] {data.get('status', 'no route')} - {err_msg}")
            return None
        route = data['routes'][0]
        encoded = route.get('overview_polyline', {}).get('points')
        coordinates = _decode_polyline(encoded) if encoded else []
        if len(coordinates) < 2:
            return None
        if tenant_id:
            _record_maps_call(tenant_id)
        leg = (route.get('legs') or [{}])[0]
        distance = leg.get('distance') or {}
        duration = leg.get('duration_in_traffic') or leg.get('duration') or {}
        distance_meters = distance.get('value')
        duration_seconds = duration.get('value')
        return {
            'coords': coordinates,
            'summary': route.get('summary', ''),
            'distance_meters': distance_meters,
            'distance_km': round(distance_meters / 1000.0, 1) if distance_meters is not None else None,
            'duration_min': math.ceil(duration_seconds / 60) if duration_seconds is not None else None,
        }
    except Exception as error:
        print(f"[GOOGLE DIRECTIONS ERROR] {error}")
        return None


def _google_reverse_geocode_road(lat, lng, tenant_id=None):
    """Ask Google which named road is nearest to a point used for an access route."""
    if not _has_api_key():
        return ''
    try:
        response = requests.get(
            'https://maps.googleapis.com/maps/api/geocode/json',
            params={'latlng': f'{lat},{lng}', 'key': _get_api_key(), 'language': 'ar'}, timeout=15
        )
        data = response.json()
        if data.get('status') != 'OK':
            return ''
        for result in data.get('results', []):
            for component in result.get('address_components', []):
                if 'route' in component.get('types', []):
                    if tenant_id:
                        _record_maps_call(tenant_id)
                    return component.get('long_name') or ''
    except Exception as error:
        print(f"[GOOGLE ROAD NAME ERROR] {error}")
    return ''


def _fixed_road_probe_points(lat, lng, lat_step, lng_step):
    diagonal_lat = lat_step * 0.72
    diagonal_lng = lng_step * 0.72
    return [
        (lat + lat_step, lng),
        (lat - lat_step, lng),
        (lat, lng + lng_step),
        (lat, lng - lng_step),
        (lat + diagonal_lat, lng + diagonal_lng),
        (lat + diagonal_lat, lng - diagonal_lng),
        (lat - diagonal_lat, lng + diagonal_lng),
        (lat - diagonal_lat, lng - diagonal_lng),
    ]


def discover_nearby_roads(center_lat, center_lng, tenant_id=None, origin_lat=None, origin_lng=None, max_results=6,
                          lat_step=0.0018, lng_step=0.0024):
    """Return verified nearby road names from Google Roads + Directions."""
    route_origin_lat = origin_lat if origin_lat is not None else center_lat
    route_origin_lng = origin_lng if origin_lng is not None else center_lng
    probes = _fixed_road_probe_points(route_origin_lat, route_origin_lng, lat_step, lng_step)

    def fetch(probe):
        p_lat, p_lng = probe
        snapped = _snap_to_roads(p_lat, p_lng, tenant_id=tenant_id)
        dest_lat = snapped['lat'] if snapped else p_lat
        dest_lng = snapped['lng'] if snapped else p_lng
        route = _google_directions_route(
            route_origin_lat, route_origin_lng, dest_lat, dest_lng, tenant_id=tenant_id
        )
        if not route:
            return None
        name = (route.get('summary') or '').strip()
        if not name or re.search(r'[A-Za-z]', name):
            localized_name = _google_reverse_geocode_road(dest_lat, dest_lng, tenant_id=tenant_id)
            if localized_name:
                name = localized_name
        name = name or 'طريق قريب'
        key = (snapped or {}).get('place_id') or name.casefold()
        distance_meters = route.get('distance_meters')
        if distance_meters is None:
            distance_meters = round(_distance_meters(route_origin_lat, route_origin_lng, dest_lat, dest_lng))
        distance_km = route.get('distance_km')
        if distance_km is None:
            distance_km = round(distance_meters / 1000.0, 1)
        duration_min = route.get('duration_min')
        return {
            'name': name,
            'lat': dest_lat,
            'lng': dest_lng,
            'distance_meters': distance_meters,
            'distance_km': distance_km,
            'distance_text': f'{distance_km} كم',
            'duration_min': duration_min,
            'duration_minutes': duration_min,
            'place_id': key,
        }

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        candidates = list(executor.map(fetch, probes))

    roads = []
    seen = set()
    for road in candidates:
        if not road or road['place_id'] in seen:
            continue
        seen.add(road['place_id'])
        roads.append(road)
        if len(roads) >= max(1, int(max_results)):
            break
    return roads


def access_probe_points(lat, lng):
    """Fixed points used to discover the access roads around a site.

    These must never depend on a regeneration seed: moving them snapped to different roads
    and produced a different set of street names on every regeneration of the same site.
    """
    return _fixed_road_probe_points(lat, lng, 0.0018, 0.0024)


_ROAD_NAME_PREFIXES = ('طريق', 'شارع', 'الطريق', 'الشارع', 'ش.', 'ش')


def _road_name_key(name):
    """Normalise a road name so the same road is not drawn twice under two spellings."""
    text = _strip_arabic_diacritics(name).strip()
    text = re.sub(r'[\u0623\u0625\u0622]', '\u0627', text)
    text = re.sub(r'[\u0649]', '\u064a', text)
    text = re.sub(r'[\u0629]', '\u0647', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    words = [word for word in text.split() if word not in _ROAD_NAME_PREFIXES]
    words = [word[2:] if word.startswith('ال') and len(word) > 3 else word for word in words]
    return ' '.join(words).casefold()


def is_same_road_name(first, second):
    """Two labels are the same road when one name is contained in the other.

    The entered list holds compound rows such as «الامير فيصل بن فهد والخليفة المهدي»
    beside «الامير فيصل بن فهد», so comparing keys for equality drew one street twice.
    """
    first_words = set(_road_name_key(first).split())
    second_words = set(_road_name_key(second).split())
    if not first_words or not second_words:
        return False
    return first_words <= second_words or second_words <= first_words


def match_known_road_name(discovered, known_names):
    """Return an approved label only when its normalized name matches Google's name."""
    discovered_key = _road_name_key(discovered)
    if not discovered_key:
        return ''
    discovered_words = set(discovered_key.split())
    candidates = []
    for index, candidate in enumerate(known_names or []):
        candidate_key = _road_name_key(candidate)
        if not candidate_key:
            continue
        if candidate_key == discovered_key:
            return str(candidate).strip()
        candidate_words = set(candidate_key.split())
        if discovered_words <= candidate_words or candidate_words <= discovered_words:
            difference = discovered_words ^ candidate_words
            if difference & {'غير', 'بدون', 'ليس'}:
                continue
            candidates.append((len(difference), index, str(candidate).strip()))
    return min(candidates)[2] if candidates else ''


def _approved_manual_road_paths(value, approved_names):
    """Validate manual geometry and keep only roads named in the approved main-road list."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if not isinstance(value, list):
        return []

    approved_by_key = {
        _road_name_key(name): name for name in approved_names or [] if _road_name_key(name)
    }
    paths = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized_names = normalize_access_road_names([item.get('name')])
        if len(normalized_names) != 1:
            continue
        approved_name = approved_by_key.get(_road_name_key(normalized_names[0]))
        if not approved_name:
            continue
        points = []
        for point in item.get('points') or []:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                point_lat = float(point[0])
                point_lng = float(point[1])
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(point_lat) and math.isfinite(point_lng)):
                continue
            if not (-90 <= point_lat <= 90 and -180 <= point_lng <= 180):
                continue
            points.append((point_lat, point_lng))
        if len(points) >= 2:
            paths.append((points, approved_name))
    return paths


def _draw_access_roads(image_path, center_lat, center_lng, zoom, scale=2, project_data=None, tenant_id=None,
                       origin_lat=None, origin_lng=None, allow_discovery=True):
    """Draw only approved main-road geometry and labels."""
    def _draw_road_label(draw, px, py, text, label_scale=1.0, font=None, bg_color=(37, 75, 102, 255), border_color=(240, 230, 210, 255)):
        label_scale = max(0.6, min(1.8, float(label_scale or 1)))
        if not font:
            font = _get_arabic_font(max(12, round(24 * label_scale)))

        reshaped_text = _reshape_arabic_text(text)
        bbox = draw.textbbox((0, 0), reshaped_text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        pad_x = max(7, round(12 * label_scale))
        pad_y = max(4, round(7 * label_scale))
        rect = [int(px - tw // 2 - pad_x), int(py - th // 2 - pad_y), int(px + tw // 2 + pad_x), int(py + th // 2 + pad_y)]

        draw.rounded_rectangle(rect, radius=max(5, round(8 * label_scale)), fill=bg_color, outline=border_color, width=2)
        draw.text((int(px - tw // 2), int(py - th // 2 - 2)), reshaped_text, fill='#FFFFFF', font=font)

    def _offset_label_point(point, route_segment, img_w, img_h, distance=52):
        px, py = point
        if len(route_segment) < 2:
            return px, py
        nearest_index = min(range(len(route_segment)), key=lambda index: (route_segment[index][0] - px) ** 2 + (route_segment[index][1] - py) ** 2)
        previous_point = route_segment[max(0, nearest_index - 1)]
        next_point = route_segment[min(len(route_segment) - 1, nearest_index + 1)]
        dx = next_point[0] - previous_point[0]
        dy = next_point[1] - previous_point[1]
        length = math.hypot(dx, dy) or 1
        ox = -dy / length * distance
        oy = dx / length * distance
        candidates = [(px + ox, py + oy), (px - ox, py - oy)]
        for candidate_x, candidate_y in candidates:
            if 90 <= candidate_x <= img_w - 90 and 60 <= candidate_y <= img_h - 60:
                return int(candidate_x), int(candidate_y)
        return px, py

    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        cx, cy = img_w // 2, img_h // 2
        overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        gold_color = (212, 163, 89, 180) # Premium gold/bronze color matching branding
        
        # main_roads is the authoritative approval list. Secondary roads and
        # unmatched Google route names must never be introduced into this view.
        route_origin_lat = origin_lat if origin_lat is not None else center_lat
        route_origin_lng = origin_lng if origin_lng is not None else center_lng
        approved_road_names = normalize_access_road_names(
            (project_data or {}).get('main_roads')
        )
        road_data = (project_data or {}).get('main_roads_data')
        if isinstance(road_data, str):
            try:
                road_data = json.loads(road_data)
            except (TypeError, ValueError):
                road_data = []
        manual_road_keys = {
            _road_name_key(item.get('name')) for item in (road_data if isinstance(road_data, list) else [])
            if isinstance(item, dict) and item.get('row_source') == 'manual'
        }
        discoverable_road_names = [name for name in approved_road_names if _road_name_key(name) not in manual_road_keys]

        # Manual geometry is already reviewed by the user, but its label must still
        # match a normalized main-road name. The provided point sequence is kept intact.
        road_route_mapping = _approved_manual_road_paths(
            (project_data or {}).get('manual_road_paths'), approved_road_names
        )
        seen_road_keys = {name for _, name in road_route_mapping}
        if not allow_discovery:
            for stored_path in _approved_manual_road_paths(
                (project_data or {}).get('access_roads_data'), approved_road_names
            ):
                if not any(is_same_road_name(stored_path[1], accepted) for accepted in seen_road_keys):
                    road_route_mapping.append(stored_path)
                    seen_road_keys.add(stored_path[1])
        label_positions = (project_data or {}).get('access_road_label_positions') or {}
        if isinstance(label_positions, str):
            try:
                label_positions = json.loads(label_positions)
            except (TypeError, ValueError):
                label_positions = {}
        position_by_key = {}
        if isinstance(label_positions, dict):
            for name, point in label_positions.items():
                try:
                    if isinstance(point, (list, tuple)) and len(point) >= 2:
                        position_by_key[_road_name_key(name)] = (float(point[0]), float(point[1]))
                except (TypeError, ValueError):
                    continue
        label_sizes = (project_data or {}).get('access_road_label_sizes') or {}
        if isinstance(label_sizes, str):
            try:
                label_sizes = json.loads(label_sizes)
            except (TypeError, ValueError):
                label_sizes = {}
        size_by_key = {}
        if isinstance(label_sizes, dict):
            for name, value in label_sizes.items():
                try:
                    size_by_key[_road_name_key(name)] = max(0.6, min(1.8, float(value)))
                except (TypeError, ValueError):
                    continue

        # Find actual nearby access roads through Google Roads + Directions.
        # The probes are fixed on purpose. They used to be shifted and rotated by regen_seed,
        # so every regeneration snapped to different roads and the map came back with a
        # different set of street names for the same site.
        probe_points = access_probe_points(route_origin_lat, route_origin_lng)
        targeted_probes = []
        for item in road_data if isinstance(road_data, list) else []:
            if not isinstance(item, dict) or item.get('row_source') == 'manual':
                continue
            expected_name = match_known_road_name(item.get('name'), discoverable_road_names)
            try:
                road_lat = float(item.get('lat'))
                road_lng = float(item.get('lng'))
            except (TypeError, ValueError):
                continue
            if expected_name and math.isfinite(road_lat) and math.isfinite(road_lng):
                targeted_probes.append(((road_lat, road_lng), expected_name))
        probe_entries = targeted_probes + [(point, None) for point in probe_points]

        def _fetch_probe_route(entry):
            probe, expected_name = entry
            p_lat, p_lng = probe
            snapped = _snap_to_roads(p_lat, p_lng, tenant_id=tenant_id)
            dest_lat = snapped['lat'] if snapped else p_lat
            dest_lng = snapped['lng'] if snapped else p_lng
            route = _google_directions_route(
                route_origin_lat, route_origin_lng, dest_lat, dest_lng, tenant_id=tenant_id
            )
            if not route:
                return None

            discovered_name = (route.get('summary') or '').strip()
            if not discovered_name or re.search(r'[A-Za-z]', discovered_name):
                localized_name = _google_reverse_geocode_road(
                    dest_lat, dest_lng, tenant_id=tenant_id
                )
                if localized_name:
                    discovered_name = localized_name
            candidates = [expected_name] if expected_name else discoverable_road_names
            approved_name = match_known_road_name(discovered_name, candidates)
            if not approved_name:
                return None
            return route['coords'], approved_name, _road_name_key(approved_name)

        remaining_approved_names = [
            name for name in discoverable_road_names
            if not any(is_same_road_name(name, accepted) for accepted in seen_road_keys)
        ]
        probe_results = []
        if allow_discovery and remaining_approved_names:
            print("[ACCESS ROADS] Discovering approved nearby roads through Google Maps APIs...")
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, max(1, len(probe_entries)))) as executor:
                probe_results = list(executor.map(_fetch_probe_route, probe_entries))

        for result in probe_results:
            if not result:
                continue
            if any(is_same_road_name(result[1], accepted) for accepted in seen_road_keys):
                continue
            seen_road_keys.add(result[1])
            road_route_mapping.append((result[0], result[1]))
        print(f"[ACCESS ROADS] labels: {[name for _, name in road_route_mapping]}")

        # 3. Draw routes and labels. Highlights first, names last so the gold
        # stroke never covers the road name.
        placed_label_rects = []  # track (x1,y1,x2,y2) of placed labels to avoid overlap
        pending_labels = []
        rendered_roads = []

        if road_route_mapping:
            origin_dx, origin_dy = _latlng_to_pixel_offset(
                route_origin_lat, route_origin_lng, center_lat, center_lng, zoom, scale=scale
            )
            origin_px, origin_py = cx + origin_dx, cy + origin_dy

            for coords, label_text in road_route_mapping:
                pixels = []
                for lat, lng in coords:
                    dx, dy = _latlng_to_pixel_offset(lat, lng, center_lat, center_lng, zoom, scale=scale)
                    pixels.append((int(cx + dx), int(cy + dy)))

                segments = []
                current_segment = []
                for point in pixels:
                    inside = -40 <= point[0] <= img_w + 40 and -40 <= point[1] <= img_h + 40
                    if inside:
                        current_segment.append(point)
                    elif len(current_segment) >= 2:
                        segments.append(current_segment)
                        current_segment = []
                    else:
                        current_segment = []
                if len(current_segment) >= 2:
                    segments.append(current_segment)
                if not segments:
                    continue

                # Draw thick gold road line
                for segment in segments:
                    draw.line(segment, fill=(105, 73, 35, 125), width=18)
                    draw.line(segment, fill=gold_color, width=9)

                route_segment = max(segments, key=len)
                pending_labels.append((route_segment, label_text, coords))

            img = Image.alpha_composite(img, overlay)
            labels_overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
            labels_draw = ImageDraw.Draw(labels_overlay)
            for route_segment, label_text, route_coords in pending_labels:
                best_p = None
                label_key = _road_name_key(label_text)
                label_point = position_by_key.get(label_key)
                label_scale = size_by_key.get(label_key, 1.0)
                if label_point:
                    label_dx, label_dy = _latlng_to_pixel_offset(
                        label_point[0], label_point[1], center_lat, center_lng, zoom, scale=scale
                    )
                    candidate = (int(cx + label_dx), int(cy + label_dy))
                    if 60 <= candidate[0] <= img_w - 60 and 40 <= candidate[1] <= img_h - 40:
                        best_p = candidate
                preferred_candidates = []
                visible_candidates = []
                for p in route_segment:
                    distance = math.sqrt((p[0] - origin_px) ** 2 + (p[1] - origin_py) ** 2)
                    if 90 <= p[0] <= img_w - 90 and 60 <= p[1] <= img_h - 60:
                        visible_candidates.append((distance, p))
                        if distance >= 120:
                            preferred_candidates.append((distance, p))
                candidates = preferred_candidates or visible_candidates
                candidates.sort(key=lambda candidate: -candidate[0])

                label_half_width = min(300, max(70, len(label_text or '') * 7 * label_scale))
                if best_p is None:
                    for _, point in candidates:
                        offset_point = _offset_label_point(point, route_segment, img_w, img_h)
                        lx1 = offset_point[0] - label_half_width
                        ly1 = offset_point[1] - 30
                        lx2 = offset_point[0] + label_half_width
                        ly2 = offset_point[1] + 30
                        collision = any(
                            not (lx2 < rx1 or lx1 > rx2 or ly2 < ry1 or ly1 > ry2)
                            for rx1, ry1, rx2, ry2 in placed_label_rects
                        )
                        if not collision:
                            best_p = offset_point
                            placed_label_rects.append((lx1, ly1, lx2, ly2))
                            break

                if best_p and label_text:
                    _draw_road_label(labels_draw, best_p[0], best_p[1], label_text, label_scale=label_scale)
                    label_point = _pixel_to_latlng(
                        best_p[0], best_p[1], img_w, img_h, center_lat, center_lng, zoom, scale=scale
                    )
                rendered_roads.append({
                    'name': label_text,
                    'points': [[point[0], point[1]] for point in route_coords],
                    'label_point': list(label_point) if label_point else None,
                    'label_scale': label_scale,
                })

            img = Image.alpha_composite(img, labels_overlay)
            img.save(image_path, 'PNG')
            print("[ACCESS ROADS] Successfully drew approved road routes")
            return rendered_roads

        # Never invent a schematic road grid when there is no approved geometry.
        print("[ACCESS ROADS] No approved road route available; leaving the base map unchanged")
        return False
    except Exception as e:
        print(f"[DRAW ACCESS ROADS ERROR] {e}")
        return False


def _get_cached_map_images(tenant_id, presentation_id, expected_lat=None, expected_lng=None, expected_highlight_site=None):
    """Return existing map images for a tenant/presentation if any exist."""
    from db import get_map_images
    existing = get_map_images(tenant_id, presentation_id=presentation_id)
    if not existing:
        return None
    placeholders = {}
    metadata_by_type = {}
    found_types = set()
    for img in existing:
        image_type = img['image_type']
        if image_type in metadata_by_type or not os.path.exists(img['file_path']):
            continue
        found_types.add(image_type)
        placeholders[img['placeholder']] = img['file_path']
        try:
            metadata_by_type[image_type] = json.loads(img.get('metadata_json') or '{}')
        except Exception:
            metadata_by_type[image_type] = {}
    if not placeholders:
        return None
    if any(
        image_type.startswith('access')
        and metadata_by_type.get(image_type, {}).get('access_roads_version') != ACCESS_ROADS_RENDER_VERSION
        for image_type in found_types
    ):
        return None
    if any(
        metadata_by_type.get(image_type, {}).get('map_highlight_version') != MAP_HIGHLIGHT_RENDER_VERSION
        for image_type in found_types
    ):
        return None
    if any(
        metadata_by_type.get(image_type, {}).get('map_label_version') != MAP_LABEL_RENDER_VERSION
        for image_type in found_types
    ):
        return None
    if expected_highlight_site is not None and any(
        metadata_by_type.get(image_type, {}).get('highlight_site') is not bool(expected_highlight_site)
        for image_type in found_types
    ):
        return None
    locations = set()
    for metadata in metadata_by_type.values():
        try:
            if metadata.get('lat') is not None and metadata.get('lng') is not None:
                locations.add((round(float(metadata.get('lat')), 6), round(float(metadata.get('lng')), 6)))
        except (TypeError, ValueError):
            return None
    if len(locations) > 1:
        return None
    if expected_lat is not None and expected_lng is not None and locations:
        cached_lat, cached_lng = next(iter(locations))
        if abs(cached_lat - float(expected_lat)) >= 1e-5 or abs(cached_lng - float(expected_lng)) >= 1e-5:
            return None
    found_base = {t.split('_')[0] for t in found_types}
    meta = next((m for t, m in metadata_by_type.items() if t.startswith('overview')), None)
    if meta is None:
        meta = next(iter(metadata_by_type.values()), {})
    landmarks = next((m.get('landmarks') for m in metadata_by_type.values() if m.get('landmarks')), [])
    landmarks_matrix = next((m.get('landmarks_matrix') for m in metadata_by_type.values() if m.get('landmarks_matrix')), [])
    access_roads = next((m.get('access_roads') for m in metadata_by_type.values() if m.get('access_roads')), [])
    catchment_landmarks = next((m.get('catchment_landmarks') for m in metadata_by_type.values() if m.get('catchment_landmarks')), [])
    landmark_map_items = next((m.get('landmark_map_items') for m in metadata_by_type.values() if m.get('landmark_map_items')), [])
    zooms = {
        image_type: meta['zoom'] for image_type, meta in metadata_by_type.items()
        if isinstance(meta, dict) and meta.get('zoom') is not None
    }
    centers = {
        image_type: {'lat': item['center_lat'], 'lng': item['center_lng']}
        for image_type, item in metadata_by_type.items()
        if isinstance(item, dict) and item.get('center_lat') is not None and item.get('center_lng') is not None
    }
    return {
        'lat': meta.get('lat'),
        'lng': meta.get('lng'),
        'placeholders': placeholders,
        'landmarks': landmarks,
        'landmarks_matrix': landmarks_matrix,
        'access_roads': access_roads,
        'catchment_landmarks': catchment_landmarks,
        'landmark_map_items': landmark_map_items,
        'zooms': zooms,
        'centers': centers,
        'found_types': found_types,
        'found_base': found_base,
        'cached': True,
    }


def _calculate_map_zooms(polygon_coords):
    """Choose presentation-friendly zoom levels for a polygon and its context."""
    zooms = {'overview': 17, 'landmarks': 16, 'access': 18, 'catchment': 12}
    if not polygon_coords or len(polygon_coords) < 3:
        return zooms
    try:
        lats = [point[0] for point in polygon_coords]
        lngs = [point[1] for point in polygon_coords]
        max_dim = max(max(lats) - min(lats), max(lngs) - min(lngs))
        if max_dim <= 0:
            return zooms
        target_pixels = 1280 * 2 * 0.45
        suggested_zoom = math.floor(math.log2((target_pixels * 360) / (max_dim * 256 * 2))) - 1
        # A 7,000 sqm plot is invisible at zoom 17, and the croquis boundary is exact, so
        # the plot view is allowed to go all the way in.
        overview_zoom = max(13, min(19, suggested_zoom))
        zooms.update({
            'overview': overview_zoom,
            'landmarks': max(14, min(17, overview_zoom - 2)),
            'access': max(15, min(17, overview_zoom)),
            'catchment': max(12, min(14, overview_zoom - 4)),
        })
    except (TypeError, ValueError, OverflowError) as error:
        print(f'[DYNAMIC ZOOM ERROR] {error}')
    return zooms


def _resolve_map_coordinates(project_data, tenant_id):
    address = project_data.get('location_address') or project_data.get('location', '')
    maps_link = (
        (address if str(address).startswith('http') else '') or
        project_data.get('location_maps_link') or project_data.get('maps_link')
    )
    confirmed = project_data.get('location_coordinates_confirmed')
    if isinstance(confirmed, str):
        confirmed = confirmed.strip().lower() in {'true', '1', 'yes'}
    lat = _extract_coordinate(
        project_data.get('location_lat') or project_data.get('locationLat') or
        project_data.get('latitude') or project_data.get('lat')
    )
    lng = _extract_coordinate(
        project_data.get('location_lng') or project_data.get('locationLng') or
        project_data.get('longitude') or project_data.get('lng')
    )
    if not confirmed:
        linked_coords = extract_coords_from_maps_link(maps_link) if maps_link else None
        if linked_coords:
            lat, lng = linked_coords['lat'], linked_coords['lng']
        elif maps_link:
            return None, None
    if (lat is None or lng is None) and address and not str(address).startswith('http'):
        geo = geocode_address(address, tenant_id=tenant_id)
        if geo.get('success'):
            lat, lng = geo['lat'], geo['lng']
    return lat, lng


def _overview_polygon(project_data, highlight_site):
    if not highlight_site:
        return None
    value = project_data.get('location_polygon')
    try:
        if isinstance(value, str):
            points = [
                (float(lat.strip()), float(lng.strip()))
                for item in value.split(';') if ',' in item
                for lat, lng in [item.split(',', 1)]
            ]
        elif isinstance(value, list):
            points = [(float(item[0]), float(item[1])) for item in value if len(item) >= 2]
        else:
            points = []
    except (TypeError, ValueError):
        points = []
    return points if len(points) >= 3 else None


def _recompose_overview_map(project_data, tenant_id, effective_id, highlight_site):
    from db import add_map_image, get_map_images, update_map_image
    rows = get_map_images(tenant_id, presentation_id=effective_id)
    by_type = {}
    for row in rows:
        if row.get('image_type') not in by_type and os.path.isfile(row.get('file_path') or ''):
            by_type[row['image_type']] = row
    lat = _extract_coordinate(
        project_data.get('location_lat') or project_data.get('locationLat') or
        project_data.get('latitude') or project_data.get('lat')
    )
    lng = _extract_coordinate(
        project_data.get('location_lng') or project_data.get('locationLng') or
        project_data.get('longitude') or project_data.get('lng')
    )
    if lat is None or lng is None:
        return {'error': 'لم يتم العثور على إحداثيات الموقع المعتمدة'}
    polygon = _overview_polygon(project_data, highlight_site)
    placeholders = {}
    centers = {}
    zooms = {}
    for editable_type in ('overview_editable', 'overview_satellite_editable', 'overview_roadmap_editable'):
        editable = by_type.get(editable_type)
        if not editable:
            continue
        try:
            metadata = json.loads(editable.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        final_type = editable_type.replace('_editable', '')
        final_placeholder = str(editable.get('placeholder') or '').replace('_EDITABLE##', '##')
        final_path = _unique_map_path(tenant_id, effective_id, final_type)
        shutil.copyfile(editable['file_path'], final_path)
        if polygon and not _draw_site_highlight(final_path, center_lat, center_lng, zoom, size=(1280, 720), polygon_coords=polygon, auto_detect_polygon=False, auto_detected=False):
            continue
        if not _overlay_markers(final_path, center_lat, center_lng, zoom, _build_markers(lat, lng), size=(1280, 720)):
            continue
        next_metadata = {**metadata, 'lat': lat, 'lng': lng, 'highlight_site': bool(highlight_site)}
        final = by_type.get(final_type)
        if final:
            update_map_image(final['id'], tenant_id, final_path, final_placeholder, next_metadata)
        else:
            add_map_image(tenant_id, final_type, final_path, final_placeholder, effective_id, next_metadata)
        update_map_image(editable['id'], tenant_id, editable['file_path'], editable['placeholder'], next_metadata)
        placeholders[final_placeholder] = final_path
        centers['overview'] = {'lat': center_lat, 'lng': center_lng}
        zooms['overview'] = zoom
    if not placeholders:
        return {'error': 'نسخة الخريطة النظيفة غير متاحة'}
    return {
        'placeholders': placeholders,
        'centers': centers,
        'zooms': zooms,
        'site_polygon': [list(point) for point in polygon] if polygon else [],
    }


def recompose_overview_map(project_data, tenant_id, presentation_id=None, draft_id=None, highlight_site=True):
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None)
    if not effective_id:
        return {'error': 'معرّف العرض أو المسودة مطلوب'}
    lock_key = (str(tenant_id), str(effective_id))
    with _MAP_GENERATION_LOCKS_GUARD:
        lock = _MAP_GENERATION_LOCKS.setdefault(lock_key, threading.Lock())
    with lock:
        return _recompose_overview_map(project_data, tenant_id, effective_id, highlight_site)


def _recompose_access_map(project_data, tenant_id, effective_id):
    from db import add_map_image, get_map_images, update_map_image
    rows = get_map_images(tenant_id, presentation_id=effective_id)
    by_type = {}
    for row in rows:
        if row.get('image_type') not in by_type and os.path.isfile(row.get('file_path') or ''):
            by_type[row['image_type']] = row
    lat = _extract_coordinate(
        project_data.get('location_lat') or project_data.get('locationLat') or
        project_data.get('latitude') or project_data.get('lat')
    )
    lng = _extract_coordinate(
        project_data.get('location_lng') or project_data.get('locationLng') or
        project_data.get('longitude') or project_data.get('lng')
    )
    if lat is None or lng is None:
        return {'error': 'لم يتم العثور على إحداثيات الموقع المعتمدة'}
    map_styles = project_data.get('map_styles') or {}
    if isinstance(map_styles, str):
        try:
            map_styles = json.loads(map_styles)
        except (TypeError, ValueError):
            map_styles = {}
    draw_compass = project_data.get('draw_compass', True)
    if isinstance(draw_compass, str):
        draw_compass = draw_compass.lower() in {'true', '1', 'yes'}
    for final_type, editable_type in (
        ('access', 'access_editable'),
        ('access_satellite', 'access_satellite_editable'),
        ('access_roadmap', 'access_roadmap_editable'),
    ):
        final = by_type.get(final_type)
        if not final or editable_type in by_type:
            continue
        try:
            metadata = json.loads(final.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        active_maptype = 'satellite' if final_type.endswith('_satellite') else 'roadmap' if final_type.endswith('_roadmap') else str(map_styles.get('access') or project_data.get('map_type') or 'satellite')
        if active_maptype in {'auto', 'both'}:
            active_maptype = 'roadmap' if active_maptype == 'auto' else 'satellite'
        styles = SATELLITE_CLEAN_STYLES if active_maptype == 'satellite' else ACCESS_ROADMAP_STYLES
        cached_base = _map_cache_path(center_lat, center_lng, active_maptype, zoom, None, None, (1280, 720), styles)
        if not os.path.isfile(cached_base):
            continue
        editable_path = _unique_map_path(tenant_id, effective_id, editable_type)
        shutil.copyfile(cached_base, editable_path)
        if active_maptype == 'satellite':
            _apply_sepia_tone(editable_path, intensity=0.35)
            _apply_map_overlay(editable_path, dark_factor=0.10)
        if draw_compass:
            _draw_compass(editable_path, position='top-right')
        editable_placeholder = str(final.get('placeholder') or '')[:-2] + '_EDITABLE##'
        editable_id = add_map_image(tenant_id, editable_type, editable_path, editable_placeholder, effective_id, metadata)
        by_type[editable_type] = {
            'id': editable_id,
            'image_type': editable_type,
            'file_path': editable_path,
            'placeholder': editable_placeholder,
            'metadata_json': json.dumps(metadata, ensure_ascii=False),
        }
    placeholders = {}
    centers = {}
    zooms = {}
    access_roads = []
    for editable_type in ('access_editable', 'access_satellite_editable', 'access_roadmap_editable'):
        editable = by_type.get(editable_type)
        if not editable:
            continue
        try:
            metadata = json.loads(editable.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        final_type = editable_type.replace('_editable', '')
        final_placeholder = str(editable.get('placeholder') or '').replace('_EDITABLE##', '##')
        final_path = _unique_map_path(tenant_id, effective_id, final_type)
        shutil.copyfile(editable['file_path'], final_path)
        rendered_roads = _draw_access_roads(
            final_path, center_lat, center_lng, zoom, scale=2, project_data=project_data,
            tenant_id=tenant_id, origin_lat=lat, origin_lng=lng, allow_discovery=False
        ) or []
        if not _overlay_markers(
            final_path, center_lat, center_lng, zoom,
            [{'lat': lat, 'lng': lng, 'color': MARKER_COLOR_SITE, 'type': 'site', 'label': None}],
            size=(1280, 720)
        ):
            continue
        next_metadata = {
            **metadata,
            'lat': lat,
            'lng': lng,
            'access_roads': rendered_roads,
            'access_roads_version': ACCESS_ROADS_RENDER_VERSION,
            'map_label_version': MAP_LABEL_RENDER_VERSION,
        }
        final = by_type.get(final_type)
        if final:
            update_map_image(final['id'], tenant_id, final_path, final_placeholder, next_metadata)
        else:
            add_map_image(tenant_id, final_type, final_path, final_placeholder, effective_id, next_metadata)
        update_map_image(editable['id'], tenant_id, editable['file_path'], editable['placeholder'], next_metadata)
        placeholders[final_placeholder] = final_path
        placeholders[editable['placeholder']] = editable['file_path']
        centers['access'] = {'lat': center_lat, 'lng': center_lng}
        zooms['access'] = zoom
        if not access_roads:
            access_roads = rendered_roads
    if not placeholders:
        return {'error': 'نسخة خريطة الطرق النظيفة غير متاحة'}
    return {'placeholders': placeholders, 'centers': centers, 'zooms': zooms, 'access_roads': access_roads}


def recompose_access_map(project_data, tenant_id, presentation_id=None, draft_id=None):
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None)
    if not effective_id:
        return {'error': 'معرّف العرض أو المسودة مطلوب'}
    lock_key = (str(tenant_id), str(effective_id))
    with _MAP_GENERATION_LOCKS_GUARD:
        lock = _MAP_GENERATION_LOCKS.setdefault(lock_key, threading.Lock())
    with lock:
        return _recompose_access_map(project_data, tenant_id, effective_id)


def _recompose_catchment_map(project_data, tenant_id, effective_id):
    from db import add_map_image, get_map_images, update_map_image
    rows = get_map_images(tenant_id, presentation_id=effective_id)
    by_type = {}
    for row in rows:
        if row.get('image_type') not in by_type and os.path.isfile(row.get('file_path') or ''):
            by_type[row['image_type']] = row
    lat = _extract_coordinate(project_data.get('location_lat') or project_data.get('locationLat') or project_data.get('lat'))
    lng = _extract_coordinate(project_data.get('location_lng') or project_data.get('locationLng') or project_data.get('lng'))
    if lat is None or lng is None:
        return {'error': 'لم يتم العثور على إحداثيات الموقع المعتمدة'}
    landmarks = project_data.get('catchment_map_landmarks') or []
    if isinstance(landmarks, str):
        try:
            landmarks = json.loads(landmarks)
        except (TypeError, ValueError):
            landmarks = []
    if not isinstance(landmarks, list):
        landmarks = []
    map_styles = project_data.get('map_styles') or {}
    if isinstance(map_styles, str):
        try:
            map_styles = json.loads(map_styles)
        except (TypeError, ValueError):
            map_styles = {}
    draw_compass = project_data.get('draw_compass', True)
    if isinstance(draw_compass, str):
        draw_compass = draw_compass.lower() in {'true', '1', 'yes'}
    rings = catchment_rings(_parse_catchment_zones(project_data.get('catchment_areas', '')))
    for final_type, editable_type in (
        ('catchment', 'catchment_editable'),
        ('catchment_satellite', 'catchment_satellite_editable'),
        ('catchment_roadmap', 'catchment_roadmap_editable'),
    ):
        final = by_type.get(final_type)
        if not final or editable_type in by_type:
            continue
        try:
            metadata = json.loads(final.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        active_maptype = 'satellite' if final_type.endswith('_satellite') else 'roadmap' if final_type.endswith('_roadmap') else str(map_styles.get('catchment') or project_data.get('map_type') or 'satellite')
        if active_maptype in {'auto', 'both'}:
            active_maptype = 'satellite'
        styles = SATELLITE_WIDE_STYLES if active_maptype == 'satellite' else SATELLITE_WITH_LABELS_STYLES
        cached_base = _map_cache_path(center_lat, center_lng, active_maptype, zoom, None, None, (1280, 720), styles)
        if not os.path.isfile(cached_base):
            continue
        editable_path = _unique_map_path(tenant_id, effective_id, editable_type)
        shutil.copyfile(cached_base, editable_path)
        if active_maptype == 'satellite':
            _apply_sepia_tone(editable_path, intensity=0.35)
            _apply_map_overlay(editable_path, dark_factor=0.15)
        if rings:
            _draw_catchment_zones(editable_path, center_lat, center_lng, zoom, rings, scale=2)
        if draw_compass:
            _draw_compass(editable_path, position='top-right')
        editable_placeholder = str(final.get('placeholder') or '')[:-2] + '_EDITABLE##'
        editable_id = add_map_image(tenant_id, editable_type, editable_path, editable_placeholder, effective_id, metadata)
        by_type[editable_type] = {
            'id': editable_id,
            'image_type': editable_type,
            'file_path': editable_path,
            'placeholder': editable_placeholder,
            'metadata_json': json.dumps(metadata, ensure_ascii=False),
        }
    placeholders = {}
    centers = {}
    zooms = {}
    rendered_landmarks = []
    for editable_type in ('catchment_editable', 'catchment_satellite_editable', 'catchment_roadmap_editable'):
        editable = by_type.get(editable_type)
        if not editable:
            continue
        try:
            metadata = json.loads(editable.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        final_type = editable_type.replace('_editable', '')
        final_placeholder = str(editable.get('placeholder') or '').replace('_EDITABLE##', '##')
        final_path = _unique_map_path(tenant_id, effective_id, final_type)
        shutil.copyfile(editable['file_path'], final_path)
        current_landmarks = _draw_catchment_markers(
            final_path, center_lat, center_lng, zoom, landmarks,
            project_data.get('catchment_label_positions'), scale=2
        )
        next_metadata = {**metadata, 'lat': lat, 'lng': lng, 'catchment_landmarks': current_landmarks}
        final = by_type.get(final_type)
        if final:
            update_map_image(final['id'], tenant_id, final_path, final_placeholder, next_metadata)
        else:
            add_map_image(tenant_id, final_type, final_path, final_placeholder, effective_id, next_metadata)
        update_map_image(editable['id'], tenant_id, editable['file_path'], editable['placeholder'], next_metadata)
        placeholders[final_placeholder] = final_path
        placeholders[editable['placeholder']] = editable['file_path']
        centers['catchment'] = {'lat': center_lat, 'lng': center_lng}
        zooms['catchment'] = zoom
        if not rendered_landmarks:
            rendered_landmarks = current_landmarks
    if not placeholders:
        return {'error': 'نسخة خريطة المنطقة النظيفة غير متاحة'}
    return {
        'placeholders': placeholders,
        'centers': centers,
        'zooms': zooms,
        'catchment_landmarks': rendered_landmarks,
    }


def recompose_catchment_map(project_data, tenant_id, presentation_id=None, draft_id=None):
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None)
    if not effective_id:
        return {'error': 'معرّف العرض أو المسودة مطلوب'}
    lock_key = (str(tenant_id), str(effective_id))
    with _MAP_GENERATION_LOCKS_GUARD:
        lock = _MAP_GENERATION_LOCKS.setdefault(lock_key, threading.Lock())
    with lock:
        return _recompose_catchment_map(project_data, tenant_id, effective_id)


def _recompose_landmarks_map(project_data, tenant_id, effective_id):
    from db import add_map_image, get_map_images, update_map_image
    rows = get_map_images(tenant_id, presentation_id=effective_id)
    by_type = {}
    for row in rows:
        if row.get('image_type') not in by_type and os.path.isfile(row.get('file_path') or ''):
            by_type[row['image_type']] = row
    site_lat = _extract_coordinate(project_data.get('location_lat') or project_data.get('locationLat') or project_data.get('lat'))
    site_lng = _extract_coordinate(project_data.get('location_lng') or project_data.get('locationLng') or project_data.get('lng'))
    if site_lat is None or site_lng is None:
        return {'error': 'لم يتم العثور على إحداثيات الموقع المعتمدة'}
    landmarks = project_data.get('landmark_map_items') or []
    if isinstance(landmarks, str):
        try:
            landmarks = json.loads(landmarks)
        except (TypeError, ValueError):
            landmarks = []
    if not isinstance(landmarks, list):
        landmarks = []
    map_styles = project_data.get('map_styles') or {}
    if isinstance(map_styles, str):
        try:
            map_styles = json.loads(map_styles)
        except (TypeError, ValueError):
            map_styles = {}
    draw_compass = project_data.get('draw_compass', True)
    if isinstance(draw_compass, str):
        draw_compass = draw_compass.lower() in {'true', '1', 'yes'}
    for final_type, editable_type in (
        ('landmarks', 'landmarks_editable'),
        ('landmarks_satellite', 'landmarks_satellite_editable'),
        ('landmarks_roadmap', 'landmarks_roadmap_editable'),
    ):
        final = by_type.get(final_type)
        if not final or editable_type in by_type:
            continue
        try:
            metadata = json.loads(final.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        active_maptype = 'satellite' if final_type.endswith('_satellite') else 'roadmap' if final_type.endswith('_roadmap') else str(map_styles.get('landmarks') or project_data.get('map_type') or 'satellite')
        if active_maptype in {'auto', 'both'}:
            active_maptype = 'satellite'
        styles = SATELLITE_WIDE_STYLES if active_maptype == 'satellite' else SATELLITE_WITH_LABELS_STYLES
        cached_base = _map_cache_path(center_lat, center_lng, active_maptype, zoom, None, None, (1280, 720), styles)
        if not os.path.isfile(cached_base):
            continue
        editable_path = _unique_map_path(tenant_id, effective_id, editable_type)
        shutil.copyfile(cached_base, editable_path)
        if active_maptype == 'satellite':
            _apply_sepia_tone(editable_path, intensity=0.35)
            _apply_map_overlay(editable_path, dark_factor=0.20)
        if draw_compass:
            _draw_compass(editable_path, position='top-right')
        editable_placeholder = str(final.get('placeholder') or '')[:-2] + '_EDITABLE##'
        editable_id = add_map_image(tenant_id, editable_type, editable_path, editable_placeholder, effective_id, metadata)
        by_type[editable_type] = {
            'id': editable_id,
            'image_type': editable_type,
            'file_path': editable_path,
            'placeholder': editable_placeholder,
            'metadata_json': json.dumps(metadata, ensure_ascii=False),
        }
    placeholders = {}
    centers = {}
    zooms = {}
    rendered_landmarks = []
    for editable_type in ('landmarks_editable', 'landmarks_satellite_editable', 'landmarks_roadmap_editable'):
        editable = by_type.get(editable_type)
        if not editable:
            continue
        try:
            metadata = json.loads(editable.get('metadata_json') or '{}')
            center_lat = float(metadata.get('center_lat'))
            center_lng = float(metadata.get('center_lng'))
            zoom = int(metadata.get('zoom'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        final_type = editable_type.replace('_editable', '')
        final_placeholder = str(editable.get('placeholder') or '').replace('_EDITABLE##', '##')
        final_path = _unique_map_path(tenant_id, effective_id, final_type)
        shutil.copyfile(editable['file_path'], final_path)
        current_landmarks = _draw_catchment_markers(
            final_path, center_lat, center_lng, zoom, landmarks,
            project_data.get('landmark_label_positions'), scale=2, site_lat=site_lat, site_lng=site_lng
        )
        next_metadata = {**metadata, 'lat': site_lat, 'lng': site_lng, 'landmark_map_items': current_landmarks}
        final = by_type.get(final_type)
        if final:
            update_map_image(final['id'], tenant_id, final_path, final_placeholder, next_metadata)
        else:
            add_map_image(tenant_id, final_type, final_path, final_placeholder, effective_id, next_metadata)
        update_map_image(editable['id'], tenant_id, editable['file_path'], editable['placeholder'], next_metadata)
        placeholders[final_placeholder] = final_path
        placeholders[editable['placeholder']] = editable['file_path']
        centers['landmarks'] = {'lat': center_lat, 'lng': center_lng}
        zooms['landmarks'] = zoom
        if not rendered_landmarks:
            rendered_landmarks = current_landmarks
    if not placeholders:
        return {'error': 'نسخة خريطة المعالم النظيفة غير متاحة'}
    return {
        'placeholders': placeholders,
        'centers': centers,
        'zooms': zooms,
        'landmark_map_items': rendered_landmarks,
    }


def recompose_landmarks_map(project_data, tenant_id, presentation_id=None, draft_id=None):
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None)
    if not effective_id:
        return {'error': 'معرّف العرض أو المسودة مطلوب'}
    lock_key = (str(tenant_id), str(effective_id))
    with _MAP_GENERATION_LOCKS_GUARD:
        lock = _MAP_GENERATION_LOCKS.setdefault(lock_key, threading.Lock())
    with lock:
        return _recompose_landmarks_map(project_data, tenant_id, effective_id)


def generate_all_map_images(project_data, tenant_id, presentation_id=None, force=False, branding=None, draft_id=None, highlight_site=True):
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None) or (project_data or {}).get('draft_id') or (project_data or {}).get('draftId') or 'unscoped'
    lock_key = (str(tenant_id), str(effective_id))
    with _MAP_GENERATION_LOCKS_GUARD:
        lock = _MAP_GENERATION_LOCKS.setdefault(lock_key, threading.Lock())
    with lock:
        return _generate_all_map_images(project_data, tenant_id, presentation_id, force, branding, draft_id, highlight_site)


def _generate_all_map_images(project_data, tenant_id, presentation_id=None, force=False, branding=None, draft_id=None, highlight_site=True):
    """
    Generate all map images needed for a project.
    Returns dict of placeholder -> file_path.
    If force=False and valid cached images exist, returns them without calling Google APIs.
    """
    if not _has_api_key():
        return {'error': 'Google Maps API key not configured'}

    limit_error = _check_maps_rate_limit(tenant_id)
    if limit_error:
        return limit_error

    address = project_data.get('location_address') or project_data.get('location', '')
    maps_link = (
        (address if str(address).startswith('http') else '') or
        project_data.get('location_maps_link') or project_data.get('maps_link')
    )
    lat, lng = _resolve_map_coordinates(project_data, tenant_id)
    if lat is None or lng is None:
        if maps_link:
            return {'error': 'تعذر استخراج الإحداثيات من رابط Google Maps'}
        return {'error': 'لم يتم العثور على موقع أو إحداثيات للمشروع. يرجى إدخال عنوان المشروع أو رابط Google Maps في البيانات.'}

    enabled_maps = project_data.get('enabled_maps')
    if isinstance(enabled_maps, str):
        try:
            enabled_maps = json.loads(enabled_maps)
        except Exception:
            enabled_maps = None
    if not isinstance(enabled_maps, list):
        enabled_maps = ['overview', 'landmarks', 'access', 'catchment']

    # Select each map's structured rows before any geocoding. A structured table is
    # authoritative when present; legacy text remains a compatibility fallback.
    nearby_structured = project_data.get('nearby_landmarks_data')
    city_structured = project_data.get('city_landmarks_data')
    nearby_rows = select_map_landmark_rows(nearby_structured)
    city_rows = select_map_landmark_rows(city_structured)
    if nearby_structured is None:
        nearby_text = project_data.get('nearby_landmarks', '')
        nearby_rows = _parse_landmarks_text(nearby_text)[:7] if isinstance(nearby_text, str) else []
    if city_structured is None:
        city_text = project_data.get('city_landmarks', '')
        city_rows = _parse_landmarks_text(city_text)[:7] if isinstance(city_text, str) else []
    landmarks = _merge_landmark_data([], nearby_rows) if 'landmarks' in enabled_maps else []
    city_landmarks = _merge_landmark_data([], city_rows) if 'catchment' in enabled_maps else []
    zones = _parse_catchment_zones(project_data.get('catchment_areas', ''))

    draft_id = draft_id or project_data.get('draft_id') or project_data.get('draftId')
    effective_pres_id = presentation_id or (f"draft_{draft_id}" if draft_id else None)

    def _close(a, b):
        try:
            return a is not None and b is not None and abs(float(a) - float(b)) < 1e-5
        except Exception:
            return False

    if not force and not project_data.get('refresh_maps') and effective_pres_id:
        cached = _get_cached_map_images(
            tenant_id,
            effective_pres_id,
            expected_lat=lat,
            expected_lng=lng,
            expected_highlight_site=highlight_site,
        )
        if cached and _close(cached.get('lat'), lat) and _close(cached.get('lng'), lng):
            found_base = cached.get('found_base') or set()
            required_base = {t for t in enabled_maps if t not in ('streetview',)}
            if not (required_base - found_base):
                return cached

    if force and effective_pres_id:
        from db import delete_map_images
        delete_map_images(tenant_id, presentation_id=effective_pres_id)

    result = {
        'lat': lat,
        'lng': lng,
        'placeholders': {},
        'landmarks': [],
        'landmarks_matrix': [],
        'access_roads': [],
        'catchment_landmarks': [],
        'landmark_map_items': [],
    }

    polygon_coords = None
    poly_data = project_data.get('location_polygon')
    user_polygon_used = False
    if highlight_site and poly_data:
        try:
            if isinstance(poly_data, str):
                polygon_coords = []
                for pt in poly_data.split(';'):
                    if ',' in pt:
                        plat, plng = pt.split(',')
                        polygon_coords.append((float(plat.strip()), float(plng.strip())))
            elif isinstance(poly_data, list):
                polygon_coords = [(float(pt[0]), float(pt[1])) for pt in poly_data if len(pt) >= 2]
            if polygon_coords and len(polygon_coords) >= 3:
                user_polygon_used = True
                print(f"[POLYGON] Using user-provided polygon with {len(polygon_coords)} points")
        except Exception as e:
            print(f"[POLYGON PARSE ERROR] {e}")

    # Croquis coordinates are the real plot boundary, so they outrank any guess.
    if highlight_site and not user_polygon_used and (not polygon_coords or len(polygon_coords) < 3):
        survey_polygon = survey_polygon_from_project(project_data, lat, lng)
        if survey_polygon and len(survey_polygon) >= 3:
            polygon_coords = survey_polygon
            print(f"[POLYGON] Using croquis survey polygon with {len(polygon_coords)} points")

    # Try to auto-detect a building/compound polygon from OSM
    if highlight_site and not user_polygon_used and (not polygon_coords or len(polygon_coords) < 3):
        cache_key = f"{lat:.6f},{lng:.6f}"
        if cache_key in _osm_polygon_cache:
            osm_poly = _osm_polygon_cache[cache_key]
        else:
            osm_poly = _fetch_osm_polygon(lat, lng, radius_m=400)
            if osm_poly:
                _osm_polygon_cache[cache_key] = osm_poly
        if osm_poly and len(osm_poly) >= 3 and not _is_viewport_rectangle(osm_poly):
            polygon_coords = osm_poly
            print(f"[POLYGON] Using OSM building polygon with {len(polygon_coords)} points")

    if highlight_site and not user_polygon_used and (not polygon_coords or len(polygon_coords) < 3):
        bounds_polygon = _google_bounds_polygon(lat, lng, tenant_id=tenant_id)
        if bounds_polygon:
            polygon_coords = bounds_polygon
            print('[POLYGON] Using the Google geocoding bounds rectangle')

    auto_detected = not user_polygon_used
    result['site_polygon'] = [list(point) for point in polygon_coords] if polygon_coords and len(polygon_coords) >= 3 else []

    # Compute presentation-friendly zoom levels from the selected boundary.
    zooms = _calculate_map_zooms(polygon_coords)
    refresh_maps = force or bool(project_data.get('refresh_maps'))
    try:
        regen_seed = int(project_data.get('regen_seed') or 0)
    except (TypeError, ValueError):
        regen_seed = 0
    # A regenerate must not re-frame a map whose extent is derived from a real boundary:
    # shifting the zoom by two levels shrank the plot back to a dot.
    if project_data.get('refresh_maps') and regen_seed and not (polygon_coords and len(polygon_coords) >= 3):
        zoom_shift = MAP_REGEN_ZOOM_OFFSETS[regen_seed % len(MAP_REGEN_ZOOM_OFFSETS)]
        for map_key in enabled_maps:
            if map_key in zooms:
                zooms[map_key] = max(12, min(20, int(zooms[map_key]) + zoom_shift))
    overview_zoom = zooms['overview']
    landmarks_zoom = zooms['landmarks']
    access_zoom = access_map_zoom(lat, zooms['access'])
    catchment_zoom = zooms['catchment']

    if polygon_coords and len(polygon_coords) >= 3:
        print(
            f"[DYNAMIC ZOOM] overview={overview_zoom}, landmarks={landmarks_zoom}, "
            f"access={access_zoom}, catchment={catchment_zoom}"
        )

    map_center_lat, map_center_lng = lat, lng
    if polygon_coords and len(polygon_coords) >= 3:
        map_center_lat = (min(point[0] for point in polygon_coords) + max(point[0] for point in polygon_coords)) / 2
        map_center_lng = (min(point[1] for point in polygon_coords) + max(point[1] for point in polygon_coords)) / 2

    result['zooms'] = {
        'overview': overview_zoom,
        'landmarks': landmarks_zoom,
        'access': access_zoom,
        'catchment': catchment_zoom,
    }
    # The client converts clicks to coordinates against these, so it must know the centre each
    # image was actually rendered around. Assuming the site pin put every drawn boundary off by
    # the distance between the pin and the plot centroid.
    result['centers'] = {
        'overview': {'lat': map_center_lat, 'lng': map_center_lng},
        'landmarks': {'lat': map_center_lat, 'lng': map_center_lng},
        'access': {'lat': map_center_lat, 'lng': map_center_lng},
        'catchment': {'lat': lat, 'lng': lng},
    }

    # The approved latitude/longitude is the user-controlled pin for every map. The boundary may
    # center the viewport, but it must never move that saved pin implicitly.
    marker_lat, marker_lng = lat, lng

    # Parse UI element flags (compass, inset map)
    draw_compass = project_data.get('draw_compass', True)
    if isinstance(draw_compass, str):
        draw_compass = draw_compass.lower() in ('true', '1', 'yes')
    elif not isinstance(draw_compass, bool):
        if branding and 'draw_compass' in branding:
            draw_compass = bool(branding['draw_compass'])
        else:
            draw_compass = True

    draw_inset = project_data.get('draw_inset', True)
    if isinstance(draw_inset, str):
        draw_inset = draw_inset.lower() in ('true', '1', 'yes')
    elif not isinstance(draw_inset, bool):
        if branding and 'draw_inset' in branding:
            draw_inset = bool(branding['draw_inset'])
        else:
            draw_inset = True

    # Parse per-map style preferences (satellite/roadmap/terrain/hybrid/both)
    # Default: all satellite. Employee can override per-map via map_styles dict.
    # Fallback to tenant branding defaults if not in project_data
    map_styles_raw = project_data.get('map_styles', {})
    if isinstance(map_styles_raw, str):
        try:
            map_styles_raw = json.loads(map_styles_raw)
        except Exception:
            map_styles_raw = {}
    if not isinstance(map_styles_raw, dict):
        map_styles_raw = {}
    else:
        map_styles_raw = dict(map_styles_raw)
    # default_map_type is only a fallback; explicit per-map tenant settings win.
    default_map_type = (
        project_data.get('map_type')
        or (branding.get('default_map_type') if branding else None)
        or 'satellite'
    )
    if branding:
        for key in ('overview', 'landmarks', 'access', 'catchment'):
            if not map_styles_raw.get(key):
                map_styles_raw[key] = branding.get(f'map_style_{key}') or default_map_type
    VALID_MAPTYPES = {'auto', 'satellite', 'roadmap', 'terrain', 'hybrid', 'both'}
    map_styles = {}
    for key in ('overview', 'landmarks', 'access', 'catchment'):
        val = map_styles_raw.get(key) or default_map_type
        if val not in VALID_MAPTYPES:
            val = 'auto'
        map_styles[key] = 'roadmap' if val == 'auto' and key == 'access' else 'satellite' if val == 'auto' else val

    landmark_radius_m = 20000
    city_context = project_data.get('city') or project_data.get('location', '')

    # Preserve the selected table order through geocoding and filtering so marker
    # numbering stays aligned with the approved rows.
    def _resolve_map_landmarks(rows, search_radius_m, maximum_distance_m=None):
        resolved = []
        for landmark in rows:
            if landmark.get('lat') is None or landmark.get('lng') is None:
                place = find_place_near(landmark.get('name'), lat, lng, radius_m=search_radius_m)
                if place:
                    landmark['lat'] = place['lat']
                    landmark['lng'] = place['lng']
                else:
                    # Only the city is appended here: adding the project address made Google
                    # return the project's own coordinates for every landmark.
                    query = f"{landmark.get('name')}, {city_context}" if city_context else landmark.get('name')
                    geo = geocode_address(query, tenant_id=tenant_id)
                    if geo.get('success'):
                        landmark['lat'] = geo['lat']
                        landmark['lng'] = geo['lng']
            if landmark.get('lat') is None or landmark.get('lng') is None:
                continue
            distance_meters = _distance_meters(lat, lng, landmark['lat'], landmark['lng'])
            if distance_meters < 50:
                continue
            if maximum_distance_m is not None and distance_meters > maximum_distance_m:
                continue
            landmark['distance_meters'] = round(distance_meters)
            resolved.append(landmark)
        return resolved

    # Retain automatic discovery only for old projects that have no structured
    # nearby-landmark table. An explicit table, including an empty one, is authoritative.
    if 'landmarks' in enabled_maps and nearby_structured is None and not landmarks:
        places = get_nearby_landmarks(
            lat, lng, radius=landmark_radius_m, max_results=7, include_all=True
        )
        if places.get('success'):
            landmarks = (places.get('landmarks') or [])[:7]
            _record_maps_call(tenant_id)

    if landmarks:
        landmarks = _resolve_map_landmarks(
            landmarks, landmark_radius_m, maximum_distance_m=landmark_radius_m
        )
    if city_landmarks:
        city_search_radius_m = min(
            50000,
            max([landmark_radius_m] + [float(zone.get('km') or 0) * 1000 for zone in zones]),
        )
        city_landmarks = _resolve_map_landmarks(city_landmarks, city_search_radius_m)
    result['landmarks'] = landmarks

    # Get driving times and distances only for the nearby rows used by the landmarks map.
    if landmarks and project_data.get('calculate_landmark_driving', True) is not False:
        matrix = get_drive_matrix((lat, lng), landmarks)
        if matrix:
            for i, landmark in enumerate(landmarks):
                if i >= len(matrix):
                    break
                entry = matrix[i]
                if not entry.get('name'):
                    entry['name'] = landmark.get('name', '')
                if entry['duration_min'] is None:
                    continue
                landmark['duration_minutes'] = entry['duration_min']
                landmark['distance_text'] = entry.get('distance_text') or f"{entry['distance_km']} كم"
            # Only rows with real Google numbers are handed to the AI prompt.
            usable = [item for item in matrix if item.get('duration_min') is not None]
            if usable:
                project_data['landmarks_matrix'] = usable
                result['landmarks_matrix'] = usable
            _record_maps_call(tenant_id)

    # Helper: pick styles based on maptype
    def _styles_for(maptype, default_styles, map_kind=None):
        """Satellite keeps custom tones; access roadmap hides native labels so our names stay readable."""
        if maptype == 'satellite':
            return default_styles
        if map_kind == 'access':
            return ACCESS_ROADMAP_STYLES
        return []

    # Generate map_overview. This view contains only the site pin/highlight.
    if 'overview' in enabled_maps:
        overview_markers = _build_markers(marker_lat, marker_lng)
        overview_mt = map_styles['overview']
        if overview_mt == 'both':
            styles_to_gen = [('satellite', '##MAP_OVERVIEW_SATELLITE##', 'overview_satellite'),
                             ('roadmap', '##MAP_OVERVIEW_ROADMAP##', 'overview_roadmap')]
        else:
            styles_to_gen = [(overview_mt, '##MAP_OVERVIEW##', 'overview')]
        editable_placeholders = {
            '##MAP_OVERVIEW##': '##MAP_OVERVIEW_EDITABLE##',
            '##MAP_OVERVIEW_SATELLITE##': '##MAP_OVERVIEW_SATELLITE_EDITABLE##',
            '##MAP_OVERVIEW_ROADMAP##': '##MAP_OVERVIEW_ROADMAP_EDITABLE##',
        }

        for active_mt, placeholder, img_suffix in styles_to_gen:
            overview_path = _unique_map_path(tenant_id, effective_pres_id, img_suffix)
            overview_res = get_static_map(map_center_lat, map_center_lng, zoom=overview_zoom, size=(1280, 720), output_path=overview_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_WITH_LABELS_STYLES), bypass_cache=refresh_maps)
            if overview_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(overview_path, intensity=0.35)
                    _apply_map_overlay(overview_path, dark_factor=0.12)
                if draw_compass:
                    _draw_compass(overview_path, position='top-right')
                if draw_inset:
                    _draw_inset_map(overview_path, lat, lng, inset_size=180)
                editable_placeholder = editable_placeholders[placeholder]
                editable_suffix = img_suffix + '_editable'
                editable_path = _unique_map_path(tenant_id, effective_pres_id, editable_suffix)
                shutil.copyfile(overview_path, editable_path)
                metadata = {'lat': lat, 'lng': lng, 'zoom': overview_zoom, 'center_lat': map_center_lat, 'center_lng': map_center_lng, 'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION, 'map_label_version': MAP_LABEL_RENDER_VERSION, 'highlight_site': bool(highlight_site), 'landmarks_matrix': result.get('landmarks_matrix') or []}
                if highlight_site:
                    _draw_site_highlight(overview_path, map_center_lat, map_center_lng, overview_zoom, size=(1280, 720), polygon_coords=polygon_coords, auto_detect_polygon=False, auto_detected=auto_detected)
                _overlay_markers(overview_path, map_center_lat, map_center_lng, overview_zoom, overview_markers, size=(1280, 720))
                result['placeholders'][placeholder] = overview_path
                result['placeholders'][editable_placeholder] = editable_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, img_suffix, overview_path, placeholder, effective_pres_id, metadata)
                add_map_image(tenant_id, editable_suffix, editable_path, editable_placeholder, effective_pres_id, metadata)

    # Generate map_landmarks (closer zoom)
    if 'landmarks' in enabled_maps:
        # The landmark view uses only the selected nearby table rows and fits that content.
        shown_landmarks = [item for item in landmarks if item.get('distance_meters')]
        if shown_landmarks:
            radius_km = max(item['distance_meters'] for item in shown_landmarks) / 1000.0
            radius_km = max(0.6, min(LANDMARKS_MAX_RADIUS_KM, radius_km * 1.1))
            fitted_zoom = zoom_for_radius_km(lat, radius_km)
            if fitted_zoom:
                landmarks_zoom = fitted_zoom
                result['zooms']['landmarks'] = landmarks_zoom
                print(f'[LANDMARKS] {len(shown_landmarks)} landmarks within {radius_km:.1f} km, zoom {landmarks_zoom}')
        landmarks_mt = map_styles['landmarks']
        if landmarks_mt == 'both':
            styles_to_gen = [('satellite', '##MAP_LANDMARKS_SATELLITE##', 'landmarks_satellite'),
                             ('roadmap', '##MAP_LANDMARKS_ROADMAP##', 'landmarks_roadmap')]
        else:
            styles_to_gen = [(landmarks_mt, '##MAP_LANDMARKS##', 'landmarks')]

        editable_placeholders = {
            '##MAP_LANDMARKS##': '##MAP_LANDMARKS_EDITABLE##',
            '##MAP_LANDMARKS_SATELLITE##': '##MAP_LANDMARKS_SATELLITE_EDITABLE##',
            '##MAP_LANDMARKS_ROADMAP##': '##MAP_LANDMARKS_ROADMAP_EDITABLE##',
        }
        for active_mt, placeholder, img_suffix in styles_to_gen:
            landmarks_path = _unique_map_path(tenant_id, effective_pres_id, img_suffix)
            lm_res = get_static_map(map_center_lat, map_center_lng, zoom=landmarks_zoom, size=(1280, 720), output_path=landmarks_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_WIDE_STYLES), bypass_cache=refresh_maps)
            if lm_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(landmarks_path, intensity=0.35)
                    _apply_map_overlay(landmarks_path, dark_factor=0.20)
                if draw_compass:
                    _draw_compass(landmarks_path, position='top-right')
                if draw_inset:
                    _draw_inset_map(landmarks_path, lat, lng, inset_size=180)
                editable_placeholder = editable_placeholders[placeholder]
                editable_suffix = img_suffix + '_editable'
                editable_path = _unique_map_path(tenant_id, effective_pres_id, editable_suffix)
                shutil.copyfile(landmarks_path, editable_path)
                rendered_landmarks = _draw_catchment_markers(
                    landmarks_path, map_center_lat, map_center_lng, landmarks_zoom, shown_landmarks or landmarks,
                    project_data.get('landmark_label_positions'), scale=2, site_lat=marker_lat, site_lng=marker_lng
                )
                if not result['landmark_map_items']:
                    result['landmark_map_items'] = rendered_landmarks
                metadata = {
                    'lat': lat,
                    'lng': lng,
                    'zoom': landmarks_zoom,
                    'center_lat': map_center_lat,
                    'center_lng': map_center_lng,
                    'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION,
                    'map_label_version': MAP_LABEL_RENDER_VERSION,
                    'highlight_site': bool(highlight_site),
                    'landmarks': landmarks,
                    'landmarks_matrix': result.get('landmarks_matrix') or [],
                    'landmark_map_items': rendered_landmarks,
                }
                result['placeholders'][placeholder] = landmarks_path
                result['placeholders'][editable_placeholder] = editable_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, img_suffix, landmarks_path, placeholder, effective_pres_id, metadata)
                add_map_image(tenant_id, editable_suffix, editable_path, editable_placeholder, effective_pres_id, metadata)

    # Generate map_access
    if 'access' in enabled_maps:
        access_markers = [{'lat': marker_lat, 'lng': marker_lng, 'color': MARKER_COLOR_SITE, 'type': 'site', 'label': None}]
        access_mt = map_styles['access']
        if access_mt == 'both':
            styles_to_gen = [('satellite', '##MAP_ACCESS_SATELLITE##', 'access_satellite'),
                             ('roadmap', '##MAP_ACCESS_ROADMAP##', 'access_roadmap')]
        else:
            styles_to_gen = [(access_mt, '##MAP_ACCESS##', 'access')]

        editable_placeholders = {
            '##MAP_ACCESS##': '##MAP_ACCESS_EDITABLE##',
            '##MAP_ACCESS_SATELLITE##': '##MAP_ACCESS_SATELLITE_EDITABLE##',
            '##MAP_ACCESS_ROADMAP##': '##MAP_ACCESS_ROADMAP_EDITABLE##',
        }
        for active_mt, placeholder, img_suffix in styles_to_gen:
            access_path = _unique_map_path(tenant_id, effective_pres_id, img_suffix)
            access_res = get_static_map(map_center_lat, map_center_lng, zoom=access_zoom, size=(1280, 720), output_path=access_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_CLEAN_STYLES, 'access'), bypass_cache=refresh_maps)
            if access_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(access_path, intensity=0.35)
                    _apply_map_overlay(access_path, dark_factor=0.10)
                if draw_compass:
                    _draw_compass(access_path, position='top-right')
                editable_placeholder = editable_placeholders[placeholder]
                editable_suffix = img_suffix + '_editable'
                editable_path = _unique_map_path(tenant_id, effective_pres_id, editable_suffix)
                shutil.copyfile(access_path, editable_path)
                rendered_roads = _draw_access_roads(
                    access_path,
                    map_center_lat,
                    map_center_lng,
                    access_zoom,
                    scale=2,
                    project_data=project_data,
                    tenant_id=tenant_id,
                    origin_lat=marker_lat,
                    origin_lng=marker_lng,
                ) or []
                if not result['access_roads']:
                    result['access_roads'] = rendered_roads
                _overlay_markers(access_path, map_center_lat, map_center_lng, access_zoom, access_markers, size=(1280, 720))
                metadata = {
                    'lat': lat,
                    'lng': lng,
                    'zoom': access_zoom,
                    'center_lat': map_center_lat,
                    'center_lng': map_center_lng,
                    'access_roads_version': ACCESS_ROADS_RENDER_VERSION,
                    'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION, 'map_label_version': MAP_LABEL_RENDER_VERSION,
                    'highlight_site': bool(highlight_site),
                    'landmarks_matrix': result.get('landmarks_matrix') or [],
                    'access_roads': rendered_roads,
                }
                result['placeholders'][placeholder] = access_path
                result['placeholders'][editable_placeholder] = editable_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, img_suffix, access_path, placeholder, effective_pres_id, metadata)
                add_map_image(tenant_id, editable_suffix, editable_path, editable_placeholder, effective_pres_id, metadata)



    # Generate map_catchment
    if 'catchment' in enabled_maps:
        # zones were pre-parsed before the cache check
        rings = catchment_rings(zones)
        if rings:
            fitted_zoom = zoom_for_radius_km(lat, max(ring['km'] for ring in rings))
            if fitted_zoom:
                catchment_zoom = fitted_zoom
                result['zooms']['catchment'] = catchment_zoom
                print(f"[CATCHMENT] {len(rings)} rings, outer {max(ring['km'] for ring in rings):.1f} km, zoom {catchment_zoom}")
        catchment_mt = map_styles['catchment']
        if catchment_mt == 'both':
            styles_to_gen = [('satellite', '##MAP_CATCHMENT_SATELLITE##', 'catchment_satellite'),
                             ('roadmap', '##MAP_CATCHMENT_ROADMAP##', 'catchment_roadmap')]
        else:
            styles_to_gen = [(catchment_mt, '##MAP_CATCHMENT##', 'catchment')]

        editable_placeholders = {
            '##MAP_CATCHMENT##': '##MAP_CATCHMENT_EDITABLE##',
            '##MAP_CATCHMENT_SATELLITE##': '##MAP_CATCHMENT_SATELLITE_EDITABLE##',
            '##MAP_CATCHMENT_ROADMAP##': '##MAP_CATCHMENT_ROADMAP_EDITABLE##',
        }
        for active_mt, placeholder, img_suffix in styles_to_gen:
            catchment_path = _unique_map_path(tenant_id, effective_pres_id, img_suffix)
            # Fetch clean map without the API-drawn paths, as we will draw them with PIL for premium styling.
            catchment_res = get_static_map(lat, lng, zoom=catchment_zoom, paths=None, size=(1280, 720), output_path=catchment_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_WIDE_STYLES), bypass_cache=refresh_maps)
            if catchment_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(catchment_path, intensity=0.35)
                    _apply_map_overlay(catchment_path, dark_factor=0.15)
                # Draw the anti-aliased concentric rings with time label pills
                if rings:
                    _draw_catchment_zones(catchment_path, lat, lng, catchment_zoom, rings, scale=2)
                if draw_compass:
                    _draw_compass(catchment_path, position='top-right')
                if draw_inset:
                    _draw_inset_map(catchment_path, lat, lng, inset_size=180)
                editable_placeholder = editable_placeholders[placeholder]
                editable_suffix = img_suffix + '_editable'
                editable_path = _unique_map_path(tenant_id, effective_pres_id, editable_suffix)
                shutil.copyfile(catchment_path, editable_path)
                rendered_landmarks = _draw_catchment_markers(
                    catchment_path, lat, lng, catchment_zoom, city_landmarks,
                    project_data.get('catchment_label_positions'), scale=2
                )
                if not result['catchment_landmarks']:
                    result['catchment_landmarks'] = rendered_landmarks
                metadata = {
                    'lat': lat,
                    'lng': lng,
                    'zoom': catchment_zoom,
                    'center_lat': lat,
                    'center_lng': lng,
                    'map_highlight_version': MAP_HIGHLIGHT_RENDER_VERSION,
                    'map_label_version': MAP_LABEL_RENDER_VERSION,
                    'highlight_site': bool(highlight_site),
                    'zones': zones,
                    'landmarks_matrix': result.get('landmarks_matrix') or [],
                    'catchment_landmarks': rendered_landmarks,
                }
                result['placeholders'][placeholder] = catchment_path
                result['placeholders'][editable_placeholder] = editable_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, img_suffix, catchment_path, placeholder, effective_pres_id, metadata)
                add_map_image(tenant_id, editable_suffix, editable_path, editable_placeholder, effective_pres_id, metadata)

    return result


def _unique_map_path(tenant_id, presentation_id, image_type):
    """Generate a unique file path for a map image."""
    safe_tenant = str(tenant_id).replace('-', '')[:12]
    pres_part = str(presentation_id).replace('-', '')[:12] if presentation_id else 'draft'
    filename = f"{safe_tenant}_{pres_part}_{image_type}_{uuid.uuid4().hex[:8]}.png"
    return os.path.join(MAPS_DIR, filename)


def _extract_coordinate(value):
    """Extract float coordinate from string or number."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        val_str = value.strip()
        if not val_str:
            return None
        match = re.search(r'(-?\d+\.\d+)', val_str)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
    return None


def _parse_landmarks_text(text):
    """Parse landmark text into structured list with name, duration_minutes, and distance_km."""
    if not text:
        return []
    landmarks = []
    for line in text.strip().split('\n'):
        line = line.strip().lstrip('-').lstrip('•').strip()
        if not line:
            continue

        duration = None
        distance = None

        dur_match = re.search(r'(\d+)\s*(?:دقيقة|دقائق|د|min|mins|minutes)', line, re.IGNORECASE)
        if dur_match:
            duration = int(dur_match.group(1))

        dist_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:كم|كـم|km|kms|kilometer|kilometers)', line, re.IGNORECASE)
        if dist_match:
            distance = float(dist_match.group(1))

        clean_name = line
        if dur_match:
            clean_name = clean_name.replace(dur_match.group(0), '')
        if dist_match:
            clean_name = clean_name.replace(dist_match.group(0), '')

        category = ''
        category_match = re.search(r'(?:^|\s)[—\-]\s*(ترفيهي|تعليمي|صحي|تجاري|ديني(?: ومركزي)?|ثقافي/سياحي|حكومي/خدمي|اجتماعي/خدمي)\s*(?:[—\-]|$)', clean_name)
        if category_match:
            category = category_match.group(1)
            clean_name = clean_name.replace(category_match.group(0), ' ')
        clean_name = re.sub(r'[\-\(\)\,\،\s—–]+', ' ', clean_name).strip()
        if not clean_name:
            clean_name = line

        landmarks.append({
            'name': clean_name,
            'category': category,
            'duration_minutes': duration,
            'distance_km': distance,
            'distance_text': f"{distance} كم" if distance is not None else None,
            'lat': None,
            'lng': None,
        })
    return landmarks


def select_map_landmark_rows(structured, limit=7):
    """Return the approved landmark rows for a map without changing their input order."""
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except (TypeError, ValueError):
            return []
    if not isinstance(structured, list):
        return []

    rows = [dict(item) for item in structured if isinstance(item, dict)]
    selected = [
        item for item in rows
        if item.get('show_on_map') is True or item.get('selected') is True
    ]
    try:
        row_limit = max(0, min(7, int(limit)))
    except (TypeError, ValueError):
        row_limit = 7
    return (selected or rows)[:row_limit]


def _merge_landmark_data(landmarks, structured):
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except (TypeError, ValueError):
            return landmarks
    if not isinstance(structured, list):
        return landmarks

    def normalized_name(value):
        return re.sub(r'\s+', ' ', _strip_arabic_diacritics(str(value or '')).strip()).casefold()

    def numeric(value):
        if value in (None, ''):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    by_name = {normalized_name(item.get('name')): item for item in landmarks if item.get('name')}
    for item in structured:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or item.get('title') or item.get('description') or '').strip()
        key = normalized_name(name)
        if not key:
            continue
        target = by_name.get(key)
        if target is None:
            target = {
                'name': name,
                'category': item.get('category') or item.get('type') or '',
                'duration_minutes': item.get('duration_minutes') or item.get('duration_min'),
                'distance_km': item.get('distance_km') or item.get('distance'),
                'distance_text': item.get('distance_text'),
                'lat': None,
                'lng': None,
            }
            landmarks.append(target)
            by_name[key] = target
        else:
            target['name'] = name or target.get('name')
            if item.get('category') or item.get('type'):
                target['category'] = item.get('category') or item.get('type')
            for field in ('duration_minutes', 'duration_min', 'distance_km', 'distance', 'distance_text'):
                if target.get(field) in (None, '') and item.get(field) not in (None, ''):
                    target[field] = item[field]

        latitude = numeric(item.get('lat') or item.get('latitude'))
        longitude = numeric(item.get('lng') or item.get('longitude'))
        if latitude is not None and longitude is not None:
            target['lat'] = latitude
            target['lng'] = longitude
        distance_meters = numeric(item.get('distance_meters'))
        if distance_meters is not None:
            target['distance_meters'] = round(distance_meters)
    return landmarks


def _parse_catchment_zones(text):
    """Parse catchment zones text into zone objects.

    Supports both the legacy formats ("10 دقائق", "5 دقائق: مجمع الراشد") and the
    structured table format ("مجمع الراشد — 4.2 كم — 5 دقائق")."""
    default_zones = [{'minutes': 10, 'km': 8}, {'minutes': 20, 'km': 16}, {'minutes': 35, 'km': 28}]
    if not text:
        return default_zones
    if isinstance(text, list):
        zones = []
        for item in text:
            if not isinstance(item, dict):
                continue
            km = item.get('km') or item.get('distance_km') or item.get('distance')
            minutes = item.get('minutes') or item.get('duration_minutes') or item.get('duration_min')
            try:
                minutes = int(float(minutes)) if minutes not in (None, '') else None
            except (TypeError, ValueError):
                minutes = None
            try:
                km = float(km) if km not in (None, '') else None
            except (TypeError, ValueError):
                km = None
            if km is None and minutes:
                km = minutes * 0.8 / 1.60934
            if not km or km <= 0:
                continue
            zone = {'minutes': minutes, 'km': km}
            label = str(item.get('label') or item.get('name') or item.get('area') or '').strip()
            if label:
                zone['label'] = label
            zones.append(zone)
        return zones or default_zones
    if not isinstance(text, str):
        return default_zones
    zones = []
    for line in text.strip().split('\n'):
        line = line.strip().lstrip('-').lstrip('•').strip()
        if not line:
            continue
        dur_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:دقيقة|دقائق|min|mins|minutes)', line, re.IGNORECASE)
        dist_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:كم|كـم|km|kms|kilometer|kilometers)', line, re.IGNORECASE)
        if dur_match:
            minutes = int(float(dur_match.group(1)))
        else:
            digits = ''.join([c for c in line if c.isdigit()])
            if not digits:
                continue
            minutes = int(digits)
        zone = {'minutes': minutes, 'km': minutes * 0.8 / 1.60934}
        if dist_match:
            zone['km'] = float(dist_match.group(1))
        label = line
        if dur_match:
            label = label.replace(dur_match.group(0), '')
        if dist_match:
            label = label.replace(dist_match.group(0), '')
        label = re.sub(r'^[\s:：\-—–,،]+|[\s:：\-—–,،]+$', '', label).strip()
        if label:
            zone['label'] = label
        zones.append(zone)
    if not zones:
        return default_zones
    return zones
