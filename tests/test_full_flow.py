import os
import sys
import json
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app
import db
from app import app as flask_app


def mock_call_zai_chat(system_prompt, user_content, temperature=0.7, max_tokens=8000):
    if max_tokens == 4000:
        return {
            'choices': [
                {
                    'message': {
                        'content': json.dumps({
                            'proposed_count': 8,
                            'reasoning': 'Test plan',
                            'slides': [
                                {'title': 'غلاف', 'type': 'cover', 'bullets': []},
                                {'title': 'فهرس', 'type': 'index', 'bullets': []},
                                {'title': 'المحتوى 1', 'type': 'content', 'design_style': 'cards', 'bullets': ['نقطة 1', 'نقطة 2', 'نقطة 3']},
                                {'title': 'المحتوى 2', 'type': 'content', 'design_style': 'cards', 'bullets': ['نقطة 1', 'نقطة 2', 'نقطة 3']},
                                {'title': 'المحتوى 3', 'type': 'content', 'design_style': 'cards', 'bullets': ['نقطة 1', 'نقطة 2', 'نقطة 3']},
                                {'title': 'المحتوى 4', 'type': 'content', 'design_style': 'cards', 'bullets': ['نقطة 1', 'نقطة 2', 'نقطة 3']},
                                {'title': 'المحتوى 5', 'type': 'content', 'design_style': 'cards', 'bullets': ['نقطة 1', 'نقطة 2', 'نقطة 3']},
                                {'title': 'ختام', 'type': 'closing', 'bullets': []},
                            ]
                        }, ensure_ascii=False)
                    }
                }
            ]
        }
    return {
        'choices': [
            {
                'message': {
                    'content': '<div class="slide" style="width:1280px;height:720px;background:#FBFAF8;color:#333;"><h1>Test Slide</h1></div>'
                }
            }
        ]
    }


def make_json(resp):
    return resp.get_json() or {}


