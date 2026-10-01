'use strict';
// Frontend integrity check for the split shell.
//
// index.html is a slim shell: styles live in assets/css and code in ordered
// classic scripts under assets/js (one shared global scope, no async, no
// modules). The shell references two server-built bundles
// (/assets/app.bundle.js + /assets/app.bundle.css) so a cold load costs four
// static requests instead of twenty-two; app.py concatenates the part files
// in order with /*__PART:name__*/ markers and serves them with an ETag, so
// there is no build step and editing a part file is enough.
//
// This script verifies that the shell references the bundles (never part
// files), that the bundle order in app.py matches the on-disk set exactly,
// that no inline <script>/<style> code was left behind, and that every part
// plus the concatenated bundle still parses (node --check).
//
// Run: node scripts/verify-frontend.js  (from the repo root)

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const ROOT = path.resolve(__dirname, '..');
const failures = [];
const fail = (msg) => failures.push(msg);

const shell = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

// 1. i18n runtime loads first (absolute path: client routes would 404 a relative one),
// preceded by its dictionary bundle (/assets/i18n.bundle.js).
if (!shell.includes('src="/assets/i18n.js"')) fail('shell must include <script src="/assets/i18n.js">');
const i18nPos = shell.indexOf('/assets/i18n.js');
const bundleJsPos = shell.indexOf('/assets/app.bundle.js');
if (bundleJsPos < 0) fail('shell must include <script src="/assets/app.bundle.js">');
if (i18nPos > bundleJsPos && bundleJsPos >= 0) fail('assets/i18n.js must load BEFORE the application bundle');
const i18nDictDir = path.join(ROOT, 'assets', 'i18n');
const i18nDictFiles = fs.existsSync(i18nDictDir)
  ? fs.readdirSync(i18nDictDir).filter((f) => f.endsWith('.js')).sort() : [];
if (!i18nDictFiles.length) fail('assets/i18n/ dictionary parts are missing');
const i18nBundlePos = shell.indexOf('src="/assets/i18n.bundle.js"');
if (i18nBundlePos < 0) fail('shell must load /assets/i18n.bundle.js before i18n.js');
else if (i18nBundlePos > i18nPos) fail('assets/i18n.bundle.js must load BEFORE i18n.js');
// The shell references the bundle, never the parts: eighteen blocking requests
// per page view is what the bundle exists to prevent.
for (const name of i18nDictFiles) {
  if (shell.includes(`/assets/i18n/${name}`)) {
    fail(`shell must not reference dictionary part /assets/i18n/${name} directly; use /assets/i18n.bundle.js`);
  }
}
// The bundle order authority is app.py (FRONTEND_I18N_ORDER) and must match
// the on-disk set exactly, so no part is silently dropped from the bundle.
const appPartsDir2 = path.join(ROOT, 'app_parts');
const appSource2 = ['app.py'].concat(
  fs.existsSync(appPartsDir2) ? fs.readdirSync(appPartsDir2).filter((f) => f.endsWith('.py')).sort().map((f) => 'app_parts/' + f) : []
).map((f) => fs.readFileSync(path.join(ROOT, f), 'utf8')).join('\n');
const i18nOrder = readOrderTuple(appSource2, 'FRONTEND_I18N_ORDER');
if (!i18nOrder || !i18nOrder.length) fail('app.py must define FRONTEND_I18N_ORDER');
if (i18nOrder) {
  for (const name of i18nOrder) {
    if (!fs.existsSync(path.join(i18nDictDir, name))) fail(`assets/i18n/${name} is listed in FRONTEND_I18N_ORDER but missing on disk`);
  }
  const orphans = i18nDictFiles.filter((f) => !i18nOrder.includes(f));
  if (orphans.length) fail(`assets/i18n parts not in FRONTEND_I18N_ORDER (never loaded): ${orphans.join(', ')}`);
  if ([...i18nOrder].sort().join() !== i18nDictFiles.join()) {
    fail('FRONTEND_I18N_ORDER must match the sorted dictionary part names');
  }
}

// 2. The shell references bundles, never part files.
for (const m of shell.matchAll(/<script src="\/assets\/js\/([^"]+)"><\/script>/g)) {
  fail(`shell must not reference part file assets/js/${m[1]} directly; use /assets/app.bundle.js`);
}
for (const m of shell.matchAll(/<link rel="stylesheet" href="\/assets\/css\/([^"]+)">/g)) {
  fail(`shell must not reference part file assets/css/${m[1]} directly; use /assets/app.bundle.css`);
}
if (!shell.includes('href="/assets/app.bundle.css"')) fail('shell must include <link rel="stylesheet" href="/assets/app.bundle.css">');

