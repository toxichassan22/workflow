import copy
import json
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

import auth
import db
import best_use_regulations as regulations
import best_use_workflow as workflow
from tests.visual_plan.test_best_use import project_fixture


def row_fixture(basis, footprint=2000, built=8000):
    return {'name': 'شقق', 'useType': 'residential', 'units': 1, 'unitArea': built,
            'builtArea': built, 'grossArea': built, 'revenueArea': built * 0.9,
            'nonRevenueArea': built * 0.1, 'footprintArea': footprint, 'investmentModel': 'sale',
            'reason': 'ملاءمة الموقع.', 'areaReason': 'داخل الحدود المعتمدة.',
            'revenueAreaBasis': 'افتراض تخطيطي لصافي المساحة مع تخصيص الخدمات.', 'allowedUseBasis': basis}


class ExplorationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'exploration.db')
        import app as application
        cls.application, cls.app = application, application.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant('Explore test', 'explore@example.test', 'hash', 'explore-test')
            cls.other = db.create_tenant('Other test', 'explore-other@example.test', 'hash', 'explore-other-test')
        cls.token = auth.create_token(cls.tenant, 'explore@example.test', user_id=None, user_role='company_admin')
        cls.other_token = auth.create_token(cls.other, 'explore-other@example.test', user_id=None, user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def setUp(self):
        self.project = project_fixture()
        self.project.update(draftId=uuid.uuid4().hex, plot_number_croquis='42', zoning_code='س ع',
                            best_use_mode='explore', best_use_explore_data={'mode': 'explore'},
                            project_type='["فندقي"]', project_idea='فكرة العميل السرية',
                            market_study_data={'summary': 'دراسة السوق السرية'}, land_use_status='غير مسموح')
        self.pages = [{'documentId': 'croquis-1', 'page': 1, 'kind': 'parcel',
                       'text': 'رقم القطعة: 42\nكود التنظيم: س ع\nالاستخدامات المسموحة: سكني\n'}]
        self.regulations = regulations.extract(self.project, self.pages)
        self.basis = self.regulations['evidence'][0]
        self.scan = {'table': [{'use': 'residential', 'salePerSqm': None, 'rentPerSqmYear': None, 'metrics': {}}],
                     'observations': [], 'status': 'partial', 'searchRan': True, 'city': 'جدة', 'district': 'حي الاختبار'}
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer ' + self.token}
        self.statuses = {'land_croquis': 'approved', 'location': 'approved', 'section-market-study': 'draft',
                         'section-financial-calc': 'approved', 'section-executive-content': 'approved'}
        with self.app.app_context():
            self.draft_id = db.save_project_draft(self.tenant, 'tenant-admin:' + self.tenant,
                self.project, self.statuses, draft_id=self.project['draftId'])
        for name, value in (('_require_billing_balance', None), ('_best_use_documents_backed', True),
                            ('_best_use_regulation_pages', self.pages), ('_best_use_scan_prices', self.scan),
                            ('_best_use_map_references', []), ('_bill_tenant_unbilled_usage_async', None),
                            ('_best_use_price_page', None)):
            mocked = patch.object(self.application, name, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        for name in ('call_text_chat', 'call_openrouter_chat'):
            mocked = patch.object(self.application, name, side_effect=AssertionError('Unmocked provider call'))
            mocked.start()
            self.addCleanup(mocked.stop)

    def draft(self):
        with self.app.app_context():
            return db.get_project_draft_by_id(self.tenant, self.draft_id)

    def post(self, action, **payload):
        return self.client.post('/api/best-use/explore/' + action, headers=self.headers,
            json=dict(draftId=self.draft_id, expectedRevision=self.draft()['revision'], **payload))

    def provider(self, payload):
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(payload, ensure_ascii=False)}}]}

    def concepts(self):
        raw = {'concepts': [{'name': 'مفهوم سكني', 'summary': 'توصية تخطيطية.', 'siteFit': 'موقع قريب من الخدمات.',
                            'revenueBasis': 'لا توجد أسعار كافية للمقارنة.', 'uses': ['residential'],
                            'components': [row_fixture(self.basis)]}]}
        with patch.object(self.application, 'call_text_chat', return_value=self.provider(raw)) as provider:
            response = self.post('concepts')
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['explore'], provider

    def select(self, state):
        return self.post('concepts/select', artifactId=state['concepts']['id'],
                         contentHash=state['concepts']['contentHash'], conceptId=state['concepts']['items'][0]['id'])

    def land(self):
        state, _ = self.concepts()
        self.assertEqual(self.select(state).status_code, 200)
        raw = {'title': 'توزيع الأرض', 'rationale': 'الحصص من حدود الأرض.',
               'setbackExplanation': 'ضمن التغطية والارتدادات.', 'components': [row_fixture(self.basis, built=2000)]}
        with patch.object(self.application, 'call_text_chat', return_value=self.provider(raw)):
            response = self.post('generate', stage='land')
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['explore']

    def test_request_fields_overlay_only_the_explore_source_fields(self):
        raw = {'concepts': [{'name': 'مفهوم سكني', 'summary': 'توصية تخطيطية.', 'siteFit': 'موقع قريب من الخدمات.',
                            'revenueBasis': 'لا توجد أسعار كافية للمقارنة.', 'uses': ['residential'],
                            'components': [row_fixture(self.basis)]}]}
        with patch.object(self.application, 'call_text_chat', return_value=self.provider(raw)):
            response = self.post('concepts', fields={'city': 'أبها', 'project_name': 'تجاوز غير مسموح'})
        self.assertEqual(response.status_code, 200, response.get_json())
        saved = self.draft()
        self.assertEqual(saved['draft_data']['city'], 'أبها')
        self.assertEqual(saved['draft_data']['project_name'], self.project['project_name'])

    def floors(self):
        state = self.land()
        row = row_fixture(self.basis)
        row['landComponentId'] = state['landDistribution']['components'][0]['id']
        row['floorAllocations'] = [{'floor': index, 'area': 2000} for index in range(1, 5)]
        raw = {'title': 'توزيع الأدوار', 'rationale': 'تخصيص داخل الحصة الأرضية.',
               'setbackExplanation': 'ضمن الأدوار والمعامل.', 'components': [row]}
        with patch.object(self.application, 'call_text_chat', return_value=self.provider(raw)):
            response = self.post('generate', stage='floors')
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['explore']

    def decide(self, state, name, decision='approved', **extra):
        artifact = state[name]
        payload = dict(artifact=name, artifactId=artifact['id'], contentHash=artifact['contentHash'],
                       inputHash=artifact['inputHash'], decision=decision)
        payload.update(extra)
        return self.post('decision', **payload)

    def test_no_project_idea_market_or_calculator_input_enters_exploration(self):
        state, provider = self.concepts()
        prompt = provider.call_args.args[1]
        for forbidden in ('فكرة العميل السرية', 'دراسة السوق السرية', 'project_type', 'project_idea',
                          'financial_study_model', 'unitRevenueMode', 'land_documents_analysis'):
            self.assertNotIn(forbidden, prompt)
        self.assertEqual(state['regulations']['permittedUses'], ['residential'])
        self.assertIsNone(state['concepts']['items'][0]['revenuePotential']['value'])
        self.assertEqual(self.draft()['draft_data']['financial_study_model'], self.project['financial_study_model'])

    def test_next_stages_need_valid_data_not_prior_approvals(self):
        state = self.floors()
        for name in ('priceScan', 'concepts', 'landDistribution', 'floorDistribution'):
            self.assertFalse(state[name]['approved'])
        self.assertEqual(self.draft()['draft_data']['financial_study_model'], self.project['financial_study_model'])

    def test_selection_is_not_an_approval(self):
        state, _ = self.concepts()
        response = self.select(state)
        self.assertEqual(response.status_code, 200)
        selected = response.get_json()['explore']
        self.assertTrue(selected['selectedConceptId'])
        self.assertFalse(selected['concepts']['approved'])
        self.assertFalse(selected['priceScan']['approved'])

    def test_only_floor_approval_applies_and_section_requires_every_artifact(self):
        state = self.floors()
        before = self.draft()['draft_data']['financial_study_model']
        floor_approval = self.decide(state, 'floorDistribution')
        self.assertEqual(floor_approval.status_code, 200, floor_approval.get_json())
        self.assertTrue(floor_approval.get_json()['componentsApplied'])
        model = self.draft()['draft_data']['financial_study_model']
        self.assertEqual(model['inputs']['builtUpAreaAbove'], 8000)
        self.assertEqual(model['inputs']['basementArea'], 0)
        self.assertEqual(model['dynamicRows']['cost'], before['dynamicRows']['cost'])
        self.assertEqual(self.draft()['section_statuses']['section-financial-calc'], 'draft')
        refused = self.client.post('/api/project-draft/section-status', headers=self.headers,
            json={'draftId': self.draft_id, 'sectionKey': 'section-best-use', 'sectionStatus': 'approved'})
        self.assertEqual(refused.status_code, 400, refused.get_json())
        self.assertEqual(refused.get_json()['error_code'], 'BEST_USE_APPROVAL_REQUIRED')
        revision = self.draft()['revision']
        self.assertEqual(self.decide(state, 'floorDistribution').status_code, 200)
        self.assertEqual(self.draft()['revision'], revision)
        for name in ('priceScan', 'concepts', 'landDistribution'):
            response = self.decide(self.draft()['draft_data']['best_use_explore_data'], name)
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertFalse(response.get_json()['componentsApplied'])
        approved = self.client.post('/api/project-draft/section-status', headers=self.headers,
            json={'draftId': self.draft_id, 'sectionKey': 'section-best-use', 'sectionStatus': 'approved'})
        self.assertEqual(approved.status_code, 200, approved.get_json())

    def test_general_draft_save_cannot_forge_exploration_or_its_mode(self):
        state, _ = self.concepts()
        data = copy.deepcopy(self.draft()['draft_data'])
        data['best_use_mode'] = 'guided'
        data['best_use_explore_data']['concepts'].update(approved=True, items=[])
        response = self.client.post('/api/project-draft', headers=self.headers, json={'draftData': data})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.draft()['draft_data']['best_use_explore_data'], state)
        self.assertEqual(self.draft()['draft_data']['best_use_mode'], 'explore')

    def test_basic_market_and_guided_state_changes_do_not_invalidate_exploration(self):
        state, _ = self.concepts()
        data = copy.deepcopy(self.draft()['draft_data'])
        data.update(project_type='["تجاري"]', project_idea='فكرة أخرى', market_study_data={'summary': 'سوق آخر'},
                    best_use_data={'id': 'forged-guided', 'approved': True})
        self.client.post('/api/project-draft', headers=self.headers, json={'draftData': data})
        self.assertEqual(self.draft()['draft_data']['best_use_explore_data'], state)
        self.assertTrue(workflow.current(self.draft()['draft_data'], 'concepts'))

    def test_land_change_invalidates_all_artifacts_and_their_approvals(self):
        self.floors()
        data = copy.deepcopy(self.draft()['draft_data'])
        data['approved_floor_area_ratio'] = 3
        response = self.client.post('/api/project-draft', headers=self.headers, json={'draftData': data})
        self.assertEqual(response.status_code, 200, response.get_json())
        state = self.draft()['draft_data']['best_use_explore_data']
        self.assertTrue(all(state[name]['inputsChanged'] for name in workflow.ARTIFACTS))
        response = self.decide(state, 'floorDistribution')
        self.assertEqual(response.status_code, 409)

    def test_wrong_artifact_hash_foreign_draft_and_wrong_mode_are_refused(self):
        state, _ = self.concepts()
        response = self.decide(state, 'concepts', contentHash='wrong')
        self.assertEqual(response.status_code, 409)
        response = self.client.post('/api/best-use/explore/concepts', headers={'Authorization': 'Bearer ' + self.other_token},
                                    json={'draftId': self.draft_id})
        self.assertEqual(response.status_code, 404)
        response = self.client.post('/api/best-use/generate', headers=self.headers, json={'draftId': self.draft_id})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'BEST_USE_WRONG_MODE')

    def test_mode_switch_keeps_both_histories_and_existing_financial_components(self):
        self.floors()
        before = self.draft()
        response = self.client.post('/api/best-use/mode', headers=self.headers, json={'draftId': self.draft_id,
                                    'mode': 'guided', 'expectedRevision': before['revision']})
        self.assertEqual(response.status_code, 200, response.get_json())
        after = self.draft()['draft_data']
        self.assertEqual(after['best_use_mode'], 'guided')
        self.assertEqual(after['financial_study_model'], before['draft_data']['financial_study_model'])
        self.assertFalse(after['best_use_explore_data']['floorDistribution'].get('inputsChanged', False))
        self.assertTrue(after['best_use_explore_data']['concepts']['items'])

    def test_a_job_cannot_write_over_a_racing_save(self):
        def provider(*args, **kwargs):
            draft = self.draft()
            project = dict(draft['draft_data'], project_name='اسم أحدث')
            db.save_project_draft(self.tenant, draft['user_id'], project,
                                  draft_id=self.draft_id, expected_revision=draft['revision'])
            return self.provider({'concepts': [{'name': 'سكني', 'summary': 'توصية.', 'siteFit': 'موقع.',
                'revenueBasis': 'نقص الأسعار.', 'uses': ['residential'], 'components': [row_fixture(self.basis)]}]})
        with patch.object(self.application, 'call_text_chat', side_effect=provider):
            response = self.post('concepts')
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(self.draft()['draft_data']['project_name'], 'اسم أحدث')
        self.assertNotIn('concepts', self.draft()['draft_data']['best_use_explore_data'])

    def test_all_flow_state_is_excluded_from_deck_hashes_and_copies(self):
        before = db.draft_generation_input_hash(self.project)
        project = copy.deepcopy(self.project)
        project['best_use_explore_data'] = {'concepts': {'id': 'x'}}
        project['best_use_explore_chat'] = {'land': [{'role': 'user', 'content': 'سؤال'}]}
        self.assertEqual(db.draft_generation_input_hash(project), before)
        copied = db.sanitize_copied_draft_data(project)
        self.assertNotIn('best_use_explore_data', copied)
        self.assertNotIn('best_use_explore_chat', copied)
        self.assertNotIn('best_use_mode', copied)


if __name__ == '__main__':
    unittest.main()
