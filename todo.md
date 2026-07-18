# خطة التنفيذ — Real Estate Proposal Generator (منافع)

> بناءً على `needed.md` + حالة المشروع الحالية (قاعدة بيانات `app.db`, `app.py`, `index.html`, `maps_service.py`, `slide_engine.py`, `design_templates.py`).
> الهدف: إغلاق الفجوات بين المتطلبات والكود الموجود، وتحديد أولويات التنفيذ.

---

## 1. ملخص الحالة الحالية

### ما تم تنفيذه بالفعل
- **نظام Multi-Tenant كامل**: شركات + موظفين + أدوار + JWT (`auth.py`, `db.py`).
- **SAG Super Admin**: إدارة الشركات (إضافة/تعطيل/حذف) موجودة في `tenantAdminPage`.
- **إعدادات الشركة (Branding)**: ألوان، خط، لوجو، قالب، هيدر/فوتر، نسبة العرض، min/max slides (`/api/branding`).
- **قواعد AI**: صفحة `tenantAIRulesPage` مع تصنيف Green/Yellow/Red + سجل تعديلات (`ai_rules_log`).
- **تدريب GLM**: `tenant_training_data` + `/api/training`، ويُمرّر في system prompt.
- **الحقول الديناميكية**: `tenant_input_fields` مقسّمة لـ sections (`basic`, `location`, `financial`, `features`, `swot`).
- **الصلاحيات**: `user_permissions` + `user_field_sections` (الموظف يوصل لحاجات محددة).
- **خطة الشرائح الذكية**: `slide_engine.py` + `/api/slide-plan` مع 4 شرائح ثابتة (cover=1, index=2, moodboard=قبل الأخير, closing=أخير).
- **الخرائط**: `maps_service.py` يولد overview/landmarks/access/catchment بأنماط satellite/roadmap/terrain/hybrid/both.
- **التصدير**: PDF عبر Playwright + PPTX عبر `exports/pptx_export.py`.
- **تعميد العروض**: `presentation_approvals` + `/api/approvals`.
- **سجل التعديلات**: `edit_log` + `presentation_versions`.
- **الأيقونات**: تحسين كبير في `design_templates.py` — ممنوع Emojis، ويتم إرشاد AI لاستخدام SVG inline أحادية اللون.

### الملفات الرئيسية التي تمت مراجعتها
- `d:\workflow\needed.md` — متطلبات المستخدم.
- `d:\workflow\app.py` — API Flask.
- `d:\workflow\db.py` — طبقة البيانات.
- `d:\workflow\index.html` — الواجهة الأمامية.
- `d:\workflow\slide_engine.py` — قواعد توزيع المحتوى وخطة الشرائح.
- `d:\workflow\design_templates.py` — قوالب التصميم وقواعد الأيقونات.
- `d:\workflow\maps_service.py` — توليد خرائط Google Maps.
- `d:\workflow\todo.md` — هذا الملف (تم تحديثه).

---

## 2. الفجوات التي تحتاج إغلاق

### 2.1 الخطوط (Fonts) — أولوية عالية
| المتطلب | الحالة | ما هو مطلوب |
|---------|--------|-------------|
| أي شخص مفيوش الخط يتنزّل تلقائي مع الملف | **غير منفذ** | تضمين الخط في HTML كـ base64 أو تحميله من CDN/مسار محلي عند Preview/PDF، مع fallback لـ Tahoma/Arial. |
| الأدمن يقدر يبدل الخطوط | **جزئي** | حالياً dropdown فقط في `tenantSettingsPage`؛ مطلوب رفع ملف font (`woff2/ttf/otf`) وتحميله تلقائياً. |

