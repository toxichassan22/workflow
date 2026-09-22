

def _ensure_required_plan_content(groups, project_data=None, images=None, tenant_id=None, offer_lang=None):
    source = project_data if isinstance(project_data, dict) else {}
    lang = resolve_offer_lang(source, offer_lang)
    images = images if isinstance(images, dict) else {}
    map_placeholders = images.get('map_placeholders') if isinstance(images.get('map_placeholders'), dict) else {}
    has_map_context = any(str(source.get(key) or '').strip() for key in (
        'location_address', 'location_lat', 'location_lng', 'site_analysis')) or any(map_placeholders.values())
    overview_map_tokens = ['##MAP_OVERVIEW##'] if has_map_context else []

    def add(section_key, slide, replace=False):
        slide = _canonicalize_slide_image_tokens(dict(slide))
        slide['section_key'] = section_key
        if replace:
            groups[section_key] = []
        signature = _plan_slide_signature(slide)
        if any(_plan_slide_signature(existing) == signature for existing in groups.get(section_key, [])):
            return
        groups.setdefault(section_key, []).append(slide)

    _reserve_media_sections(groups)
    # The visual-concept sections are a strict media-only area.  A planner may
    # still return an older summary/table slide (for example, a generic
    # "المخطط العام" slide) alongside the uploaded assets.  Keeping it here
    # makes it survive normalization and appear before the real plan images.
    # Start these sections from zero so every full or section regeneration is
    # rebuilt from the persisted media, not from stale model-authored content.
    groups['exterior'] = []
    groups['plans'] = []
    groups['interior'] = []
    used_media_tokens = _deduplicate_plan_media(groups)
    moodboard_tokens = [f'##MOODBOARD_IMAGE_{index}##' for index, _item in _available_asset_items(images.get('moodboard'))]
    if not groups.get('overview') and source:
        add('overview', {
            'title': section_title('overview', lang), 'type': 'content', 'design_style': 'text',
            'content_density': 'medium', 'requires_image': False,
            'content_source': 'project_overview', 'image_tokens': [], 'bullets': [],
        })
    elif groups.get('overview'):
        groups['overview'][0]['title'] = section_title('overview', lang)
        groups['overview'][0]['content_source'] = groups['overview'][0].get('content_source') or 'project_overview'

    # Ensure all 4 canonical location maps (Overview, Access, Catchment, Landmarks) are mandatorily present
    existing_loc = list(groups.get('location', []))
    loc_by_token = {}
    for s in existing_loc:
        t = str(s.get('type') or '')
        c_src = str(s.get('content_source') or '')
        imgs = [str(x) for x in (s.get('image_tokens') or [])]
        if '##MAP_OVERVIEW##' in imgs or t == 'map_overview' or c_src == 'location_polygon':
            loc_by_token.setdefault('overview', s)
        elif '##MAP_ACCESS##' in imgs or t == 'map_access' or c_src == 'main_roads':
            loc_by_token.setdefault('access', s)
        elif '##MAP_CATCHMENT##' in imgs or t == 'map_catchment' or c_src == 'catchment_areas':
            loc_by_token.setdefault('catchment', s)
        elif '##MAP_LANDMARKS##' in imgs or t == 'map_landmarks' or c_src == 'nearby_landmarks':
            loc_by_token.setdefault('landmarks', s)

    required_map_specs = [
        ('overview', {
            'title': 'Site Location & Plot Boundary' if lang == OFFER_LANG_ENGLISH else 'الموقع العام وحدود الأرض',
            'type': 'map_overview',
            'section_key': 'location',
            'design_style': 'map',
            'content_density': 'medium',
            'requires_image': True,
            'content_source': 'location_polygon',
            'image_tokens': ['##MAP_OVERVIEW##'],
            'bullets': (['Strategic site location and plot boundary', 'Direct link to the surrounding urban fabric']
                        if lang == OFFER_LANG_ENGLISH else
                        ['موقع المشروع الاستراتيجي وحدود الأرض', 'الربط المباشر مع النسيج الحضري المحيط']),
        }),
        ('access', {
            'title': 'Road Network & Accessibility' if lang == OFFER_LANG_ENGLISH else 'شبكة الطرق وسهولة الوصول',
            'type': 'map_access',
            'section_key': 'location',
            'design_style': 'map',
            'content_density': 'medium',
            'requires_image': True,
            'content_source': 'main_roads',
            'image_tokens': ['##MAP_ACCESS##'],
            'bullets': (['Key arterials and streets serving the site', 'Smooth and fluid traffic movement']
                        if lang == OFFER_LANG_ENGLISH else
                        ['المحاور الرئيسية والشوارع المؤدية للموقع', 'سهولة وانسيابية الحركة المرورية']),
        }),
        ('catchment', {
            'title': 'Catchment & Area of Influence' if lang == OFFER_LANG_ENGLISH else 'نطاق الخدمة والتأثير الجغرافي',
            'type': 'map_catchment',
            'section_key': 'location',
            'design_style': 'map',
            'content_density': 'medium',
            'requires_image': True,
            'content_source': 'catchment_areas',
            'image_tokens': ['##MAP_CATCHMENT##'],
            'bullets': (['Drive-time and population reach around the project', 'Population mass and demand in the target catchment']
                        if lang == OFFER_LANG_ENGLISH else
                        ['نطاقات الوصول الزمني والسكاني حول المشروع', 'الكتلة السكانية والطلب في النطاق المستهدف']),
        }),
        ('landmarks', {
            'title': 'Landmarks & Nearby Amenities' if lang == OFFER_LANG_ENGLISH else 'المعالم الحيوية والمرافق المجاورة',
            'type': 'map_landmarks',
            'section_key': 'location',
            'design_style': 'map',
            'content_density': 'medium',
            'requires_image': True,
            'content_source': 'nearby_landmarks',
            'image_tokens': ['##MAP_LANDMARKS##'],
            'bullets': (['Key facilities, services and nearby destinations', 'Distances and estimated drive times']
                        if lang == OFFER_LANG_ENGLISH else
                        ['أهم المرافق والخدمات والوجهات المحيطة', 'المسافات وأزمنة الوصول التقديرية بالسيارة']),
        }),
    ]

    mandatory_location_slides = []
    for key, spec in required_map_specs:
        existing = loc_by_token.get(key)
        if existing:
            existing['section_key'] = 'location'
            existing['type'] = spec['type']
            existing['requires_image'] = True
            token = spec['image_tokens'][0]
            existing_tokens = list(existing.get('image_tokens') or [])
            if token not in existing_tokens:
                existing_tokens.insert(0, token)
            existing['image_tokens'] = existing_tokens
            mandatory_location_slides.append(existing)
        else:
            mandatory_location_slides.append(spec)

    other_location_slides = [s for s in existing_loc if s not in loc_by_token.values()]
    groups['location'] = mandatory_location_slides + other_location_slides

    moodboard_items = _available_asset_items(images.get('moodboard'))
    moodboard_meta = images.get('moodboard_meta') if isinstance(images.get('moodboard_meta'), list) else []
    groups['exterior'] = [slide for slide in groups.get('exterior', [])
                          if not any(token.startswith('##MOODBOARD_IMAGE_') for token in (slide.get('image_tokens') or []))]
    uncovered_ext = moodboard_items
    if len(moodboard_items) > 1:
        for group_number, chunk in enumerate(_pair_media_chunks(moodboard_items), 1):
            tokens = [f'##MOODBOARD_IMAGE_{idx}##' for idx, _ in chunk]
            titles = [str(moodboard_meta[idx - 1].get('label') if idx <= len(moodboard_meta) and isinstance(moodboard_meta[idx - 1], dict) else it.get('label') or (f'Exterior Concept {idx}' if lang == OFFER_LANG_ENGLISH else f'التصور الخارجي {idx}')).strip() for idx, it in chunk]
            combined_title = ' — '.join(titles) if len(titles) > 1 else titles[0]
            if len(moodboard_items) > 2:
                combined_title = (f'Exterior Concepts — {group_number}' if lang == OFFER_LANG_ENGLISH
                                  else f'التصورات الخارجية — {group_number}')
            bullets = [str(moodboard_meta[idx - 1].get('caption') if idx <= len(moodboard_meta) and isinstance(moodboard_meta[idx - 1], dict) else it.get('caption') or '').strip() for idx, it in chunk]
            add('exterior', {
                'title': combined_title, 'type': 'content', 'design_style': 'image',
                'content_density': 'medium' if len(chunk) > 1 else 'low', 'requires_image': True,
                'content_source': f'exterior_images_group:{chunk[0][0]}:{chunk[-1][0]}',
                'image_tokens': tokens, 'image_layout': f'balanced_{len(chunk)}',
                'bullets': [], 'captions': bullets,
                'description': ' — '.join(b for b in bullets if b), 'media_only': True,
            })
    else:
        for index, item in uncovered_ext:
            meta = moodboard_meta[index - 1] if index <= len(moodboard_meta) and isinstance(moodboard_meta[index - 1], dict) else {}
            title = str(meta.get('label') or item.get('label') or (f'Exterior Concept {index}' if lang == OFFER_LANG_ENGLISH else f'التصور الخارجي {index}')).strip()
            caption = str(meta.get('caption') or item.get('caption') or '').strip()
            add('exterior', {
                'title': title, 'type': 'content', 'design_style': 'image',
                'content_density': 'low', 'requires_image': True,
                'content_source': f'exterior_image:{index}',
                'image_tokens': [f'##MOODBOARD_IMAGE_{index}##'],
                'bullets': [], 'description': caption,
                'captions': [caption] if caption else [], 'media_only': True,
            })

    land_items = _available_asset_items(images.get('land_photos'))
    groups['land'] = [slide for slide in groups.get('land', [])
                      if not any(token.startswith('##LAND_PHOTO_') for token in (slide.get('image_tokens') or []))]
    uncovered_land = land_items
    if len(land_items) > 1:
        for group_number, chunk in enumerate(_balanced_media_chunks(land_items), 1):
            tokens = [f'##LAND_PHOTO_{idx}##' for idx, _ in chunk]
            titles = [str(it.get('name') or (f'Site Photo {idx}' if lang == OFFER_LANG_ENGLISH else f'صورة الأرض {idx}')).strip() for idx, it in chunk]
            combined_title = ' — '.join(titles) if len(titles) > 1 else titles[0]
            if len(land_items) > 2:
                combined_title = (f'Site Photos — {group_number}' if lang == OFFER_LANG_ENGLISH
                                  else f'صور الأرض — {group_number}')
            bullets = [str(it.get('description') or it.get('caption') or '').strip() for _, it in chunk]
            add('land', {
                'title': combined_title, 'type': 'content', 'design_style': 'image',
                'content_density': 'medium' if len(chunk) > 1 else 'low', 'requires_image': True,
                'content_source': f'land_photos_group:{chunk[0][0]}:{chunk[-1][0]}',
                'image_tokens': tokens, 'image_layout': f'balanced_{len(chunk)}',
                'bullets': [b for b in bullets if b],
            })
    else:
        for index, item in uncovered_land:
            description = str(item.get('description') or item.get('caption') or '').strip()
            title = str(item.get('name') or (f'Site Photo {index}' if lang == OFFER_LANG_ENGLISH else f'صورة الأرض {index}')).strip()
            add('land', {
                'title': title, 'type': 'content', 'design_style': 'image',
                'content_density': 'low', 'requires_image': True,
                'content_source': f'land_photo:{index}',
                'image_tokens': [f'##LAND_PHOTO_{index}##'],
                'bullets': [description] if description else [],
            })

    if _has_land_specs_data(source):
        specs_slides = [slide for slide in groups.get('land', [])
                        if slide.get('content_source') == 'land_specs'
                        or slide.get('design_style') == 'specs'
                        or re.search(r'(?:مواصفات الأرض|الاشتراطات التنظيمية|اشتراطات البناء|land specs|regulatory)', str(slide.get('title') or ''), re.IGNORECASE)]
        groups['land'] = [slide for slide in groups.get('land', []) if slide not in specs_slides]
        canonical_specs = dict(specs_slides[0]) if specs_slides else {}
        canonical_specs.update({
            'title': 'Land Specifications & Regulatory Conditions' if lang == OFFER_LANG_ENGLISH else 'مواصفات الأرض والاشتراطات التنظيمية',
            'type': 'content',
            'design_style': 'specs',
            'content_density': 'high',
            'requires_image': False,
            'content_source': 'land_specs',
            'bullets': [],
        })
        add('land', canonical_specs)

    has_boundary_data = _has_land_boundary_data(source)
    if has_boundary_data:
        directional = [slide for slide in groups.get('land', [])
                       if slide.get('content_source') == 'land_boundary_diagram'
                       or slide.get('design_style') == 'diagram'
                       or re.search(r'(?:مخطط اتجاهي|حدود الأرض والواجهات|directional|plot boundary|boundary diagram)', str(slide.get('title') or ''), re.IGNORECASE)]
        groups['land'] = [slide for slide in groups.get('land', []) if slide not in directional]
        canonical = dict(directional[0]) if directional else {}
        canonical.update({
            'title': 'Directional Plot Boundary Diagram' if lang == OFFER_LANG_ENGLISH else 'مخطط اتجاهي لحدود الأرض',
            'type': 'content',
            'design_style': 'diagram',
            'content_density': 'medium',
            'requires_image': False,
            'content_source': 'land_boundary_diagram',
            'bullets': [],
        })
        add('land', canonical)

    plans = _available_asset_items(images.get('plans'))
    plan_meta = images.get('plan_meta') if isinstance(images.get('plan_meta'), list) else []
    groups['plans'] = [slide for slide in groups.get('plans', [])
                       if not any(token.startswith('##PLAN_IMAGE_') for token in (slide.get('image_tokens') or []))]
    for index, item in plans:
        meta = plan_meta[index - 1] if index <= len(plan_meta) and isinstance(plan_meta[index - 1], dict) else {}
        title = str(meta.get('title') or meta.get('name') or item.get('title') or (f'Plan {index}' if lang == OFFER_LANG_ENGLISH else f'المخطط {index}')).strip()
        description = str(meta.get('description') or item.get('description') or '').strip()
        add('plans', {
            'title': title, 'type': 'content', 'design_style': 'image',
            'content_density': 'low', 'requires_image': True,
            'content_source': f'plan_image:{index}', 'source_table': 'conceptual_plans',
            'image_tokens': [f'##PLAN_IMAGE_{index}##'], 'image_layout': 'single',
            'bullets': [], 'description': description,
            'captions': [description] if description else [], 'media_only': True,
        })

    interior_components = images.get('interior_components') if isinstance(images.get('interior_components'), list) else []
    groups['interior'] = [slide for slide in groups.get('interior', [])
                          if not any(token.startswith('##INTERIOR_COMP_') for token in (slide.get('image_tokens') or []))]
    for component_index, component in enumerate(interior_components, 1):
        if not isinstance(component, dict):
            continue
        component_name = str(component.get('name') or (f'Component {component_index}' if lang == OFFER_LANG_ENGLISH else f'المكون {component_index}')).strip()
        comp_items = _available_asset_items(component.get('images'))
        uncovered_comp_items = comp_items
        if len(comp_items) > 1:
            for chunk in _pair_media_chunks(comp_items):
                tokens = [f'##INTERIOR_COMP_{component_index}_IMG_{j}##' for j, _ in chunk]
                labels = [str(it.get('label') or '').strip() for _, it in chunk]
                label_parts = [l for l in labels if l and l != component_name]
                combined_title = f'{component_name} — ' + ' / '.join(label_parts) if label_parts else component_name
                bullets = [str(it.get('caption') or '').strip() for _, it in chunk]
                add('interior', {
                    'title': combined_title, 'type': 'content', 'design_style': 'image',
                    'content_density': 'medium' if len(chunk) > 1 else 'low', 'requires_image': True,
                    'content_source': f'interior_images_group:{component_index}:{chunk[0][0]}:{chunk[-1][0]}',
                    'image_tokens': tokens, 'image_layout': f'balanced_{len(chunk)}',
                    'bullets': [], 'captions': bullets,
                    'description': ' — '.join(b for b in bullets if b),
                    'component_name': component_name, 'media_only': True,
                })
        else:
            for image_index, item in uncovered_comp_items:
                label = str(item.get('label') or '').strip()
                caption = str(item.get('caption') or '').strip()
                title = f'{component_name} — {label}' if (label and label != component_name) else component_name
                add('interior', {
                    'title': title,
                    'type': 'content', 'design_style': 'image', 'content_density': 'low',
                    'requires_image': True,
                    'content_source': f'interior_image:{component_index}:{image_index}',
                    'image_tokens': [f'##INTERIOR_COMP_{component_index}_IMG_{image_index}##'],
                    'bullets': [], 'description': caption,
                    'captions': [caption] if caption else [],
                    'component_name': component_name, 'media_only': True,
                })

    components = _project_component_rows(source)
    if components:
        groups['components'] = []
        for start in range(0, len(components), 6):
            chunk = components[start:start + 6]
            number = start // 6 + 1
            add('components', {
                'title': section_title('components', lang) + (f' — {number}' if len(components) > 6 else ''),
                'type': 'content', 'design_style': 'table', 'content_density': 'high',
                'requires_image': False, 'content_source': f'project_components:{start}:{start + len(chunk)}',
                'bullets': [],
            })

    phases = parse_timeline_phases(source)
    if phases:
        timeline_slides = [s for s in groups.get('timeline', []) if s.get('content_source') == 'timeline_table_data' or s.get('design_style') == 'timeline']
        if not timeline_slides:
            add('timeline', {
                'title': 'Timeline & Development Phases' if lang == OFFER_LANG_ENGLISH else 'الجدول الزمني ومراحل التطوير', 'type': 'content',
                'design_style': 'timeline', 'content_density': 'high', 'requires_image': False,
                'content_source': 'timeline_table_data', 'bullets': [],
            })
        else:
            for s in timeline_slides:
                if not s.get('content_source'):
                    s['content_source'] = 'timeline_table_data'

    model = _parse_financial_dict(source.get('financial_study_model'))
    if financial_study_has_real_input(model, _parse_financial_dict(source.get('financial_calc_data'))):
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        report = model.get('report') if isinstance(model.get('report'), dict) else {}
        report_parts = report.get('parts') if isinstance(report.get('parts'), list) else []
        groups['financial'] = []
        if report_parts:
            heading = 'Financial Study' if lang == OFFER_LANG_ENGLISH else 'الدراسة المالية'
            subheading = ''
            pending_tables = []

            def flush_pending_tables():
                for packed_slide in _pack_financial_table_slices(pending_tables, offer_lang=lang):
                    add('financial', packed_slide)
                pending_tables.clear()

            for part_index, part in enumerate(report_parts):
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
                rows = part.get('rows') if isinstance(part.get('rows'), list) else []
                rows = _filter_substantive_financial_rows(rows, part.get('type'))
                if not rows:
                    continue
                part_title = subheading or heading
                if part.get('type') == 'fields' and any(name in part_title for name in (
                        'التكاليف والاستثمار', 'مؤشرات العائد والاسترداد')):
                    continue
                target_section = 'financial'
                is_cashflow_part = any(t in part_title.lower() for t in ('تدفق', 'cashflow', 'cash_flow', 'نقدية', 'cash flow'))
                is_components_part = any(t in part_title for t in ('مكونات', 'components')) or 'مكونات' in heading
                column_ranges = _financial_column_ranges(part, title=part_title) if part.get('type') == 'table' else [(None, None)]
                # Narrow key/value tables stay readable with more rows per slide, so a
                # 14-row section does not burn two slides; wide tables keep the
                # tighter budget because each row costs more horizontal space.
                # Cash flow table is kept on a single slide with full rows.
                column_count = len(part.get('headers') or []) if part.get('type') == 'table' else 2
                max_rows_budget = 25 if is_cashflow_part else (16 if column_count <= 3 else 12)
                row_ranges = _balanced_row_ranges(
                    len(rows), max_per_slide=max_rows_budget, min_per_slide=4)
                is_assumption_part = (
                    bool(re.search(r'افتراض|assumption|متغير', part_title, re.IGNORECASE))
                    or any('متغير' in str(h) for h in (part.get('headers') or []))
                )
                chart_cand = '' if is_assumption_part else (
                    _financial_chart_type(part_title, index=part_index) if part.get('type') == 'table' else '')
                chartable_overall = (len(column_ranges) == 1 and len(row_ranges) == 1
                                     and part.get('type') == 'table'
                                     and bool(chart_cand)
                                     and _financial_table_chartable(part, rows, None, None))
                if (chart_cand in FINANCIAL_CHART_TYPES and not chartable_overall
                        and target_section == 'financial'
                        and chart_cand != 'heatmap'
                        and _can_chart_financial_part(chart_cand, part, model, project_data)):
                    flush_pending_tables()
                    if lang == OFFER_LANG_ENGLISH:
                        chart_titles = {
                            'combo': 'Annual & Cumulative Cash Flow',
                            'waterfall': 'Investment Cost Waterfall',
                            'heatmap': 'Financial Scenarios Heatmap',
                        }
                    else:
                        chart_titles = {
                            'combo': 'التدفقات النقدية السنوية والتراكمية',
                            'waterfall': 'تكوين إجمالي تكلفة المشروع',
                            'heatmap': 'مقارنة السيناريوهات المالية',
                        }
                    add(target_section, {
                        'title': chart_titles.get(chart_cand, part_title),
                        'type': 'content',
                        'design_style': 'chart',
                        'chart_type': chart_cand,
                        'content_density': 'high',
                        'requires_image': False,
                        'content_source': f'financial_chart:{chart_cand}:{part_index}',
                        'source_table': f'report_part_{part_index}',
                        'row_count': len(rows),
                        'financial_template': 'report',
                        'bullets': [],
                    })
                for row_number, (start, end) in enumerate(row_ranges, 1):
                    for column_number, (column_start, column_end) in enumerate(column_ranges, 1):
                        chart_cand = '' if is_assumption_part else _financial_chart_type(part_title, index=part_index)
                        chartable = (len(column_ranges) == 1 and start == 0 and column_number == 1
                                     and part.get('type') == 'table'
                                     and bool(chart_cand)
                                     and _financial_table_chartable(
                                         part, rows[start:end], column_start, column_end))
                        source_suffix = (f':{column_start}:{column_end}'
                                         if column_start is not None and column_end is not None else '')
                        part_source = f'financial_report:{part_index}:{start}:{end}{source_suffix}'
                        if chartable or column_start is not None or len(column_ranges) > 1 or is_cashflow_part or is_components_part:
                            # Chart slides and wide column-split tables own their slide:
                            # two six-column tables stacked vertically do not fit.
                            flush_pending_tables()
                            title_suffixes = []
                            if len(row_ranges) > 1:
                                title_suffixes.append(str(row_number))
                            if len(column_ranges) > 1:
                                title_suffixes.append((f'Part {column_number}' if lang == OFFER_LANG_ENGLISH
                                                       else f'جزء {column_number}'))
                            add(target_section, {
                                'title': part_title + (f" — {' / '.join(title_suffixes)}" if title_suffixes else ''),
                                'type': 'content', 'design_style': 'chart' if chartable else 'table',
                                'chart_type': chart_cand if chartable else '',
                                'content_density': 'high', 'requires_image': False,
                                'content_source': part_source,
                                'source_table': f'report_part_{part_index}', 'row_count': end - start,
                                'financial_template': 'report', 'bullets': [],
                            })
                        else:
                            pending_tables.append({
                                'title': part_title,
                                'suffix': str(row_number) if len(row_ranges) > 1 else '',
                                'source': part_source,
                                'source_table': f'report_part_{part_index}',
                                'row_count': end - start,
                            })
            flush_pending_tables()
            fin_slides = groups.get('financial', [])
            if not any(canonicalize_chart_type(s.get('chart_type')) == 'combo' for s in fin_slides) and (tables.get('cashflowTable') or tables.get('cashflow')):
                cf_rows = tables.get('cashflowTable') or tables.get('cashflow') or []
                add('financial', {
                    'title': 'Annual & Cumulative Cash Flow' if lang == OFFER_LANG_ENGLISH else 'التدفقات النقدية السنوية والتراكمية',
                    'type': 'content',
                    'design_style': 'chart',
                    'chart_type': 'combo',
                    'content_density': 'high',
                    'requires_image': False,
                    'content_source': f'financial_table:cashflowTable:0:{len(cf_rows)}',
                    'source_table': 'cashflowTable',
                    'row_count': len(cf_rows),
                    'financial_template': 'report',
                    'bullets': [],
                })
            if not any(canonicalize_chart_type(s.get('chart_type')) == 'waterfall' for s in fin_slides) and (tables.get('costTable') or tables.get('costs')):
                ct_rows = tables.get('costTable') or tables.get('costs') or []
                add('financial', {
                    'title': 'Investment Cost Waterfall' if lang == OFFER_LANG_ENGLISH else 'تكوين إجمالي تكلفة المشروع',
                    'type': 'content',
                    'design_style': 'chart',
                    'chart_type': 'waterfall',
                    'content_density': 'high',
                    'requires_image': False,
                    'content_source': f'financial_table:costTable:0:{len(ct_rows)}',
                    'source_table': 'costTable',
                    'row_count': len(ct_rows),
                    'financial_template': 'report',
                    'bullets': [],
                })
            if not any(canonicalize_chart_type(s.get('chart_type')) == 'heatmap' for s in fin_slides) and (tables.get('sensitivityTable') or tables.get('sensitivity')):
                st_rows = tables.get('sensitivityTable') or tables.get('sensitivity') or []
                add('financial', {
                    'title': 'Financial Scenarios Heatmap' if lang == OFFER_LANG_ENGLISH else 'مقارنة السيناريوهات المالية',
                    'type': 'content',
                    'design_style': 'chart',
                    'chart_type': 'heatmap',
                    'content_density': 'high',
                    'requires_image': False,
                    'content_source': f'financial_table:sensitivityTable:0:{len(st_rows)}',
                    'source_table': 'sensitivityTable',
                    'row_count': len(st_rows),
                    'financial_template': 'report',
                    'bullets': [],
                })
            # The heatmap is the visual summary of the results table.  Keep the
            # separate assumptions table too when it exists but was not included
            # in the extracted report parts.
            assumption_rows = tables.get('sensitivityAssumptionsTable')
            if (not isinstance(assumption_rows, list) or not assumption_rows) and isinstance(tables.get('sensitivity'), list):
                assumption_rows = tables.get('sensitivity')
            def is_assumptions_slide(s):
                text = ' '.join(str(s.get(key) or '') for key in ('title', 'content_source', 'source_table')).lower()
                source_match = re.fullmatch(r'financial_report:(\d+):\d+:\d+.*', str(s.get('content_source') or ''))
                if source_match:
                    text += ' ' + _financial_report_part_title(model, int(source_match.group(1))).lower()
                return (
                    'sensitivityassumptionstable' in text
                    or bool(re.search(r'افتراضات.*(?:حساسية|سيناريو)|(?:حساسية|سيناريو).*افتراضات|sensitivity assumptions|assumptions.*sensitivity', text))
                )

            has_assumptions = any(is_assumptions_slide(s) for s in groups.get('financial', []))
            if assumption_rows and not has_assumptions:
                add('financial', {
                    'title': 'Sensitivity Analysis Assumptions' if lang == OFFER_LANG_ENGLISH else 'افتراضات تحليل الحساسية', 'type': 'content',
                    'design_style': 'table', 'chart_type': '', 'content_density': 'high',
                    'requires_image': False,
                    'content_source': f'financial_table:sensitivityAssumptionsTable:0:{len(assumption_rows)}',
                    'source_table': 'sensitivityAssumptionsTable', 'row_count': len(assumption_rows),
                    'financial_template': 'report', 'bullets': [],
                })
        else:
            pending_tables = []

            def flush_pending_tables():
                for packed_slide in _pack_financial_table_slices(pending_tables, offer_lang=lang):
                    add('financial', packed_slide)
                pending_tables.clear()

            for table_key, title, style in _financial_plan_tables(lang):
                rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
                if not rows and table_key == 'componentsTable':
                    rows = _project_component_rows(source)
                if not rows:
                    continue
                first_keys = list(rows[0].keys()) if isinstance(rows[0], dict) else []
                is_cf = (table_key == 'cashflowTable')
                row_ranges = _balanced_row_ranges(
                    len(rows),
                    max_per_slide=25 if is_cf else (16 if first_keys and len(first_keys) <= 3 else 12),
                    min_per_slide=4)
                for number, (start, end) in enumerate(row_ranges, 1):
                    is_chart = (style == 'chart' and start == 0)
                    c_type = _financial_chart_type(title, table_key, number - 1) if is_chart else ''
                    item = {
                        'title': title,
                        'suffix': str(number) if len(row_ranges) > 1 else '',
                        'source': f'financial_table:{table_key}:{start}:{end}',
                        'source_table': table_key,
                        'row_count': end - start,
                    }
                    if c_type or table_key == 'componentsTable' or is_cf:
                        flush_pending_tables()
                        add('financial', {
                            'title': title + (f' — {number}' if len(row_ranges) > 1 else ''),
                            'type': 'content', 'design_style': 'chart' if c_type else 'table', 'chart_type': c_type,
                            'content_density': 'high', 'requires_image': False,
                            'content_source': item['source'], 'source_table': table_key,
                            'row_count': end - start, 'financial_template': 'report', 'bullets': [],
                        })
                    else:
                        pending_tables.append(item)
            flush_pending_tables()
        _attach_sensitivity_assumptions(groups, source)
        for summary_slide in _financial_summary_plan_slides(model):
            add('financial', summary_slide)

    team_entries = _selected_team_entries(source, tenant_id)
    if team_entries:
        groups['team'] = []
        for index, entry in enumerate(team_entries, 1):
            bullets = [str(entry.get(key) or '').strip() for key in ('الدور', 'نبذة', 'سنوات الخبرة', 'أعمال سابقة')]
            add('team', {
                'title': str(entry.get('الجهة') or (f'Entity {index}' if lang == OFFER_LANG_ENGLISH else f'الجهة {index}')).strip(),
                'type': 'content', 'design_style': 'image' if entry.get('_logo_file_id') else 'text',
                'content_density': 'medium', 'requires_image': bool(entry.get('_logo_file_id')),
                'content_source': f'team_member:{index}',
                'image_tokens': [f'##TEAM_LOGO_{index}##'] if entry.get('_logo_file_id') else [],
                'bullets': [value for value in bullets if value],
            })

    market = _decode_json_fact(source.get('market_study_data'))
    market = market if isinstance(market, dict) else {}
    competitors = market.get('competitors') if isinstance(market.get('competitors'), list) else []
    named_competitors = [c for c in competitors if _competitor_name(c)]
    if named_competitors:
        comp_ranges = _market_competitor_ranges(len(named_competitors))
        total_comp_pages = len(comp_ranges)
        existing_market = groups.get('market', [])
        comp_slides = [s for s in existing_market if str(s.get('content_source') or '').startswith('market_study_data.competitors')
                       or re.search(r'منافس|competitor', str(s.get('title') or ''), re.IGNORECASE)]
        if not comp_slides:
            for chunk_idx, (start, end) in enumerate(comp_ranges):
                c_title = 'Competitor Comparison' if lang == OFFER_LANG_ENGLISH else 'مقارنة المنافسين'
                c_source = 'market_study_data.competitors' if total_comp_pages == 1 else f'market_study_data.competitors:{start}:{end}'
                if total_comp_pages > 1:
                    c_title += f' ({chunk_idx + 1}/{total_comp_pages})'
                add('market', {
                    'title': c_title,
                    'type': 'content',
                    'design_style': 'chart',
                    'chart_type': 'horizontal_bar',
                    'content_density': 'high',
                    'requires_image': False,
                    'content_source': c_source,
                    'source_table': 'competitors',
                    'competitor_start': start,
                    'competitor_end': end,
                    'bullets': [],
                })
    executive = _decode_json_fact(source.get('executive_content'))
    executive = executive if isinstance(executive, dict) else {}
    swot = _extract_project_swot(source)
    risk_source, risk_items = _risk_analysis_source(source)
    groups['swot_risks'] = []
    if any(swot.values()):
        add('swot_risks', {
            'title': 'SWOT Analysis' if lang == OFFER_LANG_ENGLISH else 'تحليل SWOT', 'type': 'content', 'design_style': 'swot',
            'content_density': 'high', 'requires_image': False,
            'content_source': 'market_study_data.swot', 'bullets': [],
        })
    if risk_items:
        add('swot_risks', {
            'title': 'Risk Analysis & Mitigation' if lang == OFFER_LANG_ENGLISH else 'تحليل المخاطر وطرق المعالجة', 'type': 'content', 'design_style': 'risk',
            'content_density': 'high', 'requires_image': False,
            'content_source': risk_source, 'bullets': [],
        })
    if phases and not groups.get('timeline'):
        add('timeline', {
            'title': 'Timeline & Development Phases' if lang == OFFER_LANG_ENGLISH else 'الجدول الزمني ومراحل التطوير',
            'type': 'content', 'design_style': 'timeline',
            'content_density': 'high', 'requires_image': False,
            'content_source': 'timeline_table_data', 'bullets': [],
        })
    has_opp = bool(str(executive.get('opportunity') or '').strip())
    has_feat = bool(str(executive.get('features') or '').strip())
    has_sum = bool(str(executive.get('summary') or '').strip() or str(source.get('executive_summary') or '').strip())
    if has_opp or has_feat or has_sum:
        exec_source_re = re.compile(r'^executive_content\.(?:summary|opportunity|features)(?::\d*:\d*)?$')
        for key in list(groups):
            kept = [s for s in groups[key]
                    if not exec_source_re.match(str(s.get('content_source') or '').strip())]
            if len(kept) != len(groups[key]):
                groups[key] = kept
        existing_exec = list(groups.get('executive_summary', []))
        existing_by_source = {
            str(s.get('content_source') or '').strip(): dict(s)
            for s in existing_exec
            if str(s.get('content_source') or '').strip()
        }
        groups['executive_summary'] = []

        def exec_page_source(base, start, count, total_pages):
            return base if total_pages == 1 or start == 0 else f'{base}:{start}:{start + count}'

        def exec_page_slide(base_slide, base, title_ar, title_en, start, rows, total_pages, index):
            page_slide = dict(base_slide)
            title = title_en if lang == OFFER_LANG_ENGLISH else title_ar
            if total_pages > 1:
                title += f' ({index}/{total_pages})'
            page_slide.update({
                'title': title,
                'type': 'content',
                'section_key': 'executive_summary',
                'design_style': 'editorial',
                'content_density': 'high',
                'requires_image': False,
                'content_source': exec_page_source(base, start, len(rows), total_pages),
                'image_tokens': [],
                'market_row_start': start,
                'market_row_end': start + len(rows),
                'bullets': [],
            })
            return page_slide

        if has_opp:
            opp_slide = existing_by_source.get('executive_content.opportunity') or {}
            opp_rows = [('', chunk) for chunk in _exec_text_chunks(str(executive.get('opportunity') or ''))]
            opp_pages = _budget_row_pages(opp_rows) or [(0, opp_rows)]
            for index, (start, page_rows) in enumerate(opp_pages, 1):
                add('executive_summary', exec_page_slide(
                    opp_slide, 'executive_content.opportunity',
                    'الفرصة الاستثمارية', 'Investment Opportunity',
                    start, page_rows, len(opp_pages), index))
        if has_feat:
            feat_slide = existing_by_source.get('executive_content.features') or {}
            feat_items = _executive_feature_items(source)
            feat_ranges = _balanced_row_ranges(len(feat_items), _executive_feature_page_size(feat_items)) or [(0, 0)]
            for index, (start, end) in enumerate(feat_ranges, 1):
                add('executive_summary', exec_page_slide(
                    feat_slide, 'executive_content.features',
                    'المميزات وفرص الاستثمار', 'Project Features & Opportunities',
                    start, feat_items[start:end], len(feat_ranges), index))
        if has_sum or (not has_opp and not has_feat):
            summary_slide = existing_by_source.get('executive_content.summary') or (existing_exec[0] if existing_exec and not has_opp and not has_feat else {})
            summary_pages = _executive_summary_pages(source) or [(0, [])]
            for index, (start, page_rows) in enumerate(summary_pages, 1):
                add('executive_summary', exec_page_slide(
                    summary_slide, 'executive_content.summary',
                    section_title('executive_summary', lang),
                    section_title('executive_summary', lang),
                    start, page_rows, len(summary_pages), index))

    if lang == OFFER_LANG_ENGLISH:
        summaries = (
            ('land', 'Land Analysis Summary', 'land_and_building_summary', str(source.get('land_and_building_summary') or '').strip()),
            ('location', 'Location Summary', 'site_analysis', str(source.get('site_analysis') or '').strip()),
            ('market', 'Project Market Executive Summary', 'market_study_data.one_block_summary', _market_one_block_paragraph(market)),
        )
        summary_match = re.compile(r'summary', re.IGNORECASE).search
    else:
        summaries = (
            ('land', 'ملخص تحليل الأرض', 'land_and_building_summary', str(source.get('land_and_building_summary') or '').strip()),
            ('location', 'ملخص الموقع الجغرافي', 'site_analysis', str(source.get('site_analysis') or '').strip()),
            ('market', 'الملخص التنفيذي لسوق المشروع', 'market_study_data.one_block_summary', _market_one_block_paragraph(market)),
        )
        summary_match = re.compile(r'ملخص').search
    for section_key, title, content_source, value in summaries:
        if not value:
            continue
        summary_tokens = overview_map_tokens if section_key == 'location' else []
        summary_style = 'map' if summary_tokens else 'text'

        if section_key == 'location' and content_source == 'site_analysis':
            paragraphs = [part.strip() for part in re.split(r'\r?\n\s*\r?\n', value) if part.strip()]
            if not paragraphs:
                paragraphs = [p.strip() for p in value.splitlines() if p.strip()] or [value]
            if len(paragraphs) >= 3 or len(value) > 600:
                half = max(1, math.ceil(len(paragraphs) / 2))
                title_1 = f'{title} (1/2)'
                title_2 = f'{title} (2/2)'
                slide_1 = {
                    'title': title_1,
                    'type': 'content',
                    'design_style': summary_style,
                    'content_density': 'medium',
                    'requires_image': bool(summary_tokens),
                    'content_source': f'site_analysis:0:{half}',
                    'image_tokens': summary_tokens,
                    'bullets': [],
                    'section_key': 'location',
                }
                slide_2 = {
                    'title': title_2,
                    'type': 'content',
                    'design_style': 'editorial',
                    'content_density': 'medium',
                    'requires_image': False,
                    'content_source': f'site_analysis:{half}:',
                    'image_tokens': [],
                    'bullets': [],
                    'section_key': 'location',
                }
                groups['location'] = [
                    s for s in groups.get('location', [])
                    if not str(s.get('content_source') or '').startswith('site_analysis')
                    and not summary_match(str(s.get('title') or ''))
                ]
                groups['location'].extend([slide_1, slide_2])
                continue

        existing = next((slide for slide in groups.get(section_key, [])
                         if slide.get('content_source') == content_source or summary_match(str(slide.get('title') or ''))), None)
        if existing:
            groups[section_key].remove(existing)
            existing.update({'title': title, 'content_source': content_source,
                             'design_style': summary_style, 'section_key': section_key,
                             'requires_image': bool(summary_tokens), 'image_tokens': summary_tokens})
            groups[section_key].append(existing)
        else:
            add(section_key, {
                'title': title, 'type': 'content', 'design_style': summary_style,
                'content_density': 'medium', 'requires_image': bool(summary_tokens),
                'content_source': content_source, 'image_tokens': summary_tokens, 'bullets': [],
            })

    # The market section has a stricter contract than the other sections:
    # canonical tables and the single approved chart are rendered from the
    # stored market data, while stale map/image requests are repaired here.
    groups['market'] = _normalize_market_group_slides(groups.get('market', []), market, offer_lang=lang)
    _merge_sparse_plan_slides(groups)
    _merge_adjacent_table_slides(groups, offer_lang=lang)
    _limit_presentation_charts(groups)
    _deduplicate_plan_media(groups)

    land_keys = ('croquis_land_area', 'approved_financial_area', 'boundary_lengths',
                 'surrounding_streets', 'facades_count', 'facades_directions',
                 'directions_table', 'land_documents_analysis_data',
                 'landDocumentsAnalysisData', 'land_documents_analysis',
                 'building_ratio_coverage', 'setbacks', 'max_floors_height',
                 'allowed_uses', 'regulatory_constraints', 'land_and_building_summary')
    location_keys = ('location_address', 'location_lat', 'location_lng', 'city', 'district',
                     'main_roads', 'nearby_landmarks', 'city_landmarks',
                     'catchment_areas', 'site_analysis')
    has_interior = any(_available_asset_items(component.get('images'))
                       for component in interior_components if isinstance(component, dict))
    map_placeholders = images.get('map_placeholders') if isinstance(images.get('map_placeholders'), dict) else {}
    has_location = (any(str(source.get(key) or '').strip() for key in location_keys)
                    or any(map_placeholders.values()))
    availability = {
        'overview': bool(source),
        'components': bool(components),
        'land': bool(land_items or any(str(source.get(key) or '').strip() for key in land_keys)),
        'location': bool(has_location),
        'market': bool(_readable_fact(market)),
        'timeline': bool(phases),
        'financial': financial_study_has_real_input(model, _parse_financial_dict(source.get('financial_calc_data'))),
        'swot_risks': bool(any(swot.values()) or risk_items),
        'team': bool(team_entries),
        'plans': bool(plans),
        'exterior': bool(moodboard_items),
        'interior': has_interior,
        'executive_summary': bool(
            str(executive.get('summary') or '').strip()
            or str(executive.get('opportunity') or '').strip()
            or str(executive.get('features') or '').strip()
            or str(source.get('executive_summary') or '').strip()
        ),
    }
    for section_key, available in availability.items():
        if not available:
            groups[section_key] = []


