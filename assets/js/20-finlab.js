/* 20-finlab.js — «معمل الدراسة المالية»: formula inspector + live patcher for the financial study.

   Two hosts:
   - /finlab-frame (super-admin lab page iframe): mounts the study standalone and wires the lab.
   - ?finlab=1 overlay on the real app: same engine attached to the rendered #section-financial-calc.

   The lab never reimplements a formula: it fetches assets/js/09-financial.js as text, evaluates it
   in place (top-level const/let -> var so re-evaluation is legal), traces every DOM write back to
   the source line via Error().stack during a recalculation, and applies edits by splicing real
   source lines then re-evaluating. Export = the patched real file, so what ships is what was
   reviewed — nothing is transcribed. */

(function () {
  const SOURCE_URL = '/assets/js/09-financial.js';
  const APPLY_URL = '/api/dev/finlab-apply';
  const SECTION_ID = 'section-financial-calc';

  const state = {
    mode: null,
    ready: false,
    original: null,
    source: null,
    edits: [],            // stack of previous full sources
    tracing: false,
    trace: new WeakMap(), // el -> { line, fn, prop }
    inspectOn: false,
    section: null,
    mounted: false,
    settersWrapped: false,
    listenersHooked: false
  };

  /* ---------- equation dictionary (Arabic) ---------- */
  /* id -> { f: formula text, code: [line numbers in 09-financial.js] } */
  const FORMULA_BY_ID = {
    coveredArea: { f: 'مساحة الأرض × نسبة التغطية', code: [1156, 1168] },
    openArea: { f: 'مساحة الأرض − المساحة المغطاة', code: [1156, 1168] },
    totalBuiltUpArea: { f: 'مسطحات البناء فوق الأرض + مساحة البدرومات', code: [1168] },
    operationStartYear: { f: 'مدة التطوير + 1', code: [1146, 1168] },
    totalProjectYearsDisplay: { f: 'أطول مدة من: التطوير، نهاية التشغيل، نهاية البيع', code: [1149, 1152] },
    landValue: { f: 'حسب الطريقة: مساحة الأرض × سعر المتر — أو القيمة اليدوية', code: [1157, 1159] },
    annualLandRent: { f: 'نسبة من قيمة الأرض — أو سنوي ثابت — أو شهري × 12', code: [1160, 1163] },
    landRentSummary: { f: 'نفس إيجار الأرض السنوي المحسوب', code: [1160, 1163] },
    landCostIncluded: { f: 'قيمة الأرض إذا كانت «مملوكة وتدخل ضمن التكلفة»، وإلا صفر', code: [1164] },
    developerBaseAmount: { f: 'أساس المطور المختار: تنفيذ فقط / + خدمات / + تصميم وخدمات / مشروع بدون أرض / مشروع شامل', code: [1235, 1025] },
    developerCostValue: { f: 'قيمة أساس المطور × نسبة المطور', code: [1236] },
    executionCostTotal: { f: 'مجموع بنود التكلفة المصنفة «تنفيذ» (ما عدا بنود نسبة-من-التنفيذ)', code: [1203, 1207] },
    designCostTotal: { f: 'مجموع البنود المصنفة «تصميم ودراسات»', code: [1208, 1213] },
    servicesCostTotal: { f: 'مجموع البنود المصنفة «رسوم خدمات»', code: [1208, 1213] },
    advertisingCostTotal: { f: 'مجموع البنود المصنفة «دعاية وإعلان»', code: [1208, 1213] },
    financeBaseAmount: { f: 'تكلفة المشروع مع الأرض أو بدونها حسب الأساس المختار', code: [1245] },
    facilityAmount: { f: 'قيمة أساس التمويل × نسبة التمويل', code: [1245] },
    arrangementFeeTotal: { f: 'قيمة التسهيل × رسوم ترتيب التمويل', code: [1245] },
    financeInterestTotal: { f: 'مجموع الفوائد السنوية — ثابتة: التسهيل × المعدل خلال فترة السداد | متناقصة: الرصيد القائم × المعدل', code: [1328, 1334] },
    landEquityContribution: { f: 'قيمة الأرض إذا كانت مساهمة عينية', code: [1317, 1364] },
    cashEquityRequired: { f: 'مجموع الضخ النقدي اللازم لتغطية العجز السنوي', code: [1351, 1356] },
    equityRequired: { f: 'مساهمة الأرض العينية + الضخ النقدي', code: [1364] },
    fundManagementFeesTotal: { f: 'مجموع (أساس الأتعاب × النسبة × معامل النمو × كسر السنة) على فترة الاحتساب', code: [1336, 1338] },
    performanceFeeTotal: { f: 'في سنة الاحتساب: أساس الحافز (أرباح فوق الحد أو أرباح المشروع) × نسبة الحافز + الاستدراك', code: [1347, 1349] },
    fundFeesTotal: { f: 'أتعاب الإدارة + الإضافية + التخارج + حافز الأداء', code: [1364] },
    graceTotalDiscount: { f: 'مجموع خصومات فترة السماح السنوية', code: [1290, 1291] },
    saleExitAreaReference: { f: 'المساحة البيعية المجمعة من بنود الإيرادات (بيع مساحة)', code: [919, 920] },
    resProjectCostBeforeFinance: { f: 'تكاليف المشروع + أتعاب المطور + البنود الخارجية + الأرض الداخلة', code: [1237] },
    resProjectCost: { f: 'تكلفة المشروع + رسوم الترتيب + إجمالي الفوائد', code: [1364] },
    resTotalInvestmentCost: { f: 'تكلفة المشروع شامل التمويل + إجمالي أتعاب الصندوق', code: [1364] },
    resSaleRevenue: { f: 'مجموع بنود الإيراد بطريقة «بيع مساحة»', code: [1184, 1198] },
    resRevenueY1: { f: 'إيرادات التشغيل في أول سنة تشغيل (بعد الوصول والسماح)', code: [1297, 1298] },
    resNOIY1: { f: 'إيراد التشغيل − المصروفات − إيجار الأرض، أول سنة تشغيل', code: [1296, 1298] },
    resFullOccupancyRevenue: { f: 'إيرادات التشغيل كأن الإشغال المستهدف 100% في أول سنة', code: [1299, 1304] },
    resFullOccupancyOpex: { f: 'المصروفات المحسوبة على إيراد الإشغال الكامل', code: [1305] },
    resFullOccupancyNOI: { f: 'إيراد كامل − مصروفات كاملة − إيجار الأرض', code: [1306] },
    resSaleExitGross: { f: 'المساحة المتبقية × سعر المتر — أو القيمة الثابتة', code: [1320] },
    resSaleExit: { f: 'إجمالي التخارج البيعي − تكلفة التخارج', code: [1322, 1323] },
    resOperatingExitGross: { f: 'حسب الطريقة: NOI ÷ معدل الرسملة | قيمة ثابتة | NOI × مضاعف | إيرادات × مضاعف', code: [1321] },
    resOperatingExit: { f: 'إجمالي التخارج التشغيلي − تكلفة التخارج', code: [1322, 1323] },
    resTerminal: { f: 'صافي التخارج البيعي + صافي التخارج التشغيلي', code: [1322, 1323] },
    resDevCost: { f: 'أتعاب المطور = الأساس × النسبة', code: [1236] },
    resFinanceCost: { f: 'رسوم الترتيب + إجمالي الفوائد', code: [1364] },
    resFundFees: { f: 'إجمالي أتعاب الصندوق (إدارة + إضافية + تخارج + أداء)', code: [1364] },
    resROI: { f: '(إجمالي التدفقات الداخلة − إجمالي الخارجة) ÷ إجمالي الخارجة على فترة ROI — الخارجة تشمل المصروفات وإيجار الأرض ورسوم وفوائد التمويل وأتعاب الصندوق', code: [1366, 1367] },
    resProjectIRR: { f: 'معدل الخصم الذي يصفّر NPV لتدفقات المشروع قبل التمويل (unlevered) — سنة 0 تحمل الأرض العينية بالسالب', code: [1365, 782] },
    resIRR: { f: 'معدل الخصم الذي يصفّر NPV لتدفقات حقوق الملكية (توزيعات − ضخ) بعد التمويل وأتعاب الصندوق', code: [1365, 1355] },
    resPayback: { f: 'أول سنة تسترد فيها التدفقات (مبيعات + NOI + تخارج) إجمالي تكلفة الاستثمار', code: [1364, 796] },
    resEquityPayback: { f: 'أول سنة يتحول فيها الرصيد التراكمي لتدفقات حقوق الملكية إلى موجب', code: [1364, 801] },
    resLeasable: { f: 'مجموع المساحات البيعية/التأجيرية للمكونات بنماذج الإيجار والتشغيل', code: [1172, 1180] },
    resLandRent: { f: 'إيجار الأرض السنوي المحسوب', code: [1160, 1163] },
    resTotalOperatingCF: { f: 'مجموع NOI كل سنوات الدراسة', code: [1357] },
    resFinalCF: { f: 'صافي التدفق في آخر سنة', code: [1357] },
    resYear0: { f: 'تدفق سنة الصفر: الأرض العينية بالسالب إن وُجدت', code: [1275, 1276] },
    resLandEquity: { f: 'مساهمة الأرض العينية ضمن حقوق الملكية', code: [1364] },
    resCashEquity: { f: 'مجموع الضخ النقدي', code: [1351, 1356] },
    resEquityRequired: { f: 'العينية + النقدية', code: [1364] },
    resSaleExitScope: { f: 'سنة التخارج البيعي ونسبة تكلفته', code: [1409] },
    resOperatingExitScope: { f: 'سنة التخارج التشغيلي ونسبة تكلفته', code: [1411] },
    resROIScope: { f: 'نطاق فترة ROI', code: [1367, 1425] },
    resProjectIRRScope: { f: 'نطاق فترة IRR — قبل التمويل', code: [1426] },
    resEquityIRRScope: { f: 'نطاق فترة IRR — بعد التمويل', code: [1427] },
    scopeROI: { f: 'وصف فترة ROI', code: [1367] },
    scopeProjectIRR: { f: 'وصف فترة IRR', code: [1367] },
    scopeEquityIRR: { f: 'وصف فترة IRR', code: [1367] },
    scheduleCostPctTotal: { f: 'مجموع نسب تكلفة التطوير عبر المراحل', code: [1272, 620] },
    scheduleDevPctTotal: { f: 'مجموع نسب دفعة المطور عبر المراحل', code: [1272, 620] },
    scheduleCostTotalValue: { f: 'مجموع قيم تكلفة المراحل = قاعدة التكلفة كاملة بعد التطبيع', code: [1271] },
    scheduleDevTotalValue: { f: 'مجموع دفعات المطور = أتعاب المطور كاملة بعد التطبيع', code: [1271] }
  };

  /* class -> formula shown for row-level result cells */
  const FORMULA_BY_CLASS = {
    compResult: { f: 'نموذج الاستفادة + المساحة المبنية للمكون', code: [1179] },
    revResult: { f: 'الإيراد السنوي عند الإشغال المستهدف — حسب طريقة الحساب المختارة في الصف', code: [810, 822, 1189] },
    costResult: { f: 'حسب الطريقة: كمية × سعر | ثابتة | شهرية × مدة | نسبة من التنفيذ | نسبة من الإيرادات | مخصصة', code: [823, 837, 1212] },
    opexResult: { f: 'حسب الطريقة: شهرية × 12 | نسبة من الإيرادات | موظفين × راتب × 12 | سنوية | لكل وحدة/متر | مخصصة', code: [838, 851, 1219] },
    externalResult: { f: 'حسب الطريقة والنوع — وتُضرب في معامل النمو السنوي داخل التدفقات', code: [852, 868, 1286] },
    stageCost: { f: 'قاعدة تكلفة التطوير (تكاليف + خارجية) × نسبة المرحلة ÷ مجموع النسب', code: [1271] },
    stageDevPayment: { f: 'أتعاب المطور × نسبة المرحلة ÷ مجموع النسب', code: [1271] },
    financeDrawAmount: { f: 'قيمة التسهيل × نسبة السنة ÷ مجموع نسب السحب', code: [1249] },
    financeRepaymentAmount: { f: 'قيمة التسهيل × نسبة السنة ÷ مجموع نسب السداد', code: [1254] },
    rampRevenue: { f: 'إيرادات التشغيل للسنة = قاعدة الإيراد × نسبة الوصول المدخلة', code: [1280, 1290, 1470] },
    fundAdditionalFeeResult: { f: 'إجمالي الأتعاب عبر سنوات تفعيلها حسب طريقتها', code: [1340, 1362] }
  };

  /* tableId -> { column header -> formula } for generated tables */
  const FORMULA_BY_HEADER = {
    cashflowTable: {
      'المبيعات': 'إجمالي مبيعات البيع ÷ عدد سنوات البيع الفعلية',
      'إيرادات التأجير': 'قاعدة الإيرادات × نسبة الوصول + نسبة-من-الإيرادات + بنود خارجية − خصم السماح',
      'خصم فترة السماح': 'نسبة الخصم × كسر السنة — أو قيمة الجدول — بحد أقصى إيراد السنة',
      'تكلفة التطوير': 'نصيب السنة من توزيع المراحل، أو بالتساوي على سنوات التطوير إن لم تُوزع نسب',
      'دفعة المطور': 'نفس التوزيع على إجمالي أتعاب المطور',
      'المصروفات': 'بنود المصروفات التشغيلية + الخارجية التشغيلية للسنة',
      'إيجار الأرض': 'إيجار الأرض إذا كانت مستأجرة أو حق انتفاع',
      'أتعاب الصندوق': 'إدارة + إضافية + تخارج + حافز أداء للسنة',
      'سحب التمويل': 'وفق خطة السحب، بحد أقصى المتبقي من التسهيل',
      'فائدة ورسوم التمويل': 'فائدة السنة + رسوم الترتيب في سنة أول سحب',
      'سداد أصل التمويل': 'وفق خطة السداد — أو تسوية كاملة عند التخارج التشغيلي وفي آخر سنة',
      'صافي تدفق المشروع': 'إيرادات + تخارج + سحب − تطوير − مطور − مصروفات − إيجار − فوائد − سداد − أتعاب',
      'الرصيد التراكمي': 'مجموع صافي التدفقات حتى السنة',
      'السيولة': 'الاحتياطي النقدي بعد الضخ والتوزيع'
    },
    debtScheduleTable: {
      'الرصيد الافتتاحي': 'رصيد العام السابق الختامي',
      'السحب': 'سحب السنة وفق الخطة',
      'الفائدة': 'ثابتة على أصل التسهيل خلال فترة السداد — أو متناقصة على الرصيد القائم',
      'رسوم التمويل': 'رسوم الترتيب في سنة أول سحب',
      'سداد أصل التمويل': 'سداد السنة وفق الخطة والتسويات',
      'الرصيد الختامي': 'افتتاحي + سحب − سداد'
    },
    fundFeeScheduleTable: {
      'أتعاب الإدارة': 'الأساس × النسبة × معامل النمو × كسر السنة',
      'الأتعاب الإضافية': 'مجموع البنود النشطة في السنة',
      'أتعاب التخارج': 'أساس التخارج × النسبة عند وجود قيمة تخارج',
      'حافز الأداء': 'في سنة الاحتساب فقط',
      'إجمالي أتعاب الصندوق': 'مجموع الأعمدة الأربعة'
    }
  };

  /* Arabic meaning for the variables the expressions are built from, so the
     editor reads like the formula instead of raw code. */
  const VAR_LABELS = {
    costTotal: 'إجمالي التكاليف', developerCost: 'أتعاب المطور', developerBaseAmount: 'أساس المطور',
    externalCost: 'البنود الخارجية', landCostIncluded: 'الأرض الداخلة في التكلفة',
    projectCost: 'تكلفة المشروع قبل التمويل', totalFinanceCost: 'إجمالي تكلفة التمويل',
    arrangementFee: 'رسوم ترتيب التمويل', totalFinanceInterest: 'إجمالي فوائد التمويل',
    projectCostWithFinance: 'تكلفة المشروع شامل التمويل', adjustedProjectCost: 'إجمالي تكلفة الاستثمار',
    totalFundFees: 'إجمالي أتعاب الصندوق', totalFundManagementFees: 'أتعاب الإدارة',
    totalAdditionalFundFees: 'الأتعاب الإضافية', fundExitFeeTotal: 'أتعاب التخارج',
    performanceFeeTotal: 'حافز الأداء', operatingRevenue: 'إيرادات التشغيل',
    opexAnnual: 'المصروفات السنوية', annualLandRent: 'إيجار الأرض السنوي', noi: 'صافي الدخل التشغيلي',
    revenueY1: 'إيراد أول سنة تشغيل', opexY1: 'مصروفات أول سنة', noiY1: 'NOI أول سنة',
    saleRevenue: 'إيرادات البيع', saleExitNet: 'صافي التخارج البيعي', operatingExitNet: 'صافي التخارج التشغيلي',
    saleExitGross: 'إجمالي التخارج البيعي', operatingExitGross: 'إجمالي التخارج التشغيلي',
    terminal: 'إجمالي صافي التخارج', facilityAmount: 'قيمة التسهيل', financeBaseAmount: 'أساس التمويل',
    landValue: 'قيمة الأرض', landArea: 'مساحة الأرض', coverageRate: 'نسبة التغطية',
    builtUpAreaAbove: 'مسطحات فوق الأرض', basementArea: 'مساحة البدرومات', totalBuiltUpArea: 'إجمالي المسطحات',
    coveredArea: 'المساحة المغطاة', openArea: 'المساحات المفتوحة',
    developmentYears: 'سنوات التطوير', operationYears: 'سنوات التشغيل', salesYears: 'سنوات البيع',
    totalYears: 'إجمالي سنوات المشروع', roiInflows: 'إجمالي التدفقات الداخلة', roiOutflows: 'إجمالي التدفقات الخارجة',
    roi: 'العائد ROI', totalCashEquity: 'الضخ النقدي', landEquityContribution: 'مساهمة الأرض العينية',
    totalEquityRequired: 'إجمالي حقوق الملكية', leasable: 'المساحة التأجيرية',
    fullOccupancyRevenue: 'إيراد الإشغال الكامل', fullOccupancyOpex: 'مصروفات الإشغال الكامل',
    fullOccupancyNOI: 'NOI الإشغال الكامل', fullBaseAnnual: 'قاعدة الإيراد الكاملة',
    graceDiscount: 'خصم السماح', revenueBase: 'قاعدة الإيرادات', executionCost: 'تكلفة التنفيذ',
    projectIrr: 'IRR المشروع', irrVal: 'IRR حقوق الملكية', payback: 'فترة الاسترداد',
    equityPayback: 'استرداد حقوق الملكية', designCostTotal: 'إجمالي التصميم',
    servicesCostTotal: 'إجمالي الخدمات', advertisingCostTotal: 'إجمالي الدعاية'
  };

  /* ---------- helpers ---------- */
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const status = t => { const el = $('finlab-status'); if (el) el.textContent = t; };
  const showErr = t => { const el = $('finlab-error'); if (el) { el.textContent = t || ''; el.style.display = t ? 'block' : 'none'; } };

  function compileSource(src) {
    // Sloppy indirect eval: function declarations rebind the file's globals in
    // place (the lab's patched copy becomes live), while top-level const/let stay
    // inside this eval's own environment — so re-evaluating never clashes with
    // the script-loaded copy and carries no stale lexical state between patches.
    (0, eval)(src + '\n//# sourceURL=09-financial.js');
  }

  /* ---------- write tracing ---------- */
  const WRITE_TARGETS = [
    [Node.prototype, 'textContent'],
    [Element.prototype, 'innerHTML'],
    [HTMLInputElement.prototype, 'value'],
    [HTMLSelectElement.prototype, 'value'],
    [HTMLTextAreaElement.prototype, 'value']
  ];

  function writerFrame(stack) {
    const skip = new Set(['setTxt', 'setVal', 'setHtml', 'setText', 'recordWrite', 'writerFrame', 'set', 'Object.set']);
    for (const line of String(stack || '').split('\n').slice(1)) {
      const pos = line.match(/<anonymous>:(\d+):(\d+)/) || line.match(/>\s*eval:(\d+):(\d+)/) || line.match(/09-financial\.js:(\d+):(\d+)/);
      if (!pos) continue;
      const fn = (line.match(/at\s+(?:new\s+)?([\w$.]+)\s*\(/) || [])[1] || '';
      if (skip.has(fn)) continue;
      return { line: +pos[1], col: +pos[2], fn };
    }
    return null;
  }

  function recordWrite(el, prop) {
    if (!state.tracing || !state.section || !state.section.contains(el)) return;
    const frame = writerFrame(new Error().stack);
    if (!frame) return;
    state.trace.set(el, { ...frame, prop });
    el.setAttribute('data-finlab-traced', '1');
  }

  function wrapSetters() {
    if (state.settersWrapped) return;
    state.settersWrapped = true;
    for (const [proto, prop] of WRITE_TARGETS) {
      const desc = Object.getOwnPropertyDescriptor(proto, prop);
      if (!desc || !desc.set) continue;
      Object.defineProperty(proto, prop, {
        configurable: true, enumerable: desc.enumerable, get: desc.get,
        set(v) { recordWrite(this, prop); return desc.set.call(this, v); }
      });
    }
  }

  function tracedRecalc() {
    state.tracing = true;
    try { window.calculateAll(); } finally { state.tracing = false; }
  }

  /* ---------- diff snapshot ---------- */
  function pathFor(el) {
    const parts = [];
    let cur = el;
    while (cur && cur !== state.section && cur.nodeType === 1) {
      let p = cur.tagName.toLowerCase();
      if (cur.id) { p += '#' + cur.id; parts.unshift(p); break; }
      const field = cur.getAttribute && cur.getAttribute('data-field');
      if (field) p += `[data-field="${field}"]`;
      else if (cur.className && typeof cur.className === 'string') {
        const cls = cur.className.trim().split(/\s+/).slice(0, 2).join('.');
        if (cls) p += '.' + cls;
      }
      const parent = cur.parentElement;
      if (parent) {
        const same = [...parent.children].filter(c => c.tagName === cur.tagName);
        if (same.length > 1) p += `:nth-of-type(${same.indexOf(cur) + 1})`;
      }
      parts.unshift(p);
      cur = parent;
    }
    return parts.join('>');
  }

  function labelFor(el) {
    if (el.id && FORMULA_BY_ID[el.id]) {
      const card = el.closest('.metric');
      const cardTitle = card ? card.querySelector('span')?.textContent.trim() : '';
      return cardTitle || el.id;
    }
    const td = el.closest('td,th');
    if (td) {
      const tr = td.closest('tr');
      const rowName = tr?.querySelector('[data-field="name"] input')?.value?.trim() || tr?.cells?.[0]?.textContent?.trim() || '';
      const th = td.closest('table')?.querySelector('thead tr')?.cells?.[td.cellIndex]?.textContent?.trim() || '';
      return [rowName, th].filter(Boolean).join(' — ') || td.textContent.trim().slice(0, 40);
    }
    const wrap = el.closest('div');
    const lab = wrap?.querySelector(':scope > label')?.textContent?.trim();
    if (lab) return lab;
    const metric = el.closest('.metric');
    if (metric) return metric.querySelector('span')?.textContent?.trim() || el.id;
    return el.id || el.tagName;
  }

  function formulaFor(el) {
    if (el.id && FORMULA_BY_ID[el.id]) return FORMULA_BY_ID[el.id];
    for (const cls in FORMULA_BY_CLASS) {
      if (el.classList && el.classList.contains(cls)) return FORMULA_BY_CLASS[cls];
      const c = el.closest && el.closest('.' + cls);
      if (c) return FORMULA_BY_CLASS[cls];
    }
    const td = el.closest('td');
    const table = el.closest('table');
    if (td && table && FORMULA_BY_HEADER[table.id]) {
      const th = table.querySelector('thead tr')?.cells?.[td.cellIndex]?.textContent?.trim();
      const f = FORMULA_BY_HEADER[table.id][th];
      if (f) return { f, code: [] };
    }
    return null;
  }

  function snapshotSection() {
    const snap = new Map();
    if (!state.section) return snap;
    state.section.querySelectorAll('input,select,textarea,td,th,strong,small,span.help,span.formula').forEach(el => {
      const key = pathFor(el);
      const value = el.matches('input,select,textarea') ? (el.value ?? '') : (el.textContent ?? '');
      snap.set(key, { value: String(value), label: labelFor(el) });
    });
    return snap;
  }

  function diffSnapshots(before, after) {
    const out = [];
    after.forEach((v, key) => {
      const b = before.get(key);
      if (b && b.value !== v.value) out.push({ label: v.label || b.label, before: b.value, after: v.value });
    });
    return out;
  }

  /* ---------- source editing ---------- */
  function sourceLines() { return state.source.split('\n'); }

  /* ---------- expression editing ----------
     A metric's write line is e.g. setTxt('resNOIY1', money(noiY1)) — the formula
     itself lives where the variable was assigned. resolveExpression walks that
     chain (noiY1 = noi  ->  noi = operatingRevenue - opexAnnual - landRent) and
     hands the panel just the right-hand expression to edit. */
  function varAssignedAt(lineText, varName) {
    const re = new RegExp('\\b' + varName.replace(/[$]/g, '\\$&') + '\\s*=', 'g');
    let m;
    while ((m = re.exec(lineText))) {
      const eq = m.index + m[0].length - 1;
      const before = lineText[eq - 1] || '';
      const after = lineText[eq + 1] || '';
      if ('=!<>+-*/%&|^'.includes(before) || after === '=' || after === '>') continue;
      return m.index + m[0].length;
    }
    return -1;
  }

  function exprEndAt(lineText, start) {
    let depth = 0, quote = null;
    for (let i = start; i < lineText.length; i++) {
      const c = lineText[i];
      if (quote) { if (c === quote && lineText[i - 1] !== '\\') quote = null; continue; }
      if (c === '"' || c === "'" || c === '`') { quote = c; continue; }
      if (c === '(' || c === '[' || c === '{') depth++;
      else if (c === ')' || c === ']' || c === '}') depth--;
      else if (depth === 0 && c === ';') return i;
      else if (depth === 0 && c === ',') {
        if (/^\s*[\w$]+\s*=/.test(lineText.slice(i + 1))) return i;
      }
    }
    return lineText.length;
  }

  function findAssignment(varName, beforeLine, hintLines) {
    const lines = sourceLines();
    const order = [...(hintLines || []), ...Array.from({ length: Math.min(beforeLine, lines.length) }, (_, i) => beforeLine - i)];
    for (const n of order) {
      if (n < 1 || n > lines.length) continue;
      const text = lines[n - 1];
      const start = varAssignedAt(text, varName);
      if (start === -1) continue;
      const end = exprEndAt(text, start);
      return { line: n, start, end, varName, expr: text.slice(start, end).trim() };
    }
    return null;
  }

  function resolveExpression(el) {
    const info = state.trace.get(el);
    if (!info) return null;
    const lines = sourceLines();
    const writeText = lines[info.line - 1] || '';
    const call = writeText.match(/(?:setTxt|setVal|setHtml|setText)\([^,]+,\s*(?:\w+\()?([\w$]+)/);
    const dict = el.id ? FORMULA_BY_ID[el.id] : null;
    let target = call && call[1];
    if (!target) {
      // Not a setTxt line — offer the line itself if it is a plain assignment.
      const assign = writeText.match(/([\w$]+)\s*=/);
      if (assign) target = assign[1];
    }
    if (!target) return null;
    for (let hop = 0; hop < 4 && target; hop++) {
      const found = findAssignment(target, info.line, dict ? dict.code : null);
      if (!found) return hop ? found : null;
      if (/^[\w$]+$/.test(found.expr)) { target = found.expr; continue; }  // alias: follow it
      return found;
    }
    return null;
  }

  function collectVars() {
    const names = new Set();
    const re = /(?:const|let|var)\s+([\w$]+)\s*=/g;
    for (const line of sourceLines()) { let m; while ((m = re.exec(line))) names.add(m[1]); }
    return [...names];
  }

  function varLabel(name) { return VAR_LABELS[name] || ''; }

  function renderVarChips(expr) {
    const box = $('finlab-vars');
    if (!box) return;
    const ids = [...new Set(expr.match(/[\w$]+/g) || [])]
      .filter(w => !/^\d/.test(w) && !['const', 'let', 'var', 'Math', 'null', 'true', 'false', 'undefined'].includes(w));
    box.innerHTML = ids.map(w =>
      `<button type="button" class="finlab-var" data-var="${esc(w)}" title="${esc(varLabel(w) || w)}">${esc(varLabel(w) || w)}</button>`
    ).join('');
    box.querySelectorAll('[data-var]').forEach(b => b.addEventListener('click', () => {
      insertAtCursor($('finlab-expr'), b.dataset.var);
    }));
  }

  function fillVarPicker() {
    const sel = $('finlab-var-add');
    if (!sel || sel.options.length > 1) return;
    const vars = collectVars().sort((a, b) => (varLabel(a) ? 0 : 1) - (varLabel(b) ? 0 : 1) || a.localeCompare(b));
    sel.innerHTML = '<option value="">— متغيرات النموذج —</option>' + vars.map(v =>
      `<option value="${esc(v)}">${esc(varLabel(v) ? varLabel(v) + ' (' + v + ')' : v)}</option>`).join('');
  }

  function insertAtCursor(area, text) {
    const s = area.selectionStart ?? area.value.length, e = area.selectionEnd ?? s;
    area.value = area.value.slice(0, s) + text + area.value.slice(e);
    area.selectionStart = area.selectionEnd = s + text.length;
    area.focus();
  }

  function showExpression(res) {
    const block = $('finlab-expr-block');
    if (!block) return;
    if (!res) { block.style.display = 'none'; return; }
    block.style.display = 'block';
    $('finlab-expr-varname').textContent = (varLabel(res.varName) ? varLabel(res.varName) + ' — ' : '') + res.varName + ' (سطر ' + res.line + ')';
    $('finlab-expr').value = res.expr;
    renderVarChips(res.expr);
    state.exprTarget = res;
  }

  function applyExpression() {
    const res = state.exprTarget;
    if (!res) return;
    const lines = sourceLines();
    let text = lines[res.line - 1] || '';
    if (text.slice(res.start, res.end).trim() !== res.expr) {
      // Line drifted since selection — re-resolve against the current source.
      const fresh = findAssignment(res.varName, res.line + 1, null);
      if (!fresh) { showErr('تغيّر سطر المعادلة — حدّد الناتج من جديد'); return; }
      Object.assign(res, fresh);
      text = lines[res.line - 1] || '';
    }
    const start = varAssignedAt(text, res.varName);
    if (start === -1) { showErr('تعذر تحديد المعادلة في السطر'); return; }
    const end = exprEndAt(text, start);
    const nextExpr = $('finlab-expr').value;
    lines[res.line - 1] = text.slice(0, start) + nextExpr + text.slice(end);
    const next = lines.join('\n');
    const before = snapshotSection();
    try {
      compileSource(next);
    } catch (err) {
      showErr('خطأ في المعادلة — لم تُطبَّق: ' + err.message);
      return;
    }
    state.edits.push(state.source);
    state.source = next;
    try { tracedRecalc(); } catch (err) { showErr('المعادلة طُبّقت لكن الحساب فشل: ' + err.message); }
    renderDiff(diffSnapshots(before, snapshotSection()));
    renderEdits();
    refreshSelection();
    status('مصدر معدّل — ' + state.edits.length + ' تعديل');
    showErr('');
  }

  function applyEdit() {
    const from = Math.max(1, parseInt($('finlab-from')?.value, 10) || 0);
    const to = Math.max(from, parseInt($('finlab-to')?.value, 10) || from);
    const lines = sourceLines();
    if (from > lines.length) { showErr('رقم السطر خارج نطاق الملف'); return; }
    const newText = $('finlab-editor').value;
    const next = lines.slice(0, from - 1).concat(newText.split('\n'), lines.slice(to)).join('\n');
    const before = snapshotSection();
    try {
      compileSource(next);
    } catch (err) {
      showErr('خطأ في الصياغة — لم يُطبَّق التعديل: ' + err.message);
      return;
    }
    state.edits.push(state.source);
    state.source = next;
    try {
      tracedRecalc();
    } catch (err) {
      showErr('التعديل طُبّق لكن الحساب فشل: ' + err.message);
    }
    renderDiff(diffSnapshots(before, snapshotSection()));
    renderEdits();
    refreshSelection();
    status('مصدر معدّل — ' + state.edits.length + ' تعديل');
    showErr('');
  }

  function undoEdit() {
    if (!state.edits.length) return;
    const before = snapshotSection();
    state.source = state.edits.pop();
    compileSource(state.source);
    try { tracedRecalc(); } catch (e) { /* keep going */ }
    renderDiff(diffSnapshots(before, snapshotSection()));
    renderEdits();
    refreshSelection();
    status(state.edits.length ? ('مصدر معدّل — ' + state.edits.length + ' تعديل') : 'المصدر الأصلي');
  }

  function resetAll() {
    if (!state.original) return;
    const before = snapshotSection();
    state.source = state.original;
    state.edits = [];
    compileSource(state.source);
    try { tracedRecalc(); } catch (e) { /* keep going */ }
    renderDiff(diffSnapshots(before, snapshotSection()));
    renderEdits();
    refreshSelection();
    status('المصدر الأصلي');
    showErr('');
  }

  function loadRange(from, to) {
    const lines = sourceLines();
    $('finlab-from').value = from;
    $('finlab-to').value = to;
    $('finlab-editor').value = lines.slice(from - 1, to).join('\n');
  }

  function renderDiff(items) {
    const box = $('finlab-diff');
    if (!box) return;
    if (!items.length) { box.innerHTML = '<p class="finlab-empty">لا توجد أرقام تغيّرت</p>'; return; }
    box.innerHTML = '<table class="finlab-diff-table"><tbody>' + items.map(d =>
      `<tr><td>${esc(d.label)}</td><td class="finlab-old">${esc(d.before)}</td><td class="finlab-arrow">إلى</td><td class="finlab-new">${esc(d.after)}</td></tr>`
    ).join('') + '</tbody></table>';
  }

  function renderEdits() {
    const box = $('finlab-edits');
    if (!box) return;
    box.innerHTML = state.edits.length
      ? '<span>' + state.edits.length + ' تعديل مطبق على المصدر في الذاكرة</span>'
      : '<span class="finlab-empty">لا تعديلات — المصدر كما هو على القرص</span>';
  }

  /* ---------- inspector ---------- */
  function findTraced(el) {
    let cur = el;
    while (cur && cur !== state.section) {
      if (state.trace.has(cur)) return cur;
      cur = cur.parentElement;
    }
    return null;
  }

  function selectElement(el) {
    const traced = findTraced(el);
    if (!traced) return;
    const info = state.trace.get(traced);
    const label = labelFor(traced);
    const value = traced.matches && traced.matches('input,select,textarea') ? traced.value : traced.textContent;
    const dict = formulaFor(traced);
    $('finlab-sel-label').textContent = label || '—';
    $('finlab-sel-value').textContent = String(value ?? '').trim() || '—';
    $('finlab-sel-formula').textContent = dict ? dict.f : '—';
    $('finlab-sel-line').textContent = (info.fn || 'دالة') + ' — سطر ' + info.line;
    const lines = sourceLines();
    $('finlab-sel-code').textContent = lines.slice(Math.max(0, info.line - 2), Math.min(lines.length, info.line + 1))
      .map((l, i) => (Math.max(1, info.line - 1) + i) + ' | ' + l).join('\n');
    loadRange(info.line, info.line);
    showExpression(resolveExpression(traced));
    state.selected = traced;
    const list = $('finlab-sel-codelines');
    if (list) {
      const code = (dict && dict.code) || [];
      list.innerHTML = code.length
        ? 'سطور الحساب: ' + code.map(n => `<button type="button" class="finlab-link" data-line="${n}">${n}</button>`).join(' ')
        : '';
      list.querySelectorAll('[data-line]').forEach(b => b.addEventListener('click', () => loadRange(+b.dataset.line, +b.dataset.line)));
    }
  }

  function refreshSelection() { if (state.selected && document.contains(state.selected)) selectElement(state.selected); }

  function hookInspector() {
    state.section.addEventListener('mouseover', e => {
      if (!state.inspectOn) return;
      const t = findTraced(e.target);
      if (t) t.classList.add('finlab-hover');
    });
    state.section.addEventListener('mouseout', e => {
      const t = findTraced(e.target);
      if (t) t.classList.remove('finlab-hover');
    });
    state.section.addEventListener('click', e => {
      if (!state.inspectOn) return;
      const t = findTraced(e.target);
      if (!t) return;
      e.preventDefault(); e.stopPropagation();
      selectElement(t);
    }, true);
    // Rows bound before a patch still hold the old function object; this delegated
    // re-run makes the patched calculateAll the last writer on every input event.
    state.section.addEventListener('input', () => {
      if (state.ready) Promise.resolve().then(() => { try { window.calculateAll(); } catch (e) { /* surfaced in panel */ } });
    });
    state.section.addEventListener('change', () => {
      if (state.ready) Promise.resolve().then(() => { try { window.calculateAll(); } catch (e) { /* ignore */ } });
    });
  }

  /* ---------- export ---------- */
  function downloadSource() {
    const blob = new Blob([state.source], { type: 'text/javascript;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '09-financial.js';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  async function saveToProject() {
    try {
      const data = await api('POST', APPLY_URL, { source: state.source });
      if (data && data.ok) status('تم الحفظ في assets/js/09-financial.js');
      else showErr('تعذر الحفظ: ' + ((data && data.error) || 'خطأ غير معروف'));
    } catch (err) {
      showErr('تعذر الحفظ: ' + err.message);
    }
  }

  /* ---------- draft loading (frame mode) ---------- */
  async function loadDraftList() {
    const sel = $('finlab-draft');
    if (!sel || typeof api !== 'function') return;
    const data = await api('GET', '/api/project-drafts').catch(() => null);
    const list = (data && (data.drafts || data.items || data.projects)) || [];
    sel.innerHTML = '<option value="">— دراسة فارغة —</option>' + list.map(d => {
      const id = d.id || d.draft_id;
      const name = d.project_name || d.name || d.title || ('مسودة ' + id);
      return `<option value="${esc(id)}">${esc(name)}</option>`;
    }).join('');
  }

  async function loadDraft(id) {
    if (!id || typeof api !== 'function') return;
    const data = await api('GET', '/api/project-draft/' + encodeURIComponent(id)).catch(() => null);
    const draft = data && (data.draft || data.project || data);
    const model = draft && (draft.financial_study_model || draft.draft_data?.financial_study_model || draft.data?.financial_study_model);
    if (!model) { showErr('المسودة لا تحمل دراسة مالية محفوظة'); return; }
    if (typeof hydrateFinancialStudyModel === 'function') {
      window.__batchLoading = true;
      try { hydrateFinancialStudyModel(typeof model === 'string' ? model : JSON.stringify(model)); }
      finally { window.__batchLoading = false; }
      try { tracedRecalc(); } catch (e) { /* keep going */ }
      status('مسودة محمّلة');
      showErr('');
    }
  }

  /* ---------- UI ---------- */
  function injectStyle() {
    if ($('finlab-style')) return;
    const st = document.createElement('style');
    st.id = 'finlab-style';
    st.textContent = `
      .finlab-launch{position:fixed;bottom:18px;inset-inline-start:18px;z-index:60000;padding:10px 18px;border:0;border-radius:10px;background:#1f2937;color:#fff;font:700 13px inherit;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.25)}
      .finlab-topbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 14px;background:#111827;color:#fff;position:sticky;top:0;z-index:50}
      .finlab-topbar strong{font-size:14px}
      .finlab-topbar select,.finlab-topbar button{font:12px inherit;padding:6px 10px;border-radius:8px;border:1px solid #374151;background:#1f2937;color:#fff;cursor:pointer}
      .finlab-topbar select{min-width:200px;background:#fff;color:#111}
      .finlab-panel{position:fixed;top:0;bottom:0;inset-inline-end:0;width:470px;max-width:94vw;background:#fff;color:#111;z-index:60001;box-shadow:-6px 0 24px rgba(0,0,0,.18);overflow-y:auto;padding:14px;font-size:13px;display:none}
      .finlab-panel.open{display:block}
      .finlab-panel h4{margin:14px 0 6px;font-size:12.5px}
      .finlab-head{display:flex;align-items:center;justify-content:space-between;gap:8px}
      .finlab-head strong{font-size:14px}
      .finlab-btn{padding:6px 12px;border-radius:8px;border:1px solid #d1d5db;background:#f9fafb;cursor:pointer;font:600 12px inherit}
      .finlab-btn.primary{background:#1f2937;color:#fff;border-color:#1f2937}
      .finlab-btn.danger{background:#fef2f2;color:#b91c1c;border-color:#fecaca}
      .finlab-kv{display:flex;gap:8px;margin:4px 0}
      .finlab-kv span{color:#6b7280;min-width:92px}
      .finlab-kv b{font-weight:600;word-break:break-word}
      .finlab-code{direction:ltr;text-align:left;background:#0f172a;color:#e2e8f0;border-radius:8px;padding:8px;font:11px/1.6 Consolas,monospace;white-space:pre;overflow-x:auto;margin-top:6px}
      #finlab-editor{width:100%;min-height:150px;direction:ltr;text-align:left;font:12px/1.5 Consolas,monospace;border:1px solid #d1d5db;border-radius:8px;padding:8px;box-sizing:border-box}
      .finlab-range{display:flex;align-items:center;gap:6px;margin-bottom:6px}
      .finlab-range input{width:64px;padding:4px 6px;border:1px solid #d1d5db;border-radius:6px;font:12px inherit}
      .finlab-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
      .finlab-error{display:none;background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;border-radius:8px;padding:8px;margin-top:8px;font-size:12px;direction:ltr;text-align:left}
      .finlab-empty{color:#9ca3af;font-size:12px}
      .finlab-diff-table{width:100%;border-collapse:collapse;font-size:12px}
      .finlab-diff-table td{border-bottom:1px solid #f3f4f6;padding:4px 6px;vertical-align:top}
      .finlab-old{color:#b91c1c;text-decoration:line-through}
      .finlab-new{color:#047857;font-weight:700}
      .finlab-arrow{color:#9ca3af}
      .finlab-hover{outline:2px solid #f59e0b !important;outline-offset:1px;cursor:pointer}
      [data-finlab-traced]{transition:outline .1s}
      .finlab-link{border:0;background:none;color:#2563eb;cursor:pointer;font:600 12px inherit;text-decoration:underline;padding:0 2px}
      .finlab-block{border:1px solid #e5e7eb;border-radius:10px;padding:10px;margin-top:10px}
      .finlab-vars{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0}
      .finlab-var{border:1px solid #c7d2fe;background:#eef2ff;color:#3730a3;border-radius:14px;padding:2px 10px;font:600 11px inherit;cursor:pointer}
      #finlabStudyHost{padding:18px}
      .finlab-frame-body{margin:0;background:#f3f4f6}
    `;
    document.head.appendChild(st);
  }

  function buildPanel() {
    if ($('finlab-panel')) return;
    const panel = document.createElement('div');
    panel.id = 'finlab-panel';
    panel.className = 'finlab-panel';
    panel.dir = 'rtl';
    panel.innerHTML = `
      <div class="finlab-head">
        <strong>معمل الدراسة المالية</strong>
        <button type="button" class="finlab-btn" id="finlab-close">إغلاق</button>
      </div>
      <div style="margin:8px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <label><input type="checkbox" id="finlab-inspect"> تتبّع مصدر كل ناتج عند تحديده</label>
        <span id="finlab-status" class="finlab-empty"></span>
      </div>
      <div class="finlab-block">
        <select id="finlab-pick" style="width:100%;padding:6px;border:1px solid #d1d5db;border-radius:8px;font:12px inherit"></select>
        <div class="finlab-kv" style="margin-top:8px"><span>الخانة</span><b id="finlab-sel-label">—</b></div>
        <div class="finlab-kv"><span>القيمة الحالية</span><b id="finlab-sel-value">—</b></div>
        <div class="finlab-kv"><span>المعادلة</span><b id="finlab-sel-formula">—</b></div>
        <div class="finlab-kv"><span>المصدر</span><b id="finlab-sel-line">—</b></div>
        <div id="finlab-sel-codelines" style="margin-top:4px"></div>
        <div id="finlab-sel-code" class="finlab-code">—</div>
      </div>
      <div class="finlab-block" id="finlab-expr-block" style="display:none">
        <h4>المعادلة</h4>
        <div class="finlab-kv"><span>المتغير</span><b id="finlab-expr-varname"></b></div>
        <textarea id="finlab-expr" spellcheck="false" style="width:100%;min-height:56px;direction:ltr;text-align:left;font:12px/1.5 Consolas,monospace;border:1px solid #d1d5db;border-radius:8px;padding:8px;box-sizing:border-box"></textarea>
        <div id="finlab-vars" class="finlab-vars"></div>
        <div class="finlab-range"><select id="finlab-var-add" style="flex:1;padding:4px;border:1px solid #d1d5db;border-radius:6px;font:12px inherit"></select></div>
        <div class="finlab-actions">
          <button type="button" class="finlab-btn primary" id="finlab-expr-apply">تطبيق المعادلة</button>
        </div>
      </div>
      <div class="finlab-block">
        <h4>محرر المصدر (متقدم)</h4>
        <div class="finlab-range">من سطر <input id="finlab-from" type="number" min="1"> إلى سطر <input id="finlab-to" type="number" min="1"> <button type="button" class="finlab-btn" id="finlab-load-range">عرض النطاق</button></div>
        <textarea id="finlab-editor" spellcheck="false"></textarea>
        <div class="finlab-actions">
          <button type="button" class="finlab-btn primary" id="finlab-apply">تطبيق التعديل</button>
          <button type="button" class="finlab-btn" id="finlab-undo">تراجع عن آخر تعديل</button>
          <button type="button" class="finlab-btn danger" id="finlab-reset">إعادة تعيين الكل</button>
        </div>
        <div id="finlab-error" class="finlab-error"></div>
      </div>
      <div class="finlab-block">
        <h4>الأرقام التي تغيّرت بعد آخر تعديل</h4>
        <div id="finlab-diff"><p class="finlab-empty">لا توجد أرقام تغيّرت</p></div>
      </div>
      <div class="finlab-block">
        <h4>حالة المصدر</h4>
        <div id="finlab-edits"><span class="finlab-empty">لا تعديلات — المصدر كما هو على القرص</span></div>
        <div class="finlab-actions">
          <button type="button" class="finlab-btn" id="finlab-recalc">إعادة الحساب والتتبع</button>
          <button type="button" class="finlab-btn" id="finlab-download">تنزيل الملف المعدّل</button>
          <button type="button" class="finlab-btn primary" id="finlab-save">حفظ داخل ملف المشروع</button>
        </div>
      </div>`;
    document.body.appendChild(panel);

    $('finlab-close').addEventListener('click', () => panel.classList.remove('open'));
    $('finlab-inspect').addEventListener('change', e => { state.inspectOn = e.target.checked; });
    $('finlab-apply').addEventListener('click', applyEdit);
    $('finlab-undo').addEventListener('click', undoEdit);
    $('finlab-reset').addEventListener('click', resetAll);
    $('finlab-recalc').addEventListener('click', () => { try { tracedRecalc(); refreshSelection(); } catch (e) { showErr(e.message); } });
    $('finlab-download').addEventListener('click', downloadSource);
    $('finlab-save').addEventListener('click', saveToProject);
    $('finlab-load-range').addEventListener('click', () => {
      const from = Math.max(1, parseInt($('finlab-from').value, 10) || 1);
      const to = Math.max(from, parseInt($('finlab-to').value, 10) || from);
      loadRange(from, to);
    });
    $('finlab-expr-apply').addEventListener('click', applyExpression);
    $('finlab-expr').addEventListener('input', e => renderVarChips(e.target.value));
    $('finlab-var-add').addEventListener('change', e => {
      if (e.target.value) insertAtCursor($('finlab-expr'), e.target.value);
      e.target.value = '';
    });
    $('finlab-pick').addEventListener('change', e => {
      const el = state.pickList && state.pickList[+e.target.value];
      if (el) selectElement(el);
    });
  }

  function fillOutputPicker() {
    const sel = $('finlab-pick');
    if (!sel || !state.section) return;
    const seen = new Map();
    state.section.querySelectorAll('[data-finlab-traced]').forEach(el => {
      const key = pathFor(el);
      if (!seen.has(key)) seen.set(key, el);
    });
    state.pickList = [...seen.values()];
    sel.innerHTML = '<option value="">— النواتج المحسوبة —</option>' +
      state.pickList.map((el, i) => `<option value="${i}">${esc(labelFor(el))}</option>`).join('');
  }

  function buildLauncher() {
    if ($('finlab-launch')) return;
    const b = document.createElement('button');
    b.id = 'finlab-launch';
    b.className = 'finlab-launch';
    b.type = 'button';
    b.textContent = 'معمل المعادلات';
    b.addEventListener('click', () => { const p = $('finlab-panel'); if (p) p.classList.toggle('open'); });
    document.body.appendChild(b);
  }

  /* ---------- engine attach ---------- */
  async function attachEngine() {
    if (!state.section) return;
    status('تحميل المصدر…');
    if (!state.original) {
      const res = await fetch(SOURCE_URL, { cache: 'no-store' });
      if (!res.ok) { status('تعذر تحميل المصدر'); return; }
      state.original = state.source = await res.text();
    }
    try {
      compileSource(state.source);
    } catch (err) {
      status('فشل تقييم المصدر: ' + err.message);
      return;
    }
    wrapSetters();
    try { tracedRecalc(); } catch (e) { showErr('الحساب الأول فشل: ' + e.message); }
    if (!state.listenersHooked) { state.listenersHooked = true; hookInspector(); }
    state.ready = true;
    fillOutputPicker();
    fillVarPicker();
    status('جاهز');
    renderEdits();
  }

  function waitForSection(cb) {
    const found = document.getElementById(SECTION_ID);
    if (found) return cb(found);
    const timer = setInterval(() => {
      const s = document.getElementById(SECTION_ID);
      if (s) { clearInterval(timer); cb(s); }
    }, 700);
  }

  /* ---------- frame mode ---------- */
  function bootFrame() {
    injectStyle();
    buildPanel();
    const bar = document.createElement('div');
    bar.className = 'finlab-topbar';
    bar.innerHTML = '<strong>معمل الدراسة المالية</strong>' +
      '<select id="finlab-draft" title="مسودة"></select>' +
      '<button type="button" id="finlab-open-panel">لوحة المعمل</button>' +
      '<span id="finlab-status" class="finlab-empty" style="color:#9ca3af"></span>';
    document.body.prepend(bar);
    $('finlab-open-panel').addEventListener('click', () => $('finlab-panel').classList.add('open'));
    $('finlab-draft').addEventListener('change', e => loadDraft(e.target.value));

    const host = $('finlabStudyHost') || document.body.appendChild(Object.assign(document.createElement('div'), { id: 'finlabStudyHost' }));
    fetch(SOURCE_URL, { cache: 'no-store' }).then(r => r.text()).then(src => {
      state.original = state.source = src;
      compileSource(src);                 // lab copy becomes the live globals before mount
      if (typeof addFinancialCalculations === 'function') addFinancialCalculations(host);
      state.mounted = true;
      waitForSection(s => { state.section = s; attachEngine(); loadDraftList(); });
    }).catch(err => status('فشل التحميل: ' + err.message));
    $('finlab-panel').classList.add('open');
  }

  /* ---------- overlay mode ---------- */
  function bootOverlay() {
    injectStyle();
    buildPanel();
    buildLauncher();
    waitForSection(s => { state.section = s; attachEngine(); });
  }

  function activate() {
    if (state.mode) return;
    const isFrame = document.body && document.body.hasAttribute('data-finlab-frame');
    state.mode = isFrame ? 'frame' : 'overlay';
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => (isFrame ? bootFrame() : bootOverlay()));
    } else {
      isFrame ? bootFrame() : bootOverlay();
    }
  }

  /* ---------- admin page entry ---------- */
  window.openFinlabPage = function () {
    if (typeof showTenantPage === 'function') showTenantPage('tenantFinlabPage');
    const frame = document.getElementById('finlabFrame');
    if (frame && !frame.src) frame.src = frame.dataset.src;
  };

  window.FINLAB = { activate, state };
  if (document.body && document.body.hasAttribute('data-finlab-frame')) activate();
  else if (new URLSearchParams(location.search).has('finlab')) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', activate);
    else activate();
  }
})();
