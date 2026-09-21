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

    let isGeneratingTenantSlides = false;
    let isRegeneratingTenantSlide = false;

    function tenantSlidePlanFingerprint(plan) {
      return JSON.stringify((plan?.slides || []).map(slide => ({
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
                '-' + (tenantProjectData.draftId || tenantPresentationId || Date.now())
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
          try {
            const preview = processSlideHtmlClient(String(partial));
            if (preview) stage.innerHTML = preview;
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
          tenantSlidesData.push(slideObj);
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
          renderTenantSlidesSidebar();
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
        renderTenantSlidesSidebar();
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

    function renderTenantSlidesProgress(total, done, currentTitle) {
      let bar = document.getElementById('slideGenProgress');
      if (!bar) {
        bar = document.createElement('div');
        bar.id = 'slideGenProgress';
        bar.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;background:#fff;border-bottom:2px solid var(--p);padding:10px 20px;display:flex;align-items:center;gap:12px;box-shadow:0 2px 8px rgba(0,0,0,.1)';
        document.body.appendChild(bar);
      }
      const pct = Math.round((done / total) * 100);
      bar.innerHTML = '<div style="flex:1"><div style="font-weight:700;margin-bottom:4px">جاري توليد الشرائح: ' + done + ' / ' + total + (currentTitle ? ' — ' + escapeHtml(currentTitle) : '') + '</div><div style="height:6px;background:#e0e0e0;border-radius:3px;overflow:hidden"><div style="height:100%;width:' + pct + '%;background:var(--p);transition:width .3s"></div></div></div>';
    }

    function hideSlideProgress() {
      const bar = document.getElementById('slideGenProgress');
      if (bar) bar.remove();
    }

    let activeSlideIndex = 0;
    const slideInlineEditStates = {};
    const slideElementEditStates = {};
    const TENANT_PRESENTATION_SECTION_TITLES = {
      overview: 'نبذة عن المشروع', components: 'مكونات المشروع', land: 'تحليل الأرض',
      location: 'تحليل الموقع الجغرافي', market: 'تحليل السوق', timeline: 'الجدول الزمني',
      financial: 'الدراسة المالية', swot_risks: 'تحليل SWOT وتحليل المخاطر', team: 'فريق العمل',
      visual_concept: 'التصور البصري',
      plans: 'المخططات', exterior: 'التصورات الخارجية', interior: 'التصورات الداخلية',
      executive_summary: 'الملخص التنفيذي', closing: 'الخاتمة'
    };

    function tenantSlideSectionKey(slide, current = '') {
      const explicit = String(slide?.section_key || slide?.sectionKey || slide?.section || '').trim();
      if (TENANT_PRESENTATION_SECTION_TITLES[explicit]) return explicit;
      const type = String(slide?.type || '').toLowerCase();
      if (type === 'closing') return 'closing';
      if (type === 'moodboard') return 'exterior';
      if (type.startsWith('map_') || type === 'site_specs') return 'location';
      const text = [slide?.title, slide?.content_source, slide?.contentSource, slide?.source_table]
        .filter(Boolean).join(' ').toLowerCase();
      const matchers = [
        ['closing', /الخاتمة|الختام|شكرا|شكراً|closing|conclusion|thanks/i],
        ['executive_summary', /الملخص التنفيذي|executive summary/i],
        ['interior', /التصورات? الداخلية|التصميم الداخلي|interior/i],
        ['exterior', /التصورات? الخارجية|المود بورد|mood ?board|واجهات المشروع|exterior|التصور البصري/i],
        ['plans', /المخططات|المخطط|المساقط|مخطط معماري|2d|floor ?plans?/i],
        ['team', /فريق العمل|فريق التطوير|المطور|الاستشاري|team/i],
        ['swot_risks', /swot|نقاط القوة|نقاط الضعف|الفرص والتهديدات|المخاطر|إدارة المخاطر|risk/i],
        ['financial', /الدراسة المالية|التحليل المالي|الجدوى|التدفقات النقدية|الإيرادات|التكاليف|العائد|roi|irr|financial|cash ?flow/i],
        ['timeline', /الجدول الزمني|الخطة الزمنية|مراحل التطوير|مراحل التنفيذ|timeline|schedule/i],
        ['market', /تحليل السوق|دراسة السوق|المنافسين|الطلب السوقي|market|competitor/i],
        ['location', /الموقع الجغرافي|تحليل الموقع|الموقع الاستراتيجي|خريطة|الطرق|المعالم|نطاق التأثير|site|location|map|access|landmarks|catchment/i],
        ['land', /تحليل الأرض|الأرض والاشتراطات|الأرض والكروكي|الكروكي|اشتراطات البناء|حدود الأرض|صور الأرض|land|croquis/i],
        ['components', /مكونات المشروع|الوحدات والمساحات|المكونات|components|units/i],
        ['overview', /نبذة عن المشروع|المشروع والفكرة|فكرة المشروع|نظرة عامة|تعريف المشروع|project overview|project brief/i]
      ];
      return matchers.find(([, pattern]) => pattern.test(text))?.[0] || current || 'overview';
    }

    function renumberTenantSlideHtml(slide, index, total, indexEntries) {
      if (!slide?.html) return slide?.html || '';
      const template = document.createElement('template');
      template.innerHTML = String(slide.html);
      const root = template.content.querySelector('.slide');
      if (!root) return slide.html;
      const type = String(slide.type || 'content').toLowerCase();
      if (['cover', 'closing', 'moodboard'].includes(type)) {
        root.querySelectorAll('[data-slide-footer], footer, .slide-footer').forEach(node => node.remove());
      } else {
        const counter = String(index).padStart(2, '0') + ' — ' + String(total).padStart(2, '0');
        let counters = Array.from(root.querySelectorAll('[data-slide-counter]'));
        if (!counters.length && type === 'section_divider') {
          counters = Array.from(root.querySelectorAll('div, span')).filter(node => /^\s*\d{1,3}\s*[—–-]\s*\d{1,3}\s*$/.test(node.textContent || ''));
        }
        if (!counters.length) {
          const footer = root.querySelector('footer, .slide-footer, [data-slide-footer]')
            || Array.from(root.querySelectorAll('footer, div')).find(node => /height:\s*36px/i.test(node.getAttribute('style') || ''));
          if (footer) {
            footer.dataset.slideFooter = '1';
            const candidates = Array.from(footer.querySelectorAll('span, div')).filter(node => /^\s*\d{1,3}(?:\s*[—–/-]\s*\d{1,3})?\s*$/.test(node.textContent || ''));
            const counterNode = candidates[candidates.length - 1];
            if (counterNode) {
              counterNode.dataset.slideCounter = '1';
              counters = [counterNode];
            }
          }
        }
        counters.forEach(node => {
          node.dataset.slideCounter = '1';
          node.textContent = counter;
        });
      }
      if (type === 'index') {
        const activeSections = new Set((indexEntries || []).map(entry => entry.section_key));
        root.querySelectorAll('[data-index-section]').forEach(row => {
          if (!activeSections.has(row.dataset.indexSection)) row.remove();
        });
        (indexEntries || []).forEach(entry => {
          let page = root.querySelector('[data-index-page="' + entry.section_key + '"]');
          if (!page) {
            const titleNodes = Array.from(root.querySelectorAll('div, span, p, td, h3, h4')).filter(node =>
              node.children.length === 0 && String(node.textContent || '').trim() === entry.title);
            for (const title of titleNodes) {
              const row = title.closest('[data-index-section]') || title.parentElement;
              if (row) {
                const candidates = Array.from(row.querySelectorAll('*')).filter(n =>
                  n !== title && n.children.length === 0 && /^\s*\d{1,3}\s*$/.test(n.textContent || ''));
                if (candidates.length) {
                  page = candidates[candidates.length - 1];
                  break;
                }
              }
              const sibling = title.nextElementSibling;
              if (sibling && /^\s*\d+\s*$/.test(sibling.textContent || '')) {
                page = sibling;
                break;
              }
            }
          }
          if (page) {
            page.dataset.indexPage = entry.section_key;
            page.textContent = String(entry.page).padStart(2, '0');
          }
        });
      }
      return template.innerHTML;
    }

    function renumberTenantSlides() {
      if (!Array.isArray(tenantSlidesData) || !tenantSlidesData.length) return tenantSlidesData;
      let current = '';
      tenantSlidesData = tenantSlidesData.map(slide => {
        const item = { ...(slide || {}) };
        const type = String(item.type || 'content').toLowerCase();
        if (type === 'cover') item.section_key = 'cover';
        else if (type === 'index') item.section_key = 'index';
        else {
          item.section_key = tenantSlideSectionKey(item, current);
          if (type === 'section_divider') current = item.section_key;
        }
        return item;
      });
      const seen = new Set();
      const indexEntries = [];
      tenantSlidesData.forEach((slide, index) => {
        if (slide.type !== 'section_divider' && slide.section_key !== 'closing') return;
        if (!TENANT_PRESENTATION_SECTION_TITLES[slide.section_key] || seen.has(slide.section_key)) return;
        seen.add(slide.section_key);
        indexEntries.push({
          section_key: slide.section_key,
          title: TENANT_PRESENTATION_SECTION_TITLES[slide.section_key],
          page: index + 1
        });
      });
      tenantSlidesData = tenantSlidesData.map((slide, index) => {
        const item = { ...slide };
        if (item.type === 'index') item.index_entries = indexEntries;
        item.html = renumberTenantSlideHtml(item, index + 1, tenantSlidesData.length, indexEntries);
        return item;
      });
      // During a paused generation the full plan must remain intact. Rebuilding it from the
      // completed prefix would make the resume button believe there are no remaining slides.
      if (!tenantSlideGenerationCheckpoint?.active) {
        tenantSlidePlan = {
          ...(tenantSlidePlan || {}),
          proposed_count: tenantSlidesData.length,
          slides: tenantSlidesData.map(slide => ({
            title: slide.title || '', type: slide.type || 'content', section_key: slide.section_key || '',
            content_source: slide.content_source || '', source_table: slide.source_table || '',
            index_entries: slide.index_entries || [], design_style: slide.designStyle || slide.design_style || 'cards',
            bullets: slide.bullets || [], metrics: slide.metrics || []
          }))
        };
      }
      return tenantSlidesData;
    }

    // Mirror of design_templates.sanitize_slide_html_for_export(): every export strips the font
    // declarations a slide carries so the company font wins, and the preview must show the same
    // thing — its whole promise is that what you see is what the PDF holds.
    function stripSlideFontDeclarations(html) {
      if (!html) return html;
      let out = String(html).replace(/\sstyle\s*=\s*(["'])([\s\S]*?)\1/gi, (match, quote, value) => {
        let cleaned = value.replace(/\s*font-family\s*:\s*[^;]+;?\s*/gi, '')
          .replace(/;\s*;/g, ';').trim().replace(/^;|;$/g, '');
        return cleaned ? ' style=' + quote + cleaned + quote : '';
      });
      out = out.replace(/<style[^>]*>([\s\S]*?)<\/style>/gi, (match, block) => {
        if (block.indexOf('@font-face') !== -1) return match;
        return '<style>' + block.replace(/\s*font-family\s*:\s*[^;]+;?\s*/gi, '')
          .replace(/;\s*;/g, ';') + '</style>';
      });
      return out;
    }

    function forceSectionDividerBackgroundHtml(html, coverImage) {
      if (!html || !coverImage) return String(html || '');
      const safeCover = String(coverImage).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      const declaration = "background-image:url('" + safeCover + "')!important;" +
        'background-size:cover!important;background-position:center center!important;' +
        'background-repeat:no-repeat!important;';
      let replaced = false;
      let output = String(html).replace(
        /background(?:-image)?\s*:\s*(?:url\([^)]*\)|none)\s*;?/i,
        () => {
          replaced = true;
          return declaration;
        }
      );
      if (!replaced) {
        const background = '<div data-section-divider-background="1" aria-hidden="true" ' +
          'style="position:absolute;top:0;right:0;left:0;bottom:0;' + declaration + '"></div>';
        output = output.replace(
          /(<div\b[^>]*\bclass=["'][^"']*\bslide\b[^"']*["'][^>]*>)/i,
          '$1' + background
        );
      }
      return output;
    }

    function processSlideHtmlClient(html, slideType) {
      if (!html) return '';
      let cleanHtml = stripSlideFontDeclarations(html);
      const projectData = tenantProjectData || {};
      const logoUrl = (tenantBranding && (tenantBranding.logo_path || tenantBranding.logo || tenantBranding.logo_url)) || '/assets/logo.png';

      cleanHtml = cleanHtml.replace(/##LOGO##/g, logoUrl);

      // 1. Creative Images (Cover & Moodboard)
      const creativeImages = tenantCreativeImages || {};
      const defaultStock = {
        cover: '/uploads/luxury_skyscraper_cover.png',
        moodboard: [
          '/uploads/moodboard_exterior.png',
          '/uploads/moodboard_materials.png',
          '/uploads/moodboard_interior.png',
          '/uploads/moodboard_urban_lifestyle.png'
        ]
      };
      const coverImage = creativeImages.cover || creativeImages.mainImageData || defaultStock.cover;
      const userMoodboard = Array.isArray(creativeImages.moodboard) && creativeImages.moodboard.filter(Boolean).length > 0
        ? creativeImages.moodboard
        : (Array.isArray(creativeImages.moodboardImages) && creativeImages.moodboardImages.filter(Boolean).length > 0
          ? creativeImages.moodboardImages
          : []);

      const moodboardImages = [];
      for (let i = 0; i < 16; i++) {
        moodboardImages.push(userMoodboard[i] || defaultStock.moodboard[i % 4]);
      }

      cleanHtml = cleanHtml.replace(/#*IMAGE_COVER#*/gi, coverImage);
      cleanHtml = cleanHtml.replace(/#*COVER_IMAGE#*/gi, coverImage);
      cleanHtml = cleanHtml.replace(/#*MAIN_IMAGE#*/gi, coverImage);
      cleanHtml = cleanHtml.replace(/#*PROJECT_IMAGE_COVER#*/gi, coverImage);

      for (let idx = 0; idx < 16; idx++) {
        const mbUrl = moodboardImages[idx];
        const num = idx + 1;
        const mbReg = new RegExp('#*MOODBOARD_IMAGE_' + num + '#*', 'gi');
        const projReg = new RegExp('#*PROJECT_IMAGE_' + num + '#*', 'gi');
        cleanHtml = cleanHtml.replace(mbReg, mbUrl).replace(projReg, mbUrl);
      }

      // Component-Specific Interior Placeholders
      const interiorCompsList = Array.isArray(creativeImages.interior_components) ? creativeImages.interior_components : [];
      interiorCompsList.forEach((comp, cIdx) => {
        const cNum = cIdx + 1;
        const cImgs = Array.isArray(comp.images) ? comp.images : [];
        cImgs.forEach((imgItem, jIdx) => {
          const jNum = jIdx + 1;
          const url = (typeof imgItem === 'object' && imgItem !== null) ? (imgItem.url || '') : String(imgItem || '');
          if (url) {
            const reg1 = new RegExp('#*INTERIOR_COMP_' + cNum + '_(?:IMG|IMAGE)_' + jNum + '#*', 'gi');
            const reg2 = new RegExp('#*INTERIOR_C' + cNum + '_(?:IMG|IMAGE)_' + jNum + '#*', 'gi');
            const reg3 = new RegExp('#*INTERIOR_' + cNum + '_' + jNum + '#*', 'gi');
            cleanHtml = cleanHtml.replace(reg1, url).replace(reg2, url).replace(reg3, url);
          }
        });
      });

      // Flat Interior Placeholders
      const interiorImagesList = Array.isArray(creativeImages.interior) ? creativeImages.interior : [];
      for (let idx = 0; idx < 16; idx++) {
        const intUrl = interiorImagesList[idx] || '';
        const num = idx + 1;
        const intReg = new RegExp('#*INTERIOR_IMAGE_' + num + '#*', 'gi');
        cleanHtml = cleanHtml.replace(intReg, intUrl);
      }
      cleanHtml = cleanHtml.replace(/#*INTERIOR_(?:COMP_\d+_(?:IMG|IMAGE)_\d+|C\d+_(?:IMG|IMAGE)_\d+|\d+_\d+|IMAGE_\d+|\d+)#*/gi, '');

      // 2D Plans Placeholders
      const plansImagesList = Array.isArray(creativeImages.plans) ? creativeImages.plans : [];
      for (let idx = 0; idx < 16; idx++) {
        const planUrl = plansImagesList[idx] || '';
        const num = idx + 1;
        const planReg1 = new RegExp('#*PLAN_IMAGE_' + num + '#*', 'gi');
        const planReg2 = new RegExp('#*2D_PLAN_' + num + '#*', 'gi');
        cleanHtml = cleanHtml.replace(planReg1, planUrl).replace(planReg2, planUrl);
      }
      cleanHtml = cleanHtml.replace(/#*(?:PLAN_IMAGE|2D_PLAN)_\d+#*/gi, '');

      // Map Placeholders
      if (creativeImages.map_placeholders && typeof creativeImages.map_placeholders === 'object') {
        Object.entries(creativeImages.map_placeholders).forEach(([token, url]) => {
          if (url) {
            const reg = new RegExp(token.replace(/#/g, '\\#'), 'g');
            cleanHtml = cleanHtml.replace(reg, url);
          }
        });
      }

      // 2. Data Placeholders
      const projectLogoMetaPath = projectData.project_logo_file_meta?.path
        ? ('/' + String(projectData.project_logo_file_meta.path).replace(/^\/+/, '')) : '';
      const projectLogoUrl = projectData.project_logo || projectLogoMetaPath
        || (projectData.project_logo_file_id ? '/api/project-files/' + encodeURIComponent(projectData.project_logo_file_id) : '');
      const replacements = {
        'PROJECT_NAME': projectData.project_name || projectData.projectName || projectData.name || '',
        'PROJECT_TYPE': projectData.project_type || projectData.projectType || '',
        'land_area': projectData.croquis_land_area || projectData.approved_financial_area || projectData.total_area_sqm || projectData.landArea || '',
        'location_address': projectData.location_address || projectData.location || projectData.address || '',
        'location_lat': projectData.location_lat || '',
        'location_lng': projectData.location_lng || '',
        'altsnyf_altkhtyty': projectData.altsnyf_altkhtyty || projectData.zoning || '',
        'nsba_albna__far': projectData.nsba_albna__far || projectData.far || '',
        'plot_number': projectData.plot_number || projectData.plotNumber || '',
        'budget': projectData.budget || projectData.total_cost || '',
        'noi': projectData.noi || projectData.annual_profit || '',
        'roi': projectData.roi || '',
        'alqrma_almdafa_almtwqaa__cap_rate': projectData.cap_rate || projectData.capRate || '',
        'nsba_alashgal_almtwqaa': projectData.occupancy_rate || '',
        'PROJECT_LOGO': projectLogoUrl
      };

      Object.entries(replacements).forEach(([key, val]) => {
        if (val) {
          const regExact = new RegExp('##' + key + '##', 'g');
          const regLower = new RegExp('##' + key.toLowerCase() + '##', 'g');
          const regUpper = new RegExp('##' + key.toUpperCase() + '##', 'g');
          cleanHtml = cleanHtml.replace(regExact, val).replace(regLower, val).replace(regUpper, val);
        }
      });

      Object.entries(projectData).forEach(([k, v]) => {
        if (v && (typeof v === 'string' || typeof v === 'number')) {
          const regExact = new RegExp('##' + k + '##', 'gi');
          cleanHtml = cleanHtml.replace(regExact, String(v));
        }
      });

      // Map files are already complete marked images from the location section.
      // The preview must fetch that exact file again after a replacement, even when
      // a server-side edit reused the same URL and the browser still has the old
      // bytes in its image cache.
      cleanHtml = cleanHtml.replace(
        /(?:\/uploads\/maps\/|\/api\/map-images\/)[^"'\s)]+/gi,
        url => withCacheBust(url)
      );

      // Cover and divider slides auto-inject fallback if model omitted ##IMAGE_COVER##
      if (coverImage && slideType === 'section_divider') {
        cleanHtml = forceSectionDividerBackgroundHtml(cleanHtml, coverImage);
      } else if (coverImage && (slideType === 'cover' || cleanHtml.includes('class="slide cover"') || cleanHtml.includes("class='slide cover'"))) {
        if (!cleanHtml.includes(coverImage) && !cleanHtml.includes('background-image')) {
          const bgDiv = '<div aria-hidden="true" style="position:absolute;inset:0;z-index:0;background-image:url(\'' + coverImage.replace(/'/g, "\\'") + '\');background-size:cover;background-position:center;"></div>';
          cleanHtml = cleanHtml.replace(/(<div[^>]*class=["']slide[^"']*["'][^>]*>)/i, '$1' + bgDiv);
        }
      }

      // Moodboard slide auto-inject fallback if images exist but tokens weren't placed
      if (slideType === 'moodboard' && moodboardImages.length) {
        const hasAnyImage = moodboardImages.some(img => img && cleanHtml.includes(img));
        if (!hasAnyImage) {
          const cols = moodboardImages.length <= 2 ? '1fr 1fr' : '1fr 1fr';
          const rows = moodboardImages.length <= 2 ? '1fr' : '1fr 1fr';
          const tiles = moodboardImages.map(img => '<div style="background-image:url(\'' + img.replace(/'/g, "\\'") + '\');background-size:cover;background-position:center;"></div>').join('');
          cleanHtml = '<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#171717;color:#fff;font-family:Arial,sans-serif;box-sizing:border-box;padding:42px;"><div style="display:flex;align-items:center;justify-content:space-between;height:52px;margin-bottom:20px;"><div style="font-size:30px;font-weight:700;">لوحة الإلهام (Moodboard)</div><div style="width:170px;height:4px;background:#C2A176;"></div></div><div style="height:560px;display:grid;grid-template-columns:' + cols + ';grid-template-rows:' + rows + ';gap:8px;">' + tiles + '</div></div>';
        }
      }

      // Heal pre-gray watermarks for display (mirror of the server-side
      // normalization): a saved overlay keeps its old filter until the next
      // save persists the healed one.
      cleanHtml = cleanHtml.replace(
        /(<div\b[^>]*\bdata-slide-watermark=["']true["'][^>]*>[\s\S]*?<img\b[^>]*style="[^"]*?)filter\s*:\s*[^;"]+/gi,
        '$1filter:grayscale(100%) brightness(0) invert(53.3%)'
      );

      cleanHtml = cleanHtml.replace(/##[a-zA-Z0-9_]+##/g, '');
      return cleanHtml;
    }

    function tenantSlideCanvasDimensions(slide) {
      const ratio = String((tenantBranding && tenantBranding.slide_ratio) || '16:9').trim();
      const defaultHeight = ratio === '4:3' ? 960 : 720;
      const parsePx = value => {
        const match = String(value || '').trim().match(/^([0-9]+(?:\.[0-9]+)?)px$/i);
        return match ? Number(match[1]) : 0;
      };
      const width = parsePx(slide && slide.style && slide.style.width) || 1280;
      const height = parsePx(slide && slide.style && slide.style.height) || defaultHeight;
      return {
        width: width > 0 ? width : 1280,
        height: height > 0 ? height : defaultHeight
      };
    }

    function autoFitSlideContent(stage) {
      if (!stage) return null;
      const slide = stage.querySelector('.slide');
      if (!slide) return null;

      const canvas = tenantSlideCanvasDimensions(slide);

      slide.style.boxSizing = 'border-box';
      slide.style.width = canvas.width + 'px';
      slide.style.height = canvas.height + 'px';

      // Keep the stage in sync when a slide is inserted after the initial refit. Generated
      // slides can use a taller canvas, while the old stage kept the skeleton's 16:9 height.
      const stageWidth = parseFloat(stage.style.getPropertyValue('--stage-w')) || 0;
      if (stageWidth > 0) {
        stage.style.setProperty('--stage-h', (stageWidth * canvas.height / canvas.width).toFixed(2) + 'px');
        stage.style.setProperty('--slide-scale', (stageWidth / canvas.width).toFixed(4));
      }

      // The stage already scales the complete slide canvas. A second scale on an
      // arbitrary content wrapper made some previews shorter than the exported slide,
      // which left a large blank area and could move the heading outside the viewport.
      // Keep the generated layout intact and only remove the legacy mutations that this
      // function used to write into saved slide HTML.
      slide.querySelectorAll('*').forEach(el => {
        el.style.boxSizing = 'border-box';
        const transform = String(el.style.transform || '').trim();
        const transformOrigin = String(el.style.transformOrigin || '').trim();
        const width = String(el.style.width || '').trim();
        const maxWidth = String(el.style.maxWidth || '').trim();
        const isLegacyAutoFit = /^scale\(0?\.\d+\)$/.test(transform)
          && transformOrigin === 'top right'
          && (/%$/.test(width) || /%$/.test(maxWidth));
        if (isLegacyAutoFit) {
          el.style.removeProperty('transform');
          el.style.removeProperty('transform-origin');
          if (/%$/.test(width)) el.style.removeProperty('width');
          if (/%$/.test(maxWidth)) el.style.removeProperty('max-width');
        }
      });
      return canvas;
    }

    function collectSlideTextNodes(root) {
      const nodes = [];
      if (!root) return nodes;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
          if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
          const parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          if (parent.closest('.slide-resize-handle, .slide-move-handle, .slide-element-delete-btn')) return NodeFilter.FILTER_REJECT;
          const tag = parent.tagName;
          if (tag === 'SCRIPT' || tag === 'STYLE') return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
      });
      let node;
      while ((node = walker.nextNode())) nodes.push(node);
      return nodes;
    }

    function enableSlideInlineEditing(stage, index) {
      const slide = stage.querySelector('.slide');
      if (!slide) return;
      const enabled = hasPermission('create_presentation') && !!slideInlineEditStates[index];
      const seen = new Set();
      collectSlideTextNodes(slide).forEach(node => {
        const el = node.parentElement;
        if (!el || seen.has(el)) return;
        seen.add(el);
        if (enabled) {
          if (el.hasAttribute('contenteditable')) return;
          el.setAttribute('contenteditable', 'plaintext-only');
          el.setAttribute('spellcheck', 'false');
          el.classList.add('slide-editable');
          el.title = 'اضغط للتعديل المباشر على النص (Esc للخروج)';
          el.addEventListener('mousedown', stopEditEvent);
          el.addEventListener('click', stopEditEvent);
          el.addEventListener('keydown', onInlineEditKey);
          el.addEventListener('paste', onInlineEditPaste);
          el.addEventListener('focus', onSlideEditableFocus);
          el.addEventListener('blur', () => commitSlideInlineEdit(stage, index, el));
        } else {
          el.removeAttribute('contenteditable');
          el.removeAttribute('spellcheck');
          el.classList.remove('slide-editable');
          el.removeAttribute('title');
          el.removeEventListener('mousedown', stopEditEvent);
          el.removeEventListener('click', stopEditEvent);
          el.removeEventListener('keydown', onInlineEditKey);
          el.removeEventListener('paste', onInlineEditPaste);
          el.removeEventListener('focus', onSlideEditableFocus);
        }
      });
      // Re-fit the slide when toggling edit mode.
      autoFitSlideContent(stage);
    }

    function slideElementPath(root, element) {
      const path = [];
      let node = element;
      while (node && node !== root) {
        const parent = node.parentElement;
        if (!parent) return null;
        path.unshift(Array.prototype.indexOf.call(parent.children, node));
        node = parent;
      }
      return node === root ? path : null;
    }

    function elementAtSlidePath(root, path) {
      let node = root;
      for (const index of path || []) {
        if (!node || !node.children || !node.children[index]) return null;
        node = node.children[index];
      }
      return node;
    }

    /* A static "shape": a block with its own visible surface (background,
       image, border or shadow). These are the cards and panels behind texts
       in flow layouts. Outline is deliberately ignored: hover and selection
       outlines must never make an element look like a shape. */
    function slideNodeIsVisualShape(node, style) {
      if (!node || !style) return false;
      const bg = String(style.backgroundColor || '').trim().toLowerCase();
      if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return true;
      const bgImg = String(style.backgroundImage || '').trim().toLowerCase();
      if (bgImg && bgImg !== 'none') return true;
      const borderW = parseFloat(style.borderTopWidth) || 0;
      const borderStyle = String(style.borderTopStyle || '').trim().toLowerCase();
      if (borderW > 0 && borderStyle && borderStyle !== 'none') return true;
      const shadow = String(style.boxShadow || '').trim().toLowerCase();
      if (shadow && shadow !== 'none') return true;
      return false;
    }

    /* Watermark-aware target: geometry ops (frame/move/resize) use the logo img
       itself, while overlay-level ops (opacity/layer/delete) walk back up via
       watermarkOverlayOf(). */
    function watermarkOverlayOf(node) {
      if (!node || !node.closest) return null;
      return node.closest('[data-slide-watermark="true"], .slide-watermark');
    }

    function slideDragTarget(slide, source) {
      if (!slide || !source || source === slide) return null;
      if (source.closest && source.closest('.slide-resize-handle, .slide-move-handle, .slide-element-delete-btn')) return null;
      if (source.closest && source.closest('[contenteditable]')) return null;
      if (source.closest && source.closest('[data-slide-textbox], [data-slide-imagebox]')) {
        const box = source.closest('[data-slide-textbox], [data-slide-imagebox]');
        if (box && slide.contains(box)) return box;
      }
      if (source.closest && source.closest('.presentation-chrome-logo, [data-canonical-map]')) return null;
      /* Watermark layer: selectable in edit mode so it can be dragged,
         restacked or deleted per slide. In normal view it stays
         click-through via pointer-events:none. */
      if (source.closest) {
        const watermark = source.closest('[data-slide-watermark="true"], .slide-watermark');
        if (watermark && slide.contains(watermark)) {
          // The overlay is a full-slide inset:0 layer; selecting it stretched
          // the edit frame over the whole slide. Handles must hug the logo img.
          const logo = watermark.querySelector('img');
          return (logo && watermark.contains(logo)) ? logo : watermark;
        }
      }
      let node = source.nodeType === 1 ? source : source.parentElement;
      while (node && node !== slide) {
        const style = window.getComputedStyle(node);
        if (node.matches('[data-company-logo-placement], [data-team-logo-placement], img:not(.presentation-chrome-logo)')
          || style.position === 'absolute') {
          if (node.tagName === 'IMG' && node.parentElement && node.parentElement !== slide
            && node.parentElement.hasAttribute && node.parentElement.hasAttribute('data-slide-imagebox')) {
            return node.parentElement;
          }
          return node;
        }
        /* Flow-layout shapes: the deepest block with its own visible surface
           wins, so an inner card is picked over a full-slide wrapper. Managed
           chrome (header/footer/counters) is never a shape. The walk stops
           before the slide root, which can never be selected. */
        if (!node.closest('[data-slide-header], [data-slide-footer], header, footer')
          && node.matches('div, section, aside, figure, table, ul')
          && slideNodeIsVisualShape(node, style)) {
          return node;
        }
        node = node.parentElement;
      }
      return null;
    }

    function findSlideRawTarget(rawRoot, target, path) {
      if (!rawRoot) return null;
      const placement = target ? (target.getAttribute('data-company-logo-placement')
        || target.getAttribute('data-team-logo-placement')) : null;
      if (placement) {
        const attr = target.hasAttribute('data-company-logo-placement')
          ? 'data-company-logo-placement' : 'data-team-logo-placement';
        const safePlacement = String(placement).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
        const byPlacement = rawRoot.querySelector('[' + attr + '="' + safePlacement + '"]');
        if (byPlacement) return byPlacement;
      }
      return elementAtSlidePath(rawRoot, path);
    }

    function commitSlideElementMove(stage, index, target, path, dx, dy) {
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html || (!dx && !dy)) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      const rawTarget = findSlideRawTarget(rawRoot, target, path);
      if (!rawTarget) return;

      pushSlideEditHistory(index);
      const nextX = (Number(target.dataset.manualTranslateX) || 0) + dx;
      const nextY = (Number(target.dataset.manualTranslateY) || 0) + dy;
      const transform = 'translate(' + Math.round(nextX) + 'px, ' + Math.round(nextY) + 'px)';
      target.dataset.manualTranslateX = String(Math.round(nextX));
      target.dataset.manualTranslateY = String(Math.round(nextY));
      target.style.transform = transform;
      rawTarget.dataset.manualTranslateX = String(Math.round(nextX));
      rawTarget.dataset.manualTranslateY = String(Math.round(nextY));
      rawTarget.style.transform = transform;
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      toast('تم تحريك العنصر وحفظ موضعه في الشريحة');
    }

    function commitSlideElementDelete(stage, index, target, path) {
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      const rawTarget = findSlideRawTarget(rawRoot, target, path);
      if (!rawTarget || !rawTarget.parentElement) return;
      // Deleting the logo must remove the whole watermark overlay,
      // not leave an empty full-slide layer behind.
      const deleteTarget = watermarkOverlayOf(rawTarget) || rawTarget;
      if (!deleteTarget.parentElement) return;
      pushSlideEditHistory(index);
      deleteTarget.parentElement.removeChild(deleteTarget);
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      const session = slideEditSessions[index];
      if (session) session.sel = null;
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
      toast('تم حذف العنصر من الشريحة');
    }

    function enableSlideElementDragging(stage, index) {
      const slide = stage.querySelector('.slide');
      if (!slide) return;
      const enabled = hasPermission('create_presentation') && !!slideElementEditStates[index];
      slide.classList.toggle('slide-element-editing', enabled);
      if (!enabled) return;
      let activeDeleteBtn = null;
      function removeDeleteBtn() {
        if (activeDeleteBtn) { activeDeleteBtn.remove(); activeDeleteBtn = null; }
      }
      stage.addEventListener('mouseover', function handleSlideHover(event) {
        if (!enabled) return;
        if (slideElementDragActive) return;
        removeDeleteBtn();
        const target = slideDragTarget(slide, event.target);
        if (!target) return;
        const path = slideElementPath(slide, target);
        if (!path) return;
        target.classList.add('slide-element-editable');
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'slide-element-delete-btn';
        btn.textContent = 'حذف';
        btn.addEventListener('pointerdown', function(e) { e.stopPropagation(); e.preventDefault(); });
        btn.addEventListener('click', function(e) {
          e.stopPropagation();
          e.preventDefault();
          removeDeleteBtn();
          commitSlideElementDelete(stage, index, target, path);
        });
        // A selected watermark target is the logo img itself (a void element),
        // so the hover button docks on its overlay instead of throwing.
        const btnHost = (target.tagName === 'IMG' && target.parentElement) ? target.parentElement : target;
        btnHost.appendChild(btn);
        activeDeleteBtn = btn;
      });
      stage.addEventListener('mouseout', function handleSlideHoverOut(event) {
        if (!enabled) return;
        const related = event.relatedTarget;
        if (activeDeleteBtn && (!related || (!activeDeleteBtn.contains(related) && !activeDeleteBtn.parentElement?.contains(related)))) {
          const target = slideDragTarget(slide, event.target);
          if (target) target.classList.remove('slide-element-editable');
          removeDeleteBtn();
        }
      });
      stage.addEventListener('pointerdown', function handleSlidePointerDown(event) {
        if (event.button !== 0) return;
        if (slideElementDragActive) return;
        const target = slideDragTarget(slide, event.target);
        if (!target) return;
        const path = slideElementPath(slide, target);
        if (!path) return;
        event.preventDefault();
        event.stopPropagation();
        slideElementDragActive = true;
        const scale = Number(stage.style.getPropertyValue('--slide-scale')) || 1;
        const startX = event.clientX;
        const startY = event.clientY;
        const startTranslateX = Number(target.dataset.manualTranslateX) || 0;
        const startTranslateY = Number(target.dataset.manualTranslateY) || 0;
        let moved = false;
        target.classList.add('slide-element-editable');
        target.setPointerCapture?.(event.pointerId);

        const handlePointerMove = moveEvent => {
          const dx = (moveEvent.clientX - startX) / scale;
          const dy = (moveEvent.clientY - startY) / scale;
          if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
          target.style.transform = 'translate(' + Math.round(startTranslateX + dx) + 'px, ' + Math.round(startTranslateY + dy) + 'px)';
        };
        const finish = endEvent => {
          const dx = (endEvent.clientX - startX) / scale;
          const dy = (endEvent.clientY - startY) / scale;
          target.releasePointerCapture?.(event.pointerId);
          target.removeEventListener('pointermove', handlePointerMove);
          target.removeEventListener('pointerup', finish);
          target.removeEventListener('pointercancel', finish);
          target.classList.remove('slide-element-editable');
          slideElementDragActive = false;
          if (moved) commitSlideElementMove(stage, index, target, path, dx, dy);
          selectSlideElement(stage, index, target, path);
        };
        target.addEventListener('pointermove', handlePointerMove);
        target.addEventListener('pointerup', finish);
        target.addEventListener('pointercancel', finish);
      });
      stage.addEventListener('click', function handleSlideEditClick(event) {
        if (!getSlideEditSession(index)) return;
        if (event.target.closest('.slide-element-selected, .slide-resize-handle, .slide-move-handle, .slide-element-delete-btn')) return;
        if (event.target.closest && event.target.closest('[contenteditable]')) return;
        const session = slideEditSessions[index];
        if (session && session.sel) {
          const slideEl = stage.querySelector('.slide');
          const selected = slideEl ? elementAtSlidePath(slideEl, session.sel.path) : null;
          if (selected && (selected === event.target || selected.contains(event.target))) return;
        }
        if (slideDragTarget(slide, event.target)) return;
        clearSlideElementSelection(stage);
        if (session) session.sel = null;
        syncSlideElementToolbar(index);
      });
      stage.addEventListener('keydown', function handleSlideEditKey(event) {
        if (event.key !== 'Delete' && event.key !== 'Backspace') return;
        const ae = document.activeElement;
        if (ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|BUTTON|SELECT)$/.test(ae.tagName))) return;
        if (!getSlideEditSession(index)) return;
        event.preventDefault();
        event.stopPropagation();
        deleteSelectedSlideElement(index);
      });
    }