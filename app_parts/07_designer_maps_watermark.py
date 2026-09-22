

def _record_slide_vision_state(available, error='', source='edit'):
    _SLIDE_VISION_STATE.clear()
    _SLIDE_VISION_STATE.update({
        'available': bool(available),
        'error': str(error or '')[:300],
        'source': source,
        'checkedAt': db._utcnow().isoformat(timespec='seconds'),
    })


def _designer_creative_images(project_data, creative_images=None):
    """The cover, moodboard and map images of the open presentation.

    `clean_project_data()` strips `creativeImages`, `mainImageData` and `moodboardImages` from
    project data, so reading them off `project_data` could never work: an edited slide kept its
    `##MOODBOARD_IMAGE_N##` markers and rendered as empty cards. The client sends the images in
    `creativeImages`, and a draft carries them under `tenantCreativeImages`.
    """
    if isinstance(creative_images, dict) and creative_images:
        return creative_images
    nested = project_data.get('tenantCreativeImages') if isinstance(project_data, dict) else None
    return nested if isinstance(nested, dict) else {}


def resolve_designer_chat_placeholders(html_out, project_data, presentation_id, tenant_id,
                                       creative_images=None):
    """Resolve map and creative image placeholders to their actual URLs."""
    if not html_out or '<div' not in html_out:
        return html_out

    creative = _designer_creative_images(project_data, creative_images)

    # 1. Gather all map placeholders
    map_placeholders = {}
    supplied_maps = creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {}
    for placeholder, url in supplied_maps.items():
        if placeholder and url:
            map_placeholders[placeholder] = url
    
    draft_id = project_data.get('draft_id') or project_data.get('draftId') if isinstance(project_data, dict) else None
    db_maps = []
    if presentation_id:
        db_maps = db.get_map_images(tenant_id, presentation_id=presentation_id)
    elif draft_id:
        db_maps = db.get_map_images(tenant_id, draft_id=draft_id)
        
    for m in db_maps:
        placeholder = m.get('placeholder')
        path = m.get('file_path')
        if placeholder and path and os.path.exists(path):
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            if placeholder not in map_placeholders:
                map_placeholders[placeholder] = f"/{rel_path}"
                
    # Missing maps remain placeholders. Map generation belongs to the explicit
    # map workflow, never to a chat/edit request.

    # 2. Replace map placeholders in HTML
    for placeholder, url in map_placeholders.items():
        if url:
            html_out = html_out.replace(placeholder, url)

    # 3. Replace creative image placeholders (cover & moodboard)
    cover_url = (creative.get('cover') or creative.get('mainImageData')
                 or project_data.get('cover') or project_data.get('mainImageData') or '')
    moodboard = (creative.get('moodboard') or project_data.get('moodboard')
                 or project_data.get('moodboardImages') or [])
    
    if cover_url:
        html_out = html_out.replace('##IMAGE_COVER##', cover_url)
        html_out = html_out.replace('##COVER_IMAGE##', cover_url)
        html_out = html_out.replace('##MAIN_IMAGE##', cover_url)
        
    if isinstance(moodboard, list):
        for idx, mb_img in enumerate(moodboard):
            if mb_img:
                html_out = html_out.replace(f'##MOODBOARD_IMAGE_{idx + 1}##', mb_img)

    # An edited slide goes to the reader as it is, so a token with no image behind it must not
    # survive as an empty frame here either.
    return slide_engine._drop_unresolved_image_placeholders(html_out)


def _designer_json_response(text):
    """Parse the first JSON object returned by the designer model, with fallback extraction."""
    if not text:
        return {}
    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    match = re.search(r'\{[\s\S]*\}', cleaned)
    if match:
        try:
            value = json.loads(match.group(0))
            if isinstance(value, dict):
                return value
        except Exception:
            pass
    # Resilient fallback: extract "html" and "response" fields manually if JSON broken by quotes/newlines
    html_match = re.search(r'"(?:html|slide_html|content)"\s*:\s*"([\s\S]*?)(?<!\\)"\s*,\s*"(?:response|reply)"', cleaned)
    if not html_match:
        html_match = re.search(r'"(?:html|slide_html|content)"\s*:\s*"([\s\S]*?)(?<!\\)"\s*\}', cleaned)
    if html_match:
        extracted_html = html_match.group(1).replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
        resp_match = re.search(r'"(?:response|reply)"\s*:\s*"([\s\S]*?)(?<!\\)"', cleaned)
        resp_text = resp_match.group(1).replace('\\"', '"').replace('\\n', '\n') if resp_match else 'تم تحديث الشريحة بنجاح.'
        return {'html': extracted_html, 'response': resp_text}
    # Direct HTML slide block fallback
    div_match = re.search(r'<div\b[^>]*class=["\']slide["\'][\s\S]*?</div>\s*$', cleaned, flags=re.IGNORECASE)
    if div_match:
        return {'html': div_match.group(0), 'response': 'تم تحديث الشريحة بنجاح.'}
    return {}


def normalize_arabic_digits_py(text):
    if not text:
        return ""
    eastern = "٠١٢٣٤٥٦٧٨٩"
    western = "0123456789"
    return text.translate(str.maketrans(eastern, western))


def _slide_range_indexes(text, count):
    """Return zero-based indexes for numeric ranges such as «من 2 إلى 6»."""
    if not text or count <= 0:
        return []
    normalized = normalize_arabic_digits_py(text.lower())
    indexes = []
    for match in re.finditer(r'(?<!\d)(\d+)\s*(?:إلى|الى|حتى|لحد|[-–—])\s*(\d+)(?!\d)', normalized):
        start, end = int(match.group(1)), int(match.group(2))
        if start > end:
            start, end = end, start
        for number in range(start, end + 1):
            index = number - 1
            if 0 <= index < count and index not in indexes:
                indexes.append(index)
    return indexes


