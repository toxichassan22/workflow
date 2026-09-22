# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SLIDE PLAN & GENERATION ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from slide_engine import (
    build_slide_plan_prompt, parse_slide_plan, validate_slide_plan,
    generate_all_slides, extract_html_from_glm, CONTENT_DISTRIBUTION_RULES,
    resolve_slide_bounds, build_fallback_plan, _suggest_design_style,
    _timeline_data_note, _financial_data_note,
)


PROJECT_SECTION_PRESENTATION_TARGETS = {
    'basic': (('overview', 'components'), 'بيانات المشروع'),
    'location': (('location',), 'الموقع الجغرافي'),
    'land_croquis': (('land',), 'تحليل الأرض'),
    'section-timeline': (('timeline',), 'الجدول الزمني'),
    'section-financial-calc': (('financial',), 'الدراسة المالية والمؤشرات'),
    'section-team': (('team',), 'فريق العمل'),
    'section-market-study': (('market', 'swot_risks'), 'دراسة السوق'),
    'section-visual-concept': (('plans', 'exterior', 'interior'), 'التصور البصري'),
    'section-executive-content': (('executive_summary',), 'المحتوى التنفيذي'),
    'contact': (('closing',), 'بيانات التواصل'),
}


def _ensure_required_location_slides(plan, project_data):
    if not isinstance(plan, dict) or not isinstance(plan.get('slides'), list):
        return plan
    slides = plan['slides']
    existing_types = {slide.get('type') for slide in slides if isinstance(slide, dict)}
    offer_lang = slide_engine.resolve_offer_lang(project_data)
    deck_en = offer_lang == slide_engine.OFFER_LANG_ENGLISH
    required = []
    if project_data.get('location_lat') and project_data.get('location_lng'):
        required.append({
            'title': 'Location Data & Coordinates' if deck_en else 'بيانات الموقع والإحداثيات',
            'type': 'site_specs',
            'section_key': 'location',
            'design_style': 'table',
            'requires_image': False,
            'content_density': 'medium',
            'bullets': [],
            'content_source': 'location_detail',
        })
        for slide_type, title, source in (
            ('map_overview', 'Site & Location Map' if deck_en else 'خريطة الأرض والموقع', 'location_polygon'),
            ('map_access', 'Main Roads Map' if deck_en else 'خريطة الطرق الرئيسية', 'main_roads'),
            ('map_catchment', 'Area & Catchment Map' if deck_en else 'خريطة المنطقة ونطاق التأثير', 'catchment_areas'),
            ('map_landmarks', 'Nearby Landmarks Map' if deck_en else 'خريطة المعالم القريبة', 'nearby_landmarks'),
        ):
            if project_data.get(source) or slide_type == 'map_overview':
                required.append({
                    'title': title,
                    'type': slide_type,
                    'section_key': 'location',
                    'design_style': 'map',
                    'requires_image': True,
                    'content_density': 'medium',
                    'bullets': [],
                    'content_source': source,
                    'image_tokens': [f'##{slide_type.upper()}##'],
                })
        required.append({
            'title': 'Location Summary' if deck_en else 'ملخص الموقع الجغرافي',
            'type': 'content',
            'section_key': 'location',
            'design_style': 'map',
            'requires_image': True,
            'content_density': 'medium',
            'bullets': (['Site character and strategic position', 'Road and landmark connectivity', 'Evidence-based site advantages']
                        if deck_en else
                        ['طبيعة الموقع وموقعه الاستراتيجي', 'الاتصال بالطرق والمعالم المحيطة', 'المزايا المستندة إلى بيانات الموقع']),
            'content_source': 'site_analysis',
            'image_tokens': ['##MAP_OVERVIEW##'],
        })
    if not required:
        return plan
    insert_at = 2 if len(slides) >= 2 else len(slides)
    for item in required:
        if item['type'] in existing_types:
            existing_slides = [slide for slide in slides if isinstance(slide, dict) and slide.get('type') == item['type']]
            for existing in existing_slides:
                if item.get('image_tokens'):
                    existing['image_tokens'] = list(item['image_tokens'])
                    existing['requires_image'] = True
                    existing['design_style'] = item.get('design_style') or existing.get('design_style')
            continue
        slides.insert(insert_at, item)
        insert_at += 1
        existing_types.add(item['type'])
    plan['slides'] = slides
    plan['proposed_count'] = len(slides)
    return plan


