'use strict';

// UI-level tests for the market summary chat (assets/js/05a-market-summary-chat.js)
// run against the real market modules in a vm context with DOM/API stubs.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const source = [
  'assets/js/03-executive-classification.js',
  'assets/js/04-market.js',
  'assets/js/04a-market-section.js',
  'assets/js/05-market-competitors.js',
  'assets/js/05-market-competitors/01_project_data_snapshot.js',
  'assets/js/05a-market-jobs.js',
  'assets/js/05a-market-summary-chat.js'
].map(file => fs.readFileSync(path.join(root, file), 'utf8')).join('\n');
const plain = value => JSON.parse(JSON.stringify(value));

function fakeSourceRow(row) {
  const fields = {
    competitor_name: row.competitor_name || '', name: row.name || '', url: row.url || '',
    data_date: row.data_date || '', accessed_at: row.accessed_at || '',
    reliability: row.reliability || '', note: row.note || ''
  };
  return {
    dataset: {
      competitorId: row.competitor_id || '', sourceKind: row.source_kind || '',
      sourceFields: '{}', previousUrl: row.url || ''
    },
    querySelector: selector => {
      const match = selector.match(/\[data-field="([^"]+)"\]/);
      return match ? { value: fields[match[1]] || '' } : null;
    }
  };
}

