/* Public pages: language toggle (lang-tagged markup, one CSS rule hides the
   inactive half) and the landing "request access" form. External file only —
   the site CSP allows no inline scripts. */
(function () {
  'use strict';

  var LANG_KEY = 'll_site_lang';

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
      el.innerHTML =
        '<span lang="ar"></span><span lang="en"></span>';
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
})();
