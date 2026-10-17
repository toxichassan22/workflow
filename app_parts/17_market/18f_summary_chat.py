

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Market summary chat: a per-axis discuss/research turn plus the final
# consolidate pass. Every message is a market job — phase A answers with
# optional targeted ops, phase B re-asks through provider-native Google
# search (same owner-ordered protocol as the summary: zero page opens) when
# the turn needs fresh evidence. Ops are validated and proposed, never
# applied server-side; an approved market-study section locks op-producing
# turns while pure discussion keeps answering.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


_SUMMARY_CHAT_MESSAGE_MAX = 4000
_SUMMARY_CHAT_HISTORY_MAX = 12
_SUMMARY_CHAT_SOURCES_MAX = 8

# One chat turn's research is a targeted native-search follow-up — a short
# forced Google search, far below the full summary sweep.
_SUMMARY_CHAT_MAX_STEPS = 8
_SUMMARY_CHAT_RESEARCH_MAX_OUTPUT_TOKENS = 66000

# The research phase gets its own short wall-clock budget — a chat reply
# cannot sit on a multi-minute sweep the way the full summary job can.
try:
    _SUMMARY_CHAT_JOB_TIME_BUDGET = max(30, int(os.environ.get('SUMMARY_CHAT_JOB_TIME_BUDGET') or 120))
except (TypeError, ValueError):
    _SUMMARY_CHAT_JOB_TIME_BUDGET = 120

_SUMMARY_CHAT_STALE_KEYS = ('one_block', 'decision', 'swot')


def _summary_chat_model():
    """MARKET_CHAT_MODEL stays an owner override; unset it falls back to the
    tenant-chat model every other chat surface uses."""
    return str(os.environ.get('MARKET_CHAT_MODEL') or '').strip() or GEMINI_TEXT_MODEL


def _summary_chat_axis(value):
    """Resolve the thread axis: a SUMMARY_SECTIONS key or the general thread."""
    axis = str(value or '').strip()
    if not axis or axis == market_study.SUMMARY_CHAT_AXIS_GENERAL:
        return market_study.SUMMARY_CHAT_AXIS_GENERAL
    if axis in {item['key'] for item in market_study.SUMMARY_SECTIONS}:
        return axis
    return None


def _summary_chat_history(raw):
    """Caller sends the last messages of this thread; keep real turns only."""
    history = []
    items = raw if isinstance(raw, list) else []
    for item in items[-_SUMMARY_CHAT_HISTORY_MAX:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get('role') or '').strip()
        content = str(item.get('content') or '').strip()[:_SUMMARY_CHAT_MESSAGE_MAX]
        if role in ('user', 'assistant') and content:
            history.append({'role': role, 'content': content})
    return history


def _summary_chat_state(data):
    """The market summary's live state rides in the request, like the summary
    executor's currentSummary/currentSources/currentSwot — nothing is stored."""
    summary = data.get('currentSummary')
    sources = data.get('currentSources')
    swot = data.get('currentSwot')
    return {
        'summary': summary if isinstance(summary, dict) else {},
        'sources': sources if isinstance(sources, list) else [],
        'swot': swot if isinstance(swot, dict) else {},
        'decision': str(data.get('decision') or '').strip(),
        'one_block_summary': str(data.get('oneBlockSummary')
                                 or data.get('one_block_summary') or '').strip(),
    }


def _market_summary_section_approved(data, tenant_id):
    """The market summary's approval flag is the section status the
    section-status route writes on the draft — the same flag that route
    checks. A chat turn is stateless, so a missing or unreadable draft simply
    has no lock to check."""
    draft_id = str(data.get('draftId') or data.get('draft_id') or '').strip()
    if not draft_id or not tenant_id:
        return False
    try:
        draft = db.get_project_draft_by_id(tenant_id, draft_id)
    except Exception:
        return False
    statuses = (draft or {}).get('section_statuses') or {}
    return statuses.get('section-market-study') == 'approved'


def _summary_chat_lock_result():
    return {
        'success': False,
        'error': 'ملخص السوق معتمد — التعديل مقفل حتى إلغاء اعتماد القسم.',
        'error_code': 'SUMMARY_APPROVAL_LOCKED',
        'failureReason': 'approval_locked',
        'httpStatus': 409,
    }


def _summary_chat_validated_ops(ops):
    """validate_summary_ops drops unknown ops/keys/decisions and reports the
    rejects; accept either a bare kept-list or a (kept, rejected) pair."""
    validated = market_study.validate_summary_ops(ops)
    rejected = []
    if isinstance(validated, tuple) and len(validated) == 2:
        validated, rejected = validated
    elif isinstance(validated, dict):
        validated, rejected = validated.get('ops'), validated.get('rejected')
    return (validated if isinstance(validated, list) else [],
            rejected if isinstance(rejected, list) else [])


