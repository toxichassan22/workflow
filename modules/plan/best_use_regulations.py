import re

from best_use_contract import ProposalError, text, DIGITS, USE_TERMS
CONDITIONAL = re.compile(r'بشرط|شريطة|بعد موافقة|حسب المعتمد|حسب المخطط|حسب الاستعمال|يرجع للجهة|subject to|conditional', re.I)
NEGATION = re.compile(r'غير مسموح|لا يسمح|لا يُسمح|يحظر|ممنوع|not permitted|prohibited|not allowed', re.I)
GLOBAL_BAN = re.compile(r'(?:يحظر|يمنع|لا يسمح|لا يُسمح).{0,25}(?:تطوير الأرض|البناء على الأرض|أي تطوير)|development is prohibited', re.I)


def folded(value):
    return re.sub(r'\s+', ' ', str(value or '').translate(DIGITS)).strip()


def declared_basis(project, scope):
    """The client's declared permitted uses — the regulatory floor. Approval-
    gated, never silently trusted. Conditional or negated clauses are dropped
    clause-by-clause so a plain "سكني" survives a neighbouring "تجاري بشرط"
    without hard-failing."""
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


def declared(project):
    """The permitted-uses contract for exploration: the land/croquis analysis
    already distilled the parcel's regulation text into the declared fields, so
    that summary is the source — parcel documents and municipal files are never
    re-read. requiresApproval stays on: the uses are client-declared, so the
    artifact still certifies them instead of trusting them silently."""
    scope = {'plotNumber': folded(project.get('plot_number_croquis')),
             'zoningCode': folded(project.get('zoning_code')),
             'city': text(project.get('city'), 150), 'documentCity': '', 'proven': False}
    fields = '\n'.join(text(project.get(key), 8000) for key in
                       ('allowed_uses', 'regulatory_constraints', 'land_and_building_summary')).strip()
    if GLOBAL_BAN.search(fields):
        raise ProposalError('land_development_prohibited: يوجد حظر موثق على تطوير الأرض.')
    basis = declared_basis(project, scope)
    if basis is None:
        raise ProposalError('regulatory_uses_complete: قائمة الاستخدامات المسموحة غير متوفرة أو غير محسومة.')
    return {'permittedUses': basis['permittedUses'], 'evidence': basis['evidence'],
            'scope': scope, 'basis': 'declared', 'sourceDocuments': [],
            'constraints': [{'documentId': 'declared-inputs', 'page': 0,
                             'text': text(project.get(key), 8000)}
                            for key in ('allowed_uses', 'regulatory_constraints', 'land_and_building_summary')
                            if text(project.get(key))],
            'requiresApproval': True}


def validate_basis(row, regulations):
    use = row.get('useType')
    evidence = regulations.get('evidence') or []
    matches = [item for item in evidence if item.get('use') == use and item.get('status') == 'permitted']
    if regulations.get('basis') == 'declared':
        # Declared evidence is one identical entry per permitted use — the
        # server attaches it rather than expecting the model to echo the whole
        # allowed_uses summary verbatim. Membership in permittedUses is the
        # real gate; it runs before this is reached.
        if matches:
            return dict(matches[0])
        raise ProposalError('أساس السماح التنظيمي غير مثبت للمكون: ' + text(row.get('name'), 200))
    basis = row.get('allowedUseBasis')
    if not isinstance(basis, dict) or not any(all(basis.get(key) == item.get(key) for key in
            ('documentId', 'page', 'excerpt', 'parcelScope', 'landClassification')) for item in matches):
        raise ProposalError('أساس السماح التنظيمي غير مثبت للمكون: ' + text(row.get('name'), 200))
    return dict(next(item for item in matches if item.get('documentId') == basis.get('documentId')
                     and item.get('page') == basis.get('page') and item.get('excerpt') == basis.get('excerpt')))
