# ── Deterministic task executors ────────────────────────────────────
# Code ops that never call the worker model (watermark, table/color edits,
# image/logo ops, duplicate, find/replace, font, ui) plus the executor
# map the runner dispatches through. Shared exec namespace — no imports.

def _agent_exec_code(task, ctx, session, feedback=''):
    """Deterministic ops that never call the worker model."""
    slides = ctx['slides']
    op = task['op']
    params = task.get('params') or {}
    indexes = task.get('_indexes') or []
    changed, note = [], None

    if op == 'table_edit':
        # The grammar is defined on the user's own wording; the planner's
        # rephrased instruction routinely fails detection on purpose.
        request_text = str(ctx.get('message') or task['_instruction'] or '')
        detection = {'handled': False}
        try:
            detection = designer_chat_reliability.detect_table_edit_request(request_text)
        except Exception:
            pass
        # Blocks the grammar refuses on safety grounds (conditional wording,
        # ambiguity, emptying the table) stay refusals — a worker rewrite
        # must not smuggle the same delete past the gate.
        _TABLE_SAFETY_BLOCKS = {
            'negated_or_conditional_request', 'would_empty_table',
            'ambiguous_table_request', 'ambiguous_table_selector',
            'compound_table_request', 'missing_table_target',
            'malformed_table', 'nested_table_unsupported',
            'merged_cells_unsupported', 'non_rectangular_table',
            'column_layout_unsupported', 'no_table_in_slide',
            'table_not_found', 'ambiguous_table',
        }
        # Anything else the grammar saw but could not run — add/edit/cell/
        # merge/sort ops, fuzzy names, numbers it could not match — goes to
        # the worker carrying the user's original words.
        if detection.get('handled') and not detection.get('supported'):
            reason = str(detection.get('reason') or '')
            if reason in _TABLE_SAFETY_BLOCKS:
                arabic = _TABLE_PRECHECK_ARABIC_REASONS.get(reason, reason)
                return False, None, f'table_precheck:{arabic}', None
            return _agent_exec_edit(dict(task, op='edit', _instruction=request_text),
                                    ctx, session, feedback)
        note = None
        fuzzy_blocked = None
        safety_blocked = None
        for idx in indexes:
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            res = designer_chat_reliability.apply_table_delete_request(
                slide.get('html', ''), request_text)
            if isinstance(res, dict) and res.get('description'):
                note = res['description']
            if res.get('changed') and res.get('html'):
                slide['html'] = res['html']
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                changed.append(idx)
            elif isinstance(res, dict):
                reason = str(res.get('reason') or '')
                if reason in _TABLE_SAFETY_BLOCKS:
                    safety_blocked = reason
                elif reason and reason != 'not_a_table_edit':
                    fuzzy_blocked = reason
        if changed:
            return True, note, None, None
        if fuzzy_blocked and not safety_blocked:
            return _agent_exec_edit(dict(task, op='edit', _instruction=request_text),
                                    ctx, session, feedback)
        if safety_blocked:
            arabic = _TABLE_PRECHECK_ARABIC_REASONS.get(safety_blocked, safety_blocked)
            return False, None, f'table_precheck:{arabic}', None
        return False, note, 'table_unchanged', None

    if op == 'color_edit':
        request_text = str(ctx.get('message') or task['_instruction'] or '')
        refused = False
        for idx in indexes:
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            # apply_color_edit returns (html, message): html is the patched
            # slide, the unchanged original on a no-op, or None on a refusal
            # the grammar cannot express («غمّق الأزرق شوية»).
            new_html, color_msg = designer_chat_colors.apply_color_edit(
                slide.get('html', ''), request_text)
            if new_html is None:
                refused = True
                continue
            if new_html != slide.get('html', ''):
                slide['html'] = new_html
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                changed.append(idx)
        if changed:
            return True, color_msg or None, None
        if refused:
            # A refusal is a grammar limit, not an impossible request — the
            # worker can darken a color the table of literals cannot parse.
            return _agent_exec_edit(dict(task, op='edit', _instruction=request_text),
                                    ctx, session, feedback)
        return False, color_msg or None, 'color_unchanged', None

    if op == 'watermark':
        action = str(params.get('action') or 'apply').lower()
        watermark_url = str(ctx['branding'].get('watermark_path') or '').strip()
        if action == 'apply' and not watermark_url:
            return False, 'لا توجد علامة مائية مرفوعة في إعدادات الشركة.', 'watermark_missing', None
        only_white = bool(params.get('only_white'))
        try:
            opacity = float(params.get('opacity', 0.045))
        except (TypeError, ValueError):
            opacity = 0.045
        try:
            width = int(params.get('width_px', 480))
        except (TypeError, ValueError):
            width = 480
        for idx in indexes:
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            if only_white and not _is_white_or_light_slide(slide):
                continue
            html = slide.get('html', '')
            if action == 'remove':
                new_html = _remove_slide_watermark(html)
            elif action in ('show', 'hide'):
                new_html = _set_slide_watermark_visible(html, action == 'show', logo_url=watermark_url)
            else:
                new_html = _apply_slide_watermark(html, watermark_url, opacity=opacity, width_px=width)
            if new_html != html:
                slide['html'] = new_html
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                changed.append(idx)
        return (bool(changed), None, 'watermark_unchanged' if not changed else None, None)

    if op == 'insert_attached_image':
        uris = ctx.get('attached_uris') or []
        try:
            image_index = int(params.get('image_index') or params.get('imageIndex') or 1)
        except (TypeError, ValueError):
            image_index = 1
        if not uris or image_index < 1 or image_index > len(uris):
            return False, 'لا توجد صورة مرفقة بهذه الرسالة بالترتيب المطلوب.', 'attached_image_missing', None
        image_url = uris[image_index - 1]
        position = _designer_attached_image_position(ctx['message'], params)
        try:
            opacity = float(params.get('opacity', 0.12 if position == 'watermark' else 1.0))
        except (TypeError, ValueError):
            opacity = 0.12 if position == 'watermark' else 1.0
        try:
            width = int(params.get('width_px', params.get('widthPx', 480 if position == 'watermark' else 140)))
        except (TypeError, ValueError):
            width = 480 if position == 'watermark' else 140
        caption = str(params.get('caption') or '')[:160]
        title = str(params.get('title') or 'صورة مرفقة')[:160]
        if position == 'separate_slide':
            insert_at = (max(indexes) + 1) if indexes else len(slides)
            new_html = _build_designer_attached_slide_html(
                image_url, title=title, caption=caption, branding=ctx['branding'])
            try:
                new_html = resolve_designer_chat_placeholders(
                    new_html, ctx['project_data'], ctx['presentation_id'], ctx['tenant_id'],
                    ctx['creative_images'])
                new_html = slide_engine.finalize_designer_slide_html(
                    new_html, 'content', ctx['project_data'], ctx['branding'],
                    creative_images=ctx['creative_images'], tenant_id=ctx['tenant_id'],
                    slide_num=insert_at + 1, slide_title=title,
                    total_slides=len(slides) + 1, content_source='designer_attached_image',
                    allow_all_maps=True)
            except Exception as exc:
                print(f"[DESIGNER-AGENT] attached slide finalize failed: {exc}")
            slides.insert(min(insert_at, len(slides)), {
                'id': designer_agent_ids.new_slide_id(),
                'html': new_html, 'title': title, 'type': 'content',
                'content_source': 'designer_attached_image', 'section_key': '',
                '_designer_keep_html': True, 'is_custom': True})
            return True, f'وُضعت الصورة المرفقة في شريحة جديدة رقم {insert_at + 1}.', None, None
        for idx in indexes:
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            slide['html'] = _insert_designer_attached_image(
                slide.get('html', ''), image_url, position=position,
                opacity=opacity, width_px=width, caption=caption)
            slide['_designer_keep_html'] = True
            slide['is_custom'] = True
            changed.append(idx)
        return (bool(changed), None, 'image_unchanged' if not changed else None, None)

    if op == 'insert_map':
        map_type = str(params.get('map_type') or 'overview').lower()
        map_url = (_approved_canonical_map_url(map_type, ctx['project_data'], ctx['creative_images'])
                   or _latest_canonical_map_url(map_type, ctx['project_data'], ctx['creative_images']))
        if not map_url:
            return False, 'لا توجد خريطة معتمدة من هذا النوع.', 'map_missing', None
        _map_project = ctx.get('project_data') or {}
        marks = _persisted_map_source_marks(
            ctx['tenant_id'], presentation_id=ctx['presentation_id'],
            draft_id=_map_project.get('draftId') or _map_project.get('draft_id'))
        for idx in indexes:
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            new_html, applied = _replace_slide_with_approved_map(
                slide.get('html', ''), map_type, map_url, marks)
            if applied:
                slide['html'] = new_html
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                changed.append(idx)
        return (bool(changed), None, 'map_unchanged' if not changed else None, None)

    if op == 'update_image':
        token = str(params.get('asset') or '').strip()
        assets = _designer_image_assets(ctx['creative_images'])
        url = _designer_image_asset_url(token, assets)
        if not url:
            return False, 'الأصل البصري المطلوب غير موجود في المشروع.', 'asset_missing', None
        image_index = params.get('image_index') or params.get('imageIndex')
        for idx in indexes:
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            new_html, applied = _replace_slide_image_with_asset(
                slide.get('html', ''), url, token, image_index=image_index)
            if applied:
                slide['html'] = new_html
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                changed.append(idx)
        return (bool(changed), None, 'image_unchanged' if not changed else None, None)

    if op == 'image_descriptions':
        descriptions = designer_chat_reliability.collect_image_descriptions(
            ctx['project_data'], ctx['creative_images'])
        for idx in indexes:
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            updated, count, _added = designer_chat_reliability.add_missing_image_descriptions(
                slide.get('html', ''), descriptions)
            if count:
                slide['html'] = updated
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                changed.append(idx)
        return (bool(changed), None, 'no_missing_descriptions' if not changed else None, None)

    if op == 'team_logo':
        instruction = task['_instruction'] or 'أضف شعار الفريق إلى هذه الشريحة باستخدام توكن ##TEAM_LOGO_1##.'
        return _agent_exec_edit(dict(task, op='edit', _instruction=instruction), ctx, session, feedback)

    if op == 'company_logo_panel':
        instruction = task['_instruction'] or 'أضف لوحة شعار الشركة باستخدام توكن ##LOGO## / ##PROJECT_LOGO## حسب المتاح.'
        return _agent_exec_edit(dict(task, op='edit', _instruction=instruction), ctx, session, feedback)

    if op == 'duplicate':
        # In-place copy after each selected slide, deepest index first so the
        # originals keep their positions; the clone gets a fresh stable id.
        for idx in sorted(indexes, reverse=True):
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            clone = copy.deepcopy(slide)
            clone['id'] = designer_agent_ids.new_slide_id()
            clone['title'] = (str(slide.get('title') or '').strip() or f'شريحة {idx + 1}') + ' (نسخة)'
            slides.insert(min(idx + 1, len(slides)), clone)
            changed.append(idx)
        if not changed:
            return False, None, 'no_target_slide', None
        return True, f'كُررت {len(changed)} شريحة في الموضع التالي لأصلها.', None, None

    if op == 'find_replace':
        frm = str(params.get('from') or params.get('find') or '').strip()
        to = str(params.get('to') or params.get('replace') or '')
        if not frm:
            return False, None, 'missing_replace_target', None
        for idx in indexes:
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            html = slide.get('html', '')
            # Text nodes only — a replace that also rewrites attribute values
            # (classes, urls, data-*) would corrupt markup.
            chunks = re.split(r'(<[^>]*>)', html)
            for i in range(0, len(chunks), 2):
                if frm in chunks[i]:
                    chunks[i] = chunks[i].replace(frm, to)
            new_html = ''.join(chunks)
            if new_html != html:
                slide['html'] = new_html
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                changed.append(idx)
        return (bool(changed), (f'استُبدل «{frm[:60]}» في {len(changed)} شريحة.' if changed else None),
                'find_replace_not_found' if not changed else None, None)

    if op == 'font_edit':
        font = str(params.get('font') or '').strip()
        if not font:
            # «غيّر الخط لـ Cairo» — the name trails the font word.
            match = re.search(r'خط[ةه]?[^\w\s]*\s*(?:إلى|الى|لـ|ل|to)\s*["\']?([\w\s\'".+-]+?)["\']?\s*(?:[.。،,]|$)',
                              str(ctx.get('message') or ''), re.IGNORECASE)
            font = (match.group(1).strip() if match else '')[:60]
        if not font:
            return False, None, 'missing_replace_target', None
        def _font_sub(match):
            suffix = ' !important' if 'important' in match.group(2).lower() else ''
            return match.group(1) + "'" + font + "'" + suffix
        for idx in indexes:
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            html = slide.get('html', '')
            new_html = re.sub(
                r'(font-family\s*:\s*)([^;}]+)', _font_sub, html, flags=re.IGNORECASE)
            if new_html != html:
                slide['html'] = new_html
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                changed.append(idx)
        return (bool(changed), (f'تغيّر الخط إلى {font} في {len(changed)} شريحة.' if changed else None),
                'font_unchanged' if not changed else None, None)

    if op == 'ui':
        # Interface actions the chat can trigger client-side; the deck is
        # untouched and the frontend executes the action after apply.
        action = str(params.get('action') or '').strip().lower()
        if action not in ('undo', 'save', 'export', 'goto'):
            return False, None, 'unsupported_op', None
        task['_ui'] = {'action': action}
        if action == 'goto':
            if not indexes:
                return False, None, 'missing_slide', None
            task['_ui']['index'] = min(indexes)
            return True, f'انتقل للشريحة {min(indexes) + 1}.', None, None
        label = {'undo': 'تراجع عن آخر تعديل', 'save': 'حفظ العرض',
                 'export': 'تصدير العرض'}[action]
        return True, f'سينفَّذ إجراء «{label}» في الواجهة.', None, None

    return False, None, f'unknown_code_op:{op}', None


