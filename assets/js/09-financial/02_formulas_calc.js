    function getCustomFormula(row) { return row.querySelector('[data-field="customFormula"] input')?.value || ''; }
    function setCustomFormulaVisible(tr, visible) { const el = tr.querySelector('[data-field="customFormula"]'); if (!el) return; el.classList.toggle('dynamic-off', !visible); el.querySelectorAll('input,select,textarea').forEach(x => x.disabled = !visible); }
    function markFormulaError(row, hasError) { const el = row.querySelector('[data-field="customFormula"] .help'); if (el) el.classList.toggle('formula-error', !!hasError); }

    function calcRevenueByMethod(method, qty, price, period, occ, baseRevenue = 0) {
      occ = (occ || 0) / 100;
      if (method === 'areaSale') return qty * price;
      if (method === 'dailyRent') return qty * price * 365 * occ;
      if (method === 'monthlyAreaRent') return qty * price * 12 * occ;
      if (method === 'monthlyUnitRent') return qty * price * 12 * occ;
      if (method === 'areaRent') return qty * price * occ;
      if (method === 'unitRent') return qty * price * occ;
      if (method === 'weeklyUnit') return qty * price * period * occ;
      if (method === 'tickets') return qty * price * occ;
      if (method === 'commission') return qty * (price / 100) * occ;
      if (method === 'subscription') return qty * price * occ;
      if (method === 'fixed') return (qty || price) * occ;
      if (method === 'percentRevenue') return baseRevenue * (price / 100);
      return qty * price * period * occ;
    }
    function formulaText(method) {
      const map = { areaSale: 'المساحة البيعية × سعر البيع للمتر', dailyRent: 'عدد الوحدات × السعر اليومي × 365 × الإشغال', monthlyAreaRent: 'المساحة × إيجار المتر الشهري × 12 × الإشغال', monthlyUnitRent: 'عدد الوحدات × الإيجار الشهري × 12 × الإشغال', areaRent: 'المساحة × إيجار المتر السنوي × الإشغال', unitRent: 'عدد الوحدات × الإيجار السنوي × الإشغال', weeklyUnit: 'الوحدات × السعر الأسبوعي × الأسابيع × التشغيل', tickets: 'عدد الزوار × سعر التذكرة', commission: 'قيمة العمليات × نسبة العمولة', subscription: 'عدد المشتركين × قيمة الاشتراك', fixed: 'قيمة ثابتة', percentRevenue: 'إجمالي الإيرادات × النسبة', areaCost: 'المساحة × تكلفة المتر', unitCost: 'العدد × تكلفة الوحدة', percentExecution: 'تكلفة التنفيذ × النسبة', monthlyDuration: 'التكلفة الشهرية × المدة', monthlyFixed: 'القيمة الشهرية × 12', staffSalary: 'عدد الموظفين × الراتب × 12', annualFixed: 'قيمة سنوية ثابتة', perUnit: 'عدد الوحدات × تكلفة الوحدة', perM2: 'المساحة × تكلفة المتر', qtyPrice: 'الكمية × السعر', areaPrice: 'المساحة × سعر المتر', percentCost: 'إجمالي التكلفة × النسبة', recurring: 'القيمة الأساسية سنويًا', custom: 'فورمولا مخصصة' };
      return map[method] || 'حسب الاختيار';
    }
    function annualGrowthFactor(year, rate) { return Math.pow(1 + (rate || 0) / 100, year - 1); }
    function activeYearFraction(year, startYear, endYear) { const start = Math.max(0, (Number(startYear) || 1) - 1), end = Math.max(start, Number(endYear) || year); return Math.max(0, Math.min(year, end) - Math.max(year - 1, start)); }

    function irr(cashflows) {
      const npv = (r) => cashflows.reduce((s, cf, i) => s + cf / Math.pow(1 + r, i), 0);
      const hasPositive = cashflows.some(v => v > 0), hasNegative = cashflows.some(v => v < 0);
      if (!hasPositive || !hasNegative) return null;
      const rates = []; const minX = Math.log(0.001), maxX = Math.log(1001), steps = 1800;
      for (let i = 0; i <= steps; i++)rates.push(Math.exp(minX + (maxX - minX) * (i / steps)) - 1);
      const brackets = []; let low = rates[0], fLow = npv(low);
      for (let i = 1; i < rates.length; i++) { const high = rates[i], fHigh = npv(high); if (Number.isFinite(fLow) && Number.isFinite(fHigh) && (fLow === 0 || fHigh === 0 || fLow * fHigh < 0)) brackets.push([low, high]); low = high; fLow = fHigh; }
      if (!brackets.length) return null;
      const selected = brackets.find(([a, b]) => b >= 0) || brackets[brackets.length - 1];
      low = selected[0]; let high = selected[1]; fLow = npv(low);
      for (let i = 0; i < 120; i++) { const mid = (low + high) / 2; const fMid = npv(mid); if (Math.abs(fMid) < 0.0001) return mid; if (fLow * fMid < 0) { high = mid; } else { low = mid; fLow = fMid; } }
      return (low + high) / 2;
    }
    function capitalRecoveryPeriod(totalProjectCost, annualNetReturns) {
      const target = Math.max(0, Number(totalProjectCost) || 0); if (!target) return 0; let recovered = 0;
      for (let index = 0; index < annualNetReturns.length; index++) { const annual = Number(annualNetReturns[index]) || 0; if (annual > 0 && recovered + annual >= target) { const remaining = target - recovered; return index + (annual ? remaining / annual : 0); } recovered += annual; }
      return null;
    }
    function cashflowPaybackPeriod(cashflows) {
      let cumulative = 0, hadDeficit = false;
      for (let index = 0; index < cashflows.length; index++) { const cf = Number(cashflows[index]) || 0; const opening = cumulative; cumulative += cf; if (cumulative < 0) hadDeficit = true; if (hadDeficit && opening < 0 && cumulative >= 0 && cf > 0) return Math.max(0, index - 1) + (-opening / cf); }
      return hadDeficit ? null : 0;
    }
    function analysisEndYear(period, customYear, developmentYears, totalYears) { if (period === 'development') return developmentYears; if (period === 'custom') return Math.max(1, Math.min(totalYears, Math.round(customYear || totalYears))); return totalYears; }
    function periodLabel(endYear, developmentYears, totalYears) { if (endYear === developmentYears) return `<span>سنوات التطوير</span> 1-${developmentYears}`; if (endYear === totalYears) return `<span>كامل الدراسة</span> 1-${totalYears}`; return `<span>من السنة</span> 1 <span>حتى السنة</span> ${endYear}`; }
    document.addEventListener('wf:lang', () => { try { if (document.getElementById('section-financial-calc')) calculateAll(); } catch (e) { /* ignore */ } });

    function calculateRevenueBase(row, baseRevenue = 0, occupancyOverride = null) {
      const method = row.querySelector('[data-field="method"] select')?.value || 'areaRent';
      const qty = getRevenueQuantity(row);
      const price = parseNumber(row.querySelector('[data-field="price"] input')?.value);
      const periodInput = row.querySelector('[data-field="period"] input')?.value;
      const occupancyInput = row.querySelector('[data-field="occupancy"] input')?.value;
      const period = String(periodInput ?? '').trim() === '' ? 1 : parseNumber(periodInput);
      const occ = occupancyOverride === null ? (String(occupancyInput ?? '').trim() === '' ? 100 : parseNumber(occupancyInput)) : Number(occupancyOverride);
      if (method === 'custom') {
        try { markFormulaError(row, false); return safeCustomFormula(getCustomFormula(row), { A: qty, B: price, C: period, D: occ, E: baseRevenue }); } catch (e) { markFormulaError(row, true); return 0; }
      }
      return calcRevenueByMethod(method, qty, price, period, occ, baseRevenue);
    }
    function calculateCostRow(row, executionCost = 0, revenueTotal = 0) {
      const method = row.querySelector('[data-field="method"] select')?.value || 'areaCost';
      const qty = parseNumber(row.querySelector('[data-field="qty"] input')?.value);
      const price = parseNumber(row.querySelector('[data-field="price"] input')?.value);
      const duration = parseNumber(row.querySelector('[data-field="duration"] input')?.value) || 1;
      if (method === 'custom') {
        try { markFormulaError(row, false); return safeCustomFormula(getCustomFormula(row), { A: qty, B: price, C: duration, D: executionCost, E: revenueTotal }); } catch (e) { markFormulaError(row, true); return 0; }
      }
      if (method === 'areaCost' || method === 'unitCost') return qty * price;
      if (method === 'fixed') return qty || price;
      if (method === 'monthlyDuration') return price * duration;
      if (method === 'percentRevenue') return revenueTotal * (price / 100);
      if (method === 'percentExecution') return executionCost * (price / 100);
      return qty * price * duration;
    }
    function calculateOpexRow(row, revenueTotal = 0) {
      const method = row.querySelector('[data-field="method"] select')?.value || 'monthlyFixed';
      const qty = parseNumber(row.querySelector('[data-field="qty"] input')?.value);
      const price = parseNumber(row.querySelector('[data-field="price"] input')?.value);
      if (method === 'custom') {
        try { markFormulaError(row, false); return safeCustomFormula(getCustomFormula(row), { A: qty, B: price, C: revenueTotal }); } catch (e) { markFormulaError(row, true); return 0; }
      }
      if (method === 'monthlyFixed') return qty * 12;
      if (method === 'percentRevenue') return revenueTotal * (price / 100);
      if (method === 'staffSalary') return qty * price * 12;
      if (method === 'annualFixed') return qty || price;
      if (method === 'perUnit' || method === 'perM2') return qty * price;
      return qty * price;
    }
    function calculateExternalRow(row, revenueTotal = 0, costTotal = 0) {
      const type = row.querySelector('[data-field="type"] select')?.value || 'revenue';
      const method = row.querySelector('[data-field="method"] select')?.value || 'fixed';
      const base = parseNumber(row.querySelector('[data-field="base"] input')?.value);
      const qty = parseNumber(row.querySelector('[data-field="qty"] input')?.value);
      const price = parseNumber(row.querySelector('[data-field="price"] input')?.value);
      let res = 0;
      if (method === 'custom') {
        try { markFormulaError(row, false); res = safeCustomFormula(getCustomFormula(row), { A: base, B: qty, C: price, D: revenueTotal, E: costTotal }); } catch (e) { markFormulaError(row, true); res = 0; }
      }
      else if (method === 'fixed' || method === 'recurring') res = base;
      else if (method === 'qtyPrice' || method === 'areaPrice') res = qty * price;
      else if (method === 'percentRevenue') res = revenueTotal * (price / 100);
      else if (method === 'percentCost') res = costTotal * (price / 100);
      else res = base || qty * price;
      return { type, value: res };
    }
    function getComponentRowsData() {
      return [...document.querySelectorAll('#componentsTable tbody tr')].map((tr, idx) => {
        const name = tr.querySelector('[data-field="name"] input')?.value?.trim() || `مكون ${idx + 1}`;
        const units = parseNumber(tr.querySelector('[data-field="units"] input')?.value);
        const unitArea = parseNumber(tr.querySelector('[data-field="unitArea"] input')?.value);
        const builtArea = parseNumber(tr.querySelector('[data-field="builtArea"] input')?.value);
        const revenueArea = parseNumber(tr.querySelector('[data-field="revenueArea"] input')?.value);
        const useType = tr.querySelector('[data-field="useType"] select')?.value || 'retail';
        const investmentModel = tr.querySelector('[data-field="investmentModel"] select')?.value || 'nonRevenue';
        const leasable = ['dailyRent', 'monthlyRent', 'annualRent', 'operating'].includes(investmentModel);
        const id = tr.dataset.componentKey || (tr.dataset.componentKey = 'p_' + Date.now() + '_' + Math.random().toString(16).slice(2));
        return { idx, id, name, useType, units, unitArea, builtArea, revenueArea, totalArea: revenueArea, investmentModel, leasable };
      });
    }
    function updateRevenueComponentOptions() {
      const components = getComponentRowsData();
      const optionsHtml = '<option value="">غير مرتبط بمكون</option>' + components.map(c => {
        const fallbackMatch = String(c.name || '').match(/^مكون (\d+)$/);
        const displayName = fallbackMatch ? (trDynamicI18n('مكون') + ' ' + fallbackMatch[1]) : c.name;
        return `<option value="${c.id}">${displayName} — ${trDynamicI18n('مبني')} ${money(c.builtArea)} ${trDynamicI18n('م²')} | ${trDynamicI18n('بيعي/تأجيري')} ${money(c.revenueArea)} ${trDynamicI18n('م²')} | ${money(c.units)} ${trDynamicI18n('وحدة')}</option>`;
      }).join('');
      document.querySelectorAll('#revenueTable tbody tr').forEach(tr => {
        const sel = tr.querySelector('[data-field="component"] select'); if (!sel) return;
        let currentId = (sel.options && sel.options.length > 0) ? (sel.value || '') : (tr.dataset.componentId || '');
        if (currentId !== '' && !components.some(c => String(c.id) === String(currentId)) && /^\d+$/.test(currentId) && components[Number(currentId)]) {
          currentId = components[Number(currentId)].id;
        }
        if (sel.dataset.lastOptionsHtml !== optionsHtml) {
          sel.innerHTML = optionsHtml;
          sel.dataset.lastOptionsHtml = optionsHtml;
        }
        if (currentId && [...sel.options].some(o => o.value === currentId)) {
          sel.value = currentId;
        } else {
          sel.value = '';
        }
        tr.dataset.componentId = sel.value || '';
      });
    }
    function getLinkedComponentForRevenueRow(tr) { const sel = tr.querySelector('[data-field="component"] select'); const idx = sel ? (sel.value || '') : (tr?.dataset?.componentId || ''); if (idx === '') return null; return getComponentRowsData().find(c => String(c.id) === String(idx)) || null; }
    function getRevenueQuantity(tr) { const source = tr.querySelector('[data-field="qtySource"] select')?.value || 'manual'; const comp = getLinkedComponentForRevenueRow(tr); if (source === 'componentRevenueArea' || source === 'componentArea') return comp ? comp.revenueArea : 0; if (source === 'componentBuiltArea') return comp ? comp.builtArea : 0; if (source === 'componentUnits') return comp ? comp.units : 0; return parseNumber(tr.querySelector('[data-field="qty"] input')?.value); }
    function updateAutoQtyPreview(tr) { const source = tr.querySelector('[data-field="qtySource"] select')?.value || 'manual'; const comp = getLinkedComponentForRevenueRow(tr); const qtyInput = tr.querySelector('[data-field="qty"] input'); if (!qtyInput) return; if (source === 'componentRevenueArea' || source === 'componentArea') qtyInput.value = money(comp ? comp.revenueArea : 0); else if (source === 'componentBuiltArea') qtyInput.value = money(comp ? comp.builtArea : 0); else if (source === 'componentUnits') qtyInput.value = money(comp ? comp.units : 0); }

    function setWrapVisible(id, visible) { const el = document.getElementById(id); if (!el) return; el.classList.toggle('dynamic-off', !visible); el.querySelectorAll('input,select,textarea').forEach(x => x.disabled = !visible); }

    // A sale exit worth zero is indistinguishable from a sale exit nobody set up, so the reason is
    // stated: no sellable units in the project, the method left off, or a figure still missing. The
    // reference cell carries the sellable area already entered in بنود الإيرادات so the remaining
    // area is typed against a real number instead of guessed.
    function renderSaleExitStatus({ modeFlags, exitOn, saleExitMethod, saleAreaTotal, saleExitGross, saleExitValue }) {
      const reference = document.getElementById('saleExitAreaReference');
      if (reference) reference.value = saleAreaTotal > 0 ? money(saleAreaTotal) : '';
      const note = document.getElementById('saleExitStatusNote');
      if (!note) return;
      let text = '';
      if (!modeFlags.sales) text = 'لا يوجد تخارج بيعي: وحدات المشروع تأجيرية بالكامل.';
      else if (!exitOn) text = 'التخارج غير مطبق في هذه الدراسة.';
      else if (saleExitMethod === 'none') text = 'التخارج البيعي غير مطبق: لم تُختر طريقة احتساب.';
      else if (!(saleExitGross > 0)) text = 'التخارج البيعي مطبق بقيمة صفر: القيمة أو المساحة أو سعر المتر غير مُدخل.';
      else if (saleExitMethod === 'remainingArea' && saleAreaTotal > 0) {
        const entered = Math.max(0, num('saleExitRemainingArea'));
        if (entered > saleAreaTotal) text = `<span>المساحة المتبقية المُدخلة</span> ${money(entered)} <span>م²</span> <span>تتجاوز المساحة البيعية في بنود الإيرادات</span> ${money(saleAreaTotal)} <span>م²</span>.`;
      }
      if (!text && saleExitValue > 0) text = `<span>صافي التخارج البيعي</span> ${money(saleExitValue)} <span>من إجمالي</span> ${money(saleExitGross)} <span>بعد تكاليف التخارج.</span>`;
      note.hidden = text === '';
      note.innerHTML = text || '';
    }
    function setCellVisible(tr, field, visible, helpText = '') { const cell = tr.querySelector(`[data-field="${field}"]`); if (!cell) return; cell.classList.toggle('off-cell', !visible); cell.querySelectorAll('input,select').forEach(x => x.disabled = !visible); const h = cell.querySelector('.miniHelp'); if (h) h.textContent = helpText ? (typeof WFT === 'function' ? WFT(helpText) : helpText) : ''; }

    function updateDynamicFields() {
      const landMethod = val('landValueMethod');
      setWrapVisible('landPricePerM2Wrap', landMethod === 'perM2'); setWrapVisible('manualLandValueWrap', landMethod === 'manual');
      const rentMethod = val('landRentMethod');
      setWrapVisible('landRentRateWrap', rentMethod === 'percentLandValue'); setWrapVisible('manualAnnualLandRentWrap', rentMethod === 'annualFixed'); setWrapVisible('monthlyLandRentWrap', rentMethod === 'monthlyFixed');
      const exitOn = val('exitEnabled') !== 'no';
      const exitMethod = val('exitMethod'); const exitInput = document.getElementById('exitInput');
      if (exitInput) { exitInput.disabled = !exitOn || exitMethod === 'none'; exitInput.closest('div')?.classList.toggle('dynamic-off', !exitOn || exitMethod === 'none'); const lbl = exitInput.closest('div')?.querySelector('label'); if (lbl) { const lText = exitMethod === 'capRate' ? 'Cap Rate %' : exitMethod === 'fixed' ? 'قيمة البيع الثابتة' : exitMethod === 'noiMultiple' ? 'مضاعف NOI' : exitMethod === 'revenueMultiple' ? 'مضاعف الإيرادات' : 'مدخل التخارج'; lbl.textContent = typeof WFT === 'function' ? WFT(lText) : lText; } }
      updateDynamicFieldDetails(exitOn);
    }

    function updateDynamicFieldDetails(exitOn) {
      // A sale exit is the disposal of unsold sellable area, so it exists only in a project that
      // has sellable units at all. The selector used to stay open on a rental-only project, where
      // `calculateAll()` forces saleExitMethod to 'none' — so a user could pick a method, enter an
      // area and a price, and every sale-exit figure stayed zero with nothing saying why.
      const saleModeOn = projectModeFlags().sales;
      const saleExitMethod = saleModeOn ? (val('saleExitMethod') || 'none') : 'none';
      const saleExitActive = exitOn && saleModeOn && saleExitMethod !== 'none';
      setWrapVisible('saleExitMethodWrap', exitOn && saleModeOn);
      setWrapVisible('saleExitYearWrap', saleExitActive);
      setWrapVisible('saleExitCostRateWrap', saleExitActive);
      setWrapVisible('saleExitRemainingAreaWrap', saleExitActive && saleExitMethod === 'remainingArea');
      setWrapVisible('saleExitAreaReferenceWrap', saleExitActive && saleExitMethod === 'remainingArea');
      setWrapVisible('saleExitPricePerM2Wrap', saleExitActive && saleExitMethod === 'remainingArea');
      setWrapVisible('saleExitFixedValueWrap', saleExitActive && saleExitMethod === 'fixed');
      const resSaleExitGrossCard = document.getElementById('resSaleExitGrossCard');
      if (resSaleExitGrossCard) resSaleExitGrossCard.classList.toggle('dynamic-off', !saleExitActive);
      const resSaleExitCard = document.getElementById('resSaleExitCard');
      if (resSaleExitCard) resSaleExitCard.classList.toggle('dynamic-off', !saleExitActive);
      setWrapVisible('roiEndYearWrap', val('roiPeriod') === 'custom'); setWrapVisible('irrEndYearWrap', val('irrPeriod') === 'custom');
      const fundOn = val('fundFeesEnabled') !== 'no'; const fundBase = val('fundFeeBase') || 'fundCapital';
      setWrapVisible('fundCapitalInputWrap', fundOn && ['fundCapital', 'investedCapital'].includes(fundBase)); setWrapVisible('fundNavInputWrap', fundOn && fundBase === 'nav'); setWrapVisible('fundManagementRateWrap', fundOn && fundBase !== 'fixed'); setWrapVisible('fundFixedAnnualFeeWrap', fundOn && fundBase === 'fixed');
      ['fundFeeStartYear', 'fundFeeEndYear', 'fundFeeFrequency', 'fundFeeTiming', 'fundFeeGrowthRate'].forEach(id => { const el = document.getElementById(id); if (el) el.disabled = !fundOn });
      const fundExitOn = val('fundExitFeeEnabled') === 'yes'; setWrapVisible('fundExitFeeRateWrap', fundExitOn && val('fundExitFeeBase') !== 'fixed'); setWrapVisible('fundExitFixedFeeWrap', fundExitOn && val('fundExitFeeBase') === 'fixed');
      ['fundExitFeeBase'].forEach(id => { const el = document.getElementById(id); if (el) el.disabled = !fundExitOn });
      const perfOn = val('performanceFeeEnabled') === 'yes';
      ['hurdleRate', 'hurdleMethod', 'performanceFeeRate', 'performanceFeeBase', 'catchupEnabled', 'catchupRate', 'performanceCrystallizationYear'].forEach(id => { const el = document.getElementById(id); if (el) el.disabled = !perfOn });
      const catchup = document.getElementById('catchupRate'); if (catchup) catchup.disabled = !perfOn || val('catchupEnabled') !== 'yes';
      const financeOn = val('financeEnabled') !== 'no';
      ['financeBase', 'financingRate', 'financeArrangementFeeRate', 'financeInterestMethod', 'annualFinanceRate', 'financeDrawYears', 'financeRepaymentStartYear', 'financeRepaymentYears'].forEach(id => { const el = document.getElementById(id); if (el) el.disabled = !financeOn; });
      document.querySelectorAll('#financeDrawTable input').forEach(el => el.disabled = !financeOn); document.querySelectorAll('#financeRepaymentTable input').forEach(el => el.disabled = !financeOn);

      updateRevenueComponentOptions();
      document.querySelectorAll('#componentsTable tbody tr').forEach(tr => { tr.querySelectorAll('input,select').forEach(x => { if (!x.dataset.boundComponentRefresh) { x.addEventListener('input', () => { updateRevenueComponentOptions(); calculateAll(); }); x.dataset.boundComponentRefresh = '1'; } }); });
      document.querySelectorAll('#revenueTable tbody tr').forEach(tr => {
        const method = tr.querySelector('[data-field="method"] select')?.value; const source = tr.querySelector('[data-field="qtySource"] select')?.value || 'manual'; const comp = getLinkedComponentForRevenueRow(tr); tr.dataset.componentId = tr.querySelector('[data-field="component"] select')?.value || ''; if (source !== 'manual') updateAutoQtyPreview(tr);
        const visible = {
          areaSale: { qty: true, price: true, period: false, occupancy: false, qtyHelp: 'المساحة البيعية', priceHelp: 'سعر البيع للمتر' },
          dailyRent: { qty: true, price: true, period: false, occupancy: true, qtyHelp: 'عدد الوحدات', priceHelp: 'السعر اليومي' },
          monthlyAreaRent: { qty: true, price: true, period: false, occupancy: true, qtyHelp: 'المساحة', priceHelp: 'إيجار المتر الشهري' },
          monthlyUnitRent: { qty: true, price: true, period: false, occupancy: true, qtyHelp: 'عدد الوحدات', priceHelp: 'الإيجار الشهري للوحدة' },
          areaRent: { qty: true, price: true, period: false, occupancy: true, qtyHelp: 'المساحة', priceHelp: 'إيجار المتر السنوي' },
          unitRent: { qty: true, price: true, period: false, occupancy: true, qtyHelp: 'عدد الوحدات', priceHelp: 'إيجار الوحدة السنوي' },
          weeklyUnit: { qty: true, price: true, period: true, occupancy: true, qtyHelp: 'عدد الوحدات', priceHelp: 'السعر الأسبوعي' },
          tickets: { qty: true, price: true, period: false, occupancy: true, qtyHelp: 'عدد الزوار', priceHelp: 'سعر التذكرة' },
          commission: { qty: true, price: true, period: false, occupancy: true, qtyHelp: 'قيمة العمليات', priceHelp: 'نسبة العمولة %' },
          subscription: { qty: true, price: true, period: false, occupancy: true, qtyHelp: 'عدد المشتركين', priceHelp: 'قيمة الاشتراك' },
          fixed: { qty: true, price: false, period: false, occupancy: true, qtyHelp: 'القيمة السنوية' },
          percentRevenue: { qty: false, price: true, period: false, occupancy: false, priceHelp: 'النسبة من الإيرادات %' },
          custom: { qty: true, price: true, period: true, occupancy: true, qtyHelp: 'مدخل 1', priceHelp: 'مدخل 2' }
        }[method] || {};
        setCustomFormulaVisible(tr, method === 'custom'); setCellVisible(tr, 'component', !!visible.qty, 'اختر المكون المرتبط'); setCellVisible(tr, 'qtySource', !!visible.qty, 'مصدر الكمية'); setCellVisible(tr, 'qty', !!visible.qty, visible.qtyHelp);
        const qtyInput = tr.querySelector('[data-field="qty"] input');
        if (qtyInput) { const locked = !!visible.qty && source !== 'manual'; qtyInput.readOnly = locked; qtyInput.classList.toggle('locked-input', locked); }
        setCellVisible(tr, 'price', !!visible.price, visible.priceHelp); setCellVisible(tr, 'period', !!visible.period, 'الفترة / الأسابيع'); setCellVisible(tr, 'occupancy', !!visible.occupancy, 'الإشغال السنوي المستهدف');
      });

      const devYears = Math.max(1, Math.round(num('developmentYears') || 1));
      document.querySelectorAll('#scheduleTable tbody tr').forEach(tr => { const year = parseNumber(tr.dataset.stageYear || 1); if (year > devYears) tr.dataset.stageYear = String(devYears); });
      document.querySelectorAll('#costTable tbody tr').forEach(tr => {
        const method = tr.querySelector('[data-field="method"] select')?.value;
        const visible = { areaCost: { qty: true, price: true, duration: false }, unitCost: { qty: true, price: true, duration: false }, fixed: { qty: true, price: false, duration: false }, percentExecution: { qty: false, price: true, duration: false }, monthlyDuration: { qty: false, price: true, duration: true }, percentRevenue: { qty: false, price: true, duration: false }, custom: { qty: true, price: true, duration: true } }[method] || {};
        setCustomFormulaVisible(tr, method === 'custom'); setCellVisible(tr, 'qty', !!visible.qty); setCellVisible(tr, 'price', !!visible.price); setCellVisible(tr, 'duration', !!visible.duration);
      });
      document.querySelectorAll('#opexTable tbody tr').forEach(tr => {
        const method = tr.querySelector('[data-field="method"] select')?.value;
        const visible = { monthlyFixed: { qty: true, price: false }, percentRevenue: { qty: false, price: true }, staffSalary: { qty: true, price: true }, annualFixed: { qty: true, price: false }, perUnit: { qty: true, price: true }, perM2: { qty: true, price: true }, custom: { qty: true, price: true } }[method] || {};
        setCustomFormulaVisible(tr, method === 'custom'); setCellVisible(tr, 'qty', !!visible.qty); setCellVisible(tr, 'price', !!visible.price);
      });
      document.querySelectorAll('#externalTable tbody tr').forEach(tr => {
        const method = tr.querySelector('[data-field="method"] select')?.value;
        const visible = { fixed: { base: true, qty: false, price: false }, qtyPrice: { base: false, qty: true, price: true }, areaPrice: { base: false, qty: true, price: true }, percentRevenue: { base: false, qty: false, price: true }, percentCost: { base: false, qty: false, price: true }, recurring: { base: true, qty: false, price: false }, custom: { base: true, qty: true, price: true } }[method] || {};
        setCustomFormulaVisible(tr, method === 'custom'); setCellVisible(tr, 'base', !!visible.base); setCellVisible(tr, 'qty', !!visible.qty); setCellVisible(tr, 'price', !!visible.price);
      });
    }

    function calculateDeveloperBaseAmount(baseType, totals) {
      const execution = totals.execution || 0, design = totals.design || 0, services = totals.services || 0, costTotal = totals.costTotal || 0, externalCost = totals.externalCost || 0, landCostIncluded = totals.landCostIncluded || 0;
      if (baseType === 'executionServices') return execution + services;
      if (baseType === 'executionDesignServices') return execution + design + services;
      if (baseType === 'projectNoLand') return costTotal + externalCost;
      if (baseType === 'projectWithLand') return costTotal + externalCost + landCostIncluded;
      return execution;
    }

    function projectModeFlags() { const mode = val('unitRevenueMode') || 'mixed'; return { mode, sales: mode === 'sale' || mode === 'mixed', rental: mode === 'rental' || mode === 'mixed', anyRevenue: mode !== 'nonRevenue' } }
    function syncProjectYearBounds(totalYears, developmentYears) {
      ['salesStartYear', 'landContributionYear', 'saleExitYear', 'operatingExitYear', 'roiEndYear', 'irrEndYear', 'fundFeeStartYear', 'fundFeeEndYear', 'performanceCrystallizationYear', 'graceStartYear'].forEach(id => { const el = document.getElementById(id); if (!el) return; el.max = String(totalYears); const raw = String(el.value ?? '').trim(); if (raw === '') return; const n = parseNumber(raw); if (n > totalYears) el.value = String(totalYears); if (n < 1) el.value = '1' });
      document.querySelectorAll('#scheduleTable tbody tr').forEach(tr => { const year = parseNumber(tr.dataset.stageYear || 1); if (year > developmentYears) tr.dataset.stageYear = String(developmentYears) });
    }
    function validateComponentAreas() {
      const limit = Math.max(0, num('builtUpAreaAbove')); const used = [...document.querySelectorAll('#componentsTable tbody tr')].reduce((s, tr) => s + Math.max(0, parseNumber(tr.querySelector('[data-field="builtArea"] input')?.value)), 0); const remaining = limit - used, valid = used <= limit + .01;
      const panel = document.getElementById('componentAreaValidation'); if (panel) { panel.classList.toggle('error', !valid); panel.innerHTML = valid ? `<span>تم تخصيص</span> <b>${money(used)}</b> <span>م²</span> <span>من أصل</span> <b>${money(limit)}</b> <span>م²</span> — <span>المتبقي</span> <b>${money(remaining)}</b> <span>م²</span>.` : `<span>خطأ:</span> <span>مجموع المساحات المبنية للمكونات يتجاوز مسطحات البناء فوق الأرض بمقدار</span> <b>${money(-remaining)}</b> <span>م²</span>. <span>عدّل المساحات قبل اعتماد النتائج أو التصدير.</span>` }
      // The .area-invalid rule already exists in the stylesheet; without this toggle the block
      // never got its red border, so the only cue was the text panel.
      document.querySelector('#componentsTable')?.closest('.finance-block')?.classList.toggle('area-invalid', !valid);
      return { valid, used, limit, remaining };
    }
    function updateGraceRevenueOptions() { const select = document.getElementById('graceRevenueId'); if (!select) return; const current = select.value; const rows = [...document.querySelectorAll('#revenueTable tbody tr')].filter(tr => tr.querySelector('[data-field="method"] select')?.value !== 'areaSale'); select.innerHTML = rows.map((tr, i) => `<option value="${tr.dataset.revenueKey}">${tr.querySelector('[data-field="name"] input')?.value || (trDynamicI18n('إيراد') + ' ' + (i + 1))}</option>`).join(''); if (rows.some(tr => tr.dataset.revenueKey === current)) select.value = current; refreshDynamicI18n(select); }
    document.addEventListener('wf:lang', () => {
      try { updateRevenueComponentOptions(); } catch (e) { /* ignore */ }
      try { updateGraceRevenueOptions(); } catch (e) { /* ignore */ }
    });
    function graceYearFraction(year) { if (val('graceEnabled') !== 'yes') return 0; const start = (Math.max(1, Math.round(num('graceStartYear') || 1)) - 1) * 12, end = start + Math.max(0, num('graceDurationMonths')), ys = (year - 1) * 12, ye = year * 12; return Math.max(0, Math.min(ye, end) - Math.max(ys, start)) / 12 }
    function addGraceScheduleRow(d = {}) { const tb = document.querySelector('#graceScheduleTable tbody'); if (!tb) return; const tr = document.createElement('tr'); tr.innerHTML = `<td data-field="year"><input type="number" min="1" value="${financialInputNumber(d.year, 1)}"></td><td data-field="amount"><input type="number" min="0" value="${financialInputNumber(d.amount, 0)}"></td><td>${rowActionsHtml()}</td>`; tb.appendChild(tr); tr.querySelectorAll('input').forEach(x => x.addEventListener('input', calculateAll)); enhanceNumericInputs(tr) }
    function collectGraceSchedule() { return [...document.querySelectorAll('#graceScheduleTable tbody tr')].map(tr => ({ year: parseNumber(tr.querySelector('[data-field="year"] input')?.value) || 1, amount: Math.max(0, parseNumber(tr.querySelector('[data-field="amount"] input')?.value)) })) }
    function setConditionalVisibility(target, visible) {
      const element = typeof target === 'string' ? document.getElementById(target) : target;
      if (!element) return;
      element.classList.toggle('conditional-off', !visible);
      element.hidden = !visible;
      element.setAttribute('aria-hidden', visible ? 'false' : 'true');
    }

    function setConditionalSelector(selector, visible) {
      document.querySelectorAll(selector).forEach(element => setConditionalVisibility(element, visible));
    }

    function applyConditionalVisibility(flags) {
      const graceOn = flags.rental && val('graceEnabled') === 'yes';
      const selectedGraceRevenue = graceOn && val('graceScope') === 'selectedRevenue';
      const scheduledGrace = graceOn && val('graceMethod') === 'schedule';
      const financeOn = val('financeEnabled') === 'yes';
      const fundOn = val('fundEnabled') === 'yes';
      const feesOn = fundOn && val('fundFeesEnabled') === 'yes';
      const fundExitEnabled = feesOn && val('fundExitFeeEnabled') === 'yes';
      const performanceEnabled = feesOn && val('performanceFeeEnabled') === 'yes';
      const catchupEnabled = performanceEnabled && val('catchupEnabled') === 'yes';
      const exitOn = val('exitEnabled') === 'yes';

      setConditionalVisibility('salesStartYearWrap', flags.sales);
      setConditionalVisibility('salesYearsWrap', flags.sales);
      setConditionalVisibility('operationYearsWrap', flags.rental);
      setConditionalVisibility('operationStartYearWrap', flags.rental);
      setConditionalVisibility('rentalRevenueDetails', flags.rental);
      setConditionalVisibility('graceBlock', flags.rental);
      setConditionalVisibility('graceDetails', graceOn);
      setConditionalVisibility('graceRevenueWrap', selectedGraceRevenue);
      setConditionalVisibility('graceScheduleWrap', scheduledGrace);
      setConditionalVisibility('developerBonusBlock', flags.sales);
      setConditionalVisibility('developerBonusDetails', flags.sales && val('developerBonusEnabled') === 'yes');
      setConditionalVisibility('externalDetails', val('externalEnabled') === 'yes');
      setConditionalVisibility('developerPaymentsDetails', val('developerPaymentsEnabled') === 'yes');

      setConditionalSelector('#financeBlock .grid.four>div:not(:first-child),#financeBlock h4,#financeBlock .table-wrap,#financeBlock p.help', financeOn);
      setConditionalSelector('#fundBlock .grid.four>div:not(:first-child),#fundBlock h4,#fundBlock .table-wrap,#fundBlock button', fundOn);
      setConditionalSelector('#fundBlock .grid.four>div:nth-child(n+3),#fundBlock h4,#fundBlock .table-wrap,#fundBlock button', feesOn);
      setConditionalVisibility('fundExitPerformanceGrid', feesOn);
      setConditionalVisibility('fundExitFeeEnabledWrap', feesOn);
      setConditionalVisibility('fundExitFeeBaseWrap', fundExitEnabled);
      setConditionalVisibility('fundExitFeeRateWrap', fundExitEnabled && val('fundExitFeeBase') !== 'fixed');
      setConditionalVisibility('fundExitFixedFeeWrap', fundExitEnabled && val('fundExitFeeBase') === 'fixed');
      setConditionalVisibility('performanceFeeEnabledWrap', feesOn);
      ['hurdleRateWrap', 'hurdleMethodWrap', 'performanceFeeRateWrap', 'performanceFeeBaseWrap', 'catchupEnabledWrap', 'performanceCrystallizationYearWrap', 'performanceFeeTotalWrap'].forEach(id => setConditionalVisibility(id, performanceEnabled));
      setConditionalVisibility('catchupRateWrap', catchupEnabled);
      setConditionalSelector('#exitBlock .grid.four>div:not(:first-child)', exitOn);
      setConditionalSelector('.cf-sales', flags.sales);
      setConditionalSelector('.cf-rental', flags.rental);
      setConditionalSelector('.cf-finance', financeOn);
      setConditionalSelector('.cf-fund', feesOn);
      setConditionalSelector('.cf-grace', graceOn);

      const saleExitMethod = val('saleExitMethod') || 'none';
      const saleExitActive = exitOn && saleExitMethod !== 'none';

      ['resSaleRevenue'].forEach(id => setConditionalVisibility(document.getElementById(id)?.closest('.metric'), flags.sales));
      ['resSaleExitGross', 'resSaleExit'].forEach(id => setConditionalVisibility(document.getElementById(id)?.closest('.metric'), exitOn && saleExitActive && flags.sales));
      ['resRevenueY1', 'resNOIY1', 'resFullOccupancyRevenue', 'resFullOccupancyOpex', 'resFullOccupancyNOI', 'resOperatingExitGross', 'resOperatingExit'].forEach(id => setConditionalVisibility(document.getElementById(id)?.closest('.metric'), flags.rental));
      ['resFinanceCost', 'resCashEquity', 'resEquityRequired', 'resIRR', 'resEquityPayback'].forEach(id => setConditionalVisibility(document.getElementById(id)?.closest('.metric'), financeOn));
      setConditionalVisibility(document.getElementById('resFundFees')?.closest('.metric'), feesOn);
      ['resOperatingExitGross', 'resOperatingExit', 'resTerminal'].forEach(id => setConditionalVisibility(document.getElementById(id)?.closest('.metric'), exitOn));
    }
    function reorderResultCards() {
      const container = document.getElementById('resultsCards'); if (!container) return;
      container.querySelectorAll('.result-group-title').forEach(node => node.remove());
      const groups = [['التكاليف والاستثمار', ['resProjectCostBeforeFinance', 'resDevCost', 'resProjectCost', 'resFinanceCost', 'resFundFees', 'resTotalInvestmentCost']], ['الإيرادات وصافي الدخل', ['resSaleRevenue', 'resRevenueY1', 'resNOIY1', 'resFullOccupancyRevenue', 'resFullOccupancyOpex', 'resFullOccupancyNOI']], ['التمويل وحقوق الملكية', ['resLandEquity', 'resCashEquity', 'resEquityRequired']], ['التخارج', ['resSaleExitGross', 'resSaleExit', 'resOperatingExitGross', 'resOperatingExit', 'resTerminal']], ['مؤشرات العائد والاسترداد', ['resROI', 'resProjectIRR', 'resIRR', 'resPayback', 'resEquityPayback']]];
      groups.forEach(([title, ids]) => {
        const visibleCards = ids.map(id => document.getElementById(id)?.closest('.metric')).filter(c => c && !c.classList.contains('conditional-off') && !c.classList.contains('dynamic-off') && !c.classList.contains('hidden') && !c.hidden && c.style.display !== 'none');
        if (!visibleCards.length) return;
        const heading = document.createElement('h4');
        heading.className = 'result-group-title';
        heading.textContent = title;
        container.appendChild(heading);
        visibleCards.forEach(card => container.appendChild(card));
      });
    }

    function calculateAll() {
      const modeFlags = projectModeFlags();
      applyConditionalVisibility(modeFlags);
      updateDynamicFields();
      updateGraceRevenueOptions();
      const developmentYears = Math.max(1, Math.min(20, Math.round(num('developmentYears') || 1)));
      const operationYears = modeFlags.rental ? Math.max(0, Math.min(40, Math.round(num('operationYears')))) : 0;
      if (modeFlags.rental && document.querySelectorAll('#occupancyRampTable tbody tr').length !== operationYears) syncOccupancyRamp();
      const salesStartYear = Math.max(1, Math.round(num('salesStartYear') || 1));
      const salesYears = Math.max(1, Math.min(20, Math.round(num('salesYears') || 1)));
      const operationStartYear = modeFlags.rental ? developmentYears + 1 : 0;
      const rentalEndYear = modeFlags.rental ? developmentYears + operationYears : developmentYears;
      const salesEndYear = modeFlags.sales ? salesStartYear + salesYears - 1 : developmentYears;
      const naturalTotalYears = Math.max(developmentYears, rentalEndYear, salesEndYear);
      const totalYears = naturalTotalYears;
      syncProjectYearBounds(totalYears, developmentYears);
      const disp = document.getElementById('totalProjectYearsDisplay');
      const enteredYears = num('developmentYears') || num('operationYears') || num('salesYears') || num('salesStartYear');
      if (disp) disp.value = enteredYears ? totalYears + ' سنة' : '';
      const landArea = num('landArea'), coverage = num('coverageRate') / 100, basement = num('basementArea');
      const builtUpAreaAbove = num('builtUpAreaAbove');
      const landMethod = val('landValueMethod'), landStatus = val('landStatus'), rentMethod = val('landRentMethod');
      const covered = landArea * coverage, open = landArea - covered;
      let landValue = 0;
      if (landMethod === 'perM2') landValue = landArea * num('landPricePerM2');
      else if (landMethod === 'manual') landValue = num('manualLandValue');
      let landRent = 0;
      if (rentMethod === 'percentLandValue') landRent = landValue * (num('landRentRate') / 100);
      else if (rentMethod === 'annualFixed') landRent = num('manualAnnualLandRent');
      else if (rentMethod === 'monthlyFixed') landRent = num('monthlyLandRent') * 12;
      const landCostIncluded = landStatus === 'ownedIncluded' ? landValue : 0;
      const landContributionType = val('landContributionType') || 'inKind';
      const landContributionYear = Math.max(1, Math.min(totalYears, Math.round(num('landContributionYear') || 1)));
      const covEl = document.getElementById('coveredArea'), openEl = document.getElementById('openArea'), tBuiltEl = document.getElementById('totalBuiltUpArea'), opStartEl = document.getElementById('operationStartYear'), lValEl = document.getElementById('landValue'), aRentEl = document.getElementById('annualLandRent');
      if (covEl) covEl.value = money(covered); if (openEl) openEl.value = money(open); if (tBuiltEl) tBuiltEl.value = money(builtUpAreaAbove + basement); if (opStartEl) opStartEl.value = modeFlags.rental ? (num('developmentYears') ? 'السنة ' + operationStartYear : '') : 'غير مطبق'; if (lValEl) lValEl.value = money(landValue); if (aRentEl) aRentEl.value = money(landRent);
      if (document.getElementById('landCostIncluded')) document.getElementById('landCostIncluded').value = money(landCostIncluded);
      if (document.getElementById('landRentSummary')) document.getElementById('landRentSummary').value = money(landRent);

      let leasable = 0, componentSaleArea = 0;
      document.querySelectorAll('#componentsTable tbody tr').forEach(tr => {
        const builtArea = parseNumber(tr.querySelector('[data-field="builtArea"] input')?.value);
        const revenueArea = parseNumber(tr.querySelector('[data-field="revenueArea"] input')?.value);
        const model = tr.querySelector('[data-field="investmentModel"] select')?.value || 'nonRevenue';
        if (model === 'sale') componentSaleArea += revenueArea;
        if (['dailyRent', 'monthlyRent', 'annualRent', 'operating'].includes(model)) leasable += revenueArea;
        const cell = tr.querySelector('.compResult'); if (cell) cell.textContent = { sale: 'وحدات بيعية', dailyRent: 'إيجار يومي', monthlyRent: 'إيجار شهري', annualRent: 'إيجار سنوي', operating: 'تأجير آخر', nonRevenue: 'بدون إيراد' }[model] + ` | مبني ${money(builtArea)} م²`;
      });

      let operatingRevenueBase = 0, saleRevenueTotal = 0, saleAreaTotal = 0;
      const revRows = [...document.querySelectorAll('#revenueTable tbody tr')];
      revRows.forEach(tr => {
        const method = tr.querySelector('[data-field="method"] select')?.value || 'areaRent';
        const res = calculateRevenueBase(tr, 0);
        if (method === 'areaSale' && modeFlags.sales) { saleRevenueTotal += res; saleAreaTotal += getRevenueQuantity(tr); }
        else if (method !== 'percentRevenue' && modeFlags.rental) operatingRevenueBase += res;
        const c1 = tr.querySelector('.revResult'), c2 = tr.querySelector('.revenueFormula'); if (c1) c1.textContent = money(res); if (c2) c2.textContent = formulaText(method);
      });
      revRows.forEach(tr => {
        const method = tr.querySelector('[data-field="method"] select')?.value || 'areaRent';
        if (method === 'percentRevenue' && modeFlags.rental) {
          const res = calculateRevenueBase(tr, operatingRevenueBase);
          const c1 = tr.querySelector('.revResult'); if (c1) c1.textContent = money(res);
        }
      });
      if (!saleAreaTotal) saleAreaTotal = componentSaleArea;

      let executionCost = 0, costTotal = 0;
      const classTotals = { execution: 0, design: 0, services: 0, advertising: 0, operationSetup: 0, external: 0 };
      const costRows = [...document.querySelectorAll('#costTable tbody tr')];
      costRows.forEach(tr => {
        const i = tr.querySelectorAll('input,select'); const cls = i[1]?.value, method = i[2]?.value;
        if (cls === 'execution' && method !== 'percentExecution') { executionCost += calculateCostRow(tr, 0, operatingRevenueBase); }
        const c2 = tr.querySelector('.costFormula'); if (c2) c2.textContent = formulaText(method);
      });
      costRows.forEach(tr => {
        const i = tr.querySelectorAll('input,select'); const cls = i[1]?.value;
        const res = calculateCostRow(tr, executionCost, operatingRevenueBase);
        costTotal += res; if (classTotals[cls] !== undefined) classTotals[cls] += res;
        const c1 = tr.querySelector('.costResult'); if (c1) c1.textContent = money(res);
      });

      const opexRows = [...document.querySelectorAll('#opexTable tbody tr')];
      opexRows.forEach(tr => {
        const i = tr.querySelectorAll('input,select'); const method = i[1]?.value;
        const res = calculateOpexRow(tr, operatingRevenueBase);
        const c1 = tr.querySelector('.opexResult'), c2 = tr.querySelector('.opexFormula'); if (c1) c1.textContent = money(res); if (c2) c2.textContent = formulaText(method);
      });

      let externalRevenue = 0, externalCost = 0, externalOpex = 0;
      const externalOn = val('externalEnabled') === 'yes';
      const externalRows = [...document.querySelectorAll('#externalTable tbody tr')];
      externalRows.forEach(tr => {
        if (!externalOn) { const c = tr.querySelector('.externalResult'); if (c) c.textContent = '0'; return }
        const i = tr.querySelectorAll('input,select'); const method = i[2]?.value;
        const ex = calculateExternalRow(tr, operatingRevenueBase, costTotal);
        if (ex.type === 'revenue') externalRevenue += ex.value;
        if (ex.type === 'cost' || ex.type === 'asset' || ex.type === 'tax') externalCost += ex.value;
        if (ex.type === 'opex') externalOpex += ex.value;
        const c1 = tr.querySelector('.externalResult'), c2 = tr.querySelector('.externalFormula'); if (c1) c1.textContent = money(ex.value); if (c2) c2.textContent = formulaText(method);
      });

      const developerBaseAmount = calculateDeveloperBaseAmount(val('developerBase'), { execution: executionCost, design: classTotals.design, services: classTotals.services, costTotal, externalCost, landCostIncluded });
      const developerCost = developerBaseAmount * (num('developerRate') / 100);
      const projectCost = costTotal + developerCost + externalCost + landCostIncluded;
      const fundOn = val('fundEnabled') === 'yes', fundFeesOn = fundOn && val('fundFeesEnabled') !== 'no';
      const fundFeeBase = val('fundFeeBase') || 'fundCapital', fundCapitalInput = Math.max(0, num('fundCapitalInput')), fundNavInput = Math.max(0, num('fundNavInput')), fundManagementRate = Math.max(0, num('fundManagementRate')) / 100, fundFixedAnnualFee = Math.max(0, num('fundFixedAnnualFee')), fundFeeStartYear = Math.max(1, num('fundFeeStartYear') || 1), fundFeeEndYear = Math.max(fundFeeStartYear, num('fundFeeEndYear') || developmentYears), fundFeeGrowthRate = num('fundFeeGrowthRate');
      const fundAdditionalFeeRows = [...document.querySelectorAll('#fundAdditionalFeesTable tbody tr')].map(tr => ({ tr, name: tr.querySelector('[data-field="name"] input')?.value || '', method: tr.querySelector('[data-field="method"] select')?.value || 'fixed', value: Math.max(0, parseNumber(tr.querySelector('[data-field="value"] input')?.value)), startYear: Math.max(1, Math.round(parseNumber(tr.querySelector('[data-field="startYear"] input')?.value) || 1)), endYear: Math.max(1, Math.round(parseNumber(tr.querySelector('[data-field="endYear"] input')?.value) || 1)), recurrence: tr.querySelector('[data-field="recurrence"] select')?.value || 'once', total: 0 }));
      const fundExitFeeOn = fundFeesOn && val('fundExitFeeEnabled') === 'yes', performanceFeeOn = fundFeesOn && val('performanceFeeEnabled') === 'yes', performanceCrystallizationYear = Math.max(1, Math.min(totalYears, Math.round(num('performanceCrystallizationYear') || totalYears)));
      const exitOn = val('exitEnabled') === 'yes', exitMethod = exitOn && modeFlags.rental ? val('exitMethod') : 'none', exitInput = num('exitInput'), saleExitMethod = exitOn && modeFlags.sales ? (val('saleExitMethod') || 'none') : 'none', saleExitYear = Math.max(1, Math.min(totalYears, Math.round(num('saleExitYear') || totalYears))), operatingExitYear = Math.max(1, Math.min(totalYears, Math.round(num('operatingExitYear') || totalYears))), saleExitCostRate = Math.max(0, num('saleExitCostRate')) / 100, operatingExitCostRate = Math.max(0, num('operatingExitCostRate')) / 100, settleDebtAtExit = val('settleDebtAtExit') !== 'no';
      const activeExitYears = []; if (saleExitMethod !== 'none') activeExitYears.push(saleExitYear); if (exitMethod !== 'none') activeExitYears.push(operatingExitYear);
      const equityDistributionYear = activeExitYears.length ? Math.max(...activeExitYears) : totalYears;
      const financeOn = val('financeEnabled') === 'yes', financeShare = financeOn ? Math.max(0, Math.min(100, num('financingRate'))) / 100 : 0, financeBase = val('financeBase') || 'withLand', financeBaseAmount = Math.max(0, financeBase === 'withoutLand' ? projectCost - landCostIncluded : projectCost), facilityAmount = financeBaseAmount * financeShare, arrangementFee = financeOn ? facilityAmount * (num('financeArrangementFeeRate') / 100) : 0, annualFinanceRate = financeOn ? num('annualFinanceRate') / 100 : 0, financeInterestMethod = val('financeInterestMethod') || 'declining', financeDrawYears = Math.max(0, Math.min(20, Math.round(num('financeDrawYears'))));
      if (document.querySelectorAll('#financeDrawTable tbody tr').length !== financeDrawYears) syncFinanceDrawPlan();
      const financePlan = [...document.querySelectorAll('#financeDrawTable tbody tr')].map(tr => ({ tr, year: parseNumber(tr.querySelector('[data-field="year"] input')?.value) || 1, drawPct: Math.max(0, parseNumber(tr.querySelector('[data-field="drawPct"] input')?.value)) }));
      const financeDrawPctTotal = financePlan.reduce((sum, row) => sum + row.drawPct, 0);
      financePlan.forEach(row => { const amount = financeDrawPctTotal ? facilityAmount * (row.drawPct / financeDrawPctTotal) : 0; const c = row.tr.querySelector('.financeDrawAmount'); if (c) c.textContent = money(amount); });
      const financeRepaymentStartYear = Math.max(1, Math.min(totalYears, Math.round(num('financeRepaymentStartYear') || 1))), financeRepaymentYears = Math.max(0, Math.min(40, Math.round(num('financeRepaymentYears'))));
      if (document.querySelectorAll('#financeRepaymentTable tbody tr').length !== financeRepaymentYears) syncFinanceRepaymentPlan();
      const financeRepaymentPlan = [...document.querySelectorAll('#financeRepaymentTable tbody tr')].map(tr => ({ tr, year: parseNumber(tr.querySelector('[data-field="year"] input')?.value) || 1, repaymentPct: Math.max(0, parseNumber(tr.querySelector('[data-field="repaymentPct"] input')?.value)) }));
      const financeRepaymentPctTotal = financeRepaymentPlan.reduce((sum, row) => sum + row.repaymentPct, 0);
      financeRepaymentPlan.forEach(row => { const amount = financeRepaymentPctTotal ? facilityAmount * (row.repaymentPct / financeRepaymentPctTotal) : 0; const c = row.tr.querySelector('.financeRepaymentAmount'); if (c) c.textContent = money(amount); });

      const scheduleRows = val('developerPaymentsEnabled') === 'yes' ? [...document.querySelectorAll('#scheduleTable tbody tr')].map(tr => {
        const startYear = Math.max(1, Math.min(developmentYears, Math.round(parseNumber(tr.dataset.stageYear) || 1)));
        const endYear = Math.max(startYear, Math.min(developmentYears, Math.round(parseNumber(tr.dataset.stageEndYear) || startYear)));
        return {
          tr,
          name: tr.querySelector('[data-field="name"] input')?.value || 'مرحلة تطوير',
          year: startYear,
          endYear,
          spanYears: endYear - startYear + 1,
          costPct: Math.max(0, parseNumber(tr.querySelector('[data-field="costPct"] input')?.value)),
          devPct: Math.max(0, parseNumber(tr.querySelector('[data-field="devPct"] input')?.value))
        };
      }) : [];
      const costPctTotal = Math.min(100, scheduleRows.reduce((s, r) => s + r.costPct, 0)), devPctTotal = Math.min(100, scheduleRows.reduce((s, r) => s + r.devPct, 0)), developmentCostBase = costTotal + externalCost;
      let scheduleCostValueTotal = 0, scheduleDevValueTotal = 0;
      scheduleRows.forEach(r => { const stageCost = costPctTotal ? developmentCostBase * (r.costPct / costPctTotal) : 0, stageDev = devPctTotal ? developerCost * (r.devPct / devPctTotal) : 0; scheduleCostValueTotal += stageCost; scheduleDevValueTotal += stageDev; const c1 = r.tr.querySelector('.stageCost'), c2 = r.tr.querySelector('.stageDevPayment'); if (c1) c1.textContent = money(stageCost); if (c2) c2.textContent = money(stageDev); });
      renderSchedulePercentTotals(scheduleRows, scheduleCostValueTotal, scheduleDevValueTotal);

      const projected = [];
      const initialProjectLandFlow = landContributionType === 'inKind' ? -landCostIncluded : 0, initialEquityLandFlow = landContributionType === 'inKind' ? -landCostIncluded : 0;
      const projectCashflows = [initialProjectLandFlow], equityCashflows = [initialEquityLandFlow];
      let cumulative = 0, totalOperatingCF = 0, terminal = 0, saleExitValue = 0, operatingExitValue = 0, saleExitGross = 0, operatingExitGross = 0, totalExitCosts = 0, finalCF = 0, debtBalance = 0, totalDrawn = 0, totalFinanceInterest = 0, totalCashEquity = 0, totalEquityDistributions = 0, cumulativeInvestedCapital = 0, cashReserve = 0, totalFundManagementFees = 0, totalAdditionalFundFees = 0, fundExitFeeTotal = 0, performanceFeeTotal = 0, cumulativeBeforePerformance = 0, revenueY1 = 0, opexY1 = 0, noiY1 = 0, fullOccupancyRevenue = 0, fullOccupancyOpex = 0, fullOccupancyNOI = 0, totalGraceDiscount = 0;

      for (let year = 1; year <= totalYears; year++) {
        const inOperation = modeFlags.rental && year >= operationStartYear && (exitMethod === 'none' || year <= operatingExitYear), operationYear = inOperation ? year - developmentYears : 0, occupancyReach = inOperation ? occupancyReachForYear(operationYear) : 0, saleRevenue = (modeFlags.sales && year >= salesStartYear && year < Math.min(totalYears + 1, salesStartYear + salesYears)) ? saleRevenueTotal / Math.max(1, Math.min(salesYears, totalYears - salesStartYear + 1)) : 0;
        let revBaseAnnual = 0, revTotalAnnual = 0;
        revRows.forEach(tr => { const method = tr.querySelector('[data-field="method"] select')?.value || 'areaRent'; if (method !== 'percentRevenue' && method !== 'areaSale' && inOperation) { const base = calculateRevenueBase(tr, 0); revBaseAnnual += base * occupancyReach; revTotalAnnual += base * occupancyReach; } });
        revRows.forEach(tr => { const method = tr.querySelector('[data-field="method"] select')?.value || 'areaRent'; if (method === 'percentRevenue' && inOperation) { revTotalAnnual += calculateRevenueBase(tr, revBaseAnnual); } });

        let extRevenueAnnual = 0, extOpexAnnual = 0;
        if (externalOn) externalRows.forEach(tr => { const exType = tr.querySelector('[data-field="type"] select')?.value || 'revenue', startYear = parseNumber(tr.querySelector('[data-field="startYear"] input')?.value) || 1, endYear = parseNumber(tr.querySelector('[data-field="endYear"] input')?.value) || totalYears, growth = parseNumber(tr.querySelector('[data-field="growth"] input')?.value); if (year >= startYear && year <= endYear) { const ex = calculateExternalRow(tr, revTotalAnnual, costTotal); const val = ex.value * annualGrowthFactor(year - startYear + 1, growth); if (exType === 'revenue') extRevenueAnnual += val; if (exType === 'opex') extOpexAnnual += val; } });

        let graceSubjectRevenue = revTotalAnnual;
        if (val('graceScope') === 'selectedRevenue') { const selected = revRows.find(tr => tr.dataset.revenueKey === val('graceRevenueId')); if (selected && inOperation) { const method = selected.querySelector('[data-field="method"] select')?.value || 'areaRent'; graceSubjectRevenue = method === 'percentRevenue' ? calculateRevenueBase(selected, revBaseAnnual) : calculateRevenueBase(selected, 0) * occupancyReach } else graceSubjectRevenue = 0; }
        const scheduledGrace = collectGraceSchedule().filter(r => r.year === year).reduce((s, r) => s + r.amount, 0), calculatedGrace = Math.max(0, graceSubjectRevenue) * graceYearFraction(year) * Math.max(0, Math.min(100, num('graceDiscountRate'))) / 100, graceDiscount = val('graceEnabled') === 'yes' ? Math.min(revTotalAnnual + extRevenueAnnual, val('graceMethod') === 'schedule' ? scheduledGrace : calculatedGrace) : 0;
        totalGraceDiscount += graceDiscount;
        const operatingRevenue = Math.max(0, revTotalAnnual + extRevenueAnnual - graceDiscount);
        let opexAnnual = 0;
        if (inOperation) { opexRows.forEach(tr => { opexAnnual += calculateOpexRow(tr, operatingRevenue); }); opexAnnual += extOpexAnnual; }
        const annualLandRent = (landStatus === 'leased' || landStatus === 'usufruct') ? landRent : 0;
        const noi = operatingRevenue - opexAnnual - annualLandRent;
        if (operationYear === 1) {
          revenueY1 = operatingRevenue; opexY1 = opexAnnual; noiY1 = noi;
          let fullBaseAnnual = 0, fullRevenueAnnual = 0;
          revRows.forEach(tr => { const method = tr.querySelector('[data-field="method"] select')?.value || 'areaRent'; if (method !== 'percentRevenue' && method !== 'areaSale') { const base = calculateRevenueBase(tr, 0); fullBaseAnnual += base; fullRevenueAnnual += base; } });
          revRows.forEach(tr => { const method = tr.querySelector('[data-field="method"] select')?.value || 'areaRent'; if (method === 'percentRevenue') fullRevenueAnnual += calculateRevenueBase(tr, fullBaseAnnual); });
          let fullExternalRevenue = 0, fullExternalOpex = 0;
          if (externalOn) externalRows.forEach(tr => { const exType = tr.querySelector('[data-field="type"] select')?.value || 'revenue', startYear = parseNumber(tr.querySelector('[data-field="startYear"] input')?.value) || 1, endYear = parseNumber(tr.querySelector('[data-field="endYear"] input')?.value) || totalYears, growth = parseNumber(tr.querySelector('[data-field="growth"] input')?.value); if (year >= startYear && year <= endYear) { const ex = calculateExternalRow(tr, fullRevenueAnnual, costTotal); const amount = ex.value * annualGrowthFactor(year - startYear + 1, growth); if (exType === 'revenue') fullExternalRevenue += amount; if (exType === 'opex') fullExternalOpex += amount; } });
          fullOccupancyRevenue = fullRevenueAnnual + fullExternalRevenue;
          opexRows.forEach(tr => { fullOccupancyOpex += calculateOpexRow(tr, fullOccupancyRevenue) }); fullOccupancyOpex += fullExternalOpex;
          fullOccupancyNOI = fullOccupancyRevenue - fullOccupancyOpex - annualLandRent;
        }

        let developmentCost = 0, developerPayment = 0;
        scheduleRows.filter(r => year >= r.year && year <= r.endYear).forEach(r => {
          const span = Math.max(1, r.spanYears || 1);
          developmentCost += costPctTotal ? developmentCostBase * (r.costPct / costPctTotal) / span : 0;
          developerPayment += devPctTotal ? developerCost * (r.devPct / devPctTotal) / span : 0;
        });
        if (!costPctTotal && year <= developmentYears) developmentCost = developmentCostBase / developmentYears;
        if (!devPctTotal && year <= developmentYears) developerPayment = developerCost / developmentYears;
        const landPayment = (year === landContributionYear && landContributionType === 'cash') ? landCostIncluded : 0, landInKindContribution = (year === landContributionYear && landContributionType === 'inKind') ? landCostIncluded : 0;

        let saleExitGrossAnnual = 0, operatingExitGrossAnnual = 0;
        if (year === saleExitYear && saleExitMethod !== 'none') { if (saleExitMethod === 'remainingArea') saleExitGrossAnnual = num('saleExitRemainingArea') * num('saleExitPricePerM2'); else if (saleExitMethod === 'fixed') saleExitGrossAnnual = num('saleExitFixedValue'); }
        if (year === operatingExitYear && exitMethod !== 'none') { if (exitMethod === 'capRate') operatingExitGrossAnnual = (exitInput ? noi / (exitInput / 100) : 0); else if (exitMethod === 'fixed') operatingExitGrossAnnual = exitInput; else if (exitMethod === 'noiMultiple') operatingExitGrossAnnual = noi * exitInput; else if (exitMethod === 'revenueMultiple') operatingExitGrossAnnual = operatingRevenue * exitInput; }
        const saleExitCost = saleExitGrossAnnual * saleExitCostRate, operatingExitCost = operatingExitGrossAnnual * operatingExitCostRate, exitCosts = saleExitCost + operatingExitCost, saleExit = saleExitGrossAnnual - saleExitCost, operatingExit = operatingExitGrossAnnual - operatingExitCost, tv = saleExit + operatingExit;
        saleExitGross += saleExitGrossAnnual; operatingExitGross += operatingExitGrossAnnual; saleExitValue += saleExit; operatingExitValue += operatingExit; totalExitCosts += exitCosts; terminal += tv;

        const projectOutflow = developmentCost + developerPayment + landPayment, unlevered = saleRevenue + operatingRevenue + tv - projectOutflow - opexAnnual - annualLandRent, openingDebt = debtBalance;
        const planRow = financePlan.find(row => row.year === year), plannedDraw = financeDrawPctTotal && planRow ? facilityAmount * (planRow.drawPct / financeDrawPctTotal) : 0, draw = (financeOn && year <= financeDrawYears) ? Math.min(Math.max(0, facilityAmount - totalDrawn), plannedDraw) : 0;
        totalDrawn += draw;
        const outstandingBeforeRepayment = openingDebt + draw, firstDrawYear = financePlan.filter(row => row.drawPct > 0).reduce((min, row) => Math.min(min, row.year), 1), withinFixedInterestTerm = year >= firstDrawYear && year < firstDrawYear + financeRepaymentYears;
        const interest = financeOn ? (financeInterestMethod === 'fixed' ? (withinFixedInterestTerm ? facilityAmount * annualFinanceRate : 0) : (outstandingBeforeRepayment > 0 ? outstandingBeforeRepayment * annualFinanceRate : 0)) : 0, fee = year === firstDrawYear ? arrangementFee : 0;
        const repaymentRow = financeRepaymentPlan.find(row => row.year === year), plannedRepayment = financeRepaymentPctTotal && repaymentRow ? facilityAmount * (repaymentRow.repaymentPct / financeRepaymentPctTotal) : 0;
        let repayment = financeOn ? Math.min(openingDebt + draw, plannedRepayment) : 0;
        if (financeOn && settleDebtAtExit && exitMethod !== 'none' && year === operatingExitYear) repayment = openingDebt + draw;
        if (year === totalYears) repayment = openingDebt + draw;
        debtBalance = Math.max(0, openingDebt + draw - repayment); totalFinanceInterest += interest;

        let fundManagementFee = 0; const feeYearFraction = fundFeesOn ? activeYearFraction(year, fundFeeStartYear, fundFeeEndYear) : 0;
        if (feeYearFraction > 0) { let managementBase = 0; if (fundFeeBase === 'fundCapital') managementBase = fundCapitalInput; else if (fundFeeBase === 'investedCapital') managementBase = Math.max(cumulativeInvestedCapital + landInKindContribution, fundCapitalInput); else if (fundFeeBase === 'nav') managementBase = fundNavInput; else if (fundFeeBase === 'projectCost') managementBase = projectCost; const growthYears = Math.max(0, year - Math.ceil(fundFeeStartYear)); fundManagementFee = (fundFeeBase === 'fixed' ? fundFixedAnnualFee : managementBase * fundManagementRate) * Math.pow(1 + fundFeeGrowthRate / 100, growthYears) * feeYearFraction; }
        totalFundManagementFees += fundManagementFee;

        let additionalFundFees = 0; fundAdditionalFeeRows.forEach(row => { const active = fundFeesOn && (row.recurrence === 'annual' ? (year >= row.startYear && year <= row.endYear) : (year === row.startYear)); if (!active) return; const amount = calculateFundAdditionalFee(row.method, row.value, { fundCapital: fundCapitalInput, projectCost, exitValue: saleExitGrossAnnual + operatingExitGrossAnnual, profit: unlevered }); row.total += amount; additionalFundFees += amount; });
        totalAdditionalFundFees += additionalFundFees;

        const beforeFundExitFee = unlevered + draw - fee - interest - repayment - fundManagementFee - additionalFundFees;
        let fundExitFee = 0; if (fundExitFeeOn && (saleExitGrossAnnual + operatingExitGrossAnnual) > 0) { const fundExitBase = val('fundExitFeeBase') || 'saleValue'; if (fundExitBase === 'fixed') fundExitFee = Math.max(0, num('fundExitFixedFee')); else if (fundExitBase === 'saleValue') fundExitFee = (saleExitGrossAnnual + operatingExitGrossAnnual) * Math.max(0, num('fundExitFeeRate')) / 100; else fundExitFee = Math.max(0, cumulativeBeforePerformance + beforeFundExitFee) * Math.max(0, num('fundExitFeeRate')) / 100; }
        fundExitFeeTotal += fundExitFee;

        const beforePerformance = beforeFundExitFee - fundExitFee; cumulativeBeforePerformance += beforePerformance;
        let performanceFee = 0; if (performanceFeeOn && year === performanceCrystallizationYear) { const profit = Math.max(0, cumulativeBeforePerformance), capitalBase = Math.max(fundCapitalInput, cumulativeInvestedCapital + landInKindContribution), hurdle = Math.max(0, num('hurdleRate')) / 100, yearsHeld = Math.max(1, performanceCrystallizationYear), hurdleAmount = val('hurdleMethod') === 'simple' ? capitalBase * hurdle * yearsHeld : capitalBase * (Math.pow(1 + hurdle, yearsHeld) - 1), excess = Math.max(0, profit - hurdleAmount), carryRate = Math.max(0, Math.min(100, num('performanceFeeRate'))) / 100, performanceBase = val('performanceFeeBase') === 'projectProfit' ? profit : excess; performanceFee = performanceBase * carryRate; if (val('catchupEnabled') === 'yes' && val('performanceFeeBase') === 'aboveHurdle') { const targetCarry = profit * carryRate, catchupGap = Math.max(0, targetCarry - performanceFee); performanceFee += Math.min(catchupGap, excess * Math.max(0, Math.min(100, num('catchupRate'))) / 100); } }
        performanceFeeTotal += performanceFee;

        const fundFeesAnnual = fundManagementFee + additionalFundFees + fundExitFee + performanceFee, final = beforePerformance - performanceFee, cashFlowExcludingInKind = final, unleveredForIrr = unlevered, cashBeforeEquity = cashReserve + cashFlowExcludingInKind, cashEquityInjection = Math.max(0, -cashBeforeEquity);
        cashReserve = Math.max(0, cashBeforeEquity + cashEquityInjection);
        const equityDistribution = year === equityDistributionYear ? cashReserve : 0;
        cashReserve = Math.max(0, cashReserve - equityDistribution);
        const equityFlowForIrr = equityDistribution - cashEquityInjection;
        totalCashEquity += cashEquityInjection; totalEquityDistributions += equityDistribution; cumulativeInvestedCapital += landInKindContribution + cashEquityInjection;
        finalCF = final; totalOperatingCF += noi; cumulative += final;
        projectCashflows.push(unleveredForIrr); equityCashflows.push(equityFlowForIrr);
        projected.push({ year, phase: year <= developmentYears ? 'تطوير' : exitMethod !== 'none' && year > operatingExitYear ? 'بعد التخارج' : operationYear === 1 ? 'بدء التشغيل' : 'تشغيل', occupancyReach, operationYear, saleRevenue, operatingRevenue, revenue: saleRevenue + operatingRevenue, developmentCost, developerPayment, landPayment, landInKindContribution, landContributionType, opex: opexAnnual, landRent: annualLandRent, noi, terminal: tv, saleExit, operatingExit, saleExitGross: saleExitGrossAnnual, operatingExitGross: operatingExitGrossAnnual, exitCosts, fundManagementFee, additionalFundFees, fundExitFee, performanceFee, fundFeesAnnual, graceDiscount, openingDebt, financeDraw: draw, financeFee: fee, financeInterest: interest, financeRepayment: repayment, closingDebt: debtBalance, cashEquityInjection, equityDistribution, cashReserve, unlevered, unleveredForIrr, equityFlowForIrr, projectOutflow, final, cumulative, debtBalance });
      }

      fundAdditionalFeeRows.forEach(row => { const cell = row.tr.querySelector('.fundAdditionalFeeResult'); if (cell) cell.textContent = money(row.total); const formula = row.tr.querySelector('.fundAdditionalFeeFormula'); if (formula) formula.textContent = fundAdditionalFeeFormulaText(row.method); });

      const totalFinanceCost = arrangementFee + totalFinanceInterest, totalFundFees = totalFundManagementFees + totalAdditionalFundFees + fundExitFeeTotal + performanceFeeTotal, projectCostWithFinance = projectCost + totalFinanceCost, adjustedProjectCost = projectCostWithFinance + totalFundFees, landEquityContribution = landContributionType === 'inKind' ? landCostIncluded : 0, totalEquityRequired = landEquityContribution + totalCashEquity, recoveryCashflows = projected.map(row => row.saleRevenue + row.noi + row.terminal), payback = capitalRecoveryPeriod(adjustedProjectCost, recoveryCashflows), equityPayback = cashflowPaybackPeriod([initialEquityLandFlow, ...projected.map(row => row.equityFlowForIrr)]), roiPeriod = val('roiPeriod') || 'full', irrPeriod = val('irrPeriod') || 'full', roiEndYear = analysisEndYear(roiPeriod, num('roiEndYear'), developmentYears, totalYears), irrEndYear = analysisEndYear(irrPeriod, num('irrEndYear'), developmentYears, totalYears), roiRows = projected.filter(r => r.year <= roiEndYear), irrRows = projected.filter(r => r.year <= irrEndYear);
      const projectIrr = irr([initialProjectLandFlow, ...irrRows.map(r => r.unleveredForIrr)]), irrVal = irr([initialEquityLandFlow, ...irrRows.map(r => r.equityFlowForIrr)]);
      const roiInflows = roiRows.reduce((sum, r) => sum + r.saleRevenue + r.operatingRevenue + r.terminal, 0), roiOutflows = roiRows.reduce((sum, r) => sum + r.projectOutflow + r.opex + r.landRent + r.financeFee + r.financeInterest + r.fundFeesAnnual, 0);
      const roi = roiOutflows > 0 ? (roiInflows - roiOutflows) / roiOutflows : null, roiScope = periodLabel(roiEndYear, developmentYears, totalYears), irrScope = periodLabel(irrEndYear, developmentYears, totalYears);
      const warnings = [];
      const warnT = (key, fallback, params) => (typeof WFT === 'function' ? WFT(key, fallback, params) : fallback);
      if (saleExitMethod !== 'none' && saleExitYear > roiEndYear) warnings.push(warnT('financial.warn_sale_exit_outside_roi', 'التخارج البيعي في السنة ' + saleExitYear + ' خارج فترة ROI، ولذلك لا يدخل في ROI.', { year: saleExitYear }));
      if (exitMethod !== 'none' && operatingExitYear > roiEndYear) warnings.push(warnT('financial.warn_operating_exit_outside_roi', 'التخارج التشغيلي في السنة ' + operatingExitYear + ' خارج فترة ROI، ولذلك لا يدخل في ROI.', { year: operatingExitYear }));
      if (saleExitMethod !== 'none' && saleExitYear > irrEndYear) warnings.push(warnT('financial.warn_sale_exit_outside_irr', 'التخارج البيعي في السنة ' + saleExitYear + ' خارج فترة IRR المختارة.', { year: saleExitYear }));
      if (exitMethod !== 'none' && operatingExitYear > irrEndYear) warnings.push(warnT('financial.warn_operating_exit_outside_irr', 'التخارج التشغيلي في السنة ' + operatingExitYear + ' خارج فترة IRR المختارة.', { year: operatingExitYear }));
      if (exitMethod === 'capRate' && operatingExitYear < operationStartYear) warnings.push('سنة التخارج التشغيلي تسبق بدء التشغيل؛ لا يوجد NOI صالح لتطبيق معدل الرسملة.');
      if (landCostIncluded > 0 && landContributionType === 'none') warnings.push('قيمة الأرض داخلة في تكلفة المشروع لكنها مستبعدة من التدفقات؛ قد يؤدي ذلك إلى تضخيم مؤشرات العائد.');
      if (projectIrr === null) warnings.push('لا يمكن حساب Project IRR خلال الفترة المختارة لعدم وجود تدفقات موجبة وسالبة صالحة.');
      if (irrVal === null) warnings.push('لا يمكن حساب Equity IRR خلال الفترة المختارة لعدم وجود تدفقات موجبة وسالبة صالحة.');
      const warningBox = document.getElementById('analysisWarnings');
      const renderAnalysisWarnings = () => {
        if (!warningBox) return;
        warningBox.innerHTML = warnings.map(w => '<div>' + escapeHtml(w) + '</div>').join('');
        warningBox.classList.toggle('show', warnings.length > 0);
      };
      renderAnalysisWarnings();

      const setTxt = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
      const setHtml = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
      const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };

      setVal('executionCostTotal', money(executionCost));
      setVal('designCostTotal', money(classTotals.design));
      setVal('servicesCostTotal', money(classTotals.services));
      setVal('advertisingCostTotal', money(classTotals.advertising));
      setVal('developerBaseAmount', money(developerBaseAmount));
      setVal('developerCostValue', money(developerCost));

      setTxt('resLeasable', money(leasable) + ' م²');
      setTxt('resRevenueY1', money(revenueY1));
      setTxt('resProjectCostBeforeFinance', money(projectCost));
      setTxt('resProjectCost', money(projectCostWithFinance));
      setTxt('resNOIY1', money(noiY1));
      setTxt('resFullOccupancyRevenue', money(fullOccupancyRevenue));
      setTxt('resFullOccupancyOpex', money(fullOccupancyOpex));
      setTxt('resFullOccupancyNOI', money(fullOccupancyNOI));
      setTxt('resSaleExitGross', money(saleExitGross));
      setTxt('resSaleExit', money(saleExitValue));
      setTxt('resOperatingExitGross', money(operatingExitGross));
      setTxt('resOperatingExit', money(operatingExitValue));
      setHtml('resSaleExitScope', saleExitMethod === 'none' ? '<span>غير مفعل</span>' : `<span>السنة</span> ${saleExitYear} | <span>تكلفة التخارج</span> ${financialPercent(saleExitCostRate * 100)}`);
      renderSaleExitStatus({ modeFlags, exitOn, saleExitMethod, saleAreaTotal, saleExitGross, saleExitValue });
      setHtml('resOperatingExitScope', exitMethod === 'none' ? '<span>غير مفعل</span>' : `<span>السنة</span> ${operatingExitYear} | <span>تكلفة التخارج</span> ${financialPercent(operatingExitCostRate * 100)}`);
      setTxt('resTerminal', money(terminal));
      setTxt('resYear0', '0');
      setTxt('resLandRent', money(landRent));
      setTxt('resDevCost', money(developerCost));
      setTxt('resSaleRevenue', money(saleRevenueTotal));
      setTxt('resFinanceCost', money(totalFinanceCost));
      setTxt('resFundFees', money(totalFundFees));
      setTxt('resTotalInvestmentCost', money(adjustedProjectCost));
      setTxt('resROI', roi === null ? 'غير متاح' : financialPercent(roi * 100));
      setTxt('resProjectIRR', projectIrr === null ? 'غير متاح' : financialPercent(projectIrr * 100));
      setTxt('resIRR', irrVal === null ? 'غير متاح' : financialPercent(irrVal * 100));
      setHtml('resPayback', payback === null ? '<span>لا يسترد خلال الفترة</span>' : formatFinancialResultNumber(payback, false) + ' <span>سنة</span>');
      setHtml('resEquityPayback', equityPayback === 0 ? '<span>لا يتطلب ضخًا صافياً</span>' : equityPayback === null ? '<span>لا يسترد خلال الفترة</span>' : formatFinancialResultNumber(equityPayback, false) + ' <span>سنة</span>');
      setHtml('resROIScope', roiScope + ' | <span>يشمل التمويل وتكاليف الصندوق</span>');
      setHtml('resProjectIRRScope', irrScope + ' | <span>قبل التمويل وأتعاب الصندوق</span>');
      setHtml('resEquityIRRScope', irrScope + ' | <span>بعد التمويل وأتعاب الصندوق</span>');
      setHtml('scopeROI', roiScope);
      setHtml('scopeProjectIRR', irrScope);
      setHtml('scopeEquityIRR', irrScope);
      setTxt('resTotalOperatingCF', money(totalOperatingCF));
      setTxt('resFinalCF', money(finalCF));

      setVal('financeBaseAmount', money(financeBaseAmount));
      setVal('facilityAmount', money(facilityAmount));
      setVal('arrangementFeeTotal', money(arrangementFee));
      setVal('financeInterestTotal', money(totalFinanceInterest));
      setVal('landEquityContribution', money(landEquityContribution));
      setVal('cashEquityRequired', money(totalCashEquity));
      setVal('equityRequired', money(totalEquityRequired));

      setTxt('resLandEquity', money(landEquityContribution));
      setTxt('resCashEquity', money(totalCashEquity));
      setTxt('resEquityRequired', money(totalEquityRequired));

      setVal('fundManagementFeesTotal', money(totalFundManagementFees));
      setVal('performanceFeeTotal', money(performanceFeeTotal));
      setVal('fundFeesTotal', money(totalFundFees));
      setVal('graceTotalDiscount', money(totalGraceDiscount));

      const areaState = validateComponentAreas();
      if (!areaState.valid && warningBox) { warnings.push('تم حجب اعتماد النتائج والطباعة لأن مجموع المساحات المبنية للمكونات يتجاوز مسطحات البناء فوق الأرض.'); renderAnalysisWarnings(); }

      const tb = document.querySelector('#cashflowTable tbody');
      if (tb) {
        tb.innerHTML = projected.map(r => `<tr>
          <td>${r.year}</td><td>${r.phase}</td><td class="cf-rental">${r.operationYear ? financialPercent(r.occupancyReach * 100) : '—'}</td><td class="cf-sales">${money(r.saleRevenue)}</td><td class="cf-rental">${money(r.operatingRevenue)}</td><td class="cf-grace">${money(r.graceDiscount)}</td>
          <td>${money(r.developmentCost)}</td><td>${money(r.developerPayment)}</td><td class="cf-rental">${money(r.opex)}</td><td>${money(r.landRent)}</td><td class="cf-fund">${money(r.fundFeesAnnual)}</td>
          <td class="cf-finance">${money(r.financeDraw)}</td><td class="cf-finance">${money(r.financeInterest + r.financeFee)}</td><td class="cf-finance">${money(r.financeRepayment)}</td>
          <td class="row-result">${r.final < 0 ? '(' + money(Math.abs(r.final)) + ')' : money(r.final)}</td><td class="row-result">${r.cumulative < 0 ? '(' + money(Math.abs(r.cumulative)) + ')' : money(r.cumulative)}</td><td>${money(r.cashReserve)}</td>
        </tr>`).join('');
      }
      const debtTb = document.querySelector('#debtScheduleTable tbody');
      if (debtTb) debtTb.innerHTML = financeMovementRows(projected, financeOn, financeRepaymentStartYear, financeRepaymentYears).map(r => `<tr><td>${r.year}</td><td>${money(r.openingDebt)}</td><td>${money(r.financeDraw)}</td><td>${money(r.financeInterest)}</td><td>${money(r.financeFee)}</td><td>${money(r.financeRepayment)}</td><td>${money(r.closingDebt)}</td></tr>`).join('');
      const fundTb = document.querySelector('#fundFeeScheduleTable tbody');
      if (fundTb) fundTb.innerHTML = fundFeeScheduleRows(projected, fundFeesOn, fundFeeEndYear).map(r => `<tr><td>${r.year}</td><td>${money(r.fundManagementFee)}</td><td>${money(r.additionalFundFees)}</td><td>${money(r.fundExitFee)}</td><td>${money(r.performanceFee)}</td><td>${money(r.fundFeesAnnual)}</td><td>${reportFieldValue('fundFeeFrequency')}</td><td>${reportFieldValue('fundFeeTiming')}</td></tr>`).join('');

      document.querySelectorAll('#occupancyRampTable tbody tr').forEach((tr, index) => {
        const row = projected.find(r => r.operationYear === index + 1);
        const c = tr.querySelector('.rampRevenue'); if (c) c.textContent = money(row?.operatingRevenue || 0);
        const studyInput = tr.querySelector('[data-field="studyYear"] input'); if (studyInput) studyInput.value = money(developmentYears + index + 1);
      });

      window.__financialProjection = {
        projectCost, projectCostWithFinance, adjustedProjectCost, totalFundFees, totalFundManagementFees, totalAdditionalFundFees, fundExitFeeTotal, performanceFeeTotal, revenueY1, opexY1, noiY1, fullOccupancyRevenue, fullOccupancyOpex, fullOccupancyNOI, terminal, saleExitGross, operatingExitGross, totalExitCosts, saleExitValue, operatingExitValue, saleExitYear, operatingExitYear, roi, roiPeriod, roiEndYear, irrPeriod, irrEndYear, irr: irrVal, projectIrr, payback, equityPayback, totalOperatingCF, finalCF,
        projected, cashflows: equityCashflows, projectCashflows, leasable, developerCost, landRent,
        saleRevenueTotal, saleAreaTotal, facilityAmount, arrangementFee, totalFinanceInterest, totalFinanceCost,
        financeBase, financeBaseAmount, financeDrawYears, financeInterestMethod, financePlan: financePlan.map(({ year, drawPct }) => ({ year, drawPct })),
        financeRepaymentStartYear, financeRepaymentYears, financeRepaymentPlan: financeRepaymentPlan.map(({ year, repaymentPct }) => ({ year, repaymentPct })),
        landEquityContribution, cashEquityRequired: totalCashEquity, equityRequired: totalEquityRequired, totalEquityDistributions, developmentYears, operationYears, totalYears, operationStartYear, salesStartYear, salesYears, totalGraceDiscount, modeFlags, areaState
      };
      applyConditionalVisibility(modeFlags);
      reorderResultCards();
      if (!window.__sensitivityRunning) renderSensitivity();

      // Save complete model data into hidden input for autosave & server sync
      const componentRows = typeof getComponentRowsData === 'function' ? getComponentRowsData() : [];
      const componentData = document.getElementById('projectComponentsData');
      if (componentData) componentData.value = JSON.stringify(componentRows);
      const hidden = document.getElementById('financialCalcData');
      if (hidden) {
        hidden.value = JSON.stringify({
          ...roundFinancialSavedResults({
            projectCost, projectCostWithFinance, adjustedProjectCost, totalFundFees,
            roi, projectIrr, equityIrr: irrVal, payback, equityPayback, totalEquityRequired
          }),
           components: componentRows,
           unitRevenueMode: val('unitRevenueMode'), developmentYears, salesStartYear, salesYears, operationYears, landArea: num('landArea'), coverageRate: num('coverageRate'), floorCount: num('floorCount'), builtUpAreaAbove: num('builtUpAreaAbove'), basementArea: num('basementArea'), landValueMethod: val('landValueMethod'), landPricePerM2: num('landPricePerM2'), manualLandValue: num('manualLandValue'), landStatus: val('landStatus'), landContributionType: val('landContributionType'), landRentMethod: val('landRentMethod'), landRentRate: num('landRentRate'), developerRate: num('developerRate'), developerBase: val('developerBase'), financeEnabled: val('financeEnabled'), financingRate: num('financingRate'), annualFinanceRate: num('annualFinanceRate'), fundEnabled: val('fundEnabled'), fundFeesEnabled: val('fundFeesEnabled'), exitEnabled: val('exitEnabled'), exitMethod: val('exitMethod'), exitInput: num('exitInput'), roiPeriod: val('roiPeriod'), irrPeriod: val('irrPeriod')
         });
       }
       refreshDynamicI18n(document.getElementById('section-financial-calc'));
     }