def refresh_index_entries(plan, offer_lang=None):
    if not isinstance(plan, dict) or not isinstance(plan.get('slides'), list):
        return plan
    lang = resolve_offer_lang(None, offer_lang if offer_lang is not None else (plan.get('offer_lang') if isinstance(plan, dict) else None))
    entries = []
    seen = set()
    current_section = ''
    for page, slide in enumerate(plan['slides'], 1):
        if not isinstance(slide, dict):
            continue
        slide_type = str(slide.get('type') or '').strip().lower()
        if slide_type in ('cover', 'index'):
            continue
        section_key = str(slide.get('section_key') or slide.get('sectionKey') or '').strip().lower()
        section_key = _SECTION_KEY_ALIASES.get(section_key, section_key)
        if not section_key or section_key in ('cover', 'index'):
            section_key = _slide_section_key(slide, current_section)
        if not section_key or section_key in ('cover', 'index'):
            continue
        if section_key not in PRESENTATION_SECTION_ORDER:
            continue
        current_section = section_key
        if section_key in seen:
            continue
        seen.add(section_key)
        entries.append({'section_key': section_key,
                        'title': section_title(section_key, lang), 'page': page})
    for slide in plan['slides']:
        if isinstance(slide, dict) and str(slide.get('type') or '').strip().lower() == 'index':
            slide['title'] = offer_chrome('index_heading', lang)
            slide['design_style'] = 'text'
            slide['index_entries'] = entries
            slide['bullets'] = []
            break
    plan['proposed_count'] = len(plan['slides'])
    return plan


