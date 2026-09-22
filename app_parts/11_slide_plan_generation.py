

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


@app.route('/api/geocode', methods=['POST'])
@require_auth
def api_geocode():
    """Geocode an address or Google Maps link to lat/lng."""
    data = request.json or {}
    address = data.get('address', '').strip()
    maps_link = data.get('maps_link', '').strip()

    if not address and not maps_link:
        return jsonify({'error': 'رابط Google Maps مطلوب لتحديد موقع المشروع'}), 400

    query = maps_link or address
    if not query.startswith('http'):
        return jsonify({'error': 'موقع المشروع يجب أن يكون رابط Google Maps'}), 400

    if query.startswith('http'):
        coords = maps_service.extract_coords_from_maps_link(query)
        if coords:
            print(f"[MAPS LINK] Extracted coords from link: {coords}")
            place = maps_service.reverse_geocode_location(
                coords['lat'], coords['lng'], tenant_id=g.tenant_id, language='ar',
                usage_ctx=maps_service.maps_usage_ctx('geocode', g.tenant_id, data=data)
            ) or {}
            names = market_study.extract_city_district(
                place.get('address_components') or [],
                place.get('formatted_address') or '',
            )
            return jsonify({
                'success': True,
                'lat': coords['lat'],
                'lng': coords['lng'],
                'formatted_address': place.get('formatted_address') or (
                    address if (address and not address.startswith('http')) else 'تم الاستخراج من رابط خرائط جوجل'
                ),
                'city': names.get('city') or '',
                'district': names.get('district') or '',
                'source': 'maps_link'
            })

    return jsonify({'success': False, 'error': 'رابط Google Maps غير صالح أو لا يحتوي على إحداثيات'})


@app.route('/api/debug-osm-polygon', methods=['GET'])
@require_auth
def api_debug_osm_polygon():
    try:
        lat = float(request.args.get('lat'))
        lng = float(request.args.get('lng'))
    except (TypeError, ValueError):
        return jsonify({'error': 'lat and lng are required'}), 400
    radius = int(request.args.get('radius', 400))
    maps_service._osm_polygon_cache.clear()
    coords = maps_service._fetch_osm_polygon(lat, lng, radius_m=radius)
    if not coords:
        return jsonify({'found': False, 'lat': lat, 'lng': lng, 'radius_m': radius})
    return jsonify({
        'found': True,
        'points': len(coords),
        'area_sqm': round(maps_service._approx_polygon_area_sqm(coords)),
        'coords': coords,
    })


@app.route('/api/nearby-landmarks', methods=['POST'])
@require_auth
def api_nearby_landmarks():
    """Get nearby landmarks for given coordinates."""
    data = request.json or {}
    lat = data.get('lat')
    lng = data.get('lng')
    radius = data.get('radius', 20000)
    if lat is None or lng is None:
        return jsonify({'error': 'lat and lng are required'}), 400
    result = maps_service.get_nearby_landmarks(float(lat), float(lng), int(radius), max_results=int(data.get('maxResults', 20)), include_all=True, usage_ctx=maps_service.maps_usage_ctx('places', g.tenant_id, data=data))
    status = 502 if result.get('error') and not result.get('success') else 200
    return jsonify(result), status


@app.route('/api/preview-map-data', methods=['POST'])
@require_auth
def api_preview_map_data():
    """Preview calculated landmarks, drive matrix times, distances, and catchment zones before generation."""
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))

    lat = maps_service._extract_coordinate(
        project_data.get('location_lat') or project_data.get('locationLat') or
        project_data.get('latitude') or project_data.get('lat')
    )
    lng = maps_service._extract_coordinate(
        project_data.get('location_lng') or project_data.get('locationLng') or
        project_data.get('longitude') or project_data.get('lng')
    )

    if lat is None or lng is None:
        address = project_data.get('location_address') or project_data.get('location', '')
        if address and not address.startswith('http'):
            geo = maps_service.geocode_address(address, tenant_id=g.tenant_id, usage_ctx=maps_service.maps_usage_ctx('geocode', g.tenant_id, data=data))
            if geo.get('success'):
                lat = geo['lat']
                lng = geo['lng']

    if lat is None or lng is None:
        return jsonify({'success': False, 'error': 'لم يتم العثور على إحداثيات للموقع'}), 400

    landmark_radius_m = 20000
    selected_landmarks = data.get('selectedLandmarks')
    custom_text = project_data.get('nearby_landmarks') or project_data.get('landmarks_text')
    landmarks = selected_landmarks if isinstance(selected_landmarks, list) else (
        maps_service._parse_landmarks_text(custom_text) if isinstance(custom_text, str) else (custom_text or [])
    )
    landmarks_error = None
    landmarks_warning = None

    if not landmarks:
        places = maps_service.get_nearby_landmarks(lat, lng, radius=landmark_radius_m, max_results=20, include_all=True, usage_ctx=maps_service.maps_usage_ctx('places', g.tenant_id, data=data))
        if places.get('success'):
            landmarks = places['landmarks']
            if not landmarks:
                landmarks_warning = 'لم تُرجع Google Places أي معالم ضمن نطاق 20 كم من الموقع'
        else:
            landmarks_error = places.get('error') or 'تعذر جلب المعالم من Google Places'

    location_context = project_data.get('location_detail') or project_data.get('location_address') or project_data.get('location', '')
    for lm in landmarks:
        if lm.get('lat') is None or lm.get('lng') is None:
            query = f"{lm['name']}, {location_context}" if location_context else lm['name']
            geo = maps_service.geocode_address(query, tenant_id=g.tenant_id, usage_ctx=maps_service.maps_usage_ctx('geocode', g.tenant_id, data=data))
            if geo.get('success'):
                lm['lat'] = geo['lat']
                lm['lng'] = geo['lng']

    filtered_landmarks = []
    for lm in landmarks:
        if lm.get('lat') is None or lm.get('lng') is None:
            lm['location_status'] = 'unresolved'
            filtered_landmarks.append(lm)
            continue
        dist_m = maps_service._distance_meters(lat, lng, lm['lat'], lm['lng'])
        if dist_m < 50 or dist_m > landmark_radius_m:
            continue
        lm['distance_meters'] = round(dist_m)
        filtered_landmarks.append(lm)

    landmarks = sorted(filtered_landmarks, key=lambda item: item.get('distance_meters', float('inf')))

    geocoded = [lm for lm in landmarks if lm.get('lat') is not None and lm.get('lng') is not None]
    matrix = []
    if data.get('calculateDriving') and geocoded:
        matrix = maps_service.get_drive_matrix((lat, lng), geocoded, usage_ctx=maps_service.maps_usage_ctx('matrix', g.tenant_id, data=data))
        for i, lm in enumerate(geocoded):
            if i < len(matrix) and matrix[i]:
                entry = matrix[i]
                lm['duration_minutes'] = entry.get('duration_min')
                lm['distance_km'] = entry.get('distance_km')
                lm['distance_text'] = f"{entry.get('distance_km')} كم" if entry.get('distance_km') else None

    catchment_text = project_data.get('catchment_areas') or project_data.get('catchment_zones')
    zones = maps_service._parse_catchment_zones(catchment_text) if isinstance(catchment_text, str) else catchment_text

    if landmarks_error:
        return jsonify({
            'success': False,
            'error': landmarks_error,
            'error_code': 'NEARBY_LANDMARKS_UNAVAILABLE',
            'lat': lat,
            'lng': lng,
            'landmarks': [],
        }), 503

    return jsonify({
        'success': True,
        'lat': lat,
        'lng': lng,
        'landmarks': landmarks,
        'landmarks_matrix': matrix or landmarks,
        'catchment_zones': zones,
        'warning': landmarks_warning,
    })


