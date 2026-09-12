"""Offline, source-preserving table deletion regressions (no app/model imports)."""
import unittest

import designer_chat_reliability as reliability


PREFIX = '<div class="slide" dir="rtl"><style>.keep{color:#123456}</style>\n<h2>عنوان &amp; ثابت</h2><img src="/uploads/logo.png" data-x="a > b">\n'
SUFFIX = '\n<aside class="keep">ملاحظة لا تتغير 1,234.5</aside><footer data-slide-counter>03 — 12</footer></div>'
HEADER = '<tr class="head"><th>البند</th><th>السعر</th><th>المساحة</th></tr>'
ROWS = [
    '<tr id="one"><th scope="row">الأرض</th><td data-x="a > b">100</td><td>10</td></tr>',
    '<tr id="two"><th scope="row"><b>البناء</b></th><td>200</td><td>20</td></tr>',
    '<tr id="three"><th scope="row">التشغيل</th><td>300</td><td>30</td></tr>',
]
FOOT = '<tfoot><tr><td>الإجمالي</td><td>600</td><td>60</td></tr></tfoot>'


def table(rows=ROWS, header=HEADER, attrs=' id="costs"', footer=FOOT):
    return '<table' + attrs + '><caption>التكاليف</caption><thead>' + header + '</thead><tbody>\n' + '\n<!-- retained -->\n'.join(rows) + '\n</tbody>' + footer + '</table>'


def slide(value=None):
    return PREFIX + (table() if value is None else value) + SUFFIX


