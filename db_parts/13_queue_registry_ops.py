

def create_document_version(tenant_id, document_type, document_id, file_id=None,
                            content_hash=None, approval_id=None, generated_by=None,
                            generated_by_name=None):
    """Version every produced document; the next number is per document id."""
    conn = get_db()
    row = conn.execute(
        'SELECT COALESCE(MAX(version), 0) + 1 AS next FROM document_versions '
        'WHERE tenant_id = ? AND document_type = ? AND document_id = ?',
        (str(tenant_id), str(document_type), str(document_id)),
    ).fetchone()
    version = int(row['next'])
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO document_versions
           (id, tenant_id, document_type, document_id, version, file_id, content_hash,
            approval_id, generated_by, generated_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, str(tenant_id), str(document_type), str(document_id), version,
         file_id, content_hash, approval_id, generated_by, generated_by_name),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM document_versions WHERE id = ?', (row_id,)).fetchone())


def list_document_versions(tenant_id, document_type=None, document_id=None):
    conn = get_db()
    clauses = ['tenant_id = ?']
    params = [str(tenant_id)]
    if document_type:
        clauses.append('document_type = ?')
        params.append(str(document_type))
    if document_id:
        clauses.append('document_id = ?')
        params.append(str(document_id))
    rows = conn.execute(
        'SELECT * FROM document_versions WHERE ' + ' AND '.join(clauses) +
        ' ORDER BY created_at DESC', params,
    ).fetchall()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# t61: persistent job queue + email outbox (survive process restarts)
# ═════════════════════════════════════════════════════════════════════════════