def detect_slide_indexes_from_message_py(text, slides):
    """Detect single or multiple slide indexes from prompt text using dynamic digits, words, or titles."""
    if not text or not slides:
        return []

    norm_text = normalize_arabic_digits_py(text.strip().lower())
    count = len(slides)
    found_indexes = []

    # 1. Check ordinal word phrases
    word_map = [
        ('الحادية عشر', 11), ('الحاديه عشر', 11),
        ('الثانية عشر', 12), ('الثانيه عشر', 12),
        ('الثالثة عشر', 13), ('الثالثه عشر', 13),
        ('الرابعة عشر', 14), ('الرابعه عشر', 14),
        ('الخامسة عشر', 15), ('الخامسه عشر', 15),
        ('السادسة عشر', 16), ('السادسه عشر', 16),
        ('السابعة عشر', 17), ('السابعه عشر', 17),
        ('الثامنة عشر', 18), ('الثامنه عشر', 18),
        ('التاسعة عشر', 19), ('التاسعه عشر', 19),
        ('الأولى', 1), ('الاولى', 1), ('الأول', 1), ('الاول', 1),
        ('الثانية', 2), ('الثانيه', 2), ('الثاني', 2),
        ('الثالثة', 3), ('الثالثه', 3), ('الثالث', 3),
        ('الرابعة', 4), ('الرابعه', 4), ('الرابع', 4),
        ('الخامسة', 5), ('الخامسه', 5), ('الخامس', 5),
        ('السادسة', 6), ('السادسه', 6), ('السادس', 6),
        ('السابعة', 7), ('السابعه', 7), ('السابع', 7),
        ('الثامنة', 8), ('الثامنه', 8), ('الثامن', 8),
        ('التاسعة', 9), ('التاسعه', 9), ('التاسع', 9),
        ('العاشرة', 10), ('العاشره', 10), ('العاشر', 10),
        ('العشرين', 20), ('العشرون', 20),
        ('الثلاثين', 30), ('الثلاثون', 30)
    ]

    for word, num in word_map:
        if word in norm_text:
            idx = num - 1
            if 0 <= idx < count and idx not in found_indexes:
                found_indexes.append(idx)

    # 2. Expand numeric ranges before extracting individual numbers. The old parser stopped at
    # the first number in «من 2 إلى 6», so a request for a bounded group silently edited one slide.
    for idx in _slide_range_indexes(norm_text, count):
        if idx not in found_indexes:
            found_indexes.append(idx)

    # 3. Extract digits after trigger words (شريحة, شرايح, سلايد, رقم) or lists like "7 و 9 و 20"
    trigger_match = re.search(r'(?:الشريحة|شريحة|شريحه|شرايح|سلايد|سلايدات|رقم|الأرقام|ارقام)\s*([\d\s\,\،و]+)', norm_text)
    if trigger_match:
        digit_str = trigger_match.group(1)
        raw_numbers = re.findall(r'\b\d+\b', digit_str)
        for num_s in raw_numbers:
            try:
                num = int(num_s)
                idx = num - 1
                if 0 <= idx < count and idx not in found_indexes:
                    found_indexes.append(idx)
            except ValueError:
                continue

    # Fallback to any standalone numbers in the message if no trigger matched
    if not found_indexes:
        raw_numbers = re.findall(r'\b\d+\b', norm_text)
        for num_s in raw_numbers:
            try:
                num = int(num_s)
                idx = num - 1
                if 0 <= idx < count and idx not in found_indexes:
                    found_indexes.append(idx)
            except ValueError:
                continue

    # 4. Check slide title and section matches
    if not found_indexes:
        norm_clean = re.sub(r'[^\w\s]', ' ', norm_text)
        sec_aliases = {
            'executive_summary': ['الملخص التنفيذي', 'ملخص تنفيذي', 'الملخص'],
            'financial': ['الدراسة المالية', 'التحليل المالي', 'الجانب المالي', 'دراسة مالية', 'المالية'],
            'location': ['تحليل الموقع', 'موقع المشروع', 'خريطة الموقع', 'الموقع'],
            'land': ['تحليل الأرض', 'كروكي الأرض', 'بيانات الأرض', 'الأرض', 'الارض'],
            'market': ['تحليل السوق', 'دراسة السوق', 'السوق'],
            'overview': ['نبذة عن المشروع', 'مقدمة المشروع', 'عن المشروع'],
            'components': ['مكونات المشروع', 'عناصر المشروع', 'المكونات'],
            'swot_risks': ['تحليل المخاطر', 'مصفوفة المخاطر', 'المخاطر', 'سوات', 'swot'],
            'timeline': ['الجدول الزمني', 'مراحل المشروع', 'الجدول'],
            'team': ['فريق العمل', 'فريق المشروع'],
            'visual_concept': ['التصور البصري', 'الهوية البصرية', 'الرؤية البصرية'],
            'cover': ['الغلاف', 'شريحة الغلاف'],
            'conclusion': ['الخاتمة', 'شريحة الختام'],
        }
        for idx, s in enumerate(slides):
            if not isinstance(s, dict):
                continue
            title = (s.get('title') or '').strip().lower()
            clean_title = re.sub(r'[^\w\s]', ' ', title).strip()
            if len(clean_title) >= 3 and (clean_title in norm_clean or any(part in norm_clean for part in clean_title.split(' - ') if len(part.strip()) >= 4)):
                if idx not in found_indexes:
                    found_indexes.append(idx)
                    break
            title_words = [w for w in clean_title.split() if len(w) >= 3 and w not in ('شريحة', 'صفحة', 'عرض', 'مشروع')]
            if len(title_words) >= 2:
                phrase = ' '.join(title_words[:2])
                if phrase in norm_clean and idx not in found_indexes:
                    found_indexes.append(idx)
                    break
            sec_key = (s.get('section_key') or s.get('sectionKey') or '').strip().lower()
            if sec_key and sec_key in sec_aliases:
                for alias in sec_aliases[sec_key]:
                    if alias in norm_clean:
                        if idx not in found_indexes:
                            found_indexes.append(idx)
                            break
                if found_indexes:
                    break

    return found_indexes


def detect_slide_from_message_py(text, slides):
    indexes = detect_slide_indexes_from_message_py(text, slides)
    return indexes[0] if indexes else -1


def _designer_target_indexes(action, count, current_index, force_all=False):
    """Resolve explicit targets without redirecting invalid numbers to another slide."""
    if force_all:
        return list(range(count))
    params = action.get('params') if isinstance(action.get('params'), dict) else action
    return designer_chat_targets.resolve_indexes(params, count, current_index)


def _designer_actionable_edit_request(message):
    """Identify a concrete edit that should not be stalled by a needless clarification."""
    normalized = normalize_arabic_digits_py(str(message or '').lower())
    return bool(re.search(
        r'(?:لون|ألوان|الوان|خلفي|خط|عنوان|نص|هيدر|فوتر|بطاق|كارت|مساف|تباعد|حجم|عرض|ارتفاع|محاذاة|تنسيق|ترقيم|رقم|إزاحة|ازاحة|يمين|يسار|أعلى|اعلى|أسفل|اسفل|تصميم)',
        normalized,
    ))


_CANONICAL_MAP_TOKENS = {
    'overview': '##MAP_OVERVIEW##',
    'access': '##MAP_ACCESS##',
    'catchment': '##MAP_CATCHMENT##',
    'landmarks': '##MAP_LANDMARKS##',
}


def _canonical_map_type_for_slide(slide):
    """Infer the canonical map owned by a slide without asking the model."""
    item = slide if isinstance(slide, dict) else {}
    slide_type = str(item.get('type') or '').strip().lower()
    source = str(item.get('content_source') or item.get('contentSource') or '').strip().lower()
    title = normalize_arabic_digits_py(str(item.get('title') or '').strip().lower())
    raw_html = str(item.get('html') or '')
    html = raw_html.upper()

    explicit_map = re.search(
        r'data-canonical-map\s*=\s*["\'](overview|access|catchment|landmarks)["\']',
        raw_html, flags=re.IGNORECASE,
    )
    if explicit_map:
        return explicit_map.group(1).lower()

    for map_type in ('overview', 'access', 'catchment', 'landmarks'):
        if slide_type == f'map_{map_type}' or source in {
            map_type,
            f'{map_type}_areas',
            f'{map_type}_landmarks',
            f'{map_type}_roads',
        }:
            return map_type
        if _CANONICAL_MAP_TOKENS[map_type] in html:
            return map_type

    if any(term in title for term in ('النطاق الجغرافي', 'نطاق التأثير', 'استيعاب المنطقة', 'منطقة الخدمة')):
        return 'catchment'
    if any(term in title for term in ('الوصول', 'شبكة الطرق', 'الطرق الرئيسية', 'المحاور')):
        return 'access'
    if any(term in title for term in ('المعالم', 'الخدمات القريبة', 'أوقات القيادة')):
        return 'landmarks'
    if any(term in title for term in ('الموقع العام', 'خريطة الموقع', 'خريطة الأرض', 'النظرة العامة')):
        return 'overview'
    return ''


def _approved_canonical_map_url(map_type, project_data, creative_images=None):
    """Return only the already-persisted map; this helper never calls a map provider."""
    map_type = str(map_type or '').strip().lower()
    token = _CANONICAL_MAP_TOKENS.get(map_type)
    if not token:
        return ''
    creative = _designer_creative_images(project_data, creative_images)
    placeholders = creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {}
    approvals = creative.get('map_approvals') if isinstance(creative.get('map_approvals'), dict) else {}
    if map_type in approvals:
        approved = approvals.get(map_type)
        if not (approved is True or (isinstance(approved, str) and approved.strip().lower() in {'true', '1', 'yes'})):
            return ''
    base = token[:-2]
    for candidate in (token, f'{base}_SATELLITE##', f'{base}_ROADMAP##'):
        value = placeholders.get(candidate)
        if value and not str(value).startswith('##'):
            return str(value)
    return ''


