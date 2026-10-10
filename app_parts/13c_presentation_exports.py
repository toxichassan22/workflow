def _export_html_from_slides(slides_data):
    """Join the deck for export, making sure every entry contributes exactly one page.

    Joining the stored html and hoping for the best is how a 50-slide deck exported as 25 pages
    with nothing to point at. Each entry is inspected on its own: an entry whose html carries no
    root `.slide` element is wrapped in one (it would otherwise print as loose content sharing a
    neighbour's page), and an entry carrying several is reported. The notes are logged and returned
    with the error, so the failure names the slide instead of only counting.
    """
    from design_templates import extract_slide_elements

    pieces = []
    empty = []
    wrapped = []
    multiple = []
    for index, item in enumerate(slides_data if isinstance(slides_data, list) else [], 1):
        html = str((item or {}).get('html') or '').strip() if isinstance(item, dict) else str(item or '').strip()
        title = str((item or {}).get('title') or '').strip() if isinstance(item, dict) else ''
        if not html:
            empty.append(index)
            continue
        roots = extract_slide_elements(html)
        if len(roots) == 1:
            pieces.append(roots[0])
        elif len(roots) > 1:
            multiple.append(index)
            pieces.extend(roots)
        else:
            wrapped.append(index)
            pieces.append(
                '<div class="slide" style="width:1280px;height:720px;position:relative;'
                'overflow:hidden;background:#fff;">' + html + '</div>'
            )
        if not html.strip():
            print(f'[EXPORT] slide {index} ({title}) has no html')

    notes = []
    if empty:
        notes.append('شرائح بلا محتوى: ' + '، '.join(str(n) for n in empty))
    if wrapped:
        notes.append('شرائح بلا إطار شريحة (أُضيف لها إطار): ' + '، '.join(str(n) for n in wrapped))
    if multiple:
        notes.append('شرائح تحتوي أكثر من شريحة: ' + '، '.join(str(n) for n in multiple))
    print(f'[EXPORT] entries={len(slides_data or [])} printable={len(pieces)}')
    return '\n'.join(pieces), notes


