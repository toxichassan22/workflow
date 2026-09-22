

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Project team library (فريق العمل)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _team_entity_payload(data):
    """Normalise a team-entity request body; returns (fields, error)."""
    name = str(data.get('name') or '').strip()
    if not name:
        return None, 'اسم الجهة مطلوب'
    logo_file_id = str(data.get('logoFileId') or '').strip()
    if logo_file_id and not db.get_project_file(g.tenant_id, logo_file_id):
        return None, 'شعار الجهة غير موجود'
    return {
        'name': name,
        'logo_file_id': logo_file_id,
        'brief': str(data.get('brief') or '').strip(),
        'experience_years': str(data.get('experienceYears') or '').strip(),
        'notable_projects': str(data.get('notableProjects') or '').strip(),
        'role': str(data.get('role') or '').strip(),
    }, None


@app.route('/api/team-entities', methods=['GET'])
@require_auth
def api_list_team_entities():
    """Company-wide team library; every project file starts from this list."""
    return jsonify({'success': True, 'entities': db.get_team_entities(g.tenant_id)})


@app.route('/api/team-entities', methods=['POST'])
@require_permission('company_settings')
def api_create_team_entity():
    fields, error = _team_entity_payload(request.json or {})
    if error:
        return jsonify({'success': False, 'error': error}), 400
    entity_id = db.create_team_entity(g.tenant_id, fields.pop('name'), **fields)
    return jsonify({'success': True, 'entity': db.get_team_entity(g.tenant_id, entity_id)}), 201


@app.route('/api/team-entities/<entity_id>', methods=['PUT'])
@require_permission('company_settings')
def api_update_team_entity(entity_id):
    if not db.get_team_entity(g.tenant_id, entity_id):
        return jsonify({'success': False, 'error': 'الجهة غير موجودة'}), 404
    fields, error = _team_entity_payload(request.json or {})
    if error:
        return jsonify({'success': False, 'error': error}), 400
    db.update_team_entity(g.tenant_id, entity_id, **fields)
    return jsonify({'success': True, 'entity': db.get_team_entity(g.tenant_id, entity_id)})


@app.route('/api/team-entities/<entity_id>', methods=['DELETE'])
@require_permission('company_settings')
def api_delete_team_entity(entity_id):
    if not db.delete_team_entity(g.tenant_id, entity_id):
        return jsonify({'success': False, 'error': 'الجهة غير موجودة'}), 404
    return jsonify({'success': True})


@app.route('/api/field-sections/custom', methods=['POST'])
@require_permission('custom_fields')
def api_add_custom_section():
    """Create a custom field section."""
    data = request.json or {}
    label = (data.get('label') or '').strip()
    if not label:
        return jsonify({'error': 'اسم القسم مطلوب'}), 400
    # Generate key from label if not provided
    key = (data.get('key') or '').strip().lower().replace(' ', '_').replace('-', '_')
    if not key:
        import re as _re
        # Transliterate Arabic to approximate key
        ar_map = {'أ': 'a', 'إ': 'a', 'آ': 'a', 'ا': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th', 'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'th', 'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a', 'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n', 'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ة': 'a', 'ء': '', 'ئ': 'y', 'ؤ': 'w'}
        key = ''.join(ar_map.get(c, c) for c in label)
        key = _re.sub(r'[^a-zA-Z0-9_]', '', key)
        if not key:
            key = 'section_' + str(_uuid.uuid4())[:8]
    # Prevent collision with built-in keys
    builtin_keys = {s['key'] for s in db.FIELD_SECTIONS}
    if key in builtin_keys:
        return jsonify({'error': 'لا يمكن استخدام اسم قسم موجود مسبقاً'}), 400
    sort_order = int(data.get('sortOrder', 100))
    section_id = db.add_custom_section(g.tenant_id, key, label, sort_order)
    if not section_id:
        return jsonify({'error': 'قسم بهذا الاسم موجود مسبقاً'}), 409
    return jsonify({'success': True, 'sectionId': section_id, 'key': key}), 201


@app.route('/api/field-sections/custom/<section_key>', methods=['PUT'])
@require_permission('custom_fields')
def api_update_custom_section(section_key):
    """Update a custom field section."""
    # The route is deliberately custom-only: built-in section labels and
    # structure stay stable, while each company can rename its own additions.
    if not db.get_custom_section(g.tenant_id, section_key):
        return jsonify({'error': 'Custom section not found'}), 404

    data = request.json or {}
    updates = {}
    if 'label' in data:
        label = (data.get('label') or '').strip()
        if not label:
            return jsonify({'error': 'اسم القسم لا يمكن أن يكون فارغاً'}), 400
        updates['section_label'] = label
    if 'sortOrder' in data:
        updates['sort_order'] = int(data.get('sortOrder', 100))
    if 'isActive' in data:
        updates['is_active'] = 1 if data.get('isActive') else 0
    if not updates:
        return jsonify({'error': 'لا توجد تغييرات'}), 400
    db.update_custom_section(g.tenant_id, section_key, **updates)
    return jsonify({'success': True})


def _stringify_chat_part(value):
    """Flatten OpenRouter/OpenAI message fragments into a single string."""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(_stringify_chat_part(item) for item in value)
    if isinstance(value, dict):
        for key in ('text', 'content', 'reasoning', 'output', 'summary'):
            fragment = value.get(key)
            if fragment not in (None, '', [], {}):
                return _stringify_chat_part(fragment)
        return ''
    return str(value)


def _get_chat_response_text(res):
    """Safely extract string content from OpenAI/GLM/OpenRouter chat response dict."""
    if not isinstance(res, dict):
        return str(res) if res else ""
    if 'choices' in res and isinstance(res['choices'], list) and res['choices']:
        choice = res['choices'][0]
        if isinstance(choice, dict):
            msg = choice.get('message', {})
            if isinstance(msg, dict):
                for key in ('content', 'reasoning', 'reasoning_content', 'reasoning_details'):
                    text = _stringify_chat_part(msg.get(key))
                    if text and str(text).strip():
                        return text
                parsed = msg.get('parsed')
                if isinstance(parsed, dict):
                    return json.dumps(parsed, ensure_ascii=False)
                return ''
            return str(choice.get('text', '') or '')
    return ""


