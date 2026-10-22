/* tests/workflow/test_generation_stop.js — closing the progress card stops the work.
 *
 * The X on the floating loader used to call hideLoader() alone: the card
 * disappeared while the paid job kept running with no way back to it. The
 * close control must cancel every registered run before hiding.
 *
 * Run from the repo root:  node tests/workflow/test_generation_stop.js
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = process.cwd();
const source = fs.readFileSync(
  path.join(root, 'assets/js/13-visual/04_generation_stop.js'), 'utf8');

const calls = [];
const hidden = [];
const toasts = [];

const context = {
  console, Number, String, Boolean, Promise, JSON, Object, Math, Date,
  setTimeout: () => 0,
  clearTimeout: () => {},
  document: { getElementById: () => null },
  api: async (method, url) => {
    calls.push({ method, url });
    return { success: true };
  },
  apiWithTimeout: async () => ({}),
  WFT: (key, fallback) => fallback,
  toast: message => toasts.push(message),
  hideLoader: () => hidden.push(true),
};
vm.createContext(context);
vm.runInContext(source + [
  '',
  'globalThis.__runs = () => Array.from(tenantActiveGenerationRuns);',
  'globalThis.__stopRequested = () => tenantGenerationStopRequested;',
].join('\n'), context);

(async () => {
  testClosingWithARunCancelsIt();
  await testClosingWithoutARunOnlyHides();
  console.log('Generation stop harness passed: close cancels, empty close hides.');
})().catch(error => { console.error(error); process.exitCode = 1; });

function testClosingWithARunCancelsIt() {
  calls.length = 0;
  hidden.length = 0;
  context.registerTenantGenerationRun('job-1');
  context.registerTenantGenerationRun('job-2');
  context.closeGenerationPopup();
  assert.equal(hidden.length, 1, 'the card hides immediately');
  const urls = calls.map(call => call.url).sort();
  assert.deepEqual(urls, [
    '/api/runs/job-1/cancel',
    '/api/runs/job-2/cancel',
  ]);
  assert.equal(context.__runs().length, 0, 'the cancelled runs are released');
  assert.equal(context.__stopRequested(), false, 'the next run starts clean');
}

async function testClosingWithoutARunOnlyHides() {
  calls.length = 0;
  hidden.length = 0;
  await context.closeGenerationPopup();
  assert.equal(hidden.length, 1);
  assert.equal(calls.length, 0, 'a plain loader close must not call the server');
}
