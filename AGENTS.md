# AGENTS.md

Project notes for automated agents working on this repo (Manafe — real-estate proposal generator).

## Always push to GitHub

This is a standing owner rule. After a requested change is done and verified:

- Commit only the files that belong to that change. Do not commit local leftovers
  (`*.png`, PDFs, `model_benchmark/`, `sandbox/`, `الطلوبات لليوم.md`, etc.).
- Push `main` to `github/main` in the same turn. Do not wait to be asked again.
- If the user asked to implement something, shipping means commit **and** push.
  A local-only commit is unfinished work.

Remote: `github` → `https://github.com/toxichassan22/workflow.git`.

## Hosting autodeploy

GitHub Actions (`.github/workflows/deploy.yml`) POSTs to
`https://sagdemos.store/api/deploy-webhook` after every `main` push. The
cPanel account is `demos`; server paths are `/home/demos/workflow.git`,
`/home/demos/proposal-generator`, and `/home/demos/public_html`. Do not
put the cPanel password or `DEPLOY_WEBHOOK_SECRET` in the repo. Keep the
secret in GitHub Actions secrets and in the server `.env` only.

## No how-to text on screen

The owner asked for the instructional copy to be gone: a screen may state **what** something is
(section titles, field labels, status, empty states, errors) but never **how** to operate it. No
«اضغط ...», no «راجع ... أولًا», no «اختر ... ثم», no «اختياري: ارفع ...». `tenant-hint` still exists
for status and empty-state text — «مقفل حتى اعتماد الصورة الرئيسية», «لا توجد بنود مدخلة في هذا
الجدول», «لم تُرفع صور للأرض» — and elements that JS writes status into keep their id with an empty
default. `test_ui_carries_no_static_how_to_hints` guards both directions.

## No icons, no emojis — anywhere

This is a hard product rule, not a preference. **Never add an emoji or an icon** to this project:

- No emoji characters in UI strings, buttons, labels, placeholders, toasts, table cells, comments,
  commit messages, or generated slide/PDF content.
- No icon glyphs used as labels either — arrows (`↑ ↓ → ←`), check marks, bullets-as-symbols. Use
  Arabic words: `أعلى`, `أسفل`, `حذف`, `معاينة`.
- No icon libraries or icon fonts (Font Awesome, Material Icons, Lucide, Feather, Bootstrap Icons).
- No decorative inline `<svg>`. SVG is allowed only for genuine data rendering — currently just
  `#mapPolygonOverlay`, which draws the plot boundary.
- Use a text monogram (first letter) or a short text label where a placeholder image is missing.

`slide_engine._strip_presentation_icons()` enforces this on generated slides, and
`test_ui_contains_no_emojis_or_icon_glyphs` enforces it on `index.html`. If either fails, remove the
glyph — do not relax the check.

`emoji_icons.py` exists but is deliberately unused: it turned emojis into inline SVG icons, which
the very next line then stripped. Do not wire it back in.

## Stack

- Backend: Flask, single file `app.py` (~7.4k lines). DB layer in `db.py` (SQLite locally, Postgres via `DATABASE_URL`).
- Frontend: one single-page app, `index.html` (~13.7k lines). All JS lives in **one inline `<script>` block** starting at line ~4195, so every function shares one scope.
- PDF handling: PyMuPDF (`fitz`). AI: OpenRouter / Z.ai (GLM) — see `.env`.

## Schema gotchas

`_create_tables()` runs one big SQL script and the fallback runner splits statements on `;`.
**Never put a semicolon inside a `--` comment in that script** — the text after it is parsed as SQL,
the script aborts part-way, and every table declared below it is silently missing. The failure
surfaces far away as `no such table: <something unrelated>`.

It used to `return` early when the `tenants` table already existed, which meant the schema only ran
on a brand-new database and **every table added after the first deploy was missing forever on
existing installs** — a 500 from whichever endpoint touched it, with a healthy-looking app
otherwise. Every statement is `IF NOT EXISTS`, so it now runs unconditionally. Do not reintroduce
that guard; `test_new_tables_are_created_on_an_existing_database` covers it.

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

