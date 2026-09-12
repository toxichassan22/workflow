/* ============================================================================
 * Manafe / Workflow — UI internationalization (i18n) foundation.
 *
 * OWNER RULE FOR ALL FUTURE WORK (enforced by tests/test_i18n.py):
 *   1. New UI strings go HERE first, in BOTH languages, then are referenced
 *      from code with WFT('section.key', 'Arabic fallback') in JS or
 *      data-i18n="section.key" in static HTML (data-i18n-ph for placeholders,
 *      data-i18n-title for titles, data-i18n-aria for aria-labels).
 *   2. Never add a new hardcoded Arabic UI literal to toast() / confirm() /
 *      placeholder="" / showLoader() / hideLoader() / updateLoaderProgress().
 *      The suite keeps a baseline of the legacy literals and fails when a new
 *      one appears. If you migrate an old literal to WFT()/data-i18n, the
 *      baseline entry for it may be dropped (it only ever shrinks).
 *   3. Static HTML keeps its Arabic text content as the fallback, so the page
 *      still reads correctly if this file ever fails to load, and
 *      WFT(key, fallback) always renders the fallback when the key is absent.
 *
 * Loading: index.html includes this file with an ABSOLUTE path
 * (<script src="/assets/i18n.js">) BEFORE the main inline script, so WFI18n
 * and WFT exist before any application code runs. The path must stay absolute:
 * client routes (/app/..., /c/<slug>, /superadmin/...) would resolve a
 * relative "assets/..." URL against the deep link and 404.
 *
 * Language choice is per device (localStorage "wf.lang", default "ar").
 * A per-tenant default from company settings can be layered on later; it must
 * only ever act as the initial value, never override an explicit choice.
 *
 * The two dict blocks below are JSON-compatible on purpose (double quotes, no
 * trailing commas) between the I18N_*_BEGIN/END markers so the Python suite
 * can parse and validate them. Edit the text, never the markers.
 * ========================================================================== */
