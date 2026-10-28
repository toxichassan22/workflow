'use strict';

// The progress card must follow the task, not the clock.
// (assets/js/00-core/01_progress.js)
//
// Contract under test:
//   - showLoader() with no measured fraction renders an indeterminate bar and
//     the bar does NOT move when the clock ticks;
//   - a measured percentage stays exactly where it was put;
//   - an authored percentage is not drawn at all — it becomes a stage name;
//   - a job payload's step list is rendered with done/active rows and its
//     measured progress drives the bar;
//   - a plan without a measured percentage leaves the bar indeterminate.
//
// Run like the other UI suites: node --test tests/presentations/test_progress_engine.js

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const source = fs.readFileSync(path.join(root, 'assets/js/00-core/01_progress.js'), 'utf8');

function makeElement(id) {
  const node = {
    id,
    style: { display: id === 'globalLoader' ? 'none' : '', width: '' },
    textContent: '',
    innerHTML: '',
    hidden: false,
    attrs: {},
    classes: new Set(),
    parentElement: null,
    classList: {
      toggle(name, on) {
        if (on) node.classes.add(name);
        else node.classes.delete(name);
      },
      add(...names) { names.forEach(name => node.classes.add(name)); },
      remove(...names) { names.forEach(name => node.classes.delete(name)); },
      contains(name) { return node.classes.has(name); }
    },
    setAttribute(name, value) { node.attrs[name] = String(value); },
    removeAttribute(name) { delete node.attrs[name]; },
    getAttribute(name) { return Object.prototype.hasOwnProperty.call(node.attrs, name) ? node.attrs[name] : null; },
    querySelector() { return null; }
  };
  return node;
}

function createPage() {
  const nodes = new Map();
  const timeouts = [];
  const intervals = [];
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, makeElement(id));
    return nodes.get(id);
  };
  const track = makeElement('globalLoaderTrack');
  const bar = get('globalLoaderBar');
  bar.parentElement = track;
  ['globalLoader', 'globalLoaderTitle', 'globalLoaderText', 'globalLoaderProgress',
    'globalLoaderPct', 'globalLoaderStep', 'globalLoaderEstimate', 'globalLoaderSteps',
    'globalLoaderStopButton', 'tenantLiveGenBanner', 'liveGenSlideTitle',
    'liveGenSlideDetails', 'liveGenProgressBar', 'liveGenProgressPct',
    'liveGenResumeButton', 'genBar', 'genPct', 'genSubtitle', 'genEta', 'genSteps']
    .forEach(get);
  const sandbox = {
    window: {},
    console,
    Date,
    setTimeout(fn, ms) { timeouts.push({ fn, ms }); return timeouts.length; },
    clearTimeout() {},
    setInterval(fn, ms) { intervals.push({ fn, ms }); return intervals.length; },
    clearInterval(id) { if (id) intervals[id - 1] = null; },
    WFT(key, fallback, params) {
      let out = String(fallback === undefined || fallback === null ? key : fallback);
      Object.keys(params || {}).forEach(name => {
        out = out.split('{' + name + '}').join(String(params[name]));
      });
      return out;
    },
    escapeHtml(value) {
      return String(value === undefined || value === null ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    },
    showTenantPage() {},
    resetTenantGenerationStop() {},
    tenantProjectData: {},
    tenantSlideGenerationCheckpoint: null,
    document: {
      getElementById: get,
      querySelector(selector) {
        return selector === '#globalLoaderProgress .global-loader-progress-track' ? track : null;
      }
    }
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: 'assets/js/00-core/01_progress.js' });
  return {
    fn: sandbox,
    node: get,
    track,
    tick(times) {
      for (let index = 0; index < times; index += 1) {
        intervals.filter(Boolean).forEach(interval => interval.fn());
      }
    },
    runTimeouts() {
      timeouts.splice(0).forEach(timeout => timeout.fn());
    },
    intervalCount() {
      return intervals.filter(Boolean).length;
    }
  };
}

test('the bar does not advance because time passed', () => {
  const page = createPage();
  page.fn.showLoader('إعداد العرض', 'تحليل بيانات المشروع');
  const bar = page.node('globalLoaderBar');
  const pct = page.node('globalLoaderPct');
  assert.equal(bar.style.width, '', 'no measured fraction means no width');
  assert.equal(pct.style.display, 'none', 'an invented percentage must not be shown');
  assert.equal(page.node('globalLoaderProgress').classList.contains('is-indeterminate'), true);
  page.tick(30);
  assert.equal(bar.style.width, '', 'the clock tick must never move the bar');
  assert.equal(pct.textContent, '', 'the clock tick must never invent a percentage');
  assert.equal(page.intervalCount(), 1, 'one clock timer, and it only renders the clock');
});

test('a measured percentage stays exactly where it was put', () => {
  const page = createPage();
  page.fn.showLoader('إعداد العرض', 'تجهيز البيانات');
  // Third argument: the caller counted something real (bytes, rows).
  page.fn.updateLoaderProgress(40, 'تجهيز الصور', true);
  assert.equal(page.node('globalLoaderBar').style.width, '40%');
  assert.equal(page.node('globalLoaderPct').textContent, '40%');
  page.tick(30);
  assert.equal(page.node('globalLoaderBar').style.width, '40%');
  assert.equal(page.node('globalLoaderPct').textContent, '40%');
});

