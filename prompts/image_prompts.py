"""
Image Prompts – architectural style library and prompt builders.
Used by the image generator to create consistent, high-quality visuals.
"""

# ── Architectural Style Presets ─────────────────────────────────────────
STYLES: dict[str, dict[str, str]] = {
    "modern": {
        "prefix": "modern contemporary architecture",
        "materials": "glass, steel, concrete, clean lines",
        "mood": "minimalist, sleek, luxurious",
    },
    "classic": {
        "prefix": "classic traditional architecture",
        "materials": "stone, marble, ornate columns, arched windows",
        "mood": "elegant, timeless, prestigious",
    },
    "commercial": {
        "prefix": "commercial office building architecture",
        "materials": "glass curtain wall, steel structure, modern facade",
        "mood": "professional, corporate, impressive",
    },
    "mixed_use": {
        "prefix": "mixed-use development architecture",
        "materials": "varied materials, retail ground floor, residential upper floors",
        "mood": "vibrant, urban, community-oriented",
    },
    "luxury_villa": {
        "prefix": "luxury villa architecture",
        "materials": "premium stone, large windows, landscaped gardens",
        "mood": "opulent, private, resort-style",
    },
    "islamic": {
        "prefix": "Islamic-inspired contemporary architecture",
        "materials": "geometric patterns, mashrabiya screens, domed elements",
        "mood": "culturally authentic, modern interpretation, majestic",
    },
}

# ── Negative Prompt (shared across all generations) ─────────────────────
NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, unrealistic proportions, watermark, "
    "text overlay, cartoon, anime, sketch, doodle, people, cars, "
    "oversaturated, underexposed, noise, artifacts"
)

# ── Quality Suffix (appended to every prompt) ───────────────────────────
QUALITY_SUFFIX = (
    "professional architectural rendering, photorealistic, 8k, "
    "golden hour lighting, detailed materials, sharp focus, "
    "award-winning architecture photography"
)


def get_image_prompt(style: str, building_description: str, slide_type: str) -> str:
    """Build a complete image generation prompt.

    Args:
        style: One of the STYLES keys (modern, classic, etc.).
        building_description: User's description of the building.
        slide_type: The slide this image is for (exterior, interior, etc.).

    Returns:
        A detailed prompt string ready for SDXL / ControlNet.
    """
    style_data = STYLES.get(style, STYLES["modern"])

    # Slide-specific angle / context
    angle_map = {
        "exterior": "exterior front view, eye-level perspective",
        "interior": "luxury interior design, wide-angle shot",
        "aerial": "aerial bird's eye view, drone perspective",
        "landscape": "landscaped surroundings, garden view",
        "entrance": "grand entrance, welcoming facade",
        "night": "night view, dramatic lighting, illuminated facade",
    }
    angle = angle_map.get(slide_type, "exterior front view")

    prompt = (
        f"{style_data['prefix']}, {angle}, {building_description}, "
        f"materials: {style_data['materials']}, "
        f"mood: {style_data['mood']}, {QUALITY_SUFFIX}"
    )
    return prompt


def get_controlled_image_prompt(style: str, building_description: str) -> str:
    """Build a prompt for ControlNet (land-photo-referenced) generation.

    The prompt is tailored to work with canny edge detection, preserving
    the spatial layout of the original land photo.

    Args:
        style: Architectural style key.
        building_description: What to build on the land.

    Returns:
        Prompt string for ControlNet-Canny.
    """
    style_data = STYLES.get(style, STYLES["modern"])

    prompt = (
        f"{style_data['prefix']}, architectural visualization on existing land, "
        f"{building_description}, "
        f"maintaining original terrain perspective and layout, "
        f"materials: {style_data['materials']}, "
        f"realistic integration with surroundings, {QUALITY_SUFFIX}"
    )
    return prompt
