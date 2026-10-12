import re
from pathlib import Path

import city_regulations
import regulation_digest
from best_use_contract import ProposalError, text, digest, DIGITS, USE_TERMS
CONDITIONAL = re.compile(r'بشرط|شريطة|بعد موافقة|حسب المعتمد|حسب المخطط|حسب الاستعمال|يرجع للجهة|subject to|conditional', re.I)
NEGATION = re.compile(r'غير مسموح|لا يسمح|لا يُسمح|يحظر|ممنوع|not permitted|prohibited|not allowed', re.I)
GLOBAL_BAN = re.compile(r'(?:يحظر|يمنع|لا يسمح|لا يُسمح).{0,25}(?:تطوير الأرض|البناء على الأرض|أي تطوير)|development is prohibited', re.I)
DECLARATION = re.compile(r'(?:الاستخدامات المسموحة|الاستعمالات المسموحة|permitted uses)\s*[:：]\s*([^\n]+)', re.I)
HEADING_DECLARATION = re.compile(r'(?m)^\s*#{1,4}\s*[^\n]*(?:الاستعمالات (?:ب|في)|الاستخدامات المسموحة)[^\n]*\n+([^#]+)', re.I)


def folded(value):
    return re.sub(r'\s+', ' ', str(value or '').translate(DIGITS)).strip()


def parcel_scope(project, pages):
    selected = folded(project.get('plot_number_croquis'))
    found = []
    marked = False
    for page in pages:
        if page.get('kind') != 'parcel':
            continue
        normalized = str(page.get('text') or '').translate(DIGITS)
        plots = re.findall(r'(?:رقم القطعة|قطعة رقم|plot number)\s*[:：]?\s*([\w/-]+)', normalized, re.I)
        if plots:
            marked = True
        if not selected and len(set(plots)) == 1:
            found.append(plots[0])
        elif selected in plots:
            found.append(selected)
    if not selected and len(set(found)) == 1:
        selected = found[0]
    # Older croquis documents carry no parcel marker at all — then the client's
    # declared parcel data stands on its own and the artifact is approval-gated.
    # When a document does mark parcels, a mismatch still proves the wrong file.
    if marked and (not selected or selected not in found):
        raise ProposalError('regulatory_parcel_scope: لا يوجد نص مستند يثبت القطعة المقصودة.')
    codes = []
    for page in pages:
        raw = str(page.get('text') or '')
        if page.get('kind') == 'parcel' and (not marked or not selected or selected in folded(raw)):
            codes.extend(folded(match) for match in re.findall(
                r'(?:كود التنظيم|الكود التنظيمي|zoning code)\s*[:：]\s*([^\n]+)', raw, re.I))
    code = folded(project.get('zoning_code'))
    if code and codes and code not in codes:
        raise ProposalError('regulatory_zoning_scope: كود التنظيم غير مثبت في مستند القطعة.')
    if not code and len(set(codes)) == 1:
        code = codes[0]
    city = text(project.get('city'), 150)
    documented_cities = []
    for page in pages:
        if page.get('kind') != 'parcel':
            continue
        for value in re.findall(r'(?:اسم المدينة|المدينة|city)\s*[:：]\s*([^\n]+)|أمانة(?: محافظة)?\s+([^\n]+)',
                                str(page.get('text') or ''), re.I):
            label = next((part.strip() for part in value if part.strip()), '')
            slug, _display = city_regulations.resolve_site_city(label)
            if slug:
                documented_cities.append(slug)
    target_city, _label = city_regulations.resolve_site_city(city)
    if documented_cities and any(slug != target_city for slug in documented_cities):
        raise ProposalError('regulatory_city_scope: مدينة المستند لا تطابق موقع الأرض.')
    return {'plotNumber': selected, 'zoningCode': code, 'city': city,
            'documentCity': documented_cities[0] if documented_cities else '', 'proven': marked}


