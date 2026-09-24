

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI usage metering: per-call OpenRouter consumption, attributed per tenant,
# draft and presentation. Token figures are copied verbatim from the provider
# response. Dollar cost is resolved per generation id off the request path.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AI_USAGE_FLOWS = (
    'slide', 'slide_plan', 'designer_chat', 'training_chat', 'land', 'site',
    'market', 'executive', 'project_data', 'image', 'other',
)


def _usage_ctx(flow, data=None, draft_id=None, presentation_id=None, tenant_id=None):
    """Build the metering context for one AI call. Unknown ids stay None."""
    if isinstance(data, dict):
        project_data = data.get('projectData')
        if draft_id is None:
            draft_id = data.get('draftId') or data.get('draft_id')
            if draft_id is None and isinstance(project_data, dict):
                draft_id = project_data.get('draftId') or project_data.get('draft_id')
        if presentation_id is None:
            presentation_id = data.get('presentationId') or data.get('presentation_id')
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None
    return {
        'tenant_id': tenant_id,
        'draft_id': draft_id,
        'presentation_id': presentation_id,
        'flow': flow if flow in AI_USAGE_FLOWS else 'other',
    }


def _usage_ctx_optional(flow, data=None, draft_id=None, presentation_id=None):
    """Metering context for public endpoints that skip require_auth.

    Logged-in browsers still send their token, so the spend is attributed to
    the company without turning the endpoint into a 401 for anyone else.
    """
    try:
        from auth import get_optional_tenant_id
        tenant_id = get_optional_tenant_id()
    except Exception:
        tenant_id = None
    return _usage_ctx(flow, data, draft_id=draft_id, presentation_id=presentation_id,
                      tenant_id=tenant_id)


def _parse_openrouter_cost(value):
    """Validate one provider dollar figure. Unknown never becomes zero.

    Returns (cost_float_or_None, raw_text_or_None). Correct zero stays zero.
    Non-numeric, non-finite and negative figures return (None, None).
    """
    try:
        if value is None:
            return None, None
        if isinstance(value, bool):
            return None, None
        import math as _math
        if isinstance(value, float) and (not _math.isfinite(value)):
            return None, None
        text = str(value).strip()
        if not text:
            return None, None
        amount = Decimal(text)
        if not amount.is_finite():
            return None, None
        if amount < 0:
            return None, None
        return float(amount), text
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return None, None
    except Exception:
        return None, None


def _extract_openrouter_cost(data):
    """Read the billed amount from a chat response. Never estimates, never sums parts.

    OpenRouter defines usage.cost as the amount deducted for the request and
    /generation total_cost as the generation cost. Sub-detail fields are
    never added on top of that total.
    """
    try:
        if not isinstance(data, dict):
            return None, None
        usage = data.get('usage')
        if isinstance(usage, dict):
            for key in ('cost', 'total_cost'):
                if usage.get(key) is not None:
                    cost, raw = _parse_openrouter_cost(usage.get(key))
                    if cost is not None:
                        return cost, raw
        direct = data.get('cost')
        if direct is not None and not isinstance(direct, dict):
            cost, raw = _parse_openrouter_cost(direct)
            if cost is not None:
                return cost, raw
        return None, None
    except Exception:
        return None, None


def _extract_openrouter_usage(data):
    """Return (generation_id, usage_dict) copied from a provider response, never raising.

    usage_dict carries verbatim token counts plus cost_usd/cost_raw when the
    response itself states the billed amount. Missing or corrupt cost stays
    None so the attempt remains pending instead of a misleading zero.
    """
    try:
        if not isinstance(data, dict):
            return None, {}
        generation_id = data.get('id')
        if not isinstance(generation_id, str) or not generation_id:
            generation_id = None
        usage = data.get('usage')
        if not isinstance(usage, dict):
            cost, raw = _extract_openrouter_cost(data)
            out = {}
            if cost is not None:
                out['cost_usd'] = cost
                out['cost_raw'] = raw
            return generation_id, out

        def _num(value):
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        result = {
            'prompt_tokens': _num(usage.get('prompt_tokens')),
            'completion_tokens': _num(usage.get('completion_tokens')),
            'total_tokens': _num(usage.get('total_tokens')),
        }
        cost, raw = _parse_openrouter_cost(usage.get('cost'))
        if cost is None:
            cost, raw = _parse_openrouter_cost(usage.get('total_cost'))
        if cost is not None:
            result['cost_usd'] = cost
            result['cost_raw'] = raw
        return generation_id, result
    except Exception:
        return None, {}


