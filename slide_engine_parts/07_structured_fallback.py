

def _build_structured_fallback_slide(slide, project_data, branding, slide_num=None, total_slides=None):
    source = project_data if isinstance(project_data, dict) else {}
    lang = resolve_offer_lang(source)
    slide_dir = 'ltr' if lang == OFFER_LANG_ENGLISH else 'rtl'
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    secondary = normalize_hex_color((branding or {}).get('secondary_color'), '#0ea5e9')
    title = html_lib.escape(str((slide or {}).get('title') or ('Content' if lang == OFFER_LANG_ENGLISH else 'المحتوى')))
    slide_type = str((slide or {}).get('type') or 'content')
    content_source = str((slide or {}).get('content_source') or '')
    tokens = [str(token) for token in ((slide or {}).get('image_tokens') or []) if str(token or '').strip()]
    if slide_type == 'cover':
        name = html_lib.escape(str(source.get('project_name') or source.get('projectName') or title))
        project_logo = '<img src="##PROJECT_LOGO##" style="height:80px;width:auto;object-fit:contain;">' if source.get('project_logo') else ''
        return (f'<div class="slide" dir="{slide_dir}" style="width:1280px;height:720px;position:relative;overflow:hidden;background:{primary};color:#fff;">'
                '<div style="position:absolute;inset:0;background-image:url(##IMAGE_COVER##);background-size:cover;background-position:center;"></div>'
                '<div data-cover-overlay></div>'
                f'<div style="position:absolute;z-index:2;inset:64px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px;">'
                f'<div style="display:flex;align-items:center;gap:18px;"><img src="##LOGO##" style="height:80px;width:auto;object-fit:contain;">{project_logo}</div>'
                f'<div style="font-size:48px;font-weight:800;">{name}</div></div></div>')
    if slide_type == 'closing':
        name = html_lib.escape(str(source.get('project_name') or source.get('projectName') or title))
        contact = html_lib.escape(_slide_source_data_note({'content_source': 'contact_closing'}, source)).replace('\n', '<br>')
        project_logo = '<img src="##PROJECT_LOGO##" style="height:80px;width:auto;object-fit:contain;">' if source.get('project_logo') else ''
        return (f'<div class="slide" dir="{slide_dir}" style="width:1280px;height:720px;position:relative;overflow:hidden;background:{primary};color:#fff;">'
                '<div style="position:absolute;inset:0;background-image:url(##IMAGE_COVER##);background-size:cover;background-position:center;"></div>'
                '<div data-cover-overlay></div><div style="position:absolute;z-index:2;inset:70px;display:flex;flex-direction:column;justify-content:center;">'
                f'<div style="display:flex;gap:18px;align-items:center;"><img src="##LOGO##" style="height:80px;width:auto;object-fit:contain;">{project_logo}</div>'
                f'<h2 style="font-size:42px;margin:28px 0 16px;">{name}</h2><div style="font-size:18px;line-height:1.8;">{contact}</div></div></div>')
    if content_source == 'land_boundary_diagram':
        return _build_land_boundary_diagram_slide(
            slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    if content_source == 'land_specs' or (slide.get('section_key') == 'land' and slide.get('design_style') == 'specs'):
        return _build_land_specs_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    if content_source == 'timeline_table_data' or slide.get('design_style') == 'timeline' or slide.get('section_key') == 'timeline':
        return _build_timeline_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    if _is_visual_concept_media_slide(slide):
        return _build_visual_concept_media_slide(slide, branding=branding)
    if str(content_source or '').startswith('site_analysis'):
        analysis = _slide_source_data_note(slide, source)
        if not analysis:
            analysis = str(source.get('site_analysis') or '').strip()
        paragraphs = [part.strip() for part in re.split(r'\r?\n\s*\r?\n', analysis) if part.strip()]
        if not paragraphs and analysis:
            paragraphs = [p.strip() for p in analysis.splitlines() if p.strip()] or [analysis]

        has_map = bool(tokens) or slide.get('requires_image') or '##MAP_OVERVIEW##' in str(slide.get('image_tokens') or [])
        accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
        if has_map:
            p_html = ''.join(
                f'<div style="font-size:13.5px;line-height:1.8;color:#1e293b;border-right:3px solid {accent};padding-right:14px;text-align:justify;">'
                f'{html_lib.escape(p)}</div>'
                for p in paragraphs
            )
            return (
                f'<div class="slide" dir="{slide_dir}" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;color:#172033;padding:68px 36px 44px;box-sizing:border-box;display:flex;flex-direction:column;">'
                f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">'
                f'<h2 style="font-size:26px;color:{primary};font-weight:800;margin:0;">{title}</h2>'
                f'<div style="height:3px;width:60px;background:{accent};border-radius:2px;"></div>'
                f'</div>'
                f'<div style="display:grid;grid-template-columns:1.15fr 1fr;gap:24px;flex:1;min-height:0;">'
                f'<div style="display:flex;flex-direction:column;justify-content:center;gap:14px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:24px;overflow:hidden;box-sizing:border-box;">'
                f'{p_html}'
                f'</div>'
                f'<div style="border-radius:12px;overflow:hidden;border:1px solid #d9e2ec;background:#f1f5f9;display:flex;align-items:center;justify-content:center;">'
                f'<img src="##MAP_OVERVIEW##" style="width:100%;height:100%;object-fit:contain;object-position:center center;">'
                f'</div>'
                f'</div>'
                f'</div>'
            )
        else:
            cards = []
            for i, p in enumerate(paragraphs, 1):
                cards.append(
                    f'<div style="background:#ffffff;border:1px solid #e2e8f0;border-top:4px solid {accent};border-radius:12px;padding:22px;box-shadow:0 4px 12px rgba(0,0,0,0.03);display:flex;flex-direction:column;justify-content:flex-start;gap:10px;box-sizing:border-box;">'
                    f'<div style="font-size:20px;font-weight:800;color:{primary};opacity:0.35;">{i:02d}</div>'
                    f'<div style="font-size:13.5px;line-height:1.8;color:#1e293b;text-align:justify;">{html_lib.escape(p)}</div>'
                    f'</div>'
                )
            grid_cols = '1fr 1fr' if len(cards) <= 2 else '1fr 1fr 1fr'
            return (
                f'<div class="slide" dir="{slide_dir}" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;color:#172033;padding:68px 36px 44px;box-sizing:border-box;display:flex;flex-direction:column;">'
                f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">'
                f'<h2 style="font-size:26px;color:{primary};font-weight:800;margin:0;">{title}</h2>'
                f'<div style="height:3px;width:60px;background:{accent};border-radius:2px;"></div>'
                f'</div>'
                f'<div style="display:grid;grid-template-columns:{grid_cols};gap:20px;flex:1;min-height:0;align-items:stretch;">'
                f'{"".join(cards)}'
                f'</div>'
                f'</div>'
            )
    if re.fullmatch(r'executive_content\.summary(?::\d+:\d+)?', content_source):
        return _build_executive_summary_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    if content_source == 'executive_content.opportunity':
        return _build_executive_opportunity_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    if content_source == 'executive_content.features':
        return _build_executive_features_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    if re.fullmatch(r'market_study_data\.scope', content_source):
        return _build_market_scope_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    if re.fullmatch(r'market_study_data\.summary(?::\d+:\d+)?', content_source):
        return _build_market_summary_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    if re.fullmatch(r'market_study_data\.one_block_summary(?::\d+:\d+)?', content_source):
        return _build_market_one_block_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    if re.fullmatch(r'market_study_data\.sources(?::\d+:\d+)?', content_source):
        return _build_market_sources_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    if content_source == 'market_study_data.swot':
        return _build_market_swot_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    if content_source in {
        'executive_content.risks', 'market_study_data.risk_analysis',
        'market_study_data.risk_register', 'market_study_data.risks',
        'market_study_data.summary.risks',
    }:
        return _build_market_risk_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    if slide_type == 'map_access':
        roads = source.get('access_roads_data') if isinstance(source.get('access_roads_data'), list) else []
        if not roads:
            m_data = source.get('main_roads_data')
            if isinstance(m_data, list) and m_data:
                roads = m_data
            else:
                raw_text = str(source.get('main_roads') or '').strip()
                if raw_text:
                    roads = [{'name': line.strip()} for line in raw_text.splitlines() if line.strip()]
        roads = [r for r in roads if isinstance(r, dict) and str(r.get('name') or '').strip()]
        has_width = any(str(r.get('width_m') or r.get('width') or '').strip() for r in roads)
        has_type = any(str(r.get('type') or '').strip() for r in roads)
        has_dist = any(str(r.get('distance') or r.get('distance_km') or '').strip() for r in roads)

        headers = ['Road / Corridor'] if lang == OFFER_LANG_ENGLISH else ['الطريق / المحور']
        if has_width:
            headers.append('Width (m)' if lang == OFFER_LANG_ENGLISH else 'العرض (م)')
        if has_type:
            headers.append('Type' if lang == OFFER_LANG_ENGLISH else 'النوع')
        if has_dist:
            headers.append('Distance' if lang == OFFER_LANG_ENGLISH else 'المسافة')

        rows = []
        for r in roads:
            row = [str(r.get('name') or '').strip()]
            if has_width:
                row.append(str(r.get('width_m') or r.get('width') or '—').strip())
            if has_type:
                row.append(str(r.get('type') or '—').strip())
            if has_dist:
                row.append(str(r.get('distance') or r.get('distance_km') or '—').strip())
            rows.append(row)

        table = _render_fallback_table(headers, rows, primary) if rows else ''
        return (f'<div class="slide" dir="{slide_dir}" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;padding:68px 28px 44px;box-sizing:border-box;">'
                f'<h2 style="font-size:26px;margin:0 0 14px;color:{primary};font-weight:800;">{title}</h2><div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;height:540px;">'
                f'<div style="border-radius:12px;overflow:hidden;border:1px solid #d9e2ec;background:#f8fafc;display:flex;align-items:center;justify-content:center;">'
                f'<img src="##MAP_ACCESS##" style="width:100%;height:100%;object-fit:contain;">'
                f'</div>'
                f'<div style="overflow:hidden;">{table}</div></div></div>')
    if slide_type == 'map_catchment':
        city_marks = source.get('city_landmarks_data') if isinstance(source.get('city_landmarks_data'), list) else []
        if not city_marks:
            raw_cm = source.get('catchment_areas') or source.get('city_landmarks')
            if isinstance(raw_cm, list):
                city_marks = raw_cm
        city_marks = [r for r in city_marks if isinstance(r, dict)]

        def first_val(item, *keys):
            for k in keys:
                v = item.get(k)
                if v not in (None, '', []):
                    return v
            return ''

        if lang == OFFER_LANG_ENGLISH:
            headers = ['Landmark / Destination', 'Distance (km)', 'Drive Time (min)', 'Category']
        else:
            headers = ['المعلم / الوجهة', 'المسافة (كم)', 'مدة الوصول (دقيقة)', 'التصنيف']

        rows = []
        for r in city_marks:
            name = first_val(r, 'name', 'title', 'landmark')
            if not name:
                continue
            dist = first_val(r, 'distance_km', 'distance', 'distance_text')
            dur = first_val(r, 'duration_minutes', 'duration_min', 'duration', 'minutes', 'duration_text')
            cat = first_val(r, 'category', 'type', 'classification')
            rows.append([name, dist or '—', dur or '—', cat or '—'])

        table = _render_fallback_table(headers, rows, primary) if rows else ''
        return (f'<div class="slide" dir="{slide_dir}" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;padding:68px 28px 44px;box-sizing:border-box;">'
                f'<h2 style="font-size:26px;margin:0 0 14px;color:{primary};font-weight:800;">{title}</h2><div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;height:540px;">'
                f'<div style="border-radius:12px;overflow:hidden;border:1px solid #d9e2ec;background:#f8fafc;display:flex;align-items:center;justify-content:center;">'
                f'<img src="##MAP_CATCHMENT##" style="width:100%;height:100%;object-fit:contain;">'
                f'</div>'
                f'<div style="overflow:hidden;">{table}</div></div></div>')
    if slide_type == 'map_landmarks':
        if lang == OFFER_LANG_ENGLISH:
            headers = ['Landmark', 'Type', 'Distance (km)', 'Duration (min)']
        else:
            headers = ['المعلم', 'النوع', 'المسافة (كم)', 'المدة (دقائق)']
        rows = _nearby_landmark_table_rows(source)
        table = _render_fallback_table(headers, rows, primary) if rows else ''
        return (f'<div class="slide" dir="{slide_dir}" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;padding:68px 28px 44px;box-sizing:border-box;">'
                f'<h2 style="font-size:26px;margin:0 0 14px;">{title}</h2><div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;height:540px;">'
                f'<img src="##MAP_LANDMARKS##" style="width:100%;height:100%;object-fit:contain;">'
                f'<div style="overflow:hidden;">{table}</div></div></div>')
    if tokens:
        columns = 1 if len(tokens) == 1 else len(tokens)
        captions = (slide or {}).get('captions') or (slide or {}).get('bullets') or []
        description = str((slide or {}).get('description') or '').strip()
        cards = []
        for i, token in enumerate(tokens):
            cap = str(captions[i]).strip() if i < len(captions) and str(captions[i] or '').strip() else description
            cap_html = f'<div style="margin-top:8px;padding:8px 12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;font-size:13px;font-weight:600;color:#334155;text-align:center;">{html_lib.escape(cap)}</div>' if cap else ''
            cards.append(f'<div style="display:flex;flex-direction:column;height:100%;min-height:0;overflow:hidden;"><div style="flex:1;min-height:0;border:1px solid #d9e1ea;border-radius:10px;overflow:hidden;background:#fff;display:flex;align-items:center;justify-content:center;"><img src="{html_lib.escape(token)}" style="width:100%;height:100%;object-fit:contain;"></div>{cap_html}</div>')
        return (f'<div class="slide" dir="{slide_dir}" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;padding:68px 34px 44px;box-sizing:border-box;display:flex;flex-direction:column;">'
                f'<h2 style="font-size:26px;margin:0 0 14px;">{title}</h2>'
                f'<div style="display:grid;grid-template-columns:repeat({columns},1fr);gap:16px;flex:1;min-height:0;">{"".join(cards)}</div></div>')

    chart_type = canonicalize_chart_type((slide or {}).get('chart_type'))
    if chart_type == 'waterfall':
        return _build_sol_waterfall_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    elif chart_type == 'combo':
        return _build_sol_combo_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    elif chart_type == 'heatmap':
        return _build_sol_heatmap_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    elif chart_type == 'horizontal_bar':
        return _build_sol_horizontal_bar_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)

    content_sources = (slide or {}).get('content_sources')
    if isinstance(content_sources, list) and len(content_sources) > 1:
        return _build_sol_stacked_tables_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)

    headers, rows = _fallback_table_data(slide, source)
    if rows:
        return _build_sol_table_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)

    note = _slide_source_data_note(slide, source) or '\n'.join(str(item) for item in ((slide or {}).get('bullets') or []))
    if note:
        content = html_lib.escape(note).replace('\n', '<br>')
        return (f'<div class="slide" dir="{slide_dir}" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;padding:90px 48px 60px;box-sizing:border-box;">'
                f'<h2 style="font-size:28px;color:{primary};">{title}</h2><div style="font-size:16px;line-height:1.8;">{content}</div></div>')
    return None


