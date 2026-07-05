// ═══════════════════════════════════════════════════════════════
// GLM 5.1 + Gemini Flash — Luxury Real Estate Investment PPTX
// ═══════════════════════════════════════════════════════════════

var PptxGenJS = require('pptxgenjs');
var fs = require('fs');
var path = require('path');
var { execSync } = require('child_process');

var ZAI_KEY = process.env.ZAI_KEY;
var OPENROUTER_KEY = process.env.OPENROUTER_KEY;
var ZAI_BASE = 'https://api.z.ai/api/paas/v4';
var OPENROUTER_BASE = 'https://openrouter.ai/api/v1';
var GLM_MODEL = 'glm-5.1';
var IMAGE_MODEL = 'google/gemini-3.1-flash-image-preview';
var OUTPUT_DIR = path.join(__dirname, 'outputs');
var LOGO_PATH = path.join(__dirname, 'assets', 'logo.png');

if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR, { recursive: true });

var logoBase64 = '';
try {
  logoBase64 = 'data:image/png;base64,' + fs.readFileSync(LOGO_PATH).toString('base64');
} catch(e) {}

// ═══ System Prompt ═══
var SYSTEM_PROMPT = `You are a world-class luxury real estate investment presentation designer for "منافع الاقتصادية للعقار" (Manafe Economic Co. for Real Estate).

Your task: Generate a pptxgenjs Node.js script that creates a LUXURY investment presentation.

═══════════════════════════════════════════════════════════════════
HOW TO DETERMINE SLIDE COUNT AND CONTENT
═══════════════════════════════════════════════════════════════════
The user specifies how many slides they want. You MUST follow this formula:

Total slides = N
- Slide 1 = COVER (always, no content)
- Slide N = CLOSING (always, no content)
- Slides 2 to N-1 = CONTENT slides (white background, with data)

Examples:
- 3 slides: COVER + 1 CONTENT + CLOSING
- 4 slides: COVER + 2 CONTENT + CLOSING
- 5 slides: COVER + 3 CONTENT + CLOSING
- 10 slides: COVER + 8 CONTENT + CLOSING
- 14 slides: COVER + 12 CONTENT + CLOSING

RULE: NEVER add content to slide 1 or slide N. They are ONLY cover and closing.

═══════════════════════════════════════════════════════════════════
SLIDE STRUCTURE — WHAT GOES WHERE
═══════════════════════════════════════════════════════════════════
SLIDE 1 (COVER) — EXACTLY as shown in client proof:
- Background: Use ##IMAGE_COVER## as FULL background (x:0, y:0, w:13.33, h:7.5, sizing:{type:'cover'})
- Add dark overlay: slide.addShape(pptx.shapes.RECTANGLE, { x:0, y:0, w:13.33, h:7.5, fill:{color:'000000'}, transparency:40 })
- Add burgundy accent line on right edge: slide.addShape(pptx.shapes.RECTANGLE, { x:12.8, y:0, w:0.53, h:7.5, fill:{color:'670D0C'} })
- Logo at CENTER: slide.addImage({ data: logo, x:5.0, y:0.8, w:3.3, h:2.5 })
- Project name LARGE at center: slide.addText(projectName, { x:1.5, y:3.3, w:10.33, h:1.2, fontSize:48, bold:true, color:'FFFFFF', align:'center' })
- Subtitle below: slide.addText('عرض مشروع استثماري', { x:1.5, y:4.6, w:10.33, h:0.5, fontSize:20, color:'C2A176', align:'center' })
- NOTHING ELSE. NO KPI. NO DATA. NO TABLES. NO FOOTER.

SLIDE N (CLOSING) — EXACTLY as shown in client proof:
- slide.background = { color: '670D0C' }
- Logo at TOP: slide.addImage({ data: logo, x:5.0, y:0.6, w:3.3, h:2.5 })
- "شكراً لكم" LARGE center: slide.addText('شكراً لكم', { x:1.0, y:3.0, w:11.33, h:1.2, fontSize:52, bold:true, color:'FFFFFF', align:'center' })
- Project name below: slide.addText(projectName, { x:1.0, y:4.3, w:11.33, h:0.6, fontSize:22, color:'C2A176', align:'center' })
- Contact info: slide.addText('للاستفسارات والتواصل: راسل فريق الاستثمار', { x:1.0, y:5.5, w:11.33, h:0.4, fontSize:14, color:'FFFFFF', align:'center' })
- NOTHING ELSE. NO KPI. NO DATA. NO TABLES. NO FOOTER.

SLIDES 2 to N-1 (CONTENT) — WHITE BACKGROUND:
- slide.background = { color: 'FFFFFF' }
- Add header with logo at top-right
- Add footer with page number
- Add content (KPI cards, tables, etc.)

═══════════════════════════════════════════════════════════════════
CRITICAL RULES — SLIDE ORDER (MUST FOLLOW)
═══════════════════════════════════════════════════════════════════
YOU MUST FOLLOW THIS EXACT ORDER:

Slide 1 = COVER ONLY (logo + project name, NO content, NO data, NO tables)
Slides 2 to N-1 = CONTENT (white background, with data)
Slide N = CLOSING ONLY (logo + "شكراً لكم", NO content, NO data, NO tables)

WRONG: Adding KPI cards, tables, data, bullets to slide 1 or slide N
CORRECT: Slide 1 has ONLY logo + project name. Slide N has ONLY logo + "شكراً لكم"

═══════════════════════════════════════════════════════════════════
CRITICAL RULES
═══════════════════════════════════════════════════════════════════
- Do NOT change any financial numbers, data, or item names.
- Do NOT delete any content slide.
- All text is Arabic. All text alignment is RIGHT. All text flows RTL.
- BACKGROUND: WHITE ("FFFFFF") for content slides only.
- NEVER use beige, gray, or any other color as slide background.

═══════════════════════════════════════════════════════════════════
BRAND IDENTITY
═══════════════════════════════════════════════════════════════════
Company: منافع الاقتصادية للعقار (Manafe Economic Co.)
Colors:
  - BURGUNDY: "670D0C"
  - SILVER: "A7A9AC"
  - GOLD: "C2A176"
  - BEIGE: "F5F0EE" (cards only, NOT backgrounds)
  - WHITE: "FFFFFF" (content slide backgrounds)
  - DARK TEXT: "0F172A"
  - MUTED TEXT: "64748B"
  - CARD BG: "F8FAFC"
Font: "The Sans Arabic" or "Cairo" or "Tajawal" or fallback to Arial

═══════════════════════════════════════════════════════════════════
HEADER & FOOTER — CONTENT SLIDES ONLY
═══════════════════════════════════════════════════════════════════
HEADER: Logo top-right + slide name + thin burgundy line
FOOTER: Page number in burgundy circle + company name + date
*** NEVER add "صورة المشروع" text. NEVER add image placeholders. ***

══════════════════════════════════════════════════════════════════
EXACT COORDINATES — MUST USE FOR EVERY CONTENT SLIDE
══════════════════════════════════════════════════════════════════
SLIDE: 13.33 x 7.5 inches

HEADER (every content slide):
- Bg rect: x:0, y:0, w:13.33, h:0.47, fill:{color:'FFFFFF', transparency:6}
- Logo: x:0.33, y:0.08, w:0.45, h:0.30
- Company name: x:0.9, y:0.08, w:3.0, h:0.30, fontSize:11, bold:true, color:'670D0C', align:'right'
- Slide title: x:4.5, y:0.08, w:5.0, h:0.30, fontSize:10, color:'888888', align:'center'
- Line below: x:0, y:0.47, w:13.33, h:0.015, fill:{color:'670D0C', transparency:70}

FOOTER (every content slide):
- Line above: x:0, y:7.06, w:13.33, h:0.01, fill:{color:'EEEEEE'}
- Bg: x:0, y:7.07, w:13.33, h:0.43, fill:{color:'FFFFFF', transparency:6}
- Project name: x:0.33, y:7.12, w:4.0, h:0.25, fontSize:8, color:'AAAAAA', align:'right'
- Company: x:4.5, y:7.12, w:5.0, h:0.25, fontSize:8, color:'AAAAAA', align:'center'
- Page circle: x:12.5, y:7.10, w:0.35, h:0.35, fill:{color:'670D0C'}, rectRadius:0.05
- Page text: x:12.5, y:7.12, w:0.35, h:0.30, fontSize:9, color:'FFFFFF', bold:true, align:'center'

CONTENT AREA (between header and footer):
- Available: x:0.33, y:0.65, w:12.67, h:6.35
- Do NOT place below y:7.00 (overlaps footer)
- Do NOT place above y:0.55 (overlaps header)
- Cards padding: 0.25 inches inside each card

══════════════════════════════════════════════════════════════════
CONTENT SLIDE OPTIONS (pick N-2 slides from these)
═══════════════════════════════════════════════════════════════════
- EXECUTIVE SUMMARY: 6 KPI cards
- PROJECT CONCEPT: 5 info cards
- LOCATION: Feature cards + Google Maps
- ADVANTAGES: Marketing grid 4+ cards
- COMPONENTS: Table + 3 summary cards
- OPERATING PROFIT: Visual equation
- COSTS: Side-by-side cards + total
- PROFITS: Flow diagram equation
- FINANCIAL: Dashboard ROI/NOI/Payback
- TIMELINE: Gantt bars
- OPPORTUNITIES: Marketing cards
- RISKS: Risk cards

═══════════════════════════════════════════════════════════════════
API RULES
═══════════════════════════════════════════════════════════════════
- pptx.shapes.RECTANGLE, pptx.shapes.ROUNDED_RECTANGLE, pptx.shapes.OVAL
- Colors hex WITHOUT '#'. NEVER put base64 in addText().
- Do NOT redeclare "logo" or "projectData".
- OUTPUT: pptx.writeFile({ fileName: 'D:/workflow/outputs/presentation_TIMESTAMP.pptx' })

=== IMAGE RULES ===
5 images max: 1 cover + 4 distributed across content slides.
NEVER add "صورة المشروع" placeholder.
Each IMAGE_SPEC unique. "high quality, no text, no watermarks"

Return ONLY valid JavaScript code. No explanations.`;

