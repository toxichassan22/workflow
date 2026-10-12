def _financial_inputs(model):
    if not isinstance(model, dict):
        return {}
    inputs = model.get('inputs')
    return inputs if isinstance(inputs, dict) else model


def _financial_has_value(value):
    return value is not None and not (isinstance(value, str) and not value.strip())


def validate_financial_model(model):
    """Validate only fields activated by the financial model switches."""
    inputs = _financial_inputs(model)
    tables = model.get('tables', {}) if isinstance(model, dict) and isinstance(model.get('tables'), dict) else {}
    errors = []

    def required(key, label=None):
        if not _financial_has_value(inputs.get(key)):
            errors.append({'field': key, 'message': f'{label or key} مطلوب عند تفعيل هذا الخيار'})

    mode = inputs.get('unitRevenueMode') or 'mixed'
    sales_on = mode in {'sale', 'mixed'}
    rental_on = mode in {'rental', 'mixed'}
    if sales_on:
        required('salesStartYear', 'سنة بدء البيع')
        required('salesYears', 'عدد سنوات البيع')
    if rental_on:
        required('operationYears', 'عدد سنوات التشغيل')

    required('developmentYears', 'مدة التطوير')
    required('landArea', 'مساحة الأرض')
    required('builtUpAreaAbove', 'مسطحات البناء فوق الأرض')

    if inputs.get('financeEnabled') == 'yes':
        for key, label in (
            ('financeBase', 'أساس التمويل'), ('financingRate', 'نسبة التمويل'),
            ('financeArrangementFeeRate', 'رسوم ترتيب التمويل'),
            ('financeInterestMethod', 'طريقة احتساب الفائدة'), ('annualFinanceRate', 'معدل الفائدة'),
            ('financeDrawYears', 'سنوات سحب التمويل'),
            ('financeRepaymentStartYear', 'سنة بدء السداد'),
            ('financeRepaymentYears', 'سنوات السداد'),
        ):
            required(key, label)
        draw_rows = tables.get('financeDrawTable') or []
        repayment_rows = tables.get('financeRepaymentTable') or []
        if not draw_rows:
            errors.append({'field': 'financeDrawTable', 'message': 'خطة سحب التمويل مطلوبة عند تفعيل التمويل'})
        if not repayment_rows:
            errors.append({'field': 'financeRepaymentTable', 'message': 'خطة سداد التمويل مطلوبة عند تفعيل التمويل'})

    fund_on = inputs.get('fundEnabled') == 'yes'
    fees_on = fund_on and inputs.get('fundFeesEnabled') == 'yes'
    if fees_on:
        required('fundFeeBase', 'أساس أتعاب الصندوق')
        for key, label in (
            ('fundFeeStartYear', 'بداية احتساب أتعاب الصندوق'),
            ('fundFeeEndYear', 'نهاية احتساب أتعاب الصندوق'),
            ('fundFeeFrequency', 'دورية السداد'), ('fundFeeTiming', 'توقيت السداد'),
            ('fundFeeGrowthRate', 'نسبة نمو الأتعاب'),
        ):
            required(key, label)
        base = inputs.get('fundFeeBase')
        if base in {'fundCapital', 'investedCapital'}:
            required('fundCapitalInput', 'رأس مال الصندوق')
        elif base == 'nav':
            required('fundNavInput', 'صافي قيمة الأصول')
        elif base == 'fixed':
            required('fundFixedAnnualFee', 'الأتعاب السنوية الثابتة')

        if inputs.get('fundExitFeeEnabled') == 'yes':
            required('fundExitFeeBase', 'أساس أتعاب التخارج')
            if inputs.get('fundExitFeeBase') == 'fixed':
                required('fundExitFixedFee', 'مبلغ أتعاب التخارج')
            else:
                required('fundExitFeeRate', 'نسبة أتعاب التخارج')
        if inputs.get('performanceFeeEnabled') == 'yes':
            for key, label in (
                ('hurdleRate', 'الحد الأدنى للعائد'), ('hurdleMethod', 'طريقة الحد الأدنى'),
                ('performanceFeeRate', 'نسبة حافز الأداء'), ('performanceFeeBase', 'أساس حافز الأداء'),
                ('performanceCrystallizationYear', 'سنة احتساب حافز الأداء'),
            ):
                required(key, label)
            if inputs.get('catchupEnabled') == 'yes':
                required('catchupRate', 'نسبة Catch-up')
        additional_fees = tables.get('fundAdditionalFeesTable') or []
        for index, row in enumerate(additional_fees):
            if not isinstance(row, dict):
                continue
            if _financial_has_value(row.get('name')) and not _financial_has_value(row.get('value')):
                errors.append({'field': f'fundAdditionalFeesTable[{index}].value', 'message': 'قيمة الأتعاب الإضافية مطلوبة'})

    if rental_on and inputs.get('graceEnabled') == 'yes':
        for key, label in (
            ('graceMethod', 'طريقة فترة السماح'), ('graceScope', 'نطاق فترة السماح'),
            ('graceStartYear', 'سنة بداية السماح'), ('graceDurationMonths', 'مدة السماح'),
            ('graceDiscountRate', 'نسبة الخصم'),
        ):
            required(key, label)
        if inputs.get('graceScope') == 'selectedRevenue':
            required('graceRevenueId', 'الإيراد المشمول بالسماح')
        if inputs.get('graceMethod') == 'schedule' and not tables.get('graceScheduleTable'):
            errors.append({'field': 'graceScheduleTable', 'message': 'جدول خصومات فترة السماح مطلوب'})

    if inputs.get('externalEnabled') == 'yes' and not tables.get('externalTable'):
        errors.append({'field': 'externalTable', 'message': 'أضف بندًا خارجيًا واحدًا على الأقل'})

    if inputs.get('exitEnabled') == 'yes':
        if sales_on and inputs.get('saleExitMethod') not in (None, '', 'none'):
            required('saleExitYear', 'سنة التخارج البيعي')
        if rental_on and inputs.get('exitMethod') not in (None, '', 'none'):
            required('operatingExitYear', 'سنة التخارج التشغيلي')
            required('exitInput', 'مدخل التخارج التشغيلي')

    projection = model.get('projection') if isinstance(model, dict) else None
    if isinstance(projection, dict) and isinstance(projection.get('areaState'), dict) and projection['areaState'].get('valid') is False:
        errors.append({'field': 'componentsTable', 'message': 'مجموع مساحات مكونات المشروع يتجاوز مسطحات البناء فوق الأرض أو مساحة البدرومات أو المساحات المفتوحة للأرض'})
    parking_error = _financial_parking_model_error(model)
    if parking_error:
        errors.append(parking_error)
    return errors


