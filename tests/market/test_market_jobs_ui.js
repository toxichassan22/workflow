'use strict';

// Market job UI tests — search-rework board task A6
// (assets/js/05a-market-jobs.js + the callers in 05-market-competitors.js and
// 05a-market-summary-chat.js). Contracts under test:
//
// - MARKET_JOB_POLL_LIMIT_MS is three hours — the study's configured budget.
// - The research trace remains downloadable after a job settles.
//   how long a generation takes.
// - A generate click re-attaches to the remembered running job in
//   state.activeMarketJobs instead of posting a duplicate; a settled
//   remembered job is forgotten so the next click posts fresh.
// - A job that outlives the poll budget surfaces the status text "still
//   running in the background" — never a retry instruction.
//
// Run like the other UI suites: node --test tests/market/test_market_jobs_ui.js

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const files = [
  'assets/js/03-executive-classification.js',
  'assets/js/04-market.js',
  'assets/js/04a-market-section.js',
  'assets/js/05-market-competitors.js',
  'assets/js/05-market-competitors/01_project_data_snapshot.js',
  'assets/js/05-market-competitors/02_table_ux.js',
  'assets/js/05-market-competitors/03_source_links.js',
  'assets/js/05a-market-jobs.js',
  'assets/js/05a-market-summary-chat.js'
];
const source = files.map(file =>
  fs.readFileSync(path.join(root, file), 'utf8')).join('\n');

const JOB_ENDPOINT = id => '/api/market-study/jobs/' + encodeURIComponent(id);
const completedCompetitors = () => ({
  success: true, status: 'completed',
  competitors: [{ name: 'منافس واحد', district: 'النرجس' }],
  sources: []
});

function recordingText() {
  // The job flow writes status, then overwrites it — keep every write.
  return {
    _writes: [],
    get textContent() { return this._writes.length ? this._writes[this._writes.length - 1] : ''; },
    set textContent(value) { this._writes.push(String(value)); }
  };
}

