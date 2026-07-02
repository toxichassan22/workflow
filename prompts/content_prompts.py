"""
Content Prompts – generates outlines and individual slide contents with strict structural rules.
"""

def generate_outline_prompt(context_data: str | dict, num_slides: int | str) -> tuple[str, str]:
    custom_instructions = ""
    if isinstance(context_data, dict):
        custom_instructions = context_data.get("custom_instructions") or ""
    elif isinstance(context_data, str):
        # Fallback search if context_data is dumped as a string
        import re
        match = re.search(r"'custom_instructions':\s*'([^']*)'", context_data)
        if match:
            custom_instructions = match.group(1)

    custom_instructions_rule = ""
    if custom_instructions:
        custom_instructions_rule = (
            "\nCRITICAL CUSTOM USER INSTRUCTIONS (MANDATORY):\n"
            "The user has specified these custom rules/instructions for generating the presentation outline. "
            "You MUST strictly apply and obey them across all outline structures and slide types:\n"
            f"<<< {custom_instructions} >>>\n\n"
        )

    layout_rules = (
        "LAYOUT VARIETY & FLOW RULES (MANDATORY):\n"
        "- Do NOT use 'standard' slides repeatedly. You must design a premium, highly diverse layout flow.\n"
        "- If the project data contains budgets, financial allocations, project costs, or investment details, you MUST use at least one 'chart' slide (which renders as a beautiful native data table).\n"
        "- If the project data describes development timeline, execution schedule, or construction phases, you MUST use at least one 'timeline' slide.\n"
        "- If there is a market or competitor analysis, competitive advantages, or risks, you MUST use at least one 'swot' slide.\n"
        "- If there is a location description, site details, boundaries, surroundings, or land shape details, you MUST use at least one 'map' slide.\n"
        "- Use 'section_header' to demarcate major parts of the proposal (e.g., introduction, technical details, financial details) if the presentation has 8 or more slides.\n"
        "- Use 'two_column' slides to compare features or list highlights side-by-side.\n"
        "- Design a logical flow: cover -> section_header/standard -> map -> two_column/standard -> swot -> timeline -> chart -> closing.\n"
        "- IMPORTANT: Set 'requires_image' to true for the Cover slide, and also for up to 3 other content slides (making 4 total slides with images). Do NOT set requires_image on more than 4 slides. Choose the most visually impactful content slides for images."
    )

    if str(num_slides).lower() == "auto":
        system = (
            "You are an expert real estate presentation architect. "
            "Your job is to structure a compelling, high-end proposal.\n\n"
            f"{custom_instructions_rule}"
            "CRITICAL SOURCE OF TRUTH (MANDATORY):\n"
            "- The client's uploaded document (provided under 'Reference documents' in the context data) is your ABSOLUTE PRIMARY SOURCE OF TRUTH.\n"
            "- You MUST read the document text carefully and extract actual floors, boundaries, financial numbers, and key facts directly from it.\n"
            "- The outline MUST strictly reflect the actual project facts inside the uploaded document with 100% adherence and zero hallucination. If the document describes specific floors, your outline slides MUST map to those exact floors.\n\n"
            "CRITICAL RULES FOR STRUCTURE & ADHERENCE:\n"
            "1. STRICT SLIDE MAPPING & CONTENT DENSITY: You MUST carefully read the provided project data, especially 'توزيع الأدوار' (floor distribution) and 'الوصف' (description).\n"
            "2. OPTIMAL SLIDE COUNT & LOGICAL FLOOR GROUPING: Analyze the input and determine the OPTIMAL number of slides needed to cover everything comfortably. If the number of floors is large, group them logically (e.g., 'الأدوار 1-7', 'المحلات التجارية'). ALL floors specified in the project data MUST be completely covered. DO NOT skip or omit any floor!\n"
            "3. Every floor slide MUST be labeled clearly in Arabic reflecting the floor or group of floors.\n"
            "4. IMAGE REQUIREMENT: Set 'requires_image': true for the Cover slide, and also for up to 3 other content slides that are most visually important (e.g., exterior rendering, interior, site overview). Do NOT set 'requires_image': true on more than 4 slides in total. Write a highly descriptive English 'image_prompt' for each slide that has 'requires_image': true.\n"
            f"5. {layout_rules}\n"
            "6. Output ONLY a valid JSON object. DO NOT wrap it in ```json fences. DO NOT output any other text."
        )
        
        user = (
            "Create an outline for a real estate presentation based on this data. Use the OPTIMAL number of slides to ensure full coverage without crowding:\n"
            f"{context_data}\n\n"
            "Return EXACTLY this JSON structure:\n"
            "{\n"
            "  \"slides\": [\n"
            "    {\"slide_type\": \"cover\", \"topic\": \"Title of Slide in Arabic\", \"requires_image\": true, \"image_prompt\": \"Detailed English prompt...\"},\n"
            "    ... (generate as many slides as needed)\n"
            "  ]\n"
            "}\n"
            "Allowed slide_type: [cover, section_header, standard, two_column, timeline, swot, map, chart, closing]."
        )
        return system, user

    system = (
        "You are an expert real estate presentation architect. "
        "Your job is to structure a compelling, high-end proposal into a specific number of slides.\n\n"
        f"{custom_instructions_rule}"
        "CRITICAL SOURCE OF TRUTH (MANDATORY):\n"
        "- The client's uploaded document (provided under 'Reference documents' in the context data) is your ABSOLUTE PRIMARY SOURCE OF TRUTH.\n"
        "- You MUST read the document text carefully and extract actual floors, boundaries, financial numbers, and key facts directly from it.\n"
        "- The outline MUST strictly reflect the actual project facts inside the uploaded document with 100% adherence and zero hallucination. If the document describes specific floors, your outline slides MUST map to those exact floors.\n\n"
        "CRITICAL RULES FOR STRUCTURE & ADHERENCE:\n"
        "1. STRICT SLIDE MAPPING & CONTENT DENSITY: You MUST carefully read the provided project data, especially 'توزيع الأدوار' (floor distribution) and 'الوصف' (description).\n"
        "2. LOGICAL FLOOR GROUPING: If the number of specified floors or sections is larger than the requested slide count ({num_slides}), you MUST group the floors/sections logically (e.g., 'الأدوار 1-7', 'الأدوار 8-15', 'الأدوار 16-20', or group them by function like 'المحلات التجارية والخدمات', 'المكاتب الإدارية', 'الشقق السكنية') so that ALL floors specified in the project data are completely covered across the slides. DO NOT skip or omit any floor under any circumstance! If the slide count allows, you may dedicate one slide per floor.\n"
        "3. Every floor slide MUST be labeled clearly in Arabic reflecting the floor or group of floors (e.g., 'الدور الأرضي: [اسم مختصر]', 'الدور الأول: [اسم مختصر]', 'السطح (الروف): [اسم مختصر]', 'الأدوار 1-10: [تفاصيل]').\n"
        "4. IMAGE REQUIREMENT & SUGGESTED PROMPTS: Set 'requires_image': true for the Cover slide, and also for up to 3 other content slides that are most visually important (exterior, interior, site). CRITICAL: Do NOT set 'requires_image': true on more than 4 slides in total. For every slide with 'requires_image': true, you MUST write a highly descriptive English image prompt under the key 'image_prompt' (e.g. 'A photorealistic architectural visualization of...').\n"
        f"5. {layout_rules}\n"
        "6. EXACT SLIDE COUNT (NO EXCEPTIONS): The total number of generated slides in the JSON array MUST BE EXACTLY {num_slides}. Not one more, not one less. If you are asked for {num_slides}, you MUST return exactly {num_slides} items in the JSON array. Add 'cover', 'section_header', or 'closing' slides as necessary to hit the exact number while ensuring all requested floors are fully mapped.\n"
        "7. Output ONLY a valid JSON object. DO NOT wrap it in ```json fences. DO NOT output any other text."
    ).replace("{num_slides}", str(num_slides))
    
    user = (
        f"Create an outline for EXACTLY a {num_slides}-slide real estate presentation based on this data:\n"
        f"{context_data}\n\n"
        "Return EXACTLY this JSON structure:\n"
        "{\n"
        "  \"slides\": [\n"
        "    {\"slide_type\": \"cover\", \"topic\": \"Title of Slide in Arabic\", \"requires_image\": true, \"image_prompt\": \"Detailed English prompt for Flux image generator...\"},\n"
        "    ... (generate EXACTLY {num_slides} objects)\n"
        "  ]\n"
        "}\n"
        "Allowed slide_type: [cover, section_header, standard, two_column, timeline, swot, map, chart, closing]."
    ).replace("{num_slides}", str(num_slides))
    return system, user


