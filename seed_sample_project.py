"""
Seed script: Adds realistic sample input fields and training data for a real
Saudi real-estate project (Al Waha Compound – Al Narjis, Riyadh).
Run once: python seed_sample_project.py
"""
import json
import uuid
import db

SAMPLE_FIELDS = [
    # ── Basic Info ────────────────────────────────────────────────────
    {"key": "project_name",        "label": "اسم المشروع",             "type": "text",     "section": "basic",      "required": True,  "placeholder": "مثلاً: مجمع الواحة السكني"},
    {"key": "project_name_en",     "label": "اسم المشروع بالإنجليزي",  "type": "text",     "section": "basic",      "required": False, "placeholder": "e.g. Al Waha Residential Compound"},
    {"key": "project_type",        "label": "نوع المشروع",             "type": "select",   "section": "basic",      "required": True,  "options": ["سكني فاخر", "سكني اقتصادي", "تجاري", "مختلط", "świقي", "świقي فاخر"]},
    {"key": "project_description", "label": "وصف المشروع",             "type": "textarea", "section": "basic",      "required": True,  "placeholder": "وصف تفصيلي للمشروع..."},
    {"key": "total_area_sqm",      "label": "المساحة الإجمالية (م²)",   "type": "number",   "section": "basic",      "required": True},
    {"key": "total_units",         "label": "عدد الوحدات",             "type": "number",   "section": "basic",      "required": True},

    # ── Location ──────────────────────────────────────────────────────
    {"key": "location_address",    "label": "عنوان الموقع",            "type": "text",     "section": "location",   "required": True,  "placeholder": "حي النرجس، طريق الأمير محمد بن سعد، الرياض"},
    {"key": "location_lat",        "label": "خط العرض",                "type": "number",   "section": "location",   "required": True},
    {"key": "location_lng",        "label": "خط الطول",                "type": "number",   "section": "location",   "required": True},
    {"key": "main_roads",          "label": "الطرق الرئيسية المحيطة",  "type": "textarea", "section": "location",   "required": False, "placeholder": "طريق الملك فهد، طريق الأمير محمد بن سعد"},
    {"key": "secondary_roads",     "label": "الطرق الفرعية",           "type": "textarea", "section": "location",   "required": False, "placeholder": "شارع النرجس، شارع الراكة"},
    {"key": "catchment_areas",     "label": "نطاق الخدمات المحيطة",   "type": "textarea", "section": "location",   "required": False, "placeholder": "5 دقائق: مجمع الراشد Mall\n10 دقائق: جامعة الملك سعود"},

    # ── Financial ─────────────────────────────────────────────────────
    {"key": "total_project_cost",     "label": "إجمالي تكلفة المشروع (ريال)",  "type": "number", "section": "financial", "required": True},
    {"key": "land_cost",              "label": "تكلفة الأرض (ريال)",           "type": "number", "section": "financial", "required": True},
    {"key": "construction_cost",      "label": "تكلفة الإنشاء (ريال)",         "type": "number", "section": "financial", "required": True},
    {"key": "infrastructure_cost",    "label": "تكلفة البنية التحتية (ريال)",  "type": "number", "section": "financial", "required": False},
    {"key": "unit_price_min",         "label": "أقل سعر للوحدة (ريال)",        "type": "number", "section": "financial", "required": True},
    {"key": "unit_price_max",         "label": "أعلى سعر للوحدة (ريال)",       "type": "number", "section": "financial", "required": True},
    {"key": "annual_revenue_expected", "label": "الإيراد السنوي المتوقع (ريال)", "type": "number", "section": "financial", "required": True},
    {"key": "annual_operating_expenses", "label": "المصروفات التشغيلية السنوية (ريال)", "type": "number", "section": "financial", "required": True},
    {"key": "net_operating_income",   "label": "صافي الدخل التشغيلي (ريال)",  "type": "number", "section": "financial", "required": True},
    {"key": "roi_percentage",         "label": "نسبة العائد على الاستثمار %",  "type": "number", "section": "financial", "required": True},
    {"key": "payback_period_years",   "label": "مدة استرداد الاستثمار (سنوات)","type": "number", "section": "financial", "required": True},
    {"key": "total_profit_expected",  "label": "إجمالي الأرباح المتوقعة (ريال)","type": "number","section": "financial", "required": True},

    # ── Features / Components ─────────────────────────────────────────
    {"key": "project_features",    "label": "مميزات المشروع",         "type": "textarea", "section": "features",   "required": False, "placeholder": "مميز للبيع: مسبح أولمبي ونادي صحي..."},
    {"key": "project_components",  "label": "مكونات المشروع",         "type": "textarea", "section": "features",   "required": False, "placeholder": "فيلا standalone × 40 — 450 م² — 3,200,000 ريال"},
    {"key": "target_audience",     "label": "الجمهور المستهدف",       "type": "textarea", "section": "features",   "required": False},
    {"key": "key_selling_points",  "label": "نقاط البيع الرئيسية",    "type": "textarea", "section": "features",   "required": False},
    {"key": "exit_strategy",       "label": "استراتيجية الخروج",      "type": "text",     "section": "features",   "required": False},

    # ── SWOT ──────────────────────────────────────────────────────────
    {"key": "swot_strengths",     "label": "نقاط القوة",              "type": "textarea", "section": "swot", "required": False},
    {"key": "swot_weaknesses",    "label": "نقاط الضعف",              "type": "textarea", "section": "swot", "required": False},
    {"key": "swot_opportunities", "label": "الفرص",                   "type": "textarea", "section": "swot", "required": False},
    {"key": "swot_threats",       "label": "التهديدات",               "type": "textarea", "section": "swot", "required": False},

    # ── Timeline ──────────────────────────────────────────────────────
    {"key": "development_timeline_months", "label": "مدة التطوير (أشهر)", "type": "number", "section": "basic", "required": False},
    {"key": "project_start_date",          "label": "تاريخ البدء",        "type": "date",   "section": "basic", "required": False},
    {"key": "project_end_date",            "label": "تاريخ الانتهاء",     "type": "date",   "section": "basic", "required": False},
]

