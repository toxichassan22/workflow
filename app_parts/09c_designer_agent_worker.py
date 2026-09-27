# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Designer agent — scoped worker (chatplan section 3.6)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# One model call per task on DESIGNER_AGENT_WORKER_MODEL. The worker sees only
# what the task needs: design rules, labeled project facts (never the raw
# project file), the slide's HTML and its render, the last slide designed in
# this run as a consistency reference, and the task instruction. It never sees
# the whole deck — the runner owns retries and verification.
#
# Every edit goes through the same post-pipeline the legacy editor used:
# resolve placeholders, refresh map/asset sources, finalize, sanitize, carry
# the watermark.

_AGENT_WORKER_SCHEMA = {
    'type': 'json_schema',
    'json_schema': {
        'name': 'designer_worker_result',
        'schema': {
            'type': 'object',
            'properties': {
                'slides': {'type': 'array', 'items': {
                    'type': 'object',
                    'properties': {
                        'title': {'type': 'string'},
                        'html': {'type': 'string'},
                    },
                    'required': ['title', 'html'],
                    'additionalProperties': True,
                }},
                'summary': {'type': 'string'},
            },
            'required': ['slides'],
            'additionalProperties': True,
        },
        'strict': False,
    },
}


def _agent_worker_facts(ctx, slide=None):
    """Labeled project facts only — the raw project file stays out."""
    parts = []
    try:
        facts = slide_engine.build_project_facts(
            ctx['project_data'], ctx['tenant_id'])
    except Exception:
        facts = ''
    if str(facts or '').strip():
        parts.append('## حقائق المشروع المرجعية\n' + str(facts).strip())
    asset_note = _get_images_info(ctx['creative_images'] or {}, ctx['project_data'])
    if str(asset_note or '').strip():
        parts.append('## الأصول البصرية والخرائط المتاحة فعليًا\n' + str(asset_note).strip())
    if isinstance(slide, dict) and _is_land_boundary_diagram_slide(
            title=slide.get('title'),
            content_source=slide.get('content_source') or slide.get('contentSource'),
            html=slide.get('html')):
        boundary = _designer_boundary_facts_note(ctx['project_data'])
        if str(boundary or '').strip():
            parts.append(boundary.strip())
    team_note = _designer_team_logo_context(ctx['creative_images'])
    parts.append(
        '## شعارات فريق العمل\n' + team_note +
        '\nممنوع إدراج أي شعار (شركة أو مشروع أو فريق عمل) إلا إذا طلب المستخدم ذلك '
        'صراحة بكلمة شعار أو لوجو في تعليماته الحالية.')
    return '\n\n'.join(parts)


def _agent_worker_system(ctx, slide_type, facts, style_brief):
    """Worker system prompt: rules + scoped facts + strict output contract."""
    training = str(ctx.get('training_context') or '').strip()
    training_note = (
        f"\n\n## قواعد الشركة الملزمة (من التدريب — التزم بها في التصميم)\n{training[:4000]}"
        if training else '')
    brief = str(style_brief or '').strip()
    brief_note = f"\n\n## الموجز الأسلوبي لهذه الخطة (يسري على كل المهام)\n{brief}" if brief else ''
    surface_note = '' if slide_type in ('cover', 'closing', 'section_divider', 'moodboard') else (
        "\n\n## عقد سطح شريحة المحتوى\n"
        "هذه شريحة محتوى عادية ويجب أن تبقى على canvas أبيض أو فاتح موحد، لا على إطار داكن حول صفحة بيضاء. "
        "استخدم اللون الأساسي في العناوين ورؤوس الجداول والمساحات المحدودة فقط، واترك الخلفية الداكنة الكاملة للغلاف والخاتمة وفواصل الأقسام ذات الصورة. "
        "خلفية شعار الشركة وشعار المشروع مستقلة لكل شعار حسب لونه وتباينه؛ لا تغيّرها عند تغيير خلفية الشريحة."
    )
    return f"""{build_design_rules(ctx['branding'])}{training_note}{brief_note}{surface_note}

{facts}
أنت عامل تصميم جراحي في Landloom. تنفذ مهمة واحدة على شريحة واحدة (أو ناتج محدد العدد) بدقة متناهية:
- التزم بنظام الألوان والخط أعلاه؛ لا تكتب اسم خط ثابت ولا تغيّر خط الشركة.
- الحفاظ حرفياً على كل نص ورقم وجدول وصورة ورابط وخريطة وخصائص البيانات (data-*) والتوكنات
  (##LOGO## و ##MAP_*## و ##TEAM_LOGO_*## و ##PRESERVED_*##) — بلا تلخيص أو حذف أو اختراع،
  ما لم تأمر التعليمات بعكس ذلك صراحة.
- نبرة عقارية استثمارية رسمية. ممنوع أي إيموجي أو أيقونات أو رموز أسهم أو نص إرشادي.
- مقاس الشريحة ثابت 1280x720 مع overflow:hidden وبلا أشرطة تمرير — وزّع المحتوى حتى لا يخرج عن الإطار.
- أعد JSON فقط بالصيغة المطلوبة: {{"slides":[{{"title":"..","html":"<div class=\\"slide\\" style=\\"width:1280px;height:720px;position:relative;overflow:hidden;\\">...</div>"}}],"summary":"شرح عربي موجز"}}"""


