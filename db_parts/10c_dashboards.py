# ── t54: operational monitoring that never exposes client content ───────────

def _activity_bucket_pairs(months=12, from_month=None, to_month=None):
    """Bucket grid shared by the platform and company activity charts.

    Returns (labels, bucket_keys, bucket): display labels, the substr() prefix
    per bucket, and the prefix width (7 = month, 10 = day, 13 = hour).
    """
    now = _utcnow()

    def _parse_range_dt(value, is_end=False):
        s = str(value or '').strip()
        try:
            if len(s) >= 16:
                return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]),
                                int(s[11:13]), int(s[14:16])), True
            if len(s) >= 10:
                d = datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]))
                return (d + timedelta(days=1) - timedelta(seconds=1)) if is_end else d, False
            if len(s) == 7:
                y, m = int(s[0:4]), int(s[5:7])
                d = datetime(y, m, 1)
                if is_end:
                    d = datetime(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1) - timedelta(seconds=1)
                return d, False
        except (ValueError, IndexError):
            pass
        return None, False

    pairs = []  # (display label, substr bucket key)
    (start_dt, s_has_time), (end_dt, e_has_time) = _parse_range_dt(from_month), _parse_range_dt(to_month, is_end=True)
    bucket = 7
    if start_dt and end_dt:
        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt
        span = end_dt - start_dt
        hourly = span <= timedelta(hours=48) if (s_has_time or e_has_time) else start_dt.date() == end_dt.date()
        if hourly:
            bucket = 13
            cur = start_dt.replace(minute=0, second=0, microsecond=0)
            while cur <= end_dt and len(pairs) < 96:
                pairs.append(('%04d-%02d-%02d %02d:00' % (cur.year, cur.month, cur.day, cur.hour),
                              '%04d-%02d-%02d %02d' % (cur.year, cur.month, cur.day, cur.hour)))
                cur += timedelta(hours=1)
        elif span <= timedelta(days=95):
            bucket = 10
            cur = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            while cur <= end_dt and len(pairs) < 96:
                key = '%04d-%02d-%02d' % (cur.year, cur.month, cur.day)
                pairs.append((key, key))
                cur += timedelta(days=1)
        else:
            cur = start_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            while cur <= end_dt and len(pairs) < 37:
                key = '%04d-%02d' % (cur.year, cur.month)
                pairs.append((key, key))
                cur = datetime(cur.year + (1 if cur.month == 12 else 0),
                               1 if cur.month == 12 else cur.month + 1, 1)
    if not pairs:
        try:
            months = max(1, min(int(months or 12), 36))
        except (TypeError, ValueError):
            months = 12
        for i in range(months - 1, -1, -1):
            mm = now.month - i
            yy = now.year + (mm - 1) // 12
            mm = (mm - 1) % 12 + 1
            key = '%04d-%02d' % (yy, mm)
            pairs.append((key, key))
    return [p[0] for p in pairs], [p[1] for p in pairs], bucket


