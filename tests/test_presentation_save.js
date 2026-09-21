const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
// index.html is a slim shell now; the code under test lives in ordered classic scripts.
const FRONTEND_JS_ORDER = ['00-core.js', '01-nav-auth.js', '02-settings-branding.js',
  '03-executive-classification.js', '04-market.js', '05-market-competitors.js', '06-team.js',
  '07-project-form.js', '08-location-maps.js', '09-financial.js', '10-financial-report-timeline.js',
  '11-land-croquis.js', '12-files-media.js', '13-visual.js', '14-slides-gen.js',
  '15-slide-edit-chat.js', '16-presentations-export.js', '17-admin-boot.js'];
const source = ['index.html', 'assets/css/base.css', 'assets/css/project-form.css',
  ...FRONTEND_JS_ORDER.map(n => 'assets/js/' + n)]
  .map(f => fs.readFileSync(path.join(process.cwd(), f), 'utf8')).join('\n');
const names = ['commitTenantPresentation', 'saveTenantPresentation', 'savePresentationFromToolbar', 'savePresentationCopy', 'preparePresentationGenerationTarget'];
const start = source.indexOf('    async function commitTenantPresentation(');
const end = source.indexOf('    async function openExistingPresentation(', start);
const buttons = {};
const context = {
  console, JSON, Number, String, Promise, Error, crypto: require('node:crypto').webcrypto,
  tenantPresentationSavePromise: null, tenantPresentationRevision: 3, tenantPresentationProvenance: null,
  tenantPresentationId: 'existing', tenantPresentationTitle: 'Title', tenantProjectMode: 'presentation',
  tenantProjectData: { draftId: 'draft', presentation_scope: 'full' }, tenantSlidesData: [{html:'old'}],
  tenantSlidePlan: {}, tenantCreativeImages: {}, tenantArchiveCache: null, isGeneratingTenantSlides: false,
  document: { getElementById: id => buttons[id] ||= {} },
  renumberTenantSlides() {}, updatePresentationUndoButtons() {}, setSlidesEditorInfo() {},
  clearPresentationUndoProvenance() { context.tenantPresentationProvenance = null; },
  designerChatPersistence() { return {}; }, setDraftDirty() {}, toast() {}, resetPresentationUndo() {},
  checkpointPresentationUndo() {}, recoverTenantSlidePlan(data) { return data.tenantSlidePlan || {}; },
  prompt() { return null; }, saveProjectAsDraft() {},
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  const calls = [];
  context.api = async (method,path,body) => { calls.push({method,path,body}); return {success:true,presentationId:'existing',revision:4,changed:true}; };
  assert.equal(await context.saveTenantPresentation(), true);
  assert.equal(calls[0].method,'PUT');
  assert.equal(calls[0].body.expectedRevision,3);
  assert.equal(context.tenantPresentationRevision,4);
  assert.equal(calls.length,1);
  context.tenantPresentationId = null;
  context.tenantPresentationRevision = 0;
  await context.saveTenantPresentation();
  assert.equal(calls[1].method,'POST');
  assert.equal(context.tenantPresentationId,'existing');
  context.api = async () => ({success:false,error_code:'PRESENTATION_REVISION_CONFLICT',currentRevision:9});
  assert.equal(await context.saveTenantPresentation(),false);
  assert.equal(context.tenantPresentationRevision,4);
  assert.equal(context.tenantSlidesData[0].html,'old');
  context.tenantPresentationId = null;
  context.tenantProjectData.presentation_scope = 'full';
  const requests = [];
  context.api = async (method,path,body) => {
    requests.push({method,path,body});
    if (path.includes('?draftId=')) return {success:true,presentations:[{id:'full',presentationScope:'full',revision:8},{id:'section',presentationScope:'section:location',revision:2}]};
    if (method==='GET') return {success:true,presentation:{id:'full',revision:8,projectData:{presentation_scope:'full'},slidesData:[{html:'saved'}],title:'Saved'}};
    return {success:true,revision:8,presentationId:'full'};
  };
  assert.equal(await context.preparePresentationGenerationTarget('full'),true);
  assert.equal(context.tenantPresentationId,'full');
  assert.equal(context.tenantPresentationRevision,8);
  assert.equal(requests.filter(x=>x.method==='POST').length,0);
  assert.equal(requests[2].body.expectedRevision,8);
  await testCheckpointPreservesInputs();
  await testSlideGenerationFailures();
  console.log('Presentation save harness passed: update/create, conflict preservation, scoped generation reuse, generation failure checkpoints.');
})().catch(error => { console.error(error); process.exitCode=1; });

