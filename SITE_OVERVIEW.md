# التوثيق الشامل للمنصة — Manafe / LandLoom

منصة SaaS متعددة الشركات (multi-tenant) لتوليد **العروض التقديمية وملفات الاستثمار
العقارية** بالذكاء الاصطناعي، موجّهة للسوق السعودي وعربية أولاً. كل شركة (tenant)
لها مستخدمون وصلاحيات ومحفظة دفع وهوية بصرية خاصة، وتنتج المنصة عرضاً تقديمياً
كاملاً (غلاف، فهرس، أقسام، خاتمة) قابلاً للتصدير PDF وPPTX، مع دراسة مالية،
دراسة سوق، تحليل أرض وكروكي، خرائط موقع، وتصورات بصرية مولّدة بالصور.

---

## 1. لغات البرمجة

| اللغة | الدور |
|---|---|
| **Python** (≥3.10، الإنتاج على 3.11) | الباكند كامل: Flask API، قاعدة البيانات، توليد الشرائح، الخرائط، التصدير، الفوترة |
| **JavaScript** (Vanilla، بدون framework) | الواجهة الأمامية SPA بالكامل + أدوات Node للفحص والتصدير |
| **HTML5 / CSS3** | هيكل الواجهة والشرائح المولّدة (كل شريحة HTML/CSS بمقاس 1280×720 بنسبة 16:9) |
| **SQL** | SQLite محلياً وPostgreSQL في الإنتاج عبر طبقة تجريد واحدة |
| **Bash / YAML** | سكربتات النشر (`deploy*.sh`, `start_server*.sh`) وGitHub Actions |

---

## 2. بنية النظام والملفات الرئيسية

### الباكند (Python / Flask)

| الملف | الحجم التقريبي | الدور |
|---|---|---|
| `app.py` | ~31,300 سطر | التطبيق الرئيسي: كل الـ API endpoints، استدعاءات النماذج، الوظائف الخلفية، الفوترة |
| `db.py` | ~14,600 سطر | طبقة قاعدة البيانات كاملة: إنشاء الجداول، migrations، كل الاستعلامات |
| `db_driver.py` | ~400 سطر | shim يجعل نفس الكود يعمل على SQLite أو Postgres حسب `DATABASE_URL` |
| `slide_engine.py` | ~11,600 سطر | محرك الشرائح: بناء "حقائق المشروع" للبرومبت، تطبيع الخطة، إعادة الترقيم، تنظيف HTML |
| `maps_service.py` | ~4,600 سطر | كل خدمات Google Maps: صور الخرائط، الطرق، المعالم، تراكب الحدود والأسماء العربية (Pillow) |
| `market_study.py` | ~2,100 سطر | منطق دراسة السوق: أولويات المصادر، الجداول، البحث الموجّه |
| `change_tracking.py` | ~1,100 سطر | توليد سطور سجل التغييرات «من غيّر ماذا» بالعربي |
| `design_templates.py` | ~1,100 سطر | قوالب التصميم وتباين الألوان (4.5:1) |
| `executive_content.py` | ~600 سطر | توليد كتل المحتوى التنفيذي من حقائق الأقسام السابقة |
| `regulation_digest.py` | ~400 سطر | خلاصة اشتراطات البناء الجاهزة (`rules/`) بدون إعادة قراءة الـ PDFs |
| `auth.py` | ~430 سطر | JWT (HMAC) + PBKDF2 لتجزئة كلمات المرور، الصلاحيات، signed download tokens |
| `designer_chat_*.py` | ~4 ملفات | موثوقية/أمان/سياق/ألوان شات المصمم |
| `exports/pptx_export.py` | ~2,900 سطر | تصدير PPTX أصلي بـ python-pptx بدون متصفح |
| `generate_pdf_from_preview.py`, `pdf_generator*.py` | — | مسارات تصدير PDF (Chromium أساسي + PyMuPDF احتياطي) |
| `sitecustomize.py` | — | startup hook يُحقن في site-packages داخل Docker |

### الواجهة الأمامية (SPA)

