import unittest

import best_use
import best_use_geometry
import plot_shape
import visual_plan_context


def dimension_project(**overrides):
    project = {
        'croquis_land_area': 24250,
        'approved_financial_area': 24250,
        'approved_coverage_ratio': 60,
        'approved_floor_count': 4,
        'approved_floor_area_ratio': 2,
        'setbacks': 'الارتداد الأمامي 5 م، الخلفي 5 م، الجانبي 5 م',
        'survey_coordinates': [],
        'directions_table': [
            {'direction': 'north', 'regulation_text': 'شارع رئيسي عرض 30م', 'boundary_length_m': 97, 'setback': '5م'},
            {'direction': 'south', 'regulation_text': 'بطول 97م يحده جار', 'setback': '5م'},
            {'direction': 'east', 'boundary_length_m': '250', 'setback': '5م'},
            {'direction': 'west', 'boundary_length_m': 250, 'setback': '5م'},
        ],
    }
    project.update(overrides)
    return project


class DirectionLengthsTests(unittest.TestCase):
    def test_structured_lengths_read_from_the_directions_table(self):
        lengths = plot_shape.direction_lengths(dimension_project())
        self.assertEqual(lengths, {'north': 97, 'south': 97, 'east': 250, 'west': 250})

    def test_lengths_survive_dict_form_and_arabic_labels(self):
        project = {'directions_table': {
            'الشمال': {'boundary_length_m': '٩٧'},
            'الجنوب': {'boundary_length_m': 97},
            'الشرق': {'regulation_text': 'بطول 250م'},
            'الغرب': {'length': 250},
        }}
        lengths = plot_shape.direction_lengths(project)
        self.assertEqual(lengths, {'north': 97, 'south': 97, 'east': 250, 'west': 250})

    def test_batool_phrase_inside_regulation_text_counts_but_street_width_does_not(self):
        project = {'directions_table': [
            {'direction': 'شمال', 'regulation_text': 'يحده شارع عرض 30م بطول 97م'},
            {'direction': 'جنوب', 'regulation_text': 'شارع فرعي عرض 12م'},
        ]}
        lengths = plot_shape.direction_lengths(project)
        self.assertEqual(lengths['north'], 97)
        self.assertIsNone(lengths['south'])

    def test_boundary_lengths_summary_text_fills_missing_sides(self):
        project = {'boundary_lengths': 'الشمالي 97م، الجنوبي 97م، والشرقي 250م، والغربي 250م'}
        self.assertEqual(plot_shape.dimension_rectangle(project), (97, 250))

    def test_front_back_and_sides_phrasing_builds_the_same_rectangle(self):
        project = {'boundary_lengths': 'الواجهة الأمامية بطول 97م والخلفية بطول 97م والجانبين بطول 250م'}
        self.assertEqual(plot_shape.dimension_rectangle(project), (97, 250))

    def test_the_editable_table_wins_over_the_raw_extraction(self):
        project = dimension_project(
            land_documents_analysis={'parcels': [{'directions': {
                'north': {'boundary_length_m': 80}}}]})
        lengths = plot_shape.direction_lengths(project)
        self.assertEqual(lengths['north'], 97)
        self.assertEqual(lengths['east'], 250)

    def test_analysis_parcels_fill_what_the_table_never_recorded(self):
        project = {'directions_table': [
            {'direction': 'north', 'boundary_length_m': 97},
            {'direction': 'south', 'boundary_length_m': 97}],
            'land_documents_analysis': {'parcels': [{'directions': {
                'east': {'boundary_length_m': 250}, 'west': {'boundary_length_m': 250}}}]}}
        lengths = plot_shape.direction_lengths(project)
        self.assertEqual(lengths, {'north': 97, 'south': 97, 'east': 250, 'west': 250})

    def test_partial_dimensions_never_fabricate_a_shape(self):
        project = {'directions_table': [{'direction': 'شمال', 'boundary_length_m': 97}]}
        self.assertIsNone(plot_shape.dimension_rectangle(project))
        self.assertEqual(plot_shape.dimension_points(project), [])
        self.assertEqual(plot_shape.dimension_survey_rows(project), [])

    def test_asymmetric_sides_average_into_the_rectangle(self):
        project = {'directions_table': [
            {'direction': 'north', 'boundary_length_m': 97},
            {'direction': 'south', 'boundary_length_m': 99},
            {'direction': 'east', 'boundary_length_m': 250},
            {'direction': 'west', 'boundary_length_m': 252}]}
        self.assertEqual(plot_shape.dimension_rectangle(project), (98, 251))

    def test_survey_rows_mark_their_source_and_stay_positive(self):
        rows = plot_shape.dimension_survey_rows(dimension_project())
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row['source'] == 'boundary_lengths' for row in rows))
        self.assertTrue(all(row['eastings'] >= 1000 and row['northings'] >= 1000 for row in rows))