def _agent_worker_call(ctx, user_content, *, slide_type='content', facts='',
                       style_brief='', want_parts=1, temperature=0.35):
    """One worker model call. ``user_content`` is a text string or a parts list
    (text + image_url). Returns (parts_list, summary, error)."""
    try:
        parts_cap = int(want_parts or 1)
    except (TypeError, ValueError):
        parts_cap = 1
    max_tokens = DESIGNER_EDIT_MAX_TOKENS * min(max(parts_cap, 1), 4)
    messages = [
        {'role': 'system', 'content': _agent_worker_system(
            ctx, slide_type, facts, style_brief)},
        {'role': 'user', 'content': user_content},
    ]
    response = call_openrouter_messages(
        messages, response_format=_AGENT_WORKER_SCHEMA,
        model=DESIGNER_AGENT_WORKER_MODEL,
        max_tokens=max_tokens, temperature=temperature, timeout=300,
        usage_ctx=_agent_usage_ctx(ctx))
    result = openrouter_response_message(response, 'DESIGNER-WORKER')
    try:
        parsed = _designer_json_response(result['content'])
    except Exception:
        parsed = None
    produced = parsed.get('slides') if isinstance(parsed, dict) else None
    if not isinstance(produced, list) or not produced:
        return None, None, 'empty_worker_result'
    parts = []
    for item in produced:
        if not isinstance(item, dict):
            continue
        html = str(item.get('html') or item.get('content') or item.get('slide_html') or '')
        parts.append({'title': str(item.get('title') or ''), 'html': html})
    if not parts:
        return None, None, 'empty_worker_result'
    summary = (parsed.get('summary') or parsed.get('response') or '') if isinstance(parsed, dict) else ''
    return parts, str(summary), None


def _agent_worker_vision(ctx, slide_html, session):
    """(vision_uri, consistency_uri, vision_note) — the run's render session
    supplies both; the browser starts lazily on this first render call."""
    uri, report = (None, None)
    if session is not None and getattr(session, 'available', False):
        uri, report = session.render(slide_html)
    consistency = ctx.get('agent_style_ref_uri')
    note = ''
    if uri:
        note = (
            '\n\n## الرؤية البصرية للشريحة الحالية (الصورة الأولى المرفقة):\n'
            'لقطة فعلية للشريحة كما تظهر للمستخدم بدقة 1280x720 — التزم بنفس التوازن '
            'البصري والهوامش ما لم تأمر التعليمات بتغييره.'
        )
        if isinstance(report, dict) and report.get('ok'):
            overflow = []
            if report.get('overflowY'):
                overflow.append('تجاوز عمودي')
            if report.get('overflowX'):
                overflow.append('تجاوز أفقي')
            if (report.get('clipped') or []):
                overflow.append(f"عناصر مقصوصة ({len(report['clipped'])})")
            if overflow:
                note += '\nالقياس الحالي يظهر مشكلة: ' + '، '.join(overflow) + ' — عالجها في الناتج.'
    if consistency:
        note += ('\n\nالصورة الأخيرة المرفقة هي آخر شريحة صُممت في هذا التشغيل —'
                 ' حافظ على نفس اللغة البصرية والهوية.')
    return uri, consistency, note


def _agent_preserve_base64(html):
    """Same base64-to-placeholder trick the legacy editor used, so prompt size
    stays small and generated slides get their inline images back."""
    base64_map = {}

    def _keep(match):
        ph = f"##PRESERVED_BASE64_{len(base64_map)}##"
        base64_map[ph] = match.group(0)
        return ph
    clean = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', _keep, html or '')
    return clean, base64_map


