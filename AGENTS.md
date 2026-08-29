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

## Fonts

The company font is injected as `.slide,.slide *{font-family:… !important}` with the face carried
under a per-tenant alias (`tenant-managed-<id>`), from `/api/branding/font.css` in the preview and
from `build_font_css(embed=True)` in every export. Three things used to break that:

- **A slide could out-shout it.** A slide carrying `font-family` in its own `<style>` block with
  `!important` beat the injected rule in the preview, while every export stripped it — so the preview
  and the PDF disagreed. `stripSlideFontDeclarations()` in `index.html` is the mirror of
  `sanitize_slide_html_for_export()`; keep the two in step.
- **The prompt told the model to write a font name.** It received the display family
  (`'The Sans Arabic'`) while the loaded face is the alias, so the two never matched. The rules now
  forbid `font-family` in generated slides entirely.
- **A stored name with nothing behind it fell back silently.** Any `font_family` saved without a
  matching selection or file — including one the admin agent types — reached the last branch of
  `build_font_css()`, which emitted the bare name; the reader then got Tahoma with nothing to
  explain it. That branch now ships the bundled `platform-fallback-arabic` face behind the requested
  name.

**Arabic and Latin resolve independently**, and a script with no selection keeps the platform
default. The panel used to offer one dropdown holding exactly the two families that already are
those defaults, so choosing either changed nothing — measured identical text widths for both picks.
One font is chosen for the whole deck (owner's rule: a font applies to everything, not to text and
numbers separately), so `selectPresentationFont()` writes the chosen family to **both** scripts and
every weight, and falls back to the family's own faces when it ships only one script.

A system font is a legitimate choice (Arial for everything) but it is only a **name**: the export
runs on the server, which has neither Arial nor Tahoma, so `_managed_font_css()` appends the bundled
`platform-fallback-arabic` face whenever no shipped face covers Arabic. `font-status` then reports
`installed name only with shipped fallback` — the company's own face is a name, and that is stated
rather than dressed up as embedded.

`GET /api/branding/font-status` reports how the glyphs actually arrive: `embedded file`,
`served file`, `google web font` (needs the network) or `installed name only` (renders only where
that font is installed), plus the resolved face per script. The bundled faces come from
`fonts_bundle.json`, which is committed normally — `fonts/*.ttf|otf` are **Git LFS** files and may be
pointers on the server.

## Change history (who changed what)

`change_log` is the single history for a **presentation or a project file**, and
`change_tracking.py` produces its lines. `edit_log` came first, could only reference a presentation,
and stored one sentence such as «تعديل المحتوى»; it is still read for old rows and never written to.

- `describe_slide_changes(old, new)` names the difference: a title from one value to another, which
  phrases left and which arrived, a replaced image or map, an added or removed slide, and a styling
  change that left the text untouched. `describe_draft_changes` does the same per field, and names a
  data area (`financial_study_model` → «الدراسة المالية») instead of dumping its JSON.
- Every flow that changes either target writes one entry with `source` = `manual` or `ai`: the
  manual slide edit, inline text editing (quoting both sides), the AI designer chat (with the
  request and the tools it ran), draft save, section approval, version restore, creation, export and
  map regeneration. Add a `_record_change(...)` call to any new flow that mutates them.
- Read with `GET /api/presentations/<id>/edit-log` or `GET /api/project-draft/<id>/edit-log`.

## The admin agent (`/api/training-chat`)

It runs on `SLIDE_TEXT_MODEL` (`openai/gpt-5.6-sol`) with `reasoning_effort='medium'`, because it
changes company settings; it used to run on the fast text model with 2,000 tokens and no reasoning.

- **It asks instead of guessing.** The `ask` tool short-circuits the turn: if the reply contains it,
  no other action runs, and the response carries `awaitingAnswer`.
