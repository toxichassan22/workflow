

# ---------------------------------------------------------------------------
# Benchmark axes — a mixed-use project's revenue components each need their own
# COMPETITOR_MIN_DIRECT direct competitors. project_competitor_axes derives the
# axes from the payload (components table, then subtypes, then main types), and
# competitor_row_axis_keys attributes each competitor row to the axes it
# benchmarks so the expansion passes can count per axis instead of per table.
# ---------------------------------------------------------------------------


def _split_multi_values(value):
    """Split a joined multi-select value ('، '-joined, JSON list, or list)."""
    if isinstance(value, (list, tuple, set)):
        return [_norm(item) for item in value if _norm(item)]
    text = _norm(value)
    if not text:
        return []
    if text.startswith('['):
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return [_norm(item) for item in parsed if _norm(item)]
    return [part.strip() for part in re.split(r'[,،\n;|]', text) if part.strip()]


def _iter_payload_components(payload):
    """The structured components list the frontend sends ('components')."""
    components = (payload or {}).get('components')
    if isinstance(components, str):
        try:
            components = json.loads(components)
        except Exception:
            components = None
    if not isinstance(components, list):
        return []
    return [item for item in components if isinstance(item, dict)]


def project_competitor_axes(payload):
    """Ordered benchmark axes for the competitor table.

    One axis per distinct revenue-bearing component use; falls back to the
    project subtypes (mixed-use selections), then the main type(s), then a
    single 'general' axis — which reproduces the old whole-table minimum.
    """
    payload = payload or {}
    axes = []

    def add(key, base=None, label='', name=''):
        definition = COMPONENT_USE_AXES.get(base or key)
        if not definition:
            return
        existing = next((axis for axis in axes if axis['key'] == key), None)
        if existing:
            if name and name not in existing['names']:
                existing['names'].append(name)
            return
        axes.append({
            'key': key,
            'base': base or key,
            'label': label or definition['label'],
            'label_en': label if key.startswith('other:') else definition['label_en'],
            'search': definition['search'],
            'names': [name] if name else [],
        })

    for component in _iter_payload_components(payload):
        model = _fold_choice(
            component.get('investmentModel') or component.get('investment_model'))
        if model == 'nonrevenue':
            continue
        use = _norm(component.get('useType') or component.get('use_type')).lower()
        if not use or use in COMPONENT_NON_COMPETING_USES:
            continue
        name = _norm(component.get('name'))
        if use in COMPONENT_USE_AXES:
            add(use, name=name)
        else:
            add(f'other:{name or "أخرى"}', base='other', label=name or 'أخرى', name=name)
    if not axes:
        subtypes = _split_multi_values(
            payload.get('projectSubtype') or payload.get('project_subtype'))
        subtypes += _split_multi_values(
            payload.get('projectComponents') or payload.get('project_components')
            or payload.get('project_mixed_components'))
        for subtype in subtypes:
            key = MIXED_COMPONENT_AXIS_KEYS.get(subtype)
            if key:
                add(key, name=subtype)
    if not axes:
        for main in _split_multi_values(
                payload.get('projectType') or payload.get('project_type')):
            key = PROJECT_MAIN_AXIS_KEYS.get(main)
            if key:
                add(key, name=main)
    if not axes:
        add('general')
    return axes


def benchmark_axis_label(axis, offer_lang='ar'):
    """The label the model must write in benchmarks for this axis."""
    if offer_lang == 'en':
        return axis.get('label_en') or axis.get('label') or ''
    return axis.get('label') or ''


def _axis_alias_set(axis):
    """Folded benchmark values that attribute a row to this axis."""
    aliases = {
        _fold_choice(axis.get('label')),
        _fold_choice(axis.get('label_en')),
    }
    aliases.update(_fold_choice(name) for name in axis.get('names') or [])
    if axis.get('base') != 'other':
        aliases.update(
            _fold_choice(item)
            for item in BENCHMARK_AXIS_ALIASES.get(axis.get('base'), ()))
    return {alias for alias in aliases if alias}


def competitor_row_axis_keys(row, axes, offer_lang='ar'):
    """The axes a competitor row benchmarks.

    Priority: the row's benchmarks field (the model's explicit tag, which may
    legitimately cover several axes for a mixed-use competitor), then a
    project_type fallback for untagged/legacy rows, then a single 'general'
    axis counts every named row — the old whole-table semantics.
    """
    axis_keys = {axis['key'] for axis in axes}
    if axis_keys == {'general'}:
        return {'general'}
    if not isinstance(row, dict):
        return set()
    keys = set()
    raw = (row.get('benchmarks') or row.get('benchmark_axes')
           or row.get('measured_against') or row.get('serves_components')
           or row.get('يُقاس على') or row.get('يقاس على'))
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    alias_sets = {axis['key']: _axis_alias_set(axis) for axis in axes}
    for item in items:
        for part in _split_multi_values(item):
            folded = _fold_choice(part)
            if not folded:
                continue
            for axis in axes:
                if folded in alias_sets[axis['key']]:
                    keys.add(axis['key'])
    if not keys:
        fallback = BENCHMARK_PROJECT_TYPE_FALLBACK.get(
            _fold_choice(row.get('project_type')))
        if fallback == '*':
            keys = set(axis_keys)
        elif fallback:
            keys = {
                axis['key'] for axis in axes
                if axis['key'] in fallback
                or (axis.get('base') == 'other' and 'other' in fallback)}
    return keys
