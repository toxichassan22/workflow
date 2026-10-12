def _best_use_regulation_pages(draft):
    import fitz
    project = draft.get('draft_data') or {}
    pages = []
    for file_id in best_use_contract.decoded(project.get('land_documents_files_file_ids'), []):
        record = db.get_project_file(g.tenant_id, file_id)
        if not record or record.get('file_type') not in {'land_document', 'croquis'}:
            raise best_use_contract.ProposalError('regulatory_document_missing')
        if record.get('draft_id') and str(record['draft_id']) != str(draft['id']):
            raise best_use_contract.ProposalError('regulatory_document_scope')
        path = _resolve_project_file_storage_path(record, g.tenant_id)
        if not path:
            raise best_use_contract.ProposalError('regulatory_document_missing')
        try:
            with fitz.open(path) as document:
                if len(document) > 150:
                    raise best_use_contract.ProposalError('regulatory_document_too_large')
                for index, page in enumerate(document, 1):
                    pages.append({'documentId': file_id, 'page': index, 'kind': 'parcel', 'text': page.get_text()})
        except (OSError, RuntimeError, ValueError) as error:
            raise best_use_contract.ProposalError('regulatory_document_unreadable') from error
    if not pages:
        raise best_use_contract.ProposalError('regulatory_full_text_missing')
    pages.extend(best_use_regulations.local_pages(project, pages))
    return pages


def _best_use_extract_regulations(draft, data):
    project = draft.get('draft_data') or {}
    pages = _best_use_regulation_pages(draft)
    try:
        return best_use_regulations.extract(project, pages)
    except best_use_contract.ProposalError as error:
        if not str(error).startswith('regulatory_uses_complete'):
            raise
    if sum(len(page['text']) for page in pages) > 120000:
        raise best_use_contract.ProposalError('regulatory_full_text_too_large')
    prompt = json.dumps({'scope': best_use_regulations.parcel_scope(project, pages), 'documents': pages}, ensure_ascii=False)
    response = call_text_chat(
        'تفسير محدود للنصوص التنظيمية الأصلية. لا توجد فكرة مشروع أو دراسة سوق. '
        'حدد قائمة الاستعمالات الكاملة المنطبقة على القطعة دون تخمين السماح أو تجاهل نفي أو شرط. '
        'أعد JSON {"declarations":[{"documentId":"","page":1,"excerpt":"الاقتباس الكامل الحرفي"}]} '
        'أو {"declarations":[]} عند غياب قائمة كاملة. لا أرقام أو تصنيفات مخترعة.',
        prompt, max_tokens=2500, timeout=75, reasoning_effort='low', response_format={'type': 'json_object'},
        usage_ctx=_usage_ctx('best_use_regulations', data, draft_id=draft['id']))
    interpreted = _best_use_explore_provider(response)
    result = best_use_regulations.extract(project, pages, interpreted)
    result['interpretedDeclarations'] = [item for item in (interpreted.get('declarations') or [])
                                        if isinstance(item, dict)]
    return result


def _best_use_verify_regulations(draft):
    project = draft.get('draft_data') or {}
    stored = (project.get('best_use_explore_data') or {}).get('regulations') or {}
    if not best_use_workflow.current(project, 'regulations'):
        raise best_use_contract.ProposalError('regulatory_inputs_changed')
    interpreted = None
    if stored.get('requiresApproval') and stored.get('interpretedDeclarations'):
        interpreted = {'declarations': stored['interpretedDeclarations']}
    current = best_use_regulations.extract(project, _best_use_regulation_pages(draft), interpreted)
    if current['sourceDocuments'] != stored.get('sourceDocuments') or current['permittedUses'] != stored.get('permittedUses'):
        raise best_use_contract.ProposalError('regulatory_inputs_changed')
    return stored


def _best_use_price_page(url):
    pool, response, final_url = _pinned_https_get(url)
    if response is None:
        return None
    try:
        if response.status != 200:
            return None
        mime = str(response.headers.get('Content-Type') or '').lower()
        if not any(value in mime for value in ('text/html', 'text/plain', 'application/xhtml')):
            return None
        body = response.read(1024 * 1024 + 1, decode_content=True)
        if len(body) > 1024 * 1024:
            return None
        parser = best_use_prices.PageText()
        parser.feed(body.decode('utf-8', errors='replace'))
        return dict(parser.result(), url=url, finalUrl=final_url)
    except Exception:
        return None
    finally:
        response.release_conn()
        pool.close()


