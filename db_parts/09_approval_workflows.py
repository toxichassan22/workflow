# ── t14/t30: generation approval + atomic points reservation ────────────────

def estimate_generation_cost(tenant_id, draft_id=None, slides_count=0, presentation_id=None):
    """Price one generation run from real units, not billing history.

    A company with no usage history used to get a zero estimate and a free
    approval. The estimate is now the product price: one plan plus every
    slide plus each map and creative image the draft already asks for, at
    the effective unit prices (``GENERATION_UNIT_PRICES``).
    """
    prices = get_generation_unit_prices()
    slides = max(1, int(slides_count or 0))
    maps_count = 0
    images_count = 0
    if draft_id:
        try:
            draft = get_project_draft_by_id(tenant_id, draft_id)
            data = (draft or {}).get('draft_data') or {}
            if isinstance(data, str):
                data = json.loads(data) if data.strip() else {}
            creative = data.get('tenantCreativeImages') if isinstance(data, dict) else {}
            if isinstance(creative, dict):
                maps = creative.get('map_placeholders')
                if isinstance(maps, dict):
                    maps_count = sum(1 for value in maps.values() if value)
                moodboard = creative.get('moodboard')
                if isinstance(moodboard, list):
                    images_count = sum(1 for value in moodboard if value)
        except Exception:
            maps_count = images_count = 0
    units = {'plan': 1, 'slide': slides, 'map': maps_count, 'image': images_count}
    estimated = round(
        sum(units[key] * prices.get(key, 0.0) for key in units) + 1e-9, 4)
    return {
        'estimated_cost_usd': estimated,
        'estimated_cost_sar': usd_to_sar(estimated),
        'estimated_points': int(round(estimated * POINTS_PER_USD)),
        'slides_count': slides,
        'units': units,
        'unit_prices': prices,
        'draft_id': draft_id,
        'presentation_id': presentation_id,
    }


def _draft_gate_transition(tenant_id, draft_id, target_status, actor_id, actor_name, reason):
    """Move a draft as part of an approval gate, warning instead of raising.

    Gate helpers already committed their own rows; a lifecycle failure here must
    surface in the result and the log without rolling the decision back.
    """
    if not draft_id:
        return None
    try:
        res = transition_project_draft_status(
            tenant_id, draft_id, target_status,
            actor_id=actor_id, actor_name=actor_name, reason=reason,
        )
    except Exception as exc:
        print(f'[LIFECYCLE] gate transition {draft_id} -> {target_status} crashed: {exc}')
        return None
    if res.get('error'):
        print(f"[LIFECYCLE] gate transition {draft_id} -> {target_status} refused: {res.get('error')}")
        return None
    return res


