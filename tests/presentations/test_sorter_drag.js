'use strict';
// Run with node tests/presentations/test_sorter_drag.js
// Drives the real sorter part with a minimal DOM: dragging must show the
// landing gap, and dropping must reorder the existing nodes instead of
// rebuilding the grid (a rebuild is what flashed the thumbnails away).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const file = path.join(process.cwd(), 'assets/js/15a-slide-workspace/02_sorter.js');
const source = fs.readFileSync(file, 'utf8');

const pureStart = source.indexOf('/* SORTER_PURE_BEGIN */');
const pureEnd = source.indexOf('/* SORTER_PURE_END */');
assert.ok(pureStart !== -1 && pureEnd > pureStart, 'sorter pure block markers are missing');
const pure = vm.createContext({});
vm.runInContext(source.slice(pureStart, pureEnd), pure);

const rtlRow = [770, 522, 274].map(left => ({ rect: { left, top: 0, width: 230, height: 150 } }));
const rtlSecondRow = [770, 522, 274].map(left => ({ rect: { left, top: 168, width: 230, height: 150 } }));
const rtlItems = rtlRow.concat(rtlSecondRow);
assert.equal(pure.sorterDropBoundary(rtlItems, 900, 75, true), 0, 'right of the first card is the start');
assert.equal(pure.sorterDropBoundary(rtlItems, 700, 75, true), 1, 'between the first two cards');
assert.equal(pure.sorterDropBoundary(rtlItems, 637, 75, true), 2, 'a card midpoint belongs to its slot');
assert.equal(pure.sorterDropBoundary(rtlItems, 300, 75, true), 3, 'left of the row leaves the row');
assert.equal(pure.sorterDropBoundary(rtlItems, 900, 243, true), 3, 'the second row starts after the first');
assert.equal(pure.sorterDropBoundary(rtlItems, 700, 243, true), 4);
assert.equal(pure.sorterDropBoundary(rtlItems, 700, 900, true), 4, 'below the grid uses the nearest row');
assert.equal(pure.sorterDropBoundary([], 0, 0, true), 0);
const ltrRow = [274, 522, 770].map(left => ({ rect: { left, top: 0, width: 230, height: 150 } }));
assert.equal(pure.sorterDropBoundary(ltrRow, 200, 75, false), 0);
assert.equal(pure.sorterDropBoundary(ltrRow, 500, 75, false), 1);
assert.equal(pure.sorterDropBoundary(ltrRow, 900, 75, false), 3);

// The pointer slot must not move when the preview gap reflows the grid under
// a resting pointer: counting midpoints means the cards that decide the
// boundary never move, so the same coordinates keep the same slot.
{
  const clientX = 700;
  const beforeGap = pure.sorterDropBoundary(rtlRow, clientX, 75, true);
  const shifted = [770, 274, 26].map(left => ({ rect: { left, top: 0, width: 230, height: 150 } }));
  const afterGap = pure.sorterDropBoundary(shifted, clientX, 75, true);
  assert.equal(beforeGap, 1);
  assert.equal(afterGap, beforeGap, 'the landing slot is stable while the gap reflows the row');
}

assert.equal(pure.sorterDropFinalIndex(1, 3, 'after', 5), 3);
assert.equal(pure.sorterDropFinalIndex(1, 3, 'before', 5), 2);
assert.equal(pure.sorterDropFinalIndex(3, 1, 'before', 5), 1);
assert.equal(pure.sorterDropFinalIndex(3, 1, 'after', 5), 2);
assert.equal(pure.sorterDropFinalIndex(3, 1, 'end', 5), 4);
assert.equal(pure.sorterDropFinalIndex(0, 0, 'before', 5), 0, 'its own slot is a no-op');
assert.equal(pure.sorterDropFinalIndex(0, 0, 'after', 5), 0);
assert.equal(pure.sorterDropFinalIndex(2, 1, 'after', 5), 2, 'after the previous card is a no-op');
assert.equal(pure.sorterDropFinalIndex(0, 0, 'before', 0), -1);
assert.equal(pure.sorterDropFinalIndex(-1, 2, 'before', 5), -1);
assert.equal(pure.sorterDropFinalIndex(0, 9, 'before', 5), -1);

