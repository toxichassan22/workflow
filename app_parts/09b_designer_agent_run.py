# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Designer agent — task executors and runner (split of 09a for the 1,000-line rule)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Executors return (ok, reply, reason, after_htmls); after_htmls=None tells the
# runner to derive the result from the task's resolved indexes.

# ── Task executors ───────────────────────────────────────────────────────────

def _agent_exec_edit(task, ctx, session, feedback=''):
    """One scoped worker call per slide — partial success inside the task is
    kept and reported, a fully failed task returns the last worker reason."""
    indexes = task['_indexes']
    changed, replies, last_reason = [], [], None
    for idx in indexes:
        slide = slides_at(ctx, idx)
        if slide is None:
            continue
        before = slide.get('html', '')
        html, reply = _agent_worker_edit_slide(
            ctx, slide, idx, task['_instruction'], len(ctx['slides']),
            session, feedback, task.get('style_brief') or '')
        if html is None:
            last_reason = reply or ctx.get('agent_last_worker_reason') or 'worker_failed'
            continue
        if reply:
            replies.append(reply)
        if designer_chat_reliability.materially_changed(before, html, reply):
            slide['html'] = html
            slide['_designer_keep_html'] = True
            slide['is_custom'] = True
            extracted = slide_engine._extract_visual_concept_captions(html)
            if extracted:
                slide['captions'] = extracted
            changed.append(idx)
    if not changed:
        return False, None, last_reason or 'unchanged', None
    note = ' '.join(dict.fromkeys(r for r in replies if r)) or None
    if last_reason and note:
        note += f' (تعذرت بعض الشرائح: {str(last_reason)[:120]})'
    return True, note, None, None


def slides_at(ctx, idx):
    slides = ctx['slides']
    if 0 <= idx < len(slides) and isinstance(slides[idx], dict):
        return slides[idx]
    return None


def _agent_exec_split(task, ctx, session, feedback=''):
    """execute_structure keeps the deterministic split candidates and atomic
    preservation check; the model fallback now goes through the scoped worker
    instead of the full-context legacy editor."""
    slides = ctx['slides']
    idx = task['_indexes'][0]
    params = {'slide_number': idx + 1, 'instruction': task['_instruction']}
    if task.get('parts') is not None:
        params['parts'] = task['parts']
    elif (task.get('params') or {}).get('parts') is not None:
        params['parts'] = task['params']['parts']
    record, status = designer_chat_safety.execute_structure(
        'split_slide', params, slides, task['_instruction'],
        edit_slide=_agent_structure_edit(ctx, session, feedback,
                                         task.get('style_brief') or ''),
        reliability=designer_chat_reliability,
        carry_watermark=_carry_slide_watermark,
        progress=lambda p, m: ctx['report_progress'](p, m))
    ok = record.get('status') == 'success'
    after = [slides[j].get('html', '') for j in (record.get('indexes') or []) if j < len(slides)] if ok else None
    reason = record.get('reason')
    if not ok and ctx.get('agent_last_worker_reason'):
        reason = str(reason or '') + ':' + ctx['agent_last_worker_reason']
    return ok, status, reason, after