### 2.2 الخرائط — أولوية عالية
| المتطلب | الحالة | ما هو مطلوب |
|---------|--------|-------------|
| الموظف يختار نوع الخريطة (قمر صناعي/مروري/تضاريس/هجين) | **جزئي** | لوحة اختيار `mapStylePanel` موجودة في `tenantSlidesPage` لكنها تظهر فقط عند معاينة الشرائح؛ يجب أن تكون متاحة في خطوة بيانات المشروع أيضاً وتُحفظ في `project_data`. |
| كتابة أسماء الطرق على الخريطة | **جزئي** | `maps_service.py` يعرض labels عبر Google Static Map styles؛ لكن الطرق الرئيسية المُدخلة يدوياً (`main_roads`) لا تُكتب فوق الصورة. مطلوب overlay بنص عربي. |
| ثبات النتيجة | **يحتاج تحسين** | إضافة cache للخرائط حسب `lat,lng,maptype,zoom` + إمكانية re-generate بنفس الإعدادات. |

### 2.3 الثيم والأيقونات — أولوية عالية
| المتطلب | الحالة | ما هو مطلوب |
|---------|--------|-------------|
| الثيم يتطبق في كل حاجة | **جزئي** | `build_design_rules()` يبني system prompt ديناميكي، لكن `app.py` لا يزال يحتوي `DESIGN_RULES` hardcoded في `SLIDE_DEFS` و `api_generate`. يجب توحيد المصدر. |
| الأيقونات لا تبدو كإيموجي | **جزئي** | `design_templates.py` يمنع Emojis، لكن لا يوجد post-process يتحقق من أن الشرائح النهائية لا تحتوي Emojis. |

### 2.4 تدريب الـ AI وربطه بالمدخلات — أولوية عالية جداً
| المتطلب | الحالة | ما هو مطلوب |
|---------|--------|-------------|
| التدريب يفهم الأوامر (بدون فوتر/لوجو في النص/إلخ) | **جزئي** | `training_context` يُضاف لـ system prompt؛ لكن لا يوجد chat تفاعلي لتوضيح التأثير. |
| الـ AI يبني صفحة المدخلات بنفسه | **غير منفذ** | حالياً الأدمن يضيف الحقول يدوياً. المطلوب: chat مع AI يقترح الحقول، والأدمن يوافق/يرفض/يضيف، ثم AI ينشئ الحقول في DB. |
| ربط المدخلات بالتدريب | **غير منفذ** | يجب أن يقرأ AI من `tenant_training_data` ليعرف اقتراحات الحقول المناسبة لكل شركة. |

### 2.5 الصفحات والعرض — أولوية متوسطة
| المتطلب | الحالة | ما هو مطلوب |
|---------|--------|-------------|
| Top bar منظم | **يحتاج تحسين** | الـ `tenant-topbar` به أزرار كثيرة جداً في الهاتف/الشاشات الصغيرة؛ تحتاج لـ dropdown menu. |
| صفحة المدخلات مقسّمة أقسام واضحة | **جزئي** | `tenantProjectForm` يولّد الحقول حسب `section_key` لكن لا يوجد عرض collapsible/ tabs واضحة. |
| AI يقسّم المدخلات (عنوان/جداول مالية/إلخ) | **غير منفذ** | مطلوب أن يقترح AI تقسيم الأقسام أثناء بناء صفحة المدخلات. |

### 2.6 نظام الصلاحيات — أولوية متوسطة
| المتطلب | الحالة | ما هو مطلوب |
|---------|--------|-------------|
| SAG تتحكم في الشركات | **منفذ** | `tenantAdminPage` + `/api/admin/tenants`. |
| أدمن الشركة يتحكم في الثيم/الخط/اللوجو | **منفذ** | `tenantSettingsPage`. |
| أدمن الشركة يرفع ملف font | **غير منفذ** | يجب إضافة upload font في settings + `font_family` يقبل custom value. |
| أدمن الشركة تدريب النموذج عبر chat | **غير منفذ** | صفحة `tenantTrainingPage` هي form بسيط؛ مطلوب chat ذكي يشرح التأثير. |
| أدمن يدي/يمنع صلاحيات الموظفين | **منفذ** | `tenantUsersPage` + `/api/users/<id>/permissions` + `/api/users/<id>/field-sections`. |
| الموظف يشوف من عدّل على العرض | **منفذ** | `presentation_versions` + `edit_log`. |
| تعميد النسخ | **منفذ** | `presentation_approvals`. |

