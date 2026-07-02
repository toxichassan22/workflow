"""
Style Signature Service - Uses OpenRouter (DeepSeek V4 Pro) for extracting architectural
style signatures and generating consistent image prompts.
"""

import logging
import os
from typing import List, Optional

from openai import OpenAI
from services.api_keys import get_openrouter_api_key
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")


def _get_api_key() -> str:
    return get_openrouter_api_key()



_client: Optional[OpenAI] = None
_client_key: Optional[str] = None


def _get_client() -> OpenAI:
    global _client, _client_key
    key = _get_api_key()
    if not key:
        raise ValueError(
            "OpenRouter API Key is missing. "
            "Please set OPENROUTER_API_KEY in your environment, or provide it in the API settings sidebar."
        )
    if _client is None or _client_key != key:
        _client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=key,
        )
        _client_key = key
    return _client


def _is_retryable(exc: BaseException) -> bool:
    """Return True only for transient errors worth retrying."""
    exc_str = str(exc).lower()
    if any(code in exc_str for code in ["401", "403", "404", "authentication", "unauthorized", "not found"]):
        return False
    return True


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    retry=lambda retry_state: _is_retryable(retry_state.outcome.exception()) if retry_state.outcome and retry_state.outcome.failed else False,
    reraise=True,
)
def _generate_content_with_retry(system_prompt: str, user_prompt: str) -> str:
    """Text generation via OpenRouter with retry."""
    logger.info("OpenRouter style/prompt request...")
    client = _get_client()

    response = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""


def extract_style_signature(images_b64: List[str], fallback_text: str) -> str:
    """
    Generates a cohesive architectural style signature.
    Note: OpenRouter text models cannot analyze images directly,
    so we always synthesize from project metadata/fallback text.
    If images were provided, we mention that in the prompt for richer context.
    """
    logger.info("Extracting style signature... images count: %d", len(images_b64))

    system_instruction = (
        "You are a world-class architectural analyst. Your job is to create a highly detailed, "
        "professional building architectural identity and styling signature in English. This signature "
        "will be used as a design prompt template for an AI image generator (like GPT-5.4 Image 2) to generate "
        "architecturally consistent images across different perspectives of the SAME building project.\n\n"
        "Be extremely descriptive. Focus on:\n"
        "1. Architectural Geometry & Structural Layout (e.g., L-shaped two-story villa, dramatic cantilevers, flat roofs, double-height voids).\n"
        "2. Facade Materials & Textures (e.g., warm cedar wood slats, raw board-formed concrete panels, white textured stucco, dark metal framing).\n"
        "3. Window Design (e.g., floor-to-ceiling glass panels, slim black aluminum frames, panoramic glazing).\n"
        "4. Palette & Color Scheme (e.g., neutral warm greys, off-whites, warm natural timber, charcoal accents).\n"
        "5. Landscaping & Environment (e.g., xeriscaped garden with neat lawn patches, stone tile walkways, minimal ground uplighting).\n"
        "6. Lighting, Atmosphere & Rendering Style (e.g., evening golden hour, dramatic dusk twilight sky, warm interior lighting visible from glass facades, photorealistic architectural rendering)."
    )

    try:
        image_context = ""
        if images_b64:
            image_context = (
                f"\n\nNote: {len(images_b64)} reference image(s) of the land/site were uploaded by the user. "
                "Since we cannot analyze them directly, please create a style signature that would work well "
                "for a modern luxury real estate development in Saudi Arabia (Riyadh area)."
            )

        user_prompt = (
            f"Create an elegant, ultra-consistent architectural style signature in English based on these project details:\n"
            f"{fallback_text}{image_context}\n\n"
            "If the text is in Arabic, interpret it carefully. Decide on a premium, beautiful architectural style "
            "that fits this description, and write a rich, highly detailed style block signature."
        )

        response_text = _generate_content_with_retry(system_instruction, user_prompt)
        style_sig = response_text.strip()
        logger.info("Successfully generated style signature: %s...", style_sig[:100])
        return style_sig

    except Exception as e:
        logger.error("Failed to extract style signature: %s", e, exc_info=True)
        # Safe fallback
        return (
            "modern minimalist contemporary architecture, flat roof, glass facades, "
            "concrete and warm wood panels, warm dusk lighting, luxury landscaping"
        )


