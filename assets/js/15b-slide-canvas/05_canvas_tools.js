/* Text formatting beyond the quick typography buttons, image cropping and
   partial inline colour. Everything writes through the same selected-element
   path so the stored slide HTML, undo and export stay in step. */

    function slideSelectionPrimary(index) {
      const stage = canvasStageFor(index);
      const session = canvasSession(index);
      if (!stage || !session) return null;
      const slide = stage.querySelector('.slide');
      const pairs = slideSelectedTargets(stage, session);
      if (!slide || !pairs.length) return null;
      return { stage, session, slide, target: pairs[0].target };
    }

    function toggleSlideSelectionTextStyle(index, styleKind) {
      const primary = slideSelectionPrimary(index);
      if (!primary) return;
      const computed = window.getComputedStyle(primary.target);
      if (styleKind === 'italic') {
        const next = String(computed.fontStyle || '').toLowerCase() === 'italic' ? 'normal' : 'italic';
        setSlideSelectionStyle(index, el => { el.style.fontStyle = next; });
      } else {
        const current = String(computed.textDecorationLine || computed.textDecoration || '').toLowerCase();
        const wanted = styleKind === 'underline' ? 'underline' : 'line-through';
        const has = current.indexOf(wanted) !== -1;
        let next = current
          .replace('underline', '')
          .replace('line-through', '')
          .replace(/\s+/g, ' ')
          .trim();
        if (!has) next = (next ? next + ' ' : '') + wanted;
        setSlideSelectionStyle(index, el => { el.style.textDecoration = next; });
      }
    }

    function adjustSlideSelectionLineHeight(index, delta) {
      const primary = slideSelectionPrimary(index);
      if (!primary) return;
      const computed = window.getComputedStyle(primary.target);
      const fontSize = parseFloat(computed.fontSize) || 18;
      const rawLine = parseFloat(computed.lineHeight);
      const lineHeight = isFinite(rawLine) ? rawLine : fontSize * 1.6;
      const next = Math.round((lineHeight / fontSize + Number(delta || 0)) * 10) / 10;
      setSlideSelectionLineHeight(index, Math.max(0.8, Math.min(3, next)));
    }

    function adjustSlideSelectionLetterSpacing(index, delta) {
      const primary = slideSelectionPrimary(index);
      if (!primary) return;
      const computed = window.getComputedStyle(primary.target);
      const current = parseFloat(computed.letterSpacing);
      const next = (isFinite(current) ? current : 0) + Number(delta || 0);
      setSlideSelectionLetterSpacing(index, Math.max(-5, Math.min(20, Math.round(next * 10) / 10)));
    }

    function slideSelectionListHtml(target, listKind) {
      const previous = String(target.getAttribute('data-slide-list') || '');
      if (previous) {
        const items = Array.from(target.querySelectorAll('li'))
          .map(item => String(item.innerHTML || '').trim())
          .filter(Boolean);
        return { html: items.join('<br>'), listKind: '' };
      }
      const lines = String(target.innerText || target.textContent || '')
        .split(/\n+/).map(line => line.trim()).filter(Boolean);
      if (!lines.length) lines.push(slideToolbarText('ca.new_bullet', 'بند جديد'));
      const tag = listKind === 'number' ? 'ol' : 'ul';
      const type = listKind === 'number' ? 'decimal' : 'disc';
      const items = lines.map(line => '<li style="margin:0 0 8px;">'
        + authoringEscape(line) + '</li>').join('');
      return {
        html: '<' + tag + ' data-slide-list="' + listKind + '" style="margin:0;padding:0 22px 0 0;'
          + 'list-style-position:inside;list-style-type:' + type + ';">' + items + '</' + tag + '>',
        listKind
      };
    }

    function toggleSlideSelectionList(index, listKind) {
      const primary = slideSelectionPrimary(index);
      if (!primary) return;
      const next = slideSelectionListHtml(primary.target, listKind);
      withSlideElementTargets(index, (live, raw) => {
        live.innerHTML = next.html;
        raw.innerHTML = next.html;
        if (next.listKind) {
          live.setAttribute('data-slide-list', next.listKind);
          raw.setAttribute('data-slide-list', next.listKind);
        } else {
          live.removeAttribute('data-slide-list');
          raw.removeAttribute('data-slide-list');
        }
      });
      if (next.listKind) {
        toast(WFT('slide.list_applied', 'تم تحويل النص إلى قائمة'));
      } else {
        toast(WFT('slide.list_removed', 'تم إرجاع القائمة إلى نص'));
      }
    }

    function clearSlideSelectionFormatting(index) {
      const resets = ['color', 'backgroundColor', 'backgroundImage', 'fontStyle', 'fontWeight',
        'fontSize', 'fontFamily', 'textDecoration', 'textAlign', 'lineHeight', 'letterSpacing',
        'textShadow', 'border', 'borderRadius', 'boxShadow', 'padding'];
      const primary = slideSelectionPrimary(index);
      const wasList = !!(primary && primary.target.getAttribute('data-slide-list'));
      if (wasList) toggleSlideSelectionList(index, primary.target.getAttribute('data-slide-list'));
      withSlideElementTargets(index, (live, raw) => {
        [live, raw].forEach(el => {
          resets.forEach(property => { el.style[property] = ''; });
        });
      });
      toast(WFT('slide.format_cleared', 'تم مسح التنسيق'));
    }

    function fitSlideSelectionText(index) {
      const primary = slideSelectionPrimary(index);
      if (!primary) return;
      const live = primary.target;
      const startSize = parseFloat(window.getComputedStyle(live).fontSize) || 18;
      let size = startSize;
      const overflows = () => live.scrollHeight - live.clientHeight > 2
        || live.scrollWidth - live.clientWidth > 2;
      if (!overflows()) {
        toast(WFT('slide.text_fits', 'النص داخل المساحة بالفعل'));
        return;
      }
      while (size > 8 && overflows()) {
        size = Math.max(8, size - 1);
        live.style.fontSize = Math.round(size) + 'px';
      }
      const finalSize = Math.round(size) + 'px';
      withSlideElementTargets(index, (liveEl, rawEl) => {
        const isImage = liveEl.tagName === 'IMG' || rawEl.tagName === 'IMG';
        if (isImage) return;
        liveEl.style.fontSize = finalSize;
        rawEl.style.fontSize = finalSize;
      });
      toast(WFT('slide.text_fit', 'تم ضبط النص داخل المساحة'));
    }

    /* ── Partial inline colour ──────────────────────────────────────────── */

    function slideTextSelectionRange(target) {
      const selection = window.getSelection();
      if (!target || !selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
      const range = selection.getRangeAt(0);
      const container = range.commonAncestorContainer;
      if (!container) return null;
      if (container === target) return range;
      return target.contains(container) ? range : null;
    }

    function slideTextSelectionInside(index, target) {
      const primary = slideSelectionPrimary(index);
      if (!primary || primary.target !== target) return false;
      return !!slideTextSelectionRange(target);
    }

    function applySlideInlineColorToSelection(index, kind, color) {
      const primary = slideSelectionPrimary(index);
      if (!primary) return false;
      const range = slideTextSelectionRange(primary.target);
      if (!range) return false;
      const span = document.createElement('span');
      span.setAttribute('data-slide-inline-style', '1');
      span.style[kind === 'highlight' ? 'backgroundColor' : 'color'] = color;
      try {
        range.surroundContents(span);
      } catch (error) {
        const fragment = range.extractContents();
        span.appendChild(fragment);
        range.insertNode(span);
      }
      withSlideElementTargets(index, (live, raw) => {
        if (live !== primary.target) return;
        raw.innerHTML = live.innerHTML;
      });
      toast(WFT('slide.inline_color', 'تم تلوين الجزء المحدد'));
      return true;
    }

    /* ── Image crop: move the picture inside its fixed frame ────────────── */

    function slideImageTargetOf(target) {
      if (!target) return null;
      if (target.tagName === 'IMG') return target;
      return target.querySelector ? target.querySelector('img') : null;
    }

    function prepareSlideImageCrop(index, img) {
      if (!img || img.tagName !== 'IMG') return false;
      // `height:auto` is how every uploaded image ships; it is not a frame.
      if (img.style.height && img.style.height !== 'auto') return false;
      const stage = canvasStageFor(index);
      if (!stage) return false;
      const scale = Number(stage.style.getPropertyValue('--slide-scale')) || 1;
      const height = Math.round(img.getBoundingClientRect().height / scale);
      if (!height) return false;
      img.style.height = Math.max(24, height) + 'px';
      img.style.objectFit = 'cover';
      img.dataset.cropPrepared = '1';
      return true;
    }

    function toggleSlideImageCrop(index) {
      const session = canvasSession(index);
      const primary = slideSelectionPrimary(index);
      if (!session || !primary) return;
      const img = slideImageTargetOf(primary.target);
      if (!img) return;
      if (session.cropMode) {
        session.cropMode = false;
        img.classList.remove('slide-crop-target');
        refreshSlideEditToolbar(index);
        renderSlideInspector(index);
        toast(WFT('slide.crop_off', 'انتهى القص'));
        return;
      }
      session.cropMode = true;
      img.classList.add('slide-crop-target');
      prepareSlideImageCrop(index, img);
      refreshSlideEditToolbar(index);
      renderSlideInspector(index);
      toast(WFT('slide.crop_on', 'اسحب الصورة لضبط القص'));
    }

    function startSlideImageCropDrag(stage, index, target, event) {
      const img = slideImageTargetOf(target);
      if (!img || !stage) return;
      prepareSlideImageCrop(index, img);
      const scale = Number(stage.style.getPropertyValue('--slide-scale')) || 1;
      const rect = img.getBoundingClientRect();
      const width = Math.max(1, rect.width / scale);
      const height = Math.max(1, rect.height / scale);
      const computed = window.getComputedStyle(img);
      const position = String(computed.objectPosition || '50% 50%').split(/\s+/);
      const parsePct = value => {
        const number = parseFloat(value);
        return isFinite(number) ? number : 50;
      };
      let posX = parsePct(position[0]);
      let posY = parsePct(position[1] || position[0]);
      const startX = event.clientX;
      const startY = event.clientY;
      let moved = false;
      slideElementDragActive = true;
      const onMove = moveEvent => {
        const dx = (moveEvent.clientX - startX) / scale;
        const dy = (moveEvent.clientY - startY) / scale;
        if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
        const nextX = Math.max(0, Math.min(100, posX - (dx / width) * 100));
        const nextY = Math.max(0, Math.min(100, posY - (dy / height) * 100));
        img.style.objectPosition = nextX.toFixed(1) + '% ' + nextY.toFixed(1) + '%';
      };
      const onUp = () => {
        window.removeEventListener('pointermove', onMove, true);
        window.removeEventListener('pointerup', onUp, true);
        window.removeEventListener('pointercancel', onUp, true);
        slideElementDragActive = false;
        if (!moved) return;
        const livePosition = img.style.objectPosition;
        const liveHeight = img.style.height;
        withSlideElementTargets(index, (live, raw) => {
          const liveImg = slideImageTargetOf(live);
          const rawImg = slideImageTargetOf(raw);
          if (!liveImg || !rawImg) return;
          [liveImg, rawImg].forEach(image => {
            image.style.objectFit = 'cover';
            image.style.objectPosition = livePosition;
            if (liveHeight) image.style.height = liveHeight;
          });
        });
        toast(WFT('slide.crop_applied', 'تم قص الصورة'));
      };
      window.addEventListener('pointermove', onMove, true);
      window.addEventListener('pointerup', onUp, true);
      window.addEventListener('pointercancel', onUp, true);
    }

    function slideInlineStyleSanitizer(value) {
      const allowed = ['color', 'background-color', 'font-weight', 'font-style', 'text-decoration'];
      const kept = [];
      String(value || '').split(';').forEach(declaration => {
        const [property, ...rest] = declaration.split(':');
        const name = String(property || '').trim().toLowerCase();
        const content = rest.join(':').trim();
        if (!content || !allowed.includes(name)) return;
        if (/[<>"'`]/.test(content)) return;
        kept.push(name + ':' + content);
      });
      return kept.join(';');
    }
