"""Ministry of Tourism report discovery, caching, extraction and source limits."""

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKET_MODULES = ROOT / 'modules' / 'market'
WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for path in (str(ROOT), str(MARKET_MODULES), str(WEB_BROWSE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import evidence  # noqa: E402
import tourism_report_sync as sync  # noqa: E402


class _Response:
    def __init__(self, payload=None, body=b'', status=200, headers=None):
        self._payload = payload
        self._body = body
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=0):
        for offset in range(0, len(self._body), max(1, chunk_size)):
            yield self._body[offset:offset + chunk_size]

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, catalog, pdf_body=b'', pdf_status=200, pdf_headers=None):
        self.catalog = catalog
        self.pdf_body = pdf_body
        self.pdf_status = pdf_status
        self.pdf_headers = pdf_headers or {}
        self.catalog_calls = 0
        self.pdf_calls = 0
        self.closed = False

    def get(self, url, **kwargs):
        if url == sync.PUBLICATIONS_API:
            self.catalog_calls += 1
            return _Response(payload=self.catalog)
        self.pdf_calls += 1
        if self.pdf_status in (301, 302, 303, 307, 308):
            return _Response(status=self.pdf_status, headers=self.pdf_headers)
        return _Response(body=self.pdf_body, status=self.pdf_status,
                         headers=self.pdf_headers)

    def close(self):
        self.closed = True


def _pdf_bytes():
    import fitz
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), 'Saudi tourism annual report')
    page = document.new_page()
    page.insert_text((72, 72),
                     'Jeddah Al Andalus hotel occupancy 73 percent; ADR 540 SAR')
    page = document.new_page()
    page.insert_text((72, 72), 'Dammam industrial warehouse supply')
    body = document.tobytes()
    document.close()
    return body


def _catalog(pdf_url='https://cdn.mt.gov.sa/reports/hospitality-2026.pdf'):
    return {'data': [{
        'id': 12,
        'attributes': {
            'title': 'أداء قطاع الضيافة لعام 2026',
            'category': {'data': {'attributes': {'title': 'التقارير'}}},
            'year': 2026,
            'publishedDate': '2026-09-15',
            'file': {'data': {'attributes': {'url': pdf_url}}},
        },
    }]}


class TourismReportSyncTests(unittest.TestCase):
    def test_sync_downloads_extracts_and_attaches_city_relevant_pdf_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pool = evidence.EvidencePool()
            session = _FakeSession(_catalog(), pdf_body=_pdf_bytes())
            result = sync.sync_ministry_tourism_reports(
                evidence_pool=pool, city=['Jeddah'], district=['Al Andalus'],
                cache_dir=temp_dir, session=session,
                today=date(2026, 10, 18))

            self.assertEqual(result['records_seen'], 1)
            self.assertEqual(len(result['reports']), 1)
            self.assertEqual(result['reports'][0]['page_count'], 3)
            self.assertTrue(result['reports'][0]['downloaded'])
            self.assertEqual(session.catalog_calls, 1)
            self.assertEqual(session.pdf_calls, 1)
            pages = pool.pages()
            self.assertTrue(any('#page=2' in page['url'] for page in pages), pages)
            self.assertTrue(any('Al Andalus' in page['content'] for page in pages), pages)
            self.assertEqual(result['pages_added'], len(pages))
            self.assertTrue(any(Path(temp_dir).glob('ministry_12_*.pdf')))

    def test_reuses_recent_cache_without_downloading_pdf_again(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = _FakeSession(_catalog(), pdf_body=_pdf_bytes())
            first = sync.sync_ministry_tourism_reports(
                cache_dir=temp_dir, session=session, today=date(2026, 10, 18))
            second = sync.sync_ministry_tourism_reports(
                cache_dir=temp_dir, session=session, today=date(2026, 10, 18))

            self.assertEqual(first['reports'][0]['downloaded'], True)
            self.assertEqual(second['reports'][0]['cached'], True)
            self.assertEqual(session.catalog_calls, 2)
            self.assertEqual(session.pdf_calls, 1)
            self.assertGreater(second['pages_selected'], 0)

    def test_rejects_pdf_urls_and_redirects_outside_ministry_cdn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            external = _FakeSession(
                _catalog('https://attacker.example/fake.pdf'),
                pdf_body=_pdf_bytes())
            rejected = sync.sync_ministry_tourism_reports(
                cache_dir=temp_dir, session=external, today=date(2026, 10, 18))
            self.assertEqual(rejected['reports'], [])
            self.assertEqual(external.pdf_calls, 0)

            redirected = _FakeSession(
                _catalog(), pdf_status=302,
                pdf_headers={'Location': 'https://attacker.example/fake.pdf'})
            blocked = sync.sync_ministry_tourism_reports(
                cache_dir=temp_dir, session=redirected, today=date(2026, 10, 18))
            self.assertEqual(blocked['reports'], [])
            self.assertTrue(any(item['reason'] == 'pdf_redirect_not_allowed'
                                for item in blocked['errors']))

    def test_report_context_is_only_given_to_an_allowed_ministry_researcher(self):
        reports = [{
            'title': 'Hospitality report', 'year': 2026,
            'url': 'https://cdn.mt.gov.sa/reports/hospitality.pdf',
            'pages': [{'page_number': 2, 'content': 'Jeddah occupancy was 73 percent.'}],
        }]
        allowed = sync.format_research_context(reports, ['mt.gov.sa'])
        blocked = sync.format_research_context(reports, ['booking.com'])
        self.assertIn('cdn.mt.gov.sa/reports/hospitality.pdf', allowed)
        self.assertIn('Jeddah occupancy was 73 percent', allowed)
        self.assertEqual(blocked, '')

    def test_duplicate_editions_of_the_same_publication_collapse(self):
        reports = [
            {'year': 2025, 'published_date': '2026-07-29',
             'title': 'التقرير الإحصائي السنوي - نسخة تفاعلية', 'url': 'https://cdn.mt.gov.sa/a.pdf'},
            {'year': 2025, 'published_date': '2026-07-28',
             'title': 'التقرير الإحصائي السنوي - نسخة جوال تفاعلية', 'url': 'https://cdn.mt.gov.sa/b.pdf'},
        ]
        deduped = sync._dedupe_publications(reports)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]['url'], 'https://cdn.mt.gov.sa/a.pdf')

    def test_recent_selection_keeps_annual_baselines(self):
        annuals = [{
            'id': str(year), 'year': year,
            'published_date': f'{year}-12-01',
            'title': f'التقرير الإحصائي السنوي للإحصاءات السياحية لعام {year}',
            'url': f'https://cdn.mt.gov.sa/annual-{year}.pdf',
        } for year in (2023, 2024, 2025)]
        recent = [{
            'id': f'q{index}', 'year': 2026,
            'published_date': f'2026-10-{18 - index:02d}',
            'title': f'مؤشرات السياحة المحلية للربع {index}',
            'url': f'https://cdn.mt.gov.sa/report-{index}.pdf',
        } for index in range(1, 15)]
        selected = sync._select_publications(annuals + recent, max_reports=10)
        selected_urls = {item['url'] for item in selected}
        self.assertTrue(all(item['url'] in selected_urls for item in annuals))
        self.assertEqual(len(selected), 10)


if __name__ == '__main__':
    unittest.main()
