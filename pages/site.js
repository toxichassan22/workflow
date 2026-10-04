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
  initCounters();
  initTilt();
  initMarquee();
  initTopbar();
})();
