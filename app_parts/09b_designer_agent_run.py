# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Designer agent — task executors and runner (split of 09a for the 1,000-line rule)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Executors return (ok, reply, reason, after_htmls); after_htmls=None tells the
# runner to derive the result from the task's resolved indexes.

# ── Task executors ───────────────────────────────────────────────────────────

def _agent_exec_edit(task, ctx, session, feedback='', color_request=None):
    """One scoped worker call per slide — partial success inside the task is
    kept and reported, a fully failed task returns the last worker reason.

    Slides inside one task are independent, so they run in a small bounded
    pool (vision renders stay serialized on ``ctx['_session_lock']`` — the
    Playwright session is not thread-safe). The cancel flag is honored
    between slide indexes, not only between tasks.
    """
    indexes = task['_indexes']
    changed, replies, last_reason = [], [], None
    cancelled = ctx.get('_is_cancelled') or (lambda: False)

    def work(idx):
        if cancelled():
            return idx, '', None, 'cancelled'
        slide = slides_at(ctx, idx)
        if slide is None:
            return idx, '', None, 'missing_slide'
        before = slide.get('html', '')
        html, reply = _agent_worker_edit_slide(
            ctx, slide, idx, task['_instruction'], len(ctx['slides']),
            session, feedback, task.get('style_brief') or '',
            color_request=color_request)
        return idx, before, html, reply

    workers = min(3, len(indexes))
    if workers <= 1:
        results = [work(idx) for idx in indexes]
    else:
        import concurrent.futures
        try:
            from flask import current_app, g
            flask_app = current_app._get_current_object()
        except Exception:
            flask_app = None
        tenant_id = ctx.get('tenant_id')

        def run_one(idx):
            if flask_app is None:
                return work(idx)
            with flask_app.app_context():
                from flask import g as thread_g
                thread_g.tenant_id = tenant_id
                return work(idx)

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_one, idx): idx for idx in indexes}
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append((futures[future], '', None, f'exception:{type(exc).__name__}'))
        results.sort(key=lambda item: indexes.index(item[0]))

    for idx, before, html, reply in results:
        slide = slides_at(ctx, idx)
        if slide is None or html is None:
            if reply != 'cancelled':
                last_reason = reply or ctx.get('agent_last_worker_reason') or last_reason
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
        if all(r[3] == 'cancelled' for r in results) and results:
            return False, None, 'cancelled', None
        return False, None, last_reason or 'unchanged', None
    note = ' '.join(dict.fromkeys(r for r in replies if r)) or None
    if last_reason and note:
        note += f' (تعذرت بعض الشرائح: {str(last_reason)[:120]})'
    return True, note, None, None


def _agent_exec_content_edit(task, ctx, session, feedback=''):
    """``edit``: its own raw wording — never the composed instruction with the
    style brief — may take the free deterministic color path first."""
    return _agent_exec_edit(task, ctx, session, feedback,
                            color_request=str(task.get('instruction') or '').strip() or None)


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
    if ok and record.get('warnings'):
        task['_warnings'] = list(record['warnings'])
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
    instruction += ('\nالنص النثري يجوز تلخيصه بشرط ألا يسقط معلومة أو معنى؛ '
                    'الأرقام والحقائق وصفوف الجداول والوسائط وخصائص البيانات تُحفظ كاملة.')
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
                content_source=sources[0].get('content_source') or sources[0].get('contentSource'),
                removed_elements=part.get('removed'))
            finalized.append({'title': str(part.get('title') or ''), 'html': out})
    except Exception as exc:
        return False, None, f'finalize_failed:{exc}', None
    part_htmls = [p['html'] for p in finalized]
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
    # Every source id except the position-first one's is gone from the deck —
    # the integrity check must not report them as silently dropped.
    task['_consumed_ids'] = [s.get('id') for s in sources[1:]]
    try:
        for html in part_htmls:
            designer_chat_safety.validate_single_slide(html)
        if target < len(sources):
            # Shrinking must summarize prose, so literal preservation is
            # impossible by construction — facts must survive instead.
            designer_chat_safety.require_facts_preserved(source_htmls, part_htmls)
        else:
            # Growing/regrouping may also condense prose — the owner accepts
            # summarized wording as long as the facts and the partition hold.
            designer_chat_safety.require_preserved(source_htmls, part_htmls, target,
                                                   summarize_ok=True)
    except designer_chat_safety.StructureSafetyError as exc:
        # The splice already stands in the deck — a warnable rejection lets the
        # runner keep it (applied with a warning) once retries are spent.
        return False, None, str(exc), part_htmls
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
    reason = record.get('reason')
    if ok and record.get('warnings'):
        task['_warnings'] = list(record['warnings'])
    if not ok and ctx.get('agent_last_worker_reason'):
        # Same as split: the worker's own failure (a provider or billing
        # error) hides behind execute_structure's generic incomplete_result.
        reason = str(reason or '') + ':' + ctx['agent_last_worker_reason']
    return ok, status, reason, after


