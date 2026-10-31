const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// The pure authoring helpers build slide HTML and replace deck text without a
// DOM; the browser contract around them is pinned in test_slide_workspace_ui.py.
const file = path.join(process.cwd(), 'assets/js/15b-slide-canvas/04_authoring.js');
const source = fs.readFileSync(file, 'utf8');
const start = source.indexOf('/* AUTHORING_PURE_BEGIN */');
const end = source.indexOf('/* AUTHORING_PURE_END */');
assert.ok(start !== -1 && end > start, 'authoring pure block markers are missing');
const context = {};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);

const colors = context.authoringBrandColors();
assert.equal(colors.primary, '#07182C');
assert.equal(colors.accent, '#17C8E3');

const blank = context.structuredSlideHtml('blank', 'عرض تجريبي', colors);
assert.match(blank, /class="slide"/);
assert.match(blank, /dir="rtl"/);
assert.match(blank, /data-manual-slide="1"/);
assert.match(blank, /##LOGO##/);
assert.match(blank, /data-slide-footer="1"/);
assert.match(blank, /data-slide-counter="1"/);
assert.match(blank, /height:720px/);
assert.doesNotMatch(blank, /font-family/);

const title = context.structuredSlideHtml('title', 'عنوان "مقتبس"', colors);
assert.match(title, /data-slide-textbox="1"/);
assert.match(title, /عنوان &quot;مقتبس&quot;/);

const titleText = context.structuredSlideHtml('title_text', 'عنوان', colors);
assert.match(titleText, /اكتب النص هنا/);

const textImage = context.structuredSlideHtml('text_image', 'عنوان', colors);
assert.match(textImage, /width:520px/);
assert.match(textImage, /اكتب النص هنا/);

const tableSlide = context.structuredSlideHtml('table', 'جدول', colors);
assert.equal((tableSlide.match(/<th\b/g) || []).length, 3, 'header cells match columns');
assert.equal((tableSlide.match(/<td\b/g) || []).length, 9, 'body cells are 3 rows by 3 columns');
assert.match(tableSlide, /data-slide-table="1"/);

const table = context.slideTableMarkup(5, 2, colors);
assert.equal((table.match(/<th\b/g) || []).length, 2);
assert.equal((table.match(/<td\b/g) || []).length, 8);
assert.equal((table.match(/<tr>/g) || []).length, 5);

const html = '<div class="slide" title="قديم"><style>.قديم{color:red}</style>'
  + '<p>قديم هنا</p><span data-label="قديم">قديم</span></div>';
const replaced = context.deckReplaceInSlideHtml(html, 'قديم', 'جديد');
assert.equal(replaced.count, 2);
assert.match(replaced.html, /<p>جديد هنا<\/p>/);
assert.match(replaced.html, /<span data-label="قديم">جديد<\/span>/, 'attributes stay untouched');
assert.match(replaced.html, /title="قديم"/, 'the slide attribute stays untouched');
assert.match(replaced.html, /\.قديم\{color:red\}/, 'style blocks stay untouched');

const unchanged = context.deckReplaceInSlideHtml(html, 'مفقود', 'جديد');
assert.equal(unchanged.count, 0);
assert.equal(unchanged.html, html);

const literalReplacement = context.deckReplaceInSlideHtml('<p>ابحث</p>', 'ابحث', 'a$b\\c');
assert.equal(literalReplacement.count, 1);
assert.match(literalReplacement.html, /<p>a\$b\\c<\/p>/);

const emptyNeedle = context.deckReplaceInSlideHtml(html, '', 'x');
assert.equal(emptyNeedle.count, 0);
assert.equal(emptyNeedle.html, html);

// Manual slides survive a full regeneration: captured before the AI deck is
// cleared, then put back at their original positions (or at the end after a
// failed run, so a checkpoint resume can never overwrite them).
const manualStart = source.indexOf('function preserveManualSlidesForRegeneration()');
assert.ok(manualStart !== -1, 'manual preservation helpers are missing');
const manualContext = {
  tenantSlidesData: [],
  renumberTenantSlides() {},
  renderTenantSlides() {},
  renderTenantSlidesSidebar() {},
  markSlidesDeckChanged() {},
};
vm.createContext(manualContext);
vm.runInContext(source.slice(manualStart), manualContext);

const manual = { id: 'manual', manual: true };
const generated = { id: 'generated' };
manualContext.tenantSlidesData = [{ id: 'm1', manual: true }, generated, { id: 'm2', manual: true }];
const captured = manualContext.preserveManualSlidesForRegeneration();
assert.deepEqual(captured.map(entry => entry.index), [0, 2]);
assert.deepEqual(captured.map(entry => entry.slide.id), ['m1', 'm2']);

manualContext.tenantSlidesData = [{ id: 'g1' }, { id: 'g2' }, { id: 'g3' }];
manualContext.restoreManualSlidesAfterRegeneration(captured, {});
assert.deepEqual(manualContext.tenantSlidesData.map(slide => slide.id),
  ['m1', 'g1', 'm2', 'g2', 'g3']);

manualContext.tenantSlidesData = [{ id: 'g1' }, { id: 'g2' }, { id: 'g3' }];
manualContext.restoreManualSlidesAfterRegeneration(captured, { atEnd: true });
assert.deepEqual(manualContext.tenantSlidesData.map(slide => slide.id),
  ['g1', 'g2', 'g3', 'm1', 'm2']);

console.log('Slide authoring harness passed: structures, table markup, text-node replacement, manual-slide preservation.');
