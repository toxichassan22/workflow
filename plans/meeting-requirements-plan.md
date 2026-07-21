# خطة متطلبات اجتماع اليوم

## تاريخ: 2026-07-20

---

## المتطلب 1: نظام Section كامل + أزرار التالي

### الوضع الحالي
- صفحة `tenantProjectPage` تحتوي على sidebar للتنقل بين الأقسام + form content
- الأقسام: معلومات أساسية، موقع وخرائط، بيانات مالية، تفاصيل المشروع، SWOT، مكونات، حسابات مالية، جدول زمني
- 3 مراحل وركفلو: الهيكل → الصورة الرئيسية → المود بورد
- صفحة معاينة شرائح + صفحة شات تصميم

### المطلوب
- **إلغاء الـ sidebar** في صفحة بيانات المشروع
- **كل الأقسام تظهر تحت بعضها** في صفحة واحدة بـ scroll عمودي
- **زر "التالي"** في نهاية الصفحة ينقل لصفحة التوليد (خطة الشرائح → الصورة الرئيسية → المود بورد) ثم الشات
- زر "التالي" لا يظهر إلا في صفحة التوليد وصفحة الشات فقط
- صفحة بيانات المشروع تنتهي بزر "التالي: خطة الشرائح"

### التغييرات المطلوبة

#### index.html
1. **إلغاء `projectFormSidebar`** — حذف الـ sidebar container والـ `formSidebarNav`
2. **تعديل `renderTenantProjectForm()`** — عرض كل الأقسام stacked عمودياً بدل إخفاء/إظهار قسم واحد
3. **تعديل `showSection()`** — تحويلها لـ scroll إلى القسم بدل إخفاء الباقي
4. **تعديل `populateProjectSidebar()`** — إلغاؤها أو تحويلها لـ progress indicator علوي بدل sidebar
5. **إضافة زر "التالي"** في نهاية `tenantProjectPage` ينقل لـ `tenantSlidePlanPage`
6. **إزالة أزرار التالي** من أي مكان آخر غير صفحات التوليد والشات
7. **تعديل CSS** — `.tenant-form-section` يظهر دائماً (إزالة `display:none` الافتراضي)

#### الملفات المتأثرة
- `index.html` — الواجهة والـ JS

---

## المتطلب 2: دقة الخرائط

### الوضع الحالي
- `maps_service.py` يستخدم Google Maps Static API + Geocoding API + Places API
- OSM Overpass API لكشف polygon المباني
- OSRM لرسم الطرق
- زوم ديناميكي مبني على حجم الـ polygon
- المشاكل: إحداثيات غير دقيقة، زوم غير مناسب، معالم بعيدة، طرق مرسومة من frontend

### المطلوب
1. **دقة الإحداثيات** — تحسين الـ geocoding
2. **مستوى الزوم** — ضبط الزوم ليكون مناسباً
3. **المعالم القريبة** — معالم صحيحة وقريبة
4. **الطرق** — تحديد الطرق من Google Maps بدلاً من frontend/OSRM

### التغييرات المطلوبة

#### maps_service.py
1. **تحسين Geocoding**:
   - إضافة `components` parameter للـ geocoding (country:SA, region) لتقييد النتائج
   - استخدام `result_type` filter للمباني والعناوين الدقيقة
   - إذا يتوفر `location_maps_link`، استخراج الإحداثيات منه مباشرة بدل geocoding
   - التحقق من دقة الإحداثيات بمقارنة `viewport` size — إذا كبير جداً يعني غير دقيق

2. **ضبط الزوم**:
   - مراجعة حسابات الـ dynamic zoom في `generate_all_map_images()`
   - overview: zoom 14-16 (بدل 13)
   - landmarks: zoom 15-17 (بدل 14)
   - access: zoom 16-18 (بدل 15)
   - catchment: zoom 13-14 (بدل 12)
   - بناء الزوم على مسافة المعالم الأبعد بدل حجم الـ polygon فقط

3. **تحسين المعالم القريبة**:
   - تقليل radius من 2000m إلى 1000m للمعالم القريبة
   - فلترة المعالم بمسافة فعلية (Haversine) بدل الإحداثيات التقريبية
   - ترتيب المعالم بالمسافة الفعلية
   - استخدام `rankby=distance` في Places API
   - إضافة أنواع معالم عقارية ذات صلة (school, hospital, mall, park, mosque)

4. **تحديد الطرق من Google Maps**:
   - إلغاء استخدام OSRM لرسم الطرق
   - استخدام Google Maps Roads API (`nearestRoads` و `snapToRoads`) لتحديد الطرق الفعلية
   - أو استخدام Google Directions API للحصول على polyline الطرق الفعلية
   - تحديث `SATELLITE_CLEAN_STYLES` لإبراز الطرق الرئيسية في صورة الخريطة
   - الاعتماد على styling بدل رسم خطوط يدوية

#### app.py
- تحديث `resolve_designer_chat_placeholders()` لتمرير بيانات الطرق بشكل صحيح

#### الملفات المتأثرة
- `maps_service.py` — التحسينات الأساسية
- `app.py` — تمرير البيانات