def _validate_chart_slide_html(html, chart_type, slide, project_data=None):
    """
    Validates that a generated chart slide meets all architectural and content requirements.
    Returns an error message string if invalid (to trigger a retry), or None if valid.
    """
    chart_type = canonicalize_chart_type(chart_type)
    if not chart_type:
        return None

    html_lower = html.lower()

    # Rule 1: Every chart slide must have the approved data table (<table) side-by-side with the visual chart
    if '<table' not in html_lower:
        return "الشريحة ملزمة بعرض جدول البيانات الرقمي الكامل (table) بجانب المخطط البياني في تقسيم 50/50. أعد الشريحة مع الجدول المعتمد."

    # Rule 2: Chart-specific structural and semantic checks
    if chart_type == 'waterfall':
        # Must have floating bar geometry
        if not re.search(r'height\s*:\s*\d+%', html, re.IGNORECASE) or not re.search(r'(?:bottom|margin-bottom|top)\s*:\s*\d+%', html, re.IGNORECASE):
            return "مخطط الشلال (waterfall) يتطلب أعمدة عائمة مع ارتفاعات ومسافات سفلية واضحة بنسب مئوية (height, bottom/margin-bottom)."
        # Must have total pillar / final cost
        if not any(kw in html for kw in ('إجمالي', 'المجموع', 'صافي', 'total', 'Total')):
            return "مخطط الشلال (waterfall) يجب أن يتضمن عمود الإجمالي النهائي المرتكز على خط الأساس."
        # Must have monetary or numerical values
        if not re.search(r'\d+(?:\.\d+)?\s*(?:م\.ر|مليون|ر\.س|SAR|%)', html) and not re.search(r'\d{1,3}(?:,\d{3})+', html):
            return "مخطط الشلال (waterfall) يجب أن يعرض أرقام التكلفة بوضوح على كل عمود أو تحته (ر.س)."

    elif chart_type == 'horizontal_bar':
        # Must have horizontal bars with percentage widths
        if not re.search(r'width\s*:\s*(?:\d+%\s*|calc\([^)]+\))', html, re.IGNORECASE):
            return "مخطط الأشرطة الأفقية (horizontal_bar) يتطلب عناصر أشرطة بعروض نسبية (width: ...%)."
        # Must mention project or comparison
        if not any(kw in html for kw in ('المشروع', 'مشروع', 'سعر', 'المقترح', 'منافس', 'م²', 'project', 'Project', 'price', 'Price', 'competitor', 'Competitor')):
            return "مخطط الأشرطة الأفقية (horizontal_bar) يجب أن يتضمن أسماء المنافسين وسعر المشروع المقترح."

    elif chart_type == 'combo':
        # Must have cash flow bars (bars with #10b981 / #ef4444 or explicit bar containers)
        has_flow_bars = any(c in html_lower for c in ('#10b981', '#ef4444', 'bar_direction', 'net_flow', 'flow-bar')) or (
            html_lower.count('background:') >= 4 and re.search(r'(?:top|bottom)\s*:\s*(?:50%|\d+%)', html)
        )
        if not has_flow_bars:
            return "المخطط المدمج (combo) يتطلب رسم أعمدة التدفق السنوي (أعمدة خضراء وحمراء موجبة وسالبة) لكل سنة بجانب منحنى الرصيد التراكمي."
        # Must have SVG cumulative line and closed SVG
        if '<svg' not in html_lower or '</svg>' not in html_lower:
            return "المخطط المدمج (combo) يتطلب منحنى الرصيد التراكمي في عنصر <svg> مغلق بالكامل يربط نقاط السنوات."
        if '<polyline' not in html_lower and '<path' not in html_lower:
            return "المخطط المدمج (combo) يتطلب مسار خطي (polyline أو path) داخل الـ SVG للرصيد التراكمي."
        # Must have year labels
        if not any(kw in html for kw in ('سنة', 'عام', 'Year', 'year', 'تراكمي', 'صافي')):
            return "المخطط المدمج (combo) يتطلب تسميات السنوات ومؤشرات التدفق السنوي والتراكمي."

    elif chart_type == 'heatmap':
        # Must compare scenarios
        has_scenarios = (any(kw in html for kw in ('متحفظ', 'تحفظ')) and any(kw in html for kw in ('أساسي', 'اساسي', 'واقعي')) and any(kw in html for kw in ('متفائل', 'تفاؤل'))) or (
            'conservative' in html_lower and 'optimistic' in html_lower and any(kw in html_lower for kw in ('base', 'baseline', 'moderate')))
        if not has_scenarios:
            return "الخريطة الحرارية (heatmap) يجب أن تعرض سيناريوهات الحساسية الثلاثة (متحفظ، أساسي، متفائل)."
        # Must have visual color shading / highlight
        if not re.search(r'background\s*:\s*(?:rgba|#[0-9a-fA-F]{3,8}|hsl)', html, re.IGNORECASE):
            return "الخريطة الحرارية (heatmap) تتطلب تمييزًا لونيًا لخلايا السيناريو الأفضل."

    return None


