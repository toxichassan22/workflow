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
                if marker.get('type') != 'site':
                    print(f"[MAP] landmark '{marker.get('name')}' has no coordinates — skipped")
                continue
            dx, dy = _latlng_to_pixel_offset(marker_lat, marker_lng, center_lat, center_lng, zoom, scale=scale)
            px = center_x + dx
            py = center_y + dy
            if not (0 <= px <= img_w and 0 <= py <= img_h):
                if marker.get('type') != 'site':
                    print(f"[MAP] landmark '{marker.get('name')}' falls outside the frame at zoom {zoom} — skipped")
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


def classify_landmark_category(types, language='ar'):
    types = set(types or [])
    english = _lang_norm(language) == 'en'
    categories = (
        ('Leisure' if english else 'ترفيهي', {'amusement_park', 'aquarium', 'zoo', 'park', 'garden', 'sports_complex', 'golf_course', 'swimming_pool', 'movie_theater', 'performing_arts_theater', 'concert_hall', 'event_venue'}),
        ('Education' if english else 'تعليمي', {'school', 'university', 'library', 'preschool', 'primary_school', 'secondary_school'}),
        ('Health' if english else 'صحي', {'hospital', 'doctor', 'dentist', 'pharmacy', 'veterinary_care'}),
        ('Retail' if english else 'تجاري', {'shopping_mall', 'department_store', 'supermarket', 'market', 'store'}),
        ('Religious' if english else 'ديني', {'mosque', 'church', 'hindu_temple', 'synagogue', 'place_of_worship'}),
        ('Culture/Tourism' if english else 'ثقافي/سياحي', {'tourist_attraction', 'landmark', 'historical_landmark', 'museum', 'art_gallery'}),
        ('Government/Services' if english else 'حكومي/خدمي', {'city_hall', 'government_office', 'embassy', 'police', 'fire_station'}),
    )
    for label, matched_types in categories:
        if types & matched_types:
            return label
    return 'Social/Services' if english else 'اجتماعي/خدمي'


