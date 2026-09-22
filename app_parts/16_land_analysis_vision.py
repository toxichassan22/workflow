

def _call_land_analysis_model(system_prompt, user_content, max_tokens, min_tokens=None, truncation_ceiling=None, usage_ctx=None):
    """Call the vision model, lowering the reserved cap when the provider cannot afford it.

    Gateway failures (HTTP 5xx) are usually transient, so they are retried with the same cap
    before being surfaced. A response truncated at the cap is retried once with a higher cap,
    bounded by ``LAND_ANALYSIS_TRUNCATION_CEILING``. Returns ``(response, used_cap, error_message)``.
    """
    minimum = LAND_ANALYSIS_MIN_TOKENS if min_tokens is None else max(1, int(min_tokens))
    ceiling = LAND_ANALYSIS_TRUNCATION_CEILING if truncation_ceiling is None else max(1, int(truncation_ceiling))
    cap = max(minimum, int(max_tokens))
    message = ''
    res = None
    use_json_mode = True
    for attempt in range(3):
        res = call_openrouter_chat(
            system_prompt, user_content, temperature=None,
            max_tokens=cap, model=LAND_ANALYSIS_MODEL,
            response_format={'type': 'json_object'} if use_json_mode else None,
            provider=LAND_ANALYSIS_PROVIDER,
            usage_ctx=usage_ctx or _usage_ctx('land'),
        )
        if _has_chat_choices(res):
            choices = res.get('choices') or []
            finish_reason = choices[0].get('finish_reason') if choices and isinstance(choices[0], dict) else None
            higher_cap = min(ceiling, int(cap * 1.35))
            if finish_reason == 'length' and higher_cap > cap and attempt < 2:
                print(f'[LAND ANALYSIS] response truncated at cap={cap}; retrying with {higher_cap}')
                cap = higher_cap
                continue
            raw_text = _get_chat_response_text(res)
            if not str(raw_text).strip() and use_json_mode and attempt < 2:
                print('[LAND ANALYSIS] json_object returned empty content; retrying without response_format')
                use_json_mode = False
                continue
            return res, cap, ''
        message = _chat_error_message(res)
        affordable = _AFFORDABLE_TOKENS_RE.search(message)
        if affordable:
            # Leave a margin: the quoted allowance shrinks as the prompt itself consumes credit.
            retry_cap = max(minimum, int(int(affordable.group(1)) * 0.85))
            if retry_cap >= cap:
                break
            print(f'[LAND ANALYSIS] provider refused max_tokens={cap}; retrying with {retry_cap}')
            cap = retry_cap
            continue
        if use_json_mode and _JSON_MODE_BLOCK_RE.search(message) and attempt < 2:
            print(f'[LAND ANALYSIS] json_object blocked; retrying without response_format: {message}')
            use_json_mode = False
            continue
        if (_TRANSIENT_PROVIDER_RE.search(message) or _EMPTY_PROVIDER_RE.search(message)) and attempt < 2:
            print(f'[LAND ANALYSIS] transient provider response; retrying: {message}')
            time.sleep(2)
            continue
        break
    return res, cap, message


def _run_land_json_stage(stage_name, system_prompt, user_content, max_tokens, min_tokens, truncation_ceiling, usage_ctx=None):
    response, used_cap, provider_error = _call_land_analysis_model(
        system_prompt,
        user_content,
        max_tokens,
        min_tokens=min_tokens,
        truncation_ceiling=truncation_ceiling,
        usage_ctx=usage_ctx,
    )
    if not _has_chat_choices(response):
        return {}, used_cap, provider_error
    raw = _get_chat_response_text(response)
    parsed = parse_json_object(raw)
    if not parsed:
        return {}, used_cap, 'المرحلة ' + stage_name + ' أعادت JSON فارغًا أو غير صالح'
    print(f'[LAND ANALYSIS STAGE] {stage_name} cap={used_cap} chars={len(raw)}')
    return parsed, used_cap, ''


def _extract_land_site_facts(parsed, request_data=None):
    source = parsed.get('site_facts') if isinstance(parsed, dict) else None
    source = source if isinstance(source, dict) else (parsed if isinstance(parsed, dict) else {})
    request_data = request_data if isinstance(request_data, dict) else {}
    facts = {}
    for key in ('area_sqm', 'croquis_land_area', 'zoning_code', 'land_use', 'city',
                'project_type', 'axis_type', 'building_type', 'plot_number',
                'location_address', 'location_lat', 'location_lng'):
        value = source.get(key)
        if value in (None, ''):
            value = request_data.get(key)
        if value not in (None, ''):
            facts[key] = value
    return facts


def _compact_regulation_evidence(source_name, parsed):
    if not isinstance(parsed, dict):
        return {'source_file': source_name, 'evidence': {}}
    evidence = parsed.get('evidence') or parsed.get('regulation_evidence') or parsed.get('rules')
    if evidence is None:
        evidence = parsed
    return {'source_file': source_name, 'evidence': evidence}


def _decode_data_uri(data_uri):
    if not isinstance(data_uri, str) or not data_uri.strip():
        return None
    payload = data_uri.split(',', 1)[1] if ',' in data_uri else data_uri
    try:
        return base64.b64decode(payload, validate=False)
    except (TypeError, ValueError):
        return None


PDF_PAGE_SELECTION_TERMS = (
    ('إحداثيات التنظيم', 160), ('جدول إحداثيات', 145), ('إحداثيات', 100),
    ('الشرقيات', 75), ('الشماليات', 75), ('نقاط الحدود', 60),
    ('بموجب التنظيم', 150), ('الاتجاهات', 90), ('حدود', 55), ('الشوارع', 45), ('واجهات', 45),
    ('ارتدادات', 35), ('مواقف', 35), ('مداخل', 35), ('مخارج', 35),
    ('coordinates', 70), ('easting', 60), ('northing', 60),
)


def _rank_pdf_page(raw_text):
    text = str(raw_text or '').lower().replace('ـ', '')
    score = 0
    for term, weight in PDF_PAGE_SELECTION_TERMS:
        normalized = term.lower()
        if normalized in text or normalized[::-1] in text:
            score += weight
    return score


