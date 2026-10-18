"""Land boundary data extraction and diagram rendering."""

def _extract_land_boundary_diagram_data(project_data):
    """Extract structured data for the directional land boundary diagram."""
    source = project_data if isinstance(project_data, dict) else {}

    facades_count = str(source.get('facades_count') or '').strip()
    facades_directions = str(source.get('facades_directions') or '').strip()

    facades_summary = ''
    if facades_count and facades_directions:
        if facades_count in ('2', 'واجهتان'):
            count_text = 'واجهتان'
        elif facades_count in ('1', 'واجهة'):
            count_text = 'واجهة واحدة'
        elif facades_count.isdigit() and int(facades_count) > 2:
            count_text = f'{facades_count} واجهات'
        else:
            count_text = f'{facades_count} واجهات' if 'واجه' not in facades_count else facades_count
        facades_summary = f'{count_text} ({facades_directions})'
    elif facades_directions:
        facades_summary = f'الواجهات: {facades_directions}'
    elif facades_count:
        facades_summary = f'عدد الواجهات: {facades_count}'

    directions = {
        'north': {'label': 'الشمال', 'length': '', 'description': '', 'is_facade': False, 'setback': ''},
        'south': {'label': 'الجنوب', 'length': '', 'description': '', 'is_facade': False, 'setback': ''},
        'east': {'label': 'الشرق', 'length': '', 'description': '', 'is_facade': False, 'setback': ''},
        'west': {'label': 'الغرب', 'length': '', 'description': '', 'is_facade': False, 'setback': ''},
    }
    dir_aliases = {
        'north': ('north', 'شمال', 'الشمال'),
        'south': ('south', 'جنوب', 'الجنوب'),
        'east': ('east', 'شرق', 'الشرق'),
        'west': ('west', 'غرب', 'الغرب'),
    }

    raw_dt = source.get('directions_table')
    dt_rows = _decode_json_fact(raw_dt) if isinstance(raw_dt, str) else raw_dt
    if isinstance(dt_rows, dict):
        dt_rows = [dict(value, direction=key) if isinstance(value, dict) else {
            'direction': key, 'description': value
        } for key, value in dt_rows.items()]
    if isinstance(dt_rows, list):
        for row in dt_rows:
            if not isinstance(row, dict):
                continue
            dir_key = str(row.get('direction') or row.get('label') or '').strip().lower()
            reg_text = str(row.get('regulation_text') or row.get('text') or row.get('description') or '').strip()
            length_val = str(row.get('boundary_length') or row.get('boundary_length_m') or row.get('length') or '').strip()
            street_val = str(row.get('street_name') or row.get('street') or '').strip()
            neighbour_val = str(row.get('neighbour') or row.get('neighbor') or row.get('adjacent') or '').strip()
            width_val = str(row.get('street_width') or row.get('street_width_m') or row.get('width') or '').strip()
            uses_val = str(row.get('uses') or row.get('use') or '').strip()
            setback_val = str(row.get('setback') or row.get('setbacks') or row.get('artidad') or '').strip()
            for std_key, aliases in dir_aliases.items():
                if dir_key in aliases or any(a in dir_key for a in aliases):
                    if reg_text and not directions[std_key]['description']:
                        directions[std_key]['description'] = reg_text
                    if length_val and not directions[std_key]['length']:
                        directions[std_key]['length'] = length_val if 'م' in length_val else f"{length_val} م"
                    if street_val and not directions[std_key].get('street_name'):
                        directions[std_key]['street_name'] = street_val
                    if neighbour_val and not directions[std_key].get('neighbour'):
                        directions[std_key]['neighbour'] = neighbour_val
                    if width_val and not directions[std_key].get('street_width'):
                        directions[std_key]['street_width'] = width_val if 'م' in width_val else f"{width_val} م"
                    if uses_val and not directions[std_key].get('uses'):
                        directions[std_key]['uses'] = uses_val
                    if setback_val and not directions[std_key].get('setback'):
                        directions[std_key]['setback'] = setback_val if 'م' in setback_val else f"{setback_val} م"
                    break

    land_analysis = _decode_json_fact(source.get('land_documents_analysis_data') or source.get('landDocumentsAnalysisData') or source.get('land_documents_analysis'))
    if isinstance(land_analysis, dict):
        parcels = land_analysis.get('parcels') if isinstance(land_analysis.get('parcels'), list) else []
        parcel_dirs = parcels[0].get('directions') if parcels and isinstance(parcels[0], dict) and isinstance(parcels[0].get('directions'), dict) else {}
        if not parcel_dirs and isinstance(land_analysis.get('directions'), dict):
            parcel_dirs = land_analysis.get('directions')
        for std_key, aliases in dir_aliases.items():
            for alias in aliases:
                if alias in parcel_dirs and isinstance(parcel_dirs[alias], dict):
                    p_info = parcel_dirs[alias]
                    desc = str(p_info.get('regulation_text') or p_info.get('uses') or '').strip()
                    length = p_info.get('boundary_length_m') or p_info.get('length')
                    width = p_info.get('street_width_m') or p_info.get('width')
                    street = str(p_info.get('street_name') or '').strip()
                    neighbour = str(p_info.get('neighbour') or p_info.get('neighbor') or p_info.get('adjacent') or '').strip()
                    setback_p = str(p_info.get('setback') or p_info.get('setbacks') or p_info.get('artidad') or '').strip()
                    if desc and not directions[std_key]['description']:
                        directions[std_key]['description'] = desc
                    if length and not directions[std_key]['length']:
                        directions[std_key]['length'] = f"{length} م"
                    if street and not directions[std_key].get('street_name'):
                        directions[std_key]['street_name'] = street
                    if neighbour and not directions[std_key].get('neighbour'):
                        directions[std_key]['neighbour'] = neighbour
                    if width and not directions[std_key].get('street_width'):
                        directions[std_key]['street_width'] = f"{width} م"
                    if setback_p and not directions[std_key].get('setback'):
                        directions[std_key]['setback'] = setback_p if 'م' in setback_p else f"{setback_p} م"
                    break

    raw_lengths = str(source.get('boundary_lengths') or '').strip()
    if raw_lengths:
        for part in re.split(r'[|,\n،]', raw_lengths):
            part = part.strip()
            if not part:
                continue
            for std_key, aliases in dir_aliases.items():
                if any(part.startswith(a) or f"{a}:" in part or f"{a} :" in part for a in aliases):
                    val = re.sub(r'^(?:' + '|'.join(aliases) + r')\s*[:=\-—]\s*', '', part).strip()
                    if val and not directions[std_key]['length']:
                        directions[std_key]['length'] = val if 'م' in val else f"{val} م"
                    break

    raw_streets = str(source.get('surrounding_streets') or '').strip()
    if raw_streets:
        for part in re.split(r'[|,\n،]', raw_streets):
            part = part.strip()
            if not part:
                continue
            for std_key, aliases in dir_aliases.items():
                if any(part.startswith(a) or f"{a}:" in part or f"{a} :" in part for a in aliases):
                    val = re.sub(r'^(?:' + '|'.join(aliases) + r')\s*[:=\-—]\s*', '', part).strip()
                    if val and not directions[std_key].get('street_name') and not directions[std_key].get('neighbour'):
                        if re.search(r'(?:شارع|طريق|ممر|ميدان|نافذ|street|road)', val):
                            directions[std_key]['street_name'] = val
                        else:
                            directions[std_key]['neighbour'] = val
                    break

    raw_setbacks = str(source.get('setbacks') or '').strip()
    if raw_setbacks:
        dir_setback_words = (
            ('north', r'(?:الجهة\s+)?(?:ال)?شمالي?(?:ة)?'),
            ('south', r'(?:الجهة\s+)?(?:ال)?جنوبي?(?:ة)?'),
            ('east', r'(?:الجهة\s+)?(?:ال)?شرقي?(?:ة)?'),
            ('west', r'(?:الجهة\s+)?(?:ال)?غربي?(?:ة)?'),
        )
        for std_key, word in dir_setback_words:
            if not directions[std_key].get('setback'):
                match = re.search(word + r'\s*[:=\-–—]?\s*([0-9٠-٩]+(?:[.,][0-9]+)?\s*(?:متر|م\.?))', raw_setbacks)
                if match:
                    val = match.group(1).strip()
                    directions[std_key]['setback'] = val if 'م' in val else f"{val} م"
        front_m = re.search(r'(?:أمامي|الواجهة|الشارع)\s*[:=\-–—]?\s*([0-9٠-٩]+(?:[.,][0-9]+)?\s*(?:متر|م\.?))', raw_setbacks)
        rear_m = re.search(r'(?:خلفي|الخلف)\s*[:=\-–—]?\s*([0-9٠-٩]+(?:[.,][0-9]+)?\s*(?:متر|م\.?))', raw_setbacks)
        side_m = re.search(r'(?:جانبي|الجانبين|الجانبيان|الجوانب)\s*[:=\-–—]?\s*([0-9٠-٩]+(?:[.,][0-9]+)?\s*(?:متر|م\.?))', raw_setbacks)
        for std_key, d in directions.items():
            if not d.get('setback'):
                if d.get('is_facade') and front_m:
                    d['setback'] = front_m.group(1).strip()
                elif not d.get('is_facade') and rear_m:
                    d['setback'] = rear_m.group(1).strip()
                elif side_m:
                    d['setback'] = side_m.group(1).strip()

    raw_streets = str(source.get('surrounding_streets') or '').strip()
    for std_key, d in directions.items():
        desc = f"{d.get('description', '')} {d.get('street_name', '')} {raw_streets}"
        if re.search(r'(?:شارع|طريق|ممر|ميدان|نافذ|street|road|avenue|boulevard)', desc):
            d['is_facade'] = True
            d['type'] = 'street'
        else:
            d['type'] = 'neighbor'

    key_view = ''
    full_text = f"{raw_streets} {json.dumps(directions, ensure_ascii=False)}"
    if re.search(r'(?:كورنيش|بحر|إطلالة بحرية|شاطئ|واجهة بحرية|sea view|corniche)', full_text, re.IGNORECASE):
        for std_key in ('west', 'north', 'east', 'south'):
            dir_text = json.dumps(directions.get(std_key, {}), ensure_ascii=False)
            if re.search(r'(?:كورنيش|بحر|إطلالة بحرية|شاطئ|واجهة بحرية)', dir_text):
                lbl = directions[std_key]['label']
                key_view = f"جهة {lbl} — جهة الإطلالة البحرية وطريق الكورنيش"
                break
        if not key_view:
            key_view = "جهة الإطلالة البحرية وطريق الكورنيش"
    elif re.search(r'(?:طريق رئيسي|محور|بوليفارد|شريان)', full_text):
        for std_key in ('west', 'north', 'east', 'south'):
            dir_text = json.dumps(directions.get(std_key, {}), ensure_ascii=False)
            if re.search(r'(?:طريق رئيسي|محور|طريق|بوليفارد)', dir_text):
                lbl = directions[std_key]['label']
                key_view = f"جهة {lbl} — واجهة الطريق الرئيسي"
                break

    return {
        'plot_name': 'أرض المشروع',
        'facades_summary': facades_summary or 'الواجهات المحيطة بالأرض',
        'north': directions['north'],
        'south': directions['south'],
        'east': directions['east'],
        'west': directions['west'],
        'key_view': key_view,
        'boundary_lengths_summary': raw_lengths,
        'surrounding_streets_summary': raw_streets,
    }


