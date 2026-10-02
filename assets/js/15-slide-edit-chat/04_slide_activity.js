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
        pending: forCard ? 'بانتظار تعديل المصمم' : 'في خطة التنفيذ',
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
      // A pending mark on a proposed plan is only a footprint preview — dashed
      // border, slide stays inspectable. Once the run is live every slide the
      // plan still owes work locks behind the same veil as the running one;
      // only a resolved task reopens it for manual editing.
      const planPreview = !!tenantDesignerPendingPlan;
      document.querySelectorAll('.ge-slide-card').forEach((card, index) => {
        const status = map.get(index) || '';
        if (status) card.dataset.designerState = status;
        else card.removeAttribute('data-designer-state');
        const locked = status === 'running' || (status === 'pending' && !planPreview);
        let veil = card.querySelector(':scope > .designer-slide-veil');
        if (locked) {
          if (!veil) {
            veil = document.createElement('div');
            veil.className = 'designer-slide-veil';
            // The veil owns the card while the designer owns the slide — a
            // click through the frosted glass must not open an inline edit the
            // arriving result would silently overwrite.
            veil.addEventListener('click', event => event.stopPropagation());
            card.appendChild(veil);
            const ae = document.activeElement;
            if (ae && card.contains(ae) && ae.blur) ae.blur();
          }
          if (veil.dataset.state !== status) {
            veil.dataset.state = status;
            veil.innerHTML = '<span class="designer-slide-veil-label">' +
              escapeHtml(designerSlideActivityLabel(status, true)) + '</span>';
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

    // ── Live apply + whole-run undo baseline ─────────────────────────────────
    // A completed task's slides land on the deck mid-run: the card re-renders
    // in place and its veil lifts instead of waiting for the job to finish.
    // designerPreRunDeckJson keeps the deck as it stood when the request was
    // sent so a single undo rolls back the whole run, not one poll's worth.

    let designerPreRunDeckJson = null;

    function designerNotePreRunDeck() {
      try {
        designerPreRunDeckJson = JSON.stringify(
          Array.isArray(tenantSlidesData) ? tenantSlidesData : []);
      } catch (error) {
        designerPreRunDeckJson = null;
      }
    }

    function designerPreRunDeck() {
      if (!designerPreRunDeckJson) return null;
      try {
        const parsed = JSON.parse(designerPreRunDeckJson);
        return Array.isArray(parsed) ? parsed : null;
      } catch (error) {
        return null;
      }
    }

    function clearDesignerPreRunDeck() {
      designerPreRunDeckJson = null;
    }

    function applyDesignerLiveSlideUpdates(updates) {
      if (!updates || typeof updates !== 'object') return 0;
      const deck = Array.isArray(tenantSlidesData) ? tenantSlidesData : [];
      const byId = new Map();
      deck.forEach((slide, i) => {
        if (slide && slide.id != null) byId.set(String(slide.id), i);
      });
      const thumbs = document.querySelectorAll('#tenantSlidesSidebar .ge-thumb');
      let applied = 0;
      Object.entries(updates).forEach(([slideId, patch]) => {
        const index = byId.get(String(slideId));
        if (index === undefined || !patch || typeof patch !== 'object') return;
        // An open manual edit session owns the card — the final apply resolves it.
        if (typeof getSlideEditSession === 'function' && getSlideEditSession(index)) return;
        const slide = deck[index];
        const nextHtml = typeof patch.html === 'string' ? patch.html : null;
        const nextTitle = patch.title != null ? String(patch.title) : null;
        if ((nextHtml === null || nextHtml === slide.html)
            && (nextTitle === null || nextTitle === String(slide.title || ''))) return;
        if (nextTitle !== null) slide.title = nextTitle;
        if (nextHtml !== null) slide.html = nextHtml;
        const card = document.getElementById('slide-card-' + index);
        const stage = card && card.querySelector('.tenant-slide-stage');
        if (stage && nextHtml !== null) {
          const fallback = '<div class="slide" style="padding:40px;font-size:24px;background:#fff">' +
            escapeHtml(slide.title || '') + '</div>';
          stage.innerHTML = processSlideHtmlClient(slide.html, slide.type) || fallback;
          if (!stage.querySelector('.slide')) stage.innerHTML = fallback;
          autoFitSlideContent(stage);
          repairSlideTextContrast(stage);
          enableSlideInlineEditing(stage, index);
          enableSlideElementDragging(stage, index);
          restoreSlideEditSelection(stage, index);
        }
        const thumb = thumbs[index];
        if (thumb && nextTitle !== null) {
          const titleEl = thumb.querySelector('.ge-thumb-title');
          if (titleEl) {
            titleEl.textContent = nextTitle || 'شريحة بدون عنوان';
            titleEl.setAttribute('title', nextTitle);
          }
        }
        // Lifting the veil reads as "this slide is done" even if the checklist
        // tick lands one poll later.
        if (designerSlideActivityMap) {
          designerSlideActivityMap.set(index, 'success');
          designerSlideActivityDeck = tenantSlidesData;
        }
        applied++;
      });
      if (applied) applyDesignerSlideActivity();
      return applied;
    }

    // ── Per-slide drift baselines ────────────────────────────────────────────
    // The workspace signature used to cover the whole deck, so a manual edit
    // on a slide the run never touched failed the apply with «العرض تغير أثناء
    // تنفيذ المهمة». Baselines are per slide id instead: at apply time only a
    // slide the run rewrote or removed counts as a conflict, and edits on any
    // other slide merge back into the returned deck.

    function designerChatStableSerialize(value) {
      if (Array.isArray(value)) {
        return '[' + value.map(designerChatStableSerialize).join(',') + ']';
      }
      if (value && typeof value === 'object') {
        return '{' + Object.keys(value).sort()
          .map(key => JSON.stringify(key) + ':' + designerChatStableSerialize(value[key]))
          .join(',') + '}';
      }
      return JSON.stringify(value === undefined ? null : value);
    }

    function designerChatHashSignature(value) {
      const serialized = designerChatStableSerialize(value);
      let hash = 2166136261;
      for (let index = 0; index < serialized.length; index++) {
        hash ^= serialized.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
      }
      return serialized.length + ':' + (hash >>> 0).toString(16);
    }

    // A slide signature ignores what a renumber pass rewrites mechanically —
    // the footer counter element, index entries and the server-side preserve
    // flags — or an insert that only shifts a slide would read as the run
    // owning it and a user edit there would falsely conflict.
    const DESIGNER_SLIDE_VOLATILE_KEYS = new Set([
      'index_entries', 'is_custom', 'keep_html', 'custom_html', 'number', 'position', 'page'
    ]);

    function designerChatSlideSignature(slide) {
      if (!slide || typeof slide !== 'object') return designerChatHashSignature(slide);
      const stable = {};
      Object.keys(slide).forEach(key => {
        if (key.charAt(0) === '_' || DESIGNER_SLIDE_VOLATILE_KEYS.has(key)) return;
        let value = slide[key];
        if (key === 'html' && typeof value === 'string') {
          value = value.replace(
            /<([a-z][\w:-]*)\b[^>]*\bdata-slide-counter\s*=\s*["'][^"']*["'][^>]*>[\s\S]*?<\/\1>/gi,
            '');
        }
        stable[key] = value;
      });
      return designerChatHashSignature(stable);
    }

    // {slideId: signature} in deck order — null when a slide cannot be keyed,
    // which sends the apply path back to the whole-deck signature check.
    function designerChatSlideSignatures(slides = tenantSlidesData) {
      const source = Array.isArray(slides) ? slides : [];
      const signatures = {};
      for (const slide of source) {
        const id = slide && slide.id;
        if (typeof id !== 'string' || !id) return null;
        signatures[id] = designerChatSlideSignature(slide);
      }
      return signatures;
    }

    function designerChatCreativeSignatures() {
      const source = (typeof tenantCreativeImages !== 'undefined'
          && tenantCreativeImages && typeof tenantCreativeImages === 'object'
          && !Array.isArray(tenantCreativeImages)) ? tenantCreativeImages : {};
      const signatures = {};
      Object.keys(source).forEach(key => {
        signatures[key] = designerChatHashSignature(source[key]);
      });
      return signatures;
    }

    // A live-applied task rewrote these slides on this deck — move their
    // baselines forward so the run's own writes never read as drift. A slide
    // an open edit session owns kept its content, so its baseline stays and a
    // later conflict is still detected.
    function designerChatAdvanceSlideBaselines(metadata, applied) {
      const signatures = metadata && metadata.slideSignatures;
      if (!signatures || typeof signatures !== 'object' || !applied || typeof applied !== 'object') return;
      const deck = Array.isArray(tenantSlidesData) ? tenantSlidesData : [];
      Object.keys(applied).forEach(slideId => {
        const patch = applied[slideId];
        const slide = deck.find(item => String(item && item.id) === String(slideId));
        const patchHtml = patch && typeof patch.html === 'string' ? patch.html : null;
        const patchTitle = patch && patch.title != null ? String(patch.title) : null;
        if (!slide || (patchHtml !== null && slide.html !== patchHtml)
            || (patchTitle !== null && String(slide.title || '') !== patchTitle)) return;
        signatures[String(slideId)] = designerChatSlideSignature(slide);
      });
    }

    // Merge the returned deck over the live one by slide id. A slide the run
    // left untouched keeps the user's mid-run version; a slide the run rewrote
    // or removed while its content drifted from the last designer-written
    // state is a real conflict and keeps the old refuse behavior.
    function designerChatMergeJobSlides(jobMeta, incoming) {
      const deck = Array.isArray(tenantSlidesData) ? tenantSlidesData : [];
      const signatures = jobMeta && jobMeta.slideSignatures;
      const wholeDeckConflict = () => !!(jobMeta && jobMeta.workspaceSignature
        && jobMeta.workspaceSignature !== designerChatWorkspaceSignature());
      if (!signatures || typeof signatures !== 'object') {
        return { conflict: wholeDeckConflict(), slides: incoming };
      }
      const currentById = new Map();
      const currentIndexById = new Map();
      deck.forEach((slide, index) => {
        const id = slide && slide.id;
        if (typeof id === 'string' && id && !currentById.has(id)) {
          currentById.set(id, slide);
          currentIndexById.set(id, index);
        }
      });
      const incomingById = new Map();
      incoming.forEach(slide => {
        const id = slide && slide.id;
        if (typeof id === 'string' && id) incomingById.set(id, slide);
      });
      const baselineIds = Object.keys(signatures);
      if (baselineIds.length && incoming.length
          && !incoming.some(slide => slide && signatures[String(slide.id)] !== undefined)) {
        // The id spaces diverged entirely — nothing to key the merge against.
        return { conflict: wholeDeckConflict(), slides: incoming };
      }
      const jobChangedIds = new Set();
      for (const id of baselineIds) {
        const base = signatures[id];
        const inc = incomingById.get(id);
        if (inc && designerChatSlideSignature(inc) === base) continue;
        jobChangedIds.add(id);  // the run rewrote it or removed it
        const current = currentById.get(id);
        if (!inc && !current) continue;  // both sides removed it — nothing to fight over
        const drifted = !current
          || designerChatSlideSignature(current) !== base
          || (typeof getSlideEditSession === 'function'
              && !!getSlideEditSession(currentIndexById.get(id)));
        if (drifted) return { conflict: true, slides: deck };
      }
      const incomingIds = new Set();
      incoming.forEach(slide => {
        const id = slide && slide.id;
        if (typeof id === 'string' && id) incomingIds.add(id);
      });
      const jobAdded = incoming.some(slide => {
        const id = slide && slide.id;
        return !(typeof id === 'string' && id) || signatures[id] === undefined;
      });
      const sharedBaselineOrder = baselineIds.filter(id => incomingIds.has(id));
      const sharedIncomingOrder = incoming
        .map(slide => slide && slide.id)
        .filter(id => typeof id === 'string' && signatures[id] !== undefined);
      const structural = jobAdded || sharedBaselineOrder.length !== baselineIds.length
        || sharedBaselineOrder.some((id, index) => id !== sharedIncomingOrder[index]);
      if (!structural) {
        // Pure content edits: the user's deck order stays authoritative.
        return {
          conflict: false,
          slides: deck.map(slide => {
            const id = slide && slide.id;
            return (typeof id === 'string' && id && jobChangedIds.has(id))
              ? incomingById.get(id) : slide;
          })
        };
      }
      // Structural runs: the returned order is the run's intent, but untouched
      // slides still merge the user's version back in by id.
      const merged = [];
      incoming.forEach(inc => {
        const id = inc && inc.id;
        const keyed = typeof id === 'string' && id;
        if (keyed && signatures[id] !== undefined) {
          const current = currentById.get(id);
          if (!current) return;  // the user deleted it; the run only echoed it
          if (designerChatSlideSignature(inc) === signatures[id]) {
            merged.push(current);
            return;
          }
        }
        merged.push(inc);
      });
      // Slides the user added mid-run exist in neither the baseline nor the
      // result — reinsert them where they sit now.
      deck.forEach((slide, index) => {
        const id = slide && slide.id;
        const keyed = typeof id === 'string' && id;
        if (keyed && (signatures[id] !== undefined || incomingIds.has(id))) return;
        merged.splice(Math.min(index, merged.length), 0, slide);
      });
      return { conflict: false, slides: merged };
    }

    // Editor state is keyed by numeric position (edit sessions, the inline/
    // element edit flags, the active/chat slide). A structural merge can move
    // a slide to a new index, so re-key that state by slide id — otherwise an
    // open edit session ends up parked on whichever slide took its old spot.
    function designerChatRemapSlideState(prevSlides, nextSlides) {
      const prevIds = (Array.isArray(prevSlides) ? prevSlides : []).map(s => s && s.id);
      const nextIndexById = {};
      (Array.isArray(nextSlides) ? nextSlides : []).forEach((slide, i) => {
        const id = slide && slide.id;
        if (id && nextIndexById[id] === undefined) nextIndexById[id] = i;
      });
      const nextIndexFor = oldIndex => {
        const id = prevIds[oldIndex];
        return id !== undefined && id !== null ? nextIndexById[id] : undefined;
      };
      const remapTable = table => {
        if (!table || typeof table !== 'object') return;
        const entries = Object.keys(table).map(k => [Number(k), table[k]]);
        Object.keys(table).forEach(k => { delete table[k]; });
        entries.forEach(([oldIndex, value]) => {
          const nextIndex = nextIndexFor(oldIndex);
          if (nextIndex !== undefined) table[nextIndex] = value;
        });
      };
      if (typeof slideEditSessions === 'object') remapTable(slideEditSessions);
      if (typeof slideInlineEditStates === 'object') remapTable(slideInlineEditStates);
      if (typeof slideElementEditStates === 'object') remapTable(slideElementEditStates);
      const nextActive = nextIndexFor(activeSlideIndex);
      if (nextActive !== undefined) activeSlideIndex = nextActive;
      if (typeof tenantChatSlideIndex !== 'undefined') {
        const nextChat = nextIndexFor(tenantChatSlideIndex);
        if (nextChat !== undefined) tenantChatSlideIndex = nextChat;
      }
    }

    // creativeImages is keyed like the deck: the run's new and updated keys
    // land, but a key the user changed or added mid-run keeps the user value.
    function designerChatMergeCreativeImages(jobMeta, incoming) {
      if (!incoming || typeof incoming !== 'object' || Array.isArray(incoming)) return incoming;
      const baseline = jobMeta && jobMeta.creativeSignatures;
      const current = (typeof tenantCreativeImages !== 'undefined'
          && tenantCreativeImages && typeof tenantCreativeImages === 'object'
          && !Array.isArray(tenantCreativeImages)) ? tenantCreativeImages : {};
      if (!baseline || typeof baseline !== 'object') return incoming;
      const merged = { ...incoming };
      Object.keys(current).forEach(key => {
        if (!Object.prototype.hasOwnProperty.call(baseline, key)) {
          if (!Object.prototype.hasOwnProperty.call(merged, key)) merged[key] = current[key];
          return;
        }
        if (designerChatHashSignature(current[key]) !== baseline[key]) merged[key] = current[key];
      });
      return merged;
    }
