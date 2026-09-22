
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Call Image API (OpenRouter - Gemini)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _image_response_url(data):
    def candidate(value):
        if isinstance(value, str):
            value = value.strip()
            return value if value.startswith('data:image/') or value.startswith('http') else None
        if not isinstance(value, dict):
            return None
        encoded = value.get('b64_json') or value.get('base64')
        if encoded:
            media_type = value.get('media_type') or value.get('mime_type')
            if isinstance(media_type, str) and media_type.startswith('image/'):
                return 'data:' + media_type + ';base64,' + str(encoded)
            return 'data:image/png;base64,' + str(encoded)
        for key in ('image_url', 'image', 'url', 'data_uri'):
            nested = value.get(key)
            if isinstance(nested, dict):
                nested = nested.get('url') or nested.get('data_uri')
            result = candidate(nested)
            if result:
                return result
        return None

    if not isinstance(data, dict):
        return None
    for choice in data.get('choices') or []:
        message = choice.get('message') if isinstance(choice, dict) else None
        if not isinstance(message, dict):
            continue
        for key in ('images', 'content'):
            value = message.get(key)
            values = value if isinstance(value, list) else [value]
            for item in values:
                result = candidate(item)
                if result:
                    return result
    for item in data.get('data') or []:
        result = candidate(item)
        if result:
            return result
    return None


def call_image_api(prompt, usage_ctx=None):
    return call_images_api(prompt, usage_ctx=usage_ctx)

def _map_image_owned_by_tenant(image_path, tenant_id):
    """ISS-020: map files share one folder — ownership is proven by a
    ``map_images`` row of this tenant pointing at the same real path."""
    try:
        real = os.path.realpath(image_path)
        for row in db.get_map_images(tenant_id) or []:
            stored = row.get('file_path')
            if stored and os.path.realpath(stored) == real:
                return True
    except Exception:
        return False
    return False


def _uploads_reference_owned_by_tenant(relative_path, image_path, tenant_id):
    """ISS-020: an ``uploads/`` path is only a valid reference when it resolves
    inside the caller's own tenant namespace.

    Layout: ``uploads/creative/<tenant>/`` for generated images,
    ``uploads/<tenant>/`` for documents/fonts, ``uploads/training/<tenant>/``
    for attachments, and ``uploads/maps/`` which is shared on disk so ownership
    comes from the ``map_images`` ledger instead.
    """
    tenant = re.sub(r'[^A-Za-z0-9_-]', '', str(tenant_id or ''))
    if not tenant:
        return False
    parts = [part for part in relative_path.split('/') if part]
    if len(parts) < 2:
        return False
    namespace = parts[1]
    if namespace.startswith('.'):
        return False
    if namespace in ('creative', 'training'):
        return len(parts) > 2 and parts[2] == tenant
    if namespace == 'maps':
        return _map_image_owned_by_tenant(image_path, tenant_id)
    return namespace == tenant


def _prepare_image_reference_for_model(reference, tenant_id=None):
    """Normalize a caller-supplied image reference into a model-readable form.

    ISS-020: the reference must be provably the caller's own — a ``data:`` URI
    (already client-side bytes) or a local ``uploads/`` path inside the
    tenant's namespace. Remote URLs are refused outright: the model only needs
    images this app stored, and an unverifiable remote fetch is an SSRF hole.
    ``tenant_id`` is an explicit parameter because generation runs in worker
    threads where ``g`` does not exist.
    """
    if not isinstance(reference, str) or not reference.strip():
        return None
    reference = reference.strip()
    if reference.startswith('data:image/'):
        return reference
    if re.match(r'^https?://', reference, re.IGNORECASE):
        print(f'[IMAGE ERROR] Remote reference images are not allowed: {reference[:120]}')
        return None
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None

    relative_path = reference.split('?', 1)[0].lstrip('/')
    if not relative_path.startswith('uploads/'):
        print(f'[IMAGE ERROR] Unsupported local reference path: {reference}')
        return None

    uploads_root = os.path.abspath(UPLOADS_DIR)
    image_path = os.path.abspath(
        os.path.join(uploads_root, relative_path[len('uploads/'):].replace('/', os.sep)))
    try:
        if os.path.commonpath([uploads_root, image_path]) != uploads_root:
            return None
    except ValueError:
        return None
    if not os.path.isfile(image_path) or os.path.getsize(image_path) > 15 * 1024 * 1024:
        print(f'[IMAGE ERROR] Local reference image is unavailable: {reference}')
        return None
    if not _uploads_reference_owned_by_tenant(relative_path, image_path, tenant_id):
        print(f'[IMAGE ERROR] Reference image is not owned by this tenant: {reference[:120]}')
        return None

    mime_type = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.webp': 'image/webp',
    }.get(os.path.splitext(image_path)[1].lower())
    if not mime_type:
        print(f'[IMAGE ERROR] Unsupported local reference format: {reference}')
        return None
    try:
        with open(image_path, 'rb') as image_file:
            encoded = base64.b64encode(image_file.read()).decode('ascii')
        return f'data:{mime_type};base64,{encoded}'
    except OSError as error:
        print(f'[IMAGE ERROR] Could not read local reference image: {error}')
        return None


def call_image_api_with_reference(reference_image_base64, prompt, usage_ctx=None):
    return call_images_api(prompt, references=[reference_image_base64], usage_ctx=usage_ctx)


