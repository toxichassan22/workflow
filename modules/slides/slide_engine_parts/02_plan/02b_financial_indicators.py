# ─────────────────────────────────────────────────────────────────────────────
# Financial indicators — the display contract
# ─────────────────────────────────────────────────────────────────────────────
#
# The projection object stores raw decimals: a ROI of 0.2345 is shown on the
# financial screen as «23.45%», and a payback of 4.5 years as «4.5». A deck
# that copies the raw decimal prints «0.2345» and contradicts the number the
# client approved, so every indicator leaves the engine through one formatter.
#
# The client sends the exact string it displays (`formattedIndicators`), so the
# deck and the screen can never drift apart. An older draft without that map
# falls back to formatting the stored projection the same way.

_FINANCIAL_INDICATOR_PERCENT_KEYS = ('roi', 'projectIrr', 'equityIrr')
_FINANCIAL_INDICATOR_YEAR_KEYS = ('payback', 'equityPayback', 'developmentYears')


def _financial_indicator_display_value(key, value):
    """Format one indicator the way the financial study screen shows it."""
    if value in (None, '', [], {}):
        return ''
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if key in _FINANCIAL_INDICATOR_PERCENT_KEYS:
        # The projection keeps the ratio; the screen shows the percentage.
        return f'{format_financial_number(number * 100, grouped=False)}%'
    if key in _FINANCIAL_INDICATOR_YEAR_KEYS:
        return format_financial_number(number, grouped=False)
    return format_financial_number(number)


def _financial_indicator_display_map(model, project_data=None):
    """Every indicator with its display string — the client's own values first."""
    model = model if isinstance(model, dict) else {}
    projection = model.get('projection') if isinstance(model.get('projection'), dict) else {}
    inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
    calc = _parse_financial_dict((project_data or {}).get('financial_calc_data'))
    formatted = model.get('formattedIndicators') or model.get('formatted_indicators') or {}
    formatted = formatted if isinstance(formatted, dict) else {}
    display_map = {}
    for key, _label in _FINANCIAL_INDICATOR_LABELS:
        value = formatted.get(key)
        if value not in (None, '', [], {}):
            display_map[key] = str(value)
            continue
        value = projection.get(key)
        if value in (None, '', [], {}) and inputs.get(key) not in (None, '', [], {}):
            value = inputs.get(key)
        if value in (None, '', [], {}) and calc.get(key) not in (None, '', [], {}):
            value = calc.get(key)
        if value in (None, '', [], {}, -1):
            continue
        display = _financial_indicator_display_value(key, value)
        if display:
            display_map[key] = display
    return display_map


def _financial_indicator_display_rows(model, project_data=None, limit=None):
    """[(label, display value)] — the key figures of the financial section."""
    display_map = _financial_indicator_display_map(model, project_data)
    rows = []
    for key, label in _FINANCIAL_INDICATOR_LABELS:
        value = display_map.get(key)
        if not value:
            continue
        rows.append([label, value])
        if limit and len(rows) >= limit:
            break
    return rows
