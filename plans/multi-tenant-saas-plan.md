# الخطة الشاملة: تحويل النظام لـ Multi-Tenant SaaS

## نظرة عامة

تحويل النظام من تطبيق لشركة واحدة ("منافع الاقتصادية للعقار") إلى منصة SaaS متعددة المستأجرين (Multi-Tenant) تُباع لعدة شركات. كل شركة تحصل على هويتها البصرية الخاصة (ألوان، لوجو، اسم، خطوط)، مدخلاتها المخصصة، وطريقة تصميم الشرائح الخاصة بها.

---

## القرارات الأساسية (مؤكدة من العميل)

| الموضوع | القرار |
|---------|--------|
| التسجيل | Self-Registration + Admin Panel (الشركستان) |
| المدخلات | حقول جاهزة قابلة للتفعيل + حقول مخصصة بالكامل |
| تصميم الشرائح | رفع صورة مرجعية + قوالب جاهزة + إعدادات متقدمة |
| عدد الشرائح | AI يقترح العدد + الشركة تقدر تعدله قبل التوليد |
| المخرجات | PDF + PPTX |
| الباك-إند | دمج كامل في Flask (app.py) — هو الـ deployment target الحالي |

---

## البنية المعمارية المستهدفة

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (index.html)                  │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────────┐  │
│  │  Login/  │  │  Company  │  │  Presentation Builder │  │
│  │  Signup  │  │  Settings │  │  (Dynamic Form +      │  │
│  │          │  │  (Branding)│  │   Preview + Export)   │  │
│  └──────────┘  └───────────┘  └──────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐    │
│  │              Admin Panel (Super Admin)            │    │
│  └──────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│              Backend (app.py - Flask only)                │
│                                                          │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │  Auth   │  │  Tenant  │  │   AI     │  │  Export  │ │
│  │  (JWT)  │  │  Config  │  │  Engine  │  │  Engine  │ │
│  │         │  │  Service │  │  (GLM +  │  │  (PDF +  │ │
│  │         │  │          │  │  Gemini) │  │  PPTX)   │ │
│  └─────────┘  └──────────┘  └──────────┘  └──────────┘ │
│         │            │             │            │       │
│         └────────────┴─────────────┴────────────┘       │
│                          │                               │
│                          ▼                               │
│              ┌─────────────────────┐                     │
│              │   SQLite Database   │                     │
│              │  (tenants, users,   │                     │
│              │  presentations,     │                     │
│              │  branding, fields)  │                     │
│              └─────────────────────┘                     │
└─────────────────────────────────────────────────────────┘
```

---

## قاعدة البيانات (SQLite)

### الجداول الأساسية

#### `tenants` (الشركات)
```sql
CREATE TABLE tenants (
    id TEXT PRIMARY KEY,              -- UUID
    company_name TEXT NOT NULL,
    subdomain TEXT UNIQUE,            -- e.g. "manafe" → manafe.app.com
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    plan TEXT DEFAULT 'free',         -- free, pro, enterprise
    is_active BOOLEAN DEFAULT 1,
    is_admin BOOLEAN DEFAULT 0,       -- super admin flag
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    settings_json TEXT                -- JSON: advanced settings
);
```

#### `tenant_branding` (الهوية البصرية لكل شركة)
```sql
CREATE TABLE tenant_branding (
    tenant_id TEXT PRIMARY KEY REFERENCES tenants(id),
    -- الألوان
    primary_color TEXT DEFAULT '#7A0C0C',
    secondary_color TEXT DEFAULT '#5A0808',
    accent_color TEXT DEFAULT '#C4A35A',
    background_color TEXT DEFAULT '#FBFAF8',
    text_color TEXT DEFAULT '#333333',
    -- الهوية
    logo_path TEXT,                   -- مسار اللوجو المرفوع
    company_name TEXT,                -- اسم الشركة (للفوتر والهيدر)
    tagline TEXT,                     -- وصف مختصر
    -- الخطوط
    font_family TEXT DEFAULT 'The Sans Arabic',
    font_arabic TEXT DEFAULT 'The Sans Arabic',
    -- التصميم
    design_template TEXT DEFAULT 'modern',  -- modern, classic, minimal, luxury
    reference_image_path TEXT,        -- صورة مرجعية يرفعها العميل
    -- إعدادات متقدمة
    header_enabled BOOLEAN DEFAULT 1,
    footer_enabled BOOLEAN DEFAULT 1,
    header_height INTEGER DEFAULT 56,
    footer_height INTEGER DEFAULT 36,
    card_style TEXT DEFAULT 'bordered',     -- bordered, shadow, flat, gradient
    slide_ratio TEXT DEFAULT '16:9',        -- 16:9, 4:3
    -- الصور
    moodboard_enabled BOOLEAN DEFAULT 1,
    cover_image_enabled BOOLEAN DEFAULT 1,
    -- الإعدادات العامة
    default_slide_count INTEGER DEFAULT 16,
    min_slides INTEGER DEFAULT 8,
    max_slides INTEGER DEFAULT 30,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `tenant_input_fields` (الحقول المخصصة لكل شركة)
```sql
CREATE TABLE tenant_input_fields (
    id TEXT PRIMARY KEY,
    tenant_id TEXT REFERENCES tenants(id),
    field_key TEXT NOT NULL,          -- e.g. "project_name", "budget", "custom_roi"
    field_label TEXT NOT NULL,        -- الاسم المعروض بالعربي
    field_type TEXT NOT NULL,         -- text, number, textarea, select, date, image
    field_options TEXT,               -- JSON: options for select type
    is_required BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    is_custom BOOLEAN DEFAULT 0,      -- 0 = pre-built, 1 = custom
    sort_order INTEGER DEFAULT 0,
    placeholder TEXT,
    default_value TEXT,
    ai_hint TEXT,                     -- تلميح للـ AI عن هذا الحقل
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `tenant_slide_templates` (قوالب الشرائح المخصصة)
```sql
CREATE TABLE tenant_slide_templates (
    id TEXT PRIMARY KEY,
    tenant_id TEXT REFERENCES tenants(id),
    slide_type TEXT NOT NULL,         -- cover, index, content, moodboard, closing, custom
    slide_name TEXT NOT NULL,         -- اسم الشريحة
    design_instructions TEXT,         -- وصف تصميم الشريحة (يُحقن في الـ prompt)
    is_active BOOLEAN DEFAULT 1,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `presentations` (العروض المُنشأة)
```sql
CREATE TABLE presentations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT REFERENCES tenants(id),
    title TEXT NOT NULL,
    project_data TEXT,                -- JSON: بيانات المشروع
    slides_data TEXT,                 -- JSON: بيانات الشرائح
    slide_count INTEGER,
    status TEXT DEFAULT 'draft',      -- draft, completed, exported
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `exports` (الملفات المُصدّرة)
```sql
CREATE TABLE exports (
    id TEXT PRIMARY KEY,
    presentation_id TEXT REFERENCES presentations(id),
    tenant_id TEXT REFERENCES tenants(id),
    format TEXT NOT NULL,             -- pdf, pptx
    file_path TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Phase 1: Database & Auth Layer

### 1.1 إعداد قاعدة البيانات
- إنشاء `db.py` — إدارة SQLite connection و migrations
- إنشاء جميع الجداول المذكورة أعلاه
- Seed: مستخدم Admin افتراضي

### 1.2 نظام المصادقة (JWT)
- `auth.py` — تسجيل، دخول، JWT tokens
- **Endpoints:**
  - `POST /api/auth/register` — شركة جديدة تسجل
  - `POST /api/auth/login` — دخول
  - `POST /api/auth/logout` — خروج
  - `GET /api/auth/me` — بيانات الشركة الحالية
  - `POST /api/auth/refresh` — تجديد الـ token
- **Middleware:** `require_auth()` — يتحقق من JWT ويحقن `tenant_id` في `g.tenant_id`
- **Middleware:** `require_admin()` — يتحقق من `is_admin` flag

### 1.3 رفع الملفات
- `POST /api/upload/logo` — رفع لوجو الشركة
- `POST /api/upload/reference-image` — رفع صورة مرجعية للتصميم
- الملفات تُحفظ في `uploads/{tenant_id}/`

---

## Phase 2: Tenant Branding System

### 2.1 إدارة الهوية البصرية
- **Endpoints:**
  - `GET /api/branding` — جلب إعدادات الهوية للشركة الحالية
  - `PUT /api/branding` — تحديث الألوان، الاسم، اللوجو، الخطوط
  - `POST /api/branding/template` — اختيار قالب تصميم جاهز
  - `POST /api/branding/reference` — رفع صورة مرجعية وتحليلها

### 2.2 قوالب التصميم الجاهزة
```python
DESIGN_TEMPLATES = {
    'modern': {
        'name': 'مودرن',
        'card_style': 'bordered',
        'header_style': 'minimal',
        'use_gradients': False,
        'icon_style': 'unicode',
    },
    'classic': {
        'name': 'كلاسيك',
        'card_style': 'shadow',
        'header_style': 'ornate',
        'use_gradients': True,
        'icon_style': 'unicode',
    },
    'minimal': {
        'name': 'مينيمال',
        'card_style': 'flat',
        'header_style': 'none',
        'use_gradients': False,
        'icon_style': 'none',
    },
    'luxury': {
        'name': 'فاخر',
        'card_style': 'gradient',
        'header_style': 'ornate',
        'use_gradients': True,
        'icon_style': 'unicode',
    },
}
```

### 2.3 تحليل الصورة المرجعية
- لما العميل يرفع صورة مرجعية، الـ AI (Gemini Vision) يحللها ويستخرج:
  - لوحة الألوان السائدة
  - نمط التصميم (مودرن/كلاسيك/الخ)
  - نوع التخطيط
- النتيجة تُحقن في الـ design prompt كـ "style reference"

### 2.4 بناء DESIGN_RULES ديناميكياً
```python
def build_design_rules(tenant_branding):
    """Build DESIGN_RULES from tenant's branding settings instead of hardcoded."""
    return f"""أنت مصمم عروض تقديمية احترافية لشركة "{tenant_branding.company_name}".

## الألوان
- رئيسي: {tenant_branding.primary_color}
- ثانوي: {tenant_branding.secondary_color}
- مميز: {tenant_branding.accent_color}
- خلفية: {tenant_branding.background_color}
- نص: {tenant_branding.text_color}

## الخط
font-family: '{tenant_branding.font_family}', Arial, sans-serif

## الهيدر والفوتر
{'هيدر إلزامي' if tenant_branding.header_enabled else 'بدون هيدر'}
{'فوتر إلزامي' if tenant_branding.footer_enabled else 'بدون فوتر'}
اسم الشركة في الفوتر: {tenant_branding.company_name}

## القالب
النمط: {tenant_branding.design_template}
نوع البطاقات: {tenant_branding.card_style}
"""
```

---

## Phase 3: Dynamic Input Fields

### 3.1 الحقول الجاهزة (Pre-built Fields)
```python
PREBUILT_FIELDS = [
    {'key': 'project_name', 'label': 'اسم المشروع', 'type': 'text', 'required': True, 'ai_hint': 'اسم المشروع الرئيسي'},
    {'key': 'project_type', 'label': 'نوع المشروع', 'type': 'select', 'options': ['سكني', 'تجاري', 'صناعي', 'سياحي', 'زراعي'], 'ai_hint': 'نوع المشروع العقاري'},
    {'key': 'location', 'label': 'الموقع', 'type': 'text', 'ai_hint': 'الموقع الجغرافي للمشروع'},
    {'key': 'budget', 'label': 'الميزانية', 'type': 'text', 'ai_hint': 'الميزانية الإجمالية'},
    {'key': 'target_audience', 'label': 'الجمهور المستهدف', 'type': 'textarea', 'ai_hint': 'الفئة المستهدفة من العرض'},
    {'key': 'roi', 'label': 'العائد المتوقع', 'type': 'text', 'ai_hint': 'نسبة العائد على الاستثمار'},
    {'key': 'timeline', 'label': 'الجدول الزمني', 'type': 'textarea', 'ai_hint': 'مراحل المشروع والمدد الزمنية'},
    {'key': 'description', 'label': 'وصف المشروع', 'type': 'textarea', 'ai_hint': 'وصف تفصيلي للمشروع'},
    # ... حقول إضافية
]
```

### 3.2 إدارة الحقول
- **Endpoints:**
  - `GET /api/fields` — جلب كل حقول الشركة (جاهزة + مخصصة)
  - `POST /api/fields` — إضافة حقل مخصص
  - `PUT /api/fields/:id` — تعديل حقل
  - `DELETE /api/fields/:id` — حذف حقل
  - `PUT /api/fields/reorder` — ترتيب الحقول
  - `POST /api/fields/toggle/:id` — تفعيل/تعطيل حقل جاهز

### 3.3 بناء الفورم ديناميكياً في الـ Frontend
- الـ Frontend يطلب `/api/fields` ويرسم الفورم بناءً على النتيجة
- كل حقل يُرسم حسب `field_type` (text, number, textarea, select, date, image)
- الحقول المخصصة تظهر بنفس طريقة الجاهزة

---

## Phase 4: Dynamic Slide Count & Content Distribution

### 4.1 تحليل المحتوى واقتراح عدد الشرائح
```python
def analyze_content_and_propose_slides(project_data, tenant_branding):
    """
    AI يحلل بيانات المشروع ويقترح:
    - عدد الشرائح المناسب
    - عناوين الشرائح
    - توزيع المحتوى
    """
    prompt = f"""
أنت خبير في تحليل المحتوى وتوزيعه على شرائح العروض التقديمية.

بيانات المشروع:
{json.dumps(project_data, ensure_ascii=False)}

المهمة:
1. حلل كمية ونوع المحتوى المتاح
2. اقترح عدد شرائح مناسب (بين {tenant_branding.min_slides} و {tenant_branding.max_slides})
3. وزع المحتوى بحيث:
   - لا توجد شريحة بكلمتين فقط (فارغة بصرياً)
   - لا توجد شريحة مزدحمة بالكلام
   - كل شريحة لها فكرة واحدة واضحة
   - المحتوى المالي/الرقمي في شرائح منفصلة (dashboard style)
   - المحتوى الوصفي في شرائح بطاقات (card style)

أعد JSON:
{{
  "proposed_count": <عدد الشرائح>,
  "reasoning": "<سبب اختيار هذا العدد>",
  "slides": [
    {{
      "title": "عنوان الشريحة",
      "type": "cover|index|content|moodboard|closing",
      "content_density": "low|medium|high",
      "design_style": "dashboard|cards|timeline|table|text|image",
      "bullets": ["نقطة 1", "نقطة 2"],
      "requires_image": true|false
    }}
  ]
}}
"""
    response = call_zai_chat(system_prompt, prompt, max_tokens=4000)
    return parse_slide_proposal(response)
```

### 4.2 قواعد توزيع المحتوى (Content Distribution Rules)
```python
CONTENT_DISTRIBUTION_RULES = """
## قواعد توزيع المحتوى (إلزامية)
1. **التوازن البصري:** كل شريحة يجب أن تكون ممتلئة بصرياً بنسبة 60-85%
2. **الحد الأدنى للمحتوى:** كل شريحة محتوى يجب أن تحتوي على:
   - عنوان واضح
   - 3-6 نقاط أساسية (bullets) أو 2-4 بطاقات (cards) أو 3-5 أرقام (metrics)
   - لا تقبل شريحة بكلمة أو كلمتين فقط
3. **الحد الأقصى للمحتوى:** لا تزدحم شريحة بأكثر من:
   - 6 bullets
   - 4 بطاقات
   - 5 metrics
4. **التقسيم الذكي:** لو المحتوى كتير لشريحة واحدة، قسمه على شريحتين
5. **الدمج الذكي:** لو المحتوى قليل لشريحة، ادمجه مع شريحة مجاورة
6. **الأنواع الإلزامية:**
   - شريحة غلاف (1) — دائماً في البداية
   - شريحة فهرس (1) — بعد الغلاف
   - شريحة ختام (1) — دائماً في النهاية
   - شريحة مود بورد (0-1) — اختياري حسب توفر الصور
   - شرائح محتوى (N) — العدد يحدده المحتوى
"""
```

### 4.3 تدفق العمل (Workflow)
```
1. المستخدم يملأ الفورم (حقول ديناميكية)
2. الضغط على "تحليل المحتوى"
3. AI يحلل ويقترح:
   - عدد الشرائح (مثلاً: 14 شريحة)
   - عناوين كل شريحة
   - نوع تصميم كل شريحة
   - كثافة المحتوى
4. المستخدم يرى الاقتراح ويمكنه:
   - الموافقة كما هو
   - زيادة/تقليل العدد
   - تعديل العناوين
   - إضافة/حذف شرائح
5. الضغط على "توليد العرض"
6. AI يولد HTML لكل شريحة بالتوزيع المتوازن
```

---

## Phase 5: Design Templates & Reference Image System

### 5.1 قوالب التصميم الجاهزة
- **modern:** بطاقات بحدود رفيعة، هيدر بسيط، أيقونات Unicode
- **classic:** بطاقات بظلال، هيدر مزخرف، تدرجات لونية
- **minimal:** بطاقات مسطحة، بدون هيدر، مساحات بيضاء كبيرة
- **luxury:** بطاقات بتدرجات، هيدر مزخرف بالذهبي، أيقونات Unicode كبيرة

### 5.2 رفع صورة مرجعية
```python
def analyze_reference_image(image_path, tenant_id):
    """
    استخدم Gemini Vision لتحليل الصورة المرجعية واستخراج:
    - لوحة الألوان
    - نمط التصميم
    - نوع التخطيط
    """
    image_b64 = encode_image(image_path)
    prompt = """
حلل هذا التصميم المرجعي واستخرج:
1. لوحة الألوان (hex codes للـ 4-5 ألوان رئيسية)
2. نمط التصميم (modern/classic/minimal/luxury)
3. نوع التخطيط (grid/cards/timeline/dashboard)
4. نمط البطاقات (bordered/shadow/flat/gradient)
5. نمط الهيدر/الفوتر

أعد JSON:
{
  "colors": {"primary": "#...", "secondary": "#...", "accent": "#...", "background": "#...", "text": "#..."},
  "design_style": "modern|classic|minimal|luxury",
  "layout_type": "grid|cards|timeline|dashboard",
  "card_style": "bordered|shadow|flat|gradient",
  "header_style": "minimal|ornate|none",
  "notes": "ملاحظات إضافية عن الستايل"
}
"""
    response = call_vision_api(image_b64, prompt)
    return parse_reference_analysis(response)
```

### 5.3 إعدادات متقدمة
- تفعيل/تعطيل الهيدر والفوتر
- ارتفاع الهيدر/الفوتر
- نوع البطاقات (bordered, shadow, flat, gradient)
- نسبة العرض (16:9, 4:3)
- تفعيل/تعطيل المود بورد
- تفعيل/تعطيل صورة الغلاف

---

## Phase 6: Refactor app.py

### 6.1 إزالة الـ Hardcoded
- **احذف:** `SLIDE_DEFS` الثابت (16 شريحة)
- **احذف:** `DESIGN_RULES` الثابت (ألوان منافع)
- **احذف:** `DEFAULT_TITLES` الثابت
- **احذف:** كل الإشارات لـ "منافع الاقتصادية للعقار"

### 6.2 جعل كل شيء Tenant-Aware
```python
# قبل:
def build_system_prompt(project_data, images_info):
    return f"{DESIGN_RULES}\n## بيانات المشروع\n{project_json}..."

# بعد:
def build_system_prompt(project_data, images_info, tenant_id):
    branding = get_tenant_branding(tenant_id)
    design_rules = build_design_rules(branding)
    slide_templates = get_tenant_slide_templates(tenant_id)
    return f"{design_rules}\n## بيانات المشروع\n{project_json}...\n## قوالب الشرائح\n{slide_templates}..."
```

### 6.3 توليد الشرائح ديناميكياً
```python
def generate_slides(project_data, slide_plan, tenant_id):
    """
    slide_plan: قائمة الشرائح المقترحة (من Phase 4)
    تولد كل شريحة على حدة بالـ design rules الخاصة بالشركة
    """
    branding = get_tenant_branding(tenant_id)
    system_prompt = build_system_prompt(project_data, images_info, tenant_id)

    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        for slide in slide_plan:
            future = executor.submit(generate_single_slide, system_prompt, slide, branding)
            results.append(future)

    return [f.result() for f in results]
```

### 6.4 إزالة server.js
- نقل كل الـ endpoints المتبقية من `server.js` إلى `app.py`
- حذف `server.js` نهائياً
- تحديث `start.bat` و `Dockerfile`

---

## Phase 7: Frontend

### 7.1 صفحات جديدة
1. **Login/Signup Page** — تسجيل/دخول شركة جديدة
2. **Company Settings Page** — إعداد الهوية البصرية
3. **Dynamic Form** — فورم يُبنى ديناميكياً من `/api/fields`
4. **Slide Plan Review** — مراجعة اقتراح الشرائح وتعديلها
5. **Presentation Builder** — المعاينة والتصدير (موجود، يحتاج تعديل)

### 7.2 تطبيق الـ Branding على الـ UI
```javascript
// عند تسجيل الدخول، جلب الـ branding وتطبيقه
async function loadTenantBranding() {
    const res = await fetch('/api/branding', {
        headers: { 'Authorization': `Bearer ${token}` }
    });
    const branding = await res.json();

    // تطبيق الألوان على CSS variables
    document.documentElement.style.setProperty('--p', branding.primary_color);
    document.documentElement.style.setProperty('--pd', branding.secondary_color);
    document.documentElement.style.setProperty('--g', branding.accent_color);
    document.documentElement.style.setProperty('--bg', branding.background_color);

    // تطبيق اللوجو واسم الشركة
    document.getElementById('company-logo').src = branding.logo_path;
    document.getElementById('company-name').textContent = branding.company_name;
}
```

### 7.3 بناء الفورم ديناميكياً
```javascript
async function buildDynamicForm() {
    const res = await fetch('/api/fields', {
        headers: { 'Authorization': `Bearer ${token}` }
    });
    const { fields } = await res.json();

    const form = document.getElementById('project-form');
    form.innerHTML = '';

    fields
        .filter(f => f.is_active)
        .sort((a, b) => a.sort_order - b.sort_order)
        .forEach(field => {
            const wrapper = document.createElement('div');
            wrapper.className = 'form-field';

            const label = document.createElement('label');
            label.textContent = field.field_label + (field.is_required ? ' *' : '');

            let input;
            switch (field.field_type) {
                case 'textarea':
                    input = document.createElement('textarea');
                    break;
                case 'select':
                    input = document.createElement('select');
                    JSON.parse(field.field_options || '[]').forEach(opt => {
                        const option = document.createElement('option');
                        option.value = opt;
                        option.textContent = opt;
                        input.appendChild(option);
                    });
                    break;
                case 'number':
                    input = document.createElement('input');
                    input.type = 'number';
                    break;
                case 'date':
                    input = document.createElement('input');
                    input.type = 'date';
                    break;
                case 'image':
                    input = document.createElement('input');
                    input.type = 'file';
                    input.accept = 'image/*';
                    break;
                default:
                    input = document.createElement('input');
                    input.type = 'text';
            }

            input.name = field.field_key;
            input.placeholder = field.placeholder || '';
            if (field.is_required) input.required = true;

            wrapper.appendChild(label);
            wrapper.appendChild(input);
            form.appendChild(wrapper);
        });
}
```

---

## Phase 8: Admin Panel

### 8.1 Super Admin
- مستخدم بـ `is_admin = 1`
- يقدر يشوف كل الشركات
- يقدر يفعّل/يعطّل شركة
- يقدر يغير الـ plan (free/pro/enterprise)
- يقدر يشوف إحصائيات (عدد العروض، الاستخدام)

### 8.2 Endpoints
- `GET /api/admin/tenants` — كل الشركات
- `PUT /api/admin/tenants/:id` — تعديل شركة
- `DELETE /api/admin/tenants/:id` — حذف شركة
- `GET /api/admin/stats` — إحصائيات عامة

---

## Phase 9: Export (PDF + PPTX)

### 9.1 PDF (موجود، يحتاج تعديل)
- استخدام الـ branding الخاصة بالشركة (ألوان، خطوط، لوجو)
- الـ font faces تُحقن ديناميكياً حسب `font_family` الخاصة بالشركة

### 9.2 PPTX (جديد)
```python
def export_pptx(slides_data, tenant_branding):
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(13.333)  # 16:9
    prs.slide_height = Inches(7.5)

    for slide_data in slides_data:
        slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
        # إضافة المحتوى بناءً على نوع الشريحة
        # استخدام ألوان الشركة
        # إضافة اللوجو في الهيدر

    output_path = f'outputs/{tenant_id}/{presentation_id}.pptx'
    prs.save(output_path)
    return output_path
```

### 9.3 Endpoints
- `POST /api/export/pdf` — تصدير PDF
- `POST /api/export/pptx` — تصدير PPTX
- `GET /api/exports` — قائمة الملفات المُصدّرة
- `GET /api/exports/:id/download` — تحميل ملف

---

## Phase 10: Testing & Deployment

### 10.1 Testing
- اختبار التسجيل والدخول لشركات مختلفة
- اختبار العزل بين الشركات (شركة ما تقدرش تشوف بيانات شركة تانية)
- اختبار الـ branding (كل شركة بألوانها ولوجوها)
- اختبار الفورم الديناميكي
- اختبار عدد الشرائح المتغير
- اختبار تصدير PDF و PPTX بألوان الشركة

### 10.2 Deployment
- تحديث `Dockerfile` (إزالة Node.js dependencies)
- تحديث `requirements.txt` (إضافة PyJWT, etc.)
- تحديث `start.bat`
- اختبار على `sagdemo.site`

---

## ترتيب التنفيذ (Execution Order)

```
Phase 1 (Database & Auth)     ──┐
                                 ├── Phase 6 (Refactor app.py) ──┐
Phase 2 (Branding)            ──┤                                 ├── Phase 7 (Frontend) ──┐
                                 │                                 │                         │
Phase 3 (Input Fields)        ──┘                                 │                         ├── Phase 8 (Admin)
                                   Phase 4 (Dynamic Slides) ───────┘                         │
                                   Phase 5 (Design Templates) ───────────────────────────────┤
                                                                                             ├── Phase 9 (Export)
                                                                                             │
                                                                                             └── Phase 10 (Testing)
```

### الأولويات:
1. **Phase 1 + 2 + 3** — الأساس (Database, Auth, Branding, Fields) — **ممكن بالتوازي**
2. **Phase 4 + 5** — المنطق الذكي (Dynamic Slides, Design Templates)
3. **Phase 6** — إعادة هيكلة app.py (دمج كل شيء)
4. **Phase 7** — الـ Frontend
5. **Phase 8 + 9** — Admin Panel + Export
6. **Phase 10** — Testing & Deployment

---

## الملفات الجديدة

| الملف | الوصف |
|------|-------|
| `db.py` | إدارة SQLite و migrations |
| `auth.py` | JWT authentication |
| `tenant.py` | Tenant management (branding, fields, templates) |
| `slide_engine.py` | Dynamic slide generation engine |
| `design_templates.py` | Pre-built design templates |
| `reference_analyzer.py` | Gemini Vision reference image analysis |
| `exports/pdf_export.py` | PDF export (tenant-branded) |
| `exports/pptx_export.py` | PPTX export (tenant-branded) |

## الملفات المعدلة

| الملف | التغييرات |
|------|-----------|
| `app.py` | إزالة hardcoded values، جعل كل شيء tenant-aware، دمج server.js endpoints |
| `index.html` | إضافة Login/Signup، Company Settings، Dynamic Form، Slide Plan Review |
| `Dockerfile` | إزالة Node.js، إضافة SQLite |
| `requirements.txt` | إضافة PyJWT, PySQLite3 |
| `start.bat` | تحديث رسالة التشغيل |

## الملفات المحذوفة

| الملف | السبب |
|------|-------|
| `server.js` | دمج في app.py |
| `glm-designer.js` | دمج في app.py |
| `pdf_engine.js` | دمج في app.py |
| `users_db.json` | استبدال بـ SQLite |

---

## المخاطر والحلول

| الخطر | الاحتمال | الحل |
|-------|----------|------|
| SQLite لا يكفي لعدد شركات كبير | متوسط | الترحيل لـ PostgreSQL لاحقاً |
| الـ AI لا يوزع المحتوى بالتساوي | عالي | validation + retry + قواعد صارمة في الـ prompt |
| رفع صور مرجعية كبيرة | متوسط | ضغط الصور قبل الحفظ |
| عزل البيانات بين الشركات | عالي | tenant_id في كل query + middleware صارم |
| أداء التوليد (شرائح كتير) | متوسط | parallel generation + caching |

---

## Success Criteria

- [ ] شركة جديدة تقدر تسجل وتدخل
- [ ] كل شركة تقدر تحدد ألوانها، لوجوها، اسمها
- [ ] كل شركة تقدر تضيف/تعدل حقول الفورم
- [ ] الـ AI يقترح عدد شرائح مناسب ويوزع المحتوى بالتساوي
- [ ] الشركة تقدر تعدل عدد الشرائح قبل التوليد
- [ ] كل شركة تقدر تختار قالب تصميم أو ترفع صورة مرجعية
- [ ] تصدير PDF و PPTX بألوان ولوجو الشركة
- [ ] Admin يقدر يتحكم في كل الشركات
- [ ] عزل كامل للبيانات بين الشركات
- [ ] لا توجد شريحة بكلمتين فقط أو شريحة مزدحمة

---

## Notes

- الـ deployment الحالي على Flask (app.py) + gunicorn + Docker — نحافظ على نفس الـ setup
- SQLite كافي للبداية، يمكن الترحيل لـ PostgreSQL لاحقاً
- الـ AI models تبقى كما هي: GLM-5.1 (نص) + Gemini (صور + vision)
- الخطوط: نحافظ على The Sans Arabic كـ default، مع إمكانية إضافة خطوط لاحقاً
- الـ port يبقى 7860
