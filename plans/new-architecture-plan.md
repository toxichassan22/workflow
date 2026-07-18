# الخطة: النظام الجديد (GLM-First Architecture)

## المشكلة الحالية
- 35 endpoints معقدة
- كل endpoint بيعتمد على التاني
- debugging صعب
- bugs كتير (font, shadows, image generation)
- kod كتير مش ضروري

## الحل
GLM يعمل كل حاجة في call واحد:
- يصمم الهيكل (16 شريحة)
- يكتب المحتوى
- يكتب HTML + CSS
- يحط الصور في مكانها

**الباك اند بيبقى 3 endpoints بس:**
1. `POST /api/generate` - GLM يكتب HTML كامل
2. `POST /api/image` - Gemini يولد صور
3. `POST /api/export-pdf` - Playwright يعمل PDF

---

## Phase 1: الكود الأساسي ✅
```
النسخة الحالية هي الرسمية — لا يوجد mirror منفصل
```
> **تم:** الـ mirror أصبح هو الكود الأساسي رسمياً، وتم إلغاء مفهوم الـ mirror تماماً.

## Phase 2: Backend الجديد

### 2.1 هيكل app.py الجديد

```python
# app.py - Backend بسيط

import os
import json
import requests
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

app = Flask(__name__, static_folder='.', static_url_path='')

# Config
ZAI_KEY = os.environ.get("ZAI_KEY")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
GLM_MODEL = "glm-5.1"
IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Endpoint 1: GLM generates complete HTML
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/generate', methods=['POST'])
def generate():
    """
    GLM generates complete HTML for all 16 slides.
    
    Input: {projectData: {name, type, location, budget, ...}, images: {cover: url, moodboard: [urls]}}
    Output: {html: "<div class='slide'>...</div>..."}
    """
    data = request.json
    project_data = data.get('projectData', {})
    images = data.get('images', {})
    
    # Build comprehensive prompt
    prompt = build_glm_prompt(project_data, images)
    
    # Call GLM
    response = call_zai_chat(prompt)
    
    # Extract HTML from response
    html = extract_html_from_response(response)
    
    return jsonify({'html': html})

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Endpoint 2: Image generation (Gemini)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/image', methods=['POST'])
def generate_image():
    """
    Generate image using Gemini via OpenRouter.
    
    Input: {prompt: string, referenceImage?: base64}
    Output: {url: base64_data_uri}
    """
    data = request.json
    prompt = data.get('prompt')
    reference = data.get('referenceImage')
    
    if reference:
        image = call_image_api_with_reference(reference, prompt)
    else:
        image = call_image_api(prompt)
    
    return jsonify({'url': image})

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Endpoint 3: PDF Export
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/export-pdf', methods=['POST'])
def export_pdf():
    """
    Export HTML to PDF using Playwright.
    
    Input: {html: string, projectName: string}
    Output: {url: string}
    """
    slides_html = request.json.get('html')
    project_name = request.json.get('projectName', 'project')
    
    # Generate PDF with Playwright
    pdf_path = generate_pdf_with_playwright(slides_html, project_name)
    
    return jsonify({'url': f'/outputs/{os.path.basename(pdf_path)}'})

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Static files + Health
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/outputs/<path:path>')
def serve_output(path):
    return send_from_directory('outputs', path)

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})
```

### 2.2 GLM Prompt Design

```python
def build_glm_prompt(project_data, images):
    """
    Build comprehensive prompt for GLM to generate all 16 slides.
    """
    
    # Design system constants
    DESIGN_SYSTEM = """
## نظام التصميم
- الألوان: primary=#7A0C0C, secondary=#5A0808, accent=#C4A35A, bg=#FBFAF8
- الخط: 'The Sans Arabic' (Light: 300-600, Bold: 700-900)
- الاتجاه: RTL (dir="rtl")
- حجم كل شريحة: 1280x720px
- الـ CSS يكون inline بس (مفيش external stylesheets)
"""
    
    # Slide templates
    SLIDE_TEMPLATES = """
## قوالب الشرايح

### 1. Cover Slide (غلاف)
```html
<div class="slide" style="background:url('IMAGE_URL') center/cover;background-color:#7A0C0C;">
  <div style="position:absolute;inset:0;background:rgba(122,12,12,0.7);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;">
    <h1 style="font-size:42px;font-weight:700;color:#fff;margin-bottom:16px;">{{TITLE}}</h1>
    <p style="font-size:20px;font-weight:300;color:#C4A35A;">{{SUBTITLE}}</p>
  </div>
