/* 12-files-media/02a_visual_concept_sections.js — Visual Concept section approvals */

    /* ── Major-section approvals, the workflow's second tier. The workspace runs
       as a strict sequence — plans → exterior → interior → sketches — and each
       leg carries one durable flag that certifies every generated item inside
       it. Approving a leg is refused while any of its items is unapproved, and
       each flag unlocks only the next leg. The flags live in
       tenantVisualConceptState.sectionApprovals and are reconciled on every
       persist, so revoked or regenerated content can never leave a stale
       approval behind. ── */

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

    // The generated items a section approval certifies. Anything on this list
    // without an approved artifact keeps approval refused — and drops an
    // existing flag on the next persist pass. An empty section has nothing to
    // certify, so it stays refused too.
    function visualConceptSectionItemCount(id) {
      const slots = tenantVisualConceptState?.slots || {};
      if (id === 'plans2d') return VISUAL_CONCEPT_PLAN_KINDS.length;
      if (id === 'external') return VISUAL_CONCEPT_EXTERNAL_SLOTS.length;
      if (id === 'internal') return Object.keys(slots).filter(isVisualConceptInteriorSlot).length;
      if (id === 'sketches') return visualConceptSketchSourceIds().length;
      return 0;
    }

    function visualConceptSectionBlockers(id) {
      const slots = tenantVisualConceptState?.slots || {};
      const labels = [];
      if (id === 'plans2d') {
        VISUAL_CONCEPT_PLAN_KINDS.forEach(item => {
          if (!durableImageUrl(slots[item.id]?.approvedImageUrl)) labels.push(visualConceptSlotLabel(item.id));
        });
      } else if (id === 'external') {
        VISUAL_CONCEPT_EXTERNAL_SLOTS.forEach(item => {
          if (!durableImageUrl(slots[item.id]?.approvedImageUrl)) labels.push(visualConceptSlotLabel(item.id));
        });
      } else if (id === 'internal') {
        Object.keys(slots).filter(isVisualConceptInteriorSlot).sort().forEach(viewId => {
          if (!durableImageUrl(slots[viewId]?.approvedImageUrl)) labels.push(visualConceptSketchSourceLabel(viewId));
        });
      } else if (id === 'sketches') {
        visualConceptSketchSourceIds().forEach(srcId => {
          const sketch = slots[srcId]?.sketch || {};
          if (sketch.status !== 'approved' || !durableImageUrl(sketch.approvedImageUrl)) {
            labels.push(visualConceptSketchSourceLabel(srcId));
          }
        });
      } else {
        return [id];
      }
      if (!labels.length && !visualConceptSectionItemCount(id)) {
        labels.push(WFT('vc.sec.empty', 'لا يوجد محتوى'));
      }
      return labels;
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
        text = WFT('vc.sec.ready', 'اكتمل اعتماد محتوى القسم');
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
