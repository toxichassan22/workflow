# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# The two location pages the map redesign left behind.
#
# The access, catchment and landmarks pages already share one designed frame:
# a page title, a table card, a 16:9 map card with a caption slot, and a facts
# strip. The site-data page and the site-analysis summary are the same kind of
# page — reference data the client signed off, plus one approved reading — but
# they were still drawn by the old template: a heading with a paragraph, or a
# key/value grid, thrown on a white slide. They now use that frame, so the
# location section reads as one designed sequence instead of three designed
# pages followed by two raw ones.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _location_names(value):
    """Names from a row list, a JSON-encoded row list, or a free-text field."""
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith('['):
            try:
                value = json.loads(raw)
            except (TypeError, ValueError):
                value = raw
    names = []
    if isinstance(value, (list, tuple)):
        for row in value:
            name = ''
            if isinstance(row, dict):
                for key in ('name', 'title', 'landmark', 'displayName'):
                    name = str(row.get(key) or '').strip()
                    if name:
                        break
            else:
                name = str(row or '').strip()
            if name:
                names.append(name)
        return names
    if isinstance(value, str):
        for line in re.split(r'[\r\n]+', value):
            for part in re.split(r'\s*[،,]\s*', line):
                part = part.strip(' -–—•*')
                if part:
                    names.append(part)
    return names


def _location_inline_names(names, en=False, limit=3):
    """«أ، ب، ج +2» — the first names plus a count of what follows."""
    names = [str(name).strip() for name in (names or []) if str(name or '').strip()]
    if not names:
        return ''
    shown = names[:limit]
    rest = len(names) - len(shown)
    joined = ', '.join(shown) if en else '، '.join(shown)
    return f'{joined} (+{rest})' if rest > 0 else joined


def _location_area_text(source, en=False):
    """The site area as the client entered it, with its unit but no conversion."""
    for key in ('approved_financial_area', 'croquis_land_area', 'land_area'):
        raw = str((source or {}).get(key) or '').strip()
        if not raw:
            continue
        if re.search(r'(?:م²|م2|m²|sqm)', raw, flags=re.IGNORECASE):
            return raw
        shown = format_financial_number(raw, grouped=True) or raw
        return shown + (' sqm' if en else ' م²')
    return ''


def _location_coordinates_text(source):
    lat = str((source or {}).get('location_lat') or '').strip()
    lng = str((source or {}).get('location_lng') or '').strip()
    coordinates = ' , '.join(part for part in (lat, lng) if part)
    return coordinates


def _location_road_names(source):
    source = source or {}
    for key in ('access_roads_data', 'main_roads_data', 'main_roads'):
        names = _location_names(source.get(key))
        if names:
            return names
    return []


def _location_landmark_names(source, structured_key, legacy_key):
    source = source or {}
    structured = source.get(structured_key)
    if isinstance(structured, (list, str)):
        names = _location_names(_approved_landmark_rows(structured))
        if names:
            return names
    return _location_names(source.get(legacy_key))


def _location_landmark_row_metrics(source, structured_key, legacy_key):
    """(nearest label, count) for the facts strip, from the approved rows."""
    source = source or {}
    structured = source.get(structured_key)
    rows = _approved_landmark_rows(structured) if isinstance(structured, (list, str)) else []
    if not rows:
        return '', len(_location_names(source.get(legacy_key)))
    nearest, nearest_distance = None, None
    for row in rows:
        try:
            distance = float(str(row.get('distance_km') or row.get('distance') or '').replace(',', ''))
        except (AttributeError, TypeError, ValueError):
            continue
        if nearest_distance is None or distance < nearest_distance:
            nearest, nearest_distance = row, distance
    if nearest is None:
        nearest = rows[0]
    name = str(nearest.get('name') or nearest.get('title') or '').strip()
    distance = str(nearest.get('distance_km') or nearest.get('distance') or '').strip()
    if distance and not re.search(r'[^\d.,\s-]', distance):
        distance += ' km' if resolve_offer_lang(source) == OFFER_LANG_ENGLISH else ' كم'
    return (f'{name} · {distance}' if distance else name), len(rows)


