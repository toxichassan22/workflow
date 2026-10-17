'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const dir = path.resolve(__dirname, '../../assets/js/12-files-media');
const source = fs.readdirSync(dir).filter(file => /^02.*\.js$/.test(file)).sort()
  .map(file => fs.readFileSync(path.join(dir, file), 'utf8')).join('\n');
const visualPageSource = fs.readFileSync(path.resolve(__dirname,
  '../../assets/js/13-visual/01_visual_concept_page.js'), 'utf8');
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
    }) };
  context.markVisualConceptDirty = () => {};
  context.setVisualConceptPlanNotes('new note');
  const workflow = plain(context.tenantVisualConceptState.plansWorkflow);
  assert.equal(workflow.clientNotes, 'new note');
  assert.equal(workflow.notesReview.verified, false);
  assert.equal(workflow.promptReady, false);
  assert.equal(workflow.scene, null);
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
  assert.equal(reloaded.canProceed, false);
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

test('a changed parking plan invalidates the saved conflict review and approvals', () => {
  const context = fixture();
  const before = { financial_study_model: { inputs: { basementArea: 800 },
    dynamicRows: { components: [{ id: 'parking_row', parkingPlanId: 'parking_1', units: 20 }] },
    parkingPlan: { id: 'parking_1', approved: true, requiredSpaces: 20 } } };
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {},
    plansWorkflow: { verification: { approved: true, canProceed: false, checks: [{ item: 'الارتداد', result: 'متعارض' }] },
      boundary: { approved: true }, distribution: { approved: true, aiReviewed: true },
      notesReview: { verified: true, canProceed: true } } });
  context.tenantVisualConceptState.plansWorkflow.sourceStamp = context.visualConceptPlanInputStamp(before);

  context.syncVisualConceptPlanInputs({ financial_study_model: { ...before.financial_study_model,
    parkingPlan: { ...before.financial_study_model.parkingPlan, requiredSpaces: 24 } } });

  const workflow = context.tenantVisualConceptState.plansWorkflow;
  assert.equal(workflow.verification.approved, false);
  assert.equal(workflow.verification.checks.length, 0);
  assert.equal(workflow.boundary.approved, true);
  assert.equal(workflow.distribution.approved, false);
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
});

test('site plan chat input, send action, and choices stay locked while the assistant is processing', () => {
  const context = fixture(true);
  context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {
    plan_site: { chat: [{ role: 'assistant', text: 'ما جهة المدخل الرئيسي؟', choices: ['الغرب'] }] },
  }, plansWorkflow: { siteAssistant: {
    turns: [{ role: 'assistant', text: 'ما جهة المدخل الرئيسي؟', choices: ['الغرب'] }],
  } } });
  vm.runInContext('visualConceptSiteAssistantBusy = true', context);

  const card = context.renderVisualConceptSitePlanCard();
  assert.match(card, /data-visual-chat="plan_site"[^>]*disabled/);
  assert.match(card, /data-visual-action="chat"[^>]*disabled>إرسال/);
  assert.match(card, /data-visual-action="chat-choice"[^>]*disabled>الغرب/);
  assert.match(card, /جاري مراجعة بيانات المخطط/);
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
  assert.equal(vm.runInContext('visualConceptSiteAssistantBusy', context), false);
});

test('stage three ignores a second chat send while its current request is active', async () => {
  const context = fixture(true);
  let apiCalls = 0;
  context.api = async () => { apiCalls += 1; return { success: true }; };
  vm.runInContext('visualConceptSiteAssistantBusy = true', context);

  await context.sendVisualConceptChat('plan_site');
  assert.equal(apiCalls, 0);
});

test('visual plan job polling allows the requested two-hour generation window', () => {
  const actions = fs.readFileSync(path.join(dir, '02d_visual_concept_plan_actions.js'), 'utf8');
  assert.match(actions, /Date\.now\(\) \+ 7200000/);
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
    '../../assets/js/10-financial-report-timeline/02_timeline_sidebar.js'), 'utf8');
  assert.match(timeline, /tenantCreativeImages\.main_facade_prompt/);
  assert.match(timeline, /item\.id === 'main_facade' \? tenantCreativeImages\.main_facade/);
});

test('site plan chat choices, surgical SVG source, and saved checkpoints are connected to the new assistant route', () => {
  const page = fs.readFileSync(path.resolve(__dirname,
    '../../assets/js/13-visual/01_visual_concept_page.js'), 'utf8');
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
    '../../assets/css/base/08_shell_chrome.css'), 'utf8');
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