function fixture() {
  const inputs = {
    marketGenerateCompetitorsBtn: { disabled: false },
    marketFillCompetitorsBtn: { disabled: false },
    marketCompetitorsNote: recordingText(),
    marketGenerateSummaryBtn: { disabled: false },
    marketResumeSummaryBtn: { disabled: false, hidden: true },
    marketSummaryTraceBtn: { hidden: true, onclick: null },
    marketSummaryFailure: recordingText(),
    marketSummaryCompare: { hidden: true, innerHTML: '' },
    marketCompetitorPriceBenchmarks: { hidden: false, innerHTML: '' },
    marketStudyData: { value: '', dataset: { key: 'market_study_data' } },
    marketStudyOneBlockSummary: { value: '', closest: () => null },
    marketSummaryChat: { innerHTML: '' },
    marketSummaryChatInput: { value: '', disabled: false, addEventListener() {} },
    marketSummaryChatResearch: { checked: true, disabled: false, addEventListener() {} },
    marketSummaryChatLog: { scrollTop: 0, scrollHeight: 10 },
    marketDisclaimer: { value: '' },
    marketCompetitorScopeMode: { value: 'district' },
    marketCompetitorDistrictChips: { innerHTML: '' },
    marketCompetitorDistrictInput: { value: '' },
    marketCompetitorUnitTypes: { innerHTML: '' },
    marketCompetitorRadius: { value: '10' },
    marketCompetitorRadiusCustomKm: { value: '' },
    marketComparisonTypes: { querySelectorAll: () => [] },
    marketDataPeriod: { value: '12m' },
    marketDataPeriodFrom: { value: '' },
    marketDataPeriodTo: { value: '' },
    marketDecision: { value: '' },
    financialCalcData: { value: '' }
  };
  const context = vm.createContext({
    console, Intl, URL, JSON, Date, setTimeout, clearTimeout,
    window: { location: { origin: 'http://localhost:5515' } },
    tenantProjectData: {
      draftId: 'draft-1', project_name: 'مشروع سكني', city: 'جدة',
      project_language: '',
      market_study_data: {
        competitors: [], sources: [],
        summary: { market_definition: 'تعريف السوق الحالي' },
        swot: {}
      }
    },
    tenantProjectSectionStatuses: {},
    tenantAllowedFieldSections: {},
    tenantProjectMode: 'draft',
    toasts: [], requests: [], appliedStates: [],
    // Run-control globals the job flow registers itself with.
    registerTenantGenerationRun() {},
    releaseTenantGenerationRun() {},
    tenantActiveGenerationRuns: new Set(),
    tenantGenerationStopRequested: false,
    document: {
      addEventListener() {},
      createElement: tag => ({ tagName: tag, className: '', hidden: false, textContent: '' }),
      getElementById: id => inputs[id] || null,
      querySelector: () => null,
      querySelectorAll: () => []
    },
    WFT: (key, fallback = key, params = {}) =>
      String(fallback).replace(/\{(\w+)\}/g, (match, name) => params[name] ?? match),
    wfTr: text => text,
    escapeHtml: text => String(text ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;'),
    toast: text => context.toasts.push(text),
    confirm: () => true,
    triggerAutoSaveDraft() {},
    hasPermission: () => true,
    showLoader() {}, updateLoaderProgress() {}, hideLoader() {},
    parseStoredLandTable: value => {
      if (!value) return null;
      if (typeof value === 'string') { try { return JSON.parse(value); } catch (e) { return null; } }
      return value;
    },
    selectedProjectTypeMains: () => ['سكني'],
    selectedProjectSubtypes: () => ['شقق'],
    groupedAudienceSelection: () => [],
    getComponentRowsData: () => [],
    api: async (method, endpoint, payload) => {
      context.requests.push({ method, endpoint, payload });
      return context.nextApi(method, endpoint, payload);
    },
    // Each test drives the API through this handle.
    nextApi: () => ({ success: true })
  });
  vm.runInContext(source, context);
  // DOM-free stand-ins: the job flow is about requests/state, not rendering.
  context.applyMarketStudyState = state => context.appliedStates.push(state);
  context.persistMarketStudyFromDom = () => {};
  context.collectMarketStudyRequestPayload = () => ({ city: 'جدة', district: 'النرجس' });
  return { context, inputs };
}

function postCount(context, endpoint) {
  return context.requests.filter(
    req => req.method === 'POST' && req.endpoint === endpoint).length;
}

test('market study separates competitors and market into accessible tabs', () => {
  const ui = fs.readFileSync(
    path.join(root, 'assets/js/04a-market-section.js'), 'utf8');
  const markupStart = ui.indexOf('body.innerHTML = `');
  const markupEnd = ui.indexOf('`;', markupStart);
  const markup = ui.slice(markupStart, markupEnd);
  assert.match(ui, /data-market-study-tab="competitors"[^>]*>المنافسون<\/button>/);
  assert.match(ui, /data-market-study-tab="market"[^>]*>السوق<\/button>/);
  assert.match(ui, /data-market-study-panel="competitors"/);
  assert.match(ui, /data-market-study-panel="market"/);
  assert.match(ui, /id="marketCompetitorScopeMode"/);
  assert.match(ui, /<option value="distance">المسافة<\/option>/);
  assert.match(ui, /id="marketCompetitorRadius"/);
  assert.match(ui, /id="marketCompetitorRadiusCustomKm"/);
  const marketPanelStart = markup.indexOf('data-market-study-panel="market"');
  assert.ok(markup.indexOf('marketCompetitorRadius') < marketPanelStart);
  assert.equal(markup.indexOf('marketCompetitorRadius', marketPanelStart), -1);
  assert.match(ui, /id="marketComparisonTypes"/);
  assert.match(ui, /id="marketAddComparisonTypeBtn"/);
  assert.match(ui, /id="marketCompetitorTypeTabs"/);
  assert.match(ui, /id="marketCompetitorDistrictChips"/);
  assert.match(ui, /id="marketCompetitorUnitTypes"/);
  assert.match(ui, /أحياء النطاق/);
  assert.match(ui, /data-comparison-field="stars"/);
  assert.match(ui, /إضافة نوع مقارنة/);
  assert.doesNotMatch(source, /outOfRadiusCount/);

  const { context } = fixture();
  const makeControl = (field, key, classes = '') => {
    const classNames = new Set(classes.split(/\s+/).filter(Boolean));
    return {
      dataset: { [field]: key },
      classList: {
        contains: name => classNames.has(name),
        toggle(name, force) {
          if (force) classNames.add(name);
          else classNames.delete(name);
        }
      },
      attributes: {}, handlers: {}, tabIndex: 0,
      addEventListener(type, handler) { this.handlers[type] = handler; },
      setAttribute(name, value) { this.attributes[name] = value; }
    };
  };
  const tabs = [makeControl('marketStudyTab', 'competitors', 'active'), makeControl('marketStudyTab', 'market')];
  const panels = [makeControl('marketStudyPanel', 'competitors'), makeControl('marketStudyPanel', 'market', 'market-study-tab-panel-off')];
  const bar = { querySelectorAll: () => tabs };
  const rootElement = {
    querySelector: selector => selector === '#marketStudyTabs' ? bar : null,
    querySelectorAll: selector => selector === '.market-study-tab-panel' ? panels : tabs
  };

  context.setupMarketStudyTabs(rootElement);
  assert.equal(tabs[0].attributes['aria-selected'], 'true');
  assert.equal(tabs[1].attributes['aria-selected'], 'false');
  assert.equal(panels[0].attributes['aria-hidden'], 'false');
  assert.equal(panels[1].attributes['aria-hidden'], 'true');

  tabs[1].handlers.click();
  assert.equal(tabs[0].attributes['aria-selected'], 'false');
  assert.equal(tabs[1].attributes['aria-selected'], 'true');
  assert.equal(panels[0].attributes['aria-hidden'], 'true');
  assert.equal(panels[1].attributes['aria-hidden'], 'false');
});

test('transaction benchmark title uses the source recorded in the files', () => {
  const { context, inputs } = fixture();
  context.renderMarketTransactionBenchmarks({
    source_label: 'صفقات وزارة العدل',
    note: 'بيانات مرجعية محدودة التغطية.',
    groups: [{ district: 'الروضة', unit_type: 'فيلا', deal_count: 3 }]
  });
  assert.match(inputs.marketCompetitorPriceBenchmarks.innerHTML, /صفقات وزارة العدل/);
  assert.doesNotMatch(inputs.marketCompetitorPriceBenchmarks.innerHTML, /مجهولة الهوية/);
});

test('comparison rows accept several operations or hotel classifications', () => {
  const { context } = fixture();
  const operationRow = context.marketComparisonTypeRowHtml({
    type: 'residential', operation: ['sale', 'rent']
  });
  assert.match(operationRow, /value="sale" checked/);
  assert.match(operationRow, /value="rent" checked/);

  const hotelRow = context.marketComparisonTypeRowHtml({
    type: 'hotel', stars: ['4', '5']
  });
  assert.match(hotelRow, /value="4" checked/);
  assert.match(hotelRow, /value="5" checked/);
  const newRow = context.marketComparisonTypeRowHtml({}, ['hotel']);
  assert.doesNotMatch(newRow, /value="hotel"/);
  assert.match(newRow, /value="residential"/);

  const merged = JSON.parse(JSON.stringify(context.normalizeMarketComparisonRows([
    { type: 'residential', operation: 'sale' },
    { type: 'residential', operation: 'rent' }
  ])));
  assert.deepEqual(merged, [{ type: 'residential', operation: ['sale', 'rent'], stars: [] }]);

  const row = {
    querySelector: selector => selector.includes('[data-comparison-field="type"]')
      ? { value: 'residential' } : null,
    querySelectorAll: selector => selector.includes('[data-comparison-field="operation"]')
      ? [{ checked: true, value: 'sale' }, { checked: true, value: 'rent' }] : []
  };
  context.document.querySelectorAll = () => [row];
  assert.deepEqual(JSON.parse(JSON.stringify(context.collectMarketComparisonTypes())), [{
    type: 'residential', operation: ['sale', 'rent'], stars: []
  }]);
});

test('competitor table keeps blank type cells aligned and compacts comparison choices', () => {
  const { context } = fixture();
  const renderer = fs.readFileSync(path.join(root, 'assets/js/05-market-competitors.js'), 'utf8');
  assert.match(renderer, /'<td' \+ marketHotelStarsCellAttributes\(isHotel\)/);
  assert.match(renderer, /const benchmarksHtml = marketBenchmarkPickerHtml\(benchAxes, benchSelected\)/);
  assert.match(renderer, /el\.style\.visibility = show \? 'visible' : 'hidden'/);
  assert.match(renderer, /benchmarks: marketSelectedBenchmarkValues\(tr\)/);

  const emptyStarsCell = context.marketHotelStarsCellAttributes(false);
  assert.match(emptyStarsCell, /data-hotel-stars-cell/);
  assert.match(emptyStarsCell, /market-hotel-stars-empty/);
  assert.doesNotMatch(emptyStarsCell, /\shidden(?:\s|=|>)/);

  const picker = context.marketBenchmarkPickerHtml([
    { label: 'سكني - بيع', labelEn: 'Residential sale' },
    { label: 'فندقي - 4 نجوم', labelEn: '4-star hotel' }
  ], ['سكني - بيع']);
  const summary = picker.match(/<summary>([\s\S]*?)<\/summary>/)[1];
  assert.match(summary, /سكني - بيع/);
  assert.doesNotMatch(summary, /فندقي/);
  assert.match(picker, /type="checkbox"/);
  assert.match(picker, /فندقي - 4 نجوم/);

  const tabs = context.marketCompetitorTypeTabsModel([
    { project_type: 'سكني' }, { project_type: 'فندقي' }, { project_type: 'تجاري' }
  ], []);
  assert.deepEqual(JSON.parse(JSON.stringify(tabs.map(item => item.key))), [
    'residential', 'commercial', 'hotel'
  ]);
  assert.deepEqual(JSON.parse(JSON.stringify(context.marketCompetitorRowsForType([
    { project_type: 'سكني', name: 'أ' }, { project_type: 'فندقي', name: 'ب' }
  ], 'residential').map(row => row.name))), ['أ']);

  const row = { querySelectorAll: selector => selector.includes(':checked')
    ? [{ checked: true, value: 'سكني - بيع' }]
    : [{ checked: true, value: 'سكني - بيع' }, { checked: false, value: 'فندقي - 4 نجوم' }] };
  assert.deepEqual(JSON.parse(JSON.stringify(context.marketSelectedBenchmarkValues(row))), ['سكني - بيع']);
});

test('poll budget constant is three hours', () => {
  const { context } = fixture();
  assert.equal(vm.runInContext('MARKET_JOB_POLL_LIMIT_MS', context), 3 * 60 * 60 * 1000);
  assert.equal(vm.runInContext('MARKET_JOB_POLL_INTERVAL_MS', context), 2500);
});

test('the summary research trace downloads with the tenant token', async () => {
  const { context, inputs } = fixture();
  const calls = [];
  context.URL = class extends URL {
    static createObjectURL() { return 'blob:market-trace'; }
    static revokeObjectURL() {}
  };
  context.Blob = Blob;
  context.getTenantToken = () => 'tenant-token';
  context.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, blob: async () => new Blob(['trace']) };
  };
  context.document.createElement = tag => ({
    tagName: tag,
    click() { context.downloadedTrace = this; }
  });

  context.setMarketResearchTraceJob('job-trace-1');
  assert.equal(inputs.marketSummaryTraceBtn.hidden, false);
  await inputs.marketSummaryTraceBtn.onclick();

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/market-study/jobs/job-trace-1/trace');
  assert.equal(calls[0].options.headers.Authorization, 'Bearer tenant-token');
  assert.equal(context.downloadedTrace.download, 'market-research-job-trace-1.jsonl');
  assert.equal(context.downloadedTrace.href, 'blob:market-trace');
});

