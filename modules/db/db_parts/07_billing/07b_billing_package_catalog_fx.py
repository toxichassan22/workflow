# Billing package catalog and currency conversion.

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


def create_billing_package(name, credit_sar=0.0, price_sar=None, is_custom=True,
                           name_en=None, badge=None, badge_en=None,
                           tagline=None, tagline_en=None, is_featured=False,
                           duration_days=None, features=None):
    """Create a package. credit_sar may be zero (prepaid, topped up later).

    The wallet credit is riyal-denominated; ``credit_usd`` on the row keeps
    the dollar equivalent for provider-side audit only. ``name_en`` is the
    English catalog label; it is optional and the client falls back to the
    Arabic ``name`` when it is empty. ``badge``/``tagline`` (plus their
    ``*_en`` twins) dress the sales card — a pill above the name and a
    blurb line — and ``is_featured`` paints the card dark.
    """
    label = str(name or '').strip()
    if not label or len(label) > 120:
        raise ValueError('Invalid package name')
    label_en = str(name_en or '').strip()
    if len(label_en) > 120:
        raise ValueError('Invalid package name_en')
    badge_label = str(badge or '').strip()
    if len(badge_label) > 80:
        raise ValueError('Invalid package badge')
    badge_label_en = str(badge_en or '').strip()
    if len(badge_label_en) > 80:
        raise ValueError('Invalid package badge_en')
    tagline_label = str(tagline or '').strip()
    if len(tagline_label) > 200:
        raise ValueError('Invalid package tagline')
    tagline_label_en = str(tagline_en or '').strip()
    if len(tagline_label_en) > 200:
        raise ValueError('Invalid package tagline_en')
    try:
        credit = float(credit_sar or 0.0)
    except (TypeError, ValueError):
        raise ValueError('Invalid credit_sar')
    if credit < 0:
        raise ValueError('Invalid credit_sar')
    price = None
    if price_sar is not None:
        try:
            price = float(price_sar)
        except (TypeError, ValueError):
            raise ValueError('Invalid price_sar')
        if price < 0:
            raise ValueError('Invalid price_sar')
    conn = get_db()
    package_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO billing_packages (id, name, name_en, credit_usd, credit_sar, '
        'price_sar, badge, badge_en, tagline, tagline_en, is_featured, '
        'is_active, is_custom) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)',
        (package_id, label, label_en or None, sar_to_usd(credit), credit, price,
         badge_label or None, badge_label_en or None,
         tagline_label or None, tagline_label_en or None,
         1 if is_featured else 0, 1 if is_custom else 0)
    )
    conn.commit()
    if duration_days is not None or features is not None:
        set_package_terms(package_id, duration_days=duration_days,
                          features=features)
    return get_billing_package(package_id)


# ``_UNSET`` marks "leave alone" for update kwargs where None is a real value
# (a NULL duration means «بلا انتهاء», an empty list clears the features).
_PKG_TERMS_UNSET = object()


def update_billing_package(package_id, name=None, credit_sar=None, price_sar=None,
                           is_active=None, name_en=None, badge=None, badge_en=None,
                           tagline=None, tagline_en=None, is_featured=None,
                           duration_days=_PKG_TERMS_UNSET, features=_PKG_TERMS_UNSET):
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
    if name_en is not None:
        label_en = str(name_en or '').strip()
        if len(label_en) > 120:
            raise ValueError('Invalid package name_en')
        assignments.append('name_en = ?')
        params.append(label_en or None)
    if badge is not None:
        badge_label = str(badge or '').strip()
        if len(badge_label) > 80:
            raise ValueError('Invalid package badge')
        assignments.append('badge = ?')
        params.append(badge_label or None)
    if badge_en is not None:
        badge_label_en = str(badge_en or '').strip()
        if len(badge_label_en) > 80:
            raise ValueError('Invalid package badge_en')
        assignments.append('badge_en = ?')
        params.append(badge_label_en or None)
    if tagline is not None:
        tagline_label = str(tagline or '').strip()
        if len(tagline_label) > 200:
            raise ValueError('Invalid package tagline')
        assignments.append('tagline = ?')
        params.append(tagline_label or None)
    if tagline_en is not None:
        tagline_label_en = str(tagline_en or '').strip()
        if len(tagline_label_en) > 200:
            raise ValueError('Invalid package tagline_en')
        assignments.append('tagline_en = ?')
        params.append(tagline_label_en or None)
    if is_featured is not None:
        assignments.append('is_featured = ?')
        params.append(1 if is_featured else 0)
    if credit_sar is not None:
        try:
            credit = float(credit_sar)
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
            price = float(price_sar)
        except (TypeError, ValueError):
            raise ValueError('Invalid price_sar')
        if price < 0:
            raise ValueError('Invalid price_sar')
        assignments.append('price_sar = ?')
        params.append(price)
    if is_active is not None:
        assignments.append('is_active = ?')
        params.append(1 if is_active else 0)
    if assignments:
        assignments.append("updated_at = datetime('now')")
        params.append(str(package_id))
        conn.execute(
            'UPDATE billing_packages SET ' + ', '.join(assignments) + ' WHERE id = ?',
            tuple(params)
        )
        conn.commit()
    terms = {}
    if duration_days is not _PKG_TERMS_UNSET:
        terms['duration_days'] = duration_days
    if features is not _PKG_TERMS_UNSET:
        terms['features'] = features
    if terms:
        set_package_terms(package_id, **terms)
    return get_billing_package(package_id)


