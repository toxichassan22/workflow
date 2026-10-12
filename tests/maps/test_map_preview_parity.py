import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

import maps_service as maps


class MapPreviewParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'map.png')

    def base(self, size=(2560, 1440)):
        Image.new('RGB', size, (80, 100, 120)).save(self.path)

    def mask_bounds(self, image, color):
        channels = image.convert('RGB').split()
        masks = [channel.point(lambda value, target=target: 255 if abs(value - target) <= 3 else 0)
                 for channel, target in zip(channels, color)]
        return ImageChops.multiply(ImageChops.multiply(masks[0], masks[1]), masks[2]).getbbox()

    def label_point(self, x, y, size=(2560, 1440)):
        return list(maps._pixel_to_latlng(x, y, *size, 24, 46, 14, scale=2))

    def test_site_marker_is_circular_at_every_frame_size(self):
        for size in ((2560, 1440), (750, 422)):
            with self.subTest(size=size):
                self.base(size)
                self.assertTrue(maps._overlay_markers(
                    self.path, 24, 46, 14, [{'lat': 24, 'lng': 46, 'type': 'site'}]))
                with Image.open(self.path) as image:
                    bounds = self.mask_bounds(image, (255, 255, 255))
                self.assertIsNotNone(bounds)
                self.assertAlmostEqual(bounds[2] - bounds[0], bounds[3] - bounds[1], delta=2)
                self.assertAlmostEqual(bounds[2] - bounds[0], 51 * size[0] / 1000, delta=3)

    def test_site_marker_has_the_same_white_ring_thickness_as_css(self):
        self.base()
        maps._overlay_markers(self.path, 24, 46, 14, [{'lat': 24, 'lng': 46, 'type': 'site'}])
        with Image.open(self.path) as image:
            white = sum(min(image.getpixel((x, 720))[:3]) >= 245 for x in range(1210, 1350))
        self.assertAlmostEqual(white, 14 * 2.56, delta=5)

    def test_label_height_uses_the_line_box_not_each_names_glyph_bounds(self):
        for name in ('مطار الملك عبدالعزيز الدولي', 'كورنيش جدة', 'ROSHN'):
            with self.subTest(name=name):
                self.base()
                maps._draw_catchment_markers(self.path, 24, 46, 14,
                    [{'name': name, 'lat': 24.001, 'lng': 46.001}],
                    {name: self.label_point(500, 300)})
                with Image.open(self.path) as image:
                    bounds = self.mask_bounds(image, (37, 75, 102))
                expected = (12 * 1.25 + 6) * 2.56
                self.assertAlmostEqual(bounds[3] - bounds[1], expected, delta=3)

    def test_landmark_markers_stay_above_overlapping_labels(self):
        self.base()
        lat, lng = 24.001, 46.001
        dx, dy = maps._latlng_to_pixel_offset(lat, lng, 24, 46, 14, scale=2)
        x, y = 1280 + dx, 720 + dy - 11 * 2.56
        maps._draw_catchment_markers(self.path, 24, 46, 14,
            [{'name': 'معلم قريب من الموقع', 'lat': lat, 'lng': lng}],
            {'معلم قريب من الموقع': self.label_point(x, y)})
        with Image.open(self.path) as image:
            self.assertEqual(image.getpixel((round(x + 13), round(y)))[:3], (139, 32, 32))

    def test_road_text_stays_inside_the_name_pill(self):
        self.base()
        project = {
            'main_roads': 'طريق الملك فهد',
            'manual_road_paths': [{'name': 'طريق الملك فهد', 'points': [[24.0, 45.99], [24.0, 46.01]]}],
            'access_road_label_positions': {'طريق الملك فهد': self.label_point(700, 300)}
        }
        rendered = maps._draw_access_roads(self.path, 24, 46, 14, project_data=project, allow_discovery=False)
        self.assertEqual(len(rendered), 1)
        with Image.open(self.path) as image:
            pill = self.mask_bounds(image, (37, 75, 102))
            text = self.mask_bounds(image, (255, 255, 255))
        self.assertIsNotNone(pill)
        self.assertIsNotNone(text)
        self.assertGreaterEqual(text[1], pill[1])
        self.assertLessEqual(text[3], pill[3])

    def test_road_stroke_scales_with_image_width(self):
        for size in ((2560, 1440), (750, 422)):
            with self.subTest(size=size):
                self.base(size)
                maps._draw_access_roads(self.path, 24, 46, 14, project_data={
                    'main_roads': 'طريق الملك فهد',
                    'manual_road_paths': [{'name': 'طريق الملك فهد', 'points': [[24, 45.99], [24, 46.01]]}]
                }, allow_discovery=False)
                with Image.open(self.path) as image:
                    x, y = size[0] // 2, size[1] // 2
                    gold = [row for row in range(max(0, y - 40), min(size[1], y + 40))
                            if image.getpixel((x, row))[:3] == (212, 163, 89)]
                self.assertTrue(gold)
                self.assertAlmostEqual(len(gold), 9 * size[0] / 1000, delta=2)

    def test_catchment_cap_never_reintroduces_a_far_ring(self):
        zones = [{'km': 25, 'minutes': 30}, {'km': 65, 'minutes': 75}]
        self.assertEqual(maps.catchment_rings(zones), [])
        self.assertEqual(zones[0]['km'], 25)

    def test_catchment_bands_keep_a_city_frame_without_hiding_selected_landmarks(self):
        rings = maps.catchment_rings([{'km': km, 'minutes': 10} for km in (4, 8, 17.6, 65)])
        self.assertEqual([ring['km'] for ring in rings], [4, 8])
        self.assertEqual(maps.catchment_frame_fit(21.5, 39.2, 8, [])[0], 12)
        landmarks = [{'lat': 21.7, 'lng': 39.2}, {'lat': 21.5, 'lng': 39.35}]
        zoom, lat, lng = maps.catchment_frame_fit(21.5, 39.2, 8, landmarks)
        for landmark in landmarks:
            dx, dy = maps._latlng_to_pixel_offset(landmark['lat'], landmark['lng'], lat, lng, zoom, scale=2)
            self.assertLess(abs(dx), 1280)
            self.assertLess(abs(dy), 720)


class MapRecomposeParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch_dir = patch.object(maps, 'MAPS_DIR', self.temp.name)
        self.patch_dir.start()
        self.addCleanup(self.patch_dir.stop)
        self.base = str(Path(self.temp.name) / 'base.png')
        Image.new('RGB', (2560, 1440), (80, 100, 120)).save(self.base)

    def row(self, map_type, metadata, editable=True, size=(2560, 1440)):
        path = str(Path(self.temp.name) / (map_type + '-stored.png'))
        Image.new('RGB', size, (80, 100, 120)).save(path)
        return {'id': 'stored', 'image_type': map_type + ('_editable' if editable else ''),
                'file_path': path, 'placeholder': '##MAP_' + map_type.upper() + ('_EDITABLE##' if editable else '##'),
                'metadata_json': json.dumps(metadata)}

    def recompose(self, map_type, row, project=None):
        data = {'location_lat': 24, 'location_lng': 46, **(project or {})}
        with patch('db.get_map_images', return_value=[row]), patch('db.add_map_image', return_value='new'), \
                patch('db.update_map_image') as update, \
                patch.object(maps, '_fetch_map_base', return_value=self.base) as fetch, \
                patch.object(maps, '_apply_sepia_tone'), patch.object(maps, '_apply_map_overlay'), \
                patch.object(maps, '_draw_compass'), patch.object(maps, '_draw_inset_map') as inset, \
                patch.object(maps, '_record_maps_call'):
            result = getattr(maps, 'recompose_' + map_type + '_map')(data, 'tenant-test', draft_id='parity-test')
        return result, update, fetch, inset

    def test_recompose_updates_the_render_version_on_all_four_maps(self):
        for map_type in ('overview', 'access', 'catchment', 'landmarks'):
            with self.subTest(map_type=map_type):
                metadata = {'lat': 24, 'lng': 46, 'center_lat': 24, 'center_lng': 46, 'zoom': 12,
                            'map_label_version': 'old', 'map_highlight_version': maps.MAP_HIGHLIGHT_RENDER_VERSION}
                result, update, _, _ = self.recompose(map_type, self.row(map_type, metadata))
                self.assertNotIn('error', result)
                self.assertEqual(update.call_args.args[-1]['map_label_version'], maps.MAP_LABEL_RENDER_VERSION)

    def test_catchment_ring_content_changes_rebuild_even_when_the_frame_is_unchanged(self):
        old_zones = [{'km': 4, 'minutes': 5, 'label': 'منطقة'}]
        zoom, lat, lng = maps.catchment_frame_fit(24, 46, 4, [])
        for zones in ([{'km': 4, 'minutes': 12, 'label': 'منطقة'}],
                      [{'km': 4, 'minutes': 5, 'label': 'منطقة جديدة'}],
                      [{'km': 4.1, 'minutes': 5, 'label': 'منطقة'}]):
            with self.subTest(zones=zones):
                self.assertEqual(maps.catchment_frame_fit(24, 46, zones[0]['km'], []), (zoom, lat, lng))
                metadata = {'lat': 24, 'lng': 46, 'zoom': zoom, 'center_lat': lat, 'center_lng': lng,
                            'viewport_size': {'width': 1280, 'height': 720}, 'zones': old_zones,
                            'catchment_rings': maps.catchment_rings(old_zones)}
                with patch.object(maps, '_draw_catchment_zones', return_value=True) as draw:
                    result, update, fetch, _ = self.recompose(
                        'catchment', self.row('catchment', metadata), {'catchment_areas': zones})
                self.assertNotIn('error', result)
                fetch.assert_called_once()
                draw.assert_called_once()
                self.assertEqual(draw.call_args.args[4], maps.catchment_rings(zones))
                self.assertEqual(update.call_args.args[-1]['catchment_rings'], maps.catchment_rings(zones))

    def test_removing_the_last_catchment_ring_rebuilds_a_clean_base(self):
        zones = [{'km': 8, 'minutes': 10}]
        zoom, lat, lng = maps.catchment_frame_fit(24, 46, 8, [])
        metadata = {'lat': 24, 'lng': 46, 'zoom': zoom, 'center_lat': lat, 'center_lng': lng,
                    'viewport_size': {'width': 1280, 'height': 720}, 'zones': zones,
                    'catchment_rings': maps.catchment_rings(zones)}
        with patch.object(maps, '_draw_catchment_zones', return_value=True) as draw:
            result, update, fetch, _ = self.recompose(
                'catchment', self.row('catchment', metadata), {'catchment_areas': [{'km': 65, 'minutes': 75}]})
        self.assertNotIn('error', result)
        fetch.assert_called_once()
        draw.assert_not_called()
        self.assertEqual(update.call_args.args[-1]['catchment_rings'], [])

    def test_fixed_sidecar_rebuild_keeps_the_inset_and_canonical_size(self):
        for map_type in ('catchment', 'landmarks'):
            with self.subTest(map_type=map_type):
                metadata = {'lat': 24, 'lng': 46, 'center_lat': 24, 'center_lng': 46, 'zoom': 12,
                            'viewport_size': {'width': 375, 'height': 211}}
                result, update, fetch, inset = self.recompose(
                    map_type, self.row(map_type, metadata, size=(750, 422)))
                self.assertNotIn('error', result)
                fetch.assert_called_once()
                self.assertEqual(fetch.call_args.kwargs['size'], (1280, 720))
                inset.assert_called_once()
                self.assertEqual(result['centers'][map_type]['width'], 1280)
                self.assertEqual(result['centers'][map_type]['height'], 720)
                self.assertEqual(update.call_args.args[-1]['viewport_size'], {'width': 1280, 'height': 720})

    def test_fixed_sidecar_rebuild_does_not_fall_back_to_a_stale_frame_when_fetch_fails(self):
        for map_type in ('catchment', 'landmarks'):
            with self.subTest(map_type=map_type):
                metadata = {'lat': 24, 'lng': 46, 'center_lat': 24.1, 'center_lng': 46.1, 'zoom': 9}
                row = self.row(map_type, metadata)
                with patch.object(maps, '_fetch_map_base', return_value=None):
                    with patch('db.get_map_images', return_value=[row]), patch('db.add_map_image'), \
                            patch('db.update_map_image') as update:
                        result = getattr(maps, 'recompose_' + map_type + '_map')(
                            {'location_lat': 24, 'location_lng': 46,
                             'catchment_map_landmarks': [{'name': 'mall', 'lat': 24.01, 'lng': 46.01}],
                             'landmark_map_items': [{'name': 'mall', 'lat': 24.01, 'lng': 46.01}]},
                            'tenant-test', draft_id='parity-test')
                self.assertIn('error', result)
                update.assert_not_called()

    def test_fixed_maps_keep_metadata_landmarks_when_the_client_has_no_resolved_items(self):
        for map_type, key in (('catchment', 'catchment_landmarks'), ('landmarks', 'landmark_map_items')):
            with self.subTest(map_type=map_type):
                item = {'name': 'mall', 'lat': 24.04, 'lng': 46.01}
                metadata = {'lat': 24, 'lng': 46, 'center_lat': 24, 'center_lng': 46, 'zoom': 12, key: [item]}
                result, _, _, _ = self.recompose(map_type, self.row(map_type, metadata))
                self.assertEqual([row['name'] for row in result[key]], ['mall'])
                if map_type == 'landmarks':
                    self.assertEqual(result['zooms'][map_type], maps.catchment_frame_fit(24, 46, 0, [item])[0])


