/* 10-financial-report-timeline/03_timeline_board.js — the visual project timeline. */

    // S5: Timeline. The client enters a start date and an end date for the project and for
    // each phase; the duration, the year/quarter labels and the board are all derived, so no
    // fact is ever filled twice.
    const TIMELINE_DAY_MS = 86400000;
    const TIMELINE_AXIS_PX_PER_DAY = 2;
    const TIMELINE_CARD_MIN_PX = 64;
    // Spans up to three years tick months; longer ones tick quarters so the axis stays readable.
    const TIMELINE_MONTH_TICK_MAX_MONTHS = 36;
    const TIMELINE_QUARTER_NAMES = ['Q1', 'Q2', 'Q3', 'Q4'];

    // The standard development phases a new project opens with; the client edits them freely.
    const TIMELINE_DEFAULT_PHASES = [
      'التصميم، الدراسات، التراخيص',
      'تجهيز الموقع والأساسات والهيكل الإنشائي',
      'استكمال الهيكل وأعمال الكهرباء والميكانيكا',
      'التشطيبات والأعمال الخارجية',
      'الاختبارات والتسليم والتسويق',
    ];

    // Phases live in a small model — {name, start, end, notes} with ISO dates — and the board
    // is a pure render of it, so collecting rows never scrapes positioned DOM.
    let timelinePhases = [];
    let timelineEditingIndex = -1;

    function addTimelineTable(form) {
      const div = document.createElement('div');
      div.className = 'tenant-form-section';
      div.id = 'section-timeline';
      div.dataset.section = 'section-timeline';
      div.innerHTML = `
        <h3 class="tenant-section-title">الجدول الزمني للمشروع</h3>
        <div class="tenant-grid" style="grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px">
          <div class="tenant-field"><label>تاريخ البداية</label><input type="date" id="tlStartDate" data-key="timeline_start_date" data-type="text" onchange="recalcTimeline()"></div>
          <div class="tenant-field"><label>تاريخ النهاية</label><input type="date" id="tlEndDate" data-key="timeline_end_date" data-type="text" onchange="recalcTimeline()"></div>
          <div class="tenant-field"><label>مدة المشروع</label><input type="text" id="tlDuration" readonly class="readonly-highlight"></div>
        </div>
        <input type="hidden" id="tlYears" data-key="timeline_years" data-type="number">
        <div id="timelineDatesWarning" class="validation-panel error" hidden>تاريخ النهاية قبل تاريخ البداية</div>
        <div id="timelineRangeWarning" class="validation-panel error" hidden>بعض المراحل خارج فترة المشروع</div>
        <div class="tl-board-scroll"><div id="timelineBoard" class="tl-board"></div></div>
        <div id="timelineUndated" class="tl-undated" hidden></div>
        <div id="timelineEmpty" class="tl-empty" hidden>لا توجد مراحل مدخلة.</div>
        <button type="button" class="btn ghost small" style="margin-top:10px" onclick="openTimelinePhaseEditor(-1)">إضافة مرحلة</button>
        <div id="timelinePhaseEditor" class="tl-editor" hidden>
          <div class="tl-editor-title">بيانات المرحلة</div>
          <div class="tenant-grid" style="grid-template-columns:2fr 1fr 1fr;gap:12px">
            <div class="tenant-field"><label>اسم المرحلة</label><input type="text" id="tlPhaseName" list="tlPhaseNames"></div>
            <div class="tenant-field"><label>تاريخ البداية</label><input type="date" id="tlPhaseStart" onchange="timelineEditorLiveUpdate()"></div>
            <div class="tenant-field"><label>تاريخ النهاية</label><input type="date" id="tlPhaseEnd" onchange="timelineEditorLiveUpdate()"></div>
          </div>
          <div class="tenant-field"><label>الملاحظات</label><input type="text" id="tlPhaseNotes"></div>
          <div class="tl-editor-meta"><span id="tlPhaseDurationText"></span><span id="tlPhaseError" class="tl-editor-error"></span></div>
          <div class="tl-editor-actions">
            <button type="button" class="btn small" onclick="saveTimelinePhaseEditor()">حفظ</button>
            <button type="button" class="btn danger small" id="tlPhaseDelete" onclick="deleteTimelinePhaseFromEditor()" hidden>حذف</button>
            <button type="button" class="btn ghost small" onclick="closeTimelinePhaseEditor()">إلغاء</button>
          </div>
        </div>
        <datalist id="tlPhaseNames"></datalist>
        <input type="hidden" data-key="timeline_table_data" data-type="text" id="timelineTableData">
      `;
      div.querySelector('.tenant-section-title')?.replaceWith(
        createProjectSectionHeader('section-timeline', 'الجدول الزمني للمشروع')
      );
      const list = div.querySelector('#tlPhaseNames');
      TIMELINE_DEFAULT_PHASES.forEach(name => {
        const option = document.createElement('option');
        option.value = name;
        list.appendChild(option);
      });
      form.appendChild(div);
      recalcTimeline();
    }

    // A date the client picks (YYYY-MM-DD); a stored month-only value (YYYY-MM) maps to its
    // first day so pre-migration drafts keep working.
    function parseTimelineDate(raw) {
      const match = String(raw || '').trim().match(/^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$/);
      if (!match) return null;
      const year = parseInt(match[1], 10);
      const month = parseInt(match[2], 10);
      const day = match[3] ? parseInt(match[3], 10) : 1;
      if (month < 1 || month > 12 || day < 1 || day > 31) return null;
      return { year, month, day, index: year * 12 + (month - 1), ms: Date.UTC(year, month - 1, day) };
    }

    function parseTimelineStartValue(raw) {
      return parseTimelineDate(raw);
    }

    function timelineProjectStart() {
      // Once the section is built the input is the truth — a cleared date must stay cleared;
      // the stored value only leads while the section is not on screen.
      const input = document.getElementById('tlStartDate');
      if (input) return parseTimelineDate(input.value);
      return parseTimelineDate(tenantProjectData?.timeline_start_date)
        || (() => {
          const year = parseInt(tenantProjectData?.timeline_start_year, 10);
          return Number.isFinite(year) ? parseTimelineDate(year + '-01-01') : null;
        })();
    }

    function timelineProjectEnd() {
      const input = document.getElementById('tlEndDate');
      if (input) return parseTimelineDate(input.value);
      return parseTimelineDate(tenantProjectData?.timeline_end_date);
    }

    function timelineProjectPeriod() {
      const start = timelineProjectStart();
      const end = timelineProjectEnd();
      if (!start || !end || end.ms < start.ms) return null;
      return { start, end };
    }

    function timelineDateToIso(ms) {
      const date = new Date(ms);
      return date.getUTCFullYear() + '-' + String(date.getUTCMonth() + 1).padStart(2, '0') + '-' + String(date.getUTCDate()).padStart(2, '0');
    }

    // Month picker values land on the first of the month so they stay valid in date inputs.
    function normalizeTimelineInputDate(raw) {
      const parsed = parseTimelineDate(raw);
      return parsed ? timelineDateToIso(parsed.ms) : '';
    }

    function formatTimelineMonth(index) {
      if (!Number.isFinite(index)) return '';
      return ((index % 12) + 1) + '/' + Math.floor(index / 12);
    }

    // A full date prints day/month/year; a month-only one keeps the old month/year look.
    function formatTimelineStart(raw) {
      const parsed = parseTimelineDate(raw);
      if (!parsed) return String(raw || '').trim();
      return String(raw || '').trim().split('-').length === 3
        ? parsed.day + '/' + parsed.month + '/' + parsed.year
        : formatTimelineMonth(parsed.index);
    }

    function timelineSpanDays(startMs, endMs) {
      return Math.round((endMs - startMs) / TIMELINE_DAY_MS) + 1;
    }

    // Calendar-aware humanization, inclusive of both ends: «سنة و6 شهور», «4 شهور», «12 يوم».
    function timelineDurationText(startMs, endMs) {
      if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) return '';
      const start = new Date(startMs);
      const end = new Date(endMs + TIMELINE_DAY_MS);
      let months = (end.getUTCFullYear() - start.getUTCFullYear()) * 12 + (end.getUTCMonth() - start.getUTCMonth());
      let days = end.getUTCDate() - start.getUTCDate();
      if (days < 0) {
        months -= 1;
        days += new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), 0)).getUTCDate();
      }
      const years = Math.floor(months / 12);
      months %= 12;
      const parts = [];
      if (years) parts.push(WFT('timeline.duration_year', '{n} سنة', { n: years }));
      if (months) parts.push(WFT('timeline.duration_month', '{n} شهر', { n: months }));
      if (days) parts.push(WFT('timeline.duration_day', '{n} يوم', { n: days }));
      return parts.join(WFT('timeline.duration_join', ' و'));
    }

    // Everything downstream of the two date fields: the conflict flag, the duration label and
    // the stored «timeline_years» derivative the rest of the system still reads.
    function refreshTimelinePeriod() {
      const start = timelineProjectStart();
      const end = timelineProjectEnd();
      const invalid = !!(start && end && end.ms < start.ms);
      const warning = document.getElementById('timelineDatesWarning');
      if (warning) warning.hidden = !invalid;
      const period = invalid ? null : timelineProjectPeriod();
      const durationInput = document.getElementById('tlDuration');
      if (durationInput) durationInput.value = period ? timelineDurationText(period.start.ms, period.end.ms) : '';
      const yearsInput = document.getElementById('tlYears');
      if (yearsInput) {
        yearsInput.value = period
          ? String(roundSystemNumber(timelineSpanDays(period.start.ms, period.end.ms) / 365.25))
          : '';
      }
    }

    function renderTimelineBoard() {
      const board = document.getElementById('timelineBoard');
      if (!board) return;
      const undatedHost = document.getElementById('timelineUndated');
      const empty = document.getElementById('timelineEmpty');
      const rangeWarning = document.getElementById('timelineRangeWarning');
      board.innerHTML = '';
      delete board.dataset.axisStart;
      if (undatedHost) { undatedHost.innerHTML = ''; undatedHost.hidden = true; }
      if (rangeWarning) rangeWarning.hidden = true;

      const period = timelineProjectPeriod();
      const dated = [];
      const undated = [];
      timelinePhases.forEach((phase, index) => {
        const start = parseTimelineDate(phase.start);
        const end = parseTimelineDate(phase.end);
        if (start && end && end.ms >= start.ms) dated.push({ ...phase, startDate: start, endDate: end, index });
        else undated.push({ ...phase, index });
      });

      if (empty) empty.hidden = !!(dated.length || undated.length);

      if (undatedHost && undated.length) {
        undatedHost.hidden = false;
        const title = document.createElement('div');
        title.className = 'tl-undated-title';
        title.textContent = 'مراحل غير مجدولة';
        undatedHost.appendChild(title);
        undated.forEach(phase => {
          const chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'tl-chip';
          chip.textContent = (phase.name || '').trim() || '—';
          chip.title = chip.textContent;
          chip.addEventListener('click', () => openTimelinePhaseEditor(phase.index));
          undatedHost.appendChild(chip);
        });
      }

      if (!dated.length) return;

      // The axis spans the project period, stretching only as far as the phases demand.
      let axisStart = period ? period.start.ms : null;
      let axisEnd = period ? period.end.ms : null;
      dated.forEach(phase => {
        axisStart = axisStart === null ? phase.startDate.ms : Math.min(axisStart, phase.startDate.ms);
        axisEnd = axisEnd === null ? phase.endDate.ms : Math.max(axisEnd, phase.endDate.ms);
      });
      const spanDays = Math.max(1, Math.round((axisEnd - axisStart) / TIMELINE_DAY_MS) + 1);
      const boardWidth = Math.max(520, spanDays * TIMELINE_AXIS_PX_PER_DAY);
      board.style.minWidth = boardWidth + 'px';
      board.dataset.axisStart = String(axisStart);
      const dayToPx = offsetDays => Math.round(offsetDays * TIMELINE_AXIS_PX_PER_DAY);

      // The project band makes an out-of-period phase visible instead of silently letting it
      // stretch past its own dates.
      if (period) {
        const band = document.createElement('div');
        band.className = 'tl-project-band';
        band.style.insetInlineStart = dayToPx((period.start.ms - axisStart) / TIMELINE_DAY_MS) + 'px';
        band.style.inlineSize = dayToPx(timelineSpanDays(period.start.ms, period.end.ms)) + 'px';
        board.appendChild(band);
      }

      const axis = document.createElement('div');
      axis.className = 'tl-axis';
      const tickMonths = spanDays <= TIMELINE_MONTH_TICK_MAX_MONTHS * 31 ? 1 : 3;
      const axisStartDate = new Date(axisStart);
      let cursor = new Date(Date.UTC(axisStartDate.getUTCFullYear(), axisStartDate.getUTCMonth(), 1));
      while (cursor.getTime() <= axisEnd) {
        const ms = cursor.getTime();
        if (ms >= axisStart) {
          const tick = document.createElement('div');
          tick.className = 'tl-tick' + (cursor.getUTCMonth() === 0 ? ' tl-tick-year' : '');
          tick.style.insetInlineStart = dayToPx((ms - axisStart) / TIMELINE_DAY_MS) + 'px';
          const label = document.createElement('span');
          label.className = 'tl-tick-label';
          label.textContent = formatTimelineMonth(cursor.getUTCFullYear() * 12 + cursor.getUTCMonth());
          tick.appendChild(label);
          axis.appendChild(tick);
        }
        cursor = new Date(Date.UTC(cursor.getUTCFullYear(), cursor.getUTCMonth() + tickMonths, 1));
      }
      board.appendChild(axis);

      // Greedy lane packing: a phase joins the first lane whose previous card has already ended.
      const sorted = dated.slice().sort((a, b) => a.startDate.ms - b.startDate.ms || a.endDate.ms - b.endDate.ms);
      const laneEnds = [];
      const lanes = [];
      sorted.forEach(phase => {
        let lane = laneEnds.findIndex(end => phase.startDate.ms > end);
        if (lane < 0) {
          lane = laneEnds.length;
          laneEnds.push(-Infinity);
          lanes.push([]);
        }
        lanes[lane].push(phase);
        laneEnds[lane] = phase.endDate.ms;
      });
      const outOfRange = dated.some(phase => period && (phase.startDate.ms < period.start.ms || phase.endDate.ms > period.end.ms));

      lanes.forEach(lanePhases => {
        const lane = document.createElement('div');
        lane.className = 'tl-lane';
        lanePhases.forEach(phase => {
          const card = document.createElement('button');
          card.type = 'button';
          const isOut = period && (phase.startDate.ms < period.start.ms || phase.endDate.ms > period.end.ms);
          card.className = 'tl-card' + (isOut ? ' tl-out' : '');
          card.dataset.index = String(phase.index);
          card.style.insetInlineStart = dayToPx((phase.startDate.ms - axisStart) / TIMELINE_DAY_MS) + 'px';
          card.style.inlineSize = Math.max(TIMELINE_CARD_MIN_PX, dayToPx(timelineSpanDays(phase.startDate.ms, phase.endDate.ms))) + 'px';
          const name = document.createElement('span');
          name.className = 'tl-card-name';
          name.textContent = (phase.name || '').trim() || '—';
          const dur = document.createElement('span');
          dur.className = 'tl-card-dur';
          dur.textContent = timelineDurationText(phase.startDate.ms, phase.endDate.ms);
          card.append(name, dur);
          card.title = name.textContent + ' — ' + formatTimelineStart(phase.start) + ' إلى ' + formatTimelineStart(phase.end);
          card.addEventListener('click', () => {
            // A real drag sets the flag first, so the trailing click does not reopen the editor.
            if (!card.dataset.tlDragged) openTimelinePhaseEditor(phase.index);
          });
          card.addEventListener('pointerdown', event => timelineDragStart(event, phase.index, 'move', card));
          ['start', 'end'].forEach(edge => {
            const handle = document.createElement('span');
            handle.className = 'tl-handle tl-handle-' + edge;
            handle.addEventListener('pointerdown', event => {
              event.stopPropagation();
              timelineDragStart(event, phase.index, edge, card);
            });
            card.appendChild(handle);
          });
          lane.appendChild(card);
        });
        board.appendChild(lane);
      });

      if (rangeWarning) rangeWarning.hidden = !outOfRange;
    }

    // Optional visual editing of the same start/end pair: a drag moves the phase, the edge
    // handles resize it. Snaps to whole days — the date inputs stay the precise path.
    function timelineDragStart(event, index, mode, card) {
      if (event.button !== undefined && event.button !== 0) return;
      const phase = timelinePhases[index];
      const origStart = parseTimelineDate(phase?.start);
      const origEnd = parseTimelineDate(phase?.end);
      if (!phase || !origStart || !origEnd) return;
      event.preventDefault();
      const startX = event.clientX;
      let dragged = false;
      const applyDelta = deltaDays => {
        const shift = deltaDays * TIMELINE_DAY_MS;
        if (mode === 'move') {
          phase.start = timelineDateToIso(origStart.ms + shift);
          phase.end = timelineDateToIso(origEnd.ms + shift);
        } else if (mode === 'start') {
          phase.start = timelineDateToIso(Math.min(origEnd.ms, origStart.ms + shift));
        } else {
          phase.end = timelineDateToIso(Math.max(origStart.ms, origEnd.ms + shift));
        }
      };
      const onMove = moveEvent => {
        // The axis grows towards inline-start — the right edge in RTL — so dragging leftwards
        // moves a phase to a later date.
        const deltaPx = startX - moveEvent.clientX;
        if (!dragged && Math.abs(deltaPx) < 4) return;
        dragged = true;
        applyDelta(Math.round(deltaPx / TIMELINE_AXIS_PX_PER_DAY));
        const start = parseTimelineDate(phase.start);
        const end = parseTimelineDate(phase.end);
        const axisStart = Number(card.closest('.tl-board')?.dataset.axisStart);
        if (start && end && Number.isFinite(axisStart)) {
          card.style.insetInlineStart = Math.round((start.ms - axisStart) / TIMELINE_DAY_MS * TIMELINE_AXIS_PX_PER_DAY) + 'px';
          card.style.inlineSize = Math.max(TIMELINE_CARD_MIN_PX, Math.round(timelineSpanDays(start.ms, end.ms) * TIMELINE_AXIS_PX_PER_DAY)) + 'px';
          const dur = card.querySelector('.tl-card-dur');
          if (dur) dur.textContent = timelineDurationText(start.ms, end.ms);
          card.title = (phase.name || '').trim() + ' — ' + formatTimelineStart(phase.start) + ' إلى ' + formatTimelineStart(phase.end);
        }
      };
      const onUp = () => {
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
        if (dragged) {
          card.dataset.tlDragged = '1';
          setTimeout(() => { delete card.dataset.tlDragged; }, 0);
          saveTimelineData();
        }
      };
      document.addEventListener('pointermove', onMove);
      document.addEventListener('pointerup', onUp);
    }

    function openTimelinePhaseEditor(index) {
      const editor = document.getElementById('timelinePhaseEditor');
      if (!editor) return;
      timelineEditingIndex = index;
      const phase = index >= 0 ? (timelinePhases[index] || {}) : {};
      document.getElementById('tlPhaseName').value = phase.name || '';
      document.getElementById('tlPhaseStart').value = normalizeTimelineInputDate(phase.start);
      document.getElementById('tlPhaseEnd').value = normalizeTimelineInputDate(phase.end);
      document.getElementById('tlPhaseNotes').value = phase.notes || '';
      const deleteButton = document.getElementById('tlPhaseDelete');
      if (deleteButton) deleteButton.hidden = index < 0;
      timelineEditorLiveUpdate();
      editor.hidden = false;
      document.getElementById('tlPhaseName')?.focus();
    }

    function closeTimelinePhaseEditor() {
      const editor = document.getElementById('timelinePhaseEditor');
      if (editor) editor.hidden = true;
      timelineEditingIndex = -1;
    }

    function timelineEditorLiveUpdate() {
      const start = parseTimelineDate(document.getElementById('tlPhaseStart')?.value);
      const end = parseTimelineDate(document.getElementById('tlPhaseEnd')?.value);
      const duration = document.getElementById('tlPhaseDurationText');
      if (duration) duration.textContent = (start && end && end.ms >= start.ms) ? timelineDurationText(start.ms, end.ms) : '';
      const error = document.getElementById('tlPhaseError');
      if (error) error.textContent = (start && end && end.ms < start.ms) ? 'تاريخ النهاية قبل تاريخ البداية' : '';
    }

    function saveTimelinePhaseEditor() {
      const editor = document.getElementById('timelinePhaseEditor');
      if (!editor) return;
      const error = document.getElementById('tlPhaseError');
      const fail = message => { if (error) error.textContent = message; };
      const name = (document.getElementById('tlPhaseName')?.value || '').trim();
      if (!name) return fail('اسم المرحلة مطلوب');
      const startValue = document.getElementById('tlPhaseStart')?.value || '';
      const endValue = document.getElementById('tlPhaseEnd')?.value || '';
      if ((startValue && !endValue) || (!startValue && endValue)) return fail('تاريخ بداية المرحلة أو نهايتها غير محدد');
      const start = parseTimelineDate(startValue);
      const end = parseTimelineDate(endValue);
      if (start && end && end.ms < start.ms) return fail('تاريخ النهاية قبل تاريخ البداية');
      if (error) error.textContent = '';
      const next = {
        name,
        start: start ? timelineDateToIso(start.ms) : '',
        end: end ? timelineDateToIso(end.ms) : '',
        notes: (document.getElementById('tlPhaseNotes')?.value || '').trim()
      };
      if (timelineEditingIndex >= 0 && timelinePhases[timelineEditingIndex]) {
        timelinePhases[timelineEditingIndex] = next;
      } else {
        timelinePhases.push(next);
      }
      closeTimelinePhaseEditor();
      saveTimelineData();
    }

    function deleteTimelinePhaseFromEditor() {
      if (timelineEditingIndex >= 0) timelinePhases.splice(timelineEditingIndex, 1);
      closeTimelinePhaseEditor();
      saveTimelineData();
    }

    function addTimelinePhase(data = {}) {
      timelinePhases.push({
        name: String(data.name || ''),
        start: normalizeTimelineInputDate(data.start),
        end: normalizeTimelineInputDate(data.end),
        notes: String(data.notes || '')
      });
    }

    function removeTimelinePhase(index) {
      if (index < 0 || index >= timelinePhases.length) return;
      if (timelineEditingIndex === index) closeTimelinePhaseEditor();
      timelinePhases.splice(index, 1);
      saveTimelineData();
    }

    function collectTimelineRows() {
      return timelinePhases
        .map(phase => ({
          name: String(phase.name || ''),
          start: normalizeTimelineInputDate(phase.start),
          end: normalizeTimelineInputDate(phase.end),
          notes: String(phase.notes || '')
        }))
        .filter(phase => phase.name || phase.start || phase.end || phase.notes);
    }

    function saveTimelineData() {
      const hidden = document.getElementById('timelineTableData');
      if (hidden) hidden.value = JSON.stringify(collectTimelineRows());
      renderTimelineBoard();
      syncFinancialFromTimeline();
      if (typeof triggerAutoSaveDraft === 'function') triggerAutoSaveDraft();
    }

    function recalcTimeline() {
      refreshTimelinePeriod();
      renderTimelineBoard();
      syncFinancialFromTimeline();
    }

    // New projects open with the standard phases already named — a starting point the client
    // edits freely. They carry no invented dates, so they wait in the unscheduled lane until
    // the client dates them; drafts hydrate their own rows instead.
    function seedDefaultTimelinePhases() {
      if (!document.getElementById('timelineBoard')) return;
      if (timelinePhases.some(phase => (phase.name || '').trim())) return;
      timelinePhases = TIMELINE_DEFAULT_PHASES.map(name => ({ name, start: '', end: '', notes: '' }));
      const hidden = document.getElementById('timelineTableData');
      if (hidden) hidden.value = JSON.stringify(collectTimelineRows());
      renderTimelineBoard();
      syncFinancialFromTimeline();
    }

    // Drafts store {name, start, end, notes}. Rows saved by the quarter/duration table convert
    // to real dates against the project start; a name with nothing else lands unscheduled.
    function hydrateTimelinePhases(source) {
      const stored = typeof parseStoredProjectTable === 'function'
        ? parseStoredProjectTable(source?.timeline_table_data || source?.timelineRows)
        : [];
      timelinePhases = [];
      const startInput = document.getElementById('tlStartDate');
      const endInput = document.getElementById('tlEndDate');
      // The month-only picker predates the day-precision one: a «YYYY-MM» start lands on the
      // first of that month, a «YYYY-MM» end on its last day, a bare start year on January first.
      const normalizeStored = (raw, toMonthEnd) => {
        const text = String(raw || '').trim();
        const parsed = parseTimelineDate(text);
        if (!parsed) return '';
        const monthOnly = !/^\d{4}-\d{1,2}-\d{1,2}$/.test(text);
        return timelineDateToIso(monthOnly && toMonthEnd ? Date.UTC(parsed.year, parsed.month, 0) : parsed.ms);
      };
      let projectStart = startInput ? parseTimelineDate(startInput.value) : null;
      if (projectStart) {
        const iso = normalizeStored(startInput.value, false);
        if (startInput.value !== iso) startInput.value = iso;
      } else {
        const mapped = parseTimelineDate(source?.timeline_start_date)
          || (() => {
            const year = parseInt(source?.timeline_start_year, 10);
            return Number.isFinite(year) ? parseTimelineDate(year + '-01-01') : null;
          })();
        if (mapped) {
          projectStart = mapped;
          const iso = timelineDateToIso(mapped.ms);
          if (startInput) startInput.value = iso;
          tenantProjectData.timeline_start_date = iso;
        }
      }
      if (endInput && endInput.value) {
        const iso = normalizeStored(endInput.value, true);
        if (endInput.value !== iso) endInput.value = iso;
      } else if (endInput && projectStart && !source?.timeline_end_date) {
        // «عدد السنوات» used to define the end: a legacy draft with no stored end date maps its
        // span onto the calendar the same way — start plus that many years, minus a day.
        const legacyYears = parseInt(source?.timeline_years, 10);
        if (Number.isFinite(legacyYears) && legacyYears > 0) {
          const lastMonth = projectStart.index + legacyYears * 12 - 1;
          endInput.value = timelineDateToIso(Date.UTC(Math.floor(lastMonth / 12), (lastMonth % 12) + 1, 0));
        }
      }
      stored.forEach(row => {
        if (!row || typeof row !== 'object') return;
        let start = normalizeTimelineInputDate(row.start);
        let end = normalizeTimelineInputDate(row.end);
        if (!start && !end) {
          let year = parseInt(row.year, 10);
          let endYear = parseInt(row.endYear, 10);
          // Rows saved against a bare start year stored calendar years, not relative ones.
          const legacyYear = parseInt(source?.timeline_start_year, 10);
          if (!source?.timeline_start_date && Number.isFinite(legacyYear)) {
            if (Number.isFinite(year) && year >= 1000) year = Math.max(1, year - legacyYear + 1);
            if (Number.isFinite(endYear) && endYear >= 1000) endYear = Math.max(1, endYear - legacyYear + 1);
          }
          const quarterIndex = TIMELINE_QUARTER_NAMES.indexOf(String(row.quarter || '').trim());
          const duration = parseInt(row.duration, 10);
          if (projectStart && Number.isFinite(year) && quarterIndex >= 0) {
            const startMonth = projectStart.index + (year - 1) * 12 + quarterIndex * 3;
            start = timelineDateToIso(Date.UTC(Math.floor(startMonth / 12), startMonth % 12, 1));
            if (Number.isFinite(duration) && duration > 0) {
              const endMonth = startMonth + duration - 1;
              end = timelineDateToIso(Date.UTC(Math.floor(endMonth / 12), (endMonth % 12) + 1, 0));
            } else if (Number.isFinite(endYear)) {
              const endQuarterIndex = Math.max(0, TIMELINE_QUARTER_NAMES.indexOf(String(row.endQuarter || '').trim()));
              const endMonth = projectStart.index + (endYear - 1) * 12 + endQuarterIndex * 3 + 2;
              end = timelineDateToIso(Date.UTC(Math.floor(endMonth / 12), (endMonth % 12) + 1, 0));
            }
          }
        }
        timelinePhases.push({ name: String(row.name || ''), start, end, notes: String(row.notes || '') });
      });
      const hidden = document.getElementById('timelineTableData');
      if (hidden) hidden.value = JSON.stringify(collectTimelineRows());
      recalcTimeline();
    }

    // The timeline is the single source of truth for the development duration and the stage
    // list; the financial study mirrors them read-only so the two can never disagree.
    function syncFinancialFromTimeline() {
      const scheduleBody = document.querySelector('#scheduleTable tbody');
      const devYearsInput = document.getElementById('developmentYears');
      if (!scheduleBody && !devYearsInput) return;

      const period = timelineProjectPeriod();
      // «مدة تطوير المشروع» counts the annual buckets the period touches: thirteen months is
      // two development years, four months is one.
      const nextDevYears = period
        ? String(Math.max(1, Math.ceil(timelineSpanDays(period.start.ms, period.end.ms) / 365.25)))
        : '';
      let devYearsChanged = false;
      if (devYearsInput && devYearsInput.value !== nextDevYears) {
        devYearsInput.value = nextDevYears;
        devYearsChanged = true;
      }
      const devYears = Math.max(1, parseInt(devYearsInput?.value, 10) || 1);
      const recalculate = () => {
        if (window.__batchLoading || typeof calculateAll !== 'function') return;
        try { calculateAll(); } catch (e) { console.warn('calculateAll failed:', e); }
      };

      const namedStages = collectTimelineRows().filter(row => row.name.trim());
      const warning = document.getElementById('timelineStagesWarning');
      if (warning) warning.hidden = namedStages.length > 0;
      if (!scheduleBody) {
        if (devYearsChanged) recalculate();
        return;
      }

      // Percentages are this study's own data, so carry them over by stage name on every rebuild.
      const previous = new Map();
      scheduleBody.querySelectorAll('tr').forEach(tr => {
        const name = (tr.querySelector('[data-field="name"] input')?.value || '').trim();
        if (!name) return;
        previous.set(name, {
          costPct: tr.querySelector('[data-field="costPct"] input')?.value ?? 0,
          devPct: tr.querySelector('[data-field="devPct"] input')?.value ?? 0,
          year: tr.dataset.stageYear,
          endYear: tr.dataset.stageEndYear
        });
      });
      // An empty timeline used to wipe a just-restored schedule table. Keep the
      // already-hydrated stages until the user actually names phases.
      if (!namedStages.length) {
        if (devYearsChanged) recalculate();
        return;
      }

      // A phase's project-year is the annual bucket its start lands in, anchored to the
      // project start — or, while the period is still unset, to the earliest dated phase.
      const stageDates = namedStages.map(row => parseTimelineDate(row.start)?.ms).filter(Number.isFinite);
      const anchor = period ? period.start.ms : (stageDates.length ? Math.min(...stageDates) : NaN);
      const yearOf = ms => (Number.isFinite(anchor) && Number.isFinite(ms))
        ? Math.max(1, Math.floor((ms - anchor) / (365.25 * TIMELINE_DAY_MS)) + 1)
        : 1;

      const wasBatching = window.__batchLoading;
      window.__batchLoading = true;
      scheduleBody.innerHTML = '';
      namedStages.forEach(row => {
        const name = row.name.trim();
        const kept = previous.get(name) || {};
        const startRelative = Math.min(devYears, yearOf(parseTimelineDate(row.start)?.ms));
        const endRelative = Math.min(devYears, Math.max(startRelative, yearOf(parseTimelineDate(row.end)?.ms)));
        addScheduleStage({
          name,
          year: startRelative,
          endYear: endRelative,
          costPct: kept.costPct ?? 0,
          devPct: kept.devPct ?? 0
        });
      });
      window.__batchLoading = wasBatching;
      recalculate();
    }
