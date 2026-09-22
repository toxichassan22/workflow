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






    let tempCoverImage = null;
    let tempMoodboardImages = {};


    function containsSlideRoot(html) {
      if (!html) return false;
      return Boolean(new DOMParser().parseFromString(String(html), 'text/html').querySelector('.slide'));
    }

    // A streamed preview is only worth painting once it holds a complete .slide
    // root: mid-stream fragments are unclosed markup that morph on every poll
    // and read as the slide being redesigned over and over.
    function slidePartialComplete(partial) {
      const text = String(partial || '');
      const start = text.search(/<div\b[^>]*\bclass\s*=\s*["'](?:[^"']*\s)?slide(?:\s[^"']*)?["']/i);
      if (start < 0) return false;
      const tail = text.slice(start);
      const opens = (tail.match(/<div\b/gi) || []).length;
      const closes = (tail.match(/<\/div\s*>/gi) || []).length;
      return opens > 0 && closes >= opens;
    }

    let isGeneratingTenantSlides = false;
    let isRegeneratingTenantSlide = false;

    function tenantSlidePlanFingerprint(plan) {
      // The engine version rides in every normalized plan: a checkpoint stored
      // under older rendering code must never resume — its stored slide HTML
      // was produced by a different renderer and would come back unchanged.
      const engineVersion = String(plan?.engine_version || plan?.engineVersion || '');
      return engineVersion + '|' + JSON.stringify((plan?.slides || []).map(slide => ({
        title: slide?.title || '',
        type: slide?.type || 'content',
        section_key: slide?.section_key || '',
        content_source: slide?.content_source || '',
        source_table: slide?.source_table || '',
        chart_type: slide?.chart_type || '',
      })));
    }

    function tenantSlideGenerationOptions(options = {}) {
      return {
        sectionKey: options.sectionKey || '',
        sectionLabel: options.sectionLabel || '',
        presentationTitle: options.presentationTitle || tenantPresentationTitle || '',
        financialValidated: !!options.financialValidated,
        markDraftDirty: options.markDraftDirty !== false,
      };
    }

    async function saveTenantSlideGenerationCheckpoint(nextIndex, status, lastError = '', projectData = null) {
      const planSignature = tenantSlidePlanFingerprint(tenantSlidePlan);
      tenantSlideGenerationCheckpoint = {
        ...(tenantSlideGenerationCheckpoint || {}),
        planSignature,
        nextIndex: Math.max(0, Number(nextIndex) || 0),
        completedCount: Array.isArray(tenantSlidesData) ? tenantSlidesData.length : 0,
        status: status || 'paused',
        active: status !== 'complete',
        lastError: String(lastError || '').slice(0, 500),
        options: tenantSlideGenerationOptions(tenantSlideGenerationCheckpoint?.options || {}),
      };
      tenantProjectData.slide_generation_checkpoint = tenantSlideGenerationCheckpoint;
      tenantProjectData.tenantSlidePlan = tenantSlidePlan;
      try {
        // The draft sits in the locked 'generating' state while this runs; the
        // flag marks this as the job's own checkpoint write, not a user edit.
        // The boolean comes back so a caller can tell a persisted checkpoint
        // from one that silently failed.
        return await saveProjectAsDraftNow(true, false, true, projectData);
      } catch (error) {
        console.error('[SLIDE CHECKPOINT]', error);
        return false;
      }
    }

    function hasResumableTenantSlideGeneration() {
      const checkpoint = tenantSlideGenerationCheckpoint || tenantProjectData?.slide_generation_checkpoint;
      return !!(
        checkpoint?.status === 'paused' && checkpoint?.active !== false &&
        tenantSlidePlan?.slides?.length && Array.isArray(tenantSlidesData) &&
        tenantSlidesData.length < tenantSlidePlan.slides.length &&
        checkpoint.planSignature === tenantSlidePlanFingerprint(tenantSlidePlan)
      );
    }

    async function resumeTenantSlideGeneration() {
      if (isGeneratingTenantSlides) return;
      if (!hasResumableTenantSlideGeneration()) {
        toast('لا توجد مهمة توليد قابلة للاستكمال');
        return;
      }
      const checkpoint = tenantSlideGenerationCheckpoint || tenantProjectData.slide_generation_checkpoint;
      await generateTenantSlides({
        ...(checkpoint.options || {}),
        resume: true,
      });
    }

    // t14-05: the run is a generation_jobs row — heartbeat carries progress and
    // finish settles the reservation server-side, so a closed tab cannot strand
    // the hold. Without a registered job the direct settle path still applies.
    async function settleGenerationRun(consumed, note) {
      const jobId = window.currentGenerationJobId;
      const approvalId = window.currentGenerationApprovalId;
      window.currentGenerationJobId = null;
      window.currentGenerationApprovalId = null;
      if (jobId) {
        // api() resolves with the error body instead of throwing, so a 502
        // settlement_failed answer must fall through to the direct settle —
        // the job is closed but its escrow and the draft lock are still live.
        const res = await api('POST', '/api/generation-jobs/' + encodeURIComponent(jobId) + '/finish', {
          status: consumed ? 'completed' : 'failed',
          progress: consumed ? 100 : undefined,
          slidesDone: (tenantSlidesData || []).length,
          note: note || ''
        });
        if (res && res.success) return;
        console.warn('Generation job finish refused, settling directly:', res);
      }
      if (approvalId) {
        const res = await api('POST', '/api/generation-approvals/' + encodeURIComponent(approvalId) + '/settle', {
          consumed: consumed,
          jobId: jobId || undefined,
          note: note || ''
        });
        if (!res || !res.success) console.warn('Settlement error:', res);
      }
    }

    function releaseGenerationRunOnPageHide() {
      const jobId = window.currentGenerationJobId;
      const approvalId = window.currentGenerationApprovalId;
      if (!jobId && !approvalId) return;
      const headers = { 'Content-Type': 'application/json' };
      const token = typeof getTenantToken === 'function' ? getTenantToken() : '';
      if (token) headers.Authorization = 'Bearer ' + token;
      const note = 'أُغلقت صفحة التوليد قبل اكتمالها';
      const request = { method: 'POST', headers, keepalive: true };
      if (jobId) {
        fetch('/api/generation-jobs/' + encodeURIComponent(jobId) + '/finish', {
          ...request,
          body: JSON.stringify({ status: 'cancelled', slidesDone: (tenantSlidesData || []).length, note })
        }).catch(() => {});
      }
      if (approvalId) {
        fetch('/api/generation-approvals/' + encodeURIComponent(approvalId) + '/settle', {
          ...request,
          body: JSON.stringify({ consumed: false, jobId: jobId || undefined, note })
        }).catch(() => {});
      }
      window.currentGenerationJobId = null;
      window.currentGenerationApprovalId = null;
    }

    window.addEventListener('pagehide', releaseGenerationRunOnPageHide);
    window.addEventListener('beforeunload', releaseGenerationRunOnPageHide);

    async function cancelActiveTenantGenerationRun(draftId) {
      if (!draftId) return false;
      const [jobsResponse, approvalsResponse] = await Promise.all([
        api('GET', '/api/generation-jobs?draftId=' + encodeURIComponent(draftId)),
        api('GET', '/api/generation-approvals?status=approved'),
      ]);
      const jobs = jobsResponse?.jobs || [];
      const latestJobByApproval = new Map();
      for (const job of jobs) {
        const approvalId = String(job.approval_id || '');
        if (approvalId && !latestJobByApproval.has(approvalId)) latestJobByApproval.set(approvalId, job.id);
      }
      const activeJobs = jobs.filter(job => ['queued', 'running'].includes(job.status));
      const activeApprovals = (approvalsResponse?.approvals || []).filter(approval =>
        String(approval.draft_id || '') === String(draftId) && !approval.section_key);
      if (!activeJobs.length && !activeApprovals.length) return false;
      if (typeof confirm !== 'function' || !confirm(
        'يوجد توليد قيد التنفيذ لهذا المشروع. هل تريد إيقافه وبدء توليد جديد؟')) return false;
      let released = false;
      const finishedApprovals = new Set();
      const inactiveJobByApproval = new Map();
      const unresolvedApprovals = new Set();
      for (const job of activeJobs) {
        const res = await api('POST', '/api/generation-jobs/' + encodeURIComponent(job.id) + '/finish', {
          status: 'cancelled',
          slidesDone: (tenantSlidesData || []).length,
          note: 'أُلغيت مهمة التوليد لبدء توليد جديد'
        });
        if (res?.success) {
          released = true;
          if (job.approval_id) finishedApprovals.add(String(job.approval_id));
        } else if (res?.error_code === 'job_not_active' || res?.error_code === 'settlement_failed') {
          released = true;
          if (job.approval_id) inactiveJobByApproval.set(String(job.approval_id), job.id);
        } else if (job.approval_id) {
          unresolvedApprovals.add(String(job.approval_id));
        }
      }
      for (const approval of activeApprovals) {
        if (finishedApprovals.has(String(approval.id))) continue;
        if (unresolvedApprovals.has(String(approval.id))) continue;
        const res = await api('POST', '/api/generation-approvals/' + encodeURIComponent(approval.id) + '/settle', {
          consumed: false,
          jobId: inactiveJobByApproval.get(String(approval.id))
            || latestJobByApproval.get(String(approval.id)) || undefined,
          note: 'أُلغي اعتماد التوليد لبدء توليد جديد'
        });
        if (res?.success || res?.error_code === 'approval_not_approved') released = true;
      }
      return released;
    }

    async function generateTenantSlides(options = {}) {
      if (isGeneratingTenantSlides) return;
      if (!tenantSlidePlan || !tenantProjectData) return;
      isGeneratingTenantSlides = true;
      try {
        const sectionKey = String(options.sectionKey || '');
        const totalSlides = (tenantSlidePlan.slides || []).length;
        if (!totalSlides) { toast('لا توجد شرائح في الخطة'); return; }

        const planSignature = tenantSlidePlanFingerprint(tenantSlidePlan);
        const savedCheckpoint = tenantSlideGenerationCheckpoint || tenantProjectData.slide_generation_checkpoint;
        const resumeRequested = options.resume === true;
        const canResume = resumeRequested && savedCheckpoint?.status === 'paused'
          && savedCheckpoint?.active !== false
          && savedCheckpoint.planSignature === planSignature
          && Array.isArray(tenantSlidesData)
          && tenantSlidesData.length < totalSlides;
        if (resumeRequested && !canResume) {
          toast('لا توجد نقطة توقف متوافقة مع خطة العرض الحالية');
          return;
        }
        const startIndex = canResume
          ? Math.min(totalSlides, Math.min(
            Math.max(0, Number(savedCheckpoint.nextIndex) || 0), tenantSlidesData.length))
          : 0;

        // The approval gate is per-run: pausing settled the old approval and
        // released its escrow, so a resume must open a fresh one. The draft is
        // saved first so the approval prices and snapshots exactly the inputs
        // this run will send, and only the slides still left are reserved.
        if (!options.approvalGranted) {
          if (typeof showGenerationApprovalModal === 'function') {
            if (resumeRequested && !(await saveProjectAsDraftNow(true, false))) return;
            isGeneratingTenantSlides = false;
            const approved = await showGenerationApprovalModal({
              draftId: tenantProjectData && (tenantProjectData.draftId || tenantProjectData.draft_id),
              slidesCount: totalSlides - startIndex,
              projectName: options.presentationTitle || tenantPresentationTitle || tenantProjectData.project_name || 'عرض بدون عنوان',
              sectionKey: sectionKey || ''
            });
            if (!approved) {
              return;
            }
            isGeneratingTenantSlides = true;
          }
        }
        tenantSlideGenerationCheckpoint = {
          ...(canResume ? savedCheckpoint : {}),
          planSignature,
          nextIndex: startIndex,
          completedCount: tenantSlidesData.length,
          status: 'running',
          active: true,
          lastError: '',
          options: tenantSlideGenerationOptions(options),
        };
        tenantProjectData.slide_generation_checkpoint = tenantSlideGenerationCheckpoint;
        tenantProjectData.tenantSlidePlan = tenantSlidePlan;

        // Re-collect latest form data to ensure all location fields are fresh
        if (typeof collectTenantFormData === 'function') {
          const freshData = await collectTenantFormData();
          tenantProjectData = { ...tenantProjectData, ...freshData };
        }
        if ((!sectionKey || sectionKey === 'section-financial-calc') && !options.financialValidated
          && !(await validateFinancialStudyBeforeProceed())) return;

        // Ensure we are on the presentation page
        showTenantPage('tenantSlidesPage');

        // Set up live generation banner
        setLiveGenBanner(true, 'بدء توليد الشرائح بالذكاء الاصطناعي...', 'إجمالي ' + totalSlides + ' شريحة', 10);

        // Pre-render skeleton cards in main preview area
        const wrap = document.getElementById('tenantSlidesMain');
        if (wrap) {
          wrap.innerHTML = '';
          tenantSlidePlan.slides.forEach((plan, i) => {
            const container = document.createElement('div');
            container.className = 'ge-slide-card' + (i === 0 ? ' active-slide' : '');
            container.id = 'slide-card-' + i;
            container.style.cssText = 'margin-bottom:24px; position:relative;';
            container.onclick = () => selectTenantSlide(i);
            const stage = document.createElement('div');
            stage.className = 'tenant-slide-stage';
            stage.style.setProperty('--stage-w', '960px');
            stage.style.setProperty('--stage-h', '540px');
            stage.style.setProperty('--slide-scale', '0.75');
            const savedSlide = canResume && tenantSlidesData[i] && tenantSlidesData[i].html
              ? processSlideHtmlClient(tenantSlidesData[i].html, tenantSlidesData[i].type)
              : '';
            stage.innerHTML = savedSlide || ('<div class="slide live-gen-skeleton-stage" id="slide-stage-inner-' + i + '">' +
              '<div style="font-size:12px;font-weight:700;color:#94a3b8;letter-spacing:1px">الشريحة ' + (i + 1) + ' من ' + totalSlides + '</div>' +
              '<div style="font-size:22px;font-weight:700;color:#1e293b;margin:6px 0">' + escapeHtml(plan.title || ('شريحة ' + (i + 1))) + '</div>' +
              '<div style="font-size:13px;color:#64748b;background:#f1f5f9;padding:6px 16px;border-radius:20px">قيد الانتظار للتوليد</div>' +
              '</div>');
            container.appendChild(stage);
            wrap.appendChild(container);
          });
        }

        // Pre-render sidebar planned thumbnails
        const sidebar = document.getElementById('tenantSlidesSidebar');
        if (sidebar) {
          sidebar.innerHTML = '';
          tenantSlidePlan.slides.forEach((plan, i) => {
            const thumb = document.createElement('div');
            thumb.className = 'ge-thumb' + (i === 0 ? ' active' : '');
            thumb.id = 'thumb-slide-' + i;
            thumb.onclick = () => selectTenantSlide(i);
            thumb.innerHTML = '<span class="ge-thumb-num">' + (i + 1) + '</span>' +
              '<span class="ge-thumb-title" title="' + escapeHtml(plan.title || '') + '">' + escapeHtml(plan.title || ('شريحة ' + (i + 1))) + '</span>';
            sidebar.appendChild(thumb);
          });
        }

        const hasLocation = Boolean(
          tenantProjectData.location_lat ||
          tenantProjectData.location_lng ||
          tenantProjectData.location_address ||
          tenantProjectData.location_maps_link ||
          tenantProjectData.location
        );
        if (hasLocation && (!sectionKey || sectionKey === 'location')) {
          if (!tenantProjectData.location_analysis_approved) {
            throw new Error('اعتماد تحليل الموقع مطلوب قبل توليد العرض');
          }
          const mapApprovals = tenantCreativeImages.map_approvals || {};
          const missingMaps = MAP_PREVIEW_VIEW_DEFS.filter(view => !mapApprovals[view.mapType]);
          if (missingMaps.length) {
            throw new Error('اعتماد الخرائط الأربع مطلوب قبل توليد العرض');
          }
          if (tenantCreativeImages.map_landmarks && tenantCreativeImages.map_landmarks.length) {
            tenantProjectData.landmarks_matrix = tenantCreativeImages.map_landmarks;
          }
        }

        persistVisualConceptDraftState();
        const generationImages = buildPresentationGenerationImages();
        const generationProjectData = JSON.parse(JSON.stringify(tenantProjectData));
        const generationPayloadProjectData = JSON.parse(JSON.stringify(slimGenerationProjectData(generationProjectData)));
        const hasUnapprovedImages = !!tempCoverImage || Object.keys(tempMoodboardImages || {}).length > 0;
        if (hasUnapprovedImages) toast('سيتم استخدام الصور المولدة غير المعتمدة مع استمرار إمكانية اعتمادها لاحقًا.');
        if (!canResume) tenantSlidesData = [];
        activeSlideIndex = Math.min(startIndex, Math.max(0, tenantSlidesData.length - 1));

        // Slides generate in small parallel waves, but they are committed in plan
        // order: tenantSlidesData stays dense, so checkpoints, resume, ordering and
        // the final validation below work exactly as they did for the sequential loop.
        const SLIDE_GENERATION_CONCURRENCY = 3;
        if (window.currentGenerationApprovalId && !window.currentGenerationJobId) {
          try {
            const jobRes = await api('POST', '/api/generation-approvals/' +
              encodeURIComponent(window.currentGenerationApprovalId) + '/jobs', {
              slidesTotal: totalSlides,
              idempotencyKey: 'gen-' + (window.currentGenerationApprovalId || 'run') +
                '-' + (tenantProjectData.draftId || tenantPresentationId || 'draft') +
                '-' + Date.now()
            });
            if (jobRes && jobRes.success && jobRes.job) window.currentGenerationJobId = jobRes.job.id;
          } catch (jobErr) { console.warn('Generation job register:', jobErr); }
        }
        const pendingSlides = {};
        let launchIndex = startIndex;
        let inFlightCount = 0;
        let commitIndex = startIndex;
        let generationStopped = false;
        let generationFinished = false;
        let generationFailure = null;
        let finishResolve = null;
        const generationDone = new Promise((resolve) => { finishResolve = resolve; });
        let commitRunning = false;
        let commitAgain = false;

        function updateGenerationBanner() {
          if (generationFinished) return;
          const done = tenantSlidesData.length;
          const slidePct = Math.round(20 + (done / totalSlides) * 75);
          const activeTitles = [];
          Object.keys(pendingSlides).forEach((key) => {
            const idx = Number(key);
            if (pendingSlides[key] === true && idx >= commitIndex) {
              const plan = tenantSlidePlan.slides[idx] || {};
              if (plan.title) activeTitles.push((idx + 1) + '. ' + plan.title);
            }
          });
          setLiveGenBanner(true, 'توليد الشرائح (' + done + ' من ' + totalSlides + ')',
            activeTitles.length ? activeTitles.slice(0, 3).join(' | ') : 'جاري الصياغة والتصميم بالذكاء الاصطناعي...', slidePct);
        }

        function markSlideGenerating(i) {
          const plan = tenantSlidePlan.slides[i] || {};
          document.querySelectorAll('.ge-slide-card').forEach((c, idx) => {
            c.classList.toggle('active-slide', idx === i);
            if (idx === i) c.classList.add('generating-live');
          });
          document.querySelectorAll('.ge-thumb').forEach((t, idx) => {
            if (idx === i) {
              t.classList.add('active');
              t.classList.add('generating-live');
            }
          });
          const cardEl = document.getElementById('slide-card-' + i);
          if (cardEl) {
            const stageInner = document.getElementById('slide-stage-inner-' + i);
            if (stageInner) {
              stageInner.className = 'slide live-gen-skeleton-stage live-gen-skeleton-pulse';
              stageInner.innerHTML = '<div style="font-size:12px;font-weight:700;color:var(--p);letter-spacing:1px">جاري توليد الشريحة ' + (i + 1) + ' من ' + totalSlides + '</div>' +
                '<div style="font-size:24px;font-weight:700;color:var(--pd);margin:8px 0">' + escapeHtml(plan.title || '') + '</div>' +
                '<div style="font-size:14px;color:var(--p);font-weight:600;display:flex;align-items:center;gap:8px">' +
                '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--p);animation:pulseDot 1s infinite alternate"></span>' +
                'جاري صياغة المحتوى وبناء التصميم...' +
                '</div>';
            }
          }
        }

        function buildSlidePayload(i) {
          const plan = tenantSlidePlan.slides[i] || {};
          const _snapSlide = tenantSlidePlan.slides[i];
          const genPayload = {
            projectData: JSON.parse(JSON.stringify(generationPayloadProjectData)),
            slidePlan: { slides: [_snapSlide] },
            images: generationImages,
            slideIndex: 0,
            sectionKey: sectionKey || '',
            _slideNum: (i + 1),
            _totalSlides: totalSlides
          };
          if (tenantPresentationId) genPayload.presentationId = tenantPresentationId;
          return genPayload;
        }

        function renderTenantSlidePartial(i, partial) {
          if (generationStopped || generationFinished || !partial) return;
          const cardEl = document.getElementById('slide-card-' + i);
          if (!cardEl) return;
          const stage = cardEl.querySelector('.tenant-slide-stage');
          if (!stage) return;
          // Preview only: the finalized slide still renders on completion below.
          // Painting only complete roots keeps the card steady instead of
          // flashing a different half-parsed design on every poll.
          if (!slidePartialComplete(partial)) return;
          try {
            const preview = processSlideHtmlClient(String(partial));
            if (preview) {
              stage.innerHTML = preview;
              autoFitSlideContent(stage);
            }
          } catch (previewError) { /* preview-only */ }
        }

        async function commitSlide(i, generated) {
          const plan = tenantSlidePlan.slides[i] || {};
          const slideObj = {
            title: generated.title || plan.title,
            type: generated.type || plan.type || 'content',
            html: generated.html,
            section_key: generated.sectionKey || plan.section_key || '',
            content_source: generated.contentSource || plan.content_source || '',
            source_table: generated.sourceTable || plan.source_table || '',
            index_entries: generated.indexEntries || plan.index_entries || [],
            designStyle: generated.designStyle || plan.design_style || 'cards',
            bullets: plan.bullets || [],
            metrics: plan.metrics || []
          };
          // Commits arrive in plan order exactly once, but if a resume or a
          // mid-run edit ever replays an index it must replace — never append a
          // second copy of the same planned slide.
          if (i < tenantSlidesData.length && tenantSlidesData[i]) {
            tenantSlidesData[i] = slideObj;
          } else {
            tenantSlidesData.push(slideObj);
          }
          tenantProjectData.tenantSlidesData = tenantSlidesData;
          if (window.currentGenerationJobId) {
            api('POST', '/api/generation-jobs/' + encodeURIComponent(window.currentGenerationJobId) + '/heartbeat', {
              progress: Math.round((tenantSlidesData.length / totalSlides) * 100),
              slidesDone: tenantSlidesData.length,
              slidesTotal: totalSlides
            }).catch(() => {});
          }
          await saveTenantSlideGenerationCheckpoint(i + 1, 'running', '', generationProjectData);

          // Live populate the slide card right in front of the user!
          const cardEl = document.getElementById('slide-card-' + i);
          document.querySelectorAll('.ge-slide-card').forEach((c, idx) => {
            c.classList.toggle('active-slide', idx === i);
          });
          document.querySelectorAll('.ge-thumb').forEach((t, idx) => {
            t.classList.toggle('active', idx === i);
          });
          if (cardEl) {
            cardEl.classList.remove('generating-live');
            cardEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            const stage = cardEl.querySelector('.tenant-slide-stage');
            if (stage) {
              const slideHtml = processSlideHtmlClient(generated.html, generated.type);
              stage.innerHTML = slideHtml || '<div class="slide" style="padding:40px;font-size:24px;background:#fff">' + escapeHtml(slideObj.title || '') + '</div>';
              autoFitSlideContent(stage);
              repairSlideTextContrast(stage);
              slideObj.html = stage.innerHTML;
              enableSlideInlineEditing(stage, i);
            }
          }

          // Update sidebar thumb
          const thumbEl = document.getElementById('thumb-slide-' + i);
          if (thumbEl) {
            thumbEl.classList.remove('generating-live');
            thumbEl.title = slideObj.title;
          }
        }

        async function pauseSlideGeneration(i, lastError) {
          generationStopped = true;
          generationFinished = true;
          generationFailure = { index: i, error: lastError || '' };
          const checkpointSaved = await saveTenantSlideGenerationCheckpoint(i, 'paused', lastError, generationProjectData);
          const slidePct = Math.round(20 + (tenantSlidesData.length / totalSlides) * 75);
          setLiveGenBanner(true, 'توقف التوليد مؤقتًا عند الشريحة ' + (i + 1),
            (lastError ? lastError + ' — ' : '') + (checkpointSaved
              ? 'تم حفظ ' + tenantSlidesData.length + ' شريحة ويمكن استكمال العرض لاحقًا.'
              : 'تعذر حفظ نقطة الاستئناف — الشرائح المنجزة محفوظة في هذه الجلسة فقط.'), slidePct);
          renderTenantSlidesSidebar(true);
          toast(lastError || (checkpointSaved
            ? 'تم حفظ نقطة التوقف عند الشريحة ' + (i + 1)
            : 'تعذر حفظ نقطة التوقف على الخادم'));
          if (typeof finishResolve === 'function') finishResolve();
        }

        async function drainCommits() {
          if (commitRunning) { commitAgain = true; return; }
          commitRunning = true;
          try {
            do {
              commitAgain = false;
              while (!generationFinished && commitIndex < totalSlides) {
                const entry = pendingSlides[commitIndex];
                if (!entry || entry === true) break;
                if (!entry.slide) {
                  await pauseSlideGeneration(commitIndex, entry.error);
                  break;
                }
                try {
                  await commitSlide(commitIndex, entry.slide);
                } catch (commitError) {
                  // Committing only renders and checkpoints; a failure here
                  // pauses at this slide exactly like a generation failure.
                  console.error('Slide commit error for index', commitIndex, commitError);
                  await pauseSlideGeneration(commitIndex, (commitError && commitError.message) || 'خطأ في الحفظ');
                  break;
                }
                delete pendingSlides[commitIndex];
                commitIndex += 1;
              }
              updateGenerationBanner();
              if (!generationFinished && commitIndex >= totalSlides) {
                generationFinished = true;
                if (typeof finishResolve === 'function') finishResolve();
              }
            } while (commitAgain && !generationFinished);
          } finally {
            commitRunning = false;
          }
        }

        function pumpSlideLaunches() {
          if (generationStopped || generationFinished) return;
          while (!generationStopped && !generationFinished
            && inFlightCount < SLIDE_GENERATION_CONCURRENCY && launchIndex < totalSlides) {
            const i = launchIndex;
            launchIndex += 1;
            inFlightCount += 1;
            pendingSlides[i] = true;
            try {
              markSlideGenerating(i);
            } catch (markError) {
              // A preview-only DOM failure must pause the slide like a
              // generation failure, never leak the in-flight slot.
              pendingSlides[i] = { error: (markError && markError.message) || 'خطأ في العرض' };
              generationStopped = true;
              inFlightCount -= 1;
              drainCommits();
              continue;
            }
            runSlideWorker(i);
          }
          updateGenerationBanner();
        }

        async function runSlideWorker(i) {
          let generated = null;
          let lastError = '';

          // The request is already a background job. Retrying here could enqueue a second paid
          // generation after a browser or proxy timeout, so a failed slide is checkpointed for an
          // explicit resume instead.
          for (let attempt = 1; attempt <= 1 && !generated; attempt++) {
            try {
              // Snapshot the specific slide so a mutating plan cannot break the request.
              const data = await requestTenantSlideGeneration(buildSlidePayload(i),
                (partial) => renderTenantSlidePartial(i, partial));
              if (data.success && data.slide && data.slide.html && containsSlideRoot(data.slide.html)) {
                generated = data.slide;
              } else {
                lastError = data.error || 'استجابة غير مكتملة من الخادم';
                console.error('[SLIDE GENERATION]', {
                  slideIndex: i, error_code: data.error_code, input_key: data.input_key, error: lastError
                });
              }
            } catch (err) {
              lastError = err.message || 'خطأ في الاتصال';
              console.error('Slide generation error for index', i, 'attempt', attempt, err);
            }
          }

          if (!generated) generationStopped = true;
          pendingSlides[i] = generated ? { slide: generated } : { error: lastError };
          inFlightCount -= 1;
          await drainCommits();
          pumpSlideLaunches();
        }

        pumpSlideLaunches();
        await generationDone;
        if (generationFailure) {
          await settleGenerationRun(false, 'فشل التوليد');
          return;
        }

        if (tenantSlidesData.length !== totalSlides || tenantSlidesData.some(s => !s.html || !containsSlideRoot(s.html))) {
          await settleGenerationRun(false, 'لم يكتمل التوليد');
          setLiveGenBanner(true, 'لم يكتمل التوليد', 'حدث خطأ في بعض الشرائح ولم يتم الحفظ', 90);
          toast('لم يكتمل توليد العرض، لذلك لم يتم حفظه.');
          return;
        }

        await saveTenantSlideGenerationCheckpoint(totalSlides, 'complete', '', generationProjectData);
        setLiveGenBanner(true, 'تم اكتمال توليد كافة الشرائح بنجاح!', 'إجمالي ' + totalSlides + ' شريحة معتمدة', 100);
        renderTenantSlidesSidebar(true);
        renderTenantDesignerChat();
        // await saveTenantPresentation(options.presentationTitle)
        const presentationSaved = await saveTenantPresentation(options.presentationTitle, { operation: 'generation' });
        if (!presentationSaved) {
          // No file was produced, so the hold is released — the draft leaves
          // 'generating' and the points return to the wallet.
          await settleGenerationRun(false, 'تعذر حفظ العرض بعد التوليد');
          setLiveGenBanner(true, 'اكتمل التوليد وتعذر الحفظ', 'الشرائح ما زالت مفتوحة في المعاينة', 100);
          return;
        }
        await settleGenerationRun(true, '');
        if (options.markDraftDirty !== false) triggerAutoSaveDraft();
        selectTenantSlide(0);
        const completedTitle = options.sectionLabel
          ? 'تم توليد عرض ' + options.sectionLabel + ' وحفظه (' + totalSlides + ' شريحة)'
          : 'تم توليد جميع الشرائح (' + totalSlides + ' شريحة) بنجاح';
        setSlidesEditorInfo(tenantPresentationTitle, totalSlides);
        toast(completedTitle);
        setTimeout(() => {
          setLiveGenBanner(false);
        }, 3500);
      } finally {
        // Every exit above — a thrown validation, an early return, a dead
        // request — ends this client-driven run. Leaving with the gate still
        // open would hold the escrowed points and lock the draft in
        // 'generating', so an unsettled approval is always released here.
        if (window.currentGenerationApprovalId || window.currentGenerationJobId) {
          try {
            await settleGenerationRun(false, 'انتهت مهمة التوليد قبل اكتمالها');
          } catch (settleError) {
            console.warn('[GENERATION SETTLE]', settleError);
          }
        }
        isGeneratingTenantSlides = false;
        checkpointPresentationUndo();
        updatePresentationUndoButtons();
      }
    }

