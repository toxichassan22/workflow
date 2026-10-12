'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const source = ['03_best_use.js', '03a_best_use_calculator.js']
  .map(file => fs.readFileSync(path.join(root, 'assets/js/07-project-form', file), 'utf8')).join('\n');
const plain = value => JSON.parse(JSON.stringify(value));

function fixture() {
  const rows = [{ id: 'old', name: 'مكونات يدوية' }];
  const inputs = {
    bestUseData: { value: '', dataset: { key: 'best_use_data' } },
    bestUseChatData: { value: '', dataset: { key: 'best_use_chat' } },
    builtUpAreaAbove: { value: '6000' },
    basementArea: { value: '2500' },
    bestUseChatInput: { value: 'لماذا اخترت هذا التوزيع؟' }
  };
  const body = { replaceChildren() { rows.length = 0; } };
  const context = vm.createContext({
    console, Intl, URL, setTimeout, clearTimeout, window: { location: { origin: 'http://localhost:5515' } },
    tenantProjectData: {
      draftId: 'draft-1', project_type: '["سكني"]', project_name: 'مشروع سكني',
      approved_financial_area: 5000, croquis_land_area: 5000, approved_coverage_ratio: 60,
      approved_floor_count: 4, approved_floor_area_ratio: 2,
      setbacks: 'أمامي 5 م، خلفي 5 م، جانبي 5 م', allowed_uses: 'سكني',
      land_documents_files_file_ids: ['croquis-1'], land_documents_analysis: { parcels: [{ land_area: 5000 }] },
      location_address: 'https://maps.google.com/?q=21.5,39.2', location_lat: '21.5', location_lng: '39.2',
      market_study_data: { summary: { market_definition: 'طلب موثق على السكن' } },
      tenantCreativeImages: { map_placeholders: { '##MAP_OVERVIEW##': '/uploads/maps/site.png?s=old' } },
      financial_study_model: { inputs: { builtUpAreaAbove: 6000, manualLandValue: 7000000 },
        dynamicRows: { components: plain(rows), cost: [{ price: 500 }] } },
      visual_concept: { plansWorkflow: { ownerLocalWork: 'unchanged' } }
    },
    tenantProjectSectionStatuses: { land_croquis: 'approved', location: 'approved', 'section-market-study': 'approved' },
    tenantAllowedFieldSections: { 'section-best-use': true, 'section-financial-calc': true },
    tenantDraftRevision: 1, draftEditCounter: 0, tenantDraftDirty: false, tenantProjectMode: 'draft',
    rows, toasts: [], requests: [], saves: 0, recalculations: 0,
    document: {
      addEventListener() {},
      getElementById: id => inputs[id] || null,
      querySelector: selector => {
        if (selector === '#componentsTable tbody') return body;
        const key = selector.match(/\[data-key="([^"]+)"\]/)?.[1];
        if (key && key in context.tenantProjectData) return { value: context.tenantProjectData[key] };
        return null;
      },
      querySelectorAll: () => []
    },
    WFT: (key, fallback = key, params = {}) => fallback.replace(/\{(\w+)\}/g, (match, name) => params[name] ?? match),
    wfTr: text => text,
    toast: text => context.toasts.push(text),
    confirm: () => true,
    saveProjectAsDraft: async () => { context.saves++; return true; },
    triggerAutoSaveDraft() {},
    persistFinancialStudyDraftState() {},
    calculateAll: () => { context.recalculations++; },
    addComponent: row => rows.push(plain(row)),
    applySectionStatuses: statuses => Object.assign(context.tenantProjectSectionStatuses, statuses),
    hasPermission: () => true,
    showLoader() {}, updateLoaderProgress() {}, hideLoader() {}
  });
  vm.runInContext(source, context);
  function proposal(approved = false) {
    return { id: 'proposal-1', approved, rejected: false,
      sourceSnapshot: plain(context.bestUseSourceSnapshot()), title: 'توزيع مقترح',
      rationale: 'سبب موثق', setbackExplanation: 'الارتدادات المسجلة',
      capacity: { maxBuiltArea: 10000, landArea: 5000, far: 2, footprintLimit: 3000 },
      totals: { builtArea: 8000, openArea: 0, footprintArea: 2000, revenueArea: 7200 },
      components: [{ id: 'best_1', name: 'شقق', useType: 'residential', units: 80,
        unitArea: 100, builtArea: 8000, revenueArea: 7200, footprintArea: 2000,
        investmentModel: 'sale', reason: 'سبب الاختيار', areaReason: 'أساس المساحة' }] };
  }
  function requestContext() {
    return { draftId: context.tenantProjectData.draftId, editCounter: context.draftEditCounter,
      sourceSnapshot: plain(context.bestUseSourceSnapshot()) };
  }
  return { context, rows, inputs, proposal, requestContext };
}

