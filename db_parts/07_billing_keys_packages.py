

# ─────────────────────────────────────────────────────────────────────────────
# Billing ledger (tenant wallet debits backed by unbilled usage events)
# ─────────────────────────────────────────────────────────────────────────────

BILLING_MULTIPLIER_DEFAULT = 1.6


class InsufficientBalance(Exception):
    """Raised when a tenant wallet cannot cover a billing amount.

    Amounts are wallet riyals — the wallet is SAR-denominated; provider
    dollars only exist upstream of the conversion at billing time.
    """

    def __init__(self, required_sar=0.0, available_sar=0.0):
        self.required_sar = float(required_sar or 0.0)
        self.available_sar = float(available_sar or 0.0)
        # Legacy attribute names kept for older catch sites — same SAR figures.
        self.required_usd = self.required_sar
        self.available_usd = self.available_sar
        super().__init__(
            f'Insufficient balance: required {self.required_sar:.2f} SAR, '
            f'available {self.available_sar:.2f} SAR'
        )


def _active_fx_rate():
    """Stored USD→SAR rate for wallet conversions. Never raises."""
    try:
        rate = float((get_fx_rate() or {}).get('rate') or 0.0)
        return rate if rate > 0 else FX_DEFAULT_USD_SAR
    except Exception:
        return FX_DEFAULT_USD_SAR


# The app layer registers a callable here that re-syncs the tenant's
# provider-side spend cap whenever the wallet moves (top-up, debit, hold,
# release, adjustment). Assigned once at import; None in tests and CLI use.
BALANCE_CHANGE_HOOK = None


def _fire_balance_change(tenant_id):
    """Notify the registered listener that a wallet moved. Never raises."""
    _maybe_warn_low_balance(tenant_id)
    hook = BALANCE_CHANGE_HOOK
    if not hook or not tenant_id:
        return
    try:
        hook(tenant_id)
    except Exception as exc:
        print(f'[BILLING] balance-change hook failed for {tenant_id}: {exc}')


LOW_BALANCE_CYCLE_RATIO = 0.20


def _maybe_warn_low_balance(tenant_id):
    """One low-balance notice per recharge cycle: when the wallet drops under
    20% of the latest approved recharge (or of lifetime credit for a package-
    less wallet) the company admin gets an in-app + email notice. The notice
    is keyed to the recharge id, so a new approval re-arms the warning."""
    try:
        balance = get_tenant_balance(tenant_id)
        cycle = get_latest_approved_recharge(tenant_id)
        base = float((cycle or {}).get('amount_sar') or 0.0)
        cycle_key = str((cycle or {}).get('id') or 'wallet')
        if base <= 0:
            base = float(get_tenant_wallet_credited(tenant_id) or 0.0)
        if base <= 0 or balance >= base * LOW_BALANCE_CYCLE_RATIO:
            return
        if recent_notification_exists(
                tenant_id, 'low_balance', cycle_key, since_hours=24 * 3650):
            return
        tenant = get_tenant_by_id(tenant_id)
        create_notification(
            tenant_id, 'رصيدك أوشك على الانتهاء',
            body='الرصيد المتاح أقل من 20% من قيمة آخر شحنة — جدّد الباقة لتفادي توقف التوليد.',
            category='billing', user_id='tenant-admin:' + str(tenant_id),
            entity_type='low_balance', entity_id=cycle_key,
            email_to=(tenant or {}).get('email'))
    except Exception as exc:
        print(f'[BILLING] low-balance check failed for {tenant_id}: {exc}')


def get_billing_multiplier():
    """Markup applied to raw provider cost at billing time. Env-overridable."""
    try:
        value = float(os.environ.get('BILLING_MULTIPLIER') or BILLING_MULTIPLIER_DEFAULT)
    except (TypeError, ValueError):
        value = BILLING_MULTIPLIER_DEFAULT
    return max(0.0, value)


def billing_enforcement_enabled():
    """Pre-flight balance checks run only when explicitly enabled."""
    return str(os.environ.get('BILLING_ENFORCE') or '').strip() == '1'


def get_billing_flow_estimates():
    """Conservative billed-USD estimates per expensive flow. Env-overridable."""
    defaults = {
        'analyze_site': 1.0,
        'site_analysis': 0.5,
        'map_image': 0.5,
        'slide_plan': 0.5,
        'slide_single': 0.25,
        'market_competitors': 1.0,
        'market_summary': 1.0,
        'croquis': 0.5,
        'image_generation': 0.5,
        'visual_concept': 0.25,
        'executive_content': 0.25,
        'designer_chat': 0.5,
        'ai_text': 0.25,
    }
    try:
        overrides = json.loads(os.environ.get('BILLING_PREFLIGHT_ESTIMATES') or '{}')
    except (TypeError, ValueError):
        overrides = {}
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            try:
                defaults[key] = max(0.0, float(value))
            except (TypeError, ValueError):
                continue
    return defaults


# Product price per generation unit in USD. This is what the client is charged
# (converted to points at POINTS_PER_USD), independent of the provider cost that
# usage events record — env-overridable as the effective pricing policy. The
# wallet itself is SAR-denominated, so wallet conversions run through the
# configured fx rate.
POINTS_PER_USD = 1000
GENERATION_UNIT_PRICES_DEFAULT = {
    'slide': 0.05,
    'map': 0.15,
    'image': 0.10,
    'plan': 0.25,
}
RESERVATION_TTL_HOURS = 6


def get_generation_unit_prices():
    """Effective per-unit generation pricing. Env-overridable via JSON."""
    defaults = dict(GENERATION_UNIT_PRICES_DEFAULT)
    try:
        overrides = json.loads(os.environ.get('GENERATION_UNIT_PRICES') or '{}')
    except (TypeError, ValueError):
        overrides = {}
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            try:
                defaults[key] = max(0.0, float(value))
            except (TypeError, ValueError):
                continue
    return defaults