@app.route('/api/export', methods=['POST'])
@require_permission('export_files')
def api_export():
    """
    Export presentation to PDF or PPTX.
    Input: {format: 'pdf'|'pptx', slidesHtml: '...', slidesData: [...], projectName: '...'}
    """
    data = request.json or {}
    # Safety net: if __chunked_body reached route handler, perform inline reassembly
    if '__chunked_body' in data and isinstance(data.get('__chunked_body'), dict):
        meta = data['__chunked_body']
        fallback_id = str(meta.get('id', ''))
        fallback_total = meta.get('total')
        fallback_gzip = bool(meta.get('gzip'))
        chunk_dir = _body_chunk_dir(fallback_id)
        if chunk_dir and os.path.isdir(chunk_dir) and isinstance(fallback_total, int) and (1 <= fallback_total <= 1024):
            try:
                parts = []
                for i in range(fallback_total):
                    with open(os.path.join(chunk_dir, f'{i}.part'), 'rb') as part_fh:
                        parts.append(part_fh.read())
                raw = b''.join(parts)
                if fallback_gzip:
                    import gzip as _gzip
                    raw = _gzip.decompress(raw)
                data = json.loads(raw.decode('utf-8'))
                import shutil as _shutil
                _shutil.rmtree(chunk_dir, ignore_errors=True)
                print(f"[EXPORT] Inline chunked body reassembly succeeded for {fallback_id}")
            except Exception as _fb_err:
                print(f"[EXPORT] Inline chunked body reassembly failed: {_fb_err}")
    fmt = data.get('format', 'pdf').lower()
    project_name = data.get('projectName', 'presentation')
    export_notes = []
    branding = db.get_branding(g.tenant_id)
    print(f"[EXPORT] format={fmt} tenant={g.tenant_id} font_family={branding.get('font_family')!r} font_file_path={branding.get('font_file_path')!r}")

    # Tenant-specific output directory
    tenant_output_dir = os.path.join(OUTPUT_DIR, g.tenant_id)
    os.makedirs(tenant_output_dir, exist_ok=True)

    try:
        if fmt == 'pdf':
            from exports.pdf_export import generate_pdf
            slides_html = data.get('slidesHtml', '')
            slides_data = data.get('slidesData', [])
            presentation_id = data.get('presentationId')
            project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
            pres = db.get_presentation(presentation_id, g.tenant_id) if presentation_id else None
            if pres and not _presentation_in_scope(pres):
                return jsonify({'error': 'Presentation not found'}), 404
            if pres and not project_data:
                try:
                    project_data = json.loads(pres.get('project_data') or '{}')
                except (TypeError, ValueError):
                    project_data = {}
            render_project_data = copy.deepcopy(project_data)
            _prepare_generation_logo_context(render_project_data, branding, g.tenant_id)

            # Fallback: load latest saved slides from DB
            if not slides_html and not slides_data and pres and pres.get('slides_data'):
                try:
                    loaded = pres['slides_data']
                    if isinstance(loaded, str):
                        loaded = json.loads(loaded)
                    slides_data = loaded if isinstance(loaded, list) else []
                except Exception as e:
                    print(f"[EXPORT] failed to load slides_data: {e}")

            if slides_data:
                slides_data = slide_engine.renumber_presentation_slides(
                    slides_data, branding=branding, project_data=render_project_data, tenant_id=g.tenant_id,
                    creative_images=_presentation_creative_images(render_project_data, g.tenant_id),
                )
                slides_html, export_notes = _export_html_from_slides(slides_data)
                if export_notes:
                    print('[EXPORT] ' + ' | '.join(export_notes))
            if not slides_html:
                return jsonify({'error': 'slidesHtml or slidesData is required for PDF export'}), 400

            safe_name = ''.join(c for c in project_name if c.isalnum() or c in '-_ ')[:50].strip() or 'presentation'
            pdf_path = os.path.join(tenant_output_dir, f"{safe_name}_{int(time.time())}.pdf")
            # The deck's own count, so a file that came out short is visible here too. This used to
            # log len(slides_html) — the character count — as the number of slides.
            slide_count = len(slides_data) if slides_data else slides_html.count('class="slide"')
            generate_pdf(slides_html, branding, pdf_path, g.tenant_id)
            relative_url = f'/outputs/{g.tenant_id}/{os.path.basename(pdf_path)}'
            # Which renderer wrote the file: 'chromium' / 'chromium-isolated' is the
            # faithful export, 'fitz-fallback' keeps the page count but shifts the
            # layout (white strip left, clipped right) when no browser runs on host.
            try:
                import generate_pdf_from_preview as _deck_renderer
                pdf_engine = getattr(_deck_renderer, 'LAST_PDF_ENGINE', '') or 'unknown'
            except Exception:
                pdf_engine = 'unknown'
            print(f'[EXPORT] engine={pdf_engine} pages={slide_count} file={os.path.basename(pdf_path)}')

            # Record export — d03: each produced file carries the content hash
            # it was rendered from, its regen policy and the billed run cost.
            export_content_hash = db._presentation_review_hash({
                'slides_data': slides_data if slides_data else slides_html,
                'project_data': project_data,
            })
            regen_policy, export_cost = _export_regen_policy(
                g.tenant_id, presentation_id, export_content_hash)
            export_id = db.create_export(
                presentation_id, g.tenant_id, 'pdf', pdf_path,
                content_hash=export_content_hash, cost_usd=export_cost,
                regen_policy=regen_policy)
            official = _export_is_official_row({
                'id': export_id, 'presentation_id': presentation_id,
                'content_hash': export_content_hash, 'file_path': pdf_path})
            if presentation_id:
                _record_change('presentation', presentation_id, 'تصدير',
                               [f'صُدّر العرض بصيغة PDF ({slide_count} شريحة)'])
            download_url = f'/api/exports/{export_id}/download' + ('' if official else '?draft=1')
            return jsonify({'success': True, 'url': download_url, 'exportId': export_id,
                            'format': 'pdf', 'engine': pdf_engine, 'officiallyApproved': official})

        elif fmt == 'pptx':
            from exports.pptx_export import generate_pptx
            slides_data = data.get('slidesData', [])
            presentation_id = data.get('presentationId')
            project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
            pres = db.get_presentation(presentation_id, g.tenant_id) if presentation_id else None
            if pres and not _presentation_in_scope(pres):
                return jsonify({'error': 'Presentation not found'}), 404
            if pres and not project_data:
                try:
                    project_data = json.loads(pres.get('project_data') or '{}')
                except (TypeError, ValueError):
                    project_data = {}

            # Fallback: load latest saved slides from DB
            if not slides_data and pres and pres.get('slides_data'):
                try:
                    loaded = pres['slides_data']
                    if isinstance(loaded, str):
                        loaded = json.loads(loaded)
                    slides_data = loaded if isinstance(loaded, list) else []
                except Exception as e:
                    print(f"[EXPORT] failed to load slides_data for PPTX: {e}")

            if not slides_data:
                return jsonify({'error': 'slidesData is required for PPTX export'}), 400
            slides_data = slide_engine.renumber_presentation_slides(
                slides_data, branding=branding, project_data=project_data, tenant_id=g.tenant_id,
                creative_images=_presentation_creative_images(project_data, g.tenant_id),
            )

            pptx_path = generate_pptx(slides_data, project_name, branding, tenant_output_dir, g.tenant_id)
            relative_url = f'/outputs/{g.tenant_id}/{os.path.basename(pptx_path)}'
            # Native python-pptx build: no browser involved, and generate_pptx
            # already refused a short file. The count travels with the response
            # the same way the PDF engine does.
            pptx_count = len(slides_data)
            print(f'[EXPORT] engine=pptx-native slides={pptx_count} file={os.path.basename(pptx_path)}')

            pptx_hash = db._presentation_review_hash({
                'slides_data': slides_data, 'project_data': project_data})
            regen_policy, export_cost = _export_regen_policy(
                g.tenant_id, data.get('presentationId'), pptx_hash)
            export_id = db.create_export(
                data.get('presentationId'), g.tenant_id, 'pptx', pptx_path,
                content_hash=pptx_hash, cost_usd=export_cost, regen_policy=regen_policy)
            official = _export_is_official_row({
                'id': export_id, 'presentation_id': data.get('presentationId'),
                'content_hash': pptx_hash, 'file_path': pptx_path})
            if data.get('presentationId'):
                _record_change('presentation', data['presentationId'], 'تصدير',
                               [f'صُدّر العرض بصيغة PPTX ({len(slides_data)} شريحة)'])
            download_url = f'/api/exports/{export_id}/download' + ('' if official else '?draft=1')
            return jsonify({'success': True, 'url': download_url, 'exportId': export_id,
                            'format': 'pptx', 'engine': 'pptx-native', 'slideCount': pptx_count,
                            'officiallyApproved': official})

        else:
            return jsonify({'error': f'Unsupported format: {fmt}. Use pdf or pptx'}), 400

    except Exception as e:
        print(f"[EXPORT ERROR] {e}")
        # The notes name which slides the deck could not print, so the failure is actionable
        # instead of being a page count the user cannot act on.
        message = str(e)
        if export_notes:
            message += ' — ' + '؛ '.join(export_notes)
        return jsonify({'error': message, 'notes': export_notes}), 500