def operational_overview(months=12, from_month=None, to_month=None):
    """Counts and activity shape only: the super-admin never sees client content."""
    conn = get_db()
    def count(table, where='1 = 1', params=()):
        try:
            row = conn.execute('SELECT COUNT(*) AS n FROM ' + table + ' WHERE ' + where, params).fetchone()
            return int(row['n'] or 0)
        except Exception:
            return 0

    def monthly_map(table, value_sql='COUNT(*)', date_col='created_at', where='1 = 1', bucket=7):
        try:
            rows = conn.execute(
                'SELECT substr(' + date_col + ', 1, ' + str(int(bucket)) + ') AS m, ' + value_sql + ' AS v FROM ' + table +
                ' WHERE ' + where + ' AND ' + date_col + ' IS NOT NULL GROUP BY m'
            ).fetchall()
            return {r['m']: float(r['v'] or 0) for r in rows if r['m']}
        except Exception:
            return {}

    now = _utcnow()
    labels, bucket_keys, bucket = _activity_bucket_pairs(months, from_month, to_month)

    series_maps = {
        'companies': monthly_map('tenants', where='is_admin = 0', bucket=bucket),
        'presentations': monthly_map('presentations', bucket=bucket),
        'users': monthly_map('users', bucket=bucket),
        'ai_spend': monthly_map('ai_usage_events', 'COALESCE(SUM(cost_usd), 0)', bucket=bucket),
        'maps_spend': monthly_map('map_usage_events', 'COALESCE(SUM(cost_usd), 0)', bucket=bucket),
        'revenue': monthly_map('recharge_requests', 'COALESCE(SUM(amount_usd), 0)',
                               date_col='reviewed_at', where="status = 'approved'", bucket=bucket),
        # Recharges are paid in riyals — the SAR series reads price_sar
        # directly instead of converting the wallet-dollar figure.
        'revenue_sar': monthly_map('recharge_requests', 'COALESCE(SUM(price_sar), 0)',
                                   date_col='reviewed_at', where="status = 'approved'", bucket=bucket),
        'tickets': monthly_map('support_tickets', bucket=bucket),
    }
    try:
        fx_rate = float((get_fx_rate() or {}).get('rate') or FX_DEFAULT_USD_SAR)
    except (TypeError, ValueError):
        fx_rate = FX_DEFAULT_USD_SAR
    trends = {'labels': labels}
    for key, mmap in series_maps.items():
        trends[key] = [round(mmap.get(k, 0), 2) for k in bucket_keys]
    trends['ai_spend_sar'] = [usd_to_sar(v, fx_rate) for v in trends['ai_spend']]
    trends['maps_spend_sar'] = [usd_to_sar(v, fx_rate) for v in trends['maps_spend']]

    def delta(mmap):
        cur = mmap.get(bucket_keys[-1], 0)
        prev = mmap.get(bucket_keys[-2], 0)
        if not prev:
            return None
        return round((cur - prev) / float(prev) * 100)

    ticket_status = {}
    try:
        for r in conn.execute('SELECT status, COUNT(*) AS n FROM support_tickets GROUP BY status').fetchall():
            ticket_status[r['status'] or 'open'] = int(r['n'] or 0)
    except Exception:
        pass

    spend_map = series_maps['ai_spend']
    maps_map = series_maps['maps_spend']
    revenue_map = series_maps['revenue']
    return {
        'tenants': {
            'total': count('tenants'),
            'companies': count('tenants', 'is_admin = 0'),
            'active': count('tenants', 'is_active = 1'),
            'active_companies': count('tenants', 'is_active = 1 AND is_admin = 0'),
        },
        'users': {'total': count('users'), 'active': count('users', 'is_active = 1')},
        'drafts': {'total': count('project_drafts')},
        'presentations': {'total': count('presentations'), 'approved': count('presentations', "status = 'approved'")},
        'workflows': {
            'pending_recharges': count('recharge_requests', "status = 'pending'"),
            'open_support_tickets': count('support_tickets', "status IN ('open', 'in_progress', 'waiting_customer')"),
            'open_tasks': count('approval_tasks', "status = 'open'"),
        },
        'tickets_by_status': ticket_status,
        'revenue': {
            'month_usd': round(revenue_map.get(bucket_keys[-1], 0), 2),
            'total_usd': round(sum(revenue_map.values()), 2),
            'month_sar': round(series_maps['revenue_sar'].get(bucket_keys[-1], 0), 2),
            'total_sar': round(sum(series_maps['revenue_sar'].values()), 2),
        },
        'spend': {
            'month_usd': round(spend_map.get(bucket_keys[-1], 0) + maps_map.get(bucket_keys[-1], 0), 2),
            'total_usd': round(sum(spend_map.values()) + sum(maps_map.values()), 2),
            'month_sar': usd_to_sar(
                spend_map.get(bucket_keys[-1], 0) + maps_map.get(bucket_keys[-1], 0), fx_rate),
            'total_sar': usd_to_sar(
                sum(spend_map.values()) + sum(maps_map.values()), fx_rate),
        },
        'trends': trends,
        'deltas': {
            'companies': delta(series_maps['companies']),
            'presentations': delta(series_maps['presentations']),
            'users': delta(series_maps['users']),
            'spend': delta({k: spend_map.get(k, 0) + maps_map.get(k, 0) for k in bucket_keys}),
            'revenue': delta(revenue_map),
            'tickets': delta(series_maps['tickets']),
        },
        'storage': storage_overview(),
        'generation': generation_job_metrics(),
        'queue': _job_queue_metrics(),
        'email': _email_outbox_metrics(),
        'alerts': platform_alerts(),
        'backup': {
            'rpo_hours': RPO_TARGET_HOURS,
            'rto_hours': RTO_TARGET_HOURS,
            'latest': latest_successful_backup(),
        },
        'generated_at': now.isoformat(),
    }


