'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..');
const folders = ['08-location-maps', '11-land-croquis'];
const source = folders.flatMap(folder => fs.readdirSync(path.join(root, 'assets/js', folder))
  .filter(name => name.endsWith('.js')).sort()
  .map(name => fs.readFileSync(path.join(root, 'assets/js', folder, name), 'utf8'))).join('\n');
const plain = value => JSON.parse(JSON.stringify(value));
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

async function until(predicate) {
  for (let count = 0; count < 100; count++) {
    if (predicate()) return;
    await Promise.resolve();
  }
  assert(predicate(), 'Async map operation did not reach its checkpoint');
}

function preview(mapType = 'catchment') {
  const requests = [];
  const timers = new Map();
  const toasts = [];
  let timerId = 0;
  const image = { src: '', naturalWidth: 2560, naturalHeight: 1440, style: {} };
  const box = { style: {}, querySelector: () => image, scrollIntoView() {} };
  const creative = {
    map_placeholders: { ['##MAP_' + mapType.toUpperCase() + '##']: '/uploads/maps/legacy.png' },
    map_zooms: { [mapType]: 12 }, map_centers: { [mapType]: { lat: 24, lng: 46 } },
    map_approvals: {}, map_viewport_overrides: {}
  };
  const state = vm.createContext({
    console, window: {},
    setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    document: {
      getElementById: id => id === 'mapPreviewImage' ? box : null,
      querySelector: selector => selector === '#mapPreviewImage img' ? image : null,
      querySelectorAll: () => []
    },
    tenantCreativeImages: creative,
    tenantProjectData: {
      draftId: 'approval-test', location_lat: 24, location_lng: 46,
      city_landmarks_data: [], nearby_landmarks_data: [], change: 'first'
    },
    tenantProjectSectionStatuses: {}, tenantPresentationId: null, tenantPresentationRevision: 0,
    LOCATION_TABLE_FIELDS: {
      city_landmarks: { mapType: 'catchment' }, nearby_landmarks: { mapType: 'landmarks' },
      main_roads: { mapType: 'access' }, catchment_areas: { mapType: 'catchment' }
    },
    slimMapProjectData: data => plain(data),
    saveProjectAsDraft: async () => true,
    mapsSignature: () => 'signature', shouldHighlightTenantSite: () => true,
    mapPreviewStoredUrl: view => creative.map_placeholders[view.keys[0]] || '',
    mapPreviewIsVisible: () => true, mapPreviewIsGenerated: () => true,
    triggerAutoSaveDraft() {}, toast: message => toasts.push(message),
    WFT: (key, fallback) => fallback,
    api: async (method, url, body) => {
      requests.push(plain(body));
      return { success: true, placeholders: { ['##MAP_' + body.mapType.toUpperCase() + '##']: '/uploads/maps/current.png' } };
    }
  });
  vm.runInContext(source, state);
  vm.runInContext(`
    tenantSelectedMapType = '${mapType}';
    tenantMapPreviewState = { lat: 24, lng: 46, zoom: 12, frameAccurate: true };
    renderLocationWorkflowState = () => {};
    renderMapPreviewGallery = () => {};
    renderTenantMapPolygonOverlay = () => {};
    selectMapPreviewView = () => true;
  `, state);
  return { state, creative, requests, timers, toasts, run: code => vm.runInContext(code, state) };
}

for (const mapType of ['overview', 'access', 'catchment', 'landmarks']) {
  test(`${mapType} approval recomposes a legacy raster before certifying it`, async () => {
    const fixture = preview(mapType);
    assert.equal(await fixture.state.approveTenantMap(mapType), true);
    assert.equal(fixture.requests.length, 1);
    assert.equal(fixture.requests[0].overlayOnly, true);
    assert.equal(fixture.requests[0].mapType, mapType);
    assert.equal(fixture.creative.map_approvals[mapType], true);
    assert.equal(fixture.creative.map_placeholders['##MAP_' + mapType.toUpperCase() + '##'], '/uploads/maps/current.png');
  });
}

