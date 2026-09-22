

def _iter_offer_text_values(value, budget, _key=''):
    """Yield human string values for offer-language detection.

    Detection is intentionally conservative: genuine Arabic content wins, while
    machine identifiers and small auto-filled fragments (city, road names) can
    never flip an English project.
    """
    if budget[0] <= 0:
        return
    if isinstance(value, str):
        chunk = value[:budget[0]]
        budget[0] -= len(chunk)
        yield chunk
    elif isinstance(value, dict):
        for item_key, item in value.items():
            if isinstance(item_key, str) and _MACHINE_OFFER_KEY_RE.search(item_key):
                continue
            yield from _iter_offer_text_values(item, budget, item_key)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_offer_text_values(item, budget, _key)


def detect_offer_lang(project_data):
    """Detect the deck language from the project data itself.

    Returns 'en' only for substantial Latin data with at most fragmentary
    Arabic (auto-filled city/district, a road name); everything else —
    including empty drafts and mixed content — stays 'ar', which preserves
    the historical behavior exactly.
    """
    if not isinstance(project_data, dict):
        return OFFER_LANG_ARABIC
    budget = [50000]
    arabic = 0
    latin = 0
    for text in _iter_offer_text_values(project_data, budget):
        arabic += len(_ARABIC_SCRIPT_RE.findall(text))
        if arabic >= 40:
            return OFFER_LANG_ARABIC
        latin += len(_LATIN_LETTER_RE.findall(text))
    if latin >= 30:
        return OFFER_LANG_ENGLISH
    return OFFER_LANG_ARABIC


def resolve_offer_lang(project_data, offer_lang=None):
    """Normalize an explicit language or detect it from the project data."""
    if offer_lang == OFFER_LANG_ENGLISH:
        return OFFER_LANG_ENGLISH
    if offer_lang == OFFER_LANG_ARABIC:
        return OFFER_LANG_ARABIC
    return detect_offer_lang(project_data)


def section_title(section_key, offer_lang=OFFER_LANG_ARABIC):
    """Canonical deck-chrome title for a section in the deck language."""
    if offer_lang == OFFER_LANG_ENGLISH:
        return PRESENTATION_SECTION_TITLES_EN.get(section_key,
                                                  PRESENTATION_SECTION_TITLES.get(section_key, section_key))
    return PRESENTATION_SECTION_TITLES.get(section_key, section_key)


def offer_chrome(key, offer_lang=OFFER_LANG_ARABIC):
    """Fixed non-data deck label (cover/index markers) in the deck language."""
    if offer_lang == OFFER_LANG_ENGLISH:
        return OFFER_CHROME_EN.get(key, OFFER_CHROME_AR.get(key, key))
    return OFFER_CHROME_AR.get(key, key)

_SECTION_KEY_ALIASES = {
    'project': 'overview', 'project_overview': 'overview', 'project_idea': 'overview',
    'project_components': 'components', 'land_analysis': 'land', 'site': 'location',
    'geographic_location': 'location', 'market_analysis': 'market', 'schedule': 'timeline',
    'finance': 'financial', 'financial_study': 'financial', 'swot': 'swot_risks',
    'risks': 'swot_risks', 'team_members': 'team', 'floorplans': 'plans',
    'moodboard': 'exterior', 'external': 'exterior', 'internal': 'interior',
    'visual_concept': 'exterior',
    'executive': 'executive_summary', 'summary': 'executive_summary', 'conclusion': 'closing',
}

_LOCATION_MAP_SOURCE_TYPES = {
    'location_polygon': ('map_overview', '##MAP_OVERVIEW##'),
    'main_roads': ('map_access', '##MAP_ACCESS##'),
    'access_roads': ('map_access', '##MAP_ACCESS##'),
    'catchment_areas': ('map_catchment', '##MAP_CATCHMENT##'),
    'city_landmarks': ('map_catchment', '##MAP_CATCHMENT##'),
    'nearby_landmarks': ('map_landmarks', '##MAP_LANDMARKS##'),
}


def _normalize_land_boundary_slide(slide):
    """Repair old boundary-diagram entries before they can reach the model.

    Older saved plans often kept the visible title and diagram style but lost
    ``content_source``.  The single-slide endpoint receives those snapshots
    directly, so without this repair it treated the deterministic boundary
    diagram as a normal AI-authored content slide.
    """
    if not isinstance(slide, dict):
        return slide
    item = dict(slide)
    title = str(item.get('title') or '').strip()
    source = str(item.get('content_source') or item.get('contentSource') or '').strip()
    section = str(item.get('section_key') or item.get('sectionKey') or item.get('section') or '').strip().lower()
    is_boundary_diagram = (
        source == 'land_boundary_diagram'
        or bool(re.search(r'(?:مخطط\s*(?:اتجاهي|حدود)|مخطط\s+اتجاهي|حدود\s+الأرض\s+والواجهات|directional\s+boundary)', title, flags=re.IGNORECASE))
        or (str(item.get('design_style') or '').strip().lower() == 'diagram'
            and section in ('', 'land', 'location'))
    )
    if not is_boundary_diagram:
        return item
    item.update({
        'title': 'مخطط اتجاهي لحدود الأرض',
        'type': 'content',
        'section_key': 'land',
        'sectionKey': 'land',
        'design_style': 'diagram',
        'requires_image': False,
        'content_source': 'land_boundary_diagram',
        'image_tokens': [],
        'bullets': [],
    })
    return item


def _normalize_location_map_slide(slide):
    """Keep every intentional map in the location section and give it one token."""
    if not isinstance(slide, dict):
        return slide
    item = dict(slide)
    slide_type = str(item.get('type') or 'content').strip().lower()
    source = str(item.get('content_source') or item.get('contentSource') or '').strip()
    type_sources = {
        'map_overview': ('location_polygon', '##MAP_OVERVIEW##'),
        'map_access': ('main_roads', '##MAP_ACCESS##'),
        'map_catchment': ('catchment_areas', '##MAP_CATCHMENT##'),
        'map_landmarks': ('nearby_landmarks', '##MAP_LANDMARKS##'),
        'site_specs': ('location_detail', ''),
    }
    if slide_type in type_sources:
        canonical_source, token = type_sources[slide_type]
        item.update({
            'content_source': source or canonical_source,
            'design_style': 'map' if slide_type.startswith('map_') else (item.get('design_style') or 'table'),
            'requires_image': slide_type.startswith('map_'),
            'image_tokens': [token] if token else list(item.get('image_tokens') or []),
        })
        item['section_key'] = 'location'
        item['sectionKey'] = 'location'
    elif source in _LOCATION_MAP_SOURCE_TYPES:
        canonical_type, token = _LOCATION_MAP_SOURCE_TYPES[source]
        item.update({
            'type': canonical_type,
            'section_key': 'location',
            'sectionKey': 'location',
            'design_style': 'map',
            'requires_image': True,
            'image_tokens': [token],
        })
    elif source == 'site_analysis':
        item.update({
            'section_key': 'location',
            'sectionKey': 'location',
            'design_style': 'map',
            'requires_image': True,
            'image_tokens': ['##MAP_OVERVIEW##'],
        })
    elif source == 'location_detail':
        item['section_key'] = 'location'
        item['sectionKey'] = 'location'
    return item


def _is_financial_slide(slide):
    """Recognize financial slides even when an old/model plan assigned another section."""
    if not isinstance(slide, dict):
        return False
    section = str(slide.get('section_key') or slide.get('sectionKey') or '').strip().lower()
    source = str(slide.get('content_source') or slide.get('contentSource') or '').strip().lower()
    source_table = str(slide.get('source_table') or slide.get('sourceTable') or '').strip().lower()
    title = str(slide.get('title') or '').strip()
    if section == 'financial':
        return True
    if source.startswith(('financial_', 'financial:', 'financial_report:', 'financial_summary:')):
        return True
    if source_table in {'costtable', 'cashflowtable', 'sensitivitytable', 'financial_report'}:
        return True
    return bool(re.search(
        r'(?:الدراسة المالية|التحليل المالي|الجدوى المالية|التدفقات النقدية|مؤشرات العائد|التكاليف والاستثمار|financial|cash ?flow|roi|irr)',
        title, flags=re.IGNORECASE,
    ))


def _normalize_financial_slide(slide):
    if not _is_financial_slide(slide):
        return slide
    item = dict(slide)
    item['section_key'] = 'financial'
    item['sectionKey'] = 'financial'
    item['requires_image'] = False
    return item


