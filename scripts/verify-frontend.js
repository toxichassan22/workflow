'use strict';
// Frontend integrity check for the split shell.
//
// index.html is a slim shell: styles live in assets/css and code in ordered
// classic scripts under assets/js (one shared global scope, no async, no
// modules). This script verifies that the shell references every part exactly
// once in order, that no inline <script>/<style> code was left behind, and
// that every script still parses (node --check).
//
// Run: node scripts/verify-frontend.js  (from the repo root)

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const ROOT = path.resolve(__dirname, '..');
const failures = [];
const fail = (msg) => failures.push(msg);

const shell = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

// 1. i18n runtime loads first (absolute path: client routes would 404 a relative one).
if (!shell.includes('src="/assets/i18n.js"')) fail('shell must include <script src="/assets/i18n.js">');
const i18nPos = shell.indexOf('/assets/i18n.js');
const firstApp = shell.indexOf('/assets/js/');
if (firstApp < 0) fail('shell references no /assets/js/ scripts');
if (i18nPos > firstApp) fail('assets/i18n.js must load BEFORE the application scripts');

// 2. No inline code blocks left in the shell.
const bareScripts = [...shell.matchAll(/^\s*<script>\s*$/gm)].map((m) => m[0]);
if (bareScripts.length) fail(`shell still carries ${bareScripts.length} inline <script> block(s)`);
for (const m of shell.matchAll(/<style(?![^>]*id="zai-global-styles")[^>]*>/g)) {
  fail(`shell still carries an inline <style> block: ${m[0].slice(0, 60)}`);
}

// 3. Every referenced asset exists, exactly once, in order.
const jsRefs = [...shell.matchAll(/<script src="\/assets\/js\/([^"]+)"><\/script>/g)].map((m) => m[1]);
const cssRefs = [...shell.matchAll(/<link rel="stylesheet" href="\/assets\/css\/([^"]+)">/g)].map((m) => m[1]);
if (!jsRefs.length) fail('no app scripts referenced');
if (!cssRefs.length) fail('no stylesheets referenced');
for (const [kind, refs, dir] of [['js', jsRefs, 'js'], ['css', cssRefs, 'css']]) {
  const seen = new Set();
  for (const name of refs) {
    if (seen.has(name)) fail(`assets/${dir}/${name} referenced twice`);
    seen.add(name);
    if (!fs.existsSync(path.join(ROOT, 'assets', dir, name))) fail(`assets/${dir}/${name} is missing`);
  }
}
// The on-disk set must equal the referenced set (no orphan, no forgotten file).
for (const [refs, dir, ext] of [[jsRefs, 'js', '.js'], [cssRefs, 'css', '.css']]) {
  const onDisk = fs.readdirSync(path.join(ROOT, 'assets', dir)).filter((f) => f.endsWith(ext)).sort();
  const missing = onDisk.filter((f) => !refs.includes(f));
  if (missing.length) fail(`assets/${dir} files not referenced by the shell: ${missing.join(', ')}`);
}

// 4. Every script parses on its own (cuts are at top-level boundaries).
const node = process.execPath;
for (const name of ['i18n.js', ...jsRefs.map((n) => `js/${n}`)]) {
  const target = path.join(ROOT, 'assets', name);
  if (!fs.existsSync(target)) continue;
  const proc = spawnSync(node, ['--check', target], { encoding: 'utf8' });
  if (proc.status !== 0) fail(`node --check assets/${name} failed:\n${proc.stderr}`);
}

if (failures.length) {
  console.error(`verify-frontend: ${failures.length} problem(s):\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`verify-frontend: OK (shell + ${cssRefs.length} css + ${jsRefs.length} js, all parse)`);