function matchSimple(node, selector) {
  if (selector.startsWith('.')) return node.classList.contains(selector.slice(1));
  if (selector.startsWith('#')) return node.id === selector.slice(1);
  return node.tagName === selector.toUpperCase();
}

function matches(node, selector) {
  const parts = String(selector).split(',').map(part => part.trim()).filter(Boolean);
  return parts.some(part => {
    const nots = [];
    const base = part.replace(/:not\(([^)]*)\)/g, (match, inner) => {
      nots.push(inner.trim());
      return '';
    });
    for (const not of nots) if (matchSimple(node, not)) return false;
    return base ? matchSimple(node, base) : true;
  });
}

function descendants(node, out = []) {
  node.children.forEach(child => {
    out.push(child);
    descendants(child, out);
  });
  return out;
}

class FakeNode {
  constructor(tag) {
    this.tagName = String(tag || 'div').toUpperCase();
    this.id = '';
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this._classes = new Set();
    this._text = '';
    this._html = '';
    this._rect = null;
    this._isRoot = false;
    this.hidden = false;
    const self = this;
    this.classList = {
      add: (...names) => names.forEach(name => self._classes.add(name)),
      remove: (...names) => names.forEach(name => self._classes.delete(name)),
      contains: name => self._classes.has(name),
      toggle: (name, force) => {
        const on = force === undefined ? !self._classes.has(name) : !!force;
        if (on) self._classes.add(name); else self._classes.delete(name);
        return on;
      },
    };
  }

  get className() { return Array.from(this._classes).join(' '); }
  set className(value) { this._classes = new Set(String(value).split(/\s+/).filter(Boolean)); }

  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value); }

  get innerHTML() { return this._html; }
  set innerHTML(value) {
    this._html = String(value);
    this.children.forEach(child => { child.parentNode = null; });
    this.children = [];
  }

  get isConnected() {
    let node = this;
    while (node.parentNode) node = node.parentNode;
    return node._isRoot === true;
  }

  get nextSibling() {
    const parent = this.parentNode;
    if (!parent) return null;
    const index = parent.children.indexOf(this);
    return index === -1 ? null : (parent.children[index + 1] || null);
  }

  appendChild(child) { return this.insertBefore(child, null); }

  insertBefore(child, reference) {
    if (child === reference) return child;
    if (child.parentNode) {
      const oldIndex = child.parentNode.children.indexOf(child);
      if (oldIndex !== -1) child.parentNode.children.splice(oldIndex, 1);
    }
    const at = reference ? this.children.indexOf(reference) : this.children.length;
    if (at === -1) throw new Error('insertBefore reference not found');
    this.children.splice(at, 0, child);
    child.parentNode = this;
    return child;
  }

  remove() {
    if (!this.parentNode) return;
    const index = this.parentNode.children.indexOf(this);
    if (index !== -1) this.parentNode.children.splice(index, 1);
    this.parentNode = null;
  }

  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] === undefined ? null : this.attributes[name]; }

  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    return descendants(this).filter(node => matches(node, selector));
  }

  closest(selector) {
    let node = this;
    while (node) {
      if (matches(node, selector)) return node;
      node = node.parentNode;
    }
    return null;
  }

  getBoundingClientRect() {
    return this._rect || { left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 };
  }

  contains(node) {
    let current = node;
    while (current) {
      if (current === this) return true;
      current = current.parentNode;
    }
    return false;
  }

  animate() { return { cancel() {} }; }
  getAnimations() { return []; }
  addEventListener() {}
}

const boxes = {};
const documentStub = {
  dir: 'rtl',
  getElementById: id => boxes[id] || null,
  createElement: tag => new FakeNode(tag),
  addEventListener: () => {},
  querySelectorAll: () => [],
  documentElement: { dir: 'rtl' },
  elementFromPoint: () => null,
};

