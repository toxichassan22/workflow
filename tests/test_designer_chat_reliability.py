import re

import designer_chat_reliability as reliability


def test_collects_descriptions_from_project_and_parallel_metadata():
    project = {
        "land_photos_file_meta": [
            {"imageUrl": "/uploads/land-a.jpg", "description": "واجهة الأرض الشمالية"}
        ],
        "visual_concept": {
            "slots": {
                "exterior-1": {
                    "approvedImageUrl": "/uploads/exterior.webp",
                    "caption": "تصور الواجهة الرئيسية",
                }
            }
        },
    }
    images = {
        "moodboard": ["/uploads/mood-1.jpg"],
        "moodboard_meta": [{"caption": "الخامات المقترحة"}],
        "plans": ["/uploads/plan.png"],
        "plan_meta": [{"description": "المخطط العام للمشروع"}],
    }

    descriptions = reliability.collect_image_descriptions(project, images)

    assert descriptions["land-a.jpg"] == "واجهة الأرض الشمالية"
    assert descriptions["exterior.webp"] == "تصور الواجهة الرئيسية"
    assert descriptions["mood-1.jpg"] == "الخامات المقترحة"
    assert descriptions["plan.png"] == "المخطط العام للمشروع"


def test_adds_only_missing_matching_image_descriptions_and_is_idempotent():
    descriptions = {
        "/uploads/a.jpg": "وصف الصورة الأولى",
        "b.jpg": "وصف الصورة الثانية",
    }
    html = (
        '<div class="slide">'
        '<figure><img src="/uploads/a.jpg"></figure>'
        '<figure><img src="https://cdn.example.com/b.jpg?version=2">'
        '<figcaption>وصف موجود بالفعل</figcaption></figure>'
        '<img src="/uploads/unmatched.jpg">'
        '</div>'
    )

    updated, count, added = reliability.add_missing_image_descriptions(html, descriptions)
    repeated, repeated_count, _ = reliability.add_missing_image_descriptions(updated, descriptions)

    assert count == 1
    assert added == ["وصف الصورة الأولى"]
    assert "وصف الصورة الأولى" in updated
    assert "وصف الصورة الثانية" not in updated
    assert repeated_count == 0
    assert repeated == updated


def test_caption_escapes_clipped_media_wrapper_and_repairs_old_insertions():
    descriptions = {"photo.jpg": "وصف محفوظ يجب أن يظهر أسفل الصورة"}
    html = (
        '<div class="card"><h3>قاعة الاحتفالات</h3>'
        '<div class="image-frame" style="height:325px;overflow:hidden">'
        '<img src="/uploads/photo.jpg" style="width:100%;height:100%;object-fit:cover">'
        '</div><div class="blank-space"></div></div>'
    )

    updated, count, _ = reliability.add_missing_image_descriptions(html, descriptions)
    repeated, repeated_count, _ = reliability.add_missing_image_descriptions(updated, descriptions)

    wrapper_close = updated.index('</div>', updated.index('<img'))
    caption_start = updated.index('data-project-image-description')
    assert count == 1
    assert caption_start > wrapper_close
    assert updated.count('data-project-image-description') == 1
    assert repeated_count == 0
    assert repeated == updated

    broken = (
        '<div class="card"><div style="height:325px;overflow:hidden">'
        '<img src="/uploads/photo.jpg">'
        '<div data-project-image-description="old" data-visual-media-caption="1" '
        'style="font-size:13px">وصف محفوظ يجب أن يظهر أسفل الصورة</div>'
        '</div></div>'
    )
    repaired, repaired_count, _ = reliability.add_missing_image_descriptions(broken, descriptions)
    repaired_wrapper_close = repaired.index('</div>', repaired.index('<img'))
    repaired_caption_start = repaired.index('data-project-image-description')

    assert repaired_count == 1
    assert repaired_caption_start > repaired_wrapper_close
    assert repaired.count('data-project-image-description') == 1


