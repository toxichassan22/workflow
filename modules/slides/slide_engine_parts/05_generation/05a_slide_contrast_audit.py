# Slide text contrast inspection and repair.

class _SlideContrastAudit(HTMLParser):
    _VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    _MEDIA_TAGS = {'img', 'video', 'canvas', 'svg', 'picture'}

    def __init__(self, rules=None, html=''):
        super().__init__(convert_charrefs=True)
        self.rules = rules or []
        self.stack = []
        self.issues = []
        self._line_offsets = [0]
        for match in re.finditer('\n', str(html or '')):
            self._line_offsets.append(match.end())

    def _tag_span(self):
        """Absolute (start, end) offsets of the current opening tag."""
        line, column = self.getpos()
        if line < 1 or line > len(self._line_offsets):
            return (0, 0)
        start = self._line_offsets[line - 1] + column
        return (start, start + len(self.get_starttag_text() or ''))

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1] if self.stack else None
        foreground = parent['fg'] if parent else '#000000'
        background = parent['bg'] if parent else '#ffffff'
        attributes = dict(attrs)
        element = (
            tag.lower(),
            frozenset(str(attributes.get('class') or '').split()),
            str(attributes.get('id') or ''),
        )
        ancestors = [frame['element'] for frame in self.stack]
        styles = {}
        for compounds, properties in self.rules:
            if _selector_matches(compounds, element, ancestors):
                styles.update(properties)
        styles.update(_inline_style_properties(attributes.get('style')))
        if 'color' in styles:
            foreground = _css_solid_color(styles['color'])
        background_value = styles.get('background-color') or styles.get('background')
        if background_value and background_value.lower().strip() != 'transparent':
            background = _css_solid_color(background_value)
        if element[0] in self._MEDIA_TAGS and self.stack:
            self.stack[-1]['contains_media'] = True
        if tag.lower() not in self._VOID_TAGS:
            self.stack.append({
                'element': element,
                'fg': foreground,
                'bg': background,
                'positioned': str(styles.get('position') or '').strip().lower() in ('absolute', 'fixed'),
                'contains_media': False,
                'span': self._tag_span(),
            })

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        lowered = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]['element'][0] == lowered:
                popped = self.stack[index:]
                del self.stack[index:]
                if self.stack and any(frame['contains_media'] for frame in popped):
                    self.stack[-1]['contains_media'] = True
                break

    def _over_media(self):
        """Whether the current text sits in a positioned layer over an image.

        The nearest absolutely/fixed-positioned ancestor (or self) defines the
        local context; text there is indeterminate when that layer or its parent
        holds an image, so it is neither flagged nor repaired.
        """
        for index in range(len(self.stack) - 1, -1, -1):
            frame = self.stack[index]
            if frame['positioned']:
                parent = self.stack[index - 1] if index else None
                return bool(frame['contains_media'] or (parent and parent['contains_media']))
        return False

    def _on_contrast_issue(self):
        """Hook for subclasses; receives the flagged innermost frame on top of the stack."""

    def handle_data(self, data):
        text = re.sub(r'\s+', ' ', data).strip()
        if not text or not self.stack or self.stack[-1]['element'][0] in ('style', 'script'):
            return
        foreground, background = self.stack[-1]['fg'], self.stack[-1]['bg']
        if not foreground or not background or self._over_media():
            return
        ratio = contrast_ratio(foreground, background)
        if ratio < 4.5:
            self.issues.append((text[:40], foreground, background, ratio))
            self._on_contrast_issue()


def slide_contrast_issues(html):
    html = str(html or '')
    parser = _SlideContrastAudit(rules=_parse_slide_style_rules(html), html=html)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return []
    return parser.issues


class _SlideContrastRepair(_SlideContrastAudit):
    """Records opening-tag spans for elements whose effective text is unreadable."""

    def __init__(self, html):
        super().__init__(rules=_parse_slide_style_rules(html), html=html)
        self.repairs = {}

    def _on_contrast_issue(self):
        frame = self.stack[-1]
        start, end = frame['span']
        if end <= start or start in self.repairs:
            return
        color = readable_text_color('#1e293b', frame['bg'], ('#0f172a', '#334155'))
        self.repairs[start] = (start, end, color)