def create_generation_approval(tenant_id, draft_id, estimate, requested_by, requested_by_name,
                               presentation_id=None, input_snapshot=None, section_key=None):
    """Open a generation approval carrying the estimate shown to the approver.

    The request is what moves the draft into ``generation_approval_pending``:
    every tracked section must already be approved (the request itself fails
    early otherwise), one pending request per draft at a time, and a locked or
    generating draft refuses a new request. ``prior_status`` remembers where a
    rejected or released request returns the draft. ``input_snapshot`` freezes
    the priced inputs so the decision can verify nothing drifted meanwhile.

    A ``section_key`` scopes the request to one project section: the gate then
    asks only that section to be approved — the all-sections requirement
    belongs to the full-file run — and the draft lifecycle stays untouched
    (the section presentation, not the whole file, is what is being built).
    """
    section_key = str(section_key or '').strip() or None
    conn = get_db()
    draft = get_project_draft_by_id(tenant_id, draft_id)
    if not draft:
        return {'error': 'draft_not_found'}
    # One pending request per scope: a section request does not block another
    # section's request nor the full-file one.
    if section_key:
        pending = conn.execute(
            "SELECT id FROM generation_approvals WHERE tenant_id = ? AND draft_id = ? "
            "AND status = 'pending' AND section_key = ?",
            (tenant_id, draft_id, section_key),
        ).fetchone()
    else:
        pending = conn.execute(
            "SELECT id FROM generation_approvals WHERE tenant_id = ? AND draft_id = ? "
            "AND status = 'pending' AND (section_key IS NULL OR section_key = '')",
            (tenant_id, draft_id),
        ).fetchone()
    if pending:
        return {'error': 'approval_already_pending', 'approval_id': pending['id']}
    norm = normalize_proposal_status(draft.get('status'))
    if norm == 'generating':
        # A corpse run must not refuse a new request: recover the draft first,
        # then let the normal gate decide on the state that is really there.
        recover_dead_generating_drafts(tenant_id, draft_id=draft_id)
        draft = get_project_draft_by_id(tenant_id, draft_id)
        if not draft:
            return {'error': 'draft_not_found'}
        norm = normalize_proposal_status(draft.get('status'))
    if proposal_status_is_locked(norm):
        return {'error': 'draft_locked', 'status': norm}
    statuses = draft.get('section_statuses') or {}
    if section_key:
        expired = [key for key in expired_approved_sections(tenant_id, draft_id)
                   if key == section_key]
        if expired:
            return {'error': 'section_version_expired', 'sections': expired}
        if statuses.get(section_key) != 'approved':
            return {'error': 'section_not_approved', 'section': section_key,
                    'section_statuses': statuses}
        prior_status = norm
    else:
        expired = expired_approved_sections(tenant_id, draft_id)
        if expired:
            return {'error': 'section_version_expired', 'sections': expired}
        if norm == 'generated_draft':
            # Regeneration: the file exists, a new gate opens on top of it.
            prior_status = 'generated_draft'
        elif norm in {'draft', 'sections_in_progress', 'section_approval_pending',
                      'rejected_for_revision', 'sections_approved'}:
            if statuses and any(value != 'approved' for value in statuses.values()):
                return {'error': 'sections_not_approved', 'section_statuses': statuses}
            prior_status = 'sections_approved'
            if norm != 'sections_approved':
                res = _draft_gate_transition(
                    tenant_id, draft_id, 'sections_approved', requested_by, requested_by_name,
                    'جميع أقسام المشروع معتمدة — تأهيل تلقائي قبل طلب التوليد')
                if res is None:
                    return {'error': 'invalid_transition', 'current_status': norm,
                            'target_status': 'sections_approved'}
        else:
            return {'error': 'invalid_transition', 'current_status': norm}
    approval_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO generation_approvals
           (id, tenant_id, draft_id, presentation_id, estimated_cost_usd, estimated_points,
            slides_count, status, requested_by, requested_by_name, prior_status, input_snapshot,
            section_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)''',
        (approval_id, tenant_id, draft_id, presentation_id,
         float(estimate.get('estimated_cost_usd') or 0), int(estimate.get('estimated_points') or 0),
         int(estimate.get('slides_count') or 0), requested_by, requested_by_name, prior_status,
         json.dumps(input_snapshot, ensure_ascii=False) if isinstance(input_snapshot, dict) else None,
         section_key),
    )
    conn.commit()
    if not section_key:
        _draft_gate_transition(
            tenant_id, draft_id, 'generation_approval_pending', requested_by, requested_by_name,
            'طلب اعتماد التوليد')
    row = conn.execute('SELECT * FROM generation_approvals WHERE id = ?', (approval_id,)).fetchone()
    return dict(row)


def decide_generation_approval(tenant_id, approval_id, decision, decided_by, decided_by_name,
                               note=None, allow_self=False, current_section_hash=None):
    """Approve, reject or cancel. Approval reserves the points atomically.

    Separation of duties (d02): the requester cannot approve or reject their own
    request. Only a company-level administrator may combine both hats, which the
    route expresses through allow_self.

    ``current_section_hash`` is the live hash of the scoped section's inputs —
    required to decide a section-scoped request, so a drifted section fails
    closed rather than slipping through unverified.
    """
    if decision not in {'approved', 'rejected', 'cancelled'}:
        return {'error': 'invalid_decision'}
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM generation_approvals WHERE id = ? AND tenant_id = ?',
        (approval_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'approval_not_found'}
    if row['status'] != 'pending':
        return {'error': 'approval_not_pending'}
    if decision == 'cancelled' and row['requested_by'] and str(row['requested_by']) != str(decided_by):
        return {'error': 'cancel_not_allowed'}
    if decision in {'approved', 'rejected'} and not allow_self \
            and row['requested_by'] and str(row['requested_by']) == str(decided_by):
        return {'error': 'self_approval_not_allowed'}
    section_scope = (row['section_key'] if 'section_key' in row.keys() else None) or None
    if decision == 'approved' and row['draft_id']:
        # Approving generation confirms the gate behind it: a section-scoped
        # request asks only its own section, a full-file request asks every
        # tracked section of the draft.
        draft = get_project_draft_by_id(tenant_id, row['draft_id'])
        statuses = (draft or {}).get('section_statuses') or {}
        if section_scope:
            if statuses.get(section_scope) != 'approved':
                return {'error': 'section_not_approved', 'section': section_scope,
                        'section_statuses': statuses}
        elif statuses and any(value != 'approved' for value in statuses.values()):
            return {'error': 'sections_not_approved', 'section_statuses': statuses}
        # d05: an approval that expired while the request waited is no
        # longer a gate the run can rely on.
        expired = expired_approved_sections(tenant_id, row['draft_id'])
        if section_scope:
            expired = [key for key in expired if key == section_scope]
        if expired:
            return {'error': 'section_version_expired', 'sections': expired}
        # t14-04/t15-01: the inputs the approver saw and priced must still be
        # what generation will run on — edits after the request void it. A
        # section-scoped request froze only its own section's inputs, so it is
        # compared against the hash the caller computed for that section.
        snapshot = _json_object(row['input_snapshot'] if 'input_snapshot' in row.keys() else None)
        if section_scope and snapshot.get('section_hash'):
            if current_section_hash is None or snapshot['section_hash'] != current_section_hash:
                return {'error': 'inputs_changed'}
        else:
            wanted_hash = snapshot.get('draft_hash')
            if wanted_hash and draft \
                    and draft_generation_input_hash(draft.get('draft_data') or {}) != wanted_hash:
                return {'error': 'inputs_changed'}
        # And the draft must be able to enter 'generating' right now — an
        # approved reservation on an unreachable state would strand the run.
        # A section-scoped run never moves the draft, so it skips this check.
        if not section_scope and draft \
                and not can_transition_proposal_status(draft.get('status'), 'generating'):
            return {'error': 'invalid_transition',
                    'current_status': normalize_proposal_status(draft.get('status')),
                    'target_status': 'generating'}
        # Free any expired holds first so the balance check below reads the
        # real available wallet, not one inflated by dead runs.
        release_stale_reservations(tenant_id)
    reservation_id = None
    # ISS-028: the decide itself is the atomic claim — a competing decision
    # that committed meanwhile turns this UPDATE into a no-op, and the loser
    # exits before any reservation is held or lifecycle moved.
    updated_row = conn.execute(
        '''UPDATE generation_approvals SET status = ?, decided_by = ?, decided_by_name = ?,
           decided_at = ?, decision_note = ? WHERE id = ? AND status = 'pending' ''',
        (decision, decided_by, decided_by_name, _utcnow().isoformat(), str(note or '').strip() or None, approval_id),
    )
    if updated_row.rowcount != 1:
        return {'error': 'approval_not_pending'}
    if decision == 'approved' and int(row['estimated_points'] or 0) > 0:
        # One commit covers the decision and the escrow: an approval that
        # cannot hold its points rolls the decision back with it. The
        # estimate is priced in USD product units; the wallet hold is riyals.
        reservation = _hold_points_tx(
            conn, tenant_id, row['estimated_points'],
            usd_to_sar(row['estimated_cost_usd']),
            reserved_by=decided_by, reserved_by_name=decided_by_name,
            generation_approval_id=approval_id, draft_id=row['draft_id'],
            presentation_id=(row['presentation_id'] if 'presentation_id' in row.keys() else None),
        )
        if reservation.get('error'):
            conn.rollback()
            return reservation
        reservation_id = reservation['id']
    conn.commit()
    if reservation_id:
        _fire_balance_change(tenant_id)
    updated = dict(conn.execute('SELECT * FROM generation_approvals WHERE id = ?', (approval_id,)).fetchone())
    if decision == 'approved':
        if reservation_id:
            updated['reservation_id'] = reservation_id
        if section_scope:
            # A section run leaves the draft where it is — only the section's
            # own presentation is being built.
            pass
        else:
            # Approval starts the run: the draft leaves the queue for 'generating'.
            lifecycle = _draft_gate_transition(
                tenant_id, row['draft_id'], 'generating', decided_by, decided_by_name,
                'اعتماد طلب التوليد — بدء التنفيذ')
            if lifecycle:
                updated['draft_status'] = lifecycle.get('current_status')
            elif row['draft_id']:
                # The gate could not open — roll the decision and the reservation
                # back so nothing is approved against a draft that never started.
                if reservation_id:
                    release_points(tenant_id, reservation_id, settled_by=decided_by,
                                   note='تراجع الاعتماد: تعذر الانتقال إلى التوليد')
                conn.execute(
                    "UPDATE generation_approvals SET status = 'pending', decided_by = NULL, "
                    'decided_by_name = NULL, decided_at = NULL WHERE id = ?',
                    (approval_id,),
                )
                conn.commit()
                return {'error': 'lifecycle_transition_failed', 'target_status': 'generating'}
    elif not section_scope:
        # Rejected or withdrawn: the draft returns to the state it was requested
        # from — approved sections, or the generated file for a re-run.
        prior = ((row['prior_status'] if 'prior_status' in row.keys() else '') or '').strip()
        if prior not in PROPOSAL_LIFECYCLE_STATES:
            prior = 'sections_approved'
        lifecycle = _draft_gate_transition(
            tenant_id, row['draft_id'], prior, decided_by, decided_by_name,
            str(note or '').strip() or 'قرار على طلب اعتماد التوليد')
        if lifecycle:
            updated['draft_status'] = lifecycle.get('current_status')
    return updated


def settle_generation_approval(tenant_id, approval_id, job_id, consumed=True, settled_by=None, note=None):
    """After the generation job finishes: consume the reservation once, or release it.

    Settlement is also the lifecycle boundary: a consumed run lands the draft on
    ``generated_draft``; a released one returns it to the state the request came
    from so a new approval can be opened.
    """
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM generation_approvals WHERE id = ? AND tenant_id = ?',
        (approval_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'approval_not_found'}
    if row['status'] != 'approved':
        return {'error': 'approval_not_approved'}
    reservations = conn.execute(
        "SELECT * FROM point_reservations WHERE generation_approval_id = ? AND status = 'reserved'",
        (approval_id,),
    ).fetchall()
    settled = []
    for reservation in reservations:
        if consumed:
            result = consume_points(tenant_id, reservation['id'], settled_by=settled_by, note=note or job_id)
        else:
            result = release_points(tenant_id, reservation['id'], settled_by=settled_by, note=note or job_id)
        if result.get('error'):
            return result
        settled.append(result['id'])
    conn.execute(
        'UPDATE generation_approvals SET status = ?, job_id = ? WHERE id = ?',
        ('consumed' if consumed else 'rejected', job_id, approval_id),
    )
    conn.commit()
    lifecycle = None
    if (row['section_key'] if 'section_key' in row.keys() else None):
        # A section-scoped run never moved the draft — settlement leaves the
        # lifecycle untouched too.
        pass
    elif consumed:
        lifecycle = _draft_gate_transition(
            tenant_id, row['draft_id'], 'generated_draft', settled_by, settled_by,
            'اكتمال التوليد وحفظ العرض')
    else:
        prior = ((row['prior_status'] if 'prior_status' in row.keys() else '') or '').strip()
        if prior not in PROPOSAL_LIFECYCLE_STATES:
            prior = 'sections_approved'
        lifecycle = _draft_gate_transition(
            tenant_id, row['draft_id'], prior, settled_by, settled_by,
            str(note or '').strip() or 'تحرير حجز التوليد بعد فشل أو إلغاء')
    result = {'id': approval_id, 'status': 'consumed' if consumed else 'rejected', 'reservations': settled}
    if lifecycle:
        result['draft_status'] = lifecycle.get('current_status')
    return result


def _reservation_hold_key(reservation_id):
    return f'hold:{reservation_id}'


def _hold_points_tx(conn, tenant_id, points, cost_sar, reserved_by=None, reserved_by_name=None,
                    generation_approval_id=None, draft_id=None, presentation_id=None, note=None):
    """Escrow the hold inside an open transaction — never commits.

    ``cost_sar`` is wallet riyals. The wallet debit is a conditional UPDATE,
    so two parallel holds cannot spend the same balance: the loser sees
    rowcount 0 and reports ``insufficient_balance``. A live hold on the same
    approval is returned as-is (the unique index makes a second row
    impossible anyway).
    """
    points = int(points or 0)
    cost = round(float(cost_sar or 0.0) + 1e-9, 2)
    if points <= 0 or cost <= 0:
        return {'error': 'nothing_to_reserve'}
    if generation_approval_id:
        existing = conn.execute(
            "SELECT * FROM point_reservations WHERE generation_approval_id = ? AND status = 'reserved'",
            (generation_approval_id,),
        ).fetchone()
        if existing:
            return dict(existing)
    debit = conn.execute(
        'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) - ? '
        'WHERE id = ? AND COALESCE(credit_balance, 0) >= ?',
        (cost, tenant_id, cost),
    )
    if (debit.rowcount or 0) <= 0:
        return {'error': 'insufficient_balance',
                'available_sar': get_tenant_balance(tenant_id),
                'required_sar': cost}
    reservation_id = str(uuid.uuid4())
    now = _utcnow()
    expires = (now + timedelta(hours=RESERVATION_TTL_HOURS)).isoformat()
    conn.execute(
        '''INSERT INTO point_reservations
           (id, tenant_id, generation_approval_id, draft_id, points, cost_usd, cost_sar,
            status, reserved_by, reserved_by_name, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?)''',
        (reservation_id, tenant_id, generation_approval_id, draft_id, points,
         sar_to_usd(cost), cost, reserved_by, reserved_by_name, expires),
    )
    conn.execute(
        '''INSERT INTO tenant_ledger
           (id, tenant_id, kind, amount_usd, amount_sar, fx_rate, draft_id, presentation_id,
            idempotency_key, note)
           VALUES (?, ?, 'hold', ?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), tenant_id, sar_to_usd(cost), cost, _active_fx_rate(),
         draft_id, presentation_id,
         _reservation_hold_key(reservation_id),
         str(note or '').strip() or 'حجز نقاط التوليد'),
    )
    row = conn.execute('SELECT * FROM point_reservations WHERE id = ?', (reservation_id,)).fetchone()
    return dict(row)