def _summary_chat_prepare_sources(rows, citations, search_ran, payload):
    """Run proposed source rows through the summary executor's own pipeline:
    citation resolution, dead-link flagging (or unverified marking when no
    search actually ran), and the binding data-period check."""
    prepared = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get('url') or '').strip()
        if url and url.casefold() in seen:
            continue
        if url:
            seen.add(url.casefold())
        prepared.append(dict(row))
        if len(prepared) >= _SUMMARY_CHAT_SOURCES_MAX:
            break
    if not prepared:
        return prepared
    market_study.apply_search_citations(prepared, citations, url_key='url')
    if search_ran:
        dead_urls = _verify_market_urls(row.get('url') for row in prepared)
        for row in prepared:
            url = str(row.get('url') or '').strip()
            if url and url in dead_urls:
                row['dead_url'] = url
                note = str(row.get('note') or '').strip()
                row['note'] = (note + ' — ' if note else '') + 'الرابط لم يعد يعمل'
    else:
        # Claimed links without a real search behind them stay visible but
        # flagged — the owner reviews them instead of trusting model memory.
        marker = 'رابط غير موثق — لم يصل من نتائج البحث'
        for row in prepared:
            if str(row.get('url') or '').strip():
                row['sources_unverified'] = True
            note = str(row.get('note') or '').strip()
            if marker not in note:
                row['note'] = f'{note} — {marker}' if note else marker
    market_study.flag_out_of_period_sources(prepared, payload.get('dataPeriodBounds'))
    return prepared


def _summary_chat_fatal_or_credit(res, provider_error, parse_error, fallback_error):
    """The summary executor's failure idiom: a deterministic wallet/key
    refusal surfaces as insufficient_credit, any other parse miss keeps its
    reason."""
    fatal = _ai_fatal_error_dict(res)
    credit = (fatal is not None or _is_company_credit_error(provider_error or '')
              or 'afford' in (provider_error or '').lower())
    wallet_msg = ((fatal or {}).get('message') or provider_error or '').strip()
    return {
        'success': False,
        'error': wallet_msg if credit and wallet_msg else fallback_error,
        'failureReason': 'insufficient_credit' if credit else parse_error,
        'providerError': provider_error,
    }


