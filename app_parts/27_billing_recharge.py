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
                        metadata={'amount_sar': row.get('amount_sar')})
    # Recharge requests live in the billing queue — no approval task is
    # opened; the desk gets a single notification pointing at the record.
    _notify_super_admins(
        'طلب شحن جديد',
        f'{(g.tenant or {}).get("company_name") or "شركة"} — {row.get("package_name") or ""}'
        f' — {row.get("price_sar") or row.get("amount_sar") or ""} ريال',
        entity_type='recharge_request', entity_id=row['id'])
    return jsonify({'success': True, 'request': row})


@app.route('/api/recharge-requests', methods=['GET'])
@require_auth
def api_list_recharge_requests():
    try:
        rows = db.list_recharge_requests(g.tenant_id, status=request.args.get('status'))
    except Exception as exc:
        app.logger.exception('list_recharge_requests failed for tenant %s', g.tenant_id)
        return jsonify({'success': False, 'error': f'recharge_list_failed: {exc}'}), 500
    return jsonify({'success': True, 'requests': rows})


@app.route('/api/admin/recharge-requests', methods=['GET'])
@require_admin
def api_admin_list_recharge_requests():
    try:
        rows = db.list_recharge_requests(status=request.args.get('status'))
    except Exception as exc:
        app.logger.exception('admin list_recharge_requests failed')
        return jsonify({'success': False, 'error': f'recharge_list_failed: {exc}'}), 500
    return jsonify({'success': True, 'requests': rows})


