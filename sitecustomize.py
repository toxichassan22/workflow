"""Runtime compatibility patch for persisted slide-logo dimensions.

The presentation pipeline rebuilds the managed chrome when an existing presentation is
opened. That rebuild intentionally creates the company/project chrome at a canonical
40px height, which used to overwrite a user's manual resize stored in the slide HTML.

This module is loaded by Python's normal ``site`` startup hook and installs a very small
import-time patch for ``slide_engine``. It preserves the explicit width/height (and their
max constraints) of every managed ``presentation-chrome-logo`` found in the persisted HTML
while ``renumber_presentation_slides`` refreshes the rest of the chrome.
"""

import importlib.abc
import importlib.machinery
import re
import sys

_TARGET = "slide_engine"


def _style_properties(style):
    result = {}
    for declaration in str(style or "").split(";"):
        if ":" not in declaration:
            continue
        name, value = declaration.split(":", 1)
        result[name.strip().lower()] = value.strip()
    return result


def _capture_logo_dimensions(html):
    """Capture explicit dimensions in DOM order for managed chrome logos."""
    captured = []
    for match in re.finditer(
        r'<img\b[^>]*\bclass=["\'][^"\']*\bpresentation-chrome-logo\b[^"\']*["\'][^>]*>',
        str(html or ""),
        flags=re.IGNORECASE,
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
    """Restore saved dimensions without changing contrast/background rules."""
    if not html or not captured:
        return html
    position = 0

    def restore(match):
        nonlocal position
        if position >= len(captured):
            return match.group(0)
        dimensions = captured[position]
        position += 1
        tag = match.group(0)
        style_match = re.search(r'\bstyle\s*=\s*(["\'])(.*?)\1', tag, flags=re.IGNORECASE | re.DOTALL)
        declarations = "".join(f"{key}:{value}!important;" for key, value in dimensions.items())
        if style_match:
            style = style_match.group(2)
            for key in dimensions:
                style = re.sub(
                    rf'(^|;)\s*{re.escape(key)}\s*:[^;]*;?',
                    r'\1',
                    style,
                    flags=re.IGNORECASE,
                )
            style = style.rstrip("; ") + (";" if style.strip() else "") + declarations
            return tag[:style_match.start(2)] + style + tag[style_match.end(2):]
        return tag.replace("<img", f'<img style="{declarations}"', 1)

    return re.sub(
        r'<img\b[^>]*\bclass=["\'][^"\']*\bpresentation-chrome-logo\b[^"\']*["\'][^>]*>',
        restore,
        html,
        flags=re.IGNORECASE,
    )


def _patch_slide_engine(module):
    if getattr(module, "_workflow_logo_resize_patch", False):
        return
    original = getattr(module, "renumber_presentation_slides", None)
    if not callable(original):
        return

    def patched_renumber_presentation_slides(
        slides, branding=None, project_data=None, tenant_id=None,
        allow_all_maps=False, creative_images=None,
    ):
        saved_dimensions = []
        for item in slides if isinstance(slides, list) else []:
            html = item.get("html", "") if isinstance(item, dict) else ""
            saved_dimensions.append(_capture_logo_dimensions(html))

        result = original(
            slides,
            branding=branding,
            project_data=project_data,
            tenant_id=tenant_id,
            allow_all_maps=allow_all_maps,
            creative_images=creative_images,
        )

        if isinstance(result, list):
            for index, item in enumerate(result):
                if not isinstance(item, dict) or index >= len(saved_dimensions):
                    continue
                dimensions = saved_dimensions[index]
                if dimensions and item.get("html"):
                    item["html"] = _restore_logo_dimensions(item["html"], dimensions)
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
        if spec is not None and spec.loader is not None:
            spec.loader = _LoaderProxy(spec.loader)
        return spec


if not any(isinstance(item, _Finder) for item in sys.meta_path):
    sys.meta_path.insert(0, _Finder())