def declared_basis(project, scope):
    """The client's declared permitted uses — the regulatory floor when the
    croquis text cannot prove them. Approval-gated, never silently trusted.
    Conditional or negated clauses are dropped clause-by-clause so a plain
    "سكني" survives a neighbouring "تجاري بشرط" without hard-failing."""
    declared = text(project.get('allowed_uses'), 8000)
    if not declared:
        return None
    uses = set()
    for clause in re.split(r'[\n؛;,،.]', declared):
        if NEGATION.search(clause) or CONDITIONAL.search(clause):
            continue
        for use, pattern in USE_TERMS.items():
            if re.search(pattern, clause, re.I):
                uses.add(use)
        if re.search(r'تجاري(?:ة)?|commercial', clause, re.I):
            uses.update({'retail', 'office', 'entertainment'})
    if not uses:
        return None
    return {'permittedUses': sorted(uses),
            'evidence': [{'use': use, 'documentId': 'declared-inputs', 'page': 0, 'excerpt': declared,
                          'parcelScope': scope['plotNumber'], 'landClassification': scope['zoningCode'],
                          'conditions': [], 'status': 'permitted'} for use in sorted(uses)],
            'basis': 'declared'}


def local_pages(project, parcel_pages):
    scope = parcel_scope(project, parcel_pages)
    slug, _label = city_regulations.resolve_site_city(scope['city'])
    if (not slug or not city_regulations.is_local_city(slug)
            or (scope['documentCity'] and scope['documentCity'] != slug) or not scope['zoningCode']):
        return []
    lookup = regulation_digest._load('index.json')['lookup']
    entry = next((value for key, value in lookup.items() if folded(key) == scope['zoningCode']), None)
    if not entry or 'حسب' in entry.get('label', '') or 'يتطلب' in entry.get('label', '') or 'تحقق' in entry.get('label', ''):
        return []
    zone = regulation_digest.zone_rules(entry['zone'])
    if not zone or not zone.get('uses'):
        return []
    ranges = {}
    for source in zone.get('source') or []:
        numbers = set()
        for part in str(source.get('p') or '').split(','):
            span = part.split('-')
            if all(value.strip().isdigit() for value in span):
                numbers.update(range(int(span[0]), int(span[-1]) + 1))
        ranges.setdefault(int(source.get('f') or 0), set()).update(numbers)
    folder = Path(regulation_digest.__file__).parent / 'regulation_transcriptions'
    pages = []
    for path in sorted(folder.glob('clean*.md')):
        content = path.read_text(encoding='utf-8')
        first = content.split('\n', 1)[0]
        document_number = next((n for n in ranges if 'اشتراطات' + str(n) + '.pdf' in first), None)
        if document_number is None:
            continue
        for match in re.finditer(r'---\s*صفحة\s*(\d+)\s*---\s*\n(.*?)(?=---\s*صفحة\s*\d+\s*---|\Z)', content, re.S):
            if int(match.group(1)) in ranges[document_number]:
                pages.append({'documentId': 'municipal-' + str(document_number), 'page': int(match.group(1)),
                              'kind': 'municipal', 'text': match.group(2).strip(), 'scope': scope,
                              'zoneUses': zone['uses'], 'zoneName': zone.get('name') or ''})
    return pages


def declarations(page):
    source = str(page.get('text') or '')
    results = [(match.group(0).strip(), match.group(1).strip()) for match in DECLARATION.finditer(source)]
    if page.get('kind') == 'municipal':
        for match in HEADING_DECLARATION.finditer(source):
            body = match.group(1).strip().split('\n\n', 1)[0]
            excerpt = match.group(0)[:match.group(0).find(match.group(1))] + body
            if any(folded(use) in folded(body) for use in page.get('zoneUses') or []):
                results.append((excerpt.strip(), body))
    return results


