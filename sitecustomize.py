"""Runtime compatibility patch for persisted slide-logo dimensions."""
import importlib.abc
import importlib.machinery
import re
import sys

_TARGET = "slide_engine"
_LEGACY_HEIGHTS = {"40px", "48px", "50px"}
_RECOVERY_HEIGHT = "78px"


def _style_properties(style):
    result = {}
    for declaration in str(style or "").split(";"):
        if ":" not in declaration:
            continue
        name, value = declaration.split(":", 1)
        result[name.strip().lower()] = value.strip()
    return result


def _capture_logo_dimensions(html):
    captured = []
    for match in re.finditer(
        r'<img\b[^>]*\bclass=["\'][^"\']*\bpresentation-chrome-logo\b[^"\']*["\'][^>]*>',
        str(html or ""), flags=re.IGNORECASE,
    ):
        tag = match.group(0)
        style_match = re.search(r'\bstyle\s*=\s*(["\'])(.*?)\1', tag, flags=re.IGNORECASE | re.DOTALL)
        props = _style_properties(style_match.group(2) if style_match else "")
        dimensions = {
            key: props[key]
            for key in ("width", "height", "max-width", "max-height")
            if props.get(key)
        }
        if dimensions:
            captured.append(dimensions)
    return captured


def _restore_logo_dimensions(html, captured):
    if not html or not captured:
        return html
    position = 0

    def restore(match):
        nonlocal position
        if position >= len(captured):
            return match.group(0)
        dimensions = dict(captured[position])
        position += 1
        height = dimensions.get("height", "").lower().replace("!important", "").strip()
        if height in _LEGACY_HEIGHTS:
            dimensions["height"] = _RECOVERY_HEIGHT
            dimensions["max-height"] = _RECOVERY_HEIGHT

        tag = match.group(0)
        style_match = re.search(r'\bstyle\s*=\s*(["\'])(.*?)\1', tag, flags=re.IGNORECASE | re.DOTALL)
        declarations = "".join(f"{key}:{value}!important;" for key, value in dimensions.items())
        if style_match:
            style = style_match.group(2)
            for key in dimensions:
                style = re.sub(
                    rf'(^|;)\s*{re.escape(key)}\s*:[^;]*;?',
                    r'\1', style, flags=re.IGNORECASE,
                )
            style = style.rstrip("; ") + (";" if style.strip() else "") + declarations
            return tag[:style_match.start(2)] + style + tag[style_match.end(2):]
        return tag.replace("<img", f'<img style="{declarations}"', 1)

    return re.sub(
        r'<img\b[^>]*\bclass=["\'][^"\']*\bpresentation-chrome-logo\b[^"\']*["\'][^>]*>',
        restore, html, flags=re.IGNORECASE,
    )


def _wrap_html_function(module, name):
    original = getattr(module, name, None)
    if not callable(original) or getattr(original, "_workflow_logo_resize_wrapper", False):
        return

    def wrapped(html, *args, **kwargs):
        captured = _capture_logo_dimensions(html)
        result = original(html, *args, **kwargs)
        return _restore_logo_dimensions(result, captured) if captured else result

    wrapped.__name__ = original.__name__
    wrapped.__doc__ = original.__doc__
    wrapped.__wrapped__ = original
    wrapped._workflow_logo_resize_wrapper = True
    setattr(module, name, wrapped)


def _patch_slide_engine(module):
    if getattr(module, "_workflow_logo_resize_patch", False):
        return

    # Patch the exact chrome-styling layer. This is the important part: the
    # renderer can call it from several paths, not only from renumbering.
    _wrap_html_function(module, "_apply_logo_contrast_styles")

    original = getattr(module, "renumber_presentation_slides", None)
    if not callable(original):
        return

    def patched_renumber_presentation_slides(
        slides, branding=None, project_data=None, tenant_id=None,
        allow_all_maps=False, creative_images=None,
    ):
        saved_dimensions = [
            _capture_logo_dimensions(item.get("html", "") if isinstance(item, dict) else "")
            for item in (slides if isinstance(slides, list) else [])
        ]
        result = original(
            slides, branding=branding, project_data=project_data, tenant_id=tenant_id,
            allow_all_maps=allow_all_maps, creative_images=creative_images,
        )
        if isinstance(result, list):
            for index, item in enumerate(result):
                if isinstance(item, dict) and index < len(saved_dimensions) and saved_dimensions[index] and item.get("html"):
                    item["html"] = _restore_logo_dimensions(item["html"], saved_dimensions[index])
        return result

    patched_renumber_presentation_slides.__name__ = original.__name__
    patched_renumber_presentation_slides.__doc__ = original.__doc__
    patched_renumber_presentation_slides.__wrapped__ = original
    module.renumber_presentation_slides = patched_renumber_presentation_slides
    module._workflow_logo_resize_patch = True


class _LoaderProxy:
    def __init__(self, loader):
        self._loader = loader

    def create_module(self, spec):
        creator = getattr(self._loader, "create_module", None)
        return creator(spec) if creator else None

    def exec_module(self, module):
        self._loader.exec_module(module)
        _patch_slide_engine(module)

    def __getattr__(self, name):
        return getattr(self._loader, name)


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != _TARGET:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and spec.loader:
            spec.loader = _LoaderProxy(spec.loader)
        return spec


if not any(isinstance(item, _Finder) for item in sys.meta_path):
    sys.meta_path.insert(0, _Finder())