### 2.7 نظام التوليد (Generation Pipeline) — أولوية عالية جداً
| المتطلب | الحالة | ما هو مطلوب |
|---------|--------|-------------|
| 1. حقول الإدخال | **منفذ جزئي** | الحقول الديناميكية موجودة، لكن AI لا يبنيها بعد. |
| 2. توليد الهيكل + الموافقة/تعديل | **منفذ** | `tenantSlidePlanPage` تعرض خطة الشرائح وتسمح بإضافة/تعديل. |
| 3. توليد الصورة الأساسية + الموافقة | **جزئي** | `/api/generate-images` يولد cover + moodboard ولكن لا توجد شاشة موافقة مخصصة قبل التوليد. |
| 4. توليد Moodboard (عدد صور متغير) | **غير منفذ** | `api_generate_images` و `SLIDE_DEFS` يفترضان 4 صور دائماً. الأدمن لا يتحكم في العدد، ولا يمكنه منح صلاحية تعديل العدد للموظفين. |
| 5. توليد الشرائح (عدد متغير) | **جزئي** | `slide_engine.py` يدعم min/max slides، لكن `SLIDE_DEFS` في `app.py` ثابت 16 شريحة. |
| 6. شات ذكي لتعديل الشرائح | **غير منفذ** | `editSlideHtml()` تعديل HTML يدوي فقط. المطلوب: chat يفهم "غيّر خط/لون/صورة/خريطة/أيقونة". |
| 7. التصدير + التعميد | **منفذ** | `/api/export` + approvals. |

---

## 3. خطة التنفيذ المرحلية

### المرحلة A: أساسيات الجودة والاستقرار (أسبوع 1)
1. **توحيد نظام الخطوط**
   - إزالة `DESIGN_RULES` الثابت من `app.py` وجعل كل التوليد يستخدم `build_design_rules(branding)`.
   - إضافة `font_upload` endpoint وتحديث `tenantSettingsPage` ليرفع ملف font.
   - تضمين الخط في HTML preview/PDF كـ base64 من `uploads/fonts` مع fallback.
2. **تحسين الخرائط**
   - إضافة overlay بأسماء الطرق الرئيسية/الفرعية على `map_access`.
   - cache للخرائط في `map_images` باستخدام hash الإعدادات.
   - السماح باختيار نوع الخريطة في `tenantProjectPage` (وليس فقط في preview).
3. **تطبيق الثيم والأيقونات**
   - تفعيل `build_design_rules` في كل النقاط (`/api/generate`, `/api/designer-generate`, `/api/export`).
   - إضافة post-process في `slide_engine.py` يتحقق من عدم وجود Emojis ويستبدلها بـ SVG placeholder.

### المرحلة B: AI يبني المدخلات والشرائح (أسبوع 2–3)
4. **chat لبناء حقول المدخلات**
   - صفحة جديدة أو تبويب في `tenantFieldsPage`: AI Input Builder.
   - الـ AI يقرأ `tenant_training_data` + industry ويقترح أقسام وحقول.
   - الأدمن يوافق/يرفض/يعدل، ثم تُكتب الحقول لـ `tenant_input_fields`.
5. **تدريب GLM عبر chat**
   - تحويل `tenantTrainingPage` من form لـ chat يشرح "كل تعديل هنا يؤثر على جودة العرض".
   - أمثلة جاهزة: "اللوجو يكون في النص"، "بدون فوتر"، "أقل عدد شرائح 12".
6. **التحكم في عدد صور Moodboard**
   - إضافة `moodboard_count` في `tenant_branding` و `project_data`.
   - تعديل `/api/generate-images` لتوليد عدد متغير.
   - صلاحية `change_moodboard_count` للموظفين.