def persist_generated_image(image, tenant_id):
    """Store generated data-URI images on disk and return a compact public URL."""
    if not isinstance(image, str) or not image.startswith('data:image/') or ';base64,' not in image:
        return image
    header, encoded = image.split(',', 1)
    mime = header[5:].split(';', 1)[0].lower()
    extension = {
        'image/png': '.png',
        'image/jpeg': '.jpg',
        'image/jpg': '.jpg',
        'image/webp': '.webp',
    }.get(mime)
    if not extension or not re.fullmatch(r'\.(png|jpg|webp)', extension):
        return image
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        return image
    digest = hashlib.sha256(raw).hexdigest()[:24]
    safe_tenant = re.sub(r'[^A-Za-z0-9_-]', '', str(tenant_id or 'public')) or 'public'
    image_dir = os.path.join(UPLOADS_DIR, 'creative', safe_tenant)
    os.makedirs(image_dir, exist_ok=True)
    filename = digest + extension
    path = os.path.join(image_dir, filename)
    if not os.path.exists(path):
        with open(path, 'wb') as image_file:
            image_file.write(raw)
    return f'/uploads/creative/{safe_tenant}/{filename}'


VISUAL_CONCEPT_MAX_REFERENCE_IMAGES = 5
VISUAL_CONCEPT_MAX_INTERIOR_IMAGES = 4
VISUAL_CONCEPT_SLOTS = ('cover', 'right', 'left', 'top', 'back', 'interior')
VISUAL_CONCEPT_EXTERNAL_SLOTS = ('cover', 'right', 'left', 'top', 'back')
VISUAL_CONCEPT_MOODBOARD_SLOTS = ('right', 'left', 'top', 'back')
VISUAL_CONCEPT_INTERNAL_PREFIX = 'interior'
VISUAL_CONCEPT_PLAN_PREFIX = 'plan'
VISUAL_CONCEPT_PLAN_DEFINITIONS = (
    {'kind': 'site', 'id': 'plan_site', 'label': 'الموقع العام المبسط'},
    {'kind': 'uses', 'id': 'plan_uses', 'label': 'توزيع الاستخدامات على الأدوار'},
    {'kind': 'massing', 'id': 'plan_massing', 'label': 'المنظور الكتلي ثلاثي الأبعاد'},
)
VISUAL_CONCEPT_PLAN_KIND_BY_ID = {item['id']: item['kind'] for item in VISUAL_CONCEPT_PLAN_DEFINITIONS}
VISUAL_CONCEPT_PLAN_LABEL_BY_ID = {item['id']: item['label'] for item in VISUAL_CONCEPT_PLAN_DEFINITIONS}
VISUAL_CONCEPT_PLAN_COLORS = (
    ('Residential', 'soft blue'),
    ('Hotel', 'soft yellow'),
    ('Retail & F&B', 'soft teal'),
    ('Amenities', 'soft pink'),
    ('Parking/Service', 'light grey'),
    ('Landscape/Open space', 'pale green'),
    ('Sea', 'pale cyan'),
)
VISUAL_CONCEPT_SLOT_LABELS = {
    'cover': 'الصورة الرئيسية',
    'right': 'يمين',
    'left': 'شمال',
    'top': 'فوق',
    'back': 'خلف',
    'interior': 'التصميم الداخلي',
}
VISUAL_CONCEPT_REQUIRED_FIELDS = (
    ('project_name', 'اسم المشروع'),
    ('project_idea', 'فكرة المشروع'),
    ('land_and_building_summary', 'وصف المشروع والأرض'),
    ('target_audience', 'الفئات المستهدفة'),
    ('approved_financial_area', 'المساحة المعتمدة للدراسة المالية'),
    ('approved_floor_count', 'عدد الأدوار المعتمدة'),
    ('approved_coverage_ratio', 'نسبة التغطية المعتمدة'),
    ('facades', 'عدد الواجهات على الشارع واتجاهاتها'),
    ('allowed_uses', 'الاستخدامات المسموحة'),
    ('directions_table', 'جدول الاتجاهات'),
    ('overview_map', 'خريطة الأرض / المبنى'),
)


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
    financial = source.get('financial_study_model') if isinstance(source.get('financial_study_model'), dict) else {}
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


def _visual_concept_style_reference_ids(project_data):
    source = project_data if isinstance(project_data, dict) else {}
    visual = source.get('visual_concept')
    if isinstance(visual, str):
        visual = _visual_concept_parse_json(visual, {})
    visual = visual if isinstance(visual, dict) else {}
    candidates = []
    for key in ('styleReferenceFileIds', 'style_reference_file_ids'):
        candidates.extend(_visual_concept_list(visual.get(key)))
    candidates.extend(_visual_concept_list(visual.get('styleReferenceFileId') or visual.get('style_reference_file_id')))
    for key in ('visual_style_reference_file_ids',):
        candidates.extend(_visual_concept_list(source.get(key)))
    candidates.extend(_visual_concept_list(source.get('visual_style_reference_file_id')))
    unique = []
    for file_id in candidates:
        if file_id not in unique:
            unique.append(file_id)
        if len(unique) >= VISUAL_CONCEPT_MAX_REFERENCE_IMAGES:
            break
    return unique


def _visual_concept_style_reference_id(project_data):
    return next(iter(_visual_concept_style_reference_ids(project_data)), '')


def _visual_concept_overview_map_url(project_data):
    source = project_data if isinstance(project_data, dict) else {}
    creative = source.get('tenantCreativeImages') if isinstance(source.get('tenantCreativeImages'), dict) else {}
    placeholders = creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {}
    if not placeholders and isinstance(source.get('map_placeholders'), dict):
        placeholders = source.get('map_placeholders')
    for key in ('##MAP_OVERVIEW##', '##MAP_OVERVIEW_SATELLITE##', '##MAP_OVERVIEW_ROADMAP##'):
        url = placeholders.get(key)
        if isinstance(url, str) and url.strip():
            return url.strip()
    return ''