Frontend JS syntax check (extract the inline script and run `node --check`). Locate the block
dynamically — its start line moves whenever markup is added above it:
```powershell
$open = (Select-String -Path D:\workflow\index.html -Pattern '^\s*<script>\s*$' | Select-Object -Last 1).LineNumber
$close = (Select-String -Path D:\workflow\index.html -Pattern '</script>' -SimpleMatch | Select-Object -Last 1).LineNumber
(Get-Content D:\workflow\index.html)[$open..($close-2)] -join "`n" | Set-Content "$env:TEMP\wf_check.js" -Encoding UTF8
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
- The visible land rules are split into `building_ratio_coverage` and `setbacks`; the old
  `building_ratio_setbacks` value remains only as a compatibility value for older drafts and floor
  design payloads. Never collapse the visible ratio field to a bare "60%".
- `location_address` belongs to the `location` section and is the only visible Google Maps link
  field. Land analysis receives that link, the resolved coordinates, and the map/site context from
  the location workflow.
- Map preview «إعادة توليد» must actually fetch a new image: `POST /api/generate-map-image`
  deletes that view's DB rows, sets `refresh_maps` + `regen_seed`, and skips `_get_cached_map_images`.
  After a successful response, the client must replace the view's placeholders, bust the img cache,
  and call `selectMapPreviewView`. On the access map, Google road labels stay off and our names are
  drawn after the gold highlight so the stroke never covers the text. Directions, reverse-geocode,
  and route labels use Arabic without diacritics. Pillow uses the real presentation-form font
  `fonts/arabic-overlay.bin`; do not switch map labels to English.
- **The site boundary comes from the croquis, not from Google.** No Google Maps API returns a
  building footprint or a parcel outline: Geocoding and Places expose only a `bounds`/`viewport`
  rectangle, and Roads/Directions return road geometry. `survey_polygon_from_project()` converts the
  croquis `survey_coordinates` (UTM, zone from the longitude) to lat/lng and is tried first, then the
  OSM footprint, then `_google_bounds_polygon()` (accepted only under 400 m across), then the manual
  drawing. On the live project the converted polygon measured 7,205 sqm against an approved
  7,012 sqm, and it sat 240 m from the Maps pin — which is why the pin is now placed on the polygon
  centroid. A parcel that converts to somewhere more than 8 km away is refused, not drawn.
- `location_polygon_source` distinguishes **`none`** (nothing found yet — automatic sources must
  still run) from **`cleared`** (the user switched the highlight off). It used to default to `none`
  with `shouldHighlightTenantSite()` returning false for it, so the automatic highlight never ran.
  `survey_coordinates` must stay in `MAP_PAYLOAD_FIELDS` or the server never sees the boundary.
- The map API returns `centers` per view and stores `center_lat`/`center_lng` in each image's
  metadata. The client converts clicks against that centre; assuming the site pin put every manually
  drawn boundary off by the pin-to-plot distance, which is what made the manual highlight look fake.
  When a real boundary exists the regenerate zoom shift is skipped, otherwise it re-framed the plot
  back to a dot.
- `catchment_rings()` collapses the catchment rows into at most three concentric drive-time bands and
  `zoom_for_radius_km()` frames the outer one. The rows are destinations, so one ring per row drew
  nine circles up to 31 km wide with unreadable labels. The landmarks view is framed the same way
  around the landmarks it draws; it used to inherit the plot zoom, so every landmark fell outside
  the frame.
- Landmark names are resolved with `find_place_near()` (Places text search biased to the site).
  Geocoding `"<name>, <project address>"` returned the project's own coordinates, so 14 of 16
  landmarks were then dropped by the 50 m duplicate filter and the map showed none.
- The land analysis reads the complete text and tables from both `اشتراطات1.pdf` and
  `اشتراطات2.pdf` by default. Page numbers may remain in internal evidence metadata, but must never
  be written into user-facing land fields or the narrative summary. `allowed_uses` and
  `regulatory_constraints` are separate visible fields; the former must state whether the selected
  project type is allowed, disallowed, or unresolved.
- The land analysis has **no visible review panel** (conflicts and the parcels table were removed on
  request), but `storeLandDocumentAnalysis()` must keep writing the hidden
  `landDocumentsAnalysisData` input — the directions table falls back to `parcels[0].directions`,
  and `collectTenantFormData()` only persists DOM inputs. `conflicts` are still requested from the
  model so it records disagreements instead of silently picking a value; they surface in the
  narrative summary.

## Project team (فريق العمل)

Two layers, deliberately:

- **Company library** — `tenant_team_entities`, managed at `/app/settings/team`, shared by every
  project file. A **flat list**, deliberately: there is no category layer. One was built and then
  removed because each entity already states what it does in its `role` field, so categories only
  added a required first step and a way to fail. Do not reintroduce them.
