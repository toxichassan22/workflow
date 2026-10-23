# ─────────────────────────────────────────────────────────────────────────────
# The project facts — the brief every prompt reads
# ─────────────────────────────────────────────────────────────────────────────
#
# The facts block was built inside the plan normalizer, which had grown past
# the file limit. It is a concern of its own: it decides what the model is told
# about the project, and the slide prompt, the plan prompt and the executive
# summary all read it.


# A single field cannot flood the brief, and the brief cannot flood the request.
FACT_VALUE_LIMIT = 6000
PROJECT_FACTS_LIMIT = 120000


def _field_label_map():
    """key -> (Arabic label, section key, sort order) for every prebuilt field."""
    labels = {}
    for field in getattr(db, 'PREBUILT_FIELDS', []) or []:
        key = field.get('key')
        if key:
            labels[key] = (field.get('label') or key,
                           field.get('section_key') or 'basic',
                           field.get('sort_order') or 0)
    return labels


def _readable_fact(value):
    """Render one stored value as text a writer can read."""
    if value is None or isinstance(value, bool):
        return '' if value is None else ('نعم' if value else '')
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith('{') or text.startswith('['):
            decoded = _decode_json_fact(text)
            if decoded is not None:
                return _readable_fact(decoded)
        return text[:FACT_VALUE_LIMIT]
    if isinstance(value, dict):
        if len(value) == 1 and 'general' in value:
            return _readable_fact(value['general'])
        parts = []
        for key, item in value.items():
            text = _readable_fact(item)
            raw_label = str(key).split('::')[-1]
            label = USE_TYPE_LABELS.get(raw_label, INVESTMENT_MODEL_LABELS.get(raw_label, raw_label))
            if text:
                parts.append(f'{label}: {text}' if label != 'general' else text)
        return ' | '.join(parts)[:FACT_VALUE_LIMIT]
    if isinstance(value, (list, tuple)):
        parts = [_readable_fact(item) for item in value]
        parts = [part for part in parts if part]
        if not parts:
            return ''
        inline = '، '.join(parts)
        if len(inline) <= 200 and '\n' not in inline:
            return inline[:FACT_VALUE_LIMIT]
        return '\n'.join(f'  - {part}' for part in parts)[:FACT_VALUE_LIMIT]
    return str(value)[:FACT_VALUE_LIMIT]


def _decode_json_fact(value):
    """Sections are stored as JSON strings inside the draft, so they must be decoded first."""
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _market_study_facts(project_data):
    """The market study: the written summary, the competitor rows, SWOT and the decision."""
    state = _decode_json_fact(project_data.get('market_study_data'))
    if not isinstance(state, dict):
        return ''
    lines = []
    summary = str(state.get('one_block_summary') or '').strip()
    if summary:
        lines.append('### الملخص التنفيذي لسوق المشروع')
        lines.append(summary)
    scope = {}
    for key in ('competitor_radius', 'competitor_radius_custom_km', 'data_period',
                'data_period_from', 'data_period_to'):
        value = state.get(key)
        if value not in (None, '', []):
            scope[key] = value
    if scope:
        lines.append('### نطاق وفترة بيانات دراسة السوق')
        lines.append(json.dumps(scope, ensure_ascii=False, indent=2))
    competitors = state.get('competitors') if isinstance(state.get('competitors'), list) else []
    rows = []
    for index, competitor in enumerate(competitors, 1):
        if not isinstance(competitor, dict):
            continue
        # Per-field source URLs are provenance for the study screen, not slide content.
        row = {key: value for key, value in competitor.items()
               if key not in ('id', 'field_sources', 'source_urls', 'row_source', 'logo_file_id',
                              'logo_path', 'logo_url', 'logo_source_url', 'conflict_warnings',
                              'logo_import_warning', 'price_cache', 'area_cache',
                              'benchmarks') and value not in (None, '', [])}
        if competitor.get('logo_file_id') or competitor.get('logo_path') or competitor.get('logo_url'):
            row['شعار المنافس'] = f'##COMPETITOR_LOGO_{index}##'
        if row:
            rows.append(row)
    if rows:
        lines.append('### المنافسون (أرقامهم كما هي، ممنوع تعديلها)')
        lines.append(json.dumps(rows, ensure_ascii=False, indent=2))
    sources = state.get('sources') if isinstance(state.get('sources'), list) else []
    if sources:
        lines.append('### مصادر دراسة السوق')
        lines.append(json.dumps(sources, ensure_ascii=False, indent=2))
    # Keep the detailed analysis even when one_block_summary is present. The
    # executive paragraph must not replace the market analysis in the model context.
    summary_text = str(state.get('summary') or '').strip() if isinstance(state.get('summary'), str) else ''
    if summary_text:
        lines.append('### تحليل السوق')
        lines.append(summary_text)
    for key, title in (('summary', 'تحليل السوق'), ('swot', 'تحليل SWOT')):
        block = state.get(key)
        if isinstance(block, dict):
            filled = {k: v for k, v in block.items() if str(v or '').strip()}
            if filled:
                lines.append(f'### {title}')
                lines.append(json.dumps(filled, ensure_ascii=False, indent=2))
    for key, title in (('decision', 'تصنيف القرار'), ('disclaimer', 'إخلاء المسؤولية')):
        text = str(state.get(key) or '').strip()
        if text:
            lines.append(f'{title}: {text}')
    if not lines:
        return ''
    return '### دراسة السوق\n' + '\n'.join(lines)