def _agent_exec_financial_chart(task, ctx, session, feedback=''):
    """A financial chart (waterfall & co.) is content work: same surgical
    worker call, with the chart contract spelled out in the instruction."""
    params = task.get('params') or {}
    chart_type = str(params.get('chart_type') or params.get('chart') or 'waterfall')
    instruction = (
        f'أنشئ في هذه الشريحة مخططًا ماليًا احترافيًا من نوع {chart_type} '
        '(جدول أعمدة مقارنة أو waterfall برسوم SVG/HTML نظيفة) من أرقام بيانات '
        'المشروع المالية — الإيرادات والتكاليف والصافي. حافظ على كل نص ورقم '
        'وصورة موجود في الشريحة، وضع المخطط في المساحة المناسبة دون تغطية أي '
        'عنصر، والتزم بألوان الهوية دون أي إيموجي أو أيقونات.')
    sub = dict(task, op='financial_chart', _instruction=instruction)
    return _agent_exec_edit(sub, ctx, session, feedback)


_EXECUTORS = {
    'edit': _agent_exec_content_edit, 'redesign': _agent_exec_edit, 'rewrite': _agent_exec_edit,
    'split': _agent_exec_split, 'restructure': _agent_exec_restructure,
    'create': _agent_exec_create, 'delete': _agent_exec_delete, 'move': _agent_exec_move,
    'generate_image': _agent_exec_generate_image, 'renumber': _agent_exec_renumber,
    'financial_chart': _agent_exec_financial_chart,
}