def _map_image_point_to_coords(x, y, width, height, center_lat, center_lng, zoom, scale=2):
    """Convert normalized image coordinates to WGS84 using Web Mercator."""
    world = 256 * (2 ** zoom) * scale
    center_x = (center_lng + 180.0) / 360.0 * world
    center_lat_rad = math.radians(center_lat)
    center_y = (1.0 - math.log(math.tan(math.pi / 4.0 + center_lat_rad / 2.0)) / math.pi) / 2.0 * world
    target_x = center_x + (float(x) - 0.5) * width
    target_y = center_y + (float(y) - 0.5) * height
    lng = target_x / world * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * target_y / world))))
    return lat, lng


def _estimate_site_polygon_from_satellite(image_path, center_lat, center_lng, zoom, usage_ctx=None):
    """Ask the vision model for a conservative building-only polygon estimate."""
    vision_ctx = usage_ctx or _usage_ctx('site')
    if _tenant_key_gate(vision_ctx) is not None:
        return None
    if not _has_any_openrouter_key(vision_ctx) or not image_path or not os.path.isfile(image_path):
        return None
    site_attempt_id = _begin_ai_attempt_record(vision_ctx, GEMINI_TEXT_MODEL)
    try:
        from reference_analyzer import encode_image_to_base64
        from PIL import Image
        image_uri = encode_image_to_base64(image_path)
        prompt = (
            'Analyze this satellite map image. The target site is at the exact image center. '
            'Identify only the footprint of the building or compound directly at the center; '
            'do not select roads, highways, interchanges, districts, empty land, airport areas, '
            'or any nearby polygon. Return JSON only: '
            '{"confidence":0.0,"points":[{"x":0.0,"y":0.0}]} where x and y are normalized '
            'image coordinates between 0 and 1. Return an empty points array if no building footprint '
            'can be identified with confidence >= 0.65.'
        )
        response = requests.post(
            f'{OPENROUTER_BASE}/chat/completions',
            headers=_openrouter_headers(vision_ctx, title='Real Estate Proposal Generator - Site Boundary'),
            json={
                'model': GEMINI_TEXT_MODEL,
                'messages': [{'role': 'user', 'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url', 'image_url': {'url': image_uri}},
                ]}],
                'modalities': ['text'],
                'max_tokens': 1200,
            },
            timeout=90,
        )
        payload = response.json()
        generation_id, vision_usage = _extract_openrouter_usage(payload)
        _settle_ai_attempt_record(
            site_attempt_id,
            'ok' if response.status_code < 400 and 'error' not in payload else 'error',
            vision_usage, generation_id)
        content = payload.get('choices', [{}])[0].get('message', {}).get('content', '')
        if isinstance(content, list):
            content = ' '.join(str(part.get('text', '')) if isinstance(part, dict) else str(part) for part in content)
        match = re.search(r'\{[\s\S]*\}', content or '')
        if not match:
            return None
        result = json.loads(match.group())
        confidence = float(result.get('confidence', 0) or 0)
        raw_points = result.get('points') or []
        if confidence < 0.65 or len(raw_points) < 3 or len(raw_points) > 40:
            return None
        with Image.open(image_path) as image:
            width, height = image.size
        normalized = []
        for point in raw_points:
            if not isinstance(point, dict):
                return None
            x, y = float(point.get('x')), float(point.get('y'))
            if not (0 <= x <= 1 and 0 <= y <= 1):
                return None
            normalized.append(_map_image_point_to_coords(x, y, width, height, center_lat, center_lng, zoom))
        if not maps_service._point_in_polygon(center_lat, center_lng, normalized):
            return None
        area = maps_service._approx_polygon_area_sqm(normalized)
        if area < 20 or area > 100000:
            return None
        return normalized
    except requests.exceptions.Timeout:
        print('[SITE BOUNDARY VISION] OpenRouter timeout')
        _settle_ai_attempt_record(site_attempt_id, 'error', {}, None)
        return None
    except requests.exceptions.ConnectionError as error:
        print(f'[SITE BOUNDARY VISION] {error}')
        _settle_ai_attempt_record(site_attempt_id, 'error', {}, None)
        return None
    except Exception as error:
        print(f'[SITE BOUNDARY VISION] {error}')
        try:
            _settle_ai_attempt_record(site_attempt_id, 'error', {}, None)
        except Exception:
            pass
        return None


