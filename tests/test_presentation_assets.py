import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from presentation_assets import PresentationAssetError, freeze_presentation_assets


class PresentationAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.tenant = 'tenant-a'
        self.url = '/uploads/creative/tenant-a/cover.png'
        self.original = self.write(self.url, b'original image bytes')

    def write(self, url, data):
        path = self.root / url.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def freeze(self, value, **kwargs):
        return freeze_presentation_assets(value, self.tenant, root=self.root, **kwargs)

    def revision(self, data, extension='.png'):
        return '/uploads/creative/tenant-a/revisions/' + hashlib.sha256(data).hexdigest() + extension

    def test_recursive_html_css_plain_urls_and_serialized_json_without_mutation(self):
        original = {
            'slides': [{'html': '<img src="' + self.url + '?v=1">'
                        '<div style="background:url(\'' + self.url + '\')"></div>'}],
            'projectData': {'cover': self.url, 'copies': [self.url, None, True, 3]},
            'serialized': json.dumps({'slots': [{'imageUrl': self.url}]}),
        }
        untouched = json.loads(json.dumps(original))
        result = self.freeze(original)
        revision = self.revision(self.original.read_bytes())
        self.assertEqual(original, untouched)
        self.assertIsNot(result, original)
        self.assertEqual(result['projectData']['cover'], revision)
        self.assertEqual(result['projectData']['copies'], [revision, None, True, 3])
        self.assertEqual(result['slides'][0]['html'].count(revision), 2)
        self.assertEqual(json.loads(result['serialized'])['slots'][0]['imageUrl'], revision)
        self.assertEqual((self.root / revision.lstrip('/')).read_bytes(), self.original.read_bytes())

    def test_overwriting_source_cannot_change_existing_revision(self):
        first = self.freeze(self.url)
        self.original.write_bytes(b'replacement')
        second = self.freeze(self.url)
        self.assertNotEqual(first, second)
        self.assertEqual((self.root / first.lstrip('/')).read_bytes(), b'original image bytes')
        self.assertEqual((self.root / second.lstrip('/')).read_bytes(), b'replacement')
        self.original.unlink()
        self.assertEqual(self.freeze(first), first)
        self.assertEqual(self.freeze(second), second)

    def test_already_frozen_urls_are_verified_and_idempotent(self):
        revision = self.freeze(self.url)
        self.assertEqual(self.freeze(revision + '?v=4#view'), revision + '#view')
        self.write(revision, b'tampered')
        with self.assertRaisesRegex(PresentationAssetError, 'hash'):
            self.freeze(revision)
        with self.assertRaisesRegex(PresentationAssetError, 'hash'):
            self.freeze(self.url)

    def test_missing_revision_is_not_treated_as_success(self):
        missing = self.revision(b'missing')
        with self.assertRaisesRegex(PresentationAssetError, 'missing'):
            self.freeze(missing)

    def test_deduplication_and_atomic_parallel_publication(self):
        expected = self.revision(self.original.read_bytes())
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self.freeze, [self.url] * 20))
        self.assertEqual(results, [expected] * 20)
        files = list((self.root / 'uploads/creative/tenant-a/revisions').iterdir())
        self.assertEqual([path.name for path in files], [Path(expected).name])
        copy = '/uploads/creative/tenant-a/other.png'
        self.write(copy, self.original.read_bytes())
        self.assertEqual(self.freeze(copy), expected)

    def test_remote_and_inline_refs_unchanged_without_network(self):
        values = ['https://remote.example' + self.url,
                  '//remote.example' + self.url,
                  'data:image/png;base64,AAAA', 'https://remote.example/image.png',
                  '#layer', '##MAP_OVERVIEW##', '/app/projects', 'ordinary text']
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            self.assertEqual(self.freeze(values), values)
            html = '<img src="https://remote.example' + self.url + '">'
            self.assertEqual(self.freeze(html), html)

    def test_verified_absolute_origin_and_scheme_relative_urls(self):
        origin = 'https://site.example'
        revision = self.revision(self.original.read_bytes())
        values = [origin + self.url, '//site.example' + self.url,
                  'https://SITE.example:443' + self.url]
        self.assertEqual(self.freeze(values, allowed_origin=origin), [revision] * 3)
        others = ['http://site.example' + self.url,
                  'https://site.example:8443' + self.url,
                  'https://site.example.evil' + self.url,
                  'https://site.example@evil.example' + self.url]
        self.assertEqual(self.freeze(others, allowed_origin=origin), others)
        self.assertEqual(self.freeze(origin + self.url), origin + self.url)

    def test_flask_request_host_is_used_without_app_or_config_import(self):
        from flask import Flask
        app = Flask(__name__)
        with app.test_request_context('/', base_url='https://request.example'):
            self.assertEqual(self.freeze('https://request.example' + self.url),
                             self.revision(self.original.read_bytes()))
            remote = 'https://elsewhere.example' + self.url
            self.assertEqual(self.freeze(remote), remote)

    def test_tenant_fonts_and_public_media_keep_bytes_and_fragment(self):
        font = self.write('/uploads/tenant-a/fonts/Arabic.woff2', b'font bytes')
        logo = self.write('/assets/logo.png', b'public logo')
        value = ('@font-face{src:url(/tenant-assets/tenant-a/fonts/Arabic.woff2?v=1#face)}'
                 'body{background-image:url("/assets/logo.png")}')
        result = self.freeze(value)
        self.assertIn(self.revision(font.read_bytes(), '.woff2') + '#face', result)
        self.assertIn(self.revision(logo.read_bytes()), result)

    def test_relative_paths_percent_encoding_html_entities_and_srcset(self):
        self.write('/uploads/creative/tenant-a/land photo.png', b'photo')
        html = ('<img srcset="' + self.url + '?v=1&amp;z=2 1x, '
                '/uploads/creative/tenant-a/land%20photo.png 2x">')
        result = self.freeze(html)
        self.assertIn(self.revision(b'photo') + ' 2x', result)
        self.assertIn(self.revision(self.original.read_bytes()) + ' 1x', result)
        self.assertNotIn('&amp;', result)
        self.assertEqual(self.freeze('uploads/creative/tenant-a/cover.png'),
                         self.freeze('./uploads/creative/tenant-a/cover.png'))

    def test_encoded_html_and_css_urls_are_not_missed(self):
        encoded = '/%75ploads/creative/tenant-a/cover.png'
        double = '/%2575ploads/creative/tenant-a/cover.png'
        expected = self.revision(self.original.read_bytes())
        self.assertEqual(self.freeze(encoded), expected)
        self.assertIn(expected, self.freeze('<img src="' + double + '">'))
        self.assertIn(expected, self.freeze(r'background:url(/\75 ploads/creative/tenant-a/cover.png)'))
        self.assertIn(expected, self.freeze('<img src="&#47;uploads/creative/tenant-a/cover.png">'))
        with self.assertRaises(PresentationAssetError):
            self.freeze(r'background:url(/uploads/creative/tenant-a/\2e\2e /tenant-b/cover.png)')

    def test_missing_local_assets_raise_clear_redacted_errors(self):
        with self.assertRaises(PresentationAssetError) as caught:
            self.freeze('<img src="/uploads/creative/tenant-a/missing.png?token=SECRET">')
        self.assertIn('missing.png', str(caught.exception))
        self.assertIn('missing', caught.exception.reason)
        self.assertNotIn('SECRET', str(caught.exception))

    def test_tenant_identity_and_cross_tenant_paths_are_strict(self):
        for tenant in ('', None, '../a', 'tenant.a', 'tenant/a', 'a' * 129):
            with self.subTest(tenant=tenant), self.assertRaises(PresentationAssetError):
                freeze_presentation_assets(self.url, tenant, root=self.root)
        self.write('/uploads/creative/tenant-b/cover.png', b'other tenant')
        self.write('/uploads/tenant-b/fonts/font.woff', b'other font')
        for url in ('/uploads/creative/tenant-b/cover.png',
                    '/uploads/tenant-b/fonts/font.woff',
                    '/tenant-assets/tenant-b/fonts/font.woff',
                    '/tenant-assets/tenant-b/logo'):
            with self.subTest(url=url), self.assertRaises(PresentationAssetError):
                self.freeze(url)

    def test_traversal_encoded_traversal_and_windows_special_paths_rejected(self):
        paths = [
            '../uploads/creative/tenant-a/cover.png',
            '/%2fuploads/creative/tenant-a/cover.png',
            '/uploads/creative/tenant-a/../tenant-b/cover.png',
            '/uploads/creative/tenant-a/%2e%2e/tenant-b/cover.png',
            '/uploads/creative/tenant-a/%252e%252e%252ftenant-b/cover.png',
            '/uploads/creative/tenant-a/%5c..%5csecret.png',
            '/uploads/creative/tenant-a/a.png:stream.png',
            '/uploads/creative/tenant-a/%00cover.png',
            '/uploads/creative/tenant-a//cover.png',
            '/uploads/creative/tenant-a/.secret.png',
            '/uploads/creative/tenant-a/cover.png.',
            '/uploads/creative/tenant-a/cover.png%20',
            '/uploads/creative/tenant-a/%ff.png',
        ]
        for url in paths:
            with self.subTest(url=url), self.assertRaises(PresentationAssetError):
                self.freeze('<img src="' + url + '">')

    def test_private_files_apis_and_unowned_flat_maps_fail_closed(self):
        self.write('/uploads/tenant-a/project-documents/private.png', b'private image')
        self.write('/uploads/tenant-a/project-documents/private.pdf', b'private document')
        self.write('/uploads/maps/tenanta_draft_overview_12345678.png', b'map')
        self.write('/assets/config.json', b'private configuration')
        for url in ('/uploads/tenant-a/project-documents/private.png',
                    '/uploads/tenant-a/project-documents/private.pdf',
                    '/api/project-files/private', '/api/branding/font.css',
                    '/api/map-images/123', '/tenant-assets/tenant-a/logo',
                    '/tenant-assets/tenant-a/watermark',
                    '/uploads/maps/tenanta_draft_overview_12345678.png',
                    '/assets/config.json', 'file:///etc/passwd', 'blob:https://site/id'):
            with self.subTest(url=url), self.assertRaises(PresentationAssetError):
                self.freeze(url)

    def test_explicit_authorized_maps_require_exact_urls_not_tenant_prefixes(self):
        url = '/uploads/maps/tenanta_draft_overview_12345678.png'
        self.write(url, b'authorized map')
        allowed = [url + '?v=1']
        self.assertEqual(self.freeze(url + '?v=2', authorized_paths=allowed),
                         self.revision(b'authorized map'))
        other = '/uploads/maps/tenanta_draft_overview_abcdefgh.png'
        self.write(other, b'same truncated prefix but unproven ownership')
        with self.assertRaises(PresentationAssetError):
            self.freeze(other, authorized_paths=allowed)

    def test_authorized_alias_mapping_uses_exact_trusted_file(self):
        logo = self.write('/uploads/tenant-a/logo.jpg', b'chosen logo')
        self.write('/uploads/tenant-a/logo.png', b'not chosen')
        project = self.write('/uploads/tenant-a/project-documents/id.png', b'authorized image')
        watermark = self.write('/uploads/tenant-a/watermark.webp', b'chosen watermark')
        allowed = {'/tenant-assets/tenant-a/logo': logo,
                   '/tenant-assets/tenant-a/watermark': watermark,
                   '/api/project-files/id': project}
        self.assertEqual(self.freeze(list(allowed), authorized_paths=allowed), [
            self.revision(b'chosen logo', '.jpg'),
            self.revision(b'chosen watermark', '.webp'),
            self.revision(b'authorized image'),
        ])

    def test_authorization_mapping_cannot_escape_tenant_or_publish_non_media(self):
        bad_paths = [self.write('/uploads/tenant-b/logo.png', b'other logo'),
                     self.write('/secrets.png', b'secret'),
                     self.write('/uploads/tenant-a/project-documents/private.pdf', b'pdf')]
        for path in bad_paths:
            with self.subTest(path=path), self.assertRaises(PresentationAssetError):
                self.freeze('/api/project-files/id', authorized_paths={'/api/project-files/id': path})
        with self.assertRaises(PresentationAssetError):
            self.freeze('/tenant-assets/tenant-b/logo', authorized_paths={
                '/tenant-assets/tenant-b/logo': self.original})

    def make_symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            self.skipTest(f'Symlink creation unavailable: {error}')

    def test_source_file_and_directory_symlinks_rejected_even_inside_tenant(self):
        link = self.original.parent / 'linked.png'
        self.make_symlink(link, self.original)
        with self.assertRaisesRegex(PresentationAssetError, 'symlink'):
            self.freeze('/uploads/creative/tenant-a/linked.png')
        fonts = self.root / 'uploads/tenant-a/fonts'
        fonts.parent.mkdir(parents=True)
        self.make_symlink(fonts, self.original.parent, directory=True)
        with self.assertRaisesRegex(PresentationAssetError, 'symlink'):
            self.freeze('/tenant-assets/tenant-a/fonts/cover.png')

    def test_destination_symlink_rejected_without_writing_outside(self):
        outside = self.root / 'outside'
        outside.mkdir()
        self.make_symlink(self.original.parent / 'revisions', outside, directory=True)
        with self.assertRaisesRegex(PresentationAssetError, 'symlink'):
            self.freeze(self.url)
        self.assertEqual(list(outside.iterdir()), [])

    def test_destination_file_symlink_rejected_without_overwriting(self):
        target = self.root / self.revision(self.original.read_bytes()).lstrip('/')
        target.parent.mkdir()
        self.make_symlink(target, self.original)
        with self.assertRaisesRegex(PresentationAssetError, 'symlink'):
            self.freeze(self.url)
        self.assertEqual(self.original.read_bytes(), b'original image bytes')

    def test_reparse_points_rejected_even_without_symlink_privileges(self):
        original_lstat = Path.lstat
        for unsafe in (self.original, self.original.parent, self.root / 'uploads'):
            def fake_lstat(path, *args, **kwargs):
                result = original_lstat(path, *args, **kwargs)
                if path == unsafe:
                    return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
                return result

            with self.subTest(path=unsafe), patch.object(Path, 'lstat', fake_lstat):
                with self.assertRaisesRegex(PresentationAssetError, 'reparse'):
                    self.freeze(self.url)

    def test_non_regular_source_is_rejected(self):
        url = '/uploads/creative/tenant-a/directory.png'
        (self.root / url.lstrip('/')).mkdir()
        with self.assertRaisesRegex(PresentationAssetError, 'regular file'):
            self.freeze(url)

    def test_authorization_does_not_accept_a_string_or_arbitrary_iterable_paths(self):
        for paths in (self.url, [self.url], ['https://remote.example/map.png']):
            with self.subTest(paths=paths), self.assertRaises(PresentationAssetError):
                self.freeze(self.url, authorized_paths=paths)

    def test_explicit_paths_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            path = Path(elsewhere) / 'secret.png'
            path.write_bytes(b'secret')
            with self.assertRaisesRegex(PresentationAssetError, 'outside'):
                self.freeze('/api/project-files/secret', authorized_paths={
                    '/api/project-files/secret': path})

    def test_reserved_map_namespace_never_becomes_a_tenant_grant(self):
        self.write('/uploads/maps/logo.png', b'unowned map')
        with self.assertRaises(PresentationAssetError):
            freeze_presentation_assets('/uploads/maps/logo.png', 'maps', root=self.root)

    def test_failed_atomic_publication_leaves_no_partial_file(self):
        with patch('presentation_assets.os.link', side_effect=OSError('write failed')):
            with self.assertRaisesRegex(PresentationAssetError, 'atomically'):
                self.freeze(self.url)
        self.assertEqual(list((self.original.parent / 'revisions').iterdir()), [])

    def test_default_root_is_module_directory_not_flask_working_directory(self):
        with patch('presentation_assets.ROOT', self.root):
            self.assertEqual(freeze_presentation_assets(self.url, self.tenant),
                             self.revision(self.original.read_bytes()))


if __name__ == '__main__':
    unittest.main()
