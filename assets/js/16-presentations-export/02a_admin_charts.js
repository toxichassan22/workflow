/* 16-presentations-export/02a_admin_charts.js — the shared SVG chart layer:
   line/donut builders, axis labels, hover tooltip, sparklines and the
   points/money formatters feeding them. Drives the super-admin activity chart
   (renderSagActivityChart) and the tenant copy in 02-settings-branding. Classic
   script, same shared global scope as every other part file. */

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
        { name: WFT('admin.legend_spend', 'المصروفات'), values: spendSeries, color: 'var(--chart-3)', fmt: sagFmtPoints },
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

    // ── SVG data-viz helpers (no icon glyphs; charts are genuine data
    //    rendering and keep the no-icons rule intact) ──

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

    // The figure and its currency are computed apart on purpose. The currency
    // label is language-dependent (ريال سعودي / SAR) and used to be glued into
    // the number string and then split back out on the Arabic literal, so it
    // could never reach English: the split found nothing and the whole line
    // stayed Arabic. Numbers themselves never change with the language.
    function sagFmtMoneyParts(v) {
      const n = Number(v || 0);
      const digits = n !== 0 && Math.abs(n) < 100 ? 2 : 0;
      return {
        number: n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }),
        currency: wfTr('ريال سعودي')
      };
    }

    function sagFmtMoney(v) {
      const parts = sagFmtMoneyParts(v);
      return parts.number + ' ' + parts.currency;
    }

    function sagFmtMoneyHtml(v) {
      const parts = sagFmtMoneyParts(v);
      return '<span dir="ltr">' + escapeHtml(parts.number) + '</span>'
        + ' <span class="money-currency">' + escapeHtml(parts.currency) + '</span>';
    }

    // Wallet figures render as points — the client never sees a currency unit
    // on its balance, only the counting unit the platform bills in.
    function sagFmtPointsParts(v) {
      const parts = sagFmtMoneyParts(v);
      parts.currency = wfTr('نقطة');
      return parts;
    }

    function sagFmtPoints(v) {
      const parts = sagFmtPointsParts(v);
      return parts.number + ' ' + parts.currency;
    }

    function sagFmtPointsHtml(v) {
      const parts = sagFmtPointsParts(v);
      return '<span dir="ltr">' + escapeHtml(parts.number) + '</span>'
        + ' <span class="money-currency">' + escapeHtml(parts.currency) + '</span>';
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
        const c1x = p1[0] + (p2[0] - p0[0]) / 6;
        const c2x = p2[0] - (p3[0] - p1[0]) / 6;
        // Catmull-Rom control points overshoot past a segment's endpoints when
        // a flat stretch sits next to a steep jump — that is what dipped the
        // curve under the x-axis ahead of a spike. Clamping each control point
        // to the segment's vertical band keeps the whole curve between its two
        // endpoints, so a zero floor can never be crossed visually.
        const yLo = Math.min(p1[1], p2[1]), yHi = Math.max(p1[1], p2[1]);
        const c1y = Math.max(yLo, Math.min(yHi, p1[1] + (p2[1] - p0[1]) / 6));
        const c2y = Math.max(yLo, Math.min(yHi, p2[1] - (p3[1] - p1[1]) / 6));
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

    // Tick-label width in viewBox units, measured on the same font the
    // .admin-chart-tick class renders (600/10px, page family). Canvas is a
    // best-effort ruler — jsdom and friends get the per-character estimate.
    var sagTickCtx;
    function sagTickWidth(text) {
      try {
        if (sagTickCtx === undefined) {
          sagTickCtx = document.createElement('canvas').getContext('2d');
          if (sagTickCtx) {
            sagTickCtx.font = '600 10px ' + (getComputedStyle(document.body).fontFamily || 'sans-serif');
          }
        }
        if (sagTickCtx) return sagTickCtx.measureText(String(text)).width;
      } catch (e) { /* measured width is best-effort; fall through to estimate */ }
      return String(text).length * 5.5;
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
      // X labels sit on a coarse grid plus both range edges. The edge labels
      // are pinned to the viewBox borders — text-anchor start/end is
      // direction-relative, so on the RTL page the physical edge flips — which
      // keeps a long month name inside the frame instead of clipped at the
      // border. A grid tick whose label would touch a kept neighbour is
      // dropped; the two edge labels always render.
      const rtl = typeof document !== 'undefined' && document.documentElement.dir === 'rtl';
      const tickText = i => sagMonthLabel(labels[i]);
      const maxLabelW = Math.max(1, ...labels.map((lb, i) => sagTickWidth(tickText(i))));
      const maxTicks = Math.max(2, Math.floor(innerW / (maxLabelW + 14)));
      const tickStep = Math.max(1, Math.ceil(n / maxTicks));
      const candidates = [];
      for (let i = 0; i < n; i += tickStep) candidates.push(i);
      if (n > 1 && candidates[candidates.length - 1] !== n - 1) candidates.push(n - 1);
      const tickBox = i => {
        const w = sagTickWidth(tickText(i));
        if (n > 1 && i === 0) return [2, 2 + w];
        if (i === n - 1 && n > 1) return [W - 2 - w, W - 2];
        return [x(i) - w / 2, x(i) + w / 2];
      };
      const kept = [];
      candidates.forEach(i => {
        if (!kept.length) { kept.push(i); return; }
        if (i === n - 1) {
          while (kept.length > 1 && tickBox(kept[kept.length - 1])[1] + 4 > tickBox(i)[0]) kept.pop();
          kept.push(i);
          return;
        }
        if (tickBox(kept[kept.length - 1])[1] + 4 <= tickBox(i)[0]) kept.push(i);
      });
      labels.forEach((lb, i) => {
        if (kept.indexOf(i) === -1) return;
        const anchor = n === 1 ? 'middle'
          : i === 0 ? (rtl ? 'end' : 'start')
          : i === n - 1 ? (rtl ? 'start' : 'end') : 'middle';
        const lx = n === 1 ? x(i) : (i === 0 ? 2 : (i === n - 1 ? W - 2 : x(i)));
        svg += '<text x="' + lx + '" y="' + (H - 8) + '" class="admin-chart-tick" text-anchor="' + anchor + '">' + tickText(i) + '</text>';
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
