
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Call the text/design model through OpenRouter
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _has_chat_choices(response):
    return (
        isinstance(response, dict)
        and 'error' not in response
        and isinstance(response.get('choices'), list)
        and bool(response['choices'])
    )


def _tenant_id_from_usage_ctx(usage_ctx):
    """Tenant id for key selection. Never raises, even outside a request."""
    try:
        if isinstance(usage_ctx, dict) and usage_ctx.get('tenant_id'):
            return usage_ctx.get('tenant_id')
    except Exception:
        pass
    try:
        return getattr(g, 'tenant_id', None)
    except Exception:
        return None


def _worker_app_context():
    """App context for threads that lack one; passthrough inside a request.

    Pool workers (competitor verification, slide generation) share no Flask
    context, so db helpers built on ``g`` die with 'Working outside of
    application context' — on staging that misread every keyed company as
    «no key row» and made auto-provisioning delete each key it created.
    Pushing only when absent keeps the caller's request-scoped ``g`` —
    tenant attribution included — intact, and the context's own teardown
    closes the connection it opened.
    """
    return contextlib.nullcontext() if has_app_context() else app.app_context()


def _resolve_openrouter_key(usage_ctx=None, tenant_id=None):
    """Provider key for one call: the company key first, global fallback after.

    Returns the raw bearer string or None. Never raises: metering and tests
    run outside requests too, and a missing key must surface as a normal
    provider error, not a 500.
    """
    tid = tenant_id
    if tid is None:
        tid = _tenant_id_from_usage_ctx(usage_ctx)
    if tid:
        with _worker_app_context():
            try:
                raw = db.get_tenant_openrouter_key_raw(tid)
                if raw:
                    return raw
            except Exception as exc:
                print(f"[OPENROUTER KEY] tenant lookup failed: {exc}")
    return OPENROUTER_KEY


def _openrouter_headers(usage_ctx=None, tenant_id=None, title='Real Estate Proposal Generator'):
    return {
        "Authorization": f"Bearer {_resolve_openrouter_key(usage_ctx, tenant_id)}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com",
        "X-Title": title,
    }


def _has_any_openrouter_key(usage_ctx=None, tenant_id=None):
    return bool(_resolve_openrouter_key(usage_ctx, tenant_id))


# Auto-provisioning is retried at most once per window per tenant — an
# unprovisionable company used to fire a Management-API create/delete pair on
# every gated call (the log showed ~40 attempts inside one market job).
_PROVISION_ATTEMPT_AT = {}
_PROVISION_RETRY_SECONDS = 300


def _tenant_key_gate(usage_ctx=None, tenant_id=None):
    """Strict-mode refusal for companies without an active key of their own.

    Returns None when the call may proceed, otherwise an error dict with
    NO_TENANT_KEY. Off unless REQUIRE_TENANT_OPENROUTER_KEY=1. Super-admin
    operations and unattributed internal calls always pass; the provider's
    own per-key limit remains the funding backstop. Never raises.
    """
    try:
        with _worker_app_context():
            if not REQUIRE_TENANT_OPENROUTER_KEY:
                return None
            tid = tenant_id
            if tid is None:
                tid = _tenant_id_from_usage_ctx(usage_ctx)
            if not tid:
                return None
            try:
                tenant = db.get_tenant_by_id(tid)
            except Exception:
                tenant = None
            if tenant and tenant.get('is_admin'):
                return None
            try:
                meta = db.get_tenant_openrouter_key_meta(tid)
                raw = db.get_tenant_openrouter_key_raw(tid)
            except Exception as exc:
                print(f"[OPENROUTER KEY] gate lookup failed: {exc}")
                # Strict mode exists to stop unkeyed companies spending on the
                # platform key — a lookup error that opens the gate defeats it.
                return {'message': 'تعذر التحقق من مفتاح AI للشركة الآن',
                        'error_code': 'TENANT_KEY_CHECK_FAILED'}
            if raw:
                return None
            # The refusal reason matters for support: no row, a deactivated row,
            # or a row whose secret no longer decrypts all look identical to the
            # caller but need different fixes.
            refusal_reason = ('no key row' if not (meta or {}).get('has_key')
                              else 'key row is inactive'
                              if not meta.get('is_active')
                              else 'stored key failed to decrypt')
            print(f"[OPENROUTER KEY] gate refused tenant {tid}: {refusal_reason}")
            # A management key is configured: try to provision one on the fly
            # instead of blocking the call. Rate-limited per tenant — a company
            # that cannot be provisioned would otherwise fire a create/delete pair
            # at the Management API on every gated call in a job.
            if _openrouter_management_key():
                now = time.time()
                if now - _PROVISION_ATTEMPT_AT.get(tid, 0) >= _PROVISION_RETRY_SECONDS:
                    _PROVISION_ATTEMPT_AT[tid] = now
                    print(f"[OPENROUTER KEY] auto-provisioning key for tenant {tid}")
                    try:
                        # Same cap as tenant creation: the wallet-derived
                        # provider limit — a funded company gets a usable key,
                        # not the static zero default that stays refused.
                        _ensure_tenant_openrouter_key(
                            tid, limit_usd=_tenant_provider_cap_usd(tid))
                    except Exception as exc:
                        print(f"[OPENROUTER KEY] auto-provision failed: {exc}")
                    try:
                        raw = db.get_tenant_openrouter_key_raw(tid)
                    except Exception:
                        raw = None
                    if raw:
                        _PROVISION_ATTEMPT_AT.pop(tid, None)
                        return None
            return {'message': 'لا يوجد مفتاح AI مفعل لهذه الشركة',
                    'error_code': 'NO_TENANT_KEY'}
    except Exception as exc:
        print(f"[OPENROUTER KEY] gate failed open: {exc}")
        return None