async function testCheckpointPreservesInputs() {
  const approved = {
    draftId: 'draft', project_name: 'Approved project',
    map_styles: { overview: 'aerial', landmarks: 'aerial', access: 'aerial', catchment: 'aerial' },
    financial_study_model: { inputs: { projectCost: 1200 } },
    nearby_landmarks_data: [{ name: 'Approved landmark' }],
  };
  const writes = [];
  let collected = 0;
  const state = {
    console, JSON, Math, Number, String, Promise, crypto: require('node:crypto').webcrypto,
    tenantProjectData: JSON.parse(JSON.stringify(approved)),
    tenantSlidePlan: { slides: [{ title: 'Cover' }, { title: 'Content' }] },
    tenantSlidesData: [{ html: '<div class="slide">saved</div>' }],
    tenantSlideGenerationCheckpoint: null, tenantDraftRevision: 7,
    tenantPresentationId: 'presentation', tenantPresentationTitle: 'Title',
    tenantCreativeImages: {}, tenantVisualConceptState: null,
    tempCoverImage: null, tempMoodboardImages: {}, tenantNearbyLandmarks: [],
    tenantProjectSectionStatuses: { basic: 'approved' }, draftEditCounter: 0,
    tenantDraftDirty: true, tenantArchiveCache: null,
    LOCATION_TABLE_FIELDS: {}, VISUAL_CONCEPT_EXTERNAL_SLOTS: [],
    document: { getElementById: () => null },
    renumberTenantSlides() {}, serializeLocationTable() {}, designerChatPersistence: () => ({}), toast() {},
    async collectTenantFormData() { collected++; return { project_name: 'Form edit' }; },
    async api(method, route, body) {
      assert.equal(route, '/api/project-draft');
      writes.push(JSON.parse(JSON.stringify(body)));
      await new Promise(resolve => setImmediate(resolve));
      return { success: true, draftId: 'draft', revision: 8 };
    },
  };
  vm.createContext(state);
  for (const name of ['collectMapStylePanel', 'saveProjectAsDraftNow', 'tenantSlidePlanFingerprint',
    'tenantSlideGenerationOptions', 'saveTenantSlideGenerationCheckpoint']) {
    const match = new RegExp('^    (?:async )?function ' + name + '\\(', 'm').exec(source);
    assert(match, name);
    vm.runInContext(source.slice(match.index, source.indexOf('\n    }', match.index) + 6), state);
  }
  const pending = state.saveTenantSlideGenerationCheckpoint(1, 'running', '', approved);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(state.tenantProjectData.map_styles, approved.map_styles,
    'Checkpoint must not replace approved map inputs with hidden panel defaults while saving');
  assert.equal(await pending, true);
  assert.equal(collected, 0, 'Checkpoint must not re-collect form inputs');
  const saved = writes[0];
  for (const key of Object.keys(approved)) assert.deepEqual(saved.draftData[key], approved[key], key);
  assert.equal(saved.slideCheckpoint, true);
  assert.equal(saved.expectedRevision, 7);
  assert.equal(saved.draftData.tenantSlidesData.length, 1);
  assert.equal(saved.draftData.slide_generation_checkpoint.nextIndex, 1);
  assert.equal(state.tenantDraftRevision, 8);
  assert.equal(state.tenantDraftDirty, true, 'Output-only saves must not clear unsaved input edits');

  state.api = async () => ({ error: 'Revision conflict', error_code: 'DRAFT_REVISION_CONFLICT' });
  assert.equal(await state.saveTenantSlideGenerationCheckpoint(1, 'paused', 'Rejected', approved), false);
  assert.equal(state.tenantDraftRevision, 8);
  assert.equal(collected, 0);
  state.api = async (method, route, body) => { writes.push(body); return { success: true, revision: 9 }; };
  assert.equal(await state.saveProjectAsDraftNow(true, false), true);
  assert.equal(collected, 1, 'Normal saves must still collect user edits');
  assert.equal(writes.at(-1).draftData.project_name, 'Form edit');
  assert.equal(writes.at(-1).draftData.map_styles.overview, 'aerial',
    'Missing map controls must not reset saved styles');
  assert.equal(state.tenantDraftDirty, false);
}

