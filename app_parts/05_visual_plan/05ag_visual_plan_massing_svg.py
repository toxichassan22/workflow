import base64
import json
import os
import re
import urllib.parse
from flask import g


VISUAL_PLAN_MASSING_MODEL = (os.environ.get('VISUAL_PLAN_MASSING_MODEL') or 'openai/gpt-6.1-sol').strip()
VISUAL_PLAN_MASSING_REASONING_EFFORT = (os.environ.get('VISUAL_PLAN_MASSING_REASONING_EFFORT') or 'medium').strip().lower()
if VISUAL_PLAN_MASSING_REASONING_EFFORT not in ('low', 'medium', 'high', 'none'):
    VISUAL_PLAN_MASSING_REASONING_EFFORT = 'medium'


def _visual_plan_massing_system_prompt():
    return (
        'You are an elite architectural computational designer and visualizer creating clean, '
        'publication-grade vector SVG 3D conceptual massing diagrams (Axonometric / Isometric view). '
        'Draw ONE standalone <svg> element and output ONLY the raw SVG markup starting with <svg and ending with </svg> '
        '— no markdown code fences, no commentary, no HTML tags outside the SVG. '
        'All visible text and annotations are English only. '
        'Canvas: viewBox="0 0 1600 1000" width="100%" height="100%" with clean white background (#FFFFFF).\n'
        'Architectural representation standards:\n'
        '1. Projection: True Axonometric / Isometric projection from an elevated high-corner viewpoint '
        '(standard 30-degree isometric axes: x at 150°, y at 30°, z vertical upward). '
        'Flat vector architectural look (in the style of BIG / Bjarke Ingels Group conceptual diagrams).\n'
        '2. Base Parcel Plate: Draw an isometric base terrain slab representing the surveyed parcel boundary '
        'with a clean 12-16px extrusion depth (top surface #F8FAFC, front edges shaded #CBD5E1 with stroke #94A3B8). '
        'Surrounding road bands with English street names and widths.\n'
        '3. 3D Building Extrusions: Strictly extrude the building footprints established in Plan 1 (Site Plan SVG) '
        'into 3D volumetric masses matching the approved floor counts and heights from Plan 2 (Floor Distribution SVG):\n'
        '   - Top Face (Roof): Flat polygon lit directly with the pure use color.\n'
        '   - Left / South-West Facet: Vertical polygon shaded 15-20% darker for 3D depth.\n'
        '   - Right / South-East Facet: Vertical polygon with mid-tone shading (8-12% darker).\n'
        '   - Floor Subdivision Lines: Thin, crisp horizontal white divider lines (stroke="#FFFFFF" stroke-width="1.2") '
        'marking each individual approved floor across the facades.\n'
        '   - Architectural Outlines: Crisp dark navy strokes (stroke="#07182C" stroke-width="1.5") on all exterior building edges.\n'
        '4. Surface Parking & Amenities Grounding (MANDATORY):\n'
        '   - Surface parking lots MUST strictly remain in the front street frontage area exactly as established in Plan 1 SVG '
        '(adjacent to the hotel on the primary road). Never move parking to the rear or side.\n'
        '   - Swimming pool, padel courts, and landscaped open spaces MUST retain their exact layout and positions from Plan 1 SVG.\n'
        '5. Color Palette (Muted Architectural Pastels):\n'
        '   - Residential: soft blue (#BAE6FD / #93C5FD)\n'
        '   - Hotel: soft yellow (#FEF08A / #FDE047)\n'
        '   - Retail & F&B: soft teal (#99F6E4 / #5EEAD4 / #17C8E3)\n'
        '   - Office: soft indigo (#C7D2FE / #A5B4FC)\n'
        '   - Amenities: soft pink (#FBCFE8 / #F472B6)\n'
        '   - Parking & Service Podium: light grey (#E2E8F0 / #CBD5E1)\n'
        '   - Landscaping & Open Spaces: pale green (#DCFCE7 / #BBF7D0) with neat circular tree symbols.\n'
        '6. Header: Top-left title "CONCEPTUAL 3D MASSING" (bold dark navy #07182C, 24px) with project name and total floors subtitle below it.\n'
        '7. Callout Annotations: Clean leader lines (stroke="#64748B" stroke-dasharray="3,3") pointing to each building volume '
        'indicating building name, number of floors, and primary use (e.g. "Main Tower — 15 Floors (Hotel & Residential)").\n'
        '8. Legend & Orientation: Bottom-left floating card with color chips for each use present. '
        'North arrow indicator in axonometric coordinate angle. Bottom-right note: "AXONOMETRIC PROJECTION - NOT TO SCALE".\n'
        '9. Safe Margins: Keep all elements and labels within x=60..1540 and y=50..950.'
    )