SAMPLE_PROJECT_DATA = {
    "project_name": "مجمع الواحة السكني — حي النرجس",
    "project_name_en": "Al Waha Residential Compound – Al Narjis",
    "project_type": "سكني فاخر",
    "project_description": "مجمع سكني فاخر يتكون من 120 فيلا بتصميم معماري حديث في حي النرجس شمال الرياض. يتضمن المجمع مرافق ترفيهية متنوعة منها مسبح أولمبي ونادي صحي ومساحات خضراء واسعة ومسارات للمشي وركوب الدراجات. يتميز الموقع بقربه من طريق الملك فهد وطريق الأمير محمد بن سعد، مع وصول سهل إلى مطار الملك خالد الدولي والخدمات الحيوية.",
    "location_address": "حي النرجس، طريق الأمير محمد بن سعد، الرياض، المملكة العربية السعودية",
    "location_lat": 24.7833,
    "location_lng": 46.6250,
    "main_roads": "طريق الملك فهد\nطريق الأمير محمد بن سعد\nطريق الدمام",
    "secondary_roads": "شارع النرجس\nشارع الراكة\nطريق وادي الدواسر",
    "catchment_areas": "5 دقائق: مجمع الراشد Mall\n10 دقائق: جامعة الملك سعود\n15 دقائق: مطار الملك خالد الدولي\n20 دقائق: مركز المملكة",
    "total_area_sqm": 85000,
    "total_units": 120,
    "total_project_cost": 280000000,
    "land_cost": 95000000,
    "construction_cost": 165000000,
    "infrastructure_cost": 20000000,
    "unit_price_min": 1800000,
    "unit_price_max": 3200000,
    "annual_revenue_expected": 42000000,
    "annual_operating_expenses": 8400000,
    "net_operating_income": 33600000,
    "roi_percentage": 14.5,
    "payback_period_years": 6.8,
    "total_profit_expected": 140000000,
    "exit_strategy": "بيع الوحدات سكناً واستثماراً مع خيارات تمويل بنكي",
    "development_timeline_months": 30,
    "project_start_date": "2026-01-01",
    "project_end_date": "2028-06-30",
    "project_features": "120 فيلا بتصميم معماري حديث\nمسبح أولمبي ونادي صحي\nمساحات خضراء 40% من المساحة الإجمالية\nنظام أمن متكامل 24/7\nالقريب لطريق الملك فهد\nقريب من مطار الملك خالد الدولي\nخدمات صيانة شاملة\nموقف سيارات مغطى لكل فيلا",
    "project_components": "فيلا standalone × 40 — 450 م² — 3,200,000 ريال\nفيلا Townhouse × 50 — 380 م² — 2,400,000 ريال\nفيلا Duplex × 30 — 320 م² — 1,800,000 ريال\nمرافق ترفيهية × 1 — 5,000 م² — 15,000,000 ريال\nمسبح أولمبي × 1 — 2,000 م² — 8,000,000 ريال\nنادي صحي × 1 — 1,500 م² — 5,000,000 ريال",
    "target_audience": "عائلات متوسطة وعالية الدخل الباحثة عن سكن فاخر في شمال الرياض\nالمستثمرون في العقارات السكنية\nالمغتربون العاملون في الرياض",
    "key_selling_points": "أفضل موقع في شمال الرياض\nتصميم معماري عالمي\nمرافق حصرية\nعائد استثماري مرتفع\nقريب من جميع الخدمات",
    "swot_strengths": "موقع استراتيجي على طريق الملك فهد\nتصميم معماري عالي الجودة\nمرافق ترفيهية متكاملة\nقرب من المطار والخدمات",
    "swot_weaknesses": "تطلب استثمار أولي مرتفع\nمنافسة شديدة في السوق\nتأخر محتمل في التصاريح",
    "swot_opportunities": "نمو سكاني متزايد في الرياض\nزيادة الطلب على الفيلات الفاخرة\nدعم حكومي للمشاريع السكنية",
    "swot_threats": "تغيرات اقتصادية محتملة\nزيادة تكاليف البناء\nمنافسة مشاريع جديدة",
}