def filter_presentation_plan_sections(plan, section_keys):
    if not isinstance(plan, dict) or not isinstance(plan.get('slides'), list):
        return None
    requested = {
        _SECTION_KEY_ALIASES.get(str(key or '').strip().lower(), str(key or '').strip().lower())
        for key in (section_keys or [])
    }
    requested.intersection_update(PRESENTATION_SECTION_ORDER)
    if not requested:
        return None

    slides = [slide for slide in plan['slides'] if isinstance(slide, dict)]
    cover = next((slide for slide in slides if slide.get('type') == 'cover'), None)
    index = next((slide for slide in slides if slide.get('type') == 'index'), None)
    closing = next((slide for slide in reversed(slides) if slide.get('type') == 'closing'), None)
    body = [
        slide for slide in slides
        if slide.get('type') not in ('cover', 'index', 'closing')
        and _slide_section_key(slide) in requested
    ]
    if not body and not ('closing' in requested and closing):
        return None

    selected = []
    if cover:
        selected.append(cover)
    if index:
        selected.append(index)
    selected.extend(body)
    if closing:
        selected.append(closing)
    filtered = dict(plan)
    filtered['slides'] = selected
    return refresh_index_entries(filtered)


def normalize_presentation_plan(plan, project_data=None, images=None, tenant_id=None, offer_lang=None):
    if not isinstance(plan, dict):
        plan = {}
    lang = resolve_offer_lang(project_data, offer_lang)
    source_slides = plan.get('slides') if isinstance(plan.get('slides'), list) else []
    source_slides = [_canonicalize_slide_image_tokens(dict(slide))
                     for slide in source_slides if isinstance(slide, dict)]
    cover = next((slide for slide in source_slides if slide.get('type') == 'cover'), None)
    if cover is None and source_slides:
        cover = source_slides[0]
    cover = dict(cover or {})
    cover.update({'title': offer_chrome('cover', lang), 'type': 'cover', 'section_key': 'cover',
                  'design_style': 'image', 'requires_image': True,
                  'image_tokens': ['##IMAGE_COVER##'], 'image_layout': None})
    index = next((slide for slide in source_slides if slide.get('type') == 'index'), None)
    index = dict(index or {})
    index.update({'title': offer_chrome('index', lang), 'type': 'index', 'section_key': 'index',
                  'design_style': 'text', 'requires_image': False, 'bullets': []})
    closing = next((slide for slide in reversed(source_slides) if slide.get('type') == 'closing'), None)
    if closing is None and source_slides:
        closing = source_slides[-1]
    closing = dict(closing or {})
    has_cover_image = bool((images or {}).get('cover')) if isinstance(images, dict) else False
    closing.update({'title': section_title('closing', lang), 'type': 'closing',
                    'section_key': 'closing', 'design_style': 'image' if has_cover_image else 'minimal',
                    'requires_image': has_cover_image, 'content_source': 'contact_closing',
                    'image_tokens': ['##IMAGE_COVER##'] if has_cover_image else [], 'bullets': []})

    groups = {key: [] for key in PRESENTATION_SECTION_ORDER if key != 'closing'}
    signatures = set()
    current = ''
    for slide in source_slides:
        slide = _normalize_land_boundary_slide(slide)
        slide = _normalize_location_map_slide(slide)
        slide = _normalize_financial_slide(slide)
        slide_type = str(slide.get('type') or 'content')
        if slide is cover or slide is index or slide is closing or slide_type in ('cover', 'index', 'closing'):
            continue
        section_key = _slide_section_key(slide, current)
        if _is_fixed_section_divider(slide, section_key):
            current = section_key
            continue
        if slide_type == 'section_divider':
            current = section_key
            continue
        current = section_key
        if section_key == 'closing':
            continue
        item = dict(slide)
        item['section_key'] = section_key
        if item.get('type') == 'moodboard':
            if not _available_asset_items((images or {}).get('moodboard') if isinstance(images, dict) else []):
                continue
            item['type'] = 'content'
            item['design_style'] = 'image'
        signature = (section_key,) + _plan_slide_signature(item)
        if signature in signatures:
            continue
        signatures.add(signature)
        groups.setdefault(section_key, []).append(item)

    _ensure_required_plan_content(groups, project_data, images, tenant_id, offer_lang=lang)
    _drop_redundant_generic_slides(groups, offer_lang=lang)

    if not any(groups.values()) and project_data:
        groups['overview'].append({
            'title': section_title('overview', lang), 'type': 'content',
            'section_key': 'overview', 'design_style': 'text', 'content_density': 'medium',
            'requires_image': False,
            'bullets': (['Project definition from approved data', 'Approved concept and uses',
                         'Concise summary without repetition']
                        if lang == OFFER_LANG_ENGLISH else
                        ['تعريف المشروع من البيانات المعتمدة', 'الفكرة والاستخدامات المعتمدة',
                         'ملخص موجز دون تكرار']),
        })

    slides = [cover, index]
    for section_key in PRESENTATION_SECTION_ORDER:
        if section_key == 'closing' or not groups.get(section_key):
            continue
        slides.append({
            'title': section_title(section_key, lang), 'type': 'section_divider',
            'section_key': section_key, 'design_style': 'divider', 'content_density': 'low',
            'requires_image': section_key != 'market', 'bullets': [],
        })
        slides.extend(groups[section_key])
    slides.append(closing)
    normalized = dict(plan)
    normalized['slides'] = slides
    normalized['offer_lang'] = lang
    normalized['engine_version'] = SLIDE_ENGINE_VERSION
    return refresh_index_entries(normalized, offer_lang=lang)