class TableDeletionSafetyTests(unittest.TestCase):
    def assert_applied(self, source, command, expected):
        result = reliability.apply_table_delete_request(source, command)
        self.assertTrue(result['handled'], result)
        self.assertTrue(result['changed'], result)
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(result['html'], expected)
        self.assertEqual(result['reason'], '')
        # Every changed byte must be accounted for by a removed original span.
        rebuilt = source
        spans = sorted(result['changes'], key=lambda item: item['start'], reverse=True)
        for change in spans:
            self.assertEqual(source[change['start']:change['end']], change['removedHtml'])
            rebuilt = rebuilt[:change['start']] + rebuilt[change['end']:]
        self.assertEqual(rebuilt, expected)
        return result

    def assert_blocked(self, source, command, reason=None):
        result = reliability.apply_table_delete_request(source, command)
        self.assertTrue(result['handled'], result)
        self.assertFalse(result['changed'], result)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['html'], source)
        self.assertEqual(result['changes'], [])
        self.assertTrue(result['reason'])
        if reason:
            self.assertEqual(result['reason'], reason)
        return result

    def test_arabic_and_english_numbered_rows_preserve_every_other_byte(self):
        source = slide()
        for command in ('احذف الصف الثاني', 'احذف الصف رقم ٢ من الشريحة ٩',
                        'امسح السطر ۲', 'شيل الصف 2', 'أزل الصف الثاني',
                        'اِحْذِف الصّف الثّاني', 'delete row 2', 'remove row second',
                        'احذف الصف الثاني من الجدول', 'احذف الصف 2 فقط'):
            with self.subTest(command=command):
                self.assert_applied(source, command, source.replace(ROWS[1], ''))

    def test_last_row_and_last_column(self):
        source = slide()
        for command in ('احذف آخر صف', 'احذف الصف الأخير', 'delete last row'):
            with self.subTest(command=command):
                self.assert_applied(source, command, source.replace(ROWS[2], ''))
        expected = source
        for cell in ('<th>المساحة</th>', '<td>10</td>', '<td>20</td>', '<td>30</td>', '<td>60</td>'):
            expected = expected.replace(cell, '')
        for command in ('احذف العمود الأخير', 'remove last column', 'شيل العامود ٣'):
            with self.subTest(command=command):
                self.assert_applied(source, command, expected)

    def test_named_rows_and_columns_do_not_rewrite_other_content(self):
        source = slide()
        for command in ('احذف صف البناء', 'احذف الصف باسم «البناء»', 'delete row "البناء"'):
            with self.subTest(command=command):
                self.assert_applied(source, command, source.replace(ROWS[1], ''))
        expected = source
        for cell in ('<th>السعر</th>', '<td data-x="a > b">100</td>', '<td>200</td>', '<td>300</td>', '<td>600</td>'):
            expected = expected.replace(cell, '')
        for command in ('شيل عمود السعر', 'احذف العمود «السعر» من الشريحة 4', 'delete column "السعر"'):
            with self.subTest(command=command):
                self.assert_applied(source, command, expected)

    def test_polite_phrases_dialects_and_unit_labels_apply_surgically(self):
        source = slide()
        expected_row = source.replace(ROWS[1], '')
        for command in (
            'احذف صف البناء لو سمحت',
            'شيل صف البناء بعد اذنك',
            'ممكن تشيل صف البناء',
            'شيل الصف بتاع البناء',
            'احذف صف البناء لو تكرمت',
            'شيل صف البناء من فضلك',
        ):
            with self.subTest(command=command):
                self.assert_applied(source, command, expected_row)

        expected_col = source
        for cell in ('<th>السعر</th>', '<td data-x="a > b">100</td>', '<td>200</td>', '<td>300</td>', '<td>600</td>'):
            expected_col = expected_col.replace(cell, '')
        for command in (
            'شيل عمود السعر لو سمحت',
            'ممكن تشيل عمود السعر',
            'شيل العمود بتاع السعر',
            'شيل العمود اللي اسمه السعر',
            'احذف عمود السعر من فضلك',
            'شيل العمود حق السعر',
        ):
            with self.subTest(command=command):
                self.assert_applied(source, command, expected_col)

        # ة vs ه spelling flexibility:
        expected_area = source
        for cell in ('<th>المساحة</th>', '<td>10</td>', '<td>20</td>', '<td>30</td>', '<td>60</td>'):
            expected_area = expected_area.replace(cell, '')
        self.assert_applied(source, 'شيل عمود المساحه', expected_area)

        # Unit stripping in header:
        source_with_units = source.replace('<th>المساحة</th>', '<th>المساحة (م²)</th>')
        expected_units = expected_area.replace('<th>المساحة</th>', '')
        self.assert_applied(source_with_units, 'احذف عمود المساحة', expected_units)

    def test_multiple_numbered_rows_use_original_positions_atomically(self):
        source = slide()
        expected = source.replace(ROWS[0], '').replace(ROWS[2], '')
        for command in ('احذف الصفوف ١ و٣', 'delete rows 1, 3', 'احذف الصفوف الأول والثالث'):
            with self.subTest(command=command):
                self.assert_applied(source, command, expected)
        self.assert_blocked(source, 'delete rows 1, 99', 'row_number_out_of_range')

    def test_multiple_named_rows_and_columns(self):
        source = slide()
        self.assert_applied(source, 'احذف الصفوف «الأرض» و«التشغيل»', source.replace(ROWS[0], '').replace(ROWS[2], ''))
        expected = source
        for cell in ('<th>السعر</th>', '<th>المساحة</th>', '<td data-x="a > b">100</td>',
                     '<td>200</td>', '<td>300</td>', '<td>600</td>', '<td>10</td>', '<td>20</td>', '<td>30</td>', '<td>60</td>'):
            expected = expected.replace(cell, '')
        self.assert_applied(source, 'احذف الأعمدة «السعر» و«المساحة»', expected)

    def test_duplicate_target_numbers_are_deduplicated(self):
        source = slide()
        self.assert_applied(source, 'delete rows 2, 2', source.replace(ROWS[1], ''))

    def test_slide_number_never_supplies_missing_row_target(self):
        source = slide()
        for command in ('احذف الصف من الشريحة رقم ٢', 'احذف الصف في الشريحة الأولى',
                        'احذف العمود في الشريحة الأخيرة', 'delete row from slide 2'):
            with self.subTest(command=command):
                self.assert_blocked(source, command, 'missing_table_target')

    def test_ordinal_in_label_does_not_become_row_position(self):
        row = '<tr><td>المرحلة الأولى</td><td>500</td><td>40</td></tr>'
        source = slide(table([ROWS[0], row, ROWS[2]]))
        self.assert_applied(source, 'احذف الصف «المرحلة الأولى»', source.replace(row, ''))
        self.assert_applied(source, 'احذف الصف المرحلة الأولى', source.replace(row, ''))

    def test_numbered_tables_are_explicit_not_largest(self):
        first = table([ROWS[0], ROWS[1]], attrs=' id="small"')
        second = table(attrs=' id="large"')
        source = slide(first + '<p>فاصل</p>' + second)
        self.assert_blocked(source, 'احذف الصف 2', 'ambiguous_table')
        expected = slide(first.replace(ROWS[1], '') + '<p>فاصل</p>' + second)
        self.assert_applied(source, 'احذف الصف الثاني من الجدول الأول', expected)
        self.assert_blocked(source, 'احذف الصف 2 من الجدول 9', 'table_not_found')

    def test_table_caption_and_id_disambiguate(self):
        first = table(attrs=' id="costs"')
        second = table(attrs=' id="income"').replace('التكاليف', 'الإيرادات')
        source = slide(first + second)
        expected = slide(first + second.replace(ROWS[1], ''))
        for command in ('احذف الصف الثاني من جدول الإيرادات', 'احذف الصف 2 من الجدول «income»'):
            with self.subTest(command=command):
                self.assert_applied(source, command, expected)

    def test_duplicate_table_names_are_ambiguous(self):
        self.assert_blocked(slide(table() + table()), 'احذف الصف 2 من جدول التكاليف', 'ambiguous_table')

    def test_unique_name_can_select_one_of_multiple_tables(self):
        first = table()
        row = '<tr><td>عنصر فريد</td><td>4</td><td>5</td></tr>'
        second = table([ROWS[0], row, ROWS[2]])
        source = slide(first + second)
        self.assert_applied(source, 'احذف صف «عنصر فريد»', slide(first + second.replace(row, '')))
        self.assert_blocked(source, 'احذف صف «الأرض»', 'ambiguous_table_target')

    def test_named_targets_cannot_silently_span_multiple_tables(self):
        one = '<tr><td>فريد أ</td><td>1</td><td>2</td></tr>'
        two = '<tr><td>فريد ب</td><td>3</td><td>4</td></tr>'
        source = slide(table([one, ROWS[0]]) + table([two, ROWS[0]]))
        self.assert_blocked(source, 'احذف الصفوف «فريد أ» و«فريد ب»', 'ambiguous_table')

    def test_duplicate_rows_and_duplicate_column_labels_fail_safe(self):
        self.assert_blocked(slide(table([ROWS[1], ROWS[1], ROWS[2]])), 'احذف صف البناء', 'ambiguous_table_target')
        source = slide(table(header=HEADER.replace('المساحة', 'السعر')))
        self.assert_blocked(source, 'احذف عمود السعر', 'ambiguous_table_target')

    def test_similar_names_are_not_fuzzy_matched(self):
        source = slide(table(header=HEADER.replace('السعر', 'سعر البيع').replace('المساحة', 'سعر الإيجار')))
        self.assert_blocked(source, 'احذف عمود سعر', 'column_name_not_found')
        self.assert_blocked(slide(), 'احذف صف بناء', 'row_name_not_found')

    def test_contains_row_phrase_requires_unique_word_bounded_match(self):
        row = '<tr><td>مرحلة البناء النهائية</td><td>4</td><td>5</td></tr>'
        source = slide(table([ROWS[0], row, ROWS[2]]))
        self.assert_applied(source, 'احذف الصف اللي فيه «البناء»', source.replace(row, ''))
        self.assert_blocked(source, 'احذف الصف اللي فيه «بناء»', 'row_name_not_found')

    def test_empty_header_never_matches_any_name(self):
        source = slide(table(header=HEADER.replace('السعر', '')))
        self.assert_blocked(source, 'احذف عمود مجهول', 'column_name_not_found')

    def test_data_is_not_guessed_to_be_a_column_header(self):
        source = slide('<table><tbody>' + ''.join(ROWS) + '</tbody></table>')
        self.assert_blocked(source, 'احذف عمود البناء', 'column_name_not_found')
        self.assert_applied(source, 'delete row 1', source.replace(ROWS[0], ''))

    def test_implicit_header_in_tbody_remains_byte_exact(self):
        source = slide('<table><tbody>\n' + HEADER + '<!-- head preserved -->' + '\n'.join(ROWS) + '</tbody></table>')
        self.assert_applied(source, 'delete row 1', source.replace(ROWS[0], ''))

    def test_direct_rows_keep_header_and_footer(self):
        source = slide('<table>' + HEADER + '\n'.join(ROWS) + FOOT + '</table>')
        self.assert_applied(source, 'delete row last', source.replace(ROWS[2], ''))

    def test_multiple_tbodies_keep_groups_and_comments(self):
        source = slide('<table><thead>' + HEADER + '</thead><tbody>' + ROWS[0] + '</tbody>\n<!-- between -->\n<tbody>' + ROWS[1] + ROWS[2] + '</tbody>' + FOOT + '</table>')
        self.assert_applied(source, 'delete row 2', source.replace(ROWS[1], ''))

    def test_row_headers_are_data_not_column_headers(self):
        source = slide('<table><tbody>' + ''.join(ROWS) + '</tbody></table>')
        self.assert_applied(source, 'delete row 1', source.replace(ROWS[0], ''))

    def test_multirow_header_column_resolution_is_positional(self):
        header2 = '<tr><th>الاسم</th><th>ريال</th><th>متر</th></tr>'
        source = slide(table(header=HEADER + header2))
        expected = source
        for cell in ('<th>السعر</th>', '<th>ريال</th>', '<td data-x="a > b">100</td>', '<td>200</td>', '<td>300</td>', '<td>600</td>'):
            expected = expected.replace(cell, '')
        self.assert_applied(source, 'احذف عمود السعر', expected)

    def test_rowspan_in_a_different_row_blocks_deletion(self):
        source = slide(table([ROWS[0].replace('<td ', '<td rowspan="2" ', 1), ROWS[1], ROWS[2]]))
        self.assert_blocked(source, 'delete row 2', 'merged_cells_unsupported')
        self.assert_blocked(source, 'delete column 2', 'merged_cells_unsupported')

    def test_merged_header_footer_and_invalid_spans_fail_safe(self):
        for attrs in ('colspan="2"', 'rowspan="0"', 'rowspan', 'colspan="banana"', 'colspan="-1"'):
            source = slide(table(header=HEADER.replace('<th>', '<th ' + attrs + '>', 1)))
            with self.subTest(attrs=attrs):
                self.assert_blocked(source, 'delete row 2', 'merged_cells_unsupported')
        source = slide(table(footer=FOOT.replace('<td>', '<td colspan="2">', 1)))
        self.assert_blocked(source, 'delete column 2', 'merged_cells_unsupported')

    def test_unit_spans_are_not_merges(self):
        source = slide().replace('<td>200</td>', '<td colspan="1" rowspan="1">200</td>')
        self.assert_applied(source, 'delete row 2', source.replace(ROWS[1].replace('<td>200</td>', '<td colspan="1" rowspan="1">200</td>'), ''))

    def test_nested_tables_are_not_flattened_or_partially_removed(self):
        nested = '<table><tr><td>داخل</td></tr></table>'
        source = slide(table([ROWS[0], ROWS[1].replace('<b>البناء</b>', nested), ROWS[2]]))
        self.assert_blocked(source, 'delete row 1 from table 1', 'nested_table_unsupported')
        self.assert_blocked(source, 'احذف صف «داخل»', 'nested_table_unsupported')

    def test_malformed_table_is_never_repaired_by_deletion(self):
        for body in (
            '<tr><td>أ</td><td>ب</td><tr><td>ج</td><td>د</td></tr>',
            '<tr><td>أ<td>ب</td></tr><tr><td>ج</td><td>د</td></tr>',
            '<tr><td><b>أ</td><td>ب</td></tr><tr><td>ج</td><td>د</td></tr>',
            '<td>أ</td><tr><td>ب</td></tr>',
            '<tr></tr><tr><td>أ</td></tr>',
            '<div>فاصل</div><tr><td>أ</td></tr>',
            'نص خارج الصف<tr><td>أ</td></tr>',
        ):
            with self.subTest(body=body):
                self.assert_blocked(slide('<table>' + body + '</table>'), 'delete row 1', 'malformed_table')
        self.assert_blocked(slide('<table>' + ''.join(ROWS)), 'delete row 1', 'malformed_table')

    def test_ragged_columns_and_colgroup_fail_safe(self):
        source = slide(table([ROWS[0], ROWS[1].replace('<td>20</td>', ''), ROWS[2]]))
        self.assert_blocked(source, 'delete column 2', 'non_rectangular_table')
        source = slide(table().replace('<caption>', '<colgroup><col><col span="2"></colgroup><caption>', 1))
        self.assert_blocked(source, 'delete column 2', 'column_layout_unsupported')

    def test_width_only_colgroup_deletes_matching_col_element(self):
        body = ('<table id="costs"><colgroup><col span="1" style="width:50%"><col style="width:30%"><col style="width:20%"></colgroup>'
                '<caption>التكاليف</caption><thead>' + HEADER + '</thead><tbody>\n'
                + '\n<!-- retained -->\n'.join(ROWS) + '\n</tbody>' + FOOT + '</table>')
        source = slide(body)
        expected = source
        for cell in ('<th>السعر</th>', '<td data-x="a > b">100</td>', '<td>200</td>',
                     '<td>300</td>', '<td>600</td>', '<col style="width:30%">'):
            expected = expected.replace(cell, '')
        self.assert_applied(source, 'احذف عمود السعر', expected)

    def test_spanned_or_mismatched_colgroup_stays_blocked(self):
        two_col = ('<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody>'
                   '<tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></tbody></table>')
        self.assert_blocked(slide(two_col.replace('<table>', '<table><colgroup span="2"></colgroup>', 1)),
                            'delete column 1', 'column_layout_unsupported')
        self.assert_blocked(slide(two_col.replace('<table>', '<table><colgroup><col><col><col></colgroup>', 1)),
                            'delete column 1', 'column_layout_unsupported')

    def test_empty_table_guard_is_atomic_for_single_and_multiple_targets(self):
        self.assert_blocked(slide(table([ROWS[0]])), 'delete row 1', 'would_empty_table')
        self.assert_blocked(slide(), 'delete rows 1, 2, 3', 'would_empty_table')
        self.assert_blocked(slide(), 'delete columns 1, 2, 3', 'would_empty_table')
        self.assert_blocked(slide('<table><tr><td>أ</td></tr><tr><td>ب</td></tr></table>'), 'delete column 1', 'would_empty_table')
        self.assert_blocked(slide(), 'احذف الجدول بالكامل', 'ambiguous_table_request')

    def test_escaped_text_matches_visible_label_not_markup(self):
        row = '<tr><td><span>أ &amp; ب &lt;ج&gt;</span></td><td>2</td><td>3</td></tr>'
        source = slide(table([ROWS[0], row, ROWS[2]]))
        self.assert_applied(source, 'احذف صف «أ & ب <ج>»', source.replace(row, ''))
        self.assert_blocked(source, 'احذف صف «span»', 'row_name_not_found')
        self.assertNotIn('«أ & ب <ج>»', reliability.apply_table_delete_request(source, 'احذف صف «أ & ب <ج>»')['description'])

    def test_attribute_and_comment_text_are_not_row_labels(self):
        source = slide().replace('<b>البناء</b>', '<b title="مخفي">البناء</b><!-- مخفي -->')
        self.assert_blocked(source, 'احذف صف مخفي', 'row_name_not_found')
        self.assert_blocked(slide(), 'احذف صف «two»', 'row_name_not_found')

    def test_script_style_comments_and_templates_do_not_create_candidates(self):
        fake = '<table><tr><td>fake</td></tr></table>'
        for extra in ('<script>const x = "' + fake + '";</script>', '<style>/*' + fake + '*/</style>',
                      '<!-- ' + fake + ' -->', '<template>' + fake + '</template>',
                      '<textarea>' + fake + '</textarea>'):
            with self.subTest(extra=extra):
                source = slide(extra + table())
                self.assert_applied(source, 'delete row 2', source.replace(ROWS[1], ''))

    def test_uppercase_tags_and_quoted_angle_attributes_preserved(self):
        source = slide('<TABLE data-x="<x> >"><TBODY>' + HEADER.upper() + ''.join(ROWS) + '</TBODY></TABLE>')
        self.assert_applied(source, 'delete row 2', source.replace(ROWS[1], ''))

    def test_numeric_and_one_character_quoted_labels_are_names(self):
        row = '<tr><td>2</td><td>200</td><td>20</td></tr>'
        source = slide(table([row, ROWS[0], ROWS[2]]))
        self.assert_applied(source, 'احذف صف «2»', source.replace(row, ''))
        source = source.replace('<td>2</td>', '<td>أ</td>')
        self.assert_applied(source, 'احذف صف «أ»', source.replace(row.replace('<td>2</td>', '<td>أ</td>'), ''))

    def test_missing_and_out_of_range_targets_are_handled_not_model_fallback(self):
        for command in ('احذف الصف', 'احذف الصف 0', 'احذف الصف -1', 'احذف الصف 9999999',
                        'احذف العمود المجهول', 'احذف الصفوف 1-2', 'احذف الصفوف كلها',
                        'احذف الصف والعمود', 'delete column 1.5'):
            with self.subTest(command=command):
                self.assert_blocked(slide(), command)
        self.assert_blocked(slide('<p>لا يوجد جدول</p>'), 'احذف الصف 1', 'no_table_in_slide')

    def test_negated_conditional_and_compound_requests_are_never_partly_executed(self):
        for command in ('لا تحذف الصف الثاني', 'لا احذف الصف الثاني', 'احذف الصف الثاني لو موجود',
                        'delete row 2 if it exists', "don't delete row 2", 'احذف الصف 2 وعدل العنوان',
                        'احذف الصف 2 ثم غير اللون', 'احذف الصف 2 واحذف العمود 1'):
            with self.subTest(command=command):
                self.assert_blocked(slide(), command)

    def test_add_edit_cell_intent_is_blocked_until_supported(self):
        for command in ('أضف صف جديد', 'عدل الخلية الثانية', 'احذف محتوى الخلية',
                        'غير قيمة العمود', 'edit cell 2', 'add column'):
            with self.subTest(command=command):
                self.assert_blocked(slide(), command, 'unsupported_table_edit')

    def test_non_table_commands_are_not_caught_by_substrings(self):
        for command in ('احذف الشريحة 5', 'احذف وصف الصورة', 'احذف الصفحة الثالثة',
                        'delete slideshow', 'غير تصميم الشريحة', 'صف الجدول', ''):
            with self.subTest(command=command):
                result = reliability.apply_table_delete_request(slide(), command)
                self.assertFalse(result['handled'], result)
                self.assertEqual(result['status'], 'not_applicable')
                self.assertEqual(result['html'], slide())

    def test_legacy_public_api_shapes(self):
        self.assertEqual(reliability.parse_table_edit_request('احذف الصف الثالث'),
                         {'kind': 'row', 'by': 'number', 'number': 3})
        self.assertEqual(reliability.parse_table_edit_request('شيل عمود السعر'),
                         {'kind': 'column', 'by': 'name', 'name': 'السعر'})
        updated, description = reliability.apply_table_row_column_edit(slide(), 'احذف الصف الثالث')
        self.assertEqual(updated, slide().replace(ROWS[2], ''))
        self.assertTrue(description)
        self.assertEqual(reliability.apply_table_row_column_edit(slide(), 'احذف الصف'), (None, 'missing_table_target'))
        self.assertTrue(reliability.is_table_row_column_request('احذف الصف والعمود'))
        self.assertIsNone(reliability.parse_table_edit_request('احذف الصف والعمود'))

    def test_removal_is_not_replayed_as_a_different_named_row(self):
        first = reliability.apply_table_delete_request(slide(), 'احذف صف البناء')
        self.assert_blocked(first['html'], 'احذف صف البناء', 'row_name_not_found')

    def test_invisible_bidi_marks_and_definite_article_flexibility(self):
        source = slide(table(header='<tr><th>&rlm;الحالة</th><th>اسم المشروع</th><th>المساحة م²</th><th>المصدر والملاحظات</th></tr>',
                             rows=['<tr><td>نشط</td><td>مشروع 1</td><td>250</td><td>توثيق</td></tr>',
                                   '<tr><td>مكتمل</td><td>مشروع 2</td><td>180</td><td>سجل</td></tr>'],
                             footer=''))
        # With and without definite article
        self.assertTrue(reliability.apply_table_delete_request(source, 'احذف عمود الحاله من شريحه 21')['changed'])
        self.assertTrue(reliability.apply_table_delete_request(source, 'احذف عمود الحالة من شريحه 21')['changed'])
        self.assertTrue(reliability.apply_table_delete_request(source, 'احذف عمود حاله من شريحه 21')['changed'])
        self.assertTrue(reliability.apply_table_delete_request(source, 'احذف عمود حالة من شريحه 21')['changed'])

        # Area with superscript units, digit units, or bare name
        self.assertTrue(reliability.apply_table_delete_request(source, 'احذف عمود المساحة')['changed'])
        self.assertTrue(reliability.apply_table_delete_request(source, 'احذف عمود المساحه')['changed'])
        self.assertTrue(reliability.apply_table_delete_request(source, 'احذف عمود مساحة')['changed'])
        self.assertTrue(reliability.apply_table_delete_request(source, 'احذف عمود المساحة م2')['changed'])
        self.assertTrue(reliability.apply_table_delete_request(source, 'احذف عمود المساحة م²')['changed'])

        # Compound header with conjunction
        self.assertTrue(reliability.apply_table_delete_request(source, 'احذف عمود المصدر والملاحظات')['changed'])
        self.assertTrue(reliability.apply_table_delete_request(source, 'احذف عمود مصدر وملاحظات')['changed'])


if __name__ == '__main__':
    unittest.main()
