# Platform architecture (t61)

Manafe runs as a single Flask application (`app.py`) with a SQLite or
PostgreSQL database behind the `db.py`/`db_driver.py` seam. This document
records the operational architecture decisions made for the multi-tenant SaaS
rollout.

## Process layout

- **Web process**: gunicorn serving `app.py`. All tenant traffic, the
  super-admin desk and the JSON API live here.
- **Worker process**: `scripts/worker.py`-style loop that polls the durable
  `job_queue` table (`db.claim_due_jobs`) and drains `email_outbox`
  (`db.claim_due_emails`). Background work is a row, not an in-process thread,
  so a restart loses nothing and retries are bounded by `max_attempts` before a
  job goes `dead` (re-queued by the operator via
  `POST /api/admin/jobs/requeue`).
- **Backup job**: `scripts/backup_db.py` on a schedule produces an encrypted,
  compressed copy of the database and registers it in `backup_history`.
  `scripts/restore_check.py` decrypts an artifact into scratch space and runs
  the engine's integrity check; the row is stamped `restore_tested_at`.

## Data architecture

- `db.init_db()` is idempotent and additive: every table is
  `IF NOT EXISTS`, every migration is `ALTER TABLE ... ADD COLUMN` guarded by a
  `PRAGMA table_info` read. The same code path creates a fresh install and
  upgrades an existing one.
- The relational graph is described by the schema functions
  `_create_tables`, `_create_omran_tables`, `_create_omran_role_tables`,
  `_create_omran_event_tables` and `_create_platform_tables`. Cross-tenant
  isolation is enforced by `tenant_id` on every tenant-owned row plus
  tenant-scoped queries in `db.py`.
- Append-only stores: `audit_events` (UPDATE/DELETE rejected by triggers on
  both engines), `tenant_ledger`, `ai_usage_events`, `map_usage_events`,
  `notification_deliveries`.
- Immutable version chains: `section_versions`, `tenant_contract_versions`,
  `billing_package_versions`, `document_versions`, `field_schema_versions`,
  `study_types`, `generator_registry`. A head row holds the latest version;
  history is never rewritten.
- Uniqueness enforced in the database (not app checks): `tenants.slug`,
  `tenants.username`, `recharge_requests.transfer_reference`, one active point
  reservation per generation approval, one open approval task per entity.

## Identity and access

- `auth.py` issues HMAC JWTs. `require_auth` / `require_admin` /
  `require_permission` resolve the live tenant and user row on every request,
  so a suspended company loses access immediately.
- The super admin is an `is_admin` tenant; it is isolated from company data
  models and only sees aggregate counts and metadata — never client content
  (`operational_overview` returns counts and shapes by design).
- Company workspaces are addressed by a stable Latin slug
  (`tenants.slug`, then `subdomain`, `username`, then the `t-<id8>` fallback).
  Retired slugs keep resolving through `tenant_slug_redirects` which the
  server answers with a permanent redirect.

## Storage seam

Uploaded files land under a tenant-confined directory
(`tenant-assets/<tenant_id>/...`) and are registered in `project_files` with
`sha256`, `scan_status` and the registry rule (`file_type_registry`) that
admitted them. `scan_status` is the malware-scan hook: an external scanner
flips `pending -> clean|quarantined`, and a quarantined file is never served
as a preview or export input. Moving to object storage only changes the
storage-path writer/reader, not the schema.

Downloads can be detached from the session: `POST
/api/project-files/<id>/signed-url` mints a short-lived HMAC token
(`auth.create_signed_download_token`, default 15 minutes) that
`GET /api/files/signed/<token>` verifies and serves through the same
tenant-confined path check. The token binds the file id and the owning
tenant, so a leaked link cannot cross tenants and dies on expiry.

## Observability

- `platform_alerts()` computes the alert strip: recharge SLA breaches, ticket
  SLA breaches, failed generation jobs, dead queue rows, zero-balance
  companies, RPO breach, contract expiry.
- `operational_overview()` aggregates tenants, users, presentations, spend,
  revenue, ticket mix, trends and deltas — counts only, no content.
- Every mutation writes an `audit_events` row; the super-admin company file
  and the CSV report endpoints (`/api/admin/reports/*`) read from it.

## Recovery targets

- **RPO** 24 hours (`BACKUP_RPO_HOURS`), **RTO** 4 hours
  (`BACKUP_RTO_HOURS`). The ops dashboard flags a breach when the newest
  `backup_history` success row is older than the RPO.
- Restore is verified, not assumed: `restore_check.py` must run against every
  scheduled artifact and stamps `restore_tested_at`.

## Deliberate non-goals (current phase)

- No background threads in the web process for billable work — the durable
  queue exists so a worker can be a second dyno/container without code
  changes.
- Email never sends inline; `email_outbox` absorbs SMTP outages with retries.
- Production deploy stays manual (`workflow_dispatch`) until the client app
  has its own host; staging auto-deploys on `lab` pushes.
