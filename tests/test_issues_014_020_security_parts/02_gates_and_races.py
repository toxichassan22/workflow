

class GenerationSettlementTests(ScopeTestBase):
    """ISS-042: settle/finish verify the run against server state — an
    unverified job label cannot consume or release the escrow, and a failed
    settlement can never be reported as success."""

    def _approved_run(self, draft_id, job_status='queued'):
        with self.app.app_context():
            db.save_project_draft(
                self.tenant, 'owner', {'project_name': 'مشروع التسوية'},
                {'basic': 'approved'}, 'draft', draft_id=draft_id)
            approval = db.create_generation_approval(
                self.tenant, draft_id,
                {'estimated_points': 0, 'estimated_cost_usd': 0, 'slides_count': 1},
                'owner', 'Owner')
            self.assertNotIn('error', approval, approval)
            decided = db.decide_generation_approval(
                self.tenant, approval['id'], 'approved', 'owner', 'Owner', allow_self=True)
            self.assertNotIn('error', decided, decided)
            job = db.create_generation_job(
                self.tenant, approval_id=approval['id'], draft_id=draft_id)
            if job_status != 'queued':
                job = db.update_generation_job(job['id'], status=job_status)
            return approval['id'], job['id']

    def _settle(self, approval_id, payload):
        return self.client.post(
            f'/api/generation-approvals/{approval_id}/settle',
            headers=self.admin_headers, json=payload)

    def test_consume_claim_needs_a_completed_job(self):
        approval_id, job_id = self._approved_run('settle-live', job_status='running')
        response = self._settle(approval_id, {'jobId': job_id, 'consumed': True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'job_not_completed')

    def test_release_claim_needs_a_finished_job(self):
        approval_id, job_id = self._approved_run('settle-rel', job_status='running')
        response = self._settle(approval_id, {'jobId': job_id, 'consumed': False})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'job_still_running')

    def test_settle_rejects_a_job_from_another_approval(self):
        approval_id, _job = self._approved_run('settle-a')
        other_approval, other_job = self._approved_run('settle-b')
        response = self._settle(approval_id, {'jobId': other_job, 'consumed': True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'job_mismatch')
        response = self._settle(approval_id, {'jobId': 'ghost-job', 'consumed': True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'job_mismatch')

    def test_settle_without_job_id_is_refused_when_a_run_exists(self):
        approval_id, _job = self._approved_run('settle-noname')
        response = self._settle(approval_id, {'consumed': True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'job_required')

    def test_settle_consumes_once_the_job_is_completed(self):
        approval_id, job_id = self._approved_run('settle-ok', job_status='completed')
        response = self._settle(approval_id, {'jobId': job_id, 'consumed': True})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['result']['status'], 'consumed')

    def test_finish_reports_settlement_failure_instead_of_success(self):
        approval_id, job_id = self._approved_run('finish-fail')
        with self.app.app_context():
            # Consume the approval first so the finish-time settle must fail.
            db.update_generation_job(job_id, status='running')
            settled = db.settle_generation_approval(
                self.tenant, approval_id, job_id, consumed=True)
            self.assertEqual(settled.get('status'), 'consumed')
        # The job is still 'running' server-side; finishing it now hits a
        # settle that can no longer pass — the route must surface that.
        response = self.client.post(
            f'/api/generation-jobs/{job_id}/finish',
            headers=self.admin_headers, json={'status': 'completed'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['error_code'], 'settlement_failed')
        self.assertFalse(response.get_json()['success'])


class WorkflowClaimTests(ScopeTestBase):
    """ISS-025: client-sent unlock booleans cannot mint workflow state — every
    approval the routes honor must exist as a stored server artifact."""

    def _draft(self, draft_id, data=None, status='draft', statuses=None):
        with self.app.app_context():
            saved = db.save_project_draft(
                self.tenant, 'owner', {'project_name': 'مشروع الأعلام', **(data or {})},
                statuses or {'basic': 'draft'}, 'draft', draft_id=draft_id)
            if status != 'draft':
                db.get_db().execute(
                    'UPDATE project_drafts SET status = ? WHERE id = ?', (status, saved))
                db.get_db().commit()
            return saved

    def _stored_draft_data(self, draft_id):
        with self.app.app_context():
            return (db.get_project_draft_by_id(self.tenant, draft_id) or {}).get('draft_data') or {}

    def _approve_generation(self, draft_id):
        with self.app.app_context():
            draft = db.get_project_draft_by_id(self.tenant, draft_id)
            snapshot = {'draft_hash': db.draft_generation_input_hash(draft['draft_data'] or {})}
            approval = db.create_generation_approval(
                self.tenant, draft_id,
                {'estimated_points': 0, 'estimated_cost_usd': 0, 'slides_count': 1},
                'owner', 'Owner', input_snapshot=snapshot)
            self.assertNotIn('error', approval, approval)
            decided = db.decide_generation_approval(
                self.tenant, approval['id'], 'approved', 'owner', 'Owner', allow_self=True)
            self.assertNotIn('error', decided, decided)
            return approval['id']

    def _generate_map(self, draft_id, map_type='overview', project_extra=None):
        project = {'draftId': draft_id, 'project_name': 'مشروع الأعلام'}
        project.update(project_extra or {})
        with patch.object(self.module.maps_service, 'generate_all_map_images',
                          return_value={'placeholders': {}, 'landmarks': []}), \
                patch.object(db, 'get_branding', return_value={'company_name': 'x'}):
            return self.client.post('/api/generate-map-image', headers=self.admin_headers,
                                    json={'projectData': project, 'mapType': map_type})

    def test_map_gate_reads_approval_from_storage_not_payload(self):
        # The payload claims every approval under the sun; the stored draft has
        # none, so generation is refused at the first gate.
        draft_id = self._draft('wfc-map-claims')
        response = self._generate_map(draft_id, 'overview', {
            'location_analysis_approved': True,
            'locationAnalysisApproved': True,
            'tenantCreativeImages': {'map_approvals': {'overview': True}},
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error_code'], 'LOCATION_ANALYSIS_NOT_APPROVED')

    def test_dependent_maps_need_the_stored_overview_approval(self):
        draft_id = self._draft('wfc-map-overview', {'location_analysis_approved': True})
        for map_type in ('landmarks', 'access', 'catchment'):
            response = self._generate_map(draft_id, map_type)
            self.assertEqual(response.status_code, 400, map_type)
            self.assertEqual(response.get_json()['error_code'], 'OVERVIEW_MAP_NOT_APPROVED',
                             map_type)

    def test_approved_map_cannot_be_regenerated_by_flagging_it(self):
        draft_id = self._draft('wfc-map-done', {
            'location_analysis_approved': True,
            'tenantCreativeImages': {'map_approvals': {'overview': True}},
        })
        response = self._generate_map(draft_id, 'overview')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error_code'], 'MAP_ALREADY_APPROVED')

    def test_stored_approval_lets_generation_through(self):
        draft_id = self._draft('wfc-map-ok', {'location_analysis_approved': True})
        response = self._generate_map(draft_id, 'overview')
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])

    def test_checkpoint_flag_without_a_live_run_stays_locked(self):
        # The flag claims a running generation; parked at the approval gate the
        # draft has none, so the write is refused instead of unlocking.
        draft_id = self._draft('wfc-gen-locked', status='generation_approval_pending')
        response = self.client.post('/api/project-draft', headers=self.admin_headers, json={
            'draftData': {'draftId': draft_id, 'project_name': 'مشروع الأعلام'},
            'slideCheckpoint': True})
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.get_json()['error_code'], 'DRAFT_LOCKED')

    def test_checkpoint_flag_passes_with_a_live_approval(self):
        draft_id = self._draft('wfc-gen-live', statuses={'basic': 'approved'})
        self._approve_generation(draft_id)
        with self.app.app_context():
            stored = db.get_project_draft_by_id(self.tenant, draft_id)
            self.assertEqual(db.normalize_proposal_status(stored['status']), 'generating')
        response = self.client.post('/api/project-draft', headers=self.admin_headers, json={
            'draftData': {'draftId': draft_id, 'project_name': 'مشروع الأعلام'},
            'slideCheckpoint': True})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_generation_operation_flag_cannot_unlock_a_presentation_save(self):
        # A live run bound to one file must not be used to write a different
        # one: the flag names the run's presentation or it stays locked.
        draft_id = self._draft('wfc-op-flag', status='generating')
        with self.app.app_context():
            pres_id = db.create_presentation(
                self.tenant, 'عرض مقفل', project_data={'project_name': 'مشروع الأعلام'},
                slides_data=[{'html': '<div class="slide">x</div>'}], draft_id=draft_id)
            db.get_db().execute(
                """INSERT INTO generation_approvals
                   (id, tenant_id, draft_id, presentation_id, status, requested_by,
                    decided_at, prior_status)
                   VALUES (?, ?, ?, ?, 'approved', 'owner', ?, 'sections_approved')""",
                ('appr-wfc-op-flag', self.tenant, draft_id, 'pres-other-file',
                 db._utcnow().isoformat()))
            db.get_db().commit()
        response = self.client.put(f'/api/presentations/{pres_id}',
                                   headers=self.admin_headers,
                                   json={'operation': 'generation',
                                         'projectData': {'project_name': 'مشروع الأعلام'},
                                         'expectedRevision': 0})
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.get_json()['error_code'], 'DRAFT_LOCKED')

    def test_unbacked_approval_claims_are_stripped_on_save(self):
        draft_id = self._draft('wfc-strip')
        response = self.client.post('/api/project-draft', headers=self.admin_headers, json={
            'draftData': {'draftId': draft_id, 'project_name': 'مشروع الأعلام',
                          'location_analysis_approved': True,
                          'tenantCreativeImages': {'map_approvals': {'overview': True}}}})
        self.assertEqual(response.status_code, 200, response.get_json())
        stored = self._stored_draft_data(draft_id)
        self.assertNotIn(stored.get('location_analysis_approved'), (True, 'true', 1))
        approvals = (stored.get('tenantCreativeImages') or {}).get('map_approvals') or {}
        self.assertNotEqual(approvals.get('overview'), True)


class VersionRestoreGateTests(ScopeTestBase):
    """ISS-026: restoring a version rewrites the file, so every edit gate that
    guards a PUT guards the restore as well."""

    def _draft(self, draft_id, status='draft'):
        with self.app.app_context():
            saved = db.save_project_draft(
                self.tenant, 'owner', {'project_name': 'مشروع الاستعادة'},
                {'basic': 'draft'}, 'draft', draft_id=draft_id)
            if status != 'draft':
                db.get_db().execute(
                    'UPDATE project_drafts SET status = ? WHERE id = ?', (status, saved))
                db.get_db().commit()
            return saved

    def _presentation(self, draft_id=None, status='draft'):
        with self.app.app_context():
            pres_id = db.create_presentation(
                self.tenant, 'عرض الاستعادة', project_data={'project_name': 'مشروع الاستعادة'},
                slides_data=[{'html': '<div class="slide">v1</div>'}], draft_id=draft_id)
            with self.app.test_request_context():
                from flask import g as flask_g
                flask_g.tenant_id = self.tenant
                version_id = self.module._commit_presentation_state(
                    self.tenant, pres_id, action='حالة ابتدائية', source='system')['version_id']
            if status != 'draft':
                db.get_db().execute('UPDATE presentations SET status = ? WHERE id = ?',
                                    (status, pres_id))
                db.get_db().commit()
            return pres_id, version_id

    def _restore(self, pres_id, version_id, payload=None, headers=None):
        return self.client.post(
            f'/api/presentations/{pres_id}/versions/{version_id}/restore',
            headers=headers or self.admin_headers, json=payload or {})

    def test_restore_inside_a_locked_draft_is_refused(self):
        draft_id = self._draft('rst-locked', status='generating')
        pres_id, version_id = self._presentation(draft_id=draft_id)
        with self.app.app_context():
            # A fresh approved approval makes the 'generating' state a live run
            # rather than a corpse the lock path would recover.
            db.get_db().execute(
                """INSERT INTO generation_approvals
                   (id, tenant_id, draft_id, status, requested_by, decided_at, prior_status)
                   VALUES (?, ?, ?, 'approved', 'owner', ?, 'sections_approved')""",
                ('appr-rst-locked', self.tenant, draft_id, db._utcnow().isoformat()))
            db.get_db().commit()
        response = self._restore(pres_id, version_id)
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.get_json()['error_code'], 'DRAFT_LOCKED')

    def test_restore_on_an_approved_file_needs_the_permission(self):
        pres_id, version_id = self._presentation(status='approved')
        with self.app.app_context():
            limited_id = db.create_user(self.tenant, 'محرر محدود', 'limited@scope.test',
                                        'hash', role='employee')
            for key in db.PERMISSION_KEYS:
                db.set_user_permission(limited_id, key, True)
            db.set_user_permission(limited_id, 'post_approval_edit', False)
            limited_headers = {'Authorization': 'Bearer ' + auth.create_token(
                self.tenant, 'limited@scope.test', user_id=limited_id,
                user_name='محرر محدود', user_role='employee')}
        response = self._restore(pres_id, version_id,
                                 payload={'editReason': 'سبب'}, headers=limited_headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_code'], 'post_approval_edit_required')

    def test_restore_on_an_approved_file_needs_a_reason(self):
        pres_id, version_id = self._presentation(status='approved')
        response = self._restore(pres_id, version_id, payload={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error_code'], 'reason_required')

    def test_restore_on_an_approved_file_with_reason_passes(self):
        pres_id, version_id = self._presentation(status='approved')
        response = self._restore(pres_id, version_id,
                                 payload={'editReason': 'تصحيح قيمة'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])

    def test_restore_on_an_open_file_still_works(self):
        pres_id, version_id = self._presentation()
        response = self._restore(pres_id, version_id)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])


class LegacyApprovalGateTests(ScopeTestBase):
    """ISS-027: the legacy approval table cannot mint a final approval for a
    file inside the formal lifecycle, and where it still governs it enforces
    the gate's invariants — pending state, separation of duties, rejection
    reason and content binding."""

    def _draft(self, draft_id, status='draft'):
        with self.app.app_context():
            saved = db.save_project_draft(
                self.tenant, 'owner', {'project_name': 'مشروع الاعتماد'},
                {'basic': 'draft'}, 'draft', draft_id=draft_id)
            if status != 'draft':
                db.get_db().execute(
                    'UPDATE project_drafts SET status = ? WHERE id = ?', (status, saved))
                db.get_db().commit()
            return saved

    def _presentation(self, draft_id=None):
        with self.app.app_context():
            return db.create_presentation(
                self.tenant, 'عرض الاعتماد', project_data={'project_name': 'مشروع الاعتماد'},
                slides_data=[{'html': '<div class="slide">x</div>'}], draft_id=draft_id)

    def _request(self, pres_id, headers=None):
        return self.client.post(f'/api/presentations/{pres_id}/request-approval',
                                headers=headers or self.admin_headers, json={})

    def _review(self, approval_id, status='approved', note=None, headers=None):
        payload = {'status': status}
        if note is not None:
            payload['note'] = note
        return self.client.post(f'/api/approvals/{approval_id}/review',
                                headers=headers or self.admin_headers, json=payload)

    def test_request_on_a_formal_gate_file_is_refused(self):
        draft_id = self._draft('lga-gated', status='generated_draft')
        pres_id = self._presentation(draft_id=draft_id)
        response = self._request(pres_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'use_final_approval_gate')

    def test_request_and_clean_decision_on_a_legacy_file(self):
        pres_id = self._presentation()
        requested = self._request(pres_id)
        self.assertEqual(requested.status_code, 200, requested.get_json())
        approval_id = requested.get_json()['approvalId']
        with self.app.app_context():
            row = db.get_approval(approval_id, self.tenant)
            self.assertEqual(row['status'], 'pending')
            self.assertTrue(row['request_hash'])
        decided = self._review(approval_id, 'approved')
        self.assertEqual(decided.status_code, 200, decided.get_json())
        with self.app.app_context():
            self.assertEqual(db.get_approval(approval_id, self.tenant)['status'], 'approved')
            pres = db.get_presentation(pres_id, tenant_id=self.tenant)
            self.assertEqual(pres['status'], 'approved')
        # A second decision on the settled row is refused, not re-applied.
        again = self._review(approval_id, 'approved')
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.get_json()['error_code'], 'approval_not_pending')

    def test_employee_cannot_self_decide(self):
        pres_id = self._presentation()
        requested = self._request(pres_id, headers=self.emp_headers)
        self.assertEqual(requested.status_code, 200, requested.get_json())
        approval_id = requested.get_json()['approvalId']
        decided = self._review(approval_id, 'approved', headers=self.emp_headers)
        self.assertEqual(decided.status_code, 403)
        self.assertEqual(decided.get_json()['error_code'], 'self_approval_not_allowed')

    def test_rejection_requires_a_written_reason(self):
        pres_id = self._presentation()
        approval_id = self._request(pres_id).get_json()['approvalId']
        decided = self._review(approval_id, 'rejected')
        self.assertEqual(decided.status_code, 400)
        self.assertEqual(decided.get_json()['error_code'], 'note_required')
        decided = self._review(approval_id, 'rejected', note='أعد العنوان')
        self.assertEqual(decided.status_code, 200, decided.get_json())
        with self.app.app_context():
            pres = db.get_presentation(pres_id, tenant_id=self.tenant)
            self.assertEqual(pres['status'], 'draft')

    def test_approval_fails_when_the_content_moved(self):
        pres_id = self._presentation()
        approval_id = self._request(pres_id).get_json()['approvalId']
        with self.app.app_context():
            db.get_db().execute(
                'UPDATE presentations SET project_data = ? WHERE id = ?',
                ('{"project_name": "محتوى مغيّر"}', pres_id))
            db.get_db().commit()
        decided = self._review(approval_id, 'approved')
        self.assertEqual(decided.status_code, 409)
        self.assertEqual(decided.get_json()['error_code'], 'content_changed')
        with self.app.app_context():
            self.assertEqual(db.get_approval(approval_id, self.tenant)['status'], 'pending')

    def test_a_file_that_enters_the_gate_mid_request_leaves_the_legacy_path(self):
        draft_id = self._draft('lga-mid', status='draft')
        pres_id = self._presentation(draft_id=draft_id)
        approval_id = self._request(pres_id).get_json()['approvalId']
        # The draft moved into the formal lifecycle after the request opened.
        self._draft(draft_id, status='generated_draft')
        decided = self._review(approval_id, 'approved')
        self.assertEqual(decided.status_code, 409)
        self.assertEqual(decided.get_json()['error_code'], 'use_final_approval_gate')


