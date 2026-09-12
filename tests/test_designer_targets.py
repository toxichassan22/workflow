"""Target selection stays bounded and original numbering survives earlier actions."""
import unittest
import designer_chat_targets as targets


class DesignerTargetTests(unittest.TestCase):
    def test_invalid_numbers_never_fall_back_to_current(self):
        for number in [0, -1, 99, True, 1.5, '1.5', None]:
            with self.subTest(number=number), self.assertRaises(targets.TargetError):
                targets.resolve_indexes({'target': 'indexes', 'indexes': [number]}, 4, 2)

    def test_missing_indexes_fail(self):
        for params in [{'target': 'indexes'}, {'target': 'indexes', 'indexes': []}]:
            with self.assertRaises(targets.TargetError):
                targets.resolve_indexes(params, 4, 2)

    def test_reference_slide_is_not_an_edit_target(self):
        self.assertEqual(targets.explicit_slide_numbers('عدل الشريحة 2 زي الشريحة 5'), [2])
        self.assertEqual(targets.explicit_slide_numbers('عدّل الشرائح ٢، ٤ و ٦'), [2, 4, 6])
        self.assertEqual(targets.explicit_slide_numbers('غير الشرائح 2 إلى 4'), [2, 3, 4])
        self.assertIsNone(targets.explicit_slide_numbers('حجم الخط 24'))

    def test_explicit_slide_numbers_spelling_dialects_and_corrections(self):
        self.assertEqual(targets.explicit_slide_numbers('احذف عمود الحاله من شريحه رقم 21'), [21])
        self.assertEqual(targets.explicit_slide_numbers('احذف عمود الحالة من الشريحة 21'), [21])
        self.assertEqual(targets.explicit_slide_numbers('شيل صف 3 من شريحه 21'), [21])
        self.assertEqual(targets.explicit_slide_numbers('احذف عمود الحاله من سلايد 21'), [21])
        self.assertEqual(targets.explicit_slide_numbers('احذف عمود الحاله من سلايده 21'), [21])
        self.assertEqual(targets.explicit_slide_numbers('احذف عمود الحاله من صفحه 21'), [21])
        self.assertEqual(targets.explicit_slide_numbers('احذف عمود الحاله من الصفحه 21'), [21])
        self.assertEqual(targets.explicit_slide_numbers('احذف عمود الحاله من رقم 21'), [21])
        self.assertEqual(targets.explicit_slide_numbers('احذف عمود الحاله في رقم 21'), [21])
        self.assertEqual(targets.explicit_slide_numbers('21'), [21])
        self.assertEqual(targets.explicit_slide_numbers('رقم 21'), [21])
        self.assertEqual(targets.explicit_slide_numbers('شريحه 21'), [21])
        self.assertEqual(targets.explicit_slide_numbers('21 مش 1'), [21])
        self.assertEqual(targets.explicit_slide_numbers('انا بقولك 21 مش 1'), [21])
        self.assertEqual(targets.explicit_slide_numbers('شريحة 21 بدل 1'), [21])
        self.assertIsNone(targets.explicit_slide_numbers('مش الشريحة 1'))

    def test_partial_or_expanded_selection_is_rejected(self):
        slides = [{} for _ in range(4)]
        for indexes in [[1], [1, 2, 3], [2, 3]]:
            with self.assertRaises(targets.TargetError):
                targets.prepare_actions([{'tool': 'edit_slides', 'params': {'target': 'indexes', 'indexes': indexes}}],
                                        {'indexes': [1, 2]}, 'عدل الألوان', slides, 0)

    def test_current_ui_scope_overrides_prior_focus(self):
        with self.assertRaises(targets.TargetError):
            targets.prepare_actions([{'tool': 'edit_slides', 'params': {'target': 'indexes', 'indexes': [1]}}],
                                    {'scope': 'current', 'focusIndexes': [1]}, 'عدل اللون', [{}, {}, {}], 2)

    def test_original_indexes_remap_after_delete(self):
        original = [{'id': str(i)} for i in range(4)]
        actions = targets.prepare_actions([{'tool': 'edit_slides', 'params': {'indexes': [3]}}], {}, 'عدل اللون', original, 0)
        mapped = targets.remap_action(actions[0], original, original[1:])
        self.assertEqual(mapped['params']['indexes'], [2])
        with self.assertRaises(targets.TargetError):
            targets.remap_action(actions[0], original, [original[0], original[3]])


if __name__ == '__main__':
    unittest.main()
