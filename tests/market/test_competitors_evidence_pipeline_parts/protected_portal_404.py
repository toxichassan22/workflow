from unittest.mock import patch

from tests.market import test_competitors_evidence_pipeline as pipeline


class _Response:
    def __init__(self, status):
        self.status_code = status

    def close(self):
        pass


class ProtectedPortal404Tests(pipeline._MarketTestBase):
    """A protected portal's 404 is a refusal, not proof the page is gone."""

    def test_aqar_404_never_marks_a_source_dead(self):
        module = self.module
        with patch.object(module, '_public_host_addresses', return_value=True), \
                patch.object(module.requests, 'head',
                             return_value=_Response(404)), \
                patch.object(module.requests, 'get',
                             return_value=_Response(404)):
            self.assertTrue(module._market_url_alive(
                'https://sa.aqar.fm/فلل-للبيع/جدة'))
            self.assertFalse(module._market_url_alive(
                'https://example.com/missing-page'))