class ApprovalRaceTests(ScopeTestBase):
    """ISS-028: the decide UPDATE is the atomic claim — a competing decision
    committed inside the read-write window turns the loser's write into a
    refusal instead of a silent overwrite."""

    def _draft(self, draft_id, statuses=None):
        with self.app.app_context():
            return db.save_project_draft(
                self.tenant, 'owner', {'project_name': 'مشروع السباق'},
                statuses or {'basic': 'approved'}, 'draft', draft_id=draft_id)

    def _generation_approval(self, draft_id):
        with self.app.app_context():
            draft = db.get_project_draft_by_id(self.tenant, draft_id)
            snapshot = {'draft_hash': db.draft_generation_input_hash(draft['draft_data'] or {})}
            approval = db.create_generation_approval(
                self.tenant, draft_id,
                {'estimated_points': 5, 'estimated_cost_usd': 1, 'slides_count': 1},
                'owner', 'Owner', input_snapshot=snapshot)
            self.assertNotIn('error', approval, approval)
            return approval['id']

    def _final_approval(self, draft_id):
        with self.app.app_context():
            pres_id = db.create_presentation(
                self.tenant, 'عرض السباق', project_data={'project_name': 'مشروع السباق'},
                slides_data=[{'html': '<div class="slide">x</div>'}], draft_id=draft_id)
            result = db.request_final_file_approval(
                self.tenant, pres_id, revision=1, requested_by='owner', requested_by_name='Owner')
            self.assertNotIn('error', result, result)
            return result['id']

    def test_generation_decision_loses_the_race_atomically(self):
        draft_id = self._draft('race-gen')
        approval_id = self._generation_approval(draft_id)
        real_release = db.release_stale_reservations

        def competitor_wins(tenant_id):
            # A competing reviewer decided inside this decision's read-write
            # window: the row is no longer pending by the time ours writes.
            conn = db.get_db()
            conn.execute(
                "UPDATE generation_approvals SET status = 'rejected', "
                "decided_by = 'rival', decided_at = datetime('now') WHERE id = ?",
                (approval_id,))
            conn.commit()
            return real_release(tenant_id)

        with self.app.app_context(), \
                patch.object(db, 'release_stale_reservations', side_effect=competitor_wins):
            result = db.decide_generation_approval(
                self.tenant, approval_id, 'approved', 'owner', 'Owner', allow_self=True)
        self.assertEqual(result.get('error'), 'approval_not_pending')
        with self.app.app_context():
            row = db.get_db().execute(
                'SELECT * FROM generation_approvals WHERE id = ?', (approval_id,)).fetchone()
            # The winning decision stands — no overwrite, no reservation.
            self.assertEqual(row['status'], 'rejected')
            self.assertEqual(row['decided_by'], 'rival')
            holds = db.get_db().execute(
                "SELECT COUNT(*) AS n FROM point_reservations WHERE generation_approval_id = ?",
                (approval_id,)).fetchone()
            self.assertEqual(holds['n'], 0)

    def test_final_file_decision_loses_the_race_atomically(self):
        draft_id = self._draft('race-final', statuses={'basic': 'approved'})
        with self.app.app_context():
            db.get_db().execute(
                "UPDATE project_drafts SET status = 'generated_draft' WHERE id = ?",
                (draft_id,))
            db.get_db().commit()
            approval_id = self._final_approval(draft_id)
        real_get = db.get_project_draft_by_id

        def competitor_wins(tenant_id, did):
            conn = db.get_db()
            conn.execute(
                "UPDATE final_file_approvals SET status = 'approved', "
                "decided_by = 'rival', decided_at = datetime('now') WHERE id = ?",
                (approval_id,))
            conn.commit()
            return real_get(tenant_id, did)

        with self.app.app_context(), \
                patch.object(db, 'get_project_draft_by_id', side_effect=competitor_wins):
            result = db.decide_final_file_approval(
                self.tenant, approval_id, 'rejected', 'owner', 'Owner',
                note='سبب', allow_self=True)
        self.assertEqual(result.get('error'), 'approval_not_pending')
        with self.app.app_context():
            row = db.get_db().execute(
                'SELECT * FROM final_file_approvals WHERE id = ?', (approval_id,)).fetchone()
            self.assertEqual(row['status'], 'approved')
            self.assertEqual(row['decided_by'], 'rival')

    def test_section_version_decision_loses_the_race_atomically(self):
        draft_id = self._draft('race-section', statuses={'basic': 'draft'})
        with self.app.app_context():
            version = db.create_section_version(
                self.tenant, draft_id, 'basic', {'project_name': 'x'},
                created_by='owner', created_by_name='Owner')
            self.assertNotIn('error', version, version)
            version_id = version['id']
        real_days = db.get_section_approval_validity_days

        def competitor_wins(tenant_id):
            conn = db.get_db()
            conn.execute(
                "UPDATE section_versions SET status = 'returned', "
                "decided_by = 'rival', decided_at = datetime('now') WHERE id = ?",
                (version_id,))
            conn.commit()
            return real_days(tenant_id)

        with self.app.app_context(), \
                patch.object(db, 'get_section_approval_validity_days', side_effect=competitor_wins):
            result = db.decide_section_version(
                self.tenant, version_id, 'approved', 'reviewer', 'Reviewer')
        self.assertEqual(result.get('error'), 'version_not_pending')
        with self.app.app_context():
            row = db.get_db().execute(
                'SELECT * FROM section_versions WHERE id = ?', (version_id,)).fetchone()
            self.assertEqual(row['status'], 'returned')
            self.assertEqual(row['decided_by'], 'rival')


