

# ═════════════════════════════════════════════════════════════════════════════
# t60-04: immutable package versions, subscriptions and top-up receipts
# ═════════════════════════════════════════════════════════════════════════════


def create_package_version(package_id, name=None, credit_usd=None, price_sar=None,
                           duration_days=None, limits=None, features=None,
                           actor_id=None, actor_name=None):
    """Snapshot a package into an immutable version row (next version number)."""
    conn = get_db()
    package = conn.execute(
        'SELECT * FROM billing_packages WHERE id = ?', (str(package_id),),
    ).fetchone()
    if package is None:
        return {'error': 'package_not_found'}
    package = dict(package)
    row = conn.execute(
        'SELECT COALESCE(MAX(version), 0) + 1 AS next FROM billing_package_versions WHERE package_id = ?',
        (str(package_id),),
    ).fetchone()
    version = int(row['next'])
    version_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO billing_package_versions
           (id, package_id, version, name, credit_usd, price_sar, duration_days,
            limits_json, features_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (version_id, str(package_id), version,
         name if name is not None else package.get('name'),
         float(credit_usd) if credit_usd is not None else float(package.get('credit_usd') or 0.0),
         price_sar if price_sar is not None else package.get('price_sar'),
         duration_days,
         json.dumps(limits or {}, ensure_ascii=False),
         json.dumps(features or {}, ensure_ascii=False)),
    )
    conn.commit()
    return dict(conn.execute(
        'SELECT * FROM billing_package_versions WHERE id = ?', (version_id,)).fetchone())


def list_package_versions(package_id):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM billing_package_versions WHERE package_id = ? ORDER BY version DESC',
        (str(package_id),),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item['limits'] = _json_or(item.get('limits_json'), {})
        item['features'] = _json_or(item.get('features_json'), {})
        result.append(item)
    return result


def create_subscription(tenant_id, package_id=None, package_version_id=None,
                        starts_at=None, ends_at=None, trial_ends_at=None,
                        status='active', created_by=None, created_by_name=None):
    """Record a subscription window for a tenant (one active at a time)."""
    conn = get_db()
    if status == 'active':
        conn.execute(
            "UPDATE tenant_subscriptions SET status = 'expired' "
            "WHERE tenant_id = ? AND status = 'active'",
            (str(tenant_id),),
        )
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO tenant_subscriptions
           (id, tenant_id, package_id, package_version_id, status,
            starts_at, ends_at, trial_ends_at, created_by, created_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, str(tenant_id), str(package_id) if package_id else None,
         str(package_version_id) if package_version_id else None, status,
         starts_at or _utcnow().isoformat(), ends_at, trial_ends_at,
         created_by, created_by_name),
    )
    conn.commit()
    return dict(conn.execute(
        'SELECT * FROM tenant_subscriptions WHERE id = ?', (row_id,)).fetchone())


def current_subscription(tenant_id):
    conn = get_db()
    row = conn.execute(
        "SELECT s.*, p.name AS package_name, p.price_sar AS package_price_sar "
        "FROM tenant_subscriptions s LEFT JOIN billing_packages p ON p.id = s.package_id "
        "WHERE s.tenant_id = ? AND s.status = 'active' ORDER BY s.starts_at DESC LIMIT 1",
        (str(tenant_id),),
    ).fetchone()
    return dict(row) if row else None


def list_subscriptions(tenant_id):
    conn = get_db()
    rows = conn.execute(
        'SELECT s.*, p.name AS package_name FROM tenant_subscriptions s '
        'LEFT JOIN billing_packages p ON p.id = s.package_id '
        'WHERE s.tenant_id = ? ORDER BY s.starts_at DESC',
        (str(tenant_id),),
    ).fetchall()
    return [dict(r) for r in rows]