def _agent_exec_restructure(task, ctx, session, feedback=''):
    """Regroup a contiguous set of source slides into target_count via one
    scoped worker call, then the shared finalize pipeline."""
    slides = ctx['slides']
    indexes = task['_indexes']
    # The splice below replaces slides[lo..hi]: a non-contiguous selector would
    # silently delete slides that were never part of the task.
    lo = min(indexes)
    if sorted(indexes) != list(range(lo, max(indexes) + 1)):
        return False, None, 'non_contiguous_sources', None
    sources = [slides[i] for i in indexes]
    target = task.get('target_count') or (task.get('params') or {}).get('target_count')
    try:
        target = max(1, int(target))
    except (TypeError, ValueError):
        return False, None, 'invalid_target_count', None
    source_htmls = [s.get('html', '') for s in sources]
    brief = task.get('style_brief') or ''
    instruction = task['_instruction'] + (f'\nالموجز الأسلوبي: {brief}' if brief else '')
    try:
        produced, error = _agent_worker_restructure(
            ctx, sources, target, instruction, feedback)
    except Exception as exc:
        return False, None, f'generation_failed:{exc}', None
    if error or produced is None:
        return False, None, error or 'incomplete_result', None
    finalized = []
    try:
        for i, part in enumerate(produced):
            out = _agent_worker_finalize(
                str(part.get('html') or ''), source_htmls[0], task['_instruction'], ctx,
                slide_num=min(indexes) + i + 1,
                title=str(part.get('title') or sources[0].get('title') or ''),
                total=len(slides) - len(sources) + target,
                slide_type=sources[0].get('type', 'content'),
                content_source=sources[0].get('content_source') or sources[0].get('contentSource'))
            finalized.append({'title': str(part.get('title') or ''), 'html': out})
    except Exception as exc:
        return False, None, f'finalize_failed:{exc}', None
    part_htmls = [p['html'] for p in finalized]
    try:
        for html in part_htmls:
            designer_chat_safety.validate_single_slide(html)
        if target < len(sources):
            # Shrinking must summarize prose, so literal preservation is
            # impossible by construction — facts must survive instead.
            designer_chat_safety.require_facts_preserved(source_htmls, part_htmls)
        else:
            designer_chat_safety.require_preserved(source_htmls, part_htmls, target)
    except designer_chat_safety.StructureSafetyError as exc:
        return False, None, str(exc), None
    replacements = []
    for i, part in enumerate(finalized):
        replacement = copy.deepcopy(sources[0])
        replacement.update(title=part['title'] or sources[0].get('title') or '',
                           html=part['html'], _designer_keep_html=True, is_custom=True)
        if i:
            replacement['id'] = designer_agent_ids.new_slide_id()
            replacement['restructured_from'] = [s.get('id') for s in sources]
        replacements.append(replacement)
    slides[lo:max(indexes) + 1] = replacements
    return True, f'أعيدت هيكلة {len(sources)} شريحة إلى {target}.', None, part_htmls


def _agent_exec_create(task, ctx, session, feedback=''):
    slides = ctx['slides']
    params = {'title': task.get('title') or (task.get('params') or {}).get('title') or 'شريحة جديدة',
              'type': task.get('type') or (task.get('params') or {}).get('type') or 'content',
              'instruction': task['_instruction']}
    after = task.get('after')
    if isinstance(after, str) and after not in ('start', 'end'):
        by_id = {str(s.get('id')): i for i, s in enumerate(slides) if isinstance(s, dict)}
        if after in by_id:
            params['after'] = by_id[after] + 1
        else:
            return False, None, 'unknown_after_id', None
    elif after == 'start':
        params['position'] = 1
    record, status = designer_chat_safety.execute_structure(
        'create_slide', params, slides, task['_instruction'],
        edit_slide=_agent_structure_edit(ctx, session, feedback,
                                         task.get('style_brief') or ''),
        reliability=designer_chat_reliability,
        carry_watermark=_carry_slide_watermark,
        progress=lambda p, m: ctx['report_progress'](p, m))
    ok = record.get('status') == 'success'
    after = ([slides[record['index']].get('html', '')]
             if ok and isinstance(record.get('index'), int) and record['index'] < len(slides) else None)
    return ok, status, record.get('reason'), after


def _agent_exec_delete(task, ctx, session, feedback=''):
    slides = ctx['slides']
    indexes = sorted(task['_indexes'], reverse=True)
    if len(slides) - len(indexes) < 1:
        return False, None, 'cannot_delete_all', None
    for idx in indexes:
        slides.pop(idx)
    return True, f'حُذفت {len(indexes)} شريحة.', None, []


def _agent_exec_move(task, ctx, session, feedback=''):
    slides = ctx['slides']
    idx = task['_indexes'][0]
    slide = slides.pop(idx)
    after = task.get('after')
    if isinstance(after, str) and after not in ('start', 'end'):
        by_id = {str(s.get('id')): i for i, s in enumerate(slides) if isinstance(s, dict)}
        if after not in by_id:
            slides.insert(min(idx, len(slides)), slide)
            return False, None, 'unknown_after_id', None
        slides.insert(by_id[after] + 1, slide)
    elif after == 'start':
        slides.insert(0, slide)
    else:
        slides.append(slide)
    return True, 'نُقلت الشريحة.', None, []


