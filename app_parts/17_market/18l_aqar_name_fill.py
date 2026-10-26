"""Complete a named residential or commercial competitor from aqar.

Hotels are completed from Booking (``18j_booking_name_fill``): the row's own
name resolves to a real property page and its figures are read from it.
Residential and commercial rows had no such lookup — a client-typed row waited
on the browse agent, which returns no project page, so the row kept a name and
nothing else. Two aqar sources answer here instead, both read deterministically:
the projects directory (every named project with its price and unit-area
ranges) and, for a competitor that is one advertised unit rather than a named
project, the city listing pages and the ad's own page. Matching compares the
row's name with the project's or card's own words, never with a search result,
and only the cells the row left empty are written — a figure the client entered
stays and the page's differing figure becomes a warning with its URL.
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
# A city listing page is a big SPA read; a fill that misses the named-project
# directory still gets a bounded look at the advertised units.
_LISTING_PAGE_LIMIT = 3
_LISTING_AREA_RE = re.compile(
    r'(?:المساحة|مساحة)\s*(?:الكلية|الصافية|الإجمالية)?\s*[:\-]?\s*'
    r'([0-9][0-9.,\u0660-\u0669]{0,6})\s*'
    r'(?:م²|م2|متر\s*مربع|مترمربع|sqm|m²|m2)(?![0-9A-Za-z])',
    re.IGNORECASE)


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


def _listing_area_sqm(text):
    """The unit area a listing page itself states, or None."""
    translated = str(text or '').translate(
        str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    match = _LISTING_AREA_RE.search(translated)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(',', ''))
    except ValueError:
        return None
    return value if 8 <= value <= 20000 else None


def _listing_page_urls(row, city):
    """The aqar city listing pages this row's own activity appears on."""
    kind = str((row or {}).get('project_type') or '').strip()
    kind = {'سكني': 'سكني', 'تجاري': 'تجاري'}.get(kind, '')
    operation = str((row or {}).get('operation_type') or '').strip()
    if not kind or operation not in ('بيع', 'إيجار'):
        return []
    try:
        return [url for url, _label in market_study._listing_urls(
            [kind], {operation}, city)]
    except Exception as exc:
        print(f'[MARKET STUDY] aqar listing urls skipped: {exc}', flush=True)
        return []


def _find_listing_link(session, row, city, cache):
    """The first listing card in the city pages whose own text names the row."""
    for url in _listing_page_urls(row, city):
        if url not in cache:
            if len(cache) >= _LISTING_PAGE_LIMIT:
                return None
            try:
                page = session.fetch_html(url, timeout=45)
            except Exception as exc:
                print(f'[MARKET STUDY] aqar listing page failed: {exc}',
                      flush=True)
                page = {}
            cache[url] = aqar_projects.parse_listing_links(
                (page or {}).get('html') or '')
        match = aqar_projects.match_listing_link(
            cache.get(url) or [], row.get('name'), city=city)
        if match:
            return match
    return None


def _listing_name_is_specific(row, city):
    """Two distinctive words are needed before an ad card can be claimed."""
    city_tokens = set(aqar_projects.project_name_tokens(city))
    tokens = {token for token in aqar_projects.project_name_tokens(
        (row or {}).get('name')) if token not in city_tokens}
    return len(tokens) >= 2


def _fill_row_from_aqar_listings(session, row, city, cache):
    """Complete a row from one advertised unit's own page on aqar.

    A competitor that is a single advertised unit has no entry in the named
    projects directory. Its card on the city listing page names it, and its
    own page states the asking price and the unit area. The price goes
    through the shared listing reader, so the page rules are the same ones
    every other listing-based figure obeys (original before discount,
    currency conversion, listing evidence marked as such).
    """
    if not _listing_name_is_specific(row, city):
        return False
    link = _find_listing_link(session, row, city, cache)
    if not link:
        return False
    opened = session.open_url(link.get('url'))
    opened = opened if isinstance(opened, dict) else {}
    title = str(opened.get('title') or '')
    text = str(opened.get('text') or '')
    if not aqar_projects.listing_page_names(
            title, text, row.get('name'), city=city):
        print(f'[MARKET STUDY] aqar listing rejected '
              f'name={row.get("name")!r} url={link.get("url")!r}', flush=True)
        return False
    url = str(opened.get('final_url') or link.get('url') or '').strip()
    filled = False
    try:
        filled = bool(_fill_competitor_price_from_listings(
            row, [url], pages=[{'url': url, 'title': title,
                                'content': text}]))
    except Exception as exc:
        print(f'[MARKET STUDY] aqar listing price failed: {exc}', flush=True)
    sources = row.get('field_sources')
    sources = dict(sources) if isinstance(sources, dict) else {}
    if not any(str(row.get(key) or '').strip()
               for key in ('area_sqm', 'area_from', 'area_to')):
        area = _listing_area_sqm(f'{title} {text}')
        if area is not None:
            # One advertised unit is one fixed area, never a range.
            row['area_mode'] = 'fixed'
            row['area_sqm'] = _money(area)
            row['area_from'] = ''
            row['area_to'] = ''
            sources['area_sqm'] = [url]
            filled = True
    row['field_sources'] = sources
    if url:
        urls = [item for item in (row.get('source_urls') or []) if item]
        if not str(row.get('source_url') or '').strip():
            row['source_url'] = url
        if url not in urls:
            urls.append(url)
        row['source_urls'] = urls
        if not str(row.get('source') or '').strip():
            row['source'] = 'عقار'
        if str(row.get('row_source') or '').strip() in ('', 'ai'):
            row['row_source'] = 'aqar'
            row['verify_state'] = 'verified'
    _set_note_if_empty(
        row, 'السعر والمساحة من إعلان هذا المشروع على عقار '
             '(إعلان معروض، وليس صفقة منفذة).')
    return filled


def _fill_project_rows_from_aqar(rows, payload, data, tenant_id=None,
                                 budget_seconds=None, progress=None,
                                 band=(48, 56), catalog=None, deadline=None):
    """Give every named residential/commercial row an aqar page of its own."""
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
                listing_cache = {}
                for index, row in enumerate(targets, start=1):
                    if time.time() > stop:
                        break
                    name = str(row.get('name') or '')
                    report(lo, f'قراءة مشروع «{name}» من عقار '
                               f'({index} من {total})...')
                    applied = False
                    link = aqar_projects.match_project_link(
                        links, name, city=city)
                    if link:
                        matched['count'] += 1
                        project = aqar_projects.project_for_link(
                            session, link, offer_lang=offer_lang, cards=cards)
                        if project and _apply_project_fields(row, project):
                            applied = True
                            print(f'[MARKET STUDY] aqar name fill matched '
                                  f'name={name!r} '
                                  f'url={str(project.get("source_url"))[:120]!r}',
                                  flush=True)
                    if not applied:
                        applied = _fill_row_from_aqar_listings(
                            session, row, city, listing_cache)
                    if not applied:
                        if _listing_name_is_specific(row, city):
                            note = ('لم يُعثر على هذا المشروع في دليل المشاريع '
                                    'المسمّاة ولا في إعلانات عقار؛ لم تُقرأ '
                                    'أسعار أو مساحات.')
                        else:
                            note = ('لم يُعثر على هذا المشروع في دليل المشاريع '
                                    'المسمّاة على عقار؛ لم تُقرأ أسعار أو '
                                    'مساحات.')
                        _set_note_if_empty(row, note)
                        print(f'[MARKET STUDY] aqar name fill miss '
                              f'name={name!r}', flush=True)
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