def _resolve_ai_attempt_ctx(usage_ctx):
    try:
        ctx = dict(usage_ctx or {})
    except Exception:
        ctx = {}
    tenant_id = ctx.get('tenant_id')
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None
    flow = ctx.get('flow') or 'other'
    if flow not in AI_USAGE_FLOWS:
        flow = 'other'
    return tenant_id, flow, ctx.get('draft_id'), ctx.get('presentation_id')


def _begin_ai_attempt_record(usage_ctx, model):
    """Create the one row that owns a real provider attempt, before sending."""
    try:
        tenant_id, flow, draft_id, presentation_id = _resolve_ai_attempt_ctx(usage_ctx)
        with app.app_context():
            return db.begin_ai_usage_attempt(
                tenant_id, model or 'unknown', flow=flow,
                draft_id=draft_id, presentation_id=presentation_id)
    except Exception as exc:
        print(f"[AI-USAGE] begin attempt failed: {exc}")
        return None


def _settle_ai_attempt_record(event_id, status, usage, generation_id):
    """Settle the same row created before sending. Never inserts a second row."""
    if not event_id:
        return
    try:
        usage = dict(usage or {})
        cost = usage.get('cost_usd')
        raw = usage.get('cost_raw')
        coerced, parsed_raw = (None, None)
        if cost is not None:
            coerced, parsed_raw = _parse_openrouter_cost(cost)
        if raw is None:
            raw = parsed_raw
        if coerced is not None:
            attempt_status = 'settled'
            cost_source = 'response'
        elif generation_id:
            attempt_status = 'pending'
            cost_source = None
            coerced = None
        else:
            attempt_status = 'unresolved'
            cost_source = None
            coerced = None
        with app.app_context():
            db.update_ai_usage_attempt(
                event_id, status=status or 'ok',
                prompt_tokens=usage.get('prompt_tokens', 0),
                completion_tokens=usage.get('completion_tokens', 0),
                total_tokens=usage.get('total_tokens', 0),
                generation_id=generation_id,
                cost_usd=coerced, cost_source=cost_source, cost_raw=raw,
                response_cost_usd=coerced if cost_source == 'response' else None,
                attempt_status=attempt_status,
                clear_next_retry=(attempt_status == 'settled'),
            )
        if generation_id and (coerced is None or attempt_status == 'settled'):
            # Pending rows resolve off the request path as before. Rows settled
            # from the chat response carry a provisional figure, so they get
            # one delayed verification against /generation total_cost (usually
            # ready by then) instead of keeping a stale value forever.
            _backfill_ai_usage_cost_async(
                event_id, generation_id,
                delay_seconds=0 if coerced is None else 20)
    except Exception as exc:
        print(f"[AI-USAGE] settle attempt failed: {exc}")


def _record_ai_usage(usage_ctx, model, status='ok', usage=None, generation_id=None,
                     cost_usd=None, cost_source=None):
    """Persist one metered provider call. Never raises: metering must not break generation."""
    try:
        tenant_id, flow, draft_id, presentation_id = _resolve_ai_attempt_ctx(usage_ctx)
        usage = dict(usage or {})
        direct_cost = cost_usd if cost_usd is not None else usage.get('cost_usd')
        direct_raw = usage.get('cost_raw')
        coerced, parsed_raw = (None, None)
        if direct_cost is not None:
            coerced, parsed_raw = _parse_openrouter_cost(direct_cost)
        if direct_raw is None:
            direct_raw = parsed_raw
        source = cost_source if cost_source in ('response', 'generation', 'review') else None
        if coerced is not None and source is None:
            source = 'response'
        if coerced is None:
            source = None
        if source is None:
            direct_raw = None
        attempt_status = 'settled' if coerced is not None else ('pending' if generation_id else 'unresolved')
        with app.app_context():
            event_id = db.record_ai_usage_event(
                tenant_id, model or 'unknown',
                flow=flow, status=status,
                prompt_tokens=usage.get('prompt_tokens', 0),
                completion_tokens=usage.get('completion_tokens', 0),
                total_tokens=usage.get('total_tokens', 0),
                cost_usd=coerced, cost_raw=direct_raw, cost_source=source,
                response_cost_usd=coerced if source == 'response' else None,
                generation_cost_usd=coerced if source in ('generation', 'review') else None,
                attempt_status=attempt_status,
                draft_id=draft_id,
                presentation_id=presentation_id,
                generation_id=generation_id,
            )
        if generation_id and (coerced is None or source == 'response'):
            # Pending rows resolve off the request path as before. Rows settled
            # from the chat response carry a provisional figure, so they get
            # one delayed verification against /generation total_cost (usually
            # ready by then) instead of keeping a stale value forever.
            _backfill_ai_usage_cost_async(
                event_id, generation_id,
                delay_seconds=0 if coerced is None else 20)
        return event_id
    except Exception as exc:
        print(f"[AI-USAGE] record failed: {exc}")
        return None


