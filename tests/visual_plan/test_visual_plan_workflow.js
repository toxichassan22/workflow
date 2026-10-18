'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const registerJobErrorTests = require('./test_visual_plan_workflow_parts/01_job_error_details.js');
const registerPlanStatusAndWiringTests = require('./test_visual_plan_workflow_parts/02_plan_status_and_wiring.js');

const dir = path.resolve(__dirname, '../../assets/js/12-files-media');
const source = fs.readdirSync(dir).filter(file => /^02.*\.js$/.test(file)).sort()
  .map(file => fs.readFileSync(path.join(dir, file), 'utf8')).join('\n');
const visualPageSource = fs.readFileSync(path.resolve(__dirname,
  '../../assets/js/13-visual/01_visual_concept_page.js'), 'utf8');
const financialParkingSource = fs.readFileSync(path.resolve(__dirname,
  '../../assets/js/09-financial/03_parking_planning.js'), 'utf8');
const formSectionsSource = fs.readFileSync(path.resolve(__dirname,
  '../../assets/js/07-project-form/01_form_sections.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function fixture(includeVisualPage = false) {
  const context = vm.createContext({
    console, Intl, setTimeout, clearTimeout, setInterval, clearInterval, window: {},
    document: { addEventListener() {}, getElementById: () => null, querySelector: () => null,
      querySelectorAll: () => [] },
    tenantProjectData: {}, tenantCreativeImages: {}, tenantVisualConceptState: null,
    durableImageUrl: value => String(value || ''),
    isSessionOnlyImageUrl: () => false,
    visualConceptSlotLabel: id => id,
    visualConceptSlotLocked: () => false,
    escapeHtml: value => String(value).replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch])),
    WFT: (key, fallback, params = {}) => fallback.replace(/\{([^}]+)\}/g,
      (match, name) => params[name] ?? match),
    setDraftDirty() {}, renderVisualConceptPage() {},
    normalizeVisualConceptSketch: value => value || {}, emptyVisualConceptSketch: () => ({}),
    visualConceptReferenceNameSeed: value => value,
  });
  vm.runInContext(source, context);
  if (includeVisualPage) vm.runInContext(visualPageSource, context);
  return context;
}

registerJobErrorTests({ test, fixture });
registerPlanStatusAndWiringTests({ test, fixture, source, dir, fs, path, vm });

function installActiveSectionApproval(context) {
  const start = formSectionsSource.indexOf('    function activeProjectSectionKey()');
  const end = formSectionsSource.indexOf('    async function setSectionStatus', start);
  assert.ok(start >= 0 && end > start);
  vm.runInContext(formSectionsSource.slice(start, end), context);
}

test('plans approval is handled by the shared bottom action in the plans view', () => {
  const context = fixture();
  const button = { style: {}, dataset: {} };
  let approved = false;
  const called = [];
  context.tenantActiveProjectSection = 'section-visual-concept';
  context.tenantProjectSectionStatuses = { 'section-visual-concept': 'draft' };
  context.document.querySelector = selector => selector.includes('plans2d')
    ? { dataset: { visualConceptView: 'plans2d' } } : null;
  context.document.getElementById = id => id === 'activeSectionApproveBtn' ? button : null;
  context.getProjectSectionElement = () => ({ dataset: {} });
  context.visualConceptSectionApproved = () => approved;
  context.approveVisualConceptSection = id => { called.push(['approve', id]); approved = true; };
  context.unapproveVisualConceptSection = id => { called.push(['unapprove', id]); approved = false; };
  installActiveSectionApproval(context);

  context.refreshActiveSectionApproveButton();
  assert.equal(button.textContent, 'اعتماد القسم');
  context.toggleActiveSectionApproval();
  assert.deepEqual(called, [['approve', 'plans2d']]);

  context.refreshActiveSectionApproveButton();
  assert.equal(button.textContent, 'الغاء اعتماد القسم');
  context.toggleActiveSectionApproval();
  assert.deepEqual(called, [['approve', 'plans2d'], ['unapprove', 'plans2d']]);
});

test('plan notes and their review survive workflow normalization and JSON round trips', () => {
  const context = fixture();
  const data = { clientNotes: 'Keep the main entrance on the west facade.\nSeparate service access.',
    notesReview: { verified: true, inputSignature: 'checked-input', token: 'server-proof',
      canProceed: true, checks: [], issues: [] } };
  const state = plain(context.normalizeVisualConceptPlansWorkflow(JSON.stringify(data)));
  assert.equal(state.clientNotes, data.clientNotes);
  assert.equal(state.notesReview.inputSignature, 'checked-input');
  assert.equal(state.notesReview.token, 'server-proof');
  assert.equal(state.notesReview.verified, true);
});

test('site-plan SVG checkpoints retain their input signature and render revision', () => {
  const context = fixture();
  const state = plain(context.normalizeVisualConceptPlansWorkflow({
    siteAssistant: { inputSignature: 'current-input', renderRevision: 4,
      checkpoints: { components: '<g id="ll-section-components"/>' } }
  }));
  assert.equal(state.siteAssistant.inputSignature, 'current-input');
  assert.equal(state.siteAssistant.renderRevision, 4);
  assert.equal(state.siteAssistant.checkpoints.components, '<g id="ll-section-components"/>');
});

test('empty or boolean survey values cannot become invented zero coordinates', () => {
  const context = fixture();
  const result = plain(context.visualConceptBoundaryPoints([
    { point: '1', eastings: '', northings: 2000000 },
    { point: '2', eastings: true, northings: 2000010 },
    { point: '3', eastings: 500000, northings: 2000020 },
  ]));
  assert.equal(result.length, 1);
  assert.equal(result[0].point, '3');
});

test('changing notes invalidates their review and scene without removing saved images', () => {
  const context = fixture();
  context.tenantVisualConceptState = { slots: { plan_site: { imageUrl: '/uploads/creative/old.png' } },
    plansWorkflow: context.normalizeVisualConceptPlansWorkflow({
      clientNotes: 'old note', promptReady: true,
      prompts: { site: 'site', uses: 'uses', massing: 'massing' },
      scene: { version: 1, token: 'old-scene' },
      notesReview: { verified: true, canProceed: true, token: 'old-review' },
      distribution: { aiReviewed: true, reviewSignature: 'old-review-signature',
        checks: [{ item: 'مساحة التوزيع', result: 'متعارض' }],
        issues: [{ title: 'تعارض محفوظ' }], canProceed: false },
    }) };
  context.markVisualConceptDirty = () => {};
  context.setVisualConceptPlanNotes('new note');
  const workflow = plain(context.tenantVisualConceptState.plansWorkflow);
  assert.equal(workflow.clientNotes, 'new note');
  assert.equal(workflow.notesReview.verified, false);
  assert.equal(workflow.promptReady, false);
  assert.equal(workflow.scene, null);
  assert.equal(workflow.distribution.aiReviewed, false);
  assert.equal(workflow.distribution.reviewSignature, '');
  assert.equal(workflow.distribution.checks.length, 0);
  assert.equal(workflow.distribution.issues.length, 0);
  assert.equal(context.tenantVisualConceptState.slots.plan_site.imageUrl, '/uploads/creative/old.png');
});