def extract(project, pages, interpreted=None):
    scope = parcel_scope(project, pages)
    scoped = []
    for page in pages:
        if page.get('kind') == 'municipal':
            if page.get('scope') != scope:
                continue
        else:
            plots = re.findall(r'(?:رقم القطعة|قطعة رقم|plot number)\s*[:：]?\s*([\w/-]+)',
                               str(page.get('text') or '').translate(DIGITS), re.I)
            # Unproven scope (no parcel markers in the document) keeps every
            # client-attached parcel page — they all describe this land.
            if scope['proven'] and set(plots) != {scope['plotNumber']}:
                continue
        scoped.append(page)
    if any(GLOBAL_BAN.search(str(page.get('text') or '')) for page in scoped):
        raise ProposalError('land_development_prohibited: يوجد حظر موثق على تطوير الأرض.')
    candidates = None
    if interpreted is not None:
        candidates = interpreted.get('declarations') if isinstance(interpreted, dict) else None
        if not isinstance(candidates, list):
            raise ProposalError('regulatory_uses_complete: قائمة الأدلة غير مكتملة.')
    sources = [(page, excerpt, body) for page in scoped for excerpt, body in declarations(page)]
    if candidates is not None:
        marker = re.compile(r'(?:الاستخدامات|الاستعمالات)\s+المسموح[ةه]|permitted uses', re.I)
        for item in candidates:
            if not isinstance(item, dict):
                raise ProposalError('regulatory_evidence_invalid: الاقتباس لا يمثل قائمة سماح كاملة منطبقة.')
            page = next((entry for entry in scoped if entry['documentId'] == item.get('documentId')
                         and entry['page'] == item.get('page')), None)
            excerpt = str(item.get('excerpt') or '')
            if page is None or not excerpt.strip() or excerpt not in str(page.get('text') or ''):
                raise ProposalError('regulatory_evidence_invalid: الاقتباس غير موجود حرفيًا في الصفحة المنطبقة.')
            found = marker.search(excerpt)
            body = re.sub(r'^\s*[:：]?\s*', '', excerpt[found.end():]) if found else ''
            if not body:
                raise ProposalError('regulatory_evidence_invalid: الاقتباس لا يحمل قائمة استخدامات كاملة.')
            sources.append((page, excerpt.strip(), body))
    evidence = []
    use_sets = []
    for page, excerpt, body in sources:
        if CONDITIONAL.search(body) or NEGATION.search(body):
            raise ProposalError('regulatory_uses_conditions: السماح مشروط أو منفي في النص الأصلي.')
        uses = {use for use, pattern in USE_TERMS.items() if re.search(pattern, body, re.I)}
        if re.search(r'تجاري(?:ة)?|commercial', body, re.I):
            uses.update({'retail', 'office', 'entertainment'})
        if not uses:
            continue
        for clause in str(page.get('text') or '').split('\n'):
            if NEGATION.search(clause) and not re.search(r'التجزئة|الارتفاع|المواقف|القبو|البدروم', clause):
                if any(re.search(USE_TERMS[use], clause, re.I) for use in uses):
                    raise ProposalError('regulatory_uses_conditions: يوجد نفي لسماح الاستخدام في النص المنطبق.')
        use_sets.append(uses)
        for use in sorted(uses):
            evidence.append({'use': use, 'documentId': page['documentId'], 'page': page['page'],
                             'excerpt': excerpt, 'parcelScope': scope['plotNumber'],
                             'landClassification': scope['zoningCode'], 'conditions': [], 'status': 'permitted'})
    if not use_sets:
        # The client-declared uses are the regulatory floor when the document
        # carries no full permitted-use declaration — approval-gated.
        declared = declared_basis(project, scope)
        if declared is None:
            raise ProposalError('regulatory_uses_complete: النص التنظيمي الكامل للاستخدامات غير متوفر أو غير محسوم.')
        return {'permittedUses': declared['permittedUses'], 'evidence': declared['evidence'],
                'scope': scope, 'basis': 'declared',
                'sourceDocuments': [{'documentId': page['documentId'], 'page': page['page'],
                    'textHash': digest(page['text'])} for page in scoped],
                'constraints': [{'documentId': page['documentId'], 'page': page['page'], 'text': page['text']}
                                for page in scoped], 'requiresApproval': True}
    permitted = set.intersection(*use_sets)
    if not permitted:
        raise ProposalError('regulatory_uses_conflict: قوائم الاستخدامات في المستندات متعارضة.')
    return {'permittedUses': sorted(permitted), 'evidence': [item for item in evidence if item['use'] in permitted],
            'scope': scope, 'sourceDocuments': [{'documentId': page['documentId'], 'page': page['page'],
                'textHash': digest(page['text'])} for page in scoped],
            'constraints': [{'documentId': page['documentId'], 'page': page['page'], 'text': page['text']}
                            for page in scoped], 'requiresApproval': interpreted is not None or not scope['proven']}


def validate_basis(row, regulations):
    use = row.get('useType')
    evidence = regulations.get('evidence') or []
    matches = [item for item in evidence if item.get('use') == use and item.get('status') == 'permitted']
    basis = row.get('allowedUseBasis')
    if not isinstance(basis, dict) or not any(all(basis.get(key) == item.get(key) for key in
            ('documentId', 'page', 'excerpt', 'parcelScope', 'landClassification')) for item in matches):
        raise ProposalError('أساس السماح التنظيمي غير مثبت للمكون: ' + text(row.get('name'), 200))
    return dict(next(item for item in matches if item.get('documentId') == basis.get('documentId')
                     and item.get('page') == basis.get('page') and item.get('excerpt') == basis.get('excerpt')))
