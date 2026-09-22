


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Land-document extraction jobs: the file-backed land job store
# and the croquis extraction pipeline behind /api/extract-croquis.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _land_job_dir(tenant_id):
    return _job_dir('.land_jobs', tenant_id)


def _land_job_path(tenant_id, job_id):
    return _job_path('.land_jobs', tenant_id, job_id)


def _write_land_job(tenant_id, job_id, payload):
    _write_job('.land_jobs', tenant_id, job_id, payload)


def _read_land_job(tenant_id, job_id):
    return _read_job('.land_jobs', tenant_id, job_id)


def _land_job_worker(app, tenant_id, data, job_id):
    """Run the long land extraction off the HTTP request so the hosting proxy cannot 404 it."""
    with app.app_context():
        _write_land_job(tenant_id, job_id, {
            'status': 'running',
            'success': True,
            'message': 'جاري تحليل المستندات والاشتراطات...',
        })
        try:
            with app.test_request_context('/api/extract-croquis', method='POST', json=data):
                g.tenant_id = tenant_id
                response = _execute_extract_croquis()
            http_status = getattr(response, 'status_code', 500)
            if isinstance(response, tuple):
                http_status = response[1] if len(response) > 1 else 200
                response = response[0]
            payload = response.get_json(silent=True) if response is not None else {}
            if not isinstance(payload, dict):
                payload = {}
            payload.pop('rawText', None)
            status = 'completed' if payload.get('success') else 'failed'
            _write_land_job(tenant_id, job_id, {
                **payload,
                'status': status,
                'httpStatus': http_status,
                'message': payload.get('error') or 'اكتمل التحليل',
            })
        except Exception as exc:
            _write_land_job(tenant_id, job_id, {
                'status': 'failed',
                'success': False,
                'error': f'حدث خطأ في قراءة ملف الكروكي: {exc}',
                'failureReason': 'job_failed',
            })


def _land_document_key(filename, provided=''):
    """Give each uploaded land document a stable kind for the prompt.

    The client tags every file 'land_document', so the filename carries the
    only real signal about whether the model is looking at the croquis, the
    building licence, or the deed — the identity matters because the source
    priority order references it.
    """
    lowered = str(filename or '').casefold()
    if any(token in lowered for token in ('رخصة', 'رخصه', 'licen', 'permit')):
        return 'building_license'
    if any(token in lowered for token in ('كروكي', 'croquis', 'krooki')):
        return 'croquis'
    if any(token in lowered for token in ('صك', 'deed')):
        return 'deed'
    return provided or 'land_document'


@app.route('/api/extract-croquis', methods=['POST'])
@require_permission('create_presentation')
def api_extract_croquis():
    """Accept a land-analysis request.

    The hosting proxy fabricates a 404 if this route stays open for the whole
    vision + regulation pipeline. Production therefore queues the work and
    returns immediately; the client polls GET /api/extract-croquis/<job_id>.
    Tests keep the original synchronous response unless they pass background=true.
    """
    data = request.json or {}
    _billing_guard = _require_billing_balance('croquis')
    if _billing_guard is not None:
        return _billing_guard
    use_background = (not current_app.config.get('TESTING')) or bool(data.get('background'))
    if not use_background:
        return _execute_extract_croquis()
    job_id = str(_uuid.uuid4())
    tenant_id = g.tenant_id
    _write_land_job(tenant_id, job_id, {
        'status': 'queued',
        'success': True,
        'message': 'تم استلام طلب التحليل',
        'payload': {'data': data},
    })
    threading.Thread(
        target=_land_job_worker,
        args=(current_app._get_current_object(), tenant_id, data, job_id),
        daemon=True,
    ).start()
    return jsonify({
        'success': True,
        'jobId': job_id,
        'status': 'queued',
        'message': 'بدأ التحليل في الخلفية',
    }), 202


@app.route('/api/extract-croquis/<job_id>', methods=['GET'])
@require_auth
def api_extract_croquis_job(job_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(job_id or '')):
        return jsonify({'success': False, 'error': 'معرف مهمة غير صالح'}), 400
    job = _read_land_job(g.tenant_id, job_id)
    if not job:
        return jsonify({
            'success': False,
            'error': 'مهمة التحليل غير موجودة',
            'failureReason': 'job_not_found',
        }), 404
    return jsonify(_public_job(job))


