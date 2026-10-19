"""Financial PDF generator from model (PyMuPDF fallback)."""

import os
import fitz


def generate_financial_pdf_from_model(project_name, model, output_path):
    import fitz
    inputs = _financial_inputs(model)
    tables = model.get('tables', {}) if isinstance(model, dict) and isinstance(model.get('tables'), dict) else {}
    projection = model.get('projection', {}) if isinstance(model, dict) and isinstance(model.get('projection'), dict) else {}
    mode = inputs.get('unitRevenueMode') or 'mixed'
    rental_on = mode in {'rental', 'mixed'}
    font_path = _financial_pdf_font()
    document = fitz.open()
    page_size = fitz.paper_rect('a4-l')
    page = document.new_page(width=page_size.width, height=page_size.height)
    margin = 28
    y = margin
    font_name = 'helv'
    if font_path:
        try:
            page.insert_font(fontname='arabic', fontfile=font_path)
            font_name = 'arabic'
        except Exception as error:
            print(f'[FINANCIAL PDF] custom font skipped ({error})')
            font_path = None
    metrics = fitz.Font(fontfile=font_path) if font_path else fitz.Font('helv')
    latin_metrics = fitz.Font('helv')

    def ensure_space(needed=24):
        nonlocal page, y
        if y + needed < page_size.height - margin:
            return
        page = document.new_page(width=page_size.width, height=page_size.height)
        if font_path:
            try:
                page.insert_font(fontname='arabic', fontfile=font_path)
            except Exception:
                pass
        y = margin

    def split_runs(value):
        """Group a visual-order line by which embedded font actually owns each glyph.

        The bundled Arabic font carries no Latin or percent glyph, so a single-font
        line drops them to empty boxes.
        """
        runs = []
        for character in value:
            arabic = font_name == 'arabic' and metrics.has_glyph(ord(character))
            name, font = (font_name, metrics) if arabic else ('helv', latin_metrics)
            if runs and runs[-1][0] == name:
                runs[-1][2] += character
            else:
                runs.append([name, font, character])
        return runs

    def place(rect, text, size, color=(0.15, 0.15, 0.15)):
        """Right-align one line with insert_text.

        insert_textbox silently draws nothing when its line height does not fit the
        rectangle, which is why the whole report used to come out as empty borders.
        """
        value = _financial_pdf_shape(text)
        if not value.strip():
            return
        runs = split_runs(value)
        width = lambda items: sum(font.text_length(part, size) for _, font, part in items)
        while len(value) > 1 and width(runs) > rect.width:
            value = value[1:]
            runs = split_runs(value)
        baseline = min(rect.y0 + size, rect.y1 - 1) if rect.height > size else rect.y0 + size
        x = max(rect.x0, rect.x1 - width(runs))
        for name, font, part in runs:
            page.insert_text((x, baseline), part, fontname=name, fontsize=size, color=color)
            x += font.text_length(part, size)

    def place_wrapped(rect, text, size, color=(0.1, 0.1, 0.1), max_lines=2):
        """Header cells carry whole Arabic phrases, so a single truncated line loses the column."""
        words = str(text or '').split(' ')
        lines, current = [], ''
        for word in words:
            candidate = (current + ' ' + word).strip()
            if current and metrics.text_length(_financial_pdf_shape(candidate), size) > rect.width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        for index, line in enumerate(lines[:max_lines]):
            top = rect.y0 + index * (size + 1)
            place(fitz.Rect(rect.x0, top, rect.x1, top + size + 1), line, size, color=color)

    def draw_text(text, size=11, indent=0):
        nonlocal y
        ensure_space(size + 8)
        box = fitz.Rect(margin + indent, y, page_size.width - margin, y + size + 6)
        place(box, text, size, color=(0.1, 0.1, 0.1))
        y += size + 8

    def draw_paragraph(text, size=9):
        nonlocal y
        width = page_size.width - margin * 2
        for paragraph in str(text or '').splitlines() or ['']:
            words = paragraph.split()
            if not words:
                y += size + 4
                continue
            line = ''
            for word in words:
                candidate = (line + ' ' + word).strip()
                shaped = _financial_pdf_shape(candidate)
                measured = sum(font.text_length(part, size) for _, font, part in split_runs(shaped))
                if line and measured > width:
                    draw_text(line, size)
                    line = word
                else:
                    line = candidate
            if line:
                draw_text(line, size)

    def draw_kv_table(rows, raw=False):
        nonlocal y
        visible = []
        for item in rows:
            label, value, key = (item + ('',))[:3] if len(item) < 3 else item
            if value in (None, '', [], {}) or isinstance(value, (dict, list)):
                continue
            visible.append((
                str(label),
                html_lib.unescape(_financial_report_format_display(value, label)) if raw
                else _financial_pdf_text(value, key),
            ))
        if not visible:
            draw_text('لا توجد قيم مطبقة في هذا القسم.', 9)
            return
        col_w = (page_size.width - margin * 2) / 2
        for label, value in visible:
            if label.strip() == 'الإيضاحات':
                draw_paragraph(value)
                y += 4
                continue
            ensure_space(16)
            rect = fitz.Rect(margin, y, page_size.width - margin, y + 15)
            page.draw_rect(rect, color=(0.85, 0.82, 0.8), width=0.4)
            place(fitz.Rect(rect.x0 + col_w + 4, rect.y0 + 2, rect.x1 - 4, rect.y1), label, 8)
            place(fitz.Rect(rect.x0 + 4, rect.y0 + 2, rect.x0 + col_w - 4, rect.y1), value, 8)
            y += 15

    def draw_data_table(rows, title):
        nonlocal y
        if not isinstance(rows, list) or not rows:
            draw_text(title, 12)
            draw_text('لا توجد بنود مدخلة في هذا الجدول.', 9)
            return
        keys = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in row:
                label = FINANCIAL_COLUMN_LABELS.get(key, key)
                if key in FINANCIAL_REPORT_DROP_COLUMNS or label in FINANCIAL_REPORT_DROP_COLUMNS:
                    continue
                if key not in keys:
                    keys.append(key)
        if not keys:
            draw_text(title, 12)
            draw_text('لا توجد بنود مدخلة في هذا الجدول.', 9)
            return
        preferred = {
            'cashflowTable': ['year', 'phase', 'saleRevenue', 'operatingRevenue', 'developmentCost', 'developerPayment', 'opex', 'noi', 'financeDraw', 'financeInterest', 'final', 'cumulative'],
            'sensitivityAssumptionsTable': ['key', 'low', 'high'],
            'sensitivityTable': ['scenario', 'totalRevenue', 'investmentCost', 'netProfit', 'roi', 'projectIrr', 'equityRequired'],
        }
        wanted = preferred.get(title) or preferred.get(next((key for key in ('cashflowTable', 'sensitivityAssumptionsTable', 'sensitivityTable') if key in title), ''))
        if 'التدفقات' in title:
            wanted = preferred['cashflowTable']
        elif 'الافتراضات' in title:
            wanted = preferred['sensitivityAssumptionsTable']
        elif 'النتائج' in title and 'حساسية' in title:
            wanted = preferred['sensitivityTable']
        if wanted:
            keys = [key for key in wanted if key in keys] or keys[:8]
        elif len(keys) > 8:
            keys = keys[:8]
        draw_text(title, 12)
        usable = page_size.width - margin * 2
        col_w = usable / max(1, len(keys))
        row_h = 14
        def paint_row(values, header=False):
            nonlocal y
            ensure_space(row_h)
            x = margin
            for value in reversed(values):
                cell = fitz.Rect(x, y, x + col_w, y + row_h)
                fill = (0.07, 0.23, 0.43) if header else None
                page.draw_rect(cell, color=(0.85, 0.82, 0.8), fill=fill, width=0.4)
                color = (1, 1, 1) if header else (0.15, 0.15, 0.15)
                place(cell + (2, 1, -2, -1), value, 7, color=color)
                x += col_w
            y += row_h
        paint_row([FINANCIAL_COLUMN_LABELS.get(key, key) for key in keys], header=True)
        for row in rows:
            if isinstance(row, dict):
                paint_row([_financial_pdf_text(row.get(key), key) for key in keys])

    def draw_grid(headers, rows):
        """Draw a screen table verbatim. Columns beyond a readable page width continue in a
        second band that repeats the first column, so no entered figure is dropped."""
        nonlocal y
        if not headers:
            return
        if not rows:
            draw_text('لا توجد بنود مدخلة في هذا الجدول.', 9)
            return
        rows = [
            [
                html_lib.unescape(_financial_report_format_display(
                    value, headers[index] if index < len(headers) else ''
                ))
                for index, value in enumerate(row)
            ]
            for row in rows
        ]
        cell = lambda row, index: str(row[index]).strip() if index < len(row) else ''
        max_columns = 9
        bands = [(headers, rows)]
        if len(headers) > max_columns:
            bands = []
            for start in range(1, len(headers), max_columns - 1):
                picked = list(range(start, min(start + max_columns - 1, len(headers))))
                bands.append(([headers[0]] + [headers[index] for index in picked],
                              [[cell(row, 0)] + [cell(row, index) for index in picked] for row in rows]))
        for band_headers, band_rows in bands:
            col_w = (page_size.width - margin * 2) / len(band_headers)
            ensure_space(38)
            top = y
            x = margin
            for header in reversed(band_headers):
                box = fitz.Rect(x, top, x + col_w, top + 22)
                page.draw_rect(box, color=(0.7, 0.7, 0.7), fill=(0.9, 0.9, 0.9), width=0.4)
                place_wrapped(box + (2, 2, -2, -2), header, 7)
                x += col_w
            y = top + 22
            for row in band_rows:
                ensure_space(14)
                top = y
                x = margin
                for index in reversed(range(len(band_headers))):
                    box = fitz.Rect(x, top, x + col_w, top + 14)
                    page.draw_rect(box, color=(0.7, 0.7, 0.7), width=0.4)
                    place(box + (2, 1, -2, -1), cell(row, index), 7)
                    x += col_w
                y = top + 14
            y += 8

    screen_parts = _financial_screen_parts(model)
    if screen_parts:
        draw_text(project_name or 'الدراسة المالية', 18)
        for part in screen_parts:
            if not isinstance(part, dict):
                continue
            kind = part.get('type')
            if kind == 'heading':
                draw_text(str(part.get('text') or ''), 10 if part.get('level') == 3 else 12)
            elif kind == 'fields':
                draw_kv_table([(row[0], row[1], '') for row in (part.get('rows') or [])
                               if isinstance(row, (list, tuple)) and len(row) >= 2], raw=True)
            elif kind == 'table':
                draw_grid([str(header) for header in (part.get('headers') or [])],
                          [list(row) for row in (part.get('rows') or []) if isinstance(row, (list, tuple))])
        document.save(output_path)
        document.close()
        return output_path

    draw_text(project_name or 'الدراسة المالية', 18)
    draw_text('التقرير المالي المنظم', 13)
    draw_text('1. ملخص المشروع', 12)
    draw_kv_table([
        ('طبيعة الإيرادات', inputs.get('unitRevenueMode'), 'unitRevenueMode'),
        ('مدة التطوير', inputs.get('developmentDurationText') or inputs.get('developmentYears'), 'developmentYears'),
        ('سنوات التشغيل', inputs.get('operationYears'), 'operationYears'),
        ('مساحة الأرض', inputs.get('landArea'), 'landArea'),
    ])
    draw_text('2. الأرض والمساحات', 12)
    draw_kv_table([
        ('مساحة الأرض', inputs.get('landArea'), 'landArea'),
        ('نسبة التغطية', inputs.get('coverageRate'), 'coverageRate'),
        ('عدد الطوابق', inputs.get('floorCount'), 'floorCount'),
        ('مسطحات البناء فوق الأرض', inputs.get('builtUpAreaAbove'), 'builtUpAreaAbove'),
        ('مساحة البدرومات', inputs.get('basementArea'), 'basementArea'),
        ('حالة الأرض', inputs.get('landStatus'), 'landStatus'),
    ])
    for number, title, table_key in (
        ('3', 'مكونات المشروع', 'componentsTable'),
        ('4', 'بنود الإيرادات', 'revenueTable'),
        ('5', 'تكاليف المشروع', 'costTable'),
    ):
        draw_data_table(tables.get(table_key), f'{number}. {title}')
    if inputs.get('developerPaymentsEnabled', 'yes') == 'yes':
        draw_data_table(tables.get('scheduleTable'), '6. مراحل التطوير ودفعات المطور')
    draw_data_table(tables.get('opexTable'), '7. المصروفات التشغيلية')
    if rental_on and inputs.get('graceEnabled') == 'yes':
        draw_text('فترة السماح للمستأجرين', 12)
        draw_kv_table([
            ('طريقة احتساب السماح', inputs.get('graceMethod'), 'graceMethod'),
            ('نطاق فترة السماح', inputs.get('graceScope'), 'graceScope'),
            ('سنة بداية السماح', inputs.get('graceStartYear'), 'graceStartYear'),
            ('مدة السماح (شهر)', inputs.get('graceDurationMonths'), 'graceDurationMonths'),
            ('نسبة الخصم %', inputs.get('graceDiscountRate'), 'graceDiscountRate'),
            ('إجمالي الخصم', inputs.get('graceTotalDiscount') or projection.get('totalGraceDiscount'), 'graceTotalDiscount'),
        ])
        if inputs.get('graceMethod') == 'schedule' and tables.get('graceScheduleTable'):
            draw_data_table(tables.get('graceScheduleTable'), 'جدول خصومات فترة السماح')
    if inputs.get('fundEnabled') == 'yes' and inputs.get('fundFeesEnabled') == 'yes':
        draw_text('8. الصندوق وأتعابه', 12)
        draw_kv_table([
            ('أساس الأتعاب', inputs.get('fundFeeBase'), 'fundFeeBase'),
            ('نسبة الإدارة', inputs.get('fundManagementRate'), 'fundManagementRate'),
        ])
        draw_data_table(tables.get('fundAdditionalFeesTable'), 'أتعاب إضافية')
    if inputs.get('financeEnabled') == 'yes':
        draw_text('9. التمويل', 12)
        draw_kv_table([
            ('أساس التمويل', inputs.get('financeBase'), 'financeBase'),
            ('نسبة التمويل', inputs.get('financingRate'), 'financingRate'),
            ('معدل المرابحة', inputs.get('annualFinanceRate'), 'annualFinanceRate'),
            ('قيمة أساس التمويل', inputs.get('financeBaseAmount') or projection.get('financeBaseAmount'), 'financeBaseAmount'),
            ('قيمة التسهيل التمويلي', inputs.get('facilityAmount') or projection.get('facilityAmount'), 'facilityAmount'),
        ])
        draw_data_table(tables.get('financeDrawTable'), 'خطة السحب')
        draw_data_table(tables.get('financeRepaymentTable'), 'خطة السداد')
        if tables.get('financeMurabahaTable'):
            draw_data_table(tables.get('financeMurabahaTable'), 'خطة المرابحة')
    if inputs.get('externalEnabled') == 'yes' and tables.get('externalTable'):
        draw_text('10. البنود الخارجية', 12)
        draw_data_table(tables.get('externalTable'), 'البنود الخارجية')
    if inputs.get('exitEnabled') == 'yes':
        draw_text('11. التخارج', 12)
        draw_kv_table([
            ('التخارج البيعي', inputs.get('saleExitMethod'), 'saleExitMethod'),
            ('التخارج التشغيلي', inputs.get('exitMethod'), 'exitMethod'),
            ('سنة التخارج التشغيلي', inputs.get('operatingExitYear'), 'operatingExitYear'),
        ])
    draw_text('12. النتائج المالية', 12)
    filtered_results = _filter_financial_results(inputs, projection)
    draw_kv_table(filtered_results)
    cf_rows = _filter_cashflow_columns(tables.get('cashflowTable'), inputs)
    draw_data_table(cf_rows, '13. التدفقات النقدية السنوية')
    sensitivity_assumptions = tables.get('sensitivityAssumptionsTable')
    if not isinstance(sensitivity_assumptions, list) or not sensitivity_assumptions:
        dynamic_rows = model.get('dynamicRows') if isinstance(model, dict) else {}
        if isinstance(dynamic_rows, dict) and isinstance(dynamic_rows.get('sensitivity'), list):
            sensitivity_assumptions = dynamic_rows.get('sensitivity')
    draw_data_table(sensitivity_assumptions, '14. تحليل الحساسية العام - الافتراضات')
    draw_data_table(tables.get('sensitivityTable'), '14. تحليل الحساسية العام - النتائج')
    clarifications = str(inputs.get('financialClarifications') or '').strip()
    if clarifications:
        draw_text('15. الإيضاحات', 12)
        draw_paragraph(clarifications)
    document.save(output_path)
    document.close()
    return output_path


