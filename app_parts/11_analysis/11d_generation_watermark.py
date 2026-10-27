

def _generation_watermark_html(html, branding, requested):
    """Apply the company watermark to one generated slide when the run asked for it.

    The watermark is always the asset stored on the tenant's branding row; the
    request carries the client's yes/no only, never a source URL. A company
    without an uploaded watermark gets an unmarked slide, not an empty overlay.
    """
    if not html or not requested:
        return html
    watermark_path = str((branding or {}).get('watermark_path') or '').strip()
    if not watermark_path:
        return html
    return _apply_slide_watermark(html, watermark_path)
