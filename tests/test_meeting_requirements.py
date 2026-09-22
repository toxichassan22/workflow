"""Regression checks for the meeting requirements implemented in this change.

The suite uses a temporary SQLite database and never calls Google or an AI API.
"""

import base64
import gzip
import hashlib
import math
import os
import re
import sys
import tempfile
import json
import time
import unittest
import io
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import auth
import db

FRONTEND_JS_ORDER = (
    '00-core.js', '01-nav-auth.js', '02-settings-branding/01_routing.js',
    '02-settings-branding/02_auth_boot.js',
    '03-executive-classification.js', '04-market.js', '05-market-competitors.js',
    '06-team.js', '07-project-form/01_form_sections.js',
    '07-project-form/02_section_versions.js', '08-location-maps/01_tables_approvals.js',
    '08-location-maps/02_catchment_edits.js', '09-financial/01_financial_format.js',
    '09-financial/02_formulas_calc.js',
    '10-financial-report-timeline/01_report_collect.js',
    '10-financial-report-timeline/02_timeline_sidebar.js', '11-land-croquis/01_croquis_survey.js',
    '11-land-croquis/02_map_edits.js', '12-files-media/01_files_media.js',
    '12-files-media/02_visual_concept.js',
    '13-visual/01_visual_concept_page.js',
    '13-visual/02_slides_progress.js',
    '13-visual/03_tenant_slide_generation.js', '14-slides-gen/01_undo.js',
    '14-slides-gen/02_element_editing.js', '14-slides-gen/03_slide_regeneration.js',
    '15-slide-edit-chat/01_render_inline_edit.js',
    '15-slide-edit-chat/02_designer_chat.js',
    '16-presentations-export/01_presentations.js',
    '16-presentations-export/02_admin_dashboard.js',
    '16-presentations-export/03_export_delivery.js',
    '16-presentations-export/04_sag_company_create.js',
    '17-admin-boot/01_training_rules.js',
    '17-admin-boot/02_users_roles.js',
    '17-admin-boot/03_training_chat_sessions.js', '18-landloom-ops.js',
    '19-notifications.js',
)


def read_module_source(name):
    """Full source of a backend module: the slim <name> file plus every ordered
    part under <stem>_parts/ concatenated in exec order."""
    text = (ROOT / name).read_text(encoding='utf-8')
    parts_dir = ROOT / (name[:-3] + '_parts')
    if parts_dir.is_dir():
        for part in sorted(parts_dir.glob('*.py')):
            text += part.read_text(encoding='utf-8')
    return text


def read_frontend_text():
    """The full client source: shell + styles + scripts in load order.

    index.html was split into assets/css + assets/js; literal-source
    assertions must read the combined text, not the shell alone.
    """
    parts = [(ROOT / 'index.html').read_text(encoding='utf-8')]
    for _css in sorted((ROOT / 'assets' / 'css').rglob('*.css')):
        parts.append(_css.read_text(encoding='utf-8'))
    for name in FRONTEND_JS_ORDER:
        parts.append((ROOT / 'assets' / 'js' / name).read_text(encoding='utf-8'))
    return '\n'.join(parts)


def read_shell_text():
    """index.html alone: markup plus resource references, no inline code."""
    return read_frontend_text()



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew too large to edit comfortably, so its body
# lives in ordered files under tests/test_meeting_requirements_parts/, exec'd into this module's own
# namespace. Globals, monkeypatching (patch.object(test_meeting_requirements, 'name')) and
# tracebacks are unchanged: parts are compiled with their real path so frames
# point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_meeting_requirements_parts')
for _part_name in sorted(_n for _n in os.listdir(_PARTS_DIR) if _n.endswith('.py')):
    _part_path = os.path.join(_PARTS_DIR, _part_name)
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_name
except NameError:
    pass
del _PARTS_DIR


if __name__ == '__main__':
    unittest.main()