def _pixmap_to_pil(pixmap):
    from PIL import Image
    mode = 'RGBA' if pixmap.alpha else 'RGB'
    return Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples).convert('RGB')


def _encode_vision_image(image, quality, use_png=False):
    import io
    buffer = io.BytesIO()
    if use_png:
        image.save(buffer, format='PNG', optimize=True)
        mime = 'image/png'
    else:
        image.save(buffer, format='JPEG', quality=max(40, int(quality)), optimize=True)
        mime = 'image/jpeg'
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:{mime};base64,{encoded}', len(encoded)


def _detect_scan_rotation(image):
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return {
            'rotation': 0,
            'alternate_rotations': [],
            'method': 'default_no_numpy',
            'axis_gap': 0,
            'scores': {},
        }

    sample = image.convert('L')
    resampling = getattr(Image, 'Resampling', Image).LANCZOS
    sample.thumbnail((900, 900), resampling)
    gray = np.asarray(sample, dtype=np.uint8)
    if gray.ndim != 2 or min(gray.shape) < 16:
        return {
            'rotation': 0,
            'alternate_rotations': [],
            'method': 'default_small_image',
            'axis_gap': 0,
            'scores': {},
        }

    pad_y = max(1, int(gray.shape[0] * 0.02))
    pad_x = max(1, int(gray.shape[1] * 0.02))
    gray = gray[pad_y:-pad_y, pad_x:-pad_x]
    dark = gray < 200

    def projection_score(mask):
        height, width = mask.shape
        horizontal = 0.0
        vertical = 0.0
        for span, weight in ((2, 1.0), (3, 2.0), (4, 2.0), (5, 1.0), (7, 1.0)):
            if width >= span:
                run = np.ones((height, width - span + 1), dtype=bool)
                for offset in range(span):
                    run &= mask[:, offset:offset + width - span + 1]
                horizontal += weight * np.count_nonzero(run)
            if height >= span:
                run = np.ones((height - span + 1, width), dtype=bool)
                for offset in range(span):
                    run &= mask[offset:offset + height - span + 1, :]
                vertical += weight * np.count_nonzero(run)
        return float(horizontal - vertical) / max(1, mask.size)

    scores = {
        0: projection_score(dark),
        90: projection_score(np.rot90(dark, 1)),
        180: projection_score(np.rot90(dark, 2)),
        270: projection_score(np.rot90(dark, 3)),
    }
    base_score = (scores[0] + scores[180]) / 2
    sideways_score = (scores[90] + scores[270]) / 2
    axis_gap = sideways_score - base_score
    configured = os.environ.get('PDF_VISION_ROTATION', 'auto').strip().lower()
    if configured in {'0', '90', '180', '270'}:
        rotation = int(configured)
        alternate = []
        method = 'configured'
    elif axis_gap >= PDF_VISION_ROTATION_MIN_SCORE_GAP:
        rotation = 90 if scores[90] - scores[270] >= PDF_VISION_ROTATION_DIRECTION_MIN_SCORE_GAP else 270
        alternate = [270 if rotation == 90 else 90]
        method = 'projection_profile_sideways'
    elif axis_gap <= -PDF_VISION_ROTATION_MIN_SCORE_GAP:
        rotation = 180 if scores[180] - scores[0] >= PDF_VISION_ROTATION_DIRECTION_MIN_SCORE_GAP else 0
        alternate = []
        method = 'projection_profile_upright'
    else:
        rotation = 180 if scores[180] - scores[0] >= PDF_VISION_ROTATION_DIRECTION_MIN_SCORE_GAP else 0
        alternate = []
        method = 'projection_profile_ambiguous'

    return {
        'rotation': rotation,
        'alternate_rotations': alternate,
        'method': method,
        'axis_gap': round(axis_gap, 6),
        'scores': {str(key): round(value, 6) for key, value in scores.items()},
    }


def _render_pdf_clip_image(page, clip, scale, rotation):
    import fitz
    from PIL import Image
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    image = _pixmap_to_pil(pixmap)
    if rotation:
        resampling = getattr(Image, 'Resampling', Image).BICUBIC
        image = image.rotate(rotation, expand=True, resample=resampling)
    return image


def _pdf_tile_rects(rect):
    import fitz
    columns = max(1, PDF_VISION_TILE_COLUMNS)
    rows = max(1, PDF_VISION_TILE_ROWS)
    overlap = max(0.0, min(0.2, PDF_VISION_TILE_OVERLAP))
    result = []
    for row in range(rows):
        for column in range(columns):
            x0 = max(0.0, rect.width * column / columns - rect.width * overlap)
            y0 = max(0.0, rect.height * row / rows - rect.height * overlap)
            x1 = min(rect.width, rect.width * (column + 1) / columns + rect.width * overlap)
            y1 = min(rect.height, rect.height * (row + 1) / rows + rect.height * overlap)
            result.append((fitz.Rect(x0, y0, x1, y1), row, column))
    return result


def _alternate_tile_indexes(tile_count):
    columns = max(1, PDF_VISION_TILE_COLUMNS)
    priority = [index for index in range(tile_count) if index % columns == columns - 1]
    priority.extend(index for index in range(tile_count) if index not in priority)
    return priority


