"""مرابحة wording guards for the financing block of the financial study.

Owner's rule: the financing block speaks Islamic-finance language — «المرابحة»
replaces every «فائدة / فوائد» on the screen, in the financing movement table
(«حركة رصيد التمويل السنوية»), in the exported financial PDF, in the change-log
labels, in the deck's financial facts and in the English auto-translation map.
The calculation itself (ثابتة / متناقصة) and the internal keys
(``financeInterestMethod``, ``annualFinanceRate``, ``financeInterestTotal``,
``financeInterest``) do not change, so saved drafts keep working.

Run as a module from the repo root (one suite per process)::

    python -m unittest tests.workflow.test_financial_murabaha_terms
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402  (DB_PATH is redirected in setUpClass before app import)

I18N_DIR = ROOT / 'assets' / 'i18n'


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


class FinancialMurabahaTermsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'financial-murabaha.db')

        # Import only after redirecting DB_PATH: app.py initializes its database at import time.
        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant(
                'Murabaha Co', 'murabaha@example.test', 'hash-mb', 'murabaha-co')

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    @staticmethod
    def _read(relative):
        return (ROOT / relative).read_text(encoding='utf-8')

    def _finance_model(self, **overrides):
        """A financing study whose report/Arabic labels come from the screen snapshot."""
        inputs = {
            'unitRevenueMode': 'mixed', 'developmentYears': 4,
            'financeEnabled': 'yes', 'financeBase': 'withLand',
            'financingRate': 60, 'financeArrangementFeeRate': 1,
            'annualFinanceRate': 6, 'financeInterestMethod': 'declining',
            'financeDrawYears': 2, 'financeRepaymentStartYear': 3,
            'financeRepaymentYears': 3, 'projectCost': 1000000,
            'financeInterestTotal': 126000,
        }
        inputs.update(overrides)
        return {
            'inputs': inputs,
            'projection': {
                'projectCost': 1000000, 'facilityAmount': 600000,
                'arrangementFee': 6000, 'totalFinanceInterest': 126000,
                'totalFinanceCost': 132000,
            },
            'tables': {
                'financeDrawTable': [{
                    'سنة السحب': 1, 'نسبة السحب من التسهيل %': 50,
                    'قيمة السحب المحسوبة': 300000,
                }],
                'financeRepaymentTable': [{
                    'سنة السداد': 3, 'نسبة السداد من أصل التسهيل %': 33.3,
                    'قيمة السداد المحسوبة': 200000,
                }],
                'debtScheduleTable': [{
                    'السنة': 3, 'الرصيد الافتتاحي': 600000, 'السحب': 0,
                    'المرابحة': 36000, 'رسوم التمويل': 0,
                    'سداد أصل التمويل': 200000, 'الرصيد الختامي': 400000,
                }],
                'cashflowTable': [{
                    'السنة': 3, 'سحب التمويل': 0,
                    'مرابحة ورسوم التمويل': 36000, 'سداد أصل التمويل': 200000,
                    'صافي تدفق المشروع': -164000, 'الرصيد التراكمي': -164000,
                }],
            },
            'dynamicRows': {},
        }

    # ── the screen ───────────────────────────────────────────────────────────

    def test_financing_screen_labels_speak_murabaha(self):
        source = self._read('assets/js/09-financial/01_financial_format.js')
        self.assertIn('<label>طريقة احتساب المرابحة</label>', source)
        self.assertIn('<label>معدل المرابحة السنوي %</label>', source)
        self.assertIn('<label>إجمالي المرابحة</label>', source)
        self.assertIn('<tr><td>ROI</td><td>يشمل رسوم ترتيب التمويل والمرابحة</td>', source)
        # The calculation and its option wording are untouched: naming change only.
        self.assertIn('<option value="fixed">ثابتة على أصل التسهيل</option>'
                      '<option value="declining">متناقصة على الرصيد المتبقي</option>', source)
        # Saved drafts keep their data-key/id names — only the display wording moved.
        for element_id in ('financeInterestMethod', 'annualFinanceRate', 'financeInterestTotal'):
            self.assertIn('id="%s"' % element_id, source)
        self.assertNotIn('الفائدة', source)
        self.assertNotIn('فوائد', source)

    def test_financing_movement_table_column_is_murabaha(self):
        """«حركة رصيد التمويل السنوية» carries the المرابحة column, not الفائدة."""
        source = self._read('assets/js/09-financial/01_financial_format.js')
        self.assertIn('id="debtScheduleTable"', source)
        self.assertIn('<th>السنة</th><th>الرصيد الافتتاحي</th><th>السحب</th>'
                      '<th>المرابحة</th><th>رسوم التمويل</th>'
                      '<th>سداد أصل التمويل</th><th>الرصيد الختامي</th>', source)
        # The cash-flow table column follows the same wording.
        self.assertIn('<th class="cf-finance">مرابحة ورسوم التمويل</th>', source)

    def test_report_collector_labels_speak_murabaha(self):
        source = self._read('assets/js/10-financial-report-timeline/01_report_collect.js')
        self.assertIn("['طريقة احتساب المرابحة', reportFieldValue('financeInterestMethod')]", source)
        self.assertIn("['معدل المرابحة السنوي', reportFieldValue('annualFinanceRate') + '%']", source)
        self.assertIn("['إجمالي المرابحة', reportFieldValue('financeInterestTotal')]", source)
        self.assertNotIn('الفائدة', source)
        self.assertNotIn('فوائد', source)

    # ── the exported financial PDF ───────────────────────────────────────────

    def test_financial_report_pdf_labels_speak_murabaha(self):
        with self.app.app_context():
            html = self.application_module.build_financial_report_html(
                'مشروع المرابحة', self._finance_model(), {}, self.tenant)
        self.assertIn('معدل المرابحة', html)
        self.assertIn('طريقة المرابحة', html)
        self.assertIn('إجمالي المرابحة', html)
        self.assertNotIn('فائدة', html)
        self.assertNotIn('فوائد', html)

    def test_finance_cashflow_columns_stay_hidden_without_financing(self):
        """The new header must still be dropped from the PDF when financing is off."""
        model = self._finance_model(financeEnabled='no')
        with self.app.app_context():
            html = self.application_module.build_financial_report_html(
                'مشروع بلا تمويل', model, {}, self.tenant)
        self.assertNotIn('مرابحة ورسوم التمويل', html)
        self.assertNotIn('سحب التمويل', html)
        self.assertIn('13. التدفقات النقدية السنوية', html)

    def test_validation_and_change_log_labels_speak_murabaha(self):
        errors = self.application_module.validate_financial_model({
            'inputs': {
                'unitRevenueMode': 'nonRevenue', 'developmentYears': 1,
                'landArea': 1000, 'builtUpAreaAbove': 500,
                'financeEnabled': 'yes', 'fundEnabled': 'no', 'externalEnabled': 'no',
                'exitEnabled': 'no',
            },
            'tables': {},
        })
        messages = [item['message'] for item in errors]
        self.assertTrue(any('طريقة احتساب المرابحة' in m for m in messages), messages)
        self.assertTrue(any('معدل المرابحة' in m for m in messages), messages)
        self.assertFalse(any('فائدة' in m for m in messages), messages)

        labels = self.application_module.change_tracking.BLOB_KEY_LABELS
        self.assertEqual(labels.get('financeInterestMethod'), 'طريقة احتساب المرابحة')
        self.assertEqual(labels.get('annualFinanceRate'), 'معدل المرابحة السنوي %')
        self.assertEqual(labels.get('financeInterestTotal'), 'إجمالي المرابحة')

    # ── the generated deck ───────────────────────────────────────────────────

    def test_deck_finance_chart_reads_the_murabaha_column(self):
        engine = self.application_module.slide_engine
        cost_rows = [{'اسم التكلفة': 'تكلفة التنفيذ والإنشاء', 'الناتج': 10000000}]
        model = {'inputs': {}, 'tables': {'debtScheduleTable': [
            {'السنة': 1, 'المرابحة': '5000000', 'رسوم التمويل': '1000000'}]}}
        data = engine._extract_waterfall_chart_data(cost_rows, model, {})
        by_name = {item['name']: item['value_sar'] for item in data['items']}
        self.assertEqual(by_name.get('تكلفة التمويل'), 6000000)

        # A report saved before the rename still totals from the old column name.
        legacy = {'inputs': {}, 'tables': {'debtScheduleTable': [
            {'السنة': 1, 'الفائدة': '7000000', 'رسوم التمويل': '1000000'}]}}
        data = engine._extract_waterfall_chart_data(cost_rows, legacy, {})
        by_name = {item['name']: item['value_sar'] for item in data['items']}
        self.assertEqual(by_name.get('تكلفة التمويل'), 8000000)

    def test_deck_financial_facts_and_design_rule_speak_murabaha(self):
        engine_src = read_module_source('slide_engine.py')
        self.assertIn("('totalFinanceInterest', 'إجمالي المرابحة')", engine_src)
        self.assertIn("dr.get('المرابحة') or dr.get('الفائدة')", engine_src)
        self.assertNotIn('فوائد التمويل', engine_src)

        design_src = read_module_source('design_templates.py')
        self.assertIn('إدخال رسوم ترتيب التمويل والمرابحة فقط ضمن تكلفة التمويل.', design_src)

    # ── English auto-translation map ─────────────────────────────────────────

    def test_english_auto_map_translates_murabaha_labels(self):
        financial = self._read('assets/i18n/05_dict_en_auto_financial.js')
        self.assertIn('"طريقة احتساب المرابحة": "Murabaha calculation method",', financial)
        self.assertIn('"معدل المرابحة السنوي %": "Annual murabaha rate %",', financial)
        self.assertIn('"إجمالي المرابحة": "Total murabaha",', financial)
        self.assertIn('"المرابحة": "Murabaha",', financial)
        self.assertIn('"يشمل رسوم ترتيب التمويل والمرابحة": '
                      '"Includes financing arrangement fees and murabaha",', financial)
        core = self._read('assets/i18n/03_dict_en_auto_core.js')
        self.assertIn('"معدل المرابحة السنوي": "Annual Murabaha Rate %",', core)
        ops = self._read('assets/i18n/18_dict_en_auto_backend_platform.js')
        self.assertIn('"مرابحة ورسوم التمويل": "Financing murabaha and fees",', ops)

        # A stale key would translate nothing: no dictionary may keep interest wording.
        for part in sorted(I18N_DIR.glob('*.js')):
            text = part.read_text(encoding='utf-8')
            self.assertNotIn('الفائدة', text, '%s still carries interest wording' % part.name)
            self.assertNotIn('فوائد', text, '%s still carries interest wording' % part.name)

    def test_murabaha_plan_inputs_and_table_markup(self):
        """خطة المرابحة table and its inputs exist and match the principal repayment plan style."""
        source = self._read('assets/js/09-financial/01_financial_format.js')
        self.assertIn('id="financeMurabahaStartYear"', source)
        self.assertIn('id="financeMurabahaYears"', source)
        self.assertIn('<label>سنة بدء المرابحة</label>', source)
        self.assertIn('<label>عدد سنوات المرابحة</label>', source)
        self.assertIn('<h4>خطة المرابحة</h4>', source)
        self.assertIn('id="financeMurabahaTable"', source)
        self.assertIn('<th>سنة الاستحقاق</th><th>نسبة المرابحة %</th><th>قيمة المرابحة المحسوبة</th>', source)
        self.assertIn('function addFinanceMurabahaYear', source)
        self.assertIn('function syncFinanceMurabahaPlan', source)

    def test_murabaha_plan_integration_and_export(self):
        """Murabaha plan hydrates, tracks diffs, and exports in report HTML and PDF."""
        team_src = self._read('assets/js/06-team.js')
        self.assertIn("hydrateFinancialTableRows('financeMurabahaTable', rows.financeMurabaha, addFinanceMurabahaYear);", team_src)

        calc_src = self._read('assets/js/09-financial/02_formulas_calc.js')
        self.assertIn('financeMurabahaPlan', calc_src)
        self.assertIn('baseMurabaha', calc_src)
        self.assertIn('.financeMurabahaAmount', calc_src)

        labels = self.application_module.change_tracking.BLOB_KEY_LABELS
        self.assertEqual(labels.get('financeMurabaha'), 'جدول خطة المرابحة')
        self.assertEqual(labels.get('financeMurabahaStartYear'), 'سنة بدء المرابحة')
        self.assertEqual(labels.get('financeMurabahaYears'), 'عدد سنوات المرابحة')

        model = self._finance_model()
        model['tables']['financeMurabahaTable'] = [{
            'سنة الاستحقاق': 2,
            'نسبة المرابحة %': 50,
            'قيمة المرابحة المحسوبة': 63000,
        }, {
            'سنة الاستحقاق': 3,
            'نسبة المرابحة %': 50,
            'قيمة المرابحة المحسوبة': 63000,
        }]
        with self.app.app_context():
            html = self.application_module.build_financial_report_html(
                'مشروع خطة المرابحة', model, {}, self.tenant)
        self.assertIn('خطة المرابحة', html)
        self.assertIn('63,000', html)


if __name__ == '__main__':
    unittest.main()