class DraftRevisionConflictTests(ScopeTestBase):
    """ISS-030: a save that names its base revision cannot silently overwrite
    a draft that moved meanwhile — the conflict surfaces instead."""

    def _save(self, draft_id, data, expected='omit', statuses=None):
        payload = {'draftData': {'draftId': draft_id, **data}}
        if statuses is not None:
            payload['sectionStatuses'] = statuses
        if expected != 'omit':
            payload['expectedRevision'] = expected
        return self.client.post('/api/project-draft', headers=self.admin_headers, json=payload)

    def _stored(self, draft_id):
        with self.app.app_context():
            return db.get_project_draft_by_id(self.tenant, draft_id)

    def test_save_chain_tracks_the_returned_revision(self):
        response = self._save('rev-draft', {'project_name': 'أول'}, expected=0)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['revision'], 1)
        response = self._save('rev-draft', {'project_name': 'ثان'}, expected=1)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['revision'], 2)
        self.assertEqual(self._stored('rev-draft')['draft_data']['project_name'], 'ثان')

    def test_stale_revision_is_refused_not_overwritten(self):
        self._save('rev-stale', {'project_name': 'أول', 'field_a': 'A'})
        # A second tab moved the row meanwhile.
        self._save('rev-stale', {'project_name': 'أول', 'field_a': 'A2'}, expected=1)
        stale = self._save('rev-stale', {'project_name': 'أول', 'field_b': 'B'}, expected=1)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()['error_code'], 'DRAFT_REVISION_CONFLICT')
        self.assertEqual(stale.get_json()['currentRevision'], 2)
        stored = self._stored('rev-stale')['draft_data']
        self.assertEqual(stored.get('field_a'), 'A2')
        self.assertNotIn('field_b', stored)

    def test_unknown_future_revision_is_refused(self):
        self._save('rev-future', {'project_name': 'أول'})
        response = self._save('rev-future', {'project_name': 'أول'}, expected=9)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'DRAFT_REVISION_CONFLICT')

    def test_legacy_save_without_revision_still_works(self):
        response = self._save('rev-legacy', {'project_name': 'أول'})
        self.assertEqual(response.status_code, 200, response.get_json())
        response = self._save('rev-legacy', {'project_name': 'ثان', 'more': 'x'})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_invalid_expected_revision_is_a_client_error(self):
        response = self._save('rev-bad', {'project_name': 'أول'}, expected='abc')
        self.assertEqual(response.status_code, 400)

    def test_presentation_get_reports_the_linked_draft_revision(self):
        """Opening a presentation must hand the workspace its draft revision —
        otherwise the next expectedRevision save conflicts against a counter
        the client never saw."""
        self._save('rev-linked', {'project_name': 'أول'}, expected=0)
        with self.app.app_context():
            pres_id = db.create_presentation(
                self.tenant, 'عرض مرتبط', project_data={'project_name': 'أول'},
                slides_data=[{'html': '<div class="slide">x</div>'}], draft_id='rev-linked')
        response = self.client.get(f'/api/presentations/{pres_id}', headers=self.admin_headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['presentation'].get('draftRevision'), 1)
        # A second save moves the draft — the next open sees the new counter.
        self._save('rev-linked', {'project_name': 'ثان'}, expected=1)
        response = self.client.get(f'/api/presentations/{pres_id}', headers=self.admin_headers)
        self.assertEqual(response.get_json()['presentation'].get('draftRevision'), 2)

    def test_section_version_restore_returns_the_new_draft_revision(self):
        self._save('rev-restore', {'project_name': 'أول'}, expected=0,
                   statuses={'basic': 'draft'})
        with self.app.app_context():
            version = db.create_section_version(
                self.tenant, 'rev-restore', 'basic', {'project_name': 'أول'},
                created_by='owner', created_by_name='Owner')
            self.assertNotIn('error', version, version)
        response = self.client.post(
            '/api/project-draft/section-version/restore',
            headers=self.admin_headers, json={'versionId': version['id']})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn('revision', response.get_json())
        self.assertEqual(
            response.get_json()['revision'],
            self._stored('rev-restore')['revision'])