- **Per-file choices** — one `team_selection` key in `draft_data`:
  `{excluded: [libraryId], roles: {libraryId: text}, local: [{localId, ...six fields}]}`.
  Excluding an entity or overriding its role affects only that file; `local` entities exist only in
  that file. Nothing here writes back to the library.

Logos reuse `project_files` with `file_type='team_logo'`, so they inherit tenant scoping and the
authenticated `GET /api/project-files/<id>` preview route. `team_logo` is in
`PROJECT_IMAGE_ONLY_TYPES` because it renders in an `<img>`.

Section order is `basic → location → land_croquis → timeline → financial → team → market study → conceptual 2D`.
The first three come from the `sectionOrder` loop; the remaining sections are appended in that order.

## Market study (دراسة السوق)

The full brief is `تحليل السوق .pdf`. `market_study.py` is that brief as code — indicators, source
priority, mandatory rules, and option lists. `SOURCE_PRIORITY` is the canonical five-level source
order supplied by the owner, while `TYPE_SOURCE_PRIORITY` contains the exact per-type source lists
from the brief. The AI must start at the applicable level 1 list and descend only when the higher
level has no usable data. Do not drop a required item from the PDF to shorten a prompt or a screen.

- **Basic fields:** `project_type` is a multi-select of the four mains (سكني / تجاري /
  فندقي / صناعي ولوجستي). One choice is a single-type project; two or more is mixed-use.
  There is no fifth "متعدد الاستخدامات" option. Then `project_subtype` opens the matching
  subtype list for each chosen type; residential has no subtypes. `activity_class` sits
  after the subtype selector. Extra classification is one field: hotel / office /
  industrial get specialized lists, every other type uses the generic مستوى المشروع
  list. `project_idea` is client-typed only. Choosing a main plus subtype reveals the
  matching audience list. Audience drawers are grouped by audience kind, so all hotel
  subtypes share one فندقي audience drawer instead of repeating identical drawers.
- **City / district:** visible in الموقع, filled from reverse geocode of the Maps link, editable,
  and mirrored read-only inside دراسة السوق. Persist via `data-key`.
- **Section body** lives in `draft_data.market_study_data` (hidden `#marketStudyData` input).
  The competitor table shows project name, type, area, status, source, operation type,
  dynamic price type, and dynamic value. The backend-only `classification` is preserved
  in each row but is not a visible table column. Price inputs default to Saudi riyal (`SAR`);
  range types render `من` and `إلى` values. Competitor radius has no fake «تلقائي» option:
  the default is an explicit `10` km. Saved drafts that still store `auto` map back to 10 km.
  `city` and `custom` are real instructions sent to the search. Generating competitors **replaces** the table
  with the new list. Fill-by-name completes empty cells only and never adds or deletes a row.
  Re-generating a summary shows current vs new and waits for replace/keep. The client also
  asked for a separate SWOT block (`strengths` / `weaknesses` / `opportunities` / `threats`)
  inside دراسة السوق; it is generated with the summary but must stay independent of the
  ten executive-summary sections from the PDF. The market summary must start with
  `الملخص التنفيذي لسوق المشروع`, contain the ten sections in order, target about 500 words,
  and use `غير متوفر من مصدر موثوق` for unavailable information; the decision must always
  be one of the five allowed classifications.
- Production jobs are queued (`POST /api/market-study/competitors` or `/summary`, poll
  `GET /api/market-study/jobs/<id>`) for the same hosting-proxy reason as croquis. Tests stay
  synchronous unless they pass `background: true`. Web search goes through the OpenRouter
  `openrouter:web_search` server tool; a failed tool call retries without tools. Missing figures stay
  `غير متوفر من مصدر موثوق`. Competitor `source_url` and summary `url` must be the exact
  page that contained the figure, not the site homepage. `prefer_specific_source_url()`
  drops a bare domain/home path when a deeper URL is also present.
- **Never send the search tool together with `response_format: json_object`.** Gemini answers that
  pair with reasoning and empty content, the JSON parse fails, and the retry ladder then drops the
  tool — so no search ever ran and every link was a homepage recalled from memory. The first attempt
  in `_call_market_study_model` must be tools with JSON mode **off** (`parse_json_object` reads the
  fenced block), and the tool asks for `engine: 'exa'` because native Google search returns no
  citations. `_market_citation_urls()` reads the `url_citation` annotations and
  `market_study.apply_search_citations()` swaps a model-written homepage for the retrieved page on
  the same host. It never touches a row the user typed (`row_source != 'ai'`).
