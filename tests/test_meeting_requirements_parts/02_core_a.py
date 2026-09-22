class MeetingRequirementsTestsPart01(MeetingRequirementsTests):

    def test_map_zoom_caps_overview_and_preserves_context(self):
        zooms = self.application_module.maps_service._calculate_map_zooms([
            (21.63200, 39.10500),
            (21.63201, 39.10501),
            (21.63200, 39.10501),
        ])

        # The old cap of 17 left a 7,000 sqm plot as a dot on the slide. The croquis boundary
        # is exact, so the plot view may go to 19 while the context views stay wider.
        self.assertLessEqual(zooms['overview'], 19)
        self.assertEqual(zooms['landmarks'], max(14, min(17, zooms['overview'] - 2)))
        self.assertEqual(zooms['access'], max(15, min(17, zooms['overview'])))
        self.assertEqual(self.application_module.maps_service.access_map_zoom(21.63, 19), 16)
        self.assertLessEqual(zooms['catchment'], 14)

    def test_google_places_errors_are_explicit_instead_of_empty_success(self):
        response = Mock(status_code=403)
        response.json.return_value = {
            'error': {'status': 'PERMISSION_DENIED', 'message': 'Places API (New) is not enabled'}
        }
        with patch.object(self.application_module.maps_service.requests, 'post', return_value=response):
            result = self.application_module.maps_service.get_nearby_landmarks(24.0, 46.0)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_code'], 'GOOGLE_PLACES_HTTP_ERROR')
        self.assertIn('Places API (New) is not enabled', result['error'])

    def test_preview_map_data_surfaces_google_places_errors(self):
        client = self.app.test_client()
        with patch.object(self.application_module.maps_service, 'get_nearby_landmarks', return_value={
            'success': False,
            'error': 'Google Places API HTTP 403: Places API (New) is not enabled',
            'error_code': 'GOOGLE_PLACES_HTTP_ERROR',
        }):
            response = client.post('/api/preview-map-data', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0}
            })

        # 503, not 502: the edge fabricates its own 502s, so the app must stay out of that status.
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['error_code'], 'NEARBY_LANDMARKS_UNAVAILABLE')
        self.assertIn('Places API (New) is not enabled', response.get_json()['error'])

    def test_nearest_category_landmarks_return_real_names(self):
        places = [
            {'name': 'مول حقيقي', 'types': ['shopping_mall'], 'lat': 24.01, 'lng': 46.01, 'distance_meters': 1000},
            {'name': 'جامعة حقيقية', 'types': ['university'], 'lat': 24.02, 'lng': 46.02, 'distance_meters': 2000},
            {'name': 'مستشفى حقيقي', 'types': ['hospital'], 'lat': 24.03, 'lng': 46.03, 'distance_meters': 3000},
        ]
        with patch.object(self.application_module.maps_service, 'get_nearby_landmarks', return_value={
            'success': True, 'landmarks': places
        }), patch.object(self.application_module.maps_service, 'get_drive_matrix', return_value=[
            {'distance_km': 1.0, 'distance_text': '1 كم', 'duration_min': 3},
            {'distance_km': 2.0, 'distance_text': '2 كم', 'duration_min': 5},
            {'distance_km': 3.0, 'distance_text': '3 كم', 'duration_min': 7},
        ]):
            result = self.application_module.maps_service.get_nearest_category_landmarks(24.0, 46.0)

        self.assertEqual([item['name'] for item in result], ['مول حقيقي', 'جامعة حقيقية', 'مستشفى حقيقي'])
        self.assertEqual([item['category'] for item in result], ['التسوق', 'التعليم', 'الصحة'])
        self.assertEqual(result[1]['duration_minutes'], 5)

    def test_pdf_documents_are_rendered_to_vision_images_without_text_extraction(self):
        import fitz
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), 'Visual table sample')
        pdf_data = document.tobytes()
        document.close()
        data_uri = 'data:application/pdf;base64,' + __import__('base64').b64encode(pdf_data).decode('ascii')
        parts, warnings, page_count, mode = self.application_module._prepare_document_vision_parts({
            'filename': 'scan.pdf', 'mimeType': 'application/pdf', 'fileData': data_uri
        })
        self.assertEqual(page_count, 1)
        self.assertEqual(warnings, [])
        self.assertEqual(mode, 'pdf_rendered')
        self.assertTrue(any(part.get('type') == 'image_url' for part in parts))
        self.assertFalse(any(part.get('type') == 'file' for part in parts))
        app_source = read_module_source('app.py')
        self.assertNotIn('أُرسل الملف الأصلي كحل احتياطي', app_source)
        self.assertIn('finish_reason == \'length\'', app_source)
        self.assertIn('_detect_scan_rotation', app_source)
        self.assertIn('PDF_VISION_TILE_MAX_EDGE', app_source)
        self.assertIn('extraction_diagnostics', app_source)
        # The cap is negotiated in _call_land_analysis_model: too low truncates the JSON, too high
        # is refused outright because the provider reserves max_tokens against the balance.
        self.assertIn('_call_land_analysis_model(\n', app_source)
        self.assertIn('LAND_ANALYSIS_MAX_TOKENS', app_source)

    def test_pdf_scan_orientation_adds_high_resolution_table_tiles(self):
        import base64
        import fitz
        from PIL import Image, ImageDraw

        source = Image.new('RGB', (800, 1000), 'white')
        painter = ImageDraw.Draw(source)
        for y in range(80, 900, 70):
            painter.line((40, y, 760, y), fill='black', width=2)
            painter.line((40, y + 28, 760, y + 28), fill='black', width=1)
        sideways = source.rotate(90, expand=True)
        image_buffer = io.BytesIO()
        sideways.save(image_buffer, format='PNG')
        document = fitz.open()
        page = document.new_page(width=sideways.width, height=sideways.height)
        page.insert_image(page.rect, stream=image_buffer.getvalue())
        pdf_data = document.tobytes()
        document.close()
        data_uri = 'data:application/pdf;base64,' + base64.b64encode(pdf_data).decode('ascii')

        diagnostics = {}
        parts, warnings, page_count, mode = self.application_module._prepare_document_vision_parts(
            {'filename': 'rotated-scan.pdf', 'mimeType': 'application/pdf', 'fileData': data_uri},
            budget=8 * 1024 * 1024,
            diagnostics=diagnostics,
        )

        self.assertEqual((page_count, mode), (1, 'pdf_rendered'))
        self.assertEqual(diagnostics['rotated_page_count'], 1)
        self.assertGreater(diagnostics['tile_count'], 0)
        self.assertTrue(any('تم تصحيح اتجاه' in warning for warning in warnings))
        self.assertTrue(any('قصاصة مكبرة' in part.get('text', '') for part in parts if part.get('type') == 'text'))

    def test_land_normalizer_accepts_regulation_coordinate_and_direction_aliases(self):
        result = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-2',
                'directions': [{'direction': 'الشمال', 'regulation_text': 'بطول 80 م يحده شارع'}],
                'regulation_coordinates': [{
                    'point_number': 1,
                    'الشرقيات': '511085,849',
                    'الشماليات': '2392264,840',
                }],
            }],
        })

        parcel = result['parcels'][0]
        self.assertEqual(parcel['directions']['north']['regulation_text'], 'بطول 80 م يحده شارع')
        self.assertEqual(result['survey_coordinates'][0]['eastings'], '511085,849')
        self.assertEqual(result['survey_coordinates'][0]['northings'], '2392264,840')
        self.assertEqual(result['survey_coordinates'][0]['source'], 'regulation_table')

        mixed = self.application_module._normalize_land_document_result({
            'survey_coordinates': [
                {'point': '1 (إحداثيات الموقع)', 'eastings': '511072.703', 'northings': '2392261.792'},
                {'point': '1 (إحداثيات التنظيم)', 'eastings': '511085.849', 'northings': '2392264.840'},
            ]
        })
        self.assertEqual(len(mixed['survey_coordinates']), 1)
        self.assertEqual(mixed['survey_coordinates'][0]['point'], '1')
        self.assertEqual(mixed['survey_coordinates'][0]['eastings'], '511085.849')

    def test_land_normalizer_selects_rows_under_regulation_coordinate_table(self):
        result = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-1',
                'regulation_coordinates': [
                    {'point': '1', 'eastings': '511073.703', 'northings': '2392261.792'},
                ],
                'coordinate_tables': [
                    {
                        'table_name': 'إحداثيات الموقع',
                        'rows': [{'point': '1', 'eastings': '511073.703', 'northings': '2392261.792'}],
                    },
                    {
                        'table_name': 'إحداثيات التنظيم',
                        'rows': [{'point': '1', 'eastings': '511085.849', 'northings': '2392264.840'}],
                    },
                ],
            }],
        })

        self.assertEqual(len(result['survey_coordinates']), 1)
        self.assertEqual(result['survey_coordinates'][0]['eastings'], '511085.849')
        self.assertEqual(result['survey_coordinates'][0]['northings'], '2392264.840')

        top_level_regulation = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-1',
                'survey_coordinates': [{'point': '1', 'eastings': '511073.703', 'northings': '2392261.792'}],
            }],
            'regulation_coordinates': [{
                'point': '1', 'eastings': '511085.849', 'northings': '2392264.840'
            }],
        })
        self.assertEqual(top_level_regulation['survey_coordinates'][0]['eastings'], '511085.849')

    def test_land_extraction_diagnostics_identifies_empty_tables(self):
        result = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-1',
                'directions': {'north': {'regulation_text': 'بطول 10 م يحده جار'}},
                'survey_coordinates': [],
            }],
            'conflicts': [{'field': 'survey_coordinates', 'description': 'الجدول غير مقروء'}],
        })
        diagnostics = self.application_module._build_land_extraction_diagnostics(result, [])

        self.assertEqual(diagnostics['status'], 'partial')
        self.assertEqual(diagnostics['coordinates_rows'], 0)
        self.assertEqual(diagnostics['directions_with_values'], 1)
        self.assertIn('إحداثيات التنظيم', diagnostics['missing_tables'])
        self.assertEqual(diagnostics['conflict_count'], 1)

    def test_extract_croquis_response_exposes_table_diagnostics(self):
        model_payload = {
            'parcels': [{
                'parcel_id': 'P-1',
                'survey_coordinates': [{
                    'point': '1', 'eastings': '511085.849', 'northings': '2392264.840'
                }],
                'directions': {
                    'north': {'regulation_text': 'بطول 10 م'},
                    'south': {'regulation_text': 'بطول 11 م'},
                    'east': {'regulation_text': 'بطول 12 م'},
                    'west': {'regulation_text': 'بطول 13 م'},
                },
            }],
            'conflicts': [],
        }
        provider_response = {
            'choices': [{
                'finish_reason': 'stop',
                'message': {'content': json.dumps(model_payload, ensure_ascii=False)},
            }]
        }
        with patch.object(self.application_module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(self.application_module, '_prepare_document_vision_parts', return_value=(
                    [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test', 'detail': 'high'}}],
                    [], 1, 'image_direct'
                )), \
                patch.object(self.application_module, 'search_official_regulations_evidence', return_value=(
                    {'context': '', 'documents': [], 'table_pages': []}, []
                )), \
                patch.object(self.application_module, '_call_land_analysis_model', return_value=(provider_response, 9000, '')):
            response = self.app.test_client().post('/api/extract-croquis', headers=self._headers(self.token_a), json={
                'fileData': 'data:image/png;base64,test',
                'locationAddress': 'https://www.google.com/maps/@24.0,46.0,17z',
                'locationLat': 24.0,
                'locationLng': 46.0,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        diagnostics = response.get_json()['extractedData']['extraction_diagnostics']
        self.assertEqual(diagnostics['coordinates_rows'], 1)
        self.assertEqual(diagnostics['directions_with_values'], 4)
        self.assertEqual(diagnostics['status'], 'complete')

    def test_extract_croquis_requires_resolved_google_location(self):
        response = self.app.test_client().post('/api/extract-croquis', headers=self._headers(self.token_a), json={
            'fileData': 'data:image/png;base64,test',
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['failureReason'], 'location_required')

    def test_land_analysis_pipeline_uses_verified_digest_when_zone_matches(self):
        """A recognized zoning code resolves from rules/ deterministically: the
        per-request PDF evidence stages are skipped and the digest's numbers are
        force-filled on the parcel."""
        final_payload = {
            'parcels': [{
                'parcel_id': 'P-1',
                'plot_number': '9',
                'area_sqm': 3000,
                'setbacks': 'قيمة غير موثقة من النموذج',
                'survey_coordinates': [{
                    'point': '1', 'eastings': '511085.849', 'northings': '2392264.840'
                }],
                'directions': {},
            }],
            'conflicts': [],
        }
        stage_responses = [
            {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'site_facts': {'area_sqm': 3000, 'land_use': 'سكني', 'zoning_code': 'ت ر1'}
            }, ensure_ascii=False)}}]},
            {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(final_payload, ensure_ascii=False)}}]},
        ]
        stage_responses = [(response, 9000, '') for response in stage_responses]
        with patch.object(self.application_module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(self.application_module, '_prepare_document_vision_parts', return_value=(
                    [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test', 'detail': 'high'}}],
                    [], 1, 'image_direct'
                )), \
                patch.object(self.application_module, 'search_official_regulations_evidence') as evidence_search, \
                patch.object(self.application_module, '_call_land_analysis_model', side_effect=stage_responses) as calls:
            response = self.app.test_client().post('/api/extract-croquis', headers=self._headers(self.token_a), json={
                'fileData': 'data:image/png;base64,test',
                'locationAddress': 'https://www.google.com/maps/@24.0,46.0,17z',
                'locationLat': 24.0,
                'locationLng': 46.0,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        # site_facts + final analysis only — the digest replaces evidence extraction.
        self.assertEqual(calls.call_count, 2)
        evidence_search.assert_not_called()
        final_user_content = json.dumps(calls.call_args_list[-1].args[1], ensure_ascii=False)
        self.assertIn('الشوارع التجارية الرئيسة', final_user_content)
        parcel = response.get_json()['extractedData']['parcels'][0]
        self.assertIn('ارتداد أمامي', parcel['setbacks'])
        self.assertNotIn('قيمة غير موثقة', parcel['setbacks'])

    def test_land_analysis_pipeline_falls_back_to_pdf_evidence_for_unknown_zone(self):
        """An unrecognized zoning code keeps the legacy two-file evidence path."""
        final_payload = {
            'parcels': [{
                'parcel_id': 'P-1',
                'plot_number': '9',
                'area_sqm': 3000,
                'survey_coordinates': [{
                    'point': '1', 'eastings': '511085.849', 'northings': '2392264.840'
                }],
                'directions': {},
            }],
            'conflicts': [],
        }
        stage_responses = [
            {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'site_facts': {'area_sqm': 3000, 'land_use': 'سكني', 'zoning_code': 'كود غير موثق'}
            }, ensure_ascii=False)}}]},
            {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'evidence': [{'field': 'allowed_uses_restrictions', 'value': 'سكني', 'page': 12}]
            }, ensure_ascii=False)}}]},
            {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'evidence': [{'field': 'building_ratio', 'value': '60%', 'page': 44}]
            }, ensure_ascii=False)}}]},
            {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(final_payload, ensure_ascii=False)}}]},
        ]
        stage_responses = [(response, 9000, '') for response in stage_responses]
        evidence_package = {
            'context': 'لا يُستخدم هذا الحقل في الدمج النهائي',
            'documents': [
                {'name': 'اشتراطات1.pdf', 'context': 'دليل الملف الأول', 'text_pages': [12], 'table_pages': []},
                {'name': 'اشتراطات2.pdf', 'context': 'دليل الملف الثاني', 'text_pages': [44], 'table_pages': []},
            ],
            'table_pages': [],
        }
        with patch.object(self.application_module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(self.application_module, '_prepare_document_vision_parts', return_value=(
                    [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test', 'detail': 'high'}}],
                    [], 1, 'image_direct'
                )), \
                patch.object(self.application_module, 'search_official_regulations_evidence', return_value=(
                    evidence_package, []
                )), \
                patch.object(self.application_module, '_call_land_analysis_model', side_effect=stage_responses) as calls:
            response = self.app.test_client().post('/api/extract-croquis', headers=self._headers(self.token_a), json={
                'fileData': 'data:image/png;base64,test',
                'locationAddress': 'https://www.google.com/maps/@24.0,46.0,17z',
                'locationLat': 24.0,
                'locationLng': 46.0,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(calls.call_count, 4)
        final_user_content = json.dumps(calls.call_args_list[-1].args[1], ensure_ascii=False)
        self.assertIn('اشتراطات1.pdf', final_user_content)
        self.assertIn('اشتراطات2.pdf', final_user_content)
        self.assertNotIn('لا يُستخدم هذا الحقل في الدمج النهائي', final_user_content)

    def test_health_reports_deployment_marker(self):
        marker = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        marker.write(json.dumps({'commit': '492d856c7fa', 'deployed_at': '2026-08-06T22:45:00Z', 'source': 'github'}))
        marker.close()
        self.addCleanup(lambda: os.path.exists(marker.name) and os.unlink(marker.name))
        with patch.object(self.application_module, 'DEPLOYMENT_MARKER_PATH', marker.name):
            payload = self.app.test_client().get('/health').get_json()
        self.assertEqual(payload['commit'], '492d856')
        self.assertEqual(payload['deployed_commit'], '492d856c7fa')
        self.assertEqual(payload['deployment_source'], 'github')
        self.assertIn('map_label_font', payload)

    def test_deploy_webhook_forwards_and_validates_the_expected_commit(self):
        module = self.application_module
        commit = 'a' * 40
        with patch.dict(os.environ, {'DEPLOY_WEBHOOK_SECRET': 'deploy-secret'}), \
                patch('subprocess.Popen') as popen:
            response = self.app.test_client().post(
                f'/api/deploy-webhook?secret=deploy-secret&commit={commit}')
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['expected_commit'], commit)
        self.assertEqual(popen.call_args.args[0][-1], commit)

        with patch.dict(os.environ, {'DEPLOY_WEBHOOK_SECRET': 'deploy-secret'}):
            invalid = self.app.test_client().post(
                '/api/deploy-webhook?secret=deploy-secret&commit=not-a-commit')
        self.assertEqual(invalid.status_code, 400, invalid.get_json())

        workflow = (ROOT / '.github/workflows/deploy.yml').read_text(encoding='utf-8')
        deploy_script = (ROOT / 'deploy.sh').read_text(encoding='utf-8')
        self.assertIn('&commit=${{ github.sha }}', workflow)
        # Production moved off the dead sagdemos.store host: manual deploys go to
        # PROD_BASE_URL, lab deploys go to STAGING_BASE_URL. Neither workflow may
        # reference the old host anymore.
        self.assertNotIn('sagdemos.store', workflow)
        self.assertIn('PROD_BASE_URL', workflow)
        staging_workflow = (ROOT / '.github/workflows/deploy-staging.yml').read_text(encoding='utf-8')
        self.assertIn('STAGING_BASE_URL', staging_workflow)
        self.assertIn('/api/deploy-webhook-staging', staging_workflow)
        # Lab work always ships to the lab branch, never to main.
        self.assertIn('- lab', staging_workflow)
        self.assertNotIn('sagdemos.store', staging_workflow)
        self.assertNotIn('sagdemo.site', workflow)
        self.assertNotIn('sagdemo.site', staging_workflow)
        self.assertIn('TARGET_COMMIT="${1:-}"', deploy_script)
        self.assertIn('git reset --hard "$TARGET_COMMIT"', deploy_script)
        self.assertIn('REPO_DIR="/home/landloom/workflow.git"', deploy_script)
        self.assertIn('APP_DIR="/home/landloom/proposal-generator"', deploy_script)
        start_script = (ROOT / 'start_server.sh').read_text(encoding='utf-8')
        self.assertIn('WEB_ROOT="/home/landloom/public_html"', start_script)
        self.assertIn("deploy_script = '/home/landloom/proposal-generator/deploy.sh'", read_module_source('app.py'))

    def test_fresh_database_has_meeting_columns(self):
        """Fresh initialization no longer executes multiple DDL statements incorrectly."""
        with self.app.app_context():
            conn = db.get_db()
            training_columns = {row['name'] for row in conn.execute('PRAGMA table_info(tenant_training_data)')}
            draft_columns = {row['name'] for row in conn.execute('PRAGMA table_info(project_drafts)')}
        self.assertTrue({'image_type', 'image_description'}.issubset(training_columns))
        self.assertTrue({'requested_by', 'reviewed_by', 'review_note', 'reviewed_at'}.issubset(draft_columns))

    def test_single_slide_generation_uses_tenant_logo_immediately(self):
        """A freshly generated slide must not be finalized with the system logo."""
        logo_path = f'/tenant-assets/{self.tenant_a}/logo'
        with self.app.app_context():
            db.update_branding(self.tenant_a, logo_path=logo_path)

        generated_html = (
            '<div class="slide" style="width:1280px;height:720px;position:relative;">'
            '<img src="##LOGO##">'
            '</div>'
        )
        client = self.app.test_client()
        with patch.object(self.application_module.slide_engine, 'generate_single_slide', return_value=generated_html), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images', return_value={}):
            response = client.post('/api/generate-slide-single', headers=self._headers(self.token_a), json={
                'projectData': {},
                'slidePlan': {'slides': [{'title': 'غلاف', 'type': 'cover'}]},
                'slideIndex': 0,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        html = response.get_json()['slide']['html']
        self.assertIn(logo_path + '?t=1', html)
        self.assertNotIn('/assets/logo.png', html)

    def test_single_slide_snapshot_uses_real_deck_position_for_chrome(self):
        """A single-slide snapshot must use _slideNum, not the snapshot index.

        The client sends one slide at a time with slideIndex always 0. Numbering
        the slide from that index mistook every slide for the cover, stripped
        its header/footer and never re-added them, so         whole decks came out
        without chrome.
        """
        project_data = {
            'project_name': 'المشروع',
            'financial_study_model': {
                'inputs': {'projectCost': 1000},
                'report': {'parts': [
                    {'type': 'heading', 'level': 2, 'text': 'الدراسة المالية'},
                    {'type': 'heading', 'level': 3, 'text': '1. طبيعة وحدات المشروع'},
                    {'type': 'fields', 'rows': [[f'البند {i}', f'القيمة {i}'] for i in range(1, 7)]},
                ]},
            },
        }
        plan_slide = {'title': '1. طبيعة وحدات المشروع', 'type': 'content',
                      'design_style': 'table', 'content_source': 'financial_report:2:0:6',
                      'row_count': 6}
        client = self.app.test_client()
        response = client.post('/api/generate-slide-single', headers=self._headers(self.token_a), json={
            'projectData': project_data,
            'slidePlan': {'slides': [plan_slide]},
            'images': {},
            'slideIndex': 0,
            '_slideNum': 5,
            '_totalSlides': 24,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        html = response.get_json()['slide']['html']
        self.assertIn('data-slide-header="1"', html)
        self.assertIn('data-slide-footer="1"', html)
        self.assertIn('05 — 24', html)
        self.assertIn('<table', html)

        # Backward compatibility: without _slideNum the snapshot index still numbers the slide.
        legacy = client.post('/api/generate-slide-single', headers=self._headers(self.token_a), json={
            'projectData': project_data,
            'slidePlan': {'slides': [
                {'title': 'الغلاف', 'type': 'cover'},
                dict(plan_slide, title='1. طبيعة وحدات المشروع'),
                {'title': 'الخاتمة', 'type': 'closing'},
            ]},
            'images': {},
            'slideIndex': 1,
        })
        self.assertEqual(legacy.status_code, 200, legacy.get_json())
        legacy_html = legacy.get_json()['slide']['html']
        self.assertIn('data-slide-header="1"', legacy_html)
        self.assertIn('02 — 03', legacy_html)

    def test_slide_prompt_carries_every_section_instead_of_a_truncated_dump(self):
        """A real project payload is ~230,000 characters and was cut at 4,000, so the market study,
        the executive content, the team and most of the location section never reached the model."""
        # The library is company-wide, so it is removed again: other cases assert it is empty.
        with self.app.app_context():
            entity_id = db.create_team_entity(self.tenant_a, 'شركة الاستشارات الهندسية',
                                              role='المستشار الهندسي',
                                              brief='خبرة في الأبراج الفاخرة')
            try:
                facts = self.application_module.slide_engine.build_project_facts(
                    self.FULL_PROJECT, tenant_id=self.tenant_a)
            finally:
                db.delete_team_entity(self.tenant_a, entity_id)

        for heading in ('معلومات أساسية', 'الموقع والخرائط', 'الأرض والكروكي',
                        'فريق العمل', 'دراسة السوق', 'المحتوى التنفيذي'):
            self.assertIn(heading, facts)
        for fact in ('THE VIEW', 'جدة', 'طريق الكورنيش', 'مطار الملك عبدالعزيز',
                     'ارتداد أمامي 6م', 'سكني وفندقي وتجاري', 'فور سيزونز جدة',
                     'الملخص التنفيذي المعتمد للمشروع.', 'خطر التأخير ومعالجته بجدول ملزم.',
                     'شركة الاستشارات الهندسية', 'مكتب تصميم محلي', 'فرصة جاذبة'):
            self.assertIn(fact, facts)
        # Multi-select groups are stored under internal keys; the model must not see them.
        self.assertIn('أصحاب الثروات', facts)
        self.assertNotIn('audience::', facts)
        # Noise: the previous deck, image prompts, per-field provenance, file metadata.
        for noise in ('class="slide"', 'ديك قديم', 'Cinematic wide-angle shot', 'field_sources',
                      'source_urls', 'krooki.pdf', '511085.849', 'tenantSlidesData'):
            self.assertNotIn(noise, facts)
        # A complete project fits without being cut at all.
        self.assertNotIn('[تم اختصار البيانات]', facts)

        app_source = read_module_source('app.py')
        engine_source = read_module_source('slide_engine.py')
        self.assertNotIn('project_json[:4000]', app_source)
        self.assertNotIn('project_json[:6000]', engine_source)
        self.assertIn('slide_engine.build_project_facts(project_data, g.tenant_id)', app_source)
        self.assertIn('project_json = build_project_facts(project_data, tenant_id)', engine_source)

    def test_generated_slide_request_sends_the_sections_and_not_the_previous_deck(self):
        """End to end: what the endpoint hands to the model for one slide."""
        captured = {}

        def fake_generate(system_prompt, slide, slide_num, total, branding, call_fn, **kwargs):
            captured['system_prompt'] = system_prompt
            return '<div class="slide" style="width:1280px;height:720px">ok</div>'

        client = self.app.test_client()
        with patch.object(self.application_module.slide_engine, 'generate_single_slide',
                          side_effect=fake_generate), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images',
                             return_value={}):
            response = client.post('/api/generate-slide-single', headers=self._headers(self.token_a), json={
                'projectData': self.FULL_PROJECT,
                'slidePlan': {'slides': [{'title': 'دراسة السوق', 'type': 'content'}]},
                'slideIndex': 0,
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        prompt = captured['system_prompt']
        for fact in ('THE VIEW', 'دراسة السوق', 'المحتوى التنفيذي', 'فريق العمل',
                     'فور سيزونز جدة', 'التصميم', 'شقق سكنية'):
            self.assertIn(fact, prompt)
        self.assertNotIn('ديك قديم', prompt)

        # The client must not upload the previous deck or the image state with every slide either.
        index_source = read_frontend_text()
        self.assertIn('function slimGenerationProjectData(data)', index_source)
        self.assertIn('projectData: slimGenerationProjectData(tenantProjectData)', index_source)
        for dropped in ('tenantSlidesData', 'pageDrafts', 'tenantCreativeImages', 'visual_concept'):
            self.assertIn(f"'{dropped}'", index_source.split('const GENERATION_PAYLOAD_DROPPED')[1][:900])

    def test_project_logo_is_used_next_to_the_company_logo(self):
        """An uploaded project logo was never used: the model was not told it exists, the fallback
        header carried the company logo alone, and resolve_logo_in_html() rewrote the project
        logo's src to the company logo whenever its path contained the word "logo"."""
        engine = self.application_module.slide_engine
        project_logo = '/api/project-files/proj-logo-1'
        project = {'project_name': 'THE VIEW', 'project_logo': project_logo}

        # 1. The prompt states whether a project logo exists, so "if it exists" is answerable.
        with_logo = self.application_module._get_images_info({}, project)
        self.assertIn('شعار المشروع: متوفر', with_logo)
        self.assertIn('##PROJECT_LOGO##', with_logo)
        without_logo = self.application_module._get_images_info({}, {'project_name': 'x'})
        self.assertIn('لا يوجد', without_logo)

        # 2. A content slide with no header of its own gets both logos.
        branding = {'primary_color': '#0b1f33', 'accent_color': '#0ea5e9', 'company_name': 'Landloom'}
        finished = engine.finalize_slide_html(
            '<div class="slide" style="width:1280px;height:720px"><p>محتوى</p></div>',
            'content', project, branding, slide_num=3, slide_title='الموقع', total_slides=8,
        )
        self.assertIn(project_logo, finished)
        self.assertIn('##LOGO##'.replace('##LOGO##', '/assets/logo.png'), finished)

        # 3. A project logo whose own path contains "logo" keeps its src.
        risky = '/uploads/project-files/tenant-a/logo.png'
        kept = engine.resolve_logo_in_html(
            f'<img src="{risky}" alt="project" />', None, project_logo=risky)
        self.assertIn(risky, kept)

        # 4. Cover and closing ask for both logos, and never get a header or footer.
        rules = self.application_module.build_design_rules(branding)
        self.assertIn('##PROJECT_LOGO##', rules)
        self.assertIn('الغلاف والختام', rules)
        cover = engine.finalize_slide_html(
            '<div class="slide" style="width:1280px;height:720px"><h1>THE VIEW</h1></div>',
            'cover', project, branding, slide_num=1, slide_title='الغلاف', total_slides=8,
        )
        self.assertNotIn('height:56px', cover)
        self.assertNotIn('height:36px', cover)

    def test_ai_created_slide_is_finalized_with_both_logos_and_counter(self):
        module = self.application_module
        company_logo = f'/tenant-assets/{self.tenant_a}/logo'
        project_logo = '/api/project-files/project-logo-ai'
        with self.app.app_context():
            db.update_branding(self.tenant_a, logo_path=company_logo)
            branding = db.get_branding(self.tenant_a) or {}
        response = {'choices': [{'message': {'content': json.dumps({
            'html': '<div class="slide" style="width:1280px;height:720px"><h1>محتوى جديد</h1></div>',
            'response': 'تمت الإضافة',
        }, ensure_ascii=False)}}]}
        with self.app.test_request_context(), \
                patch.object(module, 'call_zai_chat', return_value=response), \
                patch('generate_pdf_from_preview.render_slide_to_image_base64', return_value=None):
            module.g.tenant_id = self.tenant_a
            html, _message = module._designer_edit_slide(
                '<div class="slide"><h1>جديد</h1></div>', 'محتوى جديد', 'أضف شريحة', 2,
                {'project_name': 'المشروع', 'project_logo': project_logo}, None, branding,
                tenant_id=self.tenant_a, slide_type='content', total_slides=5,
            )
        self.assertIn(company_logo, html)
        self.assertIn(project_logo, html)
        self.assertIn('03 — 05', html)
        self.assertIn('data-slide-footer="1"', html)

    def test_general_slide_numbers_use_one_decimal_without_changing_exact_values_or_css(self):
        html = (
            '<style>.metric{width:1280px;opacity:0.875}</style><div class="slide">'
            '<p>القيمة 1234.55 والنسبة 18.25%</p><p>المعامل 1.85</p>'
            '<p>السنة 2027</p><p>هاتف</p><p>0500000000</p>'
            '<p>رقم الصك</p><p>12345678</p><p>خط العرض</p><p>21.687123</p>'
            '<p>الميزانية ##budget##</p></div>'
        )
        formatted = self.application_module.slide_engine.finalize_slide_html(
            html, 'content', {'budget': '9876.55'}, {'primary_color': '#123456'}, slide_num=2, total_slides=4)
        self.assertIn('1,234.6', formatted)
        self.assertIn('9,876.6', formatted)
        self.assertIn('18.3%', formatted)
        self.assertIn('1.9', formatted)
        self.assertIn('2027', formatted)
        self.assertNotIn('2,027', formatted)
        self.assertIn('0500000000', formatted)
        self.assertIn('12345678', formatted)
        self.assertIn('21.687123', formatted)
        self.assertIn('width:1280px', formatted)
        self.assertIn('opacity:0.875', formatted)
        self.assertNotIn('width:1,280px', formatted)

    def test_palette_contrast_and_logo_backgrounds_are_resolved_before_rendering(self):
        from PIL import Image, ImageDraw
        from design_templates import build_design_rules, contrast_ratio

        tenant_dir = Path(self.application_module.UPLOADS_DIR) / self.tenant_a
        tenant_dir.mkdir(parents=True, exist_ok=True)
        company_path = tenant_dir / 'logo.png'
        company_logo = Image.new('RGBA', (160, 80), (0, 0, 0, 0))
        ImageDraw.Draw(company_logo).rectangle((12, 20, 148, 60), fill=(250, 250, 250, 255))
        company_logo.save(company_path)

        project_path = tenant_dir / 'project-documents' / 'dark-project.png'
        project_path.parent.mkdir(parents=True, exist_ok=True)
        project_logo = Image.new('RGBA', (160, 80), (0, 0, 0, 0))
        ImageDraw.Draw(project_logo).rectangle((12, 20, 148, 60), fill=(10, 30, 45, 255))
        project_logo.save(project_path)

        with self.app.app_context():
            file_id = db.create_project_file(
                self.tenant_a, 'project_logo', 'dark-project.png', str(project_path),
                'image/png', project_path.stat().st_size, 'dark-project-sha')
            db.update_branding(
                self.tenant_a, logo_path=f'/tenant-assets/{self.tenant_a}/logo',
                primary_color='#005f78', secondary_color='#003d50', accent_color='#d8c49a',
                background_color='#005f78', text_color='#111111')
            branding = db.get_branding(self.tenant_a)
            project = {
                'project_name': 'THE VIEW',
                'project_logo': f'/api/project-files/{file_id}',
                'project_logo_file_id': file_id,
            }
            self.application_module._prepare_generation_logo_context(project, branding, self.tenant_a)

        self.assertEqual(branding['_logo_tone'], 'light')
        self.assertEqual(project['_project_logo_tone'], 'dark')
        info = self.application_module._get_images_info({}, project)
        self.assertIn('شعار الشركة فاتح', info)
        self.assertIn('خلفية داكنة', info)
        self.assertIn('شعار المشروع داكن', info)
        self.assertIn('خلفية بيضاء', info)

        rules = build_design_rules(branding)
        self.assertIn('4.5:1', rules)
        self.assertIn('شعار الشركة فاتح', rules)
        index_html = self.application_module.slide_engine.build_index_slide({
            'index_entries': [{'title': 'نبذة عن المشروع', 'page': 3}],
        }, 2, 5, branding, project)
        self.assertIn('background:#ffffff', index_html)
        self.assertIn('color:#111111', index_html)

        finished = self.application_module.slide_engine.finalize_slide_html(
            '<div class="slide" style="width:1280px;height:720px;background:#ffffff;color:#111111"><p>محتوى</p></div>',
            'content', project, branding, tenant_id=self.tenant_a,
            slide_num=3, slide_title='نبذة عن المشروع', total_slides=5)
        logo_tags = re.findall(r'<img\b[^>]*>', finished, re.IGNORECASE)
        company_tag = next(tag for tag in logo_tags if f'/tenant-assets/{self.tenant_a}/logo' in tag)
        project_tag = next(tag for tag in logo_tags if f'/api/project-files/{file_id}' in tag)
        self.assertIn('background:#005f78', company_tag)
        self.assertIn('background:#ffffff', project_tag)

    def test_single_slide_accepts_any_valid_slide_class_attribute(self):
        engine = self.application_module.slide_engine

        def generated(*_args, **_kwargs):
            return {'choices': [{'message': {'content': (
                "<div class='slide generated' style='width:1280px;height:720px;"
                "background:#ffffff;color:#111827'><p>محتوى</p></div>"
            )}}]}

        html = engine.generate_single_slide(
            'system', {'title': 'نبذة', 'type': 'content'}, 3, 8,
            {'primary_color': '#0b1f33'}, generated, project_data={})
        self.assertEqual(len(self.application_module.extract_slide_elements(html)), 1)
        self.assertIn('class="slide"', html)
        self.assertIn('height:56px', html)

    def test_content_surface_is_normalized_to_light_and_logos_stay_independent(self):
        """A dark/model-authored content root is repaired to the light report canvas."""
        engine = self.application_module.slide_engine
        branding = {
            'primary_color': '#122a67',
            'secondary_color': '#0f1f4d',
            'accent_color': '#d8b36a',
        }
        html = engine.finalize_slide_html(
            '<div class="slide" style="width:1280px;height:720px;background:#122a67;color:#ffffff;">'
            '<div style="background:#ffffff;color:#122a67;">محتوى SOL</div></div>',
            'content', {'project_name': 'المشروع'}, branding,
            slide_num=4, slide_title='ملخص الموقع', total_slides=9,
        )
        header = re.search(r'<header\b[^>]*>', html, flags=re.IGNORECASE).group(0)
        footer = re.search(r'<footer\b[^>]*>', html, flags=re.IGNORECASE).group(0)
        self.assertIn('background:#ffffff', header)
        self.assertIn('background:#122a67', footer)
        self.assertIn('background:#ffffff', re.search(r'<div class="slide"[^>]*>', html, flags=re.IGNORECASE).group(0))
        self.assertNotIn('data-slide-surface="dark"', html)

        old = (
            '<div class="slide" style="width:1280px;height:720px;background:#122a67;color:#fff;">'
            '<header class="slide-header" data-slide-header="1" style="background:#ffffff;color:#122a67;">قديم</header>'
            '<div>المحتوى</div>'
            '<footer class="slide-footer" data-slide-footer="1" style="background:#122a67;">قديم</footer>'
            '</div>'
        )
        renumbered = engine.renumber_presentation_slides(
            [{'type': 'content', 'title': 'ملخص الموقع', 'html': old}],
            branding=branding, project_data={'project_name': 'المشروع'},
        )[0]['html']
        self.assertIn('background:#ffffff', re.search(r'<header\b[^>]*>', renumbered, flags=re.IGNORECASE).group(0))
        self.assertIn('background:#ffffff', re.search(r'<div class="slide"[^>]*>', renumbered, flags=re.IGNORECASE).group(0))
        self.assertNotIn('قديم', renumbered)

    def test_legacy_dark_surface_is_repaired_without_touching_logo_contrast(self):
        engine = self.application_module.slide_engine
        branding = {
            'primary_color': '#122a67',
            'secondary_color': '#0f1f4d',
            'accent_color': '#d8b36a',
        }
        source = (
            '<div class="slide" style="width:1280px;height:720px;background:#122a67;color:#ffffff;">'
            '<div style="background:transparent;border:1px solid rgba(255,255,255,.22);color:#f8fafc;padding:24px;">'
            '<h1 style="color:#f8fafc;">العنوان</h1>'
            '<table><tr style="background:rgba(255,255,255,.08);"><td style="color:#f8fafc;">القيمة</td></tr></table>'
            '</div></div>'
        )
        finished = engine.finalize_slide_html(
            source, 'content', {'project_name': 'المشروع'}, branding,
            slide_num=4, slide_title='ملخص الموقع', total_slides=9,
        )
        content_region = re.search(r'</header>([\s\S]*?)<footer\b', finished, flags=re.IGNORECASE).group(1)
        self.assertNotIn('data-slide-surface="dark"', finished)
        self.assertIn('background:#ffffff', re.search(r'<div class="slide"[^>]*>', finished, flags=re.IGNORECASE).group(0))
        self.assertIn('background:#ffffff', content_region)
        self.assertIn('color:#1e293b', content_region)

        renumbered = engine.renumber_presentation_slides(
            [{'type': 'content', 'title': 'ملخص الموقع', 'html': source}],
            branding=branding, project_data={'project_name': 'المشروع'},
        )[0]['html']
        content_region = re.search(r'</header>([\s\S]*?)<footer\b', renumbered, flags=re.IGNORECASE).group(1)
        self.assertIn('background:#ffffff', content_region)
        self.assertNotIn('data-slide-surface="dark"', renumbered)

    def test_single_slide_retries_severely_unreadable_text(self):
        engine = self.application_module.slide_engine
        responses = iter([
            "<div class='slide' style='width:1280px;height:720px;background:#005f78;color:#111111'><p>نص غير مقروء</p></div>",
            "<div class='slide' style='width:1280px;height:720px;background:#005f78;color:#ffffff'><p>نص مقروء</p></div>",
        ])
        prompts = []

        def generated(_system, user_message, **_kwargs):
            prompts.append(user_message)
            return {'choices': [{'message': {'content': next(responses)}}]}

        html = engine.generate_single_slide(
            'system', {'title': 'نبذة', 'type': 'content'}, 3, 8,
            {'primary_color': '#005f78'}, generated, project_data={})
        self.assertIn('background:#ffffff', re.search(r'<div class="slide"[^>]*>', html, flags=re.IGNORECASE).group(0))
        # Post-processing repairs unreadable text deterministically, so a dark
        # page with dark text ships readable after a single call instead of
        # paying for a redesign.
        self.assertEqual(len(prompts), 1)
        self.assertFalse(engine.slide_contrast_issues(html))
        self.assertTrue(engine.slide_contrast_issues(
            "<div class='slide' style='background:#005f78'><p>لون المتصفح الافتراضي</p></div>"))

    def test_style_block_table_text_is_repaired_without_retry(self):
        """A <style> rule like ``td{color:#fff}`` used to ship white-on-white:
        the audit only read inline styles, so the slide passed as-is. The
        cascade-aware repair now patches the effective color in place."""
        engine = self.application_module.slide_engine
        source = (
            '<div class="slide" style="width:1280px;height:720px;background:#ffffff;color:#1e293b;">'
            '<style>.tbl{width:100%}.tbl th{background:#005f78;color:#fff}.tbl td{color:#fff}</style>'
            '<table class="tbl"><tr><th>البند</th></tr><tr><td>أرض</td></tr></table>'
            '</div>'
        )
        repaired = engine.postprocess_slide(
            source, 'content', slide_num=5, slide_title='جدول', total_slides=30)
        self.assertFalse(engine.slide_contrast_issues(repaired))
        self.assertIn('color:#1e293b!important', repaired)
        # The dark header rule stays intact: white on #005f78 is correct.
        self.assertIn('background:#005f78;color:#fff', repaired)

        calls = []

        def generated(_system, user_message, **_kwargs):
            calls.append(user_message)
            return {'choices': [{'message': {'content': source}}]}

        html = engine.generate_single_slide(
            'system', {'title': 'جدول', 'type': 'content'}, 5, 30,
            {'primary_color': '#005f78'}, generated, project_data={})
        self.assertEqual(len(calls), 1, 'a repairable contrast defect must not consume a paid retry')
        self.assertFalse(engine.slide_contrast_issues(html))

    def test_text_over_image_is_not_repaired(self):
        """Captions positioned over a photo keep their authored color: the
        surface under them is an image, so neither the audit nor the repair may
        treat them as text on the white canvas."""
        engine = self.application_module.slide_engine
        source = (
            '<div class="slide" style="width:1280px;height:720px;background:#ffffff;color:#1e293b;">'
            '<div style="position:relative;height:300px;"><img src="/uploads/x.png">'
            '<div style="position:absolute;bottom:10px;right:10px;color:#fff">تسمية على الصورة</div></div>'
            '<p style="color:#fff">نص على الأبيض</p>'
            '</div>'
        )
        repaired = engine.postprocess_slide(
            source, 'content', slide_num=6, slide_title='صور', total_slides=30)
        self.assertRegex(
            repaired,
            r'<div style="position:absolute[^"]*color:#fff[^"]*"[^>]*>تسمية على الصورة')
        self.assertIn('color:#1e293b!important', repaired)
        self.assertFalse(engine.slide_contrast_issues(repaired))

    def test_section_dividers_are_built_from_one_fixed_layout(self):
        """Every divider is the same layout over the approved main image with only the text
        changing, so it is rendered in code: identical on every divider and no model call."""
        engine = self.application_module.slide_engine
        branding = {'primary_color': '#0b1f33', 'accent_color': '#22b6e8', 'company_name': 'Landloom'}
        project = {'project_name': 'THE VIEW', 'project_logo': '/api/project-files/logo-1'}
        slide = {
            'title': 'فريق التطوير والتصميم', 'type': 'section_divider',
            'title_en': 'Development & Design Team',
            'subtitle': 'شراكة تجمع خبرة التطوير العقاري السعودي مع التصميم والهندسة العالمية.',
        }

        # No model call: call_glm_fn must not be touched for a divider.
        def fail_if_called(*args, **kwargs):
            raise AssertionError('a section divider must not call the model')

        html = engine.generate_single_slide(
            'system', slide, 6, 60, branding, fail_if_called, project_data=project)

        self.assertEqual(html.count('class="slide"'), 1)
        self.assertIn('فريق التطوير والتصميم', html)
        self.assertNotIn('DEVELOPMENT & DESIGN TEAM', html)
        self.assertNotIn('شراكة تجمع خبرة التطوير العقاري', html)
        self.assertIn('url(##IMAGE_COVER##)', html)               # the approved main image
        self.assertIn('06 — 60', html)                            # slide number, as in the reference
        self.assertIn('THE VIEW', html)
        self.assertIn('##PROJECT_LOGO##', html)                   # both logos
        self.assertIn('##LOGO##', html)
        self.assertIn('#22b6e8', html)                            # tenant accent, not a fixed colour

        # Finalizing must not add the content header/footer to it.
        finished = engine.finalize_slide_html(
            html, 'section_divider', project, branding,
            creative_images={'cover': '/uploads/creative/cover.jpg'},
            slide_num=6, slide_title=slide['title'], total_slides=60,
        )
        self.assertNotIn('height:56px', finished)
        self.assertNotIn('height:36px', finished)
        self.assertIn('/uploads/creative/cover.jpg', finished)
        self.assertIn('/api/project-files/logo-1', finished)

        # A divider with no English line or description still renders.
        bare = engine.generate_single_slide(
            'system', {'title': 'مكونات المشروع', 'type': 'section_divider'},
            15, 60, branding, fail_if_called, project_data=project)
        self.assertIn('مكونات المشروع', bare)
        self.assertIn('15 — 60', bare)

        # Saved cover slides can place logos before their full-bleed image. Export still discovers
        # the real image and rebuilds every divider with that exact URL.
        repaired = engine.renumber_presentation_slides([
            {
                'title': 'الغلاف', 'type': 'cover',
                'html': '<div class="slide"><img src="/uploads/company-logo.png">'
                        '<img src="/uploads/creative/approved-cover.jpg"></div>',
            },
            {
                'title': 'نبذة عن المشروع', 'type': 'section_divider', 'section_key': 'overview',
                'html': '<div class="slide" style="background-image:none">نبذة عن المشروع</div>',
            },
        ], branding=branding, project_data={'project_name': 'THE VIEW'}, creative_images={})
        self.assertIn('/uploads/creative/approved-cover.jpg', repaired[1]['html'])
        self.assertNotIn('background-image:none', repaired[1]['html'])

        # The planner knows the type, and the validator accepts it.
        prompt = engine.build_slide_plan_prompt({'project_name': 'THE VIEW'}, branding)
        self.assertIn('section_divider', prompt)
        self.assertIn('بلا وصف أو ترجمة', prompt)
        plan = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            {'title': 'مكونات المشروع', 'type': 'section_divider'},
            {'title': 'المكونات', 'type': 'content', 'bullets': ['1', '2', '3']},
            {'title': 'الختام', 'type': 'closing'},
        ]}
        _valid, issues = engine.validate_slide_plan(plan, {'min_slides': 1, 'max_slides': 60})
        self.assertFalse([issue for issue in issues if 'section_divider' in issue], issues)

    def test_market_and_swot_dividers_keep_cover_and_footer_layout(self):
        engine = self.application_module.slide_engine
        branding = {
            'primary_color': '#0b1f33', 'accent_color': '#22b6e8',
            'company_name': 'Landloom',
        }
        project = {
            'project_name': 'THE VIEW',
            'tenantCreativeImages': {'cover': '/uploads/creative/approved-cover.jpg'},
        }

        for section_key, title, source in (
            ('market', 'تحليل السوق', None),
            ('swot_risks', 'تحليل SWOT وتحليل المخاطر', 'market_study_data.swot'),
        ):
            html = engine.finalize_slide_html(
                engine.build_section_divider_slide(
                    {'title': title, 'type': 'section_divider'}, 19, 72,
                    branding, project,
                ),
                'section_divider', project, branding,
                creative_images=project['tenantCreativeImages'],
                slide_num=19, slide_title=title, total_slides=72,
                content_source=source,
            )
            self.assertIn('/uploads/creative/approved-cover.jpg', html)
            self.assertIn('bottom:34px;left:48px', html)
            self.assertIn('data-slide-counter="1"', html)
            self.assertIn('19 — 72', html)

            # A legacy content-only snapshot with the divider title is repaired
            # to the same fixed divider before it reaches the preview/export.
            repaired = engine.renumber_presentation_slides([
                {
                    'title': title, 'type': 'content', 'section_key': section_key,
                    'html': '<div class="slide"><div style="position:absolute;top:220px;left:48px">19 — 72</div></div>',
                }
            ], branding=branding, project_data=project)
            self.assertEqual(repaired[0]['type'], 'section_divider')
            self.assertIn('/uploads/creative/approved-cover.jpg', repaired[0]['html'])
            self.assertIn('bottom:34px;left:48px', repaired[0]['html'])
            self.assertNotIn('top:220px', repaired[0]['html'])
            self.assertIn('01 — 01', repaired[0]['html'])

    def test_final_deck_plan_has_canonical_sections_page_index_and_exact_media(self):
        engine = self.application_module.slide_engine
        financial = {
            'inputs': {'projectCost': 1200000},
            'dynamicRows': {'components': [{'name': 'فندق', 'units': 20}]},
            'tables': {
                'componentsTable': [{'المكون': 'فندق', 'الوحدات': '20'}],
                'revenueTable': [
                    {'السنة': '2027', 'الإيراد': '1,200,000'},
                    {'السنة': '2028', 'الإيراد': '1,500,000'},
                ],
                'costTable': [
                    {'البند': 'تكلفة الأرض', 'القيمة': '500,000'},
                    {'البند': 'تكلفة البناء والتطوير', 'القيمة': '700,000'},
                ],
            },
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': 'مكونات المشروع'},
                {'type': 'table', 'headers': ['المكون', 'الوحدات'], 'rows': [['فندق', '20']]},
                {'type': 'heading', 'level': 2, 'text': 'النتائج المالية'},
                {'type': 'fields', 'rows': [['ROI', '18%'], ['إجمالي التكلفة', '1,200,000']]},
                {'type': 'heading', 'level': 2, 'text': 'الإيرادات'},
                {'type': 'table', 'headers': ['السنة', 'الإيراد'],
                 'rows': [['2027', '1,200,000'], ['2028', '1,500,000']]},
                {'type': 'heading', 'level': 2, 'text': 'هيكل التكاليف والاستثمار'},
                {'type': 'table', 'headers': ['البند', 'القيمة'],
                 'rows': [['تكلفة الأرض', '500,000'], ['تكلفة البناء والتطوير', '700,000']]},
            ]},
        }
        project = {
            'project_name': 'المشروع', 'project_idea': 'نبذة المشروع',
            'contact_email': 'info@example.test', 'contact_phone': '0110000000',
            'land_and_building_summary': 'ملخص الأرض النهائي',
            'site_analysis': 'ملخص الموقع النهائي',
            'timeline_table_data': json.dumps([
                {'name': 'التصميم', 'year': '2027', 'quarter': 'Q1', 'duration': '3', 'notes': ''},
                {'name': 'التنفيذ', 'year': '2027', 'quarter': 'Q2', 'duration': '9',
                 'notes': 'بعد الاعتماد'},
            ], ensure_ascii=False),
            'financial_study_model': financial,
            'market_study_data': json.dumps({
                'one_block_summary': 'ملخص السوق النهائي',
                'swot': {'strengths': 'موقع قوي', 'weaknesses': 'تكلفة مرتفعة'},
            }, ensure_ascii=False),
            'executive_content': json.dumps({
                'risks': 'خطر التأخير ومعالجته بجدول ملزم.',
                'summary': 'الملخص التنفيذي المعتمد.',
            }, ensure_ascii=False),
            'team_selection': json.dumps({'excluded': [], 'roles': {}, 'local': [{
                'localId': 'local-1', 'name': 'المكتب الهندسي', 'role': 'التصميم',
                'brief': 'خبرة متخصصة', 'logoFileId': 'team-logo-1',
            }]}, ensure_ascii=False),
        }
        images = {
            'moodboard': ['/uploads/creative/right.jpg', '/uploads/creative/left.jpg'],
            'moodboard_meta': [
                {'label': 'الواجهة اليمنى', 'caption': 'التكوين الحجري'},
                {'label': 'الواجهة الشمالية', 'caption': 'المدخل الرئيسي'},
            ],
            'land_photos': [{
                'url': '/uploads/creative/land.jpg', 'name': 'واجهة الأرض',
                'description': 'الحد الشمالي للأرض',
            }],
            'plans': ['/uploads/creative/plan.jpg'],
            'plan_meta': [{'title': 'مخطط الدور الأرضي', 'description': 'توزيع الدور الأرضي'}],
            'interior_components': [{
                'name': 'الفندق', 'images': [{
                    'url': '/uploads/creative/lobby.jpg', 'label': 'الاستقبال',
                    'caption': 'منطقة الاستقبال الرئيسية',
                }],
            }],
            'team_members': [{'name': 'المكتب الهندسي', 'role': 'التصميم',
                              'logo': '/uploads/creative/team.jpg'}],
        }
        raw = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            {'title': 'تحليل السوق', 'type': 'content', 'section_key': 'market',
             'bullets': ['أ', 'ب', 'ج']},
            {'title': 'المشروع والفكرة', 'type': 'content', 'section_key': 'overview',
             'bullets': ['أ', 'ب', 'ج']},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}
        plan = engine.normalize_presentation_plan(raw, project, images)
        dividers = [slide for slide in plan['slides'] if slide.get('type') == 'section_divider']
        expected_sections = list(engine.PRESENTATION_SECTION_ORDER[:-1])
        self.assertEqual([slide['section_key'] for slide in dividers], expected_sections)
        self.assertTrue(all('subtitle' not in slide and 'title_en' not in slide for slide in dividers))

        entries = plan['slides'][1]['index_entries']
        self.assertEqual([entry['section_key'] for entry in entries], expected_sections + ['closing'])
        for entry in entries:
            self.assertEqual(plan['slides'][entry['page'] - 1].get('section_key'), entry['section_key'])
        index_html = engine.build_index_slide(plan['slides'][1], 2, len(plan['slides']), {}, project)
        self.assertIn('محتويات العرض', index_html)
        self.assertIn('نبذة عن المشروع', index_html)
        self.assertIn('الخاتمة', index_html)
        self.assertNotIn('محور', index_html)

        divider_html = engine.build_section_divider_slide({
            'title': 'تحليل الأرض', 'subtitle': 'وصف يجب ألا يظهر', 'title_en': 'LAND',
        }, 3, len(plan['slides']), {}, project)
        self.assertNotIn('وصف يجب ألا يظهر', divider_html)
        self.assertNotIn('LAND', divider_html)

        overview = next(slide for slide in plan['slides'] if slide.get('content_source') == 'project_overview')
        self.assertEqual(overview['image_tokens'], [])
        exterior_tokens = [token for slide in plan['slides'] if slide.get('section_key') == 'exterior'
                           for token in (slide.get('image_tokens') or [])]
        self.assertEqual(exterior_tokens, ['##MOODBOARD_IMAGE_1##', '##MOODBOARD_IMAGE_2##'])
        land = [slide for slide in plan['slides'] if slide.get('section_key') == 'land'
                and slide.get('type') == 'content']
        self.assertEqual(land[0]['image_tokens'], ['##LAND_PHOTO_1##'])
        self.assertEqual(land[0]['bullets'], ['الحد الشمالي للأرض'])
        self.assertEqual(land[-1]['content_source'], 'land_and_building_summary')
        self.assertTrue(any(slide.get('image_tokens') == ['##PLAN_IMAGE_1##'] for slide in plan['slides']))
        self.assertTrue(any(slide.get('image_tokens') == ['##INTERIOR_COMP_1_IMG_1##']
                            for slide in plan['slides']))
        self.assertTrue(any(slide.get('image_tokens') == ['##TEAM_LOGO_1##'] for slide in plan['slides']))
        self.assertEqual(sum(slide.get('section_key') == 'components' and slide.get('type') == 'content'
                             for slide in plan['slides']), 1)
        component_slide = next(slide for slide in plan['slides']
                               if slide.get('section_key') == 'components' and slide.get('type') == 'content')
        self.assertTrue(component_slide['content_source'].startswith('project_components:'))
        financial_slides = [slide for slide in plan['slides'] if slide.get('section_key') == 'financial'
                            and slide.get('type') == 'content']
        self.assertTrue(financial_slides)
        self.assertTrue(all(slide.get('content_source') == 'financial_indicators'
                            or str(slide.get('content_source')).startswith(('financial_report:', 'financial_summary:'))
                            for slide in financial_slides))
        self.assertTrue(any(slide.get('design_style') == 'chart' and slide.get('chart_type')
                            for slide in financial_slides))
        revenue_slide = next(slide for slide in financial_slides
                             if str(slide.get('content_source')).startswith('financial_report:5:')
                             or any(str(src).startswith('financial_report:5:') for src in (slide.get('content_sources') or [])))
        source_note = engine._slide_source_data_note(revenue_slide, project)
        self.assertIn('1,500,000', source_note)
        self.assertEqual(financial_slides[-1].get('content_source'), 'financial_indicators')
        financial_note = engine._financial_data_note(project)
        self.assertIn('نفس محتوى تقرير PDF', financial_note)
        self.assertIn('ROI', financial_note)
        self.assertIn('1,500,000', financial_note)
        self.assertIn('فواصل الآلاف', financial_note)
        facts = engine.build_project_facts(project)
        self.assertIn('بيانات التواصل المعتمدة للخاتمة', facts)
        self.assertIn('info@example.test', facts)
        closing_message = engine.build_slide_user_msg(
            plan['slides'][-1], len(plan['slides']), len(plan['slides']), {}, project)
        self.assertIn('فرصة واعدة بشروط', closing_message)
        cleaned_closing = engine.postprocess_slide(
            '<div class="slide"><p>فرصة واعدة بشروط</p><p>شكراً لكم</p></div>',
            'closing', slide_num=len(plan['slides']), total_slides=len(plan['slides']),
            slide_title='الخاتمة',
        )
        self.assertNotIn('فرصة واعدة بشروط', cleaned_closing)
        self.assertIn('شكراً لكم', cleaned_closing)

        gated = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'المخططات', 'type': 'content', 'section_key': 'plans'},
            {'title': 'الدراسة المالية', 'type': 'content', 'section_key': 'financial'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, {'project_name': 'مشروع بلا وسائط'}, {})
        self.assertNotIn('plans', [slide.get('section_key') for slide in gated['slides']])
        self.assertNotIn('financial', [slide.get('section_key') for slide in gated['slides']])

    def test_canonical_plan_assigns_each_media_asset_to_one_slide(self):
        engine = self.application_module.slide_engine
        images = {
            'moodboard': ['/uploads/m1.jpg', '/uploads/m2.jpg'],
            'moodboard_meta': [{'label': 'يمين'}, {'label': 'شمال'}],
            'land_photos': [
                {'url': '/uploads/l1.jpg', 'name': 'شمال'},
                {'url': '/uploads/l2.jpg', 'name': 'جنوب'},
            ],
            'plans': ['/uploads/p1.jpg', '/uploads/p2.jpg', '/uploads/p3.jpg'],
            'plan_meta': [{}, {}, {}],
            'interior_components': [{'name': 'الفندق', 'images': [
                {'url': '/uploads/i1.jpg', 'label': 'الاستقبال'},
                {'url': '/uploads/i2.jpg', 'label': 'الغرف'},
            ]}],
        }
        raw = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            {'title': 'نبذة', 'type': 'content', 'section_key': 'overview', 'bullets': ['أ', 'ب', 'ج']},
            {'title': 'الخارجي مجمع', 'type': 'content', 'section_key': 'exterior',
             'image_tokens': ['##PROJECT_IMAGE_1##', '##PROJECT_IMAGE_2##']},
            {'title': 'الخارجي 1', 'type': 'content', 'section_key': 'exterior',
             'image_tokens': ['##MOODBOARD_IMAGE_1##']},
            {'title': 'الأرض مجمعة', 'type': 'content', 'section_key': 'land',
             'image_tokens': ['##LAND_IMAGE_1##', '##LAND_IMAGE_2##']},
            {'title': 'الأرض شمال', 'type': 'content', 'section_key': 'land',
             'image_tokens': ['##LAND_PHOTO_1##']},
            {'title': 'المخططات', 'type': 'content', 'section_key': 'plans',
             'image_tokens': ['##2D_PLAN_1##', '##2D_PLAN_2##', '##2D_PLAN_3##']},
            {'title': 'المخطط الأول', 'type': 'content', 'section_key': 'plans',
             'image_tokens': ['##PLAN_IMAGE_1##']},
            {'title': 'الداخلي', 'type': 'content', 'section_key': 'interior',
             'image_tokens': ['##INTERIOR_C1_IMAGE_1##', '##INTERIOR_1_2##']},
            {'title': 'الاستقبال', 'type': 'content', 'section_key': 'interior',
             'image_tokens': ['##INTERIOR_COMP_1_IMG_1##']},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}
        plan = engine.normalize_presentation_plan(raw, {'project_name': 'المشروع'}, images)
        used = []
        for slide in plan['slides']:
            used.extend(slide.get('image_tokens') or [])
        self.assertEqual(len(used), len(set(used)), used)
        self.assertTrue(all(token.startswith('##') and token.endswith('##') for token in used))
        self.assertNotIn('##PROJECT_IMAGE_1##', used)
        self.assertNotIn('##2D_PLAN_1##', used)
        self.assertNotIn('##LAND_IMAGE_1##', used)
        self.assertNotIn('##INTERIOR_1_2##', used)

    def test_media_assets_are_reserved_for_their_dedicated_sections(self):
        engine = self.application_module.slide_engine
        images = {
            'moodboard': [f'/uploads/exterior-{index}.jpg' for index in range(1, 6)],
            'moodboard_meta': [{} for _ in range(5)],
            'plans': [f'/uploads/plan-{index}.jpg' for index in range(1, 4)],
            'plan_meta': [{} for _ in range(3)],
            'interior_components': [{'name': 'الفندق', 'images': [
                {'url': f'/uploads/interior-{index}.jpg'} for index in range(1, 15)
            ]}],
        }
        raw = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'نبذة', 'type': 'content', 'section_key': 'overview',
             'image_tokens': ['##MOODBOARD_IMAGE_1##', '##MOODBOARD_IMAGE_2##'], 'bullets': ['أ', 'ب', 'ج']},
            {'title': 'تحليل السوق', 'type': 'content', 'section_key': 'market',
             'image_tokens': ['##PLAN_IMAGE_1##'], 'bullets': ['أ', 'ب', 'ج']},
            {'title': 'المكونات', 'type': 'content', 'section_key': 'components',
             'image_tokens': ['##INTERIOR_COMP_1_IMG_1##'], 'bullets': ['أ', 'ب', 'ج']},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}
        plan = engine.normalize_presentation_plan(raw, {'project_name': 'المشروع'}, images)
        owners = {
            '##MOODBOARD_IMAGE_': 'exterior',
            '##PLAN_IMAGE_': 'plans',
            '##INTERIOR_COMP_': 'interior',
        }
        counts = {prefix: 0 for prefix in owners}
        for slide in plan['slides']:
            for token in slide.get('image_tokens') or []:
                for prefix, section in owners.items():
                    if token.startswith(prefix):
                        self.assertEqual(slide.get('section_key'), section, (token, slide))
                        counts[prefix] += 1
        self.assertEqual(counts, {
            '##MOODBOARD_IMAGE_': 5,
            '##PLAN_IMAGE_': 3,
            '##INTERIOR_COMP_': 14,
        })
        self.assertEqual([len(slide.get('image_tokens') or []) for slide in plan['slides']
                          if slide.get('section_key') == 'exterior' and slide.get('type') == 'content'], [2, 2, 1])
        self.assertEqual([len(slide.get('image_tokens') or []) for slide in plan['slides']
                          if slide.get('section_key') == 'plans' and slide.get('type') == 'content'], [1, 1, 1])
        self.assertEqual([len(slide.get('image_tokens') or []) for slide in plan['slides']
                          if slide.get('section_key') == 'interior' and slide.get('type') == 'content'], [2] * 7)
        visual_media_slides = [slide for slide in plan['slides']
                               if slide.get('section_key') in {'plans', 'exterior', 'interior'}
                               and slide.get('type') == 'content']
        self.assertTrue(visual_media_slides)
        self.assertTrue(all(slide.get('media_only') is True and slide.get('bullets') == []
                            for slide in visual_media_slides))
        content_slides = [slide for slide in plan['slides'] if slide.get('type') == 'content']
        self.assertTrue(any(slide.get('image_tokens') for slide in content_slides))
        self.assertTrue(any(not slide.get('image_tokens') for slide in content_slides))
        self.assertIn('لا تضف صورة إلى شرائح النص أو الجداول بلا حاجة',
                      engine.build_slide_plan_prompt({'project_name': 'المشروع'}, {}, images))

    def test_image_slide_retries_when_a_planned_image_is_missing(self):
        engine = self.application_module.slide_engine
        responses = iter([
            '<div class="slide" style="background:#fff;color:#111"><img src="##LAND_PHOTO_1##"></div>',
            '<div class="slide" style="background:#fff;color:#111"><img src="##LAND_PHOTO_1##"><img src="##LAND_PHOTO_2##"></div>',
        ])
        prompts = []

        def generated(_system, user_message, **_kwargs):
            prompts.append(user_message)
            return {'choices': [{'message': {'content': next(responses)}}]}

        html = engine.generate_single_slide(
            'system', {'title': 'صور الأرض', 'type': 'content', 'section_key': 'land',
                       'design_style': 'image',
                       'image_tokens': ['##LAND_PHOTO_1##', '##LAND_PHOTO_2##']},
            3, 5, {'primary_color': '#123456'}, generated, project_data={})
        self.assertIn('##LAND_PHOTO_2##', html)
        self.assertEqual(len(prompts), 2)
        self.assertIn('##LAND_PHOTO_2##', prompts[1])

    def test_visual_concept_drops_stale_text_and_table_slides(self):
        engine = self.application_module.slide_engine
        images = {
            'moodboard': ['/uploads/exterior-1.jpg', '/uploads/exterior-2.jpg'],
            'plans': ['/uploads/plan-1.jpg'],
            'interior_components': [{'name': 'الفندق', 'images': [
                {'url': '/uploads/interior-1.jpg'},
            ]}],
        }
        raw = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            {'title': 'المخطط العام والمسطح الأفقي للمشروع', 'type': 'content',
             'bullets': ['ملخص قديم', 'بيانات جدولية قديمة']},
            {'title': 'ملخص التصور الخارجي', 'type': 'content',
             'section_key': 'exterior', 'bullets': ['نص قديم']},
            {'title': 'ملخص التصور الداخلي', 'type': 'content',
             'section_key': 'interior', 'bullets': ['نص قديم']},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}

        plan = engine.normalize_presentation_plan(raw, {'project_name': 'المشروع'}, images)
        visual = [slide for slide in plan['slides']
                  if slide.get('section_key') in {'plans', 'exterior', 'interior'}
                  and slide.get('type') == 'content']

        self.assertEqual(len([slide for slide in visual if slide.get('section_key') == 'plans']), 1)
        self.assertTrue(visual)
        self.assertTrue(all(slide.get('media_only') is True
                            and slide.get('image_tokens')
                            and slide.get('bullets') == []
                            for slide in visual))
        self.assertNotIn('المخطط العام والمسطح الأفقي للمشروع',
                         [slide.get('title') for slide in plan['slides']])
        self.assertNotIn('ملخص التصور الخارجي',
                         [slide.get('title') for slide in plan['slides']])
        self.assertNotIn('ملخص التصور الداخلي',
                         [slide.get('title') for slide in plan['slides']])

    def test_visual_concept_media_slides_are_deterministic_and_text_free(self):
        engine = self.application_module.slide_engine
        for section_key, source, tokens in (
            ('plans', 'plan_image:1', ['##PLAN_IMAGE_1##']),
            ('exterior', 'exterior_images_group:1:2', ['##MOODBOARD_IMAGE_1##', '##MOODBOARD_IMAGE_2##']),
            ('interior', 'interior_images_group:1:1:2', ['##INTERIOR_COMP_1_IMG_1##', '##INTERIOR_COMP_1_IMG_2##']),
        ):
            calls = []

            def must_not_call(*_args, **_kwargs):
                calls.append(True)
                raise AssertionError('visual concept media must not call the text model')

            html = engine.generate_single_slide(
                'system', {'title': 'وسائط', 'type': 'content', 'section_key': section_key,
                           'content_source': source, 'design_style': 'image',
                           'image_tokens': tokens},
                3, 8, {'primary_color': '#123456'}, must_not_call, project_data={})
            self.assertIn('data-visual-media-only="1"', html)
            for token in tokens:
                self.assertIn(token, html)
            self.assertNotIn('<h2', html.lower())
            self.assertIn('padding:72px 34px 48px', html)
            self.assertIn(
                'max-width:100%!important;max-height:100%!important;object-fit:contain!important',
                html,
            )
            self.assertFalse(calls)

    def test_visual_concept_saved_state_restores_all_unapproved_media(self):
        project = {
            'financial_study_model': {'dynamicRows': {'components': [
                {'id': 'hotel', 'name': 'الفندق'},
            ]}},
            'visual_concept': {
                'slots': {
                    'right': {'imageUrl': '/uploads/exterior-right.jpg'},
                    'left': {'imageUrl': '/uploads/exterior-left.jpg'},
                    'top': {'imageUrl': '/uploads/exterior-top.jpg'},
                    'back': {'imageUrl': '/uploads/exterior-back.jpg'},
                    'interior_hotel::1': {'imageUrl': '/uploads/interior-1.jpg', 'status': 'review'},
                    'interior_hotel::2': {'imageUrl': '/uploads/interior-2.jpg', 'status': 'review'},
                    'interior_hotel::3': {'imageUrl': '/uploads/interior-3.jpg', 'status': 'review'},
                },
                'plans2d': [{'fileId': 'plan-file-1', 'fileName': 'plan-one.pdf'}],
            },
        }
        with patch.object(self.application_module, '_generation_project_image_url', return_value='/uploads/plan-one.png'):
            restored = self.application_module._augment_generation_images({
                'moodboard': ['available'],
                'interior_components': [{'name': 'الفندق', 'images': [{'url': 'available'}]}],
                'plans': ['available'],
            }, project, self.tenant_a)
        self.assertEqual(len(restored['moodboard']), 4)
        self.assertEqual(sum(len(item['images']) for item in restored['interior_components']), 3)
        self.assertEqual(len(restored['plans']), 1)
        self.assertEqual(restored['plans'][0]['url'], '/uploads/plan-one.png')

    def test_compact_media_markers_keep_each_uploaded_image_distinct(self):
        engine = self.application_module.slide_engine
        plan = engine.normalize_presentation_plan({
            'slides': [
                {'title': 'الغلاف', 'type': 'cover'},
                {'title': 'الفهرس', 'type': 'index'},
                {'title': 'التصور البصري', 'type': 'content', 'section_key': 'plans'},
                {'title': 'الخاتمة', 'type': 'closing'},
            ]
        }, {'project_name': 'المشروع'}, {
            'plans': ['available', 'available', 'available'],
        })
        plan_slides = [slide for slide in plan['slides']
                       if slide.get('section_key') == 'plans' and slide.get('type') == 'content']
        self.assertEqual([slide.get('image_tokens') for slide in plan_slides], [
            ['##PLAN_IMAGE_1##'], ['##PLAN_IMAGE_2##'], ['##PLAN_IMAGE_3##']
        ])

    def test_unplanned_creative_image_tokens_are_removed_from_text_slides(self):
        engine = self.application_module.slide_engine
        html = engine.generate_single_slide(
            'system', {'title': 'نبذة عن المشروع', 'type': 'content',
                       'section_key': 'overview', 'image_tokens': []},
            3, 8, {'primary_color': '#123456'},
            lambda *_args, **_kwargs: {
                'choices': [{'message': {'content': (
                    '<div class="slide" style="background:#fff;color:#111">'
                    '<img src="##MOODBOARD_IMAGE_1##"><p>محتوى</p></div>'
                )}}]
            },
            project_data={},
        )
        self.assertNotIn('MOODBOARD_IMAGE_1', html)
        self.assertIn('محتوى', html)

    def test_maps_are_removed_from_every_non_location_slide(self):
        engine = self.application_module.slide_engine
        rogue = (
            '<div class="slide" style="background:#fff;color:#111">'
            '<img src="##MAP_OVERVIEW##">'
            '<img src="##MAP_OVERVIEW_SATELLITE_EDITABLE##">'
            '<div style="background-image:url(/uploads/maps/overview.png);height:300px"></div>'
            '<p>بيانات الجدول الزمني</p></div>'
        )
        cleaned = engine.finalize_slide_html(
            rogue, 'content', {'project_name': 'المشروع'},
            {'primary_color': '#123456'},
            map_placeholders={'##MAP_OVERVIEW##': '/uploads/maps/overview.png'},
            slide_num=7, slide_title='الجدول الزمني للمشروع', total_slides=20,
            content_source='timeline',
        )
        self.assertNotIn('MAP_', cleaned)
        self.assertNotIn('/uploads/maps/', cleaned)
        self.assertIn('بيانات الجدول الزمني', cleaned)

    def test_land_analysis_slide_can_show_requested_overview_map(self):
        engine = self.application_module.slide_engine
        html = (
            '<div class="slide" style="background:#fff;color:#111">'
            '<div style="background-image:url(##MAP_OVERVIEW##);height:300px"></div>'
            '<p>بيانات تحليل الأرض</p></div>'
        )
        cleaned = engine.finalize_slide_html(
            html, 'content', {'project_name': 'المشروع'},
            {'primary_color': '#123456'},
            map_placeholders={'##MAP_OVERVIEW##': '/uploads/maps/overview.png'},
            slide_num=8, slide_title='تحليل الأرض', total_slides=20,
            content_source='land_and_building_summary',
        )
        self.assertIn('/uploads/maps/overview.png', cleaned)
        self.assertNotIn('##MAP_OVERVIEW##', cleaned)
        self.assertIn('بيانات تحليل الأرض', cleaned)

    def test_renumbering_does_not_delete_a_saved_map_url(self):
        engine = self.application_module.slide_engine
        html = (
            '<div class="slide">'
            '<img src="/uploads/maps/overview.png" alt="خريطة محفوظة">'
            '<img src="##MAP_ACCESS##" alt="خريطة غير محلولة">'
            '<p>نبذة عن المشروع</p></div>'
        )
        renumbered = engine.renumber_presentation_slides([
            {'title': 'نبذة عن المشروع', 'type': 'content', 'section_key': 'overview', 'html': html},
        ], branding={'primary_color': '#123456'}, project_data={'project_name': 'المشروع'})

        # Opening/re-numbering a saved presentation must not silently erase a map
        # that was already resolved and persisted. An unresolved token is still
        # removed because it has no image to render.
        self.assertIn('/uploads/maps/overview.png', renumbered[0]['html'])
        self.assertNotIn('##MAP_ACCESS##', renumbered[0]['html'])

    def test_legacy_full_renderer_cannot_restore_map_in_visual_slide(self):
        engine = self.application_module.slide_engine

        def generated(_system, _user_message, **_kwargs):
            return {'choices': [{'message': {'content': (
                '<div class="slide" style="background:#fff;color:#111">'
                '<img src="##MAP_OVERVIEW_SATELLITE_EDITABLE##">'
                '<p>التصور الداخلي</p></div>'
            )}}]}

        html = engine.generate_all_slides(
            {'slides': [{'title': 'التصور الداخلي', 'type': 'content',
                         'section_key': 'interior', 'content_source': 'interior_image:1:1'}]},
            {'project_name': 'المشروع'}, {'primary_color': '#123456'}, {}, generated,
            map_placeholders={'##MAP_OVERVIEW_SATELLITE_EDITABLE##': '/uploads/maps/overview.png'},
        )[0]
        self.assertNotIn('MAP_', html)
        self.assertNotIn('/uploads/maps/', html)
        self.assertIn('التصور الداخلي', html)
