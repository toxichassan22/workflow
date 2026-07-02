"""
LLM Service – OpenRouter (OpenAI-compatible) using DeepSeek V4 Pro model.
Provides premium intelligent text and JSON completions via OpenRouter.
"""

import base64
import io
import json
import logging
import os
import re
from typing import Any, Optional

from openai import OpenAI
from config.settings import settings
from services.api_keys import get_openrouter_api_key, get_zai_api_key
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro")
OPENROUTER_CHAT_MODEL = os.getenv("OPENROUTER_CHAT_MODEL", "google/gemini-3.5-flash")


def _get_api_key() -> str:
    zk = get_zai_api_key()
    if zk:
        return zk
    return get_openrouter_api_key()


_client: Optional[OpenAI] = None
_client_key: Optional[str] = None
_client_type: Optional[str] = None


def _get_client_info() -> tuple[str, str, str, str]:
    zai_key = get_zai_api_key()
    if zai_key:
        return zai_key, "zai", "https://api.z.ai/api/paas/v4", "glm-5.1"
    
    or_key = get_openrouter_api_key()
    if or_key:
        return or_key, "openrouter", OPENROUTER_BASE_URL, OPENROUTER_MODEL
    
    return "", "", "", ""


def _get_client() -> tuple[OpenAI, str]:
    global _client, _client_key, _client_type
    key, provider, base_url, model = _get_client_info()
    if not key:
        raise ValueError(
            "API Key is missing. "
            "Please set ZAI_KEY or OPENROUTER_API_KEY in your environment, or provide it in the API settings sidebar."
        )
    if _client is None or _client_key != key or _client_type != provider:
        _client = OpenAI(
            base_url=base_url,
            api_key=key,
        )
        _client_key = key
        _client_type = provider
    return _client, model


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
def _generate_content_inner(system_prompt: str, user_prompt: str, images: list[dict] = None) -> str:
    """Inner retried text generation logic."""
    system_prompt = _truncate_prompt(system_prompt)
    user_prompt = _truncate_prompt(user_prompt)
    client, model = _get_client()
    logger.info("LLM request (%s): %s...", model, user_prompt[:80])

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
        content = response.choices[0].message.content or ""
        logger.info("LLM response: %d chars", len(content))
        return content
    except Exception as e:
        logger.error("LLM text generation failed: %s", e, exc_info=True)
        raise e


def _truncate_prompt(text: str, max_chars: int = 12000) -> str:
    """Truncate a prompt to stay within model context limits."""
    if len(text) <= max_chars:
        return text
    logger.warning("Prompt truncated from %d to %d chars", len(text), max_chars)
    return text[:max_chars]


def generate_content(system_prompt: str, user_prompt: str, images: list[dict] = None) -> str:
    """Generate text content. Fails instantly if key is missing."""
    system_prompt = _truncate_prompt(system_prompt)
    user_prompt = _truncate_prompt(user_prompt)
    if not _get_api_key():
        raise ValueError(
            "API Key is missing. "
            "Please set ZAI_KEY or OPENROUTER_API_KEY in your environment, or provide it in the API settings sidebar."
        )
    return _generate_content_inner(system_prompt, user_prompt, images)


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    retry=lambda retry_state: _is_retryable(retry_state.outcome.exception()) if retry_state.outcome and retry_state.outcome.failed else False,
    reraise=True,
)
def _generate_json_inner(system_prompt: str, user_prompt: str, stream_callback=None, images: list[dict] = None, use_chat_model: bool = False) -> dict[str, Any]:
    """Inner retried JSON generation logic."""
    system_prompt = _truncate_prompt(system_prompt)
    user_prompt = _truncate_prompt(user_prompt)
    client, model = _get_client()
    global _client_type
    
    if _client_type == "openrouter":
        target_model = OPENROUTER_CHAT_MODEL if use_chat_model else model
    else:
        target_model = model
        
    logger.info("LLM JSON request (%s): %s...", target_model, user_prompt[:80])

    # Force JSON output via system prompt instruction
    json_system = system_prompt + "\n\nCRITICAL: You MUST output ONLY valid JSON. No markdown, no explanation, no extra text. Output raw JSON only."
    
    # Handle multimodal images
    if images:
        user_content = [{"type": "text", "text": user_prompt}]
        for img in images:
            mime = img.get("mime_type", "image/jpeg")
            b64_data = img.get("base64", "")
            if b64_data:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64_data}"}
                })
    else:
        user_content = user_prompt

    messages = [
        {"role": "system", "content": json_system},
        {"role": "user", "content": user_content},
    ]

    raw = ""
    try:
        if stream_callback:
            # Streaming mode
            stream = client.chat.completions.create(
                model=target_model,
                messages=messages,
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    raw += delta.content
                    stream_callback(raw)
        else:
            response = client.chat.completions.create(
                model=target_model,
                messages=messages,
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
            )
            raw = response.choices[0].message.content or "{}"

        # Robust JSON extraction — handles markdown fences, leading text, etc.
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
        if match:
            raw = match.group(1)
        else:
            start_idx = raw.find('{')
            start_arr_idx = raw.find('[')
            if start_arr_idx != -1 and (start_idx == -1 or start_arr_idx < start_idx):
                start_idx = start_arr_idx
                end_idx = raw.rfind(']')
            else:
                end_idx = raw.rfind('}')

            if start_idx != -1 and end_idx != -1:
                raw = raw[start_idx:end_idx + 1]

        logger.info("LLM JSON response: %d chars", len(raw))
        return json.loads(raw)
    except Exception as e:
        logger.error("LLM JSON generation failed: %s", e, exc_info=True)
        # Try to auto-repair by adding closing brackets.
        closures = ['"}', '"]}', ']}', '}']
        for closure in closures:
            try:
                return json.loads(raw + closure)
            except json.JSONDecodeError:
                continue
        raise ValueError(
            f"LLM did not return valid JSON after auto-repair attempts. "
            f"Error: {e}. Raw content (first 500 chars): {raw[:500]}"
        )


def generate_json(system_prompt: str, user_prompt: str, stream_callback=None, images: list[dict] = None, use_chat_model: bool = False) -> dict[str, Any]:
    """Generate structured JSON content. Fails instantly if key is missing."""
    if not _get_api_key():
        raise ValueError(
            "API Key is missing. "
            "Please set ZAI_KEY or OPENROUTER_API_KEY in your environment, or provide it in the API settings sidebar."
        )
    return _generate_json_inner(system_prompt, user_prompt, stream_callback, images, use_chat_model)
