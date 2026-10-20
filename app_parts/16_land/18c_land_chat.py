# ━━━ Scoped Q&A chat for the land/croquis section ━━━
#
# One-shot chat endpoint: the model answers questions about the parcel only from
# the recorded land data (section fields, document analysis, verified regulation
# facts). When a value is not in the data or is uncertain, the prompt forces the
# reply to say so instead of guessing — «لا تضليل». It may suggest field edits
# as grounded guidance, but it never applies them — the client owns every change.
from numeric_precision import format_precise_number

import chat_memory


LAND_CHAT_FIELD_LABELS = (
    ('project_name', 'اسم المشروع'),
    ('project_type', 'نوع المشروع'),
    ('project_subtype', 'الأنواع الفرعية للمشروع'),
    ('project_stage', 'مرحلة المشروع الحالية'),
    ('city', 'المدينة'),
    ('district', 'الحي'),
    ('croquis_land_area', 'مساحة الأرض حسب الكروكي (م²)'),
    ('approved_financial_area', 'المساحة المعتمدة للدراسة المالية (م²)'),
    ('plot_number_croquis', 'رقم القطعة'),
    ('plan_number', 'رقم المخطط'),
    ('subdivision_number', 'رقم القسم'),
    ('deed_number', 'رقم الصك أو المرجع'),
    ('deed_date', 'تاريخ الصك'),
    ('boundary_lengths', 'أطوال الأضلاع وحدود الأرض'),
    ('surrounding_streets', 'الشوارع المحيطة وعروضها'),
    ('north_direction', 'اتجاه الشمال'),
    ('facades_count', 'عدد الواجهات المطلة على شوارع'),
    ('facades_directions', 'اتجاهات الواجهات'),
    ('zoning_code', 'كود التنظيم'),
    ('land_use', 'استخدام الأرض'),
    ('building_ratio_coverage', 'نسبة البناء والتغطية'),
    ('setbacks', 'الارتدادات'),
    ('building_ratio_setbacks', 'نسب البناء والارتدادات'),
    ('max_floors_height', 'الارتفاع أو عدد الأدوار المسموح'),
    ('approved_floor_count', 'الأدوار المعتمدة'),
    ('approved_coverage_ratio', 'تغطية البناء (%)'),
    ('approved_floor_area_ratio', 'معامل مسطح البناء المعتمد (FAR)'),
    ('approved_typical_floor_coverage', 'التغطية للطوابق المتكررة (%)'),
    ('allowed_uses', 'الاستخدامات المسموحة'),
    ('allowed_uses_restrictions', 'الاستخدامات والقيود التنظيمية المسجلة'),
    ('parking_requirements', 'اشتراطات المواقف'),
    ('entrances_exits_requirements', 'اشتراطات المداخل والمخارج'),
    ('land_use_status', 'حالة استخدام المشروع'),
    ('regulatory_constraints', 'القيود التنظيمية'),
    ('land_and_building_summary', 'ملخص بيانات الأرض والاشتراطات'),
)

