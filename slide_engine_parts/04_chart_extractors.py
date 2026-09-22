

def _slide_source_data_note(slide, project_data, offer_lang=None):
    lang = resolve_offer_lang(project_data if isinstance(project_data, dict) else None, offer_lang)
    content_sources = (slide or {}).get('content_sources') if isinstance(slide, dict) else None
    if isinstance(content_sources, list) and content_sources:
        fin_sources = [str(source) for source in content_sources
                       if re.fullmatch(r'financial_report:\d+:\d+:\d+(?::\d+:\d+)?', str(source))]
        if fin_sources and len(fin_sources) == len([s for s in content_sources if str(s or '').strip()]):
            model = _parse_financial_dict((project_data if isinstance(project_data, dict) else {})
                                          .get('financial_study_model'))
            stacked_note = _stacked_financial_report_note(fin_sources, model)
            if stacked_note:
                return stacked_note
        notes = []
        for content_source in content_sources:
            item = dict(slide)
            item.pop('content_sources', None)
            item['content_source'] = content_source
            note = _slide_source_data_note(item, project_data, lang)
            if note:
                notes.append(note)
        return '\n\n'.join(notes)
    source = str((slide or {}).get('content_source') or '')
    project_data = project_data if isinstance(project_data, dict) else {}
    model = _parse_financial_dict(project_data.get('financial_study_model'))
    c_type = canonicalize_chart_type((slide or {}).get('chart_type'))
    if (slide or {}).get('type') == 'map_access' or source in ('main_roads', 'access_roads'):
        roads_data = project_data.get('access_roads_data')
        if isinstance(roads_data, list) and roads_data:
            return 'جدول شبكة الطرق والمحاور الرئيسية ومداخل المشروع كما هو دون حذف أو اختلاق للقيم:\n' + json.dumps(roads_data, ensure_ascii=False, indent=2)
        roads_text = str(project_data.get('main_roads') or '').strip()
        return 'شبكة الطرق ومداخل المشروع كما هي دون حذف:\n' + roads_text if roads_text else ''
    if (slide or {}).get('type') == 'map_catchment' or source in ('catchment_areas', 'city_landmarks'):
        city_data = project_data.get('city_landmarks_data')
        if isinstance(city_data, list) and city_data:
            return 'جدول نطاق التأثير الجغرافي ومعالم المدينة وأوقات القيادة كما هو دون حذف أو اختلاق:\n' + json.dumps(city_data, ensure_ascii=False, indent=2)
        catchment_text = str(project_data.get('catchment_areas') or project_data.get('city_landmarks') or '').strip()
        return 'نطاق التأثير ومعالم المدينة كما هي دون حذف:\n' + catchment_text if catchment_text else ''
    if (slide or {}).get('type') == 'map_landmarks' or source in ('nearby_landmarks', 'landmarks_matrix'):
        nearby_data = project_data.get('nearby_landmarks_data') or project_data.get('landmarks_matrix')
        if isinstance(nearby_data, list) and nearby_data:
            return 'جدول المعالم والمسافات وأوقات القيادة كما هو دون حذف:\n' + json.dumps(nearby_data, ensure_ascii=False, indent=2)
        value = str(project_data.get('nearby_landmarks') or '').strip()
        return 'المعالم والمسافات وأوقات القيادة كما هي دون حذف:\n' + value if value else ''
    if source in {
        'executive_content.risks', 'market_study_data.risk_analysis',
        'market_study_data.risk_register', 'market_study_data.risks',
        'market_study_data.summary.risks',
    }:
        risk_source, risk_items = _risk_analysis_source(project_data)
        if source == risk_source and risk_items:
            return 'سجل المخاطر وطرق المعالجة المعتمد كما أُدخل، دون إضافة أو تكرار:\n' + json.dumps(risk_items, ensure_ascii=False, indent=2)
        return ''
    if source == 'market_study_data.swot':
        market = _decode_json_fact(project_data.get('market_study_data'))
        swot = market.get('swot') if isinstance(market, dict) and isinstance(market.get('swot'), dict) else {}
        return 'تحليل SWOT الأصلي الوحيد، انقل المحاور الأربعة دون إضافة أو تكرار:\n' + json.dumps(swot, ensure_ascii=False, indent=2) if swot else ''
    if source == 'market_study_data.scope':
        market = _market_state(project_data)
        rows = _market_scope_rows(market)
        return 'نطاق الدراسة وفترة البيانات كما أُدخلتا في القسم:\n' + json.dumps(rows, ensure_ascii=False, indent=2) if rows else ''
    summary_match = re.fullmatch(r'market_study_data\.summary(?::(\d+):(\d+))?', source)
    if summary_match:
        market = _market_state(project_data)
        rows, _row_offset = _market_rows_for_slide(
            slide, 'market_study_data.summary', _market_summary_rows(market)
        )
        return 'الملخص التنفيذي لسوق المشروع، بكل محاوره وقيمه كما أُدخلت:\n' + json.dumps(rows, ensure_ascii=False, indent=2) if rows else ''
    one_block_match = re.fullmatch(r'market_study_data\.one_block_summary(?::(\d+):(\d+))?', source)
    if one_block_match:
        market = _market_state(project_data)
        value = _market_one_block_paragraph(market)
        if one_block_match.group(1) is not None:
            value = value[int(one_block_match.group(1)):int(one_block_match.group(2))]
        return 'ملخص دراسة السوق المعتمد كما أُدخل:\n' + value if value else ''
    sources_match = re.fullmatch(r'market_study_data\.sources(?::(\d+):(\d+))?', source)
    if sources_match:
        market = _market_state(project_data)
        rows = _market_source_rows(market)
        if sources_match.group(1) is not None:
            rows = rows[int(sources_match.group(1)):int(sources_match.group(2))]
        return 'مصادر دراسة السوق كاملة كما أُدخلت:\n' + json.dumps(rows, ensure_ascii=False, indent=2) if rows else ''
    if source == 'market_study_data.competitors' or (slide or {}).get('source_table') == 'competitors':
        market = _decode_json_fact(project_data.get('market_study_data'))
        market = market if isinstance(market, dict) else {}
        competitors = market.get('competitors') if isinstance(market.get('competitors'), list) else []
        items = []
        for index, comp in enumerate(competitors, 1):
            if not isinstance(comp, dict):
                continue
            name = _competitor_name(comp)
            if not name:
                continue
            row = {key: value for key, value in comp.items()
                   if key not in ('id', 'field_sources', 'row_source', 'logo_file_id', 'logo_path',
                                  'logo_url', 'logo_source_url', 'conflict_warnings',
                                  'logo_import_warning', 'price_cache', 'area_cache')
                   and value not in (None, '', [])}
            logo_token = _competitor_logo_token(comp, index)
            if logo_token:
                row['شعار المنافس'] = logo_token
            if row:
                items.append(row)
        chart_items = _extract_competitor_chart_data(competitors, project_data)
        chart_block = (
            '\n\nبيانات مخطط الأعمدة الأفقية لمقارنة المنافسين (horizontal_bar_chart_data) بنسب العرض المحسوبة جاهزة:\n'
            + json.dumps(chart_items, ensure_ascii=False, indent=2)
        ) if chart_items else ''
        scope = {key: market.get(key) for key in (
            'competitor_radius', 'competitor_radius_custom_km', 'data_period',
            'data_period_from', 'data_period_to') if market.get(key) not in (None, '', [])}
        scope_block = (
            '\nنطاق وفترة البيانات كما أُدخلتا في القسم:\n' +
            json.dumps(scope, ensure_ascii=False, indent=2)
        ) if scope else ''
        source_rows = market.get('sources') if isinstance(market.get('sources'), list) else []
        sources_block = (
            '\nمصادر المنافسين ودراسة السوق كما هي:\n' +
            json.dumps(source_rows, ensure_ascii=False, indent=2)
        ) if source_rows else ''
        return (
            'جدول المنافسين الكامل كما هو في قسم دراسة السوق (horizontal_bar):\n'
            + json.dumps(items, ensure_ascii=False, indent=2)
            + chart_block
            + scope_block
            + sources_block
            + '\n\nقواعد رسم مقارنة المنافسين المعتمدة:\n'
            '- ترتيب تنازلي حسب السعر (من الأعلى إلى الأقل).\n'
            '- مقارنة الأسعار لنفس وحدة القياس ونوع السعر (سعر المتر بيع أو تأجير، أو إجمالي سعر الوحدة).\n'
            '- إبراز مشروعنا بلون الهوية المعتمد إذا كان له سعر مقترح، لتمييزه فوراً عن المنافسين.\n'
            '- استبعاد أي منافس لا يملك قيمة رقمية موثقة (لا تدرج منافس بسعر صفر أو مجهول).\n'
            '- نطاق السعر يمثل كشريط من الأدنى للأعلى (وليس متوسطاً افتراضياً).\n'
            '- تنبيه المبرمج: يمنع منعاً باتاً اختراع قيم افتراضية أو متوسطات تقديرية.'
        )
    if str(source or '').startswith('site_analysis'):
        value = str(project_data.get('site_analysis') or '').strip()
        if not value:
            return ''
        paragraphs = [p.strip() for p in re.split(r'\r?\n\s*\r?\n', value) if p.strip()]
        if not paragraphs:
            paragraphs = [p.strip() for p in value.splitlines() if p.strip()] or [value]
        if ':' in str(source):
            parts = str(source).split(':')
            if len(parts) >= 3:
                start = int(parts[1]) if parts[1].isdigit() else 0
                end = int(parts[2]) if parts[2].isdigit() else len(paragraphs)
                value = '\n\n'.join(paragraphs[start:end])
        return 'ملخص الموقع المعتمد دون إضافة أو تكرار:\n' + value if value else ''
    def _explicit_row_range():
        start = (slide or {}).get('market_row_start')
        end = (slide or {}).get('market_row_end')
        if start is None or end is None:
            return None
        return max(int(start), 0), max(int(end), 0)

    summary_match = re.fullmatch(r'executive_content\.summary(?::(\d+):(\d+))?', str(source or ''))
    if summary_match:
        explicit = _explicit_row_range()
        if explicit is not None or summary_match.group(1) is not None:
            sections = _executive_summary_sections(project_data)
            start, end = explicit or (int(summary_match.group(1)), int(summary_match.group(2)))
            value = '\n\n'.join(
                (f'{label}\n{text}' if label else text)
                for label, text in sections[start:end]
            ).strip()
        else:
            sections = _executive_summary_sections(project_data)
            pages = _executive_summary_pages(project_data)
            first = pages[0][1] if pages else sections
            value = '\n\n'.join(
                (f'{label}\n{text}' if label else text)
                for label, text in first
            ).strip()
        return 'الملخص التنفيذي المعتمد دون إضافة أو تكرار:\n' + value if value else ''
    opp_match = re.fullmatch(r'executive_content\.opportunity(?::(\d+):(\d+))?', str(source or ''))
    if opp_match:
        executive = _decode_json_fact(project_data.get('executive_content'))
        value = str(executive.get('opportunity') or '').strip() if isinstance(executive, dict) else ''
        explicit = _explicit_row_range()
        if value:
            chunks = _exec_text_chunks(value)
            if explicit is not None or opp_match.group(1) is not None:
                start, end = explicit or (int(opp_match.group(1)), int(opp_match.group(2)))
                value = '\n\n'.join(chunks[start:end])
            else:
                pages = _budget_row_pages([('', chunk) for chunk in chunks])
                if pages:
                    value = '\n\n'.join(chunk for _, chunk in pages[0][1])
        return 'الفرصة الاستثمارية المعتمدة دون إضافة أو تكرار:\n' + value if value else ''
    feat_match = re.fullmatch(r'executive_content\.features(?::(\d+):(\d+))?', str(source or ''))
    if feat_match:
        items = _executive_feature_items(project_data)
        explicit = _explicit_row_range()
        if explicit is not None or feat_match.group(1) is not None:
            start, end = explicit or (int(feat_match.group(1)), int(feat_match.group(2)))
            items = items[start:end]
        else:
            ranges = _balanced_row_ranges(len(items), _executive_feature_page_size(items))
            if ranges:
                items = items[ranges[0][0]:ranges[0][1]]
        value = '\n'.join(f'- {it}' for it in items)
        return 'المميزات وفرص الاستثمار المعتمدة دون إضافة أو تكرار:\n' + value if value else ''
    if source == 'contact_closing':
        contact = _contact_facts(project_data)
        if contact:
            if lang == OFFER_LANG_ENGLISH:
                return contact + '\nShow only the listed fields, with the project hero image and the company and project logos.'
            return contact + '\nاعرض جميع الحقول المذكورة فقط، مع صورة المشروع الرئيسية وشعاري الشركة والمشروع.'
        project_name = str(project_data.get('project_name') or project_data.get('projectName') or ('Project' if lang == OFFER_LANG_ENGLISH else 'المشروع')).strip()
        if lang == OFFER_LANG_ENGLISH:
            return f'No contact data entered. Show only a brief thanks and the project name: {project_name}.'
        return f'لا توجد بيانات تواصل مدخلة. اعرض شكرًا موجزًا واسم المشروع فقط: {project_name}.'
    match = re.fullmatch(r'financial_report:(\d+):(\d+):(\d+)(?::(\d+):(\d+))?', source)
    if match:
        part_index, start, end = map(int, match.groups()[:3])
        column_start = int(match.group(4)) if match.group(4) is not None else None
        column_end = int(match.group(5)) if match.group(5) is not None else None
        report = model.get('report') if isinstance(model.get('report'), dict) else {}
        parts = report.get('parts') if isinstance(report.get('parts'), list) else []
        if part_index < len(parts) and isinstance(parts[part_index], dict):
            part = _financial_report_part_slice(parts[part_index], start, end, column_start, column_end)
            extra = ''
            if c_type == 'waterfall':
                c_data = _extract_waterfall_chart_data(part, model, project_data)
                extra = '\n\nبيانات المخطط الشلالي (waterfall_chart_data) لتكوين إجمالي تكلفة المشروع (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
            elif c_type == 'combo':
                c_data = _extract_combo_chart_data(part, model, project_data)
                extra = '\n\nبيانات مخطط التدفقات النقدية (combo_chart_data) السنوية والتراكمية (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
            elif c_type == 'heatmap':
                c_data = _extract_heatmap_chart_data(part, model, project_data)
                extra = '\n\nبيانات مصفوفة الخريطة الحرارية (heatmap_chart_data) لمقارنة السيناريوهات والقطبية:\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
            return 'المحتوى الحرفي المطلوب في هذه الشريحة فقط:\n' + json.dumps(part, ensure_ascii=False, indent=2) + extra
    match = re.fullmatch(r'financial_chart:([^:]+):(\d+)', source)
    if match:
        chart_cand, part_index = match.group(1), int(match.group(2))
        report = model.get('report') if isinstance(model.get('report'), dict) else {}
        parts = report.get('parts') if isinstance(report.get('parts'), list) else []
        part = parts[part_index] if part_index < len(parts) and isinstance(parts[part_index], dict) else {}
        extra = ''
        if c_type == 'waterfall':
            c_data = _extract_waterfall_chart_data(part, model, project_data)
            extra = '\n\nبيانات المخطط الشلالي (waterfall_chart_data) لتكوين إجمالي تكلفة المشروع (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        elif c_type == 'combo':
            c_data = _extract_combo_chart_data(part, model, project_data)
            extra = '\n\nبيانات مخطط التدفقات النقدية (combo_chart_data) السنوية والتراكمية (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        elif c_type == 'heatmap':
            c_data = _extract_heatmap_chart_data(part, model, project_data)
            extra = '\n\nبيانات مصفوفة الخريطة الحرارية (heatmap_chart_data) لمقارنة السيناريوهات والقطبية:\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        return 'بيانات الرسم البياني المعتمد:\n' + extra
    match = re.fullmatch(r'financial_table:([^:]+):(\d+):(\d+)', source)
    if match:
        table_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
        extra = ''
        if c_type == 'waterfall' or (not c_type and table_key == 'costTable'):
            c_data = _extract_waterfall_chart_data({'rows': rows[start:end]}, model, project_data)
            extra = '\n\nبيانات المخطط الشلالي (waterfall_chart_data) لتكوين إجمالي تكلفة المشروع (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        elif c_type == 'combo' or (not c_type and table_key == 'cashflowTable'):
            c_data = _extract_combo_chart_data({'rows': rows[start:end]}, model, project_data)
            extra = '\n\nبيانات مخطط التدفقات النقدية (combo_chart_data) السنوية والتراكمية (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        elif c_type == 'heatmap' or (not c_type and table_key == 'sensitivityTable'):
            c_data = _extract_heatmap_chart_data({'rows': rows[start:end]}, model, project_data)
            extra = '\n\nبيانات مصفوفة الخريطة الحرارية (heatmap_chart_data) لمقارنة السيناريوهات والقطبية:\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        clean_rows = []
        for r in rows[start:end]:
            if isinstance(r, dict):
                clean_rows.append({k: v for k, v in r.items() if str(k).strip() not in ('ترتيب / حذف', 'ترتيب', 'حذف', 'إجراءات', 'actions') and str(v).strip() != 'أعلىأسفلحذف'})
            else:
                clean_rows.append(r)
        return f'جدول هذه الشريحة فقط ({table_key}):\n' + json.dumps(clean_rows, ensure_ascii=False, indent=2) + extra
    match = re.fullmatch(r'financial_summary:(costs|returns):(\d+):(\d+)', source)
    if match:
        group_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        group_name = 'التكاليف والاستثمار' if group_key == 'costs' else 'مؤشرات العائد والاسترداد'
        rows = _financial_summary_from_report(model).get(group_name, [])[start:end]
        extra = ''
        if c_type == 'waterfall' and group_key == 'costs':
            c_data = _extract_waterfall_chart_data({'rows': rows}, model, project_data)
            extra = '\n\nبيانات المخطط الشلالي (waterfall_chart_data) لتكوين إجمالي تكلفة الاستثمار (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        return f'{group_name} من نفس تقرير PDF دون إعادة حساب:\n' + json.dumps(rows, ensure_ascii=False, indent=2) + extra
    if source == 'financial_indicators':
        report_summary = _financial_summary_from_report(model)
        if report_summary:
            return (
                'الملخص المالي من نفس بيانات تقرير PDF — أنشئ جدول التكاليف والاستثمار وجدول مؤشرات العائد والاسترداد بالقيم والمسميات نفسها دون حذف أو إعادة حساب:\n'
                + json.dumps(report_summary, ensure_ascii=False, indent=2)
            )
        inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
        projection = model.get('projection') if isinstance(model.get('projection'), dict) else {}
        calc = _parse_financial_dict(project_data.get('financial_calc_data'))

        cost_investment_keys = (
            ('projectCost', 'إجمالي تكلفة المشروع'),
            ('projectCostWithFinance', 'التكلفة شاملة التمويل'),
            ('adjustedProjectCost', 'إجمالي تكلفة الاستثمار'),
            ('developerCost', 'أتعاب المطور'),
            ('landValue', 'قيمة الأرض'),
            ('landRent', 'إيجار الأرض السنوي'),
            ('totalCashEquity', 'حقوق الملكية النقدية المطلوبة'),
            ('facilityAmount', 'قيمة التسهيل التمويلي'),
            ('totalFinanceCost', 'إجمالي كلفة التمويل'),
            ('totalFundFees', 'إجمالي أتعاب الصندوق'),
        )
        returns_payback_keys = (
            ('roi', 'معدل العائد على الاستثمار (ROI)'),
            ('projectIrr', 'معدل العائد الداخلي للمشروع (Project IRR)'),
            ('equityIrr', 'معدل العائد الداخلي للملكية (Equity IRR)'),
            ('payback', 'فترة استرداد رأس المال (سنوات)'),
            ('equityPayback', 'فترة استرداد حقوق الملكية (سنوات)'),
            ('totalEquityDistributions', 'إجمالي توزيعات الأرباح'),
            ('saleExitValue', 'صافي التخارج البيعي'),
            ('operatingExitValue', 'صافي التخارج التشغيلي'),
            ('terminal', 'إجمالي قيمة التخارج'),
        )

        def _extract_group(keys):
            res = {}
            for key, label in keys:
                value = projection.get(key)
                if value in (None, '', [], {}) and inputs.get(key) not in (None, '', [], {}):
                    value = inputs.get(key)
                if value in (None, '', [], {}) and calc.get(key) not in (None, '', [], {}):
                    value = calc.get(key)
                if value not in (None, '', [], {}, -1):
                    res[label] = value
            return res

        cost_investment_table = _extract_group(cost_investment_keys)
        returns_payback_table = _extract_group(returns_payback_keys)

        payload = {
            'جدول التكاليف والاستثمار': cost_investment_table,
            'جدول مؤشرات العائد والاسترداد': returns_payback_table,
        }
        return (
            'المؤشرات المالية المطلوبة — نسّقها في جدولين منظمين متجاورين أو متتاليين (جدول التكاليف والاستثمار + جدول مؤشرات العائد والاسترداد) مع إبراز المؤشرات الكبرى بخط عريض 800:\n'
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )
    match = re.fullmatch(r'project_components:(\d+):(\d+)', source)
    if match:
        start, end = map(int, match.groups())
        return 'مكونات هذه الشريحة فقط:\n' + json.dumps(_project_component_rows(project_data)[start:end], ensure_ascii=False, indent=2)
    if source == 'land_boundary_diagram':
        data = _extract_land_boundary_diagram_data(project_data)
        return (
            'بيانات المخطط الاتجاهي لحدود الأرض والواجهات — أنشئ مخططاً اتجاهياً هندسياً راقياً (Directional Boundary Diagram) '
            'يتوسطه صندوق عريض يمثل «أرض المشروع» مع أطوال الأضلاع على حوافه الأربع وملخص الواجهات في وسطه، وتحيط به بطاقات '
            'الاتجاهات الأربعة (شمال، جنوب، شرق، غرب) مبيناً عليها أطوال الأضلاع وعروض الشوارع والواجهات مع تمييز الشوارع بلون التمييز (مثل الذهبي) '
            'وبطاقة بارزة ومميزة لجهة الإطلالة أو الطريق الرئيسي إن وجدت:\n'
            + json.dumps(data, ensure_ascii=False, indent=2)
        )
    if source == 'land_specs':
        data = _extract_land_specs_data(project_data)
        return (
            'بيانات مواصفات الأرض والاشتراطات التنظيمية والبلدية — أنشئ شريحة مواصفات فنية واشتراطات معمارية وتنظيمية راقية، '
            'تتضمن بطاقات واضحة لأرقام الصك والمخطط والقطعة والمساحة الإجمالية، وشبكة بطاقات أنيقة لنسبة البناء، معامل البناء، الارتدادات، '
            'الارتفاعات المسموحة، الاستخدام المعتمد، واشتراطات المواقف، مع إبراز أي ميزات تنظيمية أو ملخص بياني دون أي أيقونات:\n'
            + json.dumps(data, ensure_ascii=False, indent=2)
        )
    if source in ('timeline_table_data', 'timeline'):
        phases = parse_timeline_phases(project_data)
        timeline_meta = {
            'start_date': project_data.get('timeline_start_date') or project_data.get('start_date') or '',
            'duration_years': project_data.get('timeline_duration_years') or project_data.get('project_duration_years') or '',
            'phases': phases,
        }
        return (
            'بيانات الجدول الزمني ومراحل التطوير — أنشئ شريحة جدول زمني متكاملة ومراحل تنفيذ واضحة وأنيقة (Horizontal Timeline / Gantt cards) '
            'تعرض كل مرحلة باسمها، مدتها، تواريخ أو فترات البداية والنهاية، والمهام الرئيسية، وتوزع المراحل زمنياً بشكل جذاب وواضح دون أي أيقونات:\n'
            + json.dumps(timeline_meta, ensure_ascii=False, indent=2)
        )
    return ''