def generate_slide_content_prompt(slide_spec: dict, project_data: dict) -> tuple[str, str]:
    layout = slide_spec.get("slide_type", "standard")
    topic = slide_spec.get("topic", "شريحة")
    req_image = slide_spec.get("requires_image", False)
    density = project_data.get("density_preference", "Detailed") # Default to Detailed for premium results
    
    custom_instructions = project_data.get("custom_instructions") or ""
    custom_instructions_rule = ""
    if custom_instructions:
        custom_instructions_rule = (
            "\nCRITICAL CUSTOM USER INSTRUCTIONS (MANDATORY):\n"
            "The user has specified these custom rules/instructions for generating the presentation slide content. "
            "You MUST strictly apply, obey, and manifest them in this slide's title, descriptions, tables, or bullets:\n"
            f"<<< {custom_instructions} >>>\n\n"
        )
    
    section = slide_spec.get("section")
    structured_data = project_data.get("structured_project_data")
    
    if section and structured_data:
        system = (
            "You are a professional real estate proposal writer for 'شركة منافع الاقتصادية للعقار'. "
            "Write in Arabic (using professional investment and commercial terms). "
            f"{custom_instructions_rule}"
            "You must write extremely comprehensive and detailed slide content based on the EXACT inputs provided. "
            "DO NOT add random hallucinations or filler information. Focus on presenting the user's data beautifully, "
            "cohesively, and in a high-end corporate format. "
            "Output ONLY valid JSON matching the requested schema exactly."
        )
        
        user_parts = [
            f"Write the slide content for section: {section} (Topic: {topic})",
            "Based on the following EXACT structured inputs entered by the user:"
        ]
        
        if section == "cover":
            cover_types = structured_data.get('cover_project_type', [])
            if isinstance(cover_types, list):
                cover_types_str = " / ".join(cover_types)
            else:
                cover_types_str = str(cover_types)
            cover_custom = structured_data.get('cover_project_type_custom', '')
            if cover_custom:
                cover_types_str += f" / {cover_custom}"
            user_parts.append(
                f"- اسم المشروع/الدراسة: {structured_data.get('cover_project_name')}\n"
                f"- نوع المشروع: {cover_types_str}\n"
                f"- موقع المشروع: {structured_data.get('cover_location')}\n"
                f"- اسم العميل: {structured_data.get('cover_client_name')}\n"
                f"- تاريخ الإصدار: {structured_data.get('cover_date')}"
            )
            user_parts.append("Format as: {\"title\": \"[Project Name]\", \"subtitle\": \"[Type | Location | Client | Date]\"}")
            
        elif section == "introduction":
            user_parts.append(
                f"- اسم العميل: {structured_data.get('intro_client_name')}\n"
                f"- وصف المشروع: {structured_data.get('intro_brief_desc')}\n"
                f"- الهدف من الدراسة: {structured_data.get('intro_goal')} {structured_data.get('intro_goal_custom', '')}\n"
                f"- رقم الأرض/المخطط: {structured_data.get('intro_plot_number')}\n"
                f"- المدينة/الحي: {structured_data.get('intro_location_details')}\n"
                f"- مساحة الأرض: {structured_data.get('intro_land_area')}"
            )
            user_parts.append("Format as standard: {\"title\": \"المقدمة وأهداف الدراسة\", \"description\": \"Write a beautiful, detailed, professional 2-3 paragraph introductory text incorporating all these details perfectly in fluent, elegant Arabic.\"}")
            
        elif section == "executive_summary":
            components_str = ", ".join(structured_data.get('exec_components', []))
            if structured_data.get('exec_components_custom'):
                components_str += f", {structured_data.get('exec_components_custom')}"
            exec_types = structured_data.get('exec_project_type', [])
            if isinstance(exec_types, list):
                exec_types_str = " / ".join(exec_types)
            else:
                exec_types_str = str(exec_types)
            user_parts.append(
                f"- نوع المشروع المقترح: {exec_types_str}\n"
                f"- مكونات المشروع: {components_str}\n"
                f"- مساحة الأرض: {structured_data.get('exec_land_area')}\n"
                f"- المساحة المبنية: {structured_data.get('exec_built_area')}\n"
                f"- المساحة التأجيرية: {structured_data.get('exec_leasable_area')}\n"
                f"- عدد الوحدات: {structured_data.get('exec_units_count')}\n"
                f"- مدة التطوير: {structured_data.get('exec_duration')}\n"
                f"- استراتيجية التخارج: {structured_data.get('exec_exit_strategy')}\n"
                f"- المؤشرات المالية: {structured_data.get('exec_financial_indicators')}"
            )
            user_parts.append("Format as two_column: {\"title\": \"الملخص التنفيذي للمقترح\", \"bullets\": [\"نوع المشروع ومكوناته بالتفصيل\", \"مساحة الأرض والمساحات المبنية والتأجيرية المقترحة\", \"الطاقة الاستيعابية وعدد الوحدات والتشغيل المتوقع\", \"استراتيجية التخارج والجدوى الاستثمارية المستهدفة\", \"أبرز المؤشرات المالية المتوقعة للمشروع\"]}")
            
        elif section == "site_analysis":
            user_parts.append(
                f"- وصف الموقع: {structured_data.get('site_desc')}\n"
                f"- الشوارع المحيطة: {structured_data.get('site_streets')}\n"
                f"- سهولة الوصول: {structured_data.get('site_accessibility')}\n"
                f"- المداخل والمخارج: {structured_data.get('site_entrances')}\n"
                f"- مستوى الحركة المرورية: {structured_data.get('site_traffic_level')}\n"
                f"- ملاحظات الحركة: {structured_data.get('site_traffic_notes')}\n"
                f"- مميزات الموقع: {structured_data.get('site_strengths')}\n"
                f"- تحديات الموقع: {structured_data.get('site_challenges')}"
            )
            user_parts.append("Format as two_column: {\"title\": \"تحليل الموقع والوصول\", \"bullets\": [\"وصف موقع الأرض والشوارع المحيطة بها بالتفصيل\", \"سهولة الوصول والمداخل والمخارج والحركة المرورية للموقع\", \"أبرز المزايا الاستراتيجية التي يتمتع بها الموقع الجغرافي\", \"أبرز التحديات المرصودة وكيفية التعامل معها للتطوير\"]}")
            
        elif section == "surrounding_landmarks":
            landmarks_type_str = ", ".join(structured_data.get('surr_landmark_type', []))
            user_parts.append(
                f"- المعالم المحيطة: {structured_data.get('surr_landmarks')}\n"
                f"- نوع المعالم: {landmarks_type_str}\n"
                f"- الاتجاه الغالب: {structured_data.get('surr_landmark_direction')}"
            )
            user_parts.append("Format as standard: {\"title\": \"المعالم المحيطة ومحيط الجذب\", \"description\": \"Write a comprehensive, professional description of the surroundings, analyzing how these landmarks (types: ...) located in the ... direction enhance the commercial value and foot traffic of our project.\"}")
            
        elif section == "nearby_landmarks":
            user_parts.append(
                f"- المعالم القريبة: {structured_data.get('near_landmarks')}\n"
                f"- مدة الوصول: {structured_data.get('near_travel_time')}\n"
                f"- نوع المعلم الغالب: {structured_data.get('near_landmark_type')}"
            )
            user_parts.append(
                "Format as timeline slide. Create 3 to 5 phases, each representing one of the major landmarks along with its travel time and a professional description of its significance to our property site. "
                "Format: {\"title\": \"المعالم القريبة ومدة الوصول\", \"phases\": [{\"name\": \"Landmark Name\", \"duration\": \"Travel Time\", \"description\": \"Professional significance...\"}]}"
            )
            
        elif section == "site_characteristics":
            infra_str = ", ".join(structured_data.get('char_infrastructure', []))
            user_parts.append(
                f"- مخطط رقم: {structured_data.get('char_plot_map')}\n"
                f"- قطعة رقم: {structured_data.get('char_plot_num')}\n"
                f"- مساحة الأرض: {structured_data.get('char_land_area')}\n"
                f"- نظام البناء: {structured_data.get('char_building_sys')}\n"
                f"- شكل الأرض: {structured_data.get('char_shape')}\n"
                f"- المناسيب: {structured_data.get('char_levels')}\n"
                f"- البنية التحتية المتوفرة: {infra_str}\n"
                f"- ملاحظات إضافية: {structured_data.get('char_additional_notes')}"
            )
            user_parts.append("Format as two_column: {\"title\": \"خصائص الموقع ونظم البناء\", \"bullets\": [\"مخطط رقم ... وقطعة رقم ...\", \"مساحة الأرض: ...\", \"شكل الأرض ... ومناسيبها ...\", \"نظام البناء والارتدادات: ...\", \"البنية التحتية المتوفرة: ...\", \"ملاحظات إضافية وجغرافية: ...\"]}")
            
        elif section == "site_images":
            user_parts.append(
                f"- اتجاه الصور: {structured_data.get('site_images_direction')}\n"
                f"- وصف الصور: {structured_data.get('site_images_desc')}"
            )
            user_parts.append("Format as standard: {\"title\": \"صور ولقطات الموقع الفعلية\", \"description\": \"Detailed description of the actual land pictures and aerial views capturing the site from the ... direction. Text: ...\"}")
            
        elif section == "site_visits":
            user_parts.append(
                f"- تاريخ الزيارة: {structured_data.get('visit_date')}\n"
                f"- الملاحظات المرصودة: {structured_data.get('visit_observations')}\n"
                f"- نوع الملاحظة الغالب: {structured_data.get('visit_observation_type')}\n"
                f"- مستوى الأثر: {structured_data.get('visit_impact_level')}"
            )
            user_parts.append("Format as standard: {\"title\": \"تقرير الزيارة الميدانية وتوصياتها\", \"description\": \"Write a comprehensive real estate site visit report dated ... detailing key observations about ... with a ... impact level on the overall feasibility. Formulate as a polished corporate analysis.\"}")
            
        elif section == "key_brands":
            brands_act_str = ", ".join(structured_data.get('brands_activity', []))
            user_parts.append(
                f"- العلامات القريبة: {structured_data.get('brands_names')}\n"
                f"- تصنيف الأنشطة: {brands_act_str}\n"
                f"- ملاحظات النشاط التجاري: {structured_data.get('brands_notes')}"
            )
            user_parts.append("Format as two_column: {\"title\": \"تحليل العلامات التجارية بالمنطقة\", \"bullets\": [\"العلامات التجارية النشطة بالمنطقة: ...\", \"تصنيف الأنشطة التجارية المحيطة: ...\", \"الجدوى الاستثمارية والجاذبية للعلامات: ...\"]}")
            
        elif section == "development_options":
            user_parts.append(
                f"- عدد البدائل: {structured_data.get('dev_options_count')}\n"
            )
            for opt_idx in range(1, 5):
                opt_name = structured_data.get(f'dev_opt{opt_idx}_name')
                if opt_name:
                    opt_desc = structured_data.get(f'dev_opt{opt_idx}_desc', '')
                    opt_total_built = structured_data.get(f'dev_opt{opt_idx}_total_built', '')
                    opt_total_leasable = structured_data.get(f'dev_opt{opt_idx}_total_leasable', '')
                    opt_ratio = structured_data.get(f'dev_opt{opt_idx}_leasable_ratio', '')
                    opt_count = structured_data.get(f'dev_opt{opt_idx}_elements_count', '0')
                    
                    user_parts.append(f"- البديل {'الأول' if opt_idx == 1 else 'الثاني' if opt_idx == 2 else 'الثالث' if opt_idx == 3 else 'الرابع'}: {opt_name}")
                    user_parts.append(f"  الوصف: {opt_desc}")
                    user_parts.append(f"  إجمالي المساحة المبنية: {opt_total_built}, إجمالي المساحة التأجيرية: {opt_total_leasable}, نسبة التأجير: {opt_ratio}, عدد العناصر: {opt_count}")
                    
                    # Add element-level details
                    elements = structured_data.get(f'dev_opt{opt_idx}_elements', [])
                    if elements and isinstance(elements, list):
                        user_parts.append(f"  عناصر البديل:")
                        for e_idx, elem in enumerate(elements):
                            elem_display_name = elem.get('name', '')
                            if elem.get('name_custom'):
                                elem_display_name += f" ({elem['name_custom']})"
                            user_parts.append(f"    - {elem_display_name}: مبنية={elem.get('built_area', 'ال ينطبق')}, تأجيرية={elem.get('leasable_area', 'ال ينطبق')}, ملاحظات={elem.get('notes', '')}")
                    user_parts.append("")
            
            reason_list = structured_data.get('dev_recommendation_reason', [])
            if isinstance(reason_list, list):
                reason_str = " / ".join(reason_list)
            else:
                reason_str = str(reason_list)
            if "أخرى" in reason_str:
                custom_reason = structured_data.get('dev_recommendation_reason_custom', '')
                if custom_reason:
                    reason_str += f" / {custom_reason}"
                
            user_parts.append(
                f"- البديل الموصى به: {structured_data.get('dev_recommended')}\n"
                f"- سبب التوصية: {reason_str}"
            )
            user_parts.append(
                "Format as a chart/table comparison. Make it a detailed table representing the alternatives with their elements, built areas, leasable areas, and ratios. "
                "Format: {\"title\": \"بدائل التطوير ودراسة البديل الموصى به\", \"data\": [{\"label\": \"اسم البديل\", \"value\": \"وصف مختصر، المساحة المبنية الإجمالية، المساحة التأجيرية الإجمالية، نسبة التأجير\"}, ...]}"
            )
            
        elif section == "similar_projects":
            user_parts.append(
                f"- أسماء المشاريع المشابهة: {structured_data.get('similar_proj_name')}\n"
                f"- الوصف والنجاح: {structured_data.get('similar_proj_desc')}\n"
                f"- الدروس المستفادة لمشروعنا: {structured_data.get('similar_proj_lessons')}"
            )
            user_parts.append("Format as two_column: {\"title\": \"دراسة الحالات والمشاريع المرجعية\", \"bullets\": [\"مشاريع مرجعية بالمنطقة: ...\", \"عوامل النجاح والإشغال: ...\", \"توصيات مستفادة مطبقة على مشروعنا: ...\"]}")
            
        elif section == "closing":
            user_parts.append("Write a professional closing slide for 'شركة منافع الاقتصادية للعقار' thanking the client.")
            user_parts.append("Format as closing: {\"title\": \"شكراً لاهتمامكم\", \"message\": \"Write a warm, professional closing message in Arabic expressing gratitude and inviting collaboration.\", \"cta\": \"نتطلع للعمل معكم\"}")
            
        elif section.startswith("custom_"):
            custom_content = slide_spec.get("custom_content", "")
            user_parts.append(
                f"- عنوان الشريحة المخصصة: {topic}\n"
                f"- وصف الشريحة والتعليمات: {slide_spec.get('desc', '')}\n"
                f"- محتوى مدخل بواسطة المستخدم (إن وجد): {custom_content}"
            )
            if layout == "standard":
                user_parts.append("Format as standard: {\"title\": \"[Slide Title]\", \"description\": \"Write highly professional, detailed paragraphs expanding beautifully on the custom topic and content in elegant Arabic.\"}")
            elif layout == "two_column":
                user_parts.append("Format as two_column: {\"title\": \"[Slide Title]\", \"bullets\": [\"Detailed bullet point 1...\", \"Detailed bullet point 2...\"]}")
            elif layout == "timeline":
                user_parts.append("Format as timeline: {\"title\": \"[Slide Title]\", \"phases\": [{\"name\": \"Phase Name\", \"duration\": \"Duration\", \"description\": \"Detailed description...\"}]}")
            elif layout == "chart":
                user_parts.append("Format as chart: {\"title\": \"[Slide Title]\", \"data\": [{\"label\": \"Label Name\", \"value\": \"Value\"}]}")
            else:
                user_parts.append("Format as standard: {\"title\": \"[Slide Title]\", \"description\": \"...\"}")
            
        if req_image:
            user_parts.append(
                "\nSince this slide requires an image, add an 'image_prompt' key with a highly detailed prompt in English "
                "for generating the architectural rendering. Make it photorealistic, matching Burgundy and Gold branding colors, "
                "with an upscale Riyadh commercial/residential exterior mood. "
                "CRITICAL: The image prompt MUST accurately and strictly reflect ONLY the specific architectural elements and floors described in this slide's input. Do not add hallucinated elements."
            )
            
        return system, "\n".join(user_parts)

    few_shot_examples = (
        "PREMIUM EXECUTIVE FEW-SHOT EXAMPLES (STUDY THESE STRUCTURES AND IMITATE THEM FOR AN ELITE LOOK):\n"
        "Example 1: Standard Content Slide ('standard')\n"
        "{\n"
        "  \"title\": \"رؤية المخطط العام وأهدافه الاستراتيجية\",\n"
        "  \"description\": \"◆ صياغة معيار جديد للتسوق والرفاهية المدمجة بالطبيعة لتقديم تجربة ترفيهية استثنائية للزوار.\\n◆ تعظيم القيمة الاستثمارية والتشغيلية للمشروع من خلال دراسة مسارات التدفق البشري بدقة عالية.\\n◆ دمج تقنيات البناء المستدام والواجهات الزجاجية الذكية لتحقيق كفاءة طاقة متكاملة وجذابة.\"\n"
        "}\n\n"
        "Example 2: Two-Column Slide ('two_column')\n"
        "{\n"
        "  \"title\": \"التوزيع المساحي والنشاط المقترح لأدوار المشروع\",\n"
        "  \"bullets\": [\n"
        "    \"الدور الأرضي: واجهات زجاجية ذكية مخصصة للبيع بالتجزئة والتسوق الفاخر (60% من المساحة التأجيرية).\",\n"
        "    \"الدور الأول: مطاعم مكشوفة ومقاهي راقية بإطلالات بانورامية مفتوحة (20% من المساحة التأجيرية).\",\n"
        "    \"المناطق الخارجية: لاندسكيب أخضر ونوافير مياه تفاعلية مع نظام أمان متطور للأطفال (20% من المساحة).\"\n"
        "  ]\n"
        "}"
    )

    content_depth_rules = (
        "CONTENT DEPTH & DETAIL: You MUST write highly descriptive, specific, and professional text. "
        "Do not use short or generic phrases. Expand on the facts provided gracefully."
    )

    system = (
        "You are an elite real estate proposal writer for 'شركة منافع الاقتصادية للعقار'. "
        "Write in Arabic (using highly professional investment, real estate, and commercial terms). "
        f"Text density/length preference: {density}.\n\n"
        f"{custom_instructions_rule}"
        "CRITICAL SOURCE OF TRUTH (MANDATORY):\n"
        "- The client's uploaded document (available under the key 'docs_text' in the Project Data) and the custom fact sheet fields are your ABSOLUTE PRIMARY SOURCE OF TRUTH.\n"
        "- ZERO HALLUCINATION (100% STRICT ADHERENCE): You are strictly forbidden from inventing, deducing, or hallucinating any facts, amenities, or features that are not explicitly present in the provided Project Data or 'docs_text'. If the input says there is a ground floor and a first floor, you MUST NOT invent a roof or basement. Execute exactly based on the provided content. Your output must be a 100% reflection of the input, elegantly written.\n"
        "- GEOGRAPHIC & FINANCIAL ADHERENCE: You MUST strictly integrate the project location ('location' field) and cost/financial details ('financial_details' field) entered by the user into the relevant slides (especially Cover, Introduction, and Financial/Chart slides). If the user specified Egypt's New Administrative Capital and 50 million EGP, you MUST use these exact metrics, markets, and numbers. DO NOT ignore them or fallback to Riyadh metrics!\n"
        "- You MUST read the document text carefully and extract actual, real-world facts, numbers, areas (BUA, land area), plot numbers, street names, traffic directions, financial indicators, and competitor names directly from it.\n"
        "- DO NOT write generic real estate filler or make up hypothetical numbers if the document or fact sheet contains specific facts.\n\n"
        "CRITICAL ADHERENCE & ANTI-DUPLICATION:\n"
        "1. NO CONTENT DUPLICATION: Do NOT copy and paste the overall project description or the same percentages/sentences across multiple slides. Each slide MUST have its own unique, focused, and distinct content. For example: the concept slide explains the vision; the space distribution slide details the specific numbers and spatial breakdowns; the design elements slide focuses on materials, facade, and child safety features. Keep each slide highly specialized and unique!\n"
        "2. Read the 'floor_distribution' and 'description' from the Project Data carefully.\n"
        "3. When writing the content for a slide describing a specific floor or a GROUP of floors (e.g., {topic}), you MUST strictly describe ALL the details, layout, and features specified for those specific floors in the Project Data or 'docs_text'. If the topic groups multiple floors together, you must summarize and include all of them in this slide. Do NOT invent new functions, do NOT mix details from outside this group, and do NOT make up generic real estate filler. DO NOT omit any floor included in the group.\n"
        f"4. {content_depth_rules}\n"
        f"5. {few_shot_examples}\n"
        "6. Output ONLY valid JSON, matching the requested schema exactly."
    ).replace("{topic}", topic)
    
    clarification_schema_info = (
        "\nINTERACTIVE CLARIFICATION PROTOCOL (MANDATORY):\n"
        "- If the key details required to write a high-quality slide on this topic ({topic}) are completely missing, vague, or contradictory in 'docs_text' or the Project Data, you MUST set the key 'needs_clarification' to true and write a clear, specific question in Arabic under the key 'clarification_question' asking the user for the missing details.\n"
        "- In this case, your output JSON should look exactly like: {\"title\": \"[Slide Topic]\", \"needs_clarification\": true, \"clarification_question\": \"سؤالك هنا بالتفصيل...\"}"
    ).replace("{topic}", topic)
    
    user_parts = [
        f"Write the content for a slide about: {topic}",
        f"Project Data & Context: {project_data}",
        f"Layout Type: {layout}",
        "Required JSON format based on Layout Type:",
        clarification_schema_info
    ]
    
    if layout == "cover":
        user_parts.append('{"title": "...", "subtitle": "..."}')
    elif layout == "section_header":
        user_parts.append('{"title": "..."}')
    elif layout == "standard":
        user_parts.append('{"title": "...", "description": "..."}')
    elif layout == "two_column":
        user_parts.append('{"title": "...", "bullets": ["...", "..."]}')
    elif layout == "timeline":
        user_parts.append('{"title": "...", "phases": [{"name": "...", "duration": "...", "description": "..."}]}')
    elif layout == "swot":
        user_parts.append('{"title": "...", "strengths": ["..."], "weaknesses": ["..."], "opportunities": ["..."], "threats": ["..."]}')
    elif layout == "map":
        user_parts.append('{"title": "...", "desc": "...", "bullets": ["..."]}')
    elif layout == "chart":
        user_parts.append('{"title": "...", "data": [{"label": "...", "value": "..."}]}')
    elif layout == "closing":
        user_parts.append('{"title": "...", "message": "...", "cta": "..."}')
        
    return system, "\n".join(user_parts)


