def _designer_legacy_apply(plan, actions, message, data, slides, project_data,
                           presentation, presentation_id, branding, tenant_id,
                           current_index, creative_images, request_creative_images,
                           project_creative_images, user_image_refs, chat_attached_urls,
                           history_for_turn, chat_memory, focus_indexes,
                           preferred_indexes, slides_before, is_all_slides_request,
                           report_designer_progress):
    """Apply the legacy all-at-once plan: per-tool executors, rollback rules,
    validation and the final workspace_update/ask/chat_only response."""
    # A question is an answer on its own: nothing is edited until the user replies.
    question = ''
    for action in actions if isinstance(actions, list) else []:
        if isinstance(action, dict) and action.get('tool') == 'ask':
            params = action.get('params') if isinstance(action.get('params'), dict) else {}
            question = str(params.get('question') or '').strip()
            if question:
                break
    if question:
        ask_messages = list(history_for_turn)
        if not ask_messages or ask_messages[-1].get('content') != message or ask_messages[-1].get('role') != 'user':
            ask_messages.append({'role': 'user', 'content': message[:2000], 'slides': preferred_indexes[:]})
        ask_messages.append({'role': 'assistant', 'content': question[:2000], 'slides': preferred_indexes[:]})
        ask_chat = {
            'presentationId': presentation_id or None,
            'messages': ask_messages[-DESIGNER_CHAT_STORED_TURNS * 2:],
            'memory': chat_memory,
            'focusIndexes': preferred_indexes[:],
        }
        ask_project_data = dict(project_data)
        ask_project_data['designerChat'] = ask_chat
        return jsonify({'success': True, 'data': {
            'action': 'ask',
            'response': question,
            'slidesData': slides,
            'creativeImages': data.get('creativeImages') if isinstance(data.get('creativeImages'), dict) else {},
            'actions': [{'tool': 'ask', 'status': 'success'}],
            'memory': chat_memory,
            'focusIndexes': focus_indexes,
            'chatHistory': ask_chat['messages'],
            'saved': False,
        }})

    if not actions or any(not isinstance(action, dict) for action in actions):
        return jsonify({'success': False, 'error': 'لم تصل خطة تنفيذ صالحة؛ لم يتغير العرض.',
                        'error_code': 'DESIGNER_INVALID_PLAN'}), 502

    if all(action.get('tool') == 'chat_only' for action in actions):
        response_text = str(plan.get('response') or '').strip()
        chat_messages = list(history_for_turn)
        chat_messages.append({'role': 'user', 'content': message[:2000], 'slides': []})
        chat_messages.append({'role': 'assistant', 'content': response_text[:2000], 'slides': []})
        return jsonify({'success': True, 'data': {
            'action': 'chat_only', 'response': response_text, 'actions': [],
            'memory': chat_memory, 'focusIndexes': focus_indexes,
            'chatHistory': chat_messages[-DESIGNER_CHAT_STORED_TURNS * 2:], 'saved': False,
        }})

    try:
        actions = designer_chat_targets.prepare_actions(actions, data, message, slides, current_index)
    except designer_chat_targets.TargetError as _plan_scope_err:
        # The planner named slides outside the explicit request (e.g. it followed an older
        # focus instead of «شريحة 13»). For a supported table row/column delete the message
        # itself already resolves the targets, and the executor below applies the edit
        # deterministically — so fall back to those slides instead of failing the turn
        # with «خطة التعديل لا تطابق الشرائح المحددة» and changing nothing.
        _scope_probe = designer_chat_reliability.detect_table_edit_request(message)
        _scope_fallback = None
        if _scope_probe.get('supported') and _scope_probe.get('operation') == 'delete':
            try:
                _scope_indexes = _resolve_deterministic_table_targets(
                    message, data, slides, current_index, is_all_slides_request)
                if _scope_indexes:
                    _scope_fallback = [{
                        'tool': 'edit_slides',
                        'params': {
                            'target': 'indexes',
                            'indexes': [_i + 1 for _i in _scope_indexes],
                            'instruction': message,
                        },
                    }]
                    print(f"[DESIGNER-CHAT] planner scope rejected ({_plan_scope_err}); "
                          f"falling back to message-resolved slides {[_i + 1 for _i in _scope_indexes]}")
            except Exception as _scope_resolve_err:
                print(f"[DESIGNER-CHAT] scope fallback resolve failed: {_scope_resolve_err}")
                _scope_fallback = None
        if _scope_fallback is None:
            raise
        actions = _scope_fallback
    original_slide_objects = list(slides)
    executed = []
    assistant_messages = []
    tenant_id = g.tenant_id
    for action_number, planned_action in enumerate(actions):
        action = designer_chat_targets.remap_action(planned_action, original_slide_objects, slides)
        tool = action.get('tool') if isinstance(action, dict) else ''
        params = action.get('params') if isinstance(action.get('params'), dict) else {}
        if tool in ('ask', 'chat_only', 'validate_design_workspace', 'save_design_workspace'):
            continue
        if tool == 'apply_image_descriptions':
            indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
            descriptions = designer_chat_reliability.collect_image_descriptions(project_data, creative_images)
            changed = []
            for idx in indexes:
                report_designer_progress(35, f'جاري تعديل الشريحة {idx + 1}...',
                                        {'phase': 'editing', 'activeSlideIndex': idx, 'actionNumber': action_number})
                updated, count, _ = designer_chat_reliability.add_missing_image_descriptions(slides[idx].get('html', ''), descriptions)
                if count:
                    slides[idx].update(html=updated, _designer_keep_html=True, is_custom=True)
                    changed.append(idx)
            executed.append({'tool': tool, 'status': 'success' if changed else 'noop', 'indexes': changed})
            assistant_messages.append(f'أضيفت الأوصاف المحفوظة إلى {len(changed)} شريحة.' if changed else 'لا توجد أوصاف محفوظة ناقصة ومطابقة للصور المستهدفة.')
        elif tool in ('apply_watermark', 'remove_watermark'):
            indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
            # Default off: without an explicit white-only request every targeted
            # slide gets the watermark, otherwise dark slides were silently skipped.
            only_white = params.get('only_white', False)
            is_remove = (tool == 'remove_watermark')
            watermark_url = str(branding.get('watermark_path') or '').strip()
            if not is_remove and not watermark_url:
                assistant_messages.append('لا توجد علامة مائية مرفوعة في إعدادات الشركة؛ لم تتغير أي شريحة.')
                executed.append({
                    'tool': tool, 'status': 'failed', 'indexes': [],
                    'reason': 'watermark_missing',
                })
                continue
            affected_indexes = []
            skipped_dark_indexes = []
            total_target = max(1, len(indexes))
            report_designer_progress(20, 'جاري معالجة العلامة المائية للشرائح...')
            for i, idx in enumerate(indexes):
                slide = slides[idx] if isinstance(slides[idx], dict) else {}
                if only_white and not _is_white_or_light_slide(slide):
                    skipped_dark_indexes.append(idx)
                    continue
                report_designer_progress(25, f'جاري تعديل الشريحة {idx + 1}...',
                                        {'phase': 'editing', 'activeSlideIndex': idx, 'actionNumber': action_number})
                current_slide_html = slide.get('html', '')
                if is_remove:
                    # Hiding keeps the saved position/size/opacity so a later
                    # show restores exactly what the user had.
                    new_html = _set_slide_watermark_visible(current_slide_html, False)
                else:
                    try:
                        wm_opacity = float(params.get('opacity', 0.045))
                    except (TypeError, ValueError):
                        wm_opacity = 0.045
                    try:
                        wm_width = int(params.get('width_px', 480))
                    except (TypeError, ValueError):
                        wm_width = 480
                    new_html = _apply_slide_watermark(current_slide_html, watermark_url, opacity=wm_opacity, width_px=wm_width)
                slide['html'] = new_html
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                slides[idx] = slide
                affected_indexes.append(idx)
                pct = int(20 + 75 * ((i + 1) / total_target))
                report_designer_progress(pct, f"تمت معالجة الشريحة {i + 1} من {total_target}...")

            executed.append({
                'tool': tool,
                'status': 'success',
                'indexes': affected_indexes,
                'count': len(affected_indexes),
                'skipped_indexes': [idx + 1 for idx in skipped_dark_indexes],
                'skipped_count': len(skipped_dark_indexes),
            })
            action_desc = 'حذف' if is_remove else 'إضافة'
            if (not is_remove) and only_white:
                skipped_dark = len(skipped_dark_indexes)
                if skipped_dark > 0:
                    skipped_numbers = ', '.join(str(idx + 1) for idx in sorted(skipped_dark_indexes)[:20])
                    if skipped_dark > 20:
                        skipped_numbers += f' وغيرها ({skipped_dark} إجمالاً)'
                    assistant_messages.append(
                        f"تم {action_desc} العلامة المائية بنجاح في خلفية {len(affected_indexes)} شريحة بيضاء "
                        f"وتخطي {skipped_dark} شريحة داكنة (أرقام: {skipped_numbers}) "
                        f"مع الحفاظ الكامل على النصوص والتصميم."
                    )
                else:
                    assistant_messages.append(
                        f"تم {action_desc} العلامة المائية بنجاح في خلفية {len(affected_indexes)} شريحة مع الحفاظ الكامل على النصوص والتصميم."
                    )
            else:
                assistant_messages.append(
                    f"تم {action_desc} العلامة المائية بنجاح في خلفية {len(affected_indexes)} شريحة مع الحفاظ الكامل على النصوص والتصميم."
                )
        elif tool == 'insert_attached_image':
            # Deterministic insertion of a user-uploaded chat image: no model call.
            try:
                _image_index = int(params.get('image_index') or params.get('imageIndex') or 1)
            except (TypeError, ValueError):
                _image_index = 1
            if not chat_attached_urls or _image_index < 1 or _image_index > len(chat_attached_urls):
                assistant_messages.append(
                    'لا توجد صورة مرفقة بهذه الرسالة بالترتيب المطلوب؛ أرفق الصورة مع نفس الرسالة ثم أعد الطلب.')
                executed.append({'tool': tool, 'status': 'failed', 'reason': 'attached_image_missing'})
                continue
            _image_url = chat_attached_urls[_image_index - 1]
            _position = _designer_attached_image_position(message, params)
            try:
                _opacity = float(params.get('opacity', 0.12 if _position == 'watermark' else 1.0))
            except (TypeError, ValueError):
                _opacity = 0.12 if _position == 'watermark' else 1.0
            try:
                _width = int(params.get('width_px', params.get('widthPx', 480 if _position == 'watermark' else 140)))
            except (TypeError, ValueError):
                _width = 480 if _position == 'watermark' else 140
            _caption = str(params.get('caption') or '')[:160]
            _title = str(params.get('title') or message or 'صورة مرفقة')[:160]
            if _position == 'separate_slide':
                try:
                    _targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                except designer_chat_targets.TargetError:
                    _targets = [current_index] if 0 <= current_index < len(slides) else [len(slides) - 1]
                _insert_at = max(_targets) + 1 if _targets else len(slides)
                _new_html = _build_designer_attached_slide_html(_image_url, title=_title, caption=_caption, branding=branding)
                try:
                    _new_html = resolve_designer_chat_placeholders(
                        _new_html, project_data, presentation_id, tenant_id, creative_images)
                    _new_html = slide_engine.finalize_designer_slide_html(
                        _new_html, 'content', project_data, branding,
                        creative_images=creative_images, tenant_id=tenant_id,
                        slide_num=_insert_at + 1, slide_title=_title,
                        total_slides=len(slides) + 1, content_source='designer_attached_image',
                        allow_all_maps=True)
                except Exception as _fin_err:
                    print(f"[DESIGNER-CHAT] attached slide finalize failed: {_fin_err}")
                _new_slide = {'html': _new_html, 'title': _title, 'type': 'content',
                              'content_source': 'designer_attached_image',
                              'section_key': '', '_designer_keep_html': True, 'is_custom': True}
                slides.insert(min(_insert_at, len(slides)), _new_slide)
                report_designer_progress(60, f'تم إنشاء شريحة جديدة للصورة المرفقة بعد الشريحة {_insert_at}...')
                executed.append({'tool': tool, 'status': 'success', 'position': _position,
                                 'image_index': _image_index, 'inserted_at': _insert_at + 1})
                assistant_messages.append(f'تم وضع الصورة المرفقة في شريحة منفصلة جديدة رقم {_insert_at + 1}.')
            else:
                _indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                for _i, _idx in enumerate(_indexes):
                    _slide = slides[_idx] if isinstance(slides[_idx], dict) else {}
                    _slide['html'] = _insert_designer_attached_image(
                        _slide.get('html', ''), _image_url, position=_position,
                        opacity=_opacity, width_px=_width, caption=_caption)
                    _slide['_designer_keep_html'] = True
                    _slide['is_custom'] = True
                    slides[_idx] = _slide
                    report_designer_progress(
                        int(20 + 60 * ((_i + 1) / max(1, len(_indexes)))),
                        f'تم إدراج الصورة المرفقة في الشريحة {_idx + 1}...')
                executed.append({'tool': tool, 'status': 'success', 'position': _position,
                                 'image_index': _image_index, 'indexes': _indexes})
                _pos_names = {'inline': 'داخل الشريحة', 'background': 'كخلفية للشريحة',
                              'watermark': 'كعلامة مائية', 'logo': 'كشعار إضافي'}
                assistant_messages.append(
                    f"تم وضع الصورة المرفقة {_pos_names.get(_position, 'داخل الشريحة')} "
                    f"في {len(_indexes)} شريحة.")
        elif tool in ('edit_slides', 'edit_design_slide', 'edit_design_slides'):
            indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
            instruction = params.get('instruction') or message
            original_table_request = designer_chat_reliability.detect_table_edit_request(message)
            if original_table_request.get('supported') and original_table_request.get('operation') == 'delete':
                instruction = message
            changed_indexes = []
            if indexes:
                report_designer_progress(20, f'جاري تعديل الشريحة {indexes[0] + 1}...',
                                        {'phase': 'editing', 'activeSlideIndex': indexes[0], 'actionNumber': action_number})
            if len(indexes) > 1:
                skip_vision = len(indexes) > 3
                def _edit_worker(idx):
                    with app.app_context():
                        slide_item = slides[idx] if isinstance(slides[idx], dict) else {}
                        h, r = _designer_edit_slide(
                            slide_item.get('html', ''),
                            slide_item.get('title', f'شريحة {idx + 1}'),
                            instruction,
                            idx,
                            project_data,
                            presentation_id,
                            branding,
                            tenant_id=tenant_id,
                            creative_images=creative_images,
                            user_image_refs=user_image_refs,
                            slide_type=slide_item.get('type', 'content'),
                            total_slides=len(slides),
                            content_source=slide_item.get('content_source') or slide_item.get('contentSource'),
                            skip_vision=skip_vision,
                        )
                        return idx, h, r

                max_workers = min(4, len(indexes))
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(_edit_worker, idx) for idx in indexes]
                    completed_count = 0
                    total_slides_count = len(indexes)
                    for future in concurrent.futures.as_completed(futures):
                        completed_count += 1
                        try:
                            idx_res, updated_html_res, resp_text_res = future.result()
                            original_html_res = slides[idx_res].get('html', '')
                            if designer_chat_reliability.materially_changed(
                                    original_html_res, updated_html_res, resp_text_res):
                                slides[idx_res]['html'] = updated_html_res
                                slides[idx_res]['_designer_keep_html'] = True
                                slides[idx_res]['is_custom'] = True
                                changed_indexes.append(idx_res)
                                extracted_caps = slide_engine._extract_visual_concept_captions(updated_html_res)
                                if extracted_caps:
                                    slides[idx_res]['captions'] = extracted_caps
                            if resp_text_res:
                                assistant_messages.append(resp_text_res)
                        except Exception as exc:
                            print(f"[PARALLEL EDIT ERROR] Slide edit failed: {exc}")
                        pct = int(15 + 75 * (completed_count / total_slides_count))
                        report_designer_progress(pct, f"تمت معالجة الشريحة {completed_count} من {total_slides_count}...")
            else:
                for idx in indexes:
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    original_html = slide.get('html', '')
                    report_designer_progress(40, f"جاري تعديل الشريحة {idx + 1}...")
                    html, response_text = _designer_edit_slide(
                        original_html, slide.get('title', f'شريحة {idx + 1}'),
                        instruction, idx, project_data, presentation_id, branding,
                        tenant_id=tenant_id, creative_images=creative_images,
                        user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                        total_slides=len(slides),
                        content_source=slide.get('content_source') or slide.get('contentSource'),
                        progress_callback=lambda attempt, total: report_designer_progress(
                            min(78, 35 + attempt * 12),
                            f"جاري تنفيذ محاولة تعديل الشريحة {attempt} من {total}...",
                        ),
                    )
                    if designer_chat_reliability.materially_changed(original_html, html, response_text):
                        slide['html'] = html
                        slide['_designer_keep_html'] = True
                        slide['is_custom'] = True
                        changed_indexes.append(idx)
                        extracted_caps = slide_engine._extract_visual_concept_captions(html)
                        if extracted_caps:
                            slide['captions'] = extracted_caps
                        slides[idx] = slide
                    if response_text:
                        assistant_messages.append(response_text)
                    report_designer_progress(85, f"تم الانتهاء من معالجة الشريحة {idx + 1}...")
            # A multi-slide edit is per-slide work, not an atomic batch: keep every
            # slide that changed and report the ones that did not. Only structural
            # operations stay all-or-nothing (their check is in the failure block).
            _all_changed = bool(indexes) and len(changed_indexes) == len(indexes)
            _failed_targets = sorted(set(indexes) - set(changed_indexes))
            if changed_indexes and _failed_targets:
                _missed = '، '.join(str(i + 1) for i in _failed_targets[:10])
                assistant_messages.append(
                    f'تم تعديل {len(changed_indexes)} من {len(indexes)} شريحة؛ '
                    f'تعذر التعديل في الشرائح {_missed}.')
            executed.append({
                'tool': tool,
                'status': 'success' if _all_changed else ('partial' if changed_indexes else 'failed'),
                'reason': None if _all_changed else 'incomplete_edit',
                'indexes': sorted(changed_indexes),
                'failed_indexes': _failed_targets,
                'requested_indexes': indexes,
            })
        elif tool == 'insert_team_logo':
            raw_team_index = params.get('team_index') or params.get('teamIndex') or 0
            try:
                team_index = int(raw_team_index)
            except (TypeError, ValueError):
                team_index = 0
            team_members = creative_images.get('team_members') if isinstance(creative_images, dict) else []
            team_member = (
                team_members[team_index - 1]
                if isinstance(team_members, list) and 0 < team_index <= len(team_members)
                and isinstance(team_members[team_index - 1], dict)
                else None
            )
            if not team_member or not team_member.get('logo'):
                assistant_messages.append('لا يوجد شعار مرفوع للجهة المحددة في فريق العمل؛ لم يتم إنشاء شعار بديل.')
                executed.append({'tool': tool, 'status': 'failed', 'reason': 'team_logo_missing'})
                continue
            indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
            team_name = str(team_member.get('name') or f'الجهة {team_index}').strip()
            team_token = f'##TEAM_LOGO_{team_index}##'
            team_instruction = (
                f"أدرج شعار جهة فريق العمل «{team_name}» داخل موضع محتوى مناسب ومرئي في هذه الشريحة، "
                f"باستخدام الرمز {team_token} فقط؛ يجب أن يتحول الرمز إلى الشعار المرفوع فعلياً. "
                "لا تستخدم ##LOGO## ولا ##PROJECT_LOGO## لهذا الطلب، ولا تضع شعار الجهة في هيدر شعار الشركة، "
                "وحافظ على شعار الشركة الموجود وبقية محتوى الشريحة وتوازنها البصري."
            )
            successful_indexes = []
            for i, idx in enumerate(indexes):
                slide = slides[idx] if isinstance(slides[idx], dict) else {}
                updated_html, response_text = _designer_edit_slide(
                    slide.get('html', ''), slide.get('title', f'شريحة {idx + 1}'),
                    team_instruction, idx, project_data, presentation_id, branding,
                    tenant_id=tenant_id, creative_images=creative_images,
                    user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                    total_slides=len(slides),
                    content_source=slide.get('content_source') or slide.get('contentSource'),
                )
                updated_html = _inject_team_logo_fallback(
                    updated_html, str(team_member.get('logo') or ''), team_index
                )
                slide['html'] = updated_html
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                slides[idx] = slide
                successful_indexes.append(idx)
                if response_text:
                    assistant_messages.append(response_text)
                pct = int(15 + 75 * ((i + 1) / max(1, len(indexes))))
                report_designer_progress(pct, f"تم إدراج الشعار في الشريحة {i + 1} من {len(indexes)}...")
            executed.append({'tool': tool, 'status': 'success' if successful_indexes else 'failed',
                             'indexes': successful_indexes, 'team_index': team_index,
                             'token': team_token})
        elif tool == 'insert_company_logo_panel':
            indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
            company_logo_url = str(
                branding.get('logo_path') or branding.get('logo') or branding.get('logo_url') or '/assets/logo.png'
            ).strip()
            company_instruction = (
                'انقل شعار الشركة المعتمد باستخدام الرمز ##LOGO## إلى داخل المربع الكحلي الموجود في يمين الشريحة، '
                'واجعله فوق رقم سنوات الخبرة مباشرة داخل نفس المربع. لا تستخدم ##TEAM_LOGO_N## ولا شعار جهة من فريق العمل، '
                'ولا تضع الشعار في أعلى يسار الشريحة. حافظ على الرقم 55 وبقية النصوص والتنسيق.'
            )
            successful_indexes = []
            for i, idx in enumerate(indexes):
                slide = slides[idx] if isinstance(slides[idx], dict) else {}
                updated_html, response_text = _designer_edit_slide(
                    slide.get('html', ''), slide.get('title', f'شريحة {idx + 1}'),
                    company_instruction, idx, project_data, presentation_id, branding,
                    tenant_id=tenant_id, creative_images=creative_images,
                    user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                    total_slides=len(slides),
                    content_source=slide.get('content_source') or slide.get('contentSource'),
                )
                updated_html = _inject_company_logo_panel_fallback(updated_html, company_logo_url)
                slide['html'] = updated_html
                slide['_designer_keep_html'] = True
                slide['is_custom'] = True
                slides[idx] = slide
                successful_indexes.append(idx)
                if response_text:
                    assistant_messages.append(response_text)
                pct = int(15 + 75 * ((i + 1) / max(1, len(indexes))))
                report_designer_progress(pct, f"تم وضع الشعار في الشريحة {i + 1} من {len(indexes)}...")
            executed.append({'tool': tool, 'status': 'success' if successful_indexes else 'failed',
                             'indexes': successful_indexes, 'placement': 'right_panel_above_experience_years'})
        elif tool in ('generate_image', 'generate_design_image', 'insert_image_into_slide'):
            prompt = params.get('prompt') or message
            comp_name = params.get('component_name') or params.get('component') or ''
            if not comp_name and current_index < len(slides):
                cur_title = slides[current_index].get('title', '')
                comps = (project_data.get('interior_components') or project_data.get('components') or []) if isinstance(project_data, dict) else []
                for c in comps:
                    c_title = (c.get('name') or c.get('title') or '') if isinstance(c, dict) else ''
                    if c_title and c_title in cur_title:
                        comp_name = c_title
                        break

            ref_images = _find_component_reference_image(comp_name or prompt or message, project_data, creative_images)
            designer_image_ctx = _usage_ctx('image', project_data, presentation_id=presentation_id, tenant_id=tenant_id)
            if ref_images:
                image_raw = call_image_api_with_references(prompt, references=ref_images, usage_ctx=designer_image_ctx)
            else:
                image_raw = call_image_api(prompt, usage_ctx=designer_image_ctx)

            image = persist_generated_image(image_raw, tenant_id)
            if not image:
                raise RuntimeError('تعذر توليد الصورة. تحقق من إعداد OpenRouter ورصيده.')
            targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
            position = params.get('position', 'surgical')
            for idx in targets:
                slide = slides[idx] if isinstance(slides[idx], dict) else {}
                orig_html = slide.get('html', '')
                caption_text = comp_name or prompt[:60]
                caption_markup = f'<div data-visual-media-caption="1" style="font-size:12px;color:#c5a059;margin-top:6px;font-weight:600;text-align:center;">{caption_text}</div>'
                if position in ('surgical', 'inline') or not position:
                    instruction_img = (
                        f"أدرج الصورة الجديدة ({image}) في تصميم الشريحة كعنصر مرئي رئيسي متناسق وجميل مع بطاقة شرح توضيحي ({caption_markup}). "
                        f"حافظ على جميع النصوص والبطاقات واضبط مكان الصورة باحترافية وتوازن بدون أي إيموجي أو أيقونات."
                    )
                    updated_html, r_msg = _designer_edit_slide(
                        orig_html, slide.get('title', f'شريحة {idx + 1}'),
                        instruction_img, idx, project_data, presentation_id, branding,
                        tenant_id=tenant_id, creative_images=creative_images,
                        user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                        total_slides=len(slides),
                        content_source=slide.get('content_source') or slide.get('contentSource'),
                    )
                    slide['html'] = updated_html
                    slide['_designer_keep_html'] = True
                    if r_msg:
                        assistant_messages.append(r_msg)
                elif position == 'background':
                    tag = f'<div aria-hidden="true" style="position:absolute;inset:0;background-image:url(\'{image}\');background-size:cover;background-position:center;z-index:0;"></div>'
                    slide['html'] = re.sub(r'(</div>\s*)$', tag + r'\1', orig_html or '', count=1)
                    slide['_designer_keep_html'] = True
                else:
                    side = 'right:40px' if position != 'left' else 'left:40px'
                    tag = f'<div style="position:absolute;{side};top:120px;width:38%;z-index:2;"><img src="{image}" alt="" style="width:100%;max-height:460px;object-fit:cover;border-radius:8px;">{caption_markup}</div>'
                    slide['html'] = re.sub(r'(</div>\s*)$', tag + r'\1', orig_html or '', count=1)
                    slide['_designer_keep_html'] = True
                slides[idx] = slide
            creative_images.setdefault('generated', []).append(image)
            executed.append({'tool': tool, 'status': 'success', 'indexes': targets, 'image': image})
        elif tool in ('insert_canonical_map', 'insert_map'):
            map_type = str(params.get('map_type') or 'overview').lower()
            refresh_requested = params.get('refresh') is True or params.get('use_latest') is True
            token_map = {
                'overview': ('##MAP_OVERVIEW##', 'خريطة الموقع العام ونظرة جوية للأرض'),
                'access': ('##MAP_ACCESS##', 'خريطة شبكة الطرق والمحاور الرئيسية للوصول'),
                'catchment': ('##MAP_CATCHMENT##', 'خريطة النطاق الجغرافي واستيعاب المنطقة'),
                'landmarks': ('##MAP_LANDMARKS##', 'خريطة المعالم الحيوية والخدمات وأوقات القيادة'),
            }
            token, label = token_map.get(map_type, ('##MAP_OVERVIEW##', 'خريطة الموقع العام'))
            targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
            map_url = (_latest_canonical_map_url(
                map_type, project_data, creative_images,
                tenant_id=tenant_id, presentation_id=presentation_id,
                preferred_images=[request_creative_images, project_creative_images],
            ) if refresh_requested else _approved_canonical_map_url(map_type, project_data, creative_images))
            if not map_url:
                missing_text = (
                    f'لا توجد نسخة محفوظة حديثة من خريطة {label} لتحديثها.'
                    if refresh_requested else
                    f'لا توجد نسخة معتمدة محفوظة من خريطة {label} لإعادة إدراجها؛ لم يتم طلب خريطة جديدة من جوجل.'
                )
                assistant_messages.append(missing_text)
                executed.append({'tool': tool, 'status': 'failed', 'indexes': targets,
                                 'map_type': map_type, 'reason': 'approved_map_missing'})
                continue
            # Saved slides freeze map sources into revision URLs that no
            # longer look like map paths, so the existing slot is found by
            # the canonical attribute and persisted-file marks, not by URL.
            map_marks = _persisted_map_source_marks(
                tenant_id, presentation_id=presentation_id,
                draft_id=None if presentation_id else (
                    project_data.get('draftId') or project_data.get('draft_id')
                    if isinstance(project_data, dict) else None))
            successful_targets = []
            for idx in targets:
                slide = slides[idx] if isinstance(slides[idx], dict) else {}
                updated_html, replaced = _replace_slide_with_approved_map(
                    slide.get('html', ''), map_type, map_url, map_marks=map_marks
                )
                if not replaced:
                    assistant_messages.append(f'تعذر العثور على موضع خريطة {label} في الشريحة رقم {idx + 1}؛ لم يتم تغيير الشريحة.')
                    continue
                updated_html = resolve_designer_chat_placeholders(
                    updated_html, project_data, presentation_id, tenant_id, creative_images
                )
                # A chat map refresh is a source swap, not a slide regeneration.
                # Keep the existing HTML/layout and carry the exact marked image
                # from the project section into the existing map slot.
                slide['html'] = updated_html
                slides[idx] = slide
                successful_targets.append(idx)
            if successful_targets:
                assistant_messages.append(
                    f"تم تحديث خريطة {label} في الشرائح المحددة من أحدث نسخة محفوظة دون توليد نسخة من جوجل."
                    if refresh_requested else
                    f'تمت إعادة إدراج خريطة {label} المعتمدة في الشرائح المحددة دون توليد نسخة من جوجل.'
                )
            executed.append({'tool': tool, 'status': 'success' if successful_targets else 'failed',
                             'indexes': successful_targets, 'map_type': map_type,
                             'source': 'latest_persisted_map' if refresh_requested else 'approved_persisted_map'})
        elif tool == 'update_slide_image':
            # Deterministic project-asset swap: the planner names an exact
            # token from the enumerated asset list, the URL resolves from
            # the current creative state, and the slide's image slot is
            # rewritten in place without a model rebuild.
            raw_asset = str(params.get('asset') or params.get('token')
                            or params.get('placeholder') or params.get('image_token') or '').strip()
            asset_url, asset = _designer_image_asset_url(raw_asset, designer_image_assets)
            targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
            if not asset_url:
                assistant_messages.append(
                    f'لا توجد صورة مشروع بالرمز {raw_asset or "المطلوب"} ضمن الأصول المتاحة؛ لم يتغير العرض.')
                executed.append({'tool': tool, 'status': 'failed', 'indexes': targets,
                                 'asset': raw_asset, 'reason': 'asset_missing'})
                continue
            raw_index = params.get('image_index', params.get('imageIndex'))
            try:
                image_index = int(raw_index) if raw_index not in (None, '') else None
            except (TypeError, ValueError):
                image_index = None
            asset_label = str(asset.get('label') or raw_asset).strip() if isinstance(asset, dict) else raw_asset
            successful_targets = []
            for idx in targets:
                slide = slides[idx] if isinstance(slides[idx], dict) else {}
                updated_html, replaced = _replace_slide_image_with_asset(
                    slide.get('html', ''), asset_url,
                    asset_token=asset['token'], image_index=image_index)
                if not replaced:
                    assistant_messages.append(
                        f'تعذر العثور على موضع صورة في الشريحة رقم {idx + 1}؛ لم يتم تغيير الشريحة.')
                    continue
                updated_html = resolve_designer_chat_placeholders(
                    updated_html, project_data, presentation_id, tenant_id, creative_images)
                slide['html'] = updated_html
                slides[idx] = slide
                successful_targets.append(idx)
            if successful_targets:
                assistant_messages.append(
                    f'تم تحديث الصورة في الشرائح المحددة إلى «{asset_label}» من أصول المشروع دون إعادة تصميم.')
            executed.append({'tool': tool, 'status': 'success' if successful_targets else 'failed',
                             'indexes': successful_targets, 'asset': asset['token'],
                             'source': 'project_asset'})
        elif tool in ('insert_financial_chart', 'update_financial_chart'):
            chart_type = str(params.get('chart_type') or 'waterfall').lower()
            targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
            chart_desc = {
                'waterfall': 'مخطط شلال التدفقات النقدية والأرباح الصافية',
                'sensitivity': 'مخطط تحليل الحساسية للإيرادات ونسب الإشغال',
                'compound_flows': 'مخطط التدفقات التراكمية وصافي القيمة الحالية (NPV)',
                'financing_structure': 'مخطط توزيع هيكل التمويل والنفقات الرأسمالية والتشغيلية',
            }.get(chart_type, 'مخطط التحليل المالي والاستثماري')
            instruction_chart = (
                f"أدرج رسم بياني مالي احترافي متناسق يوضح «{chart_desc}» معتمد على الأرقام والمؤشرات المالية للمشروع. "
                f"حافظ على ألوان الهوية الرسمية (الكحلي الملكي والذهبي الاستثماري) والتباين العالي وخلو الشريحة من أي إيموجي أو أيقونات."
            )
            for idx in targets:
                slide = slides[idx] if isinstance(slides[idx], dict) else {}
                orig_html = slide.get('html', '')
                updated_html, r_msg = _designer_edit_slide(
                    orig_html, slide.get('title', f'شريحة {idx + 1}'),
                    instruction_chart, idx, project_data, presentation_id, branding,
                    tenant_id=tenant_id, creative_images=creative_images,
                    user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                    total_slides=len(slides),
                    content_source=slide.get('content_source') or slide.get('contentSource'),
                )
                slide['html'] = updated_html
                slide['_designer_keep_html'] = True
                slides[idx] = slide
                if r_msg:
                    assistant_messages.append(r_msg)
            executed.append({'tool': tool, 'status': 'success', 'indexes': targets, 'chart_type': chart_type})
        elif tool in ('delete_slide', 'remove_slide'):
            raw_nums = params.get('slide_numbers') or params.get('slide_number') or params.get('slide_index') or params.get('index')
            if not isinstance(raw_nums, list):
                raw_nums = [raw_nums]
            target_nums = [designer_chat_targets.slide_number(value, len(slides)) for value in raw_nums]
            del_indexes = sorted(set(n - 1 for n in target_nums), reverse=True)
            if len(slides) - len(del_indexes) >= 1:
                removed_titles = []
                for d_idx in del_indexes:
                    removed = slides.pop(d_idx)
                    removed_titles.append(f'«{removed.get("title", f"شريحة {d_idx + 1}")}»')
                assistant_messages.append(f'تم حذف {len(del_indexes)} شريحة بنجاح ({", ".join(removed_titles)}).')
                executed.append({'tool': tool, 'status': 'success', 'deleted_indexes': del_indexes})
            else:
                assistant_messages.append('لا يمكن حذف جميع الشرائح المتبقية في العرض.')
                executed.append({'tool': tool, 'status': 'rejected', 'reason': 'single_slide'})
        elif tool in ('duplicate_slide', 'clone_slide'):
            raw_num = params.get('slide_number') or params.get('slide_index') or params.get('index')
            target_num = designer_chat_targets.slide_number(raw_num, len(slides))
            dup_idx = target_num - 1
            cloned = copy.deepcopy(slides[dup_idx])
            cloned['id'] = designer_agent_ids.new_slide_id()
            cloned['duplicated_from'] = slides[dup_idx].get('id')
            cur_title = cloned.get('title', '')
            cloned['title'] = cur_title + ' (نسخة)' if not cur_title.endswith('(نسخة)') else cur_title
            slides.insert(dup_idx + 1, cloned)
            assistant_messages.append(f'تم تكرار الشريحة رقم {target_num} بنجاح.')
            executed.append({'tool': tool, 'status': 'success', 'duplicated_index': dup_idx + 1})
        elif tool in ('reorder_slides', 'move_slide'):
            from_num = params.get('from_index') or params.get('from')
            to_num = params.get('to_index') or params.get('to')
            f_idx = designer_chat_targets.slide_number(from_num, len(slides)) - 1
            t_idx = designer_chat_targets.slide_number(to_num, len(slides)) - 1
            if f_idx == t_idx:
                raise designer_chat_targets.TargetError('موضعا النقل متطابقان؛ لم يتغير العرض.')
            moved = slides.pop(f_idx)
            slides.insert(t_idx, moved)
            assistant_messages.append(f'تم نقل الشريحة من الترتيب {f_idx + 1} إلى الترتيب {t_idx + 1} بنجاح.')
            executed.append({'tool': tool, 'status': 'success', 'from_index': f_idx, 'to_index': t_idx})
        elif tool in ('split_slide', 'split_dense_slide', 'merge_slides', 'combine_slides',
                      'create_slide', 'create_design_slide'):
            import designer_chat_safety

            def render_structure_slide(html, title, instruction, index, kind, total, source):
                return _designer_edit_slide(
                    html, title, instruction, index, project_data, presentation_id, branding,
                    tenant_id=tenant_id, creative_images=creative_images,
                    user_image_refs=user_image_refs, slide_type=kind, total_slides=total,
                    content_source=source,
                )

            structural_result, structural_message = designer_chat_safety.execute_structure(
                tool, params, slides, message, edit_slide=render_structure_slide,
                reliability=designer_chat_reliability, carry_watermark=_carry_slide_watermark,
                progress=report_designer_progress,
            )
            executed.append(structural_result)
            assistant_messages.append(structural_message)
        elif tool in ('regenerate_maps', 'update_map_style', 'change_map_type'):
            maptype = params.get('maptype') or params.get('style') or 'roadmap'
            executed.append({'tool': tool, 'status': 'deferred', 'maptype': maptype})
            assistant_messages.append('لم تتغير خرائط الموقع المعتمدة؛ توليد الخرائط منفصل لكل خريطة.')
        else:
            executed.append({'tool': tool, 'status': 'skipped', 'message': 'أداة غير معروفة'})

    failed_actions = [item for item in executed if item.get('status') in ('failed', 'rejected', 'deferred', 'skipped', 'noop')]
    # All-or-nothing is reserved for structural operations: a failed split or merge
    # must roll back the request because renumbering changed every position. Plain
    # per-slide edits keep whatever succeeded and report the rest.
    structural_failure = any(item.get('tool') in designer_chat_targets.STRUCTURAL_TOOLS for item in failed_actions)
    if structural_failure:
        return jsonify({'success': False, 'error': 'لم يُطبق الطلب لأن عملية هيكلية لم تنجح: '
                        + designer_chat_targets.action_failure_summary(executed),
                        'error_code': 'DESIGNER_ATOMIC_EDIT_FAILED', 'actions': executed, 'slidesData': slides_before}), 422
    structural_change = any(item.get('tool') in designer_chat_targets.STRUCTURAL_TOOLS
                            and item.get('status') == 'success' for item in executed)
    structural_change = structural_change or any(
        isinstance(item, dict) and item.get('tool') == 'insert_attached_image'
        and item.get('status') == 'success' and item.get('position') == 'separate_slide'
        for item in executed)
    if structural_change:
        slides = slide_engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project_data, tenant_id=tenant_id,
            allow_all_maps=True, creative_images=creative_images, preserve_html=True,
        )
    validation = _validate_workspace_data({'slidesData': slides})
    if not validation['valid']:
        return jsonify({'success': False, 'error': 'تم رفض التعديل لأن العرض يحتوي على شرائح غير صالحة', 'validation': validation}), 422
    slide_changes = change_tracking.describe_slide_changes(slides_before, slides)
    touched = [item.get('index') + 1 for item in executed
               if isinstance(item, dict) and isinstance(item.get('index'), int)]
    touched += [n + 1 for item in executed if isinstance(item, dict)
                for n in (item.get('indexes') or []) if isinstance(n, int)]
    touched += [int(item.get('inserted_at')) for item in executed
                if isinstance(item, dict) and isinstance(item.get('inserted_at'), int)]
    turn_focus = sorted(dict.fromkeys(touched)) or focus_indexes
    successful_execution = any(
        isinstance(item, dict) and item.get('status') in ('success', 'partial')
        for item in executed
    )
    failure_reason = None
    if successful_execution:
        response_text = 'تم تطبيق التعديل المطلوب.'
        if assistant_messages:
            response_text += ' ' + ' '.join(dict.fromkeys(assistant_messages))
    else:
        failure_reason = next((
            item.get('reason') for item in executed
            if isinstance(item, dict) and item.get('reason')
        ), 'no_verified_change')
        response_text = 'لم يتم تنفيذ أي تعديل على العرض. ' + designer_chat_targets.action_failure_summary(executed)
    # Return the updated conversation beside the edited workspace. The browser keeps both in
    # memory until the user explicitly presses save; writing here would make a failed edit
    # impossible to discard with a refresh.
    persisted_messages = _normalize_designer_chat_messages(history_for_turn)[-DESIGNER_CHAT_STORED_TURNS * 2:]
    if not persisted_messages or persisted_messages[-1].get('content') != message or persisted_messages[-1].get('role') != 'user':
        persisted_messages.append({'role': 'user', 'content': message[:2000], 'slides': preferred_indexes[:]})
    persisted_messages.append({'role': 'assistant', 'content': response_text[:2000], 'slides': preferred_indexes[:]})
    persisted_project_data = dict(project_data)
    persisted_project_data['tenantSlidesData'] = slides
    persisted_project_data['designerChat'] = {
        'messages': persisted_messages[-DESIGNER_CHAT_STORED_TURNS * 2:],
        'memory': chat_memory,
        'focusIndexes': turn_focus or preferred_indexes,
    }
    # The slides this turn actually touched become the conversation's focus, so the next
    # message («وطلعها أوضح») lands on them without asking again.
    # Both keys carry 0-based indexes; the chat speaks in 1-based slide numbers.
    persisted_project_data['designerChat']['focusIndexes'] = turn_focus
    # ``creative_images`` is the generation view and intentionally aliases
    # editable placeholders to the marked canonical image. Do not send that
    # alias back to the browser: the location editor needs the persisted
    # clean sidecar so its HTML labels are not drawn over raster labels.
    response_creative_images = copy.deepcopy(creative_images)
    source_creative_images = request_creative_images or project_creative_images
    if isinstance(source_creative_images, dict) and isinstance(source_creative_images.get('map_placeholders'), dict):
        returned_placeholders = response_creative_images.get('map_placeholders')
        returned_placeholders = dict(returned_placeholders) if isinstance(returned_placeholders, dict) else {}
        returned_placeholders.update(source_creative_images['map_placeholders'])
        response_creative_images['map_placeholders'] = returned_placeholders
    response_data = {
        'action': 'workspace_update', 'response': response_text,
        'slidesData': slides, 'creativeImages': response_creative_images,
        'actions': executed, 'validation': validation,
        'memory': chat_memory, 'focusIndexes': turn_focus,
        'chatHistory': persisted_project_data['designerChat']['messages'],
        'saved': False,
    }
    if successful_execution and slide_changes:
        response_data['changeSource'] = 'ai'
        response_data['provenance'] = _issue_presentation_provenance(
            slides, presentation_id, int((presentation or {}).get('revision') or 0),
            [f'طلب التصميم: {message[:2000]}'] + [
                f'أداة التصميم: {item.get("tool")}' for item in executed
                if isinstance(item, dict) and item.get('status') == 'success'
            ],
        )
    if failure_reason:
        response_data['failureReason'] = failure_reason
    return jsonify({'success': True, 'data': response_data})