- One market-wide search cannot price six competitors. The tool is given `max_uses` and
  `max_total_results`, and `build_competitors_user_prompt()` carries a «بروتوكول البحث الإلزامي»
  that requires a separate price search per competitor plus the allowed `price_type` list per
  operation. Without both, every price came back empty (or, before the search worked at all,
  invented). A row with an empty price and `غير متوفر من مصدر موثوق` is the correct output; a
  number without the page it came from is not.

## Performance rules

- `compress_response()` gzips text responses (`app.py`). The SPA shell is ~740KB uncompressed and
  ~156KB gzipped. It reads file responses by clearing `direct_passthrough`.
- The shell is served `Cache-Control: no-cache` — revalidate, **not** `no-store`. `no-store`
  forbids keeping a copy at all and re-downloaded all 740KB on every load; with the ETag from
  `send_from_directory` an unchanged shell now answers 304 with no body.
- `ensure_tenant_prebuilt_fields_active()` runs on every `/api/fields` call. It **must compare
  before writing** — it used to issue 39 UPDATEs plus a commit per project-form load. Keep the
  `unchanged` check and the `dirty` flag.
- Draft lists must use `get_all_project_draft_summaries()`, never `get_all_project_drafts()`:
  `draft_data` holds slide HTML and base64 images.
- Hot lookups are "newest draft for this actor" and "active fields ordered by sort_order"; both
  have composite indexes. A single-column index on `tenant_id` still sorts every row.

## Drafts and routing

- **Drafts persist only `data-key` DOM values.** `saveProjectAsDraftNow()` merges
  `tenantProjectData` with `collectTenantFormData()`. Anything kept only in a JS object or
  a custom widget is **lost on save** unless it is written into a `data-key` input first.
  New fields and new sections are therefore mandatory draft work: give them a `data-key`,
  keep a hidden/native input in `#tenantProjectForm`, and call an explicit persist helper
  from `saveProjectAsDraftNow()` / `collectTenantFormData()` before the merge. Custom
  widgets (`<select>` overlays, drawers, maps, tables) must never be the only copy of the
  value. Classification currently uses `persistClassificationDraftState()` for
  `project_type`, `project_subtype`, `target_audience`, and `activity_class`.
  Visual concept uses `persistVisualConceptDraftState()` for the hidden
  `visual_concept` input plus `tenantCreativeImages`. The page now has two
  groups on a home page of two cards, like floor-design stages: `التصور الخارجي`
  (`cover`, `right`, `left`, `top`, `back`) and `التصور الداخلي`. Internal
  images are one per actual financial-study component, chosen from a
  dropdown. Each component has its own five optional references plus the
  approved cover as a required sixth image. Clicking a card opens that
  group's workspace. Legacy
  ids `east`/`west`/`aerial` hydrate into `right`/`left`/`top`. Rebuilding
  the project form must restore the existing `visual_concept` /
  `target_audience` values before writing those hidden inputs; empty widgets
  must not overwrite a saved draft. External angle slots restore from
  `tenantCreativeImages.moodboard` and `moodboard_prompts` the same way the
  cover restores from `cover`.
  The optional style reference is a `project_files` upload with
  `file_type='visual_reference'`. Land photos are not visual-concept
  references. The external reference input accepts up to five images and
  persists `styleReferenceFileIds` (with singular legacy fields retained).
  Cover generation uses those references and the overview map when it fits
  the provider's five-image limit; external angles use the approved cover
  only. Generated local image URLs get a cache-busting query on regeneration.
  **Never hold a slot reference across an `await` or a render.** `renderVisualConceptPage()`
  reassigns `tenantVisualConceptState` through `normalizeVisualConceptState()`, which builds new
  slot objects, so a `const slot = tenantVisualConceptState.slots[slotId]` captured earlier is
  detached. That is why the cover image reported success and never appeared: the status was written
  to the live slot and `imageUrl` to the dead one. `generateVisualConceptImage()` and
  `sendVisualConceptChat()` use a `liveSlot()` accessor instead.
  **Each image carries the same single approval toggle as a section**: `اعتماد` becomes
  `الغاء الاعتماد`, the chip reads `مسودة` / `معتمد`, and while approved the card gets
  `.section-locked` and every control in it — prompt, generate, chat, and the interior reference
  card — is disabled except the toggle. Unapproving the cover re-locks the angles and interiors
  because they key off `cover.approvedImageUrl`.
  `normalizeVisualConceptState()` must decide approval from the slot's own state, never from the
  legacy `tenantCreativeImages.cover` / `moodboard` mirrors: those store unapproved previews too, so
  rebuilding from them re-approved an image on the next render or reload. The `stated[id]` guard
  keeps the mirrors as a fallback for old drafts only, and unapproving the cover clears
  `tenantCreativeImages.cover` because slides read that as the approved cover.
