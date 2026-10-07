def generate_all_map_images(project_data, tenant_id, presentation_id=None, force=False, branding=None, draft_id=None, highlight_site=True, usage_flow=None):
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None) or (project_data or {}).get('draft_id') or (project_data or {}).get('draftId') or 'unscoped'
    lock_key = (str(tenant_id), str(effective_id))
    with _MAP_GENERATION_LOCKS_GUARD:
        lock = _MAP_GENERATION_LOCKS.setdefault(lock_key, threading.Lock())
    with lock:
        flow = usage_flow if usage_flow in MAPS_USAGE_FLOWS else 'maps'
        scope_ctx = maps_usage_ctx(
            flow, tenant_id=tenant_id, presentation_id=presentation_id,
            draft_id=draft_id or (project_data or {}).get('draftId') or (project_data or {}).get('draft_id'))
        with maps_usage_scope(scope_ctx):
            return _generate_all_map_images(project_data, tenant_id, presentation_id, force, branding, draft_id, highlight_site)


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


def _parse_landmarks_text(text, language='ar'):
    """Parse landmark text into structured list with name, duration_minutes, and distance_km."""
    if not text:
        return []
    landmarks = []
    for line in text.strip().split('\n'):
        line = line.strip().lstrip('-').lstrip('\u2022').strip()
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
        category_match = re.search(r'(?:^|\s)[—\-]\s*(ترفيهي|تعليمي|صحي|تجاري|ديني(?: ومركزي)?|ثقافي/سياحي|حكومي/خدمي|اجتماعي/خدمي|Leisure|Education|Health|Retail|Religious|Culture/Tourism|Government/Services|Social/Services|Shopping|Transport|Public transit|Main corridor|Waterfront|Future development|Heritage & tourism|Business & logistics|Sports & events|Events|Coastal areas|Religious & central|Holy sites|Major projects|Religious tourism|Business & finance|Business & tech|Business & government|City center|Tourism & landmarks|Exhibitions & events|Nature & leisure|Logistics|Industry & logistics|Major landmark|Landmark)\s*(?:[—\-]|$)', clean_name, re.IGNORECASE)
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
            'distance_text': f"{distance} {_distance_unit(language)}" if distance is not None else None,
            'lat': None,
            'lng': None,
        })
    return landmarks


def _landmark_row_selected(item):
    """Twin of slide_engine._landmark_row_selected — keep both in sync.

    Tolerant of string flags from older drafts («true», «1», «yes»); a checked
    row must render however it was stored.
    """
    for key in ('show_on_map', 'selected'):
        value = (item or {}).get(key)
        if value is True or str(value or '').strip().lower() in {'true', '1', 'yes'}:
            return True
    return False


def select_map_landmark_rows(structured, limit=7):
    """Return the approved landmark rows for a map without changing their input order.

    Every checked row renders — the client picks the count; with no selection the
    first ``limit`` rows show like before.
    """
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except (TypeError, ValueError):
            return []
    if not isinstance(structured, list):
        return []

    rows = [dict(item) for item in structured if isinstance(item, dict)]
    selected = [item for item in rows if _landmark_row_selected(item)]
    try:
        row_limit = max(0, min(7, int(limit)))
    except (TypeError, ValueError):
        row_limit = 7
    if selected:
        return selected
    return rows[:row_limit]


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
        if item.get('manual_position'):
            target['manual_position'] = True
    return landmarks


def _snap_road_landmarks(items, project_data, site_lat, site_lng, language='ar', search_radius_m=50000):
    """Re-anchor road-named landmark rows near the site.

    A road name geocodes to a single point that can sit at the feature's remote
    end — the marker then lands kilometres out and the fitted frame zooms out to
    cover it. When the same road is drawn on the access map, its stored path is
    the truth: the marker belongs at the path's closest point to the site.
    Undrawn roads re-resolve through the Places candidate nearest the site.
    Markers the user placed by hand (``manual_position``) are never moved.
    """
    if not isinstance(items, list):
        return
    paths = []
    for key in ('manual_road_paths', 'access_roads_data'):
        raw = (project_data or {}).get(key)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = []
        for entry in raw or []:
            if not isinstance(entry, dict):
                continue
            road_name = str(entry.get('name') or '').strip()
            points = []
            for point in entry.get('points') or []:
                try:
                    points.append((float(point[0]), float(point[1])))
                except (TypeError, ValueError, IndexError):
                    continue
            if road_name and points:
                paths.append((road_name, points))
    for item in items:
        if not isinstance(item, dict) or item.get('manual_position'):
            continue
        names = [item.get('name'), item.get('name_src')]
        if not any(is_road_name(name) for name in names if name):
            continue
        old_lat, old_lng = item.get('lat'), item.get('lng')
        match = next((
            points for road_name, points in paths
            if any(is_same_road_name(name, road_name) for name in names if name)), None)
        if match:
            item['lat'], item['lng'] = min(
                match, key=lambda pt: _distance_meters(site_lat, site_lng, pt[0], pt[1]))
        else:
            place = find_place_near(item.get('name'), site_lat, site_lng,
                                    radius_m=search_radius_m, language=language)
            if not (place and place.get('lat') is not None and place.get('lng') is not None):
                continue
            item['lat'], item['lng'] = place['lat'], place['lng']
        item['distance_meters'] = round(_distance_meters(
            site_lat, site_lng, float(item['lat']), float(item['lng'])))
        moved_m = None
        try:
            moved_m = _distance_meters(float(old_lat), float(old_lng), float(item['lat']), float(item['lng']))
        except (TypeError, ValueError):
            moved_m = None
        if moved_m is None or moved_m > 250:
            # The stored label point was drawn beside the old marker — a moved
            # pin would leave it stranded off-frame, so the label re-seats.
            item.pop('label_point', None)
            for labels_key in ('catchment_label_positions', 'landmark_label_positions'):
                labels = (project_data or {}).get(labels_key)
                if isinstance(labels, dict):
                    labels.pop(item.get('name'), None)
            print(f"[LANDMARKS] road marker '{item.get('name')}' snapped near the site")


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
        line = line.strip().lstrip('-').lstrip('\u2022').strip()
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
