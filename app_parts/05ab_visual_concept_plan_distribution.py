def _visual_concept_plan_floor_range(text):
    """Parse an approved-table floor cell: 'G', 'B1-B3', '5-12', 'Roof' into
    {kind, lo, hi, count}. Basement lo/hi are negative; ground lo=hi=0; a lone
    mezzanine/مسروق sits at 0.5 — a slab inside the ground level, so it never
    collides with plain «أرضي» yet still overlaps a range that spans it."""
    value = str(text or '').strip()
    if not value:
        return None
    lowered = value.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')).lower()
    if re.search(r'مساحة\s*مفتوحة|سطحية|سطحي|surface|\bsite\b|open\s*area', lowered):
        return {'kind': 'site', 'lo': 0, 'hi': 0, 'count': 1}
    if re.search(r'roof|سطح|روف|ملحق|ملاحق', lowered):
        return {'kind': 'roof', 'lo': 0, 'hi': 0, 'count': 1}
    if re.search(r'\bb\s*\d|basement|بدروم|قبو|سرداب|تحت\s*الأرض', lowered):
        digits = [int(d) for d in re.findall(r'\d+', lowered)] or [1]
        first, last = min(digits), max(digits)
        return {'kind': 'basement', 'lo': -last, 'hi': -first, 'count': last - first + 1}
    numbers = [int(d) for d in re.findall(r'\d+', lowered)]
    if not numbers:
        ordinals = {'اول': 1, 'ثاني': 2, 'ثالث': 3, 'رابع': 4, 'خامس': 5,
                    'سادس': 6, 'سابع': 7, 'ثامن': 8, 'تاسع': 9, 'عاشر': 10}
        found = [ordinals.get(_visual_concept_plan_component_key(token) or '')
                 for token in re.split(r'[-–—]', value)]
        numbers = [n for n in found if n]
    mezzanine = bool(re.search(r'ميزانين|mezzanine|مسروق', lowered))
    ground = bool(re.search(r'\bg\b|ground|أرضي|الارضي|الأرضي', lowered))
    if mezzanine and not ground:
        return {'kind': 'mezzanine', 'lo': 0.5, 'hi': 0.5, 'count': 1}
    if not numbers:
        return {'kind': 'ground', 'lo': 0, 'hi': 0, 'count': 1} if ground else None
    lo, hi = (0, numbers[-1]) if ground else (numbers[0], numbers[-1])
    return {'kind': 'range', 'lo': lo, 'hi': hi, 'count': max(1, hi - lo + 1)}


_VISUAL_PLAN_FLOOR_LABEL_AR = {
    'g': 'أرضي', 'gf': 'أرضي', 'ground': 'أرضي', 'ground floor': 'أرضي',
    'm': 'ميزانين', 'mezzanine': 'ميزانين', 'mezz': 'ميزانين',
    'roof': 'ملحق علوي', 'rooftop': 'ملحق علوي', 'r': 'ملحق علوي',
    'podium': 'بوديوم', 'basement': 'بدروم', 'b': 'بدروم',
    'site': 'مساحة مفتوحة', 'surface': 'مساحة مفتوحة',
}


def _visual_concept_plan_floor_label(text):
    """Display label for a floor cell: Latin tokens the model emits (G, M,
    B1-B3, Roof) become the Arabic names the client actually reads. Ranges and
    already-Arabic labels pass through."""
    value = str(text or '').strip()
    if not value:
        return value
    lowered = value.casefold()
    if lowered in _VISUAL_PLAN_FLOOR_LABEL_AR:
        return _VISUAL_PLAN_FLOOR_LABEL_AR[lowered]
    basement = re.fullmatch(r'b\s*(\d+)(?:\s*-\s*b?\s*(\d+))?', lowered)
    if basement:
        start, end = basement.group(1), basement.group(2)
        return f'بدروم {start}' + (f'-{end}' if end else '')
    return value