def _collect_site_fields(project_data, tenant_id, lat, lng):
    """Gather site fields (landmarks, roads, population, polygon) from Google/BigQuery data.

    Does not generate map images.  Used by analyze-site and site-analysis so they
    share the same data sources.
    """

    def landmark_lines(items, matrix=None):
        matrix = matrix or []
        lines = []
        for index, item in enumerate(items or []):
            name = item.get('name') or item.get('displayName') or ''
            if not name:
                continue
            drive = matrix[index] if index < len(matrix) and isinstance(matrix[index], dict) else {}
            distance = drive.get('distance_text') or item.get('distance_text')
            duration = drive.get('duration_min') or item.get('duration_minutes')
            category = item.get('category')
            details = []
            if category:
                details.append(str(category))
            if distance:
                details.append(str(distance))
            if duration:
                details.append(f'{duration} دقيقة')
            lines.append(f"{name} - {' - '.join(details)}" if details else name)
        return '\n'.join(lines)

    def enrich_road_metrics(items):
        if not items or all(item.get('distance_text') and item.get('duration_minutes') for item in items):
            return
        matrix = maps_service.get_drive_matrix((lat, lng), items)
        for index, item in enumerate(items):
            if index >= len(matrix) or not isinstance(matrix[index], dict):
                continue
            entry = matrix[index]
            item['distance_text'] = entry.get('distance_text') or item.get('distance_text')
            item['distance_km'] = entry.get('distance_km') or item.get('distance_km')
            item['duration_min'] = entry.get('duration_min') or item.get('duration_min')
            item['duration_minutes'] = entry.get('duration_min') or item.get('duration_minutes')

    nearby = maps_service.get_nearby_landmarks(lat, lng, radius=20000, max_results=20, include_all=True)
    nearby_items = nearby.get('landmarks', []) if nearby.get('success') else []
    nearby_error = nearby.get('error') if not nearby.get('success') else None
    nearby_warning = 'لم تُرجع Google Places أي معالم ضمن نطاق 20 كم من الموقع' if nearby.get('success') and not nearby_items else None
    nearby_matrix = maps_service.get_drive_matrix((lat, lng), nearby_items) if nearby_items else []
    for index, item in enumerate(nearby_items):
        if index >= len(nearby_matrix) or not isinstance(nearby_matrix[index], dict):
            continue
        entry = nearby_matrix[index]
        item['distance_km'] = entry.get('distance_km') or item.get('distance_km')
        item['distance_text'] = entry.get('distance_text') or item.get('distance_text')
        item['duration_min'] = entry.get('duration_min') or item.get('duration_min')
        item['duration_minutes'] = entry.get('duration_min') or item.get('duration_minutes')

    curated_city = maps_service.detect_curated_city(lat, lng, tenant_id=tenant_id)
    city_error = None
    city_warning = None
    if curated_city:
        city_items = maps_service.get_curated_city_landmarks(lat=lat, lng=lng, city=curated_city, tenant_id=tenant_id)
    else:
        city = maps_service.get_nearby_landmarks(lat, lng, radius=5000, max_results=20, include_all=True)
        city_items = city.get('landmarks', []) if city.get('success') else []
        city_error = city.get('error') if not city.get('success') else None
        existing_city_names = {item.get('name', '').casefold() for item in city_items}
        city_items.extend(
            item for item in maps_service.get_nearest_category_landmarks(lat, lng, radius=20000, tenant_id=tenant_id)
            if item.get('name', '').casefold() not in existing_city_names
        )
    if not city_items and not city_error:
        city_warning = 'لم تُرجع Google Places أي معالم للمدينة ضمن النطاق المحدد'
    # One Google discovery per analysis: the main and secondary road lists are
    # split locally from the same probes instead of paying for a second
    # 8-probe discovery. Previously every analysis burned ~16 Roads plus
    # ~16 Directions calls here alone.
    all_roads = maps_service.discover_nearby_roads(lat, lng, tenant_id=tenant_id, max_results=10)
    enrich_road_metrics(all_roads)
    roads = all_roads[:6]

    polygon = None
    raw_polygon = project_data.get('location_polygon')
    if isinstance(raw_polygon, str):
        try:
            polygon = [
                (float(lat_value.strip()), float(lng_value.strip()))
                for point in raw_polygon.split(';') if ',' in point
                for lat_value, lng_value in [point.split(',', 1)]
            ]
            if len(polygon) < 3:
                polygon = None
        except (TypeError, ValueError):
            polygon = None
    if not polygon:
        polygon = maps_service._fetch_osm_polygon(lat, lng, radius_m=180)

    population = population_service.get_population_density(lat, lng)
    location_details = maps_service.reverse_geocode_location(lat, lng, tenant_id=tenant_id, language='en')
    arabic_location = maps_service.reverse_geocode_location(lat, lng, tenant_id=tenant_id, language='ar') or {}
    place_names = market_study.extract_city_district(
        arabic_location.get('address_components') or location_details.get('address_components') or [],
        arabic_location.get('formatted_address') or location_details.get('formatted_address') or '',
    )
    fields = {
        'location_lat': lat,
        'location_detail': arabic_location.get('formatted_address') or location_details.get('formatted_address', ''),
        'location_lng': lng,
        'nearby_landmarks': landmark_lines(nearby_items, nearby_matrix),
        'city_landmarks': landmark_lines(city_items),
    }
    if place_names.get('city') and not str(project_data.get('city') or '').strip():
        fields['city'] = place_names['city']
    if place_names.get('district') and not str(project_data.get('district') or '').strip():
        fields['district'] = place_names['district']
    if population.get('available'):
        fields['population_density'] = f"{population['value']} {population.get('unit', 'نسمة/كم²')}"
        fields['population_density_source'] = population.get('source')
    road_names = []
    for road in roads:
        name = road.get('name')
        if name and name not in road_names:
            road_names.append(name)
    road_names = maps_service.normalize_access_road_names(road_names)
    if road_names:
        fields['main_roads'] = '\n'.join(road_names)

    city_matrix = maps_service.get_drive_matrix((lat, lng), city_items) if city_items else []
    for index, item in enumerate(city_items):
        if index < len(city_matrix) and isinstance(city_matrix[index], dict):
            if city_matrix[index].get('duration_min') is not None:
                item['duration_minutes'] = city_matrix[index].get('duration_min')
            if city_matrix[index].get('distance_text'):
                item['distance_text'] = city_matrix[index].get('distance_text')
    fields['city_landmarks'] = landmark_lines(city_items, city_matrix)
    catchment_lines = []
    for item in city_items:
        name = item.get('name')
        duration = item.get('duration_minutes')
        if not name:
            continue
        parts = [name]
        if item.get('category'):
            parts.append(str(item['category']))
        if item.get('distance_text'):
            parts.append(str(item['distance_text']))
        if duration is not None:
            parts.append(f'{duration} دقائق')
        catchment_lines.append(' — '.join(parts))
    if catchment_lines:
        fields['catchment_areas'] = '\n'.join(catchment_lines)

    if polygon:
        fields['location_polygon'] = ';'.join(f'{point[0]:.6f},{point[1]:.6f}' for point in polygon)

    diagnostics = {
        'nearby_landmarks_error': nearby_error,
        'nearby_landmarks_warning': nearby_warning,
        'city_landmarks_error': city_error,
        'city_landmarks_warning': city_warning,
    }
    return fields, nearby_items, nearby_matrix, city_items, city_matrix, roads, polygon, diagnostics


@app.route('/api/analyze-site', methods=['POST'])
@require_permission('create_presentation')
def api_analyze_site():
    """Resolve and enrich site data without generating map images."""
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    _billing_guard = _require_billing_balance('analyze_site')
    if _billing_guard is not None:
        return _billing_guard
    if data.get('generateMaps') is True:
        return jsonify({
            'success': False,
            'error': 'توليد الخرائط متاح لكل خريطة على حدة بعد اعتماد تحليل الموقع',
            'error_code': 'INDIVIDUAL_MAP_GENERATION_REQUIRED',
        }), 400
    address = project_data.get('location_address') or project_data.get('location') or ''
    link = address if isinstance(address, str) and address.startswith('http') else (
        project_data.get('location_maps_link') or project_data.get('maps_link')
    )
    if not isinstance(link, str) or not link.startswith('http'):
        return jsonify({'success': False, 'error': 'موقع المشروع يجب أن يكون رابط Google Maps'}), 400
    coords = maps_service.extract_coords_from_maps_link(link)
    if coords:
        lat, lng = coords['lat'], coords['lng']
        source = 'maps_link'
    elif link:
        return jsonify({'success': False, 'error': 'تعذر استخراج الإحداثيات من رابط Google Maps'}), 400
    else:
        lat = maps_service._extract_coordinate(
            project_data.get('location_lat') or project_data.get('locationLat') or
            project_data.get('latitude') or project_data.get('lat')
        )
        lng = maps_service._extract_coordinate(
            project_data.get('location_lng') or project_data.get('locationLng') or
            project_data.get('longitude') or project_data.get('lng')
        )
        source = 'existing_coordinates'
        if (lat is None or lng is None) and address and not str(address).startswith('http'):
            geo = maps_service.geocode_address(address, tenant_id=g.tenant_id, usage_ctx=maps_service.maps_usage_ctx('site', g.tenant_id, data=data))
            if geo.get('success'):
                lat, lng = geo['lat'], geo['lng']
                source = 'geocoding'

    if lat is None or lng is None:
        return jsonify({'success': False, 'error': 'أدخل رابط Google Maps أو عنوان الموقع أولاً'}), 400

    site_maps_ctx = maps_service.maps_usage_ctx('site', g.tenant_id, data=data)
    with maps_service.maps_usage_scope(site_maps_ctx):
        fields, nearby_items, nearby_matrix, city_items, city_matrix, roads, polygon, diagnostics = _collect_site_fields(
            project_data, g.tenant_id, lat, lng
        )
    fields['location_polygon_source'] = (
        'manual' if project_data.get('location_polygon_source') == 'manual'
        # 'cleared' is the user switching the highlight off; it must survive a re-analysis.
        else 'cleared' if project_data.get('location_polygon_source') == 'cleared'
        else 'auto' if fields.get('location_polygon')
        else 'none'
    )

    return jsonify({
        'success': True,
        'fields': fields,
        'mapPlaceholders': {},
        'mapsDeferred': True,
        'landmarks': nearby_items,
        'landmarksMatrix': nearby_matrix,
        'cityLandmarks': city_items,
        'roads': roads,
        'zooms': {},
        'lat': lat,
        'lng': lng,
        'source': source,
        'boundary': {
            'status': 'verified_building' if polygon else 'needs_review',
            'estimated': False,
            'manual_edit_available': True,
        },
        'warning': None,
        'landmarksWarning': diagnostics.get('nearby_landmarks_error') or diagnostics.get('nearby_landmarks_warning'),
        'cityLandmarksWarning': diagnostics.get('city_landmarks_error') or diagnostics.get('city_landmarks_warning'),
    })


