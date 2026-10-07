# Map marker and place-label drawing. The browser preview renders pins and
# labels as a DOM overlay sized in container-width units (cqw), so every size
# here is derived from the image width the same way (unit = img_w/1000) — the
# approved raster keeps the design the client saw instead of a fixed-pixel
# variant that shrinks when the 2560px image is displayed small.
def _draw_marker_shape(draw, px, py, unit, img_h, is_site, label=None, occupied=None):
    """Draw the marker the DOM overlay shows, with its bottom edge at (px, py).

    Site: the same flat oval the preview SVG draws (non-uniform viewBox, so the
    radius fractions track width and height separately).
    Landmarks: the 22px numbered circle with a white ring — no teardrop tail.
    """
    if is_site:
        # CSS: circle r=2.2/1.25 on a 100x100 viewBox with preserveAspectRatio=none.
        outer_rx, outer_ry = 22 * unit, 22 * img_h / 1000.0
        inner_rx, inner_ry = 12.5 * unit, 12.5 * img_h / 1000.0
        draw.ellipse(
            [px - outer_rx, py - outer_ry, px + outer_rx, py + outer_ry],
            fill=(107, 28, 35, 61),
            outline=(255, 255, 255, 235),
            width=max(1, round(0.7 * unit)),
        )
        draw.ellipse(
            [px - inner_rx, py - inner_ry, px + inner_rx, py + inner_ry],
            fill=(107, 28, 35, 255),
        )
        if occupied is not None:
            occupied.append((px - outer_rx, py - outer_ry, px + outer_rx, py + outer_ry))
        return

    # .map-place-marker: 22px circle, 2px white border, bottom edge on the point.
    outer_r = 11 * unit
    border = max(2, round(2 * unit))
    cy = py - outer_r
    # DOM box-shadow 0 2px 5px rgba(0,0,0,.35)
    shadow_r = outer_r + 1.2 * unit
    draw.ellipse(
        [px - shadow_r, cy - shadow_r + 0.8 * unit, px + shadow_r, cy + shadow_r + 0.8 * unit],
        fill=(0, 0, 0, 90),
    )
    draw.ellipse(
        [px - outer_r, cy - outer_r, px + outer_r, cy + outer_r],
        fill=(255, 255, 255, 255),
    )
    inner_r = outer_r - border
    draw.ellipse(
        [px - inner_r, cy - inner_r, px + inner_r, cy + inner_r],
        fill=(139, 32, 32, 255),
    )
    if label:
        number_font = _get_arabic_font(max(9, round(10 * unit)))
        bbox = draw.textbbox((0, 0), str(label), font=number_font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            (int(px - tw / 2 - bbox[0]), int(cy - th / 2 - bbox[1])),
            str(label),
            fill='#FFFFFF',
            font=number_font,
        )
    if occupied is not None:
        occupied.append((px - outer_r, cy - outer_r, px + outer_r, cy + outer_r))