async function testSlideGenerationFailures() {
  const match = /^    async function generateTenantSlides\(/m.exec(source);
  assert(match);
  const generateSource = source.slice(match.index, source.indexOf('\n    }', match.index) + 6);
  const flush = () => new Promise(resolve => setImmediate(resolve));
  const deferred = () => {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return { promise, resolve };
  };
  const slide = { success: true, slide: { html: '<div class="slide">saved</div>' } };
  for (const blockedCheckpoint of [false, true]) {
    const requests = [], checkpoints = [], banners = [], settlements = [];
    const saving = deferred();
    const generation = {
      console, JSON, Math, Number, String, Promise, window: {},
      isGeneratingTenantSlides: false,
      tenantSlidePlan: { slides: Array.from({ length: 8 }, (_, i) => ({ title: 'Slide ' + i })) },
      tenantProjectData: { draftId: 'draft', project_name: 'Approved project' },
      tenantSlidesData: [], tenantSlideGenerationCheckpoint: null,
      tenantPresentationId: 'presentation', tenantPresentationTitle: 'Title',
      tenantCreativeImages: {}, tempCoverImage: null, tempMoodboardImages: {}, activeSlideIndex: 0,
      document: { getElementById: () => null, querySelectorAll: () => [] },
      tenantSlidePlanFingerprint: () => 'plan', tenantSlideGenerationOptions: options => options,
      collectTenantFormData: async () => ({}), persistVisualConceptDraftState() {},
      buildPresentationGenerationImages: () => ({}), slimGenerationProjectData: data => data,
      containsSlideRoot: value => value.includes('class="slide"'), showTenantPage() {},
      toast() {}, renderTenantSlidesSidebar() {}, renderTenantDesignerChat() {},
      checkpointPresentationUndo() {}, updatePresentationUndoButtons() {},
      setLiveGenBanner: (...args) => banners.push(args),
      settleGenerationRun: async consumed => settlements.push(consumed),
      requestTenantSlideGeneration(payload) {
        const request = deferred();
        requests.push({ index: payload._slideNum - 1, ...request });
        return request.promise;
      },
      async saveTenantSlideGenerationCheckpoint(index, status, error) {
        checkpoints.push({ index, status, error });
        if (blockedCheckpoint && status === 'running') await saving.promise;
        return true;
      },
    };
    vm.createContext(generation);
    vm.runInContext(generateSource, generation);
    const run = generation.generateTenantSlides({ approvalGranted: true, financialValidated: true });
    await flush();
    assert.deepEqual(requests.map(request => request.index), [0, 1, 2]);
    if (blockedCheckpoint) {
      requests[0].resolve(slide);
      await flush();
      assert.equal(checkpoints[0].status, 'running');
    }
    const message = 'Approved inputs changed';
    requests[1].resolve({ error_code: 'inputs_changed', error: message });
    await flush();
    assert.equal(requests.length, 3, 'A rejected worker must stop launches before ordered checkpointing');
    if (!blockedCheckpoint) requests[0].resolve(slide);
    requests[2].resolve(slide);
    saving.resolve();
    await run;
    assert.equal(generation.tenantSlidesData.length, 1);
    assert.equal(checkpoints.at(-1).status, 'paused');
    assert.equal(checkpoints.at(-1).index, 1);
    assert.equal(checkpoints.at(-1).error, message);
    assert.deepEqual(settlements, [false]);
    assert.equal(generation.isGeneratingTenantSlides, false);
    assert(banners.at(-1)[1].includes('توقف التوليد'));
    assert(banners.at(-1)[2].includes(message), 'The server refusal must remain visible');

    generation.tenantSlidesData = [];
    const expectedName = generation.tenantProjectData.project_name;
    generation.requestTenantSlideGeneration = async payload => {
      requests.push({ index: payload._slideNum - 1 });
      assert.equal(payload.projectData.project_name, expectedName, 'Every slide must use the same run inputs');
      generation.tenantProjectData.project_name = 'Changed after launch';
      return slide;
    };
    generation.saveTenantPresentation = async () => true;
    generation.triggerAutoSaveDraft = () => {};
    generation.selectTenantSlide = () => {};
    generation.setSlidesEditorInfo = () => {};
    generation.setTimeout = () => {};
    await generation.generateTenantSlides({ approvalGranted: true, financialValidated: true });
    assert.equal(generation.tenantSlidesData.length, 8);
    assert.equal(checkpoints.at(-1).status, 'complete');
    assert.deepEqual(settlements, [false, true]);
  }
}
