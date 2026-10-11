/* 12-files-media/02a_visual_concept_sections.js — Visual Concept section approvals */

    /* ── Major-section approvals, the workflow's second tier. The workspace runs
       as a strict sequence — plans, exterior, interior, sketches — and each
       leg carries one durable flag that certifies its generated content.
       Plans is the all-items leg: the exterior model consumes the full
       three-diagram set, so every plan must be approved. The later legs
       certify whatever subset the user chose to generate — including none at
       all: an untouched section approves as skipped. What a flag never
       certifies is a pending draft — anything generated but not yet approved
       blocks the flag until it is approved too. Each flag unlocks only the
       next leg. The flags live in tenantVisualConceptState.sectionApprovals
       and are reconciled on every persist, so revoked or regenerated content
       can never leave a stale approval behind. ── */

    const VISUAL_CONCEPT_SECTION_IDS = ['plans2d', 'external', 'internal', 'sketches'];

    function visualConceptSectionLabel(id) {
      const fallback = {
        plans2d: 'المخططات', external: 'التصور الخارجي',
        internal: 'التصور الداخلي', sketches: 'السكتشات'
      }[id] || id;
      return WFT('vc.sec.' + id, fallback);
    }

    function visualConceptSectionGate(id) {
      const index = VISUAL_CONCEPT_SECTION_IDS.indexOf(id);
      return index > 0 ? VISUAL_CONCEPT_SECTION_IDS[index - 1] : null;
    }

    function visualConceptSectionApproved(id) {
      const approvals = tenantVisualConceptState && tenantVisualConceptState.sectionApprovals;
      return Boolean(approvals && approvals[id]);
    }

    function visualConceptSectionLocked(id) {
      const gate = visualConceptSectionGate(id);
      return Boolean(gate) && !visualConceptSectionApproved(gate);
    }

    function visualConceptSectionLockReason(id) {
      const gate = visualConceptSectionGate(id);
      if (!gate || visualConceptSectionApproved(gate)) return '';
      return WFT('vc.sec.locked_until', 'مقفل حتى اعتماد قسم {name}', { name: visualConceptSectionLabel(gate) });
    }

    // The approved artifacts a section flag certifies. Plans needs the full
    // three-diagram set; the later sections certify whatever subset the user
    // chose to generate, so a single approved artifact is enough there.
    function visualConceptSectionApprovedCount(id) {
      const slots = tenantVisualConceptState?.slots || {};
      if (id === 'plans2d') {
        return VISUAL_CONCEPT_PLAN_KINDS
          .filter(item => durableImageUrl(slots[item.id]?.approvedImageUrl)).length;
      }
      if (id === 'external') {
        return VISUAL_CONCEPT_EXTERNAL_SLOTS
          .filter(item => durableImageUrl(slots[item.id]?.approvedImageUrl)).length;
      }
      if (id === 'internal') {
        return Object.keys(slots)
          .filter(key => isVisualConceptInteriorSlot(key) && durableImageUrl(slots[key]?.approvedImageUrl))
          .length;
      }
      if (id === 'sketches') {
        return visualConceptSketchSourceIds().filter(srcId => {
          const sketch = slots[srcId]?.sketch || {};
          return sketch.status === 'approved' && durableImageUrl(sketch.approvedImageUrl);
        }).length;
      }
      return 0;
    }

    // Generated-but-unapproved artifacts inside a section. Their existence is
    // what a section flag cannot certify — an untouched slot is just content
    // the user chose not to make.
    function visualConceptSectionPendingIds(id) {
      const slots = tenantVisualConceptState?.slots || {};
      const pending = slot => durableImageUrl(slot?.imageUrl) && !durableImageUrl(slot?.approvedImageUrl);
      if (id === 'external') {
        return VISUAL_CONCEPT_EXTERNAL_SLOTS.filter(item => pending(slots[item.id])).map(item => item.id);
      }
      if (id === 'internal') {
        return Object.keys(slots).filter(key => isVisualConceptInteriorSlot(key) && pending(slots[key])).sort();
      }
      if (id === 'sketches') {
        return visualConceptSketchSourceIds().filter(srcId => pending(slots[srcId]?.sketch || {}));
      }
      return [];
    }

    // What still blocks a section approval. Plans lists its unapproved
    // diagrams by name (all three are required); the optional sections list
    // only their pending drafts — no drafts, nothing to certify, approvable.
    function visualConceptSectionBlockers(id) {
      const slots = tenantVisualConceptState?.slots || {};
      if (id === 'plans2d') {
        return VISUAL_CONCEPT_PLAN_KINDS
          .filter(item => !durableImageUrl(slots[item.id]?.approvedImageUrl))
          .map(item => visualConceptSlotLabel(item.id));
      }
      if (!VISUAL_CONCEPT_SECTION_IDS.includes(id)) return [id];
      return visualConceptSectionPendingIds(id).map(srcId => id === 'sketches'
        ? WFT('vcsketch.mirror_of', 'سكتش — {name}', { name: visualConceptSketchSourceLabel(srcId) })
        : visualConceptSketchSourceLabel(srcId));
    }

    // Reconciler: a section flag never outlives the content it certifies, and a
    // dropped flag closes every later section. Runs inside persist so every
    // mutation path (unapprove, delete, regenerate, revoke) inherits it.
    function visualConceptSyncSectionApprovals() {
      if (!tenantVisualConceptState || typeof tenantVisualConceptState !== 'object') return;
      const approvals = tenantVisualConceptState.sectionApprovals || (tenantVisualConceptState.sectionApprovals = {});
      let upstreamBroken = false;
      VISUAL_CONCEPT_SECTION_IDS.forEach(id => {
        approvals[id] = Boolean(approvals[id]) && !upstreamBroken && !visualConceptSectionBlockers(id).length;
        if (!approvals[id]) upstreamBroken = true;
      });
    }

    function renderVisualConceptSectionApprovalBar(id) {
      const approved = visualConceptSectionApproved(id);
      const locked = visualConceptSectionLocked(id);
      const blockers = approved ? [] : visualConceptSectionBlockers(id);
      let cls, text;
      if (approved) {
        cls = 'approved';
        text = WFT('vc.sec.approved', 'قسم معتمد');
      } else if (locked) {
        cls = 'locked';
        text = visualConceptSectionLockReason(id);
      } else if (blockers.length) {
        cls = 'waiting';
        text = WFT('vc.sec.waiting', 'بانتظار اعتماد: {items}', { items: blockers.join('، ') });
      } else {
        cls = 'ready';
        text = visualConceptSectionApprovedCount(id)
          ? WFT('vc.sec.ready', 'يوجد محتوى معتمد في القسم')
          : WFT('vc.sec.no_content', 'لا يوجد محتوى في القسم');
      }
      const button = locked ? ''
        : (approved
          ? '<button type="button" class="btn ghost small" data-visual-action="section-unapprove" data-visual-section="' + id + '">' + escapeHtml(WFT('vc.sec.unapprove', 'الغاء اعتماد القسم')) + '</button>'
          : '<button type="button" class="btn primary small" data-visual-action="section-approve" data-visual-section="' + id + '">' + escapeHtml(WFT('vc.sec.approve', 'اعتماد القسم')) + '</button>');
      return '<div class="visual-concept-section-approval ' + cls + '" data-visual-section-status="' + id + '">' +
        '<p class="visual-concept-section-status">' + escapeHtml(text) + '</p>' + button + '</div>';
    }

    function refreshVisualConceptSectionBars() {
      document.querySelectorAll('[data-visual-section-bar]').forEach(host => {
        host.innerHTML = renderVisualConceptSectionApprovalBar(host.getAttribute('data-visual-section-bar'));
      });
    }

    // Approve stays clickable while blocked — pressing it surfaces the missing
    // items in the lock notice instead of dying silently on a disabled button.
    function approveVisualConceptSection(id) {
      if (!VISUAL_CONCEPT_SECTION_IDS.includes(id)) return;
      if (visualConceptSectionLocked(id)) {
        showVisualConceptLockNotice(visualConceptSectionLockReason(id));
        return;
      }
      const blockers = visualConceptSectionBlockers(id);
      if (blockers.length) {
        showVisualConceptLockNotice(
          WFT('vc.sec.blocked', 'لا يكتمل اعتماد القسم قبل اعتماد: {items}', { items: blockers.join('، ') }));
        return;
      }
      tenantVisualConceptState.sectionApprovals[id] = true;
      markVisualConceptDirty();
      toast(WFT('vc.sec.approved_toast', 'تم اعتماد قسم {name}', { name: visualConceptSectionLabel(id) }));
      renderVisualConceptPage();
    }

    function unapproveVisualConceptSection(id) {
      if (!tenantVisualConceptState?.sectionApprovals?.[id]) return;
      tenantVisualConceptState.sectionApprovals[id] = false;
      // Downstream flags collapse inside persist's reconciliation pass.
      markVisualConceptDirty();
      toast(WFT('vc.sec.unapproved_toast', 'تم إلغاء اعتماد قسم {name}', { name: visualConceptSectionLabel(id) }));
      renderVisualConceptPage();
    }