def _query_openrouter_generation(generation_id, timeout=15):
    """Ask OpenRouter what one generation cost. Returns (cost, raw, outcome).

    outcome is one of ok, not_found, rate_limited, network, invalid,
    missing_key or bad_response. HTTP, payload shape and the echoed id are
    all checked before any figure is accepted.
    """
    try:
        lookup_key = OPENROUTER_KEY or _openrouter_management_key()
        if not lookup_key or not generation_id:
            return None, None, 'missing_key'
        response = requests.get(
            f"{OPENROUTER_BASE}/generation?id={generation_id}",
            headers={"Authorization": f"Bearer {lookup_key}"},
            timeout=timeout,
        )
        if response.status_code == 404:
            return None, None, 'not_found'
        if response.status_code == 429:
            return None, None, 'rate_limited'
        if response.status_code >= 400:
            return None, None, 'bad_response'
        try:
            payload = response.json()
        except Exception:
            return None, None, 'bad_response'
        data = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None, None, 'invalid'
        echoed = data.get('id')
        if isinstance(echoed, str) and echoed and echoed != generation_id:
            return None, None, 'invalid'
        cost, raw = _parse_openrouter_cost(data.get('total_cost'))
        if cost is None:
            return None, None, 'invalid'
        return cost, raw, 'ok'
    except requests.exceptions.Timeout:
        return None, None, 'network'
    except requests.exceptions.ConnectionError:
        return None, None, 'network'
    except Exception as exc:
        print(f"[AI-USAGE] cost lookup failed for {generation_id}: {exc}")
        return None, None, 'network'


def _fetch_openrouter_generation_cost(generation_id, timeout=15):
    """Ask OpenRouter what one generation actually cost. Returns dollars or None."""
    cost, _raw, _outcome = _query_openrouter_generation(generation_id, timeout=timeout)
    return cost


AI_RECONCILE_MAX_ATTEMPTS = int(os.environ.get('AI_RECONCILE_MAX_ATTEMPTS') or 6)
_AI_RECONCILE_LOCK = threading.Lock()
_AI_RECONCILE_IN_FLIGHT = set()


def _ai_reconcile_delay_seconds(attempts, outcome):
    try:
        base = int(attempts or 0)
    except (TypeError, ValueError):
        base = 0
    if outcome == 'rate_limited':
        delay = 600 * (base + 1)
    elif outcome == 'not_found':
        delay = 120 * (base + 1)
    else:
        delay = 120 * (2 ** min(max(base, 0), 4))
    return max(60, min(3600, int(delay)))