def _visual_concept_plan_component_key(name):
    """Match key for component names — unifies hamza/taa/ya variants and drops
    word-initial «ال» so «طابق أرضي - سكني» matches «الطابق الأرضي سكني»."""
    text = str(name or '').translate(
        str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')).casefold()
    text = re.sub(r'[أإآٱ]', 'ا', text).replace('ى', 'ي').replace('ة', 'ه')
    text = text.replace('ـ', '')
    text = re.sub(r'(?<!\w)ال', '', text)
    return re.sub(r'[^\w\u0600-\u06FF]+', '', text)


def _visual_concept_plan_component_base(name):
    """Component name without a leading floor tag: «طابق أرضي - سكني» resolves to
    «سكني» and «ملحق علوي - خدمات أخرى» to «خدمات أخرى», so the study's
    per-floor rows and the distribution's per-use rows compare like for like.
    Names without a dash tag pass through unchanged."""
    text = _visual_concept_plan_sanitize_text(name)
    stripped = re.sub(
        r'^(?:ال)?(?:طابق|دور|ملحق|بدروم|سطح|floor|level|basement|roof)\s+[^-–—:]*[-–—:]\s*',
        '', text).strip()
    return stripped or text


def _visual_concept_plan_distribution_totals(rows, context):
    """Per-component totals from the distribution table, each matched against the
    required figure recorded in the project components / financial study rows.
    Both sides group on the base component name, so the study's per-floor rows
    («طابق أرضي - سكني» …) aggregate to the whole-component figure before the
    comparison instead of matching only the first floor's row."""
    groups = {}
    order = []
    for row in rows:
        name = _visual_concept_plan_sanitize_text(row.get('component')) or 'غير محدد'
        base = _visual_concept_plan_component_base(name)
        key = _visual_concept_plan_component_key(base) or _visual_concept_plan_component_key(name) or name
        if key not in groups:
            groups[key] = {'component': base, 'units': 0.0, 'area': 0.0,
                           'has_units': False, 'has_area': False}
            order.append(key)
        parsed = _visual_concept_plan_floor_range(row.get('floor_range'))
        count = parsed['count'] if parsed else 1
        units = row.get('units_per_floor')
        area = row.get('floor_area_sqm')
        if isinstance(units, (int, float)):
            groups[key]['units'] += units * count
            groups[key]['has_units'] = True
        if isinstance(area, (int, float)):
            groups[key]['area'] += area * count
            groups[key]['has_area'] = True
    required = []
    for comp in context.get('components') or []:
        comp_name = _visual_concept_plan_sanitize_text(comp.get('name'))
        required.append({
            'key': _visual_concept_plan_component_key(comp_name),
            'base_key': _visual_concept_plan_component_key(
                _visual_concept_plan_component_base(comp_name)),
            'component': _visual_concept_plan_component_base(comp_name) or comp_name,
            'required_units': comp.get('units'),
            'required_area': comp.get('builtArea') or comp.get('unitArea'),
        })

    def match_rank(item, key):
        if item['key'] == key or item['base_key'] == key:
            return 0
        if item['key'] and (item['key'] in key or key in item['key']):
            return 1
        if item['base_key'] and (item['base_key'] in key or key in item['base_key']):
            return 2
        return None

    matched = {key: [] for key in order}
    leftovers = []
    for item in required:
        if not (item['key'] or item['base_key']):
            continue
        best_key = best_rank = None
        for key in order:
            rank = match_rank(item, key)
            if rank is not None and (best_rank is None or rank < best_rank
                                     or (rank == best_rank and len(key) > len(best_key or ''))):
                best_key, best_rank = key, rank
        if best_key is None:
            leftovers.append(item)
        else:
            matched[best_key].append(item)

    def summed(field, items):
        numbers = [item[field] for item in items if isinstance(item[field], (int, float))]
        return round(sum(numbers), 2) if numbers else None

    totals = []
    for key in order:
        entry = groups[key]
        total = {
            'component': entry['component'],
            'units': round(entry['units'], 2) if entry['has_units'] else None,
            'area': round(entry['area'], 2) if entry['has_area'] else None,
            'required_units': summed('required_units', matched[key]),
            'required_area': summed('required_area', matched[key]),
        }
        for pair in (('units', 'required_units', 'delta_units'),
                     ('area', 'required_area', 'delta_area')):
            value, wanted = total[pair[0]], total[pair[1]]
            total[pair[2]] = (round(value - wanted, 2)
                              if isinstance(value, (int, float)) and isinstance(wanted, (int, float))
                              else None)
        totals.append(total)
    merged = {}
    merged_order = []
    for item in leftovers:
        group_key = item['base_key'] or item['key'] or item['component']
        if group_key not in merged:
            merged[group_key] = {'component': item['component'], 'items': []}
            merged_order.append(group_key)
        merged[group_key]['items'].append(item)
    for group_key in merged_order:
        entry = merged[group_key]
        req_units = summed('required_units', entry['items'])
        req_area = summed('required_area', entry['items'])
        totals.append({'component': entry['component'], 'units': 0, 'area': 0,
                       'required_units': req_units, 'required_area': req_area,
                       'delta_units': -req_units if isinstance(req_units, (int, float)) else None,
                       'delta_area': -req_area if isinstance(req_area, (int, float)) else None})
    return totals


def _visual_concept_plan_regulation_floor_cap(regulations):
    """Documented maximum floor count. `table_floors` is the regulation table's
    floor number and wins outright. `max_floors_height` is free text that can
    carry a METER height («حتى 23م لأربعة أدوار», «أقصى ارتفاع 15م»): a number
    there only counts as a floor cap when it sits next to a floor word —
    numbers tied to م/متر are heights, not floors, and must never cap a tower.
    """
    cap = _visual_concept_number(regulations.get('table_floors'))
    if cap:
        return cap
    text = str(regulations.get('max_floors_height') or '')
    if not text.strip():
        return None
    floor_word = r'(?:طوابق|طابق(?:ة|ين)?|أدوار|ادوار|دور(?:ات)?|floors?)'
    floors_first = re.search(r'(\d+(?:[.,]\d+)?)\s*' + floor_word, text, re.IGNORECASE)
    if floors_first:
        return _visual_concept_number(floors_first.group(1))
    floors_labeled = re.search(floor_word + r'\s*[:=]?\s*(\d+(?:[.,]\d+)?)', text, re.IGNORECASE)
    if floors_labeled:
        return _visual_concept_number(floors_labeled.group(1))
    candidates = []
    for match in re.finditer(r'(\d+(?:[.,]\d+)?)\s*(متر|م\b|meters?|metres?|m\b)?', text, re.IGNORECASE):
        if match.group(2):
            continue
        number = _visual_concept_number(match.group(1))
        if number:
            candidates.append(number)
    return max(candidates) if candidates else None


def _visual_concept_plan_distribution_checks(rows, totals, context, regulations):
    """Deterministic re-check of an (edited) distribution table — instant, no model:
    floor-range overlaps per building, height caps, coverage footprint, and the
    per-component deltas against the recorded program."""
    checks = []
    by_building = {}
    ids_by_component = {}
    parsed_rows = []
    for row in rows:
        parsed = _visual_concept_plan_floor_range(row.get('floor_range'))
        parsed_rows.append((row, parsed))
        row_key = _visual_concept_plan_component_key(
            _visual_concept_plan_component_base(row.get('component')))
        if row_key:
            ids_by_component.setdefault(row_key, []).append(row.get('id'))
        if not parsed or parsed['kind'] in ('basement', 'roof', 'site'):
            continue
        building = _visual_concept_plan_sanitize_text(row.get('building')) or 'المبنى الرئيسي'
        by_building.setdefault(building, []).append((parsed, row))
    for building, entries in by_building.items():
        # Hard conflict only when the SAME component claims overlapping ranges —
        # different components sharing a floor is normal mixed use, so it is a
        # soft "confirm the share" note instead of a blocker.
        by_component = {}
        for parsed, row in entries:
            key = _visual_concept_plan_component_key(
                _visual_concept_plan_component_base(row.get('component')))
            if key:
                by_component.setdefault(key, []).append((parsed, row))
        for comp_entries in by_component.values():
            ordered = sorted(comp_entries, key=lambda item: item[0]['lo'])
            for (first, row_a), (second, row_b) in zip(ordered, ordered[1:]):
                if second['lo'] <= first['hi']:
                    checks.append({
                        'item': f'نطاقان متداخلان لمكوّن واحد — {building}',
                        'detail': (f'«{row_a.get("component") or "مكوّن"}» مسجل على «{row_a.get("floor_range")}» '
                                   f'و«{row_b.get("floor_range")}» — ادمج الصفين أو عدّل النطاق'),
                        'result': 'متعارض', 'severity': 'high',
                        'row_ids': [row_a.get('id'), row_b.get('id')]})

    cap = _visual_concept_number(context.get('approved_floor_count')) or _visual_concept_plan_regulation_floor_cap(regulations)
    if cap:
        for row, parsed in parsed_rows:
            if parsed and parsed['kind'] == 'range' and parsed['hi'] > cap:
                checks.append({
                    'item': 'تجاوز سقف الأدوار الموثق',
                    'detail': f'«{row.get("component") or "مكون"}» ({row.get("floor_range")}) يتجاوز الحد الموثق {cap:g} دورًا',
                    'result': 'متعارض', 'severity': 'high', 'row_ids': [row.get('id')]})
    land = _visual_concept_number(context.get('land_area') or regulations.get('croquis_land_area'))
    coverage = _visual_concept_number(context.get('coverage_ratio') or regulations.get('coverage_ratio')
                                      or regulations.get('building_ratio_coverage'))
    if land and coverage:
        ratio = coverage / 100 if coverage > 1.5 else coverage
        footprint_cap = land * ratio
        for row, parsed in parsed_rows:
            area = row.get('floor_area_sqm')
            if parsed and parsed['kind'] == 'site':
                continue
            if isinstance(area, (int, float)) and area > footprint_cap * 1.02:
                checks.append({
                    'item': 'مساحة الدور تتجاوز حد التغطية',
                    'detail': f'«{row.get("component") or "مكون"}» {area:g} م² والحد التقريبي {footprint_cap:g} م²',
                    'result': 'يحتاج تأكيد', 'severity': 'medium', 'row_ids': [row.get('id')]})
    far = _visual_concept_number(context.get('floor_area_ratio')) or _visual_concept_number(regulations.get('floor_area_ratio'))
    if not far:
        far_match = re.search(r'معامل[^\d]{0,15}(\d+(?:[.,]\d+)?)',
                              str(regulations.get('zone_rules') or '') + ' ' +
                              str(regulations.get('building_ratio') or ''))
        far = _visual_concept_number(far_match.group(1)) if far_match else None
    if land and far:
        total_built = sum(
            row.get('floor_area_sqm') * (parsed['count'] if parsed else 1)
            for row, parsed in parsed_rows
            if isinstance(row.get('floor_area_sqm'), (int, float))
            and (not parsed or parsed['kind'] not in ('basement', 'site')))
        cap_area = land * far
        if total_built > cap_area * 1.02:
            checks.append({
                'item': 'إجمالي المسطحات يتجاوز معامل البناء',
                'detail': (f'مجموع مساحات الأدوار {total_built:g} م² يتجاوز حد المعامل '
                           f'{cap_area:g} م² ({far:g} × أرض {land:g} م²) — قلّل مساحات الأدوار'),
                'result': 'يحتاج تأكيد', 'severity': 'medium',
                'row_ids': [row.get('id') for row, parsed in parsed_rows
                            if isinstance(row.get('floor_area_sqm'), (int, float))
                            and (not parsed or parsed['kind'] not in ('basement', 'site'))]})
    for total in totals:
        for delta_key, label in (('delta_units', 'الوحدات'), ('delta_area', 'المساحة')):
            delta = total.get(delta_key)
            required_key = 'required_units' if delta_key == 'delta_units' else 'required_area'
            wanted = total.get(required_key)
            if isinstance(delta, (int, float)) and isinstance(wanted, (int, float)) and wanted:
                if abs(delta) > max(1.0, abs(wanted) * 0.1):
                    checks.append({
                        'item': f'فرق {label} — {total["component"]}',
                        'detail': f'التوزيع {total[delta_key.replace("delta_", "")]:g} مقابل المطلوب {wanted:g}',
                        'result': 'يحتاج تأكيد', 'severity': 'medium',
                        'row_ids': ids_by_component.get(
                            _visual_concept_plan_component_key(total['component']), [])})
    return checks + _financial_parking_distribution_checks(rows, context)


def _visual_concept_plan_adjudicate_checks(checks, reviews):
    """Merge sol's per-finding verdicts into the deterministic check list: the model
    judges every numbered finding — «متعارض» keeps blocking, «يحتاج تأكيد» stays
    advisory, and «مطابق»/«سليم» dismisses a false alarm outright. A finding the
    model skipped keeps its deterministic verdict, so nothing clears silently."""
    verdicts = {}
    for item in (reviews or [])[:60]:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get('index'))
        except (TypeError, ValueError):
            continue
        result = _visual_concept_plan_sanitize_text(item.get('result'))
        detail = _visual_concept_plan_sanitize_text(
            item.get('detail') or item.get('reason'))[:500]
        fixable = item.get('fixable') is not False
        if result in ('مطابق', 'سليم', 'صحيح'):
            verdicts[index] = ('مطابق', detail, fixable)
        elif result == 'متعارض':
            verdicts[index] = ('متعارض', detail, fixable)
        elif result:
            verdicts[index] = ('يحتاج تأكيد', detail, fixable)
    adjudicated = []
    for index, check in enumerate(checks or []):
        if check.get('fixedFact') or index not in verdicts:
            adjudicated.append(check)
            continue
        result, detail, fixable = verdicts[index]
        if result == 'مطابق':
            continue
        updated = dict(check)
        updated['result'] = result
        updated['severity'] = 'high' if result == 'متعارض' else 'medium'
        if not fixable:
            updated['fixable'] = False
        if detail:
            updated['detail'] = detail
        adjudicated.append(updated)
    return adjudicated


