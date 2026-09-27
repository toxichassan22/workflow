# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Designer agent (DESIGNER_AGENT=1): planner then runner then worker
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# The legacy path sends one giant plan that edits slides by mutable position
# and discards the whole batch when one slide fails. The agent path instead:
#   1. plans against an outline of stable slide ids (designer_agent_plan),
#   2. expands the plan into explicit per-task work (designer_agent_ops),
#   3. executes tasks one at a time, checkpointing progress into the job file
#      so a restart resumes mid-run instead of replaying the planner,
#   4. verifies each task result and retries once with the failure reason,
#   5. preserves every successful task when later tasks fail.
# Pending plans the user must confirm are echoed back and returned inside
# ``pendingPlan`` — the deck signature (ordered slide ids) guards against
# confirming a plan that no longer matches the deck.

import designer_agent_ids
import designer_agent_ops
import designer_agent_plan
import designer_chat_safety

_AGENT_JOB_NS = '.designer_chat_jobs'
_AGENT_TOOL_ROUNDS = 6
_AGENT_TASK_ATTEMPTS = 2
# Plans at or above this many tasks — or any deck-shape op — ask the user to
# confirm the checklist before anything executes.
_AGENT_CONFIRM_TASK_THRESHOLD = 5

_DESIGNER_AGENT_TOOLS = [
    {'type': 'function', 'function': {
        'name': 'get_slides',
        'description': 'أعِد HTML الكامل لشرائح محددة بالمعرفات (حتى 6 في المرة الواحدة). استخدمه فقط عندما لا يكفي المخطط للقرار.',
        'parameters': {'type': 'object', 'properties': {
            'ids': {'type': 'array', 'items': {'type': 'string'},
                    'description': 'معرفات الشرائح من المخطط'}},
            'required': ['ids']}}},
    {'type': 'function', 'function': {
        'name': 'density',
        'description': 'مؤشرات كثافة الشرائح (أحرف/صفوف/كروت/صور/درجة) لتقدير الحاجة للتقسيم أو الدمج.',
        'parameters': {'type': 'object', 'properties': {
            'ids': {'type': 'array', 'items': {'type': 'string'}}}}}},
    {'type': 'function', 'function': {
        'name': 'render_slide',
        'description': 'صورة للشريحة كما تبدو الآن — للحالات المشكوك فيها بصرياً فقط (تداخل، تدفق نصي).',
        'parameters': {'type': 'object', 'properties': {
            'id': {'type': 'string'}}, 'required': ['id']}}},
]

_AGENT_PLAN_SCHEMA = {
    'type': 'json_schema',
    'json_schema': {
        'name': 'designer_turn',
        'schema': {
            'type': 'object',
            'properties': {
                'kind': {'type': 'string', 'enum': ['reply', 'ask', 'plan']},
                'message': {'type': 'string'},
                'style_brief': {'type': 'string'},
                'ops': {'type': 'array', 'items': {
                    'type': 'object',
                    'properties': {
                        'op': {'type': 'string'},
                        'select': {'type': 'object'},
                        'instruction': {'type': 'string'},
                        'params': {'type': 'object'},
                        'parts': {}, 'target_count': {},
                        'title': {'type': 'string'}, 'type': {'type': 'string'},
                        'after': {}, 'exact_text': {'type': 'string'},
                    },
                    'required': ['op'],
                    'additionalProperties': True,
                }},
            },
            'required': ['kind'],
            'additionalProperties': True,
        },
        'strict': False,
    },
}