def _normalize_legacy_single_slide(slide, project_data=None):
    """Recover structured sources from a slide snapshot saved by an older client."""
    item = _normalize_land_boundary_slide(slide)
    item = _normalize_location_map_slide(item)
    item = _normalize_financial_slide(item)
    if not isinstance(item, dict):
        return item
    source = str(item.get('content_source') or item.get('contentSource') or '').strip()
    if source:
        return item

    project = project_data if isinstance(project_data, dict) else {}
    title = str(item.get('title') or '').strip()
    section = _slide_section_key(item)
    lower_title = title.lower()

    if section == 'market':
        market = _market_state(project)
        deck_en = resolve_offer_lang(project) == OFFER_LANG_ENGLISH
        if re.search(r'(?:مقارنة\s+المنافسين|منافس|competitor)', title, flags=re.IGNORECASE):
            if isinstance(market.get('competitors'), list) and any(_competitor_name(row) for row in market.get('competitors') or []):
                item.update({
                    'title': 'Competitor Comparison' if deck_en else 'مقارنة المنافسين', 'design_style': 'chart',
                    'chart_type': 'horizontal_bar', 'requires_image': False,
                    'content_source': 'market_study_data.competitors',
                    'source_table': 'competitors', 'image_tokens': [],
                })
        elif re.search(r'نطاق' if not deck_en else r'نطاق|scope', title, flags=re.IGNORECASE) and _market_scope_rows(market):
            item.update({'content_source': 'market_study_data.scope', 'source_table': 'market_scope',
                         'design_style': 'editorial', 'requires_image': False, 'image_tokens': []})
        elif re.search(r'مصادر|مراجع' if not deck_en else r'مصادر|مراجع|sources?|references?', title, flags=re.IGNORECASE) and _market_source_rows(market):
            item.update({'content_source': 'market_study_data.sources', 'source_table': 'market_sources',
                         'design_style': 'editorial', 'requires_image': False, 'image_tokens': []})
        elif re.search(r'(?:swot|نقاط\s+القوة|نقاط\s+الضعف|الفرص|التهديدات)' if not deck_en else r'(?:swot|strengths|weaknesses|opportunities|threats)', lower_title, flags=re.IGNORECASE):
            swot = _extract_project_swot(market) if isinstance(market, dict) and any(_extract_project_swot(market).values()) else _extract_project_swot(project)
            if any(swot.values()):
                item.update({'content_source': 'market_study_data.swot', 'design_style': 'swot',
                             'requires_image': False, 'image_tokens': []})
        elif re.search(r'تحليل\s+السوق|دراسة\s+السوق' if not deck_en else r'market\s+analysis|market\s+overview', title, flags=re.IGNORECASE) and _market_summary_rows(market):
            item.update({'content_source': 'market_study_data.summary', 'source_table': 'market_summary',
                         'design_style': 'editorial', 'requires_image': False, 'image_tokens': []})
        elif re.search(r'ملخص\s+دراسة\s+سوق\s+العمل' if not deck_en else r'market\s+study\s+summary', title, flags=re.IGNORECASE) and _market_one_block_paragraph(market):
            item.update({'content_source': 'market_study_data.one_block_summary', 'design_style': 'text',
                         'requires_image': False, 'image_tokens': []})
        if str(item.get('content_source') or '').strip():
            item['type'] = 'content'

    if not str(item.get('content_source') or '').strip() and section == 'swot_risks':
        if re.search(r'(?:swot|نقاط\s+القوة|نقاط\s+الضعف|الفرص|التهديدات)', lower_title, flags=re.IGNORECASE):
            swot = _extract_project_swot(project)
            if any(swot.values()):
                item.update({'content_source': 'market_study_data.swot', 'design_style': 'swot',
                             'requires_image': False, 'image_tokens': []})
        elif re.search(r'مخاطر|معالجة|risk', lower_title, flags=re.IGNORECASE):
            risk_source, _items = _risk_analysis_source(project)
            if risk_source:
                item.update({'content_source': risk_source, 'design_style': 'table',
                             'requires_image': False, 'image_tokens': []})

    if not str(item.get('content_source') or '').strip() and section == 'location':
        if re.search(r'(?:ملخص\s+الموقع|تحليل\s+الموقع)', title, flags=re.IGNORECASE) and str(project.get('site_analysis') or '').strip():
            item.update({'content_source': 'site_analysis', 'design_style': 'map',
                         'requires_image': True, 'image_tokens': ['##MAP_OVERVIEW##']})
        elif re.search(r'(?:بيانات\s+الموقع|الإحداثيات|مواصفات\s+الموقع)', title, flags=re.IGNORECASE):
            item.update({'type': 'site_specs', 'content_source': 'location_detail',
                         'design_style': 'table', 'requires_image': False, 'image_tokens': []})

    if not str(item.get('content_source') or '').strip() and section == 'land':
        if re.search(r'(?:مواصفات\s+الأرض|الاشتراطات\s+التنظيمية|اشتراطات\s+البناء|مواصفات\s+واشتراطات|land_specs)', title, flags=re.IGNORECASE):
            item.update({'content_source': 'land_specs', 'design_style': 'specs',
                         'requires_image': False, 'image_tokens': []})
        elif re.search(r'(?:ملخص\s+تحليل\s+الأرض|تحليل\s+الأرض)', title, flags=re.IGNORECASE) and str(project.get('land_and_building_summary') or '').strip():
            item.update({'content_source': 'land_and_building_summary', 'design_style': 'text',
                         'requires_image': False, 'image_tokens': []})

    if not str(item.get('content_source') or '').strip() and section == 'timeline':
        if re.search(r'(?:الجدول\s+الزمني|مراحل\s+المشروع|مراحل\s+التطوير|خطة\s+التنفيذ|timeline)', title, flags=re.IGNORECASE):
            item.update({'content_source': 'timeline_table_data', 'design_style': 'timeline',
                         'requires_image': False, 'image_tokens': []})

    if not str(item.get('content_source') or '').strip() and (
        section == 'executive_summary' or re.search(r'الملخص\s+التنفيذي|الفرصة\s+الاستثمارية|المميزات|executive\s+summary|investment\s+opportunity', title, flags=re.IGNORECASE)
    ):
        executive = _decode_json_fact(project.get('executive_content'))
        if not isinstance(executive, dict):
            executive = {}
        if re.search(r'فرصة|opportunity', title, flags=re.IGNORECASE) and str(executive.get('opportunity') or '').strip():
            item.update({'section_key': 'executive_summary', 'sectionKey': 'executive_summary',
                         'content_source': 'executive_content.opportunity', 'design_style': 'editorial',
                         'requires_image': False, 'image_tokens': []})
        elif re.search(r'ممي[زس]|feature', title, flags=re.IGNORECASE) and str(executive.get('features') or '').strip():
            item.update({'section_key': 'executive_summary', 'sectionKey': 'executive_summary',
                         'content_source': 'executive_content.features', 'design_style': 'editorial',
                         'requires_image': False, 'image_tokens': []})
        elif str(executive.get('summary') or '').strip() or str(project.get('executive_summary') or '').strip():
            item.update({'section_key': 'executive_summary', 'sectionKey': 'executive_summary',
                         'content_source': 'executive_content.summary', 'design_style': 'editorial',
                         'requires_image': False, 'image_tokens': []})

    return item

_SECTION_MATCHERS = (
    ('closing', r'(?:الخاتمة|الختام|شكرا|شكراً|closing|conclusion|thanks)'),
    ('executive_summary', r'(?:الملخص التنفيذي|الفرصة الاستثمارية|المميزات وفرص الاستثمار|مميزات المشروع|executive summary|investment opportunity)'),
    ('interior', r'(?:التصورات? الداخلية|التصميم الداخلي|interior)'),
    ('exterior', r'(?:التصورات? الخارجية|المود بورد|mood ?board|واجهات المشروع|exterior|التصور البصري)'),
    ('plans', r'(?:المخططات|المخطط|المساقط|مخطط معماري|2d|floor ?plans?)'),
    ('team', r'(?:فريق العمل|فريق التطوير|المطور|الاستشاري|team)'),
    ('swot_risks', r'(?:swot|نقاط القوة|نقاط الضعف|الفرص والتهديدات|المخاطر|إدارة المخاطر|risk)'),
    ('financial', r'(?:الدراسة المالية|التحليل المالي|الجدوى|التدفقات النقدية|الإيرادات|التكاليف|العائد|roi|irr|financial|cash ?flow)'),
    ('timeline', r'(?:الجدول الزمني|الخطة الزمنية|مراحل التطوير|مراحل التنفيذ|timeline|schedule)'),
    ('market', r'(?:تحليل السوق|دراسة السوق|المنافسين|الطلب السوقي|market|competitor)'),
    ('location', r'(?:الموقع الجغرافي|تحليل الموقع|الموقع الاستراتيجي|خريطة|الطرق|المعالم|نطاق التأثير|site|location|map|access|landmarks|catchment)'),
    ('land', r'(?:تحليل الأرض|الأرض والاشتراطات|الأرض والكروكي|الكروكي|اشتراطات البناء|حدود الأرض|صور الأرض|land|croquis)'),
    ('components', r'(?:مكونات المشروع|الوحدات والمساحات|المكونات|components|units)'),
    ('overview', r'(?:نبذة عن المشروع|المشروع والفكرة|فكرة المشروع|نظرة عامة|تعريف المشروع|project overview|project brief)'),
)


def _slide_section_key(slide, current=''):
    slide = slide if isinstance(slide, dict) else {}
    explicit = str(slide.get('section_key') or slide.get('sectionKey') or slide.get('section') or '').strip().lower()
    explicit = _SECTION_KEY_ALIASES.get(explicit, explicit)
    if explicit in PRESENTATION_SECTION_ORDER:
        return explicit
    slide_type = str(slide.get('type') or '').strip().lower()
    if slide_type == 'closing':
        return 'closing'
    if slide_type == 'moodboard':
        return 'exterior'
    if slide_type == 'cover':
        return 'cover'
    if slide_type == 'index':
        return 'index'
    # Older plans sometimes labelled market slides as map_* because the model
    # saw words such as "نطاق" or "منافسة" and chose a location map. Keep
    # those slides in the market section so the market-only media policy can
    # repair them instead of letting a map leak into the location section.
    market_text = ' '.join(str(value or '') for value in (
        slide.get('title'), slide.get('content_source') or slide.get('contentSource'),
        slide.get('source_table') or slide.get('sourceTable'),
    )).lower()
    if re.search(r'(?:تحليل السوق|دراسة السوق|المنافسين|مقارنة المنافسين|الفجوة السوقية|السوقية|market|competitor)', market_text, flags=re.IGNORECASE):
        return 'market'
    if slide_type.startswith('map_') or slide_type == 'site_specs':
        return 'location'
    text = ' '.join(str(value or '') for value in (
        slide.get('title'), slide.get('content_source') or slide.get('contentSource'),
        slide.get('source_table') or slide.get('sourceTable'),
        ' '.join(str(item or '') for item in (slide.get('bullets') or [])),
    )).lower()
    for key, pattern in _SECTION_MATCHERS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return key
    return current if current in PRESENTATION_SECTION_ORDER else 'overview'


_FIXED_DIVIDER_SECTION_KEYS = {'market', 'swot_risks'}


def _is_fixed_section_divider(slide, section_key=None):
    """Identify the two legacy dividers whose stored HTML needs rebuilding."""
    item = slide if isinstance(slide, dict) else {}
    section = section_key or _slide_section_key(item)
    if section not in _FIXED_DIVIDER_SECTION_KEYS:
        return False
    if str(item.get('type') or '').strip().lower() == 'section_divider':
        return True
    title = re.sub(r'\s+', ' ', str(item.get('title') or '').strip())
    return title == PRESENTATION_SECTION_TITLES.get(section, '')


def _plan_slide_signature(slide):
    # ``[\W_]`` was stripping Arabic letters in the runtime used by the app,
    # turning every source-less Arabic title into the same empty signature and
    # silently dropping the later land tables.
    title = ''.join(char for char in str(slide.get('title') or '').lower() if char.isalnum())
    source = re.sub(r'\s+', '', str(slide.get('content_source') or slide.get('source_table') or '').lower())
    tokens = '|'.join(str(item or '') for item in (slide.get('image_tokens') or []))
    return ('source', source) if source else ('tokens', tokens) if tokens else ('title', title)