def get_tenant_balance(tenant_id):
    """Current wallet balance in SAR — the wallet is riyal-denominated.
    Never raises for a missing tenant."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT credit_balance FROM tenants WHERE id = ?', (tenant_id,)
        ).fetchone()
    except Exception:
        return 0.0
    if row is None:
        return 0.0
    try:
        return float(dict(row).get('credit_balance') or 0.0)
    except (TypeError, ValueError):
        return 0.0


def get_tenant_wallet_credited(tenant_id):
    """Total SAR ever placed in the wallet: top-ups plus positive adjustments.

    A release is excluded — it is held money coming back, not new credit —
    while holds and debits carry positive amounts but move money out, so the
    sum whitelists incoming kinds only. The dashboard balance card reads this
    as the wallet's effective limit; consumed = credited - balance.
    """
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT COALESCE(SUM(COALESCE(amount_sar, amount_usd)), 0) AS total '
            "FROM tenant_ledger WHERE tenant_id = ? AND COALESCE(amount_sar, amount_usd) > 0 "
            "AND kind IN ('credit', 'refund', 'correction', 'expiry')",
            (str(tenant_id),)
        ).fetchone()
        return round(float(dict(row).get('total') or 0.0), 2)
    except Exception:
        return 0.0


# AI events checkout may claim: a verified cost ('settled'), a completed call
# with nothing left to reconcile ('unresolved'), or a legacy row that predates
# attempt tracking but already carries a cost. 'pending', 'in_flight' and
# 'needs_review' rows stay unbilled until the reconcile loop prices them —
# claiming them early would lock them at $0 forever.
_AI_BILLABLE_STATUS_CLAUSE = (
    "COALESCE(attempt_status, CASE WHEN cost_usd IS NOT NULL THEN 'settled' "
    "ELSE 'pending' END) IN ('settled', 'unresolved')"
)


def _live_hold_exclusion_sql(tenant_ref):
    """ISS-034: usage rows under a draft or presentation covered by a live
    point hold are prepaid by the reservation — the settlement claims them
    under its own ledger entry, so billing them here would charge the run
    twice. ``tenant_ref`` is either a bound '?' or a correlated column; the
    unqualified draft_id/presentation_id resolve to the statement's own
    usage-events table in both UPDATE and SELECT contexts."""
    return (
        '(draft_id IS NULL OR draft_id NOT IN ('
        'SELECT draft_id FROM point_reservations '
        f"WHERE status = 'reserved' AND draft_id IS NOT NULL AND tenant_id = {tenant_ref})) "
        'AND (presentation_id IS NULL OR presentation_id NOT IN ('
        'SELECT ga.presentation_id FROM point_reservations pr '
        'JOIN generation_approvals ga ON ga.id = pr.generation_approval_id '
        f"WHERE pr.status = 'reserved' AND ga.presentation_id IS NOT NULL "
        f'AND pr.tenant_id = {tenant_ref}))'
    )


def _unbilled_scope_clause(tenant_id, draft_id=None, presentation_id=None,
                           ai_settled_only=False):
    # package_id IS NULL: a usage row burned under an assigned package is
    # consumed against that package's credit — it is never wallet-billable
    # and must not be double-charged by checkout or counted as unbilled.
    clauses = ['tenant_id = ?', 'billed_ledger_id IS NULL', 'package_id IS NULL']
    params = [tenant_id]
    clauses.append(_live_hold_exclusion_sql('?'))
    params.extend([tenant_id, tenant_id])
    if ai_settled_only:
        clauses.append(_AI_BILLABLE_STATUS_CLAUSE)
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(presentation_id)
    return 'WHERE ' + ' AND '.join(clauses), params


def get_unbilled_usage(tenant_id, draft_id=None, presentation_id=None):
    """Raw cost of usage events that no ledger entry has billed yet."""
    conn = get_db()
    ai_where, ai_params = _unbilled_scope_clause(tenant_id, draft_id, presentation_id)
    maps_where, maps_params = _unbilled_scope_clause(tenant_id, draft_id, presentation_id)
    ai_row = conn.execute(
        'SELECT COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM ai_usage_events {ai_where}',
        ai_params
    ).fetchone()
    maps_row = conn.execute(
        'SELECT COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM map_usage_events {maps_where}',
        maps_params
    ).fetchone()
    ai_calls = int(dict(ai_row).get('calls') or 0)
    maps_calls = int(dict(maps_row).get('calls') or 0)
    ai_cost = float(dict(ai_row).get('cost_usd') or 0.0)
    maps_cost = float(dict(maps_row).get('cost_usd') or 0.0)
    return with_sar_fields({
        'ai_calls': ai_calls,
        'maps_calls': maps_calls,
        'ai_cost_usd': ai_cost,
        'maps_cost_usd': maps_cost,
        'raw_cost_usd': ai_cost + maps_cost,
    })


def bill_unbilled_usage(tenant_id, draft_id=None, presentation_id=None,
                        idempotency_key=None, multiplier=None, note=None):
    """Bill every unbilled usage event in scope. Fully idempotent.

    The claim step marks unbilled rows with the new ledger id in a single
    UPDATE, so a retry or a parallel request finds an empty unbilled scope
    instead of billing the same events twice. The wallet debit is a
    conditional UPDATE on the balance it read, so a lost race surfaces as
    InsufficientBalance rather than an overdraft. One commit covers the
    claim, the ledger row and the debit. Any failure rolls everything back.
    """
    conn = get_db()
    if idempotency_key:
        existing = conn.execute(
            'SELECT * FROM tenant_ledger WHERE tenant_id = ? AND idempotency_key = ?',
            (tenant_id, idempotency_key)
        ).fetchone()
        if existing:
            return {'billed': False, 'reason': 'idempotency_key_replayed',
                    'entry': dict(existing)}
    # An expired hold must not keep its usage unbillable — sweep stale rows
    # before the exclusion below decides what is still prepaid.
    release_stale_reservations(tenant_id)
    ledger_id = str(uuid.uuid4())
    try:
        try:
            active_multiplier = float(multiplier) if multiplier is not None else get_billing_multiplier()
        except (TypeError, ValueError):
            active_multiplier = get_billing_multiplier()
        active_multiplier = max(0.0, active_multiplier)
        ai_where, ai_params = _unbilled_scope_clause(
            tenant_id, draft_id, presentation_id, ai_settled_only=True)
        maps_where, maps_params = _unbilled_scope_clause(tenant_id, draft_id, presentation_id)
        ai_claim = conn.execute(
            'UPDATE ai_usage_events SET billed_ledger_id = ? ' + ai_where,
            tuple([ledger_id] + ai_params)
        )
        maps_claim = conn.execute(
            'UPDATE map_usage_events SET billed_ledger_id = ? ' + maps_where,
            tuple([ledger_id] + maps_params)
        )
        ai_count = ai_claim.rowcount if ai_claim.rowcount is not None else 0
        maps_count = maps_claim.rowcount if maps_claim.rowcount is not None else 0
        if ai_count <= 0 and maps_count <= 0:
            conn.rollback()
            return {'billed': False, 'reason': 'no_unbilled_events'}
        ai_cost = float(dict(conn.execute(
            'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM ai_usage_events WHERE billed_ledger_id = ?',
            (ledger_id,)
        ).fetchone()).get('total') or 0.0)
        maps_cost = float(dict(conn.execute(
            'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM map_usage_events WHERE billed_ledger_id = ?',
            (ledger_id,)
        ).fetchone()).get('total') or 0.0)
        raw_cost = ai_cost + maps_cost
        # Provider cost arrives in USD; the wallet is SAR, so the billed
        # amount converts at the active rate before the multiplier applies.
        try:
            fx_rate = float((get_fx_rate() or {}).get('rate') or FX_DEFAULT_USD_SAR)
        except (TypeError, ValueError):
            fx_rate = FX_DEFAULT_USD_SAR
        billed_amount = round(raw_cost * fx_rate * active_multiplier + 1e-9, 2)
        if raw_cost > 0 and billed_amount <= 0:
            # A sub-cent claim must not close: rolling the claim back keeps the
            # rows unbilled so the cents carry into the next invoice instead of
            # being marked paid at 0 forever.
            conn.rollback()
            return {'billed': False, 'reason': 'below_minimum_charge'}
        debit = conn.execute(
            'UPDATE tenants SET credit_balance = credit_balance - ? '
            'WHERE id = ? AND credit_balance >= ?',
            (billed_amount, tenant_id, billed_amount)
        )
        if (debit.rowcount or 0) <= 0:
            conn.rollback()
            raise InsufficientBalance(billed_amount, get_tenant_balance(tenant_id))
        conn.execute(
            '''INSERT INTO tenant_ledger
               (id, tenant_id, kind, amount_usd, amount_sar, fx_rate, raw_cost_usd, multiplier,
                maps_cost_usd, ai_cost_usd, maps_events_count, ai_events_count,
                draft_id, presentation_id, idempotency_key, note)
               VALUES (?, ?, 'debit', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (ledger_id, tenant_id, round(raw_cost * active_multiplier + 1e-9, 2),
             billed_amount, fx_rate, raw_cost, active_multiplier,
             maps_cost, ai_cost, max(0, int(maps_count)), max(0, int(ai_count)),
             draft_id, presentation_id, idempotency_key, note)
        )
        conn.commit()
    except InsufficientBalance:
        raise
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    _fire_balance_change(tenant_id)
    entry = conn.execute(
        'SELECT * FROM tenant_ledger WHERE id = ?', (ledger_id,)
    ).fetchone()
    return {'billed': True, 'entry': dict(entry),
            'balance_sar': get_tenant_balance(tenant_id)}


def record_ledger_credit(tenant_id, amount_sar, note=None, idempotency_key=None, actor=None):
    """Top up a tenant wallet. Records a credit entry and adds the balance.

    ``amount_sar`` is wallet riyals — the wallet is SAR-denominated; the
    amount_usd column keeps the dollar equivalent for provider-side audit.
    ``actor`` names who created the movement — 'platform_admin' for the
    recharge-decision path, 'client_admin' for a client-side top-up — so the
    separation-of-duties matrix can flag credits from the wrong side (t23).
    """
    amount = round(float(amount_sar or 0.0) + 1e-9, 2)
    if amount <= 0:
        raise ValueError('Credit amount must be positive')
    conn = get_db()
    if idempotency_key:
        existing = conn.execute(
            'SELECT * FROM tenant_ledger WHERE tenant_id = ? AND idempotency_key = ?',
            (tenant_id, idempotency_key)
        ).fetchone()
        if existing:
            return {'credited': False, 'reason': 'idempotency_key_replayed',
                    'entry': dict(existing)}
    ledger_id = str(uuid.uuid4())
    try:
        conn.execute(
            'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) + ? WHERE id = ?',
            (amount, tenant_id)
        )
        conn.execute(
            '''INSERT INTO tenant_ledger
               (id, tenant_id, kind, amount_usd, amount_sar, fx_rate, raw_cost_usd, multiplier,
                maps_cost_usd, ai_cost_usd, maps_events_count, ai_events_count,
                draft_id, presentation_id, idempotency_key, note, actor)
               VALUES (?, ?, 'credit', ?, ?, ?, 0, 1, 0, 0, 0, 0, NULL, NULL, ?, ?, ?)''',
            (ledger_id, tenant_id, sar_to_usd(amount), amount, _active_fx_rate(),
             idempotency_key, note, actor)
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    _fire_balance_change(tenant_id)
    entry = conn.execute(
        'SELECT * FROM tenant_ledger WHERE id = ?', (ledger_id,)
    ).fetchone()
    return {'credited': True, 'entry': dict(entry),
            'balance_sar': get_tenant_balance(tenant_id)}


def reset_all_company_balances(clear_usage=True):
    """Forced fresh start: zero wallets and unassign packages, optionally
    wiping spend history too. Super-admin tenants are never touched.
    Provider key rows stay (identity only); limits re-sync on next assign."""
    conn = get_db()
    scope = 'COALESCE(is_admin, 0) != 1'
    try:
        affected_tenants = [row[0] for row in conn.execute(
            f'SELECT id FROM tenants WHERE {scope}').fetchall()]
    except Exception:
        affected_tenants = []
    wallets = conn.execute(
        f'UPDATE tenants SET credit_balance = 0, package_id = NULL WHERE {scope}')
    result = {'tenants_reset': wallets.rowcount or 0, 'ai_deleted': 0,
              'maps_deleted': 0, 'history_deleted': 0, 'ledger_deleted': 0}
    if clear_usage:
        for table, key in (('ai_usage_events', 'ai_deleted'),
                           ('map_usage_events', 'maps_deleted'),
                           ('tenant_package_history', 'history_deleted'),
                           ('tenant_ledger', 'ledger_deleted')):
            try:
                cur = conn.execute(
                    f'DELETE FROM {table} WHERE tenant_id IN '
                    f'(SELECT id FROM tenants WHERE {scope})')
                result[key] = cur.rowcount or 0
            except Exception:
                pass
    conn.commit()
    for _tid in affected_tenants:
        _fire_balance_change(_tid)
    return result


def _norm_range_bound(value, is_end=False):
    """Normalize a UI date/datetime bound ('YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM')
    to the stored 'YYYY-MM-DD HH:MM:SS' format so string comparison works."""
    s = str(value or '').strip().replace('T', ' ')
    if not s:
        return ''
    if len(s) == 10:
        return s + (' 23:59:59' if is_end else ' 00:00:00')
    if len(s) == 16:
        return s + (':59' if is_end else ':00')
    return s


def get_ledger_entries(tenant_id, limit=50, kind=None, from_date=None, to_date=None,
                       draft_id=None, presentation_id=None, actor=None):
    """Newest ledger entries for a tenant, with the t32 report filters:
    period, project file, presentation, movement kind and actor."""
    conn = get_db()
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if kind:
        clauses.append('kind = ?')
        params.append(str(kind))
    if from_date:
        clauses.append('created_at >= ?')
        params.append(_norm_range_bound(from_date))
    if to_date:
        clauses.append('created_at <= ?')
        params.append(_norm_range_bound(to_date, is_end=True))
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(str(draft_id))
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(str(presentation_id))
    if actor:
        clauses.append('actor = ?')
        params.append(str(actor))
    rows = conn.execute(
        'SELECT id, kind, amount_usd, amount_sar, fx_rate, raw_cost_usd, multiplier, '
        'maps_cost_usd, ai_cost_usd, maps_events_count, ai_events_count, draft_id, '
        'presentation_id, idempotency_key, note, actor, reversal_of, created_at '
        'FROM tenant_ledger WHERE ' + ' AND '.join(clauses) +
        ' ORDER BY created_at DESC LIMIT ?',
        params + [int(limit)]
    ).fetchall()
    return with_sar_fields([dict(r) for r in rows])


def points_overview(tenant_id):
    """One read of the wallet — current balance, live holds, expired and
    consumed totals. Wallet figures are SAR; *_usd twins are the provider-side
    audit equivalent."""
    release_stale_reservations(tenant_id)
    conn = get_db()
    balance = get_tenant_balance(tenant_id)
    rows = conn.execute(
        '''SELECT status, COALESCE(SUM(COALESCE(cost_sar, cost_usd)), 0) AS total, COUNT(*) AS n
           FROM point_reservations WHERE tenant_id = ? GROUP BY status''',
        (str(tenant_id),),
    ).fetchall()
    buckets = {row['status']: {'sar': float(row['total'] or 0), 'count': int(row['n'])}
               for row in rows}
    reserved_sar = buckets.get('reserved', {}).get('sar', 0.0)
    expired_sar = buckets.get('expired', {}).get('sar', 0.0)
    total_sar = balance + reserved_sar
    return {
        'balance_sar': round(total_sar, 2),
        'balance_points': int(round(total_sar * POINTS_PER_USD)),
        'current_points': int(round(total_sar * POINTS_PER_USD)),
        'reserved_sar': round(reserved_sar, 2),
        'reserved_points': int(round(reserved_sar * POINTS_PER_USD)),
        'available_sar': round(balance, 2),
        'available_points': int(round(balance * POINTS_PER_USD)),
        'expired_sar': round(expired_sar, 2),
        'expired_points': int(round(expired_sar * POINTS_PER_USD)),
        'consumed_sar': round(buckets.get('consumed', {}).get('sar', 0.0), 2),
        'released_sar': round(buckets.get('released', {}).get('sar', 0.0), 2),
        'reservations': buckets,
    }


LEDGER_ADJUSTMENT_KINDS = ('refund', 'correction', 'expiry')


def record_ledger_adjustment(tenant_id, amount_sar, kind, note=None, actor=None,
                             reversal_of=None, idempotency_key=None):
    """t32: refund, correction and expiry movements on the wallet.

    A positive amount credits the wallet, a negative amount debits it
    (conditional — never overdrawn). Amounts are wallet riyals.
    ``reversal_of`` links the movement back to the original ledger entry it
    reverses. Admin-only at the route level.
    """
    if kind not in LEDGER_ADJUSTMENT_KINDS:
        return {'error': 'invalid_kind'}
    amount = round(float(amount_sar or 0.0) + 1e-9, 2)
    if amount == 0:
        return {'error': 'amount_required'}
    conn = get_db()
    if reversal_of:
        original = conn.execute(
            'SELECT * FROM tenant_ledger WHERE id = ? AND tenant_id = ?',
            (str(reversal_of), tenant_id),
        ).fetchone()
        if not original:
            return {'error': 'original_entry_not_found'}
    if idempotency_key:
        existing = conn.execute(
            'SELECT * FROM tenant_ledger WHERE tenant_id = ? AND idempotency_key = ?',
            (tenant_id, idempotency_key),
        ).fetchone()
        if existing:
            return {'adjusted': False, 'reason': 'idempotency_key_replayed',
                    'entry': dict(existing)}
    if amount < 0:
        debit = conn.execute(
            'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) + ? '
            'WHERE id = ? AND COALESCE(credit_balance, 0) >= ?',
            (amount, tenant_id, -amount),
        )
        if (debit.rowcount or 0) <= 0:
            return {'error': 'insufficient_balance',
                    'available_sar': get_tenant_balance(tenant_id)}
    else:
        conn.execute(
            'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) + ? WHERE id = ?',
            (amount, tenant_id),
        )
    ledger_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO tenant_ledger
           (id, tenant_id, kind, amount_usd, amount_sar, fx_rate,
            idempotency_key, note, actor, reversal_of)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (ledger_id, tenant_id, kind, sar_to_usd(amount), amount, _active_fx_rate(),
         idempotency_key, str(note or '').strip() or None, actor, reversal_of),
    )
    conn.commit()
    _fire_balance_change(tenant_id)
    return {'adjusted': True,
            'entry': dict(conn.execute(
                'SELECT * FROM tenant_ledger WHERE id = ?', (ledger_id,)).fetchone()),
            'balance_sar': get_tenant_balance(tenant_id)}


# ─────────────────────────────────────────────────────────────────────────────
# Per-tenant OpenRouter keys. One row per company. Managed keys are created
# through the OpenRouter Management API so they show in the owner dashboard
# with their own spend limit. Manual keys are pasted by a super admin.
# The raw value is stored encrypted and metadata reads never return it.
# ─────────────────────────────────────────────────────────────────────────────

TENANT_KEY_PROVENANCES = ('auto', 'manual')
TENANT_KEY_LIMIT_RESETS = ('daily', 'weekly', 'monthly', 'none')


def _tenant_key_secret():
    """Bytes used to obscure stored provider keys. Env-overridable."""
    configured = (os.environ.get('OPENROUTER_KEY_ENCRYPTION_SECRET') or '').strip()
    if configured:
        return configured.encode('utf-8')
    fallback = (os.environ.get('JWT_SECRET') or '').strip()
    if fallback:
        return fallback.encode('utf-8')
    try:
        base_dir = os.path.abspath(os.path.dirname(__file__))
        secret_path = os.path.abspath(os.path.join(base_dir, '.jwt_secret'))
        if os.path.commonpath([base_dir, secret_path]) == base_dir and os.path.exists(secret_path):
            with open(secret_path, 'r', encoding='utf-8') as secret_file:
                stored = secret_file.read().strip()
                if stored:
                    return stored.encode('utf-8')
    except Exception:
        pass
    return b'dev-only-tenant-key-secret'


def _tenant_key_stream(secret, nonce, length):
    """SHA256 counter stream for XOR obscuring without new dependencies."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hashlib.sha256(secret + nonce + counter.to_bytes(4, 'big')).digest())
        counter += 1
    return bytes(out[:length])


