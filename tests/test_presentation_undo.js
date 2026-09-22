'use strict';
// Run with node tests/test_presentation_undo.js; uses the actual inline functions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
// index.html is a slim shell now; the code under test lives in ordered classic
// scripts. Mirrors FRONTEND_JS_ORDER in app_parts/22_rules_approvals_static.py.
const FRONTEND_JS_ORDER = ['00-core.js', '01-nav-auth.js', '02-settings-branding/01_routing.js',
  '02-settings-branding/02_auth_boot.js',
  '03-executive-classification.js', '04-market.js', '05-market-competitors.js',
  '06-team.js', '07-project-form/01_form_sections.js',
  '07-project-form/02_section_versions.js', '08-location-maps/01_tables_approvals.js',
  '08-location-maps/02_catchment_edits.js', '09-financial/01_financial_format.js',
  '09-financial/02_formulas_calc.js',
  '10-financial-report-timeline/01_report_collect.js',
  '10-financial-report-timeline/02_timeline_sidebar.js', '11-land-croquis/01_croquis_survey.js',
  '11-land-croquis/02_map_edits.js', '12-files-media/01_files_media.js',
  '12-files-media/02_visual_concept.js',
  '13-visual/01_visual_concept_page.js',
  '13-visual/02_slides_progress.js',
  '13-visual/03_tenant_slide_generation.js', '14-slides-gen/01_undo.js',
  '14-slides-gen/02_element_editing.js', '14-slides-gen/03_slide_regeneration.js',
  '15-slide-edit-chat/01_render_inline_edit.js',
  '15-slide-edit-chat/02_designer_chat.js',
  '16-presentations-export/01_presentations.js',
  '16-presentations-export/02_admin_dashboard.js',
  '16-presentations-export/03_export_delivery.js',
  '16-presentations-export/04_sag_company_create.js',
  '17-admin-boot/01_training_rules.js',
  '17-admin-boot/02_users_roles.js',
  '17-admin-boot/03_training_chat_sessions.js', '18-landloom-ops.js',
  '19-notifications.js'];
const source = ['index.html',
  ...FRONTEND_JS_ORDER.map(n => 'assets/js/' + n)]
  .map(f => fs.readFileSync(path.join(__dirname, '..', f), 'utf8')).join('\n');
const helperStart = source.indexOf('    // In-session deck history only.');
const helperEnd = source.indexOf('    // End presentation undo helpers.', helperStart);
assert(helperStart >= 0 && helperEnd > helperStart);
const extract = name => {
  const match = new RegExp('^    (?:async )?function ' + name + '\\(', 'm').exec(source);
  assert(match, name);
  const end = source.indexOf('\n    }', match.index);
  return source.slice(match.index, end + 6);
};
const buttons = { presentationUndoButton: {}, presentationRedoButton: {} };
let pageActive = true;
const elements = {};
const body = { tagName: 'BODY', closest: () => null };
const context = vm.createContext({
  console, queueMicrotask, JSON, Set,
  document: {
    activeElement: body,
    getElementById(id) {
      if (id === 'tenantSlidesPage') return { classList: { contains: () => pageActive } };
      return elements[id] || buttons[id] || null;
    },
    addEventListener: () => {}
  },
  confirm: () => true
});
vm.runInContext(`
  let tenantSlidesData = [], tenantSlidePlan = null, tenantSlideGenerationCheckpoint = null;
  let tenantPresentationProvenance = null, tenantPresentationSavePromise = null;
  let tenantProjectData = {}, activeSlideIndex = 0, tenantChatSlideIndex = 0, tenantChatFocusIndexes = [];
  let isGeneratingTenantSlides = false, isRegeneratingTenantSlide = false, tenantSlidePlanRequest = null;
  let tenantDesignerChatBusy = null, slideElementDragActive = false, permitted = true;
  const slideEditSessions = {}, slideInlineEditStates = {}, slideElementEditStates = {};
  const SLIDE_EDIT_HISTORY_LIMIT = 30;
  let dirty = false, rendered = 0, numbered = 0, nativeUndoCalls = 0, nativeRedoCalls = 0;
  let tenantDesignerMessages = [], tenantCreativeImages = {};
  function hasPermission() { return permitted; }
  function setDraftDirty(value) { dirty = value; }
  function triggerAutoSaveDraft() { dirty = true; }
  function renumberTenantSlides() { numbered++; }
  function renderTenantSlides() { rendered++; }
  function selectTenantSlide(index) { activeSlideIndex = index; tenantChatSlideIndex = index; }
  function toast() {}
  function refreshSingleSlideCard() {}
  function refreshSlideEditToolbar() {}
  function slideEditFingerprint(slide) { return slide.html; }
  function renderTenantDesignerChat() {}
  function applyDesignerChatHistory() {}
  function applyDesignerChatMemory() {}
  function designerChatPersistence() { return {}; }
  function containsSlideRoot(html) { return html.includes('class="slide"'); }
`, context);
vm.runInContext(source.slice(helperStart, helperEnd), context);
for (const name of ['getSlideEditSession', 'touchSlideEditSession', 'pushSlideEditHistory',
  'endSlideEditSession', 'undoSlideEdit', 'redoSlideEdit', 'moveSlide', 'moveTenantSlide',
  'deleteSlide', 'saveSlideEdit', 'applyTenantDesignerChatResult']) {
  vm.runInContext(extract(name), context);
}
const run = code => vm.runInContext(code, context);
const json = code => JSON.parse(run(`JSON.stringify(${code})`));
const seed = () => run(`
  tenantSlidesData = ['A','B','C'].map(title => ({title, html:'<div class="slide">'+title+'</div>'}));
  tenantSlidePlan = {source:'ai', slides:[{title:'A',media:['asset']},{title:'B'},{title:'C'}]};
  tenantSlideGenerationCheckpoint = null; tenantPresentationProvenance = null;
  tenantProjectData = {unrelated:'keep'}; activeSlideIndex = 1; tenantChatSlideIndex = 2;
  tenantChatFocusIndexes = [1,3,99,-1,1]; dirty = false;
  [slideEditSessions,slideInlineEditStates,slideElementEditStates].forEach(x => Object.keys(x).forEach(k => delete x[k]));
  resetPresentationUndo();
`);
const flush = () => new Promise(resolve => queueMicrotask(resolve));
const keyEvent = (key, extra = {}) => ({ key, ctrlKey: true, target: body,
  prevented: false, preventDefault() { this.prevented = true; }, ...extra });
