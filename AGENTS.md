# AGENTS.md

Project notes for automated agents working on this repo (Manafe — real-estate proposal generator).

## Stack

- Backend: Flask, single file `app.py` (~7.4k lines). DB layer in `db.py` (SQLite locally, Postgres via `DATABASE_URL`).
- Frontend: one single-page app, `index.html` (~13.7k lines). All JS lives in **one inline `<script>` block** starting at line ~4195, so every function shares one scope.
- PDF handling: PyMuPDF (`fitz`). AI: OpenRouter / Z.ai (GLM) — see `.env`.

## Verification

There is no pytest; the suites use `unittest` and must be run as **modules from the repo root** (`tests/` is not an importable package, so `unittest discover` fails).

```powershell
# Main suite (50 tests) — run this for any land/croquis/draft/AI change
D:\workflow\.venv\Scripts\python.exe -m unittest tests.test_meeting_requirements

# Other suites
D:\workflow\.venv\Scripts\python.exe -m unittest tests.test_location_data_parsing
D:\workflow\.venv\Scripts\python.exe -m unittest tests.test_project_draft_isolation
D:\workflow\.venv\Scripts\python.exe -m unittest tests.test_export_slide_sanitization
D:\workflow\.venv\Scripts\python.exe -m unittest tests.test_font_workflows
```

`tests.test_full_flow` contains no unittest cases (reports "Ran 0 tests") — that is expected.

Python syntax check:
```powershell
D:\workflow\.venv\Scripts\python.exe -c "import ast; [ast.parse(open(f,encoding='utf-8').read(), f) for f in ('app.py','db.py','slide_engine.py','maps_service.py')]"
```

Frontend JS syntax check (extract the inline script and run `node --check`):
```powershell
$lines = Get-Content D:\workflow\index.html
$close = (Select-String -Path D:\workflow\index.html -Pattern '</script>' -SimpleMatch | Select-Object -Last 1).LineNumber
$lines[4195..($close-2)] -join "`n" | Set-Content "$env:TEMP\wf_check.js" -Encoding UTF8
node --check "$env:TEMP\wf_check.js"
```

Note: many tests assert against **literal source strings** in `index.html` / `app.py`. Renaming a
function or changing prompt wording can fail a test even when behaviour is correct — update the
assertion deliberately, not reflexively.

## Land / croquis subsystem gotchas

- **Form fields are defined in `db.py` `PREBUILT_FIELDS`**, not in HTML. `_migrate_location_fields`
  and `ensure_tenant_prebuilt_fields_active` re-sync label/type/section/sort_order for every tenant
  on each request, so editing `PREBUILT_FIELDS` is enough to roll out a field change.
  To retire a field add it to `REMOVED_PREBUILT_FIELDS`.
- `TENANT_PROJECT_HIDDEN_FIELDS` (index.html) hides `plot_number`, `land_area`, `built_area`,
  `building_system`, `infrastructure`, … from the project form. They are **not dead** — they carry
  data into the slide templates (`slide_engine.py`). Do not delete them.
- `collectTenantFormData()` only reads DOM inputs with `data-key`. Anything kept solely in the
  `tenantProjectData` JS object is **not persisted** to the draft. That is why the land analysis is
  mirrored into the hidden `landDocumentsAnalysisData` input.
- The coordinates/directions tables are stored as **JSON strings** in hidden inputs. Always parse
  with `parseStoredLandTable()` before rendering, and never write render output back when parsing
  fails — that previously wiped saved rows on every reload.
- `_normalize_land_document_result()` has two branches. The model normally returns a `parcels`
  array, so the legacy branch (which calls `normalize_croquis_fields`) does **not** run; per-parcel
  scalar cleanup lives in `_normalize_parcel_scalar_fields()`. Add new normalizers to both paths.
- `approved_financial_area` is **client-entered only**. AI output must never populate it.
- **Never give a land field `type: 'date'`.** These documents are dated in Hijri (`1446/03/12`) and
  `<input type="date">` accepts only ISO Gregorian, so it discards the value silently and the box
  looks empty. `croquis_expiry_date` and `deed_date` are `text`; use `parseDocumentDate()` (JS) or
  `_find_document_date()` (Python, handles Arabic-Indic digits and both day/year-first orders).
- A **facade is only a boundary that fronts a street** — every plot has four boundaries, so listing
  four compass points is meaningless. `facade_directions_from_streets()` filters neighbour
  boundaries and also derives `facades_count` when the model leaves it blank.
- `building_ratio_setbacks` is a **composite** field (ratio + coverage + FAR + floors + setbacks).
  It used to be `building_ratio || setbacks`, which collapsed it to a bare "60%".
- The land analysis has **no visible review panel** (conflicts and the parcels table were removed on
  request), but `storeLandDocumentAnalysis()` must keep writing the hidden
  `landDocumentsAnalysisData` input — the directions table falls back to `parcels[0].directions`,
  and `collectTenantFormData()` only persists DOM inputs. `conflicts` are still requested from the
  model so it records disagreements instead of silently picking a value; they surface in the
  narrative summary.

## Drafts and routing

- **Drafts are never autosaved.** `triggerAutoSaveDraft()` keeps its name (~40 call sites) but only
  sets the dirty flag via `setDraftDirty()`; a `beforeunload` handler warns about unsaved work.
  Saving happens through `saveProjectAsDraft()` (the "حفظ كمسودة" buttons) and at a few explicit
  checkpoints before slide/presentation generation, which must stay because the backend associates
  generated assets with an existing `draftId`.
- Deleting a draft must address `DELETE /api/project-draft/<draft_id>`. There is no
  collection-level DELETE route; the old `DELETE /api/project-draft` call returned 405 and left the
  draft on the server while the form looked emptied.
- `get_project_draft()` returns the **newest** row for `(tenant_id, user_id)`, while
  `/api/project-drafts` lists them all. A user can therefore own several draft rows and only the
  latest is auto-restored — that is what "a draft vanished" usually means. Which draft auto-opens
  also depends on `T_NAVIGATION_KEY` in localStorage, so it differs per device.
- **Routing:** client routes live in `TENANT_PAGE_ROUTES` (`/app/...`). `@app.errorhandler(404)`
  serves the SPA shell for HTML GETs so refreshing or sharing a deep link works;
  `SPA_RESERVED_PREFIXES` keeps real 404s for `api/`, `uploads/`, `assets/` etc. `popstate` must
  handle `/` and unmapped paths — leaving them unhandled desynced the view from the address bar and
  made the next Back exit the site. On boot, `/` is rewritten to the current page's real route.

## Timeline drives the financial study

The project timeline is the single source of truth for two things the financial study displays:

- `developmentYears` ("مدة تطوير المشروع") mirrors the timeline's `tlYears` ("عدد السنوات").
- The `scheduleTable` stage list (name + year) mirrors the named timeline phases.

Both are rendered `readonly` in the financial study; only `costPct` and `devPct` are editable there,
and they are carried across a rebuild by matching on stage name. `syncFinancialFromTimeline()` does
the mirroring and is called from `recalcTimeline()`, `saveTimelineData()`, the financial seeding
block and draft hydration. Timeline years are **calendar** years while the cashflow uses years
**relative** to project start, so the conversion is `calendarYear - tlStartYear + 1`, clamped to
`[1, developmentYears]`.

An empty timeline is allowed but surfaces `#timelineStagesWarning`, because with no stages the
development cost never reaches the cashflow. Note that `scheduleTable` no longer has an actions
column, so `reportTableSnapshot('scheduleTable', false)` must keep `false` or the PDF drops the
developer-payment column.

