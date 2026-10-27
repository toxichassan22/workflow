'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const source = fs.readFileSync(
  path.join(root, 'assets/js/08-location-maps/03_land_metrics.js'), 'utf8');

function fixture(values) {
  const inputs = {};
  for (const [key, value] of Object.entries(values)) {
    inputs[key] = { value: String(value), dataset: { key } };
  }
  const cells = {
    computedTotalBuiltArea: { textContent: '—' },
    computedCoverageArea: { textContent: '—' },
    computedRepeatedFloorsArea: { textContent: '—' },
    computedTypicalFloorArea: { textContent: '—' }
  };
  const box = { hidden: true, violated: false, classList: { toggle(name, on) { box.violated = on; } } };
  const note = { textContent: '', hidden: true };
  const created = [];
  const context = vm.createContext({
    console,
    tenantProjectData: {},
    parseNumber: value => {
      const number = Number(String(value ?? '').replace(/[٬،,]/g, '').replace(/\s/g, ''));
      return Number.isFinite(number) ? number : 0;
    },
    WFT: (key, fallback, params = {}) =>
      fallback.replace(/\{(\w+)\}/g, (match, name) => (name in params ? params[name] : match)),
    document: {
      createElement: () => {
        const node = { className: '', innerHTML: '' };
        created.push(node);
        return node;
      },
      getElementById: id => {
        if (id === 'landComputedMetrics') return box;
        if (id === 'landComputedCapNote') return note;
        return cells[id] || null;
      },
      querySelector: selector => {
        const key = selector.match(/\[data-key="([^"]+)"\]/)?.[1];
        return (key && inputs[key]) || null;
      }
    }
  });
  vm.runInContext(source, context);
  return { context, inputs, cells, box, note, created };
}

function values(overrides = {}) {
  // The owner's live project: 24,912.95 m² land, FAR 2.4, 48% footprint,
  // 65 approved floors.
  return {
    approved_financial_area: 24912.95,
    approved_floor_area_ratio: 2.4,
    approved_coverage_ratio: 48,
    approved_typical_floor_coverage: 10,
    approved_floor_count: 65,
    ...overrides
  };
}

test('the typical-floor coverage drives the repeated-floors and floor figures', () => {
  const f = fixture(values());
  f.context.updateLandComputedMetrics();
  // 24,912.95 × 10% = 2,491.295 per floor; 64 repeated floors above ground.
  assert.equal(f.cells.computedTypicalFloorArea.textContent, '2,491.3');
  assert.equal(f.cells.computedRepeatedFloorsArea.textContent, '159,442.9');
  assert.equal(f.cells.computedTotalBuiltArea.textContent, '59,791.1');
  assert.equal(f.cells.computedCoverageArea.textContent, '11,958.2');
  // The old subtraction figure (total − footprint) is gone.
  assert.notEqual(f.cells.computedRepeatedFloorsArea.textContent, '47,832.9');
});

test('editing the coverage updates the panel and the warning carries the numbers', () => {
  const f = fixture(values({ approved_typical_floor_coverage: 2 }));
  f.context.updateLandComputedMetrics();
  assert.equal(f.cells.computedTypicalFloorArea.textContent, '498.3');
  assert.equal(f.cells.computedRepeatedFloorsArea.textContent, '31,888.6');
  assert.equal(f.note.hidden, true);
  assert.equal(f.note.textContent, '');
  assert.equal(f.box.violated, false);

  f.inputs.approved_typical_floor_coverage.value = '10';
  f.context.updateLandComputedMetrics();
  assert.equal(f.cells.computedRepeatedFloorsArea.textContent, '159,442.9');
  assert.equal(f.box.violated, true);
  assert.equal(f.note.hidden, false);
  // The numbers behind the refusal are stated, not just the refusal.
  assert.match(f.note.textContent, /159,442\.9/);
  assert.match(f.note.textContent, /11,958\.2/);
  assert.match(f.note.textContent, /59,791\.1/);
  assert.match(f.note.textContent, /111,610/);
});

test('the approved floor count is used, not the old hardcoded 18', () => {
  const f = fixture(values({ approved_typical_floor_coverage: 10 }));
  f.context.updateLandComputedMetrics();
  const sixtyFiveFloors = f.cells.computedRepeatedFloorsArea.textContent;
  f.inputs.approved_floor_count.value = '19';
  f.context.updateLandComputedMetrics();
  assert.equal(f.cells.computedRepeatedFloorsArea.textContent, '44,843.3');
  assert.notEqual(f.cells.computedRepeatedFloorsArea.textContent, sixtyFiveFloors);
});

test('a single floor has no repeated floors and never trips the gate', () => {
  const f = fixture(values({ approved_floor_count: 1, approved_typical_floor_coverage: 100 }));
  f.context.updateLandComputedMetrics();
  assert.equal(f.cells.computedRepeatedFloorsArea.textContent, '—');
  assert.equal(f.note.hidden, true);
  assert.equal(f.box.violated, false);
});

test('missing inputs stay empty instead of inventing numbers', () => {
  const f = fixture({ approved_financial_area: 24912.95, approved_floor_area_ratio: '', approved_coverage_ratio: '', approved_typical_floor_coverage: '', approved_floor_count: '' });
  f.context.updateLandComputedMetrics();
  for (const id of Object.keys(f.cells)) {
    assert.equal(f.cells[id].textContent, '—');
  }
  assert.equal(f.note.hidden, true);
});

test('validation refuses approval with the same numbers the panel shows', () => {
  const f = fixture(values());
  const errors = f.context.validateLandCroquisClientFields();
  assert.equal(errors.length, 1);
  assert.equal(errors[0].key, 'approved_typical_floor_coverage');
  assert.match(errors[0].message, /159,442\.9/);

  f.inputs.approved_typical_floor_coverage.value = '2';
  assert.equal(f.context.validateLandCroquisClientFields().length, 0);

  f.inputs.approved_floor_count.value = '';
  const missing = f.context.validateLandCroquisClientFields();
  assert.equal(missing.length, 1);
  assert.equal(missing[0].key, 'approved_floor_count');
});

test('mounting the panel wires live recompute to the approved inputs', () => {
  const f = fixture(values({ approved_typical_floor_coverage: 2 }));
  const section = {
    listeners: [],
    children: [],
    appendChild(node) { this.children.push(node); },
    addEventListener(type, handler) { this.listeners.push([type, handler]); }
  };
  f.context.mountLandComputedMetrics(section);
  assert.equal(section.children.length, 1);
  const markup = section.children[0].innerHTML;
  for (const id of ['computedTotalBuiltArea', 'computedCoverageArea',
                    'computedRepeatedFloorsArea', 'computedTypicalFloorArea',
                    'landComputedCapNote']) {
    assert.ok(markup.includes('id="' + id + '"'), id + ' missing from the mounted panel');
  }
  assert.equal(section.listeners.length, 2);
  assert.equal(f.cells.computedRepeatedFloorsArea.textContent, '31,888.6');

  f.inputs.approved_typical_floor_coverage.value = '10';
  for (const [, handler] of section.listeners) {
    handler({ target: { dataset: { key: 'approved_typical_floor_coverage' } } });
  }
  assert.equal(f.cells.computedRepeatedFloorsArea.textContent, '159,442.9');
});