let activeIndex = 0;
const moves = [];
const insertCalls = [];
const deleteCalls = [];
const events = [];
const ctx = {
  console,
  document: documentStub,
  window: { matchMedia: () => ({ matches: true }) },
  requestAnimationFrame: callback => callback(),
  getComputedStyle: () => ({ direction: 'rtl' }),
  WFT: (key, fallback) => fallback,
  escapeHtml: value => String(value),
  hasPermission: () => true,
  selectTenantSlide: (index, skipScroll) => {
    activeIndex = index;
    ctx.activeSlideIndex = index;
    events.push('select:' + index + ':' + (skipScroll ? 'quiet' : 'scroll'));
  },
  setSlidesWorkspaceView: view => { events.push('view:' + view); },
  fillSlideThumbnailCanvas: canvas => { canvas.dataset.filled = '1'; },
  openSlideInsertMenu: (anchor, index) => { insertCalls.push(index); },
  deleteSlide: index => { deleteCalls.push(index); },
  tenantSlidesView: 'sorter',
  tenantSlidesData: [],
  activeSlideIndex: 0,
  slideIndexById: id => ctx.tenantSlidesData.findIndex(slide => String(slide.id) === String(id)),
  beginPresentationUndoChange: () => {},
  triggerAutoSaveDraft: () => {},
  toast: () => {},
  moveTenantSlide: (from, to, options) => {
    // Mirrors the real moveTenantSlide: it re-renders the sorter, which the
    // drop must suppress while it reorders the grid in place.
    moves.push({
      from,
      to,
      options,
      suppressed: typeof ctx.__suppressNow === 'function' ? ctx.__suppressNow() : null
    });
    const [moved] = ctx.tenantSlidesData.splice(from, 1);
    ctx.tenantSlidesData.splice(to, 0, moved);
    if (typeof ctx.renderTenantSlidesSorter === 'function') ctx.renderTenantSlidesSorter();
  },
};
vm.createContext(ctx);
vm.runInContext(source, ctx);
vm.runInContext('function __suppressNow() { return tenantSorterSuppressRender; }', ctx);

function layout(grid) {
  const cells = grid.children.filter(child => child.classList.contains('ge-sorter-cell'));
  cells.forEach((cell, index) => {
    const row = Math.floor(index / 3);
    const col = index % 3;
    const width = 230;
    const height = 150;
    const left = 1000 - (col + 1) * width - col * 18;
    const top = row * (height + 18);
    cell._rect = { left, top, width, height, right: left + width, bottom: top + height };
  });
}

function setup(ids) {
  ctx.tenantSlidesData = ids.map(id => ({ id, title: 'Slide ' + id, html: '' }));
  ctx.activeSlideIndex = 0;
  activeIndex = 0;
  moves.length = 0;
  insertCalls.length = 0;
  deleteCalls.length = 0;
  events.length = 0;
  const box = new FakeNode('div');
  box._isRoot = true;
  boxes.tenantSlidesSorter = box;
  ctx.renderTenantSlidesSorter();
  const grid = box.children.find(child => child.classList.contains('ge-sorter-grid'));
  assert.ok(grid, 'the sorter grid is rendered');
  layout(grid);
  return { box, grid };
}

const cellFor = (grid, id) => grid.children.find(child =>
  child.classList.contains('ge-sorter-cell') && child.dataset.slideId === id);
const cardOf = cell => (cell ? cell.children.find(child => child.classList.contains('ge-sorter-card')) : null);
const addCellOf = grid => grid.children.find(child => child.classList.contains('ge-sorter-add-cell'));
const placeholderOf = grid => grid.children.find(child => child.classList.contains('ge-sorter-placeholder')) || null;
const orderOf = grid => grid.children
  .filter(child => child.classList.contains('ge-sorter-cell') && !child.classList.contains('ge-sorter-add-cell'))
  .map(child => child.dataset.slideId);