def _reconcile_single_ai_event(event_id, generation_id, timeout=15, is_review=False):
    """Resolve one attempt in place. Updates the row, never appends a cost row."""
    if not event_id or not generation_id:
        return {'ok': False, 'outcome': 'invalid'}
    with _AI_RECONCILE_LOCK:
        if event_id in _AI_RECONCILE_IN_FLIGHT:
            return {'ok': False, 'outcome': 'in_flight'}
        _AI_RECONCILE_IN_FLIGHT.add(event_id)
    try:
        try:
            claimed = db.claim_ai_usage_reconcile_row(event_id, delay_seconds=300)
        except Exception:
            claimed = True
        if not claimed:
            return {'ok': False, 'outcome': 'claimed'}
        cost, raw, outcome = _query_openrouter_generation(generation_id, timeout=timeout)
        try:
            current_rows = db.get_db().execute(
                'SELECT cost_usd, response_cost_usd, reconcile_attempts FROM ai_usage_events WHERE id = ?',
                (str(event_id),)).fetchall()
            current = dict(current_rows[0]) if current_rows else {}
        except Exception:
            current = {}
        attempts = 0
        try:
            attempts = int(current.get('reconcile_attempts') or 0)
        except (TypeError, ValueError):
            attempts = 0
        if outcome == 'ok' and cost is not None:
            # /generation total_cost is the source of truth: an automatic run
            # overwrites even a response-settled figure with it, while an
            # explicit review keeps the 'review' source for the audit trail.
            source = 'review' if is_review else 'generation'
            db.update_ai_usage_attempt(
                event_id, cost_usd=cost, cost_source=source, cost_raw=raw,
                generation_cost_usd=cost, attempt_status='settled',
                clear_next_retry=True)
            return {'ok': True, 'outcome': 'ok', 'cost_usd': cost, 'cost_source': source}
        if attempts + 1 >= AI_RECONCILE_MAX_ATTEMPTS:
            db.update_ai_usage_attempt(event_id, attempt_status='needs_review', clear_next_retry=True)
            return {'ok': False, 'outcome': outcome, 'needs_review': True}
        delay = _ai_reconcile_delay_seconds(attempts, outcome)
        try:
            from datetime import timedelta as _td
            nxt = (datetime.now(timezone.utc) + _td(seconds=delay)).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            nxt = None
        db.update_ai_usage_attempt(event_id, next_retry_at=nxt)
        return {'ok': False, 'outcome': outcome}
    finally:
        with _AI_RECONCILE_LOCK:
            _AI_RECONCILE_IN_FLIGHT.discard(event_id)


def _reconcile_ai_scope(limit=10, time_budget_seconds=8, tenant_id=None, draft_id=None,
                        presentation_id=None, include_settled=False, force=False):
    """Stateful limited reconcile that survives restarts via DB columns.

    Runs in bounded batches on the existing background path and resumes when
    the consumption view opens or the explicit review action runs. No new
    scheduler service is created. Oldest rows go first so busy scopes never
    starve their earliest attempts.
    """
    if not force:
        try:
            if app.config.get('TESTING'):
                return {'reconciled': 0, 'checked': 0, 'skipped_testing': True}
        except Exception:
            pass
    try:
        pending = db.get_ai_events_needing_reconcile(
            limit=limit, tenant_id=tenant_id, draft_id=draft_id,
            presentation_id=presentation_id, include_settled=include_settled)
    except Exception as exc:
        print(f"[AI-USAGE] pending lookup failed: {exc}")
        return {'reconciled': 0, 'checked': 0}
    started = time.monotonic()
    reconciled = 0
    checked = 0
    needs_review = 0
    verified = 0
    for row in pending:
        remaining = time_budget_seconds - (time.monotonic() - started)
        if remaining <= 0:
            break
        checked += 1
        result = _reconcile_single_ai_event(
            row.get('id'), row.get('generation_id'),
            timeout=max(3, min(15, remaining)),
            is_review=bool(include_settled and row.get('cost_usd') is not None))
        if result.get('ok'):
            reconciled += 1
            if row.get('cost_source') == 'response' and result.get('cost_source') == 'generation':
                verified += 1
        if result.get('needs_review'):
            needs_review += 1
    return {'reconciled': reconciled, 'checked': checked, 'needs_review': needs_review,
            'verified': verified}


def _backfill_ai_usage_cost(event_id, generation_id, delay_seconds=0):
    """Resolve one event's dollar cost inside a worker thread."""
    try:
        with app.app_context():
            if app.config.get('TESTING'):
                return
            if delay_seconds:
                try:
                    time.sleep(min(120, max(0, int(delay_seconds))))
                except (TypeError, ValueError):
                    pass
            _reconcile_single_ai_event(event_id, generation_id)
    except Exception as exc:
        print(f"[AI-USAGE] cost backfill failed: {exc}")