class MarketJobIdentityTests(ScopeTestBase):
    """ISS-033: the background market worker must run under the job's tenant
    identity — upload dirs, logo publishing, audit rows and key selection all
    read it from g, and an app context starts empty."""

    def test_worker_stamps_tenant_and_actor_inside_its_context(self):
        from flask import g as flask_g
        captured = {}

        def fake_execute(data, tenant_id=None, progress=None):
            captured['g_tenant'] = getattr(flask_g, 'tenant_id', None)
            captured['g_user'] = getattr(flask_g, 'user_id', None)
            captured['arg_tenant'] = tenant_id
            return {'success': True, 'summary': {}}

        with patch.object(self.module, '_execute_market_summary', side_effect=fake_execute):
            self.module._market_job_worker(
                self.app, self.tenant, 'summary', {'projectData': {}}, 'job0001',
                actor={'user_id': 'u-1', 'user_name': 'Employee', 'user_role': 'employee'})

        self.assertEqual(captured['g_tenant'], self.tenant)
        self.assertEqual(captured['g_user'], 'u-1')
        self.assertEqual(captured['arg_tenant'], self.tenant)


class BillingHoldExclusionTests(ScopeTestBase):
    """ISS-034: usage under a live generation hold is prepaid by the escrow —
    the periodic sweep must not bill it separately and charge the run twice."""

    def _wallet_tenant(self, slug, credit=100.0):
        tenant = db.create_tenant('Wallet ' + slug, slug + '@example.test', 'hash', slug)
        db.record_ledger_credit(tenant, credit, note='topup')
        return tenant

    def test_unbilled_usage_under_a_live_hold_is_not_billed(self):
        with self.app.app_context():
            tenant = self._wallet_tenant('hold-tenant')
            draft_id = db.save_project_draft(
                tenant, 'owner', {'project_name': 'تشغيل'}, {'basic': 'approved'},
                'draft', draft_id='hold-draft')
            hold = db.reserve_points(
                tenant, 10, cost_usd=10.0,
                generation_approval_id='appr-1', draft_id=draft_id)
            self.assertNotIn('error', hold, hold)
            self.assertAlmostEqual(db.get_tenant_balance(tenant), 90.0)
            db.record_ai_usage_event(
                tenant, 'model-x', flow='slide', cost_usd=1.0, draft_id=draft_id)
            # The sweep must skip usage the live hold already prepays.
            result = db.bill_unbilled_usage(tenant)
            self.assertFalse(result.get('billed'), result)
            self.assertAlmostEqual(db.get_tenant_balance(tenant), 90.0)
            # Settlement claims the run's usage under its own entry — one
            # debit total, and the usage lands on that entry, not a second.
            settle = db.consume_points(tenant, hold['id'])
            self.assertNotIn('error', settle, settle)
            billed = db.get_db().execute(
                'SELECT billed_ledger_id FROM ai_usage_events WHERE tenant_id = ?',
                (tenant,)).fetchone()
            self.assertIsNotNone(billed['billed_ledger_id'])
            self.assertAlmostEqual(db.get_tenant_balance(tenant), 90.0)

    def test_usage_outside_the_hold_scope_still_bills(self):
        with self.app.app_context():
            tenant = self._wallet_tenant('hold-scope')
            db.save_project_draft(
                tenant, 'owner', {'project_name': 'تشغيل'}, {'basic': 'approved'},
                'draft', draft_id='held-draft')
            db.save_project_draft(
                tenant, 'owner', {'project_name': 'حر'}, {'basic': 'draft'},
                'draft', draft_id='free-draft')
            hold = db.reserve_points(
                tenant, 10, cost_usd=10.0,
                generation_approval_id='appr-2', draft_id='held-draft')
            self.assertNotIn('error', hold, hold)
            db.record_ai_usage_event(
                tenant, 'model-x', flow='slide', cost_usd=1.0, draft_id='held-draft')
            db.record_ai_usage_event(
                tenant, 'model-x', flow='market', cost_usd=2.0, draft_id='free-draft')
            # Only the unrelated usage bills; the held draft's spend stays
            # prepaid until settlement.
            result = db.bill_unbilled_usage(tenant)
            self.assertTrue(result.get('billed'), result)
            entry = result.get('entry') or {}
            self.assertAlmostEqual(float(entry.get('ai_cost_usd') or 0), 2.0)
            held = db.get_db().execute(
                'SELECT billed_ledger_id FROM ai_usage_events WHERE draft_id = ?',
                ('held-draft',)).fetchone()
            self.assertIsNone(held['billed_ledger_id'])

    def test_released_hold_returns_its_usage_to_billable(self):
        with self.app.app_context():
            tenant = self._wallet_tenant('hold-release')
            db.save_project_draft(
                tenant, 'owner', {'project_name': 'تشغيل'}, {'basic': 'approved'},
                'draft', draft_id='rel-draft')
            hold = db.reserve_points(
                tenant, 10, cost_usd=10.0,
                generation_approval_id='appr-3', draft_id='rel-draft')
            self.assertNotIn('error', hold, hold)
            db.record_ai_usage_event(
                tenant, 'model-x', flow='slide', cost_usd=1.0, draft_id='rel-draft')
            released = db.release_points(tenant, hold['id'])
            self.assertNotIn('error', released, released)
            # After release the escrow is refunded and the usage bills normally.
            self.assertAlmostEqual(db.get_tenant_balance(tenant), 100.0)
            result = db.bill_unbilled_usage(tenant)
            self.assertTrue(result.get('billed'), result)