def _execute_slide_plan(project_data, tenant_id, branding, images=None, target_section_keys=None):
    """Ask the planner for a slide plan, then enforce the company's slide bounds on it."""
    target_section_keys = tuple(
        key for key in (target_section_keys or ())
        if key in slide_engine.PRESENTATION_SECTION_ORDER
    )
    section_mode = bool(target_section_keys)
    training_context = db.get_training_context(tenant_id) or ''
    slide_count_locked = bool(branding.get('lock_slide_count')) and not section_mode
    bounds_branding = dict(branding)
    if section_mode:
        bounds_branding['lock_slide_count'] = False
    configured_min, configured_max, locked_count = resolve_slide_bounds(bounds_branding)

    effective_max_slides = max(1, configured_max)
    effective_min_slides = 1 if section_mode else min(configured_min, effective_max_slides)

    # A locked slide count outranks any hint found in the training context.
    if not slide_count_locked and not section_mode:
        # Search training context only for explicit min slide constraints
        matches = re.findall(r'(?:أقل|لا يقل عن|بدون أن يقل عن|الحد الأدنى|من|حوالي|أقل عدد|عدد الشرائح.*?لا يقل عن|الالتزام بـ).*?(\d+)', training_context)
        if matches:
            try:
                nums = [int(m) for m in matches if 1 <= int(m) <= 50]
                if nums:
                    detected_min = max(nums)
                    effective_min_slides = min(max(effective_min_slides, detected_min), effective_max_slides)
            except ValueError:
                pass

    effective_branding = dict(branding)
    effective_branding['min_slides'] = effective_min_slides
    effective_branding['max_slides'] = effective_max_slides
    if section_mode:
        effective_branding['lock_slide_count'] = False
    if slide_count_locked:
        effective_branding['default_slide_count'] = locked_count
    elif effective_branding.get('default_slide_count', 0) > effective_max_slides:
        effective_branding['default_slide_count'] = effective_max_slides

    prompt = build_slide_plan_prompt(project_data, effective_branding, tenant_id=tenant_id, images=images)
    offer_lang = slide_engine.resolve_offer_lang(project_data)
    if section_mode:
        target_titles = '، '.join(slide_engine.section_title(key, offer_lang) for key in target_section_keys)
        prompt = (
            "## نطاق العرض المستقل\n"
            f"أنشئ خطة للغلاف والفهرس والأقسام التالية فقط ثم الخاتمة: {target_titles}.\n"
            "لا تضف أي قسم آخر، ولا تطبق الحد الأدنى لعدد شرائح العرض الكامل.\n\n"
            + prompt
        )
    if training_context:
        # Only a locked count is a ceiling. Otherwise the count follows the content, and this
        # header used to contradict the prompt by naming a maximum the prompt calls open.
        count_rule = (
            "هذا عرض مستقل لقسم محدد، وعدد شرائحه يتبع محتوى القسم فقط."
            if section_mode else
            f"عدد الشرائح لهذه الشركة مقفل على {locked_count} شريحة بالضبط."
            if slide_count_locked else
            f"لا يقل عدد الشرائح عن {effective_min_slides} شريحة، ولا يوجد حد أعلى: "
            "وزّع كل المحتوى المتاح على ما يحتاجه من شرائح دون اختصار أو دمج، "
            "وابقِ كل شريحة بفكرة واحدة غير مزدحمة."
        )
        prompt = f"## بيانات خاصة بالشركة وقاعدة عدد الشرائح\nتنبيه هام جداً: {count_rule}\n{training_context}\n\n---\n\n{prompt}"

    plan = None
    last_error = None
    # The planner must finish before the web worker timeout so a slow provider can fall back cleanly.
    max_attempts = 1
    for attempt in range(1, max_attempts + 1):
        try:
            response = call_zai_chat_parallel(
                "أنت خبير في تحليل المحتوى وتوزيعه على شرائح العروض التقديمية الاستثمارية.",
                prompt,
                # The outline is compact; a bounded fast-model request avoids the five-minute
                # Gunicorn kill that previously left the background job stuck at 8 percent.
                max_tokens=12000,
                attempts=1,
                timeout=75,
                model=LUNA_TEXT_MODEL,
                usage_ctx=_usage_ctx('slide_plan', project_data, tenant_id=tenant_id)
            )
            content = extract_chat_content(response, "SLIDE-PLAN")
            plan = parse_slide_plan(content, effective_branding, project_data)
            print(f"[SLIDE-PLAN] Parsed on attempt {attempt}")
            break
        except Exception as e:
            last_error = e
            print(f"[SLIDE-PLAN ATTEMPT {attempt} FAILED] {e}")
            if attempt < max_attempts:
                time.sleep(1)

    # A failed planner used to be invisible: the generic fallback structure shipped as if the model
    # had produced it, so every such file came out with the same titles and the same count and it
    # looked like a fixed slide count instead of a failure.
    plan_source = 'model'
    plan_error = ''
    if not plan:
        print(f"[SLIDE-PLAN FALLBACK] Using fallback plan after {max_attempts} attempts. Last error: {last_error}")
        plan = build_fallback_plan(effective_branding, project_data)
        plan_source = 'fallback'
        plan_error = str(last_error or '')

    plan = _ensure_required_location_slides(plan, project_data)
    # A project with no financial study gets no financial slides at all, from any source.
    plan = slide_engine.strip_financial_slides(plan, project_data)
    # There are no photographs of the site, so a slide built to hold them holds empty frames.
    plan = slide_engine.strip_street_view_slides(plan)
    plan = slide_engine.normalize_presentation_plan(plan, project_data, images, tenant_id=tenant_id)
    has_financial = slide_engine.project_has_financial_study(project_data)

    # Enforce min and max slide counts strictly on generated plan
    slides = plan.get('slides', [])

    if len(slides) < effective_min_slides:
        print(f"[SLIDE-PLAN ENFORCE] Plan returned {len(slides)} slides, auto-padding to effective_min_slides ({effective_min_slides})")
        needed_extra = effective_min_slides - len(slides)
        if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
            extra_topics = [
                {'title': 'Technical Specifications & Material Quality', 'style': 'cards', 'bullets': ['Finishing quality and materials used', 'HVAC and thermal insulation systems', 'Warranties and after-sales services']},
                {'title': 'Environmental Analysis & Immediate Surroundings', 'style': 'text', 'bullets': ['Accessibility and key arterials', 'Proximity to amenities and vital centers', 'Quality of the surrounding built environment']},
                {'title': 'Timeline & Development Phases', 'style': 'timeline', 'bullets': ['Planning and initial studies phase', 'Execution and construction phase', 'Handover and operation phase']},
            ]
        else:
            extra_topics = [
                {'title': 'المواصفات الفنية وجودة المواد', 'style': 'cards', 'bullets': ['جودة التشطيبات والمواد المستخدمة', 'أنظمة التكييف والعزل الحراري', 'الضمانات وخدمات ما بعد البيع']},
                {'title': 'التحليل البيئي والمحيط المباشر', 'style': 'text', 'bullets': ['سهولة الوصول والمحاور الرئيسية', 'قرب المشروع من المرافق والمراكز الحيوية', 'جودة البيئة العمرانية المحيطة']},
                {'title': 'الخطة الزمنية ومراحل التطوير', 'style': 'timeline', 'bullets': ['مرحلة التخطيط والدراسات الأولية', 'مرحلة التنفيذ والإنشاءات', 'مرحلة التسليم والتشغيل']},
            ]
        if has_financial:
            if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
                extra_topics.insert(0, {'title': 'Performance Metrics & Added Value', 'style': 'dashboard', 'bullets': ['Expected investment return analysis', 'Occupancy and sustainability rate', 'Long-term asset value']})
            else:
                extra_topics.insert(0, {'title': 'مؤشرات الأداء والقيمة المضافة', 'style': 'dashboard', 'bullets': ['تحليل العائد الاستثماري المتوقع', 'معدل الإشغال والاستدامة', 'قيمة الأصول على المدى الطويل']})
        insert_idx = max(1, len(slides) - 1)
        if len(slides) >= 2 and slides[-2].get('type') == 'moodboard':
            insert_idx = max(1, len(slides) - 2)

        for i in range(needed_extra):
            topic = extra_topics[i % len(extra_topics)]
            new_slide = {
                'title': topic['title'] + (f" ({i+1})" if i >= len(extra_topics) else ""),
                'type': 'content',
                'design_style': topic['style'],
                'requires_image': False,
                'bullets': topic['bullets'],
                'content_density': 'medium',
            }
            slides.insert(insert_idx, new_slide)
            insert_idx += 1

    plan['slides'] = slides
    plan = slide_engine.normalize_presentation_plan(plan, project_data, images, tenant_id=tenant_id)
    slides = plan['slides']

    # Trimming only happens for a tenant who locked the count: without a lock the maximum is
    # SLIDE_COUNT_OPEN, so a long plan is kept exactly as the planner produced it.
    if len(slides) > effective_max_slides:
        print(f"[SLIDE-PLAN TRIM] Plan returned {len(slides)} slides, trimming strictly to effective_max_slides ({effective_max_slides})")
        if effective_max_slides == 1:
            slides = slides[:1]
        else:
            first_slides = slides[:1]
            last_slides = slides[-1:]
            middle_count = max(0, effective_max_slides - 2)
            middle_slides = slides[1:1+middle_count]
            slides = first_slides + middle_slides + last_slides

    plan['proposed_count'] = len(slides)
    plan['slides'] = slides
    plan = slide_engine.refresh_index_entries(plan)
    if section_mode:
        filtered_plan = slide_engine.filter_presentation_plan_sections(plan, target_section_keys)
        if not filtered_plan:
            target_titles = '، '.join(slide_engine.PRESENTATION_SECTION_TITLES[key] for key in target_section_keys)
            return {
                'success': False,
                'error': f'لا توجد بيانات متاحة لتوليد عرض قسم {target_titles}',
                'failureReason': 'section_empty',
            }
        plan = filtered_plan
    plan['source'] = plan_source
    if plan_error:
        plan['source_error'] = plan_error[:400]

    is_valid, issues = validate_slide_plan(plan, effective_branding)
    if not is_valid:
        print(f"[SLIDE-PLAN] Validation issues: {issues}")

    return {
        'success': True,
        'plan': plan,
        'planSource': plan_source,
        'validation': {'isValid': is_valid, 'issues': issues},
    }


