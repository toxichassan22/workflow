# Market slide fallbacks.

def _market_value_html(value):
    return html_lib.escape(html_lib.unescape(str(value or 'غير متوفر'))).replace('\n', '<br>')


def _source_url(value):
    """Return a safe absolute http(s) URL, or '' when the value is not one."""
    url = html_lib.unescape(str(value or '')).strip().strip('"\'<>')
    if not url:
        return ''
    if url.lower().startswith('//'):
        url = 'https:' + url
    elif not re.match(r'^[a-z][a-z0-9+.-]*://', url, flags=re.IGNORECASE):
        # A bare `www.example.com/page` used to reach the deck as written, so a
        # click resolved against the app origin and the reader landed on a 404.
        if re.match(r'^(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:[/:?#]|$)',
                    url, flags=re.IGNORECASE):
            url = 'https://' + url
        else:
            return ''
    scheme = url.split(':', 1)[0].lower()
    return url if scheme in ('http', 'https') else ''


def _source_url_html(value):
    """The source cell as a real external link, never as bare text."""
    raw = str(value or '').strip()
    url = _source_url(raw)
    if not url:
        return _market_value_html(raw)
    return (
        f'<a href="{html_lib.escape(url, quote=True)}" target="_blank" '
        'rel="noopener noreferrer" dir="ltr" '
        f'style="color:#1d4ed8;text-decoration:underline;word-break:break-all;'
        f'overflow-wrap:anywhere;">{html_lib.escape(url)}</a>'
    )


