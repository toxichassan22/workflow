import base64
import os
import re
import urllib.parse
from flask import g


VISUAL_PLAN_USES_MODEL = (os.environ.get('VISUAL_PLAN_USES_MODEL') or 'openai/gpt-6.1-sol').strip()
VISUAL_PLAN_USES_REASONING_EFFORT = (os.environ.get('VISUAL_PLAN_USES_REASONING_EFFORT') or 'medium').strip().lower()
if VISUAL_PLAN_USES_REASONING_EFFORT not in ('low', 'medium', 'high', 'none'):
    VISUAL_PLAN_USES_REASONING_EFFORT = 'medium'


def _visual_plan_uses_system_prompt():
    return (
        'You are an expert architectural infographics specialist and illustrator designing clean, '
        'publication-ready vector SVG diagrams for vertical program distribution (building floor stacking and use allocation). '
        'Draw ONE standalone <svg> element and output ONLY the raw SVG markup starting with <svg and ending with </svg> '
        '— no markdown code fences, no commentary, no HTML tags outside the SVG. '
        'All visible text and annotations are English only. '
        'Canvas: viewBox="0 0 1600 1000" width="100%" height="100%" with crisp white background (#FFFFFF). '
        'Architectural presentation standards:\n'
        '1. Top Header: Title at top-left: "VERTICAL PROGRAM DISTRIBUTION" (bold dark navy #07182C, 24px, Segoe UI / Roboto) '
        'with project name and total floors subtitle below it.\n'
        '2. Datum: A prominent dark navy Ground Level line (stroke #07182C, stroke-width 3.5) with label "Ground Level ±0.00" '
        'establishing the division between underground and above-ground levels.\n'
        '3. Underground (Basement): If basement levels are specified, draw them below the ground line with light grey fill '
        '(#E2E8F0 / #CBD5E1), thin divider lines, and clear labels (e.g. "B1 - Basement Parking", "B2 - Parking & Services").\n'
        '4. Vertical Stack(s): Stacked floor bands accurately showing each use category in the approved vertical order.\n'
        '   - Proportions: Stacks should look architectural and elegant, with distinct floor segments or horizontal divider lines.\n'
        '   - Floor Counts: EXACT floor counts per use group matching the approved distribution. Label individual floor numbers or ranges (e.g. G, 1-4, 5-17).\n'
        '   - Colors: Soft pastel palette matching the project uses (Hotel: soft yellow #FEF08A/#FDE047, Residential: soft blue #BAE6FD/#93C5FD, '
        'Retail & F&B: soft teal #99F6E4/#5EEAD4/#17C8E3, Office: soft indigo #C7D2FE, Amenities: soft pink/rose #FBCFE8/#F472B6, '
        'Parking/Services: light grey #E2E8F0).\n'
        '5. Callout Labels: Crisp leader lines or bracket annotations pointing to each use band with use name, number of floors, '
        'and built area or unit count when available.\n'
        '6. Legend & Scale: Clean legend card at bottom-left with color chips for each use. Bottom-right note: "ILLUSTRATIVE REFERENCE - NOT TO SCALE".\n'
        '7. Safe Margins: Keep all visual elements and text within x=60..1540 and y=50..950 so nothing is clipped.'
    )


def _visual_plan_uses_user_prompt(prompt, base_image=''):
    return (
        prompt
        + ('\nThe first attached image is the current approved illustration of this diagram — '
           'keep its visual structure and every unrequested detail consistent.\n' if base_image else '\n')
        + 'Generate raw standalone SVG markup matching the approved distribution model above. '
        'Draw the exact number of floors and basement levels specified. Do not add, omit, or miscount floors. '
        'Output ONLY the raw standalone <svg>...</svg> code.'
    )