def _draw_marker_name_label(draw, px, anchor_y, text, img_w, img_h, occupied, preferred_point=None):
    """Draw the navy name pill the DOM overlay shows (.map-place-label).

    Font, padding, radius and offsets scale with the image width like the
    overlay's cqw units, so a name keeps the same size on the approved raster
    that it had in the preview — no shrink-to-fit for longer names.
    """
    clean_text = _strip_arabic_diacritics(str(text or '').strip())
    if not clean_text:
        return None

    unit = img_w / 1000.0
    font = _get_arabic_font(max(10, round(12 * unit)))
    shaped_text = _reshape_arabic_text(clean_text)
    text_bbox = draw.textbbox((0, 0), shaped_text, font=font)

    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    pad_x = 7 * unit
    pad_y = 3 * unit
    label_width = text_width + pad_x * 2
    label_height = text_height + pad_y * 2

    gap = 4 * unit
    side = 20 * unit
    candidates = [
        (px - label_width / 2, anchor_y + gap),
        (px - label_width / 2, anchor_y - label_height - side),
        (px + side, anchor_y - label_height / 2),
        (px - label_width - side, anchor_y - label_height / 2),
        (px + side, anchor_y + gap + 11 * unit),
        (px - label_width - side, anchor_y + gap + 11 * unit),
        (px + side, anchor_y - label_height - side - gap),
        (px - label_width - side, anchor_y - label_height - side - gap),
    ]

    margin = 3 * unit
    rect = None
    if preferred_point:
        left = max(margin, min(img_w - label_width - margin, preferred_point[0] - label_width / 2))
        top = max(margin, min(img_h - label_height - margin, preferred_point[1] - label_height / 2))
        rect = (left, top, left + label_width, top + label_height)
    else:
        for left, top in candidates:
            left = max(margin, min(img_w - label_width - margin, left))
            top = max(margin, min(img_h - label_height - margin, top))
            candidate = (left, top, left + label_width, top + label_height)
            if not any(_rects_overlap(candidate, box) for box in occupied):
                rect = candidate
                break
    if rect is None:
        for distance in (35, 55, 78, 105):
            dy = distance * unit
            for left, top in (
                (px - label_width / 2, anchor_y + gap + dy),
                (px - label_width / 2, anchor_y - label_height - gap - dy),
            ):
                left = max(margin, min(img_w - label_width - margin, left))
                top = max(margin, min(img_h - label_height - margin, top))
                candidate = (left, top, left + label_width, top + label_height)
                if not any(_rects_overlap(candidate, box) for box in occupied):
                    rect = candidate
                    break
            if rect is not None:
                break
    if rect is None:
        left = max(margin, min(img_w - label_width - margin, px - label_width / 2))
        top = max(margin, min(img_h - label_height - margin, anchor_y + gap))
        rect = (left, top, left + label_width, top + label_height)

    left, top, right, bottom = [int(round(v)) for v in rect]
    radius = 6 * unit
    # DOM box-shadow 0 1px 3px rgba(0,0,0,.18)
    draw.rounded_rectangle(
        [left, top + int(round(0.4 * unit)), right, bottom + int(round(0.4 * unit))],
        radius=radius,
        fill=(0, 0, 0, 46),
    )
    draw.rounded_rectangle(
        [left, top, right, bottom],
        radius=radius,
        fill=(37, 75, 102, 255),
        outline=(240, 230, 210, 255),
        width=max(1, round(1 * unit)),
    )
    draw.text(
        (int(left + pad_x - text_bbox[0]), int(top + pad_y - text_bbox[1])),
        shaped_text,
        fill='#FFFFFF',
        font=font,
    )
    occupied.append(rect)
    return (left + (right - left) / 2, top + (bottom - top) / 2)


def _overlay_markers(image_path, center_lat, center_lng, zoom, markers_list, size=(1280, 720), scale=2):
    """
    Overlay the preview's flat site/landmark markers on a map image.
    markers_list: list of dicts with keys: lat, lng, color, label, name, type ('site' or 'landmark')
    """
    try:
        img = Image.open(image_path).convert('RGBA')
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        img_w, img_h = img.size
        unit = img_w / 1000.0
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
                name = m.get('name') or m.get('label_text')
                is_site = m.get('type') == 'site'
                _draw_marker_shape(
                    draw, px, py, unit, img_h, is_site,
                    label=m.get('label'), occupied=occupied_labels,
                )
                rendered_markers.append((px, py, name, is_site))

        for px, py, name, is_site in rendered_markers:
            if name and not is_site:
                _draw_marker_name_label(draw, px, py, name, img_w, img_h, occupied_labels)
        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[MAP MARKERS ERROR] {e}")
        return False


def _draw_catchment_markers(image_path, center_lat, center_lng, zoom, landmarks, label_positions=None, scale=2,
                            site_lat=None, site_lng=None):
    """Draw the catchment/landmarks markers the DOM preview shows.

    Rows without coordinates are filtered before numbering so the baked
    numbers match the preview indices exactly.
    """
    try:
        img = Image.open(image_path).convert('RGBA')
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        img_w, img_h = img.size
        unit = img_w / 1000.0
        center_x, center_y = img_w // 2, img_h // 2
        positions = label_positions or {}
        if isinstance(positions, str):
            try:
                positions = json.loads(positions)
            except (TypeError, ValueError):
                positions = {}
        drawable = []
        for item in landmarks:
            if item.get('lat') is None or item.get('lng') is None:
                if item.get('name'):
                    print(f"[MAP] landmark '{item.get('name')}' has no coordinates — skipped")
                continue
            drawable.append(item)
        marker_items = _build_markers(
            site_lat if site_lat is not None else center_lat,
            site_lng if site_lng is not None else center_lng,
            drawable,
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
                if marker.get('type') != 'site':
                    print(f"[MAP] landmark '{marker.get('name')}' falls outside the frame at zoom {zoom} — skipped")
                continue
            is_site = marker.get('type') == 'site'
            _draw_marker_shape(draw, px, py, unit, img_h, is_site, label=marker.get('label'), occupied=occupied)
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


def _rects_overlap(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


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