# ── Per-tenant managed keys (OpenRouter Management API) ────────────────
# One dashboard-visible key per company with its own spend limit. The
# management key never leaves the server; tenant secrets are stored
# encrypted and metadata reads never return them.

def _openrouter_management_key():
    return OPENROUTER_MANAGEMENT_KEY


def _openrouter_reset_for_provider(limit_reset):
    """Map a stored reset policy to the provider payload.

    OpenRouter accepts daily/weekly/monthly verbatim; our 'none' means a
    lifetime cap and must be sent as an explicit null — omitting the field
    on a PATCH would leave an old monthly reset in place.
    """
    value = str(limit_reset or '').strip().lower()
    if value in ('daily', 'weekly', 'monthly'):
        return value
    return None


def _openrouter_create_managed_key(name, limit_usd, limit_reset='none'):
    """Provision a dashboard-visible key. Returns the parsed JSON body."""
    mgmt = _openrouter_management_key()
    if not mgmt:
        return {'error': 'OPENROUTER_MANAGEMENT_KEY is not configured'}
    try:
        response = requests.post(
            f"{OPENROUTER_BASE}/keys",
            headers={"Authorization": f"Bearer {mgmt}", "Content-Type": "application/json"},
            json={"name": name, "limit": float(limit_usd),
                  "limit_reset": _openrouter_reset_for_provider(limit_reset)},
            timeout=30,
        )
    except Exception as exc:
        print(f"[OPENROUTER KEYS] create failed: {exc}")
        return {'error': str(exc) or type(exc).__name__}
    try:
        body = response.json()
    except Exception:
        body = {}
    if response.status_code >= 400:
        err = (body.get('error') if isinstance(body, dict) else None) or f'HTTP {response.status_code}'
        print(f"[OPENROUTER KEYS] create refused: {err}")
        return {'error': str(err) if not isinstance(err, dict) else json.dumps(err, ensure_ascii=False)}
    data = body.get('data') if isinstance(body, dict) else None
    res = {}
    if isinstance(data, dict):
        res.update(data)
    if isinstance(body, dict):
        for k, v in body.items():
            if k != 'data':
                res[k] = v
    if res.get('key'):
        return res
    if isinstance(data, dict) and data.get('key'):
        return data
    if isinstance(body, dict) and body.get('key'):
        return body
    try:
        if isinstance(body, dict):
            shape = 'keys=' + ','.join(sorted(str(k) for k in body.keys())[:20])
        else:
            shape = 'type=' + type(body).__name__
    except Exception:
        shape = 'unknown'
    print(f"[OPENROUTER KEYS] create returned HTTP {response.status_code} without a key ({shape})")
    return {'error': f'Provider returned HTTP {response.status_code} without a key'}


