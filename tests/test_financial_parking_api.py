import copy
import json
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

import auth
import db
import financial_parking
import test_financial_parking as parking_fixtures


class FinancialParkingApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'parking.db')
        import app as application
        cls.application = application
        cls.app = application.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant('Parking test', 'parking@example.test', 'hash', 'parking-test')
            cls.other_tenant = db.create_tenant('Other test', 'other@example.test', 'hash', 'parking-other')
        cls.token = auth.create_token(cls.tenant, 'parking@example.test', user_id=None,
                                      user_name='Parking test', user_role='company_admin')
        cls.other_token = auth.create_token(cls.other_tenant, 'other@example.test', user_id=None,
                                            user_name='Other test', user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def setUp(self):
        fixture = parking_fixtures.FinancialParkingTests()
        fixture.setUp()
        self.project = copy.deepcopy(fixture.project)
        self.rules = copy.deepcopy(fixture.rules)
        self.project['project_name'] = 'مشروع المواقف'
        self.project['draftId'] = uuid.uuid4().hex
        self.project['financial_study_model']['inputs'].update(
            unitRevenueMode='nonRevenue', developmentYears=1)
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer ' + self.token}
        response = self.client.post('/api/project-draft', headers=self.headers, json={
            'draftData': self.project, 'sectionStatuses': {'section-financial-calc': 'draft'}, 'status': 'draft'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.draft_id = response.get_json()['draftId']
        self.balance_guard = patch.object(self.application, '_require_billing_balance', return_value=None)
        self.balance_guard.start()
        self.addCleanup(self.balance_guard.stop)
        self.regulations = patch.object(self.application, '_visual_concept_plan_regulation_facts', return_value={})
        self.regulations.start()
        self.addCleanup(self.regulations.stop)
        self.billing_settlement = patch.object(self.application, '_bill_tenant_unbilled_usage_async')
        self.billing_settlement.start()
        self.addCleanup(self.billing_settlement.stop)

    def draft(self):
        with self.app.app_context():
            return db.get_project_draft_by_id(self.tenant, self.draft_id)

    def suggest(self, **body):
        payload = {'draftId': self.draft_id, 'expectedRevision': self.draft()['revision'], **body}
        with patch.object(self.application, 'call_text_chat', return_value={
                'choices': [{'message': {'content': json.dumps(self.rules, ensure_ascii=False)}}]}) as provider:
            response = self.client.post('/api/financial-study/parking/suggest', headers=self.headers, json=payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json(), provider

    def approve(self, plan, approved=True):
        return self.client.post('/api/financial-study/parking/approval', headers=self.headers, json={
            'draftId': self.draft_id, 'planId': plan['id'], 'approved': approved,
            'expectedRevision': self.draft()['revision']})

    def test_suggestion_uses_scoped_saved_inputs_and_is_not_applied_implicitly(self):
        response, provider = self.suggest(projectData={'regulatory_constraints': 'موقف لكل 1 م²'})
        plan = response['financialModel']['parkingPlan']
        self.assertEqual(plan['requiredSpaces'], 130)
        self.assertFalse(plan['approved'])
        self.assertEqual(len(response['financialModel']['dynamicRows']['components']), 2)
        self.assertEqual(response['financialModel']['inputs']['basementArea'], 600)
        self.assertEqual(provider.call_args.kwargs['usage_ctx']['draft_id'], self.draft_id)
        self.assertEqual(provider.call_args.kwargs['usage_ctx']['tenant_id'], self.tenant)
        self.assertNotIn('موقف لكل 1 م²', provider.call_args.args[1])

    def test_approval_applies_exact_counts_and_keeps_a_single_generated_set(self):
        response, _ = self.suggest()
        plan = response['financialModel']['parkingPlan']
        approved = self.approve(plan)
        self.assertEqual(approved.status_code, 200, approved.get_json())
        model = approved.get_json()['financialModel']
        parking = [row for row in model['dynamicRows']['components'] if row.get('parkingPlanId')]
        self.assertEqual(sum(row['units'] for row in parking), 130)
        self.assertTrue(model['parkingPlan']['approved'])
        again = self.approve(plan)
        self.assertEqual(again.status_code, 200, again.get_json())
        self.assertEqual(again.get_json()['financialModel']['dynamicRows']['components'], model['dynamicRows']['components'])
        self.assertIsNone(financial_parking.parking_plan_error(self.draft()['draft_data']))

    def test_all_section_approval_paths_refuse_a_pending_parking_artifact(self):
        self.suggest()
        requests = [
            ('/api/project-draft/section-status', {'sectionKey': 'section-financial-calc', 'sectionStatus': 'approved'}),
            ('/api/project-draft/section-status', {'sectionStatuses': {'section-financial-calc': 'approved'}}),
            ('/api/project-draft/section-version', {'sectionKey': 'section-financial-calc'}),
        ]
        for url, body in requests:
            with self.subTest(url=url, body=body):
                response = self.client.post(url, headers=self.headers, json={'draftId': self.draft_id, **body})
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertEqual(response.get_json()['error_code'], 'PARKING_APPROVAL_REQUIRED')

    def test_plain_save_cannot_forge_the_generated_content_approval(self):
        response, _ = self.suggest()
        model = response['financialModel']
        model['parkingPlan']['approved'] = True
        model['parkingPlan']['requiredSpaces'] = 1
        payload = copy.deepcopy(self.draft()['draft_data'])
        payload['financial_study_model'] = model
        saved = self.client.post('/api/project-draft', headers=self.headers, json={
            'draftData': payload, 'sectionStatuses': {'section-financial-calc': 'approved'}})
        self.assertEqual(saved.status_code, 200, saved.get_json())
        stored = self.draft()
        plan = stored['draft_data']['financial_study_model']['parkingPlan']
        self.assertFalse(plan['approved'])
        self.assertEqual(plan['requiredSpaces'], 130)
        self.assertNotEqual(stored['section_statuses'].get('section-financial-calc'), 'approved')

    def test_program_drift_refuses_the_old_proposal_and_demotes_approvals(self):
        response, _ = self.suggest()
        plan = response['financialModel']['parkingPlan']
        self.assertEqual(self.approve(plan).status_code, 200)
        with self.app.app_context():
            db.update_draft_section_status_by_id(self.tenant, self.draft_id, {
                'section-financial-calc': 'approved', 'section-visual-concept': 'approved'})
        payload = copy.deepcopy(self.draft()['draft_data'])
        payload['financial_study_model']['dynamicRows']['components'][0]['units'] = 120
        saved = self.client.post('/api/project-draft', headers=self.headers, json={'draftData': payload})
        self.assertEqual(saved.status_code, 200, saved.get_json())
        draft = self.draft()
        self.assertFalse(draft['draft_data']['financial_study_model']['parkingPlan']['approved'])
        self.assertEqual(draft['section_statuses']['section-financial-calc'], 'draft')
        self.assertEqual(draft['section_statuses']['section-visual-concept'], 'draft')
        refused = self.approve(plan)
        self.assertEqual(refused.status_code, 409, refused.get_json())
        self.assertEqual(refused.get_json()['error_code'], 'PARKING_INPUTS_CHANGED')

    def test_unapproval_removes_only_generated_rows_and_releases_extra_basement_area(self):
        response, _ = self.suggest()
        plan = response['financialModel']['parkingPlan']
        self.approve(plan)
        response = self.approve(plan, approved=False)
        self.assertEqual(response.status_code, 200, response.get_json())
        model = response.get_json()['financialModel']
        self.assertFalse(model['parkingPlan']['approved'])
        self.assertEqual(model['inputs']['basementArea'], 600)
        self.assertEqual(len(model['dynamicRows']['components']), 2)

    def test_provider_conflict_notes_warn_the_approver_without_blocking(self):
        self.rules['missing'] = ['تعارض موثق بين القيد الحالي والجدول في معدل الشقق.']
        response, _ = self.suggest()
        plan = response['financialModel']['parkingPlan']
        self.assertTrue(plan['canApply'])
        self.assertIn('تعارض موثق بين القيد الحالي والجدول في معدل الشقق.', plan['warnings'])
        self.assertEqual(self.approve(plan).status_code, 200)

    def test_provider_error_never_leaves_an_empty_or_approved_proposal(self):
        with patch.object(self.application, 'call_text_chat', side_effect=RuntimeError('provider failed')):
            response = self.client.post('/api/financial-study/parking/suggest', headers=self.headers,
                                        json={'draftId': self.draft_id})
        self.assertEqual(response.status_code, 503, response.get_json())
        self.assertNotIn('parkingPlan', self.draft()['draft_data']['financial_study_model'])

    def test_foreign_draft_is_not_read_and_never_calls_the_provider(self):
        with patch.object(self.application, 'call_text_chat') as provider:
            response = self.client.post('/api/financial-study/parking/suggest',
                                        headers={'Authorization': 'Bearer ' + self.other_token},
                                        json={'draftId': self.draft_id})
        self.assertEqual(response.status_code, 404)
        provider.assert_not_called()

    def test_hidden_financial_or_land_sections_are_enforced(self):
        for section in ('section-financial-calc', 'land_croquis'):
            with self.subTest(section=section), patch.object(self.application, '_hidden_field_sections', return_value={section}), \
                    patch.object(self.application, 'call_text_chat') as provider:
                response = self.client.post('/api/financial-study/parking/suggest', headers=self.headers,
                                            json={'draftId': self.draft_id})
                self.assertEqual(response.status_code, 403, response.get_json())
                provider.assert_not_called()

    def test_provider_response_cannot_overwrite_a_racing_draft_save(self):
        def generate(*args, **kwargs):
            draft = db.get_project_draft_by_id(self.tenant, self.draft_id)
            data = dict(draft['draft_data'], project_name='اسم أحدث')
            db.save_project_draft(self.tenant, draft['user_id'], data,
                                  draft_id=self.draft_id, expected_revision=draft['revision'])
            return {'choices': [{'message': {'content': json.dumps(self.rules, ensure_ascii=False)}}]}
        with patch.object(self.application, 'call_text_chat', side_effect=generate):
            response = self.client.post('/api/financial-study/parking/suggest', headers=self.headers,
                                        json={'draftId': self.draft_id})
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(self.draft()['draft_data']['project_name'], 'اسم أحدث')
        self.assertNotIn('parkingPlan', self.draft()['draft_data']['financial_study_model'])

    def test_financial_validation_requires_the_artifact_before_export(self):
        response, _ = self.suggest()
        model = response['financialModel']
        validation = self.client.post('/api/financial-study/validate', headers=self.headers,
                                      json={'financialModel': model, 'draftId': self.draft_id})
        self.assertFalse(validation.get_json()['success'])
        self.assertTrue(any(row['field'] == 'financialParkingPanel' for row in validation.get_json()['validation']))
        approved = self.approve(model['parkingPlan']).get_json()
        validation = self.client.post('/api/financial-study/validate', headers=self.headers,
                                      json={'financialModel': approved['financialModel'], 'draftId': self.draft_id})
        self.assertTrue(validation.get_json()['success'], validation.get_json())

    def test_transient_export_payload_cannot_forge_a_server_approval(self):
        response, _ = self.suggest()
        plan = response['financialModel']['parkingPlan']
        plan['approved'] = True
        forged = financial_parking.apply_parking_plan(response['financialModel'], plan)
        validation = self.client.post('/api/financial-study/validate', headers=self.headers,
                                      json={'financialModel': forged, 'draftId': self.draft_id})
        self.assertFalse(validation.get_json()['success'])

    def test_a_partial_save_preserves_the_server_owned_proposal(self):
        self.suggest()
        payload = copy.deepcopy(self.draft()['draft_data'])
        payload.pop('financial_study_model')
        saved = self.client.post('/api/project-draft', headers=self.headers, json={'draftData': payload})
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertIn('parkingPlan', self.draft()['draft_data']['financial_study_model'])

    def test_approval_retry_does_not_change_the_revision_or_demote_visuals_again(self):
        response, _ = self.suggest()
        plan = response['financialModel']['parkingPlan']
        self.approve(plan)
        before = self.draft()
        self.approve(plan)
        self.assertEqual(self.draft()['revision'], before['revision'])
        self.assertEqual(self.draft()['draft_data']['financial_study_model']['parkingPlan']['approvedAt'],
                         before['draft_data']['financial_study_model']['parkingPlan']['approvedAt'])

    def test_discard_removes_the_proposal_and_only_its_generated_rows(self):
        response, _ = self.suggest()
        plan = response['financialModel']['parkingPlan']
        self.approve(plan)
        discarded = self.client.post('/api/financial-study/parking/discard', headers=self.headers,
                                      json={'draftId': self.draft_id, 'planId': plan['id'],
                                            'expectedRevision': self.draft()['revision']})
        self.assertEqual(discarded.status_code, 200, discarded.get_json())
        model = discarded.get_json()['financialModel']
        self.assertNotIn('parkingPlan', model)
        self.assertEqual(len(model['dynamicRows']['components']), 2)
        self.assertEqual(model['inputs']['basementArea'], 600)

    def test_copy_does_not_inherit_parking_approval(self):
        response, _ = self.suggest()
        self.approve(response['financialModel']['parkingPlan'])
        copied = db.sanitize_copied_draft_data(self.draft()['draft_data'])
        self.assertFalse(copied['financial_study_model']['parkingPlan']['approved'])

    def test_approval_invalidates_visuals_without_discarding_their_images(self):
        payload = copy.deepcopy(self.draft()['draft_data'])
        payload['visual_concept'] = {
            'slots': {'cover': {'imageUrl': '/uploads/saved.png', 'approvedImageUrl': '/uploads/saved.png', 'status': 'approved'}},
            'plansWorkflow': {'planContext': {'components': []}, 'promptReady': True,
                              'prompts': {'site': 'old', 'uses': 'old', 'massing': 'old'},
                              'distribution': {'rows': [{'component': 'شقق سكنية'}], 'approved': True}},
        }
        self.client.post('/api/project-draft', headers=self.headers, json={'draftData': payload})
        response, _ = self.suggest()
        approved = self.approve(response['financialModel']['parkingPlan']).get_json()
        concept = approved['visualConcept']
        self.assertEqual(concept['slots']['cover']['imageUrl'], '/uploads/saved.png')
        self.assertEqual(concept['slots']['cover']['approvedImageUrl'], '')
        self.assertIsNone(concept['plansWorkflow']['planContext'])
        self.assertFalse(concept['plansWorkflow']['distribution']['approved'])
        rows = concept['plansWorkflow']['distribution']['rows']
        self.assertEqual(sum(row.get('units_per_floor', 0) for row in rows if 'مواقف' in row['component']), 130)


if __name__ == '__main__':
    unittest.main()
