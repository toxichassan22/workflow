

# ─────────────────────────────────────────────────────────────────────────────
# AI Usage Metering (OpenRouter consumption per tenant, draft and presentation)
# ─────────────────────────────────────────────────────────────────────────────

AI_ATTEMPT_STATUSES = ('in_flight', 'pending', 'settled', 'unresolved', 'needs_review')
AI_COST_SOURCES = ('response', 'generation', 'review')


def _ai_usage_now_text():
    return _utcnow().strftime('%Y-%m-%d %H:%M:%S')


def _ai_usage_columns(conn):
    try:
        return {row['name'] for row in conn.execute('PRAGMA table_info(ai_usage_events)').fetchall()}
    except Exception:
        return set()


def _coerce_ai_cost(value):
    """Validate a provider dollar figure without ever turning unknown into zero.

    Returns (cost_float_or_None, raw_text_or_None). Unknown, non-numeric,
    non-finite and negative values all return (None, None) so the caller
    keeps the attempt pending instead of storing a misleading zero.
    """
    try:
        if value is None:
            return None, None
        if isinstance(value, bool):
            return None, None
        from decimal import Decimal, InvalidOperation
        import math as _math
        if isinstance(value, float) and (not _math.isfinite(value)):
            return None, None
        text = str(value).strip()
        if not text:
            return None, None
        amount = Decimal(text)
        if not amount.is_finite():
            return None, None
        if amount < 0:
            return None, None
        return float(amount), text
    except Exception:
        return None, None


def _derive_attempt_status(cost_usd, generation_id, explicit=None):
    if explicit in AI_ATTEMPT_STATUSES:
        return explicit
    if cost_usd is not None:
        return 'settled'
    if generation_id:
        return 'pending'
    return 'unresolved'


def _tenant_package_cycle(conn, tenant_id):
    """(package_id, credit_usd, assigned_at) for the tenant's current cycle.

    The entitlement comes from the latest tenant_package_history snapshot, so
    editing the catalog's credit_usd never rewrites an already-granted
    assignment. ``assigned_at`` is where the new cycle's consumption starts —
    re-assigning a spent package begins a fresh window instead of inheriting
    the old cycle's burn. Falls back to the catalog credit for assignments
    that predate history tracking. None when the tenant has no valid package.
    """
    try:
        if not tenant_id:
            return None
        row = conn.execute(
            'SELECT package_id FROM tenants WHERE id = ?', (str(tenant_id),)).fetchone()
        package_id = dict(row).get('package_id') if row else None
        if not package_id:
            return None
        package_id = str(package_id)
        package = conn.execute(
            'SELECT credit_usd, is_active FROM billing_packages WHERE id = ?',
            (package_id,)).fetchone()
        if not package or not dict(package).get('is_active'):
            return None
        hist = conn.execute(
            'SELECT credit_usd, assigned_at FROM tenant_package_history '
            'WHERE tenant_id = ? AND package_id = ? '
            'ORDER BY assigned_at DESC, rowid DESC LIMIT 1',
            (str(tenant_id), package_id)).fetchone()
        if hist:
            return (package_id, float(dict(hist).get('credit_usd') or 0.0),
                    dict(hist).get('assigned_at'))
        return (package_id, float(dict(package).get('credit_usd') or 0.0), None)
    except Exception:
        return None


def _package_cycle_consumed(conn, tenant_id, package_id, assigned_at):
    """Tagged spend inside the current cycle — rows before ``assigned_at``
    belong to the previous assignment of the same package."""
    consumed = 0.0
    bound = str(assigned_at).replace('T', ' ')[:19] if assigned_at else None
    for table in ('ai_usage_events', 'map_usage_events'):
        try:
            where = ('WHERE tenant_id = ? AND package_id = ?'
                     + (" AND REPLACE(created_at, 'T', ' ') >= ?" if bound else ''))
            params = [str(tenant_id), str(package_id)] + ([bound] if bound else [])
            spent = conn.execute(
                f'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM {table} {where}',
                tuple(params)).fetchone()
            consumed += float(dict(spent).get('total') or 0.0)
        except Exception:
            pass
    return consumed