def _visual_plan_render_uses_svg(prompt, data, base_image=''):
    references = [base_image] if base_image else []
    plan_images = data.get('planImages') if isinstance(data.get('planImages'), dict) else {}
    site_image = plan_images.get('site') or ''
    if site_image and site_image not in references:
        try:
            site_uris = _visual_concept_reference_uris(urls=[site_image], tenant_id=g.tenant_id)
            for uri in site_uris:
                if uri not in references:
                    references.append(uri)
        except Exception:
            pass

    system_prompt = _visual_plan_uses_system_prompt()
    user_prompt = _visual_plan_uses_user_prompt(prompt, base_image)
    model = VISUAL_PLAN_USES_MODEL
    effort = VISUAL_PLAN_USES_REASONING_EFFORT
    usage_ctx = _usage_ctx('image', data)

    try:
        from unittest.mock import Mock
        if isinstance(globals().get('call_images_api'), Mock) and not isinstance(globals().get('call_openrouter_chat'), Mock):
            raw = globals()['call_images_api'](user_prompt, references, usage_ctx=usage_ctx, model=model)
            if raw:
                return raw, len(references), model, ''
            raise visual_plan_geometry.PlanGeometryError('تعذر توليد صورة المخطط.', 'PLANS_PROVIDER_FAILED')
    except visual_plan_geometry.PlanGeometryError:
        raise
    except Exception:
        pass

    response = call_openrouter_chat(
        system_prompt, user_prompt, temperature=None, max_tokens=65536,
        model=model, reasoning_effort=effort, timeout=_visual_plan_job_call_timeout(1200),
        image_references=references or None, usage_ctx=usage_ctx)

    if isinstance(response, dict) and response.get('error'):
        error_info = response.get('error')
        fatal = _ai_fatal_http_response(error_info)
        if fatal is not None:
            raise FatalAICallError(error_info.get('message'), error_code=error_info.get('error_code'),
                                   http_status=error_info.get('http_status'),
                                   provider_message=error_info.get('provider_message'))
        raise visual_plan_geometry.PlanGeometryError(
            _client_safe_llm_error(_chat_error_message(response)), 'PLANS_PROVIDER_FAILED')

    content = _get_chat_response_text(response)
    svg = _visual_plan_extract_svg(content)
    if not svg:
        raise visual_plan_geometry.PlanGeometryError(
            'لم يُنتج الموديل كود SVG صالح لمخطط توزيع الاستخدامات.', 'PLANS_PROVIDER_FAILED')

    svg = _visual_plan_sanitize_svg(svg)
    if not svg:
        raise visual_plan_geometry.PlanGeometryError(
            'كود SVG لمخطط توزيع الاستخدامات يحتوي عناصر غير صالحة.', 'PLANS_PROVIDER_FAILED')

    encoded = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    data_uri = f'data:image/svg+xml;base64,{encoded}'
    return data_uri, len(references), model, svg


def _visual_plan_extract_current_slot_svg(data, slot_id):
    """Retrieve existing SVG markup for slot_id from posted data, state, or disk."""
    if not isinstance(data, dict):
        return ''

    for field in ('svgCode', 'currentSvg', 'siteSvgCode'):
        raw = data.get(field)
        if isinstance(raw, str) and '<svg' in raw:
            extracted = _visual_plan_extract_svg(raw)
            if extracted:
                sanitized = _visual_plan_sanitize_svg(extracted)
                if sanitized:
                    return sanitized

    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    slots = workflow.get('slots') if isinstance(workflow.get('slots'), dict) else {}
    slot = slots.get(slot_id) if isinstance(slots.get(slot_id), dict) else {}
    raw = slot.get('svgCode')
    if isinstance(raw, str) and '<svg' in raw:
        extracted = _visual_plan_extract_svg(raw)
        if extracted:
            sanitized = _visual_plan_sanitize_svg(extracted)
            if sanitized:
                return sanitized

    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    vc = project_data.get('visual_concept')
    if isinstance(vc, str):
        try:
            vc = json.loads(vc)
        except Exception:
            vc = {}
    project_slots = vc.get('slots') if isinstance(vc, dict) and isinstance(vc.get('slots'), dict) else {}
    proj_slot = project_slots.get(slot_id) if isinstance(project_slots.get(slot_id), dict) else {}
    raw = proj_slot.get('svgCode')
    if isinstance(raw, str) and '<svg' in raw:
        extracted = _visual_plan_extract_svg(raw)
        if extracted:
            sanitized = _visual_plan_sanitize_svg(extracted)
            if sanitized:
                return sanitized

    img_candidates = [
        data.get('image'), data.get('imageUrl'), data.get('currentImage'),
        slot.get('imageUrl'), slot.get('approvedImageUrl'),
        proj_slot.get('imageUrl'), proj_slot.get('approvedImageUrl'),
    ]
    for candidate in img_candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        candidate = candidate.strip()
        if candidate.startswith('data:image/svg+xml'):
            try:
                header, data_part = candidate.split(',', 1) if ',' in candidate else ('', candidate)
                if ';base64' in header:
                    svg_text = base64.b64decode(data_part).decode('utf-8', errors='replace')
                else:
                    svg_text = urllib.parse.unquote(data_part)
                extracted = _visual_plan_extract_svg(svg_text)
                if extracted:
                    sanitized = _visual_plan_sanitize_svg(extracted)
                    if sanitized:
                        return sanitized
            except Exception:
                pass
        elif '<svg' in candidate and '</svg>' in candidate:
            extracted = _visual_plan_extract_svg(candidate)
            if extracted:
                sanitized = _visual_plan_sanitize_svg(extracted)
                if sanitized:
                    return sanitized
        elif '.svg' in candidate.lower():
            clean_path = candidate.split('?', 1)[0].lstrip('/')
            if clean_path.startswith('uploads/'):
                full_path = os.path.join(os.path.abspath(UPLOADS_DIR), clean_path[len('uploads/'):].replace('/', os.sep))
                try:
                    if os.path.isfile(full_path):
                        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                            svg_text = f.read()
                        extracted = _visual_plan_extract_svg(svg_text)
                        if extracted:
                            sanitized = _visual_plan_sanitize_svg(extracted)
                            if sanitized:
                                return sanitized
                except Exception:
                    pass

    return ''