_AGENT_PLANNER_RULES = """أنت «المخطط» لمساعد تصميم العروض في Landloom. مهمتك تحويل طلب المستخدم إلى خطة مهام صغيرة قابلة للتنفيذ على شرائح محددة بمعرّفاتها (id) — أنت لا تنفذ التعديل ولا تكتب HTML.

## الشرائح الحالية
{outline}

## المحادثة
{memory}{history}{focus}{scope}

## أدوات قراءة قبل التخطيط
- get_slides(ids): نص HTML كامل لشرائح محددة (حتى 6 في المرة).
- density(ids): مؤشرات كثافة (أحرف/صفوف/كروت/صور).
- render_slide(id): صورة الشريحة الحالية للحالات المشكوك فيها بصرياً.
لا تستدعِ أداة إلا عندما لا يكفي المخطط أعلاه للقرار.

## القرار — JSON بإحدى الصيغ
- {{"kind":"reply","message":"رد مختصر"}} — لسؤال أو تأكيد لا يحتاج تنفيذاً.
- {{"kind":"ask","message":"سؤال توضيحي واحد محدد"}} — عند غموض جوهري في الهدف أو العدد.
- {{"kind":"plan","style_brief":"موجز أسلوبي اختياري يسري على كل المهام","ops":[...]}} — خطة تنفيذية.

## أشكال select
{{"ids":["id1","id2"]}} | {{"range":[fromId,toId]}} | {{"section":"key"}} | {{"all":true}} | {{"current":true}}

## العمليات (op)
- edit: تعديل محدد على محتوى الشريحة مع الحفاظ على بنيتها.
- redesign: إعادة تصميم الشريحة شكلياً مع الحفاظ على الحقائق والأرقام حرفياً.
- rewrite: إعادة صياغة نص الشريحة.
- split: تقسيم شريحة واحدة إلى parts أجزاء (params.parts أو "auto").
- restructure: إعادة هيكلة مجموعة شرائح متجاورة إلى target_count شريحة (أقل أو أكثر) — لطلبات «قلل الصفحات/ادمج هذه الصفحات في N».
- delete / move / create: حذف أو نقل أو إنشاء صريح. move وcreate يأخذان after = معرف شريحة أو "start" أو "end".
- table_edit: حذف صف أو عمود من جدول — params {{"column":"اسم العمود"}} أو {{"row":رقم}} — تنفيذ كودي حتمي.
- color_edit: استبدال لون — params {{"from":"#hex","to":"#hex"}}.
- watermark: علامة مائية — params {{"action":"apply|remove|show|hide","opacity":0.045,"width_px":480,"only_white":false}}.
- insert_attached_image: صورة أرفقها المستخدم في هذه الرسالة — params {{"image_index":1,"position":"separate_slide|inline|background|watermark|logo","title":"","caption":"","opacity":0.12,"width_px":480}}.
- insert_map: خريطة معتمدة — params {{"map_type":"overview|access|catchment|landmarks","refresh":false}}.
- update_image: استبدال صورة داخل شريحة بأصل بصري من المشروع — params {{"asset":"التوكن من قائمة الأصول","image_index":1}}.
- generate_image: توليد صورة جديدة — params {{"prompt":"وصف دقيق","component_name":"","position":"surgical|background|right|left|inline"}}.
- image_descriptions: إضافة الأوصاف المحفوظة للصور.
- team_logo / company_logo_panel: شعار الفريق أو شعار الشركة.

## قواعد
- لا تخمّن معرفات غير موجودة في المخطط — عند شك في الهدف اسأل بدل التخمين.
- «أعد تصميم/حسّن الشكل» تعني redesign؛ «غيّر/عدّل شيئاً محدداً» تعني edit؛ «أعد الصياغة» تعني rewrite.
- الافتراضي عند غياب تحديد هو current (الشريحة المعروضة)، إلا إذا كان الطلب جمعاً واضحاً فاختر all أو ids.
- كل مهمة وظيفة واحدة: لا تخلط إعادة تصميم وتقسيم على نفس الشريحة في op واحد — أنشئ op لكل مقصود وستُدمج تلقائياً على الأقوى.
- نبّه في message عندما تحتاج الخطة لتأكيد المستخدم (تغيير عدد الشرائح أو مهام كثيرة)."""


def _agent_usage_ctx(ctx, kind='designer_chat'):
    return _usage_ctx(kind, ctx.get('data') or {},
                      presentation_id=ctx.get('presentation_id'))


