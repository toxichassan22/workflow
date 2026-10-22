'use strict';

// ROI must be one formula everywhere: the indicator card and the sensitivity
// base row both come from computeProjectRoi, and the in-kind land value is part
// of the investment base even though it never appears in projectOutflow.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const read = file => fs.readFileSync(path.join(root, 'assets/js', file), 'utf8');
const calcSource = read('09-financial/02_formulas_calc.js');
const reportSource = read('10-financial-report-timeline/01_report_collect.js');

function browserContext() {
  const context = vm.createContext({
    console, Intl, setTimeout, clearTimeout, window: {}, document: {
      addEventListener() {}, getElementById: () => null, querySelector: () => null,
      querySelectorAll: () => [], createElement: () => ({ dataset: {}, innerHTML: '', querySelectorAll: () => [] })
    },
    escapeHtml: value => String(value),
    refreshDynamicI18n() {}, wfTr: text => text, toast: () => {},
    WFT: (key, fallback, params = {}) => fallback
  });
  vm.runInContext([calcSource, reportSource].join('\n'), context);
  return context;
}

const rows = [
  { saleRevenue: 100, operatingRevenue: 0, terminal: 0, projectOutflow: 20, opex: 5, landRent: 1, financeFee: 2, financeInterest: 1, fundFeesAnnual: 1 },
  { saleRevenue: 0, operatingRevenue: 50, terminal: 60, projectOutflow: 0, opex: 5, landRent: 1, financeFee: 0, financeInterest: 0, fundFeesAnnual: 0 }
];

test('in-kind land is added to the ROI investment base', () => {
  const c = browserContext();
  assert.equal(typeof c.computeProjectRoi, 'function');
  assert.equal(c.computeProjectRoi(rows, 0), 174 / 36);
  assert.equal(c.computeProjectRoi(rows, 14), 160 / 50);
  assert.equal(c.computeProjectRoi([], 0), null);
});

test('the shared formula matches the sensitivity base row', () => {
  const c = browserContext();
  const adjustedProjectCost = 38;
  const expenses = 12;
  const inflows = 210;
  const sensitivityRoi = (inflows - (adjustedProjectCost + expenses)) / (adjustedProjectCost + expenses);
  assert.equal(c.computeProjectRoi(rows, 14), sensitivityRoi);
});

test('the indicator and the sensitivity row use the shared formula', () => {
  assert.match(calcSource, /const roi = computeProjectRoi\(roiRows, landEquityContribution\)/);
  assert.doesNotMatch(calcSource, /roiInflows/);
  assert.match(reportSource, /roi: computeProjectRoi\(rows, f\.landEquityContribution\)/);
  assert.doesNotMatch(reportSource, /roi: out > 0 \? profit \/ out : null/);
});