def _backfill_ai_usage_cost_async(event_id, generation_id, delay_seconds=0):
    """Resolve the dollar cost off the request path."""
    try:
        thread = threading.Thread(
            target=_backfill_ai_usage_cost,
            args=(event_id, generation_id, delay_seconds),
            daemon=True,
        )
        thread.start()
    except Exception as exc:
        print(f"[AI-USAGE] cost thread failed: {exc}")


def _ai_usage_event_age_hours(created_at):
    try:
        stamp = str(created_at or '').replace(' ', 'T')[:19]
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is not None:
            moment = moment.replace(tzinfo=None)
        return (datetime.now(timezone.utc).replace(tzinfo=None) - moment).total_seconds() / 3600.0
    except Exception:
        return 0.0


def _backfill_missing_ai_costs(max_events=10, time_budget_seconds=8, max_age_hours=None, tenant_id=None):
    """Best-effort fill of costs the background threads missed. Bounded so reads stay fast.

    No age cutoff is applied: rows older than 24 hours stay eligible until
    they settle or move to needs_review. max_age_hours is kept only for
    caller compatibility and is ignored.
    """
    _reconcile_ai_scope(limit=max_events, time_budget_seconds=time_budget_seconds, tenant_id=tenant_id)


def _require_billing_balance(flow_key):
    """Pre-flight wallet guard for expensive operations.

    Returns None when the operation may proceed, otherwise a (body, status)
    tuple the route must return. Enforcement is off unless BILLING_ENFORCE=1,
    so existing behaviour and tests are unchanged until the owner enables it.
    Metering itself never raises; only this explicit billing guard can refuse.
    """
    try:
        if not db.billing_enforcement_enabled():
            return None
    except Exception:
        return None
    try:
        # Flow estimates are priced in USD product units; the wallet compares
        # in riyals, so the estimate crosses the active rate first.
        estimate_sar = db.usd_to_sar(
            float(db.get_billing_flow_estimates().get(flow_key) or 0.0))
    except (TypeError, ValueError):
        estimate_sar = 0.0
    try:
        balance = db.get_tenant_balance(g.tenant_id)
    except Exception:
        # ISS-037: an unreadable wallet is not a funded wallet — enforcement
        # that fails open turns every storage hiccup into a free paid run.
        return jsonify({
            'success': False,
            'error': 'تعذر التحقق من رصيد الشركة الآن. أعد المحاولة بعد قليل',
            'error_code': 'BILLING_CHECK_UNAVAILABLE',
        }), 503
    if balance < estimate_sar:
        return jsonify({
            'success': False,
            'error': 'الرصيد غير كافٍ لتشغيل هذه العملية. اشحن رصيد الشركة ثم أعد المحاولة',
            'error_code': 'INSUFFICIENT_BALANCE',
            'required_sar': round(estimate_sar, 2),
            'available_sar': round(balance, 2),
        }), 402
    return None