def generate_consultant_chat_prompt(chat_history: list[dict], uploaded_docs_text: str = "", structured_data: dict = None) -> tuple[str, str]:
    system = (
        "You are an expert real estate development consultant from 'منصة منافع'. "
        "Your mission is to guide the user through an engaging, natural Arabic chat to gather all the necessary facts "
        "to generate a world-class real estate proposal.\n\n"
        "FACT SHEET DETAILS TO EXTRACT OR DISCOVER:\n"
        "- 'project_name': Arabic or English name of the real estate project (e.g., 'مول منافع التجاري').\n"
        "- 'num_slides': Preferred slide count (e.g. 8, 10, or 'auto').\n"
        "- 'language': Preferred presentation language (either 'العربية' (Arabic) or 'الإنجليزية' (English)), as determined dynamically through your conversation.\n"
        "- 'description': Main purpose, slogan, or overall vision.\n"
        "- 'floor_distribution': Architectural distribution (e.g., ground floor showroom, 1st floor offices, 2nd floor dining, etc.).\n"
        "- 'image_style_description': Visual style and lighting preferences for the AI image generation.\n"
        "- 'location': City, neighborhood, and main street.\n"
        "- 'financial_details': Cost, investment value, or rentals if applicable.\n"
        "- 'custom_instructions': Any custom user requests, specific formatting guidelines, structural rules, focus points, layout preferences, or special text instructions they want applied across all slides (e.g. 'ركز على مؤشرات الأرباح', 'اجعل اللغة تسويقية بأسلوب حماسي', 'تجنب العناوين الطويلة').\n\n"
        "CONVERSATIONAL STRATEGY & FILE UPLOADS:\n"
        "1. Be extremely polite, professional, and welcoming in Arabic.\n"
        "2. IMPORTANT: The user may have already filled out a comprehensive form. If 'structured_data' is provided in the context below, YOU MUST READ IT. Do NOT ask the user for their project name, location, or description if it is already present in 'structured_data'!\n"
        "3. Parse the conversation history and any uploaded document text to populate the fact sheet.\n"
        "4. If a document is uploaded, acknowledge it enthusiastically, summarize the main facts, and ask if they are correct.\n"
        "5. Once all essential details are collected (Project Name and either a solid Description or Floor Distribution is known), "
        "set 'all_essential_facts_gathered' to true, summarize what was collected in a congratulations note, and tell them they can now click '🚀 ابدأ التوليد'!\n\n"
        "STRICT SYSTEM GUARDRAILS (CRITICAL):\n"
        "- VAGUE OR INCOMPLETE FACTS: If essential facts are missing, proactively ask them to clarify.\n"
        "- DOMAIN LIMITATION: You are strictly a real estate presentation and development proposal advisor.\n"
        "OUTPUT FORMAT (STRICT):\n"
        "You must output ONLY a valid JSON object with the following structure. DO NOT wrap it in ```json blocks. DO NOT output any other text:\n"
        "{\n"
        "  \"chat_response\": \"Your polite Arabic chat message here...\",\n"
        "  \"fact_sheet\": {\n"
        "    \"project_name\": \"...\",\n"
        "    \"num_slides\": \"...\",\n"
        "    \"language\": \"...\",\n"
        "    \"description\": \"...\",\n"
        "    \"floor_distribution\": \"...\",\n"
        "    \"image_style_description\": \"...\",\n"
        "    \"location\": \"...\",\n"
        "    \"financial_details\": \"...\",\n"
        "    \"custom_instructions\": \"...\",\n"
        "    \"all_essential_facts_gathered\": false\n"
        "  }\n"
        "}"
    )
    
    # Format the history into the user prompt
    history_str = ""
    for msg in chat_history:
        role_label = "المستشار" if msg["role"] == "assistant" else "المستخدم"
        history_str += f"{role_label}: {msg['content']}\n"
        
    user = (
        f"Here is the history of our consultation so far:\n{history_str}\n"
    )
    if uploaded_docs_text:
        user += f"The user has just uploaded a document containing this text:\n{uploaded_docs_text}\n"
        
    if structured_data:
        user += f"The user has ALREADY provided the following structured form data. Do NOT ask for this information again:\n{structured_data}\n"
        
    user += "Analyze this history, update the fact sheet, and write the next response in Arabic."
    return system, user

