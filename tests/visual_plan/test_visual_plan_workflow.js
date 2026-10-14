'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const dir = path.resolve(__dirname, '../../assets/js/12-files-media');
const source = fs.readdirSync(dir).filter(file => /^02.*\.js$/.test(file)).sort()
  .map(file => fs.readFileSync(path.join(dir, file), 'utf8')).join('\n');
const plain = value => JSON.parse(JSON.stringify(value));

function fixture() {
  const context = vm.createContext({
    console, Intl, setTimeout, clearTimeout, window: {},
    document: { addEventListener() {}, getElementById: () => null, querySelector: () => null,
      querySelectorAll: () => [] },
    tenantProjectData: {}, tenantCreativeImages: {}, tenantVisualConceptState: null,
    durableImageUrl: value => String(value || ''),
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
  return context;
}

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

test('the parcel preview uses one uniform scale for both surveyed axes', () => {
  const context = fixture();
  const host = { innerHTML: '' };
  context.renderVisualConceptBoundarySvg(host, [
    { point: '1', eastings: 500000, northings: 2000000 },
    { point: '2', eastings: 500020, northings: 2000000 },
    { point: '3', eastings: 500020, northings: 2000020 },
    { point: '4', eastings: 500000, northings: 2000020 },
  ]);
  const points = host.innerHTML.match(/<polygon points="([^"]+)"/)[1]
    .split(' ').map(point => point.split(',').map(Number));
  assert.equal(Math.abs(points[1][0] - points[0][0]), Math.abs(points[2][1] - points[1][1]));
});

test('the preview merges per-point parcel ids into one drawn boundary', () => {
  const context = fixture();
  const host = { innerHTML: '' };
  context.renderVisualConceptBoundarySvg(host, [
    { point: '1', parcel_id: 'P-1', eastings: 500000, northings: 2000000 },
    { point: '2', parcel_id: 'P-2', eastings: 500020, northings: 2000000 },
    { point: '3', parcel_id: 'P-3', eastings: 500020, northings: 2000020 },
    { point: '4', parcel_id: 'P-4', eastings: 500000, northings: 2000020 },
  ]);
  const parcel = host.innerHTML.match(/<polygon points="([^"]+)"/);
  assert.ok(parcel);
  assert.equal(parcel[1].split(' ').length, 4);
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
  assert.ok(!html.includes('ITEM_MATCHED'));
  assert.ok(!html.includes('DETAIL_MATCHED'));
  const button = html.match(/data-plans-workflow-action="approve-distribution"([^>]*)>/);
  assert.ok(button);
  assert.ok(!button[1].includes('disabled'));
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