</div>
```

### 2. Index Slide (فهرس)
```html
<div class="slide" style="background:#FBFAF8;display:flex;align-items:center;">
  <div style="width:100%;padding:60px;">
    <h2 style="font-size:32px;font-weight:700;color:#7A0C0C;margin-bottom:40px;">فهرس المحتويات</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
      {{INDEX_ITEMS}}
    </div>
  </div>
</div>
```

### 3. Content Slide (محتوى)
```html
<div class="slide" style="background:#FBFAF8;display:flex;">
  <div style="flex:1;padding:50px;display:flex;flex-direction:column;justify-content:center;">
    <h2 style="font-size:28px;font-weight:700;color:#7A0C0C;margin-bottom:24px;">{{TITLE}}</h2>
    <ul style="list-style:none;padding:0;">
      {{BULLETS}}
    </ul>
  </div>
  <div style="flex:1;background:url('IMAGE_URL') center/cover;"></div>
</div>
```

### 4. Moodboard Slide (مود بورد)
```html
<div class="slide" style="background:#FBFAF8;padding:40px;">
  <h2 style="font-size:28px;font-weight:700;color:#7A0C0C;margin-bottom:30px;text-align:center;">{{TITLE}}</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;height:calc(100% - 100px);">
    {{MOODBOARD_IMAGES}}
  </div>
</div>
```

### 5. Closing Slide (ختام)
```html
<div class="slide" style="background:linear-gradient(135deg,#7A0C0C,#5A0808);display:flex;align-items:center;justify-content:center;text-align:center;">
  <div>
    <h2 style="font-size:36px;font-weight:700;color:#fff;margin-bottom:20px;">{{TITLE}}</h2>
    <p style="font-size:18px;color:#C4A35A;">{{CONTACT_INFO}}</p>
  </div>
</div>
```
"""
    
    # Content guidelines
    CONTENT_GUIDELINES = """
## قواعد المحتوى
- اكتب محتوى حقيقي بناءً على بيانات المشروع
- استخدم أرقام وبيانات حقيقية من input
- تجنب العناوين النمطية، اعمل عناوين مخصصة
- كل شريحة content فيها 3-5 bullets مختصرة

## قواعد الصور (مهم جداً)
- صورة الغلاف (1 صورة): اجباري في خلفية شريحة رقم 1 (cover)
- صور المود بورد (4 صور): 
  - اجباري: حطها كلها في شريحة رقم 15 (moodboard)
  - اختياري: توزعها على شرايح المحتوى (3-14) كل صورة في شريحة مختلفة
  - كل صورة تُستخدم مرتين بالحد الأقصى (مرة في moodboard + مرة في content)
  - ممنوع تحط صور في: غلاف (الصورة الرئيسية بس)، فهرس، ختام

## مثال على توزيع الصور
- الشريحة 1 (cover): صورة الغلاف كخلفية
- الشريحة 15 (moodboard): 4 صور في grid
- الشريحة 3 (content): صورة 1 من المود بورد
- الشريحة 7 (content): صورة 2 من المود بورد
- الشريحة 10 (content): صورة 3 من المود بورد
- الشريحة 12 (content): صورة 4 من المود بورد
"""
    
    # Build final prompt
    prompt = f"""
أنت مصمم عروض تقديمية محترف. قم بإنشاء عرض تقديمي كامل بصيغة HTML.

## بيانات المشروع
{json.dumps(project_data, ensure_ascii=False, indent=2)}

## الصور المتوفرة
- صورة الغلاف (1 صورة): {images.get('cover', 'لا توجد')} ← اجباري في خلفية شريحة رقم 1
- صور المود بورد (4 صور): {images.get('moodboard', [])} ← اجباري في شريحة رقم 15 + يحق لك توزيعها على شرايح المحتوى (3-14)
  - كل صورة تُستخدم مرتين: مرة في شريحة 15 ومرة في أي شريحة محتوى (ماعدا غلاف، فهرس، ختام)

{DESIGN_SYSTEM}

{SLIDE_TEMPLATES}

{CONTENT_GUIDELINES}

## المطلوب
اكتب HTML كامل يشمل كل الـ 16 شريحة في document واحد.
- الشريحة الأولى: cover (غلاف بالصورة)
- الشريحة الثانية: index (فهرس)
- الشرايح 3-14: content (محتوى)
- الشريحة 15: moodboard (مود بورد بالصور)
- الشريحة 16: closing (ختام)

## مخرجات
اكتب HTML فقط بدون أي شرح أو تعليقات.
"""
    
    return prompt
```

### 2.4 GLM Response Validation

