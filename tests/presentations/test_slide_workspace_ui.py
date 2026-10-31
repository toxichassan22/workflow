"""Design-page workspace UI contracts (axis 1 of docs/md/design_page.md).

The deck page used to be a flat toolbar with text-only thumbnails and a fixed
chat panel. These guards pin the approved structure: a three-zone header, real
thumbnails with hover actions and multi-select, a manual add path, a delete that
follows the slide instead of the position, a sorter, a collapsible chat panel
with a folded plan card and a send/stop toggle, and a present mode.
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / 'index.html'


def _bundle_order(kind):
    part = ROOT / 'app_parts' / '22_rules_pages' / '22f_frontend_bundles.py'
    name = 'FRONTEND_{}_ORDER'.format(kind.upper())
    tree = ast.parse(part.read_text(encoding='utf-8'))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name
                   for target in node.targets):
            continue
        return tuple(ast.literal_eval(node.value))
    return ()


def read_frontend_text():
    """The whole client source: shell + CSS + JS in bundle order."""
    parts = [INDEX.read_text(encoding='utf-8')]
    for name in _bundle_order('css'):
        parts.append((ROOT / 'assets' / 'css' / name).read_text(encoding='utf-8'))
    for name in _bundle_order('js'):
        parts.append((ROOT / 'assets' / 'js' / name).read_text(encoding='utf-8'))
    return '\n'.join(parts)


class SlidesWorkspaceHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell = INDEX.read_text(encoding='utf-8')
        cls.source = read_frontend_text()

    def test_header_answers_context_view_and_actions(self):
        self.assertIn('slide-workspace-header', self.shell)
        for view in ('edit', 'sorter', 'present'):
            self.assertIn('data-slides-view="%s"' % view, self.shell)
        self.assertIn('id="slidesHeaderTitle"', self.shell)
        self.assertIn('id="slidesHeaderCount"', self.shell)
        self.assertIn('id="slidesHeaderStatusBadge"', self.shell)
        self.assertIn('id="slidesHeaderSaveState"', self.shell)
        # The old mixed toolbar and its unexplained chip are gone.
        self.assertNotIn('slide-toolbar-chat-context', self.shell)
        self.assertNotIn('<h2>معاينة وتعديل الشرائح</h2>', self.shell)
        # Undo/redo follow the editing session, not save/export.
        header = self.shell.split('<div class="ge-topbar slide-workspace-header"', 1)[1]
        header = header.split('<!-- Undo/redo follow', 1)[0]
        self.assertNotIn('id="presentationUndoButton"', header)
        self.assertIn('id="slidesUndoRail"', self.shell)

    def test_header_reads_live_presentation_state(self):
        self.assertIn('function renderSlidesHeader()', self.source)
        self.assertIn('function setSlidesWorkspaceView(view)', self.source)
        self.assertIn("wsText('ws.save_dirty', 'تعديلات غير محفوظة')", self.source)
        self.assertIn("tenantPresentationStatus = p.status || 'draft';", self.source)


class SlidesSidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = read_frontend_text()

    def test_thumbnails_are_real_slides_rendered_lazily(self):
        self.assertIn("canvas.className = 'ge-thumb-canvas'", self.source)
        self.assertIn('function fillSlideThumbnailCanvas(canvas, slide)', self.source)
        self.assertIn('new IntersectionObserver', self.source)
        self.assertIn('function toggleTenantSidebar()', self.source)
        self.assertIn('is-collapsed', self.source)

    def test_add_and_delete_animate_without_repainting_the_rail(self):
        body = self.source.split('function renderTenantSlidesSidebar(force) {', 1)[1]
        body = body.split('function toggleTenantSidebar', 1)[0]
        self.assertIn('tenantSidebarThumbCache', body)
        self.assertIn('animateTenantSidebarRebuild(sidebar, previousRects, removedThumbs)', body)
        self.assertIn("canvas.dataset.filled = '1'", body)
        self.assertIn('function animateTenantSidebarRebuild(sidebar, previous, removed)', self.source)
        self.assertIn('function sidebarSpawnGhost(host, node, rect)', self.source)
        self.assertIn('thumb.animate(', self.source)
        self.assertIn('ge-thumb-ghost', self.source)


    def test_actions_are_hover_only_and_cover_every_slide_operation(self):
        self.assertIn('function slideThumbActionsHtml(index, slide)', self.source)
        self.assertIn('.ge-thumb:hover .ge-thumb-actions', self.source)
        for fn in ('moveTenantSlide(', 'deleteSlide(', 'regenerateTenantSlide(',
                   'removeTenantSlideBackground(', 'duplicateSlideAt(',
                   'startRenameTenantSlide('):
            self.assertIn(fn, self.source)

    def test_multi_select_and_bulk_actions(self):
        self.assertIn('function handleThumbClick(event, index)', self.source)
        self.assertIn('event.ctrlKey || event.metaKey', self.source)
        self.assertIn('event.shiftKey', self.source)
        self.assertIn('function deleteSelectedSlides()', self.source)
        self.assertIn('function duplicateSelectedSlides()', self.source)
        self.assertIn("wsText('ws.selected_count', 'المحدد: {n}', { n: tenantSlideSelectionIds.length })", self.source)

    def test_manual_add_without_ai(self):
        self.assertIn('function insertBlankSlideAt(index)', self.source)
        self.assertIn('function blankSlideTemplate(title)', self.source)
        self.assertIn('ge-thumb-add', self.source)

    def test_delete_follows_the_slide_instead_of_the_position(self):
        self.assertIn('function deleteSlide(index)', self.source)
        body = self.source.split('function deleteSlide(index) {', 1)[1]
        body = body.split('\n    async function commitTenantPresentation', 1)[0]
        self.assertIn('index < wasActive', body)
        self.assertIn('selectTenantSlide(activeSlideIndex, true)', body)

    def test_add_and_delete_animate_the_stage_list(self):
        self.assertIn('const tenantStageHtmlCache = new Map();', self.source)
        self.assertIn('function animateTenantDeckChange(wrap, previous, removed)', self.source)
        self.assertIn('animateTenantDeckChange(wrap, previousCards, removedCards)', self.source)
        self.assertIn('ge-slide-card-ghost', self.source)
        body = self.source.split('function renderTenantSlides() {', 1)[1]
        body = body.split('function tenantSlideHasBackground', 1)[0]
        self.assertIn('tenantStageHtmlCache.get(String(s.id))', body)
        self.assertIn('tenantStageHtmlCache.set(String(s.id), stage.innerHTML);', body)
        self.assertIn('containers.filter(entry => !entry.cached).forEach(renderTenantSlideCard)', body)


    def test_render_keeps_the_open_slide_under_the_viewport(self):
        body = self.source.split('function renderTenantSlides() {', 1)[1]
        body = body.split('function tenantSlideHasBackground', 1)[0]
        self.assertIn('anchorOffset', body)
        self.assertIn('anchorId', body)

    def test_scroll_spy_listens_to_the_real_scroller(self):
        self.assertIn("const mainWrap = document.getElementById('tenantSlidesMain');", self.source)
        self.assertNotIn("getElementById('tenantSlidesMainWrap')", self.source)


class SlidesSorterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = read_frontend_text()

    def test_sorter_reorders_and_inserts_between_slides(self):
        self.assertIn('function renderTenantSlidesSorter()', self.source)
        self.assertIn('ondragstart', self.source)
        self.assertIn('ondrop', self.source)
        self.assertIn('ge-sorter-insert', self.source)
        # The + hangs on the inline-start edge, so the gap it marks is before
        # its card in RTL and after it in LTR. insert + 1 added one too far.
        self.assertIn('function sorterInsertIndex(index, isRtl)', self.source)
        self.assertIn('sorterInsertIndex(current, sorterIsRtl(grid))', self.source)
        self.assertIn('openSlideInsertMenu(insert, at)', self.source)
        self.assertNotIn('openSlideInsertMenu(insert, index + 1)', self.source)

    def test_sorter_deletes_and_opens_the_clicked_slide(self):
        self.assertIn('ge-sorter-delete', self.source)
        self.assertIn('deleteSlide(current)', self.source)
        self.assertIn('function sorterOpenSlideInEditor(index)', self.source)
        self.assertIn('sorterOpenSlideInEditor(current)', self.source)


class DesignerChatPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell = INDEX.read_text(encoding='utf-8')
        cls.source = read_frontend_text()

    def test_panel_collapses_resizes_and_manages_conversations(self):
        self.assertIn('function toggleTenantChatPanel()', self.source)
        self.assertIn('function bindTenantChatResize()', self.source)
        self.assertIn('function startNewTenantDesignerConversation()', self.source)
        self.assertIn('function deleteTenantDesignerConversation()', self.source)
        self.assertIn('id="tenantChatResize"', self.shell)
        self.assertIn('ge-chat-reopen', self.shell)

    def test_composer_has_attach_send_and_stop(self):
        self.assertIn('id="tenantChatStopButton"', self.shell)
        self.assertIn('function stopTenantDesignerChat()', self.source)
        self.assertIn('function renderTenantComposerState()', self.source)
        self.assertIn('renderTenantComposerState', self.source)
        self.assertIn('function renderTenantChatAttachment()', self.source)
        self.assertIn('tenant-chat-attachment-item', self.source)

    def test_chat_controls_use_the_owner_authorized_icons(self):
        # Owner request (2026-10-31): paperclip, send arrow, stop and a chevron
        # replace the attach/send/stop/طي words on this page.
        for icon in ('attach', 'send', 'stop', 'chevron'):
            self.assertIn('data-ws-icon="%s"' % icon, self.shell)
        self.assertIn('function wsIcon(name)', self.source)
        self.assertIn('function hydrateWorkspaceIcons(root)', self.source)
        self.assertIn('hydrateWorkspaceIcons(document)', self.source)
        self.assertIn('WS_ICON_PATHS', self.source)

    def test_plan_card_folds_with_progress(self):
        self.assertIn('function toggleDesignerChecklistCard()', self.source)
        self.assertIn('tenant-designer-checklist-progress-fill', self.source)
        self.assertIn('tenantDesignerChecklistCollapsed = true', self.source)
        # The card lives in the message flow, not as a block between messages and composer.
        messages = self.shell.split('id="tenantChatMessages"', 1)[1].split('id="tenantChatComposer"', 1)[0]
        self.assertIn('id="tenantDesignerChecklist"', messages)


class SlidesNotesAndMenusTests(unittest.TestCase):
    """Notes are written inline and reach every viewer; dropdown menus stay on
    screen."""

    @classmethod
    def setUpClass(cls):
        cls.shell = INDEX.read_text(encoding='utf-8')
        cls.source = read_frontend_text()

    def test_notes_are_edited_inline_with_autosave(self):
        self.assertIn('function openTenantSlideNotesEditor(index)', self.source)
        self.assertIn('function openTenantSlideEditor(index, field)', self.source)
        self.assertIn('function commitTenantSlideEditor()', self.source)
        self.assertIn('setTimeout(commitTenantSlideEditor, 450)', self.source)
        self.assertIn("openTenantSlideNotesEditor(' + index + ')", self.source)
        self.assertNotIn("prompt(wsText('ws.notes_prompt'", self.source)
        self.assertNotIn("prompt(wsText('ws.group_prompt'", self.source)
        self.assertIn('slide-editor-popover', self.source)

    def test_notes_reach_present_mode_and_the_shared_link(self):
        self.assertIn('id="tenantPresentNotes"', self.shell)
        self.assertIn('function renderTenantPresentNotes(slide)', self.source)
        self.assertIn('renderTenantPresentNotes(slide);', self.source)
        self.assertIn('function toggleTenantPresentNotes()', self.source)
        shares = (ROOT / 'app_parts' / '11_presentations' / '13d_presentation_shares.py').read_text(encoding='utf-8')
        self.assertIn("'notes': str(slide.get('notes') or '').strip(),", shares)
        self.assertIn('id="shareNotes"', shares)
        self.assertIn('slides[index].notes', shares)

    def test_menus_stay_inside_the_viewport(self):
        self.assertIn('function clampTenantDropdownMenu(drop)', self.source)
        self.assertIn('function resetTenantDropdownPosition(drop)', self.source)
        clamp = self.source.split('function clampTenantDropdownMenu(drop)', 1)[1].split('function toggleTenantDropdown', 1)[0]
        self.assertIn('getBoundingClientRect()', clamp)
        self.assertIn('window.innerWidth', clamp)
        self.assertIn('translateX(', clamp)
        self.assertIn('clampTenantDropdownMenu(drop);', self.source)


class SlidesPresentModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell = INDEX.read_text(encoding='utf-8')
        cls.source = read_frontend_text()

    def test_present_mode_is_fullscreen_read_only_with_controls(self):
        self.assertIn('id="tenantPresentOverlay"', self.shell)
        self.assertIn('function openTenantPresentation(startIndex)', self.source)
        self.assertIn('function closeTenantPresentation()', self.source)
        self.assertIn('function handleTenantPresentationKey(event)', self.source)
        self.assertIn('function stepTenantPresentation(delta)', self.source)
        self.assertIn('requestFullscreen', self.source)
        self.assertIn('controls-hidden', self.source)

    def test_presentation_restarts_from_the_first_visible_slide(self):
        # Walking the deck end to end used to have no way back: the only control
        # was «السابق», so a viewer had to press it for every page to reach the cover.
        self.assertIn('id="presentRestartButton" onclick="restartTenantPresentation()"',
                      self.shell)
        restart = self.source.split('function restartTenantPresentation()', 1)[1]
        restart = restart.split('function stepTenantPresentation(delta)', 1)[0]
        self.assertIn('if (!tenantPresentActive) return;', restart)
        # Hidden slides are skipped by the visible index list, never by position.
        self.assertIn('visibleSlideIndexes()[0]', restart)
        self.assertIn('renderTenantPresentSlide()', restart)
        self.assertIn('showTenantPresentControls()', restart)
        self.assertIn("if (event.key === 'Home') { event.preventDefault(); restartTenantPresentation(); }",
                      self.source)

    def test_present_stage_shares_the_canvas_slide_normalization(self):
        # The app-wide «table { min-width: 850px }» and heading margins are form
        # rules; they reached the presented slide only, cutting wide tables off at
        # the left edge while the canvas and the PDF showed them whole.
        flat = re.sub(r'\s+', ' ', self.source)
        self.assertIn('.tenant-slide-stage .slide table, '
                      '#tenantPresentOverlay .present-stage .slide table { min-width: 0; }',
                      flat)
        self.assertIn('.tenant-slide-stage .slide *, '
                      '#tenantPresentOverlay .present-stage .slide * { margin: 0; padding: 0; '
                      'box-sizing: border-box; }',
                      flat)
        present = flat.split('#tenantPresentOverlay .present-stage .slide {', 1)[1].split('}', 1)[0]
        self.assertIn('line-height: normal', present)



class SlidesCanvasEditingTests(unittest.TestCase):
    """Axis 2 of docs/md/design_page.md: per-type tools, the inspector, zoom,
    snapping, multi-select and the shortcut contract."""

    @classmethod
    def setUpClass(cls):
        cls.shell = INDEX.read_text(encoding='utf-8')
        cls.source = read_frontend_text()

    def test_bundle_loads_the_canvas_layer(self):
        js = _bundle_order('js')
        for name in ('15b-slide-canvas/01_zoom_inspector.js',
                     '15b-slide-canvas/02_snap_selection.js',
                     '15b-slide-canvas/03_text_shortcuts.js'):
            self.assertIn(name, js)
        self.assertIn('base/10_slide_canvas.css', _bundle_order('css'))

    def test_zoom_is_a_canvas_control_with_a_ratio_safe_scale(self):
        self.assertIn('function applyTenantCanvasZoom(scale, silent)', self.source)
        self.assertIn('function fitTenantCanvasZoom()', self.source)
        self.assertIn('function fullscreenTenantCanvas()', self.source)
        self.assertIn('id="slidesZoomReadout"', self.source)
        self.assertIn('TENANT_CANVAS_ZOOM_MIN = 0.5', self.source)
        self.assertIn('TENANT_CANVAS_ZOOM_MAX = 2', self.source)
        zoom = self.source.split('function applyTenantCanvasZoom(scale, silent)', 1)[1]
        zoom = zoom.split('function fitTenantCanvasZoom', 1)[0]
        self.assertIn('autoFitSlideContent(stage)', zoom)
        # A hardcoded 16:9 stage squeezed a 4:3 deck; the zoom is a ratio-safe scale.
        self.assertNotIn('1280 * next', zoom)
        fit = self.source.split('function autoFitSlideContent(stage)', 1)[1]
        fit = fit.split('function slideParseCssColor', 1)[0]
        self.assertIn('tenantCanvasZoom', fit)
        self.assertIn('canvas.height / canvas.width', fit)

    def test_each_element_kind_gets_its_own_tools(self):
        self.assertIn('function inspectorTargetKind(el)', self.source)
        self.assertIn('function slideToolbarSelectionKind(index)', self.source)
        toolbar = self.source.split('function slideEditToolbarHTML(index)', 1)[1]
        toolbar = toolbar.split('function normalizeHexColor', 1)[0]
        for tab in ('common', 'text', 'image', 'shape', 'colors', 'add', 'watermark'):
            self.assertIn("data-slide-edit-tab", toolbar)
        self.assertIn("slideEditToolbarAvailableTabs(selectionKind)", toolbar)
        # The session never leaves the bar, whichever tab is open.
        self.assertIn('slide-edit-session-rail', toolbar)
        self.assertIn('data-slide-edit-act="commit"', toolbar)
        self.assertIn('data-slide-edit-act="cancel"', toolbar)
        self.assertIn('return sessionRail + tabbar', toolbar)

    def test_inspector_carries_exact_values_per_kind(self):
        self.assertIn('function renderSlideInspector(index)', self.source)
        for field in ('inspectorX', 'inspectorY', 'inspectorW', 'inspectorH'):
            self.assertIn(field, self.source)
        for fn in ('moveSlideSelectionTo(', 'resizeSlideSelection(',
                   'alignSlideSelection(', 'distributeSlideSelection(',
                   'setSlideSelectionFontSize(', 'setSlideSelectionLineHeight(',
                   'setSlideSelectionLetterSpacing(', 'setSlideSelectionImageFit(',
                   'setSlideSelectionBorderRadius(', 'setSlideSelectionRotation('):
            self.assertIn(fn, self.source)
        for section in ("canvasText('ca.text', 'النص')", "canvasText('ca.image', 'الصورة')",
                        "canvasText('ca.shape', 'الشكل')"):
            self.assertIn(section, self.source)

    def test_multi_select_drag_snapping_and_grouping(self):
        for fn in ('addSlideElementToSelection(stage, index, target, path)',
                   'selectAllSlideElements(index)',
                   'commitSlideDragEntries(stage, index, pairs, dx, dy)',
                   'snapSlideMoveDelta(stage, target, dx, dy)',
                   'groupSelectedSlideElements(index)',
                   'ungroupSelectedSlideElements(index)'):
            self.assertIn(fn, self.source)
        self.assertIn('session.multi', self.source)
        self.assertIn('slide-element-multiselected', self.source)
        self.assertIn('.slide-snap-guide', self.source)
        drag = self.source.split('function handleSlidePointerDown(event)', 1)[1]
        drag = drag.split("target.addEventListener('pointermove', handlePointerMove);", 1)[0]
        self.assertIn('addSlideElementToSelection', drag)
        self.assertIn('snapSlideMoveDelta', drag)
        self.assertIn('commitSlideDragEntries', drag)

    def test_clipboard_duplicate_delete_and_shortcut_contract(self):
        for fn in ('copySelectedSlideElements(', 'pasteSlideElements(',
                   'duplicateSelectedSlideElements(', 'deleteSelectedSlideElements('):
            self.assertIn(fn, self.source)
        shortcuts = self.source.split('function handleSlidesWorkspaceShortcuts(event)', 1)[1]
        shortcuts = shortcuts.split('document.addEventListener', 1)[0]
        for key in ("key === 's'", "key === 'd'", "key === 'c'", "key === 'v'", "key === 'a'"):
            self.assertIn(key, shortcuts)
        self.assertIn('ArrowLeft', shortcuts)
        self.assertIn("event.key === 'Delete'", shortcuts)
        self.assertIn("event.key === 'Escape'", shortcuts)

    def test_text_undo_joins_the_slide_history(self):
        for token in ('function undoSlideText(el)', 'function redoSlideText(el)',
                      'slideTextEditableFrom',
                      'function persistPresentationUndoHistory()',
                      'function restorePersistedUndoHistory()',
                      "'wf.undo.v1.'", 'PRESENTATION_UNDO_PERSIST_LIMIT'):
            self.assertIn(token, self.source)

    def test_canvas_labels_are_translated_in_both_dictionaries(self):
        ar = (ROOT / 'assets' / 'i18n' / '01a_dict_ar_extra.js').read_text(encoding='utf-8')
        en = (ROOT / 'assets' / 'i18n' / '01b_dict_en_extra.js').read_text(encoding='utf-8')
        for key in ('ca.inspector', 'ca.zoom_fit', 'ca.image', 'ca.shape', 'ca.text',
                    'ca.more', 'ca.actions'):
            self.assertIn('"%s":' % key, ar)
            self.assertIn('"%s":' % key, en)


if __name__ == '__main__':
    unittest.main()


class SlidesCanvasEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = read_frontend_text()

    def test_zoom_fit_and_fullscreen_belong_to_the_canvas(self):
        self.assertIn('function applyTenantCanvasZoom(scale, silent)', self.source)
        self.assertIn('function fitTenantCanvasZoom()', self.source)
        self.assertIn('fullscreenTenantCanvas()', self.source)
        self.assertIn('slides-canvas-zoom', self.source)
        self.assertIn("localStorage.setItem('wf.slidesCanvasZoom'", self.source)

    def test_inspector_changes_with_the_selected_type(self):
        self.assertIn('function renderSlideInspector(index)', self.source)
        for section in ("canvasText('ca.text'", "canvasText('ca.image'", "canvasText('ca.shape'"):
            self.assertIn(section, self.source)
        # Numeric geometry and alignment are exact values, not drag-only.
        for fn in ('moveSlideSelectionTo(', 'resizeSlideSelection(', 'alignSlideSelection(',
                   'distributeSlideSelection('):
            self.assertIn(fn, self.source)
        self.assertIn('function setSlideSelectionRotation(', self.source)
        self.assertIn('session.aspectLock', self.source)

    def test_elements_snap_and_multi_select_moves_as_one(self):
        self.assertIn('function snapSlideMoveDelta(stage, target, dx, dy)', self.source)
        self.assertIn('slide-snap-guide', self.source)
        self.assertIn('function addSlideElementToSelection(', self.source)
        self.assertIn('function commitSlideDragEntries(', self.source)
        drag = self.source.split("stage.addEventListener('pointerdown', function handleSlidePointerDown", 1)[1]
        drag = drag.split("stage.addEventListener('click'", 1)[0]
        self.assertIn('snapSlideMoveDelta', drag)
        self.assertIn('commitSlideDragEntries', drag)

    def test_group_copy_paste_and_delete_cover_the_selected_set(self):
        for fn in ('groupSelectedSlideElements(', 'ungroupSelectedSlideElements(',
                   'copySelectedSlideElements(', 'pasteSlideElements(',
                   'duplicateSelectedSlideElements(', 'deleteSelectedSlideElements(',
                   'selectAllSlideElements('):
            self.assertIn('function ' + fn, self.source)

    def test_shortcut_contract_is_wired(self):
        for token in ("key === 's'", "key === 'd'", "key === 'c'", "key === 'v'",
                      "key === 'a'", "event.key === 'Delete'", "event.key === 'Escape'",
                      "moveSlideSelectionBy(index, dx, dy)"):
            self.assertIn(token, self.source)
        self.assertIn('function handleSlidesWorkspaceShortcuts(event)', self.source)

    def test_text_undo_works_inside_the_editable_text(self):
        self.assertIn('function undoSlideText(el)', self.source)
        self.assertIn('function redoSlideText(el)', self.source)
        self.assertIn('slideTextEditableFrom(event.target)', self.source)

    def test_undo_history_survives_a_refresh_with_a_cap(self):
        self.assertIn('function persistPresentationUndoHistory()', self.source)
        self.assertIn('function restorePersistedUndoHistory()', self.source)
        self.assertIn('PRESENTATION_UNDO_PERSIST_LIMIT', self.source)
        self.assertIn('PRESENTATION_UNDO_PERSIST_BYTES', self.source)
        self.assertIn('restorePersistedUndoHistory()', self.source)

    def test_deck_undo_stays_available_while_an_edit_session_is_open(self):
        body = self.source.split('function presentationUndoAvailable()', 1)[1]
        body = body.split('function updatePresentationUndoButtons', 1)[0]
        self.assertNotIn('Object.keys(slideEditSessions).length', body)
        self.assertIn('sessionHasSteps', body)
        key_handler = self.source.split('function handlePresentationUndoKey(event)', 1)[1]
        key_handler = key_handler.split('document.addEventListener', 1)[0]
        self.assertIn('session && (session.undo.length || session.redo.length)', key_handler)

    def test_edit_toolbar_never_widens_the_slide_card(self):
        """A toolbar wider than the slide used to stretch the card, leaving the
        stage on one side and an empty white half beside it."""
        self.assertIn('function observeTenantSlideStage(stage, card)', self.source)
        self.assertIn('new ResizeObserver', self.source)
        self.assertIn("card.style.width = width + 'px'", self.source)
        self.assertIn('observeTenantSlideStage(stage, container)', self.source)
        css = (ROOT / 'assets' / 'css' / 'base' / '09_slide_workspace.css').read_text(encoding='utf-8')
        self.assertIn('#tenantSlidesPage .ge-slide-edit-controls', css)
        self.assertIn('max-width: 100%', css)

    def test_slide_images_are_uploaded_as_project_files(self):
        body = self.source.split('async function addSlideImageFromDevice(index, file)', 1)[1]
        body = body.split('function onSlideEditableFocus', 1)[0]
        self.assertIn("form.append('fileType', 'slide_image')", self.source)
        self.assertIn('publishProjectFileImageUrl(response.file.id)', self.source)
        self.assertNotIn('readAsDataURL(file)', body)


class PresentationShareUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell = INDEX.read_text(encoding='utf-8')
        cls.source = read_frontend_text()

    def test_share_entry_point_lives_in_the_header_menu(self):
        self.assertIn('data-i18n="sh.menu"', self.shell)
        self.assertIn('openPresentationShareDialog()', self.shell)
        self.assertIn('function openPresentationShareDialog()', self.source)

    def test_share_dialog_offers_password_expiry_copy_and_revoke(self):
        for token in ('sharePasswordInput', 'shareExpirySelect', 'shareCreateButton',
                      'refreshPresentationShareList', 'copyPresentationShareUrl',
                      'revokePresentationShare'):
            self.assertIn(token, self.source)
        for choice in ('1d', '7d', '30d', 'never'):
            self.assertIn("value=\"%s\"" % choice, self.source)

    def test_share_calls_the_owner_and_public_endpoints(self):
        self.assertIn("'/shares'", self.source)
        self.assertIn("'/revoke'", self.source)
        self.assertIn("'/api/presentations/' + encodeURIComponent(tenantPresentationId) + '/shares'", self.source)


class SlidesAuthoringTests(unittest.TestCase):
    """PowerPoint-style manual authoring: the insert menu, per-type tools,
    tables, crop, deck-wide replace and the hidden-slide contract."""

    @classmethod
    def setUpClass(cls):
        cls.shell = INDEX.read_text(encoding='utf-8')
        cls.source = read_frontend_text()

    def test_bundle_loads_the_authoring_layer(self):
        js = _bundle_order('js')
        for name in ('14-slides-gen/01a_slide_toolbar.js',
                     '15b-slide-canvas/04_authoring.js',
                     '15b-slide-canvas/05_canvas_tools.js',
                     '15b-slide-canvas/06_deck_tools.js'):
            self.assertIn(name, js)

    def test_insert_menu_offers_five_on_brand_structures(self):
        self.assertIn('function openSlideInsertMenu(anchor, index)', self.source)
        for structure in ('blank', 'title', 'title_text', 'text_image', 'table'):
            self.assertIn("['%s'," % structure, self.source)
        template = self.source.split('function structuredSlideHtml(structure, title, colors)', 1)[1]
        template = template.split('/* Replaces match text', 1)[0]
        self.assertIn('##LOGO##', template)
        self.assertIn('data-slide-footer="1"', template)
        self.assertIn('data-slide-counter="1"', template)
        self.assertIn('data-manual-slide="1"', template)
        self.assertIn('manual: true', self.source)
        # The deck font is injected, so an authored slide never pins a family.
        self.assertNotIn('font-family', template)
        self.assertIn('openSlideInsertMenu(', self.shell + self.source)

    def test_toolbar_shows_slide_and_table_tools_by_selection(self):
        toolbar = self.source.split('function slideEditToolbarAvailableTabs(selectionKind)', 1)[1]
        toolbar = toolbar.split('function slideEditToolbarTabLabels', 1)[0]
        self.assertIn("return ['add', 'slide']", toolbar)
        self.assertIn("selectionKind === 'table') return ['table', 'common']", self.source)
        self.assertIn("typeof insertSlideShape === 'function'", self.source)
        self.assertIn("typeof insertSlideTableFromPanel === 'function'", self.source)

    def test_text_formatting_contract(self):
        for fn in ('toggleSlideSelectionTextStyle(', 'toggleSlideSelectionList(',
                   'clearSlideSelectionFormatting(', 'fitSlideSelectionText(',
                   'adjustSlideSelectionLineHeight(', 'applySlideInlineColorToSelection('):
            self.assertIn('function ' + fn, self.source)
        self.assertIn('data-slide-edit-color="highlight"', self.source)
        self.assertIn('slideTextSelectionInside', self.source)
        self.assertIn('slideInlineStyleSanitizer', self.source)

    def test_image_crop_moves_the_picture_inside_its_frame(self):
        self.assertIn('function toggleSlideImageCrop(index)', self.source)
        self.assertIn('function startSlideImageCropDrag(stage, index, target, event)', self.source)
        self.assertIn('session.cropMode', self.source)
        self.assertIn('objectPosition', self.source)
        drag = self.source.split("stage.addEventListener('pointerdown', function handleSlidePointerDown", 1)[1]
        drag = drag.split("stage.addEventListener('click'", 1)[0]
        self.assertIn('startSlideImageCropDrag', drag)
        self.assertIn('.slide-crop-target', self.source)

    def test_tables_insert_and_edit_like_powerpoint(self):
        for fn in ('insertSlideTable(', 'mutateSlideTableSelection(', 'mutateSlideTableCell(',
                   'addSlideTableRow(', 'removeSlideTableRow(', 'addSlideTableColumn(',
                   'removeSlideTableColumn(', 'toggleSlideTableHeader(', 'bindSlideTableEditing('):
            self.assertIn('function ' + fn, self.source)
        self.assertIn("[data-slide-table] td, [data-slide-table] th", self.source)
        self.assertIn('data-slide-table', self.source)
        self.assertIn("card.addEventListener('dblclick'", self.source)
        # A cell edits on double-click; a single click selects the table.
        inline = self.source.split('function enableSlideInlineEditing(stage, index)', 1)[1]
        inline = inline.split('function slidePathIgnores', 1)[0]
        self.assertIn('markSlideTablesForPointerEditing(slide);', inline)
        self.assertIn("el.closest('[data-slide-table] td, [data-slide-table] th')", inline)
        self.assertIn('bindSlideTableEditing(stage, index)', inline)
        self.assertIn('function slideTablePointerBox(table)', self.source)
        self.assertIn("rect.width <= tableRect.width * 1.5 + 24", self.source)
        # A generated table may be shaped by its fixed, overflow-hidden frame.
        context = self.source.split('function slideTableContext(index)', 1)[1]
        context = context.split('function slideTableActiveCell', 1)[0]
        self.assertIn("rawWrapper.tagName === 'TABLE' ? rawWrapper", context)
        bind = self.source.split('function bindSlideTableEditing(stage, index)', 1)[1]
        bind = bind.split('function beginSlideTableCellEdit', 1)[0]
        self.assertIn('lastCellTap', bind)
        self.assertIn('beginSlideTableCellEdit(stage, index, cell)', bind)

    def test_slide_background_and_visibility(self):
        for fn in ('setSlideBackgroundColor(', 'clearSlideBackground(',
                   'openSlideBackgroundPicker(', 'toggleSlideHidden('):
            self.assertIn('function ' + fn, self.source)
        self.assertIn('data-slide-edit-slide-bg', self.source)
        self.assertIn('visibleSlideIndexes()', self.source)
        step = self.source.split('function stepTenantPresentation(delta)', 1)[1]
        step = step.split('function handleTenantPresentationKey', 1)[0]
        self.assertIn('tenantSlidesData[next].hidden', step)
        self.assertIn('ge-thumb-hidden', self.source)

    def test_deck_wide_find_and_replace(self):
        self.assertIn('id="deckFindInput"', self.shell)
        self.assertIn('id="deckReplaceInput"', self.shell)
        self.assertIn('runDeckFindReplace()', self.shell)
        self.assertIn('function runDeckFindReplace()', self.source)
        self.assertIn('function deckReplaceInSlideHtml(html, find, replace)', self.source)
        run_replace = self.source.split('function runDeckFindReplace()', 1)[1]
        run_replace = run_replace.split('function toggleSlideHiddenFromDeckTools', 1)[0]
        # A live text edit commits on blur; replace must wait for that commit.
        self.assertIn('active.blur()', run_replace)
        self.assertLess(run_replace.index('active.blur()'), run_replace.index('let total = 0'))
        # Replacement touches text nodes only — never attributes or style blocks.
        replace = self.source.split('function deckReplaceInSlideHtml(html, find, replace)', 1)[1]
        replace = replace.split('/* AUTHORING_PURE_END */', 1)[0]
        self.assertIn('replace(/>([^<]*)</g', replace)
        self.assertIn('(style|script)', replace)

    def test_manual_slides_survive_a_full_regeneration(self):
        self.assertIn('function preserveManualSlidesForRegeneration()', self.source)
        self.assertIn('function restoreManualSlidesAfterRegeneration(preserved, options)', self.source)
        generation = self.source.split('async function generateTenantSlides(options = {})', 1)[1]
        self.assertIn('preserveManualSlidesForRegeneration()', generation)
        self.assertIn('restorePreservedManualSlides(', generation)
        self.assertIn('manualSlidesRestored', generation)

    def test_inspector_is_an_inline_split_panel(self):
        self.assertIn('function slideInlineInspectorHost(index)', self.source)
        self.assertIn('.slide-inline-inspector', self.source)
        self.assertNotIn("inspector.id = 'slideInspector'", self.source)
        self.assertIn("canvasText('ca.position', 'الموضع')", self.source)
        self.assertIn("canvasText('ca.align', 'محاذاة')", self.source)
        self.assertIn("canvasText('ca.horizontal', 'أفقي')", self.source)
        self.assertIn("canvasText('ca.vertical', 'رأسي')", self.source)
        self.assertIn('slideShadowSelect(', self.source)
        self.assertIn('function setSlideSelectionShadow(', self.source)
        self.assertIn('function toggleSlideInlineInspector(btn)', self.source)
        self.assertIn('is-collapsed', self.source)

    def test_inspector_stays_compact_and_folds_the_rest_behind_chips(self):
        render = self.source.split('function renderSlideInspector(index)', 1)[1]
        render = render.split('function closeSlideInspector', 1)[0]
        # Default surface: one geometry row and one row for the selected type.
        self.assertIn('slide-inspector-rowline', render)
        self.assertIn("canvasText('ca.position', 'الموضع')", render)
        for chip in ("slideInspectorChip(canvasText('ca.align', 'محاذاة'), 'align')",
                     "slideInspectorChip(canvasText('ca.more', 'مزيد'), 'more')",
                     "slideInspectorChip(canvasText('ca.actions', 'إجراءات'), 'actions')"):
            self.assertIn(chip, render)
        # Everything past the default rows is emitted only when its chip is open.
        for group in ('align', 'more', 'actions'):
            self.assertIn("slideInspectorGroup === '" + group + "'", render)
        default_part = render.split("slideInspectorGroup === 'more'", 1)[0]
        self.assertNotIn("canvasText('ca.opacity'", default_part)
        self.assertNotIn("canvasText('ca.rotation'", default_part)
        more = render.split("slideInspectorGroup === 'more'", 1)[1]
        more = more.split("slideInspectorGroup === 'actions'", 1)[0]
        for token in ("canvasText('ca.opacity'", "canvasText('ca.rotation'", "canvasText('ca.layer'"):
            self.assertIn(token, more)
        actions = render.split("slideInspectorGroup === 'actions'", 1)[1]
        self.assertIn('duplicateSelectedSlideElements(', actions)
        self.assertIn('deleteSelectedSlideElements(', actions)
        self.assertIn('function toggleSlideInspectorGroup(group)', self.source)
        self.assertIn('let slideInspectorGroup', self.source)
        css = (ROOT / 'assets' / 'css' / 'base' / '10_slide_canvas.css').read_text(encoding='utf-8')
        for token in ('.slide-inspector-rowline', '.slide-inspector-field',
                      '.slide-inspector-chip', '.slide-inspector-group'):
            self.assertIn(token, css)
        # The global input rule sets min-height:42px; the compact fields must
        # override it or every row grows back to a full-height input.
        field_css = css.split('#tenantSlidesPage .slide-inspector-field input[type="number"]', 1)[1]
        field_css = field_css.split('}', 1)[0]
        self.assertIn('min-height: 0', field_css)
        self.assertIn('height: 20px', field_css)

    def test_selecting_an_element_keeps_the_canvas_under_the_pointer(self):
        self.assertIn('function holdSlideStagePosition(stage, anchorTop)', self.source)
        select = self.source.split('function selectSlideElement(stage, index, target, path)', 1)[1]
        select = select.split('function restoreSlideEditSelection', 1)[0]
        self.assertIn('holdSlideStagePosition(stage, anchorTop)', select)
        self.assertIn("container.onclick = () => { if (activeSlideIndex !== i) selectTenantSlide(i); }",
                      self.source)
        self.assertIn("kind === 'table' && host.previousElementSibling !== stage", self.source)

    def test_resize_stays_inside_the_slide_and_edge_handles_stay_clickable(self):
        self.assertIn('const maxW = !touchW ? slideW :', self.source)
        self.assertIn('slideW - base.left', self.source)
        self.assertIn('Math.max(0, Math.min(pos[0], 1280 - HS))', self.source)
        self.assertIn('Math.max(0, Math.min(pos[1], 720 - HS))', self.source)

    def test_selection_geometry_uses_the_painted_scale(self):
        self.assertIn('function slideRenderedScale(stage)', self.source)
        # Every coordinate/handle path measures the painted slide, not only the
        # stage zoom variable.
        self.assertGreaterEqual(self.source.count('slideRenderedScale(stage)'), 8)
        self.assertIn('slideElementOpacityProduct', self.source)
        self.assertIn('applySlideElementEffectiveOpacity', self.source)
        self.assertIn('function slideElementOpacityPct(el)', self.source)

    def test_marquee_selection_and_group_naming(self):
        self.assertIn('function startSlideMarqueeSelection(stage, index, event)', self.source)
        self.assertIn('slide-marquee', self.source)
        self.assertIn('marqueeAt', self.source)
        self.assertIn('startSlideMarqueeSelection(stage, index, event)', self.source)
        self.assertIn("groupedSlide.querySelector('[data-slide-group]')", self.source)
        self.assertIn('selectSlideElement(groupedStage, index, grouped, groupedPath)', self.source)
        self.assertIn('touchSlideEditSession(index);', self.source)
        ar = (ROOT / 'assets' / 'i18n' / '01a_dict_ar_extra.js').read_text(encoding='utf-8')
        en = (ROOT / 'assets' / 'i18n' / '01b_dict_en_extra.js').read_text(encoding='utf-8')
        self.assertIn('"ca.group": "مجموعة"', ar)
        self.assertIn('"ca.group": "Group"', en)
        self.assertIn('"ca.ungroup": "فك المجموعة"', ar)

    def test_shadow_can_be_removed_and_reports_its_level(self):
        self.assertIn('function slideElementShadowLevel(el, property)', self.source)
        self.assertIn("el.style.boxShadow = 'none'", self.source)
        self.assertIn("el.style.textShadow = 'none'", self.source)
        ar = (ROOT / 'assets' / 'i18n' / '01a_dict_ar_extra.js').read_text(encoding='utf-8')
        en = (ROOT / 'assets' / 'i18n' / '01b_dict_en_extra.js').read_text(encoding='utf-8')
        for key in ('ca.shadow_none', 'ca.shadow_soft', 'ca.shadow_strong'):
            self.assertIn('"%s":' % key, ar)
            self.assertIn('"%s":' % key, en)

    def test_authoring_labels_carry_both_languages(self):
        ar = (ROOT / 'assets' / 'i18n' / '01a_dict_ar_extra.js').read_text(encoding='utf-8')
        en = (ROOT / 'assets' / 'i18n' / '01b_dict_en_extra.js').read_text(encoding='utf-8')
        for key in ('tb.table', 'tb.slide', 'ca.crop', 'ca.clear_format',
                    'ca.add_row', 'ws.deck_tools', 'ws.structure_table',
                    'deck.replace_all', 'slide.table_added'):
            self.assertIn('"%s":' % key, ar)
            self.assertIn('"%s":' % key, en)


class SlidesWorkspaceDensityTests(unittest.TestCase):
    """The designer page is a working surface: the header, both rails and the
    inspector are sized so the deck wins the room. Shrinking the rail without the
    thumbnail scale (or the reverse) puts the 16:9 stills outside their frame, so
    the pair is asserted as one number."""

    @classmethod
    def setUpClass(cls):
        base = ROOT / 'assets' / 'css' / 'base'
        cls.workspace_css = (base / '09_slide_workspace.css').read_text(encoding='utf-8')
        cls.canvas_css = (base / '10_slide_canvas.css').read_text(encoding='utf-8')
        cls.chat_css = (base / '11_slide_chat_present.css').read_text(encoding='utf-8')
        cls.preview_css = (base / '01_preview_chat.css').read_text(encoding='utf-8')
        cls.space_js = (ROOT / 'assets' / 'js' / '15a-slide-workspace'
                        / '01_workspace.js').read_text(encoding='utf-8')
        cls.source = read_frontend_text()

    @staticmethod
    def _rule(css, selector):
        block = css.split(selector, 1)[1]
        return block.split('}', 1)[0]

    def test_header_stays_a_compact_band(self):
        rule = self._rule(self.workspace_css, '#tenantSlidesPage .slide-workspace-header {')
        self.assertIn('padding: 6px 11px', rule)
        self.assertIn('gap: 10px', rule)
        title = self._rule(self.workspace_css, '#tenantSlidesPage .slide-header-title {')
        self.assertIn('font-size: 15px', title)
        action = self._rule(self.workspace_css, '#tenantSlidesPage .slide-header-actions .btn {')
        self.assertIn('padding: 5px 11px', action)
        self.assertIn('font-size: 11px', action)

    def test_thumbnail_rail_width_and_scale_agree(self):
        rail = self._rule(self.workspace_css, '#tenantSlidesPage .ge-sidebar {')
        self.assertIn('width: 176px', rail)
        # Content-box width would add the padding back and overflow the row.
        self.assertIn('box-sizing: border-box', rail)
        card = self._rule(self.workspace_css, '#tenantSlidesPage .ge-thumb {')
        self.assertIn('padding: 4px', card)
        canvas = self._rule(self.workspace_css, '#tenantSlidesPage .ge-thumb-canvas {')
        match = re.search(r'var\(--thumb-scale, ([0-9.]+)\)', canvas)
        self.assertIsNotNone(match, canvas)
        scale = float(match.group(1))
        # 176 rail − 12 rail padding − 8 card padding − 4 card border.
        frame = 176 - 12 - 8 - 4
        painted = 1280 * scale
        self.assertLessEqual(painted, frame)
        self.assertGreaterEqual(painted, frame - 2)

    def test_chat_panel_defaults_to_the_compact_rail(self):
        panel = self._rule(self.chat_css, '#tenantSlidesPage .ge-right-panel {')
        self.assertIn('var(--chat-width, 300px)', panel)
        self.assertIn('min-width: 240px', panel)
        self.assertIn('let width = 300;', self.space_js)
        self.assertIn('Math.max(240, Math.min(560, width))', self.space_js)
        # The old default was never written unless the panel was dragged, so a
        # stored 340 is that default and must not keep the wide rail.
        self.assertIn('if (width === 340) width = 300;', self.space_js)
        self.assertIn('Math.max(240, Math.min(560, startWidth', self.space_js)

    def test_canvas_owns_the_space_between_the_rails(self):
        main = self._rule(self.preview_css, '.tenant-app.preview-active .ge-main {')
        self.assertIn('padding: 10px 6px 64px', main)
        self.assertIn('gap: 16px', main)
        zoom = self._rule(self.canvas_css, '#tenantSlidesPage .slides-canvas-zoom {')
        match = re.search(r'right: ([0-9]+)px', zoom)
        self.assertIsNotNone(match, zoom)
        # The zoom bar floats beside the rail; a wider offset hides it under it.
        self.assertGreater(int(match.group(1)), 176)

    def test_inspector_rows_leave_the_slide_in_view(self):
        field_css = self._rule(
            self.canvas_css, '#tenantSlidesPage .slide-inspector-field input[type="number"],\n'
            '#tenantSlidesPage .slide-inspector-field input[type="text"] {')
        self.assertIn('height: 20px', field_css)
        self.assertIn('min-height: 0', field_css)
        row = self._rule(self.canvas_css, '#tenantSlidesPage .slide-inspector-rowline {')
        self.assertIn('min-height: 20px', row)
        toolbar = self._rule(self.workspace_css, '#tenantSlidesPage .ge-slide-edit-controls button {')
        self.assertIn('padding: 2px 7px', toolbar)
        self.assertIn('font-size: 10px', toolbar)

    def test_card_and_rails_measure_in_layout_pixels(self):
        # The page renders under a root zoom, so a painted rect is 15% smaller
        # than the layout box it describes. Writing that rect back into a style
        # length made the slide card narrower than its own slide.
        observer = self.source.split('function ensureTenantStageWidthObserver()', 1)[1]
        observer = observer.split('function observeTenantSlideStage', 1)[0]
        self.assertIn('stage.offsetWidth', observer)
        self.assertNotIn('getBoundingClientRect().width', observer)
        resize = self.source.split('function bindTenantChatResize()', 1)[1]
        resize = resize.split('function resetTenantDesignerConversationState', 1)[0]
        self.assertNotIn('getBoundingClientRect().width', resize)
        self.assertIn('String(Math.round(panel.offsetWidth))', resize)
        # Fixed overlays built from a captured rect convert it to layout first.
        self.assertIn('function wfRootZoom()', self.source)
        ghost = self.source.split('function sidebarSpawnGhost(host, node, rect)', 1)[1]
        ghost = ghost.split('function animateTenantSidebarRebuild', 1)[0]
        self.assertIn('rect.left / zoom', ghost)
        menu = self.source.split('function openSlideInsertMenu(anchor, index)', 1)[1]
        menu = menu.split('function selectSlideElementBySelector', 1)[0]
        self.assertIn('const zoom = typeof wfRootZoom', menu)
        self.assertIn("menu.style.position = 'fixed';", menu)
        self.assertIn("menu.style.visibility = 'hidden';", menu)
        sorter = (ROOT / 'assets' / 'js' / '15a-slide-workspace'
                  / '02_sorter.js').read_text(encoding='utf-8')
        ghost = sorter.split('function sorterSpawnGhost', 1)[1]
        ghost = ghost.split('function sorterReconcileGrid', 1)[0]
        self.assertIn('(rect.width / zoom)', ghost)
        # FLIP deltas come from painted rects but drive layout transforms.
        self.assertGreaterEqual(sorter.count('/ zoom * 10) / 10'), 2)
        deck_flip = self.source.split('function animateTenantDeckChange', 1)[1]
        deck_flip = deck_flip.split('function renderTenantSlides()', 1)[0]
        self.assertIn('/ zoom * 10) / 10', deck_flip)