def _claim_run_usage_tx(conn, tenant_id, ledger_id, draft_id=None, presentation_id=None,
                        reserved_at=None):
    """Attach the run's unbilled usage events to the settling ledger row.

    The reservation price is what the client pays; claiming the usage events
    under the same entry records the provider cost on it and keeps checkout
    from billing the run a second time. Events are attributed to the draft or
    the presentation — either link counts as this run. ISS-035: package-burned
    rows never join a wallet ledger, still-unpriced AI rows stay unclaimed
    until reconciliation settles them, and usage older than the hold belongs
    to a different accounting context than this run.
    """
    empty = {'ai_events_count': 0, 'maps_events_count': 0, 'raw_cost_usd': 0.0,
             'ai_cost_usd': 0.0, 'maps_cost_usd': 0.0}
    if not ledger_id:
        return empty
    clauses = ['tenant_id = ?', 'billed_ledger_id IS NULL', 'package_id IS NULL']
    params = [tenant_id]
    links = []
    if draft_id:
        links.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        links.append('presentation_id = ?')
        params.append(presentation_id)
    if not links:
        return empty
    where = 'WHERE ' + ' AND '.join(clauses) + ' AND (' + ' OR '.join(links) + ')'
    if reserved_at:
        # Bound the claim to this run's window: usage older than the hold
        # belongs to a different accounting context. Both sides are compared
        # as 'YYYY-MM-DD HH:MM:SS' text — created_at's column default and the
        # ISO form rows differ only by the 'T' separator, so REPLACE keeps the
        # comparison portable and same-second rows land inside the window.
        bound = str(reserved_at).replace('T', ' ')[:19]
        where += " AND REPLACE(created_at, 'T', ' ') >= ?"
        params.append(bound)
    ai_claim = conn.execute(
        'UPDATE ai_usage_events SET billed_ledger_id = ? ' + where
        + ' AND ' + _AI_BILLABLE_STATUS_CLAUSE,
        tuple([ledger_id] + params),
    )
    maps_claim = conn.execute(
        'UPDATE map_usage_events SET billed_ledger_id = ? ' + where,
        tuple([ledger_id] + params),
    )
    ai_count = max(0, int(ai_claim.rowcount or 0))
    maps_count = max(0, int(maps_claim.rowcount or 0))
    ai_cost = float(dict(conn.execute(
        'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM ai_usage_events WHERE billed_ledger_id = ?',
        (ledger_id,),
    ).fetchone()).get('total') or 0.0)
    maps_cost = float(dict(conn.execute(
        'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM map_usage_events WHERE billed_ledger_id = ?',
        (ledger_id,),
    ).fetchone()).get('total') or 0.0)
    return {'ai_events_count': ai_count, 'maps_events_count': maps_count,
            'raw_cost_usd': ai_cost + maps_cost, 'ai_cost_usd': ai_cost,
            'maps_cost_usd': maps_cost}