def _agent_deck_signature(slides):
    """Sign the deck by content, not ids: a pending plan stays valid only while
    the slides it targeted are byte-identical — any user edit between plan and
    confirm forces a re-plan (ids alone would miss content edits, and the
    plan_pending response intentionally doesn't return slidesData)."""
    body = '\x00'.join(str(s.get('html') or '') for s in slides if isinstance(s, dict))
    return hashlib.sha1(body.encode('utf-8')).hexdigest()[:16]


def _agent_error_turn(text):
    return {'kind': 'reply', 'message': text}


def _is_billing_error_text(text):
    return _is_company_credit_error(text)


# ── Balance pre-flight ───────────────────────────────────────────────────────

def _agent_run_estimate_sar(tasks):
    """Rough billed-SAR estimate for a task plan: the planner turn plus one
    worker call per targeted slide (per-image pricing for generate_image).

    Deliberately conservative: it exists to refuse a run the wallet clearly
    cannot finish — mid-run failures still degrade to the billing-stop path.
    """
    try:
        estimates = db.get_billing_flow_estimates()
    except Exception:
        estimates = {}
    per_call = float(estimates.get('slide_single') or 0.25)
    per_image = float(estimates.get('image_generation') or 0.5)
    calls = 1  # the planner turn itself
    images = 0
    for task in tasks or []:
        if not isinstance(task, dict) or task.get('engine') != 'worker':
            continue
        op = str(task.get('op') or '')
        slide_count = max(1, len(task.get('slides') or []))
        if op == 'generate_image':
            images += 1
        elif op == 'split':
            try:
                calls += max(1, int(task.get('parts') or (task.get('params') or {}).get('parts') or 2))
            except (TypeError, ValueError):
                calls += 2
        elif op == 'restructure':
            calls += 1
        else:
            calls += slide_count
    try:
        return db.usd_to_sar(calls * per_call + images * per_image)
    except Exception:
        return 0.0


def _agent_balance_preflight(ctx, tasks):
    """Refuse a run early when the wallet visibly cannot cover its estimate.

    Gated on BILLING_ENFORCE=1 like every other billing guard — with
    enforcement off, tests and zero-balance tenants must still generate; the
    runner's billing-stop then preserves partial successes instead.
    """
    try:
        if not db.billing_enforcement_enabled():
            return None
    except Exception:
        return None
    need_sar = _agent_run_estimate_sar(tasks)
    if need_sar <= 0:
        return None
    available = _designer_available_sar(ctx['tenant_id'])
    if available >= need_sar:
        return None
    return _agent_chat_response(
        ctx,
        f'رصيد شركتك المتاح حاليًا ~{available:.2f} ريال، والتكلفة التقديرية '
        f'لهذا الطلب ~{need_sar:.2f} ريال — اشحن المحفظة ثم أعد المحاولة.',
        kind='reply')


# ── Planner read tools ───────────────────────────────────────────────────────

def _agent_tool_result(name, args, ctx, session):
    """Execute one planner read tool. Returns (tool_text, image_data_uri|None)."""
    slides = ctx['slides']
    by_id = {str(s.get('id')): s for s in slides if isinstance(s, dict) and s.get('id')}
    if name == 'get_slides':
        ids = [str(i) for i in (args.get('ids') or [])][:6]
        found = []
        for sid in ids:
            slide = by_id.get(sid)
            if slide is None:
                continue
            found.append({'id': sid, 'title': str(slide.get('title') or ''),
                          'html': str(slide.get('html') or '')[:60000]})
        return json.dumps({'slides': found, 'requested': len(ids), 'found': len(found)},
                          ensure_ascii=False), None
    if name == 'density':
        ids = [str(i) for i in (args.get('ids') or [])]
        return json.dumps(designer_agent_plan.density(slides, ids or None),
                          ensure_ascii=False), None
    if name == 'render_slide':
        slide = by_id.get(str(args.get('id') or ''))
        if slide is None:
            return json.dumps({'error': 'unknown_id'}, ensure_ascii=False), None
        if session is None or not getattr(session, 'available', False):
            return json.dumps({'error': 'render_unavailable',
                               'note': 'استنتج من بنية HTML عبر get_slides بدلاً من المعاينة'},
                              ensure_ascii=False), None
        uri, report = session.render(slide.get('html') or '')
        if not uri:
            return json.dumps({'error': 'render_failed'}, ensure_ascii=False), None
        return json.dumps({'report': report}, ensure_ascii=False), uri
    return json.dumps({'error': f'unknown_tool:{name}'}, ensure_ascii=False), None