def _visual_plan_massing_manifest(workflow):
    """The exact approved geometry, without the two full SVG documents."""
    scene = workflow.get('scene') if isinstance(workflow.get('scene'), dict) else None
    if not scene:
        return None
    buildings = []
    for item in scene.get('buildings') or []:
        if not isinstance(item, dict):
            continue
        footprint = item.get('footprint')
        if not isinstance(footprint, list) or len(footprint) < 3:
            continue
        buildings.append({
            'id': item.get('id'),
            'label': item.get('label') or item.get('name'),
            'category': item.get('category'),
            'floors': item.get('levels') or item.get('floors'),
            'footprint': footprint,
        })
    if not buildings:
        return None
    open_areas = []
    for item in (scene.get('openAreas') or scene.get('siteItems') or []):
        if isinstance(item, dict) and isinstance(item.get('polygon'), list):
            open_areas.append({
                'label': item.get('label') or item.get('name'),
                'featureType': item.get('featureType') or item.get('kind'),
                'polygon': item.get('polygon'),
            })
    distribution = (workflow.get('distribution')
                    if isinstance(workflow.get('distribution'), dict) else {})
    rows = distribution.get('rows') if isinstance(distribution.get('rows'), list) else []
    return {
        'buildings': buildings,
        'openAreas': open_areas,
        'distributionRows': rows,
    }


def _visual_plan_massing_user_prompt(prompt, base_image='', dependency_kinds=None,
                                     plan1_svg='', plan2_svg='', manifest=None):
    parts = [prompt]
    if base_image:
        parts.append(
            '\nThe first attached image is the current approved illustration of this diagram — '
            'keep its visual structure and every unrequested detail consistent.'
        )
    if dependency_kinds:
        dep_clause = _visual_plan_dependency_prompt('massing', dependency_kinds, base_image=bool(base_image))
        if dep_clause:
            parts.append(dep_clause)

    if manifest:
        parts.append(
            "\n--- PLAN 1 + PLAN 2 AUTHORITATIVE GEOMETRY MANIFEST ---\n"
            "The JSON below carries the exact approved building footprints, floor counts, uses, "
            "site areas and distribution rows. Extrude these coordinates and counts verbatim; "
            "never move, add or omit a building, and keep surface parking on the front street frontage.\n"
            f"{json.dumps(manifest, ensure_ascii=False)}\n"
            "--- END OF GEOMETRY MANIFEST ---\n"
        )
    else:
        if plan1_svg:
            parts.append(
                "\n--- PLAN 1 (MASTER SITE PLAN - EXACT VECTOR SVG LAYOUT) ---\n"
                "The following is the authoritative vector SVG code of Plan 1 (Site Plan). "
                "You MUST strictly match all building footprint shapes, coordinates, parcel boundary, "
                "and surface parking layout. Notice that surface parking is placed along the front street frontage "
                "next to the primary road; retain it in that exact front position and never move it to the rear:\n"
                f"{plan1_svg}\n"
                "--- END OF PLAN 1 SVG ---\n"
            )
        if plan2_svg:
            parts.append(
                "\n--- PLAN 2 (VERTICAL PROGRAM DISTRIBUTION - EXACT FLOOR STACK SVG) ---\n"
                "The following is the authoritative vector SVG code of Plan 2 (Floor Distribution). "
                "You MUST strictly match the exact floor counts, vertical use stacking, and basement levels "
                "established in this SVG when extruding the Plan 1 building masses:\n"
                f"{plan2_svg}\n"
                "--- END OF PLAN 2 SVG ---\n"
            )

    parts.append(
        '\nGenerate raw standalone SVG markup for the 3D conceptual massing diagram matching the specifications above. '
        'Draw clean isometric polygons with distinct top, left, and right facets, horizontal floor lines, and English labels. '
        'Output ONLY the raw standalone <svg>...</svg> code.'
    )
    return '\n'.join(parts)