def parse_json_object(text):
    """Extract and parse any JSON dict from text string, including auto-repairing truncated JSON."""
    if not text or not isinstance(text, str):
        return {}
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    cb = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)
    if cb:
        try:
            parsed = json.loads(cb.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    start = text.find('{')
    if start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if esc:
                esc = False
                continue
            if c == '\\' and in_str:
                esc = True
                continue
            if c == '"' and not esc:
                in_str = not in_str
                continue
            if not in_str:
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(text[start:i+1])
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            pass
                        break
        # Auto-repair truncated unclosed JSON
        if depth > 0 or in_str:
            partial = text[start:]
            partial = re.sub(r'\\u[0-9a-fA-F]{0,3}$', '', partial)
            partial = re.sub(r'\\$', '', partial)
            if in_str:
                partial += '"'
            effective_depth = max(1, depth)
            for d in range(effective_depth, 0, -1):
                attempt = partial + ('}' * d)
                try:
                    parsed = json.loads(attempt)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
    return {}


PLACEHOLDER_VALUE_PHRASES = (
    'غير مدون', 'غير مذكور', 'غير موضح', 'غير متاح', 'غير محدد',
    'لا يوجد', 'n/a', 'none', 'null', 'غير مدونة',
)

# Cardinal/ordinal wording that belongs in the facade *directions* field, never in the count.
FACADE_DIRECTION_WORDS = ('شمال', 'جنوب', 'شرق', 'غرب', 'قبلي', 'بحري')

FACADE_COUNT_PATTERNS = (
    ('4', ('بلك كامل', 'بلك', 'أربع', 'اربع', '4 واجهات', 'أربعة شوارع', 'اربعة شوارع')),
    ('3', ('ثلاث', '3 واجهات', 'ثلاثة شوارع', '3 شوارع')),
    ('2', ('زاوية', 'زاوي', 'شارعين', 'واجهتين', 'واجهتان', '2 واجهة')),
    ('1', ('واجهة واحدة', 'شارع واحد', '1 واجهة')),
)


def is_placeholder_value(value):
    """True for short "not stated" answers that must not be stored as real data."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and len(text) < 20 and any(
        phrase in text.lower() for phrase in PLACEHOLDER_VALUE_PHRASES
    )


def normalize_facades_count(value, fallback_text=''):
    """Coerce the facade count to a bare 1-4.

    The form field is numeric, so a direction word ("جنوبية") is rejected outright instead
    of being written into the field; the caller keeps the wording in facades_directions.
    """
    text = '' if value is None else str(value).strip()
    digits = re.findall(r'[1-4]', text)
    if digits:
        return digits[0]
    for count, patterns in FACADE_COUNT_PATTERNS:
        if any(pattern in text for pattern in patterns):
            return count
    if text and not any(word in text for word in FACADE_DIRECTION_WORDS):
        return ''
    for count, patterns in FACADE_COUNT_PATTERNS:
        if any(pattern in fallback_text for pattern in patterns):
            return count
    return ''


FACADE_SIDE_LABELS = (('north', 'شمالية'), ('south', 'جنوبية'), ('east', 'شرقية'), ('west', 'غربية'))

# A boundary that abuts another plot is not a facade, however the cell is worded.
FACADE_NEIGHBOUR_HINTS = ('جار', 'مجاور', 'قطعة', 'قطعه', 'ملك', 'أرض فضاء', 'حد القطعة')
FACADE_STREET_HINTS = ('شارع', 'طريق', 'ممر', 'كورنيش', 'ميدان', 'دوار', 'واجهة')


def facade_directions_from_streets(directions):
    """Return only the sides that actually front a street.

    A plot always has four boundaries, so listing all four compass points says nothing. What
    matters is which sides are facades — i.e. border a street rather than a neighbour.
    """
    found = []
    for side, label in FACADE_SIDE_LABELS:
        info = (directions or {}).get(side)
        if not isinstance(info, dict):
            continue
        text = ' '.join(
            str(info.get(key) or '') for key in ('street_name', 'uses', 'regulation_text')
        )
        width = info.get('street_width_m')
        has_width = width not in (None, '', 0, '0', '0.0')
        mentions_street = any(hint in text for hint in FACADE_STREET_HINTS)
        # "قطعة رقم 12" or "أرض مجاورة" means a neighbour, unless a street is named too.
        if any(hint in text for hint in FACADE_NEIGHBOUR_HINTS) and not mentions_street:
            continue
        if mentions_street or has_width:
            found.append(label)
    return '، '.join(found)


def normalize_facade_directions(*values):
    """Fallback for the legacy path: scan free text for cardinal directions."""
    haystack = ' '.join(str(value) for value in values if value)
    labels = (
        ('شمالية', ('شمالي', 'شمالية', 'الشمال', 'شمال')),
        ('جنوبية', ('جنوبي', 'جنوبية', 'الجنوب', 'جنوب')),
        ('شرقية', ('شرقي', 'شرقية', 'الشرق', 'شرق')),
        ('غربية', ('غربي', 'غربية', 'الغرب', 'غرب')),
    )
    found = [label for label, needles in labels if any(needle in haystack for needle in needles)]
    return '، '.join(found)


def normalize_north_direction(value):
    """Snap a free-text bearing onto one of the eight compass labels.

    Matches on the bare roots so wording like "الشمال الغربي" still resolves to a compound
    direction instead of collapsing to "شمال".
    """
    text = str(value or '').strip()
    if not text:
        return ''
    north, south = 'شمال' in text, 'جنوب' in text
    east, west = 'شرق' in text, 'غرب' in text
    for present, label in (
        (north and east, 'شمال شرقي'), (north and west, 'شمال غربي'),
        (south and east, 'جنوب شرقي'), (south and west, 'جنوب غربي'),
        (north, 'شمال'), (south, 'جنوب'), (east, 'شرق'), (west, 'غرب'),
    ):
        if present:
            return label
    return text


def strip_placeholder_values(payload):
    """Drop placeholder strings while leaving nested tables (dicts/lists) untouched."""
    cleaned = {}
    for key, value in (payload or {}).items():
        if isinstance(value, str):
            text = value.strip()
            if is_placeholder_value(text):
                continue
            cleaned[key] = text
        elif isinstance(value, (dict, list)):
            cleaned[key] = value
        elif value is not None:
            cleaned[key] = str(value)
    return cleaned


_LAND_USE_STATUS_LINE_RE = re.compile(
    r'(?:حالة\s*)?استخدام\s*(?:نوع\s*)?(?:المشروع|الأرض)\s*[:：]?\s*(مسموح|غير\s*مسموح|غير\s*محسوم|غير\s*محدد|ممنوع)',
    re.IGNORECASE,
)
_LAND_USE_STATUS_ONLY_RE = re.compile(
    r'^(حالة\s*استخدام\s*المشروع\s*[:：]\s*)?(مسموح|غير\s*مسموح|غير\s*محسوم|غير\s*محدد|ممنوع)\.?$',
    re.IGNORECASE,
)


def normalize_land_use_status(value):
    text = str(value or '').strip()
    if not text:
        return ''
    if re.search(r'غير\s*مسموح|ممنوع', text):
        return 'غير مسموح'
    if re.search(r'غير\s*محسوم|غير\s*محدد', text):
        return 'غير محسوم'
    if text == 'مسموح' or re.search(r'(^|[^\u0621-\u064A])مسموح([^\u0621-\u064A]|$)', text):
        return 'مسموح'
    return ''


def split_land_use_status_text(text):
    raw = str(text or '')
    match = _LAND_USE_STATUS_LINE_RE.search(raw)
    only = _LAND_USE_STATUS_ONLY_RE.fullmatch(raw.strip())
    status = normalize_land_use_status(
        (match.group(1) if match else '') or (only.group(2) if only else '') or raw
    )
    cleaned = _LAND_USE_STATUS_LINE_RE.sub('', raw)
    cleaned = re.sub(r'ولم ي[ُو]حدد نوع المشروع[^\n.]*[.\n]?', '', cleaned)
    cleaned = re.sub(r'\n{2,}', '\n', cleaned).strip(' \n-–—:')
    if _LAND_USE_STATUS_ONLY_RE.fullmatch(cleaned):
        cleaned = ''
    return status, cleaned


PROJECT_TYPE_USE_ALIASES = {
    'سكني': ('سكني',),
    'تجاري': ('تجاري',),
    'إداري': ('إداري', 'مكتبي', 'مكاتب'),
    'فندقي': ('فندقي', 'فندق'),
    'ترفيهي': ('ترفيهي', 'سياحي', 'ترفيه'),
    'صناعي': ('صناعي',),
    'لوجستي': ('لوجستي', 'مستودع', 'تخزين'),
    'صناعي ولوجستي': ('صناعي', 'لوجستي', 'مستودع', 'تخزين'),
    'متعدد الاستخدامات': ('متعدد', 'مختلط', 'متنوع', 'سكني', 'تجاري'),
    'طبي': ('طبي', 'صحي'),
    'تعليمي': ('تعليمي', 'مدرسة', 'جامعة'),
    'سيارات وترفيه': ('سيارات', 'ترفيهي', 'ترفيه'),
    'مختلط': ('مختلط', 'متنوع', 'سكني', 'تجاري', 'متعدد'),
}


def resolve_land_use_status(project_type, allowed_uses):
    """Compare the entered project type with extracted permitted uses.

    The model often leaves land_use_status unresolved even when the form sent
    "سكني" and the regulations already list residential use.
    """
    raw_project = project_type
    if isinstance(raw_project, str):
        try:
            parsed_project = json.loads(raw_project)
            raw_project = parsed_project
        except (TypeError, ValueError):
            raw_project = re.split(r'[,،\n;|]', raw_project)
    projects = raw_project if isinstance(raw_project, (list, tuple, set)) else [raw_project]
    projects = [str(item or '').strip() for item in projects if str(item or '').strip()]
    uses = str(allowed_uses or '').strip()
    if not projects:
        return 'غير محسوم'
    if not uses or uses.startswith('غير محدد'):
        return 'غير محسوم'
    aliases = [alias for project in projects for alias in PROJECT_TYPE_USE_ALIASES.get(project, (project,))]
    if any(alias and alias in uses for alias in aliases):
        return 'مسموح'
    return 'غير مسموح'


def apply_entered_land_use_status(result, project_type=''):
    if not isinstance(result, dict):
        return result
    parcels = result.get('parcels') if isinstance(result.get('parcels'), list) else []
    first = parcels[0] if parcels and isinstance(parcels[0], dict) else {}
    uses = str(result.get('allowed_uses') or first.get('allowed_uses') or '').strip()
    _, uses = split_land_use_status_text(uses)
    status = resolve_land_use_status(project_type, uses)
    if uses:
        result['allowed_uses'] = uses
        if first:
            first['allowed_uses'] = uses
    result['land_use_status'] = status
    if first:
        first['land_use_status'] = status
    return result


def merge_regulatory_access_requirements(payload):
    if not isinstance(payload, dict):
        return payload
    uses = str(payload.get('allowed_uses') or '').strip()
    legacy_uses = str(payload.get('allowed_uses_restrictions') or '').strip()
    if not uses and legacy_uses:
        uses = legacy_uses
    constraints = str(payload.get('regulatory_constraints') or '').strip()
    additions = []
    for label, key in (
        ('اشتراطات المواقف', 'parking_requirements'),
        ('اشتراطات المداخل والمخارج', 'entrances_exits_requirements'),
    ):
        value = str(payload.get(key) or '').strip()
        if value and value not in additions and value not in constraints:
            additions.append(f'{label}: {value}')
    if uses:
        payload['allowed_uses'] = uses
    if additions:
        constraints = '\n'.join([item for item in (constraints, *additions) if item])
    if constraints:
        payload['regulatory_constraints'] = constraints
    legacy_parts = [item for item in (uses, constraints) if item]
    if legacy_parts:
        payload['allowed_uses_restrictions'] = '\n'.join(legacy_parts)
    return payload


def normalize_croquis_fields(resp_json, text_content=""):
    """Normalize extracted croquis fields, map select dropdown values, filter invalid placeholders, and apply text regex fallbacks."""
    if not isinstance(resp_json, dict):
        resp_json = {}

    resp_json = strip_placeholder_values(resp_json)

    full_text = text_content + " " + json.dumps(resp_json, ensure_ascii=False)

    # 1. Deed number fallback
    if not resp_json.get('deed_number'):
        deed_match = re.search(r'(?:صك|الصك|مرجع|المرجع|وثيقة)\s*(?:رقم)?\s*[:\s]*([0-9]{8,14})', full_text)
        if deed_match:
            resp_json['deed_number'] = deed_match.group(1)

    # 2. Plot / plan number fallback
    if not resp_json.get('plot_number_croquis'):
        plot_match = re.search(r'(?:قطعة|قطعه|مخطط)\s*(?:رقم)?\s*[:\s]*([0-9/\-\sA-Za-z]+)', full_text)
        if plot_match:
            resp_json['plot_number_croquis'] = plot_match.group(1).strip()

    # 3. Land area fallback (Targeting "بموجب التنظيم")
    if not resp_json.get('croquis_land_area'):
        area_match = re.search(r'(?:بموجب التنظيم|المساحة بموجب التنظيم|المساحة التنظيمية|مساحة الأرض|المساحة الإجمالية|مساحة المخطط)\s*[:\s]*([0-9,.]+)', full_text)
        if area_match:
            resp_json['croquis_land_area'] = area_match.group(1).replace(',', '')

    # These values are client decisions, so AI output is never allowed to populate or overwrite them.
    resp_json.pop('approved_financial_area', None)
    resp_json.pop('approved_financial_area_sqm', None)
    resp_json.pop('approved_floor_count', None)
    resp_json.pop('approved_floors', None)
    resp_json.pop('approved_coverage_ratio', None)

    # 4. Facades count normalization & fallback (Pure Number: 1, 2, 3, 4)
    raw_facades = resp_json.get('facades_count', '')
    resp_json['facades_count'] = normalize_facades_count(raw_facades, full_text)
    if not resp_json.get('facades_directions'):
        directions_text = normalize_facade_directions(raw_facades, resp_json.get('surrounding_streets'))
        if directions_text:
            resp_json['facades_directions'] = directions_text

    # 5. Floors / Max height fallback
    if not resp_json.get('max_floors_height'):
        floor_match = re.search(r'(?:أدوار|دور|ارتفاع|الأدوار)\s*[:\s]*([^\n,.]+)', full_text)
        if floor_match:
            resp_json['max_floors_height'] = floor_match.group(1).strip()

    # 6. North direction normalization
    resp_json['north_direction'] = normalize_north_direction(resp_json.get('north_direction'))

    # 7. Apply Aliases across all keys
    aliases = {
        'plot_number_croquis': ['plot_number', 'plot_and_plan_number'],
        'croquis_land_area': ['land_area'],
        'deed_number': ['deed_or_reference_number'],
        'deed_date': ['deed_issue_date', 'deed_date_hijri'],
        'plan_number': ['plan_no', 'subdivision_plan_number'],
        'subdivision_number': ['section_number', 'part_number'],
        'boundary_lengths': ['boundary_dimensions'],
        'surrounding_streets': ['surrounding_streets_widths'],
        'building_ratio_coverage': ['building_coverage', 'building_ratio'],
        'building_ratio_setbacks': ['building_coverage_setbacks'],
        'setbacks': ['setback_requirements'],
        'allowed_uses': ['permitted_uses', 'allowed_land_uses'],
        'regulatory_constraints': ['restrictions', 'regulatory_restrictions'],
        'max_floors_height': ['height_or_floors_allowed'],
    }
    # 8. Apply aliases and build a source-faithful summary. Missing values stay
    # explicitly unknown; never invent a city, regulation, area, or validity.
    for canonical, alternatives in aliases.items():
        if resp_json.get(canonical) in (None, ''):
            for alternative in alternatives:
                if resp_json.get(alternative) not in (None, ''):
                    resp_json[canonical] = resp_json[alternative]
                    break

    merge_regulatory_access_requirements(resp_json)
    if not resp_json.get('building_ratio_coverage'):
        resp_json['building_ratio_coverage'] = land_rule_text(resp_json)
    if not resp_json.get('building_ratio_setbacks'):
        resp_json['building_ratio_setbacks'] = land_rule_text(resp_json, include_setbacks=True)
    if not resp_json.get('allowed_uses') and resp_json.get('allowed_uses_restrictions'):
        resp_json['allowed_uses'] = resp_json['allowed_uses_restrictions']
    summary_text = str(resp_json.get('land_and_building_summary', '')).replace('{}', '').strip()
    if not summary_text:
        labels = (
            ('رقم القطعة', resp_json.get('plot_number_croquis')),
            ('رقم المخطط', resp_json.get('plan_number')),
            ('رقم القسم', resp_json.get('subdivision_number')),
            ('رقم الصك/المرجع', resp_json.get('deed_number')),
            ('تاريخ الصك', resp_json.get('deed_date')),
            ('المساحة التنظيمية م²', resp_json.get('croquis_land_area')),
            ('الحدود والأبعاد', resp_json.get('boundary_lengths')),
            ('الاتجاهات', resp_json.get('directions') or resp_json.get('north_direction')),
            ('الشوارع والواجهات', resp_json.get('surrounding_streets')),
            ('نسب البناء والارتدادات', resp_json.get('building_ratio_setbacks')),
            ('الارتفاع/الأدوار', resp_json.get('max_floors_height')),
            ('اشتراطات المواقف', resp_json.get('parking_requirements')),
            ('المداخل والمخارج', resp_json.get('entrances_exits_requirements')),
            ('الاستخدامات والقيود', resp_json.get('allowed_uses_restrictions')),
        )
        available = [f'{label}: {value}' for label, value in labels if value not in (None, '', [], {})]
        summary_text = ' | '.join(available) if available else 'لم يتم استخراج بيانات مؤكدة؛ تحتاج الوثائق إلى مراجعة يدوية.'

    resp_json['land_and_building_summary'] = summary_text.replace('{}', '').strip()
    strip_regulation_references_from_payload(resp_json)

    return resp_json


REGULATION_OUTPUT_KEYS = {
    'building_ratio', 'coverage_ratio', 'floor_area_ratio', 'table_floors',
    'building_ratio_coverage', 'building_ratio_setbacks', 'setbacks',
    'max_floors_height', 'allowed_uses', 'allowed_uses_restrictions',
    'regulatory_constraints', 'parking_requirements', 'entrances_exits_requirements',
    'land_and_building_summary', 'document_summary', 'summary',
}


def strip_regulation_references(value):
    if not isinstance(value, str):
        return value
    cleaned = re.sub(
        r'(?:اشتراطات\s*[12](?:\.pdf)?\s*(?:[-–—]\s*)?)?(?:صفحة|صفحات|ص)\s*[0-9٠-٩]+(?:\s*[-–—]\s*[0-9٠-٩]+)?',
        '', value, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return cleaned.replace('  ', ' ').strip(' \n-–—')


def strip_regulation_references_from_payload(payload):
    if not isinstance(payload, dict):
        return payload
    for key, value in list(payload.items()):
        if key in REGULATION_OUTPUT_KEYS and isinstance(value, str):
            payload[key] = strip_regulation_references(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    strip_regulation_references_from_payload(item)
        elif isinstance(value, dict) and key in {'parcels', 'site_facts'}:
            strip_regulation_references_from_payload(value)
    return payload


def land_rule_text(payload, include_setbacks=False):
    if not isinstance(payload, dict):
        return ''
    labels = (
        ('نسبة البناء', payload.get('building_ratio')),
        ('نسبة التغطية', payload.get('coverage_ratio')),
        ('معامل مسطح البناء (FAR)', payload.get('floor_area_ratio')),
        ('عدد الأدوار بموجب الجدول', payload.get('table_floors')),
    )
    if include_setbacks:
        labels += (('الارتدادات', payload.get('setbacks')),)
    return '\n'.join(
        f'{label}: {str(value).strip()}'
        for label, value in labels
        if value not in (None, '') and str(value).strip()
    )


REGULATION_PDF_NAMES = ('اشتراطات1.pdf', 'اشتراطات2.pdf')
REGULATION_SNIPPET_CHARS = int(os.environ.get('REGULATION_SNIPPET_CHARS', '2600'))
REGULATION_MAX_SNIPPETS = int(os.environ.get('REGULATION_MAX_SNIPPETS', '6'))
REGULATION_MAX_TABLE_PAGES = int(os.environ.get('REGULATION_MAX_TABLE_PAGES', '6'))
REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE = int(os.environ.get('REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE', '0'))
REGULATION_EVIDENCE_TABLE_PAGES_PER_FILE = int(os.environ.get('REGULATION_EVIDENCE_TABLE_PAGES_PER_FILE', '0'))
REGULATION_EVIDENCE_MAX_CHARS_PER_FILE = int(os.environ.get('REGULATION_EVIDENCE_MAX_CHARS_PER_FILE', '0'))
REGULATION_EVIDENCE_TEXT_CHUNK_CHARS = int(os.environ.get('REGULATION_EVIDENCE_TEXT_CHUNK_CHARS', '50000'))
REGULATION_EVIDENCE_TABLE_BATCH_SIZE = int(os.environ.get(
    'REGULATION_EVIDENCE_TABLE_BATCH_SIZE',
    os.environ.get('REGULATION_EVIDENCE_TABLE_PAGES_PER_STAGE', '4')))
REGULATION_EVIDENCE_TABLE_PAGES_PER_STAGE = REGULATION_EVIDENCE_TABLE_BATCH_SIZE
REGULATION_EVIDENCE_TABLE_DPI = int(os.environ.get('REGULATION_EVIDENCE_TABLE_DPI', '180'))
LAND_FACTS_MAX_TOKENS = int(os.environ.get('LAND_FACTS_MAX_TOKENS', '2500'))
LAND_FACTS_MIN_TOKENS = int(os.environ.get('LAND_FACTS_MIN_TOKENS', '1200'))
REGULATION_EVIDENCE_MAX_TOKENS = int(os.environ.get('REGULATION_EVIDENCE_MAX_TOKENS', '4000'))
REGULATION_EVIDENCE_MIN_TOKENS = int(os.environ.get('REGULATION_EVIDENCE_MIN_TOKENS', '1500'))
# When enabled, the verified rules digest (rules/*.json) supplies regulation
# values deterministically and the per-request PDF evidence extraction is
# skipped. Set REGULATION_DIGEST=0 to restore the legacy extraction path.
REGULATION_DIGEST_ENABLED = os.environ.get('REGULATION_DIGEST', '1') != '0'

_REGULATION_PAGE_INDEX = None
_REGULATION_PAGE_INDEX_SIGNATURE = None

# Terms that mark a page as carrying the conditions we need. Arabic extracted from these PDFs
# loses the lam-alef ligature and some letters, so the roots are matched without "ال".
REGULATION_TOPIC_TERMS = (
    ('نسبة البناء', 6), ('مسطح البناء', 4), ('معامل مسطح', 4),
    ('ارتداد', 6), ('تغطية', 4), ('عدد الطوابق', 5), ('الطوابق', 3),
    ('ارتفاع', 3), ('استعمال', 2), ('استخدام', 2),
    ('مواقف', 4), ('مدخل', 3), ('مخرج', 3), ('تحميل', 3), ('خدمات', 2),
    ('محاور التجارية', 3), ('سكني', 2), ('تجاري', 2),
)

# Repeated page furniture in these documents; it wastes the snippet budget.
_REGULATION_NOISE = re.compile(
    r'(المخطط المحلي لمحافظة\s*جدة\s*1447[^\n]*|أنظمة وضوابط البناء\s*1447[^\n]*|'
    r'الالئحة التنفيذية[^\n]*|م\s*ص\s*\d+\s*من\s*\d+|\.{6,})'
)


def _clean_regulation_text(text):
    """Strip repeated headers/footers and dotted index rows from an extracted page."""
    cleaned = _REGULATION_NOISE.sub(' ', text or '')
    return re.sub(r'[ \t]*\n[ \t]*', '\n', re.sub(r'[ \t]{2,}', ' ', cleaned)).strip()


def _is_regulation_index_page(text):
    """Index / list-of-figures pages match many keywords but contain no actual rules."""
    if not text:
        return True
    if len(re.findall(r'\.{6,}', text)) >= 3:
        return True
    return len(re.findall(r'\(\s*شكل رقم\s*\d+', text)) >= 3


def _score_regulation_page(text, query_tokens):
    score = sum(weight for term, weight in REGULATION_TOPIC_TERMS if term in text)
    for token in query_tokens:
        if token and token in text:
            score += 8
    if re.search(r'\d{2}\s*%', text):
        score += 5
    return score


def regulation_pdf_paths():
    """Absolute paths of the municipality regulation PDFs that exist on disk."""
    base = os.path.dirname(__file__)
    return [os.path.join(base, name) for name in REGULATION_PDF_NAMES
            if os.path.isfile(os.path.join(base, name))]


def search_official_regulations_pdf(query_text=""):
    """Return a bounded, source-separated regulation evidence packet for older callers."""
    package, warnings = search_official_regulations_evidence(query_text, {})
    return package.get('context', ''), package.get('table_pages', []), warnings


def _regulation_index_signature(paths):
    signature = []
    for path in paths:
        try:
            stat = os.stat(path)
            signature.append((path, stat.st_mtime_ns, stat.st_size))
        except OSError:
            signature.append((path, None, None))
    return tuple(signature)


def _regulation_transcription_pages(pdf_name):
    """Page-numbered text from the manually verified transcription markdowns
    (clean_*.md). Each file names its source PDF in the first heading and marks
    pages with --- صفحة N --- matching the PDF page number. Returns {} when no
    transcription covers this file."""
    pages = {}
    base = os.path.dirname(__file__)
    for md_path in sorted(glob.glob(os.path.join(base, 'clean*.md'))):
        try:
            with open(md_path, encoding='utf-8') as handle:
                text = handle.read()
        except OSError:
            continue
        if pdf_name not in text.split('\n', 1)[0]:
            continue
        for match in re.finditer(
                r'---\s*صفحة\s*(\d+)\s*---\s*\n(.*?)(?=---\s*صفحة\s*\d+\s*---|\Z)',
                text, re.S):
            pages[int(match.group(1))] = match.group(2).strip()
    return pages


def _build_regulation_page_index():
    global _REGULATION_PAGE_INDEX, _REGULATION_PAGE_INDEX_SIGNATURE
    paths = regulation_pdf_paths()
    signature = _regulation_index_signature(paths)
    if _REGULATION_PAGE_INDEX_SIGNATURE == signature and _REGULATION_PAGE_INDEX is not None:
        return _REGULATION_PAGE_INDEX
    try:
        import fitz
    except ImportError:
        _REGULATION_PAGE_INDEX = []
        _REGULATION_PAGE_INDEX_SIGNATURE = signature
        return []

    records = []
    for path in paths:
        name = os.path.basename(path)
        # Verified transcriptions win — PyMuPDF mangles this file family's
        # Arabic extraction. The PDF still opens for the page count, gap
        # filling, and table-page rendering downstream.
        transcribed = _regulation_transcription_pages(name)
        try:
            document = fitz.open(path)
        except Exception:
            document = None
        try:
            total = len(document) if document else max(transcribed, default=0)
            for page_no in range(1, total + 1):
                text = transcribed.get(page_no)
                if text is not None:
                    if _is_regulation_index_page(text):
                        continue
                    cleaned = _clean_regulation_text(text)
                    has_table = bool(re.search(r'(?m)^\s*\|.*\|\s*$', text))
                elif document is not None:
                    page = document[page_no - 1]
                    raw = page.get_text()
                    if _is_regulation_index_page(raw):
                        continue
                    cleaned = _clean_regulation_text(raw)
                    try:
                        has_table = bool(page.find_tables().tables)
                    except Exception:
                        has_table = False
                else:
                    continue
                if not cleaned and not has_table:
                    continue
                records.append({
                    'name': name,
                    'path': path,
                    'page': page_no,
                    'text': cleaned,
                    'has_table': has_table,
                })
        finally:
            if document:
                document.close()
    _REGULATION_PAGE_INDEX = records
    _REGULATION_PAGE_INDEX_SIGNATURE = signature
    return records


def _regulation_search_tokens(query_text='', site_facts=None):
    values = [str(query_text or '')]
    if isinstance(site_facts, dict):
        values.extend(str(site_facts.get(key) or '') for key in (
            'area_sqm', 'croquis_land_area', 'zoning_code', 'land_use', 'city',
            'project_type', 'axis_type', 'building_type', 'plot_number'
        ))
    blob = ' '.join(values)
    tokens = re.findall(r'[0-9A-Za-z\u0600-\u06FF/%.-]{3,}', blob)
    return list(dict.fromkeys(token.casefold() for token in tokens))[:24]


def search_official_regulations_evidence(query_text='', site_facts=None):
    records = _build_regulation_page_index()
    if not records:
        return {'context': '', 'documents': [], 'table_pages': []}, [
            'ملفات الاشتراطات غير موجودة أو لا تحتوي صفحات قابلة للبحث: '
            + '، '.join(REGULATION_PDF_NAMES)
        ]
    query_tokens = _regulation_search_tokens(query_text, site_facts)
    warnings = []
    documents = []
    table_pages = []
    for name in REGULATION_PDF_NAMES:
        file_records = [record for record in records if record['name'] == name]
        scored = sorted(
            (
                {
                    **record,
                    'score': _score_regulation_page(record['text'], query_tokens)
                }
                for record in file_records
            ),
            key=lambda record: (-record['score'], record['page'])
        )
        matched = [record for record in scored if record['score'] > 0]
        full_document = REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE <= 0
        text_records = file_records if full_document else matched[:REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE]
        table_pool = file_records if REGULATION_EVIDENCE_TABLE_PAGES_PER_FILE <= 0 else matched
        table_records = [record for record in table_pool if record['has_table']]
        if REGULATION_EVIDENCE_TABLE_PAGES_PER_FILE > 0:
            table_records = table_records[:REGULATION_EVIDENCE_TABLE_PAGES_PER_FILE]
        if not text_records:
            warnings.append(f'لم يتم العثور على صفحات مطابقة في {name}')
        context_parts = []
        remaining = None if REGULATION_EVIDENCE_MAX_CHARS_PER_FILE <= 0 else REGULATION_EVIDENCE_MAX_CHARS_PER_FILE
        for record in text_records:
            if remaining is not None and remaining <= 0:
                break
            raw_text = record.get('text') or ''
            max_chars = len(raw_text) if remaining is None else min(REGULATION_SNIPPET_CHARS, remaining)
            snippet = raw_text[:max_chars]
            if not snippet and not record.get('has_table'):
                continue
            if not snippet:
                snippet = 'لا يوجد نص مستخرج من هذه الصفحة؛ اقرأ الجدول من الصورة المرفقة.'
            context_parts.append(
                f"--- {name} — صفحة {record['page']} — score={record.get('score', 0)} ---\n{snippet}"
            )
            if remaining is not None:
                remaining -= len(snippet)
        for record in table_records:
            table_pages.append({
                'path': record['path'],
                'name': name,
                'page': record['page'],
                'score': record.get('score', 0),
            })
        documents.append({
            'name': name,
            'context': '\n\n'.join(context_parts),
            'text_pages': [record['page'] for record in text_records],
            'table_pages': [record['page'] for record in table_records],
        })
    return {
        'context': '\n\n'.join(document['context'] for document in documents if document['context']),
        'documents': documents,
        'table_pages': table_pages,
    }, warnings


# Saudi Building Code (SBC 201-AR-2024) — a separate official corpus searched
# during plans verification. It deliberately stays out of REGULATION_PDF_NAMES
# so the zoning-extraction flow keeps its two-document municipal scope.
SBC_PDF_NAMES = ('SBC201_AR2024.pdf',)
SBC_EVIDENCE_MAX_PAGES = int(os.environ.get('SBC_EVIDENCE_MAX_PAGES', '4'))
SBC_EVIDENCE_MAX_CHARS = int(os.environ.get('SBC_EVIDENCE_MAX_CHARS', '7000'))
SBC_SNIPPET_CHARS = int(os.environ.get('SBC_SNIPPET_CHARS', '2200'))

# Roots without «ال» — the PyMuPDF scoring index swaps the lam past the next
# letter («الجدران» becomes «اجلدران»), the same mangling the municipal terms
# avoid. Some spans also arrive fully reversed, so matching checks term[::-1]
# as well. Snippets shown to the model are re-extracted cleanly via pypdf.
SBC_TOPIC_TERMS = (
    ('إشغال', 6), ('مخارج', 6), ('اخلا', 5), ('منافذ', 5),
    ('مواقف', 5), ('موقف', 3), ('مدخل', 3),
    ('ارتفاع', 4), ('طوابق', 4), ('قبو', 3), ('سطح', 2), ('ملحق', 2),
    ('إعاقة', 5), ('ذوي', 3), ('منحدر', 3),
    ('مصاعد', 3), ('سعة', 3), ('درج', 2),
    ('ممرات', 2), ('مسار', 2), ('حريق', 2), ('مقاومة', 2),
    ('سكني', 2), ('تجاري', 2), ('تصنيف', 2), ('مساحة البناء', 3),
)

_SBC_PAGE_INDEX = None
_SBC_PAGE_INDEX_SIGNATURE = None


def sbc_pdf_paths():
    """Absolute paths of the Saudi Building Code PDFs that exist on disk."""
    base = os.path.dirname(__file__)
    return [os.path.join(base, name) for name in SBC_PDF_NAMES
            if os.path.isfile(os.path.join(base, name))]


def _clean_sbc_text(text):
    """Strip the SBC running header, then reuse the shared regulation cleaner."""
    text = re.sub(r'SBC\s*201[^\n]*', ' ', text or '')
    return _clean_regulation_text(text)


def _build_sbc_page_index():
    """Page-level text index of the code PDFs. Built lazily once per process —
    the codebook is ~600 pages, so it is indexed only when verification needs it.
    Tables are not detected: verification consumes text snippets only."""
    global _SBC_PAGE_INDEX, _SBC_PAGE_INDEX_SIGNATURE
    paths = sbc_pdf_paths()
    signature = _regulation_index_signature(paths)
    if _SBC_PAGE_INDEX_SIGNATURE == signature and _SBC_PAGE_INDEX is not None:
        return _SBC_PAGE_INDEX
    try:
        import fitz
    except ImportError:
        _SBC_PAGE_INDEX = []
        _SBC_PAGE_INDEX_SIGNATURE = signature
        return []
    records = []
    for path in paths:
        name = os.path.basename(path)
        try:
            document = fitz.open(path)
        except Exception:
            continue
        try:
            for index in range(len(document)):
                cleaned = _clean_sbc_text(document[index].get_text())
                if cleaned and not _is_regulation_index_page(cleaned):
                    records.append({'name': name, 'path': path, 'page': index + 1,
                                    'text': cleaned, 'has_table': False})
        finally:
            document.close()
    _SBC_PAGE_INDEX = records
    _SBC_PAGE_INDEX_SIGNATURE = signature
    return records


def _pdf_clean_page_texts(path, page_numbers, cleaner=None):
    """Clean text for specific PDF pages via pypdf. PyMuPDF swaps adjacent
    Arabic letter pairs in these files' CFF-encoded runs («الجدران» becomes
    «اجلدران»), so the snippets handed to the model are re-extracted with
    pypdf — the PyMuPDF index stays in place for fast scoring only."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return {}
    try:
        reader = PdfReader(path)
    except Exception:
        return {}
    cleaned = {}
    try:
        for page in page_numbers:
            try:
                text = reader.pages[page - 1].extract_text() or ''
                cleaned[page] = cleaner(text) if cleaner else text
            except Exception:
                cleaned[page] = ''
    finally:
        try:
            reader.stream.close()
        except Exception:
            pass
    return cleaned