// ═══ Step 1: GLM generates presentation with image specs ═══
async function generateWithGLM(topic, projectData) {
  console.log('\n[1/3] GLM 5.1 generating presentation...');

  var userText = 'TOPIC: "' + topic + '"';
  if (projectData) {
    userText += '\n\nPROJECT DATA:\n' + JSON.stringify(projectData, null, 2);
  }

  var userMessageContent;
  var referenceImage = projectData ? projectData.mainImageData : null;
  if (referenceImage && typeof referenceImage === 'string' && (referenceImage.startsWith('data:image/') || referenceImage.startsWith('http'))) {
    userMessageContent = [
      { type: "text", text: userText },
      { type: "image_url", image_url: { url: referenceImage } }
    ];
  } else {
    userMessageContent = userText;
  }

  var response = await fetch(ZAI_BASE + '/chat/completions', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + ZAI_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: GLM_MODEL,
      messages: [
        { role: 'system', content: [
            { type: 'text', text: SYSTEM_PROMPT, cache_control: { type: 'ephemeral' } }
        ]},
        { role: 'user', content: userMessageContent }
      ],
      temperature: 0.3,
      max_tokens: 16000,
      stream: false
    })
  });

  var data = await response.json();
  if (!data.choices || !data.choices[0]) throw new Error('GLM failed: ' + JSON.stringify(data));

  if (data.usage) {
    var u = data.usage;
    console.log('  ✓ Tokens: ' + u.total_tokens + ' | Cost: $' + ((u.prompt_tokens * 0.98 + u.completion_tokens * 3.08) / 1000000).toFixed(4));
  }

  var code = data.choices[0].message.content.trim();
  code = code.replace(/^```javascript\s*/i, '').replace(/^```js\s*/i, '').replace(/^```\s*/i, '');
  code = code.replace(/\s*```\s*$/, '');

  // Extract IMAGE_SPEC comments — strictly limit to MAX 4 images
  var MAX_IMAGES = 5;
  var SLIDE_W = 13.33;
  var SLIDE_H = 7.5;
  var imageSpecs = [];
  var specRegex = /\/\/\s*IMAGE_SPEC:\s*slide=(\d+),\s*x=([\d.]+),\s*y=([\d.]+),\s*w=([\d.]+),\s*h=([\d.]+),\s*prompt="([^"]+)"/g;
  var match;
  while ((match = specRegex.exec(code)) !== null) {
    imageSpecs.push({
      slide: parseInt(match[1]),
      x: parseFloat(match[2]),
      y: parseFloat(match[3]),
      w: parseFloat(match[4]),
      h: parseFloat(match[5]),
      prompt: match[6]
    });
  }

  // Enforce strict limit of MAX_IMAGES
  if (imageSpecs.length > MAX_IMAGES) {
    console.log('  ⚠ GLM generated ' + imageSpecs.length + ' IMAGE_SPECs — truncating to ' + MAX_IMAGES);
    imageSpecs = imageSpecs.slice(0, MAX_IMAGES);
  }

  // Validate and constrain positions to stay within slide bounds
  for (var i = 0; i < imageSpecs.length; i++) {
    var spec = imageSpecs[i];
    // Ensure slide number is valid (not cover slide 1, not beyond total slides)
    if (spec.slide <= 1) spec.slide = 2;
    if (spec.slide > 14) spec.slide = 13;
    // Constrain x: must be >= 0 and x + w <= SLIDE_W
    if (spec.x < 0) spec.x = 0.3;
    if (spec.x + spec.w > SLIDE_W) spec.w = SLIDE_W - spec.x - 0.2;
    if (spec.w < 2) spec.w = 4;
    // Constrain y: must be >= 0 and y + h <= SLIDE_H
    if (spec.y < 0) spec.y = 1.2;
    if (spec.y + spec.h > SLIDE_H) spec.h = SLIDE_H - spec.y - 0.2;
    if (spec.h < 2) spec.h = 3.5;
  }

  // Remove IMAGE_SPEC comments from code
  code = code.replace(/\/\/\s*IMAGE_SPEC:[^\n]*/g, '');

  // ═══ POST-PROCESSING: Scan all x,y,w,h values and clamp to slide ═══
  // This catches any coordinate that would go outside the 13.33×7.5 slide
  code = code.replace(/(x\s*:\s*)([\d.]+)/g, function(match, prefix, numStr) {
    var num = parseFloat(numStr);
    if (isNaN(num)) return match;
    if (num > SLIDE_W) return prefix + SLIDE_W.toFixed(2);
    if (num < 0) return prefix + '0';
    return match;
  });
  code = code.replace(/(y\s*:\s*)([\d.]+)/g, function(match, prefix, numStr) {
    var num = parseFloat(numStr);
    if (isNaN(num)) return match;
    if (num > SLIDE_H) return prefix + SLIDE_H.toFixed(2);
    if (num < 0) return prefix + '0';
    return match;
  });
  // Also clamp w values that exceed slide width
  code = code.replace(/(w\s*:\s*)([\d.]+)/g, function(match, prefix, numStr) {
    var num = parseFloat(numStr);
    if (isNaN(num)) return match;
    if (num > SLIDE_W) return prefix + (SLIDE_W - 0.2).toFixed(2);
    return match;
  });
  // Clamp h values that exceed slide height
  code = code.replace(/(h\s*:\s*)([\d.]+)/g, function(match, prefix, numStr) {
    var num = parseFloat(numStr);
    if (isNaN(num)) return match;
    if (num > SLIDE_H) return prefix + (SLIDE_H - 0.2).toFixed(2);
    return match;
  });

  console.log('  ✓ Slides: 14 | Images specified: ' + imageSpecs.length + ' (max ' + MAX_IMAGES + ')');
  return { code: code, imageSpecs: imageSpecs };
}