test('flush drains an edit queued while the previous recompose is in flight', async () => {
  const fixture = preview();
  const first = deferred();
  fixture.state.api = async (method, url, body) => {
    fixture.requests.push(plain(body));
    if (fixture.requests.length === 1) await first.promise;
    return { success: true };
  };
  const running = fixture.state.runMapTableRecompose('catchment');
  await until(() => fixture.requests.length === 1);
  fixture.state.tenantProjectData.change = 'second';
  fixture.state.scheduleMapRecomposeType('catchment');
  const flush = fixture.state.flushMapTableRecompose();
  first.resolve();
  await Promise.all([running, flush]);
  assert.equal(fixture.requests.length, 2);
  assert.equal(fixture.requests[1].projectData.change, 'second');
  assert.equal(fixture.run('Object.keys(tenantMapRecomposeTimers).length'), 0);
  assert.equal(fixture.timers.size, 0);
});

test('flush reports a failed recompose instead of silently discarding it', async () => {
  const fixture = preview();
  fixture.state.api = async () => ({ success: false });
  fixture.state.scheduleMapRecomposeType('catchment');
  assert.equal(await fixture.state.flushMapTableRecompose(), false);
});

test('approval cannot certify a raster after the queued recompose fails', async () => {
  const fixture = preview();
  fixture.state.api = async () => ({ success: false });
  fixture.state.scheduleMapRecomposeType('catchment');
  assert.equal(await fixture.state.approveTenantMap('catchment'), false);
  assert.notEqual(fixture.creative.map_approvals.catchment, true);
});

test('approval waits for both in-flight table edits and the final recompose', async () => {
  const fixture = preview();
  const first = deferred();
  fixture.state.api = async (method, url, body) => {
    fixture.requests.push(plain(body));
    if (fixture.requests.length === 1) await first.promise;
    return { success: true };
  };
  const running = fixture.state.runMapTableRecompose('catchment');
  await until(() => fixture.requests.length === 1);
  fixture.state.tenantProjectData.change = 'second';
  fixture.state.scheduleMapRecomposeType('catchment');
  const approval = fixture.state.approveTenantMap('catchment');
  assert.notEqual(fixture.creative.map_approvals.catchment, true);
  first.resolve();
  assert.equal(await approval, true);
  await running;
  assert(fixture.requests.length >= 2);
  assert.equal(fixture.requests.at(-1).projectData.change, 'second');
  assert.equal(fixture.run('Object.keys(tenantMapRecomposeTimers).length'), 0);
});

test('a failed final render leaves the legacy artifact unapproved', async () => {
  const fixture = preview('landmarks');
  fixture.state.api = async () => ({ success: false });
  assert.equal(await fixture.state.approveTenantMap('landmarks'), false);
  assert.notEqual(fixture.creative.map_approvals.landmarks, true);
});

test('a failed approval save rolls the local flag back', async () => {
  const fixture = preview();
  fixture.state.saveProjectAsDraft = async () => false;
  assert.equal(await fixture.state.approveTenantMap('catchment'), false);
  assert.notEqual(fixture.creative.map_approvals.catchment, true);
});

test('a rejected presentation save does not advance the local revision', async () => {
  const fixture = preview();
  fixture.state.tenantPresentationId = 'presentation-test';
  fixture.state.tenantPresentationRevision = 7;
  fixture.state.api = async () => ({ success: false, revision: 8 });
  assert.equal(await fixture.state.saveMapPreviewState(), false);
  assert.equal(fixture.state.tenantPresentationRevision, 7);
});

test('a thrown approval save restores the local approval flag', async () => {
  const fixture = preview();
  fixture.state.saveMapPreviewState = async () => { throw new Error('save failure'); };
  assert.equal(await fixture.state.approveTenantMap('catchment'), false);
  assert.notEqual(fixture.creative.map_approvals.catchment, true);
  assert(!fixture.toasts.includes('تم اعتماد الخريطة'));
});

