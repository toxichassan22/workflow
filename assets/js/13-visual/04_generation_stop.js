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
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      unsub();
      document.removeEventListener('visibilitychange', onVisibility);
      resolve(value);
    };
    // Chrome throttles timers in a hidden tab — a 2.5 s poll waits ~1 minute,
    // and a minute per tick after five hidden minutes — so a study running
    // fine on the server looked frozen until its tab was focused again.
    // Coming back to the tab ends the wait at once, so the next poll reports
    // the job's own progress instead of an old one.
    const onVisibility = () => { if (!document.hidden) finish(true); };
    const unsub = onTenantGenerationStop(() => finish(false));
    document.addEventListener('visibilitychange', onVisibility);
    timer = setTimeout(() => finish(true), ms);
  });
}

function registerTenantGenerationRun(runId) {
  if (!runId) return;
  tenantActiveGenerationRuns.add(String(runId));
  // The handle arrived after the user already stopped — the start request was
  // still in flight when the X was pressed. It is cancelled the moment it has
  // a name, otherwise the stop would have missed the only handle that matters.
  if (tenantGenerationStopRequested) cancelTenantGenerationRun(String(runId));
}

// Releasing a handle says "this run is no longer being waited on" — it does
// NOT say "the user changed their mind". Clearing the stop here is what made a
// stopped job keep going: the deck's launcher re-checked the flag the moment
// the cancelled slice released its handle, saw it false, and started every
// remaining slide. The flag stays latched until the next action begins
// (resetTenantGenerationStop, called by showLoader/stoppable and by each
// generation entry point).
function releaseTenantGenerationRun(runId) {
  if (!runId) return;
  tenantActiveGenerationRuns.delete(String(runId));
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

// The close control on the progress card means "stop this", not "hide it":
// a closed popup used to leave the paid work running with nothing on screen
// showing it. It hides immediately and asks the server to cancel every run
// the card is following.
async function closeGenerationPopup() {
  const runs = tenantGenerationRunsInFlight();
  const stopControl = document.getElementById('globalLoaderStopButton');
  const stoppable = !!(stopControl && stopControl.style && stopControl.style.display !== 'none');
  // A generation loader carries the stop control even before its first job id
  // arrives; closing it is still the user asking for that work to end, so the
  // stop is recorded and the late handle is cancelled when it lands.
  if (runs.length || stoppable) {
    stopTenantGeneration();
  }
  hideLoader();
}

async function stopTenantGeneration() {
  // A second press must still reach a handle that appeared after the first one
  // (the start request was already in flight when the user clicked), so the
  // command is not short-circuited — it is only announced once.
  const alreadyRequested = tenantGenerationStopRequested;
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
  if (!alreadyRequested) toast(WFT('gen.stop_requested', 'تم إرسال طلب الإيقاف'));
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
    // A stopped job is a stop, not a failure: the caller reports it as one
    // even when the job document carries the stop as its error text.
    if (job?.status === 'cancelled') break;
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
