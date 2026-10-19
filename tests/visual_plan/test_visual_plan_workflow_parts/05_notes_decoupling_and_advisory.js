'use strict';

const assert = require('node:assert/strict');

module.exports = function registerNotesDecouplingAndAdvisoryTests({ test, fixture, plain }) {
  test('typing client notes or distribution notes preserves distribution review and checks', () => {
    const context = fixture();
    context.tenantVisualConceptState = {
      slots: { plan_site: { imageUrl: '/uploads/creative/site.png' } },
      plansWorkflow: context.normalizeVisualConceptPlansWorkflow({
        clientNotes: 'ملاحظة أولية',
        distributionNotes: 'ملاحظة توزيع سابقة',
        promptReady: true,
        notesReview: { verified: true, canProceed: true, token: 'notes-token' },
        distribution: {
          approved: true,
          aiReviewed: true,
          reviewSignature: 'dist-sig-123',
          checks: [
            { item: 'الارتفاع', result: 'مطابق', detail: '18 طابقاً مطابقة لاشتراطات طريق المدينة' },
            { item: 'دراسة مرورية', result: 'يحتاج تأكيد', detail: 'يلزم إعداد دراسة مرورية TIA وفق دليل المباني العالية' },
          ],
          issues: [],
          canProceed: true,
        },
        siteAssistant: {
          inputSignature: 'chat-sig-1',
          turns: [{ role: 'assistant', text: 'مرحباً، تم تحليل المخطط' }],
        },
      }),
    };
    context.markVisualConceptDirty = () => {};

    // User types new notes
    context.setVisualConceptPlanNotes('توجيه جديد من العميل للتصميم');

    const wf = context.tenantVisualConceptState.plansWorkflow;
    assert.equal(wf.clientNotes, 'توجيه جديد من العميل للتصميم');
    // Only notesReview is invalidated, distribution review and checks are preserved
    assert.equal(wf.notesReview.verified, false);
    assert.equal(wf.distribution.aiReviewed, true);
    assert.equal(wf.distribution.approved, true);
    assert.equal(wf.distribution.reviewSignature, 'dist-sig-123');
    assert.equal(wf.distribution.checks.length, 2);
    // Site assistant chat turns are not wiped by typing notes
    assert.equal(wf.siteAssistant.turns.length, 1);
  });

  test('passive syncVisualConceptPlanInputs on reload does not wipe approved verification or distribution review', () => {
    const context = fixture();
    const workflow = context.normalizeVisualConceptPlansWorkflow({
      viewStage: 'generate',
      inputStamp: 'old-stamp',
      distributionRowStamp: 'rows-stamp-1',
      verification: {
        approved: true,
        canProceed: true,
        summary: 'تم التحقق بنجاح من مساحات الأرض',
        checks: [{ item: 'المساحة', result: 'مطابق' }],
      },
      distribution: {
        approved: true,
        aiReviewed: true,
        reviewSignature: 'dist-sig-1',
        checks: [{ item: 'المواقف', result: 'مطابق' }],
        issues: [],
        canProceed: true,
      },
      boundary: {
        approved: true,
        points: [{ point: '1', eastings: 500000, northings: 2000000 }],
      },
    });

    const projectData = {
      project_name: 'مشروع الفندق',
      approved_financial_area: '15000',
      croquis_land_area: '3500',
      survey_coordinates: [{ point: '1', eastings: 500000, northings: 2000000 }],
    };

    // Calling syncVisualConceptPlanInputs should update the stamp without wiping verification or distribution review
    context.syncVisualConceptPlanInputs(workflow, projectData);

    assert.equal(workflow.verification.approved, true);
    assert.equal(workflow.verification.canProceed, true);
    assert.equal(workflow.distribution.approved, true);
    assert.equal(workflow.distribution.aiReviewed, true);
    assert.equal(workflow.viewStage, 'generate');
    assert.equal(workflow.distribution.checks.length, 1);
  });

  test('isAdvisoryOrCompliantNotice classifies compliance notes and procedural advisories as non-conflicts', () => {
    const context = fixture();

    // Procedural advisories and confirmations of compliance
    assert.equal(context.isAdvisoryOrCompliantNotice('يلزم إعداد دراسة مرورية TIA للمشروع'), true);
    assert.equal(context.isAdvisoryOrCompliantNotice('المبنى يخضع لدليل المباني العالية'), true);
    assert.equal(context.isAdvisoryOrCompliantNotice('وهو ما يطابق الارتفاع المعتمد على طريق المدينة'), true);
    assert.equal(context.isAdvisoryOrCompliantNotice('مطابق لكود البناء السعودي'), true);
    assert.equal(context.isAdvisoryOrCompliantNotice('وفق نظام واشتراطات أمانة جدة'), true);

    // Genuine conflicts
    assert.equal(context.isAdvisoryOrCompliantNotice('تجاوز نسبة البناء بـ 1500م² عن الحد الأقصى'), false);
    assert.equal(context.isAdvisoryOrCompliantNotice('الارتداد الشمالي 2م وهو مخالف للحد الأدنى 4م'), false);
    assert.equal(context.isAdvisoryOrCompliantNotice('عجز في عدد مواقف السيارات بمقدار 45 موقف'), false);
  });

  test('visualConceptDistributionBlocking ignores advisory and compliant notices', () => {
    const context = fixture();

    // Workflow with advisory items labeled as 'يحتاج تأكيد' or containing TIA notes
    const advisoryWorkflow = context.normalizeVisualConceptPlansWorkflow({
      distribution: {
        aiReviewed: true,
        checks: [
          { item: 'الارتفاع', result: 'يحتاج تأكيد', detail: 'يلزم دراسة مرورية TIA وفق اشتراطات المباني العالية' },
          { item: 'الارتدادات', result: 'مطابق', detail: 'مطابق للاشتراطات' },
        ],
        issues: [],
      },
    });
    assert.equal(context.visualConceptDistributionBlocking(advisoryWorkflow.distribution).length, 0);

    // Workflow with a real unresolved conflict
    const blockingWorkflow = context.normalizeVisualConceptPlansWorkflow({
      distribution: {
        aiReviewed: true,
        checks: [
          { item: 'نسبة التغطية', result: 'متعارض', detail: 'تجاوز نسبة التغطية المسموحة بنسبة 15%' },
        ],
        issues: [{ title: 'تجاوز التغطية', severity: 'high' }],
      },
    });
    assert.ok(context.visualConceptDistributionBlocking(blockingWorkflow.distribution).length > 0);
  });

  test('renderVisualConceptPlansWorkflow displays advisory notices in info containers rather than conflict warnings', () => {
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
          rows: [{ id: 'b1', name: 'برج فندقي', floors: '18', footprintSqm: '1200', builtAreaSqm: '21600' }],
          checks: [
            { item: 'الارتفاع والأدوار', result: 'يحتاج تأكيد', detail: '18 طابقاً مطابقة للمعتمد على طريق المدينة، ويلزم دراسة مرورية TIA' },
          ],
          issues: [],
          canProceed: true,
        },
      },
    });

    context.renderVisualConceptPlansWorkflow();
    const html = root.innerHTML;
    // Advisory item should be in plans-workflow-info, not plans-workflow-notice
    assert.ok(html.includes('plans-workflow-info'));
    // Should NOT have the red conflict notice container
    assert.ok(!html.includes('plans-workflow-notice'));
  });

  test('approveVisualConceptPlansDistribution approves directly without disclaimer modal when only advisory items exist', async () => {
    const context = fixture();
    let riskModalShown = false;
    context.showVisualConceptDistributionRisk = () => { riskModalShown = true; };
    context.hasPermission = () => true;
    context.visualConceptSlotLocked = () => false;
    context.visualConceptPlanJobApi = async () => ({ success: true });
    context.renderVisualConceptPage = () => {};

    context.tenantVisualConceptState = context.normalizeVisualConceptState({
      slots: {},
      plansWorkflow: {
        viewStage: 'boundary',
        verification: { approved: true, canProceed: true },
        boundary: { approved: true },
        distribution: {
          approved: false,
          aiReviewed: true,
          rows: [{ id: 'b1', building: 'برج فندقي', floor_range: '1-18', component: 'فندق', floor_area_sqm: 1200 }],
          checks: [
            { item: 'الارتفاع', result: 'يحتاج تأكيد', detail: 'المبنى 18 طابقاً وهو ما يطابق الارتفاع المعتمد ويلزم دراسة TIA' },
          ],
          issues: [],
          canProceed: true,
        },
      },
    });

    context.approveVisualConceptPlansDistribution();

    assert.equal(riskModalShown, false);
    assert.equal(context.tenantVisualConceptState.plansWorkflow.distribution.approved, true);
  });
};
