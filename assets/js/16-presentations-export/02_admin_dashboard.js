    function sagDonut(segments, centerLabel) {
      const r = 56, C = 2 * Math.PI * r, size = 150;
      const total = segments.reduce((a, s) => a + (s.value || 0), 0);
      const go = s => s.key ? ' onclick="sagGoToCompaniesByPlan(\'' + encodeURIComponent(String(s.key)) + '\')"' : '';
      let off = 0, rings = '';
      segments.forEach(s => {
        const len = total ? (s.value / total) * C : 0;
        rings += '<circle class="admin-donut-seg" cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" fill="none" stroke="' + s.color + '" stroke-width="20" ' +
          'stroke-dasharray="' + len.toFixed(1) + ' ' + (C - len).toFixed(1) + '" stroke-dashoffset="' + (-off).toFixed(1) + '" transform="rotate(-90 ' + size / 2 + ' ' + size / 2 + ')"' + go(s) +
          ' onmouseenter="this.setAttribute(\'stroke-width\',\'26\')" onmouseleave="this.setAttribute(\'stroke-width\',\'20\')">' +
          '<title>' + s.label + ': ' + sagFmtNum(s.value) + '</title></circle>';
        off += len;
      });
      const legend = segments.map(s =>
        '<div class="admin-legend-item"' + go(s) + '><span class="admin-legend-dot" style="background:' + s.color + '"></span>' +
        '<span>' + s.label + '</span><strong>' + sagFmtNum(s.value) + '</strong></div>'
      ).join('');
      return '<div class="admin-donut-chart"><svg viewBox="0 0 ' + size + ' ' + size + '" role="img">' +
        '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" fill="none" class="admin-donut-track" stroke-width="20"/>' + rings +
        '<text x="' + size / 2 + '" y="' + (size / 2 - 2) + '" class="admin-donut-total" text-anchor="middle">' + sagFmtNum(total) + '</text>' +
        '<text x="' + size / 2 + '" y="' + (size / 2 + 16) + '" class="admin-donut-sub" text-anchor="middle">' + centerLabel + '</text>' +
        '</svg></div><div class="admin-donut-legend">' + legend + '</div>';
    }

    function sagLegend(el, series) {
      if (!el) return;
      el.innerHTML = series.map(s =>
        '<span class="admin-legend-item"><span class="admin-legend-dot" style="background:' + s.color + '"></span>' + s.name + '</span>'
      ).join('');
    }

    var sagLastChartTrends = null;
    var sagChartRange = { preset: '12', from: '', to: '' };

    function renderSagActivityChart(trends) {
      trends = trends || {};
      sagLastChartTrends = trends;
      const activityEl = document.getElementById('sagActivityChart');
      if (!activityEl) return;
      const labels = trends.labels || [];
      const spendSeries = (trends.ai_spend_sar || trends.ai_spend || []).map((v, i) => v + (((trends.maps_spend_sar || trends.maps_spend) || [])[i] || 0));
      const series = [
        { name: WFT('admin.legend_spend', 'المصروفات'), values: spendSeries, color: 'var(--chart-3)', fmt: sagFmtMoney },
        { name: WFT('admin.legend_companies', 'شركات جديدة'), values: trends.companies || [], color: 'var(--chart-2)', fmt: sagFmtNum },
      ];
      const chart = sagLineChart(labels, series);
      activityEl.innerHTML = labels.length ? chart.svg : '';
      if (labels.length) sagBindChartTooltip(activityEl, labels, series, chart.geom);
      sagLegend(document.getElementById('sagActivityLegend'), series);
      renderSagRangeControls();
    }

    function renderSagRangeControls() {
      const box = document.getElementById('sagActivityRange');
      if (!box) return;
      const presets = [
        { v: '3', t: WFT('admin.range_3m', 'آخر 3 شهور') },
        { v: '6', t: WFT('admin.range_6m', 'آخر 6 شهور') },
        { v: '12', t: WFT('admin.range_12m', 'آخر 12 شهرًا') },
        { v: '24', t: WFT('admin.range_24m', 'آخر سنتين') },
        { v: 'ytd', t: WFT('admin.range_ytd', 'هذه السنة') },
        { v: 'custom', t: WFT('admin.range_custom', 'نطاق مخصص') },
      ];
      box.innerHTML =
        '<select id="sagRangePreset" class="admin-range-select" onchange="sagChartRange.preset=this.value; renderSagRangeControls(); sagApplyChartRange()">' +
        presets.map(p => '<option value="' + p.v + '"' + (sagChartRange.preset === p.v ? ' selected' : '') + '>' + p.t + '</option>').join('') +
        '</select>' +
        '<span class="admin-range-custom" style="display:' + (sagChartRange.preset === 'custom' ? 'inline-flex' : 'none') + '">' +
        '<input type="date" id="sagRangeFromDate" dir="ltr" aria-label="' + escapeHtml(WFT('admin.range_from', 'من')) + '" value="' + escapeHtml(sagChartRange.from.slice(0, 10)) + '" onchange="sagRangeChanged()">' +
        '<input type="time" id="sagRangeFromTime" dir="ltr" aria-label="' + escapeHtml(WFT('admin.range_from_time', 'وقت البداية (اختياري)')) + '" value="' + escapeHtml(sagChartRange.from.slice(11, 16)) + '" onchange="sagRangeChanged()">' +
        '<input type="date" id="sagRangeToDate" dir="ltr" aria-label="' + escapeHtml(WFT('admin.range_to', 'إلى')) + '" value="' + escapeHtml(sagChartRange.to.slice(0, 10)) + '" onchange="sagRangeChanged()">' +
        '<input type="time" id="sagRangeToTime" dir="ltr" aria-label="' + escapeHtml(WFT('admin.range_to_time', 'وقت النهاية (اختياري)')) + '" value="' + escapeHtml(sagChartRange.to.slice(11, 16)) + '" onchange="sagRangeChanged()">' +
        '</span>';
    }

    function sagRangeChanged() {
      const fd = document.getElementById('sagRangeFromDate');
      const ft = document.getElementById('sagRangeFromTime');
      const td = document.getElementById('sagRangeToDate');
      const tt = document.getElementById('sagRangeToTime');
      sagChartRange.from = fd && fd.value ? fd.value + (ft && ft.value ? 'T' + ft.value : '') : '';
      sagChartRange.to = td && td.value ? td.value + (tt && tt.value ? 'T' + tt.value : '') : '';
      sagApplyChartRange();
    }

    async function sagApplyChartRange() {
      const params = new URLSearchParams();
      if (sagChartRange.preset === 'custom') {
        if (!sagChartRange.from || !sagChartRange.to) return;
        params.set('from', sagChartRange.from);
        params.set('to', sagChartRange.to);
      } else if (sagChartRange.preset === 'ytd') {
        params.set('months', String(new Date().getMonth() + 1));
      } else {
        params.set('months', sagChartRange.preset);
      }
      const data = await api('GET', '/api/admin/operational-overview?' + params.toString()).catch(() => null);
      if (data && data.overview) {
        renderSagActivityChart(data.overview.trends || {});
      }
    }

    const SAG_PLAN_COLORS = ['var(--chart-1)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-2)', 'var(--chart-5)', '#8b5cf6', '#0ea5e9', '#f59e0b'];
    const SAG_PLAN_ORDER = ['free', 'pro', 'enterprise'];

    function sagSortedPlans(plans) {
      return plans.slice().sort((a, b) => {
        const ia = SAG_PLAN_ORDER.indexOf(a), ib = SAG_PLAN_ORDER.indexOf(b);
        return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || String(a).localeCompare(String(b));
      });
    }

    function sagPlanLabel(plan) {
      const known = { free: 'Free', pro: 'Pro', enterprise: 'Enterprise' };
      if (known[plan]) return known[plan];
      return String(plan || 'free').replace(/[-_]+/g, ' ');
    }

    async function sagGoToCompaniesByPlan(plan) {
      await openTenantCompanies();
      const sel = document.getElementById('sagFilterPlan');
      if (!sel) return;
      sel.value = decodeURIComponent(plan);
      filterSagTenants();
    }

    function sagSyncPlanFilter() {
      const sel = document.getElementById('sagFilterPlan');
      if (!sel) return;
      const current = sel.value;
      const plans = sagSortedPlans([...new Set(sagAllTenants.map(t => t.plan || 'free'))]);
      sel.innerHTML = '<option value="">' + WFT('admin.filter_all_plans', 'كل الخطط') + '</option>' +
        plans.map(p => '<option value="' + escapeHtml(p) + '">' + escapeHtml(sagPlanLabel(p)) + '</option>').join('');
      if (plans.indexOf(current) !== -1) sel.value = current;
    }

    function renderAdminDashboard(overview) {
      const statsEl = document.getElementById('sagAdminStats');
      const pendingEl = document.getElementById('sagPendingActions');
      const tenants = overview.tenants || {};
      const workflows = overview.workflows || {};
      const trends = overview.trends || {};
      const deltas = overview.deltas || {};
      const spend = overview.spend || {};
      const revenue = overview.revenue || {};
      const spendSeries = (trends.ai_spend_sar || trends.ai_spend || []).map((v, i) => v + (((trends.maps_spend_sar || trends.maps_spend) || [])[i] || 0));

      if (statsEl) {
        const kpis = [
          { label: WFT('admin.kpi_companies', 'إجمالي الشركات'), value: sagFmtNum(tenants.companies != null ? tenants.companies : tenants.total || sagAllTenants.filter(t => !t.isAdmin).length), sub: WFT('admin.kpi_active', '{n} نشطة', { n: sagFmtNum(tenants.active_companies != null ? tenants.active_companies : tenants.active || 0) }), delta: deltas.companies, spark: trends.companies, color: 'var(--chart-1)' },
          { label: WFT('admin.kpi_spend', 'استهلاك الشهر'), value: sagFmtMoney(spend.month_sar != null ? spend.month_sar : spend.month_usd), sub: WFT('admin.kpi_spend_total', 'الإجمالي {n}', { n: sagFmtMoney(spend.total_sar != null ? spend.total_sar : spend.total_usd) }), delta: deltas.spend, spark: spendSeries, color: 'var(--chart-3)' },
          { label: WFT('admin.kpi_revenue', 'إيراد الشحن'), value: sagFmtMoney(revenue.month_sar != null ? revenue.month_sar : revenue.month_usd), sub: WFT('admin.kpi_revenue_total', 'الإجمالي {n}', { n: sagFmtMoney(revenue.total_sar != null ? revenue.total_sar : revenue.total_usd) }), delta: deltas.revenue, spark: trends.revenue_sar || trends.revenue, color: 'var(--chart-5)' },
        ];
        statsEl.innerHTML = kpis.map(k =>
          '<div class="admin-kpi-card">' +
          '<div class="admin-kpi-top"><span class="admin-kpi-label">' + k.label + '</span>' + sagDeltaChip(k.delta) + '</div>' +
          '<div class="admin-kpi-value">' + k.value + '</div>' +
          '<div class="admin-kpi-sub">' + k.sub + '</div>' +
          '<div class="admin-spark">' + sagSparkline(k.spark, k.color) + '</div>' +
          '</div>'
        ).join('');
      }

      renderSagActivityChart(sagLastChartTrends || trends);

      const donutEl = document.getElementById('sagPlanDonut');
      if (donutEl) {
        const planCounts = {};
        sagAllTenants.filter(t => !t.isAdmin).forEach(t => { const p = t.plan || 'free'; planCounts[p] = (planCounts[p] || 0) + 1; });
        const plans = sagSortedPlans(Object.keys(planCounts));
        donutEl.innerHTML = sagDonut(plans.map((p, i) => ({
          key: p,
          label: sagPlanLabel(p),
          value: planCounts[p],
          color: SAG_PLAN_COLORS[i % SAG_PLAN_COLORS.length]
        })), WFT('admin.donut_companies', 'شركة'));
      }

      const ticketEl = document.getElementById('sagTicketBars');
      if (ticketEl) {
        const byStatus = overview.tickets_by_status || {};
        const rows = [
          { key: 'open', label: WFT('support.status_open', 'مفتوحة'), color: 'var(--chart-5)' },
          { key: 'in_progress', label: WFT('support.status_in_progress', 'قيد المعالجة'), color: 'var(--chart-1)' },
          { key: 'waiting_customer', label: WFT('support.status_waiting', 'بانتظار العميل'), color: 'var(--chart-4)' },
          { key: 'resolved', label: WFT('support.status_resolved', 'تم الحل'), color: 'var(--chart-2)' },
          { key: 'closed', label: WFT('support.status_closed', 'مغلقة'), color: 'var(--muted)' },
        ];
        const max = Math.max(1, ...rows.map(r => byStatus[r.key] || 0));
        const total = rows.reduce((a, r) => a + (byStatus[r.key] || 0), 0);
        ticketEl.innerHTML = total === 0 ? '<p class="tenant-hint">' + WFT('admin.no_tickets', 'لا توجد تذاكر') + '</p>' :
          rows.map(r =>
            '<div class="admin-bar-row"><span class="admin-bar-label">' + r.label + '</span>' +
            '<span class="admin-bar-track"><span class="admin-bar-fill" style="width:' + Math.round(((byStatus[r.key] || 0) / max) * 100) + '%;background:' + r.color + '"></span></span>' +
            '<strong>' + (byStatus[r.key] || 0) + '</strong></div>'
          ).join('');
      }

      if (pendingEl) {
        const items = [
          { label: WFT('admin.pending_recharges', 'طلبات شحن بانتظار المراجعة'), count: workflows.pending_recharges || 0, action: 'openAdminRechargePage()' },
          { label: WFT('admin.pending_tickets', 'تذاكر دعم مفتوحة من الشركات'), count: workflows.open_support_tickets || 0, action: 'openAdminTicketsPage()' },
        ];
        pendingEl.innerHTML = items.map(item =>
          '<div class="tenant-presentation-card admin-action-card">' +
          '<div><h3>' + item.label + '</h3>' +
          '<div class="meta"><span class="admin-action-count' + (item.count ? ' has' : '') + '">' + item.count + '</span></div></div>' +
          (item.action ? '<div><button type="button" class="btn small primary" onclick="' + item.action + '">' + WFT('admin.review', 'مراجعة') + '</button></div>' : '') +
          '</div>'
        ).join('');
      }

      renderSagOpsAlerts(overview.alerts || []);
      renderSagReportsPanel();
    }

    // Alert text follows the UI language: the backend sends a stable `kind`
    // plus an Arabic message, so the label resolves through WFT and re-renders
    // on the wf:lang pass like every other dashboard string.
    const SAG_ALERT_LABELS = {
      recharge_sla: ['admin.alert_recharge_sla', 'طلبات شحن تجاوزت مهلة المراجعة ٢٤ ساعة'],
      generation_failures: ['admin.alert_generation_failures', 'مهام توليد فاشلة خلال ٢٤ ساعة'],
      dead_jobs: ['admin.alert_dead_jobs', 'مهام خلفية استنفدت محاولاتها'],

    };

    function renderSagOpsAlerts(alerts) {
      const el = document.getElementById('sagOpsAlerts');
      if (!el) return;
      if (!alerts.length) { el.innerHTML = ''; return; }
      const colors = { critical: '#c33', warning: '#b45309', info: 'var(--p)' };
      el.innerHTML = alerts.map(a => {
        const known = SAG_ALERT_LABELS[a.kind];
        const text = known ? WFT(known[0], known[1]) : (a.message_ar || a.kind);
        return '<div class="tenant-presentation-card" style="border-right:4px solid ' + (colors[a.severity] || 'var(--p)') + '">' +
          '<div><h3>' + escapeHtml(text) + '</h3>' +
          '<div class="meta"><span>' + sagFmtNum(a.count || 0) + '</span></div></div></div>';
      }).join('');
    }

    var sagReportRange = { from: '', to: '' };

    function renderSagReportsPanel() {
      const el = document.getElementById('sagReportsPanel');
      if (!el) return;
      const reports = [
        { key: 'ledger', label: WFT('admin.report_ledger', 'حركات الرصيد') },
        { key: 'tickets', label: WFT('admin.report_tickets', 'تذاكر الدعم') },
      ];
      el.innerHTML =
        '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px">' +
        '<div class="tenant-field"><label for="sagReportFrom">' + WFT('reports.range_from', 'من تاريخ') + '</label>' +
        '<div style="display:flex;gap:6px">' +
        '<input type="date" id="sagReportFrom" dir="ltr" value="' + escapeHtml(sagReportRange.from.slice(0, 10)) + '" onchange="sagReportRangeChanged()">' +
        '<input type="time" id="sagReportFromTime" dir="ltr" aria-label="' + escapeHtml(WFT('admin.range_from_time', 'وقت البداية (اختياري)')) + '" value="' + escapeHtml(sagReportRange.from.slice(11, 16)) + '" onchange="sagReportRangeChanged()"></div></div>' +
        '<div class="tenant-field"><label for="sagReportTo">' + WFT('reports.range_to', 'إلى تاريخ') + '</label>' +
        '<div style="display:flex;gap:6px">' +
        '<input type="date" id="sagReportTo" dir="ltr" value="' + escapeHtml(sagReportRange.to.slice(0, 10)) + '" onchange="sagReportRangeChanged()">' +
        '<input type="time" id="sagReportToTime" dir="ltr" aria-label="' + escapeHtml(WFT('admin.range_to_time', 'وقت النهاية (اختياري)')) + '" value="' + escapeHtml(sagReportRange.to.slice(11, 16)) + '" onchange="sagReportRangeChanged()"></div></div>' +
        '</div>' +
        reports.map(r =>
          '<div class="tenant-presentation-card" style="margin-bottom:8px"><div><h3>' + r.label + '</h3></div>' +
          '<div><button type="button" class="btn small primary" onclick="sagDownloadReport(\'' + r.key + '\')">' +
          WFT('reports.download_pdf', 'تنزيل PDF') + '</button></div></div>'
        ).join('');
    }

    function sagReportRangeChanged() {
      const fd = document.getElementById('sagReportFrom');
      const ft = document.getElementById('sagReportFromTime');
      const td = document.getElementById('sagReportTo');
      const tt = document.getElementById('sagReportToTime');
      sagReportRange.from = fd && fd.value ? fd.value + (ft && ft.value ? 'T' + ft.value : '') : '';
      sagReportRange.to = td && td.value ? td.value + (tt && tt.value ? 'T' + tt.value : '') : '';
    }

    async function sagDownloadReport(name) {
      const token = (typeof getTenantToken === 'function') ? getTenantToken() : null;
      try {
        const params = new URLSearchParams();
        if (sagReportRange.from) params.set('from', sagReportRange.from);
        if (sagReportRange.to) params.set('to', sagReportRange.to);
        const qs = params.toString();
        const res = await fetch('/api/admin/reports/' + encodeURIComponent(name) + (qs ? '?' + qs : ''), {
          headers: token ? { 'Authorization': 'Bearer ' + token } : {}
        });
        if (!res.ok) { toast(WFT('reports.download_failed', 'تعذر تنزيل التقرير')); return; }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = name + '-report.pdf';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
      } catch (e) {
        toast(WFT('reports.download_failed', 'تعذر تنزيل التقرير'));
      }
    }

    async function openTenantCompanies() {
      showTenantPage('tenantCompaniesPage');
      const list = document.getElementById('sagTenantsList');
      showInlineLoader(list, 'جاري التحميل...');
      const tenantsData = await api('GET', '/api/admin/tenants');
      sagAllTenants = (tenantsData.success && tenantsData.tenants) ? tenantsData.tenants : [];
      sagSyncPlanFilter();
      renderSagTenants(sagAllTenants);
    }

    async function sagEnsureAllKeys() {
      const btn = document.getElementById('sagEnsureKeysBtn');
      if (btn) btn.disabled = true;
      showLoader(WFT('admin.keys_issuing', 'جاري إصدار مفاتيح الشركات...'), '', 5);
      try {
        let cleaned = 0;
        try {
          const orphans = await api('GET', '/api/admin/openrouter-keys/orphans');
          if (orphans && orphans.success && orphans.count) {
            const swept = await api('DELETE', '/api/admin/openrouter-keys/orphans', { confirm: true });
            cleaned = (swept && swept.deleted_count) || 0;
          }
        } catch (sweepError) { /* orphan sweep must never block issuance */ }
        let created = 0, failed = 0, rounds = 0, firstError = '';
        let totalKeyless = null, lastKeyless = null, provisionedNames = [];
        const isMeaningfulKeyError = (v) => {
          if (v === undefined || v === null) return false;
          const s = String(v).trim();
          if (!s) return false;
          const low = s.toLowerCase();
          return low !== 'none' && low !== 'null' && low !== 'undefined';
        };
        while (rounds < 40) {
          rounds += 1;
          const data = await api('POST', '/api/admin/openrouter-keys/ensure-all', { batch: 25, offset: 0 });
          if (!data || !data.success) {
            toast(WFT('admin.keys_failed', 'تعذر إصدار المفاتيح'));
            if (data && isMeaningfulKeyError(data.error)) toast(String(data.error).slice(0, 300));
            return;
          }
          const keyless = (data.total_keyless || 0);
          if (totalKeyless === null) totalKeyless = keyless;
          created += data.created || 0;
          failed += data.failed || 0;
          if (Array.isArray(data.results)) {
            data.results.forEach((r) => {
              if (r && r.ok && r.companyName) provisionedNames.push(String(r.companyName));
            });
            if (!firstError) {
              const bad = data.results.find((r) => !r.ok && isMeaningfulKeyError(r.error));
              if (bad) firstError = String(bad.error).slice(0, 300);
            }
          }
          const done = created + failed;
          const target = Math.max(1, totalKeyless || done || 1);
          updateLoaderProgress(Math.min(95, Math.round((done / target) * 100)));
          if (!data.results || !data.results.length) break;
          const remaining = (data.remaining_keyless !== undefined && data.remaining_keyless !== null)
            ? data.remaining_keyless : keyless;
          if (remaining <= 0) break;
          if (lastKeyless !== null && keyless >= lastKeyless) break;
          lastKeyless = keyless;
        }
        if (!created && !failed) {
          toast(WFT('admin.keys_none', 'كل الشركات لديها مفاتيح'));
        } else {
          const total = (totalKeyless !== null && totalKeyless !== undefined) ? totalKeyless : (created + failed);
          toast(WFT('admin.keys_done', 'تم إصدار {created} من أصل {total}', { created, total }));
          if (provisionedNames.length) toast(provisionedNames.slice(0, 10).join(', ').slice(0, 300));
          if (firstError) toast(firstError);
        }
        if (cleaned) {
          toast(WFT('admin.orphans_deleted', 'تم حذف {count} مفاتيح يتيمة', { count: cleaned }));
        }
        const tenantsData = await api('GET', '/api/admin/tenants');
        sagAllTenants = tenantsData.success ? tenantsData.tenants || [] : sagAllTenants;
        sagSyncPlanFilter();
        renderSagTenants(sagAllTenants);
      } finally {
        if (btn) btn.disabled = false;
        hideLoader();
      }
    }

    function renderSagTenants(tenants) {
      const list = document.getElementById('sagTenantsList');
      if (!tenants.length) { list.innerHTML = '<p class="tenant-hint">لا توجد شركات</p>'; return; }
      list.innerHTML = tenants.map(t => {
        const planBadge = { 'free': '<span style="color:var(--muted)">Free</span>', 'pro': '<span style="color:var(--green)">Pro</span>', 'enterprise': '<span style="color:#7c3aed">Enterprise</span>' }[t.plan || 'free'] || t.plan;
        const statusBadge = t.isActive ? '<span style="color:var(--green)">نشط</span>' : '<span style="color:#c33">معطل</span>';
        const adminBadge = t.isAdmin ? ' | <span style="color:#7c3aed;font-weight:600">SAG Admin</span>' : '';
        const keyBadge = t.isAdmin ? '' : (t.keyActive
          ? ' | <span style="color:var(--green)">مفتاح نشط</span>'
          : ' | <span style="color:#c33">بدون مفتاح</span>');
        return '<div class="tenant-presentation-card">' +
          '<div><h3>' + escapeHtml(t.companyName || '') + adminBadge + '</h3>' +
          '<div class="meta">' + escapeHtml(t.accountManagerName || '') + ' | ' +
          escapeHtml(t.email) + ' | ' + escapeHtml(t.username || '') + ' | ' +
          planBadge + ' | ' + statusBadge + keyBadge + ' | <span>رصيد</span> ' +
          Number(t.creditBalanceSar != null ? t.creditBalanceSar : (t.creditBalance || 0)).toLocaleString('en-US') + ' <span>ريال</span>' +
          (t.createdAt ? ' | ' + t.createdAt.slice(0, 10) : '') +
          '</div></div>' +
          '<div class="tenant-actions" style="gap:6px">' +
          '<button class="btn small primary" onclick="showSagTenantDetails(\'' + t.id + '\')">عرض الحساب</button>' +
          '<button class="btn small ' + (t.isActive ? 'danger' : 'green') + '" onclick="sagToggleTenant(\'' + t.id + '\', ' + (!t.isActive) + ')">' + (t.isActive ? 'إيقاف' : 'تفعيل') + '</button>' +
          '<button class="btn small ghost" onclick="openSagResetPassword(\'' + t.id + '\')">إعادة تعيين كلمة المرور</button>' +
          (!t.isAdmin && !t.keyActive
            ? '<button class="btn small ghost" onclick="sagProvisionTenantKey(\'' + t.id + '\')">إصدار مفتاح</button>' : '') +
          (t.isAdmin ? '' : '<button class="btn small danger" onclick="sagDeleteTenant(\'' + t.id + '\')">حذف</button>') +
          '</div></div>';
      }).join('');
    }

    function filterSagTenants() {
      const q = (document.getElementById('sagSearchInput').value || '').toLowerCase();
      const plan = document.getElementById('sagFilterPlan').value;
      const status = document.getElementById('sagFilterStatus').value;
      let filtered = sagAllTenants.filter(t => {
        const searchValue = [
          t.companyName, t.accountManagerName, t.email, t.username, t.phone
        ].filter(Boolean).join(' ').toLowerCase();
        if (q && !searchValue.includes(q)) return false;
        if (plan && t.plan !== plan) return false;
        if (status === 'active' && !t.isActive) return false;
        if (status === 'inactive' && t.isActive) return false;
        return true;
      });
      renderSagTenants(filtered);
    }

    const SAG_TENANT_TABS = ['company', 'users', 'drafts', 'presentations', 'exports', 'activity', 'access', 'agent'];

    function sagTenantPaneId(tab) {
      return 'sagTenantTab' + tab.charAt(0).toUpperCase() + tab.slice(1);
    }

    function sagTenantBtnId(tab) {
      return 'sagTabBtn' + tab.charAt(0).toUpperCase() + tab.slice(1);
    }

    function showSagTenantTab(tab) {
      if (!SAG_TENANT_TABS.includes(tab)) tab = 'company';
      sagTenantActiveTab = tab;
      SAG_TENANT_TABS.forEach(name => {
        const pane = document.getElementById(sagTenantPaneId(name));
        const btn = document.getElementById(sagTenantBtnId(name));
        const active = name === tab;
        if (pane) pane.style.display = active ? '' : 'none';
        if (btn) { btn.classList.toggle('primary', active); btn.classList.toggle('ghost', !active); }
      });
      if (['drafts', 'presentations', 'exports', 'activity', 'access', 'agent'].includes(tab)) {
        sagLoadTenantDataPane(sagCurrentTenantId, tab);
      }
    }

    async function sagLoadTenantDataPane(tenantId, tab) {
      const bodies = {
        drafts: 'sagTenantDraftsList',
        presentations: 'sagTenantPresentationsList',
        exports: 'sagTenantExportsList',
        activity: 'sagTenantActivityList',
        access: 'sagTenantAccessList',
        agent: 'sagTenantAgentList'
      };
      const host = document.getElementById(bodies[tab]);
      if (!host || !tenantId || host.dataset.loaded === '1') return;
      showInlineLoader(host, 'جاري التحميل...');
      const url = tab === 'access'
        ? '/api/admin/access-requests?tenant_id=' + encodeURIComponent(tenantId)
        : '/api/admin/tenants/' + tenantId + '/' + tab;
      const data = await api('GET', url).catch(() => ({ success: false }));
      if (!data || !data.success) {
        host.innerHTML = (data && data.error_code === 'access_grant_required')
          ? '<p class="tenant-hint">' + escapeHtml(WFT('admin.access_needed', 'الاطّلاع على محتوى الشركة يتطلب إذنًا معتمدًا من مديرها')) + '</p>'
          : '<p class="tenant-hint">تعذر التحميل</p>';
        return;
      }
      host.dataset.loaded = '1';
      if (tab === 'drafts') host.innerHTML = renderSagTenantDrafts(data.drafts || []);
      else if (tab === 'presentations') host.innerHTML = renderSagTenantPresentations(data.presentations || [], tenantId);
      else if (tab === 'exports') host.innerHTML = renderSagTenantExports(data.exports || []);
      else if (tab === 'access') host.innerHTML = renderSagTenantAccess(data.requests || []);
      else if (tab === 'agent') host.innerHTML = renderSagTenantAgent(data);
      else host.innerHTML = renderSagTenantActivity(data.activity || []);
    }

    function renderSagTenantAgent(data) {
      const training = data.training || [];
      const rulesLog = data.rulesLog || [];
      const chatLog = data.chatLog || [];
      const card = (title, meta, extra) =>
        '<div class="tenant-presentation-card"><div><h3 style="font-size:14px">' + title + '</h3>' +
        '<div class="meta">' + meta + '</div>' + (extra || '') + '</div></div>';
      let html = '<h3 class="dash-section-title">مدخلات التدريب</h3>';
      html += training.length ? training.map(e => {
        const date = (e.created_at || '').slice(0, 16).replace('T', ' ');
        return card(
          escapeHtml(e.title || 'بدون عنوان') + (e.is_active ? '' : ' <span style="font-size:11px">معطل</span>'),
          escapeHtml(e.category || 'general') + ' | ' + escapeHtml(date),
          '<div class="meta" style="white-space:pre-wrap;margin-top:6px">' + escapeHtml(String(e.content || '').slice(0, 400)) + '</div>');
      }).join('') : '<p class="tenant-hint">لا توجد مدخلات تدريب</p>';
      html += '<h3 class="dash-section-title" style="margin-top:18px">سجل تغييرات الوكيل</h3>';
      html += rulesLog.length ? rulesLog.map(r => {
        const date = (r.created_at || '').slice(0, 16).replace('T', ' ');
        return card(
          escapeHtml(r.rule_category || '') + ' — ' + escapeHtml(r.rule_key || ''),
          escapeHtml(r.user_name || '') + ' | ' + escapeHtml(r.risk_level || '') + ' | ' + escapeHtml(date),
          '<div class="meta" style="white-space:pre-wrap;margin-top:6px">' +
            escapeHtml(String(r.old_value == null ? '—' : r.old_value).slice(0, 200)) + ' إلى ' +
            escapeHtml(String(r.new_value == null ? '—' : r.new_value).slice(0, 200)) + '</div>');
      }).join('') : '<p class="tenant-hint">لا يوجد سجل تغييرات</p>';
      html += '<h3 class="dash-section-title" style="margin-top:18px">محادثات الوكيل</h3>';
      html += chatLog.length ? chatLog.map(c => {
        const date = (c.created_at || '').slice(0, 16).replace('T', ' ');
        let actionsText = '';
        try {
          const acts = typeof c.actions_json === 'string' ? JSON.parse(c.actions_json) : (c.actions_json || []);
          if (acts.length) actionsText = '<div class="meta" style="margin-top:4px">' +
            acts.map(a => escapeHtml((a.tool || '') + ': ' + (a.status || ''))).join(' | ') + '</div>';
        } catch (e) { /* keep the turn readable even if actions json is malformed */ }
        return card(
          escapeHtml(c.user_name || 'مستخدم') + ' | ' + escapeHtml(date),
          escapeHtml(String(c.message || '').slice(0, 300)),
          (c.reply ? '<div class="meta" style="white-space:pre-wrap;margin-top:4px">الرد: ' +
            escapeHtml(String(c.reply).slice(0, 300)) + '</div>' : '') + actionsText);
      }).join('') : '<p class="tenant-hint">لا توجد محادثات مسجلة</p>';
      return html;
    }

    function renderSagTenantAccess(requests) {
      if (!requests.length) return '<p class="tenant-hint">' + escapeHtml(WFT('admin.access_empty', 'لا توجد طلبات اطّلاع')) + '</p>';
      const statusLabels = {
        pending: WFT('users.access_pending', 'قيد الانتظار'), approved: WFT('users.access_approved', 'معتمد'),
        denied: WFT('users.access_denied', 'مرفوض'), expired: WFT('users.access_expired', 'منتهي'),
        revoked: WFT('users.access_revoked', 'ملغي'),
      };
      const scopeLabels = {
        tenant: WFT('users.access_scope_tenant', 'كل محتوى الشركة'),
        presentation: WFT('users.access_scope_presentation', 'عرض تقديمي محدد'),
        file: WFT('users.access_scope_file', 'ملف محدد'),
      };
      return requests.map(r => {
        const expiry = r.expires_at ? ' | <span>' + escapeHtml(WFT('users.access_expires', 'ينتهي')) + ':</span> ' + escapeHtml(String(r.expires_at).slice(0, 16).replace('T', ' ')) : '';
        return '<div class="tenant-presentation-card"><div><h3 style="font-size:14px">' + escapeHtml(scopeLabels[r.scope] || scopeLabels.tenant) +
          (r.target_id ? ' — ' + escapeHtml(r.target_id) : '') + '</h3>' +
          '<div class="meta"><span>' + escapeHtml(statusLabels[r.status] || r.status) + '</span> | ' +
          escapeHtml(r.reason || '') + expiry + '</div></div></div>';
      }).join('');
    }

    async function sagCreateAccessRequest(event, tenantId) {
      event.preventDefault();
      const payload = {
        scope: document.getElementById('sagAccessScope').value,
        targetId: document.getElementById('sagAccessTarget').value.trim() || null,
        reason: document.getElementById('sagAccessReason').value.trim(),
        hours: parseInt(document.getElementById('sagAccessHours').value, 10) || 24,
      };
      if (!payload.reason) { toast(WFT('admin.access_reason_required', 'السبب مطلوب')); return; }
      const data = await api('POST', '/api/admin/tenants/' + tenantId + '/access-requests', payload);
      if (data && data.success) {
        toast(WFT('admin.access_requested', 'أُرسل طلب الاطّلاع'));
        document.getElementById('sagAccessReason').value = '';
        document.getElementById('sagAccessTarget').value = '';
        const host = document.getElementById('sagTenantAccessList');
        if (host) host.dataset.loaded = '';
        sagLoadTenantDataPane(tenantId, 'access');
      } else {
        toast((data && data.error) || WFT('common.error', 'حدث خطأ'));
      }
    }

    function renderSagTenantDrafts(drafts) {
      if (!drafts.length) return '<p class="tenant-hint">لا توجد ملفات مشاريع</p>';
      return drafts.map(d => {
        const status = (d.status === 'pending_approval' ? 'بانتظار التعميد' : d.status === 'approved' ? 'معتمد' : 'مسودة') +
          (d.status === 'pending_approval' && d.approver_name ? ' — ' + escapeHtml(d.approver_name) : '');
        const date = (d.updated_at || d.created_at || '').slice(0, 16).replace('T', ' ');
        return '<div class="tenant-presentation-card"><div><h3>' + escapeHtml(d.title || 'مشروع بدون عنوان') + '</h3>' +
          '<div class="meta"><span>' + status + '</span> | ' + escapeHtml(date) + '</div></div></div>';
      }).join('');
    }

    function renderSagTenantPresentations(presentations, tenantId) {
      if (!presentations.length) return '<p class="tenant-hint">لا توجد عروض</p>';
      return presentations.map(p => {
        const status = (p.status === 'pending_approval' ? 'بانتظار التعميد' : p.status === 'approved' ? 'معتمد' : 'مسودة') +
          (p.status === 'pending_approval' && p.approver_name ? ' — ' + escapeHtml(p.approver_name) : '');
        const date = (p.updatedAt || p.createdAt || '').slice(0, 16).replace('T', ' ');
        return '<div class="tenant-presentation-card"><div><h3>' + escapeHtml(p.title || 'عرض بدون عنوان') + '</h3>' +
          '<div class="meta"><span>' + (p.slideCount || 0) + '</span> <span>شريحة</span> | <span>' + status + '</span> | ' + escapeHtml(date) + '</div></div>' +
          '<div class="tenant-actions">' +
          '<button type="button" class="btn small primary" onclick="openSagPresentationPreview(\'' + tenantId + '\', \'' + p.id + '\')">معاينة</button>' +
          '</div></div>';
      }).join('');
    }

    let sagPreviewSlides = [];
    let sagPreviewIndex = 0;

    async function openSagPresentationPreview(tenantId, presId) {
      showLoader('جاري تحميل العرض', '');
      try {
        const data = await api('GET', '/api/admin/tenants/' + tenantId + '/presentations/' + presId);
        if (!data.success) {
          if (data.error_code === 'access_grant_required') {
            toast(WFT('admin.access_needed', 'الاطّلاع على محتوى الشركة يتطلب إذنًا معتمدًا من مديرها'));
            if (sagCurrentTenantId === tenantId) showSagTenantTab('access');
          } else {
            toast(data.error || 'تعذر تحميل العرض');
          }
          return;
        }
        sagPreviewSlides = ((data.presentation && data.presentation.slidesData) || []).filter(s => s && s.html);
        if (!sagPreviewSlides.length) { toast('العرض بدون شرائح'); return; }
        sagPreviewIndex = 0;
        const existing = document.getElementById('sagPreviewModal');
        if (existing) existing.remove();
        const modal = document.createElement('div');
        modal.id = 'sagPreviewModal';
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
        modal.innerHTML = '<div class="sag-modal-card" style="max-width:1100px">' +
          '<div class="sag-modal-head"><h2>' + escapeHtml(data.presentation.title || 'عرض') + '</h2>' +
          '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">' +
          '<span id="sagPreviewCounter" class="tenant-hint"></span>' +
          '<button class="btn ghost" onclick="document.getElementById(\'sagPreviewModal\').remove()">إغلاق</button>' +
          '</div></div>' +
          '<div id="sagPreviewWrap" style="overflow:hidden;border:1px solid var(--line);border-radius:12px;background:#fff">' +
          '<div id="sagPreviewStage"></div></div>' +
          '<div class="sag-modal-actions" style="justify-content:space-between">' +
          '<button type="button" class="btn ghost" onclick="sagPreviewStep(-1)">السابق</button>' +
          '<button type="button" class="btn ghost" onclick="sagPreviewStep(1)">التالي</button>' +
          '</div></div>';
        document.body.appendChild(modal);
        renderSagPreviewSlide();
        if (!window._sagPreviewResizeBound) {
          window._sagPreviewResizeBound = true;
          window.addEventListener('resize', () => { fitSagPreviewStage(); });
        }
      } finally {
        hideLoader();
      }
    }

    function sagPreviewStep(delta) {
      sagPreviewIndex += delta;
      renderSagPreviewSlide();
    }

    function renderSagPreviewSlide() {
      const host = document.getElementById('sagPreviewStage');
      const counter = document.getElementById('sagPreviewCounter');
      if (!host) return;
      const total = sagPreviewSlides.length;
      if (!total) return;
      sagPreviewIndex = Math.max(0, Math.min(sagPreviewIndex, total - 1));
      if (counter) counter.textContent = (sagPreviewIndex + 1) + ' / ' + total;
      host.innerHTML = sagPreviewSlides[sagPreviewIndex].html || '';
      host.querySelectorAll('img[data-team-logo]').forEach(img => {
        attachProjectFileThumbnail(img, img.dataset.teamLogo);
      });
      host.querySelectorAll('img[src*="/api/project-files/"]').forEach(img => {
        const match = /\/api\/project-files\/([^/?#]+)/.exec(img.getAttribute('src') || '');
        if (match) attachProjectFileThumbnail(img, match[1]);
      });
      fitSagPreviewStage();
    }

    function fitSagPreviewStage() {
      const wrap = document.getElementById('sagPreviewWrap');
      const stage = document.getElementById('sagPreviewStage');
      if (!wrap || !stage) return;
      const scale = Math.min(1, wrap.clientWidth / 1280);
      stage.style.width = '1280px';
      stage.style.transform = 'scale(' + scale + ')';
      stage.style.transformOrigin = 'top right';
      wrap.style.height = (720 * scale) + 'px';
    }

    function renderSagTenantExports(exports) {
      if (!exports.length) return '<p class="tenant-hint">لا توجد تصديرات</p>';
      return exports.map(e => {
        const date = (e.createdAt || '').slice(0, 16).replace('T', ' ');
        return '<div class="tenant-presentation-card"><div><h3>' + escapeHtml(e.format || 'ملف') + '</h3>' +
          '<div class="meta">' + escapeHtml(date) + '</div></div></div>';
      }).join('');
    }

    function renderSagTenantActivity(activity) {
      if (!activity.length) return '<p class="tenant-hint">لا يوجد سجل تعديلات</p>';
      return activity.map(a => {
        const date = (a.created_at || '').slice(0, 16).replace('T', ' ');
        const target = a.target_type === 'presentation' ? 'عرض' : a.target_type === 'draft' ? 'ملف مشروع' : escapeHtml(a.target_type || '');
        return '<div class="tenant-presentation-card"><div><h3>' + escapeHtml(a.action || 'تعديل') + '</h3>' +
          '<div class="meta">' + escapeHtml(a.user_name || '') + ' | ' + escapeHtml(a.summary || '') + ' | <span>' + target + '</span> | ' + escapeHtml(date) + '</div></div></div>';
      }).join('');
    }

    async function showSagTenantDetails(tenantId) {
      const data = await api('GET', '/api/admin/tenants/' + tenantId + '/details');
      if (!data.success) { toast('فشل تحميل التفاصيل'); return; }
      const t = data.tenant;
      const c = data.counts;
      const users = data.users || [];
      if (sagCurrentTenantId !== tenantId) sagTenantActiveTab = 'company';
      sagCurrentTenantId = tenantId;
      sagModalUsers = users;
      const modal = document.getElementById('sagTenantModal');
      modal.style.display = 'flex';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div class="sag-modal-card" role="dialog" aria-modal="true" aria-labelledby="sagTenantModalTitle">' +
        '<div class="sag-modal-head">' +
        '<h2 id="sagTenantModalTitle">' + escapeHtml(t.companyName) + '</h2>' +
        '<button class="btn ghost" onclick="document.getElementById(\'sagTenantModal\').style.display=\'none\';if(typeof a11yModalDidClose===\'function\')a11yModalDidClose()">إغلاق</button></div>' +
        '<div class="tenant-dashboard-cards" style="margin-bottom:14px">' +
        '<div class="tenant-dash-card stat"><h3>' + c.users + '</h3><p>مستخدمون</p></div>' +
        '<div class="tenant-dash-card stat"><h3>' + c.projects + '</h3><p>دراسات</p></div>' +
        '<div class="tenant-dash-card stat"><h3>' + c.presentations + '</h3><p>عروض</p></div>' +
        '<div class="tenant-dash-card stat"><h3>' + c.exports + '</h3><p>تصديرات</p></div>' +
        '</div>' +
        '<div class="sag-tabs">' +
        '<button type="button" id="sagTabBtnCompany" class="btn small primary" onclick="showSagTenantTab(\'company\')">معلومات الشركة</button>' +
        '<button type="button" id="sagTabBtnUsers" class="btn small ghost" onclick="showSagTenantTab(\'users\')">المستخدمون</button>' +
        '<button type="button" id="sagTabBtnDrafts" class="btn small ghost" onclick="showSagTenantTab(\'drafts\')">المشاريع</button>' +
        '<button type="button" id="sagTabBtnPresentations" class="btn small ghost" onclick="showSagTenantTab(\'presentations\')">العروض</button>' +
        '<button type="button" id="sagTabBtnExports" class="btn small ghost" onclick="showSagTenantTab(\'exports\')">التصديرات</button>' +
        '<button type="button" id="sagTabBtnActivity" class="btn small ghost" onclick="showSagTenantTab(\'activity\')">سجل التعديلات</button>' +
        '<button type="button" id="sagTabBtnAccess" class="btn small ghost" onclick="showSagTenantTab(\'access\')">' + escapeHtml(WFT('admin.access_tab', 'طلبات الاطّلاع على المحتوى')) + '</button>' +
        '<button type="button" id="sagTabBtnAgent" class="btn small ghost" onclick="showSagTenantTab(\'agent\')">تدريب AI والوكيل</button>' +
        '</div>' +
        '<div id="sagTenantTabCompany">' +
        '<form onsubmit="saveSagTenant(event, \'' + tenantId + '\')"><div class="tenant-grid">' +
        '<div class="tenant-field"><label for="sagDetailCompanyName">اسم الشركة</label><input id="sagDetailCompanyName" value="' + escapeHtml(t.companyName || '') + '" required></div>' +
        '<div class="tenant-field"><label for="sagDetailManagerName">اسم مدير الحساب</label><input id="sagDetailManagerName" value="' + escapeHtml(t.accountManagerName || '') + '" required></div>' +
        '<div class="tenant-field"><label for="sagDetailEmail">البريد الإلكتروني</label><input type="email" id="sagDetailEmail" value="' + escapeHtml(t.email || '') + '" required></div>' +
        '<div class="tenant-field"><label for="sagDetailPhone">رقم الجوال</label><input id="sagDetailPhone" value="' + escapeHtml(t.phone || '') + '" required></div>' +
        '<div class="tenant-field"><label for="sagDetailUsername">اسم المستخدم</label><input id="sagDetailUsername" value="' + escapeHtml(t.username || '') + '" required></div>' +
        '<div class="tenant-field"><label>تاريخ إنشاء الحساب</label><p style="margin:0">' + escapeHtml(t.createdAt || '') + '</p></div>' +
        '<div class="tenant-field"><label for="sagDetailSlug">رابط الشركة (slug)</label><input id="sagDetailSlug" dir="ltr" maxlength="60" value="' + escapeHtml(t.slug || '') + '"></div>' +
        '<div class="tenant-field"><label for="sagDetailPlan">الباقة</label><select id="sagDetailPlan">' +
        '<option value="free"' + (t.plan === 'free' ? ' selected' : '') + '>Free</option>' +
        '<option value="pro"' + (t.plan === 'pro' ? ' selected' : '') + '>Pro</option>' +
        '<option value="enterprise"' + (t.plan === 'enterprise' ? ' selected' : '') + '>Enterprise</option></select></div>' +
        '<div class="tenant-field"><label>الرصيد الحالي (ريال)</label><p style="margin:0;font-weight:700">' + Number(t.creditBalanceSar != null ? t.creditBalanceSar : (t.creditBalance || 0)).toLocaleString('en-US', { maximumFractionDigits: 2 }) + '</p></div>' +
        '<div class="tenant-field"><label for="sagDetailLegalName">الاسم القانوني</label><input id="sagDetailLegalName" maxlength="160" value="' + escapeHtml(t.legalName || '') + '"></div>' +
        '<div class="tenant-field"><label for="sagDetailTaxNumber">الرقم الضريبي</label><input id="sagDetailTaxNumber" dir="ltr" maxlength="40" value="' + escapeHtml(t.taxNumber || '') + '"></div>' +
        '<div class="tenant-field"><label for="sagDetailCrNumber">السجل التجاري</label><input id="sagDetailCrNumber" dir="ltr" maxlength="40" value="' + escapeHtml(t.crNumber || '') + '"></div>' +
        '<div class="tenant-field"><label for="sagDetailCountry">الدولة</label><input id="sagDetailCountry" maxlength="80" value="' + escapeHtml(t.country || '') + '"></div>' +
        '<div class="tenant-field"><label for="sagDetailTrialEnds">نهاية التجربة</label><input type="date" id="sagDetailTrialEnds" dir="ltr" value="' + escapeHtml((t.trialEndsAt || '').slice(0, 10)) + '"></div>' +
        '<div class="tenant-field"><label for="sagDetailStatus">حالة الحساب</label><select id="sagDetailStatus">' +
        '<option value="active"' + (t.isActive ? ' selected' : '') + '>نشط</option>' +
        '<option value="inactive"' + (!t.isActive ? ' selected' : '') + '>موقوف</option></select></div>' +
        '<div class="tenant-field"><label>التفعيل</label><p style="margin:0">' +
        (t.activatedAt ? ('فُعّلت في ' + escapeHtml(String(t.activatedAt).slice(0, 10)) + (t.activatedByName ? ' بواسطة ' + escapeHtml(t.activatedByName) : '')) : 'لم تُفعّل بعد') +
        (t.deactivatedReason ? ' | سبب الإيقاف: ' + escapeHtml(t.deactivatedReason) : '') + '</p></div>' +
        '</div><div class="sag-modal-actions">' +
        '<button type="submit" class="btn primary">حفظ بيانات الشركة</button></div></form>' +
        '<h3 class="dash-section-title" style="margin-top:18px">تصحيح رصيد</h3>' +
        '<form onsubmit="sagSubmitLedgerAdjust(event, \'' + tenantId + '\')"><div class="tenant-grid">' +
        '<div class="tenant-field"><label for="sagAdjKind">نوع الحركة</label><select id="sagAdjKind">' +
        '<option value="correction">تصحيح</option>' +
        '<option value="refund">استرداد</option>' +
        '<option value="expiry">انتهاء صلاحية</option></select></div>' +
        '<div class="tenant-field"><label for="sagAdjAmount">المبلغ (ريال)</label><input type="number" id="sagAdjAmount" step="0.01" required dir="ltr"></div>' +
        '<div class="tenant-field full"><label for="sagAdjNote">ملاحظة</label><input id="sagAdjNote" maxlength="300"></div>' +
        '</div><div class="sag-modal-actions"><button type="submit" class="btn primary">تسجيل الحركة</button></div></form>' +
        '</div>' +
        '<div id="sagTenantTabUsers" style="display:none">' +
        '<h3 class="dash-section-title">المستخدمون</h3>' +
        '<div id="sagTenantUsers">' + renderSagTenantUsers(tenantId, t.primaryUserId, users) + '</div>' +
        '<h3 class="dash-section-title" style="margin-top:18px">إضافة مستخدم</h3>' +
        '<form onsubmit="sagAddTenantUser(event, \'' + tenantId + '\')"><div class="tenant-grid">' +
        '<div class="tenant-field"><label for="sagNewUserName">الاسم</label><input id="sagNewUserName" required></div>' +
        '<div class="tenant-field"><label for="sagNewUserEmail">البريد الإلكتروني</label><input type="email" id="sagNewUserEmail" required></div>' +
        '<div class="tenant-field"><label for="sagNewUserUsername">اسم المستخدم</label><input id="sagNewUserUsername" minlength="3" maxlength="40" required></div>' +
        '<div class="tenant-field"><label for="sagNewUserPhone">رقم الجوال</label><input id="sagNewUserPhone" required></div>' +
        '</div><div class="sag-modal-actions">' +
        '<button type="submit" class="btn primary">إضافة المستخدم</button></div></form>' +
        '</div>' +
        '<div id="sagTenantTabDrafts" style="display:none">' +
        '<h3 class="dash-section-title">المشاريع</h3><div id="sagTenantDraftsList"></div></div>' +
        '<div id="sagTenantTabPresentations" style="display:none">' +
        '<h3 class="dash-section-title">العروض</h3><div id="sagTenantPresentationsList"></div></div>' +
        '<div id="sagTenantTabExports" style="display:none">' +
        '<h3 class="dash-section-title">التصديرات</h3><div id="sagTenantExportsList"></div></div>' +
        '<div id="sagTenantTabActivity" style="display:none">' +
        '<h3 class="dash-section-title">سجل التعديلات</h3><div id="sagTenantActivityList"></div></div>' +
        '<div id="sagTenantTabAccess" style="display:none">' +
        '<h3 class="dash-section-title">' + escapeHtml(WFT('admin.access_tab', 'طلبات الاطّلاع على المحتوى')) + '</h3>' +
        '<form onsubmit="sagCreateAccessRequest(event, \'' + tenantId + '\')" style="margin-bottom:14px"><div class="tenant-grid">' +
        '<div class="tenant-field"><label for="sagAccessScope">' + escapeHtml(WFT('admin.access_scope', 'النطاق')) + '</label><select id="sagAccessScope">' +
        '<option value="tenant">' + escapeHtml(WFT('admin.access_scope_tenant', 'كل محتوى الشركة')) + '</option>' +
        '<option value="presentation">' + escapeHtml(WFT('admin.access_scope_presentation', 'عرض محدد')) + '</option>' +
        '<option value="file">' + escapeHtml(WFT('admin.access_scope_file', 'ملف محدد')) + '</option></select></div>' +
        '<div class="tenant-field"><label for="sagAccessTarget">' + escapeHtml(WFT('admin.access_target', 'معرف الهدف')) + '</label><input id="sagAccessTarget" dir="ltr"></div>' +
        '<div class="tenant-field"><label for="sagAccessHours">' + escapeHtml(WFT('admin.access_hours', 'المدة بالساعات')) + '</label><input type="number" id="sagAccessHours" min="1" max="72" value="24" dir="ltr"></div>' +
        '<div class="tenant-field full"><label for="sagAccessReason">' + escapeHtml(WFT('admin.access_reason', 'السبب')) + '</label><input id="sagAccessReason" maxlength="300" required></div>' +
        '</div><div class="sag-modal-actions"><button type="submit" class="btn primary">' + escapeHtml(WFT('admin.access_request_btn', 'إرسال طلب اطّلاع')) + '</button></div></form>' +
        '<div id="sagTenantAccessList"></div></div>' +
        '<div id="sagTenantTabAgent" style="display:none">' +
        '<h3 class="dash-section-title">تدريب AI والوكيل</h3><div id="sagTenantAgentList"></div></div>' +
        '</div>';
      showSagTenantTab(sagTenantActiveTab);
      if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(modal);
    }

    function renderSagTenantUsers(tenantId, primaryUserId, users) {
      if (!users.length) return '<p class="tenant-hint">لا يوجد مستخدمون</p>';
      return users.map(user => {
        const primary = user.id === primaryUserId;
        return '<div class="tenant-presentation-card"><div><h3>' + escapeHtml(user.name) +
          (primary ? ' <span style="font-size:11px;color:var(--p)">مدير الحساب</span>' : '') + '</h3>' +
          '<div class="meta">' + escapeHtml(user.email) + ' | ' + escapeHtml(user.username || '') +
          ' | ' + escapeHtml(user.phone || '') + ' | <span>' +
          (primary ? 'أدمن الشركة' : 'موظف') + '</span> | <span>' +
          (user.is_active ? 'نشط' : 'موقوف') + '</span></div></div>' +
          '<div class="tenant-actions">' +
          '<button type="button" class="btn small ghost" onclick="openSagUserEdit(\'' +
            tenantId + '\', \'' + user.id + '\')">تعديل</button>' +
          '<button type="button" class="btn small primary" onclick="openSagUserPermissions(\'' +
            tenantId + '\', \'' + user.id + '\', \'' + escapeHtml(user.name) + '\')">صلاحيات</button>' +
          (primary ? '' : '<button type="button" class="btn small ghost" onclick="sagSetPrimaryUser(\'' +
            tenantId + '\', \'' + user.id + '\')">تعيين مدير الحساب</button>') +
          '<button type="button" class="btn small ' + (user.is_active ? 'danger' : 'green') +
          '" onclick="sagToggleTenantUser(\'' + tenantId + '\', \'' + user.id + '\', ' +
          (!user.is_active) + ')">' + (user.is_active ? 'إيقاف' : 'تفعيل') + '</button>' +
          (primary ? '' : '<button type="button" class="btn small danger" onclick="sagDeleteTenantUser(\'' +
            tenantId + '\', \'' + user.id + '\')">حذف</button>') +
          '</div></div>';
      }).join('');
    }

    async function saveSagTenant(event, tenantId) {
      event.preventDefault();
      const trialEl = document.getElementById('sagDetailTrialEnds');
      const payload = {
        companyName: document.getElementById('sagDetailCompanyName').value.trim(),
        accountManagerName: document.getElementById('sagDetailManagerName').value.trim(),
        email: document.getElementById('sagDetailEmail').value.trim().toLowerCase(),
        phone: document.getElementById('sagDetailPhone').value.trim(),
        username: document.getElementById('sagDetailUsername').value.trim().toLowerCase(),
        plan: document.getElementById('sagDetailPlan').value,
        isActive: document.getElementById('sagDetailStatus').value === 'active',
        legalName: (document.getElementById('sagDetailLegalName') || {}).value || '',
        taxNumber: (document.getElementById('sagDetailTaxNumber') || {}).value || '',
        crNumber: (document.getElementById('sagDetailCrNumber') || {}).value || '',
        country: (document.getElementById('sagDetailCountry') || {}).value || '',
        trialEndsAt: trialEl && trialEl.value ? trialEl.value : null
      };
      const slugEl = document.getElementById('sagDetailSlug');
      const slugValue = slugEl ? slugEl.value.trim().toLowerCase() : '';
      const tenant = (sagAllTenants || []).find(t => t.id === tenantId) || {};
      const data = await api('PUT', '/api/admin/tenants/' + tenantId, payload);
      if (!data.success) {
        if (data.error === 'activation_incomplete') {
          toast(WFT('admin.profile_incomplete', 'ملف الشركة غير مكتمل:') + ' ' + ((data.missing || []).join('، ')));
        } else {
          toast(data.error || 'تعذر حفظ بيانات الشركة');
        }
        return;
      }
      if (slugValue && slugValue !== (tenant.slug || '')) {
        const slugRes = await api('PUT', '/api/admin/tenants/' + tenantId + '/slug', {
          slug: slugValue, allowAfterActivation: true
        }).catch(e => e);
        if (!slugRes || !slugRes.success) {
          toast((slugRes && (slugRes.message || slugRes.error)) || 'تعذر تحديث الرابط');
        }
      }
      toast('تم حفظ بيانات الشركة');
      await openTenantCompanies();
      await showSagTenantDetails(tenantId);
    }

    // Wallet money moves only through the ledger: an approved recharge or a
    // typed adjustment here (correction / refund / expiry) with an optional
    // note — never a raw balance write.
    async function sagSubmitLedgerAdjust(event, tenantId) {
      event.preventDefault();
      const amount = parseFloat((document.getElementById('sagAdjAmount') || {}).value);
      const kind = (document.getElementById('sagAdjKind') || {}).value || 'correction';
      const note = ((document.getElementById('sagAdjNote') || {}).value || '').trim();
      if (!Number.isFinite(amount) || amount === 0) { toast(WFT('wallet.invalid_amount', 'أدخل مبلغًا صالحًا')); return; }
      const data = await api('POST', '/api/admin/ledger/adjust', {
        tenantId: tenantId, amountSar: amount, kind: kind, note: note || undefined
      }).catch(e => e);
      if (!data || !data.success) {
        toast((data && data.error) || 'تعذر تسجيل حركة الرصيد');
        return;
      }
      toast(WFT('wallet.movement_recorded', 'تم تسجيل حركة الرصيد'));
      await openTenantCompanies();
      await showSagTenantDetails(tenantId);
    }

    async function sagAddTenantUser(event, tenantId) {
      event.preventDefault();
      showLoader('جاري إضافة المستخدم', 'إنشاء الحساب ورابط كلمة المرور', 15);
      try {
        const data = await api('POST', '/api/admin/tenants/' + tenantId + '/users', {
          name: document.getElementById('sagNewUserName').value.trim(),
          email: document.getElementById('sagNewUserEmail').value.trim().toLowerCase(),
          username: document.getElementById('sagNewUserUsername').value.trim().toLowerCase(),
          phone: document.getElementById('sagNewUserPhone').value.trim(),
          useSetupLink: true
        });
        if (!data.success) {
          toast(data.error || 'تعذر إضافة المستخدم');
          return;
        }
        if (data.setupUrl) await copySagText(data.setupUrl);
        toast('تمت إضافة المستخدم');
        await showSagTenantDetails(tenantId);
      } finally {
        hideLoader();
      }
    }

    async function sagSetPrimaryUser(tenantId, userId) {
      const data = await api('PUT', '/api/admin/tenants/' + tenantId + '/users/' + userId, { isPrimary: true });
      if (!data.success) {
        toast(data.error || 'تعذر تغيير مدير الحساب');
        return;
      }
      toast('تم تغيير مدير الحساب');
      await openTenantCompanies();
      await showSagTenantDetails(tenantId);
    }

    async function sagToggleTenantUser(tenantId, userId, isActive) {
      const data = await api('PUT', '/api/admin/tenants/' + tenantId + '/users/' + userId, { is_active: isActive });
      if (!data.success) {
        toast(data.error || 'تعذر تحديث المستخدم');
        return;
      }
      toast(isActive ? 'تم تفعيل المستخدم' : 'تم إيقاف المستخدم');
      await showSagTenantDetails(tenantId);
    }

    async function sagDeleteTenantUser(tenantId, userId) {
      if (!confirm(WFT('admin.confirm_delete_user', 'حذف المستخدم نهائياً؟'))) return;
      const data = await api('DELETE', '/api/admin/tenants/' + tenantId + '/users/' + userId);
      if (!data.success) {
        toast(data.error || 'تعذر حذف المستخدم');
        return;
      }
      toast('تم حذف المستخدم');
      await showSagTenantDetails(tenantId);
    }

    let editingSagUserPermissions = null;

    async function openSagUserPermissions(tenantId, userId, userName) {
      const [permData, sectionData] = await Promise.all([
        api('GET', '/api/admin/tenants/' + tenantId + '/users/' + userId + '/permissions'),
        api('GET', '/api/admin/tenants/' + tenantId + '/users/' + userId + '/field-sections')
      ]);
      if (!permData.success || !sectionData.success) { toast('تعذر تحميل الصلاحيات'); return; }
      const perms = permData.permissions || {};
      const keys = permData.availableKeys || [];
      const sections = sectionData.sections || {};
      const availableSections = sectionData.available || [];
      editingSagUserPermissions = { tenantId, userId, userName, availableSections };

      const permRows = keys.map(key => {
        const label = PERMISSION_LABELS[key] || key;
        return '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)">' +
          '<label>' + label + '</label>' +
          '<input type="checkbox" id="sperm_' + key + '" ' + (perms[key] ? 'checked' : '') + '>' +
          '</div>';
      }).join('');

      const sectionRows = availableSections.map(s => {
        return '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)">' +
          '<label>' + escapeHtml(s.label) + '</label>' +
          '<input type="checkbox" id="ssection_' + s.key + '" ' + (sections[s.key] ? 'checked' : '') + '>' +
          '</div>';
      }).join('');

      const existing = document.getElementById('sagUserPermissionsModal');
      if (existing) existing.remove();
      const modal = document.createElement('div');
      modal.id = 'sagUserPermissionsModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:16px;padding:20px;max-width:520px;width:100%;max-height:85vh;overflow:auto">' +
        '<div class="sag-modal-head">' +
        '<h2>صلاحيات: ' + escapeHtml(userName) + '</h2>' +
        '<button class="btn ghost" onclick="document.getElementById(\'sagUserPermissionsModal\').remove()">إغلاق</button></div>' +
        '<h4 style="margin:12px 0 8px;color:var(--pd)">صلاحيات التطبيق</h4>' +
        permRows +
        '<h4 style="margin:16px 0 8px;color:var(--pd)">أقسام فورم المشروع</h4>' +
        sectionRows +
        '<div class="sag-modal-actions">' +
        '<button class="btn primary" onclick="saveSagUserPermissions()">حفظ الصلاحيات</button>' +
        '</div></div>';
      document.body.appendChild(modal);
    }

    async function saveSagUserPermissions() {
      if (!editingSagUserPermissions) return;
      const { tenantId, userId } = editingSagUserPermissions;
      const permissions = {};
      Object.keys(PERMISSION_LABELS).forEach(key => {
        const cb = document.getElementById('sperm_' + key);
        permissions[key] = cb ? cb.checked : false;
      });
      const sections = {};
      (editingSagUserPermissions.availableSections || []).forEach(s => {
        const cb = document.getElementById('ssection_' + s.key);
        sections[s.key] = cb ? cb.checked : false;
      });
      showLoader('جاري حفظ الصلاحيات', '');
      const [permRes, sectionRes] = await Promise.all([
        api('PUT', '/api/admin/tenants/' + tenantId + '/users/' + userId + '/permissions', { permissions }),
        api('PUT', '/api/admin/tenants/' + tenantId + '/users/' + userId + '/field-sections', { sections })
      ]);
      hideLoader();
      const modal = document.getElementById('sagUserPermissionsModal');
      if (modal) modal.remove();
      if (permRes.success && sectionRes.success) { toast('تم حفظ الصلاحيات'); }
      else { toast(permRes.error || sectionRes.error || 'فشل الحفظ'); }
    }

    function openSagUserEdit(tenantId, userId) {
      const user = (sagModalUsers || []).find(u => u.id === userId);
      if (!user) { toast('تعذر تحميل بيانات المستخدم'); return; }
      const existing = document.getElementById('sagUserEditModal');
      if (existing) existing.remove();
      const modal = document.createElement('div');
      modal.id = 'sagUserEditModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:16px;padding:20px;max-width:560px;width:100%;max-height:85vh;overflow:auto">' +
        '<div class="sag-modal-head">' +
        '<h2>تعديل المستخدم</h2>' +
        '<button class="btn ghost" onclick="document.getElementById(\'sagUserEditModal\').remove()">إغلاق</button></div>' +
        '<div class="tenant-grid">' +
        '<div class="tenant-field"><label>الاسم</label><input id="sagEditUserName" value="' + escapeHtml(user.name || '') + '" required></div>' +
        '<div class="tenant-field"><label>البريد الإلكتروني</label><input type="email" id="sagEditUserEmail" value="' + escapeHtml(user.email || '') + '" required></div>' +
        '<div class="tenant-field"><label>اسم المستخدم</label><input id="sagEditUserUsername" value="' + escapeHtml(user.username || '') + '" minlength="3" maxlength="40" required></div>' +
        '<div class="tenant-field"><label>رقم الجوال</label><input id="sagEditUserPhone" value="' + escapeHtml(user.phone || '') + '"></div>' +
        '<div class="tenant-field full"><label>كلمة مرور جديدة</label>' +
        '<div style="display:flex;gap:8px">' +
        '<input type="text" id="sagEditUserPassword" minlength="10" autocomplete="new-password" placeholder="فارغة للإبقاء على الحالية" style="flex:1;min-width:0">' +
        '<button type="button" class="btn ghost" onclick="document.getElementById(\'sagEditUserPassword\').value = generateStrongPassword()">توليد تلقائي</button>' +
        '</div></div>' +
        '</div>' +
        '<div class="sag-modal-actions">' +
        '<button type="button" class="btn ghost" onclick="document.getElementById(\'sagUserEditModal\').remove()">إلغاء</button>' +
        '<button type="button" class="btn primary" onclick="sagSaveUserEdit(\'' + tenantId + '\', \'' + user.id + '\')">حفظ</button>' +
        '</div></div>';
      document.body.appendChild(modal);
    }

    async function sagSaveUserEdit(tenantId, userId) {
      const payload = {
        name: document.getElementById('sagEditUserName').value.trim(),
        email: document.getElementById('sagEditUserEmail').value.trim().toLowerCase(),
        username: document.getElementById('sagEditUserUsername').value.trim().toLowerCase(),
        phone: document.getElementById('sagEditUserPhone').value.trim()
      };
      const newPassword = document.getElementById('sagEditUserPassword').value;
      if (newPassword) {
        const pwError = passwordPolicyError(newPassword);
        if (pwError) { toast(pwError); return; }
        payload.password = newPassword;
      }
      if (!payload.name || !payload.email || !payload.username) {
        toast('الاسم والبريد واسم المستخدم مطلوبة');
        return;
      }
      showLoader('جاري حفظ بيانات المستخدم', '');
      try {
        const data = await api('PUT', '/api/admin/tenants/' + tenantId + '/users/' + userId, payload);
        if (!data.success) {
          toast(data.error || 'تعذر حفظ بيانات المستخدم');
          return;
        }
        document.getElementById('sagUserEditModal').remove();
        toast('تم حفظ بيانات المستخدم');
        await showSagTenantDetails(tenantId);
      } finally {
        hideLoader();
      }
    }

    async function sagToggleTenant(tenantId, isActive) {
      const data = await api('PUT', '/api/admin/tenants/' + tenantId, { is_active: isActive });
      if (data.success) { toast(isActive ? 'تم التفعيل' : 'تم التعطيل'); openTenantCompanies(); }
      else { toast(data.error || 'فشل'); }
    }

    async function sagProvisionTenantKey(tenantId) {
      const data = await api('POST', '/api/admin/tenants/' + tenantId + '/openrouter-key/provision', {});
      if (data.success) { toast(WFT('admin.key_issued', 'تم إصدار مفتاح الشركة')); openTenantCompanies(); }
      else { toast(data.error || WFT('admin.key_issue_failed', 'فشل إصدار المفتاح')); }
    }

    async function sagDeleteTenant(tenantId) {
      if (!confirm(WFT('admin.confirm_delete_tenant', 'حذف الشركة وكل بياناتها نهائياً؟'))) return;
      const data = await api('DELETE', '/api/admin/tenants/' + tenantId);
      if (data.success) { toast('تم حذف الشركة'); openTenantCompanies(); }
      else { toast(data.error || 'فشل الحذف'); }
    }

    function openSagResetPassword(tenantId) {
      const existing = document.getElementById('sagResetPasswordModal');
      if (existing) existing.remove();
      const modal = document.createElement('div');
      modal.id = 'sagResetPasswordModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:20px;padding:28px;max-width:520px;width:100%">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">' +
        '<h2 style="margin:0">إعادة تعيين كلمة المرور</h2>' +
        '<button class="btn ghost" onclick="document.getElementById(\'sagResetPasswordModal\').remove()">إغلاق</button></div>' +
        '<div class="tenant-field"><label>كلمة مرور جديدة</label>' +
        '<div style="display:flex;gap:8px">' +
        '<input type="text" id="sagResetPasswordValue" minlength="10" autocomplete="new-password" style="flex:1;min-width:0">' +
        '<button type="button" class="btn ghost" onclick="document.getElementById(\'sagResetPasswordValue\').value = generateStrongPassword()">توليد تلقائي</button>' +
        '</div></div>' +
        '<div style="display:flex;justify-content:flex-end;gap:10px;margin-top:16px;flex-wrap:wrap">' +
        '<button type="button" class="btn ghost" onclick="document.getElementById(\'sagResetPasswordModal\').remove()">إلغاء</button>' +
        '<button type="button" class="btn ghost" onclick="sagResetPasswordWithLink(\'' + tenantId + '\')">رابط تعيين</button>' +
        '<button type="button" class="btn primary" onclick="sagResetPasswordWithValue(\'' + tenantId + '\')">اعتماد</button>' +
        '</div></div>';
      document.body.appendChild(modal);
    }

    async function sagResetPasswordWithValue(tenantId) {
      const password = document.getElementById('sagResetPasswordValue').value;
      const pwError = passwordPolicyError(password);
      if (pwError) { toast(pwError); return; }
      showLoader('جاري تعيين كلمة المرور', 'حفظ كلمة المرور الجديدة', 15);
      try {
        const data = await api('POST', '/api/admin/tenants/' + tenantId + '/reset-password', { password });
        if (!data.success) {
          toast(data.error || 'تعذر تعيين كلمة المرور');
          return;
        }
        document.getElementById('sagResetPasswordModal').remove();
        toast('تم تعيين كلمة المرور');
      } finally {
        hideLoader();
      }
    }

    async function sagResetPasswordWithLink(tenantId) {
      showLoader('جاري إنشاء رابط كلمة المرور', 'تأمين رابط جديد للاستخدام مرة واحدة', 15);
      try {
        const data = await api('POST', '/api/admin/tenants/' + tenantId + '/reset-password', { useSetupLink: true });
        if (!data.success) {
          toast(data.error || 'تعذر إنشاء الرابط');
          return;
        }
        await copySagText(data.setupUrl);
        document.getElementById('sagResetPasswordModal').remove();
        toast('تم إنشاء رابط كلمة المرور');
      } finally {
        hideLoader();
      }
    }





    function escapeHtml(text) {
      if (!text) return '';
      return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    function formatUsageCost(sar) {
      const value = Number(sar) || 0;
      const digits = value >= 1 ? 2 : value >= 0.01 ? 2 : 4;
      const text = (value >= 1
        ? value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : value.toFixed(digits));
      return '<span dir="ltr">' + text + '</span> <span>ريال</span>';
    }

    function aiReconcileStatusText(entry) {
      if (!entry || typeof entry !== 'object') return '';
      const state = entry.state || '';
      if (state === 'pending') return 'قيد الاستكمال';
      if (state === 'needs_review') return 'تحتاج مطابقة';
      if (state === 'settled') return 'التكلفة المسجلة';
      const pending = Number(entry.pending || 0) + Number(entry.in_flight || 0);
      const review = Number(entry.unresolved || 0) + Number(entry.needs_review || 0);
      if (pending > 0) return 'قيد الاستكمال';
      if (review > 0) return 'تحتاج مطابقة';
      return '';
    }

    async function fetchAiUsageEvents(draftId, page, pageSize) {
      const params = [];
      if (draftId) params.push('draftId=' + encodeURIComponent(draftId));
      params.push('page=' + encodeURIComponent(page || 1));
      params.push('pageSize=' + encodeURIComponent(pageSize || 20));
      return api('GET', '/api/ai-usage?' + params.join('&')).catch(() => null);
    }

    async function reconcileAiUsage(draftId, presentationId, includeSettled) {
      const payload = {};
      if (draftId) payload.draftId = draftId;
      if (presentationId) payload.presentationId = presentationId;
      if (includeSettled) payload.includeSettled = true;
      return api('POST', '/api/ai-usage/reconcile', payload).catch(() => null);
    }


    function renderTrainingChat() {
      const log = document.getElementById('trainingChatLog');
      if (!log) return;
      if (!trainingChatHistory.length) {
        log.innerHTML = '<div style="text-align:center;padding:32px 20px;"><h3 style="margin:0 0 8px;color:var(--accent);">وكيل الإدارة الذكي</h3></div>';
        return;
      }
      log.innerHTML = trainingChatHistory.map(m => {
        if (m.role === 'user') {
          return '<div class="msg user">' + escapeHtml(m.text) + '</div>';
        }
        // AI message — check for executed actions
        let html = '<div class="msg ai">' + escapeHtml(m.text).replace(/\n/g, '<br>');
        if (m.actions && m.actions.length) {
          html += '<div style="margin-top:10px;">';
          m.actions.forEach(a => {
            const isOk = a.status === 'success';
            const icon = isOk ? '' : '';
            const bg = isOk ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)';
            const border = isOk ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)';
            const color = isOk ? '#16a34a' : '#dc2626';
            html += '<div style="background:' + bg + ';border:1px solid ' + border + ';border-radius:8px;padding:8px 12px;margin-top:6px;font-size:12px;">';
            html += '<span style="color:' + color + ';font-weight:600;">' + icon + ' ' + escapeHtml(a.message || a.tool || '') + '</span>';
            if (a.changes && Object.keys(a.changes).length) {
              html += '<div style="margin-top:4px;font-size:11px;opacity:0.8;">';
              Object.entries(a.changes).forEach(([k, v]) => {
                if (v && typeof v === 'object' && 'old' in v) {
                  html += '<div>' + escapeHtml(k) + ': <s>' + escapeHtml(String(v.old || '—')) + '</s> إلى <strong>' + escapeHtml(String(v.new)) + '</strong></div>';
                }
              });
              html += '</div>';
            }
            html += '</div>';
          });
          html += '</div>';
        }
        html += '</div>';
        return html;
      }).join('');
      log.scrollTop = log.scrollHeight;
    }

    function buildAgentWorkspacePayload() {
      return {
        presentationId: tenantPresentationId,
        projectData: tenantProjectData || {},
        slidePlan: tenantSlidePlan || {},
        slidesData: Array.isArray(tenantSlidesData) ? tenantSlidesData : [],
        creativeImages: tenantCreativeImages || {},
        title: (tenantProjectData && (tenantProjectData.project_name || tenantProjectData.projectName)) || 'عرض بدون عنوان'
      };
    }

    async function applyAgentWorkspaceActions(actions) {
      checkpointPresentationUndo();
      let changed = false;
      let planChanged = false;
      let dataChanged = false;
      (actions || []).forEach(action => {
        const data = action && action.data;
        if (!data || typeof data !== 'object') return;
        if (Array.isArray(data.slidesData)) {
          tenantSlidesData = data.slidesData;
          changed = true;
        }
        if (data.presentationId) {
          tenantPresentationId = data.presentationId;
          changed = true;
        }
        if (data.revision) {
          tenantPresentationRevision = Number(data.revision) || tenantPresentationRevision;
        }
        if (data.projectData && typeof data.projectData === 'object') {
          tenantProjectData = { ...(tenantProjectData || {}), ...data.projectData };
          dataChanged = true;
        }
        if (data.slidePlan && typeof data.slidePlan === 'object' && Array.isArray(data.slidePlan.slides)) {
          tenantSlidePlan = data.slidePlan;
          planChanged = true;
        }
        if (data.url && data.exportId) {
          window.open(data.url, '_blank', 'noopener');
        }
      });
      if (dataChanged) {
        const form = document.getElementById('tenantProjectForm');
        if (form) {
          Object.entries(tenantProjectData || {}).forEach(([key, value]) => {
            const input = form.querySelector('[data-key="' + key + '"]');
            if (input && input.type !== 'file') input.value = value;
          });
          refreshLocationTables();
        }
      }
      if (changed) {
        renumberTenantSlides();
        renderTenantSlides();
        renderTenantSlidesSidebar();
        updateTenantChatSlideSelect();
        triggerAutoSaveDraft();
      }
      if (changed || planChanged || dataChanged) triggerAutoSaveDraft();
      if (changed || planChanged) checkpointPresentationUndo();
      return changed || planChanged || dataChanged;
    }


    async function openTenantAdmin() {
      showTenantPage('tenantAdminPage');
      await loadAdminDashboard();
    }

    async function loadAdminDashboard() {
      const statsEl = document.getElementById('sagAdminStats');
      const pendingEl = document.getElementById('sagPendingActions');
      if (statsEl) statsEl.innerHTML = '';
      if (pendingEl) showInlineLoader(pendingEl, WFT('common.loading', 'جاري التحميل...'));
      const [overviewData, tenantsData] = await Promise.all([
        api('GET', '/api/admin/operational-overview').catch(() => null),
        api('GET', '/api/admin/tenants').catch(() => null)
      ]);
      const overview = (overviewData && overviewData.overview) || {};
      sagAllTenants = (tenantsData && tenantsData.success && tenantsData.tenants) ? tenantsData.tenants : [];
      sagLastOverview = overview;
      renderAdminDashboard(overview);
      if (sagChartRange.preset !== '12') sagApplyChartRange();
      if (typeof llLoadNotifications === 'function') llLoadNotifications('adminNotificationsList');
      fillAnnounceTargets(document.getElementById('adminAnnounceTarget'), sagAllTenants);
    }

    // prefix selects the field set — the dashboard panel uses «adminAnnounce»,
    // the notifications page panel uses «notifAnnounce»; both post to the
    // same super-admin endpoint.
    async function adminSendAnnouncement(prefix) {
      prefix = prefix || 'adminAnnounce';
      const target = (document.getElementById(prefix + 'Target') || {}).value || 'all';
      const title = ((document.getElementById(prefix + 'Title') || {}).value || '').trim();
      const body = ((document.getElementById(prefix + 'Body') || {}).value || '').trim();
      if (!title) { toast(WFT('admin.announce_title_required', 'عنوان الإشعار مطلوب')); return; }
      const res = await api('POST', '/api/admin/notifications',
        { tenantId: target, title: title, body: body }).catch(e => e);
      if (!res || !res.success) {
        toast((res && res.error) || WFT('admin.announce_failed', 'تعذر إرسال الإشعار'));
        return;
      }
      document.getElementById(prefix + 'Title').value = '';
      document.getElementById(prefix + 'Body').value = '';
      toast(WFT('admin.announce_sent', 'تم إرسال الإشعار'));
    }

    // Re-render on language toggle: every dashboard label is built through
    // WFT at render time, so switching ar/en redraws KPIs, legends, month
    // ticks, status bars and pending actions instead of leaving stale Arabic.
    document.addEventListener('wf:lang', function () {
      const page = document.getElementById('tenantAdminPage');
      if (!page || !sagLastOverview) return;
      const visible = page.classList.contains('active') || (page.style.display !== 'none' && page.style.display !== '');
      if (visible) renderAdminDashboard(sagLastOverview);
    });

    // ── Super-admin dashboard: SVG data-viz helpers (no icon glyphs; charts
    //    are genuine data rendering and keep the no-icons rule intact) ──

    const SAG_MONTHS = {
      ar: ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر'],
      en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
    };

    function sagMonthLabel(iso) {
      const lang = (window.WFI18n && WFI18n.getLang && WFI18n.getLang()) || 'ar';
      const names = SAG_MONTHS[lang === 'en' ? 'en' : 'ar'];
      const s = String(iso);
      const parts = s.split('-');
      const m = parseInt(parts[1], 10);
      const name = names[(m || 1) - 1] || s;
      if (parts.length >= 3) {
        const day = parseInt(parts[2], 10);
        const time = s.includes(' ') ? s.split(' ')[1] : (s.includes('T') ? s.split('T')[1] : '');
        const base = day + ' ' + name + ' ' + parts[0];
        return time ? base + ' ' + time.slice(0, 5) : base;
      }
      return name + ' ' + (parts[0] || '');
    }

    function sagFmtNum(v) {
      return Number(v || 0).toLocaleString('en-US');
    }

    function sagFmtMoney(v) {
      const n = Number(v || 0);
      const digits = n !== 0 && Math.abs(n) < 100 ? 2 : 0;
      return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }) + ' ريال';
    }

    function sagDeltaChip(d) {
      if (d === null || d === undefined || isNaN(d)) {
        return '<span class="admin-delta flat">' + WFT('admin.delta_na', '—') + '</span>';
      }
      const cls = d > 0 ? 'up' : (d < 0 ? 'down' : 'flat');
      const txt = (d > 0 ? '+' : '') + d + '%';
      return '<span class="admin-delta ' + cls + '">' + txt + '</span>';
    }

    function sagSmoothPath(pts) {
      if (pts.length < 3) {
        return 'M' + pts.map(p => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' L');
      }
      let d = 'M' + pts[0][0].toFixed(1) + ' ' + pts[0][1].toFixed(1);
      for (let i = 0; i < pts.length - 1; i++) {
        const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
        const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
        const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
        d += ' C' + c1x.toFixed(1) + ' ' + c1y.toFixed(1) + ' ' + c2x.toFixed(1) + ' ' + c2y.toFixed(1) + ' ' + p2[0].toFixed(1) + ' ' + p2[1].toFixed(1);
      }
      return d;
    }

    function sagSparkline(values, color) {
      const w = 140, h = 40, pad = 3;
      const vals = (values && values.length ? values : [0, 0]);
      const max = Math.max(1, ...vals);
      const pts = vals.map((v, i) => [pad + i * (w - 2 * pad) / (vals.length - 1), h - pad - (v / max) * (h - 2 * pad)]);
      const line = sagSmoothPath(pts);
      const area = line + ' L' + pts[pts.length - 1][0].toFixed(1) + ' ' + h + ' L' + pts[0][0].toFixed(1) + ' ' + h + ' Z';
      return '<svg class="admin-spark-svg" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" aria-hidden="true">' +
        '<path d="' + area + '" fill="' + color + '" opacity="0.14"/>' +
        '<path d="' + line + '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linecap="round"/></svg>';
    }

    function sagNiceScale(maxV) {
      const steps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 5000, 10000];
      const step = steps.find(s => maxV <= s * 3) || 50000;
      return { top: step * 3, step: step };
    }

    function sagTickText(v, top) {
      return top < 10 ? String(Math.round(v * 10) / 10) : sagFmtNum(Math.round(v));
    }

    function sagLineChart(labels, series) {
      const W = 660, H = 240, padL = 34, padR = 10, padT = 16, padB = 28;
      const innerW = W - padL - padR, innerH = H - padT - padB;
      const maxV = Math.max(0.01, ...series.flatMap(s => s.values));
      const sc = sagNiceScale(maxV), top = sc.top;
      const n = labels.length;
      const x = i => padL + (n === 1 ? innerW / 2 : i * innerW / (n - 1));
      const y = v => padT + innerH - (v / top) * innerH;
      let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">';
      for (let g = 0; g <= 3; g++) {
        const gv = sc.step * g, gy = y(gv);
        svg += '<line x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '" class="admin-chart-grid"/>' +
          '<text x="' + (padL - 6) + '" y="' + (gy + 4) + '" class="admin-chart-tick" text-anchor="end">' + sagTickText(gv, top) + '</text>';
      }
      const tickStep = Math.max(1, Math.ceil(n / 7));
      labels.forEach((lb, i) => {
        if (i % tickStep !== 0 && i !== n - 1) return;
        svg += '<text x="' + x(i) + '" y="' + (H - 8) + '" class="admin-chart-tick" text-anchor="middle">' + sagMonthLabel(lb) + '</text>';
      });
      series.forEach(s => {
        const fmt = s.fmt || sagFmtNum;
        const pts = s.values.map((v, i) => [x(i), y(v)]);
        const line = sagSmoothPath(pts);
        const area = line + ' L' + x(n - 1) + ' ' + (padT + innerH) + ' L' + x(0) + ' ' + (padT + innerH) + ' Z';
        svg += '<path d="' + area + '" fill="' + s.color + '" opacity="0.10"/>' +
          '<path d="' + line + '" fill="none" stroke="' + s.color + '" stroke-width="2.4" stroke-linecap="round"/>';
        pts.forEach((p, i) => {
          svg += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="3.2" fill="' + s.color + '">' +
            '<title>' + s.name + ': ' + fmt(s.values[i]) + ' — ' + sagMonthLabel(labels[i]) + '</title></circle>';
        });
      });
      return { svg: svg + '</svg>', geom: { W, H, padL, padR, padT, padB, top, n } };
    }

    function sagBindChartTooltip(container, labels, series, geom) {
      const svg = container.querySelector('svg');
      if (!svg || !geom.n) return;
      const NS = 'http://www.w3.org/2000/svg';
      const innerW = geom.W - geom.padL - geom.padR;
      const innerH = geom.H - geom.padT - geom.padB;
      const xFor = i => geom.padL + (geom.n === 1 ? innerW / 2 : i * innerW / (geom.n - 1));
      const yFor = v => geom.padT + innerH - (v / geom.top) * innerH;
      const guide = document.createElementNS(NS, 'line');
      guide.setAttribute('class', 'admin-chart-guide');
      guide.setAttribute('x1', '0');
      guide.setAttribute('x2', '0');
      guide.setAttribute('y1', String(geom.padT));
      guide.setAttribute('y2', String(geom.H - geom.padB));
      guide.style.display = 'none';
      svg.appendChild(guide);
      const dots = series.map(s => {
        const c = document.createElementNS(NS, 'circle');
        c.setAttribute('r', '4.5');
        c.setAttribute('fill', s.color);
        c.setAttribute('class', 'admin-chart-hover-dot');
        c.style.display = 'none';
        svg.appendChild(c);
        return c;
      });
      const tip = document.createElement('div');
      tip.className = 'admin-chart-tip';
      tip.style.display = 'none';
      container.appendChild(tip);
      svg.addEventListener('mousemove', (ev) => {
        const rect = svg.getBoundingClientRect();
        if (!rect.width) return;
        const vbX = (ev.clientX - rect.left) * (geom.W / rect.width);
        const span = innerW / Math.max(1, geom.n - 1);
        let i = Math.round((vbX - geom.padL) / span);
        i = Math.max(0, Math.min(geom.n - 1, i));
        const px = xFor(i);
        guide.setAttribute('x1', px.toFixed(1));
        guide.setAttribute('x2', px.toFixed(1));
        guide.style.display = '';
        series.forEach((s, si) => {
          dots[si].setAttribute('cx', px.toFixed(1));
          dots[si].setAttribute('cy', yFor(s.values[i] || 0).toFixed(1));
          dots[si].style.display = '';
        });
        tip.innerHTML = '<div class="tip-title">' + escapeHtml(sagMonthLabel(labels[i])) + '</div>' +
          series.map(s =>
            '<div class="tip-row"><span class="admin-legend-dot" style="background:' + s.color + '"></span>' +
            '<span>' + s.name + '</span><strong>' + escapeHtml(String((s.fmt || sagFmtNum)(s.values[i] || 0))) + '</strong></div>'
          ).join('');
        tip.style.display = 'block';
        const cRect = container.getBoundingClientRect();
        const half = tip.offsetWidth / 2;
        tip.style.left = Math.max(half + 4, Math.min(cRect.width - half - 4, ev.clientX - cRect.left)) + 'px';
      });
      svg.addEventListener('mouseleave', () => {
        guide.style.display = 'none';
        dots.forEach(c => { c.style.display = 'none'; });
        tip.style.display = 'none';
      });
    }