LAND_CHAT_SYSTEM_PROMPT = (
    'أنت مساعد متخصص في تنظيمات الأرض داخل منصة «لاندلوم» (Landloom).\n'
    'تجيب على أسئلة المستخدم حول بيانات قسم «الأرض والكروكي» اعتمادًا على البيانات المرفقة حصريًا:\n'
    '- حقول القسم: بيانات القطعة والصك والمساحة والحدود والشوارع والواجهات والارتدادات والاستخدامات والقيود.\n'
    '- الإحداثيات وجدول الاتجاهات كما سُجلّا.\n'
    '- تحليل مستندات الأرض: القيم المستخرجة من الكروكي والرخصة والاشتراطات (نسب البناء والتغطية، معاملات FAR والأدوار الموثقة لكل شريحة) مع التعارضات المسجلة.\n'
    '- الحقائق التنظيمية الموثقة: قواعد المنطقة الرسمية إن وُجدت ونقاط المراجعة.\n'
    '- السجل الكامل للمنطقة التنظيمية الموثقة: كل شرائح المساحات ومعاملاتها واستثناءاتها وقيودها لمنطقة القطعة إن طُبقت.\n'
    '- القواعد العامة الموثقة لاشتراطات المدينة: الجداول والقواعد المشتركة (المواقف، الارتدادات، الارتفاعات، الملاحق…) إن توفرت للمدينة.\n'
    '- نصوص الاشتراطات الموثقة من ملفات الأمانة: مقتطفات النص الكامل للوائح البلدية مختارة بحسب سؤال المستخدم.\n'
    '- القيم المعتمدة التي أدخلها العميل (المساحة المعتمدة، الأدوار المعتمدة، تغطية البناء، تغطية الطوابق المتكررة، معامل البناء المعتمد).\n'
    '- القيم المحسوبة من المدخلات المعتمدة: إجمالي مسطحات البناء (معامل البناء × المساحة المعتمدة)، ومساحة البناء. مساحة الأدوار المتكررة هي إجمالي مسطحات البناء بعد طرح مساحة البناء، ومساحة الدور هي الناتج مقسومًا على 18؛ ومساحة الدور مضروبة في 18 تساوي مساحة الأدوار المتكررة. نبّه عند تجاوز المساحة الفعلية للأدوار المتكررة مع مساحة البناء إجمالي مسطحات البناء.\n'
    '- قسم أفضل استخدامات: التوزيع المقترح أو المعتمد لمكونات المشروع ومساحاتها وحصصها الأرضية ونماذج الاستفادة وأسبابها وحالة الاعتماد.\n'
    '- قسم المخططات التصورية: نتيجة التحقق من المدخلات، حد الأرض المعتمد، توزيع المكونات على الأدوار، ملاحظات العميل ونقاط المراجعة.\n'
    'قواعد إلزامية:\n'
    '- أجب بلغة سؤال المستخدم نفسها — العربية إن كتب بالعربية، والإنجليزية إن كتب بها.\n'
    '- اسم المنصة «لاندلوم» (Landloom) — اكتبه بهذه التهجئة حرفيًا كلما ذُكر ولا تغيّر حروفه.\n'
    '- خير الكلام ما قلّ ودلّ: الرد الافتراضي قصير — الإجابة المباشرة أولاً في سطر أو سطرين، بلا عناوين ولا أقسام مرقمة ولا تعدادات طويلة، ولا تتجاوز نحو 100 كلمة إلا إذا طلب المستخدم شرحًا مفصلاً صراحة. لا تعرض محتوى الاشتراطات إلا القدر اللازم للإجابة على السؤال المطروح، ولا تكرر المحاذير والشروط نفسها في كل رد.\n'
    '- استند فقط إلى البيانات المرفقة؛ لا تستنتج قيمة غير موجودة ولا تعمّم اشتراطات من خارجها.\n'
    '- إذا كانت المعلومة غير موجودة في البيانات أو غير مؤكدة، صرّح بذلك في الإجابة نفسها '
    '(مثل «البيانات المتاحة لا تذكر عدد الأدوار المسموح لمعامل التميّز») بدل تخمينها — ممنوع التضليل أو الافتراض.\n'
    '- فرّق دائمًا بين القيمة الموثقة في المستندات والقيمة المعتمدة التي أدخلها العميل، وسمِّ كلًا منهما عند ذكره.\n'
    '- فسّر واشرح أي اشتراط أو قيمة أو مصطلح غير واضح في البيانات عندما يطلب المستخدم، واربط الاشتراط بشريحة مساحة الأرض أو نوع المشروع عند الحاجة.\n'
    '- إن سأل المستخدم عن عدد أو كمية (عدد أدوار، مسطحات، مواقف…) فابدأ بالإجابة المباشرة برقم واضح أو مدى محدد: احسبه من البيانات المتاحة (مثال: عدد الأدوار ≈ معامل البناء × المساحة ÷ مساحة مسطح الدور بأقصى تغطية متكررة موثقة) واكتب الناتج أولاً، ثم الشروط في سطر لا أكثر.\n'
    '- إن نقصت بيانات لدى المستخدم نفسه وتعذر الحساب بدونها، اسأله عنها سؤالًا واحدًا مباشرًا (مثال: «ما مساحة مسطح الدور المتكرر المتوقعة؟») — ممنوع تحويل الرد إلى قائمة «بيانات مطلوبة» طويلة.\n'
    '- عند الإجابة من نصوص الاشتراطات انسبها دائمًا إلى «ملفات الأمانة» فقط، ولا تذكر أسماء ملفات أو أرقام صفحات أو مستندات داخلية إطلاقًا.\n'
    '- اكتب المعادلات كنص عادي يقرؤه الإنسان (مثال: مسطح البناء = 7.0 × المساحة = 56000 م²)، وممنوع صيغ LaTeX أو رموزها مثل $ و \\times و \\text، وممنوع تنسيق Markdown تمامًا (لا ** ولا ### ولا جداول).\n'
    '- إن كان للسؤال علاقة بتعارض أو نقطة مراجعة مسجلة فاذكرها.\n'
    '- إن كان السؤال خارج بيانات الأرض والكروكي فوضّح أن هذا الشات مخصص لقسم الأرض والكروكي فقط.\n'
    '- ذاكرة المحادثة إلزامية: لا تخالف ما اتُّفق عليه سابقًا ولا تعِد رقمًا عدّلته أو رفضته، '
    'وإذا غيّر العميل قرارًا سابقًا فاذكر التغيير صراحة.\n'
    '- يجوز اقتراح تعديل على قيم القسم كنص إرشادي مبني على البيانات المرفقة حصرًا: '
    'انسب كل قيمة مقترحة إلى مصدرها الموثق (جدول التنظيم، الحقائق التنظيمية، ملفات الأمانة) '
    'بلا اجتهاد ولا افتراض قيمة غير مسجلة، وإن لم تدعم البيانات اقتراحًا فصرّح بذلك. '
    'ممنوع تنفيذ أي تعديل أو إجراء — الاقتراح إرشاد يقرره العميل ويطبقه بنفسه.'
)


