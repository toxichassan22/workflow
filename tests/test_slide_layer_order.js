'use strict';
// Run with node tests/test_slide_layer_order.js; uses the actual inline functions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const FRONTEND_JS_ORDER = ['00-core.js', '01-nav-auth.js', '02-settings-branding.js',
  '03-executive-classification.js', '04-market.js', '05-market-competitors.js', '06-team.js',
  '07-project-form.js', '08-location-maps.js', '09-financial.js', '10-financial-report-timeline.js',
  '11-land-croquis.js', '12-files-media.js', '13-visual.js', '14-slides-gen.js',
  '15-slide-edit-chat.js', '16-presentations-export.js', '17-admin-boot.js'];
const source = ['index.html', 'assets/css/base.css', 'assets/css/project-form.css',
  ...FRONTEND_JS_ORDER.map(n => 'assets/js/' + n)]
  .map(f => fs.readFileSync(path.join(__dirname, '..', f), 'utf8')).join('\n');
const extract = name => {
  const match = new RegExp('^    (?:async )?function ' + name + '\\(', 'm').exec(source);
  assert(match, name);
  const end = source.indexOf('\n    }', match.index);
  return source.slice(match.index, end + 6);
};
const context = vm.createContext({ console, JSON, Set, Array });
vm.runInContext(`
  /* Minimal fake DOM: enough surface for the layer-order functions —
     children/parent links, sibling navigation, class/attr/style, outerHTML. */
  function El(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.parentElement = null;
    this.style = {};
    this.attrs = {};
    this.classes = new Set();
    const self = this;
    this.classList = { contains: n => self.classes.has(n) };
  }
  El.prototype = {
    get nextElementSibling() {
      const p = this.parentElement;
      if (!p) return null;
      const i = p.children.indexOf(this);
      return (i >= 0 && i < p.children.length - 1) ? p.children[i + 1] : null;
    },
    get previousElementSibling() {
      const p = this.parentElement;
      if (!p) return null;
      const i = p.children.indexOf(this);
      return i > 0 ? p.children[i - 1] : null;
    },
    insertBefore(node, ref) {
      if (node.parentElement) node.parentElement.removeChild(node);
      const i = ref ? this.children.indexOf(ref) : -1;
      node.parentElement = this;
      if (i < 0) this.children.push(node); else this.children.splice(i, 0, node);
      return node;
    },
    appendChild(node) { return this.insertBefore(node, null); },
    removeChild(node) {
      const i = this.children.indexOf(node);
      if (i >= 0) this.children.splice(i, 1);
      node.parentElement = null;
      return node;
    },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); },
    matches(sel) {
      sel = sel.trim();
      if (sel.startsWith('.')) return this.classes.has(sel.slice(1));
      if (sel.startsWith('[')) {
        const m = /^\\[([\\w-]+)(?:="([^"]*)")?\\]$/.exec(sel);
        if (!m) return false;
        const v = this.getAttribute(m[1]);
        return m[2] === undefined ? v !== null : v === m[2];
      }
      return this.tagName.toLowerCase() === sel.toLowerCase();
    },
    closest(sel) {
      const sels = sel.split(',').map(s => s.trim());
      let n = this;
      while (n) {
        if (n.matches && sels.some(s => n.matches(s))) return n;
        n = n.parentElement;
      }
      return null;
    },
    contains(node) {
      let n = node;
      while (n) { if (n === this) return true; n = n.parentElement; }
      return false;
    },
    get outerHTML() {
      const t = this.tagName.toLowerCase();
      const cls = this.classes.size ? ' class="' + [...this.classes].join(' ') + '"' : '';
      const attrs = Object.entries(this.attrs).map(([k, v]) => ' ' + k + '="' + v + '"').join('');
      const stylePairs = Object.entries(this.style).filter(([, v]) => v !== undefined && v !== '');
      const style = stylePairs.length
        ? ' style="' + stylePairs.map(([k, v]) => k.replace(/[A-Z]/g, c => '-' + c.toLowerCase()) + ':' + v).join(';') + '"'
        : '';
      const kids = this.children.map(c => c.outerHTML).join('');
      return ['img', 'br', 'input'].includes(t)
        ? '<' + t + cls + attrs + style + '>'
        : '<' + t + cls + attrs + style + '>' + kids + '</' + t + '>';
    }
  };
  function parseHTML(html) {
    const re = /<(\\/?)([a-zA-Z0-9]+)((?:[^>"']|"[^"]*"|'[^']*')*?)(\\/?)>/g;
    let m, root = null; const stack = [];
    while ((m = re.exec(html))) {
      if (m[1] === '/') { stack.pop(); continue; }
      const tag = m[2].toLowerCase();
      const el = new El(tag);
      const are = /([\\w-]+)(?:="([^"]*)")?/g; let am;
      while ((am = are.exec(m[3]))) {
        const k = am[1], v = am[2] === undefined ? '' : am[2];
        if (k === 'class') v.split(/\\s+/).forEach(c => c && el.classes.add(c));
        else if (k === 'style') {
          v.split(';').forEach(p => {
            const i = p.indexOf(':');
            if (i > 0) {
              const prop = p.slice(0, i).trim().replace(/-([a-z])/g, (_, c) => c.toUpperCase());
              const val = p.slice(i + 1).trim();
              if (val) el.style[prop] = val;
            }
          });
        } else el.attrs[k] = v;
      }
      if (stack.length) stack[stack.length - 1].appendChild(el); else root = el;
      if (!(m[4] === '/' || ['img', 'br', 'input'].includes(tag))) stack.push(el);
    }
    return root;
  }
  class DOMParser {
    parseFromString(html) {
      const root = parseHTML(html);
      return { querySelector(sel) {
        let found = null;
        (function walk(n) {
          if (found || !n) return;
          if (n.matches(sel)) { found = n; return; }
          (n.children || []).forEach(walk);
        })(root);
        return found;
      } };
    }
  }
  const window = { getComputedStyle(el) {
    return {
      zIndex: (el.style && el.style.zIndex) ? el.style.zIndex : 'auto',
      position: (el.style && el.style.position) ? el.style.position : 'static'
    };
  } };
  let tenantSlidesData = [], tenantProjectData = {}, historyCount = 0, toasts = [];
  const sessions = {};
  let liveSlide = null;
  function getSlideEditSession(index) { return sessions[index] || null; }
  function slideStageForIndex() { return { querySelector: sel => sel === '.slide' ? liveSlide : null }; }
  function selectSlideElement(stage, index, target, path) {
    if (sessions[index] && sessions[index].sel) sessions[index].sel.path = path;
  }
  function pushSlideEditHistory() { historyCount++; }
  function touchSlideEditSession() {}
  function triggerAutoSaveDraft() {}
  function renderTenantSlides() {}
  function toast(msg) { toasts.push(msg); }
  ${extract('slideElementPath')}
  ${extract('elementAtSlidePath')}
  ${extract('watermarkOverlayOf')}
  ${extract('findSlideRawTarget')}
  ${extract('isSlideEditorChrome')}
  ${extract('siblingContent')}
  ${extract('restackElement')}
  ${extract('outrankZ')}
  ${extract('effectiveZ')}
  ${extract('pressurizeZ')}
  ${extract('adjustSlideElementLayer')}
  function setup(html, targetId, chromeCount) {
    liveSlide = parseHTML(html);
    for (let i = 0; i < (chromeCount || 0); i++) {
      const h = new El('div');
      h.classes.add(i ? 'slide-resize-handle' : 'slide-move-handle');
      liveSlide.appendChild(h);
    }
    tenantSlidesData = [{ html }];
    const target = (function find(n, id) {
      if (n.getAttribute('id') === id) return n;
      for (const c of n.children) { const r = find(c, id); if (r) return r; }
      return null;
    })(liveSlide, targetId);
    sessions[0] = { sel: { path: slideElementPath(liveSlide, target) } };
    toasts = []; historyCount = 0;
    return target;
  }
  globalThis.__t = { El, parseHTML, setup, adjustSlideElementLayer, slideElementPath,
    elementAtSlidePath,
    get tenantSlidesData() { return tenantSlidesData; },
    get liveSlide() { return liveSlide; },
    get toasts() { return toasts; },
    get historyCount() { return historyCount; },
    sessions };
`, context);
const t = context.__t;

