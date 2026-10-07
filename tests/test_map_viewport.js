'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..');
const parts = ['01_croquis_survey.js', '02_map_edits.js', '02a_map_approval_viewport.js', '03_interactive_map.js'];
const source = parts.map(name => fs.readFileSync(path.join(root, 'assets/js/11-land-croquis', name), 'utf8')).join('\n');
const plain = value => JSON.parse(JSON.stringify(value));

function preview(mapType, width = 974, height = 548, bakedSize = { width: 1280, height: 720 }) {
  const live = { lat: 24.0002, lng: 46.0001, zoom: 18 };
  const requests = [];
  const image = { src: '', naturalWidth: bakedSize.width * 2, naturalHeight: bakedSize.height * 2, style: {} };
  const holder = { clientWidth: width, clientHeight: height, style: {} };
  const box = { style: {}, querySelector: () => image, scrollIntoView() {} };
  const creative = {
    map_placeholders: { ['##MAP_' + mapType.toUpperCase() + '##']: '/uploads/maps/old.png' },
    map_zooms: { [mapType]: live.zoom },
    map_centers: { [mapType]: { lat: live.lat, lng: live.lng } },
    map_baked_frames: { [mapType]: { ...live, ...bakedSize } },
    map_renderer_version: 'current', map_render_versions: { [mapType]: 'current' },
    map_approvals: {}, map_viewport_overrides: {}
  };
  const state = vm.createContext({
    console, live, holder, mapType,
    window: {},
    document: {
      getElementById: id => id === 'mapLiveView' ? holder : id === 'mapPreviewImage' ? box : null,
      querySelector: () => image
    },
    tenantCreativeImages: creative,
    tenantProjectData: { draftId: 'test-draft', location_lat: 24, location_lng: 46 },
    tenantProjectSectionStatuses: {}, tenantPresentationId: null, tenantPresentationRevision: 0,
    LOCATION_TABLE_FIELDS: {},
    hasPermission: () => true, isUsableMapCoordinate: () => true,
    slimMapProjectData: data => ({ ...data }),
    collectTenantFormData: async () => ({}), serializeLocationTable() {},
    saveProjectAsDraftNow: async () => true,
    mapPreviewStoredUrl: view => creative.map_placeholders[view.keys[0]] || '',
    mapPreviewIsVisible: () => true, mapPreviewIsGenerated: () => true,
    shouldHighlightTenantSite: () => true, mapsSignature: () => 'signature',
    accessRoadGeometry: () => [], catchmentMapLandmarks: () => [], nearbyMapLandmarks: () => [],
    renderLocationWorkflowState() {}, releaseLocationSectionApproval() {},
    triggerAutoSaveDraft() {}, showLoader() {}, hideLoader() {}, toast() {},
    setLocationDataFetchedAt() {}, withCacheBust: value => value,
    WFT: (key, fallback) => fallback,
    apiWithTimeout: async (method, url, body) => {
      requests.push(plain(body));
      const frame = body.projectData.map_centers[body.mapType];
      const width = frame.width || 1280;
      const height = frame.height || 720;
      image.naturalWidth = width * 2;
      image.naturalHeight = height * 2;
      return {
        success: true, mapRenderVersion: 'current',
        placeholders: { ['##MAP_' + body.mapType.toUpperCase() + '##']: '/uploads/maps/baked.png' },
        zooms: { [body.mapType]: body.projectData.map_zooms[body.mapType] },
        centers: { [body.mapType]: { ...frame, width, height } }
      };
    }
  });
  vm.runInContext(source, state);
  vm.runInContext(`
    tenantSelectedMapType = mapType;
    tenantMapPreviewState = { ...live, frameAccurate: true };
    tenantInteractiveMapType = mapType;
    tenantInteractiveMounted = true;
    tenantInteractiveProjection = {};
    tenantInteractiveMap = {
      getCenter: () => ({ lat: () => live.lat, lng: () => live.lng }),
      getZoom: () => live.zoom,
      setOptions() {}
    };
    mountInteractivePreview = async () => false;
  `, state);
  return { state, live, creative, requests, holder, image, run: code => vm.runInContext(code, state) };
}