def _executive_content_facts(project_data):
    """The approved executive texts, each under its own Arabic label."""
    state = _decode_json_fact(project_data.get('executive_content'))
    if not isinstance(state, dict):
        return ''
    try:
        import executive_content
        blocks = [(item['key'], item['label']) for item in executive_content.BLOCKS]
    except Exception:
        blocks = [(key, key) for key in state]
    lines = []
    for key, label in blocks:
        text = str(state.get(key) or '').strip()
        if text:
            lines.append(f'#### {label}\n{text[:FACT_VALUE_LIMIT]}')
    if not lines:
        return ''
    return ('### المحتوى التنفيذي المعتمد (نصوص معتمدة — أعد صياغتها للشرائح ولا تخترع غيرها)\n'
            + '\n\n'.join(lines))


def _selected_team_entries(project_data, tenant_id=None):
    selection = _decode_json_fact((project_data or {}).get('team_selection'))
    selection = selection if isinstance(selection, dict) else {}
    excluded = set(selection.get('excluded') or [])
    overrides = selection.get('roles') if isinstance(selection.get('roles'), dict) else {}
    entries = []
    if tenant_id:
        try:
            library = db.get_team_entities(tenant_id) or []
        except Exception:
            library = []
        for entity in library:
            if entity.get('id') in excluded:
                continue
            entries.append({
                'الجهة': entity.get('name') or '',
                'الدور': overrides.get(entity.get('id')) or entity.get('role') or '',
                'نبذة': entity.get('brief') or '',
                'سنوات الخبرة': entity.get('experienceYears') or '',
                'أعمال سابقة': entity.get('notableProjects') or '',
                '_logo_file_id': entity.get('logoFileId') or '',
            })
    for local in selection.get('local') or []:
        if not isinstance(local, dict):
            continue
        entries.append({
            'الجهة': local.get('name') or '',
            'الدور': local.get('role') or '',
            'نبذة': local.get('brief') or '',
            'سنوات الخبرة': local.get('experienceYears') or '',
            'أعمال سابقة': local.get('notableProjects') or '',
            '_logo_file_id': local.get('logoFileId') or '',
        })
    return [{key: value for key, value in entry.items() if str(value or '').strip()}
            for entry in entries if str(entry.get('الجهة') or '').strip()]


def _team_facts(project_data, tenant_id=None):
    """The team actually chosen for this file: the company library minus exclusions, plus locals.

    The library lives in ``tenant_team_entities`` and the draft only stores ids, so without
    resolving it the prompt would carry no names at all.
    """
    entries = []
    for index, source in enumerate(_selected_team_entries(project_data, tenant_id), 1):
        entry = {key: value for key, value in source.items() if not key.startswith('_')}
        if source.get('_logo_file_id'):
            entry['الشعار'] = f'##TEAM_LOGO_{index}##'
        entries.append(entry)
    if not entries:
        return ''
    return '### فريق العمل (بنفس الترتيب والحقول، وشعار كل جهة إلزامي عند توفره)\n' + json.dumps(entries, ensure_ascii=False, indent=2)


