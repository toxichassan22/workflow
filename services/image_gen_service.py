"""Image generation service with project-level visual reference locking."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import settings

logger = logging.getLogger(__name__)



def _cache_disabled() -> bool:
    return os.getenv("DISABLE_IMAGE_CACHE", "").lower() in {"1", "true", "yes"}


def _image_to_png_bytes(image) -> bytes:
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format="PNG")
    return img_byte_arr.getvalue()


def _normalise_reference_image(image_bytes: bytes) -> bytes:
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image.thumbnail((1024, 1024))
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format="PNG")
    return img_byte_arr.getvalue()


def _project_slug(value: str) -> str:
    clean = re.sub(r"[^\w\u0600-\u06FF-]+", "_", value.strip(), flags=re.UNICODE)
    clean = re.sub(r"_+", "_", clean).strip("_")
    return clean[:64] or "project"


def get_project_image_key(project_data: dict) -> str:
    """Return a stable key for a project's image identity."""
    identity = {
        "project_name": project_data.get("project_name") or project_data.get("name"),
        "description": project_data.get("description"),
        "land_area": project_data.get("land_area"),
        "dimensions": project_data.get("dimensions"),
        "floor_distribution": project_data.get("floor_distribution"),
    }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{_project_slug(str(identity.get('project_name') or 'project'))}_{digest}"


def _project_image_dir(project_key: str) -> Path:
    path = settings.OUTPUT_DIR / "project_image_refs" / _project_slug(project_key)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_project_reference_image(project_key: str) -> Optional[bytes]:
    path = _project_image_dir(project_key) / "master_reference.png"
    return path.read_bytes() if path.exists() else None


def set_project_reference_image(project_key: str, image_bytes: bytes) -> Path:
    path = _project_image_dir(project_key) / "master_reference.png"
    path.write_bytes(_normalise_reference_image(image_bytes))
    return path


def get_project_slide_image(project_key: str, slide_index: int) -> Optional[bytes]:
    path = _project_image_dir(project_key) / f"slide_{slide_index:02d}.png"
    return path.read_bytes() if path.exists() else None


def set_project_slide_image(project_key: str, slide_index: int, image_bytes: bytes) -> Path:
    path = _project_image_dir(project_key) / f"slide_{slide_index:02d}.png"
    path.write_bytes(image_bytes)
    return path


def _contains_any(value: str, keywords: list[str]) -> bool:
    return any(keyword in value for keyword in keywords)


def _truncate_prompt(prompt: str, max_chars: int = 3000) -> str:
    """Truncate prompt to prevent exceeding model context limits."""
    if len(prompt) <= max_chars:
        return prompt
    logger.warning("Prompt truncated from %d to %d chars", len(prompt), max_chars)
    return prompt[:max_chars].rsplit(",", 1)[0].strip()


