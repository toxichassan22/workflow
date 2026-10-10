    /* ── Sketch mirrors: one derived pen-and-ink sketch per visual-concept
       image (exterior + interior, never plans), with its own generated-content
       approval. Lives in slot.sketch inside the normal visual_concept draft
       state — no new slot ids and nothing mirrors into tenantCreativeImages. ── */

    // Generation is tracked outside the slot: normalize maps any stored
    // 'generating' back to a durable status, so an in-flight run is a Set, not
    // a status that a re-render silently loses.
    const visualConceptSketchGenerating = new Set();

    function emptyVisualConceptSketch() {
      return { imageUrl: '', approvedImageUrl: '', status: 'pending', instruction: '' };
    }

    function normalizeVisualConceptSketch(raw) {
      const source = raw && typeof raw === 'object' ? raw : {};
      const approved = durableImageUrl(source.approvedImageUrl);
      const imageUrl = durableImageUrl(source.imageUrl);
      const rawStatus = source.status;
      return {
        imageUrl,
        approvedImageUrl: approved,
        status: ['approved', 'review', 'pending'].includes(rawStatus)
          ? rawStatus
          : (approved ? 'approved' : imageUrl ? 'review' : 'pending'),
        instruction: String(source.instruction || '').slice(0, 2000)
      };
    }

    function visualConceptSketchOf(slotId) {
      const slot = tenantVisualConceptState?.slots?.[slotId];
      if (!slot) return null;
      if (!slot.sketch || typeof slot.sketch !== 'object') slot.sketch = emptyVisualConceptSketch();
      return slot.sketch;
    }

    // Every visual slot except plan diagrams: exterior slots in their fixed
    // order, then interior views grouped by component and view index.
    function visualConceptSketchSourceIds() {
      const slots = tenantVisualConceptState?.slots || {};
      const interior = Object.keys(slots).filter(isVisualConceptInteriorSlot).sort((a, b) => {
        const compA = visualConceptInteriorComponentIdFromSlot(a);
        const compB = visualConceptInteriorComponentIdFromSlot(b);
        if (compA !== compB) return compA < compB ? -1 : 1;
        return visualConceptInteriorViewIndexFromSlot(a) - visualConceptInteriorViewIndexFromSlot(b);
      });
      return VISUAL_CONCEPT_EXTERNAL_SLOTS.map(item => item.id).concat(interior).filter(id => {
        const slot = slots[id];
        if (!slot) return false;
        const hasSource = Boolean(
          durableImageUrl(slot.approvedImageUrl) || durableImageUrl(slot.imageUrl) || slot.sourceFileId);
        const sketch = slot.sketch || {};
        const hasSketch = Boolean(
          durableImageUrl(sketch.approvedImageUrl) || durableImageUrl(sketch.imageUrl));
        return hasSource || hasSketch;
      });
    }

    function visualConceptSketchSourceLabel(slotId) {
      if (isVisualConceptInteriorSlot(slotId)) {
        const componentId = visualConceptInteriorComponentIdFromSlot(slotId);
        const component = visualConceptInteriorComponents().find(item => item.id === componentId);
        return WFT('vc.internal_concept', 'تصور داخلي: {name} — صورة {n}', {
          name: component?.name || WFT('vc.component_fallback', 'المكون'),
          n: visualConceptInteriorViewIndexFromSlot(slotId)
        });
      }
      return visualConceptSlotLabel(slotId);
    }

    function updateVisualConceptSketchesHomeStatus() {
      const status = document.getElementById('visualConceptHomeSketchesStatus');
      if (!status) return;
      const count = visualConceptSketchSourceIds().filter(id => {
        const sketch = tenantVisualConceptState?.slots?.[id]?.sketch || {};
        return durableImageUrl(sketch.approvedImageUrl) || durableImageUrl(sketch.imageUrl);
      }).length;
      status.textContent = count
        ? WFT('vcsketch.count', '{n} سكتش', { n: count })
        : WFT('vcsketch.none', 'لا توجد سكتشات');
    }

    function renderVisualConceptSketches() {
      updateVisualConceptSketchesHomeStatus();
      const host = document.getElementById('visualConceptSketchesWorkspace');
      if (!host) return;
      const sourceIds = visualConceptSketchSourceIds();
      host.innerHTML = sourceIds.length
        ? '<div class="visual-concept-stack">' + sourceIds.map(renderVisualConceptSketchCard).join('') + '</div>'
        : '<p class="tenant-hint">لا توجد صور في التصور البصري بعد.</p>';
    }

    function renderVisualConceptSketchCard(slotId) {
      const slot = tenantVisualConceptState.slots[slotId] || {};
      const sketch = visualConceptSketchOf(slotId) || emptyVisualConceptSketch();
      const sourceImage = durableImageUrl(slot.approvedImageUrl) || durableImageUrl(slot.imageUrl);
      const sketchImage = durableImageUrl(sketch.approvedImageUrl) || durableImageUrl(sketch.imageUrl);
      const approved = sketch.status === 'approved';
      const generating = visualConceptSketchGenerating.has(slotId);
      const statusLabel = approved ? 'معتمد'
        : generating ? 'قيد التوليد'
        : sketchImage ? 'مسودة - جاهزة للاعتماد' : 'مسودة';
      const title = WFT('vcsketch.mirror_of', 'سكتش — {name}', { name: visualConceptSketchSourceLabel(slotId) });
      const preview = sketchImage
        ? '<div class="visual-concept-preview has-image" data-visual-zoom="' + escapeHtml(sketchImage) + '" data-visual-title="' + escapeHtml(title) + '">' +
          '<img src="' + escapeHtml(sketchImage) + '" alt="' + escapeHtml(title) + '">' +
          '<button type="button" class="visual-concept-zoom-btn" data-visual-zoom="' + escapeHtml(sketchImage) + '" data-visual-title="' + escapeHtml(title) + '">تكبير</button></div>'
        : '<div class="visual-concept-preview empty">لم يُولَّد السكتش بعد.</div>';
      const controlsDisabled = approved || generating;
      const canGenerate = Boolean(sourceImage || slot.sourceFileId) && !controlsDisabled;
      const generateBtn = '<button type="button" class="btn primary small" data-sketch-action="generate" data-sketch-slot="' + escapeHtml(slotId) + '" ' + (canGenerate ? '' : 'disabled') + '>' +
        (sketchImage ? 'إعادة توليد السكتش' : 'توليد السكتش') + '</button>';
      const approveBtn = '<button type="button" class="btn ' + (approved ? 'ghost' : 'primary') + ' small" data-sketch-action="' + (approved ? 'unapprove' : 'approve') + '" data-sketch-slot="' + escapeHtml(slotId) + '" ' + ((!sketchImage && !approved) || generating ? 'disabled' : '') + '>' +
        (approved ? 'الغاء الاعتماد' : 'اعتماد') + '</button>';
      const sourceBtn = sourceImage
        ? '<button type="button" class="btn ghost small" data-visual-zoom="' + escapeHtml(sourceImage) + '" data-visual-title="' + escapeHtml(visualConceptSketchSourceLabel(slotId)) + '">معاينة الأصل</button>'
        : '';
      const deleteBtn = sketchImage
        ? '<button type="button" class="btn danger small" data-sketch-action="delete" data-sketch-slot="' + escapeHtml(slotId) + '" ' + (controlsDisabled ? 'disabled' : '') + '>حذف السكتش</button>'
        : '';
      return '<article class="visual-concept-card' + (approved ? ' section-locked' : '') + '" data-sketch-card="' + escapeHtml(slotId) + '">' +
        '<div class="visual-concept-head"><h3>' + escapeHtml(title) + '</h3>' +
        '<span class="visual-concept-status ' + escapeHtml(generating ? 'generating' : sketch.status) + '">' + escapeHtml(statusLabel) + '</span></div>' +
        preview +
        '<label>تعليمات السكتش</label>' +
        '<textarea data-sketch-instruction="' + escapeHtml(slotId) + '" rows="2" ' + (controlsDisabled ? 'disabled' : '') + '>' + escapeHtml(sketch.instruction || '') + '</textarea>' +
        '<div class="visual-concept-actions">' + generateBtn + approveBtn + sourceBtn + deleteBtn + '</div>' +
        '</article>';
    }

    async function generateVisualConceptSketch(slotId) {
      if (!hasPermission('generate_images')) { toast('لا تملك صلاحية توليد الصور'); return; }
      const liveSlot = () => tenantVisualConceptState.slots[slotId];
      if (!liveSlot() || visualConceptSketchGenerating.has(slotId)) return;
      const sketch = visualConceptSketchOf(slotId);
      const sourceImage = durableImageUrl(liveSlot().approvedImageUrl) || durableImageUrl(liveSlot().imageUrl);
      if (!sourceImage && !liveSlot().sourceFileId) {
        toast(WFT('vcsketch.no_source', 'لا توجد صورة أصلية لتوليد السكتش منها'));
        return;
      }
      const previousImage = sketch.imageUrl || sketch.approvedImageUrl;
      visualConceptSketchGenerating.add(slotId);
      renderVisualConceptPage();
      showLoader(WFT('vcsketch.generating', 'جاري توليد السكتش'),
        WFT('vcsketch.generating_detail', 'يتم تحويل الصورة إلى سكتش معماري...'));
      try {
        const payload = await collectVisualConceptPayload(slotId);
        // The sketch endpoint reads slotId, the source image and the note —
        // the visual_concept state mirror is dropped like the plans payload.
        payload.projectData = { ...payload.projectData };
        delete payload.projectData.visual_concept;
        payload.sourceImage = sourceImage;
        payload.sourceFileId = liveSlot().sourceFileId || '';
        payload.instruction = String(visualConceptSketchOf(slotId).instruction || '').slice(0, 2000);
        const response = await apiWithTimeout('POST', '/api/visual-concept/sketch', payload, 180000,
          WFT('vcsketch.timeout', 'انتهت مهلة توليد السكتش؛ أعد المحاولة.'));
        hideLoader();
        if (!response?.success || !response.sketch) {
          visualConceptSketchOf(slotId).status = previousImage ? 'review' : 'pending';
          renderVisualConceptPage();
          toast(response?.error || WFT('vcsketch.failed', 'تعذر توليد السكتش'));
          return;
        }
        const current = visualConceptSketchOf(slotId);
        current.imageUrl = visualConceptImageUrl(response.sketch);
        current.approvedImageUrl = '';
        current.status = 'review';
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast(WFT('vcsketch.generated', 'تم توليد السكتش'));
      } catch (error) {
        hideLoader();
        visualConceptSketchOf(slotId).status = previousImage ? 'review' : 'pending';
        renderVisualConceptPage();
        toast(error.message || WFT('vcsketch.failed', 'تعذر توليد السكتش'));
      } finally {
        visualConceptSketchGenerating.delete(slotId);
      }
    }

    function approveVisualConceptSketch(slotId) {
      const sketch = visualConceptSketchOf(slotId);
      if (!sketch) return;
      const image = durableImageUrl(sketch.imageUrl) || durableImageUrl(sketch.approvedImageUrl);
      if (!image) {
        toast(WFT('vcsketch.approve_first', 'ولّد السكتش أولاً حتى يمكن اعتماده'));
        return;
      }
      sketch.approvedImageUrl = image;
      sketch.status = 'approved';
      markVisualConceptDirty();
      renderVisualConceptPage();
      toast(WFT('vcsketch.approved', 'تم اعتماد السكتش'));
    }

    function unapproveVisualConceptSketch(slotId) {
      const sketch = visualConceptSketchOf(slotId);
      if (!sketch || sketch.status !== 'approved') return;
      sketch.imageUrl = sketch.imageUrl || sketch.approvedImageUrl;
      sketch.approvedImageUrl = '';
      sketch.status = sketch.imageUrl ? 'review' : 'pending';
      markVisualConceptDirty();
      renderVisualConceptPage();
      toast(WFT('vcsketch.unapproved', 'تم إلغاء اعتماد السكتش'));
    }

    function deleteVisualConceptSketch(slotId) {
      const slot = tenantVisualConceptState?.slots?.[slotId];
      if (!slot || !slot.sketch) return;
      const instruction = slot.sketch.instruction || '';
      slot.sketch = emptyVisualConceptSketch();
      slot.sketch.instruction = instruction;
      markVisualConceptDirty();
      renderVisualConceptPage();
      toast(WFT('vcsketch.deleted', 'تم حذف السكتش'));
    }

    // Delegated like the rest of the section: every render replaces innerHTML.
    document.addEventListener('click', event => {
      const button = event.target.closest('[data-sketch-action]');
      if (!button || button.disabled) return;
      const action = button.getAttribute('data-sketch-action');
      const slotId = button.getAttribute('data-sketch-slot');
      if (!slotId) return;
      if (action === 'generate') generateVisualConceptSketch(slotId);
      else if (action === 'approve') approveVisualConceptSketch(slotId);
      else if (action === 'unapprove') unapproveVisualConceptSketch(slotId);
      else if (action === 'delete') deleteVisualConceptSketch(slotId);
    });

    document.addEventListener('input', event => {
      const input = event.target.closest('[data-sketch-instruction]');
      if (!input) return;
      const sketch = visualConceptSketchOf(input.getAttribute('data-sketch-instruction'));
      if (!sketch) return;
      sketch.instruction = String(input.value || '').slice(0, 2000);
      markVisualConceptDirty();
    });