def current_package_limits(tenant_id):
    """d10: the limits dict of the tenant's active package version — empty
    when no subscription pins one. Uploads read ``max_file_mb`` from it."""
    conn = get_db()
    row = conn.execute(
        '''SELECT v.limits_json FROM tenant_subscriptions s
           JOIN billing_package_versions v ON v.id = s.package_version_id
           WHERE s.tenant_id = ? AND s.status = 'active'
           ORDER BY s.starts_at DESC LIMIT 1''',
        (str(tenant_id),),
    ).fetchone()
    if not row:
        return {}
    return _json_or(row['limits_json'], {})


def _next_invoice_number_tx(conn):
    """Sequential financial document number: INV-<year>-<six digits>."""
    year = _utcnow().year
    row = conn.execute(
        "SELECT invoice_number FROM topup_receipts WHERE invoice_number LIKE ? "
        "ORDER BY invoice_number DESC LIMIT 1",
        (f'INV-{year}-%',),
    ).fetchone()
    sequence = 1
    if row and row['invoice_number']:
        try:
            sequence = int(str(row['invoice_number']).rsplit('-', 1)[-1]) + 1
        except (ValueError, IndexError):
            sequence = 1
    return f'INV-{year}-{sequence:06d}'


TAX_RATE_SAR = float(os.environ.get('TOPUP_TAX_RATE', '0.15'))


def _create_topup_receipt_tx(conn, tenant_id, recharge_request_id=None, receipt_file_id=None,
                             receipt_sha256=None, transfer_reference=None, amount_usd=0,
                             price_sar=None, issued_by=None, issued_by_name=None):
    """d09: one financial document per approved top-up, inside the caller's
    transaction — never commits. Carries the VAT breakdown on the SAR price."""
    if recharge_request_id:
        existing = conn.execute(
            'SELECT * FROM topup_receipts WHERE recharge_request_id = ?',
            (str(recharge_request_id),),
        ).fetchone()
        if existing:
            return dict(existing)
    receipt_id = str(uuid.uuid4())
    invoice_number = _next_invoice_number_tx(conn)
    subtotal = float(price_sar) if price_sar is not None else None
    tax_amount = round(subtotal * TAX_RATE_SAR, 2) if subtotal is not None else None
    total_sar = round(subtotal + tax_amount, 2) if subtotal is not None else None
    conn.execute(
        '''INSERT INTO topup_receipts
           (id, tenant_id, recharge_request_id, receipt_file_id, receipt_sha256,
            transfer_reference, invoice_number, amount_usd, price_sar,
            tax_rate, tax_amount_sar, total_sar, status,
            issued_by, issued_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'issued', ?, ?)''',
        (receipt_id, str(tenant_id),
         str(recharge_request_id) if recharge_request_id else None,
         str(receipt_file_id) if receipt_file_id else None,
         receipt_sha256, transfer_reference, invoice_number,
         float(amount_usd or 0.0), subtotal,
         TAX_RATE_SAR if subtotal is not None else None,
         tax_amount, total_sar,
         issued_by, issued_by_name),
    )
    return dict(conn.execute(
        'SELECT * FROM topup_receipts WHERE id = ?', (receipt_id,)).fetchone())


def create_topup_receipt(tenant_id, recharge_request_id=None, receipt_file_id=None,
                         receipt_sha256=None, transfer_reference=None, amount_usd=0,
                         price_sar=None, issued_by=None, issued_by_name=None):
    """Issue the financial document for an approved top-up (d09/t60-04).

    The receipt is created once per recharge request — a repeat call returns
    the existing row — and carries an immutable invoice number, the VAT
    breakdown and the receipt fingerprint so a duplicate bank transfer can be
    detected.
    """
    conn = get_db()
    row = _create_topup_receipt_tx(
        conn, tenant_id, recharge_request_id=recharge_request_id,
        receipt_file_id=receipt_file_id, receipt_sha256=receipt_sha256,
        transfer_reference=transfer_reference, amount_usd=amount_usd,
        price_sar=price_sar, issued_by=issued_by, issued_by_name=issued_by_name)
    conn.commit()
    return row


