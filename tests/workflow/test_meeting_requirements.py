"""Regression checks for the meeting requirements implemented in this change.

The suite uses a temporary SQLite database and never calls Google or an AI API.
"""

import ast
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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import auth
import db

FRONTEND_JS_ORDER = (
    '00-core.js', '00-core/01_progress.js', '01-nav-auth.js', '02-settings-branding/01_routing.js',
    '02-settings-branding/02_auth_boot.js',
    '03-executive-classification.js', '04-market.js', '05-market-competitors.js',
    '05a-market-summary-chat.js',
    '06-team.js', '07-project-form/01_form_sections.js',
    '07-project-form/02_section_versions.js', '07-project-form/03_best_use.js', '07-project-form/03a_best_use_calculator.js', '07-project-form/03b_best_use_explore.js',
    '08-location-maps/01_tables_approvals.js',
    '08-location-maps/02_catchment_edits.js', '09-financial/01_financial_format.js',
    '09-financial/02_formulas_calc.js', '09-financial/03_parking_planning.js',
    '10-financial-report-timeline/01_report_collect.js',
    '10-financial-report-timeline/02_timeline_sidebar.js',
    '10-financial-report-timeline/03_timeline_board.js', '11-land-croquis/01_croquis_survey.js',
    '11-land-croquis/02_map_edits.js', '11-land-croquis/02a_map_approval_viewport.js',
    '11-land-croquis/03_interactive_map.js', '11-land-croquis/04_land_chat.js', '12-files-media/01_files_media.js',
    '12-files-media/02_visual_concept.js',
    '12-files-media/02a_visual_concept_sections.js',
    '12-files-media/02b_visual_concept_plan_state.js',
    '12-files-media/02c_visual_concept_plans_ui.js',
    '12-files-media/02d_visual_concept_plan_actions.js',
    '12-files-media/02f_plans_distribution_chat.js',
    '12-files-media/03_visual_concept_sketch.js',
    '12-files-media/04_visual_concept_references.js',
    '13-visual/01_visual_concept_page.js',
    '13-visual/02_slides_progress.js', '13-visual/02a_slide_element_drag.js',
    '13-visual/03_tenant_slide_generation.js', '14-slides-gen/01_undo.js',
    '14-slides-gen/02_element_editing.js', '14-slides-gen/03_slide_regeneration.js',
    '15-slide-edit-chat/01_render_inline_edit.js',
    '15-slide-edit-chat/02_designer_chat.js',
    '15-slide-edit-chat/04_slide_activity.js',
    '15-slide-edit-chat/05_designer_job_store.js',
    '15a-slide-workspace/01_workspace.js',
    '15a-slide-workspace/02_sorter.js',
    '15a-slide-workspace/03_chat_composer.js',
    '15b-slide-canvas/01_zoom_inspector.js',
    '15b-slide-canvas/02_snap_selection.js',
    '15b-slide-canvas/03_text_shortcuts.js',
    '15c-presenter/01_share.js',
    '16-presentations-export/01_presentations.js',
    '16-presentations-export/02_admin_dashboard.js',
    '16-presentations-export/02a_admin_charts.js',
    '16-presentations-export/03_export_delivery.js',
    '16-presentations-export/04_sag_company_create.js',
    '17-admin-boot/01_training_rules.js',
    '17-admin-boot/02_users_roles.js',
    '17-admin-boot/03_training_chat_sessions.js', '18-landloom-ops.js',
    '18-landloom-ops/01_package_slider.js', '19-notifications.js',
    '20-live-collab/01_live_collab.js',
)


def _module_file(name):
    """Locate a top-level module: at the repo root, or under modules/<domain>/."""
    direct = ROOT / name
    if direct.is_file():
        return direct
    for candidate in sorted((ROOT / 'modules').rglob(name)):
        if candidate.is_file():
            return candidate
    return direct


def read_module_source(name):
    """Full source of a backend module: the slim <name> file plus every ordered
    part under <stem>_parts/ — grouping subfolders included — in exec order."""
    module_file = _module_file(name)
    text = module_file.read_text(encoding='utf-8')
    parts_dir = module_file.parent / (name[:-3] + '_parts')
    if parts_dir.is_dir():
        for part in sorted(parts_dir.rglob('*.py'), key=lambda p: (p.name, str(p))):
            text += part.read_text(encoding='utf-8')
    return text


def _bundle_order(kind):
    """The bundle's own load order, read from app_parts/22f_frontend_bundles.py.

    The tuple there is the single order authority shared with
    scripts/verify-frontend.js; keeping a second copy here let the list fall
    behind the split, and every file it did not name became invisible to these
    assertions.
    """
    part = (ROOT / 'app_parts' / '22_rules_pages'
            / '22f_frontend_bundles.py')
    name = 'FRONTEND_{}_ORDER'.format(kind.upper())
    try:
        tree = ast.parse(part.read_text(encoding='utf-8'))
    except OSError:
        return ()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name
                   for target in node.targets):
            continue
        try:
            return tuple(ast.literal_eval(node.value))
        except ValueError:
            return ()
    return ()


def _asset_files(subdir, extension, order):
    """The ordered files first, then anything else on disk, so a stale list
    can never hide client source from a literal assertion."""
    root = ROOT / 'assets' / subdir
    files = []
    seen = set()
    for name in order:
        path = root / name
        if path.is_file():
            files.append(path)
            seen.add(path.resolve())
    for path in sorted(root.rglob('*' + extension)):
        if path.resolve() not in seen:
            files.append(path)
    return files


def read_frontend_text():
    """The full client source: shell + styles + scripts in load order.

    index.html was split into assets/css + assets/js; literal-source
    assertions must read the combined text, not the shell alone.
    """
    parts = [(ROOT / 'index.html').read_text(encoding='utf-8')]
    for path in _asset_files('css', '.css', _bundle_order('css')):
        parts.append(path.read_text(encoding='utf-8'))
    for path in _asset_files('js', '.js', _bundle_order('js')):
        parts.append(path.read_text(encoding='utf-8'))
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
_part_files = []
for _dirpath, _dirnames, _filenames in os.walk(_PARTS_DIR):
    _filenames.sort()
    for _n in _filenames:
        if _n.endswith('.py'):
            _part_files.append(os.path.join(_dirpath, _n))
# Subfolders inside test_meeting_requirements_parts/ are human grouping only — exec order is the part
# filename, so a file moves between folders without changing load order.
for _part_path in sorted(_part_files, key=lambda _p: (os.path.basename(_p), _p)):
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_files, _dirpath, _dirnames, _filenames, _n
except NameError:
    pass
del _PARTS_DIR


if __name__ == '__main__':
    unittest.main()