class RunClaimScopeTests(ScopeTestBase):
    """ISS-035: settlement claims only this run's wallet-billable usage —
    package rows, still-unpriced attempts and usage older than the hold stay
    out of the settling entry."""

    def _settle_with_events(self, slug, events):
        with self.app.app_context():
            tenant = db.create_tenant('Claim ' + slug, slug + '@example.test', 'hash', slug)
            db.record_ledger_credit(tenant, 100.0, note='topup')
            draft_id = db.save_project_draft(
                tenant, 'owner', {'project_name': 'تشغيل'}, {'basic': 'approved'},
                'draft', draft_id='claim-draft-' + slug)
            ids = {}
            conn = db.get_db()
            for name, kwargs in events.items():
                kwargs = dict(kwargs)
                older = kwargs.pop('older_than_hold', False)
                kwargs.setdefault('tenant_id', tenant)
                kwargs.setdefault('draft_id', draft_id)
                ids[name] = db.record_ai_usage_event(model='model-x', **kwargs)
                if older:
                    conn.execute(
                        "UPDATE ai_usage_events SET created_at = '2020-01-01 00:00:00' WHERE id = ?",
                        (ids[name],))
                    conn.commit()
            hold = db.reserve_points(
                tenant, 10, cost_usd=10.0,
                generation_approval_id='appr-' + slug, draft_id=draft_id)
            self.assertNotIn('error', hold, hold)
            settle = db.consume_points(tenant, hold['id'])
            self.assertNotIn('error', settle, settle)
            rows = {
                row['id']: row['billed_ledger_id']
                for row in conn.execute(
                    'SELECT id, billed_ledger_id FROM ai_usage_events WHERE tenant_id = ?',
                    (tenant,)).fetchall()
            }
            return ids, rows

    def test_settled_usage_in_the_run_window_is_claimed(self):
        ids, rows = self._settle_with_events('inwin', {
            'settled': {'flow': 'slide', 'cost_usd': 1.0},
        })
        self.assertIsNotNone(rows[ids['settled']])

    def test_pending_and_package_rows_stay_unclaimed(self):
        ids, rows = self._settle_with_events('pend', {
            'pending': {'flow': 'slide', 'attempt_status': 'in_flight'},
            'packaged': {'flow': 'slide', 'cost_usd': 1.0, 'package_id': 'pkg-1'},
        })
        self.assertIsNone(rows[ids['pending']])
        self.assertIsNone(rows[ids['packaged']])

    def test_usage_older_than_the_hold_is_not_claimed(self):
        ids, rows = self._settle_with_events('older', {
            'prior': {'flow': 'slide', 'cost_usd': 1.0, 'older_than_hold': True},
            'current': {'flow': 'slide', 'cost_usd': 1.0},
        })
        self.assertIsNone(rows[ids['prior']])
        self.assertIsNotNone(rows[ids['current']])