def list_topup_receipts(tenant_id, limit=100):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM topup_receipts WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?',
        (str(tenant_id), int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def get_topup_receipt(tenant_id, receipt_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM topup_receipts WHERE id = ? AND tenant_id = ?',
        (str(receipt_id), str(tenant_id)),
    ).fetchone()
    return dict(row) if row else None


# ═════════════════════════════════════════════════════════════════════════════
# t60-01: notification delivery rows per channel
# ═════════════════════════════════════════════════════════════════════════════

NOTIFICATION_CHANNELS = ('in_app', 'email')
DELIVERY_STATUSES = ('queued', 'sent', 'delivered', 'failed')


def queue_notification_deliveries(notification_id, tenant_id, channels=None, email_to=None):
    """Fan a notification out to per-channel delivery rows (t60-01).

    The in-app channel is delivered the moment it exists; the email channel is
    queued into ``email_outbox`` so a worker can retry it. Returns the created
    delivery rows.
    """
    conn = get_db()
    channels = list(channels or ('in_app',))
    now = _utcnow().isoformat()
    deliveries = []
    for channel in channels:
        if channel not in NOTIFICATION_CHANNELS:
            continue
        delivery_id = str(uuid.uuid4())
        if channel == 'in_app':
            status, sent_at, delivered_at = 'delivered', now, now
        else:
            status, sent_at, delivered_at = 'queued', None, None
        conn.execute(
            '''INSERT INTO notification_deliveries
               (id, notification_id, tenant_id, channel, status, attempts,
                last_attempt_at, sent_at, delivered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (delivery_id, notification_id, str(tenant_id), channel, status,
             1 if channel == 'in_app' else 0,
             now if channel == 'in_app' else None, sent_at, delivered_at),
        )
        if channel == 'email' and email_to:
            notification = conn.execute(
                'SELECT title, body FROM notifications WHERE id = ?', (notification_id,)
            ).fetchone()
            if notification:
                conn.execute(
                    '''INSERT INTO email_outbox
                       (id, tenant_id, notification_id, to_email, subject, body_text)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (str(uuid.uuid4()), str(tenant_id), notification_id, email_to,
                     notification['title'], notification['body']),
                )
        deliveries.append(dict(conn.execute(
            'SELECT * FROM notification_deliveries WHERE id = ?', (delivery_id,)
        ).fetchone()))
    conn.commit()
    return deliveries


def record_delivery_attempt(delivery_id, status, error=None):
    """Record one delivery attempt: attempts++ plus the terminal state."""
    if status not in DELIVERY_STATUSES:
        return {'error': 'invalid_status'}
    conn = get_db()
    now = _utcnow().isoformat()
    sent_at = now if status in ('sent', 'delivered') else None
    conn.execute(
        '''UPDATE notification_deliveries
           SET status = ?, attempts = attempts + 1, last_error = ?, last_attempt_at = ?,
               sent_at = COALESCE(?, sent_at), delivered_at = CASE WHEN ? = 'delivered' THEN ? ELSE delivered_at END
           WHERE id = ?''',
        (status, error, now, sent_at, status, now, str(delivery_id)),
    )
    conn.commit()
    row = conn.execute(
        'SELECT * FROM notification_deliveries WHERE id = ?', (str(delivery_id),)
    ).fetchone()
    return dict(row) if row else None


def mark_notification_read(notification_id, tenant_id):
    """Stamp read_at on the in-app delivery when the feed marks it read."""
    conn = get_db()
    now = _utcnow().isoformat()
    conn.execute(
        '''UPDATE notification_deliveries SET read_at = ?
           WHERE notification_id = ? AND tenant_id = ? AND channel = 'in_app' AND read_at IS NULL''',
        (now, str(notification_id), str(tenant_id)),
    )
    conn.commit()


def notification_delivery_report(tenant_id=None, limit=200):
    """Delivery rows joined with their notification for the delivery log UI."""
    conn = get_db()
    query = ('SELECT d.*, n.title, n.category, n.user_id FROM notification_deliveries d '
             'JOIN notifications n ON n.id = d.notification_id')
    params = []
    if tenant_id:
        query += ' WHERE d.tenant_id = ?'
        params.append(str(tenant_id))
    query += ' ORDER BY d.created_at DESC LIMIT ?'
    params.append(int(limit))
    return [dict(r) for r in conn.execute(query, params).fetchall()]


# ═════════════════════════════════════════════════════════════════════════════
# t60-02: ticket attachments and project links
# ═════════════════════════════════════════════════════════════════════════════


def attach_support_ticket_file(tenant_id, ticket_id, file_id, message_id=None):
    """Attach a stored project file to a support ticket."""
    conn = get_db()
    ticket = conn.execute(
        'SELECT id FROM support_tickets WHERE id = ? AND tenant_id = ?',
        (str(ticket_id), str(tenant_id)),
    ).fetchone()
    if not ticket:
        return {'error': 'ticket_not_found'}
    file_row = conn.execute(
        'SELECT id FROM project_files WHERE id = ? AND tenant_id = ?',
        (str(file_id), str(tenant_id)),
    ).fetchone()
    if not file_row:
        return {'error': 'file_not_found'}
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO support_ticket_attachments (id, ticket_id, message_id, tenant_id, file_id)
           VALUES (?, ?, ?, ?, ?)''',
        (row_id, str(ticket_id), str(message_id) if message_id else None,
         str(tenant_id), str(file_id)),
    )
    conn.commit()
    return dict(conn.execute(
        'SELECT * FROM support_ticket_attachments WHERE id = ?', (row_id,)).fetchone())


def list_support_ticket_attachments(ticket_id):
    conn = get_db()
    rows = conn.execute(
        '''SELECT a.*, f.original_name, f.mime_type, f.file_size
           FROM support_ticket_attachments a
           JOIN project_files f ON f.id = a.file_id
           WHERE a.ticket_id = ? ORDER BY a.created_at''',
        (str(ticket_id),),
    ).fetchall()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# t60-05: generation jobs and document versions
# ═════════════════════════════════════════════════════════════════════════════

GENERATION_JOB_STATUSES = ('queued', 'running', 'completed', 'failed', 'cancelled')


def _generation_job_by_idempotency(conn, tenant_id, approval_id, idempotency_key):
    """The replay lookup lives at (tenant, approval, key) scope: the key names
    one client's retried request, so a match outside this approval — or outside
    this company entirely — is a different request and must not return the row."""
    return conn.execute(
        "SELECT * FROM generation_jobs WHERE tenant_id = ? "
        "AND COALESCE(approval_id, '') = COALESCE(?, '') AND idempotency_key = ?",
        (str(tenant_id), str(approval_id) if approval_id is not None else None,
         str(idempotency_key)),
    ).fetchone()


def create_generation_job(tenant_id, approval_id=None, draft_id=None, presentation_id=None,
                          model=None, template_version=None, schema_version=None,
                          input_snapshot=None, estimated_cost_usd=None, slides_total=None,
                          created_by=None, created_by_name=None, idempotency_key=None,
                          correlation_id=None):
    """Register one generation run tied to its approval and input snapshot.

    ``idempotency_key`` makes a retried client call return the same job
    instead of a duplicate row.
    """
    conn = get_db()
    if idempotency_key:
        existing = _generation_job_by_idempotency(
            conn, tenant_id, approval_id, idempotency_key)
        if existing:
            return dict(existing)
    job_id = str(uuid.uuid4())
    try:
        conn.execute(
            '''INSERT INTO generation_jobs
               (id, tenant_id, approval_id, draft_id, presentation_id, status, model,
                template_version, schema_version, input_snapshot_json, estimated_cost_usd,
                slides_total, correlation_id, idempotency_key, created_by, created_by_name)
               VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (job_id, str(tenant_id), approval_id, draft_id, presentation_id, model,
             template_version, schema_version,
             json.dumps(input_snapshot, ensure_ascii=False) if input_snapshot is not None else None,
             estimated_cost_usd, slides_total, correlation_id,
             str(idempotency_key) if idempotency_key else None, created_by, created_by_name),
        )
    except sqlite3.IntegrityError:
        raced = (_generation_job_by_idempotency(conn, tenant_id, approval_id, idempotency_key)
                 if idempotency_key else None)
        if raced:
            return dict(raced)
        raise
    conn.commit()
    return dict(conn.execute('SELECT * FROM generation_jobs WHERE id = ?', (job_id,)).fetchone())


