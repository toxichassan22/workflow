/* 18-landloom-ops/03_legal_content.js — desk editor for the public pages
   (About Us, Terms of Use, Privacy Policy). The desk edits sections —
   heading, body and bullet points in Arabic and English — while the stored
   HTML is generated here, so nobody has to type markup. Supports editing the
   publication/updated date and notice phrases as well.
   Shared global scope, classic scripts in order. */

var adminLegalSectionsState = { ar: { title: '', sections: [] }, en: { title: '', sections: [] } };

function legalDecodeEntities(value) {
  return String(value || '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#0*39;|&apos;/gi, "'")
    .replace(/&#(\d+);/g, function (_, code) { return String.fromCharCode(Number(code)); });
}

function legalEscapeText(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function legalPlainText(html) {
  return legalDecodeEntities(
    String(html || '').replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]*>/g, ' ')
  ).replace(/\s+/g, ' ').trim();
}

function legalSectionFromHtml(title, chunk) {
  var bullets = [];
  var withoutLists = String(chunk || '')
    .replace(/<ul\b[^>]*>([\s\S]*?)<\/ul>/gi, function (_, listHtml) {
      var liRe = /<li\b[^>]*>([\s\S]*?)<\/li>/gi;
      var li;
      while ((li = liRe.exec(listHtml))) {
        var text = legalPlainText(li[1]);
        if (text) bullets.push(text);
      }
      return ' ';
    })
    .replace(/<ol\b[^>]*>[\s\S]*?<\/ol>/gi, ' ');
  var paragraphs = [];
  var pRe = /<p\b[^>]*>([\s\S]*?)<\/p>/gi;
  var p;
  while ((p = pRe.exec(withoutLists))) {
    var para = legalPlainText(p[1]);
    if (para) paragraphs.push(para);
  }
  if (!paragraphs.length) {
    var rest = legalPlainText(withoutLists);
    if (rest) paragraphs.push(rest);
  }
  return { title: title, body: paragraphs.join('\n\n'), bullets: bullets };
}

/* Stored HTML -> editable state. One h2 starts a section; its p/ul blocks
   belong to it. The page h1 is carried but not shown. */
function legalDocSections(html) {
  var source = String(html || '').trim();
  var title = '';
  var h1 = source.match(/<h1\b[^>]*>([\s\S]*?)<\/h1>/i);
  if (h1) {
    title = legalPlainText(h1[1]);
    source = source.replace(h1[0], '');
  }
  var headings = [];
  var re = /<h2\b[^>]*>([\s\S]*?)<\/h2>/gi;
  var m;
  while ((m = re.exec(source))) headings.push({ title: legalPlainText(m[1]), start: m.index, end: re.lastIndex });
  var sections = [];
  if (!headings.length) {
    var single = legalSectionFromHtml('', source);
    if (single.body || single.bullets.length) sections.push(single);
    return { title: title, sections: sections };
  }
  if (legalPlainText(source.slice(0, headings[0].start))) {
    sections.push(legalSectionFromHtml('', source.slice(0, headings[0].start)));
  }
  headings.forEach(function (heading, i) {
    var until = i + 1 < headings.length ? headings[i + 1].start : source.length;
    sections.push(legalSectionFromHtml(heading.title, source.slice(heading.end, until)));
  });
  return { title: title, sections: sections };
}

function legalBulletHtml(text) {
  var lead = String(text || '').match(/^([^:]{1,60}):\s*(.+)$/);
  if (lead) {
    return '<strong>' + legalEscapeText(lead[1]) + ':</strong> ' + legalEscapeText(lead[2]);
  }
  return legalEscapeText(text);
}

/* Editable state -> stored HTML. */
function legalDocumentHtml(state) {
  var parts = [];
  var title = String((state && state.title) || '').trim();
  if (title) parts.push('<h1>' + legalEscapeText(title) + '</h1>');
  ((state && state.sections) || []).forEach(function (section) {
    var heading = String((section && section.title) || '').trim();
    if (heading) parts.push('<h2>' + legalEscapeText(heading) + '</h2>');
    String((section && section.body) || '').split(/\n{2,}/).forEach(function (para) {
      para = para.replace(/\s+$/, '').trim();
      if (para) parts.push('<p>' + legalEscapeText(para).replace(/\n/g, '<br>') + '</p>');
    });
    var bullets = ((section && section.bullets) || []).filter(function (bullet) {
      return String(bullet || '').trim() !== '';
    });
    if (bullets.length) {
      parts.push('<ul>');
      bullets.forEach(function (bullet) {
        parts.push('<li>' + legalBulletHtml(String(bullet).trim()) + '</li>');
      });
      parts.push('</ul>');
    }
  });
  return parts.join('\n\n');
}

function legalDocumentIsEmpty(state) {
  var sections = (state && state.sections) || [];
  return !sections.some(function (section) {
    return String((section && section.title) || '').trim() !== ''
      || String((section && section.body) || '').trim() !== ''
      || ((section && section.bullets) || []).some(function (bullet) { return String(bullet || '').trim() !== ''; });
  });
}

function legalEl(tag, className, text) {
  var el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined && text !== null) el.textContent = text;
  return el;
}

