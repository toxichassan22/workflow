# Frontend bundle assembly and cache-aware delivery.
# The SPA shell references two bundles instead of twenty part files, so a cold
# load costs four static requests (shell, i18n, one JS bundle, one CSS bundle)
# instead of twenty-two. The part files stay the source of truth: edit them,
# never the bundle, and never reference a part file from the shell. This tuple
# is the single order authority shared with scripts/verify-frontend.js and the
# test suites that pin FRONTEND_JS_ORDER.
FRONTEND_CSS_ORDER = (
    'base/01_preview_chat.css', 'base/02_tenant_pages.css',
    'base/03_the_view_model.css', 'base/04_export_responsive.css',
    'base/05_dashboard_viz.css', 'base/06_designer_activity.css',
    'base/07_package_slider.css', 'base/08_shell_chrome.css',
    'project-form/01_sections_changelog.css',
    'project-form/01a_location_maps.css',
    'project-form/02_fields_tables_rail.css',
    'project-form/03_timeline_board.css', 'project-form/04_financial_parking.css',
    'project-form/05_best_use.css', 'project-form/05a_market_summary_chat.css',
    'project-form/05b_market_study_tabs.css',
    'project-form/06_visual_concept_plans.css',
    'project-form/07_section_change_history.css',
)
FRONTEND_JS_ORDER = (
    '00-core.js', '01-nav-auth.js', '02-settings-branding/01_routing.js',
    '02-settings-branding/02_auth_boot.js',
    '03-executive-classification.js', '04-market.js', '04-market/01_scope.js',
    '04a-market-section.js',
    '05-market-competitors.js',
    '05-market-competitors/01_project_data_snapshot.js',
    '05-market-competitors/02_table_ux.js',
    '05a-market-jobs.js', '05a-market-summary-chat.js',
    '06-team.js', '07-project-form/01_form_sections.js',
    '07-project-form/02_section_versions.js', '07-project-form/03_best_use.js',
    '07-project-form/03a_best_use_calculator.js', '07-project-form/03b_best_use_explore.js',
    '07-project-form/04_draft_versions.js',
    '07-project-form/05_draft_branches.js',
    '07-project-form/06_draft_merge_decisions.js',
    '07-project-form/07_draft_live_sync.js',
    '08-location-maps/01_tables_approvals.js',
    '08-location-maps/02_catchment_edits.js', '09-financial/01_financial_format.js',
    '09-financial/02_formulas_calc.js', '09-financial/03_parking_planning.js',
    '10-financial-report-timeline/01_report_collect.js',
    '10-financial-report-timeline/02_timeline_sidebar.js',
    '10-financial-report-timeline/03_timeline_board.js', '11-land-croquis/01_croquis_survey.js',
    '11-land-croquis/01a_boundary_dimensions.js',
    '11-land-croquis/02_map_edits.js', '11-land-croquis/02a_map_approval_viewport.js',
    '11-land-croquis/03_interactive_map.js', '11-land-croquis/04_land_chat.js',
    '12-files-media/01_files_media.js',
    '12-files-media/02_visual_concept.js',
    '12-files-media/02a_visual_concept_sections.js',
    '12-files-media/02b_visual_concept_plan_state.js',
    '12-files-media/02c_visual_concept_plans_ui.js',
    '12-files-media/02d_visual_concept_plan_actions.js',
    '12-files-media/02e_plans_conflict_chat.js',
    '12-files-media/02f_plans_distribution_chat.js',
    '12-files-media/03_visual_concept_sketch.js',
    '12-files-media/04_visual_concept_references.js',
    '13-visual/01_visual_concept_page.js',
    '13-visual/02_slides_progress.js',
    '13-visual/03_tenant_slide_generation.js', '13-visual/04_generation_stop.js',
    '14-slides-gen/01_undo.js',
    '14-slides-gen/02_element_editing.js', '14-slides-gen/03_slide_regeneration.js',
    '15-slide-edit-chat/01_render_inline_edit.js',
    '15-slide-edit-chat/02_designer_chat.js',
    '15-slide-edit-chat/03_agent_checklist.js',
    '15-slide-edit-chat/04_slide_activity.js',
    '16-presentations-export/01_presentations.js',
    '16-presentations-export/02_admin_dashboard.js',
    '16-presentations-export/02a_admin_charts.js',
    '16-presentations-export/03_export_delivery.js',
    '16-presentations-export/04_sag_company_create.js',
    '17-admin-boot/01_training_rules.js',
    '17-admin-boot/02_users_roles.js',
    '17-admin-boot/03_training_chat_sessions.js', '18-landloom-ops.js',
    '18-landloom-ops/01_package_slider.js',
    '18-landloom-ops/02_join_requests.js', '18-landloom-ops/03_legal_content.js',
    '19-notifications.js',
)

_FRONTEND_BUNDLE_CACHE = {}