def _canonical_image_token(token):
    value = str(token or '').strip()
    patterns = (
        (r'#*(?:PROJECT_IMAGE|MOODBOARD_IMAGE)_(\d+)#*', 'MOODBOARD_IMAGE'),
        (r'#*(?:LAND_IMAGE|LAND_PHOTO)_(\d+)#*', 'LAND_PHOTO'),
        (r'#*(?:2D_PLAN|PLAN_IMAGE)_(\d+)#*', 'PLAN_IMAGE'),
    )
    for pattern, prefix in patterns:
        match = re.fullmatch(pattern, value, re.IGNORECASE)
        if match:
            return f'##{prefix}_{int(match.group(1))}##'
    for pattern in (
        r'#*INTERIOR_COMP_(\d+)_(?:IMG|IMAGE)_(\d+)#*',
        r'#*INTERIOR_C(\d+)_(?:IMG|IMAGE)_(\d+)#*',
        r'#*INTERIOR_(\d+)_(\d+)#*',
    ):
        match = re.fullmatch(pattern, value, re.IGNORECASE)
        if match:
            return f'##INTERIOR_COMP_{int(match.group(1))}_IMG_{int(match.group(2))}##'
    return value


def _canonicalize_slide_image_tokens(slide):
    if not isinstance(slide, dict):
        return slide
    normalized = []
    raw_tokens = slide.get('image_tokens') or []
    if not isinstance(raw_tokens, (list, tuple)):
        raw_tokens = [raw_tokens]
    for token in raw_tokens:
        canonical = _canonical_image_token(token)
        if canonical and canonical not in normalized:
            normalized.append(canonical)
    slide['image_tokens'] = normalized
    return slide


def _reserve_media_sections(groups):
    owners = {
        '##MOODBOARD_IMAGE_': 'exterior',
        '##LAND_PHOTO_': 'land',
        '##PLAN_IMAGE_': 'plans',
        '##INTERIOR_COMP_': 'interior',
    }
    def owner_of(token):
        return next((owner for prefix, owner in owners.items() if token.startswith(prefix)), '')

    for section_key, slides in groups.items():
        kept = []
        for slide in slides:
            _canonicalize_slide_image_tokens(slide)
            original = slide.get('image_tokens') or []
            tokens = [token for token in original if not owner_of(token) or owner_of(token) == section_key]
            slide['image_tokens'] = tokens
            if original and not tokens:
                slide['requires_image'] = False
                if slide.get('design_style') == 'image' and not slide.get('content_source') and not slide.get('bullets'):
                    continue
                if slide.get('design_style') == 'image':
                    slide['design_style'] = 'text'
            kept.append(slide)
        groups[section_key] = kept


def _deduplicate_plan_media(groups):
    used = set()
    prefixes = ('##MOODBOARD_IMAGE_', '##LAND_PHOTO_', '##PLAN_IMAGE_', '##INTERIOR_COMP_')
    for section_key in PRESENTATION_SECTION_ORDER:
        kept = []
        for slide in groups.get(section_key, []):
            _canonicalize_slide_image_tokens(slide)
            tokens = slide.get('image_tokens') or []
            unique_tokens = [token for token in tokens if not token.startswith(prefixes) or token not in used]
            if tokens and not unique_tokens:
                continue
            slide['image_tokens'] = unique_tokens
            used.update(token for token in unique_tokens if token.startswith(prefixes))
            kept.append(slide)
        groups[section_key] = kept
    return used


def _drop_redundant_generic_slides(groups, offer_lang=None):
    generic = {
        'المحتوى المعتمد لهذا القسم', 'التفاصيل المتاحة في بيانات المشروع',
        'الملخص النهائي دون تكرار', 'تعريف المشروع من البيانات المعتمدة',
        'الفكرة والاستخدامات المعتمدة', 'ملخص موجز دون تكرار',
    }
    if offer_lang == OFFER_LANG_ENGLISH:
        generic |= {
            'Approved content for this section', 'Available details from the project data',
            'Final summary without repetition', 'Project definition from approved data',
            'Approved concept and uses', 'Concise summary without repetition',
            'Additional detail from the project data',
            'Concise wording', 'Without inventing information',
        }
    for section_key, slides in groups.items():
        concrete = any(slide.get('content_source') or slide.get('source_table') or slide.get('image_tokens')
                       for slide in slides)
        if concrete:
            groups[section_key] = [
                slide for slide in slides
                if slide.get('content_source') or slide.get('source_table') or slide.get('image_tokens')
                or not generic.intersection(str(item or '').strip() for item in (slide.get('bullets') or []))
            ]


APPROVED_CHART_TYPES = ('horizontal_bar', 'waterfall', 'combo', 'heatmap')
FINANCIAL_CHART_TYPES = ('waterfall', 'combo', 'heatmap')

CHART_TYPE_ALIASES = {
    'bar': 'horizontal_bar',
    'horizontal_bar': 'horizontal_bar',
    'waterfall': 'waterfall',
    'combo': 'combo',
    'combo_chart': 'combo',
    'column_line': 'combo',
    'line_column': 'combo',
    'heatmap': 'heatmap',
}


def canonicalize_chart_type(chart_type):
    if not chart_type:
        return ''
    cleaned = str(chart_type).strip().lower().replace('-', '_').replace(' ', '_')
    return CHART_TYPE_ALIASES.get(cleaned, '')


def _financial_chart_type(title='', table_key='', index=0):
    text = f'{title} {table_key}'.lower()
    if re.search(r'حساسي|سيناريو|sensitivity', text):
        return 'heatmap'
    if re.search(r'تدفق|cashflow|cash flow', text):
        return 'combo'
    if re.search(r'تكال|تكلف|cost|استثمار|capex', text) and not re.search(r'تشغيل|opex', text):
        return 'waterfall'
    return ''


def _financial_report_part_slice(part, row_start, row_end, column_start=None, column_end=None):
    result = dict(part) if isinstance(part, dict) else {}
    rows = result.get('rows') if isinstance(result.get('rows'), list) else []
    selected_rows = rows[row_start:row_end]
    headers = result.get('headers') if isinstance(result.get('headers'), list) else []
    if column_start is not None and column_end is not None and headers:
        indexes = list(range(column_start, min(column_end, len(headers))))
        if column_start > 0 and 0 not in indexes:
            indexes.insert(0, 0)
        result['headers'] = [headers[index] for index in indexes]
        result['rows'] = [[row[index] if index < len(row) else '' for index in indexes]
                          if isinstance(row, (list, tuple)) else row for row in selected_rows]
    else:
        result['rows'] = selected_rows
    return result


