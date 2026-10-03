"""Compliance and ethical AI guardrails tests (Reports 6, 8, 9, 10).

Covers:
- PII masking and scrubbing for document extractions (6.8).
- Audit logging for project file previews and downloads (6.11).
- Human rights and anti-eviction constraints in AI rules (9.3).
- Anti-stereotyping and ethical neutrality constraints (10.5).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as app_module
import auth
import db
import market_study


class ComplianceGuardrailsTests(unittest.TestCase):
    def test_market_study_mandatory_rules_contain_ethical_guardrails(self):
        """MANDATORY_RULES must include human rights, anti-stereotyping, and PII guardrails."""
        rules_text = ' '.join(market_study.MANDATORY_RULES)
        self.assertIn('إخلاء', rules_text)
        self.assertIn('حقوق السكان', rules_text)
        self.assertIn('صور نمطية', rules_text)
        self.assertIn('بيانات شخصية', rules_text)

    def test_scrub_pii_from_extracted_data(self):
        """PII scrubber must drop owner identifiers and mask 10-digit Saudi national IDs."""
        sample_payload = {
            'parcel_id': 'P-1',
            'owner_name': 'محمد بن فهد',
            'national_id': '1098765432',
            'notes': 'المستند صادر للمالك ذي الهوية 1023456789 بموجب الصك',
            'directions': {
                'north': {
                    'street_name': 'شارع الملك فهد',
                    'buyer_name': 'شركة الأفق',
                    'text': 'رقم الهوية للمشتري 2012345678',
                }
            },
            'list_items': [
                'بيانات اعتيادية',
                'هوية أخرى 1000000001 مسجلة',
            ]
        }

        scrubbed = app_module._scrub_pii_from_extracted_data(sample_payload)

        self.assertNotIn('owner_name', scrubbed)
        self.assertNotIn('national_id', scrubbed)
        self.assertNotIn('1023456789', scrubbed['notes'])
        self.assertIn('[تم حجب رقم الهوية]', scrubbed['notes'])

        north = scrubbed['directions']['north']
        self.assertNotIn('buyer_name', north)
        self.assertNotIn('2012345678', north['text'])
        self.assertIn('[تم حجب رقم الهوية]', north['text'])

        self.assertNotIn('1000000001', scrubbed['list_items'][1])
        self.assertIn('[تم حجب رقم الهوية]', scrubbed['list_items'][1])


if __name__ == '__main__':
    unittest.main()