- **It reads what is attached.** `_agent_attachment_context()` passes an image to the model as an
  image reference and extracts the text of a PDF (or a text file) into the prompt. The old path
  uploaded the image to a separate endpoint, stored the analysis as training text, and ended the
  turn, so the agent answering the message never saw the file.
- **Fields:** it adds, edits and disables freely, and `delete_field` refuses anything that is not
  `is_custom` — an original field is disabled with `update_field {is_active: 0}`, never deleted.
- **Team library:** `list_team` / `add_team_entity` / `update_team_entity` / `delete_team_entity`
  act on `tenant_team_entities`, which is shared by every project file. Per-file exclusions stay in
  the project's own team screen.
- **The generation prompt** is `tenant_branding.generation_rules`, read and written with
  `get_generation_rules` / `set_generation_rules` and appended by `build_design_rules()` to every
  slide prompt and design edit. It is the only way to change the generation prompt without a code
  change, and it cannot license inventing facts, icons or rewritten numbers — that is stated in the
  appended block itself.

## Verification

There is no pytest; the suites use `unittest` and must be run as **modules from the repo root** (`tests/` is not an importable package, so `unittest discover` fails). Run them **one suite per process**: each redirects `db.DB_PATH` before importing `app`, so two suites in one command leave the second without tables.