### المرحلة C: الشات الذكي والتوليد المرن (أسبوع 3–4)
7. **شات تعديل الشرائح (Slide AI Chat)**
   - في `tenantSlidesPage`: لوحة chat على اليمين/الشمال ترى الشرائح الحالية.
   - الأوامر: تغيير خط، لون، مكان لوجو، إضافة/حذف صورة، تغيير خريطة، تغيير أيقونة، إلخ.
   - تطبيق التعديل على `tenantSlidesData[i].html` مع `edit_log`.
8. **توليد مرن بعدد شرائح متغير**
   - تحديث `SLIDE_DEFS` أو استبداله بـ `slide_plan` ديناميكي في `api_designer_generate`.
   - AI يلتزم بـ `min_slides`/`max_slides` و `default_slide_count` من Branding.
9. **إعادة تنظيم Top bar**
   - تصغير الأزرار وإضافة dropdown للأدوات، خاصة على الموبايل.

### المرحلة D: التصدير والنشر (أسبوع 4–5)
10. **التصدير النهائي**
    - التأكد من أن PDF/PPTX يحملان الخط المخصص والثيم.
    - إضافة علامة مائية/بيانات التعميد في التصدير.
11. **الاختبار والنشر**
    - اختبار end-to-end: تسجيل شركة → branding → حقول → خريطة → توليد → تعديل → تصدير.
    - نشر على `sagdemo.site:2083`.

---

## 4. الـ Todo التفصيلي

### أولوية عالية
- [ ] **F1** — توحيد مصدر قواعد التصميم: إزالة `DESIGN_RULES` الثابت من `app.py`.
- [ ] **F2** — دعم رفع ملفات الخطوط (`woff2/ttf/otf`) في `tenantSettingsPage` + `/api/branding`.
- [ ] **F3** — تضمين الخط المرفوع تلقائياً في Preview/PDF/PPTX مع fallback.
- [ ] **M1** — إضافة overlay لأسماء الطرق على `map_access` باستخدام `main_roads`/`secondary_roads`.
- [ ] **M2** — cache للخرائط في `map_images` لمنع التكرار وضمان الاستقرار.
- [ ] **M3** — نقل اختيار نوع الخريطة لـ `tenantProjectPage` وحفظه في `project_data`.
- [ ] **I1** — post-process يمنع Emojis ويستبدلها بـ SVG inline في `slide_engine.py`.
- [ ] **G1** — جعل عدد صور Moodboard متغير وتحكم به من الأدمن (`moodboard_count`).
- [ ] **G2** — جعل عدد الشرائح يتبع `default_slide_count`/`min_slides`/`max_slides` بدلاً من 16 ثابت.
- [ ] **G3** — شاشة موافقة على الصورة الأساسية قبل توليد باقي الشرائح.

### أولوية متوسطة
- [ ] **A1** — بناء chat ذكي لتوليد حقول المدخلات من `tenant_training_data`.
- [ ] **A2** — تحويل `tenantTrainingPage` لـ chat تفاعلي مع أمثلة جاهزة.
- [ ] **U1** — إعادة تنظيم `tenant-topbar` بـ dropdown menu.
- [ ] **U2** — تقسيم `tenantProjectPage` لأقسام collapsible/tabs بوضوح.
- [ ] **C1** — شات تعديل الشرائح (خط، لون، لوجو، صور، خرائط، أيقونات).

### أولوية منخفضة / نشر
- [ ] **D1** — إضافة علامة مائية/بيانات التعميد في PDF/PPTX.
- [ ] **D2** — اختبار end-to-end كامل ونشر على `sagdemo.site:2083`.

---

## 5. ملاحظات النشر

- بيانات الاستضافة (cpanel) كانت في نسخة `todo.md` القديمة؛ يجب حفظها في `.env` أو ملف آمن خارج الـ repo.
- `GOOGLE_MAPS_API_KEY` و `ZAI_KEY` / `OPENROUTER_KEY` يجب أن تكون في `.env` وليس في الكود.
- جميع التعديلات يجب أن تُختبر محلياً أولاً باستخدام `python app.py` ثم `node server.js`.

---

*آخر تحديث: 15 يوليو 2026 — بناءً على `needed.md`.*