def _render_pdf_pages_for_vision(file_data, filename, dpi=PDF_VISION_DPI, max_pages=PDF_VISION_MAX_PAGES,
                                 budget=PDF_VISION_MAX_TOTAL_BYTES, diagnostics=None):
    """Render relevant PDF pages to image data URIs for vision models without OCR/text extraction.

    Raw 300 DPI PNG pages made multi-page deed books into a request so large that the
    provider's proxy dropped it with a bare non-JSON 502. Each page is therefore capped to
    ``PDF_VISION_MAX_EDGE`` pixels on its long side and encoded as JPEG, and when a document
    still exceeds its byte budget the whole document is re-rendered down a ladder of smaller
    edge caps and qualities until it fits.
    """
    pdf_bytes = _decode_data_uri(file_data)
    if not pdf_bytes:
        raise ValueError(f'Unable to decode PDF: {filename}')
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError('PyMuPDF is required for visual PDF analysis') from exc

    pages = []
    page_diagnostics = []
    truncated = False
    dpi_scale = max(1.0, float(dpi) / 72.0)
    ladder = (
        (PDF_VISION_MAX_EDGE, PDF_VISION_JPEG_QUALITY),
        (int(PDF_VISION_MAX_EDGE * 0.75), 80),
        (int(PDF_VISION_MAX_EDGE * 0.55), 72),
    )
    document = fitz.open(stream=pdf_bytes, filetype='pdf')
    try:
        page_count = len(document)
        limit = min(page_count, max(1, int(max_pages)))
        if page_count <= limit:
            selected_pages = list(range(page_count))
        else:
            scored_pages = []
            for index, page in enumerate(document):
                score = _rank_pdf_page(page.get_text())
                try:
                    score += min(3, len(page.find_tables().tables)) * 55
                except Exception:
                    pass
                if score > 0:
                    scored_pages.append((score, index))
            ranked_pages = sorted(scored_pages, key=lambda item: (-item[0], item[1]))
            selected_pages = [index for _, index in ranked_pages[:limit]]
            for index in range(page_count):
                if len(selected_pages) >= limit:
                    break
                if index not in selected_pages:
                    selected_pages.append(index)
            selected_pages.sort()
        truncated = len(selected_pages) < page_count
        tile_limit = min(len(selected_pages), max(0, PDF_VISION_TILE_MAX_PAGES))
        selection_order = {index: position for position, index in enumerate(selected_pages)}
        tile_candidates = sorted(
            selected_pages,
            key=lambda index: (-_rank_pdf_page(document[index].get_text()), selection_order[index])
        )
        tile_page_indexes = set(tile_candidates[:tile_limit])
        for edge_cap, quality in ladder:
            pages = []
            page_diagnostics = []
            total = 0
            for page_index in selected_pages:
                page = document[page_index]
                rect = page.rect
                orientation_scale = min(dpi_scale, 900.0 / max(rect.width, rect.height, 1.0))
                orientation_image = _render_pdf_clip_image(page, None, orientation_scale, 0)
                orientation = _detect_scan_rotation(orientation_image)
                scale = min(dpi_scale, float(edge_cap) / max(rect.width, rect.height, 1.0))
                full_image = _render_pdf_clip_image(page, None, scale, orientation['rotation'])
                full_data, full_size = _encode_vision_image(full_image, quality)
                total += full_size
                pages.append({
                    'page_number': page_index + 1,
                    'image_data': full_data,
                    'kind': 'full',
                    'rotation': orientation['rotation'],
                    'orientation_variant': 'primary',
                    'orientation_method': orientation['method'],
                    'axis_gap': orientation['axis_gap'],
                })
                if orientation['alternate_rotations']:
                    alternate_scale = min(dpi_scale, float(edge_cap * 0.65) / max(rect.width, rect.height, 1.0))
                    alternate_image = _render_pdf_clip_image(
                        page, None, alternate_scale, orientation['alternate_rotations'][0]
                    )
                    alternate_data, alternate_size = _encode_vision_image(
                        alternate_image, min(quality, 65)
                    )
                    total += alternate_size
                    pages.append({
                        'page_number': page_index + 1,
                        'image_data': alternate_data,
                        'kind': 'full',
                        'rotation': orientation['alternate_rotations'][0],
                        'orientation_variant': 'alternate',
                    })
                page_diagnostics.append({
                    'page': page_index + 1,
                    'rotation': orientation['rotation'],
                    'alternate_rotations': orientation['alternate_rotations'],
                    'method': orientation['method'],
                    'axis_gap': orientation['axis_gap'],
                })
                if page_index not in tile_page_indexes:
                    continue
                tile_rects = _pdf_tile_rects(rect)
                tile_edge = min(PDF_VISION_TILE_MAX_EDGE, max(1200, int(edge_cap)))
                tile_quality = min(quality, PDF_VISION_TILE_JPEG_QUALITY)
                for tile_index, (clip, row, column) in enumerate(tile_rects):
                    tile_scale = min(float(PDF_VISION_TILE_DPI) / 72.0,
                                     tile_edge / max(clip.width, clip.height, 1.0))
                    tile_image = _render_pdf_clip_image(page, clip, tile_scale, orientation['rotation'])
                    tile_data, tile_size = _encode_vision_image(tile_image, tile_quality)
                    total += tile_size
                    pages.append({
                        'page_number': page_index + 1,
                        'image_data': tile_data,
                        'kind': 'tile',
                        'tile_index': tile_index,
                        'tile_row': row,
                        'tile_column': column,
                        'rotation': orientation['rotation'],
                        'orientation_variant': 'primary',
                    })
                if orientation['alternate_rotations']:
                    alternate_indexes = _alternate_tile_indexes(len(tile_rects))
                    if budget < 8 * 1024 * 1024:
                        alternate_indexes = alternate_indexes[:PDF_VISION_ALTERNATE_TILE_LIMIT]
                    for tile_index in alternate_indexes:
                        clip, row, column = tile_rects[tile_index]
                        alternate_rotation = orientation['alternate_rotations'][0]
                        tile_scale = min(float(PDF_VISION_TILE_DPI) / 72.0,
                                         tile_edge / max(clip.width, clip.height, 1.0))
                        tile_image = _render_pdf_clip_image(page, clip, tile_scale, alternate_rotation)
                        tile_data, tile_size = _encode_vision_image(tile_image, tile_quality)
                        total += tile_size
                        pages.append({
                            'page_number': page_index + 1,
                            'image_data': tile_data,
                            'kind': 'tile',
                            'tile_index': tile_index,
                            'tile_row': row,
                            'tile_column': column,
                            'rotation': alternate_rotation,
                            'orientation_variant': 'alternate',
                        })
            if total <= max(1, int(budget)):
                break
        while total > max(1, int(budget)):
            removable = next((index for index in range(len(pages) - 1, -1, -1)
                              if pages[index].get('kind') == 'tile'
                              and pages[index].get('orientation_variant') == 'alternate'), None)
            if removable is None:
                removable = next((index for index in range(len(pages) - 1, -1, -1)
                                  if pages[index].get('kind') == 'full'
                                  and pages[index].get('orientation_variant') == 'alternate'), None)
            if removable is None:
                removable = next((index for index in range(len(pages) - 1, -1, -1)
                                  if pages[index].get('kind') == 'tile'), None)
            if removable is None:
                break
            total -= len(pages[removable].get('image_data', '').split(',', 1)[-1])
            pages.pop(removable)
    finally:
        document.close()

    if diagnostics is not None:
        diagnostics.update({
            'page_rotations': page_diagnostics,
            'rotated_page_count': sum(1 for item in page_diagnostics if item.get('rotation')),
            'tile_count': sum(1 for item in pages if item.get('kind') == 'tile'),
            'image_count': len(pages),
            'encoded_base64_bytes': sum(len(item.get('image_data', '').split(',', 1)[-1]) for item in pages),
        })
    return pages, page_count, truncated