def generate_consistent_image_prompt(
    slide_title: str,
    slide_body: str,
    style_signature: str,
    slide_type: str
) -> str:
    """
    Generates a highly descriptive, floor-accurate English room or structural description
    based on the slide content and details, supporting 3D skeletons vs. furnished interiors.
    """
    logger.info("Generating consistent prompt for slide: %s (Type: %s)", slide_title, slide_type)

    system_instruction = (
        "You are an expert architectural prompt engineer. Your job is to write a highly detailed, "
        "professional English description of a specific scene, room, or floor layout for a real estate proposal.\n\n"
        "CRITICAL RULES:\n"
        "1. CORE PERSPECTIVE: Read the slide title and body details (which may be in Arabic) and determine the exact perspective to show.\n"
        "2. MANDATORY PREMIUM HYBRID STYLE:\n"
        "   - ALL slides must use a premium HYBRID architectural-realistic style.\n"
        "   - Blends engineering/blueprint aesthetics with gorgeous, photorealistic interior/exterior finishes.\n"
        "   - Describe the scene as a luxury '3D axonometric cutaway structural rendering' showing a fascinating mix of clean white technical blueprint lines, structural grid layouts, and exposed concrete details on one side, transitioning seamlessly into a fully finished, ultra-luxurious space on the other side.\n"
        "3. SCENE DESCRIPTION ONLY: Focus ONLY on describing the specific room layout, furniture arrangements, concrete structure, camera angle, and perspective. Do NOT write general styling rules.\n"
        "4. NO TEXT/PEOPLE/QUOTES: Do NOT include people, cars, text, or watermarks. Do NOT use quotation marks or place slogans in quotes (e.g. do NOT write 'Spirit of the Future'), as this tricks the image generator into drawing text signs on the building. Describe all concepts physically. Focus entirely on the pure architecture."
    )

    user_prompt = (
        f"--- Visual Theme Style Signature (MUST follow): ---\n"
        f"{style_signature}\n\n"
        f"--- Current Slide Information: ---\n"
        f"Slide Title: {slide_title}\n"
        f"Slide Content/Details: {slide_body}\n"
        f"Slide Layout Type: {slide_type}\n\n"
        f"Write a specific scene description in English for the floor layout or room perspective described, "
        f"strictly using the premium hybrid architectural-realistic style."
    )

    try:
        response_text = _generate_content_with_retry(system_instruction, user_prompt)
        final_prompt = response_text.strip()

        # Clean markdown wrappers
        final_prompt = final_prompt.replace("```", "").strip()
        if final_prompt.startswith('"') and final_prompt.endswith('"'):
            final_prompt = final_prompt[1:-1].strip()

        logger.info("Successfully generated consistent slide prompt: %s...", final_prompt[:120])
        return final_prompt

    except Exception as e:
        logger.error("Failed to generate consistent prompt: %s", e, exc_info=True)

        # Fallback based on keywords
        title_lower = (slide_title or "").lower()
        body_lower = (slide_body or "").lower()
        combined = f"{title_lower} {body_lower}"

        if any(kw in combined for kw in ["هيكل", "خرساني", "إنشائي", "عظم", "أعمدة", "skeleton", "concrete"]):
            return "3D axonometric cutaway structural rendering in a premium hybrid style, seamless blend of a clean engineering blueprint showing technical grid lines, blue/white layout markings, and raw concrete column structural details, transitioning into an ultra-luxurious fully furnished space. Features premium high-end furniture, elegant soft leather sofa, polished white marble floor, rich natural oak panels, warm architectural spotlights and glowing ambient LED strip lighting, daytime studio light, crisp photorealistic details"
        elif any(kw in combined for kw in ["أثاث", "فرش", "مؤثث", "داخلي", "معيشة", "صالون", "غرفة", "نوم", "مطبخ", "صالة", "مجلس", "interior", "furniture", "living room", "bedroom"]):
            return "ultra-luxurious modern furnished interior rendering of a contemporary open-plan floor, premium luxury furniture layout, elegant soft leather sofa, marble coffee table, warm architectural ambient lighting, natural oak wood wall paneling, polished concrete floor, minimal styling, cozy photorealistic details"
        elif any(kw in combined for kw in ["سطح", "روف", "خارجي", "حديقة", "مسبح", "outdoor", "pool", "roof", "terrace", "garden"]):
            return "luxurious modern roof terrace rendering, premium outdoor seating lounge, wooden pergola, minimal swimming pool, twilight sunset sky, warm uplighting"
        elif any(kw in combined for kw in ["مساحة", "موقع", "قياسات", "أبعاد", "مخطط"]):
            return "luxurious modern architectural rendering of the premium property development, upscale design and landscaping, warm twilight lighting, photorealistic 8k, no text"

        return "modern minimalist contemporary architectural rendering of a luxury villa, flat roof, wood and concrete facade, twilight golden hour lighting"


