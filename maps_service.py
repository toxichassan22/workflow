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

# Professional satellite map style — sepia/greyscale tone matching reference examples
# Road labels kept visible in Arabic for context
SATELLITE_WITH_LABELS_STYLES = [
    'feature:all|saturation:-80|lightness:-10',
    'feature:poi|visibility:off',
    'feature:poi.business|visibility:off',
    'feature:transit|visibility:off',
    'feature:administrative|visibility:off',
    # Keep road labels visible in Arabic
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
SITE_FILL_COLOR = (160, 50, 50, 130)    # More visible semi-transparent red fill
SITE_BORDER_COLOR = (107, 28, 35, 230)  # Dark maroon border
COMPASS_COLOR = (107, 28, 35)       # Dark maroon for compass

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


def _has_api_key():
    return bool(GOOGLE_API_KEY and GOOGLE_API_KEY.startswith('AIza'))


def _api_key_error():
    return {'error': 'Google Maps API key not configured'}


def geocode_address(address, tenant_id=None):
    """Convert address string to lat/lng using Geocoding API."""
    if not _has_api_key():
        return _api_key_error()

    if tenant_id:
        limit_error = _check_maps_rate_limit(tenant_id)
        if limit_error:
            return limit_error

    url = 'https://maps.googleapis.com/maps/api/geocode/json'
    params = {'address': address, 'key': GOOGLE_API_KEY}
    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        if data.get('status') != 'OK':
            return {'error': f"Geocoding API error: {data.get('status')}", 'details': data}

        result = data['results'][0]
        loc = result['geometry']['location']
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
        }
    except Exception as e:
        return {'error': f"Geocoding request failed: {str(e)}"}


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


def get_static_map(lat, lng, zoom=14, markers=None, paths=None, size=(1280, 720), output_path=None,
                   maptype='satellite', styles=None, use_google_markers=False, language='ar'):
    """Generate a static map image with optional markers and paths."""
    if not _has_api_key():
        return _api_key_error()

    if output_path is None:
        filename = f"map_{uuid.uuid4().hex}.png"
        output_path = os.path.join(MAPS_DIR, filename)

    url = 'https://maps.googleapis.com/maps/api/staticmap'
    params = {
        'center': f"{lat},{lng}",
        'zoom': zoom,
        'size': f"{size[0]}x{size[1]}",
        'maptype': maptype,
        'key': GOOGLE_API_KEY,
        'scale': 2,
        'language': language,
    }

    chosen_styles = styles or SATELLITE_WITH_LABELS_STYLES
    params['style'] = chosen_styles

    if markers and use_google_markers:
        params['markers'] = markers
    if paths:
        params['path'] = paths

    return _download_image(url, params, output_path)


def _latlng_to_pixel_offset(lat, lng, center_lat, center_lng, zoom, scale=2):
    """Convert lat/lng to pixel offset from image center for a static map."""
    world_width = 256 * (2 ** zoom) * scale
    x_offset = (lng - center_lng) * world_width / 360
    lat_rad = math.radians(center_lat)
    y_world = world_width / (2 * math.pi)
    # Convert lat difference to radians for correct scaling in Mercator projection
    y_offset = math.radians(lat - center_lat) * y_world / math.cos(lat_rad)
    return x_offset, -y_offset


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
            try:
                font = ImageFont.truetype("arial.ttf", 60)
            except Exception:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), label_text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = ccx - tw // 2
            ty = ccy + pin_r + tri_h + 10
            pad = 20
            draw.rounded_rectangle([tx - pad, ty - 8, tx + tw + pad, ty + th + 12], radius=16, fill=color)
            draw.text((tx, ty), label_text, fill='#FFFFFF', font=font)
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
            try:
                font = ImageFont.truetype("arial.ttf", int(pin_r * 1.1))
            except Exception:
                font = ImageFont.load_default()
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


def _overlay_markers(image_path, center_lat, center_lng, zoom, markers_list, size=(1280, 720), scale=2):
    """
    Overlay custom markers on a map image.
    markers_list: list of dicts with keys: lat, lng, color, label, type ('site' or 'landmark')
    """
    try:
        img = Image.open(image_path).convert('RGBA')
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        img_w, img_h = img.size
        center_x, center_y = img_w // 2, img_h // 2
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
                is_site = m.get('type') == 'site'
                pin_size = 120 if is_site else 72
                pin_img = _draw_pin_marker(color=color, label=label, size=pin_size, is_site=is_site)
                
                px_paste = int(px - pin_size // 2)
                py_paste = int(py - pin_size)
                overlay.paste(pin_img, (px_paste, py_paste), pin_img)
        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[MAP MARKERS ERROR] {e}")
        return False


def get_nearby_landmarks(lat, lng, radius=1500, keyword=None, max_results=8):
    """Find nearby landmarks using Places API (New)."""
    if not _has_api_key():
        return _api_key_error()

    url = 'https://places.googleapis.com/v1/places:searchNearby'
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': GOOGLE_API_KEY,
        'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.id,places.types',
    }
    body = {
        'locationRestriction': {
            'circle': {
                'center': {'latitude': lat, 'longitude': lng},
                'radius': radius,
            }
        },
        'maxResultCount': max_results,
    }
    if keyword:
        body['keyword'] = keyword

    try:
        response = requests.post(url, headers=headers, json=body, timeout=15)
        data = response.json()
        if 'places' not in data:
            return {'error': f"Places API error: {data}", 'details': data}

        places = []
        for p in data.get('places', []):
            loc = p.get('location', {})
            places.append({
                'name': p.get('displayName', {}).get('text', 'Unknown'),
                'address': p.get('formattedAddress', ''),
                'lat': loc.get('latitude'),
                'lng': loc.get('longitude'),
                'place_id': p.get('id'),
                'types': p.get('types', []),
            })
        return {'success': True, 'landmarks': places}
    except Exception as e:
        return {'error': f"Places request failed: {str(e)}"}