def _emergency_slide_plan(project_data, branding, images, tenant_id, target_section_keys=None):
    plan = build_fallback_plan(branding, project_data)
    plan = _ensure_required_location_slides(plan, project_data)
    plan = slide_engine.strip_financial_slides(plan, project_data)
    plan = slide_engine.strip_street_view_slides(plan)
    plan = slide_engine.normalize_presentation_plan(plan, project_data, images, tenant_id=tenant_id)
    if target_section_keys:
        filtered = slide_engine.filter_presentation_plan_sections(plan, target_section_keys)
        if filtered:
            plan = filtered
    plan = slide_engine.refresh_index_entries(plan)
    plan['source'] = 'fallback'
    return plan


def _slide_plan_job_worker(flask_app, tenant_id, project_data, branding, images, job_id, target_section_keys=None):
    with flask_app.app_context():
        fallback_plan = _emergency_slide_plan(
            project_data, branding, images, tenant_id, target_section_keys=target_section_keys)
        _write_job('.plan_jobs', tenant_id, job_id, {
            'status': 'running',
            'success': True,
            'message': 'جاري تحليل بيانات المشروع وإعداد هيكل العرض...',
            'fallbackPlan': fallback_plan,
        })
        try:
            payload = _execute_slide_plan(
                project_data, tenant_id, branding, images,
                target_section_keys=target_section_keys,
            )
            succeeded = bool(payload.get('success'))
            _write_job('.plan_jobs', tenant_id, job_id, {
                **payload,
                'status': 'completed' if succeeded else 'failed',
                'message': 'تم إعداد خطة الشرائح' if succeeded else payload.get('error', 'تعذر إعداد خطة الشرائح'),
            })
        except Exception as exc:
            print(f'[SLIDE-PLAN JOB FAILED] {exc}')
            _write_job('.plan_jobs', tenant_id, job_id, {
                'status': 'failed',
                'success': False,
                'error': f'تعذر إعداد خطة الشرائح: {exc}',
                'failureReason': 'job_failed',
            })


@app.route('/api/slide-plan', methods=['POST'])
@require_permission('create_presentation')
def api_slide_plan():
    """
    AI analyzes project data and proposes a slide plan.
    Input: {projectData: {...}}
    Output: {jobId} in production, or {proposed_count, reasoning, slides: [...]} in tests.

    The planner needs minutes on a full project, and the live hosting proxy drops a request that
    stays open that long — the browser then saw a timeout for work the server had completed. So the
    plan is queued and polled, the same way the croquis and market-study jobs are.
    """
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    _billing_guard = _require_billing_balance('slide_plan')
    if _billing_guard is not None:
        return _billing_guard
    presentation_id = str(data.get('presentationId') or '').strip()
    if presentation_id and not project_data:
        presentation = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
        if not presentation or not _presentation_in_scope(presentation):
            return jsonify({'success': False, 'error': 'العرض غير موجود أو لا يتبع هذه الشركة'}), 404
        try:
            project_data = clean_project_data(json.loads(presentation.get('project_data') or '{}'))
        except (TypeError, ValueError):
            project_data = {}
        project_data = _merge_persisted_map_assets(
            project_data, g.tenant_id, presentation_id=presentation_id)
    images = _augment_generation_images(data.get('images', {}), project_data, g.tenant_id)
    branding = db.get_branding(g.tenant_id)
    project_section_key = str(data.get('sectionKey') or '').strip()
    section_target = PROJECT_SECTION_PRESENTATION_TARGETS.get(project_section_key) if project_section_key else None

    if project_section_key and not section_target:
        return jsonify({'success': False, 'error': 'قسم المشروع غير صالح'}), 400
    if not branding:
        return jsonify({'error': 'Branding not configured'}), 400
    if section_target:
        # A section-scoped plan is bound to that section's own approval — the
        # all-sections gate belongs to the full-file generation only. Only a
        # draft the request actually names can be checked; a draftless call
        # (e.g. replanning slides of a saved presentation) has nothing to
        # verify against and passes.
        section_draft_id = (project_data.get('draftId') or project_data.get('draft_id')
                            or data.get('draftId'))
        section_draft = (db.get_project_draft_by_id(g.tenant_id, section_draft_id)
                         if section_draft_id else None)
        if section_draft and (section_draft.get('section_statuses') or {}).get(project_section_key) != 'approved':
            return jsonify({'success': False,
                            'error': 'توليد هذا القسم يتطلب اعتماده أولًا',
                            'error_code': 'section_not_approved'}), 409

    target_section_keys = section_target[0] if section_target else None
    use_background = (not current_app.config.get('TESTING')) or bool(data.get('background'))
    if not use_background:
        payload = _execute_slide_plan(
            project_data, g.tenant_id, branding, images,
            target_section_keys=target_section_keys,
        )
        return jsonify(payload), 200 if payload.get('success') else 400

    job_id = str(_uuid.uuid4())
    fallback_plan = _emergency_slide_plan(
        project_data, branding, images, g.tenant_id, target_section_keys=target_section_keys)
    _write_job('.plan_jobs', g.tenant_id, job_id, {
        'status': 'queued',
        'success': True,
        'message': 'تم استلام طلب إعداد هيكل العرض',
        'fallbackPlan': fallback_plan,
        'payload': {
            'projectData': project_data,
            'images': images,
            'targetSectionKeys': target_section_keys,
        },
    })
    threading.Thread(
        target=_slide_plan_job_worker,
        args=(current_app._get_current_object(), g.tenant_id, project_data, dict(branding), images, job_id, target_section_keys),
        daemon=True,
    ).start()
    return jsonify({
        'success': True,
        'jobId': job_id,
        'status': 'queued',
        'message': 'بدأ إعداد هيكل العرض في الخلفية',
        'fallbackPlan': fallback_plan,
    }), 202