def _suggest_design_style(title, bullets=None, slide_type='content'):
    """Pick a varied design style from the title, bullets, and slide type."""
    title = (title or '').lower()
    bullets_text = ' '.join(b or '' for b in (bullets or [])).lower()
    text = f"{title} {bullets_text}"

    fixed = {
        'cover': 'image',
        'index': 'text',
        'section_divider': 'divider',
        'moodboard': 'image',
        'closing': 'minimal',
    }
    if slide_type in fixed:
        return fixed[slide_type]
    if slide_type.startswith('map_') or slide_type == 'site_specs':
        return 'map'

    if re.search(r'(?:مؤشر|أداء|قيمة مضافة|عائد|roi|noi|ربح|تكلفة|مالي|جدوى|إيراد|نسبة|رقم|إحصائية|تكلفة|دخل|استثمار|profit|cost|financial|revenue)', text):
        if re.search(r'(?:توزيع|مساحات|حصص|نسب الاستخدام|مصادر التمويل|pie|donut)', text):
            return 'pie'
        if re.search(r'(?:حساسية|سيناريو|نطاق|مخاطر العائد|candlestick)', text):
            return 'candlestick'
        if re.search(r'(?:سحب|سداد|تدفق نقدي|قنوات|pipeline|flow)', text):
            return 'flow'
        return 'dashboard'
    if re.search(r'(?:توزيع الوحدات|فئات المساحات|مدرج تكراري|histogram)', text):
        return 'histogram'
    if re.search(r'(?:انتشار|علاقة|مقارنة السوق|scatter)', text):
        return 'scatter'
    if re.search(r'(?:وحدات|مساحات|مواصفات|جدول|مقارنة|أنواع|تفاصيل|مكونات|قائمة|بيانات|units|areas|specs|table|components|details|list|data)', text):
        return 'table'
    if re.search(r'(?:خطة|زمن|جدول|مراحل|تنفيذ|تطوير|خطوات|مدة|timeline|schedule|phases|plan|stages|duration)', text):
        return 'timeline'
    if re.search(r'(?:موقع|خريطة|وصول|معالم|محيط|منطقة|location|map|access|landmarks|area|surrounding)', text):
        return 'map'
    if re.search(r'(?:swot|قوة|ضعف|فرص|تحديات|منافسة|مزايا تنافسية|مخاطر|strength|weakness|opportunities|threats|competitive)', text):
        return 'swot'
    if re.search(r'(?:عملية|تدفق|خطوات|عملاء|رحلة|عمل|process|flow|customer journey|steps)', text):
        return 'flow'
    if re.search(r'(?:مخطط اتجاهي|حدود الأرض|اتجاهي|أبعاد الأرض|diagram|boundary)', text):
        return 'diagram'
    if re.search(r'(?:صورة|واجهة|تصميم معماري|انطباع|visual|image|facade|architectural|render)', text):
        return 'image'
    if re.search(r'(?:نظرة|نبذة|مقدمة|شرح|وصف|ملخص|تعريف|رؤية|رسالة|فلسفة|overview|introduction|description|summary|vision|mission)', text):
        return 'text'
    return 'text'


