/* 15-slide-edit-chat.js - index.html lines 24651-26147, shared global scope, classic scripts in order */

    function addSlideImageFromDevice(index, file) {
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html || !file) return;
      if (!getSlideEditSession(index)) return;
      if (!String(file.type || '').startsWith('image/')) { toast('الملف المختار ليس صورة'); return; }
      if (file.size > 4 * 1024 * 1024) { toast('حجم الصورة كبير (الحد 4 ميجا)'); return; }
      const reader = new FileReader();
      reader.onload = () => {
        const url = String(reader.result || '');
        if (!url.startsWith('data:image/')) { toast('تعذر قراءة الصورة'); return; }
        const current = tenantSlidesData[index];
        if (!current || !current.html || !getSlideEditSession(index)) return;
        const rawDoc = new DOMParser().parseFromString(current.html, 'text/html');
        const rawRoot = rawDoc.querySelector('.slide');
        if (!rawRoot) return;
        pushSlideEditHistory(index);
        const wrap = rawDoc.createElement('div');
        wrap.setAttribute('data-slide-imagebox', '1');
        wrap.setAttribute('style', 'position:absolute;top:180px;right:390px;width:500px;'
          + 'box-sizing:border-box;z-index:5;');
        const img = rawDoc.createElement('img');
        img.setAttribute('src', url);
        img.setAttribute('alt', '');
        img.setAttribute('style', 'display:block;width:100%;height:auto;border-radius:10px;');
        wrap.appendChild(img);
        rawRoot.appendChild(wrap);
        current.html = rawRoot.outerHTML;
        tenantProjectData.tenantSlidesData = tenantSlidesData;
        touchSlideEditSession(index);
        triggerAutoSaveDraft();
        refreshSingleSlideCard(index);
        toast('تمت إضافة الصورة');
      };
      reader.onerror = () => toast('تعذر قراءة الصورة');
      reader.readAsDataURL(file);
    }

    function onSlideEditableFocus(event) {
      const el = event.target;
      const stage = el && el.closest ? el.closest('.tenant-slide-stage') : null;
      const card = el && el.closest ? el.closest('.ge-slide-card') : null;
      if (!stage || !card) return;
      const index = Number(String(card.id || '').replace('slide-card-', ''));
      if (!Number.isInteger(index)) return;
      if (!getSlideEditSession(index)) return;
      const root = stage.querySelector('.slide');
      const path = root ? slideElementPath(root, el) : null;
      if (path) selectSlideElement(stage, index, el, path);
    }

    function toggleSlideInlineEditing(index) {
      slideInlineEditStates[index] = !slideInlineEditStates[index];
      renderTenantSlides();
      toast(slideInlineEditStates[index] ? 'تم تفعيل التعديل المباشر لهذه الشريحة' : 'تم إيقاف التعديل المباشر');
    }

    function commitSlideInlineEdit(stage, index, editedEl) {
      const slide = stage.querySelector('.slide');
      const slideData = tenantSlidesData[index];
      if (!slide || !slideData || !slideData.html) return;

      const doc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = doc.querySelector('.slide');
      if (!rawRoot) return;

      const liveNodes = collectSlideTextNodes(slide);
      const rawNodes = collectSlideTextNodes(rawRoot);
      // Structure mismatch means we cannot map text safely — keep the original HTML.
      if (liveNodes.length !== rawNodes.length) return;

      let changed = false;
      liveNodes.forEach((node, i) => {
        if (editedEl && !editedEl.contains(node)) return;
        if (rawNodes[i].nodeValue !== node.nodeValue) {
          rawNodes[i].nodeValue = node.nodeValue;
          changed = true;
        }
      });
      if (!changed) return;

      pushSlideEditHistory(index);
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      renderTenantSlidesSidebar();
      triggerAutoSaveDraft();
      toast('تم تعديل النص. اضغط "حفظ التعديلات" للحفظ النهائي.');
      autoFitSlideContent(stage);
    }

    function setSlidesEditorInfo(title, count) {
      const editorInfo = document.getElementById('slidesEditorInfo');
      if (!editorInfo) return;
      const name = String(title || '').trim();
      editorInfo.innerHTML = name ? '<span>عرض:</span> ' + escapeHtml(name) + ' | <span>' + (count || 0) + '</span> <span>شريحة</span>' : '';
    }

    // Opening a saved presentation leaves its slides, its thumbnails and its title in this page's
    // markup, and nothing else cleared them: a new project file that reached the slides page then
    // displayed the previous proposal until the first generated slide overwrote it.
    function clearSlidesEditorSurface() {
      const wrap = document.getElementById('tenantSlidesMain');
      if (wrap) wrap.innerHTML = '';
      const sidebar = document.getElementById('tenantSlidesSidebar');
      if (sidebar) sidebar.innerHTML = '';
      setSlidesEditorInfo('', 0);
    }

    // The stage while a new deck is being planned: empty, with the status only. The previously
    // generated slides stay in memory and in the saved file until the new ones replace them.
    function clearTenantSlidesStage(statusText) {
      clearSlidesEditorSurface();
      const wrap = document.getElementById('tenantSlidesMain');
      if (!wrap) return;
      wrap.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;' +
        'min-height:380px;padding:48px 24px;text-align:center;gap:12px;background:#fff;border:1px dashed var(--line);' +
        'border-radius:16px;margin:32px auto;max-width:540px">' +
        '<div style="font-size:18px;font-weight:700;color:var(--txt)">' + escapeHtml(statusText || '') + '</div>' +
        '<div class="tenant-hint">تحليل بيانات المشروع وتحديد عدد الشرائح</div>' +
        '</div>';
    }

    function renderTenantSlideResumeNotice(wrap) {
      if (!wrap || !hasResumableTenantSlideGeneration()) return;
      const remaining = Math.max(0, (tenantSlidePlan?.slides?.length || 0) - (tenantSlidesData?.length || 0));
      const notice = document.createElement('div');
      notice.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 18px;margin:0 auto 20px;max-width:960px;background:#fff8ed;border:1px solid #e7c98a;border-radius:12px;color:#6b4d16;';
      notice.innerHTML = '<div><div style="font-weight:800"><span>التوليد متوقف مؤقتًا</span></div>' +
        '<div style="font-size:13px;margin-top:4px"><span>تم حفظ</span> ' + escapeHtml(String(tenantSlidesData.length)) +
        ' <span>شريحة</span> <span>ويتبقى</span> ' + escapeHtml(String(remaining)) + ' <span>شرائح</span>.</div></div>' +
        '<button type="button" class="btn primary" style="background:#1a4d6f;color:#fff;white-space:nowrap" onclick="resumeTenantSlideGeneration()">استكمال التوليد</button>';
      wrap.appendChild(notice);
    }

    function renderTenantSlides() {
      const wrap = document.getElementById('tenantSlidesMain');
      if (!wrap) return;
      // A running generation owns the surface: its cards are skeletons, live
      // partial previews and committed slides keyed by plan index, while
      // tenantSlidesData only holds the committed prefix. Rebuilding here would
      // wipe the in-flight cards and flash the deck away mid-run.
      if (isGeneratingTenantSlides) return;
      // Manual edit flows (تعديل/اعتماد/تراجع/تقدم/الغاء) re-render the whole list.
      // Clearing the container resets scrollTop to 0, which looked like a 3-4 slide
      // jump. Preserve the exact pixel so the view stays fixed on the same slide.
      const savedScrollTop = wrap.scrollTop;
      renumberTenantSlides();
      try { syncSlideEditSessionsAfterRender(); } catch (err) {}
      // If branding hasn't loaded yet (failed/slow earlier), retry it and re-render
      // when it arrives so the real logo replaces the sample one automatically.
      if (!tenantBranding && !renderTenantSlides._brandingRetry) {
        renderTenantSlides._brandingRetry = true;
        loadTenantBranding().finally(() => {
          renderTenantSlides._brandingRetry = false;
          if (tenantBranding) renderTenantSlides();
        });
      }
      wrap.innerHTML = '';

      // Cancel any pending batch render from a previous call
      if (renderTenantSlides._raf) cancelAnimationFrame(renderTenantSlides._raf);
      renderTenantSlides._batchTimer && clearTimeout(renderTenantSlides._batchTimer);

      const slides = tenantSlidesData;
      if (!slides.length) {
        wrap.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:380px;padding:48px 24px;text-align:center;gap:16px;background:#fff;border:1px dashed var(--line);border-radius:16px;margin:32px auto;max-width:540px">' +
          '<div style="font-size:18px;font-weight:700;color:var(--txt)">لم يتم توليد شرائح هذا العرض بعد</div>' +
          '<button type="button" class="btn primary" style="background:#1a4d6f;color:#fff;padding:10px 32px;font-size:15px;font-weight:700;margin-top:8px" onclick="directGenerateProposalFile()">توليد العرض الآن</button>' +
          '</div>';
        renderTenantSlideResumeNotice(wrap);
        renderTenantSlidesSidebar();
        renderTenantSlidesDesignerChat();
        return;
      }

      renderTenantSlideResumeNotice(wrap);

      // Phase 1: create lightweight skeletons instantly (no heavy processing)
      const containers = [];
      slides.forEach((s, i) => {
        const container = document.createElement('div');
        container.className = 'ge-slide-card' + (i === activeSlideIndex ? ' active-slide' : '');
        container.id = 'slide-card-' + i;
        container.style.cssText = 'margin-bottom:24px; position:relative;';
        container.onclick = () => selectTenantSlide(i);
        if (hasPermission('create_presentation')) {
          const editControls = document.createElement('div');
          editControls.className = 'ge-slide-edit-controls';
          const editSession = getSlideEditSession(i);
          slideInlineEditStates[i] = !!editSession;
          slideElementEditStates[i] = !!editSession;
          editControls.innerHTML = slideEditToolbarHTML(i);
          wireSlideEditControls(editControls, i);
          container.appendChild(editControls);
        }
        const stage = document.createElement('div');
        stage.className = 'tenant-slide-stage';
        stage.style.setProperty('--stage-w', '960px');
        stage.style.setProperty('--stage-h', '540px');
        stage.style.setProperty('--slide-scale', '0.75');
        stage.innerHTML = '<div class="slide" style="padding:40px;font-size:14px;color:#999;background:#fafafa;">جاري التحميل...</div>';
        container.appendChild(stage);
        wrap.appendChild(container);
        containers.push({ container, stage, slide: s, index: i });
      });

      // Instant restore (no smooth animation) so the view does not visibly move.
      try {
        wrap.style.scrollBehavior = 'auto';
        wrap.scrollTop = savedScrollTop;
        wrap.style.scrollBehavior = '';
      } catch (err) {
        try { wrap.scrollTop = savedScrollTop; } catch (err2) {}
      }

      renderTenantSlidesSidebar();
      renderTenantDesignerChat();
      setTimeout(tgrRefit, 0);

      // Phase 2: batch-process heavy slide rendering off the main-thread bottleneck
      const BATCH = 4;
      let cursor = 0;
      function processBatch() {
        const end = Math.min(cursor + BATCH, containers.length);
        for (let j = cursor; j < end; j++) {
          const { stage, slide: s, index: i } = containers[j];
          const slideHtml = processSlideHtmlClient(s.html, s.type);
          stage.innerHTML = slideHtml || '<div class="slide" style="padding:40px;font-size:24px;background:#fff">' + escapeHtml(s.title || '') + '</div>';
          if (!stage.querySelector('.slide')) {
            stage.innerHTML = '<div class="slide" style="padding:40px;font-size:24px;background:#fff">' + escapeHtml(s.title || '') + '</div>';
          }
          autoFitSlideContent(stage);
          repairSlideTextContrast(stage);
          enableSlideInlineEditing(stage, i);
          enableSlideElementDragging(stage, i);
          restoreSlideEditSelection(stage, i);
        }
        cursor = end;
        if (cursor < containers.length) {
          renderTenantSlides._batchTimer = setTimeout(processBatch, 0);
        }
      }
      renderTenantSlides._batchTimer = setTimeout(processBatch, 0);
    }
    function renderTenantSlidesDesignerChat() { renderTenantDesignerChat(); }

    function moveTenantSlide(fromIdx, toIdx) {
      if (fromIdx < 0 || fromIdx >= tenantSlidesData.length) return;
      if (toIdx < 0 || toIdx >= tenantSlidesData.length || fromIdx === toIdx) return;
      beginPresentationUndoChange();
      const [moved] = tenantSlidesData.splice(fromIdx, 1);
      tenantSlidesData.splice(toIdx, 0, moved);
      renumberTenantSlides();
      renderTenantSlides();
      selectTenantSlide(toIdx);
      triggerAutoSaveDraft();
      toast('تم نقل الشريحة ' + (fromIdx + 1) + ' إلى الموقع ' + (toIdx + 1) + ' بنجاح');
    }

    function renderTenantSlidesSidebar(force) {
      const sidebar = document.getElementById('tenantSlidesSidebar');
      if (!sidebar) return;
      // Mid-generation the sidebar holds plan thumbnails keyed thumb-slide-i;
      // rebuilding it from the committed prefix would drop the in-flight ones.
      if (isGeneratingTenantSlides && !force) return;
      sidebar.innerHTML = '';

      tenantSlidesData.forEach((s, i) => {
        const thumb = document.createElement('div');
        thumb.className = 'ge-thumb' + (i === activeSlideIndex ? ' active' : '');
        thumb.onclick = () => selectTenantSlide(i);

        const moveUpBtn = i > 0 ? '<button type="button" class="ge-thumb-move" title="تحريك لأعلى" aria-label="تحريك لأعلى" onclick="event.stopPropagation(); moveTenantSlide(' + i + ', ' + (i - 1) + ')">أعلى</button>' : '';
        const moveDownBtn = i < tenantSlidesData.length - 1 ? '<button type="button" class="ge-thumb-move" title="تحريك لأسفل" aria-label="تحريك لأسفل" onclick="event.stopPropagation(); moveTenantSlide(' + i + ', ' + (i + 1) + ')">أسفل</button>' : '';
        const regenerateBtn = hasPermission('create_presentation')
          ? '<button type="button" class="ge-thumb-regenerate" title="إعادة توليد هذه الشريحة فقط" aria-label="إعادة توليد هذه الشريحة فقط"' +
            ((isGeneratingTenantSlides || isRegeneratingTenantSlide) ? ' disabled' : '') +
            ' onclick="event.stopPropagation(); regenerateTenantSlide(' + i + ')">إعادة توليد</button>'
          : '';
        const deleteBtn = hasPermission('create_presentation') && tenantSlidesData.length > 1
          ? '<button type="button" class="ge-thumb-delete" title="حذف الشريحة" aria-label="حذف الشريحة" onclick="event.stopPropagation(); deleteSlide(' + i + ')">حذف</button>'
          : '';

        thumb.innerHTML = '<span class="ge-thumb-num">' + (i + 1) + '</span>' +
          '<span class="ge-thumb-title" title="' + escapeHtml(s.title || '') + '">' + escapeHtml(s.title || 'شريحة بدون عنوان') + '</span>' +
          '<div class="ge-thumb-actions">' + moveUpBtn + moveDownBtn + regenerateBtn + deleteBtn + '</div>';
        sidebar.appendChild(thumb);
      });
    }

    let isProgrammaticScrolling = false;

    function normalizeArabicDigits(text) {
      if (!text) return '';
      return text.replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));
    }

    function detectSlideIndexesFromMessage(text) {
      if (!text || !tenantSlidesData.length) return [];
      const normalized = normalizeArabicDigits(text.trim().toLowerCase());
      const count = tenantSlidesData.length;
      const foundIndexes = [];

      const wordMap = [
        { phrase: 'الحادية عشر', num: 11 }, { phrase: 'الحاديه عشر', num: 11 },
        { phrase: 'الثانية عشر', num: 12 }, { phrase: 'الثانيه عشر', num: 12 },
        { phrase: 'الثالثة عشر', num: 13 }, { phrase: 'الثالثه عشر', num: 13 },
        { phrase: 'الرابعة عشر', num: 14 }, { phrase: 'الرابعه عشر', num: 14 },
        { phrase: 'الخامسة عشر', num: 15 }, { phrase: 'الخامسه عشر', num: 15 },
        { phrase: 'السادسة عشر', num: 16 }, { phrase: 'السادسه عشر', num: 16 },
        { phrase: 'السابعة عشر', num: 17 }, { phrase: 'السابعه عشر', num: 17 },
        { phrase: 'الثامنة عشر', num: 18 }, { phrase: 'الثامنه عشر', num: 18 },
        { phrase: 'التاسعة عشر', num: 19 }, { phrase: 'التاسعه عشر', num: 19 },
        { phrase: 'الأولى', num: 1 }, { phrase: 'الاولى', num: 1 }, { phrase: 'الأول', num: 1 }, { phrase: 'الاول', num: 1 },
        { phrase: 'الثانية', num: 2 }, { phrase: 'الثانيه', num: 2 }, { phrase: 'الثاني', num: 2 },
        { phrase: 'الثالثة', num: 3 }, { phrase: 'الثالثه', num: 3 }, { phrase: 'الثالث', num: 3 },
        { phrase: 'الرابعة', num: 4 }, { phrase: 'الرابعه', num: 4 }, { phrase: 'الرابع', num: 4 },
        { phrase: 'الخامسة', num: 5 }, { phrase: 'الخامسه', num: 5 }, { phrase: 'الخامس', num: 5 },
        { phrase: 'السادسة', num: 6 }, { phrase: 'السادسه', num: 6 }, { phrase: 'السادس', num: 6 },
        { phrase: 'السابعة', num: 7 }, { phrase: 'السابعه', num: 7 }, { phrase: 'السابع', num: 7 },
        { phrase: 'الثامنة', num: 8 }, { phrase: 'الثامنه', num: 8 }, { phrase: 'الثامن', num: 8 },
        { phrase: 'التاسعة', num: 9 }, { phrase: 'التاسعه', num: 9 }, { phrase: 'التاسع', num: 9 },
        { phrase: 'العاشرة', num: 10 }, { phrase: 'العاشره', num: 10 }, { phrase: 'العاشر', num: 10 },
        { phrase: 'العشرين', num: 20 }, { phrase: 'العشرون', num: 20 },
        { phrase: 'الثلاثين', num: 30 }, { phrase: 'الثلاثون', num: 30 }
      ];

      for (const item of wordMap) {
        if (normalized.includes(item.phrase)) {
          const idx = item.num - 1;
          if (idx >= 0 && idx < count && !foundIndexes.includes(idx)) {
            foundIndexes.push(idx);
          }
        }
      }

      // Expand bounded requests such as «الشرائح من 2 إلى 6» before parsing individual numbers.
      const rangeMatches = normalized.matchAll(/(?<!\d)(\d+)\s*(?:إلى|الى|حتى|لحد|[-–—])\s*(\d+)(?!\d)/g);
      for (const match of rangeMatches) {
        let start = Number(match[1]);
        let end = Number(match[2]);
        if (start > end) [start, end] = [end, start];
        for (let number = start; number <= end; number++) {
          const idx = number - 1;
          if (idx >= 0 && idx < count && !foundIndexes.includes(idx)) foundIndexes.push(idx);
        }
      }

      // Extract numbers following slide triggers or digit sequences (e.g., "7 و 9 و 20" or "1 و 4 و 20 و 30")
      const triggerMatch = normalized.match(/(?:الشريحة|شريحة|شريحه|شرايح|سلايد|سلايدات|رقم|الأرقام|ارقام)\s*([\d\s\,\،و]+)/);
      if (triggerMatch && triggerMatch[1]) {
        const numbers = triggerMatch[1].match(/\b\d+\b/g) || [];
        numbers.forEach(numStr => {
          const idx = parseInt(numStr, 10) - 1;
          if (idx >= 0 && idx < count && !foundIndexes.includes(idx)) {
            foundIndexes.push(idx);
          }
        });
      }

      if (!foundIndexes.length) {
        const numbers = normalized.match(/\b\d+\b/g) || [];
        numbers.forEach(numStr => {
          const idx = parseInt(numStr, 10) - 1;
          if (idx >= 0 && idx < count && !foundIndexes.includes(idx)) {
            foundIndexes.push(idx);
          }
        });
      }

      if (!foundIndexes.length) {
        tenantSlidesData.forEach((s, idx) => {
          if (!s.title) return;
          const titleNorm = s.title.toLowerCase().trim();
          if (titleNorm.length >= 3 && normalized.includes(titleNorm)) {
            if (!foundIndexes.includes(idx)) foundIndexes.push(idx);
          }
        });
      }

      return foundIndexes;
    }

    function detectSlideFromMessage(text) {
      const indexes = detectSlideIndexesFromMessage(text);
      return indexes.length ? indexes[0] : -1;
    }

    function initScrollSpy() {
      const mainWrap = document.getElementById('tenantSlidesMainWrap');
      if (!mainWrap) return;

      mainWrap.addEventListener('scroll', () => {
        if (isProgrammaticScrolling) return;

        const cards = document.querySelectorAll('.ge-slide-card');
        if (!cards.length) return;

        let closestIdx = -1;
        let minDistance = Infinity;
        const containerRect = mainWrap.getBoundingClientRect();
        const containerMid = containerRect.top + containerRect.height / 2;

        cards.forEach((card, idx) => {
          const rect = card.getBoundingClientRect();
          const cardMid = rect.top + rect.height / 2;
          const distance = Math.abs(cardMid - containerMid);
          if (distance < minDistance) {
            minDistance = distance;
            closestIdx = idx;
          }
        });

        if (closestIdx !== -1 && closestIdx !== activeSlideIndex) {
          selectTenantSlide(closestIdx, true);
        }
      });
    }

    function selectTenantSlide(index, skipScroll = false) {
      activeSlideIndex = index;
      tenantChatSlideIndex = index;

      // Update active states
      document.querySelectorAll('.ge-slide-card').forEach((card, idx) => {
        if (idx === index) card.classList.add('active-slide');
        else card.classList.remove('active-slide');
      });

      document.querySelectorAll('.ge-thumb').forEach((thumb, idx) => {
        if (idx === index) thumb.classList.add('active');
        else thumb.classList.remove('active');
      });

      if (!skipScroll) {
        // Scroll card into view inside the main preview area
        const targetCard = document.getElementById('slide-card-' + index);
        if (targetCard) {
          isProgrammaticScrolling = true;
          targetCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
          setTimeout(() => {
            isProgrammaticScrolling = false;
          }, 800);
        }
      }
    }

    function renderTenantDesignerChat() {
      const messages = document.getElementById('tenantChatMessages');
      if (!messages) return;
      if (tenantChatSlideIndex >= tenantSlidesData.length) tenantChatSlideIndex = 0;

      if (!tenantDesignerMessages.length) {
        messages.innerHTML = '<div class="tenant-hint">' + trDynamicI18n('لا توجد تعديلات بعد.') + '</div>';
        restoreDesignerChatBusyIndicator();
        updateDesignerChatStatus();
        return;
      }
      messages.innerHTML = tenantDesignerMessages.map(message => {
        const gallery = (Array.isArray(message.images) && message.images.length ? message.images : (message.image ? [message.image] : []))
          .filter(src => typeof src === 'string' && src.startsWith('data:image/'))
          .slice(0, 3);
        const galleryHtml = gallery.map(src =>
          '<button type="button" class="tenant-chat-message-image-button" data-chat-image-src="' + escapeHtml(src) + '" onclick="openTenantChatImagePreview(this.dataset.chatImageSrc)" aria-label="فتح الصورة المرفقة"><img src="' + escapeHtml(src) + '" alt="صورة مرفقة" class="tenant-chat-message-image"></button>'
        ).join('');
        return '<div class="tenant-chat-message ' + (message.role === 'user' ? 'user' : 'assistant') + '">' +
          galleryHtml +
          escapeHtml(message.content) + '</div>';
      }).join('');
      restoreDesignerChatBusyIndicator();
      messages.scrollTop = messages.scrollHeight;
      updateDesignerChatStatus();
    }
    // Chat logs are excluded from auto-translate (user/AI content), so the
    // empty state above is resolved at build time; refresh it on toggle.
    document.addEventListener('wf:lang', () => { try { renderTenantDesignerChat(); } catch (e) { /* ignore */ } });

    function detectMoveSlideCommand(text) {
      if (!text || !tenantSlidesData.length) return null;
      const normalized = normalizeArabicDigits(text.trim().toLowerCase());

      // Pattern 1: Move last slide e.g. "انقل الشريحة الأخيرة لخامسة/رقم 4"
      const lastMatch = normalized.match(/(?:انقل|حرك|غير|ضع|خلي)\s*(?:الشريحة|شريحة|سلايد)?\s*الأخيرة\s*(?:إلى|مكان|خليها|تكون|بعد|قبل|لتصبح)?\s*(?:الشريحة|شريحة|سلايد)?\s*(?:رقم\s*)?(\d+)/i);
      if (lastMatch && lastMatch[1]) {
        const fromIdx = tenantSlidesData.length - 1;
        let toIdx = parseInt(lastMatch[1], 10) - 1;
        if (fromIdx >= 0 && toIdx >= 0 && toIdx < tenantSlidesData.length && fromIdx !== toIdx) {
          return { fromIdx, toIdx };
        }
      }

      // Pattern 2: Explicit numbers e.g. "انقل الشريحة 8 وخليها رقم 4" or "حرك 8 الى 4" or "ضع 8 بعد 3"
      const numMatch = normalized.match(/(?:انقل|حرك|غير\s*موقع|غير\s*ترتيب|ضع|خالي|خلي)\s*(?:الشريحة|شريحة|سلايد)?\s*(?:رقم\s*)?(\d+)\s*(?:إلى|ليصبح|لتصبح|مكان|تكون|خليها|خليها\s*رقم|رقم|بعد|قبل)?\s*(?:الشريحة|شريحة|سلايد)?\s*(?:رقم\s*)?(\d+)/i);
      if (numMatch && numMatch[1] && numMatch[2]) {
        const fromIdx = parseInt(numMatch[1], 10) - 1;
        let toIdx = parseInt(numMatch[2], 10) - 1;
        if (normalized.includes('بعد') && !normalized.includes('قبل')) {
          toIdx = parseInt(numMatch[2], 10);
          if (fromIdx < toIdx) toIdx -= 1;
        }
        if (fromIdx >= 0 && fromIdx < tenantSlidesData.length && toIdx >= 0 && toIdx < tenantSlidesData.length && fromIdx !== toIdx) {
          return { fromIdx, toIdx };
        }
      }

      return null;
    }

    // The composer is one line that grows with the text, the way a chat behaves.
    function growTenantChatInput(input) {
      if (!input) return;
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 140) + 'px';
    }

    let tenantChatAttachedImage = null;
    let tenantChatAttachedImages = [];
    const TENANT_CHAT_IMAGE_LIMIT = 4 * 1024 * 1024;
    const TENANT_CHAT_MAX_IMAGES = 3;

    function renderTenantChatAttachment() {
      const box = document.getElementById('tenantChatAttachment');
      const name = document.getElementById('tenantChatAttachmentName');
      if (!box) return;
      const list = tenantChatAttachedImages.length ? tenantChatAttachedImages : (tenantChatAttachedImage ? [tenantChatAttachedImage] : []);
      box.hidden = !list.length;
      if (!list.length) {
        if (name) name.textContent = '';
        return;
      }
      if (name) name.textContent = list.map(item => item.name).join('، ');
    }

    function openTenantChatImagePreview(src) {
      if (!src) return;
      const previous = document.getElementById('tenantChatLightbox');
      if (previous) previous.remove();
      const modal = document.createElement('div');
      modal.id = 'tenantChatLightbox';
      modal.className = 'tenant-chat-lightbox';
      modal.innerHTML = '<div class="tenant-chat-lightbox-card">' +
        '<button type="button" class="tenant-chat-lightbox-close" aria-label="إغلاق الصورة">إغلاق</button>' +
        '<img src="' + escapeHtml(src) + '" alt="صورة مرفقة">' +
        '</div>';
      modal.addEventListener('click', event => {
        if (event.target === modal || event.target.closest('.tenant-chat-lightbox-close')) modal.remove();
      });
      document.body.appendChild(modal);
    }

    function clearTenantChatAttachment() {
      tenantChatAttachedImage = null;
      tenantChatAttachedImages = [];
      const input = document.getElementById('tenantChatImageFile');
      if (input) input.value = '';
      renderTenantChatAttachment();
    }

    // The attach button used to open the training page's file input, and the designer never
    // received the image: the picked file was only ever read by the training chat.
    function attachTenantChatImage(input) {
      const picked = input && input.files ? Array.from(input.files).slice(0, TENANT_CHAT_MAX_IMAGES) : [];
      if (!picked.length) return;
      for (const file of picked) {
        if (!String(file.type || '').startsWith('image/')) {
          toast('الملف ليس صورة');
          clearTenantChatAttachment();
          return;
        }
        if (file.size > TENANT_CHAT_IMAGE_LIMIT) {
          toast('حجم الصورة أكبر من 4 م.ب');
          clearTenantChatAttachment();
          return;
        }
      }
      const reads = picked.map(file => new Promise(resolve => {
        const reader = new FileReader();
        reader.onload = () => resolve({ name: file.name, dataUri: String(reader.result || '') });
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(file);
      }));
      Promise.all(reads).then(results => {
        const valid = results.filter(item => item && String(item.dataUri || '').startsWith('data:image/'));
        if (!valid.length) {
          toast('تعذر قراءة الصورة');
          clearTenantChatAttachment();
          return;
        }
        tenantChatAttachedImages = valid.slice(0, TENANT_CHAT_MAX_IMAGES);
        tenantChatAttachedImage = tenantChatAttachedImages[0] || null;
        renderTenantChatAttachment();
      });
    }

    // The server compresses the older turns into one memory string and reports which slides the
    // conversation is on; both are kept here and travel with the file, so a reload does not reset
    // the conversation to «أي شريحة؟».
    function applyDesignerChatMemory(reply) {
      if (!reply || typeof reply !== 'object') return;
      if (typeof reply.memory === 'string') tenantDesignerChatMemory = reply.memory.slice(0, 4000);
      if (Array.isArray(reply.focusIndexes) && reply.focusIndexes.length) {
        tenantChatFocusIndexes = reply.focusIndexes
          .map(value => Number(value))
          .filter(value => Number.isInteger(value) && value >= 1)
          .slice(0, 30);
      }
      if (tenantDesignerMessages.length > DESIGNER_CHAT_HISTORY_KEPT * 2) {
        tenantDesignerMessages = tenantDesignerMessages.slice(-DESIGNER_CHAT_HISTORY_KEPT * 2);
      }
    }

    function applyDesignerChatHistory(reply) {
      if (!reply || !Array.isArray(reply.chatHistory)) return;
      const localByKey = new Map();
      tenantDesignerMessages.forEach(item => {
        const key = String(item.role || 'assistant') + '\u0000' + String(item.content || '');
        const queue = localByKey.get(key) || [];
        queue.push(item);
        localByKey.set(key, queue);
      });
      tenantDesignerMessages = reply.chatHistory
        .filter(item => item && typeof item.content === 'string')
        .map(item => {
          const key = String(item.role || 'assistant') + '\u0000' + String(item.content || '');
          const queue = localByKey.get(key) || [];
          const local = queue.shift();
          const localGallery = Array.isArray(local?.images) && local.images.length ? local.images : (local?.image ? [local.image] : []);
          return {
            role: item.role === 'user' ? 'user' : 'assistant',
            content: String(item.content || '').slice(0, 2000),
            slides: Array.isArray(item.slides) ? item.slides : [],
            image: local?.image || '',
            images: localGallery.filter(src => typeof src === 'string').slice(0, 3)
          };
        });
    }

    function newTenantDesignerRequestId() {
      if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return window.crypto.randomUUID();
      }
      return 'designer-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 14);
    }

    function isTransientDesignerChatResponse(result) {
      return result?.error_code === 'CLIENT_REQUEST_TIMEOUT'
        || String(result?.error || '').startsWith('Network error');
    }

    function isTerminalDesignerChatJob(result) {
      const status = String(result?.status || '');
      return status === 'completed' || status === 'failed'
        || status === 'not_found' || status === 'stale';
    }

    async function requestTenantDesignerChat(payload, indicator, resumedJob = null) {
      const workspaceKey = resumedJob?.workspaceKey || designerChatWorkspaceKey();
      const requestId = resumedJob?.jobId || newTenantDesignerRequestId();
      const metadata = {
        jobId: String(requestId),
        workspaceKey: String(workspaceKey || ''),
        presentationId: resumedJob?.presentationId || tenantPresentationId || null,
        draftId: resumedJob?.draftId || tenantProjectData?.draftId || tenantProjectData?.draft_id || null,
        message: resumedJob?.message || payload?.message || '',
        target: resumedJob?.target || payload?.target || 'auto',
        scope: resumedJob?.scope || payload?.scope || payload?.target || 'auto',
        indexes: Array.isArray(resumedJob?.indexes) ? resumedJob.indexes
          : (Array.isArray(payload?.indexes) ? payload.indexes : []),
        slideIndex: Number(resumedJob?.slideIndex ?? payload?.slideIndex ?? 0),
        hadAttachment: !!(resumedJob?.hadAttachment || payload?.attachedImage || (Array.isArray(payload?.attachedImages) && payload.attachedImages.length)),
        workspaceSignature: String(
          resumedJob?.workspaceSignature || designerChatWorkspaceSignature()),
        startedAt: Number(resumedJob?.startedAt || Date.now()),
        updatedAt: Date.now(),
        status: String(resumedJob?.status || 'queued')
      };
      if (!metadata.workspaceKey) {
        return {
          success: false,
          status: 'failed',
          error: 'تعذر ربط مهمة تعديل العرض بالمشروع الحالي.',
          failureReason: 'workspace_missing',
          _designerJob: metadata
        };
      }

      const jobPath = '/api/designer-chat/jobs/' + encodeURIComponent(metadata.jobId);
      const queuePayload = payload ? { ...payload, requestId: metadata.jobId } : null;
      persistTenantDesignerJob(metadata);
      if (!resumedJob) {
        // localStorage is shared by tabs. A short settle window lets the last workspace claim win,
        // so two simultaneous clicks do not launch two differently keyed AI jobs.
        await new Promise(resolve => setTimeout(resolve, 80));
        const activeClaim = currentTenantDesignerJob();
        if (activeClaim && String(activeClaim.jobId) !== metadata.jobId) {
          return {
            success: false,
            status: 'superseded',
            error: 'توجد مهمة تعديل أخرى نشطة لنفس العرض.',
            failureReason: 'workspace_job_superseded',
            _designerJob: metadata
          };
        }
      }

      async function submitOrRecoverJob() {
        if (!queuePayload) return null;
        return apiWithTimeout(
          'POST', '/api/designer-chat/jobs', queuePayload, 30000,
          'تعذر تأكيد تسجيل مهمة تعديل العرض مؤقتًا.'
        );
      }

      if (!resumedJob) {
        const queued = await submitOrRecoverJob();
        if (queued?.jobId) {
          metadata.jobId = String(queued.jobId);
          metadata.status = String(queued.status || 'queued');
          metadata.updatedAt = Date.now();
          persistTenantDesignerJob(metadata);
        } else if (!isTransientDesignerChatResponse(queued)) {
          return {
            ...(queued || {}),
            success: false,
            status: 'failed',
            error: queued?.error || 'تعذر تسجيل مهمة تعديل العرض.',
            _designerJob: metadata
          };
        }
      }

      const pollingStarted = Date.now();
      const maxWaitMs = 60 * 60 * 1000;
      let retryDelay = 2000;
      let queueRecoveryAttempts = 0;
      let lastExecutionTarget = '';
      while (Date.now() - pollingStarted < maxWaitMs) {
        await new Promise(resolve => setTimeout(resolve, retryDelay));
        const result = await apiWithTimeout(
          'GET', jobPath + '?includeResult=0', null,
          30000, 'تعذر تحديث حالة تعديل العرض مؤقتًا.'
        );
        if (isTransientDesignerChatResponse(result)) {
          retryDelay = Math.min(10000, Math.round(retryDelay * 1.5));
          if (tenantDesignerJobMatchesWorkspace(metadata)) {
            updateDesignerChatBusy(
              tenantDesignerChatBusy?.progress || 5,
              'مهمة تعديل العرض مستمرة وجار استعادة الاتصال...'
            );
          }
          continue;
        }

        if (!tenantDesignerServerJobMatches(metadata, result)) {
          return {
            success: false,
            status: 'failed',
            error: 'تعذر تطبيق نتيجة مهمة لا تخص العرض الحالي.',
            failureReason: 'job_workspace_mismatch',
            _designerJob: metadata
          };
        }

        const status = String(result?.status || '');
        if (result?.stale && (status === 'queued' || status === 'running')) {
          return {
            ...(result || {}),
            success: false,
            status: 'stale',
            error: 'توقفت تحديثات مهمة تعديل العرض على الخادم قبل وصول نتيجة مؤكدة.',
            failureReason: 'job_stale',
            _designerJob: metadata
          };
        }
        if (status === 'not_found' && queuePayload && queueRecoveryAttempts < 3) {
          queueRecoveryAttempts += 1;
          const recovered = await submitOrRecoverJob();
          if (recovered?.jobId || isTransientDesignerChatResponse(recovered)) {
            retryDelay = Math.min(10000, 2000 * (queueRecoveryAttempts + 1));
            continue;
          }
          return {
            ...(recovered || result || {}),
            success: false,
            status: 'failed',
            error: recovered?.error || result?.error || 'تعذر استعادة مهمة تعديل العرض.',
            _designerJob: metadata
          };
        }

        metadata.status = status || metadata.status;
        metadata.updatedAt = Date.now();
        persistTenantDesignerJob(metadata);
        retryDelay = 2000;
        const progress = Math.max(1, Math.min(99, Number(result?.progress || 5)));
        if (tenantDesignerJobMatchesWorkspace(metadata)) {
          updateDesignerChatBusy(progress, result?.message || 'جاري تنفيذ تعديل العرض...');
          // Navigate only after the executor starts editing a model-selected slide.
          // Deduplicate polling events so manual scrolling is not constantly undone.
          if (result?.phase === 'editing' && Number.isInteger(result.activeSlideIndex)
            && result.activeSlideIndex >= 0 && result.activeSlideIndex < tenantSlidesData.length) {
            const executionTarget = String(result.actionNumber) + ':' + result.activeSlideIndex;
            if (executionTarget !== lastExecutionTarget) {
              lastExecutionTarget = executionTarget;
              selectTenantSlide(result.activeSlideIndex);
            }
          }
          if (indicator && document.contains(indicator)) {
            setInlineLoaderProgress(indicator, progress, result?.message || 'جاري تنفيذ تعديل العرض...');
          }
        }

        if (status === 'completed') {
          while (Date.now() - pollingStarted < maxWaitMs) {
            const completed = await apiWithTimeout(
              'GET', jobPath + '?includeResult=1', null,
              120000, 'اكتملت المهمة وتعذر استلام نتيجتها مؤقتًا.'
            );
            if (isTransientDesignerChatResponse(completed)) {
              if (tenantDesignerJobMatchesWorkspace(metadata)) {
                updateDesignerChatBusy(99, 'اكتمل التعديل وجار استلام النتيجة...');
              }
              await new Promise(resolve => setTimeout(resolve, retryDelay));
              retryDelay = Math.min(10000, Math.round(retryDelay * 1.5));
              continue;
            }
            if (!tenantDesignerServerJobMatches(metadata, completed)) {
              return {
                success: false,
                status: 'failed',
                error: 'تعذر تطبيق نتيجة مهمة لا تخص العرض الحالي.',
                failureReason: 'job_workspace_mismatch',
                _designerJob: metadata
              };
            }
            if (!completed?.data) {
              return {
                ...(completed || {}),
                success: false,
                status: 'failed',
                error: completed?.error || 'اكتملت المهمة دون نتيجة قابلة للتطبيق.',
                failureReason: completed?.failureReason || 'result_missing',
                _designerJob: metadata
              };
            }
            completed._designerJob = metadata;
            return completed;
          }
        }
        if (status === 'failed' || status === 'not_found') {
          result._designerJob = metadata;
          return result;
        }
      }
      return {
        success: false,
        status: 'waiting',
        error: 'استغرق تعديل العرض وقتًا أطول من ساعة ولم تصل نتيجة مؤكدة.',
        error_code: 'DESIGNER_JOB_WAIT_TIMEOUT',
        _designerJob: metadata
      };
    }

    function applyTenantDesignerChatResult(data, message, input = null) {
      const reply = data && data.data ? data.data : null;
      if (!data?.success || !reply) {
        tenantDesignerMessages.push({
          role: 'assistant',
          content: (data && data.error) || 'تعذر تنفيذ الطلب. لم يتم تغيير العرض.'
        });
        tenantProjectData.designerChat = designerChatPersistence();
        renderTenantDesignerChat();
        triggerAutoSaveDraft();
        return false;
      }

      applyDesignerChatHistory(reply);
      applyDesignerChatMemory(reply);

      // The designer asked instead of guessing: show the question, change nothing, keep the answer
      // in the input's turn. Guessing and then editing wrongly is worse than one question.
      if (reply.action === 'ask' || reply.action === 'chat_only') {
        if (!Array.isArray(reply.chatHistory)) {
          tenantDesignerMessages.push({
            role: 'assistant',
            content: reply.response || 'تعذر تحديد التعديل دون معلومات إضافية.',
            slides: tenantChatFocusIndexes.slice()
          });
        }
        tenantProjectData.designerChat = designerChatPersistence();
        renderTenantDesignerChat();
        triggerAutoSaveDraft();
        if (input) input.focus();
        return true;
      }

      checkpointPresentationUndo();
      const undoSlidesBefore = JSON.stringify(tenantSlidesData);
      // The executor owns structural positions; do not reinterpret the message
      // and move its last slide a second time after applying the returned workspace.
      if (reply.action === 'add_slide' || reply.action === 'insert_slide') {
        const insertAfter = reply.insertAfterIndex !== undefined ? Number(reply.insertAfterIndex) : (tenantChatSlideIndex + 1);
        const insertIdx = Math.max(0, Math.min(insertAfter, tenantSlidesData.length));
        const newSlide = {
          title: reply.title || 'شريحة جديدة',
          html: reply.html,
          type: reply.type || 'content',
          section_key: reply.sectionKey || reply.section_key || '',
          content_source: reply.contentSource || reply.content_source || ''
        };
        tenantSlidesData.splice(insertIdx, 0, newSlide);
        // New slides start without a watermark; the user enables it per
        // slide from the edit toolbar or the designer chat.
        tenantProjectData.tenantSlidesData = tenantSlidesData;
        selectTenantSlide(insertIdx);
      } else if (Array.isArray(reply.slidesData)) {
        const oldLength = tenantSlidesData.length;
        // Guard against a model reply that silently drops slides: entries without a
        // slide root would render as broken cards, and a shorter deck without a delete
        // request means slides were lost. Neither is applied quietly.
        const incoming = reply.slidesData.filter(item => item && typeof item.html === 'string' && containsSlideRoot(item.html));
        const deleteIntent = Array.isArray(reply.actions) && reply.actions.some(action =>
          action?.status === 'success' && ['delete_slide', 'remove_slide', 'merge_slides', 'combine_slides'].includes(action.tool));
        if (!incoming.length || incoming.length !== reply.slidesData.length) {
          tenantDesignerMessages.push({
            role: 'assistant',
            content: 'تعذر تنفيذ الطلب. لم يتم تغيير العرض.',
            slides: tenantChatFocusIndexes.slice()
          });
          tenantProjectData.designerChat = designerChatPersistence();
          renderTenantDesignerChat();
          triggerAutoSaveDraft();
          return false;
        }
        if (incoming.length < oldLength && !deleteIntent) {
          tenantDesignerMessages.push({
            role: 'assistant',
            content: 'لم يتم تطبيق التعديل لأن النتيجة أسقطت ' + (oldLength - incoming.length) + ' من ' + oldLength + ' شريحة.',
            slides: tenantChatFocusIndexes.slice()
          });
          tenantProjectData.designerChat = designerChatPersistence();
          renderTenantDesignerChat();
          triggerAutoSaveDraft();
          return false;
        }
        tenantSlidesData = incoming;
        if (tenantSlidesData.length < oldLength) {
          activeSlideIndex = Math.max(0, Math.min(activeSlideIndex, tenantSlidesData.length - 1));
          tenantChatSlideIndex = Math.max(0, Math.min(tenantChatSlideIndex, tenantSlidesData.length - 1));
        }
      }

      if (JSON.stringify(tenantSlidesData) !== undoSlidesBefore && typeof tenantPresentationProvenance !== 'undefined') {
        tenantPresentationProvenance = data.provenance || reply.provenance || tenantPresentationProvenance;
      }
      if (reply.creativeImages && typeof reply.creativeImages === 'object') {
        tenantCreativeImages = reply.creativeImages;
        tenantProjectData = { ...tenantProjectData, tenantCreativeImages };
      }
      if (!Array.isArray(reply.chatHistory)) {
        tenantDesignerMessages.push({
          role: 'assistant',
          content: reply.response || 'تم تنفيذ الطلب وتحديث العرض.',
          slides: tenantChatFocusIndexes.slice()
        });
      }
      tenantProjectData.designerChat = designerChatPersistence();
      if (!Array.isArray(reply.slidesData)) renumberTenantSlides();
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      renderTenantSlides();
      renderTenantDesignerChat();
      triggerAutoSaveDraft();
      checkpointPresentationUndo();
      return true;
    }

    async function resumeTenantDesignerChatJob() {
      const workspaceKey = designerChatWorkspaceKey();
      if (tenantDesignerChatBusy?.workspaceKey && tenantDesignerChatBusy.workspaceKey !== workspaceKey) {
        clearDesignerChatBusy(tenantDesignerChatBusy.workspaceKey);
      }
      const job = currentTenantDesignerJob();
      if (!job || !tenantDesignerJobMatchesWorkspace(job)) return;
      if (tenantDesignerChatBusy?.workspaceKey === workspaceKey) return;
      if (tenantDesignerJobPollPromise?.workspaceKey === workspaceKey) return;

      const lastTurn = tenantDesignerMessages[tenantDesignerMessages.length - 1];
      if (job.message && (!lastTurn || lastTurn.role !== 'user' || lastTurn.content !== job.message)) {
        tenantDesignerMessages.push({ role: 'user', content: job.message, slides: [] });
        tenantProjectData.designerChat = designerChatPersistence();
        triggerAutoSaveDraft();
      }
      const resumeJob = {
        ...job,
        workspaceSignature: designerChatWorkspaceSignature(),
        updatedAt: Date.now()
      };
      persistTenantDesignerJob(resumeJob);
      setDesignerChatBusy('جاري استعادة مهمة تعديل العرض...', workspaceKey);
      renderTenantDesignerChat();
      restoreDesignerChatBusyIndicator();
      const indicator = document.getElementById('tenantChatTypingIndicator');
      const input = document.getElementById('tenantChatInput');
      const recoveryPayload = resumeJob.hadAttachment ? null : {
        message: resumeJob.message,
        target: resumeJob.target || 'auto',
        scope: resumeJob.scope || resumeJob.target || 'auto',
        indexes: Array.isArray(resumeJob.indexes) ? resumeJob.indexes : [],
        history: tenantDesignerMessages.slice(0, -1).slice(-DESIGNER_CHAT_HISTORY_KEPT).map(item => ({
          role: item.role === 'user' ? 'user' : 'assistant',
          content: String(item.content || '').slice(0, 2000),
          slides: Array.isArray(item.slides) ? item.slides : []
        })),
        memory: tenantDesignerChatMemory,
        focusIndexes: tenantChatFocusIndexes,
        slideIndex: Number(resumeJob.slideIndex || 0),
        presentationId: resumeJob.presentationId || tenantPresentationId,
        projectData: buildDesignerChatProjectData(tenantProjectData),
        creativeImages: buildPresentationGenerationImages()
      };
      if (recoveryPayload && (tenantDraftDirty || !recoveryPayload.presentationId)) {
        recoveryPayload.slideHtml = tenantSlidesData[recoveryPayload.slideIndex]?.html || '';
        recoveryPayload.slideTitle = tenantSlidesData[recoveryPayload.slideIndex]?.title || '';
        recoveryPayload.slidesData = tenantSlidesData;
        recoveryPayload.slidePlan = tenantSlidePlan;
      }
      const promise = requestTenantDesignerChat(recoveryPayload, indicator, resumeJob);
      const pollRecord = { workspaceKey, promise };
      tenantDesignerJobPollPromise = pollRecord;
      try {
        const data = await promise;
        if (!tenantDesignerJobMatchesWorkspace(resumeJob)) return;
        if (!tenantDesignerJobCanApply(resumeJob)) {
          applyTenantDesignerChatResult({
            success: false,
            status: 'failed',
            error: 'لم تُطبق النتيجة لأن العرض تغير أثناء تنفيذ المهمة.'
          }, resumeJob.message, input);
          clearTenantDesignerJob(resumeJob);
          return;
        }
        applyTenantDesignerChatResult(data, resumeJob.message, input);
        if (isTerminalDesignerChatJob(data)) clearTenantDesignerJob(resumeJob);
      } catch (error) {
        if (tenantDesignerJobMatchesWorkspace(job)) {
          applyTenantDesignerChatResult({
            success: false,
            status: 'waiting',
            error: error?.message || 'تعذر استعادة نتيجة تعديل العرض مؤقتًا.'
          }, resumeJob.message, input);
        }
      } finally {
        if (tenantDesignerJobPollPromise === pollRecord) tenantDesignerJobPollPromise = null;
        clearDesignerChatBusy(workspaceKey);
      }
    }

    async function sendTenantDesignerChat() {
      const input = document.getElementById('tenantChatInput');
      const message = input ? input.value.trim() : '';
      const attachedImage = tenantChatAttachedImage;
      const attachedGallery = (tenantChatAttachedImages.length ? tenantChatAttachedImages : (attachedImage ? [attachedImage] : []))
        .filter(item => item && String(item.dataUri || '').startsWith('data:image/'))
        .slice(0, TENANT_CHAT_MAX_IMAGES);
      if (!message) { toast('التعديل المطلوب فارغ'); return; }
      if (!tenantSlidesData.length && !tenantPresentationId) {
        toast('لا يوجد عرض مفتوح للتعديل');
        return;
      }

      const activeJob = currentTenantDesignerJob();
      if (activeJob) {
        void resumeTenantDesignerChatJob();
        return;
      }
      if (tenantDesignerChatBusy) return;
      let requestWorkspaceKey = designerChatWorkspaceKey();
      setDesignerChatBusy('جاري تجهيز بيانات المشروع...', requestWorkspaceKey);
      try {
        if (typeof collectTenantFormData === 'function' && document.getElementById('tenantProjectForm')) {
          const currentFormData = await collectTenantFormData();
          tenantProjectData = { ...tenantProjectData, ...currentFormData };
        }
      } catch (error) {
        clearDesignerChatBusy(requestWorkspaceKey);
        toast(error?.message || 'تعذر تجهيز بيانات المشروع الحالية.');
        return;
      }
      requestWorkspaceKey = designerChatWorkspaceKey();
      if (tenantDesignerChatBusy) tenantDesignerChatBusy.workspaceKey = requestWorkspaceKey;
      // Send the untouched message and conversation. A number is not a client-side
      // command, and even a slide reference does not authorize an edit or navigation.
      const targetScope = tenantChatSlideScope === 'all' ? 'all' : 'auto';
      const target1BasedIndexes = [];

      tenantDesignerMessages.push({
        role: 'user',
        content: message,
        image: attachedImage ? attachedImage.dataUri : '',
        images: attachedGallery.map(item => item.dataUri),
        slides: target1BasedIndexes
      });
      if (input) { input.value = ''; growTenantChatInput(input); }
      clearTenantChatAttachment();
      tenantProjectData.designerChat = designerChatPersistence();
      renderTenantDesignerChat();
      triggerAutoSaveDraft();

      const messagesDiv = document.getElementById('tenantChatMessages');
      updateDesignerChatBusy(5, 'جاري تجهيز الطلب...');
      restoreDesignerChatBusyIndicator();
      const indicator = document.getElementById('tenantChatTypingIndicator');
      if (messagesDiv) messagesDiv.scrollTop = messagesDiv.scrollHeight;

      // The turn carries the conversation behind it: recent turns verbatim and the older ones as
      // the memory the server compressed. A dirty workspace also carries its current slides so
      // multiple unsaved chat edits build on one another instead of reverting to the saved deck.
      const chatPayload = {
        message,
        target: targetScope,
        scope: targetScope,
        indexes: target1BasedIndexes,
        history: tenantDesignerMessages.slice(0, -1).slice(-DESIGNER_CHAT_HISTORY_KEPT).map(item => ({
          role: item.role === 'user' ? 'user' : 'assistant',
          content: String(item.content || '').slice(0, 2000),
          slides: Array.isArray(item.slides) ? item.slides : []
        })),
        memory: tenantDesignerChatMemory,
        focusIndexes: tenantChatFocusIndexes,
        slideIndex: tenantChatSlideIndex,
        presentationId: tenantPresentationId,
        projectData: buildDesignerChatProjectData(tenantProjectData),
        creativeImages: buildPresentationGenerationImages(),
        attachedImage: attachedImage ? attachedImage.dataUri : '',
        attachedImages: attachedGallery.map(item => item.dataUri)
      };
      // Once the workspace is dirty, send the in-memory copy as the source for the next turn.
      // The server must not reload the last saved presentation and discard an earlier unsaved
      // change made in this same chat session.
      if (tenantDraftDirty || !tenantPresentationId) {
        chatPayload.slideHtml = tenantSlidesData[tenantChatSlideIndex]?.html || '';
        chatPayload.slideTitle = tenantSlidesData[tenantChatSlideIndex]?.title || '';
        chatPayload.slidesData = tenantSlidesData;
        chatPayload.slidePlan = tenantSlidePlan;
      }
      let data = null;
      try {
        data = await requestTenantDesignerChat(chatPayload, indicator);
      } catch (error) {
        data = { success: false, status: 'waiting', error: error?.message || 'تعذر تنفيذ الطلب.' };
      } finally {
        clearDesignerChatBusy(requestWorkspaceKey);
      }

      const job = data?._designerJob || null;
      if (data?.status === 'superseded') {
        applyTenantDesignerChatResult(data, message, input);
        return;
      }
      if (job && !tenantDesignerJobMatchesWorkspace(job)) return;
      if (job && !tenantDesignerJobCanApply(job)) {
        applyTenantDesignerChatResult({
          success: false,
          status: 'failed',
          error: 'لم تُطبق النتيجة لأن العرض تغير أثناء تنفيذ المهمة.'
        }, message, input);
        clearTenantDesignerJob(job);
        return;
      }
      applyTenantDesignerChatResult(data, message, input);
      if (job && isTerminalDesignerChatJob(data)) clearTenantDesignerJob(job);
    }

    async function renderPresentationFontStatus() {
      const line = document.getElementById('presentationFontStatus');
      if (!line) return;
      const data = await api('GET', '/api/branding/font-status');
      const status = (data && data.status) || null;
      if (!status) { line.textContent = ''; return; }
      const scripts = status.scripts || {};
      const label = key => {
        const item = scripts[key] || {};
        return (item.font || trDynamicI18n('الافتراضي')) + (item.chosen ? '' : ' ' + trDynamicI18n('(افتراضي)'));
      };
      const renders = {
        'embedded file': 'ملف خط مضمّن مع العرض',
        'served file': 'ملف خط من الخادم',
        'google web font': 'خط ويب من Google — يحتاج اتصالًا',
        'installed name only': 'اسم خط فقط — لا يظهر إلا على جهاز مثبَّت عليه',
        'installed name only with shipped fallback':
          'خط نظام — يظهر على الأجهزة المثبَّت عليها، والعربي له خط مضمّن بديل في التصدير',
        'nothing': 'لا يوجد خط'
      }[status.renders] || status.renders;
      const arabic = label('arabic');
      const latin = label('latin');
      line.innerHTML = (arabic === latin ? '<span>المطبَّق الآن:</span> ' + escapeHtml(arabic)
        : '<span>المطبَّق الآن</span> — <span>عربي:</span> ' + escapeHtml(arabic) + ' | <span>لاتيني:</span> ' + escapeHtml(latin)) +
        ' | <span>' + escapeHtml(renders) + '</span>';
      refreshDynamicI18n(line);
    }
    document.addEventListener('wf:lang', () => { try { renderPresentationFontStatus(); } catch (e) { /* ignore */ } });

    // One entry per family: the weights of a family are applied together, so listing each weight as
    // its own choice only invited picking half a font.
    function presentationFontFamilies(data) {
      const available = (data.available || []).concat(data.custom_uploaded || []);
      const families = new Map();
      available.forEach(font => {
        const name = font.font_family || font.font_name;
        if (!name) return;
        if (!families.has(name)) families.set(name, { name, faces: [] });
        families.get(name).faces.push(font);
      });
      return Array.from(families.values());
    }

    async function openPresentationFontSettings() {
      const panel = document.getElementById('presentationFontSettingsPanel');
      const select = document.getElementById('presentationFontSelect');
      if (!panel || !select) return;
      panel.style.display = 'flex';
      if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(panel);
      select.disabled = true;
      select.innerHTML = '<option value="">جاري تحميل الخطوط...</option>';
      try {
        const data = await api('GET', '/api/branding/fonts');
        if (!data.success) throw new Error(data.error || 'Font list unavailable');
        const families = presentationFontFamilies(data);
        const selections = data.selections || [];
        const chosenIds = new Set(selections.map(item => item.font_id).filter(Boolean));
        const chosenPaths = new Set(selections.map(item => item.custom_font_path).filter(Boolean));
        window.tenantPresentationFontFamilies = families;
        select.innerHTML = '<option value="">الخط الافتراضي</option>' + families.map(family => {
          const selected = family.faces.some(face =>
            chosenIds.has(face.id) || (face.custom_font_path && chosenPaths.has(face.custom_font_path)));
          const scripts = new Set(family.faces.map(face => face.script || 'arabic'));
          const coverage = scripts.has('arabic') && scripts.has('latin') ? trDynamicI18n('عربي ولاتيني')
            : scripts.has('arabic') ? trDynamicI18n('عربي') : trDynamicI18n('لاتيني');
          return '<option value="' + escapeHtml(family.name) + '"' + (selected ? ' selected' : '') +
            '>' + escapeHtml(family.name + ' — ' + coverage) + '</option>';
        }).join('');
        select.disabled = false;
        refreshDynamicI18n(select);
        await renderPresentationFontStatus();
      } catch (error) {
        console.warn('[PRESENTATION FONT] load failed:', error);
        select.innerHTML = '<option value="">تعذر تحميل الخطوط</option>';
        refreshDynamicI18n(select);
      }
    }
    document.addEventListener('wf:lang', () => {
      try {
        const panel = document.getElementById('presentationFontSettingsPanel');
        if (panel && panel.style.display === 'flex') openPresentationFontSettings();
      } catch (e) { /* ignore */ }
    });

    function closePresentationFontSettings() {
      const panel = document.getElementById('presentationFontSettingsPanel');
      if (panel) {
        panel.style.display = 'none';
        if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
      }
    }

    // The chosen family is applied to the whole deck: both scripts and every weight. A family that
    // ships faces for one script only is used for the other script too, otherwise half the text
    // would silently stay on the platform default and the choice would look like it did nothing.
    async function selectPresentationFont(familyName) {
      const select = document.getElementById('presentationFontSelect');
      if (!select || select.disabled) return;
      select.disabled = true;
      const weights = ['light', 'regular', 'medium', 'bold', 'black'];
      try {
        await Promise.all(['arabic', 'latin'].flatMap(script =>
          weights.map(weight => api('DELETE', '/api/branding/fonts/' + script + '/' + weight))));
        if (familyName) {
          let families = window.tenantPresentationFontFamilies;
          if (!families) {
            families = presentationFontFamilies(await api('GET', '/api/branding/fonts'));
          }
          const family = families.find(item => item.name === familyName);
          if (!family) throw new Error('Unknown font family');
          for (const script of ['arabic', 'latin']) {
            const own = family.faces.filter(face => (face.script || 'arabic') === script);
            for (const face of (own.length ? own : family.faces)) {
              const body = { script, weight: face.weight || 'regular' };
              if (face.custom_font_path) body.custom_font_path = face.custom_font_path;
              else body.font_id = face.id;
              await api('PUT', '/api/branding/fonts', body);
            }
          }
          await api('PUT', '/api/branding', { font_family: familyName, font_arabic: familyName });
        }
        await loadTenantBranding();
        await renderPresentationFontStatus();
        if (typeof renderTenantSlides === 'function') renderTenantSlides();
        toast(familyName ? 'تم تطبيق الخط على العرض' : 'تم الرجوع للخط الافتراضي');
      } catch (error) {
        console.error('[PRESENTATION FONT] save failed:', error);
        toast('تعذر تحديث خط العرض');
      } finally {
        select.disabled = false;
      }
    }

    function toggleMapStylePanel() {
      const panel = document.getElementById('mapStylePanel');
      if (panel) {
        if (panel.style.display === 'none' || !panel.style.display) {
          const pStyles = (tenantProjectData && tenantProjectData.map_styles) || {};
          const bStyles = tenantBranding || {};
          const setSelect = (id, val) => { const el = document.getElementById(id); if (el && val) el.value = val; };
          setSelect('mapStyleOverview', pStyles.overview || bStyles.map_style_overview || 'satellite');
          setSelect('mapStyleLandmarks', pStyles.landmarks || bStyles.map_style_landmarks || 'satellite');
          setSelect('mapStyleAccess', pStyles.access || bStyles.map_style_access || 'satellite');
          setSelect('mapStyleCatchment', pStyles.catchment || bStyles.map_style_catchment || 'satellite');
          panel.style.display = 'flex';
        } else {
          panel.style.display = 'none';
        }
      }
    }

    function editSlideHtml(index) {
      if (!hasPermission('create_presentation')) return;
      const slide = tenantSlidesData[index];
      if (!slide) return;
      const existing = document.getElementById('slideEditModal');
      if (existing) existing.remove();
      const modal = document.createElement('div');
      modal.id = 'slideEditModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:20px;padding:24px;max-width:800px;width:100%;max-height:90vh;overflow:auto">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">' +
        '<h3>تعديل شريحة ' + (index + 1) + '</h3>' +
        '<button class="btn ghost" onclick="this.closest(\'#slideEditModal\').remove()">إغلاق</button></div>' +
        '<label>عنوان الشريحة</label>' +
        '<input type="text" id="slideEditTitle" value="' + escapeHtml(slide.title || '') + '" style="width:100%;margin-bottom:10px">' +
        '<label>HTML المحتوى</label>' +
        '<textarea id="slideEditHtml" style="width:100%;min-height:300px;font-family:monospace;font-size:13px">' + escapeHtml(slide.html || '') + '</textarea>' +
        '<div class="tenant-btns" style="margin-top:12px">' +
        '<button class="btn primary" onclick="saveSlideEdit(' + index + ')">حفظ</button>' +
        '</div></div>';
      document.body.appendChild(modal);
    }

    function saveSlideEdit(index) {
      if (!hasPermission('create_presentation')) return;
      const title = document.getElementById('slideEditTitle').value;
      const html = document.getElementById('slideEditHtml').value;
      beginPresentationUndoChange();
      tenantSlidesData[index].title = title;
      tenantSlidesData[index].html = html;
      tenantSlidesData[index]._designer_keep_html = true;
      tenantSlidesData[index].is_custom = true;
      document.getElementById('slideEditModal').remove();
      renderTenantSlides();
      triggerAutoSaveDraft();
      toast('تم تعديل الشريحة');
    }

    function moveSlide(index, direction) {
      const newIndex = index + direction;
      if (newIndex < 0 || newIndex >= tenantSlidesData.length) return;
      beginPresentationUndoChange();
      const temp = tenantSlidesData[index];
      tenantSlidesData[index] = tenantSlidesData[newIndex];
      tenantSlidesData[newIndex] = temp;
      renumberTenantSlides();
      renderTenantSlides();
      triggerAutoSaveDraft();
    }

    function deleteSlide(index) {
      if (!hasPermission('create_presentation')) return;
      if (tenantSlidesData.length <= 1) { toast('لا يمكن حذف آخر شريحة'); return; }
      if (!confirm('حذف الشريحة ' + (index + 1) + '؟')) return;
      beginPresentationUndoChange();
      tenantSlidesData.splice(index, 1);
      activeSlideIndex = Math.min(activeSlideIndex, tenantSlidesData.length - 1);
      tenantChatSlideIndex = Math.min(tenantChatSlideIndex, tenantSlidesData.length - 1);
      renumberTenantSlides();
      renderTenantSlides();
      triggerAutoSaveDraft();
      toast('تم حذف الشريحة');
    }

    async function commitTenantPresentation(snapshot, presentationId, title, options = {}) {
      if (tenantPresentationSavePromise) return tenantPresentationSavePromise;
      const initialRevision = options.expectedRevision ?? tenantPresentationRevision;
      const provenance = tenantPresentationProvenance;
      const button = document.getElementById('presentationSaveButton');
      if (button) { button.disabled = true; button.textContent = 'جاري الحفظ...'; }
      tenantPresentationSavePromise = (async () => {
        let currentRevision = initialRevision;
        let attempts = 0;
        while (attempts < 2) {
          attempts++;
          // api('POST', '/api/presentations'
          const response = await api(presentationId ? 'PUT' : 'POST',
            '/api/presentations' + (presentationId ? '/' + encodeURIComponent(presentationId) : ''), {
              title, projectData: snapshot, slidesData: snapshot.tenantSlidesData,
              slideCount: snapshot.tenantSlidesData.length,
              ...(presentationId ? { expectedRevision: currentRevision } : {}),
              changeSource: provenance ? 'ai' : 'manual', provenance,
              operation: options.operation || 'save'
            });
          if (!response?.success) {
            if (response?.error_code === 'PRESENTATION_REVISION_CONFLICT') {
              const serverRevision = Number(response.currentRevision);
              const isInteractive = typeof options.interactive !== 'undefined' ? options.interactive : !options.silent;
              if (attempts === 1 && (options.force || isInteractive) && Number.isInteger(serverRevision) && typeof confirm === 'function') {
                const confirmOverwrite = options.force || confirm(
                  WFT('presentation.conflict_confirm', 'توجد نسخة أحدث محفوظة على الخادم (النسخة {rev}). هل تريد حفظ تعديلاتك الحالية فوقها؟', { rev: serverRevision })
                );
                if (confirmOverwrite) {
                  currentRevision = serverRevision;
                  continue;
                }
              }
              throw new Error('العرض له نسخة أحدث محفوظة على الخادم. تعديلاتك ما زالت مفتوحة ولم تُستبدل النسخة المحفوظة.');
            }
            const saveError = new Error(response?.error || 'تعذر حفظ العرض');
            saveError.response = response || {};
            throw saveError;
          }
          if (!presentationId || tenantPresentationId === presentationId) {
            tenantPresentationId = response.presentationId || presentationId;
            tenantPresentationRevision = Number(response.revision) || 0;
            tenantPresentationTitle = title;
            tenantProjectMode = 'presentation';
            clearPresentationUndoProvenance();
            setSlidesEditorInfo(title, tenantSlidesData.length);
          }
          tenantArchiveCache = null;
          return response;
        }
      })();
      updatePresentationUndoButtons();
      try { return await tenantPresentationSavePromise; }
      finally {
        tenantPresentationSavePromise = null;
        if (button) { button.disabled = false; button.textContent = 'حفظ كمسودة'; }
        updatePresentationUndoButtons();
      }
    }

    async function saveTenantPresentation(titleOverride = '', options = {}) {
      const title = String(titleOverride || tenantPresentationTitle
        || tenantProjectData.project_name || tenantProjectData.projectName || 'عرض بدون عنوان').trim();
      renumberTenantSlides();
      // api('POST', '/api/presentations'
      tenantProjectData = {
        ...tenantProjectData, tenantSlidePlan, tenantCreativeImages,
        designerChat: designerChatPersistence(), tenantSlidesData
      };
      const snapshot = JSON.parse(JSON.stringify(tenantProjectData));
      try {
        const response = await commitTenantPresentation(snapshot, tenantPresentationId, title, options);
        tenantProjectData.designerChat = designerChatPersistence(response.presentationId);
        return true;
      } catch (error) {
        if (typeof options.onError === 'function') options.onError(error);
        setDraftDirty(true);
        toast(error.message || 'تعذر حفظ العرض');
        return false;
      }
    }

    async function savePresentationFromToolbar() {
      if (tenantPresentationSavePromise || isGeneratingTenantSlides) return;
      if (tenantPresentationId) await saveExistingPresentation();
      else if (tenantSlidesData.length) await saveTenantPresentation();
      else await saveProjectAsDraft();
    }

    async function savePresentationCopy() {
      if (!tenantSlidesData.length || tenantPresentationSavePromise || isGeneratingTenantSlides) return;
      const name = prompt('اسم العرض المستقل', (tenantPresentationTitle || 'عرض') + ' - نسخة مستقلة');
      if (!name?.trim()) return;
      const original = { id: tenantPresentationId, revision: tenantPresentationRevision,
        title: tenantPresentationTitle, scope: tenantProjectData.presentation_scope };
      tenantPresentationId = null;
      tenantPresentationRevision = 0;
      tenantProjectData.presentation_scope = 'copy:' + crypto.randomUUID();
      if (await saveTenantPresentation(name.trim())) {
        resetPresentationUndo();
        toast('تم حفظ عرض مستقل');
      } else {
        tenantPresentationId = original.id;
        tenantPresentationRevision = original.revision;
        tenantPresentationTitle = original.title;
        tenantProjectData.presentation_scope = original.scope;
      }
    }

    async function preparePresentationGenerationTarget(scope) {
      if (tenantPresentationSavePromise) await tenantPresentationSavePromise;
      const saveCurrentPresentation = async () => {
        let saveError = null;
        const saved = await saveTenantPresentation('', {
          onError: error => { saveError = error; }
        });
        return saved ? true : ((saveError && saveError.response) || false);
      };
      if (tenantPresentationId && tenantSlidesData.length) {
        let saved = await saveCurrentPresentation();
        if (saved !== true && saved?.error_code === 'DRAFT_LOCKED' && saved?.status === 'generating'
          && await cancelActiveTenantGenerationRun(tenantProjectData.draftId || tenantProjectData.draft_id)) {
          saved = await saveCurrentPresentation();
        }
        if (saved !== true) return false;
      }
      let target = null;
      const currentScope = tenantProjectData.presentation_scope;
      if (tenantPresentationId && (currentScope === scope || (!currentScope && scope === 'full')
        || (scope === 'full' && String(currentScope || '').startsWith('copy:')))) {
        target = { id: tenantPresentationId, revision: tenantPresentationRevision };
      } else {
        const draftId = tenantProjectData.draftId;
        if (draftId) {
          const response = await api('GET', '/api/presentations?draftId=' + encodeURIComponent(draftId));
          if (!response?.success) { toast(response?.error || 'تعذر تحميل عروض المشروع'); return false; }
          target = (response.presentations || []).find(item => item.presentationScope === scope) || null;
        }
      }
      if (target && target.id !== tenantPresentationId) {
        const response = await api('GET', '/api/presentations/' + encodeURIComponent(target.id));
        if (!response?.success) { toast(response?.error || 'تعذر تحميل النسخة الحالية'); return false; }
        const saved = response.presentation;
        let checkpoint = await api('PUT', '/api/presentations/' + encodeURIComponent(target.id), {
          title: saved.title, projectData: saved.projectData, slidesData: saved.slidesData,
          expectedRevision: Number(saved.revision) || 0
        });
        if (!checkpoint?.success && checkpoint?.error_code === 'DRAFT_LOCKED'
          && checkpoint?.status === 'generating'
          && await cancelActiveTenantGenerationRun(saved.draftId || saved.projectData?.draftId || tenantProjectData.draftId)) {
          checkpoint = await api('PUT', '/api/presentations/' + encodeURIComponent(target.id), {
            title: saved.title, projectData: saved.projectData, slidesData: saved.slidesData,
            expectedRevision: Number(saved.revision) || 0
          });
        }
        if (!checkpoint?.success) { toast(checkpoint?.error || 'تعذر حماية النسخة الحالية'); return false; }
        target.revision = checkpoint.revision;
        tenantSlidesData = saved.slidesData || [];
        tenantSlidePlan = recoverTenantSlidePlan(saved.projectData || {}, tenantSlidesData);
        resetPresentationUndo();
      }
      tenantPresentationId = target?.id || null;
      tenantPresentationRevision = Number(target?.revision) || 0;
      tenantPresentationProvenance = null;
      tenantProjectMode = target ? 'presentation' : 'new';
      tenantProjectData.presentation_scope = target && String(currentScope || '').startsWith('copy:')
        ? currentScope : scope;
      checkpointPresentationUndo();
      return true;
    }