@app.route('/api/slide-plan/jobs/<job_id>', methods=['GET'])
@require_permission('create_presentation')
def api_slide_plan_job(job_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(job_id or '')):
        return jsonify({'success': False, 'error': 'معرف مهمة غير صالح'}), 400
    job = _read_job('.plan_jobs', g.tenant_id, job_id)
    if not job:
        return jsonify({
            'success': False,
            'status': 'not_found',
            'error': 'المهمة غير موجودة أو انتهت صلاحيتها',
            'failureReason': 'job_not_found',
        }), 404
    return jsonify(_public_job(job))


def _generation_map_marker_side(images, project_data, view='overview'):
    images = images if isinstance(images, dict) else {}
    project_data = project_data if isinstance(project_data, dict) else {}
    centers = images.get('map_centers') if isinstance(images.get('map_centers'), dict) else {}
    center = centers.get(view) if isinstance(centers.get(view), dict) else {}
    try:
        marker_lng = float(images.get('map_lng') or project_data.get('location_lng'))
        center_lng = float(center.get('lng'))
    except (TypeError, ValueError):
        return 'right'
    return 'left' if marker_lng < center_lng else 'right'


def _generation_sent_value_matches(sent, stored):
    """Deep-compare a sent generation input against its stored counterpart.

    Forward-only: every key the client sent must agree with storage, while
    stored keys legitimately absent from the payload (the client slims the
    request) are ignored. ``clean_project_data`` replaces embedded image data
    with ``[IMAGE_DATA_OMITTED]`` before the guard runs — a leaf the run only
    ever sees as the placeholder, so it matches whatever storage holds. The
    same applies to ``blob:`` URLs, which the backend cannot consume.
    """
    if isinstance(sent, str) and (sent == '[IMAGE_DATA_OMITTED]' or sent.startswith('blob:')):
        return True
    if isinstance(sent, str) and isinstance(stored, (dict, list)):
        try:
            sent = json.loads(sent)
        except (TypeError, ValueError):
            pass
    elif isinstance(stored, str) and isinstance(sent, (dict, list)):
        try:
            stored = json.loads(stored)
        except (TypeError, ValueError):
            pass
    if isinstance(sent, dict) and isinstance(stored, dict):
        return all(_generation_sent_value_matches(value, stored.get(key))
                   for key, value in sent.items())
    if isinstance(sent, list) and isinstance(stored, list):
        return len(sent) == len(stored) and all(
            _generation_sent_value_matches(a, b) for a, b in zip(sent, stored))
    return _draft_values_equal(db.normalize_generation_input(sent),
                               db.normalize_generation_input(stored))


def _generation_sent_input_matches(key, sent_value, stored_value, stored_data=None):
    """Whether one client-sent generation input agrees with the stored draft.

    Two fields reach the wire in a slimmed shape (slimGenerationProjectData):
    ``financial_study_model`` gains an injected ``report`` companion and
    ``land_photos_file_meta`` collapses each photo to {id, imageUrl,
    originalName, description} — they are compared in that normalized form.
    ``landmarks_matrix`` may be mirrored client-side from map_landmarks or
    nearby_landmarks_data; if absent at root in storage it falls back to those.
    """
    if key == 'projectName':
        target = stored_value
        if target is None and isinstance(stored_data, dict):
            target = stored_data.get('project_name')
        return _generation_sent_value_matches(sent_value, target)
    if key == 'financial_study_model':
        strip = lambda model: ({k: v for k, v in model.items() if k != 'report'}
                               if isinstance(model, dict) else model)
        return _generation_sent_value_matches(strip(sent_value), strip(stored_value))
    if key == 'land_photos_file_meta':
        def norm(items):
            return [
                {
                    'id': photo.get('id') or '',
                    'imageUrl': photo.get('imageUrl') or photo.get('url') or '',
                    'originalName': photo.get('originalName') or photo.get('name') or '',
                    'description': photo.get('description') or '',
                }
                for photo in (items if isinstance(items, list) else [])
                if isinstance(photo, dict)
            ]
        return db.normalize_generation_input(norm(sent_value)) == db.normalize_generation_input(
            norm(stored_value))
    if key == 'landmarks_matrix':
        target = stored_value
        if target is None and isinstance(stored_data, dict):
            creative = stored_data.get('tenantCreativeImages')
            if isinstance(creative, dict) and creative.get('map_landmarks') is not None:
                target = creative.get('map_landmarks')
            elif stored_data.get('nearby_landmarks_data') is not None:
                target = stored_data.get('nearby_landmarks_data')
        if target is not None:
            return _generation_sent_value_matches(sent_value, target)
        return True
    return _generation_sent_value_matches(sent_value, stored_value)


def _generation_inputs_guard(project_data, section_key=''):
    """t14-04/t15-01: draft-scoped generation stays inside its approval gate.

    Returns None when the run is clean. Once projectData names a draft, a live
    ``approved`` generation approval must exist (settlement moves the row to
    ``consumed``, so the gate is per-run), the stored draft must still match the
    approved snapshot, and every generation input the request actually carries
    must agree with that stored draft — slimmed keys legitimately absent from
    the payload are skipped, reshaped fields are compared normalized. A lookup
    failure fails closed rather than letting generation slip the gate.

    A ``section_key`` scopes the run to one project section: the approval must
    then carry the same scope (a full-file approval does not cover a section
    run and vice versa) and that section — not every section — must be
    approved on the draft.
    """
    draft_id = project_data.get('draftId') or project_data.get('draft_id')
    if not draft_id:
        return None
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if not draft:
        return None
    if not db.user_may_access_draft(g.user_id, draft):
        return jsonify({'error': 'المشروع غير موجود'}), 404
    section_key = str(section_key or '').strip() or None
    try:
        if section_key:
            approval = db.get_db().execute(
                "SELECT * FROM generation_approvals WHERE tenant_id = ? AND draft_id = ? "
                "AND status = 'approved' AND section_key = ? ORDER BY decided_at DESC LIMIT 1",
                (g.tenant_id, draft_id, section_key)).fetchone()
        else:
            approval = db.get_db().execute(
                "SELECT * FROM generation_approvals WHERE tenant_id = ? AND draft_id = ? "
                "AND status = 'approved' AND (section_key IS NULL OR section_key = '') "
                "ORDER BY decided_at DESC LIMIT 1",
                (g.tenant_id, draft_id)).fetchone()
    except Exception:
        app.logger.warning('generation gate lookup failed for draft %s', draft_id, exc_info=True)
        return jsonify({'error': 'تعذر التحقق من اعتماد التوليد — أعد المحاولة',
                        'error_code': 'generation_gate_unverified'}), 503
    if section_key and (draft.get('section_statuses') or {}).get(section_key) != 'approved':
        return jsonify({'error': 'توليد هذا القسم يتطلب اعتماده أولًا',
                        'error_code': 'section_not_approved'}), 409
    if not approval:
        return jsonify({'error': 'توليد هذا المشروع يتطلب اعتماد توليد ساريًا',
                        'error_code': 'generation_not_approved'}), 409
    snapshot = db._json_object(approval['input_snapshot'] if 'input_snapshot' in approval.keys() else None)
    stored_data = draft.get('draft_data') or {}
    section_map = _draft_field_section_map(g.tenant_id) if section_key else None
    if section_key:
        # A section approval froze that section's inputs only — drift anywhere
        # else is none of this run's business.
        wanted = snapshot.get('section_hash')
        if wanted:
            live_hash = db.section_snapshot_hash(_section_snapshot_slice(
                stored_data, section_key, section_map))
            if live_hash != wanted:
                return jsonify({'error': 'مدخلات هذا القسم تغيّرت عن النسخة المعتمدة — أعد طلب التوليد',
                                'error_code': 'inputs_changed'}), 409
    else:
        wanted = snapshot.get('draft_hash')
        if wanted and db.draft_generation_input_hash(stored_data) != wanted:
            return jsonify({'error': 'مدخلات المشروع تغيّرت عن النسخة المعتمدة — أعد طلب التوليد',
                            'error_code': 'inputs_changed'}), 409
    for key, value in project_data.items():
        if key in db.GENERATION_INPUT_EXCLUDED_KEYS:
            continue
        if key.endswith('_file_meta') and key != 'land_photos_file_meta':
            continue
        if section_key:
            key_belongs = (
                _draft_section_of_key(section_map, key) == section_key
                or key in SECTION_SNAPSHOT_BLOBS.get(section_key, [])
                or (section_key == 'location' and key in SECTION_SNAPSHOT_LOCATION_EXTRAS)
            )
            if not key_belongs:
                continue
        if not _generation_sent_input_matches(key, value, stored_data.get(key), stored_data=stored_data):
            return jsonify({'error': 'مدخلات التوليد المرسلة لا تطابق المشروع المعتمد',
                            'error_code': 'inputs_changed', 'input_key': key}), 409
    return None