---

## المتطلب 3: نظام المسودة والتعميد

### الوضع الحالي
- `saveProjectAsDraft()` يحفظ في `localStorage` فقط (محلي)
- التعميد موجود على مستوى العرض كامل (`presentation_approvals` table)
- لا يوجد حالة per-section
- حالات العرض: draft, pending_approval, approved, edited

### المطلوب
- **مسودة موحدة** للمشروع كامل (حفظ في السيرفر)
- **حالة لكل قسم**: draft / approved
- **التعميد على المشروع كامل** بعد إكمال كل الأقسام

### التغييرات المطلوبة

#### db.py
1. **جدول جديد `project_drafts`**:
   ```sql
   CREATE TABLE IF NOT EXISTS project_drafts (
     id TEXT PRIMARY KEY,
     tenant_id TEXT NOT NULL,
     user_id TEXT NOT NULL,
     project_data TEXT,
     section_statuses TEXT, -- JSON: {basic: "draft", location: "approved", ...}
     status TEXT DEFAULT 'draft', -- draft, pending_approval, approved
     created_at TEXT,
     updated_at TEXT
   );
   ```
2. **دوال جديدة**:
   - `save_project_draft(tenant_id, user_id, project_data, section_statuses)`
   - `get_project_draft(tenant_id, draft_id)`
   - `get_latest_draft(tenant_id, user_id)`
   - `update_section_status(draft_id, section_key, status)`
   - `submit_draft_for_approval(draft_id)` — يغير الحالة لـ pending_approval
   - `approve_draft(draft_id)` — يغير الحالة لـ approved وينشئ presentation

#### app.py
1. **API endpoints جديدة**:
   - `POST /api/drafts` — حفظ مسودة
   - `GET /api/drafts/<id>` — جلب مسودة
   - `GET /api/drafts/latest` — جلب آخر مسودة
   - `PUT /api/drafts/<id>/section-status` — تحديث حالة قسم
   - `POST /api/drafts/<id>/submit-approval` — إرسال للتعميد
   - `POST /api/drafts/<id>/approve` — تعميد (admin فقط)

#### index.html
1. **استبدال `saveProjectAsDraft()`** — حفظ في السيرفر بدل localStorage
2. **إضافة مؤشر حالة لكل قسم** — badge بجانب كل قسم (مسودة / معمّد)
3. **زر "حفظ المسودة"** في كل قسم — يحفظ القسم ويحدّث حالته
4. **زر "تعميد المشروع"** — يظهر بعد إكمال كل الأقسام
5. **تحميل المسودة المحفوظة** عند فتح صفحة بيانات المشروع

#### الملفات المتأثرة
- `db.py` — جدول جديد ودوال
- `app.py` — API endpoints
- `index.html` — الواجهة

---

## المتطلب 4: إزالة كل الأيقونات

### الوضع الحالي
- **index.html**: `SECTION_ICONS`, `SECTION_ICON_MAP`, `SECTION_ICON_EMOJI` — كلها فارغة بالفعل
- **design_templates.py**: قواعد SVG icons في الـ prompts للـ AI
- **pdf_generator.py**: `draw_icon()` — رسم أيقونات بـ reportlab
- **pdf_generator_html.py**: `icons_map` — SVG icons في الـ HTML PDF
- **slide_engine.py**: أيقونات في الـ prompts

### المطلوب
- إزالة كل الأيقونات من: الواجهة، الشرائح المولّدة، PDF، PPTX

### التغييرات المطلوبة

#### index.html
1. **حذف** `SECTION_ICONS`, `SECTION_ICON_MAP`, `SECTION_ICON_EMOJI` maps
2. **حذف** `getSectionIcon()` function
3. **حذف** `<select id="newSectionIcon">` من إعدادات الأقسام المخصصة
4. **حذف** `icon` من `addCustomSection()` call
5. **تنظيف** أي مرجع للأيقونات في `populateProjectSidebar()`
6. **حذف** `.pf-icon` CSS class

#### design_templates.py
1. **تعديل** `icon_style` — تعطيل أيقونات SVG في كل القوالب
2. **حذف** قسم "الأيقونات — قواعد صارمة" من الـ prompts
3. **استبدال** بـ "بدون أيقونات. اعتمد على التخطيط والمساحات."

#### pdf_generator.py
1. **تعطيل** `draw_icon()` — جعلها no-op أو حذفها
2. **إزالة** كل استدعاءات `draw_icon()` في دوال الرسم

#### pdf_generator_html.py
1. **حذف** `icons_map` dictionary
2. **إزالة** `icon_svg` من `_render_metrics()` وغيرها
3. **استبدال** مساحة الأيقونة بمساحة فارغة أو نص فقط

#### slide_engine.py
1. **إزالة** أي ذكر للأيقونات من الـ system prompts
2. **إزالة** `icon` من أي template أو layout

#### app.py
1. **إزالة** `icon` parameter من `api_add_custom_section()` و `api_update_custom_section()`