test('verification conflicts approve only through the responsibility dialog', () => {
  const context = fixture();
  const modal = { style: {}, listeners: {},
    setAttribute() {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    querySelector() { return { textContent: '' }; } };
  context.document.createElement = () => modal;
  context.document.body = { appendChild() {} };
  context.tenantVisualConceptState = { slots: {},
    plansWorkflow: context.normalizeVisualConceptPlansWorkflow({
      verification: { canProceed: false, summary: 'يوجد تعارض واحد',
        checks: [{ item: 'الارتداد', result: 'متعارض', issues: ['الشمالي 5م مقابل 3م'] }] },
      boundary: { points: [
        { eastings: 500000, northings: 2000000 },
        { eastings: 500100, northings: 2000000 },
        { eastings: 500050, northings: 2000100 }] },
    }) };
  context.markVisualConceptDirty = () => {};
  context.approveVisualConceptPlansVerification();
  // The state getter re-normalizes into a fresh object each call — read the
  // stored workflow again after every step instead of holding a reference.
  // The approve click itself never approves a conflicted result — it opens
  // the warning instead.
  assert.equal(context.tenantVisualConceptState.plansWorkflow.verification.approved, false);
  assert.equal(modal.style.display, 'flex');
  // Only the dialog's own continue lands the approval, on the client's
  // responsibility.
  modal.listeners.click({ target: { closest: sel => sel === '[data-plans-risk-continue]' ? {} : null } });
  assert.equal(context.tenantVisualConceptState.plansWorkflow.verification.approved, true);
  assert.equal(context.tenantVisualConceptState.plansWorkflow.viewStage, 'boundary');
});

test('plan notes results list only unresolved findings — مطابق rows never render red', () => {
  const context = fixture();
  const workflow = context.normalizeVisualConceptPlansWorkflow({
    clientNotes: 'NOTE_MATCHED_TEXT\nNOTE_CONFLICT_TEXT',
    notesReview: { verified: true, canProceed: false, inputSignature: 's', token: 't',
      checks: [
        { index: 0, note: 'NOTE_MATCHED_TEXT', result: 'مطابق', detail: 'DETAIL_MATCHED' },
        { index: 1, note: 'NOTE_CONFLICT_TEXT', result: 'متعارض', detail: 'DETAIL_CONFLICT' },
      ], issues: [] }
  });
  const html = context.visualConceptPlanNotesResultsHtml(workflow);
  assert.ok(html.includes('plans-workflow-notice'));
  assert.ok(html.includes('NOTE_CONFLICT_TEXT'));
  assert.ok(html.includes('DETAIL_CONFLICT'));
  assert.ok(!html.includes('NOTE_MATCHED_TEXT'));
  assert.ok(!html.includes('DETAIL_MATCHED'));
  const clean = context.normalizeVisualConceptPlansWorkflow({
    clientNotes: 'NOTE_MATCHED_TEXT',
    notesReview: { verified: true, canProceed: true, inputSignature: 's', token: 't',
      checks: [{ index: 0, note: 'NOTE_MATCHED_TEXT', result: 'مطابق', detail: 'DETAIL_MATCHED' }],
      issues: [] }
  });
  const cleanHtml = context.visualConceptPlanNotesResultsHtml(clean);
  assert.ok(cleanHtml.includes('plans-workflow-success'));
  assert.ok(cleanHtml.includes('نتيجة فحص الملاحظات'));
  assert.ok(!cleanHtml.includes('NOTE_MATCHED_TEXT'));
  assert.ok(!cleanHtml.includes('DETAIL_MATCHED'));
});

test('distribution findings list conflicts only and approve no longer waits on notes', () => {
  const context = fixture();
  // Written but unchecked notes used to disable the approve button outright.
  context.tenantVisualConceptState = { slots: {},
    plansWorkflow: context.normalizeVisualConceptPlansWorkflow({
      clientNotes: 'unreviewed note', notesReview: { verified: false } }) };
  const distribution = context.normalizeVisualConceptPlansWorkflow({
    distribution: { aiReviewed: true,
      rows: [{ id: 'row_1', building: 'A', component: 'res' }],
      checks: [
        { item: 'ITEM_MATCHED', result: 'مطابق', detail: 'DETAIL_MATCHED' },
        { item: 'ITEM_CONFLICT', result: 'متعارض' },
      ], issues: [] }
  }).distribution;
  const html = context.visualConceptDistributionResultsHtml(distribution);
  assert.ok(html.includes('ITEM_CONFLICT'));
  assert.ok(html.includes('نتيجة فحص التوزيع'));
  assert.ok(!html.includes('ITEM_MATCHED'));
  assert.ok(!html.includes('DETAIL_MATCHED'));
  const button = html.match(/data-plans-workflow-action="approve-distribution"([^>]*)>/);
  assert.ok(button);
  assert.ok(!button[1].includes('disabled'));
});

test('a stage-two conflict review and its decision survive draft normalization', async () => {
  const context = fixture();
  context.tenantProjectData = {};
  context.showLoader = () => {};
  context.hideLoader = () => {};
  context.collectVisualConceptPlansWorkflowPayload = async () => ({ projectData: {}, plansWorkflow: {} });
  context.visualConceptPlanInputStamp = () => 'same-inputs';
  context.api = async (method, path) => {
    assert.equal(method, 'POST');
    assert.equal(path, '/api/visual-concept/plans-distribution-check');
    return {
      success: true,
      totals: [{ item: 'إجمالي المسطحات', value: 1200 }],
      checks: [{ item: 'المسطحات تتجاوز المسموح', result: 'متعارض', detail: 'تجاوز موثق' }],
      issues: [{ title: 'تعارض موثق', severity: 'high', points: ['يلزم تعديل المساحات'] }],
      canProceed: false
    };
  };
  context.tenantVisualConceptState = { slots: {}, plansWorkflow: context.normalizeVisualConceptPlansWorkflow({
    verification: { approved: true },
    distribution: { rows: [{ id: 'row_1', building: 'A', component: 'مكاتب' }] }
  }) };

  await context.checkVisualConceptPlansDistribution('ai');

  const draftSnapshot = JSON.stringify(context.tenantVisualConceptState);
  const reloaded = context.normalizeVisualConceptState(draftSnapshot).plansWorkflow.distribution;
  assert.equal(reloaded.checks[0].result, 'متعارض');
  assert.equal(reloaded.issues[0].title, 'تعارض موثق');
  assert.equal(reloaded.aiReviewed, true);
  assert.equal(reloaded.reviewSignature, 'same-inputs');
  assert.equal(reloaded.canProceed, false);
});

test('a legacy saved distribution review remains approvable after reload without another analysis', () => {
  const context = fixture();
  context.tenantProjectData = {};
  context.markVisualConceptDirty = () => {};
  context.renderVisualConceptPage = () => {};
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {}, plansWorkflow: {
    verification: { approved: true, canProceed: true },
    boundary: { approved: true },
    distribution: { approved: false, aiReviewed: true, canProceed: true,
      rows: [{ id: 'row_1', component: 'مكاتب' }],
      checks: [{ item: 'المساحات', result: 'مطابق' }], issues: [] },
    sourceStamp: 'older-downstream-stamp', viewStage: 'generate',
  } });

  const savedDraft = JSON.stringify(context.tenantVisualConceptState);
  context.tenantVisualConceptState = context.normalizeVisualConceptState(savedDraft);
  context.syncVisualConceptPlanInputs(context.tenantProjectData);

  const workflow = context.tenantVisualConceptState.plansWorkflow;
  assert.equal(workflow.distribution.aiReviewed, true);
  assert.equal(workflow.distribution.reviewSignature, context.visualConceptPlanInputStamp());
  assert.equal(workflow.distribution.checks[0].result, 'مطابق');
  assert.equal(workflow.viewStage, 'generate');
  const html = context.visualConceptDistributionResultsHtml(workflow.distribution);
  const approveButton = html.match(/data-plans-workflow-action="approve-distribution"([^>]*)>/);
  assert.ok(approveButton);
  assert.ok(!approveButton[1].includes('disabled'));

  context.approveVisualConceptPlansDistribution();
  assert.equal(context.tenantVisualConceptState.plansWorkflow.distribution.approved, true);
});