def _execute_market_summary_chat(data, tenant_id=None, progress=None):
    report = progress if callable(progress) else (lambda *_args: None)
    chat_model = _summary_chat_model()
    payload = _prepare_market_payload(data, tenant_id)
    message = str(data.get('message') or '').strip()[:_SUMMARY_CHAT_MESSAGE_MAX]
    if not message:
        return {'success': False, 'error': 'الرسالة مطلوبة.',
                'error_code': 'MESSAGE_REQUIRED', 'failureReason': 'message_required'}
    axis = _summary_chat_axis(data.get('axis'))
    if axis is None:
        return {'success': False, 'error': 'محور الملخص غير معروف.',
                'error_code': 'AXIS_UNKNOWN', 'failureReason': 'axis_unknown'}
    # No pinned axis (the general/auto thread) — the model names the axis its
    # reply actually handles; the detected key steers phase-B context and is
    # echoed back so the client can show what the message was routed to.
    auto_axis = axis == market_study.SUMMARY_CHAT_AXIS_GENERAL
    research_allowed = str(data.get('research') or 'auto').strip().lower() != 'off'
    history = _summary_chat_history(data.get('history'))
    state = _summary_chat_state(data)
    offer_lang = slide_engine.resolve_offer_lang(data)
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None
    system_prompt = market_study.build_summary_chat_system(offer_lang)
    training_context = (db.get_training_context(tenant_id, surface='content', offer_lang=offer_lang)
                        if tenant_id else '')
    if training_context:
        system_prompt += f"\n\n## بيانات خاصة بالشركة\n{training_context}"
    if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
        system_prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
    usage_ctx = _usage_ctx('market', data, tenant_id=tenant_id)
    usage_ctx['billing_flow'] = 'market_summary'

    # Phase A — discuss: one JSON answer with the reply, an optional research
    # request, and the ops the model proposes (displayed, never applied here).
    report(18, 'جاري إعداد الرد على محور الملخص...')
    turn_prompt = market_study.build_summary_chat_turn_prompt(
        payload, axis, message, history, state)
    res = call_text_chat(system_prompt, turn_prompt, max_tokens=4000,
                         response_format={'type': 'json_object'},
                         model=chat_model, usage_ctx=usage_ctx)
    provider_error = _chat_error_message(res) if res.get('error') else ''
    parsed, parse_error = _parse_market_model_json(res)
    if parse_error:
        return _summary_chat_fatal_or_credit(res, provider_error, parse_error,
                                             'تعذر إعداد رد ملخص السوق.')
    try:
        turn = market_study.normalize_summary_chat_reply(parsed)
    except ValueError as exc:
        return {'success': False, 'error': str(exc) or 'تعذر قراءة رد النموذج.',
                'failureReason': 'invalid_json', 'providerError': provider_error}

    reply = str(turn.get('reply') or '').strip()
    ops = turn.get('ops') if isinstance(turn.get('ops'), list) else []
    sources_add = []
    citations = []
    search_performed = False
    detected_axis = str(turn.get('axis') or '').strip() if auto_axis else axis
    if detected_axis not in {item['key'] for item in market_study.SUMMARY_SECTIONS} \
            and detected_axis != market_study.SUMMARY_CHAT_AXIS_GENERAL:
        detected_axis = market_study.SUMMARY_CHAT_AXIS_GENERAL
    # A clarification turn is a question back to the user — never an edit
    # proposal and never a browse run.
    clarification = bool(turn.get('needs_clarification'))
    if clarification:
        ops = []

    # Phase B — live research inside the same binding scope/period, only when
    # the model asked for it and the caller did not forbid it. The researched
    # answer replaces phase A's reply/ops: it saw the retrieved pages.
    if turn.get('needs_research') and research_allowed and not clarification:
        report(46, 'جاري البحث في الويب داخل نطاق المشروع...')
        research_prompt = market_study.build_summary_chat_research_prompt(
            payload, detected_axis, message, history, state, turn.get('queries') or [],
            offer_lang=offer_lang)
        # The turn shares the job contract: one evidence pool and one
        # deadline bound the native search like every other market search.
        chat_pool = _new_evidence_pool()
        research_res = _browse_agent_call(
            system_prompt, research_prompt, usage_ctx, model=GEMINI_TEXT_MODEL,
            evidence_pool=chat_pool,
            deadline=time.time() + _SUMMARY_CHAT_JOB_TIME_BUDGET,
            local_tools=True, search_provider='searxng', search_budget=3,
            max_steps=_SUMMARY_CHAT_MAX_STEPS,
            max_tokens=_SUMMARY_CHAT_RESEARCH_MAX_OUTPUT_TOKENS,
            reasoning_effort='low',
            on_event=_market_agent_progress(report, 46, 68,
                                            'بحث الويب عن المحور'))
        research_error = (_chat_error_message(research_res)
                          if research_res.get('error') else '')
        citations = list(_market_citation_urls(research_res))
        if chat_pool is not None:
            for _pool_page in chat_pool.pages():
                _pool_url = str((_pool_page or {}).get('url') or '').strip()
                if _pool_url:
                    citations.append(_pool_url)
        citations = list(dict.fromkeys(citations))
        search_performed = _market_search_ran(research_res)
        research_parsed, research_parse_error = _parse_market_model_json(research_res)
        if research_parse_error:
            provider_error = provider_error or research_error or research_parse_error
        else:
            try:
                researched = market_study.normalize_summary_chat_research(research_parsed)
                reply = str(researched.get('reply') or '').strip() or reply
                if isinstance(researched.get('ops'), list):
                    ops = researched['ops']
                if isinstance(researched.get('sources_add'), list):
                    sources_add = researched['sources_add']
            except ValueError:
                provider_error = provider_error or 'invalid_research_json'

    valid_ops, rejected_ops = _summary_chat_validated_ops(ops)
    claimed_rows = []
    kept_ops = []
    for op in valid_ops:
        if isinstance(op, dict) and op.get('op') == 'add_sources':
            claimed_rows.extend(op.get('rows') or [])
        else:
            kept_ops.append(op)
    claimed_rows.extend(sources_add)
    source_rows = _summary_chat_prepare_sources(
        claimed_rows, citations, search_performed, payload)
    final_ops = list(kept_ops)
    if source_rows:
        final_ops.append({'op': 'add_sources', 'rows': source_rows})

    proposal = None
    if final_ops:
        if _market_summary_section_approved(data, tenant_id):
            return _summary_chat_lock_result()
        _applied, touched = market_study.apply_summary_ops(
            copy.deepcopy(state), final_ops)
        proposal = {
            'ops': final_ops,
            'touchedAxes': sorted(str(item) for item in (touched or [])),
            'sourcesAdd': source_rows,
        }
    result = {
        'success': True,
        'reply': reply,
        'axis': detected_axis,
        'proposal': proposal,
        'searchPerformed': search_performed,
        'citations': citations,
    }
    if clarification:
        result['clarification'] = True
    if rejected_ops:
        result['rejectedOps'] = rejected_ops
    if provider_error:
        result['providerError'] = provider_error
    return result