def _agent_worker_finalize(output, source_html, instruction, ctx, *,
                           slide_num, title, total, slide_type, content_source):
    """The post-edit pipeline: tokens to assets, fresh map sources, finalize,
    sanitize, watermark carry-over."""
    output = resolve_designer_chat_placeholders(
        output, ctx['project_data'], ctx['presentation_id'],
        ctx['tenant_id'], ctx['creative_images'])
    output = _refresh_slide_map_sources(
        output, ctx['project_data'], ctx['tenant_id'],
        presentation_id=ctx['presentation_id'],
        creative_images=ctx['creative_images'])
    output = _refresh_slide_asset_sources(
        output, _designer_image_assets(
            _designer_creative_images(ctx['project_data'], ctx['creative_images'])))
    output = slide_engine.finalize_designer_slide_html(
        output, slide_type or 'content', ctx['project_data'], ctx['branding'],
        creative_images=ctx['creative_images'], tenant_id=ctx['tenant_id'],
        slide_num=slide_num, slide_title=title,
        total_slides=total, content_source=content_source,
        allow_all_maps=True)
    output = _sanitize_designer_output(output)
    if source_html and not _is_watermark_removal_instruction(instruction):
        output = _carry_slide_watermark(source_html, output)
    return output


def _agent_worker_note_failure(ctx, reason):
    """Executor-visible failure text (billing markers must survive for the
    runner's billing-stop check)."""
    if reason:
        ctx['agent_last_worker_reason'] = str(reason)[:400]
    return reason


def _agent_worker_edit_slide(ctx, slide, index, instruction, total,
                             session=None, feedback='', style_brief=''):
    """One scoped worker call on one slide.

    Returns ``(html, reply)`` on success and ``(None, reason)`` on failure —
    the runner owns retry/verification, so no attempts loop lives here.
    """
    html = slide.get('html', '')
    title = slide.get('title', f'شريحة {index + 1}')
    slide_type = slide.get('type', 'content')
    content_source = slide.get('content_source') or slide.get('contentSource')

    # Free deterministic edits — same head the legacy editor had, so a table or
    # color request routed as a generic edit never buys a model call.
    table_edit = designer_chat_reliability.apply_table_delete_request(html, instruction)
    if table_edit['changed']:
        return table_edit['html'], table_edit['description']
    is_slide_redesign = bool(re.search(
        r'(?:اعد\s*تصميم|إعادة\s*تصميم|غير\s*تصميم|تصميم|تنسيق|شريحة|سلايد|redesign|layout|style)',
        str(instruction or ''), re.IGNORECASE))
    if (not is_slide_redesign and table_edit['handled']
            and table_edit.get('reason') in ('would_empty_table', 'negated_or_conditional_request')):
        reason_text = _TABLE_PRECHECK_ARABIC_REASONS.get(table_edit['reason'], table_edit['reason'])
        return None, _agent_worker_note_failure(ctx, f'table_precheck:{reason_text}')
    if designer_chat_colors.is_color_only_request(instruction):
        color_html, color_message = designer_chat_colors.apply_color_edit(html, instruction)
        if color_html and color_html != html:
            return color_html, color_message
        return None, _agent_worker_note_failure(ctx, 'color_unchanged')

    # The boundary diagram is rebuilt from documented facts — the legacy
    # deterministic editor owns that slide type.
    if _is_land_boundary_diagram_slide(
            title=title, content_source=content_source, html=html):
        return _designer_edit_slide(
            html, title, instruction, index, ctx['project_data'],
            ctx['presentation_id'], ctx['branding'], tenant_id=ctx['tenant_id'],
            creative_images=ctx['creative_images'],
            user_image_refs=ctx['user_image_refs'],
            slide_type=slide_type, total_slides=total,
            content_source=content_source)

    clean_html, base64_map = _agent_preserve_base64(html)
    vision_uri, consistency_uri, vision_note = _agent_worker_vision(ctx, html, session)
    facts = _agent_worker_facts(ctx, slide=slide)
    text = (f'عنوان الشريحة: {title}\nرقمها الحالي في العرض: {index + 1} من {total}\n'
            f'الطلب:\n{instruction}'
            + (f'\nملاحظة تحقق على محاولة سابقة — عالجها حرفياً: {feedback[:800]}' if feedback else '')
            + vision_note
            + f'\n\nHTML الحالي:\n{clean_html}')
    user_content = [{'type': 'text', 'text': text}]
    for uri in (vision_uri, consistency_uri):
        if uri:
            user_content.append({'type': 'image_url', 'image_url': {'url': uri}})
    if ctx.get('user_image_refs'):
        for ref in ctx['user_image_refs']:
            uri = ref.get('data_uri') if isinstance(ref, dict) else None
            if uri:
                user_content.append({'type': 'image_url', 'image_url': {'url': uri}})
        user_content.insert(1, {'type': 'text', 'text':
            'الصور الأخيرة المرفقة صور أرفقها المستخدم مع طلبه — استخدمها كما يوضح الطلب.'})
    try:
        parts, summary, error = _agent_worker_call(
            ctx, user_content, slide_type=slide_type, facts=facts,
            style_brief=style_brief, want_parts=1)
    except Exception as exc:
        return None, _agent_worker_note_failure(ctx, f'provider_error:{exc}')
    if error or not parts:
        return None, _agent_worker_note_failure(ctx, error or 'empty_worker_result')
    output = str(parts[0].get('html') or '')
    if not output or 'slide' not in output or '<div' not in output:
        return None, _agent_worker_note_failure(ctx, 'invalid_html')
    for ph, b64 in base64_map.items():
        output = output.replace(ph, b64)
    try:
        output = _agent_worker_finalize(
            output, html, instruction, ctx,
            slide_num=index + 1, title=title,
            total=total, slide_type=slide_type, content_source=content_source)
    except Exception as exc:
        return None, _agent_worker_note_failure(ctx, f'finalize_failed:{exc}')
    return output, summary or ''


