def _draw_access_roads(image_path, center_lat, center_lng, zoom, scale=2, project_data=None, tenant_id=None,
                       origin_lat=None, origin_lng=None, allow_discovery=True):
    """Draw only approved main-road geometry and labels."""
    def _draw_road_label(image, px, py, text, label_scale=1.0, font=None, bg_color=(37, 75, 102, 255), border_color=(240, 230, 210, 255)):
        label_scale = max(0.6, min(1.8, float(label_scale or 1)))
        # Sizes mirror the DOM overlay: 13px font and 4px/8px padding per scale
        # unit on a 1000px-wide box, so the baked label matches the preview.
        layout = _map_label_layout(text, img_w, font_size=13, padding=(8, 4), label_scale=label_scale)
        rect = (px - layout['width'] / 2, py - layout['height'] / 2,
                px + layout['width'] / 2, py + layout['height'] / 2)
        _paint_map_label(image, rect, layout, bg_color=bg_color, border_color=border_color)

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
        distance *= img_w / 2560.0
        ox = -dy / length * distance
        oy = dx / length * distance
        candidates = [(px + ox, py + oy), (px - ox, py - oy)]
        for candidate_x, candidate_y in candidates:
            if 90 <= candidate_x <= img_w - 90 and 60 <= candidate_y <= img_h - 60:
                return candidate_x, candidate_y
        return px, py

    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        cx, cy = img_w / 2, img_h / 2
        unit = img_w / 1000.0
        overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        gold_color = (212, 163, 89, 255) # Premium gold/bronze color matching branding
        
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

        # A stored road name translated for an English deck never matches the
        # name Google returns, so matching runs on the original-script alias
        # (name_src, kept at collection time) while the drawn label stays the
        # approved display name.
        discoverable_aliases = []
        display_by_alias = {}
        for name in discoverable_road_names:
            alias = name
            for item in road_data if isinstance(road_data, list) else []:
                if not isinstance(item, dict):
                    continue
                display = str(item.get('name') or '').strip()
                if display and is_same_road_name(display, name):
                    alias = str(item.get('name_src') or '').strip() or display
                    break
            discoverable_aliases.append(alias)
            display_by_alias[alias] = name

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
        road_lang = map_language(project_data)
        ambient_ctx = _current_maps_ctx()
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
                expected_alias = str(item.get('name_src') or '').strip() or expected_name
                targeted_probes.append(((road_lat, road_lng), (expected_name, expected_alias)))
        probe_entries = targeted_probes + [(point, None) for point in probe_points]

        def _fetch_probe_route(entry):
            probe, expected_pair = entry
            if isinstance(expected_pair, tuple):
                expected_name, expected_alias = expected_pair
            else:
                expected_name, expected_alias = expected_pair, expected_pair
            p_lat, p_lng = probe
            snapped = _snap_to_roads(p_lat, p_lng, tenant_id=tenant_id)
            dest_lat = snapped['lat'] if snapped else p_lat
            dest_lng = snapped['lng'] if snapped else p_lng
            route = _google_directions_route(
                route_origin_lat, route_origin_lng, dest_lat, dest_lng, tenant_id=tenant_id,
                language=road_lang
            )
            if not route:
                return None

            discovered_name = (route.get('summary') or '').strip()
            wrong_script = bool(_ARABIC_CHAR_RE.search(discovered_name)) if road_lang == 'en' else bool(re.search(r'[A-Za-z]', discovered_name))
            if not discovered_name or wrong_script:
                localized_name = _google_reverse_geocode_road(
                    dest_lat, dest_lng, tenant_id=tenant_id, language=road_lang
                )
                if localized_name:
                    discovered_name = localized_name
            if expected_name:
                # A targeted probe sits on the stored road's own coordinates —
                # a cross-script Google name it cannot verify under an English
                # deck still draws under the approved label instead of dropping
                # the road. Arabic keeps the strict name check.
                matched = match_known_road_name(discovered_name, [expected_alias or expected_name])
                approved_name = expected_name if (matched or road_lang == 'en') else None
            else:
                matched_alias = match_known_road_name(discovered_name, discoverable_aliases)
                approved_name = display_by_alias.get(matched_alias) if matched_alias else None
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
            targeted_names = [pair[1][0] for pair in targeted_probes if isinstance(pair[1], tuple)]
            alias_by_name = dict(zip(discoverable_road_names, discoverable_aliases))
            for name in remaining_approved_names:
                if any(is_same_road_name(name, seen) for seen in targeted_names):
                    continue
                # Name-only approved rows carry no stored coordinates — under an
                # English deck the fixed probes' name check cannot match a road
                # Google only names in Arabic, so the row is located through
                # Places first and its probe then binds to real geometry.
                place = find_place_near(
                    name, route_origin_lat, route_origin_lng,
                    radius_m=30000, language=road_lang, usage_ctx=ambient_ctx)
                if place and place.get('lat') is not None and place.get('lng') is not None:
                    probe_entries.append(((place['lat'], place['lng']),
                                          (name, alias_by_name.get(name) or name)))
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
                    pixels.append((round(cx + dx), round(cy + dy)))

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
                    draw.line(segment, fill=(105, 73, 35, 140), width=max(1, round(18 * unit)), joint='curve')
                    draw.line(segment, fill=gold_color, width=max(1, round(9 * unit)), joint='curve')

                route_segment = max(segments, key=len)
                pending_labels.append((route_segment, label_text, coords))

            img = Image.alpha_composite(img, overlay)
            labels_overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
            for route_segment, label_text, route_coords in pending_labels:
                best_p = None
                label_key = _road_name_key(label_text)
                label_point = position_by_key.get(label_key)
                label_scale = size_by_key.get(label_key, 1.0)
                if label_point:
                    label_dx, label_dy = _latlng_to_pixel_offset(
                        label_point[0], label_point[1], center_lat, center_lng, zoom, scale=scale
                    )
                    candidate = (cx + label_dx, cy + label_dy)
                    if all(math.isfinite(value) for value in candidate):
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

                layout = _map_label_layout(label_text, img_w, font_size=13, padding=(8, 4), label_scale=label_scale)
                label_half_width = layout['width'] / 2
                label_half_height = layout['height'] / 2
                if best_p is None:
                    for _, point in candidates:
                        offset_point = _offset_label_point(point, route_segment, img_w, img_h)
                        lx1 = offset_point[0] - label_half_width
                        ly1 = offset_point[1] - label_half_height
                        lx2 = offset_point[0] + label_half_width
                        ly2 = offset_point[1] + label_half_height
                        collision = any(
                            not (lx2 < rx1 or lx1 > rx2 or ly2 < ry1 or ly1 > ry2)
                            for rx1, ry1, rx2, ry2 in placed_label_rects
                        )
                        if not collision:
                            best_p = offset_point
                            placed_label_rects.append((lx1, ly1, lx2, ly2))
                            break

                if best_p and label_text:
                    _draw_road_label(labels_overlay, best_p[0], best_p[1], label_text, label_scale=label_scale)
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
        return None