def seed_fields(tenant_id):
    """Insert sample input fields for the given tenant."""
    conn = db.get_db()
    inserted = 0
    for i, f in enumerate(SAMPLE_FIELDS):
        fid = uuid.uuid4().hex[:12]
        options_json = json.dumps(f.get("options"), ensure_ascii=False) if f.get("options") else None
        try:
            conn.execute(
                """INSERT OR IGNORE INTO tenant_input_fields
                   (id, tenant_id, field_key, field_label, field_type, field_options,
                    section_key, is_required, is_active, is_custom, sort_order, placeholder)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)""",
                (fid, tenant_id, f["key"], f["label"], f["type"], options_json,
                 f["section"], 1 if f.get("required") else 0, i * 10, f.get("placeholder")),
            )
            inserted += 1
        except Exception as e:
            print(f"  skip {f['key']}: {e}")
    conn.commit()
    return inserted


def seed_training(tenant_id):
    """Add sample AI training entries."""
    entries = [
        ("توجه الشركة",   "الشركة تركز على المشاريع السكنية الفاخرة في شمال الرياض. العروض التقديمية يجب أن تعكس الفخامة والجودة العالية. الألوان الرئيسية هي الأزرق الداكن والذهبي. الأيقونات يجب أن تكون SVG أحادية اللون وليست إيموجي.", "general"),
        ("أسلوب العرض",   "الشرائح يجب أن تكون بسيطة وأنيقة مع تركيز على الأرقام المالية. الأرقام الكبيرة في البطاقات. تجنب النص الطويل واستخدم bullet points. التصميم يجب أن يكون احترافي وليس كرتوني.", "design"),
        ("الخرائط",       "استخدم دائماً خرائط قمر صناعي مع علامات موقع واضحة. أضف المعالم القريبة مع أوقات القيادة. اكتب أسماء الطرق الرئيسية على الخريطة.", "maps"),
    ]
    conn = db.get_db()
    inserted = 0
    for title, content, cat in entries:
        eid = uuid.uuid4().hex[:12]
        try:
            conn.execute(
                """INSERT INTO tenant_training_data (id, tenant_id, title, content, category)
                   VALUES (?, ?, ?, ?, ?)""",
                (eid, tenant_id, title, content, cat),
            )
            inserted += 1
        except Exception as e:
            print("  skip training: " + str(e))
    conn.commit()
    return inserted


if __name__ == "__main__":
    import sys
    from app import app          # noqa — ensures Flask app is available
    tenant_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not tenant_id:
        print("Usage: python seed_sample_project.py <tenant_id>")
        print("  Run after registering a company to populate it with sample data.")
        sys.exit(1)

    with app.app_context():
        print(f"[SEED] Populating tenant {tenant_id} …")
        n_fields = seed_fields(tenant_id)
        n_training = seed_training(tenant_id)
        print(f"[SEED] Done — {n_fields} fields, {n_training} training entries inserted.")
        print(f"[SEED] Sample project data saved to: sample_project_data.json")