function fixture() {
  const storedSources = [{ name: 'مصدر موجود', url: 'https://a.sa' }];
  const host = { innerHTML: '' };
  const chatInput = { value: '', disabled: false, addEventListener() {}, focus() {} };
  const decisionLabel = { children: [], querySelector: sel => (sel === '.market-summary-stale-tag' ? decisionLabel.children[0] || null : null), appendChild(c) { decisionLabel.children[0] = c; return c; } };
  const inputs = {
    marketSummaryChat: host,
    marketSummaryChatInput: chatInput,
    marketSummaryChatResearch: { checked: true, disabled: false, addEventListener() {} },
    marketSummaryChatLog: { scrollTop: 0, scrollHeight: 10 },
    marketStudyData: { value: '', dataset: { key: 'market_study_data' } },
    marketStudyOneBlockSummary: { value: 'ملخص قائم', closest: () => null },
    marketDisclaimer: { value: '' },
    marketCompetitorScopeMode: { value: 'district' },
    marketComparisonTypes: { querySelectorAll: () => [] },
    marketDataPeriod: { value: '' },
    marketDataPeriodFrom: { value: '' },
    marketDataPeriodTo: { value: '' },
    marketDecision: {
      value: 'فرصة قوية',
      options: [
        { value: '' }, { value: 'فرصة قوية' }, { value: 'فرصة واعدة بشروط' },
        { value: 'فرصة متوسطة' }, { value: 'فرصة مرتفعة المخاطر' }, { value: 'البيانات غير كافية' }
      ],
      parentElement: { querySelector: sel => (sel === 'label' ? decisionLabel : null) }
    }
  };
  // Element registry: innerHTML is never parsed in the stub DOM, so elements
  // reached through querySelector('#id') are minted lazily and shared with
  // getElementById — enough for mount/toggle paths to run for real.
  const registry = {};
  const fakeEl = () => ({
    tagName: 'DIV', className: '', hidden: false, disabled: false,
    textContent: '', innerHTML: '', value: '', style: {}, dataset: {},
    children: [], offsetWidth: 400, offsetHeight: 500,
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); }, remove(c) { this._set.delete(c); },
      contains(c) { return this._set.has(c); },
      toggle(c, force) {
        const want = force === undefined ? !this._set.has(c) : !!force;
        if (want) this._set.add(c); else this._set.delete(c);
      }
    },
    appendChild(child) { this.children.push(child); return child; },
    remove() {},
    addEventListener() {}, setPointerCapture() {}, focus() {},
    closest() { return null; },
    getBoundingClientRect() { return { left: 18, top: 700, right: 74, bottom: 756, width: 56, height: 56 }; },
    querySelector(sel) {
      const id = sel.startsWith('#') ? sel.slice(1) : null;
      if (id) return registry[id] || (registry[id] = fakeEl());
      return null;
    },
    querySelectorAll() { return []; }
  });
  inputs['section-market-study'] = fakeEl();
  const initialSummary = { market_definition: 'تعريف السوق الحالي', supply: 'نص العرض الحالي' };
  const initialSwot = { strengths: 'قوة قائمة' };
  const summaryKeys = ['market_definition', 'city_position', 'sector_performance', 'supply',
    'demand', 'competition', 'market_gap', 'project_evaluation', 'recommendation', 'risks'];
  const swotKeys = ['strengths', 'weaknesses', 'opportunities', 'threats'];
  summaryKeys.forEach(key => { inputs['marketSummary_' + key] = { value: initialSummary[key] || '', addEventListener() {} }; });
  swotKeys.forEach(key => { inputs['marketSwot_' + key] = { value: initialSwot[key] || '', addEventListener() {} }; });
  const context = vm.createContext({
    console, Intl, URL, JSON, setTimeout, clearTimeout,
    window: {
      location: { origin: 'http://localhost:5515' },
      innerWidth: 1280, innerHeight: 800,
      addEventListener() {}
    },
    localStorage: { _m: {}, getItem(k) { return this._m[k] ?? null; }, setItem(k, v) { this._m[k] = String(v); } },
    getComputedStyle: () => ({ direction: 'rtl' }),
    tenantProjectData: {
      draftId: 'draft-1', project_name: 'مشروع سكني', city: 'الرياض',
      project_language: '', market_study_data: {
        summary: initialSummary,
        sources: storedSources.map(row => ({ ...row })),
        swot: initialSwot,
        decision: 'فرصة قوية',
        one_block_summary: 'ملخص قائم'
      }
    },
    tenantProjectSectionStatuses: {},
    tenantAllowedFieldSections: { 'section-market-study': true },
    tenantProjectMode: 'draft',
    toasts: [], requests: [],
    document: {
      addEventListener() {},
      createElement: fakeEl,
      getElementById: id => inputs[id] || registry[id] || null,
      querySelector: () => null,
      querySelectorAll: selector =>
        (selector === '#marketSourcesPanels .market-sources-table tbody tr'
          ? storedSources.map(fakeSourceRow) : [])
    },
    WFT: (key, fallback = key, params = {}) =>
      String(fallback).replace(/\{(\w+)\}/g, (match, name) => params[name] ?? match),
    wfTr: text => text,
    escapeHtml: text => String(text ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;'),
    toast: text => context.toasts.push(text),
    confirm: () => true,
    triggerAutoSaveDraft() {},
    hasPermission: () => true,
    showLoader() {}, updateLoaderProgress() {}, hideLoader() {},
    parseStoredLandTable: value => {
      if (!value) return null;
      if (typeof value === 'string') { try { return JSON.parse(value); } catch (e) { return null; } }
      return value;
    },
    selectedProjectTypeMains: () => ['سكني'],
    selectedProjectSubtypes: () => ['شقق'],
    groupedAudienceSelection: () => [],
    api: async (method, endpoint, payload) => {
      context.requests.push({ method, endpoint, payload });
      return context.nextResponse || { success: true, reply: 'رد المساعد' };
    },
    pollMarketStudyJob: async () => context.pollResponse || { success: true, reply: 'رد المساعد' }
  });
  vm.runInContext(source, context);
  return { context, inputs, host, chatInput, decisionLabel };
}

test('axis list is general plus the ten summary axes in order', () => {
  const { context } = fixture();
  const axes = context.marketSummaryChatAxes();
  assert.equal(axes.length, 11);
  assert.equal(axes[0].key, 'general');
  const sectionKeys = vm.runInContext(
    'MARKET_STUDY_SUMMARY_SECTIONS.map(item => item.key)', context);
  assert.deepEqual(axes.slice(1).map(item => item.key), sectionKeys);
});

test('applySummaryChatOps writes ops, merges sources and stamps stale flags', () => {
  const { context } = fixture();
  const state = context.getMarketStudyState();
  state.summaryStale = {};
  const next = context.applySummaryChatOps(state, {
    ops: [
      { op: 'set_axis', key: 'supply', value: 'نص عرض جديد' },
      { op: 'set_swot', key: 'strengths', value: 'قوة جديدة' },
      { op: 'set_decision', value: 'فرصة متوسطة' },
      { op: 'set_axis', key: 'unknown_axis', value: 'x' },
      { op: 'set_decision', value: 'قيمة غير معروفة' }
    ],
    sourcesAdd: [
      { name: 'مصدر جديد', url: 'https://b.sa' },
      { name: 'مكرر', url: 'https://a.sa' }
    ]
  });
  assert.equal(next.summary.supply, 'نص عرض جديد');
  assert.equal(next.summary.market_definition, 'تعريف السوق الحالي');
  assert.equal(next.swot.strengths, 'قوة جديدة');
  assert.equal(next.decision, 'فرصة متوسطة');
  const urls = next.sources.map(row => row.url);
  assert.ok(urls.includes('https://b.sa'));
  assert.equal(urls.filter(url => url === 'https://a.sa').length, 1);
  assert.equal(next.summaryStale.one_block, true);
  assert.equal(next.summaryStale.decision, true);
  assert.equal(next.summaryStale.swot, true);
});