def update_generation_job(job_id, status=None, progress=None, slides_done=None,
                          slides_total=None, actual_cost_usd=None, error=None):
    """Advance a generation job; first 'running' stamps started_at, terminal
    states stamp finished_at."""
    conn = get_db()
    row = conn.execute('SELECT * FROM generation_jobs WHERE id = ?', (str(job_id),)).fetchone()
    if not row:
        return {'error': 'job_not_found'}
    row = dict(row)
    updates = []
    params = []
    now = _utcnow().isoformat()
    if status is not None:
        if status not in GENERATION_JOB_STATUSES:
            return {'error': 'invalid_status'}
        updates.append('status = ?')
        params.append(status)
        if status == 'running' and not row.get('started_at'):
            updates.append('started_at = ?')
            params.append(now)
        if status in ('completed', 'failed', 'cancelled'):
            updates.append('finished_at = ?')
            params.append(now)
    if progress is not None:
        updates.append('progress = ?')
        params.append(max(0, min(100, int(progress))))
    if slides_done is not None:
        updates.append('slides_done = ?')
        params.append(int(slides_done))
    if slides_total is not None:
        updates.append('slides_total = ?')
        params.append(int(slides_total))
    if actual_cost_usd is not None:
        updates.append('actual_cost_usd = ?')
        params.append(float(actual_cost_usd))
    if error is not None:
        updates.append('error = ?')
        params.append(str(error)[:2000])
    # Every update doubles as the heartbeat the stale-job sweeper reads.
    updates.append('heartbeat_at = ?')
    params.append(now)
    params.append(str(job_id))
    conn.execute('UPDATE generation_jobs SET ' + ', '.join(updates) + ' WHERE id = ?', params)
    conn.commit()
    return dict(conn.execute('SELECT * FROM generation_jobs WHERE id = ?', (str(job_id),)).fetchone())