test('approval synchronizes dimensions even when the camera did not move', () => {
  const fixture = preview('overview');
  fixture.state.syncInteractiveLiveFrame();
  assert.deepEqual(plain(fixture.creative.map_centers.overview), {
    lat: fixture.live.lat, lng: fixture.live.lng, width: 974, height: 548
  });
  assert.equal(fixture.run('tenantInteractiveFrameDirty.overview'), true);
  assert.equal(fixture.creative.map_viewport_overrides.overview, true);
});

// Only the land and roads maps mount a live frame; catchment and landmarks
// are fixed auto-framed rasters — edits there move labels, never the frame.
for (const mapType of ['overview', 'access']) {
  for (const [width, height] of [[375, 211], [974, 548], [1280, 720]]) {
    test(`${mapType} approval retains the ${width}x${height} live frame`, async () => {
      const fixture = preview(mapType, width, height);
      fixture.live.lat -= 0.0004;
      fixture.live.lng += 0.0003;
      fixture.live.zoom = 19;
      assert.equal(await fixture.state.approveTenantMap(mapType), true);
      assert.equal(fixture.requests.length, 1);
      const expected = { lat: fixture.live.lat, lng: fixture.live.lng, width, height };
      assert.deepEqual(fixture.requests[0].projectData.map_centers[mapType], expected);
      assert.deepEqual(plain(fixture.creative.map_centers[mapType]), expected);
      assert.deepEqual(plain(fixture.creative.map_baked_frames[mapType]), { ...expected, zoom: 19 });
      assert.equal(fixture.creative.map_approvals[mapType], true);
      assert.equal(fixture.run(`tenantInteractiveFrameDirty['${mapType}']`), false);
      assert.equal(fixture.run('tenantInteractiveMounted'), false);
      fixture.live.lat += 0.001;
      fixture.state.interactiveMapFrameChanged();
      assert.equal(fixture.creative.map_approvals[mapType], true);
      assert.deepEqual(plain(fixture.creative.map_centers[mapType]), expected);
    });
  }
}

for (const mapType of ['overview', 'access']) {
  test(`${mapType} restores an explicit viewport when the legacy baked size is missing`, async () => {
    const fixture = preview(mapType, 974, 548, { width: 974, height: 548 });
    fixture.creative.map_centers[mapType] = { lat: fixture.live.lat, lng: fixture.live.lng, width: 974, height: 548 };
    fixture.creative.map_baked_frames = {};
    fixture.state.evaluateInteractiveDirtyAtMount(mapType, fixture.live.lat, fixture.live.lng, 18);
    assert.equal(await fixture.state.approveTenantMap(mapType), true);
    assert.equal(fixture.requests.length, 1);
    assert.equal(fixture.requests[0].projectData.map_viewport_overrides[mapType], true);
  });
}

test('a resize without a pan requires a fresh bake', async () => {
  const fixture = preview('overview', 974, 548, { width: 974, height: 548 });
  fixture.creative.map_centers.overview = { ...fixture.live, width: 974, height: 548 };
  fixture.holder.clientWidth = 375;
  fixture.holder.clientHeight = 211;
  assert.equal(await fixture.state.approveTenantMap('overview'), true);
  assert.equal(fixture.requests.length, 1);
  assert.equal(fixture.creative.map_baked_frames.overview.width, 375);
  assert.equal(fixture.creative.map_baked_frames.overview.height, 211);
});

test('an unchanged correctly sized frame does not trigger another provider call', async () => {
  const fixture = preview('overview', 974, 548, { width: 974, height: 548 });
  fixture.creative.map_centers.overview = { lat: fixture.live.lat, lng: fixture.live.lng, width: 974, height: 548 };
  fixture.state.evaluateInteractiveDirtyAtMount('overview', fixture.live.lat, fixture.live.lng, 18);
  assert.equal(await fixture.state.approveTenantMap('overview'), true);
  assert.equal(fixture.requests.length, 0);
});