@app.route('/api/generate-slide-single', methods=['POST'])
@require_permission('create_presentation')
def api_generate_slide_single():
    """Generate a single slide by index. Returns one slide HTML."""
    from slide_engine import generate_single_slide, build_design_rules, finalize_slide_html
    data = request.json or {}
    _billing_guard = _require_billing_balance('slide_single')
    if _billing_guard is not None:
        return _billing_guard
    project_data = clean_project_data(data.get('projectData', {}))
    _inputs_guard = _generation_inputs_guard(project_data, section_key=data.get('sectionKey'))
    if _inputs_guard is not None:
        return _inputs_guard
    presentation_id = str(data.get('presentationId') or '').strip() or None
    project_data, request_images = _hydrate_map_assets_for_request(
        project_data, data.get('images', {}), g.tenant_id, presentation_id=presentation_id
    )
    slide_plan = data.get('slidePlan', {})
    images = _augment_generation_images(request_images, project_data, g.tenant_id)
    slide_index = int(data.get('slideIndex', 0))

    if not slide_plan or 'slides' not in slide_plan:
        return jsonify({'error': 'slidePlan with slides array is required'}), 400

    slides = slide_plan.get('slides', [])
    # The client may send just the single slide needed (slideIndex always 0)
    # together with a _totalSlides field for the real deck size and a _slideNum
    # field for this slide's real one-based position in that deck. Numbering,
    # cover/closing detection and header/footer all follow _slideNum: using the
    # snapshot index (always 1) mistook every slide for the cover and stripped
    # its chrome without re-adding it.
    _total_slides_override = data.get('_totalSlides')
    total_slides = int(_total_slides_override) if isinstance(_total_slides_override, (int, float)) and _total_slides_override > 0 else len(slides)
    if slide_index < 0 or slide_index >= len(slides):
        return jsonify({'error': 'Invalid slide index'}), 400
    try:
        slide_num = int(data.get('_slideNum') or 0)
    except (TypeError, ValueError):
        slide_num = 0
    if slide_num < 1 or slide_num > total_slides:
        slide_num = slide_index + 1

    branding = db.get_branding(g.tenant_id)
    if not branding:
        return jsonify({'error': 'Branding not configured'}), 400
    _prepare_generation_logo_context(project_data, branding, g.tenant_id)
    project_data['_map_marker_side'] = _generation_map_marker_side(images, project_data)

    # Map generation is explicit. A single-slide request may reuse supplied
    # persisted assets, but it must never trigger a hidden Google/OSM call.
    map_placeholders = {}
    has_maps = isinstance(images, dict) and isinstance(images.get('map_placeholders'), dict) and bool(images.get('map_placeholders'))
    if has_maps:
        map_placeholders = {key: value for key, value in images.get('map_placeholders', {}).items() if value}
        resolved_location = project_data.get('_resolved_location')
        if not isinstance(resolved_location, dict):
            resolved_location = {}
        if project_data.get('location_lat') and project_data.get('location_lng'):
            project_data['_resolved_location'] = {
                'lat': resolved_location.get('lat') or project_data.get('location_lat'),
                'lng': resolved_location.get('lng') or project_data.get('location_lng'),
            }

    images_info = _get_images_info(images, project_data)
    training_context = db.get_training_context(g.tenant_id)

    design_rules = build_design_rules(branding)
    # Every collected fact, grouped by section. This used to be the raw draft cut at 4,000
    # characters, which silently dropped the market study, the executive content and the team.
    project_json = slide_engine.build_project_facts(project_data, g.tenant_id)

    landmarks_matrix = project_data.get('nearby_landmarks_data') or project_data.get('landmarks_matrix')
    landmarks_note = ''
    if landmarks_matrix:
        landmarks_note = (
            " إرشادات هامة لعرض المعالم:\n"
            "يجب عرض المسافة والوقت معاً لكل معلم بدون استثناء بالصيغة التاعية: (اسم المعلم - المسافة بالكم - الوقت بالدقائق)، مثل: 'ميدان السارية (1.5 كم - 5 دقائق)'.\n"
            "استخدم البيانات الموثقة التالية كما هي وممنوع تعديل الأرقام:\n" +
            json.dumps(landmarks_matrix, ensure_ascii=False, indent=2)
        )
    timeline_note = _timeline_data_note(project_data)
    financial_note = _financial_data_note(project_data)

    system_prompt = f"""{design_rules}

## بيانات المشروع
{project_json}

## الصور المتوفرة
{images_info}

## بيانات المسافات والأوقات (ممنوع تعديل الأرقام)
{landmarks_note}
{timeline_note}
{financial_note}

## قواعد عامة
- كل شريحة 1280x720px (أو حسب نسبة العرض المحددة)
- CSS inline فقط
- ممنوع box-shadow/filter/backdrop-filter
- استخدم ##LOGO## للشعار، ##IMAGE_COVER## لصورة الغلاف، ##MOODBOARD_IMAGE_N## لصور المود بورد
- للخرائط: ##MAP_OVERVIEW##، ##MAP_LANDMARKS##، ##MAP_ACCESS##، ##MAP_CATCHMENT## — استخدمها في شرائح تحليل الموقع الجغرافي أو تحليل الأرض عند طلبها صراحة أو ملخص الموقع المحدد صراحة، وممنوع استخدامها في الجدول الزمني أو الدراسة المالية أو المخططات أو التصورات الخارجية أو الداخلية أو أي قسم آخر
-  ممنوع base64 أو روابط صور خارجية
- {slide_engine.NO_STREET_VIEW_RULE}
"""

    def call_glm_fn(sys_prompt, user_msg, max_tokens=6000):
        if training_context:
            sys_prompt = f"{sys_prompt}\n\n## بيانات خاصة بالشركة\n{training_context}"
        # Inside a background slide job the worker streams the single call and
        # publishes live previews; the request, model and limits are identical,
        # so the completion - and the validation loop around it - is unchanged.
        # Direct (non-job) calls keep the previous raced behaviour byte for byte.
        stream_job = getattr(g, '_slide_stream_job', None)
        if isinstance(stream_job, dict) and stream_job.get('job_id'):
            return call_zai_chat_stream(sys_prompt, user_msg, max_tokens=max_tokens, model=SLIDE_TEXT_MODEL, usage_ctx=_usage_ctx('slide', data, presentation_id=presentation_id), on_token=_slide_stream_progress(g.tenant_id, stream_job['job_id']))
        return call_zai_chat_parallel(sys_prompt, user_msg, max_tokens=max_tokens, attempts=1, model=SLIDE_TEXT_MODEL, usage_ctx=_usage_ctx('slide', data, presentation_id=presentation_id))

    # Apply the same ownership repair used by the full-plan normalizer before
    # rendering and before returning slide metadata. A single-slide retry can
    # arrive from an older saved plan that misclassified a map or financial
    # slide, so finalization must see the repaired type/source too.
    slide = slide_engine._normalize_legacy_single_slide(
        dict(slides[slide_index] or {}), project_data
    )
    total = total_slides
    # One retry is the ceiling: postprocess_slide already repairs fixable output
    # (contrast, surface, readability), so extra attempts mostly re-design the
    # same slide while the meter runs. Exhausted attempts fall back to the
    # deterministic renderer inside generate_single_slide.
    html = generate_single_slide(system_prompt, slide, slide_num, total, branding, call_glm_fn, max_retries=1, project_data=project_data)

    # Never turn a failed generation into a fake successful slide. The client
    # can retry the request, but it must not save an incomplete presentation.
    if len(extract_slide_elements(html or '')) != 1:
        title = slide.get('title', f'شريحة {slide_num}')
        return jsonify({
            'success': False,
            'error': f'تعذر توليد الشريحة {slide_num}: {title}',
            'slideIndex': slide_index,
            'totalSlides': total,
        }), 503

    html = finalize_slide_html(
        html,
        slide.get('type', 'content'),
        project_data,
        branding,
        creative_images=images,
        map_placeholders=map_placeholders,
        tenant_id=g.tenant_id,
        slide_num=slide_num,
        slide_title=slide.get('title', f'شريحة {slide_num}'),
        total_slides=total,
        content_source=slide.get('content_source'),
    )

    return jsonify({
        'success': True,
        'slide': {
            'html': html,
            'title': slide.get('title', f'شريحة {slide_num}'),
            'type': slide.get('type', 'content'),
            'sectionKey': slide.get('section_key', ''),
            'contentSource': slide.get('content_source', ''),
            'sourceTable': slide.get('source_table', ''),
            'indexEntries': slide.get('index_entries', []),
            'designStyle': slide.get('design_style', 'cards'),
        },
        'slideIndex': slide_index,
        'totalSlides': total,
    })