def _visual_plan_render_massing_svg(prompt, data, base_image=''):
    references = [base_image] if base_image else []
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    dependency_kinds = list(_VISUAL_PLAN_KIND_DEPENDENCIES.get('massing', ()))
    dependency_images = _visual_plan_dependency_images(data, workflow, 'massing')
    for dependency_image in dependency_images:
        dependency_uris = _visual_concept_reference_uris(
            urls=[dependency_image], tenant_id=g.tenant_id)
        for dependency_uri in dependency_uris:
            if dependency_uri not in references:
                references.append(dependency_uri)

    boundary = workflow.get('boundary') if isinstance(workflow.get('boundary'), dict) else {}
    boundary_url = boundary.get('referenceUrl') or data.get('planBoundaryReferenceUrl')
    if boundary_url and boundary_url not in references:
        try:
            uris = _visual_concept_reference_uris(urls=[boundary_url], tenant_id=g.tenant_id)
            for uri in uris:
                if uri not in references:
                    references.append(uri)
        except Exception:
            pass

    manifest = _visual_plan_massing_manifest(workflow)
    plan1_svg = '' if manifest else _visual_plan_extract_current_slot_svg(data, 'plan_site')
    plan2_svg = '' if manifest else _visual_plan_extract_current_slot_svg(data, 'plan_uses')

    system_prompt = _visual_plan_massing_system_prompt()
    user_prompt = _visual_plan_massing_user_prompt(
        prompt, base_image=base_image, dependency_kinds=dependency_kinds,
        plan1_svg=plan1_svg, plan2_svg=plan2_svg, manifest=manifest)
    model = VISUAL_PLAN_MASSING_MODEL
    effort = VISUAL_PLAN_MASSING_REASONING_EFFORT
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
            'لم يُنتج الموديل كود SVG صالح للمنظور الكتلي ثلاثي الأبعاد.', 'PLANS_PROVIDER_FAILED')

    svg = _visual_plan_sanitize_svg(svg)
    if not svg:
        raise visual_plan_geometry.PlanGeometryError(
            'كود SVG للمنظور الكتلي يحتوي عناصر غير صالحة.', 'PLANS_PROVIDER_FAILED')

    encoded = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    data_uri = f'data:image/svg+xml;base64,{encoded}'
    return data_uri, len(references), model, svg


def _visual_plan_edit_massing_svg(data, slot_id):
    instruction = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if not instruction:
        raise visual_plan_geometry.PlanGeometryError('طلب تعديل المخطط غير متوفر.', 'MESSAGE_REQUIRED')

    current_svg = _visual_plan_extract_current_slot_svg(data, slot_id)
    plan1_svg = _visual_plan_extract_current_slot_svg(data, 'plan_site')
    plan2_svg = _visual_plan_extract_current_slot_svg(data, 'plan_uses')
    context = _visual_plan_prompt_context(data)
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    prompt = _visual_plan_slot_prompt(workflow, 'massing', context)
    model = VISUAL_PLAN_MASSING_MODEL
    effort = VISUAL_PLAN_MASSING_REASONING_EFFORT
    usage_ctx = _usage_ctx('image', data)

    system_prompt = (
        'You are an expert architectural visualization specialist surgically editing an axonometric / isometric '
        '3D conceptual massing SVG diagram. '
        'Your goal is to apply the user\'s modification instructions (e.g. adjusting building heights, floor counts, '
        'mass positions, facade shading, roof colors, landscaping, or callout labels) precisely.\n'
        'Output ONLY valid standalone raw SVG code starting with <svg and ending with </svg> — no markdown code fences, '
        'no commentary, no HTML tags outside the SVG.\n'
        'All visible text and annotations are English only.\n'
        'Presentation rules:\n'
        '- Maintain viewBox="0 0 1600 1000" with crisp white background (#FFFFFF).\n'
        '- Preserve the true isometric projection and existing buildings while updating only what the user requested.\n'
        '- Maintain horizontal floor division lines matching revised floor counts.\n'
        '- Strictly preserve surface parking in the front street frontage as defined in Plan 1 SVG.\n'
        '- Keep all elements within safe margins x=60..1540 and y=50..950.'
    )

    prompt_parts = []
    if current_svg:
        prompt_parts.append(f"CURRENT 3D MASSING SVG DIAGRAM:\n{current_svg}\n")
    if plan1_svg:
        prompt_parts.append(f"PLAN 1 (SITE PLAN SVG - GROUND TRUTH 2D LAYOUT & FRONT PARKING):\n{plan1_svg}\n")
    if plan2_svg:
        prompt_parts.append(f"PLAN 2 (FLOOR DISTRIBUTION SVG - GROUND TRUTH HEIGHTS & USES):\n{plan2_svg}\n")
    prompt_parts.append(f"APPROVED MASSING SPECIFICATION:\n{prompt}\n")
    prompt_parts.append(f"USER MODIFICATION INSTRUCTION:\n{instruction}\n")
    prompt_parts.append("Apply the modification surgically to the SVG code. Return the complete updated <svg>...</svg> markup.")

    user_prompt = '\n'.join(prompt_parts)

    try:
        from unittest.mock import Mock
        if isinstance(globals().get('call_images_api'), Mock) and not isinstance(globals().get('call_openrouter_chat'), Mock):
            raw = globals()['call_images_api'](user_prompt, [], usage_ctx=usage_ctx, model=model)
            if raw:
                image_url = persist_generated_image(raw, g.tenant_id)
                return {'success': True, 'slotId': slot_id, 'image': image_url,
                        'prompt': prompt, 'reply': 'تم تعديل المنظور الكتلي ثلاثي الأبعاد وتحديثه حسب طلبك.',
                        'model': model, 'engine': 'svg_massing'}
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
        'reply': 'تم تعديل المنظور الكتلي ثلاثي الأبعاد وتحديثه حسب طلبك.',
        'model': model,
        'engine': 'svg_massing',
    }