test('financial parking hydration cannot revoke a saved distribution review mid-load', () => {
  const context = fixture();
  vm.runInContext(financialParkingSource, context);
  context.tenantProjectFormIsFilled = () => false;
  context.persistVisualConceptDraftState = () => {};
  context.tenantProjectData = {};
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {}, plansWorkflow: {
    distribution: { rows: [{ id: 'row_1', component: 'مكاتب' }], aiReviewed: true,
      approved: true, reviewSignature: 'saved-review' }
  } });

  assert.equal(context.financialParkingInvalidateVisuals(), false);
  assert.equal(context.tenantVisualConceptState.plansWorkflow.distribution.aiReviewed, true);
  assert.equal(context.tenantVisualConceptState.plansWorkflow.distribution.approved, true);

  context.tenantProjectFormIsFilled = () => true;
  assert.equal(context.financialParkingInvalidateVisuals(), true);
  assert.equal(context.tenantVisualConceptState.plansWorkflow.distribution.aiReviewed, false);
  assert.equal(context.tenantVisualConceptState.plansWorkflow.distribution.approved, false);
});

test('unchecked notes approve through the responsibility dialog with a signed ack', async () => {
  const context = fixture();
  const modal = { style: {}, listeners: {},
    setAttribute() {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    querySelector() { return { textContent: '' }; } };
  context.document.createElement = () => modal;
  context.document.body = { appendChild() {} };
  context.toast = () => {};
  context.collectVisualConceptPayload = async () => ({ projectData: {} });
  context.api = async (method, path) => {
    assert.equal(path, '/api/visual-concept/plans-notes-acknowledge');
    return { success: true, notesAck: { acknowledged: true, inputSignature: 'sig', token: 'ack-token' } };
  };
  context.tenantVisualConceptState = { slots: {},
    plansWorkflow: context.normalizeVisualConceptPlansWorkflow({
      clientNotes: 'ملاحظة مكتوبة', notesReview: { verified: false },
      distribution: { aiReviewed: true, canProceed: true,
        rows: [{ id: 'row_1', building: 'A', component: 'res' }] },
    }) };
  context.markVisualConceptDirty = () => {};
  // The approve click itself never approves pending notes — it opens the
  // warning; only the dialog's own continue signs the ack and lands approval.
  context.approveVisualConceptPlansDistribution();
  assert.equal(context.tenantVisualConceptState.plansWorkflow.distribution.approved, false);
  assert.equal(modal.style.display, 'flex');
  modal.listeners.click({ target: { closest: sel => sel === '[data-plans-risk-continue]' ? {} : null } });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(context.tenantVisualConceptState.plansWorkflow.distribution.approved, true);
  assert.equal(context.tenantVisualConceptState.plansWorkflow.notesReview.acknowledged, true);
  assert.equal(context.tenantVisualConceptState.plansWorkflow.notesReview.ackToken, 'ack-token');
  assert.equal(context.visualConceptPlanNotesCleared(context.tenantVisualConceptState.plansWorkflow), true);
});

test('the processing lock repaints once prepare finishes instead of lingering', async () => {
  const context = fixture();
  const locks = [];
  context.renderVisualConceptPage = () =>
    locks.push(context.visualConceptLockMessage('plan_site'));
  context.showLoader = () => {};
  context.hideLoader = () => {};
  context.toast = () => {};
  context.api = async () => ({ success: true,
    prompts: { site: 'site', uses: 'uses', massing: 'massing' },
    scene: { version: 1, token: 'sealed' }, planContext: {} });
  context.tenantVisualConceptState = { slots: { cover: {} },
    plansWorkflow: context.normalizeVisualConceptPlansWorkflow({
      verification: { approved: true },
      boundary: { approved: true, points: [
        { eastings: 0, northings: 0 }, { eastings: 10, northings: 0 },
        { eastings: 10, northings: 10 }] },
      distribution: { approved: true,
        rows: [{ id: 'row_1', building: 'A', component: 'res' }] },
    }) };
  await context.prepareVisualConceptPlansPrompts();
  assert.ok(locks.length > 0);
  // Every render inside the request runs with the pending flag up; the
  // trailing repaint after it clears is what stops «قيد المعالجة» lingering.
  assert.notEqual(locks[locks.length - 1], 'المشهد الهندسي قيد المعالجة.');
});

test('approving stages one and two survives a saved draft and a reload', () => {
  const context = fixture();
  const data = {
    verification: { approved: true, canProceed: true, summary: '', checks: [], issues: [] },
    boundary: { approved: true, referenceUrl: '/uploads/creative/parcel.png', points: [
      { point: '1', eastings: 500000, northings: 2000000 },
      { point: '2', eastings: 500020, northings: 2000000 },
      { point: '3', eastings: 500020, northings: 2000020 }] },
    distribution: { approved: true, aiReviewed: true,
      rows: [{ id: 'row_1', building: 'A', component: 'res' }] },
  };
  // The draft stores the workflow as JSON; a reload normalizes it right back.
  const reloaded = context.normalizeVisualConceptPlansWorkflow(
    JSON.stringify(context.normalizeVisualConceptPlansWorkflow(data)));
  assert.equal(reloaded.verification.approved, true);
  assert.equal(reloaded.boundary.approved, true);
  assert.equal(reloaded.distribution.approved, true);
  assert.equal(reloaded.distribution.aiReviewed, true);
  assert.equal(reloaded.boundary.points.length, 3);
  assert.equal(reloaded.boundary.referenceUrl, '/uploads/creative/parcel.png');
  // No notes written, so the notes gate is already clear — nothing to redo.
  assert.equal(context.visualConceptPlanNotesCleared(reloaded), true);
});

test('a saved conflict review survives financial calculations rebuilt on draft reload', () => {
  const context = fixture();
  const before = { financial_study_model: {
    inputs: { basementArea: 800, landArea: 2500 },
    dynamicRows: { components: [{ id: 'component_1', name: 'مكاتب', units: 20 }] },
    parkingPlan: { id: 'parking_1', approved: true, requiredSpaces: 20 },
    projection: { totalCosts: 1000000 },
  } };
  context.tenantVisualConceptState = context.normalizeVisualConceptState({
    slots: {},
    plansWorkflow: { verification: { approved: true, canProceed: false,
      summary: 'تعارض واحد', checks: [{ item: 'الارتداد', result: 'متعارض' }] },
      boundary: { approved: true, points: [
        { eastings: 1, northings: 1 }, { eastings: 2, northings: 1 }, { eastings: 2, northings: 2 }] },
      distribution: { approved: true, aiReviewed: true, rows: [{ id: 'row_1', component: 'مكاتب' }] },
      notesReview: { verified: true, canProceed: true, inputSignature: 'notes-signature' } }
  });
  context.tenantVisualConceptState.plansWorkflow.sourceStamp = context.visualConceptPlanInputStamp(before);

  // Draft loading recalculates projections and can add unrelated financial data.
  const after = { financial_study_model: { ...before.financial_study_model,
    projection: { totalCosts: 1000000, netIncome: 450000 },
    financialCalcData: { summary: 'recomputed' } } };
  const savedDraft = JSON.stringify(context.tenantVisualConceptState);
  context.tenantVisualConceptState = context.normalizeVisualConceptState(savedDraft);
  context.syncVisualConceptPlanInputs(after);

  const workflow = context.tenantVisualConceptState.plansWorkflow;
  assert.equal(workflow.verification.approved, true);
  assert.equal(workflow.verification.checks[0].item, 'الارتداد');
  assert.equal(workflow.boundary.approved, true);
  assert.equal(workflow.distribution.approved, true);
  assert.equal(workflow.notesReview.verified, true);
});

test('a saved conflict review survives survey coordinates changing from JSON text to hydrated rows', () => {
  const context = fixture();
  const before = { survey_coordinates: JSON.stringify([
    { point: '1', eastings: '500000', northings: '2000000' },
    { point: '2', eastings: '500020', northings: '2000000' },
    { point: '3', eastings: '500020', northings: '2000020' },
  ]) };
  context.tenantProjectData = before;
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {},
    plansWorkflow: {
      verification: { approved: true, canProceed: false,
        checks: [{ item: 'الارتداد', result: 'متعارض' }] },
      boundary: { approved: true, points: [
        { eastings: 1, northings: 1 }, { eastings: 2, northings: 1 }, { eastings: 2, northings: 2 }] },
      distribution: { approved: true, aiReviewed: true,
        rows: [{ id: 'row_1', component: 'مكاتب' }],
        checks: [{ item: 'المساحة', result: 'متعارض' }] },
    }
  });
  context.tenantVisualConceptState.plansWorkflow.sourceStamp = context.visualConceptPlanInputStamp(before);

  // Hydration rebuilds the editable table and stores its rows as an array.
  const after = { survey_coordinates: JSON.parse(before.survey_coordinates) };
  const savedDraft = JSON.stringify(context.tenantVisualConceptState);
  context.tenantVisualConceptState = context.normalizeVisualConceptState(savedDraft);
  context.tenantProjectData = after;
  context.syncVisualConceptPlanInputs(after);

  const workflow = context.tenantVisualConceptState.plansWorkflow;
  assert.equal(workflow.verification.approved, true);
  assert.equal(workflow.verification.checks[0].item, 'الارتداد');
  assert.equal(workflow.distribution.approved, true);
  assert.equal(workflow.distribution.aiReviewed, true);
  assert.equal(workflow.distribution.checks[0].item, 'المساحة');
});