def _market_paragraph_blocks(value, count=3):
    """Split approved prose into visual blocks without changing its wording."""
    text = re.sub(r'\s+', ' ', str(value or '').strip())
    if not text:
        return []
    sentences = [item.strip() for item in re.split(r'(?<=[.!؟])\s+', text) if item.strip()]
    if len(sentences) <= 1:
        words = text.split()
        size = max(1, (len(words) + count - 1) // count)
        return [' '.join(words[index:index + size]) for index in range(0, len(words), size)]
    block_size = max(1, (len(sentences) + count - 1) // count)
    return [" ".join(sentences[index:index + block_size]) for index in range(0, len(sentences), block_size)]


def _build_market_scope_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render the market scope as an editorial overview instead of a raw key/value table."""
    source = source if isinstance(source, dict) else {}
    offer_lang = resolve_offer_lang(source)
    en = offer_lang == OFFER_LANG_ENGLISH
    market = _market_state(source)
    rows = _market_scope_rows(market, offer_lang)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or ('Study Scope' if en else 'نطاق الدراسة')))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))
    midpoint = (len(rows) + 1) // 2
    columns = (rows[:midpoint], rows[midpoint:])

    def render_row(label, value):
        return (
            f'<div style="padding:16px 18px;border-bottom:1px solid #e2e8f0;box-sizing:border-box;">'
            f'<div style="font-size:13px;font-weight:800;color:{primary};margin-bottom:6px;">{html_lib.escape(str(label))}</div>'
            f'<div style="font-size:14px;line-height:1.75;color:#334155;text-align:justify;">{_market_value_html(value)}</div></div>'
        )

    column_html = ''.join(
        f'<div style="background:#ffffff;border:1px solid #dbe4ee;border-top:4px solid {primary};border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.03);">'
        + ''.join(render_row(label, value) for label, value in column)
        + '</div>'
        for column in columns if column
    )
    city = str(source.get('city') or '').strip()
    district = str(source.get('district') or '').strip()
    location_line = ' — '.join(item for item in (district, city) if item)
    location_html = (
        f'<div style="background:#f1f5f9;border-radius:10px;padding:12px 18px;border:1px solid #cbd5e1;min-width:200px;">'
        f'<div style="font-size:11px;font-weight:800;color:#475569;margin-bottom:4px;">{"Project Geographic Scope" if en else "النطاق الجغرافي للمشروع"}</div>'
        f'<div style="font-size:16px;font-weight:800;color:{primary};">{html_lib.escape(location_line)}</div></div>'
    ) if location_line else ''

    # Additional contextual highlights so the slide feels rich and comprehensive
    context_cards = []
    prop_type = str(source.get('property_type') or source.get('project_type') or '').strip()
    if prop_type:
        context_cards.append(f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;">'
                             f'<div style="font-size:11px;font-weight:700;color:#64748b;">{"Asset Type" if en else "نوع الأصل الاستثماري"}</div>'
                             f'<div style="font-size:13.5px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(prop_type)}</div></div>')
    decision = str(market.get('decision') or '').strip()
    if decision:
        context_cards.append(f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;">'
                             f'<div style="font-size:11px;font-weight:700;color:#64748b;">{"Market Fit Rating" if en else "تصنيف ملاءمة السوق"}</div>'
                             f'<div style="font-size:13.5px;font-weight:800;color:{accent};margin-top:2px;">{html_lib.escape(decision)}</div></div>')
    sources_count = len(market.get('sources') or [])
    if sources_count:
        context_cards.append(f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;">'
                             f'<div style="font-size:11px;font-weight:700;color:#64748b;">{"Approved Reference Sources" if en else "المصادر المرجعية المعتمدة"}</div>'
                             f'<div style="font-size:13.5px;font-weight:800;color:{primary};margin-top:2px;">{sources_count} {"data sources" if en else "مصادر بيانات"}</div></div>')
    highlights_html = (
        f'<div style="margin-top:16px;display:grid;grid-template-columns:repeat({len(context_cards)}, 1fr);gap:14px;">{"".join(context_cards)}</div>'
        if context_cards else ''
    )

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    slide_dir = 'ltr' if en else 'rtl'
    subtitle = ('The geographic and methodological frame the market reading is bound to'
                if en else 'الإطار الجغرافي والزمني والمنهجي المعتمد لقراءة السوق')
    heading = 'Market Definition & Study Scope' if en else 'تعريف السوق ونطاق الدراسة'
    subheading = ('Criteria governing the comparison and analysis domain'
                  if en else 'المحددات والمعايير التي تحكم مجال المقارنة والتحليل')
    return f'''<div class="slide" dir="{slide_dir}" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">MARKET SCOPE</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">{subtitle}</p>
      </div>
    </div>
  </header>
  <div data-market-scope="1" style="padding:0 36px;margin-top:14px;">
    <div style="background:#ffffff;border:1px solid #dbe4ee;border-radius:12px;padding:22px 24px;box-sizing:border-box;">
      <div style="display:flex;align-items:end;justify-content:space-between;gap:20px;border-bottom:1px solid #dbe4ee;padding-bottom:14px;margin-bottom:16px;direction:{slide_dir};">
        <div><div style="font-size:22px;font-weight:800;color:{primary};">{heading}</div><div style="font-size:12px;color:#64748b;margin-top:5px;">{subheading}</div></div>
        {location_html}
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start;">
        {column_html}
      </div>
      {highlights_html}
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">{"Market Analysis — Study Scope" if en else "تحليل السوق — نطاق الدراسة"}</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


_MARKET_NUMERAL_RE = re.compile(
    r'\d[\d,]*(?:\.\d+)?(?:\s*(?:%|ر\.س|ريال|مليون|م²|كم|سنة|سنوات|شهرًا?|وحدة|شقة|غرفة|دقيقة))?')


def _market_rich_text(value, accent, weight='700'):
    """Escape approved text and bold the figures already inside it."""
    text = html_lib.escape(html_lib.unescape(str(value or ''))).replace('\n', '<br>')
    return _MARKET_NUMERAL_RE.sub(
        rf'<strong style="color:{accent};font-weight:{weight};">\g<0></strong>', text)


def _build_market_summary_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render one readable page of the detailed market analysis."""
    source = source if isinstance(source, dict) else {}
    market = _market_state(source)
    rows, _row_offset = _market_rows_for_slide(
        slide, 'market_study_data.summary', _market_summary_rows(market)
    )
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'تحليل السوق'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))
    is_prose = isinstance(market.get('summary'), str) and bool(str(market.get('summary') or '').strip())
    subtitle = 'قراءة تحليلية للعرض والطلب والمنافسة والفرصة الاستثمارية'
    compact = len(rows) <= 2

    def topic_text_html(value, accent_color, weight='700'):
        return _market_rich_text(value, accent_color, weight)

    if is_prose:
        prose_blocks = _market_paragraph_blocks(rows[0][1] if rows else '', 3)
        prose_rows = ''.join(
            f'<div data-market-analysis-block="{index + 1}" style="display:flex;gap:16px;padding:14px 2px;'
            f'border-bottom:1px solid #e2e8f0;align-items:flex-start;">'
            f'<span style="font-size:22px;font-weight:800;color:{accent};line-height:1.1;min-width:34px;">{index + 1:02d}</span>'
            f'<div style="flex:1;font-size:13.5px;line-height:1.9;color:#1f2937;text-align:justify;">'
            f'{topic_text_html(block, accent)}</div></div>'
            for index, block in enumerate(prose_blocks)
        )
        body_content = (
            f'<div data-market-analysis="1" style="background:#ffffff;border:1px solid #dbe4ee;border-radius:12px;'
            f'padding:10px 26px;box-sizing:border-box;">{prose_rows}</div>'
        )
    else:
        decision = str(market.get('decision') or '').strip()
        decision_html = (
            f'<div style="display:flex;align-items:center;gap:12px;background:#f8fafc;border:1px solid #e2e8f0;'
            f'border-right:4px solid {accent};border-radius:8px;padding:8px 16px;margin-bottom:12px;">'
            f'<span style="font-size:11px;font-weight:700;color:#64748b;white-space:nowrap;">تصنيف الدراسة</span>'
            f'<span style="font-size:14px;font-weight:800;color:{primary};">{html_lib.escape(decision)}</span></div>'
        ) if decision and _row_offset == 0 else ''

        lead_label, lead_value = rows[0] if rows else ('تحليل السوق', '')
        lead_columns = 'column-count:2;column-gap:34px;' if len(str(lead_value or '')) > 320 else ''
        lead_font = '14.5px' if compact else '13.5px'
        lead_html = (
            f'<div style="background:{primary};border-radius:12px;padding:{26 if compact else 20}px 28px;'
            f'box-sizing:border-box;position:relative;overflow:hidden;">'
            f'<div style="display:flex;align-items:baseline;gap:14px;margin-bottom:{12 if compact else 8}px;">'
            f'<span style="font-size:30px;font-weight:800;color:{accent};line-height:1;">{_row_offset + 1:02d}</span>'
            f'<span style="font-size:{19 if compact else 17}px;font-weight:800;color:#ffffff;">{html_lib.escape(str(lead_label))}</span>'
            f'<span style="flex:1;border-bottom:1px solid rgba(255,255,255,0.22);transform:translateY(-6px);"></span>'
            f'</div>'
            f'<div style="font-size:{lead_font};line-height:1.85;color:#eef2f7;text-align:justify;{lead_columns}">'
            f'{topic_text_html(lead_value, accent)}</div>'
            f'</div>'
        )

        def render_topic(index, label, value):
            text_len = len(re.sub(r'\s+', ' ', str(value or '')).strip())
            columns = 'column-count:2;column-gap:30px;' if text_len > 420 else ''
            body_font = '13px' if compact else '12.5px'
            return (
                f'<div data-market-analysis-topic="{index}" style="padding:{14 if compact else 11}px 2px 0;">'
                f'<div style="display:flex;align-items:baseline;gap:12px;">'
                f'<span style="font-size:{24 if compact else 21}px;font-weight:800;color:{accent};line-height:1;min-width:34px;">{index:02d}</span>'
                f'<span style="font-size:{15.5 if compact else 14}px;font-weight:800;color:{primary};white-space:nowrap;">{html_lib.escape(str(label))}</span>'
                f'<span style="flex:1;border-bottom:1px solid #e2e8f0;transform:translateY(-5px);"></span>'
                f'</div>'
                f'<div style="margin-top:{8 if compact else 5}px;font-size:{body_font};line-height:{1.85 if compact else 1.72};'
                f'color:#334155;text-align:justify;{columns}">{topic_text_html(value, accent)}</div>'
                f'</div>'
            )

        topics_html = ''.join(
            render_topic(_row_offset + idx + 1, label, value)
            for idx, (label, value) in enumerate(rows[1:], 1)
        )
        body_content = (
            f'<div data-market-analysis="1" style="display:flex;flex-direction:column;">'
            f'{decision_html}{lead_html}{topics_html}</div>'
        )

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">MARKET SUMMARY</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">{subtitle}</p>
      </div>
    </div>
  </header>
  <div style="padding:0 40px;margin-top:12px;">
    {body_content}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">تحليل السوق</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _market_one_block_paragraph(market):
    """Return the executive market summary as one prose paragraph."""
    value = str((market or {}).get('one_block_summary') or '').replace('\\r\\n', '\n').replace('\\n', '\n').strip()
    try:
        import market_study
        is_paragraph = market_study.is_market_summary_paragraph(value)
    except Exception:
        is_paragraph = bool(value and not re.search(r'(?m)^\s*\d+[.)]\s+', value))
    if is_paragraph:
        return re.sub(r'\s+', ' ', value).strip()
    summary = (market or {}).get('summary')
    if isinstance(summary, dict):
        try:
            import market_study
            fallback = market_study.summary_prose(summary)
        except Exception:
            fallback = ' '.join(str(summary.get(key) or '').strip() for key in (
                'market_definition', 'city_position', 'sector_performance', 'supply',
                'demand', 'competition', 'market_gap', 'recommendation', 'risks'
            ) if str(summary.get(key) or '').strip())
        if fallback:
            return re.sub(r'\s+', ' ', fallback).strip()
    return re.sub(r'\s+', ' ', str(summary or '').strip()).strip() if isinstance(summary, str) else re.sub(r'\s+', ' ', value).strip()


