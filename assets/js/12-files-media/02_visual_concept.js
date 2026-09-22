    function persistVisualConceptDraftState() {
      const previousImages = tenantCreativeImages || {};
      const previousMoodboard = Array.isArray(previousImages.moodboard) ? previousImages.moodboard : [];
      const previousPrompts = Array.isArray(previousImages.moodboard_prompts) ? previousImages.moodboard_prompts : [];
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState || tenantProjectData.visual_concept);
      tenantProjectData.visual_concept = tenantVisualConceptState;
      tenantVisualConceptState.plansWorkflow = normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow);
      VISUAL_CONCEPT_PLAN_KINDS.forEach(definition => {
        const slot = tenantVisualConceptState.slots[definition.id];
        if (!slot || (!slot.prompt && !slot.imageUrl && !slot.approvedImageUrl)) return;
        let plan = (tenantVisualConceptState.plans2d || []).find(item => item.id === definition.id);
        if (!plan) {
          plan = { id: definition.id, mode: 'ai', title: definition.label, description: definition.label, fileId: '', fileName: '', imageUrl: '' };
          tenantVisualConceptState.plans2d.push(plan);
        }
      });
      // The durable plan record mirrors its slot so slides and exports keep reading plans2d.
      (tenantVisualConceptState.plans2d || []).forEach(plan => {
        const slot = tenantVisualConceptState.slots[plan.id];
        if (!slot) return;
        plan.mode = slot.mode === 'upload' ? 'upload' : 'ai';
        plan.title = String(slot.label || '').slice(0, 120);
        plan.description = String(slot.caption || '').slice(0, 2000);
        plan.fileId = String(slot.sourceFileId || '');
        plan.fileName = String(slot.sourceFileName || '');
        plan.imageUrl = durableImageUrl(slot.approvedImageUrl) || durableImageUrl(slot.imageUrl);
      });
      const referenceIds = Array.isArray(tenantVisualConceptState.styleReferenceFileIds)
        ? tenantVisualConceptState.styleReferenceFileIds.slice(0, 5) : [];
      tenantProjectData.visual_style_reference_file_ids = referenceIds;
      tenantProjectData.visual_style_reference_file_id = referenceIds[0] || '';
      const cover = tenantVisualConceptState.slots.cover || {};
      tenantCreativeImages = previousImages;
      // These mirrors reach the export and the slide prompts, so a session-only blob URL is
      // dropped here: it would arrive on the server as an image that can never be read.
      tenantCreativeImages.cover = durableImageUrl(cover.approvedImageUrl) || durableImageUrl(tenantCreativeImages.cover);
      tenantCreativeImages.cover_prompt = cover.prompt || tenantCreativeImages.cover_prompt || '';
      tenantCreativeImages.moodboard = VISUAL_CONCEPT_EXTERNAL_SLOTS.slice(1).map((item, index) => {
        const slot = tenantVisualConceptState.slots[item.id] || {};
        return durableImageUrl(slot.approvedImageUrl) || durableImageUrl(slot.imageUrl) || durableImageUrl(previousMoodboard[index]);
      });
      tenantCreativeImages.moodboard_prompts = VISUAL_CONCEPT_EXTERNAL_SLOTS.slice(1).map((item, index) => {
        const slot = tenantVisualConceptState.slots[item.id] || {};
        return slot.prompt || previousPrompts[index] || '';
      });
      tenantProjectData.tenantCreativeImages = tenantCreativeImages;
      const hidden = document.getElementById('visualConceptData');
      if (hidden) hidden.value = JSON.stringify(tenantVisualConceptState);
    }

    function markVisualConceptDirty() {
      persistVisualConceptDraftState();
      setDraftDirty(true);
    }

    function visualConceptMissingMessage(response) {
      const missing = Array.isArray(response?.missingFields) ? response.missingFields : [];
      if (!missing.length) return response?.error || '';
      return 'أكمل الحقول الناقصة: ' + missing.map(item => item.label || item.key).join('، ');
    }

    async function collectVisualConceptPayload(slotId) {
      if (typeof persistClassificationDraftState === 'function') persistClassificationDraftState();
      if (typeof persistMarketStudyFromDom === 'function' && document.getElementById('marketStudyData')) persistMarketStudyFromDom();
      if (typeof persistExecutiveContentFromDom === 'function' && document.getElementById('executiveContentData')) persistExecutiveContentFromDom();
      persistVisualConceptDraftState();
      let projectData = { ...tenantProjectData };
      if (typeof collectTenantFormData === 'function' && document.getElementById('tenantProjectForm')) {
        projectData = { ...projectData, ...(await collectTenantFormData()) };
      }
      if (document.getElementById('section-financial-calc') && typeof collectFinancialStudyModel === 'function') {
        projectData.financial_study_model = collectFinancialStudyModel();
      }
      tenantProjectData = projectData;
      return {
        slotId,
        projectData,
        creativeImages: tenantCreativeImages,
        coverImage: tenantVisualConceptState.slots.cover.approvedImageUrl || tenantVisualConceptState.slots.cover.imageUrl || '',
        coverFileId: tenantVisualConceptState.slots.cover.sourceFileId || '',
        slotLabel: visualConceptSlotLabel(slotId),
        currentPrompt: document.querySelector('[data-visual-prompt="' + slotId + '"]')?.value
          || tenantVisualConceptState.slots[slotId]?.prompt || '',
        prompt: document.querySelector('[data-visual-prompt="' + slotId + '"]')?.value
          || tenantVisualConceptState.slots[slotId]?.prompt || '',
        componentId: isVisualConceptInteriorSlot(slotId)
          ? (visualConceptInteriorComponentIdFromSlot(slotId) || selectedVisualConceptInteriorComponentId())
          : '',
        referenceFileIds: isVisualConceptInteriorSlot(slotId)
          ? visualConceptInteriorReferenceIds(slotId)
          : [],
        planDescription: isVisualConceptPlanSlot(slotId)
          ? (visualConceptPlans().find(item => item.id === slotId)?.description || '')
          : '',
        planKind: visualConceptPlanKind(slotId),
        // Exterior slots also ship the workflow + the approved plan diagrams:
        // the server grounds their prompts on the deterministic measurements and
        // feeds the three plan images as generation references.
        plansWorkflow: normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow),
        planImages: visualConceptPlanImageMap(),
        planBoundaryPoints: isVisualConceptWorkflowPlan(slotId)
          ? normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow).boundary.points
          : [],
        planBoundaryReferenceUrl: isVisualConceptWorkflowPlan(slotId)
          ? normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow).boundary.referenceUrl
          : ''
      };
    }

    function visualConceptPlansApproved() {
      const slots = tenantVisualConceptState?.slots || {};
      return VISUAL_CONCEPT_PLAN_KINDS.every(item => Boolean(slots[item.id]?.approvedImageUrl));
    }

    function visualConceptPlanImageMap() {
      const slots = tenantVisualConceptState?.slots || {};
      const map = {};
      VISUAL_CONCEPT_PLAN_KINDS.forEach(item => {
        const url = durableImageUrl(slots[item.id]?.approvedImageUrl);
        if (url) map[item.kind] = url;
      });
      return map;
    }

    function visualConceptLockMessage(slotId) {
      if (isVisualConceptPlanSlot(slotId)) {
        const planKind = visualConceptPlanKind(slotId);
        if (planKind === 'uses') return 'مقفل حتى اعتماد مخطط الموقع العام.';
        if (planKind === 'massing') return 'مقفل حتى اعتماد مخططي الموقع العام وتوزيع الأدوار.';
      }
      if (isVisualConceptInteriorSlot(slotId)) return 'أضف مكونات المشروع واعتمد الصورة الرئيسية أولاً.';
      if (!visualConceptPlansApproved()) return 'اعتمد المخططات الثلاثة أولاً.';
      return 'اعتمد الصورة الرئيسية أولاً.';
    }

    function visualConceptSlotLocked(slotId) {
      // The plan diagrams generate in sequence — each is drawn on the previous
      // approved image, so a later plan stays locked until its predecessors
      // are approved.
      if (isVisualConceptPlanSlot(slotId)) {
        const planKind = visualConceptPlanKind(slotId);
        const slots = tenantVisualConceptState?.slots || {};
        const siteApproved = Boolean(durableImageUrl(slots.plan_site?.approvedImageUrl));
        const usesApproved = Boolean(durableImageUrl(slots.plan_uses?.approvedImageUrl));
        if (planKind === 'uses') return !siteApproved;
        if (planKind === 'massing') return !siteApproved || !usesApproved;
        return false;
      }
      if (isVisualConceptInteriorSlot(slotId)) {
        return !tenantVisualConceptState.slots.cover.approvedImageUrl || !visualConceptInteriorComponents().length;
      }
      // Exterior renders are built on the approved plan diagrams, so they stay
      // locked until all three plans are approved; the angles still wait for
      // the hero image on top of that.
      if (!visualConceptPlansApproved()) return true;
      return slotId !== 'cover' && !tenantVisualConceptState.slots.cover.approvedImageUrl;
    }

    function selectedVisualConceptInteriorComponentId() {
      const select = document.getElementById('visualConceptInteriorComponentSelect');
      return String(select?.value || tenantVisualConceptState?.selectedInteriorComponentId || visualConceptInteriorComponents()[0]?.id || '').trim();
    }

    function visualConceptInteriorReferenceIds(slotId) {
      const componentId = visualConceptInteriorComponentIdFromSlot(slotId) || selectedVisualConceptInteriorComponentId();
      const firstId = visualConceptInteriorSlotId(componentId, 1);
      const slot = tenantVisualConceptState.slots[slotId] || {};
      const first = tenantVisualConceptState.slots[firstId] || {};
      const ids = Array.isArray(slot.styleReferenceFileIds) && slot.styleReferenceFileIds.length
        ? slot.styleReferenceFileIds
        : (first.styleReferenceFileIds || []);
      return ids.slice(0, 5);
    }

    function visualConceptInteriorViewIds(componentId) {
      const deleted = new Set(tenantVisualConceptState.deletedInteriorSlots || []);
      const ids = [];
      for (let view = 1; view <= VISUAL_CONCEPT_MAX_INTERIOR_IMAGES; view += 1) {
        const id = visualConceptInteriorSlotId(componentId, view);
        if (tenantVisualConceptState.slots[id] && !deleted.has(id)) ids.push(id);
      }
      return ids;
    }

    function addVisualConceptInteriorView() {
      const componentId = selectedVisualConceptInteriorComponentId();
      if (!componentId) return;
      const existing = visualConceptInteriorViewIds(componentId);
      if (existing.length >= VISUAL_CONCEPT_MAX_INTERIOR_IMAGES) return;
      let nextId = '';
      for (let view = 1; view <= VISUAL_CONCEPT_MAX_INTERIOR_IMAGES; view += 1) {
        const candidate = visualConceptInteriorSlotId(componentId, view);
        if (!tenantVisualConceptState.slots[candidate]) { nextId = candidate; break; }
      }
      if (!nextId) return;
      tenantVisualConceptState.deletedInteriorSlots = (tenantVisualConceptState.deletedInteriorSlots || [])
        .filter(id => id !== nextId);
      tenantVisualConceptState.slots[nextId] = emptyVisualConceptSlot(nextId);
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    function renderVisualConceptInteriorReferences(slotId) {
      const preview = document.getElementById('visualConceptInteriorReferencePreview');
      if (!preview) return;
      const componentId = visualConceptInteriorComponentIdFromSlot(slotId) || selectedVisualConceptInteriorComponentId();
      const firstId = visualConceptInteriorSlotId(componentId, 1);
      const slot = tenantVisualConceptState.slots[firstId] || tenantVisualConceptState.slots[slotId] || emptyVisualConceptSlot(firstId);
      const ids = Array.isArray(slot.styleReferenceFileIds) ? slot.styleReferenceFileIds : [];
      const names = Array.isArray(slot.styleReferenceNames) ? slot.styleReferenceNames : [];
      if (!ids.length) {
        preview.textContent = 'لم تُرفع صور مرجعية لهذا المكون.';
        return;
      }
      preview.innerHTML = '<div class="visual-concept-reference-list"></div>';
      const list = preview.firstElementChild;
      ids.forEach((fileId, index) => {
        const item = document.createElement('div');
        item.className = 'visual-concept-reference-item';
        item.innerHTML = '<img alt="صورة مرجعية ' + (index + 1) + '"><span>' + escapeHtml(names[index] || ('صورة مرجعية ' + (index + 1))) + '</span>';
        list.appendChild(item);
        attachProjectFileThumbnail(item.querySelector('img'), fileId);
      });
    }

    function renderVisualConceptInteriorWorkspace() {
      const host = document.getElementById('visualConceptInternalWorkspace');
      const select = document.getElementById('visualConceptInteriorComponentSelect');
      const hint = document.getElementById('visualConceptInteriorHint');
      const referenceCard = document.getElementById('visualConceptInteriorReferenceCard');
      if (!host) return;
      const components = visualConceptInteriorComponents();
      const coverApproved = Boolean(tenantVisualConceptState.slots.cover.approvedImageUrl);
      if (select) {
        const current = selectedVisualConceptInteriorComponentId();
        select.innerHTML = components.length
          ? components.map(item => '<option value="' + escapeHtml(item.id) + '"' + (item.id === current ? ' selected' : '') + '>' + escapeHtml(item.name) + '</option>').join('')
          : '<option value="">لا توجد مكونات في الدراسة المالية</option>';
        if (components.some(item => item.id === current)) select.value = current;
        else if (components[0]) select.value = components[0].id;
        tenantVisualConceptState.selectedInteriorComponentId = select.value || '';
      }
      if (hint) {
        if (!components.length) hint.textContent = 'أضف مكونات المشروع في الدراسة المالية أولًا.';
        else hint.textContent = '';
      }
      if (referenceCard) referenceCard.hidden = !components.length;
      const selectedId = selectedVisualConceptInteriorComponentId();
      if (!selectedId) {
        host.innerHTML = '<p class="tenant-hint">لا توجد مكونات لتوليد صور داخلية.</p>';
        return;
      }
      const component = components.find(item => item.id === selectedId);
      const viewIds = visualConceptInteriorViewIds(selectedId);
      viewIds.forEach(id => {
        if (!tenantVisualConceptState.slots[id]) tenantVisualConceptState.slots[id] = emptyVisualConceptSlot(id);
      });
      const cards = viewIds.map((id, index) => renderVisualConceptSlot({
        id,
        label: 'تصور داخلي: ' + (component?.name || 'المكون') + ' — صورة ' + (index + 1),
        group: 'internal'
      }, !coverApproved)).join('');
      const canAdd = viewIds.length < VISUAL_CONCEPT_MAX_INTERIOR_IMAGES;
      host.innerHTML = '<div class="visual-concept-interior-stack">' + cards + '</div>' +
        (canAdd ? '<div class="visual-concept-actions" style="margin-top:12px"><button type="button" class="btn ghost small" data-visual-action="add-interior">إضافة صورة داخلية</button></div>' : '');
      renderVisualConceptInteriorReferences(viewIds[0]);
      const allApproved = viewIds.length > 0 && viewIds.every(id => tenantVisualConceptState.slots[id]?.status === 'approved');
      if (referenceCard) {
        referenceCard.classList.toggle('section-locked', allApproved);
        referenceCard.querySelectorAll('input, button').forEach(control => {
          control.disabled = allApproved;
        });
      }
    }

    function renderVisualConceptSlot(slotDef, locked) {
      const slot = tenantVisualConceptState.slots[slotDef.id];
      const stored = slot.approvedImageUrl || slot.imageUrl;
      const image = isSessionOnlyImageUrl(stored) ? '' : stored;
      const hasImage = Boolean(image || slot.sourceFileId);
      // Approval is one toggle per image and it locks that card, exactly like a section.
      const approved = slot.status === 'approved';
      const frozen = approved;
      const waitCover = locked && !approved;
      const generateDisabled = frozen || waitCover || slot.status === 'generating';
      const mode = slot.mode === 'upload' ? 'upload' : 'ai';
      const disableAiSwitch = frozen || (hasImage && mode === 'upload');
      const disableUploadSwitch = frozen || (hasImage && mode === 'ai');
      const statusLabel = approved ? 'معتمد' : slot.status === 'generating' ? 'قيد التوليد' : slot.status === 'review' ? 'مسودة - جاهزة للاعتماد' : 'مسودة';
      const chat = (slot.chat || []).map(item => (
        '<div class="visual-concept-chat-message"><strong>' + (item.role === 'assistant' ? trDynamicI18n('النظام:') + ' ' : trDynamicI18n('أنت:') + ' ') + '</strong>' + escapeHtml(item.text) + '</div>'
      )).join('') || '<div class="tenant-hint">' + trDynamicI18n('لا توجد تعديلات بعد.') + '</div>';
      const title = visualConceptSlotLabel(slotDef.id);
      const preview = image
        ? '<div class="visual-concept-preview has-image" data-visual-zoom="' + escapeHtml(image) + '" data-visual-title="' + escapeHtml(title) + '">' +
        '<img src="' + escapeHtml(image) + '" alt="' + escapeHtml(title) + '">' +
        '<button type="button" class="visual-concept-zoom-btn" data-visual-zoom="' + escapeHtml(image) + '" data-visual-title="' + escapeHtml(title) + '">تكبير</button>' +
        '</div>'
        : '<div class="visual-concept-preview empty">لم تُرفع أو تُولَّد هذه الصورة بعد.</div>';
      const uploadAccept = 'image/png,image/jpeg,image/jpg,image/webp';
      const heading = visualConceptCanRenameSlot(slotDef.id)
        ? '<input class="visual-concept-title-input" data-visual-title="' + slotDef.id + '" value="' + escapeHtml(title) + '" ' + (frozen ? 'disabled' : '') + '>'
        : '<h3>' + escapeHtml(title) + '</h3>';

      // Plans pick their mode by which tab they live in, not a per-card switch.
      const modeSelector = isVisualConceptPlanSlot(slotDef.id) ? '' : '<div class="visual-concept-mode-selector">' +
        '<button type="button" class="visual-concept-mode-btn' + (mode === 'ai' ? ' active' : '') + '" data-visual-action="set-mode" data-visual-mode="ai" data-visual-slot="' + slotDef.id + '" ' + (disableAiSwitch ? 'disabled title="احذف الصورة الحالية أولاً لتغيير النمط"' : '') + '>توليد بالذكاء الاصطناعي</button>' +
        '<button type="button" class="visual-concept-mode-btn' + (mode === 'upload' ? ' active' : '') + '" data-visual-action="set-mode" data-visual-mode="upload" data-visual-slot="' + slotDef.id + '" ' + (disableUploadSwitch ? 'disabled title="احذف الصورة الحالية أولاً لتغيير النمط"' : '') + '>رفع يدوي</button>' +
        '</div>';

      const deleteBtn = hasImage
        ? '<button type="button" class="btn danger small" data-visual-action="delete-image" data-visual-slot="' + slotDef.id + '" ' + (frozen ? 'disabled' : '') + '>حذف الصورة</button>'
        : '';
      const deleteFieldBtn = isVisualConceptInteriorSlot(slotDef.id)
        ? '<button type="button" class="btn danger small" data-visual-action="delete-interior-field" data-visual-slot="' + slotDef.id + '">حذف الحقل</button>'
        : (isVisualConceptPlanSlot(slotDef.id)
          ? '<button type="button" class="btn danger small" data-visual-action="delete-plan" data-visual-slot="' + slotDef.id + '">حذف المخطط</button>'
          : '');

      let bodyControls = '';
      if (mode === 'upload') {
        bodyControls = '<div class="visual-concept-upload-box">' +
          '<label class="visual-concept-upload-label">اختر ملف الصورة من جهازك</label>' +
          '<input type="file" accept="' + uploadAccept + '" data-visual-upload="' + slotDef.id + '" ' + (frozen ? 'disabled' : '') + '>' +
          (slot.sourceFileName ? '<div class="visual-concept-file-info">الملف الحالي: ' + escapeHtml(slot.sourceFileName) + '</div>' : '') +
          '</div>' +
          (isVisualConceptPlanSlot(slotDef.id) ? '<label>وصف المخطط</label>' : '<label>وصف الصورة</label>') +
          '<textarea data-visual-caption="' + slotDef.id + '" rows="3" ' + (frozen ? 'disabled' : '') + '>' + escapeHtml(slot.caption || '') + '</textarea>' +
          '<div class="visual-concept-actions">' +
          '<button type="button" class="btn ' + (approved ? 'ghost' : 'primary') + ' small" data-visual-action="' + (approved ? 'unapprove' : 'approve') + '" data-visual-slot="' + slotDef.id + '" ' + ((!image && !approved) ? 'disabled' : '') + '>' + (approved ? 'الغاء الاعتماد' : 'اعتماد') + '</button>' +
          deleteBtn + deleteFieldBtn +
          '</div>';
      } else {
        bodyControls = '<label>وصف التوليد</label>' +
          '<textarea class="visual-concept-prompt" data-visual-prompt="' + slotDef.id + '" ' + (frozen ? 'disabled' : '') + ' dir="ltr">' + escapeHtml(slot.prompt || '') + '</textarea>' +
          (isVisualConceptPlanSlot(slotDef.id)
            ? '<label>وصف المخطط</label><textarea data-visual-caption="' + slotDef.id + '" rows="2" ' + (frozen ? 'disabled' : '') + '>' + escapeHtml(slot.caption || '') + '</textarea>'
            : '') +
          '<div class="visual-concept-actions">' +
          '<button type="button" class="btn ghost small" data-visual-action="prompt" data-visual-slot="' + slotDef.id + '" ' + (generateDisabled ? 'disabled' : '') + '>إنشاء / إعادة توليد الوصف</button>' +
          '<button type="button" class="btn primary small" data-visual-action="generate" data-visual-slot="' + slotDef.id + '" ' + (generateDisabled ? 'disabled' : '') + '>توليد الصورة</button>' +
          '<button type="button" class="btn ' + (approved ? 'ghost' : 'primary') + ' small" data-visual-action="' + (approved ? 'unapprove' : 'approve') + '" data-visual-slot="' + slotDef.id + '" ' + ((!image && !approved) ? 'disabled' : '') + '>' + (approved ? 'الغاء الاعتماد' : 'اعتماد') + '</button>' +
          deleteBtn + deleteFieldBtn +
          '</div>' +
          '<div class="visual-concept-chat">' + chat + '</div>' +
          '<div class="visual-concept-chat-row">' +
          '<textarea data-visual-chat="' + slotDef.id + '" rows="2" ' + (generateDisabled ? 'disabled' : '') + '></textarea>' +
          '<button type="button" class="btn primary small" data-visual-action="chat" data-visual-slot="' + slotDef.id + '" ' + (generateDisabled ? 'disabled' : '') + '>إرسال التعديل</button>' +
          '</div>';
      }

      const lockHint = waitCover
        ? '<p class="tenant-hint">' + escapeHtml(visualConceptLockMessage(slotDef.id)) + '</p>'
        : '';
      return '<article class="visual-concept-card' + (waitCover ? ' locked' : '') + (approved ? ' section-locked' : '') + '" data-visual-slot="' + slotDef.id + '">' +
        '<div class="visual-concept-head">' + heading +
        '<span class="visual-concept-status ' + slot.status + '">' + statusLabel + '</span></div>' +
        modeSelector +
        preview +
        lockHint +
        bodyControls +
        '</article>';
    }

    function openVisualConceptLightbox(url, title) {
      if (!url) return;
      let modal = document.getElementById('visualConceptLightbox');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'visualConceptLightbox';
        modal.className = 'visual-concept-lightbox';
        modal.innerHTML = `
          <div class="visual-concept-lightbox-backdrop" data-visual-lightbox-close></div>
          <div class="visual-concept-lightbox-content">
            <div class="visual-concept-lightbox-header">
              <h3 id="visualConceptLightboxTitle">معاينة الصورة</h3>
              <button type="button" class="btn ghost small" data-visual-lightbox-close>إغلاق</button>
            </div>
            <div class="visual-concept-lightbox-body">
              <img id="visualConceptLightboxImg" src="" alt="معاينة مكبرة">
            </div>
          </div>
        `;
        document.body.appendChild(modal);
        modal.querySelectorAll('[data-visual-lightbox-close]').forEach(btn => {
          btn.addEventListener('click', closeVisualConceptLightbox);
        });
      }
      const img = modal.querySelector('#visualConceptLightboxImg');
      const titleEl = modal.querySelector('#visualConceptLightboxTitle');
      if (img) img.src = url;
      if (titleEl) titleEl.textContent = title || 'معاينة الصورة';
      modal.hidden = false;
    }

    function closeVisualConceptLightbox() {
      const modal = document.getElementById('visualConceptLightbox');
      if (modal) {
        modal.hidden = true;
        const img = modal.querySelector('#visualConceptLightboxImg');
        if (img) img.src = '';
      }
    }

    if (!window._visualConceptLightboxEscapeBound) {
      window._visualConceptLightboxEscapeBound = true;
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeVisualConceptLightbox();
      });
    }

    function visualConceptImageUrl(url) {
      const value = String(url || '');
      if (!value.startsWith('/uploads/')) return value;
      // The media route needs the expiring ?s= signature from the JSON response —
      // keep it and only append a cache-buster, or a fresh image 404s until reload.
      return value + (value.includes('?') ? '&' : '?') + 't=' + Date.now();
    }

    function renderVisualConceptStyleReference() {
      const preview = document.getElementById('visualConceptStyleReferencePreview');
      if (!preview) return;
      const ids = Array.isArray(tenantVisualConceptState?.styleReferenceFileIds)
        ? tenantVisualConceptState.styleReferenceFileIds : [];
      const names = Array.isArray(tenantVisualConceptState?.styleReferenceNames)
        ? tenantVisualConceptState.styleReferenceNames : [];
      if (!ids.length) {
        preview.textContent = 'لم تُرفع صور مرجعية.';
        return;
      }
      preview.innerHTML = '<div class="visual-concept-reference-list"></div>';
      const list = preview.firstElementChild;
      ids.forEach((fileId, index) => {
        const item = document.createElement('div');
        item.className = 'visual-concept-reference-item';
        item.innerHTML = '<img alt="صورة مرجعية ' + (index + 1) + '"><span>' + escapeHtml(names[index] || ('صورة مرجعية ' + (index + 1))) + '</span>';
        list.appendChild(item);
        attachProjectFileThumbnail(item.querySelector('img'), fileId);
      });
    }

    async function uploadVisualConceptStyleReference(input) {
      const files = Array.from(input?.files || []);
      if (!files.length) return;
      if (files.length > 5) toast('سيتم رفع أول 5 صور فقط.');
      try {
        input.dataset.projectFileType = 'visual_reference';
        const uploaded = await uploadTenantProjectFileInput(input, 'visual_style_reference');
        const incoming = (Array.isArray(uploaded) ? uploaded : [uploaded]).map((file, index) => ({
          id: file?.id || file,
          name: file?.originalName || files[index]?.name || ''
        })).filter(file => file.id);
        if (!incoming.length) throw new Error('تعذر رفع الصور المرجعية');
        tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
        const merged = [];
        const existingIds = tenantVisualConceptState.styleReferenceFileIds || [];
        const existingNames = tenantVisualConceptState.styleReferenceNames || [];
        existingIds.forEach((id, index) => merged.push({ id, name: existingNames[index] || '' }));
        incoming.forEach(file => {
          const found = merged.find(item => String(item.id) === String(file.id));
          if (found) found.name = found.name || file.name;
          else merged.push(file);
        });
        const limited = merged.slice(0, 5);
        tenantVisualConceptState.styleReferenceFileIds = limited.map(file => file.id);
        tenantVisualConceptState.styleReferenceNames = limited.map(file => file.name);
        tenantVisualConceptState.styleReferenceFileId = limited[0]?.id || '';
        tenantVisualConceptState.styleReferenceName = limited[0]?.name || '';
        markVisualConceptDirty();
        renderVisualConceptStyleReference();
        toast('تم حفظ ' + limited.length + ' صور مرجعية.');
      } catch (error) {
        toast(error.message || 'تعذر رفع الصور المرجعية');
      } finally {
        if (input) input.value = '';
      }
    }

    async function uploadVisualConceptInteriorReferences(input) {
      const files = Array.from(input?.files || []);
      if (!files.length) return;
      const componentId = selectedVisualConceptInteriorComponentId();
      if (!componentId) {
        toast('اختر مكونًا أولًا');
        return;
      }
      const remaining = Math.max(0, VISUAL_CONCEPT_MAX_INTERIOR_IMAGES - visualConceptInteriorViewIds(componentId).filter(id => {
        const slot = tenantVisualConceptState.slots[id] || {};
        return slot.imageUrl || slot.approvedImageUrl || slot.sourceFileId;
      }).length);
      if (!remaining) {
        toast('تم الوصول إلى الحد الأقصى لصور هذا المكون');
        input.value = '';
        return;
      }
      const slotId = visualConceptInteriorSlotId(componentId, 1);
      if (files.length > 4) toast('سيتم رفع أول 4 صور فقط.');
      try {
        input.dataset.projectFileType = 'visual_reference';
        const uploaded = await uploadTenantProjectFileInput(input, 'visual_style_reference');
        const incoming = (Array.isArray(uploaded) ? uploaded : [uploaded]).map((file, index) => ({
          id: file?.id || file,
          name: file?.originalName || files[index]?.name || ''
        })).filter(file => file.id);
        if (!incoming.length) throw new Error('تعذر رفع الصور المرجعية');
        tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
        if (!tenantVisualConceptState.slots[slotId]) tenantVisualConceptState.slots[slotId] = emptyVisualConceptSlot(slotId);
        const slot = tenantVisualConceptState.slots[slotId];
        const merged = [];
        (slot.styleReferenceFileIds || []).forEach((id, index) => merged.push({ id, name: (slot.styleReferenceNames || [])[index] || '' }));
        incoming.forEach(file => {
          const found = merged.find(item => String(item.id) === String(file.id));
          if (found) found.name = found.name || file.name;
          else merged.push(file);
        });
        const limited = merged.slice(0, 4);
        slot.styleReferenceFileIds = limited.map(file => file.id);
        slot.styleReferenceNames = limited.map(file => file.name);
        const revivedViewIds = [];
        for (let index = 0; index < limited.length; index += 1) {
          const file = limited[index];
          const viewId = visualConceptInteriorSlotId(componentId, index + 1);
          revivedViewIds.push(viewId);
          if (!tenantVisualConceptState.slots[viewId]) tenantVisualConceptState.slots[viewId] = emptyVisualConceptSlot(viewId);
          const viewSlot = tenantVisualConceptState.slots[viewId];
          if (!viewSlot.imageUrl && !viewSlot.approvedImageUrl) {
            viewSlot.sourceFileId = file.id;
            viewSlot.sourceFileName = file.name;
            viewSlot.imageUrl = await publishProjectFileImageUrl(file.id);
            viewSlot.status = viewSlot.status === 'approved' ? viewSlot.status : 'review';
          }
        }
        tenantVisualConceptState.deletedInteriorSlots = (tenantVisualConceptState.deletedInteriorSlots || [])
          .filter(id => !revivedViewIds.includes(id));
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast('تم حفظ صور هذا المكون.');
      } catch (error) {
        toast(error.message || 'تعذر رفع الصور المرجعية');
      } finally {
        if (input) input.value = '';
      }
    }

    function clearVisualConceptInteriorReferences() {
      const componentId = selectedVisualConceptInteriorComponentId();
      const slotId = visualConceptInteriorSlotId(componentId, 1);
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      if (!tenantVisualConceptState.slots[slotId]) return;
      tenantVisualConceptState.slots[slotId].styleReferenceFileIds = [];
      tenantVisualConceptState.slots[slotId].styleReferenceNames = [];
      markVisualConceptDirty();
      renderVisualConceptInteriorReferences(slotId);
      toast('تم حذف صور هذا المكون.');
    }

    function clearVisualConceptStyleReference() {
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      tenantVisualConceptState.styleReferenceFileIds = [];
      tenantVisualConceptState.styleReferenceFileId = '';
      tenantVisualConceptState.styleReferenceNames = [];
      tenantVisualConceptState.styleReferenceName = '';
      markVisualConceptDirty();
      renderVisualConceptStyleReference();
      toast('تم حذف الصور المرجعية. سيولد النظام التصميم من البيانات والخريطة فقط.');
    }

    function visualConceptPlans() {
      if (!Array.isArray(tenantVisualConceptState?.plans2d)) {
        if (tenantVisualConceptState) tenantVisualConceptState.plans2d = [];
        else return [];
      }
      return tenantVisualConceptState.plans2d;
    }

    function visualConceptPlanMode(plan) {
      const slot = tenantVisualConceptState?.slots?.[plan?.id];
      const mode = slot ? slot.mode : plan?.mode;
      return mode === 'upload' ? 'upload' : 'generate';
    }

    function setVisualConceptPlansTab(tab) {
      const active = tab === 'upload' ? 'upload' : 'generate';
      document.querySelectorAll('[data-visual-plans-tab]').forEach(button => {
        button.classList.toggle('active', button.getAttribute('data-visual-plans-tab') === active);
      });
      document.querySelectorAll('[data-visual-plans-panel]').forEach(panel => {
        panel.hidden = panel.getAttribute('data-visual-plans-panel') !== active;
      });
    }

    function renderVisualConceptBoundarySvg(host, points) {
      if (!host) return;
      const rows = visualConceptBoundaryPoints(points);
      if (rows.length < 3) {
        host.innerHTML = '<p class="tenant-hint">لا توجد نقاط حدود مكتملة.</p>';
        return;
      }
      const xs = rows.map(item => item.eastings);
      const ys = rows.map(item => item.northings);
      const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      const span = Math.max(maxX - minX, maxY - minY) || 1;
      const pad = 100;
      const toPoint = item => {
        const x = pad + ((item.eastings - minX) / span) * (1000 - pad * 2) + ((1000 - pad * 2) - ((maxX - minX) / span) * (1000 - pad * 2)) / 2;
        const y = 700 - (pad + ((item.northings - minY) / span) * (700 - pad * 2) + ((700 - pad * 2) - ((maxY - minY) / span) * (700 - pad * 2)) / 2);
        return [Math.round(x), Math.round(y)];
      };
      const polygon = rows.map(toPoint).map(point => point.join(',')).join(' ');
      const circles = rows.map((item, index) => {
        const [x, y] = toPoint(item);
        return '<circle cx="' + x + '" cy="' + y + '" r="9" fill="#172b4d"><title>' + escapeHtml(item.point || String(index + 1)) + '</title></circle>';
      }).join('');
      host.innerHTML = '<svg viewBox="0 0 1000 700" role="img" aria-label="حدود الأرض" class="plans-boundary-svg">' +
        '<polygon points="' + polygon + '" fill="#e8f0e8" stroke="#172b4d" stroke-width="7"></polygon>' +
        circles +
        '<line x1="90" y1="155" x2="90" y2="70" stroke="#172b4d" stroke-width="7"></line>' +
        '<polygon points="90,50 76,78 104,78" fill="#172b4d"></polygon>' +
        '<text x="82" y="185" fill="#172b4d" font-size="24">N</text>' +
        '</svg>';
    }

    function visualConceptDistributionTotalsRowsHtml(distribution) {
      const totals = Array.isArray(distribution.totals) ? distribution.totals : [];
      if (!totals.length) return '';
      const fmt = value => (value === null || value === undefined || value === '') ? '—'
        : (typeof value === 'number' ? String(Math.round(value * 100) / 100) : String(value));
      const rowsHtml = totals.map(item => {
        const deltas = [];
        if (typeof item.delta_units === 'number' && item.delta_units) deltas.push('وحدات ' + (item.delta_units > 0 ? '+' : '') + item.delta_units);
        if (typeof item.delta_area === 'number' && item.delta_area) deltas.push('م² ' + (item.delta_area > 0 ? '+' : '') + item.delta_area);
        const hasRequired = typeof item.required_units === 'number' || typeof item.required_area === 'number';
        const deltaText = deltas.length ? deltas.join('، ') : (hasRequired ? 'مطابق للدراسة' : '—');
        const impact = deltas.length ? '<div class="plans-conflict-location">يؤثر في الدراسة المالية</div>' : '';
        return '<tr class="plans-distribution-total"><td colspan="3">' + escapeHtml(item.component || '') + '</td>' +
          '<td>' + escapeHtml(fmt(item.units)) + ' / ' + escapeHtml(fmt(item.required_units)) + '</td>' +
          '<td>' + escapeHtml(fmt(item.area)) + ' / ' + escapeHtml(fmt(item.required_area)) + '</td>' +
          '<td colspan="2">' + escapeHtml(deltaText) + impact + '</td></tr>';
      }).join('');
      return '<tr class="plans-distribution-total-head"><td colspan="3">إجمالي المكونات</td>' +
        '<td>الوحدات توزيع/دراسة</td><td>المساحة توزيع/دراسة</td><td colspan="2">الفرق</td></tr>' + rowsHtml;
    }

    function visualConceptDistributionEditorHtml(distribution) {
      const rows = Array.isArray(distribution.rows) ? distribution.rows : [];
      const head = '<thead><tr><th>المبنى</th><th>الدور أو نطاق الأدوار</th><th>الاستخدام / المكون</th>' +
        '<th>عدد الوحدات لكل دور</th><th>مساحة الدور الإجمالية</th><th>الحركة والخدمات ضمن المساحة</th><th></th></tr></thead>';
      const body = rows.length ? rows.map(row =>
        '<tr>' +
        '<td><input data-dist-field="building" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.building) + '"></td>' +
        '<td><input data-dist-field="floor_range" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.floor_range) + '" placeholder="1-4"></td>' +
        '<td><input data-dist-field="component" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.component) + '"></td>' +
        '<td><input data-dist-field="units_per_floor" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.units_per_floor ?? '') + '"></td>' +
        '<td><input data-dist-field="floor_area_sqm" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.floor_area_sqm ?? '') + '"></td>' +
        '<td><input data-dist-field="circulation" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.circulation) + '"></td>' +
        '<td><button type="button" class="btn ghost small" data-dist-remove="' + escapeHtml(row.id) + '">حذف</button></td>' +
        '</tr>').join('')
        : '<tr><td colspan="7" class="plans-workflow-empty">لم يُقترح توزيع بعد.</td></tr>';
      return '<div class="plans-workflow-table-wrap"><table class="plans-workflow-table plans-distribution-table">' +
        head + '<tbody>' + body + '</tbody>' +
        '<tfoot data-plans-distribution-totals>' + visualConceptDistributionTotalsRowsHtml(distribution) + '</tfoot>' +
        '</table></div>' +
        '<div class="visual-concept-actions"><button type="button" class="btn ghost small" data-plans-workflow-action="add-distribution-row">إضافة صف</button></div>';
    }

    function visualConceptDistributionResultsHtml(distribution) {
      const rows = Array.isArray(distribution.rows) ? distribution.rows : [];
      const checks = Array.isArray(distribution.checks) ? distribution.checks : [];
      const issues = Array.isArray(distribution.issues) ? distribution.issues : [];
      const findings = checks.map(item =>
          (item.result && item.result !== 'مطابق' ? item.result + ': ' : '') + (item.detail || item.item || ''))
        .concat(issues.flatMap(item =>
          (Array.isArray(item.points) && item.points.length ? item.points : [item.title || ''])))
        .filter(Boolean);
      const findingsHtml = findings.length
        ? '<div class="plans-workflow-notice"><ul class="plans-issue-list">' +
          findings.map(point => '<li>' + escapeHtml(point) + '</li>').join('') + '</ul></div>'
        : (rows.length ? '<p class="plans-workflow-success">لا توجد تعارضات في التوزيع.</p>' : '');
      const canApprove = rows.length > 0 && !visualConceptDistributionBlocking(distribution).length;
      return findingsHtml +
        '<div class="visual-concept-actions">' +
        '<button type="button" class="btn ghost small" data-plans-workflow-action="check-distribution" ' + (rows.length ? '' : 'disabled') + '>فحص التعارضات</button>' +
        '<button type="button" class="btn ghost small" data-plans-workflow-action="repair-distribution" ' + (findings.length ? '' : 'disabled') + '>إصلاح التعارضات بالذكاء الاصطناعي</button>' +
        '<button type="button" class="btn primary small" data-plans-workflow-action="approve-distribution" ' + (canApprove ? '' : 'disabled') + '>اعتماد التوزيع</button>' +
        (distribution.approved ? '<span class="plans-workflow-success">التوزيع معتمد</span>' : '') +
        '</div>';
    }

    function visualConceptDistributionBlocking(distribution) {
      const checks = Array.isArray(distribution.checks) ? distribution.checks : [];
      const issues = Array.isArray(distribution.issues) ? distribution.issues : [];
      return checks.filter(item => item.result === 'متعارض' || item.severity === 'high')
        .concat(issues.filter(item => item.severity === 'high'));
    }

    function renderVisualConceptPlansWorkflow() {
      const root = document.getElementById('visualConceptPlansWorkflow');
      if (!root) return;
      const workflow = visualConceptPlansWorkflowState();
      const verification = workflow.verification || {};
      const boundary = workflow.boundary || {};
      const distribution = workflow.distribution || {};
      const verified = Boolean(verification.approved);
      const boundaryApproved = Boolean(boundary.approved);
      const distApproved = Boolean(distribution.approved);
      const promptReady = Boolean(workflow.promptReady);
      const defaultStage = !verified ? 'verify' : ((boundaryApproved && distApproved) ? 'generate' : 'boundary');
      const requestedStage = ['verify', 'boundary', 'generate'].includes(workflow.viewStage) ? workflow.viewStage : defaultStage;
      const activeStage = requestedStage === 'generate' && !(boundaryApproved && distApproved)
        ? (verified ? 'boundary' : 'verify')
        : (requestedStage === 'boundary' && !verified ? 'verify' : requestedStage);
      const checks = Array.isArray(verification.checks) ? verification.checks : [];
      const conflicts = checks.filter(item => item.result === 'متعارض');
      const canApprove = !conflicts.length && (checks.length > 0 || verification.canProceed);
      const checkRows = conflicts.length ? conflicts.map(item =>
        '<tr><td>' + escapeHtml(item.item || '') +
        ((item.section || item.field) ? '<div class="plans-conflict-location">' + escapeHtml(item.section || '') + (item.field ? ' — ' + escapeHtml(item.field) : '') + '</div>' : '') +
        '</td><td>' + escapeHtml(item.project || '') + '</td><td>' + escapeHtml(item.regulatory || '') + '</td><td><span class="plans-check-result plans-check-' + escapeHtml(item.result || '') + '">' + escapeHtml(item.result || '') + '</span></td><td>' +
        (Array.isArray(item.issues) && item.issues.length ? '<ul class="plans-issue-list">' + item.issues.map(issue => '<li>' + escapeHtml(issue) + '</li>').join('') + '</ul>' : '') +
        (item.suggestion ? '<div class="plans-conflict-solution"><strong>' + escapeHtml(WFT('plans.proposed_solution', 'الحل المقترح:')) + '</strong> ' + escapeHtml(item.suggestion) + '</div>' : '') +
        escapeHtml(item.action || '') + '</td></tr>'
      ).join('') : '<tr><td colspan="5" class="plans-workflow-empty plans-workflow-success">' + escapeHtml(WFT('plans.no_conflicts', 'لا توجد تعارضات مباشرة.')) + '</td></tr>';
      const conflictPoints = conflicts.flatMap(item => Array.isArray(item.issues) ? item.issues : []).filter(Boolean);
      const issueList = conflictPoints.length
        ? '<ul class="plans-issue-list plans-issue-summary">' + conflictPoints.map(point => '<li>' + escapeHtml(point) + '</li>').join('') + '</ul>'
        : '';
      const promptCards = promptReady
        ? '<div class="visual-concept-stack">' + VISUAL_CONCEPT_PLAN_KINDS.map(definition =>
          renderVisualConceptSlot({ id: definition.id, label: definition.label, group: 'plans' }, visualConceptSlotLocked(definition.id))
        ).join('') + '</div>'
        : '<p class="tenant-hint">لم تُجهز برومبتات المخططات بعد.</p>';
      root.innerHTML =
        '<div class="plans-workflow-card">' +
        '<ol class="plans-workflow-steps">' +
        '<li class="' + (activeStage === 'verify' ? 'is-active' : (verified ? 'is-complete' : '')) + '"><button type="button" data-plans-workflow-tab="verify">التحقق من التضارب</button></li>' +
        '<li class="' + (activeStage === 'boundary' ? 'is-active' : (boundaryApproved && distApproved ? 'is-complete' : '')) + '"><button type="button" data-plans-workflow-tab="boundary" ' + (!verified ? 'disabled' : '') + '>رسم الحدود وتوزيع المكونات</button></li>' +
        '<li class="' + (activeStage === 'generate' ? 'is-active' : '') + '"><button type="button" data-plans-workflow-tab="generate" ' + (!(boundaryApproved && distApproved) ? 'disabled' : '') + '>توليد المخططات</button></li>' +
        '</ol>' +
        '<section class="plans-workflow-panel" data-plans-workflow-stage="verify"' + (activeStage !== 'verify' ? ' hidden' : '') + '>' +
        '<div class="plans-workflow-panel-head"><h4>التحقق من التضارب</h4><button type="button" class="btn primary small" data-plans-workflow-action="verify">تحقق</button></div>' +
        '<p class="' + (conflicts.length ? 'tenant-hint' : 'plans-workflow-success') + '" data-plans-verification-summary>' + escapeHtml(conflicts.length ? WFT('plans.conflicts_count', 'عدد التعارضات المباشرة: ') + conflicts.length : WFT('plans.no_conflicts', 'لا توجد تعارضات مباشرة.')) + '</p>' +
        (issueList ? '<div class="plans-workflow-notice">' + issueList + '</div>' : '') +
        '<div class="plans-workflow-table-wrap"><table class="plans-workflow-table plans-check-table"><thead><tr><th>البند</th><th>بيانات المشروع</th><th>البيانات الموثقة</th><th>النتيجة</th><th>المشاكل والإجراء</th></tr></thead><tbody>' + checkRows + '</tbody></table></div>' +
        '<div class="visual-concept-actions"><button type="button" class="btn primary small" data-plans-workflow-action="approve-verification" ' + (!canApprove ? 'disabled' : '') + '>اعتماد نتيجة التحقق</button></div>' +
        '</section>' +
        '<section class="plans-workflow-panel" data-plans-workflow-stage="boundary"' + (activeStage !== 'boundary' ? ' hidden' : '') + '>' +
        '<div class="plans-workflow-panel-head"><h4>رسم حدود الأرض</h4><div class="visual-concept-actions"><button type="button" class="btn ghost small" data-plans-workflow-action="open-land-data">مراجعة بيانات الأرض والكروكي</button><button type="button" class="btn ghost small" data-plans-workflow-action="refresh-boundary">تحديث الرسم</button></div></div>' +
        '<div class="plans-boundary-editor"><div class="plans-boundary-preview" data-plans-boundary-preview></div><div class="plans-boundary-meta"><p class="tenant-hint">حدود الرسم مأخوذة من جدول الإحداثيات المعتمد في الأرض والكروكي.</p></div></div>' +
        '<div class="visual-concept-actions"><button type="button" class="btn ghost small" data-plans-workflow-action="boundary-ai">تعديل الحدود بالذكاء الاصطناعي</button><button type="button" class="btn primary small" data-plans-workflow-action="approve-boundary" ' + (boundary.points.length < 3 || !boundary.referenceUrl ? 'disabled' : '') + '>اعتماد حدود الأرض</button></div>' +
        '<label>ملاحظات تعديل الحدود</label><textarea rows="3" data-plans-boundary-instruction>' + escapeHtml(boundary.instruction || '') + '</textarea>' +
        '<div class="plans-workflow-panel-head"><h4>توزيع المكونات على الأدوار</h4><button type="button" class="btn primary small" data-plans-workflow-action="propose-distribution">اقتراح التوزيع</button></div>' +
        '<div data-plans-distribution-editor>' + visualConceptDistributionEditorHtml(distribution) + '</div>' +
        '<div data-plans-distribution-results>' + visualConceptDistributionResultsHtml(distribution) + '</div>' +
        '</section>' +
        '<section class="plans-workflow-panel" data-plans-workflow-stage="generate"' + (activeStage !== 'generate' ? ' hidden' : '') + '>' +
        '<div class="plans-workflow-panel-head"><h4>توليد المخططات</h4><button type="button" class="btn primary small" data-plans-workflow-action="prepare-prompts">إعداد برومبتات المخططات</button></div>' +
        '<p class="tenant-hint">' + escapeHtml(promptReady ? 'البرومبتات جاهزة للتعديل والتوليد.' : (workflow.promptsError ? 'تعذر إعداد برومبتات المخططات: ' + workflow.promptsError : 'برومبتات المخططات الثلاثة غير جاهزة.')) + '</p>' +
        '<div data-plans-workflow-prompts>' + promptCards + '</div>' +
        '</section></div>';
      const preview = root.querySelector('[data-plans-boundary-preview]');
      renderVisualConceptBoundarySvg(preview, boundary.points);
      // Delegated binding, once: the distribution results container is re-rendered
      // in place after every re-check, so per-button listeners would die with it.
      if (!root.dataset.plansWorkflowBound) {
        root.dataset.plansWorkflowBound = 'true';
        root.addEventListener('click', event => {
          const tab = event.target.closest('[data-plans-workflow-tab]');
          if (tab && !tab.disabled) {
            const stage = tab.getAttribute('data-plans-workflow-tab');
            const state = visualConceptPlansWorkflowState();
            if (stage === 'boundary' && !state.verification.approved) return;
            if (stage === 'generate' && !(state.boundary.approved && state.distribution.approved)) return;
            state.viewStage = stage;
            persistVisualConceptDraftState();
            renderVisualConceptPage();
            return;
          }
          const removeBtn = event.target.closest('[data-dist-remove]');
          if (removeBtn) {
            const state = visualConceptPlansWorkflowState();
            const id = removeBtn.getAttribute('data-dist-remove');
            state.distribution.rows = (state.distribution.rows || []).filter(item => item.id !== id);
            state.distribution.approved = false;
            state.promptReady = false;
            markVisualConceptDirty();
            renderVisualConceptPage();
            scheduleVisualConceptDistributionCheck();
            return;
          }
          const actionBtn = event.target.closest('[data-plans-workflow-action]');
          if (!actionBtn || actionBtn.disabled) return;
          const action = actionBtn.getAttribute('data-plans-workflow-action');
          const state = visualConceptPlansWorkflowState();
          if (action === 'open-land-data') {
            state.verification.approved = false;
            state.boundary.approved = false;
            state.distribution.approved = false;
            state.promptReady = false;
            state.promptsError = '';
            state.viewStage = 'verify';
            state.status = 'idle';
            markVisualConceptDirty();
            if (typeof showSection === 'function') showSection('land_croquis');
          } else if (action === 'verify') verifyVisualConceptPlans();
          else if (action === 'approve-verification') approveVisualConceptPlansVerification();
          else if (action === 'refresh-boundary') refreshVisualConceptPlansBoundary();
          else if (action === 'boundary-ai') reviseVisualConceptPlansBoundaryWithAi();
          else if (action === 'approve-boundary') approveVisualConceptPlansBoundary();
          else if (action === 'propose-distribution') proposeVisualConceptPlansDistribution();
          else if (action === 'check-distribution') checkVisualConceptPlansDistribution('ai');
          else if (action === 'repair-distribution') repairVisualConceptPlansDistribution();
          else if (action === 'add-distribution-row') addVisualConceptDistributionRow();
          else if (action === 'approve-distribution') approveVisualConceptPlansDistribution();
          else if (action === 'prepare-prompts') prepareVisualConceptPlansPrompts();
        });
        root.addEventListener('change', event => {
          const input = event.target.closest('[data-dist-field]');
          if (!input) return;
          const state = visualConceptPlansWorkflowState();
          const id = input.getAttribute('data-dist-id');
          const field = input.getAttribute('data-dist-field');
          const row = (state.distribution.rows || []).find(item => item.id === id);
          if (!row) return;
          row[field] = input.value;
          state.distribution.approved = false;
          state.promptReady = false;
          state.promptsError = '';
          markVisualConceptDirty();
          scheduleVisualConceptDistributionCheck();
        });
      }
    }

    function renderVisualConceptPlans() {
      renderVisualConceptPlansWorkflow();
      const uploadHost = document.getElementById('visualConceptPlansUploadList');
      const count = document.getElementById('visualConceptPlansCount');
      const input = document.getElementById('visualConceptPlansUploadInput');
      const plans = visualConceptPlans().filter(plan => !isVisualConceptWorkflowPlan(plan.id));
      if (count) count.textContent = plans.length ? plans.length + ' مخطط مرفوع' : 'لا توجد مخططات مرفوعة.';
      if (input) input.disabled = plans.length >= VISUAL_CONCEPT_MAX_PLANS;
      if (!uploadHost) return;
      plans.forEach(plan => {
        if (!tenantVisualConceptState.slots[plan.id]) tenantVisualConceptState.slots[plan.id] = visualConceptPlanSeed(plan) || emptyVisualConceptSlot(plan.id);
      });
      uploadHost.innerHTML = plans.length
        ? '<div class="visual-concept-stack">' + plans.map(plan => renderVisualConceptSlot({ id: plan.id, label: plan.title || 'مخطط', group: 'plans' }, false)).join('') + '</div>'
        : '<p class="tenant-hint">لا توجد مخططات مرفوعة.</p>';
    }

    async function collectVisualConceptPlansWorkflowPayload() {
      const payload = await collectVisualConceptPayload('plan_site');
      payload.plansWorkflow = normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow);
      // The plans endpoints read plansWorkflow and the project facts only, so the
      // visual_concept state mirror is dead weight here — and oversized bodies are
      // what the hosting edge corrupts, so the request drops it (clone: projectData
      // is tenantProjectData, which must keep its own copy).
      payload.projectData = { ...payload.projectData };
      delete payload.projectData.visual_concept;
      return payload;
    }

    async function verifyVisualConceptPlans() {
      if (!hasPermission('generate_images')) { toast(WFT('plans.permission', 'لا تملك صلاحية توليد المخططات')); return; }
      showLoader(WFT('plans.verify_loading', 'جاري التحقق من التضارب'), WFT('plans.verify_loading_detail', 'يتم فحص بيانات المشروع والبيانات التنظيمية الموثقة...'), 18);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const response = await api('POST', '/api/visual-concept/plans-verify', payload);
        hideLoader();
        if (!response?.success) { toast(response?.error || WFT('plans.verify_failed', 'تعذر التحقق من التضارب')); return; }
        const workflow = visualConceptPlansWorkflowState();
        workflow.verification = normalizeVisualConceptPlansWorkflow({ verification: response.verification }).verification;
        workflow.planContext = response.planContext || workflow.planContext || null;
        workflow.status = 'verified';
        workflow.viewStage = 'verify';
        workflow.boundary.approved = false;
        workflow.distribution.approved = false;
        workflow.promptReady = false;
        workflow.promptsError = '';
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.verify_failed', 'تعذر التحقق من التضارب'));
      }
    }

    function approveVisualConceptPlansVerification() {
      const workflow = visualConceptPlansWorkflowState();
      const checks = Array.isArray(workflow.verification.checks) ? workflow.verification.checks : [];
      const conflicts = checks.filter(item => item.result === 'متعارض');
      if (conflicts.length || (!checks.length && !workflow.verification.canProceed)) return;
      workflow.verification.approved = true;
      workflow.status = 'verified';
      workflow.viewStage = 'boundary';
      if (!workflow.boundary.points.length) workflow.boundary.points = visualConceptBoundaryPoints(tenantProjectData.survey_coordinates);
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    async function refreshVisualConceptPlansBoundary() {
      const payload = await collectVisualConceptPlansWorkflowPayload();
      const seedWorkflow = visualConceptPlansWorkflowState();
      const sourcePoints = visualConceptBoundaryPoints(payload.projectData?.survey_coordinates);
      if (sourcePoints.length >= 3) seedWorkflow.boundary.points = sourcePoints;
      payload.points = seedWorkflow.boundary.points;
      payload.mode = 'manual';
      showLoader(WFT('plans.boundary_loading', 'جاري تجهيز رسم حدود الأرض'), WFT('plans.boundary_loading_detail', 'يتم بناء الرسم من الإحداثيات المحفوظة...'), 35);
      try {
        const response = await api('POST', '/api/visual-concept/plans-boundary', payload);
        hideLoader();
        if (!response?.success) { toast(response?.error || WFT('plans.boundary_failed', 'تعذر تجهيز رسم الحدود')); return; }
        const workflow = visualConceptPlansWorkflowState();
        workflow.boundary.points = visualConceptBoundaryPoints(response.points);
        workflow.boundary.referenceUrl = response.referenceUrl || '';
        workflow.boundary.approved = false;
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.boundary_failed', 'تعذر تجهيز رسم الحدود'));
      }
    }

    async function reviseVisualConceptPlansBoundaryWithAi() {
      const instruction = String(document.querySelector('[data-plans-boundary-instruction]')?.value || '').trim();
      if (!instruction) { toast(WFT('plans.boundary_instruction_required', 'طلب تعديل الحدود مطلوب')); return; }
      const savedInstruction = instruction.slice(0, 2000);
      const payload = await collectVisualConceptPlansWorkflowPayload();
      const seedWorkflow = visualConceptPlansWorkflowState();
      seedWorkflow.boundary.instruction = savedInstruction;
      payload.points = seedWorkflow.boundary.points;
      payload.instruction = savedInstruction;
      payload.mode = 'ai';
      showLoader(WFT('plans.boundary_ai_loading', 'جاري تعديل حدود الأرض'), WFT('plans.boundary_ai_loading_detail', 'يتم مراجعة التعديل على الإحداثيات...'), 35);
      try {
        const response = await api('POST', '/api/visual-concept/plans-boundary', payload);
        hideLoader();
        if (!response?.success) { toast(response?.error || WFT('plans.boundary_failed', 'تعذر تعديل رسم الحدود')); return; }
        const workflow = visualConceptPlansWorkflowState();
        workflow.boundary.points = visualConceptBoundaryPoints(response.points);
        workflow.boundary.referenceUrl = response.referenceUrl || workflow.boundary.referenceUrl;
        workflow.boundary.instruction = savedInstruction;
        workflow.boundary.approved = false;
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.boundary_failed', 'تعذر تعديل رسم الحدود'));
      }
    }

    function approveVisualConceptPlansBoundary() {
      const workflow = visualConceptPlansWorkflowState();
      if (workflow.boundary.points.length < 3 || !workflow.boundary.referenceUrl) return;
      workflow.boundary.approved = true;
      workflow.status = 'boundary';
      workflow.viewStage = workflow.distribution.approved ? 'generate' : 'boundary';
      workflow.promptReady = false;
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    let visualConceptDistCheckTimer = null;

    function scheduleVisualConceptDistributionCheck() {
      if (visualConceptDistCheckTimer) clearTimeout(visualConceptDistCheckTimer);
      visualConceptDistCheckTimer = setTimeout(() => {
        visualConceptDistCheckTimer = null;
        checkVisualConceptPlansDistribution('local', { silent: true });
      }, 700);
    }

    function addVisualConceptDistributionRow() {
      const workflow = visualConceptPlansWorkflowState();
      workflow.distribution.rows.push({
        id: 'row_' + Date.now().toString(36),
        building: '', floor_range: '', component: '',
        units_per_floor: '', floor_area_sqm: '', circulation: ''
      });
      workflow.distribution.approved = false;
      workflow.promptReady = false;
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    async function proposeVisualConceptPlansDistribution() {
      if (!hasPermission('generate_images')) { toast(WFT('plans.permission', 'لا تملك صلاحية توليد المخططات')); return; }
      showLoader(WFT('plans.distribution_loading', 'جاري اقتراح التوزيع'),
        WFT('plans.distribution_loading_detail', 'يتم توزيع المكونات على المباني والأدوار...'), 30);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const response = await api('POST', '/api/visual-concept/plans-distribution', payload);
        hideLoader();
        if (!response?.success) { toast(response?.error || WFT('plans.distribution_failed', 'تعذر اقتراح التوزيع')); return; }
        const workflow = visualConceptPlansWorkflowState();
        workflow.distribution = normalizeVisualConceptPlansWorkflow({ distribution: response.distribution }).distribution;
        workflow.planContext = response.planContext || workflow.planContext || null;
        workflow.promptReady = false;
        workflow.promptsError = '';
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.distribution_failed', 'تعذر اقتراح التوزيع'));
      }
    }

    async function checkVisualConceptPlansDistribution(mode, options) {
      const silent = Boolean(options && options.silent);
      const workflow = visualConceptPlansWorkflowState();
      if (!workflow.verification.approved || !(workflow.distribution.rows || []).length) return;
      if (!silent) showLoader(WFT('plans.distribution_check_loading', 'جاري فحص التوزيع'),
        WFT('plans.distribution_check_loading_detail', 'يتم مراجعة المساحات والقيود...'), 35);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        payload.mode = mode || 'local';
        payload.distribution = { rows: workflow.distribution.rows };
        const response = await api('POST', '/api/visual-concept/plans-distribution-check', payload);
        if (!silent) hideLoader();
        if (!response?.success) {
          if (!silent) toast(response?.error || WFT('plans.distribution_check_failed', 'تعذر فحص التوزيع'));
          return;
        }
        workflow.distribution.totals = Array.isArray(response.totals) ? response.totals : [];
        workflow.distribution.checks = Array.isArray(response.checks) ? response.checks : [];
        if (Array.isArray(response.issues)) workflow.distribution.issues = response.issues;
        markVisualConceptDirty();
        const totalsHost = document.querySelector('[data-plans-distribution-totals]');
        if (totalsHost) totalsHost.innerHTML = visualConceptDistributionTotalsRowsHtml(workflow.distribution);
        const host = document.querySelector('[data-plans-distribution-results]');
        if (host) host.innerHTML = visualConceptDistributionResultsHtml(workflow.distribution);
        else renderVisualConceptPage();
      } catch (error) {
        if (silent) return;
        hideLoader();
        toast(error.message || WFT('plans.distribution_check_failed', 'تعذر فحص التوزيع'));
      }
    }

    async function repairVisualConceptPlansDistribution() {
      if (!hasPermission('generate_images')) { toast(WFT('plans.permission', 'لا تملك صلاحية توليد المخططات')); return; }
      const workflow = visualConceptPlansWorkflowState();
      if (!(workflow.distribution.rows || []).length) return;
      showLoader(WFT('plans.distribution_repair_loading', 'جاري إصلاح التوزيع'),
        WFT('plans.distribution_repair_loading_detail', 'يعالج الذكاء الصفوف المتعارضة ويحدّث المجاميع...'), 40);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        payload.distribution = { rows: workflow.distribution.rows, issues: workflow.distribution.issues };
        const response = await api('POST', '/api/visual-concept/plans-distribution-repair', payload);
        hideLoader();
        if (!response?.success) { toast(response?.error || WFT('plans.distribution_repair_failed', 'تعذر إصلاح التوزيع')); return; }
        if (response.repaired === false) toast(WFT('plans.distribution_nothing_to_repair', 'لا توجد ملاحظات تستدعي الإصلاح'));
        workflow.distribution = normalizeVisualConceptPlansWorkflow({ distribution: response.distribution }).distribution;
        workflow.promptReady = false;
        workflow.promptsError = '';
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.distribution_repair_failed', 'تعذر إصلاح التوزيع'));
      }
    }

    function approveVisualConceptPlansDistribution() {
      const workflow = visualConceptPlansWorkflowState();
      const rows = workflow.distribution.rows || [];
      if (!rows.length) return;
      if (visualConceptDistributionBlocking(workflow.distribution).length) return;
      workflow.distribution.approved = true;
      workflow.promptReady = false;
      workflow.promptsError = '';
      workflow.viewStage = workflow.boundary.approved ? 'generate' : 'boundary';
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    let visualConceptPlansPromptsPending = false;

    async function prepareVisualConceptPlansPrompts() {
      const initialWorkflow = visualConceptPlansWorkflowState();
      if (!initialWorkflow.verification.approved || !initialWorkflow.boundary.approved || !initialWorkflow.distribution.approved) return;
      if (visualConceptPlansPromptsPending) return;
      visualConceptPlansPromptsPending = true;
      initialWorkflow.promptsError = '';
      showLoader(WFT('plans.prompts_loading', 'جاري إعداد برومبتات المخططات'), WFT('plans.prompts_loading_detail', 'يتم بناء البرومبتات من البيانات المعتمدة وحدود الأرض...'), 50);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const response = await api('POST', '/api/visual-concept/plans-prompts', payload);
        hideLoader();
        const workflow = visualConceptPlansWorkflowState();
        if (!response?.success || !response.prompts) {
          workflow.promptsError = String(response?.error || WFT('plans.prompts_failed', 'تعذر إعداد برومبتات المخططات'));
          markVisualConceptDirty();
          renderVisualConceptPage();
          toast(workflow.promptsError);
          return;
        }
        workflow.prompts = { ...workflow.prompts, ...response.prompts };
        workflow.promptReady = VISUAL_CONCEPT_PLAN_KINDS.every(item => Boolean(workflow.prompts[item.kind]));
        workflow.promptsError = workflow.promptReady ? '' : WFT('plans.prompts_incomplete', 'برومبتات المخططات الثلاثة غير مكتملة');
        workflow.status = workflow.promptReady ? 'ready' : 'boundary';
        VISUAL_CONCEPT_PLAN_KINDS.forEach(definition => {
          const slot = tenantVisualConceptState.slots[definition.id] || (tenantVisualConceptState.slots[definition.id] = emptyVisualConceptSlot(definition.id));
          slot.label = definition.label;
          slot.prompt = workflow.prompts[definition.kind] || slot.prompt;
          slot.caption = definition.label;
          slot.status = slot.imageUrl ? 'review' : 'pending';
        });
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        const workflow = visualConceptPlansWorkflowState();
        workflow.promptsError = String(error.message || WFT('plans.prompts_failed', 'تعذر إعداد برومبتات المخططات'));
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast(workflow.promptsError);
      } finally {
        visualConceptPlansPromptsPending = false;
      }
    }

    function addVisualConceptPlan() {
      if (visualConceptPlans().length >= VISUAL_CONCEPT_MAX_PLANS) {
        toast('تم الوصول إلى الحد الأقصى للمخططات');
        return;
      }
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      const id = 'plan_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
      visualConceptPlans().push({ id, mode: 'ai', title: '', description: '', fileId: '', fileName: '', imageUrl: '' });
      tenantVisualConceptState.slots[id] = emptyVisualConceptSlot(id);
      markVisualConceptDirty();
      setVisualConceptPlansTab('generate');
      renderVisualConceptPage();
    }

    async function uploadVisualConceptPlanImages(input) {
      const files = Array.from(input?.files || []);
      if (!files.length) return;
      const plans = visualConceptPlans();
      const uploadedPlans = plans.filter(plan => !isVisualConceptWorkflowPlan(plan.id));
      const remaining = Math.max(0, VISUAL_CONCEPT_MAX_PLANS - uploadedPlans.length);
      if (!remaining) {
        toast('تم الوصول إلى الحد الأقصى للمخططات');
        input.value = '';
        return;
      }
      showLoader('جاري رفع المخططات', 'يتم حفظ ' + Math.min(files.length, remaining) + ' مخطط...');
      input.disabled = true;
      try {
        input.dataset.projectFileType = 'visual_reference';
        const uploaded = await uploadTenantProjectFileInput(input, 'visual_plan_2d');
        const incoming = (Array.isArray(uploaded) ? uploaded : [uploaded]).map((file, index) => ({
          id: file?.id || file,
          name: file?.originalName || files[index]?.name || ''
        })).filter(file => file.id).slice(0, remaining);
        if (!incoming.length) throw new Error('تعذر رفع المخططات');
        for (const file of incoming) {
          if (plans.some(plan => plan.fileId === String(file.id))) continue;
          plans.push({
            id: 'plan_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8),
            mode: 'upload',
            title: '',
            description: '',
            fileId: String(file.id),
            fileName: file.name,
            imageUrl: await publishProjectFileImageUrl(file.id)
          });
        }
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast('تم رفع ' + incoming.length + ' مخطط.');
      } catch (error) {
        toast(error.message || 'تعذر رفع المخططات');
      } finally {
        hideLoader();
        if (input) {
          input.disabled = false;
          input.value = '';
          delete input.dataset.uploadSignatures;
        }
      }
    }

    function deleteVisualConceptPlan(planId) {
      if (isVisualConceptWorkflowPlan(planId)) return;
      const plans = visualConceptPlans();
      const index = plans.findIndex(item => item.id === planId);
      if (index < 0) return;
      plans.splice(index, 1);
      if (tenantVisualConceptState.slots) delete tenantVisualConceptState.slots[planId];
      markVisualConceptDirty();
      renderVisualConceptPage();
      toast('تم حذف المخطط');
    }

    function updateVisualConceptHomeCards() {
      const cover = tenantVisualConceptState?.slots?.cover || {};
      const stored = cover.approvedImageUrl || cover.imageUrl || tenantCreativeImages?.cover || '';
      const image = isSessionOnlyImageUrl(stored) ? '' : stored;
      const preview = document.getElementById('visualConceptHomeCoverPreview');
      const externalStatus = document.getElementById('visualConceptHomeExternalStatus');
      const internalStatus = document.getElementById('visualConceptHomeInternalStatus');
      const externalCard = document.querySelector('.visual-concept-home-card[data-visual-concept-target="external"]');
      if (preview) {
        if (image) {
          preview.src = image;
          preview.hidden = false;
        } else {
          preview.removeAttribute('src');
          preview.hidden = true;
        }
      }
      if (externalCard) externalCard.classList.toggle('has-preview', !!image);
      if (externalStatus) {
        externalStatus.textContent = cover.status === 'approved'
          ? 'معتمدة'
          : (image ? 'تم التوليد — تحتاج اعتماد' : 'جاهز للعمل');
      }
      if (internalStatus) {
        internalStatus.textContent = cover.approvedImageUrl
          ? (visualConceptInteriorComponents().length ? 'جاهز للعمل' : 'أضف مكونات الدراسة المالية')
          : 'مقفل حتى اعتماد الصورة الرئيسية';
      }
      const plansStatus = document.getElementById('visualConceptHomePlansStatus');
      if (plansStatus) {
        const plans = visualConceptPlans();
        plansStatus.textContent = plans.length ? plans.length + ' مخطط' : 'لا توجد مخططات';
      }
    }