def _run_slide_generation_job(flask_app, tenant_id, payload, job_id, authorization):
    """Run one slide request outside the hosting proxy's request lifetime."""
    with flask_app.test_request_context(
            '/api/generate-slide-single', method='POST', json=payload,
            headers={'Authorization': authorization}):
        # g is bound to this worker's request context, so the single-slide
        # route streams this job's completion as live previews through it.
        g._slide_stream_job = {'tenant_id': tenant_id, 'job_id': job_id}
        try:
            result = api_generate_slide_single()
            response = result[0] if isinstance(result, tuple) else result
            status_code = result[1] if isinstance(result, tuple) and len(result) > 1 else response.status_code
            body = response.get_json(silent=True) or {}
            if 200 <= int(status_code) < 300 and body.get('success'):
                _write_job('.slide_jobs', tenant_id, job_id, {
                    **body, 'status': 'completed', 'success': True,
                })
            else:
                _write_job('.slide_jobs', tenant_id, job_id, {
                    **body,
                    'status': 'failed',
                    'success': False,
                    'error': body.get('error') or f'فشل توليد الشريحة (HTTP {status_code})',
                })
        except Exception as exc:
            print(f'[SLIDE GENERATION JOB FAILED] {exc}')
            _write_job('.slide_jobs', tenant_id, job_id, {
                'status': 'failed',
                'success': False,
                'error': f'تعذر توليد الشريحة: {exc}',
                'failureReason': 'job_failed',
            })


@app.route('/api/generate-slide-single-job', methods=['POST'])
@require_permission('create_presentation')
def api_generate_slide_single_job():
    """Queue one slide so a slow AI response cannot become a proxy 404."""
    data = request.json or {}
    _inputs_guard = _generation_inputs_guard(
        data.get('projectData') if isinstance(data.get('projectData'), dict) else {},
        section_key=data.get('sectionKey'))
    if _inputs_guard is not None:
        return _inputs_guard
    slide_plan = data.get('slidePlan') or {}
    slides = slide_plan.get('slides') if isinstance(slide_plan, dict) else None
    if not isinstance(slides, list) or not slides:
        return jsonify({'success': False, 'error': 'slidePlan with slides array is required'}), 400
    job_id = str(_uuid.uuid4())
    tenant_id = g.tenant_id
    authorization = request.headers.get('Authorization', '')
    _write_job('.slide_jobs', tenant_id, job_id, {
        'status': 'queued',
        'success': True,
        'message': 'تم استلام طلب توليد الشريحة',
        'payload': {'data': data},
        'actor': {
            'user_id': getattr(g, 'user_id', None),
            'user_name': getattr(g, 'user_name', None),
            'user_role': getattr(g, 'user_role', None),
        },
    })
    threading.Thread(
        target=_run_slide_generation_job,
        args=(current_app._get_current_object(), tenant_id, data, job_id, authorization),
        daemon=True,
    ).start()
    return jsonify({
        'success': True,
        'jobId': job_id,
        'status': 'queued',
        'message': 'بدأ توليد الشريحة في الخلفية',
    }), 202