def find_place_near(name, lat, lng, radius_m=20000, language='ar', usage_ctx=None):
    """Locate a named landmark around the site with Places text search.

    Geocoding a landmark name together with the project address returns the *address*,
    so every named landmark landed on the site itself and was then dropped as a duplicate.
    A text search with a location bias resolves the place instead. The top hit is
    not kept blindly either: a road or multi-branch name can resolve to a far
    endpoint, so the nearest candidate to the site wins.
    """
    query = str(name or '').strip()
    if not query or not _has_api_key():
        return None
    place_tenant = usage_ctx.get('tenant_id') if isinstance(usage_ctx, dict) else None
    cache_key = _discovery_cache_key(
        place_tenant, 'place', lat, lng,
        extra=f"{query.casefold()}:{radius_m}:{language}:v2")
    cached = _discovery_cache_get(place_tenant, cache_key)
    if isinstance(cached, dict) and cached.get('lat') is not None:
        return cached
    try:
        response = requests.post(
            'https://places.googleapis.com/v1/places:searchText',
            headers={
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': _get_api_key(),
                'X-Goog-FieldMask': 'places.displayName,places.location,places.formattedAddress,places.types',
            },
            json={
                'textQuery': query,
                'languageCode': language,
                'maxResultCount': 5,
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
        # The first hit can sit kilometres off — a long road's remote segment or
        # a far same-named branch — while a closer candidate is the landmark this
        # map means. Road-style names additionally prefer actual route entities
        # over businesses carrying the road's name.
        candidates = []
        for place in places:
            location = (place or {}).get('location') or {}
            latitude, longitude = location.get('latitude'), location.get('longitude')
            if latitude is None or longitude is None:
                continue
            candidates.append({
                'place': place,
                'lat': float(latitude),
                'lng': float(longitude),
                'distance': _distance_meters(lat, lng, latitude, longitude),
                'route': 'route' in set((place or {}).get('types') or []),
            })
        if not candidates:
            return None
        roadish = is_road_name(query)
        if roadish and any(candidate['route'] for candidate in candidates):
            candidates = [candidate for candidate in candidates if candidate['route']]
        best = min(candidates, key=lambda candidate: candidate['distance'])
        if places and best['place'] is not places[0]:
            print(f"[PLACES TEXT] {query}: picked a nearer candidate "
                  f"{best['distance'] / 1000.0:.1f} km out instead of the top hit")
        _record_maps_usage(usage_ctx, 'places_text', 1)
        resolved_place = {
            'lat': best['lat'],
            'lng': best['lng'],
            'name': ((best['place'].get('displayName') or {}).get('text') or query),
        }
        _discovery_cache_put(place_tenant, cache_key, resolved_place, ttl_days=30)
        return resolved_place
    except Exception as error:
        print(f'[PLACES TEXT ERROR] {query}: {error}')
        return None


def get_nearby_landmarks(lat, lng, radius=1500, keyword=None, max_results=8, include_all=False, included_types=None, usage_ctx=None, language='ar'):
    """Find nearby landmarks using Places API (New).
    Filters out irrelevant place types like gas stations, parking, ATMs, etc."""
    if not _has_api_key():
        return _api_key_error()
    language = _lang_norm(language)
    nearby_tenant = usage_ctx.get('tenant_id') if isinstance(usage_ctx, dict) else None
    nearby_key = _discovery_cache_key(
        nearby_tenant, 'nearby', lat, lng,
        extra=f"{radius}:{max_results}:{bool(include_all)}:{','.join(sorted(included_types or []))}:{language}")
    nearby_hit = _discovery_cache_get(nearby_tenant, nearby_key)
    if isinstance(nearby_hit, dict) and nearby_hit.get('success'):
        return nearby_hit
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
        'languageCode': language,
    }
    if included_types:
        body['includedTypes'] = list(included_types)

    try:
        response = requests.post(_assert_allowed_remote_url(url), headers=headers, json=body, timeout=15)
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

        _record_maps_usage(usage_ctx, 'places_nearby', 1)

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
            empty_result = {'success': True, 'landmarks': []}
            # Quiet areas are not cached: an empty answer must never mask a
            # later malformed provider body as a success.
            return empty_result

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
                'category': classify_landmark_category(p.get('types', []), language=language),
                'rating': p.get('rating', 0),
                'preferred': is_preferred,
                'distance_meters': round(distance_meters),
            })

        places.sort(key=lambda x: (not x.get('preferred', False), x.get('distance_meters', float('inf')), -(x.get('rating') or 0)))
        places = places[:max_results]

        nearby_result = {'success': True, 'landmarks': places}
        if places:
            _discovery_cache_put(nearby_tenant, nearby_key, nearby_result, ttl_days=7)
        return nearby_result
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


def get_driving_times(origin_lat, origin_lng, destinations, language='ar'):
    """Backwards-compatible wrapper around get_drive_matrix.

    Kept so older callers keep working, but the numbers come from a single
    source of truth (get_drive_matrix) to avoid divergent results.
    """
    if not _has_api_key():
        return _api_key_error()

    if not destinations:
        return {'success': True, 'times': []}

    matrix = get_drive_matrix({'lat': origin_lat, 'lng': origin_lng}, destinations, language=language)
    times = []
    for i, dest in enumerate(destinations):
        entry = matrix[i] if i < len(matrix) else None
        times.append({
            'landmark': dest,
            'duration_minutes': entry['duration_min'] if entry else None,
            'distance_text': f"{entry['distance_km']} {_distance_unit(language)}" if entry else None,
            'status': 'OK' if entry else 'NOT_FOUND',
        })
    return {'success': True, 'times': times}


def get_drive_matrix(origin, destinations, usage_ctx=None, language='ar'):
    """Return driving metrics in chunks so large curated landmark lists remain supported."""
    if not destinations:
        return []
    chunk_size = 25
    combined = []
    for start in range(0, len(destinations), chunk_size):
        combined.extend(_get_drive_matrix_chunk(origin, destinations[start:start + chunk_size], usage_ctx=usage_ctx, language=language))
    return combined