def _latest_canonical_map_url(map_type, project_data, creative_images=None,
                              tenant_id=None, presentation_id=None, preferred_images=None):
    """Return the newest saved final map for an explicit chat refresh.

    A map edit deliberately releases that map's approval until the user reviews
    it again. That is correct for the workflow, but it must not make an explicit
    "update the map in this slide" request keep the old raster image. This helper
    therefore ignores the approval flag, never calls Google, and prefers the
    current marked image from the project section over presentation snapshots.
    The sidecar is never a candidate here.
    """
    map_type = str(map_type or '').strip().lower()
    token = _CANONICAL_MAP_TOKENS.get(map_type)
    if not token:
        return ''

    canonical_types = {map_type, f'{map_type}_satellite', f'{map_type}_roadmap'}

    def usable_map_url(value):
        value = str(value or '').strip()
        if not value or value.startswith('##'):
            return False
        parsed = urlsplit(value)
        if parsed.path.startswith('/uploads/maps/'):
            relative = parsed.path.removeprefix('/uploads/maps/').replace('/', os.sep)
            maps_root = os.path.abspath(os.path.join(UPLOADS_DIR, 'maps'))
            candidate = os.path.abspath(os.path.join(maps_root, relative))
            if candidate != maps_root and not candidate.startswith(maps_root + os.sep):
                return False
            return os.path.isfile(candidate)
        # There is no live /api/map-images route.  Treating one as usable made
        # an old client URL win over the real persisted file and rendered a blank frame.
        if parsed.path.startswith('/api/map-images/'):
            return False
        # The browser must never receive a server filesystem path (for example
        # ``C:\\...`` or ``D:\\...``) as an image source.  It is not a URL and
        # silently renders as a missing image, while the persisted map row below
        # already has the public upload path we need.  Canonical maps are either
        # served from our map route or inline image data.  External map URLs are
        # deliberately excluded: an explicit refresh must copy the saved marked
        # raster, never a stale Google/CDN URL that can disappear or render a
        # different map after the response reaches the browser.
        if value.startswith('data:image/'):
            return True
        return False

    def public_map_url(file_path):
        """Convert a persisted map file to the only public route that serves it."""
        if not file_path or not os.path.isfile(file_path):
            return ''
        maps_root = os.path.realpath(os.path.join(UPLOADS_DIR, 'maps'))
        service_maps_root = os.path.realpath(getattr(maps_service, 'MAPS_DIR', maps_root))
        candidate = os.path.realpath(file_path)
        in_upload_maps = candidate == maps_root or candidate.startswith(maps_root + os.sep)
        in_service_maps = candidate == service_maps_root or candidate.startswith(service_maps_root + os.sep)
        if not (in_upload_maps or in_service_maps):
            return ''
        return '/uploads/maps/' + os.path.basename(candidate)

    # The location section is the source of truth for the image the user has just
    # approved or edited.  It is sent separately from project_data by the browser,
    # so prefer it before consulting map_images, whose rows can belong to an older
    # presentation snapshot.  This is only a file selection; it never generates a map.
    preferred_sources = list(preferred_images or [])
    preferred_sources.extend([creative_images, (project_data or {}).get('tenantCreativeImages')])
    for source in preferred_sources:
        if not isinstance(source, dict):
            continue
        placeholders = source.get('map_placeholders') if isinstance(source.get('map_placeholders'), dict) else {}
        base = token[:-2]
        for candidate in (token, f'{base}_SATELLITE##', f'{base}_ROADMAP##'):
            value = placeholders.get(candidate)
            if usable_map_url(value):
                return str(value)

    draft_id = (project_data or {}).get('draftId') or (project_data or {}).get('draft_id')
    if tenant_id and (presentation_id or draft_id):
        try:
            rows = db.get_map_images(
                tenant_id,
                presentation_id=presentation_id,
                draft_id=draft_id if not presentation_id else None,
            )
        except Exception:
            rows = []
        for row in rows:
            if row.get('image_type') not in canonical_types:
                continue
            path = row.get('file_path')
            public_url = public_map_url(path)
            if public_url:
                return public_url

    # Compatibility fallback for an unsaved draft or a request carrying a map
    # that has not yet been written to map_images.
    sources = []
    nested = project_data.get('tenantCreativeImages') if isinstance(project_data, dict) else None
    if isinstance(nested, dict):
        sources.append(nested)
    if isinstance(creative_images, dict) and creative_images not in sources:
        sources.append(creative_images)
    base = token[:-2]
    candidates = (token, f'{base}_SATELLITE##', f'{base}_ROADMAP##')
    for creative in sources:
        placeholders = creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {}
        for candidate in candidates:
            value = placeholders.get(candidate)
            if usable_map_url(value):
                return str(value)
    return ''


def _persisted_map_source_marks(tenant_id, presentation_id=None, draft_id=None):
    """Index each persisted map file by every marker a stored slide may carry.

    Saving a presentation freezes /uploads/maps/ sources into
    /uploads/creative/<tenant>/revisions/<sha256>.<ext>, so a stored slide can
    reference a map through a URL with nothing map-like in it. Each file is
    indexed by its public basename and by its content digest (the frozen
    filename), letting a chat map update find the existing slot even inside a
    frozen revision URL.
    """
    marks = {}
    if not tenant_id:
        return marks
    try:
        rows = db.get_map_images(
            tenant_id, presentation_id=presentation_id,
            draft_id=None if presentation_id else draft_id)
    except Exception:
        rows = []
    for row in rows:
        image_type = str(row.get('image_type') or '').strip().lower()
        map_type = next(
            (name for name in _CANONICAL_MAP_TOKENS
             if image_type == name or image_type.startswith(name + '_')),
            '')
        path = str(row.get('file_path') or '')
        if not map_type or not os.path.isfile(path):
            continue
        info = {'type': map_type, 'image_type': image_type, 'path': path, 'digest': ''}
        basename = os.path.basename(path)
        if basename:
            marks.setdefault(basename, info)
            marks.setdefault(basename.lower(), info)
        try:
            with open(path, 'rb') as handle:
                info['digest'] = hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            continue
        marks.setdefault(info['digest'], info)
    return marks


def _tag_map_source_info(tag, map_marks):
    """Return the persisted-map record an HTML tag references, if any."""
    if not map_marks:
        return None
    for segment in re.findall(r'([\w.-]+\.(?:png|jpe?g|webp|gif|avif|svg))',
                              tag, flags=re.IGNORECASE):
        info = map_marks.get(segment) or map_marks.get(segment.rsplit('.', 1)[0])
        if info:
            return info
    return None


def _replace_slide_with_approved_map(html, map_type, map_url, map_marks=None):
    """Replace a slide's map media with one approved image and remove duplicate map tags."""
    if not html or not map_url:
        return html, False
    token = _CANONICAL_MAP_TOKENS.get(str(map_type or '').strip().lower())
    if not token:
        return html, False

    base = token[:-2]
    map_tokens = (token, f'{base}_SATELLITE##', f'{base}_ROADMAP##')
    output = str(html)
    for candidate in map_tokens:
        output = output.replace(candidate, map_url)

    map_ref = re.compile(r'(?:/uploads/maps/|/api/map-images/|maps/|##map_)', re.IGNORECASE)
    map_url_ref = str(map_url).lower()
    attr_re = re.compile(r'data-canonical-map\s*=\s*["\']([\w-]+)', re.IGNORECASE)
    media_tags = []
    tag_pattern = re.compile(r'<[a-z][^>]*>|</(?:div|section|figure|main)\s*>', re.IGNORECASE)
    # The saved slide can carry the map through a frozen revision URL that no
    # map-looking path survives in, so the canonical container attribute and the
    # persisted-file marks decide what counts as this map type's media.
    canonical_depth = 0
    for match in tag_pattern.finditer(output):
        tag = match.group(0)
        lowered = tag.lower()
        if lowered.startswith('</'):
            if canonical_depth:
                canonical_depth -= 1
            continue
        attr = attr_re.search(tag)
        opens_canonical = bool(attr) and attr.group(1).lower() == map_type
        in_canonical = canonical_depth > 0
        if lowered.startswith(('<div', '<section', '<figure', '<main')):
            if in_canonical:
                canonical_depth += 1
            elif opens_canonical:
                canonical_depth = 1
        is_image = lowered.startswith('<img')
        marked_info = _tag_map_source_info(lowered, map_marks)
        marked = bool(marked_info) and marked_info['type'] == map_type
        own_slot = in_canonical or opens_canonical or marked
        is_map_background = (
            'data-map-summary-background' in lowered
            or bool(re.search(r'background(?:-image)?\s*:\s*url\(', lowered)
                    and (map_ref.search(lowered) or own_slot))
        )
        if is_image and (map_ref.search(lowered) or map_url_ref in lowered or own_slot):
            media_tags.append(('image', match))
        elif is_map_background:
            media_tags.append(('background', match))

    changed = False
    if media_tags:
        # A map slide can contain both a legacy background placeholder on the
        # root element and the real image slot inside its content grid.  The
        # root background is covered by the slide's white content surface, so
        # prefer an image element whenever one exists.  Selecting the first
        # tag blindly made the refresh appear successful while leaving the
        # visible image slot empty.
        image_media = [(kind, match) for kind, match in media_tags if kind == 'image']
        dedicated_backgrounds = [
            (kind, match) for kind, match in media_tags
            if kind == 'background' and re.search(
                r'data-canonical-map\s*=|data-map-summary-background\b',
                match.group(0),
                flags=re.IGNORECASE,
            )
        ]
        # Newer map slides use a dedicated background layer inside the map
        # panel.  It is more authoritative than the legacy root background,
        # which is normally covered by the slide content surface.
        first_kind, first = (
            image_media[0] if image_media else
            dedicated_backgrounds[0] if dedicated_backgrounds else
            media_tags[0]
        )
        first_tag = first.group(0)
        if first_kind == 'image':
            src_pattern = re.compile(r'(\bsrc\s*=\s*)(["\'])(.*?)(\2)', re.IGNORECASE | re.DOTALL)
            if src_pattern.search(first_tag):
                first_tag = src_pattern.sub(lambda m: f'{m.group(1)}{m.group(2)}{map_url}{m.group(4)}', first_tag, count=1)
            else:
                first_tag = re.sub(r'\s*/>$', '>', first_tag)
                first_tag = first_tag[:-1] + f' src="{map_url}">'
        else:
            background_pattern = re.compile(
                r'(background(?:-image)?\s*:\s*url\(\s*["\']?)([^)"\']+)(["\']?\s*\))',
                re.IGNORECASE,
            )
            first_tag = background_pattern.sub(
                lambda m: f'{m.group(1)}{map_url}{m.group(3)}', first_tag, count=1
            )
        if 'data-canonical-map=' not in first_tag.lower():
            first_tag = re.sub(r'\s*/>$', '>', first_tag)
            first_tag = first_tag[:-1] + f' data-canonical-map="{map_type}">'
        replacements = [(first.start(), first.end(), first_tag)]
        for kind, match in media_tags:
            if match is first:
                continue
            if kind == 'image':
                # There must be one visible canonical image, not a stack of
                # old and new rasters in the same slide.
                replacements.append((match.start(), match.end(), ''))
            else:
                # Keep the element itself intact.  Removing only its opening
                # tag can unbalance the HTML, and a duplicate background is
                # unnecessary once the visible image slot is authoritative.
                background_tag = match.group(0)
                background_tag = re.sub(
                    r'(background(?:-image)?\s*):\s*url\([^)]*\)',
                    lambda m: f'{m.group(1)}:none',
                    background_tag,
                    count=1,
                    flags=re.IGNORECASE,
                )
                replacements.append((match.start(), match.end(), background_tag))
        # Sort by source position because the visible image is often after
        # the root background in the tag list.  Applying an earlier, shorter
        # replacement first would invalidate the later match offsets.
        for start, end, value in sorted(replacements, key=lambda item: item[0], reverse=True):
            output = output[:start] + value + output[end:]
        changed = True
    elif token in output or map_url in output:
        changed = map_url in output
    else:
        closing = re.search(r'</div>\s*$', output, re.IGNORECASE)
        if closing:
            map_markup = (
                f'<div data-canonical-map="{map_type}" style="position:absolute;left:40px;right:40px;'
                f'top:120px;bottom:70px;z-index:1;display:flex;align-items:center;justify-content:center;overflow:hidden;">'
                f'<img src="{map_url}" alt="" style="width:100%;height:100%;object-fit:contain;object-position:center center;"></div>'
            )
            output = output[:closing.start()] + map_markup + output[closing.start():]
            changed = True

    return output, changed