test('an unused or rejected optional section is not a required approval', () => {
  const f = fixture();
  assert.equal(f.context.bestUseSectionRequired(), false);
  assert.equal('section-best-use' in f.context.bestUseOptionalStatuses({ basic: 'approved', 'section-best-use': 'draft' }), false);
  f.context.tenantProjectData.best_use_data = { ...f.proposal(), rejected: true };
  assert.equal(f.context.bestUseSectionRequired(), false);
  f.context.tenantProjectData.best_use_data = f.proposal();
  assert.equal(f.context.bestUseSectionRequired(), true);
  assert.equal(f.context.bestUseOptionalStatuses({ 'section-best-use': 'draft' })['section-best-use'], 'draft');
});

test('generation and chat receive proposals without editing the components table', () => {
  const f = fixture();
  const visuals = plain(f.context.tenantProjectData.visual_concept);
  assert.equal(f.context.applyBestUseResponse({ success: true, draftId: 'draft-1', revision: 2,
    bestUse: f.proposal(), chat: { messages: [{ role: 'user', content: 'لماذا؟' }] } }, f.requestContext()), true);
  assert.equal(f.rows[0].id, 'old');
  assert.equal(f.context.tenantProjectData.best_use_data.approved, false);
  assert.equal(f.context.tenantProjectData.best_use_chat.messages.length, 1);
  assert.deepEqual(plain(f.context.tenantProjectData.visual_concept), visuals);
  assert.equal(JSON.parse(f.inputs.bestUseData.value).id, 'proposal-1');
  assert.equal(JSON.parse(f.inputs.bestUseChatData.value).messages.length, 1);
});

test('only an approval response replaces components and updates the area input', () => {
  const f = fixture();
  const model = plain(f.context.tenantProjectData.financial_study_model);
  const proposed = f.proposal(true);
  model.dynamicRows.components = plain(proposed.components);
  model.inputs.builtUpAreaAbove = 8000;
  model.inputs.basementArea = 1000;
  const visuals = plain(f.context.tenantProjectData.visual_concept);
  assert.equal(f.context.applyBestUseResponse({ success: true, draftId: 'draft-1', revision: 2,
    bestUse: proposed, financialModel: model, componentsApplied: true,
    sectionStatuses: { 'section-financial-calc': 'draft', 'section-best-use': 'draft' } }, f.requestContext()), true);
  assert.deepEqual(f.rows, plain(proposed.components));
  assert.equal(f.inputs.builtUpAreaAbove.value, '8000');
  assert.equal(f.inputs.basementArea.value, '1000');
  assert.equal(f.context.tenantProjectData.financial_study_model.inputs.manualLandValue, 7000000);
  assert.deepEqual(plain(f.context.tenantProjectData.visual_concept), visuals);
  assert.equal(f.context.recalculations, 1);
});

test('a response from another project cannot enter the current workspace', () => {
  const f = fixture();
  assert.equal(f.context.applyBestUseResponse({ success: true, draftId: 'another', bestUse: f.proposal() }, f.requestContext()), false);
  assert.equal(f.context.tenantProjectData.best_use_data, undefined);
  assert.equal(f.rows[0].id, 'old');
});