def _visual_concept_plan_surgical_rows(old_rows, new_rows, editable_ids, allowed_keys=None):
    """Keep the model's edit surgical: rows no check flagged are restored
    verbatim — the model may edit, merge or drop only the flagged ids, and may
    add brand-new rows (e.g. a study component the table is missing). Untouched
    rows keep their original order; new rows append at the end. When
    `allowed_keys` (the study's component keys) is given, a rename that lands
    outside the study vocabulary — «الشقق السكنية الفاخرة» turned
    «Residential» — is reverted and off-vocabulary additions are dropped, so
    every row keeps matching its study totals."""
    old_by_id = {row.get('id'): row for row in old_rows}
    new_by_id = {}
    extra_rows = []
    for row in new_rows:
        rid = row.get('id')
        if rid in old_by_id or rid in new_by_id:
            new_by_id[rid] = row
        else:
            extra_rows.append(row)
    if allowed_keys is not None:
        def _key(name):
            return _visual_concept_plan_component_key(
                _visual_concept_plan_component_base(name))
        for rid, row in list(new_by_id.items()):
            if rid in editable_ids and rid in old_by_id:
                new_key = _key(row.get('component'))
                old_key = _key(old_by_id[rid].get('component'))
                if new_key != old_key and new_key not in allowed_keys:
                    row = dict(row)
                    row['component'] = old_by_id[rid].get('component')
                    new_by_id[rid] = row
        extra_rows = [row for row in extra_rows if _key(row.get('component')) in allowed_keys]
    merged = []
    for row in old_rows:
        rid = row.get('id')
        if rid in new_by_id:
            merged.append(new_by_id[rid] if rid in editable_ids else row)
        elif rid not in editable_ids:
            merged.append(row)
    merged.extend(extra_rows)
    return merged


