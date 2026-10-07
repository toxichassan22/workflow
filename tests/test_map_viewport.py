import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

import maps_service as maps


class MapViewportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(maps, 'MAPS_DIR', self.temp.name))
        self.stack.enter_context(patch.object(maps, '_has_api_key', return_value=True))
        self.stack.enter_context(patch.object(maps, '_get_api_key', return_value='test-key'))
        self.usage = self.stack.enter_context(patch.object(maps, '_record_maps_usage'))
        self.stack.enter_context(patch.object(maps, '_record_maps_call'))
        self.stack.enter_context(patch.object(maps.requests, 'get', side_effect=AssertionError('Unexpected provider call')))
        self.stack.enter_context(patch.object(maps.requests, 'post', side_effect=AssertionError('Unexpected provider call')))
        self.requests = []
        self.point = (23.99955, 46.00035)
        self.stack.enter_context(patch.object(maps, '_download_image', side_effect=self.download))

    def download(self, url, params, path):
        self.requests.append(dict(params))
        width, height = map(int, params['size'].split('x'))
        image = Image.new('RGB', (width * params['scale'], height * params['scale']), 'white')
        lat, lng = map(float, params['center'].split(','))
        dx, dy = maps._latlng_to_pixel_offset(*self.point, lat, lng, params['zoom'], params['scale'])
        x, y = image.width / 2 + dx, image.height / 2 + dy
        ImageDraw.Draw(image).rectangle((round(x) - 2, round(y) - 2, round(x) + 2, round(y) + 2), fill='red')
        image.save(path)
        return {'success': True, 'path': path}

    def assert_frame(self, path, center, zoom, size):
        with Image.open(path) as image:
            self.assertEqual(image.size, (size[0] * 2, size[1] * 2))
            bounds = image.getchannel('G').point(lambda value: 255 if value < 100 else 0).getbbox()
            self.assertIsNotNone(bounds)
            dx, dy = maps._latlng_to_pixel_offset(*self.point, *center, zoom, scale=1)
            actual_x = (bounds[0] + bounds[2] - 1) / 4
            actual_y = (bounds[1] + bounds[3] - 1) / 4
            self.assertAlmostEqual(actual_x, size[0] / 2 + dx, delta=2)
            self.assertAlmostEqual(actual_y, size[1] / 2 + dy, delta=2)

    def test_static_request_keeps_extent_within_google_size_limits(self):
        for size in ((1280, 720), (974, 548), (976, 550), (375, 211), (1281, 721)):
            with self.subTest(size=size):
                result = maps.get_static_map(24.0, 46.0, zoom=18, size=size, bypass_cache=True)
                self.assertTrue(result.get('success'), result)
                width, height = map(int, self.requests[-1]['size'].split('x'))
                self.assertLessEqual(width, 640)
                self.assertLessEqual(height, 640)
                self.assert_frame(result['path'], (24.0, 46.0), 18, size)
        self.assertEqual(self.usage.call_count, 5)

    def test_size_is_part_of_the_raw_cache_key(self):
        first = maps.get_static_map(24.0, 46.0, zoom=18, size=(974, 548))
        second = maps.get_static_map(24.0, 46.0, zoom=18, size=(974, 548))
        third = maps.get_static_map(24.0, 46.0, zoom=18, size=(375, 211))
        self.assertEqual(first['path'], second['path'])
        self.assertTrue(second['cached'])
        self.assertNotEqual(first['path'], third['path'])
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.usage.call_count, 2)

    def generation_patches(self):
        self.stack.enter_context(patch.object(maps, '_check_maps_rate_limit', return_value=None))
        self.stack.enter_context(patch.object(maps, '_resolve_map_coordinates', return_value=(24.0, 46.0)))
        self.stack.enter_context(patch.object(maps, '_get_cached_map_images', return_value=None))
        for name in ('_apply_sepia_tone', '_apply_map_overlay', '_draw_compass', '_draw_inset_map',
                     '_draw_site_highlight', '_overlay_markers', '_draw_catchment_zones'):
            self.stack.enter_context(patch.object(maps, name, return_value=True))
        for name in ('_draw_access_roads', '_draw_catchment_markers'):
            self.stack.enter_context(patch.object(maps, name, return_value=[]))
        return self.stack.enter_context(patch('db.add_map_image', return_value='map-row'))

    def project(self, map_type, center):
        return {
            'draftId': 'viewport-test', 'refresh_maps': True, 'enabled_maps': [map_type],
            'location_lat': 24.0, 'location_lng': 46.0,
            'location_polygon': '23.9997,45.9997;24.0003,45.9997;24.0003,46.0003;23.9997,46.0003',
            'nearby_landmarks_data': [], 'city_landmarks_data': [],
            'calculate_landmark_driving': False,
            'map_viewport_overrides': {map_type: True}, 'map_zooms': {map_type: 18},
            'map_centers': {map_type: center},
        }

    def test_live_viewport_dimensions_apply_only_to_the_adjustable_maps(self):
        add_image = self.generation_patches()
        polygon = [(23.9997, 45.9997), (24.0003, 45.9997), (24.0003, 46.0003), (23.9997, 46.0003)]
        auto_zooms = maps._calculate_map_zooms(polygon)
        for map_type in ('overview', 'access', 'catchment', 'landmarks'):
            for size in ((974, 548), (375, 211)):
                with self.subTest(map_type=map_type, size=size):
                    center = {'lat': 24.0, 'lng': 46.0, 'width': size[0], 'height': size[1]}
                    result = maps._generate_all_map_images(self.project(map_type, center), 'tenant-test')
                    path = result['placeholders']['##MAP_' + map_type.upper() + '##']
                    if map_type in ('overview', 'access'):
                        self.assertEqual(result['centers'][map_type], center)
                        self.assertEqual(result['zooms'][map_type], 18)
                        self.assert_frame(path, (24.0, 46.0), 18, size)
                    elif map_type == 'catchment':
                        # Fixed map: the stored viewport is ignored — the frame
                        # refits around the rings (the 16 km band — the default
                        # 28 km ring is past the city-radius cap).
                        self.assertEqual(result['zooms'][map_type], maps.zoom_for_radius_km(24.0, 16.0))
                        self.assert_frame(path, (24.0, 46.0), result['zooms'][map_type], size)
                    else:
                        self.assertEqual(result['zooms'][map_type], auto_zooms['landmarks'])
                        self.assert_frame(path, (24.0, 46.0), result['zooms'][map_type], size)
                    metadata = add_image.call_args.args[-1]
                    self.assertEqual(metadata['viewport_size'], {'width': size[0], 'height': size[1]})

    def test_explicit_live_frame_can_pan_more_than_three_kilometres(self):
        self.generation_patches()
        for map_type in ('overview', 'access'):
            with self.subTest(map_type=map_type):
                center = {'lat': 24.05, 'lng': 46.05, 'width': 974, 'height': 548}
                project = self.project(map_type, center)
                project['map_zooms'][map_type] = 12
                result = maps._generate_all_map_images(project, 'tenant-test')
                self.assertEqual(result['centers'][map_type], center)
                self.assertEqual(result['zooms'][map_type], 12)
        # The fixed maps never take a stored manual frame — they stay on the
        # site-anchored content fit however far the recorded pan reached.
        for map_type in ('catchment', 'landmarks'):
            with self.subTest(map_type=map_type):
                center = {'lat': 24.05, 'lng': 46.05, 'width': 974, 'height': 548}
                project = self.project(map_type, center)
                project['map_zooms'][map_type] = 12
                result = maps._generate_all_map_images(project, 'tenant-test')
                self.assertNotEqual(result['zooms'][map_type], 12)
                self.assertEqual(result['centers'][map_type]['lat'], 24.0)
                self.assertEqual(result['centers'][map_type]['lng'], 46.0)

    def test_unflagged_or_invalid_dimensions_keep_the_default_frame(self):
        self.generation_patches()
        for center, override in (({'lat': 24.0, 'lng': 46.0, 'width': 375, 'height': 211}, False),
                                 ({'lat': 24.0, 'lng': 46.0, 'width': 'NaN', 'height': 548}, True),
                                 ({'lat': 24.0, 'lng': 46.0, 'width': 999999, 'height': 548}, True)):
            with self.subTest(center=center, override=override):
                project = self.project('overview', center)
                project['map_viewport_overrides']['overview'] = override
                result = maps._generate_all_map_images(project, 'tenant-test')
                with Image.open(result['placeholders']['##MAP_OVERVIEW##']) as image:
                    self.assertEqual(image.size, (2560, 1440))

    def place_search(self, places):
        calls = []

        class Resp:
            content = b'{}'
            status_code = 200

            def json(self):
                return {'places': places}

        self.stack.enter_context(patch.object(maps, '_discovery_cache_get', return_value=None))
        self.stack.enter_context(patch.object(maps, '_discovery_cache_put', return_value=True))
        self.stack.enter_context(patch.object(
            maps.requests, 'post', side_effect=lambda *a, **k: (calls.append(k), Resp())[-1]))
        return calls

    def test_place_resolution_prefers_the_nearest_candidate(self):
        calls = self.place_search([
            {'displayName': {'text': 'far endpoint'}, 'types': ['route'],
             'location': {'latitude': 24.4, 'longitude': 46.4}},
            {'displayName': {'text': 'near endpoint'}, 'types': ['route'],
             'location': {'latitude': 24.01, 'longitude': 46.01}},
        ])
        place = maps.find_place_near('طريق الملك فهد', 24.0, 46.0)
        self.assertEqual((place['lat'], place['lng']), (24.01, 46.01))
        self.assertEqual(place['name'], 'near endpoint')
        self.assertEqual(calls[0]['json']['maxResultCount'], 5)

    def test_road_names_prefer_route_entities_over_nearer_businesses(self):
        self.place_search([
            {'displayName': {'text': 'a shop on the road'}, 'types': ['store'],
             'location': {'latitude': 24.01, 'longitude': 46.01}},
            {'displayName': {'text': 'the road'}, 'types': ['route'],
             'location': {'latitude': 24.2, 'longitude': 46.2}},
        ])
        place = maps.find_place_near('طريق الأمير سلطان', 24.0, 46.0)
        self.assertEqual((place['lat'], place['lng']), (24.2, 46.2))
        # A non-road query just takes the closest candidate whatever its type.
        self.place_search([
            {'displayName': {'text': 'far mall'}, 'types': ['shopping_mall'],
             'location': {'latitude': 24.4, 'longitude': 46.4}},
            {'displayName': {'text': 'near mall'}, 'types': ['store'],
             'location': {'latitude': 24.01, 'longitude': 46.01}},
        ])
        place = maps.find_place_near('الراشد مول', 24.0, 46.0)
        self.assertEqual((place['lat'], place['lng']), (24.01, 46.01))

    def test_failed_static_render_is_not_returned_as_a_generated_map(self):
        add_image = self.generation_patches()
        for map_type in ('overview', 'access', 'catchment', 'landmarks'):
            with self.subTest(map_type=map_type), patch.object(
                    maps, '_download_image', return_value={'success': False, 'error': 'test provider failure'}):
                center = {'lat': 24.0, 'lng': 46.0, 'width': 974, 'height': 548}
                result = maps._generate_all_map_images(self.project(map_type, center), 'tenant-test')
                self.assertEqual(result.get('error'), 'test provider failure')
        add_image.assert_not_called()
        self.usage.assert_not_called()

    def test_recompose_preserves_the_stored_size_and_manual_frame(self):
        self.generation_patches()
        size = {'width': 974, 'height': 548}
        center = {'lat': 24.0, 'lng': 46.0, **size}
        for map_type in ('overview', 'access', 'catchment', 'landmarks'):
            with self.subTest(map_type=map_type):
                path = str(Path(self.temp.name) / (map_type + '-editable.png'))
                Image.new('RGB', (size['width'] * 2, size['height'] * 2), 'white').save(path)
                metadata = {'lat': 24.0, 'lng': 46.0, 'center_lat': 24.0, 'center_lng': 46.0,
                            'zoom': 18, 'manual_viewport': True, 'viewport_size': size}
                row = {'id': 'editable-row', 'image_type': map_type + '_editable',
                       'file_path': path, 'placeholder': '##MAP_' + map_type.upper() + '_EDITABLE##',
                       'metadata_json': json.dumps(metadata)}
                with patch('db.get_map_images', return_value=[row]), patch('db.update_map_image'):
                    result = getattr(maps, 'recompose_' + map_type + '_map')(
                        self.project(map_type, center), 'tenant-test', draft_id='viewport-test')
                self.assertEqual(result['centers'][map_type], center)
                if map_type == 'catchment':
                    # The catchment frame is fixed and content-fitted: a stored
                    # manual viewport is interactive-era residue, so the
                    # recompose refits around the rings (the 16 km band — the
                    # default 28 km ring is past the city-radius cap).
                    self.assertEqual(result['zooms'][map_type], maps.zoom_for_radius_km(24.0, 16.0))
                else:
                    self.assertEqual(result['zooms'][map_type], 18)
                with Image.open(result['placeholders']['##MAP_' + map_type.upper() + '##']) as image:
                    self.assertEqual(image.size, (1948, 1096))

    def test_road_landmark_snaps_to_the_drawn_path_point_nearest_the_site(self):
        items = [{'name': 'طريق الملك عبدالعزيز', 'lat': 24.6, 'lng': 46.0}]
        project = {'access_roads_data': [{'name': 'طريق الملك عبدالعزيز',
                                        'points': [[24.3, 46.3], [24.01, 46.01]]}]}
        with patch.object(maps, 'find_place_near', side_effect=AssertionError('no Places call needed')):
            maps._snap_road_landmarks(items, project, 24.0, 46.0)
        self.assertEqual((items[0]['lat'], items[0]['lng']), (24.01, 46.01))
        self.assertLess(items[0]['distance_meters'], 2000)

    def test_undrawn_road_landmark_re_resolves_through_the_nearest_place(self):
        items = [{'name': 'طريق الملك عبدالعزيز', 'lat': 24.6, 'lng': 46.0}]
        with patch.object(maps, 'find_place_near', return_value={'lat': 24.02, 'lng': 46.02}) as search:
            maps._snap_road_landmarks(items, {}, 24.0, 46.0)
        search.assert_called_once()
        self.assertEqual((items[0]['lat'], items[0]['lng']), (24.02, 46.02))

    def test_manual_position_road_landmark_keeps_its_coordinates(self):
        items = [{'name': 'طريق الملك عبدالعزيز', 'lat': 24.6, 'lng': 46.0, 'manual_position': True}]
        project = {'access_roads_data': [{'name': 'طريق الملك عبدالعزيز', 'points': [[24.01, 46.01]]}]}
        with patch.object(maps, 'find_place_near', side_effect=AssertionError('unexpected')):
            maps._snap_road_landmarks(items, project, 24.0, 46.0)
        self.assertEqual((items[0]['lat'], items[0]['lng']), (24.6, 46.0))

    def test_non_road_landmarks_keep_their_stored_coordinates(self):
        items = [{'name': 'مطار الملك عبدالعزيز الدولي', 'lat': 24.6, 'lng': 46.0}]
        project = {'access_roads_data': [{'name': 'طريق الملك عبدالعزيز', 'points': [[24.01, 46.01]]}]}
        with patch.object(maps, 'find_place_near', side_effect=AssertionError('unexpected')):
            maps._snap_road_landmarks(items, project, 24.0, 46.0)
        self.assertEqual((items[0]['lat'], items[0]['lng']), (24.6, 46.0))

    def test_landmark_merge_keeps_the_manual_position_flag(self):
        merged = maps._merge_landmark_data([], [
            {'name': 'طريق الملك عبدالعزيز', 'lat': 24.0, 'lng': 46.0, 'manual_position': True}])
        self.assertTrue(merged[0]['manual_position'])

    def test_curated_road_entries_take_the_places_point_in_arabic(self):
        geo = {'success': True, 'lat': 24.6, 'lng': 46.0}
        with patch.dict(maps.CURATED_CITY_LANDMARKS, {'جدة': [{'name': 'طريق الملك عبدالعزيز', 'category': 'المحاور'}]}), \
                patch.object(maps, 'geocode_address', return_value=dict(geo)), \
                patch.object(maps, 'find_place_near',
                             return_value={'lat': 24.02, 'lng': 46.02, 'name': 'King Abdulaziz Rd'}) as search, \
                patch.object(maps, 'get_nearest_category_landmarks', return_value=[]), \
                patch.object(maps, 'get_drive_matrix', return_value=[]):
            maps._CURATED_GEOCODE_CACHE.clear()
            landmarks = maps.get_curated_city_landmarks('جدة', 24.0, 46.0, language='ar')
        self.assertEqual((landmarks[0]['lat'], landmarks[0]['lng']), (24.02, 46.02))
        self.assertEqual(search.call_args.kwargs['language'], 'ar')


if __name__ == '__main__':
    unittest.main()