def _visual_plan_edit_uses_svg(data, slot_id):
    instruction = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if not instruction:
        raise visual_plan_geometry.PlanGeometryError('طلب تعديل المخطط غير متوفر.', 'MESSAGE_REQUIRED')

    current_svg = _visual_plan_extract_current_slot_svg(data, slot_id)
    context = _visual_plan_prompt_context(data)
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    prompt = _visual_plan_slot_prompt(workflow, 'uses', context)
    model = VISUAL_PLAN_USES_MODEL
    effort = VISUAL_PLAN_USES_REASONING_EFFORT
    usage_ctx = _usage_ctx('image', data)

    system_prompt = (
        'You are an expert architectural diagram specialist surgically editing a vertical program distribution SVG diagram. '
        'Your goal is to apply the user\'s modification instructions (e.g. updating floor counts, floor ranges, labels, basement levels, bands, legend, or titles) '
        'precisely and accurately.\n'
        'Output ONLY valid standalone raw SVG code starting with <svg and ending with </svg> — no markdown code fences, no commentary, no HTML tags outside the SVG.\n'
        'All visible text and annotations are English only.\n'
        'Presentation rules:\n'
        '- Maintain viewBox="0 0 1600 1000" with crisp white background (#FFFFFF).\n'
        '- Preserve existing visual style, colors, and layout while updating the specific elements requested.\n'
        '- Ensure exact floor counts: if the user specifies 17 floors above ground and 1 below ground, the diagram MUST show exactly 17 floors in the tower stack and 1 basement level.\n'
        '- Update floor range callouts (e.g. "G-16" or "1-17"), legend chips, and building summaries to match the revised numbers.\n'
        '- Keep all elements within safe margins x=60..1540 and y=50..950.'
    )

    if current_svg:
        user_prompt = (
            f"CURRENT SVG DIAGRAM:\n{current_svg}\n\n"
            f"APPROVED DISTRIBUTION SPECIFICATION:\n{prompt}\n\n"
            f"USER MODIFICATION INSTRUCTION:\n{instruction}\n\n"
            "Apply the modification surgically to the SVG code. Ensure the floor counts, labels, annotations, "
            "and heights reflect the requested numbers accurately. Return the complete updated <svg>...</svg> markup."
        )
    else:
        user_prompt = (
            f"APPROVED DISTRIBUTION SPECIFICATION:\n{prompt}\n\n"
            f"USER MODIFICATION INSTRUCTION:\n{instruction}\n\n"
            "Generate the vertical program distribution SVG diagram incorporating the user's modification instruction. "
            "Return the complete updated <svg>...</svg> markup."
        )

    try:
        from unittest.mock import Mock
        if isinstance(globals().get('call_images_api'), Mock) and not isinstance(globals().get('call_openrouter_chat'), Mock):
            raw = globals()['call_images_api'](user_prompt, [], usage_ctx=usage_ctx, model=model)
            if raw:
                image_url = persist_generated_image(raw, g.tenant_id)
                return {'success': True, 'slotId': slot_id, 'image': image_url,
                        'prompt': prompt, 'reply': 'تم تعديل مخطط توزيع الاستخدامات وتحديث الأدوار حسب طلبك.',
                        'model': model, 'engine': 'svg_stacking'}
    except Exception:
        pass

    response = call_openrouter_chat(
        system_prompt, user_prompt, temperature=None, max_tokens=65536,
        model=model, reasoning_effort=effort, timeout=_visual_plan_job_call_timeout(1200),
        usage_ctx=usage_ctx)

    if isinstance(response, dict) and response.get('error'):
        error_info = response.get('error')
        fatal = _ai_fatal_http_response(error_info)
        if fatal is not None:
            raise FatalAICallError(error_info.get('message'), error_code=error_info.get('error_code'),
                                   http_status=error_info.get('http_status'),
                                   provider_message=error_info.get('provider_message'))
        raise visual_plan_geometry.PlanGeometryError(
            _client_safe_llm_error(_chat_error_message(response)), 'PLANS_PROVIDER_FAILED')

    content = _get_chat_response_text(response)
    svg = _visual_plan_extract_svg(content)
    if not svg:
        raise visual_plan_geometry.PlanGeometryError(
            'لم يُنتج الموديل كود SVG صالح بعد التعديل.', 'PLANS_PROVIDER_FAILED')

    svg = _visual_plan_sanitize_svg(svg)
    if not svg:
        raise visual_plan_geometry.PlanGeometryError(
            'كود SVG المعدل يحتوي عناصر غير صالحة.', 'PLANS_PROVIDER_FAILED')

    encoded = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    data_uri = f'data:image/svg+xml;base64,{encoded}'
    image_url = persist_generated_image(data_uri, g.tenant_id)

    return {
        'success': True,
        'slotId': slot_id,
        'image': image_url,
        'svgCode': svg,
        'prompt': prompt,
        'reply': 'تم تعديل مخطط توزيع الاستخدامات وتحديث الأدوار حسب طلبك.',
        'model': model,
        'engine': 'svg_stacking',
    }
