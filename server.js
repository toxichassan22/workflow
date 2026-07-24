var express = require('express');
var path = require('path');
var fs = require('fs');
var { execSync, exec } = require('child_process');

// ═══ Load .env file (same logic as Python's dotenv) ═══
(function loadEnv() {
  var envPath = path.join(__dirname, '.env');
  try {
    var lines = fs.readFileSync(envPath, 'utf8').split('\n');
    lines.forEach(function (line) {
      var trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) return;
      var eqIdx = trimmed.indexOf('=');
      if (eqIdx < 1) return;
      var key = trimmed.substring(0, eqIdx).trim();
      var val = trimmed.substring(eqIdx + 1).trim();
      // Only set if not already in environment (env vars take priority)
      if (!process.env[key]) process.env[key] = val;
    });
  } catch (e) { /* no .env file, that's ok */ }
})();

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
var LOGO_PATH = path.join(__dirname, 'assets', 'logo.png');
var USERS_DB_PATH = path.join(__dirname, 'users_db.json');

// Vision-capable model (Gemini via OpenRouter). ZAI's GLM models do NOT
// support multi-modal image input, so any endpoint that must "see" images
// (designer-generate with uploaded creative images, designer-chat that views
// a rendered slide) routes through this model instead.
var VISION_MODEL = process.env.VISION_MODEL || 'google/gemini-3.1-flash-image-preview';
var VISION_BASE = OPENROUTER_BASE;

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

// ═══ Brand Profiles Management ═══
app.get('/api/branding-profiles', function (req, res) {
  var userId = req.query.userId || 'default_user';
  var db = loadUserDB();
  var user = db.users[userId];
  var profiles = (user && user.brandProfiles) ? user.brandProfiles : [];
  res.json({ success: true, profiles: profiles });
});

app.post('/api/save-branding-profile', function (req, res) {
  var userId = req.body.userId || 'default_user';
  var profile = req.body.profile;
  if (!profile || !profile.id) {
    return res.status(400).json({ error: 'Profile data and profile.id are required' });
  }
  var db = loadUserDB();
  if (!db.users[userId]) db.users[userId] = {};
  if (!db.users[userId].brandProfiles) db.users[userId].brandProfiles = [];

  var existingIdx = db.users[userId].brandProfiles.findIndex(function (p) { return p.id === profile.id; });
  if (existingIdx !== -1) {
    db.users[userId].brandProfiles[existingIdx] = profile;
  } else {
    db.users[userId].brandProfiles.push(profile);
  }
  saveUserDB(db);
  res.json({ success: true, profiles: db.users[userId].brandProfiles });
});

app.post('/api/delete-branding-profile', function (req, res) {
  var userId = req.body.userId || 'default_user';
  var profileId = req.body.profileId;
  if (!profileId) {
    return res.status(400).json({ error: 'profileId is required' });
  }
  var db = loadUserDB();
  if (db.users[userId] && db.users[userId].brandProfiles) {
    db.users[userId].brandProfiles = db.users[userId].brandProfiles.filter(function (p) { return p.id !== profileId; });
    saveUserDB(db);
  }
  var profiles = (db.users[userId] && db.users[userId].brandProfiles) ? db.users[userId].brandProfiles : [];
  res.json({ success: true, profiles: profiles });
});

function hexToRgb(hex) {
  if (!hex) return '103,13,12';
  hex = String(hex).replace('#', '');
  if (hex.length === 3) {
    hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
  }
  if (hex.length !== 6) return '103,13,12';
  var r = parseInt(hex.substring(0, 2), 16);
  var g = parseInt(hex.substring(2, 4), 16);
  var b = parseInt(hex.substring(4, 6), 16);
  return r + ',' + g + ',' + b;
}

