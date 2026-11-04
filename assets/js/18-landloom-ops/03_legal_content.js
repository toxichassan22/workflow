/* 18-landloom-ops/03_legal_content.js — desk editor for the public pages
   (About Us, Terms of Use, Privacy Policy). Supports editing Arabic/English
   HTML body, publication/updated date, and notice phrases.
   Shared global scope, classic scripts in order. */

async function adminLoadLegalDoc() {
  const arBox = document.getElementById('adminLegalAr');
  const enBox = document.getElementById('adminLegalEn');
  const dateArBox = document.getElementById('adminLegalDateAr');
  const dateEnBox = document.getElementById('adminLegalDateEn');
  const noticeArBox = document.getElementById('adminLegalNoticeAr');
  const noticeEnBox = document.getElementById('adminLegalNoticeEn');
  if (!arBox || !enBox) return;

  const doc = (document.getElementById('adminLegalDoc') || {}).value || 'terms';
  arBox.value = WFT('common.loading', 'جاري التحميل...');
  enBox.value = WFT('common.loading', 'جاري التحميل...');
  if (dateArBox) dateArBox.value = '';
  if (dateEnBox) dateEnBox.value = '';
  if (noticeArBox) noticeArBox.value = '';
  if (noticeEnBox) noticeEnBox.value = '';

  try {
    const res = await api('GET', '/api/admin/legal/' + doc);
    if (res && res.success && res.document) {
      const d = res.document;
      arBox.value = d.ar || '';
      enBox.value = d.en || '';
      if (dateArBox) dateArBox.value = d.date_ar || '';
      if (dateEnBox) dateEnBox.value = d.date_en || '';
      if (noticeArBox) noticeArBox.value = d.notice_ar || '';
      if (noticeEnBox) noticeEnBox.value = d.notice_en || '';
      return;
    }
    throw new Error((res && res.error) || 'Failed to load document');
  } catch (e) {
    try {
      const pageRes = await fetch('/' + doc, { headers: { 'Accept': 'text/html' } });
      if (!pageRes.ok) throw new Error('http ' + pageRes.status);
      const parsed = new DOMParser().parseFromString(await pageRes.text(), 'text/html');
      const strip = (el) => el ? el.innerHTML.replace(/<!--[\s\S]*?-->/g, '').trim() : '';
      arBox.value = strip(parsed.querySelector('[data-legal-ar]'));
      enBox.value = strip(parsed.querySelector('[data-legal-en]'));
      if (dateArBox) dateArBox.value = strip(parsed.querySelector('[data-legal-date-ar]'));
      if (dateEnBox) dateEnBox.value = strip(parsed.querySelector('[data-legal-date-en]'));
      if (noticeArBox) noticeArBox.value = strip(parsed.querySelector('[data-legal-notice-ar]'));
      if (noticeEnBox) noticeEnBox.value = strip(parsed.querySelector('[data-legal-notice-en]'));
    } catch (err) {
      arBox.value = '';
      enBox.value = '';
      toast(WFT('admin.legal_load_failed', 'تعذر تحميل الصفحة المحددة'));
    }
  }
}

function adminLegalSelectDoc() {
  adminLoadLegalDoc();
}

async function adminSaveLegalDoc() {
  const doc = (document.getElementById('adminLegalDoc') || {}).value || 'terms';
  const ar = (document.getElementById('adminLegalAr') || {}).value || '';
  const en = (document.getElementById('adminLegalEn') || {}).value || '';
  const dateAr = (document.getElementById('adminLegalDateAr') || {}).value || '';
  const dateEn = (document.getElementById('adminLegalDateEn') || {}).value || '';
  const noticeAr = (document.getElementById('adminLegalNoticeAr') || {}).value || '';
  const noticeEn = (document.getElementById('adminLegalNoticeEn') || {}).value || '';

  if (!ar.trim() || !en.trim()) {
    toast(WFT('admin.legal_empty', 'المحتوى العربي والإنجليزي مطلوبان'));
    return;
  }

  const payload = {
    ar: ar,
    en: en,
    date_ar: dateAr,
    date_en: dateEn,
    notice_ar: noticeAr,
    notice_en: noticeEn
  };

  const res = await api('PUT', '/api/admin/legal/' + doc, payload).catch(e => e);
  if (!res || !res.success) {
    toast((res && res.error) || WFT('admin.legal_save_failed', 'تعذر حفظ المحتوى والتعديلات'));
    return;
  }
  toast(WFT('admin.legal_saved', 'تم حفظ المحتوى والتعديلات بنجاح'));
}
