"""Parallel side sources for the competitor job: aqar projects and the
known-sources plan. Each owns its thread and never blocks the scans."""

import os
import threading


_AQAR_PROJECT_LIMIT = int(os.environ.get('AQAR_PROJECT_LIMIT') or 12)
_AQAR_SCAN_BUDGET_SECONDS = float(
    os.environ.get('AQAR_SCAN_BUDGET_SECONDS') or 90)


def _aqar_pairs(axes):
    """The Arabic (project_type, operation) pairs the selected axes need."""
    pairs = []
    for axis in axes or []:
        kind = str((axis or {}).get('type') or '')
        operation = str((axis or {}).get('operation') or '')
        project_type = {'residential': 'سكني',
                        'commercial': 'تجاري'}.get(kind, '')
        op_ar = {'sale': 'بيع', 'rent': 'إيجار'}.get(operation, '')
        pair = (project_type, op_ar)
        if project_type and op_ar and pair not in pairs:
            pairs.append(pair)
    return pairs


def _start_aqar_projects_scan(payload, axes, report=None, deadline=None,
                              offer_lang='ar'):
    """Read the city's named projects from aqar beside the agent scans.

    The directory page is a bot-walled SPA; the thread owns its browser and
    its own session, and the join in `_await_aqar_projects_scan` bounds it.
    """
    pairs = _aqar_pairs(axes)
    city = str((payload or {}).get('city') or '').strip()
    if not pairs or not city:
        return None
    scope = (payload or {}).get('competitorScope') or {}
    # A district scope may cover several neighborhoods the client picked.
    # They are read together and nothing outside them is accepted.
    districts = []
    if str(scope.get('mode') or 'district') == 'district':
        picked = scope.get('districts') if isinstance(scope.get('districts'), list) else []
        for item in list(picked) + [str((payload or {}).get('district') or '').strip()]:
            text = str(item or '').strip()
            if text and text not in districts:
                districts.append(text)
    district = districts[0] if districts else ''
    holder = {'rows': [], 'result': {}, 'error': ''}

    def _worker():
        session = None
        try:
            with _worker_app_context():
                import aqar_projects
                session = _market_browser_session()
                result = aqar_projects.scan(
                    session, city, district=district, pairs=pairs,
                    districts=tuple(districts),
                    limit=_AQAR_PROJECT_LIMIT,
                    budget_seconds=_AQAR_SCAN_BUDGET_SECONDS,
                    progress=report, offer_lang=offer_lang)
                holder['result'] = result if isinstance(result, dict) else {}
                holder['rows'] = list(holder['result'].get('rows') or [])
        except Exception as exc:
            holder['error'] = str(exc)
            print(f'[MARKET STUDY] aqar projects scan failed: {exc}',
                  flush=True)
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    thread = threading.Thread(target=_worker, name='aqar-projects',
                              daemon=True)
    thread.start()
    return {'thread': thread, 'holder': holder, 'district': district,
            'districts': districts}


def _await_aqar_projects_scan(handle, timeout=60):
    if not handle:
        return []
    thread = handle.get('thread')
    if thread is not None:
        thread.join(timeout=timeout)
    holder = handle.get('holder') or {}
    rows = holder.get('rows') or []
    result = holder.get('result') or {}
    print(f'[MARKET STUDY] aqar projects cards={result.get("cards", 0)} '
          f'matched={result.get("matched", 0)} rows={len(rows)} '
          f'error={holder.get("error") or result.get("error") or ""!r}',
          flush=True)
    return rows


def _start_source_plan_async(payload, offer_lang, evidence_pool, deadline,
                             report, session=None, market_wide=False):
    """Run the known-sources plan beside the scans instead of before them.

    It keeps the job's shared browser (the scans own their own), so the plan
    still reaches the pages a plain HTTP read cannot and the job closes that
    session once, after every stage.
    """
    if evidence_pool is None:
        return None

    def _worker():
        try:
            with _worker_app_context():
                kwargs = dict(
                    offer_lang=offer_lang,
                    evidence_pool=evidence_pool,
                    session=session,
                    deadline=deadline,
                    report=report)
                if market_wide:
                    kwargs['market_wide'] = True
                _run_market_source_plan(payload, **kwargs)
        except Exception as exc:
            print(f'[MARKET STUDY] parallel source plan failed: {exc}')

    thread = threading.Thread(target=_worker, name='market-source-plan', daemon=True)
    thread.start()
    return thread


def _await_source_plan(thread, timeout=None):
    if thread is None:
        return
    thread.join(timeout=timeout)