def _best_use_scan_prices(draft, regulation_data, data, progress=None):
    project = draft.get('draft_data') or {}
    uses = regulation_data['permittedUses']
    city, district = best_use_contract.text(project.get('city'), 150), best_use_contract.text(project.get('district'), 150)
    if not city:
        raise best_use_contract.ProposalError('price_city_missing')
    candidates = []
    for index, use in enumerate(uses):
        if progress:
            progress(20 + int(35 * index / max(1, len(uses))), 'prices')
        prompt = json.dumps({'city': city, 'district': district, 'use': use,
                            'maximumSearches': 2, 'maximumObservations': 6}, ensure_ascii=False)
        response, error = _call_market_study_model(
            'مسح أسعار صغير حي من الويب للاستخدام والمنطقة المحددين فقط. '
            'بحث بيع وبحث إيجار، لا دراسة سوق ولا بيانات مشروع أساسية. '
            'لا تسم إعلانًا متوسطًا. لا تؤلف أسعارًا ولا تستخدم ذاكرة الموديل. '
            'لكل سعر مقتطف حرفي من الصفحة يثبت السعر والاستخدام والمدينة والحي والعملة والوحدة والفترة. '
            'الحي غير المتوفر يبقى فارغًا ولا تنسب بيانات المدينة إلى حي. لا تحول سعر الوحدة إلى متر. '
            'تاريخ نشر السعر غير المثبت null. معرف الإعلان الحرفي في propertyId، أو اسم المشروع في entityName. '
            'أعد JSON {"observations":[{"use":"' + use + '","revenueMode":"sale|rent",'
            '"value":100,"currency":"SAR","unit":"sqm|unit|room","period":"oneOff|year|month|night",'
            '"city":"","district":"","url":"","excerpt":"","publishedAt":null,"propertyId":"","entityName":""}]}. '
            'إذا لم يوجد سعر موثق observations=[]؛ لا تعوض النقص بأرقام مفترضة.',
            prompt, max_tokens=4000, usage_ctx=_usage_ctx('best_use_price_scan', data, draft_id=draft['id']),
            search_context={'city': city, 'country': 'SA'}, max_search_results=6,
            search_budget={'max_uses': 2, 'max_total_results': 8, 'max_tool_calls': 3, 'timeout': 75})
        if error or not _market_search_ran(response):
            # Surface the provider's real reason — quota, timeout, malformed
            # tool call — instead of a bare code that reads as "no results".
            detail = (error or '').strip() or 'no_search_executed'
            raise best_use_contract.ProposalError('price_search_not_run: ' + detail[:240])
        parsed = _best_use_explore_provider(response)
        rows = parsed.get('observations')
        if not isinstance(rows, list):
            raise best_use_contract.ProposalError('price_scan_invalid')
        candidates.extend(row for row in rows[:6] if isinstance(row, dict) and row.get('use') == use)
    pages = []
    urls = list(dict.fromkeys(best_use_prices.clean_url(row.get('url')) for row in candidates))
    for index, url in enumerate(urls):
        if progress:
            progress(55 + int(8 * index / max(1, len(urls))), 'priceEvidence')
        if not url:
            continue
        page = _best_use_price_page(url)
        if page:
            pages.append(page)
    return best_use_prices.build_scan(uses, candidates, pages, db._utcnow().isoformat(), city, district)


def _best_use_guided_prices(project):
    market = best_use.read_object(project.get('market_study_data'))
    candidates, pages = [], []
    mapping = {'سعر المتر المربع': ('sale', 'oneOff'), 'Price per SQM': ('sale', 'oneOff'),
               'إيجار المتر السنوي': ('rent', 'year'), 'Annual Rent per SQM': ('rent', 'year')}
    for row in (market.get('competitors') or [])[:18]:
        if not isinstance(row, dict) or row.get('price_type') not in mapping:
            continue
        mode, period = mapping[row['price_type']]
        value = best_use_prices.number(row.get('price_value'))
        if value is None or value <= 0:
            continue
        urls = row.get('source_urls') or [row.get('source_url') or row.get('source')]
        if not isinstance(urls, list):
            urls = []
        for url in urls[:2]:
            url = best_use_prices.clean_url(url)
            if not url:
                continue
            page = next((page for page in pages if page['url'] == url), None)
            if page is None:
                page = _best_use_price_page(url)
                if page:
                    pages.append(page)
            if not page:
                continue
            for excerpt in re.split(r'\n+', page['content']):
                if not excerpt.strip():
                    continue
                for use, pattern in best_use_regulations.USE_TERMS.items():
                    if re.search(pattern, excerpt, re.I):
                        candidates.append({'use': use, 'revenueMode': mode, 'period': period, 'unit': 'sqm',
                            'value': value, 'currency': 'SAR', 'city': project.get('city') or '',
                            'district': row.get('district') or '', 'url': url, 'excerpt': excerpt[:5000],
                            'entityName': row.get('name') or '', 'publishedAt': page.get('publishedAt')})
    uses = sorted(set().union(*(best_use.MAIN_USES.get(kind, set()) for kind in best_use.project_types(project))))
    return best_use_prices.build_scan(uses, candidates, pages, db._utcnow().isoformat(),
                                     project.get('city') or '', project.get('district') or '', search_ran=True)