_LAND_CHAT_DOC_KEY_RE = re.compile(r'doc(\d+)(.*)')
_LAND_CHAT_DOC_STR_RE = re.compile(r'\bdoc(\d+)\b')
_LAND_CHAT_FILE_TOKEN_RE = re.compile(
    r'اشتراطات\s*\d+(?:\.\w+)?|[\w-]+\.pdf\b|clean_\w+')


def _land_chat_scrub_rule_refs(value):
    """Recursively drop internal citation keys (source/sources/_doc) from a
    regulation payload, rename the doc1/doc2 value keys, and rewrite file-name
    mentions inside string values, so the chat can only ever describe these
    rules as «ملفات الأمانة» — never internal file names or transcription ids."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if not isinstance(key, str):
                cleaned[key] = _land_chat_scrub_rule_refs(item)
                continue
            if key in ('source', 'sources', '_doc'):
                continue
            doc_match = _LAND_CHAT_DOC_KEY_RE.fullmatch(key)
            if doc_match:
                suffix = doc_match.group(2).replace('_', ' ').strip()
                key = 'وثيقة الأمانة ' + doc_match.group(1) + (
                    f' ({suffix})' if suffix else '')
            cleaned[key] = _land_chat_scrub_rule_refs(item)
        return cleaned
    if isinstance(value, list):
        return [_land_chat_scrub_rule_refs(item) for item in value]
    if isinstance(value, str):
        value = _LAND_CHAT_DOC_STR_RE.sub(r'وثيقة الأمانة \1', value)
        return _LAND_CHAT_FILE_TOKEN_RE.sub('ملفات الأمانة', value)
    return value


def _land_chat_regulation_evidence(message, source):
    """Top-scored page snippets from the municipal اشتراطات PDFs themselves.

    The digest covers the zone's recorded numbers; the files answer everything
    else — premium-FAR tiers, exceptions and conditional rules the digest never
    recorded. Runs only for the verified local city so Jeddah's files never
    bleed into another municipality's answers."""
    try:
        analysis = source.get('land_documents_analysis')
        if isinstance(analysis, str):
            analysis = _visual_concept_parse_json(analysis, {})
        analysis = analysis if isinstance(analysis, dict) else {}
        parcels = analysis.get('parcels') if isinstance(analysis.get('parcels'), list) else []
        parcel = parcels[0] if parcels and isinstance(parcels[0], dict) else {}
        facts_input = _visual_concept_plan_site_facts(source, analysis, parcel)
        site_city_slug, _site_city_label = city_regulations.resolve_site_city(
            facts_input.get('city'))
        if not city_regulations.is_local_city(site_city_slug):
            return ''
        records = _build_regulation_page_index()
    except Exception:
        return ''
    if not records:
        return ''
    query_tokens = _regulation_search_tokens(message, facts_input)
    scored = sorted(
        ({**record, 'score': _score_regulation_page(record['text'], query_tokens)}
         for record in records),
        key=lambda record: (-record['score'], record['page']))
    top = [record for record in scored if record['score'] > 0][:REGULATION_MAX_SNIPPETS]
    # Neutral headers only — the client must always see the source named
    # «ملفات الأمانة», never internal file names or page numbers.
    return '\n\n'.join(
        f"--- مقتطف من ملفات الأمانة ---\n"
        f"{(record['text'] or '')[:REGULATION_SNIPPET_CHARS]}"
        for record in top)