def _location_bidi(text):
    """Digits stay in reading order without re-aligning the whole cell.

    `unicode-bidi:plaintext` fixes «24.71 , 46.67» but also flips a number-only
    value to the left edge of an RTL cell; an isolate keeps the digits LTR
    while the cell keeps the paragraph's own direction.
    """
    return f'<span style="unicode-bidi:isolate;">{html_lib.escape(str(text))}</span>'


def _location_clip(text, limit=160):
    cleaned = re.sub(r'\s+', ' ', str(text or '')).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip(' ،,.-') + '…'


def _location_metric_strip(metrics, primary):
    """The facts strip under both pages, in the map pages' own card style."""
    cards = [
        (label, value, sub) for label, value, sub in (metrics or [])
        if str(value or '').strip()
    ][:3]
    if not cards:
        return ''
    html = ''.join(
        '<div data-location-metric="1" style="display:flex;flex-direction:column;'
        'justify-content:center;gap:5px;min-width:0;'
        'padding:14px 16px;border:1px solid #e2e8f0;border-radius:12px;background:#fff;">'
        f'<div style="font-size:10.5px;font-weight:700;color:#64748b;">{html_lib.escape(label)}</div>'
        f'<div style="font-size:14px;font-weight:800;color:{primary};line-height:1.4;white-space:nowrap;'
        'overflow:hidden;text-overflow:ellipsis;">'
        + _location_bidi(value) + '</div>'
        + (f'<div style="font-size:10.5px;color:#64748b;">{html_lib.escape(sub)}</div>' if sub else '')
        + '</div>'
        for label, value, sub in cards
    )
    return f'<div style="display:grid;grid-template-columns:repeat({len(cards)},1fr);gap:16px;">{html}</div>'


def _location_title_block(title, eyebrow, subtitle, primary, accent):
    return (
        '<div style="display:flex;align-items:flex-start;justify-content:flex-start;min-width:0;">'
        '<div style="min-width:0;">'
        f'<div style="font-size:10.5px;font-weight:800;letter-spacing:1.2px;color:{accent};">'
        f'{html_lib.escape(eyebrow)}</div>'
        f'<div style="font-size:27px;line-height:1.3;font-weight:800;color:{primary};margin-top:4px;">'
        f'{html_lib.escape(title)}</div>'
        f'<div style="font-size:12.5px;color:#64748b;margin-top:4px;line-height:1.6;">'
        f'{html_lib.escape(subtitle)}</div>'
        '</div></div>'
    )


def _location_page(body_html, strip_html, title, eyebrow, subtitle, primary, accent,
                   en=False, kind=''):
    """One frame for every location page: title above, content, facts strip below."""
    slide_dir = 'ltr' if en else 'rtl'
    return (
        f'<div class="slide" data-location-page="{html_lib.escape(kind)}" dir="{slide_dir}" '
        'style="width:1280px;height:720px;position:relative;'
        'overflow:hidden;background:#ffffff;color:#172033;box-sizing:border-box;'
        'padding:68px 40px 52px;display:flex;flex-direction:column;justify-content:space-between;">'
        + _location_title_block(title, eyebrow, subtitle, primary, accent)
        + body_html
        + strip_html
        + '</div>'
    )


def _location_card_header(title, badge, primary):
    return (
        f'<div style="height:42px;flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;'
        f'gap:12px;padding:0 16px;background:#f8fafc;border-bottom:1px solid #e2e8f0;">'
        f'<div style="font-size:12px;font-weight:800;color:{primary};">{html_lib.escape(title)}</div>'
        f'<div style="font-size:10.5px;font-weight:700;color:#64748b;">{html_lib.escape(str(badge))}</div>'
        '</div>'
    )