def _extract_land_boundary_diagram_data(project_data):
    """Extract structured data for the directional land boundary diagram."""
    source = project_data if isinstance(project_data, dict) else {}

    facades_count = str(source.get('facades_count') or '').strip()
    facades_directions = str(source.get('facades_directions') or '').strip()

    facades_summary = ''
    if facades_count and facades_directions:
        if facades_count in ('2', 'واجهتان'):
            count_text = 'واجهتان'
        elif facades_count in ('1', 'واجهة'):
            count_text = 'واجهة واحدة'
        elif facades_count.isdigit() and int(facades_count) > 2:
            count_text = f'{facades_count} واجهات'
        else:
            count_text = f'{facades_count} واجهات' if 'واجه' not in facades_count else facades_count
        facades_summary = f'{count_text} ({facades_directions})'
    elif facades_directions:
        facades_summary = f'الواجهات: {facades_directions}'
    elif facades_count:
        facades_summary = f'عدد الواجهات: {facades_count}'

    directions = {
        'north': {'label': 'الشمال', 'length': '', 'description': '', 'is_facade': False, 'setback': ''},
        'south': {'label': 'الجنوب', 'length': '', 'description': '', 'is_facade': False, 'setback': ''},
        'east': {'label': 'الشرق', 'length': '', 'description': '', 'is_facade': False, 'setback': ''},
        'west': {'label': 'الغرب', 'length': '', 'description': '', 'is_facade': False, 'setback': ''},
    }
    dir_aliases = {
        'north': ('north', 'شمال', 'الشمال'),
        'south': ('south', 'جنوب', 'الجنوب'),
        'east': ('east', 'شرق', 'الشرق'),
        'west': ('west', 'غرب', 'الغرب'),
    }

    raw_dt = source.get('directions_table')
    dt_rows = _decode_json_fact(raw_dt) if isinstance(raw_dt, str) else raw_dt
    if isinstance(dt_rows, dict):
        dt_rows = [dict(value, direction=key) if isinstance(value, dict) else {
            'direction': key, 'description': value
        } for key, value in dt_rows.items()]
    if isinstance(dt_rows, list):
        for row in dt_rows:
            if not isinstance(row, dict):
                continue
            dir_key = str(row.get('direction') or row.get('label') or '').strip().lower()
            reg_text = str(row.get('regulation_text') or row.get('text') or row.get('description') or '').strip()
            length_val = str(row.get('boundary_length') or row.get('boundary_length_m') or row.get('length') or '').strip()
            street_val = str(row.get('street_name') or row.get('street') or '').strip()
            neighbour_val = str(row.get('neighbour') or row.get('neighbor') or row.get('adjacent') or '').strip()
            width_val = str(row.get('street_width') or row.get('street_width_m') or row.get('width') or '').strip()
            uses_val = str(row.get('uses') or row.get('use') or '').strip()
            setback_val = str(row.get('setback') or row.get('setbacks') or row.get('artidad') or '').strip()
            for std_key, aliases in dir_aliases.items():
                if dir_key in aliases or any(a in dir_key for a in aliases):
                    if reg_text and not directions[std_key]['description']:
                        directions[std_key]['description'] = reg_text
                    if length_val and not directions[std_key]['length']:
                        directions[std_key]['length'] = length_val if 'م' in length_val else f"{length_val} م"
                    if street_val and not directions[std_key].get('street_name'):
                        directions[std_key]['street_name'] = street_val
                    if neighbour_val and not directions[std_key].get('neighbour'):
                        directions[std_key]['neighbour'] = neighbour_val
                    if width_val and not directions[std_key].get('street_width'):
                        directions[std_key]['street_width'] = width_val if 'م' in width_val else f"{width_val} م"
                    if uses_val and not directions[std_key].get('uses'):
                        directions[std_key]['uses'] = uses_val
                    if setback_val and not directions[std_key].get('setback'):
                        directions[std_key]['setback'] = setback_val if 'م' in setback_val else f"{setback_val} م"
                    break

    land_analysis = _decode_json_fact(source.get('land_documents_analysis_data') or source.get('landDocumentsAnalysisData') or source.get('land_documents_analysis'))
    if isinstance(land_analysis, dict):
        parcels = land_analysis.get('parcels') if isinstance(land_analysis.get('parcels'), list) else []
        parcel_dirs = parcels[0].get('directions') if parcels and isinstance(parcels[0], dict) and isinstance(parcels[0].get('directions'), dict) else {}
        if not parcel_dirs and isinstance(land_analysis.get('directions'), dict):
            parcel_dirs = land_analysis.get('directions')
        for std_key, aliases in dir_aliases.items():
            for alias in aliases:
                if alias in parcel_dirs and isinstance(parcel_dirs[alias], dict):
                    p_info = parcel_dirs[alias]
                    desc = str(p_info.get('regulation_text') or p_info.get('uses') or '').strip()
                    length = p_info.get('boundary_length_m') or p_info.get('length')
                    width = p_info.get('street_width_m') or p_info.get('width')
                    street = str(p_info.get('street_name') or '').strip()
                    neighbour = str(p_info.get('neighbour') or p_info.get('neighbor') or p_info.get('adjacent') or '').strip()
                    setback_p = str(p_info.get('setback') or p_info.get('setbacks') or p_info.get('artidad') or '').strip()
                    if desc and not directions[std_key]['description']:
                        directions[std_key]['description'] = desc
                    if length and not directions[std_key]['length']:
                        directions[std_key]['length'] = f"{length} م"
                    if street and not directions[std_key].get('street_name'):
                        directions[std_key]['street_name'] = street
                    if neighbour and not directions[std_key].get('neighbour'):
                        directions[std_key]['neighbour'] = neighbour
                    if width and not directions[std_key].get('street_width'):
                        directions[std_key]['street_width'] = f"{width} م"
                    if setback_p and not directions[std_key].get('setback'):
                        directions[std_key]['setback'] = setback_p if 'م' in setback_p else f"{setback_p} م"
                    break

    raw_lengths = str(source.get('boundary_lengths') or '').strip()
    if raw_lengths:
        for part in re.split(r'[|,\n،]', raw_lengths):
            part = part.strip()
            if not part:
                continue
            for std_key, aliases in dir_aliases.items():
                if any(part.startswith(a) or f"{a}:" in part or f"{a} :" in part for a in aliases):
                    val = re.sub(r'^(?:' + '|'.join(aliases) + r')\s*[:=\-—]\s*', '', part).strip()
                    if val and not directions[std_key]['length']:
                        directions[std_key]['length'] = val if 'م' in val else f"{val} م"
                    break

    raw_streets = str(source.get('surrounding_streets') or '').strip()
    if raw_streets:
        for part in re.split(r'[|,\n،]', raw_streets):
            part = part.strip()
            if not part:
                continue
            for std_key, aliases in dir_aliases.items():
                if any(part.startswith(a) or f"{a}:" in part or f"{a} :" in part for a in aliases):
                    val = re.sub(r'^(?:' + '|'.join(aliases) + r')\s*[:=\-—]\s*', '', part).strip()
                    if val and not directions[std_key].get('street_name') and not directions[std_key].get('neighbour'):
                        if re.search(r'(?:شارع|طريق|ممر|ميدان|نافذ|street|road)', val):
                            directions[std_key]['street_name'] = val
                        else:
                            directions[std_key]['neighbour'] = val
                    break

    raw_setbacks = str(source.get('setbacks') or '').strip()
    if raw_setbacks:
        dir_setback_words = (
            ('north', r'(?:الجهة\s+)?(?:ال)?شمالي?(?:ة)?'),
            ('south', r'(?:الجهة\s+)?(?:ال)?جنوبي?(?:ة)?'),
            ('east', r'(?:الجهة\s+)?(?:ال)?شرقي?(?:ة)?'),
            ('west', r'(?:الجهة\s+)?(?:ال)?غربي?(?:ة)?'),
        )
        for std_key, word in dir_setback_words:
            if not directions[std_key].get('setback'):
                match = re.search(word + r'\s*[:=\-–—]?\s*([0-9٠-٩]+(?:[.,][0-9]+)?\s*(?:متر|م\.?))', raw_setbacks)
                if match:
                    val = match.group(1).strip()
                    directions[std_key]['setback'] = val if 'م' in val else f"{val} م"
        front_m = re.search(r'(?:أمامي|الواجهة|الشارع)\s*[:=\-–—]?\s*([0-9٠-٩]+(?:[.,][0-9]+)?\s*(?:متر|م\.?))', raw_setbacks)
        rear_m = re.search(r'(?:خلفي|الخلف)\s*[:=\-–—]?\s*([0-9٠-٩]+(?:[.,][0-9]+)?\s*(?:متر|م\.?))', raw_setbacks)
        side_m = re.search(r'(?:جانبي|الجانبين|الجانبيان|الجوانب)\s*[:=\-–—]?\s*([0-9٠-٩]+(?:[.,][0-9]+)?\s*(?:متر|م\.?))', raw_setbacks)
        for std_key, d in directions.items():
            if not d.get('setback'):
                if d.get('is_facade') and front_m:
                    d['setback'] = front_m.group(1).strip()
                elif not d.get('is_facade') and rear_m:
                    d['setback'] = rear_m.group(1).strip()
                elif side_m:
                    d['setback'] = side_m.group(1).strip()

    raw_streets = str(source.get('surrounding_streets') or '').strip()
    for std_key, d in directions.items():
        desc = f"{d.get('description', '')} {d.get('street_name', '')} {raw_streets}"
        if re.search(r'(?:شارع|طريق|ممر|ميدان|نافذ|street|road|avenue|boulevard)', desc):
            d['is_facade'] = True
            d['type'] = 'street'
        else:
            d['type'] = 'neighbor'

    key_view = ''
    full_text = f"{raw_streets} {json.dumps(directions, ensure_ascii=False)}"
    if re.search(r'(?:كورنيش|بحر|إطلالة بحرية|شاطئ|واجهة بحرية|sea view|corniche)', full_text, re.IGNORECASE):
        for std_key in ('west', 'north', 'east', 'south'):
            dir_text = json.dumps(directions.get(std_key, {}), ensure_ascii=False)
            if re.search(r'(?:كورنيش|بحر|إطلالة بحرية|شاطئ|واجهة بحرية)', dir_text):
                lbl = directions[std_key]['label']
                key_view = f"جهة {lbl} — جهة الإطلالة البحرية وطريق الكورنيش"
                break
        if not key_view:
            key_view = "جهة الإطلالة البحرية وطريق الكورنيش"
    elif re.search(r'(?:طريق رئيسي|محور|بوليفارد|شريان)', full_text):
        for std_key in ('west', 'north', 'east', 'south'):
            dir_text = json.dumps(directions.get(std_key, {}), ensure_ascii=False)
            if re.search(r'(?:طريق رئيسي|محور|طريق|بوليفارد)', dir_text):
                lbl = directions[std_key]['label']
                key_view = f"جهة {lbl} — واجهة الطريق الرئيسي"
                break

    return {
        'plot_name': 'أرض المشروع',
        'facades_summary': facades_summary or 'الواجهات المحيطة بالأرض',
        'north': directions['north'],
        'south': directions['south'],
        'east': directions['east'],
        'west': directions['west'],
        'key_view': key_view,
        'boundary_lengths_summary': raw_lengths,
        'surrounding_streets_summary': raw_streets,
    }