#### db.py
1. **إزالة** `section_icon` من `FIELD_SECTIONS` definitions
2. **إبقاء** العمود في الـ DB (للتوافق مع البيانات الموجودة) لكن تجاهله

#### الملفات المتأثرة
- `index.html`
- `design_templates.py`
- `pdf_generator.py`
- `pdf_generator_html.py`
- `slide_engine.py`
- `app.py`
- `db.py`

---

## المتطلب 5: رفع الصور لنظام التدريب

### الوضع الحالي
- نظام التدريب نصي فقط (`tenant_training_data` table — title, content, category)
- شات للتدريب عبر `/api/training-chat`
- لا يوجد رفع صور للتدريب
- كل شركه (tenant) لها training data منفصلة (موجود بالفعل)

### المطلوب
- رفع صور لنظام التدريب (لوجو، علامة مائية، صور مرجعية للتصميم)
- كل صورة مع نص وصفي
- تحليل بالـ AI Vision لاستخراج معلومات من الصورة
- الصور تُستخدم كـ context للـ AI عند توليد الشرائح
- كل شركة لها صورها الخاصة (عبر tenant_id)

### التغييرات المطلوبة

#### db.py
1. **جدول جديد `tenant_training_images`**:
   ```sql
   CREATE TABLE IF NOT EXISTS tenant_training_images (
     id TEXT PRIMARY KEY,
     tenant_id TEXT NOT NULL,
     title TEXT NOT NULL,
     description TEXT,
     file_path TEXT NOT NULL,
     file_type TEXT, -- logo, watermark, reference, design_sample
     ai_analysis TEXT, -- تحليل AI Vision للصورة
     is_active INTEGER DEFAULT 1,
     created_at TEXT,
     updated_at TEXT
   );
   ```
2. **دوال جديدة**:
   - `add_training_image(tenant_id, title, description, file_path, file_type, ai_analysis)`
   - `get_training_images(tenant_id, active_only=False)`
   - `update_training_image(id, **kwargs)`
   - `delete_training_image(id)`
   - `get_training_images_context(tenant_id)` — يجمع كل الصور النشطة + وصفها + تحليلها كنص

#### app.py
1. **API endpoints جديدة**:
   - `POST /api/training-images` — رفع صورة (multipart/form-data)
   - `GET /api/training-images` — جلب كل الصور
   - `PUT /api/training-images/<id>` — تحديث
   - `DELETE /api/training-images/<id>` — حذف
2. **تحليل AI Vision**:
   - عند رفع صورة، إرسالها لـ AI Vision (GLM-4V أو مماثل) لاستخراج:
     - نوع المحتوى (لوجو، تصميم، صورة عقار)
     - الألوان الرئيسية
     - الأسلوب (modern, classic, minimal)
     - العناصر المرئية
   - حفظ التحليل في `ai_analysis`
3. **دمج الصور في training context**:
   - تعديل `get_training_context()` لإضافة وصف الصور وتحليلها
   - تمرير الصور المرجعية كـ URLs في الـ system prompt للـ AI
4. **أنواع الصور**:
   - `logo` — شعار الشركة (يُستخدم في الشرائح)
   - `watermark` — علامة مائية
   - `reference` — صورة مرجعية للتصميم
   - `design_sample` — نموذج تصميم سابق

#### index.html
1. **إضافة قسم رفع الصور** في صفحة التدريب (`tenantTrainingPage` و `tenantAIRulesPage`)
2. **UI لرفع الصور**:
   - drag & drop area
   - اختيار نوع الصورة (لوجو، علامة مائية، مرجع، نموذج)
   - حقل وصف نصي
   - معاينة الصورة بعد الرفع
3. **عرض الصور المرفوعة**:
   - grid للصور مع نوعها ووصفها وتحليل AI
   - أزرار تفعيل/تعطيل/حذف
4. **استخدام اللوجو**:
   - إذا رُفع لوجو كنوع `logo`، يُستخدم تلقائياً في الشرائح بدل `##LOGO##`

#### الملفات المتأثرة
- `db.py` — جدول جديد ودوال
- `app.py` — API endpoints + AI Vision integration
- `index.html` — UI لرفع وعرض الصور

---

## ترتيب التنفيذ

| # | المتطلب | الأولوية | المدة التقديرية |
|---|---------|----------|----------------|
| 1 | إزالة الأيقونات | عالية | 1-2 ساعة |
| 2 | نظام Section + أزرار التالي | عالية | 2-3 ساعة |
| 3 | نظام المسودة والتعميد | عالية | 3-4 ساعة |
| 4 | دقة الخرائط | عالية | 3-4 ساعة |
| 5 | رفع الصور للتدريب | متوسطة | 3-4 ساعة |

**الإجمالي: ~12-17 ساعة**

---

## ملاحظات

- كل شركة (tenant) لها عزل كامل لبياناتها (موجود بالفعل في الـ architecture)
- التغييرات في `index.html` هي الأكبر لأن الواجهة كلها فيه
- `maps_service.py` يحتاج اختبار فعلي بإحداثيات حقيقية
- رفع الصور يحتاج AI Vision API — التحقق من توفره في الـ API المستخدم