@app.route('/api/site-analysis', methods=['POST'])
@require_permission('create_presentation')
def api_site_analysis():
    data = request.json or {}
    _billing_guard = _require_billing_balance('site_analysis')
    if _billing_guard is not None:
        return _billing_guard
    raw_project_data = clean_project_data(data.get('projectData', {}))
    analysis_keys = (
        'project_name', 'project_type', 'project_subtype', 'project_idea', 'description', 'project_description',
        'project_goal', 'project_stage', 'initial_features', 'initial_strengths',
        'project_features', 'investment_opportunities', 'target_audience', 'location_address',
        'location_maps_link', 'maps_link', 'location_detail', 'location_lat', 'location_lng',
        'city', 'district', 'main_roads', 'nearby_landmarks', 'nearby_landmarks_data',
        'city_landmarks', 'catchment_areas', 'population_density', 'population_density_source',
        'location_polygon'
    )
    project_data = {
        key: raw_project_data.get(key)
        for key in analysis_keys
        if raw_project_data.get(key) not in (None, '', [], {})
    }
    if not project_data.get('location_lat') or not project_data.get('location_lng'):
        return jsonify({'success': False, 'error': 'بيانات الموقع والإحداثيات مطلوبة أولًا'}), 400

    lat = maps_service._extract_coordinate(project_data.get('location_lat'))
    lng = maps_service._extract_coordinate(project_data.get('location_lng'))
    if lat is None or lng is None:
        return jsonify({'success': False, 'error': 'بيانات الموقع والإحداثيات مطلوبة أولًا'}), 400

    enriched_fields = {}
    enrichment_diagnostics = {}
    needs_enrichment = any(
        project_data.get(key) in (None, '', [], {})
        for key in (
            'location_detail', 'main_roads', 'nearby_landmarks', 'nearby_landmarks_data',
            'city_landmarks', 'catchment_areas', 'population_density',
            'location_polygon',
        )
    )
    filled_fields = {}
    if needs_enrichment:
        try:
            # Same metering scope as analyze-site: every Google call inside
            # _collect_site_fields bills to this tenant/draft instead of
            # landing as an unbillable tenant_id=NULL row.
            site_maps_ctx = maps_service.maps_usage_ctx('site', g.tenant_id, data=data)
            with maps_service.maps_usage_scope(site_maps_ctx):
                enrichment_result = _collect_site_fields(raw_project_data, g.tenant_id, lat, lng)
            enriched_fields, nearby_items, *_rest, enrichment_diagnostics = enrichment_result
            enrichment_diagnostics = enrichment_diagnostics or {}
            if not project_data.get('nearby_landmarks_data') and nearby_items:
                enriched_fields['nearby_landmarks_data'] = nearby_items
        except Exception as error:
            print(f'[SITE DATA ENRICHMENT ERROR] {error}')
            enriched_fields = {}

    for key in analysis_keys:
        if enriched_fields.get(key) not in (None, '', [], {}) and project_data.get(key) in (None, '', [], {}):
            project_data[key] = enriched_fields[key]
            filled_fields[key] = enriched_fields[key]

    prompt = f"""اكتب تحليلًا عربيًا احترافيًا ومفصلًا لموقع مشروع عقاري اعتمادًا على البيانات التالية فقط.

المطلوب:
- اكتب تحليلًا عربيًا مسترسلًا في فقرات مترابطة، ولا تختصره إلى ملخص سريع أو عبارات عامة.
- غطِّ جميع الفئات التالية الموجودة في البيانات ولا تتخطى أي فئة فيها بيانات.
- يجب أن يتضمن التحليل إشارة مختصرة إلى كل ما يلي متاح منه، بالترتيب التالي قدر الإمكان:
  1. نوع المشروع وفكرته ووصفه والهدف منه ومرحلته الحالية والجمهور المستهدف.
  2. المميزات الأولية ونقاط القوة وفرص الاستثمار المناسبة للمشروع.
  3. طبيعة الموقع وموقعه الاستراتيجي والعنوان التفصيلي والإحداثيات.
  4. الكثافة السكانية ومصدرها إن وجدت.
  5. الطرق الرئيسية وطبيعة الوصول.
  6. المعالم القريبة ومعالم المدينة، مع ذكر المسافات وأوقات القيادة كدليل لا كموضوع رئيسي.
  7. نطاق التأثير ومناطق الالتقاط إن وجدت.
- اربط كل فئة بصلاحية الموقع لنوع المشروع وفكرته وهدفه ومرحلته والجمهور المستهدف ومميزات المشروع وفرصه.
- اشرح العلاقة والاستنتاجات بالتفصيل دون تكرار نفس المعلومة.
- لا تخترع أي معلومة غير موجودة في البيانات.
- إذا كانت معلومة غير متوفرة، لا تذكرها أبدًا بدلًا من اختلاقها.
- لا تستخدم عناوين أو نقاط تعداد في النص النهائي؛ أعد تحليلًا عربيًا سلسًا جاهزًا للعرض.

بيانات المشروع والموقع:
{json.dumps(project_data, ensure_ascii=False, indent=2)}"""
    system_prompt = 'أنت محلل مواقع عقارية دقيق. أخرج تحليلًا عربيًا سلسًا يغطي كل فئة متاحة من البيانات دون تخطي أي منها، ودون اختلاق معلومات غير موجودة.'
    training_context = db.get_training_context(g.tenant_id, surface='content') or ''
    if training_context:
        system_prompt += f"\n\n## بيانات خاصة بالشركة\n{training_context}"
    try:
        try:
            response = call_zai_chat(
                system_prompt, prompt, max_tokens=SITE_ANALYSIS_MAX_TOKENS,
                reasoning_effort='max', usage_ctx=_usage_ctx('site', data))
            analysis = extract_chat_content(response, 'SITE-ANALYSIS').strip()
        except Exception as primary_error:
            if not _has_any_openrouter_key(_usage_ctx('site', data)):
                raise
            print(f'[SITE ANALYSIS PRIMARY ERROR] {primary_error}. Trying direct OpenRouter fallback...')
            fallback = call_openrouter_chat(
                system_prompt,
                prompt,
                temperature=None,
                max_tokens=SITE_ANALYSIS_MAX_TOKENS,
                model=LUNA_TEXT_MODEL,
                usage_ctx=_usage_ctx('site', data)
            )
            analysis = extract_chat_content(fallback, 'SITE-ANALYSIS-FALLBACK').strip()
        warnings = [value for value in (
            enrichment_diagnostics.get('nearby_landmarks_error'),
            enrichment_diagnostics.get('nearby_landmarks_warning'),
            enrichment_diagnostics.get('city_landmarks_error'),
            enrichment_diagnostics.get('city_landmarks_warning'),
        ) if value]
        return jsonify({
            'success': True,
            'analysis': analysis,
            'fields': filled_fields,
            'warnings': warnings,
        })
    except Exception as error:
        print(f'[SITE ANALYSIS AI ERROR] {error}')
        return jsonify({
            'success': False,
            'error': 'تعذر تشغيل خدمة تحليل AI للموقع: ' + str(error),
            'error_code': 'SITE_ANALYSIS_AI_UNAVAILABLE'
        }), 503