def _settle_reservation_tx(conn, tenant_id, row, new_status, settled_by=None, note=None):
    """Flip a live reservation once, inside an open transaction — never commits.

    ``consumed`` reclassifies the escrow hold as the debit that pays the run
    and claims the run's usage events onto it. ``released`` refunds the hold
    to the wallet. Both are guarded by the status flip, so a settled
    reservation can never settle again.
    """
    reservation_id = row['id']
    settled = conn.execute(
        "UPDATE point_reservations SET status = ?, settled_at = ?, settled_by = ?, note = ? "
        "WHERE id = ? AND status = 'reserved'",
        (new_status, _utcnow().isoformat(), settled_by,
         str(note or '').strip() or None, reservation_id),
    )
    if (settled.rowcount or 0) <= 0:
        return {'error': 'reservation_not_reserved'}
    hold = conn.execute(
        'SELECT * FROM tenant_ledger WHERE idempotency_key = ?',
        (_reservation_hold_key(reservation_id),),
    ).fetchone()
    if new_status == 'consumed':
        usage = _claim_run_usage_tx(
            conn, tenant_id, hold['id'] if hold else None,
            draft_id=row['draft_id'],
            presentation_id=(hold['presentation_id'] if hold and 'presentation_id' in hold.keys() else None),
            reserved_at=row['reserved_at'])
        if hold:
            conn.execute(
                '''UPDATE tenant_ledger SET kind = 'debit', raw_cost_usd = ?, multiplier = ?,
                   maps_cost_usd = ?, ai_cost_usd = ?, maps_events_count = ?, ai_events_count = ?,
                   note = ? WHERE id = ?''',
                (usage['raw_cost_usd'], get_billing_multiplier(), usage['maps_cost_usd'],
                 usage['ai_cost_usd'], usage['maps_events_count'], usage['ai_events_count'],
                 str(note or '').strip() or 'تسوية حجز التوليد', hold['id']),
            )
        else:
            # A legacy hold with no escrow: debit the wallet directly so the
            # consumption still lands on the real ledger.
            amount = _reservation_cost_sar(row)
            if amount > 0:
                debit = conn.execute(
                    'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) - ? '
                    'WHERE id = ? AND COALESCE(credit_balance, 0) >= ?',
                    (amount, tenant_id, amount),
                )
                if (debit.rowcount or 0) <= 0:
                    raise InsufficientBalance(amount, get_tenant_balance(tenant_id))
                conn.execute(
                    '''INSERT INTO tenant_ledger
                       (id, tenant_id, kind, amount_usd, amount_sar, fx_rate, draft_id,
                        idempotency_key, note)
                       VALUES (?, ?, 'debit', ?, ?, ?, ?, ?, ?)''',
                    (str(uuid.uuid4()), tenant_id, sar_to_usd(amount), amount,
                     _active_fx_rate(), row['draft_id'],
                     f'consume:{reservation_id}', str(note or '').strip() or 'تسوية حجز التوليد'),
                )
    elif new_status == 'released':
        if hold:
            # Refund the escrow: the hold row becomes the release movement so
            # the ledger still nets out to the real balance.
            conn.execute(
                "UPDATE tenant_ledger SET kind = 'release', note = ? WHERE id = ?",
                (str(note or '').strip() or 'تحرير حجز التوليد', hold['id']),
            )
            conn.execute(
                'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) + ? WHERE id = ?',
                (_reservation_cost_sar(row), tenant_id),
            )
    return dict(conn.execute('SELECT * FROM point_reservations WHERE id = ?', (reservation_id,)).fetchone())


