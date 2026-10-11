# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VISUAL CONCEPT SECTION GATES
#
# The workspace runs as four approved sections in a fixed order — plans →
# exterior → interior → sketches. Each paid route re-checks the chain before a
# provider call: the posted sectionApprovals flag plus, when the visual_concept
# mirror ships with the request, the underlying item approvals it certifies.
# Plans is the all-items leg (the exterior model consumes the three-diagram
# set); the later sections certify whatever subset the client generated —
# including none (an untouched section approves as skipped). What a flag never
# certifies is a pending draft: anything generated but unapproved blocks it,
# mirroring the frontend reconciler that drops it on persist.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VISUAL_CONCEPT_SECTION_ORDER = ('plans2d', 'external', 'internal', 'sketches')

_VISUAL_CONCEPT_SECTION_ERRORS = {
    'plans2d': 'اعتمد قسم المخططات أولاً',
    'external': 'اعتمد قسم التصور الخارجي أولاً',
    'internal': 'اعتمد قسم التصور الداخلي أولاً',
}


def _visual_concept_posted_state(data):
    """The visual_concept mirror, parsed whether it shipped as a dict or as the
    hidden-input JSON string the tenant form posts."""
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    concept = project_data.get('visual_concept')
    if isinstance(concept, str):
        concept = _visual_concept_parse_json(concept, {})
    return concept if isinstance(concept, dict) else {}


def _visual_concept_section_approvals(data):
    state = _visual_concept_posted_state(data)
    source = state.get('sectionApprovals')
    if not isinstance(source, dict):
        source = state.get('section_approvals')
    if not isinstance(source, dict):
        # Routes that drop the mirror (the sketch payload) ship the flags alone.
        source = data.get('sectionApprovals') or data.get('section_approvals')
    source = source if isinstance(source, dict) else {}
    return {key: bool(source.get(key)) for key in VISUAL_CONCEPT_SECTION_ORDER}


def _visual_concept_section_items_approved(data, section_id):
    """Re-derives what the section flag certifies so a hand-edited flag cannot
    stand in for content the same request does not show. Plans needs the full
    three-diagram set; the later sections certify whatever subset the client
    generated — including none — so an untouched slot never blocks, but a
    pending draft (imageUrl present, approvedImageUrl absent) always does.
    Routes that drop the mirror (sketches) skip this — the flag stands alone
    there, the same trust level as the approvedImageUrl values the rest of
    the flow accepts."""
    if section_id == 'plans2d':
        return len(_visual_concept_plan_image_urls(data)) >= 3
    slots = _visual_concept_posted_state(data).get('slots')
    slots = slots if isinstance(slots, dict) else {}
    if not slots:
        return True

    def _pending(slot):
        return (isinstance(slot, dict)
                and str(slot.get('imageUrl') or '').strip()
                and not str(slot.get('approvedImageUrl') or '').strip())

    if section_id == 'external':
        return not any(_pending(slots.get(key)) for key in VISUAL_CONCEPT_EXTERNAL_SLOTS)
    if section_id == 'internal':
        return not any(_pending(slots.get(key)) for key in slots
                       if _visual_concept_is_internal_slot(key))
    return True


def _visual_concept_section_requirement(slot_id):
    """Which approved section unlocks generation for this slot — None for the
    plan slots themselves (their own workflow gate already ran)."""
    if _visual_concept_is_plan_slot(slot_id):
        return None
    if _visual_concept_is_internal_slot(slot_id):
        return 'external'
    if slot_id in VISUAL_CONCEPT_EXTERNAL_SLOTS:
        return 'plans2d'
    return None


def _visual_concept_section_gate(data, required):
    """None when the required section is certified; the error payload
    otherwise. Runs after the legacy plan-image and cover gates so their error
    codes keep their precedence."""
    if not required:
        return None
    if not _visual_concept_section_approvals(data).get(required):
        return {'success': False,
                'error': _VISUAL_CONCEPT_SECTION_ERRORS.get(required, 'قسم التصور غير معتمد'),
                'error_code': 'SECTION_APPROVAL_REQUIRED',
                'section': required}
    if not _visual_concept_section_items_approved(data, required):
        return {'success': False,
                'error': 'اعتماد القسم لا يطابق محتواه المعتمد',
                'error_code': 'SECTION_ITEMS_INCOMPLETE',
                'section': required}
    return None
