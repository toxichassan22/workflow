def _tenant_provider_headroom_for_usage_ctx(usage_ctx):
    """Current provider-dollar entitlement for the tenant, or None if unknown."""
    tenant_id = _tenant_id_from_usage_ctx(usage_ctx)
    if not tenant_id:
        return None
    try:
        with _worker_app_context():
            tenant = db.get_tenant_by_id(tenant_id)
            if not tenant or tenant.get('is_admin'):
                return None
            return float(_tenant_provider_cap_usd(tenant_id))
    except Exception:
        return None


_TENANT_CREDIT_RECOVERY_READY_UNTIL = {}
_TENANT_CREDIT_RECOVERY_STATE_LOCK = threading.Lock()


def _repair_tenant_key_limit_after_refusal(usage_ctx):
    """Refresh a funded company's managed key once after a provider 402.

    Wallet changes sync the provider cap asynchronously. A generation can race
    that sync, so after a refusal this repairs the cap only when the current
    wallet/package entitlement can still cover the configured operation
    estimate. The caller retries the request at most once and only after the
    provider confirms the refreshed key has enough remaining limit. A brief
    ready window lets concurrent requests share one successful repair instead
    of issuing a burst of identical Management API updates.
    """
    tenant_id = _tenant_id_from_usage_ctx(usage_ctx)
    if not tenant_id or not _openrouter_management_key():
        return False
    if not isinstance(usage_ctx, dict):
        return False
    flow_key = str(usage_ctx.get('billing_flow') or '').strip()
    try:
        with _worker_app_context():
            estimate_usd = float(
                db.get_billing_flow_estimates().get(flow_key) or 0.0)
            if estimate_usd <= 0:
                return False
            tenant = db.get_tenant_by_id(tenant_id)
            if not tenant or tenant.get('is_admin'):
                return False
            meta = db.get_tenant_openrouter_key_meta(tenant_id)
            raw_key = db.get_tenant_openrouter_key_raw(tenant_id)
            if not raw_key or not meta.get('has_key') or not meta.get('is_active'):
                return False
            if _tenant_provider_cap_usd(tenant_id) < estimate_usd:
                return False
            with _balance_sync_lock(str(tenant_id)):
                live_status = _openrouter_key_status(raw_key)
                if not isinstance(live_status, dict) or live_status.get('error'):
                    return False
                remaining = live_status.get('limit_remaining')
                if remaining is None:
                    return False
                remaining = float(remaining)
                with _TENANT_CREDIT_RECOVERY_STATE_LOCK:
                    ready_until = _TENANT_CREDIT_RECOVERY_READY_UNTIL.get(
                        str(tenant_id), 0.0)
                if time.monotonic() <= ready_until:
                    return remaining >= estimate_usd
                if remaining >= estimate_usd:
                    return False
                synced = _sync_tenant_credit_to_openrouter(tenant_id)
            if not synced or synced.get('cap_sync_pending'):
                return False
            with _TENANT_CREDIT_RECOVERY_STATE_LOCK:
                _TENANT_CREDIT_RECOVERY_READY_UNTIL[str(tenant_id)] = (
                    time.monotonic() + 30.0)
            raw_key = db.get_tenant_openrouter_key_raw(tenant_id)
            if not raw_key:
                return False
            live_status = _openrouter_key_status(raw_key)
            if not isinstance(live_status, dict) or live_status.get('error'):
                return False
            remaining = live_status.get('limit_remaining')
            if remaining is None or float(remaining) < estimate_usd:
                return False
            return True
    except (TypeError, ValueError):
        return False
    except Exception as exc:
        print(f"[OPENROUTER KEYS] refusal recovery failed for {str(tenant_id)[:8]}: {exc}")
        return False