def _resolve_project_file_storage_path(stored, tenant_id=None):
    """Resolve and validate a project file's physical path within the tenant root.

    Handles absolute paths from migrated databases where the host prefix changed
    (e.g. from /home/demos/... to /home/landloom/...).
    """
    if not stored or not stored.get('storage_path'):
        return None
    tenant = str(tenant_id or stored.get('tenant_id') or getattr(g, 'tenant_id', '') or '')
    if not tenant:
        return None
    tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, tenant))
    raw_path = str(stored.get('storage_path') or '').replace('\\', '/')
    candidate = os.path.realpath(stored['storage_path'])
    try:
        if os.path.commonpath([tenant_root, candidate]) == tenant_root and os.path.isfile(candidate):
            return candidate
    except ValueError:
        pass
    # If migrated from another host, re-root relative to tenant_root
    if f'/{tenant}/' in raw_path:
        subpath = raw_path.split(f'/{tenant}/', 1)[1]
        re_rooted = os.path.realpath(os.path.join(tenant_root, subpath.replace('/', os.sep)))
        try:
            if os.path.commonpath([tenant_root, re_rooted]) == tenant_root and os.path.isfile(re_rooted):
                return re_rooted
        except ValueError:
            pass
    elif '/project-documents/' in raw_path:
        filename = os.path.basename(raw_path)
        re_rooted = os.path.realpath(os.path.join(tenant_root, 'project-documents', filename))
        try:
            if os.path.commonpath([tenant_root, re_rooted]) == tenant_root and os.path.isfile(re_rooted):
                return re_rooted
        except ValueError:
            pass
    return None


def _visual_concept_project_file_data_uri(file_id, tenant_id=None):
    tenant_id = tenant_id or getattr(g, 'tenant_id', None)
    if not tenant_id or not file_id:
        return None
    stored = db.get_project_file(tenant_id, str(file_id))
    if not stored or not stored.get('storage_path'):
        return None
    mime_type = stored.get('mime_type') or ''
    if not mime_type.startswith('image/'):
        return None
    storage_path = _resolve_project_file_storage_path(stored, tenant_id)
    if not storage_path or not os.path.isfile(storage_path) or os.path.getsize(storage_path) > 15 * 1024 * 1024:
        return None
    try:
        with open(storage_path, 'rb') as image_file:
            encoded = base64.b64encode(image_file.read()).decode('ascii')
    except OSError:
        return None
    return f'data:{mime_type};base64,{encoded}'


def _publish_project_file_as_creative_image(file_id, tenant_id=None):
    """Copy an uploaded image into the tenant's creative folder and return its public URL.

    An uploaded slot image used to be shown from a ``blob:`` URL, which exists only inside
    the tab that created it. That URL was saved into the draft, so after a reload every
    client-uploaded image rendered broken and every export shipped a dead reference.
    """
    tenant_id = tenant_id or getattr(g, 'tenant_id', None)
    data_uri = _visual_concept_project_file_data_uri(file_id, tenant_id)
    if not data_uri:
        return None
    url = persist_generated_image(data_uri, tenant_id)
    return url if isinstance(url, str) and url.startswith('/uploads/') else None


def _visual_concept_reference_uris(urls=None, file_ids=None, max_images=None, urls_first=False,
                                   tenant_id=None):
    tenant_id = tenant_id or getattr(g, 'tenant_id', None)
    limit = VISUAL_CONCEPT_MAX_REFERENCE_IMAGES if max_images is None else max(1, int(max_images))
    prepared_files = []
    for file_id in file_ids or []:
        prepared = _visual_concept_project_file_data_uri(file_id, tenant_id)
        if prepared:
            prepared_files.append(prepared)
    prepared_urls = []
    for url in urls or []:
        prepared = _prepare_image_reference_for_model(url, tenant_id)
        if prepared:
            prepared_urls.append(prepared)
    references = (prepared_urls + prepared_files) if urls_first else (prepared_files + prepared_urls)
    unique = []
    seen = set()
    for item in references:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _visual_concept_facts(project_data):
    source = project_data if isinstance(project_data, dict) else {}
    directions = _visual_concept_directions(source)
    components = _visual_concept_components(source)
    style_reference_ids = _visual_concept_style_reference_ids(source)
    style_reference_id = style_reference_ids[0] if style_reference_ids else ''
    map_url = _visual_concept_overview_map_url(source)
    facades_count = _visual_concept_text(_visual_concept_read(source, 'facades_count'), 40)
    facades_directions = _visual_concept_text(_visual_concept_read(source, 'facades_directions'), 240)
    facts = {
        'project_name': _visual_concept_text(_visual_concept_read(source, 'project_name', 'projectName'), 200),
        'project_idea': _visual_concept_text(_visual_concept_read(source, 'project_idea'), 4000),
        'land_and_building_summary': _visual_concept_text(
            _visual_concept_read(source, 'land_and_building_summary', 'project_description', 'description'), 8000),
        'target_audience': _visual_concept_text(_visual_concept_read(source, 'target_audience'), 2000),
        'approved_financial_area': _visual_concept_text(_visual_concept_read(source, 'approved_financial_area'), 80),
        'approved_floor_count': _visual_concept_text(_visual_concept_read(source, 'approved_floor_count'), 40),
        'approved_coverage_ratio': _visual_concept_text(_visual_concept_read(source, 'approved_coverage_ratio'), 40),
        'facades_count': facades_count,
        'facades_directions': facades_directions,
        'allowed_uses': _visual_concept_text(_visual_concept_read(source, 'allowed_uses'), 4000),
        'city': _visual_concept_text(_visual_concept_read(source, 'city'), 80),
        'district': _visual_concept_text(_visual_concept_read(source, 'district'), 80),
        'directions': directions,
        'components': components,
        'style_reference_file_id': style_reference_id,
        'style_reference_file_ids': style_reference_ids,
        'overview_map_url': map_url,
    }
    return facts