def _sbc_term_present(term, text):
    if term in text:
        return True
    # Whole-span reversal happens in some extracted runs; only reverse Arabic
    # words so digit tokens never match backwards.
    return bool(re.search(r'[\u0600-\u06FF]', term)) and term[::-1] in text


def _score_sbc_page(text, query_tokens):
    score = sum(weight for term, weight in SBC_TOPIC_TERMS
                if _sbc_term_present(term, text))
    for token in query_tokens:
        if token and _sbc_term_present(token, text):
            score += 8
    if re.search(r'\d{2}\s*%', text):
        score += 3
    if re.search(r'[0-9٠-٩]+\s*(?:م|متر)\b', text):
        score += 2
    return score


def search_sbc_evidence(query_text='', site_facts=None):
    """Bounded Saudi Building Code evidence packet for plans verification.

    Returns ({'context', 'pages', 'matched'}, warnings). Hard-bounded by
    SBC_EVIDENCE_MAX_PAGES / SBC_EVIDENCE_MAX_CHARS so the codebook can never
    flood the verification prompt.
    """
    records = _build_sbc_page_index()
    if not records:
        return {'context': '', 'pages': [], 'matched': False}, [
            'كود البناء السعودي غير متاح — لا يوجد ملف قابل للبحث: ' + '، '.join(SBC_PDF_NAMES)]
    query_tokens = _regulation_search_tokens(query_text, site_facts)
    scored = sorted(
        ({**record, 'score': _score_sbc_page(record['text'], query_tokens)} for record in records),
        key=lambda record: (-record['score'], record['page']))
    matched = [record for record in scored if record['score'] > 0][:SBC_EVIDENCE_MAX_PAGES]
    if not matched:
        return {'context': '', 'pages': [], 'matched': False}, [
            'لم يتم العثور على نصوص مطابقة في كود البناء السعودي']
    clean_pages = {}
    for path in {record['path'] for record in matched}:
        wanted = [record['page'] for record in matched if record['path'] == path]
        clean_pages.update(_pdf_clean_page_texts(path, wanted, _clean_sbc_text))
    parts = []
    pages = []
    remaining = SBC_EVIDENCE_MAX_CHARS
    for record in matched:
        if remaining <= 0:
            break
        snippet = (clean_pages.get(record['page']) or record['text'])[
            :min(SBC_SNIPPET_CHARS, remaining)]
        if not snippet:
            continue
        pages.append(record['page'])
        parts.append(f"--- مقتطف من كود البناء السعودي ---\n{snippet}")
        remaining -= len(snippet)
    return {'context': '\n\n'.join(parts), 'pages': pages, 'matched': bool(parts)}, []