test('a swot-only proposal stales the one-block summary alone', () => {
  const { context } = fixture();
  const state = context.getMarketStudyState();
  state.summaryStale = {};
  const next = context.applySummaryChatOps(state, {
    ops: [{ op: 'set_swot', key: 'threats', value: 'تهديد' }]
  });
  assert.deepEqual(plain(next.summaryStale), { one_block: true });
});

test('sendMarketSummaryChat posts the axis state and stores both turns', async () => {
  const { context, chatInput } = fixture();
  chatInput.value = 'حدّث محور العرض';
  context.nextResponse = { success: true, reply: 'تم البحث', searchPerformed: true };
  await context.sendMarketSummaryChat();
  assert.equal(context.requests.length, 1);
  const request = context.requests[0];
  assert.equal(request.method, 'POST');
  assert.equal(request.endpoint, '/api/market-study/summary/chat');
  assert.equal(request.payload.message, 'حدّث محور العرض');
  assert.equal(request.payload.axis, '');
  assert.equal(request.payload.research, 'auto');
  assert.equal(request.payload.decision, 'فرصة قوية');
  assert.equal(request.payload.oneBlockSummary, 'ملخص قائم');
  assert.equal(Array.isArray(request.payload.history), true);
  const thread = context.getMarketStudyState().summaryChat.general;
  assert.equal(thread.length, 2);
  assert.equal(thread[0].role, 'user');
  assert.equal(thread[1].role, 'assistant');
  assert.equal(thread[1].searchPerformed, true);
});