test('a saved approval survives numeric inputs hydrating from numbers to strings', () => {
  for (const verification of [
    { approved: true, canProceed: false, checks: [{ item: 'الارتداد', result: 'متعارض' }] },
    { approved: true, canProceed: true, checks: [{ item: 'الارتداد', result: 'مطابق' }] },
  ]) {
    const context = fixture();
    const before = {
      approved_floor_count: 4,
      approved_coverage_ratio: 60,
      boundary_lengths: { north_length: 24 },
      project_components_data: [{ id: 'component_1', units_per_floor: 12, floor_area_sqm: 840 }],
      financial_study_model: {
        inputs: { basementArea: 800 },
        dynamicRows: { components: [{ id: 'component_1', units: 12 }] },
        parkingPlan: { id: 'parking_1', requiredSpaces: 24 },
      },
    };
    context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {}, plansWorkflow: {
      verification,
      boundary: { approved: true, points: [
        { eastings: 1, northings: 1 }, { eastings: 2, northings: 1 }, { eastings: 2, northings: 2 }] },
      distribution: { approved: true, aiReviewed: true,
        rows: [{ id: 'row_1', component: 'مكاتب', units_per_floor: 12 }] },
    } });
    context.tenantVisualConceptState.plansWorkflow.sourceStamp = context.visualConceptPlanInputStamp(before);

    const after = {
      approved_floor_count: '4',
      approved_coverage_ratio: '60',
      boundary_lengths: { north_length: '24' },
      project_components_data: [{ id: 'component_1', units_per_floor: '12', floor_area_sqm: '840' }],
      financial_study_model: {
        inputs: { basementArea: '800' },
        dynamicRows: { components: [{ id: 'component_1', units: '12' }] },
        parkingPlan: { id: 'parking_1', requiredSpaces: '24' },
      },
    };
    context.syncVisualConceptPlanInputs(after);

    const reloaded = context.tenantVisualConceptState.plansWorkflow;
    assert.equal(reloaded.verification.approved, true);
    assert.equal(reloaded.verification.checks[0].item, 'الارتداد');
    assert.equal(reloaded.distribution.approved, true);
    assert.equal(reloaded.distribution.aiReviewed, true);
  }
});

