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
};
