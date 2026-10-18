'use strict';

const assert = require('node:assert/strict');

module.exports = function registerSiteAssistantPayloadTests({ test, fixture }) {
  test('site assistant payload keeps approved project facts and removes unrelated bulk and stale components', async () => {
    const context = fixture();
    const projectData = {
      project_name: 'المشروع الحالي',
      approved_financial_area: '24912.95',
      croquis_land_area: '1000',
      project_components_data: '[]',
      financial_study_model: { dynamicRows: { components: [
        { id: 'deleted-villa', name: 'فلل محذوفة', builtArea: 12000 },
      ] } },
      survey_coordinates: [{ point: '1', eastings: 400000, northings: 2000000 }],
      land_documents_analysis: {
        summary: 'ملخص الاشتراطات الحالية.',
        rawText: 'نص خام كبير'.repeat(20000),
        parcels: [{ setbacks: '3 م من الجهات الأربع.' }],
      },
      unrelated_project_blob: 'بيانات لا تخص المخطط'.repeat(20000),
    };
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {}, plansWorkflow: {
        verification: { approved: true, summary: 'فحص سابق طويل لا يحتاجه الشات.' },
        boundary: { points: [{ point: '1', eastings: 400000, northings: 2000000 }],
          approved: true, referenceUrl: 'data:image/png;base64,large-boundary' },
        distribution: { approved: true, rows: [{ id: 'parking-row', component: 'المواقف',
          floor_area_sqm: 9000, notes: 'إبقاء مدخل الخدمة خاليًا.' }],
          totals: [{ label: 'ملخص قديم' }], checks: [{ detail: 'فحص سابق' }] },
        clientNotes: 'الملاحظات الحالية.', distributionNotes: 'الملاحظات المسجلة للتوزيع.',
        notesReview: { verified: true, canProceed: true, inputSignature: 'signature',
          token: 'review-token', checks: [{ index: 0 }], issues: [] },
        scene: { version: 1, token: 'scene-token', inputSignature: 'same-input' },
        jobTodos: [{ id: '1', label: 'مهمة قديمة', status: 'done' }],
        prompts: { site: 'وصف سابق كبير' },
        siteAssistant: { inputSignature: 'same-input', checkpoints: { components: 'X'.repeat(50000) } },
      },
    });
    context.collectVisualConceptPayload = async () => ({
      slotId: 'plan_site', projectData: { ...projectData },
      creativeImages: { cover: 'data:image/png;base64,large-image' },
      coverImage: 'data:image/png;base64,large-cover', coverFileId: 'cover-id',
      planImages: { site: 'data:image/png;base64,large-plan' },
      currentPrompt: 'old prompt', prompt: 'old prompt',
    });

    const payload = await context.collectVisualConceptPlansWorkflowPayload({ siteAssistantContext: true });

    assert.equal(payload.projectData.approved_financial_area, '24912.95');
    assert.equal(payload.projectData.croquis_land_area, '1000');
    assert.deepEqual(JSON.parse(JSON.stringify(payload.projectData.project_components_data)), []);
    assert.equal(payload.projectData.land_documents_analysis.summary, 'ملخص الاشتراطات الحالية.');
    assert.equal(payload.projectData.land_documents_analysis.parcels[0].setbacks, '3 م من الجهات الأربع.');
    assert.equal(Object.hasOwn(payload.projectData.land_documents_analysis, 'rawText'), false);
    assert.equal(Object.hasOwn(payload.projectData, 'financial_study_model'), false);
    assert.equal(Object.hasOwn(payload.projectData, 'unrelated_project_blob'), false);
    assert.deepEqual(Object.keys(payload).sort(), ['plansWorkflow', 'projectData', 'slotId']);
    assert.equal(JSON.stringify(payload).includes('data:image'), false);
    assert.deepEqual(Object.keys(payload.plansWorkflow).sort(), [
      'boundary', 'clientNotes', 'distribution', 'distributionNotes',
      'notesReview', 'scene', 'siteAssistant', 'verification',
    ]);
    assert.equal(payload.plansWorkflow.distribution.rows[0].notes, 'إبقاء مدخل الخدمة خاليًا.');
    assert.equal(payload.plansWorkflow.notesReview.token, 'review-token');
    assert.equal(payload.plansWorkflow.boundary.points[0].eastings, 400000);
    assert.deepEqual(JSON.parse(JSON.stringify(payload.plansWorkflow.siteAssistant.checkpoints)), {});
    assert.equal(JSON.stringify(payload).includes('وصف سابق كبير'), false);
    assert.ok(JSON.stringify(payload.projectData).length < 20000);

    const generationPayload = await context.collectVisualConceptPlansWorkflowPayload({
      siteAssistantContext: true, assistantAction: 'generate',
    });
    assert.equal(generationPayload.plansWorkflow.siteAssistant.checkpoints.components.length, 50000);
  });

  test('distribution row notes survive workflow normalization for Argon', () => {
    const context = fixture();
    const workflow = context.normalizeVisualConceptPlansWorkflow({ distribution: { rows: [{
      id: 'parking-row', building: 'المواقف', component: 'مواقف سطحية',
      floor_range: 'سطحي', units_per_floor: 250, floor_area_sqm: 9000,
      circulation: 'ممر خدمة جانبي', notes: 'اترك مدخل الإسعاف خاليًا.',
    }] } });

    assert.equal(workflow.distribution.rows[0].notes, 'اترك مدخل الإسعاف خاليًا.');
    assert.equal(workflow.distribution.rows[0].circulation, 'ممر خدمة جانبي');
  });

  test('rebasing stale site-plan context clears the cached scene before continuing', () => {
    const context = fixture(true);
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: { plan_site: { svgCode: '<svg>old layout</svg>', imageUrl: '/old.svg' } },
      plansWorkflow: { scene: { version: 1, inputSignature: 'old-input', buildings: [
        { id: 'deleted-villa', name: 'فلل محذوفة' },
      ] } },
    });
    context.markVisualConceptDirty = () => {};

    context.applyVisualConceptSiteAssistantResponse({
      contextChanged: true,
      assistantState: { turns: [{ role: 'assistant', text: 'أراجع المدخلات الحالية.' }] },
    });

    assert.equal(context.tenantVisualConceptState.plansWorkflow.scene, null);
    assert.equal(context.tenantVisualConceptState.plansWorkflow.sourceStamp, '');
    assert.equal(context.tenantVisualConceptState.slots.plan_site.svgCode, '');
    assert.equal(context.tenantVisualConceptState.slots.plan_site.imageUrl, '');
  });

  test('long Argon site-plan replies survive response handling and draft normalization', () => {
    const context = fixture(true);
    const fullReply = ('تفصيل المخطط الحالي. '.repeat(900)).trim();
    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: { plan_site: { chat: [] } }, plansWorkflow: { siteAssistant: { turns: [] } },
    });
    context.markVisualConceptDirty = () => {};

    context.applyVisualConceptSiteAssistantResponse({
      reply: fullReply,
      assistantState: { turns: [{ role: 'assistant', text: fullReply.slice(0, 4000), choices: [] }] },
    });

    const restored = context.normalizeVisualConceptState(context.tenantVisualConceptState);
    assert.equal(restored.slots.plan_site.chat[0].text.length, fullReply.length);
    assert.equal(restored.slots.plan_site.chat[0].text.slice(-80), fullReply.slice(-80));
  });
};
