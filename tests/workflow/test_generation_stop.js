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
  console, Number, String, Boolean, Promise, JSON, Object, Math, Date, AbortController,
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
  await testAnInlineRequestCarriesItsOwnRunHandle();
  await testAStoppedInlineRequestReadsAsStoppedNotFailed();
  await testStoppingAbortsTheRequestInFlight();
  console.log('Generation stop harness passed: X cancels, latches, and catches late runs.');
})().catch(error => { console.error(error); process.exitCode = 1; });

function reset() {
  calls.length = 0;
  hidden.length = 0;
  toasts.length = 0;
  context.resetTenantGenerationStop();
  elements.globalLoaderStopButton.style.display = 'none';
}

async function testAnInlineRequestCarriesItsOwnRunHandle() {
  reset();
  const original = context.api;
  let captured = null;
  context.api = async (method, url, body, isFile, options) => {
    // Only this request: a cancel posted by an earlier case may still be in
    // flight and must not be mistaken for the call under test.
    if (url !== '/api/generate-images') return { success: true };
    captured = { method, url, options, runs: context.__runs() };
    return { success: true };
  };
  try {
    const response = await context.apiStoppable('POST', '/api/generate-images', { a: 1 });
    assert.equal(response.success, true);
    assert.equal(captured.method, 'POST');
    assert.equal(captured.url, '/api/generate-images');
    const runId = captured.options.headers['X-Run-Id'];
    assert.match(runId, /^[A-Za-z0-9-]{8,64}$/,
      'the handle must satisfy the server run-id rule');
    assert.deepEqual(Array.from(captured.runs), [runId],
      'the run is registered while the call is in flight, so X can cancel it');
    assert.equal(context.__runs().length, 0, 'the handle is released after the answer');
  } finally {
    context.api = original;
  }
}

async function testAStoppedInlineRequestReadsAsStoppedNotFailed() {
  reset();
  const original = context.api;
  context.api = async () => ({
    success: false, error_code: 'RUN_CANCELLED', cancelled: true,
    partial: { cover: 'cover.png' },
  });
  try {
    const response = await context.apiStoppable('POST', '/api/generate-images', {});
    assert.equal(response.cancelled, true, 'a stopped request is a stop, not a failure');
    assert.equal(response.status, 'cancelled');
    assert.equal(response.partial.cover, 'cover.png',
      'the images already produced are handed back, not thrown away');
    assert.equal(context.__runs().length, 0);
  } finally {
    context.api = original;
  }
}

async function testStoppingAbortsTheRequestInFlight() {
  reset();
  const original = context.api;
  let seenSignal = null;
  context.api = async (method, url, body, isFile, options) => {
    if (url !== '/api/preview-map-data') return { success: true };
    seenSignal = options.signal;
    // A real fetch rejects when its signal aborts and api() turns that into an
    // error object; the stop must still read as a stop, not a network failure.
    return await new Promise(resolve => {
      options.signal.addEventListener('abort', () => resolve({ error: 'Network error: aborted' }));
    });
  };
  try {
    const pending = context.apiStoppable('POST', '/api/preview-map-data', {});
    await context.stopTenantGeneration();
    const response = await pending;
    assert.equal(seenSignal.aborted, true,
      'the request itself is cut, not only the work behind it');
    assert.equal(response.cancelled, true);
    assert.equal(response.error_code, 'RUN_CANCELLED');
  } finally {
    context.api = original;
  }
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