function dragStart(card) {
  card.ondragstart({ dataTransfer: { effectAllowed: '', setData() {}, setDragImage() {} }, clientX: 0, clientY: 0 });
}

function dragOver(grid, cell, clientX) {
  grid.ondragover({
    preventDefault() {},
    dataTransfer: { dropEffect: '' },
    target: cardOf(cell) || cell,
    clientX,
    clientY: cell._rect.top + cell._rect.height / 2,
  });
}

function dropOn(grid, cell, clientX) {
  grid.ondrop({
    preventDefault() {},
    dataTransfer: { dropEffect: '' },
    target: cell ? (cardOf(cell) || cell) : grid,
    clientX,
    clientY: cell && cell._rect ? cell._rect.top + cell._rect.height / 2 : 0,
  });
}

{
  const { grid } = setup(['a', 'b', 'c', 'd', 'e']);
  const cardA = cardOf(cellFor(grid, 'a'));
  const cardB = cardOf(cellFor(grid, 'b'));
  dragStart(cardB);
  assert.ok(cellFor(grid, 'b').classList.contains('is-dragging-source'), 'the source leaves the flow');
  const homeGap = placeholderOf(grid);
  assert.ok(homeGap && homeGap.dataset.slotKey === 'home', 'the gap takes the card own slot at drag start');
  assert.equal(grid.children.indexOf(homeGap), grid.children.indexOf(cellFor(grid, 'b')) - 1);

  const cellD = cellFor(grid, 'd');
  dragOver(grid, cellD, cellD._rect.left + 10);
  const placeholder = placeholderOf(grid);
  assert.ok(placeholder, 'a landing gap appears under the pointer');
  assert.equal(placeholder.dataset.slotKey, 'before:e');
  assert.equal(grid.children.indexOf(placeholder), grid.children.indexOf(cellD) + 1,
    'the gap sits on the side the pointer indicates');

  dropOn(grid, cellD, cellD._rect.left + 10);
  assert.deepEqual(orderOf(grid), ['a', 'c', 'd', 'b', 'e']);
  assert.equal(moves.length, 1);
  assert.equal(moves[0].from, 1);
  assert.equal(moves[0].to, 3);
  assert.equal(moves[0].suppressed, true, 'the drop suppresses the sorter rebuild');
  assert.equal(placeholderOf(grid), null, 'the gap is removed on drop');
  assert.equal(cellFor(grid, 'b').classList.contains('is-dragging-source'), false);
  assert.equal(cardOf(cellFor(grid, 'b')), cardB, 'the same card node survives the drop');
  assert.equal(cardOf(cellFor(grid, 'a')), cardA, 'untouched cards are the same nodes too');
  assert.equal(cardA.querySelector('.ge-thumb-canvas').dataset.filled, '1', 'thumbnails stay painted');
  assert.deepEqual(
    grid.children.filter(child => child.classList.contains('ge-sorter-cell')
      && !child.classList.contains('ge-sorter-add-cell')).map(child => child.dataset.sorterIndex),
    ['0', '1', '2', '3', '4']
  );
}

{
  const { grid } = setup(['a', 'b', 'c', 'd', 'e']);
  dragStart(cardOf(cellFor(grid, 'd')));
  const cellB = cellFor(grid, 'b');
  dragOver(grid, cellB, cellB._rect.right - 10);
  const placeholder = placeholderOf(grid);
  assert.ok(placeholder);
  assert.equal(grid.children.indexOf(placeholder), grid.children.indexOf(cellB) - 1);
  dropOn(grid, cellB, cellB._rect.right - 10);
  assert.deepEqual(orderOf(grid), ['a', 'd', 'b', 'c', 'e']);
  assert.equal(moves[0].from, 3);
  assert.equal(moves[0].to, 1);
}