def enqueue_job(job_type, payload=None, tenant_id=None, priority=100, run_after=None,
                correlation_id=None, max_attempts=3):
    """Put a unit of background work on the durable queue."""
    conn = get_db()
    job_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO job_queue
           (id, tenant_id, job_type, payload_json, priority, run_after, max_attempts, correlation_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (job_id, str(tenant_id) if tenant_id else None, str(job_type),
         json.dumps(payload or {}, ensure_ascii=False), int(priority), run_after,
         int(max_attempts), correlation_id),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM job_queue WHERE id = ?', (job_id,)).fetchone())


def claim_due_jobs(worker_id, limit=5, now=None):
    """Atomically mark due queued jobs running for this worker and return them."""
    conn = get_db()
    now = now or _utcnow().isoformat()
    conn.execute(
        '''UPDATE job_queue SET status = 'running', locked_by = ?, locked_at = ?,
           started_at = COALESCE(started_at, ?), attempts = attempts + 1
           WHERE id IN (
               SELECT id FROM job_queue
               WHERE status = 'queued' AND (run_after IS NULL OR run_after <= ?)
               ORDER BY priority, created_at LIMIT ?
           )''',
        (str(worker_id), now, now, now, int(limit)),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT * FROM job_queue WHERE status = 'running' AND locked_by = ? ORDER BY priority, created_at",
        (str(worker_id),),
    ).fetchall()
    result = []
    for row in rows[:int(limit)]:
        item = dict(row)
        item['payload'] = _json_or(item.get('payload_json'), {})
        result.append(item)
    return result


def complete_job(job_id, worker_id=None):
    conn = get_db()
    conn.execute(
        "UPDATE job_queue SET status = 'done', finished_at = ?, locked_by = NULL "
        "WHERE id = ? AND status = 'running'",
        (_utcnow().isoformat(), str(job_id)),
    )
    conn.commit()


def fail_job(job_id, error=None, retry_delay_seconds=60, worker_id=None):
    """Record a failure; retry while attempts remain, then mark dead."""
    conn = get_db()
    row = conn.execute('SELECT * FROM job_queue WHERE id = ?', (str(job_id),)).fetchone()
    if not row:
        return
    now = _utcnow()
    from datetime import timedelta
    error_text = str(error or '')[:2000]
    if int(row['attempts'] or 0) < int(row['max_attempts'] or 1):
        run_after = (now + timedelta(seconds=int(retry_delay_seconds))).isoformat()
        conn.execute(
            """UPDATE job_queue SET status = 'queued', run_after = ?, locked_by = NULL,
               last_error = ? WHERE id = ?""",
            (run_after, error_text, str(job_id)),
        )
    else:
        conn.execute(
            "UPDATE job_queue SET status = 'dead', finished_at = ?, last_error = ? WHERE id = ?",
            (now.isoformat(), error_text, str(job_id)),
        )
    conn.commit()


def requeue_dead_jobs(job_type=None, limit=100):
    """Operator action: put dead jobs back on the queue with attempts reset."""
    conn = get_db()
    clauses = ["status = 'dead'"]
    params = []
    if job_type:
        clauses.append('job_type = ?')
        params.append(str(job_type))
    rows = conn.execute(
        'SELECT id FROM job_queue WHERE ' + ' AND '.join(clauses) + ' LIMIT ?',
        list(params) + [int(limit)],
    ).fetchall()
    now = _utcnow().isoformat()
    for row in rows:
        conn.execute(
            """UPDATE job_queue SET status = 'queued', attempts = 0, run_after = ?,
               locked_by = NULL, locked_at = NULL, last_error = NULL WHERE id = ?""",
            (now, row['id']),
        )
    conn.commit()
    return len(rows)


def list_jobs(status=None, job_type=None, limit=100):
    conn = get_db()
    clauses = []
    params = []
    if status:
        clauses.append('status = ?')
        params.append(str(status))
    if job_type:
        clauses.append('job_type = ?')
        params.append(str(job_type))
    query = 'SELECT * FROM job_queue'
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY created_at DESC LIMIT ?'
    params.append(int(limit))
    result = []
    for row in conn.execute(query, params).fetchall():
        item = dict(row)
        item['payload'] = _json_or(item.get('payload_json'), {})
        result.append(item)
    return result


def enqueue_email(to_email, subject, body_text=None, body_html=None, tenant_id=None,
                  notification_id=None, related_type=None, related_id=None):
    """Outbound mail goes through the outbox so SMTP outages lose nothing."""
    conn = get_db()
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO email_outbox
           (id, tenant_id, notification_id, to_email, subject, body_text, body_html,
            related_type, related_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, str(tenant_id) if tenant_id else None,
         str(notification_id) if notification_id else None,
         str(to_email or ''), str(subject or ''), body_text, body_html,
         related_type, str(related_id) if related_id else None),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM email_outbox WHERE id = ?', (row_id,)).fetchone())


def claim_due_emails(limit=20):
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM email_outbox WHERE status = 'queued'
           ORDER BY created_at LIMIT ?""",
        (int(limit),),
    ).fetchall()
    claimed = []
    for row in rows:
        cursor = conn.execute(
            "UPDATE email_outbox SET status = 'sending', attempts = attempts + 1 "
            "WHERE id = ? AND status = 'queued'",
            (row['id'],),
        )
        if cursor.rowcount:
            claimed.append(row)
    conn.commit()
    return [dict(r) for r in claimed]


def mark_email_sent(email_id):
    conn = get_db()
    conn.execute(
        "UPDATE email_outbox SET status = 'sent', sent_at = ? WHERE id = ?",
        (_utcnow().isoformat(), str(email_id)),
    )
    conn.commit()


def mark_email_delivery(notification_id, status, error=None):
    """Reflect an outbox send result on the notification's email delivery row."""
    if not notification_id:
        return
    conn = get_db()
    now = _utcnow().isoformat()
    conn.execute(
        """UPDATE notification_deliveries
           SET status = ?, attempts = attempts + 1, last_attempt_at = ?,
               last_error = ?,
               sent_at = CASE WHEN ? = 'sent' THEN ? ELSE sent_at END,
               delivered_at = CASE WHEN ? = 'sent' THEN ? ELSE delivered_at END
           WHERE notification_id = ? AND channel = 'email'""",
        (status, now, str(error or '')[:2000] or None,
         status, now, status, now, str(notification_id)),
    )
    conn.commit()


def mark_email_failed(email_id, error=None):
    conn = get_db()
    row = conn.execute('SELECT * FROM email_outbox WHERE id = ?', (str(email_id),)).fetchone()
    if not row:
        return
    error_text = str(error or '')[:2000]
    if int(row['attempts'] or 0) < 5:
        conn.execute(
            "UPDATE email_outbox SET status = 'queued', last_error = ? WHERE id = ?",
            (error_text, str(email_id)),
        )
    else:
        conn.execute(
            "UPDATE email_outbox SET status = 'dead', last_error = ? WHERE id = ?",
            (error_text, str(email_id)),
        )
    conn.commit()


def list_email_outbox(status=None, limit=100):
    conn = get_db()
    clauses = []
    params = []
    if status:
        clauses.append('status = ?')
        params.append(str(status))
    query = 'SELECT * FROM email_outbox'
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY created_at DESC LIMIT ?'
    params.append(int(limit))
    return [dict(r) for r in conn.execute(query, params).fetchall()]


# ═════════════════════════════════════════════════════════════════════════════
# t62: study-type registry, generator registry, feature flags, schema versions
# ═════════════════════════════════════════════════════════════════════════════


def register_study_type(key, name_ar, name_en=None, definition=None,
                        supersedes_version=None, created_by=None, created_by_name=None):
    """Register a new immutable version of a study type (t62).

    The definition carries sections, fields, validation rules, the approval
    sequence and pricing hints as JSON. A re-register of the same key creates
    the next version; older versions stay addressable.
    """
    key = str(key or '').strip().lower()
    if not key or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,60}', key):
        return {'error': 'invalid_key'}
    if not str(name_ar or '').strip():
        return {'error': 'name_required'}
    conn = get_db()
    row = conn.execute(
        'SELECT COALESCE(MAX(version), 0) + 1 AS next FROM study_types WHERE key = ?', (key,)
    ).fetchone()
    version = int(row['next'])
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO study_types
           (id, key, version, name_ar, name_en, definition_json, supersedes_version,
            created_by, created_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, key, version, str(name_ar).strip(), name_en,
         json.dumps(definition or {}, ensure_ascii=False), supersedes_version,
         created_by, created_by_name),
    )
    conn.commit()
    return _study_type_public(conn.execute(
        'SELECT * FROM study_types WHERE id = ?', (row_id,)).fetchone())