def _visual_concept_plan_normalize_distribution(raw, context, regulations):
    """Normalize the distribution table (proposed or client-edited) and attach the
    deterministic totals + checks so every edit re-verifies the same way."""
    source = raw if isinstance(raw, dict) else {}
    rows = []
    for item in (source.get('rows') if isinstance(source.get('rows'), list) else []):
        if not isinstance(item, dict):
            continue
        component = _visual_concept_plan_sanitize_text(
            item.get('component') or item.get('use') or item.get('name'))
        building = _visual_concept_plan_sanitize_text(item.get('building') or item.get('mass'))
        floor_range = _visual_concept_plan_floor_label(
            _visual_concept_plan_sanitize_text(
                item.get('floor_range') or item.get('floors') or item.get('range')))
        if not (component or building or floor_range):
            continue
        rows.append({
            'id': _visual_concept_plan_sanitize_text(item.get('id'))[:40] or f'row_{len(rows) + 1}',
            'building': building[:160],
            'floor_range': floor_range[:80],
            'component': component[:160],
            'units_per_floor': _visual_concept_number(item.get('units_per_floor') or item.get('units')),
            'floor_area_sqm': _visual_concept_number(item.get('floor_area_sqm') or item.get('floor_area')),
            'circulation': _visual_concept_plan_sanitize_text(
                item.get('circulation') or item.get('services'))[:400],
        })
    totals = _visual_concept_plan_distribution_totals(rows, context)
    return {
        'rows': rows,
        'totals': totals,
        'checks': _visual_concept_plan_distribution_checks(rows, totals, context, regulations),
        'issues': _visual_concept_plan_normalize_issues(source.get('issues') or []),
        'approved': False,
    }