_LAND_CHAT_ANALYSIS_DROP_KEYS = {
    # Extraction internals and raw tables are operator diagnostics or duplicate
    # data the chat already receives through the labeled fields and the
    # survey/directions context blocks — they are the bulk of the payload.
    'extraction_diagnostics', 'document_processing', 'land_document_processing',
    'coordinate_tables', 'regulation_coordinates', 'survey_coordinates',
    'coordinates', 'coordinates_table_source_page',
}


def _land_chat_slim_analysis(analysis):
    """Copy the document analysis minus heavy internals and duplicated tables,
    so the context stays small enough to resend with every chat turn."""
    def slim_dict(source):
        return {
            key: value for key, value in source.items()
            if key not in _LAND_CHAT_ANALYSIS_DROP_KEYS and value not in (None, '', [], {})
        }

    slimmed = slim_dict(analysis)
    parcels = slimmed.get('parcels')
    if isinstance(parcels, list):
        slimmed['parcels'] = [
            slim_dict(parcel) if isinstance(parcel, dict) else parcel
            for parcel in parcels
        ]
    return slimmed


def _land_chat_derived_metrics(source):
    """Deterministic m² figures the chat can quote directly instead of
    recomputing them per question — plus the mandatory capacity check:
    repeated floors area + building footprint must not exceed the total
    built area (approved area × FAR)."""
    metrics = {}
    area = _visual_concept_number(source.get('approved_financial_area'))
    far = _visual_concept_number(source.get('approved_floor_area_ratio'))
    coverage = _visual_concept_number(source.get('approved_coverage_ratio'))
    typical = _visual_concept_number(source.get('approved_typical_floor_coverage'))
    floors = _visual_concept_number(source.get('approved_floor_count'))
    total = area * far if area and far else None
    building = area * coverage / 100 if area and coverage else None
    repeated = max(total - building, 0) if total is not None and building is not None else None
    floor_area = repeated / 18 if repeated is not None else None
    actual_floor_area = area * typical / 100 if area and typical else None
    actual_repeated = actual_floor_area * floors if actual_floor_area and floors else None
    if total:
        metrics['إجمالي مسطحات البناء (معامل البناء × المساحة المعتمدة) م²'] = total
    if building:
        metrics['مساحة البناء (تغطية البناء × المساحة المعتمدة) م²'] = building
    if repeated:
        metrics['مساحة الأدوار المتكررة (إجمالي المسطحات بعد طرح مساحة البناء) م²'] = repeated
    if floor_area:
        metrics['مساحة الدور (المتبقي بعد طرح مساحة البناء مقسومًا على 18) م²'] = floor_area
    if total and actual_repeated is not None and building is not None and actual_repeated + building > total + 0.05:
        metrics['تنبيه'] = ('مجموع مساحة الأدوار المتكررة الفعلية مع مساحة البناء '
                            f'({actual_repeated + building} م²) يتجاوز إجمالي مسطحات البناء '
                            f'({total} م²)')
    return metrics