# ── Planner ──────────────────────────────────────────────────────────────────

def _designer_agent_plan(ctx, session=None):
    """Run the planner loop. Returns (turn_dict, messages, errors)."""
    slides = ctx['slides']
    notes = {
        'memory': (f"\n\n## ذاكرة المحادثة\n{ctx['chat_memory']}" if ctx.get('chat_memory') else ''),
        'history': ("\n\n## آخر رسائل المحادثة\n" + '\n'.join(ctx['history_lines']))
                   if ctx.get('history_lines') else '',
        'focus': (f"\n\n## نطاق الحديث السابق: {'، '.join(str(n) for n in ctx['focus_indexes'])}"
                  ' — سياق سابق وليس أمراً جديداً.') if ctx.get('focus_indexes') else '',
        'scope': (f"\n\n## الشريحة الظاهرة الآن: {ctx['current_index'] + 1} (موضع معاينة فقط)"
                  + ('\nالمستخدم طلب صراحة تعديل جميع الشرائح.' if ctx.get('is_all_slides_request') else '')),
    }
    system = _AGENT_PLANNER_RULES.format(
        outline=designer_agent_plan.outline_text(slides),
        memory=notes['memory'], history=notes['history'],
        focus=notes['focus'], scope=notes['scope'])
    if ctx.get('attached_uris'):
        system += (f"\n\n## صور مرفقة في هذه الرسالة: {len(ctx['attached_uris'])}\n"
                   'استخدم op="insert_attached_image" حصراً لإدراج أي منها.')
    if ctx.get('training_context'):
        system += f"\n\n## قواعد الشركة الملزمة\n{ctx['training_context'][:4000]}"

    messages = [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': ctx['message'][:4000]},
    ]
    errors = []
    for _round in range(_AGENT_TOOL_ROUNDS):
        try:
            response = call_openrouter_messages(
                messages, tools=_DESIGNER_AGENT_TOOLS,
                response_format=_AGENT_PLAN_SCHEMA,
                model=DESIGNER_AGENT_PLANNER_MODEL,
                max_tokens=DESIGNER_PLANNER_MAX_TOKENS + 3000,
                temperature=0.3, timeout=180,
                usage_ctx=_agent_usage_ctx(ctx))
            result = openrouter_response_message(response, 'DESIGNER-PLANNER')
        except RuntimeError as exc:
            errors.append(str(exc))
            if _is_company_credit_error(exc):
                return _agent_error_turn(_COMPANY_CREDIT_EXHAUSTED_MSG), messages, errors
            return _agent_error_turn('تعذر التخطيط الآن — ' + _client_safe_llm_error(exc)[:300]), messages, errors
        if result['tool_calls']:
            messages.append(openrouter_assistant_tool_message(result))
            images = []
            # Every tool call gets a tool message — OpenAI rejects a request
            # that answers only some calls. Executed calls are capped at 4;
            # the rest get an explicit error result instead of silence.
            for i, call in enumerate(result['tool_calls']):
                if i < 4:
                    text, image_uri = _agent_tool_result(
                        call['name'], call.get('arguments') or {}, ctx, session)
                    if image_uri:
                        images.append(image_uri)
                else:
                    text = json.dumps(
                        {'error': 'too_many_tool_calls',
                         'note': 'أصدر 4 طلبات أدوات كحد أقصى في الجولة الواحدة'},
                        ensure_ascii=False)
                messages.append(openrouter_tool_result_message(call, text))
            # Vision payloads ride AFTER the tool results, never between them:
            # a user message interleaved with tool results is a 400 on OpenAI.
            if images:
                messages.append({'role': 'user', 'content': [
                    {'type': 'text', 'text': 'معاينات الشرائح المطلوبة بالترتيب:'},
                    *[{'type': 'image_url', 'image_url': {'url': uri}} for uri in images],
                ]})
            continue
        content = result['content']
        try:
            turn = _designer_json_response(content)
        except Exception:
            turn = None
        if isinstance(turn, dict) and turn.get('kind') in ('reply', 'ask', 'plan'):
            if turn.get('kind') == 'plan' and not isinstance(turn.get('ops'), list):
                errors.append('plan_without_ops')
            else:
                return turn, messages, errors
        errors.append('unparseable_turn')
        messages.append({'role': 'assistant', 'content': content or ''})
        messages.append({'role': 'user', 'content':
                         'أجب فقط بـ JSON مطابق للصيغة المطلوبة (kind: reply|ask|plan).'})
    return _agent_error_turn('تعذر فهم الطلب بصيغة خطة واضحة — أعد صياغته لو سمحت.'), messages, errors