// ═══ Step 2: Generate images (building from description, then different angles) ═══
async function generateImages(imageSpecs, projectData) {
  console.log('\n[2/3] Generating ' + imageSpecs.length + ' images...');
  var results = {};

  if (imageSpecs.length === 0) return results;

  // STEP 1: Generate a "hero" building image from project description
  // This is the KEY fix — we generate the building from text description,
  // NOT from the client's land photo (which may be empty)
  var heroImage = null;
  var heroPrompt = buildHeroPrompt(projectData);

  console.log('  Generating hero building image from project description...');
  console.log('  Hero prompt: ' + heroPrompt.substring(0, 120) + '...');
  heroImage = await callImageAPI(heroPrompt);

  if (heroImage) {
    console.log('  ✓ Hero building image generated successfully');
  } else {
    console.log('  ⚠ Hero generation failed, falling back to client image...');
    heroImage = projectData ? projectData.mainImageData : null;
  }

  // STEP 2: Use hero image as reference for ALL slides
  if (heroImage) {
    console.log('  Using hero image as reference for all slides (same building, different angles)');

    for (var i = 0; i < imageSpecs.length; i++) {
      var spec = imageSpecs[i];
      var isCoverSlide = (spec.slide === 1);

      if (isCoverSlide) {
        // Slide 1 (cover): use the hero image directly
        console.log('  [' + (i + 1) + '/' + imageSpecs.length + '] Slide ' + spec.slide + ' (hero image for cover)');
        results[spec.slide] = { data: heroImage, x: spec.x, y: spec.y, w: spec.w, h: spec.h };
      } else {
        // All other slides: use hero as reference + unique angle prompt
        console.log('  [' + (i + 1) + '/' + imageSpecs.length + '] Slide ' + spec.slide + ' (same building, different angle)...');

        var variantImage = await callImageAPIWithReference(
          heroImage,
          'Using the building in the reference image as the EXACT SAME building. ' +
          'Show this SAME building from a completely different angle/perspective. ' +
          'Keep the same architectural style, materials, colors, and design language. ' +
          'Do NOT change the building itself — only change the camera angle, lighting, or context. ' +
          'Angle description: ' + spec.prompt + '. high quality, professional, no text, no watermarks'
        );

        if (variantImage) {
          results[spec.slide] = { data: variantImage, x: spec.x, y: spec.y, w: spec.w, h: spec.h };
          console.log('    ✓ Same building, different angle generated');
        } else {
          console.log('    ⚠ Reference failed, falling back to independent generation...');
          var fallback = await callImageAPI(spec.prompt + ', high quality, professional, no text, no watermarks');
          if (fallback) {
            results[spec.slide] = { data: fallback, x: spec.x, y: spec.y, w: spec.w, h: spec.h };
          }
        }
      }

      // Rate limiting between generations
      if (i < imageSpecs.length - 1) {
        await new Promise(function(r) { setTimeout(r, 2000); });
      }
    }
  } else {
    // No reference image at all — generate each independently
    console.log('  ⚠ No reference image available. Generating independently...');
    for (var i = 0; i < imageSpecs.length; i++) {
      var spec = imageSpecs[i];
      console.log('  [' + (i + 1) + '/' + imageSpecs.length + '] Slide ' + spec.slide + ' (independent)...');
      var img = await callImageAPI(spec.prompt + ', high quality, professional, no text, no watermarks');
      if (img) {
        results[spec.slide] = { data: img, x: spec.x, y: spec.y, w: spec.w, h: spec.h };
      }
      if (i < imageSpecs.length - 1) {
        await new Promise(function(r) { setTimeout(r, 2000); });
      }
    }
  }

  return results;
}