def _financial_pdf_plain_html(html):
    """Drop huge embedded fonts so the PyMuPDF HTML parser can open the report."""
    text = str(html or '')
    text = re.sub(r'@font-face\s*\{.*?\}', '', text, flags=re.S)
    text = re.sub(r'src:\s*url\(data:font/[^)]+\);?', '', text, flags=re.I)
    text = re.sub(r'<style>.*?</style>', '<style>body{font-family:Tahoma,Arial,sans-serif;direction:rtl}table{width:100%;border-collapse:collapse;font-size:10px}th,td{border:1px solid #ccc;padding:4px;text-align:right}h1,h2,h3{color:#123B6D}</style>', text, flags=re.S)
    return text


def _financial_pdf_font():
    return maps_service.bundled_arabic_font_path()


def _financial_pdf_shape(text):
    """PyMuPDF places glyphs verbatim, so Arabic must be shaped and ordered first."""
    value = str(text or '')
    if not re.search(r'[\u0600-\u06ff]', value):
        return value
    return maps_service.shape_arabic_for_drawing(value)


def _financial_pdf_has_text(output_path, minimum=200):
    """A PDF of table borders with no glyphs is a failed render, not a report.

    The MuPDF HTML engine writes exactly that on hosts with no system Arabic font,
    and the old size-only check accepted it, so the client downloaded blank pages.
    """
    import fitz
    try:
        document = fitz.open(output_path)
    except Exception as error:
        print(f'[FINANCIAL PDF] cannot inspect the written file ({error})')
        return False
    try:
        return sum(len(page.get_text().strip()) for page in document) >= minimum
    finally:
        document.close()


@app.route('/api/financial-study/validate', methods=['POST'])
@require_permission('create_presentation')
def api_validate_financial_study():
    data = request.json or {}
    errors = validate_financial_model(data.get('financialModel') or data.get('model') or {})
    return jsonify({'success': not errors, 'validation': errors})


@app.route('/api/financial-study/export', methods=['POST'])
@require_auth
def api_export_financial_study():
    data = request.json or {}
    model = data.get('financialModel') or data.get('model') or {}
    errors = validate_financial_model(model)
    if errors:
        return jsonify({'success': False, 'error': 'لا يمكن تصدير الدراسة قبل استكمال المدخلات المطلوبة', 'validation': errors}), 400
    project_name = str(data.get('projectName') or 'الدراسة المالية').strip()[:120] or 'الدراسة المالية'
    tenant_output_dir = os.path.join(OUTPUT_DIR, g.tenant_id)
    os.makedirs(tenant_output_dir, exist_ok=True)
    safe_name = ''.join(c for c in project_name if c.isalnum() or c in '-_ ')[:50].strip() or 'financial-study'
    output_path = os.path.join(tenant_output_dir, f'{safe_name}_{int(time.time())}_financial.pdf')
    try:
        branding = db.get_branding(g.tenant_id) or {}
        report_html = build_financial_report_html(project_name, model, branding, g.tenant_id)
        generate_financial_pdf(report_html, output_path, model=model, project_name=project_name)
        export_id = db.create_export(data.get('presentationId') or None, g.tenant_id, 'financial_pdf', output_path)
        return jsonify({
            'success': True,
            'exportId': export_id,
            'format': 'financial_pdf',
            'fileName': os.path.basename(output_path),
            'url': f'/api/exports/{export_id}/download',
        })
    except Exception as error:
        print(f'[FINANCIAL PDF ERROR] {type(error).__name__}: {error!r}')
        if os.path.exists(output_path):
            os.unlink(output_path)
        detail = str(error).strip() or type(error).__name__
        return jsonify({'success': False, 'error': 'تعذر إنشاء ملف الدراسة المالية: ' + detail}), 500