- `index.html` — شِل نحيف (~1,680 سطر): markup + مراجع الموارد فقط، لا كود مضمّن.
- `assets/js/00-core.js` … `19-notifications.js` — 20 ملفاً مرتباً، كلاسيكية (بدون
  modules)، تشترك في scope واحد. `assets/i18n.js` يُحمّل قبلها (عربي/إنجليزي).
- `assets/css/base.css` + `project-form.css`.
- الخادم يقدّمها كحزمتين (`/assets/app.bundle.js` و`.css`) بدمج الملفات حسب
  `FRONTEND_*_ORDER` في `app.py` مع ETag — لا يوجد build step.
- `node scripts/verify-frontend.js` يحرس التوصيل (الترتيب، لا ملفات يتيمة،
  `node --check` لكل ملف وللحزمة المدموجة).

### أقسام ملف المشروع (بالترتيب)

`basic → location → land_croquis → timeline → financial → team → market study →
visual concept → executive content → contact`

وترتيب العرض المولّد ثابت: نبذة → مكونات → تحليل الأرض → الموقع الجغرافي → السوق →
الجدول الزمني → المالية → SWOT والمخاطر → الفريق → المخططات → تصورات خارجية →
داخلية → ملخص تنفيذي → خاتمة. عدد الشرائح مفتوح (حد أدنى فقط) ويقرره المخطط.

---

## 3. نماذج الذكاء الاصطناعي وأدوارها

كل التوليد يمر عبر **OpenRouter** (`call_zai_chat` / `call_openrouter_chat` /
`call_images_api`). لكل شركة مفتاح OpenRouter خاص بحد إنفاق يُدار آلياً عبر
Management API ويُزامَن مع رصيد المحفظة؛ وعند غيابه تُستخدم المفتاح العام.

| النموذج | الثابت في الكود | الدور |
|---|---|---|
| `google/gemini-3.8-flash` | `GEMINI_TEXT_MODEL` (والأسماء القديمة `LUNA_TEXT_MODEL`/`GLM_MODEL`) | **النموذج النصي السريع الافتراضي** لكل ما لا يحتاج النموذج الكبير |
| `openai/gpt-5.6-sol` | `SLIDE_TEXT_MODEL` (env) | توليد شرائح HTML، شات المصمم، وكيل الإدارة |
| `openai/gpt-image-2.5-sunburst` | `IMAGE_MODEL` / `VISUAL_CONCEPT_IMAGE_MODEL` (env) | توليد الصور: الغلاف، الزوايا الخارجية، الداخلية |
| `google/gemini-3.1-flash-image-preview` | `reference_analyzer.VISION_MODEL` | تحليل صور المرجع البصري التي يرفعها العميل |
| `openrouter:web_search` (محرك `exa`) | أداة server-side | بحث ويب حي باستشهادات لدراسة السوق |

### توزيع الأدوار بالتفصيل

- **`gemini-3.8-flash` — التحليل والتخطيط:**
  - تحليل مستندات الأرض والكروكي (vision على صفحات PDF + نصوص الاشتراطات)،
    مع مشيئة سقف `max_tokens` وإعادة المحاولة عند القصّ (`LAND_ANALYSIS_MODEL`).
  - تحليل الموقع (`/api/analyze-site`).
  - دراسة السوق: المنافسون والملخص (`MARKET_STUDY_MODEL`) مع أداة البحث —
    JSON mode يُطفأ في المحاولة الأولى لأن إقرانه بالأداة يرجع محتوى فارغاً.
  - خطة الشرائح `/api/slide-plan`: طلب واحد محدود بـ 12k token / 75 ثانية داخل
    job في الخلفية حتى لا يقتله Gunicorn.
  - كتل المحتوى التنفيذي (brief/opportunity/features/risks/summary) بـ
    `reasoning_effort='low'` وJSON mode.
  - تخطيط برومبتات صور التصور البصري.
