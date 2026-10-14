import unittest

from visual_plan_geometry import (PlanGeometryError, boundary_geometry, polygons_overlap,
                                  signed_area, validate_footprint)
from visual_plan_scene import buildable_envelopes, fallback_scene


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

    def test_fallback_scene_places_missing_basements_through_make_scene(self):
        contract = _contract()
        scene = fallback_scene(contract, _program(_building(1, 200),
                                                  _building(2, 100, basement=True)))
        self.assertEqual(len(scene['buildings']), 2)
        basement = next(item for item in scene['buildings'] if item['id'] == 'b2')
        self.assertTrue(basement['basementOnly'])
        self.assertAlmostEqual(abs(signed_area(basement['footprint'])), 100, places=4)

    def test_fallback_scene_explains_why_nothing_fits(self):
        contract = _contract()
        with self.assertRaises(PlanGeometryError) as caught:
            fallback_scene(contract, _program(_building(1, 800), _building(2, 200)))
        self.assertEqual(caught.exception.code, 'PLANS_SETBACK_CONFLICT')
        self.assertIn('لا تتسع', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