def _agent_exec_delete(task, ctx, session, feedback=''):
    slides = ctx['slides']
    indexes = sorted(task['_indexes'], reverse=True)
    if len(slides) - len(indexes) < 1:
        return False, None, 'cannot_delete_all', None
    task['_consumed_ids'] = [slides[i].get('id') for i in indexes
                             if isinstance(slides[i], dict)]
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
    # The generation succeeded, but the run only counts if the asset actually
    # landed in slide HTML — a worker that described the image without an
    # <img> or a url() used to pass as success.
    placed = any(isinstance(slides_at(ctx, idx), dict)
                 and image in slides_at(ctx, idx).get('html', '')
                 for idx in (changed or indexes))
    if not placed:
        return False, 'تولّدت الصورة لكنها لم تُدرج في الشريحة.', 'image_not_placed', None
    if isinstance(ctx['creative_images'], dict):
        ctx['creative_images'].setdefault('generated', []).append(image)
    return True, None, None, None


def _agent_exec_renumber(task, ctx, session, feedback=''):
    """Rewrite the managed page counters on the targeted slides.

    The counter is chrome owned by the renumber pipeline, so a «أعد ترقيم»
    request can never legitimately go through a worker edit: changing the
    digits trips missing_numbers, and leaving them trips unchanged. This op
    fixes the number deterministically to the slide's live position — and a
    content slide that lost its counter gets the managed one back.
    """
    slides = ctx['slides']
    total = len(slides)
    changed = []
    for idx in task.get('_indexes') or []:
        slide = slides_at(ctx, idx)
        if slide is None:
            continue
        slide_type = str(slide.get('type') or 'content').strip().lower()
        before = str(slide.get('html') or '')
        html = slide_engine._rewrite_preserved_counter(before, slide_type, idx + 1, total)
        if (slide_type not in ('cover', 'closing', 'moodboard')
                and not re.search(r'\bdata-slide-counter\s*=', html, re.IGNORECASE)):
            counter = slide_engine._slide_counter_text(idx + 1, total)
            if counter:
                counter_html = '<span data-slide-counter="1" dir="ltr">' + counter + '</span>'
                if re.search(r'</footer\s*>', html, re.IGNORECASE):
                    html = re.sub(r'</footer\s*>', lambda m: counter_html + m.group(0),
                                  html, count=1, flags=re.IGNORECASE)
                else:
                    footer = ('<footer data-slide-footer="1" style="position:absolute;'
                              'bottom:8px;left:24px;">' + counter_html + '</footer>')
                    html = re.sub(r'(</div>\s*)$', lambda m: footer + m.group(0),
                                  html, count=1, flags=re.IGNORECASE)
        if html != before:
            slide['html'] = html
            slide['_designer_keep_html'] = True
            slide['is_custom'] = True
            changed.append(idx)
    if not changed:
        return False, 'ترقيم الشرائح الظاهر صحيح بالفعل.', 'renumber_unchanged', None
    return (True, f'أُعيد ترقيم {len(changed)} شريحة.', None,
            [slides[j].get('html', '') for j in changed])



# ── Runner ───────────────────────────────────────────────────────────────────

def _agent_job_get(ctx):
    if not ctx.get('job_id'):
        return None
    try:
        return _read_job(_AGENT_JOB_NS, ctx['tenant_id'], ctx['job_id'])
    except Exception:
        return None


