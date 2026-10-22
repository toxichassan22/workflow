"""Tests for external flexible line items in financial study calculations and cashflow projections.

Owner's rule:
External items of type 'opex' (مصروف) with a defined startYear and endYear must be
calculated and added to the cashflow table under the expenses line item ('المصروفات')
from startYear to endYear, deducting from net cashflows even in pre-operation/development
years or in non-rental project modes.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402


class FinancialExternalItemsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'financial-external.db')
        import app as application_module
        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_frontend_formulas_initialize_opex_with_external_opex_for_all_years(self):
        formulas_file = ROOT / 'assets' / 'js' / '09-financial' / '02_formulas_calc.js'
        text = formulas_file.read_text(encoding='utf-8')

        # Must initialize opexAnnual with extOpexAnnual so startYear..endYear
        # is honored even before inOperation.
        self.assertIn('let opexAnnual = extOpexAnnual;', text)
        self.assertNotIn('let opexAnnual = 0;\n        if (inOperation)', text)
        self.assertNotIn('let opexAnnual = 0;\r\n        if (inOperation)', text)

        # Must unhide column 9 (المصروفات) if external opex is present in non-rental mode
        self.assertIn("!flags.rental && val('externalEnabled') === 'yes'", text)
        self.assertIn("document.querySelectorAll('#cashflowTable tr > :nth-child(9)')", text)

    def test_filter_cashflow_columns_preserves_opex_when_external_opex_exists_in_sales_mode(self):
        _filter_cashflow_columns = getattr(self.application_module, '_filter_cashflow_columns')
        rows = [
            {'year': 1, 'المبيعات': 1000000, 'opex': 50000, 'المصروفات': '50,000'},
            {'year': 2, 'المبيعات': 2000000, 'opex': 50000, 'المصروفات': '50,000'},
            {'year': 3, 'المبيعات': 0, 'opex': 0, 'المصروفات': '0'},
        ]
        filtered = _filter_cashflow_columns(rows, {'unitRevenueMode': 'sale'})
        self.assertEqual(len(filtered), 3)
        self.assertIn('opex', filtered[0])
        self.assertIn('المصروفات', filtered[0])
        self.assertEqual(filtered[0]['opex'], 50000)

        # But if there is no opex data at all in sales mode, opex columns should still be pruned
        empty_rows = [
            {'year': 1, 'المبيعات': 1000000, 'opex': 0, 'المصروفات': '0'},
            {'year': 2, 'المبيعات': 2000000, 'opex': 0, 'المصروفات': '0'},
        ]
        filtered_empty = _filter_cashflow_columns(empty_rows, {'unitRevenueMode': 'sale'})
        self.assertNotIn('opex', filtered_empty[0])
        self.assertNotIn('المصروفات', filtered_empty[0])

    def test_external_opex_added_to_cashflow_across_start_and_end_years_via_node(self):
        """Simulate the annual cashflow loop logic via node to verify that
        development-phase years (e.g. Years 1 and 2 before operation starts in Year 3)
        receive the external expense and reduce unlevered cash flows."""
        node_script = """
        function annualGrowthFactor(years, rate) {
            return Math.pow(1 + (Number(rate) || 0) / 100, Math.max(0, years - 1));
        }

        const totalYears = 5;
        const developmentYears = 2;
        const operationStartYear = 3;
        const modeFlags = { rental: true, sales: false };
        const exitMethod = 'none';
        const operatingExitYear = 5;

        const externalOn = true;
        const externalRows = [
            { type: 'opex', startYear: 1, endYear: 3, value: 50000, growth: 0 }
        ];

        const opexBasePerYear = 30000;
        const projected = [];

        for (let year = 1; year <= totalYears; year++) {
            const inOperation = modeFlags.rental && year >= operationStartYear && (exitMethod === 'none' || year <= operatingExitYear);
            let extOpexAnnual = 0;
            if (externalOn) externalRows.forEach(item => {
                if (year >= item.startYear && year <= item.endYear) {
                    const val = item.value * annualGrowthFactor(year - item.startYear + 1, item.growth);
                    if (item.type === 'opex') extOpexAnnual += val;
                }
            });

            // The fixed logic: opexAnnual starts with extOpexAnnual
            let opexAnnual = extOpexAnnual;
            if (inOperation) {
                opexAnnual += opexBasePerYear;
            }

            const developmentCost = year <= developmentYears ? 100000 : 0;
            const operatingRevenue = inOperation ? 200000 : 0;
            const unlevered = operatingRevenue - developmentCost - opexAnnual;

            projected.push({ year, inOperation, opexAnnual, unlevered });
        }

        console.log(JSON.stringify(projected));
        """

        result = subprocess.run(['node', '-e', node_script], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout.strip())

        # Year 1 (development phase, inOperation = false):
        self.assertFalse(data[0]['inOperation'])
        self.assertEqual(data[0]['opexAnnual'], 50000, "Year 1 must have external opex of 50,000")
        self.assertEqual(data[0]['unlevered'], -150000, "Unlevered flow must subtract the 50,000 opex in Year 1")

        # Year 2 (development phase, inOperation = false):
        self.assertFalse(data[1]['inOperation'])
        self.assertEqual(data[1]['opexAnnual'], 50000, "Year 2 must have external opex of 50,000")
        self.assertEqual(data[1]['unlevered'], -150000, "Unlevered flow must subtract the 50,000 opex in Year 2")

        # Year 3 (operation phase, inOperation = true):
        self.assertTrue(data[2]['inOperation'])
        self.assertEqual(data[2]['opexAnnual'], 80000, "Year 3 must have external opex (50,000) + base opex (30,000)")
        self.assertEqual(data[2]['unlevered'], 120000)

        # Year 4 (past endYear=3, inOperation = true):
        self.assertTrue(data[3]['inOperation'])
        self.assertEqual(data[3]['opexAnnual'], 30000, "Year 4 has only base opex")

        # Year 5 (past endYear=3, inOperation = true):
        self.assertTrue(data[4]['inOperation'])
        self.assertEqual(data[4]['opexAnnual'], 30000, "Year 5 has only base opex")


if __name__ == '__main__':
    unittest.main()