// ═══ Helper: Build a hero prompt from project data ═══
function buildHeroPrompt(projectData) {
  var parts = [];

  // Start with the project type/description
  if (projectData && projectData.projectDescription) {
    parts.push(projectData.projectDescription);
  } else if (projectData && projectData.aiImagePrompt) {
    parts.push(projectData.aiImagePrompt);
  } else if (projectData && projectData.projectName) {
    parts.push('Modern luxury ' + projectData.projectName);
  } else {
    parts.push('Modern luxury residential tower');
  }

  // Add location context if available
  if (projectData && projectData.location) {
    parts.push('Located in ' + projectData.location);
  }

  // Add building details if available
  if (projectData && projectData.buildingType) {
    parts.push(projectData.buildingType);
  }

  // Add style keywords
  parts.push('professional architectural photography');
  parts.push('modern glass and steel facade');
  parts.push('warm golden hour lighting');
  parts.push('cinematic composition');
  parts.push('no text, no people, no watermarks');

  return parts.join(', ');
}

async function callImageAPI(prompt) {
  try {
    var controller = new AbortController();
    var timeout = setTimeout(function() { controller.abort(); }, 90000);

    var response = await fetch(OPENROUTER_BASE + '/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + OPENROUTER_KEY,
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://github.com',
        'X-Title': 'PPTX Generator'
      },
      body: JSON.stringify({
        model: IMAGE_MODEL,
        messages: [{ role: 'user', content: prompt }]
      }),
      signal: controller.signal
    });

    clearTimeout(timeout);
    var data = await response.json();

    if (data.choices && data.choices[0] && data.choices[0].message.images) {
      var imgs = data.choices[0].message.images;
      if (imgs.length > 0 && imgs[0].image_url && imgs[0].image_url.url) {
        return imgs[0].image_url.url;
      }
    }
  } catch(e) {
    console.error('    API Error: ' + e.message);
  }
  return null;
}

