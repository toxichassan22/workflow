'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

// Load 01-nav-auth.js and 01_routing.js into a shared sandbox environment
const rootDir = path.resolve(__dirname, '..', '..');
const navAuthCode = fs.readFileSync(path.join(rootDir, 'assets', 'js', '01-nav-auth.js'), 'utf-8');
const routingCode = fs.readFileSync(path.join(rootDir, 'assets', 'js', '02-settings-branding', '01_routing.js'), 'utf-8');

const mockLocalStorage = {
  data: {},
  getItem(k) { return this.data[k] || null; },
  setItem(k, v) { this.data[k] = String(v); },
  removeItem(k) { delete this.data[k]; }
};

const sandbox = {
  window: { addEventListener: () => {} },
  document: {
    querySelectorAll: () => [],
    getElementById: () => null,
    addEventListener: () => {},
    documentElement: { style: {} },
    body: { classList: { toggle: () => false, add: () => {}, remove: () => {} } }
  },
  history: {
    state: null,
    replaceState(st, title, url) { this.state = st; sandbox.window.location.pathname = url.split('?')[0]; },
    pushState(st, title, url) { this.state = st; sandbox.window.location.pathname = url.split('?')[0]; }
  },
  localStorage: mockLocalStorage,
  sessionStorage: mockLocalStorage,
  URLSearchParams,
  console,
  setTimeout: () => {},
  clearTimeout: () => {},
  tenantUser: { slug: 'acme-corp', isAdmin: false },
  tenantProjectData: null,
  tenantActiveProjectSection: 'basic',
  tenantPresentationId: null,
  tenantSlidesView: 'edit',
  tenantSlidesData: []
};
sandbox.window.location = { pathname: '/', search: '' };
sandbox.window.history = sandbox.history;

vm.createContext(sandbox);
vm.runInContext(navAuthCode, sandbox);
vm.runInContext(routingCode, sandbox);

console.log('--- Testing resolveTenantRoutePath ---');

// 1. Superadmin static & dynamic routes
let res = sandbox.resolveTenantRoutePath('/superadmin');
assert.strictEqual(res.pageId, 'tenantAdminPage');
assert.strictEqual(res.prefix, '/superadmin');

res = sandbox.resolveTenantRoutePath('/superadmin/dashboard');
assert.strictEqual(res.pageId, 'tenantDashboardPage');

res = sandbox.resolveTenantRoutePath('/superadmin/projects/new');
assert.strictEqual(res.pageId, 'tenantProjectPage');
assert.strictEqual(res.mode, 'new');
assert.strictEqual(res.draftId, null);
assert.strictEqual(res.activeSection, 'basic');

res = sandbox.resolveTenantRoutePath('/superadmin/projects/new/market');
assert.strictEqual(res.pageId, 'tenantProjectPage');
assert.strictEqual(res.mode, 'new');
assert.strictEqual(res.activeSection, 'market');

res = sandbox.resolveTenantRoutePath('/superadmin/projects/draft-101');
assert.strictEqual(res.pageId, 'tenantProjectPage');
assert.strictEqual(res.draftId, 'draft-101');
assert.strictEqual(res.activeSection, 'basic');

res = sandbox.resolveTenantRoutePath('/superadmin/projects/draft-101/financial');
assert.strictEqual(res.pageId, 'tenantProjectPage');
assert.strictEqual(res.draftId, 'draft-101');
assert.strictEqual(res.activeSection, 'financial');

res = sandbox.resolveTenantRoutePath('/superadmin/projects/draft-101/presentations');
assert.strictEqual(res.pageId, 'tenantProjectPresentationsPage');
assert.strictEqual(res.draftId, 'draft-101');

res = sandbox.resolveTenantRoutePath('/superadmin/projects/draft-101/visual-concept');
assert.strictEqual(res.pageId, 'tenantVisualConceptPage');
assert.strictEqual(res.draftId, 'draft-101');

res = sandbox.resolveTenantRoutePath('/superadmin/presentations');
assert.strictEqual(res.pageId, 'tenantPresentationsPage');

res = sandbox.resolveTenantRoutePath('/superadmin/presentations/current');
assert.strictEqual(res.pageId, 'tenantSlidesPage');
assert.strictEqual(res.presentationId, null);

res = sandbox.resolveTenantRoutePath('/superadmin/presentations/pres-555');
assert.strictEqual(res.pageId, 'tenantSlidesPage');
assert.strictEqual(res.presentationId, 'pres-555');
assert.strictEqual(res.slidesView, 'edit');

res = sandbox.resolveTenantRoutePath('/superadmin/presentations/pres-555/sorter');
assert.strictEqual(res.pageId, 'tenantSlidesPage');
assert.strictEqual(res.presentationId, 'pres-555');
assert.strictEqual(res.slidesView, 'sorter');

