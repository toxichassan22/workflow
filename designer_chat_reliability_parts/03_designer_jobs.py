# ── Queued designer jobs ────────────────────────────────────────────
# The background-job endpoints (queue + status) the reliability wrapper
# registers; split out of 02_table_intents.py to keep parts under the
# 1,000-line limit. Same exec namespace — helpers come from namespace.

def install_job_routes(app, namespace):
    """Install the queued designer-job endpoints (queue + status)."""
    require_auth = namespace["require_auth"]
    write_job = namespace["_write_job"]
    read_job = namespace["_read_job"]
    job_path = namespace["_job_path"]

    def job_context(payload):
        project_data = payload.get("projectData") if isinstance(payload.get("projectData"), dict) else {}
        context = {
            "presentationId": payload.get("presentationId") or None,
            "draftId": project_data.get("draftId") or project_data.get("draft_id") or None,
        }
        # The retry key is valid only for the exact AI request. Hashing the complete payload
        # prevents a stale tab from reusing an old result after slides, facts, images, history or
        # attachments have changed, without storing a second copy of that large request on disk.
        identity = {
            key: value for key, value in payload.items()
            if key not in {"requestId", "_job_id"}
        }
        encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        context["requestHash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return context

    def claim_job(tenant_id, job_id, initial_payload):
        """Create one queued record across Gunicorn workers before starting the AI thread."""
        path = job_path(".designer_chat_jobs", tenant_id, job_id)
        claim_path = path + ".claim"
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                descriptor = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                existing = read_job(".designer_chat_jobs", tenant_id, job_id)
                if existing:
                    return False, existing
                try:
                    if time.time() - os.path.getmtime(claim_path) > 30:
                        os.unlink(claim_path)
                        continue
                except OSError:
                    pass
                time.sleep(0.025)
                continue
            try:
                existing = read_job(".designer_chat_jobs", tenant_id, job_id)
                if existing:
                    return False, existing
                write_job(".designer_chat_jobs", tenant_id, job_id, initial_payload)
                return True, initial_payload
            finally:
                os.close(descriptor)
                try:
                    os.unlink(claim_path)
                except OSError:
                    pass
        existing = read_job(".designer_chat_jobs", tenant_id, job_id)
        if existing:
            return False, existing
        raise RuntimeError("Designer chat job registration lock timed out")

    def run_job(flask_app, tenant_id, payload, job_id, authorization):
        payload_with_job = dict(payload)
        payload_with_job["_job_id"] = job_id
        job_record_context = job_context(payload)
        heartbeat_stop = threading.Event()

        def heartbeat():
            # Touching the published file does not race with its JSON contents. The status route
            # reads the mtime as a heartbeat, so a killed worker is distinguishable from a model
            # call that is still legitimately taking several minutes.
            path = job_path(".designer_chat_jobs", tenant_id, job_id)
            while not heartbeat_stop.wait(15):
                try:
                    os.utime(path, None)
                except OSError:
                    pass

        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        with flask_app.test_request_context(
            "/api/designer-chat",
            method="POST",
            json=payload_with_job,
            headers={
                "Authorization": authorization,
                "X-Designer-Job-Id": job_id,
            },
        ):
            try:
                write_job(".designer_chat_jobs", tenant_id, job_id, {
                    **job_record_context,
                    "status": "running", "success": True, "progress": 10,
                    "message": "جاري تنفيذ وتطبيق التعديل...",
                })
                result = flask_app.view_functions["api_designer_chat"]()
                response = result[0] if isinstance(result, tuple) else result
                status_code = result[1] if isinstance(result, tuple) and len(result) > 1 else response.status_code
                body = response.get_json(silent=True) or {}
                succeeded = 200 <= int(status_code) < 300 and body.get("success")
                response_data = body.get("data") if isinstance(body.get("data"), dict) else {}
                failure_reason = body.get("failureReason") or response_data.get("failureReason")
                final_payload = {
                    **body,
                    **job_record_context,
                    "status": "completed" if succeeded else "failed",
                    "success": bool(succeeded),
                    "progress": 100,
                    "message": "اكتمل تنفيذ تعديل العرض" if succeeded else body.get("error", "تعذر تعديل العرض"),
                }
                if failure_reason:
                    final_payload["failureReason"] = failure_reason
                write_job(".designer_chat_jobs", tenant_id, job_id, final_payload)
            except Exception as error:
                flask_app.logger.exception("Designer chat background job failed")
                write_job(".designer_chat_jobs", tenant_id, job_id, {
                    **job_record_context,
                    "status": "failed", "success": False, "progress": 100,
                    "error": f"تعذر تنفيذ تعديل العرض: {error}", "failureReason": "job_failed",
                })
            finally:
                heartbeat_stop.set()

    def queue_job():
        from flask import current_app, g, jsonify, request

        payload = request.get_json(silent=True) or {}
        if not str(payload.get("message") or "").strip():
            return jsonify({"success": False, "error": "الطلب فارغ"}), 400
        requested_id = str(payload.get("requestId") or "").strip()
        if requested_id and not re.fullmatch(r"[A-Za-z0-9-]{8,64}", requested_id):
            return jsonify({"success": False, "error": "معرف الطلب غير صالح"}), 400
        job_id = requested_id or str(uuid.uuid4())
        queued_context = job_context(payload)
        # Cross-tab protection: at most one live designer job per presentation.
        # Two tabs editing the same deck used to interleave checkpoint writes
        # and silently clobber each other's slides.
        presentation_key = str(queued_context.get("presentationId") or "")
        if presentation_key:
            try:
                jobs_dir = os.path.dirname(
                    job_path(".designer_chat_jobs", g.tenant_id, "probe"))
                for name in (os.listdir(jobs_dir) if os.path.isdir(jobs_dir) else []):
                    if not name.endswith(".json") or name[:-5] == job_id:
                        continue
                    other = read_job(".designer_chat_jobs", g.tenant_id, name[:-5])
                    if not isinstance(other, dict):
                        continue
                    if str(other.get("status") or "") not in ("queued", "running"):
                        continue
                    if str(other.get("presentationId") or "") != presentation_key:
                        continue
                    try:
                        fresh = time.time() - os.path.getmtime(
                            os.path.join(jobs_dir, name)) < 120
                    except OSError:
                        fresh = False
                    if not fresh:
                        continue  # dead worker — do not block the user on a ghost
                    if other.get("requestHash") == queued_context.get("requestHash"):
                        continue  # the same request retried — claim handles it
                    return jsonify({
                        "success": False,
                        "error": "توجد مهمة تعديل قيد التنفيذ لهذا العرض — انتظر انتهاءها أو ألغها.",
                        "failureReason": "designer_job_conflict",
                        "conflictJobId": name[:-5],
                    }), 409
            except Exception:
                pass  # a scan hiccup must never block a legitimate request
        try:
            created, existing = claim_job(g.tenant_id, job_id, {
                **queued_context,
                "status": "queued", "success": True, "progress": 1,
                "message": "تم استلام طلب تعديل العرض",
                "payload": {"data": payload},
                "actor": {
                    "user_id": getattr(g, "user_id", None),
                    "user_name": getattr(g, "user_name", None),
                    "user_role": getattr(g, "user_role", None),
                },
            })
        except RuntimeError as error:
            app.logger.error("Designer chat job registration failed: %s", error)
            return jsonify({
                "success": False,
                "error": "تعذر تسجيل مهمة تعديل العرض مؤقتًا",
                "failureReason": "job_registration_failed",
            }), 503
        if not created:
            if existing.get("requestHash") and existing.get("requestHash") != queued_context["requestHash"]:
                return jsonify({
                    "success": False,
                    "error": "معرف الطلب مستخدم لمهمة تعديل أخرى",
                    "failureReason": "request_id_conflict",
                }), 409
            return jsonify({
                "success": True,
                "jobId": job_id,
                "status": existing.get("status") or "queued",
                "progress": existing.get("progress") or 1,
                "message": existing.get("message") or "مهمة تعديل العرض مسجلة",
                "reused": True,
            }), 202
        threading.Thread(
            target=run_job,
            args=(current_app._get_current_object(), g.tenant_id, payload, job_id, request.headers.get("Authorization", "")),
            daemon=True,
        ).start()
        return jsonify({
            "success": True, "jobId": job_id, "status": "queued", "progress": 1,
            "message": "بدأ تعديل العرض في الخلفية",
        }), 202

    # The restart-resume sweep in app.py re-dispatches orphaned jobs through this worker.
    namespace["_designer_chat_run_job"] = run_job

    def job_status(job_id):
        from flask import g, jsonify, request

        if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", str(job_id or "")):
            return jsonify({"success": False, "error": "معرف مهمة غير صالح"}), 400
        job = read_job(".designer_chat_jobs", g.tenant_id, job_id)
        if not job:
            return jsonify({
                "success": False, "status": "not_found",
                "error": "مهمة تعديل العرض غير موجودة أو انتهت صلاحيتها",
                "failureReason": "job_not_found",
            }), 404
        try:
            heartbeat_at = os.path.getmtime(job_path(".designer_chat_jobs", g.tenant_id, job_id))
        except OSError:
            heartbeat_at = float(job.get("updatedAt") or 0)
        response_job = {k: v for k, v in job.items()
                        if k not in ("payload", "actor", "pid")}
        state = response_job.get("agentState")
        if isinstance(state, dict) and ("slides" in state or "slidesPacked" in state):
            # The checkpoint needs the in-flight deck for restart resume, but
            # polling must never pay megabytes for it — task statuses suffice.
            state = {k: v for k, v in state.items()
                     if k not in ("slides", "slidesPacked")}
            response_job["agentState"] = state
        response_job["jobId"] = str(job_id)
        response_job["heartbeatAt"] = heartbeat_at
        if response_job.get("status") in {"queued", "running"} and heartbeat_at:
            response_job["stale"] = time.time() - heartbeat_at > 120
            if response_job["stale"]:
                response_job["message"] = "توقفت تحديثات مهمة تعديل العرض على الخادم"
        include_result = request.args.get("includeResult") == "1"
        if not include_result:
            response_job["resultReady"] = response_job.get("status") == "completed" and isinstance(response_job.get("data"), dict)
            response_job.pop("data", None)
        return jsonify(response_job)

    app.add_url_rule(
        "/api/designer-chat/jobs",
        endpoint="api_designer_chat_reliability_job",
        view_func=require_auth(queue_job),
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/designer-chat/jobs/<job_id>",
        endpoint="api_designer_chat_reliability_job_status",
        view_func=require_auth(job_status),
        methods=["GET"],
    )
