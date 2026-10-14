"""Stale-state hygiene for the designer AI surfaces.

Two server-side «cache» leaks used to feed the model conflicting data: frozen
drift-check snapshots embedded inside stored blobs (parkingSnapshot,
sourceSnapshot, planContext…) arriving verbatim beside the live values, and a
stored designerChat stamped for one presentation leaking its memory into
another presentation of the same draft.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch


def slide(inner, title='شريحة', slide_type='content'):
    return {'title': title, 'type': slide_type,
            'html': f'<div class="slide" style="width:1280px;height:720px;">{inner}</div>'}


class DesignerStaleStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import auth
        import db
        cls.temp = tempfile.TemporaryDirectory()
        cls.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp.name, 'designer-stale.db')
        import app
        cls.module = app
        cls.app = app.app
        cls.app.config.update(TESTING=True)
        cls.previous_uploads = app.UPLOADS_DIR
        app.UPLOADS_DIR = os.path.join(cls.temp.name, 'uploads')
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant('Stale', 'stale@example.test', 'hash', 'stale-slug')
        cls.token = auth.create_token(cls.tenant, 'stale@example.test', user_id=None,
                                      user_name='Admin', user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        import db
        cls.module.UPLOADS_DIR = cls.previous_uploads
        db.DB_PATH = cls.previous_db_path
        cls.temp.cleanup()

    def post(self, payload):
        return self.app.test_client().post(
            '/api/designer-chat',
            headers={'Authorization': 'Bearer ' + self.token},
            json=payload)

    # ── get_project_data tool ────────────────────────────────────────────────

    def test_get_project_data_tool_strips_stored_snapshots(self):
        """The planner's read tool used to dump stored blobs verbatim, so the
        frozen parking snapshot answered «الأدوار 10» next to the live «12»."""
        model = {'inputs': {'floorCount': 12, 'landArea': 5000},
                 'parkingSnapshot': {'floorCount': 10, 'landArea': 5000},
                 'parkingPlan': {'id': 'plan-1',
                                 'sourceSnapshot': {'floorCount': 10},
                                 'sourceHash': 'hash-1',
                                 'components': [{'name': 'مواقف'}]}}
        ctx = {'slides': [],
               'request_project_data': {'financial_study_model': model},
               'presentation': None, 'tenant_id': self.tenant,
               'project_data': {}, 'superseded_numbers': set()}
        with self.app.app_context():
            text, image = self.module._agent_tool_result(
                'get_project_data', {'keys': ['financial_study_model']}, ctx, None)
        self.assertIsNone(image)
        fields = {f['key']: f['value'] for f in json.loads(text)['fields']}
        self.assertIn('financial_study_model', fields)
        rendered = fields['financial_study_model']
        self.assertNotIn('parkingSnapshot', rendered)
        self.assertNotIn('sourceSnapshot', rendered)
        self.assertNotIn('sourceHash', rendered)
        self.assertIn('12', rendered)
        self.assertNotIn('10', rendered)

    # ── stored designerChat scoping ──────────────────────────────────────────

    def _chat_payload(self, presentation_id):
        return {'message': 'سلام', 'presentationId': presentation_id,
                'slidesData': [slide('<p>أ</p>')],
                'projectData': {'project_name': 'P'}, 'slideIndex': 0,
                'history': []}

    def test_stored_chat_from_another_presentation_does_not_leak(self):
        """The merged draft keeps whichever presentation's chat saved last; a
        chat stamped for another presentation must not feed this session."""
        foreign = {'presentationId': 'pres-2', 'memory': 'FOREIGN_MEMORY',
                   'messages': [{'role': 'user', 'content': 'FOREIGN_TURN',
                                 'slides': []}]}
        presentation = {'id': 'pres-1', 'draft_id': 'd1',
                        'project_data': {'project_name': 'P'},
                        'slides_data': '[]', 'tenant_id': self.tenant}
        draft = {'draft_data': {'project_name': 'P', 'designerChat': foreign}}
        with patch.object(self.module.db, 'get_presentation', return_value=presentation), \
                patch.object(self.module.db, 'get_project_draft_by_id', return_value=draft):
            response = self.post(self._chat_payload('pres-1'))
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        self.assertEqual(body['action'], 'chat_only')
        contents = [m['content'] for m in body['chatHistory']]
        self.assertNotIn('FOREIGN_TURN', contents)
        self.assertNotEqual(body.get('memory'), 'FOREIGN_MEMORY')

    def test_stored_chat_for_same_presentation_still_loads(self):
        """Scoping must not throw away the presentation's own conversation."""
        stored = {'presentationId': 'pres-1', 'memory': 'KEPT_MEMORY',
                  'messages': [{'role': 'user', 'content': 'KEPT_TURN',
                                'slides': []}]}
        presentation = {'id': 'pres-1', 'draft_id': 'd1',
                        'project_data': {'project_name': 'P', 'designerChat': stored},
                        'slides_data': '[]', 'tenant_id': self.tenant}
        draft = {'draft_data': {'project_name': 'P'}}
        with patch.object(self.module.db, 'get_presentation', return_value=presentation), \
                patch.object(self.module.db, 'get_project_draft_by_id', return_value=draft):
            response = self.post(self._chat_payload('pres-1'))
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()['data']
        contents = [m['content'] for m in body['chatHistory']]
        self.assertIn('KEPT_TURN', contents)
        self.assertEqual(body.get('memory'), 'KEPT_MEMORY')


if __name__ == '__main__':
    unittest.main()