res = sandbox.resolveTenantRoutePath('/superadmin/presentations/pres-555/present');
assert.strictEqual(res.pageId, 'tenantSlidesPage');
assert.strictEqual(res.presentationId, 'pres-555');
assert.strictEqual(res.slidesView, 'present');

res = sandbox.resolveTenantRoutePath('/superadmin/presentations/pres-555/slides/6');
assert.strictEqual(res.pageId, 'tenantSlidesPage');
assert.strictEqual(res.presentationId, 'pres-555');
assert.strictEqual(res.slideIndex, 5);

// 2. Company scoped dynamic routes
res = sandbox.resolveTenantRoutePath('/c/roshn/projects/d-88/location');
assert.strictEqual(res.pageId, 'tenantProjectPage');
assert.strictEqual(res.prefix, '/c/roshn');
assert.strictEqual(res.urlSlug, 'roshn');
assert.strictEqual(res.draftId, 'd-88');
assert.strictEqual(res.activeSection, 'location');

res = sandbox.resolveTenantRoutePath('/c/roshn/projects/d-88/presentations');
assert.strictEqual(res.pageId, 'tenantProjectPresentationsPage');
assert.strictEqual(res.draftId, 'd-88');

res = sandbox.resolveTenantRoutePath('/c/roshn/presentations/p-99/sorter');
assert.strictEqual(res.pageId, 'tenantSlidesPage');
assert.strictEqual(res.presentationId, 'p-99');
assert.strictEqual(res.slidesView, 'sorter');

res = sandbox.resolveTenantRoutePath('/c/roshn/settings/team');
assert.strictEqual(res.pageId, 'tenantTeamPage');
assert.strictEqual(res.urlSlug, 'roshn');

console.log('resolveTenantRoutePath tests passed.');

console.log('--- Testing tenantCanonicalRoute ---');

// Default tenant: acme-corp
sandbox.tenantUser = { slug: 'acme-corp', isAdmin: false };
sandbox.tenantProjectData = null;
sandbox.tenantPresentationId = null;

// New project
let route = sandbox.tenantCanonicalRoute('tenantProjectPage', { mode: 'new', activeSection: 'basic' });
assert.strictEqual(route, '/c/acme-corp/projects/new');

route = sandbox.tenantCanonicalRoute('tenantProjectPage', { mode: 'new', activeSection: 'market' });
assert.strictEqual(route, '/c/acme-corp/projects/new/market');

// Existing draft
route = sandbox.tenantCanonicalRoute('tenantProjectPage', { draftId: 'd-123', activeSection: 'basic' });
assert.strictEqual(route, '/c/acme-corp/projects/d-123');

route = sandbox.tenantCanonicalRoute('tenantProjectPage', { draftId: 'd-123', activeSection: 'financial' });
assert.strictEqual(route, '/c/acme-corp/projects/d-123/financial');

// Previous presentations for a project
route = sandbox.tenantCanonicalRoute('tenantProjectPresentationsPage', { draftId: 'd-123' });
assert.strictEqual(route, '/c/acme-corp/projects/d-123/presentations');

// Visual concept for a project
route = sandbox.tenantCanonicalRoute('tenantVisualConceptPage', { draftId: 'd-123' });
assert.strictEqual(route, '/c/acme-corp/projects/d-123/visual-concept');

// Presentations workspace
route = sandbox.tenantCanonicalRoute('tenantSlidesPage', {});
assert.strictEqual(route, '/c/acme-corp/presentations/current');

route = sandbox.tenantCanonicalRoute('tenantSlidesPage', { presentationId: 'p-777', slidesView: 'edit' });
assert.strictEqual(route, '/c/acme-corp/presentations/p-777');

route = sandbox.tenantCanonicalRoute('tenantSlidesPage', { presentationId: 'p-777', slidesView: 'sorter' });
assert.strictEqual(route, '/c/acme-corp/presentations/p-777/sorter');

route = sandbox.tenantCanonicalRoute('tenantSlidesPage', { presentationId: 'p-777', slidesView: 'present' });
assert.strictEqual(route, '/c/acme-corp/presentations/p-777/present');

route = sandbox.tenantCanonicalRoute('tenantSlidesPage', { presentationId: 'p-777', slideIndex: 3, slidesView: 'edit' });
assert.strictEqual(route, '/c/acme-corp/presentations/p-777/slides/4');

// Superadmin canonical route
sandbox.tenantUser = { slug: 'acme-corp', isAdmin: true };
route = sandbox.tenantCanonicalRoute('tenantProjectPage', { draftId: 'd-123', activeSection: 'market' });
assert.strictEqual(route, '/superadmin/projects/d-123/market');

route = sandbox.tenantCanonicalRoute('tenantSlidesPage', { presentationId: 'p-777', slidesView: 'sorter' });
assert.strictEqual(route, '/superadmin/presentations/p-777/sorter');

console.log('tenantCanonicalRoute tests passed.');

console.log('All tenant routing tests passed successfully.');