def _visual_concept_missing_fields(facts, slot_id='cover'):
    missing = []
    if _visual_concept_is_plan_slot(slot_id):
        if not facts.get('project_name'):
            missing.append({'key': 'project_name', 'label': 'اسم المشروع'})
        if not facts.get('components') and not facts.get('approved_plan_context'):
            missing.append({'key': 'project_components_data', 'label': 'مكونات المشروع في الدراسة المالية'})
        return missing
    if not facts.get('project_name'):
        missing.append({'key': 'project_name', 'label': 'اسم المشروع'})
    if not facts.get('project_idea'):
        missing.append({'key': 'project_idea', 'label': 'فكرة المشروع'})
    if not facts.get('land_and_building_summary'):
        missing.append({'key': 'land_and_building_summary', 'label': 'وصف المشروع والأرض'})
    if not facts.get('target_audience'):
        missing.append({'key': 'target_audience', 'label': 'الفئات المستهدفة'})
    if _visual_concept_number(facts.get('approved_financial_area')) in (None, 0):
        missing.append({'key': 'approved_financial_area', 'label': 'المساحة المعتمدة للدراسة المالية'})
    if _visual_concept_number(facts.get('approved_floor_count')) in (None, 0):
        missing.append({'key': 'approved_floor_count', 'label': 'عدد الأدوار المعتمدة'})
    if _visual_concept_number(facts.get('approved_coverage_ratio')) in (None, 0):
        missing.append({'key': 'approved_coverage_ratio', 'label': 'نسبة التغطية المعتمدة'})
    if not facts.get('facades_count') or not facts.get('facades_directions'):
        missing.append({'key': 'facades', 'label': 'عدد الواجهات على الشارع واتجاهاتها'})
    if not facts.get('allowed_uses'):
        missing.append({'key': 'allowed_uses', 'label': 'الاستخدامات المسموحة'})
    if not facts.get('directions'):
        missing.append({'key': 'directions_table', 'label': 'جدول الاتجاهات'})
    if not facts.get('overview_map_url'):
        missing.append({'key': 'overview_map', 'label': 'خريطة الأرض / المبنى'})
    if slot_id == 'interior' or str(slot_id or '').startswith(VISUAL_CONCEPT_INTERNAL_PREFIX + '_'):
        if not facts.get('components'):
            missing.append({'key': 'project_components_data', 'label': 'مكونات المشروع في الدراسة المالية'})
    return missing


def _visual_concept_is_internal_slot(slot_id):
    value = str(slot_id or '')
    return value == VISUAL_CONCEPT_INTERNAL_PREFIX or value.startswith(VISUAL_CONCEPT_INTERNAL_PREFIX + '_')


def _visual_concept_is_plan_slot(slot_id):
    return str(slot_id or '').startswith(VISUAL_CONCEPT_PLAN_PREFIX + '_')


def _visual_concept_interior_component_id(slot_id):
    value = str(slot_id or '')
    prefix = VISUAL_CONCEPT_INTERNAL_PREFIX + '_'
    if not value.startswith(prefix):
        return ''
    rest = value[len(prefix):].strip()
    if '::' in rest:
        rest = rest.rsplit('::', 1)[0]
    return rest


def _visual_concept_normalize_slot(slot_id):
    value = str(slot_id or 'cover').strip()
    folded = value.lower()
    if folded in VISUAL_CONCEPT_SLOTS:
        return folded
    if folded.startswith(VISUAL_CONCEPT_INTERNAL_PREFIX + '_'):
        suffix = value.split('_', 1)[1].strip()
        return f'{VISUAL_CONCEPT_INTERNAL_PREFIX}_{suffix}' if suffix else None
    if folded.startswith(VISUAL_CONCEPT_PLAN_PREFIX + '_'):
        suffix = value.split('_', 1)[1].strip()
        return f'{VISUAL_CONCEPT_PLAN_PREFIX}_{suffix}' if suffix else None
    aliases = {
        'main': 'cover', 'cover_image': 'cover', 'hero': 'cover',
        'east': 'right', 'east_facade': 'right', 'يمين': 'right',
        'west': 'left', 'west_facade': 'left', 'شمال': 'left',
        'aerial': 'top', 'above': 'top', 'فوق': 'top',
        'rear': 'back', 'behind': 'back', 'خلف': 'back',
        'inside': 'interior', 'internal': 'interior',
    }
    return aliases.get(folded)


def _visual_concept_slot_label(slot_id, facts=None):
    custom = ''
    if isinstance(facts, dict):
        custom = _visual_concept_text(facts.get('slot_label'), 80)
    return custom or VISUAL_CONCEPT_SLOT_LABELS.get(
        slot_id, VISUAL_CONCEPT_PLAN_LABEL_BY_ID.get(slot_id, 'مخطط')
        if _visual_concept_is_plan_slot(slot_id) else 'تصور داخلي للمكون')