def _maybe_map_slide_type(title, project_data):
    """If a content slide title matches a map topic and location data exists, return a map type."""
    if not project_data:
        return None
    has_location = (
        bool(project_data.get('location_lat') and project_data.get('location_lng'))
        or bool(project_data.get('location_address'))
    )
    if not has_location:
        return None
    t = (title or '').lower()
    if re.search(r'(?:موقع المشروع|الموقع|موقع)', t):
        return 'map_overview'
    if re.search(r'(?:معالم|محيط|القرب|المسافات|landmarks)', t):
        return 'map_landmarks'
    if re.search(r'(?:وصول|طرق|مداخل|access|roads)', t):
        return 'map_access'
    if re.search(r'(?:نطاق|catchment|دوائر)', t):
        return 'map_catchment'
    if re.search(r'(?:خصائص|مواصفات|site specs)', t):
        return 'site_specs'
    return None


TIMELINE_QUARTERS = ('Q1', 'Q2', 'Q3', 'Q4')


def _timeline_project_start_index(project_data):
    """Project start as an absolute month index (year*12 + month-1), or None.

    The client picks a month+year start («2030-02»); drafts saved before that field carry a
    bare start year, which maps to January.
    """
    source = project_data if isinstance(project_data, dict) else {}
    raw = str(source.get('timeline_start_date') or '').strip()
    match = re.match(r'^(\d{4})-(\d{1,2})$', raw)
    if match and 1 <= int(match.group(2)) <= 12:
        return int(match.group(1)) * 12 + (int(match.group(2)) - 1)
    legacy = str(source.get('timeline_start_year') or '').strip()
    if re.match(r'^\d{4}$', legacy):
        return int(legacy) * 12
    return None


def _format_timeline_month(index):
    return f'{(index % 12) + 1}/{index // 12}'


