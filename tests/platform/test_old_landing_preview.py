import unittest
from app import app


class TestOldLandingPreview(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_old_landing_route_serves_cinematic_page(self):
        resp = self.client.get('/old-landing')
        self.assertEqual(resp.status_code, 200)
        text = resp.get_data(as_text=True)
        self.assertIn('id="intro"', text)
        self.assertIn('id="introCam"', text)
        self.assertIn('id="introPath"', text)
        self.assertIn('LANDLOOM', text)
        self.assertIn('/pages/old-site-landing.css', text)
        self.assertIn('/pages/old-site.js', text)

    def test_old_landing_assets_serve_correctly(self):
        css_resp = self.client.get('/pages/old-site-landing.css')
        self.assertEqual(css_resp.status_code, 200)
        self.assertIn('.intro', css_resp.get_data(as_text=True))

        js_resp = self.client.get('/pages/old-site.js')
        self.assertEqual(js_resp.status_code, 200)
        self.assertIn('initOpening', js_resp.get_data(as_text=True))

    def test_scroll_landing_route_serves_scroll_page(self):
        resp = self.client.get('/scroll-landing')
        self.assertEqual(resp.status_code, 200)
        text = resp.get_data(as_text=True)
        self.assertIn('id="opening"', text)
        self.assertIn('LANDLOOM', text)

    def test_live_landing_remains_active_and_untouched(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        text = resp.get_data(as_text=True)
        self.assertIn('id="intro"', text)
        self.assertIn('id="introCue"', text)
        self.assertIn('class="op-cue"', text)
        self.assertIn('/pages/site-landing.css', text)
        self.assertIn('/pages/site.js', text)

        css_resp = self.client.get('/pages/site-landing.css')
        self.assertEqual(css_resp.status_code, 200)
        self.assertIn('.op-cue', css_resp.get_data(as_text=True))

    def test_live_landing_intro_centered_and_uses_official_logo(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        text = resp.get_data(as_text=True)
        self.assertIn('intro-brand-logo', text)
        self.assertIn('landloom-wordmark-white', text)
        self.assertIn('L45.6 163.4 L36.5 138.3 Z', text)

        nav_about_idx = text.find('href="/about"')
        nav_features_idx = text.find('href="/#features"')
        self.assertTrue(0 <= nav_about_idx < nav_features_idx, "'من نحن' must appear first in site navigation")

        css_resp = self.client.get('/pages/site-landing.css')
        self.assertEqual(css_resp.status_code, 200)
        css_text = css_resp.get_data(as_text=True)
        self.assertNotIn('translate(5%, -16%)', css_text)
        self.assertIn('.intro-brand-logo', css_text)


if __name__ == '__main__':
    unittest.main()
