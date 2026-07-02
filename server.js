var express = require('express');
var path = require('path');
var fs = require('fs');
var { execSync, exec } = require('child_process');

var app = express();
var PORT = process.env.PORT || 3000;

// ═══ API Keys (same as glm-designer.js) ═══
var ZAI_KEY = process.env.ZAI_KEY;
var OPENROUTER_KEY = process.env.OPENROUTER_KEY;
var ZAI_BASE = 'https://api.z.ai/api/paas/v4';
var OPENROUTER_BASE = 'https://openrouter.ai/api/v1';
var GLM_MODEL = 'glm-5.1';
var IMAGE_MODEL = 'google/gemini-3.1-flash-image-preview';
var OUTPUT_DIR = path.join(__dirname, 'outputs');
var LOGO_PATH = path.join(__dirname, 'manafe-logo.png');
var USERS_DB_PATH = path.join(__dirname, 'users_db.json');

if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR, { recursive: true });

app.use(express.json({ limit: '50mb' }));
app.use(express.static(__dirname));
app.use('/outputs', express.static(path.join(__dirname, 'outputs')));

// ═══ User Database Schema & Helper Functions (JSON-based schema with ai_training_history) ═══
function loadUserDB() {
  if (fs.existsSync(USERS_DB_PATH)) {
    try {
      return JSON.parse(fs.readFileSync(USERS_DB_PATH, 'utf8'));
    } catch (e) {
      console.error('Error reading user database:', e);
    }
  }
  return { users: {} };
}

function saveUserDB(db) {
  try {
    fs.writeFileSync(USERS_DB_PATH, JSON.stringify(db, null, 2), 'utf8');
  } catch (e) {
    console.error('Error writing user database:', e);
  }
}

function getTrainingHistory(userId) {
  var db = loadUserDB();
  var user = db.users[userId || 'default_user'];
  return (user && user.ai_training_history) ? user.ai_training_history : [];
}

function saveTrainingHistory(userId, messages) {
  var db = loadUserDB();
  var id = userId || 'default_user';
  if (!db.users[id]) {
    db.users[id] = {};
  }
  db.users[id].ai_training_history = messages;
  saveUserDB(db);
}

// Truncate project data to fit within GLM token limits
function truncateProjectData(data, maxChars) {
  maxChars = maxChars || 8000;
  if (!data) return data;
  var str = JSON.stringify(data);
  if (str.length <= maxChars) return data;
  var obj = JSON.parse(str);
  var keys = Object.keys(obj);
  var perKey = Math.floor(maxChars / keys.length);
  for (var i = 0; i < keys.length; i++) {
    var val = obj[keys[i]];
    if (typeof val === 'string' && val.length > perKey) {
      obj[keys[i]] = val.substring(0, perKey) + '...';
    } else if (Array.isArray(val)) {
      var arrStr = JSON.stringify(val);
      if (arrStr.length > perKey) {
        obj[keys[i]] = val.slice(0, 5);
      }
    }
  }
  return obj;
}

// Helper to construct the messages list prepending training history to the API request to leverage Prefix Caching
// Helper to construct the messages list prepending training history to the API request to leverage Prefix Caching
function writeSystemPrombetBackup(messages, aiResponse) {
  try {
    var merged = JSON.parse(JSON.stringify(messages));
    if (aiResponse) {
      merged.push({ role: 'assistant', content: typeof aiResponse === 'string' ? aiResponse : JSON.stringify(aiResponse, null, 2) });
    }
    
    var backupContent = merged.map(function(m) {
      var contentVal = m.content;
      if (Array.isArray(contentVal)) {
        var contentStr = "";
        contentVal.forEach(function(part) {
          if (part.type === 'text') {
            contentStr += (part.text || '') + '\n';
          } else if (part.type === 'image_url') {
            var url = (part.image_url && part.image_url.url) || '';
            if (url.startsWith('data:')) {
              contentStr += "[IMAGE DATA: " + url.substring(0, 100) + "...]\n";
            } else {
              contentStr += "[IMAGE URL: " + url + "]\n";
            }
          }
        });
        contentVal = contentStr;
      }
      return "[" + m.role.toUpperCase() + "]:\n" + contentVal;
    }).join('\n\n═══════════════════════════════════════\n\n');
    
    fs.writeFileSync(path.join(__dirname, 'systemprombet'), backupContent, 'utf8');
    fs.writeFileSync(path.join(__dirname, 'systemprombet.txt'), backupContent, 'utf8');
    fs.writeFileSync(path.join(__dirname, 'systemprombet.json'), JSON.stringify(merged, null, 2), 'utf8');
    
    // Auto-sync files to GitHub in background if token exists
    syncToGitHub();
  } catch (err) {
    console.error('Failed to write systemprombet backup:', err.message);
  }
}

function syncToGitHub() {
  var token = process.env.GITHUB_TOKEN;
  if (!token) {
    return; // Silently skip if no GitHub token is provided
  }
  
  var gitUrl = 'https://toxichassan22:' + token + '@github.com/toxichassan22/manafe-presentation-generator.git';
  
  // Check if git repo exists, if not initialize one (Docker container won't have .git)
  var initCmd = '';
  if (!fs.existsSync(path.join(__dirname, '.git'))) {
    initCmd = 'git init && git remote add origin ' + gitUrl + ' && git fetch origin main && git reset origin/main && ';
  }
  
  var cmd = initCmd +
            'git config user.email "toxichassan22@github.com" && ' +
            'git config user.name "toxichassan22" && ' +
            'git add -f systemprombet systemprombet.txt systemprombet.json users_db.json && ' +
            'git diff --cached --quiet && echo "No changes to commit" || ' +
            '(git commit -m "Auto-save chat history and backup [bot]" && ' +
            'git push ' + gitUrl + ' HEAD:main)';
            
  exec(cmd, { cwd: __dirname }, function(err, stdout, stderr) {
    if (err) {
      console.error('[Git Auto-Save] Sync failed:', err.message);
      if (stderr) console.error('[Git Auto-Save] stderr:', stderr);
    } else {
      console.log('[Git Auto-Save] ' + (stdout || 'Synced successfully'));
    }
  });
}

function buildMessagesWithTraining(systemContent, currentMessages, userId) {
  var MAX_HISTORY_CHARS = 4000; // Limit training history to prevent exceeding GLM context limits
  var history = getTrainingHistory(userId || 'default_user');
  var merged = [];
  
  if (systemContent) {
    merged.push({ role: 'system', content: [
        { type: 'text', text: systemContent, cache_control: { type: 'ephemeral' } }
    ]});
  }
  
  // Prepend training history messages for implicit context caching, but limit total size
  if (history && history.length > 0) {
    var historyChars = 0;
    // Use only the most recent history messages that fit within the limit
    var trimmedHistory = [];
    for (var i = history.length - 1; i >= 0; i--) {
      var msgLen = (history[i].content || '').length;
      if (historyChars + msgLen > MAX_HISTORY_CHARS) break;
      historyChars += msgLen;
      trimmedHistory.unshift(history[i]);
    }
    trimmedHistory.forEach(function(msg) {
      if (msg.role === 'user' || msg.role === 'assistant' || msg.role === 'system') {
        merged.push({ role: msg.role, content: msg.content });
      }
    });
  }
  
  // Append current prompt/messages
  currentMessages.forEach(function(msg) {
    merged.push(msg);
  });

  // Backup system prompt & conversation chat (pre-response)
  writeSystemPrombetBackup(merged, null);
  
  return merged;
}