def _repair_slide_text_contrast(html):
    """Patch elements whose effective text color fails 4.5:1 against the surface below.

    Effective color accounts for inherited inline styles and the simple
    <style>-block selectors a model emits, so a rule like ``td{color:#fff}`` on
    the white content canvas is repaired exactly like an inline declaration.
    Text over images or gradients is left alone — the surface is indeterminate
    there. Each patched element receives ``color:...!important`` so the fix wins
    over the offending rule.
    """
    html = str(html or '')
    if not html:
        return html
    parser = _SlideContrastRepair(html)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return html
    for start in sorted(parser.repairs, reverse=True):
        start, end, color = parser.repairs[start]
        tag = html[start:end]
        if not tag.startswith('<'):
            continue
        patched = _set_tag_style(tag, ('color',), f'color:{color}!important;')
        html = html[:start] + patched + html[end:]
    return html


def _required_slide_texts(slide, project_data):
    content_sources = (slide or {}).get('content_sources') if isinstance(slide, dict) else None
    if isinstance(content_sources, list) and content_sources:
        required = []
        for content_source in content_sources:
            item = dict(slide)
            item.pop('content_sources', None)
            item['content_source'] = content_source
            required.extend(_required_slide_texts(item, project_data))
        return list(dict.fromkeys(required))
    source = str((slide or {}).get('content_source') or '')
    chart_type = canonicalize_chart_type((slide or {}).get('chart_type'))
    project_data = project_data if isinstance(project_data, dict) else {}
    model = _parse_financial_dict(project_data.get('financial_study_model'))
    chart_source = _financial_chart_source(slide, model)
    if chart_type == 'combo':
        c_data = _extract_combo_chart_data(chart_source, model, project_data)
        items = c_data.get('items') or []
        return [str(it.get('year') or '') for it in items if str(it.get('year') or '').strip()]
    if chart_type == 'waterfall':
        w_data = _extract_waterfall_chart_data(chart_source, model, project_data)
        items = w_data.get('items') or []
        res = [str(it.get('name') or '') for it in items if str(it.get('name') or '').strip()]
        if w_data.get('total', {}).get('name'):
            res.append(str(w_data['total']['name']))
        return res
    if chart_type == 'heatmap':
        h_data = _extract_heatmap_chart_data(chart_source, model, project_data)
        matrix = h_data.get('matrix') or []
        return [str(r.get('metric') or '') for r in matrix if str(r.get('metric') or '').strip()]
    if (slide or {}).get('type') == 'map_landmarks' or source == 'nearby_landmarks':
        rows = _nearby_landmark_table_rows(project_data)
        if rows:
            return list(dict.fromkeys(
                str(value).strip()
                for row in rows
                for value in row
                if str(value or '').strip()
            ))
        if isinstance(project_data.get('nearby_landmarks_data'), list):
            # An explicit structured table is authoritative — empty means the map
            # carries no landmarks either, so nothing is required on the slide.
            return []
        value = str(project_data.get('nearby_landmarks') or '').strip()
        return [item.strip() for item in re.split(r'[\n|]', value) if item.strip()]
    if str(source or '').startswith('site_analysis'):
        value = str(project_data.get('site_analysis') or '').strip()
        paragraphs = [p.strip() for p in re.split(r'\r?\n\s*\r?\n', value) if p.strip()]
        if not paragraphs:
            paragraphs = [p.strip() for p in value.splitlines() if p.strip()] or [value]
        if ':' in str(source):
            parts = str(source).split(':')
            if len(parts) >= 3:
                start = int(parts[1]) if parts[1].isdigit() else 0
                end = int(parts[2]) if parts[2].isdigit() else len(paragraphs)
                paragraphs = paragraphs[start:end]
        return [p for p in paragraphs if len(p) > 15]
    def _req_row_range():
        start = (slide or {}).get('market_row_start')
        end = (slide or {}).get('market_row_end')
        if start is None or end is None:
            return None
        return max(int(start), 0), max(int(end), 0)

    opp_match = re.fullmatch(r'executive_content\.opportunity(?::(\d+):(\d+))?', str(source or ''))
    if opp_match:
        executive = _decode_json_fact(project_data.get('executive_content'))
        value = str(executive.get('opportunity') or '').strip() if isinstance(executive, dict) else ''
        explicit = _req_row_range()
        if not value:
            return []
        chunks = _exec_text_chunks(value)
        if explicit is not None or opp_match.group(1) is not None:
            start, end = explicit or (int(opp_match.group(1)), int(opp_match.group(2)))
            return chunks[start:end]
        pages = _budget_row_pages([('', chunk) for chunk in chunks])
        return [chunk for _, chunk in (pages[0][1] if pages else [('', value)])]
    feat_match = re.fullmatch(r'executive_content\.features(?::(\d+):(\d+))?', str(source or ''))
    if feat_match:
        items = _executive_feature_items(project_data)
        explicit = _req_row_range()
        if explicit is not None or feat_match.group(1) is not None:
            start, end = explicit or (int(feat_match.group(1)), int(feat_match.group(2)))
            items = items[start:end]
        else:
            ranges = _balanced_row_ranges(len(items), _executive_feature_page_size(items))
            if ranges:
                items = items[ranges[0][0]:ranges[0][1]]
        return items
    summary_match = re.fullmatch(r'executive_content\.summary(?::(\d+):(\d+))?', str(source or ''))
    if summary_match:
        explicit = _req_row_range()
        if explicit is not None or summary_match.group(1) is not None:
            sections = _executive_summary_sections(project_data)
            start, end = explicit or (int(summary_match.group(1)), int(summary_match.group(2)))
            return [f'{label}\n{text}' if label else text for label, text in sections[start:end]]
        pages = _executive_summary_pages(project_data)
        first = pages[0][1] if pages else _executive_summary_sections(project_data)
        return [f'{label}\n{text}' if label else text for label, text in first]
    if source in {
        'executive_content.risks', 'market_study_data.risk_analysis',
        'market_study_data.risk_register', 'market_study_data.risks',
        'market_study_data.summary.risks',
    }:
        risk_source, risk_items = _risk_analysis_source(project_data)
        return [
            str(value).strip()
            for item in risk_items
            for value in (item.get('risk'), item.get('mitigation'))
            if str(value or '').strip()
        ] if source == risk_source else []
    if source == 'market_study_data.swot':
        market = _decode_json_fact(project_data.get('market_study_data'))
        swot = market.get('swot') if isinstance(market, dict) and isinstance(market.get('swot'), dict) else {}
        return [str(value).strip() for value in swot.values() if str(value or '').strip()]
    if source == 'market_study_data.scope':
        market = _market_state(project_data)
        return [str(value).strip() for row in _market_scope_rows(market, resolve_offer_lang(project_data)) for value in row if str(value or '').strip()]
    summary_match = re.fullmatch(r'market_study_data\.summary(?::(\d+):(\d+))?', source)
    if summary_match:
        market = _market_state(project_data)
        rows, _row_offset = _market_rows_for_slide(
            slide, 'market_study_data.summary', _market_summary_rows(market)
        )
        return [str(value).strip() for row in rows for value in row if str(value or '').strip()]
    one_block_match = re.fullmatch(r'market_study_data\.one_block_summary(?::(\d+):(\d+))?', source)
    if one_block_match:
        market = _market_state(project_data)
        value = _market_one_block_paragraph(market)
        if one_block_match.group(1) is not None:
            value = value[int(one_block_match.group(1)):int(one_block_match.group(2))]
        return [value] if value else []
    sources_match = re.fullmatch(r'market_study_data\.sources(?::(\d+):(\d+))?', source)
    if sources_match:
        market = _market_state(project_data)
        rows = _market_source_rows(market)
        if sources_match.group(1) is not None:
            rows = rows[int(sources_match.group(1)):int(sources_match.group(2))]
        return [str(value).strip() for row in rows for value in row if str(value or '').strip()]
    if source == 'market_study_data.competitors' or 'competitors' in source:
        market = _decode_json_fact(project_data.get('market_study_data')) if isinstance(project_data.get('market_study_data'), (str, dict)) else {}
        competitors = market.get('competitors') if isinstance(market, dict) else []
        competitors = [c for c in competitors if isinstance(c, dict) and _competitor_name(c)]
        c_start = (slide or {}).get('competitor_start')
        c_end = (slide or {}).get('competitor_end')
        cs = str(source or '')
        if c_start is not None and c_end is not None:
            competitors = competitors[c_start:c_end]
        elif ':' in cs:
            parts = cs.split(':')
            if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
                competitors = competitors[int(parts[-2]):int(parts[-1])]
        items = _extract_competitor_chart_data(competitors, project_data)
        return [str(it.get('name') or '').strip() for it in items if str(it.get('name') or '').strip()]
    if source == 'contact_closing':
        values = [str(project_data.get(key) or '').strip() for key in (
            'contact_name', 'contact_position', 'contact_phone', 'contact_email',
            'contact_website', 'contact_address', 'contact_social_media')]
        entered = [value for value in values if value]
        return entered or [str(project_data.get('project_name') or 'المشروع').strip(), 'شكر']

    def row_values(row):
        values = []
        if isinstance(row, dict):
            for k, v in row.items():
                if str(k).strip() in ('ترتيب / حذف', 'ترتيب', 'حذف', 'إجراءات', 'actions', 'id', 'row_id'):
                    continue
                if str(v).strip() in ('أعلىأسفلحذف', 'أعلى', 'أسفل', 'حذف', '—', '-', '0', '0.0'):
                    continue
                values.append(v)
        elif isinstance(row, (list, tuple)):
            for v in row:
                if str(v).strip() in ('أعلىأسفلحذف', 'أعلى', 'أسفل', 'حذف', '—', '-', '0', '0.0'):
                    continue
                values.append(v)
        return [str(value).strip() for value in values if str(value or '').strip()]

    def row_anchor(row):
        return next(iter(row_values(row)), '')

    match = re.fullmatch(r'project_components:(\d+):(\d+)', source)
    if match:
        start, end = map(int, match.groups())
        return [str(row.get('اسم المكون') or '').strip()
                for row in _project_component_rows(project_data)[start:end]
                if str(row.get('اسم المكون') or '').strip()]
    match = re.fullmatch(r'financial_report:(\d+):(\d+):(\d+)(?::(\d+):(\d+))?', source)
    if match:
        part_index, start, end = map(int, match.groups()[:3])
        column_start = int(match.group(4)) if match.group(4) is not None else None
        column_end = int(match.group(5)) if match.group(5) is not None else None
        report = model.get('report') if isinstance(model.get('report'), dict) else {}
        parts = report.get('parts') if isinstance(report.get('parts'), list) else []
        if part_index >= len(parts) or not isinstance(parts[part_index], dict):
            return []
        part = _financial_report_part_slice(parts[part_index], start, end, column_start, column_end)
        required = [str(header).strip() for header in (part.get('headers') or []) if str(header or '').strip()]
        required.extend(value for row in (part.get('rows') or []) for value in row_values(row))
        return list(dict.fromkeys(required))
    match = re.fullmatch(r'financial_table:([^:]+):(\d+):(\d+)', source)
    if match:
        table_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
        return list(dict.fromkeys(value for row in rows[start:end] for value in row_values(row)))
    match = re.fullmatch(r'financial_summary:(costs|returns):(\d+):(\d+)', source)
    if match:
        group_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        group_name = 'التكاليف والاستثمار' if group_key == 'costs' else 'مؤشرات العائد والاسترداد'
        rows = _financial_summary_from_report(model).get(group_name, [])[start:end]
        return list(dict.fromkeys(value for row in rows for value in row_values(row)))
    if source == 'financial_indicators':
        summary = _financial_summary_from_report(model)
        return list(dict.fromkeys(value for rows in summary.values() for row in rows for value in row_values(row)))
    return []