def _refresh_slide_map_sources(html, project_data, tenant_id, presentation_id=None,
                               creative_images=None):
    """Point persisted-map sources in a rebuilt slide at the current map files.

    A stored slide freezes map sources into /uploads/creative/<tenant>/
    revisions/<digest>.<ext>, so a slide the model rebuilds while keeping its
    old <img> keeps the old map even after the project map changed. Any source
    that resolves to a persisted map file of a canonical type is rewritten to
    that type's current image — the same target an explicit chat refresh or a
    ##MAP_*## token resolves to — and the rewritten tag is stamped with
    data-canonical-map so later updates keep finding the slot.
    """
    if not html or not tenant_id:
        return html
    if not re.search(r'data-canonical-map|/revisions/|/uploads/maps/|/api/map-images/',
                     html, re.IGNORECASE):
        return html
    draft_id = (project_data or {}).get('draftId') or (project_data or {}).get('draft_id') \
        if isinstance(project_data, dict) else None
    marks = _persisted_map_source_marks(
        tenant_id, presentation_id=presentation_id,
        draft_id=None if presentation_id else draft_id)
    if not marks:
        return html

    targets = {}

    def current_for(map_type):
        if map_type not in targets:
            targets[map_type] = _latest_canonical_map_url(
                map_type, project_data, creative_images,
                tenant_id=tenant_id, presentation_id=presentation_id) or ''
        return targets[map_type]

    def source_info(url):
        segment = urlsplit(str(url or '').strip()).path.rsplit('/', 1)[-1]
        if not segment:
            return None
        return marks.get(segment) or marks.get(segment.rsplit('.', 1)[0])

    def target_same_file(info, target):
        """True when the current target is the same file the slide already has."""
        if not target or target.startswith('data:'):
            return True
        target_info = source_info(target)
        return bool(target_info and info['digest'] and target_info['digest'] == info['digest'])

    src_re = re.compile(r'(\bsrc\s*=\s*)(["\'])(.*?)(\2)', re.IGNORECASE | re.DOTALL)
    bg_re = re.compile(r'(background(?:-image)?\s*:\s*url\(\s*["\']?)([^)"\']+)(["\']?\s*\))',
                       re.IGNORECASE)

    def refresh_tag(match):
        tag = match.group(0)
        if 'src' not in tag and 'url(' not in tag:
            return tag
        swapped_type = ['']

        def sub_src(m):
            info = source_info(m.group(3))
            if not info:
                return m.group(0)
            target = current_for(info['type'])
            if not target or target_same_file(info, target):
                return m.group(0)
            swapped_type[0] = info['type']
            return m.group(1) + m.group(2) + target + m.group(4)

        def sub_bg(m):
            info = source_info(m.group(2))
            if not info:
                return m.group(0)
            target = current_for(info['type'])
            if not target or target_same_file(info, target):
                return m.group(0)
            return m.group(1) + target + m.group(3)

        out = src_re.sub(sub_src, tag)
        out = bg_re.sub(sub_bg, out)
        if swapped_type[0] and out.startswith('<img') \
                and 'data-canonical-map' not in out.lower():
            stamp = f' data-canonical-map="{swapped_type[0]}"'
            out = out[:-2] + stamp + '/>' if out.endswith('/>') else out[:-1] + stamp + '>'
        return out

    return re.sub(r'<[a-z][^>]*>', refresh_tag, html, flags=re.IGNORECASE)


def _designer_image_assets(creative_images):
    """Enumerate the project's visual assets as token/url/label/family rows.

    The chat planner sees creative_images as raw JSON, so it guesses token
    names and invents ones that do not exist (##AERIAL_IMAGE_3##). The rows
    here are the same assets the slide generator enumerates, so a refresh
    request can name an exact token and resolve it deterministically.
    """
    assets = []
    if not isinstance(creative_images, dict) or not creative_images:
        return assets
    cover, moodboard = slide_engine._creative_image_values(creative_images)
    if cover:
        assets.append({'token': '##IMAGE_COVER##', 'url': cover,
                       'label': 'الصورة الرئيسية المعتمدة', 'family': 'cover'})
    moodboard_meta = creative_images.get('moodboard_meta')
    moodboard_meta = moodboard_meta if isinstance(moodboard_meta, list) else []
    for index, url in enumerate(moodboard, 1):
        if not url:
            continue
        meta = moodboard_meta[index - 1] if index - 1 < len(moodboard_meta) \
            and isinstance(moodboard_meta[index - 1], dict) else {}
        label = str(meta.get('label') or f'التصور الخارجي {index}').strip()
        caption = str(meta.get('caption') or '').strip()
        assets.append({'token': f'##MOODBOARD_IMAGE_{index}##', 'url': url,
                       'label': label + (f' — {caption}' if caption else ''),
                       'family': 'moodboard'})
    components = creative_images.get('interior_components') or []
    for c_idx, comp in enumerate(components if isinstance(components, list) else [], 1):
        if not isinstance(comp, dict):
            continue
        comp_name = str(comp.get('name') or f'المكون {c_idx}').strip()
        for i_idx, item in enumerate(comp.get('images') or [], 1):
            url = item.get('url', '') if isinstance(item, dict) else str(item or '')
            if not url:
                continue
            label = str(item.get('label') or comp_name).strip() if isinstance(item, dict) else comp_name
            assets.append({'token': f'##INTERIOR_COMP_{c_idx}_IMG_{i_idx}##', 'url': url,
                           'label': f'{comp_name} — {label}', 'family': 'interior'})
    interiors = creative_images.get('interior') or creative_images.get('interior_images') or []
    if not isinstance(interiors, list):
        interiors = [interiors]
    for index, url in enumerate(interiors, 1):
        if url:
            assets.append({'token': f'##INTERIOR_IMAGE_{index}##', 'url': str(url),
                           'label': f'التصور الداخلي {index}', 'family': 'interior'})
    plans = creative_images.get('plans') or creative_images.get('plans2d') or []
    if not isinstance(plans, list):
        plans = [plans]
    plan_meta = creative_images.get('plan_meta')
    plan_meta = plan_meta if isinstance(plan_meta, list) else []
    for index, item in enumerate(plans, 1):
        url = (item.get('url') or item.get('imageUrl') or item.get('image_url')
               or item.get('path') or '') if isinstance(item, dict) else str(item or '')
        if not url:
            continue
        meta = plan_meta[index - 1] if index - 1 < len(plan_meta) \
            and isinstance(plan_meta[index - 1], dict) else {}
        label = str(meta.get('title') or meta.get('name') or f'المخطط {index}').strip()
        assets.append({'token': f'##PLAN_IMAGE_{index}##', 'url': str(url),
                       'label': label, 'family': 'plan'})
    land_photos = creative_images.get('land_photos') or []
    for index, item in enumerate(land_photos if isinstance(land_photos, list) else [], 1):
        source = item if isinstance(item, dict) else {'url': item}
        url = str(source.get('url') or source.get('imageUrl') or '').strip()
        if not url:
            continue
        label = str(source.get('name') or f'صورة الأرض {index}').strip()
        assets.append({'token': f'##LAND_PHOTO_{index}##', 'url': url,
                       'label': label, 'family': 'land'})
    return assets