def _frontend_bundle_paths(kind):
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
    if kind == 'js':
        names, subdir, content_type = FRONTEND_JS_ORDER, 'js', 'application/javascript'
    elif kind == 'i18n':
        names, subdir, content_type = FRONTEND_I18N_ORDER, 'i18n', 'application/javascript'
    else:
        names, subdir, content_type = FRONTEND_CSS_ORDER, 'css', 'text/css'
    paths = [os.path.join(root, subdir, name) for name in names]
    return names, paths, content_type


def _frontend_bundle_signature(kind):
    names, paths, _content_type = _frontend_bundle_paths(kind)
    try:
        return tuple(
            (name, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            for name, path in zip(names, paths)
            for stat in (os.stat(path),)
        )
    except OSError:
        return None


def _frontend_bundle_asset_version(kind):
    signature = _frontend_bundle_signature(kind)
    if signature is None:
        return None
    digest = hashlib.sha256(repr(signature).encode('utf-8')).hexdigest()
    return digest[:20]

# The EN_AUTO exact-match map is split by screen so no single dictionary part
# approaches the 1,000-line limit, and pinned here because the shell must load
# the whole set before i18n.js reads window.__WFI18N_EN_AUTO. It ships as its own
# bundle for the same reason the app bundle does: eighteen blocking part
# requests on every page view is exactly what the bundle removed once.
FRONTEND_I18N_ORDER = (
    '01_dict_ar.js', '01a_dict_ar_extra.js', '01b_dict_en_extra.js', '02_dict_en.js',
    '03_dict_en_auto_core.js', '04_dict_en_auto_project.js',
    '05_dict_en_auto_financial.js', '06_dict_en_auto_location.js',
    '07_dict_en_auto_market.js', '08_dict_en_auto_team.js',
    '09_dict_en_auto_files.js', '10_dict_en_auto_slides.js',
    '11_dict_en_auto_presentations.js', '12_dict_en_auto_admin.js',
    '13_dict_en_auto_ops.js', '14_dict_en_auto_backend_fields.js',
    '15_dict_en_auto_backend_deck.js', '16_dict_en_auto_backend_changes.js',
    '17_dict_en_auto_backend_market.js', '18_dict_en_auto_backend_platform.js',
)


def _build_frontend_bundle(kind):
    """Concatenate part files in load order with markers, cached by content.

    The cache key is the per-file size/mtime/ctime signature, so editing a part file
    rebuilds the bundle on the next request with no build step and no restart.
    Returns (etag, raw_bytes, gzipped_bytes, content_type).
    """
    import gzip as _gzip
    import hashlib as _hashlib
    names, paths, content_type = _frontend_bundle_paths(kind)
    sig = _frontend_bundle_signature(kind)
    if sig is None:
        return None
    cached = _FRONTEND_BUNDLE_CACHE.get(kind)
    if cached and cached[0] == sig:
        return cached[1]
    chunks = []
    for name, path in zip(names, paths):
        with open(path, 'r', encoding='utf-8') as fh:
            content = fh.read()
        if kind in ('js', 'i18n'):
            # A leading semicolon keeps a file ending without one from merging
            # into the next file's first expression. The marker names the part
            # for stack traces and for the bundle-composition checks.
            chunks.append('\n;\n/*__PART:' + name + '*/\n' + content)
        else:
            chunks.append('\n/*__PART:' + name + '*/\n' + content)
    raw = (''.join(chunks)).encode('utf-8')
    etag = '"' + _hashlib.sha1(raw).hexdigest() + '"'
    bundle = (etag, raw, _gzip.compress(raw, 6), content_type)
    _FRONTEND_BUNDLE_CACHE[kind] = (sig, bundle)
    return bundle


def _serve_frontend_bundle(kind):
    bundle = _build_frontend_bundle(kind)
    if bundle is None:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    etag, raw, gzipped, content_type = bundle
    version = _frontend_bundle_asset_version(kind)
    immutable_url = bool(version and request.args.get('v') == version)
    cache_control = (
        'public, max-age=31536000, immutable' if immutable_url else 'no-cache'
    )
    if request.headers.get('If-None-Match') == etag:
        resp = app.response_class('', status=304, mimetype=content_type)
        resp.headers['ETag'] = etag
        resp.headers['Cache-Control'] = cache_control
        return resp
    use_gzip = 'gzip' in (request.headers.get('Accept-Encoding') or '').lower()
    body = gzipped if use_gzip else raw
    resp = app.response_class(body, mimetype=content_type)
    resp.headers['ETag'] = etag
    # Only a URL carrying the current source fingerprint can be cached for a
    # year. Older or hand-written unversioned URLs keep the revalidate policy.
    resp.headers['Cache-Control'] = cache_control
    resp.headers.add('Vary', 'Accept-Encoding')
    if use_gzip:
        resp.headers['Content-Encoding'] = 'gzip'
    return resp


@app.route('/assets/app.bundle.js')
def frontend_js_bundle():
    return _serve_frontend_bundle('js')


@app.route('/assets/i18n.bundle.js')
def frontend_i18n_bundle():
    return _serve_frontend_bundle('i18n')


@app.route('/assets/app.bundle.css')
def frontend_css_bundle():
    return _serve_frontend_bundle('css')