def _prepare_document_vision_parts(document, budget=PDF_VISION_MAX_TOTAL_BYTES, diagnostics=None):
    """Prepare image parts for a document while preserving source/page metadata."""
    file_data = document.get('fileData') or ''
    filename = document.get('filename') or 'document'
    mime_type = str(document.get('mimeType') or '').lower()
    is_pdf = (
        'application/pdf' in mime_type
        or file_data.startswith('data:application/pdf')
        or filename.lower().endswith('.pdf')
    )
    if not is_pdf:
        if diagnostics is not None:
            diagnostics.update({'image_count': 1, 'tile_count': 0, 'rotated_page_count': 0})
        return [{
            'type': 'image_url',
            'image_url': {'url': file_data, 'detail': 'high'}
        }], [], 1, 'image_direct'

    vision_diagnostics = {}
    pages, page_count, truncated = _render_pdf_pages_for_vision(
        file_data, filename, budget=budget, diagnostics=vision_diagnostics)
    warnings = []
    if truncated:
        selected_numbers = ', '.join(dict.fromkeys(
            str(page.get('page_number')) for page in pages if page.get('kind') == 'full'
        ))
        warnings.append(f'{filename}: تم تحليل الصفحات الأكثر ارتباطًا ({selected_numbers}) من أصل {page_count}')
    rotated_pages = [item for item in vision_diagnostics.get('page_rotations', []) if item.get('rotation')]
    if rotated_pages:
        rotations = '، '.join(f"صفحة {item['page']}: {item['rotation']} درجة" for item in rotated_pages)
        warnings.append(f'{filename}: تم تصحيح اتجاه {rotations}')
    if diagnostics is not None:
        diagnostics.update(vision_diagnostics)
    expanded = []
    for page in pages:
        if page.get('kind') == 'tile':
            variant = 'بديلة' if page.get('orientation_variant') == 'alternate' else 'مصَححة'
            label = (
                f"قصاصة مكبرة {variant} من الصفحة {page['page_number']}، "
                f"الموضع {page.get('tile_index', 0) + 1}، اتجاه {page.get('rotation', 0)} درجة. "
                "استخدمها لقراءة الأرقام والجداول، وتجاهل النسخة البديلة إذا كانت مقلوبة."
            )
        else:
            variant = ' بديلة' if page.get('orientation_variant') == 'alternate' else ''
            label = (
                f"الصورة الكاملة{variant} للمستند {filename}، الصفحة {page['page_number']} من {page_count}، "
                f"اتجاه العرض {page.get('rotation', 0)} درجة. "
                "استخدم الصورة البديلة فقط إذا كانت الكتابة فيها أفقية أوضح."
            )
        expanded.extend([
            {'type': 'text', 'text': label},
            {'type': 'image_url', 'image_url': {'url': page['image_data'], 'detail': 'high'}},
        ])
    return expanded, warnings, page_count, 'pdf_rendered'


PARCEL_PLACEHOLDER_KEYS = (
    'plot_number', 'plan_number', 'subdivision_number', 'deed_number', 'deed_date',
    'north_direction', 'setbacks', 'building_ratio', 'building_ratio_coverage',
    'coverage_ratio', 'floor_area_ratio', 'table_floors', 'max_floors_height',
    'parking_requirements', 'entrances_exits_requirements', 'allowed_uses',
    'allowed_uses_restrictions', 'regulatory_constraints', 'land_use_status', 'summary',
)


def _normalize_parcel_scalar_fields(parcel, text_content=''):
    """Apply the shared scalar normalizers to a single parcel.

    Historically these rules only ran when the model skipped the ``parcels`` array, so the
    regex fallbacks and the numeric facade coercion never executed on the real code path.
    """
    parcel.pop('approved_floor_count', None)
    parcel.pop('approved_floors', None)
    parcel.pop('approved_coverage_ratio', None)
    for key in PARCEL_PLACEHOLDER_KEYS:
        if is_placeholder_value(parcel.get(key)):
            parcel[key] = ''

    fallback_text = f"{text_content} {json.dumps(parcel, ensure_ascii=False, default=str)}"

    raw_facades = parcel.get('facades_count')
    parcel['facades_count'] = normalize_facades_count(raw_facades, fallback_text)
    # Derive the facades from the directions table: only sides bordering a street count.
    street_sides = facade_directions_from_streets(parcel.get('directions'))
    if street_sides:
        parcel['facades_directions'] = street_sides
        parcel['facades_count'] = str(len(street_sides.split('،')))
    elif not parcel.get('facades_directions'):
        parcel['facades_directions'] = ''

    parcel['north_direction'] = normalize_north_direction(parcel.get('north_direction'))

    # Per-direction setbacks: the documents usually name them per compass side,
    # so an empty direction cell can be recovered from the setbacks narrative —
    # and a bare direction table can in turn feed the narrative field.
    _fill_direction_setbacks_from_text(parcel)
    if not str(parcel.get('setbacks') or '').strip():
        composed_setbacks = _compose_setbacks_from_directions(parcel.get('directions'))
        if composed_setbacks:
            parcel['setbacks'] = composed_setbacks

    if not parcel.get('deed_number'):
        deed_match = re.search(
            r'(?:صك|الصك|مرجع|المرجع|وثيقة)\s*(?:رقم)?\s*[:\s]*([0-9]{8,14})', fallback_text)
        if deed_match:
            parcel['deed_number'] = deed_match.group(1)

    if not parcel.get('deed_date'):
        parcel['deed_date'] = _find_document_date(fallback_text)

    if not parcel.get('plan_number'):
        plan_match = re.search(
            r'(?:رقم\s*)?(?:المخطط|مخطط)\s*(?:رقم)?\s*[:\s]*'
            r'([0-9\u0660-\u0669]{1,5}\s*/\s*[\u0621-\u064A0-9]{1,6}(?:\s*/\s*[\u0621-\u064A0-9]{1,6})?)',
            fallback_text)
        if plan_match:
            parcel['plan_number'] = re.sub(r'\s*', '', plan_match.group(1))

    merge_regulatory_access_requirements(parcel)
    if not parcel.get('building_ratio_coverage'):
        parcel['building_ratio_coverage'] = land_rule_text(parcel)
    if not parcel.get('building_ratio_setbacks'):
        parcel['building_ratio_setbacks'] = land_rule_text(parcel, include_setbacks=True)
    if not parcel.get('allowed_uses') and parcel.get('allowed_uses_restrictions'):
        parcel['allowed_uses'] = parcel['allowed_uses_restrictions']
    status, uses = split_land_use_status_text(parcel.get('allowed_uses'))
    if uses:
        parcel['allowed_uses'] = uses
    parcel['land_use_status'] = normalize_land_use_status(parcel.get('land_use_status')) or status
    strip_regulation_references_from_payload(parcel)
    return parcel


