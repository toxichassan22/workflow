"""Long-lived render session for the designer agent.

The per-run runner keeps ONE Chromium alive and reuses it to render+measure
every touched slide — the per-call ``render_slide_to_image_base64`` pays a
browser launch per slide, which is untenable inside a task runner.

Exec'd into ``generate_pdf_from_preview`` module globals (part-file convention)
so the existing launch/guard/asset-resolution helpers are directly callable.
"""

import base64


_MEASURE_JS = r"""
() => {
    const slide = document.querySelector('.slide');
    if (!slide) return {ok: false, reason: 'no_slide_root'};
    const sw = slide.clientWidth, sh = slide.clientHeight;
    const report = {ok: true, overflowX: false, overflowY: false,
                    clipped: [], smallText: [], minFontPx: null,
                    slideScroll: {w: slide.scrollWidth, h: slide.scrollHeight}};
    if (slide.scrollWidth > sw + 2) report.overflowX = true;
    if (slide.scrollHeight > sh + 2) report.overflowY = true;
    const sr = slide.getBoundingClientRect();
    const all = slide.querySelectorAll('*');
    let clipped = 0;
    for (const el of all) {
        if (clipped >= 8) break;
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        const overRight = r.right - sr.right;
        const overBottom = r.bottom - sr.bottom;
        const overLeft = sr.left - r.left;
        const overTop = sr.top - r.top;
        const worst = Math.max(overRight, overBottom, overLeft, overTop);
        if (worst > 12 && (el.textContent || '').trim().length > 3) {
            report.clipped.push({
                tag: el.tagName.toLowerCase(),
                cls: (el.className || '').toString().slice(0, 60),
                overPx: Math.round(worst),
                text: (el.textContent || '').trim().slice(0, 60),
            });
            clipped++;
        }
        const fs = parseFloat(getComputedStyle(el).fontSize);
        if (fs && (el.childNodes.length === 0 ||
                   Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim()))) {
            if (report.minFontPx === null || fs < report.minFontPx) report.minFontPx = fs;
            if (fs < 8 && (el.textContent || '').trim()) {
                report.smallText.push({
                    tag: el.tagName.toLowerCase(), px: fs,
                    text: (el.textContent || '').trim().slice(0, 40)});
            }
        }
    }
    if (report.smallText.length > 8) report.smallText = report.smallText.slice(0, 8);
    return report;
}
"""


class SlideRenderSession:
    """One browser for a whole agent run, started lazily on first render.

    ``available`` means "rendering is possible on this host" (Playwright is
    importable and the browser has not already failed to start) — the browser
    itself only launches when ``render`` is first called, so a chat-only agent
    turn never pays for Chromium. ``render`` returns ``(data_uri, report)``;
    when Playwright is unavailable every call returns ``(None, None)`` so the
    runner skips measurement instead of failing the task.
    """

    def __init__(self, branding=None, tenant_id=None, width=1280, height=720):
        self.branding = branding or {}
        self.tenant_id = tenant_id
        self.width = int(width or 1280)
        self.height = int(height or 720)
        self.available = False
        self.error = ''
        self._pw = None
        self._browser = None
        self._page = None
        self._tmp_dir = None
        self._font_css = ''
        self._sync_playwright = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            self.error = f'playwright_unavailable:{exc}'
            return self
        self._sync_playwright = sync_playwright
        self.available = True
        return self

    def _ensure_started(self):
        if self._browser is not None and self._page is not None:
            return True
        if self._sync_playwright is None:
            return False
        try:
            self._tmp_dir = tempfile.mkdtemp(prefix='designer_agent_render_')
            self._pw = self._sync_playwright().start()
            self._browser, _how = _launch_chromium(self._pw)
            self._page = self._browser.new_page(
                viewport={'width': self.width, 'height': self.height})
            _install_export_request_guard(self._page)
            self._font_css, _ff = build_font_css(self.branding, self.tenant_id, embed=True)
            return True
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
            self._teardown()
            self.available = False
            return False

    def __exit__(self, *exc_info):
        self._teardown()
        return False

    def _teardown(self):
        for close in (getattr(self._page, 'close', None),
                      getattr(self._browser, 'close', None),
                      getattr(self._pw, 'stop', None)):
            try:
                if close:
                    close()
            except Exception:
                pass
        self._page = self._browser = self._pw = None
        if self._tmp_dir:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None
        self.available = False

    def _document(self, slide_html):
        tenant_id = self.tenant_id
        html = resolve_logo_in_html(slide_html, tenant_id)
        html = _strip_hidden_watermark_overlays(html)
        html = _resolve_project_file_urls(html, tenant_id)
        html = _resolve_asset_urls(html)
        html = _sanitize_export_resource_urls(html, tenant_id)
        html = sanitize_slide_html_for_export(html)
        slides = extract_slide_elements(html)
        if slides:
            html = _unwrap_spurious_map_summary_cards(slides[0])
        w, h = self.width, self.height
        layout_css = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ margin:0; padding:0; background:#fff; direction:rtl; width:{w}px; height:{h}px; overflow:hidden; }}