test('distribution checks and approval survive regulation coordinates hydrating from JSON', () => {
  for (const conflicted of [false, true]) {
    const context = fixture();
    const modal = { style: {}, listeners: {}, setAttribute() {},
      addEventListener(type, fn) { this.listeners[type] = fn; },
      querySelector() { return { textContent: '' }; } };
    context.document.createElement = () => modal;
    context.document.body = { appendChild() {} };
    context.markVisualConceptDirty = () => {};
    context.renderVisualConceptPage = () => {};
    const before = { regulation_coordinates: JSON.stringify([
      { point: '1', eastings: '500000', northings: '2000000', source: 'regulation_table' },
      { point: '2', eastings: '500020', northings: '2000000', source: 'regulation_table' },
      { point: '3', eastings: '500020', northings: '2000020', source: 'regulation_table' },
    ]) };
    context.tenantProjectData = before;
    context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {}, plansWorkflow: {
      verification: { approved: true, canProceed: true },
      boundary: { approved: true, points: [
        { eastings: 1, northings: 1 }, { eastings: 2, northings: 1 }, { eastings: 2, northings: 2 }] },
      distribution: { rows: [{ id: 'row_1', component: 'مكاتب' }], aiReviewed: true,
        canProceed: !conflicted,
        checks: [{ item: 'الارتداد', result: conflicted ? 'متعارض' : 'مطابق' }] },
    } });
    context.tenantVisualConceptState.plansWorkflow.sourceStamp = context.visualConceptPlanInputStamp(before);

    const after = { regulation_coordinates: [
      { point: 1, eastings: 500000, northings: 2000000, source: 'hydrated' },
      { point: 2, eastings: 500020, northings: 2000000, source: 'hydrated' },
      { point: 3, eastings: 500020, northings: 2000020, source: 'hydrated' },
    ] };
    context.syncVisualConceptPlanInputs(after);

    assert.equal(context.tenantVisualConceptState.plansWorkflow.distribution.aiReviewed, true);
    context.approveVisualConceptPlansDistribution();
    if (conflicted) {
      modal.listeners.click({ target: { closest: selector =>
        selector === '[data-plans-risk-continue]' ? {} : null } });
    }
    assert.equal(context.tenantVisualConceptState.plansWorkflow.distribution.approved, true);
  }
});

test('a changed parking plan invalidates the saved conflict review and approvals', () => {
  const context = fixture();
  const before = { financial_study_model: { inputs: { basementArea: 800 },
    dynamicRows: { components: [{ id: 'parking_row', parkingPlanId: 'parking_1', units: 20 }] },
    parkingPlan: { id: 'parking_1', approved: true, requiredSpaces: 20 } } };
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {},
    plansWorkflow: { verification: { approved: true, canProceed: false, checks: [{ item: 'الارتداد', result: 'متعارض' }] },
      boundary: { approved: true }, distribution: { approved: true, aiReviewed: true,
        checks: [{ item: 'المساحة', result: 'متعارض' }],
        issues: [{ title: 'تعارض محفوظ' }], canProceed: false },
      notesReview: { verified: true, canProceed: true } } });
  const reviewStamp = context.visualConceptPlanInputStamp(before);
  context.tenantVisualConceptState.plansWorkflow.sourceStamp = reviewStamp;
  context.tenantVisualConceptState.plansWorkflow.distribution.reviewSignature = reviewStamp;

  context.syncVisualConceptPlanInputs({ financial_study_model: { ...before.financial_study_model,
    parkingPlan: { ...before.financial_study_model.parkingPlan, requiredSpaces: 24 } } });

  const workflow = context.tenantVisualConceptState.plansWorkflow;
  assert.equal(workflow.verification.approved, false);
  assert.equal(workflow.verification.checks.length, 0);
  assert.equal(workflow.boundary.approved, true);
  assert.equal(workflow.distribution.approved, false);
  assert.equal(workflow.distribution.aiReviewed, false);
  assert.equal(workflow.distribution.reviewSignature, '');
  assert.equal(workflow.distribution.checks.length, 0);
  assert.equal(workflow.distribution.issues.length, 0);
});

test('deleted project components clear the stale site-plan chat and SVG cache', () => {
  const context = fixture();
  const before = {
    project_components_data: [{ id: 'deleted-villa', name: 'فلل محذوفة', builtArea: 12000 }],
    financial_study_model: { dynamicRows: { components: [
      { id: 'deleted-villa', name: 'فلل محذوفة', builtArea: 12000 },
    ] } },
  };
  context.tenantProjectData = before;
  context.tenantVisualConceptState = context.normalizeVisualConceptState({
    slots: { plan_site: { imageUrl: '/uploads/old-site.svg', approvedImageUrl: '/uploads/old-site.svg',
      svgCode: '<svg>فلل محذوفة</svg>', chat: [{ role: 'assistant', text: 'مبنى قديم' }] } },
    plansWorkflow: { siteAssistant: { inputSignature: 'old-signature', summary: 'ذاكرة عن الفلل القديمة',
      turns: [{ role: 'assistant', text: 'مبنى قديم' }], checkpoints: { components: '<g>فلل محذوفة</g>' } } },
  });
  context.tenantVisualConceptState.plansWorkflow.sourceStamp = context.visualConceptPlanInputStamp(before);

  const after = {
    project_components_data: [],
    financial_study_model: { dynamicRows: { components: [] } },
  };
  context.syncVisualConceptPlanInputs(after);

  const workflow = context.tenantVisualConceptState.plansWorkflow;
  const site = context.tenantVisualConceptState.slots.plan_site;
  assert.equal(workflow.siteAssistant.summary, '');
  assert.deepEqual(plain(workflow.siteAssistant.turns), []);
  assert.deepEqual(plain(workflow.siteAssistant.checkpoints), {});
  assert.equal(site.svgCode, '');
  assert.deepEqual(plain(site.chat), []);
  assert.equal(site.imageUrl, '/uploads/old-site.svg');
  assert.equal(site.approvedImageUrl, '');
  assert.equal(site.status, 'review');
});