@app.route('/api/ai-usage', methods=['GET'])
@require_auth
def api_ai_usage():
    """Tenant-scoped consumption: OpenRouter totals plus Maps spend, with combined cost."""
    draft_id = (request.args.get('draftId') or request.args.get('draft_id') or '').strip() or None
    presentation_id = (request.args.get('presentationId') or request.args.get('presentation_id') or '').strip() or None
    try:
        # Same rule as /api/usage-totals: a view must answer from stored rows.
        # The live provider check held this response up to 3s on every open;
        # it now runs only on explicit ?reconcile=1 or via POST /api/ai-usage/reconcile.
        _usage_reconcile = str(request.args.get('reconcile') or '').strip().lower()
        if _usage_reconcile in ('1', 'true', 'yes'):
            try:
                _reconcile_ai_scope(limit=5, time_budget_seconds=3, tenant_id=g.tenant_id,
                                    draft_id=draft_id, presentation_id=presentation_id)
            except Exception as exc:
                import traceback as _tb
                print(f"[AI-USAGE] scoped reconcile failed: {exc}\n{_tb.format_exc(limit=5)}")
        ai_usage = db.get_ai_usage_summary(
            g.tenant_id, draft_id=draft_id, presentation_id=presentation_id)
        maps_usage = db.get_maps_usage_summary(
            g.tenant_id, draft_id=draft_id, presentation_id=presentation_id)
        ai_cost = float(ai_usage['totals'].get('cost_usd') or 0.0)
        maps_cost = float(maps_usage['totals'].get('cost_usd') or 0.0)
        try:
            reconcile_status = db.get_ai_usage_status_counts(
                g.tenant_id, draft_id=draft_id, presentation_id=presentation_id)
        except Exception:
            reconcile_status = {}
        events_page = None
        if request.args.get('page') is not None or request.args.get('pageSize') is not None:
            try:
                events_page = db.get_ai_usage_events_page(
                    g.tenant_id, draft_id=draft_id, presentation_id=presentation_id,
                    page=request.args.get('page') or 1,
                    page_size=request.args.get('pageSize') or request.args.get('page_size') or 20)
            except Exception as exc:
                print(f"[AI-USAGE] events page failed: {exc}")
                events_page = None
        try:
            _refresh_fx_rate_async()
            unbilled = db.get_unbilled_usage(
                g.tenant_id, draft_id=draft_id, presentation_id=presentation_id)
            balance_sar = db.get_tenant_balance(g.tenant_id)
            fx = db.get_fx_rate()
            billing_info = {
                'balance_sar': balance_sar,
                'balance_usd': db.sar_to_usd(balance_sar, fx.get('rate')),
                'fx': {'rate': fx.get('rate'), 'source': fx.get('source'),
                       'updatedAt': fx.get('updated_at')},
                'multiplier': db.get_billing_multiplier(),
                'enforced': db.billing_enforcement_enabled(),
                'unbilled': unbilled,
            }
        except Exception as billing_exc:
            print(f"[BILLING] unbilled lookup failed: {billing_exc}")
            billing_info = {
                'balance_sar': 0.0,
                'balance_usd': 0.0,
                'fx': {'rate': db.FX_DEFAULT_USD_SAR, 'source': 'default',
                       'updatedAt': None},
                'multiplier': db.get_billing_multiplier(),
                'enforced': False,
                'unbilled': None,
            }
        body = {
            'success': True,
            'usage': ai_usage,
            'maps': maps_usage,
            'mapsSkuPrices': dict(maps_service.MAPS_SKU_UNIT_PRICES),
            'combined': {
                'calls': int(ai_usage['totals'].get('calls') or 0) + int(maps_usage['totals'].get('calls') or 0),
                'cost_usd': ai_cost + maps_cost,
                'ai_cost_usd': ai_cost,
                'maps_cost_usd': maps_cost,
                'cost_sar': db.usd_to_sar(ai_cost + maps_cost),
                'ai_cost_sar': db.usd_to_sar(ai_cost),
                'maps_cost_sar': db.usd_to_sar(maps_cost),
            },
            'billing': billing_info,
            'reconcile': reconcile_status,
        }
        if events_page is not None:
            body['events'] = events_page
        return jsonify(body)
    except Exception as exc:
        print(f"[AI-USAGE] summary failed: {exc}")
        return jsonify({'success': False, 'error': 'تعذر تحميل الاستهلاك'}), 500


@app.route('/api/ai-usage/reconcile', methods=['POST'])
@require_company_admin
def api_ai_usage_reconcile():
    """Explicit scoped review of OpenRouter costs, including settled rows when asked.

    Compares stored rows against /generation without inventing requests:
    only rows that already carry a generation_id are touched, unknown
    requests are never imported and timing proximity never attributes them.
    """
    data = request.json or {}
    draft_id = (data.get('draftId') or data.get('draft_id') or '').strip() or None
    presentation_id = (data.get('presentationId') or data.get('presentation_id') or '').strip() or None
    try:
        limit = int(data.get('limit') or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(50, limit))
    include_settled = bool(data.get('includeSettled') or data.get('include_settled'))
    try:
        result = _reconcile_ai_scope(
            limit=limit, time_budget_seconds=25, tenant_id=g.tenant_id,
            draft_id=draft_id, presentation_id=presentation_id,
            include_settled=include_settled, force=True)
        try:
            status = db.get_ai_usage_status_counts(
                g.tenant_id, draft_id=draft_id, presentation_id=presentation_id)
        except Exception:
            status = {}
        result['reconcile'] = status
        result['success'] = True
        return jsonify(result)
    except Exception as exc:
        print(f"[AI-USAGE] reconcile failed: {exc}")
        return jsonify({'success': False, 'error': 'تعذر إتمام المطابقة'}), 500