test('sendMarketSummaryChat always auto-routes: axis stays empty and history is capped', async () => {
  const { context, chatInput } = fixture();
  const state = context.getMarketStudyState();
  state.summaryChat = {
    general: Array.from({ length: 20 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', content: 'م' + i }))
  };
  context.setMarketStudyState(state);
  chatInput.value = 'رسالة جديدة';
  await context.sendMarketSummaryChat();
  const request = context.requests[0];
  assert.equal(request.payload.axis, '');
  assert.equal(request.payload.history.length, 12);
  assert.deepEqual(Object.keys(request.payload.history[0]).sort(), ['content', 'role']);
});

test('the detected axis echoes back on the assistant turn as a tag', async () => {
  const { context, host, chatInput } = fixture();
  chatInput.value = 'حدّث محور العرض';
  context.nextResponse = { success: true, reply: 'تم', axis: 'supply' };
  await context.sendMarketSummaryChat();
  const thread = context.getMarketStudyState().summaryChat.general;
  assert.equal(thread[1].axis, 'supply');
  assert.match(host.innerHTML, /market-summary-chat-axistag/);
  assert.match(host.innerHTML, /المحور:/);
});

test('a clarification answer renders like a normal reply without proposals', async () => {
  const { context, host, chatInput } = fixture();
  chatInput.value = 'عدّل القسم';
  context.nextResponse = { success: true, reply: 'هل تقصد العرض أم الطلب؟', clarification: true };
  await context.sendMarketSummaryChat();
  const thread = context.getMarketStudyState().summaryChat.general;
  assert.equal(thread[1].clarification, true);
  assert.equal(thread[1].proposal, undefined);
  assert.match(host.innerHTML, /هل تقصد العرض أم الطلب؟/);
  assert.doesNotMatch(host.innerHTML, /تعديلات مقترحة/);
});

test('mountMarketSummaryChat mounts the floating ball and a hidden panel once', () => {
  const { context, inputs } = fixture();
  const section = inputs['section-market-study'];
  context.mountMarketSummaryChat(section);
  context.mountMarketSummaryChat(section);
  assert.equal(section.children.length, 1);
  const wrap = section.children[0];
  assert.equal(wrap.className, 'land-chat-wrap');
  assert.match(wrap.innerHTML, /class="land-chat-fab" id="marketSummaryChatFab"/);
  assert.match(wrap.innerHTML, /class="land-chat-panel" id="marketSummaryChatPanel" hidden/);
  assert.match(wrap.innerHTML, /id="marketSummaryChatResize"/);
  assert.doesNotMatch(wrap.innerHTML, /selectMarketSummaryChatAxis/);
  const panel = context.document.getElementById('marketSummaryChatPanel');
  panel.hidden = true;   // the stub DOM does not parse the hidden attribute
  context.toggleMarketSummaryChat(true);
  assert.equal(panel.hidden, false);
  context.toggleMarketSummaryChat();
  assert.equal(panel.hidden, true);
});

test('legacy per-axis threads fold into the single auto thread', () => {
  const { context } = fixture();
  const state = context.getMarketStudyState();
  state.summaryChat = {
    supply: [{ role: 'user', content: 'س1' }, { role: 'assistant', content: 'ج1' }],
    demand: [{ role: 'user', content: 'س2' }]
  };
  context.setMarketStudyState(state);
  const merged = context.marketSummaryChatState();
  assert.deepEqual(Object.keys(merged.summaryChat), ['general']);
  assert.equal(merged.summaryChat.general.length, 3);
});

test('a proposal renders a pending card and apply writes the state', async () => {
  const { context, host, chatInput } = fixture();
  chatInput.value = 'اقترح تحديثًا';
  context.nextResponse = {
    success: true,
    reply: 'اقتراح جاهز',
    proposal: {
      ops: [{ op: 'set_axis', key: 'demand', value: 'طلب محدّث' }],
      touchedAxes: ['demand'],
      sourcesAdd: []
    }
  };
  await context.sendMarketSummaryChat();
  assert.match(host.innerHTML, /تعديلات مقترحة/);
  assert.match(host.innerHTML, /applyMarketSummaryChatProposal\('general', 1\)/);
  assert.match(host.innerHTML, /dismissMarketSummaryChatProposal\('general', 1\)/);
  assert.notEqual(context.getMarketStudyState().summary.demand, 'طلب محدّث');
  context.applyMarketSummaryChatProposal('general', 1);
  const stored = context.getMarketStudyState();
  assert.equal(stored.summary.demand, 'طلب محدّث');
  assert.equal(stored.summaryStale.one_block, true);
  const thread = stored.summaryChat.general;
  assert.equal(thread[1].proposalStatus, 'applied');
  assert.match(host.innerHTML, /طُبّق/);
  assert.match(host.innerHTML, /مخرجات تحتاج تحديثًا/);
});

test('dismissing a proposal keeps the state untouched', async () => {
  const { context, chatInput } = fixture();
  chatInput.value = 'اقترح';
  context.nextResponse = {
    success: true, reply: 'ر',
    proposal: { ops: [{ op: 'set_axis', key: 'demand', value: 'v' }], sourcesAdd: [] }
  };
  await context.sendMarketSummaryChat();
  context.dismissMarketSummaryChatProposal('general', 1);
  const stored = context.getMarketStudyState();
  assert.notEqual(stored.summary.demand, 'v');
  assert.equal(stored.summaryChat.general[1].proposalStatus, 'dismissed');
});

test('a locked section keeps the composer but blocks apply', async () => {
  const { context, host, chatInput } = fixture();
  context.tenantProjectSectionStatuses['section-market-study'] = 'approved';
  chatInput.value = 'اقترح';
  context.nextResponse = {
    success: true, reply: 'ر',
    proposal: { ops: [{ op: 'set_axis', key: 'supply', value: 'v' }], sourcesAdd: [] }
  };
  await context.sendMarketSummaryChat();
  assert.match(host.innerHTML, /applyMarketSummaryChatProposal\('general', 1\)" disabled>/);
  context.applyMarketSummaryChatProposal('general', 1);
  assert.equal(context.getMarketStudyState().summary.supply, 'نص العرض الحالي');
  assert.equal(context.toasts.length, 1);
});

test('consolidate posts the stale keys and clears the flags it regenerated', async () => {
  const { context } = fixture();
  const state = context.getMarketStudyState();
  state.summaryStale = { one_block: true, decision: true, swot: true };
  context.setMarketStudyState(state);
  context.nextResponse = {
    success: true,
    one_block_summary: 'ملخص جديد',
    decision: 'فرصة متوسطة',
    swot: { strengths: 'قوة جديدة', weaknesses: '', opportunities: '', threats: '' }
  };
  await context.runMarketSummaryConsolidate();
  assert.equal(context.requests[0].endpoint, '/api/market-study/summary/consolidate');
  assert.deepEqual([...context.requests[0].payload.stale].sort(), ['decision', 'one_block', 'swot']);
  const stored = context.getMarketStudyState();
  assert.equal(stored.one_block_summary, 'ملخص جديد');
  assert.equal(stored.decision, 'فرصة متوسطة');
  assert.equal(stored.swot.strengths, 'قوة جديدة');
  assert.deepEqual(plain(stored.summaryStale), {});
});

test('consolidate without stale keys never reaches the server', async () => {
  const { context } = fixture();
  const state = context.getMarketStudyState();
  state.summaryStale = {};
  context.setMarketStudyState(state);
  await context.runMarketSummaryConsolidate();
  assert.equal(context.requests.length, 0);
});

test('model replies are escaped inside the rendered thread', async () => {
  const { context, host, chatInput } = fixture();
  chatInput.value = '<script>x</script>';
  context.nextResponse = { success: true, reply: '<img src=x onerror=1>' };
  await context.sendMarketSummaryChat();
  assert.doesNotMatch(host.innerHTML, /<script>/);
  assert.doesNotMatch(host.innerHTML, /<img/);
  assert.match(host.innerHTML, /&lt;img/);
});

test('an empty thread renders an empty state, not a blank log', () => {
  const { context, host } = fixture();
  context.renderMarketSummaryChat();
  assert.match(host.innerHTML, /land-chat-empty/);
  assert.match(host.innerHTML, /لا توجد رسائل في هذه المحادثة/);
});

test('the stale bar names the flagged outputs next to its update action', () => {
  const { context, host } = fixture();
  const state = context.getMarketStudyState();
  state.summaryStale = { one_block: true, decision: true };
  context.setMarketStudyState(state);
  context.renderMarketSummaryChat();
  assert.match(host.innerHTML, /market-summary-chat-stale-title[^<]*مخرجات تحتاج تحديثًا/);
  assert.match(host.innerHTML, /ملخص دراسة سوق العمل/);
  assert.match(host.innerHTML, /تصنيف القرار/);
  assert.match(host.innerHTML, /runMarketSummaryConsolidate\(\)"[^>]*>\s*تحديث المخرجات/);
});

test('the stale bar stays hidden while nothing is flagged', () => {
  const { context, host } = fixture();
  const state = context.getMarketStudyState();
  state.summaryStale = {};
  context.setMarketStudyState(state);
  context.renderMarketSummaryChat();
  assert.match(host.innerHTML, /class="market-summary-chat-stale" hidden>/);
  // The CSS must re-hide it too: display:flex on the class beats the UA
  // [hidden] rule, which is what left a ghost bar on screen before.
  const css = fs.readFileSync(
    path.join(root, 'assets/css/project-form/05a_market_summary_chat.css'), 'utf8');
  assert.match(css, /\.market-summary-chat-stale\[hidden\]\s*\{\s*display:\s*none/);
});

test('the composer keeps a foot row with a real checkbox and the send action', () => {
  const { context, host } = fixture();
  context.renderMarketSummaryChat();
  const foot = host.innerHTML.slice(
    host.innerHTML.indexOf('market-summary-chat-composer-foot'));
  assert.match(foot, /id="marketSummaryChatResearch"/);
  assert.match(foot, /sendMarketSummaryChat\(\)/);
  // The global input rule (width:100%, min-height:42px) tiles checkboxes —
  // the chat pins its research toggle back to checkbox size.
  const css = fs.readFileSync(
    path.join(root, 'assets/css/project-form/05a_market_summary_chat.css'), 'utf8');
  assert.match(css, /\.market-summary-chat-research input\[type="checkbox"\][^}]*min-height:\s*0/);
});

test('the panel header keeps its glyph buttons with accessible names', () => {
  const { context, inputs } = fixture();
  context.mountMarketSummaryChat(inputs['section-market-study']);
  const wrap = inputs['section-market-study'].children[0];
  assert.match(wrap.innerHTML, /aria-label="إخفاء"[^>]*>&gt;&lt;/);
  assert.match(wrap.innerHTML, /aria-label="إنهاء"[^>]*>×</);
});