# ── Turn entry point ─────────────────────────────────────────────────────────

def _designer_agent_turn(ctx):
    """The agent replacement for the legacy all-at-once planner.

    ``ctx`` carries everything the route already resolved (slides have stable
    ids). Returns a Flask response.
    """
    data = ctx['data']
    slides = ctx['slides']
    tenant_id = ctx['tenant_id']

    # Attached images: raw data URIs feed the vision refs; the persisted URLs
    # are what code ops embed into slide HTML.
    raw_uris = _normalize_designer_attached_images(data)
    ctx['user_image_refs'] = [{'data_uri': uri} for uri in raw_uris] or None
    if raw_uris:
        try:
            ctx['attached_uris'] = _persist_designer_attached_images(raw_uris, tenant_id)
        except Exception as exc:
            print(f"[DESIGNER-AGENT] attached persist failed: {exc}")
            ctx['attached_uris'] = list(raw_uris)
    else:
        ctx['attached_uris'] = []

    # Restart resume: the job file keeps the in-flight deck + task statuses.
    job = _agent_job_get(ctx)
    agent_state = job.get('agentState') if isinstance(job, dict) else None
    if isinstance(agent_state, dict) and agent_state.get('tasks'):
        pending = [t for t in agent_state['tasks'] if t.get('status') in ('pending', 'failed')]
        if pending and isinstance(agent_state.get('slides'), list):
            ctx['slides'] = slides = agent_state['slides']
            ctx['plan_id'] = agent_state.get('planId')
            block = _agent_balance_preflight(ctx, agent_state['tasks'])
            if block is not None:
                return block
            with _agent_render_session(ctx['branding'], tenant_id) as session:
                run = _designer_agent_run(agent_state['tasks'], ctx, session)
            return _designer_agent_finish(run, ctx)

    # Client-side retry/continue: tasks echoed from a previous run's checklist.
    resume_tasks = data.get('retryTasks') if isinstance(data.get('retryTasks'), list) else None
    if resume_tasks:
        clean = [t for t in resume_tasks if isinstance(t, dict) and t.get('op')]
        if clean:
            for t in clean:
                t['status'] = 'pending'
                t.pop('failureReason', None)
            block = _agent_balance_preflight(ctx, clean)
            if block is not None:
                return block
            with _agent_render_session(ctx['branding'], tenant_id) as session:
                run = _designer_agent_run(clean, ctx, session)
            return _designer_agent_finish(run, ctx)

    # Pending-plan confirmation: client echoes the plan back; the deck
    # signature proves nothing shuffled while the user was deciding.
    confirm = data.get('confirmPlan') if isinstance(data.get('confirmPlan'), dict) else None
    if confirm:
        if confirm.get('deckSignature') != _agent_deck_signature(slides):
            return _agent_chat_response(ctx, 'تغيّر ترتيب العرض بعد إعداد الخطة — أعد الطلب لأخطط على النسخة الحالية.', kind='ask')
        tasks, _errs = designer_agent_plan.expand_plan(
            {'ops': confirm.get('ops') or [], 'style_brief': confirm.get('style_brief') or ''},
            slides, current_index=ctx['current_index'])
        if tasks:
            ctx['plan_id'] = confirm.get('id')
            block = _agent_balance_preflight(ctx, tasks)
            if block is not None:
                return block
            with _agent_render_session(ctx['branding'], tenant_id) as session:
                run = _designer_agent_run(tasks, ctx, session)
            return _designer_agent_finish(run, ctx)
        return _agent_chat_response(ctx, 'الخطة المؤكدة فارغة أو لم تعد صالحة.', kind='ask')
    if data.get('cancelPlan'):
        return _agent_chat_response(ctx, 'أُلغيت الخطة — لم يتغير العرض.', kind='reply')

    with _agent_render_session(ctx['branding'], tenant_id) as session:
        turn, _messages, errors = _designer_agent_plan(ctx, session)
        if turn.get('kind') != 'plan':
            return _agent_chat_response(ctx, turn.get('message') or 'لم أستطع تحديد طلبك.',
                                        kind=turn.get('kind') or 'reply')

        tasks, expand_errors = designer_agent_plan.expand_plan(
            turn, slides, current_index=ctx['current_index'])
        if expand_errors and not tasks:
            # One reprompt with the expansion errors spelled out.
            retry_ctx = dict(ctx)
            retry_ctx['message'] = (
                ctx['message'] + '\n\n[أخطاء في خطتك السابقة — صحّحها: '
                + json.dumps(expand_errors, ensure_ascii=False)[:800] + ']')
            turn, _messages, _e2 = _designer_agent_plan(retry_ctx, session)
            if turn.get('kind') == 'plan':
                tasks, expand_errors = designer_agent_plan.expand_plan(
                    turn, slides, current_index=ctx['current_index'])
        if not tasks:
            note = ''
            if expand_errors:
                note = ' (' + json.dumps(expand_errors[:3], ensure_ascii=False)[:300] + ')'
            return _agent_chat_response(
                ctx, 'لم أستطع تحويل الطلب إلى مهام صالحة على الشرائح الحالية' + note,
                kind='ask')

        block = _agent_balance_preflight(ctx, tasks)
        if block is not None:
            return block
        confirm_needed = (len(tasks) >= _AGENT_CONFIRM_TASK_THRESHOLD
                          or any(designer_agent_ops.needs_confirmation(t) for t in tasks))
        if confirm_needed and not data.get('autoConfirm'):
            plan_id = f"plan-{int(time.time() * 1000):x}-{os.urandom(3).hex()}"
            pending = {
                'id': plan_id,
                'deckSignature': _agent_deck_signature(slides),
                'style_brief': turn.get('style_brief') or '',
                'ops': turn.get('ops') or [],
                'tasks': [designer_agent_ops.public_task(t) for t in tasks],
            }
            summary = turn.get('message') or f'أعددت خطة من {len(tasks)} مهمة على العرض.'
            return _agent_chat_response(
                ctx, summary, kind='plan_pending', pending_plan=pending, tasks=tasks,
                slides=slides)

        ctx['plan_id'] = None
        run = _designer_agent_run(tasks, ctx, session)
    return _designer_agent_finish(run, ctx)