def _tenant_active_package_id(conn, tenant_id):
    """Package a new spend row burns under — only while it still has credit.

    An exhausted or deactivated package must not keep owning new usage: rows
    tagged with its id are excluded from wallet billing, so over-quota spend
    would never reach the wallet at all. Falling back to NULL lets the next
    row bill against the wallet again.
    """
    try:
        cycle = _tenant_package_cycle(conn, tenant_id)
        if not cycle:
            return None
        package_id, credit, assigned_at = cycle
        if credit - _package_cycle_consumed(conn, tenant_id, package_id, assigned_at) <= 0:
            return None
        return package_id
    except Exception:
        return None


def record_ai_usage_event(tenant_id, model, flow='other', status='ok',
                          prompt_tokens=0, completion_tokens=0, total_tokens=0,
                          cost_usd=None, generation_id=None,
                          draft_id=None, presentation_id=None,
                          cost_source=None, attempt_status=None,
                          response_cost_usd=None, generation_cost_usd=None,
                          cost_raw=None, reconcile_attempts=0,
                          next_retry_at=None, package_id=None):
    """Persist one metered OpenRouter call.

    Token figures are copied verbatim from the provider response, never
    estimated. A row is written even when the provider returned no usage so
    the attempt itself stays visible. Unknown cost stays NULL and is never
    stored as zero. The source precision is preserved in cost_raw.
    """
    conn = get_db()
    cols = _ai_usage_columns(conn)
    cost_value, cost_text = _coerce_ai_cost(cost_usd)
    if cost_usd is not None and cost_value is None:
        cost_value, cost_text = None, None
    if cost_raw is None:
        cost_raw = cost_text
    if response_cost_usd is None and cost_source == 'response' and cost_value is not None:
        response_cost_usd = cost_value
    if generation_cost_usd is None and cost_source in ('generation', 'review') and cost_value is not None:
        generation_cost_usd = cost_value
    derived = _derive_attempt_status(cost_value, generation_id, attempt_status)
    if cost_source is not None and cost_source not in AI_COST_SOURCES:
        cost_source = None
    if cost_value is None:
        cost_source = None
    if package_id is None:
        package_id = _tenant_active_package_id(conn, tenant_id)
    event_id = str(uuid.uuid4())
    now_text = _ai_usage_now_text()
    has_package_col = 'package_id' in cols
    if {'cost_source', 'attempt_status', 'reconcile_attempts', 'next_retry_at',
        'updated_at', 'response_cost_usd', 'generation_cost_usd', 'cost_raw'} <= cols:
        conn.execute(
            '''INSERT INTO ai_usage_events
               (id, tenant_id, draft_id, presentation_id, flow, model, status,
                prompt_tokens, completion_tokens, total_tokens, cost_usd, generation_id,
                cost_source, attempt_status, reconcile_attempts, next_retry_at, updated_at,
                response_cost_usd, generation_cost_usd, cost_raw{})
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?{})'''.format(
                ', package_id' if has_package_col else '',
                ', ?' if has_package_col else ''),
            (event_id, tenant_id, draft_id, presentation_id, flow or 'other', model,
             status or 'ok', int(prompt_tokens or 0), int(completion_tokens or 0),
             int(total_tokens or 0), cost_value, generation_id,
             cost_source, derived, int(reconcile_attempts or 0), next_retry_at, now_text,
             response_cost_usd, generation_cost_usd, cost_raw)
            + ((package_id,) if has_package_col else ())
        )
    else:
        conn.execute(
            '''INSERT INTO ai_usage_events
               (id, tenant_id, draft_id, presentation_id, flow, model, status,
                prompt_tokens, completion_tokens, total_tokens, cost_usd, generation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (event_id, tenant_id, draft_id, presentation_id, flow or 'other', model,
             status or 'ok', int(prompt_tokens or 0), int(completion_tokens or 0),
             int(total_tokens or 0), cost_value, generation_id)
        )
    conn.commit()
    return event_id


def begin_ai_usage_attempt(tenant_id, model, flow='other', draft_id=None, presentation_id=None):
    """Create the single unified row for one real provider attempt before sending.

    The same row is later settled with the response, so one attempt never
    becomes two rows. Futures cancelled before sending must not call this.
    """
    return record_ai_usage_event(
        tenant_id, model or 'unknown', flow=flow or 'other', status='ok',
        prompt_tokens=0, completion_tokens=0, total_tokens=0,
        cost_usd=None, generation_id=None,
        draft_id=draft_id, presentation_id=presentation_id,
        cost_source=None, attempt_status='in_flight',
    )


def update_ai_usage_attempt(event_id, status=None, prompt_tokens=None,
                            completion_tokens=None, total_tokens=None,
                            generation_id=None, cost_usd=None, cost_source=None,
                            cost_raw=None, response_cost_usd=None,
                            generation_cost_usd=None, attempt_status=None,
                            reconcile_attempts=None, next_retry_at=None,
                            clear_next_retry=False):
    """Update the single row that owns one attempt. Never inserts a new cost row."""
    conn = get_db()
    cols = _ai_usage_columns(conn)
    row = conn.execute('SELECT * FROM ai_usage_events WHERE id = ?', (str(event_id),)).fetchone()
    if row is None:
        return False
    current = dict(row)
    assignments = []
    params = []
    if status is not None:
        assignments.append('status = ?')
        params.append(status)
    for key, value in (('prompt_tokens', prompt_tokens), ('completion_tokens', completion_tokens),
                       ('total_tokens', total_tokens)):
        if value is not None:
            try:
                assignments.append(f'{key} = ?')
                params.append(int(value or 0))
            except (TypeError, ValueError):
                pass
    if generation_id is not None:
        assignments.append('generation_id = ?')
        params.append(generation_id or None)
    if cost_usd is not None or cost_source is not None or cost_raw is not None:
        candidate = cost_usd if cost_usd is not None else current.get('cost_usd')
        coerced, raw = _coerce_ai_cost(candidate)
        if candidate is not None and coerced is None:
            pass
        else:
            if cost_usd is not None:
                assignments.append('cost_usd = ?')
                params.append(coerced)
                if 'cost_raw' in cols:
                    assignments.append('cost_raw = ?')
                    params.append(cost_raw if cost_raw is not None else raw)
            if cost_source is not None and 'cost_source' in cols:
                valid_source = cost_source if cost_source in AI_COST_SOURCES else None
                if coerced is None:
                    valid_source = None
                assignments.append('cost_source = ?')
                params.append(valid_source)
    if response_cost_usd is not None and 'response_cost_usd' in cols:
        coerced, _raw = _coerce_ai_cost(response_cost_usd)
        if coerced is not None:
            assignments.append('response_cost_usd = ?')
            params.append(coerced)
    if generation_cost_usd is not None and 'generation_cost_usd' in cols:
        coerced, _raw = _coerce_ai_cost(generation_cost_usd)
        if coerced is not None:
            assignments.append('generation_cost_usd = ?')
            params.append(coerced)
    if attempt_status is not None and 'attempt_status' in cols:
        if attempt_status in AI_ATTEMPT_STATUSES:
            assignments.append('attempt_status = ?')
            params.append(attempt_status)
    if reconcile_attempts is not None and 'reconcile_attempts' in cols:
        try:
            assignments.append('reconcile_attempts = ?')
            params.append(int(reconcile_attempts))
        except (TypeError, ValueError):
            pass
    if 'next_retry_at' in cols:
        if clear_next_retry:
            assignments.append('next_retry_at = ?')
            params.append(None)
        elif next_retry_at is not None:
            assignments.append('next_retry_at = ?')
            params.append(next_retry_at)
    if 'updated_at' in cols:
        assignments.append('updated_at = ?')
        params.append(_ai_usage_now_text())
    if not assignments:
        return True
    params.append(str(event_id))
    conn.execute(f"UPDATE ai_usage_events SET {', '.join(assignments)} WHERE id = ?", params)
    conn.commit()
    return True


def update_ai_usage_cost(event_id, cost_usd, cost_source='generation'):
    """Fill in the dollar cost of a usage event once the provider reports it.

    Existing rows are updated in place so a review never appends a second
    cost row. Invalid figures leave the attempt pending instead of zero.
    """
    coerced, raw = _coerce_ai_cost(cost_usd)
    if coerced is None:
        return False
    source = cost_source if cost_source in AI_COST_SOURCES else 'generation'
    conn = get_db()
    cols = _ai_usage_columns(conn)
    if {'cost_source', 'attempt_status', 'updated_at', 'generation_cost_usd',
        'response_cost_usd', 'cost_raw'} <= cols:
        extra_gen = ', generation_cost_usd = ?' if source in ('generation', 'review') else ''
        extra_resp = ', response_cost_usd = ?' if source == 'response' else ''
        params = [coerced, source, raw, _ai_usage_now_text()]
        if source in ('generation', 'review'):
            params.append(coerced)
        if source == 'response':
            params.append(coerced)
        params.append(str(event_id))
        conn.execute(
            'UPDATE ai_usage_events SET cost_usd = ?, cost_source = ?, cost_raw = ?, '
            f"attempt_status = 'settled', updated_at = ?{extra_gen}{extra_resp} WHERE id = ?",
            params
        )
    else:
        conn.execute(
            'UPDATE ai_usage_events SET cost_usd = ? WHERE id = ?',
            (coerced, str(event_id))
        )
    conn.commit()
    return True


def claim_ai_usage_reconcile_row(event_id, delay_seconds=300):
    """Claim one row for reconcile so parallel reviews never process it twice."""
    conn = get_db()
    cols = _ai_usage_columns(conn)
    if {'reconcile_attempts', 'next_retry_at', 'updated_at'} <= cols:
        from datetime import timedelta
        next_text = (_utcnow() + timedelta(seconds=max(1, int(delay_seconds or 0)))).strftime('%Y-%m-%d %H:%M:%S')
        cursor = conn.execute(
            'UPDATE ai_usage_events SET reconcile_attempts = COALESCE(reconcile_attempts, 0) + 1, '
            'next_retry_at = ?, updated_at = ? WHERE id = ? '
            "AND (next_retry_at IS NULL OR next_retry_at <= datetime('now'))",
            (next_text, _ai_usage_now_text(), str(event_id))
        )
        conn.commit()
        return (cursor.rowcount or 0) > 0
    return True


def get_ai_events_needing_reconcile(limit=10, tenant_id=None, draft_id=None,
                                    presentation_id=None, include_settled=False):
    """Oldest-first rows whose dollar cost still needs the provider.

    No age cutoff is applied here. Rows older than 24 hours stay eligible
    until they settle or exhaust their attempts and move to needs_review.
    """
    conn = get_db()
    cols = _ai_usage_columns(conn)
    has_status = 'attempt_status' in cols
    clauses = []
    params = []
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(tenant_id)
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(presentation_id)
    if include_settled:
        clauses.append('generation_id IS NOT NULL')
        if has_status:
            clauses.append("(attempt_status IS NULL OR attempt_status != 'needs_review')")
    else:
        clauses.append('generation_id IS NOT NULL')
        has_verify_cols = {'cost_source', 'generation_cost_usd'} <= cols
        if has_verify_cols:
            # /generation total_cost is the source of truth. Rows settled from
            # the chat response keep their provisional figure until one
            # generation lookup overwrites it, so the stored total converges
            # to the dashboard figure instead of sticking at a stale value.
            clauses.append("(cost_usd IS NULL OR (cost_source = 'response' AND generation_cost_usd IS NULL))")
        else:
            clauses.append('cost_usd IS NULL')
        if has_status:
            if has_verify_cols:
                clauses.append("(attempt_status IS NULL OR attempt_status NOT IN ('settled', 'needs_review') OR (attempt_status = 'settled' AND cost_source = 'response' AND generation_cost_usd IS NULL))")
            else:
                clauses.append("(attempt_status IS NULL OR attempt_status NOT IN ('settled', 'needs_review'))")
            clauses.append("(next_retry_at IS NULL OR next_retry_at <= datetime('now'))")
    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    select_cols = ('id, tenant_id, draft_id, presentation_id, flow, model, status, '
                   'prompt_tokens, completion_tokens, total_tokens, cost_usd, generation_id, created_at')
    if {'cost_source', 'attempt_status', 'reconcile_attempts', 'next_retry_at',
        'updated_at', 'response_cost_usd', 'generation_cost_usd', 'cost_raw'} <= cols:
        select_cols += (', cost_source, attempt_status, reconcile_attempts, next_retry_at, '
                        'updated_at, response_cost_usd, generation_cost_usd, cost_raw')
    params.append(int(limit))
    rows = conn.execute(
        f'SELECT {select_cols} FROM ai_usage_events {where} '
        'ORDER BY created_at ASC LIMIT ?',
        params
    ).fetchall()
    return [dict(r) for r in rows]


def get_ai_usage_status_counts(tenant_id, draft_id=None, presentation_id=None):
    """Auditable per-scope counts with no misleading capped total."""
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(presentation_id)
    where = 'WHERE ' + ' AND '.join(clauses)
    conn = get_db()
    cols = _ai_usage_columns(conn)
    counts = {'total': 0, 'settled': 0, 'pending': 0, 'in_flight': 0,
              'unresolved': 0, 'needs_review': 0, 'unknown_cost': 0, 'pending_costs': 0}
    if 'attempt_status' in cols:
        for row in conn.execute(
            'SELECT COALESCE(attempt_status, '
            "CASE WHEN cost_usd IS NOT NULL THEN 'settled' "
            "WHEN generation_id IS NOT NULL THEN 'pending' "
            "ELSE 'unresolved' END) AS st, COUNT(*) AS n "
            f'FROM ai_usage_events {where} GROUP BY st',
            params
        ).fetchall():
            row = dict(row)
            key = str(row.get('st') or '')
            if key in counts:
                counts[key] = int(row.get('n') or 0)
            counts['total'] += int(row.get('n') or 0)
    else:
        row = dict(conn.execute(f'SELECT COUNT(*) AS n FROM ai_usage_events {where}', params).fetchone())
        counts['total'] = int(row.get('n') or 0)
        row = dict(conn.execute(
            f'SELECT COUNT(*) AS n FROM ai_usage_events {where} AND cost_usd IS NOT NULL', params).fetchone())
        counts['settled'] = int(row.get('n') or 0)
        row = dict(conn.execute(
            f'SELECT COUNT(*) AS n FROM ai_usage_events {where} AND cost_usd IS NULL AND generation_id IS NOT NULL',
            params).fetchone())
        counts['pending'] = int(row.get('n') or 0)
        counts['unresolved'] = counts['total'] - counts['settled'] - counts['pending']
    unknown = dict(conn.execute(
        f'SELECT COUNT(*) AS n FROM ai_usage_events {where} AND cost_usd IS NULL', params).fetchone())
    counts['unknown_cost'] = int(unknown.get('n') or 0)
    pending = dict(conn.execute(
        f'SELECT COUNT(*) AS n FROM ai_usage_events {where} AND cost_usd IS NULL AND generation_id IS NOT NULL',
        params).fetchone())
    counts['pending_costs'] = int(pending.get('n') or 0)
    if counts['in_flight'] or counts['pending']:
        state, label = 'pending', 'قيد الاستكمال'
    elif counts['unresolved'] or counts['needs_review']:
        state, label = 'needs_review', 'تحتاج مطابقة'
    else:
        state, label = 'settled', 'التكلفة المسجلة'
    counts['state'] = state
    counts['state_label'] = label
    return counts


def get_ai_usage_events_page(tenant_id, draft_id=None, presentation_id=None,
                             page=1, page_size=20):
    """Paginated provider attempts with generation id, cost, source and state."""
    try:
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = max(1, min(100, int(page_size or 20)))
    except (TypeError, ValueError):
        page_size = 20
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(presentation_id)
    where = 'WHERE ' + ' AND '.join(clauses)
    conn = get_db()
    cols = _ai_usage_columns(conn)
    total = int(dict(conn.execute(
        f'SELECT COUNT(*) AS n FROM ai_usage_events {where}', params).fetchone()).get('n') or 0)
    select_cols = ('id, draft_id, presentation_id, flow, model, status, prompt_tokens, '
                   'completion_tokens, total_tokens, cost_usd, generation_id, created_at')
    if {'cost_source', 'attempt_status', 'reconcile_attempts', 'next_retry_at',
        'updated_at', 'response_cost_usd', 'generation_cost_usd', 'cost_raw'} <= cols:
        select_cols += (', cost_source, attempt_status, reconcile_attempts, next_retry_at, '
                        'updated_at, response_cost_usd, generation_cost_usd, cost_raw')
    offset = (page - 1) * page_size
    rows = [dict(r) for r in conn.execute(
        f'SELECT {select_cols} FROM ai_usage_events {where} '
        'ORDER BY created_at DESC LIMIT ? OFFSET ?',
        params + [page_size, offset]
    ).fetchall()]
    return {'items': rows, 'page': page, 'page_size': page_size, 'total': total,
            'pages': ((total + page_size - 1) // page_size) if total else 0}


def decimal_cost_total(values):
    """Sum dollar figures with Decimal so display rounding never rewrites history."""
    from decimal import Decimal
    total = Decimal('0')
    for value in (values or []):
        if value is None:
            continue
        try:
            if isinstance(value, bool):
                continue
            total += Decimal(str(value))
        except Exception:
            continue
    return total


def get_ai_usage_summary(tenant_id, draft_id=None, presentation_id=None, limit=50):
    """Tenant-scoped consumption totals grouped by flow and model, plus recent events."""
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(presentation_id)
    where = 'WHERE ' + ' AND '.join(clauses)
    conn = get_db()
    cols = _ai_usage_columns(conn)
    totals = dict(conn.execute(
        'SELECT COUNT(*) AS calls, '
        'COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, '
        'COALESCE(SUM(completion_tokens), 0) AS completion_tokens, '
        'COALESCE(SUM(total_tokens), 0) AS total_tokens, '
        'COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM ai_usage_events {where}',
        params
    ).fetchone())
    by_flow = [dict(r) for r in conn.execute(
        'SELECT flow, COUNT(*) AS calls, '
        'COALESCE(SUM(total_tokens), 0) AS total_tokens, '
        'COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM ai_usage_events {where} GROUP BY flow ORDER BY total_tokens DESC',
        params
    ).fetchall()]
    by_model = [dict(r) for r in conn.execute(
        'SELECT model, COUNT(*) AS calls, '
        'COALESCE(SUM(total_tokens), 0) AS total_tokens, '
        'COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM ai_usage_events {where} GROUP BY model ORDER BY total_tokens DESC',
        params
    ).fetchall()]
    select_cols = ('id, draft_id, presentation_id, flow, model, status, prompt_tokens, '
                   'completion_tokens, total_tokens, cost_usd, generation_id, created_at')
    if {'cost_source', 'attempt_status', 'reconcile_attempts', 'next_retry_at',
        'updated_at', 'response_cost_usd', 'generation_cost_usd', 'cost_raw'} <= cols:
        select_cols += (', cost_source, attempt_status, reconcile_attempts, next_retry_at, '
                        'updated_at, response_cost_usd, generation_cost_usd, cost_raw')
    recent = [dict(r) for r in conn.execute(
        f'SELECT {select_cols} '
        f'FROM ai_usage_events {where} ORDER BY created_at DESC LIMIT ?',
        params + [int(limit)]
    ).fetchall()]
    try:
        status = get_ai_usage_status_counts(tenant_id, draft_id=draft_id, presentation_id=presentation_id)
    except Exception:
        status = {}
    return with_sar_fields({'totals': totals, 'by_flow': by_flow, 'by_model': by_model,
                            'recent': recent, 'status': status})


def get_ai_usage_pending_costs(limit=15, tenant_id=None):
    """Oldest-first events that carry a generation id but no dollar cost yet.

    Oldest first so a busy project never starves its earliest attempts.
    No age cutoff is applied here so rows older than 24 hours stay visible
    until they settle or move to needs_review through the review path.
    """
    conn = get_db()
    cols = _ai_usage_columns(conn)
    clauses = ['cost_usd IS NULL', 'generation_id IS NOT NULL']
    params = []
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(tenant_id)
    if 'attempt_status' in cols:
        clauses.append("(attempt_status IS NULL OR attempt_status NOT IN ('settled', 'needs_review'))")
    params.append(int(limit))
    select_cols = 'id, generation_id, created_at'
    if {'tenant_id', 'draft_id', 'presentation_id', 'attempt_status',
        'reconcile_attempts', 'cost_source'} <= cols:
        select_cols = ('id, tenant_id, draft_id, presentation_id, generation_id, created_at, '
                       'attempt_status, reconcile_attempts, cost_source')
    rows = conn.execute(
        'SELECT ' + select_cols + ' FROM ai_usage_events '
        f"WHERE {' AND '.join(clauses)} ORDER BY created_at ASC LIMIT ?",
        params
    ).fetchall()
    return [dict(r) for r in rows]


def record_maps_usage_event(tenant_id, sku, units, unit_price_usd,
                            flow='other', draft_id=None, presentation_id=None):
    """Persist one billable Google Maps call.

    The unit price is stored on the row, so a later price change never rewrites
    history. Only completed provider requests are recorded: cached reads and
    failed calls carry no spend.
    """
    conn = get_db()
    event_id = str(uuid.uuid4())
    units = max(0, int(units or 0))
    price = float(unit_price_usd or 0.0)
    try:
        cols = {row['name'] for row in conn.execute('PRAGMA table_info(map_usage_events)').fetchall()}
    except Exception:
        cols = set()
    package_id = _tenant_active_package_id(conn, tenant_id)
    if 'package_id' in cols:
        conn.execute(
            '''INSERT INTO map_usage_events
               (id, tenant_id, draft_id, presentation_id, flow, sku, units, unit_price_usd, cost_usd, package_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (event_id, tenant_id, draft_id, presentation_id, flow or 'other',
             sku, units, price, units * price, package_id)
        )
    else:
        conn.execute(
            '''INSERT INTO map_usage_events
               (id, tenant_id, draft_id, presentation_id, flow, sku, units, unit_price_usd, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (event_id, tenant_id, draft_id, presentation_id, flow or 'other',
             sku, units, price, units * price)
        )
    conn.commit()
    return event_id


def get_maps_usage_summary(tenant_id, draft_id=None, presentation_id=None, limit=50):
    """Tenant-scoped Maps spend grouped by flow and SKU, plus recent events."""
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(presentation_id)
    where = 'WHERE ' + ' AND '.join(clauses)
    conn = get_db()
    totals = dict(conn.execute(
        'SELECT COUNT(*) AS calls, '
        'COALESCE(SUM(units), 0) AS units, '
        'COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM map_usage_events {where}',
        params
    ).fetchone())
    by_flow = [dict(r) for r in conn.execute(
        'SELECT flow, COUNT(*) AS calls, '
        'COALESCE(SUM(units), 0) AS units, '
        'COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM map_usage_events {where} GROUP BY flow ORDER BY cost_usd DESC',
        params
    ).fetchall()]
    by_sku = [dict(r) for r in conn.execute(
        'SELECT sku, COUNT(*) AS calls, '
        'COALESCE(SUM(units), 0) AS units, '
        'COALESCE(SUM(cost_usd), 0) AS cost_usd, '
        'COALESCE(MAX(unit_price_usd), 0) AS unit_price_usd '
        f'FROM map_usage_events {where} GROUP BY sku ORDER BY cost_usd DESC',
        params
    ).fetchall()]
    recent = [dict(r) for r in conn.execute(
        'SELECT id, draft_id, presentation_id, flow, sku, units, unit_price_usd, '
        'cost_usd, created_at '
        f'FROM map_usage_events {where} ORDER BY created_at DESC LIMIT ?',
        params + [int(limit)]
    ).fetchall()]
    return with_sar_fields({'totals': totals, 'by_flow': by_flow, 'by_sku': by_sku, 'recent': recent})


def get_maps_discovery_cache(tenant_id, cache_key):
    """Cached Google discovery payload, or None on miss/expiry. Never raises."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT payload_json FROM maps_discovery_cache '
            "WHERE cache_key = ? AND expires_at > datetime('now')",
            (str(cache_key),)
        ).fetchone()
        if row is None:
            return None
        return json.loads(dict(row).get('payload_json') or 'null')
    except Exception:
        return None


def set_maps_discovery_cache(tenant_id, cache_key, payload, ttl_days=30):
    """Store one Google discovery payload. Never raises."""
    try:
        from datetime import timedelta
        days = max(1, int(ttl_days or 30))
        expires_at = (_utcnow() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        conn = get_db()
        conn.execute(
            'INSERT INTO maps_discovery_cache (cache_key, tenant_id, payload_json, expires_at) '
            'VALUES (?, ?, ?, ?) '
            'ON CONFLICT (cache_key) DO UPDATE SET tenant_id = excluded.tenant_id, '
            "payload_json = excluded.payload_json, created_at = datetime('now'), "
            "expires_at = excluded.expires_at",
            (str(cache_key), tenant_id, json.dumps(payload, ensure_ascii=False), expires_at)
        )
        conn.commit()
        return True
    except Exception as exc:
        print(f"[MAPS CACHE] store failed: {exc}")
        return False
