class MeetingRequirementsTestsPart21(MeetingRequirementsTests):

    GENERATED_HTML = (
        '<div class="slide" style="width:1280px;height:720px;position:relative;">'
        '<h1>محتوى</h1></div>'
    )

    def _generate_one_slide(self, watermark=None, watermark_path=None):
        with self.app.app_context():
            db.update_branding(self.tenant_a, watermark_path=watermark_path)
        payload = {
            'projectData': {},
            'slidePlan': {'slides': [{'title': 'محتوى', 'type': 'content'}]},
            'slideIndex': 0,
        }
        if watermark is not None:
            payload['watermark'] = watermark
        client = self.app.test_client()
        with patch.object(self.application_module.slide_engine, 'generate_single_slide',
                          return_value=self.GENERATED_HTML), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images',
                             return_value={}):
            response = client.post('/api/generate-slide-single',
                                   headers=self._headers(self.token_a), json=payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['slide']['html']

    def test_slide_generation_applies_the_company_watermark_when_requested(self):
        watermark_path = f'/tenant-assets/{self.tenant_a}/watermark'
        html = self._generate_one_slide(watermark=True, watermark_path=watermark_path)
        self.assertIn('data-slide-watermark="true"', html)
        self.assertIn('data-watermark-visible="true"', html)
        self.assertIn(watermark_path, html)
        self.assertIn('opacity:0.045', html)

    def test_slide_generation_leaves_the_slide_unmarked_without_the_choice(self):
        html = self._generate_one_slide(
            watermark_path=f'/tenant-assets/{self.tenant_a}/watermark')
        self.assertNotIn('data-slide-watermark', html)

    def test_requested_watermark_without_an_uploaded_asset_keeps_the_slide_unmarked(self):
        html = self._generate_one_slide(watermark=True, watermark_path=None)
        self.assertNotIn('data-slide-watermark', html)

    def test_generation_never_uses_a_watermark_url_from_the_request(self):
        html = self._generate_one_slide(
            watermark='https://evil.example/watermark.png',
            watermark_path=f'/tenant-assets/{self.tenant_a}/watermark')
        self.assertNotIn('evil.example', html)
        self.assertNotIn('data-slide-watermark', html)

    def test_generation_frontend_asks_for_the_watermark_in_both_entry_points(self):
        frontend = read_frontend_text()
        full = frontend.split('async function directGenerateProposalFile()', 1)[1]
        full = full.split('\n    async function submitTenantProject', 1)[0]
        self.assertIn('askGenerationWatermarkPreference()', full)
        self.assertIn('watermark: watermarkChoice', full)
        section = frontend.split('async function generateProjectSectionPresentation(', 1)[1]
        section = section.split('\n    async function ', 1)[0]
        self.assertIn('askGenerationWatermarkPreference()', section)
        self.assertIn('watermark: watermarkChoice', section)

    def test_generation_frontend_carries_the_watermark_through_payload_and_resume(self):
        frontend = read_frontend_text()
        options = frontend.split('function tenantSlideGenerationOptions(', 1)[1]
        options = options.split('\n    }', 1)[0]
        self.assertIn('watermark: options.watermark === true', options)
        payload = frontend.split('function buildSlidePayload(i) {', 1)[1]
        payload = payload.split('\n        }', 1)[0]
        self.assertIn('genPayload.watermark = runWatermark;', payload)
        generator = frontend.split('async function generateTenantSlides(', 1)[1]
        self.assertIn('const runWatermark = options.watermark === true;', generator)

    def test_section_regeneration_keeps_the_deck_watermark(self):
        frontend = read_frontend_text()
        section = frontend.split('async function regenerateTenantSection(', 1)[1]
        section = section.split('\n    function buildPresentationGenerationImages', 1)[0]
        self.assertIn('applyDeckWatermarkToHtml(', section)
        self.assertIn('deckHadWatermark', section)
