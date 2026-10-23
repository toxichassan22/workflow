"""Target-only slide patch for a selected element.

A text element the client selected can be edited without sending the rest of
the slide to the model. The server locates exactly one matching element, swaps
it, and falls back untouched when the match is ambiguous.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as application


SLIDE_HTML = (
    '<div class="slide" style="width:1280px;height:720px;">'
    '<h1>العنوان</h1>'
    '<p style="color:#ff0000">النص المحدد</p>'
    '<p>نص آخر NON_TARGET_MARKER</p>'
    '</div>'
)
SELECTED = {
    'slideIndex': 0,
    'tag': 'p',
    'text': 'النص المحدد',
    'className': '',
    'id': '',
    'outerHTML': '<p style="color:#ff0000">النص المحدد</p>',
    'styles': {'color': 'rgb(255, 0, 0)'},
}
REPLACEMENT = '<p style="color:#ff0000;font-weight:700">النص المحدد</p>'


class SelectedElementPatchTests(unittest.TestCase):
    def test_replaces_only_the_selected_element(self):
        result = application._agent_replace_selected_element(
            SLIDE_HTML, SELECTED, REPLACEMENT)
        self.assertIn(REPLACEMENT, result)
        self.assertIn('نص آخر NON_TARGET_MARKER', result)
        self.assertNotIn('color:#ff0000">النص المحدد</p>', result)
        self.assertEqual(result.count('class="slide"'), 1)

    def test_duplicate_text_is_not_patched(self):
        duplicate = SLIDE_HTML.replace(
            '<p>نص آخر NON_TARGET_MARKER</p>',
            '<p style="color:#ff0000">النص المحدد</p>')
        self.assertIsNone(application._agent_replace_selected_element(
            duplicate, SELECTED, REPLACEMENT))

    def test_targeted_prompt_carries_the_element_not_the_full_slide(self):
        captured = {}

        def fake_messages(messages, **kwargs):
            captured['messages'] = messages
            return {'choices': [{'message': {'content': json.dumps({
                'elementHtml': REPLACEMENT, 'summary': 'تم'}, ensure_ascii=False)}}]}

        ctx = {
            'project_data': {'project_name': 'THE VIEW', 'project_type': 'سكني'},
            'tenant_id': None,
            'creative_images': {},
            'branding': {},
            'training_context': '',
            'data': {},
            'presentation_id': None,
            'slides': [{'html': SLIDE_HTML, 'title': 'شريحة',
                        'section_key': 'financial'}],
        }
        with patch.object(application, 'call_openrouter_messages',
                          side_effect=fake_messages):
            element, summary = application._agent_worker_call_element(
                ctx, ctx['slides'][0], 0, 'اجعل النص المحدد عريضاً', SELECTED)

        self.assertEqual(element, REPLACEMENT)
        self.assertEqual(summary, 'تم')
        user_text = captured['messages'][1]['content']
        system_text = captured['messages'][0]['content']
        self.assertIn('النص المحدد', user_text)
        self.assertNotIn('NON_TARGET_MARKER', user_text)
        self.assertNotIn('NON_TARGET_MARKER', system_text)
        self.assertIn('elementHtml', system_text)

    def test_worker_uses_the_targeted_path_for_a_selected_element(self):
        ctx = {
            'project_data': {'project_name': 'THE VIEW', 'project_type': 'سكني'},
            'tenant_id': None,
            'creative_images': {},
            'branding': {},
            'training_context': '',
            'data': {},
            'presentation_id': None,
            'slides': [{'html': SLIDE_HTML, 'title': 'شريحة',
                        'section_key': 'financial'}],
            'selected_element': SELECTED,
        }
        with patch.object(application, '_agent_worker_call_element',
                          return_value=(REPLACEMENT, 'تم')), \
                patch.object(application, '_agent_worker_finalize',
                             side_effect=lambda html, *a, **k: html):
            html, reply = application._agent_worker_edit_slide(
                ctx, ctx['slides'][0], 0, 'اجعل النص المحدد عريضاً', 1)

        self.assertIn(REPLACEMENT, html)
        self.assertIn('NON_TARGET_MARKER', html)
        self.assertEqual(reply, 'تم')


if __name__ == '__main__':
    unittest.main()
