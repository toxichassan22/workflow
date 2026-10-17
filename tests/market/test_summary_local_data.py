"""Reads source-attributed transaction rows from owner-provided Excel workbooks."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import market_study

_REAL_SUMMARY_CSV_FILES = market_study._summary_benchmark_csv_files


def _column_name(index):
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _write_workbook(path, sheets):
    with ZipFile(path, 'w') as archive:
        for sheet_number, rows in enumerate(sheets, 1):
            row_xml = []
            for row_number, row in enumerate(rows, 1):
                cells = []
                for col_number, value in enumerate(row, 1):
                    if value is None:
                        continue
                    cell_ref = f'{_column_name(col_number)}{row_number}'
                    escaped = (str(value).replace('&', '&amp;').replace('<', '&lt;')
                               .replace('>', '&gt;'))
                    cells.append(
                        f'<c r="{cell_ref}" t="inlineStr"><is><t>{escaped}</t></is></c>')
                row_xml.append(f'<row r="{row_number}">' + ''.join(cells) + '</row>')
            sheet_xml = ('<worksheet xmlns="http://schemas.openxmlformats.org/'
                         'spreadsheetml/2006/main"><sheetData>' + ''.join(row_xml)
                         + '</sheetData></worksheet>')
            archive.writestr(f'xl/worksheets/sheet{sheet_number}.xml', sheet_xml)


class SummaryLocalDataTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workbook = Path(self.temp_dir.name) / 'deals.xlsx'
        _write_workbook(self.workbook, [[
            ['المصدر', 'الهيئة العامة للعقار'],
            ['رابط البحث', 'https://rei.rega.gov.sa/ar/advanced-search/deals'],
            ['تاريخ الصفقة', 'المدينة', 'الحي', 'نوع الوحدة',
             'قيمة تقريبية (ريال)', 'سعر المتر تقريبًا (ريال/م²)', 'مصدر الوثيقة'],
            ['2025-04-01', 'جدة', 'الروضة', 'فيلا', '2000000', '5000', 'وزارة العدل'],
            ['2025-05-01', 'جدة', 'الروضة', 'فيلا', '4000000', '7000', 'السجل العقاري'],
            ['2025-06-01', 'جدة', 'الحمراء', 'فيلا', '8000000', '9000', 'وزارة العدل'],
            ['2024-12-01', 'جدة', 'الروضة', 'فيلا', '1000000', '3000', 'وزارة العدل'],
        ]])
        self.files_patch = patch.object(
            market_study, '_summary_benchmark_files', return_value=[self.workbook])
        self.files_patch.start()
        self.addCleanup(self.files_patch.stop)
        self.csv_patch = patch.object(
            market_study, '_summary_benchmark_csv_files', return_value=[])
        self.csv_patch.start()
        self.addCleanup(self.csv_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def test_excel_rows_are_filtered_and_aggregated_without_competitor_names(self):
        payload = {
            'summaryScope': {'cities': [{'name': 'جدة', 'districts': ['الروضة']}]},
            'dataPeriodBounds': {'from': '2025-01-01', 'to': '2025-12-31'},
        }
        result = market_study.build_summary_local_benchmarks(payload)
        self.assertTrue(result['available'])
        self.assertEqual(len(result['groups']), 1)
        group = result['groups'][0]
        self.assertEqual(group['district'], 'الروضة')
        self.assertEqual(group['deal_count_in_file'], 2)
        self.assertEqual(group['median_price_sqm_sar'], 6000)
        self.assertEqual(group['median_deal_value_sar'], 3000000)
        self.assertEqual(group['period_from'], '2025-04-01')
        self.assertEqual(group['sources'], ['السجل العقاري', 'وزارة العدل'])
        self.assertIn('https://rei.rega.gov.sa/ar/advanced-search/deals',
                      group['source_urls'])
        self.assertNotIn('name', group)
        self.assertIn('مصادرها المدونة', result['limitations'])
        self.assertNotIn('مجهولة الهوية', result['limitations'])

    def test_city_scope_includes_available_districts_and_preserves_coverage_limit(self):
        result = market_study.build_summary_local_benchmarks({
            'summaryScope': {'cities': [{'name': 'جدة', 'districts': []}]},
        })
        self.assertEqual({row['district'] for row in result['groups']},
                         {'الروضة', 'الحمراء'})
        self.assertTrue(result['available'])
        self.assertIn('محدودة بالأحياء', result['limitations'])

    def test_missing_rows_returns_an_explicit_empty_local_source(self):
        result = market_study.build_summary_local_benchmarks({
            'summaryScope': {'cities': [{'name': 'مكة', 'districts': []}]},
        })
        self.assertFalse(result['available'])
        self.assertEqual(result['groups'], [])

    def test_sanitized_owner_dataset_is_available_without_original_workbooks(self):
        with patch.object(market_study, '_summary_benchmark_files', return_value=[]), \
                patch.object(market_study, '_summary_benchmark_csv_files',
                             wraps=_REAL_SUMMARY_CSV_FILES):
            result = market_study.build_summary_local_benchmarks({
                'summaryScope': {'cities': [{'name': 'جدة', 'districts': []}]},
            })
        self.assertTrue(result['available'])
        self.assertEqual(sum(group['deal_count_in_file'] for group in result['groups']), 339)
        self.assertEqual({group['unit_type'] for group in result['groups']},
                         {'فيلا', 'دور'})
        self.assertNotIn('source_record_id', str(result))


if __name__ == '__main__':
    unittest.main()
