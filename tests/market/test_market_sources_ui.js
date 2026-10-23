'use strict';

// Market source display tests — one final page per competitor, and the
// summary register never absorbs competitor links.
// Run: node --test tests/market/test_market_sources_ui.js

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const files = [
  'assets/js/03-executive-classification.js',
  'assets/js/04-market.js',
  'assets/js/04a-market-section.js',
  'assets/js/05-market-competitors.js',
  'assets/js/05-market-competitors/03_source_links.js',
  'assets/js/05a-market-jobs.js',
];
const source = files.map(file =>
  fs.readFileSync(path.join(root, file), 'utf8')).join('\n');

function context() {
  const sandbox = vm.createContext({
    console, Intl, URL, JSON, Date, Set, Map, Array, String, Number,
    window: { location: { origin: 'http://localhost:5515' } },
    tenantProjectData: { city: 'جدة', district: 'النرجس' },
    document: {
      addEventListener() {},
      getElementById: () => null,
      querySelector: () => null,
      querySelectorAll: () => [],
    },
    WFT: (key, fallback = key) => fallback,
    wfTr: text => text,
    escapeHtml: text => String(text ?? ''),
    toast() {},
  });
  vm.runInContext(source, sandbox);
  return sandbox;
}

test('competitor row points at the final property page, not the search chain', () => {
  const sandbox = context();
  const row = {
    name: 'فندق تجريبي',
    operation_type: 'تشغيل فندقي',
    source_url: 'https://www.booking.com/searchresults.ar.html?ss=jeddah',
    source_urls: [
      'https://www.booking.com/searchresults.ar.html?ss=jeddah',
      'https://www.booking.com/district/sa/jiddah/alandalus.ar.html',
      'https://www.booking.com/hotel/sa/novotel-jeddah-tahlia.ar.html',
    ],
  };
  assert.equal(
    sandbox.competitorPrimarySourceUrl(row),
    'https://www.booking.com/hotel/sa/novotel-jeddah-tahlia.ar.html');
});

test('price evidence page wins over a stated developer homepage', () => {
  const sandbox = context();
  const row = {
    name: 'مجمع',
    source_url: 'https://developer.example/',
    field_sources: { price_value: ['https://sa.aqar.fm/listing/tower-price'] },
    source_urls: ['https://developer.example/'],
  };
  assert.equal(
    sandbox.competitorPrimarySourceUrl(row),
    'https://sa.aqar.fm/listing/tower-price');
});

test('a client-entered source wins, and a deleted one stays deleted', () => {
  const sandbox = context();
  const manual = {
    name: 'مجمع',
    source_url: 'https://client.example/my-project',
    source_url_manual: true,
    field_sources: { price_value: ['https://sa.aqar.fm/listing/price'] },
  };
  assert.equal(sandbox.competitorPrimarySourceUrl(manual),
    'https://client.example/my-project');
  const deleted = { ...manual, source_url: '' };
  assert.equal(sandbox.competitorPrimarySourceUrl(deleted), '');
});

test('the source editor marks a client edit as manual', () => {
  assert.match(source, /sourceUrlManual = '1'/);
  assert.match(source, /source_url_manual: tr\.dataset\.sourceUrlManual === '1'/);
});

test('summary register drops competitor rows and canonical duplicates', () => {
  const sandbox = context();
  const rows = sandbox.mergeMarketSourceRows([
    { name: 'تقرير', url: 'https://www.example.com/report?utm_source=x' },
    { name: 'تقرير مكرر', url: 'https://example.com/report' },
    { name: 'منافس', source_kind: 'competitor', competitor_id: 'c1',
      url: 'https://www.booking.com/hotel/sa/one.ar.html' },
  ], []);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].name, 'تقرير');
});

test('the competitor editor renders exactly one source input', () => {
  const text = source;
  assert.match(text, /function renderCompetitorSourceUrlEditor/);
  assert.match(text, /function competitorPrimarySourceUrl/);
  assert.match(text, /data-source-url-row/);
  assert.doesNotMatch(text, /data-add-source-url/);
  assert.match(text, /const url = competitorSourceUrlValues\(tr\)\[0\] \|\| ''/);
});
