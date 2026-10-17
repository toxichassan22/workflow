import unittest
import math
from unittest.mock import patch

from visual_plan_geometry import (PlanGeometryError, boundary_geometry, polygons_overlap,
                                  signed_area, validate_footprint)
from visual_plan_scene import buildable_envelopes, fallback_scene, rebase_scene_context, validate_scene


SETBACKS = {'west': 5, 'east': 3, 'north': 3, 'south': 3}


def _contract(setbacks=None):
    geometry = boundary_geometry([{'eastings': x, 'northings': y}
                                  for x, y in ((0, 0), (40, 0), (40, 30), (0, 30))])
    return {'geometry': geometry,
            'primaryFrontage': {'direction': 'west', 'status': 'recorded', 'evidence': []},
            'setbacks': SETBACKS if setbacks is None else setbacks,
            'directions': [
                {'direction': 'west', 'description': 'Street', 'streetName': 'Main St',
                 'streetWidth': 20.0, 'street': True, 'setback': '5', 'boundaryLength': 30.0},
                {'direction': 'east', 'description': 'Neighbor', 'streetName': '',
                 'streetWidth': None, 'street': False, 'setback': '3', 'boundaryLength': 30.0},
            ],
            'landArea': '1200', 'coverageRatio': ''}


def _building(index, area, basement=False):
    return {'id': f'b{index}', 'name': f'Building {index}', 'label': f'Building {index}',
            'footprintArea': area, 'bands': [], 'basementOnly': basement, 'levels': 3}


def _program(*buildings):
    return {'siteItems': [], 'buildings': list(buildings)}


