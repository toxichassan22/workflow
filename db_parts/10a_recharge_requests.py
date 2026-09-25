# ── t32/t33: recharge (package purchase) requests ───────────────────────────

def create_recharge_request(tenant_id, package_name, amount_usd=0, price_sar=None,
                            transfer_reference=None, requested_by=None, requested_by_name=None,
                            package_id=None, receipt_file_id=None):
    """File a package purchase request (t33).

    When a ``package_id`` is supplied the amount and price come from the
    catalog row, not the client; a bank-transfer reference may only back one
    request so the same receipt cannot be submitted twice. Every request must
    carry proof of the transfer: the bank reference number or an uploaded
    receipt (either one suffices).
    """
    transfer_reference = str(transfer_reference or '').strip() or None
    if not transfer_reference and not str(receipt_file_id or '').strip():
        return {'error': 'reference_or_receipt_required'}
    conn = get_db()
    if transfer_reference:
        duplicate = conn.execute(
            """SELECT id FROM recharge_requests
               WHERE transfer_reference = ? AND status != 'rejected'""",
            (transfer_reference,),
        ).fetchone()
        if duplicate:
            return {'error': 'duplicate_transfer_reference'}
    if package_id:
        package = conn.execute(
            'SELECT * FROM billing_packages WHERE id = ? AND is_active = 1',
            (str(package_id),),
        ).fetchone()
        if not package:
            return {'error': 'package_not_found'}
        package = dict(package)
        package_name = package.get('name')
        amount_sar = package.get('credit_sar')
        amount_usd = package.get('credit_usd') or 0
        if amount_sar is None:
            amount_sar = usd_to_sar(amount_usd)
        price_sar = package.get('price_sar')
    else:
        amount_sar = None
    if not str(package_name or '').strip():
        return {'error': 'package_name_required'}
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO recharge_requests
           (id, tenant_id, package_id, package_name, amount_usd, amount_sar, price_sar,
            transfer_reference, receipt_file_id, requested_by, requested_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, tenant_id, package_id, str(package_name).strip(), float(amount_usd or 0),
         round(float(amount_sar) + 1e-9, 2) if amount_sar is not None else usd_to_sar(amount_usd or 0),
         round(float(price_sar) + 1e-9, 2) if price_sar is not None else None, transfer_reference, receipt_file_id,
         requested_by, requested_by_name),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM recharge_requests WHERE id = ?', (row_id,)).fetchone())