- **`gpt-5.6-sol` — الإنشاء الدقيق:**
  - توليد كل شريحة HTML على حدة (`/api/generate-slide-single`)، مع streaming
    وتنسيق أرقام وتحقق تباين.
  - شات المصمم `/api/designer-chat`: مخطط + محرر بذاكرة محادثة (10 أدوار حرفية
    ثم ملخص)، وأدوات تنفيذ على الشرائح.
  - وكيل الإدارة `/api/training-chat` بـ `reasoning_effort='medium'` لأنه يغيّر
    إعدادات الشركة، وأدواته تعيد فحص صلاحية الطالب (`AGENT_TOOL_PERMISSIONS`).
- **`gpt-image-2.5-sunburst` — الصور:** الغلاف (مع مراجع أسلوب وخريطة الموقع)،
  زوايا التصور الخارجي (يستلم الغلاف المعتمد كمرجع)، والصور الداخلية لكل مكوّن.
- **`gemini-3.1-flash-image-preview`:** قراءة صور «المرجع البصري» المرفوعة ووصفها
  قبل استخدامها في توليد الصور.

### قياس الإنفاق

كل استدعاء يُسجَّل في `ai_usage_events` (توكنات + تكلفة `/generation`) وكل استدعاء
خرائط في `map_usage_events` (وحدات × أسعار SKU) — منسوبة لكل tenant/draft/
presentation وتُقدَّم عبر `GET /api/ai-usage`.

---

## 4. الخدمات الخارجية

| الخدمة | الاستخدام |
|---|---|
| **OpenRouter** | كل توليد النصوص والصور + إدارة مفاتيح الشركات وحدود الإنفاق |
| **Google Maps Platform** | Static Maps، Places (New)، Distance Matrix، Street View Static، Geocoding، Roads، Directions — بمفتاح واحد مقيّد ومعدّل استهلاك لكل tenant |
| **BigQuery** (`population_service.py`) | كثافة سكانية اختيارية — لا تقدير بدون إعداد |
| **SMTP** | بريد عبر طابور `email_outbox` (لا إرسال inline) |
| **OpenStreetMap** | بصمة المبنى/القطعة كمصدر احتياطي لحدود الموقع |

---

## 5. المكتبات

### Python (`requirements.txt`)

- **الويب:** `flask`, `gunicorn` (عامل واحد × 8 threads × 300s), `requests`,
  `tenacity`, `pydantic`, `python-dotenv`, `PyYAML`.
- **المستندات:** `PyMuPDF (fitz)`، `pypdf`، `python-docx`، `python-pptx`،
  `reportlab`، وLibreOffice نظامياً لبعض التحويلات.
- **العربية والصور:** `arabic_reshaper`, `python-bidi`, `Pillow`, `numpy`,
  `fontTools`, `emoji`.
- **المتصفح:** `playwright` (Chromium headless لطباعة PDF).
- **الأمان وقاعدة البيانات:** `pyjwt`, `cryptography`, `psycopg2-binary`.
- **موجودة في المتطلبات وغير مستخدمة حالياً:** `replicate`, `google-genai`, `openai`
  (الاتصال بـ OpenRouter يتم بـ `requests` مباشرة).

### Node (`package.json`)

`express`, `pdf-lib`, `pptxgenjs`, `playwright`, `pm2`, `acorn`/`acorn-walk` —
تُستخدم في أدوات الفحص والتصدير الجانبية (`scripts/verify-frontend.js`,
`pdf_engine.js` القديم)، وليس في مسار التشغيل الرئيسي.

---

## 6. قاعدة البيانات

- **SQLite** ملف محلي افتراضياً، و**PostgreSQL** تلقائياً عند وجود `DATABASE_URL`
  — نفس `db.py` على الاثنين عبر `db_driver.py`، وكل الجداول `IF NOT EXISTS`
  ومigrations مضافة (`ALTER TABLE` محروس بـ `PRAGMA table_info`).
- **الجداول المحورية:** `tenants`, `users`, `project_drafts`, `presentations`,
  `project_files`, `tenant_team_entities`, `change_log` (سجل «من غيّر ماذا»)،
  `section_versions` وسلاسل نسخ غير قابلة للكتابة، `tenant_ledger` (محفظة USD)،
  `billing_packages`, `recharge_requests`, `ai_usage_events`, `map_usage_events`,
  `job_queue`, `email_outbox`, `audit_events` (append-only بمشغّلات تمنع
  UPDATE/DELETE)، `notification_deliveries`.
