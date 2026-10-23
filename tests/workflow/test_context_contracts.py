"""Section-scoped project facts.

Every slide prompt used to carry the entire project brief. These cases pin the
one place that decides which project sections a deck section actually needs,
and prove that a section run no longer receives unrelated blocks.
"""

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import context_contracts
import slide_engine


PROJECT = {
    'project_name': 'THE VIEW',
    'city': 'جدة',
    'project_type': 'سكني',
    'contact_phone': 'CONTACT_MARKER',
    'market_study_data': json.dumps(
        {'one_block_summary': 'MARKET_MARKER'}, ensure_ascii=False),
    'team_selection': json.dumps(
        {'local': [{'name': 'TEAM_MARKER', 'role': 'مستشار'}]}, ensure_ascii=False),
    'executive_content': json.dumps(
        {'brief': 'EXEC_MARKER'}, ensure_ascii=False),
    'project_components_data': json.dumps(
        [{'name': 'COMPONENT_MARKER', 'units': 3}], ensure_ascii=False),
}


class ContextContractTests(unittest.TestCase):
    def test_deck_and_project_scopes_map_to_fact_sections(self):
        self.assertEqual(
            context_contracts.fact_section_keys(('financial',)),
            ('basic', 'land_croquis', 'section-financial-calc', 'section-timeline'))
        self.assertEqual(
            context_contracts.fact_section_keys(('section-market-study',)),
            ('basic', 'location', 'section-market-study'))
        self.assertIsNone(context_contracts.fact_section_keys(('executive_summary',)))
        self.assertIsNone(context_contracts.fact_section_keys(('unknown_section',)))

    def test_section_facts_exclude_unrelated_blocks(self):
        facts = slide_engine.build_project_facts(
            PROJECT, tenant_id=None,
            section_keys=('basic', 'section-market-study'))
        self.assertIn('THE VIEW', facts)
        self.assertIn('MARKET_MARKER', facts)
        self.assertNotIn('TEAM_MARKER', facts)
        self.assertNotIn('CONTACT_MARKER', facts)
        self.assertNotIn('EXEC_MARKER', facts)

    def test_full_facts_keep_every_special_block(self):
        facts = slide_engine.build_project_facts(PROJECT, tenant_id=None)
        for marker in ('MARKET_MARKER', 'TEAM_MARKER', 'CONTACT_MARKER', 'EXEC_MARKER'):
            self.assertIn(marker, facts)

    def test_team_plan_prompt_drops_other_sections(self):
        prompt = slide_engine.build_slide_plan_prompt(
            PROJECT, {}, section_keys=('section-team',))
        self.assertIn('TEAM_MARKER', prompt)
        self.assertNotIn('MARKET_MARKER', prompt)
        self.assertNotIn('CONTACT_MARKER', prompt)
        self.assertNotIn('COMPONENT_MARKER', prompt)

    def test_plans_prompt_carries_components_without_the_full_report(self):
        prompt = slide_engine.build_slide_plan_prompt(
            PROJECT, {}, section_keys=('plans',))
        self.assertIn('COMPONENT_MARKER', prompt)
        self.assertNotIn('MARKET_MARKER', prompt)
        self.assertNotIn('TEAM_MARKER', prompt)

    def test_note_scopes_keep_financial_report_out_of_visual_sections(self):
        self.assertTrue(context_contracts.note_in_scope(('financial',), 'financial'))
        self.assertTrue(context_contracts.note_in_scope(('section-financial-calc',), 'timeline'))
        self.assertFalse(context_contracts.note_in_scope(('plans',), 'financial'))
        self.assertFalse(context_contracts.note_in_scope(('team',), 'timeline'))


if __name__ == '__main__':
    unittest.main()
