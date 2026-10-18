'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');

module.exports = function registerSiteChatDisplayTests({ test, fixture, vm, path }) {
  test('site chat merges the assistant reply and question into one message with one choice set', () => {
    const context = fixture(true);
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {}, plansWorkflow: {},
    });
    context.markVisualConceptDirty = () => {};
    const reply = 'المساحة المتاحة للتوزيع 750 مترًا مربعًا.';
    const question = 'يرجى تحديد الخيار المعتمد لمعالجة التعارض.';
    const choice = 'إعادة توزيع المواقف';

    context.applyVisualConceptSiteAssistantResponse({
      reply,
      question,
      choices: [choice],
      assistantState: { turns: [
        { role: 'user', text: 'راجع المخطط.' },
        { role: 'assistant', text: reply, choices: [choice] },
      ] },
    });

    const chat = context.tenantVisualConceptState.slots.plan_site.chat;
    assert.equal(chat.filter(item => item.role === 'assistant').length, 1);
    assert.equal(chat[1].text, reply + '\n\n' + question);
    assert.deepEqual(JSON.parse(JSON.stringify(chat[1].choices)), [choice]);
    const card = context.renderVisualConceptSitePlanCard();
    assert.equal((card.match(/data-choice="إعادة توزيع المواقف"/g) || []).length, 1);
  });

  test('successful plan completion removes the task list and its status label', () => {
    const context = fixture();
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {}, plansWorkflow: { jobTodos: [
        { id: '1', label: 'فحص بيانات الأرض والتوزيع', status: 'active' },
      ] },
    });
    context.markVisualConceptDirty = () => {};
    const status = { textContent: 'المرحلة الحالية: فحص بيانات الأرض والتوزيع' };
    const todoPanel = { innerHTML: '<ol>قيد التنفيذ</ol>' };
    context.document.querySelector = selector => selector === '[data-site-chat-status]'
      ? status : selector === '[data-plans-workflow-todos]' ? todoPanel : null;
    context.document.getElementById = () => null;

    context.updateVisualConceptPlanJobUi({ status: 'completed', success: true,
      todos: [{ id: '1', label: 'فحص بيانات الأرض والتوزيع', status: 'done' }] });

    const workflow = context.visualConceptPlansWorkflowState();
    assert.deepEqual(JSON.parse(JSON.stringify(workflow.jobTodos)), []);
    assert.equal(todoPanel.innerHTML, '');
    assert.equal(status.textContent, '');
    assert.doesNotMatch(context.renderVisualConceptSitePlanCard(), /visual-plan-job-todos|مكتمل/);

    context.tenantVisualConceptState.plansWorkflow.jobTodos = [
      { id: '2', label: 'تحليل المتطلبات', status: 'done' },
    ];
    todoPanel.innerHTML = '<ol>مكتمل</ol>';
    status.textContent = 'المرحلة الحالية: تحليل المتطلبات';
    context.updateVisualConceptPlanJobUi({ status: 'completed', success: true });
    assert.deepEqual(JSON.parse(JSON.stringify(
      context.visualConceptPlansWorkflowState().jobTodos)), []);
    assert.equal(todoPanel.innerHTML, '');
    assert.equal(status.textContent, '');
  });

  test('site plan chat uses the full row and keeps its preview below the conversation', () => {
    const context = fixture();
    context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {}, plansWorkflow: {} });
    const card = context.renderVisualConceptSitePlanCard();
    const cssPath = path.resolve(__dirname, '../../../assets/css/base/08_shell_chrome.css');
    const css = fs.readFileSync(cssPath, 'utf8');

    assert.ok(card.indexOf('<section class="visual-plan-site-chat-panel"')
      < card.indexOf('<aside class="visual-plan-site-preview-panel"'));
    assert.match(css, /\.visual-plan-site-layout\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s);
    assert.doesNotMatch(css, /\.visual-plan-site-preview-panel\s*\{\s*order:\s*-1/s);
  });

  test('site plan status follows the active backend progress step', () => {
    const context = fixture();
    context.tenantVisualConceptState = context.normalizeVisualConceptState({ slots: {}, plansWorkflow: {} });
    const status = { textContent: '' };
    const todoPanel = { innerHTML: '' };
    context.document.querySelector = selector => selector === '[data-site-chat-status]'
      ? status : selector === '[data-plans-workflow-todos]' ? todoPanel : null;
    context.document.getElementById = () => null;

    context.updateVisualConceptPlanJobUi({ status: 'running', progress: 82, todos: [
      { id: '1', label: 'فحص بيانات الأرض والتوزيع', status: 'done' },
      { id: '2', label: 'تجهيز المشهد الهندسي', status: 'done' },
      { id: '3', label: 'مراجعة الإجابات السابقة', status: 'done' },
      { id: '4', label: 'تحليل المتطلبات وتحديد السؤال', status: 'active' },
    ] });

    assert.equal(status.textContent, 'المرحلة الحالية: تحليل المتطلبات وتحديد السؤال');
  });

  test('a rebased site scene clears its approval and returns dependent plans to review', () => {
    const context = fixture(true);
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {
        plan_site: { imageUrl: '/site.png', approvedImageUrl: '/site.png', status: 'approved' },
        plan_uses: { imageUrl: '/uses.png', approvedImageUrl: '/uses.png', status: 'approved',
          sceneToken: 'old-scene' },
      },
      plansWorkflow: { scene: { version: 1, token: 'old-scene' }, siteAssistant: { turns: [] } },
    });
    context.visualConceptPlanInputStamp = () => 'current-input';
    context.markVisualConceptDirty = () => {};

    context.applyVisualConceptSiteAssistantResponse({
      contextChanged: true,
      scene: { version: 1, token: 'new-scene' },
      assistantState: { turns: [{ role: 'assistant', text: 'What is the main entry?' }] },
    });

    assert.equal(context.tenantVisualConceptState.plansWorkflow.scene.token, 'new-scene');
    assert.equal(context.tenantVisualConceptState.slots.plan_site.approvedImageUrl, '');
    assert.equal(context.tenantVisualConceptState.slots.plan_uses.approvedImageUrl, '');
    assert.equal(context.tenantVisualConceptState.slots.plan_uses.imageUrl, '/uses.png');
    assert.equal(context.tenantVisualConceptState.slots.plan_uses.status, 'review');
  });

  test('stage three ignores a second chat send while its current request is active', async () => {
    const context = fixture(true);
    let apiCalls = 0;
    context.api = async () => { apiCalls += 1; return { success: true }; };
    vm.runInContext('visualConceptSiteAssistantBusy = true', context);

    await context.sendVisualConceptChat('plan_site');
    assert.equal(apiCalls, 0);
  });
};