// Dragging back over the card's own slot restores the home gap instead of
// sticking on the slot the pointer just left.
{
  const { grid } = setup(['a', 'b', 'c', 'd', 'e']);
  const cellB = cellFor(grid, 'b');
  dragStart(cardOf(cellB));
  const cellD = cellFor(grid, 'd');
  dragOver(grid, cellD, cellD._rect.left + 10);
  assert.equal(placeholderOf(grid).dataset.slotKey, 'before:e');
  const cellC = cellFor(grid, 'c');
  dragOver(grid, cellC, cellC._rect.right - 10);
  assert.equal(placeholderOf(grid).dataset.slotKey, 'home', 'the gap comes back to the card own slot');
  assert.equal(grid.children.indexOf(placeholderOf(grid)), grid.children.indexOf(cellB) - 1);
  dropOn(grid, cellC, cellC._rect.right - 10);
  assert.equal(moves.length, 0, 'returning home is not a move');
  assert.deepEqual(orderOf(grid), ['a', 'b', 'c', 'd', 'e']);
}

{
  const { grid } = setup(['a', 'b', 'c']);
  dragStart(cardOf(cellFor(grid, 'c')));
  const cellB = cellFor(grid, 'b');
  dragOver(grid, cellB, cellB._rect.left + 10);
  assert.equal(placeholderOf(grid).dataset.slotKey, 'home',
    'the gap stays home when the slide would land where it already is');
  dropOn(grid, cellB, cellB._rect.left + 10);
  assert.equal(moves.length, 0);
  assert.deepEqual(orderOf(grid), ['a', 'b', 'c']);
}

{
  const { grid } = setup(['a', 'b', 'c']);
  dragStart(cardOf(cellFor(grid, 'a')));
  const addCell = addCellOf(grid);
  grid.ondragover({ preventDefault() {}, dataTransfer: { dropEffect: '' }, target: addCell, clientX: 5 });
  const placeholder = placeholderOf(grid);
  assert.ok(placeholder);
  assert.equal(grid.children.indexOf(placeholder), grid.children.indexOf(addCell) - 1,
    'the gap waits before the add cell');
  grid.ondrop({ preventDefault() {}, dataTransfer: { dropEffect: '' }, target: addCell, clientX: 5 });
  assert.deepEqual(orderOf(grid), ['b', 'c', 'a']);
  assert.equal(moves[0].from, 0);
  assert.equal(moves[0].to, 2);
}

// Chromium suppresses the native drop when the preview reflowed the grid under
// a resting pointer; releasing inside the grid must still commit the slot.
{
  const { grid } = setup(['a', 'b', 'c', 'd', 'e']);
  documentStub.elementFromPoint = () => grid;
  const cardB = cardOf(cellFor(grid, 'b'));
  dragStart(cardB);
  const cellD = cellFor(grid, 'd');
  dragOver(grid, cellD, cellD._rect.left + 10);
  grid.ondragleave();
  cardB.ondragend({ clientX: cellD._rect.left + 10, clientY: cellD._rect.top + cellD._rect.height / 2 });
  assert.deepEqual(orderOf(grid), ['a', 'c', 'd', 'b', 'e']);
  assert.equal(moves.length, 1);
  assert.equal(moves[0].from, 1);
  assert.equal(moves[0].to, 3);
  documentStub.elementFromPoint = () => null;
}

// A release outside the grid is a cancel, not a move.
{
  const { grid } = setup(['a', 'b', 'c', 'd', 'e']);
  documentStub.elementFromPoint = () => null;
  const cardB = cardOf(cellFor(grid, 'b'));
  dragStart(cardB);
  const cellD = cellFor(grid, 'd');
  dragOver(grid, cellD, cellD._rect.left + 10);
  grid.ondragleave();
  cardB.ondragend({ clientX: 5, clientY: 5 });
  assert.equal(moves.length, 0);
  assert.deepEqual(orderOf(grid), ['a', 'b', 'c', 'd', 'e']);
  assert.equal(placeholderOf(grid), null);
}