_LAND_CHAT_BEST_USE_COMPONENT_KEYS = (
    'name', 'useType', 'units', 'unitArea', 'builtArea', 'revenueArea',
    'footprintArea', 'investmentModel', 'parkingLocation', 'reason',
    'areaReason', 'notes',
)


def _land_chat_slim_best_use(raw):
    """The best-use proposal minus draft internals (sourceHash, sourceSnapshot)
    so the chat can discuss the recorded distribution without the audit blob."""
    proposal = raw if isinstance(raw, dict) else _visual_concept_parse_json(raw, {})
    if not isinstance(proposal, dict) or not proposal:
        return {}
    slim = {}
    for key in ('title', 'rationale', 'setbackExplanation'):
        text = _visual_concept_text(proposal.get(key), 6000)
        if text:
            slim[key] = text
    if proposal.get('approved'):
        slim['approved'] = True
    if proposal.get('rejected'):
        slim['rejected'] = True
    for key in ('capacity', 'totals'):
        value = proposal.get(key)
        if isinstance(value, dict) and value:
            slim[key] = value
    components = proposal.get('components')
    if isinstance(components, list) and components:
        slim['components'] = [
            {key: row[key] for key in _LAND_CHAT_BEST_USE_COMPONENT_KEYS
             if row.get(key) not in (None, '')}
            for row in components[:60] if isinstance(row, dict)
        ]
    return slim


