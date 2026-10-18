

# ─────────────────────────────────────────────────────────────────────────────
# Billing ledger (tenant wallet debits backed by unbilled usage events)
# ─────────────────────────────────────────────────────────────────────────────

from numeric_precision import format_precise_number


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
            f'Insufficient balance: required {format_precise_number(self.required_sar, grouped=False)} SAR, '
            f'available {format_precise_number(self.available_sar, grouped=False)} SAR'
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
        return float(dict(row).get('total') or 0.0)
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
        billed_amount = raw_cost * fx_rate * active_multiplier
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
            (ledger_id, tenant_id, raw_cost * active_multiplier,
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
    amount = float(amount_sar or 0.0)
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
              'maps_deleted': 0, 'history_deleted': 0, 'ledger_deleted': 0,
              'reservations_deleted': 0}
    if clear_usage:
        for table, key in (('ai_usage_events', 'ai_deleted'),
                           ('map_usage_events', 'maps_deleted'),
                           ('tenant_package_history', 'history_deleted'),
                           ('tenant_ledger', 'ledger_deleted'),
                           ('point_reservations', 'reservations_deleted')):
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


def reset_tenant_balance(tenant_id, clear_usage=True):
    """Single-company fresh start — the per-tenant twin of
    ``reset_all_company_balances``: zero the wallet and unassign the
    package, optionally wiping that tenant's spend history so stale
    unbilled usage can never bill a future recharge. Super admins are
    never touched. Returns None for a missing tenant, {'skipped': ...}
    for an admin."""
    conn = get_db()
    row = conn.execute(
        'SELECT id, is_admin FROM tenants WHERE id = ?', (str(tenant_id),)).fetchone()
    if row is None:
        return None
    if dict(row).get('is_admin'):
        return {'skipped': 'admin'}
    tenant_id = str(tenant_id)
    conn.execute(
        'UPDATE tenants SET credit_balance = 0, package_id = NULL WHERE id = ?',
        (tenant_id,))
    result = {'tenants_reset': 1, 'ai_deleted': 0, 'maps_deleted': 0,
              'history_deleted': 0, 'ledger_deleted': 0,
              'reservations_deleted': 0}
    if clear_usage:
        # Live holds go with the wipe: a surviving 'reserved' row would keep
        # the provider cap nonzero and, worse, its expiry would refund money
        # into the wallet the operator just zeroed.
        for table, key in (('ai_usage_events', 'ai_deleted'),
                           ('map_usage_events', 'maps_deleted'),
                           ('tenant_package_history', 'history_deleted'),
                           ('tenant_ledger', 'ledger_deleted'),
                           ('point_reservations', 'reservations_deleted')):
            try:
                cur = conn.execute(
                    f'DELETE FROM {table} WHERE tenant_id = ?', (tenant_id,))
                result[key] = cur.rowcount or 0
            except Exception:
                pass
    conn.commit()
    _fire_balance_change(tenant_id)
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
        '''SELECT status,
                  COALESCE(SUM(CASE WHEN package_id IS NULL
                               THEN COALESCE(cost_sar, cost_usd) ELSE 0 END), 0) AS wallet_total,
                  COALESCE(SUM(CASE WHEN package_id IS NOT NULL
                               THEN COALESCE(cost_sar, cost_usd) ELSE 0 END), 0) AS package_total,
                  COUNT(*) AS n
           FROM point_reservations WHERE tenant_id = ? GROUP BY status''',
        (str(tenant_id),),
    ).fetchall()
    # Wallet figures stay wallet-funded only: a package escrow never moved
    # credit_balance, so it reports under its own key instead of inflating
    # the wallet buckets.
    buckets = {row['status']: {'sar': float(row['wallet_total'] or 0),
                               'package_sar': float(row['package_total'] or 0),
                               'count': int(row['n'])}
               for row in rows}
    reserved_sar = buckets.get('reserved', {}).get('sar', 0.0)
    expired_sar = buckets.get('expired', {}).get('sar', 0.0)
    total_sar = balance + reserved_sar
    return {
        'balance_sar': total_sar,
        'balance_points': total_sar * POINTS_PER_USD,
        'current_points': total_sar * POINTS_PER_USD,
        'reserved_sar': reserved_sar,
        'reserved_points': reserved_sar * POINTS_PER_USD,
        'available_sar': balance,
        'available_points': balance * POINTS_PER_USD,
        'expired_sar': expired_sar,
        'expired_points': expired_sar * POINTS_PER_USD,
        'consumed_sar': buckets.get('consumed', {}).get('sar', 0.0),
        'released_sar': buckets.get('released', {}).get('sar', 0.0),
        'package_reserved_sar': buckets.get('reserved', {}).get('package_sar', 0.0),
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
    amount = float(amount_sar or 0.0)
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
