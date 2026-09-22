/* 10-financial-report-timeline.js - index.html lines 17234-18625, shared global scope, classic scripts in order */

    function recalcFinancials() {
      calculateAll();
    }

    function collectFinancialDataRows(tableId) {
      const table = document.getElementById(tableId);
      if (!table) return [];
      return [...table.querySelectorAll('tbody tr')].map(row => {
        const result = {};
        row.querySelectorAll('[data-field]').forEach(cell => {
          const control = cell.querySelector('input,select,textarea');
          if (!control) return;
          result[cell.dataset.field] = control.type === 'checkbox'
            ? Boolean(control.checked)
            : (isFinancialNumericControl(control) ? parseNumber(control.value) : control.value);
          if (cell.dataset.field === 'customFormula') result.formula = control.value;
        });
        if (tableId === 'scheduleTable') {
          result.year = row.dataset.stageYear || result.year || 1;
          result.endYear = row.dataset.stageEndYear || result.endYear || result.year;
        }
        if (tableId === 'revenueTable') {
          const compSel = row.querySelector('[data-field="component"] select');
          result.componentId = compSel ? (compSel.value || '') : (row.dataset.componentId || result.component || '');
          if (row.dataset.revenueKey) result.id = row.dataset.revenueKey;
        }
        if (Object.entries(result).some(([key, value]) => key !== 'id' && String(value ?? '').trim() !== '')) return result;
        return null;
      }).filter(Boolean);
    }

    function collectFinancialDynamicRows() {
      return {
        components: typeof getComponentRowsData === 'function' ? getComponentRowsData() : [],
        revenue: collectFinancialDataRows('revenueTable'),
        schedule: collectFinancialDataRows('scheduleTable'),
        financeDraw: collectFinancialDataRows('financeDrawTable'),
        financeRepayment: collectFinancialDataRows('financeRepaymentTable'),
        fundAdditionalFees: collectFinancialDataRows('fundAdditionalFeesTable'),
        occupancyRamp: collectFinancialDataRows('occupancyRampTable'),
        costs: collectFinancialDataRows('costTable'),
        opex: collectFinancialDataRows('opexTable'),
        external: collectFinancialDataRows('externalTable'),
        graceSchedule: collectFinancialDataRows('graceScheduleTable'),
        sensitivity: collectSensitivityVariables()
      };
    }

    function persistFinancialStudyDraftState() {
      const root = document.getElementById('section-financial-calc');
      if (!root || typeof collectFinancialStudyModel !== 'function') return null;
      const model = collectFinancialStudyModel();
      tenantProjectData.financial_study_model = model;
      const hidden = document.getElementById('financialStudyModelData');
      if (hidden) hidden.value = JSON.stringify(model);
      return model;
    }

    function collectFinancialStudyModel() {
      if (typeof calculateAll === 'function') {
        try { calculateAll(); } catch (error) { console.warn('calculateAll failed during draft collect:', error); }
      }
      const root = document.getElementById('section-financial-calc');
      const inputs = {};
      root?.querySelectorAll('input[id],select[id],textarea[id]').forEach(el => {
        if (el.type === 'hidden') return;
        if (el.type === 'checkbox') {
          inputs[el.id] = !!el.checked;
          return;
        }
        // Persist raw numbers. money() writes "189,750,000", and putting that back into a
        // type=number field blanks the value, so the next calculateAll() treats the whole
        // finance base as zero.
        inputs[el.id] = isFinancialNumericControl(el) ? parseNumber(el.value) : (el.value ?? '');
      });
      const tables = {};
      root?.querySelectorAll('table[id]').forEach(table => {
        const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());
        tables[table.id] = Array.from(table.querySelectorAll('tbody tr')).map(tr => {
          const row = {};
          Array.from(tr.cells).forEach((cell, index) => {
            if (index >= headers.length) return;
            const control = cell.querySelector('input,select,textarea');
            row[headers[index] || ('column_' + index)] = control
              ? (control.tagName === 'SELECT' ? (control.selectedOptions?.[0]?.textContent || control.value) : control.value)
              : cell.textContent.trim();
          });
          return row;
        }).filter(row => Object.values(row).some(value => String(value ?? '').trim() !== ''));
      });
      return {
        inputs,
        tables,
        projection: roundFinancialSavedResults(window.__financialProjection || {}),
        dynamicRows: collectFinancialDynamicRows(),
        financialCalcData: (() => {
          try { return JSON.parse(document.getElementById('financialCalcData')?.value || '{}'); } catch (e) { return {}; }
        })()
      };
    }

    // The exported PDF must be the financial study exactly as the screen shows it — same field
    // labels, same option wording, same numbers — only laid out as tables. The server used to
    // rebuild it from its own label map, so «هل وحدات المشروع بيعية أم تأجيرية؟» printed as
    // «طبيعة الإيرادات» and its value printed as the raw option id «mixed».
    const FINANCIAL_REPORT_SKIP_COLUMNS = new Set(['ترتيب / حذف', 'ترتيب', 'حذف', 'مرتبط بمكون']);
    const FINANCIAL_REPORT_SKIP_IDS = new Set([
      'componentAreaValidation', 'timelineStagesWarning', 'analysisWarnings',
      'componentsAllowedUsesNote', 'sensitivityVariableSelect',
    ]);
    const FINANCIAL_REPORT_SKIP_CLASSES = [
      'help', 'hint', 'formula-tag', 'calculation-note', 'validation-panel', 'analysis-warning',
      'row-actions', 'sensitivity-picker', 'tenant-section-title', 'section-status-badge',
    ];

    function financialReportText(node) {
      return String(node?.textContent ?? '').replace(/\s+/g, ' ').trim();
    }

    function financialReportIsHidden(el) {
      return el.hidden
        || el.classList.contains('conditional-off')
        || el.classList.contains('dynamic-off')
        || el.classList.contains('hidden')
        || el.style.display === 'none';
    }

    function financialReportControlValue(control) {
      if (!control) return '';
      if (control.tagName === 'SELECT') return financialReportText(control.selectedOptions?.[0]) || String(control.value ?? '').trim();
      if (control.type === 'checkbox') return control.checked ? 'نعم' : 'لا';
      const value = String(control.value ?? '').trim();
      return isFinancialNumericControl(control) ? formatFinancialReportValue(value, financialControlContext(control)) : value;
    }

    function financialReportCellText(cell) {
      const controls = Array.from(cell.querySelectorAll('input,select,textarea')).filter(control =>
        control.type !== 'hidden'
        && !control.closest('.dynamic-off,.conditional-off,.hidden,[hidden]'));
      if (!controls.length) return financialReportText(cell);
      return controls.map(financialReportControlValue).filter(value => value !== '').join(' — ');
    }

    function financialReportTablePart(table) {
      const headerCells = Array.from(table.querySelectorAll('thead th'));
      if (!headerCells.length) return null;
      const kept = headerCells
        .map((th, index) => ({ index, text: financialReportText(th) }))
        .filter(({ index, text }) => !FINANCIAL_REPORT_SKIP_COLUMNS.has(text) && !financialReportIsHidden(headerCells[index]));
      if (!kept.length) return null;
      // A totals row lives in `tfoot`, and reading only `tbody` dropped it from the exported PDF —
      // so the stage table printed its percentages with no statement of what they summed to.
      const rows = Array.from(table.querySelectorAll('tbody tr,tfoot tr'))
        .filter(tr => !financialReportIsHidden(tr))
        .map(tr => kept.map(({ index }) => (tr.cells[index] ? financialReportCellText(tr.cells[index]) : '')))
        .filter(cells => cells.some(text => text !== '' && text !== '—'));
      return { type: 'table', headers: kept.map(({ text }) => text), rows };
    }

    function collectFinancialStudyReport() {
      const root = document.getElementById('section-financial-calc');
      if (!root) return null;
      if (typeof calculateAll === 'function') {
        try { calculateAll(); } catch (error) { console.warn('calculateAll failed during report collect:', error); }
      }
      const parts = [];
      let fields = null;
      const addField = (label, value) => {
        if (!label || value === '') return;
        if (!fields) { fields = { type: 'fields', rows: [] }; parts.push(fields); }
        fields.rows.push([label, value]);
      };
      const walk = node => {
        for (const el of node.children) {
          if (!(el instanceof HTMLElement)) continue;
          if (financialReportIsHidden(el)) continue;
          if (FINANCIAL_REPORT_SKIP_IDS.has(el.id)) continue;
          if (FINANCIAL_REPORT_SKIP_CLASSES.some(name => el.classList.contains(name))) continue;
          const tag = el.tagName;
          if (tag === 'BUTTON' || tag === 'BR' || tag === 'SMALL' || tag === 'P' || tag === 'OPTION') continue;
          if (tag === 'H2' || tag === 'H3' || tag === 'H4' || tag === 'H5') {
            const text = financialReportText(el);
            fields = null;
            if (text) parts.push({ type: 'heading', level: tag === 'H2' || tag === 'H3' ? 2 : 3, text });
            continue;
          }
          if (tag === 'TABLE') {
            fields = null;
            const part = financialReportTablePart(el);
            if (part) parts.push(part);
            continue;
          }
          if (el.classList.contains('metric')) {
            const scope = financialReportText(el.querySelector('small'));
            const value = financialReportText(el.querySelector('strong'));
            addField(financialReportText(el.querySelector('span')), scope ? value + ' — ' + scope : value);
            continue;
          }
          const label = Array.from(el.children).find(child => child.tagName === 'LABEL');
          const control = label ? el.querySelector('input,select,textarea') : null;
          if (label && control && control.type !== 'hidden') {
            addField(financialReportText(label), financialReportControlValue(control));
            continue;
          }
          if (tag === 'SPAN' || tag === 'LABEL') continue;
          walk(el);
        }
      };
      walk(root);
      const isSubstantiveFieldRow = row => {
        if (!Array.isArray(row) || row.length < 2) return false;
        const label = String(row[0] ?? '');
        const val = String(row[1] ?? '').trim();
        if (!val || val === '—' || val === '-' || val === 'null' || val === 'undefined') return false;
        if (val === 'لا' || val === 'غير مفعل' || val === 'غير مطبق' || val === 'معطل' || val === 'لا يوجد') return false;
        if (['0', '0.00', '0%', '0.0%', '0 ر.س', '0 م²'].includes(val) && /سماح|خصم|أتعاب إضافية/.test(label)) return false;
        return true;
      };

      const cleanParts = [];
      for (const part of parts) {
        if (part.type === 'fields') {
          const substantiveRows = (part.rows || []).filter(isSubstantiveFieldRow);
          if (substantiveRows.length > 0) {
            cleanParts.push({ ...part, rows: substantiveRows });
          }
        } else {
          cleanParts.push(part);
        }
      }

      // A heading with nothing under it is a section the current settings switched off. A block
      // title still counts as filled when only its own sub-headings carry the tables.
      const trimmed = cleanParts.filter((part, index) => {
        if (part.type !== 'heading') return true;
        for (let next = index + 1; next < cleanParts.length; next += 1) {
          if (cleanParts[next].type !== 'heading') return true;
          if (cleanParts[next].level <= part.level) return false;
        }
        return false;
      });
      return { title: 'الدراسة المالية والمؤشرات', parts: trimmed };
    }

    function focusFinancialValidation(validation) {
      const first = Array.isArray(validation) ? validation[0] : null;
      if (!first?.field) return;
      const target = document.getElementById(first.field) || document.querySelector('[data-field="' + first.field + '"]');
      target?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      target?.focus?.();
    }

    async function validateFinancialStudyBeforeProceed() {
      if (!document.getElementById('section-financial-calc')) return true;
      const response = await api('POST', '/api/financial-study/validate', { financialModel: collectFinancialStudyModel() });
      if (response?.success) return true;
      focusFinancialValidation(response?.validation);
      toast(response?.validation?.[0]?.message || 'استكمل المدخلات المالية المطلوبة أولًا');
      return false;
    }

    async function exportFinancialStudyPdf() {
      const model = collectFinancialStudyModel();
      // Sent for the export only, never stored in the draft.
      model.report = collectFinancialStudyReport();
      const projectName = String(tenantProjectData?.project_name || tenantProjectData?.projectName || 'الدراسة المالية').trim();
      showLoader('جاري إنشاء الدراسة المالية', 'جاري التحقق من المدخلات وبناء ملف PDF منظم...', 8);
      try {
        const response = await api('POST', '/api/financial-study/export', {
          projectName,
          presentationId: tenantPresentationId || null,
          draftId: tenantProjectData?.draftId || null,
          financialModel: model
        });
        if (!response?.success || !response.url) {
          focusFinancialValidation(response?.validation);
          toast(response?.error || response?.validation?.[0]?.message || 'لا يمكن تصدير الدراسة المالية');
          return;
        }
        updateLoaderProgress(80, 'تم إنشاء الملف، جاري تحميله...');
        const token = getTenantToken();
        const download = await fetch(response.url, { headers: token ? { Authorization: 'Bearer ' + token } : {} });
        if (!download.ok) {
          const body = await download.json().catch(() => null);
          throw new Error(body?.error || (download.status === 403 ? 'لا توجد صلاحية لتحميل الملف' : 'Download failed'));
        }
        const blob = await download.blob();
        const blobUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        const suggestedName = response.fileName || response.url.split('/').pop() || 'financial-study.pdf';
        link.href = blobUrl;
        link.download = suggestedName.endsWith('.pdf') ? suggestedName : suggestedName + '.pdf';
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(blobUrl);
        updateLoaderProgress(100, 'اكتمل تحميل الدراسة المالية');
        toast('تم تصدير الدراسة المالية وحفظها في سجل التصديرات');
      } catch (error) {
        toast('تعذر تصدير الدراسة المالية: ' + (error?.message || 'خطأ في الاتصال'));
      } finally {
        hideLoader();
      }
    }

    function printFinancialStudy() {
      calculateAll();
      if (window.__financialProjection?.areaState && !window.__financialProjection.areaState.valid) { toast('لا يمكن الطباعة: مجموع المساحات المبنية للمكونات يتجاوز مسطحات البناء فوق الأرض'); return }
      triggerAutoSaveDraft();
      const pd = (typeof tenantProjectData !== 'undefined' && tenantProjectData) || {};
      const projectName = String(pd.project_name || pd.projectName || val('projectName') || 'المشروع').trim();
      const safeTitle = projectName.replace(/[\\/:*?"<>|]+/g, '-');
      const generatedAt = new Date().toLocaleDateString('ar-SA', { year: 'numeric', month: 'long', day: 'numeric' });
      const reportWindow = window.open('', 'financialStudyReport', 'width=1280,height=900');
      if (!reportWindow) { toast('يرجى السماح بالنوافذ المنبثقة لطباعة التقرير'); return }

      const projectSummary = reportRows([
        ['اسم المشروع', projectName],
        ['نوع المشروع', pd.project_type || reportFieldValue('projectType')],
        ['المدينة', pd.city || reportFieldValue('city')],
        ['الموقع', pd.location_address || pd.location || reportFieldValue('location')],
        ['المطور / المالك', pd.developer || reportFieldValue('developer')],
        ['تاريخ إعداد التقرير', generatedAt]
      ]);
      const areaSummary = reportRows([
        ['مدة تطوير المشروع', reportFieldValue('developmentYears') + ' سنة'],
        ['عدد سنوات التشغيل', reportFieldValue('operationYears') + ' سنة'],
        ['سنة بدء بيع الوحدات', reportFieldValue('salesStartYear')],
        ['عدد سنوات بيع الوحدات', reportFieldValue('salesYears') + ' سنة'],
        ['سنة بدء التشغيل', reportFieldValue('operationStartYear')],
        ['مساحة الأرض', reportFieldValue('landArea') + ' م²'],
        ['نسبة التغطية', reportFieldValue('coverageRate') + '%'],
        ['عدد الطوابق', reportFieldValue('floorCount')],
        ['مسطحات البناء فوق الأرض', reportFieldValue('builtUpAreaAbove') + ' م²'],
        ['مساحة البدرومات', reportFieldValue('basementArea') + ' م²'],
        ['إجمالي مسطحات البناء', reportFieldValue('totalBuiltUpArea') + ' م²'],
        ['المساحة المغطاة', reportFieldValue('coveredArea') + ' م²'],
        ['المساحات المفتوحة', reportFieldValue('openArea') + ' م²'],
        ['حالة الأرض', reportFieldValue('landStatus')],
        ['معالجة الأرض في التدفقات', reportFieldValue('landContributionType')],
        ['سنة تسجيل الأرض', reportFieldValue('landContributionYear')],
        ['قيمة الأرض المحسوبة', reportFieldValue('landValue')],
        ['إيجار الأرض السنوي', reportFieldValue('annualLandRent')]
      ]);
      const costSummary = reportRows([
        ['إجمالي تكلفة التنفيذ', reportFieldValue('executionCostTotal')],
        ['إجمالي التصميم والدراسات', reportFieldValue('designCostTotal')],
        ['إجمالي رسوم الخدمات', reportFieldValue('servicesCostTotal')],
        ['إجمالي الدعاية والإعلان', reportFieldValue('advertisingCostTotal')],
        ['نسبة المطور', reportFieldValue('developerRate') + '%'],
        ['أساس احتساب أتعاب المطور', reportFieldValue('developerBase')],
        ['قيمة أساس المطور', reportFieldValue('developerBaseAmount')],
        ['إجمالي أتعاب المطور', reportFieldValue('developerCostValue')],
        ['قيمة الأرض داخل التكلفة', reportFieldValue('landCostIncluded')]
      ]);
      const financeSummary = reportRows([
        ['استخدام تمويل', reportFieldValue('financeEnabled')],
        ['أساس احتساب التمويل', reportFieldValue('financeBase')],
        ['نسبة التمويل من تكلفة المشروع', reportFieldValue('financingRate') + '%'],
        ['طريقة احتساب الفائدة', reportFieldValue('financeInterestMethod')],
        ['عدد سنوات سحب التمويل', reportFieldValue('financeDrawYears') + ' سنة'],
        ['سنة بدء سداد التمويل', reportFieldValue('financeRepaymentStartYear')],
        ['عدد سنوات سداد التمويل', reportFieldValue('financeRepaymentYears') + ' سنة'],
        ['معدل الفائدة السنوي', reportFieldValue('annualFinanceRate') + '%'],
        ['رسوم ترتيب التمويل', reportFieldValue('financeArrangementFeeRate') + '%'],
        ['قيمة أساس التمويل', reportFieldValue('financeBaseAmount')],
        ['قيمة التسهيل التمويلي', reportFieldValue('facilityAmount')],
        ['قيمة رسوم ترتيب التمويل', reportFieldValue('arrangementFeeTotal')],
        ['إجمالي فوائد التمويل', reportFieldValue('financeInterestTotal')],
        ['مساهمة الأرض العينية', reportFieldValue('landEquityContribution')],
        ['الضخ النقدي المطلوب', reportFieldValue('cashEquityRequired')],
        ['إجمالي حقوق الملكية', reportFieldValue('equityRequired')]
      ]);
      const fundSummary = reportRows([
        ['تطبيق أتعاب إدارة الصندوق', reportFieldValue('fundFeesEnabled')],
        ['أساس احتساب الأتعاب', reportFieldValue('fundFeeBase')],
        ['رأس مال الصندوق', reportFieldValue('fundCapitalInput')],
        ['نسبة أتعاب الإدارة السنوية', reportFieldValue('fundManagementRate') + '%'],
        ['فترة احتساب أتعاب الإدارة', `من السنة ${reportFieldValue('fundFeeStartYear')} إلى السنة ${reportFieldValue('fundFeeEndYear')}`],
        ['دورية السداد', reportFieldValue('fundFeeFrequency')],
        ['توقيت السداد', reportFieldValue('fundFeeTiming')],
        ['إجمالي أتعاب الإدارة', reportFieldValue('fundManagementFeesTotal')],
        ['إجمالي حافز الأداء', reportFieldValue('performanceFeeTotal')],
        ['إجمالي تكاليف الصندوق', reportFieldValue('fundFeesTotal')]
      ]);
      const bonusSummary = reportRows([
        ['نسبة المطور من الزيادة في سعر البيع', reportFieldValue('developerUpliftShare') + '%'],
        ['آلية التطبيق', 'تطبق تعاقديًا فقط على فرق الزيادة عند البيع أعلى من السعر أو القيمة المستهدفة، ولا تدخل تلقائيًا ضمن أرقام الدراسة.']
      ]);
      const reportFlags = projectModeFlags();
      const financeOn = val('financeEnabled') === 'yes';
      const fundOn = val('fundEnabled') === 'yes' && val('fundFeesEnabled') === 'yes';
      const exitOn = val('exitEnabled') === 'yes';

      const resultsList = [
        ['تكلفة المشروع قبل التمويل', reportMetricValue('resProjectCostBeforeFinance')],
      ];
      if (financeOn) {
        resultsList.push(['إجمالي تكلفة المشروع شامل التمويل', reportMetricValue('resProjectCost')]);
      }
      if (reportFlags.sales) {
        resultsList.push(['إجمالي إيرادات البيع', reportMetricValue('resSaleRevenue')]);
      }
      if (reportFlags.rental) {
        resultsList.push(['إيراد أول سنة تشغيل', reportMetricValue('resRevenueY1')]);
        resultsList.push(['NOI — السنة الأولى', reportMetricValue('resNOIY1')]);
        resultsList.push(['إيرادات التشغيل عند الوصول إلى 100% من الإشغال المستهدف', reportMetricValue('resFullOccupancyRevenue')]);
        resultsList.push(['المصروفات عند الوصول إلى 100% من الإشغال المستهدف', reportMetricValue('resFullOccupancyOpex')]);
        resultsList.push(['NOI عند الوصول إلى 100% من الإشغال المستهدف', reportMetricValue('resFullOccupancyNOI')]);
      }
      if (exitOn) {
        if (reportFlags.sales) {
          resultsList.push(['إجمالي التخارج البيعي قبل التكاليف', reportMetricValue('resSaleExitGross')]);
          resultsList.push(['صافي التخارج البيعي', reportMetricValue('resSaleExit')]);
        }
        if (reportFlags.rental) {
          resultsList.push(['إجمالي التخارج التشغيلي قبل التكاليف', reportMetricValue('resOperatingExitGross')]);
          resultsList.push(['صافي التخارج التشغيلي', reportMetricValue('resOperatingExit')]);
        }
        resultsList.push(['إجمالي صافي التخارج', reportMetricValue('resTerminal')]);
      }
      resultsList.push(['أتعاب المطور', reportMetricValue('resDevCost')]);
      if (financeOn) {
        resultsList.push(['إجمالي تكلفة التمويل', reportMetricValue('resFinanceCost')]);
      }
      if (fundOn) {
        resultsList.push(['إجمالي تكاليف الصندوق', reportMetricValue('resFundFees')]);
      }
      if (financeOn || fundOn) {
        resultsList.push(['إجمالي تكلفة الاستثمار', reportMetricValue('resTotalInvestmentCost')]);
      }
      resultsList.push(['فترة احتساب ROI', document.getElementById('resROIScope')?.textContent || '']);
      resultsList.push(['ROI', reportMetricValue('resROI')]);
      resultsList.push(['فترة احتساب Project IRR', document.getElementById('resProjectIRRScope')?.textContent || '']);
      resultsList.push(['Project IRR', reportMetricValue('resProjectIRR')]);
      if (financeOn) {
        resultsList.push(['Equity IRR', reportMetricValue('resIRR')]);
      }
      resultsList.push(['فترة استرداد المشروع', reportMetricValue('resPayback')]);
      if (financeOn) {
        resultsList.push(['فترة استرداد حقوق الملكية', reportMetricValue('resEquityPayback')]);
      }
      if (val('landContributionType') === 'inKind' || !reportValueIsZero(reportMetricValue('resLandEquity'))) {
        resultsList.push(['مساهمة الأرض العينية', reportMetricValue('resLandEquity')]);
      }
      if (financeOn) {
        resultsList.push(['الضخ النقدي المطلوب', reportMetricValue('resCashEquity')]);
      }
      resultsList.push(['إجمالي حقوق الملكية', reportMetricValue('resEquityRequired')]);

      const resultSummary = reportRows(resultsList);
      const graceReportSection = reportFlags.rental && val('graceEnabled') === 'yes' ? `<section class="section"><h3>5. فترة السماح</h3>${reportRows([['طريقة الاحتساب', reportFieldValue('graceMethod')], ['نطاق السماح', reportFieldValue('graceScope')], ['بداية السماح', reportFieldValue('graceStartYear')], ['مدة السماح بالأشهر', reportFieldValue('graceDurationMonths')], ['إجمالي الخصم', reportFieldValue('graceTotalDiscount')]])}${val('graceMethod') === 'schedule' ? reportTableSnapshot('graceScheduleTable', true, true) : ''}</section>` : '';
      const developerPaymentsReportSection = val('developerPaymentsEnabled') === 'yes' ? `<section class="section"><h3>6. مراحل التطوير ودفعات المطور</h3>${reportTableSnapshot('scheduleTable', false)}</section>` : '';
      const financeReportSection = val('financeEnabled') === 'yes' ? `<section class="section"><h3>8. هيكل تمويل</h3>${financeSummary}<h4>خطة سحب التمويل</h4>${reportTableSnapshot('financeDrawTable', false)}<h4>خطة سداد أصل التمويل</h4>${reportTableSnapshot('financeRepaymentTable', false)}<h4>حركة رصيد التمويل السنوية</h4>${reportTableSnapshot('debtScheduleTable', false)}</section>` : '';
      const fundReportSection = val('fundEnabled') === 'yes' && val('fundFeesEnabled') === 'yes' ? `<section class="section page-break"><h3>9. أتعاب إدارة الصندوق</h3>${fundSummary}<h4>الأتعاب الإضافية الاختيارية</h4>${reportTableSnapshot('fundAdditionalFeesTable', true, true)}<h4>جدول أتعاب الصندوق السنوي</h4>${reportTableSnapshot('fundFeeScheduleTable', false)}</section>` : '';
      const bonusReportSection = reportFlags.sales && val('developerBonusEnabled') === 'yes' ? `<section class="section"><h3>10. علاوة حسن أداء المطور</h3>${bonusSummary}</section>` : '';
      const externalReportSection = val('externalEnabled') === 'yes' ? `<section class="section"><h3>11. البنود الخارجية المرنة</h3>${reportTableSnapshot('externalTable', true, true)}</section>` : '';
      const clarificationText = val('financialClarifications').trim();
      const clarificationReportSection = clarificationText
        ? `<section class="section"><h3>15. الإيضاحات</h3><div class="financial-clarifications">${escapeReportHtml(clarificationText)}</div></section>`
        : '';
      const exitReportNumber = clarificationText ? 16 : 15;
      const exitReportSection = val('exitEnabled') === 'yes' ? `<section class="section"><h3>${exitReportNumber}. التخارج والافتراضات المالية</h3>${reportRows([['طريقة التخارج البيعي', reportFieldValue('saleExitMethod')], ['سنة التخارج البيعي', reportFieldValue('saleExitYear')], ['طريقة التخارج التأجيري', reportFieldValue('exitMethod')], ['سنة التخارج التأجيري', reportFieldValue('operatingExitYear')], ['مدخل التخارج التأجيري', reportFieldValue('exitInput')], ['تكاليف التخارج التأجيري', reportFieldValue('operatingExitCostRate') + '%']])}</section>` : '';
      const ideaText = pd.project_idea || pd.project_description || pd.description || val('idea') || 'تقرير مالي مبني على المدخلات والافتراضات المسجلة في النموذج.';

      reportWindow.document.open();
      reportWindow.document.write(`<!doctype html>
      <html lang="ar" dir="rtl"><head><meta charset="utf-8">
      <title>${escapeReportHtml(safeTitle)} - الدراسة المالية</title>
      <style>
      @page{size:A4 landscape;margin:10mm}
      *{box-sizing:border-box}
      body{margin:0;color:#252525;background:#fff;font-family:Tahoma,Arial,sans-serif;direction:rtl;line-height:1.45}
      .report{max-width:1120px;margin:0 auto;padding:18px}
      .cover{min-height:175mm;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;border:2px solid #123B6D;padding:30px;page-break-after:always}
      .cover .eyebrow{color:#123B6D;font-size:14px;font-weight:700;letter-spacing:.5px}
      .cover h1{font-size:34px;margin:18px 0 6px;color:#082646}
      .cover h2{font-size:24px;margin:0;color:#123B6D}
      .cover p{font-size:15px;color:#666;max-width:760px}
      .print-actions{position:sticky;top:0;z-index:5;background:#fff;padding:10px 0;text-align:left;border-bottom:1px solid #ddd}
      .print-actions button{border:0;border-radius:8px;background:#123B6D;color:#fff;padding:10px 18px;font-family:inherit;font-weight:700;cursor:pointer}
      .section{margin:0 0 20px}
      .conditional-off{display:none!important}
      .page-break{break-before:page}
      .wide-table table{font-size:8px}
      .wide-table th,.wide-table td{white-space:normal;word-break:break-word}
      h3{font-size:19px;color:#123B6D;margin:0 0 10px;padding-bottom:7px;border-bottom:2px solid #123B6D}
      h4{font-size:14px;color:#082646;margin:14px 0 7px}
      table{width:100%;border-collapse:collapse;margin:0 0 14px;font-size:9px;direction:rtl}
      thead{display:table-header-group}
      tr{break-inside:avoid}
      th,td{border:1px solid #d9d1cb;padding:6px;text-align:right;vertical-align:top;white-space:normal}
      /* Otherwise the leading minus of a money() figure lands to the right of the digits. */
      td{unicode-bidi:plaintext}
      thead th{background:#123B6D!important;color:#fff!important;font-weight:700;text-align:center}
      tbody tr:nth-child(even) td{background:#fbf7f4}
      .summary-table{font-size:11px}
      .summary-table th{width:34%;background:#EAF2F8;color:#082646}
      .summary-table td{font-weight:700}
      .empty{color:#777;border:1px dashed #ccc;padding:12px}
      .note{background:#F4F8FC;border-right:4px solid #123B6D;padding:10px 12px;font-size:10px;color:#555}
      .financial-clarifications{white-space:pre-wrap;border:1px solid #d9d1cb;padding:10px;font-size:10px;line-height:1.6}
      footer{margin-top:20px;padding-top:10px;border-top:1px solid #ddd;color:#777;font-size:9px;display:flex;justify-content:space-between}
      @media print{
        .print-actions{display:none}
        .report{max-width:none;padding:0}
        body{-webkit-print-color-adjust:exact;print-color-adjust:exact}
      }
      </style></head><body>
      <div class="report">
        <div class="print-actions"><button onclick="window.print()">طباعة / حفظ PDF</button></div>
        <section class="cover">
          <div class="eyebrow">دراسة مالية استرشادية</div>
          <h1>${escapeReportHtml(projectName)}</h1>
          <h2>التقرير المالي الكامل</h2>
          <p>${escapeReportHtml(ideaText)}</p>
          <p>${escapeReportHtml(generatedAt)}</p>
        </section>
        <section class="section"><h3>1. بيانات المشروع</h3>${projectSummary}</section>
        <section class="section"><h3>2. مدة المشروع والأرض ومساحات البناء</h3>${areaSummary}</section>
        <section class="section page-break"><h3>3. مكونات المشروع</h3>${reportTableSnapshot('componentsTable', true)}</section>
        <section class="section page-break"><h3>4. بنود الإيرادات</h3>${reportTableSnapshot('revenueTable', false)}<h4>نسبة الوصول السنوية إلى الإشغال المستهدف</h4>${reportTableSnapshot('occupancyRampTable', false)}</section>
        ${graceReportSection}
        <section class="section page-break"><h3>5. تكاليف المشروع وأتعاب المطور</h3>${costSummary}<h4>تفاصيل بنود التكلفة</h4>${reportTableSnapshot('costTable', true, true)}</section>
        ${developerPaymentsReportSection}
        <section class="section page-break"><h3>7. المصروفات التشغيلية</h3>${reportTableSnapshot('opexTable', true, true)}</section>
        ${financeReportSection}
        ${fundReportSection}
        ${bonusReportSection}
        ${externalReportSection}
        <section class="section page-break"><h3>12. ملخص النتائج المالية</h3>${resultSummary}</section>
        <section class="section wide-table"><h3>13. التدفقات النقدية السنوية</h3>${reportTableSnapshot('cashflowTable', false)}</section>
        <section class="section wide-table"><h3>14. تحليل الحساسية العام</h3><h4>افتراضات السيناريوهات</h4>${reportTableSnapshot('sensitivityAssumptionsTable', false)}<h4>النتائج المقارنة</h4>${reportTableSnapshot('sensitivityTable', false)}</section>
        ${clarificationReportSection}
        ${exitReportSection}
        <section class="section conditional-off"><h3>16. التخارج والافتراضات المالية</h3>${reportRows([
        ['طريقة التخارج البيعي', reportFieldValue('saleExitMethod')],
        ['سنة التخارج البيعي', reportFieldValue('saleExitYear')],
        ['المساحة البيعية المتبقية', reportFieldValue('saleExitRemainingArea') + ' م²'],
        ['سعر بيع متر التخارج', reportFieldValue('saleExitPricePerM2')],
        ['قيمة التخارج البيعي الثابتة', reportFieldValue('saleExitFixedValue')],
        ['تكاليف التخارج البيعي', reportFieldValue('saleExitCostRate') + '%'],
        ['طريقة التخارج التشغيلي', reportFieldValue('exitMethod')],
        ['سنة التخارج التشغيلي', reportFieldValue('operatingExitYear')],
        ['مدخل التخارج التشغيلي', reportFieldValue('exitInput')],
        ['تكاليف التخارج التشغيلي', reportFieldValue('operatingExitCostRate') + '%'],
        ['سداد رصيد التمويل عند التخارج', reportFieldValue('settleDebtAtExit')],
        ['فترة احتساب ROI', document.getElementById('resROIScope').textContent],
        ['فترة احتساب IRR', document.getElementById('resProjectIRRScope').textContent]
      ])}${document.getElementById('analysisWarnings').textContent ? `<div class="note">${escapeReportHtml(document.getElementById('analysisWarnings').textContent)}</div>` : ''}<div class="note">هذا التقرير استرشادي ومبني على المدخلات المسجلة وقت الطباعة. أي تعديل على المدخلات أو الافتراضات يؤدي إلى تحديث النتائج والتدفقات النقدية تلقائيًا.</div></section>
        <footer><span>${escapeReportHtml(projectName)}</span><span>الدراسة المالية - ${escapeReportHtml(generatedAt)}</span></footer>
      </div></body></html>`);
      reportWindow.document.close();
      toast('تم تجهيز التقرير؛ اختر حفظ كملف PDF من نافذة الطباعة');
      setTimeout(() => { reportWindow.focus(); reportWindow.print() }, 650);
    }

    const sensitivityRegistry = {
      salePrice: { label: 'سعر بيع الوحدات', unit: 'ريال', kind: 'sale', app: () => projectModeFlags().sales, base: () => { const rows = [...document.querySelectorAll('#revenueTable tbody tr')].filter(tr => tr.querySelector('[data-field="method"] select')?.value === 'areaSale'); const q = rows.reduce((s, tr) => s + getRevenueQuantity(tr), 0); return q ? rows.reduce((s, tr) => s + calculateRevenueBase(tr, 0), 0) / q : 0 } },
      rentalRate: { label: 'أسعار الإيجار والتأجير', unit: 'مؤشر', kind: 'rate', app: () => projectModeFlags().rental, base: () => 100 },
      occupancy: { label: 'الوصول للإشغال المستهدف', unit: '%', kind: 'occupancy', app: () => projectModeFlags().rental, base: () => { const a = [...document.querySelectorAll('#occupancyRampTable [data-field="reachPct"] input')].map(x => parseNumber(x.value)); return a.length ? a.reduce((s, x) => s + x, 0) / a.length : 100 } },
      executionCost: { label: 'تكلفة التنفيذ', unit: 'ريال', kind: 'cost', app: () => true, base: () => num('executionCostTotal') },
      developmentYears: { label: 'مدة التطوير', unit: 'سنة', kind: 'delay', app: () => true, base: () => num('developmentYears') },
      financeRate: { label: 'معدل التمويل', unit: '%', kind: 'finance', app: () => val('financeEnabled') === 'yes', base: () => num('annualFinanceRate') },
      opex: { label: 'المصروفات التشغيلية', unit: 'مؤشر', kind: 'opex', app: () => projectModeFlags().rental, base: () => 100 },
      capRate: { label: 'معدل الرسملة عند التخارج', unit: '%', kind: 'cap', app: () => val('exitEnabled') === 'yes' && val('exitMethod') === 'capRate', base: () => num('exitInput') },
      fixedExit: { label: 'قيمة التخارج الثابتة', unit: 'ريال', kind: 'exit', app: () => val('exitEnabled') === 'yes' && (val('exitMethod') === 'fixed' || val('saleExitMethod') === 'fixed'), base: () => val('exitMethod') === 'fixed' ? num('exitInput') : num('saleExitFixedValue') }
    };
    function addSensitivityVariable(d = {}) { const key = d.key || val('sensitivityVariableSelect') || 'executionCost', reg = sensitivityRegistry[key], tb = document.querySelector('#sensitivityAssumptionsTable tbody'); if (!tb || !reg) return; if ([...tb.querySelectorAll('tr')].some(tr => tr.dataset.key === key)) return toast('المتغير مضاف بالفعل'); const base = Math.max(0, reg.base()); const low = d.low ?? (key === 'developmentYears' ? base + 1 : key === 'capRate' ? base + 1 : base * .9), high = d.high ?? (key === 'developmentYears' ? Math.max(1, base - 1) : key === 'capRate' ? Math.max(.01, base - 1) : base * 1.1); const tr = document.createElement('tr'); tr.dataset.key = key; tr.innerHTML = `<td>${reg.label}</td><td><input data-field="low" type="number" value="${low}" oninput="renderSensitivity()"></td><td><span class="sensitivity-base-value sensAutoBase">${money(base)} ${reg.unit}</span></td><td><input data-field="high" type="number" value="${high}" oninput="renderSensitivity()"></td><td>قيمة فعلية — الأساسي من المدخلات</td><td>${rowActionsHtml()}</td>`; tb.appendChild(tr); enhanceNumericInputs(tr); if (!d.silent) renderSensitivity() }
    function collectSensitivityVariables() { return [...document.querySelectorAll('#sensitivityAssumptionsTable tbody tr')].map(tr => ({ key: tr.dataset.key, low: parseNumber(tr.querySelector('[data-field="low"]')?.value), high: parseNumber(tr.querySelector('[data-field="high"]')?.value) })) }
    function updateSensitivityBaseInputs() { document.querySelectorAll('#sensitivityAssumptionsTable tbody tr').forEach(tr => { const reg = sensitivityRegistry[tr.dataset.key]; if (!reg) return; tr.classList.toggle('conditional-off', !reg.app()); const b = reg.base(); const c = tr.querySelector('.sensAutoBase'); if (c) c.textContent = `${money(b)} ${reg.unit}` }) }
    function renderSensitivity() {
      const tbody = document.querySelector('#sensitivityTable tbody'); if (!tbody || window.__sensitivityRunning) return; updateSensitivityBaseInputs(); const vars = collectSensitivityVariables().filter(v => sensitivityRegistry[v.key]?.app()), labels = ['متحفظ', 'أساسي', 'متفائل'], snapshots = []; const capture = (el, kind) => { if (el && !snapshots.some(x => x.el === el)) snapshots.push({ el, value: el.value, kind }) };
      document.querySelectorAll('#revenueTable tbody tr').forEach(tr => { const m = tr.querySelector('[data-field="method"] select')?.value; if (m === 'areaSale') capture(tr.querySelector('[data-field="price"] input'), 'sale'); else if (m === 'fixed') capture(tr.querySelector('[data-field="qty"] input'), 'rate'); else if (m !== 'percentRevenue') capture(tr.querySelector('[data-field="price"] input'), 'rate') }); document.querySelectorAll('#occupancyRampTable [data-field="reachPct"] input').forEach(el => capture(el, 'occupancy')); document.querySelectorAll('#costTable tbody tr').forEach(tr => { if (tr.querySelector('[data-field="class"] select')?.value === 'execution') capture(tr.querySelector('[data-field="method"] select')?.value === 'fixed' ? tr.querySelector('[data-field="qty"] input') : tr.querySelector('[data-field="price"] input'), 'cost') }); document.querySelectorAll('#opexTable tbody tr [data-field="price"] input,#opexTable tbody tr [data-field="qty"] input').forEach(el => capture(el, 'opex')); capture(document.getElementById('developmentYears'), 'delay'); capture(document.getElementById('annualFinanceRate'), 'finance'); if (val('exitMethod') === 'capRate') capture(document.getElementById('exitInput'), 'cap'); if (val('exitMethod') === 'fixed') capture(document.getElementById('exitInput'), 'exit'); if (val('saleExitMethod') === 'fixed') capture(document.getElementById('saleExitFixedValue'), 'exit'); const results = []; window.__sensitivityRunning = true; try { [0, 1, 2].forEach(si => { snapshots.forEach(s => { const regVar = vars.find(v => sensitivityRegistry[v.key]?.kind === s.kind); if (!regVar) return; const target = si === 1 ? sensitivityRegistry[regVar.key].base() : (si === 0 ? regVar.low : regVar.high), base = sensitivityRegistry[regVar.key].base(), orig = parseNumber(s.value); if (['sale', 'rate', 'cost', 'opex'].includes(s.kind)) s.el.value = String(base ? Math.max(0, orig * target / base) : orig); else if (s.kind === 'occupancy') s.el.value = String(base ? Math.max(0, Math.min(100, orig * target / base)) : orig); else s.el.value = String(Math.max(s.kind === 'cap' ? .01 : 0, target)) }); calculateAll(); const f = window.__financialProjection || {}, rows = f.projected || [], totalRevenue = rows.reduce((s, r) => s + r.saleRevenue + r.operatingRevenue, 0), totalExpenses = rows.reduce((s, r) => s + r.opex + r.landRent, 0), out = (f.adjustedProjectCost || 0) + totalExpenses, profit = totalRevenue + (f.terminal || 0) - out; results.push({ label: labels[si], totalRevenue, fullNoi: f.fullOccupancyNOI || 0, totalCost: f.adjustedProjectCost || 0, netProfit: profit, exit: f.terminal || 0, roi: out > 0 ? profit / out : null, projectIrr: irr(f.projectCashflows || []), equityIrr: irr(f.cashflows || []), payback: f.payback, equity: f.equityRequired || 0 }); snapshots.forEach(s => s.el.value = s.value) }); calculateAll() } finally { window.__sensitivityRunning = false } tbody.innerHTML = results.map(r => `<tr class="${r.label === 'أساسي' ? 'sensitivity-base-row' : ''}"><td>${r.label}</td><td>${money(r.totalRevenue)}</td><td>${money(r.fullNoi)}</td><td>${money(r.totalCost)}</td><td>${money(r.netProfit)}</td><td>${money(r.exit)}</td><td>${r.roi === null ? 'غير متاح' : (r.roi * 100).toFixed(1) + '%'}</td><td>${r.projectIrr === null ? 'غير متاح' : (r.projectIrr * 100).toFixed(1) + '%'}</td><td>${r.equityIrr === null ? 'غير متاح' : (r.equityIrr * 100).toFixed(1) + '%'}</td><td>${r.payback === null ? 'لا يسترد' : r.payback.toFixed(1) + ' سنة'}</td><td>${money(r.equity)}</td></tr>`).join('')
    }



    // S5: Timeline Table
    function addTimelineTable(form) {
      const div = document.createElement('div');
      div.className = 'tenant-form-section';
      div.id = 'section-timeline';
      div.dataset.section = 'section-timeline';
      div.innerHTML = `
        <h3 class="tenant-section-title">الجدول الزمني للمشروع</h3>
        <div class="tenant-grid" style="grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px">
          <div class="tenant-field"><label>تاريخ البداية</label><input type="month" id="tlStartDate" data-key="timeline_start_date" data-type="text" onchange="recalcTimeline()"></div>
          <div class="tenant-field"><label>عدد السنوات</label><input type="number" id="tlYears" data-key="timeline_years" data-type="number" min="1" value="" onchange="recalcTimeline()"></div>
          <div class="tenant-field"><label>تاريخ النهاية</label><input type="text" id="tlEndDate" readonly class="readonly-highlight" title="تاريخ البداية بعد عدد السنوات"></div>
        </div>
        <div id="timelineStartYearWarning" class="validation-panel error" hidden>تاريخ البداية غير محدد — تُعرض السنوات والأرباع كأرقام نسبية دون تواريخ فعلية.</div>
        <div class="fin-table-wrap">
          <table class="fin-table" id="timelineTable">
            <thead><tr><th>المرحلة</th><th>من (السنة)</th><th>من (الربع)</th><th>المدة (أشهر)</th><th>إلى</th><th>الملاحظات</th><th style="width:46px"></th></tr></thead>
            <tbody id="timelineTableBody"></tbody>
          </table>
        </div>
        <button type="button" class="btn ghost small" style="margin-top:10px" onclick="addTimelineRow()">إضافة مرحلة</button>
        <input type="hidden" data-key="timeline_table_data" data-type="text" id="timelineTableData">
      `;
      div.querySelector('.tenant-section-title')?.replaceWith(
        createProjectSectionHeader('section-timeline', 'الجدول الزمني للمشروع')
      );
      form.appendChild(div);
      recalcTimeline();
    }

    const TIMELINE_QUARTERS = ['Q1', 'Q2', 'Q3', 'Q4'];

    // The standard development phases a new project opens with; the client edits them freely.
    const TIMELINE_DEFAULT_PHASES = [
      'التصميم، الدراسات، التراخيص',
      'تجهيز الموقع والأساسات والهيكل الإنشائي',
      'استكمال الهيكل وأعمال الكهرباء والميكانيكا',
      'التشطيبات والأعمال الخارجية',
      'الاختبارات والتسليم والتسويق',
    ];

    function parseTimelineStartValue(raw) {
      const match = String(raw || '').trim().match(/^(\d{4})-(\d{1,2})$/);
      if (!match) return null;
      const year = parseInt(match[1], 10);
      const month = parseInt(match[2], 10);
      if (month < 1 || month > 12) return null;
      return { year, month, index: year * 12 + (month - 1) };
    }

    // The start date is a month+year the client picks; drafts saved before it existed carry a
    // bare start year, which maps to January.
    function timelineProjectStart() {
      return parseTimelineStartValue(document.getElementById('tlStartDate')?.value)
        || parseTimelineStartValue(tenantProjectData?.timeline_start_date)
        || (() => {
          const year = parseInt(tenantProjectData?.timeline_start_year, 10);
          return Number.isFinite(year) ? { year, month: 1, index: year * 12 } : null;
        })();
    }

    function formatTimelineMonth(index) {
      if (!Number.isFinite(index)) return '';
      return ((index % 12) + 1) + '/' + Math.floor(index / 12);
    }

    function formatTimelineStart(raw) {
      const start = parseTimelineStartValue(raw);
      return start ? formatTimelineMonth(start.index) : String(raw || '').trim();
    }

    // Rows store the relative year number; months are counted from the project's first month,
    // so the end lands on a relative year/quarter that maps back onto the calendar once the
    // start date is known.
    function computeTimelineEnd(year, quarter, duration) {
      const startYear = parseInt(year, 10);
      const quarterIndex = TIMELINE_QUARTERS.indexOf(String(quarter || '').trim());
      const months = parseInt(duration, 10);
      if (!Number.isFinite(startYear) || startYear <= 0 || quarterIndex < 0 || !Number.isFinite(months) || months <= 0) return null;
      const endMonth = (startYear - 1) * 12 + quarterIndex * 3 + months - 1;
      return {
        year: Math.floor(endMonth / 12) + 1,
        quarter: TIMELINE_QUARTERS[Math.floor((endMonth % 12) / 3)],
        monthIndex: endMonth
      };
    }

    function formatTimelineEnd(end) {
      if (!end) return '';
      const relative = 'سنة ' + end.year + ' — الربع ' + (TIMELINE_QUARTERS.indexOf(end.quarter) + 1);
      const start = timelineProjectStart();
      return start && Number.isFinite(end.monthIndex)
        ? relative + ' (' + formatTimelineMonth(start.index + end.monthIndex) + ')'
        : relative;
    }

    // The year picker offers only the project's own years (1..«عدد السنوات»); a stored value
    // outside them stays as an extra option rather than being silently wiped.
    function timelineYearOptionsHtml(chosen) {
      const declared = parseInt(document.getElementById('tlYears')?.value, 10);
      let max = Number.isFinite(declared) && declared > 0 ? declared : 1;
      const picked = parseInt(chosen, 10);
      if (Number.isFinite(picked) && picked > max) max = picked;
      const start = timelineProjectStart();
      let html = '<option value="">—</option>';
      for (let year = 1; year <= max; year++) {
        let label = 'السنة ' + year;
        if (start) {
          const first = start.index + (year - 1) * 12;
          label += ' (' + formatTimelineMonth(first) + ' – ' + formatTimelineMonth(first + 11) + ')';
        }
        html += '<option value="' + year + '"' + (String(chosen) === String(year) ? ' selected' : '') + '>' + label + '</option>';
      }
      return html;
    }

    function timelineQuarterOptionsHtml(chosen) {
      return ['<option value="">—</option>'].concat(TIMELINE_QUARTERS.map(
        (quarter, index) => '<option value="' + quarter + '"' + (String(chosen).trim() === quarter ? ' selected' : '') + '>الربع ' + (index + 1) + '</option>'
      )).join('');
    }

    // Once the row's year and the start date are known, each quarter option names the real
    // months it covers — the quarters belong to the project year, which starts at the start
    // month.
    function refreshTimelineQuarterLabels(row) {
      const select = row?.querySelector('.tl-quarter');
      if (!select) return;
      const start = timelineProjectStart();
      const year = parseInt(row.querySelector('.tl-year')?.value, 10);
      Array.from(select.options).forEach(option => {
        const quarterIndex = TIMELINE_QUARTERS.indexOf(option.value);
        if (quarterIndex < 0) return;
        let label = 'الربع ' + (quarterIndex + 1);
        if (start && Number.isFinite(year)) {
          const first = start.index + (year - 1) * 12 + quarterIndex * 3;
          label += ' (' + formatTimelineMonth(first) + ' – ' + formatTimelineMonth(first + 2) + ')';
        }
        option.textContent = label;
      });
    }

    function refreshTimelineRowPickers() {
      document.querySelectorAll('#timelineTableBody tr').forEach(row => {
        const yearSelect = row.querySelector('.tl-year');
        if (yearSelect) yearSelect.innerHTML = timelineYearOptionsHtml(yearSelect.value);
        refreshTimelineQuarterLabels(row);
        updateTimelineRowEnd(row);
      });
    }

    function updateTimelineProjectEnd() {
      const output = document.getElementById('tlEndDate');
      if (!output) return;
      const start = timelineProjectStart();
      const years = parseInt(document.getElementById('tlYears')?.value, 10);
      output.value = start && Number.isFinite(years) && years > 0
        ? formatTimelineMonth(start.index + years * 12)
        : '';
    }

    function updateTimelineRowEnd(row) {
      if (!row) return null;
      const end = computeTimelineEnd(
        row.querySelector('.tl-year')?.value,
        row.querySelector('.tl-quarter')?.value,
        row.querySelector('.tl-duration')?.value
      );
      const output = row.querySelector('.tl-end');
      if (output) output.value = formatTimelineEnd(end);
      return end;
    }

    // One builder for every path (blank row, "add phase", seeding, and draft hydration) so the
    // columns cannot drift apart between them.
    function timelineRowHtml(data = {}) {
      const attr = value => escapeHtml(value === undefined || value === null ? '' : String(value));
      const end = computeTimelineEnd(data.year, data.quarter, data.duration);
      return '<td><input type="text" class="tl-name" value="' + attr(data.name) + '" placeholder="مثال: التصميم والتراخيص" onchange="saveTimelineData()"></td>' +
        '<td><select class="tl-year" style="min-width:150px" onchange="refreshTimelineQuarterLabels(this.closest(\'tr\')); updateTimelineRowEnd(this.closest(\'tr\')); saveTimelineData()">' + timelineYearOptionsHtml(data.year) + '</select></td>' +
        '<td><select class="tl-quarter" style="min-width:120px" onchange="updateTimelineRowEnd(this.closest(\'tr\')); saveTimelineData()">' + timelineQuarterOptionsHtml(data.quarter) + '</select></td>' +
        '<td><input type="number" class="tl-duration" min="1" value="' + attr(data.duration) + '" placeholder="0" style="width:78px" oninput="updateTimelineRowEnd(this.closest(\'tr\'))" onchange="updateTimelineRowEnd(this.closest(\'tr\')); saveTimelineData()"></td>' +
        '<td><input type="text" class="tl-end" value="' + attr(formatTimelineEnd(end)) + '" readonly title="تُحسب من البداية والمدة"></td>' +
        '<td><input type="text" class="tl-notes" value="' + attr(data.notes) + '" placeholder="ملاحظة تظهر في الشريحة" onchange="saveTimelineData()"></td>' +
        '<td><button type="button" class="btn danger small" style="padding:4px 9px;font-size:11px" onclick="removeTimelineRow(this)" title="حذف المرحلة">حذف</button></td>';
    }

    function recalcTimeline() {
      const tbody = document.getElementById('timelineTableBody');
      if (!tbody) return;
      if (!tbody.rows.length) addTimelineRow();
      // «تاريخ البداية» and «عدد السنوات» bound the pickers and feed the financial study, so
      // every change rebuilds them and re-mirrors the study.
      refreshTimelineRowPickers();
      updateTimelineProjectEnd();
      syncFinancialFromTimeline();
    }

    // New projects open with the standard phases already named — a starting point the client
    // edits freely, not fixed data. Drafts and presentations hydrate their own rows instead.