test('pollMarketStudyJob polls until the job completes', async () => {
  const { context } = fixture();
  const queue = [
    { status: 'queued', success: true, progress: 10 },
    { status: 'running', success: true, progress: 55 },
    { status: 'completed', success: true, competitors: [] }
  ];
  context.nextApi = () => queue.shift() || { status: 'completed', success: true };
  const progress = [];
  const res = await context.pollMarketStudyJob('job-9',
    job => progress.push(job.status), { intervalMs: 0 });
  assert.equal(res.status, 'completed');
  assert.deepEqual(progress, ['queued', 'running', 'completed']);
  assert.equal(context.requests.length, 3);
  assert.ok(context.requests.every(
    req => req.method === 'GET' && req.endpoint === JOB_ENDPOINT('job-9')));
});

test('a lost job stops polling instead of spinning', async () => {
  const { context } = fixture();
  context.nextApi = () => ({ status: '', failureReason: 'job_not_found' });
  const res = await context.pollMarketStudyJob('job-gone', () => {},
    { intervalMs: 0 });
  assert.equal(res.failureReason, 'job_not_found');
  assert.equal(context.requests.length, 1);
});

test('an outlived budget returns the still-running job, not a retry error', async () => {
  const { context } = fixture();
  context.nextApi = () => ({ status: 'running', success: true, progress: 70 });
  const res = await context.pollMarketStudyJob('job-slow', () => {},
    { budgetMs: 30, intervalMs: 0 });
  assert.equal(res.status, 'running');
  assert.equal(context.marketJobSettled(res), false);
});

