

def _job_dir(namespace, tenant_id):
    path = os.path.join(UPLOADS_DIR, namespace, str(tenant_id))
    os.makedirs(path, exist_ok=True)
    return path


def _job_path(namespace, tenant_id, job_id):
    safe_job_id = str(job_id or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{6,80}', safe_job_id):
        raise ValueError('Invalid job id')
    return os.path.join(_job_dir(namespace, tenant_id), f'{safe_job_id}.json')


def _write_job(namespace, tenant_id, job_id, payload):
    path = _job_path(namespace, tenant_id, job_id)
    payload = dict(payload)
    payload['updatedAt'] = time.time()
    payload['pid'] = os.getpid()
    # The restart-resume sweep re-dispatches from the persisted request, so `payload`/`actor`
    # must survive every status write — status updates replace the document wholesale and would
    # otherwise drop them the moment the worker reports progress.
    if 'payload' not in payload or 'actor' not in payload:
        try:
            existing = _read_job_file(path)
        except Exception:
            existing = None
        if isinstance(existing, dict):
            for sticky in ('payload', 'actor'):
                if sticky not in payload and sticky in existing:
                    payload[sticky] = existing[sticky]
    body = json.dumps(payload, ensure_ascii=False)
    # Polling can be served by another Gunicorn worker, so a process-local lock alone cannot
    # stop that worker from opening the file between truncate() and the final write. Publish a
    # fully flushed sibling file with os.replace(); readers then see either the old complete JSON
    # or the new complete JSON, never a partial document that looks like job_not_found.
    temp_path = f'{path}.tmp-{os.getpid()}-{threading.get_ident()}-{time.time_ns()}'
    with _MARKET_JOB_LOCK:
        try:
            with open(temp_path, 'w', encoding='utf-8') as fh:
                fh.write(body)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            last_error = None
            for _ in range(8):
                try:
                    os.replace(temp_path, path)
                    return
                except OSError as error:
                    last_error = error
                    time.sleep(0.03)
            if last_error:
                raise last_error
        finally:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass


def _read_job_file(path):
    try:
        with open(path, encoding='utf-8') as fh:
            payload = json.load(fh)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _read_job(namespace, tenant_id, job_id):
    path = _job_path(namespace, tenant_id, job_id)
    if not os.path.isfile(path):
        return None
    with _MARKET_JOB_LOCK:
        payload = _read_job_file(path)
    return payload if isinstance(payload, dict) else None


def _resume_interrupted_jobs():
    """Re-dispatch persisted jobs whose owning process died.

    Every `_write_job` stamps the writing pid. A job still 'queued' or
    'running' under a foreign pid at startup belongs to a dead worker —
    Gunicorn respawns one — so this worker claims it and re-runs the stored
    request. A live sibling's job keeps that worker's pid and is left alone.
    Orphans that predate resumable payloads are closed as failed once stale
    so clients stop polling a job that will never finish.
    """
    my_pid = os.getpid()
    orphan_fail_seconds = int(os.environ.get('JOB_ORPHAN_FAIL_SECONDS') or 900)
    resumed = 0
    for namespace in ('.market_jobs', '.plan_jobs', '.land_jobs', '.slide_jobs',
                      '.designer_chat_jobs'):
        base = os.path.join(UPLOADS_DIR, namespace)
        if not os.path.isdir(base):
            continue
        for tenant_dir in os.listdir(base):
            tenant_path = os.path.join(base, tenant_dir)
            if not os.path.isdir(tenant_path):
                continue
            for name in os.listdir(tenant_path):
                if not name.endswith('.json') or '.tmp-' in name:
                    continue
                job_id = name[:-5]
                try:
                    job = _read_job(namespace, tenant_dir, job_id)
                except Exception:
                    continue
                if not isinstance(job, dict):
                    continue
                if str(job.get('status') or '') not in ('queued', 'running'):
                    continue
                if job.get('pid') == my_pid:
                    continue
                if not isinstance(job.get('payload'), dict):
                    try:
                        age = time.time() - float(job.get('updatedAt') or 0)
                    except (TypeError, ValueError):
                        age = orphan_fail_seconds + 1
                    if age > orphan_fail_seconds:
                        try:
                            _write_job(namespace, tenant_dir, job_id, {
                                'status': 'failed',
                                'success': False,
                                'error': 'توقفت المهمة عند إعادة تشغيل الخادم',
                                'failureReason': 'job_interrupted',
                            })
                        except Exception:
                            pass
                    continue
                _write_job(namespace, tenant_dir, job_id, {
                    **job,
                    'status': 'running',
                    'success': True,
                    'resumed': True,
                    'message': 'استُؤنفت المهمة بعد إعادة تشغيل الخادم',
                })
                if _redispatch_job(namespace, tenant_dir, job_id, job):
                    resumed += 1
    return resumed


def _redispatch_job(namespace, tenant_id, job_id, job):
    """Spawn the worker matching a persisted job's namespace."""
    payload = job.get('payload') or {}
    actor = job.get('actor') if isinstance(job.get('actor'), dict) else None
    try:
        if namespace == '.market_jobs':
            kind = str(job.get('kind') or payload.get('kind') or '')
            if kind not in ('competitors', 'summary'):
                return False
            threading.Thread(
                target=_market_job_worker,
                args=(current_app._get_current_object(), tenant_id, kind,
                      payload.get('data') or {}, job_id),
                kwargs={'actor': actor},
                daemon=True,
            ).start()
            return True
        if namespace == '.plan_jobs':
            branding = db.get_branding(tenant_id)
            if not branding:
                return False
            threading.Thread(
                target=_slide_plan_job_worker,
                args=(current_app._get_current_object(), tenant_id,
                      payload.get('projectData') or {}, dict(branding),
                      payload.get('images') or {}, job_id,
                      payload.get('targetSectionKeys')),
                daemon=True,
            ).start()
            return True
        if namespace == '.land_jobs':
            threading.Thread(
                target=_land_job_worker,
                args=(current_app._get_current_object(), tenant_id,
                      payload.get('data') or {}, job_id),
                daemon=True,
            ).start()
            return True
        if namespace in ('.slide_jobs', '.designer_chat_jobs'):
            if not isinstance(actor, dict) or not actor:
                return False
            # These workers authenticate by replaying the caller's Authorization
            # header; a persisted bearer token would be a stored secret, so the
            # resume path mints a fresh one for the recorded actor instead.
            token = auth.create_token(
                tenant_id, '',
                user_id=actor.get('user_id'),
                user_name=actor.get('user_name'),
                user_role=actor.get('user_role'))
            target = (_run_slide_generation_job if namespace == '.slide_jobs'
                      else globals().get('_designer_chat_run_job'))
            if target is None:
                return False
            threading.Thread(
                target=target,
                args=(current_app._get_current_object(), tenant_id,
                      payload.get('data') or {}, job_id, f'Bearer {token}'),
                daemon=True,
            ).start()
            return True
    except Exception as exc:
        print(f'[JOB RESUME] failed to re-dispatch {namespace}/{job_id}: {exc}')
    return False


_JOB_INTERNAL_KEYS = ('payload', 'actor', 'pid')


def _public_job(job):
    """Job file minus server-only internals before it is returned to a client."""
    if not isinstance(job, dict):
        return job
    return {k: v for k, v in job.items() if k not in _JOB_INTERNAL_KEYS}


def _market_job_dir(tenant_id):
    return _job_dir('.market_jobs', tenant_id)


def _market_job_path(tenant_id, job_id):
    return _job_path('.market_jobs', tenant_id, job_id)


def _write_market_job(tenant_id, job_id, payload):
    _write_job('.market_jobs', tenant_id, job_id, payload)


def _read_market_job(tenant_id, job_id):
    return _read_job('.market_jobs', tenant_id, job_id)


MARKET_SEARCH_ENGINE = (os.environ.get('MARKET_SEARCH_ENGINE') or 'auto').strip() or 'auto'


def _market_search_ran(res):
    """Whether the response proves a web search actually executed.

    ``usage.server_tool_use.web_search_requests`` counts executed queries and
    ``url_citation`` annotations carry the retrieved pages; a parseable JSON
    with neither is the model answering from memory, which used to be accepted
    silently as a sourced study.
    """
    if not isinstance(res, dict):
        return False
    usage = res.get('usage') or {}
    tool_use = usage.get('server_tool_use') or {}
    try:
        requests_count = int(tool_use.get('web_search_requests') or 0)
    except (TypeError, ValueError):
        requests_count = 0
    return requests_count > 0 or bool(_market_citation_urls(res))


def _call_market_study_model(system_prompt, user_content, max_tokens=None, usage_ctx=None,
                             search_context=None, server_tools=True, max_search_results=8):
    """Search-backed market call with JSON, provider, and credit fallbacks.

    ``server_tools=False`` drops the openrouter:web_search tool — Gemini answers
    it with MALFORMED_FUNCTION_CALL when the prompt asks for several lookups, so
    bounded tasks (logo discovery) run on the always-on Exa plugin alone.
    """
    cap = max(2000, int(max_tokens or MARKET_STUDY_MAX_TOKENS))
    # One search cannot price several competitors, so the model is allowed a search per
    # competitor plus the market-wide ones; without max_uses it settled for a single call
    # and left every price blank.
    search_params = {'engine': MARKET_SEARCH_ENGINE,
                     'max_results': 10, 'max_uses': 10, 'max_total_results': 60,
                     # Exa's adaptive highlight is ~2-4K chars — usually too thin
                     # to carry the listing's price. Pin the excerpt budget to
                     # the 8K _market_citation_pages keeps.
                     'max_characters': 8000}
    # The engine runs the provider's native search on 'auto' — Google grounding for
    # Gemini — and user_location biases those results toward the project's city
    # (native search only; Exa ignores it, so the query itself names the city).
    context = search_context if isinstance(search_context, dict) else {}
    city = str(context.get('city') or '').strip()
    country = str(context.get('country') or 'SA').strip() or 'SA'
    if city or country:
        search_params['user_location'] = {'type': 'approximate', 'city': city, 'country': country}
    tools = [{
        'type': 'openrouter:web_search',
        'parameters': search_params,
    }]
    # The server tool leaves the search decision to the model, which could skip
    # it entirely and answer from memory — and on Google, `auto` native
    # grounding is model-decided too, so it silently does nothing. The `web`
    # plugin with engine `exa` runs the search on OpenRouter's side for EVERY
    # request and injects the retrieved pages — real grounding is guaranteed.
    plugin = {
        'id': 'web',
        'engine': (os.environ.get('MARKET_SEARCH_PLUGIN_ENGINE') or 'exa').strip() or 'exa',
        'max_results': max(4, min(20, int(max_search_results or 8))),
    }
    plugins = [plugin]
    provider = {'order': ['Google'], 'allow_fallbacks': True}
    # Gemini returns reasoning and no content when tools are combined with JSON mode, so
    # that pair silently dropped the search on every call and the model answered from
    # memory with homepage links. Search first, JSON mode only as a fallback.
    attempts = ([
        (tools, None),
        (tools, {'type': 'json_object'}),
    ] if server_tools else []) + [
        (None, {'type': 'json_object'}),
        (None, None),
    ]
    last_response = {}
    last_error = ''
    # A parseable JSON with zero executed searches is kept as a fallback, never as a
    # success — the tool attempts get retried before a memory answer is accepted.
    unverified_response = None
    for _cap_attempt in range(4):
        retry_cap = None
        for index, (attempt_tools, response_format) in enumerate(attempts):
            if unverified_response is not None and not attempt_tools:
                # A parseable memory answer is already in hand — tool-less
                # attempts can only produce another unverified one, at a cost.
                break
            if index:
                print(
                    '[MARKET STUDY] retrying competitor/summary call with '
                    f'tools={bool(attempt_tools)} json_mode={bool(response_format)}: '
                    f'{_chat_error_message(last_response)}'
                )
            last_response = call_openrouter_chat(
                system_prompt,
                user_content,
                temperature=None,
                max_tokens=cap,
                model=MARKET_STUDY_MODEL,
                response_format=response_format,
                provider=provider,
                tools=attempt_tools,
                plugins=plugins,
                timeout=240,
                usage_ctx=usage_ctx or _usage_ctx('market'),
                max_tool_calls=14,
            )
            last_error = _chat_error_message(last_response)
            text = _get_chat_response_text(last_response)
            if _has_chat_choices(last_response) and parse_json_object(text):
                finish = ''
                first_choice = (last_response.get('choices') or [{}])[0]
                if isinstance(first_choice, dict):
                    finish = str(first_choice.get('native_finish_reason')
                                 or first_choice.get('finish_reason') or '')
                clean_finish = finish.lower() in ('', 'stop', 'end_turn', 'length')
                if last_response.get('error') or not clean_finish:
                    # The provider aborted the answer (e.g. MALFORMED_FUNCTION_CALL)
                    # or attached an error to it: a parseable fragment is not a
                    # usable result, and returning it with an empty error ships
                    # the failure as a silent success.
                    last_error = _chat_error_message(last_response)
                    last_response = {'error': {'message': last_error}}
                    continue
                if attempt_tools and not _market_search_ran(last_response):
                    print('[MARKET STUDY] parseable JSON but zero searches ran — '
                          'keeping it as fallback and retrying with tools')
                    if unverified_response is None:
                        unverified_response = last_response
                    continue
                return last_response, ''
            affordable = _AFFORDABLE_TOKENS_RE.search(last_error or '')
            if affordable:
                quoted = int(affordable.group(1))
                candidate = max(2000, int(quoted * 0.85))
                if candidate < cap:
                    retry_cap = candidate
                    break
        if retry_cap is None:
            break
        print(f'[MARKET STUDY] provider refused cap={cap}; retrying with cap={retry_cap}')
        cap = retry_cap
    if unverified_response is not None:
        return unverified_response, ''
    return last_response, last_error


def _market_citation_pages(res):
    """Citation pages with titles — the url_citation annotations the search returned."""
    pages = []
    seen = set()
    for choice in (res.get('choices') or []) if isinstance(res, dict) else []:
        message = (choice or {}).get('message') or {}
        for annotation in message.get('annotations') or []:
            if not isinstance(annotation, dict):
                continue
            citation = annotation.get('url_citation') if isinstance(annotation.get('url_citation'), dict) else {}
            url = str(citation.get('url') or annotation.get('url') or '').strip()
            if url and url not in seen:
                seen.add(url)
                pages.append({
                    'url': url,
                    'title': str(citation.get('title') or '').strip(),
                    'content': str(citation.get('content') or '')[:8000],
                })
    return pages


def _market_citation_urls(res):
    """Collect the url_citation pages the web search actually retrieved."""
    return [page['url'] for page in _market_citation_pages(res)]


# Words shared by nearly every project name; a citation match must rest on the
# distinctive part of the name, not on «مجمع» or «residence».
_CITATION_GENERIC_TOKENS = {
    'مجمع', 'مشروع', 'ابراج', 'برج', 'سكني', 'السكني', 'حي', 'مدينه', 'مدينة',
    'مركز', 'وحدات', 'عقاري', 'عقارات',
    'compound', 'project', 'projects', 'residence', 'residential', 'tower',
    'towers', 'city', 'district', 'saudi', 'jeddah', 'riyadh', 'real', 'estate',
    'al', 'el', 'the',
}


def _competitor_name_tokens(name):
    folded = market_study._fold_choice(name)
    # Three-letter tokens carry real names (نور، علو) — dropping them left
    # short-named competitors with no tokens at all, which skipped their
    # verification and price search entirely.
    return {token for token in re.findall(r'[\w]+', folded)
            if len(token) >= 3 and token not in _CITATION_GENERIC_TOKENS}


def _attach_retrieved_citations(rows, pages):
    """Give source-less rows the retrieved pages that actually name them.

    The model sometimes writes no URLs even though the search returned pages.
    Those citations are real evidence — attach the ones whose title or URL
    mentions the competitor's distinctive name tokens (2+ hits, or the only
    distinctive token when the name carries just one).
    """
    if not pages:
        return
    for row in rows or []:
        if not isinstance(row, dict) or (row.get('row_source') or 'ai') != 'ai':
            continue
        tokens = _competitor_name_tokens(row.get('name'))
        if not tokens:
            continue
        needed = 1 if len(tokens) == 1 else 2
        matched = []
        for page in pages:
            # The name often sits in the retrieved excerpt, not the page title
            # or URL — search results carry a generic title for listing pages.
            # Same-name projects abroad are never evidence for a Saudi row.
            if _foreign_market_host(page.get('url')):
                continue
            haystack = market_study._fold_choice(
                f"{page.get('title') or ''} {page.get('url') or ''} {page.get('content') or ''}")
            if sum(1 for token in tokens if token in haystack) >= needed:
                matched.append(page['url'])
        if matched:
            # Attach even when the row already has sources: a generic portal
            # link is not proof the page that names this competitor made it
            # into the row.
            row['source_urls'] = list(dict.fromkeys(
                market_study.competitor_source_urls(row) + matched))[:6]
            existing_main = str(row.get('source_url') or '').strip()
            portal_host = existing_main and market_study._source_host(existing_main) \
                in market_study._PORTAL_DATASET_PAGES
            if (not existing_main or market_study.is_generic_source_homepage(existing_main)
                    or portal_host):
                row['source_url'] = market_study.prefer_specific_source_url(
                    *matched, existing_main)


def _verify_competitor_row(row, payload, data, tenant_id=None):
    """One targeted web search per competitor.

    The main call's single Exa query only retrieves market-level index pages,
    so the model fills names from memory. A per-competitor query retrieves the
    pages that actually mention THIS name: they become its source links, its
    official page feeds the logo import, and a name no retrieved page mentions
    is flagged as unverified instead of being silently trusted.
    """
    name = str(row.get('name') or '').strip()
    if not name:
        return
    city = str(payload.get('city') or '').strip() or 'السعودية'
    operation = str(row.get('operation_type') or '').strip() or 'أخرى'
    price_options = '، '.join(
        market_study.PRICE_TYPE_BY_OPERATION.get(operation)
        or market_study.PRICE_TYPE_BY_OPERATION['أخرى'])
    price_shape = (
        '"price": {"type": "أحد: ' + price_options + '", "value": "الرقم فقط", '
        '"from": "الحد الأدنى للنطاق", "to": "الحد الأقصى للنطاق", '
        '"url": "رابط الصفحة التي ورد فيها السعر حرفيًا"}')
    price_rule = (
        'السعر يُقبل فقط إذا ظهر في صفحة قرأتها في هذا البحث، ورابطها يوضع في '
        'price.url — إن لم تجد سعرًا أعد حقول price فارغة ولا تكتب رقمًا من ذاكرتك. ')
    prompts = [(
        f'ابحث في الويب عن المشروع العقاري «{name}» في مدينة {city} بالسعودية.\n'
        'أرجع JSON فقط: {"exists": true/false, "official_url": "صفحة الموقع الرسمي '
        'للمشروع أو مطوّره إن وُجدت", "summary": "سطر واحد عن المشروع", '
        + price_shape + '}.\n' + price_rule +
        'أي صفحة مسترجعة تذكر المشروع بالاسم تُحتسب دليلًا — موقع المطور أو '
        'إعلانًا تفصيليًا أو خبرًا، وليس شرطًا أن تكون رسمية. '
        'إن لم تجد أي صفحة تذكر هذا المشروع بالاسم أعد exists=false ولا تخمّن روابط.'
    )]
    tokens = _competitor_name_tokens(name)
    if not tokens:
        return
    needed = 1 if len(tokens) == 1 else 2
    # Bare-token retry: a quoted «مشروع …» phrasing under-retrieves when the
    # pages that name this project drop the generic prefix or use only one
    # script of a bilingual name. It also doubles as the retry when the first
    # call errors out or returns no citations.
    prompts.append(
        f'ابحث في الويب عن {" ".join(sorted(tokens))} — {city} السعودية.\n'
        'أرجع JSON فقط: {"exists": true/false, "official_url": "صفحة الموقع '
        'الرسمي إن وُجدت", "summary": "سطر واحد", ' + price_shape + '}.\n'
        + price_rule + 'أي صفحة تذكر الاسم تُحتسب دليلًا — إعلانًا أو خبرًا أو '
        'موقع مطوّر. إن لم تجد صفحة تذكر هذا الاسم أعد exists=false.'
    )
    usage_ctx = _usage_ctx('market', data, tenant_id=tenant_id)
    response = None
    search_ran_any = False
    matched = []
    matched_pages = {}
    official = ''
    last_error = ''
    for prompt in prompts:
        prompt_response = None
        # Plugin-only first (Gemini can fumble tool calls), then the
        # openrouter:web_search tool — on deployments where the Exa plugin
        # returns no citations the tool is the only path that grounds.
        for tools_on in (False, True):
            try:
                prompt_response, err = _call_market_study_model(
                    market_study.build_consultant_system_prompt(), prompt,
                    max_tokens=1200, usage_ctx=usage_ctx, server_tools=tools_on)
            except Exception:
                prompt_response = None
                continue
            last_error = err or last_error
            if not _market_search_ran(prompt_response):
                continue
            search_ran_any = True
            break
        if prompt_response is None or not _market_search_ran(prompt_response):
            # A tenant-key gate refusal is deterministic — every remaining
            # angle fails identically, so stop instead of burning them all.
            gate_error = (prompt_response or {}).get('error')
            if isinstance(gate_error, dict) and gate_error.get('error_code') in (
                    'NO_TENANT_KEY', 'TENANT_KEY_CHECK_FAILED'):
                break
            continue
        response = prompt_response
        prompt_matched = []
        for page in _market_citation_pages(prompt_response):
            url = str(page.get('url') or '').strip()
            if url and _foreign_market_host(url):
                continue
            title_url = market_study._fold_choice(f"{page.get('title') or ''} {url}")
            haystack = market_study._fold_choice(
                f"{title_url} {page.get('content') or ''}")
            hits = sum(1 for token in tokens if token in haystack)
            if hits >= needed:
                prompt_matched.append(url)
                matched_pages[url] = page
            # An official page carries the whole distinctive name in its title
            # or URL — a content-only mention is evidence the project exists,
            # not that the host belongs to it.
            if url and not official:
                title_hits = sum(1 for token in tokens if token in title_url)
                if title_hits >= len(tokens) and not any(
                        token in _normalized_web_host(url)
                        for token in _AGGREGATOR_HOST_TOKENS):
                    official = url
        matched.extend(prompt_matched)
        parsed, _parse_error = _parse_market_model_json(prompt_response)
        # A project price is only as good as the page naming this competitor —
        # the figure must come from a page this search actually retrieved.
        _apply_verified_competitor_price(row, parsed, set(prompt_matched))
        price_filled = any(str(row.get(key) or '').strip()
                           for key in ('price_value', 'price_from', 'price_to'))
        # Identity proven is not the job done — keep searching while the price
        # is still empty; the next query angle may surface a pricing page.
        if prompt_matched and price_filled:
            break
    if not search_ran_any:
        # The provider returned no citations at all — a search-provider miss,
        # not proof the name is fabricated. Say so instead of mislabeling it.
        row['verify_state'] = 'search_not_run'
        row['verify_provider_error'] = last_error or (
            _chat_error_message(response) if response else '') or 'empty_response'
        return
    matched = list(dict.fromkeys(matched))
    if not matched:
        # The search ran and no retrieved page mentions this name — flag the row
        # rather than silently trusting a memory-generated competitor. A manual
        # name is the user's own entry, so it is never marked fabricated.
        if (row.get('row_source') or 'ai') == 'ai':
            row['no_search_evidence'] = True
        row['verify_state'] = 'no_match'
        return
    row.pop('no_search_evidence', None)
    if not any(str(row.get(key) or '').strip()
               for key in ('price_value', 'price_from', 'price_to')):
        # The model's reply rarely carries the figure — the retrieved evidence
        # does. Search the citation excerpts first (they survive bot walls),
        # then the fetched pages, and take the median.
        _fill_competitor_price_from_listings(
            row, matched + market_study.competitor_source_urls(row),
            pages=list(matched_pages.values()))
    row['verify_state'] = 'verified'
    row['source_urls'] = list(dict.fromkeys(
        market_study.competitor_source_urls(row) + matched))[:6]
    if not str(row.get('source_url') or '').strip():
        row['source_url'] = market_study.prefer_specific_source_url(*row['source_urls'])
    if official and not str(row.get('logo_source_url') or '').strip():
        row['logo_source_url'] = official
        row['logo_official_verified'] = True


def _apply_verified_competitor_price(row, parsed, citation_urls):
    """Fill empty price fields from the per-competitor verification search.

    That call already retrieves real pages for this competitor — accept its
    price only when the cited page was actually retrieved, so the figure stays
    grounded in a fetched page and a memory number never slips through. A price
    the main pass already filled is never overwritten.
    """
    price = parsed.get('price') if isinstance(parsed, dict) else None
    if not isinstance(price, dict):
        price = parsed if isinstance(parsed, dict) else {}
    url = str(price.get('url') or price.get('source_url') or price.get('sourceUrl') or '').strip()
    if not url or url not in (citation_urls or set()):
        return
    value = market_study._clean_numeric(price.get('value') or price.get('price_value'))
    from_v = market_study._clean_numeric(price.get('from') or price.get('price_from'))
    to_v = market_study._clean_numeric(price.get('to') or price.get('price_to'))
    if not (value or from_v or to_v):
        return
    if str(row.get('price_value') or '').strip() or str(row.get('price_from') or '').strip():
        return
    url = market_study.canonical_index_source_url(url, row.get('operation_type'))
    price_type = str(price.get('type') or price.get('price_type') or '').strip()
    options = market_study.PRICE_TYPE_BY_OPERATION.get(
        str(row.get('operation_type') or '').strip() or 'أخرى',
        market_study.PRICE_TYPE_BY_OPERATION['أخرى'])
    if price_type not in options:
        price_type = ''
    is_range = price_type in market_study.RANGE_PRICE_TYPES or (from_v and to_v)
    if is_range:
        row['price_from'] = from_v or value
        row['price_to'] = to_v or ''
        row['price_cache'] = {'price_from': row['price_from'], 'price_to': row['price_to']}
        field_key = 'price_from'
        if not price_type:
            price_type = 'نطاق سعري' if 'نطاق سعري' in options else 'أخرى'
    else:
        row['price_value'] = value or from_v
        row['price_cache'] = {'price_value': row['price_value']}
        field_key = 'price_value'
    if price_type:
        row['price_type'] = price_type
    field_sources = market_study.competitor_field_sources(row)
    urls = field_sources.setdefault(field_key, [])
    if url not in urls:
        urls.append(url)
    row['field_sources'] = field_sources
    row['source_urls'] = list(dict.fromkeys(
        market_study.competitor_source_urls(row) + [url]))


def _read_market_source_page(url, max_bytes=2 * 1024 * 1024):
    """(html, error) — fetch a retrieved source page through the DNS-pinned pool.

    Model-supplied URLs stay on _pinned_https_get so redirects can never leave
    the original site and private hosts remain blocked. Returns raw markup:
    JSON-LD prices live inside <script> tags that visible-text stripping
    would discard."""
    pool, response, outcome = _pinned_https_get(url)
    if pool is None:
        return '', _official_fetch_error(outcome)
    try:
        if response.status != 200:
            return '', f'HTTP {response.status}'
        content = bytearray()
        for chunk in response.stream(64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > max_bytes:
                break
        return bytes(content).decode('utf-8', errors='replace'), ''
    except Exception as exc:
        return '', str(exc)
    finally:
        response.release_conn()
        pool.close()


_ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
_LISTING_PRICE_PATTERNS = (
    re.compile(r'(?:ريال|ر\.?\s?س|SAR|SR)\s*[:=]?\s*([0-9][0-9,.\u0660-\u0669]{2,})', re.IGNORECASE),
    re.compile(r'([0-9][0-9,.\u0660-\u0669]{2,})\s*(?:ريال|ر\.?\s?س|SAR|SR)\b', re.IGNORECASE),
    re.compile(r'"price"\s*:\s*"?([0-9][0-9,.]{2,})"?'),
)
_LISTING_PRICE_MIN = 300.0
_LISTING_PRICE_MAX = 2_000_000_000.0


def _extract_listing_prices(html):
    """[{value, period, per_sqm}] — price mentions inside a fetched listing page."""
    if not html:
        return []
    found = {}
    for pattern in _LISTING_PRICE_PATTERNS:
        for match in pattern.finditer(html):
            raw = (match.group(1) or '').translate(_ARABIC_DIGITS)
            raw = raw.replace(',', '').replace(' ', '')
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if not (_LISTING_PRICE_MIN <= value <= _LISTING_PRICE_MAX):
                continue
            window = html[max(0, match.start() - 100):match.end() + 100]
            if re.search(r'سنوي|سنة|annual|yearly|per\s*year|/yr', window, re.IGNORECASE):
                period = 'سنوي'
            elif re.search(r'شهري|شهر|monthly|per\s*month|/mo', window, re.IGNORECASE):
                period = 'شهري'
            elif re.search(r'ليلة|per\s*night|nightly', window, re.IGNORECASE):
                period = 'ليلة'
            else:
                period = ''
            per_sqm = bool(re.search(r'متر|sqm|م²|per\s*sq', window, re.IGNORECASE))
            found[(value, period, per_sqm)] = {'value': value, 'period': period, 'per_sqm': per_sqm}
    return list(found.values())


def _fill_competitor_price_from_listings(row, urls, pages=None):
    """Derive a grounded price from the retrieved pages themselves.

    The verify searches leave the price fields empty when the model's reply
    omits the figure — but the retrieved evidence carries it in two places:
    the citation content the search provider already returned (free, works
    even on bot-walled portals like bayut) and the fetched page markup for
    pages that are readable directly. The median of the mentions becomes a
    «متوسط» price; a single mention keeps its own type. price_listed flags
    it as listing evidence, not an officially documented tariff.
    """
    dead = {str(item).strip().casefold() for item in (row.get('dead_source_urls') or [])}
    page_content = {}
    for page in pages or []:
        if isinstance(page, dict):
            page_content[str(page.get('url') or '').strip()] = str(page.get('content') or '')
    mentions = []
    searched = 0
    unreadable = 0
    for url in list(dict.fromkeys(urls or []))[:4]:
        if str(url).strip().casefold() in dead:
            continue
        # The citation excerpt is searched first — fetching is the fallback
        # for pages the provider did not quote (or quoted too thinly).
        html = page_content.get(url) or ''
        if not html:
            html, _err = _read_market_source_page(url)
        if not html:
            unreadable += 1
            continue
        searched += 1
        for item in _extract_listing_prices(html):
            item['url'] = url
            mentions.append(item)
        if len(mentions) >= 4:
            break
    if not mentions:
        print(f"[MARKET STUDY] «{row.get('name') or 'منافس'}» no listing prices "
              f"({searched} pages searched, {unreadable} unreadable)")
        return False
    print(f"[MARKET STUDY] «{row.get('name') or 'منافس'}» listing prices: "
          f"{len(mentions)} mentions from {len({m['url'] for m in mentions})} pages")
    operation = str(row.get('operation_type') or '').strip() or 'أخرى'
    options = market_study.PRICE_TYPE_BY_OPERATION.get(
        operation, market_study.PRICE_TYPE_BY_OPERATION['أخرى'])

    def _option(*names):
        for name in names:
            if name in options:
                return name
        return 'أخرى' if 'أخرى' in options else options[0]

    if operation == 'إيجار':
        pool = [m for m in mentions if m['period'] in ('سنوي', 'شهري')] or mentions
    elif operation == 'تشغيل فندقي':
        pool = [m for m in mentions if m['period'] == 'ليلة'] or mentions
    else:
        pool = [m for m in mentions if not m['period']] or mentions
    values = sorted({m['value'] for m in pool})
    per_sqm = any(m['per_sqm'] for m in pool)
    used_urls = list(dict.fromkeys(m['url'] for m in pool))
    median = int(round(values[len(values) // 2] if len(values) % 2
                       else (values[len(values) // 2 - 1] + values[len(values) // 2]) / 2))
    if len(values) > 1:
        if operation == 'إيجار':
            price_type = _option('متوسط إيجار المتر' if per_sqm else 'متوسط إيجار الوحدة')
        elif operation == 'بيع':
            price_type = _option('متوسط سعر المتر' if per_sqm else 'متوسط سعر الوحدة')
        elif operation == 'تشغيل فندقي':
            price_type = _option('متوسط سعر الغرفة ADR')
        else:
            price_type = _option('نطاق سعري')
    else:
        period = (pool[0] if pool else {}).get('period') or ''
        if operation == 'إيجار':
            if per_sqm:
                price_type = _option('إيجار المتر الشهري' if period == 'شهري' else 'إيجار المتر السنوي')
            else:
                price_type = _option('إيجار الوحدة الشهري' if period == 'شهري' else 'إيجار الوحدة السنوي')
        elif operation == 'بيع':
            price_type = _option('سعر المتر المربع' if per_sqm else 'سعر الوحدة')
        elif operation == 'تشغيل فندقي':
            price_type = _option('سعر الليلة')
        else:
            price_type = _option('قيمة واحدة')
    if price_type in market_study.RANGE_PRICE_TYPES and len(values) > 1:
        row['price_from'], row['price_to'] = str(int(values[0])), str(int(values[-1]))
        row['price_cache'] = {'price_from': row['price_from'], 'price_to': row['price_to']}
        field_key = 'price_from'
    else:
        row['price_value'] = str(median)
        row['price_cache'] = {'price_value': row['price_value']}
        field_key = 'price_value'
    row['price_type'] = price_type
    row['price_listed'] = True
    field_sources = market_study.competitor_field_sources(row)
    bucket = field_sources.setdefault(field_key, [])
    for url in used_urls:
        if url not in bucket:
            bucket.append(url)
    row['field_sources'] = field_sources
    row['source_urls'] = list(dict.fromkeys(
        market_study.competitor_source_urls(row) + used_urls))[:6]
    marker = 'السعر متوسط إعلانات مسترجعة — غير موثق رسميًا'
    note = str(row.get('note') or '').strip()
    if marker not in note:
        row['note'] = f'{note} — {marker}' if note else marker
    return True


def _verify_competitor_rows(rows, payload, data, tenant_id=None, progress=None):
    report = progress if callable(progress) else (lambda *_args: None)
    # Manual rows verify too: fill mode exists to complete the cells the user
    # left empty, and the per-name search is the only priced lookup they get.
    targets = [row for row in (rows or [])
               if isinstance(row, dict)
               and str(row.get('name') or '').strip()]
    if not targets:
        return
    done = [0]
    total = len(targets)

    def verify(row):
        try:
            # Pool threads share no Flask context — without one the key gate
            # misreads every company as unkeyed and db-backed helpers die.
            with _worker_app_context():
                _verify_competitor_row(row, payload, data, tenant_id=tenant_id)
        finally:
            done[0] += 1
            report(30 + int(28 * done[0] / total),
                   f'التحقق من «{row.get("name") or "منافس"}» ({done[0]} من {total})...')

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(4, total)) as pool:
        list(pool.map(verify, targets))


def _parse_market_model_json(res):
    if not _has_chat_choices(res):
        return {}, _chat_error_message(res) or 'empty_response'
    text = _get_chat_response_text(res)
    parsed = parse_json_object(text)
    if not parsed:
        return {}, 'invalid_json'
    return parsed, ''


_MARKET_URL_CHECK_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ar,en;q=0.9',
}


def _market_dns_failure(exc):
    """True when a request failure traces back to DNS — the only network
    error that proves the host does not exist. urllib3 hides the resolution
    error behind layers of wrappers, so the cause chain is walked."""
    seen = exc
    while seen is not None:
        if isinstance(seen, socket.gaierror):
            return True
        if type(seen).__name__ in ('NameResolutionError', 'FailedNameResolution'):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def _market_url_alive(url, timeout=8):
    """Probe a claimed source URL; False only when the page provably does not exist.

    The search provider already retrieved this page once, so the link is
    presumed real: only a 404/410 or a DNS failure is proof of death. Bot
    walls (401/403/429), 5xx, timeouts, refused connections and TLS errors
    are probe problems — a Cloudflare challenge holds the socket open and
    would otherwise read as a dead page.
    """
    parsed = urlsplit(str(url or '').strip())
    if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
        return False
    try:
        invalid_port = parsed.port not in (None, 80, 443, 8080)
    except ValueError:
        invalid_port = True
    if invalid_port or parsed.username or not _public_host_addresses(parsed.hostname):
        return False
    for method in ('head', 'get'):
        try:
            request = getattr(requests, method)
            response = request(
                url, headers=_MARKET_URL_CHECK_HEADERS, timeout=timeout,
                allow_redirects=False, stream=True)
            try:
                status = response.status_code
            finally:
                response.close()
        except requests.RequestException as exc:
            if _market_dns_failure(exc):
                return False
            continue
        # A HEAD 404 proves nothing — misconfigured servers answer it wrongly
        # for pages that GET fine. Only the GET's 404/410 is proof of death.
        if status in (404, 410):
            if method == 'get':
                return False
            continue
        # Any other status means a live server answered — 2xx/3xx resolve,
        # 401/403/405/429 are bot walls, 5xx is an origin problem, not a
        # missing page.
        return True
    return True


def _verify_market_urls(urls, max_workers=6):
    """Return the subset of urls that provably fail; never raises."""
    unique = []
    seen = set()
    for url in urls or []:
        value = str(url or '').strip()
        key = value.casefold()
        if not value.startswith(('http://', 'https://')) or key in seen:
            continue
        seen.add(key)
        unique.append(value)
    if not unique:
        return set()
    from concurrent.futures import ThreadPoolExecutor
    dead = set()
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for url, alive in zip(unique, pool.map(_market_url_alive, unique)):
                if not alive:
                    dead.add(url)
    except Exception as exc:
        print(f'[MARKET STUDY] url verification failed: {exc}')
        return set()
    if dead:
        print(f'[MARKET STUDY] {len(dead)} dead source urls dropped: {sorted(dead)[:5]}')
    return dead


def _competitor_claimed_urls(row):
    """Every URL a competitor row asserts — sources plus the logo page."""
    urls = list(market_study.competitor_source_urls(row))
    for extra in (row.get('logo_source_url'), row.get('logo_url')):
        value = str(extra or '').strip()
        if value.startswith(('http://', 'https://')):
            urls.append(value)
    return urls


def _flag_dead_competitor_urls(row, dead):
    """Flag dead URLs on the row without removing them.

    The owner keeps the full trail — every claimed link stays visible, and
    ``dead_source_urls`` marks the ones that failed liveness so the UI can
    label them instead of silently dropping them.
    """
    if not isinstance(row, dict) or not dead:
        return row
    dead_keys = {str(url).strip().casefold() for url in dead}
    found = [url for url in market_study.competitor_source_urls(row)
             if str(url).strip().casefold() in dead_keys]
    for key in ('source_url', 'logo_source_url', 'logo_url'):
        if str(row.get(key) or '').strip().casefold() in dead_keys:
            found.append(row.get(key))
    if found:
        row['dead_source_urls'] = list(dict.fromkeys(
            list(row.get('dead_source_urls') or []) + found))
    return row


def _market_period_label(data):
    period = str(data.get('dataPeriod') or data.get('data_period') or '').strip()
    labels = {item['value']: item['label'] for item in market_study.DATA_PERIOD_OPTIONS}
    if period == 'custom':
        start = str(data.get('dataPeriodFrom') or data.get('data_period_from') or '').strip()
        end = str(data.get('dataPeriodTo') or data.get('data_period_to') or '').strip()
        if start or end:
            return f'فترة مخصصة من {start or "غير محدد"} إلى {end or "غير محدد"}'
    return labels.get(period, period or 'غير محدد')


def _market_radius_label(data, resolved_km):
    value = str(data.get('competitorRadius') or data.get('competitor_radius') or '10').strip()
    if value == 'auto':
        value = '10'
    labels = {item['value']: item['label'] for item in market_study.COMPETITOR_RADIUS_OPTIONS}
    if value == 'custom':
        custom = data.get('competitorRadiusCustomKm') or data.get('competitor_radius_custom_km') or resolved_km
        return f'نطاق مخصص {custom} كم'
    if resolved_km is None and value == 'city':
        return 'كامل المدينة'
    return labels.get(value, value)