def split_regulation_context(context, max_chars=None):
    text = str(context or '').strip()
    limit = max_chars if max_chars is not None else REGULATION_EVIDENCE_TEXT_CHUNK_CHARS
    limit = max(1000, int(limit))
    if not text:
        return []
    units = [unit.strip() for unit in re.split(
        r'(?=---\s+[^\n]+—\s*صفحة\s+[0-9٠-٩]+\s+—)', text) if unit.strip()]
    if not units:
        units = [text]
    chunks = []
    current = ''
    for unit in units:
        if len(unit) > limit:
            if current:
                chunks.append(current)
                current = ''
            for start in range(0, len(unit), limit):
                chunks.append(unit[start:start + limit])
            continue
        candidate = unit if not current else current + '\n\n' + unit
        if current and len(candidate) > limit:
            chunks.append(current)
            current = unit
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def regulation_context_page_numbers(context):
    return {
        int(value.translate(_ARABIC_INDIC_DIGITS))
        for value in re.findall(r'---\s+[^\n]+—\s*صفحة\s+([0-9٠-٩]+)\s+—', str(context or ''))
    }


def split_regulation_table_batches(table_pages, batch_size=None):
    rows = list(table_pages or [])
    limit = int(batch_size if batch_size is not None else REGULATION_EVIDENCE_TABLE_PAGES_PER_STAGE)
    if limit <= 0:
        return [rows] if rows else []
    return [rows[start:start + limit] for start in range(0, len(rows), limit)]


