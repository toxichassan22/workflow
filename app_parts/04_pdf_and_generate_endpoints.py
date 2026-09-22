
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Generate PDF with Playwright
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def generate_pdf_with_playwright(html, project_name, branding=None, output_dir=None, tenant_id=None):
    """Generate a PDF from slide HTML using the new generate_pdf export."""
    from exports.pdf_export import generate_pdf
    out_dir = output_dir or OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    safe_name = ''.join(c for c in project_name if c.isalnum() or c in '-_ ')[:50].strip() or 'presentation'
    out_path = os.path.join(out_dir, f"{safe_name}_{int(time.time())}.pdf")
    generate_pdf(html, branding, out_path, tenant_id)
    return out_path

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: record who changed what, on a presentation or a project file
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _history_actor_name():
    """The person behind the acting identity. A tenant-level login carries the
    company name, so the log reads «شركة ليؤمرا» for every edit — resolve it to
    the primary company admin's name instead, falling back to the stored name."""
    name = getattr(g, 'user_name', None)
    if name and not getattr(g, 'user_id', None):
        # A tenant-level session (the company login) only knows the company
        # name — resolve it to the primary admin's name. Entries with no
        # session actor at all (system jobs) keep their empty name.
        try:
            name = db.get_primary_admin_name(getattr(g, 'tenant_id', None)) or name
        except Exception:
            pass
    return name


def _draft_change_id_names():
    """id-to-display-name map for rows the draft references but does not own.

    «team_selection» stores library entity ids in «roles»/«excluded»; the names
    live in tenant_team_entities, so the diff needs them handed in — otherwise
    the log prints raw uuids. Never fails a request.
    """
    try:
        tenant_id = getattr(g, 'tenant_id', None)
        if not tenant_id:
            return {}
        return {entity['id']: entity['name']
                for entity in db.get_team_entities(tenant_id)
                if entity.get('id') and entity.get('name')}
    except Exception:
        return {}


def _record_audit_event(action, entity_type, entity_id, entity_name=None,
                        old_value=None, new_value=None, metadata=None):
    """Write an immutable audit log entry. Never fails a request."""
    try:
        tenant_id = getattr(g, 'tenant_id', None)
        if not tenant_id:
            return None
        meta = dict(metadata or {}) if isinstance(metadata, dict) else {'info': metadata}
        if has_request_context():
            if getattr(request, 'remote_addr', None) and 'ip' not in meta:
                meta['ip'] = request.remote_addr
            if getattr(request, 'user_agent', None) and 'user_agent' not in meta:
                meta['user_agent'] = str(request.user_agent)[:120]
        return db.record_audit_event(
            tenant_id=tenant_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=getattr(g, 'user_id', None),
            user_name=_history_actor_name() or 'مستخدم غير معروف',
            user_role=getattr(g, 'user_role', None),
            entity_name=entity_name,
            old_value=old_value,
            new_value=new_value,
            metadata=meta,
        )
    except Exception as exc:
        print(f'[AUDIT LOG] Could not record {action} on {entity_type} {entity_id}: {exc}')
        return None


def _record_change(target_type, target_id, action, details, source='manual', summary=''):
    """Write one history entry with its individual differences. Never fails a request."""
    try:
        lines = [line for line in (details or []) if str(line or '').strip()]
        if not lines and not summary:
            return None
        _record_audit_event(
            action=action,
            entity_type=target_type,
            entity_id=target_id,
            entity_name=summary or None,
            new_value=lines,
            metadata={'source': source, 'summary': summary} if summary else {'source': source},
        )
        return db.log_change(
            g.tenant_id, target_type, target_id,
            getattr(g, 'user_id', None),
            _history_actor_name() or ('الذكاء الاصطناعي' if source == 'ai' else 'مستخدم غير معروف'),
            action, summary=summary, details=lines, source=source,
        )
    except Exception as exc:
        print(f'[CHANGE LOG] Could not record {action} on {target_type} {target_id}: {exc}')
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Clean base64 and large image data from project data
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def clean_project_data(data):
    if not data:
        return data
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            if k in ['mainImageData', 'moodboardImages', 'aiGeneratedImages', 'creativeImages', 'creativeSlots', 'image_b64', 'image', 'logo', 'referenceImage', 'slides']:
                continue
            cleaned[k] = clean_project_data(v)
        return cleaned
    elif isinstance(data, list):
        return [clean_project_data(item) for item in data]
    elif isinstance(data, str):
        if data.startswith('data:image/') or (len(data) > 1000 and ';base64,' in data):
            return "[IMAGE_DATA_OMITTED]"
        return data
    else:
        return data

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GLM Parallel Batch Prompt Builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_GENERATION_PROJECT_IMAGE_CACHE = {}
_LOGO_APPEARANCE_CACHE = {}


TENANT_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp')


def _tenant_image_storage_candidates(tenant_id, base_name):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(tenant_id or '')):
        return []
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(base_name or '')):
        return []
    tenant_dir = os.path.realpath(os.path.join(UPLOADS_DIR, str(tenant_id)))
    return [os.path.join(tenant_dir, f'{base_name}{extension}')
            for extension in TENANT_IMAGE_EXTENSIONS]


def _tenant_image_storage_path(tenant_id, base_name):
    candidates = [path for path in _tenant_image_storage_candidates(tenant_id, base_name)
                  if os.path.isfile(path)]
    return max(candidates, key=os.path.getmtime) if candidates else ''


def _tenant_logo_storage_path(tenant_id):
    stored = _tenant_image_storage_path(tenant_id, 'logo')
    if stored:
        return stored
    fallback = os.path.join(os.path.dirname(__file__), 'assets', 'logo.png')
    return fallback if os.path.isfile(fallback) else ''


def _tenant_watermark_storage_path(tenant_id):
    """Return only the tenant's uploaded watermark, with no logo fallback."""
    return _tenant_image_storage_path(tenant_id, 'watermark')