```python
def validate_glm_output(html):
    """Validate GLM output has correct structure"""
    import re
    
    # Count slides
    slide_count = len(re.findall(r'class="slide"', html))
    if slide_count != 16:
        raise ValueError(f"Expected 16 slides, got {slide_count}")
    
    # Check RTL
    if 'dir="rtl"' not in html:
        raise ValueError("Missing RTL direction")
    
    # Check font
    if 'The Sans Arabic' not in html:
        raise ValueError("Missing Arabic font")
    
    # Check slide types
    if html.count('class="slide"') < 16:
        raise ValueError("Not enough slides")
    
    return True

def fix_common_issues(html):
    """Fix common HTML issues from GLM"""
    # Remove box-shadow for Mac compatibility
    html = re.sub(r'box-shadow:[^;]+;', '', html)
    
    # Ensure RTL
    if 'dir="rtl"' not in html:
        html = html.replace('<div class="slide"', '<div class="slide" dir="rtl"', 1)
    
    # Ensure font
    if 'The Sans Arabic' not in html:
        html = html.replace('font-family:', "font-family:'The Sans Arabic',", 1)
    
    return html
```

### 2.5 Image Flow Implementation

```python
def generate_images(project_data):
    """Generate all 5 images (1 cover + 4 moodboard)"""
    images = {'cover': None, 'moodboard': []}
    
    # 1. Generate cover image
    cover_prompt = f"Modern {project_data['projectType']} building in {project_data['location']}, architectural photography, no text"
    images['cover'] = call_image_api(cover_prompt)
    
    # 2. Generate 4 moodboard images
    moodboard_prompts = [
        f"Interior design of luxury {project_data['projectType']}, modern style",
        f"Exterior view of {project_data['projectType']} in {project_data['location']}",
        f"Living space in {project_data['projectType']}, elegant design",
        f"Architectural details of {project_data['projectType']}, premium finishes"
    ]
    
    for prompt in moodboard_prompts:
        img = call_image_api(prompt)
        images['moodboard'].append(img)
    
    return images
```

### 2.3 Helper Functions

```python
def call_zai_chat(system_prompt, user_content):
    """Call ZAI API (GLM model)"""
    headers = {
        'Authorization': f'Bearer {ZAI_KEY}',
        'Content-Type': 'application/json'
    }
    data = {
        'model': GLM_MODEL,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_content}
        ],
        'temperature': 0.7,
        'max_tokens': 8000
    }
    response = requests.post(f'{ZAI_BASE}/chat/completions', headers=headers, json=data)
    return response.json()

def extract_html_from_response(response):
    """Extract HTML from GLM response"""
    content = response['choices'][0]['message']['content']
    # Find HTML block
    import re
    html_match = re.search(r'<div class="slide"[\s\S]*</div>\s*</div>\s*</div>', content)
    if html_match:
        return html_match.group()
    return content

def call_image_api(prompt):
    """Call OpenRouter for image generation"""
    headers = {
        'Authorization': f'Bearer {OPENROUTER_KEY}',
        'Content-Type': 'application/json'
    }
    data = {
        'model': IMAGE_MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'modalities': ['image', 'text']
    }
    response = requests.post(f'{OPENROUTER_BASE}/chat/completions', headers=headers, json=data)
    # Extract image from response
    # ... implementation

def generate_pdf_with_playwright(html, project_name):
    """Generate PDF using Playwright"""
    from playwright.sync_api import sync_playwright
    
    full_html = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <style>
    @page {{ size: 1280px 720px; margin: 0; }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    .slide {{ width: 1280px; height: 720px; page-break-after: always; }}
    .slide:last-child {{ page-break-after: auto; }}
  </style>
</head>
<body>
{html}
</body>
</html>"""
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(full_html, wait_until='load')
        page.wait_for_timeout(1000)
        
        # Flatten shadows for Mac compatibility
        page.evaluate('''() => {
            document.querySelectorAll('.slide *').forEach(el => {
                const s = getComputedStyle(el);
                if (s.boxShadow && s.boxShadow !== 'none') el.style.boxShadow = 'none';
            });
        }''')
        
        output_path = f'outputs/{project_name}_{int(time.time())}.pdf'
        page.pdf(path=output_path, width='1280px', height='720px', print_background=True)
        browser.close()
    
    return output_path
```

---

## Phase 3: Frontend Adjustments

### 3.1 التعديلات المطلوبة في index.html

**التعديلات:**
1. **Step 1:** Form لبيانات المشروع (name, type, location, budget, audience)
2. **Step 2:** زرار "توليد العرض" → POST `/api/generate`
3. **Step 3:** عرض الـ HTML في iframe/preview
4. **Step 4:** أزرار export (PDF)
5. **Step 5:** تعديل يدوي لو محتاج

