# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Wallet funding and billing reads (t30): package recharge requests
# with platform review, client-visible package catalog and receipts, the
# points overview, and super-admin ledger adjustments. Money stays in
# tenant_ledger; these endpoints track workflow state only.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ── t30: package purchase (recharge) requests ────────────────────────────────

@app.route('/api/recharge-requests', methods=['POST'])
@require_auth
def api_create_recharge_request():
    # The platform tenant reviews company top-ups; it must never request one for
    # itself — that would let the super-admin mint wallet credit self-approved.
    if getattr(g, 'is_admin', False):
        return _landloom_forbidden('طلبات الشحن تنشأ من حسابات الشركات فقط')
    if not _landloom_can('billing'):
        return _landloom_forbidden('رفع طلبات الشحن يتطلب صلاحية الفوترة')
    data = request.json or {}
    # The catalog owns the numbers: a purchase request must point at an active
    # billing_packages row — client-supplied names, amounts and prices are
    # never trusted (they only reach the db layer through admin tooling).
    package_id = data.get('packageId') or data.get('package_id')
    if not str(package_id or '').strip():
        return jsonify({'error': 'اختر الباقة المطلوب شراؤها',
                        'error_code': 'package_required'}), 400
    row = db.create_recharge_request(
        g.tenant_id, data.get('packageName'), amount_usd=data.get('amountUsd') or 0,
        price_sar=data.get('priceSar'), transfer_reference=data.get('referenceNumber'),
        package_id=package_id,
        receipt_file_id=data.get('receiptFileId'), requested_by=_landloom_actor_id(),
        requested_by_name=_landloom_actor_name(),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('recharge.requested', 'recharge_request', row['id'],
                        entity_name=row.get('package_name'),
                        metadata={'amount_usd': row.get('amount_usd')})
    # t33: the platform desk gets a task and a notification for the 24h review window.
    db.create_approval_task(
        g.tenant_id, 'recharge',
        f'طلب شحن رصيد — {row.get("package_name") or "باقة"}',
        entity_type='recharge_request', entity_id=row['id'],
        payload={'amount_usd': row.get('amount_usd'), 'price_sar': row.get('price_sar')},
        due_hours=24)
    db.create_notification(
        g.tenant_id, 'طلب شحن جديد بانتظار المراجعة',
        body=f'{row.get("package_name") or ""} — {row.get("price_sar") or row.get("amount_usd") or ""}',
        category='recharge', entity_type='recharge_request', entity_id=row['id'])
    _notify_super_admins(
        'طلب شحن جديد',
        f'{(g.tenant or {}).get("company_name") or "شركة"} — {row.get("package_name") or ""}'
        f' — {row.get("price_sar") or row.get("amount_usd") or ""}',
        entity_type='recharge_request', entity_id=row['id'])
    return jsonify({'success': True, 'request': row})


@app.route('/api/recharge-requests', methods=['GET'])
@require_auth
def api_list_recharge_requests():
    rows = db.list_recharge_requests(g.tenant_id, status=request.args.get('status'))
    return jsonify({'success': True, 'requests': rows})


@app.route('/api/admin/recharge-requests', methods=['GET'])
@require_admin
def api_admin_list_recharge_requests():
    rows = db.list_recharge_requests(status=request.args.get('status'))
    return jsonify({'success': True, 'requests': rows})


@app.route('/api/billing/packages', methods=['GET'])
@require_auth
def api_billing_packages():
    """t33: the purchase screen lists every active package the super admin
    manages, never hardcoded prices."""
    packages = db.with_sar_fields(db.list_billing_packages(active_only=True))
    return jsonify({'success': True, 'packages': packages, 'taxRate': db.TAX_RATE_SAR})


@app.route('/api/billing/receipts', methods=['GET'])
@require_permission('billing')
def api_billing_receipts():
    """d09: the tenant's issued financial documents for approved top-ups."""
    return jsonify({'success': True, 'receipts': db.list_topup_receipts(g.tenant_id)})


@app.route('/api/billing/receipts/<receipt_id>', methods=['GET'])
@require_permission('billing')
def api_billing_receipt(receipt_id):
    row = db.get_topup_receipt(g.tenant_id, receipt_id)
    if not row:
        return jsonify({'error': 'المستند غير موجود', 'error_code': 'receipt_not_found'}), 404
    return jsonify({'success': True, 'receipt': row})


@app.route('/api/points/overview', methods=['GET'])
@require_auth
def api_points_overview():
    """t30: current, reserved, available and expired balances in one read."""
    return jsonify({'success': True, 'points': db.points_overview(g.tenant_id)})


@app.route('/api/admin/ledger/adjust', methods=['POST'])
@require_admin
def api_admin_ledger_adjust():
    """t32: refund, correction and expiry movements are a super-admin act,
    linked to the original entry they reverse when one is given."""
    data = request.json or {}
    kind = data.get('kind')
    if kind not in db.LEDGER_ADJUSTMENT_KINDS:
        return jsonify({'error': 'نوع الحركة غير معروف', 'error_code': 'invalid_kind'}), 400
    tenant_id = data.get('tenantId')
    if not tenant_id:
        return jsonify({'error': 'الشركة مطلوبة', 'error_code': 'tenant_required'}), 400
    # The desk keys adjustments in riyals; the ledger books them in USD.
    amount_usd = data.get('amountUsd')
    amount_sar = data.get('amountSar', data.get('amount_sar'))
    if amount_sar is not None:
        try:
            fx_rate = float((db.get_fx_rate() or {}).get('rate') or db.FX_DEFAULT_USD_SAR)
            amount_usd = float(amount_sar) / fx_rate
        except (TypeError, ValueError):
            return jsonify({'error': 'مبلغ الحركة غير صالح', 'error_code': 'invalid_amount'}), 400
    result = db.record_ledger_adjustment(
        tenant_id, amount_usd, kind, note=data.get('note'),
        actor=_landloom_actor_id() or 'platform_admin', reversal_of=data.get('reversalOf'),
        idempotency_key=data.get('idempotencyKey'))
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('ledger.adjusted', 'tenant_ledger',
                        (result.get('entry') or {}).get('id') or '', entity_name=kind,
                        metadata={'tenant_id': tenant_id, 'amount_usd': data.get('amountUsd'),
                                  'reversal_of': data.get('reversalOf')})
    return jsonify({'success': True, 'result': result})


@app.route('/api/admin/recharge-requests/<request_id>/decision', methods=['POST'])
@require_permission('sag_admin_panel')
def api_admin_decide_recharge_request(request_id):
    data = request.json or {}
    decision = data.get('decision')
    row = db.decide_recharge_request(
        None, request_id, decision, _landloom_actor_id(), _landloom_actor_name(),
        note=data.get('note'), reference_number=data.get('transactionReference'),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    try:
        approved = row.get('status') == 'approved'
        _notify_tenant_billing(
            row['tenant_id'],
            'اعتُمد طلب الشحن' if approved else 'رُفض طلب الشحن',
            f'{row.get("package_name") or ""} — {row.get("amount_usd") or ""}'
            + (f' — {data.get("note")}' if data.get('note') else ''),
            entity_type='recharge_request', entity_id=row['id'])
    except Exception:
        pass
    return jsonify({'success': True, 'request': row})


@app.route('/api/client/overview', methods=['GET'])
@require_auth
def api_client_overview():
    """Client card: totals, current package with remaining, lifetime spend.

    Money travels in raw USD with a riyal rendering beside it at the live
    rate. A package reads expired exactly when its remaining hits zero.
    """
    try:
        _refresh_fx_rate_async()
        view = db.get_client_overview(g.tenant_id)
        fx = db.get_fx_rate()
        package = view.get('package')
        balance_usd = db.get_tenant_balance(g.tenant_id)
        if package is not None:
            package = dict(package)
            package['credit_sar'] = db.usd_to_sar(package.get('credit_usd'), fx.get('rate'))
            package['consumed_sar'] = db.usd_to_sar(package.get('consumed_usd'), fx.get('rate'))
            package['remaining_sar'] = db.usd_to_sar(package.get('remaining_usd'), fx.get('rate'))
        else:
            # A bare wallet has no package cap; its limit is everything the
            # platform ever credited, and what left since is the consumed share.
            credited_usd = db.get_tenant_wallet_credited(g.tenant_id)
            if balance_usd > 0 or credited_usd > 0:
                consumed_usd = max(0.0, round(credited_usd - balance_usd, 2))
                package = {
                    'id': 'wallet',
                    'name': 'رصيد المحفظة',
                    'credit_usd': credited_usd,
                    'consumed_usd': consumed_usd,
                    'remaining_usd': balance_usd,
                    'status': 'active',
                    'assigned_at': None,
                    'credit_sar': db.usd_to_sar(credited_usd, fx.get('rate')),
                    'consumed_sar': db.usd_to_sar(consumed_usd, fx.get('rate')),
                    'remaining_sar': db.usd_to_sar(balance_usd, fx.get('rate')),
                }
        return jsonify({
            'success': True,
            'totals': {
                'projects': view.get('projects'),
                'presentations': view.get('presentations'),
                'consumption_usd': view.get('consumption_usd'),
                'consumption_sar': db.usd_to_sar(view.get('consumption_usd'), fx.get('rate')),
            },
            'package': package,
            'balance_usd': balance_usd,
            'balance_sar': db.usd_to_sar(balance_usd, fx.get('rate')),
            'lifetime': {
                'consumed_usd': view.get('lifetime_consumed_usd'),
                'consumed_sar': db.usd_to_sar(view.get('lifetime_consumed_usd'), fx.get('rate')),
            },
            'fx': {'rate': fx.get('rate'), 'source': fx.get('source'),
                   'updatedAt': fx.get('updated_at')},
        })
    except Exception as exc:
        print(f"[CLIENT] overview failed: {exc}")
        return jsonify({'success': False, 'error': 'تعذر تحميل بطاقة العميل'}), 500