def _reservation_cost_sar(row):
    """SAR amount a reservation holds — ``cost_sar`` natively, legacy USD
    rows converted at the active rate."""
    try:
        value = row['cost_sar']
    except (KeyError, IndexError):
        value = None
    if value is None:
        try:
            value = usd_to_sar(row['cost_usd'])
        except (KeyError, IndexError, TypeError):
            value = 0.0
    return float(value or 0.0)


def reserve_points(tenant_id, points, cost_sar=0, reserved_by=None, reserved_by_name=None,
                   generation_approval_id=None, draft_id=None, presentation_id=None, note=None):
    """t31: escrow points against the wallet before a generation run.

    ``cost_sar`` is wallet riyals. Atomic with the balance: stale holds are
    swept first, the conditional debit and the reservation row commit
    together, and a live hold on the same approval is returned instead of
    duplicated.
    """
    release_stale_reservations(tenant_id)
    conn = get_db()
    result = _hold_points_tx(
        conn, tenant_id, points, cost_sar,
        reserved_by=reserved_by, reserved_by_name=reserved_by_name,
        generation_approval_id=generation_approval_id, draft_id=draft_id,
        presentation_id=presentation_id, note=note)
    if result.get('error'):
        conn.rollback()
        return result
    conn.commit()
    _fire_balance_change(tenant_id)
    return result