def _visual_concept_slot_instruction(slot_id, facts):
    name = facts.get('project_name') or 'the project'
    if slot_id == 'cover':
        style_note = (
            'If a style-reference building image is attached, follow its architectural signature, materials, and design language. '
            if facts.get('style_reference_file_ids') else
            'No style-reference image was supplied; invent the architecture from the project facts only. '
        )
        plan_note = (
            'The attached planning diagrams (site plan, vertical program, conceptual massing) are the '
            'approved design: the building massing, heights, use bands, footprints, and entries in the '
            'render must match them exactly. '
            if facts.get('plan_image_urls') else ''
        )
        return (
            f'Create the primary architectural hero photograph of {name}. '
            + plan_note +
            'Use the attached site/map image as the actual ground and plot background when it is included. Place the building on that plot. '
            + style_note +
            'The composition is a cinematic exterior establishing shot, 16:9.'
        )
    if slot_id in VISUAL_CONCEPT_MOODBOARD_SLOTS:
        view_name = _visual_concept_slot_label(slot_id, facts)
        return (
            f'Render the "{view_name}" view of the exact same building shown in the attached hero image of {name}. '
            + ('The attached approved planning diagrams define its massing, heights, and use bands — keep the '
               'architecture, materials, height, and massing identical to both. '
               if facts.get('plan_image_urls') else
               'Keep the architecture, materials, height, and massing unchanged. ')
            + 'Follow the named viewpoint.'
        )
    if _visual_concept_is_internal_slot(slot_id):
        selected = facts.get('selected_component') if isinstance(facts.get('selected_component'), dict) else {}
        component_name = selected.get('name') or 'the selected project component'
        use_type = selected.get('useType') or ''
        units = selected.get('units')
        area = selected.get('builtArea') or selected.get('unitArea')
        details = []
        if use_type:
            details.append(f'use type {use_type}')
        if units not in (None, ''):
            details.append(f'{units} units')
        if area not in (None, ''):
            details.append(f'area {area}')
        detail_text = ', '.join(details)
        return (
            f'Render one photorealistic INTERIOR of {name} for the actual project component named {component_name}. '
            f'This interior must belong to the same building shown in the attached approved hero image. '
            f'Use only this component: {component_name}'
            + (f' ({detail_text})' if detail_text else '')
            + '. Do not invent another program, mix other components, or change the exterior architecture. '
            'If component-specific interior references are attached, follow their materials and atmosphere. '
            'Composition is 16:9, no people, no text, no logos.'
        )
    if _visual_concept_is_plan_slot(slot_id):
        plan_title = _visual_concept_slot_label(slot_id, facts)
        description = str(facts.get('plan_description') or '').strip()
        kind = _visual_concept_plan_kind(slot_id, facts.get('plan_kind'))
        approved_context = str(facts.get('approved_plan_context') or '').strip()
        draft = str(facts.get('plan_prompt_draft') or '').strip()
        if approved_context and kind:
            return (
                f'Create the approved {kind} diagram titled "{plan_title}". '
                'The approved plan context below is the only source of geometry, numbers, uses, and labels. '
                + (f'The approved draft prompt below is fact-complete: keep every recorded fact, '
                   f'number, rule, and "not recorded" statement verbatim, polish only the English, '
                   f'and translate any non-English source text. Draft prompt:\n{draft}\n'
                   if draft else '')
                + (f"Client visual note: {description}. " if description else '')
                + 'Do not mention sources, files, pages, or internal review. Do not invent missing values. '
                + approved_context
            )
        scope = f"The client's brief for this diagram: {description}. " if description else ''
        return (
            f'Create a clean conceptual "{plan_title}" planning diagram for {name}. ' + scope +
            'Flat schematic architectural style on a white background: muted pastel color coding, '
            'dark navy outlines, English labels only, a compact legend, and a "NOT TO SCALE" caption. '
            'When a site or map image is attached, trace the parcel outline, setbacks, surrounding '
            'streets, and entrances exactly. Use only the approved program, floor ranges, and areas '
            'from the project facts. No photorealism, no people, no furniture, no room-level detail, '
            'no invented dimensions.'
        )
    component_names = '، '.join(item['name'] for item in (facts.get('components') or []) if item.get('name'))
    return (
        f'Render one photorealistic interior of {name} that belongs to the same project as the attached hero image. '
        f'Visible interior program must come from the financial components only: {component_names or "the listed project components"}. '
        'Do not invent unrelated interior uses.'
    )


def _visual_concept_facts_prompt(facts, slot_id):
    directions = '\n'.join(
        f"- {row['direction']}: {row['regulation_text']}" for row in facts.get('directions') or []
    ) or 'غير متوفر'
    components = '\n'.join(
        f"- {item['name']}"
        + (f" / {item['useType']}" if item.get('useType') else '')
        + (f" / وحدات {item['units']}" if item.get('units') not in (None, '') else '')
        + (f" / مساحة {item['builtArea'] or item['unitArea']}" if (item.get('builtArea') or item.get('unitArea')) else '')
        for item in facts.get('components') or []
    ) or 'غير متوفر'
    selected = facts.get('selected_component') if isinstance(facts.get('selected_component'), dict) else {}
    selected_component = selected.get('name') or 'غير محدد'
    location = '، '.join(part for part in (facts.get('city'), facts.get('district')) if part)
    return (
        f"اسم المشروع: {facts.get('project_name')}\n"
        f"فكرة المشروع: {facts.get('project_idea')}\n"
        f"وصف المشروع والأرض: {facts.get('land_and_building_summary')}\n"
        f"الفئات المستهدفة: {facts.get('target_audience')}\n"
        f"المساحة المعتمدة للدراسة المالية: {facts.get('approved_financial_area')}\n"
        f"عدد الأدوار المعتمدة: {facts.get('approved_floor_count')}\n"
        f"نسبة التغطية المعتمدة: {facts.get('approved_coverage_ratio')}\n"
        f"عدد الواجهات على الشارع: {facts.get('facades_count')}\n"
        f"اتجاهات الواجهات: {facts.get('facades_directions')}\n"
        f"الاستخدامات المسموحة: {facts.get('allowed_uses')}\n"
        f"المدينة والحي: {location or 'غير متوفر'}\n"
        f"جدول الاتجاهات:\n{directions}\n"
        f"مكونات الدراسة المالية:\n{components}\n"
        f"المكون الداخلي المختار: {selected_component}\n"
        f"صور مرجعية للتصميم: {'مرفقة' if facts.get('style_reference_file_ids') else 'غير مرفوعة — ولّد التصميم من البيانات فقط'}\n"
        f"صور مرجعية للمكون الداخلي: {'مرفقة' if facts.get('interior_reference_file_ids') else 'غير مرفوعة'}\n"
        f"خريطة الأرض / المبنى كخلفية الموقع: {'مرفقة' if facts.get('overview_map_url') else 'غير متوفرة'}\n"
        f"نوع الصورة المطلوبة: {_visual_concept_slot_label(slot_id, facts)}\n"
        + (f"المواصفة المعتمدة للمخطط: {facts.get('approved_plan_context')}\n" if facts.get('approved_plan_context') else '')
        + f"تعليمات الكادر: {_visual_concept_slot_instruction(slot_id, facts)}"
    )


