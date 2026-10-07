'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const source = fs.readdirSync(path.join(root, 'assets/js/11-land-croquis'))
  .filter(name => name.endsWith('.js')).sort()
  .map(name => fs.readFileSync(path.join(root, 'assets/js/11-land-croquis', name), 'utf8')).join('\n');
const css = fs.readFileSync(path.join(root, 'assets/css/project-form/01a_location_maps.css'), 'utf8');
const form = fs.readFileSync(path.join(root, 'assets/js/08-location-maps/02_catchment_edits.js'), 'utf8');
const markup = form.slice(form.indexOf('<div id="mapPreviewImage"'), form.indexOf('<p id="mapFrameDirtyHint"'));
const python = process.env.PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');

function fixture(mapType) {
  const result = spawnSync(python, ['-c',
    `import json; from tests.test_map_preview_parity import render_browser_fixture; print(json.dumps(render_browser_fixture('${mapType}')))`],
  { cwd: root, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1));
}

async function verify(page, data) {
  await page.setContent('<style>*{box-sizing:border-box}body{margin:16px}' + css + '</style>' + markup);
  await page.evaluate(data => {
    const mapType = data.type;
    window.fixture = data;
    const token = '##MAP_' + mapType.toUpperCase() + '##';
    Object.assign(window, {
      tenantCreativeImages: {
        map_placeholders: { [token]: data.marked, [token.slice(0, -2) + '_EDITABLE##']: data.clean },
        map_centers: { [mapType]: data.center }, map_zooms: { [mapType]: data.zoom },
        map_baked_frames: { [mapType]: { ...data.center, zoom: data.zoom } }, map_approvals: {}
      },
      tenantProjectData: { draftId: 'parity-test', location_lat: 24, location_lng: 46,
        location_polygon: data.polygon.map(point => point.join(',')).join(';') },
      tenantProjectSectionStatuses: {}, tenantPresentationId: null, tenantPresentationRevision: 0,
      LOCATION_TABLE_FIELDS: {}, hasPermission: () => true,
      isUsableMapCoordinate: (value, latitude) => Number.isFinite(Number(value)),
      slimMapProjectData: value => ({ ...value }), saveProjectAsDraftNow: async () => true,
      shouldHighlightTenantSite: () => true, mapsSignature: () => 'signature',
      mapPreviewStoredUrl: view => window.tenantCreativeImages.map_placeholders[view.keys[0]] || '',
      mapPreviewIsVisible: () => true, mapPreviewIsGenerated: () => true,
      accessRoadGeometry: () => data.roads,
      catchmentMapLandmarks: () => data.items, nearbyMapLandmarks: () => data.items,
      renderLocationWorkflowState() {}, releaseLocationSectionApproval() {}, triggerAutoSaveDraft() {},
      toast() {}, WFT: (key, fallback) => fallback,
      escapeHtml: value => String(value ?? '').replace(/[&<>"']/g, char =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]),
      api: async () => ({ success: true, placeholders: { [token]: data.marked },
        zooms: { [mapType]: data.zoom }, centers: { [mapType]: data.center },
        catchmentLandmarks: data.items, landmarkMapItems: data.items, accessRoads: data.roads })
    });
  }, data);
  await page.addScriptTag({ content: source });
  await page.evaluate(async () => {
    withCacheBust = url => url;
    mountInteractivePreview = async () => false;
    tenantMapPolygonPoints = fixture.polygon;
    selectMapPreviewView(fixture.type);
    await document.querySelector('#mapPreviewImage img').decode();
    await document.fonts.load('700 12px "Landloom Map"');
    await document.fonts.ready;
    renderTenantMapPolygonOverlay();
  });
  const dimensions = await page.evaluate(() => {
    const image = document.querySelector('#mapPreviewImage img');
    const box = document.getElementById('mapPreviewImage').getBoundingClientRect();
    const labels = Array.from(document.querySelectorAll('.map-place-label,.map-road-label')).map(label => {
      const rect = label.getBoundingClientRect();
      const style = getComputedStyle(label);
      return { x: rect.x - box.x, y: rect.y - box.y, width: rect.width, height: rect.height,
        font: style.fontFamily, weight: style.fontWeight };
    });
    const site = document.querySelector('.map-site-marker').getBoundingClientRect();
    return { width: image.clientWidth, height: image.clientHeight, labels,
      site: { x: site.x - box.x, y: site.y - box.y, width: site.width, height: site.height } };
  });
  const ratio = dimensions.width / 2560;
  assert(Math.abs(dimensions.site.width - dimensions.site.height) < 0.1);
  assert(Math.abs(dimensions.site.width - 51 * dimensions.width / 1000) < 0.1);
  assert.equal(dimensions.labels.length, data.layouts.length);
  dimensions.labels.forEach((label, index) => {
    assert(label.font.includes('Landloom Map'));
    assert.equal(label.weight, '700');
    const expected = data.layouts[index];
    // Pillow has no HarfBuzz: it measures the reshaped presentation forms,
    // which run a percent or two wider than the browser's OpenType shaping —
    // per-string ligature counts decide the sign, so the check allows a
    // proportional drift instead of an absolute one.
    const widthTolerance = Math.max(2, expected.width * ratio * 0.02);
    assert(Math.abs(label.width - expected.width * ratio) <= widthTolerance,
      `${data.type}: label width ${label.width} differs from baked width ${expected.width * ratio}`);
    assert(Math.abs(label.height - expected.height * ratio) <= 2,
      `${data.type}: label height ${label.height} differs from baked height ${expected.height * ratio}`);
  });
  const before = await page.locator('#mapPreviewImage').screenshot();
  assert.equal(await page.evaluate(() => approveTenantMap(fixture.type)), true);
  await page.evaluate(() => document.querySelector('#mapPreviewImage img').decode());
  const after = await page.locator('#mapPreviewImage').screenshot();
  const compare = await page.evaluate(async ({ before, after, dimensions }) => {
    async function pixels(base64) {
      const image = new Image();
      image.src = 'data:image/png;base64,' + base64;
      await image.decode();
      const canvas = document.createElement('canvas');
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const context = canvas.getContext('2d');
      context.drawImage(image, 0, 0);
      return { width: canvas.width, height: canvas.height,
        pixels: context.getImageData(0, 0, canvas.width, canvas.height).data };
    }
    function bounds(image, rect, target, inset) {
      const result = [image.width, image.height, -1, -1];
      const ix = inset ? inset.x : 0, iy = inset ? inset.y : 0;
      // An inset probe (label ink) scans the interior only — re-adding the
      // outer tolerance would expose the cream border as bright pixels again.
      const margin = inset ? 0 : 3;
      for (let y = Math.max(0, Math.floor(rect.y + iy) - margin); y < Math.min(image.height, Math.ceil(rect.y + rect.height - iy) + margin); y++) {
        for (let x = Math.max(0, Math.floor(rect.x + ix) - margin); x < Math.min(image.width, Math.ceil(rect.x + rect.width - ix) + margin); x++) {
          const i = (y * image.width + x) * 4;
          if (target(image.pixels[i], image.pixels[i + 1], image.pixels[i + 2])) {
            result[0] = Math.min(result[0], x); result[1] = Math.min(result[1], y);
            result[2] = Math.max(result[2], x); result[3] = Math.max(result[3], y);
          }
        }
      }
      return result[2] >= result[0] ? result : null;
    }
    const color = target => (r, g, b) =>
      Math.abs(r - target[0]) <= 8 && Math.abs(g - target[1]) <= 8 && Math.abs(b - target[2]) <= 8;
    // Glyph ink is probed by luminance inside the pill's content area, not by
    // exact white: a baked label is a downscaled raster, and small text is all
    // anti-aliased edge pixels, so it holds no (255,255,255) even though the
    // glyphs are there. The inset (label padding + border, in cqw) keeps the
    // cream border out of the probe so only text registers as ink.
    const ink = (r, g, b) => 0.2126 * r + 0.7152 * g + 0.0722 * b > 140;
    const old = await pixels(before);
    const current = await pixels(after);
    const inkInset = Math.max(2, Math.round(old.width * 0.009));
    const inkInsetY = Math.max(1, Math.round(old.width * 0.005));
    return { old: [old.width, old.height], current: [current.width, current.height],
      regions: [{ rect: dimensions.site, probes: [
          { label: '255,255,255', run: (r, image) => bounds(image, r, color([255, 255, 255])) },
          { label: '107,28,35', run: (r, image) => bounds(image, r, color([107, 28, 35])) }] },
        ...dimensions.labels.map(rect => ({ rect, probes: [
          { label: '37,75,102', run: (r, image) => bounds(image, r, color([37, 75, 102])) },
          { label: 'text-ink', run: (r, image) => bounds(image, r, ink, { x: inkInset, y: inkInsetY }) }] }))]
        .map(region => region.probes.map(probe => ({ label: probe.label,
          before: probe.run(region.rect, old), after: probe.run(region.rect, current) }))) };
  }, { before: before.toString('base64'), after: after.toString('base64'), dimensions });
  assert.deepEqual(compare.current, compare.old);
  compare.regions.flat().forEach(region => {
    assert(region.before && region.after, `${data.type}: missing ${region.label} pixels in the approved frame`);
    region.before.forEach((value, index) => assert(Math.abs(value - region.after[index]) <= 2,
      `${data.type}: ${region.label} bounds ${region.before} became ${region.after}`));
  });
  console.log(`${data.type} ${dimensions.width}px: DOM and Pillow retain label, glyph and circular marker bounds`);
}

(async () => {
  const font = fs.readFileSync(path.join(root, 'assets/fonts/BahijTheSansArabic-Bold.ttf'));
  const server = http.createServer((request, response) => {
    if (request.url === '/assets/fonts/BahijTheSansArabic-Bold.ttf') {
      response.writeHead(200, { 'Content-Type': 'font/ttf' });
      response.end(font);
    } else {
      response.writeHead(200, { 'Content-Type': 'text/html' });
      response.end('<!doctype html><html><head></head><body></body></html>');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    const channel = process.env.PLAYWRIGHT_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
    browser = await chromium.launch({ headless: true, channel });
    const data = ['overview', 'access', 'catchment', 'landmarks'].map(fixture);
    const failures = [];
    for (const width of [390, 1024, 1440]) {
      for (const item of data) {
        const page = await browser.newPage({ viewport: { width, height: 1000 } });
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        try {
          await page.goto('http://127.0.0.1:' + server.address().port);
          await verify(page, item);
          assert.deepEqual(errors, []);
        } catch (error) {
          failures.push(`${item.type}@${width}: ${error.message}`);
        } finally {
          await page.close();
        }
      }
    }
    assert.deepEqual(failures, []);
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
