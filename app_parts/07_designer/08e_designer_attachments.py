# ── Designer chat attachments ───────────────────────────────────────
# Image normalization + durable persistence, and PDF text extraction
# for the planner. Shared exec namespace — no imports needed here.

DESIGNER_CHAT_MAX_ATTACHED_IMAGES = 3
DESIGNER_CHAT_ATTACHED_IMAGE_LIMIT = 4 * 1024 * 1024


def _normalize_designer_attached_images(data):
    """Collect user-attached chat images as data URIs, newest protocol first.

    Accepts the legacy ``attachedImage`` string plus the newer ``attachedImages`` list
    (strings or {data_uri/url, name} dicts). Only PNG/JPEG/WEBP data URIs within the
    size limit are kept, up to DESIGNER_CHAT_MAX_ATTACHED_IMAGES, so one oversized
    attachment cannot blow up the planner prompt.
    """
    uris = []
    if not isinstance(data, dict):
        return uris

    def _take(value):
        if not isinstance(value, str):
            return
        text = value.strip()
        if not text.startswith('data:image/'):
            return
        header = text.split(',', 1)[0].lower()
        if ';base64,' not in text:
            return
        if not any(kind in header for kind in ('image/png', 'image/jpeg', 'image/jpg', 'image/webp')):
            return
        try:
            raw = base64.b64decode(text.split(',', 1)[1], validate=True)
        except Exception:
            return
        if len(raw) > DESIGNER_CHAT_ATTACHED_IMAGE_LIMIT or len(raw) == 0:
            return
        if text not in uris:
            uris.append(text)

    legacy = data.get('attachedImage')
    _take(legacy if isinstance(legacy, str) else '')
    newer = data.get('attachedImages')
    if isinstance(newer, list):
        for item in newer:
            if isinstance(item, str):
                _take(item)
            elif isinstance(item, dict):
                candidate = item.get('data_uri') or item.get('dataUri') or item.get('url') or ''
                _take(candidate if isinstance(candidate, str) else '')
            if len(uris) >= DESIGNER_CHAT_MAX_ATTACHED_IMAGES:
                break
    return uris[:DESIGNER_CHAT_MAX_ATTACHED_IMAGES]


DESIGNER_CHAT_MAX_ATTACHED_DOCS = 2
DESIGNER_CHAT_ATTACHED_DOC_LIMIT = 4 * 1024 * 1024
DESIGNER_CHAT_DOC_TEXT_CAP = 3000


def _normalize_designer_attached_docs(data):
    """Non-image attachments (PDF) — text extracted for the planner, never
    sent as vision parts. Returns [{'name', 'text'}]."""
    docs = []
    if not isinstance(data, dict):
        return docs
    raw = data.get('attachedDocs') or data.get('attachedDocuments')
    raw = raw if isinstance(raw, list) else ([raw] if raw else [])
    for item in raw[:DESIGNER_CHAT_MAX_ATTACHED_DOCS]:
        uri = ''
        name = 'مستند'
        if isinstance(item, str):
            uri = item
        elif isinstance(item, dict):
            uri = str(item.get('data_uri') or item.get('dataUri') or item.get('url') or '')
            name = str(item.get('name') or name)[:80]
        if not uri.startswith('data:application/pdf') or ';base64,' not in uri:
            continue
        try:
            payload = base64.b64decode(uri.split(',', 1)[1], validate=True)
        except Exception:
            continue
        if not payload or len(payload) > DESIGNER_CHAT_ATTACHED_DOC_LIMIT:
            continue
        text = ''
        try:
            import fitz
            with fitz.open(stream=payload, filetype='pdf') as pdf:
                text = '\n'.join(page.get_text() for page in pdf[:6])
        except Exception as exc:
            print(f"[DESIGNER-AGENT] attached pdf text failed: {exc}")
        text = re.sub(r'\s+', ' ', text).strip()[:DESIGNER_CHAT_DOC_TEXT_CAP]
        docs.append({'name': name, 'text': text})
    return docs


def _persist_designer_attached_images(data_uris, tenant_id):
    """Store chat attachments on disk and return durable URLs for slide HTML.

    Slides must reference a server URL, never a data URI: a data URI in saved HTML
    bloats every later planner prompt and breaks on reload. Falls back to the data
    URI itself only when persisting fails, so the turn can still show the image.
    """
    urls = []
    for uri in data_uris or []:
        try:
            stored = persist_generated_image(uri, tenant_id)
        except Exception:
            stored = uri
        urls.append(stored if isinstance(stored, str) and stored else uri)
    return urls


