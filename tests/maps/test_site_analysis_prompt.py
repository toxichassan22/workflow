"""Regression checks for site analysis prompt construction.

Verifies that the prompt provides balanced, objective, professional instructions
that give the real-estate project and site their full due without fabricated facts.
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
    def test_arabic_prompt_carries_site_analysis_directives(self):
        project_data = {
            'project_name': 'برج النخيل',
            'city': 'جدة',
            'main_roads': 'طريق الملك عبدالعزيز',
        }
        system_prompt, prompt = app.build_site_analysis_prompts(
            project_data, slide_engine.OFFER_LANG_ARABIC
        )
        self.assertIn('محلل مواقع عقارية دقيق', system_prompt)
        self.assertIn('اربط كل فئة بصلاحية الموقع', prompt)
        self.assertIn('المميزات الأولية ونقاط القوة', prompt)
        self.assertIn('برج النخيل', prompt)

    def test_english_prompt_carries_site_analysis_directives(self):
        project_data = {
            'project_name': 'Palm Tower',
            'city': 'Jeddah',
        }
        system_prompt, prompt = app.build_site_analysis_prompts(
            project_data, slide_engine.OFFER_LANG_ENGLISH
        )
        self.assertIn('meticulous real-estate site analyst', system_prompt)
        self.assertIn('Tie every category to how suitable the site is', prompt)
        self.assertIn('features, strengths, and suitable investment opportunities', prompt)
        self.assertIn('Palm Tower', prompt)
