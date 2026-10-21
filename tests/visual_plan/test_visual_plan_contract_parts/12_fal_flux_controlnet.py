import base64
import os
from unittest.mock import patch


class VisualPlanContractTestsPart12(VisualPlanContractBase):
    """Fal.ai FLUX ControlNet integration tests for architectural massing grounding."""

    def test_has_fal_key_reflects_environment(self):
        module = self.application_module
        with patch.dict(os.environ, {'FAL_KEY': ''}):
            self.assertFalse(module.has_fal_key())

        with patch.dict(os.environ, {'FAL_KEY': 'fal-test-key-12345'}):
            self.assertTrue(module.has_fal_key())

    def test_call_fal_flux_controlnet_invokes_endpoint_with_canny_controlnet(self):
        module = self.application_module
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
               '<rect x="0" y="0" width="40" height="20" fill="#123456"/></svg>')
        svg_data_uri = 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode('utf-8')).decode('ascii')

        captured_post = {}
        def _fake_post(url, headers=None, json=None, timeout=None):
            captured_post['url'] = url
            captured_post['headers'] = headers
            captured_post['json'] = json
            class _Resp:
                status_code = 200
                content = b'{"images": [{"url": "https://v3.fal.media/files/sample.jpeg"}]}'
                def json(self):
                    return {'images': [{'url': 'https://v3.fal.media/files/sample.jpeg'}]}
            return _Resp()

        def _fake_get(url, timeout=None):
            class _GetResp:
                status_code = 200
                content = b'FAKE_JPEG_IMAGE_BYTES'
            return _GetResp()

        with patch.dict(os.environ, {'FAL_KEY': 'fal_secret_token_abc'}), \
                patch.object(module.requests, 'post', side_effect=_fake_post), \
                patch.object(module.requests, 'get', side_effect=_fake_get):
            res = module.call_fal_flux_controlnet(
                'Photorealistic modern building',
                control_image=svg_data_uri,
                usage_ctx={'tenant_id': self.tenant_a},
            )

        self.assertIsNotNone(res)
        self.assertTrue(res.startswith('data:image/jpeg;base64,'))
        self.assertEqual(captured_post['headers'].get('Authorization'), 'Key fal_secret_token_abc')
        self.assertIn('fal-ai/flux-general', captured_post['url'])
        controlnets = captured_post['json'].get('controlnets', [])
        self.assertEqual(len(controlnets), 1)
        self.assertEqual(controlnets[0].get('path'), 'InstantX/FLUX.1-dev-Controlnet-Canny')
        self.assertTrue(controlnets[0].get('control_image_url', '').startswith('data:image/png;base64,'))

    def test_visual_concept_uses_fal_controlnet_when_key_present(self):
        module = self.application_module
        data = {
            'prompt': 'Hero facade view',
            'slotId': 'cover',
            'planImages': {
                'site': '/uploads/creative/tenant/plan1.svg',
                'massing': '/uploads/creative/tenant/plan3.svg',
            },
            'projectData': {'projectName': 'Al Waha', 'city': 'Riyadh'},
        }

        with self.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            with patch.object(module, 'has_fal_key', return_value=True), \
                    patch.object(module, 'call_fal_flux_controlnet', return_value='data:image/jpeg;base64,TEST_FAL') as mock_fal, \
                    patch.object(module, 'persist_generated_image', return_value='/uploads/creative/tenant/fal_cover.jpg'), \
                    patch.object(module, '_visual_concept_request_bundle',
                                 return_value=({}, {'plan_image_map': {'massing': '/uploads/creative/tenant/plan3.svg'}}, [])):
                result, status = module._visual_concept_generate_image_result(data, 'cover')

        self.assertEqual(status, 200)
        self.assertTrue(result['success'])
        self.assertEqual(result['image'], '/uploads/creative/tenant/fal_cover.jpg')
        mock_fal.assert_called_once()