// An Escape cancel ends the drag with no release dragleave; dragend must not
// turn that cancel into a move.
{
  const { grid } = setup(['a', 'b', 'c', 'd', 'e']);
  documentStub.elementFromPoint = () => grid;
  const cardB = cardOf(cellFor(grid, 'b'));
  dragStart(cardB);
  const cellD = cellFor(grid, 'd');
  dragOver(grid, cellD, cellD._rect.left + 10);
  cardB.ondragend({ clientX: cellD._rect.left + 10, clientY: cellD._rect.top + cellD._rect.height / 2 });
  assert.equal(moves.length, 0, 'an Escape cancel never commits the previewed slot');
  assert.deepEqual(orderOf(grid), ['a', 'b', 'c', 'd', 'e']);
  assert.equal(placeholderOf(grid), null);
  documentStub.elementFromPoint = () => null;
}

{
  const { grid } = setup(['a', 'b', 'c']);
  const cardA = cardOf(cellFor(grid, 'a'));
  dragStart(cardA);
  const cellC = cellFor(grid, 'c');
  dragOver(grid, cellC, cellC._rect.left + 10);
  assert.ok(placeholderOf(grid));
  cardA.ondragend();
  assert.equal(placeholderOf(grid), null, 'a cancelled drag removes the gap');
  assert.equal(cellFor(grid, 'a').classList.contains('is-dragging-source'), false);
  assert.deepEqual(orderOf(grid), ['a', 'b', 'c']);
  assert.equal(moves.length, 0);
}

// The + sits on its card's inline-start edge: in RTL that gap is the space
// BEFORE that card, so the new slide belongs at the card's own index. In LTR
// the same edge is the gap after it, so the index moves one further.
{
  const { grid } = setup(['a', 'b', 'c']);
  const insertOf = cell => cell.querySelector('.ge-sorter-insert');
  insertOf(cellFor(grid, 'b')).onclick({ stopPropagation() {} });
  assert.deepEqual(insertCalls, [1], 'RTL + inserts before the card it belongs to');
  insertCalls.length = 0;
  insertOf(cellFor(grid, 'a')).onclick({ stopPropagation() {} });
  assert.deepEqual(insertCalls, [0], 'RTL + on the first card inserts at the start');
}

{
  documentStub.dir = 'ltr';
  ctx.getComputedStyle = () => ({ direction: 'ltr' });
  const { grid } = setup(['a', 'b', 'c']);
  cellFor(grid, 'b').querySelector('.ge-sorter-insert').onclick({ stopPropagation() {} });
  assert.deepEqual(insertCalls, [2], 'LTR + inserts after the card it belongs to');
  documentStub.dir = 'rtl';
  ctx.getComputedStyle = () => ({ direction: 'rtl' });
}

// Every card can delete itself, and the last slide keeps the existing guard.
{
  const { grid } = setup(['a', 'b', 'c']);
  const cellB = cellFor(grid, 'b');
  const remove = cellB.querySelector('.ge-sorter-delete');
  assert.ok(remove, 'every sorter card carries a delete action');
  assert.equal(remove.textContent, 'حذف', 'the delete action is a word, not an icon');
  remove.onclick({ stopPropagation() {} });
  assert.deepEqual(deleteCalls, [1], 'delete addresses the card own live index');
  assert.equal(events.length, 0, 'deleting does not select or switch the view');
}

{
  const { grid } = setup(['only']);
  assert.equal(cellFor(grid, 'only').querySelector('.ge-sorter-delete'), null,
    'the last slide cannot be deleted');
}

// Double-click opens the editor on the clicked card: the selection is applied
// immediately, and the reveal scroll runs only after the editor has layout.
{
  const { grid } = setup(['a', 'b', 'c', 'd']);
  cardOf(cellFor(grid, 'c')).ondblclick();
  assert.deepEqual(events, ['view:edit', 'select:2:quiet', 'select:2:scroll'],
    'the editor opens on the clicked slide after the view is laid out');
  assert.equal(ctx.activeSlideIndex, 2);
}

console.log('Sorter harness passed: landing gap, RTL side math, in-place reorder, cancelled drag, '
  + 'direction-aware insert, sorter delete, editor jump.');