def _designer_image_asset_url(token, assets):
    """Resolve a planner-supplied asset reference to its current URL."""
    normalized = re.sub(r'#+', '', str(token or '')).strip().upper().replace('-', '_').replace(' ', '_')
    if not normalized:
        return '', None
    for asset in assets:
        if normalized == asset['token'].strip('#').upper():
            return asset['url'], asset
    return '', None


def _set_tag_asset_token(tag, asset_token):
    """Set or replace the data-asset-token attribute on an HTML tag."""
    attr = f'data-asset-token="{asset_token}"'
    if re.search(r'\bdata-asset-token\s*=', tag, re.IGNORECASE):
        return re.sub(r'\bdata-asset-token\s*=\s*["\'][^"\']*["\']', attr, tag,
                      count=1, flags=re.IGNORECASE)
    if tag.endswith('/>'):
        return tag[:-2] + ' ' + attr + '/>'
    return tag[:-1] + ' ' + attr + '>'


def _replace_slide_image_with_asset(html, asset_url, asset_token='', image_index=None):
    """Swap one of a slide's images for a project asset, in place.

    Chat image refresh used to go through the model, which invented token
    names that resolved to nothing. The swap is deterministic: chrome, logos,
    watermarks and canonical maps are skipped; an explicit image_index (1-based
    document order) wins, then a tag stamped by an earlier asset update, then
    the first image whose source already points at a stored project asset,
    then simply the first image. With no <img> at all, a background-image tag
    is swapped, and failing both an image box is appended before </div>.
    """
    if not html or not asset_url:
        return html, False
    output = str(html)
    skip = re.compile(
        r'presentation-chrome-logo|slide-watermark|data-slide-watermark|'
        r'data-team-logo|data-company-logo|data-designer-managed-logos|\blogo\b',
        re.IGNORECASE)
    tag_pattern = re.compile(r'<[a-z][^>]*>|</(?:div|section|figure|main)\s*>', re.IGNORECASE)
    images = []
    backgrounds = []
    canonical_depth = 0
    for match in tag_pattern.finditer(output):
        tag = match.group(0)
        lowered = tag.lower()
        if lowered.startswith('</'):
            if canonical_depth:
                canonical_depth -= 1
            continue
        if lowered.startswith(('<div', '<section', '<figure', '<main')):
            if canonical_depth:
                canonical_depth += 1
            elif 'data-canonical-map' in lowered:
                canonical_depth = 1
        if canonical_depth or skip.search(lowered):
            continue
        if lowered.startswith('<img'):
            images.append(match)
        elif re.search(r'background(?:-image)?\s*:\s*url\(', lowered):
            backgrounds.append(match)

    target = None
    kind = ''
    if images:
        if isinstance(image_index, int) and 1 <= image_index <= len(images):
            target, kind = images[image_index - 1], 'image'
        else:
            stamped = [m for m in images if 'data-asset-token' in m.group(0).lower()]
            if stamped:
                target, kind = stamped[0], 'image'
            elif len(images) == 1:
                target, kind = images[0], 'image'
            else:
                assetish = [m for m in images if re.search(
                    r'/uploads/|/api/project-files/|data:image', m.group(0), re.IGNORECASE)]
                target, kind = (assetish or images)[0], 'image'
    elif backgrounds:
        index = image_index if isinstance(image_index, int) else 1
        if 1 <= index <= len(backgrounds):
            target, kind = backgrounds[index - 1], 'background'

    if target is not None:
        tag = target.group(0)
        if kind == 'image':
            src_pattern = re.compile(r'(\bsrc\s*=\s*)(["\'])(.*?)(\2)', re.IGNORECASE | re.DOTALL)
            if src_pattern.search(tag):
                tag = src_pattern.sub(
                    lambda m: f'{m.group(1)}{m.group(2)}{asset_url}{m.group(4)}', tag, count=1)
            else:
                tag = re.sub(r'\s*/>$', '>', tag)
                tag = tag[:-1] + f' src="{asset_url}">'
        else:
            tag = re.sub(
                r'(background(?:-image)?\s*:\s*url\(\s*["\']?)([^)"\']+)(["\']?\s*\))',
                lambda m: f'{m.group(1)}{asset_url}{m.group(3)}', tag, count=1,
                flags=re.IGNORECASE)
        if asset_token:
            tag = _set_tag_asset_token(tag, asset_token)
        return output[:target.start()] + tag + output[target.end():], True

    closing = re.search(r'</div>\s*$', output, re.IGNORECASE)
    if not closing:
        return output, False
    stamp = f' data-asset-token="{asset_token}"' if asset_token else ''
    box = (
        f'<div data-slide-imagebox="1"{stamp} style="position:absolute;left:60px;right:60px;'
        f'top:120px;bottom:90px;z-index:1;display:flex;align-items:center;justify-content:center;overflow:hidden;">'
        f'<img src="{asset_url}" alt="" style="width:100%;height:100%;object-fit:contain;object-position:center center;"></div>'
    )
    return output[:closing.start()] + box + output[closing.start():], True


def _refresh_slide_asset_sources(html, assets):
    """Repoint data-asset-token-tagged media at the asset's current URL.

    A model rebuild keeps the stamped tag but preserves its stored src — which
    is a frozen revision URL once the presentation was saved — so the tag's
    own token decides which current file the element must show.
    """
    if not html or 'data-asset-token' not in html or not assets:
        return html
    urls = {asset['token'].upper(): asset['url'] for asset in assets if asset.get('url')}
    if not urls:
        return html

    def fix_tag(match):
        tag = match.group(0)
        token_match = re.search(r'data-asset-token\s*=\s*["\'](#+[\w\s-]+#+)["\']',
                                tag, re.IGNORECASE)
        if not token_match:
            return tag
        normalized = '##' + token_match.group(1).strip('#').strip().upper() + '##'
        url = urls.get(normalized)
        if not url:
            return tag
        tag = re.sub(r'(\bsrc\s*=\s*)(["\'])(.*?)(\2)',
                     lambda m: f'{m.group(1)}{m.group(2)}{url}{m.group(4)}',
                     tag, count=1, flags=re.IGNORECASE | re.DOTALL)
        tag = re.sub(
            r'(background(?:-image)?\s*:\s*url\(\s*["\']?)([^)"\']+)(["\']?\s*\))',
            lambda m: f'{m.group(1)}{url}{m.group(3)}', tag, count=1, flags=re.IGNORECASE)
        return tag

    return re.sub(r'<[a-z][^>]*\bdata-asset-token\b[^>]*>', fix_tag, html, flags=re.IGNORECASE)


def is_watermark_request(message):
    """Detect requests to add or remove slide watermarks or subtle background logos."""
    if not message:
        return False
    normalized = normalize_arabic_digits_py(str(message).strip().lower())
    patterns = (
        r'watermark',
        r'(?:ال)?(?:وتر|ووتر)\s*مارك',
        r'(?:ال)?علام[ةه]\s*(?:ال)?مائي[ةه]',
        r'(?:ال)?(?:شعار|لوجو)\s*(?:ال)?مائي',
        r'(?:ال)?(?:شعار|لوجو)\s*كـ?علام[ةه]\s*مائي[ةه]',
        r'(?:ال)?(?:شعار|لوجو)\s*(?:في|كـ?|بـ?)?\s*(?:ال)?خلفي[ةه]',
        r'(?:ال)?(?:شعار|لوجو)\s*(?:خفيف|باهت)',
    )
    return any(re.search(pat, normalized) for pat in patterns)


