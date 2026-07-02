"""Branding module – company visual identity constants.
Centralizes colors, fonts, logo path, and company info for consistent PPTX output.

Values are loaded from config/branding.yaml when available, falling back to the
code defaults below. This allows non-developers to update brand assets by
editing the YAML file without touching Python code.
"""

import yaml
from pathlib import Path

from pptx.util import Pt
from pptx.dml.color import RGBColor

from config.settings import PROJECT_ROOT


def _hex_to_rgb(hex_str: str) -> RGBColor:
    """Convert '#RRGGBB' → RGBColor."""
    h = hex_str.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _load_yaml_defaults() -> dict:
    """Load branding.yaml or return hardcoded defaults."""
    yaml_path = PROJECT_ROOT / "config" / "branding.yaml"
    data = {}
    if yaml_path.exists():
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            pass
    return data


class _BrandingTokens:
    """Internal token container loaded from YAML with fallback defaults."""

    def __init__(self):
        y = _load_yaml_defaults()
        company = y.get("company", {})
        colors = y.get("colors", {})
        fonts = y.get("fonts", {})
        sizes = y.get("sizes", {})
        slide = y.get("slide", {})
        footer = y.get("footer", {})

        self.COMPANY_NAME_AR = company.get("name_ar", "شركة منافع الاقتصادية للعقار")
        self.COMPANY_NAME_EN = company.get("name_en", "Manafe Economic Co. for Real Estate")
        self.COMPANY_TAGLINE_AR = company.get("tagline_ar", "دراسة جدوى")
        self.COMPANY_TAGLINE_EN = company.get("tagline_en", "Feasibility Study")

        self.PRIMARY = colors.get("primary", "#670D0C")
        self.SECONDARY = colors.get("secondary", "#A7A9AC")
        self.ACCENT = colors.get("accent", "#C2A176")
        self.BG = colors.get("background", "#F8FAFC")
        self.SLIDE_BG = slide.get("background", "#FFFFFF")
        self.SLIDE_TEXT_DARK = slide.get("text_dark", "#32373C")
        self.SLIDE_TEXT_MUTED = slide.get("text_muted", "#757575")

        self.FONT_HEADING = fonts.get("heading", "The Sans Arabic")
        self.FONT_BODY = fonts.get("body", "The Sans Arabic")
        self.FONT_ENGLISH = fonts.get("english", "The Sans Arabic")

        self.FONT_SIZE_TITLE = sizes.get("title", 30)
        self.FONT_SIZE_HEADING = sizes.get("heading", 20)
        self.FONT_SIZE_SUBHEADING = sizes.get("subheading", 16)
        self.FONT_SIZE_BODY = sizes.get("body", 13)
        self.FONT_SIZE_CAPTION = sizes.get("caption", 9)

        self.SLIDE_WIDTH_INCHES = slide.get("width_inches", 13.333)
        self.SLIDE_HEIGHT_INCHES = slide.get("height_inches", 7.5)

        self.FOOTER_TEXT_AR = footer.get("text_ar", "دراسة جدوى - شركة منافع الاقتصادية للعقار")
        self.FOOTER_TEXT_EN = footer.get("text_en", "Feasibility Study - Manafe Economic Co.")


tokens = _BrandingTokens()


class CompanyBranding:
    """Company visual identity constants for presentations."""

    # ── Company Info ──
    COMPANY_NAME_AR: str = tokens.COMPANY_NAME_AR
    COMPANY_NAME_EN: str = tokens.COMPANY_NAME_EN
    COMPANY_TAGLINE_AR: str = tokens.COMPANY_TAGLINE_AR
    COMPANY_TAGLINE_EN: str = tokens.COMPANY_TAGLINE_EN

    # ── Logo ──
    LOGO_PATH: Path = PROJECT_ROOT / "assets" / "logo.png"

    # ── Color Palette ──
    PRIMARY_COLOR: RGBColor = _hex_to_rgb(tokens.PRIMARY)
    SECONDARY_COLOR: RGBColor = _hex_to_rgb(tokens.SECONDARY)
    ACCENT_COLOR: RGBColor = _hex_to_rgb(tokens.ACCENT)
    BACKGROUND_COLOR: RGBColor = _hex_to_rgb(tokens.SLIDE_BG)
    TEXT_COLOR_DARK: RGBColor = _hex_to_rgb(tokens.SLIDE_TEXT_DARK)
    TEXT_COLOR_LIGHT: RGBColor = _hex_to_rgb("#FFFFFF")
    TEXT_COLOR_MUTED: RGBColor = _hex_to_rgb(tokens.SLIDE_TEXT_MUTED)

    # Color HEX strings (for Streamlit CSS)
    PRIMARY_HEX: str = tokens.PRIMARY
    SECONDARY_HEX: str = tokens.SECONDARY
    ACCENT_HEX: str = tokens.ACCENT
    BACKGROUND_HEX: str = tokens.BG

    # ── Typography ──
    FONT_HEADING: str = tokens.FONT_HEADING
    FONT_BODY: str = tokens.FONT_BODY
    FONT_ENGLISH: str = tokens.FONT_ENGLISH
    FONT_SIZE_TITLE: Pt = Pt(tokens.FONT_SIZE_TITLE)
    FONT_SIZE_HEADING: Pt = Pt(tokens.FONT_SIZE_HEADING)
    FONT_SIZE_SUBHEADING: Pt = Pt(tokens.FONT_SIZE_SUBHEADING)
    FONT_SIZE_BODY: Pt = Pt(tokens.FONT_SIZE_BODY)
    FONT_SIZE_CAPTION: Pt = Pt(tokens.FONT_SIZE_CAPTION)

    # ── Slide Dimensions (Widescreen 16:9) ──
    SLIDE_WIDTH_INCHES: float = tokens.SLIDE_WIDTH_INCHES
    SLIDE_HEIGHT_INCHES: float = tokens.SLIDE_HEIGHT_INCHES

    # ── Footer ──
    FOOTER_TEXT_AR: str = tokens.FOOTER_TEXT_AR
    FOOTER_TEXT_EN: str = tokens.FOOTER_TEXT_EN


branding = CompanyBranding()