def _study_type_public(row):
    if not row:
        return None
    item = dict(row)
    item['definition'] = _json_or(item.get('definition_json'), {})
    return item


def get_study_type(key, version=None, active_only=True):
    conn = get_db()
    clauses = ['key = ?']
    params = [str(key).strip().lower()]
    if version is not None:
        clauses.append('version = ?')
        params.append(int(version))
    if active_only:
        clauses.append('is_active = 1')
    row = conn.execute(
        'SELECT * FROM study_types WHERE ' + ' AND '.join(clauses) +
        ' ORDER BY version DESC LIMIT 1', params,
    ).fetchone()
    return _study_type_public(row)


def list_study_types(active_only=False, latest_only=True):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM study_types' + (' WHERE is_active = 1' if active_only else '') +
        ' ORDER BY key, version DESC'
    ).fetchall()
    seen = set()
    result = []
    for row in rows:
        item = _study_type_public(row)
        if latest_only and item['key'] in seen:
            continue
        seen.add(item['key'])
        result.append(item)
    return result


def register_generator(kind, key, config=None, label_ar=None, label_en=None,
                       supersedes_version=None):
    """Register a new version of a generator entry (slide/PDF template, output
    model, processor)."""
    kind = str(kind or '').strip().lower()
    key = str(key or '').strip().lower()
    if kind not in ('slide_template', 'pdf_template', 'content_template', 'ai_model',
                    'processor', 'exporter'):
        return {'error': 'invalid_kind'}
    if not key or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,60}', key):
        return {'error': 'invalid_key'}
    conn = get_db()
    row = conn.execute(
        'SELECT COALESCE(MAX(version), 0) + 1 AS next FROM generator_registry WHERE kind = ? AND key = ?',
        (kind, key),
    ).fetchone()
    version = int(row['next'])
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO generator_registry
           (id, kind, key, version, label_ar, label_en, config_json, supersedes_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, kind, key, version, label_ar, label_en,
         json.dumps(config or {}, ensure_ascii=False), supersedes_version),
    )
    conn.commit()
    item = dict(conn.execute('SELECT * FROM generator_registry WHERE id = ?', (row_id,)).fetchone())
    item['config'] = _json_or(item.get('config_json'), {})
    return item


def list_generators(kind=None, active_only=True):
    conn = get_db()
    clauses = []
    params = []
    if kind:
        clauses.append('kind = ?')
        params.append(str(kind))
    if active_only:
        clauses.append('is_active = 1')
    query = 'SELECT * FROM generator_registry'
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY kind, key, version DESC'
    result = []
    seen = set()
    for row in conn.execute(query, params).fetchall():
        item = dict(row)
        item['config'] = _json_or(item.get('config_json'), {})
        marker = (item['kind'], item['key'])
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def get_generator(kind, key, version=None):
    conn = get_db()
    clauses = ['kind = ?', 'key = ?', 'is_active = 1']
    params = [str(kind), str(key)]
    if version is not None:
        clauses.append('version = ?')
        params.append(int(version))
    row = conn.execute(
        'SELECT * FROM generator_registry WHERE ' + ' AND '.join(clauses) +
        ' ORDER BY version DESC LIMIT 1', params,
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item['config'] = _json_or(item.get('config_json'), {})
    return item


def snapshot_field_schema(tenant_id, created_by=None, created_by_name=None):
    """Freeze the tenant's active input fields as the next schema version."""
    conn = get_db()
    fields = conn.execute(
        'SELECT field_key, field_label, field_type, field_options, section_key, is_required, '
        'is_active, is_custom, sort_order FROM tenant_input_fields WHERE tenant_id = ? '
        'ORDER BY section_key, sort_order',
        (str(tenant_id),),
    ).fetchall()
    row = conn.execute(
        'SELECT COALESCE(MAX(version), 0) + 1 AS next FROM field_schema_versions WHERE tenant_id = ?',
        (str(tenant_id),),
    ).fetchone()
    version = int(row['next'])
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO field_schema_versions (id, tenant_id, version, schema_json, created_by, created_by_name)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (row_id, str(tenant_id), version,
         json.dumps([dict(f) for f in fields], ensure_ascii=False), created_by, created_by_name),
    )
    conn.commit()
    item = dict(conn.execute('SELECT * FROM field_schema_versions WHERE id = ?', (row_id,)).fetchone())
    item['schema'] = _json_or(item.get('schema_json'), [])
    return item


