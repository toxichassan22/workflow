'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const dir = path.resolve(__dirname, '../assets/js/12-files-media');
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