def _financial_column_ranges(part, title=''):
    """Split a wide table into balanced column groups, each keeping the context column.

    Groups hold at most five data columns plus the first context column, and
    the data columns are distributed evenly so no group is left as a tiny
    2-3 column remainder slide on its own.
    """
    headers = part.get('headers') if isinstance(part, dict) and isinstance(part.get('headers'), list) else []
    rows = part.get('rows') if isinstance(part, dict) and isinstance(part.get('rows'), list) else []
    title_text = f"{str((part or {}).get('title') or (part or {}).get('text') or '')} {title}".lower()
    is_sensitivity = (
        any(term in title_text for term in ('حساسية', 'sensitivity', 'سيناريو'))
        or any('سيناريو' in str(h) or 'حساسية' in str(h) for h in headers)
        or any(
            any(term in str(cell) for term in ('متحفظ', 'متفائل', 'أساسي'))
            for r in rows if isinstance(r, list) for cell in r
        )
    )
    is_cashflow = (
        any(term in title_text for term in ('تدفق', 'cashflow', 'cash_flow', 'نقدية', 'cash flow'))
        or any('تدفق' in str(h) for h in headers)
    )
    if len(headers) <= 8 or is_sensitivity or is_cashflow:
        return [(None, None)]
    data_count = len(headers) - 1
    num_groups = max(1, (data_count + 4) // 5)
    base_size = data_count // num_groups
    remainder = data_count % num_groups
    ranges = []
    start = 1
    for group in range(num_groups):
        size = base_size + (1 if group < remainder else 0)
        ranges.append((start, start + size))
        start += size
    return ranges


def _balanced_row_ranges(total_rows, max_per_slide=12, min_per_slide=4):
    """Chunk rows into balanced, readable ranges without leaving orphan 1-2 row slides.

    The chunk count follows ``max_per_slide`` (a 14-row narrow table stays on
    one slide when the caller allows 16), while the ``min_per_slide`` guard
    still folds a tiny remainder back instead of emitting a near-empty slide.
    """
    if total_rows <= 0:
        return []
    if total_rows <= max_per_slide:
        return [(0, total_rows)]
    num_chunks = (total_rows + max_per_slide - 1) // max_per_slide
    while num_chunks > 1 and (total_rows // num_chunks) < min_per_slide:
        num_chunks -= 1
    base_size = total_rows // num_chunks
    remainder = total_rows % num_chunks
    ranges = []
    start = 0
    for i in range(num_chunks):
        size = base_size + (1 if i < remainder else 0)
        ranges.append((start, start + size))
        start += size
    return ranges


def _financial_table_chartable(part, rows, column_start=None, column_end=None):
    if column_start is not None:
        return False
    headers = part.get('headers') if isinstance(part, dict) and isinstance(part.get('headers'), list) else []
    column_count = len(headers) if column_start is None else min(column_end, len(headers)) - column_start + 1
    return 2 <= len(rows) <= 12 and 2 <= column_count <= 8 and _rows_have_comparable_numbers(rows)


def _can_chart_financial_part(chart_cand, part, model=None, project_data=None):
    if not isinstance(part, dict):
        return False
    rows = part.get('rows') or []
    if not rows:
        return False
    if chart_cand == 'combo':
        for r in rows:
            if isinstance(r, dict):
                txt = ' '.join(str(k) + ' ' + str(v) for k, v in r.items()).lower()
                if re.search(r'صافي.*تدفق|net.*cash|net.*flow|رصيد.*تراكمي|cumulative', txt):
                    return True
            elif isinstance(r, (list, tuple)) and r:
                txt = str(r[0]).lower()
                if re.search(r'صافي.*تدفق|net.*cash|net.*flow|رصيد.*تراكمي|cumulative', txt):
                    return True
        if isinstance(model, dict) and (model.get('tables', {}).get('cashflowTable') or model.get('tables', {}).get('cashflow')):
            return True
        return False
    elif chart_cand == 'waterfall':
        for r in rows:
            txt = str(r.get('البند') if isinstance(r, dict) else (r[0] if isinstance(r, (list, tuple)) and r else '')).lower()
            if re.search(r'تكلف|cost|استثمار|مجموع|إجمالي', txt):
                return True
        if isinstance(model, dict) and (model.get('tables', {}).get('costTable') or model.get('tables', {}).get('costs')):
            return True
        return False
    elif chart_cand == 'heatmap':
        for r in rows:
            txt = str(r.get('السيناريو') if isinstance(r, dict) else (r[0] if isinstance(r, (list, tuple)) and r else '')).lower()
            if re.search(r'متحفظ|أساسي|اساسي|متفائل|تحفظ|تفاؤل', txt):
                return True
        if isinstance(model, dict) and (model.get('tables', {}).get('sensitivityTable') or model.get('tables', {}).get('sensitivity')):
            return True
        return False
    return False


def _financial_chart_score(slide):
    text = ' '.join(str(slide.get(key) or '') for key in ('title', 'content_source', 'source_table', 'chart_type')).lower()
    priorities = (
        (r'تكال|تكلف|cost|waterfall', 100),
        (r'تدفق|cashflow|cash flow|combo', 90),
        (r'حساسي|سيناريو|sensitivity|heatmap', 80),
    )
    return next((score for pattern, score in priorities if re.search(pattern, text)), 50)


def _limit_presentation_charts(groups, limit=4):
    chart_styles = {'chart', 'bar', 'column', 'grouped_bar', 'grouped_column', 'line', 'area',
                    'pie', 'donut', 'treemap', 'scatter', 'histogram', 'heatmap', 'candlestick',
                    'horizontal_bar', 'waterfall', 'combo'}
    for section_key, slides in groups.items():
        if section_key in ('market', 'financial'):
            continue
        for slide in slides:
            if slide.get('chart_type') or slide.get('design_style') in chart_styles:
                slide['chart_type'] = ''
                slide['design_style'] = 'table' if slide.get('source_table') else 'text'

    market_slides = groups.get('market', [])
    kept_market_chart = False
    for slide in market_slides:
        c_type = canonicalize_chart_type(slide.get('chart_type'))
        text = ' '.join(str(slide.get(k) or '') for k in ('title', 'content_source', 'source_table')).lower()
        is_competitor = bool(re.search(r'منافس|competitor', text))
        if c_type == 'horizontal_bar' and is_competitor:
            slide['chart_type'] = 'horizontal_bar'
            slide['design_style'] = 'chart'
            kept_market_chart = True
        else:
            if slide.get('chart_type') or slide.get('design_style') in chart_styles:
                slide['chart_type'] = ''
                slide['design_style'] = 'table' if slide.get('source_table') else 'text'

    financial = groups.get('financial', [])
    candidates = []
    for index, slide in enumerate(financial):
        c_type = canonicalize_chart_type(slide.get('chart_type'))
        if c_type in FINANCIAL_CHART_TYPES:
            candidates.append((index, slide, c_type))

    seen_types = set()
    keep_indices = set()
    for index, slide, c_type in sorted(
        candidates, key=lambda item: (-_financial_chart_score(item[1]), item[0])):
        if c_type not in seen_types and len(keep_indices) < 3:
            seen_types.add(c_type)
            keep_indices.add(index)
            slide['chart_type'] = c_type
            slide['design_style'] = 'chart'

    for index, slide in enumerate(financial):
        if index not in keep_indices:
            if slide.get('chart_type') or slide.get('design_style') in chart_styles:
                slide['chart_type'] = ''
                slide['design_style'] = 'table'


# Vertical stacking budget for packed tables: data rows plus the header and caption
# each stacked table costs.  The renderer uses compact rows, so consecutive tables
# keep filling the current slide until this budget is reached.
_FINANCIAL_PACK_ROW_BUDGET = 21.5
_FINANCIAL_PACK_MAX_TABLES = 8


def _pack_financial_table_slices(items, offer_lang=None):
    """Pack consecutive narrow financial table slices into slides that stack them vertically.

    The client shrinks the tables, so one small table per slide wasted the deck with
    a half-empty slide each. Wide (column-split) tables never reach this packer: the
    caller flushes them as single slides because two six-column tables stacked
    vertically do not fit the slide height.
    """
    lang = OFFER_LANG_ENGLISH if offer_lang == OFFER_LANG_ENGLISH else OFFER_LANG_ARABIC
    groups = []
    current = None
    for item in items:
        weight = float(item.get('row_count') or 0) + 2.5
        if current is not None and (current['weight'] + weight <= _FINANCIAL_PACK_ROW_BUDGET
                                    and len(current['items']) < _FINANCIAL_PACK_MAX_TABLES):
            current['items'].append(item)
            current['weight'] += weight
        else:
            current = {'items': [item], 'weight': weight}
            groups.append(current)
    slides = []
    for group in groups:
        group_items = group['items']
        sources = [str(item['source']) for item in group_items]
        row_count = sum(int(item.get('row_count') or 0) for item in group_items)
        if len(group_items) == 1:
            item = group_items[0]
            slides.append({
                'title': item['title'] + (f" — {item['suffix']}" if item.get('suffix') else ''),
                'type': 'content', 'design_style': 'table',
                'chart_type': '', 'content_density': 'high', 'requires_image': False,
                'content_source': sources[0],
                'source_table': item.get('source_table'),
                'row_count': row_count, 'financial_template': 'report', 'bullets': [],
            })
            continue
        titles = list(dict.fromkeys(str(item['title']) for item in group_items))
        sensitivity_word = 'sensitivity' if lang == OFFER_LANG_ENGLISH else 'حساسية'
        if len(titles) == 1:
            title = titles[0]
        elif any(sensitivity_word in t.lower() for t in titles):
            title = next((t for t in titles if sensitivity_word in t.lower()), titles[0])
        elif len(titles) == 2:
            title = ' + '.join(titles)
        else:
            title = f'{titles[0]} + {"other tables" if lang == OFFER_LANG_ENGLISH else "جداول أخرى"}'
        slides.append({
            'title': title, 'type': 'content', 'design_style': 'table',
            'chart_type': '', 'content_density': 'high', 'requires_image': False,
            'content_source': sources[0], 'content_sources': sources,
            'source_table': group_items[0].get('source_table'),
            'row_count': row_count, 'financial_template': 'report', 'bullets': [],
        })
    return slides


def _financial_report_part_title(model, part_index):
    """Re-derive the heading a report part sat under, matching the plan builder's walk."""
    report = model.get('report') if isinstance(model, dict) and isinstance(model.get('report'), dict) else {}
    parts = report.get('parts') if isinstance(report.get('parts'), list) else []
    heading = 'الدراسة المالية'
    subheading = ''
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        if part.get('type') == 'heading':
            text = str(part.get('text') or '').strip()
            if part.get('level') == 3:
                subheading = text
            else:
                heading = text or heading
                subheading = ''
            continue
        if index == part_index:
            return subheading or heading
    return ''


def _stacked_financial_report_note(sources, model):
    """One combined note for a slide that stacks several report tables vertically."""
    report = model.get('report') if isinstance(model, dict) and isinstance(model.get('report'), dict) else {}
    parts = report.get('parts') if isinstance(report.get('parts'), list) else []
    blocks = []
    for number, source in enumerate(sources, 1):
        match = re.fullmatch(r'financial_report:(\d+):(\d+):(\d+)(?::(\d+):(\d+))?', str(source))
        if not match:
            continue
        part_index, start, end = map(int, match.groups()[:3])
        column_start = int(match.group(4)) if match.group(4) is not None else None
        column_end = int(match.group(5)) if match.group(5) is not None else None
        if part_index >= len(parts) or not isinstance(parts[part_index], dict):
            continue
        part = _financial_report_part_slice(parts[part_index], start, end, column_start, column_end)
        part_title = _financial_report_part_title(model, part_index) or f'جدول {number}'
        blocks.append(f'جدول {number} — {part_title} (الصفوف {start + 1} إلى {end}):\n'
                      + json.dumps(part, ensure_ascii=False, indent=2))
    if not blocks:
        return ''
    return ('هذه الشريحة المالية العادية تضم الجداول التالية في الشريحة نفسها — '
            'اعرض كل جدول مستقلاً، ورص جميع الجداول رأسياً تحت بعضها بترتيب المصادر، مع إبقاء كل صف وعمود كاملاً. لا تضع جدولين بجانب بعضهما، وإذا لم تتسع المساحة الحالية فانقل بقية الجداول إلى الشريحة المالية التالية دون قص أو حذف. هذا الترتيب لا يلغي تخطيط الجدول بجانب الرسم في شرائح الرسوم المعتمدة:\n\n'
            + '\n\n'.join(blocks))


def _merge_sparse_plan_slides(groups):
    for section_key, slides in groups.items():
        merged = []
        for slide in slides:
            source = str(slide.get('content_source') or '')
            sparse_financial = (section_key == 'financial' and slide.get('row_count') == 1
                                and not source.startswith(('financial_summary:', 'financial_indicators')))
            sparse_generic = (not source and slide.get('design_style') != 'table'
                              and not slide.get('image_tokens')
                              and len([item for item in (slide.get('bullets') or []) if str(item or '').strip()]) <= 1)
            target = merged[-1] if merged else None
            if ((sparse_financial or sparse_generic) and target
                    and not target.get('chart_type') and not slide.get('chart_type')):
                if source:
                    target['content_sources'] = list(target.get('content_sources') or [target.get('content_source')])
                    target['content_sources'].append(source)
                    target['row_count'] = int(target.get('row_count') or 0) + int(slide.get('row_count') or 0)
                else:
                    target['bullets'] = list(target.get('bullets') or []) + list(slide.get('bullets') or [])
                continue
            merged.append(slide)
        if len(merged) > 1:
            first = merged[0]
            first_source = str(first.get('content_source') or '')
            first_sparse = (section_key == 'financial' and first.get('row_count') == 1
                            and not first_source.startswith(('financial_summary:', 'financial_indicators')))
            first_generic = (not first_source and first.get('design_style') != 'table'
                             and not first.get('image_tokens')
                             and len([item for item in (first.get('bullets') or []) if str(item or '').strip()]) <= 1)
            second = merged[1]
            if ((first_sparse or first_generic) and merged
                    and not second.get('chart_type') and not first.get('chart_type')):
                target = second
                if first_source:
                    target['content_sources'] = list(first.get('content_sources') or [first_source]) + list(
                        target.get('content_sources') or [target.get('content_source')])
                    target['row_count'] = int(first.get('row_count') or 0) + int(target.get('row_count') or 0)
                else:
                    target['bullets'] = list(first.get('bullets') or []) + list(target.get('bullets') or [])
                merged.pop(0)
        groups[section_key] = merged


def _merge_adjacent_table_slides(groups, offer_lang=None):
    """Combine adjacent ordinary table slides when their data can share a page.

    Financial report tables are packed from their canonical report below, but
    land/location tables can arrive directly from the plan model.  Keeping those
    slides separate made several small key/value tables consume one page each.
    The original sources and titles are retained so the generator still has all
    facts available.
    """
    for section_key, slides in groups.items():
        # Apply the same sequential packing rule to every section.  A table slide
        # is only merged with the immediately preceding table slide in its section;
        # charts, images and narrative slides naturally flush the current group.
        merged = []
        for slide in slides:
            source = str(slide.get('content_source') or '')
            is_table = (
                slide.get('type', 'content') == 'content'
                and slide.get('design_style') == 'table'
                and not slide.get('chart_type')
                and not slide.get('image_tokens')
                and section_key != 'market'
                and not source.startswith(('financial_summary:', 'financial_indicators'))
                and not source.startswith('project_components:')
                and not re.fullmatch(r'financial_report:\d+:\d+:\d+:\d+:\d+', source)
            )
            previous = merged[-1] if merged else None
            previous_is_table = bool(previous and previous.get('_table_group'))
            previous_rows = int(previous.get('row_count') or 0) if previous_is_table else 0
            current_rows = int(slide.get('row_count') or 0)
            can_fit = (
                previous_is_table
                and len(previous.get('_table_group') or []) < _FINANCIAL_PACK_MAX_TABLES
                and previous_rows + current_rows + 2.5 * (len(previous.get('_table_group') or []) + 1)
                    <= _FINANCIAL_PACK_ROW_BUDGET
            )
            if is_table and can_fit:
                previous['_table_group'].append(slide)
                previous['table_group_titles'] = list(previous.get('table_group_titles') or []) + [
                    str(slide.get('title') or '').strip()
                ]
                previous['bullets'] = list(previous.get('bullets') or []) + list(slide.get('bullets') or [])
                if source:
                    previous['content_sources'] = list(previous.get('content_sources') or [previous.get('content_source')])
                    previous['content_sources'].append(source)
                previous['row_count'] = int(previous.get('row_count') or 0) + int(slide.get('row_count') or 0)
                continue
            if is_table:
                item = dict(slide)
                item['_table_group'] = [slide]
                item['table_group_titles'] = [str(slide.get('title') or '').strip()]
                merged.append(item)
            else:
                merged.append(slide)

        for slide in merged:
            group = slide.pop('_table_group', [])
            titles = [title for title in slide.pop('table_group_titles', []) if title]
            if len(group) <= 1:
                continue
            if not slide.get('content_sources'):
                slide['content_sources'] = [
                    str(item.get('content_source') or '').strip()
                    for item in group if str(item.get('content_source') or '').strip()
                ]
            slide['table_group_titles'] = titles
            slide['title'] = (titles[0] if titles else slide.get('title')
                              or ('Data Tables' if offer_lang == OFFER_LANG_ENGLISH else 'جداول البيانات'))
        groups[section_key] = merged


def _is_sensitivity_assumptions_slide(slide, model=None):
    """Identify the assumptions table that belongs with the sensitivity results."""
    source = str((slide or {}).get('content_source') or '').strip().lower()
    source_table = str((slide or {}).get('source_table') or '').strip().lower()
    text = ' '.join(str((slide or {}).get(key) or '') for key in ('title', 'content_source', 'source_table')).lower()
    if 'sensitivityassumptionstable' in source or 'sensitivityassumptionstable' in source_table:
        return True
    if model and source.startswith('financial_report:'):
        match = re.fullmatch(r'financial_report:(\d+):\d+:\d+(?::\d+:\d+)?', source)
        report_title = _financial_report_part_title(model, int(match.group(1))).lower() if match else ''
        if match and re.search(r'sensitivity|حساسية|سيناريو', report_title):
            return bool(re.search(r'assumption|افتراض|متغير', text + ' ' + report_title))
    return bool(re.search(r'assumption|افتراض|متغير|متغيرات.*(?:حساسية|سيناريو)|(?:حساسية|سيناريو).*متغيرات', text))


def _attach_sensitivity_assumptions(groups, project_data):
    """Place the sensitivity assumptions table beside its result matrix when it fits."""
    financial = groups.get('financial', [])
    if not financial:
        return
    model = _parse_financial_dict((project_data or {}).get('financial_study_model'))
    heatmap = next((slide for slide in financial if canonicalize_chart_type(slide.get('chart_type')) == 'heatmap'), None)
    if not heatmap:
        return

    assumption_slides = []
    for slide in financial:
        if slide is heatmap or not _is_sensitivity_assumptions_slide(slide, model):
            continue
        sources = [str(value).strip() for value in (slide.get('content_sources') or [slide.get('content_source')])
                   if str(value or '').strip()]
        # Never remove a packed slide containing another table.  It remains a
        # normal table slide instead of losing unrelated source data.
        if sources and all('sensitivityassumptionstable' in value.lower() or
                           _is_sensitivity_assumptions_slide({'content_source': value}, model)
                           for value in sources):
            assumption_slides.append((slide, sources))
    if not assumption_slides:
        return

    assumption_sources = [source for _slide, sources in assumption_slides for source in sources]
    assumption_rows = sum(int(slide.get('row_count') or 0) for slide, _sources in assumption_slides)
    # The result matrix and the assumptions table share the chart slide only
    # while the assumptions can stay readable in the side column.
    if assumption_rows <= 10:
        result_source = str(heatmap.get('content_source') or '').strip()
        heatmap['content_sources'] = list(dict.fromkeys(assumption_sources + ([result_source] if result_source else [])))
        heatmap['sensitivity_assumptions_sources'] = assumption_sources
        raw_titles = (
            [str(slide.get('title') or '').strip() for slide, _sources in assumption_slides] +
            [str(heatmap.get('title') or '').strip()]
        )
        sens_title = next((t for t in raw_titles if 'حساسية' in t), raw_titles[0] if raw_titles else '')
        if sens_title:
            heatmap['title'] = sens_title
        heatmap['table_group_titles'] = list(dict.fromkeys(raw_titles))
        heatmap['row_count'] = int(heatmap.get('row_count') or 0) + assumption_rows
        removed = {id(slide) for slide, _sources in assumption_slides}
        groups['financial'] = [slide for slide in financial if id(slide) not in removed]


def _financial_summary_from_report(model):
    report = model.get('report') if isinstance(model, dict) and isinstance(model.get('report'), dict) else {}
    parts = report.get('parts') if isinstance(report.get('parts'), list) else []
    groups = {'التكاليف والاستثمار': [], 'مؤشرات العائد والاسترداد': []}
    current = ''
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get('type') == 'heading':
            current = str(part.get('text') or '').strip()
            continue
        target = next((name for name in groups if name in current), None)
        if target and part.get('type') == 'fields':
            groups[target].extend(row for row in (part.get('rows') or [])
                                  if isinstance(row, (list, tuple)) and len(row) >= 2)
    return groups if any(groups.values()) else {}


def _financial_summary_plan_slides(model):
    summary = _financial_summary_from_report(model)
    available = [(name, rows) for name, rows in summary.items() if rows]
    if not available:
        return [{
            'title': 'الملخص المالي', 'type': 'content', 'design_style': 'table',
            'chart_type': '', 'content_density': 'high', 'requires_image': False,
            'content_source': 'financial_indicators', 'row_count': 2, 'bullets': [],
        }]
    content_sources = []
    total_rows = 0
    for name, rows in available:
        key = 'costs' if name == 'التكاليف والاستثمار' else 'returns'
        content_sources.append(f'financial_summary:{key}:0:{len(rows)}')
        total_rows += len(rows)
    return [{
        'title': 'الملخص المالي',
        'type': 'content', 'design_style': 'table', 'chart_type': '',
        'content_density': 'high', 'requires_image': False,
        'content_source': content_sources[0] if len(content_sources) == 1 else f'financial_summary:combined:0:{total_rows}',
        'content_sources': content_sources,
        'row_count': total_rows, 'bullets': [],
    }]


_FINANCIAL_PLAN_TABLES = (
    ('componentsTable', 'مكونات المشروع', 'table'),
    ('revenueTable', 'بنود الإيرادات', 'table'),
    ('costTable', 'تكاليف المشروع', 'chart'),
    ('scheduleTable', 'مراحل التطوير المالية', 'flow'),
    ('opexTable', 'المصروفات التشغيلية', 'table'),
    ('graceScheduleTable', 'جدول فترة السماح', 'table'),
    ('financeDrawTable', 'جدول سحب التمويل', 'flow'),
    ('financeRepaymentTable', 'جدول سداد التمويل', 'flow'),
    ('fundAdditionalFeesTable', 'أتعاب الصندوق الإضافية', 'table'),
    ('externalTable', 'البنود الخارجية', 'table'),
    ('cashflowTable', 'التدفقات النقدية السنوية', 'chart'),
    ('sensitivityAssumptionsTable', 'افتراضات تحليل الحساسية', 'table'),
    ('sensitivityTable', 'نتائج تحليل الحساسية', 'chart'),
)

_FINANCIAL_PLAN_TABLES_EN = (
    ('componentsTable', 'Project Components', 'table'),
    ('revenueTable', 'Revenue Line Items', 'table'),
    ('costTable', 'Project Costs', 'chart'),
    ('scheduleTable', 'Financial Development Phases', 'flow'),
    ('opexTable', 'Operating Expenses', 'table'),
    ('graceScheduleTable', 'Grace Period Schedule', 'table'),
    ('financeDrawTable', 'Financing Drawdown Schedule', 'flow'),
    ('financeRepaymentTable', 'Financing Repayment Schedule', 'flow'),
    ('fundAdditionalFeesTable', 'Additional Fund Fees', 'table'),
    ('externalTable', 'External Line Items', 'table'),
    ('cashflowTable', 'Annual Cash Flow', 'chart'),
    ('sensitivityAssumptionsTable', 'Sensitivity Analysis Assumptions', 'table'),
    ('sensitivityTable', 'Sensitivity Analysis Results', 'chart'),
)


def _financial_plan_tables(offer_lang=OFFER_LANG_ARABIC):
    """Legacy-model financial table titles in the deck language (keys unchanged)."""
    if offer_lang == OFFER_LANG_ENGLISH:
        return _FINANCIAL_PLAN_TABLES_EN
    return _FINANCIAL_PLAN_TABLES

USE_TYPE_LABELS = {
    'retail': 'تجاري / تجزئة',
    'residential': 'سكني',
    'hospitality': 'فندقي / ضيافة',
    'office': 'مكاتب / إداري',
    'entertainment': 'ترفيهي',
    'services': 'خدمات ومرافق',
    'parking': 'مواقف سيارات',
    'industrial': 'صناعي',
    'logistics': 'لوجستي / مستودعات',
    'other': 'أخرى',
}

INVESTMENT_MODEL_LABELS = {
    'sale': 'بيع وحدات',
    'dailyRent': 'إيجار يومي',
    'monthlyRent': 'إيجار شهري',
    'annualRent': 'إيجار سنوي',
    'operating': 'تشغيل / تأجير آخر',
    'nonRevenue': 'بدون إيراد / مرافق عامة',
}


def _format_component_row(row):
    if not isinstance(row, dict):
        return {}
    name = row.get('name') or row.get('اسم المكون') or row.get('المكون') or ''
    use_type = row.get('useType') or row.get('use_type') or row.get('نوع الاستخدام') or ''
    use_type_label = USE_TYPE_LABELS.get(use_type, use_type)
    units_count = row.get('units') or row.get('unitsCount') or row.get('units_count') or row.get('عدد الوحدات') or ''
    unit_area = row.get('unitArea') or row.get('unit_area') or row.get('مساحة الوحدة') or row.get('مساحة الوحدة م²') or ''
    built_area = row.get('builtArea') or row.get('built_area') or row.get('المساحة المبنية') or row.get('المساحة المبنية م²') or ''
    leasable_area = row.get('revenueArea') or row.get('revenue_area') or row.get('leasableArea') or row.get('leasable_area') or row.get('totalArea') or row.get('المساحة البيعية / التأجيرية') or row.get('المساحة البيعية / التأجيرية م²') or row.get('المساحة التأجيرية') or ''
    inv_model = row.get('investmentModel') or row.get('investment_model') or row.get('نموذج الاستفادة') or row.get('نموذج الاستثمار') or ''
    inv_model_label = INVESTMENT_MODEL_LABELS.get(inv_model, inv_model)

    formatted = {}
    if name:
        formatted['اسم المكون'] = name
    if use_type_label:
        formatted['نوع الاستخدام'] = use_type_label
    if units_count:
        formatted['عدد الوحدات'] = units_count
    if unit_area:
        formatted['مساحة الوحدة م²'] = unit_area
    if built_area:
        formatted['المساحة المبنية م²'] = built_area
    if leasable_area:
        formatted['المساحة البيعية / التأجيرية م²'] = leasable_area
    if inv_model_label:
        formatted['نموذج الاستفادة'] = inv_model_label

    for k, v in row.items():
        if k not in ('name', 'useType', 'use_type', 'units', 'unitsCount', 'units_count', 'unitArea', 'unit_area',
                     'builtArea', 'built_area', 'leasableArea', 'leasable_area', 'revenueArea', 'revenue_area',
                     'totalArea', 'total_area', 'investmentModel', 'investment_model', 'idx', 'id', 'leasable',
                     'اسم المكون', 'نوع الاستخدام', 'عدد الوحدات', 'مساحة الوحدة', 'مساحة الوحدة م²',
                     'المساحة المبنية', 'المساحة المبنية م²', 'المساحة البيعية / التأجيرية',
                     'المساحة البيعية / التأجيرية م²', 'المساحة التأجيرية', 'نموذج الاستفادة', 'نموذج الاستثمار') and k not in formatted:
            if v not in (None, '', [], {}):
                formatted[k] = v
    return formatted if formatted else row


def _project_component_rows(project_data):
    model = _parse_financial_dict((project_data or {}).get('financial_study_model'))
    dynamic = model.get('dynamicRows') if isinstance(model.get('dynamicRows'), dict) else {}
    rows = dynamic.get('components') if isinstance(dynamic.get('components'), list) else []
    if not rows:
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get('componentsTable') if isinstance(tables.get('componentsTable'), list) else []
    if not rows:
        decoded = _decode_json_fact((project_data or {}).get('project_components_data'))
        rows = decoded if isinstance(decoded, list) else []
    valid_rows = [row for row in rows if isinstance(row, dict) and any(str(value or '').strip() for value in row.values())]
    return [_format_component_row(row) for row in valid_rows]


def _available_asset_items(values):
    items = []
    seen = set()
    for index, value in enumerate(values if isinstance(values, list) else [], 1):
        source = value if isinstance(value, dict) else {'url': value}
        url = str(source.get('url') or source.get('imageUrl') or '').strip()
        identity = str(source.get('id') or url).split('?', 1)[0]
        # The client sends one compact ``available`` marker per uploaded image while planning.
        # Those markers deliberately have no URL, but they still represent distinct assets.
        if url.lower() == 'available' or url.lower().startswith('available:'):
            identity = f'available:{index}'
        if url and identity not in seen:
            seen.add(identity)
            items.append((index, source))
    return items


def _balanced_media_chunks(items, single=False):
    items = list(items or [])
    if single:
        return [[item] for item in items]
    if len(items) <= 2:
        return [items] if items else []
    sizes = [2] * (len(items) // 2)
    if len(items) % 2:
        if sizes:
            sizes[-1] = 3
        else:
            sizes = [1]
    chunks = []
    start = 0
    for size in sizes:
        chunks.append(items[start:start + size])
        start += size
    return chunks


def _pair_media_chunks(items):
    """Pack visual-concept images two per slide, leaving one image alone when odd."""
    items = list(items or [])
    return [items[start:start + 2] for start in range(0, len(items), 2)]


def _market_state(project_data):
    value = (project_data or {}).get('market_study_data') if isinstance(project_data, dict) else None
    decoded = _decode_json_fact(value)
    return decoded if isinstance(decoded, dict) else {}


def _market_swot_items(value):
    if isinstance(value, list):
        values = value
    elif isinstance(value, dict):
        values = list(value.values())
    else:
        text = str(value or '').replace('\r\n', '\n').replace('\n', '\n').strip()
        values = re.split(r'\n\s*-\s+|\s+-\s+', text) if text else []
    return [str(item or '').strip(' -') for item in values if str(item or '').strip(' -')]


def _extract_project_swot(project_data):
    """Extract SWOT analysis across all possible draft formats, returning normalized 4 quadrants."""
    source = project_data if isinstance(project_data, dict) else {}
    market = _market_state(source)
    swot_candidate = None
    if isinstance(market, dict) and isinstance(market.get('swot'), dict):
        swot_candidate = market.get('swot')
    elif isinstance(source.get('swot'), dict):
        swot_candidate = source.get('swot')
    elif isinstance(source.get('swot_analysis'), dict):
        swot_candidate = source.get('swot_analysis')
    elif isinstance(source.get('swot'), str):
        try:
            swot_candidate = json.loads(source.get('swot'))
        except (ValueError, TypeError):
            pass

    res = {'strengths': [], 'weaknesses': [], 'opportunities': [], 'threats': []}
    key_aliases = {
        'strengths': ('strengths', 'strength', 'نقاط القوة', 'القوة', 'نقاط_القوة', 'swot_strengths', 'swotStrengths'),
        'weaknesses': ('weaknesses', 'weakness', 'نقاط الضعف', 'الضعف', 'نقاط_الضعف', 'swot_weaknesses', 'swotWeaknesses'),
        'opportunities': ('opportunities', 'opportunity', 'الفرص', 'فرص', 'swot_opportunities', 'swotOpportunities'),
        'threats': ('threats', 'threat', 'التهديدات', 'المخاطر والتهديدات', 'تهديدات', 'swot_threats', 'swotThreats'),
    }

    if isinstance(swot_candidate, dict):
        for std_key, aliases in key_aliases.items():
            for alias in aliases:
                val = swot_candidate.get(alias)
                if val:
                    items = _market_swot_items(val)
                    if items:
                        res[std_key].extend(items)
                        break

    for std_key, aliases in key_aliases.items():
        if not res[std_key]:
            for alias in aliases:
                val = source.get(alias)
                if val:
                    items = _market_swot_items(val)
                    if items:
                        res[std_key].extend(items)
                        break

    for std_key in res:
        seen = set()
        deduped = []
        for it in res[std_key]:
            s = str(it).strip()
            if s and s not in seen:
                seen.add(s)
                deduped.append(s)
        res[std_key] = deduped

    return res


def _market_scope_rows(market):
    if not isinstance(market, dict):
        return []
    rows = []
    scope_text = _market_scope_display(market)
    if scope_text:
        parts = [part.strip() for part in scope_text.split('|') if part.strip()]
        for part in parts:
            if ':' in part:
                label, value = part.split(':', 1)
                rows.append([label.strip(), value.strip()])
            else:
                rows.append(['نطاق الدراسة', part])
    return rows


def _market_summary_rows(market):
    if not isinstance(market, dict):
        return []
    summary = market.get('summary')
    if isinstance(summary, str):
        # Keep paragraphs from the previous schema readable until regeneration.
        text = summary.strip()
        return [['تحليل السوق', text]] if text else []
    if not isinstance(summary, dict):
        return []
    try:
        import market_study
        definitions = market_study.SUMMARY_SECTIONS
    except Exception:
        definitions = [
            {'key': 'market_definition', 'label': 'تعريف السوق'},
            {'key': 'city_position', 'label': 'وضع المدينة'},
            {'key': 'sector_performance', 'label': 'أداء القطاع'},
            {'key': 'supply', 'label': 'العرض'},
            {'key': 'demand', 'label': 'الطلب'},
            {'key': 'competition', 'label': 'المنافسة'},
            {'key': 'market_gap', 'label': 'الفجوة السوقية'},
            {'key': 'project_evaluation', 'label': 'تقييم المشروع'},
            {'key': 'recommendation', 'label': 'التوصية'},
            {'key': 'risks', 'label': 'المخاطر'},
        ]
    return [
        [item['label'], str(summary.get(item['key']) or '').strip()]
        for item in definitions
        if str(summary.get(item['key']) or '').strip()
    ]


def _market_rows_for_slide(slide, prefix, rows):
    """Return the row slice requested by a paginated market slide source."""
    rows = list(rows or [])
    explicit_start = (slide or {}).get('market_row_start')
    explicit_end = (slide or {}).get('market_row_end')
    if explicit_start is not None and explicit_end is not None:
        start = max(int(explicit_start), 0)
        end = max(int(explicit_end), start)
        return rows[start:end], start
    content_source = str((slide or {}).get('content_source') or '').strip()
    match = re.fullmatch(rf'{re.escape(prefix)}(?::(\d+):(\d+))?', content_source)
    if not match or match.group(1) is None:
        return rows, 0
    start = max(int(match.group(1)), 0)
    end = max(int(match.group(2)), start)
    return rows[start:end], start


def _market_row_pages(rows, page_size):
    rows = list(rows or [])
    return [
        (start, rows[start:start + page_size])
        for start in range(0, len(rows), page_size)
    ]


def _market_source_rows(market):
    if not isinstance(market, dict) or not isinstance(market.get('sources'), list):
        return []
    rows = []
    for item in market.get('sources') or []:
        if not isinstance(item, dict):
            continue
        name = item.get('name') or item.get('title') or item.get('source') or ''
        url = item.get('url') or item.get('source_url') or item.get('sourceUrl') or ''
        data_date = item.get('data_date') or item.get('dataDate') or item.get('source_date') or item.get('date') or ''
        accessed = item.get('accessed_at') or item.get('accessedAt') or item.get('date_accessed') or ''
        reliability = item.get('reliability') or item.get('priority') or ''
        note = item.get('note') or item.get('notes') or ''
        values = [name, url, data_date, accessed, reliability, note]
        if any(str(value or '').strip() for value in values):
            rows.append(values)
    return rows


def _market_has_required_data(market):
    if not isinstance(market, dict):
        return False
    return bool(
        _market_scope_rows(market)
        or isinstance(market.get('competitors'), list) and any(_competitor_name(row) for row in market.get('competitors') or [])
        or _market_summary_rows(market)
        or str(market.get('one_block_summary') or '').strip()
        or _market_source_rows(market)
    )


def _market_one_block_chunks(value, max_chars=2200):
    """Split the complete market-work summary into at most two readable chunks."""
    text = str(value or '').replace('\\r\\n', '\n').replace('\\n', '\n').strip()
    text = re.sub(r'\n{3,}', '\n\n', text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    midpoint = max_chars
    split_at = text.rfind('\n\n', 0, midpoint + 260)
    if split_at < int(len(text) * 0.35):
        split_at = text.rfind(' ', 0, midpoint + 260)
    if split_at < int(len(text) * 0.35):
        split_at = min(midpoint, len(text) - 1)
    first = text[:split_at].strip()
    second = text[split_at:].strip()
    return [chunk for chunk in (first, second) if chunk]


def _market_work_heading(value):
    """Return whether a short line can act as a visual section heading."""
    text = str(value or '').strip()
    return bool(text and len(text) <= 70 and not re.search(r'[:：.!؟،؛]', text))


def _market_work_blocks(value):
    """Turn the work-market narrative into headed editorial blocks."""
    text = str(value or '').replace('\\r\\n', '\n').replace('\\n', '\n').strip()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r'\n\s*\n+', text) if part.strip()]
    blocks = []
    pending_heading = ''
    for part in parts:
        lines = [line.strip() for line in part.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1 and _market_work_heading(lines[0]):
            if pending_heading:
                blocks.append((pending_heading, ''))
            pending_heading = lines[0]
            continue
        heading = pending_heading
        pending_heading = ''
        if not heading and len(lines) > 1 and _market_work_heading(lines[0]):
            heading = lines.pop(0)
        body = '\n'.join(lines).strip()
        if body or heading:
            blocks.append((heading, body))
    if pending_heading:
        blocks.append((pending_heading, ''))
    return blocks or [('', text)]


def _market_work_block_columns(blocks):
    """Balance two contiguous editorial columns while preserving reading order."""
    if len(blocks) < 2:
        return [list(blocks), []]
    weights = [max(len(str(heading or '')) + len(str(body or '')), 1)
               for heading, body in blocks]
    total = sum(weights)
    prefix = 0
    split_at = 1
    best_distance = total
    for index, weight in enumerate(weights[:-1], 1):
        prefix += weight
        distance = abs(total - 2 * prefix)
        if distance < best_distance:
            best_distance = distance
            split_at = index
    return [list(blocks[:split_at]), list(blocks[split_at:])]


def _risk_pair_for_slide(raw):
    """Normalize one stored risk into a display pair without inventing content."""
    if isinstance(raw, dict):
        risk = raw.get('risk') or raw.get('name') or raw.get('title') or raw.get('الخطر') or raw.get('المخاطر') or ''
        mitigation = (
            raw.get('mitigation') or raw.get('treatment') or raw.get('solution')
            or raw.get('المعالجة') or raw.get('طريقة المعالجة') or raw.get('التخفيف') or ''
        )
        return str(risk or '').strip(), str(mitigation or '').strip()

    text = str(raw or '').replace('\\r\\n', '\n').replace('\\n', '\n').strip()
    if not text:
        return '', ''
    risk_match = re.search(
        r'(?:^|\n)\s*(?:الخطر|المخاطر?)\s*[:：-]\s*(.*?)(?=\n\s*(?:المعالجة|طريقة المعالجة|التخفيف)\s*[:：-]|$)',
        text, flags=re.IGNORECASE | re.DOTALL)
    mitigation_match = re.search(
        r'(?:^|\n)\s*(?:المعالجة|طريقة المعالجة|التخفيف)\s*[:：-]\s*(.*)$',
        text, flags=re.IGNORECASE | re.DOTALL)
    if risk_match:
        risk = risk_match.group(1).strip()
        mitigation = mitigation_match.group(1).strip() if mitigation_match else ''
        return risk, mitigation
    if 'المعالجة' in text:
        risk, mitigation = text.split('المعالجة', 1)
        return risk.strip(' :-—'), mitigation.lstrip(' :-—').strip()
    return text, ''


def _risk_items_from_value(value):
    """Read list, object, or normalized text risk data into display rows."""
    if isinstance(value, dict):
        nested = value.get('items') or value.get('risks') or value.get('rows')
        raw_items = nested if isinstance(nested, list) else [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        text = str(value or '').replace('\\r\\n', '\n').replace('\\n', '\n').strip()
        if not text:
            return []
        blocks = [item.strip() for item in re.split(r'\n\s*\n+', text) if item.strip()]
        if len(blocks) == 1 and re.search(r'(?:^|\n)\s*(?:الخطر|المخاطر?)\s*[:：-]', text):
            blocks = [item.strip() for item in re.split(r'(?=\n\s*(?:الخطر|المخاطر?)\s*[:：-])', text) if item.strip()]
        raw_items = blocks
    result = []
    seen = set()
    for raw in raw_items:
        risk, mitigation = _risk_pair_for_slide(raw)
        if not risk:
            continue
        key = (risk, mitigation)
        if key in seen:
            continue
        seen.add(key)
        result.append({'risk': risk, 'mitigation': mitigation})
    return result


def _risk_analysis_source(project_data):
    """Choose the most complete approved risk source for the risk register."""
    source = project_data if isinstance(project_data, dict) else {}
    market = _market_state(source)
    executive = _decode_json_fact(source.get('executive_content'))
    executive = executive if isinstance(executive, dict) else {}
    candidates = (
        ('executive_content.risks', executive.get('risks')),
        ('market_study_data.risk_analysis', market.get('risk_analysis')),
        ('market_study_data.risk_register', market.get('risk_register')),
        ('market_study_data.risks', market.get('risks')),
        ('market_study_data.summary.risks', (market.get('summary') or {}).get('risks')
         if isinstance(market.get('summary'), dict) else ''),
    )
    for content_source, value in candidates:
        items = _risk_items_from_value(value)
        if items:
            return content_source, items
    return '', []


def _market_source_chunks(market, rows=None):
    """Split one source-register page into two balanced columns."""
    rows = _market_source_rows(market) if rows is None else list(rows or [])
    midpoint = (len(rows) + 1) // 2
    return [rows[:midpoint], rows[midpoint:]] if rows else []


# Estimated rendered metrics for the editorial market-summary layout. The
# paginator packs topics until their estimated block heights fill the usable
# content band of a 1280x720 slide (56px chrome header + 36px footer), so the
# number of slides follows the amount of text instead of a fixed topic count.
_MARKET_PAGE_BUDGET_PX = 560
_MARKET_DECISION_STRIP_PX = 46
_MARKET_LEAD_CHARS_PER_LINE = 88
_MARKET_ROW_CHARS_PER_LINE = 118
_MARKET_MAX_TOPICS_PER_PAGE = 7
# The comparison table plus its bar chart cannot fit more than four
# competitors in the 1280x720 content band, so pages fill sequentially.
_MARKET_COMPETITORS_PER_SLIDE = 4


def _market_competitor_ranges(count):
    """Slice competitors into balanced slides of at most _MARKET_COMPETITORS_PER_SLIDE.

    Pages fill evenly rather than sequentially: 5 split 3+2, 9 split
    3+3+3 — never a crowded page followed by a near-empty one.
    """
    return _balanced_row_ranges(
        count, max_per_slide=_MARKET_COMPETITORS_PER_SLIDE, min_per_slide=2)


def _market_summary_topic_height(label, value, lead=False):
    """Rough rendered height (px) of one summary topic in the editorial layout."""
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if lead:
        columns = 2 if len(text) > 320 else 1
        lines = max(1, math.ceil(len(text) / (_MARKET_LEAD_CHARS_PER_LINE * columns)))
        return 86 + lines * 25
    columns = 2 if len(text) > 420 else 1
    lines = max(1, math.ceil(len(text) / (_MARKET_ROW_CHARS_PER_LINE * columns)))
    return 54 + lines * 21


def _budget_row_pages(rows, first_budget=None):
    """Pack (label, text) rows into pages by estimated rendered height."""
    rows = list(rows or [])
    budget = _MARKET_PAGE_BUDGET_PX
    first_budget = budget if first_budget is None else first_budget
    pages = []
    index = 0
    while index < len(rows):
        start = index
        page_budget = first_budget if start == 0 else budget
        used = _market_summary_topic_height(rows[index][0], rows[index][1], lead=True)
        index += 1
        while (index < len(rows) and index - start < _MARKET_MAX_TOPICS_PER_PAGE
               and used + _market_summary_topic_height(rows[index][0], rows[index][1]) <= page_budget):
            used += _market_summary_topic_height(rows[index][0], rows[index][1])
            index += 1
        pages.append((start, rows[start:index]))
    return pages


def _market_summary_pages(market):
    """Pack detailed-analysis topics into pages by estimated rendered height."""
    rows = _market_summary_rows(market)
    budget_first = _MARKET_PAGE_BUDGET_PX - (
        _MARKET_DECISION_STRIP_PX if str((market or {}).get('decision') or '').strip() else 0
    )
    return _budget_row_pages(rows, budget_first)


_EXEC_LABEL_RE = re.compile(r'^[^.،,؛:؟!…\-]{2,60}$')


def _executive_summary_sections(project_data):
    """Split the approved executive summary into (label, text) blocks.

    The stored document usually uses short unnumbered label lines (البيانات
    الأساسية، الموقع، الجدول الزمني …) followed by paragraph blocks separated
    by blank lines. Some generations write the canonical headings inline as
    «الموقع: …» inside a flowing paragraph — those are normalised to label
    lines first. Unlabelled documents collapse to one summary block.
    """
    executive = _decode_json_fact((project_data or {}).get('executive_content'))
    text = str(executive.get('summary') or '').strip() if isinstance(executive, dict) else ''
    if not text:
        text = str((project_data or {}).get('executive_summary') or '').strip()
    if not text:
        return []
    try:
        from executive_content import SUMMARY_HEADINGS
    except Exception:
        SUMMARY_HEADINGS = ()
    if SUMMARY_HEADINGS:
        label_alt = '|'.join(re.escape(str(h).strip()) for h in SUMMARY_HEADINGS if str(h or '').strip())
        if label_alt:
            text = re.sub(rf'(^|\n)\s*({label_alt})\s*[:：]', r'\n\n\2\n\n', text)
            text = re.sub(rf'(?<=[.!؟])\s+({label_alt})\s*[:：]', r'\n\n\1\n\n', text)
    blocks = []
    current = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)

    doc_titles = {'الملخص التنفيذي', 'الملخص التنفيذي الشامل', 'ملخص تنفيذي', 'executive summary'}

    def is_label(block):
        joined = ' '.join(block).strip(':： ').strip()
        return len(block) == 1 and len(joined.split()) <= 6 and bool(_EXEC_LABEL_RE.match(joined))

    if not any(is_label(block) for block in blocks):
        return [('', ' '.join(block)) for block in blocks]
    sections = []
    current_label = ''
    current_paras = []
    for block in blocks:
        if is_label(block):
            if current_paras or current_label:
                sections.append((current_label, ' '.join(current_paras)))
                current_paras = []
            label = ' '.join(block).strip(':： ').strip()
            current_label = '' if label.lower() in doc_titles else label
        else:
            current_paras.append(' '.join(block))
    if current_paras or current_label:
        sections.append((current_label, ' '.join(current_paras)))
    return sections


def _executive_summary_pages(project_data):
    """Pack executive-summary sections into pages by estimated rendered height."""
    return _budget_row_pages(_executive_summary_sections(project_data))


def _market_source_pages(market):
    """Keep source rows readable by limiting each page to ten references."""
    return _market_row_pages(_market_source_rows(market), 10)


def _market_plan_slide(title, content_source, design_style='table', source_table=''):
    return {
        'title': title,
        'type': 'content',
        'section_key': 'market',
        'design_style': design_style,
        'chart_type': '',
        'content_density': 'high',
        'requires_image': False,
        'content_source': content_source,
        'source_table': source_table,
        'image_tokens': [],
        'bullets': [],
    }


def _normalize_market_group_slides(existing, market, offer_lang=None):
    """Normalize market data sources while leaving SOL's visual design open.

    The competitor comparison is the only market page with a fixed visual
    renderer.  The remaining entries are only normalized for source coverage;
    their HTML is still designed by SOL.
    """
    lang = OFFER_LANG_ENGLISH if offer_lang == OFFER_LANG_ENGLISH else OFFER_LANG_ARABIC
    if not _market_has_required_data(market):
        return list(existing or [])

    existing = [dict(slide) for slide in (existing or []) if isinstance(slide, dict)]
    competitors = market.get('competitors') if isinstance(market.get('competitors'), list) else []
    named_competitors = [row for row in competitors if _competitor_name(row)]
    # The structured market fields are the source of truth. Older plans often
    # contain duplicate pages for the same two-row table, plus narrative/map
    # pages that repeat the ten summary fields. Reusing those pages defeats the
    # compact layout and can bring stale media back, so retain only their
    # semantic identity and rebuild the section below from current data.
    existing_by_source = {
        str(slide.get('content_source') or '').strip(): slide
        for slide in existing
        if str(slide.get('content_source') or '').strip()
    }

    def take(source, title, design_style='table', source_table=''):
        slide = dict(existing_by_source.get(source) or
                     _market_plan_slide(title, source, design_style, source_table))
        slide.update({
            'title': title,
            'type': 'content',
            'section_key': 'market',
            'design_style': design_style,
            'chart_type': '',
            'content_density': 'high' if design_style == 'chart' else 'medium',
            'requires_image': False,
            'content_source': source,
            'source_table': source_table,
            'image_tokens': [],
            'bullets': [],
        })
        return slide

    result = []
    scope_rows = _market_scope_rows(market)
    if scope_rows:
        result.append(take('market_study_data.scope', 'Study Scope' if lang == OFFER_LANG_ENGLISH else 'نطاق الدراسة', 'editorial', 'market_scope'))

    if named_competitors:
        comp_ranges = _market_competitor_ranges(len(named_competitors))
        total_comp_pages = len(comp_ranges)
        for chunk_idx, (start, end) in enumerate(comp_ranges):
            c_title = 'Competitor Comparison' if lang == OFFER_LANG_ENGLISH else 'مقارنة المنافسين'
            c_source = 'market_study_data.competitors'
            if total_comp_pages > 1:
                c_title += f' ({chunk_idx + 1}/{total_comp_pages})'
                c_source = f'market_study_data.competitors:{start}:{end}'
            competitor_slide = take(c_source, c_title, 'chart', 'competitors')
            competitor_slide.update({
                'design_style': 'chart',
                'chart_type': 'horizontal_bar',
                'competitor_start': start,
                'competitor_end': end,
            })
            result.append(competitor_slide)

    summary_pages = _market_summary_pages(market)
    for page_index, (start, page_rows) in enumerate(summary_pages, 1):
        if not page_rows:
            continue
        content_source = 'market_study_data.summary'
        title = section_title('market', lang)
        if len(summary_pages) > 1:
            if start:
                content_source = f'market_study_data.summary:{start}:{start + len(page_rows)}'
            title += f' ({page_index}/{len(summary_pages)})'
        page_slide = take(content_source, title, 'editorial', 'market_summary')
        page_slide['market_row_start'] = start
        page_slide['market_row_end'] = start + len(page_rows)
        result.append(page_slide)

    one_block = _market_one_block_paragraph(market)
    if one_block:
        block_chunks = _market_one_block_chunks(one_block)
        chunk_cursor = 0
        for chunk_index, _chunk in enumerate(block_chunks, 1):
            content_source = 'market_study_data.one_block_summary'
            title = 'Market Study Summary' if lang == OFFER_LANG_ENGLISH else 'ملخص دراسة سوق العمل'
            if len(block_chunks) > 1:
                # Keep a stable source name for the single-slide case and a
                # bounded slice only when two slides are actually required.
                start = one_block.find(_chunk, chunk_cursor)
                if start < 0:
                    start = chunk_cursor
                content_source = f'market_study_data.one_block_summary:{max(start, 0)}:{max(start, 0) + len(_chunk)}'
                chunk_cursor = start + len(_chunk)
                title += f' - {chunk_index}'
            result.append(take(content_source, title, 'text'))

    source_pages = _market_source_pages(market)
    for page_index, (start, page_rows) in enumerate(source_pages, 1):
        if not page_rows:
            continue
        content_source = 'market_study_data.sources'
        title = 'Market Study Data Sources' if lang == OFFER_LANG_ENGLISH else 'مصادر دراسة السوق'
        if len(source_pages) > 1:
            if start:
                content_source = f'market_study_data.sources:{start}:{start + len(page_rows)}'
            title += f' ({page_index}/{len(source_pages)})'
        page_slide = take(content_source, title, 'editorial', 'market_sources')
        page_slide['market_row_start'] = start
        page_slide['market_row_end'] = start + len(page_rows)
        result.append(page_slide)

    # A market section can only own one chart, and it is always the competitor
    # comparison. This also protects plans produced before the deterministic
    # market renderer was introduced.
    _limit_presentation_charts({'market': result})
    return result


def normalize_market_section_plan(plan, project_data=None, offer_lang=None):
    """Repair a client/stored plan without rebuilding unrelated sections."""
    if not isinstance(plan, dict) or not isinstance(plan.get('slides'), list):
        return plan
    lang = resolve_offer_lang(project_data, offer_lang)
    market = _market_state(project_data)
    if not _market_has_required_data(market):
        return plan

    source_slides = [dict(slide) for slide in plan.get('slides') if isinstance(slide, dict)]
    current = ''
    market_indexes = []
    market_divider_indexes = []
    for index, slide in enumerate(source_slides):
        section_key = _slide_section_key(slide, current)
        if slide.get('type') == 'section_divider':
            current = section_key
            if section_key == 'market':
                market_divider_indexes.append(index)
            continue
        current = section_key
        if section_key == 'market' and slide.get('type') not in ('cover', 'index', 'closing'):
            market_indexes.append(index)

    existing = [source_slides[index] for index in market_indexes]
    normalized_market = _normalize_market_group_slides(existing, market, offer_lang=lang)
    if not normalized_market and not market_indexes:
        return plan

    if not market_divider_indexes:
        market_divider = {
            'title': section_title('market', lang),
            'type': 'section_divider',
            'section_key': 'market',
            'design_style': 'divider',
            'content_density': 'low',
            'requires_image': False,
            'bullets': [],
        }
        normalized_market = [market_divider] + list(normalized_market)

    if market_indexes:
        insertion_index = min(market_indexes)
    elif market_divider_indexes:
        insertion_index = min(market_divider_indexes) + 1
    else:
        insertion_index = next((index for index, slide in enumerate(source_slides)
                                if slide.get('type') == 'closing'), len(source_slides))

    market_index_set = set(market_indexes)
    output = []
    inserted = False
    for index, slide in enumerate(source_slides):
        if index == insertion_index and not inserted:
            output.extend(normalized_market)
            inserted = True
        if index in market_index_set:
            continue
        output.append(slide)
    if not inserted:
        output.extend(normalized_market)

    normalized = dict(plan)
    normalized['slides'] = output
    return refresh_index_entries(normalized)


def _rows_have_comparable_numbers(rows):
    values = []
    for row in rows if isinstance(rows, list) else []:
        cells = row.values() if isinstance(row, dict) else row if isinstance(row, (list, tuple)) else []
        for value in cells:
            text = str(value or '').replace(',', '').replace('٬', '').strip()
            if re.fullmatch(r'-?\d+(?:\.\d+)?%?', text):
                values.append(text)
    return len(values) >= 2


def _is_substantive_financial_cell(val, label=''):
    s = str(val or '').strip()
    if not s or s in ('—', '-', 'null', 'undefined'):
        return False
    if s in ('لا', 'no', 'غير مفعل', 'غير مطبق', 'معطل', 'لا يوجد'):
        return False
    if s in ('0', '0.00', '0%', '0.0%', '0 ر.س', '0 م²') and any(k in str(label) for k in ('سماح', 'خصم', 'أتعاب إضافية')):
        return False
    return True


def _filter_substantive_financial_rows(rows, part_type='table'):
    if not isinstance(rows, list):
        return []
    filtered = []
    for row in rows:
        if isinstance(row, (list, tuple)):
            if len(row) >= 2:
                label, val = row[0], row[1]
                if _is_substantive_financial_cell(val, label):
                    filtered.append(row)
            elif any(_is_substantive_financial_cell(c) for c in row):
                filtered.append(row)
        elif isinstance(row, dict):
            if any(_is_substantive_financial_cell(v, k) for k, v in row.items()):
                filtered.append(row)
        elif _is_substantive_financial_cell(row):
            filtered.append(row)
    return filtered
