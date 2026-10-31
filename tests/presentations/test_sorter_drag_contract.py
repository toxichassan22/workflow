"""Sorter drag contracts (design page, سورتر view).

Dragging a card shows a live landing gap and then reorders the existing grid
nodes — never rebuilds them, because a rebuild flashes every thumbnail away.
The placement math and the whole drag/drop path run against a DOM shim in
tests/presentations/test_sorter_drag.js; these guards pin the wiring.
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
    parts = [INDEX.read_text(encoding='utf-8')]
    for name in _bundle_order('css'):
        parts.append((ROOT / 'assets' / 'css' / name).read_text(encoding='utf-8'))
    for name in _bundle_order('js'):
        parts.append((ROOT / 'assets' / 'js' / name).read_text(encoding='utf-8'))
    return '\n'.join(parts)


class SorterDragContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = read_frontend_text()

    def test_drag_previews_a_gap_and_returns_home(self):
        for token in ('function sorterDropBoundary(', 'function sorterDropFinalIndex(',
                      'function sorterFlipCells(', 'function sorterApplyDrop(',
                      'ge-sorter-placeholder', 'is-dragging-source',
                      'tenantSorterLastLeaveAt', 'tenantSorterSuppressRender'):
            self.assertIn(token, self.source)

    def test_drop_reorders_the_nodes_instead_of_rebuilding_the_grid(self):
        drop = self.source.split('function sorterHandleGridDrop(grid, event)', 1)[1]
        drop = drop.split('function renderTenantSlidesSorter', 1)[0]
        self.assertNotIn('renderTenantSlidesSorter(', drop)
        self.assertIn('sorterApplyDrop(grid, slot)', drop)
        apply_body = self.source.split('function sorterApplyDrop(grid, slot)', 1)[1]
        apply_body = apply_body.split('function sorterHandleGridDrop', 1)[0]
        self.assertIn('grid.insertBefore(sourceCell, slotNode)', apply_body)
        self.assertIn('tenantSorterSuppressRender = true;', apply_body)
        self.assertIn('moveTenantSlide(from, finalIndex);', apply_body)
        self.assertIn('if (tenantSorterSuppressRender) return;', self.source)

    def test_placeholder_and_source_styles_exist(self):
        css = (ROOT / 'assets' / 'css' / 'base' / '09_slide_workspace.css').read_text(encoding='utf-8')
        self.assertIn('.ge-sorter-placeholder', css)
        self.assertIn('.ge-sorter-cell.is-dragging-source', css)

    def test_insert_lands_on_the_gap_the_plus_marks(self):
        pure = self.source.split('/* SORTER_PURE_BEGIN */', 1)[1].split('/* SORTER_PURE_END */', 1)[0]
        self.assertIn('function sorterInsertIndex(index, isRtl)', pure)
        self.assertIn('return isRtl ? base : base + 1;', pure)
        build = self.source.split('function sorterBuildCell(grid, slide, index)', 1)[1]
        build = build.split('function sorterSyncCellContent', 1)[0]
        self.assertIn('sorterInsertIndex(current, sorterIsRtl(grid))', build)
        self.assertIn('openSlideInsertMenu(insert, at)', build)
        self.assertNotIn('openSlideInsertMenu(insert, index + 1)', self.source)

    def test_add_and_delete_reconcile_the_live_grid(self):
        render = self.source.split('function renderTenantSlidesSorter()', 1)[1]
        render = render.split('document.addEventListener(\'wf:lang\'', 1)[0]
        self.assertIn('sorterReconcileGrid(liveGrid)', render)
        # The live grid is reconciled before any destructive rebuild.
        self.assertLess(render.index('sorterReconcileGrid(liveGrid)'), render.index("box.innerHTML = '';"))
        reconcile = self.source.split('function sorterReconcileGrid(grid)', 1)[1]
        reconcile = reconcile.split('function renderTenantSlidesSorter()', 1)[0]
        self.assertIn('sorterSyncCellContent(cell, slide, index)', reconcile)
        self.assertIn('sorterBuildCell(grid, slide, index)', reconcile)
        self.assertIn('sorterSpawnGhost(grid, cell', reconcile)
        self.assertIn('sorterAnimateEnter(cell)', reconcile)
        self.assertIn('grid.insertBefore(cell, addCell || null)', reconcile)
        build = self.source.split('function renderTenantSlidesSorter()', 1)[1]
        self.assertIn('const cell = sorterBuildCell(grid, slide, index);', build)
        self.assertIn('openSlideInsertMenu(addButton, tenantSlidesData.length)', build)
        self.assertNotIn('onclick="openSlideInsertMenu(this,', build)

    def test_cards_delete_themselves_and_open_the_clicked_slide(self):
        label = self.source.split('function sorterRenderCellLabel(cell, slide, index)', 1)[1]
        label = label.split('function sorterBuildCell', 1)[0]
        self.assertIn("remove.className = 'ge-sorter-delete'", label)
        self.assertIn('deleteSlide(current)', label)
        build = self.source.split('function sorterBuildCell(grid, slide, index)', 1)[1]
        build = build.split('function sorterSyncCellContent', 1)[0]
        self.assertIn('sorterOpenSlideInEditor(current)', build)
        dbl = self.source.split('function sorterOpenSlideInEditor(index)', 1)[1]
        dbl = dbl.split('function sorterHighlightActive', 1)[0]
        self.assertIn('setSlidesWorkspaceView(\'edit\');', dbl)
        self.assertIn('selectTenantSlide(index, true);', dbl)
        self.assertIn('requestAnimationFrame', dbl)
        css = (ROOT / 'assets' / 'css' / 'base' / '09_slide_workspace.css').read_text(encoding='utf-8')
        self.assertIn('.ge-sorter-delete', css)


if __name__ == '__main__':
    unittest.main()
