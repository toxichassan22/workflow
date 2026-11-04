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

    function sagMonthLabelParts(iso) {
      const lang = (window.WFI18n && WFI18n.getLang && WFI18n.getLang()) || 'ar';
      const names = SAG_MONTHS[lang === 'en' ? 'en' : 'ar'];
      const s = String(iso);
      const parts = s.split('-');
      const m = parseInt(parts[1], 10);
      const name = names[(m || 1) - 1] || s;
      const year = parts[0] || '';
      if (parts.length >= 3) {
        const day = parseInt(parts[2], 10);
        return { full: day + ' ' + name + ' ' + year, month: day + ' ' + name, year: year };
      }
      return { full: name + ' ' + year, month: name, year: year };
    }

    function sagFmtNum(v) {
      return formatExactSystemNumber(Number(v || 0), true);
    }

    // The figure and its currency are computed apart on purpose. The currency
    // label is language-dependent (ريال سعودي / SAR) and used to be glued into
    // the number string and then split back out on the Arabic literal, so it
    // could never reach English: the split found nothing and the whole line
    // stayed Arabic. Numbers themselves never change with the language.
    function sagFmtMoneyParts(v) {
      const n = Number(v || 0);
      if (!Number.isFinite(n)) {
        return { number: '0', currency: wfTr('ريال سعودي') };
      }
      const rounded = Math.round(n * 100) / 100;
      const hasDecimals = Math.abs(rounded % 1) > 0.001;
      const val = hasDecimals ? rounded.toFixed(2) : rounded;
      return {
        number: formatExactSystemNumber(val, true),
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
      return sagFmtNum(v);
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
      const W = 880, H = 260, padT = 20, padB = 40;
      const n = labels.length;

      // Detect dual-axis needs when series have radically different units/magnitudes
      const s0Values = series[0]?.values || [];
      const s1Values = series[1]?.values || [];
      const max0 = Math.max(0.01, ...s0Values);
      const max1 = Math.max(0.01, ...s1Values);
      const isDual = series.length === 2 && (
        series[0].fmt !== series[1].fmt ||
        (max0 > 0 && max1 > 0 && (max0 / max1 >= 5 || max1 / max0 >= 5))
      );

      const sc0 = sagNiceScale(max0);
      const sc1 = isDual ? sagNiceScale(max1) : sc0;

      // The gutter is measured from the tick labels themselves: «1,500 points» is
      // wider than «1,500 نقطة», and the fixed 46-unit gutter clipped the English axis.
      const tickGutter = (s, step, top) => {
        let widest = 0;
        for (let g = 0; g <= 3; g++) {
          widest = Math.max(widest, sagTickWidth((s.fmt || sagTickText)(step * g, top)));
        }
        return Math.ceil(widest) + 14;
      };
      const padL = Math.max(46, tickGutter(series[0] || {}, sc0.step, sc0.top));
      const padR = Math.max(46, (isDual && series[1]) ? tickGutter(series[1], sc1.step, sc1.top) : 0);
      const innerW = W - padL - padR, innerH = H - padT - padB;

      const x = i => padL + (n <= 1 ? innerW / 2 : i * innerW / (n - 1));
      const yFor = (v, sIdx) => {
        const sc = (isDual && sIdx === 1) ? sc1 : sc0;
        return padT + innerH - (Math.max(0, v) / sc.top) * innerH;
      };

      let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" preserveAspectRatio="xMidYMid meet">';

      // Horizontal dashed grid lines and Y ticks
      for (let g = 0; g <= 3; g++) {
        const gy = padT + innerH - (g / 3) * innerH;
        svg += '<line x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '" class="admin-chart-grid" stroke-dasharray="3,3"/>';
        // Left Y tick (Series 0)
        const v0 = sc0.step * g;
        const tickTxt0 = (series[0]?.fmt || sagTickText)(v0, sc0.top);
        svg += '<text x="' + (padL - 8) + '" y="' + (gy + 4) + '" class="admin-chart-tick admin-chart-tick-left" text-anchor="end">' + tickTxt0 + '</text>';
        // Right Y tick (Series 1 if dual)
        if (isDual && series[1]) {
          const v1 = sc1.step * g;
          const tickTxt1 = (series[1].fmt || sagTickText)(v1, sc1.top);
          svg += '<text x="' + (W - padR + 8) + '" y="' + (gy + 4) + '" class="admin-chart-tick admin-chart-tick-right" text-anchor="start">' + tickTxt1 + '</text>';
        }
      }

      // X-axis ticks & vertical dashed guidelines
      // When n <= 14 (typical 12-month rollup like in reference image), show EVERY single month!
      // When n > 14 (e.g. 24 months), step by 2 so 12 ticks are evenly distributed.
      const tickStep = (n <= 14) ? 1 : Math.max(1, Math.ceil(n / 12));
      const candidates = [];
      if (tickStep <= 1) {
        for (let i = 0; i < n; i++) candidates.push(i);
      } else {
        const numIntervals = Math.max(1, Math.round((n - 1) / tickStep));
        for (let k = 0; k <= numIntervals; k++) {
          const idx = Math.round(k * (n - 1) / numIntervals);
          if (!candidates.length || candidates[candidates.length - 1] !== idx) candidates.push(idx);
        }
      }

      candidates.forEach(i => {
        const px = x(i);
        const lp = sagMonthLabelParts(labels[i]);
        // Vertical dashed guideline (like OpenAI/OpenRouter reference)
        svg += '<line x1="' + px.toFixed(1) + '" y1="' + padT + '" x2="' + px.toFixed(1) + '" y2="' + (padT + innerH) + '" class="admin-chart-grid-v"/>';
        // Month label (top line)
        svg += '<text x="' + px.toFixed(1) + '" y="' + (H - 18) + '" class="admin-chart-tick" text-anchor="middle">' + escapeHtml(lp.month) + '</text>';
        // Year label (bottom line)
        svg += '<text x="' + px.toFixed(1) + '" y="' + (H - 6) + '" class="admin-chart-tick-sub" text-anchor="middle">' + escapeHtml(lp.year) + '</text>';
      });

      // Solid baseline
      svg += '<line x1="' + padL + '" y1="' + (padT + innerH) + '" x2="' + (W - padR) + '" y2="' + (padT + innerH) + '" class="admin-chart-baseline"/>';

      // Series curves
      series.forEach((s, sIdx) => {
        const fmt = s.fmt || sagFmtNum;
        const pts = s.values.map((v, i) => [x(i), yFor(v, sIdx)]);
        const line = sagSmoothPath(pts);
        const area = line + ' L' + x(n - 1) + ' ' + (padT + innerH) + ' L' + x(0) + ' ' + (padT + innerH) + ' Z';
        svg += '<path d="' + area + '" fill="' + s.color + '" opacity="0.10"/>' +
          '<path d="' + line + '" fill="none" stroke="' + s.color + '" stroke-width="2.2" stroke-linecap="round"/>';
        // Only draw dots at non-zero peaks so the zero baseline is not cluttered with dots!
        pts.forEach((p, i) => {
          if ((s.values[i] || 0) > 0) {
            svg += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="2.8" fill="' + s.color + '">' +
              '<title>' + s.name + ': ' + fmt(s.values[i]) + ' — ' + sagMonthLabel(labels[i]) + '</title></circle>';
          }
        });
      });

      return { svg: svg + '</svg>', geom: { W, H, padL, padR, padT, padB, top: sc0.top, top1: sc1.top, isDual, n } };
    }

    function sagBindChartTooltip(container, labels, series, geom) {
      const svg = container.querySelector('svg');
      if (!svg || !geom.n) return;
      const NS = 'http://www.w3.org/2000/svg';
      const innerW = geom.W - geom.padL - geom.padR;
      const innerH = geom.H - geom.padT - geom.padB;
      const xFor = i => geom.padL + (geom.n === 1 ? innerW / 2 : i * innerW / (geom.n - 1));
      const yFor = (v, sIdx) => {
        const top = (geom.isDual && sIdx === 1) ? (geom.top1 || geom.top) : geom.top;
        return geom.padT + innerH - (Math.max(0, v) / top) * innerH;
      };
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
          dots[si].setAttribute('cy', yFor(s.values[i] || 0, si).toFixed(1));
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