# Deed dates are usually Hijri and written in many shapes: "وتاريخ 1446/03/12هـ",
# "بتاريخ 12/03/1446", "تاريخ الصك 1446-03-12". Capture the date nearest a date keyword.
_DOCUMENT_DATE_PATTERNS = (
    r'(?:تاريخ\s*(?:الصك|صك|الإصدار|الاصدار|الاصدر))\s*[:\s]*([0-9\u0660-\u0669]{1,4}[/\-.][0-9\u0660-\u0669]{1,2}[/\-.][0-9\u0660-\u0669]{1,4})',
    r'(?:و?بتاريخ|و?تاريخ)\s*[:\s]*([0-9\u0660-\u0669]{1,4}[/\-.][0-9\u0660-\u0669]{1,2}[/\-.][0-9\u0660-\u0669]{1,4})',
    r'([0-9\u0660-\u0669]{1,4}[/\-.][0-9\u0660-\u0669]{1,2}[/\-.][0-9\u0660-\u0669]{1,4})\s*(?:هـ|هجري|هجرية)',
)

_ARABIC_INDIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


def _find_document_date(text):
    """Return the first date that looks like an issue date, normalised to Y/M/D."""
    for pattern in _DOCUMENT_DATE_PATTERNS:
        match = re.search(pattern, text or '')
        if not match:
            continue
        raw = match.group(1).translate(_ARABIC_INDIC_DIGITS)
        parts = re.split(r'[/\-.]', raw)
        if len(parts) != 3:
            continue
        # Whichever end holds the 4-digit group is the year.
        if len(parts[0]) == 4:
            year, month, day = parts
        else:
            day, month, year = parts
        try:
            return f'{int(year)}/{int(month):02d}/{int(day):02d}'
        except ValueError:
            continue
    return ''


def _coordinate_table_rows(table):
    if not isinstance(table, dict):
        return []
    for key in ('rows', 'points', 'items', 'data'):
        rows = table.get(key)
        if isinstance(rows, list) and rows:
            return rows
    return []


def _coordinate_table_title(table):
    if not isinstance(table, dict):
        return ''
    return ' '.join(str(table.get(key) or '') for key in (
        'table_name', 'table_title', 'title', 'name', 'label', 'source', 'الجدول', 'اسم الجدول'
    )).strip()


def _coordinate_table_entries(value):
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict) and _coordinate_table_rows(item)]
    if not isinstance(value, dict):
        return []
    if _coordinate_table_rows(value):
        return [value]
    entries = []
    for title, rows in value.items():
        if isinstance(rows, list) and rows:
            entries.append({'table_name': str(title), 'rows': rows})
    return entries


def _is_regulation_coordinate_table(table):
    title = _coordinate_table_title(table).casefold()
    return 'التنظيم' in title or 'regulation' in title


def _regulation_coordinate_rows_from_payload(payload):
    if not isinstance(payload, dict):
        return []
    for key in ('coordinate_tables', 'coordinates_tables', 'coordinate_table', 'coordinates_table', 'coordinatesTable'):
        for table in _coordinate_table_entries(payload.get(key)):
            if _is_regulation_coordinate_table(table):
                rows = _coordinate_table_rows(table)
                if rows:
                    return rows
    for key in ('regulation_coordinates', 'regulation_coordinates_table'):
        value = payload.get(key)
        if isinstance(value, dict):
            value = _coordinate_table_rows(value)
        if isinstance(value, list) and value:
            return value
    return []


def _coordinate_rows_from_payload(payload):
    if not isinstance(payload, dict):
        return []
    regulation_rows = _regulation_coordinate_rows_from_payload(payload)
    if regulation_rows:
        return regulation_rows
    for key in ('survey_coordinates', 'coordinates_table', 'coordinatesTable'):
        value = payload.get(key)
        if isinstance(value, dict):
            value = _coordinate_table_rows(value)
        if isinstance(value, list) and value:
            return value
    return []


def _coordinate_value(item, aliases):
    for key, value in item.items():
        normalized = str(key).strip().casefold()
        if normalized in aliases and value not in (None, ''):
            return str(value)
    return ''