async function callImageAPIWithReference(referenceImageBase64, prompt) {
  try {
    var controller = new AbortController();
    var timeout = setTimeout(function() { controller.abort(); }, 90000);

    var response = await fetch(OPENROUTER_BASE + '/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + OPENROUTER_KEY,
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://github.com',
        'X-Title': 'PPTX Generator'
      },
      body: JSON.stringify({
        model: IMAGE_MODEL,
        messages: [
          {
            role: 'user',
            content: [
              { type: 'text', text: prompt },
              { type: 'image_url', image_url: { url: referenceImageBase64 } }
            ]
          }
        ]
      }),
      signal: controller.signal
    });

    clearTimeout(timeout);
    var data = await response.json();

    if (data.choices && data.choices[0] && data.choices[0].message.images) {
      var imgs = data.choices[0].message.images;
      if (imgs.length > 0 && imgs[0].image_url && imgs[0].image_url.url) {
        return imgs[0].image_url.url;
      }
    }
  } catch(e) {
    console.error('    API Error: ' + e.message);
  }
  return null;
}

// ═══ Step 3: Merge and run ═══
async function main() {
  var topic = process.argv[2];
  var dataFile = process.argv[3];

  if (!topic) {
    console.log('\nUsage: node glm-designer.js "topic" [data.json]\n');
    process.exit(1);
  }

  console.log('═══════════════════════════════════════');
  console.log('  GLM 5.1 + Gemini Flash — Luxury Real Estate');
  console.log('═══════════════════════════════════════');
  console.log('  Topic: ' + topic);

  var projectData = null;
  if (dataFile && fs.existsSync(dataFile)) {
    projectData = JSON.parse(fs.readFileSync(dataFile, 'utf8'));
  }

  try {
    // 1. GLM generates code + image specs
    var result = await generateWithGLM(topic, projectData);

    // 2. Generate images based on specs
    var images = {};
    if (result.imageSpecs.length > 0) {
      images = await generateImages(result.imageSpecs, projectData);
    }

    // 3. Inject images into code at specified positions
    var outName = 'presentation_' + Date.now() + '.pptx';
    var code = result.code.replace(/presentation_[0-9]+\.pptx/g, outName);

    // Inject images before writeFile
    var imageBlock = '\n// === INJECTED IMAGES ===\n';
    for (var slideNum in images) {
      var img = images[slideNum];
      imageBlock += 'pptx.slides[' + (parseInt(slideNum) - 1) + '].addImage({ data: "' + img.data + '", x: ' + img.x + ', y: ' + img.y + ', w: ' + img.w + ', h: ' + img.h + ' });\n';
    }

    code = code.replace(/pptx\.writeFile/, imageBlock + '\npptx.writeFile');

    var boundsEnforcer = `
// ═══ RUNTIME BOUNDS ENFORCEMENT ═══
// Lock slide layout to 13.33 × 7.5 (LAYOUT_WIDE)
var SLIDE_W = 13.33, SLIDE_H = 7.5;
Object.defineProperty(pptx, 'layout', { get: function() { return 'LAYOUT_WIDE'; }, set: function() { /* LOCKED */ }, configurable: false });
Object.defineProperty(pptx, 'presLayout', { get: function() { return { name: 'LAYOUT_WIDE', width: SLIDE_W, height: SLIDE_H }; }, configurable: false });
// Prevent GLM from redefining layout
pptx.defineLayout = function() { console.log('  ⚠ defineLayout blocked — slide locked to ' + SLIDE_W + '×' + SLIDE_H); };

// Monkey-patch pptx.addSlide() to wrap all element methods
// and clamp coordinates to stay within the slide (13.33 × 7.5).
var _origAddSlide = pptx.addSlide.bind(pptx);
pptx.addSlide = function() {
  var slide = _origAddSlide.apply(this, arguments);
  var SLIDE_W = 13.33, SLIDE_H = 7.5, MIN_X = 0, MIN_Y = 0;

  function clampPos(o) {
    if (!o || typeof o !== 'object') return o;
    // Clamp x
    if (typeof o.x === 'number') {
      if (o.x < MIN_X) o.x = MIN_X;
      if (o.x + (o.w || 0) > SLIDE_W) { o.w = Math.max(0.1, SLIDE_W - o.x - 0.05); }
    }
    // Clamp y
    if (typeof o.y === 'number') {
      if (o.y < MIN_Y) o.y = MIN_Y;
      if (o.y + (o.h || 0) > SLIDE_H) { o.h = Math.max(0.1, SLIDE_H - o.y - 0.05); }
    }
    // Clamp w
    if (typeof o.w === 'number') {
      if (o.w > SLIDE_W) o.w = SLIDE_W - 0.1;
      if (o.x !== undefined && o.x + o.w > SLIDE_W) o.w = Math.max(0.1, SLIDE_W - o.x - 0.05);
    }
    // Clamp h
    if (typeof o.h === 'number') {
      if (o.h > SLIDE_H) o.h = SLIDE_H - 0.1;
      if (o.y !== undefined && o.y + o.h > SLIDE_H) o.h = Math.max(0.1, SLIDE_H - o.y - 0.05);
    }
    return o;
  }

  function clampOpts(opts) {
    if (!opts || typeof opts !== 'object') return opts;
    var o = Object.assign({}, clampPos(opts));
    return o;
  }

  function clampTableOpts(opts) {
    if (!opts || typeof opts !== 'object') return opts;
    var o = Object.assign({}, opts);
    if (typeof o.x === 'number' && o.x < MIN_X) o.x = MIN_X;
    if (typeof o.y === 'number' && o.y < MIN_Y) o.y = MIN_Y;
    if (typeof o.w === 'number' && o.w > SLIDE_W) o.w = SLIDE_W - 0.1;
    return o;
  }

  // Wrap addText — clamp positions to slide bounds
  var _origAddText = slide.addText.bind(slide);
  slide.addText = function(textOrArr, optsOrIdx, maybeOpts) {
    if (arguments.length === 3) {
      return _origAddText(textOrArr, optsOrIdx, clampOpts(maybeOpts));
    }
    return _origAddText(textOrArr, clampOpts(optsOrIdx));
  };

  // Wrap addShape
  var _origAddShape = slide.addShape.bind(slide);
  slide.addShape = function(shapeType, opts) {
    return _origAddShape(shapeType, clampOpts(opts));
  };

  // Wrap addImage
  var _origAddImage = slide.addImage.bind(slide);
  slide.addImage = function(opts) {
    return _origAddImage(clampOpts(opts));
  };

  // Wrap addTable
  var _origAddTable = slide.addTable.bind(slide);
  slide.addTable = function(rows, opts) {
    return _origAddTable(rows, clampTableOpts(opts));
  };

  return slide;
};
console.log('  ✓ Bounds enforcer active — all elements clamped to ' + SLIDE_W + '×' + SLIDE_H + ' inches');
`;

    var fullCode = `
var logo = '${logoBase64}';
var projectData = ${JSON.stringify(projectData || {})};

${boundsEnforcer}

${code}
`;

    var scriptPath = path.join(OUTPUT_DIR, '_generated_script.js');
    fs.writeFileSync(scriptPath, fullCode);

    console.log('\n[3/3] Running final presentation...');
    execSync('node ' + scriptPath, { stdio: 'inherit', cwd: __dirname });

    console.log('\n═══════════════════════════════════════');
    console.log('  DONE!');
    console.log('═══════════════════════════════════════\n');

  } catch (err) {
    console.error('\nError:', err.message);
    process.exit(1);
  }
}

main();
