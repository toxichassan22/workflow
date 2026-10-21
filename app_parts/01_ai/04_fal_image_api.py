import base64
import os
import requests

FAL_KEY = os.environ.get('FAL_KEY', '').strip()
FAL_API_BASE = os.environ.get('FAL_API_BASE', 'https://fal.run').rstrip('/')
FAL_FLUX_CONTROLNET_ENDPOINT = os.environ.get('FAL_FLUX_CONTROLNET_ENDPOINT', 'fal-ai/flux-general')
FAL_FLUX_CANNY_PATH = os.environ.get('FAL_FLUX_CANNY_PATH', 'InstantX/FLUX.1-dev-Controlnet-Canny')
FAL_DEFAULT_CONDITIONING_SCALE = float(os.environ.get('FAL_DEFAULT_CONDITIONING_SCALE', '0.80'))


def has_fal_key():
    """True when a valid Fal.ai API key is configured in the environment."""
    return bool(os.environ.get('FAL_KEY', '').strip() or FAL_KEY)


def call_fal_flux_controlnet(prompt, control_image, usage_ctx=None, conditioning_scale=None, timeout=180):
    """Invoke Fal.ai FLUX ControlNet (Canny) with the given architectural control image.

    Conditioning locks the geometry and edges of the diagram while rendering photorealistic
    materials onto the exact masses without perspective drift or building redistribution.
    Returns the generated image as a data:image/...;base64,... URI on success, or None on failure.
    """
    api_key = os.environ.get('FAL_KEY', '').strip() or FAL_KEY
    if not api_key:
        return None

    ctx = usage_ctx or _usage_ctx('image')
    if run_control.run_is_cancelled(ctx):
        return None

    scale = conditioning_scale if conditioning_scale is not None else FAL_DEFAULT_CONDITIONING_SCALE
    tenant_id = (ctx or {}).get('tenant_id')
    prepared = _normalize_image_references([control_image], tenant_id=tenant_id)
    if not prepared:
        return None
    control_image_data_uri = prepared[0]

    headers = {
        'Authorization': f'Key {api_key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'prompt': prompt,
        'image_size': 'landscape_16_9',
        'num_inference_steps': 28,
        'guidance_scale': 3.5,
        'controlnets': [
            {
                'path': FAL_FLUX_CANNY_PATH,
                'control_image_url': control_image_data_uri,
                'conditioning_scale': scale,
            }
        ],
        'enable_safety_checker': False,
    }

    url = f'{FAL_API_BASE}/{FAL_FLUX_CONTROLNET_ENDPOINT}'
    attempt_id = _begin_ai_attempt_record(ctx, FAL_FLUX_CONTROLNET_ENDPOINT)
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if response.status_code != 200:
            _settle_ai_attempt_record(attempt_id, 'error', {'cost_usd': 0.0}, None)
            return None
        data = response.json() if response.content else {}
        images = data.get('images') or []
        if not images or not isinstance(images, list) or not images[0].get('url'):
            _settle_ai_attempt_record(attempt_id, 'error', {'cost_usd': 0.0}, None)
            return None

        # Settle usage record (~$0.04 estimated cost for FLUX ControlNet megapixel)
        _settle_ai_attempt_record(attempt_id, 'ok', {'cost_usd': 0.04}, None)

        img_url = images[0]['url']
        # Fetch image bytes so it can be persisted locally
        img_res = requests.get(img_url, timeout=30)
        if img_res.status_code == 200:
            b64_data = base64.b64encode(img_res.content).decode('ascii')
            content_type = images[0].get('content_type') or 'image/jpeg'
            return f'data:{content_type};base64,{b64_data}'
        return img_url
    except Exception as exc:
        _settle_ai_attempt_record(attempt_id, 'error', {'cost_usd': 0.0}, None)
        return None