test('a running job that finishes later reports settled', () => {
  const { context } = fixture();
  assert.equal(context.marketJobSettled({ status: 'running' }), false);
  assert.equal(context.marketJobSettled({ status: 'queued' }), false);
  assert.equal(context.marketJobSettled({ status: 'completed' }), true);
  assert.equal(context.marketJobSettled({ status: 'failed' }), true);
  assert.equal(context.marketJobSettled({ failureReason: 'x' }), true);
});

test('a remembered running job is re-attached, never re-posted', async () => {
  const { context, inputs } = fixture();
  const state = context.getMarketStudyState();
  state.activeMarketJobs = { competitors: 'job-7' };
  context.setMarketStudyState(state);
  const polled = [];
  const notesWhilePolling = [];
  context.pollMarketStudyJob = async (jobId, onProgress) => {
    polled.push(jobId);
    // The resumed note is up while the job is being followed.
    notesWhilePolling.push(inputs.marketCompetitorsNote.textContent);
    if (typeof onProgress === 'function') onProgress({ status: 'running' });
    return completedCompetitors();
  };
  context.nextApi = () => ({ status: 'running', success: true, progress: 60 });
  await context.runMarketCompetitorsJob('generate');
  assert.equal(postCount(context, '/api/market-study/competitors'), 0);
  assert.deepEqual(polled, ['job-7']);
  assert.deepEqual(context.requests.map(req => req.endpoint), [JOB_ENDPOINT('job-7')]);
  assert.deepEqual(notesWhilePolling, ['توجد مهمة قيد التنفيذ — جاري متابعة نتيجتها.']);
  // Completion replaces the transient note with the resumed-done wording —
  // never the fill/generate copy, which would misdescribe a reattached job.
  assert.equal(inputs.marketCompetitorsNote.textContent,
    'اكتمل تحديث المنافسين — 1 في الجدول');
  assert.equal(context.appliedStates.length, 1);
  // Settled — the memory is cleared for the next click.
  assert.equal(context.rememberedMarketJob('competitors'), '');
});

