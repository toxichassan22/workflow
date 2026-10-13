"""Vertex AI `generateContent` transport for the browse agents.

Raw-HTTP client for Gemini-on-Vertex (API-key auth). Returns the parsed
response untouched — `usageMetadata` and `groundingMetadata` ride through to
the caller — and every failure comes back as `{"error": {...}}`; this layer
never raises. `responseMimeType` is never set here: JSON mode + tools returns
empty answers on this endpoint.
"""

import os

import requests

VERTEX_BASE = 'https://aiplatform.googleapis.com/v1'
DEFAULT_MODEL = 'gemini-3.8-flash'
DEFAULT_MAX_TOKENS = 4000
DEFAULT_TIMEOUT = 120


def _endpoint(project_id, model):
    return (
        f'{VERTEX_BASE}/projects/{project_id}/locations/global/'
        f'publishers/google/models/{model}:generateContent'
    )


def _err(message, status=None):
    error = {'message': message}
    if status is not None:
        error['status'] = status
    return {'error': error}


def _post(url, api_key, body, timeout):
    """POST once; return (data, status, error_dict)."""
    response = requests.post(
        url,
        headers={'x-goog-api-key': api_key},
        json=body,
        timeout=timeout,
    )
    status = response.status_code
    text = response.text or ''
    if not text.strip():
        return None, status, _err(
            f'Vertex returned an empty body (HTTP {status})', status=status)
    try:
        data = response.json()
    except ValueError:
        return None, status, _err(
            f'Vertex response is not valid JSON (HTTP {status})', status=status)
    if status >= 400:
        api_error = data.get('error') if isinstance(data, dict) else None
        message = api_error.get('message') if isinstance(api_error, dict) else None
        return None, status, _err(
            f'[{status}] {message or text[:300]}', status=status)
    return data, status, None


def _thinking_rejected(error):
    """True when the 400 is about the thinking field itself (e.g. Vertex's
    `Invalid JSON payload received. Unknown name "thinkingLevel"…`) — a 400
    about anything else must not trigger a retry."""
    message = str((error.get('error') or {}).get('message') or '')
    return 'thinking' in message.lower()


def vertex_generate(contents, tools=None, model=None, max_tokens=DEFAULT_MAX_TOKENS,
                    thinking='low', timeout=DEFAULT_TIMEOUT):
    """One Vertex `generateContent` call.

    `contents` is the Vertex-native list (or a plain string, wrapped as a user
    turn); `tools` passes through untouched. `thinking` maps to
    `generationConfig.thinkingConfig.thinkingLevel` — if the API rejects the
    field (a 400 naming it) the call retries once without it, since some
    models reject the field outright.
    """
    # strip(): a stray \r (CRLF endings) or spaces in .env would corrupt the
    # auth header / endpoint — same convention as app.py's env reads.
    project_id = (os.environ.get('GCP_PROJECT_ID') or '').strip()
    api_key = (os.environ.get('GEMINI_API_KEY') or '').strip()
    if not project_id:
        return _err('GCP_PROJECT_ID is missing')
    if not api_key:
        return _err('GEMINI_API_KEY is missing')
    model_name = (model or (os.environ.get('BROWSER_AGENT_MODEL') or '').strip()
                  or DEFAULT_MODEL)
    if isinstance(contents, str):
        contents = [{'role': 'user', 'parts': [{'text': contents}]}]
    body = {
        'contents': contents,
        'generationConfig': {'maxOutputTokens': max_tokens},
    }
    if tools:
        body['tools'] = tools
    if thinking:
        body['generationConfig']['thinkingConfig'] = {'thinkingLevel': thinking}
    url = _endpoint(project_id, model_name)
    try:
        data, status, error = _post(url, api_key, body, timeout)
        if error is not None and status == 400 and thinking and _thinking_rejected(error):
            print(f'[VERTEX] HTTP 400 with thinkingLevel={thinking} on '
                  f'model={model_name}; retrying without thinkingConfig')
            body['generationConfig'].pop('thinkingConfig', None)
            data, status, error = _post(url, api_key, body, timeout)
        return error if error is not None else data
    except requests.exceptions.Timeout:
        print(f'[VERTEX TIMEOUT] model={model_name} timeout={timeout}')
        return _err(f'انتهت مهلة الاتصال بمزوّد Vertex ({timeout} ثانية)')
    except requests.exceptions.ConnectionError as exc:
        print(f'[VERTEX CONNECTION] model={model_name} {exc}')
        return _err('انقطع الاتصال بمزوّد Vertex قبل اكتمال الطلب')
    except Exception as exc:
        print(f'[VERTEX EXCEPTION] model={model_name} {exc}')
        return _err(str(exc))