@app.route('/api/generate-map-image', methods=['POST'])
@require_permission('generate_maps')
def api_generate_single_map_image():
    data = request.json or {}
    _billing_guard = _require_billing_balance('map_image')
    if _billing_guard is not None:
        return _billing_guard
    map_type = str(data.get('mapType') or '').strip().lower()
    if map_type not in {'overview', 'landmarks', 'access', 'catchment'}:
        return jsonify({'success': False, 'error': 'نوع خريطة غير صالح'}), 400
    project_data = clean_project_data(data.get('projectData', {})) or {}
    overlay_only = data.get('overlayOnly') is True and map_type in {'overview', 'access', 'catchment', 'landmarks'}
    presentation_id = data.get('presentationId')
    draft_id = project_data.get('draftId') or project_data.get('draft_id')
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None)
    if not effective_id:
        return jsonify({'success': False, 'error': 'معرّف العرض أو المسودة مطلوب'}), 400
    # ISS-025: workflow approvals are read from the stored project, never the
    # request payload — a flag the caller types in is not the ceremony.
    stored_project = {}
    presentation = None
    if presentation_id:
        presentation = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
        if not presentation or not _presentation_in_scope(presentation):
            return jsonify({'error': 'Presentation not found'}), 404
        try:
            stored_project = json.loads(presentation.get('project_data') or '{}')
        except (TypeError, ValueError):
            stored_project = {}
    elif draft_id:
        stored_draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
        if stored_draft and not db.user_may_access_draft(g.user_id, stored_draft):
            return jsonify({'success': False, 'error': 'المشروع غير موجود'}), 404
        stored_project = (stored_draft or {}).get('draft_data') or {}
    if not isinstance(stored_project, dict):
        stored_project = {}
    stored_creative = stored_project.get('tenantCreativeImages') \
        if isinstance(stored_project.get('tenantCreativeImages'), dict) else {}
    stored_map_approvals = stored_creative.get('map_approvals') \
        if isinstance(stored_creative.get('map_approvals'), dict) else {}
    if not overlay_only and stored_project.get('location_analysis_approved') not in (True, 'true', 1):
        return jsonify({
            'success': False,
            'error': 'يجب اعتماد تحليل الموقع قبل إنشاء الخريطة',
            'error_code': 'LOCATION_ANALYSIS_NOT_APPROVED',
        }), 400
    if not overlay_only and map_type in {'landmarks', 'access', 'catchment'} \
            and stored_map_approvals.get('overview') is not True:
        return jsonify({
            'success': False,
            'error': 'يجب اعتماد خريطة الموقع العامة قبل إنشاء هذه الخريطة',
            'error_code': 'OVERVIEW_MAP_NOT_APPROVED',
        }), 400
    if stored_map_approvals.get(map_type) is True:
        return jsonify({
            'success': False,
            'error': 'يجب إلغاء اعتماد الخريطة قبل إعادة توليدها',
            'error_code': 'MAP_ALREADY_APPROVED',
        }), 400
    highlight_site = data.get('highlightSite', True) is not False
    expected_revision = None
    if presentation:
        try:
            expected_revision = _expected_presentation_revision(data, presentation)
            # Freeze a legacy baseline before a map provider can overwrite its files.
            checkpoint = _commit_presentation_state(
                g.tenant_id, presentation_id, expected_revision=expected_revision,
                action='حفظ حالة العرض قبل تعديل الخريطة', source='system')
            expected_revision = checkpoint['revision']
            presentation = checkpoint['presentation']
        except (LookupError, ValueError) as error:
            return jsonify({'error': str(error)}), 400
    if data.get('overlayOnly') is True and map_type == 'overview':
        result = maps_service.recompose_overview_map(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
            highlight_site=highlight_site,
        )
    elif data.get('overlayOnly') is True and map_type == 'access':
        result = maps_service.recompose_access_map(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
        )
    elif data.get('overlayOnly') is True and map_type == 'catchment':
        result = maps_service.recompose_catchment_map(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
        )
    elif data.get('overlayOnly') is True and map_type == 'landmarks':
        result = maps_service.recompose_landmarks_map(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
        )
    else:
        image_types = [map_type, f'{map_type}_satellite', f'{map_type}_roadmap']
        if map_type in {'overview', 'access', 'catchment', 'landmarks'}:
            image_types.extend([
                f'{map_type}_editable', f'{map_type}_satellite_editable', f'{map_type}_roadmap_editable'
            ])
        for image_type in image_types:
            db.delete_map_images(g.tenant_id, presentation_id=effective_id, image_type=image_type)
        project_data['enabled_maps'] = [map_type]
        project_data['refresh_maps'] = True
        if data.get('regenSeed') is not None:
            project_data['regen_seed'] = data.get('regenSeed')
        branding = db.get_branding(g.tenant_id) or {}
        result = maps_service.generate_all_map_images(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
            force=False,
            branding=branding,
            highlight_site=highlight_site,
            usage_flow=map_type,
        )
    if result.get('error'):
        return jsonify({'success': False, 'error': result['error']}), 400
    placeholders = {}
    for placeholder, path in result.get('placeholders', {}).items():
        if path and os.path.exists(path):
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            placeholders[placeholder] = '/' + rel_path
    map_labels = {'overview': 'الموقع العام', 'access': 'الوصول', 'catchment': 'نطاق الخدمة', 'landmarks': 'المعالم'}
    revision_result = None
    if presentation_id:
        state = _presentation_state(presentation)
        old_placeholders = dict(state['projectData'].get('map_placeholders') or {})
        old_creative = state['projectData'].get('tenantCreativeImages') or {}
        if isinstance(old_creative, dict):
            old_placeholders.update(old_creative.get('map_placeholders') or {})
        updated_project = {**state['projectData'], **project_data}
        updated_project['map_placeholders'] = {**old_placeholders, **placeholders}
        updated_project['tenantCreativeImages'] = {
            **(old_creative if isinstance(old_creative, dict) else {}),
            'map_placeholders': updated_project['map_placeholders'],
        }
        slides = state['slidesData']
        for slide in slides:
            if isinstance(slide, dict) and isinstance(slide.get('html'), str):
                for token, url in placeholders.items():
                    old_url = old_placeholders.get(token)
                    if isinstance(old_url, str) and old_url:
                        slide['html'] = slide['html'].replace(old_url, url)
                    slide['html'] = slide['html'].replace(token, url)
        try:
            revision_result = _commit_presentation_state(
                g.tenant_id, presentation_id, project_data=updated_project, slides_data=slides,
                expected_revision=expected_revision, action='تعديل خريطة' if overlay_only else 'توليد خريطة',
                details=[f'خريطة {map_labels.get(map_type, map_type)}'], source='manual')
        except (LookupError, ValueError) as error:
            return jsonify({'error': str(error)}), 400
    elif draft_id:
        _record_change('draft', draft_id, 'توليد خريطة',
                       [f'وُلّدت خريطة {map_labels.get(map_type, map_type)}'])
    return jsonify({
        **(_presentation_revision_response(revision_result) if revision_result else {}),
        'success': True,
        'mapType': map_type,
        'placeholders': placeholders,
        'landmarks': result.get('landmarks', []),
        'landmarks_matrix': result.get('landmarks_matrix', []),
        'zooms': result.get('zooms', {}),
        'centers': result.get('centers', {}),
        'sitePolygon': result.get('site_polygon', []),
        'accessRoads': result.get('access_roads', []),
        'catchmentLandmarks': result.get('catchment_landmarks', []),
        'landmarkMapItems': result.get('landmark_map_items', []),
    })


@app.route('/api/generate-map-images', methods=['POST'])
@require_auth
def api_generate_map_images():
    """Reject the retired bulk path so maps can only be generated individually."""
    return jsonify({
        'success': False,
        'error': 'توليد الخرائط متاح لكل خريطة على حدة',
        'error_code': 'INDIVIDUAL_MAP_GENERATION_REQUIRED',
    }), 400