def _pack_state_slides(slides):
    """zlib-packed deck for checkpoints — a full-deck JSON copy per task was
    writing megabytes to disk on every boundary."""
    import zlib
    try:
        raw = json.dumps(slides, ensure_ascii=False, separators=(',', ':'))
        return base64.b64encode(zlib.compress(raw.encode('utf-8'), 6)).decode('ascii')
    except Exception:
        return None


def _unpack_state_slides(agent_state):
    """Inverse of _pack_state_slides; older checkpoints stored 'slides' raw."""
    slides = agent_state.get('slides')
    if isinstance(slides, list) and slides:
        return slides
    packed = agent_state.get('slidesPacked')
    if not isinstance(packed, str) or not packed:
        return slides if isinstance(slides, list) else None
    import zlib
    try:
        return json.loads(zlib.decompress(base64.b64decode(packed)).decode('utf-8'))
    except Exception:
        return slides if isinstance(slides, list) else None


def _agent_job_checkpoint(ctx, tasks, slides):
    """Persist mid-run state so a process restart resumes instead of replanning."""
    if not ctx.get('job_id'):
        return
    try:
        job = _read_job(_AGENT_JOB_NS, ctx['tenant_id'], ctx['job_id']) or {}
        state = {
            'planId': ctx.get('plan_id'),
            'deckSignature': _agent_deck_signature(slides),
            'tasks': [{k: t.get(k) for k in ('n', 'op', 'slides', 'titles', 'instruction',
                                           'style_brief', 'params', 'parts', 'target_count',
                                           'after', 'title', 'type', 'exact_text',
                                           'status', 'failureReason')} for t in tasks],
            'slideCount': len(slides),
        }
        packed = _pack_state_slides(slides)
        if packed:
            state['slidesPacked'] = packed
        else:
            state['slides'] = slides
        job['agentState'] = state
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
    # Executors check this between slide indexes inside a task; the render
    # lock serializes Playwright calls when per-slide worker calls run in
    # the bounded pool.
    ctx['_is_cancelled'] = lambda: _agent_job_cancelled(ctx)
    ctx.setdefault('_session_lock', threading.Lock())
    # The marker file is scoped to this job id — only a click for THIS run can
    # create it, and one written during the planning window must survive until
    # the first task boundary. Do not clear it here: clearing would swallow a
    # cancel that arrived while the planner was still thinking.

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
            _agent_record_failure(ctx, task, task['failureReason'], [], [])
            continue
        task['_indexes'] = indexes
        ctx['agent_last_worker_reason'] = None
        before_htmls = [slides[i].get('html', '') for i in indexes] if indexes else []
        task['_instruction'] = designer_agent_ops.instruction_for(task)

        executor = _EXECUTORS.get(op) or _agent_exec_code
        ok, reply, reason = False, None, None
        feedback = ''
        attempts_log = []
        before_by_index = dict(zip(indexes, before_htmls))
        for attempt in range(_AGENT_TASK_ATTEMPTS):
            after_htmls = None
            measure_report = None
            rejected_by_check = False
            ctx['agent_last_worker_reason'] = None
            # Executors mutate slides before verification runs; a rejected
            # attempt must leave the deck untouched (and retry from the
            # original slides, not from its own rejected output).
            deck_backup = [dict(s) if isinstance(s, dict) else s for s in slides]
            try:
                ok, reply, reason, after_htmls = executor(task, ctx, session, feedback)
            except Exception as exc:
                print(f"[DESIGNER-AGENT] task {n} ({op}) raised: {exc}")
                ok, reply, reason = False, None, f'exception:{type(exc).__name__}'
            if ok:
                if after_htmls is None:
                    after_htmls = [slides[j].get('html', '') for j in
                                   sorted(task.get('_indexes') or indexes) if j < len(slides)]
                v_ok, v_reasons = designer_agent_ops.verify_task_result(
                    op, before_htmls, after_htmls,
                    allowed_numbers=ctx.get('superseded_numbers'),
                    request_text='\n'.join(str(part) for part in (
                        ctx.get('message'), task.get('_instruction'),
                        task.get('exact_text')) if part),
                    exact_text=task.get('exact_text'))
                if v_ok and measure and op in ('edit', 'redesign', 'rewrite', 'restructure', 'split'):
                    for j in sorted(task.get('_indexes') or indexes):
                        if j >= len(slides):
                            continue
                        m_uri, m_report = session.render(slides[j].get('html', ''), screenshot=True)
                        if m_uri:
                            # The last slide designed this run is the consistency
                            # reference the next worker call sees (chatplan 3.6).
                            ctx['agent_style_ref_uri'] = m_uri
                        # Single-slide edits answer only for regressions against
                        # their own source; split/restructure rebuild the layout.
                        source = before_by_index.get(j) if op in designer_agent_ops.EDIT_OPS else None
                        m_reasons = _agent_layout_reasons(ctx, session, source, m_report)
                        if m_reasons:
                            v_ok, v_reasons, measure_report = False, m_reasons, m_report
                            break
                if v_ok:
                    break
                ok, rejected_by_check = False, True
                reason = ';'.join(v_reasons) or 'verification_failed'
            retry = (attempt + 1 < _AGENT_TASK_ATTEMPTS
                     and designer_agent_ops.is_retryable_failure(op, reason, rejected_by_check)
                     and not _is_billing_error_text(str(reason or '')))
            if not retry:
                # Give-up path: when every remaining finding is content drift
                # the owner rule is apply + warn — the client sees the result
                # and can undo or re-ask. Only a nothing/impossible result
                # (empty, invalid, unchanged, wrong shape) still rejects.
                codes = designer_agent_ops.reason_codes(reason)
                if codes and all(designer_agent_ops.reason_is_warning(c) for c in codes):
                    task['warnings'] = (task.get('warnings') or []) + [
                        part for part in str(reason or '').split(';') if part.strip()]
                    ok = True
                    break
            slides[:] = deck_backup
            attempts_log.append({'attempt': attempt + 1, 'reason': str(reason or '')[:400],
                                 'feedback': feedback, 'resultHtml': after_htmls or []})
            # Every worker op retries what the model can repair or a transient
            # provider failure — once, with feedback that names the defect.
            if retry:
                feedback = designer_agent_ops.retry_feedback(reason, before_htmls, measure_report)
                continue
            break

        if ok:
            task['status'] = 'success'
            executor_notes = task.pop('_warnings', []) or []
            if executor_notes:
                task['warnings'] = executor_notes + list(task.get('warnings') or [])
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
            if 'cancelled' in designer_agent_ops.reason_codes(reason):
                # An executor noticed the marker mid-task — remaining tasks
                # take the cancelled branch instead of running to failure.
                # A user-requested stop is not a journaled failure either.
                cancelled = True
                task['status'] = 'skipped'
                task['failureReason'] = 'cancelled'
                executed[-1]['status'] = 'skipped'
            else:
                _agent_record_failure(ctx, task, reason, before_htmls, attempts_log)
        _agent_job_checkpoint(ctx, tasks, slides)
        report(15 + int(70 * (i + 1) / max(1, total)),
               f"اكتملت المهمة {n}/{total} ({'نجاح' if ok else 'تعذّر'})",
               {'phase': 'agent', 'tasks': [designer_agent_ops.public_task(t) for t in tasks]})

    _agent_job_clear_cancel(ctx)
    return {'tasks': tasks, 'executed': executed, 'cancelled': cancelled,
            'billing_stopped': billing_stopped, 'measure': bool(measure),
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


def _measure_regression_reasons(before, after):
    try:
        import generate_pdf_from_preview as renderer
        return renderer.measure_regression_reasons(before, after)
    except Exception:
        return []


def _agent_layout_key(html):
    return hashlib.sha1(str(html or '').encode('utf-8')).hexdigest()


def _agent_remember_layout(ctx, html, report):
    """Keep the source measurement the worker's vision render already paid for."""
    if html and isinstance(report, dict):
        ctx.setdefault('agent_layout_cache', {})[_agent_layout_key(html)] = report


def _agent_layout_reasons(ctx, session, source_html, report):
    """Layout faults of one measured result slide. Given its source slide,
    only what the result made worse counts — an inherited overflow must not
    fail an unrelated edit on every attempt."""
    if not report:
        return []
    if not source_html:
        return _measure_reasons(report)
    cache = ctx.setdefault('agent_layout_cache', {})
    key = _agent_layout_key(source_html)
    if key not in cache:
        _uri, cache[key] = session.render(source_html, screenshot=False)
    return _measure_regression_reasons(cache[key], report)

