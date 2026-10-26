"""Complete a named residential or commercial competitor from aqar.

Hotels are completed from Booking (``18j_booking_name_fill``): the row's own
name resolves to a real property page and its figures are read from it.
Residential and commercial rows had no such lookup — a client-typed row waited
on the browse agent, which returns no project page, so the row kept a name and
nothing else. Aqar's projects directory lists the city's named projects, and
each project page carries its price and unit-area ranges, which is the same
page aqar discovery already reads. Matching is deterministic: the row's name is
compared with the projects' own names, never with a search result, and only
the cells the row left empty are written — a figure the client entered stays
and the page's differing figure becomes a warning with its URL.
"""

import os
import re
import threading
import time

import aqar_projects


_AQAR_FILL_BUDGET_SECONDS = float(
    os.environ.get('AQAR_FILL_BUDGET_SECONDS') or 240)
_PRICE_KEYS = ('price_value', 'price_from', 'price_to')
_AREA_KEYS = ('area_mode', 'area_sqm', 'area_from', 'area_to')


def _numbers(*values):
    """The figures inside a price or area cell, for comparing two readings."""
    found = []
    for value in values:
        for match in re.findall(r'\d+(?:[.,]\d+)?', str(value or '')):
            try:
                found.append(float(match.replace(',', '')))
            except ValueError:
                continue
    return tuple(found)


def _project_price_text(project):
    price_type = str((project or {}).get('price_type') or '').strip()
    if price_type == 'نطاق سعري':
        low = str(project.get('price_from') or '').strip()
        high = str(project.get('price_to') or '').strip()
        if low and high:
            return f'من {low} إلى {high}'
    return str(project.get('price_value')
               or project.get('price_from') or '').strip()


def _project_area_text(project):
    project = project or {}
    if str(project.get('area_mode') or '').strip() == 'range':
        low = str(project.get('area_from') or '').strip()
        high = str(project.get('area_to') or '').strip()
        if low and high:
            return f'من {low} إلى {high} م²'
    value = str(project.get('area_sqm')
                or project.get('area_from') or '').strip()
    return f'{value} م²' if value else ''


def _append_conflict(row, field, existing, incoming, source_url):
    warnings = list(row.get('conflict_warnings') or [])
    signature = (field, str(existing), str(incoming), source_url)
    for item in warnings:
        if not isinstance(item, dict):
            continue
        if (item.get('field'), str(item.get('existing')),
                str(item.get('incoming')), item.get('source_url')) == signature:
            return
    warnings.append({
        'field': field,
        'existing': existing,
        'incoming': incoming,
        'source': 'عقار',
        'source_url': source_url,
    })
    row['conflict_warnings'] = warnings


def _needs_aqar_fill(row):
    """A non-hotel row still missing its source, its price or its area."""
    if not isinstance(row, dict) or _is_hotel_row(row):
        return False
    if not str(row.get('name') or '').strip():
        return False
    # An aqar-sourced row already carries the project page this lookup reads.
    if str(row.get('row_source') or '').strip() == 'aqar':
        return False
    if not str(row.get('source_url') or '').strip():
        urls = [item for item in (row.get('source_urls') or []) if item]
        if not urls:
            return True
    has_price = any(str(row.get(key) or '').strip() for key in _PRICE_KEYS)
    has_area = any(str(row.get(key) or '').strip()
                   for key in ('area_sqm', 'area_from', 'area_to'))
    return not has_price or not has_area


def _apply_project_fields(row, project):
    """Write the project's own figures onto the row's empty cells."""
    if not isinstance(row, dict) or not isinstance(project, dict):
        return False
    url = str(project.get('source_url') or '').strip()
    sources = row.get('field_sources')
    sources = dict(sources) if isinstance(sources, dict) else {}
    filled = False

    row_price = next((str(row.get(key) or '').strip() for key in _PRICE_KEYS
                      if str(row.get(key) or '').strip()), '')
    project_price = _project_price_text(project)
    if project_price and not row_price:
        for key in _PRICE_KEYS + ('price_currency',):
            value = str(project.get(key) or '').strip()
            if not value:
                continue
            row[key] = project.get(key)
            sources[key] = ([url] if url
                            else list(sources.get(key) or []))
        row['price_type'] = str(project.get('price_type') or '').strip()
        filled = True
    elif (project_price and row_price
            and _numbers(row_price) != _numbers(project_price)):
        _append_conflict(row, 'price_value', row_price, project_price, url)

    row_area = _project_area_text(row)
    project_area = _project_area_text(project)
    if project_area and not row_area:
        for key in _AREA_KEYS:
            value = str(project.get(key) or '').strip()
            if not value:
                continue
            row[key] = project.get(key)
            if key != 'area_mode':
                sources[key] = ([url] if url
                                else list(sources.get(key) or []))
        filled = True
    elif (project_area and row_area
            and _numbers(row_area) != _numbers(project_area)):
        _append_conflict(row, 'area_sqm', row_area, project_area, url)

    # A descriptive field only completes a cell the row left empty. Status
    # stays the client's: the directory's flag is not the project's stage.
    for key in ('project_type', 'operation_type', 'city', 'district'):
        value = str(project.get(key) or '').strip()
        if value and not str(row.get(key) or '').strip():
            row[key] = value

    row['field_sources'] = sources
    if url:
        urls = [item for item in (row.get('source_urls') or []) if item]
        if not str(row.get('source_url') or '').strip():
            row['source_url'] = url
        if url not in urls:
            urls.append(url)
        row['source_urls'] = urls
        if not str(row.get('source') or '').strip():
            row['source'] = str(project.get('source') or 'عقار')
        if str(row.get('row_source') or '').strip() in ('', 'ai'):
            row['row_source'] = 'aqar'
            row['verify_state'] = 'verified'
    if filled:
        _set_note_if_empty(row, str(project.get('notes') or ''))
    return filled