def _has_land_boundary_data(project_data):
    """Return whether the project has enough boundary evidence for the fixed diagram.

    Boundary facts can arrive through visible croquis fields or through the hidden
    structured result persisted from the land documents.  Looking only at the four
    visible scalar fields made the diagram disappear after a document-only analysis
    and, consequently, from location-only presentation generation.
    """
    source = project_data if isinstance(project_data, dict) else {}
    if any(str(source.get(key) or '').strip() for key in (
        'boundary_lengths', 'surrounding_streets', 'facades_count', 'facades_directions',
    )):
        return True
    data = _extract_land_boundary_diagram_data(source)
    if str(data.get('key_view') or '').strip():
        return True
    for key in ('north', 'south', 'east', 'west'):
        item = data.get(key) if isinstance(data.get(key), dict) else {}
        if any(str(item.get(field) or '').strip() for field in (
            'length', 'description', 'street_name', 'street_width'
        )):
            return True
    return False


def _build_land_boundary_diagram_slide(slide, project_data, branding, slide_num=None, total_slides=None):
    """Render the boundary diagram deterministically from approved land facts."""
    source = project_data if isinstance(project_data, dict) else {}
    data = _extract_land_boundary_diagram_data(source)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'مخطط اتجاهي لحدود الأرض'))
    project_name = html_lib.escape(str(data.get('plot_name') or source.get('project_name') or 'أرض المشروع'))

    def safe(value, fallback='غير متاح'):
        value = str(value or '').strip()
        return html_lib.escape(value or fallback)

    def card(direction_key):
        item = data.get(direction_key) if isinstance(data.get(direction_key), dict) else {}
        facade = bool(item.get('is_facade'))
        border = accent if facade else '#d9e3ec'
        label = safe(item.get('label'))
        length = safe(item.get('length'))
        street = str(item.get('street_name') or '').strip()
        description = str(item.get('description') or '').strip()
        neighbour = str(item.get('neighbour') or '').strip()
        width = safe(item.get('street_width')) if item.get('street_width') else ''
        uses = safe(item.get('uses')) if item.get('uses') else ''
        setback = safe(item.get('setback')) if item.get('setback') else ''

        lines = []
        if street:
            lines.append(f'<div style="margin-top:5px;color:{primary};font-size:11.5px;font-weight:700;">{safe(street)}</div>')
        elif neighbour:
            lines.append(f'<div style="margin-top:5px;color:{primary};font-size:11.5px;font-weight:700;">المجاور: {safe(neighbour)}</div>')
        if width:
            lines.append(f'<div style="margin-top:3px;color:#475569;font-size:10.5px;">عرض الشارع: {width}</div>')
        if neighbour and street:
            lines.append(f'<div style="margin-top:3px;color:#475569;font-size:10.5px;">المجاور: {safe(neighbour)}</div>')
        if setback:
            lines.append(f'<div style="margin-top:3px;color:#047857;font-size:10.5px;font-weight:700;">الارتداد: {setback}</div>')
        if description and description != street and description != neighbour:
            lines.append(f'<div style="margin-top:4px;color:#64748b;font-size:10px;line-height:1.35;">{safe(description)}</div>')
        elif uses:
            lines.append(f'<div style="margin-top:4px;color:#64748b;font-size:10px;line-height:1.35;">{uses}</div>')

        details_html = ''.join(lines)
        return (
            f'<div data-boundary-direction="{direction_key}" style="min-height:120px;border:2px solid {border};'
            f'border-radius:14px;background:#ffffff;padding:12px 14px;box-sizing:border-box;direction:rtl;'
            f'display:flex;flex-direction:column;justify-content:center;overflow:hidden;">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">'
            f'<span style="font-size:17px;font-weight:800;color:{primary};">{label}</span>'
            f'<span dir="ltr" style="font-size:20px;font-weight:800;color:{accent};white-space:nowrap;">{length}</span></div>'
            f'<div style="height:1px;background:#e2e8f0;margin:6px 0 0;"></div>{details_html}'
            '</div>'
        )

    key_view = str(data.get('key_view') or '').strip()
    view_html = (
        f'<div style="margin-top:10px;border-radius:9px;background:{accent};color:#172033;padding:8px 12px;'
        f'font-size:11px;font-weight:800;line-height:1.35;">{html_lib.escape(key_view)}</div>'
        if key_view else ''
    )
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;color:#172033;box-sizing:border-box;padding:76px 42px 48px;">
  <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:12px;">
    <div><h2 style="margin:0;color:{primary};font-size:28px;line-height:1.15;font-weight:800;">{title}</h2>
    <div style="margin-top:5px;color:#64748b;font-size:11px;">الأبعاد بالمتر</div></div>
    <div style="height:4px;width:82px;background:{accent};border-radius:4px;"></div>
  </div>
  <div data-boundary-diagram="1" style="height:500px;border:1px solid #dbe5ed;border-radius:16px;background:#f8fafc;padding:12px;box-sizing:border-box;display:grid;grid-template-columns:1fr 1.65fr 1fr;grid-template-rows:minmax(120px,1fr) minmax(180px,1.3fr) minmax(120px,1fr);gap:10px;direction:ltr;">
    <div style="grid-column:2;grid-row:1;">{card('north')}</div>
    <div style="grid-column:1;grid-row:2;">{card('west')}</div>
    <div style="grid-column:2;grid-row:2;border-radius:18px;background:{primary};color:#ffffff;border:3px solid {accent};padding:22px;box-sizing:border-box;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;direction:rtl;overflow:hidden;">
      <div style="font-size:27px;font-weight:800;line-height:1.2;">{project_name}</div>
      <div style="width:68px;height:3px;background:{accent};margin:13px 0;"></div>
      <div style="font-size:14px;line-height:1.55;color:#ffffff;">{safe(data.get('facades_summary'))}</div>{view_html}
    </div>
    <div style="grid-column:3;grid-row:2;">{card('east')}</div>
    <div style="grid-column:2;grid-row:3;">{card('south')}</div>
  </div>
  <div style="margin-top:9px;text-align:center;color:#64748b;font-size:10px;line-height:1.35;">تمثل القراءة اتجاهات الحدود وعلاقتها بالشوارع دون محاكاة مساحية للنسب.</div>
  <div data-slide-counter="1" style="display:none;">{slide_num_str}</div>
