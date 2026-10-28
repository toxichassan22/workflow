// Slide element paths must ignore editor chrome and preview-only layers.
// The move/resize handles and the cover photo are added inside the live slide,
// and they used to shift every element path after them. An edit that changed the
// text-node count then wrote its text into a neighbour (or nowhere), so the
// client showed the change and the saved presentation reverted it.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(process.cwd(), 'assets/js/13-visual/02_slides_progress.js'), 'utf8');

function extract(name, nextName) {
  const start = source.indexOf('function ' + name + '(');
  const end = source.indexOf('function ' + nextName + '(', start + 1);
  if (start < 0 || end <= start) throw new Error('missing ' + name + ' in the slide bundle');
  return source.slice(start, end);
}

const code = [
  extract('slidePathIgnores', 'slideElementPath'),
  extract('slideElementPath', 'elementAtSlidePath'),
  extract('elementAtSlidePath', 'slideNodeIsVisualShape'),
].join('\n');
const sandbox = {};
vm.runInNewContext(code + '\nthis.__api = { slidePathIgnores, slideElementPath, elementAtSlidePath };', sandbox);
const { slidePathIgnores, slideElementPath, elementAtSlidePath } = sandbox.__api;

function makeEl(tag, options = {}) {
  const classes = new Set(options.classes || []);
  const attrs = options.attrs || {};
  const node = {
    nodeType: 1,
    tagName: String(tag || 'div').toUpperCase(),
    children: [],
    parentElement: null,
    classList: {
      contains: name => classes.has(name),
      add: name => classes.add(name),
      remove: name => classes.delete(name),
    },
    getAttribute: key => (Object.prototype.hasOwnProperty.call(attrs, key) ? attrs[key] : null),
    setAttribute: (key, value) => { attrs[key] = value; },
    appendChild: child => {
      child.parentElement = node;
      node.children.push(child);
      return child;
    },
  };
  (options.children || []).forEach(child => node.appendChild(child));
  return node;
}

const root = makeEl('div', { classes: ['slide'] });
const overlay = makeEl('div', { attrs: { 'data-cover-overlay': '' } });
const logo = makeEl('div');
const titleBox = makeEl('div');
const heading = makeEl('h2');
const footer = makeEl('div');
const watermark = makeEl('div', { classes: ['slide-watermark'] });
titleBox.appendChild(makeEl('h1'));
titleBox.appendChild(heading);
root.appendChild(overlay);
root.appendChild(logo);
root.appendChild(titleBox);
root.appendChild(footer);
root.appendChild(watermark);
// Exactly what the editor adds after rendering.
root.appendChild(makeEl('div', { attrs: { 'data-slide-live-only': '1' } }));
root.appendChild(makeEl('div', { classes: ['slide-move-handle'] }));
root.appendChild(makeEl('button', { classes: ['slide-element-delete-btn'] }));

assert.equal(slidePathIgnores(root.children[5]), true, 'live-only cover photo must be ignored');
assert.equal(slidePathIgnores(root.children[6]), true, 'move handle must be ignored');
assert.equal(slidePathIgnores(root.children[7]), true, 'delete button must be ignored');
assert.equal(slidePathIgnores(titleBox), false, 'content elements stay addressable');

assert.deepEqual(Array.from(slideElementPath(root, heading)), [2, 1]);
assert.equal(elementAtSlidePath(root, [2, 1]), heading);
assert.equal(elementAtSlidePath(root, [3]), footer);
assert.equal(elementAtSlidePath(root, slideElementPath(root, footer)), footer);
assert.equal(elementAtSlidePath(root, slideElementPath(root, watermark)), watermark);

// A path taken before the chrome existed still resolves to the same content.
assert.deepEqual(Array.from(slideElementPath(root, footer)), [3]);
assert.equal(elementAtSlidePath(root, [3]), footer);

console.log('slide edit paths: OK');
