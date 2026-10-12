'use strict';
// Run with node tests/test_trusted_device_tokens.js
// Covers the per-account trusted-device token store: the browser used to keep
// ONE token slot, so every OTP verify overwrote the previous account's token
// and the next login fell back to OTP (the "OTP every time" bug).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = ['index.html', 'assets/js/01-nav-auth.js']
  .map(f => fs.readFileSync(path.join(__dirname, '..', '..', f), 'utf8')).join('\n');

const extract = name => {
  const match = new RegExp('^    (?:async )?function ' + name + '\\(', 'm').exec(source);
  assert(match, name);
  const end = source.indexOf('\n    }', match.index);
  return source.slice(match.index, end + 6);
};

const localStorageMock = () => {
  const data = {};
  return {
    getItem: k => (Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
    removeItem: k => { delete data[k]; },
    _data: data,
  };
};

const makeContext = () => {
  const localStorage = localStorageMock();
  const context = vm.createContext({ localStorage, JSON, crypto: require('node:crypto').webcrypto });
  vm.runInContext(
    'const T_DEVICE_ID_KEY = "landloom_device_id";' +
    'const T_TRUSTED_DEVICE_KEY = "landloom_trusted_device_tokens";' +
    'const T_TRUSTED_DEVICE_LEGACY_KEY = "landloom_trusted_device_token";' +
    'let memoryDeviceId = null;' +
    extract('getTrustedDeviceToken') + '\n' +
    extract('storeTrustedDeviceToken') + '\n' +
    extract('getOrCreateDeviceId'),
    context
  );
  return { context, localStorage };
};

// Two accounts keep their own tokens — the ping-pong fix.
{
  const { context } = makeContext();
  context.storeTrustedDeviceToken('admin@landloom.ai', 'tok-admin');
  context.storeTrustedDeviceToken('owner@company.test', 'tok-owner');
  assert.equal(context.getTrustedDeviceToken('admin@landloom.ai'), 'tok-admin');
  assert.equal(context.getTrustedDeviceToken('owner@company.test'), 'tok-owner');
  // Storing again for one account must not evict the other's token.
  context.storeTrustedDeviceToken('owner@company.test', 'tok-owner-2');
  assert.equal(context.getTrustedDeviceToken('admin@landloom.ai'), 'tok-admin');
  assert.equal(context.getTrustedDeviceToken('owner@company.test'), 'tok-owner-2');
}

// Identity keys are normalized (case + surrounding whitespace).
{
  const { context } = makeContext();
  context.storeTrustedDeviceToken('  Admin@Landloom.AI ', 'tok-x');
  assert.equal(context.getTrustedDeviceToken('admin@landloom.ai'), 'tok-x');
  assert.equal(context.getTrustedDeviceToken('ADMIN@LANDLOOM.AI'), 'tok-x');
}

// A pre-map single token is still offered once (graceful upgrade), and any
// real verify removes the legacy key.
{
  const { context, localStorage } = makeContext();
  localStorage.setItem('landloom_trusted_device_token', 'tok-legacy');
  assert.equal(context.getTrustedDeviceToken('admin@landloom.ai'), 'tok-legacy');
  context.storeTrustedDeviceToken('admin@landloom.ai', 'tok-new');
  assert.equal(localStorage.getItem('landloom_trusted_device_token'), null);
  assert.equal(context.getTrustedDeviceToken('admin@landloom.ai'), 'tok-new');
}

// An empty identity or token never writes.
{
  const { context, localStorage } = makeContext();
  context.storeTrustedDeviceToken('', 'tok');
  context.storeTrustedDeviceToken('a@b.c', '');
  context.storeTrustedDeviceToken(null, 'tok');
  assert.equal(localStorage.getItem('landloom_trusted_device_tokens'), null);
  assert.equal(context.getTrustedDeviceToken('a@b.c'), '');
}

// The map is bounded — the oldest identity is evicted past 20 entries.
{
  const { context } = makeContext();
  for (let i = 0; i < 25; i++) context.storeTrustedDeviceToken('u' + i + '@x.t', 'tok-' + i);
  assert.equal(context.getTrustedDeviceToken('u0@x.t'), '');
  assert.equal(context.getTrustedDeviceToken('u4@x.t'), '');
  assert.equal(context.getTrustedDeviceToken('u24@x.t'), 'tok-24');
}

// The device id stays stable across calls even with a dead localStorage —
// the login and the OTP verify inside one page must agree on the same id.
{
  const dead = {
    getItem: () => { throw new Error('blocked'); },
    setItem: () => { throw new Error('blocked'); },
    removeItem: () => { throw new Error('blocked'); },
  };
  const context = vm.createContext({ localStorage: dead, JSON, crypto: require('node:crypto').webcrypto });
  vm.runInContext(
    'const T_DEVICE_ID_KEY = "landloom_device_id"; let memoryDeviceId = null;' +
    extract('getOrCreateDeviceId'),
    context
  );
  const first = context.getOrCreateDeviceId();
  const second = context.getOrCreateDeviceId();
  assert.equal(first, second);
  assert.ok(first.length > 0);
}

console.log('test_trusted_device_tokens: all assertions passed');
