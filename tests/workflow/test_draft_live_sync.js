/* tests/workflow/test_draft_live_sync.js — the open workspace follows the file in real-time.
 *
 * Real-time sync: an edit by somebody else updates the form in-place smoothly
 * without full-page reloads, without disrupting focus, and without kicking
 * the user away from their current section.
 *
 * Run from the repo root:  node tests/workflow/test_draft_live_sync.js
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = process.cwd();
const core = fs.readFileSync(path.join(root, 'assets/js/00-core.js'), 'utf8');
const liveSync = fs.readFileSync(
  path.join(root, 'assets/js/07-project-form/07_draft_live_sync.js'), 'utf8');

const coreStart = core.indexOf('    let tenantDraftRevision = 0;');
const coreEnd = core.indexOf('    let tenantPresentationProvenance = null;');
assert.ok(coreStart > 0 && coreEnd > coreStart,
  '00-core.js must own the workspace revision and the poll baseline');

const source = [
  core.slice(coreStart, coreEnd),
  liveSync,
  'globalThis.__live = () => ({ tenantDraftRevision, draftLiveSyncRevision,'
    + ' draftLocalSavePending, draftLiveSyncId });',
].join('\n');

const badge = { style: {}, innerHTML: '' };
const toasts = [];
const reloads = [];
const calls = [];
let serverState = { success: true, revision: 1, draftId: 'draft-1' };
let serverDraftPayload = {
  success: true,
  draft: {
    id: 'draft-1',
    revision: 3,
    draft_data: { project_name: 'برج جديد', city: 'الرياض' },
    section_statuses: { basic: 'approved' },
  },
};

const domInputs = [
  {
    dataset: { key: 'project_name' },
    value: 'برج قديم',
    type: 'text',
    classList: { add: () => {}, remove: () => {} },
  },
  {
    dataset: { key: 'city' },
    value: 'جدة',
    type: 'text',
    classList: { add: () => {}, remove: () => {} },
  },
];

let activeElement = null;

const formEl = {
  querySelectorAll: selector => (selector === '[data-key]' ? domInputs : []),
};

const context = {
  console, Number, String, Boolean, Promise, JSON, Object, Math, Date,
  setTimeout: () => 0,
  clearTimeout: () => {},
  document: {
    get activeElement() { return activeElement; },
    getElementById: id => {
      if (id === 'draftSyncBadge') return badge;
      if (id === 'tenantProjectForm') return formEl;
      return null;
    },
    addEventListener: () => {},
  },
  api: async (method, url) => {
    calls.push({ method, url });
    if (url.includes('/state')) return serverState;
    if (url.includes('/project-draft/')) return serverDraftPayload;
    return serverState;
  },
  WFT: (key, fallback) => fallback,
  toast: message => toasts.push(message),
  openProjectDraftById: id => { reloads.push(id); },
  tenantDraftDirty: false,
  tenantProjectMode: 'draft',
  tenantProjectData: { draftId: 'draft-1', project_name: 'برج قديم', city: 'جدة' },
  tenantProjectSectionStatuses: { basic: 'draft' },
  applySectionStatuses: statuses => {
    context.tenantProjectSectionStatuses = { ...context.tenantProjectSectionStatuses, ...statuses };
  },
};
vm.createContext(context);
vm.runInContext(source, context);

(async () => {
  await testOurOwnSaveIsNotSomebodyElsesChange();
  await testAChangeBySomebodyElseSyncsInPlaceWithoutReload();
  await testFocusedInputIsNotOverwrittenDuringLiveSync();
  await testTheChangeIsReportedOnce();
  await testThePollWaitsForOurOwnWrite();
  console.log('Draft live sync harness passed: own save, in-place realtime sync,'
    + ' focus preservation, single report, in-flight write.');
})().catch(error => { console.error(error); process.exitCode = 1; });

async function testOurOwnSaveIsNotSomebodyElsesChange() {
  reloads.length = 0;
  toasts.length = 0;
  calls.length = 0;
  context.startDraftLiveSync('draft-1', 1);
  context.setTenantDraftRevision(2);
  serverState = { success: true, revision: 2, draftId: 'draft-1' };
  await context.pollDraftLiveState();
  assert.equal(calls.length, 1);
  assert.ok(calls[0].url.includes('/state?since=2'), calls[0].url);
  assert.equal(reloads.length, 0, 'our own save must not reload the workspace');
  assert.equal(context.__live().tenantDraftRevision, 2);
  assert.equal(context.__live().draftLiveSyncRevision, 2);
}

async function testAChangeBySomebodyElseSyncsInPlaceWithoutReload() {
  reloads.length = 0;
  calls.length = 0;
  context.tenantDraftDirty = false;
  activeElement = null;
  context.startDraftLiveSync('draft-1', 2);
  serverState = { success: true, revision: 3, draftId: 'draft-1' };
  serverDraftPayload = {
    success: true,
    draft: {
      id: 'draft-1',
      revision: 3,
      draft_data: { project_name: 'برج جديد', city: 'الرياض' },
      section_statuses: { basic: 'approved' },
    },
  };
  await context.pollDraftLiveState();
  assert.equal(reloads.length, 0, 'realtime live sync must NOT reload workspace via openProjectDraftById');
  assert.equal(domInputs[0].value, 'برج جديد', 'input project_name must update in-place');
  assert.equal(domInputs[1].value, 'الرياض', 'input city must update in-place');
  assert.equal(context.tenantProjectData.project_name, 'برج جديد', 'backing data must update');
  assert.equal(context.tenantProjectSectionStatuses.basic, 'approved', 'section statuses must update');
  assert.equal(context.__live().tenantDraftRevision, 3);
  assert.equal(context.__live().draftLiveSyncRevision, 3);
}

async function testFocusedInputIsNotOverwrittenDuringLiveSync() {
  reloads.length = 0;
  calls.length = 0;
  // User is currently typing in project_name
  activeElement = domInputs[0];
  domInputs[0].value = 'تعديل المستخدم الحالي';
  context.tenantProjectData.project_name = 'تعديل المستخدم الحالي';

  serverState = { success: true, revision: 4, draftId: 'draft-1' };
  serverDraftPayload = {
    success: true,
    draft: {
      id: 'draft-1',
      revision: 4,
      draft_data: { project_name: 'اسم الخادم الذي يجب ألا يمسح حقل المستخدم', city: 'الدمام' },
      section_statuses: { basic: 'approved' },
    },
  };
  await context.pollDraftLiveState();
  assert.equal(reloads.length, 0);
  assert.equal(domInputs[0].value, 'تعديل المستخدم الحالي', 'active focused input must NOT be overwritten');
  assert.equal(domInputs[1].value, 'الدمام', 'non-focused input must update in real time');
  activeElement = null;
}

async function testTheChangeIsReportedOnce() {
  const currentCalls = calls.length;
  await context.pollDraftLiveState();
  // Polled state, but revision is still 4 so no duplicate fetch of /project-draft
  const stateCalls = calls.slice(currentCalls).filter(c => !c.url.includes('/state'));
  assert.equal(stateCalls.length, 0, 'the same revision must not be refetched');
}

async function testThePollWaitsForOurOwnWrite() {
  calls.length = 0;
  context.startDraftLiveSync('draft-1', 4);
  context.beginDraftLocalSave();
  await context.pollDraftLiveState();
  assert.equal(calls.length, 0, 'the poll must not read the server while our own write is in flight');
  assert.equal(context.__live().draftLocalSavePending, true);
  context.endDraftLocalSave();
  await context.pollDraftLiveState();
  assert.equal(calls.length, 1);
}
