

@app.route('/api/visual-concept/plans-verify', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plans_verify():
    data = request.get_json(silent=True) or {}
    _billing_guard = _require_billing_balance('visual_concept')
    if _billing_guard is not None:
        return _billing_guard
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    context = _visual_concept_plan_context(project_data)
    if ((context.get('primary_frontage') or {}).get('status') == 'unresolved'
            and (context.get('land_brief') or context.get('croquis_regulatory_constraints'))):
        summary, constraints, site_rows, _holders, _main = _visual_plan_site_parts(project_data)
        resolved = _visual_plan_resolve_primary_frontage(summary, constraints, site_rows, data)
        if resolved:
            context['primary_frontage'] = resolved
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
    points = _visual_concept_plan_boundary_points(
        data.get('points') or project_data.get('survey_coordinates')
        or project_data.get('regulation_coordinates')
        or plot_shape.dimension_survey_rows(project_data))
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
            fatal = _ai_fatal_error_dict(response)
            if fatal is not None:
                fatal_response = _ai_fatal_http_response(response)
                if fatal_response is not None:
                    return fatal_response
                return jsonify({'success': False, 'error': _client_safe_llm_error(fatal.get('message'))}), 503
            if isinstance(response, dict) and response.get('error'):
                return jsonify({'success': False, 'error': _client_safe_llm_error(_chat_error_message(response))}), 503
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
    _financial_parking_refresh_context(context, project_data)
    _visual_concept_plan_context_ensure_idea(context, project_data)
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
        '"1-4" لنطاق أدوار رقمي، "ملحق علوي" للسطح، و"مساحة مفتوحة" لعناصر الموقع المكشوفة. '
        'كل مكوّن نوعه «مساحة مفتوحة» في بيانات المشروع (لاندسكيب، ممرات مشاة، مواقف سطحية، '
        'مرافق مكشوفة) يُسجَّل بصيغة "مساحة مفتوحة" لا "أرضي" ولا نطاق أدوار — هو عنصر موقع '
        'لا دور مبنى، وعمود building له «الموقع العام». '
        'component هو اسم المكوّن كما ورد في بيانات المشروع حرفيًا — بالعربية دون ترجمة '
        'أو إعادة صياغة ودون اسم الدور — الدور موجود في floor_range. '
        'عمود building هو المبنى أو المجمع الذي يقع فيه الصف: إذا نصّت فكرة المشروع '
        'أو بياناته على عدد من المباني أو المجمعات فوزّع الصفوف على نفس العدد وسمّ كل '
        'مبنى كما ورد في الفكرة (مجمع 1، مجمع 2…) ولا تدمج المشروع كله في كتلة واحدة، '
        'وإذا سجّلت بيانات المشروع اسم مبنى على مكوّن فالتزم به. '
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
    result['rows'] = _financial_parking_merge_distribution_rows(result.get('rows') or [], context)
    distribution = _visual_concept_plan_normalize_distribution(
        result, context, regulations, backfill=True)
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
    checks = distribution['checks']
    issues = distribution['issues']
    can_proceed = not any(check.get('result') == 'متعارض' for check in checks)
    if str(data.get('mode') or '').lower() == 'ai':
        _billing_guard = _require_billing_balance('visual_concept')
        if _billing_guard is not None:
            return _billing_guard
        # sol is the judge here, not the deterministic pass: he reviews every
        # numbered finding and may confirm it, soften it, or dismiss it as a
        # false alarm — a hard «متعارض» now requires his verdict.
        system_prompt = (
            'أنت مدقق اشتراطات لمخطط مفاهيمي تحكم على جدول توزيع مكونات على الأدوار مقابل '
            'البيانات التنظيمية الموثقة فقط. الجدول يعبّر عن: المبنى، الدور أو نطاق الأدوار، '
            'الاستخدام، عدد الوحدات لكل دور، مساحة الدور، والحركة والخدمات — فدقّق فيما يمكن '
            'للجدول إثباته فعلًا: الاستخدامات المسموحة، سقف الارتفاع وعدد الأدوار، حد التغطية، '
            'عدم تداخل نطاقات المكوّن الواحد في مبنى واحد، وعدم تجاوز مساحات أو وحدات الدراسة. '
            'ستصلك بنود فحص آلي مرقّمة — لكل بند احكم: «متعارض» مخالفة حقيقية تمنع الاعتماد، '
            '«يحتاج تأكيد» تستدعي مراجعة العميل دون منع، أو «مطابق» إنذار كاذب لأن التوزيع '
            'سليم فعلًا (نطاقات متجاورة لا متداخلة، مبانٍ مختلفة، أو استخدامات مختلفة تشترك '
            'في الدور بشكل مشروع). راجع كل البنود المرقّمة ولا تترك بندًا بلا حكم. '
            'ولكل بند متعارض قرّر fixable: true إن كان يُحل بتحرير صفوف الجدول، أو false إن '
            'كان مصدره بيانات المشروع المعتمدة نفسها مقابل الاشتراطات (برنامج يتجاوز معامل '
            'البناء مهما توزّع، استخدام غير مسموح به إطلاقًا) — حينها اشرح في detail أين '
            'يصحّح المصدر بدل وصف التحرير المستحيل. '
            'لا تكتب بنود «لم يوثّق» عمّا لا يمكن لجدول توزيع إثباته بطبيعته (أبعاد المواقف، '
            'عروض الممرات والمنحدرات، جهات المداخل، مسافات الإخلاء، تفاصيل الحريق) — فهي مرحلة '
            'تصميم لاحقة. '
            'القيم الموثقة في البيانات التنظيمية (معامل البناء، نسب التغطية، عدد الأدوار) حقائق '
            'نهائية — لا تخترع لها شروط أهلية أو اعتمادات غير مكتوبة ولا تعامل الرقم الموثق كأنه '
            'يحتاج إثباتًا خارجيًا؛ إن نصّت الوثيقة نفسها على شرط صريح مرفق بالقيمة فارفعه '
            '«يحتاج تأكيد» بنصّ الشرط لا بصياغة اعتراض. و«أضف مكوّنًا» تعني مكوّنًا موجودًا في '
            'بيانات المشروع المعتمدة ولا صف له في الجدول — لا مكوّنًا تستنتجه الاشتراطات (محطة '
            'تحويل، غرفة خدمات، منحدر)؛ برنامج الدراسة هو مرجع المكونات الوحيد وكل صف يجب أن '
            'يقابل مكوّنًا مدروسًا. ولا تعلّق على وصف الحركة بما لا يثبته الجدول (جهة مدخل، '
            'عرض ممر، موضع منحدر) إلا إذا ناقض نصًا موثقًا صراحة. '
            'issues تبقى ملاحظات إجرائية واضحة قابلة للتنفيذ على الجدول: «عدّل قيمة X في صف Y إلى Z» '
            'أو «أضف مكوّنًا لـ…»، وبحد أقصى 8 بنود مرتبة بالأهمية. '
            'سمّ الصفوف باسم المكوّن والدور («صف سكني في الدور أرضي»)، ولا تذكر معرّفات داخلية. أعد JSON فقط: '
            '{"reviews":[{"index":0,"result":"متعارض|يحتاج تأكيد|مطابق","detail":"","fixable":true}],'
            '"issues":[{"title":"","points":[""],"suggestion":"","action":"","severity":"high|medium|low"}],'
            '"canProceed":true}. لا تذكر أسماء ملفات أو أرقام صفحات أو مصادر داخلية.'
        )
        indexed_checks = [
            {'index': index, 'item': check.get('item'), 'detail': check.get('detail'),
             'result': check.get('result')}
            for index, check in enumerate(checks)
        ]
        user_prompt = (
            'البيانات التنظيمية الموثقة:\n' + json.dumps(regulations, ensure_ascii=False)
            + '\n\nبيانات المشروع المعتمدة:\n'
            + _visual_concept_plan_context_text(context, diagram_rules=False)
            + '\n\nالتوزيع المدخل للمراجعة:\n'
            + json.dumps({'rows': distribution['rows'], 'totals': distribution['totals']},
                         ensure_ascii=False)
            + '\n\nبنود الفحص الآلي المطلوب الحكم عليها كلها:\n'
            + json.dumps(indexed_checks, ensure_ascii=False)
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
            reviews = parsed.get('reviews')
            if isinstance(reviews, list):
                checks = _visual_concept_plan_adjudicate_checks(checks, reviews)
                can_proceed = not any(check.get('result') == 'متعارض' for check in checks)
            issues = _visual_concept_plan_normalize_issues(parsed.get('issues') or [])
            if parsed.get('canProceed') is False:
                can_proceed = False
    return jsonify({'success': True, 'totals': distribution['totals'],
                    'checks': checks, 'issues': issues,
                    'canProceed': can_proceed})


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
    # normalize recomputes checks deterministically and drops the verdicts the
    # client holds — but the repair must fix what sol CONFIRMED, so the posted
    # (adjudicated) findings win when they exist. fixable=false findings are
    # program-vs-regulation conflicts no row edit can resolve — they stay on
    # screen as sol's verdict and are never fed back to the repair loop.
    posted_checks = [check for check in posted.get('checks') or [] if isinstance(check, dict)]
    findings = posted_checks or distribution['checks']
    repairable = [check for check in findings
                  if check.get('fixable', True) and check.get('result') != 'مطابق']
    if not (distribution['rows'] and (repairable or distribution['issues'])):
        return jsonify({'success': True, 'distribution': distribution, 'repaired': False})
    _billing_guard = _require_billing_balance('visual_concept')
    if _billing_guard is not None:
        return _billing_guard
    editable_ids = {rid for check in repairable
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
        '"1-4" لنطاق أدوار رقمي، "ملحق علوي" للسطح، و"مساحة مفتوحة" لمكوّنات «مساحة مفتوحة» '
        'والمواقف السطحية — عناصر موقع تحت «الموقع العام» لا أدوار مبنى. '
        'component اسم المكوّن كما ورد في '
        'الدراسة حرفيًا — بالعربية ودون ترجمة أو إعادة صياغة أو اسم الدور. '
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
        + json.dumps(repairable, ensure_ascii=False)
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
    allowed_keys = set()
    for comp in context.get('components') or []:
        for variant in (comp.get('name'),
                        _visual_concept_plan_component_base(comp.get('name'))):
            key = _visual_concept_plan_component_key(variant)
            if key:
                allowed_keys.add(key)
    enforced = _visual_concept_plan_surgical_rows(
        distribution['rows'], candidate['rows'], editable_ids, allowed_keys)
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
    # The surveyed geometry and approved floor program remain deterministic;
    # sol proposes only editable scene elements, and the geometry validator
    # refuses any changed parcel, frontage, source area or floor program.
    return _visual_plan_dispatch('prepare', data)


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
    if _visual_concept_plan_kind(slot_id):
        return _visual_plan_dispatch('prompt', data, slot_id)
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
    section_gate = _visual_concept_section_gate(data, _visual_concept_section_requirement(slot_id))
    if section_gate:
        return jsonify(section_gate), 400
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
        fatal = _ai_fatal_http_response(exc)
        if fatal is not None:
            return fatal
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
    if _visual_concept_plan_kind(slot_id):
        return _visual_plan_dispatch('render', data, slot_id)
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
    section_gate = _visual_concept_section_gate(data, _visual_concept_section_requirement(slot_id))
    if section_gate:
        return jsonify(section_gate), 400
    references = _visual_concept_collect_generation_references(facts, slot_id, cover_image)
    # The suffix goes to the model only — the stored slot prompt stays clean
    # so a regenerate never bakes a duplicate line into it.
    image_prompt = _visual_concept_attach_style_reference_suffix(prompt, facts, slot_id)
    image = call_images_api(image_prompt, references, model=VISUAL_CONCEPT_IMAGE_MODEL,
                            usage_ctx=_usage_ctx('image', data))
    if not image:
        fatal = _ai_fatal_http_response(last_images_api_error())
        if fatal is not None:
            return fatal
        if not _has_any_openrouter_key(tenant_id=getattr(g, 'tenant_id', None)):
            return jsonify({'success': False, 'error': 'خدمة الذكاء الاصطناعي غير متاحة حاليًا — تواصل مع الدعم الفني.', 'error_code': 'NO_API_KEY'}), 400
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
    if _visual_concept_plan_kind(slot_id):
        return _visual_plan_dispatch('edit', data, slot_id)
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
    section_gate = _visual_concept_section_gate(data, _visual_concept_section_requirement(slot_id))
    if section_gate:
        return jsonify(section_gate), 400
    references = _visual_concept_collect_generation_references(facts, slot_id, cover_image)
    # Images the client pinned to this message ride along so the writer can
    # see exactly what "use this style" points at.
    references += _visual_concept_edit_reference_uris(data)
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
        fatal = _ai_fatal_http_response(exc)
        if fatal is not None:
            return fatal
        return jsonify({'success': False, 'error': 'تعذر تعديل وصف التصور البصري',
                        'detail': str(exc)[:400], 'error_code': 'TEXT_PROVIDER_FAILED'}), 503


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
        response = call_text_chat(prompt, "اكتب المحتوى.", max_tokens=2000, usage_ctx=_usage_ctx_optional('slide', request.json))
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
        response = call_text_chat(prompt, "عدّل الشريحة.", max_tokens=4000, model=SLIDE_TEXT_MODEL, image_references=image_refs, usage_ctx=_usage_ctx_optional('slide', data, presentation_id=presentation_id))
        html = extract_chat_content(response, "EDIT")
        html = extract_html_from_response({'choices': [{'message': {'content': html}}]})
        
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
        response = call_text_chat(prompt, message, max_tokens=2000, usage_ctx=_usage_ctx_optional('slide', data))
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
        response = call_text_chat(prompt, "اكتب النقاط.", max_tokens=1000, usage_ctx=_usage_ctx_optional('slide', request.json))
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
