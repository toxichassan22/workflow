'use strict';

// «نسبة من أساس التمويل» prices an optional fund fee as a percentage of the
// financing base («قيمة أساس التمويل» in the financing section) and adds it to
// the fee table's computed total through the same per-year loop as every other
// additional-fee method.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const read = file => fs.readFileSync(path.join(root, 'assets/js', file), 'utf8');
const formatSource = read('09-financial/01_financial_format.js');
const calcSource = read('09-financial/02_formulas_calc.js');

function browserContext() {
  const context = vm.createContext({
    console, Intl, setTimeout, clearTimeout, window: {}, document: {
      addEventListener() {}, getElementById: () => null, querySelector: () => null,
      querySelectorAll: () => [], createElement: () => ({ dataset: {}, innerHTML: '', querySelectorAll: () => [] })
    },
    escapeHtml: value => String(value),
    refreshDynamicI18n() {}, wfTr: text => text, toast: () => {},
    WFT: (key, fallback) => fallback
  });
  vm.runInContext([formatSource, calcSource].join('\n'), context);
  return context;
}

test('the financing-base method prices a percentage of the financing base', () => {
  const c = browserContext();
  assert.equal(typeof c.calculateFundAdditionalFee, 'function');
  assert.equal(c.calculateFundAdditionalFee('percentFinanceBase', 2.5, { financeBase: 4000000 }), 100000);
  assert.equal(c.calculateFundAdditionalFee('percentFinanceBase', 1.75, { financeBase: 1234567 }), 21604.9225);
  assert.equal(c.calculateFundAdditionalFee('percentFinanceBase', 0, { financeBase: 4000000 }), 0);
  assert.equal(c.calculateFundAdditionalFee('percentFinanceBase', 2.5, { financeBase: 0 }), 0);
  assert.equal(c.calculateFundAdditionalFee('percentFinanceBase', 2.5, {}), 0);
  assert.equal(c.calculateFundAdditionalFee('percentFinanceBase', -5, { financeBase: 4000000 }), 0);
});

test('the existing additional-fee methods keep their own bases', () => {
  const c = browserContext();
  assert.equal(c.calculateFundAdditionalFee('fixed', 5000, { financeBase: 4000000 }), 5000);
  assert.equal(c.calculateFundAdditionalFee('percentFundCapital', 2, { fundCapital: 1000000, financeBase: 4000000 }), 20000);
  assert.equal(c.calculateFundAdditionalFee('percentProjectCost', 2, { projectCost: 500000, financeBase: 4000000 }), 10000);
  assert.equal(c.calculateFundAdditionalFee('percentExit', 2, { exitValue: 300000, financeBase: 4000000 }), 6000);
  assert.equal(c.calculateFundAdditionalFee('percentProfit', 2, { profit: 200000, financeBase: 4000000 }), 4000);
});

test('the method is offered in the fee table dropdown and names its base', () => {
  const c = browserContext();
  assert.equal(c.fundAdditionalFeeFormulaText('percentFinanceBase'), 'أساس التمويل × النسبة');
  assert.match(formatSource, /v: 'percentFinanceBase', t: 'نسبة من أساس التمويل'/);
});

test('the year loop passes the financing base into every additional-fee row', () => {
  assert.match(calcSource, /calculateFundAdditionalFee\(row\.method, row\.value, \{[^}]*financeBase: financeBaseAmount[^}]*\}\)/);
});

test('the computed amount is summed into the total fund costs', () => {
  assert.match(calcSource, /totalAdditionalFundFees \+= additionalFundFees/);
  assert.match(calcSource, /totalFundFees = totalFundManagementFees \+ totalAdditionalFundFees/);
  assert.match(calcSource, /setVal\('fundFeesTotal', money\(totalFundFees\)\)/);
  assert.match(calcSource, /setTxt\('resFundFees', resultMoney\(totalFundFees\)\)/);
});
