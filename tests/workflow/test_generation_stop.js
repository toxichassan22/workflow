/* tests/workflow/test_generation_stop.js — closing the progress card stops the work.
 *
 * The X on the floating loader used to call hideLoader() alone: the card
 * disappeared while the paid job kept running with no way back to it. It now
 * cancels every registered run before hiding — and the stop it records stays
 * latched, because releasing a handle used to clear the flag the slide
 * launcher re-checked, so a stopped deck started every remaining slide.
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
const elements = {
  // The stop control is visible only on a generation loader; the shell ships
  // it hidden, exactly like index.html does.
  globalLoaderStopButton: { style: { display: 'none' }, disabled: false, textContent: '' },
  liveGenStopButton: { style: { display: 'none' }, disabled: false, textContent: '' },
};

const context = {
  console, Number, String, Boolean, Promise, JSON, Object, Math, Date,
  setTimeout: () => 0,
  clearTimeout: () => {},
  document: {
    getElementById: id => elements[id] || null,
    addEventListener: () => {},
    removeEventListener: () => {},
    hidden: false,
  },
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
  await testTheStopStaysLatchedAfterTheRunIsReleased();
  await testARunThatArrivesAfterTheStopIsCancelledAtOnce();
  await testANewActionClearsTheLatchedStop();
  await testClosingAPlainLoaderDoesNotStopAnything();
  await testTheVisibleStopControlLatchesEvenWithNoRunYet();
  console.log('Generation stop harness passed: X cancels, latches, and catches late runs.');
})().catch(error => { console.error(error); process.exitCode = 1; });

function reset() {
  calls.length = 0;
  hidden.length = 0;
  toasts.length = 0;
  context.resetTenantGenerationStop();
  elements.globalLoaderStopButton.style.display = 'none';
}

function testClosingWithARunCancelsIt() {
  reset();
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
  assert.equal(context.__stopRequested(), true,
    'releasing a handle must not restart the work the user stopped');
}

async function testTheStopStaysLatchedAfterTheRunIsReleased() {
  reset();
  context.registerTenantGenerationRun('deck-slide-1');
  await context.stopTenantGeneration();
  context.releaseTenantGenerationRun('deck-slide-1');
  assert.equal(context.__stopRequested(), true,
    'the slide launcher still has to see the stop after the last slice released');
}

async function testARunThatArrivesAfterTheStopIsCancelledAtOnce() {
  reset();
  // The user pressed X while the start request was still in flight: no handle
  // existed yet. When it arrives it must be cancelled rather than adopted.
  await context.stopTenantGeneration();
  calls.length = 0;
  context.registerTenantGenerationRun('late-job-9');
  await Promise.resolve();
  assert.deepEqual(calls.map(call => call.url), ['/api/runs/late-job-9/cancel']);
  assert.equal(context.__runs().length, 0);
}

async function testANewActionClearsTheLatchedStop() {
  reset();
  await context.stopTenantGeneration();
  assert.equal(context.__stopRequested(), true);
  context.resetTenantGenerationStop();
  assert.equal(context.__stopRequested(), false, 'a new action starts clean');
}

async function testClosingAPlainLoaderDoesNotStopAnything() {
  reset();
  await context.closeGenerationPopup();
  assert.equal(hidden.length, 1);
  assert.equal(calls.length, 0, 'a plain loader close must not call the server');
  assert.equal(context.__stopRequested(), false,
    'hiding a save spinner must not cancel a generation the user did not stop');
}

async function testTheVisibleStopControlLatchesEvenWithNoRunYet() {
  reset();
  // The generation loader shows its stop control; the X is the same command.
  elements.globalLoaderStopButton.style.display = 'inline-flex';
  await context.closeGenerationPopup();
  assert.equal(context.__stopRequested(), true,
    'closing a generation card before its job id arrives still records the stop');
}