class ProviderCapSyncTests(ScopeTestBase):
    """ISS-036: the provider's limit is a cumulative cap on usage — the PATCH
    must send usage + remaining entitlement or every re-sync silently shrinks
    the real allowance by what the key already burned."""

    def _sync(self, tenant, status, intended=80.0):
        captured = {}
        meta = {'has_key': True, 'openrouter_key_hash': 'hash-1',
                'is_active': 1, 'provenance': 'manual'}
        with self.app.app_context(), \
                patch.object(db, 'get_tenant_openrouter_key_meta', return_value=meta), \
                patch.object(db, 'update_tenant_openrouter_key_meta', return_value=meta), \
                patch.object(db, 'get_tenant_openrouter_key_raw', return_value='sk-or-fake'), \
                patch.object(self.module, '_openrouter_key_status', return_value=status), \
                patch.object(self.module, '_openrouter_update_managed_key',
                           side_effect=lambda h, **kw: captured.update(kw) or {'ok': True}):
            self.module._sync_tenant_credit_to_openrouter(tenant, new_limit_usd=intended)
        return captured

    def test_cap_patch_adds_recorded_usage_to_the_remaining_budget(self):
        with self.app.app_context():
            tenant = db.create_tenant('Cap T', 'cap@example.test', 'hash', 'cap-tenant')
        captured = self._sync(tenant, {'usage': 20.0, 'limit': 100.0}, intended=80.0)
        self.assertAlmostEqual(captured['limit_usd'], 100.0)

    def test_unreadable_usage_falls_back_to_the_conservative_cap(self):
        with self.app.app_context():
            tenant = db.create_tenant('Cap F', 'capf@example.test', 'hash', 'capf-tenant')
        captured = self._sync(tenant, {'error': 'network'}, intended=80.0)
        # Under-capping is the safe failure — the next successful sync corrects it.
        self.assertAlmostEqual(captured['limit_usd'], 80.0)


if __name__ == '__main__':
    unittest.main()