class VisualPlanSceneTests(unittest.TestCase):
    def test_buildable_envelopes_report_the_setback_free_region(self):
        envelopes = buildable_envelopes(_contract())
        self.assertEqual(len(envelopes), 1)
        corners = sorted((round(x, 6), round(y, 6)) for x, y in envelopes[0]['polygon'])
        self.assertEqual(corners, [(5, 3), (5, 27), (37, 3), (37, 27)])
        self.assertEqual(len(buildable_envelopes(_contract(setbacks={}))[0]['polygon']), 4)

    def test_fallback_scene_seals_exact_areas_inside_the_envelope(self):
        contract = _contract()
        scene = fallback_scene(contract, _program(_building(1, 200), _building(2, 150)))
        self.assertEqual(len(scene['buildings']), 2)
        first, second = scene['buildings']
        for building in scene['buildings']:
            polygon = validate_footprint(building['footprint'], contract['geometry'],
                                         contract['setbacks'])
            self.assertAlmostEqual(abs(signed_area(polygon)), building['footprintArea'], places=4)
        self.assertFalse(polygons_overlap(first['footprint'], second['footprint']))
        self.assertEqual(scene['entries'][0]['side'], 'west')
        self.assertEqual(scene['entries'][0]['kind'], 'main')

    def test_fallback_scene_rotates_building_footprints_to_match_the_parcel(self):
        angle = math.radians(23)
        surveyed = []
        for x, y in ((0, 0), (40, 0), (40, 30), (0, 30)):
            surveyed.append({'eastings': x * math.cos(angle) - y * math.sin(angle),
                             'northings': x * math.sin(angle) + y * math.cos(angle)})
        contract = _contract(setbacks={})
        contract['geometry'] = boundary_geometry(surveyed)

        scene = fallback_scene(contract, _program(_building(1, 200)))
        footprint = scene['buildings'][0]['footprint']
        longest = max(zip(footprint, footprint[1:] + footprint[:1]),
                      key=lambda edge: math.dist(*edge))
        actual_angle = math.degrees(math.atan2(longest[1][1] - longest[0][1],
                                               longest[1][0] - longest[0][0]))
        while actual_angle > 90:
            actual_angle -= 180
        while actual_angle <= -90:
            actual_angle += 180

        self.assertAlmostEqual(abs(signed_area(footprint)), 200, places=4)
        self.assertAlmostEqual(actual_angle, 23, places=4)

    def test_fallback_scene_places_all_one_hundred_home_footprints_separately(self):
        contract = _contract(setbacks={})
        contract['geometry'] = boundary_geometry([
            {'eastings': x, 'northings': y}
            for x, y in ((0, 0), (200, 0), (200, 150), (0, 150))
        ])
        program = _program(*(_building(index, 104) for index in range(1, 101)))

        scene = fallback_scene(contract, program)

        self.assertEqual(len(scene['buildings']), 100)
        self.assertEqual({item['id'] for item in scene['buildings']},
                         {f'b{index}' for index in range(1, 101)})
        for item in scene['buildings']:
            self.assertAlmostEqual(abs(signed_area(item['footprint'])), 104, places=5)
        for index, building in enumerate(scene['buildings']):
            for other in scene['buildings'][index + 1:]:
                self.assertFalse(polygons_overlap(building['footprint'], other['footprint']))

    def test_fallback_parks_use_combined_residual_space_when_no_single_lot_fits(self):
        contract = _contract()
        width, height = 250.0, 24906.43 / 250.0
        contract['geometry'] = boundary_geometry([
            {'eastings': x, 'northings': y}
            for x, y in ((0, 0), (width, 0), (width, height), (0, height))
        ])
        contract['landArea'] = '24912.95'
        buildings = [_building(index, 105) for index in range(1, 101)]
        buildings.extend((_building('tower_a', 1040), _building('tower_b', 1040)))
        program = _program(*buildings)
        program['siteItems'] = [
            {'id': 'parking', 'name': 'Parking', 'label': 'Parking',
             'category': 'parking', 'siteType': 'parking', 'area': 9000},
            {'id': 'pool', 'name': 'Pool', 'label': 'Pool',
             'category': 'amenity', 'siteType': 'pool', 'area': 800},
            {'id': 'padel', 'name': 'Padel', 'label': 'Padel',
             'category': 'amenity', 'siteType': 'padel', 'area': 200},
            {'id': 'playground', 'name': 'Playground', 'label': 'Playground',
             'category': 'amenity', 'siteType': 'playground', 'area': 200},
            {'id': 'landscape', 'name': 'Landscape', 'label': 'Landscape',
             'category': 'landscape', 'siteType': 'landscape', 'area': 2007.3},
        ]

        scene = fallback_scene(contract, program)

        parking = [area for area in scene['openAreas'] if area['componentId'] == 'parking']
        self.assertGreater(len(parking), 1)
        self.assertAlmostEqual(sum(abs(signed_area(area['polygon'])) for area in parking), 9000, places=3)
        self.assertEqual(len(scene['buildings']), 102)
        for index, area in enumerate(scene['openAreas']):
            for other in scene['openAreas'][index + 1:]:
                self.assertFalse(polygons_overlap(area['polygon'], other['polygon']))

    def test_fallback_scene_places_missing_basements_through_make_scene(self):
        contract = _contract()
        scene = fallback_scene(contract, _program(_building(1, 200),
                                                  _building(2, 100, basement=True)))
        self.assertEqual(len(scene['buildings']), 2)
        basement = next(item for item in scene['buildings'] if item['id'] == 'b2')
        self.assertTrue(basement['basementOnly'])
        self.assertAlmostEqual(abs(signed_area(basement['footprint'])), 100, places=4)

    def test_fallback_scene_places_recorded_pool_area_with_its_full_area(self):
        contract = _contract(setbacks={})
        program = _program(_building(1, 200))
        program['siteItems'] = [{
            'id': 'pool_1', 'name': 'Swimming Pool', 'label': 'Swimming Pool',
            'category': 'amenity', 'siteType': 'pool', 'area': 120,
        }]

        scene = fallback_scene(contract, program)

        self.assertEqual(len(scene['openAreas']), 1)
        self.assertEqual(scene['openAreas'][0]['componentId'], 'pool_1')
        self.assertEqual(scene['openAreas'][0]['kind'], 'site_facility')
        self.assertAlmostEqual(abs(signed_area(scene['openAreas'][0]['polygon'])), 120, places=4)

    def test_fallback_retries_with_site_areas_first_when_building_first_blocks_parking(self):
        contract = _contract(setbacks={})
        program = _program(_building(1, 200))
        program['siteItems'] = [{
            'id': 'parking', 'name': 'Parking', 'label': 'Parking',
            'category': 'parking', 'siteType': 'parking', 'area': 400,
        }]
        parking_polygon = [[0, 0], [20, 0], [20, 20], [0, 20]]
        building_polygon = [[20, 0], [30, 0], [30, 20], [20, 20]]

        def first_fit(_regions, area, blocked=(), _angle=0):
            if area == 400 and not blocked:
                return parking_polygon
            if area == 200 and (not blocked or blocked == [parking_polygon]):
                return building_polygon
            return None

        with patch('visual_plan_scene._rect_grid_search', side_effect=first_fit), \
                patch('visual_plan_scene._rect_search', side_effect=first_fit):
            scene = fallback_scene(contract, program)

        self.assertEqual(scene['openAreas'][0]['componentId'], 'parking')
        self.assertFalse(polygons_overlap(scene['buildings'][0]['footprint'],
                                          scene['openAreas'][0]['polygon']))

    def test_scene_rejects_an_omitted_recorded_site_area(self):
        contract = _contract(setbacks={})
        program = _program(_building(1, 200))
        program['siteItems'] = [{
            'id': 'padel_1', 'name': 'Padel Court', 'label': 'Padel Court',
            'category': 'amenity', 'siteType': 'padel', 'area': 200,
        }]
        scene = fallback_scene(contract, program)
        scene['openAreas'] = []

        with self.assertRaises(PlanGeometryError) as caught:
            validate_scene(scene, contract, program)

        self.assertEqual(caught.exception.code, 'PLANS_SITE_ITEMS_MISSING')

    def test_fallback_scene_explains_why_nothing_fits(self):
        contract = _contract()
        with self.assertRaises(PlanGeometryError) as caught:
            fallback_scene(contract, _program(_building(1, 800), _building(2, 200)))
        self.assertEqual(caught.exception.code, 'PLANS_SETBACK_CONFLICT')
        self.assertIn('لا تتسع', str(caught.exception))

    def test_fallback_scene_places_footprints_that_fit_in_total_area_in_some_order(self):
        # 50x40 parcel, west and north setbacks 5 m: envelope 1575 m2, footprints total 1472 m2.
        # Greedy placement in the first order fails, but a different order fits.
        contract = _contract(setbacks={'west': 5, 'east': 0, 'north': 5, 'south': 0})
        contract['geometry'] = boundary_geometry([
            {'eastings': x, 'northings': y} for x, y in ((0, 0), (50, 0), (50, 40), (0, 40))])
        contract['landArea'] = '2000'
        areas = (212, 389, 106, 193, 325, 247)
        program = _program(*(_building(index, area) for index, area in enumerate(areas, 1)))

        scene = fallback_scene(contract, program)

        self.assertEqual(len(scene['buildings']), len(areas))
        for building in scene['buildings']:
            validate_footprint(building['footprint'], contract['geometry'], contract['setbacks'])
        for index, building in enumerate(scene['buildings']):
            for other in scene['buildings'][index + 1:]:
                self.assertFalse(polygons_overlap(building['footprint'], other['footprint']))

    def test_fallback_scene_names_the_building_that_does_not_fit(self):
        contract = _contract()
        with self.assertRaises(PlanGeometryError) as caught:
            fallback_scene(contract, _program(_building(1, 800), _building(2, 200)))
        message = str(caught.exception)
        self.assertIn('Building 1', message)
        self.assertNotIn('1000', message)

    def test_context_rebase_revalidates_geometry_against_new_setbacks(self):
        program = _program(_building(1, 200))
        original_contract = _contract(setbacks={})
        scene = fallback_scene(original_contract, program)
        changed_contract = _contract(setbacks={
            'west': 19, 'east': 19, 'north': 14, 'south': 14,
        })

        with self.assertRaises(PlanGeometryError) as caught:
            rebase_scene_context(scene, changed_contract, program)

        self.assertEqual(caught.exception.code, 'PLANS_SETBACK_CONFLICT')


if __name__ == '__main__':
    unittest.main()