def get_driving_times(origin_lat, origin_lng, destinations):
    """Get driving times from origin to multiple destinations using Distance Matrix API."""
    if not _has_api_key():
        return _api_key_error()

    if not destinations:
        return {'success': True, 'times': []}

    url = 'https://maps.googleapis.com/maps/api/distancematrix/json'
    dest_str = '|'.join([f"{d['lat']},{d['lng']}" for d in destinations])
    params = {
        'origins': f"{origin_lat},{origin_lng}",
        'destinations': dest_str,
        'mode': 'driving',
        'key': GOOGLE_API_KEY,
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        if data.get('status') != 'OK':
            return {'error': f"Distance Matrix API error: {data.get('status')}", 'details': data}

        rows = data.get('rows', [])
        if not rows:
            return {'success': True, 'times': []}

        elements = rows[0].get('elements', [])
        times = []
        for i, elem in enumerate(elements):
            duration_min = None
            if elem.get('status') == 'OK' and elem.get('duration'):
                duration_min = math.ceil(elem['duration']['value'] / 60)
            times.append({
                'landmark': destinations[i],
                'duration_minutes': duration_min,
                'distance_text': elem.get('distance', {}).get('text') if elem.get('status') == 'OK' else None,
                'status': elem.get('status'),
            })
        return {'success': True, 'times': times}
    except Exception as e:
        return {'error': f"Distance Matrix request failed: {str(e)}"}


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
        'key': GOOGLE_API_KEY,
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
            markers.append({'lat': lm['lat'], 'lng': lm['lng'], 'color': MARKER_COLOR_LANDMARK, 'type': 'landmark', 'label': label})
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


def _fetch_osm_polygon(lat, lng, radius_m=150):
    """Fetch the real building/compound polygon from OpenStreetMap via Overpass API in a single optimized query."""
    
    overpass_servers = [
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://z.overpass-api.de/api/interpreter",
        "https://overpass.osm.ch/api/interpreter",
    ]
    
    headers = {
        'User-Agent': 'RealEstateProposalGenerator/1.0'
    }
    
    # Combine all tags into a single Overpass query for maximum speed (1 request instead of 4)
    # We query around the coordinate for leisure, amenity, landuse, and buildings
    query = f"""[out:json][timeout:10];
    (
      way(around:{radius_m},{lat},{lng})["leisure"~"sports_centre|stadium|fitness_centre|golf_course|resort|park|playground|garden"];
      way(around:{radius_m},{lat},{lng})["amenity"~"school|university|hospital|college|club|clinic|place_of_worship|public_building"];
      way(around:{radius_m},{lat},{lng})["landuse"~"construction|commercial|retail|residential|industrial"];
      way(around:{radius_m},{lat},{lng})["building"];
    );
    out geom;"""
    
    data = None
    for server_url in overpass_servers:
        try:
            resp = requests.post(server_url, data={'data': query}, headers=headers, timeout=12)
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
        
    # Priority ranking and validation in Python
    # Class 1: Point is inside the polygon (preferred)
    # Class 2: Point is near the polygon (within 60 meters)
    best_el = None
    best_sort_key = (999, 999, float('inf'))
    
    for el in elements:
        geom = el.get('geometry', [])
        if len(geom) < 3:
            continue
            
        coords = [(p['lat'], p['lon']) for p in geom]
        area_sqm = _approx_polygon_area_sqm(coords)
        
        # Determine priority and limit based on tags
        tags = el.get('tags', {})
        
        priority = 999
        max_area = 0
        tag_type = "unknown"
        
        if 'leisure' in tags and any(x in tags['leisure'] for x in ("sports_centre", "stadium", "fitness_centre", "golf_course", "resort", "park", "playground", "garden")):
            priority = 1
            max_area = 600000
            tag_type = "leisure:" + tags['leisure']
        elif 'amenity' in tags and any(x in tags['amenity'] for x in ("school", "university", "hospital", "college", "club", "clinic", "place_of_worship", "public_building")):
            priority = 2
            max_area = 400000
            tag_type = "amenity:" + tags['amenity']
        elif 'landuse' in tags and any(x in tags['landuse'] for x in ("construction", "commercial", "retail", "residential", "industrial")):
            priority = 3
            max_area = 600000
            tag_type = "landuse:" + tags['landuse']
        elif 'building' in tags:
            priority = 4
            max_area = 150000
            tag_type = "building:" + tags['building']
            
        if priority == 999:
            continue # Tag does not match our target types
            
        # Validate area limits
        if area_sqm > max_area:
            print(f"[OSM POLYGON] Rejected too-large {tag_type}: {area_sqm:.0f} sqm > {max_area} limit")
            continue
        if area_sqm < 10:
            continue
            
        # Distance calculation
        def get_dist_m(pt_lat, pt_lng):
            dy = (pt_lat - lat) * 111000.0
            dx = (pt_lng - lng) * 111000.0 * math.cos(math.radians((pt_lat + lat) / 2.0))
            return math.sqrt(dx*dx + dy*dy)
            
        min_dist_to_vertex = min(get_dist_m(p_lat, p_lng) for p_lat, p_lng in coords)
        is_inside = _point_in_polygon(lat, lng, coords)
        
        # Check if it contains the point or is very close (within 60 meters)
        if not is_inside and min_dist_to_vertex > 60.0:
            continue
            
        # Sort key: (0 if inside else 1, priority, min_dist_to_vertex)
        sort_key = (0 if is_inside else 1, priority, min_dist_to_vertex)
        if sort_key < best_sort_key:
            best_sort_key = sort_key
            best_el = el
            
    if best_el and best_el.get('geometry'):
        coords = [(p['lat'], p['lon']) for p in best_el['geometry']]
        tags = best_el.get('tags', {})
        area_sqm = _approx_polygon_area_sqm(coords)
        tag_name = tags.get('name', '')
        tag_type = tags.get('leisure', tags.get('building', tags.get('amenity', tags.get('landuse', 'polygon'))))
        is_inside_str = "containing" if best_sort_key[0] == 0 else f"nearby ({best_sort_key[2]:.1f}m away)"
        try:
            print(f"[OSM POLYGON] Found {is_inside_str} {tag_type} '{tag_name}' (Priority {best_sort_key[1]}), ~{area_sqm:.0f} sqm")
        except Exception:
            safe_name = tag_name.encode('ascii', errors='ignore').decode('ascii')
            print(f"[OSM POLYGON] Found {is_inside_str} {tag_type} '{safe_name}' (Priority {best_sort_key[1]}), ~{area_sqm:.0f} sqm")
        return coords
        
    print(f"[OSM POLYGON] No suitable polygon found near ({lat}, {lng})")
    return None


# Cache for OSM polygons to avoid re-querying for the same location across map types
_osm_polygon_cache = {}


def _draw_site_highlight(image_path, center_lat, center_lng, zoom, area_radius_m=300, size=(1280, 720), scale=2,
                         polygon_coords=None, auto_detect_polygon=True, rotation_deg=18.0):
    """Draw the site highlight using the real building shape.
    Priority: 1) User-supplied polygon, 2) Auto-detected building polygon from OSM (area-validated), 3) Small circle fallback."""
    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        cx, cy = img_w // 2, img_h // 2

        overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        fill_color = SITE_FILL_COLOR
        border_color = SITE_BORDER_COLOR

        # Priority 1: User-supplied polygon coordinates
        if auto_detect_polygon and (not polygon_coords or len(polygon_coords) < 3):
            # Priority 2: Auto-detect building polygon from OpenStreetMap
            # _fetch_osm_polygon now validates area to prevent huge neighborhood polygons
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
            # Draw real polygon (user-supplied or auto-detected building shape)
            pixel_points = []
            for p_lat, p_lng in polygon_coords:
                dx, dy = _latlng_to_pixel_offset(p_lat, p_lng, center_lat, center_lng, zoom, scale=scale)
                px = int(cx + dx)
                py = int(cy + dy)
                pixel_points.append((px, py))
            
            overlay_draw.polygon(pixel_points, fill=fill_color, outline=border_color, width=5)
            
            # White outer border for premium look
            overlay_draw.polygon(pixel_points, fill=None, outline=(255, 255, 255, 160), width=3)
        else:
            # Priority 3: Small circle fallback when no building polygon found.
            circle_radius_m = 120
            edge_lat = center_lat + (circle_radius_m / 111320.0)
            dx, _ = _latlng_to_pixel_offset(edge_lat, center_lng, center_lat, center_lng, zoom, scale=scale)
            # Make fallback circle size elegant and proportional to zoom level
            min_r = 16 if zoom <= 13 else (24 if zoom == 14 else 40)
            r = max(abs(dx), min_r)
            overlay_draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill_color, outline=border_color, width=5)
            overlay_draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=None, outline=(255, 255, 255, 160), width=3)

        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[SITE HIGHLIGHT ERROR] {e}")
        return False


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
            label = zone.get('label', f"{zone.get('minutes', 5)} دقائق")
            try:
                font = ImageFont.truetype("fonts/BahijTheSansArabic-Bold.ttf", 10 * canvas_scale)
            except Exception:
                try:
                    font = ImageFont.truetype("arial.ttf", 10 * canvas_scale)
                except Exception:
                    font = ImageFont.load_default()
            
            # Format text using arabic_reshaper if needed
            try:
                import arabic_reshaper
                from bidi.algorithm import get_display
                reshaped = get_display(arabic_reshaper.reshape(label))
            except Exception:
                reshaped = label
                
            bbox = draw.textbbox((0, 0), reshaped, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            
            # Position the label pill on the top edge of the circle (offset upwards)
            pad_x = 10 * canvas_scale
            pad_y = 5 * canvas_scale
            ly = ccy - r
            lx = ccx
            
            rect = [lx - tw // 2 - pad_x, ly - th // 2 - pad_y, lx + tw // 2 + pad_x, ly + th // 2 + pad_y]
            
            # Draw pill background and border
            draw.rounded_rectangle(rect, radius=4 * canvas_scale, fill=border_c, outline=(255, 255, 255, 200), width=1 * canvas_scale)
            draw.text((lx - tw // 2, ly - th // 2 - 2 * canvas_scale), reshaped, fill='#FFFFFF', font=font)

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
        dir_text = directions.get(heading, f"إطلالة {heading}°")
        
        try:
            font = ImageFont.truetype("fonts/BahijTheSansArabic-Bold.ttf", 14)
        except Exception:
            try:
                font = ImageFont.truetype("arial.ttf", 14)
            except Exception:
                font = ImageFont.load_default()
                
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            reshaped = get_display(arabic_reshaper.reshape(dir_text))
        except Exception:
            reshaped = dir_text
            
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

        # Draw "ش" (شمال = North) in center
        try:
            font = ImageFont.truetype("arial.ttf", compass_size // 2)
        except Exception:
            font = ImageFont.load_default()
        text = "ش"
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


def _draw_access_roads(image_path, center_lat, center_lng, zoom, scale=2, project_data=None, tenant_id=None):
    """Fetch nearby main roads via OSRM & Geocoding APIs and draw them highlighted in gold with white arrows and plaques."""
    def _reshape_arabic_text(text):
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            reshaped = arabic_reshaper.reshape(text)
            return get_display(reshaped)
        except Exception:
            return text

    def _draw_outlined_arrow(draw, p1, p2, fill_color=(255, 255, 255, 240), outline_color=(0, 0, 0, 200), arrow_len=14, arrow_w=8):
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.sqrt(dx*dx + dy*dy)
        if length == 0:
            return
        ux = dx / length
        uy = dy / length

        ap1 = (int(p2[0]), int(p2[1]))
        ap2 = (int(p2[0] - ux * arrow_len + uy * arrow_w), int(p2[1] - uy * arrow_len - ux * arrow_w))
        ap3 = (int(p2[0] - ux * arrow_len - uy * arrow_w), int(p2[1] - uy * arrow_len + ux * arrow_w))

        o_len = arrow_len + 2
        o_w = arrow_w + 1.5
        op1 = (int(p2[0] + ux * 1.5), int(p2[1] + uy * 1.5))
        op2 = (int(p2[0] - ux * o_len + uy * o_w), int(p2[1] - uy * o_len - ux * o_w))
        op3 = (int(p2[0] - ux * o_len - o_w), int(p2[1] - uy * o_len + ux * o_w))

        draw.polygon([op1, op2, op3], fill=outline_color)
        draw.polygon([ap1, ap2, ap3], fill=fill_color)

    def _draw_road_label(draw, px, py, text, font=None, bg_color=(37, 75, 102, 230), border_color=(240, 230, 210, 200)):
        if not font:
            font_paths = [
                "fonts/BahijTheSansArabic-Bold.ttf",
                "d:/workflow/fonts/BahijTheSansArabic-Bold.ttf",
                "arial.ttf"
            ]
            for fp in font_paths:
                try:
                    font = ImageFont.truetype(fp, 13)
                    break
                except Exception:
                    continue
            if not font:
                font = ImageFont.load_default()
                
        reshaped_text = _reshape_arabic_text(text)
        bbox = draw.textbbox((0, 0), reshaped_text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        
        pad_x = 10
        pad_y = 5
        rect = [int(px - tw // 2 - pad_x), int(py - th // 2 - pad_y), int(px + tw // 2 + pad_x), int(py + th // 2 + pad_y)]
        
        draw.rounded_rectangle(rect, radius=5, fill=bg_color, outline=border_color, width=1)
        draw.text((int(px - tw // 2), int(py - th // 2 - 2)), reshaped_text, fill='#FFFFFF', font=font)

    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        cx, cy = img_w // 2, img_h // 2
        overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        gold_color = (212, 163, 89, 180) # Premium gold/bronze color matching branding
        
        # Parse road names from project_data
        roads = []
        if project_data:
            main_roads_text = project_data.get('main_roads', '')
            sec_roads_text = project_data.get('secondary_roads', '')
            
            # Combine and parse road lists
            raw_roads = []
            if main_roads_text:
                raw_roads.extend(re.split(r'[\n,;]', main_roads_text))
            if sec_roads_text:
                raw_roads.extend(re.split(r'[\n,;]', sec_roads_text))
                
            for r in raw_roads:
                r_clean = r.strip().lstrip('-').lstrip('•').strip()
                if r_clean and r_clean not in roads:
                    roads.append(r_clean)

        city = "Riyadh"
        if project_data and project_data.get('location_address'):
            addr = project_data.get('location_address', '')
            parts = [p.strip() for p in addr.split(',')]
            if len(parts) > 1:
                city = parts[-1]
            elif parts:
                city = parts[0]

        routes_coords = []
        road_route_mapping = [] # stores (coords, road_name)
        
        # 1. Try to query routes based on geocoded road names
        for road in roads:
            geo = geocode_address(f"{road}, {city}", tenant_id=tenant_id)
            if not geo.get('success'):
                # Try geocoding without city
                geo = geocode_address(road, tenant_id=tenant_id)
                
            if geo.get('success'):
                origin = f"{geo['lng']},{geo['lat']}"
                dest = f"{center_lng},{center_lat}"
                url = f"http://router.project-osrm.org/route/v1/driving/{origin};{dest}?overview=full"
                try:
                    res = requests.get(url, timeout=8).json()
                    if 'routes' in res and res['routes']:
                        poly = res['routes'][0]['geometry']
                        coords = _decode_polyline(poly)
                        if coords:
                            road_route_mapping.append((coords, road))
                            routes_coords.append(coords)
                except Exception as e:
                    print(f"[OSRM ROAD ERROR] {road}: {e}")

        # 2. If no road-specific routes found, fallback to general snap routes around center
        if not routes_coords:
            print("[ACCESS ROADS DEBUG] No geocoded road routes found, querying snap routes...")
            # Query 4 directional routes snapping to nearest roads
            general_queries = [
                ((center_lat - 0.008, center_lng), (center_lat + 0.008, center_lng)), # N-S
                ((center_lat, center_lng - 0.008), (center_lat, center_lng + 0.008)), # E-W
                ((center_lat - 0.006, center_lng - 0.006), (center_lat + 0.006, center_lng + 0.006)), # NW-SE
            ]
            for idx, (orig, dst) in enumerate(general_queries):
                origin = f"{orig[1]},{orig[0]}"
                dest = f"{dst[1]},{dst[0]}"
                url = f"http://router.project-osrm.org/route/v1/driving/{origin};{dest}?overview=full"
                try:
                    res = requests.get(url, timeout=8).json()
                    if 'routes' in res and res['routes']:
                        poly = res['routes'][0]['geometry']
                        coords = _decode_polyline(poly)
                        if coords:
                            # Map to generic label if roads are list-based
                            label = roads[idx] if idx < len(roads) else f"Route {idx+1}"
                            road_route_mapping.append((coords, label))
                            routes_coords.append(coords)
                except Exception as e:
                    print(f"[OSRM GENERAL ERROR] {idx}: {e}")

        # 3. Draw routes and labels
        if routes_coords:
            for coords, label_text in road_route_mapping:
                pixels = []
                for lat, lng in coords:
                    dx, dy = _latlng_to_pixel_offset(lat, lng, center_lat, center_lng, zoom, scale=scale)
                    pixels.append((cx + dx, cy + dy))
                
                valid_pixels = [(int(p[0]), int(p[1])) for p in pixels if -150 <= p[0] <= img_w + 150 and -150 <= p[1] <= img_h + 150]
                if len(valid_pixels) < 2:
                    continue
                
                # Draw thick gold road line
                draw.line(valid_pixels, fill=gold_color, width=12)
                
                # Draw white arrows along the road
                interval = max(len(valid_pixels) // 3, 4)
                for idx in range(interval, len(valid_pixels) - 2, interval):
                    p1 = valid_pixels[idx - 1]
                    p2 = valid_pixels[idx]
                    _draw_outlined_arrow(draw, p1, p2)
                
                # Find best place to draw road label (away from center)
                best_p = None
                for p in valid_pixels:
                    px, py = p
                    if 100 <= px <= img_w - 100 and 80 <= py <= img_h - 80:
                        dist = math.sqrt((px - cx)**2 + (py - cy)**2)
                        if 180 <= dist <= 400:
                            best_p = p
                            break
                if not best_p and valid_pixels:
                    best_p = valid_pixels[len(valid_pixels) // 3]
                
                if best_p and label_text:
                    _draw_road_label(draw, best_p[0], best_p[1], label_text)
                    
            img = Image.alpha_composite(img, overlay)
            img.save(image_path, 'PNG')
            print("[ACCESS ROADS DEBUG] Successfully drew roads using OSRM")
            return True

        # 4. Pure PIL local fallback if OSRM fails completely
        print("[ACCESS ROADS DEBUG] OSRM failed completely, drawing schematic grid fallback...")
        # Draw slightly offset roads representing grid structure
        # North-South road on East side (e.g. Olaya Street)
        draw.line([(cx + 120, -50), (cx + 180, img_h + 50)], fill=gold_color, width=14)
        # East-West road on South side (e.g. Al Urubah Road)
        draw.line([(-50, cy + 150), (img_w + 50, cy + 120)], fill=gold_color, width=14)
        
        # Arrow on N-S road
        _draw_outlined_arrow(draw, (cx + 130, cy + 100), (cx + 140, cy - 100))
        # Arrow on E-W road
        _draw_outlined_arrow(draw, (cx - 150, cy + 140), (cx + 150, cy + 130))
        
        # Labels
        ns_label = roads[0] if len(roads) > 0 else "Olaya Street"
        ew_label = roads[1] if len(roads) > 1 else "Al Urubah Road"
        _draw_road_label(draw, cx + 150, cy - 150, ns_label)
        _draw_road_label(draw, cx - 180, cy + 135, ew_label)
        
        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        print("[ACCESS ROADS DEBUG] Local grid fallback drawn successfully")
        return True
    except Exception as e:
        print(f"[DRAW ACCESS ROADS ERROR] {e}")
        return False


def _get_cached_map_images(tenant_id, presentation_id):
    """Return existing map images for a tenant/presentation if all required ones exist."""
    from db import get_map_images
    existing = get_map_images(tenant_id, presentation_id=presentation_id)
    if not existing:
        return None
    placeholders = {}
    required_types = {'overview', 'access', 'catchment', 'landmarks', 'streetview_1', 'streetview_2', 'streetview_3', 'streetview_4'}
    found_types = set()
    for img in existing:
        if not os.path.exists(img['file_path']):
            continue
        found_types.add(img['image_type'])
        placeholders[img['placeholder']] = img['file_path']
    if required_types - found_types:
        return None
    metadata = {}
    if existing:
        try:
            metadata = json.loads(existing[0].get('metadata_json') or '{}')
        except Exception:
            metadata = {}
    return {
        'lat': metadata.get('lat'),
        'lng': metadata.get('lng'),
        'placeholders': placeholders,
        'landmarks': metadata.get('landmarks', []),
        'cached': True,
    }


def generate_all_map_images(project_data, tenant_id, presentation_id=None, force=False):
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

    lat = _extract_coordinate(project_data.get('location_lat'))
    lng = _extract_coordinate(project_data.get('location_lng'))

    if lat is None or lng is None:
        address = project_data.get('location_address') or project_data.get('location', '')
        if address:
            geo = geocode_address(address, tenant_id=tenant_id)
            if geo.get('success'):
                lat = geo['lat']
                lng = geo['lng']

    if lat is None or lng is None:
        return {'error': 'No valid location coordinates found'}

    if not force and presentation_id:
        cached = _get_cached_map_images(tenant_id, presentation_id)
        if cached and cached.get('lat') == lat and cached.get('lng') == lng:
            return cached

    if force and presentation_id:
        from db import delete_map_images
        delete_map_images(tenant_id, presentation_id=presentation_id)

    result = {
        'lat': lat,
        'lng': lng,
        'placeholders': {},
        'landmarks': [],
    }

    polygon_coords = None
    poly_data = project_data.get('location_polygon')
    if poly_data:
        try:
            if isinstance(poly_data, str):
                polygon_coords = []
                for pt in poly_data.split(';'):
                    if ',' in pt:
                        plat, plng = pt.split(',')
                        polygon_coords.append((float(plat.strip()), float(plng.strip())))
            elif isinstance(poly_data, list):
                polygon_coords = [(float(pt[0]), float(pt[1])) for pt in poly_data if len(pt) >= 2]
        except Exception as e:
            print(f"[POLYGON PARSE ERROR] {e}")

    # Force auto-detection of polygon to True to ensure OSM boundary retrieval
    auto_detect_polygon = True

    # Fetch/Detect OSM polygon early to compute dynamic zoom
    if auto_detect_polygon and (not polygon_coords or len(polygon_coords) < 3):
        cache_key = f"{lat:.6f},{lng:.6f}"
        if cache_key in _osm_polygon_cache:
            osm_poly = _osm_polygon_cache[cache_key]
        else:
            osm_poly = _fetch_osm_polygon(lat, lng, radius_m=400)
            if osm_poly:
                _osm_polygon_cache[cache_key] = osm_poly
        if osm_poly and len(osm_poly) >= 3:
            polygon_coords = osm_poly

    # Compute dynamic zoom levels based on polygon size (if present)
    overview_zoom = 13
    landmarks_zoom = 14
    access_zoom = 15
    catchment_zoom = 12

    if polygon_coords and len(polygon_coords) >= 3:
        try:
            lats = [pt[0] for pt in polygon_coords]
            lngs = [pt[1] for pt in polygon_coords]
            min_lat, max_lat = min(lats), max(lats)
            min_lng, max_lng = min(lngs), max(lngs)
            d_lat = max_lat - min_lat
            d_lng = max_lng - min_lng
            max_dim = max(d_lat, d_lng)
            if max_dim > 0:
                # Target: polygon max dimension occupies 20% to 35% of the screen
                suggested_zoom = int(math.log2(540.0 / max_dim))
                overview_zoom = max(13, min(19, suggested_zoom))
                
                # Make other zoom levels relative to overview_zoom
                landmarks_zoom = max(14, overview_zoom - 1)
                access_zoom = max(15, overview_zoom + 1)
                catchment_zoom = max(12, overview_zoom - 2)
                print(f"[DYNAMIC ZOOM] Adjusted zoom levels based on polygon: overview={overview_zoom}, landmarks={landmarks_zoom}, access={access_zoom}, catchment={catchment_zoom}")
        except Exception as ez:
            print(f"[DYNAMIC ZOOM ERROR] {ez}")

    # Compute polygon centroid for site marker placement
    # When a polygon exists, place the pin at its centroid so it sits ON the highlight
    marker_lat, marker_lng = lat, lng
    if polygon_coords and len(polygon_coords) >= 3:
        try:
            marker_lat = sum(pt[0] for pt in polygon_coords) / len(polygon_coords)
            marker_lng = sum(pt[1] for pt in polygon_coords) / len(polygon_coords)
        except Exception:
            marker_lat, marker_lng = lat, lng

    # Parse enabled maps (default to all if not specified)
    enabled_maps = project_data.get('enabled_maps')
    if isinstance(enabled_maps, str):
        try:
            enabled_maps = json.loads(enabled_maps)
        except Exception:
            enabled_maps = None
    if not isinstance(enabled_maps, list):
        enabled_maps = ['overview', 'landmarks', 'access', 'catchment', 'streetview']

    # Parse UI element flags (compass, inset map)
    draw_compass = project_data.get('draw_compass', True)
    if isinstance(draw_compass, str):
        draw_compass = draw_compass.lower() in ('true', '1', 'yes')
    elif not isinstance(draw_compass, bool):
        draw_compass = True

    draw_inset = project_data.get('draw_inset', True)
    if isinstance(draw_inset, str):
        draw_inset = draw_inset.lower() in ('true', '1', 'yes')
    elif not isinstance(draw_inset, bool):
        draw_inset = True

    # Parse per-map style preferences (satellite/roadmap/terrain/hybrid/both)
    # Default: all satellite. Employee can override per-map via map_styles dict.
    map_styles_raw = project_data.get('map_styles', {})
    if isinstance(map_styles_raw, str):
        try:
            map_styles_raw = json.loads(map_styles_raw)
        except Exception:
            map_styles_raw = {}
    VALID_MAPTYPES = {'satellite', 'roadmap', 'terrain', 'hybrid', 'both'}
    map_styles = {}
    for key in ('overview', 'landmarks', 'access', 'catchment'):
        val = map_styles_raw.get(key, 'satellite')
        map_styles[key] = val if val in VALID_MAPTYPES else 'satellite'

    # Parse nearby landmarks from text
    landmarks_text = project_data.get('nearby_landmarks', '')
    landmarks = _parse_landmarks_text(landmarks_text)

    # If no structured landmarks, fetch from Places API
    if not landmarks:
        places = get_nearby_landmarks(lat, lng, radius=2000, max_results=6)
        if places.get('success'):
            landmarks = places['landmarks']
            _record_maps_call(tenant_id)

    # Geocode text-parsed landmarks that lack coordinates
    for lm in landmarks:
        if lm.get('lat') is None or lm.get('lng') is None:
            geo = geo = geocode_address(lm['name'], tenant_id=tenant_id)
            if geo.get('success'):
                lm['lat'] = geo['lat']
                lm['lng'] = geo['lng']

    # Filter out landmarks that are extremely close to the site (within ~50 meters)
    filtered_landmarks = []
    for lm in landmarks:
        if lm.get('lat') is not None and lm.get('lng') is not None:
            dx = lm['lat'] - lat
            dy = lm['lng'] - lng
            if math.sqrt(dx*dx + dy*dy) < 0.0005:
                continue
        filtered_landmarks.append(lm)
    landmarks = filtered_landmarks

    # Get driving times for landmarks with coordinates
    geocoded_landmarks = [lm for lm in landmarks if lm.get('lat') is not None and lm.get('lng') is not None]
    if geocoded_landmarks:
        times = get_driving_times(lat, lng, geocoded_landmarks)
        if times.get('success'):
            for i, t in enumerate(times['times']):
                geocoded_landmarks[i]['duration_minutes'] = t['duration_minutes']
            _record_maps_call(tenant_id)
        result['landmarks'] = landmarks

    # Helper: pick styles based on maptype
    def _styles_for(maptype, default_styles):
        """For satellite, use our custom styles. For roadmap/terrain/hybrid, no custom styles needed."""
        if maptype == 'satellite':
            return default_styles
        return []  # roadmap/terrain/hybrid look best with default Google styling

    # Generate map_overview
    if 'overview' in enabled_maps:
        overview_markers = _build_markers(marker_lat, marker_lng, landmarks)
        overview_mt = map_styles['overview']
        if overview_mt == 'both':
            styles_to_gen = [('satellite', '##MAP_OVERVIEW_SATELLITE##', 'overview_satellite'),
                             ('roadmap', '##MAP_OVERVIEW_ROADMAP##', 'overview_roadmap')]
        else:
            styles_to_gen = [(overview_mt, '##MAP_OVERVIEW##', 'overview')]

        for active_mt, placeholder, img_suffix in styles_to_gen:
            overview_path = _unique_map_path(tenant_id, presentation_id, img_suffix)
            overview_res = get_static_map(lat, lng, zoom=overview_zoom, size=(1280, 720), output_path=overview_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_WITH_LABELS_STYLES))
            if overview_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(overview_path, intensity=0.35)
                    _apply_map_overlay(overview_path, dark_factor=0.12)
                _draw_site_highlight(overview_path, lat, lng, overview_zoom, size=(1280, 720), polygon_coords=polygon_coords, auto_detect_polygon=auto_detect_polygon)
                _overlay_markers(overview_path, lat, lng, overview_zoom, overview_markers, size=(1280, 720))
                if draw_compass:
                    _draw_compass(overview_path, position='top-right')
                if draw_inset:
                    _draw_inset_map(overview_path, lat, lng, inset_size=180)
                result['placeholders'][placeholder] = overview_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, img_suffix, overview_path, placeholder, presentation_id, {'lat': lat, 'lng': lng})

    # Generate map_landmarks (closer zoom)
    if 'landmarks' in enabled_maps and landmarks:
        landmarks_markers = _build_markers(marker_lat, marker_lng, landmarks)
        landmarks_mt = map_styles['landmarks']
        if landmarks_mt == 'both':
            styles_to_gen = [('satellite', '##MAP_LANDMARKS_SATELLITE##', 'landmarks_satellite'),
                             ('roadmap', '##MAP_LANDMARKS_ROADMAP##', 'landmarks_roadmap')]
        else:
            styles_to_gen = [(landmarks_mt, '##MAP_LANDMARKS##', 'landmarks')]

        for active_mt, placeholder, img_suffix in styles_to_gen:
            landmarks_path = _unique_map_path(tenant_id, presentation_id, img_suffix)
            lm_res = get_static_map(lat, lng, zoom=landmarks_zoom, size=(1280, 720), output_path=landmarks_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_WIDE_STYLES))
            if lm_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(landmarks_path, intensity=0.35)
                    _apply_map_overlay(landmarks_path, dark_factor=0.20)
                _draw_site_highlight(landmarks_path, lat, lng, landmarks_zoom, size=(1280, 720), polygon_coords=polygon_coords, auto_detect_polygon=auto_detect_polygon)
                _overlay_markers(landmarks_path, lat, lng, landmarks_zoom, landmarks_markers, size=(1280, 720))
                if draw_compass:
                    _draw_compass(landmarks_path, position='top-right')
                if draw_inset:
                    _draw_inset_map(landmarks_path, lat, lng, inset_size=180)
                result['placeholders'][placeholder] = landmarks_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, img_suffix, landmarks_path, placeholder, presentation_id, {'lat': lat, 'lng': lng, 'landmarks': landmarks})

    # Generate map_access
    if 'access' in enabled_maps:
        access_markers = [{'lat': marker_lat, 'lng': marker_lng, 'color': MARKER_COLOR_SITE, 'type': 'site', 'label': None}]
        access_mt = map_styles['access']
        if access_mt == 'both':
            styles_to_gen = [('satellite', '##MAP_ACCESS_SATELLITE##', 'access_satellite'),
                             ('roadmap', '##MAP_ACCESS_ROADMAP##', 'access_roadmap')]
        else:
            styles_to_gen = [(access_mt, '##MAP_ACCESS##', 'access')]

        for active_mt, placeholder, img_suffix in styles_to_gen:
            access_path = _unique_map_path(tenant_id, presentation_id, img_suffix)
            access_res = get_static_map(lat, lng, zoom=access_zoom, size=(1280, 720), output_path=access_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_CLEAN_STYLES))
            if access_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(access_path, intensity=0.35)
                    _apply_map_overlay(access_path, dark_factor=0.10)
                _draw_site_highlight(access_path, lat, lng, access_zoom, size=(1280, 720), polygon_coords=polygon_coords, auto_detect_polygon=auto_detect_polygon)
                _draw_access_roads(access_path, lat, lng, access_zoom, scale=2, project_data=project_data, tenant_id=tenant_id)
                _overlay_markers(access_path, lat, lng, access_zoom, access_markers, size=(1280, 720))
                if draw_compass:
                    _draw_compass(access_path, position='top-right')
                result['placeholders'][placeholder] = access_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, img_suffix, access_path, placeholder, presentation_id, {'lat': lat, 'lng': lng})

    # Generate map_catchment
    if 'catchment' in enabled_maps:
        zones = _parse_catchment_zones(project_data.get('catchment_areas', ''))
        catchment_markers = [{'lat': marker_lat, 'lng': marker_lng, 'color': MARKER_COLOR_SITE, 'type': 'site', 'label': None}]
        catchment_mt = map_styles['catchment']
        if catchment_mt == 'both':
            styles_to_gen = [('satellite', '##MAP_CATCHMENT_SATELLITE##', 'catchment_satellite'),
                             ('roadmap', '##MAP_CATCHMENT_ROADMAP##', 'catchment_roadmap')]
        else:
            styles_to_gen = [(catchment_mt, '##MAP_CATCHMENT##', 'catchment')]

        for active_mt, placeholder, img_suffix in styles_to_gen:
            catchment_path = _unique_map_path(tenant_id, presentation_id, img_suffix)
            # Fetch clean map without the API-drawn paths, as we will draw them with PIL for premium styling.
            catchment_res = get_static_map(lat, lng, zoom=catchment_zoom, paths=None, size=(1280, 720), output_path=catchment_path, maptype=active_mt, styles=_styles_for(active_mt, SATELLITE_WIDE_STYLES))
            if catchment_res.get('success'):
                if active_mt == 'satellite':
                    _apply_sepia_tone(catchment_path, intensity=0.35)
                    _apply_map_overlay(catchment_path, dark_factor=0.15)
                # Draw the anti-aliased concentric rings with time label pills
                if zones:
                    _draw_catchment_zones(catchment_path, lat, lng, catchment_zoom, zones, scale=2)
                _overlay_markers(catchment_path, lat, lng, catchment_zoom, catchment_markers, size=(1280, 720))
                if draw_compass:
                    _draw_compass(catchment_path, position='top-right')
                if draw_inset:
                    _draw_inset_map(catchment_path, lat, lng, inset_size=180)
                result['placeholders'][placeholder] = catchment_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, img_suffix, catchment_path, placeholder, presentation_id, {'lat': lat, 'lng': lng, 'zones': zones})

    # Generate street view images
    if 'streetview' in enabled_maps:
        for i, heading in enumerate([0, 90, 180, 270], 1):
            sv_path = _unique_map_path(tenant_id, presentation_id, f'streetview_{i}')
            sv_res = get_street_view(lat, lng, heading=heading, output_path=sv_path)
            if sv_res.get('success'):
                # Post-process Street View with contrast, vignette, borders, and direction label
                _post_process_streetview(sv_path, heading, i)
                placeholder = f"##STREET_VIEW_{i}##"
                result['placeholders'][placeholder] = sv_path
                _record_maps_call(tenant_id)
                from db import add_map_image
                add_map_image(tenant_id, f'streetview_{i}', sv_path, placeholder, presentation_id, {'lat': lat, 'lng': lng, 'heading': heading})

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
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_landmarks_text(text):
    """Parse landmark text like 'ميدان السارية - 1 دقيقة' into structured list."""
    if not text:
        return []
    # This is a simple text-only parser; driving times and coordinates will be
    # enriched later by Places API + Distance Matrix.
    landmarks = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        # Remove bullet markers and common separators
        line = line.lstrip('-').lstrip('•').strip()
        name = line
        duration = None
        if ' - ' in line:
            parts = line.rsplit(' - ', 1)
            name = parts[0].strip()
            duration_text = parts[1].strip()
            # Try to extract a number
            digits = ''.join([c for c in duration_text if c.isdigit()])
            if digits:
                duration = int(digits)
        landmarks.append({
            'name': name,
            'duration_minutes': duration,
            'lat': None,
            'lng': None,
        })
    return landmarks


def _parse_catchment_zones(text):
    """Parse catchment zones text into zone objects."""
    if not text:
        return [{'minutes': 10, 'km': 8}, {'minutes': 20, 'km': 16}, {'minutes': 35, 'km': 28}]
    zones = []
    for line in text.strip().split('\n'):
        line = line.strip().lstrip('-').lstrip('•').strip()
        if not line:
            continue
        digits = ''.join([c for c in line if c.isdigit()])
        if digits:
            minutes = int(digits)
            zones.append({'minutes': minutes, 'km': minutes * 0.8 / 1.60934})
    if not zones:
        return [{'minutes': 10, 'km': 8}, {'minutes': 20, 'km': 16}, {'minutes': 35, 'km': 28}]
    return zones