def _agent_structure_edit(ctx, session, feedback='', style_brief=''):
    """Adapt the scoped worker to execute_structure's edit_slide signature so
    split/create keep their deterministic candidates and atomic checks."""
    def edit_slide(html, title, instruction, index, kind, total, source):
        slide = {'html': html, 'title': title, 'type': kind,
                 'content_source': source}
        new_html, reply = _agent_worker_edit_slide(
            ctx, slide, index, instruction, total, session, feedback,
            style_brief)
        return new_html or html, reply or ''
    return edit_slide


def _agent_worker_restructure(ctx, sources, target, instruction, feedback=''):
    """One scoped call regrouping ``sources`` into exactly ``target`` slides."""
    condensing = target < len(sources)
    if condensing:
        keep = (
            'حافظ على كل رقم وتاريخ ونسبة واسم جهة وصف جدول وصورة ورابط وخريطة '
            'حرفياً كما وردت، ولا تُسقط وسوم data-index-page إن وُجدت. يجوز '
            'تلخيص النص السردي ودمج العناصر المكررة بين الشرائح — الهيدر '
            'والشعارات والتذييل تكفي مرة واحدة — لكن ممنوع إسقاط أي حقيقة أو '
            'رقم أو بند.')
    else:
        keep = (
            'الحفاظ حرفياً على كل نص ورقم وصف جدول وصورة ورابط وخريطة وخصائص '
            'البيانات من المصادر إلزامي — بلا تلخيص أو حذف أو اختراع.')
    system = (
        f'أعد هيكلة محتوى الشرائح المصدر أدناه في {target} شريحة بالضبط. '
        + keep
        + ' أعد توزيع المحتوى بشكل متوازن واحترافي فقط. '
        + (f'المحاولة السابقة رُفضت: {feedback} ' if feedback else '')
        + 'أخرج JSON بصيغة {"slides":[{"title":"..","html":".."}]} والـ html شريحة كاملة '
        'بجذر <div class="slide" style="width:1280px;height:720px;...">.')
    user = json.dumps({'sources': [{'title': s.get('title', ''), 'html': s.get('html', '')}
                                   for s in sources],
                       'instruction': instruction}, ensure_ascii=False)
    response = call_openrouter_messages(
        [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
        response_format=_AGENT_WORKER_SCHEMA, model=DESIGNER_AGENT_WORKER_MODEL,
        max_tokens=DESIGNER_EDIT_MAX_TOKENS * 2, temperature=0.35,
        usage_ctx=_agent_usage_ctx(ctx))
    result = openrouter_response_message(response, 'DESIGNER-RESTRUCTURE')
    payload = _designer_json_response(result['content'])
    produced = payload.get('slides') if isinstance(payload, dict) else None
    if not isinstance(produced, list) or len(produced) != target:
        return None, 'incomplete_result'
    return produced, None