def test_visual_caption_is_persisted_in_canonical_slide_metadata():
    descriptions = {
        "a.jpg": "وصف جديد محفوظ",
        "b.jpg": "وصف البيانات للصورة الثانية",
    }
    slide = {
        "image_tokens": ["##MOODBOARD_IMAGE_1##", "##MOODBOARD_IMAGE_2##"],
        "html": (
            '<div><div class="image-frame" style="height:300px;overflow:hidden">'
            '<img src="/uploads/a.jpg"></div></div>'
            '<div><div class="image-frame" style="height:300px;overflow:hidden">'
            '<img src="/uploads/b.jpg"></div>'
            '<div data-visual-media-caption="1">وصف ظاهر موجود</div></div>'
        ),
    }

    updated, count, _ = reliability.add_missing_image_descriptions(slide["html"], descriptions)
    slide["html"] = updated
    changed, persisted = reliability.sync_slide_caption_metadata(slide, descriptions)

    assert count == 1
    assert changed
    assert persisted == 2
    assert slide["captions"] == ["وصف جديد محفوظ", "وصف ظاهر موجود"]
    assert "description" not in slide

    changed_again, persisted_again = reliability.sync_slide_caption_metadata(slide, descriptions)
    assert not changed_again
    assert persisted_again == 0


def test_detects_caption_requests_and_requested_split_count():
    assert reliability.is_image_description_request("حط وصف الصور المكتوب في بيانات المشروع")
    assert reliability.is_image_description_request("عايزه يضيف وصف لكل صورة")
    assert not reliability.is_image_description_request("ولد صورة جديدة للواجهة")
    assert reliability.split_request_parts("قسم الشريحة إلى 3 شرائح") == 3
    assert reliability.split_request_parts("قسمها تلقائي حسب المحتوى") == "auto"
    assert reliability.is_split_request("قسمها تلقائي حسب المحتوى")
    assert reliability.is_split_request("قسّم الشريحة إلى ثلاث شرائح")
    assert not reliability.is_split_request("قسم التصور البصري")


def test_table_split_balances_rows_repeats_header_and_preserves_every_row_once():
    rows = "".join(
        f'<tr><td>صف {number}</td><td>قيمة {number}</td><td>بيان {number}</td></tr>'
        for number in range(1, 51)
    )
    html = (
        '<div class="slide"><h2>الجدول المالي</h2><table>'
        '<thead><tr><th>البند</th><th>القيمة</th><th>البيان</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div>'
    )

    parts = reliability.split_table_slide(html, "الجدول المالي", "auto")

    assert len(parts) == 5
    sizes = [len(re.findall(r"<tbody>[\s\S]*?</tbody>", part["html"])[0].split("<tr>")) - 1 for part in parts]
    assert max(sizes) - min(sizes) <= 1
    assert all(part["html"].count("<thead>") == 1 for part in parts)
    combined = "\n".join(part["html"] for part in parts)
    for number in range(1, 51):
        assert len(re.findall(fr">صف {number}<", combined)) == 1


def test_auto_table_split_does_not_split_a_table_that_fits():
    rows = "".join(f"<tr><td>{number}</td></tr>" for number in range(1, 6))
    html = f'<div class="slide"><table><tbody>{rows}</tbody></table></div>'

    assert reliability.split_table_slide(html, "جدول", "auto") == []


def test_table_without_tbody_is_paginated_and_keeps_implicit_header():
    rows = "".join(f"<tr><td>صف {number}</td><td>{number}</td></tr>" for number in range(1, 26))
    html = (
        '<div class="slide"><table><tr><th>البند</th><th>القيمة</th></tr>'
        + rows + '</table></div>'
    )

    parts = reliability.split_table_slide(html, "جدول مباشر", "auto")

    assert len(parts) == 3
    assert all(part["html"].count("<thead>") == 1 for part in parts)
    assert all(part["html"].count("<tbody>") == 1 for part in parts)
    combined = "\n".join(part["html"] for part in parts)
    for number in range(1, 26):
        assert len(re.findall(fr">صف {number}<", combined)) == 1


def test_explicit_parts_expand_when_requested_count_would_still_overflow():
    long_cell = "نص طويل " * 45
    rows = "".join(f"<tr><td>{number}</td><td>{long_cell}</td></tr>" for number in range(1, 21))
    html = f'<div class="slide"><table><tbody>{rows}</tbody></table></div>'

    parts = reliability.split_table_slide(html, "جدول طويل", 2)

    assert len(parts) >= 4
    assert sum(part["html"].count("<tr>") for part in parts) == 20


def test_material_change_rejects_unchanged_and_fallback_responses():
    original = '<div class="slide">نفس المحتوى</div>'
    assert not reliability.materially_changed(original, original, "تم التعديل")
    assert not reliability.materially_changed(original, original + " ", "تم التعديل")
    assert not reliability.materially_changed(original, original + "<p>جديد</p>", "تم الحفاظ على تصميم الشريحة 1 لتعذر التعديل التلقائي عليها.")
    assert reliability.materially_changed(original, original + "<p>جديد</p>", "تم تحديث الشريحة")
