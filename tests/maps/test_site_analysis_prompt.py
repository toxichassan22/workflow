"""Regression checks for site analysis prompt construction.

Verifies that the prompt guides the model toward an investment-positive,
value-focused real-estate consultancy tone rather than a cynical risk-auditor tone.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app
import slide_engine


class SiteAnalysisPromptTests(unittest.TestCase):
    def test_arabic_prompt_carries_investment_positive_directives(self):
        project_data = {
            'project_name': 'برج النخيل',
            'city': 'جدة',
            'main_roads': 'طريق الملك عبدالعزيز',
        }
        system_prompt, prompt = app.build_site_analysis_prompts(
            project_data, slide_engine.OFFER_LANG_ARABIC
        )
        self.assertIn('مستشار استراتيجي', system_prompt)
        self.assertIn('كن إيجابياً ومحفزاً', prompt)
        self.assertIn('المزايا التنافسية', prompt)
        self.assertIn('ابتعد تماماً عن النبرة التشكيكية', prompt)
        self.assertIn('برج النخيل', prompt)

    def test_english_prompt_carries_investment_positive_directives(self):
        project_data = {
            'project_name': 'Palm Tower',
            'city': 'Jeddah',
        }
        system_prompt, prompt = app.build_site_analysis_prompts(
            project_data, slide_engine.OFFER_LANG_ENGLISH
        )
        self.assertIn('senior real-estate investment and development strategist', system_prompt)
        self.assertIn('Maintain an encouraging, positive', prompt)
        self.assertIn('competitive advantages', prompt)
        self.assertIn('Avoid cynical', prompt)
        self.assertIn('Palm Tower', prompt)
