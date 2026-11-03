# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Deck translation: produce an English copy of an existing Arabic deck WITHOUT
# regenerating a single slide. Layout, colours, images and tables are markup and
# stay byte-identical; only the words change. The engine lives in
# modules/slides/slide_translator.py, which also validates that placeholders and
# numbers survived before accepting a translation.
#
# The model is owner-managed: TRANSLATION_MODEL has no default on purpose, and
# this route refuses with TRANSLATION_MODEL_NOT_CONFIGURED until it is set.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import copy as _translation_copy


def _presentation_slides(presentation):
    """slides_data as a list, whether the row handed us JSON text or a list."""
    raw = (presentation or {}).get('slides_data')
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _presentation_project_data(presentation):
    try:
        data = json.loads(presentation.get('project_data') or '{}')
    except (TypeError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _translation_glossary(tenant_id, project_data):
    """The owner's English spelling of the company and project names.

    Only pairs the owner filled in on both sides are used: inventing an English
    name here would put words in the deck that the client never approved.
    """
    pairs = {}
    try:
        tenant = db.get_tenant_by_id(tenant_id) or {}
    except Exception:
        tenant = {}
    arabic = str(tenant.get('company_name') or '').strip()
    english = str(tenant.get('company_name_en') or '').strip()
    if arabic and english and arabic != english:
        pairs[arabic] = english
    for arabic_key, english_key in (('project_name', 'project_name_en'),
                                    ('project_name', 'name_en')):
        arabic = str(project_data.get(arabic_key) or '').strip()
        english = str(project_data.get(english_key) or '').strip()
        if arabic and english and arabic != english:
            pairs.setdefault(arabic, english)
    return pairs


def _translation_project_data(project_data, target_lang):
    data = _translation_copy.deepcopy(project_data or {})
    # The copy must keep speaking English if it is ever regenerated, exported or
    # extended: the offer language rides on the project data.
    data['project_language'] = target_lang
    data['offer_lang'] = target_lang
    return data


@app.route('/api/presentations/<pres_id>/translate', methods=['POST'])
@require_permission('create_presentation')
def api_translate_presentation(pres_id):
    """Translate a deck into English as a separate presentation copy."""
    model_name = str(TRANSLATION_MODEL or '').strip()
    if not model_name:
        return jsonify({
            'success': False,
            'code': 'TRANSLATION_MODEL_NOT_CONFIGURED',
            'error': 'لم يُضبط موديل الترجمة في إعدادات الخادم (TRANSLATION_MODEL).',
        }), 503
    payload = request.get_json(silent=True) or {}
    target_lang = str(payload.get('targetLang') or 'en').strip().lower()
    if target_lang not in TRANSLATION_TARGET_LANGS:
        return jsonify({
            'success': False,
            'code': 'UNSUPPORTED_TARGET_LANG',
            'error': 'الترجمة المدعومة حاليًا هي العربية إلى الإنجليزية فقط.',
        }), 400

    presentation = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not presentation or not _presentation_in_scope(presentation):
        return jsonify({'error': 'Presentation not found'}), 404
    slides = _presentation_slides(presentation)
    project_data = _presentation_project_data(presentation)
    glossary = _translation_glossary(g.tenant_id, project_data)
    if not slide_translator.deck_has_arabic(slides):
        return jsonify({
            'success': False,
            'code': 'NOTHING_TO_TRANSLATE',
            'error': 'لا يوجد نص عربي في هذا العرض ليُترجم.',
        }), 422

    failure = {}

    def _translate_batch(texts):
        response = call_text_chat(
            slide_translator.translation_prompt(glossary),
            slide_translator.build_batch_payload(texts),
            max_tokens=min(8000, 600 + len(texts) * 160),
            response_format={'type': 'json_object'},
            model=model_name,
            usage_ctx={
                'tenant_id': g.tenant_id,
                'draft_id': presentation.get('draft_id'),
                'flow': 'translate',
            },
        )
        if not isinstance(response, dict) or response.get('error'):
            message = ''
            if isinstance(response, dict):
                message = str((response.get('error') or {}).get('message') or '')
            failure.setdefault('message', message or 'تعذّر الوصول إلى موديل الترجمة.')
            return [None] * len(texts)
        content = extract_chat_content(response, 'TRANSLATE')
        return slide_translator.parse_batch_response(content, len(texts))

    translated, stats = slide_translator.translate_slides(
        slides, _translate_batch, target_lang=target_lang, glossary=glossary)
    if not stats['translated'] and not stats['titles']:
        return jsonify({
            'success': False,
            'code': 'TRANSLATION_FAILED',
            'error': failure.get('message') or 'لم تُترجم أي فقرة من العرض؛ أعد المحاولة.',
        }), 502

    title = '%s (%s)' % (presentation.get('title') or 'عرض', 'English')
    project_data = _translation_project_data(project_data, target_lang)
    new_id = db.create_presentation(
        g.tenant_id,
        title,
        project_data=project_data,
        slides_data=translated,
        slide_count=len(translated),
        draft_id=presentation.get('draft_id'),
    )
    try:
        db.save_presentation_version(
            new_id, getattr(g, 'user_id', None), _history_actor_name(),
            translated, action='translate')
    except Exception as exc:
        print(f'[TRANSLATE] could not snapshot the translated deck: {exc}')
    _record_change(
        'presentation',
        new_id,
        'ترجمة العرض إلى الإنجليزية',
        [
            'عدد الشرائح: %d' % len(translated),
            'مقاطع مترجمة: %d' % stats['translated'],
            'مقاطع أبقيت كما هي: %d' % stats['skipped'],
        ],
        source='ai',
        summary=title,
    )
    return jsonify({
        'success': True,
        'presentationId': new_id,
        'sourcePresentationId': pres_id,
        'title': title,
        'slideCount': len(translated),
        'translatedUnits': stats['translated'],
        'keptUnits': stats['skipped'],
        'titles': stats['titles'],
    }), 201


TRANSLATION_TARGET_LANGS = ('en',)