def _has_land_boundary_data(project_data):
    """Return whether the project has enough boundary evidence for the fixed diagram.

    Boundary facts can arrive through visible croquis fields or through the hidden
    structured result persisted from the land documents.  Looking only at the four
    visible scalar fields made the diagram disappear after a document-only analysis
    and, consequently, from location-only presentation generation.
    """
    source = project_data if isinstance(project_data, dict) else {}
    if any(str(source.get(key) or '').strip() for key in (
        'boundary_lengths', 'surrounding_streets', 'facades_count', 'facades_directions',
    )):
        return True
    data = _extract_land_boundary_diagram_data(source)
    if str(data.get('key_view') or '').strip():
        return True
    for key in ('north', 'south', 'east', 'west'):
        item = data.get(key) if isinstance(data.get(key), dict) else {}
        if any(str(item.get(field) or '').strip() for field in (
            'length', 'description', 'street_name', 'street_width'
        )):
            return True
    return False


def _build_land_boundary_diagram_slide(slide, project_data, branding, slide_num=None, total_slides=None):
    """Render the boundary diagram deterministically from approved land facts."""
    source = project_data if isinstance(project_data, dict) else {}
    data = _extract_land_boundary_diagram_data(source)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'مخطط اتجاهي لحدود الأرض'))
    project_name = html_lib.escape(str(data.get('plot_name') or source.get('project_name') or 'أرض المشروع'))

    def safe(value, fallback='غير متاح'):
        value = str(value or '').strip()
        return html_lib.escape(value or fallback)

    def card(direction_key):
        item = data.get(direction_key) if isinstance(data.get(direction_key), dict) else {}
        facade = bool(item.get('is_facade'))
        border = accent if facade else '#d9e3ec'
        label = safe(item.get('label'))
        length = safe(item.get('length'))
        street = str(item.get('street_name') or '').strip()
        description = str(item.get('description') or '').strip()
        neighbour = str(item.get('neighbour') or '').strip()
        width = safe(item.get('street_width')) if item.get('street_width') else ''
        uses = safe(item.get('uses')) if item.get('uses') else ''
        setback = safe(item.get('setback')) if item.get('setback') else ''

        lines = []
        if street:
            lines.append(f'<div style="margin-top:5px;color:{primary};font-size:11.5px;font-weight:700;">{safe(street)}</div>')
        elif neighbour:
            lines.append(f'<div style="margin-top:5px;color:{primary};font-size:11.5px;font-weight:700;">المجاور: {safe(neighbour)}</div>')
        if width:
            lines.append(f'<div style="margin-top:3px;color:#475569;font-size:10.5px;">عرض الشارع: {width}</div>')
        if neighbour and street:
            lines.append(f'<div style="margin-top:3px;color:#475569;font-size:10.5px;">المجاور: {safe(neighbour)}</div>')
        if setback:
            lines.append(f'<div style="margin-top:3px;color:#047857;font-size:10.5px;font-weight:700;">الارتداد: {setback}</div>')
        if description and description != street and description != neighbour:
            lines.append(f'<div style="margin-top:4px;color:#64748b;font-size:10px;line-height:1.35;">{safe(description)}</div>')
        elif uses:
            lines.append(f'<div style="margin-top:4px;color:#64748b;font-size:10px;line-height:1.35;">{uses}</div>')

        details_html = ''.join(lines)
        return (
            f'<div data-boundary-direction="{direction_key}" style="min-height:120px;border:2px solid {border};'
            f'border-radius:14px;background:#ffffff;padding:12px 14px;box-sizing:border-box;direction:rtl;'
            f'display:flex;flex-direction:column;justify-content:center;overflow:hidden;">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">'
            f'<span style="font-size:17px;font-weight:800;color:{primary};">{label}</span>'
            f'<span dir="ltr" style="font-size:20px;font-weight:800;color:{accent};white-space:nowrap;">{length}</span></div>'
            f'<div style="height:1px;background:#e2e8f0;margin:6px 0 0;"></div>{details_html}'
            '</div>'
        )

    key_view = str(data.get('key_view') or '').strip()
    view_html = (
        f'<div style="margin-top:10px;border-radius:9px;background:{accent};color:#172033;padding:8px 12px;'
        f'font-size:11px;font-weight:800;line-height:1.35;">{html_lib.escape(key_view)}</div>'
        if key_view else ''
    )
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;color:#172033;box-sizing:border-box;padding:76px 42px 48px;">
  <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:12px;">
    <div><h2 style="margin:0;color:{primary};font-size:28px;line-height:1.15;font-weight:800;">{title}</h2>
    <div style="margin-top:5px;color:#64748b;font-size:11px;">الأبعاد بالمتر</div></div>
    <div style="height:4px;width:82px;background:{accent};border-radius:4px;"></div>
  </div>
  <div data-boundary-diagram="1" style="height:500px;border:1px solid #dbe5ed;border-radius:16px;background:#f8fafc;padding:12px;box-sizing:border-box;display:grid;grid-template-columns:1fr 1.65fr 1fr;grid-template-rows:minmax(120px,1fr) minmax(180px,1.3fr) minmax(120px,1fr);gap:10px;direction:ltr;">
    <div style="grid-column:2;grid-row:1;">{card('north')}</div>
    <div style="grid-column:1;grid-row:2;">{card('west')}</div>
    <div style="grid-column:2;grid-row:2;border-radius:18px;background:{primary};color:#ffffff;border:3px solid {accent};padding:22px;box-sizing:border-box;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;direction:rtl;overflow:hidden;">
      <div style="font-size:27px;font-weight:800;line-height:1.2;">{project_name}</div>
      <div style="width:68px;height:3px;background:{accent};margin:13px 0;"></div>
      <div style="font-size:14px;line-height:1.55;color:#ffffff;">{safe(data.get('facades_summary'))}</div>{view_html}
    </div>
    <div style="grid-column:3;grid-row:2;">{card('east')}</div>
    <div style="grid-column:2;grid-row:3;">{card('south')}</div>
  </div>
  <div style="margin-top:9px;text-align:center;color:#64748b;font-size:10px;line-height:1.35;">تمثل القراءة اتجاهات الحدود وعلاقتها بالشوارع دون محاكاة مساحية للنسب.</div>
  <div data-slide-counter="1" style="display:none;">{slide_num_str}</div>
</div>'''