def _visual_concept_plan_fallback_distribution(context, regulations):
    """No-model proposal: flatten the inferred plan model into table rows so the
    client still gets an editable starting point when the text call fails."""
    model = _visual_concept_plan_model(context, regulations)
    rows = []
    if model:
        for band in model.get('bands') or []:
            names = '، '.join(_visual_concept_plan_sanitize_text(item.get('name'))
                              for item in band.get('items') or [] if item.get('name'))
            floors = band.get('floors') or 1
            units = sum(item['units'] for item in band.get('items') or []
                        if isinstance(item.get('units'), (int, float)))
            area = sum(item['builtArea'] for item in band.get('items') or []
                       if isinstance(item.get('builtArea'), (int, float)))
            rows.append({
                'building': 'المبنى الرئيسي', 'floor_range': band.get('range') or '',
                'component': names or band.get('label') or '',
                'units_per_floor': round(units / floors, 2) if units else None,
                'floor_area_sqm': round(area / floors, 2) if area else None,
                'circulation': ''})
        for block in model.get('blocks') or []:
            rows.append({
                'building': block.get('label') or 'مبنى ثانٍ', 'floor_range': f"1-{block.get('cap') or 1}",
                'component': block.get('use') or '', 'units_per_floor': None,
                'floor_area_sqm': None, 'circulation': ''})
        if model.get('below') and not any(row.get('parkingPlanId') for row in context.get('components') or []):
            rows.append({'building': 'المبنى الرئيسي', 'floor_range': 'B1',
                         'component': 'مواقف سيارات', 'units_per_floor': None,
                         'floor_area_sqm': None, 'circulation': 'اتصال رأسي بالمبنى'})
        if model.get('roof'):
            rows.append({'building': 'المبنى الرئيسي', 'floor_range': 'Roof',
                         'component': 'خدمات وسطح', 'units_per_floor': None,
                         'floor_area_sqm': None, 'circulation': ''})
    rows = _financial_parking_merge_distribution_rows(rows, context)
    return {'rows': rows, 'notes': ['توزيع آلي أولي من البيانات المعتمدة — يحتاج مراجعة.']}