**اللي مش محتاجين نعدله:**
- التصميم العام
- الـ navigation
- RTL support
- Export buttons

### 3.2 Complete Frontend Flow

```javascript
// Frontend flow - Complete implementation
async function generatePresentation(projectData) {
    showLoading('جاري توليد الصور...');
    
    // Step 1: Generate all images (1 cover + 4 moodboard)
    const imagesResponse = await fetch('/api/generate-images', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({projectData})
    });
    const images = await imagesResponse.json();
    
    showLoading('جاري توليد العرض التقديمي...');
    
    // Step 2: Generate all slides HTML with GLM
    const response = await fetch('/api/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            projectData: projectData,
            images: images
        })
    });
    const {html} = await response.json();
    
    // Step 3: Preview
    document.getElementById('preview-container').innerHTML = html;
    initSlideNavigation();
    
    showLoading('جاهز!');
    
    // Step 4: Export buttons
    document.getElementById('export-pdf-btn').onclick = async () => {
        showLoading('جاري تصدير PDF...');
        const pdfResponse = await fetch('/api/export-pdf', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({html, projectName: projectData.name})
        });
        const {url} = await pdfResponse.json();
        window.open(url);
        hideLoading();
    };
}

function showLoading(msg) {
    document.getElementById('loading-overlay').style.display = 'flex';
    document.getElementById('loading-msg').textContent = msg;
}

function hideLoading() {
    document.getElementById('loading-overlay').style.display = 'none';
}
```

### 3.3 Slide Navigation

```javascript
function initSlideNavigation() {
    const slides = document.querySelectorAll('.slide');
    let currentSlide = 0;
    
    // Add navigation buttons
    const nav = document.createElement('div');
    nav.className = 'slide-nav';
    nav.innerHTML = `
        <button onclick="prevSlide()">← السابق</button>
        <span id="slide-counter">1 / ${slides.length}</span>
        <button onclick="nextSlide()">التالي →</button>
    `;
    document.getElementById('preview-container').appendChild(nav);
    
    function showSlide(index) {
        slides.forEach((s, i) => s.style.display = i === index ? 'block' : 'none');
        document.getElementById('slide-counter').textContent = `${index + 1} / ${slides.length}`;
    }
    
    window.nextSlide = () => {
        currentSlide = Math.min(currentSlide + 1, slides.length - 1);
        showSlide(currentSlide);
    };
    
    window.prevSlide = () => {
        currentSlide = Math.max(currentSlide - 1, 0);
        showSlide(currentSlide);
    };
    
    showSlide(0);
}
```

---

## Phase 4: Testing

### 4.1 Unit Tests
```python
# test_generate.py
def test_glm_generates_16_slides():
    project_data = {
        'projectName': 'مشروع الواحة',
        'projectType': 'سكني',
        'location': 'الرياض',
        'budget': '100 مليون ريال'
    }
    html = generate(project_data)
    assert html.count('class="slide"') == 16

def test_html_contains_rtl():
    html = generate(test_project)
    assert 'dir="rtl"' in html
    assert 'font-family' in html

def test_images_in_correct_slides():
    html = generate(test_project, test_images)
    # Cover slide should have background image
    # Moodboard slide should have 4 images
    # Content slides should have optional images
    pass
```

### 4.2 Integration Tests
```python
def test_full_workflow():
    # 1. Generate images
    images = generate_images(test_project)
    assert images['cover'] is not None
    assert len(images['moodboard']) == 4
    
    # 2. Generate slides
    html = generate({'projectData': test_project, 'images': images})
    assert len(html) > 1000
    
    # 3. Validate HTML
    validate_glm_output(html)
    
    # 4. Export PDF
    pdf = export_pdf({'html': html, 'projectName': 'test'})
    assert pdf['url'].endswith('.pdf')
```

### 4.3 Mac Testing
- فتح PDF في Apple Preview
- التأكد من عدم وجود ظلال
- التأكد من ظهور الخطوط
- التأكد من RTL

### 4.4 Performance Testing
```python
def test_generation_time():
    import time
    start = time.time()
    html = generate(test_project)
    elapsed = time.time() - start
    assert elapsed < 60  # Should complete in under 60 seconds
```

---