def _normalize_survey_coordinate_rows(raw_coordinates, parcel_id):
    if isinstance(raw_coordinates, dict):
        raw_coordinates = raw_coordinates.get('rows') or raw_coordinates.get('points') or []
    if not isinstance(raw_coordinates, list):
        return []
    regulation_rows = []
    for item in raw_coordinates:
        if not isinstance(item, dict):
            continue
        metadata = ' '.join(str(item.get(key) or '') for key in (
            'source', 'table', 'table_name', 'coordinates_table_name', 'point', 'point_number', 'notes', 'الجدول'
        )).casefold()
        if 'التنظيم' in metadata or 'regulation' in metadata:
            regulation_rows.append(item)
    if regulation_rows:
        raw_coordinates = regulation_rows
    normalized = []
    for item in raw_coordinates:
        if not isinstance(item, dict):
            continue
        row_parcel_id = _coordinate_value(item, {'parcel_id', 'parcelid', 'plot_number', 'رقم القطعة'}) or str(parcel_id)
        point = _coordinate_value(item, {'point', 'point_number', 'pointnumber', 'رقم النقطة', 'النقطة'})
        if 'التنظيم' in point or 'regulation' in point.casefold():
            point_match = re.search(r'[0-9\u0660-\u0669]+', point)
            if point_match:
                point = point_match.group(0)
        eastings = _coordinate_value(item, {
            'eastings', 'easting', 'easting_coordinate', 'الشرقيات', 'الشرقي', 'شرقيات'
        })
        northings = _coordinate_value(item, {
            'northings', 'northing', 'northing_coordinate', 'الشماليات', 'الشمالي', 'شماليات'
        })
        source = _coordinate_value(item, {'source', 'المصدر'}) or 'regulation_table'
        if row_parcel_id or point or eastings or northings:
            normalized.append({
                'parcel_id': row_parcel_id,
                'point': point,
                'eastings': eastings,
                'northings': northings,
                'source': source,
            })
    return normalized


_DIRECTION_ALIASES = {
    'n': 'north', 'north': 'north', 'شمال': 'north', 'الشمال': 'north',
    's': 'south', 'south': 'south', 'جنوب': 'south', 'الجنوب': 'south',
    'e': 'east', 'east': 'east', 'شرق': 'east', 'الشرق': 'east',
    'w': 'west', 'west': 'west', 'غرب': 'west', 'الغرب': 'west',
}

# The model uses several key names for a direction's setback; accept the common
# ones so the value reaches the editable table column instead of being dropped.
_DIRECTION_SETBACK_KEYS = (
    'setback', 'setback_m', 'setback_text', 'setback_value', 'setbacks',
    'setback_requirement', 'setback_meters', 'الارتداد', 'ارتداد', 'ارتدادات',
)


def _normalize_direction_map(value):
    if isinstance(value, dict):
        entries = []
        for key, item in value.items():
            if isinstance(item, dict):
                entry = dict(item)
            else:
                entry = {'notes': str(item)}
            entry['direction'] = key
            entries.append(entry)
    elif isinstance(value, list):
        entries = [item for item in value if isinstance(item, dict)]
    else:
        entries = []
    directions = {}
    for entry in entries:
        direction_key = str(entry.get('direction') or entry.get('key') or '').strip().casefold()
        direction = _DIRECTION_ALIASES.get(direction_key)
        if direction:
            clean = dict(entry)
            clean.pop('direction', None)
            clean.pop('key', None)
            if not str(clean.get('setback') or '').strip():
                for alias in _DIRECTION_SETBACK_KEYS:
                    alias_value = clean.get(alias)
                    if str(alias_value or '').strip():
                        clean['setback'] = str(alias_value).strip()
                        break
            directions[direction] = clean
    for direction in ('north', 'south', 'east', 'west'):
        directions.setdefault(direction, {})
    return directions


_DIRECTION_SETBACK_TEXT_WORDS = (
    ('north', r'(?:الجهة\s+)?(?:ال)?شمالي?(?:ة)?'),
    ('south', r'(?:الجهة\s+)?(?:ال)?جنوبي?(?:ة)?'),
    ('east', r'(?:الجهة\s+)?(?:ال)?شرقي?(?:ة)?'),
    ('west', r'(?:الجهة\s+)?(?:ال)?غربي?(?:ة)?'),
)


def _fill_direction_setbacks_from_text(parcel):
    """Copy compass-named setbacks out of the free-text ``setbacks`` value into
    the matching direction rows — only where the model left the cell empty.
    The number must follow the direction word directly, so a boundary length
    («الشمال بطول 20م») is never mistaken for a setback.
    """
    if not isinstance(parcel, dict):
        return
    directions = parcel.get('directions')
    if not isinstance(directions, dict):
        return
    text = str(parcel.get('setbacks') or parcel.get('setback_requirements') or '').strip()
    if not text:
        return
    for direction, word in _DIRECTION_SETBACK_TEXT_WORDS:
        entry = directions.get(direction)
        if not isinstance(entry, dict) or str(entry.get('setback') or '').strip():
            continue
        match = re.search(
            word + r'\s*[:=\-–—]?\s*([0-9٠-٩]+(?:[.,][0-9]+)?\s*(?:متر|م\.?))',
            text)
        if match:
            entry['setback'] = match.group(1).strip()


def _compose_setbacks_from_directions(directions):
    """Flatten per-direction setbacks into the summary text used by the legacy
    «الارتدادات» field, so the two never disagree."""
    if not isinstance(directions, dict):
        return ''
    parts = []
    for direction, label in (('north', 'شمال'), ('south', 'جنوب'), ('east', 'شرق'), ('west', 'غرب')):
        entry = directions.get(direction)
        value = str((entry or {}).get('setback') or '').strip()
        if value:
            parts.append(f'{label}: {value}')
    return ' | '.join(parts)


def _directions_have_content(directions):
    if not isinstance(directions, dict):
        return False
    return any(
        any(str(value.get(key) or '').strip() for key in (
            'regulation_text', 'street_name', 'street_width_m', 'boundary_length_m', 'uses', 'notes', 'setback'
        )) if isinstance(value, dict) else bool(str(value or '').strip())
        for value in directions.values()
    )


def _apply_regulation_digest_fields(resp_json, reg_digest):
    """Force-fill verified numeric regulation fields from the digest.

    When the digest matched a zone, its values are the source of truth for the
    numeric requirements — the model narrates them but may not override them.
    Fields absent from the digest (e.g. conflicting values) are left untouched
    so an unverified number is never force-written.
    """
    fields = reg_digest.get('fields') or {}
    if not fields:
        return
    if reg_digest.get('conflicts'):
        existing = resp_json.get('conflicts')
        merged = list(existing) if isinstance(existing, list) else []
        for conflict in reg_digest['conflicts']:
            if conflict not in merged:
                merged.append(conflict)
        resp_json['conflicts'] = merged
    targets = []
    parcels = resp_json.get('parcels')
    if isinstance(parcels, list):
        targets.extend(p for p in parcels if isinstance(p, dict))
    if not targets:
        targets.append(resp_json)
    for target in targets:
        for key, value in fields.items():
            if key == 'allowed_uses':
                continue
            if value not in (None, '', []):
                target[key] = value


