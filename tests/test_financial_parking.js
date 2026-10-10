'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..');
const files = ['09-financial/01_financial_format.js', '09-financial/02_formulas_calc.js',
  '09-financial/03_parking_planning.js', '10-financial-report-timeline/01_report_collect.js'];
const source = files.map(file => fs.readFileSync(path.join(root, 'assets/js', file), 'utf8')).join('\n');
const plain = value => JSON.parse(JSON.stringify(value));
const classes = () => ({ contains: () => false, add() {}, toggle() {} });
const field = (value = '', type = 'text') => ({ value: String(value), type, tagName: 'INPUT',
  dataset: {}, classList: classes(), style: {}, addEventListener() {}, closest: () => null });

function fixture() {
  const rows = [];
  const inputs = { landArea: field(5000, 'number'), coverageRate: field(60, 'number'),
    floorCount: field('', 'number'), builtUpAreaAbove: field(16500, 'number'),
    basementArea: field(600, 'number'), openArea: field(2000, 'number') };
  const context = vm.createContext({
    console, Intl, setTimeout, clearTimeout, window: {},
    tenantProjectData: { draftId: 'draft-1', approved_financial_area: 5000,
      approved_coverage_ratio: 60, croquis_land_area: 5000,
      regulatory_constraints: 'موقف لكل وحدة',
      financial_study_model: { inputs: { landArea: 5000, coverageRate: 60,
        builtUpAreaAbove: 16500, basementArea: 600 }, dynamicRows: { components: [] } } },
    tenantProjectSectionStatuses: {}, tenantDraftRevision: 1, tenantProjectMode: 'draft',
    tenantPresentationId: null, dirty: false, toasts: [], requests: [],
    document: {
      addEventListener() {},
      getElementById: id => id === 'componentsTable' ? table : inputs[id] || null,
      querySelector: selector => {
        if (selector === '#componentsTable tbody') return body;
        if (selector === '#componentsTable') return table;
        const key = selector.match(/^#tenantProjectForm \[data-key="([^"]+)"\]$/)?.[1];
        if (key && key in context.tenantProjectData) return { value: context.tenantProjectData[key] };
        return null;
      },
      querySelectorAll: selector => selector === '#componentsTable tbody tr' ? rows : [],
      createElement: () => ({ dataset: {}, innerHTML: '', querySelectorAll: () => [] })
    },
    escapeHtml: value => String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch])),
    refreshDynamicI18n() {}, wfTr: text => text,
    WFT: (key, fallback, params = {}) => fallback.replace(/\{([^}]+)\}/g, (match, name) => params[name] ?? match),
    toast: text => context.toasts.push(text),
    saveProjectAsDraft: async () => true,
    triggerAutoSaveDraft: () => { context.dirty = true; },
    applySectionStatuses: updates => Object.assign(context.tenantProjectSectionStatuses, updates)
  });
  const table = { closest: () => ({ classList: classes() }) };
  const body = { appendChild: row => rows.push(row) };
  vm.runInContext(source, context);
  context.calculateAll = () => {};
  context.addComponent = component => add(component);
  function add(component) {
    const controls = Object.fromEntries(Object.entries(component).map(([key, value]) => [key, field(value,
      ['units', 'unitArea', 'builtArea', 'revenueArea'].includes(key) ? 'number' : 'text')]));
    const row = { dataset: { componentKey: component.id, parkingPlanId: component.parkingPlanId || '',
      floorRange: component.floorRange || '' },
      querySelector: selector => controls[selector.match(/data-field="([^"]+)"/)?.[1]] || null,
      querySelectorAll: () => [], remove: () => { rows.splice(rows.indexOf(row), 1); } };
    rows.push(row);
    return row;
  }
  add({ id: 'housing', name: 'شقق سكنية', useType: 'residential', units: 100, unitArea: 150,
    builtArea: 15000, revenueArea: 13000, investmentModel: 'sale' });
  add({ id: 'retail', name: 'محلات تجارية', useType: 'retail', units: 10, unitArea: 150,
    builtArea: 1500, revenueArea: 1200, investmentModel: 'annualRent' });
  const snapshot = () => plain(context.financialParkingSnapshot());
  const proposal = (approved = false) => ({ id: 'plan-1', approved, canApply: true,
    sourceSnapshot: snapshot(), requiredSpaces: 130, existingSpaces: 0, additionalSpaces: 130,
    baseBasementArea: 600, basementAreaTarget: 3900, parkingArea: 3900, areaPerSpace: 30,
    requirements: [], warnings: [], missing: [], components: [{ id: 'parking-1',
      name: 'مواقف السيارات — البدروم', useType: 'parking', parkingLocation: 'basement',
      units: 130, unitArea: 30, builtArea: 3900, revenueArea: 0, investmentModel: 'nonRevenue',
      parkingPlanId: 'plan-1', floorRange: 'بدروم 1-2' }] });
  return { context, rows, inputs, add, snapshot, proposal };
}