## Complete Workflow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           المستخدم يدخل بيانات المشروع                        │
│  (الاسم, النوع, الموقع, الميزانية, الجمهور المستهدف)                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Backend: توليد الصور (5 صور)                              │
│  - 1 صورة غلاف (cover) ← اجباري                                            │
│  - 4 صور مود بورد ← اجباري في شريحة 15 + اختياري في شرايح المحتوى          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    GLM: توليد HTML كامل (16 شريحة)                          │
│  - يكتب HTML + CSS لكل الشرايح                                              │
│  - يحط الصور في مكانها (غلاف + مود بورد + محتوى)                            │
│  - يكتب المحتوى بناءً على بيانات المشروع                                    │
│  - يضمن RTL + الخطوط العربية                                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Frontend: عرض المعاينة                                    │
│  - عرض الشرايح واحدة واحدة                                                  │
│  - أزرار التنقل (السابق/التالي)                                              │
│  - أزرار التصدير (PDF)                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Backend: تصدير PDF                                        │
│  - Playwright يعرض HTML                                                      │
│  - يشيل box-shadow للـ Mac                                                  │
│  - يصدر PDF                                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 5: Migration

### 5.1 Timeline
- **Phase 1:** الكود الأساسي ✅ (تم — mirror أصبح الرسمي)
- **Phase 2:** Backend جديد (3-4 ساعات)
- **Phase 3:** Frontend adjustments (2-3 ساعات)
- **Phase 4:** Testing (2-3 ساعات)
- **Phase 5:** Migration to main ✅ (تم — الكود الحالي هو الرسمي)

### 5.2 Rollback Plan
- Git history متاح كـ backup
- لو في مشكلة، نرجع لـ commit سابق
- نعمل backup للـ .env

### 5.3 Deployment
```bash
# الكود الحالي هو الرسمي — لا حاجة لنسخ من mirror

# 1. Test
python D:\workflow\app.py

# 2. If OK, deploy to HF
python upload_to_hf.py
```

---

## Risk Assessment

| الخطر | الاحتمال | الحل |
|-------|----------|------|
| GLM context window يخلص | متوسط | نقسم لـ batches |
| HTML output مش مظبوط | عالي | نعمل retry + validation |
| Font rendering issues | منخفض | base64 fonts مضمّنة |
| Mac PDF issues | عالي | shadow flattening CSS |
| Performance issues | منخفض | GLM سريع نسبياً |

---

## Error Handling & Edge Cases

### 5.1 GLM Response Errors
```python
def handle_glm_error(response):
    """Handle various GLM response errors"""
    if 'choices' not in response or len(response['choices']) == 0:
        raise Exception("GLM returned no choices")
    
    content = response['choices'][0]['message']['content']
    
    # Check if response is too short
    if len(content) < 1000:
        raise Exception(f"GLM response too short: {len(content)} chars")
    
    # Check if HTML is valid
    if '<div class="slide"' not in content:
        raise Exception("GLM did not return valid HTML")
    
    return content
```

### 5.2 Image Generation Errors
```python
def handle_image_error(image_url):
    """Handle image generation failures"""
    if not image_url:
        # Use placeholder
        return "data:image/svg+xml;base64,..."
    return image_url
```

### 5.3 PDF Generation Errors
```python
def handle_pdf_error(html, project_name):
    """Handle PDF generation failures"""
    try:
        return generate_pdf_with_playwright(html, project_name)
    except Exception as e:
        print(f"PDF generation failed: {e}")
        # Fallback: save HTML as file
        html_path = f'outputs/{project_name}_{int(time.time())}.html'
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        return html_path
```

### 5.4 Timeout Handling
```python
import signal

class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")

def call_glm_with_timeout(prompt, timeout=60):
    """Call GLM with timeout"""
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)
    try:
        return call_zai_chat(prompt)
    except TimeoutError:
        raise Exception("GLM call timed out after 60 seconds")
    finally:
        signal.alarm(0)
```

---

## Success Criteria

- [ ] GLM يولد HTML كامل لـ 16 شريحة
- [ ] صورة الغلاف في خلفية شريحة 1
- [ ] 4 صور مود بورد في شريحة 15
- [ ] الصور المود بورد متاحة للـ content slides
- [ ] PDF يفتح صح على Mac
- [ ] الخطوط العربية تظهر
- [ ] RTL يعمل صح
- [ ] Backend بسيط (3 endpoints بس)
- [ ] Frontend يشتغل مع النظام الجديد
- [ ] Error handling مظبوط
- [ ] Performance مقبول (< 60 ثانية)

---

## Notes

- GLM model: glm-5.1 (نفس الموديل الحالي)
- Image model: google/gemini-3.1-flash-image-preview (نفس الموديل)
- Fonts: The Sans Arabic (Light + Bold)
- Colors: primary=#7A0C0C, accent=#C4A35A
- Slides: 1280x720px each
- Images: 5 total (1 cover + 4 moodboard)
- Each moodboard image used twice (moodboard + content slide)