# Named CSS colors used on slides. Any company brand color arrives as hex or as
# rgb()/hsl() and is measured by luminance below — detection never depends on
# a fixed brand palette, so a new company color cannot break it.
_CSS_NAMED_COLORS = {
    'black': '#000000', 'white': '#ffffff',
    'navy': '#000080', 'darkblue': '#00008b', 'mediumblue': '#0000cd', 'blue': '#0000ff',
    'royalblue': '#4169e1', 'steelblue': '#4682b4', 'skyblue': '#87ceeb',
    'lightskyblue': '#87cefa', 'lightblue': '#add8e6', 'powderblue': '#b0e0e6',
    'midnightblue': '#191970', 'slateblue': '#6a5acd', 'darkslateblue': '#483d8b',
    'indigo': '#4b0082', 'darkviolet': '#9400d3', 'blueviolet': '#8a2be2',
    'purple': '#800080', 'darkred': '#8b0000', 'red': '#ff0000', 'maroon': '#800000',
    'brown': '#a52a2a', 'chocolate': '#d2691e', 'sienna': '#a0522d',
    'orange': '#ffa500', 'darkorange': '#ff8c00', 'coral': '#ff7f50',
    'tomato': '#ff6347', 'orangered': '#ff4500', 'salmon': '#fa8072',
    'darksalmon': '#e9967a', 'lightsalmon': '#ffa07a',
    'pink': '#ffc0cb', 'lightpink': '#ffb6c1', 'hotpink': '#ff69b4',
    'gold': '#ffd700', 'goldenrod': '#daa520', 'darkgoldenrod': '#b8860b',
    'yellow': '#ffff00', 'lightyellow': '#ffffe0', 'lemonchiffon': '#fffacd',
    'lightgoldenrodyellow': '#fafad2', 'khaki': '#f0e68c', 'darkkhaki': '#bdb76b',
    'olive': '#808000', 'olivedrab': '#6b8e23', 'darkolivegreen': '#556b2f',
    'yellowgreen': '#9acd32', 'greenyellow': '#adff2f', 'chartreuse': '#7fff00',
    'lawngreen': '#7cfc00', 'lime': '#00ff00', 'limegreen': '#32cd32',
    'springgreen': '#00ff7f', 'mediumspringgreen': '#00fa9a',
    'forestgreen': '#228b22', 'green': '#008000', 'darkgreen': '#006400',
    'seagreen': '#2e8b57', 'mediumseagreen': '#3cb371', 'lightgreen': '#90ee90',
    'palegreen': '#98fb98', 'teal': '#008080', 'lightseagreen': '#20b2aa',
    'turquoise': '#40e0d0', 'mediumturquoise': '#48d1cc', 'darkturquoise': '#00ced1',
    'paleturquoise': '#afeeee', 'aqua': '#00ffff', 'cyan': '#00ffff',
    'gray': '#808080', 'grey': '#808080', 'darkgray': '#a9a9a9', 'darkgrey': '#a9a9a9',
    'dimgray': '#696969', 'dimgrey': '#696969', 'slategray': '#708090',
    'slategrey': '#708090', 'darkslategray': '#2f4f4f', 'darkslategrey': '#2f4f4f',
    'lightslategray': '#778899', 'lightslategrey': '#778899', 'silver': '#c0c0c0',
    'lightgray': '#d3d3d3', 'lightgrey': '#d3d3d3', 'gainsboro': '#dcdcdc',
    'whitesmoke': '#f5f5f5', 'ghostwhite': '#f8f8ff', 'aliceblue': '#f0f8ff',
    'azure': '#f0ffff', 'mintcream': '#f5fffa', 'honeydew': '#f0fff0',
    'beige': '#f5f5dc', 'ivory': '#fffff0', 'linen': '#faf0e6',
    'seashell': '#fff5ee', 'snow': '#fffafa', 'floralwhite': '#fffaf0',
    'oldlace': '#fdf5e6', 'cornsilk': '#fff8dc', 'papayawhip': '#ffefd5',
    'blanchedalmond': '#ffebcd', 'bisque': '#ffe4c4', 'moccasin': '#ffe4b5',
    'navajowhite': '#ffdead', 'wheat': '#f5deb3', 'tan': '#d2b48c',
}


def _parse_css_color_to_rgb(value):
    """Parse any CSS color (hex, rgb()/rgba(), hsl()/hsla(), named) into (r, g, b, alpha)."""
    text = str(value or '').strip().lower()
    if not text or text == 'transparent':
        return None
    short = re.fullmatch(r'#([0-9a-f]{3})', text)
    if short:
        digits = short.group(1)
        return (int(digits[0] * 2, 16), int(digits[1] * 2, 16), int(digits[2] * 2, 16), 1.0)
    full = re.fullmatch(r'#([0-9a-f]{6})', text)
    if full:
        digits = full.group(1)
        return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16), 1.0)
    rgb = re.fullmatch(r'rgba?\(\s*([^)]+)\)', text)
    if rgb:
        parts = [part.strip() for part in rgb.group(1).split(',')]
        if len(parts) in (3, 4):
            try:
                channels = []
                for part in parts[:3]:
                    if part.endswith('%'):
                        channels.append(min(255.0, max(0.0, float(part[:-1]) * 2.55)))
                    else:
                        channels.append(min(255.0, max(0.0, float(part))))
                alpha = 1.0
                if len(parts) == 4:
                    alpha_text = parts[3]
                    alpha = float(alpha_text[:-1]) / 100.0 if alpha_text.endswith('%') else float(alpha_text)
                    alpha = min(1.0, max(0.0, alpha))
                return (channels[0], channels[1], channels[2], alpha)
            except (TypeError, ValueError):
                pass
    hsl = re.fullmatch(r'hsla?\(\s*([^)]+)\)', text)
    if hsl:
        parts = [part.strip() for part in hsl.group(1).split(',')]
        if len(parts) in (3, 4):
            try:
                hue = (float(parts[0].rstrip('deg')) % 360.0) / 360.0
                saturation = min(1.0, max(0.0, float(parts[1].rstrip('%')) / 100.0))
                lightness = min(1.0, max(0.0, float(parts[2].rstrip('%')) / 100.0))
                red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
                alpha = 1.0
                if len(parts) == 4:
                    alpha_text = parts[3]
                    alpha = float(alpha_text[:-1]) / 100.0 if alpha_text.endswith('%') else float(alpha_text)
                    alpha = min(1.0, max(0.0, alpha))
                return (red * 255.0, green * 255.0, blue * 255.0, alpha)
            except (TypeError, ValueError):
                pass
    named = _CSS_NAMED_COLORS.get(text)
    if named:
        return _parse_css_color_to_rgb(named)
    return None