def _agent_exec_code(task, ctx, session, feedback=''):
    """Deterministic ops that never call the worker model."""
    slides = ctx['slides']
    op = task['op']
    params = task.get('params') or {}
    indexes = task.get('_indexes') or []
    changed, note = [], None

    if op == 'table_edit':
        note = None
        for idx in indexes:
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            res = designer_chat_reliability.apply_table_delete_request(
                slide.get('html', ''), task['_instruction'] or ctx['message'])
            if isinstance(res, dict) and res.get('description'):
                note = res['description']
            if res.get('applied') and res.get('html'):
                slide['html'] = res['html']
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                changed.append(idx)
        return (bool(changed), note, 'table_unchanged' if not changed else None, None)

    if op == 'color_edit':
        request_text = task['_instruction'] or ctx['message']
        for idx in indexes:
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            res = designer_chat_colors.apply_color_edit(slide.get('html', ''), request_text)
            new_html = res.get('html') if isinstance(res, dict) else res
            if isinstance(new_html, str) and new_html != slide.get('html', ''):
                slide['html'] = new_html
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                changed.append(idx)
        return (bool(changed), None, 'color_unchanged' if not changed else None, None)

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
        marks = _persisted_map_source_marks(ctx['tenant_id'], presentation_id=ctx['presentation_id'])
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

    return False, None, f'unknown_code_op:{op}', None


def _agent_exec_generate_image(task, ctx, session, feedback=''):
    """Generate-then-place: image model call, persist, position insert."""
    slides = ctx['slides']
    params = task.get('params') or {}
    prompt = params.get('prompt') or task['_instruction'] or ctx['message']
    comp_name = str(params.get('component_name') or params.get('component') or '')
    if not comp_name:
        idx = task.get('_indexes', [ctx['current_index']])[0] if task.get('_indexes') else ctx['current_index']
        cur = slides_at(ctx, min(idx, len(slides) - 1)) or {}
        comps = (ctx['project_data'].get('interior_components')
                 or ctx['project_data'].get('components') or []) if isinstance(ctx['project_data'], dict) else []
        for c in comps:
            c_title = (c.get('name') or c.get('title') or '') if isinstance(c, dict) else ''
            if c_title and c_title in str(cur.get('title') or ''):
                comp_name = c_title
                break
    ref_images = _find_component_reference_image(comp_name or prompt, ctx['project_data'], ctx['creative_images'])
    image_ctx = _agent_usage_ctx(ctx, 'image')
    try:
        if ref_images:
            image_raw = call_image_api_with_references(prompt, references=ref_images, usage_ctx=image_ctx)
        else:
            image_raw = call_image_api(prompt, usage_ctx=image_ctx)
        image = persist_generated_image(image_raw, ctx['tenant_id'])
    except Exception as exc:
        return False, None, f'image_generation_failed:{exc}', None
    if not image:
        return False, 'تعذر توليد الصورة حاليًا — أعد المحاولة لاحقًا.', 'image_generation_failed', None
    position = str(params.get('position') or 'surgical')
    caption = comp_name or prompt[:60]
    caption_markup = (f'<div data-visual-media-caption="1" style="font-size:12px;color:#c5a059;'
                      f'margin-top:6px;font-weight:600;text-align:center;">{html_lib.escape(caption)}</div>')
    indexes = task.get('_indexes') or ([ctx['current_index']] if ctx['slides'] else [])
    changed = []
    if position in ('surgical', 'inline'):
        instruction_img = (
            f'أدرج الصورة الجديدة ({image}) في تصميم الشريحة كعنصر مرئي رئيسي متناسق '
            f'وجميل مع بطاقة شرح توضيحي ({caption_markup}). حافظ على جميع النصوص والبطاقات '
            'واضبط مكان الصورة باحترافية وتوازن بدون أي إيموجي أو أيقونات.')
        sub = dict(task, op='edit', _instruction=instruction_img)
        ok, reply, reason, _af = _agent_exec_edit(sub, ctx, session, feedback)
        if not ok:
            return False, reply, reason, None
        changed = sub.get('_indexes') or indexes
    else:
        for idx in indexes:
            slide = slides_at(ctx, idx)
            if slide is None:
                continue
            html = slide.get('html', '')
            if position == 'background':
                tag = (f'<div aria-hidden="true" style="position:absolute;inset:0;'
                       f"background-image:url('{image}');background-size:cover;"
                       'background-position:center;z-index:0;"></div>')
            else:
                side = 'right:40px' if position != 'left' else 'left:40px'
                tag = (f'<div style="position:absolute;{side};top:120px;width:38%;z-index:2;">'
                       f'<img src="{image}" alt="" style="width:100%;max-height:460px;'
                       f'object-fit:cover;border-radius:8px;">{caption_markup}</div>')
            slide['html'] = re.sub(r'(</div>\s*)$', tag + r'\1', html, count=1)
            slide['_designer_keep_html'] = True
            slide['is_custom'] = True
            changed.append(idx)
    if not changed:
        return False, None, 'no_target_slide', None
    if isinstance(ctx['creative_images'], dict):
        ctx['creative_images'].setdefault('generated', []).append(image)
    return True, None, None, None