def generate_financial_pdf(html, output_path, model=None, project_name='', min_text=200):
    last_error = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
            )
            try:
                page = browser.new_page()
                page.set_content(html, wait_until='load', timeout=45000)
                try:
                    page.evaluate('() => document.fonts && document.fonts.ready')
                except Exception:
                    pass
                page.pdf(
                    path=str(output_path),
                    format='A4',
                    landscape=True,
                    print_background=True,
                    margin={'top': '12mm', 'right': '12mm', 'bottom': '12mm', 'left': '12mm'},
                )
            finally:
                browser.close()
        if os.path.isfile(output_path) and _financial_pdf_has_text(output_path, min_text):
            return output_path
        last_error = RuntimeError('Playwright wrote an empty PDF')
    except Exception as error:
        last_error = error
        print(f'[FINANCIAL PDF] Playwright failed ({error}); falling back to PyMuPDF')
    # The model writer embeds the Arabic font itself, so it is the reliable engine on
    # hosts without Chromium. The MuPDF HTML engine relies on system fonts and writes
    # pages of empty table borders there, so it is only the last resort.
    if model is not None:
        try:
            generate_financial_pdf_from_model(project_name, model, output_path)
            if _financial_pdf_has_text(output_path, min_text):
                return output_path
            last_error = RuntimeError('Model renderer wrote a PDF with no text')
        except Exception as error:
            last_error = error
            print(f'[FINANCIAL PDF] model fallback failed ({error})')
    import fitz
    candidates = [_financial_pdf_plain_html(html), str(html or '')]
    for candidate in candidates:
        try:
            document = fitz.open('html', candidate.encode('utf-8'))
            try:
                document.save(output_path)
            finally:
                document.close()
            if os.path.isfile(output_path) and _financial_pdf_has_text(output_path, min_text):
                return output_path
        except Exception as error:
            last_error = error
            print(f'[FINANCIAL PDF] PyMuPDF html open failed ({error})')
    raise RuntimeError(str(last_error or 'Could not write financial PDF'))