def encrypt_tenant_openrouter_key(raw_key):
    """Obscure a provider key for storage with tamper detection."""
    import base64 as _b64
    import hmac as _hmac
    import secrets as _secrets
    secret = _tenant_key_secret()
    raw = (raw_key or '').strip().encode('utf-8')
    if not raw:
        raise ValueError('Empty provider key')
    nonce = _secrets.token_bytes(16)
    stream = _tenant_key_stream(secret, nonce, len(raw))
    cipher = bytes(a ^ b for a, b in zip(raw, stream))
    tag = _hmac.new(secret, nonce + cipher, hashlib.sha256).hexdigest()
    return 'v1.' + _b64.urlsafe_b64encode(nonce).decode('ascii') + '.' \
        + _b64.urlsafe_b64encode(cipher).decode('ascii') + '.' + tag


def decrypt_tenant_openrouter_key(enc_value):
    """Reverse encrypt_tenant_openrouter_key. Returns None when tampered."""
    import base64 as _b64
    import hmac as _hmac
    try:
        if not enc_value or not isinstance(enc_value, str):
            return None
        parts = enc_value.split('.')
        if len(parts) != 4 or parts[0] != 'v1':
            return None
        secret = _tenant_key_secret()
        nonce = _b64.urlsafe_b64decode(parts[1].encode('ascii'))
        cipher = _b64.urlsafe_b64decode(parts[2].encode('ascii'))
        tag = parts[3]
        expected = _hmac.new(secret, nonce + cipher, hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(expected, tag):
            return None
        stream = _tenant_key_stream(secret, nonce, len(cipher))
        return bytes(a ^ b for a, b in zip(cipher, stream)).decode('utf-8')
    except Exception:
        return None


def _tenant_key_public(row):
    """Public metadata for a key row. The raw secret never leaves the server."""
    if row is None:
        return {'has_key': False}
    try:
        data = dict(row)
    except Exception:
        return {'has_key': False}
    key_hash = str(data.get('key_hash') or '')
    return {
        'has_key': True,
        'key_hint': ('...' + key_hash[-4:]) if len(key_hash) >= 4 else '...',
        'key_label': data.get('key_label'),
        'openrouter_key_hash': data.get('openrouter_key_hash'),
        'limit_usd': data.get('limit_usd'),
        'limit_reset': data.get('limit_reset'),
        'provenance': data.get('provenance') or 'auto',
        'is_active': bool(data.get('is_active')),
        'last_limit_remaining': data.get('last_limit_remaining'),
        'last_usage': data.get('last_usage'),
        'last_checked_at': data.get('last_checked_at'),
        'cap_sync_pending': bool(data.get('cap_sync_pending')),
        'updated_at': data.get('updated_at'),
        'created_at': data.get('created_at'),
    }


def get_tenant_openrouter_key_meta(tenant_id):
    """Public key status for one tenant. Never includes the secret."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT * FROM tenant_openrouter_keys WHERE tenant_id = ?',
            (str(tenant_id),)
        ).fetchone()
    except Exception:
        return {'has_key': False}
    return _tenant_key_public(row)


def list_tenant_key_states():
    """tenant_id -> public key metadata for every stored row, in one query.

    The admin companies list calls this once instead of paying a lookup per
    row. A tenant with no row is simply absent from the map.
    """
    try:
        conn = get_db()
        rows = conn.execute('SELECT * FROM tenant_openrouter_keys').fetchall()
    except Exception:
        return {}
    return {row['tenant_id']: _tenant_key_public(row) for row in rows}


def get_tenant_openrouter_key_raw(tenant_id):
    """Decrypted provider key for server-side calls only. None when absent."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT key_enc FROM tenant_openrouter_keys WHERE tenant_id = ? AND is_active = 1',
            (str(tenant_id),)
        ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    try:
        enc = dict(row).get('key_enc')
    except Exception:
        return None
    raw = decrypt_tenant_openrouter_key(enc)
    return raw if raw else None


def set_tenant_openrouter_key(tenant_id, raw_key, key_label=None, limit_usd=None,
                              limit_reset=None, provenance='manual',
                              openrouter_key_hash=None):
    """Create or replace one tenant key. Returns public metadata only."""
    tenant_id = str(tenant_id or '').strip()
    if not tenant_id:
        raise ValueError('tenant_id is required')
    raw = (raw_key or '').strip()
    if len(raw) < 16:
        raise ValueError('Invalid provider key')
    if provenance not in TENANT_KEY_PROVENANCES:
        provenance = 'manual'
    if limit_reset is not None and limit_reset not in TENANT_KEY_LIMIT_RESETS:
        raise ValueError('Invalid limit_reset')
    amount = None
    if limit_usd is not None:
        try:
            amount = float(limit_usd)
        except (TypeError, ValueError):
            raise ValueError('Invalid limit_usd')
        if amount < 0:
            raise ValueError('Invalid limit_usd')
    enc = encrypt_tenant_openrouter_key(raw)
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    conn = get_db()
    now = _utcnow().strftime('%Y-%m-%d %H:%M:%S')
    existing = conn.execute(
        'SELECT id FROM tenant_openrouter_keys WHERE tenant_id = ?', (tenant_id,)
    ).fetchone()
    if existing:
        conn.execute(
            'UPDATE tenant_openrouter_keys SET key_enc = ?, key_hash = ?, key_label = ?, '
            'openrouter_key_hash = ?, limit_usd = ?, limit_reset = ?, provenance = ?, '
            'is_active = 1, updated_at = ? WHERE tenant_id = ?',
            (enc, digest, (key_label or None), (openrouter_key_hash or None),
             amount, limit_reset, provenance, now, tenant_id)
        )
    else:
        conn.execute(
            'INSERT INTO tenant_openrouter_keys (id, tenant_id, key_enc, key_hash, key_label, '
            'openrouter_key_hash, limit_usd, limit_reset, provenance, is_active, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)',
            (str(uuid.uuid4()), tenant_id, enc, digest, (key_label or None),
             (openrouter_key_hash or None), amount, limit_reset, provenance, now)
        )
    conn.commit()
    return get_tenant_openrouter_key_meta(tenant_id)


def update_tenant_openrouter_key_meta(tenant_id, limit_usd=None, limit_reset=None,
                                      is_active=None, last_limit_remaining=None,
                                      last_usage=None, openrouter_key_hash=None,
                                      cap_sync_pending=None):
    """Update key metadata without touching the secret. Returns public metadata."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM tenant_openrouter_keys WHERE tenant_id = ?', (str(tenant_id),)
    ).fetchone()
    if row is None:
        return {'has_key': False}
    assignments = []
    params = []
    if limit_usd is not None:
        try:
            amount = float(limit_usd)
        except (TypeError, ValueError):
            raise ValueError('Invalid limit_usd')
        if amount < 0:
            raise ValueError('Invalid limit_usd')
        assignments.append('limit_usd = ?')
        params.append(amount)
    if limit_reset is not None:
        if limit_reset not in TENANT_KEY_LIMIT_RESETS:
            raise ValueError('Invalid limit_reset')
        assignments.append('limit_reset = ?')
        params.append(limit_reset)
    if is_active is not None:
        assignments.append('is_active = ?')
        params.append(1 if is_active else 0)
    if last_limit_remaining is not None:
        try:
            assignments.append('last_limit_remaining = ?')
            params.append(float(last_limit_remaining))
        except (TypeError, ValueError):
            pass
    if last_usage is not None:
        try:
            assignments.append('last_usage = ?')
            params.append(float(last_usage))
        except (TypeError, ValueError):
            pass
    if openrouter_key_hash is not None:
        assignments.append('openrouter_key_hash = ?')
        params.append(str(openrouter_key_hash or None))
    if cap_sync_pending is not None:
        assignments.append('cap_sync_pending = ?')
        params.append(1 if cap_sync_pending else 0)
    if last_limit_remaining is not None or last_usage is not None:
        assignments.append('last_checked_at = ?')
        params.append(_utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    if not assignments:
        return get_tenant_openrouter_key_meta(tenant_id)
    assignments.append('updated_at = ?')
    params.append(_utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    params.append(str(tenant_id))
    conn.execute(
        'UPDATE tenant_openrouter_keys SET ' + ', '.join(assignments) + ' WHERE tenant_id = ?',
        tuple(params)
    )
    conn.commit()
    return get_tenant_openrouter_key_meta(tenant_id)


def deactivate_tenant_openrouter_key(tenant_id):
    """Disable a tenant key locally. Returns public metadata."""
    return update_tenant_openrouter_key_meta(tenant_id, is_active=False)


def list_tenant_keys_pending_cap_sync(limit=25):
    """tenant_ids whose last provider-cap push never confirmed, oldest rows
    first. The housekeeping sweep retries them so one failed PATCH cannot
    leave the dashboard limit stale until the next wallet movement."""
    try:
        conn = get_db()
        rows = conn.execute(
            'SELECT tenant_id FROM tenant_openrouter_keys '
            'WHERE cap_sync_pending = 1 AND is_active = 1 '
            'ORDER BY updated_at LIMIT ?',
            (int(limit),)
        ).fetchall()
    except Exception:
        return []
    return [row['tenant_id'] for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Billing packages and the USD to SAR rate for riyal-denominated balances.
# ─────────────────────────────────────────────────────────────────────────────

FX_PAIR_USD_SAR = 'USD_SAR'
FX_DEFAULT_USD_SAR = 3.75
FX_REFRESH_SECONDS = 24 * 3600


def list_billing_packages(active_only=False):
    """All packages, newest last, each carrying the current active version's
    validity window and feature terms for the purchase screen. Never raises."""
    try:
        conn = get_db()
        rows = conn.execute(
            'SELECT p.*, v.duration_days, v.features_json '
            'FROM billing_packages p '
            'LEFT JOIN billing_package_versions v ON v.id = ('
            '  SELECT id FROM billing_package_versions '
            '  WHERE package_id = p.id AND is_active = 1 '
            '  ORDER BY version DESC LIMIT 1) '
            + ('WHERE p.is_active = 1 ' if active_only else '')
            + 'ORDER BY p.created_at ASC'
        ).fetchall()
        items = []
        for r in rows:
            item = dict(r)
            item['features'] = _json_or(item.get('features_json'), [])
            items.append(item)
        return items
    except Exception:
        return []


def get_billing_package(package_id):
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT * FROM billing_packages WHERE id = ?', (str(package_id),)).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def create_billing_package(name, credit_sar=0.0, price_sar=None, is_custom=True):
    """Create a package. credit_sar may be zero (prepaid, topped up later).

    The wallet credit is riyal-denominated; ``credit_usd`` on the row keeps
    the dollar equivalent for provider-side audit only.
    """
    label = str(name or '').strip()
    if not label or len(label) > 120:
        raise ValueError('Invalid package name')
    try:
        credit = round(float(credit_sar or 0.0) + 1e-9, 2)
    except (TypeError, ValueError):
        raise ValueError('Invalid credit_sar')
    if credit < 0:
        raise ValueError('Invalid credit_sar')
    price = None
    if price_sar is not None:
        try:
            price = round(float(price_sar) + 1e-9, 2)
        except (TypeError, ValueError):
            raise ValueError('Invalid price_sar')
        if price < 0:
            raise ValueError('Invalid price_sar')
    conn = get_db()
    package_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO billing_packages (id, name, credit_usd, credit_sar, price_sar, is_active, is_custom) '
        'VALUES (?, ?, ?, ?, ?, 1, ?)',
        (package_id, label, sar_to_usd(credit), credit, price, 1 if is_custom else 0)
    )
    conn.commit()
    return get_billing_package(package_id)


def update_billing_package(package_id, name=None, credit_sar=None, price_sar=None,
                           is_active=None):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM billing_packages WHERE id = ?', (str(package_id),)).fetchone()
    if row is None:
        return None
    assignments = []
    params = []
    if name is not None:
        label = str(name or '').strip()
        if not label or len(label) > 120:
            raise ValueError('Invalid package name')
        assignments.append('name = ?')
        params.append(label)
    if credit_sar is not None:
        try:
            credit = round(float(credit_sar) + 1e-9, 2)
        except (TypeError, ValueError):
            raise ValueError('Invalid credit_sar')
        if credit < 0:
            raise ValueError('Invalid credit_sar')
        assignments.append('credit_sar = ?')
        params.append(credit)
        assignments.append('credit_usd = ?')
        params.append(sar_to_usd(credit))
    if price_sar is not None:
        try:
            price = round(float(price_sar) + 1e-9, 2)
        except (TypeError, ValueError):
            raise ValueError('Invalid price_sar')
        if price < 0:
            raise ValueError('Invalid price_sar')
        assignments.append('price_sar = ?')
        params.append(price)
    if is_active is not None:
        assignments.append('is_active = ?')
        params.append(1 if is_active else 0)
    if not assignments:
        return dict(row)
    assignments.append("updated_at = datetime('now')")
    params.append(str(package_id))
    conn.execute(
        'UPDATE billing_packages SET ' + ', '.join(assignments) + ' WHERE id = ?',
        tuple(params)
    )
    conn.commit()
    return get_billing_package(package_id)


def delete_billing_package(package_id):
    """Delete a package; tenants on it keep their key limit, package unset."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM billing_packages WHERE id = ?', (str(package_id),)).fetchone()
    if row is None:
        return False
    try:
        conn.execute('UPDATE tenants SET package_id = NULL WHERE package_id = ?',
                     (str(package_id),))
    except Exception:
        pass
    conn.execute('DELETE FROM billing_packages WHERE id = ?', (str(package_id),))
    conn.commit()
    return True


def assign_tenant_package(tenant_id, package_id):
    """Attach a tenant to a package. Returns (tenant, package)."""
    conn = get_db()
    tenant = conn.execute(
        'SELECT * FROM tenants WHERE id = ?', (str(tenant_id),)).fetchone()
    if tenant is None:
        raise ValueError('Tenant not found')
    package = None
    if package_id:
        package = conn.execute(
            'SELECT * FROM billing_packages WHERE id = ?', (str(package_id),)).fetchone()
        if package is None:
            raise ValueError('Package not found')
        package = dict(package)
    try:
        conn.execute('UPDATE tenants SET package_id = ? WHERE id = ?',
                     (str(package_id) if package_id else None, str(tenant_id)))
        conn.commit()
    except Exception:
        pass
    if package is not None:
        try:
            conn.execute(
                'INSERT INTO tenant_package_history '
                '(id, tenant_id, package_id, package_name, credit_usd, credit_sar) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (str(uuid.uuid4()), str(tenant_id), str(package.get('id')),
                 package.get('name'), float(package.get('credit_usd') or 0.0),
                 float(package.get('credit_sar') or 0.0))
            )
            conn.commit()
        except Exception as exc:
            print(f"[PACKAGES] history failed: {exc}")
    return dict(tenant), package


