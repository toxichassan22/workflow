class MeetingRequirementsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'meeting-requirements.db')

        # Import only after redirecting DB_PATH: app.py initializes its database at import time.
        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        # Training-image bytes written by this suite stay in the temporary folder.
        cls.application_module.UPLOADS_DIR = os.path.join(cls.temp_dir.name, 'uploads')

        with cls.app.app_context():
            # The suite is split into ordered part classes; each subclass gets a
            # fresh DB_PATH, and app import (which creates the schema) is cached
            # after the first one — so the schema is created explicitly here.
            db.init_db()
            cls.tenant_a = db.create_tenant('Company A', 'a@example.test', 'hash-a', 'company-a')
            cls.tenant_b = db.create_tenant('Company B', 'b@example.test', 'hash-b', 'company-b')

        cls.token_a = auth.create_token(
            cls.tenant_a, 'a@example.test', user_id=None, user_name='Company A', user_role='company_admin'
        )
        cls.token_b = auth.create_token(
            cls.tenant_b, 'b@example.test', user_id=None, user_name='Company B', user_role='company_admin'
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    @staticmethod
    def _headers(token):
        return {'Authorization': f'Bearer {token}'}

    FULL_PROJECT = {
        'project_name': 'THE VIEW',
        'project_type': ['سكني', 'فندقي'],
        'project_idea': 'برج على كورنيش جدة يجمع الشقق السكنية والغرف الفندقية.',
        'target_audience': {'audience::سكني': ['أصحاب الثروات'], 'audience::فندقي': ['سياح الأعمال']},
        'location_address': 'https://maps.google.com/?q=21.6,39.1',
        'location_lat': '21.6', 'location_lng': '39.1', 'city': 'جدة', 'district': 'الشاطئ',
        'main_roads': 'طريق الكورنيش — 1.6 كم',
        'secondary_roads': 'شارع غير نافذ 20م',
        'nearby_landmarks': 'ريد سي مول — 1.9 كم — 4 دقائق',
        'city_landmarks': 'جدة التاريخية — 21.9 كم',
        'catchment_areas': 'مطار الملك عبدالعزيز — 25.9 كم — 37 دقائق',
        'croquis_land_area': '7012',
        'approved_financial_area': '7012',
        'building_ratio_coverage': 'نسبة البناء 400% والتغطية 60%',
        'setbacks': 'ارتداد أمامي 6م',
        'allowed_uses': 'سكني وفندقي وتجاري',
        'regulatory_constraints': 'مواقف بمعدل موقف لكل وحدة',
        'land_and_building_summary': 'ملخص الأرض والمبنى المعتمد.',
        'timeline_table_data': json.dumps([{
            'name': 'التصميم', 'year': '2026', 'quarter': 'Q1', 'duration': '6',
            'endYear': '2026', 'endQuarter': 'Q3', 'notes': 'يشمل الاعتمادات',
        }], ensure_ascii=False),
        'financial_study_model': json.dumps({
            'inputs': {'projectCost': 480000000, 'roi': '18%'},
            'dynamicRows': {'components': [{'name': 'شقق سكنية', 'useType': 'سكني',
                                            'units': 120, 'builtArea': 24000}]},
        }, ensure_ascii=False),
        'market_study_data': json.dumps({
            'one_block_summary': 'تعريف السوق: قطاع الضيافة الفاخرة في جدة.',
            'competitors': [{
                'id': 'c1', 'name': 'فور سيزونز جدة', 'price_value': '9700000',
                'field_sources': {'name': ['https://example.test/a']},
                'source_urls': ['https://example.test/a'],
            }],
            'swot': {'strengths': 'موقع بحري مباشر'},
            'decision': 'فرصة جاذبة',
        }, ensure_ascii=False),
        'executive_content': json.dumps({
            'brief': 'نبذة المشروع المعتمدة.',
            'opportunity': 'الفرصة الاستثمارية المعتمدة.',
            'features': 'الميزات المعتمدة.',
            'risks': 'خطر التأخير ومعالجته بجدول ملزم.',
            'summary': 'الملخص التنفيذي المعتمد للمشروع.',
        }, ensure_ascii=False),
        'team_selection': json.dumps({
            'excluded': [], 'roles': {},
            'local': [{'localId': 'l1', 'name': 'مكتب تصميم محلي', 'role': 'التصميم المعماري'}],
        }, ensure_ascii=False),
        # Noise the model must never receive.
        'tenantSlidesData': [{'title': 'شريحة سابقة',
                              'html': '<div class="slide">ديك قديم</div>'}],
        'pageDrafts': {'slides': {'generated': True}},
        'visual_concept': {'slots': {'cover': {'prompt': 'Cinematic wide-angle shot'}}},
        'tenantCreativeImages': {'cover': '/uploads/creative/a.jpg'},
        'land_documents_files_file_meta': [{'id': 'f1', 'originalName': 'krooki.pdf'}],
        'survey_coordinates': json.dumps([{'eastings': '511085.849', 'northings': '2392264.840'}]),
    }

    def _persisted_map_fixture(self, module, presentation_id, image_type='landmarks',
                               content=b'map-bytes'):
        maps_dir = Path(module.maps_service.MAPS_DIR)
        maps_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            dir=maps_dir, suffix='_%s.png' % image_type, delete=False)
        handle.write(content)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        with self.app.app_context():
            db.add_map_image(
                self.tenant_a, image_type, handle.name, '##MAP_%s##' % image_type.upper(),
                presentation_id=presentation_id, metadata={})
            marks = module._persisted_map_source_marks(
                self.tenant_a, presentation_id=presentation_id)
        return handle.name, marks

    def _multi_page_executive_draft(self):
        block = 'نص معتمد مفصل يغطي هذا القسم بالكامل مع أرقام ومؤشرات وإسقاطات مالية. ' * 14
        summary = '\n\n'.join(
            f'{label}\n\n{block}' for label in (
                'البيانات الأساسية', 'الموقع', 'الأرض والاشتراطات', 'الجدول الزمني',
                'الدراسة المالية', 'فريق العمل', 'دراسة السوق', 'الخلاصة'))
        opportunity = ' '.join(
            f'الجملة المعتمدة رقم {i} تصف جانباً استثمارياً فريداً للمشروع بإسهاب '
            'مع تفاصيل مالية وتشغيلية ممتدة تجعل كل جملة طويلة بما يكفي لملء الصفحة.'
            for i in range(80))
        features = ' - '.join(f'ميزة تنافسية مرقمة {i} للمشروع' for i in range(20))
        return {'project_name': 'مشروع', 'executive_content': json.dumps(
            {'summary': summary, 'opportunity': opportunity, 'features': features},
            ensure_ascii=False)}
