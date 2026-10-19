    /* ── Visual concept slot model: constants, normalizers and state
       helpers shared by every visual-concept panel. ── */


    const VISUAL_CONCEPT_SLOTS = [
      { id: 'cover', label: 'الصورة الرئيسية', group: 'external' },
      { id: 'right', label: 'يمين', group: 'external' },
      { id: 'left', label: 'شمال', group: 'external' },
      { id: 'top', label: 'فوق', group: 'external' },
      { id: 'back', label: 'خلف', group: 'external' },
      { id: 'main_facade', label: 'الواجهة الرئيسية', group: 'external' },
      { id: 'interior', label: 'التصميم الداخلي', group: 'internal' }
    ];
    const VISUAL_CONCEPT_EXTERNAL_SLOTS = VISUAL_CONCEPT_SLOTS.filter(item => item.group === 'external');
    const VISUAL_CONCEPT_ANGLE_SLOTS = VISUAL_CONCEPT_EXTERNAL_SLOTS.filter(item => item.id !== 'cover' && item.id !== 'main_facade');
    const VISUAL_CONCEPT_INTERNAL_SLOTS = VISUAL_CONCEPT_SLOTS.filter(item => item.group === 'internal');
    const VISUAL_CONCEPT_INTERNAL_PREFIX = 'interior';
    const VISUAL_CONCEPT_MAX_INTERIOR_IMAGES = 30;
    const VISUAL_CONCEPT_MAX_PLANS = 30;
    const VISUAL_CONCEPT_PLAN_KINDS = [
      { kind: 'site', id: 'plan_site', label: 'الموقع العام المبسط' },
      { kind: 'uses', id: 'plan_uses', label: 'توزيع الاستخدامات على الأدوار' },
      { kind: 'massing', id: 'plan_massing', label: 'المنظور الكتلي ثلاثي الأبعاد' }
    ];
    const VISUAL_CONCEPT_SLOT_ALIASES = {
      cover: ['cover', 'main', 'hero'],
      right: ['right', 'east', 'east_facade'],
      left: ['left', 'west', 'west_facade'],
      top: ['top', 'aerial', 'above'],
      back: ['back', 'rear', 'behind'],
      main_facade: ['main_facade', 'front_facade', 'facade_main'],
      interior: ['interior', 'inside', 'internal']
    };

    function emptyVisualConceptSlot(id) {
      return { id, mode: 'ai', label: visualConceptDefaultSlotLabel(id), caption: '', prompt: '', imageUrl: '', approvedImageUrl: '', status: 'pending', chat: [], svgCode: '', styleReferenceFileIds: [], styleReferenceNames: [], sourceFileId: '', sourceFileName: '', sketch: emptyVisualConceptSketch() };
    }

    function visualConceptDefaultSlotLabel(slotId) {
      return VISUAL_CONCEPT_SLOTS.find(item => item.id === slotId)?.label
        || visualConceptPlanDefinition(slotId)?.label
        || (isVisualConceptInteriorSlot(slotId) ? 'التصور الداخلي' : (isVisualConceptPlanSlot(slotId) ? 'مخطط' : 'الصورة'));
    }

    function visualConceptCanRenameSlot(slotId) {
      return VISUAL_CONCEPT_ANGLE_SLOTS.some(item => item.id === slotId)
        || (isVisualConceptPlanSlot(slotId) && !isVisualConceptWorkflowPlan(slotId));
    }

    function isVisualConceptPlanSlot(slotId) {
      return String(slotId || '').startsWith('plan_');
    }

    function visualConceptPlanDefinition(value) {
      const raw = value && typeof value === 'object' ? value : { id: value };
      const kind = String(raw.kind || '').trim().toLowerCase();
      const id = String(raw.id || '').trim();
      return VISUAL_CONCEPT_PLAN_KINDS.find(item => item.kind === kind || item.id === id) || null;
    }

    function isVisualConceptWorkflowPlan(value) {
      return Boolean(visualConceptPlanDefinition(value));
    }

    function visualConceptPlanKind(value) {
      return visualConceptPlanDefinition(value)?.kind || '';
    }

    function visualConceptInteriorSlotId(componentId, viewIndex = 1) {
      const index = Math.max(1, Math.min(VISUAL_CONCEPT_MAX_INTERIOR_IMAGES, Number(viewIndex) || 1));
      return VISUAL_CONCEPT_INTERNAL_PREFIX + '_' + String(componentId || '').trim() + '::' + index;
    }

    function visualConceptInteriorComponentIdFromSlot(slotId) {
      const value = String(slotId || '');
      const prefix = VISUAL_CONCEPT_INTERNAL_PREFIX + '_';
      if (!value.startsWith(prefix)) return '';
      const rest = value.slice(prefix.length);
      return rest.includes('::') ? rest.split('::')[0] : rest;
    }

    function visualConceptInteriorViewIndexFromSlot(slotId) {
      const value = String(slotId || '');
      if (!value.includes('::')) return 1;
      const index = Number(value.split('::').pop());
      return Number.isFinite(index) && index > 0 ? index : 1;
    }

    function isVisualConceptInteriorSlot(slotId) {
      const value = String(slotId || '');
      return value === VISUAL_CONCEPT_INTERNAL_PREFIX || value.startsWith(VISUAL_CONCEPT_INTERNAL_PREFIX + '_');
    }

    function visualConceptInteriorComponents() {
      const rows = typeof getComponentRowsData === 'function' ? getComponentRowsData() : [];
      const fallback = Array.isArray(tenantProjectData?.financial_study_model?.dynamicRows?.components)
        ? tenantProjectData.financial_study_model.dynamicRows.components
        : [];
      const source = rows.length ? rows : fallback;
      const seen = new Set();
      return source.map((item, index) => {
        const id = String(item.id || item.componentId || ('component_' + (index + 1))).trim();
        const name = String(item.name || item.component || item.title || '').trim();
        if (!id || !name || seen.has(id)) return null;
        seen.add(id);
        return {
          id,
          name,
          useType: item.useType || item.type || '',
          units: item.units,
          unitArea: item.unitArea,
          builtArea: item.builtArea || item.totalArea
        };
      }).filter(Boolean).slice(0, 40);
    }

    function visualConceptSlotSource(sourceSlots, itemId) {
      const slots = sourceSlots && typeof sourceSlots === 'object' ? sourceSlots : {};
      const aliases = VISUAL_CONCEPT_SLOT_ALIASES[itemId] || [itemId];
      for (const key of aliases) {
        if (slots[key] && typeof slots[key] === 'object') return slots[key];
      }
      return null;
    }

    function visualConceptReferenceList(value) {
      if (Array.isArray(value)) return value.map(item => String(item || '').trim()).filter(Boolean);
      if (typeof value !== 'string' || !value.trim()) return [];
      try {
        const parsed = JSON.parse(value);
        return Array.isArray(parsed) ? parsed.map(item => String(item || '').trim()).filter(Boolean) : [value.trim()];
      } catch (error) {
        return [value.trim()];
      }
    }

    // Labels and descriptions stay position-aligned with the id list, so empty
    // entries are kept instead of being filtered out like referenceList does.
    function visualConceptReferenceTextList(value, limit) {
      if (!Array.isArray(value)) return [];
      return value.map(item => String(item || '').trim().slice(0, limit));
    }

    // A plan is a slot too: plans2d keeps the durable record the slides and exports read
    // (title, description, file, published image), while slots[plan.id] carries the working
    // state (mode, prompt, chat, approval) so plans run through the same prompt-edit-
    // generate-approve flow as every other visual card.
    function normalizeVisualConceptPlans(raw) {
      let value = raw;
      if (typeof value === 'string') {
        try { value = JSON.parse(value); } catch (error) { value = null; }
      }
      const list = Array.isArray(value) ? value : [];
      const seen = new Set();
      return list.map((item, index) => {
        const source = item && typeof item === 'object' ? item : {};
        let id = String(source.id || '').trim() || ('plan_' + (index + 1));
        if (!id.startsWith('plan_')) id = 'plan_' + id;
        while (seen.has(id)) id = id + '_' + (index + 1);
        seen.add(id);
        const fileId = String(source.fileId || source.file_id || '');
        const imageUrl = durableImageUrl(source.imageUrl || source.image_url);
        const mode = ['ai', 'upload'].includes(source.mode) ? source.mode : (fileId ? 'upload' : 'ai');
        return {
          id,
          mode,
          title: String(source.title || '').slice(0, 120),
          description: String(source.description || '').slice(0, 2000),
          fileId,
          fileName: String(source.fileName || source.file_name || ''),
          imageUrl
        };
      }).filter(item => item.fileId || item.imageUrl || item.mode === 'ai').slice(0, VISUAL_CONCEPT_MAX_PLANS);
    }

    function visualConceptPlanSeed(plan) {
      if (!plan) return null;
      return {
        mode: plan.mode === 'upload' ? 'upload' : 'ai',
        label: plan.title || '',
        caption: plan.description || '',
        sourceFileId: plan.fileId || '',
        sourceFileName: plan.fileName || '',
        imageUrl: plan.imageUrl || '',
        status: plan.imageUrl ? 'review' : 'pending'
      };
    }

    function normalizeVisualConceptState(raw) {
      let value = raw;
      if (typeof value === 'string') {
        try { value = JSON.parse(value); } catch (error) { value = null; }
      }
      const source = value && typeof value === 'object' ? value : {};
      const deletedInteriorSlots = new Set(visualConceptReferenceList(
        source.deletedInteriorSlots || source.deleted_interior_slots));
      const hasStateReferenceIds = ['styleReferenceFileIds', 'style_reference_file_ids', 'styleReferenceFileId', 'style_reference_file_id']
        .some(key => Object.prototype.hasOwnProperty.call(source, key));
      const savedReferenceIds = visualConceptReferenceList(source.styleReferenceFileIds || source.style_reference_file_ids);
      const legacyReferenceId = String(source.styleReferenceFileId || source.style_reference_file_id || '').trim();
      if (legacyReferenceId && !savedReferenceIds.includes(legacyReferenceId)) savedReferenceIds.unshift(legacyReferenceId);
      if (!hasStateReferenceIds && typeof tenantProjectData !== 'undefined') {
        visualConceptReferenceList(tenantProjectData.visual_style_reference_file_ids).forEach(fileId => {
          if (!savedReferenceIds.includes(fileId)) savedReferenceIds.push(fileId);
        });
      }
      const plans = normalizeVisualConceptPlans(source.plans2d);
      const plansWorkflow = normalizeVisualConceptPlansWorkflow(source.plansWorkflow || source.plans_workflow);
      const styleReferenceFileIds = savedReferenceIds.slice(0, 5);
      const styleReferenceNames = visualConceptReferenceList(source.styleReferenceNames || source.style_reference_names);
      const legacyReferenceName = String(source.styleReferenceName || '').trim();
      if (legacyReferenceName && !styleReferenceNames.includes(legacyReferenceName)) styleReferenceNames.unshift(legacyReferenceName);
      styleReferenceNames.splice(5);
      // The element name + note each reference ships to the model with; a missing
      // label is seeded from a human-typed file stem (e.g. "نادي النساء.png").
      const styleReferenceLabels = visualConceptReferenceTextList(
        source.styleReferenceLabels || source.style_reference_labels, 80);
      const styleReferenceDescriptions = visualConceptReferenceTextList(
        source.styleReferenceDescriptions || source.style_reference_descriptions, 600);
      styleReferenceFileIds.forEach((id, index) => {
        if (!styleReferenceLabels[index]) {
          styleReferenceLabels[index] = visualConceptReferenceNameSeed(styleReferenceNames[index]);
        }
      });
      styleReferenceLabels.splice(5);
      styleReferenceDescriptions.splice(5);
      const slots = {};
      // A slot that already carries its own state must never be rebuilt from the legacy
      // tenantCreativeImages mirrors: those hold previews too, so they used to re-approve
      // an image the user had just unapproved, or never approved at all.
      const stated = {};
      const slotIds = new Set(VISUAL_CONCEPT_SLOTS.map(item => item.id));
      VISUAL_CONCEPT_PLAN_KINDS.forEach(definition => slotIds.add(definition.id));
      Object.keys(source.slots && typeof source.slots === 'object' ? source.slots : {}).forEach(id => {
        if (isVisualConceptInteriorSlot(id) && !deletedInteriorSlots.has(id)) slotIds.add(id);
        if (isVisualConceptPlanSlot(id) && plans.some(plan => plan.id === id)) slotIds.add(id);
      });
      plans.forEach(plan => slotIds.add(plan.id));
      visualConceptInteriorComponents().forEach(item => {
        const firstId = visualConceptInteriorSlotId(item.id, 1);
        if (!deletedInteriorSlots.has(firstId)) slotIds.add(firstId);
        const legacyId = VISUAL_CONCEPT_INTERNAL_PREFIX + '_' + item.id;
        if (source.slots && source.slots[legacyId]) slotIds.add(visualConceptInteriorSlotId(item.id, 1));
        for (let view = 2; view <= VISUAL_CONCEPT_MAX_INTERIOR_IMAGES; view += 1) {
          const viewId = visualConceptInteriorSlotId(item.id, view);
          if (source.slots && source.slots[viewId] && !deletedInteriorSlots.has(viewId)) slotIds.add(viewId);
        }
      });
      slotIds.forEach(id => {
        let sourceId = id;
        if (isVisualConceptInteriorSlot(id) && id.includes('::') && visualConceptInteriorViewIndexFromSlot(id) === 1) {
          const legacyId = VISUAL_CONCEPT_INTERNAL_PREFIX + '_' + visualConceptInteriorComponentIdFromSlot(id);
          if ((!source.slots || !source.slots[id]) && source.slots && source.slots[legacyId]) sourceId = legacyId;
        }
        const workflowDefinition = visualConceptPlanDefinition(id);
        const slot = visualConceptSlotSource(source.slots, sourceId) || visualConceptSlotSource(source.slots, id)
          || visualConceptPlanSeed(plans.find(plan => plan.id === id))
          || (workflowDefinition ? visualConceptWorkflowPlanSeed(workflowDefinition, plansWorkflow) : null)
          || emptyVisualConceptSlot(id);
        const chat = Array.isArray(slot.chat) ? slot.chat.filter(entry => entry && typeof entry.text === 'string').slice(-30).map(entry => {
          const role = entry.role === 'assistant' ? 'assistant' : 'user';
          const textLimit = id === 'plan_site' && role === 'assistant' ? 300000 : 4000;
          return {
            role,
            text: String(entry.text).slice(0, textLimit),
            choices: Array.isArray(entry.choices) ? entry.choices.slice(0, 6).map(choice => String(choice).slice(0, 240)) : [],
            attachments: (Array.isArray(entry.attachments) ? entry.attachments : [])
              .map(name => String(name).slice(0, 120)).slice(0, 5)
          };
        }) : [];
        // A blob: URL is a handle into the tab that created it, so a stored one is dead and is
        // dropped here; repairVisualConceptStoredImages republishes it from the file id.
        const approved = durableImageUrl(slot.approvedImageUrl);
        const imageUrl = durableImageUrl(slot.imageUrl);
        const mode = ['ai', 'upload'].includes(slot.mode)
          ? slot.mode
          : (slot.sourceFileId && !slot.prompt && !(slot.chat && slot.chat.length) ? 'upload' : 'ai');
        const rawStatus = slot.status;
        const safeStatus = (rawStatus === 'generating')
          ? (approved ? 'approved' : imageUrl ? 'review' : 'pending')
          : (['approved', 'review', 'pending'].includes(rawStatus)
            ? rawStatus
            : (approved ? 'approved' : imageUrl ? 'review' : 'pending'));
        stated[id] = Boolean(slot.status || approved || imageUrl);
        slots[id] = {
          id,
          mode,
          prompt: String(slot.prompt || '').slice(0, 12000),
          imageUrl,
          approvedImageUrl: approved,
          status: safeStatus,
          chat,
          svgCode: String(slot.svgCode || '').slice(0, 300000),
          styleReferenceFileIds: visualConceptReferenceList(slot.styleReferenceFileIds).slice(0, 5),
          styleReferenceNames: visualConceptReferenceList(slot.styleReferenceNames).slice(0, 5),
          sourceFileId: String(slot.sourceFileId || ''),
          sourceFileName: String(slot.sourceFileName || ''),
          label: String(slot.label || visualConceptDefaultSlotLabel(id)).slice(0, 80),
          caption: String(slot.caption || '').slice(0, 400),
          styleRefStamp: String(slot.styleRefStamp || '').slice(0, 4000),
          sceneToken: String(slot.sceneToken || '').slice(0, 128),
          sketch: normalizeVisualConceptSketch(slot.sketch)
        };
      });
      if (!stated.cover && tenantCreativeImages.cover) {
        slots.cover.approvedImageUrl = tenantCreativeImages.cover;
        slots.cover.imageUrl = slots.cover.imageUrl || tenantCreativeImages.cover;
        slots.cover.prompt = slots.cover.prompt || tenantCreativeImages.cover_prompt || '';
        slots.cover.status = 'approved';
      }
      const moodboardImages = Array.isArray(tenantCreativeImages.moodboard) ? tenantCreativeImages.moodboard : [];
      const moodboardPrompts = Array.isArray(tenantCreativeImages.moodboard_prompts) ? tenantCreativeImages.moodboard_prompts : [];
      VISUAL_CONCEPT_ANGLE_SLOTS.forEach((item, index) => {
        const slot = slots[item.id];
        if (!stated[item.id] && moodboardImages[index]) {
          slot.approvedImageUrl = moodboardImages[index];
          slot.imageUrl = slot.imageUrl || moodboardImages[index];
          slot.status = 'approved';
        }
        if (!slot.prompt && moodboardPrompts[index]) slot.prompt = String(moodboardPrompts[index] || '').slice(0, 12000);
      });
      const mainFacade = slots.main_facade;
      if (!stated.main_facade && tenantCreativeImages.main_facade) {
        mainFacade.approvedImageUrl = tenantCreativeImages.main_facade;
        mainFacade.imageUrl = mainFacade.imageUrl || tenantCreativeImages.main_facade;
        mainFacade.status = 'approved';
        mainFacade.prompt = mainFacade.prompt || tenantCreativeImages.main_facade_prompt || '';
      }
      const rawSectionApprovals = source.sectionApprovals && typeof source.sectionApprovals === 'object'
        ? source.sectionApprovals
        : (source.section_approvals && typeof source.section_approvals === 'object' ? source.section_approvals : {});
      const sectionApprovals = {};
      VISUAL_CONCEPT_SECTION_IDS.forEach(id => {
        sectionApprovals[id] = Boolean(rawSectionApprovals[id]);
      });
      return {
        version: 1,
        slots,
        plans2d: plans,
        plansWorkflow,
        sectionApprovals,
        styleReferenceFileIds,
        styleReferenceFileId: styleReferenceFileIds[0] || '',
        styleReferenceNames,
        styleReferenceName: styleReferenceNames[0] || '',
        styleReferenceLabels,
        styleReferenceDescriptions,
        deletedInteriorSlots: Array.from(deletedInteriorSlots),
        selectedInteriorComponentId: String(source.selectedInteriorComponentId || '').trim()
      };
    }


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
      tenantProjectData.visual_style_reference_names = (tenantVisualConceptState.styleReferenceNames || []).slice(0, 5);
      tenantProjectData.visual_style_reference_labels = (tenantVisualConceptState.styleReferenceLabels || []).slice(0, 5);
      tenantProjectData.visual_style_reference_descriptions = (tenantVisualConceptState.styleReferenceDescriptions || []).slice(0, 5);
      const cover = tenantVisualConceptState.slots.cover || {};
      tenantCreativeImages = previousImages;
      // These mirrors reach the export and the slide prompts, so a session-only blob URL is
      // dropped here: it would arrive on the server as an image that can never be read.
      tenantCreativeImages.cover = durableImageUrl(cover.approvedImageUrl) || durableImageUrl(tenantCreativeImages.cover);
      tenantCreativeImages.cover_prompt = cover.prompt || tenantCreativeImages.cover_prompt || '';
      tenantCreativeImages.moodboard = VISUAL_CONCEPT_ANGLE_SLOTS.map((item, index) => {
        const slot = tenantVisualConceptState.slots[item.id] || {};
        return durableImageUrl(slot.approvedImageUrl) || durableImageUrl(slot.imageUrl) || durableImageUrl(previousMoodboard[index]);
      });
      tenantCreativeImages.moodboard_prompts = VISUAL_CONCEPT_ANGLE_SLOTS.map((item, index) => {
        const slot = tenantVisualConceptState.slots[item.id] || {};
        return slot.prompt || previousPrompts[index] || '';
      });
      const mainFacade = tenantVisualConceptState.slots.main_facade || {};
      tenantCreativeImages.main_facade = durableImageUrl(mainFacade.approvedImageUrl) || durableImageUrl(mainFacade.imageUrl) || '';
      tenantCreativeImages.main_facade_prompt = mainFacade.prompt || '';
      tenantProjectData.tenantCreativeImages = tenantCreativeImages;
      // Section approvals cannot outlive the items they certify — reconcile
      // before every serialization so a revoked/unapproved item always drops
      // its section flag (and, through the chain, every downstream flag).
      if (typeof visualConceptSyncSectionApprovals === 'function') visualConceptSyncSectionApprovals();
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
      return WFT('vc.complete_missing', 'أكمل الحقول الناقصة: {fields}', { fields: missing.map(item => item.label || item.key).join('، ') });
    }

    async function collectVisualConceptPayload(slotId, options = {}) {
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
      // A page-open preflight only checks field completeness; it must not
      // invalidate approvals as a side effect of refreshing the page.
      if (options.syncPlanInputs !== false) syncVisualConceptPlanInputs(projectData);
      return {
        slotId,
        projectData,
        creativeImages: tenantCreativeImages,
        coverImage: tenantVisualConceptState.slots.cover.approvedImageUrl || tenantVisualConceptState.slots.cover.imageUrl || '',
        coverFileId: tenantVisualConceptState.slots.cover.sourceFileId || '',
        slotLabel: visualConceptSlotLabel(slotId),
        currentPrompt: tenantVisualConceptState.slots[slotId]?.prompt || '',
        prompt: tenantVisualConceptState.slots[slotId]?.prompt || '',
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
        planImages: visualConceptPlanImageMap()
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
      if (isVisualConceptWorkflowPlan(slotId)) {
        return typeof visualConceptPlanScenePending !== 'undefined' && visualConceptPlanScenePending
          ? WFT('plans.scene_busy', 'المشهد الهندسي قيد المعالجة.')
          : WFT('plans.scene_required', 'المشهد الهندسي غير جاهز.');
      }
      if (isVisualConceptInteriorSlot(slotId)) {
        if (!visualConceptSectionApproved('external')) return visualConceptSectionLockReason('internal');
        if (!durableImageUrl(tenantVisualConceptState?.slots?.cover?.approvedImageUrl)) {
          return 'مقفل حتى اعتماد الصورة الرئيسية.';
        }
        return 'لا توجد مكونات في الدراسة المالية بعد.';
      }
      if (visualConceptSectionLocked('external')) return visualConceptSectionLockReason('external');
      return 'مقفل حتى اعتماد الصورة الرئيسية.';
    }

    function visualConceptSlotLocked(slotId) {
      // Stage three starts the scene through its first chat turn, so the site
      // plan composer must remain available before a scene token exists.
      // Other workflow diagrams still require that shared scene first.
      if (isVisualConceptPlanSlot(slotId)) {
        if (!isVisualConceptWorkflowPlan(slotId)) return false;
        if (Boolean(visualConceptPlanScenePending)) return true;
        return slotId !== 'plan_site' && !tenantVisualConceptState?.plansWorkflow?.scene?.token;
      }
      if (isVisualConceptInteriorSlot(slotId)) {
        // Interior renders consume the approved hero as their building
        // reference — a skipped (empty) exterior section leaves that input
        // missing even though the section flag is set.
        return !visualConceptSectionApproved('external')
          || !durableImageUrl(tenantVisualConceptState.slots.cover?.approvedImageUrl)
          || !visualConceptInteriorComponents().length;
      }
      // Exterior renders stay locked until the plans section is approved as a
      // whole; the angles still wait for the hero image on top of that.
      if (!visualConceptSectionApproved('plans2d')) return true;
      return slotId !== 'cover' && !tenantVisualConceptState.slots.cover.approvedImageUrl;
    }

    function selectedVisualConceptInteriorComponentId() {
      const select = document.getElementById('visualConceptInteriorComponentSelect');
      return String(select?.value || tenantVisualConceptState?.selectedInteriorComponentId || visualConceptInteriorComponents()[0]?.id || '').trim();
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

    function renderVisualConceptInteriorWorkspace() {
      const host = document.getElementById('visualConceptInternalWorkspace');
      const select = document.getElementById('visualConceptInteriorComponentSelect');
      const hint = document.getElementById('visualConceptInteriorHint');
      const referenceCard = document.getElementById('visualConceptInteriorReferenceCard');
      if (!host) return;
      const components = visualConceptInteriorComponents();
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
        label: WFT('vc.internal_concept', 'تصور داخلي: {name} — صورة {n}', { name: component?.name || WFT('vc.component_fallback', 'المكون'), n: index + 1 }),
        group: 'internal'
      }, visualConceptSlotLocked(id))).join('');
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
      // A merely-locked slot keeps its generate button clickable: pressing it
      // raises the lock notice with the missing precondition, which a disabled
      // button could never surface. The chat row stays gated on the lock.
      const generateBtnDisabled = frozen || slot.status === 'generating';
      const generateDisabled = generateBtnDisabled || waitCover;
      const mode = slot.mode === 'upload' ? 'upload' : 'ai';
      const disableAiSwitch = frozen || (hasImage && mode === 'upload');
      const disableUploadSwitch = frozen || (hasImage && mode === 'ai');
      const statusLabel = approved ? 'معتمد' : slot.status === 'generating' ? 'قيد التوليد' : slot.status === 'review' ? 'مسودة - جاهزة للاعتماد' : 'مسودة';
      const chat = (slot.chat || []).map(item => (
        '<div class="visual-concept-chat-message"><strong>' + (item.role === 'assistant' ? trDynamicI18n('النظام:') + ' ' : trDynamicI18n('أنت:') + ' ') + '</strong>' + escapeHtml(item.text) +
        (item.attachments && item.attachments.length ? ' <em class="visual-concept-chat-attached">(' + escapeHtml(item.attachments.join('، ')) + ')</em>' : '') +
        (item.role === 'assistant' && item.choices?.length
          ? '<div class="visual-concept-chat-choices">' + item.choices.map(choice =>
            '<button type="button" class="btn ghost small" data-visual-action="chat-choice" data-visual-slot="' + slotDef.id + '" data-choice="' + escapeHtml(choice) + '">' + escapeHtml(choice) + '</button>'
          ).join('') + '</div>' : '') + '</div>'
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
      // «حذف المخطط» removes an uploaded plan entry; the three workflow plans
      // are fixed stages, so their cards only ever carry «حذف الصورة».
      const deleteFieldBtn = isVisualConceptInteriorSlot(slotDef.id)
        ? '<button type="button" class="btn danger small" data-visual-action="delete-interior-field" data-visual-slot="' + slotDef.id + '">حذف الحقل</button>'
        : (isVisualConceptPlanSlot(slotDef.id) && !isVisualConceptWorkflowPlan(slotDef.id)
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
        bodyControls = (isVisualConceptPlanSlot(slotDef.id)
          ? '<label>وصف المخطط</label><textarea data-visual-caption="' + slotDef.id + '" rows="2" ' + (frozen ? 'disabled' : '') + '>' + escapeHtml(slot.caption || '') + '</textarea>'
          : '') +
          '<div class="visual-concept-actions">' +
          '<button type="button" class="btn primary small" data-visual-action="generate" data-visual-slot="' + slotDef.id + '" ' + (generateBtnDisabled ? 'disabled' : '') + '>' + (slotDef.id === 'plan_site' ? 'مراجعة المتطلبات والتوليد' : 'توليد الصورة') + '</button>' +
          '<button type="button" class="btn ' + (approved ? 'ghost' : 'primary') + ' small" data-visual-action="' + (approved ? 'unapprove' : 'approve') + '" data-visual-slot="' + slotDef.id + '" ' + ((!image && !approved) ? 'disabled' : '') + '>' + (approved ? 'الغاء الاعتماد' : 'اعتماد') + '</button>' +
          deleteBtn + deleteFieldBtn +
          '</div>' +
          (slotDef.id === 'cover'
            ? '<div class="visual-concept-regen-row">' +
              '<button type="button" class="btn ghost small" data-visual-action="regen-prompt" data-visual-slot="cover" ' + (generateBtnDisabled ? 'disabled' : '') + '>' +
              escapeHtml(WFT('vc.regen_prompt', 'إعادة توليد الوصف')) + '</button>' +
              '<span class="visual-concept-regen-hint' + (visualConceptCoverStyleRefStale() ? ' stale' : '') + '">' +
              escapeHtml(WFT('vc.regen_prompt_hint', 'يُحدَّث بعد إضافة أو تعديل الصور المرجعية')) + '</span>' +
              '</div>'
            : '') +
          '<div class="visual-concept-chat">' + (slotDef.id === 'plan_site' ? '<h4>محادثة المخطط</h4>' : '') + chat + '</div>' +
          '<div class="visual-concept-chat-row">' +
          '<textarea data-visual-chat="' + slotDef.id + '" rows="2" ' + (generateDisabled ? 'disabled' : '') + '></textarea>' +
          '<button type="button" class="btn ghost small" data-visual-action="chat-attach" data-visual-slot="' + slotDef.id + '" ' + (generateDisabled ? 'disabled' : '') + '>' + escapeHtml(WFT('vc.chat_attach', 'إرفاق صورة')) + '</button>' +
          '<button type="button" class="btn primary small" data-visual-action="chat" data-visual-slot="' + slotDef.id + '" ' + (generateDisabled ? 'disabled' : '') + '>' + (slotDef.id === 'plan_site' ? 'إرسال الرسالة' : 'إرسال التعديل') + '</button>' +
          '<input type="file" accept="' + uploadAccept + '" multiple hidden data-visual-chat-upload="' + slotDef.id + '">' +
          '</div>' +
          '<div class="visual-concept-chat-refs" data-visual-chat-refs="' + slotDef.id + '"></div>';
      }

      const lockHint = waitCover
        ? '<p class="tenant-hint visual-concept-lock-hint">' + escapeHtml(visualConceptLockMessage(slotDef.id)) + '</p>'
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
              <div class="visual-concept-lightbox-controls">
                <button type="button" class="btn ghost small" data-visual-lightbox-zoom="in">تكبير</button>
                <button type="button" class="btn ghost small" data-visual-lightbox-zoom="out">تصغير</button>
                <button type="button" class="btn ghost small" data-visual-lightbox-zoom="reset">الحجم الطبيعي</button>
                <button type="button" class="btn ghost small" data-visual-lightbox-tab>نافذة جديدة</button>
                <button type="button" class="btn ghost small" data-visual-lightbox-close>إغلاق</button>
              </div>
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
        let currentScale = 1;
        const setScale = (scale) => {
          currentScale = Math.min(Math.max(scale, 0.5), 5);
          const imgEl = modal.querySelector('#visualConceptLightboxImg');
          if (imgEl) {
            imgEl.style.transform = currentScale === 1 ? 'none' : ('scale(' + currentScale + ')');
            imgEl.style.cursor = currentScale > 1 ? 'grab' : 'default';
          }
        };
        modal.querySelector('[data-visual-lightbox-zoom="in"]')?.addEventListener('click', () => setScale(currentScale + 0.35));
        modal.querySelector('[data-visual-lightbox-zoom="out"]')?.addEventListener('click', () => setScale(currentScale - 0.35));
        modal.querySelector('[data-visual-lightbox-zoom="reset"]')?.addEventListener('click', () => setScale(1));
        modal.querySelector('[data-visual-lightbox-tab]')?.addEventListener('click', () => {
          const imgEl = modal.querySelector('#visualConceptLightboxImg');
          if (imgEl && imgEl.src) window.open(imgEl.src, '_blank');
        });
      }
      const img = modal.querySelector('#visualConceptLightboxImg');
      const titleEl = modal.querySelector('#visualConceptLightboxTitle');
      if (img) {
        img.src = url;
        img.style.transform = 'none';
      }
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

    // Locked slots keep a live generate button; pressing it surfaces the
    // missing precondition in a real dialog so the client cannot miss it.
    function showVisualConceptLockNotice(message) {
      let modal = document.getElementById('visualConceptLockNotice');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'visualConceptLockNotice';
        modal.className = 'll-modal-overlay';
        modal.setAttribute('data-a11y-modal', '');
        modal.style.display = 'none';
        modal.innerHTML =
          '<div class="ll-modal-card" role="dialog" aria-modal="true" aria-labelledby="visualConceptLockNoticeTitle">' +
          '<div class="sag-modal-head"><h2 id="visualConceptLockNoticeTitle">التوليد مقفل</h2></div>' +
          '<p id="visualConceptLockNoticeText" class="visual-concept-lock-hint"></p>' +
          '<div class="sag-modal-actions"><button type="button" class="btn primary" data-visual-lock-close>إغلاق</button></div>' +
          '</div>';
        document.body.appendChild(modal);
        modal.addEventListener('click', event => {
          if (event.target === modal || event.target.closest('[data-visual-lock-close]')) {
            closeVisualConceptLockNotice();
          }
        });
      }
      modal.querySelector('#visualConceptLockNoticeText').textContent = String(message || '');
      modal.style.display = 'flex';
      if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(modal);
    }

    function closeVisualConceptLockNotice() {
      const modal = document.getElementById('visualConceptLockNotice');
      if (!modal) return;
      modal.style.display = 'none';
      if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
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

    // Style- and interior-reference upload/render helpers live in
    // 12-files-media/04_visual_concept_references.js — this file stays the
    // state machine; that part owns the reference UI.

    function updateVisualConceptHomeCards() {
      const cover = tenantVisualConceptState?.slots?.cover || {};
      const stored = cover.approvedImageUrl || cover.imageUrl || tenantCreativeImages?.cover || '';
      const image = isSessionOnlyImageUrl(stored) ? '' : stored;
      const preview = document.getElementById('visualConceptHomeCoverPreview');
      const externalStatus = document.getElementById('visualConceptHomeExternalStatus');
      const internalStatus = document.getElementById('visualConceptHomeInternalStatus');
      const externalCard = document.querySelector('.visual-concept-home-card[data-visual-concept-target="external"]');
      // Home cards mirror the section chain: a locked card is disabled and its
      // status names the approval that opens it.
      document.querySelectorAll('.visual-concept-home-card[data-visual-concept-target]').forEach(card => {
        card.disabled = visualConceptSectionLocked(card.getAttribute('data-visual-concept-target'));
      });
      const setStatus = (id, sectionId, readyText) => {
        const el = document.getElementById(id);
        if (!el) return;
        const locked = visualConceptSectionLocked(sectionId);
        el.textContent = visualConceptSectionApproved(sectionId)
          ? WFT('vc.sec.approved', 'قسم معتمد')
          : (locked ? visualConceptSectionLockReason(sectionId) : readyText);
        el.classList.toggle('locked', locked);
      };
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
      setStatus('visualConceptHomeExternalStatus', 'external',
        cover.status === 'approved' ? 'معتمدة' : (image ? 'تم التوليد — تحتاج اعتماد' : 'جاهز للعمل'));
      setStatus('visualConceptHomeInternalStatus', 'internal',
        visualConceptInteriorComponents().length ? 'جاهز للعمل' : 'لا توجد مكونات في الدراسة المالية بعد.');
      const plansStatus = document.getElementById('visualConceptHomePlansStatus');
      if (plansStatus) {
        const plans = visualConceptPlans();
        plansStatus.textContent = visualConceptSectionApproved('plans2d')
          ? WFT('vc.sec.approved', 'قسم معتمد')
          : (plans.length ? plans.length + ' مخطط' : 'لا توجد مخططات');
        plansStatus.classList.remove('locked');
      }
      updateVisualConceptSketchesHomeStatus();
    }