def set_package_terms(package_id, **terms):
    """Write the catalog terms the purchase screen shows onto the ACTIVE
    version row — ``duration_days`` (None clears to «بلا انتهاء») and the
    ``features`` list. Packages that predate the versions table get v1
    seeded from the package row so the join starts serving the terms."""
    conn = get_db()
    clean_dur = None
    if 'duration_days' in terms and terms['duration_days'] not in (None, ''):
        try:
            clean_dur = int(terms['duration_days'])
        except (TypeError, ValueError):
            raise ValueError('Invalid duration_days')
        if clean_dur < 0 or clean_dur > 36500:
            raise ValueError('Invalid duration_days')
    clean_feats = None
    if 'features' in terms:
        feats = terms['features']
        if feats is None:
            feats = []
        if not isinstance(feats, (list, tuple)):
            raise ValueError('Invalid features')
        clean_feats = [str(f).strip() for f in feats if str(f).strip()][:30]
    ver = conn.execute(
        'SELECT id FROM billing_package_versions WHERE package_id = ? AND is_active = 1 '
        'ORDER BY version DESC LIMIT 1', (str(package_id),)).fetchone()
    if ver is None:
        return create_package_version(
            package_id,
            duration_days=clean_dur if 'duration_days' in terms else None,
            features=clean_feats if 'features' in terms else None)
    sets = []
    params = []
    if 'duration_days' in terms:
        if clean_dur is None:
            sets.append('duration_days = NULL')
        else:
            sets.append('duration_days = ?')
            params.append(clean_dur)
    if 'features' in terms:
        sets.append('features_json = ?')
        params.append(json.dumps(clean_feats or [], ensure_ascii=False))
    if not sets:
        return get_billing_package(package_id)
    params.append(ver['id'])
    conn.execute('UPDATE billing_package_versions SET ' + ', '.join(sets) +
                 ' WHERE id = ?', tuple(params))
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
    """Convert dollars to riyals without reducing decimal precision."""
    try:
        active = float(rate) if rate else float(get_fx_rate()['rate'])
    except (TypeError, ValueError):
        active = FX_DEFAULT_USD_SAR
    try:
        return float(amount_usd or 0.0) * active
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
    return float(amount_sar) / active


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
            return float(value) * active
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


def get_package_tax_rate():
    """The desk-set «ضريبة» percentage for price-to-points conversion, as a
    fraction (0.15 = 15%). The stored platform setting wins; the
    ``TOPUP_TAX_RATE`` env default keeps installs working before the knob
    is first saved. The same rate feeds the receipt VAT breakdown."""
    raw = get_platform_setting('package_tax_rate')
    if raw is None or str(raw).strip() == '':
        return TAX_RATE_SAR
    try:
        return max(0.0, min(0.99, float(raw)))
    except (TypeError, ValueError):
        return TAX_RATE_SAR


def set_package_tax_rate_pct(pct):
    """Store the desk rate given as a percent (0–99). Returns the fraction."""
    try:
        value = float(pct)
    except (TypeError, ValueError):
        raise ValueError('Invalid tax rate')
    if not (0 <= value <= 99):
        raise ValueError('Invalid tax rate')
    fraction = value / 100.0
    set_platform_setting('package_tax_rate', fraction)
    return fraction


# ── Global package feature pool ─────────────────────────────────────────────
# The desk maintains one ordered list of features; every package then just
# marks which entries it includes. The client card renders the whole pool —
# included lines get the green mark, the rest the red one — so buyers compare
# tiers at a glance. Package rows store only the feature ids they include.

def get_package_feature_catalog():
    """The ordered feature pool: [{id, ar, en}]. Never raises."""
    items = get_platform_setting('package_feature_catalog', [])
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        iid = str(it.get('id') or '').strip()
        ar = str(it.get('ar') or '').strip()
        en = str(it.get('en') or '').strip()
        if iid and (ar or en):
            out.append({'id': iid, 'ar': ar or en, 'en': en})
    return out


def set_package_feature_catalog(items):
    """Replace the whole pool; order is preserved. Returns the clean list."""
    if not isinstance(items, list):
        raise ValueError('Invalid features')
    clean = []
    seen = set()
    for it in items[:100]:
        if not isinstance(it, dict):
            raise ValueError('Invalid features')
        iid = str(it.get('id') or '').strip()[:60]
        ar = str(it.get('ar') or '').strip()[:160]
        en = str(it.get('en') or '').strip()[:160]
        if not ar and not en:
            continue
        if not iid:
            iid = 'f' + uuid.uuid4().hex[:10]
        if iid in seen:
            raise ValueError('Duplicate feature id')
        seen.add(iid)
        clean.append({'id': iid, 'ar': ar or en, 'en': en})
    set_platform_setting('package_feature_catalog', clean)
    return clean


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
