'use strict';

const assert = require('node:assert/strict');

module.exports = function registerPlanStatusAndWiringTests({
  test, fixture, source, dir, fs, path, vm,
}) {
test('visual plan polling bounds status requests and surfaces a stalled poll', async () => {
  const context = fixture();
  context.tenantVisualConceptState = context.normalizeVisualConceptState({
    slots: {}, plansWorkflow: { jobTodos: [
      { id: '1', label: 'تجهيز المشهد الهندسي', status: 'active' },
      { id: '2', label: 'تحليل المتطلبات', status: 'pending' },
    ] },
  });
  context.setTimeout = callback => { callback(); return 1; };
  let pollTimeout;
  context.api = async () => ({ jobId: 'job-1', status: 'queued', timeoutSeconds: 600 });
  context.apiWithTimeout = async (method, path, body, timeoutMs) => {
    assert.equal(method, 'GET');
    assert.match(path, /plans-jobs\/job-1$/);
    pollTimeout = timeoutMs;
    return { success: false, error: 'تعذر الاتصال بحالة المهمة', error_code: 'CLIENT_REQUEST_TIMEOUT' };
  };

  const result = await context.visualConceptPlanJobApi('POST', '/api/visual-concept/site-plan-assistant', {});

  assert.equal(pollTimeout, 15000);
  assert.equal(result.success, false);
  assert.equal(result.error_code, 'CLIENT_REQUEST_TIMEOUT');
  assert.equal(context.tenantVisualConceptState.plansWorkflow.jobTodos[0].status, 'failed');
  assert.doesNotMatch(source, /Date\.now\(\) \+ 7200000/);
});

test('visual plan polling ends at the server-provided job deadline', async () => {
  const context = fixture();
  context.tenantVisualConceptState = context.normalizeVisualConceptState({
    slots: {}, plansWorkflow: { jobTodos: [
      { id: '1', label: 'تجهيز المشهد الهندسي', status: 'active' },
    ] },
  });
  let now = 100000;
  context.Date = class extends Date { static now() { return now; } };
  context.setTimeout = (callback, delay) => { now += delay; callback(); return 1; };
  context.api = async () => ({ jobId: 'job-2', status: 'queued', timeoutSeconds: 2 });
  let polls = 0;
  context.apiWithTimeout = async () => {
    polls += 1;
    return { status: 'running', success: true };
  };

  const result = await context.visualConceptPlanJobApi('POST', '/api/visual-concept/site-plan-assistant', {});

  assert.equal(result.success, false);
  assert.equal(result.error_code, 'PLANS_JOB_EXPIRED');
  assert.ok(polls <= 8, `unexpected status poll count: ${polls}`);
  assert.equal(context.tenantVisualConceptState.plansWorkflow.jobTodos[0].status, 'failed');
});

test('the AI primary facade has its own external slot while legacy moodboard angles keep their order', () => {
  const context = fixture();
  const state = context.normalizeVisualConceptState({ slots: {}, plansWorkflow: {} });
  assert.equal(state.slots.main_facade.label, 'الواجهة الرئيسية');
  const angles = JSON.parse(JSON.stringify(vm.runInContext(
    'VISUAL_CONCEPT_ANGLE_SLOTS.map(item => item.id)', context)));
  const external = JSON.parse(JSON.stringify(vm.runInContext(
    'VISUAL_CONCEPT_EXTERNAL_SLOTS.map(item => item.id)', context)));
  assert.deepEqual(angles, ['right', 'left', 'top', 'back']);
  assert.ok(external.includes('main_facade'));
  const timeline = fs.readFileSync(path.resolve(__dirname,
    '../../../assets/js/10-financial-report-timeline/02_timeline_sidebar.js'), 'utf8');
  assert.match(timeline, /tenantCreativeImages\.main_facade_prompt/);
  assert.match(timeline, /item\.id === 'main_facade' \? tenantCreativeImages\.main_facade/);
});

test('site plan chat choices, surgical SVG source, and saved checkpoints are connected to the new assistant route', () => {
  const page = fs.readFileSync(path.resolve(__dirname,
    '../../../assets/js/13-visual/01_visual_concept_page.js'), 'utf8');
  const actions = fs.readFileSync(path.join(dir, '02d_visual_concept_plan_actions.js'), 'utf8');
  const renderer = fs.readFileSync(path.join(dir, '02_visual_concept.js'), 'utf8');
  assert.match(page, /\/api\/visual-concept\/site-plan-assistant/);
  assert.match(page, /payload\.siteSvgCode = liveSlot\(\)\.svgCode/);
  assert.match(page, /action === 'chat-choice'/);
  assert.match(page, /data-choice-other/);
  assert.match(page, /checkVisualConceptPlanNotes\(\{ silent: true \}\)/);
  assert.match(page, /event\.key !== 'Enter' \|\| event\.shiftKey/);
  assert.match(actions, /job\.checkpoint\?\.svgSections/);
  assert.match(renderer, /data-visual-action="chat-choice"/);
  const shell = fs.readFileSync(path.resolve(__dirname,
    '../../../assets/css/base/08_shell_chrome.css'), 'utf8');
  assert.match(shell, /\.visual-plan-site-message\.is-user\s*\{[^}]*align-self:\s*flex-start/s);
  assert.match(shell, /\.visual-plan-site-preview img\s*\{[^}]*max-height:\s*350px/s);
});

test('a clean verification still approves without opening the dialog', () => {
  const context = fixture();
  let created = false;
  context.document.createElement = () => {
    created = true;
    return { style: {}, setAttribute() {}, addEventListener() {},
      querySelector() { return { textContent: '' }; } };
  };
  context.tenantVisualConceptState = { slots: {},
    plansWorkflow: context.normalizeVisualConceptPlansWorkflow({
      verification: { canProceed: true,
        checks: [{ item: 'الارتداد', result: 'مطابق' }] },
      boundary: { points: [
        { eastings: 500000, northings: 2000000 },
        { eastings: 500100, northings: 2000000 },
        { eastings: 500050, northings: 2000100 }] },
    }) };
  context.markVisualConceptDirty = () => {};
  context.approveVisualConceptPlansVerification();
  assert.equal(context.tenantVisualConceptState.plansWorkflow.verification.approved, true);
  assert.equal(created, false);
});
};