test('a response cannot overwrite components edited while approval was in flight', () => {
  const f = fixture();
  const request = f.requestContext();
  f.context.draftEditCounter++;
  const model = plain(f.context.tenantProjectData.financial_study_model);
  model.dynamicRows.components = f.proposal().components;
  assert.equal(f.context.applyBestUseResponse({ success: true, draftId: 'draft-1', revision: 2,
    bestUse: f.proposal(true), financialModel: model, componentsApplied: true }, request), false);
  assert.equal(f.rows[0].id, 'old');
});

test('source changes invalidate the proposal but changed fetch signatures do not', () => {
  const f = fixture();
  f.context.tenantProjectData.best_use_data = f.proposal(true);
  assert.equal(f.context.bestUseCurrent(), true);
  f.context.tenantProjectData.tenantCreativeImages.map_placeholders['##MAP_OVERVIEW##'] = '/uploads/maps/site.png?s=new&t=123';
  assert.equal(f.context.bestUseCurrent(), true);
  f.context.tenantProjectData.approved_floor_area_ratio = 3;
  assert.equal(f.context.bestUseCurrent(), false);
});

test('calculator basement and revenue modes do not change generation snapshots', () => {
  const f = fixture();
  f.context.tenantProjectData.best_use_data = f.proposal(true);
  const snapshot = plain(f.context.bestUseSourceSnapshot());
  assert.equal(snapshot.mode, 'guided');
  assert.equal('basementArea' in snapshot, false);
  assert.equal('unitRevenueMode' in snapshot, false);
  f.inputs.basementArea.value = '9000';
  f.context.tenantProjectData.financial_study_model.inputs.unitRevenueMode = 'rental';
  assert.equal(f.context.bestUseCurrent(), true);
  f.context.tenantProjectData.best_use_data.mode = 'explore';
  assert.equal(f.context.bestUseCurrent(), false);
});

test('a stored snapshot carrying response-signed media stays current', () => {
  const f = fixture();
  const proposal = f.proposal();
  // JSON responses re-sign every /uploads/ URL, including ones nested inside
  // best_use_data.sourceSnapshot — the stored copy must be normalized before
  // comparing or the approve button never enables.
  proposal.sourceSnapshot.maps['##MAP_OVERVIEW##'] = '/uploads/maps/site.png?s=signed-token';
  proposal.sourceSnapshot.market_study_data = {
    ...proposal.sourceSnapshot.market_study_data,
    competitors: [{ name: 'منافس', logo_path: '/uploads/creative/t/logo.png?s=abc.def' }]
  };
  f.context.tenantProjectData.market_study_data = {
    summary: { market_definition: 'طلب موثق على السكن' },
    competitors: [{ name: 'منافس', logo_path: '/uploads/creative/t/logo.png' }]
  };
  f.context.tenantProjectData.best_use_data = proposal;
  assert.equal(f.context.bestUseCurrent(), true);
});

test('a failed pre-save cannot start a generation or chat call', async () => {
  const f = fixture();
  f.context.saveProjectAsDraft = async () => false;
  f.context.api = async () => { throw new Error('No request should run'); };
  assert.equal(await f.context.runBestUseAction('generate'), false);
  assert.equal(await f.context.sendBestUseChat(), false);
});

test('approval cancellation and rejection do not send a destructive request without consent', async () => {
  const f = fixture();
  f.context.tenantProjectData.best_use_data = f.proposal();
  f.context.confirm = () => false;
  f.context.api = async () => { throw new Error('No approval should run'); };
  assert.equal(await f.context.runBestUseAction('approved'), false);
});

test('draft persistence is scoped to the active project, not a global conversation', () => {
  const f = fixture();
  f.context.tenantProjectData.best_use_data = f.proposal();
  f.context.tenantProjectData.best_use_chat = { messages: [{ role: 'user', content: 'سؤال محفوظ' }] };
  f.context.persistBestUseDraftState();
  assert.equal(JSON.parse(f.inputs.bestUseChatData.value).messages[0].content, 'سؤال محفوظ');
  f.context.tenantProjectData = { draftId: 'new-project' };
  f.context.persistBestUseDraftState();
  assert.deepEqual(JSON.parse(f.inputs.bestUseData.value), {});
  assert.deepEqual(JSON.parse(f.inputs.bestUseChatData.value), {});
});