def _contact_facts(project_data, tenant_id=None):
    source = project_data if isinstance(project_data, dict) else {}
    fields = (
        ('الاسم', ('contact_name', 'name')),
        ('المنصب', ('contact_position', 'position', 'job_title')),
        ('الهاتف', ('contact_phone', 'company_phone', 'phone', 'mobile')),
        ('البريد الإلكتروني', ('contact_email', 'company_email', 'email')),
        ('الموقع الإلكتروني', ('contact_website', 'company_website', 'website')),
        ('الموقع الجغرافي', ('contact_address', 'company_address', 'address')),
        ('السوشل ميديا', ('contact_social_media', 'social_media')),
    )
    values = {}
    for label, keys in fields:
        value = next((str(source.get(key) or '').strip() for key in keys if str(source.get(key) or '').strip()), '')
        if value:
            values[label] = value
    if not values:
        return ''
    return '### بيانات التواصل المعتمدة للخاتمة (انقل المتاح فقط كما هو)\n' + json.dumps(values, ensure_ascii=False, indent=2)


def build_project_facts(project_data, tenant_id=None, section_keys=None):
    """Every collected fact, grouped by its section and labelled in Arabic.

    Replaces dumping the raw draft and cutting it at a character count.
    ``section_keys`` limits the project field sections to the ones a deck
    section actually renders. ``None`` keeps the historical full brief.
    Unknown custom fields stay in every scope: they have no section mapping,
    and silently dropping them is worse than carrying their bounded text.
    """
    if not isinstance(project_data, dict) or not project_data:
        return 'لا توجد بيانات مشروع.'
    selected_sections = {str(key) for key in section_keys} if section_keys else None
    labels = _field_label_map()
    section_titles = {item['key']: item['label']
                      for item in (getattr(db, 'FIELD_SECTIONS', []) or [])}
    grouped = {key: [] for key in section_titles}
    extra = []
    for key, value in project_data.items():
        if key in PROMPT_SKIPPED_KEYS or key.startswith('_'):
            continue
        if key.endswith(PROMPT_SKIPPED_SUFFIXES):
            continue
        if key in ('market_study_data', 'executive_content', 'team_selection'):
            continue
        # Frozen drift-check copies stored inside a blob (sourceSnapshot,
        # parkingSnapshot, hashes, caches) must not narrate as facts.
        text = _readable_fact(designer_chat_context.strip_internal_snapshots(value))
        if not text:
            continue
        if key in labels:
            label, section, order = labels[key]
            grouped.setdefault(section, []).append((order, label, text))
        else:
            label = EXTRA_FIELD_LABELS.get(key)
            if not label and key.endswith('_other'):
                base = labels.get(key[:-6])
                label = f'{base[0]} (أخرى)' if base else None
            extra.append((label or key, text))

    blocks = []
    for section_key, title in section_titles.items():
        if selected_sections is not None and section_key not in selected_sections:
            continue
        # Same order as the form, so the brief reads the way the client filled it.
        rows = sorted(grouped.get(section_key) or [], key=lambda row: row[0])
        if rows:
            blocks.append(f'### {title}\n'
                          + '\n'.join(f'- {label}: {text}' for _order, label, text in rows))
    if extra:
        blocks.append('### بيانات إضافية\n'
                      + '\n'.join(f'- {label}: {text}' for label, text in extra))
    special_notes = []
    if selected_sections is None or 'section-team' in selected_sections:
        special_notes.append(_team_facts(project_data, tenant_id))
    if selected_sections is None or 'section-market-study' in selected_sections:
        special_notes.append(_market_study_facts(project_data))
    if selected_sections is None or 'section-executive-content' in selected_sections:
        special_notes.append(_executive_content_facts(project_data))
    if selected_sections is None or 'contact' in selected_sections:
        special_notes.append(_contact_facts(project_data, tenant_id))
    for note in special_notes:
        if note:
            blocks.append(note)
    facts = '\n\n'.join(blocks) or 'لا توجد بيانات مشروع.'
    if len(facts) > PROJECT_FACTS_LIMIT:
        facts = facts[:PROJECT_FACTS_LIMIT] + '\n... [تم اختصار البيانات]'
    return facts