def _missing_required_slide_texts(html, slide, project_data):
    visible = html_lib.unescape(re.sub(r'<[^>]+>', ' ', str(html or '')))

    def normalized(value):
        value = str(value or '').replace(',', '').replace('٬', '').replace('\u00a0', ' ')
        return re.sub(r'\s+', ' ', value).strip()

    compact = normalized(visible)
    required = _required_slide_texts(slide, project_data)
    if (slide or {}).get('chart_type'):
        required = [text for text in required if not re.match(r'^-?\d+(?:\.\d+)?$', normalized(text))]
    return [text for text in required
            if normalized(text) and normalized(text) not in compact]


def _financial_chart_source(slide, model):
    """Resolve the exact report/table slice that feeds a financial chart."""
    source = str((slide or {}).get('content_source') or '')
    report = model.get('report') if isinstance(model.get('report'), dict) else {}
    parts = report.get('parts') if isinstance(report.get('parts'), list) else []
    match = re.fullmatch(r'financial_report:(\d+):(\d+):(\d+)(?::(\d+):(\d+))?', source)
    if match:
        part_index, start, end = map(int, match.groups()[:3])
        column_start = int(match.group(4)) if match.group(4) is not None else None
        column_end = int(match.group(5)) if match.group(5) is not None else None
        if part_index < len(parts) and isinstance(parts[part_index], dict):
            return _financial_report_part_slice(parts[part_index], start, end, column_start, column_end)
    match = re.fullmatch(r'financial_chart:[^:]+:(\d+)', source)
    if match:
        part_index = int(match.group(1))
        if part_index < len(parts) and isinstance(parts[part_index], dict):
            return parts[part_index]
    match = re.fullmatch(r'financial_table:([^:]+):(\d+):(\d+)', source)
    if match:
        table_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
        if not rows:
            aliases = {
                'cashflowTable': ('cashflow',),
                'sensitivityTable': ('sensitivity',),
                'sensitivityAssumptionsTable': ('sensitivity',),
            }
            rows = next((tables.get(alias) for alias in aliases.get(table_key, ())
                         if isinstance(tables.get(alias), list)), [])
        return {'rows': rows[start:end]}
    return None
