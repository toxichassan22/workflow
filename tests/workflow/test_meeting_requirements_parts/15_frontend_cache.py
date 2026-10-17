class MeetingRequirementsTestsPart15(MeetingRequirementsTests):

    def test_frontend_bundles_use_versioned_long_lived_cache_urls(self):
        client = self.app.test_client()
        response = client.get('/app')
        self.assertEqual(response.status_code, 200)
        shell = response.get_data(as_text=True)
        assets = (
            (r'src="/assets/i18n\.bundle\.js\?v=([0-9a-f]{20})"',
             '/assets/i18n.bundle.js'),
            (r'href="/assets/app\.bundle\.css\?v=([0-9a-f]{20})"',
             '/assets/app.bundle.css'),
            (r'src="/assets/app\.bundle\.js\?v=([0-9a-f]{20})"',
             '/assets/app.bundle.js'),
        )
        for pattern, path in assets:
            match = re.search(pattern, shell)
            self.assertIsNotNone(match, path)
            url = path + '?v=' + match.group(1)
            bundle = client.get(url)
            self.assertEqual(bundle.status_code, 200, path)
            self.assertEqual(
                bundle.headers.get('Cache-Control'),
                'public, max-age=31536000, immutable', path)
            revalidated = client.get(url, headers={
                'If-None-Match': bundle.headers['ETag'],
            })
            self.assertEqual(revalidated.status_code, 304, path)

    def test_unversioned_frontend_bundle_still_revalidates(self):
        response = self.app.test_client().get('/assets/app.bundle.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Cache-Control'), 'no-cache')
