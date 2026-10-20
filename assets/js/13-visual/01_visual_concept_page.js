/* 13-visual.js - index.html lines 21642-23155, shared global scope, classic scripts in order */

    let visualConceptSiteAssistantBusy = false;

    function retryVisualConceptImageLoad(image) {
      if (!image || !image.isConnected) return;
      const card = image.closest('.visual-concept-card[data-visual-slot], [data-sketch-card]');
      const currentUrl = image.getAttribute('src') || '';
      if (!card || !currentUrl.startsWith('/uploads/')) return;
      const currentAttempt = Number(image.dataset.visualConceptLoadRetry || 0);
      if (currentAttempt >= 2) return;

      const nextAttempt = currentAttempt + 1;
      const retryUrl = new URL(currentUrl, window.location.origin);
      retryUrl.searchParams.set('t', Date.now() + '-' + nextAttempt);
      const refreshedUrl = retryUrl.pathname + retryUrl.search + retryUrl.hash;
      image.dataset.visualConceptLoadRetry = String(nextAttempt);
      image.src = refreshedUrl;
      const slotId = card.getAttribute('data-visual-slot') || card.getAttribute('data-sketch-card');
      const slot = tenantVisualConceptState?.slots?.[slotId];
      if (slot) {
        if (card.hasAttribute('data-sketch-card')) {
          const sketch = slot.sketch || (slot.sketch = emptyVisualConceptSketch());
          if (sketch.imageUrl === currentUrl) sketch.imageUrl = refreshedUrl;
          if (sketch.approvedImageUrl === currentUrl) sketch.approvedImageUrl = refreshedUrl;
        } else {
          if (slot.imageUrl === currentUrl) slot.imageUrl = refreshedUrl;
          if (slot.approvedImageUrl === currentUrl) slot.approvedImageUrl = refreshedUrl;
        }
        markVisualConceptDirty();
      }
      const preview = image.closest('.visual-concept-preview');
      if (preview) {
        preview.dataset.visualZoom = refreshedUrl;
        preview.querySelectorAll('[data-visual-zoom]').forEach(control => {
          control.dataset.visualZoom = refreshedUrl;
        });
      }
    }

    // A transient media response can fail after generation has succeeded. Retry
    // it in place so the user does not have to reopen the visual-concept view.
    document.addEventListener('error', event => {
      const image = event.target;
      if (image instanceof HTMLImageElement && image.closest('.visual-concept-preview')) {
        retryVisualConceptImageLoad(image);
      }
    }, true);

    // Card actions and the zoom lightbox are delegated once on the document:
    // every render replaces innerHTML, so listeners bound per-element died
    // silently whenever a subtree re-rendered after the binding pass.
    document.addEventListener('click', event => {
      const button = event.target.closest('[data-visual-action]');
      if (button && !button.disabled) {
        const action = button.getAttribute('data-visual-action');
        const slotId = button.getAttribute('data-visual-slot');
        if (action === 'generate') generateVisualConceptImage(slotId);
        else if (action === 'approve') approveVisualConceptImage(slotId);
        else if (action === 'unapprove') unapproveVisualConceptImage(slotId);
        else if (action === 'delete-image') deleteVisualConceptSlotImage(slotId);
        else if (action === 'delete-interior-field') deleteVisualConceptInteriorField(slotId);
        else if (action === 'delete-plan') deleteVisualConceptPlan(slotId);
        else if (action === 'chat') sendVisualConceptChat(slotId);
        else if (action === 'start-site-chat') startVisualConceptSiteChat();
        else if (action === 'restart-site-plan') restartVisualConceptSitePlan();
        else if (action === 'chat-choice') {
          const input = document.querySelector('[data-visual-chat="' + slotId + '"]');
          if (input) {
            if (button.getAttribute('data-choice-other') === 'true') {
              input.placeholder = 'إجابة أخرى';
              input.focus();
              return;
            }
            input.value = button.getAttribute('data-choice') || '';
            sendVisualConceptChat(slotId);
          }
        }
        else if (action === 'add-interior') addVisualConceptInteriorView();
        else if (action === 'section-approve') approveVisualConceptSection(button.getAttribute('data-visual-section'));
        else if (action === 'section-unapprove') unapproveVisualConceptSection(button.getAttribute('data-visual-section'));
        else if (action === 'regen-prompt') regenerateVisualConceptPrompt(slotId);
        else if (action === 'chat-attach') {
          const picker = document.querySelector('[data-visual-chat-upload="' + slotId + '"]');
          if (picker) picker.click();
        }
        else if (action === 'chat-ref-remove') removeVisualConceptChatRef(slotId, Number(button.getAttribute('data-ref-index')));
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

    document.addEventListener('keydown', event => {
      const input = event.target.closest?.('[data-visual-chat="plan_site"]');
      if (!input || event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      sendVisualConceptChat('plan_site');
    });

    function renderVisualConceptPage() {
      const host = document.getElementById('visualConceptWorkspace');
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      persistVisualConceptDraftState();
      updateVisualConceptHomeCards();
      if (!host) return;
      renderVisualConceptStyleReference();
      const externalLocked = visualConceptSectionLocked('external');
      const coverApproved = Boolean(tenantVisualConceptState.slots.cover.approvedImageUrl);
      const coverHtml = renderVisualConceptSlot(VISUAL_CONCEPT_SLOTS[0], externalLocked);
      const mainFacade = VISUAL_CONCEPT_EXTERNAL_SLOTS.find(item => item.id === 'main_facade');
      const mainFacadeHtml = mainFacade ? renderVisualConceptSlot(mainFacade, externalLocked || !coverApproved) : '';
      const angleHtml = VISUAL_CONCEPT_ANGLE_SLOTS.map(item => renderVisualConceptSlot(item, externalLocked || !coverApproved)).join('');
      const lockHint = externalLocked
        ? '<p class="tenant-hint visual-concept-lock-hint">التصورات الخارجية مقفلة حتى اعتماد قسم المخططات.</p>'
        : (coverApproved ? '' : '<p class="tenant-hint visual-concept-lock-hint">زوايا التصور الخارجي مقفلة حتى اعتماد الصورة الرئيسية.</p>');
      host.innerHTML = coverHtml +
        '<div class="visual-concept-stack">' +
        lockHint +
        mainFacadeHtml + angleHtml + '</div>';
      renderVisualConceptInteriorWorkspace();
      renderVisualConceptPlans();
      renderVisualConceptSketches();
      refreshVisualConceptSectionBars();
      if (typeof refreshActiveSectionApproveButton === 'function') refreshActiveSectionApproveButton();
      const bindRoot = document.getElementById('section-visual-concept') || document.getElementById('tenantVisualConceptPage') || host;
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
      bindRoot.querySelectorAll('[data-visual-chat-upload]').forEach(input => {
        input.addEventListener('change', () => attachVisualConceptChatImage(input.getAttribute('data-visual-chat-upload'), input));
      });
      // Pending chips live inside the re-rendered innerHTML — rebuild them or
      // the strip would come back empty while the ids are still held.
      bindRoot.querySelectorAll('[data-visual-chat-refs]').forEach(box => {
        renderVisualConceptChatRefs(box.getAttribute('data-visual-chat-refs'));
      });
      // The chat strip re-renders scrolled to the top — land on the newest
      // message instead, like every chat view.
      bindRoot.querySelectorAll('.visual-concept-chat').forEach(box => {
        box.scrollTop = box.scrollHeight;
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
      const allowed = new Set(['home', 'external', 'internal', 'plans2d', 'sketches']);
      let next = allowed.has(view) ? view : 'home';
      // A section view only opens once its predecessor section is approved —
      // locked navigation falls back to home with the reason on screen.
      if (visualConceptSectionLocked(next)) {
        showVisualConceptLockNotice(visualConceptSectionLockReason(next));
        next = 'home';
      }
      document.querySelectorAll('#section-visual-concept [data-visual-concept-view], #tenantVisualConceptPage [data-visual-concept-view]').forEach(node => {
        node.hidden = node.dataset.visualConceptView !== next;
      });
      if (typeof refreshActiveSectionApproveButton === 'function') refreshActiveSectionApproveButton();
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
        const payload = await collectVisualConceptPayload('cover', { syncPlanInputs: false });
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
        showVisualConceptLockNotice(visualConceptLockMessage(slotId));
        return;
      }
      showLoader('جاري إنشاء وصف التصور البصري', 'يتم قراءة بيانات المشروع والصور المرجعية...');
      try {
        const payload = await collectVisualConceptPayload(slotId);
        if (instruction) payload.instruction = instruction;
        const response = await visualConceptPlanJobApi('POST', '/api/visual-concept/prompt', payload);
        hideLoader();
        if (!response?.success || !response.prompt) {
          const message = visualConceptMissingMessage(response) || response?.error || 'تعذر إنشاء الوصف';
          showVisualConceptMissing(visualConceptMissingMessage(response));
          toast(message);
          return;
        }
        showVisualConceptMissing('');
        receiveVisualConceptPlanScene(response.scene, slotId);
        tenantVisualConceptState.slots[slotId].prompt = response.prompt;
        if (slotId === 'cover') {
          tenantVisualConceptState.slots[slotId].styleRefStamp = visualConceptStyleRefSignature();
        }
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast(WFT('vc.prompt_ready', 'تم تجهيز وصف {slot}', { slot: wfTr(visualConceptSlotLabel(slotId)) }));
      } catch (error) {
        hideLoader();
        toast(error.message || 'تعذر إنشاء الوصف');
      }
    }

    // Manual escape hatch for the hidden prompt: clearing it before the call
    // drops currentPrompt from the payload, so the writer runs in create mode
    // and stale prose cannot survive the rebuild — the old prompt is restored
    // only if the rewrite fails.
    async function regenerateVisualConceptPrompt(slotId) {
      if (!hasPermission('generate_images')) { toast('لا تملك صلاحية توليد الصور'); return; }
      if (visualConceptSlotLocked(slotId)) {
        showVisualConceptLockNotice(visualConceptLockMessage(slotId));
        return;
      }
      const liveSlot = () => tenantVisualConceptState.slots[slotId];
      const keepPrompt = liveSlot() ? liveSlot().prompt : '';
      if (liveSlot()) liveSlot().prompt = '';
      await generateVisualConceptPrompt(slotId);
      if (liveSlot() && !liveSlot().prompt && keepPrompt) {
        liveSlot().prompt = keepPrompt;
        markVisualConceptDirty();
      }
    }

    function applyVisualConceptSiteAssistantResponse(response) {
      const workflow = visualConceptPlansWorkflowState();
      const slot = tenantVisualConceptState?.slots?.plan_site;
      if (!slot || !response) return;
      if (response.contextChanged) {
        slot.svgCode = '';
        slot.imageUrl = '';
        slot.approvedImageUrl = '';
        slot.status = 'pending';
        slot.chat = [];
        workflow.scene = null;
        workflow.sourceStamp = '';
      }
      if (response.assistantState && typeof response.assistantState === 'object') {
        workflow.siteAssistant = normalizeVisualConceptPlansWorkflow({ siteAssistant: response.assistantState }).siteAssistant;
        slot.chat = workflow.siteAssistant.turns.slice(-30).map(turn => ({
          role: turn.role, text: turn.text, choices: turn.choices || [], attachments: []
        }));
      }
      if (response.scene && typeof response.scene === 'object') {
        receiveVisualConceptPlanScene(response.scene, 'plan_site');
        workflow.sourceStamp = visualConceptPlanInputStamp();
      }
      const responseParts = [response.reply, response.question]
        .map(value => String(value || '').trim()).filter(Boolean);
      const mergeMessageText = (current, addition) => {
        const left = String(current || '').trim();
        const right = String(addition || '').trim();
        if (!left) return right;
        if (!right || left.includes(right)) return left;
        if (right.includes(left)) return right;
        return left + '\n\n' + right;
      };
      const responseText = responseParts.reduce(mergeMessageText, '');
      const responseChoices = Array.isArray(response.choices)
        ? response.choices.map(value => String(value || '').trim()).filter(Boolean) : [];
      if (responseText) {
        const generatedPlanReply = Boolean(response.image || response.svgCode);
        const latestAssistant = [...slot.chat].reverse().find(item => item.role === 'assistant');
        const responseMatchesLatest = latestAssistant && responseParts.some(part =>
          latestAssistant.text.includes(part) || part.includes(latestAssistant.text));
        if (generatedPlanReply) {
          if (!latestAssistant || !latestAssistant.text.includes(responseText)) {
            slot.chat.push({ role: 'assistant', text: responseText, choices: [] });
          }
        } else if (responseMatchesLatest) {
          latestAssistant.text = responseParts.reduce(mergeMessageText, latestAssistant.text);
          latestAssistant.choices = [...new Set([...(latestAssistant.choices || []), ...responseChoices])];
        } else {
          slot.chat.push({ role: 'assistant', text: responseText, choices: responseChoices });
        }
      }
      if (response.svgCode) {
        slot.svgCode = String(response.svgCode).slice(0, 300000);
        const fallbackDataUri = 'data:image/svg+xml;utf8,' + encodeURIComponent(slot.svgCode);
        slot.imageUrl = visualConceptImageUrl(response.image || slot.imageUrl || fallbackDataUri);
        slot.approvedImageUrl = '';
        slot.status = 'review';
        workflow.siteAssistant.checkpoints = response.assistantState?.checkpoints || workflow.siteAssistant.checkpoints;
      }
      markVisualConceptDirty();
    }

    function visualConceptPlansResetBusy() {
      const generatingPlan = VISUAL_CONCEPT_PLAN_KINDS.some(item =>
        tenantVisualConceptState?.slots?.[item.id]?.status === 'generating');
      const workflowRequestBusy = typeof visualConceptPlanRequests !== 'undefined'
        && visualConceptPlanRequests.size > 0;
      return Boolean(visualConceptSiteAssistantBusy || visualConceptPlanScenePending
        || generatingPlan || workflowRequestBusy);
    }

    async function restartVisualConceptSitePlan() {
      if (!hasPermission('generate_images')) {
        toast('لا تملك صلاحية توليد المخططات');
        return false;
      }
      if (visualConceptPlansResetBusy()) {
        toast('معالجة المخطط ما زالت قيد التنفيذ.');
        return false;
      }
      if (visualConceptSlotLocked('plan_site')) {
        showVisualConceptLockNotice(visualConceptLockMessage('plan_site'));
        return false;
      }
      if (typeof confirm !== 'function' || !confirm(
        'سيتم مسح محادثة المخطط وسياق المساعد السابق فقط. ستبقى نتائج الفحص والتوزيع والاعتمادات والمخططات كما هي. هل تريد البدء من جديد؟')) {
        return false;
      }

      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      const workflow = visualConceptPlansWorkflowState();
      workflow.siteAssistant = emptyVisualConceptPlansWorkflow().siteAssistant;
      workflow.jobTodos = [];
      const slot = tenantVisualConceptState.slots.plan_site
        || (tenantVisualConceptState.slots.plan_site = emptyVisualConceptSlot('plan_site'));
      slot.chat = [];
      markVisualConceptDirty();
      renderVisualConceptPage();
      await startVisualConceptSiteChat();
      return true;
    }

    async function startVisualConceptSiteChat() {
      if (visualConceptSiteAssistantBusy) return;
      if (!hasPermission('generate_images')) { toast('لا تملك صلاحية توليد الصور'); return; }
      if (visualConceptSlotLocked('plan_site')) {
        showVisualConceptLockNotice(visualConceptLockMessage('plan_site'));
        return;
      }
      const slot = tenantVisualConceptState?.slots?.plan_site;
      const assistant = visualConceptPlansWorkflowState().siteAssistant || {};
      if (!slot || (assistant.turns || []).length || (slot.chat || []).length) return;

      visualConceptSiteAssistantBusy = true;
      const workflow = visualConceptPlansWorkflowState();
      workflow.jobTodos = [
        { id: '1', label: 'فحص بيانات الأرض والتوزيع', status: 'active' },
        { id: '2', label: 'تجهيز المشهد الهندسي', status: 'pending' },
        { id: '3', label: 'مراجعة الإجابات السابقة', status: 'pending' },
        { id: '4', label: 'تحليل المتطلبات وتحديد السؤال', status: 'pending' },
      ];
      markVisualConceptDirty();
      renderVisualConceptPage();
      try {
        const current = visualConceptPlansWorkflowState();
        const currentStamp = visualConceptPlanInputStamp();
        const reviewCurrent = !current.clientNotes.trim()
          || (current.sourceStamp === currentStamp && visualConceptPlanNotesCleared(current));
        if (!reviewCurrent) {
          const notesCleared = await checkVisualConceptPlanNotes({ silent: true });
          if (!notesCleared) return;
        }
        const payload = await collectVisualConceptPlansWorkflowPayload({
          siteAssistantContext: true, assistantAction: 'chat'
        });
        payload.planAssistantAction = 'chat';
        const response = await visualConceptPlanJobApi(
          'POST', '/api/visual-concept/site-plan-assistant', payload);
        if (!response?.success) {
          toast(response?.error || 'تعذر مراجعة بيانات المخطط');
          return;
        }
        applyVisualConceptSiteAssistantResponse(response);
      } catch (error) {
        toast(error.message || 'تعذر مراجعة بيانات المخطط');
      } finally {
        visualConceptSiteAssistantBusy = false;
        renderVisualConceptPage();
      }
    }

    async function generateVisualConceptImage(slotId) {
      if (!hasPermission('generate_images')) { toast('لا تملك صلاحية توليد الصور'); return; }
      resetTenantGenerationStop();
      // Never hold a slot reference across an await or a render: renderVisualConceptPage
      // reassigns tenantVisualConceptState through normalizeVisualConceptState, so a
      // captured slot is detached and the generated image was written to a dead object.
      const liveSlot = () => tenantVisualConceptState.slots[slotId];
      if (!liveSlot() || liveSlot().status === 'generating') return;
      const sitePlan = slotId === 'plan_site' && isVisualConceptWorkflowPlan(slotId);
      if (sitePlan && visualConceptSiteAssistantBusy) return;
      if (visualConceptSlotLocked(slotId)) {
        showVisualConceptLockNotice(visualConceptLockMessage(slotId));
        return;
      }
      if (!sitePlan && !liveSlot().prompt) {
        await generateVisualConceptPrompt(slotId);
      } else if (!sitePlan && slotId === 'cover' && visualConceptCoverStyleRefStale()) {
        // The hidden prompt predates the ref names — the prompt writer edits
        // just the reference assignments in place, so the new mapping is
        // written in proper prompt language without touching anything else.
        await generateVisualConceptPrompt(
          slotId,
          'الصور المرجعية للتصميم اتغيّرت — حدّث تعيينها في الوصف فقط: اربط كل صورة مرجعية مسمّاة بالعنصر الذي يصفه اسمها كما ورد في بيانات المشروع، واحذف تعيين أي صورة لم تعد موجودة، ولا تغيّر أي تفاصيل أخرى.');
      }
      if (!liveSlot() || (!sitePlan && !liveSlot().prompt)) return;
      const previousImage = liveSlot().imageUrl || liveSlot().approvedImageUrl;
      if (sitePlan) visualConceptSiteAssistantBusy = true;
      liveSlot().status = 'generating';
      renderVisualConceptPage();
      showLoader('جاري توليد التصور البصري', WFT('vc.generating_slot', 'يتم توليد {slot}...', { slot: wfTr(visualConceptSlotLabel(slotId)) }),
        { stoppable: true });
      try {
        const payload = sitePlan
          ? await collectVisualConceptPlansWorkflowPayload({
            siteAssistantContext: true, assistantAction: 'generate'
          })
          : await collectVisualConceptPayload(slotId);
        if (sitePlan) {
          payload.planAssistantAction = 'generate';
          payload.siteSvgCode = liveSlot().svgCode || '';
        }
        const response = sitePlan
          ? await visualConceptPlanJobApi('POST', '/api/visual-concept/site-plan-assistant', payload)
          : (isVisualConceptWorkflowPlan(slotId)
            ? await visualConceptPlanJobApi('POST', '/api/visual-concept/generate', payload)
            : await runTenantGenerationJob('POST', '/api/visual-concept/generate', payload,
              '/api/visual-concept/plans-jobs/'));
        hideLoader();
        if (sitePlan && response?.success && !response.image) {
          applyVisualConceptSiteAssistantResponse(response);
          renderVisualConceptPage();
          return;
        }
        if (!response?.success || !response.image) {
          liveSlot().status = previousImage ? 'review' : 'pending';
          renderVisualConceptPage();
          const message = visualConceptMissingMessage(response) || response?.error || 'تعذر توليد الصورة';
          showVisualConceptMissing(visualConceptMissingMessage(response));
          toast(message);
          return;
        }
        showVisualConceptMissing('');
        if (isVisualConceptWorkflowPlan(slotId)) {
          receiveVisualConceptPlanScene(response.scene, slotId);
          if (response.scene?.token) liveSlot().sceneToken = response.scene.token;
        }
        if (sitePlan) applyVisualConceptSiteAssistantResponse(response);
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
      } finally {
        if (sitePlan) {
          visualConceptSiteAssistantBusy = false;
          renderVisualConceptPage();
        }
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
      toast(WFT('vc.slot_approved', 'تم اعتماد {slot}', { slot: wfTr(visualConceptSlotLabel(slotId)) }));
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
      toast(WFT('vc.slot_unapproved', 'تم إلغاء اعتماد {slot}', { slot: wfTr(visualConceptSlotLabel(slotId)) }));
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
      if (slotId === 'main_facade' && tenantCreativeImages) {
        tenantCreativeImages.main_facade = '';
      }
      const moodboardIndex = VISUAL_CONCEPT_ANGLE_SLOTS.findIndex(item => item.id === slotId);
      if (moodboardIndex >= 0 && Array.isArray(tenantCreativeImages?.moodboard)) {
        tenantCreativeImages.moodboard[moodboardIndex] = '';
      }
      markVisualConceptDirty();
      renderVisualConceptPage();
      toast('تم حذف الصورة');
    }

    // Pending per-message attachments: the client pins the exact reference
    // image next to an edit request, so "use this on that element" binds to
    // pixels instead of a name buried in the hidden prompt. Transient — the
    // chips clear once the message carrying them succeeds.
    const visualConceptChatRefs = {};

    async function attachVisualConceptChatImage(slotId, input) {
      const files = Array.from(input?.files || []);
      if (!files.length) return;
      try {
        input.dataset.projectFileType = 'visual_reference';
        const uploaded = await uploadTenantProjectFileInput(input, 'visual_style_reference');
        const incoming = (Array.isArray(uploaded) ? uploaded : [uploaded]).map((file, index) => ({
          id: file?.id || file,
          name: file?.originalName || files[index]?.name || ''
        })).filter(file => file.id);
        if (!incoming.length) throw new Error('تعذر رفع الصورة');
        const list = visualConceptChatRefs[slotId] || (visualConceptChatRefs[slotId] = []);
        incoming.forEach(file => {
          if (list.length < 5 && !list.some(item => String(item.id) === String(file.id))) list.push(file);
        });
        renderVisualConceptChatRefs(slotId);
      } catch (error) {
        toast(error.message || 'تعذر رفع الصورة');
      } finally {
        if (input) input.value = '';
      }
    }

    function renderVisualConceptChatRefs(slotId) {
      const box = document.querySelector('[data-visual-chat-refs="' + slotId + '"]');
      if (!box) return;
      const list = visualConceptChatRefs[slotId] || [];
      box.innerHTML = list.map((file, index) =>
        '<span class="visual-concept-chat-ref-chip">' + escapeHtml(file.name || file.id) +
        '<button type="button" class="visual-concept-chat-ref-remove" data-visual-action="chat-ref-remove"' +
        ' data-visual-slot="' + slotId + '" data-ref-index="' + index + '">حذف</button></span>'
      ).join('');
    }

    function removeVisualConceptChatRef(slotId, index) {
      const list = visualConceptChatRefs[slotId] || [];
      if (index < 0 || index >= list.length) return;
      list.splice(index, 1);
      renderVisualConceptChatRefs(slotId);
    }

    async function sendVisualConceptChat(slotId) {
      resetTenantGenerationStop();
      if (slotId === 'plan_site' && visualConceptSiteAssistantBusy) return;
      if (!hasPermission('generate_images')) { toast('لا تملك صلاحية توليد الصور'); return; }
      if (visualConceptSlotLocked(slotId)) {
        showVisualConceptLockNotice(visualConceptLockMessage(slotId));
        return;
      }
      const input = document.querySelector('[data-visual-chat="' + slotId + '"]');
      const message = (input?.value || '').trim();
      if (!message) {
        toast('اكتب طلب التعديل أولاً');
        return;
      }
      const liveSlot = () => tenantVisualConceptState.slots[slotId];
      // With a durable image the edit applies to the image itself, wrapped in the
      // server's fixed surgical-edit contract. Before the first image exists the
      // same box steers the hidden prompt instead — there is nothing to edit yet.
      const planWorkflowSlot = isVisualConceptWorkflowPlan(slotId);
      const sitePlan = slotId === 'plan_site' && planWorkflowSlot;
      if (sitePlan) {
        const assistant = visualConceptPlansWorkflowState().siteAssistant || {};
        if (!(assistant.turns || []).length && !(liveSlot().chat || []).length && !liveSlot().svgCode) {
          return;
        }
        visualConceptSiteAssistantBusy = true;
      }
      const baseImage = durableImageUrl(liveSlot().imageUrl || liveSlot().approvedImageUrl);
      // Workflow plans edit the shared geometric scene rather than pixels: even
      // before the first render the same box applies a surgical scene edit and
      // the server re-renders the diagram from the validated result.
      const editImage = sitePlan ? Boolean(liveSlot().svgCode) : (planWorkflowSlot || Boolean(baseImage));
      const refs = sitePlan ? [] : (visualConceptChatRefs[slotId] || []).slice(0, 5);
      liveSlot().chat.push({ role: 'user', text: message, attachments: refs.map(file => file.name) });
      markVisualConceptDirty();
      if (sitePlan) {
        const workflow = visualConceptPlansWorkflowState();
        workflow.jobTodos = [
          { id: '1', label: 'مراجعة متطلبات التوليد', status: 'active' },
          { id: '2', label: 'مراجعة بيانات الموقع والإجابات', status: 'pending' },
          { id: '3', label: 'تجهيز السؤال أو المخطط', status: 'pending' },
        ];
        const todos = document.querySelector('[data-plans-workflow-todos]');
        if (todos) todos.innerHTML = visualConceptPlanTodoMarkup(workflow.jobTodos);
        markVisualConceptDirty();
        renderVisualConceptPage();
      } else {
        showLoader(
          editImage ? WFT('vc.edit_running', 'جاري تعديل الصورة') : WFT('vc.edit_running', 'جاري تعديل وصف الصورة'),
          editImage ? WFT('vc.edit_running_detail', 'يتم تطبيق التعديل على نفس الصورة دون تغيير باقي تفاصيلها...') : 'يتم تطبيق ملاحظاتك على نفس المشروع...',
          { stoppable: true });
      }
      try {
        if (sitePlan) {
          const workflow = visualConceptPlansWorkflowState();
          const currentStamp = visualConceptPlanInputStamp();
          const reviewCurrent = !workflow.clientNotes.trim()
            || (workflow.sourceStamp === currentStamp && visualConceptPlanNotesCleared(workflow));
          if (!reviewCurrent) {
            const notesCleared = await checkVisualConceptPlanNotes({ silent: true });
            if (!notesCleared) {
              liveSlot().chat.push({ role: 'assistant', text: 'تعذر إكمال مراجعة متطلبات التوليد.' });
              markVisualConceptDirty();
              renderVisualConceptPage();
              return;
            }
          }
        }
        const payload = sitePlan
          ? await collectVisualConceptPlansWorkflowPayload({
            siteAssistantContext: true, assistantAction: editImage ? 'edit' : 'chat'
          })
          : await collectVisualConceptPayload(slotId);
        payload.message = message;
        if (editImage && !sitePlan) payload.image = baseImage;
        if (refs.length) payload.editReferenceFileIds = refs.map(file => file.id);
        if (sitePlan) {
          payload.planAssistantAction = editImage ? 'edit' : 'chat';
          payload.siteSvgCode = liveSlot().svgCode || '';
        }
        if (planWorkflowSlot && !sitePlan) visualConceptPlanScenePending = true;
        const response = sitePlan
          ? await visualConceptPlanJobApi('POST', '/api/visual-concept/site-plan-assistant', payload)
          : (planWorkflowSlot
            ? await visualConceptPlanJobApi('POST', '/api/visual-concept/edit', payload)
          : (editImage
            ? await runTenantGenerationJob('POST', '/api/visual-concept/edit', payload,
              '/api/visual-concept/plans-jobs/')
            : await runTenantGenerationJob('POST', '/api/visual-concept/chat', payload,
              '/api/visual-concept/plans-jobs/')));
        if (!sitePlan) hideLoader();
        if (sitePlan && response?.success) {
          applyVisualConceptSiteAssistantResponse(response);
          if (input) input.value = '';
          renderVisualConceptPage();
          if (response.image) toast('تم تعديل المخطط.');
          return;
        }
        if (editImage && response?.needsClarification) {
          showVisualConceptMissing('');
          liveSlot().chat.push({
            role: 'assistant',
            text: response.question || WFT('vc.clarify_fallback', 'حدد ما الذي تريد تغييره في الصورة بالضبط.')
          });
          markVisualConceptDirty();
          renderVisualConceptPage();
          return;
        }
        const editFailed = editImage ? (!response?.success || !response.image) : (!response?.success || !response.prompt);
        if (editFailed) {
          const errorText = visualConceptMissingMessage(response) || response?.error
            || (editImage ? WFT('vc.edit_failed', 'تعذر تعديل الصورة') : 'تعذر تعديل الوصف');
          showVisualConceptMissing(visualConceptMissingMessage(response));
          toast(errorText);
          return;
        }
        showVisualConceptMissing('');
        visualConceptChatRefs[slotId] = [];
        if (editImage) {
          if (planWorkflowSlot) {
            receiveVisualConceptPlanScene(response.scene, slotId);
            if (response.scene?.token) liveSlot().sceneToken = response.scene.token;
          }
          liveSlot().imageUrl = visualConceptImageUrl(response.image);
          liveSlot().approvedImageUrl = '';
          liveSlot().status = 'review';
          liveSlot().chat.push({ role: 'assistant', text: response.reply || WFT('vc.edited_reply', 'تم تعديل الصورة حسب طلبك.') });
          markVisualConceptDirty();
          renderVisualConceptPage();
          toast(WFT('vc.edited_toast', 'تم تعديل الصورة — اعتمدها لتثبيتها.'));
        } else {
          liveSlot().prompt = response.prompt;
          if (slotId === 'cover') liveSlot().styleRefStamp = visualConceptStyleRefSignature();
          liveSlot().chat.push({ role: 'assistant', text: response.reply || 'تم تحديث وصف الصورة.' });
          markVisualConceptDirty();
          renderVisualConceptPage();
          toast('تم تحديث الوصف. اضغط توليد الصورة لتطبيق التعديل.');
        }
      } catch (error) {
        if (!sitePlan) hideLoader();
        toast(error.message || WFT('vc.edit_failed', 'تعذر تعديل الصورة'));
      } finally {
        if (sitePlan) visualConceptSiteAssistantBusy = false;
        if (planWorkflowSlot) {
          visualConceptPlanScenePending = false;
          renderVisualConceptPage();
        }
      }
    }
