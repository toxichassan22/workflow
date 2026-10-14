'use strict';

// Market job UI tests — search-rework board task A6
// (assets/js/05a-market-jobs.js + the callers in 05-market-competitors.js and
// 05a-market-summary-chat.js). Contracts under test:
//
// - MARKET_JOB_POLL_LIMIT_MS is 40 minutes — the job budget, not a guess at
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
  'assets/js/05-market-competitors.js',
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
    marketSummaryFailure: recordingText(),
    marketSummaryCompare: { hidden: true, innerHTML: '' },
    marketStudyData: { value: '', dataset: { key: 'market_study_data' } },
    marketStudyOneBlockSummary: { value: '', closest: () => null },
    marketSummaryChat: { innerHTML: '' },
    marketSummaryChatInput: { value: '', disabled: false, addEventListener() {} },
    marketSummaryChatResearch: { checked: true, disabled: false, addEventListener() {} },
    marketSummaryChatLog: { scrollTop: 0, scrollHeight: 10 },
    marketDisclaimer: { value: '' },
    marketCompetitorRadius: { value: '10' },
    marketCompetitorRadiusCustom: { value: '' },
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

test('poll budget constant is 40 minutes', () => {
  const { context } = fixture();
  assert.equal(vm.runInContext('MARKET_JOB_POLL_LIMIT_MS', context), 40 * 60 * 1000);
  assert.equal(vm.runInContext('MARKET_JOB_POLL_INTERVAL_MS', context), 2500);
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
  // An existing summary shows the compare surface — never auto-applied.
  assert.match(inputs.marketSummaryCompare.innerHTML, /تعريف جديد/);
  assert.match(inputs.marketSummaryCompare.innerHTML, /تعريف السوق الحالي/);
  assert.equal(context.appliedStates.length, 0);
  assert.equal(context.rememberedMarketJob('summary'), '');
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