@app.route('/api/exports', methods=['GET'])
@require_auth
def api_get_exports():
    """List all exports for the current tenant."""
    exports = db.get_exports(
        g.tenant_id, accessible_draft_ids=db.user_accessible_draft_ids(g.user_id, g.tenant_id))
    result = []
    for e in exports:
        result.append({
            'id': e['id'],
            'format': e['format'],
            'downloadUrl': f"/api/exports/{e['id']}/download",
            'createdAt': e.get('created_at'),
        })
    return jsonify({'success': True, 'exports': result})


def _export_content_cost(tenant_id, presentation_id):
    """The billed cost of the run that produced this presentation (d03)."""
    if not presentation_id:
        return 0.0
    try:
        row = db.get_db().execute(
            "SELECT amount_usd FROM tenant_ledger WHERE tenant_id = ? AND presentation_id = ? "
            "AND kind = 'debit' ORDER BY created_at DESC LIMIT 1",
            (tenant_id, presentation_id)).fetchone()
        return float(row['amount_usd']) if row else 0.0
    except Exception:
        return 0.0


def _export_regen_policy(tenant_id, presentation_id, content_hash):
    """d03: which content version an export carries, with the run's cost.

    'official' — the exported content is exactly what the final gate approved;
    'superseded' — the content drifted past the approved version and needs a
    new gate; 'draft' — the file never reached the final gate.
    """
    if not presentation_id:
        return 'draft', 0.0
    approval = db.latest_final_file_approval(tenant_id, presentation_id, status='approved')
    policy = 'draft'
    if approval and approval.get('request_hash'):
        policy = 'official' if approval['request_hash'] == content_hash else 'superseded'
    return policy, _export_content_cost(tenant_id, presentation_id)