- العزل بين الشركات بـ `tenant_id` على كل صف + استعلامات مقيّدة؛ السوبر أدمن يرى
  عدّادات وبيانات وصفية فقط، لا محتوى العملاء.

---

## 7. الأنظمة الفرعية الكبرى

- **المصادقة والصلاحيات:** JWT في `auth.py`، `require_auth`/`require_admin`/
  `require_permission` يقرأ الصف الحي كل طلب (إيقاف شركة = فقدان فوري للوصول)،
  slugs ثابتة مع `tenant_slug_redirects`، وروابط تنزيل موقّعة قصيرة العمر.
- **المحفظة والفوترة:** `tenant_ledger` (debit/credit بالدولار)، الفاتورة = تكلفة
  المزود × `BILLING_MULTIPLIER` (1.6)، checkout ذرّي (claim + debit + commit واحد،
  `InsufficientBalance` → HTTP 402)، شحن باقات فقط من كتالوج يملكه السوبر أدمن،
  ومزامنة حد مفتاح OpenRouter = (الرصيد + الحجوزات + الباقة) ÷ المعامل.
- **الخرائط:** حد الموقع من إحداثيات الكروكي (UTM→lat/lng) لا من Google؛ أربع
  خرائط (overview → access → catchment → landmarks) باعتمادات متسلسلة، تحرير
  محلي للحدود/الدبابيس/الأسماء بدون استدعاء مزود، وأسماء طرق عربية بلا تشكيل
  مرسومة بـ Pillow وخط `fonts/arabic-overlay.bin`.
- **الأرض والكروكي:** job خلفي (`/api/extract-croquis` + polling)، حقول من
  `PREBUILT_FIELDS` في `db.py`، تواريخ هجرية كنص، وخلاصة `rules/` الجاهزة بدل
  إعادة قراءة الاشتراطات.
- **الدراسة المالية:** أرقام تُنسخ ولا تُولَّد؛ الجدول الزمني هو المصدر لسنوات
  التطوير والمراحل؛ PDF أحادي اللون يحفظ تسميات الشاشة؛ أرقام في خلايا `dir=ltr`.
- **التصدير:** Chromium يطبع كل شريحة في `.pdf-export-page` موثوق (مجموعات 10 فوق
  25 شريحة) ثم دمج + تحقق عدد الصفحات (`_verify_pdf_page_count` يرفع الخطأ بدل
  تسليم ملف ناقص)؛ بديل PyMuPDF متدهور التخطيط؛ PPTX أصلي مع نفس ضمان العدد.
- **الخطوط:** وجه لكل tenant تحت alias، CSS مضمّن في المعاينة والتصدير، حزمة
  `fonts_bundle.json`، وملفات `fonts/*.bin` غير LFS للرسم على الخادم.
- **سجل التغييرات:** `change_log` موحّد للعروض وملفات المشاريع، سطور عربية
  («الدراسة المالية › جدول المكونات › …») من `change_tracking.py`.
- **الوظائف الخلفية:** `job_queue` durable + مخازن ملفات (`.plan_jobs`,
  `.market_jobs`) + `email_outbox` + خيط housekeeping دوري (outbox، تذكيرات،
  SLA، كنس الحجوزات والوظائف البائتة).
- **النسخ الاحتياطي:** `scripts/backup_db.py` (مشفّر ومضغوط، `backup_history`) مع
  فحص استعادة `restore_check.py` — RPO 24h / RTO 4h.
- **i18n:** `assets/i18n.js` (قاموسا AR/EN + `WFT()`/`data-i18n`)، العرض نفسه يتبع
  لغة البيانات (`detect_offer_lang`) لا لغة الواجهة.
- **الأمان:** عزل tenant في كل مسار، `audit_events` append-only، فحص ملفات
  `scan_status` hook، حماية SSRF في استيراد شعارات المنافسين، gzip + تقطيع
  الطلبات الكبيرة (`/api/body-chunk`) لأن بروكسي الاستضافة يفسد ما فوق ~40KB.

---

## 8. الاستضافة والنشر

