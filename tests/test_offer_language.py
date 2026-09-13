"""Offer-language (deck follows data language) guards.

The deck historically rendered Arabic chrome unconditionally. A draft whose
data is overwhelmingly Latin now produces an English deck instead, while every
Arabic or mixed draft keeps the exact historical Arabic output.

Run as a module from the repo root like every other suite::

    python -m unittest tests.test_offer_language
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import slide_engine
from slide_engine import (
    OFFER_LANG_ARABIC,
    OFFER_LANG_ENGLISH,
    PRESENTATION_SECTION_TITLES,
    PRESENTATION_SECTION_TITLES_EN,
)

AR_DRAFT = {
    'project_name': 'برج المارينا',
    'project_idea': 'برج سكني فاخر على الواجهة البحرية في جدة',
    'city': 'جدة',
    'executive_content': '{"summary": "ملخص تنفيذي عن المشروع"}',
    'market_study_data': '{"one_block_summary": "تحليل السوق يوضح قوة الطلب"}',
}

EN_DRAFT = {
    'project_name': 'Marina Gate Tower',
    'project_idea': 'A luxury residential tower on the Jeddah waterfront with sea-view apartments',
    'city': 'Jeddah',
    'executive_content': '{"summary": "Executive summary of the project and its investment thesis"}',
    'market_study_data': '{"one_block_summary": "Market analysis shows strong demand for branded residences"}',
}


def _plan_with_types(*types):
    return {'slides': [{'title': 't%d' % i, 'type': t} for i, t in enumerate(types)]}


class DetectOfferLangTests(unittest.TestCase):
    def test_empty_and_none_default_to_arabic(self):
        self.assertEqual(slide_engine.detect_offer_lang({}), OFFER_LANG_ARABIC)
        self.assertEqual(slide_engine.detect_offer_lang(None), OFFER_LANG_ARABIC)
        self.assertEqual(slide_engine.detect_offer_lang({'project_name': ''}), OFFER_LANG_ARABIC)

    def test_arabic_draft_stays_arabic(self):
        self.assertEqual(slide_engine.detect_offer_lang(AR_DRAFT), OFFER_LANG_ARABIC)

    def test_english_draft_detects_english(self):
        self.assertEqual(slide_engine.detect_offer_lang(EN_DRAFT), OFFER_LANG_ENGLISH)

    def test_mixed_content_stays_arabic(self):
        draft = dict(EN_DRAFT)
        draft['project_idea'] = (
            'A luxury tower with sea views and premium amenities for high-end buyers. '
            'مشروع متكامل يضم وحدات سكنية فاخرة ومرافق تجارية وترفيهية متعددة الاستخدامات'
        )
        self.assertEqual(slide_engine.detect_offer_lang(draft), OFFER_LANG_ARABIC)

    def test_machine_noise_never_flips_to_english(self):
        draft = {
            'project_name': 'برج',
            'draftId': 'c0b05881-9186-455c-b62b-0a187fa566ee',
            'image_tokens': ['##MAP_OVERVIEW##', '##IMAGE_COVER##'],
            'logo_url': 'https://example.com/assets/logo.png',
        }
        self.assertEqual(slide_engine.detect_offer_lang(draft), OFFER_LANG_ARABIC)

    def test_english_with_autofill_fragments_stays_english(self):
        draft = dict(EN_DRAFT)
        draft['city'] = 'جدة'
        draft['district'] = 'حي الياسمين'
        draft['main_roads'] = 'طريق الملك فهد'
        self.assertEqual(slide_engine.detect_offer_lang(draft), OFFER_LANG_ENGLISH)

    def test_tiny_english_stays_arabic(self):
        self.assertEqual(slide_engine.detect_offer_lang({'project_name': 'Tower'}), OFFER_LANG_ARABIC)

    def test_explicit_override_wins(self):
        self.assertEqual(slide_engine.resolve_offer_lang(EN_DRAFT, 'ar'), OFFER_LANG_ARABIC)
        self.assertEqual(slide_engine.resolve_offer_lang(AR_DRAFT, 'en'), OFFER_LANG_ENGLISH)


class SectionTitleTests(unittest.TestCase):
    def test_every_section_has_an_english_title(self):
        missing = [key for key in PRESENTATION_SECTION_TITLES if key not in PRESENTATION_SECTION_TITLES_EN]
        self.assertEqual(missing, [])
        for key, value in PRESENTATION_SECTION_TITLES_EN.items():
            self.assertTrue(value.strip(), key)

    def test_arabic_path_is_unchanged(self):
        for key, value in PRESENTATION_SECTION_TITLES.items():
            self.assertEqual(slide_engine.section_title(key, 'ar'), value)
            self.assertEqual(slide_engine.section_title(key), value)

    def test_english_titles(self):
        self.assertEqual(slide_engine.section_title('market', 'en'), 'Market Analysis')
        self.assertEqual(slide_engine.section_title('closing', 'en'), 'Conclusion')
        self.assertEqual(slide_engine.offer_chrome('cover', 'en'), 'Cover')
        self.assertEqual(slide_engine.offer_chrome('index', 'en'), 'Table of Contents')
        self.assertEqual(slide_engine.offer_chrome('cover', 'ar'), 'الغلاف')


class NormalizePlanTests(unittest.TestCase):
    def test_arabic_plan_keeps_historical_titles(self):
        plan = slide_engine.normalize_presentation_plan(
            _plan_with_types('cover', 'content', 'closing'), AR_DRAFT)
        by_type = {s['type']: s for s in plan['slides']}
        self.assertEqual(by_type['cover']['title'], 'الغلاف')
        self.assertEqual(by_type['index']['title'], 'محتويات العرض')
        self.assertEqual(by_type['closing']['title'], 'الخاتمة')
        self.assertEqual(plan.get('offer_lang'), 'ar')

    def test_english_plan_uses_english_chrome(self):
        plan = slide_engine.normalize_presentation_plan(
            _plan_with_types('cover', 'content', 'closing'), EN_DRAFT)
        by_type = {s['type']: s for s in plan['slides']}
        self.assertEqual(by_type['cover']['title'], 'Cover')
        self.assertEqual(by_type['index']['title'], 'Table of Contents')
        self.assertEqual(by_type['closing']['title'], 'Conclusion')
        self.assertEqual(plan.get('offer_lang'), 'en')
        index = by_type['index']
        titles = [e['title'] for e in index.get('index_entries', [])]
        self.assertTrue(titles)
        for title in titles:
            self.assertNotRegex(title, r'[\u0600-\u06FF]')

    def test_explicit_override_beats_detection(self):
        plan = slide_engine.normalize_presentation_plan(
            _plan_with_types('cover', 'closing'), EN_DRAFT, offer_lang='ar')
        by_type = {s['type']: s for s in plan['slides']}
        self.assertEqual(by_type['closing']['title'], 'الخاتمة')

    def test_section_filter_keeps_offer_lang(self):
        plan = slide_engine.normalize_presentation_plan(
            _plan_with_types('cover', 'content', 'closing'), EN_DRAFT)
        filtered = slide_engine.filter_presentation_plan_sections(plan, ['overview'])
        self.assertIsNotNone(filtered)
        index = next(s for s in filtered['slides'] if s.get('type') == 'index')
        self.assertEqual(index['title'], 'Table of Contents')


class PromptDirectiveTests(unittest.TestCase):
    def test_plan_prompt_arabic_has_no_directive(self):
        prompt = slide_engine.build_slide_plan_prompt(AR_DRAFT, {})
        self.assertNotIn('OUTPUT LANGUAGE', prompt)
        self.assertIn('عنوان الشريحة بالعربي', prompt)

    def test_plan_prompt_english_carries_directive_and_orders(self):
        prompt = slide_engine.build_slide_plan_prompt(EN_DRAFT, {})
        self.assertIn('OUTPUT LANGUAGE', prompt)
        self.assertIn('Slide title in English', prompt)
        self.assertNotIn('عنوان الشريحة بالعربي', prompt)

    def test_slide_user_msg_directive(self):
        slide = {'title': 't', 'type': 'content', 'design_style': 'text'}
        ar_msg = slide_engine.build_slide_user_msg(slide, 1, 3, {}, AR_DRAFT)
        en_msg = slide_engine.build_slide_user_msg(slide, 1, 3, {}, EN_DRAFT)
        self.assertNotIn('OUTPUT LANGUAGE', ar_msg)
        self.assertIn('OUTPUT LANGUAGE', en_msg)
        self.assertIn('dir="ltr"', en_msg)

    def test_fallback_plan_titles(self):
        ar_plan = slide_engine.build_fallback_plan({}, AR_DRAFT)
        en_plan = slide_engine.build_fallback_plan({}, EN_DRAFT)
        self.assertEqual(ar_plan['slides'][0]['title'], 'الغلاف')
        self.assertEqual(en_plan['slides'][0]['title'], 'Cover')
        self.assertEqual(ar_plan['slides'][-1]['title'], 'الخاتمة')
        self.assertEqual(en_plan['slides'][-1]['title'], 'Conclusion')


class RenumberTests(unittest.TestCase):
    def _divider(self, title):
        return {'title': title, 'type': 'section_divider', 'section_key': 'market'}

    def test_arabic_junk_divider_rewritten_arabic(self):
        slides = [self._divider('قسم السوق'), {'title': 'x', 'type': 'content', 'section_key': 'market'}]
        out = slide_engine.renumber_presentation_slides(slides, project_data=AR_DRAFT)
        divider = next(s for s in out if s.get('type') == 'section_divider')
        self.assertEqual(divider['title'], 'تحليل السوق')

    def test_english_divider_preserved(self):
        slides = [self._divider('Market Analysis'), {'title': 'x', 'type': 'content', 'section_key': 'market'}]
        out = slide_engine.renumber_presentation_slides(slides, project_data=EN_DRAFT)
        divider = next(s for s in out if s.get('type') == 'section_divider')
        self.assertEqual(divider['title'], 'Market Analysis')

    def test_english_junk_divider_rewritten_english(self):
        slides = [self._divider('Market Stuff'), {'title': 'x', 'type': 'content', 'section_key': 'market'}]
        out = slide_engine.renumber_presentation_slides(slides, project_data=EN_DRAFT)
        divider = next(s for s in out if s.get('type') == 'section_divider')
        self.assertEqual(divider['title'], 'Market Analysis')


class TextModuleTests(unittest.TestCase):
    def test_executive_prompt_follows_offer_lang(self):
        import executive_content
        facts = {'projectName': 'Marina Gate Tower',
                 'projectIdea': 'A luxury residential tower on the Jeddah waterfront'}
        ar_prompt = executive_content.build_user_prompt('summary', facts)
        en_prompt = executive_content.build_user_prompt('summary', facts, offer_lang='en')
        self.assertIn('كوثيقة عربية رسمية', ar_prompt)
        self.assertNotIn('OUTPUT LANGUAGE', ar_prompt)
        self.assertIn('formal flowing English document', en_prompt)

    def test_market_summary_prompt_follows_offer_lang(self):
        import market_study
        payload = {'projectName': 'Marina Gate Tower', 'projectType': 'Residential',
                   'city': 'Jeddah', 'competitorRadius': '10'}
        ar_prompt = market_study.build_summary_user_prompt(payload, [])
        en_prompt = market_study.build_summary_user_prompt(payload, [], offer_lang='en')
        self.assertIn('فقرة عربية واحدة', ar_prompt)
        ar_system = market_study.build_consultant_system_prompt()
        en_system = market_study.build_consultant_system_prompt(offer_lang='en')
        self.assertNotIn('English paragraph', ar_system)
        self.assertIn('English paragraph', en_system)
        self.assertIn('فقرة عربية واحدة', ar_system)
        self.assertNotIn('فقرة عربية واحدة', en_system)
        self.assertIn('English paragraph', en_prompt)
        self.assertNotIn('فقرة عربية واحدة', en_prompt)

    def test_market_competitors_prompt_unchanged_by_default(self):
        import market_study
        payload = {'projectName': 'X'}
        prompt = market_study.build_competitors_user_prompt(payload, [], mode='generate')
        self.assertIn('قائمة منافسين', prompt)


if __name__ == '__main__':
    unittest.main()