def _project_logo_storage_path(project_data, tenant_id):
    source = project_data if isinstance(project_data, dict) else {}
    meta = source.get('project_logo_file_meta') if isinstance(source.get('project_logo_file_meta'), dict) else {}
    file_id = source.get('project_logo_file_id') or meta.get('id')
    logo_value = str(source.get('project_logo') or '').strip()
    if not file_id and logo_value:
        match = re.search(r'/api/project-files/([^/?#]+)', logo_value)
        if match:
            file_id = match.group(1)
    if file_id:
        stored = db.get_project_file(tenant_id, str(file_id))
        if stored and stored.get('mime_type', '').startswith('image/'):
            path = _resolve_project_file_storage_path(stored, tenant_id)
            if path and os.path.isfile(path):
                return path
    relative = logo_value.split('?', 1)[0].lstrip('/')
    if relative.startswith('uploads/'):
        path = os.path.realpath(os.path.join(os.path.dirname(__file__), relative.replace('/', os.sep)))
        tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, str(tenant_id)))
        try:
            if os.path.commonpath([tenant_root, path]) == tenant_root and os.path.isfile(path):
                return path
        except ValueError:
            pass
    return ''


def _logo_pixel_luminance(red, green, blue):
    channels = [value / 255 for value in (red, green, blue)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
              for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _logo_appearance_from_path(path):
    if not path or not os.path.isfile(path):
        return 'unknown'
    stat = os.stat(path)
    key = (os.path.realpath(path), stat.st_mtime_ns, stat.st_size)
    cached = _LOGO_APPEARANCE_CACHE.get(key)
    if cached:
        return cached
    try:
        from PIL import Image
        with Image.open(path) as source:
            image = source.convert('RGBA')
            image.thumbnail((256, 256))
            width, height = image.size
            pixel_data = image.get_flattened_data() if hasattr(image, 'get_flattened_data') else image.getdata()
            pixels = list(pixel_data)
    except (OSError, ValueError):
        return 'unknown'
    visible = [pixel for pixel in pixels if pixel[3] >= 40]
    if not visible:
        return 'unknown'
    if len(visible) >= len(pixels) * 0.98 and width > 1 and height > 1:
        border = []
        for x in range(width):
            border.extend((image.getpixel((x, 0)), image.getpixel((x, height - 1))))
        for y in range(1, height - 1):
            border.extend((image.getpixel((0, y)), image.getpixel((width - 1, y))))
        background = tuple(sorted(pixel[channel] for pixel in border)[len(border) // 2]
                           for channel in range(3))
        foreground = [pixel for pixel in visible
                      if sum((pixel[channel] - background[channel]) ** 2 for channel in range(3)) >= 900]
        if len(foreground) >= max(12, len(visible) // 200):
            visible = foreground
    luminances = sorted(_logo_pixel_luminance(*pixel[:3]) for pixel in visible)
    median = luminances[len(luminances) // 2]
    light_share = sum(value >= 0.68 for value in luminances) / len(luminances)
    dark_share = sum(value <= 0.32 for value in luminances) / len(luminances)
    mean = sum(luminances) / len(luminances)
    tone = 'light' if median >= 0.58 or light_share >= 0.52 or (light_share >= 0.35 and dark_share < 0.25) else 'dark'
    if 0.48 < median < 0.58 and light_share < 0.35 and dark_share < 0.35:
        tone = 'light' if mean >= 0.55 else 'dark'
    _LOGO_APPEARANCE_CACHE[key] = tone
    return tone


def _prepare_generation_logo_context(project_data, branding, tenant_id):
    company_tone = _logo_appearance_from_path(_tenant_logo_storage_path(tenant_id))
    project_tone = _logo_appearance_from_path(_project_logo_storage_path(project_data, tenant_id))
    branding['_logo_tone'] = company_tone
    project_data['_company_logo_tone'] = company_tone
    project_data['_project_logo_tone'] = project_tone
    return company_tone, project_tone


def _generation_project_image_url(tenant_id, file_id):
    key = (str(tenant_id or ''), str(file_id or ''))
    if not all(key):
        return ''
    cached = _GENERATION_PROJECT_IMAGE_CACHE.get(key)
    if cached:
        return cached
    url = _publish_project_file_as_creative_image(file_id, tenant_id) or ''
    if url:
        _GENERATION_PROJECT_IMAGE_CACHE[key] = url
    return url


def _generation_asset_url(value, tenant_id=None):
    """Return a durable image URL from a visual-concept asset record."""
    source = value if isinstance(value, dict) else {'url': value}
    url = str(
        source.get('approvedImageUrl') or source.get('approved_image_url')
        or source.get('imageUrl') or source.get('image_url')
        or source.get('url') or source.get('path') or ''
    ).strip()
    # ``available`` is used by the compact planner payload and is not an image.
    if not url or url.lower() in {'available', 'blob:', 'undefined', 'null', 'none'} or url.lower().startswith('blob:'):
        url = ''
    if not url:
        file_id = source.get('fileId') or source.get('file_id') or source.get('sourceFileId') or source.get('source_file_id') or source.get('id')
        if file_id and str(file_id).strip() and not str(file_id).startswith('plan_'):
            url = _generation_project_image_url(tenant_id, file_id)
    if url and not url.startswith('/') and not url.startswith('http') and not url.startswith('data:'):
        url = '/' + url.lstrip('/')
    return url


def _visual_concept_generation_images(project_data, tenant_id):
    """Read every visual-concept image, including uploaded images still awaiting approval."""
    source = project_data if isinstance(project_data, dict) else {}
    visual = source.get('visual_concept')
    if isinstance(visual, str):
        visual = _visual_concept_parse_json(visual, {})
    visual = visual if isinstance(visual, dict) else {}
    slots = visual.get('slots') if isinstance(visual.get('slots'), dict) else {}
    creative = source.get('tenantCreativeImages') if isinstance(source.get('tenantCreativeImages'), dict) else {}

    def slot_value(slot_id):
        aliases = {
            'right': ('right', 'east', 'east_facade'),
            'left': ('left', 'west', 'west_facade'),
            'top': ('top', 'aerial', 'above'),
            'back': ('back', 'rear', 'behind'),
        }
        for alias in aliases.get(slot_id, (slot_id,)):
            if isinstance(slots.get(alias), dict):
                return slots[alias]
        return {}

    moodboard = []
    moodboard_meta = []
    for slot_id in ('right', 'left', 'top', 'back'):
        item = slot_value(slot_id)
        url = _generation_asset_url(item, tenant_id)
        if not url:
            continue
        moodboard.append({
            'url': url,
            'label': str(item.get('label') or slot_id).strip(),
            'caption': str(item.get('caption') or '').strip(),
        })
        moodboard_meta.append({
            'label': str(item.get('label') or slot_id).strip(),
            'caption': str(item.get('caption') or '').strip(),
            'url': url,
        })
    if not moodboard:
        saved_moodboard = creative.get('moodboard')
        if isinstance(saved_moodboard, list):
            for index, item in enumerate(saved_moodboard, 1):
                url = _generation_asset_url(item, tenant_id)
                if not url:
                    continue
                source_item = item if isinstance(item, dict) else {}
                moodboard.append({
                    'url': url,
                    'label': str(source_item.get('label') or f'التصور الخارجي {index}').strip(),
                    'caption': str(source_item.get('caption') or '').strip(),
                })
                moodboard_meta.append({
                    'label': str(source_item.get('label') or f'التصور الخارجي {index}').strip(),
                    'caption': str(source_item.get('caption') or '').strip(),
                    'url': url,
                })

    component_rows = _visual_concept_components(source)
    component_by_id = {str(row.get('id')): row for row in component_rows}
    interior_groups = {}
    interior_order = []
    for slot_id, item in slots.items():
        slot_name = str(slot_id or '')
        if slot_name == 'interior':
            component_id, view_index = 'interior', 1
        elif slot_name.startswith('interior_'):
            remainder = slot_name[len('interior_'):]
            if '::' in remainder:
                component_id, raw_index = remainder.rsplit('::', 1)
                try:
                    view_index = int(raw_index)
                except (TypeError, ValueError):
                    view_index = 1
            else:
                component_id, view_index = remainder, 1
        else:
            continue
        url = _generation_asset_url(item, tenant_id)
        if not url:
            continue
        if component_id not in interior_groups:
            interior_groups[component_id] = []
            interior_order.append(component_id)
        interior_groups[component_id].append({
            'url': url,
            'label': str(item.get('label') or '').strip(),
            'caption': str(item.get('caption') or '').strip(),
            '_view_index': view_index,
        })

    interior_components = []
    ordered_component_ids = [str(row.get('id')) for row in component_rows if str(row.get('id')) in interior_groups]
    ordered_component_ids += [component_id for component_id in interior_order if component_id not in ordered_component_ids]
    for component_id in ordered_component_ids:
        items = sorted(interior_groups.get(component_id, []), key=lambda item: int(item.get('_view_index') or 1))
        row = component_by_id.get(component_id) or {}
        component_name = str(row.get('name') or ('التصميم الداخلي' if component_id == 'interior' else component_id)).strip()
        for item in items:
            item.pop('_view_index', None)
            if not item.get('label'):
                item['label'] = component_name
        if items:
            interior_components.append({'id': component_id, 'name': component_name, 'images': items})

    plans = []
    raw_plans = visual.get('plans2d') if isinstance(visual.get('plans2d'), list) else []
    for index, item in enumerate(raw_plans, 1):
        if not isinstance(item, dict):
            continue
        url = _generation_asset_url(item, tenant_id)
        if not url:
            continue
        plans.append({
            'url': url,
            'title': str(item.get('title') or item.get('fileName') or f'المخطط {index}').strip(),
            'description': str(item.get('description') or '').strip(),
            'name': str(item.get('fileName') or '').strip(),
        })

    cover_item = slot_value('cover') or slots.get('cover') or slots.get('main') or slots.get('primary') or {}
    cover_url = _generation_asset_url(cover_item, tenant_id)
    if not cover_url:
        cover_url = (
            _generation_asset_url(creative.get('cover'), tenant_id)
            or _generation_asset_url(creative.get('coverImage'), tenant_id)
            or _generation_asset_url(creative.get('mainImageData'), tenant_id)
            or _generation_asset_url(source.get('cover'), tenant_id)
            or _generation_asset_url(source.get('coverImage'), tenant_id)
            or _generation_asset_url(source.get('cover_image'), tenant_id)
            or _generation_asset_url(source.get('mainImageData'), tenant_id)
            or _generation_asset_url(source.get('project_image_cover'), tenant_id)
            or ''
        )

    return {
        'cover': cover_url,
        'moodboard': moodboard,
        'moodboard_meta': moodboard_meta,
        'interior_components': interior_components,
        'interior': [item['url'] for component in interior_components for item in component.get('images', []) if item.get('url')],
        'plans': plans,
        'plan_meta': [
            {'title': item.get('title') or '', 'description': item.get('description') or '', 'url': item.get('url') or ''}
            for item in plans
        ],
    }


def _augment_generation_images(images, project_data, tenant_id):
    result = dict(images) if isinstance(images, dict) else {}
    persisted_visual = _visual_concept_generation_images(project_data, tenant_id)

    def real_asset_count(values):
        if isinstance(values, list):
            return sum(bool(_generation_asset_url(item)) for item in values)
        return 0

    def real_component_asset_count(values):
        if not isinstance(values, list):
            return 0
        return sum(real_asset_count(component.get('images')) for component in values if isinstance(component, dict))

    if not result.get('cover'):
        result['cover'] = (
            persisted_visual.get('cover')
            or _generation_asset_url(result.get('cover'), tenant_id)
            or _generation_asset_url(result.get('coverImage'), tenant_id)
            or _generation_asset_url(result.get('mainImageData'), tenant_id)
            or _generation_asset_url((project_data or {}).get('cover'), tenant_id)
            or _generation_asset_url((project_data or {}).get('coverImage'), tenant_id)
            or _generation_asset_url((project_data or {}).get('cover_image'), tenant_id)
            or _generation_asset_url((project_data or {}).get('mainImageData'), tenant_id)
            or _generation_asset_url((project_data or {}).get('project_image_cover'), tenant_id)
            or ''
        )

    # A compact plan request carries the word ``available`` instead of URLs. If the client state
    # was stale, prefer the persisted visual-concept state when it contains more media so no
    # uploaded view disappears from the generated section.
    if real_asset_count(result.get('moodboard')) < real_asset_count(persisted_visual.get('moodboard')):
        result['moodboard'] = persisted_visual['moodboard']
        result['moodboard_meta'] = persisted_visual['moodboard_meta']
    if real_component_asset_count(result.get('interior_components')) < real_component_asset_count(persisted_visual.get('interior_components')):
        result['interior_components'] = persisted_visual['interior_components']
        result['interior'] = persisted_visual['interior']
    if real_asset_count(result.get('plans')) < real_asset_count(persisted_visual.get('plans')):
        result['plans'] = persisted_visual['plans']
        result['plan_meta'] = persisted_visual['plan_meta']
    team_members = []
    for entry in slide_engine._selected_team_entries(project_data or {}, tenant_id):
        file_id = entry.get('_logo_file_id') or ''
        team_members.append({
            'name': entry.get('الجهة') or '',
            'role': entry.get('الدور') or '',
            'logo': _generation_project_image_url(tenant_id, file_id) if file_id else '',
        })
    result['team_members'] = team_members
    market_state = (project_data or {}).get('market_study_data')
    if isinstance(market_state, str):
        try:
            market_state = json.loads(market_state)
        except (TypeError, ValueError):
            market_state = {}
    competitors = market_state.get('competitors') if isinstance(market_state, dict) else []
    competitor_logos = []
    for row in competitors if isinstance(competitors, list) else []:
        if not isinstance(row, dict):
            continue
        logo = str(row.get('logo_path') or row.get('logo_url') or '').strip()
        if not logo and row.get('logo_file_id'):
            logo = _generation_project_image_url(tenant_id, row['logo_file_id'])
        competitor_logos.append({'name': str(row.get('name') or '').strip(), 'logo': logo})
    result['competitor_logos'] = competitor_logos
    land_source = result.get('land_photos')
    if not isinstance(land_source, list):
        land_source = (project_data or {}).get('land_photos_file_meta')
    land_photos = []
    for item in land_source if isinstance(land_source, list) else []:
        source = item if isinstance(item, dict) else {}
        url = str(source.get('url') or source.get('imageUrl') or source.get('path') or '').strip()
        if url and not url.startswith('/') and not url.startswith('http'):
            url = '/' + url.lstrip('/')
        if not url and source.get('id'):
            url = _generation_project_image_url(tenant_id, source['id'])
        if url:
            land_photos.append({
                'url': url,
                'description': str(source.get('description') or source.get('caption') or '').strip(),
                'name': str(source.get('originalName') or source.get('name') or '').strip(),
            })
    result['land_photos'] = land_photos
    return result


def _presentation_creative_images(project_data, tenant_id):
    source = project_data if isinstance(project_data, dict) else {}
    saved = source.get('tenantCreativeImages') if isinstance(source.get('tenantCreativeImages'), dict) else {}
    return _augment_generation_images(saved, source, tenant_id)


def _get_images_info(images, project_data=None):
    interior_components = []
    moodboard_meta = []
    moodboard_items = []
    plan_meta = []
    land_photos = []
    team_members = []
    if isinstance(images, list):
        has_cover = bool(images[0]) if images else False
        moodboard_items = [(index, image) for index, image in enumerate(images[1:], 1) if image]
        moodboard_count = len(moodboard_items)
        interior_count = 0
        plans_count = 0
    elif isinstance(images, dict):
        has_cover = bool(images.get('cover'))
        moodboard_items = [(index, image) for index, image in enumerate(images.get('moodboard', []), 1) if image]
        moodboard_count = len(moodboard_items)
        moodboard_meta = images.get('moodboard_meta') if isinstance(images.get('moodboard_meta'), list) else []
        interior_components = images.get('interior_components', [])
        interior_count = sum(1 for img in images.get('interior', []) if img)
        plans_count = sum(1 for img in images.get('plans', []) if img)
        plan_meta = images.get('plan_meta') if isinstance(images.get('plan_meta'), list) else []
        land_photos = images.get('land_photos') if isinstance(images.get('land_photos'), list) else []
        team_members = images.get('team_members') if isinstance(images.get('team_members'), list) else []
    else:
        has_cover = False
        moodboard_count = 0
        interior_count = 0
        plans_count = 0

    # The design rules say to place ##PROJECT_LOGO## "if it exists", and the model had no way of
    # knowing whether it does, so an uploaded project logo was simply never used.
    project_source = project_data or {}
    company_tone = str(project_source.get('_company_logo_tone') or '').strip().lower()
    project_tone = str(project_source.get('_project_logo_tone') or '').strip().lower()
    tone_rules = {
        'light': 'فاتح — خلفية داكنة إلزامية، وممنوع وضعه مباشرة على الأبيض',
        'dark': 'داكن — خلفية بيضاء إلزامية، وممنوع وضعه مباشرة على الكحلي أو الأسود',
        'unknown': 'غير محسوم — لا تفترض لونًا مماثلًا لخلفيته',
    }
    info = f"- نتيجة تحليل شعار الشركة: شعار الشركة {tone_rules.get(company_tone, tone_rules['unknown'])}.\n"
    project_logo = str(project_source.get('project_logo') or '').strip()
    if project_logo:
        info += ("- شعار المشروع: متوفر ومرفوع من العميل. ضع ##PROJECT_LOGO## بجانب شعار الشركة "
                 "##LOGO## في هيدر كل شريحة محتوى، وفي الغلاف والختام معًا جنبًا إلى جنب بفاصل "
                 "رأسي رقيق بينهما. هذا إلزامي وليس اختياريًا. "
                 f"نتيجة التحليل: شعار المشروع {tone_rules.get(project_tone, tone_rules['unknown'])}.\n")
    else:
        info += "- شعار المشروع: لا يوجد — استخدم شعار الشركة ##LOGO## وحده ولا تكتب ##PROJECT_LOGO##.\n"
    info += f"- صورة الغلاف: {'متوفرة (استخدم ##IMAGE_COVER##)' if has_cover else 'لا توجد'}\n"
    if moodboard_count > 0:
        info += f"\n## التصورات الخارجية المتوفرة ({moodboard_count} صور)\n"
        info += "استخدم صورة واحدة كبيرة أو صورتين بحد أقصى في الصفحة، ويمكن استخدام أول صورتين غير رئيسيتين داخل نبذة عن المشروع. أنشئ صفحات إضافية حتى تظهر جميع الصور بوضوح:\n"
        for token_index, _image in moodboard_items:
            meta = moodboard_meta[token_index - 1] if token_index <= len(moodboard_meta) and isinstance(moodboard_meta[token_index - 1], dict) else {}
            label = str(meta.get('label') or f'التصور الخارجي {token_index}').strip()
            caption = str(meta.get('caption') or '').strip()
            info += f"- ##MOODBOARD_IMAGE_{token_index}## — {label}" + (f": {caption}" if caption else '') + "\n"
    else:
        info += "- صور التصورات الخارجية: لا توجد\n"

    if interior_components:
        info += f"\n## صور التصورات الداخلية موزعة حسب المكونات ({len(interior_components)} مكونات)\n"
        info += "اعرض صورة واحدة كبيرة أو صورتين بحد أقصى في الصفحة، ووزع بقية الصور على صفحات إضافية مع التسمية والوصف الصحيحين:\n"
        for c_idx, comp in enumerate(interior_components, 1):
            c_name = str(comp.get('name') or f'المكون {c_idx}').strip()
            c_imgs = comp.get('images', []) if isinstance(comp.get('images'), list) else []
            for image_index, image in enumerate(c_imgs, 1):
                source = image if isinstance(image, dict) else {}
                label = str(source.get('label') or c_name).strip()
                caption = str(source.get('caption') or '').strip()
                info += f"- ##INTERIOR_COMP_{c_idx}_IMG_{image_index}## — {c_name} — {label}" + (f": {caption}" if caption else '') + "\n"
    elif interior_count > 0:
        info += f"- صور التصورات الداخلية: ##INTERIOR_IMAGE_1## حتى ##INTERIOR_IMAGE_{interior_count}##، صورة واحدة كبيرة أو صورتان بحد أقصى في الصفحة.\n"

    if plans_count > 0:
        info += f"\n## المخططات المعمارية المرفوعة ({plans_count} مخططات)\n"
        for index in range(1, plans_count + 1):
            meta = plan_meta[index - 1] if index <= len(plan_meta) and isinstance(plan_meta[index - 1], dict) else {}
            title = str(meta.get('title') or meta.get('name') or f'المخطط {index}').strip()
            description = str(meta.get('description') or '').strip()
            info += f"- ##PLAN_IMAGE_{index}## — {title}" + (f": {description}" if description else '') + "\n"
        info += "كل مخطط له صفحة مستقلة أو مساحة كبيرة، ولا يجوز ضغط عدة مخططات في شبكة صغيرة.\n"

    if land_photos:
        info += f"\n## صور الأرض المرفوعة ({len(land_photos)} صور)\n"
        info += "اعرضها داخل قسم تحليل الأرض بصورة واحدة كبيرة أو صورتين بحد أقصى في الصفحة، ثم اعرض ملخص الأرض النهائي بعد صفحات الصور:\n"
        for index, photo in enumerate(land_photos, 1):
            source = photo if isinstance(photo, dict) else {}
            description = str(source.get('description') or '').strip()
            name = str(source.get('name') or f'صورة الأرض {index}').strip()
            info += f"- ##LAND_PHOTO_{index}## — {name}" + (f": {description}" if description else ': لا يوجد وصف محفوظ') + "\n"
    else:
        info += "- صور الأرض: لا توجد\n"

    if team_members:
        info += f"\n## شعارات فريق العمل ({len(team_members)} جهات مرتبة)\n"
        for index, member in enumerate(team_members, 1):
            source = member if isinstance(member, dict) else {}
            name = str(source.get('name') or f'الجهة {index}').strip()
            role = str(source.get('role') or '').strip()
            if source.get('logo'):
                info += f"- {name}" + (f" — {role}" if role else '') + f": الشعار متوفر ويجب استخدام ##TEAM_LOGO_{index}## عند ذكر الجهة.\n"
            else:
                info += f"- {name}" + (f" — {role}" if role else '') + ": لا يوجد شعار مرفوع؛ لا تنشئ بديلاً مصورًا.\n"

    # Map image placeholders (populated when project has location data). An absent map used to be
    # simply unmentioned, and the rules list every token, so the model wrote one anyway; the
    # unresolved token was then blanked and the slide shipped with an empty frame. Every map is
    # now named as available or as forbidden, exactly like ##PROJECT_LOGO##.
    map_placeholders = {
        '##MAP_OVERVIEW##': 'خريطة الموقع العامة',
        '##MAP_LANDMARKS##': 'خريطة المعالم المحيطة',
        '##MAP_ACCESS##': 'خريطة الوصول والطرق',
        '##MAP_CATCHMENT##': 'خريطة نطاق التأثير',
    }
    supplied_maps = images.get('map_placeholders') if isinstance(images, dict) else None
    available_maps = {placeholder for placeholder, path in (supplied_maps or {}).items() if path}
    for placeholder, label in map_placeholders.items():
        if placeholder in available_maps:
            info += f"- {label}: {placeholder}\n"
        else:
            info += f"- {label}: غير متوفرة — ممنوع كتابة {placeholder}\n"
    info += f"- {slide_engine.NO_STREET_VIEW_RULE}\n"
    if not has_cover:
        info += "- ممنوع كتابة ##IMAGE_COVER## أو ##MAIN_IMAGE## لعدم وجود صورة رئيسية معتمدة\n"
    if moodboard_count <= 0:
        info += "- ممنوع كتابة ##MOODBOARD_IMAGE_N## لعدم وجود صور للزوايا الخارجية\n"
    if not interior_components and interior_count <= 0:
        info += "- ممنوع كتابة ##INTERIOR_...## لعدم وجود صور تصور داخلي\n"
    if plans_count <= 0:
        info += "- ممنوع كتابة ##PLAN_IMAGE_N## أو ##2D_PLAN_N## لعدم وجود مخططات مرفوعة\n"
    if not land_photos:
        info += "- ممنوع كتابة ##LAND_PHOTO_N## لعدم وجود صور أرض مرفوعة\n"
    if not any(isinstance(member, dict) and member.get('logo') for member in team_members):
        info += "- ممنوع كتابة ##TEAM_LOGO_N## لعدم وجود شعارات فريق متاحة\n"
    
    # Landmark driving times and distances
    if isinstance(images, dict) and images.get('map_landmarks'):
        landmarks = images['map_landmarks']
        if landmarks:
            info += "\n## أوقات القيادة والمسافات الفعلية من Google Maps\n"
            info += "استخدم هذه البيانات الحقيقية في شريحة المعالم (map_landmarks):\n"
            for lm in landmarks:
                name = lm.get('name', lm.get('description', 'معلم'))
                duration = lm.get('duration_minutes', '?')
                dist = lm.get('distance_text', '?')
                info += f"- {name}: {duration} دقيقة، {dist}\n"
    
    return info

def build_system_prompt(project_data, images_info, design_rules=None, offer_lang=None):
    """Build the shared system prompt ONCE for all slides."""
    if design_rules is None:
        design_rules = build_design_rules({})
    lang = slide_engine.resolve_offer_lang(project_data, offer_lang)
    project_json = slide_engine.build_project_facts(project_data, getattr(g, 'tenant_id', None))
    timeline_note = slide_engine._timeline_data_note(project_data)
    financial_note = slide_engine._financial_data_note(project_data)
    prompt = f"""{design_rules}

## بيانات المشروع
{project_json}

## الصور المتوفرة
{images_info}
{timeline_note}
{financial_note}"""
    if lang == slide_engine.OFFER_LANG_ENGLISH:
        prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
    return prompt

def resolve_logo_in_html(html, tenant_id=None, _branding_cache=None):
    """Replace all logo placeholders and broken logo paths with tenant's logo URL."""
    if not html:
        return html
    logo_url = '/assets/logo.png'
    if tenant_id:
        branding = _branding_cache if _branding_cache is not None else (db.get_branding(tenant_id) or {})
        if branding.get('logo_path'):
            logo_url = branding['logo_path']
            if not logo_url.startswith('http') and '?t=' not in logo_url:
                logo_url = f"{logo_url}?t=1"
        else:
            logo_url = f"/tenant-assets/{tenant_id}/logo?t=1"
    else:
        logo_url = '/assets/logo.png'

    if not logo_url.startswith('/') and not logo_url.startswith('http'):
        logo_url = f"/{logo_url}"

    html = html.replace('##LOGO##', logo_url)
    html = re.sub(
        r'src=["\'](?:/?assets/logo\.png|logo\.png|/logo\.png|undefined|null|none)["\']',
        f'src="{logo_url}"',
        html,
        flags=re.IGNORECASE
    )

    def _fix_logo_img(match):
        img_tag = match.group(0)
        lowered = img_tag.lower()
        src_match = re.search(r'\bsrc\s*=\s*["\']([^"\']*)["\']', img_tag, flags=re.IGNORECASE)
        src_value = str(src_match.group(1) if src_match else '').strip()
        src_lower = src_value.lower()
        if src_lower.startswith('data:') or src_lower.startswith('blob:'):
            return img_tag
        if re.search(r'/tenant-assets/[^/]+/watermark(?:[?#]|$)', src_lower):
            return img_tag
        if '/uploads/creative/' in lowered or '/api/project-files/' in lowered or 'project-files' in lowered:
            return img_tag
        if 'project_logo' in lowered or '##project_logo##' in lowered or 'project-logo' in lowered:
            return img_tag
        # The managed chrome contains a company logo and, when available, a
        # project logo.  A resolved project-file URL does not contain the
        # semantic marker above, so the legacy compatibility pass used to
        # rewrite it back to the company logo.  Preserve resolved chrome URLs;
        # only placeholders and known company-logo fallbacks need replacement.
        if 'presentation-chrome-logo' in lowered:
            src = src_lower
            if src and not src.startswith('##') and not src.startswith('/assets/logo.png'):
                return img_tag
        tag_without_src = re.sub(r'src\s*=\s*["\'][^"\']*["\']', '', img_tag, flags=re.IGNORECASE).lower()
        if 'logo' in tag_without_src or '##LOGO##' in img_tag or 'tenant-assets' in img_tag:
            if 'src=' in img_tag.lower():
                img_tag = re.sub(r'src=["\'][^"\']*["\']', f'src="{logo_url}"', img_tag, flags=re.IGNORECASE)
            else:
                img_tag = img_tag.replace('<img', f'<img src="{logo_url}"')

            # Ensure proper styling so logo never collapses or breaks
            if 'style=' in img_tag.lower():
                img_tag = re.sub(
                    r'style=["\']([^"\']*)["\']',
                    r'style="\1;max-height:50px;width:auto;object-fit:contain;display:inline-block;"',
                    img_tag,
                    flags=re.IGNORECASE
                )
            else:
                img_tag = img_tag.replace('<img', f'<img style="max-height:50px;width:auto;object-fit:contain;display:inline-block;"')
        return img_tag

    html = re.sub(r'<img\s[^>]*>', _fix_logo_img, html, flags=re.IGNORECASE)
    return html


def postprocess_slide(html, slide_num=None, tenant_id=None, slide_title=None, total_slides=None, slide_type=None):
    """Compatibility wrapper around slide_engine.postprocess_slide.

    Existing callers in app.py pass (html, slide_num, tenant_id). The slide_engine
    implementation is semantic-type driven and no longer depends on SLIDE_DEFS.
    """
    if slide_type is None:
        n = int(slide_num or 0)
        t = int(total_slides or 0)
        normalized_title = str(slide_title or '').strip().lower()
        if n == 1 or re.search(r'غلاف|cover|front', normalized_title):
            slide_type = 'cover'
        elif (t and n == t) or re.search(r'ختام|closing|شكراً|شكرًا|thanks', normalized_title):
            slide_type = 'closing'
        else:
            slide_type = 'content'

    branding = db.get_branding(tenant_id) if tenant_id else None
    return slide_engine.postprocess_slide(
        html,
        slide_type,
        slide_num=slide_num,
        slide_title=slide_title,
        total_slides=total_slides,
        tenant_id=tenant_id,
        branding=branding,
    )

def generate_single_slide(system_prompt, slide_num, tenant_id=None, max_retries=2, total=None, title=None, usage_ctx=None, offer_lang=None):
    """Generate one complete slide, retrying with a stricter prompt when needed."""
    deck_en = (offer_lang == slide_engine.OFFER_LANG_ENGLISH)
    slide_title = title or (f'Slide {slide_num}' if deck_en else f'شريحة {slide_num}')
    style = _suggest_design_style(slide_title, slide_type='content')
    slide = {
        'title': slide_title,
        'type': 'content',
        'design_style': style,
        'content_density': 'medium',
        'requires_image': False,
        'bullets': []
    }
    branding = db.get_branding(tenant_id) if tenant_id else {}
    if total is None:
        _min_s, _max_s, total = resolve_slide_bounds(branding)
        total = max(_min_s, min(total, _max_s))
    total = int(total)
    base_user_msg = slide_engine.build_slide_user_msg(slide, slide_num, total, branding, project_data=None, offer_lang=offer_lang)

    for attempt in range(1, max_retries + 2):
        try:
            user_msg = base_user_msg
            if attempt > 1:
                user_msg += (
                    "\n\nإعادة المحاولة: أعد إنشاء الشريحة كاملة من البداية. "
                    "أخرج div class=\"slide\" واحداً مغلقاً بشكل صحيح، "
                    "ولا تتوقف قبل اكتماله. لا تكتب أي شرح أو markdown."
                )
            print(f"[SLIDE-{slide_num}] Attempt {attempt}: {slide_title}")
            response = call_zai_chat(system_prompt, user_msg, max_tokens=7000, model=SLIDE_TEXT_MODEL, usage_ctx=usage_ctx or _usage_ctx('slide'))
            if 'choices' not in response or not response.get('choices'):
                print(f"[SLIDE-{slide_num}] ERROR: no choices (attempt {attempt})")
                continue
            html = extract_html_from_glm(response)
            html = postprocess_slide(html, slide_num, tenant_id=tenant_id, slide_title=slide_title, total_slides=total, slide_type='content')
            html = slide_engine.resolve_logo_in_html(html, tenant_id)
            count = html.count('class="slide"')
            if count >= 1:
                print(f"[SLIDE-{slide_num}] OK Done ({len(html)} chars)")
                return html
            print(f"[SLIDE-{slide_num}] WARN No slide found (attempt {attempt})")
        except Exception as e:
            print(f"[SLIDE-{slide_num}] EXCEPTION (attempt {attempt}): {e}")

    print(f"[SLIDE-{slide_num}] FAIL All attempts failed for {slide_title}")
    return ''

def build_glm_prompt(project_data, images, branding=None):
    """Legacy single-shot prompt builder (kept for /api/generate compatibility)."""
    project_data = clean_project_data(project_data)
    images_info = _get_images_info(images, project_data)

    # Resolve dynamic brand rules
    if branding is None:
        tenant_id = getattr(g, 'tenant_id', None)
        branding = db.get_branding(tenant_id) if tenant_id else {}
    dynamic_rules = build_design_rules(branding)
    min_s, max_s, default_count = resolve_slide_bounds(branding)
    slide_count = max(min_s, min(default_count, max_s))
    fallback_plan = build_fallback_plan(branding, project_data)
    slides = fallback_plan.get('slides', [])
    generic_slide = {
        'title': 'تفاصيل إضافية',
        'type': 'content',
        'design_style': _suggest_design_style('تفاصيل إضافية', slide_type='content'),
        'content_density': 'medium',
        'requires_image': False,
        'bullets': []
    }
    if slide_engine.resolve_offer_lang(project_data) == slide_engine.OFFER_LANG_ENGLISH:
        generic_slide['title'] = 'Additional details'
        generic_slide['design_style'] = _suggest_design_style('Additional details', slide_type='content')

    sys_prompt = build_system_prompt(project_data, images_info, dynamic_rules)
    return sys_prompt + '\n\n'.join(
        slide_engine.build_slide_user_msg(slides[i] if i < len(slides) else generic_slide, i + 1, slide_count, branding, project_data=project_data)
        for i in range(slide_count)
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Extract HTML from GLM response
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def extract_html_from_glm(raw_response):
    content = raw_response.get('choices', [{}])[0].get('message', {}).get('content', '')

    # Try to extract from code block first
    code_match = re.search(r'```(?:html)?\s*\n?([\s\S]*?)```', content)
    if code_match:
        html = code_match.group(1).strip()
        if 'class="slide"' in html:
            slides = extract_slide_elements(html)
            if slides:
                return '\n'.join(slides)

    # Keep only complete slide roots; discard AI prose/punctuation around them.
    slides = extract_slide_elements(content)
    if slides:
        return '\n'.join(slides)

    # Fallback: regex match (may miss deeply nested slides)
    slides_regex = re.findall(r'<div\s+class="slide"[\s\S]*?</div>\s*</div>\s*</div>\s*</div>', content)
    if slides_regex:
        return '\n'.join(slides_regex)

    if '<div' in content and 'class="slide"' in content:
        return content

    return content

def validate_html(html, expected_count=None):
    slide_count = html.count('class="slide"')
    threshold = expected_count
    if threshold is None:
        tenant_id = getattr(g, 'tenant_id', None)
        branding = db.get_branding(tenant_id) if tenant_id else {}
        _min_s, _max_s, threshold = resolve_slide_bounds(branding)
        threshold = max(_min_s, min(threshold, _max_s))
    if slide_count < threshold:
        print(f"[WARN] Only {slide_count} slides found, expected {threshold}")
    if 'dir="rtl"' not in html:
        html = html.replace('<div class="slide"', '<div class="slide" dir="rtl"')
    return html

def _extract_json_from_text(text):
    """Try to find a valid JSON object with 'action' key in text.
    Returns a dict or None."""
    # 1) Try parsing the entire response as JSON
    try:
        parsed = json.loads(text.strip())
        if isinstance(parsed, dict) and 'action' in parsed:
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    # 2) Try extracting from markdown code block
    cb = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)
    if cb:
        try:
            parsed = json.loads(cb.group(1).strip())
            if isinstance(parsed, dict) and 'action' in parsed:
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    # 3) Balanced-brace scan for the first complete JSON object
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
                            if isinstance(parsed, dict) and 'action' in parsed:
                                return parsed
                        except (json.JSONDecodeError, ValueError):
                            pass
                        break
    return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINT 1: Generate all slides HTML with GLM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/generate', methods=['POST'])
@require_permission('create_presentation')
def api_generate():
    data = request.json
    _billing_guard = _require_billing_balance('slide_plan')
    if _billing_guard is not None:
        return _billing_guard
    project_data = clean_project_data(data.get('projectData', {}))
    images = data.get('images', {})

    print(f"\n[GENERATE] Starting generation for: {project_data.get('projectName', 'Unknown')}")

    prompt = build_glm_prompt(project_data, images)
    print(f"[GENERATE] Prompt length: {len(prompt)} chars (4 batches)")

    try:
        response = call_zai_chat(prompt, "قم بإنشاء العرض التقديمي الكامل.", max_tokens=16000, usage_ctx=_usage_ctx_optional('slide', data))

        raw = extract_chat_content(response, "GENERATE")
        print(f"[GENERATE] GLM response: {len(raw)} chars")

        html = extract_html_from_glm(response)
        html = validate_html(html)

        slide_count = html.count('class="slide"')
        print(f"[GENERATE] Final HTML: {len(html)} chars, {slide_count} slides")
        return jsonify({'success': True, 'html': html})

    except Exception as e:
        print(f"[GENERATE ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINT 2: Generate images (1 cover + 4 moodboard)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/generate-images', methods=['POST'])
@require_permission('generate_images')
def api_generate_images():
    data = request.json
    _billing_guard = _require_billing_balance('image_generation')
    if _billing_guard is not None:
        return _billing_guard
    project_data = clean_project_data(data.get('projectData', {}))
    include_cover = data.get('includeCover', True) is not False
    reference_image = data.get('referenceImage') or project_data.get('cover') or project_data.get('mainImageData') or None

    project_name = project_data.get('project_name') or project_data.get('projectName') or 'مشروع'
    project_type = project_data.get('project_type') or project_data.get('projectType') or 'سكني'
    location = project_data.get('location_address') or project_data.get('location') or 'السعودية'

    branding = db.get_branding(g.tenant_id) if hasattr(g, 'tenant_id') and g.tenant_id else {}
    raw_count = data.get('count') or (branding.get('moodboard_count') if branding else 4) or 4
    try:
        target_count = max(1, min(20, int(raw_count)))
    except (ValueError, TypeError):
        target_count = 4

    print(f"\n[IMAGES] Generating {'1 cover + ' if include_cover else ''}{target_count} moodboard images for: {project_name}, ref: {'yes' if reference_image else 'no'}")

    images = {'cover': None, 'moodboard': []}

    # Meter every image against the requesting project: without the draft id
    # the spend lands outside the project total while still billing the key.
    img_ctx = _usage_ctx_optional('image', data)

    # 1. Cover image. The wizard requests moodboard-only images at its next step.
    if include_cover:
        print("[IMAGES] Generating cover image...")
        cover_prompt = f"Modern luxury {project_type} building in {location}, professional architectural photography, elegant design, high quality, no text, no watermark"
        images['cover'] = persist_generated_image(call_image_api(cover_prompt, usage_ctx=img_ctx), getattr(g, 'tenant_id', None))
        print(f"[IMAGES] Cover: {'OK' if images['cover'] else 'FAILED'}")

    # 2. Moodboard images — use reference image (main image) to maintain visual consistency
    ref_style = ', matching the architectural style, colors, and materials of the reference image provided' if reference_image else ''
    ref_note = 'CRITICAL: NO other buildings around the building — the building stands ALONE.'
    base_prompts = [
        f"Cover photo of {project_name} — a {project_type} building in {location}{ref_style}. {ref_note} Professional architectural photography, warm golden hour lighting, premium luxury facade, photorealistic.",
        f"Right-side facade view of {project_name} — the same building from the right angle. {ref_note} Clear sky background, professional architectural photography, showing the building's right side details, materials, and textures.{ref_style}",
        f"Left-side facade view of {project_name} — the same building from the left angle. {ref_note} Clear sky background, professional architectural photography, showing the building's left side details and design elements.{ref_style}",
        f"Aerial top-down view of {project_name} — bird's eye view of the building from above. {ref_note} Professional drone photography, showing the roof, overall building shape, and surrounding empty land.{ref_style}",
        f"Close-up architectural detail view of {project_name} — showing main entrance, glass balcony finishes, and premium stone cladding.{ref_style}",
        f"Night view of {project_name} — exterior building lighting and facade illumination at dusk.{ref_style}",
        f"Interior lobby and reception view of {project_name} — luxury indoor design and materials.{ref_style}",
        f"Landscape and garden surroundings of {project_name} — outdoor green areas, lighting, and pathways.{ref_style}",
        f"Sunset golden hour panoramic view of {project_name} with dramatic sky.{ref_style}",
        f"Architectural eye-level perspective of {project_name} facade and main gate.{ref_style}",
    ]
    moodboard_prompts = base_prompts[:target_count]
    while len(moodboard_prompts) < target_count:
        moodboard_prompts.append(f"Angle {len(moodboard_prompts)+1} view of {project_name} in {location}{ref_style}. Professional architectural photography.")

    for i, prompt in enumerate(moodboard_prompts):
        print(f"[IMAGES] Generating moodboard {i+1}/{target_count} (ref: {'yes' if reference_image else 'no'})...")
        if reference_image:
            img = persist_generated_image(call_image_api_with_reference(reference_image, prompt, usage_ctx=img_ctx), getattr(g, 'tenant_id', None))
        else:
            img = persist_generated_image(call_image_api(prompt, usage_ctx=img_ctx), getattr(g, 'tenant_id', None))
        images['moodboard'].append(img)
        print(f"[IMAGES] Moodboard {i+1}/{target_count}: {'OK' if img else 'FAILED'}")
        if i < len(moodboard_prompts) - 1:
            time.sleep(1)

    print(f"[IMAGES] Done. Cover: {'OK' if images['cover'] else 'FAIL'}, Moodboard: {sum(1 for x in images['moodboard'] if x)}/{target_count}")
    has_cover = bool(images['cover'])
    has_moodboard = any(images['moodboard'])
    requested_cover = include_cover
    # Only fail if nothing usable came back; otherwise preserve partial results with a warning.
    if requested_cover and not has_cover and not has_moodboard:
        if not _has_any_openrouter_key(tenant_id=getattr(g, 'tenant_id', None)):
            return jsonify({'success': False, 'error': 'مفتاح OpenRouter غير مُعدّ — يرجى إضافته في ملف .env', 'error_code': 'NO_API_KEY'}), 400
        return jsonify({'success': False, 'error': 'تعذر توليد الصور — تحقق من مفتاح OpenRouter ورصيده', 'error_code': 'IMAGE_FAILED'}), 400
    warning = None
    if requested_cover and not has_cover:
        warning = 'تعذر توليد صورة الغلاف — تم توليد المود بورد فقط'
    elif target_count and not has_moodboard:
        warning = 'تعذر توليد صور المود بورد — تم توليد الغلاف فقط'
    return jsonify({'success': True, 'images': images, 'warning': warning})

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINT 3: Export PDF
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/export-pdf', methods=['POST'])
@require_auth
def api_export_pdf():
    data = request.json
    # Accept both 'slidesHtml' (from designer) and 'html' (legacy)
    slides_html = data.get('slidesHtml', '') or data.get('html', '')
    project_name = data.get('projectName', 'project')

    print(f"\n[PDF] Exporting PDF for: {project_name}")

    if not slides_html:
        return jsonify({'success': False, 'error': 'No HTML provided'}), 400

    try:
        output_path = generate_pdf_with_playwright(slides_html, project_name, tenant_id=g.tenant_id)
        filename = os.path.basename(output_path)
        print(f"[PDF] Generated: {filename}")
        return jsonify({'success': True, 'url': f'/outputs/{filename}', 'filename': filename})
    except Exception as e:
        print(f"[PDF ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