def _validate_market_visual_design(html, slide):
    """Keep the market designer open; layout safety is handled after generation."""
    if _slide_section_key(slide) != 'market' or not html:
        return None
    # The competitor comparison is deterministic and checked separately. Every
    # other market slide belongs to SOL, so visual taste must never trigger a
    # paid retry merely because it chose prose, a diagram, a table, or a new
    # composition. The post-processing frame handles centering and flow safety.
    return None


def generate_single_slide(system_prompt, slide, slide_num, total_slides, branding, call_glm_fn, max_retries=2, project_data=None):
    """
    Generate a single slide's HTML.
    call_glm_fn: function(system_prompt, user_msg, max_tokens) -> response_dict
    """
    # A section divider is one fixed layout with different text, so it is rendered here instead of
    # being asked from the model on every deck: identical on every divider, and no call at all.
    if (slide or {}).get('type') == 'index':
        return build_index_slide(slide, slide_num, total_slides, branding, project_data)
    if (slide or {}).get('type') == 'section_divider':
        return build_section_divider_slide(slide, slide_num, total_slides, branding, project_data)

    slide = _normalize_legacy_single_slide(dict(slide or {}), project_data)

    # Single-slide requests may come from an older client and bypass the full
    # plan normalizer. Apply the same market contract to that one item.
    if _slide_section_key(slide) == 'market':
        slide = dict(slide or {})
        market = _market_state(project_data)
        title_text = str(slide.get('title') or '').strip()
        content_source = str(slide.get('content_source') or '').strip()
        if (
            content_source.startswith('market_study_data.competitors')
            or slide.get('source_table') == 'competitors'
            or re.search(r'(?:منافس|competitor)', title_text, flags=re.IGNORECASE)
        ):
            default_title = 'Competitor Comparison' if resolve_offer_lang(project_data) == OFFER_LANG_ENGLISH else 'مقارنة المنافسين'
            preserved_title = title_text if re.search(r'(?:منافس|competitor)', title_text, flags=re.IGNORECASE) else default_title
            preserved_source = content_source if content_source.startswith('market_study_data.competitors') else 'market_study_data.competitors'
            slide.update({
                'title': preserved_title, 'type': 'content', 'section_key': 'market',
                'design_style': 'chart', 'chart_type': 'horizontal_bar',
                'requires_image': False, 'image_tokens': [],
                'content_source': preserved_source, 'source_table': 'competitors',
            })
        elif re.fullmatch(r'market_study_data\.(?:scope|summary|one_block_summary|sources)(?::\d+:\d+)?', content_source):
            slide.update({'type': 'content', 'section_key': 'market', 'requires_image': False, 'image_tokens': []})
        else:
            if re.search(r'نطاق', title_text, flags=re.IGNORECASE) and _market_scope_rows(market):
                slide['content_source'] = 'market_study_data.scope'
                slide['source_table'] = 'market_scope'
                slide['design_style'] = 'table'
            elif re.search(r'مصادر', title_text, flags=re.IGNORECASE) and _market_source_rows(market):
                slide['content_source'] = 'market_study_data.sources'
                slide['source_table'] = 'market_sources'
                slide['design_style'] = 'table'
            elif re.search(r'ملخص', title_text, flags=re.IGNORECASE):
                slide['content_source'] = (
                    'market_study_data.one_block_summary'
                    if str(market.get('one_block_summary') or '').strip()
                    else 'market_study_data.summary'
                )
                slide['source_table'] = 'market_summary' if slide['content_source'] == 'market_study_data.summary' else ''
                slide['design_style'] = 'text' if slide['content_source'] == 'market_study_data.one_block_summary' else 'table'
            slide.update({'type': 'content', 'section_key': 'market', 'requires_image': False, 'image_tokens': [], 'chart_type': ''})

    chart_type = canonicalize_chart_type((slide or {}).get('chart_type'))
    market_source = str((slide or {}).get('content_source') or '')
    fixed_market_comparison = (
        _slide_section_key(slide) == 'market'
        and bool(re.fullmatch(r'market_study_data\.competitors(?::\d+:\d+)?', market_source))
        and chart_type == 'horizontal_bar'
    )
    fixed_land_boundary_diagram = market_source == 'land_boundary_diagram'
    fixed_map_slide = slide.get('type') in {
        'map_overview', 'map_landmarks', 'map_access', 'map_catchment'
    }
    deterministic_market_source = bool(
        re.fullmatch(r'market_study_data\.(?:scope|summary|sources)(?::\d+:\d+)?', market_source)
        or bool(re.fullmatch(r'market_study_data\.competitors(?::\d+:\d+)?', market_source))
        or market_source in {
            'market_study_data.swot',
            'executive_content.risks', 'market_study_data.risk_analysis',
            'market_study_data.risk_register', 'market_study_data.risks',
            'market_study_data.summary.risks',
        }
    )
    free_market_slide = _slide_section_key(slide) == 'market' and not fixed_market_comparison
    # A stale plan must not turn an arbitrary market page into a chart or a
    # fixed market template.  The sole fixed market page is the competitor
    # comparison; approved financial charts remain fixed in the financial
    # section, as required by the financial report contract.
    if _slide_section_key(slide) == 'market' and not fixed_market_comparison:
        chart_type = ''
        slide['chart_type'] = ''
    if _is_visual_concept_media_slide(slide):
        deterministic_slide = _build_visual_concept_media_slide(slide, branding=branding)
        if deterministic_slide:
            return postprocess_slide(
                deterministic_slide, (slide or {}).get('type', 'content'),
                slide_num=slide_num, slide_title=(slide or {}).get('title', f'شريحة {slide_num}'),
                total_slides=total_slides, tenant_id=(branding or {}).get('tenant_id'),
                branding=branding, project_data=project_data,
                content_source=str((slide or {}).get('content_source') or ''),
            )
    if (fixed_market_comparison
            or fixed_land_boundary_diagram
            or fixed_map_slide
            or deterministic_market_source
            or (_slide_section_key(slide) != 'market'
                and (chart_type in APPROVED_CHART_TYPES
                     or market_source == 'land_and_building_summary'
                     or _slide_section_key(slide) == 'financial'))):
        deterministic_slide = _build_structured_fallback_slide(slide, project_data, branding, slide_num=slide_num, total_slides=total_slides)
        if deterministic_slide:
            return postprocess_slide(
                deterministic_slide, (slide or {}).get('type', 'content'),
                slide_num=slide_num, slide_title=(slide or {}).get('title', f'شريحة {slide_num}'),
                total_slides=total_slides, tenant_id=(branding or {}).get('tenant_id'),
                branding=branding, project_data=project_data, content_source=market_source
            )
    user_msg = build_slide_user_msg(slide, slide_num, total_slides, branding, project_data=project_data)
    slide_title = slide.get('title', f'شريحة {slide_num}')
    slide_type = slide.get('type', 'content')
    retry_note = ''
    free_market_model_html = None

    for attempt in range(1, max_retries + 2):
        try:
            print(f"[SLIDE-{slide_num}] Attempt {attempt}: {slide_title}")
            response = call_glm_fn(system_prompt, user_msg + retry_note, max_tokens=6000)
            if 'choices' not in response or not response['choices']:
                print(f"[SLIDE-{slide_num}] ERROR: no choices (attempt {attempt})")
                continue

            content = response['choices'][0].get('message', {}).get('content', '')
            html = extract_html_from_glm(content)
            if not html:
                print(f"[SLIDE-{slide_num}] ERROR: no HTML extracted (attempt {attempt})")
                retry_note = '\n\nإعادة المحاولة: لم يصل HTML صالح. أخرج div class="slide" واحدًا مكتملًا فقط.'
                continue
            html = _strip_unplanned_creative_tokens(html, slide)
            content_source = str(slide.get('content_source') or '')
            chart_type = canonicalize_chart_type(slide.get('chart_type'))
            if chart_type:
                chart_err = _validate_chart_slide_html(html, chart_type, slide, project_data)
                if chart_err:
                    print(f"[SLIDE-{slide_num}] ERROR: chart validation failed: {chart_err} (attempt {attempt})")
                    retry_note = f'\n\nإعادة المحاولة: {chart_err}'
                    continue
            elif re.search(
                    r'(?:data-chart|class\s*=\s*["\'][^"\']*(?:chart|treemap|heatmap)|conic-gradient\s*\()',
                    html, flags=re.IGNORECASE):
                print(f"[SLIDE-{slide_num}] ERROR: unplanned chart outside selected financial charts (attempt {attempt})")
                retry_note = '\n\nإعادة المحاولة: هذه الشريحة لا تحمل chart_type؛ احذف الرسم البياني واعرض النص أو الجدول فقط.'
                continue
            market_design_err = _validate_market_visual_design(html, slide)
            if market_design_err:
                print(f"[SLIDE-{slide_num}] ERROR: market visual design failed: {market_design_err} (attempt {attempt})")
                retry_note = f'\n\nإعادة المحاولة: {market_design_err} طبّق المرجع البصري للتقرير الاستثماري، مع الحفاظ على النصوص والأرقام.'
                continue
            if free_market_slide and len(extract_slide_elements(html)) == 1:
                # If the model's composition is structurally sound but the
                # completeness audit keeps retrying, preserve SOL's design
                # instead of replacing it with a deterministic market page.
                free_market_model_html = html
            if _slide_section_key(slide) == 'financial' and not chart_type and '<table' not in html.lower():
                print(f"[SLIDE-{slide_num}] ERROR: financial slide must use table, not cards/boxes (attempt {attempt})")
                retry_note = '\n\nإعادة المحاولة: شريحة الدراسة المالية ملزمة باستخدام جداول HTML نظامية (table) بتصميم تقرير PDF. احذف الكروت العائمة والمربعات واعرض البيانات داخل جدول كامل.'
                continue
            missing_images = [token for token in (slide.get('image_tokens') or []) if token not in html]
            if missing_images:
                missing = '، '.join(missing_images)
                print(f"[SLIDE-{slide_num}] ERROR: missing required images: {missing} (attempt {attempt})")
                retry_note = (
                    f'\n\nإعادة المحاولة: الاستجابة السابقة حذفت الصور الإلزامية التالية: {missing}. '
                    'أعد الشريحة كاملة واستخدم كل رمز صورة مرة واحدة فقط وبحجم واضح.'
                )
                continue
            missing_texts = _missing_required_slide_texts(html, slide, project_data)
            if missing_texts:
                missing = '، '.join(missing_texts[:12])
                print(f"[SLIDE-{slide_num}] ERROR: missing required content: {missing} (attempt {attempt})")
                retry_note = (
                    f'\n\nإعادة المحاولة: الاستجابة السابقة حذفت البنود الإلزامية التالية: {missing}. '
                    'أعد الشريحة كاملة وانقل كل صف مطلوب دون اختصار أو حذف.'
                )
                continue
            html = postprocess_slide(
                html, slide_type, slide_num=slide_num, slide_title=slide_title,
                total_slides=total_slides, tenant_id=branding.get('tenant_id'),
                branding=branding, project_data=project_data, content_source=content_source)
            roots = extract_slide_elements(html)
            if len(roots) != 1:
                print(f"[SLIDE-{slide_num}] ERROR: expected one slide div, found {len(roots)} (attempt {attempt})")
                retry_note = f'\n\nإعادة المحاولة: أخرج جذر شريحة واحدًا فقط؛ الاستجابة السابقة احتوت {len(roots)} جذور.'
                continue
            # The audit runs on the finalized HTML: post-processing has already
            # repaired fixable contrast problems, so a failure here is a genuine
            # layout issue worth one more model pass — not a billable redesign
            # loop over a color the normalizer could have set deterministically.
            contrast_issues = slide_contrast_issues(html)
            if contrast_issues:
                sample, foreground, surface, ratio = contrast_issues[0]
                print(f"[SLIDE-{slide_num}] ERROR: contrast {ratio:.2f}:1 for {foreground} on {surface} (attempt {attempt})")
                retry_note = (
                    f'\n\nإعادة المحاولة: فشل التباين في النص «{sample}»: اللون {foreground} فوق {surface} '
                    f'بنسبة {ratio:.2f}:1. أعد الشريحة كاملة واجعل كل نص 4.5:1 على الأقل، ولا تغيّر المحتوى.'
                )
                continue
            print(f"[SLIDE-{slide_num}] OK: {len(html)} chars")
            return roots[0]
        except Exception as e:
            print(f"[SLIDE-{slide_num}] Exception: {e}")

    if free_market_model_html:
        preserved = postprocess_slide(
            free_market_model_html, slide_type, slide_num=slide_num,
            slide_title=slide_title, total_slides=total_slides,
            tenant_id=branding.get('tenant_id'), branding=branding,
            project_data=project_data, content_source=str(slide.get('content_source') or ''),
        )
        roots = extract_slide_elements(preserved)
        if len(roots) == 1:
            print(f"[SLIDE-{slide_num}] Preserving SOL market composition after content retries")
            return roots[0]

    fallback = _build_structured_fallback_slide(slide, project_data, branding, slide_num=slide_num, total_slides=total_slides)
    if fallback:
        fallback = postprocess_slide(
            fallback, slide_type, slide_num=slide_num, slide_title=slide_title,
            total_slides=total_slides, tenant_id=branding.get('tenant_id'),
            branding=branding, project_data=project_data, content_source=str(slide.get('content_source') or ''))
        roots = extract_slide_elements(fallback)
        if len(roots) == 1:
            print(f"[SLIDE-{slide_num}] Using deterministic fallback after {max_retries + 1} attempts")
            return roots[0]
    print(f"[SLIDE-{slide_num}] FAILED after {max_retries + 1} attempts")
    return None