/* أمام: DOM swap one sibling later, z-index set above the passed sibling,
   stored HTML mirrors the new order, selection path tracks the move. */
{
  const target = t.setup('<div class="slide"><div id="bg"></div><div id="card" style="position:absolute"></div><div id="img2" style="position:absolute"></div></div>', 'card');
  t.adjustSlideElementLayer(0, 1);
  const html = t.tenantSlidesData[0].html;
  assert(html.indexOf('id="img2"') < html.indexOf('id="card"'), 'card moved after img2 in stored html');
  assert(/id="card" style="position:absolute;z-index:1"/.test(html), 'card z-index above auto sibling');
  assert.equal(t.elementAtSlidePath(t.liveSlide, t.sessions[0].sel.path), target, 'selection path re-pointed');
  assert.equal(t.historyCount, 1);
  assert(t.toasts.includes('تم تقديم العنصر للأمام'));
}

/* خلف: DOM swap one sibling earlier, z-index one below it. */
{
  const target = t.setup('<div class="slide"><div id="bg"></div><div id="card" style="position:absolute"></div><div id="img2"></div></div>', 'card');
  t.adjustSlideElementLayer(0, -1);
  const html = t.tenantSlidesData[0].html;
  assert(html.indexOf('id="card"') < html.indexOf('id="bg"'), 'card moved before bg in stored html');
  assert(/id="card" style="position:absolute;z-index:-1"/.test(html), 'negative z drops below auto sibling');
  assert.equal(t.elementAtSlidePath(t.liveSlide, t.sessions[0].sel.path), target);
  assert(t.toasts.includes('تم إرجاع العنصر للخلف'));
}

