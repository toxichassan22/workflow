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
      // Fewer cards than the window must not stretch edge to edge — a
      // static row holds `maxCardWidth` and centers instead.
      const maxCardWidth = opts.maxCardWidth || 300;
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

      /* Chevron glyphs are drawn in CSS (.wf-slider-arrow) — the buttons
         keep word labels only for assistive tech, never on screen. */
      container.innerHTML =
        '<div class="wf-slider">' +
        '<div class="wf-slider-body">' +
        '<button type="button" class="btn ghost small wf-slider-nav wf-slider-prev"' +
          ' aria-label="' + llEscape(opts.prevLabel || 'السابق') + '">' +
          '<span class="wf-slider-arrow" aria-hidden="true"></span></button>' +
        '<div class="wf-slider-viewport"><div class="wf-slider-track"></div></div>' +
        '<button type="button" class="btn ghost small wf-slider-nav wf-slider-next"' +
          ' aria-label="' + llEscape(opts.nextLabel || 'التالي') + '">' +
          '<span class="wf-slider-arrow" aria-hidden="true"></span></button>' +
        '</div>' +
        '<div class="wf-slider-dots"></div>' +
        '</div>';
      const root = container.firstElementChild;
      const dotsWrap = root.querySelector('.wf-slider-dots');
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
        markCenter();
        markDot();
      }
      /* An odd window has a real middle card — it scales up a touch over
         the flanking pair. Even windows and the drag's fractional stops
         just leave every card level. */
      function markCenter() {
        const mid = (visible % 2 === 1)
          ? Math.round(pos) + (visible - 1) / 2 : -1;
        const kids = track.children;
        for (let i = 0; i < kids.length; i++) {
          kids[i].classList.toggle('wf-center', i === mid);
        }
      }
      /* The lit dot tracks the center card's real index; clone positions
         fold back through the same modulo the settle snap uses. */
      function markDot() {
        if (!sliding) return;
        const centerOffset = Math.floor((visible - 1) / 2);
        const realIdx = (((Math.round(pos) + centerOffset - visible) % n) + n) % n;
        dotsWrap.querySelectorAll('.wf-slider-dot').forEach((d, i) => {
          d.classList.toggle('on', i === realIdx);
        });
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
        // On a very wide pane, filling only `maxVisible` slots would stretch
        // each card past `maxCardWidth` — grow the window instead so the
        // cards keep their compact shape while more items stay in view.
        // Pickers that want a strict «three cards, bigger middle» look opt
        // out through `growWindow: false` and let the cards take the room.
        if (opts.growWindow !== false &&
            n > visible && (vpW - gap * (visible - 1)) / visible > maxCardWidth) {
          visible = Math.min(n, Math.ceil((vpW + gap) / (maxCardWidth + gap)));
        }
        sliding = n > visible;
        let cardW = Math.max(0, (vpW - gap * (visible - 1)) / visible);
        if (!sliding) cardW = Math.min(cardW, maxCardWidth);
        step = cardW + gap;
        track.style.gap = gap + 'px';
        track.style.justifyContent = sliding ? '' : 'center';
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
        // One dot per real item — clone cards never count. A tap jumps
        // the window straight onto that package through the same
        // animate-and-settle path the arrows use.
        dotsWrap.innerHTML = sliding ? items.map((item, i) =>
          '<button type="button" class="wf-slider-dot" data-i="' + i + '"' +
          ' aria-label="' + llEscape('الباقة ' + (i + 1)) + '"></button>'
        ).join('') : '';
        dotsWrap.style.display = sliding ? '' : 'none';
        dotsWrap.querySelectorAll('.wf-slider-dot').forEach(d => {
          d.addEventListener('click', () => {
            settle();
            // Land the window so the tapped item sits in the middle slot.
            setPos(visible + Number(d.dataset.i) -
              Math.floor((visible - 1) / 2), 0, true);
            scheduleSettle();
          });
        });
        pos = sliding ? visible + Math.min(realIndex, n - 1) : 0;
        root.classList.toggle('sliding', sliding);
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
        // A pull that starts on a real control belongs to it, not the slider.
        if (e.target.closest('input, button, textarea, select, a')) return;
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

    /* ── Packages purchase page ───────────────────────────────────────── */

    let llRechargeModalSlider = null;
    let llAdminPkgSlider = null;

    /* Sales card on the «الباقات» tab: optional badge pill, name, big price,
       a teal credit figure, the desk-authored tagline (e.g. «نحو 30 عرضًا»),
       the feature list, the validity line and an «اطلب الآن» footer button.
       ``is_featured`` paints the card dark. The sentinel ``custom`` item is
       the «باقة مخصصة»: the client keys a riyal amount and the points mirror
       the server's price − tax% math. */
    function llRechargePackageCardHtml(p) {
      if (p.custom) {
        return '<div class="pkg-card pkg-card--custom" data-pkg-id="__custom__">' +
          '<span class="pkg-badge">على مقاسك</span>' +
          '<h3>باقة مخصصة</h3>' +
          '<div class="pkg-mid">' +
          '<div class="pkg-card-meta">المبلغ بالريال السعودي</div>' +
          '<input type="number" class="pkg-custom-input"' +
          ' min="1" step="0.01" dir="ltr" placeholder="0" oninput="llCustomInputChanged(this)">' +
          '<hr class="pkg-hr">' +
          '<div class="pkg-credit-label">رصيد الاستخدام</div>' +
          '<div class="pkg-credit-num pkg-custom-points">0' +
          ' <span class="pkg-credit-unit">نقطة</span></div>' +
          '</div>' +
          '<div class="pkg-card-foot">' +
          '<button type="button" class="btn primary pkg-buy"' +
          ' onclick="llPickRechargePackage(\'__custom__\')">اطلب الآن</button>' +
          '</div></div>';
      }
      const input = document.getElementById('llRechargePackage');
      const selected = input && input.value === p.id;
      const badge = wfBilingual(p.badge, p.badge_en);
      const tagline = wfBilingual(p.tagline, p.tagline_en);
      const validity = p.duration_days
        ? '<span>الصلاحية:</span> ' + llEscape(p.duration_days) + ' <span>يومًا</span>'
        : 'الصلاحية: بلا انتهاء محدد';
      /* Every pool entry shows on the card: included ids get the green
         mark, the rest the red one — the buyer reads the tier difference
         off one list. Raw (legacy free-text) entries append as included. */
      const enabled = new Set(Array.isArray(p.features) ? p.features : []);
      const known = new Set((llPackageFeatureCatalog || []).map(f => f.id));
      const features = (llPackageFeatureCatalog || []).map(f => {
        const on = enabled.has(f.id);
        // The marks are CSS-drawn (no icon glyphs — hard product rule).
        return '<div class="pkg-feat ' + (on ? 'pkg-feat-on' : 'pkg-feat-off') + '">' +
          '<span class="pkg-feat-mark" aria-hidden="true"></span>' +
          '<span>' + llEscape(wfBilingual(f.ar, f.en)) + '</span></div>';
      }).join('') + (Array.isArray(p.features) ? p.features : [])
        .filter(f => f && !known.has(f))
        .map(f => '<div class="pkg-feat pkg-feat-on">' +
          '<span class="pkg-feat-mark" aria-hidden="true"></span>' +
          '<span>' + llEscape(f) + '</span></div>')
        .join('');
      return '<div class="pkg-card pkg-pick' + (selected ? ' selected' : '') +
        (p.is_featured ? ' pkg-card--featured' : '') + '"' +
        ' data-pkg-id="' + llEscape(p.id) + '" role="button" tabindex="0"' +
        ' onclick="llPickRechargePackage(\'' + llEscape(p.id) + '\')">' +
        (badge ? '<span class="pkg-badge">' + llEscape(badge) + '</span>' : '') +
        '<h3>' + llEscape(wfBilingual(p.name, p.name_en)) + '</h3>' +
        '<div class="pkg-price"><span class="pkg-price-num">' +
        (p.price_sar != null ? llEscape(llMoney(p.price_sar)) : 'بلا سعر') + '</span>' +
        (p.price_sar != null ? ' <span class="pkg-price-cur">ريال سعودي</span>' : '') +
        '</div>' +
        '<hr class="pkg-hr">' +
        '<div class="pkg-mid">' +
        '<div class="pkg-credit-label">رصيد الاستخدام</div>' +
        '<div class="pkg-credit-num">' + llEscape(llMoney(p.credit_sar)) +
        ' <span class="pkg-credit-unit">نقطة</span></div>' +
        (tagline ? '<div class="pkg-card-meta">' + llEscape(tagline) + '</div>' : '') +
        features +
        '<div class="pkg-card-meta">' + validity + '</div>' +
        '</div>' +
        '<div class="pkg-card-foot">' +
        '<button type="button" class="btn primary pkg-buy">اطلب الآن</button>' +
        '</div></div>';
    }

    /* Picking a card on the packages tab stores the id, marks the card and
       opens the compact transfer-details modal. The «باقة مخصصة» pick needs
       a keyed amount first — without it the focus just lands on the input. */
    function llPickRechargePackage(packageId) {
      const input = document.getElementById('llRechargePackage');
      if (packageId === '__custom__') {
        // Clone cards duplicate the input — take whichever copy is filled.
        const inputs = Array.from(document.querySelectorAll('.pkg-custom-input'));
        const amt = Math.max.apply(null, [0].concat(
          inputs.map(i => Number(i.value || 0))));
        if (!(amt > 0)) {
          const target = inputs.find(i => i.offsetParent) || inputs[0];
          if (target) target.focus();
          return;
        }
        llCustomPackageAmount = Math.round(amt * 100) / 100;
      }
      if (input) input.value = packageId || '';
      document.querySelectorAll('.pkg-pick, .pkg-card--custom').forEach(card => {
        card.classList.toggle('selected',
          card.getAttribute('data-pkg-id') === packageId);
      });
      llShowPackageInfo();
      if (packageId) {
        // A pick made inside the modal advances to the proof step; a pick
        // from the «الباقات» tab opens the modal straight on that step.
        if (typeof llShowRechargeStep === 'function') llShowRechargeStep('proof');
        if (typeof openLlModal === 'function') openLlModal('llRechargeModal');
      }
    }

    /* ── Super-admin catalog ──────────────────────────────────────────── */

    function llAdminPackageCardHtml(p) {
      const price = p.price_sar != null
        ? llEscape(llMoney(p.price_sar)) + ' <span>ريال سعودي</span>'
        : 'بلا سعر';
      const cost = p.est_cost_sar != null
        ? '<div class="pkg-card-meta">' +
          llEscape(WFT('pkg.est_cost', 'التكلفة التقديرية: {cost} نقطة', { cost: llMoney(p.est_cost_sar) })) + '</div>' : '';
      const margin = p.est_margin_sar != null
        ? '<div class="pkg-card-meta">' +
          llEscape(WFT('pkg.est_margin', 'الربح التقديري: {margin} نقطة', { margin: llMoney(p.est_margin_sar) })) + '</div>' : '';
      const badge = p.badge || p.badge_en
        ? '<div class="pkg-card-meta">' + llEscape(wfBilingual(p.badge, p.badge_en)) + '</div>' : '';
      const pool = llPackageFeatureCatalog || [];
      const onCount = (Array.isArray(p.features) ? p.features : [])
        .filter(id => pool.some(f => f.id === id)).length;
      const featsMeta = pool.length
        ? '<div class="pkg-card-meta">' + llEscape(WFT('pkg.features_count', 'المزايا المتاحة: {on} / {total}', { on: onCount, total: pool.length })) + '</div>'
        : '';
      const durMeta = p.duration_days
        ? '<div class="pkg-card-meta">' + llEscape(WFT('pkg.validity_days', 'الصلاحية: {days} يومًا', { days: p.duration_days })) + '</div>' : '';
      return '<div class="pkg-card">' +
        '<h3>' + llEscape(wfBilingual(p.name, p.name_en)) + '</h3>' +
        badge +
        '<div class="pkg-card-points">' + price + '</div>' +
        '<div class="pkg-card-meta">' + llEscape(llMoney(p.credit_sar)) +
        ' <span>نقطة</span></div>' +
        cost + margin + featsMeta + durMeta +
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