class DimensionGeometryTests(unittest.TestCase):
    def test_dimensions_drive_the_setback_envelope_when_coordinates_are_missing(self):
        envelope, issue = best_use_geometry.setback_envelope(dimension_project())
        self.assertIsNone(issue)
        self.assertAlmostEqual(envelope, (97 - 10) * (250 - 10))

    def test_a_cadastral_area_conflict_with_the_dimensions_is_reported(self):
        envelope, issue = best_use_geometry.setback_envelope(
            dimension_project(croquis_land_area=30000))
        self.assertIsNone(envelope)
        self.assertEqual(issue['code'], 'mismatch')
        self.assertEqual(issue['cadastralArea'], 30000)
        self.assertAlmostEqual(issue['polygonArea'], 24250)

    def test_dimensions_alone_suffice_when_no_cadastral_area_was_recorded(self):
        envelope, issue = best_use_geometry.setback_envelope(
            dimension_project(croquis_land_area=None, approved_financial_area=25000))
        self.assertIsNone(issue)
        self.assertAlmostEqual(envelope, 20880)

    def test_multi_parcel_surveys_are_never_flattened_into_one_rectangle(self):
        project = dimension_project(survey_coordinates=[
            {'parcel_id': 'P-1', 'eastings': 500000, 'northings': 2000000},
            {'parcel_id': 'P-1', 'eastings': 500100, 'northings': 2000000},
            {'parcel_id': 'P-1', 'eastings': 500100, 'northings': 2000050},
            {'parcel_id': 'P-1', 'eastings': 500000, 'northings': 2000050},
            {'parcel_id': 'P-2', 'eastings': 600000, 'northings': 3000000},
            {'parcel_id': 'P-2', 'eastings': 600100, 'northings': 3000000},
            {'parcel_id': 'P-2', 'eastings': 600100, 'northings': 3000050},
            {'parcel_id': 'P-2', 'eastings': 600000, 'northings': 3000050},
        ])
        envelope, issue = best_use_geometry.setback_envelope(project)
        self.assertIsNone(envelope)
        self.assertEqual(issue['code'], 'parcels')

    def test_recorded_coordinates_stay_authoritative_over_dimensions(self):
        project = dimension_project(survey_coordinates=[
            {'eastings': 500000, 'northings': 2000000},
            {'eastings': 500100, 'northings': 2000000},
            {'eastings': 500100, 'northings': 2000050},
            {'eastings': 500000, 'northings': 2000050},
        ], croquis_land_area=5000, approved_financial_area=5000)
        self.assertEqual(best_use_geometry.parcel_shape_source(project), 'survey')
        envelope, issue = best_use_geometry.setback_envelope(project)
        self.assertIsNone(issue)
        self.assertAlmostEqual(envelope, 90 * 40)

    def test_capacity_flags_the_approximate_shape_and_still_verifies(self):
        budget = best_use.capacity(dimension_project())
        self.assertEqual(budget['boundaryShape'], 'dimensions')
        self.assertTrue(budget['setbackVerified'])
        self.assertAlmostEqual(budget['setbackFootprint'], 20880)
        self.assertAlmostEqual(budget['footprintLimit'], min(24250 * 0.6, 20880))
        self.assertTrue(any('أطوال الحدود' in warning for warning in budget['warnings']))

    def test_capacity_without_shape_still_reports_missing_rows(self):
        project = dimension_project(directions_table=[], boundary_lengths='')
        budget = best_use.capacity(project)
        self.assertEqual(budget['boundaryShape'], '')
        self.assertFalse(budget['setbackVerified'])
        self.assertEqual(budget['setbackIssue']['code'], 'rows')


class DimensionContractTests(unittest.TestCase):
    def test_croquis_contract_synthesizes_geometry_from_lengths(self):
        contract = visual_plan_context.croquis_contract(
            dimension_project(), {'land_area': 24250})
        polygon = contract['geometry']['parcels'][0]['polygon']
        self.assertEqual(sorted(map(tuple, polygon)),
                         sorted([(0, 0), (97, 0), (97, 250), (0, 250)]))
        self.assertEqual(contract['landArea'], 24250)

    def test_direction_rows_keep_their_boundary_lengths(self):
        rows = visual_plan_context.direction_rows(dimension_project(), {}, {})
        self.assertEqual({row['direction']: row['boundaryLength'] for row in rows},
                         {'north': 97, 'south': 97, 'east': 250, 'west': 250})


if __name__ == '__main__':
    unittest.main()