test('an authored percentage is never drawn', () => {
  const page = createPage();
  page.fn.showLoader('إعداد العرض', 'تجهيز البيانات');
  // The old call shape: a hand-written number with nothing counted behind it.
  page.fn.updateLoaderProgress(20, 'تحليل بيانات الأرض والسوق');
  assert.equal(page.node('globalLoaderBar').style.width, '', 'no fraction may be claimed');
  assert.equal(page.node('globalLoaderPct').style.display, 'none');
  assert.equal(page.node('globalLoaderProgress').classList.contains('is-indeterminate'), true);
  assert.equal(page.node('globalLoaderText').textContent, 'تحليل بيانات الأرض والسوق',
    'the stage name is still shown — that is the real state');
  assert.equal(page.node('globalLoaderStep').textContent, 'تحليل بيانات الأرض والسوق');
});

test('a start percentage handed to showLoader is not drawn', () => {
  const page = createPage();
  page.fn.showLoader('توليد المنافسين', 'جاري البحث عن المنافسين...', 12, { stoppable: true });
  assert.equal(page.node('globalLoaderBar').style.width, '');
  assert.equal(page.node('globalLoaderPct').style.display, 'none');
  assert.equal(page.node('globalLoaderStep').textContent, 'جاري البحث عن المنافسين...');
});

test('job steps drive the checklist and the measured percentage', () => {
  const page = createPage();
  page.fn.showLoader('إعداد العرض', 'تجهيز البيانات');
  const applied = page.fn.applyLoaderJobProgress({
    steps: [
      { key: 'inputs', label: 'تجهيز بيانات المشروع' },
      { key: 'ai', label: 'تحليل البيانات وبناء الهيكل' },
      { key: 'arrange', label: 'ترتيب الأقسام والشرائح' },
      { key: 'ready', label: 'تجهيز خطة العرض' }
    ],
    step: 'ai',
    stepIndex: 1,
    stepTotal: 4,
    progress: 25,
    progressMeasured: true,
    stepLabel: 'تحليل البيانات وبناء الهيكل',
    message: 'تحليل بيانات المشروع بالذكاء الاصطناعي'
  });
  assert.equal(applied, true);
  const html = page.node('globalLoaderSteps').innerHTML;
  assert.equal((html.match(/class="global-loader-step(?=[\s"])/g) || []).length, 4);
  assert.match(html, /global-loader-step is-done[\s\S]*global-loader-step is-active/);
  assert.equal(page.node('globalLoaderSteps').hidden, false);
  assert.equal(page.node('globalLoaderBar').style.width, '25%');
  assert.equal(page.node('globalLoaderPct').style.display, '');
  assert.equal(page.node('globalLoaderProgress').classList.contains('is-indeterminate'), false);
  assert.equal(page.node('globalLoaderEstimate').textContent, 'الخطوة 2 من 4');
  assert.equal(page.node('globalLoaderText').textContent, 'تحليل بيانات المشروع بالذكاء الاصطناعي');
});

test('a plan without a measured percentage stays indeterminate', () => {
  const page = createPage();
  page.fn.showLoader('إعداد العرض', 'تجهيز البيانات');
  page.fn.applyLoaderJobProgress({
    steps: [
      { key: 'inputs', label: 'تجهيز بيانات المشروع' },
      { key: 'ai', label: 'تحليل البيانات وبناء الهيكل' }
    ],
    step: 'ai',
    // A server constant without the measured marker: authored, not counted.
    progress: 62,
    stepLabel: 'تحليل البيانات وبناء الهيكل'
  });
  assert.equal(page.node('globalLoaderProgress').classList.contains('is-indeterminate'), true);
  assert.equal(page.track.getAttribute('aria-valuenow'), null,
    'an indeterminate bar must not claim a value');
  assert.equal(page.node('globalLoaderBar').style.width, '');
});

test('a finished task ends at one hundred and resets after the card closes', () => {
  const page = createPage();
  page.fn.showLoader('إعداد العرض', 'تجهيز البيانات');
  page.fn.updateLoaderProgress(70, 'حفظ العرض');
  page.fn.hideLoader();
  assert.equal(page.node('globalLoaderBar').style.width, '100%');
  page.runTimeouts();
  assert.equal(page.node('globalLoader').style.display, 'none');
  assert.equal(page.node('globalLoaderBar').style.width, '0%');
  assert.equal(page.node('globalLoaderEstimate').textContent, '');
});

test('closing the card clears the step list so the next task starts clean', () => {
  const page = createPage();
  page.fn.showLoader('إعداد العرض', 'تجهيز البيانات');
  page.fn.applyLoaderJobProgress({
    steps: [{ key: 'inputs', label: 'تجهيز بيانات المشروع' }],
    step: 'inputs',
    progress: 0
  });
  assert.equal(page.node('globalLoaderSteps').hidden, false);
  page.fn.hideLoader();
  page.runTimeouts();
  assert.equal(page.node('globalLoaderSteps').hidden, true);
  assert.equal(page.node('globalLoaderSteps').innerHTML, '');
});