function customizePrompts(prompt, projectData) {
  if (!projectData) return prompt;
  var companyName = projectData.clientCompanyName || 'منافع الاقتصادية للعقار';
  var colors = projectData.clientColors || {};
  var primary = colors.primary || '#670D0C';
  var secondary = colors.secondary || '#C2A176';
  var rgb = hexToRgb(primary);

  var result = prompt
    .replace(/منافع الاقتصادية للعقار/g, companyName)
    .replace(/شركة منافع الاقتصادية/g, companyName)
    .replace(/منافع الاقتصادية/g, companyName)
    .replace(/شركة منافع/g, companyName)
    .replace(/Manafe Economic Co\. for Real Estate/gi, companyName)
    .replace(/Manafe Economic Co\./gi, companyName)
    .replace(/Manafe/gi, companyName)
    .replace(/#670D0C/g, primary)
    .replace(/#7A0C0C/g, primary)
    .replace(/#C2A176/g, secondary)
    .replace(/#C4A35A/g, secondary)
    .replace(/#C5A880/g, secondary)
    .replace(/103,\s*13,\s*12/g, rgb);

  return result;
}


// Truncate project data to fit within GLM token limits
function truncateProjectData(data, maxChars) {
  if (!data) return data;

  // Recursively clean out known base64 image keys
  function cleanData(obj) {
    if (!obj) return obj;
    if (Array.isArray(obj)) {
      var res = [];
      for (var i = 0; i < obj.length; i++) {
        var item = obj[i];
        if (typeof item === 'string' && (item.indexOf('data:image/') === 0 || (item.length > 1000 && item.indexOf(';base64,') !== -1))) {
          continue;
        }
        res.push(cleanData(item));
      }
      return res;
    }
    if (typeof obj === 'object') {
      var cleaned = {};
      for (var k in obj) {
        if (obj.hasOwnProperty(k)) {
          if (['mainImageData', 'moodboardImages', 'aiGeneratedImages', 'creativeImages', 'creativeSlots', 'image_b64', 'image', 'logo', 'referenceImage', 'slides', 'clientLogo', 'clientReferenceImage'].indexOf(k) !== -1) {
            continue;
          }
          cleaned[k] = cleanData(obj[k]);
        }
      }
      return cleaned;
    }
    if (typeof obj === 'string') {
      if (obj.indexOf('data:image/') === 0 || (obj.length > 500 && obj.indexOf(';base64,') !== -1)) {
        return '[IMAGE_DATA_OMITTED]';
      }
      return obj;
    }
    return obj;
  }

  var cleanedData = cleanData(data);
  maxChars = maxChars || 8000;
  var str = JSON.stringify(cleanedData);
  if (str.length <= maxChars) return cleanedData;
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

    var backupContent = merged.map(function (m) {
      var contentVal = m.content;
      if (Array.isArray(contentVal)) {
        var contentStr = "";
        contentVal.forEach(function (part) {
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

  exec(cmd, { cwd: __dirname }, function (err, stdout, stderr) {
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
    merged.push({
      role: 'system', content: [
        { type: 'text', text: systemContent, cache_control: { type: 'ephemeral' } }
      ]
    });
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
    trimmedHistory.forEach(function (msg) {
      if (msg.role === 'user' || msg.role === 'assistant' || msg.role === 'system') {
        merged.push({ role: msg.role, content: msg.content });
      }
    });
  }

  // Append current prompt/messages
  currentMessages.forEach(function (msg) {
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
  var images = options.images; // NEW: array of image data URIs/URLs (multi-image vision)

  // Normalize all provided images into a single ordered list.
  // Backward compatible: referenceImage (single) is treated as the first image.
  var allImages = [];
  if (Array.isArray(images)) {
    images.forEach(function (img) {
      if (img && typeof img === 'string' && (img.startsWith('data:image/') || img.startsWith('http'))) {
        allImages.push(img);
      }
    });
  }
  if (referenceImage && typeof referenceImage === 'string' && (referenceImage.startsWith('data:image/') || referenceImage.startsWith('http'))) {
    if (allImages.indexOf(referenceImage) === -1) {
      allImages.unshift(referenceImage);
    }
  }

  var userMessageContent;
  if (allImages.length > 0) {
    userMessageContent = [{ type: "text", text: userContent }];
    allImages.forEach(function (img) {
      userMessageContent.push({ type: "image_url", image_url: { url: img } });
    });
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

// Vision-enabled chat via OpenRouter (Gemini). Used when the model must
// actually SEE images (creative board images, rendered slide screenshots).
// Supports a system prompt + multi-image user content + conversation history.
async function callVisionChat(systemPrompt, userText, images, userId, options) {
  options = options || {};
  var temperature = typeof options.temperature === 'number' ? options.temperature : 0.7;
  var maxTokens = options.maxTokens || 8000;
  var history = options.history || []; // [{role, content}]

  // Build user content: text first, then each image
  var userContent = [{ type: "text", text: userText }];
  if (Array.isArray(images)) {
    images.forEach(function (img) {
      if (img && typeof img === 'string' && (img.startsWith('data:image/') || img.startsWith('http'))) {
        userContent.push({ type: "image_url", image_url: { url: img } });
      }
    });
  }

  var messages = [];
  if (systemPrompt) {
    messages.push({ role: "system", content: systemPrompt });
  }
  // Append prior conversation history (keep it compact)
  if (Array.isArray(history)) {
    history.forEach(function (h) {
      if (h && h.role && h.content) {
        messages.push({ role: h.role, content: typeof h.content === 'string' ? h.content : JSON.stringify(h.content) });
      }
    });
  }
  messages.push({ role: "user", content: userContent });

  var payload = {
    model: VISION_MODEL,
    messages: messages,
    temperature: temperature,
    max_tokens: maxTokens
  };

  var response = await fetch(VISION_BASE + '/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer ' + OPENROUTER_KEY,
      'Content-Type': 'application/json',
      'HTTP-Referer': 'https://github.com',
      'X-Title': 'Manafe Designer Agent'
    },
    body: JSON.stringify(payload)
  });

  var data = await response.json();
  // Normalize: OpenRouter returns the same OpenAI shape. Attach an empty
  // messages array so downstream writeSystemPrombetBackup-style code is safe.
  return { data: data, messages: messages };
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
  } catch (e) { }
  return 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNmYGD4DwAEhQGDc2a8fAAAAABJRU5ErkJggg==';
}

// ═══════════════════════════════════════════════════════════════
//  EXISTING ENDPOINTS
// ═══════════════════════════════════════════════════════════════

// Serve project data
app.get('/api/project-data', function (req, res) {
  var dataPath = path.join(__dirname, 'project-data.json');
  if (fs.existsSync(dataPath)) {
    res.json(JSON.parse(fs.readFileSync(dataPath, 'utf8')));
  } else {
    res.json(null);
  }
});

// Generate presentation (existing - calls glm-designer.js)
app.post('/api/generate', function (req, res) {
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
      .filter(function (f) { return f.endsWith('.pptx'); })
      .map(function (f) {
        return { name: f, time: fs.statSync(path.join(__dirname, 'outputs', f)).mtime.getTime() };
      })
      .sort(function (a, b) { return b.time - a.time; });

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
app.get('/api/files', function (req, res) {
  var outDir = path.join(__dirname, 'outputs');
  if (!fs.existsSync(outDir)) {
    return res.json([]);
  }
  var files = fs.readdirSync(outDir)
    .filter(function (f) { return f.endsWith('.pptx'); })
    .map(function (f) {
      return {
        name: f,
        url: '/outputs/' + f,
        size: fs.statSync(path.join(outDir, f)).size,
        time: fs.statSync(path.join(outDir, f)).mtime
      };
    })
    .sort(function (a, b) { return new Date(b.time) - new Date(a.time); });
  res.json(files);
});

// ─────────────────────────────────────────────
//  AI Customization / Training History Endpoints
// ─────────────────────────────────────────────
app.post('/api/save-training', function (req, res) {
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

app.get('/api/get-training', function (req, res) {
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
app.post('/api/generate-main-image', async function (req, res) {
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
app.post('/api/generate-images', async function (req, res) {
  var prompts = req.body.prompts;
  var referenceImage = req.body.referenceImage;
  if (!prompts || !Array.isArray(prompts) || prompts.length === 0) {
    return res.status(400).json({ error: 'Prompts array is required' });
  }

  if (req.body.mock) {
    console.log('  [Mock Mode] Returning mock variant images');
    var mockImg = getMockImageUri();
    var images = prompts.map(function (p) { return { url: mockImg, prompt: p }; });
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
          await new Promise(function (r) { setTimeout(r, 1500); });
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
          await new Promise(function (r) { setTimeout(r, 1500); });
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
            await new Promise(function (r) { setTimeout(r, 1500); });
          }
        }
      }
    }

    console.log('  ✓ Generated ' + images.filter(function (x) { return x.url; }).length + '/' + prompts.length + ' images');
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
app.post('/api/edit-deck-data', async function (req, res) {
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
app.post('/api/ai-edit-slide', async function (req, res) {
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
- The content MUST be a complete styled HTML div (1280x720) with ALL inline CSS styles preserved from the original.
- Preserve ALL design elements: header bar, footer, background colors, card layouts, typography, spacing.
- ONLY modify the text/content the user requested to change. Do NOT strip the visual design.
- Keep the same style and language as the original
- Make smart improvements based on the user's request
- For investment project slides, maintain professional tone in Arabic
- Return ONLY valid JSON, no markdown`;

    var userMessage = 'SLIDE TITLE: ' + slideTitle + '\n\nCURRENT CONTENT (this is the FULL styled HTML of the slide — preserve ALL styles):\n' + slideContent + '\n\nPROJECT DATA CONTEXT:\n' + JSON.stringify(projectData || {}, null, 2) + '\n\nEDIT REQUEST:\n' + editRequest;

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
app.post('/api/ai-chat', async function (req, res) {
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
      contextData.slides = slidesData.map(function (s, i) {
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
//  5b. POST /api/generate-cover-prompt
//      Generate image prompt from project data using GLM
// ─────────────────────────────────────────────
app.post('/api/generate-cover-prompt', async function (req, res) {
  var projectData = req.body.projectData || {};

  if (req.body.mock) {
    return res.json({ success: true, prompt: 'مجمّع تجاري فاخر بواجهات زجاجية عصرية في جدة، إضاءة غروب ذهبية، تصميم معماري حديث' });
  }

  console.log('\n[CoverPrompt] Generating cover image prompt from project data...');

  var systemPrompt = 'أنت خبير في كتابة Prompts لتوليد الصور المعمارية بالذكاء الاصطناعي.\n' +
    'مهمتك كتابة وصف (prompt) تفصيلي ودقيق لصورة غلاف عرض تقديمي استثماري لمشروع عقاري.\n\n' +
    'القواعد:\n' +
    '1. اكتب باللغة الإنجليزية\n' +
    '2. اذكر نوع المشروع (تجاري، سكني، فندقي، إلخ)\n' +
    '3. اذكر الموقع والمدينة\n' +
    '4. اوصف الواجهة المعمارية بالتفصيل (زجاج، حجر، إلخ)\n' +
    '5. اذكر اللمسات المميزة (إضاءة، حدائق، مواقف)\n' +
    '6. أضف جودة التصوير (فوتوريالستيك، جودة عالية)\n' +
    '7. لا تضع نصوصاً أو أرقاماً في الصورة\n' +
    '8. اجعل الوصف مناسباً لصورة غلاف احترافية 16:9\n' +
    '9. اذكر اسم المبنى إذا كان موجوداً\n\n' +
    'أعد النتيجة كـ JSON فقط:\n' +
    '{"prompt": "الوصف التفصيلي بالإنجليزية"}';

  var userMsg = 'بيانات المشروع:\n' + JSON.stringify(projectData, null, 2) + '\n\nاكتب prompt تفصيلي لصورة غلاف هذا المشروع.';

  try {
    var { data, messages } = await callZaiChat(systemPrompt, userMsg, 'default_user', {
      maxTokens: 1000,
      disableThinking: true
    });

    if (!data.choices || !data.choices[0]) throw new Error('GLM failed: ' + JSON.stringify(data));

    var text = (data.choices[0].message.content || '').trim();

    var match = text.match(/\{[\s\S]*"prompt"[\s\S]*\}/);
    if (!match) throw new Error('No JSON in GLM response');

    var result = JSON.parse(match[0]);
    var prompt = result.prompt || '';

    if (!prompt) throw new Error('Empty prompt in response');

    console.log('  ✓ Generated cover prompt: ' + prompt.substring(0, 80) + '...');
    res.json({ success: true, prompt: prompt });
  } catch (err) {
    console.error('  ✗ Cover prompt error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
//  6. POST /api/generate-slide-image
//     Generate a single image for a specific slide
// ─────────────────────────────────────────────
app.post('/api/generate-slide-image', async function (req, res) {
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
app.post('/api/generate-outline', async function (req, res) {
  var projectData = truncateProjectData(req.body.projectData, 4000);
  var userId = req.body.userId || 'default_user';
  var totalSlides = parseInt(req.body.slideCount) || 14;

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
      allTopics.map(function (t, i) { return (i + 1) + '. ' + t; }).join('\n') + '\n\n' +
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
app.post('/api/generate-titles', async function (req, res) {
  var projectData = truncateProjectData(req.body.projectData, 4000);
  var userId = req.body.userId || 'default_user';
  var totalSlides = parseInt(req.body.slideCount) || 16;

  if (totalSlides < 4) totalSlides = 4;
  var contentCount = totalSlides - 4;

  if (req.body.mock) {
    console.log('  [Mock Mode] Returning mock titles for ' + totalSlides + ' slides (' + contentCount + ' content)');
    var allMockTitles = [
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
    var mockTitles = allMockTitles.slice(0, contentCount);
    var mockFinalTitles = [
      { title: 'غلاف المشروع', requires_image: true, type: 'cover', bullets: [] },
      { title: 'فهرس المحتويات', requires_image: false, type: 'index', bullets: [] }
    ];
    mockTitles.forEach(function (t) { mockFinalTitles.push({ title: t, requires_image: false, type: 'content', bullets: [] }); });
    mockFinalTitles.push({ title: 'المود بورد', requires_image: false, type: 'mood_board', bullets: [] });
    mockFinalTitles.push({ title: 'ختام العرض', requires_image: false, type: 'closing', bullets: [] });
    return res.json({
      success: true,
      titles: mockFinalTitles,
      cache_analytics: { status: "MOCKED", cached_tokens: 0, total_tokens: 0 }
    });
  }

  console.log('\n[Titles] Generating ' + contentCount + ' content titles for ' + totalSlides + ' total slides...');
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
      '- الشريحة ' + totalSlides + ' = ختام (لا تحتاج عنوان - ستولّد تلقائياً)\n' +
      '- الشريحتان 2 إلى ' + (totalSlides - 1) + ' = شرائح محتوى (هنا تضع أنت العناوين)\n\n' +
      'مهمتك: ولّد ' + contentCount + ' عنوان شريحة محتوى مناسبة لهذا العرض الاستثماري.\n\n' +
      'قواعد العناوين الواضحة:\n' +
      '- العناوين يجب أن تكون واضحة ومباشرة ومفهومة فوراً بدون قراءة المحتوى\n' +
      '- اذكر المحتوى الرئيسي في العنوان (مثال: "مواقع المكونات: محلات تجارية ومكاتب" بدلاً من "مكونات المشروع")\n' +
      '- اذكر الأرقام المالية في العناوين عند توفرها (مثال: "الإيرادات: 2.4 مليون ريال سنوياً" بدلاً من "الإيرادات")\n' +
      '- تجنب العناوين الغامضة مثل "نظرة عامة" أو "تفاصيل" — كن محدداً\n' +
      '- العنوان الواحد يصف محتوى الشريحة بالكامل\n' +
      '- مثال جيد: "التكاليف: 146 مليون ريال (أرض + تطوير)" | مثال سيء: "التكاليف"\n\n' +
      'اختر من هذه المواضيع (' + contentCount + ' فقط):\n' +
      allTopics.map(function (t, i) { return (i + 1) + '. ' + t; }).join('\n') + '\n\n' +
      'أعد النتيجة كـ JSON فقط بالصيغة:\n' +
      '{"titles": [{"title": "عنوان الشريحة الواضح والمفصل", "requires_image": true أو false}]}\n\n' +
      'قواعد:\n' +
      '1. ولّد بالضبط ' + contentCount + ' عناوين (لا أكثر ولا أقل)\n' +
      '2. حدد requires_image: true لـ 3 شرائح بصرية كحد أقصى (صور الموقع ومميزات المشروع ومكوناته)\n' +
      '3. باقي الشرائح requires_image: false\n' +
      '4. لا تضع عناوين للغلاف أو الختام';

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

    var finalTitles = [
      { title: 'غلاف المشروع', requires_image: true, type: 'cover', bullets: [] },
      { title: 'فهرس المحتويات', requires_image: false, type: 'index', bullets: [] }
    ];
    finalTitles = finalTitles.concat(titles);
    finalTitles.push({ title: 'المود بورد', requires_image: false, type: 'mood_board', bullets: [] });
    finalTitles.push({ title: 'ختام العرض', requires_image: false, type: 'closing', bullets: [] });

    console.log('  ✓ Got ' + finalTitles.length + ' titles (cover + index + ' + titles.length + ' content + moodboard + closing) | Cache: ' + cacheAnalytics.status);
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
app.post('/api/official-outline', async function (req, res) {
  var projectData = req.body.projectData || {};
  var totalSlides = 16;

  console.log('\n[Official Outline] Returning fixed official outline for ' + totalSlides + ' slides...');

  var officialTitles = [
    { title: 'غلاف المشروع', requires_image: true, type: 'cover', bullets: [] },
    { title: 'فهرس المحتويات', requires_image: false, type: 'index', bullets: [] },
    {
      title: 'الملخص التنفيذي', requires_image: false, type: 'content', bullets: [
        'نظرة عامة على المشروع والأهداف الرئيسية',
        'إجمالي التكلفة والعائد المتوقع',
        'التوصية النهائية للمستثمرين'
      ]
    },
    {
      title: 'فكرة المشروع والهيكلة', requires_image: false, type: 'content', bullets: [
        'تعريف المشروع ورسالته',
        'هيكلة المشروع والunits المختلفة',
        'الجهة المطورة والخبرات'
      ]
    },
    {
      title: 'مميزات الموقع', requires_image: true, type: 'content', bullets: [
        'الموقع الجغرافي والاستراتيجي',
        'البنية التحتية المحيطة',
        'سهولة الوصول والمواصلات'
      ]
    },
    {
      title: 'مميزات المشروع', requires_image: true, type: 'content', bullets: [
        'التصميم المعماري والعصري',
        'المرافق والتجهيزات الفاخرة',
        'نظام الأمان والتشغيل الذكي'
      ]
    },
    {
      title: 'مكونات المشروع والمساحات', requires_image: false, type: 'content', bullets: [
        'تفصيل الوحدات السكنية والتجارية',
        'المساحات المبنية والتأجيرية',
        'أسعار الإيجار المقدرة'
      ]
    },
    {
      title: 'افتراضات الربح التشغيلي التأجيري', requires_image: false, type: 'content', bullets: [
        'متوسط إيجار المتر ورسوم الخدمات',
        'الإيرادات السنوية المتوقعة',
        'المصروف التشغيلي السنوي'
      ]
    },
    {
      title: 'افتراضات التكاليف', requires_image: false, type: 'content', bullets: [
        'تكلفة الأرض والتطوير',
        'إجمالي التكلفة الاستثمارية',
        'هيكل التمويل المتوقع'
      ]
    },
    {
      title: 'الأرباح والتخارج', requires_image: false, type: 'content', bullets: [
        'الربح التشغيلي طوال فترة المشروع',
        'قيمة التخارج المتوقعة',
        'معامل الرسملة وال returns'
      ]
    },
    {
      title: 'المؤشرات المالية المتوقعة', requires_image: false, type: 'content', bullets: [
        'نسبة العائد السنوي على الاستثمار',
        'نسبة صافي الربح التشغيلي NOI',
        'فترة استرداد رأس المال'
      ]
    },
    {
      title: 'الجدول الزمني ومراحل المشروع', requires_image: false, type: 'content', bullets: [
        'مراحل التصميم والتصاريح',
        'مراحل البناء والتشطيبات',
        'موعد التسليم والتشغيل'
      ]
    },
    {
      title: 'فرص الاستثمار ونقاط القوة', requires_image: false, type: 'content', bullets: [
        'الطلب المتزايد في المنطقة',
        'العائد الإيجالي المرتفع',
        'فرصة ارتفاع القيمة'
      ]
    },
    {
      title: 'المخاطر والافتراضات', requires_image: false, type: 'content', bullets: [
        'مخاطر الترخيص والتأخير',
        'تقلبات أسعار البناء',
        'مخاطر السوق والمنافسة'
      ]
    },
    { title: 'المود بورد', requires_image: false, type: 'mood_board', bullets: [] },
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
app.post('/api/generate-bullets', async function (req, res) {
  var projectData = truncateProjectData(req.body.projectData, 4000);
  var slides = req.body.slides || []; // [{index, title}, ...]
  var userId = req.body.userId || 'default_user';

  if (req.body.mock) {
    console.log('  [Mock Mode] Returning mock bullets for ' + slides.length + ' slides');
    var mockResults = slides.map(function (s) {
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
    var promises = slides.map(function (slide) {
      var systemContent = 'أنت خبير في العروض التقديمية الاستثمارية. أنشئ 3-5 نقاط مختصرة واحترافية لهذه الشريحة. إذا كانت الشريحة هي "مميزات الموقع" وكان هناك رابط قوقل ماب (googleMapsLink) في بيانات المشروع، أضف نقطة تحتوي على رابط قوقل ماب المعطى بوضوح.\n\nأعد النتيجة كـ JSON فقط:\n{"bullets": ["نقطة 1", "نقطة 2", "نقطة 3"]}';
      var userContent = 'بيانات المشروع:\n' + JSON.stringify(projectData || {}, null, 2) + '\n\nعنوان الشريحة: ' + slide.title;

      return callZaiChat(systemContent, userContent, userId, {
        maxTokens: 1000,
        disableThinking: true,
        referenceImage: projectData ? projectData.mainImageData : null
      }).then(function (result) {
        var d = result.data;
        var m = (d.choices && d.choices[0] && d.choices[0].message) ? d.choices[0].message : {};
        var text = (m.content || '').trim();
        var jm = text.match(/\{[\s\S]*\}/);
        var bullets = [];
        if (jm) { try { bullets = JSON.parse(jm[0]).bullets || []; } catch (e) { } }
        return { index: slide.index, title: slide.title, bullets: bullets, usage: d.usage, id: d.id };
      }).catch(function (err) {
        console.error('  ✗ Bullet error ' + slide.index + ':', err.message);
        return { index: slide.index, title: slide.title, bullets: [], usage: null, id: null };
      });
    });

    var results = await Promise.all(promises);
    results.sort(function (a, b) { return a.index - b.index; });

    // Consolidate caching analytics across parallel requests
    var totalPromptTokens = 0;
    var totalCachedTokens = 0;
    var totalCompletionTokens = 0;
    var totalTokensCount = 0;
    var sessionIds = [];

    results.forEach(function (r) {
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
app.post('/api/generate-content', async function (req, res) {
  var projectData = truncateProjectData(req.body.projectData, 4000);
  var outline = req.body.outline;
  var userId = req.body.userId || 'default_user';

  // Truncate outline to prevent exceeding GLM context limits
  if (outline && outline.length > 0) {
    outline = outline.map(function (s) {
      return {
        title: s.title || '',
        bullets: Array.isArray(s.bullets) ? s.bullets.slice(0, 4) : (s.bullets || ''),
        content: typeof s.content === 'string' ? s.content.substring(0, 500) : s.content
      };
    });
  }

  if (req.body.mock) {
    console.log('  [Mock Mode] Returning mock HTML content for slides');
    var mockSlides = outline.map(function (s, idx) {
      var html = '<div class="ge-slide-title">' + s.title + '</div>';
      html += '<div class="ge-slide-subtitle">تفاصيل وبنية الشريحة الاستثمارية ' + (idx + 1) + '</div>';

      if (s.title === "مميزات الموقع" && projectData && projectData.googleMapsLink) {
        html += '<div class="ge-slide-body">';
        html += '<ul>';
        if (s.bullets && s.bullets.length > 0) {
          s.bullets.forEach(function (b) {
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
          s.bullets.forEach(function (b) {
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
              } catch (e) { }
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
app.post('/api/organize-text', async function (req, res) {
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

// ═══════════════════════════════════════════════════════════════
//  DESIGNER AGENT PROMPTS (new generation + editing flow)
//  GLM builds the whole deck from approved creative-board images and
//  then edits slides via a vision-enabled chat.
// ═══════════════════════════════════════════════════════════════
var DESIGNER_SYSTEM_PROMPT = `أنت مصمم عروض استثمارية عقارية فاخرة عالمي المستوى لشركة "منافع الاقتصادية للعقار". مهمتك تصميم عرض من 16 شريحة (HTML/CSS بأنماط مضمّنة) جاهز للعرض أمام المستثمرين.

═════════════════════════════════════════════════════════════════
قواعد مقدّسة — لا تخالفها أبداً
═════════════════════════════════════════════════════════════════
1. لا تغيّر أي رقم مالي أو اسم بند — انقلها كما هي من بيانات المشروع.
2. لا تحذف أي شريحة. صمّم الـ16 بالضبط.
3. كل النصوص عربية. كل المحاذاة يمين. الاتجاه RTL. dir="rtl" lang="ar" على كل حاوية.
4. كل شريحة <div> قائمة بذاتها بأنماط مضمّنة (inline CSS) — بدون ملفات خارجية، بدون position:absolute مفرط (فقط للطبقات الخلفية والشعار).
5. الحاوية دائماً: width:1280px;height:720px;overflow:hidden;box-sizing:border-box;font-family:'The Sans Arabic','Cairo','Tajawal',sans-serif;position:relative.
   ⚠️ إرشاد الأبعاد الصارم: مساحة المحتوى الصافية بين الهيدر والفوتر هي 1200px عرض × 580px ارتفاع كحد أقصى. يُحظر تماماً تصميم أي شريحة يتجاوز ارتفاع محتواها 580px.
   أحجام الخطوط المحددة: العنوان الرئيسي 24-28px (أقصى حد 32px)، عناوين البطاقات 15-18px، النص الداخلي والجداول 12-14px، الأرقام المالية الكبيرة 24-32px (أقصى حد 36px).
   تنسيق التكيف: إذا كان في الشريحة أكثر من 4 بطاقات أو بنود، وزعها فوراً على شبكة متعددة الأعمدة (Grid 2x2 أو 3x2 أو 4x2 مع gap:10px) وحشو داخلي للبطاقة (padding:10px 14px)، وممنوع رص البطاقات في عمود رأسي واحد طويل يتجاوز أبعاد الشريحة.
6. الأرقام المالية كبيرة جداً وبارزة (24-32px) ومنسّقة بفواصل (مثال: 1,500,000).
7. استخدم بطاقات بظلال خفيفة وزوايا مدورة (border-radius:10-12px)، حشو داخلي كافٍ ومناسب (padding:10-14px)، box-sizing:border-box لكل العناصر، النص لا يلمس الحواف.
8. أيقونات SVG خطية احترافية مضمّنة (line-style، stroke-width:1.8) — ليست كرتونية ولا emoji كبيرة.
9. أقصى 3-4 ألوان لكل شريحة. مساحات بيضاء كافية — لا ازدحام أبداً.
10. أضف عناصر هندسية/معمارية خفيفة في الخلفية (خطوط رفيعة، أشكال مجردة، pattern بسيط بشفافية منخفضة).

═════════════════════════════════════════════════════════════════
الهوية البصرية
═════════════════════════════════════════════════════════════════
الشركة: منافع الاقتصادية للعقار
الألوان:
  - العنابي الغامق (رئيسي): #670D0C
  - الذهبي/البرونزي (لمسات): #C2A176
  - الفضي: #A7A9AC
  - البيج الفاتح (بطاقات فقط): #F5F0EE
  - الأبيض (خلفية الشرائح): #FFFFFF
  - النص الداكن: #0F172A
  - النص الهادئ: #64748B
الخط: 'The Sans Arabic', 'Cairo', 'Tajawal', sans-serif
ملاحظة: خلفية الشرائح دائماً بيضاء (#FFFFFF) ما عدا الغلاف والختام (عنابي/صورة). لا تستخدم البيج كخلفية للشريحة، فقط للبطاقات.

═════════════════════════════════════════════════════════════════
الهيدر والتذييل الموحّد — لكل الشرائح ما عدا الغلاف(1) والختام(16)
═════════════════════════════════════════════════════════════════
الهيدر (أعلى): شعار ##LOGO## أعلى اليمين بحجم واضح (height:48-56px، object-fit:contain) + اسم الشركة/المشروع بخط صغير مرتب + خط رفيع عنابي (2px #670D0C) أسفل الهيدر.
التذييل (أسفل): خط رفيع رمادي (#E2E8F0) + على اليمين اسم المشروع، وسط اسم الشركة "منافع الاقتصادية للعقار"، يسار رقم الشريحة داخل دائرة/مستطيل صغير باللون العنابي (background:#670D0C;color:#fff;border-radius:50%).
التذييل موحّد في كل الشرائح ولا يزاحم المحتوى. اترك مساحة (60-70px) للهيدر من الأعلى و(50-56px) للتذييل من الأسفل.

═════════════════════════════════════════════════════════════════
الصور — استخدم الرموز (TOKENS) فقط، لا تضع روابط
═════════════════════════════════════════════════════════════════
مهم جداً: لا تضع أي data URI أو رابط صورة حقيقي في src. استخدم هذه الرموز الحرفية بالضبط في داخل src="...":
  - "##PROJECT_IMAGE_COVER##"  → صورة الغلاف (الشريحة 1)
  - "##PROJECT_IMAGE_1##"      → شريحة مميزات الموقع (الشريحة 5)
  - "##PROJECT_IMAGE_2##"      → شريحة مميزات المشروع (الشريحة 6)
  - "##PROJECT_IMAGE_3##"      → شريحة فكرة المشروع (الشريحة 4)
  - "##PROJECT_IMAGE_4##"      → شريحة فرص الاستثمار (الشريحة 13)
  - "##MOODBOARD_IMAGE_1##","##MOODBOARD_IMAGE_2##","##MOODBOARD_IMAGE_3##","##MOODBOARD_IMAGE_4##" → الشريحة 15 (المودبورد، الـ4 معاً)

النظام سيستبدل هذه الرموز تلقائياً بالصور الحقيقية. اكتب <img src="##PROJECT_IMAGE_1##" style="width:100%;height:100%;object-fit:cover"> داخل حاوية منسقة.
قاعدة الصور: ضع صورة واحدة على الأقل في كل شريحة محتوى بصرية (4/5/6/13) وكل الـ4 في شريحة المودبورد(15). الصورة جزء من المحتوى: حاوية بعرض 38-42% جنب المحتوى (object-fit:cover، border-radius:12px، box-shadow خفيف) + caption تحتها (عنوان عنابي bold + وصف رمادي). لا تضع صوراً على الشرائح المالية البحتة (جداول/KPI/معادلات).

═════════════════════════════════════════════════════════════════
تصميم الشرائح الـ16 بالتفصيل (التزم بالترتيب والمحتوى)
═════════════════════════════════════════════════════════════════
الشريحة 1 — الغلاف: خلفية كاملة ##PROJECT_IMAGE_COVER## (cover، بدون تشويه) + طبقة عنابية شفافة (rgba(103,13,12,0.55)) + شعار ##LOGO## وسط بحجم كبير (height:90-110px) + اسم المشروع بخط عربي ضخم أبيض أسفل الشعار + خط ذهبي رفيع زخرفي + وصف صغير "عرض مشروع استثماري". فاخر وبسيط، بلا هيدر/تذييل/جداول، لمسة هندسية في الأطراف.

الشريحة 2 — فهرس المحتويات: قائمة رسمية بكل عناوين الشرائح من 1 إلى 16، كل عنوان برقمه داخل دائرة/مربع عنابي صغير في عمود جانبي أنيق. لا عناوين عشوائية ولا مختصرة.

الشريحة 3 — الملخص التنفيذي (Dashboard): 6 بطاقات KPI كبيرة: إجمالي التكلفة، الإيرادات السنوية، إجمالي الأرباح طوال الفترة، العائد السنوي المتوقع، NOI المتوقع، استرداد رأس المال. اجعل "إجمالي الأرباح طوال الفترة" الأكبر والأبرز. كل بطاقة: أيقونة + رقم ضخم + عنوان. ظلال خفيفة.

الشريحة 4 — فكرة المشروع والهيكلة: 5 بطاقات (فكرة المشروع، الموقع، هيكلة المشروع، نوع المشروع، المطور/الجهة) بأيقونات (فكرة/موقع/تقويم/مبنى/مطور) + صورة ##PROJECT_IMAGE_3## على جانب. زر "فتح موقع المشروع على Google Maps" بارز وقابل للضغط (a href) إن وُجد الرابط.

الشريحة 5 — مميزات الموقع: كل ميزة بطاقة مستقلة بأيقونة (Location Pin/Road/Accessibility/Population/Growth) + صورة ##PROJECT_IMAGE_1## + عنصر خريطة/Pin شفاف في الخلفية + زر Google Maps مميز.

الشريحة 6 — مميزات المشروع: شبكة (Grid) 4 بطاقات+ (أيقونة + عنوان مختصر + وصف صغير)، خلفية بيج فاتحة للبطاقات، عناوين عنابية، عناصر معمارية مجردة في الخلفية + صورة ##PROJECT_IMAGE_2##.

الشريحة 7 — مكونات المشروع والمساحات: جدول احترافي (رأس عنابي/نص أبيض، صفوف متبادلة أبيض/بيج، صف الإجمالي bold بخلفية مميزة) + 3 بطاقات أسفله (مساحة الأرض، نسبة البناء، ملاحظة المساحات) بأيقونات صغيرة.

الشريحة 8 — افتراضات الربح التشغيلي التأجيري: معادلة بصرية (الإيرادات السنوية − المصروف التشغيلي السنوي = إجمالي الربح التأجيري السنوي) كل رقم في بطاقة مالية منفصلة بأيقونة، والربح التأجيري الأكبر والأبرز. جدول مرجعي صغير جداً أسفل إن لزم.

الشريحة 9 — افتراضات التكاليف: مقارنة بصرية بطاقتين كبيرتين (تكلفة الأرض) و(تكلفة التطوير) + بطاقة (إجمالي التكلفة) أكبر وأبرز + مخطط شريطي (bar) بسيط لنسبة مساهمة كل بند + أيقونات (Land/Construction/Total Cost).

الشريحة 10 — الأرباح والتخارج: مسار قيمة استثماري متسلسل (Flow/سهم أفقي): (إجمالي الربح التشغيلي طوال الفترة + قيمة التخارج = إجمالي الأرباح طوال الفترة). اجعل "قيمة التخارج" و"إجمالي الأرباح" الأضخم والأبرز + أيقونات (Exit/Growth/Profit).

الشريحة 11 — المؤشرات المالية المتوقعة: Financial Dashboard: بطاقات علوية رئيسية لـ ROI/NOI/Payback بأرقام كبيرة + مقارنة بصرية أسفلها لإجمالي التكلفة وإجمالي الأرباح + أيقونات (Gauge/Chart/Clock/Investment).

الشريحة 12 — الجدول الزمني ومراحل المشروع: Gantt احترافي: سنوات وربوع Q1/Q2/Q3/Q4 في الأعلى كشبكة زمنية + كل مرحلة شريط أفقي ممتد بدقة حسب مدتها، أسماء المراحل بوضوح داخل/بجانب الشرائط بلا تداخل ولا تكرار. ألوان هادئة (عنابي/بني فاتح/بيج/رمادي).

الشريحة 13 — فرص الاستثمار ونقاط القوة: High Impact تسويقية: كل فرصة بطاقة كبيرة مستقلة (عنوان قصير + وصف مختصر + أيقونة قوية) + سهم نمو/مخطط صاعد خفيف في الخلفية + صورة ##PROJECT_IMAGE_4##.

الشريحة 14 — المخاطر والافتراضات: احترافية هادئة غير منفرة (ابعد عن الألوان التحذيرية الصارخة): بطاقات رمادية/بيج بلمسة عنابية وأيقونة تنبيه خطية + عنوان فرعي "نقاط يجب التحقق منها في الدراسة التفصيلية".

الشريحة 15 — المودبورد (Moodboard): شبكة 2×2 أنيقة للصور الأربع (##MOODBOARD_IMAGE_1##..4##)، فواصل رمادية/بيج خفيفة جداً، تظهر كمعرض معماري فاخر يبرز روح التصميم والهوية. (النظام سيبني هذه الشبكة تلقائياً من الصور — يمكنك أيضاً تصميمها يدوياً باستخدام الرموز الأربعة.)

الشريحة 16 — الختام: خلفية عنابية فاخرة كاملة (#670D0C) + شعار ##LOGO## كبير واضح + عبارة "شكراً لكم" بخط عربي فخم ضخم أبيض + اسم المشروع + بيانات التواصل منظمة أسفلها. بلا هيدر/تذييل.

═════════════════════════════════════════════════════════════════
تنسيق الإخراج — JSON صارم
═════════════════════════════════════════════════════════════════
أرجع فقط JSON صالح (بدون ماركداون، بدون كتل كود \`\`\`):
{
  "slides": [
    { "title": "عنوان الشريحة بالعربية", "html": "<div dir='rtl' lang='ar' style='width:1280px;height:720px;overflow:hidden;box-sizing:border-box;font-family:"The Sans Arabic","Cairo",sans-serif;position:relative;background:#fff'>...</div>" }
  ]
}

صمم بالضبط الـ16 شريحة حسب الفهرس التالي:
{{OUTLINE}}

كل البيانات المالية تطابق بيانات المشروع المقدمة تماماً. النصوص عربية فقط. كثّف الخطوط لتكون واضحة أثناء العرض.`;

var DESIGNER_CHAT_PROMPT = `أنت مصمم العروض التقديمية الخاص بالمستخدم — تتعامل معه كأنك مصمم بشري يرى عمله ويفهمه.

السياق: تم إرفاق صورة الشريحة الحالية (مقدمة من المتصفح) لتراها بعينك. ترى التصميم كما هو معروض، وتفهم المشاكل البصرية والمحتوى.

دورك:
- أنت ترى الشريحة وتفهم تركيبها البصري بالكامل.
- أبعاد الشريحة مقدسة وثابتة دائماً: 1280px عرض × 720px ارتفاع (dir="rtl" lang="ar" overflow:hidden box-sizing:border-box).
- ⚠️ قانون المساحة الصارم: عند إضافة أي عنصر أو بطاقة جديدة (مثل إضافة بند خامس أو سادس)، يُمنع زيادة الارتفاع الرأسي بما يتجاوز أبعاد الشريحة (720px). يجب عليك فوراً تعديل التخطيط ليكون شبكة متعددة الأعمدة (مثلاً 2x2 أو 4x2 أو 3x2 مع gap:10px) وتقليل الخطوط (العنوان الرئيسي 24-28px، النص 13-14px، padding البطاقة 10-14px) لضمان احتواء كامل المحتوى داخل الـ 720px بدون انقطاع أي عنصر.
- عندما يطلب المستخدم تعديلاً، عدّل HTML الشريحة وأرجعها كاملة ومحدثة ومطابقة لقوانين المساحة.
- ⚠️ عند تعديل شريحة المودبورد (Moodboard) أو إضافة صور فيها: يجب تضمين الصور الأربعة دائماً في شبكة 2x2 مستخدماً الرموز الدقيقة ##MOODBOARD_IMAGE_1## إلى ##MOODBOARD_IMAGE_4## داخل عناصر <img src="..."> أو background-image:url('##MOODBOARD_IMAGE_N##'). يمنع منعاً باتاً ترك البطاقات فارغة بدون صور، ويمنع كتابة #### في الرموز.
- حافظ على الهوية البصرية: البورجوندي #670D0C، الذهبي #C2A176، خط The Sans Arabic، اتجاه RTL.
- كل الأنماط مضمّنة (inline). الحاوية: width:1280px, height:720px, dir=rtl, lang=ar, overflow:hidden, box-sizing:border-box.
- لا تخترع صوراً وهمية — استخدم الرموز المحددة للصور فقط.
- كن دقيقاً: عدّل فقط ما طلبه المستخدم، واحتفظ بباقي التصميم سليماً ومستقراً.

عندما يتطلب الطلب تعديلاً:
{"action": "update_slide", "title": "العنوان (أبقه إن لم يتغير)", "html": "HTML كامل ومحدث بكل الأنماط المضمّنة"}

عندما يكون الطلب سؤالاً أو لا يتطلب تعديلاً:
{"action": "chat", "response": "ردك بالعربية"}

أرجع فقط JSON صالح.`;

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
IMAGE PLACEHOLDERS (CRITICAL - USE ALL 4 IMAGES)
═════════════════════════════════════════════════════════════════
You MUST use ALL 4 moodboard images. Each image placeholder appears EXACTLY ONCE across the whole presentation.
Each placeholder MUST be placed on a DIFFERENT content slide (never on cover, index, closing, or purely financial/dashboard table/chart slides).

Select the 4 most suitable content slides that contain textual lists, bullet points, or concepts (such as Executive Summary, Project Concept, Geographic Location/Advantages, Project Features, Specifications, or Market Demand).
Do NOT place image placeholders on slides containing purely financial dashboards, KPI grids, capitalization structure tables, or exit values where a full-width card layout is more appropriate.

Placeholders (copy-paste these EXACTLY into your HTML image src tags):
- "##MOODBOARD_IMAGE_1##" -> Suitable text/concept slide (e.g. Executive Summary / Project Concept)
- "##MOODBOARD_IMAGE_2##" -> Suitable text/concept slide (e.g. Project Concept / Location features)
- "##MOODBOARD_IMAGE_3##" -> Suitable text/concept slide (e.g. Features / Specifications)
- "##MOODBOARD_IMAGE_4##" -> Suitable text/concept slide (e.g. Advantages / Market Demand / Aerial View description)

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
- Generate EXACTLY 14 slides
- All financial data must match the project data provided
- Numbers formatted with commas (e.g., 1,500,000)
- Arabic text only for all labels and content
- Return ONLY valid JSON, no explanations, no markdown code blocks
`;

app.post('/api/generate-design', async function (req, res) {
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
    var slideList = outline.map(function (s, i) {
      return (i + 1) + '. ' + s.title + (s.bullets && s.bullets.length > 0 ? '\n   ' + s.bullets.join('\n   ') : '');
    }).join('\n');

    var imageInfo = '';
    if (projectData && projectData.mainImageData) {
      imageInfo += '\n\nMAIN COVER IMAGE URL: ' + projectData.mainImageData.substring(0, 100) + '... (full data URI provided)';
    }
    // Collect additional images from the project data
    var additionalImages = [];
    if (projectData && projectData.slides) {
      projectData.slides.forEach(function (s) {
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
app.post('/api/redesign-slide', async function (req, res) {
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
      allSlides.forEach(function (s, i) {
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
app.post('/api/save-file', function (req, res) {
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
    var timeout = setTimeout(function () { controller.abort(); }, 120000);

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
        messages: [{ role: 'user', content: [{ type: 'text', text: prompt + ' --aspect 16:9' }] }],
        modalities: ['image', 'text']
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
    var timeout = setTimeout(function () { controller.abort(); }, 120000);

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
              { type: 'text', text: prompt + ' --aspect 16:9' },
              { type: 'image_url', image_url: { url: referenceImageBase64 } }
            ]
          }
        ],
        modalities: ['image', 'text']
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

var { generatePdf, renderSlideImage } = require('./pdf_engine');

app.post('/api/export-pdf', async function (req, res) {
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
//  DESIGNER AGENT — new generation + editing flow
//  GLM builds the whole deck from approved creative-board images,
//  then a vision-enabled chat lets the user direct edits by seeing
//  each rendered slide.
// ═══════════════════════════════════════════════════════════════

// Strip ```json ... ``` / ``` ... ``` markdown code fences from model output.
function stripCodeFences(text) {
  if (!text) return text;
  return text.replace(/```(?:json)?\s*/gi, '').replace(/```\s*/g, '').trim();
}

// Extract the first syntactically-valid JSON object from free-form model
// output. Handles code fences, repeated/duplicated objects, and trailing
// text. Returns the parsed object or null.
function parseFirstJsonObject(text) {
  if (!text || typeof text !== 'string') return null;
  var cleaned = stripCodeFences(text);
  var start = 0;
  while (true) {
    var brace = cleaned.indexOf('{', start);
    if (brace === -1) return null;
    // Walk forward tracking brace depth (respecting strings).
    var depth = 0, inStr = false, esc = false, end = -1;
    for (var i = brace; i < cleaned.length; i++) {
      var ch = cleaned[i];
      if (inStr) {
        if (esc) { esc = false; }
        else if (ch === '\\') { esc = true; }
        else if (ch === '"') { inStr = false; }
      } else {
        if (ch === '"') { inStr = true; }
        else if (ch === '{') { depth++; }
        else if (ch === '}') { depth--; if (depth === 0) { end = i; break; } }
      }
    }
    if (end !== -1) {
      var candidate = cleaned.substring(brace, end + 1);
      try { return JSON.parse(candidate); }
      catch (e) { /* keep scanning from the next brace */ }
    }
    start = brace + 1;
  }
}


// Render a single slide's HTML to a PNG (base64) so the chat can "see" it.
app.post('/api/render-slide-image', async function (req, res) {
  try {
    var slideHtml = req.body.slideHtml;
    if (!slideHtml) return res.status(400).json({ error: 'slideHtml is required' });
    var dataUri = await renderSlideImage(slideHtml, { scale: req.body.scale || 2 });
    res.json({ success: true, image: dataUri });
  } catch (e) {
    console.error('Render slide image error:', e);
    res.status(500).json({ error: e.message || 'Slide render failed' });
  }
});

// ═══════════════════════════════════════════════════════════════
//  POST-PROCESSING: enforce image usage & rebuild special slides
//  The vision model cannot reliably copy long data URIs into <img src>.
//  We therefore (a) resolve every image TOKEN to a real image, (b) rebuild
//  the COVER, MOODBOARD, and final CLOSING deterministically, and (c) inject
//  a project image into content slides that ended up image-less.
//  This guarantees every approved image is actually displayed.
// ═══════════════════════════════════════════════════════════════
function postProcessDesignerSlides(slides, images, projectData) {
  if (!Array.isArray(slides)) return slides;
  var defaultStock = [
    '/uploads/luxury_skyscraper_cover.png',
    '/uploads/moodboard_exterior.png',
    '/uploads/moodboard_interior.png',
    '/uploads/moodboard_materials.png',
    '/uploads/moodboard_urban_lifestyle.png'
  ];
  // Normalize the image pool. images[0] is the cover; the rest are moodboard.
  var imgs = (Array.isArray(images) ? images : []).filter(function (x) { return typeof x === 'string' && x; });
  if (imgs.length === 0) {
    imgs = defaultStock;
  }

  // imgByToken: cover + 4 named content/moodboard images, cycling if too few.
  function tok(n) {
    if (imgs.length === 0) return defaultStock[n - 1] || defaultStock[0];
    if (n <= imgs.length) return imgs[n - 1];
    return imgs[(n - 1) % imgs.length];
  }
  var imgCover = tok(1);
  var img1 = tok(2) || defaultStock[1];
  var img2 = tok(3) || defaultStock[2];
  var img3 = tok(4) || defaultStock[3];
  var img4 = tok(5) || defaultStock[4];

  function escapeHtmlAttr(s) {
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  for (var i = 0; i < slides.length; i++) {
    var s = slides[i];
    var slideNo = s._slideNo || (i + 1);
    var html = s.html || '';
    if (typeof html !== 'string') html = '';

    // (a) Resolve TOKENS → real image URIs everywhere first (including malformed ones).
    html = html
      .replace(/#*PROJECT_IMAGE_COVER#*/gi, imgCover)
      .replace(/#*COVER_IMAGE#*/gi, imgCover)
      .replace(/#*MAIN_IMAGE#*/gi, imgCover)
      .replace(/#*IMAGE_COVER#*/gi, imgCover)
      .replace(/#*PROJECT_IMAGE_1#*/gi, img1)
      .replace(/#*PROJECT_IMAGE_2#*/gi, img2)
      .replace(/#*PROJECT_IMAGE_3#*/gi, img3)
      .replace(/#*PROJECT_IMAGE_4#*/gi, img4)
      .replace(/#*MOODBOARD_IMAGE_1#*/gi, img1)
      .replace(/#*MOODBOARD_IMAGE_2#*/gi, img2)
      .replace(/#*MOODBOARD_IMAGE_3#*/gi, img3)
      .replace(/#*MOODBOARD_IMAGE_4#*/gi, img4);
    s.html = html;
    s._slideNo = slideNo;

    // (b) Rebuild COVER (slide 1) deterministically.
    if (slideNo === 1) {
      s.html = buildCoverSlideHtml(imgCover, projectData);
      continue;
    }

    // Rebuild the final slide as CLOSING regardless of the deck length.
    // The previous slide-16 assumption left headers/footers in short decks.
    var isLastSlide = (i === slides.length - 1);
    var isClosingType = String(s.type || '').toLowerCase() === 'closing' ||
      /ختام|closing|شكراً|thanks/i.test(String(s.title || ''));
    if (isLastSlide || isClosingType) {
      s.html = buildClosingSlideHtml(projectData);
      continue;
    }

    // Rebuild MOODBOARD when it is explicitly the moodboard slide.
    if (slideNo === 15 || String(s.type || '').toLowerCase() === 'moodboard' ||
      /مود.?بورد|moodboard|لوحة الأنماط/i.test(String(s.title || ''))) {
      s.html = buildMoodboardSlideHtml([img1, img2, img3, img4], projectData);
      continue;
    }

    // (c) GUARANTEE 4 content slides each carry a DIFFERENT project image.
    // Map: slide 4 → img1, 5 → img2, 6 → img3, 13 → img4. We count ONLY real
    // project images (excluding the logo path) so a logo-only <img> does not
    // make us think a project image is already present.
    function countProjectImages(htmlStr) {
      var matches = String(htmlStr || '').match(/<img\b[^>]*>/gi) || [];
      var logoPat = /logo|assets\/logo|manafe|منافع/i;
      var projPat = new RegExp(
        [img1, img2, img3, img4, imgCover].filter(Boolean)
          .map(function (x) { return escapeHtmlAttr(x.substring(0, 30)); })
          .join('|'),
        'i'
      );
      var cnt = 0;
      for (var mi = 0; mi < matches.length; mi++) {
        if (logoPat.test(matches[mi])) continue;       // skip logo
        if (projPat.test(matches[mi])) cnt++;           // real project image
      }
      return cnt;
    }

    var imageSlideMap = { 4: img1, 5: img2, 6: img3, 13: img4 };
    if (imageSlideMap[slideNo]) {
      var assigned = imageSlideMap[slideNo];
      // Force-inject if the assigned image is not already on this slide.
      var assignedPat = new RegExp(escapeHtmlAttr(assigned.substring(0, 30)), 'i');
      var hasAssigned = /<img\b/i.test(html) && assignedPat.test(html);
      if (!hasAssigned) {
        s.html = injectSideImage(html, assigned);
      }
    } else if (slideNo >= 3 && slideNo !== 2 && slideNo !== 15 && !isLastSlide && !isClosingType) {
      // Other visual content slides: ensure at least ONE project image present.
      if (countProjectImages(html) === 0) {
        // distribute remaining images round-robin
        var pick2 = [img1, img2, img3, img4][slideNo % 4] || imgCover;
        s.html = injectSideImage(html, pick2);
      }
    }
  }

  return slides;
}

// Escape a data URI / URL so it is safe inside an HTML attribute.
function safeAttr(s) {
  return String(s).replace(/"/g, '&quot;');
}

function _slideShell(bg) {
  bg = bg || '#FFFFFF';
  return 'dir="rtl" lang="ar" style="width:1280px;height:720px;overflow:hidden;box-sizing:border-box;' +
    'font-family:\'The Sans Arabic\',\'Cairo\',\'Tajawal\',sans-serif;position:relative;background:' + bg + '"';
}

// Build the COVER slide (slide 1): full-bleed image + burgundy overlay +
// centered logo + huge project name + gold rule + subtitle.
function buildCoverSlideHtml(imgCover, projectData) {
  var name = (projectData && projectData.projectName) || 'عرض مشروع استثماري';
  var ptype = (projectData && projectData.projectType) || '';
  var city = (projectData && projectData.city) || '';
  var sub = 'عرض مشروع استثماري';
  if (ptype || city) sub = [ptype, city].filter(Boolean).join(' - ');
  var bg = imgCover ? 'background-image:url(\'' + safeAttr(imgCover) + '\');background-size:cover;background-position:center;' : 'background:#670D0C;';
  var img = safeAttr(imgCover);
  return '<div data-no-reprocess="true" ' + _slideShell('#670D0C') + '>' +
    '<div style="position:absolute;inset:0;' + bg + '"></div>' +
    '<div style="position:absolute;inset:0;background:linear-gradient(135deg,rgba(103,13,12,0.72),rgba(15,23,42,0.55))"></div>' +
    // corner accents
    '<div style="position:absolute;top:0;right:0;width:160px;height:160px;border-top:3px solid #C2A176;border-right:3px solid #C2A176;opacity:.7"></div>' +
    '<div style="position:absolute;bottom:0;left:0;width:160px;height:160px;border-bottom:3px solid #C2A176;border-left:3px solid #C2A176;opacity:.7"></div>' +
    '<div style="position:relative;z-index:5;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:0 60px">' +
    '<div style="background:#fff;border-radius:18px;padding:22px 40px;box-shadow:0 16px 48px rgba(0,0,0,0.30);margin-bottom:32px;display:flex;flex-direction:column;align-items:center;gap:10px">' +
    '<img src="##LOGO##" alt="منافع الاقتصادية" style="height:120px;width:auto;max-width:360px;object-fit:contain;display:block" />' +
    '<div style="color:#670D0C;font-size:18px;font-weight:800;letter-spacing:.5px">منافع الاقتصادية للعقار</div>' +
    '<div style="color:#A7A9AC;font-size:12px;letter-spacing:2px">MANAFE ECONOMIC CO.</div>' +
    '</div>' +
    '<div style="color:#FFFFFF;font-size:54px;font-weight:900;line-height:1.25;max-width:980px;text-shadow:0 2px 12px rgba(0,0,0,0.5)">' + name + '</div>' +
    '<div style="width:140px;height:3px;background:#C2A176;margin:22px 0"></div>' +
    '<div style="color:#C2A176;font-size:18px;font-weight:700;letter-spacing:1px">' + sub + '</div>' +
    '</div>' +
    '</div>';
}

// Build the MOODBOARD slide (slide 15): 2x2 gallery of the 4 images.
function buildMoodboardSlideHtml(imgs, projectData) {
  var names = ['الطابع المعماري (Exterior)', 'الألوان والمواد (Materials)', 'المساحات الداخلية (Interior)', 'البيئة المحيطة (Lifestyle)'];
  var defaultImgs = [
    '/uploads/moodboard_exterior.png',
    '/uploads/moodboard_materials.png',
    '/uploads/moodboard_interior.png',
    '/uploads/moodboard_urban_lifestyle.png'
  ];
  var grid = '';
  for (var i = 0; i < 4; i++) {
    var im = (imgs && imgs[i]) || defaultImgs[i];
    grid += '<div style="border-radius:14px;overflow:hidden;position:relative;box-shadow:0 6px 18px rgba(0,0,0,0.10);background:#f7f4ef;height:100%">' +
      '<img src="' + safeAttr(im) + '" style="width:100%;height:100%;object-fit:cover;display:block">' +
      '<div style="position:absolute;left:0;right:0;bottom:0;padding:9px 12px;background:linear-gradient(0deg,rgba(103,13,12,0.9),rgba(103,13,12,0.45));color:#fff;font-size:13px;font-weight:700;text-align:center">' + names[i] + '</div>' +
      '</div>';
  }
  var projName = (projectData && projectData.projectName) || 'عرض استثماري';
  return '<div data-no-reprocess="true" ' + _slideShell('#FFFFFF') + '>' +
    '<div style="position:absolute;inset:0;background:repeating-linear-gradient(45deg,transparent,transparent 38px,rgba(103,13,12,0.03) 38px,rgba(103,13,12,0.03) 76px);pointer-events:none"></div>' +
    // header
    '<div style="position:relative;z-index:3;display:flex;align-items:center;justify-content:space-between;padding:18px 36px 14px;border-bottom:2px solid #670D0C">' +
    '<div style="display:flex;align-items:center;gap:12px">' +
    '<div style="background:#fff;border-radius:10px;padding:6px 10px;color:#670D0C;font-weight:800;font-size:14px">منافع الاقتصادية للعقار</div>' +
    '<div style="width:1px;height:26px;background:#EFE7DC"></div>' +
    '<div style="font-size:15px;font-weight:800;color:#670D0C">المودبورد — لوحة الإلهام والتصور البصري</div>' +
    '</div>' +
    '<div style="display:flex;align-items:center;gap:8px">' +
    '<div style="font-size:10px;font-weight:700;color:#888;letter-spacing:.5px">VISUAL INSPIRATION</div>' +
    '<div style="width:8px;height:8px;border-radius:50%;background:#C2A176"></div>' +
    '</div>' +
    '</div>' +
    // gallery
    '<div style="position:relative;z-index:2;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:16px;padding:22px 36px;flex:1;height:560px">' + grid + '</div>' +
    // palette swatches
    '<div style="position:relative;z-index:3;display:flex;gap:16px;justify-content:center;align-items:center;padding:8px 0 16px;font-size:11px;color:#670D0C;font-weight:700">' +
    '<span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:12px;background:#670D0C;border-radius:3px;display:inline-block"></span> عنابي</span>' +
    '<span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:12px;background:#C2A176;border-radius:3px;display:inline-block"></span> ذهبي</span>' +
    '<span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:12px;background:#F5F0EE;border-radius:3px;display:inline-block;border:1px solid #ccc"></span> بيج فاخر</span>' +
    '</div>' +
    // footer
    '<div style="position:absolute;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:space-between;padding:10px 36px;border-top:1px solid #E2E8F0;background:#fff">' +
    '<div style="color:#64748B;font-size:11px">' + projName + '</div>' +
    '<div style="color:#64748B;font-size:11px">منافع الاقتصادية للعقار</div>' +
    '<div style="width:24px;height:24px;border-radius:50%;background:#670D0C;color:#fff;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800">15</div>' +
    '</div>' +
    '</div>';
}

// Build the CLOSING slide (slide 16): full burgundy background + logo + big
// "شكراً لكم" + project name + organized contact info.
function buildClosingSlideHtml(projectData) {
  var name = (projectData && projectData.projectName) || 'عرض مشروع استثماري';
  var preparedBy = (projectData && projectData.preparedBy) || '';
  var contact = (projectData && projectData.contactInfo) || '';
  // Contact info: split common separators into rows.
  var contactLines = String(contact).split(/[\n,،;|]+/).map(function (x) { return x.trim(); }).filter(Boolean);
  var contactHtml = '';
  if (contactLines.length) {
    contactHtml = '<div style="display:flex;flex-direction:column;gap:8px;margin-top:18px;max-width:760px">';
    contactLines.forEach(function (line) {
      contactHtml += '<div style="color:#E8E0D5;font-size:15px;font-weight:600;direction:rtl">' + line + '</div>';
    });
    contactHtml += '</div>';
  }
  return '<div data-no-reprocess="true" ' + _slideShell('#670D0C') + '>' +
    // subtle geometric pattern
    '<div style="position:absolute;inset:0;background:repeating-linear-gradient(45deg,transparent,transparent 60px,rgba(255,255,255,0.03) 60px,rgba(255,255,255,0.03) 120px);pointer-events:none"></div>' +
    '<div style="position:absolute;top:0;right:0;width:200px;height:200px;border-top:3px solid #C2A176;border-right:3px solid #C2A176;opacity:.6"></div>' +
    '<div style="position:absolute;bottom:0;left:0;width:200px;height:200px;border-bottom:3px solid #C2A176;border-left:3px solid #C2A176;opacity:.6"></div>' +
    '<div style="position:relative;z-index:5;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:50px 70px">' +
    '<div style="background:#fff;border-radius:18px;padding:18px 30px;box-shadow:0 16px 48px rgba(0,0,0,0.35);margin-bottom:30px">' +
    '<img src="##LOGO##" alt="منافع الاقتصادية" style="height:74px;width:auto;max-width:260px;object-fit:contain;display:block" />' +
    '</div>' +
    '<div style="color:#FFFFFF;font-size:60px;font-weight:900;line-height:1.2;text-shadow:0 2px 12px rgba(0,0,0,0.4)">شكراً لكم</div>' +
    '<div style="width:130px;height:3px;background:#C2A176;margin:22px 0"></div>' +
    '<div style="color:#C2A176;font-size:22px;font-weight:700">' + name + '</div>' +
    (preparedBy ? '<div style="color:#E8E0D5;font-size:14px;font-weight:600;margin-top:8px">إعداد: ' + preparedBy + '</div>' : '') +
    contactHtml +
    '<div style="margin-top:28px;color:#A7A9AC;font-size:12px;letter-spacing:1px;font-weight:700">منافع الاقتصادية للعقار · MANAFE ECONOMIC CO.</div>' +
    '</div>' +
    '</div>';
}

// Inject a side image (≈40% width) into a content slide that has none.
// Wraps the existing inner content to keep the layout intact.
function injectSideImage(html, img) {
  if (!img) return html;
  var imgSafe = safeAttr(img);
  var sideBlock =
    '<div style="width:38%;flex-shrink:0;align-self:stretch;display:flex;flex-direction:column;gap:8px">' +
    '<div style="flex:1;border-radius:14px;overflow:hidden;box-shadow:0 6px 18px rgba(0,0,0,0.10);min-height:200px">' +
    '<img src="' + imgSafe + '" style="width:100%;height:100%;object-fit:cover;display:block">' +
    '</div>' +
    '</div>';
  // If the slide already uses a main flex row, append our block; otherwise wrap.
  if (/display:\s*flex/i.test(html) && /class=["'][^"']*content/i.test(html)) {
    // attempt to insert before the last closing content div — simple & safe: append
    var lastClose = html.lastIndexOf('</div>');
    if (lastClose > 0) {
      return html.substring(0, lastClose) + sideBlock + html.substring(lastClose);
    }
  }
  // fallback: wrap the whole inner content in a row with the image on the left
  var firstClose = html.indexOf('>');
  if (firstClose > 0) {
    var open = html.substring(0, firstClose + 1);
    var rest = html.substring(firstClose + 1);
    return open + '<div style="display:flex;gap:20px;width:100%;height:100%;padding:90px 40px 60px;box-sizing:border-box">' +
      sideBlock + '<div style="flex:1;min-width:0">' + rest + '</div></div>';
  }
  return html;
}

// DESIGNER GENERATION: GLM builds the full deck from approved images.
// All creative-board images are uploaded to GLM so it has full visual
// context, plus header/footer rules + brand constraints.
app.post('/api/designer-generate', async function (req, res) {
  var projectData = req.body.projectData ? truncateProjectData(req.body.projectData, 8000) : null;
  var outline = req.body.outline || [];
  var images = req.body.images || []; // approved creative-board images (data URIs)
  var userId = req.body.userId || 'default_user';
  var userInstructions = req.body.instructions || '';
  var conversation = req.body.conversation || []; // prior chat (for regeneration)

  if (!projectData) return res.status(400).json({ error: 'Project data is required' });
  if (!Array.isArray(images) || images.length === 0) {
    return res.status(400).json({ error: 'At least one approved image is required' });
  }

  console.log('\n[Designer] Generating full deck with ' + images.length + ' images in batches...');
  console.log('  Slides: ' + outline.length + ' | Has images: ' + images.length);

  try {
    var slideList = outline.map(function (s, i) {
      return (i + 1) + '. ' + s.title + (s.bullets && s.bullets.length > 0 ? '\n   ' + s.bullets.join('\n   ') : '');
    }).join('\n');

    var designerPrompt = DESIGNER_SYSTEM_PROMPT
      .replace('{{IMAGE_COUNT}}', images.length)
      .replace('{{OUTLINE}}', slideList);

    var baseUserMessage = 'بيانات المشروع:\n' + JSON.stringify({
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

    baseUserMessage += '\n\nفهرس الشرائح الكامل:\n' + slideList;
    baseUserMessage += '\n\nالصور المعتمدة (' + images.length + ' صورة): تم رفعها لك في هذه الرسالة. صمم العرض كاملاً بناءً عليها.';
    baseUserMessage += '\nصِف كل صورة وأين ستستخدمها في تصميمك.';
    if (userInstructions) baseUserMessage += '\n\nتعليمات إضافية:\n' + userInstructions;

    // Batch configuration
    var BATCH_SIZE = 3;
    var totalSlides = outline.length;
    var allSlides = [];
    var lastCacheAnalytics = null;
    var allMessagesBackup = [];

    for (var startIdx = 0; startIdx < totalSlides; startIdx += BATCH_SIZE) {
      var endIdx = Math.min(startIdx + BATCH_SIZE, totalSlides);
      var batchOutline = outline.slice(startIdx, endIdx);
      var batchIndices = [];
      for (var k = startIdx + 1; k <= endIdx; k++) batchIndices.push(k);
      var batchIndicesStr = batchIndices.join(', ');

      console.log('  [Designer Batch] Designing slides ' + batchIndicesStr + ' of ' + totalSlides + '...');

      var batchUserMessage = baseUserMessage + '\n\n'
        + '⚠️ مطلوب منك الآن تصميم الشرائح رقم [' + batchIndicesStr + '] فقط من الفهرس المرفق.\n'
        + 'لا تصمم أي شريحة أخرى خارج هذا النطاق.\n'
        + 'أرجع كائن JSON صالح بالشكل التالي يحتوي فقط على الـ ' + batchOutline.length + ' شرائح المطلوبة في هذه الدفعة:\n'
        + '{"slides": [\n'
        + '  {"title": "عنوان الشريحة", "html": "HTML الشريحة..."}\n'
        + ']}';

      var responseVal = await callVisionChat(designerPrompt, batchUserMessage, images, userId, {
        maxTokens: 8000,
        temperature: 0.7
      });

      var data = responseVal.data;
      var messages = responseVal.messages;

      if (!data.choices || !data.choices[0]) {
        throw new Error('Vision model failed on batch ' + batchIndicesStr + ': ' + JSON.stringify(data));
      }

      var cacheAnalytics = computeCacheAnalytics(data, 'designer_gen_batch_' + Date.now());
      lastCacheAnalytics = cacheAnalytics;
      var resultText = data.choices[0].message.content.trim();

      // Save messages for backup
      allMessagesBackup = allMessagesBackup.concat(messages);
      allMessagesBackup.push({ role: 'assistant', content: resultText });

      var result = parseFirstJsonObject(resultText);
      if (!result || !result.slides) {
        throw new Error('No valid JSON object with "slides" array found in designer response for batch ' + batchIndicesStr);
      }

      var batchSlides = result.slides || [];
      // Tag each slide with its REAL 1-based number so post-processing can
      // target the cover (1) and the final closing slide regardless of deck length.
      // batchIndices are already 1-based numbers for this batch.
      for (var bi = 0; bi < batchSlides.length && bi < batchIndices.length; bi++) {
        batchSlides[bi]._slideNo = batchIndices[bi];
      }
      console.log('  [Designer Batch] Successfully generated ' + batchSlides.length + ' slides for batch ' + batchIndicesStr);
      allSlides = allSlides.concat(batchSlides);
    }

    // ═══ POST-PROCESSING: enforce images & special slides ═══
    // We cannot trust the vision model to copy data URIs into src (it often
    // drops them). So we ALWAYS resolve the tokens here and rebuild the
    // cover + moodboard + final closing slides deterministically. This also
    // guarantees that cover and closing never receive a header or footer.
    allSlides = postProcessDesignerSlides(allSlides, images, projectData);

    // Write backup of the combined conversation/responses
    writeSystemPrombetBackup(allMessagesBackup);

    console.log('  ✓ Generated total of ' + allSlides.length + ' slides with images');
    res.json({ success: true, slides: allSlides, cache_analytics: lastCacheAnalytics });

  } catch (err) {
    console.error('  ✗ Designer generation error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// DESIGNER CHAT: vision-enabled editing conversation.
// The current slide is rendered to an image and sent to GLM so it can
// "see" the design and respond with an updated full HTML for that slide.
// Conversation history is passed in and persisted by the client.
app.post('/api/designer-chat', async function (req, res) {
  var message = req.body.message;
  var currentSlideHtml = req.body.currentSlideHtml;
  var currentSlideTitle = req.body.currentSlideTitle || '';
  var slideImages = req.body.slideImages || []; // additional reference images to attach
  var projectData = truncateProjectData(req.body.projectData, 4000);
  var conversation = req.body.conversation || []; // [{role, content}]
  var userId = req.body.userId || 'default_user';

  if (!message) return res.status(400).json({ error: 'Message is required' });

  console.log('\n[Designer Chat] ' + message.substring(0, 80));

  try {
    // Render the current slide to an image so GLM can see it.
    var slideImageData = null;
    if (currentSlideHtml) {
      try {
        slideImageData = await renderSlideImage(currentSlideHtml, { scale: 2 });
        console.log('  ✓ Rendered current slide for vision');
      } catch (renderErr) {
        console.warn('  ⚠ Could not render slide image:', renderErr.message);
      }
    }

    var images = [];
    if (slideImageData) images.push(slideImageData);
    if (Array.isArray(slideImages)) {
      slideImages.forEach(function (img) {
        if (img && typeof img === 'string' && (img.indexOf('data:image/') === 0 || img.indexOf('http') === 0)) {
          images.push(img);
        }
      });
    }

    var userText = 'طلب المستخدم: ' + message + '\n\n';
    userText += 'الشريحة الحالية: ' + (currentSlideTitle || 'غير محدد') + '\n\n';
    userText += 'HTML الحالي للشريحة:\n' + (currentSlideHtml || 'لا يوجد') + '\n\n';
    if (images.length > 0) {
      userText += 'تم إرفاق صورة الشريحة الحالية' + (images.length > 1 ? ' وصور مرجعية' : '') + ' لتراها.\n\n';
    }
    userText += 'التعليمات:\n';
    userText += '- للتعديل على الشريحة الحالية: أرجع JSON بالشكل: {"action": "update_slide", "title": "العنوان (أبقه إن لم يتغير)", "html": "HTML كامل ومحدث بكل الأنماط المضمّنة"}.\n';
    userText += '- لإضافة شريحة جديدة في موضع محدد: أرجع JSON بالشكل: {"action": "add_slide", "insertAfterIndex": رقم_الشريحة_المطلوب_الوضع_بعدها (مثلاً لو طُلب الوضع بعد شريحة 3 أرجع 3 لتكون هي رقم 4), "title": "عنوان الشريحة الجديدة", "html": "HTML كامل للشريحة الجديدة"}.\n';
    userText += '- إذا كان الطلب سؤالاً أو لا يتطلب تعديلاً، أرجع {"action": "chat", "response": "ردك بالعربية"}.';

    // Vision-enabled editing: the rendered slide screenshot must be SEEN by
    // the model. GLM (ZAI) cannot see images, so route through Gemini.
    var { data, messages } = await callVisionChat(DESIGNER_CHAT_PROMPT, userText, images, userId, {
      maxTokens: 8000,
      temperature: 0.6,
      history: conversation
    });

    if (!data.choices || !data.choices[0]) {
      throw new Error('Vision model failed: ' + JSON.stringify(data));
    }

    var cacheAnalytics = computeCacheAnalytics(data, 'designer_chat_' + Date.now());
    var resultText = data.choices[0].message.content.trim();
    writeSystemPrombetBackup(messages, resultText);

    var result = parseFirstJsonObject(resultText);
    if (!result) {
      result = { action: 'chat', response: stripCodeFences(resultText).substring(0, 2000) };
    }

    if (result.action === 'update_slide' || result.action === 'add_slide' || result.action === 'insert_slide') {
      var slideHtml = result.html || '';
      var defaultImgs = [
        '/uploads/luxury_skyscraper_cover.png',
        '/uploads/moodboard_exterior.png',
        '/uploads/moodboard_materials.png',
        '/uploads/moodboard_interior.png',
        '/uploads/moodboard_urban_lifestyle.png'
      ];
      var userImgs = [];
      if (req.body.creativeImages) {
        if (req.body.creativeImages.cover) userImgs.push(req.body.creativeImages.cover);
        if (Array.isArray(req.body.creativeImages.moodboard)) {
          userImgs = userImgs.concat(req.body.creativeImages.moodboard.filter(Boolean));
        }
      }
      var activeImgs = userImgs.length >= 5 ? userImgs : defaultImgs;
      var imgCover = activeImgs[0] || defaultImgs[0];
      var img1 = activeImgs[1] || defaultImgs[1];
      var img2 = activeImgs[2] || defaultImgs[2];
      var img3 = activeImgs[3] || defaultImgs[3];
      var img4 = activeImgs[4] || defaultImgs[4];

      var isMoodboard = /مود.?بورد|moodboard|لوحة الأنماط/i.test(String(result.title || currentSlideTitle || ''));
      if (isMoodboard && (!slideHtml.includes('<img') && !slideHtml.includes('background-image'))) {
        result.html = buildMoodboardSlideHtml([img1, img2, img3, img4], projectData);
      } else {
        result.html = slideHtml
          .replace(/#*IMAGE_COVER#*/gi, imgCover)
          .replace(/#*COVER_IMAGE#*/gi, imgCover)
          .replace(/#*MAIN_IMAGE#*/gi, imgCover)
          .replace(/#*PROJECT_IMAGE_COVER#*/gi, imgCover)
          .replace(/#*PROJECT_IMAGE_1#*/gi, img1)
          .replace(/#*PROJECT_IMAGE_2#*/gi, img2)
          .replace(/#*PROJECT_IMAGE_3#*/gi, img3)
          .replace(/#*PROJECT_IMAGE_4#*/gi, img4)
          .replace(/#*MOODBOARD_IMAGE_1#*/gi, img1)
          .replace(/#*MOODBOARD_IMAGE_2#*/gi, img2)
          .replace(/#*MOODBOARD_IMAGE_3#*/gi, img3)
          .replace(/#*MOODBOARD_IMAGE_4#*/gi, img4);
      }
    }

    // The chat model can reintroduce a header/footer while editing the closing
    // slide. Keep the closing slide deterministic in every generation path.
    var resultTitle = String(result.title || currentSlideTitle || '');
    var isClosingEdit = result.action === 'update_slide' &&
      /ختام|closing|شكراً|thanks/i.test(resultTitle);
    if (isClosingEdit) {
      result.title = result.title || currentSlideTitle || 'الختام';
      result.html = buildClosingSlideHtml(projectData || {});
    }

    console.log('  ✓ Designer chat: ' + (result.action || 'chat'));
    res.json({ success: true, data: result, cache_analytics: cacheAnalytics });

  } catch (err) {
    console.error('  ✗ Designer chat error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ═══════════════════════════════════════════════════════════════
//  START SERVER
// ═══════════════════════════════════════════════════════════════

app.listen(PORT, function () {
  console.log('\n═══════════════════════════════════════');
  console.log('  🌐 Server running on port ' + PORT);
  console.log('  🔗 http://localhost:' + PORT);
  console.log('  📋 API Endpoints:');
  console.log('    GET  /api/project-data');
  console.log('    POST /api/generate');
  console.log('    GET  /api/files');
  console.log('    POST /api/generate-main-image');
  console.log('    POST /api/generate-images');
  console.log('    POST /api/generate-cover-prompt');
  console.log('    POST /api/generate-slide-image');
  console.log('    POST /api/generate-design');
  console.log('    POST /api/redesign-slide');
  console.log('    POST /api/edit-deck-data');
  console.log('    POST /api/ai-edit-slide');
  console.log('    POST /api/ai-chat');
  console.log('═══════════════════════════════════════\n');
});