def test_flow():
    app.call_zai_chat = mock_call_zai_chat

    client = flask_app.test_client()

    uid = uuid.uuid4().hex[:8]
    email = f'test-{uid}@example.com'
    password = 'password123456'
    company = f'Test Co {uid}'

    # Register
    print('--- Registering...')
    r = client.post('/api/auth/register', json={'companyName': company, 'email': email, 'password': password})
    assert r.status_code == 201, make_json(r)
    data = make_json(r)
    assert data['success']
    token = data['token']

    # Login
    print('--- Logging in...')
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, make_json(r)
    token = make_json(r)['token']

    headers = {'Authorization': f'Bearer {token}'}

    # Branding
    print('--- Fetching branding...')
    r = client.get('/api/branding', headers=headers)
    assert r.status_code == 200, make_json(r)
    branding = make_json(r)['branding']
    assert branding['tenant_id'] == make_json(r)['branding']['tenant_id']

    print('--- Updating branding...')
    r = client.put('/api/branding', headers=headers, json={'primary_color': '#1a1a1a', 'accent_color': '#d4af37'})
    assert r.status_code == 200, make_json(r)
    branding = make_json(r)['branding']
    assert branding['primary_color'] == '#1a1a1a'

    # Custom field
    print('--- Adding custom field...')
    r = client.post('/api/fields', headers=headers, json={'fieldKey': 'site_notes', 'fieldLabel': 'ملاحظات الموقع', 'fieldType': 'textarea', 'isRequired': True})
    assert r.status_code == 201, make_json(r)

    r = client.get('/api/fields', headers=headers)
    assert r.status_code == 200, make_json(r)
    fields = make_json(r)['fields']
    assert any(f['fieldKey'] == 'site_notes' for f in fields)

    # Slide plan
    project_data = {'project_name': 'مشروع تجريبي', 'location': 'الرياض', 'project_type': 'فلل'}
    print('--- Generating slide plan...')
    r = client.post('/api/slide-plan', headers=headers, json={'projectData': project_data})
    assert r.status_code == 200, make_json(r)
    plan = make_json(r)['plan']
    assert len(plan['slides']) == 8

    # Generate slides
    print('--- Generating slides HTML...')
    r = client.post('/api/generate-slides', headers=headers, json={'projectData': project_data, 'slidePlan': plan})
    assert r.status_code == 200, make_json(r)
    slides = make_json(r)['slides']
    assert len(slides) == 8
    assert all('slide' in s['html'] for s in slides)

    # Save presentation
    print('--- Saving presentation...')
    r = client.post('/api/presentations', headers=headers, json={'title': 'عرض تجريبي', 'projectData': project_data, 'slidesData': slides, 'slideCount': len(slides)})
    assert r.status_code == 201, make_json(r)
    pres_id = make_json(r)['presentationId']

    # Export PPTX
    print('--- Exporting PPTX...')
    r = client.post('/api/export', headers=headers, json={'format': 'pptx', 'presentationId': pres_id, 'projectName': 'عرض تجريبي', 'slidesData': slides})
    assert r.status_code == 200, make_json(r)
    pptx = make_json(r)
    assert pptx['success']
    pptx_url = pptx['url']

    print('--- Fetching PPTX file...')
    r = client.get(pptx_url, headers=headers)
    assert r.status_code == 200
    assert r.data[:4] == b'PK\x03\x04'

    # Export PDF
    slides_html = '\n'.join(s['html'] for s in slides)
    print('--- Exporting PDF...')
    r = client.post('/api/export', headers=headers, json={'format': 'pdf', 'presentationId': pres_id, 'projectName': 'عرض تجريبي', 'slidesData': slides, 'slidesHtml': slides_html})
    assert r.status_code == 200, make_json(r)
    pdf = make_json(r)
    assert pdf['success']
    pdf_url = pdf['url']

    print('--- Fetching PDF file...')
    r = client.get(pdf_url, headers=headers)
    assert r.status_code == 200
    assert r.data[:4] == b'%PDF'

    # Lists
    r = client.get('/api/presentations', headers=headers)
    assert r.status_code == 200
    assert len(make_json(r)['presentations']) >= 1

    print('--- Fetching exports list...')
    r = client.get('/api/exports', headers=headers)
    assert r.status_code == 200
    assert len(make_json(r)['exports']) >= 2

    # Tenant isolation
    uid2 = uuid.uuid4().hex[:8]
    email2 = f'test-{uid2}@example.com'
    print('--- Registering tenant 2...')
    r = client.post('/api/auth/register', json={'companyName': f'Other {uid2}', 'email': email2, 'password': password})
    assert r.status_code == 201
    token2 = make_json(r)['token']
    headers2 = {'Authorization': f'Bearer {token2}'}

    r = client.get('/api/presentations', headers=headers2)
    assert r.status_code == 200
    other_presentations = make_json(r)['presentations']
    assert not any(p['id'] == pres_id for p in other_presentations)

    print('--- Fetching PDF file with tenant 2 (should fail)...')
    r = client.get(pdf_url, headers=headers2)
    assert r.status_code == 404

    # Admin panel
    import auth
    with flask_app.app_context():
        admin_email = f'admin-{uid}@example.com'
        admin_id = db.create_tenant(f'Admin {uid}', admin_email, auth.hash_password('adminpass123456'))
        db.update_tenant(admin_id, is_active=1)
        db.get_db().execute('UPDATE tenants SET is_admin = 1 WHERE id = ?', (admin_id,))
        db.get_db().commit()

    print('--- Logging in admin...')
    r = client.post('/api/auth/login', json={'email': admin_email, 'password': 'adminpass123456'})
    assert r.status_code == 200, make_json(r)
    admin_token = make_json(r)['token']
    admin_headers = {'Authorization': f'Bearer {admin_token}'}

    print('--- Fetching admin stats...')
    r = client.get('/api/admin/stats', headers=admin_headers)
    assert r.status_code == 200, make_json(r)
    assert 'stats' in make_json(r)

    print('--- Fetching admin tenants...')
    r = client.get('/api/admin/tenants', headers=admin_headers)
    assert r.status_code == 200, make_json(r)
    tenants = make_json(r)['tenants']
    assert any(t['email'] == email for t in tenants)
    assert any(t['email'] == email2 for t in tenants)

    print('ALL TESTS PASSED')


if __name__ == '__main__':
    test_flow()