_EXECUTORS = {
    'edit': _agent_exec_edit, 'redesign': _agent_exec_edit, 'rewrite': _agent_exec_edit,
    'split': _agent_exec_split, 'restructure': _agent_exec_restructure,
    'create': _agent_exec_create, 'delete': _agent_exec_delete, 'move': _agent_exec_move,
    'generate_image': _agent_exec_generate_image,
}


# ── Runner ───────────────────────────────────────────────────────────────────

def _agent_job_get(ctx):
    if not ctx.get('job_id'):
        return None
    try:
        return _read_job(_AGENT_JOB_NS, ctx['tenant_id'], ctx['job_id'])
    except Exception:
        return None


def _agent_job_checkpoint(ctx, tasks, slides):
    """Persist mid-run state so a process restart resumes instead of replanning."""
    if not ctx.get('job_id'):
        return
    try:
        job = _read_job(_AGENT_JOB_NS, ctx['tenant_id'], ctx['job_id']) or {}
        job['agentState'] = {
            'planId': ctx.get('plan_id'),
            'deckSignature': _agent_deck_signature(slides),
            'tasks': [{k: t.get(k) for k in ('n', 'op', 'slides', 'titles', 'instruction',
                                           'style_brief', 'params', 'parts', 'target_count',
                                           'after', 'title', 'type', 'exact_text',
                                           'status', 'failureReason')} for t in tasks],
            'slides': slides,
        }
        _write_job(_AGENT_JOB_NS, ctx['tenant_id'], ctx['job_id'], job)
    except Exception as exc:
        print(f"[DESIGNER-AGENT] checkpoint failed: {exc}")