- **Rebuilding the form can wipe a saved draft.** `renderTenantProjectForm()`
  recreates every `data-key` input empty, then persist helpers run immediately.
  If a helper reads the new empty widget instead of `tenantProjectData`, the
  next save stores blanks. This already happened twice:
  - `target_audience` disappeared because `renderGroupedAudienceFields()` and
    `persistClassificationDraftState()` wrote `{}` when the drawers were not
    mounted yet.
  - Moodboard images and prompts disappeared because
    `persistVisualConceptDraftState()` rewrote `tenantCreativeImages.moodboard`
    from empty slots. The cover survived only because it had a separate
    `tenantCreativeImages.cover` fallback.
  The fix: seed hidden inputs from `tenantProjectData` while building the
  form, restore `tenantVisualConceptState` before persist, never replace a
  populated value with `{}` / `''` during a render pass, and fall back to
  previously saved creative assets (`cover`, `moodboard`,
  `moodboard_prompts`) when a slot is empty. A later agent adding a custom
  field must assume this wipe will happen unless they copy that pattern.
- **Every new section or page gets an explicit draft save.** Give it a `data-key` in
  `#tenantProjectForm`, persist it from `saveProjectAsDraftNow()` /
  `collectTenantFormData()`, and put a visible `حفظ كمسودة` button on that page. Do not
  rely on autosave or on values that live only in a JS object.
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
`[1, developmentYears]`. Developer and development-cost amounts are spread evenly across every
cashflow year the phase covers (`stageYear` through `stageEndYear` from «إلى»), not dumped into
the start year only. If the timeline has no named phases, do not rebuild/wipe `scheduleTable`
or overwrite `developmentYears`; keep the hydrated financial stages.

Each phase row has a start year/quarter and a duration in months. `computeTimelineEnd()` fills the
read-only «إلى» cell (`endYear` / `endQuarter` in `timeline_table_data`). Clients only type the
start and the months; never ask them to enter the end. The notes column is part of the timeline
slide: `parse_timeline_phases()` / `_timeline_data_note()` inject the full phase list (including
notes) into the slide-plan and slide-generation prompts, because the truncated project JSON can
drop `timeline_table_data`. Notes are not mirrored into the financial study.

An empty timeline is allowed but surfaces `#timelineStagesWarning`, because with no stages the
development cost never reaches the cashflow. Note that `scheduleTable` no longer has an actions
column, so `reportTableSnapshot('scheduleTable', false)` must keep `false` or the PDF drops the
developer-payment column.

## Financial study draft and PDF

The study is not just the two hidden `data-key` inputs. Persist the full snapshot through
`persistFinancialStudyDraftState()` into `financial_study_model` (hidden `#financialStudyModelData`
plus the JS object). That object must include `dynamicRows.sensitivity` so table 14 survives a
reload. `collectFinancialStudyModel()` must keep values from fields that are currently hidden by a
mode switch; otherwise toggling بيع / تأجير wipes the other side on the next save.

Save **raw numbers**, never `money()` strings, in `inputs` and `dynamicRows`. A `type="number"`
field silently blanks `189,750,000`, so the next `calculateAll()` treats project cost and every
derived finance total (`financeBaseAmount`, `facilityAmount`, arrangement fees, interest, equity)
as zero. `parseNumber()` / `financialInputNumber()` / `setFinancialSnapshotInput()` must strip
commas and Arabic digits before writing a value back into an input.