def _job_queue_metrics():
    conn = get_db()
    result = {'queued': 0, 'running': 0, 'done': 0, 'failed': 0, 'dead': 0}
    try:
        for row in conn.execute('SELECT status, COUNT(*) AS n FROM job_queue GROUP BY status').fetchall():
            if row['status'] in result:
                result[row['status']] = int(row['n'] or 0)
    except Exception:
        pass
    return result


def _email_outbox_metrics():
    conn = get_db()
    result = {'queued': 0, 'sent': 0, 'failed': 0}
    try:
        for row in conn.execute('SELECT status, COUNT(*) AS n FROM email_outbox GROUP BY status').fetchall():
            if row['status'] in result:
                result[row['status']] = int(row['n'] or 0)
    except Exception:
        pass
    return result


# ═════════════════════════════════════════════════════════════════════════════
# t55: dashboards and exportable reports
# ═════════════════════════════════════════════════════════════════════════════


def client_dashboard(tenant_id):
    """Client home: lifecycle buckets, open work, balance and month spend (t55)."""
    conn = get_db()
    tenant_id = str(tenant_id)
    by_status = {}
    try:
        for row in conn.execute(
            'SELECT status, COUNT(*) AS n FROM project_drafts WHERE tenant_id = ? GROUP BY status',
            (tenant_id,),
        ).fetchall():
            by_status[normalize_proposal_status(row['status'])] = \
                by_status.get(normalize_proposal_status(row['status']), 0) + int(row['n'] or 0)
    except Exception:
        pass
    lifecycle = [{'key': key, 'label': meta.get('label'), 'label_en': meta.get('label_en'),
                  'count': by_status.get(key, 0)}
                 for key, meta in sorted(PROPOSAL_LIFECYCLE_STATES.items(),
                                         key=lambda kv: kv[1].get('order', 0))]

    def _count(table, where='1 = 1', params=()):
        try:
            return int(conn.execute(
                f'SELECT COUNT(*) AS n FROM {table} WHERE tenant_id = ? AND {where}',
                (tenant_id,) + tuple(params)).fetchone()['n'] or 0)
        except Exception:
            return 0

    month_prefix = _utcnow().strftime('%Y-%m')
    month_ai = 0.0
    month_maps = 0.0
    try:
        month_ai = float(conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS t FROM ai_usage_events "
            "WHERE tenant_id = ? AND substr(created_at, 1, 7) = ?",
            (tenant_id, month_prefix)).fetchone()['t'] or 0.0)
        month_maps = float(conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS t FROM map_usage_events "
            "WHERE tenant_id = ? AND substr(created_at, 1, 7) = ?",
            (tenant_id, month_prefix)).fetchone()['t'] or 0.0)
    except Exception:
        pass
    recent_files = []
    try:
        for row in conn.execute(
            '''SELECT id, title, status, updated_at FROM project_drafts
               WHERE tenant_id = ? ORDER BY updated_at DESC LIMIT 8''',
            (tenant_id,),
        ).fetchall():
            item = dict(row)
            item['status'] = normalize_proposal_status(item.get('status'))
            item['status_label'] = PROPOSAL_LIFECYCLE_STATES.get(item['status'], {}).get('label')
            recent_files.append(item)
    except Exception:
        pass
    notifications_unread = 0
    try:
        notifications_unread = int(conn.execute(
            'SELECT COUNT(*) AS n FROM notifications WHERE tenant_id = ? AND read_at IS NULL',
            (tenant_id,),
        ).fetchone()['n'] or 0)
    except Exception:
        pass
    return {
        'lifecycle': lifecycle,
        'open_approval_tasks': _count('approval_tasks', "status = 'open'"),
        'open_event_tasks': _count('event_tasks', "status = 'open'"),
        'open_tickets': _count('support_tickets', "status IN ('open', 'in_progress', 'waiting_customer')"),
        'unread_notifications': notifications_unread,
        'month_consumption_usd': round(month_ai + month_maps, 4),
        'month_consumption_sar': usd_to_sar(month_ai + month_maps),
        'recent_files': recent_files,
        'pending_generation': _count('generation_approvals', "status = 'pending'"),
        'pending_final': _count('final_file_approvals', "status = 'pending'"),
    }