def _css_color_luminance(value):
    """WCAG relative luminance (0-1) of any CSS color, composited over white when translucent."""
    parsed = _parse_css_color_to_rgb(value)
    if not parsed:
        return None
    red, green, blue, alpha = parsed
    red = alpha * red + (1.0 - alpha) * 255.0
    green = alpha * green + (1.0 - alpha) * 255.0
    blue = alpha * blue + (1.0 - alpha) * 255.0
    linear = []
    for channel in (red / 255.0, green / 255.0, blue / 255.0):
        channel = min(1.0, max(0.0, channel))
        linear.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _is_white_or_light_slide(slide, minimum_luminance=0.45):
    """Check whether a slide has a white or light background.

    Every background color in every shade is measured by luminance, so any
    company brand color is classified correctly without a fixed palette.
    """
    if not isinstance(slide, dict):
        return True
    stype = str(slide.get('type') or 'content').lower()
    if stype in ('cover', 'divider', 'back_cover', 'closing', 'section_divider', 'index'):
        return False
    html = str(slide.get('html') or '')
    if re.search(
        r'class=["\'][^"\']*\b(?:dark-slide|cover-slide|divider-slide|slide-dark|bg-dark|dark-mode)\b',
        html,
        flags=re.IGNORECASE,
    ):
        return False
    color_token = r'(?:#[0-9a-f]{3,6}\b|rgba?\([^)]*\)|hsla?\([^)]*\)|[a-z]+)'
    # The root slide background decides: a white slide holding dark cards inside is
    # still a white slide, while a dark root stays dark even with light cards in it.
    # The class token must be exactly `slide` — `\bslide\b` also matches
    # `slide-inner` / `slide-footer`, which would read the wrong element.
    root_style = ''
    for root_candidate in re.finditer(r'<div\b[^>]*>', html, flags=re.IGNORECASE):
        tag_text = root_candidate.group(0)
        class_match = re.search(r'\bclass\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
        if not class_match:
            continue
        if 'slide' not in class_match.group(1).split():
            continue
        style_match = re.search(r'\bstyle\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
        if style_match:
            root_style = style_match.group(1)
        break
    if root_style:
        root_colors = []
        for background in re.findall(r'background(?:-color)?\s*:\s*([^;]+)', root_style, flags=re.IGNORECASE):
            root_colors.extend(re.findall(color_token, background, flags=re.IGNORECASE))
        measured = []
        for color in root_colors:
            luminance = _css_color_luminance(color)
            if luminance is not None:
                measured.append(luminance)
        if measured:
            return all(value >= minimum_luminance for value in measured)
    # Fallback when the root carries no explicit background: only a full-cover
    # background layer decides. Header/footer/table-header colors are dark by
    # design on white slides and must never flip a white slide to dark — that
    # is what silently skipped white slides from an only-white watermark run.
    for tag in re.finditer(r'<div\b[^>]*\bstyle\s*=\s*["\']([^"\']*)["\'][^>]*>', html, flags=re.IGNORECASE):
        style = tag.group(1) or ''
        lowered = style.lower()
        if 'absolute' not in lowered:
            continue
        compact = lowered.replace(' ', '')
        full_cover = (
            'inset:0' in compact
            or ('top:0' in compact and 'bottom:0' in compact and 'left:0' in compact and 'right:0' in compact)
            or ('width:1280' in compact and 'height:720' in compact)
        )
        if not full_cover:
            continue
        layer_colors = []
        for background in re.findall(r'background(?:-color)?\s*:\s*([^;]+)', style, flags=re.IGNORECASE):
            layer_colors.extend(re.findall(color_token, background, flags=re.IGNORECASE))
        for color in layer_colors:
            luminance = _css_color_luminance(color)
            if luminance is not None and luminance < minimum_luminance:
                return False
    return True


# The watermark always renders above slide content layers (opaque cards and
# images used to bury it at z-index 0). Its full-slide overlay stays
# click-through; in manual edit mode the client enables pointer events only on
# the visible logo so it can be selected without blocking the slide beneath it.
WATERMARK_Z_INDEX = 50


def _watermark_src_key(url):
    """Normalized watermark src for staleness checks (ignores cache-busters)."""
    return str(url or '').split('?', 1)[0].split('#', 1)[0].strip()


def _refresh_watermark_source(html, new_url):
    """Point an existing watermark layer at the current company file.

    Only the ``<img>`` src is swapped; position, size, opacity and hidden
    state are preserved. Returns the HTML unchanged when there is no layer
    or when it already points at the current file.
    """
    if not html or not new_url:
        return html
    spec = _watermark_spec_from_html(html)
    if not spec or not spec.get('markup'):
        return html
    if _watermark_src_key(spec.get('logo_url')) == _watermark_src_key(new_url):
        return html
    markup = spec['markup']
    refreshed, count = re.subn(
        r'(<img\b[^>]*\bsrc\s*=\s*["\'])[^"\']+(["\'])',
        lambda match: match.group(1) + new_url + match.group(2),
        markup, count=1, flags=re.IGNORECASE,
    )
    if not count:
        return html
    return html.replace(markup, refreshed, 1)


def _apply_slide_watermark(html, logo_url, opacity=0.045, width_px=480):
    """Inject an elegant watermark overlay on top of a slide's content layers.

    A single centered layer only. Re-applying never duplicates the layer and
    never resets a user move/resize/opacity: a visible watermark keeps its
    geometry and is only re-pointed at the current company file, a hidden
    one is unhidden with its saved geometry intact.
    """
    if not html:
        return html
    existing = _watermark_spec_from_html(html)
    if existing:
        refreshed = _refresh_watermark_source(html, logo_url)
        if existing.get('visible', True):
            return refreshed
        return _set_slide_watermark_visible(refreshed, True, logo_url)
    try:
        opacity_value = float(opacity)
    except (TypeError, ValueError):
        opacity_value = 0.045
    # Owner rule: an explicit user opacity is honored up to fully opaque (1.0).
    # The subtle default (0.045) stays at the call sites that omit it.
    opacity_value = min(1.0, max(0.01, opacity_value))
    try:
        width_value = int(width_px)
    except (TypeError, ValueError):
        width_value = 480
    width_value = min(900, max(200, width_value))
    cleaned = _remove_slide_watermark(html)
    watermark_markup = (
        '<div class="slide-watermark" data-slide-watermark="true" data-watermark-visible="true" aria-hidden="true" '
        'style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;'
        f'pointer-events:none;z-index:{WATERMARK_Z_INDEX};opacity:{opacity_value};overflow:hidden;">'
        f'<img src="{logo_url}" alt="" style="width:{width_value}px;max-width:50%;max-height:50%;object-fit:contain;filter:{slide_engine.WATERMARK_GRAY_FILTER};">'
        '</div>'
    )
    # The overlay is absolutely positioned, so the slide root must establish
    # positioning; most templates already carry position:relative.
    root_tag = re.search(r'<div\b[^>]*>', cleaned, flags=re.IGNORECASE)
    if root_tag:
        tag_text = root_tag.group(0)
        class_match = re.search(r'\bclass\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
        if class_match and 'slide' in class_match.group(1).split():
            style_match = re.search(r'\bstyle\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
            if style_match and 'position' not in style_match.group(1).lower():
                fixed_tag = tag_text.replace(
                    style_match.group(0),
                    'style="' + 'position:relative;' + style_match.group(1) + '"',
                    1,
                )
                cleaned = cleaned[:root_tag.start()] + fixed_tag + cleaned[root_tag.end():]
    closing = re.search(r'</div>\s*$', cleaned, flags=re.IGNORECASE)
    if not closing:
        return cleaned + watermark_markup
    return cleaned[:closing.start()] + watermark_markup + cleaned[closing.start():]


def _remove_slide_watermark(html):
    """Remove watermark overlay markup from a slide HTML."""
    if not html:
        return html
    cleaned = re.sub(
        r'<div\b[^>]*\bdata-slide-watermark=["\']true["\'][^>]*>[\s\S]*?</div>',
        '',
        html,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r'<div\b[^>]*\bclass=["\'][^"\']*\bslide-watermark\b[^"\']*["\'][^>]*>[\s\S]*?</div>',
        '',
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def _watermark_spec_from_html(html):
    """Read the watermark overlay spec (logo, opacity, width, visibility).

    Overlays saved before the visibility flag carry no
    ``data-watermark-visible`` attribute and count as visible, so opening an
    older presentation never flips them off.
    """
    if not html:
        return None
    match = re.search(
        r'<div\b[^>]*\bdata-slide-watermark=["\']true["\'][^>]*>([\s\S]*?)</div\s*>',
        str(html),
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r'<div\b[^>]*\bclass=["\'][^"\']*\bslide-watermark\b[^"\']*["\'][^>]*>([\s\S]*?)</div\s*>',
            str(html),
            flags=re.IGNORECASE,
        )
    if not match:
        return None
    full_markup = match.group(0)
    div_tag = full_markup[:full_markup.find('>') + 1]
    inner = match.group(1) or ''
    opacity = 0.045
    opacity_match = re.search(r'opacity\s*:\s*([0-9.]+)', div_tag, flags=re.IGNORECASE)
    if opacity_match:
        try:
            opacity = float(opacity_match.group(1))
        except (TypeError, ValueError):
            opacity = 0.045
    width = 480
    width_match = re.search(r'width\s*:\s*(\d+)\s*px', inner, flags=re.IGNORECASE)
    if width_match:
        try:
            width = int(width_match.group(1))
        except (TypeError, ValueError):
            width = 480
    logo_match = re.search(r'<img\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', inner, flags=re.IGNORECASE)
    logo_url = logo_match.group(1).strip() if logo_match else ''
    if not logo_url:
        return None
    visible_match = re.search(r'data-watermark-visible\s*=\s*["\']([^"\']*)["\']', div_tag, flags=re.IGNORECASE)
    if visible_match:
        visible = visible_match.group(1).strip().lower() != 'false'
    else:
        visible = True
    if re.search(r'display\s*:\s*none', div_tag, flags=re.IGNORECASE):
        visible = False
    return {'logo_url': logo_url, 'opacity': opacity, 'width_px': width,
            'visible': visible, 'markup': full_markup}


def _watermark_markup_from_html(html):
    """Return the raw watermark overlay markup, or an empty string."""
    spec = _watermark_spec_from_html(html)
    return spec.get('markup', '') if spec else ''


def _is_watermark_visible(html):
    """Whether the slide currently shows its watermark layer."""
    spec = _watermark_spec_from_html(html)
    return bool(spec and spec.get('visible', True))


def _set_slide_watermark_visible(html, visible, logo_url=None):
    """Show or hide the watermark layer while keeping its geometry.

    Hiding keeps position, size and opacity in the saved HTML so showing it
    again restores exactly what the user had. Showing a hidden layer never
    rebuilds it from defaults.
    """
    if not html:
        return html
    spec = _watermark_spec_from_html(html)
    if not spec:
        if not visible or not logo_url:
            return html
        return _apply_slide_watermark(html, logo_url)
    # Showing an existing layer also re-points it at the current company
    # file, so a replaced upload appears in place of the old mark without
    # losing the saved position/size/opacity.
    if visible and logo_url:
        html = _refresh_watermark_source(html, logo_url)
        spec = _watermark_spec_from_html(html) or spec
    if bool(spec.get('visible', True)) == bool(visible):
        # Already in the requested state, but the src refresh above (if any)
        # is still returned so a replaced file appears without another toggle.
        return html
    markup = spec.get('markup', '')
    if not markup:
        return html
    div_end = markup.find('>')
    if div_end == -1:
        return html
    div_tag = markup[:div_end + 1]
    rest = markup[div_end + 1:]
    if re.search(r'data-watermark-visible\s*=', div_tag, flags=re.IGNORECASE):
        div_tag = re.sub(
            r'data-watermark-visible\s*=\s*["\'][^"\']*["\']',
            'data-watermark-visible="%s"' % ('true' if visible else 'false'),
            div_tag, count=1, flags=re.IGNORECASE,
        )
    else:
        div_tag = div_tag[:-1] + ' data-watermark-visible="%s">' % ('true' if visible else 'false')
    if visible:
        div_tag = re.sub(r'display\s*:\s*none\s*;?', 'display:flex;', div_tag, flags=re.IGNORECASE)
        if 'display' not in div_tag.lower():
            div_tag = div_tag[:-1] + ' style="display:flex;">' if 'style=' not in div_tag.lower() else div_tag
    else:
        if re.search(r'display\s*:\s*flex', div_tag, flags=re.IGNORECASE):
            div_tag = re.sub(r'display\s*:\s*flex', 'display:none', div_tag, count=1, flags=re.IGNORECASE)
        elif re.search(r'display\s*:', div_tag, flags=re.IGNORECASE):
            div_tag = re.sub(r'display\s*:\s*[^;]+', 'display:none', div_tag, count=1, flags=re.IGNORECASE)
        else:
            style_match = re.search(r'style\s*=\s*(["\'])(.*?)\1', div_tag, flags=re.IGNORECASE)
            if style_match:
                div_tag = (div_tag[:style_match.start(2)] + 'display:none;'
                           + style_match.group(2) + div_tag[style_match.end(2):])
            else:
                div_tag = div_tag[:-1] + ' style="display:none;">'
    return html.replace(markup, div_tag + rest, 1)


def _carry_slide_watermark(source_html, output_html):
    """Keep a slide watermark across model regeneration that drops it.

    The model rebuilds the whole slide and almost never reproduces the overlay
    div, so without this any later AI edit silently deletes the watermark.
    The saved layer is copied verbatim — source, position, size, opacity and
    hidden state — so a user move is never lost and a hidden watermark is
    never reshown without a request.
    """
    if not output_html or _watermark_spec_from_html(output_html):
        return output_html
    spec = _watermark_spec_from_html(source_html)
    if not spec or not spec.get('markup'):
        return output_html
    markup = spec['markup']
    cleaned = _remove_slide_watermark(output_html)
    root_tag = re.search(r'<div\b[^>]*>', cleaned, flags=re.IGNORECASE)
    if root_tag:
        tag_text = root_tag.group(0)
        class_match = re.search(r'\bclass\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
        if class_match and 'slide' in class_match.group(1).split():
            style_match = re.search(r'\bstyle\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
            if style_match and 'position' not in style_match.group(1).lower():
                fixed_tag = tag_text.replace(
                    style_match.group(0),
                    'style="' + 'position:relative;' + style_match.group(1) + '"',
                    1,
                )
                cleaned = cleaned[:root_tag.start()] + fixed_tag + cleaned[root_tag.end():]
    closing = re.search(r'</div>\s*$', cleaned, flags=re.IGNORECASE)
    if not closing:
        return cleaned + markup
    return cleaned[:closing.start()] + markup + cleaned[closing.start():]


def _designer_attached_image_position(message, params):
    """Resolve where an attached chat image should land, from explicit params or wording."""
    explicit = str((params or {}).get('position') or '').strip().lower()
    aliases = {
        'separate_slide': 'separate_slide', 'new_slide': 'separate_slide', 'separate': 'separate_slide',
        'slide': 'separate_slide', 'standalone': 'separate_slide',
        'inline': 'inline', 'in_slide': 'inline', 'inside': 'inline',
        'background': 'background', 'bg': 'background', 'cover': 'background',
        'watermark': 'watermark', 'water_mark': 'watermark',
        'logo': 'logo', 'extra_logo': 'logo', 'brand': 'logo',
    }
    if explicit in aliases:
        return aliases[explicit]
    text = normalize_arabic_digits_py(str(message or '').lower())
    if re.search(r'(?:شريحة\s*(?:منفصلة|مستقلة|جديدة)|سلايد\s*(?:منفصل|جديد)|في\s*شريحة\s*(?:لوحدها|منفصلة)|separate\s*slide|new\s*slide)', text):
        return 'separate_slide'
    if re.search(r'(?:علامة\s*مائية|واترمارك|ووترمارك|watermark)', text):
        return 'watermark'
    if re.search(r'(?:لوجو\s*(?:اضافي|إضافي|جديد)|شعار\s*(?:اضافي|إضافي|جديد)|كشعار|extra\s*logo|as\s*(?:a\s*)?logo)', text):
        return 'logo'
    if re.search(r'(?:خلفية|كخلفية|background)', text):
        return 'background'
    return 'inline'


def _append_designer_overlay(html, markup):
    """Append an absolutely-positioned overlay inside the slide root."""
    if not html:
        return html
    cleaned = str(html)
    root_tag = re.search(r'<div\b[^>]*>', cleaned, flags=re.IGNORECASE)
    if root_tag:
        tag_text = root_tag.group(0)
        class_match = re.search(r'\bclass\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
        if class_match and 'slide' in class_match.group(1).split():
            style_match = re.search(r'\bstyle\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
            if style_match and 'position' not in style_match.group(1).lower():
                fixed_tag = tag_text.replace(
                    style_match.group(0),
                    'style="' + 'position:relative;' + style_match.group(1) + '"',
                    1,
                )
                cleaned = cleaned[:root_tag.start()] + fixed_tag + cleaned[root_tag.end():]
    closing = re.search(r'</div>\s*$', cleaned, flags=re.IGNORECASE)
    if not closing:
        return cleaned + markup
    return cleaned[:closing.start()] + markup + cleaned[closing.start():]


def _insert_designer_attached_image(html, image_url, position='inline', opacity=1.0, width_px=None, caption=''):
    """Deterministically embed a user-attached image; no model call, no hidden spend."""
    safe_url = html_lib.escape(str(image_url or ''), quote=True)
    if not safe_url:
        return html
    safe_caption = html_lib.escape(str(caption or '')[:160])
    try:
        opacity_value = float(opacity)
    except (TypeError, ValueError):
        opacity_value = 1.0
    if position == 'watermark':
        opacity_value = min(1.0, max(0.05, opacity_value if opacity_value < 1.0 else 0.12))
        try:
            width_value = int(width_px or 480)
        except (TypeError, ValueError):
            width_value = 480
        width_value = min(900, max(200, width_value))
        markup = (
            '<div data-chat-watermark="true" aria-hidden="true" '
            'style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;'
            f'pointer-events:none;z-index:5;opacity:{opacity_value};overflow:hidden;">'
            f'<img src="{safe_url}" alt="" style="width:{width_value}px;max-width:60%;max-height:60%;object-fit:contain;">'
            '</div>'
        )
        return _append_designer_overlay(html, markup)
    if position == 'logo':
        try:
            width_value = int(width_px or 140)
        except (TypeError, ValueError):
            width_value = 140
        width_value = min(320, max(64, width_value))
        markup = (
            '<div data-chat-extra-logo="true" '
            'style="position:absolute;top:24px;left:24px;z-index:8;'
            'background:rgba(255,255,255,0.92);border-radius:10px;padding:6px;">'
            f'<img src="{safe_url}" alt="" style="display:block;width:{width_value}px;max-height:90px;object-fit:contain;">'
            '</div>'
        )
        return _append_designer_overlay(html, markup)
    if position == 'background':
        markup = (
            '<div data-chat-background="true" aria-hidden="true" '
            'style="position:absolute;inset:0;'
            f'background-image:url(\'{safe_url}\');background-size:cover;background-position:center;z-index:0;"></div>'
        )
        return _append_designer_overlay(html, markup)
    caption_markup = (
        f'<div style="font-size:12px;color:#c5a059;margin-top:6px;font-weight:600;text-align:center;">{safe_caption}</div>'
        if safe_caption else ''
    )
    markup = (
        '<div data-chat-imagebox="1" style="position:absolute;top:150px;right:330px;width:620px;'
        'box-sizing:border-box;z-index:5;background:rgba(255,255,255,0.96);border-radius:12px;padding:12px;">'
        f'<img src="{safe_url}" alt="" style="display:block;width:100%;max-height:420px;object-fit:contain;border-radius:8px;">'
        f'{caption_markup}</div>'
    )
    return _append_designer_overlay(html, markup)
