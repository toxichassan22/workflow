# ─────────────────────────────────────────────────────────────────────────────
# Who draws a slide — the content renderer policy
# ─────────────────────────────────────────────────────────────────────────────
#
# One arbiter decides, for every slide, whether the page is composed by the
# model or rendered by a fixed template. The old rule was built from the source
# name alone, so every organised source became a static HTML page: the market
# summary shipped as twelve identical key/value rows, the study scope as a
# dense field list, and the risk register as a flat table — no design, no
# visual hierarchy, and the client editing the deck by hand.
#
# The decision is explicit here, and every entry carries its reason.

CONTENT_RENDERER_AI = 'ai'
CONTENT_RENDERER_DETERMINISTIC = 'deterministic'

# The model composes the page. Reason: the content is a reading, not a table —
# a set of findings whose hierarchy and order are a design decision, and a
# template can only flatten them into identical rows.
AI_DESIGNED_CONTENT_SOURCES = (
    # The market analysis: the nine findings of the study, the scope of the
    # data, and the one-block paragraph. The numbers travel with the prompt
    # and are never re-invented; only the composition belongs to the model.
    'market_study_data.summary',
    'market_study_data.scope',
    'market_study_data.one_block_summary',
    # The executive content: brief, opportunity, features.
    'executive_content.summary',
    'executive_content.opportunity',
    'executive_content.features',
    # The risk register: every risk against its mitigation, composed as a
    # designed page instead of a flat list.
    'executive_content.risks',
    'market_study_data.risk_analysis',
    'market_study_data.risk_register',
    'market_study_data.risks',
    'market_study_data.summary.risks',
)

# The page is drawn by a fixed template. Reason: the content is reference
# data the client signed off — a comparison, a register, a matrix, a report
# table, a map or a dated chart — and a model redrawing it can only lose rows.
DETERMINISTIC_CONTENT_SOURCES = (
    # The competitor comparison: one fixed layout (table + horizontal bars).
    'market_study_data.competitors',
    # The source register: the same names and links, every time.
    'market_study_data.sources',
    # The SWOT matrix: four quadrants, one page.
    'market_study_data.swot',
    # The plot boundary and the land/building summary.
    'land_boundary_diagram',
    'land_and_building_summary',
    # The dated Gantt of the project timeline.
    'timeline_table_data',
    # The location pages: the site data table and the approved site reading.
    # They carry the fields and the text the client signed off, and they share
    # one designed frame with the map pages — a model redrawing them shipped a
    # paragraph or a bare key/value grid on a white slide.
    'location_detail',
    'site_analysis',
)


def content_source_base(source):
    """The source name without its row range (``market_study_data.summary:0:4``)."""
    text = str(source or '').strip()
    return re.sub(r':\d+:\d+$', '', text)


def is_ai_designed_content_source(source):
    """True when the model composes this page instead of a template."""
    return content_source_base(source) in AI_DESIGNED_CONTENT_SOURCES


def slide_content_renderer(slide, project_data=None):
    """Decide who draws this slide: the model, or a fixed template."""
    slide = slide if isinstance(slide, dict) else {}
    source = str(slide.get('content_source') or '').strip()
    section = _slide_section_key(slide)
    chart_type = canonicalize_chart_type(slide.get('chart_type'))

    # 1. A source the model must compose wins over every template.
    if is_ai_designed_content_source(source):
        return CONTENT_RENDERER_AI

    # 2. The financial section is the approved report: its tables are the
    #    numbers the client signed off, so the model may not redraw them.
    if section == 'financial':
        return CONTENT_RENDERER_DETERMINISTIC

    # 3. The reference pages of the market section.
    if section == 'market' and content_source_base(source) in (
        'market_study_data.competitors',
        'market_study_data.sources',
        'market_study_data.swot',
    ):
        return CONTENT_RENDERER_DETERMINISTIC

    # 4. The maps, the plot boundary and the dated Gantt are drawn from the
    #    approved data, so the model can neither drop a map nor redraw a bar.
    if slide.get('type') in {'map_overview', 'map_landmarks', 'map_access', 'map_catchment'}:
        return CONTENT_RENDERER_DETERMINISTIC
    # The site-data page and the site-analysis summary are the two location
    # pages beside the maps: approved fields and an approved reading, drawn in
    # the same designed frame. A page sliced by paragraph range belongs here too.
    if slide.get('type') == 'site_specs' or source == 'location_detail':
        return CONTENT_RENDERER_DETERMINISTIC
    if source.startswith('site_analysis'):
        # Every page of the reading, including its paragraph-range slices.
        return CONTENT_RENDERER_DETERMINISTIC
    if source == 'land_boundary_diagram':
        return CONTENT_RENDERER_DETERMINISTIC
    if (
        (source == 'timeline_table_data'
         or str(slide.get('design_style') or '') == 'timeline'
         or section == 'timeline')
        and bool(parse_timeline_phases(project_data))
    ):
        return CONTENT_RENDERER_DETERMINISTIC

    # 5. The approved financial charts keep their own layout; a market page
    #    never becomes a chart, and a stale plan cannot turn one into a table.
    if section != 'market' and (
        chart_type in APPROVED_CHART_TYPES
        or source == 'land_and_building_summary'
    ):
        return CONTENT_RENDERER_DETERMINISTIC

    # 6. Everything else is composed by the model.
    return CONTENT_RENDERER_AI