def _execute_market_summary_consolidate(data, tenant_id=None, progress=None):
    """Regenerate only the dependents the applied ops staled — the axes and
    sources are final already, so this is a rewrite pass with no browsing."""
    report = progress if callable(progress) else (lambda *_args: None)
    chat_model = _summary_chat_model()
    payload = _prepare_market_payload(data, tenant_id)
    raw_stale = data.get('stale')
    if isinstance(raw_stale, dict):
        stale_keys = [key for key in _SUMMARY_CHAT_STALE_KEYS if raw_stale.get(key)]
    elif isinstance(raw_stale, (list, tuple, set)):
        stale_keys = [key for key in _SUMMARY_CHAT_STALE_KEYS if key in raw_stale]
    else:
        stale_keys = []
    if not stale_keys:
        return {'success': False, 'error': 'لا توجد مخرجات معلّمة للتحديث.',
                'error_code': 'STALE_KEYS_REQUIRED', 'failureReason': 'stale_keys_required'}
    if _market_summary_section_approved(data, tenant_id):
        return _summary_chat_lock_result()
    summary = data.get('summary')
    sources = data.get('sources')
    swot = data.get('swot')
    state = {
        'summary': summary if isinstance(summary, dict) else {},
        'sources': sources if isinstance(sources, list) else [],
        'swot': swot if isinstance(swot, dict) else {},
        'decision': str(data.get('decision') or '').strip(),
        'one_block_summary': str(data.get('one_block_summary')
                                 or data.get('oneBlockSummary') or '').strip(),
    }
    offer_lang = slide_engine.resolve_offer_lang(data)
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None
    system_prompt = market_study.build_summary_chat_system(offer_lang)
    training_context = (db.get_training_context(tenant_id, surface='content', offer_lang=offer_lang)
                        if tenant_id else '')
    if training_context:
        system_prompt += f"\n\n## بيانات خاصة بالشركة\n{training_context}"
    if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
        system_prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
    usage_ctx = _usage_ctx('market', data, tenant_id=tenant_id)
    usage_ctx['billing_flow'] = 'market_summary'
    report(40, 'جاري إعادة توليد المخرجات المعلّمة...')
    prompt = market_study.build_summary_consolidate_prompt(state, stale_keys, offer_lang)
    res = call_text_chat(system_prompt, prompt, max_tokens=6000,
                         response_format={'type': 'json_object'},
                         model=chat_model, usage_ctx=usage_ctx)
    provider_error = _chat_error_message(res) if res.get('error') else ''
    parsed, parse_error = _parse_market_model_json(res)
    if parse_error:
        return _summary_chat_fatal_or_credit(res, provider_error, parse_error,
                                             'تعذر تحديث مخرجات الملخص.')
    result = {'success': True}
    if 'one_block' in stale_keys:
        one_block = slide_engine._strip_presentation_icons(
            str(parsed.get('one_block_summary') or '').strip())
        if one_block:
            result['one_block_summary'] = one_block
    if 'decision' in stale_keys:
        decision = str(parsed.get('decision') or '').strip()
        if decision not in market_study.DECISION_OPTIONS:
            decision = next((option for option in market_study.DECISION_OPTIONS
                             if option in decision), '')
        if decision:
            result['decision'] = decision
    if 'swot' in stale_keys:
        raw_swot = parsed.get('swot')
        if isinstance(raw_swot, dict):
            regenerated = {
                item['key']: slide_engine._strip_presentation_icons(
                    str(raw_swot.get(item['key']) or '').strip())
                for item in market_study.SWOT_SECTIONS
            }
            if any(regenerated.values()):
                result['swot'] = regenerated
    if len(result) == 1:
        return {'success': False, 'error': 'عاد النموذج بلا قيم قابلة للتحديث.',
                'failureReason': 'empty_response', 'providerError': provider_error}
    if provider_error:
        result['providerError'] = provider_error
    return result


@app.route('/api/market-study/summary/chat', methods=['POST'])
@require_permission('create_presentation')
def api_market_study_summary_chat():
    data = request.json or {}
    message = str(data.get('message') or '').strip()
    if not message or len(message) > _SUMMARY_CHAT_MESSAGE_MAX:
        return jsonify({'success': False, 'error_code': 'MESSAGE_REQUIRED',
                        'error': 'الرسالة مطلوبة بحد أقصى 4000 حرف.'}), 400
    if _summary_chat_axis(data.get('axis')) is None:
        return jsonify({'success': False, 'error_code': 'AXIS_UNKNOWN',
                        'error': 'محور الملخص غير معروف.'}), 400
    return _start_market_job('summary_chat', _execute_market_summary_chat)


@app.route('/api/market-study/summary/consolidate', methods=['POST'])
@require_permission('create_presentation')
def api_market_study_summary_consolidate():
    return _start_market_job('summary_consolidate', _execute_market_summary_consolidate)