def _fill_project_rows_from_aqar(rows, payload, data, tenant_id=None,
                                 budget_seconds=None, progress=None,
                                 band=(48, 56), catalog=None, deadline=None):
    """Give every named residential/commercial row its aqar project page."""
    report = progress if callable(progress) else (lambda *_args: None)
    targets = [row for row in (rows or []) if _needs_aqar_fill(row)]
    print(f'[MARKET STUDY] aqar name fill rows={len(rows or [])} '
          f'targets={len(targets)}', flush=True)
    if not targets:
        return 0
    city = str((payload or {}).get('city') or '').strip()
    if not city:
        for row in targets:
            _set_note_if_empty(
                row, 'مدينة المشروع غير محددة؛ لم يُشغَّل البحث في دليل '
                     'المشاريع المسمّاة على عقار.')
        print('[MARKET STUDY] aqar name fill skipped: project city missing',
              flush=True)
        return 0
    offer_lang = slide_engine.resolve_offer_lang(data)
    budget = float(budget_seconds or _AQAR_FILL_BUDGET_SECONDS)
    stop = time.time() + budget
    if deadline is not None:
        try:
            stop = min(stop, float(deadline))
        except (TypeError, ValueError):
            pass
    before = {id(row): _filled_row_signature(row) for row in targets}
    lo, hi = band if isinstance(band, (tuple, list)) and len(band) == 2 else (48, 56)
    matched = {'count': 0}

    def _worker():
        session = None
        try:
            with _worker_app_context():
                session = _market_browser_session()
                if session is None:
                    return
                projects = catalog if isinstance(catalog, dict) else {}
                if not (projects.get('links') or projects.get('error')):
                    projects = aqar_projects.load_projects(session, city)
                links = projects.get('links') or []
                cards = projects.get('cards') or []
                print(f'[MARKET STUDY] aqar name fill city={city!r} '
                      f'links={len(links)} cards={len(cards)} '
                      f'error={projects.get("error") or ""!r}', flush=True)
                total = len(targets)
                for index, row in enumerate(targets, start=1):
                    if time.time() > stop:
                        break
                    name = str(row.get('name') or '')
                    report(lo, f'قراءة مشروع «{name}» من عقار '
                               f'({index} من {total})...')
                    link = aqar_projects.match_project_link(
                        links, name, city=city)
                    if not link:
                        _set_note_if_empty(
                            row, 'لم يُعثر على هذا المشروع في دليل المشاريع '
                                 'المسمّاة على عقار؛ لم تُقرأ أسعار أو مساحات.')
                        print(f'[MARKET STUDY] aqar name fill miss '
                              f'name={name!r}', flush=True)
                        continue
                    matched['count'] += 1
                    project = aqar_projects.project_for_link(
                        session, link, offer_lang=offer_lang, cards=cards)
                    if not project:
                        _set_note_if_empty(
                            row, 'لم تُفتح صفحة المشروع على عقار؛ لم تُقرأ '
                                 'أسعار أو مساحات.')
                        continue
                    if _apply_project_fields(row, project):
                        print(f'[MARKET STUDY] aqar name fill matched '
                              f'name={name!r} '
                              f'url={str(project.get("source_url"))[:120]!r}',
                              flush=True)
        except Exception as exc:
            print(f'[MARKET STUDY] aqar name fill failed: {exc}', flush=True)
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    thread = threading.Thread(target=_worker, name='aqar-name-fill',
                              daemon=True)
    thread.start()
    thread.join(timeout=max(5.0, stop - time.time()) + 30)
    for row in targets:
        if _filled_row_signature(row) == before[id(row)]:
            _set_note_if_empty(
                row, 'لم تُقرأ أسعار أو مساحات لهذا المشروع من عقار.')
    filled = sum(1 for row in targets
                 if _filled_row_signature(row) != before[id(row)])
    print(f'[MARKET STUDY] aqar name fill result filled={filled} '
          f'matched={matched["count"]} targets={len(targets)}', flush=True)
    report(hi, 'اكتمل إكمال بيانات المشاريع من عقار.')
    return filled