def _build_site_specs_slide(slide, project_data, branding=None):
    """The site-data page: the approved location fields, aligned — not a text dump."""
    source = project_data if isinstance(project_data, dict) else {}
    en = resolve_offer_lang(source) == OFFER_LANG_ENGLISH
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = str((slide or {}).get('title') or (
        'Location Data & Coordinates' if en else 'بيانات الموقع والإحداثيات'))

    city = str(source.get('city') or '').strip()
    district = str(source.get('district') or '').strip()
    plot = str(source.get('plot_number') or '').strip()
    area = _location_area_text(source, en)
    coordinates = _location_coordinates_text(source)
    fetched_at = str(source.get('location_data_fetched_at') or '').strip()

    rows = []
    for label, value in (
        ('City' if en else 'المدينة', city),
        ('District' if en else 'الحي', district),
        ('Plot / Plan number' if en else 'المخطط / القطعة', plot),
        ('Area' if en else 'المساحة', area),
        ('Coordinates' if en else 'الإحداثيات', coordinates),
    ):
        if value:
            rows.append((label, value))

    if rows:
        table_body = ''.join(
            f'<tr style="background:{"#ffffff" if index % 2 == 0 else "#f8fafc"};">'
            '<td style="padding:11px 14px;border-bottom:1px solid #e2e8f0;font-size:11.5px;'
            f'font-weight:700;color:#64748b;width:40%;">{html_lib.escape(label)}</td>'
            '<td style="padding:11px 14px;border-bottom:1px solid #e2e8f0;font-size:12px;'
            f'font-weight:700;color:{primary};">{_location_bidi(value)}</td>'
            '</tr>'
            for index, (label, value) in enumerate(rows)
        )
        table_html = (
            '<table data-preserve-density="1" dir="' + ('ltr' if en else 'rtl') + '" '
            'style="width:100%;height:100%;border-collapse:collapse;table-layout:fixed;">'
            f'<tbody>{table_body}</tbody></table>')
        table_badge = str(len(rows))
    else:
        table_html = (
            '<div style="padding:28px 18px;text-align:center;font-size:12.5px;color:#94a3b8;">'
            + ('No approved site data yet' if en else 'لم تُعتمد بيانات موقع بعد') + '</div>')
        table_badge = '0'

    table_card = (
        '<div data-location-card="1" style="display:flex;flex-direction:column;min-width:0;'
        'min-height:0;flex:1;'
        'border:1px solid #d9e2ec;border-radius:14px;overflow:hidden;background:#fff;">'
        + _location_card_header(
            'Site specification' if en else 'بيانات الموقع', table_badge, primary)
        # `flex:1` on a div that wraps a table is stripped by the table
        # readability pass, so the rows are given the height directly and the
        # gap under the last row never ships.
        + f'<div style="flex-grow:1;min-height:0;overflow:hidden;display:flex;'
        f'flex-direction:column;">{table_html}</div></div>')

    roads = _location_road_names(source)
    nearby = _location_landmark_names(source, 'nearby_landmarks_data', 'nearby_landmarks')
    city_landmarks = _location_landmark_names(
        source, 'city_landmarks_data', 'city_landmarks')
    catchment = _location_names(source.get('catchment_areas'))

    contexts = [
        ('Main roads & corridors' if en else 'الطرق الرئيسية المحيطة',
         _location_inline_names(roads, en)),
        ('Nearby landmarks' if en else 'أهم المعالم القريبة',
         _location_inline_names(nearby, en)),
        ('City landmarks' if en else 'المعالم الرئيسية في المدينة',
         _location_inline_names(city_landmarks, en)),
        ('Catchment areas' if en else 'مناطق نطاق التأثير',
         _location_inline_names(catchment, en) or _location_clip(source.get('catchment_areas'))),
    ]
    context_html = ''.join(
        '<div style="display:flex;flex-direction:column;gap:4px;min-width:0;">'
        f'<div style="font-size:10.5px;font-weight:700;color:#64748b;">{html_lib.escape(label)}</div>'
        f'<div style="font-size:12px;font-weight:700;color:{primary};line-height:1.65;'
        f'">{_location_bidi(text)}</div>'
        '</div>'
        for label, text in contexts if str(text or '').strip()
    ) or (
        '<div style="font-size:12.5px;color:#94a3b8;">'
        + ('No approved surrounding data yet' if en else 'لم تُعتمد بيانات محيط بعد')
        + '</div>')

    context_card = (
        '<div data-location-card="1" style="display:flex;flex-direction:column;gap:12px;'
        'min-width:0;min-height:0;flex:1;'
        'border:1px solid #d9e2ec;border-radius:14px;overflow:hidden;background:#fff;">'
        + _location_card_header(
            'Surroundings & access' if en else 'المحيط والوصول', '', primary)
        + '<div style="flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column;'
        f'gap:12px;padding:16px 18px;">{context_html}'
        '<div data-map-caption="1" style="margin-top:auto;font-size:10.5px;color:#64748b;'
        'line-height:1.5;"></div></div>'
        f'<div style="height:34px;flex:0 0 auto;display:flex;align-items:center;justify-content:flex-end;'
        f'padding:0 14px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:10px;'
        f'font-weight:700;color:#94a3b8;">{html_lib.escape("Google Maps" if en else "خرائط Google")}</div>'
        '</div>')

    metrics = [
        ('Corridors' if en else 'عدد المحاور', str(len(roads)) if roads else '', ''),
        ('Nearby landmarks' if en else 'المعالم القريبة',
         str(len(nearby)) if nearby else '', ''),
        ('City landmarks' if en else 'المعالم في المدينة',
         str(len(city_landmarks)) if city_landmarks else '', ''),
    ]
    if not any(str(value or '').strip() for _, value, _ in metrics):
        metrics = [
            ('Area' if en else 'المساحة', area, ''),
            ('City & district' if en else 'المدينة والحي',
             ' — '.join(part for part in (city, district) if part), ''),
            ('Coordinates' if en else 'الإحداثيات', coordinates, ''),
        ]

    body = (
        '<div style="display:grid;grid-template-columns:1.08fr 1fr;gap:24px;align-items:stretch;'
        'min-height:0;">'
        + table_card + context_card + '</div>')

    return _location_page(
        body, _location_metric_strip(metrics, primary), title,
        'SITE ANALYSIS' if en else 'تحليل الموقع',
        ('The approved location data and what surrounds the site' if en
         else 'بيانات الموقع المعتمدة وما يحيط به من محاور ومعالم'),
        primary, accent, en, kind='site-specs')


