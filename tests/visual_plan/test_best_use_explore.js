'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const source = ['03_best_use.js', '03a_best_use_calculator.js', '03b_best_use_explore.js']
  .map(file => fs.readFileSync(path.join(root, 'assets/js/07-project-form', file), 'utf8')).join('\n');
const plain = value => JSON.parse(JSON.stringify(value));

function fixture() {
  const inputs = {
    bestUseData: { value: '', dataset: { key: 'best_use_data' } },
    bestUseChatData: { value: '', dataset: { key: 'best_use_chat' } },
    bestUseExploreData: { value: '', dataset: { key: 'best_use_explore_data' } },
    bestUseExploreChat: { value: '', dataset: { key: 'best_use_explore_chat' } },
    bestUseModeData: { value: '', dataset: { key: 'best_use_mode' } },
    bestUseExploreChatInput: { value: '', addEventListener() {} },
    bestUseExploreWorkspace: { innerHTML: '', hidden: false },
    bestUseMode: { value: 'guided', disabled: false }
  };
  const context = vm.createContext({
    console, Intl, URL, setTimeout, clearTimeout, window: { location: { origin: 'http://localhost:5515' } },
    tenantProjectData: {
      draftId: 'draft-1', project_type: '["سكني"]', project_name: 'مشروع سكني',
      approved_financial_area: 5000, croquis_land_area: 5000, approved_coverage_ratio: 60,
      approved_floor_count: 4, approved_floor_area_ratio: 2,
      setbacks: 'أمامي 5 م', allowed_uses: 'سكني', city: 'الرياض',
      land_documents_files_file_ids: ['croquis-1'],
      location_address: 'الرياض', location_lat: '21.5', location_lng: '39.2',
      best_use_mode: 'guided', best_use_explore_data: {}, best_use_explore_chat: {},
      tenantCreativeImages: { map_placeholders: {} }
    },
    tenantProjectSectionStatuses: { land_croquis: 'approved', location: 'approved',
      'section-market-study': 'approved', 'section-best-use': 'draft' },
    tenantAllowedFieldSections: { 'section-best-use': true },
    tenantDraftRevision: 3, draftEditCounter: 0, tenantDraftDirty: false, tenantProjectMode: 'draft',
    toasts: [], requests: [], saves: 0, persists: 0, renders: 0,
    document: {
      addEventListener() {},
      getElementById: id => inputs[id] || null,
      querySelector: selector => {
        const key = selector.match(/\[data-key="([^"]+)"\]/)?.[1];
        if (key && key in context.tenantProjectData) return { value: context.tenantProjectData[key] };
        return null;
      },
      querySelectorAll: () => []
    },
    WFT: (key, fallback = key, params = {}) => fallback.replace(/\{(\w+)\}/g, (match, name) => params[name] ?? match),
    wfTr: text => text,
    escapeHtml: text => String(text ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
    useTypes: [{ v: 'residential', t: 'سكني' }],
    investmentModels: [{ v: 'sale', t: 'بيع وحدات' }],
    toast: text => context.toasts.push(text),
    confirm: () => true,
    saveProjectAsDraft: async () => { context.saves++; return true; },
    triggerAutoSaveDraft() {},
    apiWithTimeout: async (method, endpoint, payload) => {
      context.requests.push({ method, endpoint, payload });
      return { success: true, draftId: 'draft-1', revision: 9, bestUseMode: payload.mode || 'explore',
        explore: { mode: 'explore' }, exploreChat: {}, bestUse: { id: 'p1' }, chat: {},
        sectionStatuses: { 'section-best-use': 'draft' } };
    },
    applySectionStatuses: statuses => Object.assign(context.tenantProjectSectionStatuses, statuses),
    hasPermission: () => true,
    showLoader() {}, updateLoaderProgress() {}, hideLoader() {}
  });
  vm.runInContext(source, context);
  context.renderBestUse = () => { context.renders++; };
  context.persistBestUseDraftState = () => { context.persists++; };
  return { context, inputs };
}

test('mode switching never forces a draft save and sends no revision precondition', async () => {
  const f = fixture();
  assert.equal(await f.context.changeBestUseMode('explore'), true);
  assert.equal(f.context.saves, 0);
  assert.equal(f.context.requests.length, 1);
  const request = f.context.requests[0];
  assert.equal(request.method, 'POST');
  assert.equal(request.endpoint, '/api/best-use/mode');
  assert.deepEqual(plain(request.payload), { draftId: 'draft-1', mode: 'explore' });
  assert.equal(f.context.tenantProjectData.best_use_mode, 'explore');
  assert.equal(f.context.tenantDraftRevision, 9);
});

test('mode switching back to guided restores the guided workspace state', async () => {
  const f = fixture();
  f.context.tenantProjectData.best_use_mode = 'explore';
  assert.equal(await f.context.changeBestUseMode('guided'), true);
  assert.equal(f.context.requests[0].payload.mode, 'guided');
  assert.equal(f.context.saves, 0);
  assert.equal(f.context.tenantProjectData.best_use_mode, 'guided');
  assert.equal(f.context.tenantProjectData.best_use_data.id, 'p1');
});

test('mode switching without a stored draft cannot reach the server', async () => {
  const f = fixture();
  f.context.tenantProjectData.draftId = '';
  assert.equal(await f.context.changeBestUseMode('explore'), false);
  assert.equal(f.context.saves, 0);
  assert.equal(f.context.requests.length, 0);
  assert.equal(f.context.toasts.length, 1);
});

test('a stale client revision is healed by the mode response instead of conflicting', async () => {
  const f = fixture();
  f.context.tenantDraftRevision = 1;
  assert.equal(await f.context.changeBestUseMode('explore'), true);
  assert.equal(f.context.tenantDraftRevision, 9);
});

test('an edit landing during the mode request cannot desync the applied mode', async () => {
  const f = fixture();
  const original = f.context.apiWithTimeout;
  f.context.apiWithTimeout = async (method, endpoint, payload) => {
    const response = await original(method, endpoint, payload);
    f.context.draftEditCounter += 1; // a bubbled form edit arriving mid-flight
    return response;
  };
  assert.equal(await f.context.changeBestUseMode('explore'), true);
  assert.equal(f.context.tenantProjectData.best_use_mode, 'explore');
});

test('an edit landing during a generation still rejects the response', async () => {
  const f = fixture();
  f.context.tenantProjectData.best_use_mode = 'explore';
  const original = f.context.apiWithTimeout;
  f.context.apiWithTimeout = async (method, endpoint, payload) => {
    const response = await original(method, endpoint, payload);
    f.context.draftEditCounter += 1;
    return response;
  };
  f.inputs.bestUseExploreChatInput.value = 'لماذا؟';
  assert.equal(await f.context.runBestUseExplore('chat'), false);
});

test('non-mode actions still save first and carry the revision precondition', async () => {
  const f = fixture();
  f.context.tenantProjectData.best_use_mode = 'explore';
  f.inputs.bestUseExploreChatInput.value = 'لماذا هذا التوزيع؟';
  assert.equal(await f.context.runBestUseExplore('chat'), true);
  assert.equal(f.context.saves, 1);
  assert.equal(f.context.requests[0].endpoint, '/api/best-use/explore/chat');
  assert.equal(f.context.requests[0].payload.expectedRevision, 3);
});

function readyExploreState(context) {
  return {
    mode: 'explore', sourceSnapshot: context.bestUseExploreSourceSnapshot(),
    regulations: { id: 'reg-1', contentHash: 'rh', inputHash: 'ri' },
    priceScan: { id: 'ps-1', contentHash: 'ph', inputHash: 'pi' },
    concepts: { id: 'co-1', version: 3, contentHash: 'ch', inputHash: 'ci',
      items: [{ id: 'concept-1', name: 'مفهوم سكني', summary: 'ملخص', siteFit: 'ملاءمة', revenueBasis: 'أساس' }] },
    selectedConceptId: 'concept-1', selectedConceptVersion: 3
  };
}

test('explore stages unlock only after their prerequisite artifacts are current', () => {
  const f = fixture();
  f.context.tenantProjectData.best_use_mode = 'explore';
  assert.equal(f.context.bestUseExploreStageReady('concepts'), true);
  assert.equal(f.context.bestUseExploreStageReady('land'), false);
  assert.equal(f.context.bestUseExploreStageReady('floors'), false);

  const unselected = readyExploreState(f.context);
  delete unselected.selectedConceptId;
  delete unselected.selectedConceptVersion;
  f.context.tenantProjectData.best_use_explore_data = unselected;
  assert.equal(f.context.bestUseExploreStageReady('land'), false);
  assert.equal(f.context.bestUseExploreStageReady('floors'), false);

  const state = readyExploreState(f.context);
  f.context.tenantProjectData.best_use_explore_data = state;
  assert.equal(f.context.bestUseExploreStageReady('land'), true);
  assert.equal(f.context.bestUseExploreStageReady('floors'), false);

  state.landDistribution = { id: 'ld-1', contentHash: 'lh', inputHash: 'li' };
  assert.equal(f.context.bestUseExploreStageReady('floors'), true);
});

test('stale inputs lock later stages again and the wizard snaps back', () => {
  const f = fixture();
  f.context.tenantProjectData.best_use_mode = 'explore';
  const state = readyExploreState(f.context);
  state.landDistribution = { id: 'ld-1', contentHash: 'lh', inputHash: 'li' };
  f.context.tenantProjectData.best_use_explore_data = state;

  f.context.renderBestUseExplore(); // first render anchors the draft and picks the deepest stage
  f.context.setBestUseExploreStage('floors');
  assert.equal(f.context.renders, 1);
  f.context.renderBestUseExplore();
  assert.match(f.inputs.bestUseExploreWorkspace.innerHTML,
    /class="btn primary small" onclick="setBestUseExploreStage\('floors'\)"/);

  f.context.tenantProjectData.approved_floor_count = 9;
  f.context.renderBestUseExplore();
  const html = f.inputs.bestUseExploreWorkspace.innerHTML;
  assert.match(html, /setBestUseExploreStage\('land'\)[^>]*disabled/);
  assert.match(html, /setBestUseExploreStage\('floors'\)[^>]*disabled/);
  assert.match(html, /class="btn primary small" onclick="setBestUseExploreStage\('concepts'\)"/);
});

test('a failed concepts run pins the server error inside the workspace', async () => {
  const f = fixture();
  f.context.tenantProjectData.best_use_mode = 'explore';
  f.context.apiWithTimeout = async (method, endpoint, payload) => {
    f.context.requests.push({ method, endpoint, payload });
    if (method === 'POST') return { success: true, jobId: 'job-1', status: 'queued' };
    return { success: false, status: 'failed', jobId: 'job-1',
      error_code: 'BEST_USE_SEARCH_FAILED', error: 'تعذر إجراء مسح أسعار حي موثق.', validation: 'price_search_not_run' };
  };
  f.context.renderBestUseExplore(); // the workspace renders before a run can start
  assert.equal(await f.context.runBestUseExplore('concepts'), false);
  f.context.renderBestUseExplore();
  const html = f.inputs.bestUseExploreWorkspace.innerHTML;
  assert.match(html, /role="alert"[^>]*>[^<]*مسح أسعار[^<]*price_search_not_run/);
  assert.equal(f.context.toasts.length, 1);
});

test('a successful concepts run clears a pinned error and renders the concepts', async () => {
  const f = fixture();
  f.context.tenantProjectData.best_use_mode = 'explore';
  let fail = true;
  f.context.apiWithTimeout = async (method, endpoint, payload) => {
    f.context.requests.push({ method, endpoint, payload });
    if (method === 'POST') return { success: true, jobId: 'job-' + f.context.requests.length, status: 'queued' };
    if (fail) return { success: false, status: 'failed', jobId: 'job-1', error_code: 'BEST_USE_SEARCH_FAILED', error: 'تعذر' };
    return { success: true, status: 'completed', jobId: 'job-2', draftId: 'draft-1', revision: 9,
      explore: readyExploreState(f.context), exploreChat: {}, sectionStatuses: {} };
  };
  f.context.renderBestUseExplore(); // the workspace renders before a run can start
  assert.equal(await f.context.runBestUseExplore('concepts'), false);
  f.context.renderBestUseExplore();
  assert.match(f.inputs.bestUseExploreWorkspace.innerHTML, /role="alert"/);
  fail = false;
  assert.equal(await f.context.runBestUseExplore('concepts'), true);
  f.context.renderBestUseExplore();
  const html = f.inputs.bestUseExploreWorkspace.innerHTML;
  assert.doesNotMatch(html, /role="alert"/);
  assert.match(html, /best-use-concept-card/);
});