test('page preflight and image deletion keep the approved plan workflow on stage three', async () => {
  const context = fixture(true);
  const project = {};
  context.tenantProjectData = project;
  context.tenantCreativeImages = {};
  context.tenantVisualConceptState = context.normalizeVisualConceptState({
    slots: { plan_site: { imageUrl: '/uploads/creative/old-site-plan.png', status: 'review' } },
    plansWorkflow: {
      verification: { approved: true, canProceed: true,
        checks: [{ item: 'الارتداد', result: 'مطابق' }] },
      boundary: { approved: true },
      distribution: { approved: true, aiReviewed: true, rows: [{ id: 'row_1', component: 'مكاتب' }] },
      sourceStamp: 'stamp-from-a-previous-input-set',
      viewStage: 'generate',
    }
  });
  context.tenantVisualConceptState.plansWorkflow.sourceStamp = 'stamp-from-a-previous-input-set';
  context.visualConceptSyncSectionApprovals = () => {};
  context.renderVisualConceptPage = () => {};
  context.showVisualConceptMissing = () => {};
  context.visualConceptMissingMessage = () => '';
  context.toast = () => {};
  context.api = async () => ({ success: true });

  await context.refreshVisualConceptPreflight();
  context.deleteVisualConceptSlotImage('plan_site');

  const workflow = context.tenantVisualConceptState.plansWorkflow;
  assert.equal(context.tenantVisualConceptState.slots.plan_site.imageUrl, '');
  assert.equal(workflow.verification.approved, true);
  assert.equal(workflow.distribution.approved, true);
  assert.equal(workflow.distribution.aiReviewed, true);
  assert.equal(workflow.viewStage, 'generate');
  const root = workflowRoot(context);
  context.renderVisualConceptPlansWorkflow();
  assert.equal(panelsOf(root).find(panel => panel.stage === 'generate').hidden, false);
  assert.equal(panelsOf(root).find(panel => panel.stage === 'boundary').hidden, true);
});

function workflowRoot(context) {
  const root = {
    innerHTML: '', dataset: {}, panels: [], listeners: {},
    addEventListener(type, fn) { (root.listeners[type] ||= []).push(fn); },
    querySelector() { return null; },
    querySelectorAll(selector) {
      if (selector !== '[data-plans-workflow-stage]') return [];
      if (!root.panels.length) {
        root.panels = Array.from(
          root.innerHTML.matchAll(/<section[^>]*data-plans-workflow-stage="([a-z0-9]+)"([^>]*)>/g))
          .map(match => ({ stage: match[1], hidden: /\bhidden\b/.test(match[2]),
            getAttribute: () => match[1] }));
      }
      return root.panels;
    },
  };
  context.document.getElementById = id => (id === 'visualConceptPlansWorkflow' ? root : null);
  return root;
}

function renderVerificationWorkflow(context, verification) {
  context.tenantVisualConceptState = { slots: {}, plansWorkflow: context.normalizeVisualConceptPlansWorkflow({ verification }) };
  context.renderVisualConceptSlot = () => '';
  context.visualConceptSlotLocked = () => false;
  const root = workflowRoot(context);
  context.renderVisualConceptPlansWorkflow();
  return root.innerHTML;
}

test('verification shows one clean result and omits the empty findings table', () => {
  const context = fixture();
  const clean = renderVerificationWorkflow(context, {
    canProceed: true, summary: 'تم الفحص', checks: [], issues: []
  });
  assert.equal((clean.match(/لا توجد تعارضات مباشرة\./g) || []).length, 1);
  assert.ok(!clean.includes('plans-check-table'));

  const unchecked = renderVerificationWorkflow(context, {});
  assert.ok(unchecked.includes('لم يتم فحص التعارضات بعد.'));
  assert.ok(!unchecked.includes('لا توجد تعارضات مباشرة.'));

  const needsReview = renderVerificationWorkflow(context, {
    canProceed: true,
    checks: [{ item: 'الارتداد', result: 'يحتاج تأكيد' }],
    issues: []
  });
  assert.ok(needsReview.includes('plans-check-table'));
  assert.ok(needsReview.includes('يحتاج تأكيد'));
});

test('distribution rows are grouped by building and use a contained sticky-header table', () => {
  const context = fixture();
  const html = context.visualConceptDistributionEditorHtml({ rows: [
    { id: 'row_1', building: 'البرج أ', floor_range: '1', component: 'مكاتب' },
    { id: 'row_2', building: 'البرج ب', floor_range: '1', component: 'مكاتب' },
    { id: 'row_3', building: 'البرج أ', floor_range: '2', component: 'مكاتب' },
  ], totals: [] });
  assert.equal((html.match(/class="plans-distribution-building"/g) || []).length, 2);
  assert.ok(html.includes('عدد البنود: 2'));
  assert.ok(html.includes('plans-distribution-table-wrap'));
  assert.ok(html.indexOf('data-dist-id="row_3"') < html.indexOf('data-dist-id="row_2"'));

  const styles = fs.readFileSync(path.resolve(__dirname,
    '../../assets/css/project-form/06_visual_concept_plans.css'), 'utf8');
  assert.match(styles, /\.plans-distribution-table-wrap\s*\{[^}]*overflow:\s*auto/s);
  assert.match(styles, /\.plans-distribution-table thead th\s*\{[^}]*position:\s*sticky/s);
  assert.match(styles, /\.plans-workflow-distribution-panel\s*\{[^}]*padding-bottom:\s*72px/s);
});

function panelsOf(root) {
  root.querySelectorAll('[data-plans-workflow-stage]');
  return root.panels;
}

function sealedWorkflowState(context) {
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {}, plansWorkflow: {
    verification: { approved: true },
    distribution: { approved: true, rows: [{ id: 'row_1', building: 'A', component: 'res' }] },
  } });
  return context.tenantVisualConceptState.plansWorkflow;
}

function clickWorkflowTab(context, root, stage) {
  const tab = { disabled: false, getAttribute: () => stage };
  const event = { target: { closest: sel => (sel === '[data-plans-workflow-tab]' ? tab : null) } };
  (root.listeners.click || []).forEach(listener => listener(event));
}