def generate_smart_review_prompt(structured_data: dict, extracted_facts: dict = None) -> tuple[str, str]:
    """Generates the prompt for the Smart Review stage to identify missing data."""
    system = (
        "You are an expert real estate consultant for 'منصة منافع'. "
        "Your task is to review the inputted project data and identify CRITICAL missing fields that are required to build a comprehensive 12-slide real estate proposal. "
        "CRITICAL INSTRUCTION: You MUST ONLY focus on fields that are COMPLETELY EMPTY (e.g., \"\"), null, or missing. "
        "If a field has ANY data in it (e.g., 'exec_exit_strategy' has 'تطوير وتشغيل'), YOU MUST NOT ASK ABOUT IT. Do not judge the quality or precision of existing data, just check if it's empty. "
        "If the user has provided rich data and there are no completely empty critical fields, YOU MUST RETURN AN EMPTY ARRAY `[]`. Do not invent or force questions if the data is already good! "
        "If you do find truly empty fields (up to 3 max), provide a clear Arabic question, the exact JSON key you want to fill, and 3-4 logical multiple-choice options. "
        "OUTPUT FORMAT (STRICT):\n"
        "You must output ONLY a valid JSON array of objects. DO NOT output Markdown blocks. DO NOT output any other text:\n"
        "[\n"
        "  {\n"
        "    \"field_key\": \"the_internal_key\" (e.g. 'missing_field_name'),\n"
        "    \"question\": \"لم تقم بتحديد ... ما هو الأقرب:\",\n"
        "    \"options\": [\"خيار 1\", \"خيار 2\", \"خيار 3\"]\n"
        "  }\n"
        "]\n"
    )
    
    user = (
        "Here is the inputted structured data from the user:\n"
        f"{str(structured_data)}\n\n"
    )
    if extracted_facts:
        user += (
            "Here are the facts extracted from the user's chat and uploaded files:\n"
            f"{str(extracted_facts)}\n\n"
            "CRITICAL: A field is NOT missing if it is answered in EITHER the structured data OR the extracted facts. "
            "Do not ask questions about information the user has already provided in either place.\n\n"
        )

    user += (
        "Review this data. Identify any major missing fields (empty strings, None, or empty lists). "
        "Output the JSON array. Make sure the options are highly professional and relevant to the Saudi real estate market."
    )
    
    return system, user