test('a failed unapproval save restores the artifact and section approval', async () => {
  const fixture = preview();
  fixture.creative.map_approvals.catchment = true;
  fixture.state.tenantProjectSectionStatuses.location = 'approved';
  fixture.state.releaseLocationSectionApproval = () => { fixture.state.tenantProjectSectionStatuses.location = 'draft'; };
  fixture.state.applySectionStatuses = statuses => Object.assign(fixture.state.tenantProjectSectionStatuses, statuses);
  fixture.state.saveProjectAsDraft = async () => false;
  assert.equal(await fixture.state.unapproveTenantMap('catchment'), false);
  assert.equal(fixture.creative.map_approvals.catchment, true);
  assert.equal(fixture.state.tenantProjectSectionStatuses.location, 'approved');
  assert(!fixture.toasts.includes('تم إلغاء اعتماد الخريطة'));
});

test('double approval shares one final render', async () => {
  const fixture = preview();
  const response = deferred();
  fixture.state.api = async (method, url, body) => {
    fixture.requests.push(plain(body));
    await response.promise;
    return { success: true };
  };
  const first = fixture.state.approveTenantMap('catchment');
  const second = fixture.state.approveTenantMap('catchment');
  await until(() => fixture.requests.length === 1);
  response.resolve();
  assert.deepEqual(await Promise.all([first, second]), [true, true]);
  assert.equal(fixture.requests.length, 1);
});

test('re-approving a certified artifact does not change its raster', async () => {
  const fixture = preview();
  fixture.creative.map_approvals.catchment = true;
  assert.equal(await fixture.state.approveTenantMap('catchment'), true);
  assert.equal(fixture.requests.length, 0);
});

test('another map failure is not an approval gate for this artifact', async () => {
  const fixture = preview();
  fixture.creative.map_placeholders['##MAP_LANDMARKS##'] = '/uploads/maps/landmarks.png';
  fixture.state.api = async (method, url, body) => {
    fixture.requests.push(plain(body));
    return { success: body.mapType !== 'landmarks' };
  };
  fixture.state.scheduleMapRecomposeType('landmarks');
  assert.equal(await fixture.state.approveTenantMap('catchment'), true);
  assert.equal(fixture.creative.map_approvals.catchment, true);
  assert.equal(fixture.requests.filter(body => body.mapType === 'landmarks').length, 0);
});

test('an open map edit session cannot be implicitly certified', async () => {
  const fixture = preview();
  fixture.run('tenantCatchmentEditMode = true; tenantCatchmentEditDraft = { landmarks: [] }');
  assert.equal(await fixture.state.approveTenantMap('catchment'), false);
  assert.notEqual(fixture.creative.map_approvals.catchment, true);
});

test('a completed failed table update still blocks approval until retried', async () => {
  const fixture = preview();
  fixture.state.api = async () => ({ success: false });
  assert.equal(await fixture.state.runMapTableRecompose('catchment'), false);
  assert.equal(await fixture.state.approveTenantMap('catchment'), false);
  assert.notEqual(fixture.creative.map_approvals.catchment, true);
  fixture.state.api = async () => ({ success: true });
  fixture.state.scheduleMapRecomposeType('catchment');
  assert.equal(await fixture.state.flushMapTableRecompose('catchment'), true);
});

test('concurrent flushes do not enqueue a duplicate table update', async () => {
  const fixture = preview();
  const response = deferred();
  fixture.state.api = async (method, url, body) => {
    fixture.requests.push(plain(body));
    if (fixture.requests.length === 1) await response.promise;
    return { success: true };
  };
  const running = fixture.state.runMapTableRecompose('catchment');
  await until(() => fixture.requests.length === 1);
  fixture.state.scheduleMapRecomposeType('catchment');
  const first = fixture.state.flushMapTableRecompose('catchment');
  const second = fixture.state.flushMapTableRecompose('catchment');
  response.resolve();
  assert.deepEqual(await Promise.all([running, first, second]), [true, true, true]);
  assert.equal(fixture.requests.length, 2);
  assert.equal(fixture.timers.size, 0);
});
