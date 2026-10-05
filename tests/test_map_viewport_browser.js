'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const source = ['01_croquis_survey.js', '02_map_edits.js', '03_interactive_map.js']
  .map(name => fs.readFileSync(path.join(root, 'assets/js/11-land-croquis', name), 'utf8')).join('\n');
const formSource = fs.readFileSync(path.join(root, 'assets/js/08-location-maps/02_catchment_edits.js'), 'utf8');
const markup = formSource.slice(formSource.indexOf('<div id="mapPreviewImage"'), formSource.indexOf('<p id="mapFrameDirtyHint"'));

async function verify(page, mapType, zoom) {
  await page.setContent('<style>*{box-sizing:border-box}body{margin:16px}</style>' +
    '<button id="approveMap">اعتماد الخريطة</button>' + markup);
  await page.evaluate(mapType => {
    window.testMapType = mapType;
    window.renderFrame = (center, zoom, width, height, scale = 1) => {
      const canvas = document.createElement('canvas');
      canvas.width = width * scale;
      canvas.height = height * scale;
      const context = canvas.getContext('2d');
      context.fillStyle = '#f4f6f8';
      context.fillRect(0, 0, canvas.width, canvas.height);
      const world = 256 * Math.pow(2, zoom) * scale;
      const mercator = lat => (1 - Math.log(Math.tan(lat * Math.PI / 180) + 1 / Math.cos(lat * Math.PI / 180)) / Math.PI) / 2;
      const x = canvas.width / 2 + (46 - center.lng) * world / 360;
      const y = canvas.height / 2 + (mercator(24) - mercator(center.lat)) * world;
      context.fillStyle = '#aa2222';
      context.fillRect(x - 12 * scale, y - 8 * scale, 24 * scale, 16 * scale);
      return canvas;
    };
    const old = window.renderFrame({ lat: 24.0002, lng: 46.0001 }, 18, 1280, 720, 2).toDataURL();
    Object.assign(window, {
      tenantCreativeImages: {
        map_placeholders: { ['##MAP_' + mapType.toUpperCase() + '##']: old },
        map_centers: { [mapType]: { lat: 24.0002, lng: 46.0001 } }, map_zooms: { [mapType]: 18 },
        map_baked_frames: { [mapType]: { lat: 24.0002, lng: 46.0001, zoom: 18, width: 1280, height: 720 } }
      },
      tenantProjectData: { draftId: 'browser-test', location_lat: 24, location_lng: 46 },
      tenantProjectSectionStatuses: {}, tenantPresentationId: null, tenantPresentationRevision: 0,
      LOCATION_TABLE_FIELDS: {},
      hasPermission: () => true, isUsableMapCoordinate: () => true,
      slimMapProjectData: data => ({ ...data }), collectTenantFormData: async () => ({}),
      serializeLocationTable() {}, saveProjectAsDraftNow: async () => true,
      mapPreviewStoredUrl: view => window.tenantCreativeImages.map_placeholders[view.keys[0]] || '',
      mapPreviewIsVisible: () => true, mapPreviewIsGenerated: () => true,
      shouldHighlightTenantSite: () => true, mapsSignature: () => 'signature',
      accessRoadGeometry: () => [], catchmentMapLandmarks: () => [], nearbyMapLandmarks: () => [],
      renderLocationWorkflowState() {}, releaseLocationSectionApproval() {},
      triggerAutoSaveDraft() {}, showLoader() {}, hideLoader() {}, toast() {}, setLocationDataFetchedAt() {},
      WFT: (key, fallback) => fallback,
      api: async () => ({ success: true }),
      apiWithTimeout: async (method, url, body) => {
        window.bakedRequest = JSON.parse(JSON.stringify(body));
        const type = body.mapType;
        const center = body.projectData.map_centers[type];
        const width = center.width || 1280;
        const height = center.height || 720;
        const zoom = body.projectData.map_zooms[type];
        return {
          success: true,
          centers: { [type]: { ...center, width, height } }, zooms: { [type]: zoom },
          placeholders: { ['##MAP_' + type.toUpperCase() + '##']: window.renderFrame(center, zoom, width, height, 2).toDataURL() }
        };
      }
    });
    class Map {
      constructor(holder, options) {
        this.holder = holder;
        this.listeners = {};
        this.setOptions(options);
        holder.addEventListener('pointerdown', event => {
          this.drag = { x: event.clientX, y: event.clientY, center: { ...this.center } };
          event.preventDefault();
        });
        window.addEventListener('pointermove', event => {
          if (!this.drag) return;
          const dx = event.clientX - this.drag.x;
          const dy = event.clientY - this.drag.y;
          const world = 256 * Math.pow(2, this.zoom);
          const rad = this.drag.center.lat * Math.PI / 180;
          const mercator = (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2 - dy / world;
          this.center = {
            lng: this.drag.center.lng - dx * 360 / world,
            lat: Math.atan(Math.sinh(Math.PI * (1 - 2 * mercator))) * 180 / Math.PI
          };
          this.draw();
        });
        window.addEventListener('pointerup', () => { this.drag = null; });
      }
      getCenter() { return { lat: () => this.center.lat, lng: () => this.center.lng }; }
      getZoom() { return this.zoom; }
      setCenter(center) { this.center = { ...center }; this.draw(); }
      setZoom(zoom) { this.zoom = zoom; this.draw(); }
      setOptions(options) {
        if (options.center) this.center = { ...options.center };
        if (options.zoom !== undefined) this.zoom = options.zoom;
        if (this.center) this.draw();
      }
      addListener(name, callback) { this.listeners[name] = callback; }
      draw() {
        const canvas = window.renderFrame(this.center, this.zoom, this.holder.clientWidth, this.holder.clientHeight);
        canvas.style.cssText = 'width:100%;height:100%;display:block';
        this.holder.replaceChildren(canvas);
      }
    }
    class OverlayView {
      setMap(map) { this.map = map; }
      getProjection() {
        return { fromLatLngToContainerPixel: point => {
          const world = 256 * Math.pow(2, this.map.zoom);
          const mercator = lat => (1 - Math.log(Math.tan(lat * Math.PI / 180) + 1 / Math.cos(lat * Math.PI / 180)) / Math.PI) / 2;
          return {
            x: this.map.holder.clientWidth / 2 + (point.lng() - this.map.center.lng) * world / 360,
            y: this.map.holder.clientHeight / 2 + (mercator(point.lat()) - mercator(this.map.center.lat)) * world
          };
        } };
      }
    }
    window.google = { maps: { Map, OverlayView,
      LatLng: function (lat, lng) { this.lat = () => lat; this.lng = () => lng; },
      event: { trigger: map => map.draw() }
    } };
    window.imageBounds = () => {
      const holder = document.getElementById('mapLiveView');
      const live = holder.style.display !== 'none';
      const node = live ? holder.querySelector('canvas') : document.querySelector('#mapPreviewImage img');
      const rect = node.getBoundingClientRect();
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(rect.width);
      canvas.height = Math.round(rect.height);
      const context = canvas.getContext('2d');
      context.drawImage(node, 0, 0, canvas.width, canvas.height);
      const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
      const bounds = [canvas.width, canvas.height, -1, -1];
      for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
        const i = (y * canvas.width + x) * 4;
        if (data[i] > 130 && data[i + 1] < 80 && data[i + 2] < 80) {
          bounds[0] = Math.min(bounds[0], x);
          bounds[1] = Math.min(bounds[1], y);
          bounds[2] = Math.max(bounds[2], x);
          bounds[3] = Math.max(bounds[3], y);
        }
      }
      return { bounds, width: canvas.width, height: canvas.height, live };
    };
  }, mapType);
  await page.addScriptTag({ content: source });
  await page.evaluate(async () => {
    withCacheBust = url => url;
    ensureInteractiveMapsApi = async () => true;
    selectMapPreviewView(window.testMapType);
    await tenantInteractiveMountPromise;
    document.getElementById('approveMap').onclick = () => {
      approveTenantMap(window.testMapType).then(result => { window.approvalDone = result; });
    };
  });
  const rect = await page.locator('#mapLiveView').boundingBox();
  await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
  await page.mouse.down();
  await page.mouse.move(rect.x + rect.width / 2 + 35, rect.y + rect.height / 2 - 24, { steps: 4 });
  await page.mouse.up();
  await page.evaluate(value => tenantInteractiveMap.setZoom(value), zoom);
  const before = await page.evaluate(() => window.imageBounds());
  assert(before.live);
  assert(before.bounds[2] > before.bounds[0]);
  await page.locator('#approveMap').click();
  await page.waitForFunction(() => window.approvalDone === true);
  await page.evaluate(() => document.querySelector('#mapPreviewImage img').decode());
  const after = await page.evaluate(() => window.imageBounds());
  assert.equal(after.live, false);
  assert.equal(after.width, before.width);
  assert.equal(after.height, before.height);
  for (let index = 0; index < 4; index++) assert(Math.abs(after.bounds[index] - before.bounds[index]) <= 1,
    `${mapType}: marker moved at boundary ${index}: ${before.bounds} became ${after.bounds}`);
  const request = await page.evaluate(() => window.bakedRequest);
  assert.equal(request.projectData.map_centers[mapType].width, before.width);
  assert.equal(request.projectData.map_centers[mapType].height, before.height);
  console.log(`${mapType} ${before.width}x${before.height} zoom ${zoom}: approved raster retains the live marker bounds`);
}

(async () => {
  const channel = process.env.PLAYWRIGHT_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, channel });
  try {
    for (const width of [390, 1024, 1440]) {
      // Only the land and roads maps mount a live frame — catchment and
      // landmarks stay fixed rasters, so there is nothing to bake-match.
      for (const mapType of ['overview', 'access']) {
        for (const zoom of [16, 19]) {
          const page = await browser.newPage({ viewport: { width, height: 1000 } });
          const errors = [];
          page.on('pageerror', error => errors.push(error.message));
          try {
            await verify(page, mapType, zoom);
            assert.deepEqual(errors, []);
          } finally {
            await page.close();
          }
        }
      }
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
