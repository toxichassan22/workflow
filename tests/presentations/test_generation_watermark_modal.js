const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(process.cwd(), 'assets/js/13-visual/03_tenant_slide_generation.js'), 'utf8');
const start = source.indexOf('    function showGenerationNoticeAboveModals(');
const end = source.indexOf('    // t14-05:', start);
assert.ok(start >= 0 && end > start, 'watermark modal functions are missing');

const notices = [];
const timers = [];
let settingsOpened = 0;
let settingsPageShown = 0;
let scrolled = false;
let focused = false;
let lastModal = null;

function makeModal() {
  const buttons = {};
  return {
    id: '',
    style: {},
    parentNode: null,
    _buttons: buttons,
    get innerHTML() { return this._html || ''; },
    set innerHTML(value) {
      this._html = value;
      for (const match of value.matchAll(/id="([^"]+)"/g)) {
        buttons[match[1]] = buttons[match[1]] || { id: match[1], onclick: null };
      }
    },
    querySelector(selector) {
      return selector.startsWith('#') ? buttons[selector.slice(1)] || null : null;
    },
  };
}

const context = {
  console,
  Promise,
  String,
  setTimeout(fn, ms) { timers.push(ms); return timers.length; },
  tenantBranding: { watermark_path: '/tenant-assets/t/watermark' },
  hasPermission: () => true,
  WFT: (key, fallback) => fallback,
  toast: message => notices.push(message),
  api: async () => ({ success: false }),
  openTenantSettings: async () => { settingsOpened += 1; },
  showTenantPage: () => { settingsPageShown += 1; },
  document: {
    createElement: () => makeModal(),
    body: {
      appendChild(modal) {
        modal.parentNode = { removeChild() { modal.parentNode = null; } };
        lastModal = modal;
      },
    },
    getElementById(id) {
      if (id === 'toast') return { style: {}, innerHTML: '' };
      if (id === 'settingsWatermarkPreview') return { scrollIntoView() { scrolled = true; } };
      if (id === 'settingsWatermarkUploadButton') return { focus() { focused = true; } };
      return null;
    },
  },
};

vm.createContext(context);
vm.runInContext(source.slice(start, end), context);

async function chooseExistingWatermarkAddsIt() {
  context.tenantBranding = { watermark_path: '/tenant-assets/t/watermark' };
  const answer = context.askGenerationWatermarkPreference();
  assert.match(lastModal.innerHTML, /هل تريد إضافة العلامة المائية/);
  lastModal._buttons.genWatermarkAddBtn.onclick();
  assert.equal(await answer, true);
}

async function skippingAnAvailableWatermarkShowsTheReminder() {
  notices.length = 0;
  context.tenantBranding = { watermark_path: '/tenant-assets/t/watermark' };
  const answer = context.askGenerationWatermarkPreference();
  lastModal._buttons.genWatermarkWithoutBtn.onclick();
  assert.equal(await answer, false);
  assert.match(notices[0], /لم تُضف علامة مائية/);
}

async function missingWatermarkSendsTheAdminToSettings() {
  context.tenantBranding = { watermark_path: '' };
  const answer = context.askGenerationWatermarkPreference();
  assert.match(lastModal.innerHTML, /لا توجد علامة مائية مرفوعة/);
  assert.ok(lastModal._buttons.genWatermarkAddBtn);
  lastModal._buttons.genWatermarkAddBtn.onclick();
  assert.equal(await answer, null);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(settingsOpened, 1);
  assert.equal(scrolled, true);
  assert.equal(focused, true);
}

async function missingWatermarkWithoutPermissionOnlyContinues() {
  context.tenantBranding = {};
  context.hasPermission = () => false;
  const answer = context.askGenerationWatermarkPreference();
  assert.equal(lastModal._buttons.genWatermarkAddBtn, undefined);
  assert.match(lastModal.innerHTML, /يضيفها مدير الشركة/);
  lastModal._buttons.genWatermarkWithoutBtn.onclick();
  assert.equal(await answer, false);
  assert.equal(settingsOpened, 1);
}

async function cancelLeavesGenerationClosed() {
  context.tenantBranding = { watermark_path: '/tenant-assets/t/watermark' };
  const answer = context.askGenerationWatermarkPreference();
  lastModal._buttons.genWatermarkCancelBtn.onclick();
  assert.equal(await answer, null);
  assert.equal(settingsPageShown, 0);
}

(async () => {
  await chooseExistingWatermarkAddsIt();
  await skippingAnAvailableWatermarkShowsTheReminder();
  await missingWatermarkSendsTheAdminToSettings();
  await missingWatermarkWithoutPermissionOnlyContinues();
  await cancelLeavesGenerationClosed();
  console.log('Generation watermark modal harness passed: add, skip, missing-asset, no-permission and cancel paths.');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