def render_browser_fixture(map_type):
    import base64

    size = (2560, 1440)
    center = {'lat': 24, 'lng': 46, 'width': 1280, 'height': 720}
    zoom = 14
    point = lambda x, y: list(maps._pixel_to_latlng(x, y, *size, 24, 46, zoom, scale=2))
    items = [
        {'name': 'مطار الملك عبدالعزيز الدولي', 'lat': 24.008, 'lng': 46.012},
        {'name': 'جدة سوبر دوم / مركز جدة للفعاليات', 'lat': 23.995, 'lng': 45.985},
        {'name': 'ROSHN Stadium / ملعب روشن', 'lat': 24.002, 'lng': 46.02},
    ]
    labels = {item['name']: point(x, y) for item, (x, y) in zip(items, ((550, 250), (700, 1050), (1950, 850)))}
    polygon = [[24.01, 45.99], [24.01, 46.01], [23.99, 46.01], [23.99, 45.99]]
    roads = [
        {'name': 'طريق الملك فهد', 'points': [[24, 45.98], [24, 46.02]], 'label_point': point(650, 350)},
        {'name': 'شارع التحلية', 'points': [[23.99, 45.98], [23.99, 46.02]], 'label_point': point(1800, 1200)}
    ]
    project = {'main_roads': '\n'.join(road['name'] for road in roads), 'manual_road_paths': roads,
               'access_road_label_positions': {road['name']: road['label_point'] for road in roads}}
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / 'map.png')
        Image.new('RGB', size, (80, 100, 120)).save(path)
        clean = 'data:image/png;base64,' + base64.b64encode(Path(path).read_bytes()).decode('ascii')
        if map_type in ('catchment', 'landmarks'):
            items = maps._draw_catchment_markers(path, 24, 46, zoom, items, labels)
            layouts = [maps._map_label_layout(item['name'], size[0]) for item in items]
        elif map_type == 'access':
            roads = maps._draw_access_roads(path, 24, 46, zoom, project_data=project, allow_discovery=False)
            maps._overlay_markers(path, 24, 46, zoom, maps._build_markers(24, 46))
            layouts = [maps._map_label_layout(road['name'], size[0], font_size=13, padding=(8, 4)) for road in roads]
        else:
            maps._draw_site_highlight(path, 24, 46, zoom, polygon_coords=polygon,
                                      auto_detect_polygon=False, auto_detected=False)
            maps._overlay_markers(path, 24, 46, zoom, maps._build_markers(24, 46))
            layouts = []
        marked = 'data:image/png;base64,' + base64.b64encode(Path(path).read_bytes()).decode('ascii')
    return {'type': map_type, 'clean': clean, 'marked': marked, 'items': items, 'roads': roads,
            'polygon': polygon, 'center': center, 'zoom': zoom,
            'layouts': [{'width': layout['width'], 'height': layout['height']} for layout in layouts]}


if __name__ == '__main__':
    unittest.main()
