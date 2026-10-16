

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
        'وإن اختار العميل قيمة معتمدة تطابق شريحة مشروطة موثقة (كمعامل بناء متميز)، فالاختيار نفسه تصريح بالأهلية: '
        'سجّل «يحتاج تأكيد» بإجراء «التأكد من استيفاء شروط الشريحة في المستندات» بدل «متعارض»، '
        'ولا تطلب كتابة جملة إثبات في ملاحظات التوزيع. '
        'لا تذكر أسماء أو أرقام مصادر داخل النتيجة.'
    )
    result = {}
    try:
        response = call_openrouter_chat(
            system_prompt, user_prompt, temperature=None, max_tokens=8000,
            model=VISUAL_PLAN_TEXT_MODEL, reasoning_effort='medium',
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
                model=VISUAL_PLAN_TEXT_MODEL, reasoning_effort='medium',
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
    """Shared context assembly for plans endpoints: recorded land geometry is
    authoritative, with legacy workflow points retained only as a fallback."""
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    boundary = workflow.get('boundary') if isinstance(workflow.get('boundary'), dict) else {}
    points = _visual_concept_plan_recorded_points(project_data, boundary.get('points'))
    context = workflow.get('planContext') if isinstance(workflow.get('planContext'), dict) else None
    context = context or _visual_concept_plan_context(project_data, points, workflow.get('verification'))
    context['boundary_points'] = points or context.get('boundary_points') or []
    context['buildable_area'] = _visual_concept_plan_buildable_area(context, project_data, points)
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
    distribution_notes = _visual_concept_text(workflow.get('distributionNotes'), 1000000)
    # A revision applies the client's instruction to the posted table instead of
    # redistributing from scratch — the rest of the rows must come back intact.
    revision = _visual_concept_text(data.get('revision'), 4000)
    posted_distribution = (data.get('distribution') if isinstance(data.get('distribution'), dict)
                           else workflow.get('distribution') if isinstance(workflow.get('distribution'), dict)
                           else {})
    current_rows = posted_distribution.get('rows') if isinstance(posted_distribution.get('rows'), list) else []
    revise = bool(revision and current_rows)
    user_prompt = (
        'بيانات المشروع المعتمدة الوحيدة المسموح الاعتماد عليها:\n'
        + _visual_concept_plan_context_text(context, diagram_rules=False)
        + ('\nملاحظات العميل على التوزيع — رغبات تُطبَّق ضمن حدود الاشتراطات والبيانات '
           'المعتمدة ولا تجاوزها:\n' + distribution_notes if distribution_notes else '')
    )
    if revise:
        user_prompt += (
            '\nالجدول الحالي المطلوب تعديله:\n' + json.dumps({'rows': current_rows}, ensure_ascii=False)
            + '\nتعليمة العميل على هذا الجدول — طبّقها بدقة وأبقِ باقي الصفوف دون تغيير ما لم '
            'تقتضِ التعليمة نفسها أو الاشتراطات تعديلها، وأعد الجدول كاملًا بعد التطبيق:\n' + revision
        )
    else:
        user_prompt += ('\nأعد جدول التوزيع المقترح: كل صف = مبنى + دور أو نطاق أدوار + مكوّن + عدد الوحدات لكل دور '
                        '+ مساحة الدور الإجمالية + الحركة والخدمات ضمن المساحة.')
    result = {}
    try:
        response = call_openrouter_chat(
            system_prompt, user_prompt, temperature=None, max_tokens=8000,
            model=VISUAL_PLAN_TEXT_MODEL, reasoning_effort='medium',
            response_format={'type': 'json_object'}, usage_ctx=_usage_ctx('image', data))
        result = parse_json_object(_get_chat_response_text(response))
    except Exception:
        result = {}
    if not isinstance(result, dict) or not result.get('rows'):
        if revise:
            # A failed revision must not swap in a fresh distribution — the
            # client's table stays untouched and the error surfaces instead.
            return jsonify({'success': False,
                            'error': 'تعذر تطبيق التعديل على التوزيع — الجدول لم يتغير',
                            'error_code': 'DISTRIBUTION_REVISION_FAILED'}), 503
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
    distribution_notes = _visual_concept_text(workflow.get('distributionNotes'), 1000000)
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
            'دورك التدقيق والتشخيص فقط — لا يوجد إصلاح آلي؛ العميل يعدّل يدويًا. '
            'ولكل بند متعارض قرّر fixable: true إن كان يُحل بتحرير صفوف الجدول يدويًا، أو false إن '
            'كان مصدره بيانات المشروع المعتمدة نفسها مقابل الاشتراطات (برنامج يتجاوز معامل '
            'البناء مهما توزّع، استخدام غير مسموح به إطلاقًا) — حينها اشرح في detail أين '
            'يصحّح المصدر (الدراسة أو الحقل المعتمد) بدل وصف التحرير المستحيل. '
            'لا تكتب بنود «لم يوثّق» عمّا لا يمكن لجدول توزيع إثباته بطبيعته (أبعاد المواقف، '
            'عروض الممرات والمنحدرات، جهات المداخل، مسافات الإخلاء، تفاصيل الحريق) — فهي مرحلة '
            'تصميم لاحقة. '
            'القيم الموثقة في البيانات التنظيمية (معامل البناء، نسب التغطية، عدد الأدوار) حقائق '
            'نهائية — لا تخترع لها شروط أهلية أو اعتمادات غير مكتوبة ولا تعامل الرقم الموثق كأنه '
            'يحتاج إثباتًا خارجيًا؛ إن نصّت الوثيقة نفسها على شرط صريح مرفق بالقيمة فارفعه '
            '«يحتاج تأكيد» بنصّ الشرط لا بصياغة اعتراض. وإن طابقت القيمة المعتمدة التي اختارها '
            'العميل شريحةً مشروطة موثقة (كالمعامل المتميز)، فالاختيار نفسه تصريح بالأهلية — '
            'الحكم «يحتاج تأكيد» بإجراء «راجع استيفاء شروط الشريحة في المستندات»، لا «متعارض» '
            'ولا مطالبة بكتابة جملة إثبات في ملاحظات التوزيع. و«أضف مكوّنًا» تعني مكوّنًا موجودًا في '
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
            + ('\n\nملاحظات العميل على التوزيع — سياق مقصود: اختيارًا طلبه العميل لا '
               'يُعامل خطأً ما لم يخالف نصًا موثقًا:\n' + distribution_notes
               if distribution_notes else '')
        )
        try:
            response = call_openrouter_chat(
                system_prompt, user_prompt, temperature=None, max_tokens=5000,
                model=VISUAL_PLAN_TEXT_MODEL, reasoning_effort='medium',
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


@app.route('/api/visual-concept/plans-prompts', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plans_prompts():
    data = request.get_json(silent=True) or {}
    workflow_error = _visual_concept_plan_workflow_error(
        data, 'plan_site', require_distribution=True)
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
    _billing_guard = _require_billing_balance('visual_concept')
    if _billing_guard is not None:
        return _billing_guard
    slot_id = _visual_concept_normalize_slot(data.get('slotId') or 'cover')
    if not slot_id:
        return jsonify({'success': False, 'error': 'نوع الصورة غير معروف', 'error_code': 'SLOT_INVALID'}), 400
    workflow_error = _visual_concept_plan_workflow_error(
        data, slot_id, require_distribution=True)
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
            'model': GEMINI_TEXT_MODEL,
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
        data, slot_id, require_distribution=True)
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
        data, slot_id, require_distribution=True)
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
