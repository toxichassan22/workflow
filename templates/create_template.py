"""
Generate the placeholder company_template.pptx, logo.png, and pattern.png files.
Run once:  python -m templates.create_template
"""

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches
from PIL import Image, ImageDraw, ImageFont
import math

TEMPLATES_DIR = Path(__file__).resolve().parent

def create_template():
    """Create a minimal 16:9 company_template.pptx."""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    out_path = TEMPLATES_DIR / "company_template.pptx"
    prs.save(str(out_path))
    print(f"[OK] Created template: {out_path}")
    return out_path

def create_logo():
    """Create a placeholder logo.png matching the Manafe brand."""
    width, height = 400, 150
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # We won't draw a background, keep it transparent.
    # Just text for the logo.
    
    # Try to load a font, otherwise use default
    try:
        font_large = ImageFont.truetype("arial.ttf", 40)
        font_small = ImageFont.truetype("arial.ttf", 20)
    except OSError:
        font_large = ImageFont.load_default()
        font_small = font_large

    draw.text((width // 2, 50), "Manafe Economic Co.", fill="white", font=font_large, anchor="mm")
    draw.text((width // 2, 100), "Real Estate", fill=(212, 176, 106), font=font_small, anchor="mm")

    out_path = TEMPLATES_DIR / "logo.png"
    img.save(str(out_path))
    print(f"[OK] Created logo: {out_path}")
    return out_path

def create_pattern():
    """Create a geometric pattern to use as overlay in PPTX slides."""
    width, height = 800, 800
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw some thin intersecting triangles
    lines = [
        [(0, 400), (400, 0)],
        [(0, 800), (800, 0)],
        [(400, 800), (800, 400)],
        [(200, 0), (200, 800)],
        [(0, 200), (800, 200)],
    ]
    for line in lines:
        draw.line(line, fill=(255, 255, 255, 50), width=2)
        
    out_path = TEMPLATES_DIR / "pattern.png"
    img.save(str(out_path))
    print(f"[OK] Created pattern: {out_path}")
    return out_path

if __name__ == "__main__":
    create_template()
    create_logo()
    create_pattern()