def _land_chat_context(project_data):
    """Everything the land chat may answer from, grouped for the prompt — the
    stable part only. The question-scored municipality snippets are appended
    by the route after this block, so this JSON stays identical between turns
    and can hit provider-side prefix caching."""
    source = project_data if isinstance(project_data, dict) else {}
    context = {}
    fields = {}
    for key, label in LAND_CHAT_FIELD_LABELS:
        value = source.get(key)
        if value in (None, '', [], {}):
            continue
        fields[label] = _visual_concept_text(value, 3000)
    if fields:
        context['حقول قسم الأرض والكروكي'] = fields
    derived = _land_chat_derived_metrics(source)
    if derived:
        context['قيم محسوبة من القيم المعتمدة'] = derived
    for key, label in (('survey_coordinates', 'إحداثيات المساحة'),
                       ('directions_table', 'جدول الاتجاهات')):
        rows = source.get(key)
        if isinstance(rows, str):
            rows = _visual_concept_parse_json(rows, [])
        if isinstance(rows, list) and rows:
            context[label] = rows[:60]
    analysis = source.get('land_documents_analysis')
    if isinstance(analysis, str):
        analysis = _visual_concept_parse_json(analysis, None)
    if isinstance(analysis, dict) and analysis:
        slimmed_analysis = _land_chat_slim_analysis(analysis)
        if slimmed_analysis:
            context['تحليل مستندات الأرض'] = slimmed_analysis
    component_source = dict(source)
    if isinstance(component_source.get('financial_study_model'), str):
        component_source['financial_study_model'] = _visual_concept_parse_json(
            component_source['financial_study_model'], {})
    components = _visual_concept_components(component_source)
    if components:
        context['مكونات المشروع المعتمدة'] = components
    concept = _visual_concept_parse_json(source.get('visual_concept'), None)
    if not isinstance(concept, dict):
        concept = {}
    plans = concept.get('plansWorkflow') or concept.get('plans_workflow') or {}
    if not isinstance(plans, dict):
        plans = {}
    distribution = plans.get('distribution') or {}
    if not isinstance(distribution, dict):
        distribution = {}
    distribution_payload = {}
    for key in ('rows', 'totals', 'notes', 'checks', 'issues'):
        rows = distribution.get(key)
        if isinstance(rows, list) and rows:
            distribution_payload[key] = rows[:60]
    for flag in ('approved', 'aiReviewed'):
        if distribution.get(flag):
            distribution_payload[flag] = True
    if distribution_payload:
        context['توزيع المخطط التصوري على الأدوار'] = distribution_payload
    verification = plans.get('verification') or {}
    if not isinstance(verification, dict):
        verification = {}
    verification_payload = {}
    for key in ('checks', 'issues'):
        rows = verification.get(key)
        if isinstance(rows, list) and rows:
            verification_payload[key] = rows[:30]
    summary = _visual_concept_text(verification.get('summary'), 1600)
    if summary:
        verification_payload['summary'] = summary
    for flag in ('canProceed', 'approved'):
        if verification.get(flag):
            verification_payload[flag] = True
    if verification_payload:
        context['التحقق من مدخلات المخططات'] = verification_payload
    boundary = plans.get('boundary') or {}
    if isinstance(boundary, dict):
        boundary_payload = {}
        points = boundary.get('points')
        if isinstance(points, list) and points:
            boundary_payload['points'] = points[:60]
        instruction = _visual_concept_text(boundary.get('instruction'), 2000)
        if instruction:
            boundary_payload['instruction'] = instruction
        if boundary.get('approved'):
            boundary_payload['approved'] = True
        if boundary_payload:
            context['حد الأرض للمخططات'] = boundary_payload
    client_notes = _visual_concept_text(plans.get('clientNotes'), 1000000)
    if client_notes:
        context['ملاحظات العميل على المخططات'] = client_notes
    plans_status = _visual_concept_text(plans.get('status'), 40)
    if plans_status:
        context['حالة سير عمل المخططات'] = plans_status
    slots = concept.get('slots')
    if isinstance(slots, dict):
        slot_payload = {}
        for slot_id, slot in slots.items():
            if not isinstance(slot, dict) or not str(slot_id).startswith('plan_'):
                continue
            entry = {}
            status = _visual_concept_text(slot.get('status'), 40)
            if status:
                entry['status'] = status
            if slot.get('approvedImageUrl') or slot.get('approved_image_url'):
                entry['approved_image'] = True
            elif slot.get('imageUrl') or slot.get('image_url'):
                entry['generated_image'] = True
            if entry:
                slot_payload[_visual_concept_text(slot.get('label') or slot_id, 80)] = entry
        if slot_payload:
            context['حالة صور المخططات التصورية'] = slot_payload
    best_use = _land_chat_slim_best_use(source.get('best_use_data'))
    if best_use:
        context['قسم أفضل استخدامات'] = best_use
    try:
        facts = _visual_concept_plan_regulation_facts(source)
    except Exception:
        facts = {}
    if isinstance(facts, dict) and facts:
        facts.pop('survey_coordinate_count', None)
        context['الحقائق التنظيمية الموثقة'] = _land_chat_scrub_rule_refs(facts)
        if facts.get('regulatory_zone'):
            # The digest matched a verified zone — feed the whole zone record,
            # not only the matched row, so the other bands and exceptions
            # (premium FAR tiers, road rules…) stay answerable.
            try:
                zone_record = regulation_digest.zone_rules(facts.get('regulatory_zone'))
            except Exception:
                zone_record = None
            if isinstance(zone_record, dict) and zone_record:
                context['السجل الكامل للمنطقة التنظيمية الموثقة'] = (
                    _land_chat_scrub_rule_refs(zone_record))
            # The shared city rules apply to this parcel too — without them the
            # chat can quote a value but never explain the regulation behind it.
            try:
                general = regulation_digest.general_rules()
            except Exception:
                general = None
            if isinstance(general, dict) and general:
                context['القواعد العامة الموثقة لاشتراطات المدينة'] = (
                    _land_chat_scrub_rule_refs(general))
    return context