def _site_analysis_paragraphs(slide, source):
    """The approved site analysis, sliced to this page's paragraph range."""
    raw = str((source or {}).get('site_analysis') or '').strip()
    if not raw:
        return []
    paragraphs = [part.strip() for part in re.split(r'\r?\n\s*\r?\n', raw) if part.strip()]
    if not paragraphs:
        paragraphs = [part.strip() for part in raw.splitlines() if part.strip()] or [raw]
    match = re.fullmatch(
        r'site_analysis:(\d*):(\d*)',
        str((slide or {}).get('content_source') or '').strip())
    if match:
        start = int(match.group(1)) if match.group(1) else 0
        end = int(match.group(2)) if match.group(2) else len(paragraphs)
        paragraphs = paragraphs[start:end]
    return paragraphs


def _site_analysis_text_style(paragraphs, has_map):
    """Text size for the space the card actually has, so nothing is clipped."""
    length = len(' '.join(paragraphs))
    if length <= 520:
        font, line_height = 14.5, 1.9
    elif length <= 820:
        font, line_height = 13.2, 1.85
    elif length <= 1180:
        font, line_height = 12.2, 1.8
    else:
        font, line_height = 11.4, 1.75
    columns = length > (900 if has_map else 1200)
    return font, line_height, columns


def _build_location_summary_slide(slide, project_data, branding=None):
    """The site-analysis page: the approved reading beside the overview map."""
    source = project_data if isinstance(project_data, dict) else {}
    en = resolve_offer_lang(source) == OFFER_LANG_ENGLISH
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = str((slide or {}).get('title') or (
        'Location Summary' if en else 'ملخص الموقع الجغرافي'))
    paragraphs = _site_analysis_paragraphs(slide, source)
    tokens = [str(token) for token in ((slide or {}).get('image_tokens') or [])
              if str(token or '').strip()]
    map_token = next(
        (token for token in tokens if token.upper().startswith('##MAP_')), '')
    has_map = bool(map_token)

    font, line_height, columns = _site_analysis_text_style(paragraphs, has_map)
    if paragraphs:
        text_body = ''.join(
            '<div data-site-analysis-text="1" style="font-size:' + str(font) + 'px;'
            f'line-height:{line_height};color:#334155;text-align:justify;'
            f'border-inline-start:3px solid {accent};padding-inline-start:14px;'
            'margin-bottom:10px;word-break:break-word;">'
            + html_lib.escape(paragraph) + '</div>'
            for paragraph in paragraphs
        )
    else:
        text_body = (
            '<div data-site-analysis-text="1" style="font-size:12.5px;color:#94a3b8;">'
            + ('No approved site summary yet' if en else 'لم يُعتمد ملخص للموقع بعد')
            + '</div>')

    text_card = (
        '<div data-location-card="1" style="display:flex;flex-direction:column;min-width:0;'
        'min-height:0;flex:1;'
        'border:1px solid #d9e2ec;border-radius:14px;overflow:hidden;background:#fff;">'
        + _location_card_header(
            'Site reading' if en else 'القراءة التحليلية للموقع', '', primary)
        + '<div style="flex:1;min-height:0;overflow:hidden;padding:18px 20px;'
        + ('column-count:2;column-gap:28px;' if columns
           else 'display:flex;flex-direction:column;justify-content:center;')
        + f'">{text_body}</div>'
        # A page without the map still owns the caption slot, so the measurement
        # date stays inside the frame instead of floating over the facts strip.
        + ('' if has_map else (
            '<div data-map-caption="1" style="height:36px;flex:0 0 auto;display:flex;'
            'align-items:center;padding:0 16px;background:#f8fafc;border-top:1px solid #e2e8f0;'
            'font-size:10.5px;color:#64748b;line-height:1.45;"></div>'))
        + '</div>')

    if has_map:
        map_card = (
            '<div data-location-card="1" style="display:flex;flex-direction:column;min-width:0;'
            'border:1px solid #d9e2ec;border-radius:14px;overflow:hidden;background:#fff;">'
            '<div style="position:relative;width:100%;padding-top:56.25%;background:#eef2f6;">'
            f'<img src="{map_token}" alt="" style="position:absolute;inset:0;width:100%;height:100%;'
            'object-fit:contain;object-position:center center;display:block;"></div>'
            '<div style="height:44px;flex:0 0 auto;display:flex;align-items:center;'
            'justify-content:space-between;gap:12px;padding:0 14px;border-top:1px solid #e2e8f0;'
            'background:#f8fafc;">'
            '<div data-map-caption="1" style="font-size:10.5px;color:#64748b;line-height:1.45;"></div>'
            f'<div style="font-size:10px;font-weight:700;color:#94a3b8;white-space:nowrap;">'
            f'{html_lib.escape("Google Maps" if en else "خرائط Google")}</div></div></div>')
        # The card never covers the marker the map image already carries.
        marker_side = str(source.get('_map_marker_side') or 'right').strip().lower()
        columns_html = (text_card + map_card) if marker_side == 'left' else (map_card + text_card)
        body = (
            '<div style="display:grid;grid-template-columns:1.08fr 1fr;gap:24px;align-items:stretch;'
            'min-height:0;">' + columns_html + '</div>')
    else:
        body = '<div style="display:flex;min-width:0;min-height:0;flex:1;">' + text_card + '</div>'

    nearest, count = _location_landmark_row_metrics(
        source, 'nearby_landmarks_data', 'nearby_landmarks')
    metrics = [
        ('City & district' if en else 'المدينة والحي',
         ' — '.join(part for part in (
             str(source.get('city') or '').strip(),
             str(source.get('district') or '').strip()) if part), ''),
        ('Nearest landmark' if en else 'أقرب معلم', nearest, ''),
        ('Nearby landmarks' if en else 'المعالم القريبة',
         str(count) if count else '', ''),
    ]
    if not any(str(value or '').strip() for _, value, _ in metrics):
        metrics = [
            ('Coordinates' if en else 'الإحداثيات',
             _location_coordinates_text(source), ''),
            ('Main corridors' if en else 'المحاور الرئيسية', str(len(_location_road_names(source)))
             if _location_road_names(source) else '', ''),
        ]

    return _location_page(
        body, _location_metric_strip(metrics, primary), title,
        'SITE ANALYSIS' if en else 'تحليل الموقع',
        ('The approved reading of the site, its position and its access' if en
         else 'القراءة المعتمدة لموقع المشروع وموضعه ونطاق الوصول إليه'),
        primary, accent, en, kind='site-analysis')
