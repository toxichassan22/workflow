/* 18-landloom-ops/03_legal_content.js — desk editor for the public legal
   pages. The effective copy is whatever /terms and /privacy serve right now
   (the server splices any saved override into the baked file), so loading the
   public page through a DOMParser hands the editor the live text for free —
   one endpoint (PUT) and no separate GET path to keep in sync.
   Shared global scope, classic scripts in order. */

    async function adminLoadLegalDoc() {
      const arBox = document.getElementById('adminLegalAr');
      const enBox = document.getElementById('adminLegalEn');
      if (!arBox || !enBox) return;
      const doc = (document.getElementById('adminLegalDoc') || {}).value || 'terms';
      arBox.value = WFT('common.loading', 'جاري التحميل...');
      enBox.value = WFT('common.loading', 'جاري التحميل...');
      try {
        const res = await fetch('/' + doc, { headers: { 'Accept': 'text/html' } });
        if (!res.ok) throw new Error('http ' + res.status);
        const parsed = new DOMParser().parseFromString(await res.text(), 'text/html');
        const strip = (el) => el ? el.innerHTML.replace(/<!--[\s\S]*?-->/g, '').trim() : '';
        arBox.value = strip(parsed.querySelector('[data-legal-ar]'));
        enBox.value = strip(parsed.querySelector('[data-legal-en]'));
      } catch (e) {
        arBox.value = '';
        enBox.value = '';
        toast(WFT('admin.legal_load_failed', 'تعذر تحميل المحتوى الحالي'));
      }
    }

    function adminLegalSelectDoc() {
      adminLoadLegalDoc();
    }

    async function adminSaveLegalDoc() {
      const doc = (document.getElementById('adminLegalDoc') || {}).value || 'terms';
      const ar = (document.getElementById('adminLegalAr') || {}).value || '';
      const en = (document.getElementById('adminLegalEn') || {}).value || '';
      if (!ar.trim() || !en.trim()) {
        toast(WFT('admin.legal_empty', 'المحتوى العربي والإنجليزي مطلوبان'));
        return;
      }
      const res = await api('PUT', '/api/admin/legal/' + doc, { ar: ar, en: en }).catch(e => e);
      if (!res || !res.success) {
        toast((res && res.error) || WFT('admin.legal_save_failed', 'تعذر حفظ المحتوى'));
        return;
      }
      toast(WFT('admin.legal_saved', 'تم حفظ المحتوى'));
    }
