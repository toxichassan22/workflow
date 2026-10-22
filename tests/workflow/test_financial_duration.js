'use strict';

// The development duration is a timeline fact, not an assumption: section 14 shows
// the exact calendar span (3 years and 6 months is 3.5) and every sensitivity
// scenario keeps that same value instead of editing or rounding it.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const read = file => fs.readFileSync(path.join(root, 'assets/js', file), 'utf8');
const marketSource = read('04-market.js');
const formatSource = read('09-financial/01_financial_format.js');
const calcSource = read('09-financial/02_formulas_calc.js');
const reportSource = read('10-financial-report-timeline/01_report_collect.js');
const timelineSource = read('10-financial-report-timeline/03_timeline_board.js');

function browserContext(overrides = {}) {
  const context = vm.createContext({
    console, Intl, setTimeout, clearTimeout, window: {}, document: {
      addEventListener() {}, getElementById: () => null, querySelector: () => null,
      querySelectorAll: () => [], createElement: () => ({ dataset: {}, innerHTML: '', querySelector: () => null, querySelectorAll: () => [] })
    },
    escapeHtml: value => String(value),
    refreshDynamicI18n() {}, wfTr: text => text, toast: () => {},
    WFT: (key, fallback, params = {}) => fallback,
    ...overrides
  });
  vm.runInContext([marketSource, formatSource, calcSource, reportSource, timelineSource].join('\n'), context);
  return context;
}

test('the timeline duration is the exact calendar span', () => {
  const c = browserContext();
  assert.equal(c.timelineDurationYears(Date.UTC(2030, 0, 1), Date.UTC(2033, 5, 30)), 3.5);
  assert.equal(c.timelineDurationYears(Date.UTC(2030, 0, 1), Date.UTC(2032, 11, 31)), 3);
  assert.equal(c.timelineDurationYears(Date.UTC(2030, 0, 1), Date.UTC(2031, 0, 31)), 13 / 12);
  assert.equal(c.timelineDurationYears(Date.UTC(2030, 0, 1), Date.UTC(2029, 0, 1)), null);
});

test('the financial mirror stores the exact duration, never a rounded bucket', () => {
  assert.ok(timelineSource.includes('String(timelineDurationYears(period.start.ms, period.end.ms))'));
  assert.ok(!timelineSource.includes('Math.ceil((period.end.ms - period.start.ms)'));
});

test('adding the duration variable pins it to the timeline value', () => {
  const rows = {
    length: 0,
    querySelectorAll: () => [],
    appendChild(row) { rows.length += 1; rows.last = row; }
  };
  const context = browserContext({
    document: {
      addEventListener() {},
      getElementById: id => id === 'developmentYears' ? { value: '3.5' }
        : id === 'developmentDurationText' ? { value: '3 سنوات و6 شهر' } : null,
      querySelector: selector => selector === '#sensitivityAssumptionsTable tbody' ? rows : null,
      querySelectorAll: () => [],
      createElement: () => ({ dataset: {}, innerHTML: '', querySelector: () => null, querySelectorAll: () => [] })
    }
  });
  context.addSensitivityVariable({ key: 'developmentYears', low: 99, high: 1, silent: true });
  const html = rows.last.innerHTML;
  assert.equal((html.match(/data-value="3\.5"/g) || []).length, 2, html);
  assert.equal((html.match(/3 سنوات و6 شهر/g) || []).length, 3, html);
  assert.ok(!html.includes('oninput'), html);
  assert.ok(html.includes('قيمة ثابتة من الجدول الزمني'), html);
});

test('every sensitivity scenario skips the development duration', () => {
  assert.ok(reportSource.includes("if (!regVar || regVar.key === 'developmentYears') return"));
  assert.ok(reportSource.includes("const fixed = key === 'developmentYears'"));
});
