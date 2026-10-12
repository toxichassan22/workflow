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
        first_fatal = None
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
                    if getattr(exc, 'fatal_ai_error', False) and first_fatal is None:
                        first_fatal = exc
                    results[idx] = ''

        # A deterministic refusal (wallet/key) must not be retried slide by
        # slide or degraded into a partial deck — fail with the real cause.
        if first_fatal is not None:
            raise first_fatal

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
        fatal = _ai_fatal_http_response(e)
        if fatal is not None:
            return fatal
        return jsonify({'success': False, 'error': str(e)}), 500