def _visual_concept_sanitize_prompt(prompt):
    return _visual_concept_text(prompt, 12000)


def _normalize_image_references(references, tenant_id=None):
    prepared = []
    for reference in references or []:
        item = _prepare_image_reference_for_model(reference, tenant_id) if isinstance(reference, str) and not str(reference).startswith('data:image/') else reference
        if isinstance(item, str) and item.startswith('data:image/'):
            prepared.append(item)
        elif isinstance(item, str) and item:
            resolved = _prepare_image_reference_for_model(item, tenant_id)
            if resolved:
                prepared.append(resolved)
    return prepared


def call_images_api(prompt, references=None, usage_ctx=None, model=None):
    """Generate an image through OpenRouter's dedicated /images endpoint.

    Image-only models (e.g. gpt-image-2.5-*) reject /chat/completions and take
    input_references as {'type': 'image_url', 'image_url': {'url': ...}} objects.
    """
    ctx = usage_ctx or _usage_ctx('image')
    gate = _tenant_key_gate(ctx)
    if gate is not None:
        print(f"[IMAGE ERROR] {gate['message']}")
        return None
    if not _has_any_openrouter_key(ctx):
        print('[IMAGE ERROR] OPENROUTER_KEY is not configured')
        return None
    # ISS-020: reference ownership is checked against the ctx tenant — the
    # worker threads these calls run on have no request context.
    prepared = _normalize_image_references(references, tenant_id=(ctx or {}).get('tenant_id'))
    images_model = model or IMAGE_MODEL
    attempt_id = _begin_ai_attempt_record(ctx, images_model)
    try:
        headers = _openrouter_headers(ctx)
        payload = {
            'model': images_model,
            'prompt': prompt,
            'aspect_ratio': '16:9',
            'quality': 'high',
            'n': 1,
        }
        if prepared:
            payload['input_references'] = [
                {'type': 'image_url', 'image_url': {'url': ref}}
                for ref in prepared[:16]
            ]
        response = requests.post(f'{OPENROUTER_BASE}/images', headers=headers, json=payload, timeout=180)
        data = response.json()
        generation_id, img_usage = _extract_openrouter_usage(data)
        _settle_ai_attempt_record(
            attempt_id,
            'ok' if response.status_code < 400 and 'error' not in data else 'error',
            img_usage, generation_id)
        if response.status_code == 401:
            print('[IMAGE ERROR] OpenRouter API key is invalid or expired (401 Unauthorized)')
            return None
        if response.status_code == 402:
            print('[IMAGE ERROR] OpenRouter account has insufficient credits (402 Payment Required)')
            return None
        if response.status_code == 429:
            print('[IMAGE ERROR] OpenRouter rate limit exceeded (429 Too Many Requests)')
            return None
        if 'error' in data:
            err_msg = data['error'].get('message', '') if isinstance(data['error'], dict) else str(data['error'])
            print(f'[IMAGE ERROR] OpenRouter images API error: {err_msg}')
            return None
        image_url = _image_response_url(data)
        if image_url:
            return image_url
        print(f'[IMAGE ERROR] Images API returned no image (status {response.status_code}). Response: {str(data)[:300]}')
    except requests.exceptions.Timeout:
        print('[IMAGE ERROR] OpenRouter API request timed out')
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
    except requests.exceptions.ConnectionError:
        print('[IMAGE ERROR] Cannot connect to OpenRouter API')
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
    except Exception as e:
        print('[IMAGE ERROR]', str(e))
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
    return None


def call_image_api_with_references(prompt, references=None, usage_ctx=None):
    return call_images_api(prompt, references=references, usage_ctx=usage_ctx)


def _visual_concept_generate_prompt_text(facts, slot_id, current_prompt='', instruction='', image_references=None, usage_ctx=None):
    current = _visual_concept_sanitize_prompt(current_prompt)
    request_text = _visual_concept_text(instruction, 4000)
    is_plan = _visual_concept_is_plan_slot(slot_id)
    banned_clause = (
        'Never invent a generic building style and never copy a previous project signature. '
        'Plan diagrams REQUIRE their English labels, title, legend, entry arrows, and the '
        "'ILLUSTRATIVE REFERENCE - NOT TO SCALE' caption — never remove them. "
        if is_plan else
        'Never invent a generic building style, never copy a previous project signature, '
        'and never add text, logos, people, or watermarks. '
    )
    if current and request_text:
        system_prompt = (
            'You are a smart editor of an existing English architectural image prompt. '
            'The current prompt is the source of truth. Apply only the user request. '
            'Keep every other sentence, constraint, material, camera, and fact unless the user '
            'explicitly asks to rewrite, replace, or start over. '
            'If the user asks to add something, insert it into the existing prompt. '
            'If they ask to change one detail, change that detail only. '
            + banned_clause +
            'Return JSON only: {"prompt":"...","reply":"..."}.'
        )
        user_prompt = (
            'Current prompt (do not discard):\n' + current
            + '\n\nUser request:\n' + request_text
            + (('\n\nApproved plan context; do not change its facts:\n' + facts.get('approved_plan_context'))
               if facts.get('approved_plan_context') else '')
        )
    else:
        system_prompt = (
            'You write one English architectural image prompt for a Saudi real-estate project. '
            'Use only the supplied project facts and attached references. '
            + banned_clause +
            'Match the attached site/map footprint and any attached land photos. '
            'Return JSON only: {"prompt":"..."}.'
        )
        user_prompt = _visual_concept_facts_prompt(facts, slot_id)
        if current:
            user_prompt += '\n\nCurrent prompt to keep as the base:\n' + current
        if request_text:
            user_prompt += '\n\nUser request:\n' + request_text
    references = list(image_references or [])
    response = {}
    for _attempt in range(2):
        response = call_openrouter_chat(
            system_prompt,
            user_prompt,
            temperature=None,
            max_tokens=8000,
            model=SLIDE_TEXT_MODEL,
            reasoning_effort='medium',
            response_format={'type': 'json_object'},
            image_references=references or None,
            usage_ctx=usage_ctx or _usage_ctx('image'),
        )
        text = _get_chat_response_text(response)
        parsed = _designer_json_response(text) if text else {}
        prompt = _visual_concept_sanitize_prompt(parsed.get('prompt') or parsed.get('cover_prompt'))
        if prompt:
            return prompt, parsed.get('reply') or ''
        if not references:
            break
        # A rejected or unreadable reference should not kill prompt writing: retry on facts alone.
        references = []
    extract_chat_content(response, 'VISUAL-CONCEPT-PROMPT')
    return '', ''


