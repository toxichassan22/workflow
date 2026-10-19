'use strict';

// صفحة «النتائج» في الدراسة المالية تعرض كل قيمة مقربة لأقرب جزء من مئة (خانتان عشريتان)،
// وبقية أقسام الدراسة المالية تعرض القيمة كما حُفظت. الاختبار يشغّل دالة التقريب الحقيقية
// من ملفات الواجهة، يتحقق من نصف القيمة عند المنتصف، ويثبت أن كتابة صفحة النتائج وحدها
// تستخدم resultMoney / resultPercent / resultNumber.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const read = file => fs.readFileSync(path.join(root, 'assets/js', file), 'utf8');
const formatSource = read('09-financial/01_financial_format.js');
const calcSource = read('09-financial/02_formulas_calc.js');
const reportSource = read('10-financial-report-timeline/01_report_collect.js');
const source = [read('04-market.js'), formatSource, calcSource, reportSource].join('\n');

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
  vm.runInContext(source, context);
  return context;
}

test('page values round half-up to the nearest hundredth', () => {
  const c = browserContext();
  assert.equal(c.roundFinancialHundredth(12.345678901234567), 12.35);
  assert.equal(c.roundFinancialHundredth(-3.4567), -3.46);
  assert.equal(c.roundFinancialHundredth(1.005), 1.01);
  assert.equal(c.roundFinancialHundredth(-1.005), -1.01);
  assert.equal(c.roundFinancialHundredth(2.675), 2.68);
  assert.equal(c.roundFinancialHundredth(164000.00000000003), 164000);
  assert.equal(c.roundFinancialHundredth(33.333333333333336), 33.33);
  assert.equal(c.roundFinancialHundredth(0), 0);
  assert.equal(c.resultMoney(1234567.891234), '1,234,567.89');
  assert.equal(c.resultMoney(164000.00000000003), '164,000');
  assert.equal(c.resultPercent(12.345678901234567), '12.35%');
  assert.equal(c.resultPercent(-80), '-80%');
  assert.equal(c.resultNumber(-3.4567), '-3.46');
  assert.equal(c.resultNumber(4.1), '4.1');
});

test('the results page writers round and the rest of the study keeps exact values', () => {
  assert.match(calcSource, /setTxt\('resLeasable', resultMoney\(leasable\)/);
  assert.match(calcSource, /setTxt\('resProjectCost', resultMoney\(projectCostWithFinance\)\)/);
  assert.match(calcSource, /setTxt\('resROI', roi === null \? 'غير متاح' : resultPercent\(roi \* 100\)\)/);
  assert.match(calcSource, /setTxt\('resIRR', irrVal === null \? 'غير متاح' : resultPercent\(irrVal \* 100\)\)/);
  assert.match(calcSource, /setHtml\('resPayback',[^;]*resultNumber\(payback\)/);
  assert.match(calcSource, /setTxt\('resEquityRequired', resultMoney\(totalEquityRequired\)\)/);
  // جدول التدفقات النقدية داخل كتلة «النتائج» نفسها.
  assert.match(calcSource, /<td class="cf-finance">\$\{resultMoney\(r\.financeDraw\)\}<\/td>/);
  assert.match(calcSource, /<td class="row-result">\$\{r\.cumulative < 0 \? '\(' \+ resultMoney\(Math\.abs\(r\.cumulative\)\)/);

  const resultsWriters = calcSource.split('\n').filter(line => /set(Txt|Html)\('res/.test(line));
  assert.ok(resultsWriters.length > 20, 'expected the results page writers to be found');
  for (const line of resultsWriters) {
    assert.ok(!/\bmoney\(/.test(line), 'unrounded amount on the results page: ' + line.trim());
    assert.ok(!/\bfinancialPercent\(/.test(line), 'unrounded percent on the results page: ' + line.trim());
    assert.ok(!/formatFinancialResultNumber\(/.test(line), 'unrounded number on the results page: ' + line.trim());
  }

  // أقسام الدراسة المالية خارج صفحة النتائج تعرض القيمة كما حُفظت (نطاق التقريب هو الصفحة فقط).
  assert.match(calcSource, /setVal\('financeInterestTotal', money\(totalFinanceInterest\)\)/);
  assert.match(calcSource, /setVal\('facilityAmount', money\(facilityAmount\)\)/);
  assert.match(calcSource, /setVal\('equityRequired', money\(totalEquityRequired\)\)/);
  assert.match(calcSource, /debtTb\.innerHTML = financeMovementRows/);
});

test('the sensitivity tables on the results tab round the same way', () => {
  assert.match(reportSource, /sensitivity-base-value sensAutoBase">\$\{resultMoney\(base\)\}/);
  assert.match(reportSource, /c\.textContent = `\$\{resultMoney\(b\)\} \$\{reg\.unit\}`/);
  assert.match(reportSource, /<td>\$\{resultMoney\(r\.totalRevenue\)\}<\/td>/);
  assert.match(reportSource, /resultPercent\(r\.roi \* 100\)/);
  assert.match(reportSource, /resultPercent\(r\.projectIrr \* 100\)/);
  assert.match(reportSource, /resultPercent\(r\.equityIrr \* 100\)/);
  assert.match(reportSource, /resultNumber\(r\.payback\)/);
  assert.match(reportSource, /<td>\$\{resultMoney\(r\.equity\)\}<\/td>/);
});

test('a rendered sensitivity row carries no long decimal tail', () => {
  const body = { innerHTML: '' };
  const context = vm.createContext({
    console, Intl, setTimeout, clearTimeout, window: {}, document: {
      addEventListener() {}, getElementById: () => null,
      querySelector: selector => selector === '#sensitivityTable tbody' ? body : null,
      querySelectorAll: () => [], createElement: () => ({ dataset: {}, innerHTML: '', querySelectorAll: () => [] })
    },
    escapeHtml: value => String(value), refreshDynamicI18n() {}, wfTr: text => text, toast: () => {},
    WFT: (key, fallback, params = {}) => fallback
  });
  vm.runInContext(source, context);
  context.calculateAll = () => {};
  context.window.__financialProjection = {
    adjustedProjectCost: 1000000, projected: [], terminal: 200000, payback: 3.4567,
    cashflows: [-500, 200, 400], projectCashflows: [-1000, 500, 700],
    fullOccupancyNOI: 123456.789123, equityRequired: 500000.123456
  };
  context.renderSensitivity();

  assert.ok(body.innerHTML.includes('-80%'), body.innerHTML);
  assert.ok(body.innerHTML.includes('3.46 سنة'), body.innerHTML);
  assert.ok(body.innerHTML.includes('123,456.79'), body.innerHTML);
  assert.ok(body.innerHTML.includes('500,000.12'), body.innerHTML);
  assert.equal(/\.\d{3,}/.test(body.innerHTML), false, body.innerHTML);
});
