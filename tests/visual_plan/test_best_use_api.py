import copy
import json
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

import auth
import db
from tests.visual_plan.test_best_use import project_fixture, proposal_fixture


class BestUseApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'best-use.db')
        import app as application
        cls.application = application
        cls.app = application.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant('Best Use test', 'bestuse@example.test', 'hash', 'bestuse-test')
            cls.other_tenant = db.create_tenant('Other test', 'bestuse-other@example.test', 'hash', 'bestuse-other')
        cls.token = auth.create_token(cls.tenant, 'bestuse@example.test', user_id=None,
                                      user_name='Best Use test', user_role='company_admin')
        cls.other_token = auth.create_token(cls.other_tenant, 'bestuse-other@example.test', user_id=None,
                                            user_name='Other test', user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def setUp(self):
        self.project = project_fixture()
        self.project['draftId'] = uuid.uuid4().hex
        self.raw = proposal_fixture()
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer ' + self.token}
        self.statuses = {'land_croquis': 'approved', 'location': 'approved',
                         'section-market-study': 'approved', 'section-financial-calc': 'approved',
                         'section-visual-concept': 'approved', 'section-executive-content': 'approved'}
        with self.app.app_context():
            self.draft_id = db.save_project_draft(self.tenant, 'tenant-admin:' + self.tenant,
                                                   self.project, self.statuses,
                                                   draft_id=self.project['draftId'])
        for name, value in (('_require_billing_balance', None), ('_best_use_documents_backed', True)):
            mocked = patch.object(self.application, name, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        for name in ('_bill_tenant_unbilled_usage_async', '_best_use_map_references'):
            mocked = patch.object(self.application, name, return_value=[])
            mocked.start()
            self.addCleanup(mocked.stop)
        mocked = patch.object(self.application, '_land_chat_regulation_evidence', return_value='ملفات الأمانة: الاشتراط المسجل')
        mocked.start()
        self.addCleanup(mocked.stop)
        mocked = patch.object(self.application, 'UPLOADS_DIR', self.temp_dir.name)
        mocked.start()
        self.addCleanup(mocked.stop)

    def draft(self):
        with self.app.app_context():
            return db.get_project_draft_by_id(self.tenant, self.draft_id)

    def provider_reply(self, payload):
        return {'choices': [{'finish_reason': 'stop', 'message': {
            'content': json.dumps(payload, ensure_ascii=False)}}]}

    def generate(self, **overrides):
        with patch.object(self.application, 'call_text_chat', return_value=self.provider_reply(self.raw)) as provider:
            response = self.client.post('/api/best-use/generate', headers=self.headers, json={
                'draftId': self.draft_id, 'expectedRevision': self.draft()['revision'], **overrides})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json(), provider

    def decide(self, proposal, decision='approved', **overrides):
        return self.client.post('/api/best-use/decision', headers=self.headers, json={
            'draftId': self.draft_id, 'proposalId': proposal['id'], 'decision': decision,
            'expectedRevision': self.draft()['revision'], **overrides})

    def test_generation_uses_saved_scoped_inputs_without_touching_components_or_visuals(self):
        before = self.draft()
        result, provider = self.generate(projectData={'approved_floor_area_ratio': 99})
        after = self.draft()
        self.assertFalse(result['bestUse']['approved'])
        self.assertEqual(after['draft_data']['financial_study_model'], before['draft_data']['financial_study_model'])
        self.assertEqual(after['draft_data']['visual_concept'], before['draft_data']['visual_concept'])
        self.assertEqual(after['section_statuses']['section-visual-concept'], 'approved')
        self.assertEqual(after['section_statuses']['section-financial-calc'], 'approved')
        self.assertEqual(provider.call_args.kwargs['usage_ctx']['draft_id'], self.draft_id)
        self.assertEqual(provider.call_args.kwargs['usage_ctx']['tenant_id'], self.tenant)
        prompt = provider.call_args.args[1]
        self.assertIn('معامل مسطح البناء', provider.call_args.args[0])
        self.assertIn('طلب موثق على الشقق السكنية', prompt)
        self.assertNotIn('isDistinguished', prompt)
        self.assertEqual(result['bestUse']['capacity']['far'], 2)

    def test_approval_replaces_the_table_once_and_demotes_only_dependent_financial_approval(self):
        result, _ = self.generate()
        before = self.draft()
        response = self.decide(result['bestUse'])
        self.assertEqual(response.status_code, 200, response.get_json())
        saved = self.draft()
        self.assertTrue(saved['draft_data']['best_use_data']['approved'])
        self.assertEqual(len(saved['draft_data']['financial_study_model']['dynamicRows']['components']), 3)
        self.assertEqual(saved['section_statuses']['section-financial-calc'], 'draft')
        self.assertEqual(saved['section_statuses']['section-executive-content'], 'draft')
        self.assertEqual(response.get_json()['sectionStatuses']['section-executive-content'], 'draft')
        self.assertEqual(saved['section_statuses']['section-best-use'], 'draft')
        self.assertEqual(saved['section_statuses']['section-visual-concept'], before['section_statuses']['section-visual-concept'])
        self.assertEqual(saved['draft_data']['visual_concept'], before['draft_data']['visual_concept'])
        again = self.decide(result['bestUse'])
        self.assertEqual(again.status_code, 200, again.get_json())
        self.assertEqual(self.draft()['revision'], saved['revision'])
        self.assertEqual(self.draft()['draft_data']['financial_study_model'], saved['draft_data']['financial_study_model'])

    def test_calculator_inputs_do_not_constrain_or_invalidate_guided_generation(self):
        result, provider = self.generate()
        prompt = provider.call_args.args[1]
        self.assertNotIn('unitRevenueMode', prompt)
        self.assertNotIn('"basementArea":', prompt)
        self.assertEqual(result['bestUse']['mode'], 'guided')
        payload = copy.deepcopy(self.draft()['draft_data'])
        payload['financial_study_model']['inputs'].update(basementArea=3000, unitRevenueMode='rental')
        saved = self.client.post('/api/project-draft', headers=self.headers, json={'draftData': payload})
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertFalse(self.draft()['draft_data']['best_use_data'].get('inputsChanged', False))
        approved = self.decide(result['bestUse'])
        self.assertEqual(approved.status_code, 200, approved.get_json())
        self.assertEqual(approved.get_json()['financialModel']['inputs']['basementArea'], 0)
        self.assertEqual(approved.get_json()['financialModel']['inputs']['unitRevenueMode'], 'rental')
        self.assertEqual(self.draft()['draft_data']['best_use_data']['sourceHash'], result['bestUse']['sourceHash'])

    def test_basement_totals_are_applied_only_on_approval_and_old_results_are_removed(self):
        self.raw['components'].append({'name': 'بدروم', 'useType': 'basement', 'units': 1,
            'unitArea': 1000, 'builtArea': 1000, 'revenueArea': 0, 'footprintArea': 0,
            'investmentModel': 'nonRevenue', 'reason': 'مواقف تخطيطية تحتاج تحقق السماح.',
            'areaReason': 'طبقة واحدة ضمن مساحة الأرض.'})
        before = self.draft()['draft_data']['financial_study_model']
        result, _ = self.generate()
        self.assertEqual(self.draft()['draft_data']['financial_study_model'], before)
        response = self.decide(result['bestUse'])
        self.assertEqual(response.status_code, 200, response.get_json())
        model = response.get_json()['financialModel']
        self.assertEqual(model['inputs']['basementArea'], 1000)
        self.assertEqual(model['inputs']['builtUpAreaAbove'], 8800)
        self.assertEqual(set(model['financialCalcData']), {'components'})
        revision = self.draft()['revision']
        self.assertEqual(self.decide(result['bestUse']).status_code, 200)
        self.assertEqual(self.draft()['revision'], revision)

    def test_rejection_leaves_existing_components_and_financial_approval_unchanged(self):
        result, _ = self.generate()
        before = self.draft()
        rejected = self.decide(result['bestUse'], 'rejected')
        self.assertEqual(rejected.status_code, 200, rejected.get_json())
        saved = self.draft()
        self.assertTrue(saved['draft_data']['best_use_data']['rejected'])
        self.assertEqual(saved['draft_data']['financial_study_model'], before['draft_data']['financial_study_model'])
        self.assertEqual(saved['section_statuses']['section-financial-calc'], 'approved')
        self.assertNotIn('section-best-use', saved['section_statuses'])

    def test_chat_remembers_the_discussion_and_answers_from_the_same_project_and_proposal(self):
        result, _ = self.generate()
        reply = {'reply': 'مساحة الشقق مرتبطة بالطلب الوارد في الدراسة.', 'proposal': None}
        with patch.object(self.application, 'call_text_chat', return_value=self.provider_reply(reply)) as provider:
            response = self.client.post('/api/best-use/chat', headers=self.headers, json={
                'draftId': self.draft_id, 'message': 'ليه مساحة الشقق كده؟',
                'expectedRevision': self.draft()['revision']})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn('توزيع سكني متوازن', provider.call_args.args[1])
        self.assertIn('الطلب', provider.call_args.args[1])
        self.assertEqual(len(self.draft()['draft_data']['best_use_chat']['messages']), 2)
        with patch.object(self.application, 'call_text_chat', return_value=self.provider_reply(reply)) as provider:
            response = self.client.post('/api/best-use/chat', headers=self.headers, json={
                'draftId': self.draft_id, 'message': 'وماذا عن الخدمات؟',
                'expectedRevision': self.draft()['revision']})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn('ليه مساحة الشقق كده؟', provider.call_args.args[1])
        self.assertEqual(self.draft()['draft_data']['best_use_data'], result['bestUse'])

    def test_old_proposal_snapshots_cannot_reintroduce_calculator_inputs_in_chat(self):
        result, _ = self.generate()
        draft = self.draft()
        project = copy.deepcopy(draft['draft_data'])
        project['best_use_data']['sourceSnapshot'].update(basementArea=99999, unitRevenueMode='sale')
        project['best_use_data']['capacity']['basementAreaLimit'] = 99999
        with self.app.app_context():
            db.save_project_draft(self.tenant, draft['user_id'], project, draft_id=self.draft_id,
                                  expected_revision=draft['revision'])
        with patch.object(self.application, 'call_text_chat', return_value=self.provider_reply({
                'reply': 'تفسير التوزيع.', 'proposal': None})) as provider:
            response = self.client.post('/api/best-use/chat', headers=self.headers,
                                        json={'draftId': self.draft_id, 'message': 'اشرح التوزيع'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertNotIn('unitRevenueMode', provider.call_args.args[1])
        self.assertNotIn('99999', provider.call_args.args[1])

    def test_chat_revision_is_an_unapproved_proposal_not_a_component_edit(self):
        self.generate()
        before = self.draft()
        adjusted = copy.deepcopy(self.raw)
        adjusted['components'][0].update(units=70, builtArea=7000, revenueArea=6300,
                                         footprintArea=1750)
        with patch.object(self.application, 'call_text_chat', return_value=self.provider_reply({
                'reply': 'اقتراح معدل بسبعين وحدة.', 'proposal': adjusted})):
            response = self.client.post('/api/best-use/chat', headers=self.headers, json={
                'draftId': self.draft_id, 'message': 'قلل الوحدات إلى سبعين', 'revise': True,
                'expectedRevision': before['revision']})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['bestUse']['components'][0]['units'], 70)
        self.assertFalse(response.get_json()['bestUse']['approved'])
        self.assertEqual(self.draft()['draft_data']['financial_study_model'], before['draft_data']['financial_study_model'])

    def test_a_plain_question_cannot_silently_replace_the_proposal(self):
        result, _ = self.generate()
        with patch.object(self.application, 'call_text_chat', return_value=self.provider_reply({
                'reply': 'تفسير فقط.', 'proposal': self.raw})):
            response = self.client.post('/api/best-use/chat', headers=self.headers, json={
                'draftId': self.draft_id, 'message': 'اشرح لي التوزيع',
                'expectedRevision': self.draft()['revision']})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.draft()['draft_data']['best_use_data'], result['bestUse'])

    def test_every_section_approval_path_requires_the_generated_proposal_approval(self):
        self.generate()
        for url, body in (
            ('/api/project-draft/section-status', {'sectionKey': 'section-best-use', 'sectionStatus': 'approved'}),
            ('/api/project-draft/section-status', {'sectionStatuses': {'section-best-use': 'approved'}}),
            ('/api/project-draft/section-version', {'sectionKey': 'section-best-use'}),
        ):
            with self.subTest(url=url, body=body):
                response = self.client.post(url, headers=self.headers, json={'draftId': self.draft_id, **body})
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertEqual(response.get_json()['error_code'], 'BEST_USE_APPROVAL_REQUIRED')

    def test_draft_save_cannot_forge_a_proposal_or_its_approval(self):
        result, _ = self.generate()
        payload = copy.deepcopy(self.draft()['draft_data'])
        payload['best_use_data'].update(approved=True, components=[])
        saved = self.client.post('/api/project-draft', headers=self.headers, json={
            'draftData': payload, 'sectionStatuses': {'section-best-use': 'approved'}})
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(self.draft()['draft_data']['best_use_data'], result['bestUse'])
        self.assertNotEqual(self.draft()['section_statuses'].get('section-best-use'), 'approved')

    def test_a_changed_far_invalidates_the_old_proposal_without_editing_components(self):
        result, _ = self.generate()
        payload = copy.deepcopy(self.draft()['draft_data'])
        payload['approved_floor_area_ratio'] = 3
        self.client.post('/api/project-draft', headers=self.headers, json={'draftData': payload})
        response = self.decide(result['bestUse'])
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(response.get_json()['error_code'], 'BEST_USE_INPUTS_CHANGED')
        self.assertEqual(self.draft()['draft_data']['financial_study_model'], self.project['financial_study_model'])

    def test_missing_prerequisites_do_not_call_the_provider(self):
        for section in ('land_croquis', 'location', 'section-market-study'):
            with self.app.app_context():
                db.update_draft_section_status_by_id(self.tenant, self.draft_id, {section: 'draft'})
            with self.subTest(section=section), patch.object(self.application, 'call_text_chat') as provider:
                response = self.client.post('/api/best-use/generate', headers=self.headers,
                                            json={'draftId': self.draft_id})
                self.assertEqual(response.status_code, 400, response.get_json())
                provider.assert_not_called()
            with self.app.app_context():
                db.update_draft_section_status_by_id(self.tenant, self.draft_id, {section: 'approved'})

    def test_unbacked_documents_are_not_accepted(self):
        with patch.object(self.application, '_best_use_documents_backed', return_value=False), \
                patch.object(self.application, 'call_text_chat') as provider:
            response = self.client.post('/api/best-use/generate', headers=self.headers,
                                        json={'draftId': self.draft_id})
        self.assertEqual(response.status_code, 400, response.get_json())
        provider.assert_not_called()

    def test_foreign_and_hidden_sections_do_not_leak_inputs_to_the_provider(self):
        with patch.object(self.application, 'call_text_chat') as provider:
            response = self.client.post('/api/best-use/generate',
                headers={'Authorization': 'Bearer ' + self.other_token}, json={'draftId': self.draft_id})
            self.assertEqual(response.status_code, 404, response.get_json())
            provider.assert_not_called()
        for section in ('section-best-use', 'land_croquis', 'location', 'section-market-study'):
            with self.subTest(section=section), patch.object(self.application, '_hidden_field_sections', return_value={section}), \
                    patch.object(self.application, 'call_text_chat') as provider:
                response = self.client.post('/api/best-use/generate', headers=self.headers,
                                            json={'draftId': self.draft_id})
                self.assertEqual(response.status_code, 403, response.get_json())
                provider.assert_not_called()

    def test_hiding_a_source_section_also_hides_the_derived_proposal_and_chat(self):
        self.generate()
        stored = self.draft()['draft_data']
        with self.app.test_request_context():
            self.application.g.tenant_id = self.tenant
            self.application.g.user_id = 'scoped-employee'
            self.application.g.is_admin = False
            with patch.object(db, 'get_user_field_sections', return_value={'land_croquis': False}):
                filtered = self.application._draft_data_for_response(stored)
                self.assertNotIn('best_use_data', filtered)
                self.assertNotIn('best_use_chat', filtered)
                self.assertTrue(self.application._section_key_forbidden('section-best-use'))

    def test_provider_result_cannot_overwrite_a_racing_save(self):
        def generate(*args, **kwargs):
            draft = db.get_project_draft_by_id(self.tenant, self.draft_id)
            updated = dict(draft['draft_data'], project_name='اسم أحدث')
            db.save_project_draft(self.tenant, draft['user_id'], updated,
                                  draft_id=self.draft_id, expected_revision=draft['revision'])
            return self.provider_reply(self.raw)
        with patch.object(self.application, 'call_text_chat', side_effect=generate):
            response = self.client.post('/api/best-use/generate', headers=self.headers,
                                        json={'draftId': self.draft_id})
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(self.draft()['draft_data']['project_name'], 'اسم أحدث')
        self.assertNotIn('best_use_data', self.draft()['draft_data'])

    def test_a_stale_revision_does_not_start_generation(self):
        with patch.object(self.application, 'call_text_chat') as provider:
            response = self.client.post('/api/best-use/generate', headers=self.headers, json={
                'draftId': self.draft_id, 'expectedRevision': self.draft()['revision'] - 1})
        self.assertEqual(response.status_code, 409, response.get_json())
        provider.assert_not_called()

    def test_invalid_proposals_and_provider_failures_leave_the_draft_untouched(self):
        before = self.draft()
        raw = copy.deepcopy(self.raw)
        raw['components'][0]['useType'] = 'hospitality'
        with patch.object(self.application, 'call_text_chat', return_value=self.provider_reply(raw)):
            response = self.client.post('/api/best-use/generate', headers=self.headers,
                                        json={'draftId': self.draft_id})
        self.assertEqual(response.status_code, 422, response.get_json())
        self.assertEqual(self.draft()['draft_data'], before['draft_data'])
        with patch.object(self.application, 'call_text_chat', side_effect=RuntimeError('provider failed')):
            response = self.client.post('/api/best-use/generate', headers=self.headers,
                                        json={'draftId': self.draft_id})
        self.assertEqual(response.status_code, 503, response.get_json())
        self.assertEqual(self.draft()['draft_data'], before['draft_data'])

    def test_a_rejected_distribution_is_retried_once_with_the_rejection_reason(self):
        bad = copy.deepcopy(self.raw)
        bad['components'][0].update(builtArea=9000)
        replies = iter([self.provider_reply(bad), self.provider_reply(self.raw)])
        with patch.object(self.application, 'call_text_chat', side_effect=lambda *a, **k: next(replies)) as provider:
            response = self.client.post('/api/best-use/generate', headers=self.headers, json={
                'draftId': self.draft_id, 'expectedRevision': self.draft()['revision']})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(provider.call_count, 2)
        self.assertIn('رُفض', provider.call_args.args[1])
        self.assertIn('حصته الأرضية', provider.call_args.args[1])
        self.assertIn('4 أدوار', provider.call_args.args[1])
        self.assertEqual(response.get_json()['bestUse']['components'][0]['builtArea'], 8000)

    def test_a_repeatedly_rejected_distribution_still_fails_without_touching_the_draft(self):
        before = self.draft()
        bad = copy.deepcopy(self.raw)
        bad['components'][0].update(builtArea=9000)
        with patch.object(self.application, 'call_text_chat', return_value=self.provider_reply(bad)) as provider:
            response = self.client.post('/api/best-use/generate', headers=self.headers, json={
                'draftId': self.draft_id, 'expectedRevision': self.draft()['revision']})
        self.assertEqual(response.status_code, 422, response.get_json())
        self.assertEqual(provider.call_count, 4)
        self.assertEqual(response.get_json()['error_code'], 'BEST_USE_INVALID_PROPOSAL')
        self.assertIn('حصته الأرضية', response.get_json()['validation'])
        self.assertEqual(self.draft()['draft_data'], before['draft_data'])

    def test_queued_jobs_are_scoped_and_complete_off_the_request_path(self):
        with patch.object(self.application.threading, 'Thread') as thread:
            queued = self.client.post('/api/best-use/generate', headers=self.headers, json={
                'draftId': self.draft_id, 'background': True,
                'expectedRevision': self.draft()['revision']})
        self.assertEqual(queued.status_code, 202, queued.get_json())
        job_id = queued.get_json()['jobId']
        pending = self.client.get('/api/best-use/jobs/' + job_id, headers=self.headers)
        self.assertEqual(pending.get_json()['status'], 'queued')
        foreign = self.client.get('/api/best-use/jobs/' + job_id,
                                   headers={'Authorization': 'Bearer ' + self.other_token})
        self.assertEqual(foreign.status_code, 404)
        worker = thread.call_args.kwargs
        with patch.object(self.application, 'call_text_chat', return_value=self.provider_reply(self.raw)):
            worker['target'](*worker['args'])
        completed = self.client.get('/api/best-use/jobs/' + job_id, headers=self.headers)
        self.assertEqual(completed.status_code, 200, completed.get_json())
        self.assertEqual(completed.get_json()['status'], 'completed')
        self.assertFalse(completed.get_json()['bestUse']['approved'])
        self.assertNotIn('actor', completed.get_json())
        self.assertNotIn('payload', completed.get_json())

    def test_questions_remain_available_after_section_approval_without_invalidating_it(self):
        result, _ = self.generate()
        self.assertEqual(self.decide(result['bestUse']).status_code, 200)
        version = self.client.post('/api/project-draft/section-version', headers=self.headers,
                                   json={'draftId': self.draft_id, 'sectionKey': 'section-best-use'})
        self.assertEqual(version.status_code, 200, version.get_json())
        approved = self.client.post('/api/project-draft/section-version/decision', headers=self.headers,
                                    json={'versionId': version.get_json()['version']['id'], 'decision': 'approved'})
        self.assertEqual(approved.status_code, 200, approved.get_json())
        before = self.draft()
        with patch.object(self.application, 'call_text_chat', return_value=self.provider_reply({
                'reply': 'الخدمات مكون مساند للاستخدام السكني.', 'proposal': None})):
            response = self.client.post('/api/best-use/chat', headers=self.headers, json={
                'draftId': self.draft_id, 'message': 'لماذا هذه الخدمات؟',
                'expectedRevision': before['revision']})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.draft()['section_statuses']['section-best-use'], 'approved')
        self.assertEqual(self.draft()['draft_data']['best_use_data'], before['draft_data']['best_use_data'])
        with self.app.test_request_context():
            self.application.g.tenant_id = self.tenant
            state, _meta = self.application._section_version_readiness(self.draft(), 'section-best-use')
            self.assertEqual(state, 'ok')

    def test_rejected_optional_section_does_not_block_project_submission(self):
        result, _ = self.generate()
        self.assertEqual(self.decide(result['bestUse'], 'rejected').status_code, 200)
        response = self.client.post('/api/project-draft/request-approval', headers=self.headers,
                                    json={'draftId': self.draft_id})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_optional_rejected_proposal_does_not_carry_an_expired_section_gate(self):
        result, _ = self.generate()
        self.decide(result['bestUse'], 'rejected')
        self.assertNotIn('section-best-use', self.draft()['section_statuses'])
        with self.app.app_context(), patch.object(db, 'section_versions_overview', return_value={
                'section-best-use': {'status': 'approved', 'is_expired': True},
                'location': {'status': 'approved', 'is_expired': True}}):
            self.assertEqual(db.expired_approved_sections(self.tenant, self.draft_id), ['location'])

    def test_a_copy_never_inherits_the_proposal_or_its_gate(self):
        result, _ = self.generate()
        self.decide(result['bestUse'])
        copied = db.sanitize_copied_draft_data(self.draft()['draft_data'])
        self.assertNotIn('best_use_data', copied)
        self.assertNotIn('best_use_chat', copied)
        self.assertEqual(copied['financial_study_model'],
                         self.draft()['draft_data']['financial_study_model'])

    def test_unused_section_status_is_omitted_so_the_feature_remains_optional(self):
        saved = self.client.post('/api/project-draft', headers=self.headers, json={
            'draftData': self.project, 'sectionStatuses': {**self.statuses, 'section-best-use': 'draft'}})
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertNotIn('section-best-use', self.draft()['section_statuses'])


if __name__ == '__main__':
    unittest.main()