def _normalize_land_document_result(resp_json, text_content='', project_type=''):
    """Normalize multi-parcel document output while keeping legacy flat fields compatible."""
    if not isinstance(resp_json, dict):
        resp_json = {}
    raw_parcels = resp_json.get('parcels')
    if not isinstance(raw_parcels, list) or not raw_parcels:
        legacy = normalize_croquis_fields(resp_json, text_content)
        directions = _normalize_direction_map(
            legacy.get('directions') or resp_json.get('directions') or resp_json.get('directions_table')
        )
        survey_coordinates = _normalize_survey_coordinate_rows(
            _coordinate_rows_from_payload(resp_json), 'P-1'
        )
        parcel = {
            'parcel_id': 'P-1',
            'plot_number': legacy.get('plot_number_croquis', ''),
            'plan_number': legacy.get('plan_number', ''),
            'subdivision_number': legacy.get('subdivision_number', ''),
            'deed_number': legacy.get('deed_number', ''),
            'deed_date': legacy.get('deed_date', ''),
            'area_sqm': legacy.get('croquis_land_area'),
            'approved_financial_area_sqm': None,
            'facades_count': legacy.get('facades_count'),
            'facades_directions': legacy.get('facades_directions', ''),
            'directions': directions,
            'north_direction': legacy.get('north_direction', ''),
            'building_ratio_coverage': legacy.get('building_ratio_coverage', ''),
            'setbacks': legacy.get('setbacks', ''),
            'building_ratio': legacy.get('building_ratio', legacy.get('building_ratio_setbacks', '')),
            'coverage_ratio': legacy.get('coverage_ratio', ''),
            'floor_area_ratio': legacy.get('floor_area_ratio', ''),
            'table_floors': legacy.get('table_floors', ''),
            'building_ratio_setbacks': legacy.get('building_ratio_setbacks', ''),
            'max_floors_height': legacy.get('max_floors_height', ''),
            'allowed_uses': legacy.get('allowed_uses', legacy.get('allowed_uses_restrictions', '')),
            'regulatory_constraints': legacy.get('regulatory_constraints', ''),
            'land_use_status': legacy.get('land_use_status', ''),
            'allowed_uses_restrictions': legacy.get('allowed_uses_restrictions', ''),
                'coordinates': {'lat': None, 'lng': None, 'source': '', 'confidence': ''},
            'survey_coordinates': survey_coordinates,
            'confidence': {},
            'sources': [],
            'summary': legacy.get('land_and_building_summary', ''),
        }
        _normalize_parcel_scalar_fields(parcel, text_content)
        result = dict(legacy)
        result['parcels'] = [parcel]
        result['survey_coordinates'] = survey_coordinates
        result['source_priority'] = ['regulation_table', 'official_regulation', 'croquis', 'building_license']
        result['conflicts'] = resp_json.get('conflicts') if isinstance(resp_json.get('conflicts'), list) else []
        result['document_summary'] = result.get('land_and_building_summary', '')
        strip_regulation_references_from_payload(result)
        return apply_entered_land_use_status(result, project_type)

    normalized_parcels = []
    for index, raw in enumerate(raw_parcels):
        if not isinstance(raw, dict):
            continue
        directions = _normalize_direction_map(
            raw.get('directions') or raw.get('directions_table') or raw.get('regulation_directions')
        )
        if index == 0 and not _directions_have_content(directions):
            directions = _normalize_direction_map(
                resp_json.get('directions') or resp_json.get('directions_table')
            )
        parcel = dict(raw)
        parcel['parcel_id'] = str(raw.get('parcel_id') or raw.get('parcelId') or f'P-{index + 1}')
        parcel['survey_coordinates'] = _normalize_survey_coordinate_rows(
            _coordinate_rows_from_payload(raw), parcel['parcel_id']
        )
        parcel['directions'] = directions
        coords = raw.get('coordinates') if isinstance(raw.get('coordinates'), dict) else {}
        parcel['coordinates'] = {
            'lat': coords.get('lat'), 'lng': coords.get('lng'),
            'source': coords.get('source', ''), 'confidence': coords.get('confidence', '')
        }
        parcel['sources'] = raw.get('sources') if isinstance(raw.get('sources'), list) else []
        parcel['confidence'] = raw.get('confidence') if isinstance(raw.get('confidence'), dict) else {}
        _normalize_parcel_scalar_fields(parcel, text_content)
        normalized_parcels.append(parcel)

    if not normalized_parcels:
        return _normalize_land_document_result({}, text_content)
    result = dict(resp_json)
    result.pop('approved_floor_count', None)
    result.pop('approved_floors', None)
    result.pop('approved_coverage_ratio', None)
    result['parcels'] = normalized_parcels
    aggregate_coordinates = [row for parcel in normalized_parcels for row in parcel.get('survey_coordinates', [])]
    top_regulation_rows = _regulation_coordinate_rows_from_payload(resp_json)
    top_coordinates = _normalize_survey_coordinate_rows(
        top_regulation_rows or _coordinate_rows_from_payload(resp_json), normalized_parcels[0]['parcel_id']
    )
    if top_regulation_rows:
        aggregate_coordinates = top_coordinates
        normalized_parcels[0]['survey_coordinates'] = top_coordinates
    elif not aggregate_coordinates:
        aggregate_coordinates = top_coordinates
    result['survey_coordinates'] = aggregate_coordinates
    result['source_priority'] = ['regulation_table', 'official_regulation', 'croquis', 'building_license']
    result['conflicts'] = resp_json.get('conflicts') if isinstance(resp_json.get('conflicts'), list) else []
    # One canonical narrative: keep document_summary as a mirror for older stored drafts.
    summary = str(resp_json.get('land_and_building_summary') or resp_json.get('document_summary') or '').strip()
    if not summary:
        summary = str(normalized_parcels[0].get('summary') or '').strip()
    result['land_and_building_summary'] = summary
    result['document_summary'] = summary
    first = normalized_parcels[0]
    legacy_map = {
        'plot_number_croquis': first.get('plot_number', ''),
        'plan_number': first.get('plan_number', ''),
        'subdivision_number': first.get('subdivision_number', ''),
        'deed_number': first.get('deed_number', ''),
        'deed_date': first.get('deed_date', ''),
        'croquis_land_area': first.get('area_sqm'),
        'facades_count': first.get('facades_count'),
        'facades_directions': first.get('facades_directions', ''),
        'north_direction': first.get('north_direction', ''),
        'building_ratio_coverage': first.get('building_ratio_coverage') or land_rule_text(first),
        'setbacks': first.get('setbacks', ''),
        'building_ratio_setbacks': first.get('building_ratio_setbacks') or land_rule_text(first, include_setbacks=True),
        'max_floors_height': first.get('max_floors_height', ''),
        'allowed_uses': first.get('allowed_uses', ''),
        'regulatory_constraints': first.get('regulatory_constraints', ''),
        'land_use_status': first.get('land_use_status', ''),
        'allowed_uses_restrictions': first.get('allowed_uses_restrictions', ''),
    }
    for key, value in legacy_map.items():
        if value not in (None, ''):
            result.setdefault(key, value)
    strip_regulation_references_from_payload(result)
    return apply_entered_land_use_status(result, project_type)