def latest_field_schema_version(tenant_id):
    conn = get_db()
    row = conn.execute(
        'SELECT version FROM field_schema_versions WHERE tenant_id = ? ORDER BY version DESC LIMIT 1',
        (str(tenant_id),),
    ).fetchone()
    return int(row['version']) if row else None


def get_file_type_rule(file_type):
    """Registry-driven upload rule for one file type (t62/d10).

    Returns the active registry row or None when the type is unknown or
    disabled — uploads must refuse types the registry does not carry.
    """
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM file_type_registry WHERE key = ? AND is_active = 1',
        (str(file_type or '').strip().lower(),),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item['allowed_extensions'] = _json_or(item.get('allowed_extensions'), [])
    return item


# ═════════════════════════════════════════════════════════════════════════════
# t63: backup registry — RPO is measurable, restore tests are recorded
# ═════════════════════════════════════════════════════════════════════════════

RPO_TARGET_HOURS = int(os.environ.get('BACKUP_RPO_HOURS', '24'))
RTO_TARGET_HOURS = int(os.environ.get('BACKUP_RTO_HOURS', '4'))


def record_backup(kind='full', path=None, size_bytes=None, sha256=None,
                  encrypted=False, note=None):
    conn = get_db()
    row_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    conn.execute(
        '''INSERT INTO backup_history
           (id, kind, status, path, size_bytes, sha256, encrypted, note, created_at, completed_at)
           VALUES (?, ?, 'done', ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, str(kind), path, size_bytes, sha256, 1 if encrypted else 0, note, now, now),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM backup_history WHERE id = ?', (row_id,)).fetchone())


def list_backups(limit=50):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM backup_history ORDER BY created_at DESC LIMIT ?', (int(limit),)
    ).fetchall()
    return [dict(r) for r in rows]


def latest_successful_backup():
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM backup_history WHERE status = 'done' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def mark_backup_restore_tested(backup_id, note=None):
    conn = get_db()
    conn.execute(
        "UPDATE backup_history SET restore_tested_at = ?, note = COALESCE(?, note) WHERE id = ?",
        (_utcnow().isoformat(), note, str(backup_id)),
    )
    conn.commit()
    row = conn.execute('SELECT * FROM backup_history WHERE id = ?', (str(backup_id),)).fetchone()
    return dict(row) if row else None


# ═════════════════════════════════════════════════════════════════════════════
# t54: operational monitoring — metrics without client content
# ═════════════════════════════════════════════════════════════════════════════


def storage_overview():
    """Storage usage per company: file bytes and object counts, no content."""
    conn = get_db()
    per_tenant = []
    try:
        rows = conn.execute(
            '''SELECT pf.tenant_id, COALESCE(SUM(pf.file_size), 0) AS bytes, COUNT(*) AS files,
                      tn.company_name
               FROM project_files pf LEFT JOIN tenants tn ON tn.id = pf.tenant_id
               GROUP BY pf.tenant_id ORDER BY bytes DESC'''
        ).fetchall()
        per_tenant = [{'tenant_id': r['tenant_id'], 'company_name': r['company_name'],
                       'bytes': int(r['bytes'] or 0), 'files': int(r['files'] or 0)}
                      for r in rows]
    except Exception:
        per_tenant = []
    total_bytes = sum(item['bytes'] for item in per_tenant)
    return {'total_bytes': total_bytes, 'per_tenant': per_tenant}


def generation_job_metrics():
    """Generation throughput, failures and durations for the ops dashboard."""
    conn = get_db()
    metrics = {'total': 0, 'by_status': {}, 'failed_24h': 0, 'completed_24h': 0,
               'avg_duration_seconds': None, 'success_rate': None}
    try:
        rows = conn.execute(
            'SELECT status, COUNT(*) AS n FROM generation_jobs GROUP BY status'
        ).fetchall()
        for r in rows:
            metrics['by_status'][r['status']] = int(r['n'] or 0)
        metrics['total'] = sum(metrics['by_status'].values())
        from datetime import timedelta
        cutoff = (_utcnow() - timedelta(hours=24)).isoformat()
        metrics['failed_24h'] = int(conn.execute(
            "SELECT COUNT(*) AS n FROM generation_jobs WHERE status = 'failed' AND finished_at >= ?",
            (cutoff,),
        ).fetchone()['n'] or 0)
        metrics['completed_24h'] = int(conn.execute(
            "SELECT COUNT(*) AS n FROM generation_jobs WHERE status = 'completed' AND finished_at >= ?",
            (cutoff,),
        ).fetchone()['n'] or 0)
        durations = conn.execute(
            """SELECT started_at, finished_at FROM generation_jobs
               WHERE status = 'completed' AND started_at IS NOT NULL AND finished_at IS NOT NULL
               ORDER BY finished_at DESC LIMIT 200"""
        ).fetchall()
        total_seconds = 0.0
        counted = 0
        for row in durations:
            try:
                total_seconds += (datetime.fromisoformat(row['finished_at'])
                                  - datetime.fromisoformat(row['started_at'])).total_seconds()
                counted += 1
            except (TypeError, ValueError):
                continue
        if counted:
            metrics['avg_duration_seconds'] = round(total_seconds / counted, 1)
        decided = metrics['by_status'].get('completed', 0) + metrics['by_status'].get('failed', 0)
        if decided:
            metrics['success_rate'] = round(metrics['by_status'].get('completed', 0) / decided * 100, 1)
    except Exception:
        pass
    return metrics


def platform_alerts():
    """Computed alert list: failures, stale work, overdue backups (t54)."""
    conn = get_db()
    alerts = []
    now = _utcnow()
    from datetime import timedelta

    stale_recharges = 0
    try:
        cutoff = (now - timedelta(hours=24)).isoformat()
        stale_recharges = int(conn.execute(
            "SELECT COUNT(*) AS n FROM recharge_requests WHERE status = 'pending' AND requested_at < ?",
            (cutoff,),
        ).fetchone()['n'] or 0)
    except Exception:
        pass
    if stale_recharges:
        alerts.append({'kind': 'recharge_sla', 'severity': 'warning',
                       'count': stale_recharges,
                       'message_ar': 'طلبات شحن تجاوزت مهلة المراجعة ٢٤ ساعة'})
    try:
        failed_jobs = int(conn.execute(
            "SELECT COUNT(*) AS n FROM generation_jobs WHERE status = 'failed' AND finished_at >= ?",
            ((now - timedelta(hours=24)).isoformat(),),
        ).fetchone()['n'] or 0)
    except Exception:
        failed_jobs = 0
    if failed_jobs:
        alerts.append({'kind': 'generation_failures', 'severity': 'critical',
                       'count': failed_jobs, 'message_ar': 'مهام توليد فاشلة خلال ٢٤ ساعة'})
    try:
        dead_jobs = int(conn.execute(
            "SELECT COUNT(*) AS n FROM job_queue WHERE status = 'dead'"
        ).fetchone()['n'] or 0)
    except Exception:
        dead_jobs = 0
    if dead_jobs:
        alerts.append({'kind': 'dead_jobs', 'severity': 'critical', 'count': dead_jobs,
                       'message_ar': 'مهام خلفية استنفدت محاولاتها'})
    return alerts


def email_outbox_stats():
    """Queued/sent/failed counts for the outbound mail worker table."""
    conn = get_db()
    stats = {'queued': 0, 'sent': 0, 'failed': 0, 'dead': 0}
    try:
        rows = conn.execute(
            'SELECT status, COUNT(*) AS n FROM email_outbox GROUP BY status'
        ).fetchall()
        for r in rows:
            stats[str(r['status'])] = int(r['n'] or 0)
    except Exception:
        pass
    return stats


def job_queue_stats():
    """Queue depth per status for the background worker table."""
    conn = get_db()
    stats = {'queued': 0, 'running': 0, 'done': 0, 'failed': 0, 'dead': 0}
    try:
        rows = conn.execute(
            'SELECT status, COUNT(*) AS n FROM job_queue GROUP BY status'
        ).fetchall()
        for r in rows:
            stats[str(r['status'])] = int(r['n'] or 0)
    except Exception:
        pass
    return stats