def _market_one_block_text(slide, market):
    source = str((slide or {}).get('content_source') or '')
    value = _market_one_block_paragraph(market)
    match = re.fullmatch(r'market_study_data\.one_block_summary:(\d+):(\d+)', source)
    if match:
        value = value[int(match.group(1)):int(match.group(2))]
    return value.strip()


def _build_market_one_block_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render the complete work-market summary as one full-width paragraph."""
    source = source if isinstance(source, dict) else {}
    market = _market_state(source)
    value = _market_one_block_text(slide, market)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'ملخص دراسة سوق العمل'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))
    market = _market_state(source)
    blocks = _market_paragraph_blocks(value, 3)
    decision = str(market.get('decision') or '').strip()
    disclaimer = str(market.get('disclaimer') or '').strip()
    block_html = ''.join(
        f'<p style="padding:0 0 17px;margin:0 0 17px;'
        f'border-bottom:1px solid #dbe4ee;font-size:13.4px;line-height:1.9;color:#1f2937;text-align:justify;" data-market-work-block="{index + 1}">'
        f'{_market_value_html(block)}</p>'
        for index, block in enumerate(blocks)
    )
    aside_parts = []
    if decision:
        aside_parts.append(
            f'<div style="background:{primary};color:#ffffff;border-radius:10px;padding:18px 16px;margin-bottom:16px;">'
            f'<div style="font-size:12px;font-weight:800;margin-bottom:8px;">تصنيف الدراسة</div>'
            f'<div style="font-size:18px;font-weight:800;line-height:1.45;">{html_lib.escape(decision)}</div></div>'
        )
    aside_parts.append(
        f'<div style="border-right:5px solid {accent};padding:7px 16px 7px 6px;">'
        f'<div style="font-size:15px;font-weight:800;color:{primary};margin-bottom:9px;">خلاصة القرار</div>'
        f'<div style="font-size:12px;line-height:1.85;color:#475569;text-align:justify;">قراءة السوق تجمع المؤشرات المعتمدة في مسار واحد لاتخاذ القرار.</div></div>'
    )
    if disclaimer:
        aside_parts.append(
            f'<div style="background:#e8dcc0;border-radius:10px;padding:14px 16px;margin-top:20px;color:#1f2937;">'
            f'<div style="font-size:12px;font-weight:800;margin-bottom:7px;">إخلاء المسؤولية</div>'
            f'<div style="font-size:11.5px;line-height:1.7;text-align:justify;">{_market_value_html(disclaimer)}</div></div>'
        )
    # This is only the emergency renderer used when SOL is unavailable. Keep
    # it in ordinary block flow so browser and PDF engines cannot overlap the
    # decision card with the narrative when CSS grid support differs.
    body_html = (
        f'<div data-market-work-summary="1" style="background:#ffffff;border:1px solid #dbe4ee;border-radius:12px;'
        f'padding:20px 26px;min-height:0;max-height:none;overflow:visible;box-sizing:border-box;box-shadow:0 3px 10px rgba(15,23,42,.05);'
        f'display:block;direction:rtl;">'
        f'<div style="border-right:5px solid {accent};padding:0 16px 12px 6px;margin-bottom:16px;">'
        f'<div style="font-size:15px;font-weight:800;color:{primary};margin-bottom:9px;">ملخص القرار</div>'
        f'<div style="font-size:12px;line-height:1.85;color:#475569;text-align:justify;">قراءة السوق تجمع المؤشرات المعتمدة في مسار واحد لاتخاذ القرار.</div></div>'
        f'<div style="display:block;">'
        f'<div style="font-size:22px;font-weight:800;color:{primary};margin:0 0 14px;text-align:right;">القراءة النهائية للسوق</div>'
        f'{block_html}</div>'
        f'{("".join(aside_parts[:1])) if decision else ""}'
        f'{("".join(aside_parts[-1:])) if disclaimer else ""}'
        f'</div>'
    )

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">MARKET WORK SUMMARY</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">النص الكامل المعتمد لدراسة سوق العمل</p>
      </div>
    </div>
  </header>
  <div style="padding:0 42px;margin-top:12px;overflow:visible;">
    {body_html}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">ملخص دراسة سوق العمل</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_market_sources_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render one readable page of the source register as two table columns."""
    source = source if isinstance(source, dict) else {}
    market = _market_state(source)
    page_rows, row_offset = _market_rows_for_slide(
        slide, 'market_study_data.sources', _market_source_rows(market)
    )
    columns = _market_source_chunks(market, page_rows)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'مصادر دراسة السوق'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))

    def render_column(column_rows, column_index):
        # The deck shows the source and its link. The data date, the access
        # date, the reliability rating and the operator's note are internal
        # working fields — they stay on the platform screen, where the client
        # reads them while approving the study.
        header = (
            '<div style="display:grid;grid-template-columns:1.25fr 2fr;'
            f'gap:0;background:{primary};color:#fff;font-size:9px;font-weight:800;text-align:center;line-height:1.2;">'
            '<div style="padding:7px 5px;">المصدر</div><div style="padding:7px 5px;">الرابط</div></div>'
        )
        start_number = row_offset + 1 + sum(len(item) for item in columns[:column_index])
        end_number = start_number + len(column_rows) - 1
        range_title = f'مصادر {start_number} - {end_number}' if column_rows else 'مصادر'
        rows_html = []
        for row_index, row in enumerate(column_rows):
            name, url = list(row)[:2] if row else ('', '')
            bg = '#f8fafc' if row_index % 2 else '#ffffff'
            rows_html.append(
                f'<div style="display:grid;grid-template-columns:1.25fr 2fr;gap:0;'
                f'background:{bg};border-bottom:1px solid #e2e8f0;align-items:center;">'
                f'<div style="padding:8px 6px;text-align:center;font-size:9.3px;line-height:1.35;word-break:break-word;">{_market_value_html(name)}</div>'
                f'<div style="padding:8px 6px;text-align:center;font-size:8px;line-height:1.2;">{_source_url_html(url)}</div>'
                '</div>'
            )
        return (
            f'<div style="border:1px solid #dbe4ee;border-radius:8px;overflow:hidden;min-width:0;box-shadow:0 2px 7px rgba(15,23,42,.04);">'
            f'<div style="padding:8px 10px;background:#f8fafc;color:{primary};font-size:10.5px;font-weight:800;">{range_title}</div>'
            f'{header}{"".join(rows_html)}</div>'
        )

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">MARKET SOURCES</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">السجل الكامل للمراجع والروابط الرسمية المستخدمة في الدراسة</p>
      </div>
    </div>
  </header>
  <div data-market-sources="1" style="margin:12px 36px 0;padding:14px 16px 18px;background:#f3f6f8;border:1px solid #dbe4ee;border-top:5px solid {primary};border-radius:12px;box-sizing:border-box;">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:12px;direction:rtl;">
      <div style="font-size:16px;font-weight:800;color:{primary};">سجل المراجع المستخدمة في الدراسة</div>
      <div style="font-size:10.5px;color:#64748b;">روابط وبيانات المصادر كما وردت</div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start;">
      {''.join(render_column(column, index) for index, column in enumerate(columns))}
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">المراجع والمصادر الرسمية لدراسة السوق</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_market_swot_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render SWOT as a readable four-quadrant matrix instead of raw JSON."""
    source = source if isinstance(source, dict) else {}
    swot = _extract_project_swot(source)
    definitions = (
        ('strengths', 'نقاط القوة', '#0f766e', '#ecfdf5'),
        ('weaknesses', 'نقاط الضعف', '#b45309', '#fffbeb'),
        ('opportunities', 'الفرص', '#1d4ed8', '#eff6ff'),
        ('threats', 'التهديدات', '#b91c1c', '#fef2f2'),
    )
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'تحليل SWOT'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))
    quadrants = []
    for key, label, color, background in definitions:
        items = _market_swot_items(swot.get(key))
        item_html = ''.join(
            f'<div style="padding:6px 0;border-bottom:1px solid rgba(15,23,42,0.08);font-size:12.2px;line-height:1.42;color:#334155;">{_market_value_html(item)}</div>'
            for item in items
        ) or '<div style="font-size:12px;color:#64748b;">غير متوفر</div>'
        quadrants.append(
            f'<div style="background:{background};border:1px solid rgba(15,23,42,0.10);border-top:5px solid {color};'
            'border-radius:8px;padding:12px 16px;box-sizing:border-box;min-width:0;overflow:visible;">'
            f'<div style="font-size:16px;font-weight:800;color:{color};margin-bottom:5px;">{label}</div>'
            f'{item_html}</div>'
        )
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">SWOT ANALYSIS</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">مصفوفة نقاط القوة والضعف والفرص والتهديدات للمشروع في السوق المحدد</p>
      </div>
    </div>
  </header>
  <div style="padding:0 36px;margin-top:14px;">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;height:526px;align-items:stretch;">
      {''.join(quadrants)}
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">تحليل SWOT للمشروع</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_market_risk_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render approved risks as a clear risk-to-mitigation register."""
    source = source if isinstance(source, dict) else {}
    _risk_source, all_items = _risk_analysis_source(source)
    items, row_offset = _market_rows_for_slide(slide, _risk_source, all_items)
    items = list(items)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'تحليل المخاطر وطرق المعالجة'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))
    dense = len(items) >= 6
    cell_padding = '10px 14px' if dense else '16px 18px'
    body_size = '11.5px' if dense else '13.5px'
    row_html = []
    for index, item in enumerate(items, row_offset + 1):
        risk = _market_value_html(item.get('risk'))
        mitigation = _market_value_html(item.get('mitigation')) if item.get('mitigation') else 'غير محددة في البيانات المعتمدة'
        background = '#ffffff' if index % 2 else '#f8fafc'
        row_html.append(
            f'<div data-risk-row="{index}" style="display:grid;grid-template-columns:1fr 1.35fr;gap:0;'
            f'background:{background};border-bottom:1px solid #dbe4ee;align-items:stretch;">'
            f'<div style="padding:{cell_padding};border-right:3px solid #d7a4a4;color:#27364a;font-size:{body_size};line-height:1.7;">'
            f'<div style="font-size:10.5px;font-weight:800;color:#b45309;margin-bottom:5px;" dir="ltr">{index:02d}</div>{risk}</div>'
            f'<div style="padding:{cell_padding};border-right:1px solid #e2e8f0;color:#334155;font-size:{body_size};line-height:1.7;">{mitigation}</div>'
            '</div>'
        )
    if not row_html:
        row_html.append(
            '<div style="padding:18px;font-size:12px;color:#64748b;">لا توجد بيانات مخاطر معتمدة لعرضها.</div>'
        )
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">RISK ANALYSIS</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">سجل المخاطر المرتبطة بالمشروع وطرق معالجتها من البيانات المعتمدة</p>
      </div>
    </div>
  </header>
  <div data-risk-register="1" style="padding:0 42px;margin-top:16px;">
    <div style="border-top:4px solid {primary};border-bottom:1px solid #dbe4ee;overflow:hidden;">
      <div style="display:grid;grid-template-columns:1fr 1.35fr;background:{primary};color:#ffffff;font-size:12px;font-weight:800;line-height:1.25;">
        <div style="padding:10px 14px;border-right:1px solid rgba(255,255,255,.35);">المخاطر</div>
        <div style="padding:10px 14px;">طريقة المعالجة</div>
      </div>
      {''.join(row_html)}
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">تحليل المخاطر وطرق المعالجة</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''