def _extract_full_regulation_evidence(source, site_facts, usage_ctx=None):
    source_name = source.get('name') or 'ملف اشتراطات'
    context = str(source.get('context') or '')
    table_pages = source.get('table_pages') if isinstance(source.get('table_pages'), list) else []
    chunks = split_regulation_context(context)
    if not chunks and table_pages:
        chunks = ['']
    evidence = []
    uncertainties = []
    warnings = []
    base_prompt = (
        "أنت مستخرج أدلة تنظيمية من ملف واحد كامل فقط. أعد JSON فقط بهذا الشكل: "
        '{"evidence":[{"field":"","value":"","page":0,"quote":""}],'
        '"uncertainties":[]} '
        f"المصدر الوحيد هو {source_name}. لا تستخدم أي معلومة من ملف آخر. "
        "اقرأ الجزء الحالي من المحتوى الكامل وصور الجداول المرفقة، واستخرج القواعد التي تنطبق على حقائق الموقع. "
        "يمكن حفظ رقم الصفحة داخليًا داخل evidence فقط لتتبع الدليل، ولا تضعه في أي قيمة اشتراط أو نص موجّه للمستخدم. "
        "أرقام الجداول تُقرأ من الصور المرفقة لأن النص قد يكون معكوسًا."
    )

    def run_stage(stage_name, context_chunk, table_batch, stage_note):
        nonlocal evidence, uncertainties
        parts, render_warnings = render_regulation_table_pages(
            table_batch, dpi=REGULATION_EVIDENCE_TABLE_DPI)
        warnings.extend(render_warnings)
        user_content = [{
            'type': 'text',
            'text': base_prompt + stage_note
                    + '\nحقائق الموقع المستخرجة من الكروكي:\n'
                    + json.dumps(site_facts, ensure_ascii=False)
                    + '\nجزء المحتوى الحالي:\n' + context_chunk
        }] + parts
        result, _cap, error = _run_land_json_stage(
            stage_name, base_prompt, user_content,
            REGULATION_EVIDENCE_MAX_TOKENS, REGULATION_EVIDENCE_MIN_TOKENS,
            REGULATION_EVIDENCE_MAX_TOKENS * 2,
            usage_ctx=usage_ctx,
        )
        if error:
            warnings.append(f'تعذر استخراج جزء من أدلة {source_name}: {error}')
            return
        values = result.get('evidence') if isinstance(result, dict) else []
        if isinstance(values, list):
            evidence.extend(item for item in values if isinstance(item, dict))
        uncertainty_values = result.get('uncertainties') if isinstance(result, dict) else []
        if isinstance(uncertainty_values, list):
            uncertainties.extend(uncertainty_values)

    has_page_metadata = any(regulation_context_page_numbers(chunk) for chunk in chunks)
    if not has_page_metadata:
        if context.strip():
            for chunk_index, context_chunk in enumerate(chunks):
                run_stage(
                    f'{source_name}-text-{chunk_index + 1}', context_chunk, [],
                    f'\nهذا الجزء {chunk_index + 1} من {len(chunks)} من المحتوى الكامل للملف.')
        table_batch_size = REGULATION_EVIDENCE_TABLE_BATCH_SIZE
        if table_batch_size > 0:
            table_batches = [
                table_pages[start:start + table_batch_size]
                for start in range(0, len(table_pages), table_batch_size)
            ]
        else:
            table_batches = [table_pages]
        for batch_index, table_batch in enumerate(table_batches):
            run_stage(
                f'{source_name}-tables-{batch_index + 1}', '', table_batch,
                '\nهذه دفعة جداول من المحتوى الكامل للملف.')
        return {'evidence': evidence, 'uncertainties': uncertainties, 'warnings': warnings}

    for chunk_index, context_chunk in enumerate(chunks):
        chunk_pages = regulation_context_page_numbers(context_chunk)
        chunk_tables = [
            entry for entry in table_pages
            if not chunk_pages or entry.get('page') in chunk_pages
        ]
        table_batch_size = REGULATION_EVIDENCE_TABLE_BATCH_SIZE
        if table_batch_size > 0:
            table_batches = [
                chunk_tables[start:start + table_batch_size]
                for start in range(0, len(chunk_tables), table_batch_size)
            ]
        else:
            table_batches = [chunk_tables]
        if not table_batches:
            table_batches = [[]]
        for batch_index, table_batch in enumerate(table_batches):
            context_for_stage = context_chunk if batch_index == 0 else ''
            stage_note = f'\nهذا الجزء {chunk_index + 1} من {len(chunks)} من المحتوى الكامل للملف.'
            if batch_index:
                stage_note += '\nهذه دفعة جداول إضافية للجزء نفسه؛ استخرج منها ما لم يظهر في الدفعة السابقة.'
            run_stage(
                f'{source_name}-part-{chunk_index + 1}-tables-{batch_index + 1}',
                context_for_stage, table_batch, stage_note)
    return {'evidence': evidence, 'uncertainties': uncertainties, 'warnings': warnings}


