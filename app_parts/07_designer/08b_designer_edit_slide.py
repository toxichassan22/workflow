def _designer_edit_slide(html, title, instruction, slide_index, project_data, presentation_id, branding, tenant_id=None, creative_images=None, user_image_refs=None, slide_type='content', total_slides=None, content_source=None, skip_vision=False, progress_callback=None):
    """Ask the slide model for one complete slide and retry malformed responses with Playwright Vision guidance."""
    if not tenant_id:
        try:
            tenant_id = g.tenant_id
        except Exception:
            tenant_id = None

    table_edit = designer_chat_reliability.apply_table_delete_request(html, instruction)
    if table_edit['changed']:
        return table_edit['html'], table_edit['description']
    is_slide_redesign = bool(re.search(
        r'(?:اعد\s*تصميم|إعادة\s*تصميم|غير\s*تصميم|تصميم|تنسيق|شريحة|سلايد|redesign|layout|style)',
        str(instruction or ''),
        re.IGNORECASE
    ))
    if not is_slide_redesign and table_edit['handled'] and table_edit.get('reason') == 'would_empty_table':
        reason_text = _TABLE_PRECHECK_ARABIC_REASONS.get(table_edit['reason'], table_edit['reason'])
        return html, (table_edit['description'] or f'تعذر تحديد تعديل الجدول بأمان: {reason_text}')
    if designer_chat_colors.is_color_only_request(instruction):
        color_html, color_message = designer_chat_colors.apply_color_edit(html, instruction)
        return color_html or html, color_message

    # The project timeline is a system-owned slide like the boundary diagram: a
    # request for its chart rebuilds the deterministic colored Gantt instead of
    # whatever dots-on-a-line the model would improvise.
    if (_is_project_timeline_slide(title=title, content_source=content_source, html=html)
            and _designer_requests_timeline_chart(instruction)
            and slide_engine.parse_timeline_phases(
                project_data if isinstance(project_data, dict) else {})):
        try:
            timeline_html = slide_engine._build_timeline_slide(
                {
                    'title': title,
                    'type': slide_type or 'content',
                    'content_source': content_source or 'timeline_table_data',
                },
                project_data,
                branding,
                slide_num=slide_index + 1,
                total_slides=total_slides or (slide_index + 1),
            )
            timeline_html = resolve_designer_chat_placeholders(
                timeline_html, project_data, presentation_id, tenant_id, creative_images)
            timeline_html = slide_engine.finalize_designer_slide_html(
                timeline_html, slide_type or 'content', project_data, branding,
                creative_images=creative_images, tenant_id=tenant_id,
                slide_num=slide_index + 1, slide_title=title,
                total_slides=total_slides or (slide_index + 1), content_source=content_source,
                allow_all_maps=True,
            )
            timeline_html = _sanitize_designer_output(timeline_html)
            if not _is_watermark_removal_instruction(instruction):
                timeline_html = _carry_slide_watermark(html, timeline_html)
            if timeline_html:
                return timeline_html, (
                    'أعدت بناء شريحة الجدول الزمني كمخطط جانت ملوّن على محور التاريخ: '
                    'كل مرحلة شريط ملون بامتداد تاريخها الفعلي مع مدتها وملاحظاتها.')
        except Exception:
            app.logger.exception(
                '[DESIGNER-EDIT] deterministic timeline build failed for slide %s', slide_index + 1)

    rules = build_design_rules(branding)
    training_context = ''
    if tenant_id:
        try:
            training_context = db.get_training_context(
                tenant_id, offer_lang=slide_engine.resolve_offer_lang(project_data)) or ''
        except Exception:
            training_context = ''
    training_note = (
        f"\n\n## قواعد الشركة الملزمة (من التدريب — التزم بها في التصميم)\n{training_context}"
        if training_context else ''
    )
    team_logo_note = (
        "\n\n## شعارات فريق العمل في هذا المشروع\n"
        + _designer_team_logo_context(creative_images)
        + "\nلا تضع شعار جهة فريق العمل في هيدر الشركة، ولا تستبدله بـ ##LOGO## أو ##PROJECT_LOGO##. "
          "عند طلب شعار جهة محددة، أدرج الرمز المطابق داخل موضع محتوى مناسب في الشريحة. "
          "ممنوع إدراج أي شعار (شركة أو مشروع أو فريق عمل) إلا إذا طلب المستخدم ذلك صراحة بكلمة "
          "شعار أو لوجو أو علامة تجارية في رسالته الحالية. طلب وصف أو شرح أو تعليق على صور موجودة "
          "يعني إضافة نص وصفي فقط دون أي شعار ودون توليد صورة جديدة، وطلب صورة أو تصميم أو توليد "
          "يعني صورة معمارية جديدة وليس شعاراً."
    )

    # Capture Playwright vision screenshot of the current slide if available (skip in large bulk edits for speed)
    vision_image_uri = None
    vision_error = ''
    if not skip_vision:
        try:
            import generate_pdf_from_preview as renderer
            vision_image_uri = renderer.render_slide_to_image_base64(html, branding=branding, tenant_id=tenant_id)
            if not vision_image_uri:
                vision_error = getattr(renderer, 'LAST_VISION_ERROR', '') or 'no_snapshot'
        except Exception as ve:
            vision_error = str(ve)
            print(f"[DESIGNER-EDIT VISION] Screenshot failed: {ve}")
    else:
        vision_error = 'skipped_batch'
    _record_slide_vision_state(bool(vision_image_uri), vision_error)
    if vision_error:
        # Without the snapshot the model edits the markup blind, and it still claims success. The
        # user was left believing a layout was inspected and fixed when it was never seen.
        print(f"[DESIGNER-EDIT VISION] Editing slide {slide_index + 1} without a visual snapshot ({vision_error})")

    image_refs = None
    vision_note = ""
    if vision_image_uri:
        image_refs = [{"data_uri": vision_image_uri}]
        vision_note = (
            "\n\n## الرؤية البصرية للشريحة الحالية (Visual Vision Snapshot):\n"
            "لقد تم تزويدك بلقطة شاشة مرئية فعلية للشريحة الحالية بدقة 1280x720 كما تظهر للمستخدم تماماً.\n"
            "- انظر بدقة إلى اللقطة المرفقة لتفهم:\n"
            "  1. التوزيع البصري، الهوامش، والمسافات البينية (spacing / padding / margins).\n"
            "  2. أحجام الخطوط والتسلسل الهرمي للنصوص وعناوين البطاقات.\n"
            "  3. تموضع وحجم الصور والبطاقات والشعارات.\n"
            "  4. درجات الألوان وتناسق الخلفية مع النصوص والبطاقات.\n"
            "- نفّذ التعديل المطلوب بدقة جراحية مع الحفاظ على التناسق البصري والجمالي والتوازن وبدون تداخل نصوص."
        )

    if user_image_refs:
        # The user's own attachment comes after the snapshot, so the order matches the note below.
        image_refs = (image_refs or []) + list(user_image_refs)
        vision_note += (
            "\n\n## صورة أرفقها المستخدم مع طلبه\n"
            "الصورة الأخيرة المرفقة هي صورة المستخدم، لا لقطة الشريحة. استخدمها كما يوضح طلبه"
            " (مرجع تصميم أو محتوى مطلوب أو خلل يشير إليه)، ولا تنسخ نصوصها إلى الشريحة إلا إن طلب ذلك."
        )

    # Store base64 data URIs to avoid inflating prompt with hundreds of thousands of tokens
    base64_map = {}
    def _preserve_base64(match):
        idx = len(base64_map)
        ph = f"##PRESERVED_BASE64_{idx}##"
        base64_map[ph] = match.group(0)
        return ph

    clean_html = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', _preserve_base64, html or '')

    surface_note = '' if slide_type in ('cover', 'closing', 'section_divider', 'moodboard') else (
        "\n\n## عقد سطح شريحة المحتوى\n"
        "هذه شريحة محتوى عادية ويجب أن تبقى على canvas أبيض أو فاتح موحد، لا على إطار داكن حول صفحة بيضاء. "
        "استخدم اللون الأساسي في العناوين ورؤوس الجداول والمساحات المحدودة فقط، واترك الخلفية الداكنة الكاملة للغلاف والخاتمة وفواصل الأقسام ذات الصورة. "
        "خلفية شعار الشركة وشعار المشروع مستقلة لكل شعار حسب لونه وتباينه؛ لا تغيّرها عند تغيير خلفية الشريحة."
    )

    is_boundary_slide = _is_land_boundary_diagram_slide(
        title=title, content_source=content_source, html=html)
    boundary_data_request = is_boundary_slide and _designer_requests_boundary_data(instruction)
    requested_maps_link = is_boundary_slide and _designer_requests_google_maps_link(instruction)
    project_maps_link = _designer_project_maps_link(project_data) if requested_maps_link else ''
    canonical_boundary_html = ''
    if boundary_data_request and slide_engine._has_land_boundary_data(project_data):
        try:
            canonical_boundary_html = slide_engine._build_land_boundary_diagram_slide(
                {
                    'title': title,
                    'type': slide_type or 'content',
                    'content_source': content_source or 'land_boundary_diagram',
                },
                project_data,
                branding,
                slide_num=slide_index + 1,
                total_slides=total_slides or (slide_index + 1),
            )
            canonical_boundary_html = resolve_designer_chat_placeholders(
                canonical_boundary_html, project_data, presentation_id, tenant_id, creative_images)
            canonical_boundary_html = slide_engine.finalize_designer_slide_html(
                canonical_boundary_html, slide_type or 'content', project_data, branding,
                creative_images=creative_images, tenant_id=tenant_id,
                slide_num=slide_index + 1, slide_title=title,
                total_slides=total_slides or (slide_index + 1), content_source=content_source,
                allow_all_maps=True,
            )
            canonical_boundary_html = _sanitize_designer_output(canonical_boundary_html)
            if not _is_watermark_removal_instruction(instruction):
                canonical_boundary_html = _carry_slide_watermark(html, canonical_boundary_html)
        except Exception:
            canonical_boundary_html = ''
            app.logger.exception(
                '[DESIGNER-EDIT] deterministic boundary build failed for slide %s', slide_index + 1)
    project_context = _designer_project_context(project_data, creative_images, tenant_id)

    _edit_lang_note = ''
    _edit_response_spec = 'شرح عربي موجز ودقيق لما قمت به جراحياً'
    if slide_engine.resolve_offer_lang(project_data) == slide_engine.OFFER_LANG_ENGLISH:
        _edit_lang_note = (
            '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN +
            '\nEvery word you author on the slide — headings, paragraphs, labels, cell text — '
            'is written in English.'
        )
        _edit_response_spec = 'brief, precise English summary of the surgical change'

    prompt = f"""{rules}{training_note}{team_logo_note}{vision_note}{surface_note}{_edit_lang_note}

{project_context}
أنت Landloom، كبير المصممين ومهندس العرض وجرّاح كود وتصميم (Surgical Code & Design Master). عدّل الشريحة بدقة جراحية متناهية حسب الطلب:
1. قواعد الإزاحات والتخطيط الجراحي (Spatial & Layout Precision):
   - تحكّم دقيق بكسلي ونسبية في CSS: رفع أو تنزيل الهيدر، ضبط هوامش البطاقات الداخلية (padding) والخارجية (margins)، وتغيير حجم البطاقات والمسافات البينية (gap).
   - تحويل التخطيط بسلاسة بين عمودين أو ثلاثة أعمدة أو شبكة غير متماثلة (Asymmetric Grid) مع الحفاظ التام على انسيابية العناصر.
   - ضبط المحاذاة العمودية والأفقية والتوزيع المتوازن (align-items / justify-content).
2. النظم الجمالية والهوية المعتمدة (Design System & Tokens):
   - حافظ على خط الشركة المحمل؛ لا تكتب اسم خط ثابت ولا تغيره في طلب لون أو محتوى.
   - ألوان الشركة أعلاه هي الافتراضية. تغيير اللون الصريح من المستخدم يطبق على العناصر المطلوبة فقط دون إعادة تلوين باقي الشريحة.
   - تحقيق تباين لوني عالي (Contrast Ratio >= 4.5:1) لضمان سهولة القراءة الفائقة.
3. التعديل الجراحي الموضعي (Surgical Modifications):
   - إضافة أو حذف أو تعديل بطاقة أو نص أو مكون محدد دون مساس بباقي محتويات الشريحة، ودون إعادة بناء من الصفر، ودون تدمير التنسيق.
   - حذف صف أو عمود من جدول داخل الشريحة هو تعديل جراحي عادي: احذف <tr> الصف المطلوب أو خلية العمود من كل صف بما فيها الرأس، وحافظ على البقية.
4. إدراج الخرائط والمكونات المعمارية:
   - يمكنك إدراج أو استبدال أي خريطة من الخرائط الأربع المعتمدة (##MAP_OVERVIEW##, ##MAP_ACCESS##, ##MAP_CATCHMENT##, ##MAP_LANDMARKS##) أو صور المكونات مع ضبط موضعها وأبعادها بدقة.
5. الصياغة العقارية والاستثمارية الرفيعة (Saudi Real Estate Phrasing):
   - نبرة رسمية استثمارية رفيعة المستوى تخاطب المستثمرين واللجان التمويلية.
   - استخدام المصطلحات العقارية السعودية الدقيقة (معامل البناء، الارتدادات، الصك الإلكتروني، كود البناء السعودي).
6. الامتثال الصارم (Strict Compliance):
   - ممنوع منعاً باتاً وضع أي أيقونات أو إيموجي أو رموز تعبيرية (No icons, no emojis).
   - ممنوع وضع أي رموز أسهم (استخدم كلمات: أعلى، أسفل، يمين، يسار).
   - خلو الشريحة تماماً من أي نص تعليمي (No How-To text).
   - الحفاظ على مقاس الشريحة القياسي 1280x720 و overflow:hidden دون أشرطة تمرير.
   - سطح الشريحة: شرائح المحتوى العادية فاتحة وموحدة، ولا تُبنى كواجهة داكنة أو كإطار داكن حول صفحة بيضاء. حافظ على خلفية كل شعار مستقلة حسب لونه.
7. حرية إبداعية وتصميمية مطلقة لجميع أنواع الشرائح (Full Creative Freedom):
   - تمتلك كامل الصلاحية والحرية المطلقة لتعديل أو إعادة ابتكار وتصميم أي شريحة يطلبها المستخدم بلا أي استثناء أو قيود نوعية:
     * شرائح الفصول والأقسام الرئيسية (Section Dividers / الفصول): لك مطلق الحرية في إعادة تصميمها بتخطيطات إبداعية كاملة (مثل: إضافة كروت ملخصة لمحاور القسم، خطوط زمنية، إبراز مؤشرات أو أرقام قياسية، تقسيم الشريحة أفقياً أو عمودياً Split View، دمج صورة معمارية مع بطاقة داكنة ملكية، تدرجات لونية، خطوط عريضة، إلخ).
     * شريحة الفهرس (Index Slide): لك الحرية في تصميمها بشبكات عصرية أو بطاقات مرقمة فاخرة، مع الحفاظ على وسم data-index-page="section_key" لكل قسم لربط أرقام الصفحات.
     * شرائح الغلاف والخاتمة (Cover & Closing): كامل الحرية في إعادة توزيع العناصر وتنسيق المقدمة والخاتمة.
     * شرائح المحتوى، الخرائط، والتحليلات.
   - لا ترفض ولا تعتذر عن تعديل أي شريحة مهما كان نوعها، ونفّذ أي فكرة تصميمية يطلبها المستخدم بحرية مطلقة وإتقان واحترافية.
8. الهيدر والفوتر والشعارات وترقيم الصفحة عناصر قابلة للتعديل والنقل والحذف (Editable Chrome):
   - قد يصفها المستخدم بأي صيغة («أعلى الصفحة»، «الشريط العلوي»، «أسفل الشريحة»، «الشعار الزائد»...) — حدّد أنت العنصر المقصود من وصفه ونفّذ بلا رفض ولا اعتذار.
   - عند حذف عنصر مُدار عمداً أعلنه في حقل "removed" داخل JSON حتى لا يعاد إدراجه آلياً: القيم المعتمدة "company_logo"، "project_logo"، "logo" (الشعاران معاً)، "header"، "footer"، "counter". ما لا تُعلنه ولم يُطلب حذفه يبقى محفوظاً — لا تحذفه من تلقاء نفسك.
   - الترقيم الوحيد المسموح هو عنصر data-slide-counter المُدار — لا تخترع رقم صفحة أو تكتب «7/1» أو «NN — NN» بنفسك في الهيدر أو أي مكان، وأي عنصر كهذا موجود احذفه عند الطلب وأعلنه في "removed".
أعد JSON فقط بالشكل:
{{"html":"<div class=\\"slide\\">...</div>","response":"{_edit_response_spec}","removed":["project_logo"]}}
(الحقل "removed" يُدرج فقط عند حذف عنصر مُدار فعلاً؛ غير ذلك أرسله قائمة فارغة أو احذفه.)
عنوان الشريحة: {title}
HTML الحالي:
{clean_html}
الطلب:
{instruction}"""

    failure_reasons = []
    for attempt in range(1, 4):
        if callable(progress_callback):
            try:
                progress_callback(attempt, 3)
            except Exception as progress_error:
                app.logger.warning('[DESIGNER-EDIT] progress callback failed: %s', progress_error)
        try:
            raw = extract_chat_content(call_text_chat(prompt, instruction, max_tokens=DESIGNER_EDIT_MAX_TOKENS, model=SLIDE_TEXT_MODEL, image_references=image_refs, timeout=300, usage_ctx=_usage_ctx('designer_chat', project_data, presentation_id=presentation_id)), 'DESIGNER-EDIT')
            parsed = _designer_json_response(raw)
            output = parsed.get('html') or parsed.get('content') or parsed.get('slide_html')
            if not output and raw and '<div' in raw and 'slide' in raw:
                div_m = re.search(r'<div\b[^>]*class=["\']slide["\'][\s\S]*?</div>', raw, flags=re.IGNORECASE)
                if div_m:
                    output = div_m.group(0)
            if output and ('slide' in output and '<div' in output):
                if 'class="slide"' not in output and "class='slide'" not in output:
                    output = f'<div class="slide" style="width:1280px;height:720px;position:relative;box-sizing:border-box;overflow:hidden;">{output}</div>'
                
                # Restore any preserved base64 images
                for ph, b64_str in base64_map.items():
                    output = output.replace(ph, b64_str)
                model_changed = designer_chat_reliability.materially_changed(
                    html, output, parsed.get('response'))
                if (not model_changed and not canonical_boundary_html
                        and not (requested_maps_link and project_maps_link)):
                    failure_reasons.append('no_material_change')
                    print(f'[DESIGNER-EDIT] model returned no change on attempt {attempt}')
                    continue

                output = resolve_designer_chat_placeholders(output, project_data, presentation_id,
                                                           tenant_id, creative_images)
                # A rebuilt slide that kept its old map <img> kept the old map:
                # stored sources are frozen revision URLs the model preserves
                # verbatim, so any persisted-map source is repointed at the
                # current file for its canonical type before it is kept.
                output = _refresh_slide_map_sources(
                    output, project_data, tenant_id, presentation_id=presentation_id,
                    creative_images=creative_images)
                # Same staleness problem for chat-placed asset images: the
                # stamped tag's token is authoritative, its stored src is not.
                output = _refresh_slide_asset_sources(
                    output,
                    _designer_image_assets(
                        _designer_creative_images(project_data, creative_images)))
                output = slide_engine.finalize_designer_slide_html(
                    output, slide_type or 'content', project_data, branding,
                    creative_images=creative_images, tenant_id=tenant_id,
                    slide_num=slide_index + 1, slide_title=title,
                    total_slides=total_slides or (slide_index + 1), content_source=content_source,
                    allow_all_maps=True, instruction=instruction,
                    removed_elements=parsed.get('removed') or parsed.get('removed_elements'),
                )
                output = _sanitize_designer_output(output)
                # The model rebuilds the slide and drops the watermark overlay div.
                # Carry it over so any later AI edit cannot silently delete it.
                if not _is_watermark_removal_instruction(instruction):
                    output = _carry_slide_watermark(html, output)
                # Content requests on this system-owned slide always use the canonical builder.
                # Sol may choose the operation, but it cannot relocate directions, omit documented
                # neighbours or substitute stale data in the resulting boundary diagram.
                if canonical_boundary_html:
                    output = canonical_boundary_html
                if is_boundary_slide:
                    # The boundary diagram is rebuilt from documented facts: a model
                    # reply that drops a documented length corrupts the slide, and a
                    # data-add request with no visible text change is a false success.
                    # Retry instead of returning either.
                    try:
                        boundary_data = slide_engine._extract_land_boundary_diagram_data(
                            project_data if isinstance(project_data, dict) else {}
                        )
                    except Exception:
                        boundary_data = {}
                    if isinstance(boundary_data, dict):
                        dropped = []
                        for _dir_key in ('north', 'south', 'east', 'west'):
                            _raw_item = boundary_data.get(_dir_key)
                            _item = _raw_item if isinstance(_raw_item, dict) else {}
                            _length = str(_item.get('length') or '').strip()
                            _number = re.search(r'\d+(?:\.\d+)?', _length)
                            if _number and _number.group(0) not in str(output or ''):
                                dropped.append(_dir_key)
                        if dropped:
                            failure_reasons.append('dropped_boundary_data')
                            print(f'[DESIGNER-EDIT] boundary slide dropped lengths {dropped} on attempt {attempt}')
                            continue
                    if boundary_data_request:
                        _strip_tags = lambda value: re.sub(
                            r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(value or ''))).strip()
                        if _strip_tags(output) == _strip_tags(html) and not requested_maps_link:
                            failure_reasons.append('boundary_data_unchanged')
                            print(f'[DESIGNER-EDIT] boundary data already current on attempt {attempt}')
                            return output, (
                                f'تم الحفاظ على تصميم الشريحة {slide_index + 1}. '
                                'أحدث بيانات الحدود مطابقة لما هو ظاهر بالفعل في الشريحة.'
                            )
                inserted_requested_maps_link = False
                if requested_maps_link:
                    if not project_maps_link:
                        failure_reasons.append('maps_link_missing')
                        print(f'[DESIGNER-EDIT] no stored Google Maps link for slide {slide_index + 1}')
                        continue
                    output, inserted_requested_maps_link = _inject_designer_project_maps_link(
                        output, project_maps_link)
                    if 'data-project-map-link="1"' not in output:
                        failure_reasons.append('invalid_html')
                        print(f'[DESIGNER-EDIT] could not insert Google Maps link on attempt {attempt}')
                        continue
                response_text = (
                    'تم تحديث مخطط الحدود من أحدث بيانات المشروع الموثقة.'
                    if canonical_boundary_html
                    else (parsed.get('response') or 'تم تحديث الشريحة بنجاح.')
                )
                if inserted_requested_maps_link:
                    if not model_changed and not canonical_boundary_html:
                        response_text = 'تمت إضافة رابط Google Maps المحفوظ للمشروع.'
                    else:
                        response_text += ' تمت إضافة رابط Google Maps المحفوظ للمشروع.'
                if vision_error:
                    response_text += ' التعديل جرى على الكود بدون معاينة بصرية للشريحة.'
                return output, response_text
            failure_reasons.append('invalid_html')
            print(f'[DESIGNER-EDIT] invalid HTML on attempt {attempt}')
        except Exception as edit_exc:
            if _is_company_credit_error(edit_exc):
                return html, _COMPANY_CREDIT_EXHAUSTED_MSG
            failure_reasons.append('provider_error')
            app.logger.exception('[DESIGNER-EDIT] attempt %s failed for slide %s', attempt, slide_index + 1)

    fallback = html

    # The boundary diagram is a deterministic system slide. If Sol cannot safely edit it, rebuild
    # it from the newest linked-draft facts instead of returning the old snapshot. This gives new
    # streets, neighbours, widths and lengths a reliable path without weakening the no-op guard.
    deterministic = canonical_boundary_html or fallback
    rebuilt_boundary = bool(canonical_boundary_html) and designer_chat_reliability.materially_changed(
        html, deterministic, 'إعادة بناء شريحة الحدود من أحدث بيانات المشروع')
    if canonical_boundary_html and not rebuilt_boundary:
        failure_reasons.append('boundary_data_unchanged')

    inserted_maps_link = False
    if requested_maps_link:
        if project_maps_link:
            deterministic, inserted_maps_link = _inject_designer_project_maps_link(
                deterministic, project_maps_link)
        else:
            failure_reasons.append('maps_link_missing')

    if (rebuilt_boundary or inserted_maps_link) and designer_chat_reliability.materially_changed(
            html, deterministic, 'تحديث حتمي من بيانات المشروع'):
        completed = []
        if rebuilt_boundary:
            completed.append('تم تحديث مخطط الحدود من أحدث بيانات المشروع الموثقة')
        if inserted_maps_link:
            completed.append('تمت إضافة رابط Google Maps المحفوظ للمشروع')
        return deterministic, '، و'.join(completed) + '.'

    detail = _designer_edit_failure_detail(failure_reasons)
    print(f'[DESIGNER-EDIT] slide {slide_index + 1} rejected after 3 attempts: {failure_reasons}')
    return fallback, f'تم الحفاظ على تصميم الشريحة {slide_index + 1} لتعذر التعديل التلقائي عليها. {detail}'