def _sanitize_prompt(prompt: str, is_commercial: bool = False) -> str:
    """Translate Arabic-heavy prompts into stable English image prompts."""
    # If not explicitly passed as True, check prompt text
    if not is_commercial:
        is_commercial = _contains_any(prompt.lower(), [
            "تجاري", "إداري", "إداريه", "تجاريه", "مكتب", "برج", "عمارة", "مجمع", "مكاتب", "أبراج",
            "commercial", "office", "administrative", "tower", "complex", "building"
        ])

    english_chars = len(re.findall(r"[a-zA-Z]", prompt))
    if english_chars > 30:
        # Prompt is already in English! Bypass the translation firewall,
        # but strip any Arabic characters to prevent API issues.
        logger.info("Prompt is already in English (detected %d English chars). Bypassing translation firewall.", english_chars)
        clean_prompt = re.sub(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\u060C\u061B\u061F\u0640]", "", prompt).strip()
        clean_prompt = re.sub(r",\s*,", ",", clean_prompt)
        clean_prompt = re.sub(r"\s+", " ", clean_prompt).lstrip(", ").strip()
        
        if is_commercial:
            clean_prompt_lower = clean_prompt.lower()
            if "villa" in clean_prompt_lower or "residential" in clean_prompt_lower or "home" in clean_prompt_lower or "house" in clean_prompt_lower:
                if any(kw in clean_prompt_lower for kw in ["tower", "skyscraper", "high-rise", "high rise"]):
                    clean_prompt = re.sub(r"\bvilla\b", "modern commercial glass tower", clean_prompt, flags=re.IGNORECASE)
                    clean_prompt = re.sub(r"\bvillas\b", "modern commercial towers", clean_prompt, flags=re.IGNORECASE)
                else:
                    clean_prompt = re.sub(r"\bvilla\b", "modern commercial glass building", clean_prompt, flags=re.IGNORECASE)
                    clean_prompt = re.sub(r"\bvillas\b", "modern commercial buildings", clean_prompt, flags=re.IGNORECASE)
                clean_prompt = re.sub(r"\bresidential\b", "commercial office", clean_prompt, flags=re.IGNORECASE)
                clean_prompt = re.sub(r"\bhome\b", "office suite", clean_prompt, flags=re.IGNORECASE)
                clean_prompt = re.sub(r"\bhouse\b", "commercial complex", clean_prompt, flags=re.IGNORECASE)
            
            # Enforce commercial context explicitly if missing
            if not any(kw in clean_prompt_lower for kw in ["commercial", "office", "complex", "tower", "skyscraper"]):
                if any(kw in clean_prompt_lower for kw in ["tower", "skyscraper", "high-rise", "high rise"]):
                    clean_prompt = f"{clean_prompt}, modern commercial glass skyscraper tower, professional business district setting, absolutely no residential houses or villas"
                else:
                    clean_prompt = f"{clean_prompt}, modern commercial glass building complex, professional business district setting, absolutely no residential houses or villas"
                clean_prompt = re.sub(r",\s*,", ",", clean_prompt)
        
        return clean_prompt

    has_arabic = bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", prompt))
    if not has_arabic:
        return prompt

    logger.info("Found Arabic characters in prompt, applying sanitization firewall.")

    # Check structure words first (highest specificity)
    structure_words = [
        "هيكل", "خرساني", "إنشائي", "عظم", "أعمدة", "أعمدة خرسانية",
        "skeleton", "concrete", "structure",
    ]
    interior_words = [
        "أثاث", "فرش", "مؤثث", "مفروش", "داخلي", "معيشة", "صالون", "غرفة", "نوم", "حمام", "مطبخ", "صالة", "مجلس", "جناح", "سينما", "استقبال", "طعام", "معيشه",
        "furniture", "furnished", "interior", "living room", "bedroom"
    ]
    outdoor_words = [
        "سطح", "روف", "خارجي", "حديقة", "مسبح",
        "outdoor", "garden", "pool", "roof", "terrace"
    ]
    # Exclude 'أرض' from land_words to prevent matching 'الأرضي' / 'أرضي'
    land_words = [
        "مساحة", "موقع", "قياسات", "أبعاد", "مخطط",
    ]

    if _contains_any(prompt, structure_words):
        translated_scene = (
            "3D axonometric cutaway structural rendering in a premium hybrid style, "
            "seamless blend of a clean engineering blueprint showing technical grid lines, blue/white layout markings, "
            "and raw concrete column structural details, transitioning into an ultra-luxurious fully furnished space. "
            "Features premium high-end furniture, elegant soft leather sofa, polished white marble floor, rich natural oak panels, "
            "warm architectural spotlights and glowing ambient LED strip lighting, daytime studio light, crisp photorealistic details"
        )
    elif _contains_any(prompt, interior_words):
        translated_scene = (
            "ultra-luxurious modern furnished interior rendering of a contemporary open-plan floor, "
            "premium luxury furniture layout, elegant soft leather sofa, marble coffee table, warm architectural ambient lighting, "
            "natural oak wood wall paneling, polished concrete floor, minimal styling, cozy photorealistic details"
        )
    elif _contains_any(prompt, outdoor_words):
        translated_scene = (
            "luxurious modern roof terrace garden rendering, premium outdoor seating lounge, wooden pergola canopy, "
            "minimalist swimming pool, glowing sunset dusk twilight sky, warm soft floor uplighting, cozy atmosphere"
        )
    elif _contains_any(prompt, land_words):
        if is_commercial:
            translated_scene = (
                "3D architectural visualization of a premium land plot with a modern commercial glass building complex in the background, "
                "exact boundary layout guidelines marked with neat white drafting lines, surrounding modern city business district, "
                "clear day lighting, crisp photorealistic details"
            )
        else:
            translated_scene = (
                "3D architectural visualization of a premium square 400 sqm land plot with a luxury modern villa in the background, "
                "exact 20m x 20m dimension guidelines marked with neat white drafting lines, surrounding modern neighborhood, "
                "clear day lighting, crisp photorealistic details"
            )
    else:
        if is_commercial:
            if _contains_any(prompt.lower(), ["برج", "أبراج", "ناطحة", "سحاب", "tower", "skyscraper", "high-rise", "high rise"]):
                translated_scene = (
                    "luxurious modern exterior architectural rendering of a premium soaring 40-story luxury modern commercial skyscraper tower, "
                    "sleek futuristic glass and steel facade reaching into the sky, reflecting dramatic twilight sunset, architectural warm spotlights, premium plaza and landscaping"
                )
            else:
                translated_scene = (
                    "luxurious modern exterior architectural rendering of a premium 10-story modern commercial and office building, "
                    "sleek glass and steel facade reflecting dramatic twilight sunset, architectural warm spotlights, premium plaza and landscaping"
                )
        else:
            translated_scene = (
                "luxurious modern exterior architectural rendering of a premium contemporary villa, flat roof, "
                "warm cedar wood panels and concrete facade, dramatic twilight dusk lighting, elegant landscaping"
            )

    clean_prompt = re.sub(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\u060C\u061B\u061F\u0640]", "", prompt).strip()
    clean_prompt = re.sub(r",\s*,", ",", clean_prompt)
    clean_prompt = re.sub(r"\s+", " ", clean_prompt).lstrip(", ").strip()
    prompt = f"{translated_scene}, {clean_prompt}"
    prompt = re.sub(r",\s*,", ",", prompt)
    return re.sub(r"\s+", " ", prompt).strip()


