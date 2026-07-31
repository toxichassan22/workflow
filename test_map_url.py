#!/usr/bin/env python3
"""Quick map+landmarks test for a Google Maps short URL."""
import os
import sys
import json


def _load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(env_path):
        return
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            value = value.strip().strip('"').strip("'")
            if value:
                os.environ.setdefault(key, value)


_load_dotenv()

import maps_service

URL = 'https://maps.app.goo.gl/fLy4tL1PQ4NzeJWk9'
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outputs')
MAP_FILE = os.path.join(OUT_DIR, 'test_map.png')
REPORT_FILE = os.path.join(OUT_DIR, 'test_map_report.txt')


def main():
    if not maps_service._has_api_key():
        print('ERROR: GOOGLE_MAPS_API_KEY not set')
        sys.exit(1)

    print(f'[TEST] Resolving {URL} ...')
    coords = maps_service.extract_coords_from_maps_link(URL)
    if not coords or 'lat' not in coords:
        print('ERROR: Could not extract coordinates from link')
        sys.exit(1)

    lat, lng = coords['lat'], coords['lng']
    print(f'[TEST] Coordinates: {lat:.6f}, {lng:.6f}')

    # Static map (satellite with roads labels + site marker)
    print('[TEST] Generating static map ...')
    map_res = maps_service.get_static_map(
        lat, lng,
        zoom=15,
        size=(1280, 720),
        output_path=MAP_FILE,
        maptype='satellite',
        styles=maps_service.SATELLITE_WITH_LABELS_STYLES,
        language='ar',
        markers=f'color:red|{lat},{lng}',
        use_google_markers=True,
    )
    if not map_res.get('success'):
        print('ERROR:', map_res)
        sys.exit(1)
    # Highlight the actual site area/building on the map
    print('[TEST] Highlighting site area on the map ...')
    maps_service._draw_site_highlight(
        MAP_FILE, lat, lng, zoom=15, size=(1280, 720), scale=2,
        polygon_coords=None, auto_detect_polygon=True, auto_detected=True
    )
    print(f'[TEST] Map saved: {MAP_FILE}')

    # Landmarks
    print('[TEST] Fetching nearby landmarks ...')
    lm_res = maps_service.get_nearby_landmarks(lat, lng, radius=2000, max_results=8)
    if not lm_res.get('success'):
        print('WARN landmarks:', lm_res.get('error'))
        landmarks = []
    else:
        landmarks = lm_res.get('landmarks', [])
        print(f'[TEST] Found {len(landmarks)} landmarks')

    # Driving times/distances to landmarks
    if landmarks:
        print('[TEST] Computing drive matrix to landmarks ...')
        matrix = maps_service.get_drive_matrix((lat, lng), landmarks)
        if matrix:
            for i, lm in enumerate(landmarks):
                if i < len(matrix) and matrix[i].get('duration_min') is not None:
                    lm['duration_minutes'] = matrix[i]['duration_min']
                    lm['distance_text'] = matrix[i].get('distance_text') or f"{matrix[i].get('distance_km', '?')} كم"
                else:
                    lm['duration_minutes'] = None
                    lm['distance_text'] = None

    # Main roads around the site: probe in very small steps (50 m) and keep
    # the ones that are actually reachable within a short drive.
    print('[TEST] Discovering nearby main roads ...')
    step_lat = 0.00045  # ~50 m
    step_lng = 0.00055
    road_probes = [
        (lat + step_lat, lng),
        (lat - step_lat, lng),
        (lat, lng + step_lng),
        (lat, lng - step_lng),
        (lat + step_lat * 0.7, lng + step_lng * 0.7),
        (lat + step_lat * 0.7, lng - step_lng * 0.7),
        (lat - step_lat * 0.7, lng + step_lng * 0.7),
        (lat - step_lat * 0.7, lng - step_lng * 0.7),
    ]
    probe_destinations = [{'name': f'road_probe_{i}', 'lat': p[0], 'lng': p[1]}
                          for i, p in enumerate(road_probes, 1)]
    road_matrix = maps_service.get_drive_matrix((lat, lng), probe_destinations)
    reachable = []
    if road_matrix:
        for i, rd in enumerate(road_matrix):
            if rd.get('duration_min') is None:
                continue
            # Only keep probes that are actually reachable within ~200 m by car
            if rd.get('distance_km') is not None and rd['distance_km'] <= 0.2:
                reachable.append({
                    'lat': probe_destinations[i]['lat'],
                    'lng': probe_destinations[i]['lng'],
                    'distance_km': rd.get('distance_km'),
                    'duration_minutes': rd.get('duration_min'),
                    'distance_text': rd.get('distance_text'),
                })

    # Sort by actual driving distance and get unique road names
    reachable.sort(key=lambda x: x.get('distance_km') or 999)
    roads = []
    seen = set()
    for r in reachable:
        name = maps_service._google_reverse_geocode_road(r['lat'], r['lng'], tenant_id=None)
        if not name or name in seen:
            continue
        seen.add(name)
        r['name'] = name
        # Show straight-line distance if the API snaps both points to the same road
        straight_m = maps_service._distance_meters(lat, lng, r['lat'], r['lng'])
        r['straight_m'] = round(straight_m)
        roads.append(r)
        if len(roads) >= 4:
            break
    print(f'[TEST] Found {len(roads)} main roads')

    # Build report
    lines = []
    lines.append('تقرير اختبار الموقع')
    lines.append('=' * 40)
    lines.append(f'الرابط: {URL}')
    lines.append(f'الإحداثيات: {lat:.6f}, {lng:.6f}')
    lines.append('')

    lines.append('الطرق الرئيسية القريبة:')
    if roads:
        for r in roads:
            duration = r.get('duration_minutes')
            dist = r.get('distance_text')
            if duration is not None and dist:
                lines.append(f'- {r["name"]}: {duration} دقيقة، {dist}')
            else:
                dist_m = maps_service._distance_meters(lat, lng, r['lat'], r['lng'])
                lines.append(f'- {r["name"]}: {round(dist_m)} م (خط مستقيم)')
    else:
        lines.append('- لم يتم العثور على طرق رئيسية')
    lines.append('')

    lines.append('المعالم القريبة وأوقات/مسافات الوصول:')
    if landmarks:
        for lm in landmarks:
            duration = lm.get('duration_minutes')
            dist = lm.get('distance_text')
            if duration is not None and dist:
                lines.append(f'- {lm["name"]}: {duration} دقيقة، {dist}')
            else:
                lines.append(f'- {lm["name"]}: {lm.get("distance_meters")} م (خط مستقيم)')
    else:
        lines.append('- لم يتم العثور على معالم قريبة')
    lines.append('')

    lines.append(f'صورة الخريطة: {MAP_FILE}')
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'[TEST] Report saved: {REPORT_FILE}')
    print('\n--- Report ---')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