## Token budget for the land analysis

`max_tokens` cannot simply be raised: **OpenRouter reserves the whole cap against the account
balance**, so an over-large value is refused with `402 "You requested up to N tokens, but can only
afford M"` — the call returns no content at all, even though the real answer would have been short.
Too low a cap truncates the JSON instead, and a truncated response is discarded whole
(partial parcel data is worse than none). Both ends therefore look identical to the user: every
field keeps its old value, i.e. "re-analysis did nothing".

`_call_land_analysis_model()` negotiates this: it starts at `LAND_ANALYSIS_MAX_TOKENS` (12000,
verified affordable) and walks the cap down when the provider quotes an affordable figure.
`LAND_ANALYSIS_MIN_TOKENS`, `LAND_ANALYSIS_MODEL` are also env-overridable. Failures return a named
`failureReason` (`truncated` / `invalid_json` / `insufficient_credit` / `empty_response`) plus the
raw `providerError`, and the frontend states that no field was updated. Keep it that way — a silent
rejection is indistinguishable from a broken button.

When enlarging the prompt's expected output, re-check the truncation risk: Arabic costs roughly
two to three tokens per word, and the coordinates table can add dozens of rows.

## Regulation PDFs (الاشتراطات)

- Expected files in the repo root: `اشتراطات1.pdf` (executive regulations, 199 p) and
  `اشتراطات2.pdf` (building regulations, 142 p). Names are listed in `REGULATION_PDF_NAMES`.
- Text extraction quality differs sharply: **اشتراطات1 prose is legible**, اشتراطات2 prose loses
  letters (`المعلومات` → `المعلوما`), and **tables in both extract in reversed character order**.
  Hence the hybrid approach in `search_official_regulations_pdf()` /
  `render_regulation_table_pages()`: prose goes to the model as text, table pages go as images.
- Keyword search on these PDFs is unreliable — terms starting with `الا` (`الارتفاع`,
  `الارتدادات`, `نسبة التغطية`) match **zero** pages because of broken lam-alef ligatures. Match on
  bare roots (`ارتداد`, `تغطية`) instead.
- Index / list-of-figures pages match many keywords but contain no rules; `_is_regulation_index_page`
  filters them out.