/* أمام on the last content child with editor chrome after it: chrome must be
   skipped (never swapped past), and z-index pressure applies instead. */
{
  const target = t.setup('<div class="slide"><div id="a"></div><div id="last" style="position:absolute"></div></div>', 'last', 2);
  const before = t.liveSlide.children.indexOf(target);
  t.adjustSlideElementLayer(0, 1);
  assert.equal(t.liveSlide.children.indexOf(target), before, 'not swapped past editor chrome');
  assert(/id="last" style="position:absolute;z-index:1"/.test(t.tenantSlidesData[0].html), 'z pressurized above auto siblings');
  assert(t.toasts.includes('تم تقديم العنصر للأمام'));
}

/* خلف on the first child: nothing to pass, so negative z sends it behind
   auto-stacked siblings — the case the old Math.max(0,...) clamp made dead. */
{
  t.setup('<div class="slide"><div id="first"></div><div id="b"></div></div>', 'first');
  t.adjustSlideElementLayer(0, -1);
  assert(/id="first" style="position:relative;z-index:-1"/.test(t.tenantSlidesData[0].html), 'negative z applied');
  assert(t.toasts.includes('تم إرجاع العنصر للخلف'));
}

/* أمام past a sibling carrying explicit z-index:50 — DOM order alone cannot
   beat it, so the moved element takes z = sibling + 1. */
{
  t.setup('<div class="slide"><div id="hi" style="z-index:50"></div><div id="t"></div></div>', 't');
  t.adjustSlideElementLayer(0, 1);
  assert(/id="t" style="position:relative;z-index:51"/.test(t.tenantSlidesData[0].html), 'outranks explicit z sibling');
}

/* Nothing left to do (last child already at the z cap) → honest no-op toast. */
{
  t.setup('<div class="slide"><div id="a"></div><div id="top" style="z-index:200"></div></div>', 'top');
  t.adjustSlideElementLayer(0, 1);
  assert(t.toasts.includes('العنصر بالفعل في المقدمة'));
}
console.log('test_slide_layer_order: OK');