def _visual_concept_plan_image_map(data):
    """Approved plan diagram urls keyed by kind — {site, uses, massing}."""
    posted = data.get('planImages') if isinstance(data.get('planImages'), dict) else {}
    if not posted and isinstance(data.get('planImages'), list):
        posted = {kind: url for kind, url in zip(('site', 'uses', 'massing'),
                                                 data.get('planImages'))}
    urls = {}
    for kind in ('site', 'uses', 'massing'):
        raw = posted.get(kind)
        if isinstance(raw, dict):
            raw = raw.get('approvedImageUrl') or raw.get('imageUrl')
        raw = str(raw or '').strip()
        if not raw or raw.lower().startswith('blob:'):
            continue
        # data URIs carry the bytes inline — a length cap would corrupt them.
        urls[kind] = raw[:400000] if raw.startswith('data:image/') else _visual_concept_text(raw, 2000)
    return urls


def _visual_concept_plan_image_urls(data):
    """The three approved plan diagrams the client shipped — exterior renders are
    grounded on them, so they arrive as image references in fixed kind order."""
    mapped = _visual_concept_plan_image_map(data)
    return [mapped[kind] for kind in ('site', 'uses', 'massing') if mapped.get(kind)]


# Sequential plan generation: each diagram is drawn on the previous approved
# image(s), so a later kind cannot run before its predecessors are approved.
_VISUAL_PLAN_KIND_DEPENDENCIES = {'site': (), 'uses': ('site',), 'massing': ('site', 'uses')}
_VISUAL_PLAN_KIND_LABELS = {'site': 'مخطط الموقع العام', 'uses': 'مخطط توزيع الأدوار',
                            'massing': 'المنظور الكتلي'}


def _visual_concept_external_gate(data, slot_id):
    """Exterior slots (cover + the four angles) render the approved plans, so
    they are blocked until the client ships all three approved plan images."""
    if slot_id not in VISUAL_CONCEPT_EXTERNAL_SLOTS:
        return None
    if len(_visual_concept_plan_image_urls(data)) >= 3:
        return None
    return {'success': False,
            'error': 'اعتمد المخططات الثلاثة قبل توليد التصور الخارجي',
            'error_code': 'PLANS_IMAGES_REQUIRED'}


def _visual_concept_cover_image(data, tenant_id=None):
    cover = str(data.get('coverImage') or data.get('cover_image') or '').strip()
    # A blob: URL is meaningless outside the browser tab that made it, so an old draft
    # carrying one must fall back to the stored file instead of losing the cover reference.
    if cover and not cover.lower().startswith('blob:'):
        return cover
    file_id = _visual_concept_text(data.get('coverFileId') or data.get('cover_file_id'), 80)
    if file_id:
        return _visual_concept_project_file_data_uri(file_id, tenant_id) or ''
    return ''


def _visual_concept_collect_generation_references(facts, slot_id, cover_image='', tenant_id=None):
    tenant_id = tenant_id or getattr(g, 'tenant_id', None)
    plan_urls = list(facts.get('plan_image_urls') or [])
    # Exterior slots render the approved plans: the three diagrams lead the
    # reference set, then the hero image (angles only) and any style refs.
    external_cap = 3 + VISUAL_CONCEPT_MAX_REFERENCE_IMAGES
    if slot_id == 'cover':
        file_ids = list(facts.get('style_reference_file_ids') or [])
        map_urls = [facts['overview_map_url']] if facts.get('overview_map_url') else []
        if plan_urls:
            return _visual_concept_reference_uris(
                urls=plan_urls + map_urls, file_ids=file_ids,
                max_images=external_cap, urls_first=True, tenant_id=tenant_id)
        file_ids = file_ids[:VISUAL_CONCEPT_MAX_REFERENCE_IMAGES]
        if len(file_ids) >= VISUAL_CONCEPT_MAX_REFERENCE_IMAGES:
            map_urls = []
        return _visual_concept_reference_uris(urls=map_urls, file_ids=file_ids, tenant_id=tenant_id)
    urls = [cover_image] if cover_image else []
    if _visual_concept_is_internal_slot(slot_id):
        file_ids = list(facts.get('interior_reference_file_ids') or [])[:VISUAL_CONCEPT_MAX_REFERENCE_IMAGES]
        return _visual_concept_reference_uris(
            urls=urls,
            file_ids=file_ids,
            max_images=VISUAL_CONCEPT_MAX_REFERENCE_IMAGES + 1,
            urls_first=True,
            tenant_id=tenant_id,
        )
    if _visual_concept_is_plan_slot(slot_id):
        kind = _visual_concept_plan_kind(slot_id, facts.get('plan_kind'))
        boundary_url = facts.get('plan_boundary_reference_url')
        plan_map = facts.get('plan_image_map') or {}
        urls = [plan_map[dependency]
                for dependency in _VISUAL_PLAN_KIND_DEPENDENCIES.get(kind, ())
                if plan_map.get(dependency)]
        if kind in ('site', 'massing') and boundary_url:
            urls.append(boundary_url)
        if not urls and kind == 'site':
            map_url = facts.get('overview_map_url')
            urls = [map_url] if map_url else []
        return _visual_concept_reference_uris(urls=urls, tenant_id=tenant_id)
    file_ids = list(facts.get('style_reference_file_ids') or [])[:2]
    return _visual_concept_reference_uris(
        urls=plan_urls + urls, file_ids=file_ids,
        max_images=external_cap, urls_first=True, tenant_id=tenant_id)