def get_client_overview(tenant_id):
    """Client card figures in raw USD: totals, current package, lifetime.

    Every spend row carries the package it burned under at write time, so
    per-package consumption is exact and never depends on clock comparisons.
    Remaining is floored at zero and the package reads expired exactly when
    nothing remains.
    """
    conn = get_db()
    tenant_id = str(tenant_id)
    counts = get_tenant_profile_counts(tenant_id)

    def _tagged_sum(table, package_id):
        try:
            cols = {row['name'] for row in conn.execute(
                f'PRAGMA table_info({table})').fetchall()}
        except Exception:
            cols = set()
        if 'package_id' not in cols:
            return None
        try:
            return float(dict(conn.execute(
                f'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM {table} '
                'WHERE tenant_id = ? AND package_id = ?',
                (tenant_id, str(package_id))).fetchone()).get('total') or 0.0)
        except Exception:
            return 0.0

    def _lifetime_sum(table):
        try:
            return float(dict(conn.execute(
                f'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM {table} WHERE tenant_id = ?',
                (tenant_id,)).fetchone()).get('total') or 0.0)
        except Exception:
            return 0.0

    lifetime = _lifetime_sum('ai_usage_events') + _lifetime_sum('map_usage_events')
    fx = _active_fx_rate()
    lifetime_sar = usd_to_sar(lifetime, fx)
    tenant = conn.execute(
        'SELECT package_id FROM tenants WHERE id = ?', (tenant_id,)).fetchone()
    package_id = dict(tenant).get('package_id') if tenant else None
    package = get_billing_package(package_id) if package_id else None
    cycle = _tenant_package_cycle(conn, tenant_id)
    assigned_at = cycle[2] if cycle else None
    block = None
    if package is not None:
        try:
            credit = float(package.get('credit_sar') if package.get('credit_sar') is not None
                           else usd_to_sar(package.get('credit_usd'), fx))
        except (TypeError, ValueError):
            credit = 0.0
        if cycle:
            # Entitlement comes from the assignment snapshot and consumption
            # counts only this cycle — a re-assignment starts clean and a
            # catalog edit never rewrites what was already granted.
            credit = cycle[1]
            consumed = usd_to_sar(_package_cycle_consumed(conn, tenant_id, cycle[0], cycle[2]), fx)
        else:
            ai_tagged = _tagged_sum('ai_usage_events', package.get('id'))
            maps_tagged = _tagged_sum('map_usage_events', package.get('id'))
            if ai_tagged is None or maps_tagged is None:
                consumed = lifetime_sar
            else:
                consumed = usd_to_sar(ai_tagged + maps_tagged, fx)
            if not package.get('is_active'):
                consumed = max(consumed, credit)
        remaining = max(0.0, credit - consumed)
        block = {
            'id': package.get('id'),
            'name': package.get('name'),
            'credit_sar': credit,
            'consumed_sar': consumed,
            'remaining_sar': remaining,
            'status': 'expired' if remaining <= 0 else 'active',
            'assigned_at': assigned_at,
        }
    return {
        'projects': int(counts.get('projects') or 0),
        'presentations': int(counts.get('presentations') or 0),
        'consumption_usd': lifetime,
        'consumption_sar': lifetime_sar,
        'package': block,
        'lifetime_consumed_usd': lifetime,
        'lifetime_consumed_sar': lifetime_sar,
    }