def _openrouter_update_managed_key(key_hash, limit_usd=None, limit_reset=None, disabled=None):
    """Best-effort limit/disable sync to the dashboard. Never raises."""
    mgmt = _openrouter_management_key()
    if not mgmt or not key_hash:
        return {'skipped': True}
    payload = {}
    if limit_usd is not None:
        try:
            payload['limit'] = float(limit_usd)
        except (TypeError, ValueError):
            pass
    if limit_reset is not None:
        payload['limit_reset'] = _openrouter_reset_for_provider(limit_reset)
    if disabled is not None:
        payload['disabled'] = bool(disabled)
    if not payload:
        return {'skipped': True}
    try:
        response = requests.patch(
            f"{OPENROUTER_BASE}/keys/{key_hash}",
            headers={"Authorization": f"Bearer {mgmt}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if response.status_code >= 400:
            print(f"[OPENROUTER KEYS] patch refused for {str(key_hash)[:8]}: {response.status_code} - {response.text}")
            return {'ok': False, 'status': response.status_code, 'error': response.text}
        return {'ok': True}
    except Exception as exc:
        print(f"[OPENROUTER KEYS] patch failed: {exc}")
        return {'ok': False, 'error': str(exc)}


def _openrouter_delete_managed_key(key_hash):
    """Best-effort dashboard delete. Never raises."""
    mgmt = _openrouter_management_key()
    if not mgmt or not key_hash:
        return {'skipped': True}
    try:
        response = requests.delete(
            f"{OPENROUTER_BASE}/keys/{key_hash}",
            headers={"Authorization": f"Bearer {mgmt}"},
            timeout=30,
        )
        if response.status_code >= 400:
            print(f"[OPENROUTER KEYS] delete refused for {str(key_hash)[:8]}: {response.status_code}")
            return {'ok': False, 'status': response.status_code}
        return {'ok': True}
    except Exception as exc:
        print(f"[OPENROUTER KEYS] delete failed: {exc}")
        return {'ok': False, 'error': str(exc)}


def _openrouter_key_status(api_key, timeout=20):
    """Validate a key and read its limit/usage. Returns dict or {'error': ...}."""
    try:
        response = requests.get(
            f"{OPENROUTER_BASE}/key",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
    except Exception as exc:
        return {'error': str(exc)}
    try:
        body = response.json()
    except Exception:
        return {'error': f'HTTP {response.status_code}'}
    if response.status_code >= 400:
        err = (body.get('error') if isinstance(body, dict) else None) or f'HTTP {response.status_code}'
        return {'error': str(err) if not isinstance(err, dict) else json.dumps(err, ensure_ascii=False)}
    data = body.get('data') if isinstance(body, dict) else None
    return data if isinstance(data, dict) else {}


def _openrouter_list_managed_keys(limit_pages=100):
    """Every dashboard key (paginated). Returns list or {'error': ...}."""
    mgmt = _openrouter_management_key()
    if not mgmt:
        return {'error': 'OPENROUTER_MANAGEMENT_KEY is not configured'}
    items = []
    try:
        offset = 0
        for _page in range(max(1, int(limit_pages or 1))):
            response = requests.get(
                f"{OPENROUTER_BASE}/keys",
                headers={"Authorization": f"Bearer {mgmt}"},
                params={'offset': offset},
                timeout=30,
            )
            try:
                body = response.json()
            except Exception:
                body = {}
            if response.status_code >= 400:
                err = (body.get('error') if isinstance(body, dict) else None) or f'HTTP {response.status_code}'
                return {'error': str(err) if not isinstance(err, dict) else json.dumps(err, ensure_ascii=False)}
            data = (body.get('data') if isinstance(body, dict) else None) or []
            if not isinstance(data, list) or not data:
                break
            items.extend(item for item in data if isinstance(item, dict))
            if len(data) < 100:
                break
            offset += len(data)
        return items
    except Exception as exc:
        print(f"[OPENROUTER KEYS] list failed: {exc}")
        return {'error': str(exc)}


def _managed_orphan_keys():
    """Dashboard keys no company row references. Returns (orphans, error)."""
    listed = _openrouter_list_managed_keys()
    if isinstance(listed, dict) and listed.get('error'):
        return None, listed.get('error')
    try:
        conn = db.get_db()
        known = set()
        live_labels = set()
        for record in conn.execute(
                'SELECT openrouter_key_hash, key_label, is_active '
                'FROM tenant_openrouter_keys').fetchall():
            try:
                record = dict(record)
            except Exception:
                continue
            if record.get('openrouter_key_hash'):
                known.add(str(record.get('openrouter_key_hash')))
            if record.get('is_active') and record.get('key_label'):
                live_labels.add(str(record.get('key_label')))
    except Exception:
        known = set()
        live_labels = set()
    orphans = []
    for item in listed:
        key_hash = item.get('hash')
        if not key_hash or key_hash in known:
            continue
        name = str(item.get('label') or item.get('name') or '')
        if not (name.startswith('landloom-') or name.startswith('tenant-')):
            continue
        if name in live_labels:
            continue
        orphans.append({
            'name': name,
            'hash': key_hash,
            'limit': item.get('limit'),
            'limit_reset': item.get('limit_reset'),
            'usage': item.get('usage'),
            'disabled': bool(item.get('disabled')),
        })
    return orphans, None


def _managed_key_honors_limit(raw_key, expected_limit):
    """Confirm the dashboard enforces the requested limit. Never raises.

    A zero-credit key must start blocked: an explicit 0 limit with nothing
    remaining. A null limit would mean unlimited spend and must never pass
    silently, so it fails closed with cleanup by the caller.
    """
    try:
        status = _openrouter_key_status(raw_key)
    except Exception as exc:
        print(f"[OPENROUTER KEYS] limit confirm failed: {exc}")
        return False, {}
    if not isinstance(status, dict) or status.get('error'):
        return False, status if isinstance(status, dict) else {}
    if expected_limit is not None and expected_limit <= 0:
        live_limit = status.get('limit')
        if live_limit is None:
            return False, status
        try:
            remaining = status.get('limit_remaining')
            ok = float(live_limit) <= 0 and (remaining is None or float(remaining) <= 0)
        except (TypeError, ValueError):
            ok = False
        return ok, status
    return True, status


def _provision_one_tenant_key(tenant, limit_usd, limit_reset):
    """Create, store and (for zero credit) verify one managed key.

    Returns (meta, error): exactly one is set. The raw secret is stored
    encrypted immediately and never logged. Anything that fails after the
    upstream key exists deletes it again, so a retry never leaves a second
    live key behind for the same company.
    """
    created = None
    tenant_id = tenant.get('id') if isinstance(tenant, dict) else tenant
    # A re-provision replaces the stored row — remember the superseded
    # upstream key so the dashboard does not keep a live orphan.
    prior_hash = None
    try:
        prior_hash = (db.get_tenant_openrouter_key_meta(tenant_id) or {}).get('openrouter_key_hash')
    except Exception:
        prior_hash = None
    try:
        try:
            slug = (db.tenant_slug(tenant) if isinstance(tenant, dict) else '') or str(tenant_id)[:8]
        except Exception:
            slug = str(tenant_id)[:8]
        created = _openrouter_create_managed_key(f"landloom-{slug}", limit_usd, limit_reset)
        if not isinstance(created, dict) or not created.get('key'):
            reason = (created.get('error') if isinstance(created, dict) else None) or 'Provisioning failed'
            if not isinstance(reason, str):
                reason = str(reason)
            reason = reason.strip()
            if not reason or reason.lower() in ('none', 'null'):
                reason = 'Provisioning failed'
            created = None
            return None, reason
        try:
            meta = db.set_tenant_openrouter_key(
                tenant_id, created.get('key'),
                key_label=created.get('label') or created.get('name') or f"landloom-{slug}",
                limit_usd=(created.get('limit') if created.get('limit') is not None else limit_usd),
                limit_reset=created.get('limit_reset') or limit_reset,
                provenance='auto',
                openrouter_key_hash=created.get('hash'),
            )
        except Exception as store_exc:
            _openrouter_delete_managed_key(created.get('hash'))
            created = None
            return None, f"Local store failed, upstream key removed: {store_exc}"
        if (limit_usd or 0) <= 0:
            honored, _live = _managed_key_honors_limit(created.get('key'), 0)
            if not honored:
                _openrouter_delete_managed_key(created.get('hash'))
                created = None
                try:
                    db.deactivate_tenant_openrouter_key(tenant_id)
                except Exception:
                    pass
                return None, 'OpenRouter did not honor a zero limit; nothing was activated'
            try:
                live_hash = _live.get('hash') if isinstance(_live, dict) else None
                if live_hash and live_hash != meta.get('openrouter_key_hash'):
                    meta = db.update_tenant_openrouter_key_meta(
                        tenant_id, openrouter_key_hash=live_hash)
            except Exception:
                pass
        if prior_hash and prior_hash != created.get('hash'):
            try:
                _openrouter_delete_managed_key(prior_hash)
            except Exception as exc:
                print(f"[OPENROUTER KEYS] superseded key cleanup failed for {tenant_id}: {exc}")
        return meta, None
    except Exception as exc:
        print(f"[OPENROUTER KEYS] provision failed: {exc}")
        if created and isinstance(created, dict):
            _openrouter_delete_managed_key(created.get('hash'))
        msg = str(exc).strip()
        if not msg or msg.lower() in ('none', 'null'):
            msg = type(exc).__name__ or 'Provisioning failed'
        return None, msg


def _ensure_tenant_openrouter_key(tenant_id, limit_usd=None, limit_reset=None):
    """Auto-provision a managed key for a company. Best-effort, never raises.

    Skips super-admin accounts, tenants that already have a key, and setups
    without a management key. The new secret is stored encrypted immediately
    and never logged.
    """
    try:
        with _worker_app_context():
            if not tenant_id or not _openrouter_management_key():
                return None
            with _provision_lock(tenant_id):
                try:
                    tenant = db.get_tenant_by_id(tenant_id)
                except Exception:
                    tenant = None
                if tenant and tenant.get('is_admin'):
                    return None
                try:
                    existing = db.get_tenant_openrouter_key_meta(tenant_id)
                except Exception:
                    existing = {'has_key': False}
                if existing.get('has_key') and existing.get('is_active'):
                    return existing
                meta, _error = _provision_one_tenant_key(
                    tenant or {'id': tenant_id},
                    TENANT_OPENROUTER_DEFAULT_LIMIT_USD if limit_usd is None else limit_usd,
                    limit_reset or TENANT_OPENROUTER_DEFAULT_RESET,
                )
                if not meta:
                    # The refusal is the visible symptom; this is the cause — without
                    # it the gate log only ever says «no key row» forever.
                    print(f"[OPENROUTER KEYS] auto-provision failed for tenant {tenant_id}: "
                          f"{_error or 'unknown'}")
                return meta
    except Exception as exc:
        print(f"[OPENROUTER KEYS] auto-provision failed: {exc}")
        return None


def _find_managed_key_hash_for_tenant(tenant_id, tenant=None, existing_meta=None):
    """Find and cache the OpenRouter key hash for a tenant from the dashboard. Never raises."""
    if not tenant_id or not _openrouter_management_key():
        return None
    try:
        if tenant is None:
            tenant = db.get_tenant_by_id(tenant_id)
    except Exception:
        tenant = None
    if not tenant:
        return None
    try:
        if existing_meta is None:
            existing_meta = db.get_tenant_openrouter_key_meta(tenant_id)
    except Exception:
        existing_meta = {}

    slug = db.tenant_slug(tenant)
    candidate_names = set()
    if slug:
        candidate_names.add(f"landloom-{slug}")
    if tenant.get('username'):
        u_slug = db._normalize_slug(tenant.get('username'))
        if u_slug:
            candidate_names.add(f"landloom-{u_slug}")
    if existing_meta.get('key_label'):
        candidate_names.add(str(existing_meta.get('key_label')))

    keys = _openrouter_list_managed_keys()
    if not isinstance(keys, list):
        return None

    raw_key = None
    try:
        raw_key = db.get_tenant_openrouter_key_raw(tenant_id)
    except Exception:
        pass

    matched_hash = None
    for item in keys:
        if not isinstance(item, dict):
            continue
        h = item.get('hash')
        if not h:
            continue
        name = str(item.get('name') or item.get('label') or '')
        if name in candidate_names:
            matched_hash = h
            break
        if raw_key and len(raw_key) >= 8:
            lbl = str(item.get('label') or '')
            if lbl.endswith(raw_key[-4:]) or (len(raw_key) >= 12 and raw_key[-8:] in lbl):
                matched_hash = h
                break

    if matched_hash:
        try:
            db.update_tenant_openrouter_key_meta(tenant_id, openrouter_key_hash=matched_hash)
        except Exception:
            pass
    return matched_hash


def _tenant_provider_cap_usd(tenant_id):
    """Raw provider dollars the tenant may still burn on its own key.

    The wallet is billed in riyals (raw provider cost x rate x
    BILLING_MULTIPLIER at checkout, or flat reservation fees), so the
    provider-side cap converts the remaining entitlement back:
    (free balance + live holds) / rate / multiplier. Holds count because an
    approved run already paid for its spend. Package credit adds after the
    multiplier: it is consumed at raw provider cost, so its riyal figure maps
    back through the rate alone. This keeps every future checkout bill
    affordable by construction.
    """
    try:
        balance = db.get_tenant_balance(tenant_id)
    except Exception:
        balance = 0.0
    try:
        holds = db.get_active_hold_total_sar(tenant_id)
    except Exception:
        holds = 0.0
    try:
        package_remaining = db.get_package_remaining_sar(tenant_id)
    except Exception:
        package_remaining = 0.0
    try:
        multiplier = float(db.get_billing_multiplier() or 0.0)
    except (TypeError, ValueError):
        multiplier = 0.0
    if multiplier <= 0:
        multiplier = 1.0
    try:
        fx_rate = float((db.get_fx_rate() or {}).get('rate') or db.FX_DEFAULT_USD_SAR)
    except (TypeError, ValueError):
        fx_rate = db.FX_DEFAULT_USD_SAR
    if fx_rate <= 0:
        fx_rate = db.FX_DEFAULT_USD_SAR
    wallet_raw = (float(balance or 0.0) + float(holds or 0.0)) / fx_rate / multiplier
    return max(0.0, wallet_raw + float(package_remaining or 0.0) / fx_rate)


def _openrouter_key_usage_usd(tenant_id):
    """Accumulated provider-side spend on the company's key, or None when the
    live read fails. ``limit`` on a managed key is a cumulative cap on
    ``usage``, so a PATCH that wants N more dollars must send usage + N."""
    try:
        raw = db.get_tenant_openrouter_key_raw(tenant_id)
    except Exception:
        raw = None
    if not raw:
        return None
    status = _openrouter_key_status(raw)
    if not isinstance(status, dict) or status.get('error'):
        return None
    try:
        return max(0.0, float(status.get('usage') or 0.0))
    except (TypeError, ValueError):
        return None


def _sync_tenant_credit_to_openrouter(tenant_id, new_limit_usd=None):
    """Sync a tenant's spend cap to its OpenRouter key (best-effort). Never raises.

    ``new_limit_usd`` is the raw provider cap; None recomputes it from the
    current wallet (balance + holds) / multiplier. The reset policy is
    always pushed too, so an older monthly-resetting key is normalized to
    the configured default — renewal stays a manual super-admin act.
    """
    if not tenant_id:
        return None
    try:
        tenant = db.get_tenant_by_id(tenant_id)
        if tenant and tenant.get('is_admin'):
            return None
    except Exception:
        tenant = None
    try:
        if new_limit_usd is None:
            new_limit = _tenant_provider_cap_usd(tenant_id)
        else:
            new_limit = max(0.0, float(new_limit_usd))
    except (TypeError, ValueError):
        return None
    reset_policy = TENANT_OPENROUTER_DEFAULT_RESET
    try:
        existing = db.get_tenant_openrouter_key_meta(tenant_id)
        if existing and existing.get('has_key'):
            db.update_tenant_openrouter_key_meta(
                tenant_id, limit_usd=new_limit, limit_reset=reset_policy)
            key_hash = existing.get('openrouter_key_hash')
            if not key_hash and existing.get('provenance') == 'auto':
                key_hash = _find_managed_key_hash_for_tenant(tenant_id, tenant=tenant, existing_meta=existing)
            if key_hash:
                # ISS-036: the provider's limit is a cumulative cap on usage,
                # not a remaining-budget field. Adding the burn already
                # recorded keeps limit_remaining equal to the wallet
                # entitlement; without it every sync shrunk the real
                # allowance by whatever the key had already spent.
                provider_usage = _openrouter_key_usage_usd(tenant_id)
                res = _openrouter_update_managed_key(
                    key_hash,
                    limit_usd=(provider_usage + new_limit) if provider_usage is not None else new_limit,
                    limit_reset=reset_policy,
                    # A drained wallet blocks the key; a funded one reopens
                    # it. An admin-disabled key (is_active=0) stays disabled.
                    disabled=(new_limit <= 0) if existing.get('is_active') else None,
                )
                if not res.get('ok') and not res.get('skipped'):
                    print(f"[OPENROUTER KEYS] update key limit returned {res}")
            return db.get_tenant_openrouter_key_meta(tenant_id)
        else:
            return _ensure_tenant_openrouter_key(
                tenant_id, limit_usd=new_limit, limit_reset=reset_policy)
    except Exception as exc:
        print(f"[OPENROUTER KEYS] sync credit to key failed for tenant {tenant_id}: {exc}")
        return None


_BALANCE_SYNC_LOCKS = {}
_BALANCE_SYNC_LOCKS_GUARD = threading.Lock()
_PROVISION_LOCKS = {}
_PROVISION_LOCKS_GUARD = threading.Lock()


def _balance_sync_lock(tenant_id):
    with _BALANCE_SYNC_LOCKS_GUARD:
        lock = _BALANCE_SYNC_LOCKS.get(tenant_id)
        if lock is None:
            lock = threading.Lock()
            _BALANCE_SYNC_LOCKS[tenant_id] = lock
        return lock


def _provision_lock(tenant_id):
    """Per-tenant provision serialization: two concurrent gate hits must not
    each create an upstream key — the loser's key would orphan on the
    dashboard. Cross-worker races can still happen under gunicorn; the
    superseded-hash cleanup in _provision_one_tenant_key covers those."""
    with _PROVISION_LOCKS_GUARD:
        lock = _PROVISION_LOCKS.get(str(tenant_id))
        if lock is None:
            lock = threading.Lock()
            _PROVISION_LOCKS[str(tenant_id)] = lock
        return lock


def _schedule_tenant_limit_sync(tenant_id):
    """db.BALANCE_CHANGE_HOOK entry point: re-sync the provider cap off the
    request path. Per-tenant serialization plus a fresh cap read inside the
    lock collapses rapid wallet movements onto the newest state instead of
    racing stale PATCHes upstream."""
    if not tenant_id or not _openrouter_management_key():
        return
    if app.config.get('TESTING'):
        return
    tenant_key = str(tenant_id)

    def _run():
        try:
            with app.app_context():
                with _balance_sync_lock(tenant_key):
                    _sync_tenant_credit_to_openrouter(tenant_key)
        except Exception as exc:
            print(f"[BILLING] provider-cap sync failed for {tenant_key}: {exc}")

    try:
        threading.Thread(target=_run, daemon=True,
                         name=f'cap-sync-{tenant_key[:8]}').start()
    except Exception as exc:
        print(f"[BILLING] provider-cap sync spawn failed: {exc}")


# Wallet figures are riyals — the spend floor is a SAR amount (≈$10).
LOW_BALANCE_NOTIFY_SAR = float(os.environ.get('LOW_BALANCE_NOTIFY_SAR') or 37.5)


def _maybe_notify_low_balance(tenant_id):
    """Once-a-day ping to the billing audience when the wallet drops under
    the spend floor — every debit path funnels through the balance hook, so
    this catches automatic and manual spend alike without spamming."""
    try:
        balance = db.get_tenant_balance(tenant_id)
        if balance is None or float(balance) >= LOW_BALANCE_NOTIFY_SAR:
            return
        if db.recent_notification_exists(tenant_id, 'wallet', 'low-balance', since_hours=24):
            return
        _notify_tenant_billing(
            tenant_id, 'رصيد المحفظة منخفض',
            f'الرصيد الحالي {float(balance):.2f} ريال',
            entity_type='wallet', entity_id='low-balance')
    except Exception as exc:
        print(f'[NOTIFY] low-balance check failed for {tenant_id}: {exc}')


def _on_balance_changed(tenant_id):
    _schedule_tenant_limit_sync(tenant_id)
    _maybe_notify_low_balance(tenant_id)


db.BALANCE_CHANGE_HOOK = _on_balance_changed


def call_openrouter_chat(system_prompt, user_content,     temperature=0.7, max_tokens=8000, model=None, timeout=300, reasoning_effort=None, response_format=None, provider=None, image_references=None, tools=None, plugins=None, max_tool_calls=None, usage_ctx=None):
    gate = _tenant_key_gate(usage_ctx)
    if gate is not None:
        return {"error": gate}
    if not _has_any_openrouter_key(usage_ctx):
        return {"error": {"message": "OPENROUTER_KEY is missing"}}
    model_name = model or GLM_OPENROUTER_MODEL
    headers = _openrouter_headers(usage_ctx)
    user_message_content = user_content
    if image_references:
        user_message_content = [{"type": "text", "text": str(user_content)}]
        for image_reference in image_references:
            if isinstance(image_reference, dict):
                image_url = image_reference.get('data_uri') or image_reference.get('url')
            else:
                image_url = image_reference
            if isinstance(image_url, str) and image_url.startswith('data:image/'):
                user_message_content.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message_content}
        ],
        "max_tokens": max_tokens
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if response_format:
        payload["response_format"] = response_format
    if provider:
        payload["provider"] = provider
    if tools:
        payload["tools"] = tools
    if plugins:
        payload["plugins"] = plugins
    if max_tool_calls:
        payload["max_tool_calls"] = max_tool_calls
    attempt_id = _begin_ai_attempt_record(usage_ctx, model_name)
    try:
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=timeout)
        response.encoding = 'utf-8'
        text = response.text or ''
        if not text.strip():
            print(f"[OPENROUTER EMPTY BODY] status={response.status_code} model={model_name} cap={max_tokens}")
            _settle_ai_attempt_record(attempt_id, 'error', {}, None)
            return {"error": {"message": f"مزوّد الذكاء الاصطناعي رد بجسم فارغ (HTTP {response.status_code})"}}
        try:
            data = response.json()
        except Exception as json_err:
            print(f"[OPENROUTER UNPARSEABLE] status={response.status_code} model={model_name} json_err={json_err} body={text[:200]!r}")
            _settle_ai_attempt_record(attempt_id, 'error', {}, None)
            return {"error": {"message": f"استجابة المزوّد ليست JSON صالحًا (HTTP {response.status_code})"}}
        if response.status_code >= 400:
            error = data.get('error', {}) if isinstance(data, dict) else data
            print(f"[OPENROUTER HTTP ERROR] status={response.status_code} model={model_name} error={error}")
            generation_id, error_usage = _extract_openrouter_usage(data)
            _settle_ai_attempt_record(attempt_id, 'error', error_usage, generation_id)
            if isinstance(error, dict) and 'message' in error:
                error['message'] = f"[{response.status_code}] {error['message']}"
                return {"error": error}
            return {"error": error if isinstance(error, dict) else {"message": f"[{response.status_code}] {error}"}}
        generation_id, usage = _extract_openrouter_usage(data)
        _settle_ai_attempt_record(attempt_id, 'ok', usage, generation_id)
        return data
    except requests.exceptions.Timeout:
        print(f"[OPENROUTER TIMEOUT] model={model_name} cap={max_tokens} timeout={timeout}")
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
        return {"error": {"message": f"انتهت مهلة الاتصال بالمزوّد ({timeout} ثانية)"}}
    except requests.exceptions.ConnectionError as exc:
        print(f"[OPENROUTER CONNECTION] model={model_name} {exc}")
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
        return {"error": {"message": "انقطع الاتصال بالمزوّد قبل اكتمال الطلب"}}
    except Exception as exc:
        print(f"[OPENROUTER EXCEPTION] model={model_name} {exc}")
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
        return {"error": {"message": str(exc)}}