@app.route('/api/presentations/<pres_id>/regenerate-maps', methods=['POST'])
@require_permission('create_presentation')
def api_regenerate_presentation_maps(pres_id):
    """Reject the retired saved-presentation bulk regeneration path."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404

    return jsonify({
        'success': False,
        'error': 'إعادة توليد الخرائط متاحة لكل خريطة على حدة',
        'error_code': 'INDIVIDUAL_MAP_GENERATION_REQUIRED',
    }), 400


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


@app.route('/api/presentations', methods=['GET'])
@require_permission('view_presentations')
def api_get_presentations():
    """List tenant presentations with optional project and archive filters."""
    try:
        limit = int(request.args.get('limit', 200))
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit and offset must be integers'}), 400
    accessible = db.user_accessible_draft_ids(g.user_id, g.tenant_id)
    presentations = db.get_presentations(
        g.tenant_id,
        draft_id=(request.args.get('draftId') or '').strip() or None,
        search=(request.args.get('search') or '').strip(),
        status=(request.args.get('status') or '').strip(),
        date_from=(request.args.get('from') or '').strip(),
        date_to=(request.args.get('to') or '').strip(),
        limit=limit,
        offset=offset,
        accessible_draft_ids=accessible,
    )
    total = db.count_presentations(
        g.tenant_id,
        draft_id=(request.args.get('draftId') or '').strip() or None,
        search=(request.args.get('search') or '').strip(),
        status=(request.args.get('status') or '').strip(),
        date_from=(request.args.get('from') or '').strip(),
        date_to=(request.args.get('to') or '').strip(),
        accessible_draft_ids=accessible,
    )
    result = []
    for p in presentations:
        result.append({
            'id': p['id'],
            'title': p['title'],
            'draftId': p.get('draft_id'),
            'revision': int(p.get('revision') or 0),
            'presentationScope': p.get('presentation_scope'),
            'slideCount': p.get('slide_count', 0),
            'status': p.get('status', 'draft'),
            'createdAt': p.get('created_at'),
            'updatedAt': p.get('updated_at'),
        })
    return jsonify({'success': True, 'presentations': result, 'total': total})


def _presentation_has_workflow_history(pres_id):
    """True when the presentation carries approvals, exports or downloads."""
    conn = db.get_db()
    try:
        for table in ('final_file_approvals', 'exports', 'presentation_downloads'):
            if conn.execute(
                    f'SELECT 1 FROM {table} WHERE tenant_id = ? AND presentation_id = ? LIMIT 1',
                    (g.tenant_id, pres_id)).fetchone():
                return True
        return False
    except Exception:
        return True


@app.route('/api/presentations/<pres_id>', methods=['DELETE'])
@require_permission('create_presentation')
def api_delete_presentation(pres_id):
    """Delete is cleanup for never-processed presentations only — admin-gated,
    and refused once the file carries workflow history (t18)."""
    presentation = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not presentation or not _presentation_in_scope(presentation):
        return jsonify({'error': 'Presentation not found'}), 404
    if not _omran_actor_is_admin():
        return jsonify({'error': 'الحذف النهائي يتطلب صلاحية مدير الشركة — أو استخدم الأرشفة',
                        'error_code': 'admin_required'}), 403
    if _presentation_has_workflow_history(pres_id):
        return jsonify({'error': 'لهذا العرض مسار اعتماد محفوظ — استخدم الأرشفة بدل الحذف',
                        'error_code': 'archive_required'}), 409
    _record_change('presentation', pres_id, 'حذف العرض',
                   [f'حُذف العرض «{presentation.get("title") or "بدون عنوان"}»'])
    if not db.delete_presentation(pres_id, g.tenant_id):
        return jsonify({'error': 'Presentation not found'}), 404
    return jsonify({'success': True})


def _presentation_state(pres):
    """Serialize stored state without merging mutable draft assets into a revision."""
    state = dict(pres)
    for stored, public, default in [('project_data', 'projectData', {}), ('slides_data', 'slidesData', [])]:
        value = state.get(stored)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                value = default
        state[public] = value if isinstance(value, type(default)) else default
    state['slideCount'] = len(state['slidesData'])
    state['draftId'] = state.get('draft_id')
    state['revision'] = int(state.get('revision') or 0)
    return state


def _presentation_revision_response(result):
    return {
        'success': True, 'presentationId': result['presentation_id'],
        'revision': result['revision'], 'versionId': result.get('version_id'),
        'changed': result.get('changed', True),
        'presentation': _presentation_state(result['presentation']),
    }


def _expected_presentation_revision(data, pres):
    expected = data.get('expectedRevision', int((pres or {}).get('revision') or 0))
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise ValueError('expectedRevision must be a non-negative integer')
    return expected


@app.errorhandler(db.PresentationRevisionConflict)
def _presentation_conflict(error):
    return jsonify({
        'success': False, 'error': 'تغير العرض منذ فتحه؛ لم تُحفظ هذه التغييرات',
        'error_code': 'PRESENTATION_REVISION_CONFLICT',
        'expectedRevision': error.expected_revision, 'currentRevision': error.current_revision,
    }), 409


@app.errorhandler(presentation_assets.PresentationAssetError)
def _presentation_asset_error(error):
    return jsonify({
        'success': False, 'error': 'وسائط العرض غير صالحة أو غير مصرح بها؛ لم تُحفظ التغييرات',
        'error_code': 'PRESENTATION_ASSET_REJECTED',
    }), 422


def _presentation_provenance_serializer():
    from itsdangerous import URLSafeTimedSerializer
    from auth import JWT_SECRET
    return URLSafeTimedSerializer(JWT_SECRET, salt='presentation-ai-provenance-v1')


def _presentation_slides_digest(slides):
    import hashlib
    return hashlib.sha256(json.dumps(slides, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def _issue_presentation_provenance(slides, presentation_id, revision, details):
    return {'token': _presentation_provenance_serializer().dumps({
        'tenant': g.tenant_id, 'actor': g.user_id, 'presentation': presentation_id,
        'revision': revision, 'slides': _presentation_slides_digest(slides),
        'details': details,
    })}


def _verified_presentation_provenance(data, presentation_id, revision):
    """A client-supplied source or actor is not evidence of an AI edit."""
    from itsdangerous import BadData
    provenance = data.get('provenance')
    if data.get('changeSource') != 'ai' or not isinstance(provenance, dict):
        return 'manual', []
    try:
        receipt = _presentation_provenance_serializer().loads(provenance.get('token', ''), max_age=7 * 86400)
        if (receipt.get('tenant') == g.tenant_id and receipt.get('actor') == g.user_id
                and receipt.get('presentation') == presentation_id
                and receipt.get('revision') == revision):
            # The receipt proves an AI operation in this unsaved workspace, not that
            # every final byte was AI-authored. Manual edits and fitting may follow it.
            details = list(receipt.get('details') or [])
            details.insert(0, 'حفظ بمساعدة الذكاء الاصطناعي؛ قد يتضمن تعديلات يدوية')
            return 'ai', details
    except (BadData, TypeError, ValueError):
        pass
    return 'manual', []


def _freeze_presentation_project_metadata(value, freeze):
    # Private source documents are retained as metadata, never copied to public
    # revision assets. Rendered HTML still goes through the strict media freezer.
    if isinstance(value, dict):
        return {key: _freeze_presentation_project_metadata(item, freeze) for key, item in value.items()}
    if isinstance(value, list):
        return [_freeze_presentation_project_metadata(item, freeze) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(('{', '[')):
            try:
                decoded = json.loads(value)
            except (TypeError, ValueError):
                pass
            else:
                return json.dumps(_freeze_presentation_project_metadata(decoded, freeze), ensure_ascii=False)
        from urllib.parse import urlsplit
        path = urlsplit(text).path if '<' not in text and '\n' not in text else ''
        normalized_path = '/' + path.lstrip('/')
        if (normalized_path.startswith(('/api/project-files/', '/uploads/project-documents/'))
                or '/project-documents/' in normalized_path
                or re.search(r'\.(?:pdf|docx?|xlsx?|csv|txt)$', normalized_path, re.I)):
            return value
    return freeze(value)


def _commit_presentation_state(tenant_id, presentation_id=None, **kwargs):
    """All application content writes use the transactional version/history authority."""
    from presentation_assets import freeze_presentation_assets
    root = os.path.dirname(__file__)
    authorized = {}
    for row in db.get_map_images(tenant_id):
        path = row.get('file_path')
        if path:
            full_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(root, path))
            try:
                relative = '/' + os.path.relpath(full_path, root).replace('\\', '/')
            except ValueError:
                continue
            if relative.startswith('/uploads/maps/') and os.path.isfile(full_path):
                authorized[relative] = full_path
    for kind, path in [('logo', _tenant_logo_storage_path(tenant_id)),
                       ('watermark', _tenant_watermark_storage_path(tenant_id))]:
        if kind == 'logo' and not path:
            path = os.path.join(root, 'assets', 'logo.png')
        if path and os.path.isfile(path):
            authorized[f'/tenant-assets/{tenant_id}/{kind}'] = path
    for pf in db.get_project_files(tenant_id):
        storage_path = pf.get('storage_path')
        if storage_path and os.path.isfile(storage_path) and (pf.get('mime_type') or '').startswith('image/'):
            file_id = pf.get('id')
            if file_id:
                authorized[f'/api/project-files/{file_id}'] = storage_path
            try:
                rel_pf = '/' + os.path.relpath(storage_path, root).replace('\\', '/')
                authorized[rel_pf] = storage_path
            except ValueError:
                pass
    def freeze(value):
        if isinstance(value, dict):
            return {key: freeze(item) for key, item in value.items()}
        if isinstance(value, list):
            return [freeze(item) for item in value]
        # Dangling historical uploads references (files absent from this
        # server) are preserved inside the freezer per-URL; every asset that
        # exists must pass its authorization and safety checks.
        return freeze_presentation_assets(
            value, tenant_id, authorized_paths=authorized,
            allowed_origin=request.host_url.rstrip('/'),
            uploads_root=UPLOADS_DIR, preserve_missing_uploads=True)
    def freeze_snapshot(state):
        frozen = dict(state)
        parsed = _presentation_state(state)
        for stored, public in [('project_data', 'projectData'), ('slides_data', 'slidesData')]:
            frozen[stored] = (_freeze_presentation_project_metadata(parsed[public], freeze)
                              if stored == 'project_data' else freeze(parsed[public]))
        return frozen
    kwargs['snapshot_transform'] = freeze_snapshot
    kwargs.setdefault('user_id', getattr(g, 'user_id', None))
    kwargs.setdefault('user_name', getattr(g, 'user_name', None) or 'مدير الشركة')
    return db.commit_presentation_revision(tenant_id, presentation_id, **kwargs)


def _presentation_save_failure(stage, exc):
    """Answer a presentation-save crash as JSON naming the failed stage.

    The workspace lives only in the browser until the save succeeds, so a bare
    HTML 500 hides both the cause and the fact that the edits are still open.
    The exception type (never its message or the payload) travels with the
    response; the full traceback stays in the server log.
    """
    app.logger.exception(
        '[PRESENTATION SAVE] Failed at stage %s: %s: %s', stage, type(exc).__name__, exc)
    detail = f'{type(exc).__name__}: {exc}'
    for private in (os.path.dirname(__file__), UPLOADS_DIR):
        if private:
            detail = detail.replace(str(private), '[app]')
    return jsonify({
        'success': False,
        'error': 'تعذر حفظ العرض بسبب خطأ داخلي؛ تعديلاتك ما زالت مفتوحة في المتصفح ولم تُفقد',
        'error_code': 'PRESENTATION_SAVE_FAILED',
        'stage': stage,
        'reason': type(exc).__name__,
        'detail': detail[:200],
    }), 500


@app.route('/api/presentations', methods=['POST'])
@require_permission('create_presentation')
def api_save_presentation():
    """Save a new presentation."""
    data = request.json or {}
    if not isinstance(data, dict) or not isinstance(data.get('projectData', {}), dict) or not isinstance(data.get('slidesData', []), list):
        return jsonify({'error': 'projectData must be an object and slidesData an array'}), 400
    try:
        expected_revision = _expected_presentation_revision(data, None)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    title = str(data.get('title') or 'عرض بدون عنوان').strip()
    incoming_project = data.get('projectData') or {}
    locked_status = _presentation_draft_lock(
        incoming_project.get('draftId') or incoming_project.get('draft_id'), data)
    if locked_status:
        return _draft_locked_response(locked_status)
    save_stage = 'normalize'
    try:
        project_data = normalize_presentation_assets(incoming_project, g.tenant_id)
        slides_data = normalize_presentation_assets(data.get('slidesData', []), g.tenant_id)
        branding = db.get_branding(g.tenant_id) or {}
        render_project_data = copy.deepcopy(project_data)
        _prepare_generation_logo_context(render_project_data, branding, g.tenant_id)
        save_stage = 'renumber'
        slides_data = slide_engine.renumber_presentation_slides(
            slides_data, branding=branding, project_data=render_project_data,
            tenant_id=g.tenant_id,
            creative_images=_presentation_creative_images(render_project_data, g.tenant_id),
        )
        slide_count = len(slides_data)

        scope = project_data.get('presentation_scope')
        draft_id = project_data.get('draftId') or project_data.get('draft_id')
        if draft_id:
            # ISS-014: a project-scoped member cannot hang a new presentation on
            # a draft outside their scope.
            linked_draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
            if linked_draft and not db.user_may_access_draft(g.user_id, linked_draft):
                return jsonify({'error': 'Draft not found'}), 404
        creation_key = None
        if draft_id and isinstance(scope, str) and (scope == 'full' or re.fullmatch(r'(?:section|copy):[A-Za-z0-9_-]+', scope)):
            creation_key = json.dumps([str(draft_id), scope], separators=(',', ':'))
        source, provenance_details = _verified_presentation_provenance(data, None, 0)
        save_stage = 'commit'
        result = _commit_presentation_state(
            g.tenant_id, title=title, project_data=project_data, slides_data=slides_data,
            draft_id=draft_id, creation_key=creation_key,
            expected_revision=expected_revision, source=source, action='إنشاء العرض',
            details=[f'العنوان: «{title}»', f'عدد الشرائح: {slide_count}'] + provenance_details,
        )
    except (LookupError, ValueError) as error:
        return jsonify({'error': str(error)}), 400
    except Exception as exc:
        return _presentation_save_failure(save_stage, exc)
    pres_id = result['presentation_id']
    if not result.get('created', True):
        return jsonify({
            'success': False, 'error': 'يوجد عرض محفوظ لهذا القسم من المشروع؛ لم يُنشأ عرض مكرر',
            'error_code': 'PRESENTATION_SCOPE_EXISTS', 'presentationId': pres_id,
            'currentRevision': result['revision'],
        }), 409
    try:
        db.link_draft_usage_to_presentation(
            g.tenant_id, project_data.get('draftId') or project_data.get('draft_id'), pres_id)
    except Exception as link_error:
        print(f"[AI-USAGE] usage link failed for presentation {pres_id}: {link_error}")
    return jsonify(_presentation_revision_response(result)), 201


@app.route('/api/presentations/<pres_id>', methods=['GET'])
@require_permission('view_presentations')
def api_get_presentation(pres_id):
    """Get a specific presentation."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'Presentation not found'}), 404

    # ISS-030: the workspace keeps saving into the linked draft, so the client
    # needs its current revision — otherwise the next expectedRevision save
    # conflicts against a stale counter it never saw.
    draft_revision = None
    if pres.get('draft_id'):
        linked_draft = db.get_project_draft_by_id(g.tenant_id, pres['draft_id'])
        if linked_draft:
            draft_revision = int(linked_draft.get('revision') or 0)

    if int(pres.get('revision') or 0) > 0:
        state = _presentation_state(pres)
        # ISS-015: the stored projectData is a draft snapshot — hidden sections
        # stay server-side for this caller.
        state['projectData'] = _draft_data_for_response(state.get('projectData'))
        state['draftRevision'] = draft_revision
        return jsonify({'success': True, 'presentation': state})
    pres['revision'] = int(pres.get('revision') or 0)
    pres['projectData'] = json.loads(pres['project_data']) if pres.get('project_data') else {}
    pres['projectData'] = _merge_persisted_map_assets(pres['projectData'], g.tenant_id, presentation_id=pres_id)
    slides = json.loads(pres['slides_data']) if pres.get('slides_data') else []
    branding = db.get_branding(g.tenant_id) or {}
    render_project_data = copy.deepcopy(pres['projectData'])
    _prepare_generation_logo_context(render_project_data, branding, g.tenant_id)
    slides = slide_engine.renumber_presentation_slides(
        slides, branding=branding, project_data=render_project_data, tenant_id=g.tenant_id,
        creative_images=_presentation_creative_images(render_project_data, g.tenant_id),
    )
    project_logo_ref = slide_engine._project_logo_reference(render_project_data)
    for s in slides:
        if isinstance(s, dict) and 'html' in s and isinstance(s['html'], str):
            # Resolve through the engine copy: it fixes ##LOGO## tokens and broken
            # logo paths exactly like the legacy pass, but never appends the 50px
            # logo sizing over an explicit height. The legacy pass matched the
            # watermark overlay img (its src carries tenant-assets) and appended
            # max-height:50px;width:auto, collapsing width:480px to a ~50px mark
            # on every open/refresh — and the next save persisted the shrink.
            s['html'] = slide_engine.resolve_logo_in_html(
                s['html'], g.tenant_id, _branding_cache=branding,
                project_logo=project_logo_ref,
            )
    pres['slide_count'] = len(slides)
    pres['slidesData'] = slides
    pres['projectData'] = _draft_data_for_response(pres.get('projectData'))
    pres['draftRevision'] = draft_revision
    return jsonify({'success': True, 'presentation': pres})