/* Column labels follow the column's own language, not the UI language: the
   English side stays English even while the desk UI is Arabic. */
function adminLegalColumnText(key, lang) {
  var dict = lang === 'en' ? window.__WFI18N_EN : window.__WFI18N_AR;
  if (dict && dict[key]) return dict[key];
  return WFT(key, '');
}

function adminLegalEnsureSection(lang, index) {
  var bucket = adminLegalSectionsState[lang] || (adminLegalSectionsState[lang] = { title: '', sections: [] });
  while (bucket.sections.length <= index) bucket.sections.push({ title: '', body: '', bullets: [] });
  return bucket.sections[index];
}

function adminLegalField(lang, index, field, labelText, value, multiline) {
  var wrap = legalEl('div', 'll-legal-field');
  var inputId = 'legal-' + lang + '-' + index + '-' + field;
  var input = document.createElement(multiline ? 'textarea' : 'input');
  if (multiline) input.rows = 3;
  else input.type = 'text';
  input.id = inputId;
  input.setAttribute('data-legal-field', field);
  input.setAttribute('data-lang', lang);
  input.value = value || '';
  var label = legalEl('label', '', labelText);
  label.htmlFor = inputId;
  wrap.appendChild(label);
  wrap.appendChild(input);
  return wrap;
}

function adminLegalBulletRow(lang, index, bulletIndex, value) {
  var row = legalEl('div', 'll-legal-bullet');
  var input = document.createElement('input');
  input.type = 'text';
  input.id = 'legal-' + lang + '-' + index + '-bullet-' + bulletIndex;
  input.setAttribute('data-legal-field', 'bullet');
  input.setAttribute('data-legal-bullet', String(bulletIndex));
  input.setAttribute('data-lang', lang);
  input.setAttribute('aria-label', adminLegalColumnText('admin.legal_bullets', lang) + ' ' + (bulletIndex + 1));
  input.value = value || '';
  var remove = legalEl('button', 'll-legal-bullet-remove', adminLegalColumnText('admin.legal_delete', lang));
  remove.type = 'button';
  remove.setAttribute('data-legal-action', 'remove-bullet');
  remove.setAttribute('data-legal-bullet', String(bulletIndex));
  remove.setAttribute('data-lang', lang);
  row.appendChild(input);
  row.appendChild(remove);
  return row;
}

function adminLegalLangColumn(lang, index) {
  var section = (adminLegalSectionsState[lang].sections || [])[index] || { title: '', body: '', bullets: [] };
  var col = legalEl('div', 'll-legal-col');
  col.setAttribute('data-lang', lang);
  if (lang === 'en') col.setAttribute('dir', 'ltr');
  col.appendChild(legalEl('div', 'll-legal-col-head', adminLegalColumnText(
    lang === 'ar' ? 'admin.legal_lang_ar' : 'admin.legal_lang_en', lang)));
  col.appendChild(adminLegalField(lang, index, 'title', adminLegalColumnText('admin.legal_heading', lang), section.title, false));
  col.appendChild(adminLegalField(lang, index, 'body', adminLegalColumnText('admin.legal_text', lang), section.body, true));
  col.appendChild(legalEl('div', 'll-legal-bullets-label', adminLegalColumnText('admin.legal_bullets', lang)));
  var list = legalEl('div', 'll-legal-bullets');
  (section.bullets || []).forEach(function (bullet, bulletIndex) {
    list.appendChild(adminLegalBulletRow(lang, index, bulletIndex, bullet));
  });
  col.appendChild(list);
  var add = legalEl('button', 'btn ghost small ll-legal-add-bullet', adminLegalColumnText('admin.legal_add_bullet', lang));
  add.type = 'button';
  add.setAttribute('data-legal-action', 'add-bullet');
  add.setAttribute('data-legal-bullet-lang', lang);
  col.appendChild(add);
  return col;
}

