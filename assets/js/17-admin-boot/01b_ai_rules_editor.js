// Generation-rules editor for the AI rules screen: the summary strip, its drawer
// and the prompt-text preview. Kept out of 01_training_rules.js, which is already
// past the ~1,000-line limit.

let airRulesState = { tone: '', approved: [], banned: [], directives: '', extra: '' };
let airRulesMeta = { maxChars: 8000, updatedAt: '' };
let airRulesIsDirty = false;

const AIR_RULES_TERM_LIMIT = 40;
const AIR_RULES_TERM_MAX_LENGTH = 60;

function airRulesToneLabel(tone) {
  if (tone === 'analytical') return WFT('ai_rules.tone_analytical', 'تحليلي تنفيذي');
  if (tone === 'marketing') return WFT('ai_rules.tone_marketing', 'تسويقي راقٍ');
  if (tone === 'engineering') return WFT('ai_rules.tone_engineering', 'هندسي دقيق');
  return '';
}

function setAIRulesDirty(flag) {
  airRulesIsDirty = Boolean(flag);
  const chip = document.getElementById('airRulesDirty');
  if (chip) chip.hidden = !airRulesIsDirty;
}

function markAIRulesDirty() {
  setAIRulesDirty(true);
}

function renderAIRulesStamp() {
  const el = document.getElementById('airRulesStampText');
  if (!el) return;
  if (!airRulesMeta.updatedAt) {
    el.textContent = WFT('ai_rules.not_saved', 'لم تُحفظ قواعد بعد');
    return;
  }
  const date = new Date(airRulesMeta.updatedAt);
  if (isNaN(date.getTime())) {
    el.textContent = '';
    return;
  }
  el.textContent = WFT('ai_rules.saved_at', 'آخر حفظ {stamp}', {
    stamp: wfDate(date) + ' — ' + wfTime(date)
  });
}

function airRulesTermPhrase(kind, count) {
  const banned = kind === 'banned';
  if (count === 1) {
    return banned
      ? WFT('ai_rules.summary_banned_one', 'مصطلح ممنوع واحد')
      : WFT('ai_rules.summary_approved_one', 'مصطلح معتمد واحد');
  }
  if (count === 2) {
    return banned
      ? WFT('ai_rules.summary_banned_two', 'مصطلحان ممنوعان')
      : WFT('ai_rules.summary_approved_two', 'مصطلحان معتمدان');
  }
  if (count <= 10) {
    return banned
      ? WFT('ai_rules.summary_banned', '{count} مصطلحات ممنوعة', { count: count })
      : WFT('ai_rules.summary_approved', '{count} مصطلحات معتمدة', { count: count });
  }
  return banned
    ? WFT('ai_rules.summary_banned_many', '{count} مصطلحاً ممنوعاً', { count: count })
    : WFT('ai_rules.summary_approved_many', '{count} مصطلحاً معتمداً', { count: count });
}

function renderAIRulesSummary() {
  const el = document.getElementById('airRulesSummary');
  if (!el) return;
  const parts = [];
  const tone = airRulesState.tone;
  if (tone) parts.push('<b>' + escapeHtml(airRulesToneLabel(tone)) + '</b>');
  if (airRulesState.banned.length) {
    parts.push(escapeHtml(airRulesTermPhrase('banned', airRulesState.banned.length)));
  }
  if (airRulesState.approved.length) {
    parts.push(escapeHtml(airRulesTermPhrase('approved', airRulesState.approved.length)));
  }
  if (airRulesState.directives) {
    parts.push(escapeHtml(WFT('ai_rules.summary_directives', 'توجيهات أقسام مضافة')));
  }
  el.innerHTML = parts.length
    ? parts.join(' · ')
    : escapeHtml(WFT('ai_rules.summary_empty', 'لا توجد قواعد توليد خاصة بهذه المنشأة'));
}

function renderAIRulesTone() {
  const group = document.getElementById('airRulesToneGroup');
  if (!group) return;
  group.querySelectorAll('button[data-tone]').forEach(btn => {
    btn.classList.toggle('is-active', btn.getAttribute('data-tone') === airRulesState.tone);
  });
}

function renderAIRulesChips(kind) {
  const container = document.getElementById(kind === 'approved' ? 'airRulesApprovedChips' : 'airRulesBannedChips');
  if (!container) return;
  container.textContent = '';
  airRulesState[kind].forEach((term, index) => {
    const chip = document.createElement('span');
    chip.className = 'air-chip' + (kind === 'approved' ? ' is-approved' : '');
    chip.appendChild(document.createTextNode(term + ' '));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = WFT('ai_rules.remove_term', 'إزالة');
    remove.addEventListener('click', () => removeAIRulesTerm(kind, index));
    chip.appendChild(remove);
    container.appendChild(chip);
  });
}

function renderAIRulesFields() {
  renderAIRulesSummary();
  renderAIRulesTone();
  renderAIRulesChips('banned');
  renderAIRulesChips('approved');
  const directives = document.getElementById('airRulesDirectivesInput');
  if (directives) directives.value = airRulesState.directives || '';
  const extraNote = document.getElementById('airRulesExtraNote');
  if (extraNote) extraNote.hidden = !airRulesState.extra;
  renderAIRulesStamp();
}

