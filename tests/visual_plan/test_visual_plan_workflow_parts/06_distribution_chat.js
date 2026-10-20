'use strict';

const assert = require('node:assert/strict');

module.exports = function registerDistributionChatTests({ test, fixture, plain }) {
  function stubChat(context, response) {
    const calls = [];
    context.hasPermission = () => true;
    context.showLoader = () => {};
    context.hideLoader = () => {};
    context.toast = () => {};
    context.markVisualConceptDirty = () => {};
    context.renderVisualConceptPage = () => {};
    context.collectVisualConceptPlansWorkflowPayload = async () => ({
      plansWorkflow: { distribution: { rows: [] } },
      projectData: {}
    });
    context.api = async (method, path, body) => {
      calls.push({ method, path, body });
      return response;
    };
    return calls;
  }

  test('the boundary stage renders the distribution chat and drops the separate controls', () => {
    const context = fixture();
    const root = { innerHTML: '', dataset: {}, querySelector: () => null, querySelectorAll: () => [], addEventListener: () => {} };
    context.document.getElementById = id => id === 'visualConceptPlansWorkflow' ? root : null;
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {},
      plansWorkflow: {
        viewStage: 'boundary',
        verification: { approved: true, canProceed: true },
        boundary: { approved: true },
        distribution: {
          approved: false,
          aiReviewed: true,
          rows: [{ id: 'b1', building: 'المبنى أ', floor_range: 'أرضي', component: 'سكني' }],
          checks: [],
          issues: [],
          canProceed: true,
        },
      },
    });

    context.renderVisualConceptPlansWorkflow();
    const html = root.innerHTML;
    // The conversation owns the stage.
    assert.ok(html.includes('plans-distribution-chat'));
    assert.ok(html.includes('data-plans-distribution-chat-input'));
    // The table stays editable by hand.
    assert.ok(html.includes('data-plans-distribution-editor'));
    // The proposal / notes / revision / conflict-check controls are gone —
    // the chat does all four.
    assert.ok(!html.includes('data-plans-workflow-action="propose-distribution"'));
    assert.ok(!html.includes('data-plans-workflow-action="revise-distribution"'));
    assert.ok(!html.includes('data-plans-workflow-action="check-distribution"'));
    assert.ok(!html.includes('data-plans-distribution-notes'));
    assert.ok(!html.includes('data-plans-distribution-revision'));
  });

  test('an empty table offers the proposal as the first turn of the chat', () => {
    const context = fixture();
    const root = { innerHTML: '', dataset: {}, querySelector: () => null, querySelectorAll: () => [], addEventListener: () => {} };
    context.document.getElementById = id => id === 'visualConceptPlansWorkflow' ? root : null;
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {},
      plansWorkflow: {
        viewStage: 'boundary',
        verification: { approved: true, canProceed: true },
        boundary: { approved: true },
        distribution: { approved: false, aiReviewed: false, rows: [], checks: [], issues: [] },
      },
    });

    context.renderVisualConceptPlansWorkflow();
    const html = root.innerHTML;
    assert.ok(html.includes('data-plans-workflow-action="distribution-chat-start"'));
    assert.ok(html.includes('data-plans-distribution-chat-input'));
  });

  test('the chat state keeps the turns and the memory and reads the legacy array', () => {
    const context = fixture();
    const state = plain(context.normalizeVisualConceptPlansWorkflow({
      distributionChat: {
        turns: [{ role: 'user', text: 'السكن في الطابق الأول' }],
        memory: 'العميل يفضّل السكن في الطابق الأول',
        decisions: ['السكن في الطابق الأول'],
      },
      conflictChats: { verify: [{ role: 'user', text: 'سؤال سابق' }] },
    }));
    assert.equal(state.distributionChat.turns.length, 1);
    assert.equal(state.distributionChat.turns[0].text, 'السكن في الطابق الأول');
    assert.equal(state.distributionChat.memory, 'العميل يفضّل السكن في الطابق الأول');
    assert.deepEqual(state.distributionChat.decisions, ['السكن في الطابق الأول']);
    // A draft saved before the memory existed still opens its thread.
    assert.equal(state.conflictChats.verify.turns.length, 1);
    assert.equal(state.conflictChats.verify.turns[0].text, 'سؤال سابق');
    assert.equal(state.conflictChats.verify.memory, '');
  });

  test('a chat turn carries the whole thread and applies the edited table', async () => {
    const context = fixture();
    const calls = stubChat(context, {
      success: true,
      action: 'update',
      reply: 'تم نقل السكن إلى الطابق الأول.',
      rows: [{ id: 'r1', building: 'المبنى أ', floor_range: '1', component: 'سكني',
        units_per_floor: 4, floor_area_sqm: 120 }],
      checks: [{ item: 'نسبة التغطية', result: 'مطابق' }],
      issues: [],
      canProceed: true,
      memory: 'العميل يفضّل السكن في الطابق الأول',
      decisions: ['السكن في الطابق الأول'],
    });
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {},
      plansWorkflow: {
        viewStage: 'boundary',
        verification: { approved: true },
        distribution: { approved: false, aiReviewed: false, rows: [] },
        distributionChat: {
          turns: [{ role: 'user', text: 'السكن في الأرضي غير مناسب' }],
          memory: 'ذاكرة سابقة',
          decisions: [],
        },
      },
    });

    await context.sendVisualConceptDistributionChat('حوّل السكن للطابق الأول');

    assert.equal(calls.length, 1);
    assert.equal(calls[0].path, '/api/visual-concept/plans-distribution-chat');
    assert.equal(calls[0].body.message, 'حوّل السكن للطابق الأول');
    // The whole thread travels: the model answers from what was agreed.
    assert.equal(calls[0].body.history.length, 1);
    assert.equal(calls[0].body.history[0].content, 'السكن في الأرضي غير مناسب');
    assert.equal(calls[0].body.memory, 'ذاكرة سابقة');

    const workflow = context.tenantVisualConceptState.plansWorkflow;
    assert.equal(workflow.distribution.rows.length, 1);
    assert.equal(workflow.distribution.rows[0].floor_range, '1');
    assert.equal(workflow.distribution.aiReviewed, true);
    // The stored turn, the client's turn and the answer.
    assert.equal(workflow.distributionChat.turns.length, 3);
    assert.equal(workflow.distributionChat.turns[2].role, 'assistant');
    assert.equal(workflow.distributionChat.memory, 'العميل يفضّل السكن في الطابق الأول');
    assert.deepEqual(workflow.distributionChat.decisions, ['السكن في الطابق الأول']);
  });

  test('the request never carries the chat turns inside the workflow payload', async () => {
    const context = fixture();
    context.collectVisualConceptPayload = async () => ({ projectData: {}, slotId: 'plan_site' });
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {},
      plansWorkflow: {
        viewStage: 'boundary',
        verification: { approved: true },
        distribution: { approved: false, aiReviewed: false, rows: [] },
        distributionChat: {
          turns: [{ role: 'user', text: 'سؤال سابق' }],
          memory: 'ذاكرة سابقة',
          decisions: [],
        },
        conflictChats: {
          verify: { turns: [{ role: 'user', text: 'س' }], memory: '', decisions: [] },
          distribution: { turns: [{ role: 'user', text: 'س' }], memory: '', decisions: [] },
        },
      },
    });

    const payload = await context.collectVisualConceptPlansWorkflowPayload();

    assert.ok(payload.plansWorkflow);
    // The turns travel in their own field — sending them twice would grow the
    // body past what the hosting edge accepts.
    assert.equal(payload.plansWorkflow.distributionChat.turns.length, 0);
    assert.equal(payload.plansWorkflow.distributionChat.memory, 'ذاكرة سابقة');
    assert.equal(payload.plansWorkflow.conflictChats.verify.turns.length, 0);
    assert.equal(payload.plansWorkflow.conflictChats.distribution.turns.length, 0);
  });

  test('the turn is queued, polled, and the applied table lands in the workflow', async () => {
    const context = fixture();
    const calls = [];
    const toasts = [];
    context.setTimeout = fn => setTimeout(fn, 0);
    context.hasPermission = () => true;
    context.showLoader = () => {};
    context.hideLoader = () => {};
    context.toast = message => toasts.push(message);
    context.markVisualConceptDirty = () => {};
    context.renderVisualConceptPage = () => {};
    context.collectVisualConceptPlansWorkflowPayload = async () => ({
      plansWorkflow: { distribution: { rows: [] } }, projectData: {} });
    context.api = async (method, path, body) => {
      calls.push({ method, path, body });
      if (method === 'POST') {
        return { success: true, jobId: 'job-123', status: 'queued', timeoutSeconds: 600 };
      }
      return { status: 'completed', success: true, result: {
        success: true, action: 'update', reply: 'تم توزيع الأدوار.',
        rows: [{ id: 'r1', building: 'المبنى أ', floor_range: '1', component: 'سكني',
          units_per_floor: 4, floor_area_sqm: 120 }],
        checks: [], issues: [], canProceed: true } };
    };
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {},
      plansWorkflow: { viewStage: 'boundary', verification: { approved: true },
        distribution: { approved: false, aiReviewed: false, rows: [], checks: [], issues: [] } } });

    await context.sendVisualConceptDistributionChat('اقترح توزيعًا', { expectsTable: true });

    // The request leaves the page at once and the answer comes from the job.
    assert.equal(calls[0].method, 'POST');
    assert.equal(calls[0].path, '/api/visual-concept/plans-distribution-chat');
    assert.ok(calls.some(call => call.method === 'GET'
      && call.path === '/api/visual-concept/plans-jobs/job-123'));
    const workflow = context.tenantVisualConceptState.plansWorkflow;
    assert.equal(workflow.distribution.rows.length, 1);
    assert.equal(workflow.distribution.rows[0].floor_range, '1');
    assert.equal(workflow.distribution.aiReviewed, true);
    // The answer is in the chat, not only on the screen.
    assert.equal(workflow.distributionChat.turns[1].role, 'assistant');
    assert.equal(workflow.distributionChat.turns[1].text, 'تم توزيع الأدوار.');
    // A turn that applied the table does not warn about an unchanged one.
    assert.equal(toasts.length, 0);
  });

  test('a failed turn shows the reason the server gave instead of one made-up message', async () => {
    const context = fixture();
    const toasts = [];
    context.hasPermission = () => true;
    context.showLoader = () => {};
    context.hideLoader = () => {};
    context.toast = message => toasts.push(message);
    context.markVisualConceptDirty = () => {};
    context.renderVisualConceptPage = () => {};
    context.collectVisualConceptPlansWorkflowPayload = async () => ({
      plansWorkflow: { distribution: { rows: [] } }, projectData: {} });
    context.api = async () => ({ success: false,
      error: 'انتهت مهلة الاتصال بالمزوّد (900 ثانية)', error_code: 'PLANS_PROVIDER_TIMEOUT' });
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {},
      plansWorkflow: { viewStage: 'boundary', verification: { approved: true },
        distribution: { approved: false, aiReviewed: false, rows: [], checks: [], issues: [] } } });

    await context.sendVisualConceptDistributionChat('اقترح توزيعًا');

    assert.equal(toasts.length, 1);
    assert.match(toasts[0], /انتهت مهلة/);
    // The table stays exactly as the client left it.
    const workflow = context.tenantVisualConceptState.plansWorkflow;
    assert.equal(workflow.distribution.rows.length, 0);
    assert.equal(workflow.distribution.aiReviewed, false);
  });

  test('a turn that asked for a layout and got none says the floors did not change', async () => {
    const context = fixture();
    const toasts = [];
    context.hasPermission = () => true;
    context.showLoader = () => {};
    context.hideLoader = () => {};
    context.toast = message => toasts.push(message);
    context.markVisualConceptDirty = () => {};
    context.renderVisualConceptPage = () => {};
    context.collectVisualConceptPlansWorkflowPayload = async () => ({
      plansWorkflow: { distribution: { rows: [] } }, projectData: {} });
    context.api = async () => ({ success: true, action: 'explain',
      reply: 'السكن في الطابق الأول.', rows: [] });
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {},
      plansWorkflow: { viewStage: 'boundary', verification: { approved: true },
        distribution: { approved: false, aiReviewed: false, rows: [], checks: [], issues: [] } } });

    await context.sendVisualConceptDistributionChat('اقترح توزيعًا', { expectsTable: true });

    assert.equal(toasts.length, 1);
    assert.match(toasts[0], /لم يتغير توزيع الأدوار/);
  });

  test('the chat offers the floors and a clean start, and the clean start drops the old ones', async () => {
    const context = fixture();
    const calls = [];
    const root = { innerHTML: '', dataset: {}, querySelector: () => null,
      querySelectorAll: () => [], addEventListener: () => {} };
    context.document.getElementById = id => id === 'visualConceptPlansWorkflow' ? root : null;
    context.hasPermission = () => true;
    context.showLoader = () => {};
    context.hideLoader = () => {};
    context.toast = () => {};
    context.markVisualConceptDirty = () => {};
    context.renderVisualConceptPage = () => {};
    context.confirm = () => true;
    context.collectVisualConceptPlansWorkflowPayload = async () => ({
      plansWorkflow: { distribution: { rows: [] } }, projectData: {} });
    context.api = async (method, path, body) => {
      calls.push({ method, path, body });
      return { success: true, action: 'update', reply: 'تم.', rows: [],
        checks: [], issues: [], canProceed: true };
    };
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {},
      plansWorkflow: { viewStage: 'boundary', verification: { approved: true },
        distribution: { approved: false, aiReviewed: false, approved: false,
          rows: [{ id: 'r1', building: 'المبنى أ', floor_range: 'أرضي', component: 'سكني' }],
          checks: [], issues: [] },
        distributionChat: { turns: [{ role: 'user', text: 'سؤال قديم' }],
          memory: 'ذاكرة قديمة', decisions: ['قرار قديم'] } } });

    context.renderVisualConceptPlansWorkflow();
    const html = root.innerHTML;
    // The two one-click actions the client asked for.
    assert.ok(html.includes('data-plans-workflow-action="distribution-chat-start"'));
    assert.ok(html.includes('data-plans-workflow-action="distribution-chat-restart"'));
    assert.ok(html.includes('توزيع الأدوار'));
    assert.ok(html.includes('ابدأ من جديد'));

    await context.restartVisualConceptDistributionChat();

    // The old floors, the old notes and the old thread are gone — and
    // nothing was sent: the client writes the notes first.
    const workflow = context.tenantVisualConceptState.plansWorkflow;
    assert.equal(workflow.distribution.rows.length, 0);
    assert.equal(workflow.distributionNotes, '');
    assert.equal(workflow.distributionChat.turns.length, 0);
    assert.equal(workflow.distributionChat.memory, '');
    assert.equal(workflow.distributionChat.fresh, true);
    assert.equal(calls.length, 0);

    // The first turn after the clean start is a fresh proposal, not a
    // continuation of what was dropped.
    await context.sendVisualConceptDistributionChat('السكن في الطابق الثاني');
    assert.equal(calls[0].body.reset, true);
    assert.equal(calls[0].body.distribution.rows.length, 0);
    assert.equal(calls[0].body.history.length, 0);
    assert.equal(calls[0].body.memory, '');
  });

  test('the loader names the step the server is on and the time it takes', async () => {
    const context = fixture();
    const messages = [];
    const steps = [];
    let polls = 0;
    context.setTimeout = fn => setTimeout(fn, 0);
    context.hasPermission = () => true;
    context.showLoader = () => {};
    context.hideLoader = () => {};
    context.toast = () => {};
    context.markVisualConceptDirty = () => {};
    context.renderVisualConceptPage = () => {};
    context.updateLoaderMessage = text => messages.push(text);
    context.updateLoaderProgress = (pct, step) => steps.push([pct, step]);
    context.collectVisualConceptPlansWorkflowPayload = async () => ({
      plansWorkflow: { distribution: { rows: [] } }, projectData: {} });
    context.api = async (method) => {
      if (method === 'POST') {
        return { success: true, jobId: 'job-9', status: 'queued', timeoutSeconds: 600 };
      }
      polls += 1;
      if (polls === 1) {
        return { status: 'running', success: true, todos: [
          { id: '1', label: 'قراءة بيانات المشروع والتوزيع', status: 'done' },
          { id: '2', label: 'اقتراح توزيع الأدوار', status: 'active' },
          { id: '3', label: 'مراجعة النتيجة', status: 'pending' },
        ] };
      }
      return { status: 'completed', success: true, result: {
        success: true, action: 'explain', reply: 'تمام.', rows: [], checks: [], issues: [] } };
    };
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {},
      plansWorkflow: { viewStage: 'boundary', verification: { approved: true },
        distribution: { approved: false, aiReviewed: false, rows: [], checks: [], issues: [] } } });

    await context.sendVisualConceptDistributionChat('اقترح توزيعًا');

    // The work itself is on the screen, not only a clock.
    assert.equal(messages.length > 0, true);
    assert.match(messages[messages.length - 1], /اقتراح توزيع الأدوار/);
    assert.match(messages[messages.length - 1], /قراءة بيانات المشروع والتوزيع/);
    assert.equal(steps.length > 0, true);
    assert.equal(steps.some(entry => /يعمل الآن/.test(entry[1])), true);
  });

  test('the words the model has already written show in the chat, not in the loader', async () => {
    const context = fixture();
    const messages = [];
    const bubble = { textContent: '' };
    let polls = 0;
    context.setTimeout = fn => setTimeout(fn, 0);
    context.hasPermission = () => true;
    context.showLoader = () => {};
    context.hideLoader = () => {};
    context.toast = () => {};
    context.markVisualConceptDirty = () => {};
    context.renderVisualConceptPage = () => {};
    context.updateLoaderMessage = text => messages.push(text);
    context.document.querySelector = selector =>
      selector === '[data-plans-distribution-chat-partial]' ? bubble : null;
    context.collectVisualConceptPlansWorkflowPayload = async () => ({
      plansWorkflow: { distribution: { rows: [] } }, projectData: {} });
    context.api = async (method) => {
      if (method === 'POST') {
        return { success: true, jobId: 'job-10', status: 'queued', timeoutSeconds: 600 };
      }
      polls += 1;
      if (polls === 1) {
        return { status: 'running', success: true, partial: 'السكن في الطابق الثاني',
          todos: [{ id: '1', label: 'اقتراح توزيع الأدوار', status: 'active' }] };
      }
      return { status: 'completed', success: true, result: {
        success: true, action: 'update', reply: 'السكن في الطابق الثاني',
        rows: [{ id: 'r1', building: 'المبنى أ', floor_range: '2', component: 'سكني' }],
        checks: [], issues: [], canProceed: true } };
    };
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {},
      plansWorkflow: { viewStage: 'boundary', verification: { approved: true },
        distribution: { approved: false, aiReviewed: false, rows: [], checks: [], issues: [] } } });

    await context.sendVisualConceptDistributionChat('وزّع الأدوار', { expectsTable: true });

    // The answer belongs to the conversation, not to the progress card.
    assert.equal(bubble.textContent, 'السكن في الطابق الثاني');
    assert.equal(messages.some(text => text.includes('السكن في الطابق الثاني')), false);
    // The loader carries the work, in words.
    assert.equal(messages.some(text => text.includes('اقتراح توزيع الأدوار')), true);
    const workflow = context.tenantVisualConceptState.plansWorkflow;
    assert.equal(workflow.distribution.rows.length, 1);
    assert.equal(workflow.distributionChat.turns[1].text, 'السكن في الطابق الثاني');
  });

  test('a cancelled clean start leaves the floors and the thread as they were', async () => {    const context = fixture();
    context.hasPermission = () => true;
    context.confirm = () => false;
    context.toast = () => {};
    context.markVisualConceptDirty = () => assert.fail('a cancelled reset must not write');
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {},
      plansWorkflow: { verification: { approved: true },
        distribution: { rows: [{ id: 'r1', building: 'المبنى أ', component: 'سكني' }] },
        distributionChat: { turns: [{ role: 'user', text: 'سؤال قديم' }], memory: 'ذاكرة' } } });

    assert.equal(await context.restartVisualConceptDistributionChat(), false);
    const workflow = context.tenantVisualConceptState.plansWorkflow;
    assert.equal(workflow.distribution.rows.length, 1);
    assert.equal(workflow.distributionChat.turns.length, 1);
  });
};