async function main() {
  seed();
  assert.equal(buttons.presentationUndoButton.disabled, true);
  run('deleteSlide(1)'); await flush();
  assert.deepEqual(json('tenantSlidesData.map(x=>x.title)'), ['A', 'C']);
  assert.equal(run('undoPresentationChange()'), true);
  assert.deepEqual(json('tenantSlidesData.map(x=>x.title)'), ['A', 'B', 'C']);
  assert.deepEqual(json('tenantSlidePlan.slides[0].media'), ['asset']);
  assert.deepEqual(json('tenantChatFocusIndexes'), [1, 3]);
  assert.equal(run('tenantChatSlideIndex'), 2);
  assert.equal(run('tenantProjectData.unrelated'), 'keep');
  assert.equal(run('dirty && rendered > 0 && numbered > 0'), true);
  assert.equal(run('redoPresentationChange()'), true);
  run('undoPresentationChange(); moveTenantSlide(0,2)'); await flush();
  assert.equal(run('redoPresentationChange()'), false, 'new edit discards redo');
  assert.deepEqual(json('tenantSlidesData.map(x=>x.title)'), ['B', 'C', 'A']);
  run('undoPresentationChange(); moveSlide(0,1)'); await flush();
  assert.deepEqual(json('tenantSlidesData.map(x=>x.title)'), ['B', 'A', 'C']);

  seed();
  elements.slideEditTitle = {value: 'Edited'};
  elements.slideEditHtml = {value: '<div class="slide">Manual</div>'};
  elements.slideEditModal = {remove() {}};
  run('saveSlideEdit(0)'); await flush();
  run('undoPresentationChange()');
  assert.equal(run('tenantSlidesData[0].title'), 'A');
  run('redoPresentationChange()');
  assert.equal(run('tenantSlidesData[0].title'), 'Edited');

  seed();
  run(`applyTenantDesignerChatResult({success:true,provenance:{token:'signed'},data:{
    slidesData:[{title:'AI A',html:'<div class="slide">AI A</div>'},
    {title:'AI B',html:'<div class="slide">AI B</div>'},
    {title:'AI C',html:'<div class="slide">AI C</div>'}]}},'edit')`);
  assert.equal(run('presentationUndoHistory.length'), 2, 'AI batch is one checkpoint');
  run('undoPresentationChange()');
  assert.equal(run('tenantPresentationProvenance'), null);
  run('redoPresentationChange()');
  assert.equal(run('tenantPresentationProvenance.token'), 'signed');
  run('clearPresentationUndoProvenance(); undoPresentationChange(); redoPresentationChange()');
  assert.equal(run('tenantPresentationProvenance'), null, 'saved receipt never revived');
  run(`applyTenantDesignerChatResult({success:true,data:{action:'add_slide',title:'Added',html:'<div class="slide">Added</div>'}},'add')`);
  assert.equal(run('tenantSlidesData.length'), 4);
  run('undoPresentationChange()'); assert.equal(run('tenantSlidesData.length'), 3);
  run('redoPresentationChange()'); assert.equal(run('tenantSlidesData.length'), 4);

  seed();
  run(`slideEditSessions[0]={originalHtml:tenantSlidesData[0].html,undo:[],redo:[],fp:tenantSlidesData[0].html};
    pushSlideEditHistory(0); tenantSlidesData[0].html='inline'; touchSlideEditSession(0)`);
  await flush();
  assert.equal(run('undoPresentationChange()'), false, 'active slide edit retains local undo');
  context.event = keyEvent('z', {target:{tagName:'DIV',closest:s=>s==='.ge-slide-card'?{id:'slide-card-0'}:null}});
  run('handlePresentationUndoKey(event)'); await flush();
  assert.equal(run('tenantSlidesData[0].html.includes("A")'), true);
  context.event = keyEvent('y', {target:{tagName:'DIV',closest:s=>s==='.ge-slide-card'?{id:'slide-card-0'}:null}});
  run('handlePresentationUndoKey(event)'); await flush();
  assert.equal(run('tenantSlidesData[0].html'), 'inline');
  run('endSlideEditSession(0,true)'); await flush();
  assert.equal(run('undoPresentationChange()'), true);
  assert.notEqual(run('tenantSlidesData[0].html'), 'inline', 'approval must not add a metadata-only undo step');

  seed(); run('moveSlide(0,1)'); await flush();
  for (const target of [{tagName:'INPUT'}, {tagName:'TEXTAREA'}, {tagName:'SELECT'}, {isContentEditable:true}]) {
    context.event = keyEvent('z', {target}); run('handlePresentationUndoKey(event)');
    assert.equal(context.event.prevented, false);
    assert.equal(run('presentationUndoPosition'), 1);
  }
  pageActive = false;
  context.event = keyEvent('z'); run('handlePresentationUndoKey(event)');
  assert.equal(context.event.prevented, false); pageActive = true;
  for (const flag of ['isGeneratingTenantSlides','isRegeneratingTenantSlide','tenantSlidePlanRequest',
    'tenantPresentationSavePromise','tenantDesignerChatBusy','slideElementDragActive']) {
    run(`${flag}=true; updatePresentationUndoButtons()`);
    assert.equal(run('undoPresentationChange()'), false, flag);
    assert.equal(buttons.presentationUndoButton.disabled, true);
    run(`${flag}=false`);
  }
  run('permitted=false'); assert.equal(run('undoPresentationChange()'), false); run('permitted=true');
  context.event = keyEvent('z'); run('handlePresentationUndoKey(event)'); assert.equal(context.event.prevented, true);
  context.event = keyEvent('z', {shiftKey:true}); run('handlePresentationUndoKey(event)'); assert.equal(context.event.prevented, true);
  context.event = keyEvent('z'); run('handlePresentationUndoKey(event)');
  context.event = keyEvent('y'); run('handlePresentationUndoKey(event)'); assert.equal(context.event.prevented, true);

  seed();
  run(`for(let i=0;i<50;i++){tenantSlidesData[0].title=String(i);checkpointPresentationUndo();}`);
  assert.equal(run('presentationUndoHistory.length'), run('PRESENTATION_UNDO_LIMIT'));
  run('tenantSlidesData[0].html="x".repeat(PRESENTATION_UNDO_MAX_CHARS); checkpointPresentationUndo()');
  assert.equal(run('presentationUndoHistory.length'), 1, 'byte bound trims prior decks');
  seed();
  run('beginPresentationUndoChange(); tenantSlidesData=[]; tenantSlidePlan=null; resetPresentationUndo()');
  await flush(); assert.equal(run('presentationUndoHistory.length'), 1, 'reset cancels pending checkpoint');
  assert.equal(run('undoPresentationChange()'), false);
  run('tenantSlidesData=[{title:"generated",html:"new"}]; checkpointPresentationUndo(); undoPresentationChange()');
  assert.equal(run('tenantSlidesData.length'), 0, 'generation can return to empty baseline');
  run('redoPresentationChange()'); assert.equal(run('tenantSlidesData.length'), 1);
  seed();
  run(`tenantSlideGenerationCheckpoint={active:true,nextIndex:2};
    tenantProjectData.slide_generation_checkpoint=tenantSlideGenerationCheckpoint;
    resetPresentationUndo(); tenantSlideGenerationCheckpoint={active:false,nextIndex:3};
    checkpointPresentationUndo(); undoPresentationChange()`);
  assert.equal(run('tenantSlideGenerationCheckpoint.active'), true);
  assert.equal(run('tenantProjectData.slide_generation_checkpoint.active'), true);
  run('redoPresentationChange()');
  assert.equal(run('tenantProjectData.slide_generation_checkpoint.active'), false);
  seed();
  run(`applyTenantDesignerChatResult({success:true,data:{action:'ask',response:'Which slide?'}},'edit')`);
  assert.equal(run('presentationUndoHistory.length'), 1, 'chat-only responses do not create history');
  console.log('Presentation undo harness passed: structure, batch AI, provenance, manual edits, shortcuts, guards, bounds, reset.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
