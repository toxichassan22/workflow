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


def test_arabic_split_phrasing_detection():
    assert reliability.is_split_request("اقسم محتوي الملخص التنفيذي بحيث يظهر بشكل واضح و منظم و المحتوي كامل")
    assert reliability.is_split_request("فكك محتوى الشريحة 5")
    assert reliability.is_split_request("جزئ شريحة الدراسة المالية إلى قسمين")
    assert reliability.is_split_request("وزع محتوى الشريحة 3 على شريحتين")
    assert reliability.is_split_request("اقسمها إلى شريحتين")
    assert not reliability.is_split_request("قسم التصور البصري")
    assert not reliability.is_split_request("قسم مالي")


def test_split_cards_or_blocks_partitions_evenly():
    html = (
        '<div class="slide" style="width:1280px;height:720px;">'
        '<h2>الملخص التنفيذي</h2>'
        '<div class="grid">'
        '<div class="card"><h3>الموقع</h3><p>طريق الملك فهد</p></div>'
        '<div class="card"><h3>المساحة</h3><p>15000 م2</p></div>'
        '<div class="card"><h3>التكلفة</h3><p>120 مليون</p></div>'
        '<div class="card"><h3>العائد</h3><p>18%</p></div>'
        '</div></div>'
    )
    parts = reliability.split_cards_or_blocks(html, "الملخص التنفيذي", 2)
    assert len(parts) == 2
    assert "الموقع" in parts[0]["html"] and "المساحة" in parts[0]["html"]
    assert "التكلفة" in parts[1]["html"] and "العائد" in parts[1]["html"]
    assert all(part["html"].count('class="slide"') == 1 for part in parts)


def test_auto_heal_workspace_slides_unpacks_multiple_slides():
    multi_html = (
        '<div class="slide" style="width:1280px;height:720px;"><h1>الجزء الأول</h1></div>'
        '<div class="slide" style="width:1280px;height:720px;"><h1>الجزء الثاني</h1></div>'
    )
    slides = [{"title": "الملخص التنفيذي", "html": multi_html}]
    healed = reliability._auto_heal_workspace_slides(slides)
    assert len(healed) == 2
    assert "الجزء الأول" in healed[0]["title"] or "الجزء 1" in healed[0]["title"]
    assert "الجزء الثاني" in healed[1]["title"] or "الجزء 2" in healed[1]["title"]
    assert all(s["html"].count('class="slide"') == 1 for s in healed)

