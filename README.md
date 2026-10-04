# Landloom — Real Estate Proposal Generator

Multi-tenant, Arabic-first platform that turns land and project data into
branded investment proposals, presentations and financial studies. Companies
manage their own projects, branding, wallet balance and team permissions; a
super admin owns the platform catalog and tenant keys.

## Stack

- **Backend:** Flask. `app.py` is only the loader — routes and helpers live in
  ordered part files under `app_parts/` that are `exec`'d into one shared
  namespace. Same split applies to `db.py`/`db_parts/`,
  `slide_engine.py`/`slide_engine_parts/` and `maps_service.py`/`maps_service_parts/`.
- **Frontend:** one single-page app. `index.html` is a slim shell; scripts and
  styles under `assets/js`, `assets/css` and `assets/i18n` are concatenated
  into `/assets/app.bundle.{js,css}` at request time — no build step.
- **Storage:** SQLite via `db.py` (`*.db` files are local-only). `DATABASE_URL`
  switches to Postgres where supported.
- **AI:** OpenRouter for all text and image generation (`OPENROUTER_KEY`).
  Every call is metered per tenant in `ai_usage_events`.
- **PDF:** PyMuPDF (`fitz`) + HTML render pipelines under `exports/`,
  `pdf_generator*_parts/` and `generate_pdf_from_preview_parts/`.
- **Maps:** Google Maps Static, Places (New), Distance Matrix and Street View
  Static — one restricted key (`GOOGLE_MAPS_API_KEY`). The tenant map preview
  can additionally mount a live `google.maps.Map` for free pan/zoom when a
  second, browser-side key is set (`GOOGLE_MAPS_BROWSER_API_KEY`).

## Repo layout

| Path | What lives there |
|---|---|
| `app_parts/` | Flask routes and helpers, `exec`'d by `app.py` in name order |
| `db_parts/` | Schema, billing ledger, drafts, presentations, tenants |
| `slide_engine_parts/` | Deck model, layout, HTML render |
| `maps_service_parts/` | Geocoding, static maps, overlays |
| `assets/` | Frontend JS/CSS/i18n parts, served as two bundles |
| `rules/` | Verified building-regulation digest consumed by the regulations path |
| `clean*.md` | Verified Arabic transcriptions of the regulation PDFs |
| `exports/` | PPTX/PDF exporters |
| `scripts/` | Maintenance tooling (`verify-frontend.js`, backup, fonts bundle) |
| `tests/` | unittest/pytest suites |

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # or: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in the keys below
```

Minimum `.env`:

| Variable | Purpose |
|---|---|
| `OPENROUTER_KEY` | Platform OpenRouter key (all AI generation) |
| `GOOGLE_MAPS_API_KEY` | Maps/Places/Distance Matrix/Street View |
| `GOOGLE_MAPS_BROWSER_API_KEY` | Optional browser key — Maps JavaScript API |
| `JWT_SECRET` | Session signing — set explicitly in production |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Seeds the super-admin account |
| `SMTP_*` | Outgoing mail (invites, approvals, receipts) |
| `DEPLOY_WEBHOOK_SECRET` | Authenticates the cPanel deploy webhook |

Billing, metering and model defaults (`BILLING_*`, `MAPS_*`, `*_MODEL`) all
have sane defaults in `.env.example`.

## Run

```bash
gunicorn --bind 127.0.0.1:8000 --threads 8 app:app
# or for local dev:
flask --app app run --debug
```

## Tests

```bash
python -m pytest tests/
node scripts/verify-frontend.js   # bundle order, orphans, i18n, syntax
```

## Deploy

- **Staging** — every push to `lab` runs `deploy-staging.yml`, which calls the
  webhook on `lab.landloom.ai` (`deploy-staging.sh` syncs, builds the venv,
  restarts gunicorn, verifies `/health`).
- **Production** — `deploy.yml` is manual (`workflow_dispatch`) and targets the
  `landloom.ai` cPanel account once `PROD_BASE_URL` is set.
- `render.yaml` remains as an alternative one-service Docker deploy
  (`DATABASE_URL`, `JWT_SECRET`, `ADMIN_*`, `OPENROUTER_KEY`,
  `GOOGLE_MAPS_API_KEY`); without `DATABASE_URL` it falls back to SQLite inside
  the container.

## Google Maps setup

One Google Cloud project, billing enabled, and an API key restricted to exactly
these four APIs: **Maps Static**, **Places (New)**, **Distance Matrix**,
**Street View Static**. Set it as `GOOGLE_MAPS_API_KEY` in `.env`.

For the interactive map preview (drag/zoom like Google Maps instead of
regenerating the static image on every move), create a second key with only
**Maps JavaScript API** enabled and restrict it by HTTP referrer
(`https://landloom.ai/*`, `https://lab.landloom.ai/*`, `http://localhost/*`).
Set it as `GOOGLE_MAPS_BROWSER_API_KEY`. Without it the preview keeps the
generated static image; each mounted map is metered as one Dynamic Maps load.

## Large request bodies

The hosting edge corrupts request bodies above ~40KB. The frontend gzips
bodies and splits anything above 24KB wire size into `POST /api/body-chunk`
uploads, then sends a `{"__chunked_body": ...}` envelope that a
`before_request` hook reassembles transparently — automatic for all JSON
endpoints called through the `api()` helper.

## AI rules

Company admins manage AI design/content rules from the **قواعد AI** page.
Changes are classified by risk and logged in `ai_rules_log`.
