_MARKET_JOB_RESUME_LOCK = threading.Lock()


def _acquire_market_job_resume_guard():
    """Serialize resume sweeps across threads and Gunicorn worker processes."""
    _MARKET_JOB_RESUME_LOCK.acquire()
    handle = None
    try:
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        lock_path = os.path.join(UPLOADS_DIR, '.market-job-resume.lock')
        handle = open(lock_path, 'a+b')
        try:
            import fcntl
        except ImportError:
            # Windows test/dev runs still get process-local serialization.
            return handle, None
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle, fcntl
    except Exception:
        if handle is not None:
            handle.close()
        _MARKET_JOB_RESUME_LOCK.release()
        raise


def _release_market_job_resume_guard(guard):
    handle, lock_module = guard
    try:
        if lock_module is not None:
            lock_module.flock(handle.fileno(), lock_module.LOCK_UN)
    finally:
        try:
            handle.close()
        finally:
            _MARKET_JOB_RESUME_LOCK.release()


def _job_owner_pid_is_alive(owner_pid):
    """Return True/False for a valid PID, or None when the PID is unavailable."""
    try:
        pid = int(owner_pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as error:
        import errno
        if error.errno == errno.ESRCH:
            return False
        # Treat unexpected OS errors conservatively; duplicate work is worse
        # than delaying recovery until a later housekeeping sweep.
        return True
    return True


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
            for sticky in ('payload', 'actor', 'agentState', 'resumeState'):
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

    Every `_write_job` stamps the writing pid. A foreign pid is not proof that
    its worker died: Gunicorn workers share the job directory, so a live
    sibling must be left alone. The file lock makes the check-and-redispatch
    atomic across worker processes. Legacy jobs without a usable pid are only
    resumed after they become stale.
    """
    guard = _acquire_market_job_resume_guard()
    try:
        return _resume_interrupted_jobs_locked()
    finally:
        _release_market_job_resume_guard(guard)


def _resume_interrupted_jobs_locked():
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
                owner_alive = _job_owner_pid_is_alive(job.get('pid'))
                if owner_alive is True:
                    continue
                if owner_alive is None:
                    try:
                        age = time.time() - float(job.get('updatedAt') or 0)
                    except (TypeError, ValueError):
                        age = orphan_fail_seconds + 1
                    if age <= orphan_fail_seconds:
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
            if kind not in ('competitors', 'summary', 'summary_chat', 'summary_consolidate'):
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


_JOB_INTERNAL_KEYS = ('payload', 'actor', 'pid', 'evidencePages', 'resumeState')


def _market_job_can_resume(job):
    if not (isinstance(job, dict)
            and str(job.get('kind') or '') == 'summary'
            and str(job.get('status') or '') == 'failed'):
        return False
    reason = str(job.get('failureReason') or '')
    if reason in ('insufficient_credit', 'billing_refused'):
        return True
    resume_state = job.get('resumeState')
    researchers = (resume_state.get('researchers')
                   if isinstance(resume_state, dict) else None)
    return bool(reason == 'aggregator_failed'
                and isinstance(researchers, dict) and researchers)


def _public_job(job):
    """Job file minus server-only internals before it is returned to a client."""
    if not isinstance(job, dict):
        return job
    out = {k: v for k, v in job.items() if k not in _JOB_INTERNAL_KEYS}
    state = out.get('agentState')
    if isinstance(state, dict) and 'slides' in state:
        out['agentState'] = {k: v for k, v in state.items() if k != 'slides'}
    out['canResume'] = _market_job_can_resume(job)
    return out


def _market_job_dir(tenant_id):
    return _job_dir('.market_jobs', tenant_id)


def _market_job_path(tenant_id, job_id):
    return _job_path('.market_jobs', tenant_id, job_id)


def _write_market_job(tenant_id, job_id, payload):
    _write_job('.market_jobs', tenant_id, job_id, payload)


def _read_market_job(tenant_id, job_id):
    return _read_job('.market_jobs', tenant_id, job_id)


# A failed market job keeps a trimmed copy of the pages it already paid for;
# the next run of the same draft+kind picks them up instead of re-fetching
# every source — continuation after a deadline, not a restart.
_RESUME_MAX_JOB_AGE_SECONDS = 24 * 3600
_RESUME_SCAN_JOBS = 15
_RESUME_MAX_PAGES = 40
_RESUME_PAGE_CONTENT_CAP = 2500


def _pool_evidence_snapshot(evidence_pool):
    """Bounded page list for the failed-job record — url + title + a trimmed
    body, so the job file stays small while the next run inherits evidence."""
    pages = []
    if evidence_pool is None:
        return pages
    try:
        pool_pages = evidence_pool.pages()
    except Exception:
        return pages
    for page in pool_pages or []:
        if not isinstance(page, dict):
            continue
        url = str(page.get('url') or '').strip()
        if not url.startswith('http'):
            continue
        pages.append({
            'url': url,
            'title': str(page.get('title') or '')[:300],
            'content': str(page.get('content') or '')[:_RESUME_PAGE_CONTENT_CAP],
        })
        if len(pages) >= _RESUME_MAX_PAGES:
            break
    return pages


def _preload_failed_run_evidence(tenant_id, kind, data, evidence_pool):
    """Load the newest failed same-draft job's pages into this run's pool.

    The job file persists `payload.data` alongside the result, so the retry
    matches on the draft id — another project's evidence never leaks in.
    Returns the number of pages adopted (0 when nothing resumable exists).
    """
    if evidence_pool is None or not tenant_id:
        return 0
    data = data if isinstance(data, dict) else {}
    draft = str(data.get('draftId') or data.get('draft_id') or '').strip()
    if not draft:
        return 0
    try:
        job_dir = _market_job_dir(tenant_id)
        names = [name for name in os.listdir(job_dir)
                 if name.endswith('.json') and '.tmp-' not in name]
        names.sort(key=lambda name: os.path.getmtime(
            os.path.join(job_dir, name)), reverse=True)
    except OSError:
        return 0
    for name in names[:_RESUME_SCAN_JOBS]:
        try:
            job = _read_market_job(tenant_id, name[:-5])
        except Exception:
            continue
        if not isinstance(job, dict):
            continue
        if str(job.get('status') or '') != 'failed':
            continue
        if str(job.get('kind') or '') != str(kind):
            continue
        try:
            age = time.time() - float(job.get('updatedAt') or 0)
        except (TypeError, ValueError):
            continue
        if age > _RESUME_MAX_JOB_AGE_SECONDS:
            continue
        prev = job.get('payload') if isinstance(job.get('payload'), dict) else {}
        prev_data = prev.get('data') if isinstance(prev.get('data'), dict) else {}
        prev_draft = str(prev_data.get('draftId')
                         or prev_data.get('draft_id') or '').strip()
        if not prev_draft or prev_draft != draft:
            continue
        pages = job.get('evidencePages')
        if not isinstance(pages, list) or not pages:
            continue
        loaded = 0
        for page in pages:
            if not isinstance(page, dict):
                continue
            url = str(page.get('url') or '').strip()
            if not url.startswith('http'):
                continue
            try:
                if evidence_pool.add_page(
                        url, title=str(page.get('title') or ''),
                        content=str(page.get('content') or ''),
                        final_url=url, via='resumed'):
                    loaded += 1
            except Exception:
                continue
        if loaded:
            print(f'[MARKET JOB] resume preload: {loaded} pages '
                  f'for kind={kind} draft={draft[:12]}')
        return loaded
    return 0


def _attach_failure_evidence(result, evidence_pool):
    """A failed run hands its pool to the job file so the next attempt can
    resume — the snapshot only attaches to failures, never to clean runs."""
    if not isinstance(result, dict) or result.get('success'):
        return result
    snapshot = _pool_evidence_snapshot(evidence_pool)
    if snapshot:
        result['evidencePages'] = snapshot
    return result


def _market_search_ran(res):
    """Whether the response proves real web research actually executed.

    The browse agent returns ``url_citation`` annotations only for pages its
    headless Chromium actually opened — a parseable JSON with none is the
    model answering from memory, which must never read as a sourced study.
    The remaining detectors (server_tool_use, groundingMetadata) stay so a
    response from an older payload shape still counts truthfully.
    """
    if not isinstance(res, dict):
        return False
    usage = res.get('usage') or {}
    tool_use = usage.get('server_tool_use') or {}
    try:
        requests_count = int(tool_use.get('web_search_requests') or 0)
    except (TypeError, ValueError):
        requests_count = 0
    if requests_count > 0 or bool(_market_citation_urls(res)):
        return True
    # Provider-native grounding (Google) may skip url_citation annotations and
    # report only its own metadata — a recorded webSearchQueries list proves a
    # real search executed even when zero chunks came back citable.
    for choice in res.get('choices') or []:
        message = (choice or {}).get('message') or {}
        for holder in (choice, message):
            meta = (holder or {}).get('groundingMetadata') or (holder or {}).get('grounding_metadata')
            if isinstance(meta, dict) and (meta.get('webSearchQueries') or meta.get('web_search_queries')):
                return True
    return False


def _market_citation_pages(res):
    """Citation pages with titles — the url_citation annotations the search returned,
    plus provider-native grounding (Google) chunks and their supported segments."""
    pages = []
    seen = {}

    def _add(url, title='', content=''):
        url = str(url or '').strip()
        if not url:
            return
        if url in seen:
            page = pages[seen[url]]
        else:
            seen[url] = len(pages)
            page = {'url': url, 'title': '', 'content': ''}
            pages.append(page)
        if title and not page['title']:
            page['title'] = str(title).strip()
        if content:
            page['content'] = (page['content'] + '\n' + str(content)).strip()[:8000]

    for choice in (res.get('choices') or []) if isinstance(res, dict) else []:
        message = (choice or {}).get('message') or {}
        for annotation in message.get('annotations') or []:
            if not isinstance(annotation, dict):
                continue
            citation = annotation.get('url_citation') if isinstance(annotation.get('url_citation'), dict) else {}
            _add(citation.get('url') or annotation.get('url'),
                 citation.get('title'), citation.get('content'))
        for citation in message.get('citations') or []:
            if isinstance(citation, dict):
                _add(citation.get('url'), citation.get('title'), citation.get('content'))
            elif isinstance(citation, str):
                _add(citation)
        # Gemini/Google AI Mode grounding: groundingChunks carry the sources and
        # groundingSupports link answer sentences to the chunks they cite — the
        # supported text is evidence retrieved for that URL.
        for holder in (choice, message):
            meta = holder.get('groundingMetadata') or holder.get('grounding_metadata')
            if not isinstance(meta, dict):
                continue
            chunk_urls = {}
            for index, chunk in enumerate(meta.get('groundingChunks') or []):
                web = chunk.get('web') if isinstance(chunk, dict) else None
                uri = str((web or {}).get('uri') or '').strip()
                if uri:
                    chunk_urls[index] = uri
                    _add(uri, (web or {}).get('title'))
            for support in meta.get('groundingSupports') or []:
                if not isinstance(support, dict):
                    continue
                segment = support.get('segment') if isinstance(support.get('segment'), dict) else {}
                text = segment.get('text') or support.get('text')
                if not text:
                    continue
                for index in support.get('groundingChunkIndices') or []:
                    if index in chunk_urls:
                        _add(chunk_urls[index], content=text)
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
            # Same-name projects abroad are never evidence for a Saudi row,
            # and banned classifieds portals (all but aqar.fm — trivago for
            # hotel rows) never attach to a competitor at all.
            if _foreign_market_host(page.get('url')):
                continue
            if market_study.banned_competitor_listing_host(
                    page.get('url'), row.get('operation_type')):
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


def _verify_market_urls(urls, max_workers=6, progress=None, band=None):
    """Return the subset of urls that provably fail; never raises.

    ``progress``/``band`` let the caller tick the job bar per checked URL —
    the pool results arrive in order, so each completed check advances."""
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
    report = progress if callable(progress) else (lambda *_args: None)
    lo, hi = (band if isinstance(band, (tuple, list)) and len(band) == 2
              else (0, 0))
    from concurrent.futures import ThreadPoolExecutor
    dead = set()
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            checked = 0
            for url, alive in zip(unique, pool.map(_market_url_alive, unique)):
                if not alive:
                    dead.add(url)
                checked += 1
                if band:
                    host = url.split('/')[2] if '/' in url else url
                    report(lo + int((hi - lo) * checked / len(unique)),
                           f'فحص رابط {host} ({checked} من {len(unique)})...')
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
