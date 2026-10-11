    /* ── Visual concept style references: uploads, per-image names and
       descriptions, and the interior per-component reference block. An
       exterior reference ships to the prompt writer and the image model as
       "name + description", so a multi-building project assigns every
       reference to its element instead of one style winning them all. ── */


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

    // A camera-default file stem (IMG_4021, Screenshot...) is noise, not a label —
    // only a human-typed stem seeds the element name the model receives.
    function visualConceptReferenceNameSeed(fileName) {
      const stem = String(fileName || '').replace(/\.[A-Za-z0-9]{1,8}$/, '').trim();
      if (!stem) return '';
      if (!/[؀-ۿa-zA-Z]/.test(stem)) return '';
      if (/^(img|image|dsc|dscn|screenshot|screen shot|whatsapp|photo|pasted|untitled|scan|pic|pxl|mmexport|صورة|صوره)[\s_\-\d().]*$/i.test(stem)) return '';
      return stem.slice(0, 80);
    }

    function renderVisualConceptStyleReference() {
      const preview = document.getElementById('visualConceptStyleReferencePreview');
      if (!preview) return;
      const ids = Array.isArray(tenantVisualConceptState?.styleReferenceFileIds)
        ? tenantVisualConceptState.styleReferenceFileIds : [];
      const names = Array.isArray(tenantVisualConceptState?.styleReferenceNames)
        ? tenantVisualConceptState.styleReferenceNames : [];
      const labels = Array.isArray(tenantVisualConceptState?.styleReferenceLabels)
        ? tenantVisualConceptState.styleReferenceLabels : [];
      const descriptions = Array.isArray(tenantVisualConceptState?.styleReferenceDescriptions)
        ? tenantVisualConceptState.styleReferenceDescriptions : [];
      if (!ids.length) {
        preview.textContent = 'لم تُرفع صور مرجعية.';
        return;
      }
      preview.innerHTML = '<div class="visual-concept-reference-list"></div>';
      const list = preview.firstElementChild;
      ids.forEach((fileId, index) => {
        const item = document.createElement('div');
        item.className = 'visual-concept-reference-item';
        const refLabel = WFT('vc.reference_image', 'صورة مرجعية {n}', { n: index + 1 });
        const nameLabel = WFT('vc.ref_name', 'اسم العنصر');
        const descLabel = WFT('vc.ref_desc', 'وصف الصورة');
        item.innerHTML =
          '<img alt="' + refLabel + '">' +
          '<span class="visual-concept-reference-filename">' + escapeHtml(names[index] || refLabel) + '</span>' +
          '<input type="text" class="visual-concept-ref-name" data-ref-meta="label" data-ref-index="' + index + '"' +
          ' value="' + escapeHtml(labels[index] || '') + '" placeholder="' + escapeHtml(nameLabel) + '"' +
          ' aria-label="' + escapeHtml(nameLabel) + '" maxlength="80">' +
          '<textarea class="visual-concept-ref-desc" data-ref-meta="description" data-ref-index="' + index + '"' +
          ' rows="2" maxlength="600" placeholder="' + escapeHtml(descLabel) + '"' +
          ' aria-label="' + escapeHtml(descLabel) + '">' + escapeHtml(descriptions[index] || '') + '</textarea>' +
          '<button type="button" class="btn ghost danger small visual-concept-reference-remove"' +
          ' data-ref-remove="' + escapeHtml(fileId) + '">حذف</button>';
        list.appendChild(item);
        attachProjectFileThumbnail(item.querySelector('img'), fileId);
      });
    }

    function onVisualConceptStyleReferenceMeta(event) {
      const input = event.target.closest('[data-ref-meta]');
      if (!input) return;
      const index = Number(input.getAttribute('data-ref-index'));
      if (!Number.isInteger(index) || index < 0) return;
      const field = input.getAttribute('data-ref-meta') === 'description'
        ? 'styleReferenceDescriptions' : 'styleReferenceLabels';
      const limit = field === 'styleReferenceDescriptions' ? 600 : 80;
      const list = Array.isArray(tenantVisualConceptState[field])
        ? tenantVisualConceptState[field] : (tenantVisualConceptState[field] = []);
      list[index] = String(input.value || '').slice(0, limit);
      markVisualConceptDirty();
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
        const existingLabels = tenantVisualConceptState.styleReferenceLabels || [];
        const existingDescriptions = tenantVisualConceptState.styleReferenceDescriptions || [];
        existingIds.forEach((id, index) => merged.push({
          id,
          name: existingNames[index] || '',
          label: existingLabels[index] || '',
          description: existingDescriptions[index] || ''
        }));
        incoming.forEach(file => {
          const found = merged.find(item => String(item.id) === String(file.id));
          if (found) found.name = found.name || file.name;
          else merged.push({
            id: file.id,
            name: file.name,
            label: visualConceptReferenceNameSeed(file.name),
            description: ''
          });
        });
        const limited = merged.slice(0, 5);
        tenantVisualConceptState.styleReferenceFileIds = limited.map(file => file.id);
        tenantVisualConceptState.styleReferenceNames = limited.map(file => file.name);
        tenantVisualConceptState.styleReferenceLabels = limited.map(file => file.label || '');
        tenantVisualConceptState.styleReferenceDescriptions = limited.map(file => file.description || '');
        tenantVisualConceptState.styleReferenceFileId = limited[0]?.id || '';
        tenantVisualConceptState.styleReferenceName = limited[0]?.name || '';
        markVisualConceptDirty();
        renderVisualConceptStyleReference();
        toast(WFT('vc.refs_saved', 'تم حفظ {n} صور مرجعية.', { n: limited.length }));
      } catch (error) {
        toast(error.message || 'تعذر رفع الصور المرجعية');
      } finally {
        if (input) input.value = '';
      }
    }

    function clearVisualConceptStyleReference() {
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      tenantVisualConceptState.styleReferenceFileIds = [];
      tenantVisualConceptState.styleReferenceFileId = '';
      tenantVisualConceptState.styleReferenceNames = [];
      tenantVisualConceptState.styleReferenceName = '';
      tenantVisualConceptState.styleReferenceLabels = [];
      tenantVisualConceptState.styleReferenceDescriptions = [];
      markVisualConceptDirty();
      renderVisualConceptStyleReference();
      toast('تم حذف الصور المرجعية. سيولد النظام التصميم من البيانات والخريطة فقط.');
    }

    // The signature of the ref set a cover prompt was written against: ids,
    // labels and descriptions joined, so any rename or description edit flips
    // it and marks the stored prompt stale.
    function visualConceptStyleRefSignature() {
      const state = tenantVisualConceptState || {};
      const ids = Array.isArray(state.styleReferenceFileIds) ? state.styleReferenceFileIds : [];
      const labels = Array.isArray(state.styleReferenceLabels) ? state.styleReferenceLabels : [];
      const descriptions = Array.isArray(state.styleReferenceDescriptions) ? state.styleReferenceDescriptions : [];
      return ids.map((id, index) =>
        String(id) + '|' + String(labels[index] || '') + '|' + String(descriptions[index] || '')
      ).join('~');
    }

    // The stored cover prompt is hidden, so this comparison is the only
    // freshness signal — a prompt whose stamp differs from the current
    // signature was written against a different ref set.
    function visualConceptCoverStyleRefStale() {
      const slot = tenantVisualConceptState?.slots?.cover;
      if (!slot || !slot.prompt) return false;
      return String(slot.styleRefStamp || '') !== visualConceptStyleRefSignature();
    }

    // Every chip carries its own remove button: the parallel id/name/label/
    // description arrays stay index-aligned, so one splice per array drops a
    // single reference without disturbing the rest.
    function removeVisualConceptStyleReference(fileId) {
      const target = String(fileId || '');
      if (!target) return;
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      const ids = Array.isArray(tenantVisualConceptState.styleReferenceFileIds)
        ? tenantVisualConceptState.styleReferenceFileIds : [];
      const index = ids.findIndex(id => String(id) === target);
      if (index === -1) return;
      ['styleReferenceFileIds', 'styleReferenceNames', 'styleReferenceLabels', 'styleReferenceDescriptions']
        .forEach(field => {
          const list = Array.isArray(tenantVisualConceptState[field]) ? tenantVisualConceptState[field] : [];
          list.splice(index, 1);
          tenantVisualConceptState[field] = list;
        });
      tenantVisualConceptState.styleReferenceFileId = tenantVisualConceptState.styleReferenceFileIds[0] || '';
      tenantVisualConceptState.styleReferenceName = tenantVisualConceptState.styleReferenceNames[0] || '';
      markVisualConceptDirty();
      renderVisualConceptStyleReference();
      toast(WFT('vc.ref_removed', 'تم حذف الصورة المرجعية.'));
    }

    // One delegated click handler serves both reference lists; the previews are
    // re-rendered by innerHTML so listeners bound per chip would die silently.
    function onVisualConceptReferenceListClick(event) {
      const button = event.target.closest('[data-ref-remove]');
      if (!button || button.disabled) return;
      const fileId = button.getAttribute('data-ref-remove');
      if (!fileId) return;
      if (button.closest('#visualConceptInteriorReferencePreview')) removeVisualConceptInteriorReference(fileId);
      else removeVisualConceptStyleReference(fileId);
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
        const refLabel = WFT('vc.reference_image', 'صورة مرجعية {n}', { n: index + 1 });
        item.innerHTML = '<img alt="' + refLabel + '"><span>' + escapeHtml(names[index] || refLabel) + '</span>' +
          '<button type="button" class="btn ghost danger small visual-concept-reference-remove"' +
          ' data-ref-remove="' + escapeHtml(fileId) + '">حذف</button>';
        list.appendChild(item);
        attachProjectFileThumbnail(item.querySelector('img'), fileId);
      });
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

    // Mirrors the bulk clear for one chip: the entry leaves the component's
    // reference list, while the view card the upload seeded keeps its own
    // per-image delete button — an approved image never dies via a side
    // channel.
    function removeVisualConceptInteriorReference(fileId) {
      const target = String(fileId || '');
      if (!target) return;
      const componentId = selectedVisualConceptInteriorComponentId();
      const firstId = visualConceptInteriorSlotId(componentId, 1);
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      const slot = tenantVisualConceptState.slots[firstId];
      if (!slot) return;
      const ids = Array.isArray(slot.styleReferenceFileIds) ? slot.styleReferenceFileIds : [];
      const index = ids.findIndex(id => String(id) === target);
      if (index === -1) return;
      ids.splice(index, 1);
      if (Array.isArray(slot.styleReferenceNames)) slot.styleReferenceNames.splice(index, 1);
      markVisualConceptDirty();
      renderVisualConceptInteriorReferences(firstId);
      toast(WFT('vc.ref_removed', 'تم حذف الصورة المرجعية.'));
    }