def call_zai_chat(system_prompt, user_content, temperature=0.7, max_tokens=8000, timeout=300,
                  reasoning_effort=None, response_format=None, model=None, image_references=None, usage_ctx=None):
    """Compatibility wrapper: text/design work uses configured models through OpenRouter."""
    if not _has_any_openrouter_key(usage_ctx):
        return {"error": {"message": "OPENROUTER_KEY is required for the text model"}}
    return call_openrouter_chat(
        system_prompt,
        user_content,
        temperature=None,
        max_tokens=max_tokens,
        model=model or LUNA_TEXT_MODEL,
        timeout=timeout,
        reasoning_effort=reasoning_effort,
        response_format=response_format,
        image_references=image_references,
        usage_ctx=usage_ctx,
    )


def call_zai_chat_parallel(system_prompt, user_content, temperature=0.7, max_tokens=8000, attempts=2, timeout=300, model=None, image_references=None, usage_ctx=None):
    """
    Race multiple identical GLM calls in parallel and return the first valid response.
    Helps when a single model invocation is slow or returns malformed/empty content.
    Every attempt is metered separately: the provider bills each one.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _attempt():
        try:
            resp = call_zai_chat(system_prompt, user_content, temperature, max_tokens, timeout=timeout, model=model, image_references=image_references, usage_ctx=usage_ctx)
            if not _has_chat_choices(resp):
                return None
            content = extract_chat_content(resp, 'GLM-PARALLEL')
            return resp if content.strip() else None
        except Exception as e:
            print(f"[GLM PARALLEL] attempt failed: {e}")
            return None

    executor = ThreadPoolExecutor(max_workers=max(1, attempts))
    futures = [executor.submit(_attempt) for _ in range(max(1, attempts))]
    try:
        for future in as_completed(futures):
            result = future.result()
            if result:
                for pending in futures:
                    pending.cancel()
                print(f"[GLM PARALLEL] Valid response received after racing {attempts} calls")
                return result
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    raise Exception(f"All {attempts} parallel GLM attempts failed")


def call_openrouter_chat_stream(system_prompt, user_content, temperature=0.7, max_tokens=8000, model=None, timeout=300, reasoning_effort=None, response_format=None, provider=None, image_references=None, tools=None, plugins=None, usage_ctx=None, on_token=None, read_timeout=60):
    """Streaming twin of call_openrouter_chat: identical request, tokens via on_token.

    The payload carries the same model, messages and limits with stream mode on,
    so the provider generates the same completion it would for the non-stream
    call. Deltas are concatenated and returned in the same choices shape, so
    callers that read response['choices'][0]['message']['content'] work
    unchanged, and metering settles exactly once from the stream's usage chunk
    (falling back to an empty usage record exactly like the non-stream error
    paths when the provider sends none). Transport and HTTP failures return the
    same {"error": ...} shape; only on_token is new, and it must never raise.
    """
    import time as _time
    gate = _tenant_key_gate(usage_ctx)
    if gate is not None:
        return {"error": gate}
    if not _has_any_openrouter_key(usage_ctx):
        return {"error": {"message": "OPENROUTER_KEY is missing"}}
    model_name = model or GLM_OPENROUTER_MODEL
    headers = _openrouter_headers(usage_ctx)
    user_message_content = user_content
    if image_references:
        user_message_content = [{"type": "text", "text": str(user_content)}]
        for image_reference in image_references:
            if isinstance(image_reference, dict):
                image_url = image_reference.get('data_uri') or image_reference.get('url')
            else:
                image_url = image_reference
            if isinstance(image_url, str) and image_url.startswith('data:image/'):
                user_message_content.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message_content}
        ],
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "usage": {"include": True},
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if response_format:
        payload["response_format"] = response_format
    if provider:
        payload["provider"] = provider
    if tools:
        payload["tools"] = tools
    if plugins:
        payload["plugins"] = plugins
    attempt_id = _begin_ai_attempt_record(usage_ctx, model_name)

    def _fail(message):
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
        return {"error": {"message": message}}

    def _delta_text(delta, *keys):
        for key in keys:
            piece = delta.get(key)
            if isinstance(piece, list):
                piece = ' '.join(
                    part.get('text', '') if isinstance(part, dict) else str(part)
                    for part in piece
                )
            if piece:
                return str(piece)
        return ''

    start = _time.monotonic()
    try:
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=(15, read_timeout), stream=True)
        response.encoding = 'utf-8'
    except requests.exceptions.Timeout:
        print(f"[OPENROUTER STREAM TIMEOUT] model={model_name} cap={max_tokens}")
        return _fail(f"انتهت مهلة الاتصال بالمزوّد ({timeout} ثانية)")
    except requests.exceptions.ConnectionError as exc:
        print(f"[OPENROUTER STREAM CONNECTION] model={model_name} {exc}")
        return _fail("انقطع الاتصال بالمزوّد قبل اكتمال الطلب")
    except Exception as exc:
        print(f"[OPENROUTER STREAM EXCEPTION] model={model_name} {exc}")
        return _fail(str(exc))
    if response.status_code >= 400:
        try:
            data = response.json()
        except Exception:
            data = {}
        try:
            response.close()
        except Exception:
            pass
        error = data.get('error', {}) if isinstance(data, dict) else data
        print(f"[OPENROUTER STREAM HTTP ERROR] status={response.status_code} model={model_name} error={error}")
        _settle_ai_attempt_record(attempt_id, 'error', {}, None)
        if isinstance(error, dict) and 'message' in error:
            error['message'] = f"[{response.status_code}] {error['message']}"
            return {"error": error}
        return {"error": error if isinstance(error, dict) else {"message": f"[{response.status_code}] {error}"}}
    content_parts = []
    reasoning_parts = []
    generation_id = None
    usage = {}
    try:
        for line in response.iter_lines(decode_unicode=True):
            if _time.monotonic() - start > timeout:
                try:
                    response.close()
                except Exception:
                    pass
                return _fail(f"انتهت مهلة الاتصال بالمزوّد ({timeout} ثانية)")
            if not line:
                continue
            text = line.strip()
            if not text.startswith('data:'):
                continue
            text = text[5:].strip()
            if text == '[DONE]':
                break
            try:
                chunk = json.loads(text)
            except Exception:
                continue
            if not isinstance(chunk, dict):
                continue
            if generation_id is None and isinstance(chunk.get('id'), str) and chunk.get('id'):
                generation_id = chunk.get('id')
            if isinstance(chunk.get('usage'), dict):
                usage = chunk.get('usage')
            choices = chunk.get('choices')
            choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
            delta = choice.get('delta')
            if not isinstance(delta, dict):
                continue
            piece = _delta_text(delta, 'content')
            if piece:
                content_parts.append(piece)
            else:
                for key in ('reasoning_content', 'reasoning', 'reasoning_details'):
                    rpiece = _delta_text(delta, key)
                    if rpiece:
                        reasoning_parts.append(rpiece)
                        break
            if on_token and content_parts:
                try:
                    on_token(''.join(content_parts))
                except Exception:
                    pass
        try:
            response.close()
        except Exception:
            pass
    except requests.exceptions.Timeout:
        print(f"[OPENROUTER STREAM STALL] model={model_name} cap={max_tokens}")
        return _fail(f"انتهت مهلة الاتصال بالمزوّد ({timeout} ثانية)")
    except requests.exceptions.ConnectionError as exc:
        print(f"[OPENROUTER STREAM CONNECTION] model={model_name} {exc}")
        return _fail("انقطع الاتصال بالمزوّد قبل اكتمال الطلب")
    except Exception as exc:
        print(f"[OPENROUTER STREAM EXCEPTION] model={model_name} {exc}")
        return _fail(str(exc))
    final_text = ''.join(content_parts)
    if not final_text.strip() and reasoning_parts:
        final_text = ''.join(reasoning_parts)
    _, settled_usage = _extract_openrouter_usage({'id': generation_id, 'usage': usage})
    _settle_ai_attempt_record(attempt_id, 'ok', settled_usage, generation_id)
    return {"choices": [{"message": {"content": final_text}}], "usage": usage, "id": generation_id}


def call_zai_chat_stream(system_prompt, user_content, temperature=0.7, max_tokens=8000, timeout=300, reasoning_effort=None, response_format=None, model=None, image_references=None, usage_ctx=None, on_token=None):
    """Streaming twin of call_zai_chat: same defaults, tokens via on_token."""
    if not _has_any_openrouter_key(usage_ctx):
        return {"error": {"message": "OPENROUTER_KEY is required for the text model"}}
    return call_openrouter_chat_stream(
        system_prompt,
        user_content,
        temperature=None,
        max_tokens=max_tokens,
        model=model or LUNA_TEXT_MODEL,
        timeout=timeout,
        reasoning_effort=reasoning_effort,
        response_format=response_format,
        image_references=image_references,
        usage_ctx=usage_ctx,
        on_token=on_token,
    )


def _slide_stream_progress(tenant_id, job_id, interval=1.0):
    """Throttle live slide previews: at most one job-file publish per interval.

    The callback only ever writes the in-progress text; the completed job body
    keeps today's shape, so clients that ignore unknown keys see no change.
    """
    import time as _time
    state = {'last': 0.0}

    def _on_token(full_text):
        now = _time.monotonic()
        if now - state['last'] < interval:
            return
        state['last'] = now
        try:
            _write_job('.slide_jobs', tenant_id, job_id, {
                'status': 'running',
                'success': True,
                'message': 'جاري توليد الشريحة...',
                'partial': full_text,
            })
        except Exception as exc:
            print(f'[SLIDE STREAM] partial write failed: {exc}')

    return _on_token
