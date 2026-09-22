# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Dashboards and exportable reports (t55): client and company dashboard
# numbers plus the PDF report endpoints shared by admin and company.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ── t55: dashboards and exportable reports ───────────────────────────────────

@app.route('/api/dashboard', methods=['GET'])
@require_auth
def api_client_dashboard():
    """Client home numbers: lifecycle buckets, open work, month spend."""
    return jsonify({'success': True, 'dashboard': db.client_dashboard(g.tenant_id)})


@app.route('/api/dashboard/activity', methods=['GET'])
@require_auth
def api_client_dashboard_activity():
    """Company activity chart series scoped to the caller's tenant."""
    return jsonify({'success': True, 'trends': db.client_activity_trends(
        g.tenant_id,
        months=request.args.get('months'),
        from_month=request.args.get('from'),
        to_month=request.args.get('to'))})


@app.route('/api/company/dashboard', methods=['GET'])
@require_permission('company_settings')
def api_company_dashboard():
    """Company super-admin view: overdue approvals, speed, spend split."""
    return jsonify({'success': True, 'dashboard': db.company_admin_dashboard(g.tenant_id)})


_ADMIN_REPORTS = {
    'ledger': ('حركات الرصيد', db.ledger_report_rows),
    'tickets': ('تذاكر الدعم', db.tickets_report_rows),
}


def _report_pdf_html(title, headers, rows, generated_note):
    """A4-landscape RTL table document for the platform report exports."""
    from design_templates import _load_bundled_fonts
    font_face = ''
    bundled = (_load_bundled_fonts().get('TheSansArabic-Light')
               or _load_bundled_fonts().get('TheSansArabic-Bold'))
    if bundled:
        data, fmt = bundled
        mime = {'truetype': 'font/ttf', 'opentype': 'font/otf',
                'woff2': 'font/woff2', 'woff': 'font/woff'}.get(fmt, 'font/ttf')
        font_face = ("@font-face{font-family:'report-arabic';"
                     f"src:url(data:{mime};base64,{data}) format('{fmt}');"
                     "font-display:swap;}")
    head_cells = ''.join(f'<th>{html_lib.escape(str(h))}</th>' for h in headers)
    body_rows = ''.join(
        '<tr>' + ''.join(
            f'<td>{html_lib.escape("" if cell is None else str(cell))}</td>'
            for cell in row) + '</tr>'
        for row in rows)
    return (
        '<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8">'
        f'<style>{font_face}'
        "body{font-family:'report-arabic','IBM Plex Sans Arabic',Tahoma,Arial,sans-serif;"
        'direction:rtl;color:#1a1a1a;margin:0}'
        'h1{font-size:15px;color:#123B6D;margin:0 0 2px}'
        '.note{font-size:9px;color:#666;margin:0 0 10px}'
        'table{width:100%;border-collapse:collapse;font-size:9px}'
        'thead{display:table-header-group}'
        'th{background:#123B6D;color:#fff;border:1px solid #123B6D;padding:5px 6px;'
        'text-align:right;font-weight:600}'
        'td{border:1px solid #c9d2dc;padding:4px 6px;text-align:right;'
        'vertical-align:top;word-break:break-word}'
        'tr:nth-child(even) td{background:#f5f7fa}'
        '</style></head><body>'
        f'<h1>{html_lib.escape(title)}</h1>'
        f'<div class="note">{html_lib.escape(generated_note)}</div>'
        f'<table><thead><tr>{head_cells}</tr></thead>'
        f'<tbody>{body_rows}</tbody></table>'
        '</body></html>')


def _serve_report_pdf(report_name, tenant_id=None):
    """Shared admin/company report export: register rows -> RTL HTML -> PDF."""
    entry = _ADMIN_REPORTS.get(report_name)
    if not entry:
        return jsonify({'error': 'Unknown report'}), 404
    title, row_fn = entry
    try:
        limit = max(1, min(int(request.args.get('limit') or 5000), 5000))
    except (TypeError, ValueError):
        limit = 5000
    headers, rows = row_fn(
        tenant_id=tenant_id,
        from_date=request.args.get('from'),
        to_date=request.args.get('to'),
        limit=limit)
    note = datetime.now().strftime('%Y-%m-%d %H:%M') + f' — {len(rows)} صف'
    if len(rows) >= limit:
        note += ' — وصل التقرير الحد الأقصى للصفوف'
    report_html = _report_pdf_html(title, headers, rows, note)
    import tempfile
    fd, pdf_path = tempfile.mkstemp(prefix=f'{report_name}-report-', suffix='.pdf')
    os.close(fd)
    try:
        generate_financial_pdf(report_html, pdf_path, min_text=20)
        with open(pdf_path, 'rb') as handle:
            payload = handle.read()
    finally:
        try:
            os.unlink(pdf_path)
        except OSError:
            pass
    response = app.make_response(payload)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = \
        f'attachment; filename="{report_name}-report.pdf"'
    return response


@app.route('/api/admin/reports/<report_name>', methods=['GET'])
@require_admin
def api_admin_export_report(report_name):
    """t55: PDF export of the operational/financial registers."""
    return _serve_report_pdf(report_name, tenant_id=request.args.get('tenantId'))


@app.route('/api/company/reports/<report_name>', methods=['GET'])
@require_permission('company_settings')
def api_company_export_report(report_name):
    """t55: the company admin exports only their own registers."""
    if report_name not in ('ledger', 'tickets'):
        return jsonify({'error': 'Unknown report'}), 404
    return _serve_report_pdf(report_name, tenant_id=g.tenant_id)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == '__main__':
    print("=" * 60)
    print("  Real Estate Proposal Generator - GLM-First Architecture")
    print("=" * 60)
    print(f"  GLM Model: {GLM_MODEL}")
    print(f"  Image Model: {IMAGE_MODEL}")
    print(f"  Output Dir: {OUTPUT_DIR}")
    print("=" * 60)
    port = int(os.environ.get('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=True)
