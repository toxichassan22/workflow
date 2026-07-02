"""
Vision Service – uses GPT-4o Vision via OpenRouter to analyze uploaded land photos.
Extracts terrain characteristics, surroundings, and orientation from the image.
"""

import base64
import logging
import os
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from services.api_keys import get_openrouter_api_key

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "openai/gpt-4o")

_client: OpenAI | None = None
_client_key: str | None = None


def _get_client() -> OpenAI:
    global _client, _client_key
    key = get_openrouter_api_key()
    if not key:
        raise ValueError(
            "OpenRouter API Key is missing. "
            "Please set OPENROUTER_API_KEY in your environment."
        )
    if _client is None or _client_key != key:
        _client = OpenAI(api_key=key, base_url=OPENROUTER_BASE_URL)
        _client_key = key
    return _client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((Exception,)),
    reraise=True,
)
def analyze_land_image(image_bytes: bytes) -> dict[str, Any]:
    """Analyze a land photo using GPT-4o Vision.

    Args:
        image_bytes: Raw bytes of the uploaded image (JPEG/PNG).

    Returns:
        Dict with keys: terrain_type, dimensions_estimate, surroundings,
        orientation, vegetation, notable_features, suggested_styles.
    """
    logger.info("Analyzing land image (%d bytes)...", len(image_bytes))
    client = _get_client()

    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model=OPENAI_VISION_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert real estate analyst. Analyze the land photo "
                    "and return a JSON object with these keys:\n"
                    "- terrain_type: (flat, sloped, hilly, waterfront, etc.)\n"
                    "- dimensions_estimate: rough size estimate from the photo\n"
                    "- surroundings: what's around the land (urban, suburban, rural, etc.)\n"
                    "- orientation: compass direction estimate if visible\n"
                    "- vegetation: types of vegetation visible\n"
                    "- notable_features: any distinctive features\n"
                    "- suggested_styles: list of 3 architectural styles that suit this land\n"
                    "Return ONLY valid JSON."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze this land photo for a real estate development proposal:"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                    },
                ],
            },
        ],
        temperature=0.3,
        max_tokens=1000,
        response_format={"type": "json_object"},
    )

    import json
    raw = response.choices[0].message.content or "{}"
    result = json.loads(raw)
    logger.info("Land analysis complete: %s", list(result.keys()))
    return result