def get_fx_rate(pair=FX_PAIR_USD_SAR):
    """Current stored rate with source and age. Defaults without raising."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT rate, source, updated_at FROM fx_rates WHERE pair = ?',
            (str(pair),)).fetchone()
        if row:
            data = dict(row)
            return {'pair': str(pair), 'rate': float(data.get('rate') or 0) or FX_DEFAULT_USD_SAR,
                    'source': data.get('source') or 'auto', 'updated_at': data.get('updated_at')}
    except Exception:
        pass
    try:
        configured = float(os.environ.get('FX_USD_SAR') or 0)
        if configured > 0:
            return {'pair': str(pair), 'rate': configured, 'source': 'env', 'updated_at': None}
    except (TypeError, ValueError):
        pass
    return {'pair': str(pair), 'rate': FX_DEFAULT_USD_SAR, 'source': 'default',
            'updated_at': None}


def set_fx_rate(pair, rate, source='manual'):
    """Super-admin override (manual) or fetched value (auto)."""
    try:
        value = float(rate)
    except (TypeError, ValueError):
        raise ValueError('Invalid rate')
    if value <= 0:
        raise ValueError('Invalid rate')
    if source not in ('auto', 'manual'):
        source = 'manual'
    conn = get_db()
    conn.execute(
        'INSERT INTO fx_rates (pair, rate, source, updated_at) VALUES (?, ?, ?, ?) '
        'ON CONFLICT (pair) DO UPDATE SET rate = excluded.rate, source = excluded.source, '
        "updated_at = datetime('now')",
        (str(pair), value, source, _utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    return get_fx_rate(pair)


def usd_to_sar(amount_usd, rate=None):
    """Convert dollars to riyals for display, rounded to 2."""
    try:
        active = float(rate) if rate else float(get_fx_rate()['rate'])
    except (TypeError, ValueError):
        active = FX_DEFAULT_USD_SAR
    try:
        return round(float(amount_usd or 0.0) * active + 1e-9, 2)
    except (TypeError, ValueError):
        return 0.0


def sar_to_usd(amount_sar, rate=None):
    """Convert a riyal amount keyed by the desk back into wallet dollars."""
    try:
        active = float(rate) if rate else float(get_fx_rate()['rate'])
    except (TypeError, ValueError):
        active = FX_DEFAULT_USD_SAR
    if not active:
        active = FX_DEFAULT_USD_SAR
    return round(float(amount_sar) / active + 1e-9, 2)


def with_sar_fields(payload, rate=None):
    """Return a copy of ``payload`` where every ``*_usd`` numeric leaf gains a
    ``*_sar`` sibling converted at the active rate — nested dicts and lists
    included. Wallet figures are SAR-native; the *_usd twins that remain are
    provider-cost audit fields, so a *_sar sibling is never generated where
    one already exists.
    """
    try:
        active = float(rate) if rate else float(get_fx_rate().get('rate') or FX_DEFAULT_USD_SAR)
    except (TypeError, ValueError):
        active = FX_DEFAULT_USD_SAR

    def _convert(value):
        try:
            return round(float(value) * active + 1e-9, 2)
        except (TypeError, ValueError):
            return 0.0

    def _walk(node):
        if isinstance(node, list):
            return [_walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        out = {}
        for key, value in node.items():
            out[key] = _walk(value)
            if (isinstance(key, str) and key.endswith('_usd')
                    and isinstance(value, (int, float))
                    and (key[:-4] + '_sar') not in node):
                out[key[:-4] + '_sar'] = _convert(value)
        return out

    return _walk(payload)


# ── Platform settings (super-admin keyed configuration) ────────────────────

def get_platform_setting(key, default=None):
    """Read a platform-wide setting value (JSON-decoded when possible)."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT value FROM platform_settings WHERE key = ?', (str(key),)
        ).fetchone()
    except Exception:
        return default
    if not row:
        return default
    raw = dict(row).get('value')
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw if raw is not None else default


def set_platform_setting(key, value):
    """Store a platform-wide setting. Returns the stored value."""
    conn = get_db()
    conn.execute(
        "INSERT INTO platform_settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
        (str(key), json.dumps(value, ensure_ascii=False)),
    )
    conn.commit()
    return get_platform_setting(key)


def get_rejection_reasons():
    """Pre-written recharge rejection reasons the super admin maintains."""
    value = get_platform_setting('recharge_rejection_reasons', [])
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or '').strip()]


def save_rejection_reasons(reasons):
    """Replace the preset rejection-reason list (max 30 entries, 300 chars)."""
    clean = []
    for item in reasons or []:
        text = str(item or '').strip()[:300]
        if text and text not in clean:
            clean.append(text)
        if len(clean) >= 30:
            break
    return set_platform_setting('recharge_rejection_reasons', clean)
