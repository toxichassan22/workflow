# Startup hook for the workflow app.
# Loaded via PYTHONPATH=/app from Dockerfile so the patch is active before app imports slide_engine.
import importlib.abc
import importlib.machinery
import re
import sys

_LOGO_RE = re.compile(r'(<(?:img|div|span)\b[^>]*class=["\'][^"\']*\bpresentation-chrome-logo\b[^"\']*["\'][^>]*>)', re.I)
_STYLE_RE = re.compile(r'\bstyle\s*=\s*(["\'])(.*?)\1', re.I | re.S)
_DIM_RE = re.compile(r'\b(width|height|max-width|max-height)\s*:\s*([^;"\']+)', re.I)
_LEGACY_HEIGHTS = {"40px", "48px", "50px"}
_RECOVERY_HEIGHT = "78px"


def _capture_logo_dimensions(html):
    captured = []
    if not isinstance(html, str):
        return captured
    for tag in _LOGO_RE.findall(html):
        dims = {}
        match = _STYLE_RE.search(tag)
        if match:
            for name, value in _DIM_RE.findall(match.group(2)):
                dims[name.lower()] = value.strip()
        for name in ("width", "height", "max-width", "max-height"):
            attr = re.search(r'\b' + re.escape(name) + r'\s*=\s*["\']([^"\']+)', tag, re.I)
            if attr:
                dims[name] = attr.group(1).strip()
        if dims:
            captured.append(dims)
    return captured


def _restore_logo_dimensions(html, captured):
    if not isinstance(html, str) or not captured:
        return html
    index = 0

    def replace(match):
        nonlocal index
        if index >= len(captured):
            return match.group(0)
        tag = match.group(0)
        dims = dict(captured[index])
        index += 1
        if dims.get("height", "").strip().lower() in _LEGACY_HEIGHTS:
            dims["height"] = _RECOVERY_HEIGHT
            dims["max-height"] = _RECOVERY_HEIGHT
        style_match = _STYLE_RE.search(tag)
        if style_match:
            quote = style_match.group(1)
            style = style_match.group(2)
            for name, value in dims.items():
                pattern = re.compile(r'(^|;)\s*' + re.escape(name) + r'\s*:\s*[^;]*', re.I)
                replacement = r'\1' + name + ':' + value + '!important'
                if pattern.search(style):
                    style = pattern.sub(replacement, style, count=1)
                else:
                    style = style.rstrip(';') + ';' + name + ':' + value + '!important;'
            start, end = style_match.span(2)
            tag = tag[:start] + style + tag[end:]
        else:
            style = ''.join(name + ':' + value + '!important;' for name, value in dims.items())
            tag = tag[:-1] + ' style="' + style + '">'
        return tag

    return _LOGO_RE.sub(replace, html)


def _wrap_html_function(module, name):
    original = getattr(module, name, None)
    if not callable(original) or getattr(original, "_workflow_logo_resize_wrapped", False):
        return

    def wrapped(html, *args, **kwargs):
        captured = _capture_logo_dimensions(html)
        result = original(html, *args, **kwargs)
        return _restore_logo_dimensions(result, captured)

    wrapped._workflow_logo_resize_wrapped = True
    wrapped.__name__ = getattr(original, "__name__", name)
    wrapped.__doc__ = getattr(original, "__doc__", None)
    setattr(module, name, wrapped)


def _patch_slide_engine(module):
    if getattr(module, "_workflow_logo_resize_patch", False):
        return
    module._workflow_logo_resize_patch = True
    _wrap_html_function(module, "_apply_logo_contrast_styles")
    _wrap_html_function(module, "resolve_logo_in_html")


class _SlideEngineLoader(importlib.abc.Loader):
    def __init__(self, original_loader):
        self.original_loader = original_loader

    def create_module(self, spec):
        if hasattr(self.original_loader, "create_module"):
            return self.original_loader.create_module(spec)
        return None

    def exec_module(self, module):
        self.original_loader.exec_module(module)
        _patch_slide_engine(module)


class _SlideEngineFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "slide_engine":
            return None
        for finder in sys.meta_path:
            if finder is self:
                continue
            if hasattr(finder, "find_spec"):
                spec = finder.find_spec(fullname, path, target)
                if spec is not None and spec.loader is not None:
                    spec.loader = _SlideEngineLoader(spec.loader)
                    return spec
        return None


if not any(isinstance(finder, _SlideEngineFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _SlideEngineFinder())