test('stage three renders only the simplified SVG site plan and stage four renders the other two plans', () => {
  const context = fixture();
  context.trDynamicI18n = value => value;
  context.isSessionOnlyImageUrl = () => false;
  context.visualConceptSlotLabel = id => id;
  context.visualConceptSlotLocked = () => false;
  context.markVisualConceptDirty = () => {};
  context.persistVisualConceptDraftState = () => {};
  const workflow = sealedWorkflowState(context);
  workflow.viewStage = 'generate';
  workflow.scene = { version: 1, token: 'sealed-scene' };
  workflow.prompts = { site: 'site prompt', uses: 'uses prompt', massing: 'massing prompt' };
  workflow.promptReady = true;
  context.tenantVisualConceptState = context.normalizeVisualConceptState(context.tenantVisualConceptState);
  context.renderVisualConceptPage = () => context.renderVisualConceptPlansWorkflow();
  context.tenantVisualConceptState.slots.plan_site.chat = [
    { role: 'user', text: 'Generate the site plan.' },
    { role: 'assistant', text: 'Which entrance should be primary?', choices: ['West', 'South'] },
  ];
  const root = workflowRoot(context);

  context.renderVisualConceptPlansWorkflow();
  const stageThree = root.innerHTML.match(/<section class="plans-workflow-panel" data-plans-workflow-stage="generate"[^>]*>([\s\S]*?)<\/section>/)[1];
  assert.ok(stageThree.includes('المخطط العام المبسط بصيغة SVG'));
  assert.ok(stageThree.includes('data-visual-slot="plan_site"'));
  assert.ok(stageThree.includes('data-choice-other="true"'));
  assert.ok(stageThree.includes('data-visual-chat="plan_site"'));
  assert.ok(!stageThree.includes('data-visual-chat-upload'));
  assert.ok(!stageThree.includes('data-visual-action="chat-attach"'));
  assert.ok(!stageThree.includes('data-plans-workflow-action="check-notes"'));
  assert.ok(!stageThree.includes('data-plans-workflow-action="prepare-prompts"'));
  assert.ok(!stageThree.includes('وصف المخطط'));
  assert.ok(!stageThree.includes('تجهيز المخطط'));
  assert.ok(!stageThree.includes('data-visual-action="generate"'));
  assert.ok(!stageThree.includes('data-visual-slot="plan_uses"'));
  assert.ok(!stageThree.includes('data-visual-slot="plan_massing"'));
  assert.deepEqual(panelsOf(root).filter(panel => !panel.hidden).map(panel => panel.stage), ['generate']);

  root.panels = [];
  clickWorkflowTab(context, root, 'other');
  assert.equal(context.tenantVisualConceptState.plansWorkflow.viewStage, 'other');
  const stageFour = root.innerHTML.match(/<section class="plans-workflow-panel" data-plans-workflow-stage="other"[^>]*>([\s\S]*?)<\/section>/)[1];
  assert.ok(stageFour.includes('data-visual-slot="plan_uses"'));
  assert.ok(stageFour.includes('data-visual-slot="plan_massing"'));
  assert.ok(!stageFour.includes('data-visual-slot="plan_site"'));
  assert.deepEqual(panelsOf(root).filter(panel => !panel.hidden).map(panel => panel.stage), ['other']);
});

test('the site plan chat can start before a scene exists and offers an explicit start button', () => {
  const context = fixture();
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {}, plansWorkflow: {} });

  assert.equal(context.visualConceptSlotLocked('plan_site'), false);
  assert.equal(context.visualConceptSlotLocked('plan_uses'), true);

  const card = context.renderVisualConceptSitePlanCard();
  assert.match(card, /data-visual-action="start-site-chat"[^>]*>بدء المحادثة/);
  assert.match(card, /<textarea data-visual-chat="plan_site"[^>]*placeholder="رسالة جديدة" disabled>/);
  assert.match(card, /data-visual-action="chat"[^>]*disabled>إرسال/);

  context.tenantVisualConceptState.plansWorkflow.siteAssistant.turns = [
    { role: 'assistant', text: 'ما جهة المدخل الرئيسي؟', choices: ['الغرب', 'الجنوب'] },
  ];
  context.tenantVisualConceptState.slots.plan_site.chat = [
    { role: 'assistant', text: 'ما جهة المدخل الرئيسي؟', choices: ['الغرب', 'الجنوب'] },
  ];
  const activeCard = context.renderVisualConceptSitePlanCard();
  assert.match(activeCard, /<textarea data-visual-chat="plan_site"[^>]*placeholder="رسالة جديدة"\s*>/);
  assert.match(activeCard, /data-visual-action="chat-choice"[^>]*>الغرب/);
  assert.match(activeCard, /data-visual-action="restart-site-plan"[^>]*>البدء من جديد/);
});

test('starting the site plan over clears only the chat memory and keeps analysis, approvals, project facts, and generated plans', async () => {
  const context = fixture(true);
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {
    plan_site: { imageUrl: 'site.svg', approvedImageUrl: 'site.svg', svgCode: '<svg/>', chat: [{ role: 'user', text: 'old turn' }] },
    plan_uses: { imageUrl: 'uses.png', approvedImageUrl: 'uses.png', prompt: 'old prompt' },
    plan_massing: { imageUrl: 'massing.png', prompt: 'old prompt' },
  }, plansWorkflow: {
    verification: { checks: [{ item: 'Old check' }], approved: true },
    boundary: { points: [{ eastings: 10, northings: 20 }], referenceUrl: '/parcel.svg', approved: true },
    distribution: { rows: [{ id: 'old-row', component: 'Old component' }], approved: true },
    clientNotes: 'Old instruction', distributionNotes: 'Old review',
    scene: { version: 1, token: 'old-scene' }, promptReady: true,
    siteAssistant: { turns: [{ role: 'assistant', text: 'old analysis' }],
      answers: [{ question: 'Old question', answer: 'Old answer' }], summary: 'Old summary',
      checkpoints: { components: '<g/>' } },
  } });
  context.tenantProjectData = { land_area: 5000, financial_study_model: { components: [{ name: 'Villa' }] } };
  context.hasPermission = () => true;
  context.confirm = () => true;
  let started = 0;
  let dirty = 0;
  let rendered = 0;
  context.markVisualConceptDirty = () => { dirty += 1; };
  context.renderVisualConceptPage = () => { rendered += 1; };
  context.toast = () => {};
  context.startVisualConceptSiteChat = async () => { started += 1; };

  assert.equal(await context.restartVisualConceptSitePlan(), true);
  const workflow = context.tenantVisualConceptState.plansWorkflow;
  assert.equal(workflow.verification.approved, true);
  assert.deepEqual(plain(workflow.verification.checks), [{ item: 'Old check' }]);
  assert.equal(workflow.boundary.approved, true);
  assert.deepEqual(plain(workflow.boundary.points), [{ parcel_id: '', point: '1', eastings: 10, northings: 20, source: '' }]);
  assert.equal(workflow.distribution.approved, true);
  assert.deepEqual(plain(workflow.distribution.rows), [{ id: 'old-row', building: '', floor_range: '', component: 'Old component', units_per_floor: '', floor_area_sqm: '', circulation: '' }]);
  assert.equal(workflow.clientNotes, 'Old instruction');
  assert.equal(workflow.scene.token, 'old-scene');
  assert.equal(workflow.siteAssistant.turns.length, 0);
  assert.equal(workflow.siteAssistant.answers.length, 0);
  assert.deepEqual(plain(context.tenantVisualConceptState.slots.plan_site.chat), []);
  assert.equal(context.tenantVisualConceptState.slots.plan_site.imageUrl, 'site.svg');
  assert.equal(context.tenantVisualConceptState.slots.plan_site.approvedImageUrl, 'site.svg');
  assert.equal(context.tenantVisualConceptState.slots.plan_site.svgCode, '<svg/>');
  assert.equal(context.tenantVisualConceptState.slots.plan_uses.imageUrl, 'uses.png');
  assert.equal(context.tenantVisualConceptState.slots.plan_massing.imageUrl, 'massing.png');
  assert.deepEqual(plain(context.tenantProjectData), { land_area: 5000, financial_study_model: { components: [{ name: 'Villa' }] } });
  assert.equal(started, 1);
  assert.equal(dirty, 1);
  assert.equal(rendered, 1);
});

