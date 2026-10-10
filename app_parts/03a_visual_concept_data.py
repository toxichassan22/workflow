def _visual_concept_text(value, limit=4000):
    if value is None:
        return ''
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        parts = [_visual_concept_text(item, 400) for item in value]
        return '، '.join(part for part in parts if part).strip()[:limit]
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)[:limit]
    return str(value).strip()[:limit]


def _visual_concept_parse_json(value, fallback=None):
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return fallback
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, (dict, list)) else fallback


def _visual_concept_number(value):
    if isinstance(value, bool) or value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')).replace(',', '')
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _visual_concept_read(project_data, *keys):
    source = project_data if isinstance(project_data, dict) else {}
    for key in keys:
        if key in source and source[key] not in (None, ''):
            return source[key]
    return ''


def _visual_concept_components(project_data):
    source = project_data if isinstance(project_data, dict) else {}
    financial = _visual_concept_parse_json(source.get('financial_study_model'), {})
    financial = financial if isinstance(financial, dict) else {}
    dynamic_rows = financial.get('dynamicRows') if isinstance(financial.get('dynamicRows'), dict) else {}
    rows = dynamic_rows.get('components')
    if not isinstance(rows, list):
        rows = _visual_concept_parse_json(_visual_concept_read(source, 'project_components_data'), [])
    output = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        name = _visual_concept_text(item.get('name') or item.get('component') or item.get('title'), 160)
        if not name:
            continue
        component_id = _visual_concept_text(item.get('id') or item.get('componentId') or item.get('component_id'), 80)
        output.append({
            'id': component_id or f'component_{len(output) + 1}',
            'name': name,
            'useType': _visual_concept_text(item.get('useType') or item.get('type'), 80),
            'units': _visual_concept_number(item.get('units') or item.get('count')),
            'unitArea': _visual_concept_number(item.get('unitArea') or item.get('area_sqm')),
            'builtArea': _visual_concept_number(item.get('builtArea') or item.get('totalArea') or item.get('area_sqm')),
            'floorRange': _visual_concept_text(
                item.get('floorRange') or item.get('floor_range') or item.get('floor_span')
                or item.get('floors') or item.get('levels'), 120),
            'building': _visual_concept_text(item.get('building') or item.get('buildingName'), 100),
            'notes': _visual_concept_text(item.get('description') or item.get('notes'), 300),
            'parkingLocation': _visual_concept_text(item.get('parkingLocation'), 40),
            'parkingPlanId': _visual_concept_text(item.get('parkingPlanId'), 80),
        })
        if len(output) >= 40:
            break
    return output


def _visual_concept_directions(project_data):
    raw = _visual_concept_parse_json(_visual_concept_read(project_data, 'directions_table'), None)
    if isinstance(raw, dict):
        raw = [{'direction': key, **(value if isinstance(value, dict) else {'regulation_text': value})}
               for key, value in raw.items()]
    if not isinstance(raw, list):
        return []
    labels = {'north': 'شمال', 'south': 'جنوب', 'east': 'شرق', 'west': 'غرب',
              'شمال': 'شمال', 'جنوب': 'جنوب', 'شرق': 'شرق', 'غرب': 'غرب'}
    rows = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        direction = _visual_concept_text(item.get('direction') or item.get('label'), 40)
        label = labels.get(direction.lower(), direction or labels.get(item.get('label'), ''))
        text = _visual_concept_text(
            item.get('regulation_text') or item.get('regulation') or item.get('text') or item.get('notes'),
            400,
        )
        setback = _visual_concept_text(item.get('setback') or item.get('setback_m'), 120)
        if setback:
            text = (text + ' — الارتداد: ' + setback) if text else ('الارتداد: ' + setback)
        if not text:
            continue
        rows.append({'direction': label or direction, 'regulation_text': text})
    return rows


def _visual_concept_list(value):
    if isinstance(value, list):
        values = value
    elif isinstance(value, str):
        parsed = _visual_concept_parse_json(value, None)
        values = parsed if isinstance(parsed, list) else ([value] if value.strip() else [])
    else:
        values = []
    return [str(item).strip() for item in values if str(item).strip()]
