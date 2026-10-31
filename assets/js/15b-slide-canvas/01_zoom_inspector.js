/* Canvas zoom and the element inspector. The inspector is the exact-value
   surface; the card toolbar stays the quick-actions surface. */

    let tenantCanvasZoom = 0.75;
    const TENANT_CANVAS_ZOOM_MIN = 0.5;
    const TENANT_CANVAS_ZOOM_MAX = 2;

    function canvasText(key, fallback, params) {
      return (typeof WFT === 'function') ? WFT(key, fallback, params) : fallback;
    }

    function canvasStageFor(index) {
      return typeof slideStageForIndex === 'function' ? slideStageForIndex(index) : null;
    }

    function canvasSession(index) {
      return typeof getSlideEditSession === 'function' ? getSlideEditSession(index) : null;
    }

    function slideSelectedEntries(session) {
      if (!session) return [];
      if (Array.isArray(session.multi) && session.multi.length) return session.multi;
      return session.sel ? [session.sel] : [];
    }

    function slideSelectedTargets(stage, session) {
      const slide = stage ? stage.querySelector('.slide') : null;
      if (!slide || !session) return [];
      return slideSelectedEntries(session)
        .map(entry => ({ entry, target: elementAtSlidePath(slide, entry.path) }))
        .filter(item => item.target && slide.contains(item.target) && item.target !== slide);
    }

    function applyTenantCanvasZoom(scale, silent) {
      const next = Math.max(TENANT_CANVAS_ZOOM_MIN, Math.min(TENANT_CANVAS_ZOOM_MAX, Number(scale) || 0.75));
      tenantCanvasZoom = next;
      document.querySelectorAll('#tenantSlidesPage .tenant-slide-stage').forEach(stage => {
        if (typeof autoFitSlideContent === 'function') autoFitSlideContent(stage);
        const card = stage.closest('.ge-slide-card');
        const index = card ? Number(String(card.id || '').replace('slide-card-', '')) : NaN;
        if (Number.isInteger(index) && typeof restoreSlideEditSelection === 'function') {
          restoreSlideEditSelection(stage, index);
        }
      });
      const readout = document.getElementById('slidesZoomReadout');
      if (readout) readout.textContent = Math.round(next * 100) + '%';
      if (!silent) {
        try { localStorage.setItem('wf.slidesCanvasZoom', String(next)); } catch (error) {}
      }
    }

    function fitTenantCanvasZoom() {
      const main = document.getElementById('tenantSlidesMain');
      if (!main) return;
      const width = Math.max(320, main.clientWidth - 48);
      applyTenantCanvasZoom(Math.min(width / 1280, 1));
    }

    function fullscreenTenantCanvas() {
      const page = document.getElementById('tenantSlidesPage');
      if (!page) return;
      if (document.fullscreenElement) {
        document.exitFullscreen?.().catch(() => {});
        return;
      }
      page.requestFullscreen?.().then(() => fitTenantCanvasZoom()).catch(() => {});
    }

    function ensureSlidesCanvasChrome() {
      const page = document.getElementById('tenantSlidesPage');
      if (!page || document.getElementById('slidesCanvasZoom')) return;
      const zoom = document.createElement('div');
      zoom.className = 'slides-canvas-zoom';
      zoom.id = 'slidesCanvasZoom';
      zoom.innerHTML = '<button type="button" onclick="applyTenantCanvasZoom(tenantCanvasZoom - 0.1)">'
        + escapeHtml(canvasText('ca.zoom_out', 'تصغير')) + '</button>'
        + '<span class="slides-canvas-zoom-readout" id="slidesZoomReadout">75%</span>'
        + '<button type="button" onclick="applyTenantCanvasZoom(tenantCanvasZoom + 0.1)">'
        + escapeHtml(canvasText('ca.zoom_in', 'تكبير')) + '</button>'
        + '<button type="button" onclick="applyTenantCanvasZoom(1)">100%</button>'
        + '<button type="button" onclick="fitTenantCanvasZoom()">'
        + escapeHtml(canvasText('ca.zoom_fit', 'ملاءمة')) + '</button>'
        + '<button type="button" onclick="fullscreenTenantCanvas()">'
        + escapeHtml(canvasText('ca.zoom_full', 'ملء الشاشة')) + '</button>';
      page.appendChild(zoom);

    }

    function slideElementHasText(el) {
      if (!el) return false;
      const text = String(el.innerText || el.textContent || '').trim();
      return !!text;
    }

    function inspectorTargetKind(el) {
      if (!el) return 'none';
      if (el.closest && el.closest('[data-slide-table]')) return 'table';
      if (el.tagName === 'TABLE') return 'table';
      if (el.tagName === 'IMG') return 'image';
      if (el.hasAttribute && (el.hasAttribute('data-slide-imagebox') || el.hasAttribute('data-canonical-map'))) return 'image';
      if (slideElementHasText(el)) return 'text';
      const media = el.querySelector ? el.querySelector('img') : null;
      if (media) return 'image';
      return 'shape';
    }

    /* The card toolbar asks the same question the inspector asks, so a text
       element never carries image tools and a shape never carries text ones. */
    function slideToolbarSelectionKind(index) {
      const session = canvasSession(index);
      const stage = canvasStageFor(index);
      if (!session || !session.sel || !stage) return '';
      const slide = stage.querySelector('.slide');
      const target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
      return target ? inspectorTargetKind(target) : '';
    }

    function slideElementRectInSlide(stage, el) {
      const slide = stage ? stage.querySelector('.slide') : null;
      if (!slide || !el) return null;
      const scale = slideRenderedScale(stage);
      const slideRect = slide.getBoundingClientRect();
      const rect = el.getBoundingClientRect();
      return {
        x: Math.round((rect.left - slideRect.left) / scale),
        y: Math.round((rect.top - slideRect.top) / scale),
        width: Math.round(rect.width / scale),
        height: Math.round(rect.height / scale)
      };
    }

    function slideElementInlineValue(el, prop, fallback) {
      try {
        const inline = el.style && el.style[prop];
        if (inline) return inline;
        const computed = window.getComputedStyle(el);
        return computed[prop] || fallback;
      } catch (error) {
        return fallback;
      }
    }

    function slideStyleNumber(value, fallback) {
      const number = parseFloat(String(value || ''));
      return isFinite(number) ? Math.round(number * 10) / 10 : fallback;
    }

    function withSlideElementTargets(index, mutator) {
      const session = canvasSession(index);
      const stage = canvasStageFor(index);
      const slideData = tenantSlidesData[index];
      if (!session || !stage || !slideData || !slideData.html) return false;
      const slide = stage.querySelector('.slide');
      const entries = slideSelectedEntries(session);
      if (!slide || !entries.length) return false;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return false;
      const pairs = [];
      entries.forEach(entry => {
        const live = elementAtSlidePath(slide, entry.path);
        const raw = live ? findSlideRawTarget(rawRoot, live, entry.path) : null;
        if (live && raw) pairs.push({ live, raw, entry });
      });
      if (!pairs.length) return false;
      if (typeof pushSlideEditHistory === 'function') pushSlideEditHistory(index);
      pairs.forEach(({ live, raw, entry }) => {
        try { mutator(live, raw, entry); } catch (error) { console.warn('[INSPECTOR] apply failed', error); }
      });
      slideData.html = rawRoot.outerHTML;
      markSlideHtmlEdited(slideData);
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      if (typeof touchSlideEditSession === 'function') touchSlideEditSession(index);
      triggerAutoSaveDraft();
      if (typeof refreshSlideEditToolbar === 'function') refreshSlideEditToolbar(index);
      renderSlideInspector(index);
      return true;
    }

    function setSlideElementTransformPair(live, raw, tx, ty) {
      const transform = 'translate(' + Math.round(tx) + 'px, ' + Math.round(ty) + 'px)';
      live.style.transform = transform;
      raw.style.transform = transform;
      live.dataset.manualTranslateX = String(Math.round(tx));
      live.dataset.manualTranslateY = String(Math.round(ty));
      raw.dataset.manualTranslateX = String(Math.round(tx));
      raw.dataset.manualTranslateY = String(Math.round(ty));
    }

    function moveSlideSelectionTo(index, axis, value, property) {
      const stage = canvasStageFor(index);
      const session = canvasSession(index);
      if (!stage || !session) return;
      const primary = slideSelectedTargets(stage, session)[0];
      if (!primary) return;
      const rect = slideElementRectInSlide(stage, primary.target);
      if (!rect) return;
      const delta = Math.round(value - (property === 'x' ? rect.x : rect.y));
      moveSlideSelectionBy(index, axis === 'x' ? delta : 0, axis === 'y' ? delta : 0);
    }

    function moveSlideSelectionBy(index, dx, dy) {
      if (!dx && !dy) return;
      withSlideElementTargets(index, (live, raw) => {
        const baseX = Number(live.dataset.manualTranslateX) || 0;
        const baseY = Number(live.dataset.manualTranslateY) || 0;
        setSlideElementTransformPair(live, raw, baseX + dx, baseY + dy);
      });
    }

    function resizeSlideSelection(index, width, height) {
      const values = {};
      if (Number(width) > 0) values.width = Math.round(Number(width));
      if (Number(height) > 0) values.height = Math.round(Number(height));
      if (!Object.keys(values).length) return;
      withSlideElementTargets(index, (live, raw) => {
        if (values.width) {
          live.style.width = values.width + 'px';
          raw.style.width = values.width + 'px';
        }
        if (values.height) {
          const isImage = live.tagName === 'IMG';
          live.style[isImage ? 'height' : 'minHeight'] = values.height + 'px';
          raw.style[isImage ? 'height' : 'minHeight'] = values.height + 'px';
        }
      });
    }

    function alignSlideSelection(index, horizontal, vertical) {
      const stage = canvasStageFor(index);
      const session = canvasSession(index);
      if (!stage || !session) return;
      const slide = stage.querySelector('.slide');
      const pairs = slideSelectedTargets(stage, session);
      if (!slide || !pairs.length) return;
      const slideScale = slideRenderedScale(stage);
      const slideRect = slide.getBoundingClientRect();
      withSlideElementTargets(index, (live, raw) => {
        const rect = live.getBoundingClientRect();
        const w = rect.width / slideScale;
        const h = rect.height / slideScale;
        let dx = 0;
        let dy = 0;
        if (horizontal === 'left') dx = 0 - (rect.left - slideRect.left) / slideScale;
        if (horizontal === 'center') dx = (1280 - w) / 2 - (rect.left - slideRect.left) / slideScale;
        if (horizontal === 'right') dx = 1280 - w - (rect.left - slideRect.left) / slideScale;
        if (vertical === 'top') dy = 0 - (rect.top - slideRect.top) / slideScale;
        if (vertical === 'middle') dy = (720 - h) / 2 - (rect.top - slideRect.top) / slideScale;
        if (vertical === 'bottom') dy = 720 - h - (rect.top - slideRect.top) / slideScale;
        const baseX = Number(live.dataset.manualTranslateX) || 0;
        const baseY = Number(live.dataset.manualTranslateY) || 0;
        setSlideElementTransformPair(live, raw, baseX + dx, baseY + dy);
      });
    }

    function distributeSlideSelection(index, axis) {
      const stage = canvasStageFor(index);
      const session = canvasSession(index);
      if (!stage || !session) return;
      const pairs = slideSelectedTargets(stage, session);
      if (pairs.length < 3) {
        toast(canvasText('ca.distribute_needs_three', 'حدد ثلاثة عناصر أو أكثر للتوزيع'));
        return;
      }
      const scale = slideRenderedScale(stage);
      const slide = stage.querySelector('.slide');
      const slideRect = slide.getBoundingClientRect();
      const items = pairs.map(pair => {
        const rect = pair.target.getBoundingClientRect();
        return {
          pair,
          start: axis === 'x' ? (rect.left - slideRect.left) / scale : (rect.top - slideRect.top) / scale,
          size: axis === 'x' ? rect.width / scale : rect.height / scale
        };
      }).sort((a, b) => a.start - b.start);
      const first = items[0];
      const last = items[items.length - 1];
      const span = (last.start + last.size) - first.start;
      const sumSizes = items.reduce((total, item) => total + item.size, 0);
      const gap = (span - sumSizes) / (items.length - 1);
      let cursor = first.start;
      const deltas = new Map();
      items.forEach(item => {
        deltas.set(item.pair, cursor - item.start);
        cursor += item.size + gap;
      });
      withSlideElementTargets(index, (live, raw) => {
        const pair = pairs.find(item => item.target === live);
        const delta = pair ? deltas.get(pair) : 0;
        const baseX = Number(live.dataset.manualTranslateX) || 0;
        const baseY = Number(live.dataset.manualTranslateY) || 0;
        setSlideElementTransformPair(live, raw,
          baseX + (axis === 'x' ? delta : 0),
          baseY + (axis === 'y' ? delta : 0));
      });
    }

    function setSlideSelectionStyle(index, mutator) {
      withSlideElementTargets(index, (live, raw) => {
        mutator(live);
        mutator(raw);
      });
    }

    function setSlideSelectionRotation(index, degrees) {
      const value = Math.max(-180, Math.min(180, Number(degrees) || 0));
      withSlideElementTargets(index, (live, raw) => {
        live.style.rotate = value ? value + 'deg' : '';
        raw.style.rotate = value ? value + 'deg' : '';
      });
    }

    function toggleSlideSelectionShadow(index) {
      const session = canvasSession(index);
      const stage = canvasStageFor(index);
      if (!session || !stage) return;
      const pairs = slideSelectedTargets(stage, session);
      const primary = pairs[0] ? pairs[0].target : null;
      if (!primary) return;
      if (slideElementShadowLevel(primary, 'boxShadow') !== 'none') {
        setSlideSelectionStyle(index, el => { el.style.boxShadow = 'none'; });
      } else {
        setSlideSelectionStyle(index, el => { el.style.boxShadow = '0 10px 30px rgba(7,24,44,.22)'; });
      }
    }

    function deleteSelectedSlideElements(index) {
      const session = canvasSession(index);
      if (!session) return;
      const stage = canvasStageFor(index);
      const slideData = tenantSlidesData[index];
      if (!stage || !slideData) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      const pairs = slideSelectedTargets(stage, session);
      if (!pairs.length) return;
      if (typeof pushSlideEditHistory === 'function') pushSlideEditHistory(index);
      pairs.forEach(({ entry, target }) => {
        const raw = findSlideRawTarget(rawRoot, target, entry.path);
        const deleteTarget = watermarkOverlayOf(raw) || raw;
        deleteTarget?.parentElement?.removeChild(deleteTarget);
      });
      slideData.html = rawRoot.outerHTML;
      markSlideHtmlEdited(slideData);
      session.sel = null;
      session.multi = [];
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
      renderSlideInspector(index);
      toast(canvasText('ca.elements_deleted', 'تم حذف العناصر المحددة'));
    }

    let slideElementClipboard = [];

    function copySelectedSlideElements(index) {
      const stage = canvasStageFor(index);
      const session = canvasSession(index);
      if (!stage || !session) return;
      const pairs = slideSelectedTargets(stage, session);
      if (!pairs.length) return;
      slideElementClipboard = pairs.map(pair => pair.target.outerHTML);
      toast(canvasText('ca.elements_copied', 'تم نسخ العناصر المحددة'));
    }

    function pasteSlideElements(index) {
      const slideData = tenantSlidesData[index];
      const stage = canvasStageFor(index);
      const session = canvasSession(index);
      if (!slideData || !stage || !session || !slideElementClipboard.length) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      if (typeof pushSlideEditHistory === 'function') pushSlideEditHistory(index);
      slideElementClipboard.forEach(markup => {
        const template = rawDoc.createElement('div');
        template.innerHTML = markup;
        const node = template.firstElementChild;
        if (!node) return;
        node.classList.remove('slide-element-selected', 'slide-element-multiselected');
        node.dataset.manualTranslateX = String((Number(node.dataset.manualTranslateX) || 0) + 20);
        node.dataset.manualTranslateY = String((Number(node.dataset.manualTranslateY) || 0) + 20);
        node.style.transform = 'translate(' + node.dataset.manualTranslateX + 'px, ' + node.dataset.manualTranslateY + 'px)';
        rawRoot.appendChild(node);
      });
      slideData.html = rawRoot.outerHTML;
      markSlideHtmlEdited(slideData);
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
      toast(canvasText('ca.elements_pasted', 'تم لصق العناصر'));
    }

    function duplicateSelectedSlideElements(index) {
      copySelectedSlideElements(index);
      pasteSlideElements(index);
    }

    function selectAllSlideElements(index) {
      const stage = canvasStageFor(index);
      const session = canvasSession(index);
      const slide = stage ? stage.querySelector('.slide') : null;
      if (!slide || !session) return;
      const entries = [];
      Array.from(slide.children).forEach(child => {
        if (slidePathIgnores(child)) return;
        if (slideDragTarget(slide, child) !== child) return;
        const path = slideElementPath(slide, child);
        if (path) entries.push({ path, placement: '' });
      });
      if (!entries.length) return;
      session.multi = entries;
      session.sel = entries[0];
      clearSlideElementSelection(stage);
      entries.forEach(entry => {
        const target = elementAtSlidePath(slide, entry.path);
        target?.classList.add('slide-element-selected');
      });
      if (entries.length > 1) {
        slideSelectedTargets(stage, session).forEach(({ target }) => {
          target.classList.add('slide-element-multiselected');
        });
      }
      positionSlideEditHandles(stage, elementAtSlidePath(slide, entries[0].path));
      syncSlideElementToolbar(index);
      renderSlideInspector(index);
    }

    function selectAllButPrimary(stage, session) {
      const pairs = slideSelectedTargets(stage, session);
      pairs.forEach(({ target }) => {
        if (target !== pairs[0].target) target.classList.add('slide-element-multiselected');
      });
    }

    function groupSelectedSlideElements(index) {
      const stage = canvasStageFor(index);
      const session = canvasSession(index);
      const slideData = tenantSlidesData[index];
      if (!stage || !session || !slideData) return;
      const pairs = slideSelectedTargets(stage, session);
      if (pairs.length < 2) {
        toast(canvasText('ca.group_needs_two', 'حدد عنصرين أو أكثر للتجميع'));
        return;
      }
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      const scale = slideRenderedScale(stage);
      const slide = stage.querySelector('.slide');
      const slideRect = slide.getBoundingClientRect();
      const boxes = pairs.map(pair => {
        const rect = pair.target.getBoundingClientRect();
        return {
          pair,
          x: (rect.left - slideRect.left) / scale,
          y: (rect.top - slideRect.top) / scale,
          width: rect.width / scale,
          height: rect.height / scale
        };
      });
      const minX = Math.min(...boxes.map(box => box.x));
      const minY = Math.min(...boxes.map(box => box.y));
      const maxX = Math.max(...boxes.map(box => box.x + box.width));
      const maxY = Math.max(...boxes.map(box => box.y + box.height));
      const group = rawDoc.createElement('div');
      group.setAttribute('data-slide-group', '1');
      group.setAttribute('style', 'position:absolute;left:' + Math.round(minX) + 'px;top:' + Math.round(minY)
        + 'px;width:' + Math.round(maxX - minX) + 'px;height:' + Math.round(maxY - minY) + 'px;z-index:5;');
      if (typeof pushSlideEditHistory === 'function') pushSlideEditHistory(index);
      boxes.forEach(box => {
        const raw = findSlideRawTarget(rawRoot, box.pair.target, box.pair.entry.path);
        if (!raw) return;
        raw.style.position = 'absolute';
        raw.style.left = Math.round(box.x - minX) + 'px';
        raw.style.top = Math.round(box.y - minY) + 'px';
        raw.style.transform = '';
        delete raw.dataset.manualTranslateX;
        delete raw.dataset.manualTranslateY;
        group.appendChild(raw);
      });
      rawRoot.appendChild(group);
      slideData.html = rawRoot.outerHTML;
      markSlideHtmlEdited(slideData);
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      session.sel = null;
      session.multi = [];
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
      const groupedStage = slideStageForIndex(index);
      const groupedSlide = groupedStage ? groupedStage.querySelector('.slide') : null;
      const grouped = groupedSlide ? groupedSlide.querySelector('[data-slide-group]') : null;
      const groupedPath = grouped && groupedSlide ? slideElementPath(groupedSlide, grouped) : null;
      if (groupedStage && grouped && groupedPath) selectSlideElement(groupedStage, index, grouped, groupedPath);
      else renderSlideInspector(index);
      toast(canvasText('ca.elements_grouped', 'تم تجميع العناصر'));
    }

    function ungroupSelectedSlideElements(index) {
      const stage = canvasStageFor(index);
      const session = canvasSession(index);
      const slideData = tenantSlidesData[index];
      if (!stage || !session || !slideData) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot || !session.sel) return;
      const pairs = slideSelectedTargets(stage, session);
      const grouped = pairs.map(pair => pair.target.closest('[data-slide-group="1"]')).filter(Boolean);
      const unique = [...new Set(grouped)];
      if (!unique.length) {
        toast(canvasText('ca.not_a_group', 'العنصر المحدد ليس مجموعة'));
        return;
      }
      if (typeof pushSlideEditHistory === 'function') pushSlideEditHistory(index);
      unique.forEach(groupLive => {
        const rawGroup = findSlideRawTarget(rawRoot, groupLive,
          slideElementPath(stage.querySelector('.slide'), groupLive));
        if (!rawGroup) return;
        const baseX = parseFloat(rawGroup.style.left) || 0;
        const baseY = parseFloat(rawGroup.style.top) || 0;
        Array.from(rawGroup.children).forEach(child => {
          child.style.position = 'absolute';
          child.style.left = Math.round(baseX + (parseFloat(child.style.left) || 0)) + 'px';
          child.style.top = Math.round(baseY + (parseFloat(child.style.top) || 0)) + 'px';
          rawGroup.parentElement.insertBefore(child, rawGroup);
        });
        rawGroup.parentElement.removeChild(rawGroup);
      });
      slideData.html = rawRoot.outerHTML;
      markSlideHtmlEdited(slideData);
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      session.sel = null;
      session.multi = [];
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
      renderSlideInspector(index);
      toast(canvasText('ca.elements_ungrouped', 'تم فك التجميع'));
    }

    let slideInspectorGroup = '';

    function slideInspectorField(label, control) {
      return '<label class="slide-inspector-field"><span class="slide-inspector-field-label">'
        + escapeHtml(label) + '</span>' + control + '</label>';
    }

    function slideInspectorChip(label, group) {
      return '<button type="button" class="slide-inspector-chip' + (slideInspectorGroup === group ? ' is-active' : '')
        + '" data-slide-inspector-group="' + group + '" onclick="toggleSlideInspectorGroup(\'' + group + '\')">'
        + escapeHtml(label) + '</button>';
    }

    function toggleSlideInspectorGroup(group) {
      slideInspectorGroup = slideInspectorGroup === group ? '' : group;
      renderSlideInspector(activeSlideIndex);
    }

    function slideInspectorButton(label, action, active) {
      return '<button type="button"' + (active ? ' class="is-active"' : '')
        + ' onclick="' + action + '">' + escapeHtml(label) + '</button>';
    }

    function slideInlineInspectorHost(index) {
      const card = document.getElementById('slide-card-' + index);
      if (!card) return null;
      let host = card.querySelector('.slide-inline-inspector');
      if (!host) {
        host = document.createElement('div');
        host.className = 'slide-inline-inspector';
        const stage = card.querySelector('.tenant-slide-stage');
        card.insertBefore(host, stage);
      }
      return host;
    }

    function slideElementShadowLevel(el, property) {
      if (!el) return 'none';
      try {
        const inline = String(el.style && el.style[property] || '').trim().toLowerCase();
        if (inline === 'none') return 'none';
        if (inline) return 'soft';
        const computed = String(window.getComputedStyle(el)[property] || '').trim().toLowerCase();
        return computed && computed !== 'none' ? 'soft' : 'none';
      } catch (error) {
        return 'none';
      }
    }

    function slideShadowSelect(index, property, el) {
      let current = slideElementShadowLevel(el, property);
      if (current === 'none' && property === 'textShadow'
        && slideElementShadowLevel(el, 'boxShadow') !== 'none') current = 'soft';
      const option = (value, label) => '<option value="' + value + '"'
        + (current === value ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
      return '<select onchange="setSlideSelectionShadow(' + index + ', this.value)">'
        + option('none', canvasText('ca.shadow_none', 'بدون ظل'))
        + option('soft', canvasText('ca.shadow_soft', 'ظل خفيف'))
        + option('strong', canvasText('ca.shadow_strong', 'ظل قوي'))
        + '</select>';
    }

    function setSlideSelectionShadow(index, level) {
      const session = canvasSession(index);
      const stage = canvasStageFor(index);
      if (!session || !stage) return;
      const pairs = slideSelectedTargets(stage, session);
      const primary = pairs[0] ? pairs[0].target : null;
      if (!primary) return;
      const property = inspectorTargetKind(primary) === 'text' ? 'textShadow' : 'boxShadow';
      const values = property === 'textShadow'
        ? { none: 'none', soft: '0 2px 6px rgba(7,24,44,.28)', strong: '0 4px 14px rgba(7,24,44,.4)' }
        : { none: 'none', soft: '0 10px 30px rgba(7,24,44,.18)', strong: '0 18px 40px rgba(7,24,44,.35)' };
      const value = values[level] || values.none;
      setSlideSelectionStyle(index, el => {
        el.style[property] = value;
        // A text card may carry its shadow on the box; "no shadow" clears both.
        if (property === 'textShadow' && value === 'none') el.style.boxShadow = 'none';
      });
    }

    function toggleSlideInlineInspector(btn) {
      const host = btn && btn.closest ? btn.closest('.slide-inline-inspector') : null;
      if (!host) return;
      const collapsed = host.classList.toggle('is-collapsed');
      btn.textContent = canvasText(collapsed ? 'ws.plan_expand' : 'ws.plan_collapse', collapsed ? 'توسيع' : 'طي');
    }

    function renderSlideInspector(index) {
      const host = slideInlineInspectorHost(index);
      if (!host) return;
      document.querySelectorAll('.slide-inline-inspector').forEach(other => {
        if (other === host) return;
        other.innerHTML = '';
        other.hidden = true;
      });
      const session = canvasSession(index);
      const stage = canvasStageFor(index);
      const pairs = slideSelectedTargets(stage, session);
      if (!session || !pairs.length) {
        host.innerHTML = '';
        host.hidden = true;
        return;
      }
      const primary = pairs[0].target;
      const kind = inspectorTargetKind(primary);
      if (stage && host.parentElement === stage.parentElement) {
        // A table needs its own cells under the pointer for the double-click.
        // Its inspector sits after the slide, never between the table and the
        // next click that lands on a cell.
        if (kind === 'table' && host.previousElementSibling !== stage) {
          stage.parentElement.insertBefore(host, stage.nextSibling);
        } else if (kind !== 'table' && host.nextElementSibling !== stage) {
          stage.parentElement.insertBefore(host, stage);
        }
      }
      const rect = slideElementRectInSlide(stage, primary);
      const multi = pairs.length > 1;
      const opacity = typeof slideElementOpacityPct === 'function' ? slideElementOpacityPct(primary) : 100;
      const rotation = parseFloat(primary.style.rotate) || 0;
      const parts = [];
      host.hidden = false;
      const collapsed = host.classList.contains('is-collapsed');
      parts.push('<div class="slide-inspector-head"><span class="slide-inspector-title">'
        + escapeHtml(canvasText('ca.inspector', 'خصائص العنصر')) + (multi ? ' — ' + pairs.length : '')
        + '</span><span class="slide-inspector-head-actions">'
        + '<button type="button" class="slide-inspector-collapse" onclick="toggleSlideInlineInspector(this)">'
        + escapeHtml(canvasText(collapsed ? 'ws.plan_expand' : 'ws.plan_collapse', collapsed ? 'توسيع' : 'طي'))
        + '</button><button type="button" class="slide-inspector-close" onclick="closeSlideInspector()">'
        + escapeHtml(canvasText('ca.close', 'إغلاق')) + '</button></span></div>');
      parts.push('<div class="slide-inspector-body">');

      if (!multi && rect) {
        parts.push('<div class="slide-inspector-rowline">'
          + '<span class="slide-inspector-row-label">' + escapeHtml(canvasText('ca.position', 'الموضع')) + '</span>'
          + slideInspectorField('X', '<input type="number" id="inspectorX" value="' + rect.x
            + '" onchange="moveSlideSelectionTo(' + index + ', \'x\', Number(this.value))">')
          + slideInspectorField('Y', '<input type="number" id="inspectorY" value="' + rect.y
            + '" onchange="moveSlideSelectionTo(' + index + ', \'y\', Number(this.value))">')
          + slideInspectorField(canvasText('ca.w', 'العرض'), '<input type="number" id="inspectorW" value="' + rect.width
            + '" onchange="resizeSlideSelection(' + index + ', Number(this.value), 0)">')
          + slideInspectorField(canvasText('ca.h', 'الارتفاع'), '<input type="number" id="inspectorH" value="' + rect.height
            + '" onchange="resizeSlideSelection(' + index + ', 0, Number(this.value))">')
          + '</div>');
      }

      if (kind === 'text') {
        const fontSize = slideStyleNumber(slideElementInlineValue(primary, 'fontSize', '16px'), 16);
        const fontWeight = parseInt(slideElementInlineValue(primary, 'fontWeight', '400'), 10) || 400;
        const textAlign = String(slideElementInlineValue(primary, 'textAlign', 'right') || 'right');
        const color = typeof cssColorToHex === 'function' ? (cssColorToHex(slideElementInlineValue(primary, 'color', '')) || '#1e293b') : '#1e293b';
        parts.push('<div class="slide-inspector-rowline">'
          + '<span class="slide-inspector-row-label">' + escapeHtml(canvasText('ca.text', 'النص')) + '</span>'
          + slideInspectorField(canvasText('ca.font_size', 'حجم الخط'),
            '<input type="number" min="8" max="200" value="' + fontSize
            + '" onchange="setSlideSelectionFontSize(' + index + ', Number(this.value))">')
          + slideInspectorField(canvasText('ca.weight', 'الوزن'),
            '<select onchange="setSlideSelectionFontWeight(' + index + ', Number(this.value))">'
            + '<option value="400"' + (fontWeight < 600 ? ' selected' : '') + '>' + escapeHtml(canvasText('ca.normal', 'عادي')) + '</option>'
            + '<option value="700"' + (fontWeight >= 600 ? ' selected' : '') + '>' + escapeHtml(canvasText('ca.bold', 'عريض')) + '</option>'
            + '</select>')
          + slideInspectorField(canvasText('ca.text_align', 'محاذاة النص'),
            '<select onchange="setSlideSelectionTextAlign(' + index + ', this.value)">'
            + ['right', 'center', 'left'].map(value => '<option value="' + value + '"'
              + (textAlign === value ? ' selected' : '') + '>'
              + escapeHtml({ right: canvasText('ca.right', 'يمين'), center: canvasText('ca.center', 'وسط'), left: canvasText('ca.left', 'يسار') }[value])
              + '</option>').join('') + '</select>')
          + slideInspectorField(canvasText('ca.text_color', 'لون النص'),
            '<input type="color" value="' + color + '" onchange="setSlideSelectionTextColor(' + index + ', this.value)">')
          + '</div>');
      }

      if (kind === 'image') {
        const fit = String(slideElementInlineValue(primary, 'objectFit', '') || '').toLowerCase();
        const radius = slideStyleNumber(slideElementInlineValue(primary, 'borderRadius', '0px'), 0);
        parts.push('<div class="slide-inspector-rowline">'
          + '<span class="slide-inspector-row-label">' + escapeHtml(canvasText('ca.image', 'الصورة')) + '</span>'
          + '<div class="slide-inspector-actions">'
          + slideInspectorButton(canvasText('ca.replace_image', 'استبدال'), 'openSlideImagePicker(' + index + ')')
          + '</div>'
          + slideInspectorField(canvasText('ca.fit', 'الملاءمة'),
            '<select onchange="setSlideSelectionImageFit(' + index + ', this.value)">'
            + '<option value="cover"' + (fit === 'cover' ? ' selected' : '') + '>' + escapeHtml(canvasText('ca.cover', 'ملء')) + '</option>'
            + '<option value="contain"' + (fit === 'contain' ? ' selected' : '') + '>' + escapeHtml(canvasText('ca.contain', 'احتواء')) + '</option>'
            + '</select>')
          + slideInspectorField(canvasText('ca.radius', 'الزوايا'),
            '<input type="number" min="0" max="200" value="' + radius
            + '" onchange="setSlideSelectionBorderRadius(' + index + ', Number(this.value))">')
          + '</div>');
      }

      if (kind === 'shape') {
        const fill = typeof cssColorToHex === 'function' ? (cssColorToHex(slideElementInlineValue(primary, 'backgroundColor', '')) || '#ffffff') : '#ffffff';
        const borderColor = typeof cssColorToHex === 'function' ? (cssColorToHex(slideElementInlineValue(primary, 'borderColor', '')) || '#dbe3ea') : '#dbe3ea';
        const radius = slideStyleNumber(slideElementInlineValue(primary, 'borderRadius', '0px'), 0);
        parts.push('<div class="slide-inspector-rowline">'
          + '<span class="slide-inspector-row-label">' + escapeHtml(canvasText('ca.shape', 'الشكل')) + '</span>'
          + slideInspectorField(canvasText('ca.fill', 'التعبئة'),
            '<input type="color" value="' + fill + '" onchange="setSlideSelectionFill(' + index + ', this.value)">')
          + slideInspectorField(canvasText('ca.border_color', 'الحدود'),
            '<input type="color" value="' + borderColor + '" onchange="setSlideSelectionBorderColor(' + index + ', this.value)">')
          + slideInspectorField(canvasText('ca.radius', 'الزوايا'),
            '<input type="number" min="0" max="200" value="' + radius
            + '" onchange="setSlideSelectionBorderRadius(' + index + ', Number(this.value))">')
          + '</div>');
      }

      if (kind === 'table') {
        const sampleCell = primary.querySelector && primary.querySelector('td,th');
        const cellFill = sampleCell && typeof cssColorToHex === 'function'
          ? (cssColorToHex(sampleCell.style.backgroundColor || window.getComputedStyle(sampleCell).backgroundColor) || '#ffffff') : '#ffffff';
        parts.push('<div class="slide-inspector-rowline">'
          + '<span class="slide-inspector-row-label">' + escapeHtml(canvasText('tb.table', 'جدول')) + '</span>'
          + '<div class="slide-inspector-actions">'
          + slideInspectorButton(canvasText('ca.add_row', 'صف جديد'), 'runSlideTableAction(' + index + ', \'rowadd\')')
          + slideInspectorButton(canvasText('ca.del_row', 'حذف صف'), 'runSlideTableAction(' + index + ', \'rowdel\')')
          + slideInspectorButton(canvasText('ca.add_col', 'عمود جديد'), 'runSlideTableAction(' + index + ', \'coladd\')')
          + slideInspectorButton(canvasText('ca.del_col', 'حذف عمود'), 'runSlideTableAction(' + index + ', \'coldel\')')
          + '</div>'
          + slideInspectorField(canvasText('ca.cell_fill', 'لون الخلية'),
            '<input type="color" value="' + cellFill + '" onchange="setSlideInspectorTableCellColor(' + index + ', this.value)">')
          + '</div>');
      }

      parts.push('<div class="slide-inspector-rowline slide-inspector-chips">'
        + slideInspectorChip(canvasText('ca.align', 'محاذاة'), 'align')
        + slideInspectorChip(canvasText('ca.more', 'مزيد'), 'more')
        + slideInspectorChip(canvasText('ca.actions', 'إجراءات'), 'actions')
        + '</div>');

      if (slideInspectorGroup === 'align') {
        parts.push('<div class="slide-inspector-rowline slide-inspector-group" data-slide-inspector-open="align">'
          + '<span class="slide-inspector-row-label">' + escapeHtml(canvasText('ca.horizontal', 'أفقي')) + '</span>'
          + '<div class="slide-inspector-actions">'
          + slideInspectorButton(canvasText('ca.right', 'يمين'), 'alignSlideSelection(' + index + ', \'right\', \'\')')
          + slideInspectorButton(canvasText('ca.center', 'وسط'), 'alignSlideSelection(' + index + ', \'center\', \'\')')
          + slideInspectorButton(canvasText('ca.left', 'يسار'), 'alignSlideSelection(' + index + ', \'left\', \'\')')
          + '</div>'
          + '<span class="slide-inspector-row-label">' + escapeHtml(canvasText('ca.vertical', 'رأسي')) + '</span>'
          + '<div class="slide-inspector-actions">'
          + slideInspectorButton(canvasText('ca.top', 'أعلى'), 'alignSlideSelection(' + index + ', \'\', \'top\')')
          + slideInspectorButton(canvasText('ca.middle', 'منتصف'), 'alignSlideSelection(' + index + ', \'\', \'middle\')')
          + slideInspectorButton(canvasText('ca.bottom', 'أسفل'), 'alignSlideSelection(' + index + ', \'\', \'bottom\')')
          + '</div>'
          + (multi ? '<span class="slide-inspector-row-label">' + escapeHtml(canvasText('ca.distribute', 'توزيع')) + '</span>'
            + '<div class="slide-inspector-actions">'
            + slideInspectorButton(canvasText('ca.distribute_h', 'أفقي'), 'distributeSlideSelection(' + index + ', \'x\')')
            + slideInspectorButton(canvasText('ca.distribute_v', 'رأسي'), 'distributeSlideSelection(' + index + ', \'y\')')
            + '</div>' : '')
          + '</div>');
      }

      if (slideInspectorGroup === 'more') {
        let extras = '';
        if (kind === 'text') {
          const lineHeight = slideStyleNumber(slideElementInlineValue(primary, 'lineHeight', 'normal'), 0);
          const letterSpacing = slideStyleNumber(slideElementInlineValue(primary, 'letterSpacing', 'normal'), 0);
          extras = slideInspectorField(canvasText('ca.line_height', 'تباعد الأسطر'),
            '<input type="number" min="0.8" max="3" step="0.1" value="' + (lineHeight || 1.6)
            + '" onchange="setSlideSelectionLineHeight(' + index + ', Number(this.value))">')
            + slideInspectorField(canvasText('ca.letter_spacing', 'تباعد الحروف'),
              '<input type="number" min="-5" max="20" step="0.5" value="' + letterSpacing
              + '" onchange="setSlideSelectionLetterSpacing(' + index + ', Number(this.value))">')
            + slideInspectorField(canvasText('ca.shadow', 'ظل'), slideShadowSelect(index, 'textShadow', primary));
        } else if (kind === 'image') {
          const borderWidth = slideStyleNumber(slideElementInlineValue(primary, 'borderWidth', '0px'), 0);
          const borderColor = typeof cssColorToHex === 'function' ? (cssColorToHex(slideElementInlineValue(primary, 'borderColor', '')) || '#dbe3ea') : '#dbe3ea';
          extras = slideInspectorField(canvasText('ca.border_width', 'سماكة الحدود'),
            '<input type="number" min="0" max="20" value="' + borderWidth
            + '" onchange="setSlideSelectionBorderWidth(' + index + ', Number(this.value))">')
            + slideInspectorField(canvasText('ca.border_color', 'الحدود'),
              '<input type="color" value="' + borderColor + '" onchange="setSlideSelectionBorderColor(' + index + ', this.value)">')
            + '<span class="slide-inspector-row-label">' + escapeHtml(canvasText('ca.aspect_lock', 'قفل النسبة')) + '</span>'
            + '<div class="slide-inspector-actions">'
            + slideInspectorButton(hasSlideAspectLock(index) ? canvasText('ca.locked', 'مقفل') : canvasText('ca.unlocked', 'مفتوح'),
              'toggleSlideAspectLock(' + index + ')', hasSlideAspectLock(index))
            + '</div>'
            + slideInspectorField(canvasText('ca.shadow', 'ظل'), slideShadowSelect(index, 'boxShadow', primary));
        } else if (kind === 'shape') {
          const borderWidth = slideStyleNumber(slideElementInlineValue(primary, 'borderWidth', '0px'), 0);
          extras = slideInspectorField(canvasText('ca.border_width', 'سماكة الحدود'),
            '<input type="number" min="0" max="20" value="' + borderWidth
            + '" onchange="setSlideSelectionBorderWidth(' + index + ', Number(this.value))">')
            + slideInspectorField(canvasText('ca.shadow', 'ظل'), slideShadowSelect(index, 'boxShadow', primary));
        } else if (kind === 'table') {
          const sampleCell = primary.querySelector && primary.querySelector('td,th');
          const borderColor = sampleCell && typeof cssColorToHex === 'function'
            ? (cssColorToHex(sampleCell.style.borderColor || window.getComputedStyle(sampleCell).borderColor) || '#dbe3ea') : '#dbe3ea';
          extras = slideInspectorField(canvasText('ca.table_border', 'حدود الجدول'),
            '<input type="color" value="' + borderColor + '" onchange="setSlideInspectorTableBorderColor(' + index + ', this.value)">');
        }
        parts.push('<div class="slide-inspector-rowline slide-inspector-group" data-slide-inspector-open="more">'
          + slideInspectorField(canvasText('ca.opacity', 'الشفافية'),
            '<input type="number" min="1" max="100" step="1" value="' + opacity
            + '" onchange="commitSlideElementOpacity(' + index + ', Number(this.value))">')
          + slideInspectorField(canvasText('ca.rotation', 'الدوران'),
            '<input type="number" min="-180" max="180" step="1" value="' + Math.round(rotation)
            + '" onchange="setSlideSelectionRotation(' + index + ', Number(this.value))">')
          + '<span class="slide-inspector-row-label">' + escapeHtml(canvasText('ca.layer', 'الطبقة')) + '</span>'
          + '<div class="slide-inspector-actions">'
          + slideInspectorButton(canvasText('ca.front', 'أمام'), 'adjustSlideElementLayer(' + index + ', 1)')
          + slideInspectorButton(canvasText('ca.back', 'خلف'), 'adjustSlideElementLayer(' + index + ', -1)')
          + '</div>'
          + extras
          + '</div>');
      }

      if (slideInspectorGroup === 'actions') {
        parts.push('<div class="slide-inspector-rowline slide-inspector-group" data-slide-inspector-open="actions">'
          + '<div class="slide-inspector-actions">'
          + slideInspectorButton(canvasText('ca.duplicate_element', 'تكرار'), 'duplicateSelectedSlideElements(' + index + ')')
          + slideInspectorButton(canvasText('ca.copy', 'نسخ'), 'copySelectedSlideElements(' + index + ')')
          + slideInspectorButton(canvasText('ca.paste', 'لصق'), 'pasteSlideElements(' + index + ')')
          + slideInspectorButton(canvasText('ca.group', 'مجموعة'), 'groupSelectedSlideElements(' + index + ')')
          + slideInspectorButton(canvasText('ca.ungroup', 'فك المجموعة'), 'ungroupSelectedSlideElements(' + index + ')')
          + slideInspectorButton(canvasText('ca.delete_element', 'حذف العناصر'), 'deleteSelectedSlideElements(' + index + ')')
          + '</div></div>');
      }

      parts.push('</div>');
      host.innerHTML = parts.join('');
    }

    function closeSlideInspector() {
      slideInspectorGroup = '';
      document.querySelectorAll('.slide-inline-inspector').forEach(host => {
        host.innerHTML = '';
        host.hidden = true;
      });
    }

    function hasSlideAspectLock(index) {
      const session = canvasSession(index);
      return !!(session && session.aspectLock);
    }

    function toggleSlideAspectLock(index) {
      const session = canvasSession(index);
      if (!session) return;
      session.aspectLock = !session.aspectLock;
      renderSlideInspector(index);
    }

    function setSlideSelectionFontSize(index, size) {
      setSlideSelectionStyle(index, el => { el.style.fontSize = Math.max(8, Math.min(200, size)) + 'px'; });
    }

    function setSlideSelectionFontWeight(index, weight) {
      setSlideSelectionStyle(index, el => { el.style.fontWeight = weight >= 600 ? '700' : '400'; });
    }

    function setSlideSelectionTextAlign(index, value) {
      setSlideSelectionStyle(index, el => { el.style.textAlign = value; });
    }

    function setSlideSelectionLineHeight(index, value) {
      setSlideSelectionStyle(index, el => { el.style.lineHeight = String(Math.max(0.8, Math.min(3, value))); });
    }

    function setSlideSelectionLetterSpacing(index, value) {
      setSlideSelectionStyle(index, el => { el.style.letterSpacing = Math.max(-5, Math.min(20, value)) + 'px'; });
    }

    function setSlideSelectionTextColor(index, value) {
      setSlideSelectionStyle(index, el => { el.style.color = value; });
    }

    function setSlideSelectionTextShadow(index) {
      const session = canvasSession(index);
      const stage = canvasStageFor(index);
      if (!session || !stage) return;
      const pairs = slideSelectedTargets(stage, session);
      const primary = pairs[0] ? pairs[0].target : null;
      if (!primary) return;
      if (slideElementShadowLevel(primary, 'textShadow') !== 'none') {
        setSlideSelectionStyle(index, el => { el.style.textShadow = 'none'; });
      } else {
        setSlideSelectionStyle(index, el => { el.style.textShadow = '0 2px 6px rgba(7,24,44,.28)'; });
      }
    }

    function setSlideSelectionImageFit(index, value) {
      setSlideSelectionStyle(index, el => {
        el.style.objectFit = value === 'contain' ? 'contain' : 'cover';
      });
    }

    function setSlideSelectionBorderRadius(index, value) {
      setSlideSelectionStyle(index, el => { el.style.borderRadius = Math.max(0, value) + 'px'; });
    }

    function setSlideSelectionFill(index, value) {
      setSlideSelectionStyle(index, el => { el.style.backgroundColor = value; });
    }

    function setSlideSelectionBorderColor(index, value) {
      setSlideSelectionStyle(index, el => { el.style.borderColor = value; });
    }

    function setSlideSelectionBorderWidth(index, value) {
      setSlideSelectionStyle(index, el => {
        el.style.borderStyle = Number(value) > 0 ? 'solid' : '';
        el.style.borderWidth = Math.max(0, value) + 'px';
      });
    }

    function attachSlideRotationHandle(stage, index, slide, target, x, y, w) {
      const handle = document.createElement('div');
      handle.className = 'slide-rotation-handle';
      handle.title = canvasText('ca.rotation', 'الدوران');
      handle.style.left = Math.max(0, Math.min(x + w / 2 - 9, 1280 - 18)) + 'px';
      handle.style.top = Math.max(0, y - 30) + 'px';
      slide.appendChild(handle);
      handle.addEventListener('pointerdown', event => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        const rect = target.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;
        const startAngle = Math.atan2(event.clientY - centerY, event.clientX - centerX);
        const baseRotation = parseFloat(target.style.rotate) || 0;
        const onMove = moveEvent => {
          const angle = Math.atan2(moveEvent.clientY - centerY, moveEvent.clientX - centerX);
          const degrees = Math.round(baseRotation + (angle - startAngle) * 180 / Math.PI);
          target.style.rotate = degrees + 'deg';
        };
        const onUp = () => {
          window.removeEventListener('pointermove', onMove, true);
          window.removeEventListener('pointerup', onUp, true);
          const value = parseFloat(target.style.rotate) || 0;
          setSlideSelectionRotation(index, value);
          const path = slideElementPath(slide, target);
          if (path) selectSlideElement(stage, index, target, path);
        };
        window.addEventListener('pointermove', onMove, true);
        window.addEventListener('pointerup', onUp, true);
      });
    }

    document.addEventListener('wf:lang', () => {
      try {
        const session = canvasSession(activeSlideIndex);
        if (session) renderSlideInspector(activeSlideIndex);
      } catch (error) { /* ignore */ }
    });