test('a settled remembered job is forgotten and the click posts fresh', async () => {
  const { context } = fixture();
  const state = context.getMarketStudyState();
  state.activeMarketJobs = { competitors: 'job-done' };
  context.setMarketStudyState(state);
  context.nextApi = (method, endpoint) => {
    if (method === 'GET') return { status: 'completed', success: true };
    return completedCompetitors();
  };
  await context.runMarketCompetitorsJob('generate');
  assert.equal(context.rememberedMarketJob('competitors'), '');
  assert.equal(postCount(context, '/api/market-study/competitors'), 1);
});

test('a fresh post remembers the job id and clears it on completion', async () => {
  const { context } = fixture();
  context.pollMarketStudyJob = async () => completedCompetitors();
  context.nextApi = (method, endpoint) => {
    if (method === 'POST') return { jobId: 'job-8', message: 'بدأت' };
    return { status: 'completed', success: true };
  };
  await context.runMarketCompetitorsJob('generate');
  assert.equal(postCount(context, '/api/market-study/competitors'), 1);
  assert.equal(context.rememberedMarketJob('competitors'), '');
  assert.equal(context.appliedStates.length, 1);
});

test('no browsed evidence is hidden as a warning while verification status stays available', async () => {
  const { context, inputs } = fixture();
  const result = {
    ...completedCompetitors(),
    partial: true,
    searchVerified: true,
    searchNotRunCount: 1,
    providerError: 'browse_agent: no browsed evidence',
    competitors: [{
      name: 'منافس واحد', verify_state: 'search_not_run',
      verify_provider_error: 'browse_agent: no browsed evidence'
    }]
  };
  const row = { dataset: {
    verifyState: result.competitors[0].verify_state,
    verifyProviderError: result.competitors[0].verify_provider_error
  } };

  assert.equal(context.marketCompetitorVerificationWarningHtml(row), '');
  assert.equal(row.dataset.verifyState, 'search_not_run');
  assert.equal(row.dataset.verifyProviderError, 'browse_agent: no browsed evidence');

  context.nextApi = () => result;
  await context.runMarketCompetitorsJob('generate');
  assert.equal(inputs.marketCompetitorsNote.textContent, 'تم استبدال الجدول بـ 1 منافس');
  assert.ok(context.toasts.includes('تم استبدال جدول المنافسين بالنتيجة الجديدة'));
  assert.ok(!context.toasts.includes('اكتمل التحديث بنتيجة جزئية — التفاصيل موضحة أسفل الجدول'));
});

