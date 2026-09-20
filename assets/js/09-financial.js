/* 09-financial.js - index.html lines 15733-17233, shared global scope, classic scripts in order */

    // S3: Components Table
    // The standalone "جدول المكونات والعناصر" section was removed: the financial study already
    // owns a richer components table (use type, units, unit area, built vs revenue area,
    // investment model). Worse, both tables claimed the same DOM id, and duplicate ids make
    // querySelector return only the first — so every financial reader (addComponent,
    // getComponentRowsData, validateComponentAreas) was operating on the wizard table and its
    // mismatched columns. Keeping a single table removes that whole class of bug.

    // S4: Financial Study Model (Extracted from THE-VIEW-Financial-Model-FINAL-v2.html)
    const nf = new Intl.NumberFormat('en-US');
    function roundFinancialResult(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return 0;
      const rounded = Math.sign(number) * Math.round((Math.abs(number) + Number.EPSILON) * 10) / 10;
      return Object.is(rounded, -0) ? 0 : rounded;
    }
    function formatFinancialResultNumber(value, grouped = true) {
      const rounded = roundFinancialResult(value);
      const hasFraction = !Number.isInteger(rounded);
      return new Intl.NumberFormat('en-US', {
        useGrouping: grouped,
        minimumFractionDigits: hasFraction ? 1 : 0,
        maximumFractionDigits: hasFraction ? 1 : 0
      }).format(rounded);
    }
    function money(n) { return formatFinancialResultNumber(n, true) }
    function financialPercent(n) { return formatFinancialResultNumber(n, false) + '%' }
    function rawNum(n) { return Number(n || 0) }
    function parseNumber(value) {
      let cleaned = String(value ?? '').trim();
      cleaned = cleaned.replace(/[٠-٩]/g, ch => String('٠١٢٣٤٥٦٧٨٩'.indexOf(ch)));
      cleaned = cleaned.replace(/[٬،,]/g, '').replace(/٫/g, '.').replace(/\s/g, '');
      const n = Number(cleaned);
      return Number.isFinite(n) ? n : 0;
    }
    function isFinancialNumericControl(el) {
      return !!el && el.tagName === 'INPUT' && (el.type === 'number' || el.classList.contains('numeric-input') || el.inputMode === 'decimal');
    }
    function financialInputNumber(value, fallback = 0) {
      if (value == null || String(value).trim() === '') return fallback;
      return parseNumber(value);
    }
    const FINANCIAL_SAVED_RATIO_KEYS = new Set(['roi', 'projectIrr', 'irr', 'equityIrr', 'occupancyReach']);
    const FINANCIAL_SAVED_EXACT_KEYS = new Set([
      'year', 'startYear', 'endYear', 'studyYear', 'operationYear', 'developmentYears',
      'operationYears', 'totalYears', 'salesStartYear', 'salesYears', 'saleExitYear',
      'operatingExitYear', 'financeDrawYears', 'financeRepaymentStartYear',
      'financeRepaymentYears', 'floorCount', 'units'
    ]);
    function roundFinancialSavedResults(value, key = '') {
      if (Array.isArray(value)) return value.map(item => roundFinancialSavedResults(item, key));
      if (value && typeof value === 'object') {
        return Object.fromEntries(Object.entries(value).map(([childKey, childValue]) => [
          childKey, roundFinancialSavedResults(childValue, childKey)
        ]));
      }
      if (typeof value !== 'number' || !Number.isFinite(value) || FINANCIAL_SAVED_EXACT_KEYS.has(key)) return value;
      if (FINANCIAL_SAVED_RATIO_KEYS.has(key)) return roundFinancialResult(value * 100) / 100;
      return roundFinancialResult(value);
    }
    function financialControlContext(control) {
      const cell = control?.closest('td,th');
      const header = cell && cell.cellIndex >= 0 ? cell.closest('table')?.querySelector('thead tr')?.cells[cell.cellIndex]?.textContent : '';
      const label = control?.closest('div')?.querySelector(':scope > label')?.textContent || '';
      return [control?.id, control?.dataset?.field, header, label].filter(Boolean).join(' ');
    }
    function formatFinancialReportValue(value, context = '') {
      const raw = String(value ?? '').trim();
      const contextText = String(context || '');
      if (/تاريخ|هاتف|جوال|وثيقة|معرف|رقم|date|phone|mobile|document|identifier|\bid\b/i.test(contextText)) return raw;
      const match = raw.match(/^(\()?\s*([-+]?(?:[0-9٠-٩]+(?:[٬،,][0-9٠-٩]{3})*|[0-9٠-٩]+)(?:[٫.][0-9٠-٩]+)?)\s*(\))?\s*(%|٪|سنة|سنوات|م²|م2|ر\.?\s?س|ريال(?:\s+سعودي)?)?$/);
      if (match) {
        const number = parseNumber(match[2]);
        const suffix = match[4] || '';
        const amount = /إجمالي|تكلفة|قيمة|مساحة|سعر|إيراد|مصروف|كمية|مبلغ|تدفق|رصيد|حقوق|أتعاب|أصل|دين|سيولة|استثمار|دخل|NOI|total|amount|cost|price|revenue|area|cash|balance/i.test(contextText);
        const percent = suffix === '%' || suffix === '٪' || (!amount && /%|نسبة|معدل|إشغال|ROI|IRR/i.test(contextText));
        const year = suffix === 'سنة' || suffix === 'سنوات' || (!amount && /سنة|سنوات|عام|year/i.test(contextText));
        let formatted = formatFinancialResultNumber(number, !(percent || year));
        if (match[1] && match[3]) formatted = '(' + formatted.replace(/^-/, '') + ')';
        if (suffix) formatted += (suffix === '%' || suffix === '٪' ? '' : ' ') + suffix;
        return formatted;
      }
      if (!/إجمالي|تكلفة|قيمة|مساحة|سعر|إيراد|مصروف|تمويل|كمية|مبلغ|تدفق|رصيد|حقوق|أتعاب|أصل|دين|سيولة|استثمار|دخل|NOI|total|amount|cost|price|revenue|area|cash|balance/i.test(contextText + ' ' + raw)) return raw;
      return raw.replace(/(?<![0-9٠-٩])[-+]?(?:[0-9٠-٩]+(?:[٬،,][0-9٠-٩]{3})*)(?:[٫.][0-9٠-٩]+)?(?![0-9٠-٩])/g, (token, offset) => {
        const number = parseNumber(token);
        if (number >= 1900 && number <= 2100 && /سنة|سنوات|عام|year/i.test(contextText)) return token;
        const trailing = raw.slice(offset + token.length).trimStart();
        return formatFinancialResultNumber(number, !trailing.startsWith('%') && !trailing.startsWith('٪'));
      });
    }
    function num(id) { return parseNumber(document.getElementById(id)?.value) }
    function val(id) { return document.getElementById(id)?.value || '' }
    function reportFieldValue(id) {
      const el = document.getElementById(id);
      if (!el) return '—';
      if (el.tagName === 'SELECT') return el.selectedOptions?.[0]?.textContent?.trim() || '—';
      const value = String(el.value ?? '').trim();
      if (!value) return '—';
      return isFinancialNumericControl(el) ? formatFinancialReportValue(value, financialControlContext(el)) : value;
    }
    function escapeReportHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
    }
    function reportMetricValue(id) {
      const el = document.getElementById(id);
      return el?.textContent?.trim() || el?.value?.trim() || '—';
    }
    function reportValueIsZero(value) { const text = String(value ?? '').replace(/,/g, '').trim(); const numeric = text.replace(/[^0-9.\-]/g, ''); return numeric !== '' && Number(numeric) === 0 }
    function reportRows(items) {
      const visible = items.filter(([, value]) => !reportValueIsZero(value));
      return visible.length ? `<table class="summary-table"><tbody>${visible.map(([label, value]) => `<tr><th>${escapeReportHtml(label)}</th><td>${escapeReportHtml(value)}</td></tr>`).join('')}</tbody></table>` : '<p class="empty">لا توجد قيم مطبقة في هذا القسم.</p>';
    }
    function reportTableSnapshot(tableId, dropLastColumn = true, removeZeroRows = false) {
      const source = document.getElementById(tableId);
      if (!source || !source.querySelector('tbody tr')) return '<p class="empty">لا توجد بنود مدخلة في هذا الجدول.</p>';
      const table = source.cloneNode(true);
      table.removeAttribute('id');
      table.querySelectorAll('tr.hidden').forEach(row => row.remove());
      table.querySelectorAll('.conditional-off').forEach(node => node.remove());
      table.querySelectorAll('input').forEach(input => {
        const span = document.createElement('span');
        const value = input.value?.trim() || '';
        span.textContent = value
          ? (isFinancialNumericControl(input) ? formatFinancialReportValue(value, financialControlContext(input)) : value)
          : '—';
        input.replaceWith(span);
      });
      table.querySelectorAll('select').forEach(select => {
        const span = document.createElement('span');
        span.textContent = select.selectedOptions?.[0]?.textContent?.trim() || '—';
        select.replaceWith(span);
      });
      table.querySelectorAll('button,.help,.custom-formula-row,.row-actions').forEach(node => node.remove());
      table.querySelectorAll('.off-cell').forEach(cell => { if (!cell.textContent.trim()) cell.textContent = '—' });
      table.querySelectorAll('tbody td,tfoot td').forEach(cell => {
        const header = cell.closest('table')?.querySelector('thead tr')?.cells[cell.cellIndex]?.textContent || '';
        cell.textContent = formatFinancialReportValue(cell.textContent, header);
      });
      const dropIndexes = new Set();
      table.querySelectorAll('thead th').forEach((th, idx) => {
        const text = String(th.textContent || '').replace(/\s+/g, ' ').trim();
        if (text === 'ترتيب / حذف' || text === 'حذف' || text === 'ترتيب' || text === 'مرتبط بمكون') dropIndexes.add(idx);
      });
      if (!dropIndexes.size && dropLastColumn && table.querySelector('thead tr')?.cells.length) {
        dropIndexes.add(table.querySelector('thead tr').cells.length - 1);
      }
      [...dropIndexes].sort((a, b) => b - a).forEach(idx => {
        table.querySelectorAll('tr').forEach(row => { if (row.cells[idx]) row.deleteCell(idx); });
      });
      if (removeZeroRows) table.querySelectorAll('tbody tr').forEach(row => { const last = row.cells[row.cells.length - 1]; if (last && reportValueIsZero(last.textContent)) row.remove() });
      table.querySelectorAll('[style]').forEach(node => node.removeAttribute('style'));
      return table.outerHTML;
    }
    function lines(id) { return val(id).split('\n').map(x => x.trim()).filter(Boolean) }
    function rowActionsHtml() { return `<div class="row-actions"><button type="button" class="btn ghost small" onclick="moveRow(this,-1)" title="تحريك لأعلى">أعلى</button><button type="button" class="btn ghost small" onclick="moveRow(this,1)" title="تحريك لأسفل">أسفل</button><button type="button" class="btn danger small" onclick="this.closest('tr').remove();calculateAll()">حذف</button></div>` }
    function moveRow(button, direction) { const row = button.closest('tr'), body = row?.parentElement; if (!row || !body) return; const target = direction < 0 ? row.previousElementSibling : row.nextElementSibling; if (!target) return; if (direction < 0) body.insertBefore(row, target); else body.insertBefore(target, row); updateRevenueComponentOptions(); calculateAll() }
    function autoSizeField(input) { if (!input?.closest('.table-wrap')) return; const length = Math.max(10, String(input.value || input.placeholder || '').length); input.style.width = Math.min(320, Math.max(145, length * 9 + 34)) + 'px' }
    function numericInputUsesGrouping(input) {
      const label = input?.closest('div,td')?.querySelector('label')?.textContent || '';
      const identity = [input?.id, input?.dataset?.field, input?.dataset?.key, label].filter(Boolean).join(' ');
      return !/(year|date|phone|mobile|deed|plot|lat|lng|longitude|latitude|pct|percent|rate|ratio|سنة|سنوات|تاريخ|هاتف|جوال|صك|مخطط|قطعة|إحداث)/i.test(identity);
    }
    function formatNumericInput(input) { const raw = String(input.value || '').replace(/[٬،,]/g, '').replace(/٫/g, '.').trim(); const n = parseNumber(raw); const decimals = raw.includes('.') ? raw.split('.')[1].length : 0; input.value = raw === '' ? '' : (numericInputUsesGrouping(input) ? new Intl.NumberFormat('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(n) : raw); autoSizeField(input) }
    function enhanceNumericInputs(root = document) { root.querySelectorAll('input[type="number"],input.numeric-input').forEach(input => { if (input.dataset.numericReady) { formatNumericInput(input); return } input.type = 'text'; input.inputMode = 'decimal'; input.classList.add('numeric-input'); input.dataset.numericReady = '1'; input.addEventListener('focus', () => { if (numericInputUsesGrouping(input)) input.value = String(input.value || '').replace(/,/g, ''); autoSizeField(input) }); input.addEventListener('blur', () => formatNumericInput(input)); input.addEventListener('input', () => autoSizeField(input)); formatNumericInput(input) }); root.querySelectorAll('.table-wrap input:not(.numeric-input)').forEach(autoSizeField) }
    function selectHtml(options, selected) { return options.map(o => `<option value="${o.v}" ${selected === o.v ? 'selected' : ''}>${o.t}</option>`).join('') }

    const useTypes = [{ v: 'retail', t: 'تجاري / تجزئة' }, { v: 'entertainment', t: 'ترفيهي' }, { v: 'services', t: 'خدمات ومرافق' }, { v: 'parking', t: 'مواقف' }, { v: 'residential', t: 'سكني' }, { v: 'hospitality', t: 'فندقي' }, { v: 'industrial', t: 'صناعي' }, { v: 'logistics', t: 'لوجستي' }, { v: 'office', t: 'مكاتب' }, { v: 'other', t: 'أخرى' }];
    const investmentModels = [{ v: 'sale', t: 'بيع وحدات' }, { v: 'dailyRent', t: 'إيجار يومي' }, { v: 'monthlyRent', t: 'إيجار شهري' }, { v: 'annualRent', t: 'إيجار سنوي' }, { v: 'operating', t: 'تأجير آخر' }, { v: 'nonRevenue', t: 'بدون إيراد' }];
    const revenueMethods = [{ v: 'areaSale', t: 'بيع مساحة × سعر متر' }, { v: 'dailyRent', t: 'وحدات × سعر يومي × 365 × إشغال' }, { v: 'monthlyAreaRent', t: 'مساحة × إيجار متر شهري × 12 × إشغال' }, { v: 'monthlyUnitRent', t: 'وحدات × إيجار شهري × 12 × إشغال' }, { v: 'areaRent', t: 'مساحة × إيجار متر سنوي × إشغال' }, { v: 'unitRent', t: 'وحدات × إيجار سنوي × إشغال' }, { v: 'weeklyUnit', t: 'وحدات × سعر أسبوعي × أسابيع × تشغيل' }, { v: 'tickets', t: 'زوار × سعر تذكرة' }, { v: 'commission', t: 'قيمة عمليات × عمولة %' }, { v: 'subscription', t: 'مشتركين × اشتراك' }, { v: 'fixed', t: 'قيمة ثابتة سنوية' }, { v: 'percentRevenue', t: 'نسبة من الإيرادات' }, { v: 'custom', t: 'فورمولا مخصصة' }];
    const costMethods = [{ v: 'areaCost', t: 'مساحة × تكلفة متر' }, { v: 'unitCost', t: 'عدد × تكلفة وحدة' }, { v: 'fixed', t: 'قيمة ثابتة' }, { v: 'percentExecution', t: 'نسبة من تكلفة التنفيذ' }, { v: 'monthlyDuration', t: 'تكلفة شهرية × مدة' }, { v: 'percentRevenue', t: 'نسبة من الإيرادات' }, { v: 'custom', t: 'فورمولا مخصصة' }];
    const costClasses = [{ v: 'execution', t: 'تنفيذ' }, { v: 'design', t: 'تصميم ودراسات' }, { v: 'services', t: 'رسوم خدمات' }, { v: 'advertising', t: 'دعاية وإعلان' }, { v: 'operationSetup', t: 'تجهيزات تشغيلية' }, { v: 'external', t: 'خارجي' }];
    const opexMethods = [{ v: 'monthlyFixed', t: 'مصروف شهري ثابت' }, { v: 'percentRevenue', t: 'نسبة من الإيرادات' }, { v: 'staffSalary', t: 'عدد موظفين × راتب' }, { v: 'annualFixed', t: 'قيمة سنوية ثابتة' }, { v: 'perUnit', t: 'تكلفة لكل وحدة' }, { v: 'perM2', t: 'تكلفة لكل متر' }, { v: 'custom', t: 'فورمولا مخصصة' }];
    const externalTypes = [{ v: 'revenue', t: 'إيراد' }, { v: 'cost', t: 'تكلفة' }, { v: 'opex', t: 'مصروف' }, { v: 'asset', t: 'أصل' }, { v: 'tax', t: 'ضريبة' }];
    const externalMethods = [{ v: 'fixed', t: 'قيمة ثابتة' }, { v: 'qtyPrice', t: 'كمية × سعر' }, { v: 'areaPrice', t: 'مساحة × سعر متر' }, { v: 'percentRevenue', t: 'نسبة من الإيرادات' }, { v: 'percentCost', t: 'نسبة من التكلفة' }, { v: 'recurring', t: 'قيمة متكررة سنويًا' }, { v: 'custom', t: 'فورمولا مخصصة' }];
    const fundAdditionalFeeMethods = [{ v: 'fixed', t: 'مبلغ ثابت' }, { v: 'percentFundCapital', t: 'نسبة من رأس مال الصندوق' }, { v: 'percentProjectCost', t: 'نسبة من تكلفة المشروع' }, { v: 'percentExit', t: 'نسبة من قيمة التخارج' }, { v: 'percentProfit', t: 'نسبة من الأرباح' }];

    function addFinancialCalculations(form) {
      const div = document.createElement('div');
      div.className = 'tenant-form-section';
      div.id = 'section-financial-calc';
      div.dataset.section = 'section-financial-calc';
      div.innerHTML = `
        <h3 class="tenant-section-title">الدراسة المالية والمؤشرات</h3>
        <p class="hint">نموذج موحد يجمع مكونات المشروع والوحدات البيعية والوحدات المؤجرة يوميًا وشهريًا وسنويًا، ويوزع التكاليف والمبيعات والتمويل على سنوات المشروع تلقائيًا.</p>

        <div class="finance-block" id="unitNatureBlock">
          <h3>1. طبيعة وحدات المشروع</h3>
          <div class="grid four"><div><label>هل وحدات المشروع بيعية أم تأجيرية؟</label><select id="unitRevenueMode" onchange="calculateAll()"><option value="mixed">مختلطة: بيعية وتأجيرية</option><option value="sale">بيعية فقط</option><option value="rental">تأجيرية فقط</option><option value="nonRevenue">بدون إيراد</option></select><span class="help input">يحدد حقول البيع أو التأجير التي تظهر في الدراسة والتقرير.</span></div></div>
        </div>

        <div class="finance-block">
          <h3>2. مدة المشروع والأرض ومساحات البناء</h3>
          <div class="grid four">
            <div><label>مدة تطوير المشروع (سنة)</label><input id="developmentYears" type="number" min="1" value="" readonly class="readonly-highlight"><span class="help formula">مأخوذة من «عدد السنوات» في قسم الجدول الزمني — عدّلها من هناك.</span></div>
            <div id="salesStartYearWrap"><label>سنة بدء بيع الوحدات</label><input id="salesStartYear" type="number" min="1" oninput="calculateAll()"><span class="help input">يظهر للمشروع البيعي أو المختلط.</span></div>
            <div id="salesYearsWrap"><label>عدد سنوات بيع الوحدات</label><input id="salesYears" type="number" min="1" oninput="calculateAll()"><span class="help input">توزع المبيعات على هذه السنوات.</span></div>
            <div id="operationYearsWrap"><label>عدد سنوات التشغيل</label><input id="operationYears" type="number" min="1" oninput="calculateAll()"><span class="help input">يظهر للمشروع التأجيري أو المختلط.</span></div>
            <div id="operationStartYearWrap"><label>سنة بدء التشغيل</label><input id="operationStartYear" readonly><span class="help formula">مدة التطوير + 1.</span></div>
            <div><label>إجمالي سنوات المشروع</label><input id="totalProjectYearsDisplay" readonly><span class="help formula">مدة التطوير + مدة التشغيل.</span></div>

            <div><label>مساحة الأرض م²</label><input id="landArea" type="number" value="" readonly class="readonly-highlight"><span class="help formula">مأخوذة من «المساحة المعتمدة للدراسة المالية» في قسم الأرض والكروكي — عدّلها من هناك.</span></div>
            <div><label>نسبة التغطية %</label><input id="coverageRate" type="number" value="" readonly class="readonly-highlight"><span class="help formula">مأخوذة من «التغطية المعتمدة» في قسم الأرض والكروكي — عدّلها من هناك.</span></div>
            <div><label>عدد الطوابق</label><input id="floorCount" type="number" min="1" value="" readonly class="readonly-highlight"><span class="help formula">مأخوذة من «الأدوار المعتمدة» في قسم الأرض والكروكي — عدّلها من هناك.</span></div>
            <div><label>مسطحات البناء فوق الأرض م²</label><input id="builtUpAreaAbove" type="number" oninput="calculateAll()"><span class="help input">إجمالي مسطحات الأدوار فوق الأرض.</span></div>
            <div><label>مساحة البدرومات م²</label><input id="basementArea" type="number" oninput="calculateAll()"><span class="help input">إجمالي مسطحات البدرومات.</span></div>

            <div><label>إجمالي مسطحات البناء م²</label><input id="totalBuiltUpArea" readonly><span class="help formula">فوق الأرض + البدرومات.</span></div>
            <div><label>المساحة المغطاة م²</label><input id="coveredArea" readonly><span class="help formula">مساحة الأرض × نسبة التغطية.</span></div>
            <div><label>المساحات المفتوحة م²</label><input id="openArea" readonly><span class="help formula">مساحة الأرض - المساحة المغطاة.</span></div>

            <div><label>طريقة احتساب قيمة الأرض</label><select id="landValueMethod" onchange="calculateAll()">
              <option value="none">لا توجد قيمة أرض</option>
              <option value="manual">قيمة ثابتة يدوية</option>
              <option value="perM2" selected>مساحة الأرض × سعر متر الأرض</option>
            </select></div>
            <div id="landPricePerM2Wrap"><label>سعر متر الأرض</label><input id="landPricePerM2" type="number" oninput="calculateAll()"></div>
            <div id="manualLandValueWrap"><label>قيمة الأرض اليدوية</label><input id="manualLandValue" type="number" oninput="calculateAll()"></div>
            <div><label>حالة الأرض</label><select id="landStatus" onchange="calculateAll()">
              <option value="ownedIncluded">مملوكة وتدخل ضمن تكلفة المشروع</option>
              <option value="ownedInfoOnly">مملوكة وتظهر كمعلومة فقط</option>
              <option value="leased" selected>مستأجرة ولا تدخل ضمن تكلفة المشروع</option>
              <option value="usufruct">حق انتفاع</option>
              <option value="notCounted">غير محتسبة</option>
            </select></div>
            <div><label>معالجة الأرض في التدفقات</label><select id="landContributionType" onchange="calculateAll()">
              <option value="inKind">مساهمة عينية ضمن حقوق الملكية</option>
              <option value="cash">شراء نقدي للأرض</option>
              <option value="none">لا تظهر في التدفقات</option>
            </select><span class="help input">المساهمة العينية تدخل في Project IRR وEquity IRR دون اعتبارها ضخًا نقديًا.</span></div>
            <div><label>سنة تسجيل الأرض</label><input id="landContributionYear" type="number" min="1" oninput="calculateAll()"></div>

            <div><label>طريقة احتساب إيجار الأرض</label><select id="landRentMethod" onchange="calculateAll()">
              <option value="none">لا يوجد إيجار أرض</option>
              <option value="annualFixed">قيمة سنوية ثابتة</option>
              <option value="percentLandValue" selected>نسبة من قيمة الأرض</option>
              <option value="monthlyFixed">قيمة شهرية × 12</option>
            </select></div>
            <div id="landRentRateWrap"><label>نسبة إيجار الأرض السنوي %</label><input id="landRentRate" type="number" oninput="calculateAll()"></div>
            <div id="manualAnnualLandRentWrap"><label>إيجار الأرض السنوي</label><input id="manualAnnualLandRent" type="number" oninput="calculateAll()"></div>
            <div id="monthlyLandRentWrap"><label>إيجار الأرض الشهري</label><input id="monthlyLandRent" type="number" oninput="calculateAll()"></div>
            <div><label>قيمة الأرض المحسوبة</label><input id="landValue" readonly></div>
            <div><label>إيجار الأرض السنوي المحسوب</label><input id="annualLandRent" readonly></div>
          </div>
        </div>

        <div class="finance-block">
          <h3>3. مكونات المشروع</h3>
          <div id="componentsAllowedUsesNote" class="tenant-hint" style="margin:0 0 10px;font-weight:700;line-height:1.7" hidden></div>
          <div class="table-wrap">
            <table id="componentsTable">
              <thead><tr><th>اسم المكون</th><th>نوع الاستخدام</th><th>عدد الوحدات</th><th>مساحة الوحدة م²</th><th>المساحة المبنية م²</th><th>المساحة البيعية / التأجيرية م²</th><th>نموذج الاستفادة</th><th>الناتج</th><th>ترتيب / حذف</th></tr></thead>
              <tbody></tbody>
            </table>
          </div>
          <br><button type="button" class="btn ghost" onclick="addComponent()">+ إضافة مكون</button>
          <p class="help formula">المساحة المبنية هي المساحة الفعلية المخصصة للمكون، أما المساحة البيعية/التأجيرية فهي الجزء الذي يحقق الإيراد. عند إضافة مكون جديد يقترح النموذج عدد الوحدات × مساحة الوحدة، ويمكن تعديل المساحتين يدويًا.</p>
          <div id="componentAreaValidation" class="validation-panel"><span id="componentBuiltAreaTotal">0</span> م² مخصصة من أصل <span id="componentBuiltAreaLimit">0</span> م² — المتبقي <span id="componentBuiltAreaRemaining">0</span> م².</div>
        </div>

        <div class="finance-block">
          <h3>4. بنود الإيرادات</h3>
          <span class="formula-tag">لكل إيراد إشغال مستهدف، ويطبق عليه تدرج الوصول السنوي الموضح أسفل الجدول</span>
          <div class="table-wrap">
            <table id="revenueTable">
              <thead><tr><th>اسم الإيراد</th><th>مرتبط بمكون</th><th>مصدر الكمية</th><th>طريقة الحساب</th><th>الكمية / المساحة</th><th>السعر</th><th>الفترة</th><th>الإشغال السنوي المستهدف %</th><th>الإيراد السنوي عند المستهدف</th><th>ترتيب / حذف</th></tr></thead>
              <tbody></tbody>
            </table>
          </div>
          <br><button type="button" class="btn ghost" onclick="addRevenue()">+ إضافة إيراد</button>
          <p class="help formula">الإشغال هنا هو الإشغال السنوي المستهدف لكل إيراد. وفي التدفقات يُضرب في نسبة الوصول السنوية إلى المستهدف.</p>
          <div id="rentalRevenueDetails"><h4>نسبة الوصول السنوية إلى الإشغال المستهدف</h4>
          <div class="table-wrap"><table id="occupancyRampTable" class="compact-table"><thead><tr><th>سنة التشغيل</th><th>السنة في الدراسة</th><th>نسبة الوصول إلى المستهدف %</th><th>إيرادات التشغيل المحسوبة</th></tr></thead><tbody></tbody></table></div>
          <p class="calculation-note">الإشغال الفعلي لكل إيراد = إشغاله المستهدف × نسبة الوصول في سنة التشغيل.</p></div>
        </div>

        <div class="finance-block" id="graceBlock">
          <h3>5. فترة السماح للمستأجرين</h3>
          <div class="section-switch"><label>تطبيق فترة سماح؟</label><select id="graceEnabled" onchange="calculateAll()"><option value="no">لا</option><option value="yes">نعم</option></select></div>
          <div id="graceDetails" class="grid four">
            <div><label>طريقة احتساب السماح</label><select id="graceMethod" onchange="calculateAll()"><option value="percentage">نسبة ومدة بالأشهر</option><option value="schedule">جدول خصومات سنوية ثابتة</option></select></div>
            <div><label>نطاق فترة السماح</label><select id="graceScope" onchange="calculateAll()"><option value="allRental">جميع الإيرادات التأجيرية</option><option value="selectedRevenue">إيراد محدد</option></select></div>
            <div id="graceRevenueWrap"><label>الإيراد المشمول</label><select id="graceRevenueId" onchange="calculateAll()"></select></div>
            <div><label>سنة بداية السماح</label><input id="graceStartYear" type="number" min="1" oninput="calculateAll()"></div>
            <div><label>مدة السماح (شهر)</label><input id="graceDurationMonths" type="number" min="0" oninput="calculateAll()"></div>
            <div><label>نسبة الخصم خلال السماح %</label><input id="graceDiscountRate" type="number" min="0" max="100" oninput="calculateAll()"></div>
            <div><label>إجمالي خصم فترة السماح</label><input id="graceTotalDiscount" readonly></div>
          </div>
          <div id="graceScheduleWrap"><h4>جدول خصومات فترة السماح</h4><div class="table-wrap"><table id="graceScheduleTable" class="compact-table"><thead><tr><th>السنة في الدراسة</th><th>قيمة الخصم</th><th>ترتيب / حذف</th></tr></thead><tbody></tbody></table></div><br><button type="button" class="btn ghost" onclick="addGraceScheduleRow()">+ إضافة سنة سماح</button></div>
          <p class="help formula">الخصم السنوي يُخصم من الإيراد ولا يسجل كمصروف.</p>
        </div>

        <div class="finance-block">
          <h3>6. تكاليف المشروع وأتعاب المطور</h3>
          <div class="grid four">
            <div><label>نسبة المطور %</label><input id="developerRate" type="number" oninput="calculateAll()"></div>
            <div><label>أساس احتساب نسبة المطور</label><select id="developerBase" onchange="calculateAll()">
              <option value="executionOnly" selected>تكلفة التنفيذ فقط</option>
              <option value="executionServices">التنفيذ + رسوم الخدمات</option>
              <option value="executionDesignServices">التنفيذ + التصميم + الخدمات</option>
              <option value="projectNoLand">تكلفة المشروع بدون الأرض</option>
              <option value="projectWithLand">تكلفة المشروع شامل الأرض</option>
            </select></div>
            <div><label>قيمة أساس المطور</label><input id="developerBaseAmount" readonly></div>
            <div><label>إجمالي أتعاب المطور</label><input id="developerCostValue" readonly></div>
            <div><label>إجمالي تكلفة التنفيذ</label><input id="executionCostTotal" readonly></div>
            <div><label>التصميم والدراسات</label><input id="designCostTotal" readonly></div>
            <div><label>رسوم الخدمات</label><input id="servicesCostTotal" readonly></div>
            <div><label>الدعاية والإعلان</label><input id="advertisingCostTotal" readonly></div>
            <div><label>قيمة الأرض داخل التكلفة</label><input id="landCostIncluded" readonly></div>
            <div><label>إيجار الأرض السنوي</label><input id="landRentSummary" readonly></div>
          </div>
          <br>
          <div class="table-wrap"><table id="costTable"><thead><tr><th>اسم التكلفة</th><th>التصنيف</th><th>طريقة الحساب</th><th>الكمية / المساحة</th><th>السعر / النسبة</th><th>المدة</th><th>الناتج</th><th>ترتيب / حذف</th></tr></thead><tbody></tbody></table></div>
          <br><button type="button" class="btn ghost" onclick="addCost()">+ إضافة تكلفة</button>
        </div>

        <div class="finance-block">
          <h3>7. مراحل التطوير ودفعات المطور</h3>
          <div class="section-switch"><label>هل توجد مراحل تطوير ودفعات للمطور؟</label><select id="developerPaymentsEnabled" onchange="calculateAll()"><option value="no" selected>لا</option><option value="yes">نعم</option></select></div>
          <div id="developerPaymentsDetails">
            <p class="hint">المراحل وسنواتها تُعدّل من قسم الجدول الزمني. النسبتان فقط تُدخلان هنا، وتُوزَّع دفعة المطور على كل سنوات المرحلة في التدفقات.</p>
            <div id="timelineStagesWarning" class="validation-panel error" hidden>لا توجد مراحل في الجدول الزمني بعد، فلن تُوزَّع تكاليف التطوير على السنوات.</div>
            <div id="scheduleTotalsNote" class="calculation-note" hidden></div>
            <div class="table-wrap">
              <table id="scheduleTable">
                <thead><tr><th>المرحلة</th><th>نسبة تكلفة التطوير %</th><th>نسبة دفعة المطور %</th><th>قيمة تكلفة المرحلة</th><th>قيمة دفعة المطور</th></tr></thead>
                <tbody></tbody>
                <tfoot><tr><th>الإجمالي</th><th id="scheduleCostPctTotal">0%</th><th id="scheduleDevPctTotal">0%</th><th id="scheduleCostTotalValue">0</th><th id="scheduleDevTotalValue">0</th></tr></tfoot>
              </table>
            </div>
          </div>
        </div>

        <div class="finance-block">
          <h3>8. المصروفات التشغيلية</h3>
          <div class="table-wrap"><table id="opexTable"><thead><tr><th>اسم المصروف</th><th>طريقة الحساب</th><th>القيمة / الكمية</th><th>السعر / النسبة</th><th>الناتج السنوي</th><th>ترتيب / حذف</th></tr></thead><tbody></tbody></table></div>
          <br><button type="button" class="btn ghost" onclick="addOpex()">+ إضافة مصروف</button>
        </div>

        <div class="finance-block" id="financeBlock">
          <h3>9. التمويل</h3>
          <div class="grid four">
            <div><label>استخدام تمويل؟</label><select id="financeEnabled" onchange="calculateAll()"><option value="yes">نعم</option><option value="no">لا</option></select></div>
            <div><label>أساس احتساب التمويل</label><select id="financeBase" onchange="calculateAll()"><option value="withLand">إجمالي تكلفة المشروع مع قيمة الأرض</option><option value="withoutLand">إجمالي تكلفة المشروع بدون قيمة الأرض</option></select></div>
            <div><label>نسبة التمويل من تكلفة المشروع %</label><input id="financingRate" type="number" oninput="calculateAll()"></div>
            <div><label>رسوم ترتيب التمويل %</label><input id="financeArrangementFeeRate" type="number" oninput="calculateAll()"></div>
            <div><label>طريقة احتساب الفائدة</label><select id="financeInterestMethod" onchange="calculateAll()"><option value="fixed">ثابتة على أصل التسهيل</option><option value="declining">متناقصة على الرصيد المتبقي</option></select></div>
            <div><label>معدل الفائدة السنوي %</label><input id="annualFinanceRate" type="number" oninput="calculateAll()"></div>
            <div><label>عدد سنوات سحب التمويل</label><input id="financeDrawYears" type="number" min="1" oninput="syncFinanceDrawPlan();calculateAll()"></div>
            <div><label>سنة بدء سداد التمويل</label><input id="financeRepaymentStartYear" type="number" min="1" oninput="syncFinanceRepaymentPlan();calculateAll()"></div>
            <div><label>عدد سنوات التمويل والسداد</label><input id="financeRepaymentYears" type="number" min="1" oninput="syncFinanceRepaymentPlan();calculateAll()"></div>
            <div><label>قيمة أساس التمويل</label><input id="financeBaseAmount" readonly></div>
            <div><label>قيمة التسهيل التمويلي</label><input id="facilityAmount" readonly></div>
            <div><label>رسوم ترتيب التمويل</label><input id="arrangementFeeTotal" readonly></div>
            <div><label>إجمالي فوائد التمويل</label><input id="financeInterestTotal" readonly></div>
            <div><label>مساهمة الأرض العينية</label><input id="landEquityContribution" readonly></div>
            <div><label>الضخ النقدي المطلوب</label><input id="cashEquityRequired" readonly></div>
            <div><label>إجمالي حقوق الملكية</label><input id="equityRequired" readonly></div>
          </div>
          <br>
          <h4>خطة سحب التمويل</h4>
          <div class="table-wrap"><table id="financeDrawTable"><thead><tr><th>سنة السحب</th><th>نسبة السحب من التسهيل %</th><th>قيمة السحب المحسوبة</th></tr></thead><tbody></tbody></table></div>
          <h4>خطة سداد أصل التمويل</h4>
          <div class="table-wrap"><table id="financeRepaymentTable"><thead><tr><th>سنة السداد</th><th>نسبة السداد من أصل التسهيل %</th><th>قيمة السداد المحسوبة</th></tr></thead><tbody></tbody></table></div>
          <h4>حركة رصيد التمويل السنوية</h4>
          <div class="table-wrap"><table id="debtScheduleTable"><thead><tr><th>السنة</th><th>الرصيد الافتتاحي</th><th>السحب</th><th>الفائدة</th><th>رسوم التمويل</th><th>سداد أصل التمويل</th><th>الرصيد الختامي</th></tr></thead><tbody></tbody></table></div>
        </div>

        <div class="finance-block" id="fundBlock">
          <h3>10. الصندوق وأتعاب إدارة الصندوق</h3>
          <div class="grid four" id="fundMainGrid">
            <div><label>وجود صندوق للمشروع؟</label><select id="fundEnabled" onchange="calculateAll()"><option value="no">لا</option><option value="yes">نعم</option></select></div>
            <div><label>تطبيق أتعاب إدارة الصندوق</label><select id="fundFeesEnabled" onchange="calculateAll()"><option value="yes">نعم</option><option value="no">لا</option></select></div>
            <div><label>أساس احتساب الأتعاب</label><select id="fundFeeBase" onchange="calculateAll()"><option value="fundCapital">رأس مال الصندوق</option><option value="investedCapital">رأس المال المستثمر فعليًا</option><option value="nav">صافي قيمة الأصول</option><option value="projectCost">إجمالي تكلفة المشروع</option><option value="fixed">مبلغ ثابت</option></select></div>
            <div id="fundCapitalInputWrap"><label>رأس مال الصندوق</label><input id="fundCapitalInput" type="number" oninput="calculateAll()"></div>
            <div id="fundNavInputWrap"><label>صافي قيمة الأصول NAV</label><input id="fundNavInput" type="number" oninput="calculateAll()"></div>
            <div id="fundManagementRateWrap"><label>نسبة أتعاب الإدارة السنوية %</label><input id="fundManagementRate" type="number" oninput="calculateAll()"></div>
            <div id="fundFixedAnnualFeeWrap"><label>مبلغ الأتعاب السنوي الثابت</label><input id="fundFixedAnnualFee" type="number" oninput="calculateAll()"></div>
            <div><label>سنة بداية الاحتساب</label><input id="fundFeeStartYear" type="number" min="1" step="0.25" oninput="calculateAll()"></div>
            <div><label>سنة نهاية الاحتساب</label><input id="fundFeeEndYear" type="number" min="1" step="0.25" oninput="calculateAll()"></div>
            <div><label>دورية السداد</label><select id="fundFeeFrequency" onchange="calculateAll()"><option value="monthly">شهري</option><option value="quarterly">ربع سنوي</option><option value="semiannual">نصف سنوي</option><option value="annual">سنوي</option></select></div>
            <div><label>توقيت السداد</label><select id="fundFeeTiming" onchange="calculateAll()"><option value="beginning">بداية الفترة</option><option value="end">نهاية الفترة</option></select></div>
            <div><label>نسبة الزيادة السنوية في الأتعاب %</label><input id="fundFeeGrowthRate" type="number" oninput="calculateAll()"></div>
            <div><label>إجمالي أتعاب الإدارة المحسوبة</label><input id="fundManagementFeesTotal" readonly></div>
          </div>
          <h4>الأتعاب الإضافية الاختيارية</h4>
          <div class="table-wrap"><table id="fundAdditionalFeesTable"><thead><tr><th>اسم الأتعاب</th><th>طريقة الحساب</th><th>المبلغ / النسبة</th><th>سنة البداية</th><th>سنة النهاية</th><th>التكرار</th><th>الإجمالي المحسوب</th><th>ترتيب / حذف</th></tr></thead><tbody></tbody></table></div>
          <br><button type="button" class="btn ghost" onclick="addFundAdditionalFee()">+ إضافة أتعاب اختيارية</button>
          <h4>أتعاب التخارج وحافز الأداء</h4>
          <div class="grid four" id="fundExitPerformanceGrid">
            <div id="fundExitFeeEnabledWrap"><label>تطبيق أتعاب التخارج</label><select id="fundExitFeeEnabled" onchange="calculateAll()"><option value="no">لا</option><option value="yes">نعم</option></select></div>
            <div id="fundExitFeeBaseWrap"><label>أساس احتساب أتعاب التخارج</label><select id="fundExitFeeBase" onchange="calculateAll()"><option value="saleValue">قيمة البيع</option><option value="profits">الأرباح</option><option value="fixed">مبلغ ثابت</option></select></div>
            <div id="fundExitFeeRateWrap"><label>نسبة أتعاب التخارج %</label><input id="fundExitFeeRate" type="number" oninput="calculateAll()"></div>
            <div id="fundExitFixedFeeWrap"><label>مبلغ أتعاب التخارج الثابت</label><input id="fundExitFixedFee" type="number" oninput="calculateAll()"></div>
            <div id="performanceFeeEnabledWrap"><label>تطبيق حافز أداء</label><select id="performanceFeeEnabled" onchange="calculateAll()"><option value="no">لا</option><option value="yes">نعم</option></select></div>
            <div id="hurdleRateWrap"><label>الحد الأدنى للعائد Hurdle Rate %</label><input id="hurdleRate" type="number" oninput="calculateAll()"></div>
            <div id="hurdleMethodWrap"><label>طريقة احتساب الحد الأدنى</label><select id="hurdleMethod" onchange="calculateAll()"><option value="compound">تراكمي مركب</option><option value="simple">بسيط</option></select></div>
            <div id="performanceFeeRateWrap"><label>نسبة حافز الأداء %</label><input id="performanceFeeRate" type="number" oninput="calculateAll()"></div>
            <div id="performanceFeeBaseWrap"><label>أساس الاحتساب</label><select id="performanceFeeBase" onchange="calculateAll()"><option value="aboveHurdle">الأرباح فوق الحد الأدنى</option><option value="projectProfit">أرباح المشروع</option></select></div>
            <div id="catchupEnabledWrap"><label>تطبيق Catch-up</label><select id="catchupEnabled" onchange="calculateAll()"><option value="no">لا</option><option value="yes">نعم</option></select></div>
            <div id="catchupRateWrap"><label>نسبة الاستدراك %</label><input id="catchupRate" type="number" oninput="calculateAll()"></div>
            <div id="performanceCrystallizationYearWrap"><label>سنة احتساب حافز الأداء</label><input id="performanceCrystallizationYear" type="number" min="1" oninput="calculateAll()"></div>
            <div id="performanceFeeTotalWrap"><label>إجمالي حافز الأداء المحسوب</label><input id="performanceFeeTotal" readonly></div>
            <div><label>إجمالي تكاليف الصندوق</label><input id="fundFeesTotal" readonly></div>
          </div>
          <h4>جدول أتعاب الصندوق السنوي</h4>
          <div class="table-wrap"><table id="fundFeeScheduleTable"><thead><tr><th>السنة</th><th>أتعاب الإدارة</th><th>الأتعاب الإضافية</th><th>أتعاب التخارج</th><th>حافز الأداء</th><th>إجمالي أتعاب الصندوق</th><th>دورية السداد</th><th>توقيت السداد</th></tr></thead><tbody></tbody></table></div>
        </div>

        <div class="finance-block" id="developerBonusBlock"><h3>11. علاوة حسن أداء المطور</h3><div class="section-switch"><label>تطبيق علاوة حسن أداء المطور؟</label><select id="developerBonusEnabled" onchange="calculateAll()"><option value="no">لا</option><option value="yes">نعم</option></select></div><div id="developerBonusDetails" class="grid four"><div><label>نسبة المطور من الزيادة في سعر البيع %</label><input id="developerUpliftShare" type="number" oninput="calculateAll()"></div></div></div>

        <div class="finance-block" id="externalBlock"><h3>12. بنود خارجية مرنة</h3><div class="section-switch"><label>تطبيق بنود خارجية مرنة؟</label><select id="externalEnabled" onchange="calculateAll()"><option value="no">لا</option><option value="yes">نعم</option></select></div><div id="externalDetails"><div class="table-wrap"><table id="externalTable"><thead><tr><th>اسم البند</th><th>نوع البند</th><th>طريقة الحساب</th><th>القيمة الأساسية</th><th>الكمية</th><th>السعر/النسبة</th><th>يبدأ سنة</th><th>ينتهي سنة</th><th>نمو %</th><th>الناتج</th><th>ترتيب / حذف</th></tr></thead><tbody></tbody></table></div><br><button type="button" class="btn ghost" onclick="addExternal()">+ إضافة بند خارجي</button></div></div>

        <div class="finance-block" id="exitBlock">
          <h3>13. التخارج والنتائج</h3>
          <div class="grid four">
            <div><label>تطبيق التخارج؟</label><select id="exitEnabled" onchange="calculateAll()"><option value="yes">نعم</option><option value="no">لا</option></select></div>
            <div id="saleExitMethodWrap"><label>طريقة التخارج البيعي</label><select id="saleExitMethod" onchange="calculateAll()"><option value="none">بدون تخارج بيعي إضافي</option><option value="remainingArea">المساحة المتبقية × سعر البيع</option><option value="fixed">قيمة بيعية ثابتة</option></select></div>
            <div id="saleExitYearWrap"><label>سنة التخارج البيعي</label><input id="saleExitYear" type="number" min="1" oninput="calculateAll()"></div>
            <div id="saleExitRemainingAreaWrap"><label>المساحة البيعية المتبقية م²</label><input id="saleExitRemainingArea" type="number" oninput="calculateAll()"></div>
            <div id="saleExitAreaReferenceWrap"><label>المساحة البيعية في بنود الإيرادات م²</label><input id="saleExitAreaReference" readonly class="readonly-highlight"></div>
            <div id="saleExitPricePerM2Wrap"><label>سعر بيع متر التخارج</label><input id="saleExitPricePerM2" type="number" oninput="calculateAll()"></div>
            <div id="saleExitFixedValueWrap"><label>قيمة التخارج البيعي الثابتة</label><input id="saleExitFixedValue" type="number" oninput="calculateAll()"></div>
            <div id="saleExitCostRateWrap"><label>تكاليف التخارج البيعي %</label><input id="saleExitCostRate" type="number" min="0" oninput="calculateAll()"></div>
            <div><label>طريقة التخارج التشغيلي</label><select id="exitMethod" onchange="calculateAll()"><option value="capRate">الربح التشغيلي ÷ معدل الرسملة</option><option value="fixed">قيمة تشغيلية ثابتة</option><option value="noiMultiple">الربح التشغيلي × مضاعف</option><option value="revenueMultiple">الإيرادات × مضاعف</option><option value="none">بدون تخارج تشغيلي</option></select></div>
            <div><label>سنة التخارج التشغيلي</label><input id="operatingExitYear" type="number" min="1" oninput="calculateAll()"></div>
            <div><label>معدل الرسملة % / المضاعف / القيمة</label><input id="exitInput" type="number" oninput="calculateAll()"></div>
            <div><label>تكاليف التخارج التشغيلي %</label><input id="operatingExitCostRate" type="number" min="0" oninput="calculateAll()"></div>
            <div><label>سداد رصيد التمويل عند التخارج التشغيلي</label><select id="settleDebtAtExit" onchange="calculateAll()"><option value="yes">نعم</option><option value="no">لا</option></select></div>
            <div><label>فترة احتساب ROI</label><select id="roiPeriod" onchange="calculateAll()"><option value="development">مدة التطوير فقط</option><option value="full">التطوير والتشغيل</option><option value="custom">حتى سنة محددة</option></select></div>
            <div id="roiEndYearWrap"><label>آخر سنة في ROI</label><input id="roiEndYear" type="number" min="1" oninput="calculateAll()"></div>
            <div><label>فترة احتساب IRR</label><select id="irrPeriod" onchange="calculateAll()"><option value="full">كامل دورة الاستثمار</option><option value="development">مدة التطوير فقط</option><option value="custom">حتى سنة محددة</option></select></div>
            <div id="irrEndYearWrap"><label>آخر سنة في IRR</label><input id="irrEndYear" type="number" min="1" oninput="calculateAll()"></div>
          </div>
          <div id="saleExitStatusNote" class="calculation-note" hidden></div>
          <div id="analysisWarnings" class="analysis-warning"></div>
          <div class="cards" id="resultsCards">
            <div class="metric"><span>تكلفة المشروع قبل التمويل</span><strong id="resProjectCostBeforeFinance">0</strong></div>
            <div class="metric"><span>إجمالي تكلفة المشروع شامل التمويل</span><strong id="resProjectCost">0</strong></div>
            <div class="metric"><span>إجمالي إيرادات البيع</span><strong id="resSaleRevenue">0</strong></div>
            <div class="metric"><span>إيراد أول سنة تشغيل</span><strong id="resRevenueY1">0</strong></div>
            <div class="metric"><span>NOI أول سنة تشغيل</span><strong id="resNOIY1">0</strong></div>
            <div class="metric"><span>إيرادات التشغيل عند 100% إشغال</span><strong id="resFullOccupancyRevenue">0</strong></div>
            <div class="metric"><span>المصروفات عند 100% إشغال</span><strong id="resFullOccupancyOpex">0</strong></div>
            <div class="metric"><span>NOI عند 100% إشغال</span><strong id="resFullOccupancyNOI">0</strong></div>
            <div class="metric" id="resSaleExitGrossCard"><span>إجمالي التخارج البيعي</span><strong id="resSaleExitGross">0</strong><small id="resSaleExitScope"></small></div>
            <div class="metric" id="resSaleExitCard"><span>صافي التخارج البيعي</span><strong id="resSaleExit">0</strong></div>
            <div class="metric"><span>إجمالي التخارج التشغيلي</span><strong id="resOperatingExitGross">0</strong><small id="resOperatingExitScope"></small></div>
            <div class="metric"><span>صافي التخارج التشغيلي</span><strong id="resOperatingExit">0</strong></div>
            <div class="metric"><span>إجمالي صافي التخارج</span><strong id="resTerminal">0</strong></div>
            <div class="metric"><span>أتعاب المطور</span><strong id="resDevCost">0</strong></div>
            <div class="metric"><span>إجمالي تكلفة التمويل</span><strong id="resFinanceCost">0</strong></div>
            <div class="metric"><span>إجمالي تكاليف الصندوق</span><strong id="resFundFees">0</strong></div>
            <div class="metric"><span>إجمالي تكلفة الاستثمار</span><strong id="resTotalInvestmentCost">0</strong></div>
            <div class="metric"><span>ROI</span><strong id="resROI">0%</strong><small id="resROIScope"></small></div>
            <div class="metric"><span>Project IRR</span><strong id="resProjectIRR">0%</strong><small id="resProjectIRRScope"></small></div>
            <div class="metric"><span>Equity IRR</span><strong id="resIRR">0%</strong><small id="resEquityIRRScope"></small></div>
            <div class="metric"><span>فترة استرداد المشروع</span><strong id="resPayback">0</strong></div>
            <div class="metric"><span>فترة استرداد حقوق الملكية</span><strong id="resEquityPayback">0</strong></div>
            <div class="metric"><span>مساهمة الأرض العينية</span><strong id="resLandEquity">0</strong></div>
            <div class="metric"><span>الضخ النقدي المطلوب</span><strong id="resCashEquity">0</strong></div>
            <div class="metric"><span>إجمالي حقوق الملكية</span><strong id="resEquityRequired">0</strong></div>
            <div class="metric hidden"><span>إجمالي المساحة التأجيرية</span><strong id="resLeasable">0</strong></div>
            <div class="metric hidden"><span>تدفق سنة 0</span><strong id="resYear0">0</strong></div>
            <div class="metric hidden"><span>إيجار الأرض السنوي</span><strong id="resLandRent">0</strong></div>
            <div class="metric hidden"><span>إجمالي التدفقات قبل التخارج</span><strong id="resTotalOperatingCF">0</strong></div>
            <div class="metric hidden"><span>التدفق النهائي مع التخارج</span><strong id="resFinalCF">0</strong></div>
          </div>
          <h4>نطاق احتساب المؤشرات</h4>
          <div class="table-wrap"><table class="compact-table"><thead><tr><th>المؤشر</th><th>معالجة التمويل</th><th>الفترة</th></tr></thead><tbody>
            <tr><td>ROI</td><td>يشمل رسوم ترتيب التمويل والفوائد</td><td id="scopeROI">—</td></tr>
            <tr><td>Project IRR</td><td>قبل التمويل وأتعاب الصندوق</td><td id="scopeProjectIRR">—</td></tr>
            <tr><td>Equity IRR</td><td>بعد التمويل وأتعاب الصندوق وحافز الأداء</td><td id="scopeEquityIRR">—</td></tr>
            <tr><td>استرداد المشروع</td><td>تكلفة شاملة التمويل</td><td>كامل الدراسة</td></tr>
            <tr><td>استرداد حقوق الملكية</td><td>تدفقات المستثمر بعد التمويل</td><td>كامل الدراسة</td></tr>
          </tbody></table></div>
          <br>
          <h3>جدول التدفقات النقدية</h3>
          <div class="table-wrap">
            <table id="cashflowTable">
              <thead><tr><th>السنة</th><th>المرحلة</th><th class="cf-rental">الوصول للإشغال %</th><th class="cf-sales">المبيعات</th><th class="cf-rental">إيرادات التأجير</th><th class="cf-grace">خصم فترة السماح</th><th>تكلفة التطوير</th><th>دفعة المطور</th><th class="cf-rental">المصروفات</th><th>إيجار الأرض</th><th class="cf-fund">أتعاب الصندوق</th><th class="cf-finance">سحب التمويل</th><th class="cf-finance">فائدة ورسوم التمويل</th><th class="cf-finance">سداد أصل التمويل</th><th>صافي تدفق المشروع</th><th>الرصيد التراكمي</th><th>السيولة</th></tr></thead>
              <tbody></tbody>
            </table>
          </div>
        </div>

        <div class="finance-block">
          <h3>14. تحليل الحساسية العام</h3>
          <p class="hint">اختر المتغيرات المناسبة لأي مشروع.</p>
          <div class="sensitivity-picker"><div><label>المتغير المراد اختباره</label><select id="sensitivityVariableSelect"><option value="salePrice">سعر بيع الوحدات</option><option value="rentalRate">أسعار الإيجار والتأجير</option><option value="occupancy">الوصول للإشغال المستهدف</option><option value="executionCost">تكلفة التنفيذ</option><option value="developmentYears">مدة التطوير</option><option value="financeRate">معدل التمويل</option><option value="opex">المصروفات التشغيلية</option><option value="capRate">معدل الرسملة عند التخارج</option><option value="fixedExit">قيمة التخارج الثابتة</option></select></div><button type="button" class="btn ghost" onclick="addSensitivityVariable()">+ إضافة المتغير</button></div>
          <div class="table-wrap"><table id="sensitivityAssumptionsTable"><thead><tr><th>المتغير</th><th>متحفظ</th><th>أساسي من الدراسة</th><th>متفائل</th><th>طريقة التطبيق</th><th>ترتيب / حذف</th></tr></thead><tbody></tbody></table></div>
          <div class="table-wrap"><table id="sensitivityTable"><thead><tr><th>السيناريو</th><th>إجمالي الإيرادات</th><th>NOI عند الوصول 100% للإشغال المستهدف</th><th>إجمالي تكلفة الاستثمار</th><th>صافي الربح</th><th>قيمة التخارج</th><th>ROI</th><th>Project IRR</th><th>Equity IRR</th><th>فترة الاسترداد</th><th>إجمالي حقوق الملكية</th></tr></thead><tbody></tbody></table></div>
        </div>

        <div class="finance-block" id="clarificationsBlock">
          <h3>15. الإيضاحات</h3>
          <div><label for="financialClarifications">الإيضاحات</label><textarea id="financialClarifications" rows="6" maxlength="5000" oninput="triggerAutoSaveDraft()"></textarea></div>
        </div>

        <div class="finance-block" style="text-align:center;padding:20px">
          <button type="button" class="btn primary" style="font-size:15px;padding:12px 30px" onclick="exportFinancialStudyPdf()">تصدير الدراسة المالية المنظمة (PDF)</button>
        </div>

        <input type="hidden" data-key="financial_calc_data" data-type="text" id="financialCalcData">
        <input type="hidden" data-key="project_components_data" data-type="text" id="projectComponentsData">
        <input type="hidden" data-key="financial_study_model" data-type="text" id="financialStudyModelData">
      `;

      div.querySelector('.tenant-section-title')?.replaceWith(
        createProjectSectionHeader('section-financial-calc', 'الدراسة المالية والمؤشرات')
      );
      form.appendChild(div);
      enhanceNumericInputs(div);

      setTimeout(() => {
        syncFinancialFromTimeline();
        syncFinancialFromLand();
        calculateAll();
      }, 50);
    }

    function addComponent(d = {}) {
      const tb = document.querySelector('#componentsTable tbody'); if (!tb) return; const tr = document.createElement('tr'); tr.dataset.componentKey = d.id || ('p_' + Date.now() + '_' + Math.random().toString(16).slice(2)); const units = financialInputNumber(d.units, 1), unitArea = financialInputNumber(d.unitArea, 0), model = d.investmentModel || (d.leasable === 'no' ? 'nonRevenue' : 'operating'); const suggestedArea = units * unitArea; const builtArea = financialInputNumber(d.builtArea ?? d.totalArea, suggestedArea); const revenueArea = financialInputNumber(d.revenueArea, (model === 'nonRevenue' ? 0 : financialInputNumber(d.totalArea, suggestedArea))); tr.innerHTML = `
    <td data-field="name"><input value="${d.name || ''}" placeholder="مثال: معارض سيارات"></td>
    <td data-field="useType"><select>${selectHtml(useTypes, d.useType || 'retail')}</select></td>
    <td data-field="units"><input type="number" value="${units}"></td>
    <td data-field="unitArea"><input type="number" value="${unitArea}"></td>
    <td data-field="builtArea"><input type="number" value="${builtArea}"></td>
    <td data-field="revenueArea"><input type="number" value="${revenueArea}"></td>
    <td data-field="investmentModel"><select>${selectHtml(investmentModels, model)}</select></td>
    <td class="row-result compResult">محسوب</td>
    <td>${rowActionsHtml()}</td>`;
      tb.appendChild(tr);
      tr.querySelectorAll('input,select').forEach(x => x.addEventListener('input', calculateAll));
      enhanceNumericInputs(tr);
      if (!window.__batchLoading) calculateAll()
    }

    function addRevenue(d = {}) {
      const tb = document.querySelector('#revenueTable tbody'); if (!tb) return; const tr = document.createElement('tr'); tr.innerHTML = `
    <td data-field="name"><input value="${d.name || ''}" placeholder="مثال: إيجار المعارض"></td>
    <td data-field="component"><select class="componentLink"></select></td>
    <td data-field="qtySource"><select>
      <option value="manual" ${(d.qtySource || 'manual') === 'manual' ? 'selected' : ''}>إدخال يدوي</option>
      <option value="componentRevenueArea" ${['componentRevenueArea', 'componentArea'].includes(d.qtySource) ? 'selected' : ''}>المساحة البيعية / التأجيرية</option>
      <option value="componentBuiltArea" ${d.qtySource === 'componentBuiltArea' ? 'selected' : ''}>المساحة المبنية</option>
      <option value="componentUnits" ${d.qtySource === 'componentUnits' ? 'selected' : ''}>عدد الوحدات</option>
    </select></td>
    <td data-field="method"><select>${selectHtml(revenueMethods, d.method || 'areaRent')}</select><span class="help formula revenueFormula"></span>
      <div data-field="customFormula" class="custom-formula-row dynamic-off">
        <label>الفورملا المخصصة</label>
        <input type="text" value="${d.formula || 'A * B * C * D / 100'}" placeholder="A * B * C * D / 100">
      </div>
    </td>
    <td data-field="qty"><input type="number" value="${financialInputNumber(d.qty, 0)}"><span class="help input miniHelp"></span></td>
    <td data-field="price"><input type="number" value="${financialInputNumber(d.price, 0)}"><span class="help input miniHelp"></span></td>
    <td data-field="period"><input type="number" value="${financialInputNumber(d.period, 1)}"><span class="help input miniHelp"></span></td>
    <td data-field="occupancy"><input type="number" value="${financialInputNumber(d.occupancy, 100)}"><span class="help input miniHelp"></span></td>
    <td class="row-result revResult">0</td>
    <td>${rowActionsHtml()}</td>`;
      tb.appendChild(tr);
      tr.dataset.revenueKey = d.id || ('p_' + Date.now() + '_' + Math.random().toString(16).slice(2));
      tr.dataset.componentId = d.componentId || '';
      tr.querySelectorAll('input,select').forEach(x => {
        x.addEventListener('input', calculateAll);
        x.addEventListener('change', calculateAll);
      });
      const compSelect = tr.querySelector('[data-field="component"] select');
      if (compSelect) {
        const onCompChange = () => {
          tr.dataset.componentId = compSelect.value || '';
          if (!window.__batchLoading) {
            updateAutoQtyPreview(tr);
            calculateAll();
          }
        };
        compSelect.addEventListener('change', onCompChange);
        compSelect.addEventListener('input', onCompChange);
      }
      enhanceNumericInputs(tr);
      updateRevenueComponentOptions();
      updateDynamicFields();
      if (!window.__batchLoading) calculateAll()
    }

    let schedulePercentExceededMessage = '';
    function enforceSchedulePctInput(input, fieldName) {
      if (!input) return;
      const val = parseNumber(input.value);
      if (val < 0) { input.value = input.dataset.lastValidValue || '0'; return; }
      const rows = [...document.querySelectorAll('#scheduleTable tbody tr')];
      let otherSum = 0;
      rows.forEach(tr => {
        const inp = tr.querySelector(`[data-field="${fieldName}"] input`);
        if (inp && inp !== input) {
          otherSum += Math.max(0, parseNumber(inp.value));
        }
      });
      const maxAllowed = Math.max(0, 100 - otherSum);
      if (val > maxAllowed + 0.0001) {
        input.value = input.dataset.lastValidValue || '0';
        const label = fieldName === 'costPct' ? 'نسبة تكلفة التطوير' : 'نسبة دفعة المطور';
        schedulePercentExceededMessage = `تعذر قبول القيمة لأن مجموع ${label} تجاوز 100%.`;
        return;
      }
      input.dataset.lastValidValue = String(val);
      schedulePercentExceededMessage = '';
    }

    // The two percentage columns are the whole of what this study adds to a timeline stage, and
    // they are only meaningful as a share of 100%. Each cell was capped on its own, so a table
    // whose columns summed to 70% still looked complete while 30% of the development cost and of
    // the developer fee silently never entered the cashflow. The footer states both sums and the
    // note states what is still unassigned.
    function schedulePercentText(value) {
      return financialPercent(Number(value) || 0);
    }
    function renderSchedulePercentTotals(rows, costValueTotal, devValueTotal) {
      const costPct = rows.reduce((sum, row) => sum + Math.max(0, Number(row.costPct) || 0), 0);
      const devPct = rows.reduce((sum, row) => sum + Math.max(0, Number(row.devPct) || 0), 0);
      const setText = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
      setText('scheduleCostPctTotal', schedulePercentText(costPct));
      setText('scheduleDevPctTotal', schedulePercentText(devPct));
      setText('scheduleCostTotalValue', money(costValueTotal));
      setText('scheduleDevTotalValue', money(devValueTotal));
      const note = document.getElementById('scheduleTotalsNote');
      if (!note) return;
      if (!rows.length) { note.hidden = true; note.textContent = ''; return; }
      const costLeft = 100 - costPct, devLeft = 100 - devPct;
      const parts = schedulePercentExceededMessage ? [schedulePercentExceededMessage] : [];
      if (costLeft > 0.01) parts.push(`غير موزَّع من نسبة تكلفة التطوير: ${schedulePercentText(costLeft)}`);
      if (devLeft > 0.01) parts.push(`غير موزَّع من نسبة دفعة المطور: ${schedulePercentText(devLeft)}`);
      note.hidden = parts.length === 0;
      note.textContent = parts.join(' — ');
      note.classList.toggle('error', !!schedulePercentExceededMessage);
    }

    // The stage name and its year mirror the project timeline and are read-only here; only the
    // two financial percentages belong to this study, so only they stay editable.
    function addScheduleStage(d = {}) {
      const tb = document.querySelector('#scheduleTable tbody'); if (!tb) return;
      const rows = [...tb.querySelectorAll('tr')];
      let existingCostSum = 0, existingDevSum = 0;
      rows.forEach(tr => {
        existingCostSum += Math.max(0, parseNumber(tr.querySelector('[data-field="costPct"] input')?.value));
        existingDevSum += Math.max(0, parseNumber(tr.querySelector('[data-field="devPct"] input')?.value));
      });
      const costVal = Math.max(0, Math.min(Math.max(0, 100 - existingCostSum), financialInputNumber(d.costPct, 0)));
      const devVal = Math.max(0, Math.min(Math.max(0, 100 - existingDevSum), financialInputNumber(d.devPct, 0)));
      const tr = document.createElement('tr');
      tr.dataset.stageYear = String(d.year ?? 1);
      tr.dataset.stageEndYear = String(d.endYear ?? d.year ?? 1);
      tr.innerHTML = `
    <td data-field="name"><input value="${escapeHtml(d.name || '')}" readonly class="readonly-highlight" title="تُعدّل من قسم الجدول الزمني"></td>
    <td data-field="costPct"><input type="number" min="0" max="100" value="${costVal}"></td>
    <td data-field="devPct"><input type="number" min="0" max="100" value="${devVal}"></td>
    <td class="row-result stageCost">0</td>
    <td class="row-result stageDevPayment">0</td>`;
      tb.appendChild(tr);
      tr.querySelectorAll('input:not([readonly])').forEach(x => {
        const fieldName = x.closest('td')?.dataset?.field;
        if (fieldName === 'costPct' || fieldName === 'devPct') {
          x.dataset.lastValidValue = String(parseNumber(x.value));
          const runEnforce = () => {
            enforceSchedulePctInput(x, fieldName);
            calculateAll();
          };
          x.addEventListener('input', runEnforce);
        } else {
          x.addEventListener('input', calculateAll);
        }
      });
      enhanceNumericInputs(tr);
      if (!window.__batchLoading) calculateAll()
    }

    function addFinanceDrawYear(d = {}) {
      const tb = document.querySelector('#financeDrawTable tbody'); if (!tb) return; const tr = document.createElement('tr');
      tr.innerHTML = `<td data-field="year"><input type="number" min="1" value="${financialInputNumber(d.year, 1)}" readonly></td><td data-field="drawPct"><input type="number" min="0" value="${financialInputNumber(d.drawPct, 0)}"></td><td class="row-result financeDrawAmount">0</td>`;
      tb.appendChild(tr); tr.querySelectorAll('input').forEach(x => x.addEventListener('input', calculateAll)); enhanceNumericInputs(tr);
    }
    function syncFinanceDrawPlan(plan) {
      const years = Math.max(1, Math.min(20, Math.round(num('financeDrawYears') || 1)));
      const tb = document.querySelector('#financeDrawTable tbody'); if (!tb) return;
      const existing = Array.isArray(plan) ? plan : [...tb.querySelectorAll('tr')].map(tr => ({ year: parseNumber(tr.querySelector('[data-field="year"] input')?.value) || 1, drawPct: parseNumber(tr.querySelector('[data-field="drawPct"] input')?.value) }));
      tb.innerHTML = '';
      for (let year = 1; year <= years; year++) { const found = existing.find(r => Number(r.year) === year); addFinanceDrawYear(found || { year, drawPct: 100 / years }); }
    }
    function addFinanceRepaymentYear(d = {}) {
      const tb = document.querySelector('#financeRepaymentTable tbody'); if (!tb) return; const tr = document.createElement('tr');
      tr.innerHTML = `<td data-field="year"><input type="number" min="1" value="${financialInputNumber(d.year, 1)}" readonly></td><td data-field="repaymentPct"><input type="number" min="0" value="${financialInputNumber(d.repaymentPct, 0)}"></td><td class="row-result financeRepaymentAmount">0</td>`;
      tb.appendChild(tr); tr.querySelectorAll('input').forEach(x => x.addEventListener('input', calculateAll)); enhanceNumericInputs(tr);
    }
    function syncFinanceRepaymentPlan(plan) {
      const startYear = Math.max(1, Math.min(60, Math.round(num('financeRepaymentStartYear') || 1)));
      const years = Math.max(1, Math.min(40, Math.round(num('financeRepaymentYears') || 1)));
      const tb = document.querySelector('#financeRepaymentTable tbody'); if (!tb) return;
      const existing = Array.isArray(plan) ? plan : [...tb.querySelectorAll('tr')].map(tr => ({
        year: parseNumber(tr.querySelector('[data-field="year"] input')?.value) || 1,
        repaymentPct: parseNumber(tr.querySelector('[data-field="repaymentPct"] input')?.value)
      }));
      tb.innerHTML = '';
      for (let index = 0; index < years; index++) {
        const year = startYear + index;
        const found = existing.find(r => Number(r.year) === year);
        addFinanceRepaymentYear(found || { year, repaymentPct: 100 / years });
      }
    }
    function addFundAdditionalFee(d = {}) {
      const tb = document.querySelector('#fundAdditionalFeesTable tbody'); if (!tb) return; const tr = document.createElement('tr');
      tr.innerHTML = `<td data-field="name"><input value="${d.name || ''}" placeholder="مثال: أتعاب التأسيس والهيكلة"></td><td data-field="method"><select>${selectHtml(fundAdditionalFeeMethods, d.method || 'fixed')}</select><span class="help formula fundAdditionalFeeFormula"></span></td><td data-field="value"><input type="number" min="0" value="${financialInputNumber(d.value, 0)}"></td><td data-field="startYear"><input type="number" min="1" value="${financialInputNumber(d.startYear, 1)}"></td><td data-field="endYear"><input type="number" min="1" value="${financialInputNumber(d.endYear, financialInputNumber(d.startYear, 1))}"></td><td data-field="recurrence"><select><option value="once" ${d.recurrence === 'annual' ? '' : 'selected'}>مرة واحدة</option><option value="annual" ${d.recurrence === 'annual' ? 'selected' : ''}>سنوي</option></select></td><td class="row-result fundAdditionalFeeResult">0</td><td>${rowActionsHtml()}</td>`;
      tb.appendChild(tr); tr.querySelectorAll('input').forEach(x => x.addEventListener('input', calculateAll)); tr.querySelectorAll('select').forEach(x => x.addEventListener('change', calculateAll)); enhanceNumericInputs(tr); if (!window.__batchLoading) calculateAll();
    }
    function collectFundAdditionalFees() { return [...document.querySelectorAll('#fundAdditionalFeesTable tbody tr')].map(tr => ({ name: tr.querySelector('[data-field="name"] input')?.value || '', method: tr.querySelector('[data-field="method"] select')?.value || 'fixed', value: parseNumber(tr.querySelector('[data-field="value"] input')?.value), startYear: parseNumber(tr.querySelector('[data-field="startYear"] input')?.value) || 1, endYear: parseNumber(tr.querySelector('[data-field="endYear"] input')?.value) || 1, recurrence: tr.querySelector('[data-field="recurrence"] select')?.value || 'once' })) }
    function fundAdditionalFeeFormulaText(method) { return { fixed: 'المبلغ المدخل مباشرة', percentFundCapital: 'رأس مال الصندوق × النسبة', percentProjectCost: 'إجمالي تكلفة المشروع × النسبة', percentExit: 'إجمالي قيمة التخارج × النسبة', percentProfit: 'الربح السنوي الموجب × النسبة' }[method] || '—' }
    function calculateFundAdditionalFee(method, value, bases = {}) { const entered = Math.max(0, Number(value) || 0); if (method === 'fixed') return entered; if (method === 'percentFundCapital') return Math.max(0, Number(bases.fundCapital) || 0) * entered / 100; if (method === 'percentProjectCost') return Math.max(0, Number(bases.projectCost) || 0) * entered / 100; if (method === 'percentExit') return Math.max(0, Number(bases.exitValue) || 0) * entered / 100; if (method === 'percentProfit') return Math.max(0, Number(bases.profit) || 0) * entered / 100; return 0 }
    function addOccupancyRampYear(d = {}) { const tb = document.querySelector('#occupancyRampTable tbody'); if (!tb) return; const tr = document.createElement('tr'); tr.innerHTML = `<td data-field="operationYear"><input type="number" value="${financialInputNumber(d.operationYear, 1)}" readonly></td><td data-field="studyYear"><input type="number" value="${financialInputNumber(d.studyYear, ((num('developmentYears') || 0) + financialInputNumber(d.operationYear, 1)))}" readonly></td><td data-field="reachPct"><input type="number" min="0" max="100" value="${financialInputNumber(d.reachPct, 100)}"></td><td class="row-result rampRevenue">0</td>`; tb.appendChild(tr); tr.querySelectorAll('input').forEach(x => x.addEventListener('input', calculateAll)); enhanceNumericInputs(tr) }
    function syncOccupancyRamp(plan) { const years = Math.max(1, Math.min(40, Math.round(num('operationYears') || 1))), developmentYears = Math.max(1, Math.round(num('developmentYears') || 1)), tb = document.querySelector('#occupancyRampTable tbody'); if (!tb) return; const existing = Array.isArray(plan) ? plan : [...tb.querySelectorAll('tr')].map(tr => ({ operationYear: parseNumber(tr.querySelector('[data-field="operationYear"] input')?.value), reachPct: parseNumber(tr.querySelector('[data-field="reachPct"] input')?.value) })); tb.innerHTML = ''; const defaults = [60, 75, 90, 100]; for (let operationYear = 1; operationYear <= years; operationYear++) { const found = existing.find(r => Number(r.operationYear) === operationYear); addOccupancyRampYear(found || { operationYear, studyYear: developmentYears + operationYear, reachPct: defaults[operationYear - 1] ?? 100 }); } }
    function occupancyReachForYear(operationYear) { if (operationYear < 1) return 0; const row = [...document.querySelectorAll('#occupancyRampTable tbody tr')].find(tr => parseNumber(tr.querySelector('[data-field="operationYear"] input')?.value) === operationYear); return Math.max(0, Math.min(100, parseNumber(row?.querySelector('[data-field="reachPct"] input')?.value))) / 100 }

    // A schedule table must stop where its own entered period stops. Both tables used to render one
    // row per project year, so a 20-year study printed rows beyond a 10-year facility or a 4-year fee
    // period. Financing and fund fees now use their entered end years as strict display boundaries.
    const FINANCIAL_ROW_EPSILON = 0.5;
    function lastYearCarryingValue(projected, fields) {
      return projected.reduce((last, row) => fields.some(field => Math.abs(Number(row[field]) || 0) > FINANCIAL_ROW_EPSILON) ? row.year : last, 0);
    }
    function financeMovementRows(projected, financeOn, repaymentStartYear, repaymentYears) {
      if (!financeOn) return [];
      const plannedEnd = Math.max(1, Math.round(repaymentStartYear || 1)) + Math.max(1, Math.round(repaymentYears || 1)) - 1;
      return projected.filter(row => row.year <= plannedEnd);
    }
    function fundFeeScheduleRows(projected, fundFeesOn, feeEndYear) {
      if (!fundFeesOn) return [];
      const plannedEnd = Math.max(1, Math.ceil(feeEndYear || 1));
      return projected.filter(row => row.year <= plannedEnd);
    }
    function addCost(d = {}) { const tb = document.querySelector('#costTable tbody'); if (!tb) return; const tr = document.createElement('tr'); tr.innerHTML = `<td data-field="name"><input value="${d.name || ''}" placeholder="مثال: تكلفة المباني"></td><td data-field="class"><select>${selectHtml(costClasses, d.class || 'execution')}</select></td><td data-field="method"><select>${selectHtml(costMethods, d.method || 'areaCost')}</select><span class="help formula costFormula"></span><div data-field="customFormula" class="custom-formula-row dynamic-off"><label>الفورملا المخصصة</label><input type="text" value="${d.formula || 'A * B * C'}" placeholder="A * B * C"></div></td><td data-field="qty"><input type="number" value="${financialInputNumber(d.qty, 0)}"><span class="help input miniHelp"></span></td><td data-field="price"><input type="number" value="${financialInputNumber(d.price, 0)}"><span class="help input miniHelp"></span></td><td data-field="duration"><input type="number" value="${financialInputNumber(d.duration, 1)}"><span class="help input miniHelp"></span></td><td class="row-result costResult">0</td><td>${rowActionsHtml()}</td>`; tb.appendChild(tr); tr.querySelectorAll('input,select').forEach(x => x.addEventListener('input', calculateAll)); enhanceNumericInputs(tr); updateDynamicFields(); if (!window.__batchLoading) calculateAll() }
    function addOpex(d = {}) { const tb = document.querySelector('#opexTable tbody'); if (!tb) return; const tr = document.createElement('tr'); tr.innerHTML = `<td data-field="name"><input value="${d.name || ''}" placeholder="مثال: تشغيل شهري"></td><td data-field="method"><select>${selectHtml(opexMethods, d.method || 'monthlyFixed')}</select><span class="help formula opexFormula"></span><div data-field="customFormula" class="custom-formula-row dynamic-off"><label>الفورملا المخصصة</label><input type="text" value="${d.formula || 'A * B'}" placeholder="A * B"></div></td><td data-field="qty"><input type="number" value="${financialInputNumber(d.qty, 0)}"><span class="help input miniHelp"></span></td><td data-field="price"><input type="number" value="${financialInputNumber(d.price, 0)}"><span class="help input miniHelp"></span></td><td class="row-result opexResult">0</td><td>${rowActionsHtml()}</td>`; tb.appendChild(tr); tr.querySelectorAll('input,select').forEach(x => x.addEventListener('input', calculateAll)); enhanceNumericInputs(tr); updateDynamicFields(); if (!window.__batchLoading) calculateAll() }
    function addExternal(d = {}) { const tb = document.querySelector('#externalTable tbody'); if (!tb) return; const tr = document.createElement('tr'); tr.innerHTML = `<td data-field="name"><input value="${d.name || ''}" placeholder="مثال: رعاية سنوية"></td><td data-field="type"><select>${selectHtml(externalTypes, d.type || 'revenue')}</select></td><td data-field="method"><select>${selectHtml(externalMethods, d.method || 'fixed')}</select><span class="help formula externalFormula"></span><div data-field="customFormula" class="custom-formula-row dynamic-off"><label>الفورملا المخصصة</label><input type="text" value="${d.formula || 'A'}" placeholder="B * C"></div></td><td data-field="base"><input type="number" value="${financialInputNumber(d.base, 0)}"><span class="help input miniHelp"></span></td><td data-field="qty"><input type="number" value="${financialInputNumber(d.qty, 0)}"><span class="help input miniHelp"></span></td><td data-field="price"><input type="number" value="${financialInputNumber(d.price, 0)}"><span class="help input miniHelp"></span></td><td data-field="startYear"><input type="number" value="${financialInputNumber(d.startYear, 1)}"></td><td data-field="endYear"><input type="number" value="${financialInputNumber(d.endYear, 10)}"></td><td data-field="growth"><input type="number" value="${financialInputNumber(d.growth, 0)}"></td><td class="row-result externalResult">0</td><td>${rowActionsHtml()}</td>`; tb.appendChild(tr); tr.querySelectorAll('input,select').forEach(x => x.addEventListener('input', calculateAll)); enhanceNumericInputs(tr); updateDynamicFields(); if (!window.__batchLoading) calculateAll() }

    function safeCustomFormula(formula, vars = {}) {
      formula = String(formula || '').trim(); if (!formula) return 0;
      const allowedNames = ['A', 'B', 'C', 'D', 'E', 'F', 'max', 'min', 'round', 'abs', 'pow'];
      const words = formula.match(/[A-Za-z_]+/g) || [];
      for (const w of words) { if (!allowedNames.includes(w)) throw new Error('متغير غير مسموح: ' + w); }
      if (!/^[0-9A-Za-z_+\-*/().,\s]+$/.test(formula)) throw new Error('الفورملا تحتوي رموز غير مسموحة');
      const A = Number(vars.A || 0), B = Number(vars.B || 0), C = Number(vars.C || 0), D = Number(vars.D || 0), E = Number(vars.E || 0), F = Number(vars.F || 0);
      const max = Math.max, min = Math.min, round = Math.round, abs = Math.abs, pow = Math.pow;
      const result = Function('A', 'B', 'C', 'D', 'E', 'F', 'max', 'min', 'round', 'abs', 'pow', `"use strict"; return (${formula});`)(A, B, C, D, E, F, max, min, round, abs, pow);
      return Number.isFinite(Number(result)) ? Number(result) : 0;
    }
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
      ['salesStartYear', 'landContributionYear', 'saleExitYear', 'operatingExitYear', 'roiEndYear', 'irrEndYear', 'fundFeeStartYear', 'fundFeeEndYear', 'performanceCrystallizationYear', 'graceStartYear'].forEach(id => { const el = document.getElementById(id); if (!el) return; el.max = String(totalYears); const n = parseNumber(el.value); if (n > totalYears) el.value = String(totalYears); if (n < 1) el.value = '1' });
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
      const operationYears = modeFlags.rental ? Math.max(1, Math.min(40, Math.round(num('operationYears') || 10))) : 0;
      if (modeFlags.rental && document.querySelectorAll('#occupancyRampTable tbody tr').length !== operationYears) syncOccupancyRamp();
      const salesStartYear = Math.max(1, Math.round(num('salesStartYear') || 1));
      const salesYears = Math.max(1, Math.min(20, Math.round(num('salesYears') || 1)));
      const operationStartYear = modeFlags.rental ? developmentYears + 1 : 0;
      const rentalEndYear = modeFlags.rental ? developmentYears + operationYears : developmentYears;
      const salesEndYear = modeFlags.sales ? salesStartYear + salesYears - 1 : developmentYears;
      const naturalTotalYears = Math.max(developmentYears, rentalEndYear, salesEndYear);
      const totalYears = naturalTotalYears;
      syncProjectYearBounds(totalYears, developmentYears);
      const disp = document.getElementById('totalProjectYearsDisplay'); if (disp) disp.value = totalYears + ' سنة';
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
      if (covEl) covEl.value = money(covered); if (openEl) openEl.value = money(open); if (tBuiltEl) tBuiltEl.value = money(builtUpAreaAbove + basement); if (opStartEl) opStartEl.value = modeFlags.rental ? 'السنة ' + operationStartYear : 'غير مطبق'; if (lValEl) lValEl.value = money(landValue); if (aRentEl) aRentEl.value = money(landRent);
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
      const financeOn = val('financeEnabled') === 'yes', financeShare = financeOn ? Math.max(0, Math.min(100, num('financingRate'))) / 100 : 0, financeBase = val('financeBase') || 'withLand', financeBaseAmount = Math.max(0, financeBase === 'withoutLand' ? projectCost - landCostIncluded : projectCost), facilityAmount = financeBaseAmount * financeShare, arrangementFee = financeOn ? facilityAmount * (num('financeArrangementFeeRate') / 100) : 0, annualFinanceRate = financeOn ? num('annualFinanceRate') / 100 : 0, financeInterestMethod = val('financeInterestMethod') || 'declining', financeDrawYears = Math.max(1, Math.min(20, Math.round(num('financeDrawYears') || 1)));
      if (document.querySelectorAll('#financeDrawTable tbody tr').length !== financeDrawYears) syncFinanceDrawPlan();
      const financePlan = [...document.querySelectorAll('#financeDrawTable tbody tr')].map(tr => ({ tr, year: parseNumber(tr.querySelector('[data-field="year"] input')?.value) || 1, drawPct: Math.max(0, parseNumber(tr.querySelector('[data-field="drawPct"] input')?.value)) }));
      const financeDrawPctTotal = financePlan.reduce((sum, row) => sum + row.drawPct, 0);
      financePlan.forEach(row => { const amount = financeDrawPctTotal ? facilityAmount * (row.drawPct / financeDrawPctTotal) : 0; const c = row.tr.querySelector('.financeDrawAmount'); if (c) c.textContent = money(amount); });
      const financeRepaymentStartYear = Math.max(1, Math.min(totalYears, Math.round(num('financeRepaymentStartYear') || 1))), financeRepaymentYears = Math.max(1, Math.min(40, Math.round(num('financeRepaymentYears') || 1)));
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