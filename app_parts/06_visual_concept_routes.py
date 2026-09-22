

@app.route('/api/visual-concept/plans-verify', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plans_verify():
    data = request.get_json(silent=True) or {}
    _billing_guard = _require_billing_balance('visual_concept')
    if _billing_guard is not None:
        return _billing_guard
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    context = _visual_concept_plan_context(project_data)
    regulations = context.get('regulations') if isinstance(context.get('regulations'), dict) else {}
    context['regulations'] = regulations

    # Saudi Building Code evidence — the second official source of truth next to
    # the municipal digest. Bounded snippets join the facts the model compares
    # against; the page list is kept for internal traceability.
    sbc_query = ' '.join(str(part) for part in [
        'إشغال مخارج مواقف ارتفاع طوابق مداخل منافذ إعاقة منحدر',
        regulations.get('land_use'), regulations.get('zoning_code'),
        ' '.join(_visual_concept_text(item.get('name'), 60)
                 for item in (context.get('components') or [])[:12]),
    ] if part)
    try:
        sbc_packet, sbc_warnings = search_sbc_evidence(sbc_query, regulations)
    except Exception as sbc_error:
        sbc_packet, sbc_warnings = {'context': '', 'pages': [], 'matched': False}, [
            f'تعذر قراءة كود البناء السعودي: {sbc_error}']
    if sbc_packet.get('context'):
        regulations['saudi_building_code'] = _visual_concept_text(sbc_packet['context'], 9000)
        sources = regulations.get('regulatory_sources')
        sources = sources if isinstance(sources, list) else []
        if 'كود البناء السعودي' not in sources:
            sources.append('كود البناء السعودي')
        regulations['regulatory_sources'] = sources

    system_prompt = (
        'أنت مدقق اتساق لرسومات تخطيطية مفاهيمية لمشروع عقاري. '
        'قارن فقط بين بيانات المشروع المسجلة والبيانات التنظيمية الموثقة المجهولة أدناه. '
        'لا تصدر شهادة قانونية ولا تعتبر أي نقص موافقة أو رفضًا نهائيًا. ميّز بين التعارض، والقيمة الناقصة، والقيمة التي تحتاج تأكيدًا. '
        'لا تذكر أبدًا أسماء ملفات أو أرقام صفحات أو عبارة ملف اشتراط 1 أو ملف اشتراط 2 أو أي مصدر داخلي. '
        'استخدم بدل ذلك «البيانات التنظيمية الموثقة». أخرج JSON فقط: '
        '{"checks":[{"item":"","field":"","section":"","project":"","regulatory":"","result":"مطابق|متعارض|يحتاج تأكيد|غير متوفر","issues":[""],"suggestion":"حل محدد مع اسم القسم والقيمة من وإلى عند توفرهما","action":""}],'
        '"issues":[{"title":"","points":[""],"suggestion":"حل محدد قابل للتنفيذ","action":"","severity":"high|medium|low"}],"summary":"","canProceed":true}'
    )
    user_prompt = (
        'هذه هي المدخلات المسموح بفحصها فقط:\n' +
        json.dumps(_visual_concept_plan_regulation_input(project_data, context), ensure_ascii=False) +
        '\nرتّب كل مشكلة كنقاط قصيرة قابلة للمتابعة، ولا تكتب فقرة طويلة. '
        'لكل تعارض اكتب suggestion واضحًا يذكر اسم القسم أو الحقل، القيمة الحالية، القيمة الموثقة، والتعديل المقترح من قيمة إلى قيمة. '
        'إذا كانت المقارنة غير مباشرة مثل إجمالي المسطحات مقابل FAR، لا تقترح تغيير الرقم عشوائيًا؛ اقترح فصل تعريفات المساحة وتحديد القيمة التي تدخل في المقارنة. '
        'لا تذكر أسماء أو أرقام مصادر داخل النتيجة.'
    )
    result = {}
    try:
        response = call_openrouter_chat(
            system_prompt, user_prompt, temperature=None, max_tokens=8000,
            model=SLIDE_TEXT_MODEL, reasoning_effort='medium',
            response_format={'type': 'json_object'}, usage_ctx=_usage_ctx('image', data))
        result = parse_json_object(_get_chat_response_text(response))
    except Exception:
        result = {}
    verification = _visual_concept_plan_normalize_verification(result) if result else _visual_concept_plan_fallback_verification(context)
    existing_points = (context.get('regulations') or {}).get('existing_review_points') or []
    for point in existing_points:
        if not any(point in issue.get('points', []) for issue in verification.get('issues', [])):
            verification.setdefault('issues', []).append({
                'id': str(len(verification.get('issues', [])) + 1),
                'title': 'مراجعة بيانات موثقة',
                'points': [point],
                'action': 'مراجعة القيمة قبل الاعتماد.',
                'severity': 'medium'
            })
    for warning in sbc_warnings:
        verification.setdefault('issues', []).append({
            'id': str(len(verification.get('issues', [])) + 1),
            'title': 'كود البناء السعودي',
            'points': [_visual_concept_plan_sanitize_text(warning)],
            'action': 'التحقق من توفر المصدر الرسمي ثم إعادة التحقق.',
            'severity': 'medium'
        })
    return jsonify({'success': True, 'verification': verification, 'planContext': context, 'context': {
        'boundaryPointCount': len(context.get('boundary_points') or []),
        'componentCount': len(context.get('components') or []),
    }, 'evidence': {'sbc_matched': bool(sbc_packet.get('matched')), 'sbc_pages': sbc_packet.get('pages') or []}})


@app.route('/api/visual-concept/plans-boundary', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plans_boundary():
    data = request.get_json(silent=True) or {}
    workflow_error = _visual_concept_plan_workflow_error(data, 'plan_site')
    if workflow_error:
        return jsonify(workflow_error), 400
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    points = _visual_concept_plan_boundary_points(data.get('points') or project_data.get('survey_coordinates'))
    instruction = _visual_concept_text(data.get('instruction'), 2000)
    if str(data.get('mode') or '').lower() == 'ai':
        _billing_guard = _require_billing_balance('visual_concept')
        if _billing_guard is not None:
            return _billing_guard
        system_prompt = (
            'أنت محرر حدود مساحية لمخطط مفاهيمي. أعد JSON فقط بالشكل '
            '{"points":[{"point":"","eastings":0,"northings":0}],"reply":""}. '
            'حافظ على ترتيب النقاط وشكل الحدود، ولا تغيّر أي إحداثي إلا إذا طلب المستخدم ذلك صراحة. '
            'لا تخترع نقطة أو قيمة غير موجودة، ولا تذكر أسماء ملفات أو مصادر.'
        )
        user_prompt = (
            'الإحداثيات الحالية:\n' + json.dumps(points, ensure_ascii=False) +
            '\nطلب التعديل:\n' + instruction
        )
        try:
            response = call_openrouter_chat(
                system_prompt, user_prompt, temperature=None, max_tokens=4000,
                model=SLIDE_TEXT_MODEL, reasoning_effort='medium',
                response_format={'type': 'json_object'}, usage_ctx=_usage_ctx('image', data))
            parsed = parse_json_object(_get_chat_response_text(response))
            ai_points = _visual_concept_plan_boundary_points(parsed.get('points') if isinstance(parsed, dict) else [])
            if ai_points:
                points = ai_points
            reply = _visual_concept_plan_sanitize_text(parsed.get('reply') if isinstance(parsed, dict) else '')
        except Exception as error:
            return jsonify({'success': False, 'error': 'تعذر تعديل حدود الأرض بالذكاء الاصطناعي', 'detail': str(error)[:300]}), 503
    else:
        reply = ''
    if len(points) < 3:
        return jsonify({'success': False, 'error': 'لا توجد ثلاث نقاط إحداثية مكتملة على الأقل'}), 400
    reference_url = _visual_concept_render_plan_boundary_reference(points, g.tenant_id)
    return jsonify({'success': True, 'points': points, 'referenceUrl': reference_url, 'reply': reply})


def _visual_concept_plans_context_from_request(data):
    """Shared context assembly for the plans workflow endpoints: boundary points
    from the approved boundary stage (or the recorded survey), then the cached
    planContext when the verify step already built it."""
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    boundary = workflow.get('boundary') if isinstance(workflow.get('boundary'), dict) else {}
    points = _visual_concept_plan_boundary_points(
        boundary.get('points') or project_data.get('survey_coordinates'))
    context = workflow.get('planContext') if isinstance(workflow.get('planContext'), dict) else None
    context = context or _visual_concept_plan_context(project_data, points, workflow.get('verification'))
    context['boundary_points'] = points or context.get('boundary_points') or []
    return project_data, workflow, boundary, points, context


@app.route('/api/visual-concept/plans-distribution', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plans_distribution():
    data = request.get_json(silent=True) or {}
    workflow_error = _visual_concept_plan_workflow_error(data, 'plan_site')
    if workflow_error:
        return jsonify(workflow_error), 400
    _billing_guard = _require_billing_balance('visual_concept')
    if _billing_guard is not None:
        return _billing_guard
    project_data, workflow, _boundary, _points, context = _visual_concept_plans_context_from_request(data)
    regulations = context.get('regulations') if isinstance(context.get('regulations'), dict) else {}
    system_prompt = (
        'أنت مخطط معماري مفاهيمي. وزّع مكونات المشروع المعتمدة على المباني والأدوار في جدول. '
        'أعد JSON فقط: {"rows":[{"building":"","floor_range":"","component":"","units_per_floor":0,'
        '"floor_area_sqm":0,"circulation":""}],"notes":[""]}. '
        'صيغ floor_range بالعربية فقط: "أرضي"، "ميزانين"، "بدروم 1" أو "بدروم 1-3" للقبو، '
        '"1-4" لنطاق أدوار رقمي، "ملحق علوي" للسطح. '
        'component هو اسم الاستخدام فقط (سكني، تجاري، خدمات، مواقف...) دون اسم الدور — '
        'الدور موجود في floor_range. '
        'التزم بسقوف الارتفاع ونسبة التغطية والارتدادات الموثقة، ووزّع الوحدات بحيث يطابق إجماليها '
        'الوحدات والمساحات المطلوبة في بيانات المشروع، وراعِ العلاقات بين الاستخدامات (فصل مداخل '
        'الفندق عن السكن، الخدمات أسفلًا أو على السطح). لا تخترع مكونًا غير مدخل ولا تسقط مكونًا '
        'معتمدًا، ولا تذكر أسماء ملفات أو مصادر.'
    )
    user_prompt = (
        'بيانات المشروع المعتمدة الوحيدة المسموح الاعتماد عليها:\n'
        + _visual_concept_plan_context_text(context, diagram_rules=False)
        + '\nأعد جدول التوزيع المقترح: كل صف = مبنى + دور أو نطاق أدوار + مكوّن + عدد الوحدات لكل دور '
        '+ مساحة الدور الإجمالية + الحركة والخدمات ضمن المساحة.'
    )
    result = {}
    try:
        response = call_openrouter_chat(
            system_prompt, user_prompt, temperature=None, max_tokens=8000,
            model=SLIDE_TEXT_MODEL, reasoning_effort='medium',
            response_format={'type': 'json_object'}, usage_ctx=_usage_ctx('image', data))
        result = parse_json_object(_get_chat_response_text(response))
    except Exception:
        result = {}
    if not isinstance(result, dict) or not result.get('rows'):
        result = _visual_concept_plan_fallback_distribution(context, regulations)
    distribution = _visual_concept_plan_normalize_distribution(result, context, regulations)
    return jsonify({'success': True, 'distribution': distribution, 'planContext': context})


@app.route('/api/visual-concept/plans-distribution-check', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plans_distribution_check():
    """Re-verify an edited distribution. mode 'local' (default) runs only the
    deterministic checks — instant and free; mode 'ai' additionally asks the text
    model for a conflict review against the documented regulations."""
    data = request.get_json(silent=True) or {}
    workflow_error = _visual_concept_plan_workflow_error(data, 'plan_site')
    if workflow_error:
        return jsonify(workflow_error), 400
    _project_data, workflow, _boundary, _points, context = _visual_concept_plans_context_from_request(data)
    regulations = context.get('regulations') if isinstance(context.get('regulations'), dict) else {}
    posted = (data.get('distribution') if isinstance(data.get('distribution'), dict)
              else (workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {}))
    distribution = _visual_concept_plan_normalize_distribution(posted, context, regulations)
    issues = distribution['issues']
    can_proceed = not any(check.get('result') == 'متعارض' for check in distribution['checks'])
    if str(data.get('mode') or '').lower() == 'ai':
        _billing_guard = _require_billing_balance('visual_concept')
        if _billing_guard is not None:
            return _billing_guard
        system_prompt = (
            'أنت مدقق اشتراطات لمخطط مفاهيمي. راجع جدول التوزيع مقابل البيانات التنظيمية الموثقة '
            'فقط. الجدول يعبّر عن: المبنى، الدور أو نطاق الأدوار، الاستخدام، عدد الوحدات لكل دور، '
            'مساحة الدور، والحركة والخدمات — فدقّق فيما يمكن للجدول إثباته فعلًا: الاستخدامات '
            'المسموحة، سقف الارتفاع وعدد الأدوار، حد التغطية، وعدم تجاوز مساحات أو وحدات الدراسة. '
            'لا تكتب بنود «لم يوثّق» عمّا لا يمكن لجدول توزيع إثباته بطبيعته (أبعاد المواقف، '
            'عروض الممرات والمنحدرات، مسافات الإخلاء، تفاصيل الحريق) — فهي مرحلة تصميم لاحقة. '
            'كل بند يجب أن يكون إجراءً واضحًا قابلاً للتنفيذ على الجدول: «عدّل قيمة X في صف Y إلى Z» '
            'أو «أضف مكوّنًا لـ…»، وبحد أقصى 8 بنود مرتبة بالأهمية. '
            'سمّ الصفوف باسم المكوّن والدور («صف سكني في الدور أرضي»)، ولا تذكر معرّفات داخلية. أعد JSON فقط: '
            '{"issues":[{"title":"","points":[""],"suggestion":"","action":"","severity":"high|medium|low"}],"canProceed":true}. '
            'لا تذكر أسماء ملفات أو أرقام صفحات أو مصادر داخلية.'
        )
        user_prompt = (
            'البيانات التنظيمية الموثقة:\n' + json.dumps(regulations, ensure_ascii=False)
            + '\n\nبيانات المشروع المعتمدة:\n'
            + _visual_concept_plan_context_text(context, diagram_rules=False)
            + '\n\nالتوزيع المدخل للمراجعة:\n'
            + json.dumps({'rows': distribution['rows'], 'totals': distribution['totals']},
                         ensure_ascii=False)
        )
        try:
            response = call_openrouter_chat(
                system_prompt, user_prompt, temperature=None, max_tokens=5000,
                model=SLIDE_TEXT_MODEL, reasoning_effort='medium',
                response_format={'type': 'json_object'}, usage_ctx=_usage_ctx('image', data))
            parsed = parse_json_object(_get_chat_response_text(response))
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            issues = _visual_concept_plan_normalize_issues(parsed.get('issues') or [])
            if parsed.get('canProceed') is False:
                can_proceed = False
    return jsonify({'success': True, 'totals': distribution['totals'],
                    'checks': distribution['checks'], 'issues': issues,
                    'canProceed': can_proceed})


def _visual_concept_plan_surgical_rows(old_rows, new_rows, editable_ids):
    """Keep the model's edit surgical: rows no check flagged are restored
    verbatim — the model may edit, merge or drop only the flagged ids, and may
    add brand-new rows (e.g. a study component the table is missing). Untouched
    rows keep their original order; new rows append at the end."""
    old_by_id = {row.get('id'): row for row in old_rows}
    new_by_id = {}
    extra_rows = []
    for row in new_rows:
        rid = row.get('id')
        if rid in old_by_id or rid in new_by_id:
            new_by_id[rid] = row
        else:
            extra_rows.append(row)
    merged = []
    for row in old_rows:
        rid = row.get('id')
        if rid in new_by_id:
            merged.append(new_by_id[rid] if rid in editable_ids else row)
        elif rid not in editable_ids:
            merged.append(row)
    merged.extend(extra_rows)
    return merged


@app.route('/api/visual-concept/plans-distribution-repair', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plans_distribution_repair():
    """Surgical AI repair of a distribution: the findings (checks + issues) go to
    the model with the row ids each finding may touch, then the server restores
    every unflagged row verbatim — so the model fixes what is flagged, never
    rewrites the whole table."""
    data = request.get_json(silent=True) or {}
    workflow_error = _visual_concept_plan_workflow_error(data, 'plan_site')
    if workflow_error:
        return jsonify(workflow_error), 400
    _project_data, workflow, _boundary, _points, context = _visual_concept_plans_context_from_request(data)
    regulations = context.get('regulations') if isinstance(context.get('regulations'), dict) else {}
    posted = (data.get('distribution') if isinstance(data.get('distribution'), dict)
              else (workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {}))
    distribution = _visual_concept_plan_normalize_distribution(posted, context, regulations)
    if not (distribution['rows'] and (distribution['checks'] or distribution['issues'])):
        return jsonify({'success': True, 'distribution': distribution, 'repaired': False})
    _billing_guard = _require_billing_balance('visual_concept')
    if _billing_guard is not None:
        return _billing_guard
    editable_ids = {rid for check in distribution['checks']
                    for rid in (check.get('row_ids') or []) if rid}
    system_prompt = (
        'أنت مخطط معماري مفاهيمي تصحّح جدول توزيع مكونات على الأدوار بناءً على نتيجة فحص آلي. '
        'أعد JSON فقط بالجدول الكامل: {"rows":[{"id":"","building":"","floor_range":"",'
        '"component":"","units_per_floor":0,"floor_area_sqm":0,"circulation":""}],"notes":[""]}. '
        'أدواتك الجراحية: عدّل قيم الصف المعلَّم، أو ادمج صفوف المكوّن الواحد المتداخلة في صف '
        'واحد («أرضي + ميزانين» أو نطاق رقمي)، أو قسّم صفًا إلى نطاقات، أو احذف صفًا متعارضًا، '
        'أو أضف صفًا بمُعرّف id جديد لمكوّن تطلبه الدراسة ولا صف له. '
        'كل بند فحص يحمل row_ids — وهي وحدها الصفوف المسموح تعديلها أو حذفها؛ أي صف آخر '
        'تنسخه حرفيًا بنفس id ونفس القيم دون أي تغيير. '
        'بند فحص بقائمة row_ids فارغة يعني مكوّنًا مطلوبًا في الدراسة لا صف له في الجدول — '
        'أضف له صفًا جديدًا أو أعد تسمية صف معلَّم يضمّه فعلًا. '
        'وإن كان تجاوز معامل البناء أو الحد التنظيمي متأصلًا في البرنامج المعتمد نفسه، '
        'فلا تحلّه بتقليص مساحات دون مجاميع الدراسة — أولويتك مطابقة المجاميع وحل التداخلات. '
        'صيغ floor_range بالعربية فقط: "أرضي"، "ميزانين"، "بدروم 1" أو "بدروم 1-3" للقبو، '
        '"1-4" لنطاق أدوار رقمي، "ملحق علوي" للسطح. component اسم الاستخدام فقط دون اسم الدور. '
        'التزم بسقف الأدوار ومعامل البناء وحد التغطية الموثقة ومجاميع الدراسة، ولا تُنتج '
        'تعارضًا جديدًا ولا تترك فجوة مقابل مكوّن مطلوب. لا تذكر أسماء ملفات أو مصادر.'
    )
    user_prompt = (
        'بيانات المشروع المعتمدة الوحيدة المسموح الاعتماد عليها:\n'
        + _visual_concept_plan_context_text(context, diagram_rules=False)
        + '\n\nالبيانات التنظيمية الموثقة:\n' + json.dumps(regulations, ensure_ascii=False)
        + '\n\nجدول التوزيع الحالي:\n'
        + json.dumps(distribution['rows'], ensure_ascii=False)
        + '\n\nمجاميع التوزيع مقابل المطلوب في الدراسة:\n'
        + json.dumps(distribution['totals'], ensure_ascii=False)
        + '\n\nنتائج الفحص المطلوب معالجتها كلها:\n'
        + json.dumps(distribution['checks'], ensure_ascii=False)
        + ('\n\nملاحظات مراجعة سابقة (استرشادية):\n'
           + json.dumps(distribution['issues'], ensure_ascii=False)
           if distribution['issues'] else '')
    )
    try:
        response = call_openrouter_chat(
            system_prompt, user_prompt, temperature=None, max_tokens=8000,
            model=SLIDE_TEXT_MODEL, reasoning_effort='medium',
            response_format={'type': 'json_object'}, usage_ctx=_usage_ctx('image', data))
        result = parse_json_object(_get_chat_response_text(response))
    except Exception as error:
        return jsonify({'success': False, 'error': 'تعذر إصلاح التوزيع بالذكاء الاصطناعي',
                        'detail': str(error)[:300]}), 503
    if not isinstance(result, dict) or not result.get('rows'):
        return jsonify({'success': False, 'error': 'تعذر إصلاح التوزيع بالذكاء الاصطناعي'}), 503
    candidate = _visual_concept_plan_normalize_distribution(result, context, regulations)
    enforced = _visual_concept_plan_surgical_rows(
        distribution['rows'], candidate['rows'], editable_ids)
    repaired = _visual_concept_plan_normalize_distribution(
        {'rows': enforced, 'issues': result.get('issues')}, context, regulations)
    return jsonify({'success': True, 'distribution': repaired, 'repaired': True})


@app.route('/api/visual-concept/plans-prompts', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plans_prompts():
    data = request.get_json(silent=True) or {}
    workflow_error = _visual_concept_plan_workflow_error(
        data, 'plan_site', require_boundary=True, require_distribution=True)
    if workflow_error:
        return jsonify(workflow_error), 400
    _billing_guard = _require_billing_balance('visual_concept')
    if _billing_guard is not None:
        return _billing_guard
    project_data, workflow, boundary, points, context = _visual_concept_plans_context_from_request(data)
    regulations = context.get('regulations') if isinstance(context.get('regulations'), dict) else {}
    distribution = workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {}
    # The approved-facts spec is always built deterministically from the approved
    # distribution; sol only rewrites the DRAWING REQUESTED body, so a model pass
    # can no longer drop an approved mass or swap an entry direction.
    model = (_visual_concept_plan_model_from_distribution(distribution, context, regulations)
             or _visual_concept_plan_model(context, regulations))
    spec = _visual_concept_plan_distribution_spec(context, model, regulations)
    bodies = {
        'site': _visual_concept_plan_site_body(context, model, regulations),
        'uses': _visual_concept_plan_uses_body(context, model, regulations),
        'massing': _visual_concept_plan_massing_body(context, model, regulations),
    }
    adapted = _visual_concept_plan_adapt_bodies(distribution, bodies, data)
    prompts = {}
    for definition in VISUAL_CONCEPT_PLAN_DEFINITIONS:
        kind = definition['kind']
        prompts[kind] = (_visual_concept_plan_prompt_header(kind, context) + spec + '\n'
                         + (adapted.get(kind) or bodies[kind]))
    return jsonify({'success': True, 'prompts': prompts, 'context': context,
                    'referenceUrl': boundary.get('referenceUrl') or ''})


@app.route('/api/visual-concept/preflight', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_preflight():
    data = request.get_json(silent=True) or {}
    slot_id = _visual_concept_normalize_slot(data.get('slotId') or 'cover') or 'cover'
    _project_data, facts, missing = _visual_concept_request_bundle(data, slot_id)
    return jsonify({
        'success': not missing,
        'slotId': slot_id,
        'missingFields': missing,
        'facts': {
            'project_name': facts.get('project_name'),
            'hasStyleReference': bool(facts.get('style_reference_file_ids')),
            'hasOverviewMap': bool(facts.get('overview_map_url')),
            'componentCount': len(facts.get('components') or []),
            'components': facts.get('components') or [],
        },
        'error': 'أكمل الحقول الناقصة قبل توليد التصور البصري' if missing else None,
        'error_code': 'VISUAL_CONCEPT_DATA_INCOMPLETE' if missing else None,
    }), (400 if missing else 200)


@app.route('/api/visual-concept/prompt', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_prompt():
    data = request.get_json(silent=True) or {}
    slot_id = _visual_concept_normalize_slot(data.get('slotId') or 'cover')
    if not slot_id:
        return jsonify({'success': False, 'error': 'نوع الصورة غير معروف', 'error_code': 'SLOT_INVALID'}), 400
    workflow_error = _visual_concept_plan_workflow_error(
        data, slot_id, require_boundary=True, require_distribution=True)
    if workflow_error:
        return jsonify(workflow_error), 400
    _project_data, facts, missing = _visual_concept_request_bundle(data, slot_id)
    if missing:
        return jsonify({
            'success': False,
            'error': 'أكمل الحقول الناقصة قبل إنشاء وصف التصور البصري',
            'error_code': 'VISUAL_CONCEPT_DATA_INCOMPLETE',
            'missingFields': missing,
        }), 400
    external_gate = _visual_concept_external_gate(data, slot_id)
    if external_gate:
        return jsonify(external_gate), 400
    cover_image = _visual_concept_cover_image(data)
    if slot_id != 'cover' and not _visual_concept_is_plan_slot(slot_id) and not cover_image:
        return jsonify({
            'success': False,
            'error': 'اعتمد الصورة الرئيسية قبل إنشاء وصف التصور البصري',
            'error_code': 'COVER_REQUIRED',
        }), 400
    references = _visual_concept_collect_generation_references(facts, slot_id, cover_image)
    current_prompt = _visual_concept_sanitize_prompt(data.get('currentPrompt') or data.get('prompt'))
    instruction = _visual_concept_text(data.get('instruction') or data.get('message'), 4000)
    if _visual_concept_is_plan_slot(slot_id):
        plan_draft = _visual_concept_sanitize_prompt(facts.get('plan_prompt_draft'))
        if plan_draft and not instruction:
            return jsonify({
                'success': True,
                'slotId': slot_id,
                'prompt': plan_draft,
                'reply': '',
                'referenceCount': len(references),
                'model': 'deterministic',
            })
        if plan_draft and not current_prompt:
            current_prompt = plan_draft
    _billing_guard = _require_billing_balance('visual_concept')
    if _billing_guard is not None:
        return _billing_guard
    try:
        prompt, reply = _visual_concept_generate_prompt_text(
            facts, slot_id, current_prompt=current_prompt, instruction=instruction, image_references=references,
            usage_ctx=_usage_ctx('image', data),
        )
        if not prompt:
            return jsonify({'success': False, 'error': 'تعذر إنشاء وصف التصور البصري', 'error_code': 'TEXT_PROVIDER_INVALID'}), 503
        return jsonify({
            'success': True,
            'slotId': slot_id,
            'prompt': prompt,
            'reply': reply,
            'referenceCount': len(references),
            'model': SLIDE_TEXT_MODEL,
        })
    except Exception as exc:
        app.logger.exception('Visual concept prompt failed')
        return jsonify({'success': False, 'error': 'تعذر إنشاء وصف التصور البصري',
                        'detail': str(exc)[:400], 'error_code': 'TEXT_PROVIDER_FAILED'}), 503


@app.route('/api/visual-concept/generate', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_generate():
    data = request.get_json(silent=True) or {}
    _billing_guard = _require_billing_balance('image_generation')
    if _billing_guard is not None:
        return _billing_guard
    slot_id = _visual_concept_normalize_slot(data.get('slotId') or 'cover')
    if not slot_id:
        return jsonify({'success': False, 'error': 'نوع الصورة غير معروف', 'error_code': 'SLOT_INVALID'}), 400
    workflow_error = _visual_concept_plan_workflow_error(
        data, slot_id, require_boundary=True, require_distribution=True)
    if workflow_error:
        return jsonify(workflow_error), 400
    _project_data, facts, missing = _visual_concept_request_bundle(data, slot_id)
    if missing:
        return jsonify({
            'success': False,
            'error': 'أكمل الحقول الناقصة قبل توليد التصور البصري',
            'error_code': 'VISUAL_CONCEPT_DATA_INCOMPLETE',
            'missingFields': missing,
        }), 400
    prompt = _visual_concept_sanitize_prompt(data.get('prompt'))
    if not prompt:
        return jsonify({'success': False, 'error': 'وصف التصور البصري مطلوب', 'error_code': 'PROMPT_REQUIRED'}), 400
    external_gate = _visual_concept_external_gate(data, slot_id)
    if external_gate:
        return jsonify(external_gate), 400
    cover_image = _visual_concept_cover_image(data)
    if slot_id != 'cover' and not _visual_concept_is_plan_slot(slot_id) and not cover_image:
        return jsonify({
            'success': False,
            'error': 'اعتمد الصورة الرئيسية قبل توليد التصور البصري',
            'error_code': 'COVER_REQUIRED',
        }), 400
    references = _visual_concept_collect_generation_references(facts, slot_id, cover_image)
    image = call_images_api(prompt, references, model=VISUAL_CONCEPT_IMAGE_MODEL,
                            usage_ctx=_usage_ctx('image', data))
    if not image:
        if not _has_any_openrouter_key(tenant_id=getattr(g, 'tenant_id', None)):
            return jsonify({'success': False, 'error': 'مفتاح OpenRouter غير مُعدّ', 'error_code': 'NO_API_KEY'}), 400
        return jsonify({'success': False, 'error': 'تعذر توليد صورة التصور البصري', 'error_code': 'IMAGE_FAILED'}), 503
    return jsonify({
        'success': True,
        'slotId': slot_id,
        'image': persist_generated_image(image, g.tenant_id),
        'prompt': prompt,
        'referenceCount': len(references),
        'model': VISUAL_CONCEPT_IMAGE_MODEL,
    })


@app.route('/api/visual-concept/chat', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_chat():
    data = request.get_json(silent=True) or {}
    _billing_guard = _require_billing_balance('designer_chat')
    if _billing_guard is not None:
        return _billing_guard
    slot_id = _visual_concept_normalize_slot(data.get('slotId') or 'cover')
    if not slot_id:
        return jsonify({'success': False, 'error': 'نوع الصورة غير معروف', 'error_code': 'SLOT_INVALID'}), 400
    workflow_error = _visual_concept_plan_workflow_error(
        data, slot_id, require_boundary=True, require_distribution=True)
    if workflow_error:
        return jsonify(workflow_error), 400
    instruction = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if not instruction:
        return jsonify({'success': False, 'error': 'اكتب طلب التعديل أولاً', 'error_code': 'MESSAGE_REQUIRED'}), 400
    _project_data, facts, missing = _visual_concept_request_bundle(data, slot_id)
    if missing:
        return jsonify({
            'success': False,
            'error': 'أكمل الحقول الناقصة قبل تعديل التصور البصري',
            'error_code': 'VISUAL_CONCEPT_DATA_INCOMPLETE',
            'missingFields': missing,
        }), 400
    current_prompt = _visual_concept_sanitize_prompt(data.get('currentPrompt') or data.get('prompt'))
    external_gate = _visual_concept_external_gate(data, slot_id)
    if external_gate:
        return jsonify(external_gate), 400
    cover_image = _visual_concept_cover_image(data)
    if slot_id != 'cover' and not _visual_concept_is_plan_slot(slot_id) and not cover_image:
        return jsonify({
            'success': False,
            'error': 'اعتمد الصورة الرئيسية قبل تعديل التصور البصري',
            'error_code': 'COVER_REQUIRED',
        }), 400
    references = _visual_concept_collect_generation_references(facts, slot_id, cover_image)
    try:
        prompt, reply = _visual_concept_generate_prompt_text(
            facts, slot_id, current_prompt=current_prompt, instruction=instruction, image_references=references,
            usage_ctx=_usage_ctx('image', data),
        )
        if not prompt:
            return jsonify({'success': False, 'error': 'تعذر تعديل وصف التصور البصري', 'error_code': 'TEXT_PROVIDER_INVALID'}), 503
        return jsonify({
            'success': True,
            'slotId': slot_id,
            'prompt': prompt,
            'reply': reply or 'تم تحديث وصف الصورة حسب طلبك.',
            'referenceCount': len(references),
        })
    except Exception as exc:
        app.logger.exception('Visual concept chat failed')
        return jsonify({'success': False, 'error': 'تعذر تعديل وصف التصور البصري',
                        'detail': str(exc)[:400], 'error_code': 'TEXT_PROVIDER_FAILED'}), 503


@app.route('/api/designer-generate', methods=['POST'])
@require_auth
def api_designer_generate():
    """Generate slides HTML: variable slide count in parallel (4 concurrent workers)."""
    _billing_guard = _require_billing_balance('slide_plan')
    if _billing_guard is not None:
        return _billing_guard
    project_data = clean_project_data(request.json.get('projectData', {}))
    outline = request.json.get('outline', [])
    images = request.json.get('images', {})
    images_info = _get_images_info(images, project_data)

    # Build system prompt ONCE — shared across all slides
    branding = db.get_branding(g.tenant_id) or {}
    dynamic_rules = build_design_rules(branding)
    system_prompt = build_system_prompt(project_data, images_info, dynamic_rules)
    min_s, max_s, default_count = resolve_slide_bounds(branding)
    if outline:
        slide_count = max(min_s, min(max_s, len(outline)))
    else:
        slide_count = max(min_s, min(default_count, max_s))
    print(f"\n[DESIGNER] Starting {slide_count}-slide parallel generation (4 workers)...")
    print(f"[DESIGNER] System prompt: {len(system_prompt)} chars (shared)")
    start_time = time.time()

    try:
        # The attempt context is captured here in the request scope: worker
        # threads share no Flask context, so building it inside the worker
        # would lose the tenant and the project attribution.
        designer_slide_ctx = _usage_ctx('slide', request.json)
        # Run slides in parallel with 4 concurrent workers
        results = [None] * slide_count
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_idx = {}
            for i in range(slide_count):
                slide_title = outline[i].get('title') if i < len(outline) else None
                future = executor.submit(generate_single_slide, system_prompt, i + 1, g.tenant_id, total=slide_count, title=slide_title, usage_ctx=designer_slide_ctx, offer_lang=slide_engine.resolve_offer_lang(project_data))
                future_to_idx[future] = i

            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    print(f"[DESIGNER] Slide {idx + 1} worker failed: {exc}")
                    results[idx] = ''

        missing = [idx + 1 for idx, html in enumerate(results) if not html]
        if missing:
            print(f"[DESIGNER] Retrying missing slides after parallel run: {missing}")
            for slide_num in missing:
                slide_title = outline[slide_num - 1].get('title') if slide_num - 1 < len(outline) else None
                results[slide_num - 1] = generate_single_slide(
                    system_prompt, slide_num, g.tenant_id, max_retries=1, total=slide_count, title=slide_title,
                    usage_ctx=designer_slide_ctx,
                )

        elapsed = round(time.time() - start_time, 1)
        combined_html = '\n'.join(h for h in results if h).strip()
        combined_html = validate_html(combined_html, slide_count)
        total_slides = combined_html.count('class="slide"')
        print(f"[DESIGNER] Done in {elapsed}s — {total_slides} slides total")

        # Build dynamic fallback titles from the fallback plan, padded to slide_count
        fallback_slides = build_fallback_plan(branding, project_data).get('slides', [])
        _designer_deck_en = slide_engine.resolve_offer_lang(project_data) == slide_engine.OFFER_LANG_ENGLISH
        DEFAULT_TITLES = [s.get('title', (f'Slide {i + 1}' if _designer_deck_en else f'شريحة {i + 1}')) for i, s in enumerate(fallback_slides)]
        if len(DEFAULT_TITLES) < slide_count:
            for i in range(len(DEFAULT_TITLES), slide_count):
                DEFAULT_TITLES.append(f'Slide {i + 1}' if _designer_deck_en else f'شريحة {i + 1}')

        def extract_slide_title(s_html, def_title):
            for pattern in [r'<h[1-6][^>]*>([\s\S]*?)</h[1-6]>',
                            r'class="[^"]*(?:slide-title|title)[^"]*"[^>]*>([\s\S]*?)</']:
                m = re.search(pattern, s_html)
                if m:
                    t = re.sub(r'<[^>]*>', '', m.group(1)).strip()
                    if t and len(t) < 80:
                        return t
            return def_title

        slide_starts = [m.start() for m in re.finditer(r'<div[^>]*class=["\']slide["\']', combined_html)]
        slides_list = []
        for idx, start_pos in enumerate(slide_starts):
            end_pos = slide_starts[idx + 1] if idx + 1 < len(slide_starts) else len(combined_html)
            slide_html = combined_html[start_pos:end_pos].strip()
            if not slide_html:
                continue
            if idx < len(outline) and outline[idx].get('title'):
                def_title = outline[idx]['title']
            elif idx < len(DEFAULT_TITLES):
                def_title = DEFAULT_TITLES[idx]
            else:
                def_title = f'شريحة {idx + 1}'
            title = extract_slide_title(slide_html, def_title)
            slides_list.append({'title': title, 'html': slide_html})

        if not slides_list and combined_html:
            slides_list.append({'title': 'شريحة 1', 'html': combined_html})

        print(f"[DESIGNER] Returning {len(slides_list)} slides to frontend")
        return jsonify({'success': True, 'slides': slides_list})

    except Exception as e:
        print(f"[DESIGNER ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/generate-outline', methods=['POST'])
@require_auth
def api_generate_outline():
    """Compatibility: Generate outline"""
    return api_official_outline()


@app.route('/api/generate-content', methods=['POST'])
@require_auth
def api_generate_content():
    """Compatibility: Generate content for a slide"""
    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard
    slide_data = request.json.get('slide', {})
    project_data = clean_project_data(request.json.get('projectData', {}))

    prompt = f"اكتب محتوى للشريحة: {slide_data.get('title', '')}\n\nبيانات المشروع:\n{json.dumps(project_data, ensure_ascii=False, indent=2)}"

    try:
        response = call_zai_chat(prompt, "اكتب المحتوى.", max_tokens=2000, usage_ctx=_usage_ctx_optional('slide', request.json))
        content = extract_chat_content(response, "CONTENT")
        return jsonify({'success': True, 'content': content})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai-edit-slide', methods=['POST'])
@require_auth
def api_ai_edit_slide():
    """Compatibility: AI edit a slide with Playwright Vision guidance"""
    data = request.json
    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard
    instruction = data.get('instruction', '') or data.get('editRequest', '') or data.get('message', '')
    slide_html = data.get('slideHtml', '') or data.get('slideContent', '') or data.get('currentSlideHtml', '')
    project_data = clean_project_data(data.get('projectData', {}))
    presentation_id = data.get('presentationId')

    from auth import get_optional_tenant_id
    tenant_id = get_optional_tenant_id() or 'default'
    branding = db.get_branding(tenant_id) or {}
    requested_slide_type = data.get('slideType') or data.get('slide_type') or 'content'
    surface_note = '' if requested_slide_type in ('cover', 'closing', 'section_divider', 'moodboard') else (
        "\nهذه شريحة محتوى عادية: استخدم canvas أبيض أو فاتحاً موحداً، ولا تنشئ إطاراً داكناً حول صفحة بيضاء. "
        "الخلفية الداكنة الكاملة محجوزة للغلاف والخاتمة وفواصل الأقسام ذات الصورة. "
        "خلفية كل شعار مستقلة حسب لونه وتباينه، فلا تغيّر حاوية الشعار عند تغيير خلفية الشريحة."
    )

    vision_image_uri = None
    try:
        from generate_pdf_from_preview import render_slide_to_image_base64
        vision_image_uri = render_slide_to_image_base64(slide_html, branding=branding, tenant_id=tenant_id)
    except Exception as ve:
        print(f"[AI-EDIT VISION] Screenshot failed: {ve}")

    image_refs = [{"data_uri": vision_image_uri}] if vision_image_uri else None
    vision_note = (
        "\nتم تزويدك بلقطة شاشة مرئية فعلية للشريحة الحالية كما تظهر للمستخدم (1280x720). انظر للتنسيق ونفذ التعديل المطلوب بتناسق بصري."
        if vision_image_uri else ""
    )

    prompt = f"""عدّل الشريحة التالية حسب التعليمات:{vision_note}{surface_note}
التعليمات: {instruction}

الشريحة الحالية:
{slide_html}

بيانات المشروع:
{json.dumps(project_data, ensure_ascii=False, indent=2)}

أعد الشريحة بالـ HTML المعدّل."""

    try:
        response = call_zai_chat(prompt, "عدّل الشريحة.", max_tokens=4000, model=SLIDE_TEXT_MODEL, image_references=image_refs, usage_ctx=_usage_ctx_optional('slide', data, presentation_id=presentation_id))
        html = extract_chat_content(response, "EDIT")
        html = extract_html_from_glm({'choices': [{'message': {'content': html}}]})
        
        # Post-process and resolve placeholders
        # Preserve the actual slide semantics. In particular, a closing slide
        # must not be treated as content and receive a header/footer.
        slide_number = data.get('slideNumber') or data.get('slide_number')
        if slide_number is None:
            raw_index = data.get('slideIndex')
            slide_number = (int(raw_index) + 1) if raw_index is not None else 2
        html = postprocess_slide(
            html,
            int(slide_number),
            tenant_id,
            slide_title=data.get('slideTitle') or data.get('currentSlideTitle') or '',
            total_slides=data.get('totalSlides') or data.get('total_slides'),
            slide_type=requested_slide_type,
        )
        html = resolve_designer_chat_placeholders(html, project_data, presentation_id, tenant_id,
                                                 data.get('creativeImages'))
        
        return jsonify({'success': True, 'data': {'action': 'edit', 'html': html, 'response': 'تم تعديل الشريحة '}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai-chat', methods=['POST'])
@require_auth
def api_ai_chat():
    """Compatibility: AI chat — returns data.data format expected by frontend"""
    data = request.json
    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard
    message = data.get('message', '')
    project_data = clean_project_data(data.get('projectData', {}))
    current_slide_idx = data.get('currentSlideIdx', 0)

    prompt = f"""أنت مساعد ذكي متخصص في العروض العقارية.

بيانات المشروع:
{json.dumps(project_data, ensure_ascii=False, indent=2)}

مهمتك: تعدّل شريحة العرض بناءً على طلبات المستخدم.
أعد الرد بصيغة JSON فقط:
{{"action": "edit", "slideIdx": {current_slide_idx}, "changes": {{"content": "النص الجديد للشريحة", "title": "عنوان جديد (إذا طُلب)"}}}}
إذا كان الطلب استفساراً فقط بدون تعديل، أعد:
{{"action": "reply", "response": "نص الرد"}}"""

    try:
        response = call_zai_chat(prompt, message, max_tokens=2000, usage_ctx=_usage_ctx_optional('slide', data))
        reply = extract_chat_content(response, "CHAT")

        parsed = _extract_json_from_text(reply)
        if parsed:
            if parsed.get('action') == 'edit' and 'changes' in parsed:
                parsed.setdefault('slideIdx', current_slide_idx)
            return jsonify({'success': True, 'data': parsed})

        # Fallback: plain text reply wrapped in data format with response field
        return jsonify({'success': True, 'data': {'action': 'reply', 'response': reply}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/save-training', methods=['POST'])
def api_save_training_compat():
    """Compatibility: Save training data (no-op)"""
    return jsonify({'success': True})


@app.route('/api/get-training', methods=['GET'])
def api_get_training_compat():
    """Compatibility: Get training data (empty)"""
    return jsonify({'success': True, 'history': []})


@app.route('/api/edit-deck-data', methods=['POST'])
def api_edit_deck_data():
    """Compatibility: Edit deck data (pass-through)"""
    return jsonify({'success': True})


@app.route('/api/generate-bullets', methods=['POST'])
@require_auth
def api_generate_bullets():
    """Compatibility: Generate bullets for a slide"""
    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard
    title = request.json.get('title', '')
    project_data = clean_project_data(request.json.get('projectData', {}))

    prompt = f"اكتب 3-5 نقاط مختصرة للشريحة: {title}\n\nبيانات المشروع:\n{json.dumps(project_data, ensure_ascii=False, indent=2)}"

    try:
        response = call_zai_chat(prompt, "اكتب النقاط.", max_tokens=1000, usage_ctx=_usage_ctx_optional('slide', request.json))
        content = extract_chat_content(response, "BULLETS")
        # Bullet glyphs are stripped from the model's output; written as escapes so the source
        # itself stays free of icon characters.
        bullet_chars = '\u2022-\u25cf* '
        bullets = [line.strip().lstrip(bullet_chars) for line in content.split('\n') if line.strip() and len(line.strip()) > 3]
        return jsonify({'success': True, 'bullets': bullets[:5]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/organize-text', methods=['POST'])
def api_organize_text():
    """Compatibility: Organize text"""
    text = request.json.get('text', '')
    return jsonify({'success': True, 'organized': text})


@app.route('/api/generate-design', methods=['POST'])
@require_auth
def api_generate_design():
    """Compatibility: Generate design (use designer-generate)"""
    return api_designer_generate()


@app.route('/api/generate-design-batch', methods=['POST'])
@require_auth
def api_generate_design_batch():
    """Compatibility: Generate design batch"""
    return api_designer_generate()


@app.route('/api/redesign-slide', methods=['POST'])
@require_auth
def api_redesign_slide():
    """Compatibility: Redesign a slide"""
    return api_ai_edit_slide()


@app.route('/api/pdf-design', methods=['POST'])
@require_auth
def api_pdf_design():
    """Compatibility: PDF design (use export-pdf)"""
    return api_export_pdf()


@app.route('/api/pdf-design-stream', methods=['POST'])
@require_auth
def api_pdf_design_stream():
    """Compatibility: PDF design stream"""
    return api_export_pdf()


@app.route('/api/generate-pdf', methods=['POST'])
@require_auth
def api_generate_pdf():
    """Compatibility: Generate PDF"""
    return api_export_pdf()


@app.route('/api/pdf-chat', methods=['POST'])
def api_pdf_chat():
    """Compatibility: PDF chat (no-op)"""
    return jsonify({'success': True, 'reply': 'تم'})

@app.route('/api/pdf-chat/upload', methods=['POST'])
def api_pdf_chat_upload():
    """Compatibility: PDF chat upload (no-op)"""
    return jsonify({'success': True})


@app.route('/api/render-slide-image', methods=['POST'])
@require_auth
def api_render_slide_image():
    """Render slide as image (returns base64 data URI via Playwright)"""
    data = request.json or {}
    slide_html = data.get('html', '')
    from auth import get_optional_tenant_id
    tenant_id = get_optional_tenant_id() or 'default'
    branding = db.get_branding(tenant_id) or {}
    try:
        from generate_pdf_from_preview import render_slide_to_image_base64
        uri = render_slide_to_image_base64(slide_html, branding=branding, tenant_id=tenant_id)
        if uri:
            return jsonify({'success': True, 'imageDataUri': uri, 'html': slide_html})
    except Exception as e:
        print(f"[RENDER-SLIDE-IMAGE ERROR] {e}")
    return jsonify({'success': True, 'html': slide_html})


# Last observed state of the slide renderer on this host, so /health can report whether the
# designer is editing with vision or blind instead of leaving it in a log file.
_SLIDE_VISION_STATE = {}