test('a real competitor verification timeout remains visible', async () => {
  const { context } = fixture();
  const row = { dataset: {
    verifyState: 'search_not_run', verifyProviderError: 'deadline_exceeded'
  } };
  const warning = context.marketCompetitorVerificationWarningHtml(row);
  assert.match(warning, /تعذر تشغيل بحث التحقق لهذا المنافس/);
  assert.match(warning, /deadline_exceeded/);
});

test('a still-running poll result shows status text and keeps the memory', async () => {
  const { context, inputs } = fixture();
  context.pollMarketStudyJob = async () =>
    ({ status: 'running', success: true, progress: 80 });
  context.nextApi = (method) =>
    method === 'POST' ? { jobId: 'job-long', message: 'بدأت' } : {};
  await context.runMarketCompetitorsJob('generate');
  const text = 'المهمة ما زالت تعمل في الخلفية.';
  assert.equal(inputs.marketCompetitorsNote.textContent, text);
  assert.ok(context.toasts.includes(text));
  // Not settled — the job id stays remembered for the next click.
  assert.equal(context.rememberedMarketJob('competitors'), 'job-long');
  assert.equal(context.appliedStates.length, 0);
});

test('the summary job re-attaches to its remembered running job', async () => {
  const { context, inputs } = fixture();
  context.collectMarketSummaryScope = () => ({ cities: [{ name: 'جدة', districts: [] }] });
  const state = context.getMarketStudyState();
  state.activeMarketJobs = { summary: 'job-s1' };
  context.setMarketStudyState(state);
  const notesWhilePolling = [];
  context.pollMarketStudyJob = async () => {
    notesWhilePolling.push(inputs.marketSummaryFailure.textContent);
    return {
      success: true, status: 'completed',
      summary: { market_definition: 'تعريف جديد' },
      swot: {}, sources: [], decision: 'فرصة قوية'
    };
  };
  context.nextApi = () => ({ status: 'running', success: true });
  await context.runMarketSummaryJob();
  assert.equal(postCount(context, '/api/market-study/summary'), 0);
  assert.deepEqual(context.requests.map(req => req.endpoint), [JOB_ENDPOINT('job-s1')]);
  assert.deepEqual(notesWhilePolling, ['توجد مهمة قيد التنفيذ — جاري متابعة نتيجتها.']);
  assert.equal(inputs.marketSummaryFailure.textContent, '');
  assert.equal(inputs.marketSummaryTraceBtn.hidden, false);
  // An existing summary shows the compare surface — never auto-applied.
  assert.match(inputs.marketSummaryCompare.innerHTML, /تعريف جديد/);
  assert.match(inputs.marketSummaryCompare.innerHTML, /تعريف السوق الحالي/);
  assert.equal(context.appliedStates.length, 0);
  assert.equal(context.rememberedMarketJob('summary'), '');
});

test('a credit-stopped summary keeps its job and can resume that same job', async () => {
  const { context, inputs } = fixture();
  context.collectMarketSummaryScope = () => ({ cities: [{ name: 'جدة', districts: [] }] });
  context.pollMarketStudyJob = async () => ({
    success: false, status: 'failed', canResume: true,
    failureReason: 'insufficient_credit', error: 'رصيد غير كافٍ'
  });
  context.nextApi = method => method === 'POST'
    ? { success: true, jobId: 'job-summary-credit', status: 'queued' }
    : {};
  await context.runMarketSummaryJob();
  assert.equal(context.rememberedMarketJob('summary'), 'job-summary-credit');
  assert.equal(inputs.marketSummaryTraceBtn.hidden, false);
  assert.equal(inputs.marketResumeSummaryBtn.hidden, false);

  context.nextApi = (method, endpoint) => {
    assert.equal(method, 'POST');
    assert.equal(endpoint, JOB_ENDPOINT('job-summary-credit') + '/resume');
    return { success: true, jobId: 'job-summary-credit', status: 'queued' };
  };
  context.pollMarketStudyJob = async jobId => {
    assert.equal(jobId, 'job-summary-credit');
    return {
      success: true, status: 'completed',
      summary: { market_definition: 'تعريف مستكمل' }, swot: {}, sources: []
    };
  };
  await context.resumeMarketSummaryJob();
  assert.equal(context.rememberedMarketJob('summary'), '');
  assert.equal(inputs.marketResumeSummaryBtn.hidden, true);
  assert.match(inputs.marketSummaryCompare.innerHTML, /تعريف مستكمل/);
  assert.equal(postCount(context, '/api/market-study/summary'), 1);
  assert.equal(postCount(context, JOB_ENDPOINT('job-summary-credit') + '/resume'), 1);
});