function adminLegalSectionCard(index) {
  var card = legalEl('article', 'll-legal-section');
  card.setAttribute('data-index', String(index));
  var head = legalEl('div', 'll-legal-section-head');
  head.appendChild(legalEl('span', 'll-legal-section-chip', WFT('admin.legal_section', 'القسم {n}', { n: index + 1 })));
  var actions = legalEl('div', 'll-legal-section-actions');
  [['up', WFT('admin.legal_move_up', 'أعلى')],
   ['down', WFT('admin.legal_move_down', 'أسفل')],
   ['remove', WFT('admin.legal_delete', 'حذف')]].forEach(function (action) {
    var btn = legalEl('button', action[0] === 'remove' ? 'btn ghost small ll-legal-delete' : 'btn ghost small', action[1]);
    btn.type = 'button';
    btn.setAttribute('data-legal-action', action[0]);
    actions.appendChild(btn);
  });
  head.appendChild(actions);
  card.appendChild(head);
  var cols = legalEl('div', 'll-legal-cols');
  cols.appendChild(adminLegalLangColumn('ar', index));
  cols.appendChild(adminLegalLangColumn('en', index));
  card.appendChild(cols);
  return card;
}

function adminRenderLegalSections() {
  var host = document.getElementById('adminLegalSections');
  if (!host) return;
  host.textContent = '';
  var count = Math.max(
    (adminLegalSectionsState.ar.sections || []).length,
    (adminLegalSectionsState.en.sections || []).length
  );
  if (!count) {
    host.appendChild(legalEl('div', 'll-legal-empty', WFT('admin.legal_no_sections', 'لا توجد أقسام في هذه الصفحة.')));
    return;
  }
  for (var i = 0; i < count; i++) host.appendChild(adminLegalSectionCard(i));
}

function adminAddLegalSection() {
  var count = Math.max(
    (adminLegalSectionsState.ar.sections || []).length,
    (adminLegalSectionsState.en.sections || []).length
  );
  adminLegalEnsureSection('ar', count);
  adminLegalEnsureSection('en', count);
  adminRenderLegalSections();
  var card = document.querySelector('#adminLegalSections .ll-legal-section[data-index="' + count + '"]');
  var first = card && card.querySelector('input[data-legal-field="title"]');
  if (first) first.focus();
}

function adminMoveLegalSection(index, delta) {
  var target = index + delta;
  var list = adminLegalSectionsState.ar.sections || [];
  var other = adminLegalSectionsState.en.sections || [];
  var count = Math.max(list.length, other.length);
  if (target < 0 || target >= count) return;
  ['ar', 'en'].forEach(function (lang) {
    var sections = adminLegalSectionsState[lang].sections;
    if (index < sections.length && target < sections.length) {
      var moved = sections.splice(index, 1)[0];
      sections.splice(target, 0, moved);
    }
  });
  adminRenderLegalSections();
}

function adminRemoveLegalSection(index) {
  ['ar', 'en'].forEach(function (lang) {
    var sections = adminLegalSectionsState[lang].sections;
    if (index < sections.length) sections.splice(index, 1);
  });
  adminRenderLegalSections();
}

function adminAddLegalBullet(lang, index) {
  var section = adminLegalEnsureSection(lang, index);
  section.bullets.push('');
  adminRenderLegalSections();
  var rows = document.querySelectorAll('#adminLegalSections .ll-legal-section[data-index="' + index + '"] .ll-legal-col[data-lang="' + lang + '"] .ll-legal-bullet input');
  var last = rows[rows.length - 1];
  if (last) last.focus();
}

function adminRemoveLegalBullet(lang, index, bulletIndex) {
  var section = adminLegalEnsureSection(lang, index);
  section.bullets.splice(bulletIndex, 1);
  adminRenderLegalSections();
}

document.addEventListener('input', function (event) {
  var target = event.target;
  var field = target && target.getAttribute && target.getAttribute('data-legal-field');
  if (!field) return;
  var card = target.closest('.ll-legal-section');
  if (!card) return;
  var lang = target.getAttribute('data-lang');
  var index = Number(card.getAttribute('data-index'));
  var section = adminLegalEnsureSection(lang, index);
  if (field === 'bullet') {
    section.bullets[Number(target.getAttribute('data-legal-bullet'))] = target.value;
    return;
  }
  section[field] = target.value;
});

document.addEventListener('click', function (event) {
  var button = event.target.closest && event.target.closest('[data-legal-action]');
  if (!button) return;
  var action = button.getAttribute('data-legal-action');
  var card = button.closest('.ll-legal-section');
  var index = card ? Number(card.getAttribute('data-index')) : -1;
  if (action === 'add-bullet') {
    adminAddLegalBullet(button.getAttribute('data-legal-bullet-lang'), index);
    return;
  }
  if (index < 0) return;
  if (action === 'up') adminMoveLegalSection(index, -1);
  if (action === 'down') adminMoveLegalSection(index, 1);
  if (action === 'remove') adminRemoveLegalSection(index);
  if (action === 'remove-bullet') {
    adminRemoveLegalBullet(button.getAttribute('data-lang'), index, Number(button.getAttribute('data-legal-bullet')));
  }
});