</div>'''


def _has_land_specs_data(project_data):
    """Return whether the project has enough regulatory or land specification facts."""
    source = project_data if isinstance(project_data, dict) else {}
    spec_keys = (
        'croquis_land_area', 'approved_financial_area', 'land_area', 'total_land_area',
        'plot_number', 'plan_number', 'deed_number', 'deed_date',
        'building_ratio_coverage', 'building_ratio_setbacks', 'far', 'setbacks',
        'max_floors_height', 'allowed_uses', 'building_system', 'parking_regulations',
    )
    if any(str(source.get(k) or '').strip() for k in spec_keys):
        return True
    doc_raw = source.get('land_documents_analysis_data') or source.get('landDocumentsAnalysisData') or source.get('land_documents_analysis')
    if doc_raw:
        doc = _decode_json_fact(doc_raw) if isinstance(doc_raw, (str, dict)) else {}
        if isinstance(doc, dict):
            if any(str(doc.get(k) or '').strip() for k in spec_keys):
                return True
            parcels = doc.get('parcels')
            if isinstance(parcels, list) and any(isinstance(p, dict) and any(str(p.get(k) or '').strip() for k in spec_keys) for p in parcels):
                return True
    return False


def _extract_land_specs_data(project_data):
    """Extract land specifications and regulatory conditions into a clean dictionary."""
    source = project_data if isinstance(project_data, dict) else {}
    doc_raw = source.get('land_documents_analysis_data') or source.get('landDocumentsAnalysisData') or source.get('land_documents_analysis')
    doc = _decode_json_fact(doc_raw) if isinstance(doc_raw, (str, dict)) else {}
    if not isinstance(doc, dict):
        doc = {}
    parcels = doc.get('parcels') if isinstance(doc.get('parcels'), list) else []
    first_parcel = parcels[0] if parcels and isinstance(parcels[0], dict) else {}

    def _val(*keys, fallback='—'):
        for k in keys:
            v = source.get(k)
            if v not in (None, '', [], {}):
                return str(v).strip()
            v = doc.get(k)
            if v not in (None, '', [], {}):
                return str(v).strip()
            v = first_parcel.get(k)
            if v not in (None, '', [], {}):
                return str(v).strip()
        return fallback

    plot_num = _val('plot_number', 'plotNumber', 'parcel_number')
    plan_num = _val('plan_number', 'planNumber')
    deed_num = _val('deed_number', 'deedNumber', 'instrument_number')
    deed_dt = _val('deed_date', 'deedDate', 'instrument_date')

    land_area = _val('approved_financial_area', 'croquis_land_area', 'land_area', 'total_land_area')
    built_area = _val('built_area', 'total_built_area', 'building_area')
    city = _val('city')
    district = _val('district')

    bldg_ratio = _val('building_ratio_coverage', 'building_ratio_setbacks', 'building_ratio', fallback='60% كحد أقصى')
    if bldg_ratio and not bldg_ratio.endswith('%') and bldg_ratio.isdigit():
        bldg_ratio += '%'

    far = _val('far', 'nsba_albna__far', 'floor_area_ratio')
    setbacks = _val('setbacks', 'building_setbacks', fallback='حسب كود البناء والاشتراطات البلدية')
    max_floors = _val('max_floors_height', 'max_floors', 'max_height', 'floors_allowed')
    allowed_uses = _val('allowed_uses', 'permitted_uses', 'zoning', 'land_use', fallback='تجاري / سكني استثماري')
    bldg_system = _val('building_system', 'regulatory_constraints')
    parking = _val('parking_regulations', 'parking_spaces', fallback='حسب اشتراطات كود البناء السعودي ومعايير الأمانة')
    infrastructure = _val('infrastructure', 'utilities', fallback='مكتملة الخدمات (كهرباء، مياه، اتصالات، إنارة)')

    return {
        'plot_number': plot_num,
        'plan_number': plan_num,
        'deed_number': deed_num,
        'deed_date': deed_dt,
        'land_area': land_area,
        'built_area': built_area,
        'city': city,
        'district': district,
        'building_ratio_coverage': bldg_ratio,
        'far': far,
        'setbacks': setbacks,
        'max_floors_height': max_floors,
        'allowed_uses': allowed_uses,
        'building_system': bldg_system,
        'parking_regulations': parking,
        'infrastructure': infrastructure,
    }


def _build_land_specs_slide(slide, project_data, branding=None, slide_num=None, total_slides=None):
    """Render land specifications and regulatory conditions as an editorial analytical slide."""
    source = project_data if isinstance(project_data, dict) else {}
    specs = _extract_land_specs_data(source)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'مواصفات الأرض والاشتراطات التنظيمية'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))

    land_area_fmt = specs['land_area']
    if land_area_fmt != '—' and 'م' not in land_area_fmt:
        try:
            num = float(land_area_fmt.replace(',', ''))
            land_area_fmt = f"{num:,.1f}".rstrip('0').rstrip('.') + ' م²'
        except (ValueError, TypeError):
            land_area_fmt += ' م²'

    top_metric_cards = [
        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">مساحة الأرض التنظيمية</div>'
        f'<div style="font-size:17px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(land_area_fmt)}</div></div>',

        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">نسبة التغطية والبناء</div>'
        f'<div style="font-size:17px;font-weight:800;color:{accent};margin-top:2px;">{html_lib.escape(specs["building_ratio_coverage"])}</div></div>',

        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">معامل البناء (FAR)</div>'
        f'<div style="font-size:17px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(specs["far"])}</div></div>',

        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">الحد الأقصى للارتفاع / الأدوار</div>'
        f'<div style="font-size:17px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(specs["max_floors_height"])}</div></div>',
    ]
    metrics_strip = f'<div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:14px;margin-bottom:16px;">{"".join(top_metric_cards)}</div>'

    doc_rows = [
        ('رقم الصك وتاريخه', f"صك رقم {specs['deed_number']} — تاريخ {specs['deed_date']}" if specs['deed_number'] != '—' else '—'),
        ('رقم المخطط والقطعة', f"مخطط رقم {specs['plan_number']} / قطعة رقم {specs['plot_number']}" if specs['plot_number'] != '—' else '—'),
        ('المدينة والحي', f"{specs['city']} — حي {specs['district']}" if specs['city'] != '—' else '—'),
        ('الاستخدامات المصرحة', specs['allowed_uses']),
        ('البنية التحتية والخدمات', specs['infrastructure']),
    ]
    doc_table_html = ''.join(
        f'<div style="display:flex;align-items:flex-start;justify-content:space-between;padding:10px 0;border-bottom:1px solid #f1f5f9;font-size:12.5px;">'
        f'<div style="font-weight:700;color:#64748b;min-width:140px;">{label}</div>'
        f'<div style="font-weight:700;color:{primary};text-align:left;flex:1;">{html_lib.escape(val)}</div>'
        f'</div>' for label, val in doc_rows
    )

    reg_rows = [
        ('الارتدادات النظامية', specs['setbacks']),
        ('نظام البناء والاشتراطات', specs['building_system']),
        ('اشتراطات المواقف والمداخل', specs['parking_regulations']),
        ('مساحة البناء المعتمدة', specs['built_area']),
    ]
    reg_table_html = ''.join(
        f'<div style="display:flex;align-items:flex-start;justify-content:space-between;padding:11px 0;border-bottom:1px solid #f1f5f9;font-size:12.5px;">'
        f'<div style="font-weight:700;color:#64748b;min-width:150px;">{label}</div>'
        f'<div style="font-weight:700;color:{primary};text-align:left;flex:1;">{html_lib.escape(val)}</div>'
        f'</div>' for label, val in reg_rows
    )

    columns_html = f'''<div style="display:grid;grid-template-columns:1.05fr 0.95fr;gap:18px;height:385px;">
      <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:18px 20px;box-sizing:border-box;">
        <div style="font-size:15px;font-weight:800;color:{primary};margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid {primary};">المحددات التوثيقية والمساحية</div>
        {doc_table_html}
      </div>
      <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:18px 20px;box-sizing:border-box;">
        <div style="font-size:15px;font-weight:800;color:{accent};margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid {accent};">الاشتراطات والضوابط التنظيمية</div>
        {reg_table_html}
      </div>
    </div>'''

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">LAND SPECIFICATIONS</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">المحددات التوثيقية والمساحية والاشتراطات والضوابط العمرانية للمشروع</p>
      </div>
    </div>
  </header>
  <div style="padding:0 36px;margin-top:14px;">
    {metrics_strip}
    {columns_html}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">مواصفات واشتراطات الأرض</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_timeline_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render project timeline as a high-end visual pipeline across all phases."""
    source = source if isinstance(source, dict) else {}
    phases = parse_timeline_phases(source)
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'الجدول الزمني ومراحل التطوير'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))

    total_months = sum(int(p.get('duration') or 0) for p in phases if str(p.get('duration') or '').isdigit())
    years_val = source.get('timeline_years') or (str(round(total_months / 12)) if total_months >= 12 else '—')
    start_str = phases[0].get('start_label') or f"سنة {phases[0].get('year', '1')} ({phases[0].get('quarter', 'Q1')})" if phases else '—'
    end_str = phases[-1].get('end_label') or f"سنة {phases[-1].get('endYear', '')} ({phases[-1].get('endQuarter', '')})" if phases else '—'
    duration_str = f"{total_months} شهر ({years_val} سنوات)" if total_months else (f"{years_val} سنوات" if years_val != '—' else '—')

    stats_cards = [
        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">المدة الكلية للمشروع</div>'
        f'<div style="font-size:15px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(str(duration_str))}</div></div>',

        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">تاريخ انطلاق الأعمال</div>'
        f'<div style="font-size:15px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(str(start_str))}</div></div>',

        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">التسليم والتشغيل المتوقع</div>'
        f'<div style="font-size:15px;font-weight:800;color:{primary};margin-top:2px;">{html_lib.escape(str(end_str))}</div></div>',

        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 16px;text-align:center;">'
        f'<div style="font-size:11px;font-weight:700;color:#64748b;">المراحل التنفيذية المعتمدة</div>'
        f'<div style="font-size:15px;font-weight:800;color:{accent};margin-top:2px;">{len(phases)} مراحل رئيسية</div></div>',
    ]
    stats_strip_html = f'<div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:14px;margin-bottom:18px;">{"".join(stats_cards)}</div>'

    num_phases = len(phases)
    if num_phases <= 5:
        cards = []
        for idx, phase in enumerate(phases, 1):
            p_name = html_lib.escape(str(phase.get('name') or ''))
            p_dur = str(phase.get('duration') or '').strip()
            dur_badge = f'<span style="background:#f1f5f9;color:{primary};padding:3px 8px;border-radius:6px;font-size:11.5px;font-weight:700;border:1px solid #cbd5e1;">{p_dur} شهر</span>' if p_dur else ''
            p_start = phase.get('start_label') or f"سنة {phase.get('year', '')} ({phase.get('quarter', '')})"
            p_end = phase.get('end_label') or f"سنة {phase.get('endYear', '')} ({phase.get('endQuarter', '')})"
            p_notes = html_lib.escape(str(phase.get('notes') or '').strip())
            notes_html = f'<div style="font-size:11.5px;color:#475569;line-height:1.48;margin-top:10px;padding-top:8px;border-top:1px dashed #e2e8f0;">{p_notes}</div>' if p_notes else ''

            card = f'''<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:16px 14px;display:flex;flex-direction:column;justify-content:space-between;box-sizing:border-box;position:relative;border-top:5px solid {accent if idx % 2 == 1 else primary};">
              <div>
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                  <span style="font-size:11px;font-weight:800;color:#94a3b8;">المرحلة 0{idx}</span>
                  {dur_badge}
                </div>
                <div style="font-size:14.5px;font-weight:800;color:{primary};line-height:1.4;margin-bottom:10px;min-height:40px;">{p_name}</div>
                <div style="background:#f8fafc;border-radius:8px;padding:8px 10px;font-size:11.5px;color:#334155;line-height:1.5;">
                  <div><strong style="color:#64748b;">من:</strong> {html_lib.escape(str(p_start))}</div>
                  <div style="margin-top:2px;"><strong style="color:#64748b;">إلى:</strong> {html_lib.escape(str(p_end))}</div>
                </div>
              </div>
              {notes_html}
            </div>'''
            cards.append(card)
        pipeline_html = f'<div style="display:grid;grid-template-columns:repeat({max(1, num_phases)}, 1fr);gap:12px;height:380px;">{"".join(cards)}</div>'
    else:
        cards = []
        for idx, phase in enumerate(phases, 1):
            p_name = html_lib.escape(str(phase.get('name') or ''))
            p_dur = str(phase.get('duration') or '').strip()
            dur_text = f"{p_dur} شهر" if p_dur else ''
            p_start = phase.get('start_label') or f"سنة {phase.get('year', '')} ({phase.get('quarter', '')})"
            p_end = phase.get('end_label') or f"سنة {phase.get('endYear', '')} ({phase.get('endQuarter', '')})"
            p_notes = html_lib.escape(str(phase.get('notes') or '').strip())
            card = f'''<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;border-right:4px solid {primary};">
              <div style="display:flex;align-items:center;justify-content:space-between;">
                <span style="font-size:13.5px;font-weight:800;color:{primary};">المرحلة 0{idx}: {p_name}</span>
                <span style="font-size:11.5px;font-weight:700;color:#64748b;">{dur_text} ({p_start} — {p_end})</span>
              </div>
              {f'<div style="font-size:11px;color:#475569;margin-top:4px;">{p_notes}</div>' if p_notes else ''}
            </div>'''
            cards.append(card)
        pipeline_html = f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;max-height:380px;overflow:hidden;">{"".join(cards)}</div>'

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">TIMELINE & DEVELOPMENT</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">المراحل التنفيذية والمدد الزمنية المتوقعة لتطوير وإنجاز المشروع</p>
      </div>
    </div>
  </header>
  <div style="padding:0 36px;margin-top:14px;">
    {stats_strip_html}
    {pipeline_html}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">الجدول الزمني ومراحل المشروع</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _exec_badges_strip(source, primary, accent):
    """Location/type/area chips shown on the first executive page only."""
    badges = []
    city = str(source.get('city') or '').strip()
    district = str(source.get('district') or '').strip()
    loc = ' — '.join(p for p in (city, district) if p)
    if loc:
        badges.append(f'<span style="background:#f8fafc;border:1px solid #cbd5e1;color:#334155;padding:4px 12px;border-radius:6px;font-size:12px;font-weight:700;">الموقع: {html_lib.escape(loc)}</span>')
    prop_type = str(source.get('property_type') or source.get('project_type') or '').strip()
    if prop_type:
        badges.append(f'<span style="background:#f8fafc;border:1px solid #cbd5e1;color:{primary};padding:4px 12px;border-radius:6px;font-size:12px;font-weight:700;">نوع المشروع: {html_lib.escape(prop_type)}</span>')
    land_area = str(source.get('approved_financial_area') or source.get('land_area') or '').strip()
    if land_area:
        badges.append(f'<span style="background:#f8fafc;border:1px solid #cbd5e1;color:{accent};padding:4px 12px;border-radius:6px;font-size:12px;font-weight:700;">مساحة الأرض: {html_lib.escape(land_area)} م²</span>')
    if not badges:
        return ''
    return f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;direction:rtl;">{"".join(badges)}</div>'


def _exec_text_chunks(text, target=620):
    """Split a long approved text into readable chunks at sentence boundaries."""
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not text:
        return []
    sentences = [s.strip() for s in re.split(r'(?<=[.!؟?])\s+', text) if s.strip()]
    if len(sentences) <= 1:
        return [text]
    chunks = []
    buf = ''
    for sentence in sentences:
        if buf and len(buf) + len(sentence) + 1 > target:
            chunks.append(buf)
            buf = sentence
        else:
            buf = f'{buf} {sentence}'.strip()
    if buf:
        chunks.append(buf)
    return chunks


def _exec_editorial_body(rows, row_offset, primary, accent, ext_token=''):
    """Editorial block: dark lead section + numbered rows with highlighted figures.

    Executive slides carry no images or maps; ext_token is accepted for
    backwards compatibility but never rendered.
    """
    """Editorial block: dark lead section + numbered rows with highlighted figures."""
    rows = list(rows or [])
    if not rows:
        rows = [('', '')]
    compact = len(rows) <= 2

    lead_label, lead_value = rows[0]
    lead_columns = 'column-count:2;column-gap:34px;' if len(str(lead_value or '')) > 320 else ''
    lead_label_html = (
        f'<span style="font-size:{19 if compact else 17}px;font-weight:800;color:#ffffff;">{html_lib.escape(str(lead_label))}</span>'
    ) if lead_label else ''
    lead_html = (
        f'<div style="background:{primary};border-radius:12px;padding:{24 if compact else 20}px 28px;'
        f'box-sizing:border-box;position:relative;overflow:hidden;">'
        f'<div style="display:flex;align-items:baseline;gap:14px;margin-bottom:{12 if compact else 8}px;">'
        f'<span style="font-size:30px;font-weight:800;color:{accent};line-height:1;">{row_offset + 1:02d}</span>'
        f'{lead_label_html}'
        f'<span style="flex:1;border-bottom:1px solid rgba(255,255,255,0.22);transform:translateY(-6px);"></span>'
        f'</div>'
        f'<div style="font-size:{14 if compact else 13.5}px;line-height:1.85;color:#eef2f7;text-align:justify;{lead_columns}">'
        f'{_market_rich_text(lead_value, accent)}</div>'
        f'</div>'
    )

    def render_topic(index, label, value):
        label_html = (
            f'<span style="font-size:{15.5 if compact else 14}px;font-weight:800;color:{primary};white-space:nowrap;">{html_lib.escape(str(label))}</span>'
        ) if label else ''
        text_len = len(re.sub(r'\s+', ' ', str(value or '')).strip())
        columns = 'column-count:2;column-gap:30px;' if text_len > 420 else ''
        return (
            f'<div data-exec-topic="{index}" style="padding:{14 if compact else 11}px 2px 0;">'
            f'<div style="display:flex;align-items:baseline;gap:12px;">'
            f'<span style="font-size:{24 if compact else 21}px;font-weight:800;color:{accent};line-height:1;min-width:34px;">{index:02d}</span>'
            f'{label_html}'
            f'<span style="flex:1;border-bottom:1px solid #e2e8f0;transform:translateY(-5px);"></span>'
            f'</div>'
            f'<div style="margin-top:{8 if compact else 5}px;font-size:{13 if compact else 12.5}px;line-height:{1.85 if compact else 1.72};'
            f'color:#334155;text-align:justify;{columns}">{_market_rich_text(value, accent)}</div>'
            f'</div>'
        )

    topics_html = ''.join(
        render_topic(row_offset + idx + 1, label, value)
        for idx, (label, value) in enumerate(rows[1:], 1)
    )
    return f'<div data-exec-analysis="1" style="display:flex;flex-direction:column;gap:{14 if compact else 10}px;">{lead_html}{topics_html}</div>'


def _build_executive_summary_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render one page of the approved executive summary as editorial sections."""
    source = source if isinstance(source, dict) else {}
    sections = _executive_summary_sections(source)
    rows, row_offset = _market_rows_for_slide(slide, 'executive_content.summary', sections)
    if row_offset == 0 and (slide or {}).get('market_row_start') is None:
        content_source = str((slide or {}).get('content_source') or '')
        if ':' not in content_source:
            pages = _executive_summary_pages(source)
            if pages:
                rows = pages[0][1]

    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'الملخص التنفيذي'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))

    badge_strip = _exec_badges_strip(source, primary, accent) if row_offset == 0 else ''
    body_content = _exec_editorial_body(rows, row_offset, primary, accent)

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">EXECUTIVE SUMMARY</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">الرؤية الشاملة والقيمة الاستثمارية والركائز الجوهرية للمشروع</p>
      </div>
    </div>
  </header>
  <div style="padding:0 40px;margin-top:12px;">
    {badge_strip}
    {body_content}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">الملخص التنفيذي للمشروع</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_executive_opportunity_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render the investment opportunity as one editorial page."""
    source = source if isinstance(source, dict) else {}
    executive = _decode_json_fact(source.get('executive_content'))
    opp_text = str((executive.get('opportunity') if isinstance(executive, dict) else None) or '').strip()

    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'الفرصة الاستثمارية'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))

    badge_strip = _exec_badges_strip(source, primary, accent)

    chunks = _exec_text_chunks(opp_text)
    all_rows = [('', chunk) for chunk in chunks] or [('', 'الفرصة الاستثمارية للمشروع')]
    rows, row_offset = _market_rows_for_slide(slide, 'executive_content.opportunity', all_rows)
    if row_offset == 0 and (slide or {}).get('market_row_start') is None:
        content_source = str((slide or {}).get('content_source') or '')
        if ':' not in content_source:
            pages = _budget_row_pages(all_rows)
            if pages:
                rows = pages[0][1]
    body_content = _exec_editorial_body(rows, row_offset, primary, accent)

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">INVESTMENT OPPORTUNITY</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">الفرصة الاستثمارية ومحركات الجدوى والعوائد المتوقعة للمشروع</p>
      </div>
    </div>
  </header>
  <div style="padding:0 40px;margin-top:12px;">
    {badge_strip}
    {body_content}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">الفرصة الاستثمارية</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _executive_feature_items(source, slide=None):
    """Feature bullets from executive_content.features (list, newline, bullet or ' - ' separated)."""
    executive = _decode_json_fact((source or {}).get('executive_content'))
    features_raw = executive.get('features') if isinstance(executive, dict) else []
    items = []
    if isinstance(features_raw, list):
        items = [str(it).strip() for it in features_raw if str(it).strip()]
    elif isinstance(features_raw, str) and features_raw.strip():
        for line in re.split(r'[\r\n]+', features_raw):
            for part in re.split(r'\s+-\s+|\s+—\s+|•', line):
                cleaned = str(part).strip(' -–—•*').strip()
                if cleaned:
                    items.append(cleaned)
    if not items:
        bullets = (slide or {}).get('bullets') or []
        items = [str(b).strip() for b in bullets if str(b).strip()]
    deduped = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _executive_feature_page_size(items):
    """Balanced per-page capacity for numbered feature lists."""
    items = list(items or [])
    mean_len = (sum(len(item) for item in items) / len(items)) if items else 0
    return 14 if mean_len <= 140 else (10 if mean_len <= 260 else 8)


def _build_executive_features_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    """Render executive differentiators as a numbered editorial list."""
    source = source if isinstance(source, dict) else {}
    all_items = _executive_feature_items(source, slide)
    item_rows, row_offset = _market_rows_for_slide(slide, 'executive_content.features', all_items)
    if row_offset == 0 and (slide or {}).get('market_row_start') is None:
        content_source = str((slide or {}).get('content_source') or '')
        if ':' not in content_source:
            ranges = _balanced_row_ranges(len(all_items), _executive_feature_page_size(all_items))
            if ranges:
                item_rows = all_items[ranges[0][0]:ranges[0][1]]
    items = list(item_rows)
    if not items:
        items = all_items or ['مقومات تنافسية متميزة للمشروع', 'موقع استراتيجي وتدفقات مستهدفة', 'عوائد استثمارية مجدية ونمو مستدام']

    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'المميزات وفرص الاستثمار'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))

    badge_strip = _exec_badges_strip(source, primary, accent)

    cols = 2 if len(items) > 5 else 1
    col_size = (len(items) + cols - 1) // cols
    item_font = 12.5 if len(items) > 12 else (13.5 if cols == 2 else 14.5)

    def render_item(index, item_text):
        return (
            f'<div style="display:flex;align-items:baseline;gap:12px;padding:{12 if cols == 2 else 15}px 4px;'
            f'border-bottom:1px solid #e2e8f0;">'
            f'<span style="font-size:20px;font-weight:800;color:{accent};line-height:1;min-width:32px;">{index:02d}</span>'
            f'<span style="font-size:{item_font}px;line-height:1.7;color:#334155;font-weight:600;">{_market_rich_text(item_text, accent)}</span>'
            f'</div>'
        )

    col_blocks = []
    for col in range(cols):
        block = items[col * col_size:(col + 1) * col_size]
        if not block:
            continue
        inner = ''.join(render_item(row_offset + col * col_size + i + 1, item) for i, item in enumerate(block))
        col_blocks.append(
            f'<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:6px 20px;box-sizing:border-box;">{inner}</div>'
        )

    count_badge = (
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;direction:rtl;">'
        f'<span style="background:{primary};color:#ffffff;padding:5px 14px;border-radius:6px;font-size:12.5px;font-weight:800;">{len(items)} ميزة تنافسية</span>'
        f'</div>'
    )
    grid_html = f'<div style="display:grid;grid-template-columns:{"1fr 1fr" if cols == 2 else "1fr"};gap:18px;align-items:start;">{"".join(col_blocks)}</div>'

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ''
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">PROJECT FEATURES & ADVANTAGES</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">أبرز المقومات التنافسية وعناصر الجذب الاستثماري للمشروع</p>
      </div>
    </div>
  </header>
  <div style="padding:0 40px;margin-top:12px;">
    {badge_strip}
    {count_badge}
    {grid_html}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">المميزات وفرص الاستثمار</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''
