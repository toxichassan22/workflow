"""Local edits preserve all non-target markup and current project facts."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import auth
import db


class DesignerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp.name, 'designer-integration.db')
        import app
        cls.module = app
        app.app.config.update(TESTING=True)
        with app.app.app_context():
            # `import app` is a no-op when another suite already imported it —
            # build the schema on this suite's DB_PATH explicitly.
            db.init_db()
            cls.tenant = db.create_tenant('Designer', 'designer@example.test', 'hash', 'designer')
        cls.token = auth.create_token(cls.tenant, 'designer@example.test', user_role='company_admin')
        # These tests exercise the legacy all-at-once path; hold the flag off
        # regardless of the developer's local .env.
        cls.flag_off = patch.object(app, 'DESIGNER_AGENT', False)
        cls.flag_off.start()

    @classmethod
    def tearDownClass(cls):
        cls.flag_off.stop()
        cls.temp.cleanup()

    @staticmethod
    def strip_ids(items):
        # The backend backfills a stable uid=197608(root) gid=197608 groups=197608 on every slide before planning;
        # fixture slides never had one, so comparisons ignore it.
        return [{k: v for k, v in s.items() if k != 'id'} for s in items]

    def call(self, actions, slides, message, project=None, **kwargs):
        plan = {'response': 'planned', 'actions': actions}
        with patch.object(self.module, 'call_text_chat', return_value={'choices': [{'message': {'content': json.dumps(plan)}}]}) as model:
            response = self.module.app.test_client().post('/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token},
                json={'message': message, 'slidesData': slides, 'projectData': project or {'project_name': 'Test'}, **kwargs})
        return response, model

    @staticmethod
    def slides():
        return [{'title': 'Untouched', 'type': 'section_divider', 'section_key': 'financial',
                 'html': '<div class="slide" style="background:#abcdef"><p>1234.56</p></div>'},
                {'title': 'Table', 'type': 'content', 'html': '<div class="slide"><h1 style="color:#112233">Title</h1><table><thead><tr><th>البند</th><th>السعر</th></tr></thead><tbody><tr><td>A</td><td>1234.56</td></tr><tr><td>B</td><td>12.34%</td></tr></tbody></table><p>Keep</p></div>'}]

    def test_table_column_edit_is_surgical_and_does_not_call_editor_model(self):
        slides = self.slides()
        response, model = self.call([{'tool': 'edit_slides', 'params': {'target': 'indexes', 'indexes': [2], 'instruction': 'احذف عمود السعر'}}], slides, 'احذف عمود السعر في الشريحة 2')
        self.assertEqual(response.status_code, 200, response.get_json())
        result = response.get_json()['data']['slidesData']
        self.assertEqual(self.strip_ids([result[0]]), [slides[0]])
        expected = slides[1]['html'].replace('<th>السعر</th>', '').replace('<td>1234.56</td>', '').replace('<td>12.34%</td>', '')
        self.assertEqual(result[1]['html'], expected)
        # Supported table deletes bypass the planner LLM entirely (deterministic local edit),
        # so a large deck never hits the planner token cap (402) for this operation.
        self.assertEqual(model.call_count, 0)

    def test_blocked_table_delete_goes_slim_without_full_deck(self):
        slides = self.slides()
        prompts = []
        def provider(prompt, instruction, **kwargs):
            prompts.append(prompt)
            content = {'response': 'سؤال', 'actions': [{'tool': 'ask', 'params': {'question': 'أي عمود تقصد؟'}}]}
            return {'choices': [{'message': {'content': json.dumps(content)}}]}
        with patch.object(self.module, 'call_text_chat', side_effect=provider) as model:
            response = self.module.app.test_client().post('/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token},
                json={'message': 'احذف عمود مجهول في الشريحة 2', 'slidesData': slides, 'projectData': {'project_name': 'Test'}})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['data']['action'], 'ask')
        # One slim planner call only: the full unabridged deck prompt is skipped because the
        # local precheck already named the blocker (unknown column header).
        self.assertEqual(model.call_count, 1)
        self.assertEqual(len(prompts), 1)
        # The slim prompt carries the target slide only: slide 1 HTML body stays out,
        # while the available headers note names the real column.
        self.assertNotIn('#abcdef', prompts[0])
        self.assertIn('السعر', prompts[0])

    def test_color_edit_preserves_text_numbers_and_other_slide(self):
        slides = self.slides()
        response, model = self.call([{'tool': 'edit_slides', 'params': {'indexes': [2], 'instruction': 'استبدل اللون #112233 باللون #445566'}}], slides, 'استبدل اللون #112233 باللون #445566 في الشريحة 2')
        self.assertEqual(response.status_code, 200, response.get_json())
        result = response.get_json()['data']['slidesData']
        self.assertEqual(self.strip_ids([result[0]]), [slides[0]])
        self.assertEqual(result[1]['html'], slides[1]['html'].replace('#112233', '#445566'))
        self.assertEqual(model.call_count, 1)

    def test_invalid_target_and_partial_edit_apply_nothing(self):
        slides = self.slides()
        response, _ = self.call([{'tool': 'edit_slides', 'params': {'indexes': [999], 'instruction': 'احذف الصف 1'}}], slides, 'احذف الصف 1', **{'indexes': [999]})
        self.assertEqual(response.status_code, 422)
        response, _ = self.call([{'tool': 'edit_slides', 'params': {'target': 'all', 'instruction': 'احذف الصف 1'}}], slides, 'احذف الصف 1 من كل الشرائح')
        # A batch where every slide fails applies nothing and reports the failure —
        # the old all-or-nothing 422 only survives for structural operations.
        self.assertEqual(response.status_code, 200)
        body = response.get_json()['data']
        self.assertEqual(body['actions'][0]['status'], 'failed')
        self.assertTrue(body.get('failureReason'))
        self.assertEqual(self.strip_ids(body['slidesData']), slides)

    def test_planner_and_editor_get_full_deck_and_project(self):
        slides = self.slides()
        project = {'project_name': 'Test', 'custom': 'x' * 7000 + 'TAIL_FACT',
                   'nearby_landmarks_data': json.dumps([{'custom': 'LANDMARK_EXTENSION'}])}
        prompts = []
        def provider(prompt, instruction, **kwargs):
            prompts.append(prompt)
            if len(prompts) == 1:
                content = {'actions': [{'tool': 'edit_slides', 'params': {'indexes': [2], 'instruction': 'أضف النص المطلوب'}}]}
            else:
                content = {'html': slides[1]['html'].replace('<p>Keep</p>', '<p>Keep</p><p>TAIL_FACT</p>'), 'response': 'تمت الإضافة'}
            return {'choices': [{'message': {'content': json.dumps(content)}}]}
        with patch.object(self.module, 'call_text_chat', side_effect=provider), patch('generate_pdf_from_preview.render_slide_to_image_base64', return_value=None):
            response = self.module.app.test_client().post('/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token}, json={
                'message': 'أضف النص للشريحة 2', 'slidesData': slides, 'projectData': project})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertGreaterEqual(len(prompts), 2)
        for prompt in prompts:
            for value in ['TAIL_FACT', 'LANDMARK_EXTENSION', '#abcdef', 'Untouched', '1234.56']:
                self.assertIn(value, prompt)
        self.assertEqual(self.strip_ids([response.get_json()['data']['slidesData'][0]]), [slides[0]])

    def test_operational_merge_preserves_urls_and_explicit_clears(self):
        with patch.object(db, 'get_project_draft_by_id', return_value={'draft_data': {'image': '/uploads/a.png', 'custom': {'old': True}, 'logo': '/uploads/b.png'}}):
            result = self.module._designer_project_data_for_request({'custom': {}, 'logo': ''}, {'draft_id': 'draft'}, self.tenant)
        self.assertEqual(result['image'], '/uploads/a.png')
        self.assertEqual(result['custom'], {})
        self.assertEqual(result['logo'], '')

    def test_snapshot_echo_does_not_shadow_live_draft(self):
        # A presentation workspace re-sends the project data it was opened with
        # on every chat turn while the linked draft keeps moving. An echo equal
        # to the snapshot must not drag the merge back to it — otherwise
        # «حدّث بيانات التواصل» keeps applying the old approved values forever.
        presentation = {'draft_id': 'd1', 'project_data': {
            'project_name': 'P', 'contact_phone': '0111', 'contact_name': 'قديم'}}
        request = {'project_name': 'P', 'contact_phone': '0111', 'contact_name': 'قديم'}
        draft = {'draft_data': {'project_name': 'P', 'contact_phone': '0222',
                                'contact_name': 'جديد'}}
        superseded = []
        with patch.object(db, 'get_project_draft_by_id', return_value=draft):
            result = self.module._designer_project_data_for_request(
                request, presentation, self.tenant, superseded_out=superseded)
        self.assertEqual(result['contact_phone'], '0222')
        self.assertEqual(result['contact_name'], 'جديد')
        self.assertIn('0111', json.dumps(superseded, ensure_ascii=False))

    def test_form_edit_still_wins_over_snapshot_and_draft(self):
        # A request value that moved away from the snapshot is a real in-session
        # form edit — the autosave is what lands it in the draft a moment later.
        presentation = {'draft_id': 'd1', 'project_data': {'contact_name': 'قديم'}}
        draft = {'draft_data': {'contact_name': 'قيمة المسودة'}}
        with patch.object(db, 'get_project_draft_by_id', return_value=draft):
            result = self.module._designer_project_data_for_request(
                {'contact_name': 'مُدخل جديد'}, presentation, self.tenant)
        self.assertEqual(result['contact_name'], 'مُدخل جديد')

    def test_blank_request_field_cannot_wipe_draft_value(self):
        # The form renders every known field, so a key the snapshot never carried
        # arrives blank — it must not erase what the draft collected meanwhile.
        presentation = {'draft_id': 'd1', 'project_data': {'project_name': 'P'}}
        draft = {'draft_data': {'project_name': 'P', 'contact_email': 'new@x.test'}}
        with patch.object(db, 'get_project_draft_by_id', return_value=draft):
            result = self.module._designer_project_data_for_request(
                {'project_name': 'P', 'contact_email': ''}, presentation, self.tenant)
        self.assertEqual(result['contact_email'], 'new@x.test')

    def test_save_numbering_does_not_rebuild_edited_content(self):
        slides = self.slides()
        slides[1]['_designer_keep_html'] = True
        with self.module.app.app_context():
            result = self.module.slide_engine.renumber_presentation_slides(slides, branding={}, project_data={})
        self.assertEqual(result[1]['html'], slides[1]['html'])
        result = self.module.slide_engine.renumber_presentation_slides(slides, branding={}, project_data={}, preserve_html=True)
        self.assertEqual([s['html'] for s in result], [s['html'] for s in slides])

    # ── Free balance replies and the span-01-lite router ──────────────────────

    def test_balance_question_is_answered_free_without_model(self):
        slides = self.slides()
        with patch.object(self.module, '_designer_available_sar', return_value=150.0), \
                patch.object(self.module, '_designer_span_route') as router, \
                patch.object(self.module, 'call_text_chat') as model, \
                patch.object(self.module, 'call_openrouter_messages') as agent_model:
            response = self.module.app.test_client().post(
                '/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token},
                json={'message': 'هو الرصيد اللي فاضل في شركتك قد إيه؟',
                      'slidesData': slides, 'projectData': {}})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertEqual(body['action'], 'chat_only')
        self.assertIn('150', body['response'])
        self.assertIn('لم تستهلك أي رصيد', body['response'])
        self.assertEqual(body['ai_calls'], 0)
        self.assertFalse(body['billed'])
        self.assertEqual(model.call_count, 0)
        self.assertEqual(agent_model.call_count, 0)
        self.assertEqual(router.call_count, 0)

    def test_zero_balance_tenant_gets_balance_reply_not_402(self):
        # The wallet guard used to fire before the canned replies, so an empty
        # wallet could not even ask «كام رصيدي». The free candidate now skips
        # the guard, while the paid path further down stays guarded.
        slides = self.slides()
        with patch.object(db, 'billing_enforcement_enabled', return_value=True), \
                patch.object(db, 'get_tenant_balance', return_value=0.0), \
                patch.object(db, 'get_package_remaining_sar', return_value=0.0), \
                patch.object(self.module, 'call_text_chat') as model:
            response = self.module.app.test_client().post(
                '/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token},
                json={'message': 'كام رصيدي دلوقتي؟', 'slidesData': slides,
                      'projectData': {}})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertIn('0 ريال', body['response'])
        self.assertIn('لم تستهلك أي رصيد', body['response'])
        self.assertEqual(body['ai_calls'], 0)
        self.assertEqual(model.call_count, 0)

    def test_paid_candidate_still_gated_under_enforcement(self):
        # An edit request on an empty wallet must still hit the wallet guard —
        # the preflight probe only releases genuinely free turns.
        slides = self.slides()
        with patch.object(db, 'billing_enforcement_enabled', return_value=True), \
                patch.object(db, 'get_tenant_balance', return_value=0.0):
            response = self.module.app.test_client().post(
                '/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token},
                json={'message': 'عدل عنوان الشريحة', 'slidesData': slides,
                      'projectData': {}})
        self.assertEqual(response.status_code, 402, response.get_json())
        self.assertEqual(response.get_json().get('error_code'), 'INSUFFICIENT_BALANCE')

    def test_history_vetoed_free_candidate_still_gated(self):
        # «سلام» reads free in preflight, but the assistant's pending question
        # makes it an answer — the deferred guard must catch it before planning.
        slides = self.slides()
        history = [{'role': 'assistant', 'content': 'أي شريحة تقصد؟'}]
        with patch.object(db, 'billing_enforcement_enabled', return_value=True), \
                patch.object(db, 'get_tenant_balance', return_value=0.0):
            response = self.module.app.test_client().post(
                '/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token},
                json={'message': 'سلام', 'slidesData': slides, 'projectData': {},
                      'history': history})
        self.assertEqual(response.status_code, 402, response.get_json())

    def test_router_local_route_answers_without_planner(self):
        slides = self.slides()
        with patch.object(self.module, '_designer_span_route', return_value='chat') as router, \
                patch.object(self.module, 'call_text_chat') as model:
            response = self.module.app.test_client().post(
                '/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token},
                json={'message': 'إيه أخبارك النهاردة؟', 'slidesData': slides,
                      'projectData': {}})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertEqual(body['action'], 'chat_only')
        self.assertIn('Landloom', body['response'])
        self.assertEqual(router.call_count, 1)
        self.assertEqual(model.call_count, 0)

    def test_router_balance_route_answers_figure_without_marker(self):
        slides = self.slides()
        with patch.object(self.module, '_designer_span_route', return_value='balance'), \
                patch.object(self.module, '_designer_available_sar', return_value=200.0), \
                patch.object(self.module, 'call_text_chat') as model:
            response = self.module.app.test_client().post(
                '/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token},
                json={'message': 'فاضل ايه في الحساب؟', 'slidesData': slides,
                      'projectData': {}})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertIn('200', body['response'])
        self.assertIn('لم تستهلك أي رصيد', body['response'])
        self.assertEqual(model.call_count, 0)

    def test_router_design_route_reaches_the_planner(self):
        slides = self.slides()
        plan = {'response': 'تم', 'actions': [
            {'tool': 'edit_slides', 'params': {'target': 'indexes', 'indexes': [1],
                                             'instruction': 'حسّن الخط'}}]}
        with patch.object(self.module, '_designer_span_route', return_value='design') as router, \
                patch.object(self.module, '_designer_deterministic_plan', return_value=None), \
                patch.object(self.module, 'call_text_chat',
                             return_value={'choices': [{'message': {'content': json.dumps(plan)}}]}) as model, \
                patch.object(self.module, '_designer_edit_slide',
                             side_effect=lambda html, *a, **k: (html + 'x', 'تم')), \
                patch.object(self.module.designer_chat_reliability, '_auto_heal_workspace_slides',
                             side_effect=lambda s, *a: s):
            response = self.module.app.test_client().post(
                '/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token},
                json={'message': 'حسن الخط في الشريحة 1', 'slidesData': slides,
                      'projectData': {'project_name': 'P'}, 'slideIndex': 0})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(router.call_count, 1)
        self.assertEqual(model.call_count, 1)

    def test_router_skips_plan_continuations(self):
        slides = self.slides()
        plan = {'response': 'تم', 'actions': []}
        with patch.object(self.module, '_designer_span_route', return_value='chat') as router, \
                patch.object(self.module, '_designer_deterministic_plan', return_value=None), \
                patch.object(self.module, 'call_text_chat',
                             return_value={'choices': [{'message': {'content': json.dumps(plan)}}]}):
            self.module.app.test_client().post(
                '/api/designer-chat', headers={'Authorization': 'Bearer ' + self.token},
                json={'message': 'نعم', 'slidesData': slides, 'projectData': {},
                      'confirmPlan': {'ops': [], 'deckSignature': 'x'}})
        # Whatever the legacy path does with the continuation, the router must
        # never run on it — the message is a plan decision, not a chat turn.
        self.assertEqual(router.call_count, 0)


class SpanRouterTests(unittest.TestCase):
    """respan/span-01-lite Decisions-API router: scores each turn design-vs-chat."""

    @classmethod
    def setUpClass(cls):
        import app
        cls.module = app

    @staticmethod
    def _fake_response(status=200, payload=None, answers=None):
        fake = Mock()
        fake.status_code = status
        fake.text = 'x'
        fake.json.return_value = payload if payload is not None else {
            'answers': answers or {},
            'usage': {'input_tokens': 120, 'output_tokens': 0, 'cost': 0},
            'id': 'gen-dec-test'}
        return fake

    def _route(self, message, history=None, response=None, side_effect=None):
        settled = []
        with patch.dict(self.module.app.config, {'TESTING': False}), \
                patch.object(self.module, 'SPAN_ROUTER_ENABLED', True), \
                patch.object(self.module, '_has_any_openrouter_key', return_value=True), \
                patch.object(self.module, '_tenant_key_gate', return_value=None), \
                patch.object(self.module, '_begin_ai_attempt_record', return_value='evt-1'), \
                patch.object(self.module, '_settle_ai_attempt_record',
                             side_effect=lambda *a: settled.append(a)), \
                patch.object(self.module, 'requests') as rq:
            if side_effect is not None:
                rq.post.side_effect = side_effect
            else:
                rq.post.return_value = response
            result = self.module._designer_span_route(message, history=history)
        return result, rq, settled

    def test_balance_message_routes_to_balance(self):
        result, rq, _ = self._route('هو الرصيد قد إيه؟', response=self._fake_response(answers={
            'needs_design_work': {'noul': 0.02},
            'asks_credit_balance': {'noul': 0.8}}))
        self.assertEqual(result, 'balance')
        self.assertEqual(rq.post.call_count, 1)
        _, kwargs = rq.post.call_args
        self.assertEqual(kwargs['json']['model'], self.module.SPAN_ROUTER_MODEL)
        self.assertEqual(set(kwargs['json']['questions']),
                         {'needs_design_work', 'asks_credit_balance'})
        self.assertTrue(kwargs['json']['state'])

    def test_edit_message_routes_to_design(self):
        result, _, _ = self._route('عدل عنوان الشريحة', response=self._fake_response(answers={
            'needs_design_work': {'noul': 0.9}, 'asks_credit_balance': {'noul': 0.02}}))
        self.assertEqual(result, 'design')

    def test_design_signal_beats_balance_signal(self):
        # «احذف سطر الرصيد من الجدول» mentions the wallet but is an edit —
        # design wins whenever its score clears the bar.
        result, _, _ = self._route('احذف سطر الرصيد', response=self._fake_response(answers={
            'needs_design_work': {'noul': 0.7}, 'asks_credit_balance': {'noul': 0.9}}))
        self.assertEqual(result, 'design')

    def test_plain_question_routes_to_chat(self):
        result, _, _ = self._route('كيف حالك؟', response=self._fake_response(answers={
            'needs_design_work': {'noul': 0.05}, 'asks_credit_balance': {'noul': 0.1}}))
        self.assertEqual(result, 'chat')

    def test_provider_failure_falls_open_to_design(self):
        result, rq, _ = self._route('x', side_effect=Exception('network down'))
        self.assertEqual(result, 'design')
        self.assertEqual(rq.post.call_count, 1)
        result, _, _ = self._route('x', response=self._fake_response(
            status=500, payload={'error': {'message': 'provider down'}}))
        self.assertEqual(result, 'design')
        result, _, _ = self._route('x', response=self._fake_response(payload={}))
        self.assertEqual(result, 'design')

    def test_missing_design_score_is_unknown_not_local(self):
        # A balance score alone never routes locally: without the design signal
        # the message might still be an edit the model failed to read.
        result, _, _ = self._route('فلوسي كام؟', response=self._fake_response(answers={
            'asks_credit_balance': {'noul': 0.95}}))
        self.assertEqual(result, 'design')
        result, _, _ = self._route('x', response=self._fake_response(answers={
            'needs_design_work': {'noul': 7.0}}))
        self.assertEqual(result, 'design')
        result, _, _ = self._route('x', response=self._fake_response(answers={
            'needs_design_work': {'noul': 'nope'}}))
        self.assertEqual(result, 'design')

    def test_pending_question_turn_skips_the_provider_call(self):
        history = [{'role': 'user', 'content': 'عدل القسم المالي'},
                   {'role': 'assistant', 'content': 'أي شريحة تقصد؟'}]
        result, rq, _ = self._route('الأولى', history=history,
                                    response=self._fake_response())
        self.assertEqual(result, 'design')
        self.assertEqual(rq.post.call_count, 0)

    def test_numbered_slide_turn_never_reaches_the_provider(self):
        # Naming a slide is design work by definition — the lite model gets no
        # vote, so even a wrong-but-confident score cannot swallow the edit.
        result, rq, _ = self._route(
            'في سلايدة رقم ١٦ حدث خريطة المعالم لاخر خريطة',
            response=self._fake_response(answers={
                'needs_design_work': {'noul': 0.01},
                'asks_credit_balance': {'noul': 0.01}}))
        self.assertEqual(result, 'design')
        self.assertEqual(rq.post.call_count, 0)

    def test_borderline_design_score_goes_paid_not_local(self):
        # 0.3 is under the old 0.5 coin flip but still means the model saw
        # edit signals — an ambiguous score fails open to the planner.
        result, _, _ = self._route('ممكن تظبط الشكل شوية؟', response=self._fake_response(answers={
            'needs_design_work': {'noul': 0.3}, 'asks_credit_balance': {'noul': 0.1}}))
        self.assertEqual(result, 'design')

    def test_router_is_disabled_by_default(self):
        # The lite model kept swallowing real edit requests — the planner
        # decides every non-canned turn unless a deployment opts back in.
        self.assertFalse(self.module.SPAN_ROUTER_ENABLED)

    def test_no_key_and_disabled_flag_skip_the_provider_call(self):
        with patch.dict(self.module.app.config, {'TESTING': False}), \
                patch.object(self.module, '_has_any_openrouter_key', return_value=False), \
                patch.object(self.module, '_tenant_key_gate', return_value=None), \
                patch.object(self.module, 'requests') as rq:
            self.assertEqual(self.module._designer_span_route('x'), 'design')
        self.assertEqual(rq.post.call_count, 0)
        with patch.object(self.module, 'SPAN_ROUTER_ENABLED', False), \
                patch.object(self.module, 'requests') as rq2:
            self.assertEqual(self.module._designer_span_route('x'), 'design')
        self.assertEqual(rq2.post.call_count, 0)

    def test_metered_span_call_records_the_zero_cost(self):
        result, _, settled = self._route('كيفك', response=self._fake_response(answers={
            'needs_design_work': {'noul': 0.1}}))
        self.assertEqual(result, 'chat')
        self.assertEqual(len(settled), 1)
        event_id, status, usage, generation_id = settled[0]
        self.assertEqual(event_id, 'evt-1')
        self.assertEqual(status, 'ok')
        self.assertEqual(usage['cost_usd'], 0)
        self.assertEqual(usage['prompt_tokens'], 120)
        self.assertEqual(generation_id, 'gen-dec-test')


if __name__ == '__main__':
    unittest.main()
