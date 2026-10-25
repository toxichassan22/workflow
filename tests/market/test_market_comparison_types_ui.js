'use strict';

// Market comparison types: a blank row must not consume one of the three
// type slots, and residential/commercial carry both sale and rent.
// Run: node --test tests/market/test_market_comparison_types_ui.js

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const files = [
  'assets/js/04a-market-section.js',
];
const source = files.map(file =>
  fs.readFileSync(path.join(root, file), 'utf8')).join('\n');

function context() {
  const sandbox = vm.createContext({
    console, Intl, URL, JSON, Date, Set, Map, Array, String, Number, Math,
    window: { location: { origin: 'http://localhost:5515' } },
    document: {
      addEventListener() {},
      getElementById: () => null,
      querySelector: () => null,
      querySelectorAll: () => [],
    },
    WFT: (key, fallback = key) => fallback,
    wfTr: text => text,
    escapeHtml: text => String(text ?? ''),
    refreshDynamicI18n() {},
    toast() {},
  });
  vm.runInContext(source, sandbox);
  return sandbox;
}

test('a blank row does not count as a type slot', () => {
  const ctx = context();
  const guard = ctx.marketComparisonAddGuard([
    { type: 'hotel' }, { type: 'residential' }, { type: '' },
  ]);
  assert.equal(guard.filled, 2);
  assert.equal(guard.hasBlank, true);
});

test('three filled types block adding a fourth', () => {
  const ctx = context();
  const guard = ctx.marketComparisonAddGuard([
    { type: 'hotel' }, { type: 'residential' }, { type: 'commercial' },
  ]);
  assert.equal(guard.filled, 3);
  assert.equal(guard.hasBlank, false);
});

test('residential sale and rent stay on one row with both operations', () => {
  const ctx = context();
  const rows = ctx.normalizeMarketComparisonRows([
    { type: 'residential', operation: ['sale'] },
    { type: 'residential', operation: ['rent'] },
  ]);
  assert.equal(rows.length, 1);
  assert.deepEqual([...rows[0].operation].sort(), ['rent', 'sale']);
});

test('residential and commercial both accept sale and rent', () => {
  const ctx = context();
  const rows = ctx.normalizeMarketComparisonRows([
    { type: 'residential', operation: ['sale', 'rent'] },
    { type: 'commercial', operation: ['sale', 'rent'] },
  ]);
  assert.equal(rows.length, 2);
  assert.deepEqual([...rows[0].operation].sort(), ['rent', 'sale']);
  assert.deepEqual([...rows[1].operation].sort(), ['rent', 'sale']);
});