- **الإنتاج الحالي:** استضافة cPanel/Passenger على `landloom.ai` (الجذر صفحة
  ثابتة — التطبيق على subdomain). مكتبات Chromium الناقصة تُحمَّل جانبياً في
  `~/chromium-libs` عبر `scripts/rootless_rpm_extract.py` وتُكشف بـ `LD_LIBRARY_PATH`.
- **Staging:** `test.landloom.ai` — كل push على `lab` يشغّل
  `.github/workflows/deploy-staging.yml` الذي ينادي webhook على الخادم
  (`deploy-staging.sh` → clone + `.env` + restart).
- **Production:** `deploy.yml` يدوي فقط (`workflow_dispatch`).
- **بدائل جاهزة:** `Dockerfile` (python:3.11-slim + gunicorn) و`render.yaml`
  Blueprint لمنصة Render مع Postgres.
- **الأسرار:** في GitHub Actions secrets و`.env` على الخادم فقط — لا شيء في المستودع.
- التشغيل المحلي: `start.bat` / Flask مباشرة، و`/api/build` يعرض commit النسخة
  الحية و`/health?vision=1` حالة متصفح التصدير.

---

## 9. الاختبار والتحقق

- ~45 suite بـ `unittest` في `tests/` — تُشغَّل **كوحدات منفصلة** من الجذر:
  `python -m unittest tests.test_meeting_requirements` إلخ (كل suite تعيد توجيه
  `db.DB_PATH` قبل استيراد `app`).
- `node scripts/verify-frontend.js` يفحص توصيل الواجهة و`node --check` لكل ملف.
- فحص صياغة بايثون بـ `ast.parse` على الملفات الكبرى.
- `tests/test_postgres_parity.py` لا يعمل إلا بـ `TEST_DATABASE_URL` حقيقي.

---

## 10. نماذج الذكاء الاصطناعي المستخدمة في التطوير

النماذج التي شاركت في برمجة المشروع (أسماء النماذج فقط). أكمل خانة الدور
والمساهمة لكل نموذج حسب استخدامك الفعلي له.

| النموذج | دوره في المشروع | أبرز ما ساعد فيه | ملاحظات |
|---|---|---|---|
| Gemini 3.8 Flash | الاختبارات الحيه | العثور علي المشاكل بسرعه | لا يوجد|
| GPT Astra 6 | تتبع كل المشاكل في السيستم بشكل دوري | تنبيه في حاله وجود اخطاء مخفيه | لا يقوم بتعديل او كتابه |
| GPT 5.6 Sol | كتابه الاكواد الجديده | كتابه بعض من ملفات الاختبار و ملفات الشرح وحتي هذا الملف | لا يوجد |
| GPT 5.6 Luna | تعديل علي الاكواد الحاليه | السرعه في تعديل الاكواد اللتي تحتاج الي سرعه في الانجاز | لا يوجد |

### توزيع العمل بين اليدوي والـ AI (تقدير تقريبي)

- **الاختبارات وتتبع المشاكل:** الجزء الأكبر يدوي — حوالي **70–80%** اختباراً
  وتتبعاً للأخطاء وتحليلاً لها، مقابل **20–30%** بمساعدة وكلاء الـ AI.
- **كتابة الأكواد الجديدة:** حوالي **60–70%** كُتبت بواسطة الـ AI، مقابل
  **30–40%** كتابة يدوية مباشرة.
- **تعديل الأكواد القائمة:** حوالي **50–60%** من التعديلات تمت عبر الـ AI،
  مقابل **40–50%** تعديل يدوي.
- **النشر على الاستضافة:** تلقائي بالكامل (auto-deploy عند كل push على فرع
  `lab`) — لا يتم يدوياً ولا عبر الـ AI.

**النسبة الإجمالية التقريبية:** بمتوسط الفئات الثلاث أعلاه — **العمل اليدوي
~50–55%** من إجمالي الشغل على المشروع، مقابل **~45–50% لوكلاء الـ AI**. التوزيع
شبه متساوٍ مع أفضلية بسيطة للعمل اليدوي بسبب الاختبارات وتتبع المشاكل.