// 3. No inline code blocks left in the shell.
const bareScripts = [...shell.matchAll(/^\s*<script>\s*$/gm)].map((m) => m[0]);
if (bareScripts.length) fail(`shell still carries ${bareScripts.length} inline <script> block(s)`);
for (const m of shell.matchAll(/<style[^>]*>/g)) {
  fail(`shell still carries an inline <style> block: ${m[0].slice(0, 60)}`);
}

// 4. Bundle order authority is app.py; it must match the on-disk set exactly
// (no orphans, no forgotten files).
function readOrderTuple(source, name) {
  const m = source.match(new RegExp(name + '\\s*=\\s*\\(([\\s\\S]*?)\\)'));
  if (!m) return null;
  return [...m[1].matchAll(/'([^']+)'/g)].map((part) => part[1]);
}
const appPartsDir = path.join(ROOT, 'app_parts');
const appSourceFiles = ['app.py'];
if (fs.existsSync(appPartsDir)) {
  for (const part of fs.readdirSync(appPartsDir).filter((f) => f.endsWith('.py')).sort()) {
    appSourceFiles.push(path.join('app_parts', part));
  }
}
const appSource = appSourceFiles.map((f) => fs.readFileSync(path.join(ROOT, f), 'utf8')).join('\n');
const jsOrder = readOrderTuple(appSource, 'FRONTEND_JS_ORDER');
const cssOrder = readOrderTuple(appSource, 'FRONTEND_CSS_ORDER');
if (!jsOrder || !jsOrder.length) fail('app.py must define FRONTEND_JS_ORDER');
if (!cssOrder || !cssOrder.length) fail('app.py must define FRONTEND_CSS_ORDER');
for (const [order, dir, ext] of [[jsOrder || [], 'js', '.js'], [cssOrder || [], 'css', '.css']]) {
  const seen = new Set();
  for (const name of order) {
    if (seen.has(name)) fail(`bundle order lists assets/${dir}/${name} twice`);
    seen.add(name);
    if (!fs.existsSync(path.join(ROOT, 'assets', dir, name))) fail(`assets/${dir}/${name} is missing`);
  }
  const walk = (d, base) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(path.join(d, e.name), base ? base + '/' + e.name : e.name)
                    : (base ? base + '/' : '') + e.name);
  const onDisk = walk(path.join(ROOT, 'assets', dir), '').filter((f) => f.endsWith(ext)).sort();
  const missing = onDisk.filter((f) => !order.includes(f));
  if (missing.length) fail(`assets/${dir} files not in the bundle order: ${missing.join(', ')}`);
}

// 5. Every part parses on its own, and the concatenated bundle parses as one
// script/stylesheet (catches a missing-semicolon merge between parts).
const node = process.execPath;
const checkJs = (target, label) => {
  const proc = spawnSync(node, ['--check', target], { encoding: 'utf8' });
  if (proc.status !== 0) fail(`node --check ${label} failed:\n${proc.stderr}`);
};
checkJs(path.join(ROOT, 'assets', 'i18n.js'), 'assets/i18n.js');
for (const name of i18nDictFiles) {
  checkJs(path.join(i18nDictDir, name), `assets/i18n/${name}`);
}
// The dictionary parts merge into one global, so the concatenated bundle must
// parse as a single script too.
if (i18nOrder && i18nOrder.length) {
  const os0 = require('node:os');
  const tmpI18n = path.join(os0.tmpdir(), 'verify-frontend-i18n-bundle.js');
  fs.writeFileSync(tmpI18n, i18nOrder.map((name) => {
    const content = fs.readFileSync(path.join(i18nDictDir, name), 'utf8');
    return '\n;\n/*__PART:' + name + '*/\n' + content;
  }).join(''));
  checkJs(tmpI18n, 'concatenated i18n.bundle.js');
}
for (const name of jsOrder || []) {
  checkJs(path.join(ROOT, 'assets', 'js', name), `assets/js/${name}`);
}
if (jsOrder) {
  const os = require('node:os');
  const tmp = path.join(os.tmpdir(), 'verify-frontend-bundle.js');
  const bundle = jsOrder.map((name) => {
    const content = fs.readFileSync(path.join(ROOT, 'assets', 'js', name), 'utf8');
    return '\n;\n/*__PART:' + name + '*/\n' + content;
  }).join('');
  fs.writeFileSync(tmp, bundle);
  checkJs(tmp, 'concatenated app.bundle.js');
}

if (failures.length) {
  console.error(`verify-frontend: ${failures.length} problem(s):\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`verify-frontend: OK (shell + bundles ${(jsOrder || []).length} js + ${(cssOrder || []).length} css, all parse)`);
