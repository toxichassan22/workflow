/* tests/workflow/test_draft_live_sync.js — the open workspace follows the file.
 *
 * The client side of the live sync: a change by somebody else has to reach the
 * workspace without a manual refresh, while a save of our own must never read
 * as somebody else's change (it used to reload the workspace under the person
 * who had just saved, and tell them the file had moved).
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

// The workspace revision and the poll baseline live in 00-core.js, the poll
// itself in 07_draft_live_sync.js. Both are evaluated as one script, so the
// lexical bindings are shared exactly as they are in the browser.
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

const context = {
  console, Number, String, Boolean, Promise, JSON, Object, Math, Date,
  setTimeout: () => 0,
  clearTimeout: () => {},
  document: {
    getElementById: id => (id === 'draftSyncBadge' ? badge : null),
    addEventListener: () => {},
  },
  api: async (method, url) => { calls.push({ method, url }); return serverState; },
  WFT: (key, fallback) => fallback,
  toast: message => toasts.push(message),
  openProjectDraftById: id => { reloads.push(id); },
  tenantDraftDirty: false,
  tenantProjectMode: 'draft',
};
vm.createContext(context);
vm.runInContext(source, context);

(async () => {
  await testOurOwnSaveIsNotSomebodyElsesChange();
  await testAChangeBySomebodyElseReloadsTheWorkspace();
  await testUnsavedEditsKeepTheFileUnderTheHands();
  await testTheChangeIsReportedOnce();
  await testThePollWaitsForOurOwnWrite();
  console.log('Draft live sync harness passed: own save, colleague change, unsaved edits,'
    + ' single report, in-flight write.');
})().catch(error => { console.error(error); process.exitCode = 1; });

async function testOurOwnSaveIsNotSomebodyElsesChange() {
  reloads.length = 0;
  toasts.length = 0;
  calls.length = 0;
  context.startDraftLiveSync('draft-1', 1);
  // Our own save landed: the workspace revision and the poll baseline move.
  context.setTenantDraftRevision(2);
  serverState = { success: true, revision: 2, draftId: 'draft-1' };
  await context.pollDraftLiveState();
  assert.equal(calls.length, 1);
  assert.ok(calls[0].url.includes('/state?since=2'), calls[0].url);
  assert.equal(reloads.length, 0, 'our own save must not reload the workspace');
  assert.equal(toasts.length, 0, 'our own save must not report a change');
  assert.equal(context.__live().tenantDraftRevision, 2);
  assert.equal(context.__live().draftLiveSyncRevision, 2);
}

async function testAChangeBySomebodyElseReloadsTheWorkspace() {
  reloads.length = 0;
  toasts.length = 0;
  context.tenantDraftDirty = false;
  context.startDraftLiveSync('draft-1', 2);
  serverState = { success: true, revision: 3, draftId: 'draft-1' };
  await context.pollDraftLiveState();
  assert.deepEqual(reloads, ['draft-1'], 'the file must be taken again without a manual refresh');
  assert.equal(toasts.length, 1);
  assert.equal(context.__live().draftLiveSyncRevision, 3);
}

async function testUnsavedEditsKeepTheFileUnderTheHands() {
  reloads.length = 0;
  toasts.length = 0;
  context.tenantDraftDirty = true;
  context.startDraftLiveSync('draft-1', 2);
  serverState = { success: true, revision: 3, draftId: 'draft-1' };
  await context.pollDraftLiveState();
  assert.equal(reloads.length, 0, 'unsaved edits must not be thrown away by a reload');
  assert.ok(String(badge.innerHTML).includes('اتغيّرت'), badge.innerHTML);
  assert.equal(context.__live().tenantDraftRevision, 2,
    'the save must still meet the newer revision and merge instead of writing over it');
  assert.equal(context.__live().draftLiveSyncRevision, 3);
  context.tenantDraftDirty = false;
}

async function testTheChangeIsReportedOnce() {
  toasts.length = 0;
  await context.pollDraftLiveState();
  assert.equal(toasts.length, 0, 'the same revision must not be reported twice');
}

async function testThePollWaitsForOurOwnWrite() {
  calls.length = 0;
  context.startDraftLiveSync('draft-1', 3);
  context.beginDraftLocalSave();
  await context.pollDraftLiveState();
  assert.equal(calls.length, 0, 'the poll must not read the server while our own write is in flight');
  assert.equal(context.__live().draftLocalSavePending, true);
  context.endDraftLocalSave();
  await context.pollDraftLiveState();
  assert.equal(calls.length, 1);
}