async function callZaiChat(systemPrompt, userContent, userId, options) {
  options = options || {};
  var temperature = typeof options.temperature === 'number' ? options.temperature : 0.7;
  var maxTokens = options.maxTokens || 4000;
  var disableThinking = options.disableThinking !== undefined ? options.disableThinking : true;
  var referenceImage = options.referenceImage;

  var userMessageContent;
  if (referenceImage && typeof referenceImage === 'string' && (referenceImage.startsWith('data:image/') || referenceImage.startsWith('http'))) {
    userMessageContent = [
      { type: "text", text: userContent },
      { type: "image_url", image_url: { url: referenceImage } }
    ];
  } else {
    userMessageContent = userContent;
  }

  var promptMessages = buildMessagesWithTraining(
    systemPrompt,
    [{ role: "user", content: userMessageContent }],
    userId
  );

  var payload = {
    model: GLM_MODEL,
    messages: promptMessages,
    temperature: temperature,
    max_tokens: maxTokens
  };

  if (disableThinking) {
    payload.thinking = { type: "disabled" };
  }

  var response = await fetch(ZAI_BASE + '/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer ' + ZAI_KEY,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  var data = await response.json();
  return { data: data, messages: promptMessages };
}

// Compute Cache Status and Metrics from Z.ai API Response
function computeCacheAnalytics(responseJson, fallbackSessionId) {
  var usage = responseJson.usage;
  var cachedTokens = 0;
  var promptTokens = 0;
  var completionTokens = 0;
  var totalTokens = 0;
  
  if (usage) {
    promptTokens = usage.prompt_tokens || 0;
    completionTokens = usage.completion_tokens || 0;
    totalTokens = usage.total_tokens || 0;
    
    if (typeof usage.cached_tokens === 'number') {
      cachedTokens = usage.cached_tokens;
    } else if (usage.prompt_tokens_details && typeof usage.prompt_tokens_details.cached_tokens === 'number') {
      cachedTokens = usage.prompt_tokens_details.cached_tokens;
    }
  }
  
  var savingPercentage = 0;
  if (promptTokens > 0) {
    savingPercentage = parseFloat(((cachedTokens / promptTokens) * 100).toFixed(1));
  }
  
  var status = cachedTokens > 0 ? 'HIT' : 'MISS';
  var sessionId = responseJson.id || fallbackSessionId || 'sess_' + Math.random().toString(36).substring(2, 11);
  
  return {
    status: status,
    cached_tokens: cachedTokens,
    session_id: sessionId,
    saving_percentage: savingPercentage,
    prompt_tokens: promptTokens,
    completion_tokens: completionTokens,
    total_tokens: totalTokens
  };
}

function getMockImageUri() {
  try {
    var p = path.join(__dirname, 'mock-architecture.png');
    if (fs.existsSync(p)) {
      var data = fs.readFileSync(p);
      return 'data:image/png;base64,' + data.toString('base64');
    }
  } catch(e) {}
  return 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNmYGD4DwAEhQGDc2a8fAAAAABJRU5ErkJggg==';
}

// ═══════════════════════════════════════════════════════════════
//  EXISTING ENDPOINTS
// ═══════════════════════════════════════════════════════════════

// Serve project data
app.get('/api/project-data', function(req, res) {
  var dataPath = path.join(__dirname, 'project-data.json');
  if (fs.existsSync(dataPath)) {
    res.json(JSON.parse(fs.readFileSync(dataPath, 'utf8')));
  } else {
    res.json(null);
  }
});

// Generate presentation (existing - calls glm-designer.js)
app.post('/api/generate', function(req, res) {
  var topic = req.body.topic;
  if (!topic) {
    return res.status(400).json({ error: 'Topic is required' });
  }

  console.log('\n═══════════════════════════════════════');
  console.log('  Starting generation from web UI...');
  console.log('  Topic: ' + topic);
  console.log('═══════════════════════════════════════');

  try {
    var dataFile = path.join(__dirname, 'project-data.json');
    var cmd = 'node glm-designer.js "' + topic.replace(/"/g, '\\"') + '" ' + dataFile;
    var output = execSync(cmd, { 
      cwd: __dirname, 
      encoding: 'utf8', 
      timeout: 300000,
      stdio: ['pipe', 'pipe', 'pipe']
    });
    console.log(output);

    // Find the generated file
    var files = fs.readdirSync(path.join(__dirname, 'outputs'))
      .filter(function(f) { return f.endsWith('.pptx'); })
      .map(function(f) { 
        return { name: f, time: fs.statSync(path.join(__dirname, 'outputs', f)).mtime.getTime() }; 
      })
      .sort(function(a, b) { return b.time - a.time; });

    if (files.length > 0) {
      res.json({ 
        success: true, 
        file: files[0].name,
        downloadUrl: '/outputs/' + files[0].name
      });
    } else {
      res.json({ success: true, file: null, message: 'Generation completed but no file found' });
    }
  } catch (err) {
    console.error('Generation error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// List generated files
app.get('/api/files', function(req, res) {
  var outDir = path.join(__dirname, 'outputs');
  if (!fs.existsSync(outDir)) {
    return res.json([]);
  }
  var files = fs.readdirSync(outDir)
    .filter(function(f) { return f.endsWith('.pptx'); })
    .map(function(f) { 
      return { 
        name: f, 
        url: '/outputs/' + f,
        size: fs.statSync(path.join(outDir, f)).size,
        time: fs.statSync(path.join(outDir, f)).mtime
      }; 
    })
    .sort(function(a, b) { return new Date(b.time) - new Date(a.time); });
  res.json(files);
});

// ─────────────────────────────────────────────
//  AI Customization / Training History Endpoints
// ─────────────────────────────────────────────
app.post('/api/save-training', function(req, res) {
  var messages = req.body.messages || req.body.history;
  var userId = req.body.userId || 'default_user';
  if (!messages || !Array.isArray(messages)) {
    return res.status(400).json({ error: 'Messages array is required' });
  }
  
  try {
    saveTrainingHistory(userId, messages);
    writeSystemPrombetBackup(messages, null);
    console.log('[Training] Saved training history and backup files for user: ' + userId + ' (' + messages.length + ' messages)');
    res.json({ success: true, message: 'Training history and backup saved successfully' });
  } catch (err) {
    console.error('[Training] Save error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/get-training', function(req, res) {
  var userId = req.query.userId || 'default_user';
  try {
    var history = getTrainingHistory(userId);
    res.json({ success: true, messages: history, history: history });
  } catch (err) {
    console.error('[Training] Get error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ═══════════════════════════════════════════════════════════════
//  NEW ENDPOINTS - Called by the main index.html frontend
// ═══════════════════════════════════════════════════════════════

// ─────────────────────────────────────────────
//  1. POST /api/generate-main-image
//     Generate the main cover image via Gemini Flash
// ─────────────────────────────────────────────
app.post('/api/generate-main-image', async function(req, res) {
  var prompt = req.body.prompt;
  var referenceImage = req.body.referenceImage;
  if (!prompt) {
    return res.status(400).json({ error: 'Prompt is required' });
  }

  if (req.body.mock) {
    console.log('  [Mock Mode] Returning mock cover image');
    return res.json({ success: true, image: getMockImageUri() });
  }

  console.log('\n[Image] Generating main cover image...');
  console.log('  Prompt: ' + prompt.substring(0, 100) + '...');

  try {
    var image;
    if (referenceImage) {
      console.log('  Using uploaded image as base reference for main image...');
      image = await callImageAPIWithReference(
        referenceImage,
        prompt + '. Focus ONLY on the building itself and its architectural details. Keep the background clean and minimal, with absolutely no complex surrounding elements, no unnecessary context, no people, no busy surrounding streets, and no complex landscapes. Just the building itself. Professional architectural photography, modern luxury building, high quality, no text, no watermarks.'
      );
    } else {
      image = await callImageAPI(
        prompt + '. Focus ONLY on the building itself and its architectural details. Keep the background clean and minimal, with absolutely no complex surrounding elements, no unnecessary context, no people, no busy surrounding streets, and no complex landscapes. Just the building itself. Professional architectural photography, modern luxury building, high quality, no text, no watermarks.'
      );
    }

    if (image) {
      console.log('  ✓ Main image generated successfully');
      res.json({ success: true, image: image });
    } else {
      console.log('  ⚠ No image returned, using placeholder');
      res.json({ success: false, error: 'No image generated', image: null });
    }
  } catch (err) {
    console.error('  ✗ Main image error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  2. POST /api/generate-images
//     Generate multiple AI images (mood board)
// ─────────────────────────────────────────────
app.post('/api/generate-images', async function(req, res) {
  var prompts = req.body.prompts;
  var referenceImage = req.body.referenceImage;
  if (!prompts || !Array.isArray(prompts) || prompts.length === 0) {
    return res.status(400).json({ error: 'Prompts array is required' });
  }

  if (req.body.mock) {
    console.log('  [Mock Mode] Returning mock variant images');
    var mockImg = getMockImageUri();
    var images = prompts.map(function(p) { return { url: mockImg, prompt: p }; });
    return res.json({ success: true, images: images });
  }

  console.log('\n[Images] Generating ' + prompts.length + ' mood board images...');

  try {
    var images = [];
    var baseReference = referenceImage;

    if (baseReference) {
      console.log('  ✓ Using uploaded main image as base reference for all generated images...');
      for (var i = 0; i < prompts.length; i++) {
        console.log('  [' + (i + 1) + '/' + prompts.length + '] Generating variant from reference...');
        var img = await callImageAPIWithReference(
          baseReference,
          prompts[i] + '. Same building style, same architectural identity, professional photography, no text.'
        );
        if (img) {
          images.push({ url: img, prompt: prompts[i] });
          console.log('    ✓ Variant created');
        } else {
          // fallback to standard generation or copy reference
          var fallback = await callImageAPI(prompts[i] + '. Professional architectural photography, high quality, no text.');
          images.push({ url: fallback || baseReference, prompt: prompts[i] });
          console.log('    ✓ Fallback created');
        }
        if (i < prompts.length - 1) {
          await new Promise(function(r) { setTimeout(r, 1500); });
        }
      }
    } else {
      // No reference image, generate first one independently and use it as reference for rest
      console.log('  [1/' + prompts.length + '] Base image...');
      var firstImage = await callImageAPI(
        prompts[0] + '. Professional architectural photography, modern luxury building, high quality, no text.'
      );
      if (firstImage) {
        images.push({ url: firstImage, prompt: prompts[0] });
        console.log('    ✓ Base image created');

        for (var i = 1; i < prompts.length; i++) {
          console.log('  [' + (i + 1) + '/' + prompts.length + '] Variant image...');
          var variant = await callImageAPIWithReference(
            firstImage,
            prompts[i] + '. Same building style, same architectural identity, professional photography, no text.'
          );
          if (variant) {
            images.push({ url: variant, prompt: prompts[i] });
            console.log('    ✓ Variant created');
          } else {
            images.push({ url: firstImage, prompt: prompts[i] });
            console.log('    ✓ Used base image as fallback');
          }
          await new Promise(function(r) { setTimeout(r, 1500); });
        }
      } else {
        // If first image fails, generate all independently
        for (var i = 0; i < prompts.length; i++) {
          console.log('  [' + (i + 1) + '/' + prompts.length + '] Independent image...');
          var img = await callImageAPI(
            prompts[i] + '. Professional architectural photography, high quality, no text.'
          );
          images.push({ url: img, prompt: prompts[i] });
          if (i < prompts.length - 1) {
            await new Promise(function(r) { setTimeout(r, 1500); });
          }
        }
      }
    }

    console.log('  ✓ Generated ' + images.filter(function(x) { return x.url; }).length + '/' + prompts.length + ' images');
    res.json({ success: true, images: images });
  } catch (err) {
    console.error('  ✗ Images error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  3. POST /api/edit-deck-data
//     AI-powered editing of project form data
// ─────────────────────────────────────────────
app.post('/api/edit-deck-data', async function(req, res) {
  var editRequest = req.body.request;
  var projectData = req.body.data;
  var userId = req.body.userId || 'default_user';

  if (!editRequest) {
    return res.status(400).json({ error: 'Edit request is required' });
  }

  console.log('\n[Edit] AI deck data edit...');
  console.log('  Request: ' + editRequest.substring(0, 100));

  try {
    var systemPrompt = `You are a professional investment project data editor for "منافع الاقتصادية" (Manafe).
The user will give you a request to modify project data fields. You must return the COMPLETE modified data as JSON.

RULES:
- Return ONLY valid JSON, no markdown, no code blocks
- Keep all existing fields intact unless the user specifically asks to change them
- For array fields (locationFeatures, projectFeatures, investmentHighlights, risks, components, timelineRows), maintain the same structure
- Use Arabic text when editing Arabic fields
- Make smart improvements based on the user's request
- Return the FULL data object with all fields`;

    var userMessage = 'PROJECT DATA:\n' + JSON.stringify(projectData, null, 2) + '\n\nEDIT REQUEST:\n' + editRequest;
    
    var { data, messages } = await callZaiChat(systemPrompt, userMessage, userId, {
      referenceImage: projectData ? projectData.mainImageData : null
    });

    if (!data.choices || !data.choices[0]) {
      throw new Error('GLM failed: ' + JSON.stringify(data));
    }

    var cacheAnalytics = computeCacheAnalytics(data, 'edit_deck_' + Date.now());
    if (data.usage) {
      var u = data.usage;
      console.log('  ✓ Tokens: ' + u.total_tokens + ' | Cache: ' + cacheAnalytics.status + ' (' + cacheAnalytics.cached_tokens + ' tokens)');
    }

    var resultText = data.choices[0].message.content.trim();
    
    // Backup the full conversation (including the AI response)
    writeSystemPrombetBackup(messages, resultText);

    // Try to extract JSON from the response
    var jsonMatch = resultText.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      var editedData = JSON.parse(jsonMatch[0]);
      console.log('  ✓ Data edited successfully');
      res.json({ success: true, data: editedData, cache_analytics: cacheAnalytics });
    } else {
      throw new Error('Could not parse AI response as JSON');
    }
  } catch (err) {
    console.error('  ✗ Edit error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  4. POST /api/ai-edit-slide
//     AI-powered single slide content editing
// ─────────────────────────────────────────────
app.post('/api/ai-edit-slide', async function(req, res) {
  var slideTitle = req.body.slideTitle;
  var slideContent = req.body.slideContent;
  var editRequest = req.body.editRequest;
  var projectData = truncateProjectData(req.body.projectData, 8000);
  var userId = req.body.userId || 'default_user';

  if (!editRequest) {
    return res.status(400).json({ error: 'Edit request is required' });
  }

  console.log('\n[SlideEdit] Editing slide: ' + slideTitle);
  console.log('  Request: ' + editRequest.substring(0, 100));

  try {
    var systemPrompt = `You are a professional presentation content editor for "منافع الاقتصادية" (Manafe).
You edit individual slide content based on user requests.

RULES:
- Return a JSON object with: { "title": "slide title", "content": "new HTML content for the slide", "bullets": ["bullet1", "bullet2"] }
- The content should be HTML that works inside a div
- Keep the same style and language as the original
- Make smart improvements based on the user's request
- For investment project slides, maintain professional tone in Arabic
- Return ONLY valid JSON, no markdown`;

    var userMessage = 'SLIDE TITLE: ' + slideTitle + '\n\nCURRENT CONTENT:\n' + slideContent + '\n\nPROJECT DATA CONTEXT:\n' + JSON.stringify(projectData || {}, null, 2) + '\n\nEDIT REQUEST:\n' + editRequest;

    var { data, messages } = await callZaiChat(systemPrompt, userMessage, userId, {
      referenceImage: projectData ? projectData.mainImageData : null
    });

    if (!data.choices || !data.choices[0]) {
      throw new Error('GLM failed: ' + JSON.stringify(data));
    }

    var cacheAnalytics = computeCacheAnalytics(data, 'edit_slide_' + Date.now());
    var resultText = data.choices[0].message.content.trim();

    // Backup the full conversation (including the AI response)
    writeSystemPrombetBackup(messages, resultText);

    var jsonMatch = resultText.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      var edited = JSON.parse(jsonMatch[0]);
      console.log('  ✓ Slide edited successfully | Cache: ' + cacheAnalytics.status);
      res.json({ success: true, data: edited, cache_analytics: cacheAnalytics });
    } else {
      throw new Error('Could not parse AI response');
    }
  } catch (err) {
    console.error('  ✗ Slide edit error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  5. POST /api/ai-chat
//     General AI chat for slide editing
// ─────────────────────────────────────────────
app.post('/api/ai-chat', async function(req, res) {
  var message = req.body.message;
  var slidesData = req.body.slidesData;
  var currentSlideIdx = req.body.currentSlideIdx;
  var projectData = truncateProjectData(req.body.projectData, 8000);
  var userId = req.body.userId || 'default_user';

  if (!message) {
    return res.status(400).json({ error: 'Message is required' });
  }

  console.log('\n[Chat] AI chat message...');
  console.log('  Message: ' + message.substring(0, 100));

  try {
    var systemPrompt = `أنت محرر عروض تقديمية احترافي لشركة "منافع الاقتصادية" (Manafe).
تساعد المستخدمين في تحرير وتحسين عروض مشاريعهم الاستثمارية.

يمكنك:
1. تعديل محتوى الشرائح بناءً على الطلبات
2. اقتراح تحسينات وتعديلات تصميمية عامة (ألوان، حجم الخط، المحاذاة، الهوامش)
3. توليد محتوى جديد
4. الإجابة عن أسئلة حول المشروع

IMPORTANT RULES FOR APPLYING INSTRUCTIONS TO ALL SLIDES:
- When the user asks to change design/style/colors/fonts that should apply to ALL slides, you MUST:
  1. Respond with "style_override" action
  2. Make sure the CSS covers ALL slide elements (not just one slide)
  3. Explain clearly that the change will be applied to ALL slides in the presentation

When the user asks to modify the design/style/layout/colors/fonts (which will apply to the PDF export), respond with:
{ "action": "style_override", "css": "CSS rules to inject, e.g. .ge-slide-title { color: #C4A35A !important; } .ge-slide-card { border-color: #C4A35A !important; }", "response": "Message in Arabic explaining that this style change will be applied to ALL slides in the presentation" }

When the user asks you to edit slide content, respond with:
{ "action": "edit", "slideIdx": <number>, "changes": { "title": "new title if changed", "content": "new HTML content" } }

When the user asks you to edit multiple slides, respond with:
{ "action": "edit_multiple", "updates": [ { "slideIdx": <number>, "changes": { "title": "new title if changed", "content": "new HTML content" } } ], "response": "Message in Arabic explaining the edits" }

When the user asks a question or wants suggestions, respond with:
{ "action": "chat", "response": "your response in Arabic" }

Always respond in Arabic unless asked otherwise.
Return ONLY valid JSON.`;

    var contextData = {
      currentSlide: currentSlideIdx,
      message: message
    };
    if (slidesData) {
      contextData.slides = slidesData.map(function(s, i) {
        return { idx: i, title: s.title, contentPreview: (s.content || '').substring(0, 200) };
      });
    }

    var userMessage = 'PROJECT DATA:\n' + JSON.stringify(projectData || {}, null, 2) + '\n\nSLIDES CONTEXT:\n' + JSON.stringify(contextData, null, 2) + '\n\nUSER MESSAGE:\n' + message;

    var { data, messages } = await callZaiChat(systemPrompt, userMessage, userId, {
      referenceImage: projectData ? projectData.mainImageData : null
    });

    if (!data.choices || !data.choices[0]) {
      throw new Error('GLM failed: ' + JSON.stringify(data));
    }

    var cacheAnalytics = computeCacheAnalytics(data, 'chat_' + Date.now());
    var resultText = data.choices[0].message.content.trim();

    // Backup the full conversation (including the AI response)
    writeSystemPrombetBackup(messages, resultText);

    var jsonMatch = resultText.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      var result = JSON.parse(jsonMatch[0]);
      console.log('  ✓ Chat response generated | Cache: ' + cacheAnalytics.status);
      res.json({ success: true, data: result, cache_analytics: cacheAnalytics });
    } else {
      // If not JSON, return as plain chat response
      res.json({ success: true, data: { action: 'chat', response: resultText }, cache_analytics: cacheAnalytics });
    }
  } catch (err) {
    console.error('  ✗ Chat error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  6. POST /api/generate-slide-image
//     Generate a single image for a specific slide
// ─────────────────────────────────────────────
app.post('/api/generate-slide-image', async function(req, res) {
  var prompt = req.body.prompt;
  var referenceImage = req.body.referenceImage;

  if (!prompt) {
    return res.status(400).json({ error: 'Prompt is required' });
  }

  if (req.body.mock) {
    console.log('  [Mock Mode] Returning mock slide image');
    return res.json({ success: true, image: getMockImageUri() });
  }

  console.log('\n[SlideImage] Generating slide image...');

  try {
    var image;
    if (referenceImage) {
      image = await callImageAPIWithReference(
        referenceImage,
        prompt + '. Focus ONLY on the building itself and its architectural details. Keep the background clean and minimal, with absolutely no complex surrounding elements, no unnecessary context, no people, no busy surrounding streets, and no complex landscapes. Just the building itself. Same building style, professional architectural photography, high quality, no text.'
      );
    } else {
      image = await callImageAPI(
        prompt + '. Focus ONLY on the building itself and its architectural details. Keep the background clean and minimal, with absolutely no complex surrounding elements, no unnecessary context, no people, no busy surrounding streets, and no complex landscapes. Just the building itself. Professional architectural photography, high quality, no text, no watermarks.'
      );
    }

    if (image) {
      console.log('  ✓ Slide image generated');
      res.json({ success: true, image: image });
    } else {
      res.json({ success: false, error: 'No image generated' });
    }
  } catch (err) {
    console.error('  ✗ Slide image error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  7. POST /api/generate-outline
//     GLM 5.1 generates outline structure (slide titles + bullets)
// ─────────────────────────────────────────────
app.post('/api/generate-outline', async function(req, res) {
  var projectData = truncateProjectData(req.body.projectData, 4000);
  var userId = req.body.userId || 'default_user';
  var totalSlides = parseInt(req.body.slideCount) || 16;

  if (totalSlides < 3) totalSlides = 3;
  var contentCount = totalSlides - 2;

  console.log('\n[Outline] Generating ' + contentCount + ' content slides for ' + totalSlides + ' total slides...');

  try {
    var allTopics = [
      "الملخص التنفيذي",
      "فكرة المشروع والهيكلة",
      "مميزات الموقع",
      "مميزات المشروع",
      "مكونات المشروع والمساحات",
      "افتراضات الربح التشغيلي التأجيري",
      "افتراضات التكاليف",
      "الأرباح والتخارج",
      "المؤشرات المالية المتوقعة",
      "الجدول الزمني ومراحل المشروع",
      "فرص الاستثمار ونقاط القوة",
      "المخاطر والافتراضات"
    ];

    var systemContent = 'أنت خبير في إعداد عروض تقديمية استثمارية احترافية لشركات العقارات والاستثمار في السعودية.\n\n' +
      'العرض التقديمي يحتوي على ' + totalSlides + ' شريحة بالكامل:\n' +
      '- الشريحة 1 = غلاف (لا تحتاج عنوان - ستولّد تلقائياً)\n' +
      '- الشريحة ' + totalSlides + ' = ختام (لا تحتاج عنوان - ستولّد تلقائياً)\n' +
      '- الشريحتان 2 إلى ' + (totalSlides - 1) + ' = شرائح محتوى (هنا تضع أنت العناوين والنقاط)\n\n' +
      'مهمتك: ولّد ' + contentCount + ' عنوان شريحة محتوى مع النقاط الأساسية.\n\n' +
      'اختر من هذه المواضيع (' + contentCount + ' فقط):\n' +
      allTopics.map(function(t, i) { return (i + 1) + '. ' + t; }).join('\n') + '\n\n' +
      'أعد النتيجة كـ JSON فقط بدون أي نص إضافي بالشكل:\n' +
      '{"slides": [{"title": "عنوان الشريحة", "bullets": ["نقطة 1", "نقطة 2"], "requires_image": true أو false}]}\n\n' +
      'قواعد:\n' +
      '1. ولّد بالضبط ' + contentCount + ' عناوين (لا أكثر ولا أقل)\n' +
      '2. حدد requires_image: true لـ 3 شرائح بصرية كحد أقصى (صور الموقع ومميزات المشروع ومكوناته)\n' +
      '3. باقي الشرائح requires_image: false\n' +
      '4. لا تضع عناوين للغلاف أو الختام\n' +
      '5. اجعل النقاط مختصرة واحترافية';

    var userContent = 'بيانات المشروع:\n' + JSON.stringify(projectData || {}, null, 2);

    var { data, messages } = await callZaiChat(systemContent, userContent, userId, {
      maxTokens: 2500,
      referenceImage: projectData ? projectData.mainImageData : null
    });

    if (!data.choices || !data.choices[0]) {
      throw new Error('GLM failed: ' + JSON.stringify(data));
    }

    var cacheAnalytics = computeCacheAnalytics(data, 'outline_' + Date.now());
    var resultText = data.choices[0].message.content.trim();
    writeSystemPrombetBackup(messages, resultText);

    var jsonMatch = resultText.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      var result = JSON.parse(jsonMatch[0]);
      var slides = result.slides || [];
      if (slides.length > contentCount) {
        slides = slides.slice(0, contentCount);
      }
      console.log('  ✓ Outline generated: ' + slides.length + ' content slides for ' + totalSlides + ' total | Cache: ' + cacheAnalytics.status);
      res.json({ success: true, outline: slides, totalSlides: totalSlides, cache_analytics: cacheAnalytics });
    } else {
      throw new Error('No JSON in GLM response');
    }
  } catch (err) {
    console.error('  ✗ Outline generation error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  7b. POST /api/generate-titles
//      Fast: returns just slide titles (no bullets)
// ─────────────────────────────────────────────
app.post('/api/generate-titles', async function(req, res) {
  var projectData = truncateProjectData(req.body.projectData, 4000);
  var userId = req.body.userId || 'default_user';
  var totalSlides = parseInt(req.body.slideCount) || 16;

  if (totalSlides < 3) totalSlides = 3;
  var contentCount = totalSlides - 4; // cover + toc + moodboard + closing are fixed

  if (req.body.mock) {
    console.log('  [Mock Mode] Returning mock titles for ' + totalSlides + ' slides (cover + toc + ' + contentCount + ' content + moodboard + closing)');
    var allMockTitles = [
      { title: 'غلاف المشروع', requires_image: true, type: 'cover' },
      { title: 'الفهرس', requires_image: false, type: 'toc' },
      { title: 'الملخص التنفيذي', requires_image: false, type: 'content' },
      { title: 'فكرة المشروع والهيكلة', requires_image: false, type: 'content' },
      { title: 'مميزات الموقع', requires_image: true, type: 'content' },
      { title: 'مميزات المشروع', requires_image: true, type: 'content' },
      { title: 'مكونات المشروع والمساحات', requires_image: true, type: 'content' },
      { title: 'افتراضات الربح التشغيلي التأجيري', requires_image: false, type: 'content' },
      { title: 'افتراضات التكاليف', requires_image: false, type: 'content' },
      { title: 'الأرباح والتخارج', requires_image: false, type: 'content' },
      { title: 'المؤشرات المالية المتوقعة', requires_image: false, type: 'content' },
      { title: 'الجدول الزمني ومراحل المشروع', requires_image: false, type: 'content' },
      { title: 'فرص الاستثمار ونقاط القوة', requires_image: false, type: 'content' },
      { title: 'المخاطر والافتراضات', requires_image: false, type: 'content' },
      { title: 'معاينة الهوية البصرية', requires_image: true, type: 'moodboard' },
      { title: 'ختام العرض', requires_image: false, type: 'closing' }
    ];
    return res.json({
      success: true,
      titles: allMockTitles,
      totalSlides: allMockTitles.length,
      cache_analytics: { status: "MOCKED", cached_tokens: 0, total_tokens: 0 }
    });
  }

  console.log('\n[Titles] Generating ' + totalSlides + ' titles (cover + toc + ' + contentCount + ' content + moodboard + closing)...');
  var startTime = Date.now();

  try {
    var allTopics = [
      "الملخص التنفيذي",
      "فكرة المشروع والهيكلة",
      "مميزات الموقع",
      "مميزات المشروع",
      "مكونات المشروع والمساحات",
      "افتراضات الربح التشغيلي التأجيري",
      "افتراضات التكاليف",
      "الأرباح والتخارج",
      "المؤشرات المالية المتوقعة",
      "الجدول الزمني ومراحل المشروع",
      "فرص الاستثمار ونقاط القوة",
      "المخاطر والافتراضات"
    ];

    var systemContent = 'أنت خبير في العروض التقديمية الاستثمارية.\n\n' +
      'العرض التقديمي يحتوي على ' + totalSlides + ' شريحة بالكامل:\n' +
      '- الشريحة 1 = غلاف (لا تحتاج عنوان - ستولّد تلقائياً)\n' +
      '- الشريحة 2 = فهرس (لا تحتاج عنوان - ستولّد تلقائياً)\n' +
      '- الشريحة ' + (totalSlides - 1) + ' = مود بورد (لا تحتاج عنوان - ستولّد تلقائياً)\n' +
      '- الشريحة ' + totalSlides + ' = ختام (لا تحتاج عنوان - ستولّد تلقائياً)\n' +
      '- الشريحتان 3 إلى ' + (totalSlides - 2) + ' = شرائح محتوى (هنا تضع أنت العناوين)\n\n' +
      'مهمتك: ولّد ' + contentCount + ' عنوان شريحة محتوى مناسبة لهذا العرض الاستثماري.\n\n' +
      'اختر من هذه المواضيع (' + contentCount + ' فقط):\n' +
      allTopics.map(function(t, i) { return (i + 1) + '. ' + t; }).join('\n') + '\n\n' +
      'أعد النتيجة كـ JSON فقط بالصيغة:\n' +
      '{"titles": [{"title": "عنوان الشريحة", "requires_image": true أو false}]}\n\n' +
      'قواعد:\n' +
      '1. ولّد بالضبط ' + contentCount + ' عناوين (لا أكثر ولا أقل)\n' +
      '2. حدد requires_image: true لـ 3 شرائح بصرية كحد أقصى (صور الموقع ومميزات المشروع ومكوناته)\n' +
      '3. باقي الشرائح requires_image: false\n' +
      '4. لا تضع عناوين للغلاف أو الفهرس أو المود بورد أو الختام — هي تلقائية';

    var userContent = 'بيانات المشروع:\n' + JSON.stringify(projectData || {}, null, 2);

    var { data, messages } = await callZaiChat(systemContent, userContent, userId, {
      maxTokens: 1500,
      disableThinking: true,
      referenceImage: projectData ? projectData.mainImageData : null
    });

    if (!data.choices || !data.choices[0]) throw new Error('GLM failed: ' + JSON.stringify(data));

    var cacheAnalytics = computeCacheAnalytics(data, 'titles_' + Date.now());
    var text = (data.choices[0].message.content || '').trim();
    writeSystemPrombetBackup(messages, text);

    var match = text.match(/\{[\s\S]*\}/);
    if (!match) throw new Error('No JSON in response');

    var result = JSON.parse(match[0]);
    var titles = result.titles || result.slides || [];

    if (titles.length > contentCount) {
      titles = titles.slice(0, contentCount);
    }

    // Add all 16 titles: cover + toc + content + moodboard + closing
    var finalTitles = [
      { title: 'غلاف المشروع', requires_image: true, type: 'cover' },
      { title: 'الفهرس', requires_image: false, type: 'toc' }
    ];
    titles.forEach(function(t) {
      if (typeof t === 'string') {
        finalTitles.push({ title: t, requires_image: false, type: 'content' });
      } else {
        t.type = 'content';
        finalTitles.push(t);
      }
    });
    finalTitles.push({ title: 'معاينة الهوية البصرية', requires_image: true, type: 'moodboard' });
    finalTitles.push({ title: 'ختام العرض', requires_image: false, type: 'closing' });

    console.log('  ✓ Got ' + finalTitles.length + ' titles (cover + toc + ' + titles.length + ' content + moodboard + closing) | Cache: ' + cacheAnalytics.status);
    res.json({ success: true, titles: finalTitles, totalSlides: finalTitles.length, cache_analytics: cacheAnalytics });
  } catch (err) {
    console.error('  ✗ Titles error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  7b2. POST /api/official-outline
//       Returns a fixed official outline (no AI call)
// ─────────────────────────────────────────────
app.post('/api/official-outline', async function(req, res) {
  var projectData = req.body.projectData || {};
  var totalSlides = 16;

  console.log('\n[Official Outline] Returning fixed official outline for ' + totalSlides + ' slides...');

  var officialTitles = [
    { title: 'غلاف المشروع', requires_image: true, type: 'cover', bullets: [] },
    { title: 'الفهرس', requires_image: false, type: 'toc', bullets: [] },
    { title: 'الملخص التنفيذي', requires_image: false, type: 'content', bullets: [
      'نظرة عامة على المشروع والأهداف الرئيسية',
      'إجمالي التكلفة والعائد المتوقع',
      'التوصية النهائية للمستثمرين'
    ]},
    { title: 'فكرة المشروع والهيكلة', requires_image: false, type: 'content', bullets: [
      'تعريف المشروع ورسالته',
      'هيكلة المشروع والunits المختلفة',
      'الجهة المطورة والخبرات'
    ]},
    { title: 'مميزات الموقع', requires_image: true, type: 'content', bullets: [
      'الموقع الجغرافي والاستراتيجي',
      'البنية التحتية المحيطة',
      'سهولة الوصول والمواصلات'
    ]},
    { title: 'مميزات المشروع', requires_image: true, type: 'content', bullets: [
      'التصميم المعماري والعصري',
      'المرافق والتجهيزات الفاخرة',
      'نظام الأمان والتشغيل الذكي'
    ]},
    { title: 'مكونات المشروع والمساحات', requires_image: false, type: 'content', bullets: [
      'تفصيل الوحدات السكنية والتجارية',
      'المساحات المبنية والتأجيرية',
      'أسعار الإيجار المقدرة'
    ]},
    { title: 'افتراضات الربح التشغيلي التأجيري', requires_image: false, type: 'content', bullets: [
      'متوسط إيجار المتر ورسوم الخدمات',
      'الإيرادات السنوية المتوقعة',
      'المصروف التشغيلي السنوي'
    ]},
    { title: 'افتراضات التكاليف', requires_image: false, type: 'content', bullets: [
      'تكلفة الأرض والتطوير',
      'إجمالي التكلفة الاستثمارية',
      'هيكل التمويل المتوقع'
    ]},
    { title: 'الأرباح والتخارج', requires_image: false, type: 'content', bullets: [
      'الربح التشغيلي طوال فترة المشروع',
      'قيمة التخارج المتوقعة',
      'معامل الرسملة وال returns'
    ]},
    { title: 'المؤشرات المالية المتوقعة', requires_image: false, type: 'content', bullets: [
      'نسبة العائد السنوي على الاستثمار',
      'نسبة صافي الربح التشغيلي NOI',
      'فترة استرداد رأس المال'
    ]},
    { title: 'الجدول الزمني ومراحل المشروع', requires_image: false, type: 'content', bullets: [
      'مراحل التصميم والتصاريح',
      'مراحل البناء والتشطيبات',
      'موعد التسليم والتشغيل'
    ]},
    { title: 'فرص الاستثمار ونقاط القوة', requires_image: false, type: 'content', bullets: [
      'الطلب المتزايد في المنطقة',
      'العائد الإيجالي المرتفع',
      'فرصة ارتفاع القيمة'
    ]},
    { title: 'المخاطر والافتراضات', requires_image: false, type: 'content', bullets: [
      'مخاطر الترخيص والتأخير',
      'تقلبات أسعار البناء',
      'مخاطر السوق والمنافسة'
    ]},
    { title: 'معاينة الهوية البصرية', requires_image: true, type: 'moodboard', bullets: [
      'لوحة الألوان والهوية البصرية',
      'نمط التصميم المعماري',
      'الصور التوضيحية للمشروع'
    ]},
    { title: 'الختام', requires_image: false, type: 'closing', bullets: [] }
  ];

  res.json({
    success: true,
    titles: officialTitles,
    totalSlides: totalSlides,
    cache_analytics: { status: "FIXED", cached_tokens: 0, total_tokens: 0 }
  });
});

// ─────────────────────────────────────────────
//  7c. POST /api/generate-bullets
//      Returns bullets for multiple slides in parallel
// ─────────────────────────────────────────────
app.post('/api/generate-bullets', async function(req, res) {
  var projectData = truncateProjectData(req.body.projectData, 4000);
  var slides = req.body.slides || []; // [{index, title}, ...]
  var userId = req.body.userId || 'default_user';

  if (req.body.mock) {
    console.log('  [Mock Mode] Returning mock bullets for ' + slides.length + ' slides');
    var mockResults = slides.map(function(s) {
      var bullets = [];
      if (s.title === "مميزات الموقع") {
        bullets = [
          "موقع استراتيجي وحيوي لتسهيل الوصول والتنقل.",
          "قريب من الشوارع الرئيسية ومحاور الحركة بجدة.",
          "رابط الموقع الجغرافي للمشروع متوفر مباشرة عبر قوقل ماب."
        ];
        if (projectData && projectData.googleMapsLink) {
          bullets.push("رابط قوقل ماب: " + projectData.googleMapsLink);
        }
      } else if (s.title === "غلاف المشروع") {
        bullets = [
          "مشروع استثماري واعد.",
          "تم الإعداد بواسطة منافع الاقتصادية."
        ];
      } else {
        bullets = [
          "نقطة تجريبية أولى توضح الأهمية التشغيلية للمشروع.",
          "نقطة تجريبية ثانية تدعم نموذج العمل والعوائد الاستثمارية.",
          "نقطة تجريبية ثالثة لتقييم المخاطر والمؤشرات المالية للموقع."
        ];
      }
      return { index: s.index, title: s.title, bullets: bullets };
    });
    return res.json({
      success: true,
      slides: mockResults,
      cache_analytics: { status: "MOCKED", cached_tokens: 0, total_tokens: 0 }
    });
  }

  console.log('\n[Bullets] Generating bullets for ' + slides.length + ' slides...');

  try {
    var promises = slides.map(function(slide) {
      var systemContent = 'أنت خبير في العروض التقديمية الاستثمارية. أنشئ 3-5 نقاط مختصرة واحترافية لهذه الشريحة. إذا كانت الشريحة هي "مميزات الموقع" وكان هناك رابط قوقل ماب (googleMapsLink) في بيانات المشروع، أضف نقطة تحتوي على رابط قوقل ماب المعطى بوضوح.\n\nأعد النتيجة كـ JSON فقط:\n{"bullets": ["نقطة 1", "نقطة 2", "نقطة 3"]}';
      var userContent = 'بيانات المشروع:\n' + JSON.stringify(projectData || {}, null, 2) + '\n\nعنوان الشريحة: ' + slide.title;

      return callZaiChat(systemContent, userContent, userId, {
        maxTokens: 1000,
        disableThinking: true,
        referenceImage: projectData ? projectData.mainImageData : null
      }).then(function(result) {
        var d = result.data;
        var m = (d.choices && d.choices[0] && d.choices[0].message) ? d.choices[0].message : {};
        var text = (m.content || '').trim();
        var jm = text.match(/\{[\s\S]*\}/);
        var bullets = [];
        if (jm) { try { bullets = JSON.parse(jm[0]).bullets || []; } catch(e) {} }
        return { index: slide.index, title: slide.title, bullets: bullets, usage: d.usage, id: d.id };
      }).catch(function(err) {
        console.error('  ✗ Bullet error ' + slide.index + ':', err.message);
        return { index: slide.index, title: slide.title, bullets: [], usage: null, id: null };
      });
    });

    var results = await Promise.all(promises);
    results.sort(function(a, b) { return a.index - b.index; });

    // Consolidate caching analytics across parallel requests
    var totalPromptTokens = 0;
    var totalCachedTokens = 0;
    var totalCompletionTokens = 0;
    var totalTokensCount = 0;
    var sessionIds = [];

    results.forEach(function(r) {
      if (r.usage) {
        totalPromptTokens += r.usage.prompt_tokens || 0;
        totalCompletionTokens += r.usage.completion_tokens || 0;
        totalTokensCount += r.usage.total_tokens || 0;

        var cached = 0;
        if (typeof r.usage.cached_tokens === 'number') {
          cached = r.usage.cached_tokens;
        } else if (r.usage.prompt_tokens_details && typeof r.usage.prompt_tokens_details.cached_tokens === 'number') {
          cached = r.usage.prompt_tokens_details.cached_tokens;
        }
        totalCachedTokens += cached;
      }
      if (r.id) {
        sessionIds.push(r.id);
      }
      // Remove details to keep API clean
      delete r.usage;
      delete r.id;
    });

    var savingPercentage = 0;
    if (totalPromptTokens > 0) {
      savingPercentage = parseFloat(((totalCachedTokens / totalPromptTokens) * 100).toFixed(1));
    }

    var cacheAnalytics = {
      status: totalCachedTokens > 0 ? 'HIT' : 'MISS',
      cached_tokens: totalCachedTokens,
      session_id: sessionIds.length > 0 ? sessionIds[0] : 'bullets_' + Date.now(),
      saving_percentage: savingPercentage,
      prompt_tokens: totalPromptTokens,
      completion_tokens: totalCompletionTokens,
      total_tokens: totalTokensCount
    };

    console.log('  ✓ Got bullets for ' + results.length + ' slides | Cache: ' + cacheAnalytics.status + ' (' + cacheAnalytics.cached_tokens + ' tokens)');
    res.json({ success: true, slides: results, cache_analytics: cacheAnalytics });
  } catch (err) {
    console.error('  ✗ Bullets error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  8. POST /api/generate-content
//     GLM 5.1 writes full content for all slides
// ─────────────────────────────────────────────
app.post('/api/generate-content', async function(req, res) {
  var projectData = truncateProjectData(req.body.projectData, 4000);
  var outline = req.body.outline;
  var userId = req.body.userId || 'default_user';

  // Truncate outline to prevent exceeding GLM context limits
  if (outline && outline.length > 0) {
    outline = outline.map(function(s) {
      return {
        title: s.title || '',
        bullets: Array.isArray(s.bullets) ? s.bullets.slice(0, 4) : (s.bullets || ''),
        content: typeof s.content === 'string' ? s.content.substring(0, 500) : s.content
      };
    });
  }

  if (req.body.mock) {
    console.log('  [Mock Mode] Returning mock HTML content for slides');
    var mockSlides = outline.map(function(s, idx) {
      var html = '<div class="ge-slide-title">' + s.title + '</div>';
      html += '<div class="ge-slide-subtitle">تفاصيل وبنية الشريحة الاستثمارية ' + (idx + 1) + '</div>';
      
      if (s.title === "مميزات الموقع" && projectData && projectData.googleMapsLink) {
        html += '<div class="ge-slide-body">';
        html += '<ul>';
        if (s.bullets && s.bullets.length > 0) {
          s.bullets.forEach(function(b) {
            html += '<li>' + b + '</li>';
          });
        }
        html += '</ul>';
        html += '<div style="margin-top: 15px;">';
        html += '<a href="' + projectData.googleMapsLink + '" target="_blank" class="ge-maps-btn" style="display:inline-block; padding:10px 20px; background:#7A0C0C; color:#fff; text-decoration:none; border-radius:8px; font-weight:bold;">📍 فتح موقع المشروع على Google Maps</a>';
        html += '</div>';
        html += '</div>';
      } else {
        html += '<div class="ge-slide-body">';
        html += '<ul>';
        if (s.bullets && s.bullets.length > 0) {
          s.bullets.forEach(function(b) {
            html += '<li>' + b + '</li>';
          });
        } else {
          html += '<li>نقطة استثمارية أولى توضح الرؤية والأهداف.</li>';
          html += '<li>نقطة استثمارية ثانية لتحليل المؤشرات والعوائد.</li>';
          html += '<li>نقطة استثمارية ثالثة لتقييم فرص النمو المتاحة.</li>';
        }
        html += '</ul>';
        html += '</div>';
      }
      return { title: s.title, content: html };
    });
    return res.json({
      success: true,
      slides: mockSlides,
      cache_analytics: { status: "MOCKED", cached_tokens: 0, total_tokens: 0 }
    });
  }

  console.log('\n[Content] Generating full slide content via GLM 5.1...');

  try {
    var systemContent = 'أنت كاتب محتوى احترافي للعروض التقديمية الاستثمارية. مهمتك كتابة محتوى كامل ومفصل لكل شريحة في العرض التقديمي. إذا كانت الشريحة هي مميزات الموقع وتم توفير رابط قوقل ماب googleMapsLink في بيانات المشروع، قم بإنشاء زر أو رابط تشعبي HTML واضح (باستخدام <a href="..." target="_blank">) لعرض موقع المشروع على قوقل ماب.\n\nأعد النتيجة كـ JSON فقط بدون أي نص إضافي بالشكل:\n{\n  "slides": [\n    {\n      "title": "عنوان الشريحة",\n      "content": "<div class=\\"ge-slide-title\\">العنوان</div><div class=\\"ge-slide-subtitle\\">العنوان الفرعي</div><div class=\\"ge-slide-body\\"><ul><li>نقطة 1</li><li>نقطة 2</li></ul></div>"\n    }\n  ]\n}\n\nكل شريحة يجب أن تحتوي على:\n- title: العنوان الرئيسي المختصر\n- content: HTML markup بتنسيق احترافي يستخدم CSS classes: ge-slide-title, ge-slide-subtitle, ge-slide-body, ge-slide-metrics, ge-metric, ge-metric-label, ge-metric-value\n\nاكتب محتوى عربي احترافي ومفصل. استخدم الأرقام والبيانات المالية من بيانات المشروع.';

    var userContent = 'بيانات المشروع:\n' + JSON.stringify(projectData || {}, null, 2) + '\n\nهيكل العرض (Outline):\n' + JSON.stringify(outline || [], null, 2);

    var { data, messages } = await callZaiChat(systemContent, userContent, userId, {
      maxTokens: 6000,
      referenceImage: projectData ? projectData.mainImageData : null
    });

    if (!data.choices || !data.choices[0]) {
      throw new Error('GLM failed: ' + JSON.stringify(data));
    }

    var cacheAnalytics = computeCacheAnalytics(data, 'content_' + Date.now());
    var resultText = data.choices[0].message.content.trim();
    writeSystemPrombetBackup(messages, resultText);

    var jsonMatch = resultText.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      var jsonStr = jsonMatch[0];
      var result = null;
      // Try to parse, with auto-repair for truncated JSON
      try {
        result = JSON.parse(jsonStr);
      } catch (parseErr) {
        console.log('  ⚠ JSON parse failed, attempting auto-repair...');
        // Try to extract individual slide objects with regex
        var slideRegex = /\{[^{}]*"title"[^{}]*"content"[^{}]*\}/g;
        var slides = [];
        var match;
        while ((match = slideRegex.exec(jsonStr)) !== null) {
          try {
            var slide = JSON.parse(match[0]);
            slides.push(slide);
          } catch (e) {
            // Skip malformed slides
          }
        }
        if (slides.length > 0) {
          result = { slides: slides };
          console.log('  ⚠ Auto-repaired JSON: recovered ' + slides.length + ' slides');
        } else {
          // Last resort: try to find slides array content
          var slidesStart = jsonStr.indexOf('"slides"');
          if (slidesStart !== -1) {
            var partialSlides = jsonStr.substring(slidesStart);
            var objRegex = /\{[^{}]*\}/g;
            while ((match = objRegex.exec(partialSlides)) !== null) {
              try {
                var slide = JSON.parse(match[0]);
                if (slide.title) slides.push(slide);
              } catch (e) {}
            }
            if (slides.length > 0) {
              result = { slides: slides };
              console.log('  ⚠ Last-resort repair: recovered ' + slides.length + ' slides');
            }
          }
        }
      }
      if (result) {
        console.log('  ✓ Content generated for ' + (result.slides || []).length + ' slides | Cache: ' + cacheAnalytics.status);
        res.json({ success: true, slides: result.slides || [], cache_analytics: cacheAnalytics });
      } else {
        throw new Error('No JSON in GLM response');
      }
    } else {
      throw new Error('No JSON in GLM response');
    }
  } catch (err) {
    console.error('  ✗ Content generation error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  9. POST /api/organize-text
//     GLM 5.1 organizes raw text across slides
// ─────────────────────────────────────────────
app.post('/api/organize-text', async function(req, res) {
  var projectData = truncateProjectData(req.body.projectData, 4000);
  var rawText = req.body.rawText;
  var userId = req.body.userId || 'default_user';

  if (rawText && rawText.length > 3000) {
    rawText = rawText.substring(0, 3000) + '\n... [تم اختصار النص]';
  }
  var outline = req.body.outline;

  console.log('\n[Organize] Organizing text across slides via GLM 5.1...');

  try {
    var systemContent = 'أنت خبير في تنظيم المحتوى للعروض التقديمية. مهمتك تنظيم نص خام على شرائح العرض التقديمي حسب المحتوى المناسب لكل شريحة.\n\nأعد النتيجة كـ JSON فقط بدون أي نص إضافي بالشكل:\n{\n  "slides": [\n    {\n      "title": "عنوان الشريحة",\n      "bullets": ["نقطة 1 من النص", "نقطة 2 من النص"],\n      "requires_image": true أو false (حدد true لـ 5 شرائح بصرية كحد أقصى كالغلاف وصور الموقع ومميزات المشروع ومكوناته، والباقي false),\n      "missingInfo": "معلومات إضافية مطلوبة إن وُجدت"\n    }\n  ]\n}\n\nقواعد التنظيم:\n1. وزع محتوى النص على الشرائح المناسبة حسب الهيكل المحدد\n2. إذا كانت معلومات شريحة معينة غير مكتملة أو ناقصة، اذكرها في missingInfo\n3. احتفظ بالعناوين الأصلية للشرائح\n4. اجعل النقاط مختصرة ومنظمة\n5. لا تختلق معلومات - استخدم فقط ما يوجد في النص المكتوب\n6. إذا كان النص خالياً أو قصيراً جداً، اذكر ذلك في missingInfo';

    var userContent = 'بيانات المشروع:\n' + JSON.stringify(projectData || {}, null, 2) + '\n\nهيكل العرض:\n' + JSON.stringify(outline || [], null, 2) + '\n\nالنص المكتوب يدوياً:\n' + (rawText || 'لا يوجد نص');

    var { data, messages } = await callZaiChat(systemContent, userContent, userId, {
      maxTokens: 3000,
      referenceImage: projectData ? projectData.mainImageData : null
    });

    if (!data.choices || !data.choices[0]) {
      throw new Error('GLM failed: ' + JSON.stringify(data));
    }

    var cacheAnalytics = computeCacheAnalytics(data, 'organize_' + Date.now());
    var resultText = data.choices[0].message.content.trim();
    writeSystemPrombetBackup(messages, resultText);

    var jsonMatch = resultText.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      var result = JSON.parse(jsonMatch[0]);
      console.log('  ✓ Text organized across ' + (result.slides || []).length + ' slides | Cache: ' + cacheAnalytics.status);
      res.json({ success: true, slides: result.slides || [], cache_analytics: cacheAnalytics });
    } else {
      throw new Error('No JSON in GLM response');
    }
  } catch (err) {
    console.error('  ✗ Organize text error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  10. POST /api/generate-design
//      GLM 5.1 generates HTML/CSS slide designs (luxury PDF presentation)
// ─────────────────────────────────────────────
var DESIGN_SYSTEM_PROMPT = `You are a world-class luxury real estate investment presentation designer for "منافع الاقتصادية للعقار" (Manafe Economic Co. for Real Estate).

Your task: Generate a complete set of HTML/CSS slide designs for a luxury investment presentation. Each slide must be a standalone HTML component with inline CSS — no external stylesheets.

═════════════════════════════════════════════════════════════════
BRAND IDENTITY
═════════════════════════════════════════════════════════════════
Company: منافع الاقتصادية للعقار (Manafe Economic Co.)
Colors:
  - BURGUNDY (primary): #670D0C — headers, accents, key elements
  - SILVER (secondary): #A7A9AC — subtle accents, secondary text
  - GOLD/BRONZE (accent): #C2A176 — highlights, premium touches
  - BEIGE (light bg): #F5F0EE — card backgrounds
  - WHITE: #FFFFFF — main backgrounds
  - DARK TEXT: #0F172A — body text
  - MUTED TEXT: #64748B — captions, footer
  - CARD BG: #F8FAFC — card backgrounds with subtle depth
Font: 'The Sans Arabic', 'Cairo', 'Tajawal', sans-serif
RTL direction for all text.

═════════════════════════════════════════════════════════════════
CRITICAL RULES
═════════════════════════════════════════════════════════════════
1. Each slide is a self-contained <div> with inline styles
2. ALL text is Arabic. ALL text alignment is RIGHT. ALL text flows RTL.
3. Every slide has: logo (top-right), title, thin burgundy separator, content area, footer
4. Footer pattern: Company name + project name + page number in burgundy circle
5. Use card-based layouts with subtle shadows and rounded corners
6. Financial numbers must be LARGE and prominent (24-36px)
7. Use SVG icons inline (simple geometric shapes — NOT cartoon images)
8. Maximum 3 colors per slide. Keep palette restrained and elegant.
9. Each card must have internal padding. Text must NOT touch edges.
10. Use CSS flexbox/grid for layouts — NO absolute positioning
11. Images must use <img src="..."> tags with the exact placeholder strings below.
12. Use white space generously — slides must NOT feel crowded
13. Use professional linear icons (Location Pin, Road, Accessibility, etc.)
14. Add subtle geometric/architectural background patterns (light lines, shapes)

═════════════════════════════════════════════════════════════════
IMAGE PLACEHOLDERS (CRITICAL)
═════════════════════════════════════════════════════════════════
You MUST use these exact placeholder strings as the \`src\` attribute for images:
- "##MOODBOARD_IMAGE_1##": Use for Cover (Slide 1) and Closing (Slide 14) background image.
- "##MOODBOARD_IMAGE_2##": Use for Location Features (Slide 4) image card (representing a map or site view).
- "##MOODBOARD_IMAGE_3##": Use for Project Advantages (Slide 5) image card.
- "##MOODBOARD_IMAGE_4##": Use for Components (Slide 6) image card.
Always style images with object-fit: cover, width: 100%, and height: 100% inside their respective styled containers.

[Design rules removed - new rules will be provided separately]

═════════════════════════════════════════════════════════════════
OUTPUT FORMAT — STRICT JSON
═════════════════════════════════════════════════════════════════
Return ONLY valid JSON (no markdown, no code blocks) in this exact format:
{
  "slides": [
    {
      "title": "Slide title in Arabic",
      "html": "<div class='slide'>...complete HTML with inline CSS...</div>"
    }
  ]
}

Each slide's "html" must be a COMPLETE, self-contained HTML string with ALL styles inline. The container div should have:
- dir="rtl" lang="ar"
- width: 1280px, height: 720px
- overflow: hidden
- font-family: 'The Sans Arabic', 'Cairo', 'Tajawal', sans-serif
- position: relative
- background: white
- box-sizing: border-box

═════════════════════════════════════════════════════════════════
DESIGN REQUIREMENTS
═════════════════════════════════════════════════════════════════
- Increase font sizes (current ones too small on some slides)
- Fix text/table spacing
- Text in cards must be balanced, not touching edges
- Tables must be visually polished, not default-looking
- Use Icons, Shapes consistently
- Don't use too many colors
- Don't use random images — only project images or abstract elements
- Don't change content — only improve design
- Final output must look like a professional investment presentation ready to send to investors
- Generate EXACTLY 16 slides
- All financial data must match the project data provided
- Numbers formatted with commas (e.g., 1,500,000)
- Arabic text only for all labels and content
- Return ONLY valid JSON, no explanations, no markdown code blocks
`;

app.post('/api/generate-design', async function(req, res) {
  var projectData = req.body.projectData ? truncateProjectData(req.body.projectData, 8000) : null;
  var outline = req.body.outline || [];
  var userId = req.body.userId || 'default_user';
  var userInstructions = req.body.instructions || '';

  if (!projectData) {
    return res.status(400).json({ error: 'Project data is required' });
  }

  console.log('\n[Design] Generating HTML slide design via GLM 5.1...');
  console.log('  Slides: ' + outline.length);
  console.log('  Has main image: ' + !!(projectData && projectData.mainImageData));

  try {
    // Build the user message with all context
    var slideList = outline.map(function(s, i) {
      return (i + 1) + '. ' + s.title + (s.bullets && s.bullets.length > 0 ? '\n   ' + s.bullets.join('\n   ') : '');
    }).join('\n');

    var imageInfo = '';
    if (projectData && projectData.mainImageData) {
      imageInfo += '\n\nMAIN COVER IMAGE URL: ' + projectData.mainImageData.substring(0, 100) + '... (full data URI provided)';
    }
    // Collect additional images from the project data
    var additionalImages = [];
    if (projectData && projectData.slides) {
      projectData.slides.forEach(function(s) {
        if (s.image_b64 && s.image_b64 !== projectData.mainImageData) {
          additionalImages.push(s.image_b64);
        }
      });
    }

    var userMessage = 'PROJECT DATA:\n' + JSON.stringify({
      projectName: projectData.projectName,
      projectType: projectData.projectType,
      city: projectData.city,
      location: projectData.location,
      idea: projectData.idea,
      structure: projectData.structure,
      developer: projectData.developer,
      components: projectData.components,
      landArea: projectData.landArea,
      buildingRatio: projectData.buildingRatio,
      areaNote: projectData.areaNote,
      avgRent: projectData.avgRent,
      serviceFees: projectData.serviceFees,
      annualRevenue: projectData.annualRevenue,
      annualOpex: projectData.annualOpex,
      landCost: projectData.landCost,
      developmentCost: projectData.developmentCost,
      totalOperatingProfit: projectData.totalOperatingProfit,
      exitValue: projectData.exitValue,
      capRate: projectData.capRate,
      annualROI: projectData.annualROI,
      noiRate: projectData.noiRate,
      payback: projectData.payback,
      timelineRows: projectData.timelineRows,
      risks: projectData.risks,
      recommendation: projectData.recommendation,
      preparedBy: projectData.preparedBy,
      contactInfo: projectData.contactInfo,
      googleMapsLink: projectData.googleMapsLink,
      locationFeatures: projectData.locationFeatures,
      projectFeatures: projectData.projectFeatures,
      investmentHighlights: projectData.investmentHighlights
    }, null, 2);

    userMessage += '\n\nSLIDE OUTLINE:\n' + slideList;

    if (imageInfo) {
      userMessage += imageInfo;
    }

    if (additionalImages.length > 0) {
      userMessage += '\n\nADDITIONAL IMAGES AVAILABLE (' + additionalImages.length + ' images for mood board and slides)';
    }

    if (userInstructions) {
      userMessage += '\n\nADDITIONAL DESIGN INSTRUCTIONS:\n' + userInstructions;
    }

    userMessage += '\n\nGenerate the COMPLETE HTML/CSS design for ALL ' + outline.length + ' slides above. Return ONLY the JSON object with "slides" array.';

    // Build user message content — include image as image_url if available
    var userMessageContent;
    var mainImage = projectData ? projectData.mainImageData : null;
    if (mainImage && typeof mainImage === 'string' && (mainImage.startsWith('data:image/') || mainImage.startsWith('http'))) {
      userMessageContent = [
        { type: 'text', text: userMessage },
        { type: 'image_url', image_url: { url: mainImage } }
      ];
      console.log('  ✓ Sending main image to GLM for visual reference');
    } else {
      userMessageContent = userMessage;
    }

    // Build messages with training history
    var messages = buildMessagesWithTraining(DESIGN_SYSTEM_PROMPT, [{ role: 'user', content: userMessageContent }], userId);

    var payload = {
      model: GLM_MODEL,
      messages: messages,
      temperature: 0.7,
      max_tokens: 16000,
      thinking: { type: "disabled" }
    };

    var response = await fetch(ZAI_BASE + '/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + ZAI_KEY,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    var data = await response.json();
    if (!data.choices || !data.choices[0]) {
      throw new Error('GLM failed: ' + JSON.stringify(data));
    }

    var cacheAnalytics = computeCacheAnalytics(data, 'design_' + Date.now());
    var resultText = data.choices[0].message.content.trim();
    writeSystemPrombetBackup(messages, resultText);

    if (data.usage) {
      var u = data.usage;
      console.log('  ✓ Tokens: ' + u.total_tokens + ' | Cache: ' + cacheAnalytics.status);
    }

    // Parse the JSON response
    var jsonMatch = resultText.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      throw new Error('No JSON in GLM response');
    }

    var result = null;
    try {
      result = JSON.parse(jsonMatch[0]);
    } catch (parseErr) {
      console.log('  ⚠ JSON parse failed, attempting auto-repair...');
      // Try to extract slides array
      var slidesMatch = jsonMatch[0].match(/"slides"\s*:\s*\[[\s\S]*\]/);
      if (slidesMatch) {
        try {
          result = JSON.parse('{' + slidesMatch[0] + '}');
        } catch (e2) {
          throw new Error('Could not parse GLM design response');
        }
      } else {
        throw new Error('No slides array in GLM response');
      }
    }

    var slides = result.slides || [];
    console.log('  ✓ Generated design for ' + slides.length + ' slides');
    res.json({ success: true, slides: slides, cache_analytics: cacheAnalytics });

  } catch (err) {
    console.error('  ✗ Design generation error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  11. POST /api/redesign-slide
//      GLM 5.1 redesigns a single slide based on user instructions
// ─────────────────────────────────────────────
app.post('/api/redesign-slide', async function(req, res) {
  var slideHtml = req.body.slideHtml;
  var slideTitle = req.body.slideTitle;
  var editRequest = req.body.editRequest;
  var projectData = truncateProjectData(req.body.projectData, 6000);
  var allSlides = req.body.allSlides || [];
  var userId = req.body.userId || 'default_user';
  var isGlobalStyle = req.body.isGlobalStyle || false;

  if (!editRequest) {
    return res.status(400).json({ error: 'Edit request is required' });
  }

  console.log('\n[Redesign] Redesigning slide: ' + slideTitle);
  console.log('  Request: ' + editRequest.substring(0, 100));
  console.log('  Global style: ' + isGlobalStyle);

  try {
    var systemPrompt = isGlobalStyle ?
      'You are a luxury presentation designer for "منافع الاقتصادية للعقار". ' +
      'The user wants to change the design style of ALL slides. ' +
      'You will receive the current HTML of the slide and a request for style changes. ' +
      'Return a JSON object with: { "action": "global_style", "css": "CSS rules to apply globally", "response": "Arabic explanation", "updated_slides": [{ "title": "...", "html": "..." }] }. ' +
      'The css should target slide elements like: .slide, .slide-title, .kpi-card, etc. ' +
      'The updated_slides array should contain redesigned versions of the slides that need visual changes.' :
      'You are a luxury presentation designer for "منافع الاقتصادية للعقار". ' +
      'Redesign this specific slide based on the user request. ' +
      'Return a JSON object with: { "title": "new title (keep if not changing)", "html": "new complete HTML with inline CSS" }. ' +
      'Keep the same brand colors: burgundy #670D0C, gold #C2A176, silver #A7A9AC, beige #F5F0EE. ' +
      'Font: The Sans Arabic, Cairo. RTL layout. ' +
      'The html must be a complete div with ALL inline styles, width:1280px, height:720px, dir=rtl, lang=ar. ' +
      'If images were in the original slide, keep them in the redesigned version.';

    var userMessage = 'SLIDE TITLE: ' + slideTitle + '\n\n';
    userMessage += 'CURRENT HTML:\n' + (slideHtml || 'No HTML') + '\n\n';
    userMessage += 'PROJECT DATA CONTEXT:\n' + JSON.stringify({
      projectName: projectData ? projectData.projectName : '',
      annualRevenue: projectData ? projectData.annualRevenue : 0,
      totalCost: projectData ? ((projectData.landCost || 0) + (projectData.developmentCost || 0)) : 0,
      annualROI: projectData ? projectData.annualROI : '',
      noiRate: projectData ? projectData.noiRate : '',
      payback: projectData ? projectData.payback : ''
    }, null, 2) + '\n\n';

    if (isGlobalStyle && allSlides.length > 0) {
      userMessage += 'ALL CURRENT SLIDES:\n';
      allSlides.forEach(function(s, i) {
        userMessage += '\n--- Slide ' + (i + 1) + ': ' + s.title + ' ---\n';
        userMessage += (s.html || '').substring(0, 500) + '\n...\n';
      });
    }

    userMessage += 'USER REQUEST:\n' + editRequest;

    // Build user message content — include image if available
    var userMessageContent;
    var mainImage = projectData ? projectData.mainImageData : null;
    if (mainImage && typeof mainImage === 'string' && (mainImage.startsWith('data:image/') || mainImage.startsWith('http'))) {
      userMessageContent = [
        { type: 'text', text: userMessage },
        { type: 'image_url', image_url: { url: mainImage } }
      ];
    } else {
      userMessageContent = userMessage;
    }

    // Build messages with training history
    var messages = buildMessagesWithTraining(systemPrompt, [{ role: 'user', content: userMessageContent }], userId);

    var payload = {
      model: GLM_MODEL,
      messages: messages,
      temperature: 0.7,
      max_tokens: 12000,
      thinking: { type: "disabled" }
    };

    var response = await fetch(ZAI_BASE + '/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + ZAI_KEY,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    var data = await response.json();
    if (!data.choices || !data.choices[0]) {
      throw new Error('GLM failed: ' + JSON.stringify(data));
    }

    var cacheAnalytics = computeCacheAnalytics(data, 'redesign_' + Date.now());
    var resultText = data.choices[0].message.content.trim();
    writeSystemPrombetBackup(messages, resultText);

    console.log('  ✓ Redesign completed | Cache: ' + cacheAnalytics.status);

    var jsonMatch = resultText.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      var result = JSON.parse(jsonMatch[0]);
      res.json({ success: true, data: result, cache_analytics: cacheAnalytics });
    } else {
      throw new Error('No JSON in response');
    }

  } catch (err) {
    console.error('  ✗ Redesign error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  9b. POST /api/save-file
//      Saves a base64 encoded file (PPTX/PDF) to outputs dir
//      to bypass client-side iframe download restrictions
// ─────────────────────────────────────────────
app.post('/api/save-file', function(req, res) {
  var filename = req.body.filename;
  var base64Data = req.body.data;
  if (!filename || !base64Data) {
    return res.status(400).json({ error: 'filename and data are required' });
  }
  // Sanitize filename
  filename = filename.replace(/[^a-zA-Z0-9_\-\.]/g, '_');
  try {
    var buffer = Buffer.from(base64Data, 'base64');
    var filePath = path.join(OUTPUT_DIR, filename);
    fs.writeFileSync(filePath, buffer);
    console.log('  ✓ Saved file to ' + filePath);
    res.json({ success: true, url: '/outputs/' + filename });
  } catch (err) {
    console.error('  ✗ Error saving file:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ═══════════════════════════════════════════════════════════════
//  HELPER FUNCTIONS - Image Generation via OpenRouter/Gemini
// ═══════════════════════════════════════════════════════════════

async function callImageAPI(prompt) {
  try {
    var controller = new AbortController();
    var timeout = setTimeout(function() { controller.abort(); }, 120000);

    var response = await fetch(OPENROUTER_BASE + '/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + OPENROUTER_KEY,
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://github.com',
        'X-Title': 'Manafe PPTX Generator'
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
  } catch (e) {
    console.error('    Image API Error: ' + e.message);
  }
  return null;
}

async function callImageAPIWithReference(referenceImageBase64, prompt) {
  try {
    var controller = new AbortController();
    var timeout = setTimeout(function() { controller.abort(); }, 120000);

    var response = await fetch(OPENROUTER_BASE + '/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + OPENROUTER_KEY,
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://github.com',
        'X-Title': 'Manafe PPTX Generator'
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
  } catch (e) {
    console.error('    Image API Error: ' + e.message);
  }
  return null;
}

// ═══════════════════════════════════════════════════════════════
//  PDF EXPORT — Playwright Node.js (editable text layers)
// ═══════════════════════════════════════════════════════════════

var { generatePdf } = require('./pdf_engine');

app.post('/api/export-pdf', async function(req, res) {
  try {
    var { slidesHtml, projectName } = req.body;
    if (!slidesHtml) return res.status(400).json({ error: 'slidesHtml is required' });

    var filename = (projectName || 'project') + '_' + Date.now() + '.pdf';
    var outputPath = path.join(OUTPUT_DIR, filename);

    await generatePdf(slidesHtml, outputPath);

    res.json({ url: '/outputs/' + filename, filename: filename });
  } catch (e) {
    console.error('PDF export error:', e);
    res.status(500).json({ error: e.message || 'PDF generation failed' });
  }
});

// ═══════════════════════════════════════════════════════════════
//  START SERVER
// ═══════════════════════════════════════════════════════════════

app.listen(PORT, function() {
  console.log('\n═══════════════════════════════════════');
  console.log('  🌐 Server running on port ' + PORT);
  console.log('  🔗 http://localhost:' + PORT);
  console.log('  📋 API Endpoints:');
  console.log('    GET  /api/project-data');
  console.log('    POST /api/generate');
  console.log('    GET  /api/files');
  console.log('    POST /api/generate-main-image');
  console.log('    POST /api/generate-images');
  console.log('    POST /api/generate-slide-image');
  console.log('    POST /api/generate-design');
  console.log('    POST /api/redesign-slide');
  console.log('    POST /api/edit-deck-data');
  console.log('    POST /api/ai-edit-slide');
  console.log('    POST /api/ai-chat');
  console.log('═══════════════════════════════════════\n');
});