@app.route('/api/presentations/<pres_id>', methods=['PUT'])
@require_permission('create_presentation')
def api_update_presentation(pres_id):
    """Update a presentation. Saves a version snapshot and logs the edit."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'Presentation not found'}), 404

    data = request.json or {}
    if not isinstance(data, dict) or ('projectData' in data and not isinstance(data['projectData'], dict)) or ('slidesData' in data and not isinstance(data['slidesData'], list)):
        return jsonify({'error': 'projectData must be an object and slidesData an array'}), 400
    locked_status = _presentation_draft_lock(pres.get('draft_id'), data, presentation_id=pres_id)
    if locked_status:
        return _draft_locked_response(locked_status)
    # t16: editing a finally-approved file is a privileged, reasoned action —
    # the permission plus a written reason, both recorded with the edit.
    post_approval_reason = ''
    if pres.get('status') == 'approved' and ('projectData' in data or 'slidesData' in data):
        if not _omran_can('post_approval_edit'):
            return jsonify({'error': 'تعديل ملف معتمد يتطلب صلاحية التعديل بعد الاعتماد',
                            'error_code': 'post_approval_edit_required'}), 403
        post_approval_reason = str(data.get('editReason') or '').strip()
        if not post_approval_reason:
            return jsonify({'error': 'سبب التعديل بعد الاعتماد إلزامي',
                            'error_code': 'reason_required'}), 400
    try:
        expected_revision = _expected_presentation_revision(data, pres)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    source, provenance_details = _verified_presentation_provenance(data, pres_id, expected_revision)
    save_stage = 'normalize'
    try:
        updates = {}
        for k in ['title', 'projectData', 'slidesData']:
            if k in data:
                db_key = {'projectData': 'project_data', 'slidesData': 'slides_data'}.get(k, k)
                updates[db_key] = normalize_presentation_assets(data[k], g.tenant_id) if k in {'projectData', 'slidesData'} else str(data[k] or '').strip()
        if 'status' in data and data.get('status') in {'draft', 'edited'}:
            # Operational states (pending_approval/approved/rejected) belong to
            # the approval gates — a save payload can never walk into them.
            updates['status'] = 'draft'
        if isinstance(updates.get('project_data'), dict):
            current_project = _presentation_state(pres)['projectData']
            current_scope = current_project.get('presentation_scope')
            incoming_scope = updates['project_data'].get('presentation_scope')
            if current_scope and incoming_scope and current_scope != incoming_scope:
                return jsonify({'error': 'Presentation scope does not match', 'error_code': 'PRESENTATION_SCOPE_MISMATCH'}), 409
            if current_scope:
                updates['project_data']['presentation_scope'] = current_scope
            if pres.get('draft_id'):
                updates['draft_id'] = pres['draft_id']
                updates['project_data']['draftId'] = pres['draft_id']
                updates['project_data']['draft_id'] = pres['draft_id']
            else:
                updates['draft_id'] = (updates['project_data'].get('draftId')
                                       or updates['project_data'].get('draft_id'))
            # ISS-015: projectData is stored draft data — a section the caller
            # cannot see must survive the save unchanged, exactly like the
            # project-draft save path enforces.
            forbidden_sections, _restored = _enforce_draft_field_sections(
                updates['project_data'], current_project, None, None)
            if forbidden_sections:
                return jsonify({
                    'error': 'لا تملك صلاحية تعديل الأقسام: ' + '، '.join(forbidden_sections),
                    'error_code': 'SECTION_FORBIDDEN',
                    'sections': forbidden_sections}), 403

        if 'slides_data' in updates:
            project_data = updates.get('project_data')
            if not isinstance(project_data, dict):
                try:
                    project_data = json.loads(pres.get('project_data') or '{}')
                except (TypeError, ValueError):
                    project_data = {}
            update_branding = db.get_branding(g.tenant_id) or {}
            render_project_data = copy.deepcopy(project_data)
            _prepare_generation_logo_context(render_project_data, update_branding, g.tenant_id)
            save_stage = 'renumber'
            updates['slides_data'] = slide_engine.renumber_presentation_slides(
                updates['slides_data'], branding=update_branding,
                project_data=render_project_data, tenant_id=g.tenant_id,
                creative_images=_presentation_creative_images(render_project_data, g.tenant_id),
            )
            updates['slide_count'] = len(updates['slides_data'])

        save_stage = 'history'
        details = []
        action = 'تعديل العرض'
        if 'title' in updates and updates['title'] != pres.get('title'):
            details.append(f'عنوان العرض: من «{pres.get("title") or "بدون"}» إلى «{updates["title"]}»')
        if 'project_data' in updates:
            try:
                old_project_data = json.loads(pres.get('project_data') or '{}')
            except (TypeError, ValueError):
                old_project_data = {}
            details.extend(change_tracking.describe_draft_changes(
                old_project_data, updates['project_data'],
                id_names=_draft_change_id_names()))
        if 'slides_data' in updates:
            current_slides = change_tracking.parse_slides(pres.get('slides_data'))
            details.extend(change_tracking.describe_slide_changes(current_slides, updates['slides_data']))
            action = 'تعديل الشرائح'
        if 'status' in updates and updates['status'] != pres.get('status'):
            details.append(f'حالة العرض: من «{pres.get("status") or "مسودة"}» إلى «{updates["status"]}»')
        if post_approval_reason:
            details.append(f'تعديل بعد الاعتماد — السبب: {post_approval_reason}')
        updates.pop('slide_count', None)
        if data.get('operation') == 'generation':
            action = 'توليد العرض'
        save_stage = 'commit'
        result = _commit_presentation_state(
            g.tenant_id, pres_id, expected_revision=expected_revision,
            source=source, action=action, details=details + provenance_details, **updates)
    except db.PresentationRevisionConflict:
        raise
    except (LookupError, ValueError) as error:
        return jsonify({'error': str(error)}), 400
    except Exception as exc:
        return _presentation_save_failure(save_stage, exc)
    return jsonify(_presentation_revision_response(result))