@app.route('/api/recharge-requests/<request_id>/attachment/<slot>', methods=['GET'])
@require_auth
def api_recharge_request_attachment(request_id, slot):
    """Stream the transfer receipt or the platform invoice attached to a
    recharge request. The request row is the scope: a company sees only its
    own attachments, the review desk sees the receipts it must verify and the
    invoices it issued. Files live under the uploader's tenant folder, so the
    lookup is by id and the response stays confined to that tenant's root.
    """
    if slot not in ('receipt', 'invoice'):
        return jsonify({'success': False, 'error': 'المرفق غير معروف'}), 404
    row = db.get_recharge_request(request_id)
    if not row:
        return jsonify({'success': False, 'error': 'الطلب غير موجود'}), 404
    if not getattr(g, 'is_admin', False) and str(row['tenant_id']) != str(g.tenant_id):
        return jsonify({'success': False, 'error': 'الطلب غير موجود'}), 404
    file_id = row.get('receipt_file_id') if slot == 'receipt' else row.get('invoice_file_id')
    stored = db.get_project_file_by_id(str(file_id)) if file_id else None
    if not stored or not stored.get('storage_path'):
        return jsonify({'success': False, 'error': 'الملف غير موجود'}), 404
    return _send_project_file_response(stored, stored.get('tenant_id') or g.tenant_id)


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
    # The desk keys adjustments in riyals — the wallet books in SAR directly.
    amount = data.get('amountSar', data.get('amount_sar'))
    if amount is None:
        # Legacy callers sent USD; convert at the active rate.
        try:
            amount = db.usd_to_sar(data.get('amountUsd'))
        except (TypeError, ValueError):
            return jsonify({'error': 'مبلغ الحركة غير صالح', 'error_code': 'invalid_amount'}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({'error': 'مبلغ الحركة غير صالح', 'error_code': 'invalid_amount'}), 400
    result = db.record_ledger_adjustment(
        tenant_id, amount, kind, note=data.get('note'),
        actor=_landloom_actor_id() or 'platform_admin', reversal_of=data.get('reversalOf'),
        idempotency_key=data.get('idempotencyKey'))
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('ledger.adjusted', 'tenant_ledger',
                        (result.get('entry') or {}).get('id') or '', entity_name=kind,
                        metadata={'tenant_id': tenant_id, 'amount_sar': amount,
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
        invoice_file_id=data.get('invoiceFileId') or data.get('invoice_file_id'),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    try:
        approved = row.get('status') == 'approved'
        amount = row.get('amount_sar') or row.get('price_sar') or ''
        _notify_tenant_billing(
            row['tenant_id'],
            'تم شحن الرصيد' if approved else 'رُفض طلب الشحن',
            f'{row.get("package_name") or ""} — {amount} ريال'
            + (f' — {row.get("decision_note")}' if row.get('decision_note') else ''),
            entity_type='recharge_request', entity_id=row['id'])
    except Exception:
        pass
    return jsonify({'success': True, 'request': row})


# ── Recharge rejection reasons (platform settings) ────────────────────────

@app.route('/api/admin/settings/rejection-reasons', methods=['GET'])
@require_admin
def api_admin_rejection_reasons():
    return jsonify({'success': True, 'reasons': db.get_rejection_reasons()})


@app.route('/api/admin/settings/rejection-reasons', methods=['PUT'])
@require_admin
def api_admin_save_rejection_reasons():
    data = request.json or {}
    reasons = data.get('reasons')
    if not isinstance(reasons, list):
        return jsonify({'error': 'قائمة الأسباب مطلوبة', 'error_code': 'reasons_required'}), 400
    saved = db.save_rejection_reasons(reasons)
    _record_audit_event('settings.rejection_reasons', 'platform_settings',
                        'recharge_rejection_reasons',
                        metadata={'count': len(saved)})
    return jsonify({'success': True, 'reasons': saved})


@app.route('/api/client/overview', methods=['GET'])
@require_auth
def api_client_overview():
    """Client card: totals, current package with remaining, lifetime spend.

    Wallet figures are riyal-native; *_usd twins stay as provider-cost audit.
    A package reads expired exactly when its remaining hits zero.
    """
    try:
        _refresh_fx_rate_async()
        view = db.get_client_overview(g.tenant_id)
        fx = db.get_fx_rate()
        package = view.get('package')
        balance_sar = db.get_tenant_balance(g.tenant_id)
        if package is None:
            # A bare wallet has no package cap; its limit is everything the
            # platform ever credited, and what left since is the consumed
            # share. The latest approved recharge names the cycle the client
            # is spending through.
            credited_sar = db.get_tenant_wallet_credited(g.tenant_id)
            if balance_sar > 0 or credited_sar > 0:
                cycle = db.get_latest_approved_recharge(g.tenant_id)
                cycle_start = (cycle or {}).get('reviewed_at')
                consumed_sar = db.get_wallet_consumed_since(g.tenant_id, cycle_start)
                package = {
                    'id': 'wallet',
                    'name': (cycle or {}).get('package_name') or 'رصيد المحفظة',
                    'credit_sar': (cycle or {}).get('amount_sar') or credited_sar,
                    'consumed_sar': round(consumed_sar, 2),
                    'remaining_sar': round(balance_sar, 2),
                    'status': 'active' if balance_sar > 0 else 'expired',
                    'assigned_at': cycle_start,
                }
        reserved_sar = db.get_active_hold_total_sar(g.tenant_id)
        return jsonify({
            'success': True,
            'totals': {
                'projects': view.get('projects'),
                'presentations': view.get('presentations'),
                'consumption_usd': view.get('consumption_usd'),
                'consumption_sar': view.get('consumption_sar'),
            },
            'package': package,
            'balance_sar': balance_sar,
            'balance_usd': db.sar_to_usd(balance_sar, fx.get('rate')),
            'reserved_sar': round(reserved_sar, 2),
            'lifetime': {
                'consumed_usd': view.get('lifetime_consumed_usd'),
                'consumed_sar': view.get('lifetime_consumed_sar'),
            },
            'fx': {'rate': fx.get('rate'), 'source': fx.get('source'),
                   'updatedAt': fx.get('updated_at')},
        })
    except Exception as exc:
        print(f"[CLIENT] overview failed: {exc}")
        return jsonify({'success': False, 'error': 'تعذر تحميل بطاقة العميل'}), 500