@app.route('/api/usage-totals', methods=['GET'])
@require_auth
def api_usage_totals():
    """Bulk spend for list screens: per-project totals plus per-presentation costs."""
    def _ids(value):
        return [part.strip() for part in (value or '').split(',') if part.strip()][:200]

    try:
        # List screens must answer from stored rows only. A synchronous provider
        # reconcile holds this response for its whole time budget (up to 3s of
        # OpenRouter calls) on every list open, which is the delay seen on the
        # projects page even with two rows. Reconcile only on explicit opt-in
        # (?reconcile=1); the dedicated /api/ai-usage view still reconciles.
        _reconcile_flag = str(request.args.get('reconcile') or '').strip().lower()
        if _reconcile_flag in ('1', 'true', 'yes'):
            _backfill_missing_ai_costs(max_events=5, time_budget_seconds=3, tenant_id=g.tenant_id)
        draft_ids = _ids(request.args.get('draftIds') or request.args.get('draft_ids'))
        presentation_ids = _ids(request.args.get('presentationIds') or request.args.get('presentation_ids'))
        totals = db.get_usage_totals(
            g.tenant_id,
            draft_ids=draft_ids,
            presentation_ids=presentation_ids,
        )
        try:
            scoped = db.get_ai_usage_status_counts(g.tenant_id)
            totals['pending_costs'] = int(scoped.get('pending_costs') or 0)
            totals['reconcile'] = scoped
        except Exception:
            try:
                totals['pending_costs'] = len(db.get_ai_usage_pending_costs(limit=200, tenant_id=g.tenant_id))
            except Exception:
                totals['pending_costs'] = 0
        try:
            totals['reconcile_by_scope'] = db.get_ai_reconcile_by_scope(
                g.tenant_id, draft_ids=draft_ids, presentation_ids=presentation_ids)
        except Exception as exc:
            print(f"[AI-USAGE] scoped status failed: {exc}")
        return jsonify({'success': True, **totals})
    except Exception as exc:
        print(f"[AI-USAGE] totals failed: {exc}")
        return jsonify({'success': False, 'error': 'تعذر تحميل الإجماليات'}), 500


@app.route('/api/billing/ledger', methods=['GET'])
@require_permission('billing')
def api_billing_ledger():
    """Wallet balance, unbilled usage and ledger history for the tenant."""
    try:
        limit = request.args.get('limit') or 50
        try:
            limit = max(1, min(200, int(limit)))
        except (TypeError, ValueError):
            limit = 50
        entries = db.get_ledger_entries(
            g.tenant_id, limit=limit,
            kind=request.args.get('kind'), from_date=request.args.get('from'),
            to_date=request.args.get('to'), draft_id=request.args.get('draftId'),
            presentation_id=request.args.get('presentationId'),
            actor=request.args.get('actor'))
        balance_sar = db.get_tenant_balance(g.tenant_id)
        return jsonify({
            'success': True,
            'balance_sar': balance_sar,
            'balance_usd': db.sar_to_usd(balance_sar),
            'multiplier': db.get_billing_multiplier(),
            'enforced': db.billing_enforcement_enabled(),
            'unbilled': db.get_unbilled_usage(g.tenant_id),
            'points': db.points_overview(g.tenant_id),
            'entries': entries,
        })
    except Exception as exc:
        print(f"[BILLING] ledger failed: {exc}")
        return jsonify({'success': False, 'error': 'تعذر تحميل سجل الفوترة'}), 500