Server PDF (`build_financial_report_html`) must emit section 14 «تحليل الحساسية العام». Do not wrap
wide tables (`cashflowTable`, `sensitivityTable`) in `break-inside:avoid` or the last rows are
clipped. Strip «ترتيب / حذف» from both the print snapshot and the server table renderer.
`POST /api/financial-study/export` is authenticated only (`@require_auth`); do not put
`export_files` back on it — employees who can fill the study must be able to download it.
The financial section itself needs a visible `حفظ كمسودة` next to the PDF button.
`generate_financial_pdf()` has three engines and the order matters. Playwright is only available
locally; hosting has no Chromium, so the real engine there is
`generate_financial_pdf_from_model()`, which embeds the font itself. The MuPDF HTML engine
(`fitz.open('html', ...)`) depends on **system** Arabic fonts the host does not have and writes
pages of empty table borders, so it stays last. Every engine's output is gated on
`_financial_pdf_has_text()` — a size-only check accepted those blank pages and the client
downloaded an empty report.

In the model writer, never use `insert_textbox`: it silently draws **nothing** when the font's line
height does not fit the rectangle, which is how the whole report became borders with no text. Use
the `place()` helper (`insert_text` + `Font.text_length` for right alignment). PyMuPDF applies no
shaping or bidi, so text must go through `_financial_pdf_shape()`
(`maps_service.shape_arabic_for_drawing`) first, and Latin or `%` characters must be drawn with
`helv` because the bundled Arabic font has no glyph for them — `split_runs()` does that. Tables and
label/value pairs are laid out right-to-left.

Arabic in that PDF must use `fonts/arabic-text.bin`; Pillow map overlays must use
`fonts/arabic-overlay.bin` (both are real fonts stored under non-LFS names). Hosting cannot
use `*.ttf` because those files are Git LFS pointers. Strip Arabic diacritics from map road
names before reshaping; do not draw Arabic with Helvetica.

Map overlay fonts must be loaded with `layout_engine=ImageFont.Layout.BASIC`. `_reshape_arabic_text`
already returns presentation forms in visual order, and a Pillow built **with Raqm** (hosting, not
the local venv) re-runs bidi over them and draws every label backwards.

Section approval is one toggle: `اعتماد` / `الغاء الاعتماد`. Approved sections get
`.section-locked` and every control inside is disabled except the toggle. Two separate
approve/unapprove buttons must not come back.

## Token budget for the land analysis

`max_tokens` cannot simply be raised: **OpenRouter reserves the whole cap against the account
balance**, so an over-large value is refused with `402 "You requested up to N tokens, but can only
afford M"` — the call returns no content at all, even though the real answer would have been short.
Too low a cap truncates the JSON instead, and a truncated response is discarded whole
(partial parcel data is worse than none). Both ends therefore look identical to the user: every
field keeps its old value, i.e. "re-analysis did nothing".

`_call_land_analysis_model()` starts at `LAND_ANALYSIS_MAX_TOKENS` (16000), retries a truncated
response once with a higher cap up to `LAND_ANALYSIS_TRUNCATION_CEILING`, and walks the cap down
when the provider quotes an affordable figure.
The primary text/analysis model is `google/gemini-3.7-flash` (`GEMINI_TEXT_MODEL`).
Some OpenRouter fallbacks (especially Anthropic) reject `response_format: json_object` with
`output_format` content filtering, which used to abort the whole croquis run. The land call now
pins to Google with `allow_fallbacks: false` and retries once without JSON mode if that block
(or empty content) comes back.
`_get_chat_response_text()` also reads `reasoning` / `reasoning_content` when `content` is empty.
The live hosting proxy fabricates a 404 if `POST /api/extract-croquis` stays open for the whole
pipeline. Production therefore queues the job and the client polls `GET /api/extract-croquis/<id>`.
Keep the unittest path synchronous (`TESTING`) unless a test passes `background: true`.
`LAND_ANALYSIS_MIN_TOKENS`, `LAND_ANALYSIS_MODEL` are also env-overridable. Failures return a named
`failureReason` (`truncated` / `invalid_json` / `insufficient_credit` / `empty_response` /
`provider_blocked`) plus the raw `providerError`, and the frontend states that no field was
updated. Keep it that way — a silent rejection is indistinguishable from a broken button.

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

## Progress feedback for long operations

Every operation that may take noticeable time must show visible progress feedback to the user. This
includes AI text/image generation, analysis, uploads, downloads, exports, PDF generation, and other
long-running requests. Reuse the global loader/progress UI when it exists; otherwise provide an
inline progress state. Disable the triggering action while the operation is running, update the
current step when possible, and always clear the progress state on both success and failure. Do not
leave the user with a visually idle screen while a request is in flight. New agents must apply this
rule to every new workflow and generation action.
