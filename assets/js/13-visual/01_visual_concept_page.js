/* 13-visual.js - index.html lines 21642-23155, shared global scope, classic scripts in order */

    // Card actions and the zoom lightbox are delegated once on the document:
    // every render replaces innerHTML, so listeners bound per-element died
    // silently whenever a subtree re-rendered after the binding pass.
    document.addEventListener('click', event => {
      const button = event.target.closest('[data-visual-action]');
      if (button && !button.disabled) {
        const action = button.getAttribute('data-visual-action');
        const slotId = button.getAttribute('data-visual-slot');
        if (action === 'prompt') generateVisualConceptPrompt(slotId);
        else if (action === 'generate') generateVisualConceptImage(slotId);
        else if (action === 'approve') approveVisualConceptImage(slotId);
        else if (action === 'unapprove') unapproveVisualConceptImage(slotId);
        else if (action === 'delete-image') deleteVisualConceptSlotImage(slotId);
        else if (action === 'delete-interior-field') deleteVisualConceptInteriorField(slotId);
        else if (action === 'delete-plan') deleteVisualConceptPlan(slotId);
        else if (action === 'chat') sendVisualConceptChat(slotId);
        else if (action === 'add-interior') addVisualConceptInteriorView();
        else if (action === 'set-mode') {
          const targetMode = button.getAttribute('data-visual-mode');
          const slot = tenantVisualConceptState?.slots?.[slotId];
          if (slotId && slot && (targetMode === 'ai' || targetMode === 'upload')) {
            const hasImg = Boolean(slot.approvedImageUrl || slot.imageUrl || slot.sourceFileId);
            if (hasImg && targetMode !== slot.mode) {
              toast('يجب حذف الصورة الحالية أولاً لتغيير النمط.');
              return;
            }
            slot.mode = targetMode;
            markVisualConceptDirty();
            renderVisualConceptPage();
          }
        }
        return;
      }
      const zoom = event.target.closest('[data-visual-zoom]');
      if (zoom && event.target.tagName !== 'INPUT' && event.target.tagName !== 'TEXTAREA') {
        const url = zoom.getAttribute('data-visual-zoom');
        if (url) openVisualConceptLightbox(url, zoom.getAttribute('data-visual-title'));
      }
    });

    function renderVisualConceptPage() {
      const host = document.getElementById('visualConceptWorkspace');
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      persistVisualConceptDraftState();
      updateVisualConceptHomeCards();
      if (!host) return;
      renderVisualConceptStyleReference();
      const plansApproved = visualConceptPlansApproved();
      const coverApproved = Boolean(tenantVisualConceptState.slots.cover.approvedImageUrl);
      const coverHtml = renderVisualConceptSlot(VISUAL_CONCEPT_SLOTS[0], !plansApproved);
      const angleHtml = VISUAL_CONCEPT_EXTERNAL_SLOTS.slice(1).map(item => renderVisualConceptSlot(item, !plansApproved || !coverApproved)).join('');
      const lockHint = !plansApproved
        ? '<p class="tenant-hint">التصورات الخارجية مقفلة حتى اعتماد المخططات الثلاثة.</p>'
        : (coverApproved ? '' : '<p class="tenant-hint">زوايا التصور الخارجي مقفلة حتى اعتماد الصورة الرئيسية.</p>');
      host.innerHTML = coverHtml +
        '<div class="visual-concept-stack">' +
        lockHint +
        angleHtml + '</div>';
      renderVisualConceptInteriorWorkspace();
      renderVisualConceptPlans();
      const bindRoot = document.getElementById('section-visual-concept') || document.getElementById('tenantVisualConceptPage') || host;
      bindRoot.querySelectorAll('[data-visual-prompt]').forEach(input => {
        input.addEventListener('input', () => {
          const slotId = input.getAttribute('data-visual-prompt');
          tenantVisualConceptState.slots[slotId].prompt = input.value;
          markVisualConceptDirty();
        });
      });
      bindRoot.querySelectorAll('[data-visual-caption]').forEach(input => {
        input.addEventListener('input', () => {
          const slotId = input.getAttribute('data-visual-caption');
          const slot = tenantVisualConceptState.slots[slotId];
          if (!slot) return;
          slot.caption = String(input.value || '').slice(0, 400);
          markVisualConceptDirty();
        });
      });
      bindRoot.querySelectorAll('[data-visual-title]').forEach(input => {
        input.addEventListener('input', () => {
          const slotId = input.getAttribute('data-visual-title');
          const slot = tenantVisualConceptState.slots[slotId];
          if (!slot) return;
          slot.label = String(input.value || '').slice(0, 80);
          markVisualConceptDirty();
        });
      });
      bindRoot.querySelectorAll('[data-visual-upload]').forEach(input => {
        input.addEventListener('change', () => uploadVisualConceptSlotImage(input.getAttribute('data-visual-upload'), input));
      });
      repairVisualConceptStoredImages();
    }

    // A file saved before uploads were published carries blob: URLs, which are dead in every
    // later session. The uploaded image itself is still on the server, so each slot and plan
    // is republished from its file id and the stored URL is healed in place.
    let visualConceptImageRepairRunning = false;
    async function repairVisualConceptStoredImages() {
      if (visualConceptImageRepairRunning) {
        while (visualConceptImageRepairRunning) await new Promise(resolve => setTimeout(resolve, 50));
        return;
      }
      const slots = tenantVisualConceptState?.slots || {};
      const slotIds = Object.keys(slots).filter(id => {
        const slot = slots[id];
        if (!slot || !slot.sourceFileId) return false;
        if (isSessionOnlyImageUrl(slot.imageUrl) || isSessionOnlyImageUrl(slot.approvedImageUrl)) return true;
        return !slot.imageUrl && !slot.approvedImageUrl;
      });
      const plans = visualConceptPlans().filter(plan => plan.fileId && !plan.imageUrl);
      if (!slotIds.length && !plans.length) return;
      visualConceptImageRepairRunning = true;
      let healed = 0;
      try {
        for (const id of slotIds) {
          const slot = tenantVisualConceptState.slots[id];
          if (!slot) continue;
          let url = '';
          try { url = await publishProjectFileImageUrl(slot.sourceFileId); } catch (error) { url = ''; }
          if (!url) continue;
          slot.imageUrl = url;
          if (slot.status === 'approved' || isSessionOnlyImageUrl(slot.approvedImageUrl)) slot.approvedImageUrl = url;
          healed += 1;
        }
        for (const plan of plans) {
          let url = '';
          try { url = await publishProjectFileImageUrl(plan.fileId); } catch (error) { url = ''; }
          if (!url) continue;
          plan.imageUrl = url;
          const planSlot = tenantVisualConceptState.slots?.[plan.id];
          if (planSlot) {
            planSlot.imageUrl = url;
            if (!planSlot.sourceFileId) planSlot.sourceFileId = plan.fileId;
          }
          healed += 1;
        }
      } finally {
        visualConceptImageRepairRunning = false;
      }
      if (!healed) return;
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    async function uploadVisualConceptSlotImage(slotId, input) {
      const file = input?.files?.[0];
      if (!file || !slotId) return;
      try {
        input.dataset.projectFileType = 'visual_reference';
        const uploaded = await uploadTenantProjectFileInput(input, 'visual_style_reference');
        const fileRecord = Array.isArray(uploaded) ? uploaded[0] : uploaded;
        const fileId = fileRecord?.id || fileRecord;
        if (!fileId) throw new Error('تعذر رفع الصورة');
        if (!tenantVisualConceptState.slots[slotId]) tenantVisualConceptState.slots[slotId] = emptyVisualConceptSlot(slotId);
        const liveSlot = () => tenantVisualConceptState.slots[slotId];
        liveSlot().mode = 'upload';
        liveSlot().sourceFileId = fileId;
        liveSlot().sourceFileName = fileRecord?.originalName || file.name || '';
        liveSlot().imageUrl = await publishProjectFileImageUrl(fileId);
        liveSlot().approvedImageUrl = '';
        liveSlot().status = 'review';
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast('تم رفع الصورة');
      } catch (error) {
        toast(error.message || 'تعذر رفع الصورة');
      } finally {
        if (input) input.value = '';
      }
    }

    function showVisualConceptView(view) {
      const allowed = new Set(['home', 'external', 'internal', 'plans2d']);
      const next = allowed.has(view) ? view : 'home';
      document.querySelectorAll('#section-visual-concept [data-visual-concept-view], #tenantVisualConceptPage [data-visual-concept-view]').forEach(node => {
        node.hidden = node.dataset.visualConceptView !== next;
      });
      if (getTenantNavigationState()?.pageId === 'tenantVisualConceptPage') {
        saveTenantNavigationState('tenantVisualConceptPage', { visualConceptView: next });
      }
    }

    function showVisualConceptMissing(message) {
      const box = document.getElementById('visualConceptMissing');
      if (!box) return;
      if (!message) {
        box.hidden = true;
        box.textContent = '';
        return;
      }
      box.hidden = false;
      box.textContent = message;
    }

    async function refreshVisualConceptPreflight() {
      try {
        const payload = await collectVisualConceptPayload('cover');
        const response = await api('POST', '/api/visual-concept/preflight', payload);
        if (!response?.success) showVisualConceptMissing(visualConceptMissingMessage(response));
        else showVisualConceptMissing('');
        return response;
      } catch (error) {
        showVisualConceptMissing(error.message || 'تعذر مراجعة بيانات التصور البصري');
        return null;
      }
    }

    async function openTenantVisualConceptPage() {
      tenantVisualConceptState = normalizeVisualConceptState(tenantProjectData.visual_concept || tenantVisualConceptState);
      persistVisualConceptDraftState();
      showTenantPage('tenantProjectPage');
      showSection('section-visual-concept');
      renderVisualConceptPage();
      showVisualConceptView(getTenantNavigationState()?.visualConceptView || 'home');
      await refreshVisualConceptPreflight();
    }

    async function generateVisualConceptPrompt(slotId, instruction) {
      if (!hasPermission('generate_images')) { toast('لا تملك صلاحية توليد الصور'); return; }
      if (visualConceptSlotLocked(slotId)) {
        toast(visualConceptLockMessage(slotId));
        return;
      }
      showLoader('جاري إنشاء وصف التصور البصري', 'يتم قراءة بيانات المشروع والصور المرجعية...');
      try {
        const payload = await collectVisualConceptPayload(slotId);
        if (instruction) payload.instruction = instruction;
        const response = await api('POST', '/api/visual-concept/prompt', payload);
        hideLoader();
        if (!response?.success || !response.prompt) {
          const message = visualConceptMissingMessage(response) || response?.error || 'تعذر إنشاء الوصف';
          showVisualConceptMissing(visualConceptMissingMessage(response));
          toast(message);
          return;
        }
        showVisualConceptMissing('');
        tenantVisualConceptState.slots[slotId].prompt = response.prompt;
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast('تم تجهيز وصف ' + visualConceptSlotLabel(slotId));
      } catch (error) {
        hideLoader();
        toast(error.message || 'تعذر إنشاء الوصف');
      }
    }

    async function generateVisualConceptImage(slotId) {
      if (!hasPermission('generate_images')) { toast('لا تملك صلاحية توليد الصور'); return; }
      // Never hold a slot reference across an await or a render: renderVisualConceptPage
      // reassigns tenantVisualConceptState through normalizeVisualConceptState, so a
      // captured slot is detached and the generated image was written to a dead object.
      const liveSlot = () => tenantVisualConceptState.slots[slotId];
      if (!liveSlot() || liveSlot().status === 'generating') return;
      if (visualConceptSlotLocked(slotId)) {
        toast(visualConceptLockMessage(slotId));
        return;
      }
      if (!liveSlot().prompt) {
        await generateVisualConceptPrompt(slotId);
      }
      if (!liveSlot() || !liveSlot().prompt) return;
      const previousImage = liveSlot().imageUrl || liveSlot().approvedImageUrl;
      liveSlot().status = 'generating';
      renderVisualConceptPage();
      showLoader('جاري توليد التصور البصري', 'يتم توليد ' + visualConceptSlotLabel(slotId) + '...');
      try {
        const payload = await collectVisualConceptPayload(slotId);
        const response = await apiWithTimeout('POST', '/api/visual-concept/generate', payload, 180000, 'انتهت مهلة توليد الصورة؛ أعد المحاولة.');
        hideLoader();
        if (!response?.success || !response.image) {
          liveSlot().status = previousImage ? 'review' : 'pending';
          renderVisualConceptPage();
          const message = visualConceptMissingMessage(response) || response?.error || 'تعذر توليد الصورة';
          showVisualConceptMissing(visualConceptMissingMessage(response));
          toast(message);
          return;
        }
        showVisualConceptMissing('');
        liveSlot().prompt = response.prompt || liveSlot().prompt;
        liveSlot().imageUrl = visualConceptImageUrl(response.image);
        liveSlot().approvedImageUrl = '';
        liveSlot().status = 'review';
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast('تم توليد المعاينة. اضغط اعتماد الصورة لتثبيتها.');
      } catch (error) {
        hideLoader();
        liveSlot().status = previousImage ? 'review' : 'pending';
        renderVisualConceptPage();
        toast(error.message || 'تعذر توليد الصورة');
      }
    }

    function approveVisualConceptImage(slotId) {
      const slot = tenantVisualConceptState.slots[slotId];
      const image = slot.imageUrl || slot.approvedImageUrl;
      if (!image) {
        toast('ولّد الصورة أولاً حتى يمكن اعتمادها');
        return;
      }
      const caption = String(document.querySelector('[data-visual-caption="' + slotId + '"]')?.value || slot.caption || '').trim();
      slot.caption = caption || visualConceptSlotLabel(slotId);
      slot.approvedImageUrl = image;
      slot.status = 'approved';
      markVisualConceptDirty();
      renderVisualConceptPage();
      toast('تم اعتماد ' + visualConceptSlotLabel(slotId));
    }

    function visualConceptSlotLabel(slotId) {
      const custom = String(tenantVisualConceptState?.slots?.[slotId]?.label || '').trim();
      if (custom) return custom;
      return visualConceptDefaultSlotLabel(slotId);
    }

    function unapproveVisualConceptImage(slotId) {
      const slot = tenantVisualConceptState.slots[slotId];
      if (!slot || slot.status !== 'approved') return;
      // The cover gates every other slot, so releasing it re-locks the angles and interiors.
      slot.imageUrl = slot.imageUrl || slot.approvedImageUrl;
      slot.approvedImageUrl = '';
      slot.status = slot.imageUrl ? 'review' : 'pending';
      // Slides and the generation payload read this mirror as the approved cover.
      if (slotId === 'cover' && tenantCreativeImages) tenantCreativeImages.cover = '';
      markVisualConceptDirty();
      renderVisualConceptPage();
      toast('تم إلغاء اعتماد ' + visualConceptSlotLabel(slotId));
    }

    function deleteVisualConceptInteriorField(slotId) {
      if (!isVisualConceptInteriorSlot(slotId) || !slotId.includes('::')) return;
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      delete tenantVisualConceptState.slots[slotId];
      const deleted = new Set(tenantVisualConceptState.deletedInteriorSlots || []);
      deleted.add(slotId);
      tenantVisualConceptState.deletedInteriorSlots = Array.from(deleted);
      markVisualConceptDirty();
      renderVisualConceptPage();
      toast('تم حذف حقل الصورة الداخلية');
    }

    function deleteVisualConceptSlotImage(slotId) {
      const slot = tenantVisualConceptState?.slots?.[slotId];
      if (!slot) return;
      slot.imageUrl = '';
      slot.approvedImageUrl = '';
      slot.sourceFileId = '';
      slot.sourceFileName = '';
      slot.status = 'empty';
      if (slotId === 'cover' && tenantCreativeImages) {
        tenantCreativeImages.cover = '';
        tenantCreativeImages.cover_preview = '';
      }
      if ((slotId === 'right' || slotId === 'left' || slotId === 'top' || slotId === 'back') && tenantCreativeImages?.moodboard) {
        delete tenantCreativeImages.moodboard[slotId];
      }
      markVisualConceptDirty();
      renderVisualConceptPage();
      toast('تم حذف الصورة');
    }

    async function sendVisualConceptChat(slotId) {
      if (!hasPermission('generate_images')) { toast('لا تملك صلاحية توليد الصور'); return; }
      if (visualConceptSlotLocked(slotId)) {
        toast(visualConceptLockMessage(slotId));
        return;
      }
      const input = document.querySelector('[data-visual-chat="' + slotId + '"]');
      const message = (input?.value || '').trim();
      if (!message) {
        toast('اكتب طلب التعديل أولاً');
        return;
      }
      const liveSlot = () => tenantVisualConceptState.slots[slotId];
      liveSlot().chat.push({ role: 'user', text: message });
      markVisualConceptDirty();
      showLoader('جاري تعديل وصف الصورة', 'يتم تطبيق ملاحظاتك على نفس المشروع...');
      try {
        const payload = await collectVisualConceptPayload(slotId);
        payload.message = message;
        const response = await api('POST', '/api/visual-concept/chat', payload);
        hideLoader();
        if (!response?.success || !response.prompt) {
          const errorText = visualConceptMissingMessage(response) || response?.error || 'تعذر تعديل الوصف';
          showVisualConceptMissing(visualConceptMissingMessage(response));
          toast(errorText);
          return;
        }
        showVisualConceptMissing('');
        liveSlot().prompt = response.prompt;
        liveSlot().chat.push({ role: 'assistant', text: response.reply || 'تم تحديث وصف الصورة.' });
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast('تم تحديث الوصف. اضغط توليد الصورة لتطبيق التعديل.');
      } catch (error) {
        hideLoader();
        toast(error.message || 'تعذر تعديل الوصف');
      }
    }