def _execute_extract_croquis():
    """Extract one or more land documents together using vision AI."""
    import traceback
    try:
        data = request.json or {}
        location_address = str(
            data.get('locationAddress') or data.get('location_address') or ''
        ).strip()
        try:
            location_lat = float(data.get('locationLat') or data.get('location_lat'))
            location_lng = float(data.get('locationLng') or data.get('location_lng'))
        except (TypeError, ValueError):
            location_lat = location_lng = None
        if (
            not location_address.startswith('http')
            or location_lat is None or location_lng is None
            or not (-90 <= location_lat <= 90)
            or not (-180 <= location_lng <= 180)
        ):
            return jsonify({
                'success': False,
                'error': 'رابط Google Maps صالح وإحداثيات الموقع مطلوبان قبل بدء تحليل الأرض والكروكي',
                'failureReason': 'location_required',
            }), 400
        legacy_file_data = data.get('fileData') or data.get('croquis_file') or ''
        if not data.get('documents') and not legacy_file_data:
            return jsonify({'success': False, 'error': 'يرجى رفع صورة الأرض أو الكروكي أو الرخصة أولاً'}), 400

        site_context, site_context_warnings = build_land_analysis_site_context(
            data, g.tenant_id, location_lat, location_lng)
        regulation_query = ' '.join(str(data.get(key) or '') for key in (
            'zoningCode', 'zoning_code', 'projectType', 'city', 'landUse'
        )).strip()
        project_context_fields = (
            ('اسم المشروع', 'projectName'),
            ('نوع المشروع', 'projectType'),
            ('مرحلة المشروع الحالية', 'projectStage'),
            ('رابط Google Maps', 'locationAddress'),
            ('خط العرض', 'locationLat'),
            ('خط الطول', 'locationLng'),
        )
        project_context_block = '\n'.join(
            f'- {label}: {str(data.get(key) or "").strip() or "غير مدخل"}'
            for label, key in project_context_fields
        ) + '\nبيانات الموقع والخرائط المحللة:\n' + json.dumps(
            site_context, ensure_ascii=False, indent=2, default=str)

        documents = []
        raw_documents = data.get('documents')
        if isinstance(raw_documents, list) and len(raw_documents) > 10:
            return jsonify({'success': False, 'error': 'الحد الأقصى لتحليل الملفات معًا هو 10 ملفات'}), 400
        if isinstance(raw_documents, list):
            for index, item in enumerate(raw_documents):
                if not isinstance(item, dict):
                    continue
                file_data = item.get('fileData') or item.get('data') or ''
                file_id = item.get('fileId')
                if not file_data and file_id:
                    stored = db.get_project_file(g.tenant_id, str(file_id))
                    if stored and stored.get('storage_path') and os.path.isfile(stored['storage_path']):
                        with open(stored['storage_path'], 'rb') as source:
                            encoded = base64.b64encode(source.read()).decode('ascii')
                        file_data = f"data:{stored.get('mime_type') or 'application/octet-stream'};base64,{encoded}"
                if not file_data:
                    continue
                filename = os.path.basename(str(item.get('filename') or item.get('originalName') or f'document_{index + 1}'))
                documents.append({
                    'key': _land_document_key(filename, str(item.get('key') or item.get('fileType') or '')),
                    'filename': filename,
                    'fileData': file_data,
                    'mimeType': item.get('mimeType') or ('application/pdf' if 'application/pdf' in file_data else 'image/*'),
                })
        if not documents:
            file_data = data.get('fileData') or data.get('croquis_file') or ''
            if file_data:
                documents = [{
                    'key': 'croquis',
                    'filename': 'croquis.pdf' if 'application/pdf' in file_data else 'croquis-image',
                    'fileData': file_data,
                    'mimeType': 'application/pdf' if 'application/pdf' in file_data else 'image/*',
                }]
        if not documents:
            return jsonify({'success': False, 'error': 'يرجى رفع صورة الأرض أو الكروكي أو الرخصة أولاً'}), 400

        system_prompt = (
            "أنت مهندس مساح وخبير عقاري ومدقق مستندات تنظيمية. حلل كل الملفات المرفقة معًا، مع الحفاظ على هوية كل ملف ومصدر كل معلومة.\n"
            "ملفا الاشتراطات الرسميان اشتراطات1 واشتراطات2 متاحان لك بمحتواهما الكامل؛ استخدمهما كاملين ولا تعتمد على جزء أو صفحات منتقاة فقط.\n"
            "أعد JSON فقط بدون Markdown. لا تخترع قيمة غير مقروءة؛ استخدم null أو نصًا فارغًا، وسجل التعارضات بدل اختيار قيمة من نفسك.\n"
            "أولوية المصادر إلزامية: جدول التنظيم الرسمي أولًا، ثم أي مرجع تنظيمي رسمي، ثم الكروكي، ثم رخصة البناء. إذا ظهرت جداول متعددة للإحداثيات أو الاتجاهات، استخدم جدول التنظيم واربط كل قيمة بـ source=regulation_table، وسجل البدائل والتعارضات في conflicts.\n"
            "ستجد في مستندات PDF صورة كاملة للصفحة وقصاصات مكبرة عالية الدقة، وقد توجد قصاصات بديلة باتجاه دوران آخر. استخدم النسخة التي يكون النص فيها أفقيًا واضحًا، ولا تعتبر النسخة المقلوبة مصدرًا مستقلًا.\n"
            "إذا وجدت أكثر من قطعة أرض، أعد كل قطعة داخل parcels منفصلة ولا تدمج مساحاتها أو حدودها.\n"
            "استخرج جدول الاتجاهات الأربعة بشكل مستقل من جدول الجهات أو الحدود الذي يوضح «بموجب التنظيم» أولًا، وليس من وصف عام في الرخصة أو الكروكي. اقرأ أسماء الشوارع وعروضها وأطوال الحدود والواجهات من صورة الجدول.\n"
            "بالنسبة للإحداثيات، إذا وجدت أكثر من جدول فافصل الجداول أولًا داخل coordinate_tables، وضع عنوان كل جدول في table_name وصفوفه في rows.\n"
            "الجدول المطلوب حصريًا هو الجدول الذي عنوانه «إحداثيات التنظيم» أو «جدول إحداثيات التنظيم» أو «احداثيات التنظيم». جدول «إحداثيات الموقع» أو «إحداثيات الصك» ليس بديلًا ولا يجوز أخذ أي صف منه.\n"
            "بعد فصل الجداول، انسخ صفوف جدول إحداثيات التنظيم وحده إلى regulation_coordinates ثم إلى survey_coordinates بنفس الترتيب. لا تخلط أو تنتقي صفوفًا من الجدولين.\n"
            "إذا لم تجد جدول إحداثيات التنظيم أو لم يكن عنوانه وصفوفه مقروءة بوضوح، أعد regulation_coordinates وsurvey_coordinates فارغين وسجل تعارضًا يوضح السبب، ولا تستنتج الإحداثيات من الحدود أو الاتجاهات.\n"
            "استخرج من جدول إحداثيات التنظيم كما هو: رقم القطعة، رقم النقطة، الشرقيات، الشماليات، بدون تحويل إلى latitude/longitude أو حساب أي نقطة.\n"
            "الصيغة المطلوبة:\n"
            "{\n"
            '  "parcels": [{\n'
            '    "parcel_id": "P-1", "plot_number": "", "plan_number": "", "subdivision_number": "",\n'
            '    "deed_number": "", "deed_date": "", "area_sqm": null,\n'
            '    "facades_count": null, "facades_directions": "",\n'
            '    "directions": {\n'
            '      "north": {"regulation_text": "", "street_name": "", "street_width_m": null, "boundary_length_m": null, "uses": "", "setback": "", "source": "regulation_table"},\n'
            '      "south": {"regulation_text": "", "street_name": "", "street_width_m": null, "boundary_length_m": null, "uses": "", "setback": "", "source": "regulation_table"},\n'
            '      "east": {"regulation_text": "", "street_name": "", "street_width_m": null, "boundary_length_m": null, "uses": "", "setback": "", "source": "regulation_table"},\n'
            '      "west": {"regulation_text": "", "street_name": "", "street_width_m": null, "boundary_length_m": null, "uses": "", "setback": "", "source": "regulation_table"}\n'
            '    },\n'
            '    "north_direction": "", "setbacks": "", "building_ratio": "", "coverage_ratio": "",\n'
            '    "building_ratio_coverage": "", "floor_area_ratio": "", "table_floors": "", "max_floors_height": "",\n'
            '    "parking_requirements": "", "entrances_exits_requirements": "",\n'
            '    "allowed_uses": "", "regulatory_constraints": "",\n'
            '    "allowed_uses_restrictions": "", "zoning_code": "",\n'
            '    "coordinates": {"lat": null, "lng": null, "source": "", "confidence": ""},\n'
            '    "coordinates_table_name": "إحداثيات التنظيم", "coordinates_table_source_page": "",\n'
            '    "coordinate_tables": [{"table_name": "", "rows": [{"point": "", "eastings": "", "northings": "", "source": ""}]}],\n'
            '    "regulation_coordinates": [{"point": "", "eastings": "", "northings": "", "source": "regulation_table"}],\n'
            '    "survey_coordinates": [{"point": "", "eastings": "", "northings": "", "source": "regulation_table"}],\n'
            '    "confidence": {}, "sources": [], "summary": ""\n'
            '  }],\n'
            '  "coordinate_tables": [], "regulation_coordinates": [],\n'
            '  "survey_coordinates": [], "source_priority": ["regulation_table", "official_regulation", "croquis", "building_license"],\n'
            '  "conflicts": [{"field": "", "description": ""}],\n'
            '  "land_and_building_summary": ""\n'
            "}\n"
            "قواعد إلزامية لأرقام الهوية — لا تخلط بينها أبدًا:\n"
            "- plot_number: رقم قطعة الأرض وحده (مثل 9991). لا تضع فيه رقم المخطط ولا رقم القسم ولا كلمة (قطعة).\n"
            "- plan_number: رقم المخطط وحده (مثل 3/س/125).\n"
            "- subdivision_number: رقم القسم أو الجزء إن وُجد فقط، وإلا اتركه فارغًا. لا تضعه في plot_number.\n"
            "- إذا كان المستند يذكر رقمًا واحدًا فقط ولم يوضح نوعه، اتركه في الحقل المؤكد فقط وسجّل الغموض في conflicts.\n"
             "قواعد إلزامية للصك:\n"
             "- deed_number: رقم الصك رقميًا فقط.\n"
             "- deed_date: تاريخ إصدار الصك كما هو مكتوب (هجري أو ميلادي) بصيغة YYYY/MM/DD، وبيّن نوع التقويم في summary. لا تخلطه مع تاريخ الكروكي أو تاريخ الرخصة.\n"
             "قاعدة حاسمة لمساحة الأرض حسب الكروكي (area_sqm / croquis_land_area):\n"
             "- أخرج فقط المساحة المكتوبة في جدول التنظيم بجوار عبارة «بموجب التنظيم» لكل قطعة. هذه هي مساحة الأرض المعتمدة لهذا الحقل.\n"
             "- إذا وُجدت مساحات متعددة مثل مساحة الصك، أو المساحة المقاسة على الطبيعة، أو الرفع المساحي، أو مساحة حدود مختلفة، فلا تستخدم أيًا منها بدل مساحة «بموجب التنظيم».\n"
             "- استخدم مساحة «بموجب التنظيم» وحدها لاختيار شريحة جدول الاشتراطات، وسجّل أي مساحة أخرى في conflicts أو summary كمعلومة متعارضة فقط.\n"
             "- إذا لم تكن مساحة «بموجب التنظيم» مقروءة بوضوح، اترك area_sqm فارغًا وسجّل ذلك في conflicts، ولا تخمّن أو تحسب مساحة بديلة.\n"
             "قواعد إلزامية للواجهات — الواجهة هي الحد المطل على شارع فقط:\n"
            "- لكل قطعة أربعة حدود دائمًا، لكن الواجهات هي الحدود المطلة على شوارع وحدها. "
            "الحد المجاور لقطعة أو جار ليس واجهة.\n"
            "- facades_count: عدد الحدود المطلة على شوارع فقط، رقم صحيح (1 إلى 4). "
            "يُمنع منعًا تامًا كتابة أي كلمة اتجاه هنا.\n"
            "- facades_directions: اتجاهات تلك الواجهات فقط (مثل: شمالية، غربية). "
            "لا تكتب الاتجاهات الأربعة كلها إلا إذا كانت القطعة فعلًا مطلة على أربعة شوارع.\n"
            "- في directions املأ street_name و street_width_m للحدود المطلة على شوارع، "
            "واذكر في uses أن الحد يجاور قطعة/جار للحدود غير المطلة على شارع.\n"
            "- setback داخل كل اتجاه: الارتداد المخصص لذلك الاتجاه بالمتر. جدول الجهات والحدود في الكروكي أو الرخصة "
            "يحمل غالبًا عمود «الارتداد» لكل جهة — انسخ قيمته لكل اتجاه كما هي (مثل «5م»). وإذا وردت الارتدادات بصيغة "
            "أمامي/خلفي/جانبي، فالأمامي يخص جهة الواجهة على الشارع الرئيسي، والخلفي الجهة المقابلة لها، والجانبي "
            "الجهتين المتبقيتين؛ املأ الاتجاهات المقابلة بهذه القيم وسجّل في conflicts أن الربط استُنتج. "
            "لا تترك setback فارغًا إلا إذا لم يذكر أي مستند ارتدادًا لتلك الجهة.\n"
            "قواعد منع التكرار:\n"
            "- لا تكرر نفس المعلومة في أكثر من حقل. building_ratio_coverage لنسب البناء والتغطية وFAR والأدوار، وsetbacks للارتدادات فقط.\n"
            "- allowed_uses للاستخدامات، وregulatory_constraints للقيود فقط.\n"
            "- أطوال الحدود وأسماء الشوارع تُكتب داخل directions فقط، ولا تُعاد في summary كقائمة.\n"
            "قواعد الاشتراطات — ممنوع إعادة رقم مجرد أو إحالة المستخدم إلى مكان داخل ملف:\n"
            "- zoning_code: كود التنظيم/الاستخدام كما هو في الرخصة أو جدول التنظيم إن وُجد.\n"
            "- building_ratio: اكتب النسبة بجملة كاملة توضّح مجال تطبيقها، ولا تكتب «60%» وحدها. لا تذكر اسم الملف أو رقم الصفحة في القيمة.\n"
            "- coverage_ratio: نسبة التغطية إن ذُكرت منفصلة عن نسبة البناء، وإلا اتركها فارغة ولا تكرر نسبة البناء فيها.\n"
            "- building_ratio_coverage: اجمع نسبة البناء والتغطية وFAR وعدد الأدوار المرتبط بشريحة مساحة الأرض في قيمة مفهومة، بدون إحالات إلى الصفحات.\n"
            "- floor_area_ratio: معامل مسطح البناء (FAR) رقمًا مع شرح نطاق تطبيقه إن وُجد.\n"
            "- table_floors: عدد الأدوار المقابل لمساحة هذه الأرض، مع ذكر شريحة المساحة أو المحور بالكلمات فقط.\n"
            "- setbacks: الارتدادات الأربعة كل واحد برقمه بالمتر (أمامي/خلفي/جانبي أيمن/جانبي أيسر). إن لم تجدها فاكتب «غير محددة في المرجع المتاح» ولا تخترع أرقامًا.\n"
            "- parking_requirements: استخرج اشتراطات المواقف كاملة: العدد أو النسبة، نوع الاستخدام، وأبعاد الموقف أو المسار إن ذُكرت، دون ذكر أرقام الصفحات. إذا لم توجد فاكتب «غير محددة في المرجع المتاح».\n"
            "- entrances_exits_requirements: استخرج اشتراطات مداخل ومخارج السيارات والمشاة والخدمات والتحميل والفصل بين المداخل إن ذُكرت، دون ذكر أرقام الصفحات. إذا لم توجد فاكتب «غير محددة في المرجع المتاح».\n"
            "- allowed_uses: اكتب قائمة الاستخدامات المسموحة تنظيميًا لهذه الأرض من جدول التنظيم وملفي الاشتراطات "
            "(مثل: سكني، تجاري، فندقي، صناعي ولوجستي). لا تكتب حالة توافق نوع المشروع، ولا تكتب «حالة استخدام المشروع». "
            "إذا لم تُستخرج استخدامات واضحة فاكتب «غير محددة في المرجع المتاح».\n"
            "- regulatory_constraints: اذكر القيود التنظيمية المنطبقة على الموقع والمشروع، واجمع فيها المواقف والمداخل والمخارج والتحميل والخدمات عند وجودها، دون تكرار قائمة الاستخدامات.\n"
            "- allowed_uses_restrictions: اجمع allowed_uses وregulatory_constraints للتوافق مع البيانات القديمة فقط.\n"
            "- استخدم مساحة الأرض المستخرجة لاختيار الشريحة الصحيحة من جدول التنظيم؛ الجداول مفتاحها مساحة الأرض ونوع المحور/المنطقة.\n"
            "- لا تنسب اشتراطات إلى مدينة أو أمانة إلا إذا كانت المدينة ومصدر اللائحة واضحين في الملفات أو في المرجع المرفق.\n"
            "- لا تكتب في أي حقل عبارات مثل «صفحة كذا» أو «راجع الملف» أو اسم ملف كمصدر؛ اكتب الاشتراط نفسه مباشرة.\n"
            "قواعد التعارضات (conflicts) — لا تُعرض للمستخدم مباشرة:\n"
            "- عند اختلاف قيمة بين مستندين، سجّل التعارض هنا بجملة واحدة بدل اختيار قيمة من نفسك بصمت.\n"
            "- الشرح المفصّل للتعارض وأثره يُكتب داخل land_and_building_summary في فقرة المخاطر.\n"
            "- إذا لا توجد تعارضات أعد قائمة فارغة.\n"
            "قواعد الملخص (land_and_building_summary):\n"
            "- نص عربي مسترسل من ٣ إلى ٥ فقرات (١٨٠ كلمة على الأقل) وليس قائمة حقول مفصولة بشرطات.\n"
            "- لا تُعد سرد الأرقام التي وردت في الحقول؛ اربطها وحلّلها باختصار.\n"
            "- يغطي بالترتيب: (١) هوية القطعة وموقعها وصكها، (٢) المساحات والحدود والاتجاهات والواجهات، (٣) اشتراطات البناء، (٤) الاستخدامات المسموحة وحالة توافق نوع المشروع، (٥) القيود والمواقف والمداخل والمخارج، (٦) الفرص التطويرية المستنبطة من الاشتراطات، (٧) المخاطر والتعارضات وما يحتاج مراجعة.\n"
            "- يجب أن يذكر الملخص بوضوح الارتدادات والمواقف والمداخل والمخارج حتى لو وردت التفاصيل في الحقول الأخرى.\n"
            "- اربط ملاءمة الاشتراطات بنوع المشروع ومرحلته المدخلين، ولا تستبدلها بتحليل عام منفصل عن المشروع.\n"
            "- لا تذكر أرقام الصفحات أو أسماء الملفات أو مكان الاشتراط داخل الملخص؛ اذكر الاشتراط نفسه مباشرة.\n"
            "- اذكر صراحة أي معلومة غير متوفرة بدل تخطيها بصمت.\n"
            "ملاحظة: لا تُخرج حقل المساحة المعتمدة للدراسة المالية إطلاقًا؛ العميل هو من يحددها."
        )

        raw_resp = ""
        response_finish_reason = None
        model_error = ''
        vision_warnings = list(site_context_warnings)
        document_processing = []
        regulation_evidence_metadata = []
        reg_digest = {'matched': False}
        if _has_any_openrouter_key(_usage_ctx('land', data)):
            vision_parts = []
            document_descriptions = []
            per_document_budget = PDF_VISION_MAX_TOTAL_BYTES // max(1, len(documents))
            for doc in documents:
                try:
                    vision_diagnostics = {}
                    parts, warnings, page_count, mode = _prepare_document_vision_parts(
                        doc, budget=per_document_budget, diagnostics=vision_diagnostics)
                    vision_parts.extend(parts)
                    vision_warnings.extend(warnings)
                    processing = {
                        'filename': doc['filename'],
                        'mode': mode,
                        'page_count': page_count,
                        'dpi': PDF_VISION_DPI if mode == 'pdf_rendered' else None
                    }
                    processing.update({
                        key: vision_diagnostics[key]
                        for key in ('page_rotations', 'rotated_page_count', 'tile_count', 'image_count', 'encoded_base64_bytes')
                        if key in vision_diagnostics
                    })
                    document_processing.append(processing)
                    document_descriptions.append(f"- {doc['key']}: {doc['filename']} ({mode}, {page_count} صفحة/صورة)")
                except Exception as render_error:
                    print(f"[EXTRACT LAND DOCUMENTS RENDER ERROR] {doc['filename']}: {render_error}")
                    return jsonify({
                        'success': False,
                        'error': f'تعذر تجهيز المستند بصريًا: {doc["filename"]}. لم يتم إرسال PDF كملف عادي حتى لا ينتج AI بيانات غير دقيقة.',
                        'documentProcessing': document_processing,
                        'details': str(render_error)
                    }), 422

            request_facts = {
                'zoning_code': data.get('zoningCode') or data.get('zoning_code') or site_context.get('zoning_code') or '',
                'land_use': data.get('landUse') or data.get('land_use') or site_context.get('land_use') or '',
                'city': data.get('city') or site_context.get('city') or '',
                'project_type': data.get('projectType') or '',
                'location_address': data.get('locationAddress') or data.get('location_address') or '',
                'location_lat': data.get('locationLat') or data.get('location_lat') or location_lat,
                'location_lng': data.get('locationLng') or data.get('location_lng') or location_lng,
            }
            facts_prompt = (
                "أنت مستخرج حقائق أولي من صور مستندات الأرض والكروكي. أعد JSON فقط بهذا الشكل: "
                '{"site_facts":{"plot_number":"","area_sqm":null,"zoning_code":"",'
                '"land_use":"","city":"","project_type":"","axis_type":"","building_type":"",'
                '"location_address":"","location_lat":null,"location_lng":null},'
                '"uncertainties":[]} '
                "اقرأ الصور فقط ولا تستخدم أي لائحة أو تخمين. area_sqm يجب أن تكون مساحة «بموجب التنظيم» إن ظهرت، "
                "وإذا لم تكن واضحة اتركها null. هذا استخراج تمهيدي لا يكتب الملخص النهائي."
            )
            facts_payload = [{
                'type': 'text',
                'text': facts_prompt + '\nالمستندات المرفقة:\n' + '\n'.join(document_descriptions)
            }] + vision_parts
            facts_result, facts_cap, facts_error = _run_land_json_stage(
                'site_facts', facts_prompt, facts_payload,
                LAND_FACTS_MAX_TOKENS, LAND_FACTS_MIN_TOKENS, LAND_FACTS_MAX_TOKENS * 2,
                usage_ctx=_usage_ctx('land', data),
            )
            if facts_error:
                vision_warnings.append('تعذر استخراج حقائق الكروكي الأولية؛ تم استخدام بيانات المشروع المدخلة فقط.')
                print(f'[LAND ANALYSIS STAGE ERROR] site_facts cap={facts_cap} {facts_error}')
            site_facts = _extract_land_site_facts(facts_result, request_facts)
            if REGULATION_DIGEST_ENABLED:
                try:
                    reg_digest = regulation_digest.build_regulation_digest(site_facts)
                except Exception as digest_error:
                    reg_digest = {'matched': False}
                    vision_warnings.append(f'تعذر قراءة قاعدة بيانات الاشتراطات الموثقة: {digest_error}')
                    print(f'[REGULATION DIGEST ERROR] {digest_error}')
            evidence_results = []
            if reg_digest.get('matched'):
                regulation_evidence_metadata = [{
                    'name': 'قاعدة بيانات الأنظمة الموثقة (rules/)',
                    'zone': reg_digest.get('zone_key'),
                    'special_plan_required': reg_digest.get('special_plan_required'),
                    'sources': reg_digest.get('sources', []),
                }]
                print(f"[REGULATION DIGEST] zone={reg_digest.get('zone_key')} "
                      f"fields={sorted(reg_digest.get('fields') or {})} "
                      f"special={reg_digest.get('special_plan_required')}")
            else:
                regulation_query = ' '.join(str(value) for value in site_facts.values() if value not in (None, ''))
                try:
                    evidence_package, evidence_warnings = search_official_regulations_evidence(
                        regulation_query, site_facts)
                except Exception as evidence_error:
                    evidence_package = {'context': '', 'documents': [], 'table_pages': []}
                    evidence_warnings = [f'تعذر تجهيز أدلة الاشتراطات: {evidence_error}']
                vision_warnings.extend(evidence_warnings)
                for source in evidence_package.get('documents', []):
                    source_name = source.get('name') or 'ملف اشتراطات'
                    source_tables = [
                        entry for entry in evidence_package.get('table_pages', [])
                        if entry.get('name') == source_name
                    ]
                    source_for_evidence = {**source, 'table_pages': source_tables}
                    extracted_evidence = _extract_full_regulation_evidence(
                        source_for_evidence, site_facts, usage_ctx=_usage_ctx('land', data))
                    vision_warnings.extend(extracted_evidence.get('warnings', []))
                    if not extracted_evidence.get('evidence') and not extracted_evidence.get('uncertainties'):
                        if not source.get('context') and not source_tables:
                            vision_warnings.append(f'لم يتوفر محتوى قابل للقراءة في {source_name}؛ لن يتم تخمين اشتراطاته.')
                        evidence_results.append({
                            'source_file': source_name,
                            'evidence': {},
                            'error': 'لا يوجد محتوى قابل للقراءة أو تعذر استخراج أدلة',
                        })
                        continue
                    evidence_results.append({
                        'source_file': source_name,
                        'evidence': extracted_evidence.get('evidence', []),
                        'uncertainties': extracted_evidence.get('uncertainties', []),
                    })
                regulation_evidence_metadata = [
                    {
                        'name': source.get('name'),
                        'text_pages': source.get('text_pages', []),
                        'table_pages': source.get('table_pages', []),
                    }
                    for source in evidence_package.get('documents', [])
                ]
                print(
                    f"[REGULATION EVIDENCE] documents={len(regulation_evidence_metadata)} "
                    f"text_chars={sum(len(source.get('context') or '') for source in evidence_package.get('documents', []))} "
                    f"table_pages={len(evidence_package.get('table_pages', []))}"
                )

            if reg_digest.get('matched'):
                instructions = (
                    "لديك نوعان من المدخلات، لا تخلط بينهما:\n"
                    "١) مستندات العميل (الصك/الكروكي/الرخصة): مُرسلة صورًا عالية الدقة. اقرأها بصريًا فقط "
                    "ولا تعتمد على OCR أو نص مستخرج، واقرأ جداولها من الصورة نفسها.\n"
                    "٢) بلوك اشتراطات موثق مختار حتميًا من قاعدة بيانات الأنظمة المبنية على ملفي الاشتراطات. "
                    "قيمه الرقمية ملزمة: استخدمها حرفيًا ولا تخترع قاعدة غير موجودة فيه.\n"
                    "أولوية جدول التنظيم الرسمية مطلقة عند التعارض، وخاصة لجدول الإحداثيات وجدول الاتجاهات. "
                    "لا تخلط بين شرقيات/شماليات المساحية وبين latitude/longitude. لا تذكر أرقام الصفحات أو أسماء الملفات في أي قيمة للمستخدم.\n"
                )
                regulation_block = regulation_digest.digest_prompt_block(reg_digest) + "\n\n"
            else:
                instructions = (
                    "لديك نوعان من المدخلات، لا تخلط بينهما:\n"
                    "١) مستندات العميل (الصك/الكروكي/الرخصة): مُرسلة صورًا عالية الدقة. اقرأها بصريًا فقط "
                    "ولا تعتمد على OCR أو نص مستخرج، واقرأ جداولها من الصورة نفسها.\n"
                    "٢) نتائج استخلاص مبنية على المحتوى الكامل لملفي اشتراطات1 واشتراطات2، بما في ذلك جداول كل ملف. "
                    "استخدم القواعد التي تنطبق على حقائق الموقع فقط، ولا تخترع قاعدة غير موجودة في المحتوى الكامل.\n"
                    "أولوية جدول التنظيم الرسمية مطلقة عند التعارض، وخاصة لجدول الإحداثيات وجدول الاتجاهات. "
                    "لا تخلط بين شرقيات/شماليات المساحية وبين latitude/longitude. لا تذكر أرقام الصفحات أو أسماء الملفات في أي قيمة للمستخدم.\n"
                )
                regulation_block = (
                    "نتائج استخلاص الاشتراطات من المحتوى الكامل للملفين:\n"
                    + json.dumps(evidence_results, ensure_ascii=False)
                    + "\n\n"
                    if evidence_results else
                    "تنبيه: لم تتوفر نتائج قابلة للاستخدام من الملفين كاملين. لا تخترع اشتراطات، وسجّل ذلك في conflicts.\n\n"
                )
            user_content = [{
                "type": "text",
                "text": instructions
                        + "بيانات المعلومات الأساسية ورؤية المشروع التي أدخلها العميل:\n"
                        + project_context_block + "\n\n"
                        + "حقائق الموقع الأولية المستخرجة من الكروكي:\n"
                        + json.dumps(site_facts, ensure_ascii=False) + "\n\n"
                        + "استخدم هذه البيانات كسياق فعلي لربط الملخص بالمشروع، ولا تنسبها إلى الصك أو الكروكي أو اللائحة إذا لم يذكر مصدرها.\n\n"
                        + regulation_block
                        + "مستندات العميل المرفقة:\n" + "\n".join(document_descriptions)
            }] + vision_parts

            try:
                res, used_cap, provider_error = _call_land_analysis_model(
                    system_prompt, user_content, LAND_ANALYSIS_MAX_TOKENS,
                    usage_ctx=_usage_ctx('land', data))
                if _has_chat_choices(res):
                    raw_resp = _get_chat_response_text(res)
                    choices = res.get('choices') if isinstance(res, dict) else []
                    response_finish_reason = choices[0].get('finish_reason') if choices and isinstance(choices[0], dict) else None
                    print(f"[EXTRACT LAND DOCUMENTS] analyzed {len(documents)} document(s), "
                          f"cap={used_cap}, finish_reason={response_finish_reason}, chars={len(raw_resp)}")
                else:
                    model_error = provider_error
                    print(f"[EXTRACT LAND DOCUMENTS ERROR] cap={used_cap} {provider_error}")
            except Exception as model_err:
                model_error = str(model_err)
                print(f"[EXTRACT LAND DOCUMENTS EXCEPTION] {model_err}")

        # Partial JSON is never accepted: half a parcel is worse than no parcel. But the failure
        # must say so plainly, otherwise a rejected re-analysis just looks like "nothing changed".
        if response_finish_reason == 'length':
            print(f"[EXTRACT LAND DOCUMENTS TRUNCATED] {len(raw_resp)} chars at cap {used_cap}")
            return jsonify({
                'success': False,
                'error': (f'انقطعت استجابة الذكاء الاصطناعي عند الحد الأقصى ({used_cap} رمز) '
                          'فلم يُعتمد أي حقل، ولهذا لم تتغير البيانات. أعد المحاولة، '
                          'أو ارفع LAND_ANALYSIS_MAX_TOKENS إن تكرر ذلك.'),
                'failureReason': 'truncated',
                'documentProcessing': document_processing
            }), 503
        if not raw_resp.strip():
            # Report what the provider actually said. "Check your API keys" was misleading when the
            # real cause was an insufficient credit balance for the reserved max_tokens.
            insufficient_credit = 'afford' in model_error or 'credit' in model_error.lower()
            blocked_format = bool(_JSON_MODE_BLOCK_RE.search(model_error or ''))
            if insufficient_credit:
                message = ('رصيد OpenRouter لا يكفي لهذا الطلب، فلم يُعتمد أي حقل ولم تتغير البيانات. '
                           'أضف رصيدًا أو قلّل LAND_ANALYSIS_MAX_TOKENS.')
                return jsonify({
                    'success': False,
                    'error': message,
                    'failureReason': 'insufficient_credit',
                    'providerError': model_error,
                    'documentProcessing': document_processing
                }), 503
            if blocked_format:
                message = ('مزوّد الذكاء الاصطناعي رفض صيغة JSON الإجبارية، فلم يُعتمد أي حقل ولم تتغير البيانات. '
                           f'سبب المزوّد: {model_error}')
                return jsonify({
                    'success': False,
                    'error': message,
                    'failureReason': 'provider_blocked',
                    'providerError': model_error,
                    'documentProcessing': document_processing
                }), 503
            if model_error:
                message = f'لم يرد الذكاء الاصطناعي بأي محتوى فلم تتغير البيانات. سبب المزوّد: {model_error}'
            else:
                message = ('لم يرد الذكاء الاصطناعي بأي محتوى، فلم تتغير البيانات. '
                           'تأكد من مفاتيح API ثم أعد المحاولة.')
            return jsonify({
                'success': False,
                'error': message,
                'failureReason': 'empty_response',
                'providerError': model_error,
                'documentProcessing': document_processing
            }), 503
        parsed_response = parse_json_object(raw_resp)
        if parsed_response and reg_digest.get('matched'):
            _apply_regulation_digest_fields(parsed_response, reg_digest)
        if not parsed_response:
            print(f"[EXTRACT LAND DOCUMENTS UNPARSEABLE] first 400 chars: {raw_resp[:400]}")
            return jsonify({
                'success': False,
                'error': 'استجابة الذكاء الاصطناعي ليست JSON صالحًا، فلم يُعتمد أي حقل ولم تتغير البيانات.',
                'failureReason': 'invalid_json',
                'providerError': raw_resp[:400],
                'documentProcessing': document_processing
            }), 503
        resp_json = _normalize_land_document_result(
            parsed_response,
            raw_resp,
            project_type=str(data.get('projectType') or data.get('project_type') or '').strip(),
        )
        if vision_warnings:
            resp_json['warnings'] = vision_warnings
        resp_json['document_processing'] = document_processing
        resp_json['regulation_evidence'] = regulation_evidence_metadata
        extraction_diagnostics = _build_land_extraction_diagnostics(resp_json, document_processing)
        resp_json['extraction_diagnostics'] = extraction_diagnostics
        print(
            '[EXTRACT LAND DOCUMENTS TABLES] '
            f"coordinates={extraction_diagnostics['coordinates_rows']} "
            f"complete_coordinates={extraction_diagnostics['coordinates_complete_rows']} "
            f"directions={extraction_diagnostics['directions_with_values']}/4 "
            f"conflicts={extraction_diagnostics['conflict_count']}"
        )

        # Check if there are actual non-empty values extracted
        parcels = resp_json.get('parcels') if isinstance(resp_json, dict) else []
        has_scalar_values = bool(parcels) and any(
            any(value not in (None, '', [], {}) for key, value in parcel.items() if key not in {'parcel_id', 'directions', 'coordinates', 'confidence', 'sources'})
            for parcel in parcels if isinstance(parcel, dict)
        )
        has_table_values = bool(extraction_diagnostics['coordinates_rows'] or extraction_diagnostics['directions_with_values'])
        has_non_empty_values = bool(raw_resp.strip()) and bool(parcels) and (has_scalar_values or has_table_values)

        if not resp_json or not has_non_empty_values:
            print(f"[CROQUIS DEBUG RAW RESP]\n{raw_resp}")
            return jsonify({'success': False, 'error': f'لم يتم التوصل لبيانات مؤكدة في الصورة أو المستند المرفق. يرجى التأكد من وضوح الصورة.'})

        return jsonify({'success': True, 'extractedData': resp_json, 'rawText': raw_resp, 'documentProcessing': document_processing})
    except Exception as exc:
        err_msg = traceback.format_exc()
        print(f"[EXTRACT CROQUIS ERROR]\n{err_msg}")
        return jsonify({'success': False, 'error': f'حدث خطأ في قراءة ملف الكروكي: {str(exc)}'})