.slide {{ width:{w}px !important; height:{h}px !important; direction:rtl; position:relative; overflow:hidden; }}
img {{ max-width:100%; max-height:100%; object-fit:contain; }}
svg[data-chart], svg.combo-chart {{ max-width:100% !important; max-height:320px !important; height:auto !important; display:block; }}
"""
        return ("<!DOCTYPE html><html dir=\"rtl\"><head><meta charset=\"utf-8\">"
                f"<style>{layout_css}</style><style>{self._font_css}</style>"
                "</head><body style=\"margin:0;padding:0;background:#fff;\">"
                f"{html}</body></html>")

    def render(self, slide_html, screenshot=True):
        """Render one slide; returns ``(png_data_uri_or_None, report_or_None)``."""
        if not self.available or not isinstance(slide_html, str) or not slide_html.strip():
            return None, None
        if not self._ensure_started():
            return None, None
        try:
            path = Path(self._tmp_dir) / 'slide_render.html'
            path.write_text(self._document(slide_html), encoding='utf-8')
            self._page.goto(path.as_uri(), wait_until='load', timeout=15000)
            try:
                self._page.evaluate('() => document.fonts.ready')
            except Exception:
                pass
            try:
                report = self._page.evaluate(_MEASURE_JS)
            except Exception:
                report = None
            data_uri = None
            if screenshot:
                buf = self._page.screenshot(type='png')
                data_uri = 'data:image/png;base64,' + base64.b64encode(buf).decode('utf-8')
            return data_uri, report
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
            return None, None


def measure_report_reasons(report):
    """Turn a measure report into failure reasons; empty list means clean."""
    if not isinstance(report, dict) or not report.get('ok'):
        return []
    reasons = []
    if report.get('overflowX') or report.get('overflowY'):
        reasons.append('measured_overflow')
    clipped = report.get('clipped') or []
    if clipped:
        first = clipped[0]
        reasons.append(f'clipped:{first.get("tag")}:{first.get("overPx")}px')
    return reasons


_LAYOUT_TOLERANCE_PX = 8


def _worst_clip_px(report):
    worst = 0
    for item in report.get('clipped') or []:
        try:
            worst = max(worst, int(item.get('overPx') or 0))
        except (TypeError, ValueError, AttributeError):
            continue
    return worst


def measure_regression_reasons(before, after):
    """Failure reasons only for what the edit made WORSE than the source.

    A slide that already overflowed used to fail every later edit — change
    one word and the result is rejected for the overflow it inherited, on
    every attempt. An edit must not break the layout; it is not required to
    repair a fault it did not cause. Without a usable source measurement the
    absolute rule (measure_report_reasons) applies.
    """
    reasons = measure_report_reasons(after)
    if not reasons or not isinstance(before, dict) or not before.get('ok'):
        return reasons
    out = []
    before_scroll = before.get('slideScroll') or {}
    after_scroll = after.get('slideScroll') or {}
    for axis, key in (('overflowX', 'w'), ('overflowY', 'h')):
        if not after.get(axis):
            continue
        if not before.get(axis):
            out.append('measured_overflow')
            break
        try:
            grew = float(after_scroll.get(key) or 0) - float(before_scroll.get(key) or 0)
        except (TypeError, ValueError):
            grew = 0
        if grew > _LAYOUT_TOLERANCE_PX:
            out.append('measured_overflow')
            break
    clipped = after.get('clipped') or []
    if clipped and _worst_clip_px(after) > _worst_clip_px(before) + _LAYOUT_TOLERANCE_PX:
        first = clipped[0]
        out.append(f'clipped:{first.get("tag")}:{first.get("overPx")}px')
    return out


__all__ = ['SlideRenderSession', 'measure_regression_reasons', 'measure_report_reasons']