def _land_chat_clean_reply(text):
    """The chat UI renders plain text — the model sometimes emits LaTeX
    ($…$, \\text{…}, \\times) or markdown (**, ###, ---) which reads as code
    to a human. Unwrap it into readable inline text."""
    if not isinstance(text, str) or not re.search(r'[$\\*_`#]', text):
        return text
    text = re.sub(r'\\\\', ' ', text)
    text = re.sub(
        r'\\(?:text|mathrm|mathbf|mathit|mathsf|textbf|operatorname|rm)'
        r'\{([^{}]*)\}', r'\1', text)
    text = re.sub(r'\\frac\{([^{}]*)\}\{([^{}]*)\}', r'\1/\2', text)
    text = re.sub(r'\\sqrt\{([^{}]*)\}', r'√(\1)', text)
    text = re.sub(
        r'\\(times|cdot|div|leq|geq|neq|approx|pm)\b',
        lambda m: {'times': '×', 'cdot': '×', 'div': '÷', 'leq': '≤',
                   'geq': '≥', 'neq': '≠', 'approx': '≈', 'pm': '±'}[m.group(1)],
        text)
    text = re.sub(r'\\le\b', '≤', text)
    text = re.sub(r'\\ge\b', '≥', text)
    text = re.sub(r'\\left|\\right', '', text)
    text = text.replace('\\%', '%').replace('\\&', '&')
    text = re.sub(r'\$\$([\s\S]*?)\$\$', r'\1', text)
    text = re.sub(r'\$([^$]+)\$', r'\1', text)
    text = re.sub(r'\\[\[\](){}]', '', text)
    text = re.sub(r'\\[a-zA-Z]+', ' ', text)
    text = text.replace('$', '')
    text = re.sub(r'[{}]', '', text)
    text = re.sub(r'^\s*#{1,6}\s*', '', text, flags=re.M)
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.M)
    text = re.sub(r'\*\*([^*]+)\*\*|__([^_]+)__',
                  lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r'\*([^*\n]+)\*', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _land_chat_history(raw):
    """The whole conversation, not the last ten turns.

    The land chat used to carry a fixed slice of the conversation, so it
    answered a fresh question and contradicted what the client had just
    agreed. The digest keeps the client's own words when the session grows.
    """
    return chat_memory.normalize_turns(raw)


@app.route('/api/land-chat', methods=['POST'])
@require_auth
def api_land_chat():
    data = request.get_json(silent=True) or {}
    _billing_guard = _require_billing_balance('ai_text')
    if _billing_guard is not None:
        return _billing_guard
    message = _visual_concept_text(data.get('message'), 4000)
    if not message:
        return jsonify({'success': False, 'error': 'اكتب السؤال أولاً',
                        'error_code': 'MESSAGE_REQUIRED'}), 400
    project_data = clean_project_data(data.get('projectData') or {})
    context_json = json.dumps(_land_chat_context(project_data), ensure_ascii=False, default=str)[:60000]
    # Question-scored municipality snippets and history sit AFTER the stable
    # context block: both change per turn, so the request prefix stays
    # identical and can hit provider-side prompt caching.
    evidence = _land_chat_regulation_evidence(message, project_data)
    history = _land_chat_history(data.get('history'))
    memory = data.get('memory') if isinstance(data.get('memory'), str) else ''
    conversation = chat_memory.build_context(history, memory=memory)
    prior = chat_memory.prompt_block(conversation)
    if prior:
        prior = prior + '\n\n'
    user_content = f"بيانات الأرض والكروكي المتاحة:\n{context_json}\n\n"
    if evidence:
        user_content += f"نصوص الاشتراطات الموثقة من ملفات الأمانة:\n{evidence}\n\n"
    user_content += f"{prior}سؤال المستخدم: {message}"
    try:
        response = call_text_chat(
            LAND_CHAT_SYSTEM_PROMPT, user_content, max_tokens=2500,
            model=GEMINI_TEXT_MODEL,
            usage_ctx=_usage_ctx_optional('ai_text', data))
        reply = _land_chat_clean_reply(extract_chat_content(response, 'LAND-CHAT'))
    except Exception as exc:
        app.logger.exception('Land chat failed')
        fatal = _ai_fatal_http_response(exc)
        if fatal is not None:
            return fatal
        return jsonify({'success': False, 'error': 'تعذر الحصول على إجابة',
                        'error_code': 'TEXT_PROVIDER_FAILED'}), 503
    return jsonify({'success': True, 'reply': reply,
                    'memory': conversation['memory'],
                    'decisions': conversation['decisions']})
