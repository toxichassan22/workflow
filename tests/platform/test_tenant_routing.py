import os
import unittest
from flask import Flask

# Landloom imports are direct from repo root
import app as application_module
import db


class TestTenantRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = application_module.app
        cls.client = cls.app.test_client()

    def test_company_deep_links_return_spa_shell(self):
        urls = [
            '/c/demo/dashboard',
            '/c/demo/projects/new',
            '/c/demo/projects/new/market',
            '/c/demo/projects/draft-xyz-123',
            '/c/demo/projects/draft-xyz-123/location',
            '/c/demo/projects/draft-xyz-123/financial',
            '/c/demo/projects/draft-xyz-123/presentations',
            '/c/demo/projects/draft-xyz-123/visual-concept',
            '/c/demo/presentations',
            '/c/demo/presentations/current',
            '/c/demo/presentations/pres-888',
            '/c/demo/presentations/pres-888/sorter',
            '/c/demo/presentations/pres-888/present',
            '/c/demo/presentations/pres-888/slides/3',
            '/c/demo/settings/team',
            '/c/demo/approvals'
        ]
        for url in urls:
            with self.subTest(url=url):
                res = self.client.get(url, headers={'Accept': 'text/html'})
                self.assertEqual(res.status_code, 200, f'Expected 200 for {url}')
                self.assertIn(b'<!doctype html>', res.data.lower())

    def test_superadmin_deep_links_return_spa_shell(self):
        urls = [
            '/superadmin',
            '/superadmin/dashboard',
            '/superadmin/projects/new',
            '/superadmin/projects/draft-999/market',
            '/superadmin/projects/draft-999/presentations',
            '/superadmin/presentations/pres-111/sorter',
            '/superadmin/admin',
            '/superadmin/companies'
        ]
        for url in urls:
            with self.subTest(url=url):
                res = self.client.get(url, headers={'Accept': 'text/html'})
                self.assertEqual(res.status_code, 200, f'Expected 200 for {url}')
                self.assertIn(b'<!doctype html>', res.data.lower())

    def test_legacy_app_deep_links_return_spa_shell(self):
        urls = [
            '/app',
            '/app/dashboard',
            '/app/projects/new',
            '/app/presentations'
        ]
        for url in urls:
            with self.subTest(url=url):
                res = self.client.get(url, headers={'Accept': 'text/html'})
                self.assertEqual(res.status_code, 200, f'Expected 200 for {url}')
                self.assertIn(b'<!doctype html>', res.data.lower())


if __name__ == '__main__':
    unittest.main()