(function () {
  'use strict';

  var WFI18N_AR = /*I18N_AR_BEGIN*/{
    "lang.switch_to_arabic": "عربي",
    "lang.switch_to_english": "English",
    "loader.done": "اكتمل",
    "loader.loaded": "اكتمل التحميل",
    "loader.loading": "جاري التحميل...",
    "loader.preparing": "جاري التحضير...",
    "loader.preparing_file": "جاري تجهيز الملف للتحميل...",
    "loader.uploading_file": "جاري تحميل الملف ({pct}%)...",
    "nav.admin": "لوحة المدير",
    "nav.ai_rules": "قواعد AI",
    "nav.approve_offers": "تعميد العروض",
    "nav.company_settings": "إعدادات الشركة",
    "nav.dev_team": "فريق التطوير",
    "nav.fields": "الحقول",
    "nav.logout": "خروج",
    "nav.menu": "القائمة",
    "nav.new_proposal": "عرض جديد",
    "nav.projects": "المشاريع",
    "nav.staff": "الموظفون"
  }/*I18N_AR_END*/;

  var WFI18N_EN = /*I18N_EN_BEGIN*/{
    "lang.switch_to_arabic": "عربي",
    "lang.switch_to_english": "English",
    "loader.done": "Done",
    "loader.loaded": "Loading complete",
    "loader.loading": "Loading...",
    "loader.preparing": "Preparing...",
    "loader.preparing_file": "Preparing the file for download...",
    "loader.uploading_file": "Uploading file ({pct}%)...",
    "nav.admin": "Admin panel",
    "nav.ai_rules": "AI rules",
    "nav.approve_offers": "Offer approvals",
    "nav.company_settings": "Company settings",
    "nav.dev_team": "Development team",
    "nav.fields": "Fields",
    "nav.logout": "Log out",
    "nav.menu": "Menu",
    "nav.new_proposal": "New proposal",
    "nav.projects": "Projects",
    "nav.staff": "Staff"
  }/*I18N_EN_END*/;

  var DICTS = { ar: WFI18N_AR, en: WFI18N_EN };
  var SUPPORTED = ['ar', 'en'];
  var STORAGE_KEY = 'wf.lang';
  var DEFAULT_LANG = 'ar';

  function getLang() {
    try {
      var stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === 'ar' || stored === 'en') return stored;
    } catch (e) { /* storage unavailable: fall through to default */ }
    return DEFAULT_LANG;
  }

  function fillParams(text, params) {
    if (!params) return text;
    return String(text).replace(/\{(\w+)\}/g, function (m, name) {
      return (params[name] !== undefined && params[name] !== null) ? params[name] : m;
    });
  }

  // t(key, fallback, params): Arabic dict is the fallback chain before the
  // explicit fallback so a missing English string never renders a bare key.
  function t(key, fallback, params) {
    var lang = getLang();
    var hit = DICTS[lang] && DICTS[lang][key];
    if (hit === undefined || hit === null || hit === '') hit = DICTS.ar[key];
    if (hit === undefined || hit === null || hit === '') {
      hit = (fallback !== undefined && fallback !== null) ? fallback : key;
    }
    return fillParams(hit, params);
  }

  function applyI18nToDOM(root) {
    var lang = getLang();
    try {
      document.documentElement.lang = lang;
      document.documentElement.dir = (lang === 'ar') ? 'rtl' : 'ltr';
    } catch (e) { /* non-DOM context */ }
    var scope = root || document;
    var applyAll = function (attr, fn) {
      var nodes;
      try {
        nodes = scope.querySelectorAll('[' + attr + ']');
      } catch (e) { return; }
      for (var i = 0; i < nodes.length; i++) {
        var key = nodes[i].getAttribute(attr);
        if (key) fn(nodes[i], t(key));
      }
    };
    applyAll('data-i18n', function (el, s) { el.textContent = s; });
    applyAll('data-i18n-ph', function (el, s) { el.setAttribute('placeholder', s); });
    applyAll('data-i18n-title', function (el, s) { el.setAttribute('title', s); });
    applyAll('data-i18n-aria', function (el, s) { el.setAttribute('aria-label', s); });
    try {
      var btn = document.getElementById('langToggleBtn');
      if (btn) {
        btn.textContent = (lang === 'ar') ? t('lang.switch_to_english') : t('lang.switch_to_arabic');
      }
    } catch (e) { /* button absent on some views */ }
  }

  function setLang(lang) {
    if (lang !== 'ar' && lang !== 'en') return getLang();
    try { window.localStorage.setItem(STORAGE_KEY, lang); } catch (e) { /* ignore */ }
    applyI18nToDOM(document);
    try {
      document.dispatchEvent(new CustomEvent('wf:lang', { detail: { lang: lang } }));
    } catch (e) { /* ignore */ }
    return lang;
  }

  function toggleAppLanguage() {
    return setLang(getLang() === 'ar' ? 'en' : 'ar');
  }

  function boot() {
    applyI18nToDOM(document);
  }
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', boot);
    } else {
      boot();
    }
    // Re-apply after dynamic renders that run past DOMContentLoaded.
    document.addEventListener('wf:lang', function () { applyI18nToDOM(document); });
  }

  window.WFI18n = {
    getLang: getLang,
    setLang: setLang,
    toggle: toggleAppLanguage,
    t: t,
    applyI18nToDOM: applyI18nToDOM,
    supported: SUPPORTED.slice(),
    defaultLang: DEFAULT_LANG,
    storageKey: STORAGE_KEY
  };
  window.toggleAppLanguage = toggleAppLanguage;

  // WFT(key, fallback, params): the single safe global for application code.
  // "WFT" has no other meaning anywhere in the shell, so unlike a bare t() it
  // cannot collide with locals in the one shared inline-script scope.
  window.WFT = function (key, fallback, params) {
    try {
      if (window.WFI18n && typeof window.WFI18n.t === 'function') {
        return window.WFI18n.t(key, fallback, params);
      }
    } catch (e) { /* fall through to fallback */ }
    var s = (fallback !== undefined && fallback !== null) ? fallback : key;
    return fillParams(s, params);
  };
})();