function applyGenerationRulesState(rules) {
  rules = rules || {};
  airRulesState = {
    tone: rules.tone || '',
    approved: Array.isArray(rules.approved) ? rules.approved.slice() : [],
    banned: Array.isArray(rules.banned) ? rules.banned.slice() : [],
    directives: rules.directives || '',
    extra: rules.extra || ''
  };
  renderAIRulesFields();
}

async function loadGenerationRules() {
  const data = await api('GET', '/api/ai-rules/generation-rules');
  if (!data || !data.success) return;
  airRulesMeta = {
    maxChars: data.maxChars || 8000,
    updatedAt: data.updatedAt || ''
  };
  applyGenerationRulesState(data.rules);
  setAIRulesDirty(false);
}

function openAIRulesDrawer() {
  applyGenerationRulesState(airRulesState);
  setAIRulesDirty(false);
  const error = document.getElementById('airRulesError');
  if (error) error.hidden = true;
  const drawer = document.getElementById('aiRulesDrawer');
  if (drawer) drawer.hidden = false;
}

function closeAIRulesDrawer() {
  const drawer = document.getElementById('aiRulesDrawer');
  if (drawer) drawer.hidden = true;
}

function toggleAIRulesApproved() {
  const wrap = document.getElementById('airRulesApprovedWrap');
  if (wrap) wrap.hidden = !wrap.hidden;
}

function selectAIRulesTone(tone) {
  airRulesState.tone = airRulesState.tone === tone ? '' : tone;
  renderAIRulesTone();
  setAIRulesDirty(true);
}

function addAIRulesTerm(kind) {
  const input = document.getElementById(kind === 'approved' ? 'airRulesApprovedInput' : 'airRulesBannedInput');
  if (!input) return;
  const term = (input.value || '').trim();
  if (!term) return;
  if (term.length > AIR_RULES_TERM_MAX_LENGTH) {
    toast(WFT('ai_rules.term_too_long', 'المصطلح أطول من الحد المسموح'));
    return;
  }
  if (airRulesState[kind].indexOf(term) !== -1) {
    toast(WFT('ai_rules.term_exists', 'المصطلح موجود بالفعل'));
    return;
  }
  if (airRulesState[kind].length >= AIR_RULES_TERM_LIMIT) {
    toast(WFT('ai_rules.term_limit', 'بلغت الحد الأقصى لعدد المصطلحات'));
    return;
  }
  airRulesState[kind].push(term);
  input.value = '';
  renderAIRulesChips(kind);
  renderAIRulesSummary();
  setAIRulesDirty(true);
}

function removeAIRulesTerm(kind, index) {
  if (!airRulesState[kind] || index < 0 || index >= airRulesState[kind].length) return;
  airRulesState[kind].splice(index, 1);
  renderAIRulesChips(kind);
  renderAIRulesSummary();
  setAIRulesDirty(true);
}

function airRulesPayload() {
  const directives = document.getElementById('airRulesDirectivesInput');
  return {
    tone: airRulesState.tone,
    approved: airRulesState.approved.slice(),
    banned: airRulesState.banned.slice(),
    directives: directives ? directives.value.trim() : airRulesState.directives
  };
}

function showAIRulesError(message) {
  const error = document.getElementById('airRulesError');
  if (!error) return;
  error.textContent = message;
  error.hidden = false;
}

async function saveGenerationRules() {
  const button = document.getElementById('airRulesSaveBtn');
  const error = document.getElementById('airRulesError');
  if (error) error.hidden = true;
  if (button) button.disabled = true;
  const data = await api('POST', '/api/ai-rules/generation-rules', airRulesPayload());
  if (button) button.disabled = false;
  if (!data || !data.success) {
    showAIRulesError((data && data.error) || WFT('ai_rules.save_failed', 'تعذر حفظ القواعد'));
    return;
  }
  airRulesMeta.updatedAt = data.updatedAt || new Date().toISOString();
  applyGenerationRulesState(data.rules);
  setAIRulesDirty(false);
  closeAIRulesDrawer();
  toast(WFT('ai_rules.saved_toast', 'تم حفظ قواعد التوليد'));
}

async function showAIRulesPromptPreview() {
  const data = await api('POST', '/api/ai-rules/generation-rules/preview', airRulesPayload());
  if (!data || !data.success) {
    toast((data && data.error) || WFT('ai_rules.preview_failed', 'تعذر عرض النص'));
    return;
  }
  const text = document.getElementById('airRulesPromptText');
  if (text) text.textContent = data.composed || '';
  const modal = document.getElementById('airRulesPromptModal');
  if (modal) modal.hidden = false;
}

function closeAIRulesPromptPreview() {
  const modal = document.getElementById('airRulesPromptModal');
  if (modal) modal.hidden = true;
}

document.addEventListener('keydown', function (event) {
  if (event.key !== 'Escape') return;
  closeAIRulesPromptPreview();
  closeAIRulesDrawer();
});

// openTenantAIRules is defined in 01_training_rules.js, which already sits past the
// line limit, so the rules load is attached here instead of adding to it.
(function attachGenerationRulesToAIRulesPage() {
  if (typeof openTenantAIRules !== 'function') return;
  const base = openTenantAIRules;
  openTenantAIRules = async function () {
    const result = await base.apply(this, arguments);
    await loadGenerationRules();
    return result;
  };
})();