def render_regulation_table_pages(table_pages, dpi=200):
    """Render the ranked regulation table pages to images for the vision model."""
    if not table_pages:
        return [], []
    try:
        import fitz
    except ImportError:
        return [], ['PyMuPDF غير متاح؛ تعذر تصوير جداول الاشتراطات']

    parts, warnings = [], []
    scale = max(1.0, float(dpi) / 72.0)
    matrix = fitz.Matrix(scale, scale)
    by_path = {}
    for entry in table_pages:
        by_path.setdefault(entry['path'], []).append(entry)
    for path, entries in by_path.items():
        try:
            document = fitz.open(path)
        except Exception as error:
            warnings.append(f"تعذر تصوير جداول {entries[0]['name']}: {error}")
            continue
        try:
            for entry in entries:
                index = entry['page'] - 1
                if index < 0 or index >= len(document):
                    continue
                pixmap = document[index].get_pixmap(matrix=matrix, alpha=False)
                encoded = base64.b64encode(pixmap.tobytes('png')).decode('ascii')
                parts.append({
                    'type': 'text',
                    'text': (f"جدول تنظيم من لائحة الأمانة: {entry['name']} — صفحة {entry['page']}. "
                             "اقرأ الأرقام من الصورة؛ نص هذا الجدول يُستخرج بترتيب معكوس فلا تعتمد عليه.")
                })
                parts.append({
                    'type': 'image_url',
                    'image_url': {'url': f'data:image/png;base64,{encoded}', 'detail': 'high'}
                })
        finally:
            document.close()
    return parts, warnings

