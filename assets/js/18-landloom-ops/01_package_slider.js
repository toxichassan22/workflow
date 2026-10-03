/* 18-landloom-ops/01_package_slider.js - shared card slider for the billing
   package catalog: the client recharge picker and the super-admin list.
   Shared global scope, classic scripts in order. */

    /* Shows up to `maxVisible` cards at once and loops: «السابق»/«التالي» or a
       drag shifts the window one card and the far end wraps back to the
       start. The wrap borrows clone cards at both track ends — the move lands
       on a clone, then the position snaps to its real twin with no
       transition, so the seam never shows. */
    function wfCardSlider(options) {
      const opts = options || {};
      const container = opts.container;
      const renderCard = opts.renderCard || function () { return ''; };
      const maxVisible = opts.maxVisible || 3;
      const minCardWidth = opts.minCardWidth || 150;
      const gap = opts.gap == null ? 12 : opts.gap;
      let items = Array.isArray(opts.items) ? opts.items : [];
      let n = items.length;
      let visible = 1;
      let step = 1;
      let pos = 0;          // first shown card in track units (clone space)
      let sliding = false;  // loop + drag only when items overflow the window
      let builtOnce = false;
      let settleTimer = null;
      let destroyed = false;
      let suppressClick = false;

      container.innerHTML =
        '<div class="wf-slider">' +
        '<button type="button" class="btn ghost small wf-slider-nav">' +
          llEscape(opts.prevLabel || 'السابق') + '</button>' +
        '<div class="wf-slider-viewport"><div class="wf-slider-track"></div></div>' +
        '<button type="button" class="btn ghost small wf-slider-nav">' +
          llEscape(opts.nextLabel || 'التالي') + '</button>' +
        '</div>';
      const root = container.firstElementChild;
      const viewport = root.querySelector('.wf-slider-viewport');
      const track = root.querySelector('.wf-slider-track');
      const prevBtn = root.querySelectorAll('.wf-slider-nav')[0];
      const nextBtn = root.querySelectorAll('.wf-slider-nav')[1];
      prevBtn.addEventListener('click', () => go(-1));
      nextBtn.addEventListener('click', () => go(1));

      function rtlSign() {
        return getComputedStyle(container).direction === 'rtl' ? 1 : -1;
      }
      function normalize(p) {
        return visible + (((p - visible) % n) + n) % n;
      }
      function setPos(p, dx, animate) {
        pos = p;
        track.classList.toggle('anim', !!animate);
        track.style.transform =
          'translateX(' + (rtlSign() * p * step + (dx || 0)) + 'px)';
      }
      /* A move can end on a clone; the identical real position is n steps
         back, so snapping there with no transition hides the wrap. */
      function settle() {
        if (settleTimer) { clearTimeout(settleTimer); settleTimer = null; }
        if (!sliding || !n) return;
        const norm = normalize(pos);
        if (norm !== pos) setPos(norm, 0, false);
      }
      function scheduleSettle() {
        if (settleTimer) clearTimeout(settleTimer);
        settleTimer = setTimeout(settle, 360);
      }
      function go(delta) {
        if (!sliding || destroyed) return;
        settle();  // keep pos inside the clone band before queuing another step
        setPos(pos + delta, 0, true);
        scheduleSettle();
      }
      track.addEventListener('transitionend', e => {
        if (e.target === track && e.propertyName === 'transform') settle();
      });

      function build() {
        const wasSliding = sliding, prevN = n;
        n = items.length;
        const realIndex = (builtOnce && wasSliding && prevN)
          ? (((pos - visible) % prevN) + prevN) % prevN : 0;
        const vpW = viewport.clientWidth ||
          (minCardWidth * maxVisible + gap * (maxVisible - 1));
        visible = Math.max(1, Math.min(
          maxVisible, n || 1, Math.floor((vpW + gap) / (minCardWidth + gap))));
        sliding = n > visible;
        const cardW = Math.max(0, (vpW - gap * (visible - 1)) / visible);
        step = cardW + gap;
        track.style.gap = gap + 'px';
        const cardHtml = (i, clone) =>
          '<div class="wf-slider-card"' +
          (clone ? ' data-clone="1" aria-hidden="true"' : '') +
          ' style="flex:0 0 ' + cardW + 'px">' + renderCard(items[i], i) + '</div>';
        let html = '';
        if (sliding) {
          for (let i = n - visible; i < n; i++) html += cardHtml(i, true);
          for (let i = 0; i < n; i++) html += cardHtml(i, false);
          for (let i = 0; i < visible; i++) html += cardHtml(i, true);
        } else {
          for (let i = 0; i < n; i++) html += cardHtml(i, false);
        }
        track.innerHTML = html;
        track.querySelectorAll('[data-clone] [tabindex]').forEach(el => {
          el.setAttribute('tabindex', '-1');
        });
        pos = sliding ? visible + Math.min(realIndex, n - 1) : 0;
        setPos(pos, 0, false);
        prevBtn.style.display = sliding ? '' : 'none';
        nextBtn.style.display = sliding ? '' : 'none';
        builtOnce = true;
      }

      /* Drag: a horizontal pull past 6px becomes a swipe; on release the
         window settles on the nearest card, capped at one window of travel. */
      let dragX = null, dragBase = 0, dragging = false, dragPointer = null;
      viewport.addEventListener('pointerdown', e => {
        if (!sliding || e.button === 2) return;
        dragX = e.clientX;
        dragBase = pos;
        dragging = false;
        dragPointer = e.pointerId;
      });
      viewport.addEventListener('pointermove', e => {
        if (dragX === null || e.pointerId !== dragPointer) return;
        const dx = e.clientX - dragX;
        if (!dragging && Math.abs(dx) > 6) {
          dragging = true;
          settle();
          dragBase = pos;
          if (viewport.setPointerCapture) {
            try { viewport.setPointerCapture(dragPointer); } catch (err) { /* released */ }
          }
          root.classList.add('dragging');
        }
        if (dragging) {
          // Clamped to the clone band — a fling never animates into blank track.
          const lo = (visible - 1) - dragBase, hi = (visible + n) - dragBase;
          const raw = dx * rtlSign() / step;
          setPos(dragBase + Math.max(lo, Math.min(hi, raw)), 0, false);
        }
      });
      function endDrag(e) {
        if (dragX === null || e.pointerId !== dragPointer) return;
        const dx = e.clientX - dragX;
        const was = dragging;
        dragX = null; dragging = false; dragPointer = null;
        root.classList.remove('dragging');
        if (!was) return;
        suppressClick = true;
        const lo = (visible - 1) - dragBase, hi = (visible + n) - dragBase;
        const delta = Math.max(lo, Math.min(hi, Math.round(dx * rtlSign() / step)));
        setPos(dragBase + delta, 0, true);
        scheduleSettle();
      }
      viewport.addEventListener('pointerup', endDrag);
      viewport.addEventListener('pointercancel', endDrag);
      viewport.addEventListener('lostpointercapture', endDrag);
      // A real drag must not fall through to the card's click action.
      viewport.addEventListener('click', e => {
        if (!suppressClick) return;
        suppressClick = false;
        e.preventDefault();
        e.stopPropagation();
      }, true);

      let resizeObserver = null;
      if (typeof ResizeObserver === 'function') {
        let lastW = 0;
        resizeObserver = new ResizeObserver(() => {
          if (destroyed) return;
          const w = viewport.clientWidth;
          if (!w || Math.abs(w - lastW) < 1) return;
          lastW = w;
          build();
        });
        resizeObserver.observe(viewport);
      }

      build();
      return {
        element: root,
        refresh(newItems) { items = Array.isArray(newItems) ? newItems : []; build(); },
        next() { go(1); },
        prev() { go(-1); },
        destroy() {
          destroyed = true;
          if (settleTimer) clearTimeout(settleTimer);
          if (resizeObserver) resizeObserver.disconnect();
          container.innerHTML = '';
        },
      };
    }

    /* ── Client recharge picker ───────────────────────────────────────── */

    let llRechargePkgSlider = null;
    let llAdminPkgSlider = null;

    function llRechargePackageCardHtml(p) {
      const input = document.getElementById('llRechargePackage');
      const selected = input && input.value === p.id;
      const price = p.price_sar != null
        ? llEscape(llMoney(p.price_sar)) + ' <span>ريال سعودي</span>'
        : 'بلا سعر';
      const validity = p.duration_days
        ? '<span>الصلاحية:</span> ' + llEscape(p.duration_days) + ' <span>يومًا</span>'
        : 'الصلاحية: بلا انتهاء محدد';
      const features = (Array.isArray(p.features) ? p.features : [])
        .filter(Boolean)
        .map(f => '<div class="pkg-card-meta">' + llEscape(f) + '</div>')
        .join('');
      return '<div class="pkg-card pkg-pick' + (selected ? ' selected' : '') + '"' +
        ' data-pkg-id="' + llEscape(p.id) + '" role="button" tabindex="0"' +
        ' onclick="llPickRechargePackage(\'' + llEscape(p.id) + '\')">' +
        '<h3>' + llEscape(wfBilingual(p.name, p.name_en)) + '</h3>' +
        '<div class="pkg-card-points">' + llEscape(llMoney(p.credit_sar)) +
        ' <span>نقطة</span></div>' +
        '<div class="pkg-card-meta">' + price + '</div>' +
        '<div class="pkg-card-meta">' + validity + '</div>' +
        features + '</div>';
    }

    /* Card clicks select into a hidden input so llCreateRechargeRequest and
       llShowPackageInfo read the pick exactly like the old <select>. */
    function llPickRechargePackage(packageId) {
      const input = document.getElementById('llRechargePackage');
      if (input) input.value = packageId || '';
      const host = document.getElementById('llRechargePackageCards');
      if (host) {
        host.querySelectorAll('.pkg-pick').forEach(card => {
          card.classList.toggle('selected',
            card.getAttribute('data-pkg-id') === packageId);
        });
      }
      llShowPackageInfo();
    }

    /* ── Super-admin catalog ──────────────────────────────────────────── */

    function llAdminPackageCardHtml(p) {
      const price = p.price_sar != null
        ? llEscape(llMoney(p.price_sar)) + ' <span>ريال سعودي</span>'
        : 'بلا سعر';
      const cost = p.est_cost_sar != null
        ? '<div class="pkg-card-meta">التكلفة التقديرية: ' +
          llEscape(llMoney(p.est_cost_sar)) + ' <span>نقطة</span></div>' : '';
      const margin = p.est_margin_sar != null
        ? '<div class="pkg-card-meta">الربح التقديري: ' +
          llEscape(llMoney(p.est_margin_sar)) + ' <span>نقطة</span></div>' : '';
      return '<div class="pkg-card">' +
        '<h3>' + llEscape(wfBilingual(p.name, p.name_en)) + '</h3>' +
        '<div class="pkg-card-points">' + price + '</div>' +
        '<div class="pkg-card-meta">' + llEscape(llMoney(p.credit_sar)) +
        ' <span>نقطة</span></div>' +
        cost + margin +
        '<div class="pkg-card-meta">' + (p.is_active ? 'نشطة' : 'موقوفة') + '</div>' +
        '<div class="pkg-card-actions">' +
        '<button type="button" class="btn small ghost" onclick="adminEditPackage(\'' +
          llEscape(p.id) + '\')">تعديل</button>' +
        '<button type="button" class="btn small ' + (p.is_active ? 'danger' : 'green') +
          '" onclick="adminTogglePackage(\'' + llEscape(p.id) + '\', ' +
          (p.is_active ? 0 : 1) + ')">' + (p.is_active ? 'إيقاف' : 'تفعيل') + '</button>' +
        '<button type="button" class="btn small danger" onclick="adminDeletePackage(\'' +
          llEscape(p.id) + '\')">حذف</button>' +
        '</div></div>';
    }
