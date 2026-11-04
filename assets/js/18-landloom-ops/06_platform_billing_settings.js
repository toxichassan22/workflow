/* 18-landloom-ops/06_platform_billing_settings.js — USD/SAR FX rate & recharge rejection reasons.
   Shared global scope, classic scripts in order. Strictly NO emojis or icon glyphs. */

// ── USD/SAR rate: manual override or provider-tracked auto mode ──────
async function llLoadFxRate() {
  const input = document.getElementById('adminFxRate');
  if (!input) return;
  const data = await api('GET', '/api/admin/fx-rate').catch(() => null);
  const fx = (data && data.fx) || {};
  if (fx.rate != null) input.value = fx.rate;
  const info = document.getElementById('adminFxInfo');
  if (info) {
    const src = ({ manual: 'يدوي', auto: 'تلقائي', env: 'من إعدادات الخادم', default: 'افتراضي' })[fx.source] || fx.source || '';
    info.textContent = (fx.rate != null ? '1 USD = ' + llMoney(fx.rate) + ' SAR' : '') +
      (src ? WFT('admin.fx_source', ' — المصدر: {src}', { src: wfTr(src) }) : '') +
      (fx.updated_at ? ' — ' + String(fx.updated_at).slice(0, 16).replace('T', ' ') : '');
  }
}

async function adminSaveFxRate(event, auto) {
  if (event) event.preventDefault();
  let payload;
  if (auto) {
    payload = { mode: 'auto' };
  } else {
    const rate = parseFloat((document.getElementById('adminFxRate') || {}).value);
    if (!Number.isFinite(rate) || rate <= 0) { toast(WFT('fx.invalid_rate', 'أدخل سعرًا صالحًا')); return; }
    payload = { mode: 'manual', rate: rate };
  }
  const res = await api('PUT', '/api/admin/fx-rate', payload).catch(e => e);
  if (res && res.success) {
    toast(WFT('fx.rate_updated', 'تم تحديث سعر الصرف'));
  } else {
    toast((res && res.error) || 'تعذر تحديث سعر الصرف');
  }
  await llLoadFxRate();
}

// ── Recharge rejection reasons (platform settings) ────────────────────
let llRejectionReasons = [];
let llEditingReasonIndex = -1;

async function llLoadRejectionReasons() {
  const list = document.getElementById('adminRejectionReasonsList');
  if (!list) return;
  const data = await api('GET', '/api/admin/settings/rejection-reasons').catch(() => null);
  if (!data || !data.success) {
    list.innerHTML = '<p class="tenant-hint">' + WFT('recharge.reasons_load_failed', 'تعذر تحميل أسباب الرفض.') + '</p>';
    return;
  }
  llRejectionReasons = (data.reasons || []).slice();
  llRenderRejectionReasons();
}

function llRenderRejectionReasons() {
  const list = document.getElementById('adminRejectionReasonsList');
  if (!list) return;
  if (!llRejectionReasons.length) {
    list.innerHTML = '<p class="tenant-hint">' + WFT('recharge.reasons_empty', 'لا توجد أسباب مسجلة.') + '</p>';
    return;
  }
  list.innerHTML = llRejectionReasons.map(function (reason, index) {
    return '<div class="tenant-presentation-card" style="margin-bottom:8px"><div><h3>' + llEscape(reason) + '</h3></div>' +
      '<div class="tenant-actions">' +
      '<button type="button" class="btn small ghost" onclick="adminEditRejectionReason(' + index + ')">' +
      llEscape(WFT('common.edit', 'تعديل')) + '</button>' +
      '<button type="button" class="btn small danger" onclick="adminDeleteRejectionReason(' + index + ')">' +
      llEscape(WFT('common.delete', 'حذف')) + '</button>' +
      '</div></div>';
  }).join('');
}

async function llPersistRejectionReasons(toastMsg) {
  const res = await api('PUT', '/api/admin/settings/rejection-reasons', { reasons: llRejectionReasons }).catch(e => e);
  if (!res || !res.success) {
    toast((res && res.error) || WFT('recharge.reasons_save_failed', 'تعذر حفظ الأسباب'));
    await llLoadRejectionReasons();
    return;
  }
  toast(toastMsg);
  adminCancelRejectionReasonEdit();
  llRenderRejectionReasons();
}

async function adminSubmitRejectionReason(event) {
  event.preventDefault();
  const input = document.getElementById('adminRejectionReasonInput');
  const value = ((input && input.value) || '').trim();
  if (!value) return;
  const dupe = llRejectionReasons.some(function (r, i) { return r === value && i !== llEditingReasonIndex; });
  if (dupe) { toast(WFT('recharge.reason_exists', 'السبب مسجل بالفعل')); return; }
  if (llEditingReasonIndex < 0 && llRejectionReasons.length >= 30) {
    toast(WFT('recharge.reasons_limit', 'الحد الأقصى 30 سببًا'));
    return;
  }
  if (llEditingReasonIndex >= 0) llRejectionReasons[llEditingReasonIndex] = value;
  else llRejectionReasons.push(value);
  await llPersistRejectionReasons(WFT('recharge.reasons_saved', 'تم حفظ أسباب الرفض'));
}

function adminEditRejectionReason(index) {
  const reason = llRejectionReasons[index];
  if (reason == null) return;
  llEditingReasonIndex = index;
  const input = document.getElementById('adminRejectionReasonInput');
  input.value = reason;
  document.getElementById('adminRejectionReasonSubmit').textContent = WFT('admin.rejection_reason_update', 'تحديث السبب');
  document.getElementById('adminRejectionReasonCancel').style.display = '';
  input.focus();
}

function adminCancelRejectionReasonEdit() {
  llEditingReasonIndex = -1;
  const input = document.getElementById('adminRejectionReasonInput');
  if (input) input.value = '';
  const submit = document.getElementById('adminRejectionReasonSubmit');
  if (submit) submit.textContent = WFT('admin.rejection_reason_add', 'إضافة سبب');
  const cancel = document.getElementById('adminRejectionReasonCancel');
  if (cancel) cancel.style.display = 'none';
}

async function adminDeleteRejectionReason(index) {
  const reason = llRejectionReasons[index];
  if (reason == null) return;
  if (!confirm(WFT('recharge.reason_delete_confirm', 'سيتم حذف سبب الرفض «{reason}». هل تريد المتابعة؟', { reason: reason }))) return;
  llRejectionReasons.splice(index, 1);
  await llPersistRejectionReasons(WFT('recharge.reason_deleted', 'تم حذف السبب'));
}
