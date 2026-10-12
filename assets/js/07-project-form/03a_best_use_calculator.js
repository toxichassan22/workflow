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
