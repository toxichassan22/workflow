/* tests/workflow/test_draft_live_sync.js — the open workspace follows the file.
 *
 * A remote save is applied only when this side has nothing unsaved. With
 * unsaved edits the file is not reloaded under the person's hands: the badge
 * reports it and the next save merges. Applying a remote change rebuilds the
 * whole form (market/financial/timeline widgets included), not just the plain
 * inputs.
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
const calls = [];
const hydrated = [];
let selectionRestored = 0;
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
    selectionStart: 3,
    selectionEnd: 3,
    setSelectionRange: () => { selectionRestored += 1; },
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
  openProjectDraftById: () => { throw new Error('must not reload the workspace'); },
  // The real hydrate writes every section's DOM; the test records the call and
  // mimics the two plain inputs it owns.
  hydrateTenantProjectForm: data => {
    hydrated.push(data);
    domInputs[0].value = data.project_name;
    domInputs[1].value = data.city;
  },
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
  await testAChangeBySomebodyElseHydratesTheWholeForm();
  await testUnsavedEditsAreNotOverwrittenByARemoteChange();
  await testTheChangeIsReportedOnce();
  await testThePollWaitsForOurOwnWrite();
  await testTheMergeSaveCanForceTheMergedStateIn();
  console.log('Draft live sync harness passed: own save, full hydration, dirty guard,'
    + ' single report, in-flight write, forced merge apply.');
})().catch(error => { console.error(error); process.exitCode = 1; });

async function testOurOwnSaveIsNotSomebodyElsesChange() {
  hydrated.length = 0;
  calls.length = 0;
  context.startDraftLiveSync('draft-1', 1);
  context.setTenantDraftRevision(2);
  serverState = { success: true, revision: 2, draftId: 'draft-1' };
  await context.pollDraftLiveState();
  assert.equal(calls.length, 1);
  assert.ok(calls[0].url.includes('/state?since=2'), calls[0].url);
  assert.equal(hydrated.length, 0, 'our own save must not reload the workspace');
  assert.equal(context.__live().tenantDraftRevision, 2);
  assert.equal(context.__live().draftLiveSyncRevision, 2);
}

async function testAChangeBySomebodyElseHydratesTheWholeForm() {
  hydrated.length = 0;
  calls.length = 0;
  selectionRestored = 0;
  context.tenantDraftDirty = false;
  activeElement = domInputs[0];
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
  assert.equal(hydrated.length, 1, 'the whole form is hydrated from the remote save');
  assert.deepEqual(
    JSON.parse(JSON.stringify(hydrated[0])),
    { project_name: 'برج جديد', city: 'الرياض' });
  assert.equal(domInputs[0].value, 'برج جديد');
  assert.equal(domInputs[1].value, 'الرياض');
  assert.equal(selectionRestored, 1, 'the caret is put back after hydration');
  assert.equal(context.tenantProjectData.project_name, 'برج جديد');
  assert.equal(context.tenantProjectSectionStatuses.basic, 'approved');
  assert.equal(context.__live().tenantDraftRevision, 3);
  assert.equal(context.__live().draftLiveSyncRevision, 3);
  activeElement = null;
}

async function testUnsavedEditsAreNotOverwrittenByARemoteChange() {
  hydrated.length = 0;
  calls.length = 0;
  context.tenantDraftDirty = true;
  context.startDraftLiveSync('draft-1', 3);
  serverState = { success: true, revision: 4, draftId: 'draft-1' };
  serverDraftPayload = {
    success: true,
    draft: {
      id: 'draft-1',
      revision: 4,
      draft_data: { project_name: 'اسم الخادم', city: 'الدمام' },
      section_statuses: { basic: 'approved' },
    },
  };
  await context.pollDraftLiveState();
  assert.equal(calls.filter(c => !c.url.includes('/state')).length, 0,
    'a dirty workspace must not fetch or apply the remote draft');
  assert.equal(hydrated.length, 0);
  assert.equal(context.__live().tenantDraftRevision, 3,
    'the merge base stays behind so the next save merges instead of overwriting');
  assert.equal(context.__live().draftLiveSyncRevision, 4,
    'the change is reported once');
  assert.match(badge.innerHTML, /اتغيّرت/);
  context.tenantDraftDirty = false;
}

async function testTheChangeIsReportedOnce() {
  const currentCalls = calls.length;
  await context.pollDraftLiveState();
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

async function testTheMergeSaveCanForceTheMergedStateIn() {
  hydrated.length = 0;
  calls.length = 0;
  context.tenantDraftDirty = true;
  serverDraftPayload = {
    success: true,
    draft: {
      id: 'draft-1',
      revision: 5,
      draft_data: { project_name: 'النسخة المدمجة', city: 'الرياض' },
      section_statuses: { basic: 'draft' },
    },
  };
  const applied = await context.applyLiveDraftSync('draft-1', 5, { force: true });
  assert.equal(applied, true);
  assert.equal(hydrated.length, 1);
  assert.equal(context.tenantProjectData.project_name, 'النسخة المدمجة');
  assert.equal(context.__live().tenantDraftRevision, 5);
  assert.equal(context.__live().draftLiveSyncRevision, 5);
  context.tenantDraftDirty = false;
}