def client_activity_trends(tenant_id, months=12, from_month=None, to_month=None):
    """Company-scoped series for the dashboard activity chart.

    Same bucket grid as the super-admin platform chart, but every series is
    filtered to the tenant: spend (AI + maps) and newly created presentations.
    """
    conn = get_db()
    tenant_id = str(tenant_id)
    labels, bucket_keys, bucket = _activity_bucket_pairs(months, from_month, to_month)

    def monthly_map(table, value_sql='COUNT(*)', date_col='created_at'):
        try:
            rows = conn.execute(
                'SELECT substr(' + date_col + ', 1, ' + str(int(bucket)) + ') AS m, ' + value_sql + ' AS v FROM ' + table +
                ' WHERE tenant_id = ? AND ' + date_col + ' IS NOT NULL GROUP BY m',
                (tenant_id,)).fetchall()
            return {r['m']: float(r['v'] or 0) for r in rows if r['m']}
        except Exception:
            return {}

    series_maps = {
        'presentations': monthly_map('presentations'),
        'ai_spend': monthly_map('ai_usage_events', 'COALESCE(SUM(cost_usd), 0)'),
        'maps_spend': monthly_map('map_usage_events', 'COALESCE(SUM(cost_usd), 0)'),
    }
    try:
        fx_rate = float((get_fx_rate() or {}).get('rate') or FX_DEFAULT_USD_SAR)
    except (TypeError, ValueError):
        fx_rate = FX_DEFAULT_USD_SAR
    trends = {'labels': labels}
    for key, mmap in series_maps.items():
        trends[key] = [round(mmap.get(k, 0), 2) for k in bucket_keys]
    trends['ai_spend_sar'] = [usd_to_sar(v, fx_rate) for v in trends['ai_spend']]
    trends['maps_spend_sar'] = [usd_to_sar(v, fx_rate) for v in trends['maps_spend']]
    return trends


def company_admin_dashboard(tenant_id):
    """Company super-admin view: overdue sections, approval speed, spend split."""
    conn = get_db()
    tenant_id = str(tenant_id)
    now = _utcnow()
    from datetime import timedelta

    overdue_sections = []
    try:
        cutoff = (now - timedelta(hours=72)).isoformat()
        rows = conn.execute(
            '''SELECT sv.id, sv.draft_id, sv.section_key, sv.version_number, sv.created_at,
                      pd.title AS draft_title
               FROM section_versions sv LEFT JOIN project_drafts pd ON pd.id = sv.draft_id
               WHERE sv.tenant_id = ? AND sv.status = 'pending' AND sv.created_at < ?
               ORDER BY sv.created_at LIMIT 50''',
            (tenant_id, cutoff),
        ).fetchall()
        overdue_sections = [dict(r) for r in rows]
    except Exception:
        overdue_sections = []

    avg_approval_hours = None
    try:
        rows = conn.execute(
            '''SELECT created_at, decided_at FROM section_versions
               WHERE tenant_id = ? AND decided_at IS NOT NULL
               ORDER BY decided_at DESC LIMIT 200''',
            (tenant_id,),
        ).fetchall()
        total = 0.0
        counted = 0
        for row in rows:
            try:
                total += (datetime.fromisoformat(row['decided_at'])
                          - datetime.fromisoformat(row['created_at'])).total_seconds()
                counted += 1
            except (TypeError, ValueError):
                continue
        if counted:
            avg_approval_hours = round(total / counted / 3600, 1)
    except Exception:
        pass

    spend_by_project = []
    try:
        rows = conn.execute(
            '''SELECT COALESCE(draft_id, presentation_id) AS ref, COALESCE(SUM(cost_usd), 0) AS total
               FROM ai_usage_events WHERE tenant_id = ?
               GROUP BY ref ORDER BY total DESC LIMIT 20''',
            (tenant_id,),
        ).fetchall()
        titles = {}
        for row in conn.execute(
            'SELECT id, title FROM project_drafts WHERE tenant_id = ?', (tenant_id,),
        ).fetchall():
            titles[row['id']] = row['title']
        for row in conn.execute(
            'SELECT id, title FROM presentations WHERE tenant_id = ?', (tenant_id,),
        ).fetchall():
            titles[row['id']] = row['title']
        for row in rows:
            spend_by_project.append({
                'ref': row['ref'],
                'title': titles.get(row['ref']) or row['ref'],
                'total_usd': round(float(row['total'] or 0), 4),
            })
    except Exception:
        spend_by_project = []

    spend_by_user = []
    try:
        rows = conn.execute(
            '''SELECT user_name, COUNT(*) AS events FROM audit_events
               WHERE tenant_id = ? AND user_name IS NOT NULL
               GROUP BY user_name ORDER BY events DESC LIMIT 20''',
            (tenant_id,),
        ).fetchall()
        spend_by_user = [{'user_name': r['user_name'], 'events': int(r['events'] or 0)}
                         for r in rows]
    except Exception:
        spend_by_user = []

    pending_approvals = 0
    try:
        pending_approvals = int(conn.execute(
            "SELECT COUNT(*) AS n FROM section_versions WHERE tenant_id = ? AND status = 'pending'",
            (tenant_id,),
        ).fetchone()['n'] or 0)
    except Exception:
        pass

    return with_sar_fields({
        'overdue_sections': overdue_sections,
        'overdue_count': len(overdue_sections),
        'avg_approval_hours': avg_approval_hours,
        'pending_section_approvals': pending_approvals,
        'spend_by_project': spend_by_project,
        'activity_by_user': spend_by_user,
    })