def _agent_job_cancel_path(ctx):
    """Separate cancel marker file — a click can never be lost by a job-file
    rewrite racing it, because nothing on this path rewrites JSON."""
    job_id = str(ctx.get('job_id') or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{6,80}', job_id):
        return None
    return os.path.join(_job_dir(_AGENT_JOB_NS, ctx['tenant_id']), f'{job_id}.cancel')


def _agent_job_mark_cancelled(ctx):
    path = _agent_job_cancel_path(ctx)
    if not path:
        return False
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(str(time.time()))
        return True
    except OSError:
        return False


def _agent_job_clear_cancel(ctx):
    path = _agent_job_cancel_path(ctx)
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def _agent_job_cancelled(ctx):
    path = _agent_job_cancel_path(ctx)
    if path and os.path.isfile(path):
        return True
    job = _agent_job_get(ctx)
    return bool(isinstance(job, dict) and job.get('cancelRequested'))


def _designer_agent_run(tasks, ctx, session=None):
    """Execute tasks one by one. Successful work survives later failures."""
    slides = ctx['slides']
    executed = []
    cancelled = False
    billing_stopped = False
    total = len(tasks)
    measure = (session is not None and getattr(session, 'available', False))
    report = ctx['report_progress']
    # A stale marker from an earlier turn must not kill this run; a fresh click
    # during the run recreates it and is honored at the next task boundary.
    _agent_job_clear_cancel(ctx)

    for i, task in enumerate(tasks):
        n = task.get('n') or i + 1
        if cancelled or billing_stopped:
            task['status'] = 'skipped'
            task['failureReason'] = 'cancelled' if cancelled else 'billing_stopped'
            continue
        if _agent_job_cancelled(ctx):
            cancelled = True
            task['status'] = 'skipped'
            task['failureReason'] = 'cancelled'
            continue

        op = task['op']
        task['status'] = 'running'
        report(15 + int(70 * i / max(1, total)),
               f"مهمة {n}/{total}: {designer_agent_ops.OP_LABELS.get(op, op)}...",
               {'phase': 'agent', 'agentTask': n, 'tasks': [designer_agent_ops.public_task(t) for t in tasks]})

        selector = {'ids': task.get('slides') or []}
        indexes, sel_err = designer_agent_ops.resolve_selector(selector, slides, ctx['current_index'])
        if op in ('create',):
            indexes = indexes or []  # create resolves its own position
        elif not indexes:
            task['status'] = 'failed'
            task['failureReason'] = sel_err[0] if isinstance(sel_err, list) and sel_err else (sel_err or 'missing_slide')
            executed.append({'tool': f'agent_{op}', 'status': 'failed', 'task': n,
                             'reason': task['failureReason']})
            continue
        task['_indexes'] = indexes
        ctx['agent_last_worker_reason'] = None
        before_htmls = [slides[i].get('html', '') for i in indexes] if indexes else []
        task['_instruction'] = designer_agent_ops.instruction_for(task)

        executor = _EXECUTORS.get(op) or _agent_exec_code
        ok, reply, reason = False, None, None
        feedback = ''
        for attempt in range(_AGENT_TASK_ATTEMPTS):
            after_htmls = None
            # Executors mutate slides before verification runs; a rejected
            # attempt must leave the deck untouched (and retry from the
            # original slides, not from its own rejected output).
            deck_backup = [dict(s) if isinstance(s, dict) else s for s in slides]
            try:
                ok, reply, reason, after_htmls = executor(task, ctx, session, feedback)
            except Exception as exc:
                print(f"[DESIGNER-AGENT] task {n} ({op}) raised: {exc}")
                ok, reply, reason = False, None, f'exception:{type(exc).__name__}'
            if not ok:
                slides[:] = deck_backup
                retryable = (op == 'restructure' and attempt + 1 < _AGENT_TASK_ATTEMPTS
                             and str(reason or '').split(':', 1)[0] in (
                                 'facts_not_preserved', 'content_not_preserved',
                                 'incomplete_result', 'invalid_slide_html'))
                if retryable:
                    feedback = 'النتيجة رُفضت تحققاً: ' + str(reason)
                    continue
                break
            if after_htmls is None:
                after_htmls = [slides[j].get('html', '') for j in
                               sorted(task.get('_indexes') or indexes) if j < len(slides)]
            v_ok, v_reasons = designer_agent_ops.verify_task_result(op, before_htmls, after_htmls)
            if v_ok and measure and op in ('edit', 'redesign', 'rewrite', 'restructure', 'split'):
                m_indexes = sorted(task.get('_indexes') or indexes)
                for j in m_indexes:
                    if j >= len(slides):
                        continue
                    m_uri, m_report = session.render(slides[j].get('html', ''), screenshot=True)
                    if m_uri:
                        # The last slide designed this run is the consistency
                        # reference the next worker call sees (chatplan 3.6).
                        ctx['agent_style_ref_uri'] = m_uri
                    m_reasons = _measure_reasons(m_report) if m_report else []
                    if m_reasons:
                        v_ok, v_reasons = False, m_reasons
                        break
            if v_ok:
                break
            slides[:] = deck_backup
            reason = ';'.join(v_reasons) or 'verification_failed'
            if attempt + 1 < _AGENT_TASK_ATTEMPTS and op in ('edit', 'redesign', 'rewrite', 'restructure', 'split'):
                feedback = 'النتيجة رُفضت تحققاً: ' + reason
                continue
            ok = False
            break

        if ok:
            task['status'] = 'success'
            executed.append({'tool': f'agent_{op}', 'status': 'success', 'task': n,
                             'indexes': sorted(task.get('_indexes') or [])})
            if reply:
                task['reply'] = reply
        else:
            task['status'] = 'failed'
            task['failureReason'] = str(reason or 'unknown')[:400]
            executed.append({'tool': f'agent_{op}', 'status': 'failed', 'task': n,
                             'reason': task['failureReason']})
            if _is_billing_error_text(str(reason or '')) or _is_billing_error_text(str(reply or '')):
                billing_stopped = True
        _agent_job_checkpoint(ctx, tasks, slides)
        report(15 + int(70 * (i + 1) / max(1, total)),
               f"اكتملت المهمة {n}/{total} ({'نجاح' if ok else 'تعذّر'})",
               {'phase': 'agent', 'tasks': [designer_agent_ops.public_task(t) for t in tasks]})

    _agent_job_clear_cancel(ctx)
    return {'tasks': tasks, 'executed': executed, 'cancelled': cancelled,
            'billing_stopped': billing_stopped,
            'all_failed': not any(t.get('status') == 'success' for t in tasks)}


# Resolve the render-session helpers lazily: generate_pdf_from_preview imports
# playwright-heavy code paths that are optional in tests.
def _agent_render_session(branding, tenant_id):
    try:
        import generate_pdf_from_preview as renderer
        return renderer.SlideRenderSession(branding=branding, tenant_id=tenant_id)
    except Exception as exc:
        print(f"[DESIGNER-AGENT] render session unavailable: {exc}")

        class _NoRender:
            available = False
            error = str(exc)

            def render(self, html, screenshot=True):
                return None, None

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return _NoRender()


def _measure_reasons(report):
    try:
        import generate_pdf_from_preview as renderer
        return renderer.measure_report_reasons(report)
    except Exception:
        return []

