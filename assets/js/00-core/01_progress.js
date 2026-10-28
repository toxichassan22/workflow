/* 00-core/01_progress.js — the task progress card.
 *
 * The bar exists so the client can follow the task, not so it can guess what
 * the task is doing. It therefore moves for exactly two reasons:
 *   - the server named a step as finished (applyLoaderJobProgress, or the plan
 *     sent with showLoader options.steps), and
 *   - a fraction somebody actually measured (uploaded bytes, committed slides).
 * It never advances because time passed. While nothing is measured the card
 * shows an indeterminate bar, the step being worked on, and the elapsed time:
 * all true, none invented.
 */

    let loaderProgressValue = 0;
    let loaderHideTimer = null;
    let loaderSessionActive = false;
    let loaderClockTimer = null;
    let loaderStartedAt = 0;
    let loaderPlan = [];
    let loaderActiveStep = '';
    let genProgressValue = 0;
    let genStartMs = 0;

    function clampLoaderProgress(pct) {
      const value = Number(pct);
      return Number.isFinite(value) ? Math.max(0, Math.min(100, Math.round(value))) : 0;
    }

    function formatLoaderClock(ms) {
      const total = Math.max(0, Math.floor(Number(ms || 0) / 1000));
      const minutes = Math.floor(total / 60);
      const seconds = total % 60;
      return minutes + ':' + String(seconds).padStart(2, '0');
    }

    // An indeterminate bar has no number to show: the track loses
    // aria-valuenow instead of claiming one, and the fill sweeps.
    function setLoaderIndeterminate(active) {
      const progress = document.getElementById('globalLoaderProgress');
      const pctEl = document.getElementById('globalLoaderPct');
      const bar = document.getElementById('globalLoaderBar');
      const track = document.querySelector('#globalLoaderProgress .global-loader-progress-track');
      if (progress) progress.classList.toggle('is-indeterminate', !!active);
      if (bar) bar.style.width = active ? '' : loaderProgressValue + '%';
      if (pctEl) {
        pctEl.style.display = active ? 'none' : '';
        pctEl.textContent = active ? '' : loaderProgressValue + '%';
      }
      if (track) {
        if (active) track.removeAttribute('aria-valuenow');
        else track.setAttribute('aria-valuenow', String(loaderProgressValue));
      }
    }

    function renderLoaderProgress(pct, stepText, options = {}) {
      const requested = clampLoaderProgress(pct);
      const allowDecrease = !!options.allowDecrease;
      const value = allowDecrease ? requested : Math.max(loaderProgressValue, requested);
      const bar = document.getElementById('globalLoaderBar');
      const pctEl = document.getElementById('globalLoaderPct');
      const stepEl = document.getElementById('globalLoaderStep');
      const track = bar ? bar.parentElement : null;
      loaderProgressValue = value;
      if (bar) bar.style.width = value + '%';
      if (pctEl) {
        pctEl.style.display = '';
        pctEl.textContent = value + '%';
      }
      if (stepEl && stepText !== undefined && stepText !== null) stepEl.textContent = stepText || '';
      if (track) track.setAttribute('aria-valuenow', String(value));
      setLoaderIndeterminate(false);
    }

    function renderLoaderClock() {
      const el = document.getElementById('globalLoaderEstimate');
      if (!el) return;
      const activeIndex = loaderPlan.findIndex(step => String(step.key) === String(loaderActiveStep));
      if (activeIndex >= 0) {
        el.textContent = WFT('loader.step_of', 'الخطوة {n} من {total}',
          { n: activeIndex + 1, total: loaderPlan.length });
        return;
      }
      el.textContent = loaderStartedAt
        ? WFT('loader.elapsed', 'منقضي {time}', { time: formatLoaderClock(Date.now() - loaderStartedAt) })
        : '';
    }

    function stopLoaderClock() {
      if (loaderClockTimer) {
        clearInterval(loaderClockTimer);
        loaderClockTimer = null;
      }
    }

    function startLoaderClock() {
      stopLoaderClock();
      loaderStartedAt = Date.now();
      renderLoaderClock();
      // This ticks the clock only. It must never touch the bar: a percentage
      // that grew because a second passed is the fiction this file removed.
      loaderClockTimer = setInterval(renderLoaderClock, 1000);
    }

    // The server's own step list: each row is done only when the server moved
    // past it, the active row is the work running now.
    function renderLoaderSteps(steps, activeKey) {
      loaderPlan = Array.isArray(steps)
        ? steps.filter(step => step && (step.label || step.key)).map(step => ({
          key: String(step.key || step.label || ''),
          label: String(step.label || step.key || '')
        }))
        : [];
      if (activeKey !== undefined && activeKey !== null && String(activeKey)) {
        loaderActiveStep = String(activeKey);
      }
      const box = document.getElementById('globalLoaderSteps');
      if (box) {
        if (!loaderPlan.length) {
          box.hidden = true;
          box.innerHTML = '';
        } else {
          const activeIndex = loaderPlan.findIndex(step => step.key === loaderActiveStep);
          box.innerHTML = loaderPlan.map((step, index) => {
            const state = activeIndex === -1
              ? ''
              : (index < activeIndex ? ' is-done' : (index === activeIndex ? ' is-active' : ''));
            return '<div class="global-loader-step' + state + '">' +
              '<span class="global-loader-step-index">' + (index + 1) + '</span>' +
              '<span class="global-loader-step-label">' + escapeHtml(step.label) + '</span>' +
              '</div>';
          }).join('');
          box.hidden = false;
        }
      }
      renderLoaderClock();
    }

    // One job payload drives the card: steps when the server published a plan,
    // the percentage only when the server counted the unit it names. Returns
    // whether the bar moved on a real number.
    function applyLoaderJobProgress(job) {
      if (!job || typeof job !== 'object') return false;
      const steps = Array.isArray(job.steps) ? job.steps : null;
      const stepKey = job.step || job.stepKey || '';
      if (steps && steps.length) renderLoaderSteps(steps, stepKey);
      else if (stepKey) renderLoaderSteps(loaderPlan, stepKey);
      const detail = String(job.stepDetail || job.message || '').trim();
      if (detail) updateLoaderMessage(detail);
      const pct = Number(job.progress);
      const measured = job.progressMeasured === true && Number.isFinite(pct);
      if (measured) {
        renderLoaderProgress(pct, job.stepLabel || detail || undefined);
        return true;
      }
      // A plan without a counted fraction is still informative: the checklist
      // is the progress, so the bar stays indeterminate instead of guessing.
      const stepEl = document.getElementById('globalLoaderStep');
      if (stepEl && (job.stepLabel || detail)) {
        stepEl.textContent = String(job.stepLabel || detail);
      }
      setLoaderIndeterminate(true);
      return false;
    }

    // The work a long operation is doing right now, with no fraction attached.
    // This is the honest replacement for the authored "start at 20%" pitches.
    function updateLoaderStep(stepText) {
      const prog = document.getElementById('globalLoaderProgress');
      if (prog) prog.style.display = 'block';
      if (stepText) {
        updateLoaderMessage(stepText);
        const stepEl = document.getElementById('globalLoaderStep');
        if (stepEl) stepEl.textContent = String(stepText);
      }
      setLoaderIndeterminate(true);
    }

    function showLoader(title, text, pct, options = {}) {
      const loader = document.getElementById('globalLoader');
      if (!loader) return;
      const alreadyVisible = loader.style.display === 'flex';
      const continueExisting = alreadyVisible && loaderSessionActive && options.reset !== true;
      clearTimeout(loaderHideTimer);
      document.getElementById('globalLoaderTitle').textContent = title || WFT('loader.loading', 'جاري التحميل...');
      document.getElementById('globalLoaderText').textContent = text || '';
      document.getElementById('globalLoaderProgress').style.display = 'block';
      if (Array.isArray(options.steps) && options.steps.length) {
        renderLoaderSteps(options.steps, options.step);
      } else if (!continueExisting) {
        renderLoaderSteps([], '');
      }
      // The percentage argument is accepted for call-site compatibility and
      // ignored: it was always an authored starting guess, and the caller has
      // counted nothing yet. Only updateLoaderProgress(..., true) may move the
      // bar, and the stage name is what the client reads in the meantime.
      if (continueExisting) {
        const stepEl = document.getElementById('globalLoaderStep');
        if (stepEl && text) stepEl.textContent = String(text);
      } else {
        loaderSessionActive = true;
        loaderProgressValue = 0;
        setLoaderIndeterminate(true);
        const stepEl = document.getElementById('globalLoaderStep');
        if (stepEl) stepEl.textContent = text || WFT('loader.preparing', 'جاري التحضير...');
      }
      loader.style.display = 'flex';
      // A long paid operation shows the stop button; a short one never does.
      const stopButton = document.getElementById('globalLoaderStopButton');
      if (stopButton) {
        stopButton.style.display = options.stoppable ? 'inline-flex' : 'none';
        if (options.stoppable) {
          if (typeof resetTenantGenerationStop === 'function') {
            resetTenantGenerationStop();
          }
          stopButton.disabled = false;
          stopButton.textContent = WFT('gen.stop', 'إيقاف');
        }
      }
      startLoaderClock();
    }

    // The work a long operation is doing right now, in words. The percentage is
    // not a step: the client has to see what the server is actually doing.
    function updateLoaderMessage(text) {
      const el = document.getElementById('globalLoaderText');
      if (el) el.textContent = String(text || '');
    }

    // Move the bar to a fraction somebody actually counted: uploaded bytes,
    // rendered rows, committed slides. Third argument must be true — anything
    // else is a stage name, not a measurement.
    function updateLoaderProgress(pct, stepText, measured) {
      const prog = document.getElementById('globalLoaderProgress');
      if (prog) prog.style.display = 'block';
      if (measured !== true) {
        updateLoaderStep(stepText);
        return;
      }
      renderLoaderProgress(pct, stepText);
    }

    function hideLoader(completionText) {
      const loader = document.getElementById('globalLoader');
      if (!loader || loader.style.display === 'none') return;
      stopLoaderClock();
      renderLoaderProgress(100, completionText || WFT('loader.done', 'اكتمل'));
      const textEl = document.getElementById('globalLoaderText');
      if (textEl) textEl.textContent = completionText || WFT('loader.loaded', 'اكتمل التحميل');
      clearTimeout(loaderHideTimer);
      loaderHideTimer = setTimeout(() => {
        loader.style.display = 'none';
        loaderSessionActive = false;
        loaderStartedAt = 0;
        loaderPlan = [];
        loaderActiveStep = '';
        renderLoaderSteps([], '');
        renderLoaderProgress(0, WFT('loader.preparing', 'جاري التحضير...'), { allowDecrease: true });
        const estimate = document.getElementById('globalLoaderEstimate');
        if (estimate) estimate.textContent = '';
      }, 420);
    }

    function showInlineLoader(container, text) {
      if (!container) return;
      const label = String(text || 'جاري التحميل...')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
      // Nothing has been counted when the box appears, so it shows no number
      // and an indeterminate sweep; the label is the real state.
      container.innerHTML =
        '<div class="inline-loading-box">' +
        '<div class="inline-loading-header"><span>' + label + '</span></div>' +
        '<div class="inline-loading-track is-indeterminate" role="progressbar" aria-valuemin="0" aria-valuemax="100">' +
        '<div class="inline-loading-fill" data-inline-loader-bar></div>' +
        '</div></div>';
    }

    // Text only: the percentage this used to draw was the job's authored
    // constant, not a count of anything, so the inline card names the step and
    // leaves the fraction out.
    function setInlineLoaderProgress(container, pct, text) {
      if (!container) return;
      void pct;
      if (text) {
        const labelEl = container.querySelector('.inline-loading-header span:first-child');
        if (labelEl) labelEl.textContent = text;
      }
    }

    // ═══════════════════════════════════════════════════════════════
    // FULL-PAGE GENERATION PROGRESS
    // ═══════════════════════════════════════════════════════════════
    const GEN_STEPS = [
      { id: 'plan', label: 'إعداد خطة الشرائح' },
      { id: 'prompts', label: 'صياغة أوصاف الصور' },
      { id: 'images', label: 'توليد الصور الإبداعية' },
      { id: 'slides', label: 'توليد الشرائح' },
      { id: 'save', label: 'حفظ العرض' }
    ];

    function renderGenSteps() {
      const box = document.getElementById('genSteps');
      if (!box) return;
      box.innerHTML = GEN_STEPS.map((step, index) =>
        '<div class="gen-step" id="genStep_' + step.id + '">' +
        '<span>' + (index + 1) + '. ' + escapeHtml(step.label) + '</span>' +
        '<span class="gen-step-status"></span>' +
        '</div>').join('');
    }

    function showGenProgress() {
      genStartMs = Date.now();
      genProgressValue = 0;
      renderGenSteps();
      showTenantPage('tenantSlidesPage');
    }

    function elapsedGenText() {
      return genStartMs
        ? WFT('loader.elapsed', 'منقضي {time}', { time: formatLoaderClock(Date.now() - genStartMs) })
        : '';
    }

    function setGenPct(pct, subtitle) {
      const requested = clampLoaderProgress(pct);
      const value = Math.max(genProgressValue, requested);
      genProgressValue = value;
      const bar = document.getElementById('genBar');
      const pctEl = document.getElementById('genPct');
      const subEl = document.getElementById('genSubtitle');
      const elapsedEl = document.getElementById('genEta');
      if (bar) bar.style.width = value + '%';
      if (pctEl) pctEl.textContent = value + '%';
      if (subEl && subtitle) subEl.textContent = subtitle;
      // Elapsed time is measured. A "remaining" figure extrapolated from the
      // percentage was another guess dressed up as an estimate.
      if (elapsedEl) elapsedEl.textContent = elapsedGenText();
    }

    function setGenStep(stepId, state) {
      const el = document.getElementById('genStep_' + stepId);
      if (!el) return;
      const dot = el.querySelector('.gen-step-index');
      const label = el.querySelector('span:first-child');
      const status = el.querySelector('.gen-step-status');
      if (state === 'active') {
        el.classList.add('is-active');
        el.classList.remove('is-done', 'is-error');
        if (dot) dot.style.background = 'var(--p)';
        if (label) label.style.fontWeight = '700';
        if (status) status.textContent = WFT('loader.running', 'جارٍ');
      } else if (state === 'done') {
        el.classList.add('is-done');
        el.classList.remove('is-active', 'is-error');
        if (dot) dot.style.background = 'var(--p)';
        if (status) status.textContent = WFT('loader.done', 'اكتمل');
      } else if (state === 'error') {
        el.classList.add('is-error');
        el.classList.remove('is-active', 'is-done');
        if (status) status.textContent = WFT('loader.skipped', 'لم تُنفَّذ');
      }
    }

    function hideGenProgress() {
      const bar = document.getElementById('genBar');
      if (bar) bar.style.width = '100%';
      setGenPct(100, WFT('loader.done', 'اكتمل'));
      setTimeout(() => {
        hideLoader();
      }, 600);
    }

    // The live banner follows the same rule: a number only when the caller
    // counted the slides behind it. Fifth argument marks a measured fraction;
    // without it the bar sweeps and the percentage stays hidden.
    function setLiveGenBanner(visible, title, details, pct, measured) {
      const banner = document.getElementById('tenantLiveGenBanner');
      if (!banner) return;
      if (!visible) {
        banner.style.display = 'none';
        return;
      }
      banner.style.display = 'block';
      const titleEl = document.getElementById('liveGenSlideTitle');
      const detailsEl = document.getElementById('liveGenSlideDetails');
      const barEl = document.getElementById('liveGenProgressBar');
      const pctEl = document.getElementById('liveGenProgressPct');
      const resumeButton = document.getElementById('liveGenResumeButton');
      const barHost = barEl ? barEl.parentElement : null;
      if (titleEl && title) titleEl.textContent = title;
      if (detailsEl) detailsEl.textContent = details || '';
      if (resumeButton) {
        const checkpoint = tenantSlideGenerationCheckpoint || tenantProjectData?.slide_generation_checkpoint;
        const resumable = checkpoint?.status === 'paused' && checkpoint?.active !== false;
        resumeButton.style.display = resumable ? 'inline-flex' : 'none';
      }
      if (measured === true && typeof pct === 'number') {
        const clampedPct = Math.max(0, Math.min(100, Math.round(pct)));
        if (barHost) barHost.classList.remove('is-indeterminate');
        if (barEl) barEl.style.width = clampedPct + '%';
        if (pctEl) {
          pctEl.style.visibility = '';
          pctEl.textContent = clampedPct + '%';
        }
        return;
      }
      if (barHost) barHost.classList.add('is-indeterminate');
      if (barEl) barEl.style.width = '';
      if (pctEl) {
        pctEl.style.visibility = 'hidden';
        pctEl.textContent = '';
      }
    }