@app.route('/api/generate-slide-single/jobs/<job_id>', methods=['GET'])
@require_permission('create_presentation')
def api_generate_slide_single_job_status(job_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(job_id or '')):
        return jsonify({'success': False, 'error': 'معرف مهمة غير صالح'}), 400
    job = _read_job('.slide_jobs', g.tenant_id, job_id)
    if not job:
        return jsonify({
            'success': False,
            'status': 'not_found',
            'error': 'المهمة غير موجودة أو انتهت صلاحيتها',
            'failureReason': 'job_not_found',
        }), 404
    return jsonify(_public_job(job))


@app.route('/api/generate-slides', methods=['POST'])
@require_permission('create_presentation')
def api_generate_slides():
    """
    Generate all slides HTML based on a slide plan.
    Input: {projectData: {...}, slidePlan: {...}, images: {...}}
    Output: {slides: [{html, title, type}], slideCount}
    """
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    _inputs_guard = _generation_inputs_guard(project_data, section_key=data.get('sectionKey'))
    if _inputs_guard is not None:
        return _inputs_guard
    slide_plan = data.get('slidePlan', {})
    presentation_id = str(data.get('presentationId') or '').strip() or None
    project_data, request_images = _hydrate_map_assets_for_request(
        project_data, data.get('images', {}), g.tenant_id, presentation_id=presentation_id
    )
    images = _augment_generation_images(request_images, project_data, g.tenant_id)

    branding = db.get_branding(g.tenant_id)
    if not branding:
        return jsonify({'error': 'Branding not configured'}), 400

    if not slide_plan or 'slides' not in slide_plan:
        return jsonify({'error': 'slidePlan with slides array is required'}), 400
    slide_plan = slide_engine.normalize_market_section_plan(slide_plan, project_data) or slide_plan
    _prepare_generation_logo_context(project_data, branding, g.tenant_id)
    project_data['_map_marker_side'] = _generation_map_marker_side(images, project_data)

    # Map generation is explicit. Reuse only placeholders already supplied by the
    # caller or persisted by a previous, user-triggered map generation.
    map_placeholders = {}
    if isinstance(images, dict):
        supplied_placeholders = images.get('map_placeholders')
        if isinstance(supplied_placeholders, dict):
            map_placeholders = {key: value for key, value in supplied_placeholders.items() if value}
    elif isinstance(images, list):
        images = {'cover': images[0] if images else None, 'moodboard': []}

    images_info = _get_images_info(images, project_data)

    training_context = db.get_training_context(g.tenant_id)

    # Define the GLM call function for the slide engine
    def call_glm_fn(sys_prompt, user_msg, max_tokens=6000):
        if training_context:
            sys_prompt = f"{sys_prompt}\n\n## بيانات خاصة بالشركة\n{training_context}"
        return call_zai_chat_parallel(sys_prompt, user_msg, max_tokens=max_tokens, attempts=2, model=SLIDE_TEXT_MODEL, usage_ctx=_usage_ctx('slide', data, presentation_id=presentation_id))

    try:
        htmls = generate_all_slides(
            slide_plan, project_data, branding, images_info, call_glm_fn,
            map_placeholders=map_placeholders, creative_images=images
        )

        slides_out = []
        plan_slides = slide_plan.get('slides', [])
        for i, html in enumerate(htmls):
            slide_info = plan_slides[i] if i < len(plan_slides) else {}
            slides_out.append({
                'html': html or '',
                'title': slide_info.get('title', f'شريحة {i+1}'),
                'type': slide_info.get('type', 'content'),
                'sectionKey': slide_info.get('section_key', ''),
                'contentSource': slide_info.get('content_source', ''),
                'sourceTable': slide_info.get('source_table', ''),
                'indexEntries': slide_info.get('index_entries', []),
                'designStyle': slide_info.get('design_style', 'cards'),
            })

        return jsonify({
            'success': True,
            'slides': slides_out,
            'slideCount': len(slides_out),
        })
    except Exception as e:
        print(f"[GENERATE-SLIDES ERROR] {e}")
        return jsonify({'error': str(e)}), 500


def _merge_persisted_map_assets(project_data, tenant_id, presentation_id=None, draft_id=None):
    if not isinstance(project_data, dict):
        return project_data or {}
    records = db.get_map_images(tenant_id, presentation_id=presentation_id, draft_id=draft_id)
    if not records:
        return project_data
    creative = project_data.get('tenantCreativeImages')
    if not isinstance(creative, dict):
        creative = {}
    placeholders = {}
    map_zooms = {}
    map_centers = {}
    map_highlight_site = None
    seen_types = set()
    seen_placeholders = set()
    for record in records:
        path = record.get('file_path')
        placeholder = record.get('placeholder')
        image_type = record.get('image_type') or ''
        if not path or not placeholder or not os.path.exists(path):
            continue
        try:
            metadata = json.loads(record.get('metadata_json') or '{}')
        except (TypeError, ValueError):
            metadata = {}
        if image_type in seen_types or placeholder in seen_placeholders:
            continue
        seen_types.add(image_type)
        seen_placeholders.add(placeholder)
        try:
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
        except ValueError:
            rel_path = 'uploads/maps/' + os.path.basename(path)
        placeholders[placeholder] = '/' + rel_path

        # The file itself remains a valid persisted map even when a later
        # renderer version changed its overlays or labels.  Keep importing that
        # image so slide generation never produces an empty map frame.  Only
        # trust the attached metadata for marker-aware layout when both versions
        # match the renderer that produced the current map implementation.
        current_map_metadata = (
            metadata.get('map_highlight_version') == maps_service.MAP_HIGHLIGHT_RENDER_VERSION
            and metadata.get('map_label_version') == maps_service.MAP_LABEL_RENDER_VERSION
        )
        if not current_map_metadata:
            continue
        # The map row is the source of truth for the image that was actually
        # approved.  Project JSON can lag behind it when a user edits a map and
        # immediately starts presentation generation, so do not let stale JSON
        # metadata survive a hydration pass.
        if metadata.get('lat') is not None:
            creative['map_lat'] = metadata['lat']
        if metadata.get('lng') is not None:
            creative['map_lng'] = metadata['lng']
        if metadata.get('zoom') is not None:
            base_type = image_type
            for suffix in ('_editable', '_satellite', '_roadmap'):
                if base_type.endswith(suffix):
                    base_type = base_type[:-len(suffix)]
            map_zooms.setdefault(base_type, metadata['zoom'])
        if metadata.get('center_lat') is not None and metadata.get('center_lng') is not None:
            base_type = image_type
            for suffix in ('_editable', '_satellite', '_roadmap'):
                if base_type.endswith(suffix):
                    base_type = base_type[:-len(suffix)]
            if base_type in {'overview', 'access', 'catchment', 'landmarks'}:
                map_centers.setdefault(base_type, {
                    'lat': metadata['center_lat'], 'lng': metadata['center_lng']
                })
        if 'landmarks_matrix' in metadata:
            creative['map_landmarks'] = metadata['landmarks_matrix']
        if 'access_roads' in metadata:
            project_data['access_roads_data'] = metadata['access_roads']
            creative['map_access_roads'] = metadata['access_roads']
        if 'catchment_landmarks' in metadata:
            project_data['catchment_map_landmarks'] = metadata['catchment_landmarks']
            creative['map_catchment_landmarks'] = metadata['catchment_landmarks']
        if 'landmark_map_items' in metadata:
            project_data['landmark_map_items'] = metadata['landmark_map_items']
            creative['map_landmark_items'] = metadata['landmark_map_items']
        if metadata.get('highlight_site') is not None:
            map_highlight_site = bool(metadata.get('highlight_site'))
    existing_placeholders = creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {}
    merged_placeholders = {key: value for key, value in existing_placeholders.items() if key and value}
    merged_placeholders.update(placeholders)
    creative['map_placeholders'] = merged_placeholders
    creative['maps_persisted'] = bool(merged_placeholders)
    if map_highlight_site is not None:
        creative['map_highlight_site'] = map_highlight_site
    if map_zooms:
        creative['map_zooms'] = map_zooms
    if map_centers:
        creative['map_centers'] = map_centers
    project_data['tenantCreativeImages'] = creative
    return project_data