test('generate starts a fresh summary instead of echoing a settled job failure', async () => {
  const { context, inputs } = fixture();
  context.collectMarketSummaryScope = () => ({ cities: [{ name: 'جدة', districts: [] }] });
  const state = context.getMarketStudyState();
  state.activeMarketJobs = { summary: 'job-stale' };
  context.setMarketStudyState(state);
  const staleError = 'رصيد الشركة المسجل يغطي التقدير المبدئي لهذه العملية: '
    + '1.00 دولار (نحو 3.75 نقطة)، لكن مفتاح مزود الذكاء الاصطناعي رفض الطلب.';
  context.nextApi = (method, endpoint) => {
    if (method === 'GET') {
      assert.equal(endpoint, JOB_ENDPOINT('job-stale'));
      return {
        success: false, status: 'failed', canResume: true,
        failureReason: 'insufficient_credit', error: staleError
      };
    }
    if (method === 'POST') {
      assert.equal(endpoint, '/api/market-study/summary');
      return { success: true, jobId: 'job-fresh', status: 'queued' };
    }
    return {};
  };
  context.pollMarketStudyJob = async jobId => {
    assert.equal(jobId, 'job-fresh');
    return {
      success: true, status: 'completed',
      summary: { market_definition: 'تعريف جديد' }, swot: {}, sources: []
    };
  };
  await context.runMarketSummaryJob();
  assert.equal(postCount(context, '/api/market-study/summary'), 1);
  assert.equal(postCount(context, JOB_ENDPOINT('job-stale') + '/resume'), 0);
  assert.equal(inputs.marketResumeSummaryBtn.hidden, true);
  assert.doesNotMatch(inputs.marketSummaryFailure.textContent, /1\.00 دولار/);
  assert.ok(!context.toasts.some(text => /1\.00 دولار/.test(text)));
  assert.match(inputs.marketSummaryCompare.innerHTML, /تعريف جديد/);
  assert.equal(context.rememberedMarketJob('summary'), '');
});

test('the saved resume action returns after reopening the market section', async () => {
  const { context, inputs } = fixture();
  const state = context.getMarketStudyState();
  state.activeMarketJobs = { summary: 'job-summary-credit' };
  context.setMarketStudyState(state);
  context.nextApi = (method, endpoint) => {
    assert.equal(method, 'GET');
    assert.equal(endpoint, JOB_ENDPOINT('job-summary-credit'));
    return { success: false, status: 'failed', canResume: true,
      failureReason: 'insufficient_credit' };
  };
  await context.restoreMarketSummaryResumeAction();
  assert.equal(inputs.marketResumeSummaryBtn.hidden, false);
  assert.equal(context.rememberedMarketJob('summary'), 'job-summary-credit');
});

test('still-running and resumed wording carry status, never instructions', () => {
  const { context } = fixture();
  for (const text of [
    context.marketJobStillRunningText(),
    context.marketJobResumedText()
  ]) {
    assert.doesNotMatch(text, /أعد|إعادة|حاول|لاحق|انتظر|مجدد/);
    assert.doesNotMatch(text, /\p{Extended_Pictographic}/u);
  }
});

test('the market job source carries no retry-instruction copy', () => {
  const jobsSource = fs.readFileSync(
    path.join(root, 'assets/js/05a-market-jobs.js'), 'utf8');
  assert.doesNotMatch(jobsSource, /أعد المحاولة|حاول مجدد|حاول مرة أخرى/);
  assert.doesNotMatch(jobsSource, /استغرق التوليد/);
});

test('a chat job that outlives the budget posts a still-running turn', async () => {
  const { context, inputs } = fixture();
  const state = context.getMarketStudyState();
  state.summary = { market_definition: 'تعريف السوق' };
  context.setMarketStudyState(state);
  inputs.marketSummaryChatInput.value = 'حدّث محور العرض';
  context.pollMarketStudyJob = async () =>
    ({ status: 'running', success: true, progress: 40 });
  context.nextApi = (method, endpoint) =>
    method === 'POST' ? { jobId: 'job-chat', message: 'بدأت' } : {};
  await context.sendMarketSummaryChat();
  const thread = context.getMarketStudyState().summaryChat.general;
  const last = thread[thread.length - 1];
  assert.equal(last.role, 'assistant');
  assert.equal(last.content, 'المهمة ما زالت تعمل في الخلفية.');
  assert.notEqual(last.error, true);
  assert.doesNotMatch(last.content, /أعد|حاول|لاحق/);
});