test('site plan reset leaves the workflow unchanged when the client cancels', async () => {
  const context = fixture(true);
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {}, plansWorkflow: {
    siteAssistant: { turns: [{ role: 'assistant', text: 'keep this' }] },
  } });
  context.hasPermission = () => true;
  context.confirm = () => false;
  context.markVisualConceptDirty = () => assert.fail('cancel must not save a reset');
  assert.equal(await context.restartVisualConceptSitePlan(), false);
  assert.equal(context.tenantVisualConceptState.plansWorkflow.siteAssistant.turns[0].text, 'keep this');
});

test('site plan reset refuses to run while a plan job is active', async () => {
  const context = fixture(true);
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {
  }, plansWorkflow: {} });
  context.tenantVisualConceptState.slots.plan_site.status = 'generating';
  context.hasPermission = () => true;
  context.confirm = () => assert.fail('an active job must block the reset before confirmation');
  context.toast = () => {};
  assert.equal(await context.restartVisualConceptSitePlan(), false);
  assert.equal(context.tenantVisualConceptState.slots.plan_site.status, 'generating');
});

test('site plan chat input, send action, and choices stay locked while the assistant is processing', () => {
  const context = fixture(true);
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {
    plan_site: { chat: [{ role: 'assistant', text: 'ما جهة المدخل الرئيسي؟', choices: ['الغرب'] }] },
  }, plansWorkflow: { siteAssistant: {
    turns: [{ role: 'assistant', text: 'ما جهة المدخل الرئيسي؟', choices: ['الغرب'] }],
  }, jobTodos: [
    { id: '1', label: 'تجهيز المشهد الهندسي', status: 'active' },
  ] } });
  vm.runInContext('visualConceptSiteAssistantBusy = true', context);

  const card = context.renderVisualConceptSitePlanCard();
  assert.match(card, /data-visual-chat="plan_site"[^>]*disabled/);
  assert.match(card, /data-visual-action="chat"[^>]*disabled>إرسال/);
  assert.match(card, /data-visual-action="chat-choice"[^>]*disabled>الغرب/);
  assert.match(card, /data-visual-action="restart-site-plan"[^>]*disabled/);
  assert.match(card, /المرحلة الحالية: تجهيز المشهد الهندسي/);
});

test('starting the site plan chat submits analysis without a message from the client', async () => {
  const context = fixture(true);
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {}, plansWorkflow: {} });
  context.hasPermission = () => true;
  context.visualConceptSlotLocked = () => false;
  context.visualConceptPlanInputStamp = () => 'same-input';
  context.collectVisualConceptPlansWorkflowPayload = async () => ({
    projectData: {}, plansWorkflow: {},
  });
  context.markVisualConceptDirty = () => {};
  context.renderVisualConceptPage = () => {};
  context.applyVisualConceptSiteAssistantResponse = () => {};
  let request;
  context.visualConceptPlanJobApi = async (method, path, payload) => {
    request = { method, path, payload };
    assert.equal(vm.runInContext('visualConceptSiteAssistantBusy', context), true);
    return { success: true, assistantState: { turns: [] } };
  };

  await context.startVisualConceptSiteChat();

  assert.equal(request.method, 'POST');
  assert.equal(request.path, '/api/visual-concept/site-plan-assistant');
  assert.equal(request.payload.planAssistantAction, 'chat');
  assert.equal(Object.hasOwn(request.payload, 'message'), false);
  assert.deepEqual(JSON.parse(JSON.stringify(
    context.tenantVisualConceptState.plansWorkflow.jobTodos.map(item => item.label))), [
    'فحص بيانات الأرض والتوزيع', 'تجهيز المشهد الهندسي',
    'مراجعة الإجابات السابقة', 'تحليل المتطلبات وتحديد السؤال',
  ]);
  assert.equal(vm.runInContext('visualConceptSiteAssistantBusy', context), false);
});

test('site plan status follows the active backend progress step', () => {
  const context = fixture();
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {}, plansWorkflow: {} });
  const status = { textContent: '' };
  const todoPanel = { innerHTML: '' };
  context.document.querySelector = selector => selector === '[data-site-chat-status]'
    ? status : selector === '[data-plans-workflow-todos]' ? todoPanel : null;
  context.document.getElementById = () => null;

  context.updateVisualConceptPlanJobUi({ status: 'running', progress: 82, todos: [
    { id: '1', label: 'فحص بيانات الأرض والتوزيع', status: 'done' },
    { id: '2', label: 'تجهيز المشهد الهندسي', status: 'done' },
    { id: '3', label: 'مراجعة الإجابات السابقة', status: 'done' },
    { id: '4', label: 'تحليل المتطلبات وتحديد السؤال', status: 'active' },
  ] });

  assert.equal(status.textContent, 'المرحلة الحالية: تحليل المتطلبات وتحديد السؤال');
});

test('a rebased site scene clears its approval and returns dependent plans to review', () => {
  const context = fixture(true);
  const oldScene = { version: 1, token: 'old-scene' };
  context.tenantVisualConceptState = context.normalizeVisualConceptState({
    slots: {
      plan_site: { imageUrl: '/site.png', approvedImageUrl: '/site.png', status: 'approved' },
      plan_uses: { imageUrl: '/uses.png', approvedImageUrl: '/uses.png', status: 'approved',
        sceneToken: 'old-scene' },
    },
    plansWorkflow: { scene: oldScene, siteAssistant: { turns: [] } },
  });
  context.visualConceptPlanInputStamp = () => 'current-input';
  context.markVisualConceptDirty = () => {};

  context.applyVisualConceptSiteAssistantResponse({
    contextChanged: true,
    scene: { version: 1, token: 'new-scene' },
    assistantState: { turns: [{ role: 'assistant', text: 'What is the main entry?' }] },
  });

  assert.equal(context.tenantVisualConceptState.plansWorkflow.scene.token, 'new-scene');
  assert.equal(context.tenantVisualConceptState.slots.plan_site.approvedImageUrl, '');
  assert.equal(context.tenantVisualConceptState.slots.plan_uses.approvedImageUrl, '');
  assert.equal(context.tenantVisualConceptState.slots.plan_uses.imageUrl, '/uses.png');
  assert.equal(context.tenantVisualConceptState.slots.plan_uses.status, 'review');
});

test('stage three ignores a second chat send while its current request is active', async () => {
  const context = fixture(true);
  let apiCalls = 0;
  context.api = async () => { apiCalls += 1; return { success: true }; };
  vm.runInContext('visualConceptSiteAssistantBusy = true', context);

  await context.sendVisualConceptChat('plan_site');
  assert.equal(apiCalls, 0);
});