@app.route('/api/billing/checkout', methods=['POST'])
@require_auth
def api_billing_checkout():
    """Bill all unbilled usage in scope. Idempotent: a repeat call (or a
    retried request with the same idempotency key) bills nothing twice."""
    data = request.json or {}
    draft_id = (data.get('draftId') or data.get('draft_id') or '').strip() or None
    presentation_id = (data.get('presentationId') or data.get('presentation_id') or '').strip() or None
    idempotency_key = (
        request.headers.get('X-Idempotency-Key')
        or data.get('idempotencyKey') or data.get('idempotency_key') or ''
    ).strip() or None
    try:
        result = db.bill_unbilled_usage(
            g.tenant_id, draft_id=draft_id, presentation_id=presentation_id,
            idempotency_key=idempotency_key, note=data.get('note'))
    except db.InsufficientBalance as short:
        return jsonify({
            'success': False,
            'error': 'الرصيد غير كافٍ لإتمام الفوترة. اشحن رصيد الشركة ثم أعد المحاولة',
            'error_code': 'INSUFFICIENT_BALANCE',
            'required_sar': round(short.required_sar, 2),
            'available_sar': round(short.available_sar, 2),
        }), 402
    except Exception as exc:
        print(f"[BILLING] checkout failed: {exc}")
        return jsonify({'success': False, 'error': 'تعذر إتمام الفوترة'}), 500
    if not result.get('billed'):
        return jsonify({'success': True, 'billed': False, 'reason': result.get('reason'),
                        'balance_sar': db.get_tenant_balance(g.tenant_id)})
    try:
        entry = result.get('entry') or {}
        _notify_tenant_billing(
            g.tenant_id, 'خُصم من المحفظة',
            f'{float(entry.get("amount_sar") or 0.0):.2f} ريال — الرصيد الحالي '
            f'{float(result.get("balance_sar") or 0.0):.2f} ريال',
            entity_type='wallet', entity_id='debit:' + str(entry.get('id') or ''))
    except Exception:
        pass
    return jsonify({'success': True, 'billed': True, 'entry': result.get('entry'),
                    'balance_sar': result.get('balance_sar')})


@app.route('/api/admin/billing/reset-all', methods=['POST'])
@require_admin
def api_admin_billing_reset_all():
    """Forced fresh start for every company: zero wallets, unassign packages,
    and (by default) wipe spend history. Super admins are never touched.
    Requires an explicit {"confirm": true} body."""
    data = request.json or {}
    if data.get('confirm') is not True:
        return jsonify({'success': False,
                        'error': 'أرسل confirm=true لتنفيذ التصفير',
                        'error_code': 'CONFIRM_REQUIRED'}), 400
    clear_usage = data.get('clearUsage', data.get('clear_usage', True))
    clear_usage = bool(clear_usage)
    try:
        result = db.reset_all_company_balances(clear_usage=clear_usage)
    except Exception as exc:
        print(f"[BILLING] reset-all failed: {exc}")
        return jsonify({'success': False, 'error': 'تعذر تنفيذ التصفير'}), 500
    result['success'] = True
    return jsonify(result)


@app.route('/api/billing/topup', methods=['POST'])
@require_admin
def api_billing_topup():
    """Manual wallet top-ups are retired: funding is package-only.

    Companies request a catalog package and the platform desk approves the
    recharge request — no side door may mint wallet credit. The route stays
    registered so old callers get a clear refusal instead of a 404.
    """
    return jsonify({'success': False,
                    'error': 'شحن الرصيد يتم عبر باقات المنصة فقط — اعتمد طلب شحن بدل الإضافة اليدوية',
                    'error_code': 'package_only_funding'}), 403


def extract_chat_content(response, label="GLM"):
    """Safely extract text content from ZAI/GLM API response.
    Raises a descriptive exception if the response is malformed."""
    if not isinstance(response, dict):
        raise Exception(f"{label} returned an invalid response")
    if 'error' in response:
        err = response['error']
        if isinstance(err, dict):
            msg = err.get('message', json.dumps(err, ensure_ascii=False))
        else:
            msg = str(err)
        raise Exception(f"{label} API error: {msg}")
    if 'choices' not in response or not isinstance(response['choices'], list) or not response['choices']:
        raise Exception(f"{label} returned no choices. Response: {json.dumps(response, ensure_ascii=False)[:500]}")
    choice = response['choices'][0] if isinstance(response['choices'][0], dict) else {}
    message = choice.get('message') if isinstance(choice.get('message'), dict) else {}
    msg = message.get('content', '')
    if isinstance(msg, list):
        msg = ' '.join(
            part.get('text', '') if isinstance(part, dict) else str(part)
            for part in msg
        )
    if not msg:
        raise Exception(f"{label} returned empty content")
    return str(msg)