def _export_is_official_row(export_row):
    """True when this export carries exactly the content the final gate approved.

    Three proofs, strongest first: the export's content hash matches the hash
    the approver reviewed; the export row is the one the stamp pinned; or the
    physical file still matches the stamped sha256.
    """
    presentation_id = export_row.get('presentation_id')
    if not presentation_id:
        return False
    approval = db.latest_final_file_approval(g.tenant_id, presentation_id, status='approved')
    if not approval:
        return False
    if export_row.get('content_hash') and approval.get('request_hash') \
            and export_row['content_hash'] == approval['request_hash']:
        return True
    if approval.get('stamped_export_id') and approval['stamped_export_id'] == export_row.get('id'):
        return True
    if approval.get('content_hash') and export_row.get('file_path'):
        path = export_row['file_path']
        if not os.path.isabs(path):
            path = os.path.join(app.root_path, path)
        return bool(db._file_sha256(path)) and db._file_sha256(path) == approval['content_hash']
    return False


@app.route('/api/exports/<export_id>/download', methods=['GET'])
@require_auth
def api_download_export(export_id):
    """Serve an export. Only officially approved files download without the
    draft marker — anything else needs the explicit ?draft=1 flag and ships
    with a DRAFT- filename prefix and an X-Draft-Mode header (t15-06).
    Financial study reports never enter the final-file approval flow, so the
    gate does not apply to them."""
    exported_file = db.get_export(export_id, g.tenant_id)
    if not exported_file:
        return jsonify({'error': 'Export not found'}), 404
    export_pres = db.get_presentation(exported_file['presentation_id'], tenant_id=g.tenant_id) \
        if exported_file.get('presentation_id') else None
    if export_pres and export_pres.get('draft_id'):
        accessible = db.user_accessible_draft_ids(g.user_id, g.tenant_id)
        if accessible is not None and export_pres['draft_id'] not in accessible:
            return jsonify({'error': 'Export not found'}), 404
    file_path = os.path.abspath(exported_file['file_path'])
    tenant_output_dir = os.path.abspath(os.path.join(OUTPUT_DIR, g.tenant_id))
    if os.path.commonpath([file_path, tenant_output_dir]) != tenant_output_dir or not os.path.isfile(file_path):
        return jsonify({'error': 'Export file unavailable'}), 404
    official = exported_file.get('format') == 'financial_pdf' or _export_is_official_row(exported_file)
    draft_requested = request.args.get('draft') in ('1', 'true')
    if not official and not draft_requested:
        return jsonify({'error': 'الملف غير معتمد نهائيًا — التنزيل الرسمي بعد الاعتماد فقط',
                        'error_code': 'final_approval_required'}), 403
    basename = os.path.basename(file_path)
    response = send_file(file_path, as_attachment=True,
                         download_name=basename if official else f'DRAFT-{basename}')
    if not official:
        response.headers['X-Draft-Mode'] = '1'
    return response
