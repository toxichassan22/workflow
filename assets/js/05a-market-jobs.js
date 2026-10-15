    /* 05a-market-jobs.js - market-study background jobs: polling, reattach and
       the generate-button runners. One remembered job id per kind lives in
       state.activeMarketJobs so a click on a generate button re-attaches to a
       job that is still running instead of posting a duplicate, and a job that
       outlives the poll budget is reported as still running, never as a retry
       instruction. */

    const MARKET_JOB_POLL_LIMIT_MS = 40 * 60 * 1000;
    const MARKET_JOB_POLL_INTERVAL_MS = 2500;

    async function pollMarketStudyJob(jobId, onProgress, pollOpts) {
      const budgetMs = Number.isFinite(Number(pollOpts && pollOpts.budgetMs)) && Number(pollOpts.budgetMs) > 0
        ? Number(pollOpts.budgetMs) : MARKET_JOB_POLL_LIMIT_MS;
      const intervalMs = Number.isFinite(Number(pollOpts && pollOpts.intervalMs)) && Number(pollOpts.intervalMs) >= 0
        ? Number(pollOpts.intervalMs) : MARKET_JOB_POLL_INTERVAL_MS;
      const started = Date.now();
      let res = null;
      while (Date.now() - started < budgetMs) {
        await new Promise(resolve => setTimeout(resolve, intervalMs));
        res = await api('GET', '/api/market-study/jobs/' + encodeURIComponent(jobId));
        const status = String(res && res.status || '');
        if (typeof onProgress === 'function') onProgress(res);
        if (status === 'completed' || status === 'failed' || (res && res.failureReason)) break;
        if (!res || res.failureReason === 'job_not_found') break;
      }
      return res;
    }

    function marketJobStillRunningText() {
      return WFT('market.job_still_running', 'المهمة ما زالت تعمل في الخلفية.');
    }

    function marketJobResumedText() {
      return WFT('market.job_resumed', 'توجد مهمة قيد التنفيذ — جاري متابعة نتيجتها.');
    }

    function marketJobMap(state) {
      const jobs = state && state.activeMarketJobs;
      return (jobs && typeof jobs === 'object' && !Array.isArray(jobs)) ? jobs : {};
    }

    function rememberedMarketJob(kind) {
      return String(marketJobMap(getMarketStudyState())[kind] || '').trim();
    }

    function rememberMarketJob(kind, jobId) {
      const state = getMarketStudyState();
      const jobs = { ...marketJobMap(state) };
      if (jobId) jobs[kind] = String(jobId);
      else delete jobs[kind];
      state.activeMarketJobs = jobs;
      setMarketStudyState(state);
    }

    function marketJobSettled(res) {
      const status = String(res && res.status || '');
      return status === 'completed' || status === 'failed' || Boolean(res && res.failureReason);
    }

    function marketJobInFlight(res) {
      const status = String(res && res.status || '');
      return Boolean(res && res.success !== false && (status === 'running' || status === 'queued'));
    }

    async function resumeMarketJob(kind, onProgress, onResume) {
      const jobId = rememberedMarketJob(kind);
      if (!jobId) return null;
      const res = await api('GET', '/api/market-study/jobs/' + encodeURIComponent(jobId));
      const status = String(res && res.status || '');
      if (status !== 'running' && status !== 'queued') {
        rememberMarketJob(kind, '');
        return null;
      }
      if (typeof onResume === 'function') onResume(res);
      if (typeof onProgress === 'function') onProgress(res);
      return pollMarketStudyJob(jobId, onProgress);
    }

    async function runMarketCompetitorsJob(mode) {
      const generateBtn = document.getElementById('marketGenerateCompetitorsBtn');
      const fillBtn = document.getElementById('marketFillCompetitorsBtn');
      const note = document.getElementById('marketCompetitorsNote');
      if (generateBtn) generateBtn.disabled = true;
      if (fillBtn) fillBtn.disabled = true;
      showLoader(
        mode === 'fill' ? 'إكمال بيانات المنافسين' : 'توليد المنافسين',
        'جاري البحث عن المنافسين من المصادر المعتمدة...',
        12
      );
      try {
        let lastJobPct = 10;
        const onProgress = job => {
          const pct = Number(job && job.progress);
          if (Number.isFinite(pct) && pct > 0) lastJobPct = Math.min(pct, 99);
          updateLoaderProgress(lastJobPct,
            (job && job.message) || 'جاري البحث...');
        };
        let res = await resumeMarketJob('competitors', onProgress,
          () => { if (note) note.textContent = marketJobResumedText(); });
        const resumed = res !== null;
        if (!res) {
          const payload = collectMarketStudyRequestPayload();
          payload.mode = mode;
          res = await api('POST', '/api/market-study/competitors', payload);
          if (res && res.jobId && !Array.isArray(res.competitors)) {
            rememberMarketJob('competitors', res.jobId);
            updateLoaderProgress(10, res.message || 'بدأت المهمة في الخلفية...');
            res = await pollMarketStudyJob(res.jobId, onProgress);
          }
        }
        if (marketJobSettled(res)) rememberMarketJob('competitors', '');
        if (marketJobInFlight(res)) {
          const stillRunning = marketJobStillRunningText();
          if (note) note.textContent = stillRunning;
          toast(stillRunning);
          return;
        }
        if (!res || !res.success) {
          if (note) note.textContent = (res && (res.error || res.providerError)) || 'تعذر تحديث المنافسين.';
          toast((res && res.error) || 'تعذر تحديث المنافسين.');
          return;
        }
        const state = getMarketStudyState();
        state.competitors = res.competitors || state.competitors;
        state.sources = mergeMarketSourceRows(
          state.sources,
          res.sources || buildMarketCompetitorSourceRows(state.competitors)
        );
        applyMarketStudyState(state);
        persistMarketStudyFromDom();
        const extra = res.expansionNote || res.notes || '';
        const conflictCount = Array.isArray(res.conflictWarnings) ? res.conflictWarnings.length : 0;
        const doneNote = resumed
          ? WFT('market.job_done_count', 'اكتمل تحديث المنافسين — {n} في الجدول', { n: (res.competitors || []).length })
          : (mode === 'fill'
            ? WFT('market.fill_done', 'أُكملت بيانات {n} منافس', { n: res.updated || 0 })
            : WFT('market.table_replaced', 'تم استبدال الجدول بـ {n} منافس', { n: (res.competitors || []).length }));
        if (note) {
          note.textContent = doneNote +
            (conflictCount ? WFT('market.note_conflicts_kept', ' — تم الإبقاء على {n} قيمة حالية متعارضة', { n: conflictCount }) : '') +
            (res.searchVerified === false ? WFT('market.note_search_not_run', ' — لم يعمل البحث في الويب؛ الروابط معروضة كغير موثقة للمراجعة') : '') +
            ((res.outOfRadiusCount || 0) ? WFT('market.note_out_of_radius', ' — {n} منافس خارج النطاق المحدد', { n: res.outOfRadiusCount }) : '') +
            ((res.noEvidenceCount || 0) ? WFT('market.note_no_evidence', ' — {n} منافس لم تظهر أسماؤهم في نتائج البحث', { n: res.noEvidenceCount }) : '') +
            ((res.searchNotRunCount || 0) ? WFT('market.note_search_failed', ' — تعذر تنفيذ البحث عن {n} منافس', { n: res.searchNotRunCount }) : '') +
            ((res.missingPriceCount || 0) ? WFT('market.note_missing_price', ' — {n} منافس بلا سعر موثق', { n: res.missingPriceCount }) : '') +
            (res.providerError ? WFT('market.note_provider_error', ' — خطأ مزود البحث: {err}', { err: res.providerError }) : '') +
            (extra ? ' — ' + extra : '');
        }
        toast(res.partial
          ? 'اكتمل التحديث بنتيجة جزئية — التفاصيل موضحة أسفل الجدول'
          : (resumed ? doneNote
            : (mode === 'fill' ? 'تم إكمال بيانات المنافسين دون حذف الصفوف' : 'تم استبدال جدول المنافسين بالنتيجة الجديدة')));
        updateLoaderProgress(100, res.partial ? 'اكتمل التحديث بنتيجة جزئية' : 'اكتمل تحديث المنافسين');
      } catch (error) {
        toast(error.message || 'تعذر تحديث المنافسين');
      } finally {
        hideLoader();
        if (generateBtn) generateBtn.disabled = false;
        if (fillBtn) fillBtn.disabled = false;
      }
    }

    function renderMarketSummaryCompare(current, incoming, currentSwot, incomingSwot) {
      const host = document.getElementById('marketSummaryCompare');
      if (!host) return;
      host.hidden = false;
      const currentOneBlock = arguments[4] || '';
      const incomingOneBlock = arguments[5] || '';
      const swotBlocks = values => MARKET_STUDY_SWOT_SECTIONS.map(item =>
        (item.label + '\n' + ((values && values[item.key]) || '')).trim()
      ).join('\n\n');
      const currentText = [
        marketSummaryAnalysisText(current),
        currentOneBlock ? ('ملخص دراسة سوق العمل' + '\n' + currentOneBlock) : '',
        'تحليل SWOT',
        swotBlocks(currentSwot)
      ].filter(part => String(part || '').trim()).join('\n\n');
      const incomingText = [
        marketSummaryAnalysisText(incoming),
        incomingOneBlock ? ('ملخص دراسة سوق العمل' + '\n' + incomingOneBlock) : '',
        'تحليل SWOT',
        swotBlocks(incomingSwot)
      ].filter(part => String(part || '').trim()).join('\n\n');
      host.innerHTML =
        '<div class="summary-compare">' +
        '<div><label>النسخة الحالية</label><textarea rows="12" readonly>' + currentText.replace(/</g, '&lt;') + '</textarea></div>' +
        '<div><label>النسخة الجديدة</label><textarea rows="12" readonly>' + incomingText.replace(/</g, '&lt;') + '</textarea></div>' +
        '</div>' +
        '<div class="market-actions">' +
        '<button type="button" class="btn primary" id="marketAcceptSummaryBtn">استبدال بالنسخة الجديدة</button>' +
        '<button type="button" class="btn ghost" id="marketKeepSummaryBtn">الإبقاء على الحالية</button>' +
        '</div>';
      document.getElementById('marketAcceptSummaryBtn')?.addEventListener('click', () => {
        if (!marketSummaryPending) return;
        const state = getMarketStudyState();
        state.summary = marketSummaryPending.summary;
        state.swot = marketSummaryPending.swot || state.swot;
        state.sources = mergeMarketSourceRows(
          marketSummaryPending.sources,
          buildMarketCompetitorSourceRows(state.competitors)
        );
        state.decision = marketSummaryPending.decision;
        state.disclaimer = marketSummaryPending.disclaimer;
        state.one_block_summary = marketSummaryPending.oneBlockSummary || '';
        applyMarketStudyState(state);
        persistMarketStudyFromDom();
        marketSummaryPending = null;
        host.hidden = true;
        host.innerHTML = '';
        toast('تم استبدال الملخص والمصادر بالنسخة الجديدة');
      });
      document.getElementById('marketKeepSummaryBtn')?.addEventListener('click', () => {
        marketSummaryPending = null;
        host.hidden = true;
        host.innerHTML = '';
        toast('تم الإبقاء على الملخص الحالي');
      });
    }

    async function runMarketSummaryJob() {
      const btn = document.getElementById('marketGenerateSummaryBtn');
      const fail = document.getElementById('marketSummaryFailure');
      if (btn) btn.disabled = true;
      if (fail) fail.textContent = '';
      // The summary scope is mandatory: a listed mode (city/district) with
      // no names cannot bind any figure, so the run is refused up front
      // instead of failing minutes later on the server.
      const scopeCheck = (typeof collectMarketSummaryScope === 'function')
        ? collectMarketSummaryScope()
        : { mode: 'distance', places: [] };
      if ((scopeCheck.mode === 'city' || scopeCheck.mode === 'district')
          && !(scopeCheck.places || []).length) {
        const message = WFT('market.summary_scope_required', 'أضف مدينة أو حيًا واحدًا على الأقل لنطاق الملخص');
        if (fail) fail.textContent = message;
        toast(message);
        document.getElementById('marketSummaryScopeAddBtn')?.focus();
        if (btn) btn.disabled = false;
        return;
      }
      showLoader('توليد ملخص السوق', 'جاري البحث في المصادر الرسمية وكتابة الملخص التنفيذي...', 12);
      try {
        let lastJobPct = 10;
        const onProgress = job => {
          const pct = Number(job && job.progress);
          if (Number.isFinite(pct) && pct > 0) lastJobPct = Math.min(pct, 99);
          updateLoaderProgress(lastJobPct,
            (job && job.message) || 'جاري إعداد الملخص...');
        };
        const priorState = getMarketStudyState();
        const currentSummary = marketSummaryState(priorState.summary);
        const currentSwot = { ...(priorState.swot || {}) };
        const currentOneBlock = String(priorState.one_block_summary || '').trim();
        let res = await resumeMarketJob('summary', onProgress,
          () => { if (fail) fail.textContent = marketJobResumedText(); });
        if (!res) {
          const payload = collectMarketStudyRequestPayload();
          res = await api('POST', '/api/market-study/summary', payload);
          if (res && res.jobId && !res.summary) {
            rememberMarketJob('summary', res.jobId);
            updateLoaderProgress(10, res.message || 'بدأت المهمة في الخلفية...');
            res = await pollMarketStudyJob(res.jobId, onProgress);
          }
        }
        if (marketJobSettled(res)) rememberMarketJob('summary', '');
        if (marketJobInFlight(res)) {
          const stillRunning = marketJobStillRunningText();
          if (fail) fail.textContent = stillRunning;
          toast(stillRunning);
          return;
        }
        if (!res || !res.success || !res.summary) {
          const message = (res && (res.error || res.providerError)) || 'تعذر توليد الملخص. لم يُستبدل النص الحالي.';
          if (fail) fail.textContent = message;
          toast(message);
          return;
        }
        finishMarketSummaryJob(res, currentSummary, currentSwot, currentOneBlock);
      } catch (error) {
        if (fail) fail.textContent = error.message || 'تعذر توليد الملخص';
        toast(error.message || 'تعذر توليد الملخص');
      } finally {
        hideLoader();
        if (btn) btn.disabled = false;
      }
    }

    function finishMarketSummaryJob(res, currentSummary, currentSwot, currentOneBlock) {
      const fail = document.getElementById('marketSummaryFailure');
      const hasCurrent = marketSummaryHasContent(currentSummary)
        || currentOneBlock
        || Object.values(currentSwot).some(value => String(value || '').trim());
      const unverifiedNote = res.searchVerified === false
        ? WFT('market.note_sources_unverified', ' — مصادر الملخص غير موثقة: لم يعمل البحث في الويب أثناء التوليد')
        : '';
      marketSummaryPending = {
        summary: res.summary,
        swot: res.swot || {},
        sources: res.sources || [],
        decision: res.decision || '',
        disclaimer: res.disclaimer || '',
        oneBlockSummary: res.one_block_summary || res.oneBlockSummary || ''
      };
      if (hasCurrent) {
        renderMarketSummaryCompare(currentSummary, res.summary, currentSwot, res.swot || {}, currentOneBlock, marketSummaryPending.oneBlockSummary);
        toast(WFT('market.two_versions_shown', 'النسختان ظاهرتان. اختر الاستبدال أو الإبقاء.') + unverifiedNote);
      } else {
        const state = getMarketStudyState();
        state.summary = res.summary;
        state.swot = res.swot || {};
        state.sources = mergeMarketSourceRows(
          res.sources || [],
          buildMarketCompetitorSourceRows(state.competitors)
        );
        state.decision = res.decision || '';
        state.disclaimer = res.disclaimer || state.disclaimer;
        state.one_block_summary = res.one_block_summary || res.oneBlockSummary || '';
        applyMarketStudyState(state);
        persistMarketStudyFromDom();
        toast(WFT('market.summary_generated', 'تم توليد ملخص السوق وتحليل SWOT') + unverifiedNote);
      }
      updateLoaderProgress(100, 'اكتمل ملخص السوق');
      if (fail) fail.textContent = '';
    }
