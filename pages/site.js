/* Public pages: language toggle (lang-tagged markup, one CSS rule hides the
   inactive half), the landing "request a demo" form, and the page's motion —
   scroll reveals, metric counters, mockup tilt and the scrolled topbar.
   External file only — the site CSP allows no inline scripts, and every
   effect sits behind prefers-reduced-motion. */
(function () {
  'use strict';

  var LANG_KEY = 'll_site_lang';
  var reduceMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  document.body.classList.add('js');

  function currentLang() {
    return document.documentElement.lang === 'en' ? 'en' : 'ar';
  }

  function applyLang(lang) {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === 'en' ? 'ltr' : 'rtl';
    try { localStorage.setItem(LANG_KEY, lang); } catch (e) { /* private mode */ }
  }

  function savedLang() {
    try { return localStorage.getItem(LANG_KEY); } catch (e) { return null; }
  }

  function authedSwap() {
    // A signed-in visitor gets a straight path to the workspace instead of
    // the generic sign-in label. The token check is presence-only; the app
    // itself validates the session.
    var hasToken = false;
    try { hasToken = !!localStorage.getItem('tenant_token'); } catch (e) { /* ignore */ }
    if (!hasToken) return;
    document.querySelectorAll('[data-authed-ar]').forEach(function (el) {
      el.innerHTML = '<span lang="ar"></span><span lang="en"></span>';
      el.querySelector('[lang="ar"]').textContent = el.getAttribute('data-authed-ar');
      el.querySelector('[lang="en"]').textContent = el.getAttribute('data-authed-en');
    });
  }

  function initLang() {
    var saved = savedLang();
    if (saved === 'en' || saved === 'ar') applyLang(saved);
    document.querySelectorAll('[data-lang-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        applyLang(currentLang() === 'ar' ? 'en' : 'ar');
      });
    });
  }

  /* ── Motion ────────────────────────────────────────────────────────────── */

  function initReveal() {
    var targets = document.querySelectorAll('[data-reveal], [data-reveal-group]');
    if (reduceMotion || !('IntersectionObserver' in window)) {
      targets.forEach(function (el) { el.classList.add('in'); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: .15, rootMargin: '0px 0px -8% 0px' });
    targets.forEach(function (el) { io.observe(el); });
  }

  function animateCount(el) {
    var target = parseFloat(el.getAttribute('data-count-to')) || 0;
    var prefix = el.getAttribute('data-count-prefix') || '';
    var suffix = el.getAttribute('data-count-suffix') || '';
    var dec = parseInt(el.getAttribute('data-count-decimals') || '0', 10);
    var duration = 1400;
    var start = null;
    function fmt(v) {
      return prefix + v.toLocaleString('en-US', {
        minimumFractionDigits: dec, maximumFractionDigits: dec
      }) + suffix;
    }
    function step(ts) {
      if (start === null) start = ts;
      var p = Math.min(1, (ts - start) / duration);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(target * eased);
      if (p < 1) window.requestAnimationFrame(step);
    }
    window.requestAnimationFrame(step);
  }

  function initCounters() {
    if (reduceMotion) return;
    var els = document.querySelectorAll('[data-count-to]');
    if (!els.length) return;
    // The deck mockup enters ~.5s into the page load; let it land first.
    window.setTimeout(function () {
      els.forEach(animateCount);
    }, 600);
  }

  function initTilt() {
    if (reduceMotion || !window.matchMedia('(hover: hover)').matches) return;
    var vis = document.querySelector('.hero-visual');
    var card = vis && vis.querySelector('.deck-card.main');
    var back = vis && vis.querySelector('.deck-card.back');
    if (!vis || !card) return;
    vis.addEventListener('mousemove', function (ev) {
      var r = vis.getBoundingClientRect();
      var x = (ev.clientX - r.left) / r.width - .5;
      var y = (ev.clientY - r.top) / r.height - .5;
      card.style.transform =
        'perspective(900px) rotateX(' + (-y * 7).toFixed(2) + 'deg) ' +
        'rotateY(' + (x * 9).toFixed(2) + 'deg) rotate(-2.5deg)';
      if (back) {
        back.style.transform =
          'rotate(2deg) translate(' + (-x * 12).toFixed(1) + 'px,' + (-y * 10).toFixed(1) + 'px)';
      }
    });
    vis.addEventListener('mouseleave', function () {
      card.style.transform = '';
      if (back) back.style.transform = '';
    });
  }

  function initSpotlight() {
    // Cursor-tracked radial glow on dark glass surfaces. Cheap — one
    // pointermove per card, two custom properties, CSS does the rest.
    if (reduceMotion || !window.matchMedia('(hover: hover)').matches) return;
    document.querySelectorAll('.feature-card, .file-item').forEach(function (el) {
      el.addEventListener('pointermove', function (ev) {
        var r = el.getBoundingClientRect();
        el.style.setProperty('--mx', ((ev.clientX - r.left) / r.width * 100).toFixed(1) + '%');
        el.style.setProperty('--my', ((ev.clientY - r.top) / r.height * 100).toFixed(1) + '%');
      });
    });
  }

  function initTopbar() {
    var bar = document.querySelector('.site-topbar.on-dark');
    if (!bar) return;
    var onScroll = function () {
      bar.classList.toggle('scrolled', window.scrollY > 40);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* ── Opening: auto-played cinematic ──────────────────────────────────────
     On entry the camera pushes in over the map while the Saudi border draws
     itself, a beacon lands on Riyadh, and LANDLOOM collapses out of a wide
     tracking blur into its lockup — then the overlay zooms through and the
     hero takes over. One rAF clock scrubs the whole timeline; click or
     Escape skips to the last frame. body.intro-done fires the CSS exit and
     releases the hero entrance (initHeroEnter listens for ll:intro-done).
     Reduced-motion removes the overlay outright; without JS it never shows
     (body.js gates .intro's display). */

  function initOpening() {
    var intro = document.getElementById('intro');
    if (!intro) return;
    if (reduceMotion) {
      intro.parentNode.removeChild(intro);
      return;
    }

    var path = document.getElementById('introPath');
    var cam = document.getElementById('introCam');
    var sweep = document.getElementById('introSweep');
    var beacon = document.getElementById('introBeacon');
    var pin = document.getElementById('introPin');
    var brand = document.getElementById('introBrand');
    var uline = document.getElementById('introUline');
    var sloganEl = document.getElementById('introSlogan');
    if (!path || !cam) {
      // Markup mismatch — never leave a dead overlay covering the page.
      intro.parentNode.removeChild(intro);
      document.body.classList.add('intro-done');
      document.dispatchEvent(new CustomEvent('ll:intro-done'));
      return;
    }
    var len = path.getTotalLength();
    path.style.strokeDasharray = len;
    path.style.strokeDashoffset = len;

    function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
    function seg(t, a, b) { return clamp((t - a) / (b - a), 0, 1); }
    function ease(p) { return 1 - Math.pow(1 - p, 3); }
    function eio(p) { return p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; }
    function eob(p) { var c = 1.70158; return 1 + (c + 1) * Math.pow(p - 1, 3) + c * Math.pow(p - 1, 2); }
    function lerp(a, b, p) { return a + (b - a) * p; }
    function eoquint(p) { return 1 - Math.pow(1 - p, 5); }

    function render(t) {
      // Camera: the scene starts zoomed and reclined, then levels out flat.
      var cp = eoquint(seg(t, 0, 2900));
      cam.style.transform =
        'translateY(' + lerp(9, 0, cp).toFixed(2) + '%) ' +
        'rotateX(' + lerp(26, 0, cp).toFixed(2) + 'deg) ' +
        'scale(' + lerp(1.55, 1, cp).toFixed(4) + ')';

      var draw = eio(seg(t, 350, 2700));
      path.style.strokeDashoffset = len * (1 - draw);
      path.style.fillOpacity = (.07 * seg(t, 2400, 3000)).toFixed(3);

      // One diagonal light pass crosses the stage mid-draw.
      sweep.style.transform = 'translateX(' + lerp(-140, 520, eio(seg(t, 800, 2150))).toFixed(1) + '%)';

      // Beacon column rises from the pin point, then eases back.
      var bl = ease(seg(t, 2700, 3020));
      beacon.setAttribute('y2', (310 - 150 * bl).toFixed(1));
      beacon.style.opacity = (bl * (1 - .6 * seg(t, 3400, 4100))).toFixed(3);

      var ps = seg(t, 2750, 3150);
      pin.style.opacity = ps;
      pin.style.transform = 'scale(' + Math.max(eob(ps), .001).toFixed(3) + ')';
      pin.classList.toggle('show', ps >= 1);

      // Wordmark: ultra-tracked blur collapses into the final lockup.
      var bp = eio(seg(t, 2300, 3350));
      brand.style.opacity = seg(t, 2300, 2850).toFixed(3);
      brand.style.letterSpacing = lerp(.85, .14, bp).toFixed(3) + 'em';
      brand.style.filter = 'blur(' + lerp(12, 0, bp).toFixed(1) + 'px)';

      uline.style.transform = 'scaleX(' + ease(seg(t, 3300, 3720)).toFixed(3) + ')';

      var sl = ease(seg(t, 3550, 4150));
      sloganEl.style.opacity = sl.toFixed(3);
      sloganEl.style.transform = 'translateY(' + ((1 - sl) * 16).toFixed(1) + 'px)';
    }

    var DUR = 5000;
    var t0 = performance.now();
    var skipped = false;
    var done = false;

    document.documentElement.classList.add('intro-lock');

    function finish() {
      if (done) return;
      done = true;
      document.documentElement.classList.remove('intro-lock');
      document.body.classList.add('intro-done');
      document.dispatchEvent(new CustomEvent('ll:intro-done'));
    }

    function loop(now) {
      var t = skipped ? DUR : now - t0;
      render(Math.min(t, DUR));
      if (t >= DUR) { finish(); return; }
      window.requestAnimationFrame(loop);
    }

    function skip() { skipped = true; }
    intro.addEventListener('click', skip);
    document.addEventListener('keydown', function (ev) {
      if ((ev.key === 'Escape' || ev.key === ' ') && !done) skip();
    });
    render(0);
    window.requestAnimationFrame(loop);
  }

  /* ── Hero entrance ───────────────────────────────────────────────────────
     body.entered fires the hero's staggered riseIn/deckIn animations and the
     metric counters. It trips when the hero scrolls ~a fifth into view — but
     only after the intro overlay has zoomed through (ll:intro-done), so the
     entrance never plays unseen behind it. Pages without a hero get it
     immediately. */

  function initHeroEnter() {
    var hero = document.querySelector('.hero');
    function go() {
      if (!hero || !('IntersectionObserver' in window)) {
        document.body.classList.add('entered');
        initCounters();
        return;
      }
      var io = new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting) {
          document.body.classList.add('entered');
          initCounters();
          io.disconnect();
        }
      }, { threshold: .22 });
      io.observe(hero);
    }
    if (document.getElementById('intro') && !document.body.classList.contains('intro-done')) {
      document.addEventListener('ll:intro-done', go, { once: true });
    } else {
      go();
    }
  }

  /* ── Showcase: interactive deck viewer ─────────────────────────────────── */

  // Real decks rendered by the platform itself — every slide ships as a JPEG
  // under /pages/decks/<slug>/. Each file keeps the brand accent its tenant
  // palette produced, so the list dots match the deck colors.
  var SHOWCASE_FILES = [
    { name: 'واحة النخيل السكنية', meta: 'عرض مشروع سكني · 6 شرائح', accent: '#0F4C81', slug: 'nakheel', count: 6 },
    { name: 'حي الياسمين', meta: 'تحليل أرض وخرائط · 9 شرائح', accent: '#1E7A4F', slug: 'yasmin', count: 9 },
    { name: 'برج الرواف التجاري', meta: 'دراسة مالية · 18 شريحة', accent: '#0FA9C4', slug: 'rawaf', count: 18 },
    { name: 'مجمع الضياء اللوجستي', meta: 'دراسة سوق · 18 شريحة', accent: '#B45A1B', slug: 'diyaa', count: 18 },
    { name: 'فندق مرافق البوتيك', meta: 'جدول زمني · 6 شرائح', accent: '#6D3FA3', slug: 'marafiq', count: 6 }
  ];
  SHOWCASE_FILES.forEach(function (f) {
    f.slides = [];
    for (var n = 1; n <= f.count; n++) {
      f.slides.push('/pages/decks/' + f.slug + '/' + (n < 10 ? '0' : '') + n + '.jpg');
    }
  });

  var showcaseFile = 0;
  var showcaseSlide = 0;

  function slideHtml(file, slideIdx) {
    return '<img class="ms-real" src="' + file.slides[slideIdx] + '" ' +
      'alt="' + file.name + ' — شريحة ' + (slideIdx + 1) + '" ' +
      'width="1440" height="810" loading="lazy" decoding="async">';
  }

  function renderShowcaseSlide(dir) {
    var stage = document.getElementById('deckStage');
    var counter = document.getElementById('deckCounter');
    var file = SHOWCASE_FILES[showcaseFile];
    if (!stage || !file) return;
    stage.innerHTML = slideHtml(file, showcaseSlide);
    stage.classList.remove('swap-next', 'swap-prev');
    if (dir) {
      void stage.offsetWidth;
      stage.classList.add(dir === 'prev' ? 'swap-prev' : 'swap-next');
    }
    if (counter) counter.textContent = (showcaseSlide + 1) + ' / ' + file.slides.length;
    var prev = document.getElementById('deckPrev');
    var next = document.getElementById('deckNext');
    if (prev) prev.disabled = showcaseSlide === 0;
    if (next) next.disabled = showcaseSlide === file.slides.length - 1;
  }

  function selectShowcaseFile(idx, animate) {
    showcaseFile = idx;
    showcaseSlide = 0;
    document.querySelectorAll('.file-item').forEach(function (el, i) {
      el.classList.toggle('active', i === idx);
    });
    renderShowcaseSlide(animate ? 'next' : null);
  }

  function initShowcase() {
    var list = document.getElementById('showcaseFiles');
    var stage = document.getElementById('deckStage');
    if (!list || !stage) return;
    list.innerHTML = SHOWCASE_FILES.map(function (f, i) {
      return '<button type="button" class="file-item" style="--f-accent:' + f.accent + '" data-idx="' + i + '">' +
        '<span class="f-dot"></span>' +
        '<span class="f-text"><span class="f-name">' + f.name + '</span>' +
        '<span class="f-meta">' + f.meta + '</span></span></button>';
    }).join('');
    list.addEventListener('click', function (ev) {
      var btn = ev.target.closest('.file-item');
      if (btn) selectShowcaseFile(parseInt(btn.getAttribute('data-idx'), 10), true);
    });
    var prev = document.getElementById('deckPrev');
    var next = document.getElementById('deckNext');
    if (prev) prev.addEventListener('click', function () {
      if (showcaseSlide > 0) { showcaseSlide--; renderShowcaseSlide('prev'); }
    });
    if (next) next.addEventListener('click', function () {
      var file = SHOWCASE_FILES[showcaseFile];
      if (showcaseSlide < file.slides.length - 1) { showcaseSlide++; renderShowcaseSlide('next'); }
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.target && /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
      var file = SHOWCASE_FILES[showcaseFile];
      if (ev.key === 'ArrowLeft' && showcaseSlide < file.slides.length - 1) {
        showcaseSlide++; renderShowcaseSlide('next');
      } else if (ev.key === 'ArrowRight' && showcaseSlide > 0) {
        showcaseSlide--; renderShowcaseSlide('prev');
      }
    });
    selectShowcaseFile(0, false);
  }

  /* ── Request-access form ───────────────────────────────────────────────── */

  function formStrings(key) {
    var ar = {
      sending: 'جارٍ الإرسال…',
      ok: 'وصلنا طلبك — سيتواصل معك فريقنا قريبًا.',
      err: 'تعذّر إرسال الطلب. تأكد من البيانات وأعد المحاولة.',
      rate: 'عدد المحاولات كبير — أعد المحاولة لاحقًا.'
    };
    var en = {
      sending: 'Sending…',
      ok: 'Request received — our team will reach out soon.',
      err: 'Could not send the request. Check the fields and try again.',
      rate: 'Too many attempts — please try again later.'
    };
    return (currentLang() === 'en' ? en : ar)[key];
  }

  function initJoinForm() {
    var form = document.getElementById('joinRequestForm');
    if (!form) return;
    var status = document.getElementById('joinRequestStatus');
    var submitBtn = form.querySelector('[type="submit"]');

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (submitBtn) submitBtn.disabled = true;
      if (status) { status.textContent = formStrings('sending'); status.className = 'form-status'; }

      var payload = {
        name: (form.elements.name && form.elements.name.value || '').trim(),
        company: (form.elements.company && form.elements.company.value || '').trim(),
        email: (form.elements.email && form.elements.email.value || '').trim(),
        phone: (form.elements.phone && form.elements.phone.value || '').trim(),
        message: (form.elements.message && form.elements.message.value || '').trim(),
        website: (form.elements.website && form.elements.website.value || '').trim()
      };

      fetch('/api/join-requests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(function (res) {
        if (res.ok) {
          if (status) { status.textContent = formStrings('ok'); status.className = 'form-status ok'; }
          form.reset();
        } else if (res.status === 429) {
          if (status) { status.textContent = formStrings('rate'); status.className = 'form-status err'; }
        } else {
          if (status) { status.textContent = formStrings('err'); status.className = 'form-status err'; }
        }
      }).catch(function () {
        if (status) { status.textContent = formStrings('err'); status.className = 'form-status err'; }
      }).finally(function () {
        if (submitBtn) submitBtn.disabled = false;
      });
    });
  }

  initLang();
  authedSwap();
  initJoinForm();
  initReveal();
  initTilt();
  initSpotlight();
  initTopbar();
  initShowcase();
  initOpening();
  initHeroEnter();
})();