async function until(predicate) {
  for (let index = 0; index < 100; index++) { if (predicate()) return; await Promise.resolve(); }
  assert(predicate());
}

test('the proposal snapshot preserves nullable fields and Arabic numeric inputs', () => {
  const f = fixture();
  f.inputs.builtUpAreaAbove.value = '١٦٬٥٠٠';
  const data = f.snapshot();
  assert.equal(data.builtUpAreaAbove, 16500);
  assert.equal(data.floorCount, null);
  assert.equal(data.components[0].units, 100);
  assert.equal(data.components[0].parkingLocation, '');
  assert.equal(f.context.financialParkingNumber(true), null);
  assert.equal(f.context.financialParkingNumber('NaN'), null);
});

test('parking locations settle against their own area budgets', () => {
  const f = fixture();
  f.add({ id: 'surface', name: 'مواقف سطحية', useType: 'parking', parkingLocation: 'surface',
    units: 10, unitArea: 30, builtArea: 300, revenueArea: 0, investmentModel: 'nonRevenue' });
  f.add({ id: 'basement', name: 'مواقف بدروم', useType: 'parking', parkingLocation: 'basement',
    units: 20, unitArea: 30, builtArea: 600, revenueArea: 0, investmentModel: 'nonRevenue' });
  const result = plain(f.context.validateComponentAreas());
  assert.equal(result.used, 16500);
  assert.equal(result.openUsed, 300);
  assert.equal(result.basementUsed, 600);
  assert.equal(result.valid, true);
  f.inputs.basementArea.value = '500';
  assert.equal(f.context.validateComponentAreas().basementExceeded, true);
});

test('collection keeps proposal ownership, parking location and floor allocation', () => {
  const f = fixture();
  const plan = f.proposal(true);
  f.context.tenantProjectData.financial_study_model.parkingPlan = plan;
  f.add(plan.components[0]);
  f.inputs.basementArea.value = '3900';
  const rows = plain(f.context.getComponentRowsData());
  assert.equal(rows.at(-1).parkingPlanId, 'plan-1');
  assert.equal(rows.at(-1).parkingLocation, 'basement');
  assert.equal(rows.at(-1).floorRange, 'بدروم 1-2');
  assert.equal(f.context.financialParkingError(), '');
  assert.equal(f.snapshot().basementArea, 600);
  const model = plain(f.context.collectFinancialStudyModel());
  assert.equal(model.parkingPlan.id, 'plan-1');
  assert.equal(model.dynamicRows.components.at(-1).units, 130);
});

test('editing the program or a generated parking row invalidates the approval', () => {
  const f = fixture();
  const plan = f.proposal(true);
  f.context.tenantProjectData.financial_study_model.parkingPlan = plan;
  f.add(plan.components[0]);
  f.inputs.basementArea.value = '3900';
  assert.equal(f.context.financialParkingError(), '');
  f.rows[0].querySelector('[data-field="units"] input').value = '120';
  assert.match(f.context.financialParkingError(), /تغيّرت/);
  f.rows[0].querySelector('[data-field="units"] input').value = '100';
  f.rows.at(-1).querySelector('[data-field="units"] input').value = '129';
  assert.match(f.context.financialParkingError(), /لا تطابق/);
});

