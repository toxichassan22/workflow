'use strict';

const assert = require('node:assert/strict');

module.exports = function registerJobErrorTests({ test, fixture }) {
  test('failed site-plan jobs show the server reason under the failed step', async () => {
    const context = fixture();
    const failure = 'المساحة المعتمدة «Pool <img>» لا تتسع داخل حدود الأرض.';
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {}, plansWorkflow: { jobTodos: [
        { id: '2', label: 'تجهيز المشهد الهندسي', status: 'active' },
      ] },
    });
    context.markVisualConceptDirty = () => {};
    context.setTimeout = callback => { callback(); return 1; };
    context.api = async () => ({ jobId: 'failed-job', status: 'queued', timeoutSeconds: 600 });
    context.apiWithTimeout = async () => ({
      status: 'failed', success: false,
      todos: [{ id: '2', label: 'تجهيز المشهد الهندسي', status: 'failed' }],
      result: { success: false, error: failure, error_code: 'PLANS_SITE_AREA_CONFLICT' },
    });

    const result = await context.visualConceptPlanJobApi(
      'POST', '/api/visual-concept/site-plan-assistant', {});
    const workflow = context.visualConceptPlansWorkflowState();
    const markup = context.visualConceptPlanTodoMarkup(workflow.jobTodos, workflow.jobError);

    assert.equal(result.error, failure);
    assert.equal(workflow.jobError, failure);
    assert.equal(workflow.jobTodos[0].error, failure);
    assert.match(markup, /class="visual-plan-job-error"/);
    assert.match(markup, /&lt;img&gt;/);
    assert.doesNotMatch(markup, /<img>/);
  });

  test('a successful completed job clears a stale failed-step marker', () => {
    const context = fixture();
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {}, plansWorkflow: { jobTodos: [
        { id: '2', label: 'تجهيز المشهد الهندسي', status: 'failed', error: 'خطأ قديم' },
      ], jobError: 'خطأ قديم' },
    });
    context.markVisualConceptDirty = () => {};
    const todoPanel = { innerHTML: '' };
    context.document.querySelector = selector => selector === '[data-plans-workflow-todos]'
      ? todoPanel : null;
    context.document.getElementById = () => null;

    context.updateVisualConceptPlanJobUi({
      status: 'completed', success: true,
      todos: [{ id: '2', label: 'تجهيز المشهد الهندسي', status: 'failed', error: 'خطأ قديم' }],
      result: { success: true },
    });

    const workflow = context.visualConceptPlansWorkflowState();
    assert.equal(workflow.jobError, '');
    assert.equal(workflow.jobTodos[0].status, 'done');
    assert.doesNotMatch(todoPanel.innerHTML, /تعذر/);
  });
};
