const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// text-decoration: none underline is invalid CSS; the browser drops the whole
// declaration, which is why underline/strike never appeared on a slide.
const file = path.join(process.cwd(), 'assets/js/15b-slide-canvas/05_canvas_tools.js');
const source = fs.readFileSync(file, 'utf8');
const start = source.indexOf('function slideTextDecorationNext');
const end = source.indexOf('function toggleSlideSelectionTextStyle');
assert.ok(start !== -1 && end > start, 'slideTextDecorationNext is missing');
const context = {};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);

const next = context.slideTextDecorationNext;
assert.equal(next('none', 'underline'), 'underline');
assert.equal(next('none', 'strike'), 'line-through');
assert.equal(next('', 'underline'), 'underline');
assert.equal(next('NONE', 'underline'), 'underline');
assert.equal(next('underline', 'underline'), '');
assert.equal(next('line-through', 'strike'), '');
assert.equal(next('underline line-through', 'underline'), 'line-through');
assert.equal(next('line-through', 'underline'), 'line-through underline');
assert.equal(next('underline', 'strike'), 'underline line-through');

console.log('Slide text toolbar harness passed: underline/strike compose valid decoration values.');