def _build_land_extraction_diagnostics(result, document_processing=None):
    parcels = result.get('parcels') if isinstance(result, dict) else []
    parcels = parcels if isinstance(parcels, list) else []
    coordinate_rows = result.get('survey_coordinates') if isinstance(result, dict) else []
    if not isinstance(coordinate_rows, list):
        coordinate_rows = []
    first_parcel = parcels[0] if parcels and isinstance(parcels[0], dict) else {}
    if not coordinate_rows:
        coordinate_rows = first_parcel.get('survey_coordinates') if isinstance(first_parcel.get('survey_coordinates'), list) else []
    directions = first_parcel.get('directions') if isinstance(first_parcel.get('directions'), dict) else {}
    direction_values = 0
    for direction in ('north', 'south', 'east', 'west'):
        value = directions.get(direction)
        if isinstance(value, dict):
            has_value = any(str(value.get(key) or '').strip() for key in (
                'regulation_text', 'street_name', 'street_width_m', 'boundary_length_m', 'uses', 'notes'
            ))
        else:
            has_value = bool(str(value or '').strip())
        direction_values += int(has_value)
    complete_coordinates = sum(
        bool(str(row.get('eastings') or '').strip() and str(row.get('northings') or '').strip())
        for row in coordinate_rows if isinstance(row, dict)
    )
    conflicts = result.get('conflicts') if isinstance(result, dict) else []
    conflicts = conflicts if isinstance(conflicts, list) else []
    missing_tables = []
    if not coordinate_rows:
        missing_tables.append('إحداثيات التنظيم')
    if direction_values < 4:
        missing_tables.append('بموجب التنظيم')
    if not missing_tables:
        status = 'complete'
    elif coordinate_rows or direction_values:
        status = 'partial'
    else:
        status = 'empty'
    return {
        'status': status,
        'coordinates_rows': len(coordinate_rows),
        'coordinates_complete_rows': complete_coordinates,
        'directions_rows': 4,
        'directions_with_values': direction_values,
        'missing_tables': missing_tables,
        'conflict_count': len(conflicts),
        'coordinates_table_name': str(first_parcel.get('coordinates_table_name') or ''),
        'document_processing': document_processing if isinstance(document_processing, list) else [],
    }


LAND_ANALYSIS_SITE_CONTEXT_KEYS = (
    'location_address', 'location_detail', 'location_lat', 'location_lng', 'location_polygon',
    'city', 'district', 'main_roads', 'nearby_landmarks', 'nearby_landmarks_data',
    'city_landmarks', 'catchment_areas', 'population_density', 'population_density_source',
    'zoning_code', 'land_use',
)


def build_land_analysis_site_context(data, tenant_id, lat, lng):
    source = data.get('siteContext') if isinstance(data.get('siteContext'), dict) else {}
    context = {}
    for key in LAND_ANALYSIS_SITE_CONTEXT_KEYS:
        value = source.get(key)
        if value in (None, '', [], {}):
            value = data.get(key)
        if value not in (None, '', [], {}):
            context[key] = value
    context['location_address'] = data.get('locationAddress') or data.get('location_address') or context.get('location_address') or ''
    context['location_lat'] = lat
    context['location_lng'] = lng
    warnings = []
    needs_enrichment = any(context.get(key) in (None, '', [], {}) for key in (
        'location_detail', 'main_roads', 'nearby_landmarks', 'city_landmarks'))
    if data.get('includeMapContext') is True and needs_enrichment:
        try:
            # The croquis job runs on a worker thread, so the scope must be
            # opened here — a request-thread scope would never reach it, and
            # the Google calls below would record as unbillable NULL-tenant rows.
            site_maps_ctx = maps_service.maps_usage_ctx('site', tenant_id=tenant_id, data=data)
            with maps_service.maps_usage_scope(site_maps_ctx):
                enriched, nearby_items, *_rest, diagnostics = _collect_site_fields(context, tenant_id, lat, lng)
            for key, value in (enriched or {}).items():
                if value not in (None, '', [], {}) and context.get(key) in (None, '', [], {}):
                    context[key] = value
            if nearby_items and not context.get('nearby_landmarks_data'):
                context['nearby_landmarks_data'] = nearby_items
            warnings.extend(value for value in (
                (diagnostics or {}).get('nearby_landmarks_error'),
                (diagnostics or {}).get('nearby_landmarks_warning'),
                (diagnostics or {}).get('city_landmarks_error'),
                (diagnostics or {}).get('city_landmarks_warning'),
            ) if value)
        except Exception as error:
            warnings.append('تعذر استكمال بعض بيانات الموقع والخرائط: ' + str(error))
    return context, warnings


MARKET_STUDY_MAX_TOKENS = int(os.environ.get('MARKET_STUDY_MAX_TOKENS', '8000'))
MARKET_STUDY_MODEL = os.environ.get('MARKET_STUDY_MODEL') or GEMINI_TEXT_MODEL
_MARKET_JOB_LOCK = threading.Lock()
