'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const source = ['11-land-croquis/01_croquis_survey.js', '11-land-croquis/01a_boundary_dimensions.js']
  .map(file => fs.readFileSync(path.join(root, 'assets/js', file), 'utf8')).join('\n');
const plain = value => JSON.parse(JSON.stringify(value));

function fixture() {
  const context = vm.createContext({
    console, Intl, setTimeout, clearTimeout, window: {},
    document: { addEventListener() {}, getElementById: () => null, querySelector: () => null,
      querySelectorAll: () => [] },
    tenantProjectData: {},
    parseStoredLandTable: value => {
      if (Array.isArray(value) || (value && typeof value === 'object')) return value;
      if (typeof value !== 'string' || !value.trim()) return null;
      try { const parsed = JSON.parse(value); return (parsed && typeof parsed === 'object') ? parsed : null; }
      catch (e) { return null; }
    },
    escapeHtml: value => String(value),
    WFT: (key, fallback, params = {}) => fallback.replace(/\{([^}]+)\}/g,
      (match, name) => params[name] ?? match),
  });
  vm.runInContext(source, context);
  return context;
}

const dimensionProject = () => ({
  directions_table: [
    { direction: 'north', regulation_text: 'شارع رئيسي عرض 30م', boundary_length_m: 97, setback: '5م' },
    { direction: 'south', regulation_text: 'بطول 97م يحده جار', setback: '5م' },
    { direction: 'east', boundary_length_m: '250', setback: '5م' },
    { direction: 'west', boundary_length_m: 250, setback: '5م' },
  ],
});

test('direction rows keep their boundary lengths through normalization', () => {
  const context = fixture();
  const rows = plain(context.normalizeSurveyDirections(dimensionProject().directions_table));
  const byDirection = Object.fromEntries(rows.map(row => [row.direction, row.boundary_length_m]));
  assert.deepEqual(byDirection, { north: 97, south: 97, east: 250, west: 250 });
});

test('the 97x250 croquis becomes a marked approximate rectangle', () => {
  const context = fixture();
  const points = plain(context.surveyBoundaryPointsFromDimensions(dimensionProject()));
  assert.equal(points.length, 4);
  assert.equal(Math.max(...points.map(p => p.eastings)) - 1000, 97);
  assert.equal(Math.max(...points.map(p => p.northings)) - 1000, 250);
  assert.ok(points.every(p => p.source === 'boundary_lengths'));
});

test('each direction keeps the figure that follows it in one clause', () => {
  const context = fixture();
  const lengths = plain(context.surveyBoundaryLengthsByDirection({
    boundary_lengths: 'الشمالي 97م والجنوبي 98م والشرقي 250م والغربي 251م',
  }));
  assert.equal(lengths.north, 97);
  assert.equal(lengths.south, 98);
  assert.equal(lengths.east, 250);
  assert.equal(lengths.west, 251);
});

test('facade/side phrasing builds the rectangle without compass words', () => {
  const context = fixture();
  const points = plain(context.surveyBoundaryPointsFromDimensions({
    boundary_lengths: 'الواجهة الأمامية بطول 97م والخلفية بطول 97م والجانبين بطول 250م',
  }));
  assert.equal(points.length, 4);
  assert.equal(Math.max(...points.map(p => p.eastings)) - 1000, 97);
  assert.equal(Math.max(...points.map(p => p.northings)) - 1000, 250);
});

test('partial dimensions never fabricate a boundary', () => {
  const context = fixture();
  assert.deepEqual(plain(context.surveyBoundaryPointsFromDimensions({
    directions_table: [{ direction: 'شمال', boundary_length_m: 97 }],
  })), []);
  assert.deepEqual(plain(context.surveyBoundaryPointsFromDimensions({})), []);
});

test('street width figures next to a بطول phrase are not taken as lengths', () => {
  const context = fixture();
  const lengths = plain(context.surveyBoundaryLengthsByDirection({
    boundary_lengths: 'الشمالي يحده شارع عرض 30م بطول 97م، الجنوبي بطول 97م، الشرقي 250م، الغربي 250م',
  }));
  assert.equal(lengths.north, 97);
});
