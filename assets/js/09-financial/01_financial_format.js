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
      const years = Math.max(0, Math.min(20, Math.round(num('financeDrawYears'))));
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
      const years = Math.max(0, Math.min(40, Math.round(num('financeRepaymentYears'))));
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
    function syncOccupancyRamp(plan) { const years = Math.max(0, Math.min(40, Math.round(num('operationYears')))), developmentYears = Math.max(1, Math.round(num('developmentYears') || 1)), tb = document.querySelector('#occupancyRampTable tbody'); if (!tb) return; const existing = Array.isArray(plan) ? plan : [...tb.querySelectorAll('tr')].map(tr => ({ operationYear: parseNumber(tr.querySelector('[data-field="operationYear"] input')?.value), reachPct: parseNumber(tr.querySelector('[data-field="reachPct"] input')?.value) })); tb.innerHTML = ''; const defaults = [60, 75, 90, 100]; for (let operationYear = 1; operationYear <= years; operationYear++) { const found = existing.find(r => Number(r.operationYear) === operationYear); addOccupancyRampYear(found || { operationYear, studyYear: developmentYears + operationYear, reachPct: defaults[operationYear - 1] ?? 100 }); } }
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
