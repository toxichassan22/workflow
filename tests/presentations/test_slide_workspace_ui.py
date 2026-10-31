"""Design-page workspace UI contracts (axis 1 of docs/md/design_page.md).

The deck page used to be a flat toolbar with text-only thumbnails and a fixed
chat panel. These guards pin the approved structure: a three-zone header, real
thumbnails with hover actions and multi-select, a manual add path, a delete that
follows the slide instead of the position, a sorter, a collapsible chat panel
with a folded plan card and a send/stop toggle, and a present mode.
"""

import ast
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
        self.assertIn("insertBlankSlideAt(' + tenantSlidesData.length", self.source)


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

    def test_plan_card_folds_with_progress(self):
        self.assertIn('function toggleDesignerChecklistCard()', self.source)
        self.assertIn('tenant-designer-checklist-progress-fill', self.source)
        self.assertIn('tenantDesignerChecklistCollapsed = true', self.source)
        # The card lives in the message flow, not as a block between messages and composer.
        messages = self.shell.split('id="tenantChatMessages"', 1)[1].split('id="tenantChatComposer"', 1)[0]
        self.assertIn('id="tenantDesignerChecklist"', messages)


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
        for kind in ('text', 'image', 'shape'):
            self.assertIn('data-slide-edit-group="%s"' % kind, toolbar)
        self.assertIn("selectionKind === 'image'", toolbar)
        self.assertIn("selectionKind === 'shape'", toolbar)
        self.assertIn("(!selectionKind || selectionKind === 'text')", toolbar)
        # The flat always-on group is gone: text tools are conditional now.
        self.assertIn('const textTools =', toolbar)

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
        for key in ('ca.inspector', 'ca.zoom_fit', 'ca.image', 'ca.shape', 'ca.text'):
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