def _canonicalize_slide_root_class(html):
    match = re.match(r'^(<div\b[^>]*?)\bclass\s*=\s*(["\'])([^"\']*)\2', str(html or '').lstrip(), re.IGNORECASE)
    if not match or 'slide' not in match.group(3).split():
        return html
    stripped = str(html or '').lstrip()
    leading = str(html or '')[:len(str(html or '')) - len(stripped)]
    return leading + match.group(1) + 'class="slide"' + stripped[match.end():]


def extract_html_from_glm(content):
    """Extract HTML from GLM response content."""
    if not content:
        return None

    # Try to extract from code block first
    code_match = re.search(r'```(?:html)?\s*\n?([\s\S]*?)```', content)
    if code_match:
        html = code_match.group(1).strip()
    else:
        html = content.strip()

    # Basic cleanup
    html = html.replace('```html', '').replace('```', '').strip()

    slides = extract_slide_elements(html)
    if slides:
        return '\n'.join(_canonicalize_slide_root_class(slide) for slide in slides)

    # If no slide div, wrap the whole HTML in one as a fallback
    if 'class="slide"' not in html and "class='slide'" not in html:
        if '<html' in html or '<body' in html or '<div' in html:
            html = f'<div class="slide" style="width:1280px;height:720px;direction:rtl;font-family:sans-serif;">{html}</div>'
        else:
            return None

    return html