def _agent_chat_response(ctx, text, kind='reply', pending_plan=None, tasks=None, slides=None):
    """Chat-only / ask / plan-pending reply — deck content untouched. For
    plan_pending the id-annotated slidesData is included so the client can
    echo the same ids back on confirm (the ids are metadata only — content
    is unchanged)."""
    history_for_turn = ctx['history_for_turn']
    message = ctx['message']
    persisted = _normalize_designer_chat_messages(history_for_turn)[-DESIGNER_CHAT_STORED_TURNS * 2:]
    if not persisted or persisted[-1].get('content') != message or persisted[-1].get('role') != 'user':
        persisted.append({'role': 'user', 'content': message[:2000],
                          'slides': ctx['preferred_indexes'][:]})
    persisted.append({'role': 'assistant', 'content': str(text or '')[:2000],
                      'slides': ctx['preferred_indexes'][:]})
    body = {
        'action': 'plan_pending' if kind == 'plan_pending' else ('ask' if kind == 'ask' else 'chat_only'),
        'response': text, 'actions': [],
        'memory': ctx['chat_memory'], 'focusIndexes': ctx['focus_indexes'],
        'chatHistory': persisted[-DESIGNER_CHAT_STORED_TURNS * 2:], 'saved': False,
        'agent': {'mode': 'planner', 'kind': kind},
    }
    if pending_plan:
        body['pendingPlan'] = pending_plan
        body['tasks'] = pending_plan['tasks']
        body['slidesData'] = slides if slides is not None else ctx['slides']
    return jsonify({'success': True, 'data': body})


