/* ── Stop button: the user ends a paid run before it spends the rest. ──
   Every long operation runs under a server-side run handle. The browser
   keeps the handles it is waiting on here, so one press stops all of them
   and the server never starts the next paid call. */

let tenantGenerationStopRequested = false;
const tenantActiveGenerationRuns = new Set();
const tenantStopListeners = new Set();

function onTenantGenerationStop(callback) {
  if (typeof callback !== 'function') return () => {};
  tenantStopListeners.add(callback);
  return () => tenantStopListeners.delete(callback);
}

function triggerTenantGenerationStopEvent() {
  for (const callback of tenantStopListeners) {
    try { callback(); } catch (err) { /* stop notification */ }
  }
}

function interruptiblePollSleep(ms) {
  return new Promise(resolve => {
    if (tenantGenerationStopRequested) return resolve(false);
    let timer = null;
    const unsub = onTenantGenerationStop(() => {
      if (timer) clearTimeout(timer);
      unsub();
      resolve(false);
    });
    timer = setTimeout(() => {
      unsub();
      resolve(true);
    }, ms);
  });
}

function registerTenantGenerationRun(runId) {
  if (!runId) return;
  tenantActiveGenerationRuns.add(String(runId));
}

function releaseTenantGenerationRun(runId) {
  if (!runId) return;
  tenantActiveGenerationRuns.delete(String(runId));
  if (tenantActiveGenerationRuns.size === 0) {
    tenantGenerationStopRequested = false;
  }
}

function tenantGenerationRunsInFlight() {
  return Array.from(tenantActiveGenerationRuns);
}

async function cancelTenantGenerationRun(runId) {
  if (!runId) return false;
  releaseTenantGenerationRun(runId);
  const res = await api('POST', '/api/runs/' + encodeURIComponent(String(runId)) + '/cancel', null);
  return !!(res && res.success);
}

function resetTenantGenerationStop() {
  tenantGenerationStopRequested = false;
  tenantActiveGenerationRuns.clear();
  const stopButton = document.getElementById('liveGenStopButton');
  if (stopButton) {
    stopButton.disabled = false;
    stopButton.textContent = WFT('gen.stop_generation', 'إيقاف التوليد');
  }
  const loaderStopButton = document.getElementById('globalLoaderStopButton');
  if (loaderStopButton) {
    loaderStopButton.disabled = false;
    loaderStopButton.textContent = WFT('gen.stop', 'إيقاف');
  }
}

function setTenantGenerationStopVisible(visible) {
  const stopButton = document.getElementById('liveGenStopButton');
  if (stopButton) stopButton.style.display = visible ? 'inline-flex' : 'none';
  const loaderStopButton = document.getElementById('globalLoaderStopButton');
  if (loaderStopButton && !visible) loaderStopButton.style.display = 'none';
}

async function stopTenantGeneration() {
  if (tenantGenerationStopRequested) return;
  tenantGenerationStopRequested = true;
  triggerTenantGenerationStopEvent();
  const runs = tenantGenerationRunsInFlight();
  const stopButton = document.getElementById('liveGenStopButton');
  if (stopButton) {
    stopButton.disabled = true;
    stopButton.textContent = WFT('gen.stopping', 'جاري الإيقاف...');
  }
  const loaderStopButton = document.getElementById('globalLoaderStopButton');
  if (loaderStopButton) {
    loaderStopButton.disabled = true;
    loaderStopButton.textContent = WFT('gen.stopping', 'جاري الإيقاف...');
  }
  // The server has to learn about the stop before it starts the next paid
  // call, so the requests go out in parallel immediately.
  Promise.all(runs.map(runId => cancelTenantGenerationRun(runId).catch(() => false)));
  toast(WFT('gen.stop_requested', 'تم إرسال طلب الإيقاف'));
}

// A queued operation answers 202 {jobId} and finishes inside a worker. Poll
// the persisted job and hand back the same shape a synchronous call would
// have returned — a failed job yields its stored {success:false,error}.
async function pollTenantGenerationJob(jobId, statusPath, options = {}) {
  const timeoutSeconds = Number(options.timeoutSeconds);
  const jobWindowMs = Number.isFinite(timeoutSeconds) && timeoutSeconds > 0
    ? timeoutSeconds * 1000 : 600000;
  const deadline = Date.now() + jobWindowMs + 10000;
  const timeoutMessage = options.timeoutMessage || WFT('gen.job_timeout', 'انتهت مهلة المهمة.');
  let job = null;
  while (Date.now() < deadline) {
    if (tenantGenerationStopRequested) break;
    const slept = await interruptiblePollSleep(1500);
    if (tenantGenerationStopRequested || !slept) break;
    const requestTimeout = Math.min(15000, deadline - Date.now());
    if (requestTimeout <= 0) break;
    job = await apiWithTimeout(
      'GET', statusPath + encodeURIComponent(jobId), null, requestTimeout,
      options.statusTimeoutMessage || WFT('gen.job_status_timeout', 'تعذر الاتصال بحالة المهمة.'));
    if (job?.error && !job?.result) {
      return { success: false, error: job.error, error_code: job.error_code };
    }
    if (!job || !['queued', 'running'].includes(job.status)) break;
    if (tenantGenerationStopRequested) break;
  }
  if (tenantGenerationStopRequested || job?.status === 'cancelled') {
    return {
      success: false,
      error: WFT('gen.job_cancelled', 'تم إيقاف المهمة'),
      error_code: 'RUN_CANCELLED',
      cancelled: true
    };
  }
  if (job?.result && typeof job.result === 'object') return job.result;
  if (job?.error) return { success: false, error: job.error, error_code: job.error_code };
  return { success: false, error: timeoutMessage, error_code: 'JOB_TIMEOUT' };
}

// Post an operation that may be queued, then wait for its job. The run
// handle is registered so the stop button can reach it while it runs.
async function runTenantGenerationJob(method, path, body, statusPath, options = {}) {
  if (tenantActiveGenerationRuns.size === 0) {
    resetTenantGenerationStop();
  }
  const initial = await api(method, path, body);
  if (!initial || !initial.jobId) return initial;
  registerTenantGenerationRun(initial.jobId);
  try {
    return await pollTenantGenerationJob(initial.jobId, statusPath, {
      timeoutSeconds: initial.timeoutSeconds,
      ...options,
    });
  } finally {
    releaseTenantGenerationRun(initial.jobId);
  }
}
