/* Public pages: language toggle (lang-tagged markup, one CSS rule hides the
   inactive half), the landing "request access" form, and the page's motion —
   scroll reveals, metric counters, mockup tilt, the outputs marquee and the
   scrolled topbar. External file only — the site CSP allows no inline
   scripts, and every effect sits behind prefers-reduced-motion. */
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

  function initMarquee() {
    var track = document.querySelector('.outputs-marquee');
    var set = track && track.querySelector('.mq-set');
    if (!track || !set || reduceMotion) return;
    var clone = set.cloneNode(true);
    clone.setAttribute('aria-hidden', 'true');
    track.appendChild(clone);
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

  /* ── Opening sequence: scroll-scrubbed ───────────────────────────────────
     The track is a tall in-flow section whose stage sticks to the viewport;
     real scroll position drives everything — the welcome lifts out through
     the first stretch, the caret fades in, and LANDLOOM AI types letter by
     letter across the second stretch (scroll back up and it deletes). Escape
     jumps past the whole thing. Reduced-motion drops the track in CSS. */

  function initOpening() {
    var track = document.getElementById('opening');
    if (!track) return;
    if (reduceMotion) {
      track.parentNode.removeChild(track);
      return;
    }

    var welcomeEl = track.querySelector('.op-welcome');
    var brandEl = track.querySelector('.op-brand');
    var typedEl = track.querySelector('.op-typed');
    var typedAi = track.querySelector('.op-typed.op-ai');
    var cueEl = track.querySelector('.op-cue');
    var brandText = '';
    Array.prototype.forEach.call(track.querySelectorAll('.op-typed'), function (el) {
      brandText += el.textContent;
      el.textContent = '';
    });
    var splitAt = brandText.lastIndexOf(' ') + 1;

    var typed = -1;
    var raf = 0;

    function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }

    function render() {
      raf = 0;
      var rect = track.getBoundingClientRect();
      var span = rect.height - window.innerHeight;
      var p = span > 0 ? clamp(-rect.top / span, 0, 1) : 0;

      // Welcome holds through p .10, then lifts out by p .32.
      var we = clamp((p - .10) / .22, 0, 1);
      if (welcomeEl) {
        welcomeEl.style.opacity = (1 - we).toFixed(3);
        welcomeEl.style.transform = 'translateY(' + (-70 * we).toFixed(1) + 'px) scale(' + (1 + .06 * we).toFixed(3) + ')';
        welcomeEl.style.filter = we > 0 ? 'blur(' + (9 * we).toFixed(1) + 'px)' : '';
      }
      if (cueEl) cueEl.style.opacity = (1 - clamp(p / .07, 0, 1)).toFixed(3);

      // Brand fades in p .30 → .38, then types across p .38 → .88.
      if (brandEl) brandEl.style.opacity = clamp((p - .30) / .08, 0, 1).toFixed(3);
      if (typedEl) {
        var n = Math.round(clamp((p - .38) / .5, 0, 1) * brandText.length);
        if (n !== typed) {
          typedEl.textContent = brandText.slice(0, Math.min(n, splitAt));
          if (typedAi) typedAi.textContent = brandText.slice(splitAt, Math.max(splitAt, n));
          typed = n;
        }
      }
    }

    function onScroll() {
      if (!raf) raf = window.requestAnimationFrame(render);
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && track.getBoundingClientRect().bottom > 0) {
        window.scrollTo(0, track.offsetTop + track.offsetHeight);
      }
    });
    render();
  }

  /* ── Hero entrance ───────────────────────────────────────────────────────
     body.entered fires the hero's staggered riseIn/deckIn animations and the
     metric counters. It trips when the hero scrolls ~a fifth into view —
     which is right after the opening track ends. Pages without a hero get it
     immediately. */

  function initHeroEnter() {
    var hero = document.querySelector('.hero');
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

  /* ── Showcase: interactive deck viewer ─────────────────────────────────── */

  // Mock files and slides — stand-ins for real generated decks, each carrying
  // the client brand accent it was "designed" under.
  var SHOWCASE_FILES = [
    {
      name: 'عرض استثماري — حي الياسمين', meta: 'شركة الأفق · الرياض', accent: '#123B6D', logo: 'أ',
      slides: [
        { t: 'cover', title: 'عرض استثماري — حي الياسمين', sub: 'شركة الأفق للتطوير العقاري · الرياض' },
        { t: 'metrics', kicker: 'دراسة سوق', h: 'مؤشرات الطلب في النطاق', metrics: [['+34%', 'نمو الطلب'], ['8,250', 'سكن في النطاق'], ['91%', 'معدل الإشغال']], lines: 2 },
        { t: 'map', kicker: 'تحليل الموقع', h: 'الموقع والمحيط العمراني' },
        { t: 'metrics', kicker: 'النموذج المالي', h: 'المؤشرات الاستثمارية', metrics: [['12.4%', 'العائد المتوقع'], ['4.2', 'سنوات الاسترداد'], ['+18%', 'صافي التدفق']], lines: 2 },
        { t: 'closing', h: 'شكرًا', sub: 'شركة الأفق للتطوير العقاري' }
      ]
    },
    {
      name: 'دراسة جدوى — أرض الصحافة', meta: 'إسكان الشمال · الرياض', accent: '#0D7B55', logo: 'إ',
      slides: [
        { t: 'cover', title: 'دراسة جدوى — أرض الصحافة', sub: 'إسكان الشمال · الرياض' },
        { t: 'map', kicker: 'تحليل الموقع', h: 'الأرض وحدودها والوصول' },
        { t: 'metrics', kicker: 'دراسة السوق', h: 'العرض والطلب', metrics: [['1,940', 'وحدة معروضة'], ['+21%', 'نمو الأسعار'], ['6.8', 'أشهر التصريف']], lines: 2 },
        { t: 'closing', h: 'شكرًا', sub: 'إسكان الشمال' }
      ]
    },
    {
      name: 'عرض برج الواجهة البحرية', meta: 'مجموعة الريادة · جدة', accent: '#14B8A6', logo: 'ر',
      slides: [
        { t: 'cover', title: 'عرض برج الواجهة البحرية', sub: 'مجموعة الريادة · جدة' },
        { t: 'metrics', kicker: 'ملخص تنفيذي', h: 'أرقام المشروع', metrics: [['28', 'طابقًا'], ['340', 'وحدة فندقية'], ['1.2B', 'قيمة المشروع']], lines: 2 },
        { t: 'map', kicker: 'تحليل الموقع', h: 'الواجهة البحرية والمعالم' },
        { t: 'metrics', kicker: 'دراسة السوق', h: 'سياحة جدة', metrics: [['+27%', 'نمو الزوار'], ['84%', 'إشغال الفنادق'], ['5', 'معالم قريبة']], lines: 2 },
        { t: 'closing', h: 'شكرًا', sub: 'مجموعة الريادة' }
      ]
    },
    {
      name: 'تطوير مخطط النرجس', meta: 'ديار للتطوير · الرياض', accent: '#A65B00', logo: 'د',
      slides: [
        { t: 'cover', title: 'تطوير مخطط النرجس', sub: 'ديار للتطوير · الرياض' },
        { t: 'map', kicker: 'تحليل الموقع', h: 'المخطط والبنية المحيطة' },
        { t: 'metrics', kicker: 'النموذج المالي', h: 'الجدوى', metrics: [['9.8%', 'العائد'], ['520', 'قطعة أرض'], ['3.1', 'سنوات البيع']], lines: 2 },
        { t: 'closing', h: 'شكرًا', sub: 'ديار للتطوير' }
      ]
    },
    {
      name: 'عرض مجمع الورود السكني', meta: 'شركة الورود · الدمام', accent: '#5B3A8E', logo: 'و',
      slides: [
        { t: 'cover', title: 'عرض مجمع الورود السكني', sub: 'شركة الورود · الدمام' },
        { t: 'metrics', kicker: 'دراسة سوق', h: 'الطلب السكني', metrics: [['+19%', 'نمو الطلب'], ['3,400', 'أسرة مستهدفة'], ['95%', 'إشغال متوقع']], lines: 2 },
        { t: 'map', kicker: 'تحليل الموقع', h: 'الموقع والخدمات' },
        { t: 'closing', h: 'شكرًا', sub: 'شركة الورود' }
      ]
    },
    {
      name: 'دراسة أرض حي العارض', meta: 'شركة المدار · الرياض', accent: '#B3346B', logo: 'م',
      slides: [
        { t: 'cover', title: 'دراسة أرض حي العارض', sub: 'شركة المدار · الرياض' },
        { t: 'map', kicker: 'تحليل الموقع', h: 'الأرض ومناطق التقاط' },
        { t: 'metrics', kicker: 'دراسة السوق', h: 'التنافسية', metrics: [['12', 'مشروع منافس'], ['+8%', 'فارق التسعير'], ['4.5', 'أشهر التصريف']], lines: 2 },
        { t: 'metrics', kicker: 'النموذج المالي', h: 'العائد', metrics: [['11.2%', 'العائد المتوقع'], ['3.8', 'سنوات الاسترداد'], ['+15%', 'صافي التدفق']], lines: 2 },
        { t: 'closing', h: 'شكرًا', sub: 'شركة المدار' }
      ]
    }
  ];

  var showcaseFile = 0;
  var showcaseSlide = 0;

  function msFoot(brand, page) {
    return '<div class="ms-foot"><span>' + brand + '</span><b>' + page + '</b></div>';
  }

  function slideHtml(slide, file, page) {
    var a = file.accent;
    if (slide.t === 'cover') {
      return '<div class="ms ms-cover" style="--msa:' + a + '">' +
        '<div class="ms-logo">' + file.logo + '</div>' +
        '<h4 class="ms-title">' + slide.title + '</h4>' +
        '<p class="ms-sub">' + slide.sub + '</p>' + msFoot('LandLoom', page) + '</div>';
    }
    if (slide.t === 'map') {
      return '<div class="ms" style="--msa:' + a + '">' +
        '<div class="ms-bar"></div><div class="ms-kicker">' + slide.kicker + '</div>' +
        '<h4 class="ms-h">' + slide.h + '</h4>' +
        '<div class="ms-map"><span class="ms-pin"></span></div>' + msFoot('LandLoom', page) + '</div>';
    }
    if (slide.t === 'closing') {
      return '<div class="ms ms-closing" style="--msa:' + a + '">' +
        '<div class="ms-logo">' + file.logo + '</div>' +
        '<h4 class="ms-h">' + slide.h + '</h4>' +
        '<p class="ms-sub">' + slide.sub + '</p></div>';
    }
    var tiles = (slide.metrics || []).map(function (m) {
      return '<div><b>' + m[0] + '</b><span>' + m[1] + '</span></div>';
    }).join('');
    var lines = '';
    for (var i = 0; i < (slide.lines || 0); i++) lines += '<i></i>';
    return '<div class="ms" style="--msa:' + a + '">' +
      '<div class="ms-bar"></div><div class="ms-kicker">' + slide.kicker + '</div>' +
      '<h4 class="ms-h">' + slide.h + '</h4>' +
      '<div class="ms-metrics">' + tiles + '</div>' +
      '<div class="ms-lines">' + lines + '</div>' + msFoot('LandLoom', page) + '</div>';
  }

  function renderShowcaseSlide(dir) {
    var stage = document.getElementById('deckStage');
    var counter = document.getElementById('deckCounter');
    var file = SHOWCASE_FILES[showcaseFile];
    if (!stage || !file) return;
    stage.innerHTML = slideHtml(file.slides[showcaseSlide], file, showcaseSlide + 1);
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
  initMarquee();
  initTopbar();
  initShowcase();
  initOpening();
  initHeroEnter();
})();
