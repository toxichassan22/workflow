/* ============================================================================
 * Landloom / Workflow — UI internationalization (i18n) foundation.
 *
 * OWNER RULE FOR ALL FUTURE WORK (enforced by tests/test_i18n.py):
 *   1. New UI strings go HERE first, in BOTH languages, then are referenced
 *      from code with WFT('section.key', 'Arabic fallback') in JS or
 *      data-i18n="section.key" in static HTML (data-i18n-ph for placeholders,
 *      data-i18n-title for titles, data-i18n-aria for aria-labels).
 *      Exact-matchable legacy chrome also gets an entry in WFI18N_EN_AUTO
 *      (Arabic text as key) so the DOM pass below can translate it.
 *   2. Never add a new hardcoded Arabic UI literal to toast() / confirm() /
 *      placeholder="" / showLoader() / hideLoader() / updateLoaderProgress().
 *      The suite keeps a baseline of the legacy literals and fails when a new
 *      one appears. If you migrate an old literal to WFT()/data-i18n instead;
 *      the baseline entry for it may be dropped (it only ever shrinks).
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

  var WFI18N_AR = window.__WFI18N_AR;
  var WFI18N_EN = window.__WFI18N_EN;
  var WFI18N_EN_AUTO = window.__WFI18N_EN_AUTO;


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
    try {
      if (typeof document !== 'undefined' && document.title) {
        document.title = t('app.title');
      }
    } catch (e) { /* ignore */ }
  }

  // Exact-match legacy translator: renders old render functions and backend
  // field labels in English without rewriting every call site. A text node
  // (or a placeholder/title/aria-label/alt/value attribute) whose FULL trimmed
  // text is a known Arabic chrome string is swapped; user data, numbers and
  // interpolated sentences never match and are left untouched. New code must
  // still use WFT()/data-i18n — this map only absorbs the legacy long tail.
  var AUTO_SKIP_SELECTOR = [
    'script', 'style', 'textarea', 'select', 'option', 'optgroup',
    '[contenteditable]',
    '.slide', '.ge-slide-card', '.pdf-export-page',
    '#tenantChatMessages', '.tenant-chat-messages',
    '.visual-concept-chat-message', '#aiRulesChatLog', '#trainingChatLog'
  ].join(',');
  // Attribute pass uses the same skips minus textarea: a textarea body is
  // user content, but its placeholder is chrome. Image alt text is chrome
  // too (it surfaces visibly when an image fails to load).
  var AUTO_ATTR_SKIP_SELECTOR = [
    'script', 'style', 'select', 'option', 'optgroup', '[contenteditable]',
    '.slide', '.ge-slide-card', '.pdf-export-page',
    '#tenantChatMessages', '.tenant-chat-messages',
    '.visual-concept-chat-message', '#aiRulesChatLog', '#trainingChatLog'
  ].join(',');
  var AUTO_CONTAINER_SKIP_SELECTOR = [
    '.slide', '.ge-slide-card', '.pdf-export-page',
    '#tenantChatMessages', '.tenant-chat-messages',
    '.visual-concept-chat-message', '#aiRulesChatLog', '#trainingChatLog'
  ].join(',');
  var AR_RE = /[؀-ۿ]/;
  var autoApplied = [];
  var autoObserver = null;
  var autoObsTimer = null;
  var autoFullPassAt = 0;

  function autoSkipped(el, forAttr) {
    try {
      return !!(el && el.closest &&
        el.closest(forAttr ? AUTO_ATTR_SKIP_SELECTOR : AUTO_SKIP_SELECTOR));
    } catch (e) { return true; }
  }

  function autoNorm(raw) {
    return String(raw).replace(/\s+/g, ' ').trim();
  }

  function autoSwapAttr(el, attr) {
    var raw;
    try { raw = el.getAttribute(attr); } catch (e) { return; }
    if (!raw || !AR_RE.test(raw)) return;
    var en = WFI18N_EN_AUTO[autoNorm(raw)];
    if (en === undefined || en === null || en === '' || en === raw) return;
    autoApplied.push({ el: el, attr: attr, ar: raw, en: en });
    try { el.setAttribute(attr, en); } catch (e) { /* ignore */ }
  }

  function autoTranslateSubtree(root) {
    if (!root || getLang() !== 'en') return 0;
    var scope = root;
    if (typeof Node !== 'undefined' &&
        root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) {
      return 0;
    }
    var count = 0;
    var walker;
    try {
      walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, null);
    } catch (e) { return 0; }
    var batch = [];
    var tn;
    while ((tn = walker.nextNode())) batch.push(tn);
    for (var i = 0; i < batch.length; i++) {
      tn = batch[i];
      var raw = tn.nodeValue;
      if (!raw || !AR_RE.test(raw)) continue;
      var key = autoNorm(raw);
      if (!key) continue;
      var p = tn.parentElement;
      if (!p || autoSkipped(p, false)) continue;

      var en = WFI18N_EN_AUTO[key];
      var prefix = '';
      var suffix = '';
      if (!en) {
        var altKey = key.indexOf('²') !== -1 ? key.replace(/²/g, '2') : (key.indexOf('2') !== -1 ? key.replace(/2/g, '²') : null);
        if (altKey && WFI18N_EN_AUTO[altKey]) en = WFI18N_EN_AUTO[altKey];
      }
      if (!en) {
        var m = key.match(/^([\s*•:\-–—]+)?(.*?)([\s*•:\-–—]+)?$/);
        if (m && m[2] && m[2] !== key) {
          var coreKey = autoNorm(m[2]);
          if (coreKey) {
            en = WFI18N_EN_AUTO[coreKey];
            if (!en) {
              var altCore = coreKey.indexOf('²') !== -1 ? coreKey.replace(/²/g, '2') : (coreKey.indexOf('2') !== -1 ? coreKey.replace(/2/g, '²') : null);
              if (altCore && WFI18N_EN_AUTO[altCore]) en = WFI18N_EN_AUTO[altCore];
            }
            if (en) {
              prefix = m[1] || '';
              suffix = m[3] || '';
            }
          }
        }
      }
      if (en === undefined || en === null || en === '') continue;

      var lead = (raw.match(/^\s+/) || [''])[0];
      var trail = (raw.match(/\s+$/) || [''])[0];
      var out = lead + prefix + en + suffix + trail;
      if (out === raw) continue;
      autoApplied.push({ node: tn, ar: raw, en: out });
      tn.nodeValue = out;
      count++;
      if (autoApplied.length > 30000) break;
    }
    var found = [];
    try {
      found = scope.querySelectorAll(
        'input[placeholder],textarea[placeholder],[title],[aria-label],[alt],' +
        'input[type=button][value],input[type=submit][value]');
    } catch (e) { /* ignore */ }
    for (var a = 0; a < found.length; a++) {
      var el = found[a];
      if (autoSkipped(el, true)) continue;
      autoSwapAttr(el, 'placeholder');
      autoSwapAttr(el, 'title');
      autoSwapAttr(el, 'aria-label');
      autoSwapAttr(el, 'alt');
      if (el.tagName === 'INPUT' && (el.type === 'button' || el.type === 'submit')) {
        autoSwapAttr(el, 'value');
      }
    }
    autoTranslateSelectOptions(scope);
    return count;
  }

  function autoTranslateSelectOptions(scope) {
    if (getLang() !== 'en') return;
    try {
      var root = scope || document;
      var selects = [];
      if (root && root.tagName === 'SELECT') {
        selects.push(root);
      }
      if (root && root.querySelectorAll) {
        var found = root.querySelectorAll('select');
        for (var s = 0; s < found.length; s++) selects.push(found[s]);
      }
      for (var i = 0; i < selects.length; i++) {
        var sel = selects[i];
        if (sel && sel.closest && sel.closest(AUTO_CONTAINER_SKIP_SELECTOR)) continue;
        for (var j = 0; j < sel.options.length; j++) {
          var opt = sel.options[j];
          var raw = opt.getAttribute('data-ar-text');
          if (raw === null || raw === undefined) {
            raw = opt.textContent;
            opt.setAttribute('data-ar-text', raw);
          }
          if (!raw || !AR_RE.test(raw)) continue;
          var norm = autoNorm(raw);
          if (!norm) continue;
          var en = WFI18N_EN_AUTO[norm];
          var prefix = '';
          var suffix = '';
          if (!en) {
            var altKey = norm.indexOf('²') !== -1 ? norm.replace(/²/g, '2') : (norm.indexOf('2') !== -1 ? norm.replace(/2/g, '²') : null);
            if (altKey && WFI18N_EN_AUTO[altKey]) en = WFI18N_EN_AUTO[altKey];
          }
          if (!en) {
            var m = norm.match(/^([\s*•:\-–—]+)?(.*?)([\s*•:\-–—]+)?$/);
            if (m && m[2] && m[2] !== norm) {
              var coreKey = autoNorm(m[2]);
              if (coreKey) {
                en = WFI18N_EN_AUTO[coreKey];
                if (!en) {
                  var altCore = coreKey.indexOf('²') !== -1 ? coreKey.replace(/²/g, '2') : (coreKey.indexOf('2') !== -1 ? coreKey.replace(/2/g, '²') : null);
                  if (altCore && WFI18N_EN_AUTO[altCore]) en = WFI18N_EN_AUTO[altCore];
                }
                if (en) {
                  prefix = m[1] || '';
                  suffix = m[3] || '';
                }
              }
            }
          }
          if (en) {
            if (!opt.hasAttribute('value')) {
              opt.setAttribute('value', raw);
            }
            opt.textContent = prefix + en + suffix;
          }
        }
      }
    } catch (e) { /* ignore */ }
  }

  function autoRestoreSelectOptions() {
    try {
      var opts = document.querySelectorAll('option[data-ar-text]');
      for (var i = 0; i < opts.length; i++) {
        opts[i].textContent = opts[i].getAttribute('data-ar-text');
        opts[i].removeAttribute('data-ar-text');
      }
    } catch (e) { /* ignore */ }
  }

  // Every swap is recorded with both sides and only restored while the live
  // value is still ours, so switching back to Arabic can never clobber newer
  // content. Detached nodes are dropped by the isConnected check.
  function autoRestore() {
    autoRestoreSelectOptions();
    for (var i = autoApplied.length - 1; i >= 0; i--) {
      var e = autoApplied[i];
      try {
        if (e.node) {
          if (e.node.isConnected && e.node.nodeValue === e.en) {
            e.node.nodeValue = e.ar;
          }
        } else if (e.el && e.el.isConnected &&
                   e.el.getAttribute(e.attr) === e.en) {
          e.el.setAttribute(e.attr, e.ar);
        }
      } catch (err) { /* ignore */ }
    }
    autoApplied = [];
  }

  // Dynamic renders (page opens, toasts, tables) land after the full pass, so
  // added subtrees are translated as they arrive — debounced and capped.
  function autoObserve() {
    if (autoObserver || typeof MutationObserver === 'undefined') return;
    var pending = [];
    var autoObsTimerType = null;
    var flush = function () {
      if (autoObsTimer) {
        if (typeof cancelAnimationFrame === 'function' && autoObsTimerType === 'raf') {
          cancelAnimationFrame(autoObsTimer);
        } else {
          clearTimeout(autoObsTimer);
        }
      }
      autoObsTimer = null;
      autoObsTimerType = null;
      if (getLang() !== 'en') { pending = []; return; }
      var work = pending;
      pending = [];
      for (var i = 0; i < work.length; i++) {
        var rec = work[i];
        try {
          if (rec.type === 'attributes' && rec.target) {
            if (!autoSkipped(rec.target, true)) {
              autoSwapAttr(rec.target, rec.attributeName);
            }
          } else if (rec.type === 'characterData' && rec.target) {
            var cp = rec.target.parentElement || rec.target;
            if (cp && !autoSkipped(cp, false)) {
              autoTranslateSubtree(cp);
            }
          } else if (rec.addedNodes) {
            if (rec.target && (rec.target.tagName === 'SELECT' || rec.target.tagName === 'OPTGROUP')) {
              autoTranslateSelectOptions(rec.target.tagName === 'SELECT' ? rec.target : rec.target.parentElement);
            }
            for (var j = 0; j < rec.addedNodes.length; j++) {
              var nd = rec.addedNodes[j];
              if (!nd) continue;
              if (nd.nodeType === 1) {
                if (nd.tagName === 'SELECT') {
                  autoTranslateSelectOptions(nd);
                } else if (nd.tagName === 'OPTION' || nd.tagName === 'OPTGROUP') {
                  autoTranslateSelectOptions(nd.closest ? nd.closest('select') : nd.parentElement);
                } else if (!autoSkipped(nd, false)) {
                  autoTranslateSubtree(nd);
                }
              } else if (nd.nodeType === 3) {
                var par = nd.parentElement;
                if (par && !autoSkipped(par, false)) {
                  autoTranslateSubtree(par);
                }
              }
            }
          }
        } catch (e) { /* ignore */ }
      }
    };
    autoObserver = new MutationObserver(function (muts) {
      if (getLang() !== 'en') return;
      for (var i = 0; i < muts.length; i++) pending.push(muts[i]);
      if (!autoObsTimer) {
        if (typeof requestAnimationFrame === 'function') {
          autoObsTimerType = 'raf';
          autoObsTimer = requestAnimationFrame(flush);
        } else {
          autoObsTimerType = 'timeout';
          autoObsTimer = setTimeout(flush, 0);
        }
      }
    });
    try {
      autoObserver.observe(document.documentElement, {
        childList: true, subtree: true, characterData: true, attributes: true,
        attributeFilter: ['placeholder', 'title', 'aria-label', 'alt']
      });
    } catch (e) { /* ignore */ }
  }

  function setLang(lang) {
    if (lang !== 'ar' && lang !== 'en') return getLang();
    try { window.localStorage.setItem(STORAGE_KEY, lang); } catch (e) { /* ignore */ }
    autoRestore();
    applyI18nToDOM(document);
    if (lang === 'en') {
      autoFullPassAt = Date.now();
      try { autoTranslateSubtree(document.body || document); } catch (e) { /* ignore */ }
    }
    autoObserve();
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
    if (getLang() === 'en') {
      try { autoTranslateSubtree(document.body || document); } catch (e) { /* ignore */ }
    }
    autoObserve();
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

  window.WFI18N_EN_AUTO = WFI18N_EN_AUTO;
  window.WFI18n = {
    getLang: getLang,
    setLang: setLang,
    toggle: toggleAppLanguage,
    t: t,
    applyI18nToDOM: applyI18nToDOM,
    autoTranslate: autoTranslateSubtree,
    autoRestore: autoRestore,
    autoDict: WFI18N_EN_AUTO,
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
