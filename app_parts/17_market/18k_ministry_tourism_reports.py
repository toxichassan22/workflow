"""Official Ministry of Tourism PDF retrieval for hospitality market studies."""


_market_summary_before_ministry_report_sync = _run_market_summary
_summary_research_prompt_before_ministry_reports = _summary_research_prompt
_SUMMARY_RESEARCH_GROUPS = tuple(
    {**group,
     'hosts': set(group.get('hosts') or set()) |
              ({'tourism.sa'} if group.get('key') == 'hospitality_and_tourism' else set())}
    for group in _SUMMARY_RESEARCH_GROUPS)


def _run_market_summary(data, tenant_id=None, progress=None,
                        evidence_pool=None, deadline=None, session=None,
                        resume_state=None, checkpoint=None, trace_writer=None):
    """Inject official Ministry reports into the existing evidence workflow."""
    payload = dict(data or {})
    profile = market_study.summary_activity_profile(payload)
    selected_kinds = profile.get('kinds') or set()
    active_hosts = _summary_research_activity_hosts(payload)
    ministry_allowed = any(
        str(host).lower() == 'mt.gov.sa'
        or str(host).lower().endswith('.mt.gov.sa')
        for host in active_hosts)
    if 'hospitality' not in selected_kinds or not ministry_allowed:
        return _market_summary_before_ministry_report_sync(
            data, tenant_id=tenant_id, progress=progress,
            evidence_pool=evidence_pool, deadline=deadline, session=session,
            resume_state=resume_state, checkpoint=checkpoint,
            trace_writer=trace_writer)

    prepared = _prepare_market_payload(payload, tenant_id)
    report = progress if callable(progress) else (lambda *_args: None)
    report(9, 'مزامنة تقارير وزارة السياحة الرسمية واستخراج صفحاتها ذات الصلة...')
    try:
        import tourism_report_sync
        selected_cities = (prepared.get('summaryScope') or {}).get('cities') or []
        city_names = [str(item.get('name') or '').strip()
                      for item in selected_cities if isinstance(item, dict)]
        if not city_names and prepared.get('city'):
            city_names = [str(prepared.get('city')).strip()]
        selected_districts = [
            str(district_name or '').strip()
            for item in selected_cities if isinstance(item, dict)
            for district_name in (item.get('districts') or [])
            if str(district_name or '').strip()]
        requested_district = str(prepared.get('district') or '').strip()
        if requested_district and requested_district not in selected_districts:
            selected_districts.append(requested_district)
        sync_result = tourism_report_sync.sync_ministry_tourism_reports(
            evidence_pool=evidence_pool,
            city=city_names, district=selected_districts,
            trace=trace_writer)
        if callable(trace_writer):
            trace_writer({
                'event': 'tourism_report_sync_result',
                'source_page': tourism_report_sync.PUBLICATIONS_PAGE,
                'reports_processed': len(sync_result.get('reports') or []),
                'pages_added': sync_result.get('pages_added', 0),
                'errors': sync_result.get('errors') or [],
            })
        enriched_data = dict(payload)
        enriched_data['_tourismReportEvidence'] = sync_result.get('reports') or []
        enriched_data['_tourismReportSyncErrors'] = sync_result.get('errors') or []
    except Exception as exc:
        if callable(trace_writer):
            trace_writer({'event': 'tourism_report_sync_failed',
                          'reason': str(exc)[:200]})
        enriched_data = dict(payload)
        enriched_data['_tourismReportEvidence'] = []
        enriched_data['_tourismReportSyncErrors'] = [str(exc)[:200]]
    return _market_summary_before_ministry_report_sync(
        enriched_data, tenant_id=tenant_id, progress=progress,
        evidence_pool=evidence_pool, deadline=deadline, session=session,
        resume_state=resume_state, checkpoint=checkpoint,
        trace_writer=trace_writer)


def _summary_research_prompt(payload, group, hosts, city, district='',
                             offer_lang='ar'):
    """Give the Ministry researcher extracted report pages and direct PDF links."""
    prompt = _summary_research_prompt_before_ministry_reports(
        payload, group, hosts, city, district, offer_lang=offer_lang)
    if group.get('key') != 'hospitality_and_tourism':
        return prompt
    try:
        import tourism_report_sync
        report_context = tourism_report_sync.format_research_context(
            (payload or {}).get('_tourismReportEvidence'), hosts,
            offer_lang=offer_lang)
    except Exception:
        report_context = ''
    if report_context:
        prompt += '\n\n' + report_context
    errors = (payload or {}).get('_tourismReportSyncErrors') or []
    if errors and any(str(host).lower() == 'mt.gov.sa'
                      or str(host).lower().endswith('.mt.gov.sa')
                      for host in hosts or []):
        prompt += ('\nتعذر جلب بعض ملفات تقارير الوزارة تلقائيًا؛ افتح الروابط الرسمية المتاحة '
                   'في قائمة المصدر وأكمل البحث فيها. لا تستنتج محتوى ملف لم يُفتح.\n')
    return prompt