test('fill mode reports the rows it completed and keeps the benchmarks', async () => {
  const { context, inputs } = fixture();
  const state = context.getMarketStudyState();
  state.transaction_benchmarks = { residential: { sale: '4,500' } };
  context.setMarketStudyState(state);
  context.nextApi = () => ({
    success: true,
    status: 'completed',
    competitors: [{ name: 'WA Hotel', project_type: 'فندقي' }],
    sources: [],
    filledCount: 3,
    updated: 1,
    partial: false,
    searchVerified: true,
    missingPriceCount: 0
  });
  await context.runMarketCompetitorsJob('fill');
  assert.equal(inputs.marketCompetitorsNote.textContent,
    'أُكملت بيانات 3 منافس');
  assert.deepEqual(context.getMarketStudyState().transaction_benchmarks,
    { residential: { sale: '4,500' } });
});

test('fill mode reports a truthful partial count', async () => {
  const { context, inputs } = fixture();
  context.nextApi = () => ({
    success: true,
    status: 'completed',
    competitors: [{ name: 'WA Hotel', project_type: 'فندقي' }],
    sources: [],
    filledCount: 2,
    updated: 2,
    attemptedCount: 9,
    unfilledCount: 7,
    partial: true,
    searchVerified: true,
    missingPriceCount: 7
  });
  await context.runMarketCompetitorsJob('fill');
  assert.match(inputs.marketCompetitorsNote.textContent,
    /أُكملت بيانات 2 منافس/);
  assert.match(inputs.marketCompetitorsNote.textContent,
    /7 منافس بلا سعر موثق/);
});

test('the competitor scope carries several districts and chosen unit kinds', () => {
  const { context, inputs } = fixture();
  const chips = ['الروضة', 'السلامة'];
  const unitInputs = [
    { dataset: { unitType: 'فيلا مستقلة' }, checked: true },
    { dataset: { unitType: 'شقة' }, checked: false }
  ];
  context.document.querySelectorAll = selector => {
    if (String(selector).includes('data-scope-district')) {
      return chips.map(name => ({ dataset: { scopeDistrict: name } }));
    }
    if (String(selector).includes('[data-unit-type]')) return unitInputs;
    return [];
  };

  // The client's own list renders as chips, never as one fixed district.
  context.renderMarketCompetitorDistricts(chips);
  assert.match(inputs.marketCompetitorDistrictChips.innerHTML, /الروضة/);
  assert.match(inputs.marketCompetitorDistrictChips.innerHTML, /السلامة/);
  assert.deepEqual(
    Array.from(context.marketCompetitorDistrictNames()), chips);

  inputs.marketCompetitorDistrictInput.value = 'الزهراء';
  context.addMarketCompetitorDistrict();
  assert.match(inputs.marketCompetitorDistrictChips.innerHTML, /الزهراء/);
  assert.equal(inputs.marketCompetitorDistrictInput.value, '');

  // The owner's sixteen residential kinds and the commercial ones are offered.
  context.renderMarketUnitTypes(['فيلا مستقلة']);
  assert.match(inputs.marketCompetitorUnitTypes.innerHTML, /سكن موظفين/);
  assert.match(inputs.marketCompetitorUnitTypes.innerHTML, /سكن عمال/);
  assert.match(inputs.marketCompetitorUnitTypes.innerHTML, /برج مكاتب/);
  assert.match(inputs.marketCompetitorUnitTypes.innerHTML,
    /data-unit-type="فيلا مستقلة" checked/);
  assert.deepEqual(
    Array.from(context.collectMarketUnitTypeSelections()), ['فيلا مستقلة']);

  // Both reach the saved scope the job posts.
  context.collectMarketSummaryScope = () => ({ cities: [] });
  const state = context.collectMarketStudyFromDom();
  assert.deepEqual(Array.from(state.competitor_scope.districts), chips);
  assert.deepEqual(
    Array.from(state.competitor_scope.unit_types), ['فيلا مستقلة']);
});
