"""Regression checks for the structured location tables (roads/landmarks/catchment).

The UI serializes each table row as "name — X كم — Y دقائق". These tests pin the
parsers so both the new table format and the legacy free-text formats keep working.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import maps_service


class CatchmentZonesParsingTests(unittest.TestCase):
    def test_table_format_parses_duration_distance_and_label(self):
        zones = maps_service._parse_catchment_zones('مجمع الراشد — 4.2 كم — 5 دقائق')
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]['minutes'], 5)
        self.assertAlmostEqual(zones[0]['km'], 4.2)
        self.assertEqual(zones[0]['label'], 'مجمع الراشد')

    def test_legacy_duration_first_format_still_works(self):
        zones = maps_service._parse_catchment_zones('20 دقائق: مركز المملكة')
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]['minutes'], 20)
        self.assertEqual(zones[0]['label'], 'مركز المملكة')

    def test_plain_minutes_line_has_no_label(self):
        zones = maps_service._parse_catchment_zones('10 دقائق')
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]['minutes'], 10)
        self.assertNotIn('label', zones[0])

    def test_multiline_mixed_formats(self):
        text = 'حي النرجس — 3 كم — 5 دقائق\n15 دقائق: مطار الملك خالد\n20 دقائق'
        zones = maps_service._parse_catchment_zones(text)
        self.assertEqual([z['minutes'] for z in zones], [5, 15, 20])

    def test_empty_text_returns_defaults(self):
        self.assertEqual(len(maps_service._parse_catchment_zones('')), 3)
        self.assertEqual(len(maps_service._parse_catchment_zones(None)), 3)

    def test_parsed_list_passes_through(self):
        zones = [{'minutes': 7, 'km': 5}]
        self.assertEqual(maps_service._parse_catchment_zones(zones), zones)


class LandmarksTextParsingTests(unittest.TestCase):
    def test_table_format_with_em_dash(self):
        rows = maps_service._parse_landmarks_text('مجمع الراشد Mall — 4.2 كم — 5 دقائق')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'مجمع الراشد Mall')
        self.assertEqual(rows[0]['duration_minutes'], 5)
        self.assertAlmostEqual(rows[0]['distance_km'], 4.2)

    def test_legacy_single_dash_format(self):
        rows = maps_service._parse_landmarks_text('جامعة الملك سعود - 10 دقائق')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'جامعة الملك سعود')
        self.assertEqual(rows[0]['duration_minutes'], 10)

    def test_name_only_line(self):
        rows = maps_service._parse_landmarks_text('طريق الملك فهد')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'طريق الملك فهد')
        self.assertIsNone(rows[0]['duration_minutes'])

    def test_multiline(self):
        rows = maps_service._parse_landmarks_text('مجمع الراشد — 5 دقائق\nمطار الملك خالد — 20 دقائق')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['name'], 'مطار الملك خالد')


if __name__ == '__main__':
    unittest.main()