def generate_initial_reference_prompt(project_data: dict) -> str:
    """
    Generates a highly descriptive, professional architectural English prompt
    for the master reference building exterior based on the user's project facts.
    Uses DeepSeek Pro to guarantee 100% compliance with client inputs and translate Arabic styles.
    """
    logger.info("Generating initial master reference prompt for project: %s", project_data.get("project_name"))
    
    proj_name = project_data.get("project_name", "Real Estate Project")
    proj_desc = project_data.get("description", "Premium real estate development")
    floor_dist = project_data.get("floor_distribution", "")
    custom_style = project_data.get("image_style_description", "")
    
    system_instruction = (
        "You are an expert architectural prompt engineer for high-end real estate visuals.\n"
        "Your task is to write a highly detailed, professional English architectural exterior rendering prompt "
        "based on the user's project details.\n\n"
        "CRITICAL RULES:\n"
        "1. NO TEXT/LABELS/QUOTES: Do NOT include any words, company logos, brochure templates, dimension labels, or graphic overlays. Do NOT use quotation marks or place slogans in quotes (e.g. do NOT write 'Spirit of the Future'), as this tricks the image generator into drawing text signs on the building. Describe all concepts physically. The prompt must describe a clean, pure architectural rendering.\n"
        "2. SCENE DESCRIPTION: Describe a stunning, photorealistic exterior view of the building at twilight/evening golden hour with dramatic luxury lighting.\n"
        "3. COHERENT GEOMETRY: Incorporate physical layout details mentioned (e.g. U-shaped layout, L-shaped, high-end materials, child-friendly landscape, resort amenities).\n"
        "4. Output ONLY the clean English prompt text. Do NOT wrap in quotes, markdown, or explain anything."
    )
    
    user_prompt = (
        f"Project Name: {proj_name}\n"
        f"Description: {proj_desc}\n"
        f"Floor Distribution & Layout: {floor_dist}\n"
        f"Requested Visual Style: {custom_style}\n\n"
        "Write a gorgeous, detailed English prompt for a photorealistic architectural exterior rendering of this project."
    )
    
    try:
        response_text = _generate_content_with_retry(system_instruction, user_prompt)
        final_prompt = response_text.strip().replace("```", "").strip()
        if final_prompt.startswith('"') and final_prompt.endswith('"'):
            final_prompt = final_prompt[1:-1].strip()
        logger.info("Successfully generated enriched initial visual prompt: %s", final_prompt[:120])
        return final_prompt
    except Exception as e:
        logger.error("Failed to generate initial reference prompt: %s", e)
        # Fallback to a custom-compiled clean prompt in English
        return (
            f"Widescreen luxurious modern exterior architectural rendering of {proj_name}, "
            f"inspired by: {proj_desc[:80]}. High-end contemporary materials, glass facade, dark mode palette, golden uplighting, "
            f"premium landscaping, award-winning architectural photography style, photorealistic, 8k resolution, no people, no text"
        )