function adminLegalFillMeta() {
  var doc = (document.getElementById('adminLegalDoc') || {}).value || 'terms';
  var preview = document.getElementById('adminLegalPreview');
  if (preview) preview.setAttribute('href', '/' + doc);
}

async function adminLoadLegalDoc() {
  const host = document.getElementById('adminLegalSections');
  if (!host) return;
  const dateArBox = document.getElementById('adminLegalDateAr');
  const dateEnBox = document.getElementById('adminLegalDateEn');
  const noticeArBox = document.getElementById('adminLegalNoticeAr');
  const noticeEnBox = document.getElementById('adminLegalNoticeEn');

  adminLegalFillMeta();
  host.textContent = '';
  host.appendChild(legalEl('div', 'll-legal-empty', WFT('common.loading', 'جاري التحميل...')));
  if (dateArBox) dateArBox.value = '';
  if (dateEnBox) dateEnBox.value = '';
  if (noticeArBox) noticeArBox.value = '';
  if (noticeEnBox) noticeEnBox.value = '';

  const doc = (document.getElementById('adminLegalDoc') || {}).value || 'terms';

  try {
    const res = await api('GET', '/api/admin/legal/' + doc);
    if (res && res.success && res.document) {
      const d = res.document;
      adminLegalSectionsState = { ar: legalDocSections(d.ar), en: legalDocSections(d.en) };
      if (dateArBox) dateArBox.value = d.date_ar || '';
      if (dateEnBox) dateEnBox.value = d.date_en || '';
      if (noticeArBox) noticeArBox.value = d.notice_ar || '';
      if (noticeEnBox) noticeEnBox.value = d.notice_en || '';
      adminRenderLegalSections();
      return;
    }
    throw new Error((res && res.error) || 'Failed to load document');
  } catch (e) {
    try {
      const pageRes = await fetch('/' + doc, { headers: { 'Accept': 'text/html' } });
      if (!pageRes.ok) throw new Error('http ' + pageRes.status);
      const parsed = new DOMParser().parseFromString(await pageRes.text(), 'text/html');
      const strip = (el) => el ? el.innerHTML.replace(/<!--[\s\S]*?-->/g, '').trim() : '';
      adminLegalSectionsState = {
        ar: legalDocSections(strip(parsed.querySelector('[data-legal-ar]'))),
        en: legalDocSections(strip(parsed.querySelector('[data-legal-en]')))
      };
      if (dateArBox) dateArBox.value = strip(parsed.querySelector('[data-legal-date-ar]'));
      if (dateEnBox) dateEnBox.value = strip(parsed.querySelector('[data-legal-date-en]'));
      if (noticeArBox) noticeArBox.value = strip(parsed.querySelector('[data-legal-notice-ar]'));
      if (noticeEnBox) noticeEnBox.value = strip(parsed.querySelector('[data-legal-notice-en]'));
      adminRenderLegalSections();
    } catch (err) {
      adminLegalSectionsState = { ar: { title: '', sections: [] }, en: { title: '', sections: [] } };
      adminRenderLegalSections();
      toast(WFT('admin.legal_load_failed', 'تعذر تحميل الصفحة المحددة'));
    }
  }
}

function adminLegalSelectDoc() {
  adminLoadLegalDoc();
}

async function adminSaveLegalDoc() {
  const doc = (document.getElementById('adminLegalDoc') || {}).value || 'terms';
  const ar = legalDocumentHtml(adminLegalSectionsState.ar);
  const en = legalDocumentHtml(adminLegalSectionsState.en);
  const dateAr = (document.getElementById('adminLegalDateAr') || {}).value || '';
  const dateEn = (document.getElementById('adminLegalDateEn') || {}).value || '';
  const noticeAr = (document.getElementById('adminLegalNoticeAr') || {}).value || '';
  const noticeEn = (document.getElementById('adminLegalNoticeEn') || {}).value || '';

  if (legalDocumentIsEmpty(adminLegalSectionsState.ar) || legalDocumentIsEmpty(adminLegalSectionsState.en)) {
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

  const saveButton = document.getElementById('adminLegalSaveBtn');
  if (saveButton) saveButton.disabled = true;
  const res = await api('PUT', '/api/admin/legal/' + doc, payload).catch(e => e);
  if (saveButton) saveButton.disabled = false;
  if (!res || !res.success) {
    toast((res && res.error) || WFT('admin.legal_save_failed', 'تعذر حفظ المحتوى والتعديلات'));
    return;
  }
  toast(WFT('admin.legal_saved', 'تم حفظ المحتوى والتعديلات بنجاح'));
}