def _visual_concept_plan_model_from_distribution(distribution, context, regulations):
    """Build the shared plan model from the CLIENT-APPROVED distribution table
    instead of the inferred banding. Returns None when no usable rows exist so
    callers can fall back to the inferred model."""
    raw_rows = (distribution or {}).get('rows')
    rows = [row for row in raw_rows or [] if isinstance(row, dict)
            and (str(row.get('component') or '').strip() or str(row.get('floor_range') or '').strip())]
    if not rows:
        return None

    def parsed_of(row):
        return _visual_concept_plan_floor_range(row.get('floor_range'))

    def top_floor(group_rows):
        top = 0
        for row in group_rows:
            parsed = parsed_of(row)
            if parsed and parsed['kind'] not in ('basement', 'roof', 'site'):
                top = max(top, parsed['hi'])
        return int(-(-top // 1)) if top else 0

    def band_for(row):
        parsed = parsed_of(row) or {'kind': 'range', 'lo': 0, 'hi': 0, 'count': 1}
        component = _visual_concept_plan_sanitize_text(row.get('component'))
        _order, category = _visual_concept_plan_use_category({'name': component})
        count = parsed['count']
        units = row.get('units_per_floor')
        area = row.get('floor_area_sqm')
        label = _visual_concept_plan_component_en(component)
        if not label or re.search(r'[\u0600-\u06FF]', label):
            label = _VISUAL_PLAN_USE_LABEL.get(category, 'Amenities')
        return {
            'category': category,
            'label': label,
            'items': [{
                'name': component,
                'units': (units * count) if isinstance(units, (int, float)) else units,
                'builtArea': (area * count) if isinstance(area, (int, float)) else area,
                'floorRange': _visual_concept_plan_sanitize_text(row.get('floor_range')),
                'building': _visual_concept_plan_sanitize_text(row.get('building')),
                'notes': _visual_concept_plan_sanitize_text(row.get('circulation')),
            }],
            'floors': count,
            'range': _visual_concept_plan_sanitize_text(row.get('floor_range')),
            'color': _visual_concept_plan_use_color(
                context, _VISUAL_PLAN_USE_LABEL.get(category, 'Amenities')),
            'kind': parsed['kind'],
        }

    buildings, by_key, site_rows = [], {}, []
    for row in rows:
        parsed = parsed_of(row)
        if parsed and parsed['kind'] == 'site':
            site_rows.append(row)
            continue
        name = _visual_concept_plan_sanitize_text(row.get('building')) or 'المبنى الرئيسي'
        key = name.casefold()
        if key not in by_key:
            by_key[key] = len(buildings)
            buildings.append({'name': name, 'rows': []})
        buildings[by_key[key]]['rows'].append(row)
    tower = max(buildings, key=lambda group: top_floor(group['rows'])) if buildings else {'name': '', 'rows': []}
    secondaries = [group for group in buildings if group is not tower]

    def sort_bands(bands):
        return sorted(bands, key=lambda band: (
            parsed_of({'floor_range': band['range']}) or {'lo': 0})['lo'])

    bands, below, roof = [], [], []
    open_uses = [band_for(row) for row in site_rows]
    for row in tower['rows']:
        band = band_for(row)
        if band['kind'] == 'basement':
            below.append(band)
        elif band['kind'] == 'roof' or band['category'] == 'service':
            roof.append(band)
        elif band['category'] == 'landscape':
            open_uses.append(band)
        else:
            bands.append(band)
    bands = sort_bands(bands)
    blocks = []
    for index, group in enumerate(secondaries):
        block_bands = []
        for row in group['rows']:
            band = band_for(row)
            if band['kind'] == 'basement':
                below.append(band)
            elif band['kind'] == 'roof' or band['category'] == 'service':
                roof.append(band)
            elif band['category'] == 'landscape':
                open_uses.append(band)
            else:
                block_bands.append(band)
        block_bands = sort_bands(block_bands)
        label_en = _visual_concept_plan_component_en(group['name'])
        if not label_en or re.search(r'[\u0600-\u06FF]', label_en):
            label_en = (block_bands[0]['label'] if block_bands
                        else f'Block {chr(66 + index)}')
        category = block_bands[0]['category'] if block_bands else 'amenity'
        blocks.append({
            'label': label_en,
            'cap': top_floor(group['rows']) or sum(b['floors'] for b in block_bands),
            'direction': _visual_concept_plan_direction_key(group['name']) or '',
            'use': _VISUAL_PLAN_USE_LABEL.get(category, 'Amenities'),
            'color': (block_bands[0]['color'] if block_bands
                      else _visual_concept_plan_use_color(context, 'Amenities')),
            'bands': block_bands,
        })

    hints = _visual_concept_plan_sector_hints(regulations)
    capped = [hint for hint in hints if hint.get('cap')]
    low_sector = min(capped, key=lambda hint: hint['cap']) if capped else None
    explicit_open = [hint for hint in hints
                     if hint.get('uncapped') and hint is not low_sector]
    open_hints = [hint for hint in hints
                  if not hint.get('cap') and hint is not low_sector]
    high_sector = (explicit_open or open_hints or [None])[0]
    street_dirs, _other_dirs, sea_dir = _visual_concept_plan_direction_scan(context)
    main_dir, res_dir, svc_dir = _visual_concept_plan_entry_dirs(street_dirs, sea_dir, high_sector)
    all_bands = bands + [band for block in blocks for band in block['bands']]
    return {
        'bands': bands,
        'below': below,
        'roof': roof,
        'open_uses': open_uses,
        'high_sector': high_sector,
        'low_sector': low_sector,
        'blocks': blocks,
        'floor_count': top_floor(tower['rows']),
        'main_dir': main_dir,
        'res_dir': res_dir,
        'svc_dir': svc_dir,
        'sea_dir': sea_dir,
        'has_residential': any(band['category'] == 'residential' for band in all_bands),
        'block_label': blocks[0]['label'] if blocks else 'Low Block',
        'from_distribution': True,
    }