def _get_api_key() -> str:
    from services.api_keys import get_openrouter_api_key
    return get_openrouter_api_key()


def _is_retryable(exc: BaseException) -> bool:
    """Return True only for transient errors worth retrying."""
    exc_str = str(exc).lower()
    # Don't retry auth failures or model-not-found — they will never succeed
    if any(code in exc_str for code in ["401", "403", "404", "authentication", "unauthorized", "not found"]):
        return False
    return True


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=3, max=30),
    retry=lambda retry_state: _is_retryable(retry_state.outcome.exception()) if retry_state.outcome and retry_state.outcome.failed else False,
    reraise=True,
)
def generate_image(prompt: str, reference_image: Optional[bytes] = None, seed: Optional[int] = None, is_commercial: bool = False, is_land_reference: bool = False) -> bytes:
    """Generate a premium quality architectural image using OpenRouter (GPT-5.4 Image).
    No fallback to Pollinations Flux is allowed to guarantee visual consistency and reference image lock.
    """
    import requests
    import base64

    prompt = _sanitize_prompt(prompt, is_commercial=is_commercial)
    prompt = _truncate_prompt(prompt, max_chars=2500)
    
    if seed is None:
        seed = int(hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8], 16) % 1000000000

    api_key = _get_api_key()
    image_model = os.getenv("OPENROUTER_IMAGE_MODEL", "google/gemini-3.1-flash-image-preview")
    
    if not api_key:
        raise ValueError(
            "OpenRouter API Key is missing. "
            "Please set OPENROUTER_API_KEY in your environment to generate premium architectural proposals."
        )

    cache_key = hashlib.sha256(f"{image_model}\n{seed}\n{prompt}".encode("utf-8")).hexdigest()
    cache_dir = settings.OUTPUT_DIR / "image_cache"
    cache_path = cache_dir / f"{cache_key}.png"

    if not _cache_disabled() and cache_path.exists():
        logger.info("Image cache hit (%s): %s", image_model, cache_path)
        return cache_path.read_bytes()

    logger.info("Requesting image from OpenRouter using %s...", image_model)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Antigravity",
        "X-Title": "Real Estate Proposal Generator"
    }
    user_content = [{"type": "text", "text": f"{prompt} --aspect 16:9"}]
    if reference_image:
        ref_b64 = base64.b64encode(reference_image).decode("utf-8")
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{ref_b64}"
            }
        })
        if is_land_reference:
            ref_directive = (
                "CRITICAL: The attached image shows the actual development site or land plot. "
                "Your absolute goal is to place, construct, and visually build the luxurious modern building or skyscraper described in the prompt DIRECTLY ON this specific site/land plot. "
                "Retain the surrounding streets, skyline, buildings, background context, and environment layout of the attached image. "
                "Do NOT output an empty land plot. You MUST render the beautiful completed new building standing on this plot. "
                "Ensure there are no text, labels, dimensions, brochures, or graphic overlays."
            )
        else:
            ref_directive = (
                "CRITICAL: Use the attached image as the absolute architectural template, layout, structural geometry, materials, and styling guide. "
                "Ignore any text, labels, dimensions, brochures, watermarks, corporate branding, or overlays present in the reference image. "
                "Do NOT generate any text, brochures, or graphic labels on the output image under any circumstances. "
                "The generated image MUST be completely consistent with this reference building, representing another perspective or floor of the same project. "
            )
        user_content[0]["text"] = f"{ref_directive}\n{prompt} --aspect 16:9"
    
    payload = {
        "model": image_model,
        "messages": [{"role": "user", "content": user_content}],
        "modalities": ["image", "text"]
    }
    url = "https://openrouter.ai/api/v1/chat/completions"
    response = requests.post(url, headers=headers, json=payload, timeout=90)
    response.raise_for_status()
    data = response.json()
    
    message = data["choices"][0]["message"]
    images = message.get("images", [])
    if images:
        img_url = images[0]["image_url"]["url"]
        if "," in img_url:
            base64_data = img_url.split(",", 1)[1]
        else:
            base64_data = img_url
        img_bytes = base64.b64decode(base64_data)
        
        if not _cache_disabled():
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(img_bytes)
            logger.info("OpenRouter image cached at: %s", cache_path)
        
        logger.info("Generated image via OpenRouter size: %d bytes", len(img_bytes))
        return img_bytes
    else:
        err_msg = f"OpenRouter succeeded but returned no images. Content: {message.get('content')}"
        logger.error(err_msg)
        raise RuntimeError(err_msg)