test('a recompose cannot clear a newer live size', () => {
  const fixture = preview('catchment', 974, 548, { width: 974, height: 548 });
  fixture.creative.map_centers.catchment = { lat: fixture.live.lat, lng: fixture.live.lng, width: 375, height: 211 };
  fixture.creative.map_viewport_overrides.catchment = true;
  fixture.state.noteInteractiveBakedFrame('catchment', 18, { lat: fixture.live.lat, lng: fixture.live.lng, width: 974, height: 548 });
  assert.equal(fixture.run('tenantInteractiveFrameDirty.catchment'), true);
  assert.equal(fixture.creative.map_centers.catchment.width, 375);
});

test('a small high-zoom pan is not mistaken for the baked center', async () => {
  const fixture = preview('overview', 974, 548, { width: 974, height: 548 });
  fixture.creative.map_centers.overview = { lat: fixture.live.lat, lng: fixture.live.lng, width: 974, height: 548 };
  fixture.live.lat -= 0.00001;
  assert.equal(await fixture.state.approveTenantMap('overview'), true);
  assert.equal(fixture.requests.length, 1);
  assert.equal(fixture.creative.map_baked_frames.overview.lat, fixture.live.lat);
});

test('a failed bake leaves the live frame unapproved', async () => {
  const fixture = preview('overview');
  fixture.state.apiWithTimeout = async () => ({ success: false, error: 'test failure' });
  assert.equal(await fixture.state.approveTenantMap('overview'), false);
  assert.notEqual(fixture.creative.map_approvals.overview, true);
  assert.equal(fixture.run('tenantInteractiveMounted'), true);
  assert.equal(fixture.run('tenantInteractiveFrameDirty.overview'), true);
});

for (const mapType of ['catchment', 'landmarks']) {
  test(`${mapType} is a fixed raster: no live frame record, no bake on approval`, async () => {
    const fixture = preview(mapType);
    assert.equal(fixture.run(`mapViewportAdjustable('${mapType}')`), false);
    assert.equal(fixture.run(`mapViewportAdjustable('${mapType === 'catchment' ? 'overview' : 'access'}')`), true);
    // A mounted camera on a fixed map must not write a frame or an override.
    fixture.state.syncInteractiveLiveFrame();
    assert.deepEqual(plain(fixture.creative.map_centers[mapType]), { lat: fixture.live.lat, lng: fixture.live.lng });
    assert.equal(fixture.creative.map_viewport_overrides[mapType], undefined);
    assert.equal(fixture.run(`tenantInteractiveFrameDirty['${mapType}']`), undefined);
    // Neither entry point mounts the live map for a fixed type.
    fixture.run('window.google = { maps: { Map: function () {}, OverlayView: function () {} } }');
    assert.equal(fixture.state.mountInteractiveMap(mapType, 24, 46, 18), false);
    assert.equal(await fixture.state.ensureInteractivePreview(mapType), false);
    // Approval certifies the stored raster directly — nothing is baked.
    assert.equal(await fixture.state.approveTenantMap(mapType), true);
    assert.equal(fixture.requests.length, 0);
    assert.equal(fixture.creative.map_approvals[mapType], true);
    assert.equal(fixture.run('tenantInteractiveMounted'), false);
  });
}

test('selecting a fixed map drops the mounted live view', () => {
  const fixture = preview('overview');
  fixture.creative.map_placeholders['##MAP_CATCHMENT##'] = '/uploads/maps/catchment.png';
  fixture.state.selectMapPreviewView('catchment');
  assert.equal(fixture.run('tenantInteractiveMounted'), false);
  assert.equal(fixture.holder.style.display, 'none');
});