def consume_points(tenant_id, reservation_id, settled_by=None, note=None):
    """Settle a reservation exactly once; a second call is refused."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM point_reservations WHERE id = ? AND tenant_id = ?',
        (reservation_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'reservation_not_found'}
    if row['status'] != 'reserved':
        return {'error': 'reservation_not_reserved'}
    try:
        result = _settle_reservation_tx(conn, tenant_id, row, 'consumed',
                                        settled_by=settled_by, note=note)
    except InsufficientBalance as short:
        conn.rollback()
        return {'error': 'insufficient_balance',
                'required_sar': short.required_sar,
                'available_sar': short.available_sar}
    if result.get('error'):
        conn.rollback()
        return result
    conn.commit()
    _fire_balance_change(tenant_id)
    return result


def release_points(tenant_id, reservation_id, settled_by=None, note=None):
    """Free a reservation after a failed generation; the escrow is refunded."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM point_reservations WHERE id = ? AND tenant_id = ?',
        (reservation_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'reservation_not_found'}
    if row['status'] != 'reserved':
        return {'error': 'reservation_not_reserved'}
    result = _settle_reservation_tx(conn, tenant_id, row, 'released',
                                    settled_by=settled_by, note=note)
    if result.get('error'):
        conn.rollback()
        return result
    conn.commit()
    _fire_balance_change(tenant_id)
    return result


