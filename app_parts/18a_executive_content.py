


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Executive content generation endpoint: rewrites one
# executive-content block from already collected project facts.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@app.route('/api/executive-content/generate', methods=['POST'])
@require_permission('create_presentation')
def api_generate_executive_content():
    """Rewrite one executive-content block from already collected project facts."""
    data = request.json or {}
    _billing_guard = _require_billing_balance('executive_content')
    if _billing_guard is not None:
        return _billing_guard
    key = str(data.get('block') or '').strip()
    spec = executive_content.block_spec(key)
    if not spec:
        return jsonify({'success': False, 'error': 'عنصر محتوى غير صالح'}), 400
    facts = data.get('facts') if isinstance(data.get('facts'), dict) else {}
    ready, missing = executive_content.block_ready(key, facts)
    if not ready:
        labels = {
            'basic': 'البيانات الأساسية',
            'location': 'الموقع',
            'land': 'الأرض والكروكي',
            'timeline': 'الجدول الزمني',
            'financial': 'الدراسة المالية',
            'market': 'دراسة السوق',
        }
        needed = ' و'.join(labels.get(name, name) for name in missing) or 'المدخلات المطلوبة'
        return jsonify({
            'success': False,
            'error': 'استكمل ' + needed + ' قبل توليد هذا النص',
            'missing': missing,
        }), 400
    current = data.get('currentText')
    offer_lang = slide_engine.resolve_offer_lang(facts)
    prompt = executive_content.build_user_prompt(key, facts, current, offer_lang=offer_lang)
    if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
        prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
    cap = EXECUTIVE_SUMMARY_MAX_TOKENS if key in ('summary', 'risks') else EXECUTIVE_CONTENT_MAX_TOKENS
    system_prompt = executive_content.SYSTEM_PROMPT
    training_context = db.get_training_context(g.tenant_id, surface='content') or ''
    if training_context:
        system_prompt += f"\n\n## بيانات خاصة بالشركة\n{training_context}"
    if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
        system_prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
    raw = None
    last_error = None
    try:
        for attempt in range(3):
            try:
                response = call_zai_chat(
                    system_prompt, prompt, temperature=0.2,
                    max_tokens=cap,
                    reasoning_effort='low',
                    response_format={'type': 'json_object'},
                    usage_ctx=_usage_ctx('executive', data),
                )
                if isinstance(response, dict) and 'error' in response:
                    msg = _chat_error_message(response)
                    affordable = _AFFORDABLE_TOKENS_RE.search(msg)
                    if affordable:
                        retry_cap = max(8000, int(int(affordable.group(1)) * 0.85))
                        if retry_cap < cap:
                            print(f'[EXECUTIVE CONTENT] provider cap refused={cap}; retrying with {retry_cap}')
                            cap = retry_cap
                            continue
                    raise RuntimeError(msg)
                raw = _get_chat_response_text(response) or extract_chat_content(response, 'EXECUTIVE-CONTENT')
                break
            except Exception as primary_error:
                last_error = primary_error
                if not _has_any_openrouter_key(_usage_ctx('executive', data)):
                    raise
                print(f'[EXECUTIVE CONTENT PRIMARY ERROR] {primary_error}. Trying OpenRouter fallback...')
                fallback = call_openrouter_chat(
                    system_prompt,
                    prompt,
                    temperature=0.2,
                    max_tokens=cap,
                    model=LUNA_TEXT_MODEL,
                    reasoning_effort='low',
                    usage_ctx=_usage_ctx('executive', data),
                    response_format={'type': 'json_object'},
                )
                if isinstance(fallback, dict) and 'error' in fallback:
                    msg = _chat_error_message(fallback)
                    affordable = _AFFORDABLE_TOKENS_RE.search(msg)
                    if affordable:
                        retry_cap = max(8000, int(int(affordable.group(1)) * 0.85))
                        if retry_cap < cap:
                            print(f'[EXECUTIVE CONTENT] fallback cap refused={cap}; retrying with {retry_cap}')
                            cap = retry_cap
                            continue
                raw = _get_chat_response_text(fallback) or extract_chat_content(fallback, 'EXECUTIVE-CONTENT-FALLBACK')
                if raw:
                    break
        if not raw and last_error:
            raise last_error
        parsed = parse_json_object(raw) or {}
        text = executive_content.parse_generated_block(key, parsed)
        if not text and raw and isinstance(raw, str):
            cleaned_raw = executive_content.clean_raw_json_string(raw)
            cleaned_raw = re.sub(r'^```(?:json)?\s*', '', str(cleaned_raw).strip(), flags=re.MULTILINE)
            cleaned_raw = re.sub(r'\s*```$', '', cleaned_raw.strip(), flags=re.MULTILINE)
            text = executive_content.normalize_document(cleaned_raw) if spec.get('output') in ('document', 'risks') else executive_content.normalize_text(cleaned_raw)
        empty = not str(text or '').strip()
        if empty:
            return jsonify({'success': False, 'error': 'عاد النموذج نصًا فارغًا. لم يُستبدل النص الحالي.'}), 422
        return jsonify({'success': True, 'block': key, 'text': text})
    except Exception as error:
        print(f'[EXECUTIVE CONTENT AI ERROR] {error}')
        return jsonify({
            'success': False,
            'error': 'تعذر توليد المحتوى التنفيذي: ' + str(error),
        }), 503