PDF_VISION_DPI = int(os.environ.get('PDF_VISION_DPI', '300'))
PDF_VISION_MAX_PAGES = int(os.environ.get('PDF_VISION_MAX_PAGES', '40'))
PDF_VISION_MAX_EDGE = int(os.environ.get('PDF_VISION_MAX_EDGE', '3000'))
PDF_VISION_JPEG_QUALITY = int(os.environ.get('PDF_VISION_JPEG_QUALITY', '85'))
PDF_VISION_MAX_TOTAL_BYTES = int(os.environ.get('PDF_VISION_MAX_TOTAL_BYTES', str(12 * 1024 * 1024)))
PDF_VISION_TILE_COLUMNS = int(os.environ.get('PDF_VISION_TILE_COLUMNS', '2'))
PDF_VISION_TILE_ROWS = int(os.environ.get('PDF_VISION_TILE_ROWS', '3'))
PDF_VISION_TILE_MAX_PAGES = int(os.environ.get('PDF_VISION_TILE_MAX_PAGES', '6'))
PDF_VISION_TILE_MAX_EDGE = int(os.environ.get('PDF_VISION_TILE_MAX_EDGE', '2600'))
PDF_VISION_TILE_DPI = int(os.environ.get('PDF_VISION_TILE_DPI', '600'))
PDF_VISION_TILE_JPEG_QUALITY = int(os.environ.get('PDF_VISION_TILE_JPEG_QUALITY', '72'))
PDF_VISION_TILE_OVERLAP = float(os.environ.get('PDF_VISION_TILE_OVERLAP', '0.04'))
PDF_VISION_ALTERNATE_TILE_LIMIT = int(os.environ.get('PDF_VISION_ALTERNATE_TILE_LIMIT', '2'))
PDF_VISION_ROTATION_MIN_SCORE_GAP = float(os.environ.get('PDF_VISION_ROTATION_MIN_SCORE_GAP', '0.004'))
PDF_VISION_ROTATION_DIRECTION_MIN_SCORE_GAP = float(os.environ.get('PDF_VISION_ROTATION_DIRECTION_MIN_SCORE_GAP', '0.003'))
# The land prompt asks for a multi-paragraph Arabic narrative, sourced building rules and a full
# coordinates table. Arabic costs roughly 2-3 tokens per word, so a low cap truncates the JSON and
# the whole extraction is then rejected, which looks to the user like "nothing changed".
# The ceiling cannot simply be raised either: OpenRouter *reserves* max_tokens against the account
# balance, so an over-large cap is refused with 402 even when the real answer would be short.
# _call_land_analysis_model() walks the cap back down when that happens.
LAND_ANALYSIS_MAX_TOKENS = int(os.environ.get('LAND_ANALYSIS_MAX_TOKENS', '16000'))
LAND_ANALYSIS_MIN_TOKENS = int(os.environ.get('LAND_ANALYSIS_MIN_TOKENS', '6000'))
LAND_ANALYSIS_TRUNCATION_CEILING = int(os.environ.get('LAND_ANALYSIS_TRUNCATION_CEILING', '20000'))
# Gemini 3.6 Flash accepts text, images, and files and is the primary model
# for all text/analysis workflows, including land and croquis extraction.
LAND_ANALYSIS_MODEL = GEMINI_TEXT_MODEL