def _designer_agent_finish(run, ctx):
    """Build the workspace_update response after a run."""
    slides = ctx['slides']
    tasks = run['tasks']
    executed = run['executed']
    branding = ctx['branding']

    structural_change = any(t.get('op') in designer_agent_ops.STRUCTURE_OPS
                            and t.get('status') == 'success' for t in tasks)
    structural_change = structural_change or any(
        t.get('op') == 'insert_attached_image' and t.get('status') == 'success'
        and str((t.get('params') or {}).get('position') or '') == 'separate_slide'
        for t in tasks)
    if structural_change:
        slides = slide_engine.renumber_presentation_slides(
            slides, branding=branding, project_data=ctx['project_data'],
            tenant_id=ctx['tenant_id'], allow_all_maps=True,
            creative_images=ctx['creative_images'], preserve_html=True)
        ctx['slides'] = slides
    designer_agent_ids.ensure_slide_ids(slides)

    validation = _validate_workspace_data({'slidesData': slides})
    if not validation['valid']:
        return jsonify({'success': False,
                        'error': 'تم رفض التعديل لأن العرض يحتوي على شرائح غير صالحة',
                        'validation': validation}), 422
    slide_changes = change_tracking.describe_slide_changes(ctx['slides_before'], slides)
    touched = [i + 1 for t in tasks if t.get('status') == 'success'
               for i in (t.get('_indexes') or [])]
    turn_focus = sorted(dict.fromkeys(touched)) or ctx['focus_indexes']

    succeeded = [t for t in tasks if t.get('status') == 'success']
    failed = [t for t in tasks if t.get('status') == 'failed']
    skipped = [t for t in tasks if t.get('status') == 'skipped']
    replies = [t['reply'] for t in succeeded if t.get('reply')]
    if run['cancelled']:
        response_text = f'أُلغي الطلب بعد إنجاز {len(succeeded)} من {len(tasks)} مهمة — بقيت التعديلات الناجحة.'
    elif run['billing_stopped']:
        response_text = (f'توقف التنفيذ لاستنفاد رصيد شركتك — أُنجزت {len(succeeded)} من {len(tasks)} '
                         'مهمة وبقيت محفوظة. اشحن المحفظة ثم أعد المحاولة.')
    elif succeeded:
        response_text = 'تم تطبيق التعديلات المطلوبة.'
        if failed:
            response_text += f' تعذّرت {len(failed)} مهمة من أصل {len(tasks)}.'
        if replies:
            response_text += ' ' + ' '.join(dict.fromkeys(replies))[:600]
    else:
        response_text = 'لم يتم تنفيذ أي تعديل على العرض.'
        if failed:
            first_reason = _client_safe_llm_error(failed[0].get('failureReason') or '')
            response_text += f' السبب: {first_reason[:200]}'

    persisted = _normalize_designer_chat_messages(ctx['history_for_turn'])[-DESIGNER_CHAT_STORED_TURNS * 2:]
    if not persisted or persisted[-1].get('content') != ctx['message'] or persisted[-1].get('role') != 'user':
        persisted.append({'role': 'user', 'content': ctx['message'][:2000],
                          'slides': ctx['preferred_indexes'][:]})
    persisted.append({'role': 'assistant', 'content': response_text[:2000],
                      'slides': ctx['preferred_indexes'][:]})

    response_creative_images = copy.deepcopy(ctx['creative_images'])
    source_creative_images = ctx.get('request_creative_images') or ctx.get('project_creative_images')
    if isinstance(source_creative_images, dict) and isinstance(source_creative_images.get('map_placeholders'), dict):
        returned = response_creative_images.get('map_placeholders')
        returned = dict(returned) if isinstance(returned, dict) else {}
        returned.update(source_creative_images['map_placeholders'])
        response_creative_images['map_placeholders'] = returned

    public_tasks = [designer_agent_ops.public_task(t) for t in tasks]
    response_data = {
        'action': 'workspace_update', 'response': response_text,
        'slidesData': slides, 'creativeImages': response_creative_images,
        'actions': executed, 'validation': validation,
        'tasks': public_tasks,
        'memory': ctx['chat_memory'], 'focusIndexes': turn_focus,
        'chatHistory': persisted[-DESIGNER_CHAT_STORED_TURNS * 2:],
        'saved': False,
        'agent': {
            'mode': 'runner', 'planId': ctx.get('plan_id'),
            'total': len(tasks), 'done': len(succeeded),
            'failed': len(failed), 'skipped': len(skipped),
            'cancelled': run['cancelled'], 'billingStopped': run['billing_stopped'],
        },
    }
    if succeeded and slide_changes:
        response_data['changeSource'] = 'ai'
        response_data['provenance'] = _issue_presentation_provenance(
            slides, ctx['presentation_id'], int((ctx.get('presentation') or {}).get('revision') or 0),
            [f'طلب التصميم: {ctx["message"][:2000]}'] + [
                f'مهمة {t.get("n")}: {t.get("op")}' for t in succeeded])
    if failed or run['cancelled'] or run['billing_stopped']:
        response_data['failureReason'] = next(
            (t.get('failureReason') for t in failed if t.get('failureReason')),
            'cancelled' if run['cancelled'] else 'billing_stopped' if run['billing_stopped'] else 'partial')
    return jsonify({'success': True, 'data': response_data})


# ── Cancel endpoint ──────────────────────────────────────────────────────────

@app.route('/api/designer-chat/jobs/<job_id>/cancel', methods=['POST'])
@require_permission('create_presentation')
def api_designer_chat_job_cancel(job_id):
    """Request cancellation of a running designer job; the runner honors it
    between tasks (a task in flight finishes, then the run stops)."""
    try:
        job = _read_job(_AGENT_JOB_NS, g.tenant_id, job_id)
    except Exception:
        job = None
    if not isinstance(job, dict):
        return jsonify({'success': False, 'error': 'المهمة غير موجودة'}), 404
    if job.get('status') not in ('queued', 'running'):
        return jsonify({'success': False, 'error': 'المهمة انتهت بالفعل'}), 409
    # A marker file, not a job-document edit: the runner's checkpoint writes
    # cannot race away a cancel click because this file is never rewritten.
    if not _agent_job_mark_cancelled({'job_id': job_id, 'tenant_id': g.tenant_id}):
        return jsonify({'success': False, 'error': 'تعذر تسجيل طلب الإيقاف'}), 500
    return jsonify({'success': True, 'cancelRequested': True})
