const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('index.html', 'utf8');
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
  console.log('Presentation save harness passed: update/create, conflict preservation, scoped generation reuse.');
})().catch(error => { console.error(error); process.exitCode=1; });
