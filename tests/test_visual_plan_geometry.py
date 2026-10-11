import copy
import unittest

from visual_plan_context import croquis_contract, primary_frontage, recorded_setbacks
from visual_plan_geometry import (PlanGeometryError, boundary_geometry, fit_projection,
                                  isometric_projection, polygons_overlap, validate_footprint)


class VisualPlanGeometryTests(unittest.TestCase):
    def points(self):
        return [{'point': str(index + 1), 'eastings': 500000 + x, 'northings': 2000000 + y}
                for index, (x, y) in enumerate(((0, 0), (40, 0), (40, 30), (24, 30), (24, 14), (0, 14)))]

    def test_irregular_survey_points_are_preserved_without_scaling_to_an_area(self):
        points = self.points()
        original = copy.deepcopy(points)
        geometry = boundary_geometry(points)
        self.assertEqual(points, original)
        for source, stored in zip(original, geometry['surveyPoints']):
            self.assertEqual(source['eastings'], stored['eastings'])
            self.assertEqual(source['northings'], stored['northings'])
        self.assertEqual(geometry['parcels'][0]['polygon'][4], [24, 14])

    def test_uniform_projection_preserves_a_square(self):
        points = [[0, 0], [20, 0], [20, 20], [0, 20]]
        project = fit_projection(points, 1000, 700)
        a, b, c = (project(point) for point in points[:3])
        self.assertAlmostEqual(abs(b[0] - a[0]), abs(c[1] - b[1]))

    def test_concave_parcel_rejects_a_footprint_that_bridges_its_notch(self):
        geometry = boundary_geometry(self.points())
        with self.assertRaises(PlanGeometryError):
            validate_footprint([[10, 10], [30, 10], [30, 25], [10, 25]], geometry)
        accepted = validate_footprint([[26, 16], [36, 16], [36, 26], [26, 26]], geometry)
        self.assertEqual(accepted[0], [26, 16])

    def test_setbacks_are_checked_as_segment_distances(self):
        geometry = boundary_geometry(self.points())
        with self.assertRaises(PlanGeometryError) as caught:
            validate_footprint([[1, 2], [10, 2], [10, 10], [1, 10]], geometry, {'west': 5})
        self.assertEqual(caught.exception.code, 'PLANS_SETBACK_CONFLICT')
        validate_footprint([[6, 4], [12, 4], [12, 10], [6, 10]], geometry, {'west': 5, 'south': 3})

    def test_invalid_survey_values_and_crossed_edges_are_rejected(self):
        for value in ('', True, float('nan'), float('inf')):
            points = self.points()
            points[0]['eastings'] = value
            with self.subTest(value=value), self.assertRaises(PlanGeometryError):
                boundary_geometry(points)
        crossed = [{'eastings': x, 'northings': y} for x, y in ((0, 0), (20, 20), (0, 20), (20, 0))]
        with self.assertRaises(PlanGeometryError):
            boundary_geometry(crossed)

    def test_overlap_distinguishes_shared_edges_from_overlapping_buildings(self):
        box = [[0, 0], [10, 0], [10, 10], [0, 10]]
        adjacent = [[10, 0], [20, 0], [20, 10], [10, 10]]
        overlapping = [[5, 0], [15, 0], [15, 10], [5, 10]]
        self.assertFalse(polygons_overlap(box, adjacent))
        self.assertTrue(polygons_overlap(box, overlapping))
        self.assertTrue(polygons_overlap(box, box))

    def test_isometric_camera_changes_do_not_mutate_survey_geometry(self):
        geometry = boundary_geometry(self.points())
        original = copy.deepcopy(geometry)
        for direction in ('north', 'south', 'east', 'west'):
            for point in geometry['parcels'][0]['polygon']:
                self.assertEqual(len(isometric_projection(point, 12, direction)), 3)
        self.assertEqual(geometry, original)

    def test_primary_facade_comes_from_the_summary_not_street_order(self):
        rows = [{'direction': 'north', 'description': 'Street', 'street': True},
                {'direction': 'west', 'description': 'Street', 'street': True}]
        result = primary_frontage('The main facade faces west.', '', rows)
        self.assertEqual(result['direction'], 'west')
        self.assertEqual(primary_frontage('', '', rows)['status'], 'unresolved')
        self.assertEqual(primary_frontage('الواجهة الرئيسية غربية.', '', rows)['direction'], 'west')

    def test_conflicting_primary_facades_and_neighbor_frontage_do_not_pass(self):
        rows = [{'direction': 'north', 'description': 'Street', 'street': True},
                {'direction': 'west', 'description': 'Neighbor', 'street': False}]
        self.assertEqual(primary_frontage('The main facade faces west.', '', rows)['status'], 'conflicting')
        rows[1]['street'] = True
        result = primary_frontage('Main facade faces west. Main facade faces north.', '', rows)
        self.assertEqual(result['status'], 'conflicting')

    def test_setback_values_are_taken_from_recorded_units_only(self):
        result = recorded_setbacks('5 m front; 3 m rear; 4 m side', [], 'west')
        self.assertEqual(result, {'west': 5, 'east': 3, 'south': 4, 'north': 4})
        self.assertEqual(recorded_setbacks('1/5 of street width north', [], 'west'), {})

    def test_complete_croquis_text_stays_separate_from_documented_verification_rules(self):
        project = {'survey_coordinates': self.points(), 'land_and_building_summary': 'FULL SUMMARY',
                   'regulatory_constraints': 'FULL CONSTRAINTS',
                   'directions_table': [{'direction': 'west', 'street_name': 'Public Road'}]}
        context = {'land_area': '999', 'regulations': {'coverage_ratio': '50%'}}
        contract = croquis_contract(project, context)
        self.assertEqual(contract['landBrief'], 'FULL SUMMARY')
        self.assertEqual(contract['regulatoryConstraints'], 'FULL CONSTRAINTS')
        self.assertEqual(contract['documentedRegulations'], {'coverage_ratio': '50%'})
        self.assertEqual(contract['primaryFrontage']['direction'], 'west')
        self.assertEqual(contract['landArea'], '999')


if __name__ == '__main__':
    unittest.main()
