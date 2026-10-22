'use strict';
// Run with node tests/presentations/test_slide_inline_edit.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(
  __dirname, '..', '..', 'assets', 'js', '15-slide-edit-chat', '01_render_inline_edit.js'), 'utf8');
const syncStart = source.indexOf('    function syncFinancialClarificationsFromSlide');
assert(syncStart >= 0, 'syncFinancialClarificationsFromSlide must exist');
const syncEnd = source.indexOf('\n    }', syncStart) + 6;
const sync = source.slice(syncStart, syncEnd);
const start = source.indexOf('    function slideEditableSafeHtml');
assert(start >= 0, 'slideEditableSafeHtml must exist');
const end = source.indexOf('\n    }', start) + 6;
const helper = source.slice(start, end);
const commitStart = source.indexOf('    function commitSlideInlineEdit');
assert(commitStart >= 0, 'commitSlideInlineEdit must exist');
const commitEnd = source.indexOf('\n    }', commitStart) + 6;
const commit = source.slice(commitStart, commitEnd);

const context = vm.createContext({
  escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g,
      ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  },
  slideChromeOf: () => null,
  slideElementPath: () => [0],
  elementAtSlidePath: () => null,
  collectSlideTextNodes: () => [],
  pushSlideEditHistory: () => {},
  touchSlideEditSession: () => {},
  triggerAutoSaveDraft: () => {},
  renderTenantSlidesSidebar: () => {},
  toast: () => {},
  autoFitSlideContent: () => {},
  tenantSlidesData: [{}],
  tenantProjectData: { financial_study_model: { inputs: {} } },
  document: { getElementById: () => null }
});
vm.runInContext(sync + '\n' + helper + '\n' + commit, context);

const text = value => ({ nodeType: 3, nodeValue: value });
const element = (tagName, childNodes = []) => ({ nodeType: 1, tagName, childNodes });
const edited = element('TD', [
  text('أ'),
  element('BR'),
  text('ب'),
  element('DIV', [text('ج')]),
]);
assert.equal(context.slideEditableSafeHtml(edited), 'أ<br>ب<br>ج');
assert.equal(
  context.slideEditableSafeHtml(element('TD', [text('&'), element('BR'), text('<')])),
  '&amp;<br>&lt;');

// The commit must fall back to the edited element's path when Enter changed the
// number of text nodes, instead of silently keeping the pre-edit HTML.
assert.match(commit, /liveNodes\.length === rawNodes\.length/);
assert.match(commit, /slideEditableSafeHtml\(editedTarget\)/);
assert.match(commit, /elementAtSlidePath\(rawRoot, elementPath\)/);

// An inline edit of the clarifications page updates the study's own textarea
// and model, so regenerating the section does not bring the old text back.
let textarea = { value: '' };
let dirtied = false;
context.document = { getElementById: id => (id === 'financialClarifications' ? textarea : null) };
context.triggerAutoSaveDraft = () => { dirtied = true; };
const textBlock = { tagName: 'P', innerText: '1- البيع والتأجير', textContent: '1- البيع والتأجير' };
const textRoot = { children: [textBlock] };
const container = {
  querySelector(selector) {
    if (selector === '[data-financial-clarifications-empty="1"]') return null;
    if (selector === '[data-financial-clarifications-text="1"]') return textRoot;
    return null;
  }
};
const slideRoot = {
  querySelector(selector) {
    return selector === '[data-financial-clarifications="1"]' ? container : null;
  }
};
context.syncFinancialClarificationsFromSlide(slideRoot);
assert.equal(textarea.value, '1- البيع والتأجير');
assert.equal(context.tenantProjectData.financial_study_model.inputs.financialClarifications,
  '1- البيع والتأجير');
assert.equal(dirtied, true);

console.log('slide inline edit structural commit: ok');

