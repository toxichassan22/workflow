/* tests/workflow/test_live_collab.js — the CRDT half of live collaboration.
 *
 * The browser turns text edits into Yjs updates; the server never sees the
 * text itself. This harness loads the same vendored Yjs bundle the app ships,
 * applies two concurrent edits, and checks that both clients converge without
 * losing either character.
 *
 * Run from the repo root:  node tests/workflow/test_live_collab.js
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = process.cwd();
const vendor = fs.readFileSync(path.join(root, 'assets/vendor/yjs.min.js'), 'utf8');
const moduleSource = fs.readFileSync(
  path.join(root, 'assets/js/20-live-collab/01_live_collab.js'), 'utf8');

const hostEncoder = new TextEncoder();
const hostDecoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });

const context = {
  console, setTimeout, clearTimeout, btoa, atob,
  window: {},
  __hostEncode: value => Array.from(hostEncoder.encode(value)),
  __hostDecode: bytes => hostDecoder.decode(Uint8Array.from(bytes || [])),
  __hostRandom: length => Array.from(require('node:crypto').randomBytes(length)),
};
vm.createContext(context);
// The bundle runs in its own realm. Its instanceof checks compare against
// that realm's Uint8Array, so the text codec and the random source are
// created inside the realm and only call out to the host for the bytes.
vm.runInContext(`
  globalThis.TextEncoder = class {
    encode(value) {
      const bytes = __hostEncode(value);
      const out = new Uint8Array(bytes.length);
      for (let index = 0; index < bytes.length; index += 1) out[index] = bytes[index];
      return out;
    }
    encodeInto(value, destination) {
      const bytes = __hostEncode(value);
      const count = Math.min(bytes.length, destination.length);
      for (let index = 0; index < count; index += 1) destination[index] = bytes[index];
      return { read: value.length, written: count };
    }
  };
  globalThis.TextDecoder = class {
    decode(bytes) { return __hostDecode(Array.from(bytes || [])); }
  };
  globalThis.crypto = {
    subtle: {},
    getRandomValues(array) {
      const values = __hostRandom(array.length);
      for (let index = 0; index < array.length; index += 1) array[index] = values[index];
      return array;
    },
    randomUUID() {
      const bytes = __hostRandom(16);
      bytes[6] = (bytes[6] & 15) | 64;
      bytes[8] = (bytes[8] & 63) | 128;
      const hex = bytes.map(byte => byte.toString(16).padStart(2, '0')).join('');
      return hex.slice(0, 8) + '-' + hex.slice(8, 12) + '-' + hex.slice(12, 16) + '-'
        + hex.slice(16, 20) + '-' + hex.slice(20);
    }
  };
`, context);
vm.runInContext(vendor, context);
assert.equal(typeof context.Y, 'object', 'the vendored Yjs bundle must expose the Y global');
vm.runInContext(moduleSource, context);

const Y = context.Y;

testRoundTripBytes();
testTextDiff();
testCaretTransform();
testFieldEligibility();
testConcurrentTypingConverges();
console.log('Live collaboration harness passed: bytes, diff, caret, field eligibility,'
  + ' concurrent typing.');

function testRoundTripBytes() {
  const bytes = new Uint8Array([0, 1, 2, 250, 255]);
  const encoded = context.liveCollabBytesToBase64(bytes);
  const decoded = context.liveCollabBase64ToBytes(encoded);
  assert.deepEqual(Array.from(decoded), Array.from(bytes));
}

function testTextDiff() {
  const doc = new Y.Doc();
  const text = doc.getText('field');
  text.insert(0, 'hello');
  assert.equal(context.liveApplyTextDiff(text, 'hello world', 'local'), true);
  assert.equal(text.toString(), 'hello world');
  assert.equal(context.liveApplyTextDiff(text, 'hello', 'local'), true);
  assert.equal(text.toString(), 'hello');
  assert.equal(context.liveApplyTextDiff(text, 'hello', 'local'), false,
    'an unchanged value must not create an update');
  assert.equal(context.liveApplyTextDiff(text, 'أهلاً بالعالم', 'local'), true);
  assert.equal(text.toString(), 'أهلاً بالعالم');
}

function testCaretTransform() {
  assert.equal(context.liveTransformCaretByChange('hello world', 'hello', 8), 5);
  assert.equal(context.liveTransformCaretByChange('hello', 'hello world', 2), 2);
  assert.equal(context.liveTransformCaretByChange('abc', 'aXbc', 2), 3,
    'a caret after an insertion moves with the text');
  assert.equal(context.liveTransformCaretByChange('abc', 'ac', 2), 1,
    'a caret after a deletion moves back');
  assert.equal(context.liveTransformCaretByChange('abc', 'abc', 3), 3);
}

function testFieldEligibility() {
  assert.equal(context.liveCollabFieldEligible({ tagName: 'TEXTAREA', dataset: { key: 'a' } }), true);
  assert.equal(context.liveCollabFieldEligible({ tagName: 'INPUT', type: 'text', dataset: { key: 'a' } }), true);
  assert.equal(context.liveCollabFieldEligible({ tagName: 'INPUT', type: 'hidden', dataset: { key: 'a' } }), false);
  assert.equal(context.liveCollabFieldEligible({ tagName: 'INPUT', type: 'file', dataset: { key: 'a' } }), false);
  assert.equal(context.liveCollabFieldEligible({ tagName: 'SELECT', dataset: { key: 'a' } }), false);
  assert.equal(context.liveCollabFieldEligible({ tagName: 'INPUT', type: 'text', dataset: {} }), false);
  assert.equal(context.liveCollabFieldLocked({ disabled: true }), true);
  assert.equal(context.liveCollabFieldLocked({ disabled: false, readOnly: true }), true);
  assert.equal(context.liveCollabFieldLocked({
    disabled: false,
    readOnly: false,
    closest: () => ({ classList: { contains: name => name === 'section-locked' } }),
  }), true);
  assert.equal(context.liveCollabFieldLocked({
    disabled: false,
    readOnly: false,
    closest: () => ({ classList: { contains: () => false } }),
  }), false);
}

function testConcurrentTypingConverges() {
  const left = new Y.Doc();
  const right = new Y.Doc();
  const leftUpdates = [];
  const rightUpdates = [];
  left.on('update', update => leftUpdates.push(update));
  right.on('update', update => rightUpdates.push(update));
  const leftText = left.getText('field');
  const rightText = right.getText('field');
  leftText.insert(0, 'abc');
  // Both people opened the same saved value, not two independent copies.
  Y.applyUpdate(right, Y.encodeStateAsUpdate(left));
  leftUpdates.length = 0;
  rightUpdates.length = 0;

  // Two people type in the same field before either has heard from the other.
  context.liveApplyTextDiff(leftText, 'aXbc', 'left');
  context.liveApplyTextDiff(rightText, 'abYc', 'right');

  const leftFirst = leftUpdates.slice();
  const rightFirst = rightUpdates.slice();
  leftFirst.forEach(update => Y.applyUpdate(right, update));
  rightFirst.forEach(update => Y.applyUpdate(left, update));

  assert.equal(leftText.toString(), rightText.toString(),
    'both clients must converge on the same text');
  assert.ok(leftText.toString().includes('X') && leftText.toString().includes('Y'),
    'neither concurrent insertion may be lost: ' + leftText.toString());

  leftUpdates.length = 0;
  rightUpdates.length = 0;
  // A deletion on one side and an insertion elsewhere on the other also merge.
  context.liveApplyTextDiff(leftText, leftText.toString().replace('X', ''), 'left');
  context.liveApplyTextDiff(rightText, rightText.toString() + 'Z', 'right');
  const leftTail = leftUpdates.slice();
  const rightTail = rightUpdates.slice();
  leftTail.forEach(update => Y.applyUpdate(right, update));
  rightTail.forEach(update => Y.applyUpdate(left, update));
  assert.equal(leftText.toString(), rightText.toString(),
    'a deletion and an insertion must still converge');
  assert.ok(leftText.toString().endsWith('Z'));
  assert.equal(leftText.toString().includes('X'), false);
}