def release_stale_reservations(tenant_id=None):
    """Reaper for orphaned holds: expire them, refund the escrow, and return
    their drafts from ``generating`` to the state the request came from.

    A browser that dies mid-run leaves the hold, the approved request and the
    draft state behind; this sweep heals all three. It runs lazily on the
    paths that touch the wallet (new holds, reservation lists).
    """
    conn = get_db()
    now = _utcnow().isoformat()
    clauses = ["status = 'reserved'", "expires_at IS NOT NULL", 'expires_at < ?']
    params = [now]
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(tenant_id)
    try:
        rows = conn.execute(
            'SELECT * FROM point_reservations WHERE ' + ' AND '.join(clauses),
            tuple(params),
        ).fetchall()
    except Exception:
        return 0
    released = []
    for row in rows:
        result = _settle_reservation_tx(conn, row['tenant_id'], row, 'released',
                                        settled_by='system', note='انتهت صلاحية حجز التوليد')
        if not result.get('error'):
            released.append(row)
    if not released:
        return 0
    for row in released:
        if row['generation_approval_id']:
            conn.execute(
                """UPDATE generation_approvals SET status = 'expired', job_id = ?
                   WHERE id = ? AND status = 'approved'""",
                ('reservation-expired', row['generation_approval_id']),
            )
    conn.commit()
    for _tid in {row['tenant_id'] for row in released}:
        _fire_balance_change(_tid)
    for row in released:
        # After the money is settled, bring back a draft the dead run left in
        # 'generating'. Transitions commit themselves — they stay out of the
        # wallet transaction on purpose.
        approval_id = row['generation_approval_id']
        if not approval_id or not row['draft_id']:
            continue
        approval = conn.execute(
            'SELECT prior_status FROM generation_approvals WHERE id = ?', (approval_id,),
        ).fetchone()
        draft = get_project_draft_by_id(row['tenant_id'], row['draft_id'])
        if draft and normalize_proposal_status(draft.get('status')) == 'generating':
            prior = ((approval['prior_status'] if approval and 'prior_status' in approval.keys() else '') or '').strip()
            if prior not in PROPOSAL_LIFECYCLE_STATES:
                prior = 'sections_approved'
            _draft_gate_transition(
                row['tenant_id'], row['draft_id'], prior, 'system', 'النظام',
                'استرداد حجز منتهي — إعادة الملف لحالته السابقة')
    return len(released)