GENERATION_JOB_TIMEOUT_MINUTES = int(os.environ.get('GENERATION_JOB_TIMEOUT_MINUTES', '30'))


def sweep_stale_generation_jobs(tenant_id=None, timeout_minutes=None):
    """Fail generation jobs whose heartbeat went silent and free their holds.

    A client that dies mid-run leaves the job 'running' forever with the
    reservation still held; this sweep is the server-side safety net behind
    the client releases (t14-06). It runs lazily on the read paths that list
    jobs and approvals.
    """
    conn = get_db()
    limit = int(timeout_minutes or GENERATION_JOB_TIMEOUT_MINUTES)
    cutoff = (_utcnow() - timedelta(minutes=limit)).isoformat()
    clauses = ["status IN ('queued', 'running')",
               "COALESCE(heartbeat_at, started_at, created_at) < ?"]
    params = [cutoff]
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(str(tenant_id))
    try:
        rows = conn.execute(
            'SELECT * FROM generation_jobs WHERE ' + ' AND '.join(clauses),
            tuple(params),
        ).fetchall()
    except Exception:
        return 0
    for job in rows:
        conn.execute(
            "UPDATE generation_jobs SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
            ('job_timeout', _utcnow().isoformat(), job['id']),
        )
        conn.commit()
        try:
            create_notification(
                job['tenant_id'], 'فشلت مهمة التوليد',
                'انتهت مهلة التوليد — حُرر الحجز تلقائيًا',
                category='job', user_id=job['created_by'] or None,
                entity_type='generation_job', entity_id=job['id'])
        except Exception:
            pass
        if job['approval_id']:
            try:
                settle_generation_approval(
                    job['tenant_id'], job['approval_id'], job['id'], consumed=False,
                    settled_by='system',
                    note='انتهت مهلة مهمة التوليد — تحرير الحجز تلقائيًا')
            except Exception:
                pass
    return len(rows)