test('a failed pre-save cannot start a billable proposal request', async () => {
  const f = fixture();
  f.context.saveProjectAsDraft = async () => false;
  f.context.api = async () => { throw new Error('The provider must not be called'); };
  assert.equal(await f.context.suggestFinancialParking(), false);
});

test('double clicks share a single saved proposal request', async () => {
  const f = fixture();
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  f.context.api = async (method, url, body) => {
    f.context.requests.push({ method, url, body: plain(body) });
    return pending;
  };
  const first = f.context.suggestFinancialParking();
  const second = f.context.suggestFinancialParking();
  assert.equal(first, second);
  await until(() => f.context.requests.length === 1);
  const plan = f.proposal();
  release({ success: true, draftId: 'draft-1', revision: 2,
    financialModel: { inputs: { basementArea: 600 }, dynamicRows: { components: [] }, parkingPlan: plan } });
  assert.equal(await first, true);
  assert.equal(f.context.requests.length, 1);
  assert.equal(f.rows.length, 2);
  assert.equal(f.context.tenantDraftRevision, 2);
  assert.equal(f.context.tenantProjectData.financial_study_model.parkingPlan.approved, false);
});

test('approval applies only parking rows and the proposed basement area', () => {
  const f = fixture();
  const plan = f.proposal(true);
  const snapshot = f.context.financialParkingStable(f.snapshot());
  const response = { success: true, draftId: 'draft-1', revision: 2,
    financialModel: { inputs: { basementArea: 3900 }, dynamicRows: { components: plan.components }, parkingPlan: plan } };
  assert.equal(f.context.financialParkingReceive(response, snapshot, 'draft-1'), true);
  assert.equal(f.rows.length, 3);
  assert.equal(f.inputs.basementArea.value, '3900');
  assert.equal(f.context.financialParkingError(), '');
  assert.equal(f.context.financialParkingReceive(response, snapshot, 'draft-1'), true);
  assert.equal(f.rows.length, 3);
});

test('a late response does not replace newer manual edits or another open draft', () => {
  const f = fixture();
  const plan = f.proposal(true);
  const snapshot = f.context.financialParkingStable(f.snapshot());
  const response = { success: true, draftId: 'draft-1', revision: 2,
    financialModel: { inputs: { basementArea: 3900 }, dynamicRows: { components: plan.components }, parkingPlan: plan } };
  f.inputs.basementArea.value = '900';
  assert.equal(f.context.financialParkingReceive(response, snapshot, 'draft-1'), false);
  assert.equal(f.inputs.basementArea.value, '900');
  assert.equal(f.rows.length, 2);
  f.context.tenantProjectData.draftId = 'draft-2';
  f.context.tenantDraftRevision = 3;
  assert.equal(f.context.financialParkingReceive(response, snapshot, 'draft-1'), false);
  assert.equal(f.context.tenantDraftRevision, 3);
});

test('switching projects during the pre-save cannot target the newly opened draft', async () => {
  const f = fixture();
  let release;
  f.context.saveProjectAsDraft = () => new Promise(resolve => { release = resolve; });
  f.context.api = async () => { f.context.requests.push('unexpected'); return { success: false }; };
  const running = f.context.suggestFinancialParking();
  f.context.tenantProjectData = { ...f.context.tenantProjectData, draftId: 'draft-2' };
  release(true);
  assert.equal(await running, false);
  assert.equal(f.context.requests.length, 0);
});

test('rendered proposal data cannot inject markup', () => {
  const f = fixture();
  const plan = f.proposal();
  plan.requirements = [{ name: '<img src=x>', sourceQuote: '<script>bad()</script>', spaces: 130 }];
  f.context.tenantProjectData.financial_study_model.parkingPlan = plan;
  const output = { innerHTML: '' };
  const query = f.context.document.querySelector;
  const byId = f.context.document.getElementById;
  f.context.document.querySelector = selector => selector === '#parkingRequirementsTable tbody' ? output : query(selector);
  f.context.document.getElementById = id => id === 'financialParkingPanel' ? {} : byId(id);
  f.context.renderFinancialParking();
  assert(!output.innerHTML.includes('<script>'));
  assert(!output.innerHTML.includes('<img'));
  assert(output.innerHTML.includes('&lt;script&gt;'));
});