def list_point_reservations(tenant_id, status=None, limit=100):
    release_stale_reservations(tenant_id)
    conn = get_db()
    if status:
        rows = conn.execute(
            'SELECT * FROM point_reservations WHERE tenant_id = ? AND status = ? ORDER BY reserved_at DESC LIMIT ?',
            (tenant_id, status, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM point_reservations WHERE tenant_id = ? ORDER BY reserved_at DESC LIMIT ?',
            (tenant_id, int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def get_active_hold_total_sar(tenant_id):
    """Wallet riyals currently escrowed in live generation holds.

    Held money is already spent from the wallet but still entitles the run
    to provider spend, so the key-limit sync adds it back on top of the
    free balance. Pure read — the stale sweep is the caller's job.
    """
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COALESCE(SUM(COALESCE(cost_sar, cost_usd * ?)), 0) AS total "
            "FROM point_reservations "
            "WHERE tenant_id = ? AND status = 'reserved'",
            (_active_fx_rate(), str(tenant_id)),
        ).fetchone()
        return float(dict(row).get('total') or 0.0)
    except Exception:
        return 0.0


def get_package_remaining_sar(tenant_id):
    """Unburned credit of the tenant's assigned package, in wallet riyals.

    Package consumption is implicit — usage rows tagged with the package id
    at write time — so remaining = package credit minus tagged spend
    converted at the active rate. No assigned package means no package
    credit, never an error.
    """
    try:
        conn = get_db()
        cycle = _tenant_package_cycle(conn, tenant_id)
        if not cycle:
            return 0.0
        package_id, credit, assigned_at = cycle
        consumed = _package_cycle_consumed_sar(conn, tenant_id, package_id, assigned_at)
        return max(0.0, credit - consumed)
    except Exception:
        return 0.0


def list_tenants_with_billable_usage(limit=200):
    """Tenants holding usage a ledger entry could bill right now.

    Feeds the periodic billing sweep: AI rows qualify only once their cost
    is settled (the checkout claim uses the same clause), Maps rows always
    qualify. Super admins are never billed.
    """
    conn = get_db()
    # ISS-034: rows covered by a live hold are not sweep candidates — the
    # settlement claims them under the reservation's own entry.
    ai_exclusion = _live_hold_exclusion_sql('ai_usage_events.tenant_id')
    maps_exclusion = _live_hold_exclusion_sql('map_usage_events.tenant_id')
    rows = conn.execute(
        'SELECT tenant_id FROM ('
        '  SELECT DISTINCT tenant_id FROM ai_usage_events '
        '   WHERE billed_ledger_id IS NULL AND tenant_id IS NOT NULL '
        '     AND package_id IS NULL AND ' + _AI_BILLABLE_STATUS_CLAUSE +
        '     AND ' + ai_exclusion +
        '  UNION '
        '  SELECT DISTINCT tenant_id FROM map_usage_events '
        '   WHERE billed_ledger_id IS NULL AND tenant_id IS NOT NULL '
        '     AND package_id IS NULL AND ' + maps_exclusion +
        ') WHERE tenant_id NOT IN (SELECT id FROM tenants WHERE COALESCE(is_admin, 0) = 1) '
        'LIMIT ?', (int(limit),),
    ).fetchall()
    return [row[0] for row in rows]


def get_generation_approval(tenant_id, approval_id):
    sweep_stale_generation_jobs(tenant_id)
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM generation_approvals WHERE id = ? AND tenant_id = ?',
        (approval_id, tenant_id),
    ).fetchone()
    return with_sar_fields(dict(row)) if row else None


def list_generation_approvals(tenant_id, status=None, limit=50):
    sweep_stale_generation_jobs(tenant_id)
    conn = get_db()
    query = ('SELECT ga.*, pd.title AS draft_title FROM generation_approvals ga '
             'LEFT JOIN project_drafts pd ON pd.id = ga.draft_id AND pd.tenant_id = ga.tenant_id '
             'WHERE ga.tenant_id = ?')
    params = [tenant_id]
    if status:
        query += ' AND ga.status = ?'
        params.append(status)
    query += ' ORDER BY ga.requested_at DESC LIMIT ?'
    params.append(int(limit))
    return with_sar_fields([dict(row) for row in conn.execute(query, params).fetchall()])