def recover_dead_generating_drafts(tenant_id=None, timeout_minutes=None, draft_id=None):
    """Return drafts from 'generating' when the run that owned them is dead.

    A run proves it is alive through a generation_jobs row still queued or
    running with a heartbeat inside the timeout, or through an approval decided
    so recently the client may legitimately not have registered the job yet —
    the run is client-driven and the job row appears only after the slide plan
    returns. Anything else holding 'generating' is a corpse: a browser that
    died before its job was registered, a settle whose lifecycle transition
    failed, or an approval that never escrowed points. Each is closed like a
    failed run — stale jobs fail, the escrow releases, the draft returns to the
    state the request came from — so the file can be saved and generated again
    instead of staying locked until a reservation happens to expire.
    """
    conn = get_db()
    limit = int(timeout_minutes or GENERATION_JOB_TIMEOUT_MINUTES)
    cutoff = (_utcnow() - timedelta(minutes=limit)).isoformat()
    clauses = ["COALESCE(status, 'draft') = 'generating'"]
    params = []
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(str(tenant_id))
    if draft_id:
        clauses.append('id = ?')
        params.append(str(draft_id))
    try:
        drafts = conn.execute(
            'SELECT id, tenant_id FROM project_drafts WHERE ' + ' AND '.join(clauses),
            tuple(params)).fetchall()
    except Exception:
        return 0
    recovered = 0
    for draft in drafts:
        d_id, t_id = draft['id'], draft['tenant_id']
        try:
            live_job = conn.execute(
                """SELECT j.id FROM generation_jobs j
                   WHERE j.tenant_id = ? AND j.status IN ('queued', 'running')
                     AND COALESCE(j.heartbeat_at, j.started_at, j.created_at) >= ?
                     AND (j.draft_id = ? OR j.approval_id IN (
                         SELECT id FROM generation_approvals
                         WHERE tenant_id = ? AND draft_id = ?))
                   LIMIT 1""",
                (t_id, cutoff, d_id, t_id, d_id)).fetchone()
            if live_job:
                continue
            approval = conn.execute(
                """SELECT * FROM generation_approvals
                   WHERE tenant_id = ? AND draft_id = ? AND status = 'approved'
                   ORDER BY decided_at DESC LIMIT 1""",
                (t_id, d_id)).fetchone()
            if approval and str(approval['decided_at'] or '') >= cutoff:
                # Still inside the grace the client needs to register its job.
                continue
            # Stale job rows under this draft belong to the dead run: fail them
            # here so they never read as still executing.
            stale_jobs = conn.execute(
                """SELECT j.id FROM generation_jobs j
                   WHERE j.tenant_id = ? AND j.status IN ('queued', 'running')
                     AND (j.draft_id = ? OR j.approval_id IN (
                         SELECT id FROM generation_approvals
                         WHERE tenant_id = ? AND draft_id = ?))""",
                (t_id, d_id, t_id, d_id)).fetchall()
            for stale in stale_jobs:
                conn.execute(
                    "UPDATE generation_jobs SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                    ('job_timeout', _utcnow().isoformat(), stale['id']))
            if stale_jobs:
                conn.commit()
            moved = False
            if approval:
                settle_generation_approval(
                    t_id, approval['id'], 'dead-run-sweep', consumed=False,
                    settled_by='system',
                    note='مهمة التوليد توقفت دون إنهاء — تحرير الحجز وإعادة الملف')
                # settle reports success even when its lifecycle hop refused —
                # only the draft actually leaving 'generating' counts.
                current = conn.execute(
                    'SELECT status FROM project_drafts WHERE id = ?', (d_id,)).fetchone()
                moved = bool(current) and normalize_proposal_status(current['status']) != 'generating'
            if not moved:
                # No approved approval — or a settle whose transition refused:
                # nothing is funding a run anymore. Release any stray hold and
                # send the draft back to the state the request came from (or
                # the last editable gate before 'generating').
                stray = conn.execute(
                    """SELECT * FROM point_reservations
                       WHERE tenant_id = ? AND draft_id = ? AND status = 'reserved'""",
                    (t_id, d_id)).fetchall()
                for row in stray:
                    _settle_reservation_tx(conn, t_id, row, 'released', settled_by='system',
                                           note='تحرير حجز بلا مهمة توليد نشطة')
                if stray:
                    conn.commit()
                    _fire_balance_change(t_id)
                last = conn.execute(
                    """SELECT prior_status FROM generation_approvals
                       WHERE tenant_id = ? AND draft_id = ?
                       ORDER BY COALESCE(decided_at, requested_at) DESC LIMIT 1""",
                    (t_id, d_id)).fetchone()
                prior = str((last['prior_status'] if last else '') or '').strip()
                if prior not in PROPOSAL_ALLOWED_TRANSITIONS.get('generating', set()):
                    prior = 'sections_approved'
                moved = bool(_draft_gate_transition(
                    t_id, d_id, prior, 'system', 'النظام',
                    'استرداد ملف علق في حالة التوليد دون مهمة نشطة'))
            if moved:
                recovered += 1
        except Exception as exc:
            print(f'[LIFECYCLE] dead-run recovery for draft {d_id} failed: {exc}')
    return recovered


def get_generation_job(job_id, tenant_id=None):
    conn = get_db()
    if tenant_id:
        row = conn.execute(
            'SELECT * FROM generation_jobs WHERE id = ? AND tenant_id = ?',
            (str(job_id), str(tenant_id)),
        ).fetchone()
    else:
        row = conn.execute('SELECT * FROM generation_jobs WHERE id = ?', (str(job_id),)).fetchone()
    return dict(row) if row else None


def list_generation_jobs(tenant_id=None, status=None, limit=100, accessible_draft_ids=None):
    """Tenant jobs; ``accessible_draft_ids`` keeps a project-scoped member from
    listing jobs whose draft or presentation falls outside their scope
    (ISS-014). Rows with no draft link stay visible, matching presentations."""
    if tenant_id:
        sweep_stale_generation_jobs(tenant_id)
    conn = get_db()
    clauses = []
    params = []
    if tenant_id:
        clauses.append('j.tenant_id = ?')
        params.append(str(tenant_id))
    if status:
        clauses.append('j.status = ?')
        params.append(status)
    query = ('SELECT j.* FROM generation_jobs j '
             'LEFT JOIN presentations p ON p.id = j.presentation_id AND p.tenant_id = j.tenant_id')
    if accessible_draft_ids is not None:
        ids = [str(i) for i in accessible_draft_ids]
        if ids:
            placeholders = ','.join('?' * len(ids))
            clauses.append('(j.draft_id IS NULL OR j.draft_id IN (' + placeholders + '))')
            params.extend(ids)
            clauses.append('(j.presentation_id IS NULL OR p.draft_id IS NULL OR p.draft_id IN (' + placeholders + '))')
            params.extend(ids)
        else:
            clauses.append('j.draft_id IS NULL AND (j.presentation_id IS NULL OR p.draft_id IS NULL)')
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY j.created_at DESC LIMIT ?'
    params.append(int(limit))
    return [dict(r) for r in conn.execute(query, params).fetchall()]
