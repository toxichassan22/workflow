    // ── Designer run activity on the slide surface ───────────────────────────
    // The job poll already carries a live task list (targeted slide ids plus a
    // per-task status) for the checklist. This module mirrors the same state
    // onto the deck itself: a frosted veil over each card the designer is
    // executing on, plan markers on queued slides and matching thumbnail
    // chips — the preview reads as work in progress, not just a busy chat.

    let designerSlideActivityMap = null;
    let designerSlideActivityDeck = null;
    let designerSlideActivityNavKey = '';

    const DESIGNER_ACTIVITY_PRIORITY = {
      running: 5, pending: 4, failed: 3, skipped: 2, success: 1
    };

    function designerSlideActivityLabel(status, forCard) {
      const key = 'designer_agent.slide_' + (forCard ? 'veil' : 'state') + '_' + status;
      const fallbacks = {
        running: forCard ? 'المصمم يعمل على هذه الشريحة' : 'يُعدَّل',
        pending: 'في خطة التنفيذ',
        success: 'تم',
        failed: 'تعذّرت',
        skipped: 'تخطّى'
      };
      return designerAgentText(key, fallbacks[status] || status || '');
    }

    // Fold the polled task list (public_task dicts, `slides` carry slide ids)
    // plus an optional legacy activeSlideIndex into a Map<slideIndex, status>,
    // keeping the strongest status when several tasks touch the same slide.
    function designerSlideActivityCollect(tasks, activeIndex) {
      const map = new Map();
      const deck = Array.isArray(tenantSlidesData) ? tenantSlidesData : [];
      const put = (index, status) => {
        if (!Number.isInteger(index) || index < 0 || index >= deck.length) return;
        const prev = map.get(index);
        if (!prev || DESIGNER_ACTIVITY_PRIORITY[status] > DESIGNER_ACTIVITY_PRIORITY[prev]) {
          map.set(index, status);
        }
      };
      if (Array.isArray(tasks)) {
        const byId = new Map();
        deck.forEach((slide, i) => {
          if (slide && slide.id != null) byId.set(String(slide.id), i);
        });
        tasks.forEach(task => {
          const status = String(task?.status || 'pending');
          if (!DESIGNER_ACTIVITY_PRIORITY[status]) return;
          (Array.isArray(task?.slides) ? task.slides : []).forEach(id => {
            const index = byId.get(String(id));
            if (index !== undefined) put(index, status);
          });
        });
      }
      if (Number.isInteger(activeIndex)) put(activeIndex, 'running');
      return map;
    }

    function applyDesignerSlideActivity() {
      // A snapshot only describes the deck it was collected against — after a
      // presentation switch tenantSlidesData is a different array and the old
      // positions would mark the wrong slides.
      const map = (designerSlideActivityMap && designerSlideActivityDeck === tenantSlidesData)
        ? designerSlideActivityMap : new Map();
      document.querySelectorAll('.ge-slide-card').forEach((card, index) => {
        const status = map.get(index) || '';
        if (status) card.dataset.designerState = status;
        else card.removeAttribute('data-designer-state');
        let veil = card.querySelector(':scope > .designer-slide-veil');
        if (status === 'running') {
          if (!veil) {
            veil = document.createElement('div');
            veil.className = 'designer-slide-veil';
            veil.innerHTML = '<span class="designer-slide-veil-label">' +
              escapeHtml(designerSlideActivityLabel('running', true)) + '</span>';
            // The veil owns the card while the designer owns the slide — a
            // click through the frosted glass must not open an inline edit the
            // arriving result would silently overwrite.
            veil.addEventListener('click', event => event.stopPropagation());
            card.appendChild(veil);
          }
        } else if (veil) {
          veil.remove();
        }
      });
      document.querySelectorAll('#tenantSlidesSidebar .ge-thumb').forEach((thumb, index) => {
        const status = map.get(index) || '';
        if (status) thumb.dataset.designerState = status;
        else thumb.removeAttribute('data-designer-state');
        let chip = thumb.querySelector('.ge-thumb-designer-state');
        if (status) {
          if (!chip) {
            chip = document.createElement('span');
            chip.className = 'ge-thumb-designer-state';
            thumb.appendChild(chip);
          }
          chip.textContent = designerSlideActivityLabel(status, false);
        } else if (chip) {
          chip.remove();
        }
      });
    }

    function updateDesignerSlideActivity(tasks, activeIndex = null) {
      designerSlideActivityMap = designerSlideActivityCollect(tasks, activeIndex);
      designerSlideActivityDeck = tenantSlidesData;
      applyDesignerSlideActivity();
      // Bring the slide being worked on into view once per running-set change —
      // the same auto-navigation the legacy path performs via
      // result.activeSlideIndex, derived here from the agent task list.
      const running = [...designerSlideActivityMap.entries()]
        .filter(([, status]) => status === 'running')
        .map(([index]) => index)
        .sort((a, b) => a - b);
      const navKey = running.join(',');
      if (navKey && navKey !== designerSlideActivityNavKey) {
        designerSlideActivityNavKey = navKey;
        if (typeof selectTenantSlide === 'function') selectTenantSlide(running[0]);
      } else if (!navKey) {
        designerSlideActivityNavKey = '';
      }
    }

    // Preview rebuilds wipe the decorated nodes; the last polled snapshot
    // repaints them so marks survive re-renders mid-run.
    function reapplyDesignerSlideActivity() {
      if (!designerSlideActivityMap || !designerSlideActivityMap.size) return;
      if (designerSlideActivityDeck !== tenantSlidesData) return;
      applyDesignerSlideActivity();
    }

    function clearDesignerSlideActivity() {
      designerSlideActivityMap = null;
      designerSlideActivityDeck = null;
      designerSlideActivityNavKey = '';
      document.querySelectorAll('[data-designer-state]').forEach(el => el.removeAttribute('data-designer-state'));
      document.querySelectorAll('.designer-slide-veil').forEach(el => el.remove());
      document.querySelectorAll('.ge-thumb-designer-state').forEach(el => el.remove());
    }