def generate_design_edit_prompt(user_instruction: str, current_slides: list[dict], current_theme: dict) -> tuple[str, str]:
    """Generates the prompt for the Chatbot Refiner to modify presentation slides or styles."""
    import json
    system = (
        "You are an expert real estate presentation architect for 'شركة منافع الاقتصادية للعقار'. "
        "Your role is to act as the AI engine behind a chat-based slide editor. "
        "The user will provide instructions (in Arabic or English) to modify the presentation's design, content, colors, fonts, slide ordering, or details. "
        "You must interpret these instructions and return the updated slides list and any theme color/font overrides. "
        "GUIDELINES FOR MODIFICATIONS:\n"
        "1. COLOR/STYLE CHANGES: If the user requests color changes (e.g. 'اجعل الخلفية غامقة', 'غير الألوان للذهبي والفضي', 'اجعل لون العنوان عنابيا'), "
        "you must output the updated hex values under 'theme_overrides'. The available keys are 'primary_color', 'secondary_color', 'accent_color', 'bg_color', 'text_color', and 'font'. "
        "Ensure the hex strings are valid (e.g., '#670D0C').\n"
        "2. FONT CHANGES: If they request font changes (e.g. 'تغيير الخط للـ the sans arabic', 'استخدم خط النخبة'), update 'font' under 'theme_overrides' to 'The Sans Arabic' or the requested font name.\n"
        "3. CONTENT EDITING: If they want to change text (e.g. 'غير عنوان الشريحة 2 إلى...', 'عدل نقاط القوة في سوات لتشمل...'), "
        "update the corresponding slide in the 'updated_slides' array. Respect the slide_type schema.\n"
        "4. LAYOUT ALTERING: If they ask to change a slide layout (e.g. 'اجعل الشريحة 4 عمودين', 'حول الشريحة 5 إلى جدول'), "
        "update the 'slide_type' of that slide (allowed slide_type: [cover, section_header, standard, two_column, timeline, swot, map, chart, closing]). "
        "If a layout is changed, ensure the slide's keys map to that layout (e.g., a two_column slide should have 'bullets', a chart slide should have 'data', etc.).\n"
        "5. SLIDE RE-ORDERING/DELETION: If they ask to remove or re-order slides, modify the list of slides accordingly. "
        "6. CONVERSATIONAL REPLY: You must also write a friendly and professional response in Arabic explaining what changes you have made.\n\n"
        "OUTPUT FORMAT (STRICT):\n"
        "You must output ONLY a valid JSON object. DO NOT output Markdown blocks or any extra text:\n"
        "{\n"
        "  \"chat_response\": \"تم تعديل الخلفية إلى اللون الرمادي الفاتح وتعديل عنوان الشريحة الثانية...\",\n"
        "  \"theme_overrides\": {\n"
        "    \"primary_color\": \"#670D0C\",\n"
        "    \"secondary_color\": \"#A7A9AC\",\n"
        "    \"accent_color\": \"#C2A176\",\n"
        "    \"bg_color\": \"#FFFFFF\",\n"
        "    \"text_color\": \"#0F172A\",\n"
        "    \"font\": \"The Sans Arabic\"\n"
        "  },\n"
        "  \"updated_slides\": [\n"
        "     ... (the complete list of slides with all applied changes)\n"
        "  ]\n"
        "}"
    )

    user = (
        f"User Instruction:\n{user_instruction}\n\n"
        f"Current Styling Theme Variables:\n{json.dumps(current_theme, ensure_ascii=False)}\n\n"
        f"Current Presentation Slides List:\n{json.dumps(current_slides, ensure_ascii=False)}\n\n"
        "Interpret the instruction and return the updated JSON structure."
    )
    return system, user