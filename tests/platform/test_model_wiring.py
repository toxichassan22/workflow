"""Text runs on GPT-6.1-sol at max reasoning; Argon is the vision model only.

Owner rule (2026-10-27): every text/analysis call answers on
``openai/gpt-6.1-sol`` with ``reasoning_effort='max'``.
``google/gemini-4-argon`` stays only on calls that actually send an image or a
scanned document (site polygon, land analysis, visual-concept references,
map references, attached images) until a better vision model is chosen.
"""

import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as application


def read_part(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


class _FakeResponse:
    status_code = 200
    encoding = 'utf-8'

    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _chat_payload():
    return {'choices': [{'message': {'content': 'ok'}}], 'usage': {}}


class ModelConstantTests(unittest.TestCase):

    def test_text_model_is_sol_6_1_at_low_effort(self):
        self.assertEqual(application.GEMINI_TEXT_MODEL, 'openai/gpt-6.1-sol')
        self.assertEqual(application.TEXT_REASONING_EFFORT, 'low')
        self.assertEqual(application.LUNA_TEXT_MODEL, application.GEMINI_TEXT_MODEL)
        self.assertEqual(application.VISUAL_PLAN_TEXT_MODEL, application.GEMINI_TEXT_MODEL)
        self.assertEqual(application.DESIGNER_AGENT_PLANNER_MODEL, application.GEMINI_TEXT_MODEL)
        self.assertEqual(application.DESIGNER_AGENT_WORKER_MODEL, application.GEMINI_TEXT_MODEL)
        self.assertEqual(application.MARKET_STUDY_MODEL, application.GEMINI_TEXT_MODEL)

    def test_vision_model_stays_argon(self):
        self.assertEqual(application.VISION_MODEL, 'google/gemini-4-argon')
        self.assertEqual(application.LAND_ANALYSIS_MODEL, application.VISION_MODEL)

    def test_text_chat_defaults_to_max_effort(self):
        captured = {}
        with patch.object(application, '_has_any_openrouter_key', return_value=True), \
                patch.object(application, '_tenant_key_gate', return_value=None), \
                patch.object(application, '_openrouter_headers', return_value={}), \
                patch.object(application, '_begin_ai_attempt_record', return_value=None), \
                patch.object(application, '_settle_ai_attempt_record', return_value=None), \
                patch.object(application.requests, 'post',
                             side_effect=lambda url, headers=None, json=None, timeout=None:
                             (captured.update(json), _FakeResponse(_chat_payload()))[1]):
            response = application.call_text_chat('system', 'user', max_tokens=100)
        self.assertNotIn('error', response)
        self.assertEqual(captured['model'], application.GEMINI_TEXT_MODEL)
        self.assertEqual(captured['reasoning_effort'], application.TEXT_REASONING_EFFORT)

    def test_vision_chat_keeps_no_default_effort(self):
        captured = {}
        with patch.object(application, '_has_any_openrouter_key', return_value=True), \
                patch.object(application, '_tenant_key_gate', return_value=None), \
                patch.object(application, '_openrouter_headers', return_value={}), \
                patch.object(application, '_begin_ai_attempt_record', return_value=None), \
                patch.object(application, '_settle_ai_attempt_record', return_value=None), \
                patch.object(application.requests, 'post',
                             side_effect=lambda url, headers=None, json=None, timeout=None:
                             (captured.update(json), _FakeResponse(_chat_payload()))[1]):
            response = application.call_openrouter_chat(
                'system', 'user', model=application.VISION_MODEL, max_tokens=100)
        self.assertNotIn('error', response)
        self.assertEqual(captured['model'], application.VISION_MODEL)
        self.assertNotIn('reasoning_effort', captured)

    def test_no_module_hardcodes_argon_as_a_model(self):
        offenders = []
        for folder in ('app_parts', 'modules'):
            for path in sorted((ROOT / folder).rglob('*.py')):
                text = path.read_text(encoding='utf-8')
                if re.search(r"model\s*=\s*['\"]google/gemini-4-argon['\"]", text):
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


class VisionWiringTests(unittest.TestCase):

    def test_vision_paths_select_the_vision_model(self):
        expectations = {
            'app_parts/11_analysis/11a_site_analysis_maps.py': "'model': VISION_MODEL",
            'app_parts/01_ai/03_image_api.py':
                'VISION_MODEL if references else GEMINI_TEXT_MODEL',
            'app_parts/05_visual_plan/05ae_visual_plan_scene.py':
                'VISION_MODEL if references else GEMINI_TEXT_MODEL',
            'app_parts/05_visual_plan/06b_visual_concept_edit.py':
                'VISION_MODEL if (base_image or extra_images) else GEMINI_TEXT_MODEL',
            'app_parts/07_designer/09a_designer_agent.py': 'VISION_MODEL if planner_vision',
            'app_parts/07_designer/09c_designer_agent_worker.py': 'VISION_MODEL if worker_vision',
            'app_parts/07_designer/09_designer_chat.py':
                'model=VISION_MODEL if user_image_refs else GEMINI_TEXT_MODEL',
            'app_parts/07_designer/08b_designer_edit_slide.py':
                'model=VISION_MODEL if image_refs else GEMINI_TEXT_MODEL',
        }
        for relative, marker in expectations.items():
            self.assertIn(marker, read_part(relative), relative)

    def test_land_documents_ride_the_vision_model(self):
        self.assertIn('LAND_ANALYSIS_MODEL = VISION_MODEL',
                      read_part('app_parts/15_team/15_team_and_regulations.py'))

    def test_attached_training_images_ride_the_vision_model(self):
        source = read_part('app_parts/20_admin/21_training_data.py')
        self.assertIn('"model": VISION_MODEL', source)
        self.assertIn('VISION_MODEL if attachment_images else GEMINI_TEXT_MODEL', source)


class TextWiringTests(unittest.TestCase):

    def test_text_workflows_pass_max_effort(self):
        expectations = {
            'app_parts/17_market/18a_executive_content.py': 'reasoning_effort=TEXT_REASONING_EFFORT',
            'app_parts/17_market/18f_summary_chat.py': 'reasoning_effort=TEXT_REASONING_EFFORT',
            'app_parts/17_market/18h_market_summary_research.py':
                "or TEXT_REASONING_EFFORT)",
            'app_parts/05_visual_plan/05a_visual_concept_plan.py': 'reasoning_effort=TEXT_REASONING_EFFORT',
            'app_parts/05_visual_plan/05ad_visual_plan_contract.py': 'reasoning_effort=TEXT_REASONING_EFFORT',
            'app_parts/05_visual_plan/06_visual_concept_routes.py': 'reasoning_effort=TEXT_REASONING_EFFORT',
            'app_parts/07_designer/09c_designer_agent_worker.py': 'reasoning_effort=TEXT_REASONING_EFFORT',
            'app_parts/20_admin/21b_training_chat_actions.py': 'reasoning_effort=TEXT_REASONING_EFFORT',
        }
        for relative, marker in expectations.items():
            self.assertIn(marker, read_part(relative), relative)

    def test_market_browse_calls_follow_the_text_model_and_max_effort(self):
        texts = {
            'app_parts/17_market/17b_competitor_verify.py': 'reasoning_effort=TEXT_REASONING_EFFORT',
            'app_parts/17_market/18g_market_study_routes.py': 'reasoning_effort=TEXT_REASONING_EFFORT',
            'app_parts/17_market/18i_market_competitors_parallel.py': 'reasoning_effort=TEXT_REASONING_EFFORT',
            'app_parts/19_uploads/19a_competitor_media_fetch.py': 'reasoning_effort=TEXT_REASONING_EFFORT',
        }
        for relative, marker in texts.items():
            self.assertIn(marker, read_part(relative), relative)
        self.assertNotIn('model=GEMINI_TEXT_MODEL',
                         read_part('app_parts/19_uploads/19a_competitor_media_fetch.py'))


if __name__ == '__main__':
    unittest.main()
