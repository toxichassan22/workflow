# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Landmark row selection — the ONE contract for "which rows render".
#
# maps_service.select_map_landmark_rows owns the map side; these helpers mirror it
# for the slide table and every prompt note so the map and the table can never
# disagree: every checked row renders (no cap), in the table's own order so row N
# matches pin N, and with no selection the first 7 rows show like before.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _landmark_row_selected(item):
    """True when the row's show_on_map/selected flag is checked.

    Twin of the check inside maps_service.select_map_landmark_rows — keep both
    in sync. Tolerant of string flags from older drafts («true», «1», «yes»).
    """
    for key in ('show_on_map', 'selected'):
        value = (item or {}).get(key)
        if value is True or str(value or '').strip().lower() in {'true', '1', 'yes'}:
            return True
    return False


def _approved_landmark_rows(structured, limit=7):
    """Return the landmark rows approved to render, in the table's input order.

    Twin of maps_service.select_map_landmark_rows: every checked row renders —
    the client picks the count — and with no selection the first ``limit`` rows
    show. The order is the stored table order, which is also the map's pin
    numbering order, so callers must not re-sort the result.
    """
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except (TypeError, ValueError):
            return []
    if not isinstance(structured, list):
        return []
    rows = [item for item in structured if isinstance(item, dict)]
    selected = [item for item in rows if _landmark_row_selected(item)]
    if selected:
        return selected
    if limit is None:
        return rows
    try:
        row_limit = max(0, min(7, int(limit)))
    except (TypeError, ValueError):
        row_limit = 7
    return rows[:row_limit]


def _project_landmark_rows(project_data, structured_key, matrix_key=None, limit=7):
    """Resolve the rows a landmarks map/table actually renders.

    The structured table is authoritative when present — including an empty
    list, which means «no landmarks», matching the map pipeline's rule. The
    drive-matrix fallback is already the rendered set, so it passes through
    whole instead of being re-selected.
    """
    source = project_data if isinstance(project_data, dict) else {}
    canonical = source.get(structured_key)
    if isinstance(canonical, list):
        return _approved_landmark_rows(canonical, limit)
    if isinstance(canonical, str) and canonical.strip():
        return _approved_landmark_rows(canonical, limit)
    legacy = source.get(matrix_key) if matrix_key else None
    if isinstance(legacy, str):
        try:
            legacy = json.loads(legacy)
        except (TypeError, ValueError):
            legacy = None
    return [row for row in legacy if isinstance(row, dict)] if isinstance(legacy, list) else []


def _nearby_landmark_table_rows(project_data, limit=7):
    """Return the same rows, in the same order, that the landmarks map renders."""
    rows = _project_landmark_rows(project_data, 'nearby_landmarks_data', 'landmarks_matrix', limit)

    def first_value(row, *keys):
        for key in keys:
            value = row.get(key)
            if value not in (None, '', []):
                return value
        return ''

    result = []
    for row in rows:
        name = first_value(row, 'name', 'title', 'landmark', 'displayName')
        if name in (None, ''):
            continue
        result.append([
            name,
            first_value(row, 'category', 'type'),
            first_value(row, 'distance_km', 'distance', 'distance_text'),
            first_value(row, 'duration_minutes', 'duration_min', 'duration', 'minutes', 'duration_text'),
        ])
    return result