def _visual_concept_request_bundle(data, slot_id):
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    creative = data.get('creativeImages') if isinstance(data.get('creativeImages'), dict) else {}
    if creative:
        existing = project_data.get('tenantCreativeImages') if isinstance(project_data.get('tenantCreativeImages'), dict) else {}
        project_data = {
            **project_data,
            'tenantCreativeImages': {**existing, **creative},
            'map_placeholders': creative.get('map_placeholders') or project_data.get('map_placeholders'),
        }
    facts = _visual_concept_facts(project_data)
    facts['slot_label'] = _visual_concept_text(data.get('slotLabel') or data.get('slot_label'), 80)
    requested_component_id = _visual_concept_text(data.get('componentId') or data.get('component_id'), 80)
    if _visual_concept_is_internal_slot(slot_id):
        if not requested_component_id:
            requested_component_id = _visual_concept_interior_component_id(slot_id)
        selected = next((item for item in (facts.get('components') or []) if item.get('id') == requested_component_id), None)
        if not selected and requested_component_id:
            selected = next((item for item in (facts.get('components') or []) if item.get('name') == requested_component_id), None)
        if not selected and (facts.get('components') or []):
            selected = facts['components'][0]
        facts['selected_component'] = selected or {}
        facts['interior_reference_file_ids'] = _visual_concept_list(
            data.get('referenceFileIds') or data.get('interiorReferenceFileIds')
        )[:VISUAL_CONCEPT_MAX_REFERENCE_IMAGES]
    is_plan = _visual_concept_is_plan_slot(slot_id)
    if is_plan or slot_id in VISUAL_CONCEPT_EXTERNAL_SLOTS:
        workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
        boundary = workflow.get('boundary') if isinstance(workflow.get('boundary'), dict) else {}
        boundary_points = _visual_concept_plan_boundary_points(
            boundary.get('points') or data.get('planBoundaryPoints') or project_data.get('survey_coordinates'))
        context = workflow.get('planContext') if isinstance(workflow.get('planContext'), dict) else None
        context = context or _visual_concept_plan_context(project_data, boundary_points, workflow.get('verification'))
        context['boundary_points'] = boundary_points or context.get('boundary_points') or []
        if is_plan:
            facts['plan_description'] = _visual_concept_text(
                data.get('planDescription') or data.get('plan_description'), 2000)
            facts['plan_kind'] = _visual_concept_plan_kind(slot_id, data.get('planKind'))
            facts['approved_plan_context'] = _visual_concept_plan_context_text(context)
            stored_prompts = workflow.get('prompts') if isinstance(workflow.get('prompts'), dict) else {}
            stored_draft = _visual_concept_text(stored_prompts.get(facts['plan_kind']), 12000)
            if stored_draft:
                facts['plan_prompt_draft'] = stored_draft
            else:
                distribution = (workflow.get('distribution')
                                if isinstance(workflow.get('distribution'), dict) else {})
                model = _visual_concept_plan_model_from_distribution(
                    distribution, context, context.get('regulations') or {})
                facts['plan_prompt_draft'] = (
                    _visual_concept_plan_drawing_prompt(facts['plan_kind'], context, model=model)
                    if facts['plan_kind'] else '')
            facts['plan_boundary_reference_url'] = _visual_concept_text(
                boundary.get('referenceUrl') or data.get('planBoundaryReferenceUrl'), 500)
        elif _visual_concept_plan_context_has_measurements(context):
            # Exterior renders ground on the same deterministic measurements the
            # plan diagrams draw from — the spec text only, never the diagram's
            # color legend or labelling rules.
            facts['approved_plan_context'] = _visual_concept_plan_context_text(context, diagram_rules=False)
    if slot_id in VISUAL_CONCEPT_EXTERNAL_SLOTS:
        facts['plan_image_urls'] = _visual_concept_plan_image_urls(data)
    elif is_plan:
        facts['plan_image_map'] = _visual_concept_plan_image_map(data)
    missing = _visual_concept_missing_fields(facts, slot_id)
    if _visual_concept_is_internal_slot(slot_id) and not (facts.get('selected_component') or {}).get('name'):
        missing.append({'key': 'project_components_data', 'label': 'اختر مكونًا فعليًا من الدراسة المالية'})
    return project_data, facts, missing


def normalize_presentation_assets(value, tenant_id):
    """Replace embedded image data URIs with compact tenant-scoped file URLs."""
    if isinstance(value, dict):
        return {key: normalize_presentation_assets(item, tenant_id) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_presentation_assets(item, tenant_id) for item in value]
    if not isinstance(value, str) or 'data:image/' not in value:
        return value
    if value.startswith('data:image/'):
        return persist_generated_image(value, tenant_id)
    return re.sub(
        r'data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+',
        lambda match: persist_generated_image(match.group(0), tenant_id),
        value,
    )