def _hydrate_map_assets_for_request(project_data, images, tenant_id, presentation_id=None):
    """Restore saved map URLs before a slide, plan, or designer request runs.

    Map files are persisted separately from the presentation JSON.  A request may
    therefore have a perfectly valid presentation id but an incomplete client
    ``creativeImages`` object, especially after reopening an older draft.  Merge
    the DB-backed assets first, then use request values only as a fallback when
    no persisted map file exists for that placeholder.
    """
    source = project_data if isinstance(project_data, dict) else {}
    request_images = dict(images) if isinstance(images, dict) else {}
    draft_id = source.get('draftId') or source.get('draft_id')
    persisted_records = []
    if presentation_id or draft_id:
        source = _merge_persisted_map_assets(
            source, tenant_id, presentation_id=presentation_id, draft_id=draft_id
        )
        persisted_records = db.get_map_images(
            tenant_id, presentation_id=presentation_id, draft_id=draft_id
        )

    creative = source.get('tenantCreativeImages') if isinstance(source.get('tenantCreativeImages'), dict) else {}
    placeholder_sources = (
        creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {},
        source.get('map_placeholders') if isinstance(source.get('map_placeholders'), dict) else {},
        request_images.get('map_placeholders') if isinstance(request_images.get('map_placeholders'), dict) else {},
    )
    # The persisted rows are the fallback for reopened presentations.  Keep only
    # the newest valid row for each image type/placeholder; without this guard an
    # older duplicate row could be visited later and overwrite the current map.
    placeholders = {}
    for values in placeholder_sources:
        placeholders.update({key: value for key, value in values.items() if key and value})
    persisted_file_records = []
    seen_persisted_types = set()
    seen_persisted_placeholders = set()
    for record in persisted_records:
        placeholder = record.get('placeholder')
        path = record.get('file_path')
        if placeholder and path and os.path.exists(path):
            image_type = record.get('image_type') or ''
            if image_type in seen_persisted_types or placeholder in seen_persisted_placeholders:
                continue
            try:
                rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            except ValueError:
                rel_path = 'uploads/maps/' + os.path.basename(path)
            seen_persisted_types.add(image_type)
            seen_persisted_placeholders.add(placeholder)
            persisted_file_records.append(record)
            placeholders[placeholder] = '/' + rel_path

    # During the same browser session, a map can be edited and approved after an
    # older Google row was stored.  The request carries that approved state and
    # its current URL, so it is authoritative for that map.  On a reopened
    # presentation maps_persisted/approvals come from the persisted project state
    # and agree with the DB row, preserving DB hydration as the fallback.
    requested_placeholders = request_images.get('map_placeholders')
    if isinstance(requested_placeholders, dict):
        for placeholder, path in requested_placeholders.items():
            if not path or not _request_map_is_approved(request_images, placeholder):
                continue
            # The browser may already have received the generation-only alias
            # below, where an editable sidecar points at the marked canonical
            # image.  Never let that alias overwrite the clean sidecar in the
            # project copy: the location editor renders its own labels over it.
            if placeholder.endswith('_EDITABLE##'):
                canonical = placeholder.replace('_EDITABLE##', '##')
                requested_canonical = requested_placeholders.get(canonical)
                if requested_canonical and str(path) == str(requested_canonical):
                    continue
            placeholders[placeholder] = path

    if placeholders and isinstance(source, dict):
        creative = source.get('tenantCreativeImages') if isinstance(source.get('tenantCreativeImages'), dict) else {}
        creative['map_placeholders'] = dict(placeholders)
        source['tenantCreativeImages'] = creative
    # Older plans or an over-helpful model may ask for the editable sidecar token.
    # A generated presentation must always receive the approved, marked image;
    # the sidecar is only for the interactive map editor. Keep this alias in the
    # request copy only; the project/browser copy above must retain the clean file.
    generation_placeholders = dict(placeholders)
    for placeholder, path in list(generation_placeholders.items()):
        if not placeholder.endswith('_EDITABLE##'):
            continue
        canonical = placeholder.replace('_EDITABLE##', '##')
        if generation_placeholders.get(canonical):
            generation_placeholders[placeholder] = generation_placeholders[canonical]
    if generation_placeholders:
        request_images['map_placeholders'] = generation_placeholders

    # These values keep marker-aware layout and location summaries consistent with
    # the exact map image that was persisted for the open presentation.
    for key in (
        'map_zooms', 'map_centers', 'map_landmarks', 'map_access_roads',
        'map_catchment_landmarks', 'map_landmark_items', 'map_highlight_site',
        'map_lat', 'map_lng', 'maps_persisted', 'map_approvals',
    ):
        if persisted_file_records and key in creative:
            request_images[key] = creative[key]
        elif key not in request_images and key in creative:
            request_images[key] = creative[key]
    return source, request_images


def _map_approval_key(value):
    """Return the logical map name for a canonical or editable placeholder."""
    key = str(value or '').strip()
    key = key.replace('##MAP_', '').replace('_EDITABLE##', '').replace('##', '')
    for suffix in ('_SATELLITE', '_ROADMAP'):
        if key.endswith(suffix):
            key = key[:-len(suffix)]
    return key.lower()


def _request_map_is_approved(request_images, placeholder):
    """Whether the caller is sending its current, user-approved map version."""
    if not isinstance(request_images, dict) or request_images.get('maps_persisted') is not True:
        return False
    approvals = request_images.get('map_approvals')
    if not isinstance(approvals, dict):
        return False
    value = approvals.get(_map_approval_key(placeholder))
    return value is True or (isinstance(value, str) and value.strip().lower() in {'true', '1', 'yes'})