def ledger_report_rows(tenant_id=None, from_date=None, to_date=None, kind=None, limit=5000):
    """Points-ledger report rows: every wallet movement (t32/t55)."""
    conn = get_db()
    clauses = []
    params = []
    if tenant_id:
        clauses.append('l.tenant_id = ?')
        params.append(str(tenant_id))
    if kind:
        clauses.append('l.kind = ?')
        params.append(str(kind))
    if from_date:
        clauses.append('l.created_at >= ?')
        params.append(_norm_range_bound(from_date))
    if to_date:
        clauses.append('l.created_at <= ?')
        params.append(_norm_range_bound(to_date, is_end=True))
    query = ('SELECT l.*, t.company_name FROM tenant_ledger l '
             'LEFT JOIN tenants t ON t.id = l.tenant_id')
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY l.created_at DESC LIMIT ?'
    params.append(int(limit))
    rows = conn.execute(query, params).fetchall()
    headers = ['التاريخ', 'الشركة', 'النوع', 'المبلغ (ريال)', 'التكلفة الخام (ريال)', 'المضاعف',
               'أحداث AI', 'أحداث الخرائط', 'مرجع عدم التكرار', 'ملاحظة']
    body = [[r['created_at'], r['company_name'], r['kind'], usd_to_sar(r['amount_usd']),
             usd_to_sar(r['raw_cost_usd']), r['multiplier'], r['ai_events_count'],
             r['maps_events_count'], r['idempotency_key'], r['note']] for r in rows]
    return headers, body


def tickets_report_rows(tenant_id=None, from_date=None, to_date=None, limit=5000):
    """Support tickets report rows."""
    conn = get_db()
    clauses = []
    params = []
    if tenant_id:
        clauses.append('t.tenant_id = ?')
        params.append(str(tenant_id))
    if from_date:
        clauses.append('t.created_at >= ?')
        params.append(_norm_range_bound(from_date))
    if to_date:
        clauses.append('t.created_at <= ?')
        params.append(_norm_range_bound(to_date, is_end=True))
    query = ('SELECT t.*, tn.company_name FROM support_tickets t '
             'LEFT JOIN tenants tn ON tn.id = t.tenant_id')
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY t.created_at DESC LIMIT ?'
    params.append(int(limit))
    rows = conn.execute(query, params).fetchall()
    headers = ['الرقم', 'الشركة', 'العنوان', 'الفئة', 'الأولوية', 'الحالة', 'المنشئ',
               'أول استجابة', 'أنشئت', 'حُلّت', 'أُغلقت']
    body = [[r['number'], r['company_name'], r['subject'], r['category'], r['priority'],
             r['status'], r['created_by_name'], r['first_response_at'],
             r['created_at'], r['resolved_at'], r['closed_at']]
            for r in rows]
    return headers, body


# ─────────────────────────────────────────────────────────────────────────────
# Stats (Admin)
# ─────────────────────────────────────────────────────────────────────────────

def get_stats():
    """Get global stats for admin dashboard."""
    conn = get_db()
    tenants_count = conn.execute('SELECT COUNT(*) as c FROM tenants WHERE is_admin = 0').fetchone()['c']
    presentations_count = conn.execute('SELECT COUNT(*) as c FROM presentations').fetchone()['c']
    exports_count = conn.execute('SELECT COUNT(*) as c FROM exports').fetchone()['c']
    active_tenants = conn.execute('SELECT COUNT(*) as c FROM tenants WHERE is_active = 1 AND is_admin = 0').fetchone()['c']
    users_count = conn.execute('SELECT COUNT(*) as c FROM users').fetchone()['c']
    return {
        'tenants': tenants_count,
        'active_tenants': active_tenants,
        'users': users_count,
        'presentations': presentations_count,
        'exports': exports_count,
    }
