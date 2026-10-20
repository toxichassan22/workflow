/* ── Stop button: the user ends a paid run before it spends the rest. ──
   Every long operation runs under a server-side run handle. The browser
   keeps the handles it is waiting on here, so one press stops all of them
   and the server never starts the next paid call. */

let tenantGenerationStopRequested = false;
const tenantActiveGenerationRuns = new Set();

function registerTenantGenerationRun(runId) {
  if (!runId) return;
  tenantActiveGenerationRuns.add(String(runId));
}

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
  // call, so the requests go out first and the UI settles afterwards.
  await Promise.all(runs.map(runId => cancelTenantGenerationRun(runId).catch(() => false)));
  toast(WFT('gen.stop_requested', 'تم إرسال طلب الإيقاف'));
}