_AFFORDABLE_TOKENS_RE = re.compile(r'can only afford\s+(\d+)')
_TRANSIENT_PROVIDER_RE = re.compile(r'\(HTTP 5\d\d\)')
_EMPTY_PROVIDER_RE = re.compile(r'جسم فارغ \(HTTP \d+\)')
_JSON_MODE_BLOCK_RE = re.compile(
    r'output_format|content filtering|response_format|structured.?output',
    re.IGNORECASE,
)
LAND_ANALYSIS_PROVIDER = {'order': ['Google'], 'allow_fallbacks': False}


def _chat_error_message(res):
    """Human-readable provider error, so a failure is never reported as a mystery."""
    if not isinstance(res, dict):
        return str(res)[:400]
    error = res.get('error')
    if isinstance(error, dict):
        return str(error.get('message') or error)[:400]
    if error:
        return str(error)[:400]
    # Choice-level failures (e.g. MALFORMED_FUNCTION_CALL) carry no top-level
    # error — surface the finish reason instead of the misleading fallback.
    for choice in (res.get('choices') or []):
        finish = (choice or {}).get('native_finish_reason') or (choice or {}).get('finish_reason') or ''
        if str(finish).lower() not in ('', 'stop', 'end_turn', 'length'):
            return f'provider finished with {finish}'
    return 'unparseable provider response' if res.get('choices') else 'no provider response'
