"""
PDF Design Engine — GLM decides the design, this code renders it.
4 project images only, universal header/footer, decorative elements, icons.
"""

import os
import re
import math
import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.units import mm, cm, inch
from reportlab.lib.colors import HexColor, white, black, Color
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.platypus import Paragraph, Frame, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from config.settings import PROJECT_ROOT

PAGE_W, PAGE_H = 13.333 * inch, 7.5 * inch  # 960×540 pt (16:9)
MARGIN = 20 * mm

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew too large to edit comfortably, so its body
# lives in ordered files under pdf_generator_parts/, exec'd into this module's own
# namespace. Globals, monkeypatching (patch.object(pdf_generator, 'name')) and
# tracebacks are unchanged: parts are compiled with their real path so frames
# point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pdf_generator_parts')
for _part_name in sorted(_n for _n in os.listdir(_PARTS_DIR) if _n.endswith('.py')):
    _part_path = os.path.join(_PARTS_DIR, _part_name)
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_name
except NameError:
    pass
del _PARTS_DIR