```powershell
# Main suite — run this for any land/croquis/draft/AI change
D:\workflow\.venv\Scripts\python.exe -m unittest tests.test_meeting_requirements

# Other suites
D:\workflow\.venv\Scripts\python.exe -m unittest tests.test_location_data_parsing
D:\workflow\.venv\Scripts\python.exe -m unittest tests.test_project_draft_isolation
D:\workflow\.venv\Scripts\python.exe -m unittest tests.test_export_slide_sanitization
D:\workflow\.venv\Scripts\python.exe -m unittest tests.test_font_workflows
D:\workflow\.venv\Scripts\python.exe -m unittest tests.test_admin_agent
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
- **Access-road discovery must be deterministic.** `access_probe_points()` is fixed; it used to be
  shifted and rotated by `regen_seed`, so every regeneration snapped to different roads and the same
  site came back with different street names. The label also prefers the road names the user entered
  in the location section: `match_known_road_name()` normalises hamza/ال/ة and the
  «طريق»/«شارع» prefix, so Google's varying wording («طريق الأمير فيصل بن فهد») resolves to the
  stored name («الامير فيصل بن فهد»). Roads are de-duplicated on `_road_name_key()`, not on the
  snapped `place_id`, which differed per probe for one road.
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

## Financial figures are copied, never produced

Two states, and both are stated to the model explicitly — silence made it invent.

- **No study entered.** `collectFinancialStudyModel()` snapshots every control of the section plus
  the computed projection, so an untouched project still carries a ~35KB model of markup defaults
  and zeros. `financial_study_has_real_input()` (an entered row, or a real money/area figure — rates,
  years and counts are markup defaults and do not count) gates it: the payload drops
  `financial_study_model`, `_financial_data_note()` returns `FINANCIAL_ABSENT_NOTE` which forbids any
  financial slide or figure, and `strip_financial_slides()` removes financial slides that the
  planner, the fallback plan or the minimum-count padding proposed anyway.
- **Study entered.** Every figure is transcribed with the same value, unit, currency and decimal
  precision; thousands separators are display-only. No rounding, million/thousand conversion,
  recomputing, new ratio, row or year is allowed. Slide generation attaches
  `collectFinancialStudyReport()` to the generation-only copy of `financial_study_model`, so
  `_financial_data_note()` receives the same visible headings, labels, option text, metrics and
  complete tables as the financial PDF. The canonical plan splits report fields six rows per slide
  and tables eight rows per slide, adding a chart only when at least two numeric values exist.

Section order is `basic → location → land_croquis → contact → timeline → financial → team → market study → visual concept → executive content`.
The first four come from the `sectionOrder` loop; the remaining sections are appended in that order.
There is no conceptual-2D section inside بيانات المشروع. The old floor-design page is gone
entirely: `تصميم صور الطوابق`, its route, its state, and the `/api/floor-design/*` endpoints were
deleted, and 2D plans plus isometric now live as cards inside التصور البصري.

The **generated deck** has its own fixed order, enforced by
`slide_engine.normalize_presentation_plan()`: نبذة عن المشروع → مكونات المشروع → تحليل الأرض →
تحليل الموقع الجغرافي → تحليل السوق → الجدول الزمني → الدراسة المالية → تحليل SWOT وتحليل المخاطر
→ فريق العمل → المخططات → التصورات الخارجية → التصورات الداخلية → الملخص التنفيذي → الخاتمة.
Only sections backed by data or media are emitted. Every emitted section has one deterministic
`section_divider` showing its Arabic title only; no subtitle or English line. The deterministic
index lists those section starts plus the conclusion with their actual one-based page numbers.

`section-executive-content` is the last information section.
It gathers already-approved facts from every earlier section (basic, location, land/croquis,
timeline, financial, team, market study). Generated texts — brief, opportunity, features,
risks, executive summary — live in `draft_data.executive_content` via the hidden
`executive_content` input. SWOT is not generated here; it stays only inside دراسة السوق.
Risks must pair every stated risk with its mitigation method. The executive summary is a
structured Arabic document written by Gemini 3.7 Flash from the **full project facts** of
every earlier section (not from the other texts of this section).
Each text generates, edits, and regenerates on its own. The model may rephrase facts already
collected; it must not invent numbers, uses, or risks. Gate generation on the required earlier
sections, not on this section's own approval.

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

## What the slide model receives

`slide_engine.build_project_facts(project_data, tenant_id)` builds the `## بيانات المشروع` block for
`/api/generate-slide-single`, `/api/slide-plan` and `build_system_prompt()`. **Never go back to
dumping the draft as raw JSON with a character cut.** It used to be
`json.dumps(project_data)[:4000]` (and `[:6000]` for the plan). A real project file is ~230,000
characters, so the model saw 1.7% of it: the market study, the executive content, the team and most
of the location section were always past the cut, and *which* fields survived depended on the
draft's key order, so it changed between projects and after edits. The brief is 32,550 characters for
that same file — complete **and** smaller than the old raw dump.

- Facts are grouped by `db.FIELD_SECTIONS` and labelled from `PREBUILT_FIELDS` (`label`,
  `sort_order`), so adding a prebuilt field needs no change here. Unknown keys land in
  `بيانات إضافية`; `EXTRA_FIELD_LABELS` names the ones with no field entry.
- `market_study_data`, `executive_content`, `team_selection`, `timeline_table_data` are stored as
  **JSON strings inside the draft**, so they are decoded first — dumping them raw fed the model
  escaped `\"` soup.
- The team library lives in `tenant_team_entities` and the draft stores only ids, so `_team_facts()`
  resolves it with `db.get_team_entities(tenant_id)` minus `excluded`, plus `local`. Without the
  `tenant_id` the prompt carries no names at all.
- `PROMPT_SKIPPED_KEYS` is the only place noise is dropped: things sent by another route
  (`_financial_data_note`, `_timeline_data_note`, `_get_images_info`, the landmarks matrix, the slide
  plan), the previously generated deck, and machine artefacts of the land/map pipelines. Anything
  else is included, because a keep list would silently lose custom tenant fields.
- Multi-select values are stored under internal keys such as `audience::سكني`; `_readable_fact()`
  strips the `::` prefix and joins short lists inline.
- The client slims the generation payload with `slimGenerationProjectData()` (`index.html`,
  `GENERATION_PAYLOAD_DROPPED`). Generation is one request per slide, so the previous deck and the
  image state used to be re-uploaded for every slide: 196KB raw / 48.8KB gzipped per slide, which is
  4 chunk uploads each. It is now 111KB / 30.3KB, i.e. 3. Images travel in `images` and the plan in
  `slidePlan`, so `projectData` never needs them. It is a **drop** list, not a keep list, for the
  same reason.
- `test_slide_prompt_carries_every_section_instead_of_a_truncated_dump` and
  `test_generated_slide_request_sends_the_sections_and_not_the_previous_deck` guard both ends.

## Slide count is not capped

Owner's rule: the planner decides how many slides a project needs, and the only hard rule is a
minimum. Three separate things used to bind it, and together they made every deck look like it had
a fixed slide count:

- **A stored ceiling trimmed the plan.** `max_slides` (30 by default) was passed to the planner as
  «التزم بحد الشرائح … كحد أقصى» — contradicting `SLIDE_PLAN_PROMPT`, which calls the upper end
  open — and `_execute_slide_plan` then trimmed the surplus slides away. `resolve_slide_bounds()`
  now returns `SLIDE_COUNT_OPEN` as the maximum and ignores the stored `max_slides`; the trim block
  is reachable only for a tenant with `lock_slide_count`, which is the one honest way to fix a count
  exactly. The «أقصى عدد شرائح» settings input is gone, and the admin agent stores a requested
  number as `default_slide_count` + `min_slides`, never as a ceiling.
- **The plan request was capped at 6,000 tokens.** The plan is one JSON document holding every
  slide, so a large project's plan was cut mid-object, `parse_slide_plan` raised, and
  `build_fallback_plan()` took over. That is why a real file came out as exactly the generic 15
  slides (`الغلاف`, `الفهرس`, `نظرة عامة على المشروع` … `شكراً لكم`) — those titles are the
  fallback's, not the model's. It is now 40,000 tokens with a 600s timeout.
- **A regenerated file reused its saved plan.** `directGenerateProposalFile()` asked for a plan only
  `if (!tenantSlidePlan)`, and opening a draft restores the previous plan, so pressing «توليد العرض»
  again rebuilt the same structure and count regardless of how the project had changed. It now
  always re-plans.

A fallback plan carries `plan.source === 'fallback'` (plus `planSource` on the response) and both
the banner and the plan panel state it. Never let the fallback pass as the model's proposal — the
generic titles are the signal that the planner failed.

**The stage is emptied before a regeneration.** `clearTenantSlidesStage()` runs before the plan
request; rendering the file's saved slides there showed the old deck for the whole planning wait.
Slides are still generated one request at a time in a sequential loop, so time and cost grow
linearly with the count.

**The structure is not a client-facing object.** Owner's rule: the client has no contact with it.
There is no plan panel, no editable plan titles, and no button that builds or rebuilds the plan on
its own — the «تحديث الهيكل المقترح» sidebar button, `generateSlidePlanOnly()`,
`renderTenantSlidePlan()`, `updatePlanSlideTitle()`, `regenerateTenantSlidePlan()` and the
`.tenant-slide-plan-card` styles are all gone. The plan is produced inside
`directGenerateProposalFile()` and travels to the server as `slidePlan`; do not re-expose it.
`test_the_slide_structure_is_not_client_facing` guards this.

## Never advertise an image that does not exist

`##STREET_VIEW_1..4##` was listed in the design rules, in `SLIDE_PLAN_PROMPT` (type `site_photos`)
and in `_get_images_info`, but **nothing produces a street photograph**: the Street View fetch in
`maps_service.get_street_view()` is only reachable from `run_regeneration_all.py`, and `streetview`
is never in `enabled_maps`. The model duly built a «قراءة بصرية للموقع» slide out of four such
tokens, `_replace_data_placeholders`'s catch-all blanked them, and the slide shipped as **four empty
frames**. Three rules came out of it:

- `slide_engine.NO_STREET_VIEW_RULE` is appended to the plan prompt, the slide prompt, the location
  note and `_get_images_info`. The `site_photos` type is gone, and `strip_street_view_slides()`
  drops one that an old draft still carries.
- **State what is missing.** `_get_images_info` names every map as available or forbidden and does
  the same for the cover, external/interior images, land photos, team logos and 2D plans. Land-photo
  descriptions, plan titles/descriptions and visual captions travel in `images`; team logo file ids
  are resolved and published server-side. The plan emits one clear image per slide (two only when
  explicitly appropriate), never a compressed four-image moodboard before the conclusion.
- **An unresolved image token never becomes an empty box.** `IMAGE_TOKEN_RE` is skipped by the
  catch-all replacer, and `_drop_unresolved_image_placeholders()` (end of `finalize_slide_html` and
  of `resolve_designer_chat_placeholders`) removes the `<img>` or the `background-image` that
  carried it, plus any `src=""` / `url()` left by an older pass. An image that does not exist must
  leave nothing behind, not a hole.

## The export must contain the whole deck

Five separate faults each dropped pages, and every one of them reported success:

- **A broken slide ended the walk.** `extract_slide_elements()` required a balanced `</div>` per
  slide and **`break`ed** when it could not find one, so one model-generated slide with a missing
  closing tag dropped every slide after it — 21 in, 10 out. Each slide is now bounded by the next
  slide's opening tag and repaired in place, so a broken slide can only damage itself.
- **`\bslide\b` is not a class match.** A hyphen is a word boundary, so `slide-inner`,
  `slide-footer` and `slide-title` all matched, and with the bounded reader one real slide became
  three fragments: an empty `<div class="slide"></div>` plus its own inner blocks. `_SLIDE_OPEN_RE`
  captures the class attribute and the token list is checked for exactly `slide`.
- **Balancing only `<div>` does not repair a table.** Two live slides left `<table>`, `<tbody>` and
  `<tr>` open. The source still contained 50 `.pdf-export-page` strings, but Chromium's combined DOM
  had only 48 wrappers in total and 25 direct children because the HTML parser nested the remaining
  deck inside those tables. Recovery must load each original slide string into its own document;
  querying or cloning wrappers from the already-corrupted combined DOM cannot recover what vanished.
- **An out-of-flow slide gets no page.** A slide carrying `position:absolute` (or `float`) in its
  own inline style leaves the flow and shares a page: measured 5 pages for 6 slides with one such
  slide, and **1 page for 6** when all of them had it. A root inline declaration with `!important`
  also beats the export stylesheet. Every slide is therefore placed inside a generated
  `.pdf-export-page`; that trusted 1280 by 720 wrapper owns the page break even when the slide inside
  it remains absolute, floated or transformed.
- **A global page layout combines separate slides.** A `<style>` inside one slide still applies to
  the whole document. `body{display:grid;grid-template-columns:1fr 1fr}` or `columns:2` produced
  exactly **25 pages for 50 slides** while every slide itself measured 1280 by 720. The generated
  document gives its body the unique `pdf-export-root` id, resets it to one block column, and puts
  only the trusted `.pdf-export-page` wrappers in that flow. Slide CSS no longer owns pagination.

`_verify_pdf_page_count()` then **raises** when the produced file has fewer pages than the deck has
slides: a short file is a failed export, not a smaller export. Before that error can leave
`generate_pdf()`, each original slide string is written to its own temporary HTML file, loaded in
Chromium, printed, and merged. Do not append a query string to one reused `file://` path: it works on
Windows Chromium and fails on the Linux host. Separate files keep the browser's CSS, images and fonts
without trusting the corrupted combined DOM. The merged file lives under `/tmp`, while `outputs/` can
be another filesystem; `_replace_output_file()` stages a copy beside the destination before
`os.replace()` so Linux does not fail with `Invalid cross-device link`. Rebuilding a short Chromium
file with PyMuPDF completed
the page count but lost the presentation design, so PyMuPDF is used only when Chromium fails before
writing any PDF. Once Chromium writes a short file, an isolated-render failure is returned as an
error rather than silently handing back a plain document. The PyMuPDF fallback still renders one
isolated slide per page; sending the whole deck through it produced 7 pages for 6 simple slides and
could vary in either direction. `tests/test_export_slide_sanitization.py` guards all of it, and the old
`test_ignores_unbalanced_slide` (which asserted the dropping) is gone.

The failure also has to be actionable, so a page count alone is not enough:

- `_export_html_from_slides()` inspects **each** entry of `slides_data`: an entry whose html has no
  root `.slide` is wrapped in one (it would otherwise print as loose content sharing a neighbour's
  page), an empty one and one carrying several are reported, and the notes travel with the 500.
- `generate_pdf()` measures the printed layout with `page.emulate_media(media='print')` and
  `describe_slide_layout_faults()` names every slide that cannot own a page —
  `الشريحة 7 (position:absolute، height:360px)` — in the log and in the error text.
- `GET /api/build` reports the commit the live code came from. «هل نزل الإصلاح؟» previously had no
  answer for a server-side fix; the frontend could at least be checked by fetching the page and
  grepping for a new function name.

## The designer chat has a memory

`/api/designer-chat` used to send the planner nothing but the current message: it asked
«أي شريحة؟», the user answered «8», and that answer reached a model which had never asked — so it
asked again. Now:

- The client keeps `tenantDesignerMessages` (with each turn's slide numbers),
  `tenantDesignerChatMemory` and `tenantChatFocusIndexes`, sends them as `history` / `memory` /
  `focusIndexes`, and stores them in the draft under `designerChat` — `restoreDesignerChat()` brings
  the conversation back when the file is reopened instead of wiping it.
- The server keeps `DESIGNER_CHAT_VERBATIM_TURNS` (10) turns verbatim and folds anything older into
  one Arabic summary once it passes `DESIGNER_CHAT_MEMORY_CHARS`, so a long session cannot push the
  actual request out of context. It returns the updated `memory` and `focusIndexes` every turn.
- **Sticky slide focus:** a message with no slide number falls back to `focus_indexes` (the slides
  the previous turn was about) before falling back to the current slide, and the prompt says so.
- `designerChat` is in `GENERATION_PAYLOAD_DROPPED`, `PROMPT_PREVIOUS_OUTPUT` and
  `DRAFT_BOOKKEEPING_KEYS`: it never reaches a slide prompt and never counts as draft content.

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
  `visual_concept` input plus `tenantCreativeImages`. The home page has four
  cards: `التصور الخارجي` (`cover`, `right`, `left`, `top`, `back`),
  `التصور الداخلي`, `المخططات 2D`, and `مخططات الإيزومتريك`. The last two came from
  the deleted floor-design page. الإيزومتريك is entirely under construction — its
  card is `disabled` and `#visualConceptIsometricView` states that only. المخططات 2D
  is client uploads only: an unbounded `plans2d` array (capped at
  `VISUAL_CONCEPT_MAX_PLANS = 30`) where each entry carries a client-written title and
  description, `normalizeVisualConceptPlans()` drops entries with no image, and
  `#visualConceptPlansGenerateButton` stays `disabled` because AI generation for plans
  is not built yet. Plans are flat records, not fixed slots, so they have no
  approval toggle and no prompt. The four exterior
  angle titles are client-editable and persist on each slot (`slot.label`); defaults
  remain يمين / شمال / فوق / خلف until changed. Every visual image also has a required
  client caption (`slot.caption`) separate from the generation prompt. The client may
  upload their own image into any of the five exterior slots, or generate it.
  Internal images are 1–4 per actual financial-study component (`interior_<id>::n`),
  chosen from a dropdown; the client may upload or generate each one. Count is
  optional — 1 is enough, 4 is the cap. Each component still has optional
  interior references. Clicking a card opens that group's workspace. Chat
  revision must edit the current prompt in place, never rewrite it from
  scratch, unless the user explicitly asks to replace the prompt. Legacy
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
- **A `blob:` URL must never be stored.** An uploaded slot image was previewed from
  `URL.createObjectURL()` and that URL went straight into `visual_concept`, so every image the
  client had uploaded rendered broken the moment the file was reopened in another tab or another
  day — and the export shipped a reference the server could never read. Uploads now go through
  `publishProjectFileImageUrl()` → `POST /api/project-files/<id>/publish-image`, which copies the
  stored file into `/uploads/creative/<tenant>/` exactly like a generated image, and it throws
  rather than falling back to a blob URL. `durableImageUrl()` drops any stored `blob:` on load,
  `repairVisualConceptStoredImages()` republishes it from `sourceFileId` / `plan.fileId` and heals
  the file in place, and `_visual_concept_cover_image()` ignores a `blob:` cover so it falls back to
  `coverFileId`. `/api/project-files/<id>` needs an Authorization header, so it can only ever feed a
  session thumbnail (`attachProjectFileThumbnail`) — never a saved value.
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
- **A save can never empty a draft, and the server enforces it.** `POST /api/project-draft` used to
  store whatever arrived and answer `success`, so a request whose `draftData` was absent or `{}`
  wrote `{}` over the row — and because a payload with no `draftId` lands on the actor's *newest*
  draft, one stray request emptied whichever project the user had just been working on, with no
  error anywhere. That is the bug behind "the draft emptied itself while I was generating". The
  endpoint now rejects an absent/empty `draftData` (400), `db.save_project_draft()` raises
  `DraftOverwriteRefused` (409, `DRAFT_EMPTY_OVERWRITE`) rather than blanking a draft that still
  holds content, and a save that halves the number of filled fields prints a `[DRAFT SAVE]` line
  with the dropped keys and byte counts. `_has_content()` ignores `DRAFT_BOOKKEEPING_KEYS`
  (`pageDrafts`, `map_styles`, `draftId`, …) and looks inside containers, so
  `{'tenantCreativeImages': {'cover': '', 'moodboard': []}}` still counts as empty. Emptying a
  project is `DELETE /api/project-draft/<id>`, never a save. Do not relax these guards.
- **`collectTenantFormData()` only trusts a form that was filled.** `renderTenantProjectForm()`
  clears `form.dataset.projectFormFilled`, `hydrateTenantProjectForm()` sets it as its very last
  statement, and `startTenantProject()` sets it because a new project is legitimately blank. While
  it is unset, `collectTenantFormData()` drops blank values for keys where `tenantProjectData` still
  has one. So hydration that throws part-way — `storeLandDocumentAnalysis()`, `renderProjectTeam()`,
  `hydrateFinancialStudyModel()` all run before the value loop — can no longer turn into a save that
  blanks every field. Keep the marker as the last line of hydration; moving it earlier defeats it.
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
the start year only. If the timeline has no named phases, do not rebuild/wipe `scheduleTable`;
keep the hydrated financial stages. **That guard covers the stage table only.** It used to cover
`developmentYears` as well, so a timeline that said 5 سنوات left «مدة تطوير المشروع» showing its
own default 4 — in a read-only box whose hint says the number comes from the timeline. The year
count is the timeline's own field and mirrors regardless of the stage list, and the
`calculateAll()` at the end of `syncFinancialFromTimeline()` must also run on the early-return
paths (`recalculate()`), or the mirrored duration never reaches «إجمالي سنوات المشروع»,
«سنة بدء التشغيل» or the cashflow.

**A mirrored read-only input must never show a figure its source does not have.** `landArea`,
`coverageRate`, `floorCount` and `developmentYears` ship with `value=""`; they used to ship with
`70000`, `35`, `1` and `4`, so a fresh study opened on invented land data the user could not edit
and every derived number was built on it. `mirrorApproved()` in `syncFinancialFromLand()` also
writes the empty string when the source is cleared — the old `if (area > 0)` form left the last
value behind. The same applies to any field added to `TENANT_CLIENT_ENTERED_LAND_FIELDS` or to a
new mirror: carry the source's emptiness, do not invent a placeholder number.

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

**The exported PDF is the screen, verbatim, laid out as tables — nothing else changes.** The owner
asked for exactly that. `collectFinancialStudyReport()` (client, export only — never stored in the
draft) walks `#section-financial-calc` in DOM order and sends `report.parts`: `heading` /
`fields` / `table` entries carrying the **visible label** of each input, the **selected option
text** of each list, and the **displayed figure**. `_financial_screen_sections()` renders those
as-is. Do not reintroduce a server-side label map or number reformatter on that path: the report
used to be rebuilt from `FINANCIAL_RESULT_LABELS` / `FINANCIAL_COLUMN_LABELS`, so «هل وحدات
المشروع بيعية أم تأجيرية؟» printed as «طبيعة الإيرادات» and its value printed as the raw option
id `mixed`. Those maps stay only for drafts saved before `report.parts` existed.

A field is skipped when it is off on screen: `hidden`, `.conditional-off`, `.dynamic-off`,
`.hidden`, or `display:none`. Those are the same markers `applyConditionalVisibility()` and
`setWrapVisible()` set, so no `getComputedStyle` walk is needed.

**A figure needs an LTR cell.** `money()` writes `-13,125,000`, and in an RTL cell the bidi
algorithm has no strong direction to attach the leading sign to, so it takes the paragraph
direction and prints as `13,125,000-`. `_financial_report_cell()` emits `<td dir="ltr">` for cells
that are pure figures, and the screen plus the print window use `unicode-bidi: plaintext` on `td`,
`input` and `.metric strong`. Do not apply either to a cell that can hold Arabic prose, and do not
switch to `direction: ltr` on all cells. The PyMuPDF engine needs none of this: it applies no bidi,
so `place()` already draws the sign first.

The report is deliberately **monochrome** (`_financial_report_document`). It used to be painted
from branding, and a light `secondary_color` printed the whole label column as pale text on a pale
tint — unreadable. Do not put branding colours back into it.

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

All section statuses live in **one JSON column**, so never write them with parallel requests:
`approveAllSections()` fired eight calls at once, each read the same snapshot, and the last write
won — the screen showed eight approved sections while the database had stored four. Bulk changes go
through `sectionStatuses` on `POST /api/project-draft/section-status`, and
`update_draft_section_statuses()` writes conditionally on the value it read and retries, so a race
between single-section calls cannot drop one either.

`renderTenantProjectForm()` must call `applySectionStatuses(initialStatuses)`. It used to compute
that map and throw it away, so a section nobody opened had no stored status at all — and
`request_project_draft_approval()` only walks the stored map, so the file could be submitted for
approval with that section never approved.

The regulated activity list is shown next to the components table
(`#componentsAllowedUsesNote`, fed by `renderComponentsAllowedUsesNote()` from `allowed_uses` and
`land_use_status`). That is data, not guidance, so the no-how-to rule does not apply to it.

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

**Any AI call that can outlast the hosting proxy must be a queued job, not a held request.** The
three that are: `POST /api/extract-croquis`, `POST /api/market-study/{competitors,summary}`, and
`POST /api/slide-plan` — the last one because the planner reads every section, so its prompt runs to
tens of thousands of characters and the answer takes minutes; the browser reported
`CLIENT_REQUEST_TIMEOUT` for plans the server had produced. Each answers `202 {jobId}` and the
client polls (`GET /api/slide-plan/jobs/<id>`, 2.5 s, 10 min ceiling). `_write_job` / `_read_job`
are the shared tenant-scoped file store; `.plan_jobs` and `.market_jobs` are the namespaces. Keep
the unittest path synchronous (`TESTING`) unless a test passes `background: true`.

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