def decide_recharge_request(tenant_id, request_id, decision, reviewed_by, reviewed_by_name,
                            note=None, reference_number=None, invoice_file_id=None):
    """Approve or reject a recharge request atomically (t33/d09).

    One commit covers the decision, the wallet credit and the financial
    document: an approval that cannot credit rolls the decision back, and a
    repeated approval cannot mint a second credit or a second invoice.
    ``invoice_file_id`` is the optional platform-issued invoice upload the
    client sees on the approved request.
    """
    if decision not in {'approved', 'rejected'}:
        return {'error': 'invalid_decision'}
    conn = get_db()
    if tenant_id:
        row = conn.execute(
            'SELECT * FROM recharge_requests WHERE id = ? AND tenant_id = ?', (request_id, tenant_id),
        ).fetchone()
    else:
        row = conn.execute(
            'SELECT * FROM recharge_requests WHERE id = ?', (request_id,),
        ).fetchone()
    if not row:
        return {'error': 'request_not_found'}
    if row['status'] != 'pending':
        return {'error': 'request_not_pending'}
    target_tenant_id = row['tenant_id']
    if decision == 'approved':
        target = conn.execute('SELECT is_admin FROM tenants WHERE id = ?', (target_tenant_id,)).fetchone()
        if target and target['is_admin']:
            return {'error': 'platform_tenant_recharge_forbidden'}
    reference = str(reference_number or '').strip()
    if decision == 'approved' and not reference:
        reference = 'RCH-' + _utcnow().strftime('%Y%m%d') + '-' + request_id[:8].upper()
    conn.execute(
        '''UPDATE recharge_requests SET status = ?, reviewed_by = ?, reviewed_by_name = ?,
           reviewed_at = ?, decision_note = ?, reference_number = ?, invoice_file_id = ?
           WHERE id = ?''',
        (decision, reviewed_by, reviewed_by_name, _utcnow().isoformat(),
         str(note or '').strip() or None,
         reference if decision == 'approved' else row['reference_number'],
         str(invoice_file_id or '').strip()
         or (row['invoice_file_id'] if 'invoice_file_id' in row.keys() else None),
         request_id),
    )
    amount_sar = row['amount_sar'] if 'amount_sar' in row.keys() else None
    if amount_sar is None:
        amount_sar = usd_to_sar(row['amount_usd'])
    if decision == 'approved' and float(amount_sar or 0) > 0:
        amount = round(float(amount_sar) + 1e-9, 2)
        existing = conn.execute(
            'SELECT * FROM tenant_ledger WHERE tenant_id = ? AND idempotency_key = ?',
            (target_tenant_id, 'recharge:' + request_id),
        ).fetchone()
        if not existing:
            conn.execute(
                'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) + ? WHERE id = ?',
                (amount, target_tenant_id),
            )
            conn.execute(
                '''INSERT INTO tenant_ledger
                   (id, tenant_id, kind, amount_usd, amount_sar, fx_rate, raw_cost_usd, multiplier,
                    maps_cost_usd, ai_cost_usd, maps_events_count, ai_events_count,
                    draft_id, presentation_id, idempotency_key, note, actor)
                   VALUES (?, ?, 'credit', ?, ?, ?, 0, 1, 0, 0, 0, 0, NULL, NULL, ?, ?, ?)''',
                (str(uuid.uuid4()), target_tenant_id, sar_to_usd(amount), amount,
                 _active_fx_rate(), 'recharge:' + request_id,
                 'شحن رصيد بالمرجع ' + reference, 'recharge_decision'),
            )
        _create_topup_receipt_tx(
            conn, target_tenant_id, recharge_request_id=request_id,
            receipt_file_id=row['receipt_file_id'] if 'receipt_file_id' in row.keys() else None,
            transfer_reference=row['transfer_reference'] if 'transfer_reference' in row.keys() else None,
            amount_usd=sar_to_usd(amount), amount_sar=amount,
            price_sar=row['price_sar'] if 'price_sar' in row.keys() else None,
            invoice_file_id=str(invoice_file_id or '').strip() or None,
            issued_by=reviewed_by, issued_by_name=reviewed_by_name)
    conn.commit()
    if decision == 'approved' and float(amount_sar or 0) > 0:
        _fire_balance_change(target_tenant_id)
    return dict(conn.execute('SELECT * FROM recharge_requests WHERE id = ?', (request_id,)).fetchone())


def get_recharge_request(request_id):
    """One recharge row by id — used by the attachment route after the caller
    has already proven it may see the owning tenant."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM recharge_requests WHERE id = ?', (str(request_id),),
    ).fetchone()
    return dict(row) if row else None


def list_recharge_requests(tenant_id=None, status=None, limit=100):
    conn = get_db()
    query = 'SELECT * FROM recharge_requests'
    clauses = []
    params = []
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(tenant_id)
    if status:
        clauses.append('status = ?')
        params.append(status)
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY requested_at DESC LIMIT ?'
    params.append(int(limit))
    return with_sar_fields([dict(row) for row in conn.execute(query, params).fetchall()])


def get_latest_approved_recharge(tenant_id):
    """The tenant's most recent approved recharge — the cycle the wallet is
    currently spending through. None when nothing was ever approved."""
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM recharge_requests WHERE tenant_id = ? AND status = 'approved' "
            'ORDER BY reviewed_at DESC, requested_at DESC LIMIT 1',
            (str(tenant_id),),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def get_wallet_consumed_since(tenant_id, since_iso):
    """Wallet riyals spent since ``since_iso`` — debits and holds turned
    debits. ``None`` means since the beginning of the account."""
    try:
        conn = get_db()
        where = "tenant_id = ? AND kind = 'debit'"
        params = [str(tenant_id)]
        if since_iso:
            where += " AND REPLACE(created_at, 'T', ' ') >= ?"
            params.append(str(since_iso).replace('T', ' ')[:19])
        row = conn.execute(
            'SELECT COALESCE(SUM(COALESCE(amount_sar, amount_usd)), 0) AS total '
            'FROM tenant_ledger WHERE ' + where, params,
        ).fetchone()
        return float(dict(row).get('total') or 0.0)
    except Exception:
        return 0.0