def compute_timeline_end(year, quarter, duration):
    """Inclusive end as a project-relative year/quarter plus its month offset from start."""
    try:
        start_year = int(year)
        quarter_index = TIMELINE_QUARTERS.index(str(quarter or '').strip())
        months = int(duration)
    except (TypeError, ValueError):
        return None
    if start_year <= 0 or months <= 0:
        return None
    end_month = (start_year - 1) * 12 + quarter_index * 3 + months - 1
    return {
        'year': str(end_month // 12 + 1),
        'quarter': TIMELINE_QUARTERS[(end_month % 12) // 3],
        'month_index': end_month,
    }


def parse_timeline_phases(project_data):
    """Return named timeline phases from the draft table, including notes.

    Rows keep project-relative years/quarters anchored to the start date; when that date is
    known each phase also carries its real start/end month labels.
    """
    source = project_data if isinstance(project_data, dict) else {}
    raw = source.get('timeline_table_data')
    if raw in (None, '', []):
        raw = source.get('timelineRows')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = []
    if not isinstance(raw, list):
        return []
    start_index = _timeline_project_start_index(source)
    # A bare start year with no start date marks a pre-migration draft: its rows hold calendar
    # years and January-anchored quarters, so shift them onto the relative axis.
    legacy_start_year = None
    if not str(source.get('timeline_start_date') or '').strip():
        legacy = str(source.get('timeline_start_year') or '').strip()
        if re.match(r'^\d{4}$', legacy):
            legacy_start_year = int(legacy)
    phases = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()
        if not name:
            continue
        year = str(item.get('year') or '').strip()
        quarter = str(item.get('quarter') or '').strip()
        duration = str(item.get('duration') or '').strip()
        end_year = str(item.get('endYear') or '').strip()
        end_quarter = str(item.get('endQuarter') or '').strip()
        if legacy_start_year is not None:
            if year.isdigit() and int(year) >= 1000:
                year = str(max(1, int(year) - legacy_start_year + 1))
            if end_year.isdigit() and int(end_year) >= 1000:
                end_year = str(max(1, int(end_year) - legacy_start_year + 1))
        computed = compute_timeline_end(year, quarter, duration)
        if not end_year or not end_quarter:
            if computed:
                end_year = end_year or computed['year']
                end_quarter = end_quarter or computed['quarter']
        phase = {
            'name': name,
            'year': year,
            'quarter': quarter,
            'duration': duration,
            'endYear': end_year,
            'endQuarter': end_quarter,
            'notes': str(item.get('notes') or '').strip(),
        }
        if start_index is not None:
            try:
                phase['start_label'] = _format_timeline_month(
                    start_index + (int(year) - 1) * 12 + TIMELINE_QUARTERS.index(quarter) * 3)
            except (TypeError, ValueError):
                pass
            end_month_index = computed['month_index'] if computed else None
            if end_month_index is None:
                try:
                    end_month_index = (
                        (int(end_year) - 1) * 12 + TIMELINE_QUARTERS.index(end_quarter) * 3 + 2)
                except (TypeError, ValueError):
                    end_month_index = None
            if end_month_index is not None:
                phase['end_label'] = _format_timeline_month(start_index + end_month_index)
        phases.append(phase)

    if not phases:
        years_val = source.get('timeline_years') or source.get('development_years') or source.get('development_duration_years')
        has_start = start_index is not None or bool(str(source.get('timeline_start_date') or '').strip()) or bool(str(source.get('timeline_start_year') or '').strip())
        years_num = 0
        if years_val:
            try:
                years_num = int(str(years_val).strip())
            except (ValueError, TypeError):
                years_num = 0
        if years_num <= 0 and has_start:
            years_num = 3
        if years_num > 0:
            total_months = max(12, years_num * 12)
            default_phase_specs = [
                ('التصميم والدراسات والتراخيص', 0.15, 'إعداد وتدقيق المخططات الهندسية واستخراج رخص البناء والاعتمادات النظامية'),
                ('تجهيز الموقع والأساسات والهيكل الإنشائي', 0.25, 'أعمال تسوية الموقع والحفر وتنفيذ الأساسات والهيكل الخرساني والإنشائي'),
                ('استكمال الهيكل وأعمال الكهرباء والميكانيكا', 0.25, 'تمديد الشبكات الكهروميكانيكية وأنظمة التكييف والسلامة والإنذار'),
                ('التشطيبات والأعمال الخارجية وتنسيق الموقع', 0.20, 'تنفيذ التشطيبات المعمارية والواجهات وتنسيق الموقع العام والمسطحات'),
                ('الاختبارات والتسليم والتسويق والتشغيل', 0.15, 'الفحص والتشغيل التجريبي واستخراج رخص الإشغال والإطلاق والتسليم'),
            ]
            current_month = 0
            for idx, (p_name, weight, p_notes) in enumerate(default_phase_specs):
                if idx == len(default_phase_specs) - 1:
                    dur = max(2, total_months - current_month)
                else:
                    dur = max(2, round(total_months * weight))
                start_m = current_month
                end_m = start_m + dur - 1
                y_start = str(start_m // 12 + 1)
                q_start = TIMELINE_QUARTERS[(start_m % 12) // 3]
                y_end = str(end_m // 12 + 1)
                q_end = TIMELINE_QUARTERS[(end_m % 12) // 3]
                p = {
                    'name': p_name,
                    'year': y_start,
                    'quarter': q_start,
                    'duration': str(dur),
                    'endYear': y_end,
                    'endQuarter': q_end,
                    'notes': p_notes,
                }
                if start_index is not None:
                    p['start_label'] = _format_timeline_month(start_index + start_m)
                    p['end_label'] = _format_timeline_month(start_index + end_m)
                phases.append(p)
                current_month += dur

    return phases


def format_timeline_phase_line(phase):
    def _point(year, quarter, label):
        if label:
            return label
        parts = []
        if year:
            parts.append(f'سنة {year}')
        if quarter:
            parts.append(f'الربع {str(quarter).lstrip("Q")}')
        return ' '.join(parts)

    start = _point(phase.get('year'), phase.get('quarter'), phase.get('start_label'))
    end = _point(phase.get('endYear'), phase.get('endQuarter'), phase.get('end_label'))
    span = f'{start} إلى {end}' if start and end else (start or end)
    duration = phase.get('duration')
    duration_text = f' لمدة {duration} شهر' if duration else ''
    notes = phase.get('notes')
    notes_text = f' — {notes}' if notes else ''
    detail = f'{span}{duration_text}' if span or duration_text else ''
    return f"{phase['name']}: {detail}{notes_text}".strip(': ').strip()


def _timeline_data_note(project_data):
    """Keep the phase table, including notes, outside the truncated project JSON."""
    phases = parse_timeline_phases(project_data)
    if not phases:
        return ''
    return (
        "\n\n## الجدول الزمني للمشروع — إلزامي في شريحة الجدول الزمني\n"
        "هذه المراحل مصدر الحقيقة. اعرض كل مرحلة مع بدايتها ومدتها ونهايتها المحسوبة.\n"
        "إذا وُجدت ملاحظة لمرحلة فاعرضها تحتها أو بجانبها دون حذف أو اختصار. إذا كانت الملاحظة فارغة فلا تعرض عنوانًا أو حقلًا أو مساحة للملاحظات في تلك المرحلة.\n"
        + '\n'.join(f'- {format_timeline_phase_line(phase)}' for phase in phases)
    )


# The system never produces photographs of the streets around a site: the Street View fetch is
# not part of any workflow the user can run, and the visual-concept board holds renders of the
# project itself, not its surroundings. The rules used to advertise ##STREET_VIEW_1..4## anyway,
# the model built a four-card «قراءة بصرية للموقع» slide out of them, and the unresolved tokens
# were blanked — the slide shipped as four empty frames. Say it, do not imply it.
NO_STREET_VIEW_RULE = (
    "ممنوع نهائياً: لا توجد صور فوتوغرافية للشوارع أو للموقع أو لمحيط الأرض، ولا تُولَّد من الخرائط "
    "ولا من التصور البصري. لا تكتب ##STREET_VIEW_1## أو أي رمز مشابه، ولا تنشئ شريحة صور موقع أو "
    "«قراءة بصرية للمحيط» أو بطاقات صور للواجهات المحيطة. الصور المتوفرة هي المذكورة في «الصور "
    "المتوفرة» فقط، والموقع يُعرض بالخرائط والبيانات لا بالصور."
)


def _location_data_note(project_data):
    """Build an extra prompt note when map/location data is present."""
    if not project_data:
        return ''
    has_location = (
        bool(project_data.get('location_lat') and project_data.get('location_lng'))
        or bool(project_data.get('location_address'))
    )
    if not has_location:
        return ''
    parts = []
    if project_data.get('location_lat') and project_data.get('location_lng'):
        parts.append('إحداثيات الموقع متاحة.')
    if project_data.get('location_address'):
        parts.append(f"عنوان الموقع: {project_data.get('location_address')}")
    if project_data.get('nearby_landmarks_data') or project_data.get('landmarks_matrix'):
        parts.append('بيانات المعالم المحيطة متاحة.')
    if project_data.get('main_roads'):
        parts.append('بيانات الطرق الرئيسية متاحة.')
    if project_data.get('catchment_areas'):
        parts.append('بيانات نطاق التأثير متاحة.')
    if not parts:
        return ''
    return (
        "\n\n## بيانات الموقع/الخرائط المتاحة — يجب استخدامها\n"
        + '\n'.join(f'- {p}' for p in parts)
        + "\n\n"
        "الزامياً: أضف الشرائح التالية بعد الفهرس إن وُجدت البيانات المطلوبة:\n"
        "- map_overview (يتطلب إحداثيات)\n"
        "- map_landmarks (يتطلب landmarks_matrix)\n"
        "- map_access (يتطلب main_roads)\n"
        "- site_specs (يتطلب بيانات الموقع)\n"
        "- map_catchment (يتطلب catchment_areas)\n"
        "استخدم placeholders ##MAP_OVERVIEW##، ##MAP_LANDMARKS##، ##MAP_ACCESS##، ##MAP_CATCHMENT##\n"
        + NO_STREET_VIEW_RULE
    )


def _parse_financial_dict(val):
    """Safely parse a JSON string or return dict."""
    if isinstance(val, dict):
        return val
    if isinstance(val, str) and val.strip().startswith('{'):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _financial_number(value):
    """A stored financial value as a number; text such as "18%" or "1,200" still counts."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r'[^\d.\-]', '', str(value or ''))
    try:
        return float(text)
    except ValueError:
        return 0.0


def financial_study_has_real_input(model, calc=None):
    """True only when someone actually entered figures in the financial study.

    The financial section is rendered for every project and `collectFinancialStudyModel()` snapshots
    every one of its controls plus the computed projection, so an untouched project still carries a
    ~35KB model of markup defaults and zeros. Sending that made the prompt state that zero-value
    tables were "الجداول المالية المعتمدة", which is worse than saying nothing.
    """
    model = _parse_financial_dict(model)
    calc = _parse_financial_dict(calc)
    dynamic_rows = model.get('dynamicRows') if isinstance(model.get('dynamicRows'), dict) else {}
    tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
    row_sets = list(dynamic_rows.values()) + list(tables.values()) + [calc.get('components')]
    for rows in row_sets:
        if isinstance(rows, list) and any(isinstance(row, dict) and any(
                str(value or '').strip() for value in row.values()) for row in rows):
            return True
    inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
    projection = model.get('projection') if isinstance(model.get('projection'), dict) else {}
    # Rates, durations and counts carry markup defaults, so only the money and area figures
    # distinguish an entered study from an untouched one.
    for key in ('projectCost', 'adjustedProjectCost', 'landValue', 'manualLandValue',
                'equityRequired', 'facilityAmount', 'totalBuiltUpArea', 'builtUpAreaAbove',
                'basementArea', 'landArea', 'totalRevenue', 'netProfit'):
        if _financial_number(inputs.get(key) or projection.get(key) or calc.get(key)) > 0:
            return True
    return False


# Saying nothing about an empty financial study is not neutral: the model treats the gap as
# something to fill, which is where invented costs and returns came from. The absence is stated.
FINANCIAL_ABSENT_NOTE = (
    "\n\n## الدراسة المالية غير مُدخلة في هذا الملف"
    "\n- لا توجد أي أرقام مالية: لا تكلفة ولا قيمة أرض ولا رأس مال ولا تمويل ولا إيرادات ولا عائد"
    " ولا مؤشرات ولا مساحات مبنية ولا جداول."
    "\n- ممنوع إنشاء شريحة مالية أو شريحة مؤشرات أو رسم بياني مالي أو جدول أرقام."
    "\n- ممنوع ذكر أي رقم أو نسبة أو عائد أو تكلفة في أي شريحة أخرى، ولو كتقدير أو مدى أو مثال"
    " أو من معرفة عامة عن السوق."
)

# A financial title in a plan that has no financial data can only be filled by inventing numbers.
FINANCIAL_SLIDE_TITLE_RE = re.compile(
    r'(?:مالي|ماليّ|تكلفة|تكاليف|إيراد|ايراد|عائد|عوائد|ربح|أرباح|جدوى|ميزانية|تمويل|استثمار|'
    r'مؤشرات|مؤشر|قيمة مضافة|هيكل رأس المال|روي|financial|cost|revenue|profit|roi|irr|noi|'
    r'budget|feasibility|metrics|dashboard)'
)


def project_has_financial_study(project_data):
    """True when this project file carries entered financial figures."""
    source = project_data if isinstance(project_data, dict) else {}
    return financial_study_has_real_input(source.get('financial_study_model'),
                                         source.get('financial_calc_data'))


def strip_street_view_slides(plan):
    """Drop a site-photos slide from a plan: there are no photographs of the site to put in it.

    The type is gone from the prompt, but an older draft can still carry a plan that has one, and a
    model can still guess the name. Left in, it becomes a slide of empty image frames.
    """
    if not isinstance(plan, dict) or not isinstance(plan.get('slides'), list):
        return plan
    kept = [slide for slide in plan['slides']
            if not (isinstance(slide, dict) and slide.get('type') == 'site_photos')]
    if len(kept) != len(plan['slides']):
        print(f"[SLIDE-PLAN] dropped {len(plan['slides']) - len(kept)} site_photos slide(s): no site photographs exist")
        plan['slides'] = kept
        plan['proposed_count'] = len(kept)
    return plan


def strip_financial_slides(plan, project_data):
    """Drop financial slides from a plan for a project that has no financial study.

    The planner, the fallback plan and the minimum-count padding all offer titles such as
    «التحليل المالي والجدوى» and «مؤشرات الأداء والقيمة المضافة», and a slide with that title and no
    figures behind it can only be written by inventing them.
    """
    if not isinstance(plan, dict) or project_has_financial_study(project_data):
        return plan
    slides = plan.get('slides') if isinstance(plan.get('slides'), list) else []
    kept = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        text = f"{slide.get('title') or ''} {' '.join(str(b or '') for b in (slide.get('bullets') or []))}"
        financial = (slide.get('design_style') == 'dashboard'
                     or slide.get('content_source') == 'financial'
                     or bool(FINANCIAL_SLIDE_TITLE_RE.search(text.lower())))
        if financial and slide.get('type') not in ('cover', 'index', 'moodboard', 'closing'):
            print(f"[SLIDE-PLAN] Dropped financial slide «{slide.get('title')}»: no financial study entered")
            continue
        kept.append(slide)
    plan['slides'] = kept
    plan['proposed_count'] = len(kept)
    return plan


_FINANCIAL_INDICATOR_LABELS = (
    ('projectCost', 'إجمالي تكلفة المشروع'),
    ('projectCostWithFinance', 'التكلفة شاملة التمويل'),
    ('adjustedProjectCost', 'إجمالي تكلفة الاستثمار'),
    ('developerCost', 'أتعاب المطور'),
    ('landValue', 'قيمة الأرض'),
    ('landRent', 'إيجار الأرض السنوي'),
    ('saleRevenueTotal', 'إجمالي إيرادات البيع'),
    ('revenueY1', 'إيرادات السنة الأولى'),
    ('opexY1', 'مصروفات السنة الأولى'),
    ('noiY1', 'NOI — السنة الأولى'),
    ('fullOccupancyRevenue', 'الإيرادات عند الإشغال المستهدف'),
    ('fullOccupancyNOI', 'NOI عند الإشغال المستهدف'),
    ('totalGraceDiscount', 'إجمالي خصم فترة السماح'),
    ('facilityAmount', 'قيمة التسهيل التمويلي'),
    ('arrangementFee', 'رسوم ترتيب التمويل'),
    ('totalFinanceInterest', 'إجمالي فوائد التمويل'),
    ('totalFinanceCost', 'إجمالي كلفة التمويل'),
    ('totalFundFees', 'إجمالي أتعاب الصندوق'),
    ('saleExitValue', 'صافي التخارج البيعي'),
    ('operatingExitValue', 'صافي التخارج التشغيلي'),
    ('terminal', 'إجمالي قيمة التخارج'),
    ('landEquityContribution', 'مساهمة الأرض العينية'),
    ('totalCashEquity', 'حقوق الملكية النقدية'),
    ('totalEquityRequired', 'إجمالي حقوق الملكية المطلوبة'),
    ('totalEquityDistributions', 'إجمالي التوزيعات'),
    ('roi', 'ROI'),
    ('projectIrr', 'Project IRR'),
    ('equityIrr', 'Equity IRR'),
    ('payback', 'فترة استرداد رأس المال'),
    ('equityPayback', 'فترة استرداد حقوق الملكية'),
    ('totalBuiltUpArea', 'إجمالي المساحات المبنية م²'),
    ('developmentYears', 'مدة التطوير (سنوات)'),
)

_FINANCIAL_TABLE_TITLES = {
    'componentsTable': 'مكونات المشروع',
    **{key: title for key, title, _style in _FINANCIAL_PLAN_TABLES},
}


def _financial_data_note(project_data):
    """Extract and format financial study tables and metrics so they are never lost or distorted."""
    if not project_data or not isinstance(project_data, dict):
        return ''
    model = _parse_financial_dict(project_data.get('financial_study_model'))
    calc = _parse_financial_dict(project_data.get('financial_calc_data'))
    if not financial_study_has_real_input(model, calc):
        return FINANCIAL_ABSENT_NOTE

    inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
    projection = model.get('projection') if isinstance(model.get('projection'), dict) else {}
    tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
    report = model.get('report') if isinstance(model.get('report'), dict) else {}
    report_parts = report.get('parts') if isinstance(report.get('parts'), list) else []
    lines = [
        "\n\n## الدراسة المالية المعتمدة — نفس محتوى تقرير PDF",
        "- اعرض جميع الأقسام والجداول والمؤشرات الموجودة أدناه، وبالترتيب والمسميات والقيم والوحدات نفسها. لا تختصر الدراسة في لوحة مؤشرات واحدة.",
        "- أضف فواصل الآلاف بصرياً فقط من دون تقريب أو تحويل إلى ألف أو مليون أو تغيير عدد الخانات العشرية.",
        "- لا تغيّر أسماء المؤشرات، وبخاصة ROI وProject IRR وEquity IRR وNOI، ولا تستبدلها بتسميات جديدة.",
        "- لا تحذف صفاً أو عموداً أو سنة. قسّم الجدول على صفحات إضافية عند الحاجة، ولا تعِد عرض مكونات المشروع خارج قسمها المخصص.",
        "- عند وجود قيم قابلة للمقارنة أضف رسماً بيانياً بألوان الهوية، مع جدول القيم الأصلي الكامل بجانبه.",
        "- الرقم أو المؤشر غير الموجود لا يُكتب، ولا يُقدّر، ولا يُعاد حسابه أو اشتقاقه.",
    ]

    if report_parts:
        lines.append("\n### نسخة الشاشة المعتمدة بالترتيب والمسميات الظاهرة للمستخدم:")
        lines.append(json.dumps(report_parts, ensure_ascii=False, indent=2))
        return '\n'.join(lines)

    indicators = {}
    for key, label in _FINANCIAL_INDICATOR_LABELS:
        value = projection.get(key)
        if value in (None, '', [], {}) and inputs.get(key) not in (None, '', [], {}):
            value = inputs.get(key)
        if value in (None, '', [], {}) and calc.get(key) not in (None, '', [], {}):
            value = calc.get(key)
        if value not in (None, '', [], {}, -1):
            indicators[label] = value
    if indicators:
        lines.append("\n### المؤشرات المالية بمسمياتها الأصلية:")
        lines.append(json.dumps(indicators, ensure_ascii=False, indent=2))

    dynamic_rows = model.get('dynamicRows') if isinstance(model.get('dynamicRows'), dict) else {}
    components = dynamic_rows.get('components') if isinstance(dynamic_rows.get('components'), list) else []
    if components and not tables.get('componentsTable'):
        lines.append("\n### مكونات المشروع كما أُدخلت في الدراسة:")
        lines.append(json.dumps(components, ensure_ascii=False, indent=2))

    ordered_keys = list(_FINANCIAL_TABLE_TITLES)
    ordered_keys.extend(key for key in tables if key not in ordered_keys)
    for table_key in ordered_keys:
        rows = tables.get(table_key)
        if not isinstance(rows, list) or not rows:
            continue
        clean_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            cleaned = {key: value for key, value in row.items()
                       if key not in ('ترتيب / حذف', 'ترتيب', 'حذف', 'idx', 'id')}
            if any(str(value or '').strip() for value in cleaned.values()):
                clean_rows.append(cleaned)
        if clean_rows:
            title = _FINANCIAL_TABLE_TITLES.get(table_key, table_key)
            lines.append(f"\n### {title} ({len(clean_rows)} صفًا) — المفتاح {table_key}:")
            lines.append(json.dumps(clean_rows, ensure_ascii=False, indent=2))

    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Project facts for the prompt
# ─────────────────────────────────────────────────────────────────────────────
#
# The payload of a real project file is ~230,000 characters. It used to be dumped as raw JSON and
# cut at 4,000 characters, so 98% of it never reached the model: the market study, the executive
# content, the team, and most of the location section were always beyond the cut, and which fields
# survived depended on the draft's key order. The model now receives every fact under an Arabic
# heading, with the noise removed instead of the facts.

# Sent to the model by another route, so repeating them here only burns context:
#   financial/timeline    -> _financial_data_note / _timeline_data_note
#   images                -> _get_images_info
#   landmark drive times  -> the landmarks matrix note
#   the slide plan        -> the user message
PROMPT_COVERED_ELSEWHERE = {
    'financial_study_model', 'financial_calc_data', 'project_components_data',
    'timeline_table_data', 'timelineRows',
    'tenantCreativeImages', 'visual_concept', 'tenantSlidePlan', 'slidePlan',
    'landmarks_matrix', 'nearby_landmarks_data', 'street_view_images', 'company_branding',
}

# The deck itself. Feeding a model the slides it produced last time invites it to copy them.
# `designerChat` is the editing conversation: it belongs to the chat, never to a slide prompt.
PROMPT_PREVIOUS_OUTPUT = {'tenantSlidesData', 'pageDrafts', 'slides', 'designerChat', 'presentation_scope'}

# Machine artefacts of the land analysis and the map pipeline: the facts they produced are already
# in the visible land and location fields.
PROMPT_INTERNAL_KEYS = {
    'land_documents_analysis', 'land_documents_analysis_status', 'regulation_evidence',
    'regulation_coordinates', 'coordinate_tables', 'survey_coordinates', 'directions_table',
    'parcels', 'conflicts', 'warnings', 'extraction_diagnostics', 'document_processing',
    'land_document_processing', 'document_summary', 'source_priority',
    'location_polygon', 'location_polygon_source', 'location_coordinates_confirmed',
    'location_coordinates_source', 'refresh_maps', 'regen_seed', 'enabled_maps',
    'map_styles', 'map_type', 'north_direction', '_resolved_location',
    'draftId', 'draft_id', 'sectionStatuses', 'site_analysis_approved',
    'conceptual_plans', 'land_documents_files', 'land_photos', 'project_logo',
    'land_use_status',
    # Superseded by building_ratio_coverage / setbacks and allowed_uses; kept in drafts for
    # backwards compatibility only.
    'building_ratio_setbacks', 'allowed_uses_restrictions', 'secondary_roads',
}

PROMPT_SKIPPED_KEYS = PROMPT_COVERED_ELSEWHERE | PROMPT_PREVIOUS_OUTPUT | PROMPT_INTERNAL_KEYS
PROMPT_SKIPPED_SUFFIXES = ('_file_id', '_file_ids', '_file_meta')

# Facts with no PREBUILT_FIELDS entry, so they carry no label of their own.
EXTRA_FIELD_LABELS = {
    'site_analysis': 'تحليل الموقع',
    'location_detail': 'تفصيل الموقع',
    'land_use': 'استخدام الأرض',
    'zoning_code': 'كود التنظيم',
    'population_density': 'الكثافة السكانية',
    'population_density_source': 'مصدر الكثافة السكانية',
    'timeline_start_date': 'تاريخ بداية المشروع',
    'timeline_start_year': 'سنة بداية المشروع',
    'timeline_years': 'عدد سنوات المشروع',
}

# A single field cannot flood the brief, and the brief cannot flood the request.
FACT_VALUE_LIMIT = 6000
PROJECT_FACTS_LIMIT = 120000


def _field_label_map():
    """key -> (Arabic label, section key, sort order) for every prebuilt field."""
    labels = {}
    for field in getattr(db, 'PREBUILT_FIELDS', []) or []:
        key = field.get('key')
        if key:
            labels[key] = (field.get('label') or key,
                           field.get('section_key') or 'basic',
                           field.get('sort_order') or 0)
    return labels


def _readable_fact(value):
    """Render one stored value as text a writer can read."""
    if value is None or isinstance(value, bool):
        return '' if value is None else ('نعم' if value else '')
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith('{') or text.startswith('['):
            decoded = _decode_json_fact(text)
            if decoded is not None:
                return _readable_fact(decoded)
        return text[:FACT_VALUE_LIMIT]
    if isinstance(value, dict):
        if len(value) == 1 and 'general' in value:
            return _readable_fact(value['general'])
        parts = []
        for key, item in value.items():
            text = _readable_fact(item)
            raw_label = str(key).split('::')[-1]
            label = USE_TYPE_LABELS.get(raw_label, INVESTMENT_MODEL_LABELS.get(raw_label, raw_label))
            if text:
                parts.append(f'{label}: {text}' if label != 'general' else text)
        return ' | '.join(parts)[:FACT_VALUE_LIMIT]
    if isinstance(value, (list, tuple)):
        parts = [_readable_fact(item) for item in value]
        parts = [part for part in parts if part]
        if not parts:
            return ''
        inline = '، '.join(parts)
        if len(inline) <= 200 and '\n' not in inline:
            return inline[:FACT_VALUE_LIMIT]
        return '\n'.join(f'  - {part}' for part in parts)[:FACT_VALUE_LIMIT]
    return str(value)[:FACT_VALUE_LIMIT]


def _decode_json_fact(value):
    """Sections are stored as JSON strings inside the draft, so they must be decoded first."""
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _market_study_facts(project_data):
    """The market study: the written summary, the competitor rows, SWOT and the decision."""
    state = _decode_json_fact(project_data.get('market_study_data'))
    if not isinstance(state, dict):
        return ''
    lines = []
    summary = str(state.get('one_block_summary') or '').strip()
    if summary:
        lines.append('### الملخص التنفيذي لسوق المشروع')
        lines.append(summary)
    scope = {}
    for key in ('competitor_radius', 'competitor_radius_custom_km', 'data_period',
                'data_period_from', 'data_period_to'):
        value = state.get(key)
        if value not in (None, '', []):
            scope[key] = value
    if scope:
        lines.append('### نطاق وفترة بيانات دراسة السوق')
        lines.append(json.dumps(scope, ensure_ascii=False, indent=2))
    competitors = state.get('competitors') if isinstance(state.get('competitors'), list) else []
    rows = []
    for index, competitor in enumerate(competitors, 1):
        if not isinstance(competitor, dict):
            continue
        # Per-field source URLs are provenance for the study screen, not slide content.
        row = {key: value for key, value in competitor.items()
               if key not in ('id', 'field_sources', 'source_urls', 'row_source', 'logo_file_id',
                              'logo_path', 'logo_url', 'logo_source_url', 'conflict_warnings',
                              'logo_import_warning', 'price_cache', 'area_cache') and value not in (None, '', [])}
        if competitor.get('logo_file_id') or competitor.get('logo_path') or competitor.get('logo_url'):
            row['شعار المنافس'] = f'##COMPETITOR_LOGO_{index}##'
        if row:
            rows.append(row)
    if rows:
        lines.append('### المنافسون (أرقامهم كما هي، ممنوع تعديلها)')
        lines.append(json.dumps(rows, ensure_ascii=False, indent=2))
    sources = state.get('sources') if isinstance(state.get('sources'), list) else []
    if sources:
        lines.append('### مصادر دراسة السوق')
        lines.append(json.dumps(sources, ensure_ascii=False, indent=2))
    # Keep the detailed analysis even when one_block_summary is present. The
    # executive paragraph must not replace the market analysis in the model context.
    summary_text = str(state.get('summary') or '').strip() if isinstance(state.get('summary'), str) else ''
    if summary_text:
        lines.append('### تحليل السوق')
        lines.append(summary_text)
    for key, title in (('summary', 'تحليل السوق'), ('swot', 'تحليل SWOT')):
        block = state.get(key)
        if isinstance(block, dict):
            filled = {k: v for k, v in block.items() if str(v or '').strip()}
            if filled:
                lines.append(f'### {title}')
                lines.append(json.dumps(filled, ensure_ascii=False, indent=2))
    for key, title in (('decision', 'تصنيف القرار'), ('disclaimer', 'إخلاء المسؤولية')):
        text = str(state.get(key) or '').strip()
        if text:
            lines.append(f'{title}: {text}')
    if not lines:
        return ''
    return '### دراسة السوق\n' + '\n'.join(lines)


def _executive_content_facts(project_data):
    """The approved executive texts, each under its own Arabic label."""
    state = _decode_json_fact(project_data.get('executive_content'))
    if not isinstance(state, dict):
        return ''
    try:
        import executive_content
        blocks = [(item['key'], item['label']) for item in executive_content.BLOCKS]
    except Exception:
        blocks = [(key, key) for key in state]
    lines = []
    for key, label in blocks:
        text = str(state.get(key) or '').strip()
        if text:
            lines.append(f'#### {label}\n{text[:FACT_VALUE_LIMIT]}')
    if not lines:
        return ''
    return ('### المحتوى التنفيذي المعتمد (نصوص معتمدة — أعد صياغتها للشرائح ولا تخترع غيرها)\n'
            + '\n\n'.join(lines))


def _selected_team_entries(project_data, tenant_id=None):
    selection = _decode_json_fact((project_data or {}).get('team_selection'))
    selection = selection if isinstance(selection, dict) else {}
    excluded = set(selection.get('excluded') or [])
    overrides = selection.get('roles') if isinstance(selection.get('roles'), dict) else {}
    entries = []
    if tenant_id:
        try:
            library = db.get_team_entities(tenant_id) or []
        except Exception:
            library = []
        for entity in library:
            if entity.get('id') in excluded:
                continue
            entries.append({
                'الجهة': entity.get('name') or '',
                'الدور': overrides.get(entity.get('id')) or entity.get('role') or '',
                'نبذة': entity.get('brief') or '',
                'سنوات الخبرة': entity.get('experienceYears') or '',
                'أعمال سابقة': entity.get('notableProjects') or '',
                '_logo_file_id': entity.get('logoFileId') or '',
            })
    for local in selection.get('local') or []:
        if not isinstance(local, dict):
            continue
        entries.append({
            'الجهة': local.get('name') or '',
            'الدور': local.get('role') or '',
            'نبذة': local.get('brief') or '',
            'سنوات الخبرة': local.get('experienceYears') or '',
            'أعمال سابقة': local.get('notableProjects') or '',
            '_logo_file_id': local.get('logoFileId') or '',
        })
    return [{key: value for key, value in entry.items() if str(value or '').strip()}
            for entry in entries if str(entry.get('الجهة') or '').strip()]


def _team_facts(project_data, tenant_id=None):
    """The team actually chosen for this file: the company library minus exclusions, plus locals.

    The library lives in ``tenant_team_entities`` and the draft only stores ids, so without
    resolving it the prompt would carry no names at all.
    """
    entries = []
    for index, source in enumerate(_selected_team_entries(project_data, tenant_id), 1):
        entry = {key: value for key, value in source.items() if not key.startswith('_')}
        if source.get('_logo_file_id'):
            entry['الشعار'] = f'##TEAM_LOGO_{index}##'
        entries.append(entry)
    if not entries:
        return ''
    return '### فريق العمل (بنفس الترتيب والحقول، وشعار كل جهة إلزامي عند توفره)\n' + json.dumps(entries, ensure_ascii=False, indent=2)


def _contact_facts(project_data, tenant_id=None):
    source = project_data if isinstance(project_data, dict) else {}
    fields = (
        ('الاسم', ('contact_name', 'name')),
        ('المنصب', ('contact_position', 'position', 'job_title')),
        ('الهاتف', ('contact_phone', 'company_phone', 'phone', 'mobile')),
        ('البريد الإلكتروني', ('contact_email', 'company_email', 'email')),
        ('الموقع الإلكتروني', ('contact_website', 'company_website', 'website')),
        ('الموقع الجغرافي', ('contact_address', 'company_address', 'address')),
        ('السوشل ميديا', ('contact_social_media', 'social_media')),
    )
    values = {}
    for label, keys in fields:
        value = next((str(source.get(key) or '').strip() for key in keys if str(source.get(key) or '').strip()), '')
        if value:
            values[label] = value
    if not values:
        return ''
    return '### بيانات التواصل المعتمدة للخاتمة (انقل المتاح فقط كما هو)\n' + json.dumps(values, ensure_ascii=False, indent=2)


def build_project_facts(project_data, tenant_id=None):
    """Every collected fact, grouped by its section and labelled in Arabic.

    Replaces dumping the raw draft and cutting it at a character count.
    """
    if not isinstance(project_data, dict) or not project_data:
        return 'لا توجد بيانات مشروع.'
    labels = _field_label_map()
    section_titles = {item['key']: item['label']
                      for item in (getattr(db, 'FIELD_SECTIONS', []) or [])}
    grouped = {key: [] for key in section_titles}
    extra = []
    for key, value in project_data.items():
        if key in PROMPT_SKIPPED_KEYS or key.startswith('_'):
            continue
        if key.endswith(PROMPT_SKIPPED_SUFFIXES):
            continue
        if key in ('market_study_data', 'executive_content', 'team_selection'):
            continue
        text = _readable_fact(value)
        if not text:
            continue
        if key in labels:
            label, section, order = labels[key]
            grouped.setdefault(section, []).append((order, label, text))
        else:
            label = EXTRA_FIELD_LABELS.get(key)
            if not label and key.endswith('_other'):
                base = labels.get(key[:-6])
                label = f'{base[0]} (أخرى)' if base else None
            extra.append((label or key, text))

    blocks = []
    for section_key, title in section_titles.items():
        # Same order as the form, so the brief reads the way the client filled it.
        rows = sorted(grouped.get(section_key) or [], key=lambda row: row[0])
        if rows:
            blocks.append(f'### {title}\n'
                          + '\n'.join(f'- {label}: {text}' for _order, label, text in rows))
    if extra:
        blocks.append('### بيانات إضافية\n'
                      + '\n'.join(f'- {label}: {text}' for label, text in extra))
    for note in (_team_facts(project_data, tenant_id),
                 _market_study_facts(project_data),
                 _executive_content_facts(project_data),
                 _contact_facts(project_data, tenant_id)):
        if note:
            blocks.append(note)
    facts = '\n\n'.join(blocks) or 'لا توجد بيانات مشروع.'
    if len(facts) > PROJECT_FACTS_LIMIT:
        facts = facts[:PROJECT_FACTS_LIMIT] + '\n... [تم اختصار البيانات]'
    return facts
