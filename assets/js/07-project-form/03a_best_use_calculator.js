    function applyBestUseFinancialModel(response) {
      const model = bestUseObject(response.financialModel);
      tenantProjectData.financial_study_model = model;
      tenantProjectData.project_components_data = response.projectComponentsData || JSON.stringify(model.dynamicRows?.components || []);
      tenantProjectData.financial_calc_data = response.financialCalcData || JSON.stringify(model.financialCalcData || {});
      window.__batchLoading = true;
      try {
        const body = document.querySelector('#componentsTable tbody');
        if (body) { body.replaceChildren(); (model.dynamicRows?.components || []).forEach(addComponent); }
        ['builtUpAreaAbove', 'basementArea'].forEach(key => {
          const input = document.getElementById(key);
          if (input && model.inputs?.[key] !== undefined) input.value = String(model.inputs[key]);
        });
        if (typeof updateRevenueComponentOptions === 'function') updateRevenueComponentOptions();
        const revenues = Object.fromEntries((model.dynamicRows?.revenue || []).map(row => [row.id, row]));
        document.querySelectorAll('#revenueTable tbody tr').forEach(row => {
          const saved = revenues[row.dataset.revenueKey];
          if (!saved) return;
          row.dataset.componentId = saved.componentId || '';
          const select = row.querySelector('[data-field="component"] select');
          if (select) select.value = row.dataset.componentId;
        });
      } finally { window.__batchLoading = false; }
      if (typeof calculateAll === 'function') calculateAll();
      if (typeof persistFinancialStudyDraftState === 'function') persistFinancialStudyDraftState();
      if (typeof triggerAutoSaveDraft === 'function') triggerAutoSaveDraft();
    }

    function bestUseRevenuePotentialHtml(metric) {
      if (!metric) return '';
      const labels = {
        comparable: WFT('best_use_explore.comparable', 'قابل للمقارنة على أساس موحد'),
        insufficient_data: WFT('best_use_explore.insufficient', 'بيانات غير كافية للمقارنة المالية'),
        mixed_basis: WFT('best_use_explore.mixed', 'أسس البيع والإيجار منفصلة؛ لا يوجد ترتيب إجمالي')
      };
      const values = [
        [WFT('best_use_explore.sale_potential', 'إمكان إيراد البيع التقديري'), metric.saleTotal],
        [WFT('best_use_explore.rent_potential', 'إمكان إيراد الإيجار السنوي التقديري'), metric.annualRentTotal]
      ].filter(([, value]) => value !== null && value !== undefined);
      return '<section class="best-use-revenue"><span class="best-use-note-tag">'
        + WFT('best_use_explore.note_tag', 'ملاحظة توضيحية') + '</span><h5>'
        + WFT('best_use_explore.revenue_title', 'إمكان الإيراد التقديري') + '</h5>'
        + values.map(([label, value]) => '<p>' + escapeHtml(label) + ': ' + bestUseFormat(value) + ' '
          + WFT('best_use_explore.currency', 'ريال سعودي') + '</p>').join('')
        + '<p>' + escapeHtml(labels[metric.comparisonStatus] || labels.insufficient_data) + '</p>'
        + (metric.rank ? '<p>' + WFT('best_use_explore.rank', 'الترتيب ضمن الأساس المتجانس: {n}', { n: metric.rank }) + '</p>' : '')
        + '<p>' + WFT('best_use_explore.planning_only', 'سيناريو تخطيطي لا يشمل التكاليف أو صافي العائد.') + '</p></section>';
    }
