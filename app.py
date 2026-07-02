import os
import sys
import json
import time
import subprocess
import re
import base64
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
try:
    import webbrowser
except ImportError:
    webbrowser = None
import builtins

# Global print wrapper to prevent UnicodeEncodeError on Windows consoles when printing Arabic
_original_print = builtins.print
def safe_print(*args, **kwargs):
    try:
        _original_print(*args, **kwargs)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, 'encoding', 'utf-8') or 'utf-8'
        safe_args = []
        for arg in args:
            if isinstance(arg, str):
                safe_args.append(arg.encode(encoding, errors='replace').decode(encoding))
            else:
                safe_args.append(arg)
        try:
            _original_print(*safe_args, **kwargs)
        except Exception:
            try:
                _original_print(*(str(arg).encode('ascii', errors='replace').decode('ascii') for arg in args), **kwargs)
            except Exception:
                pass

builtins.print = safe_print

# Load environment variables
load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')

# Configuration
ZAI_KEY = os.environ.get("ZAI_KEY")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
ZAI_BASE = 'https://api.z.ai/api/paas/v4'
OPENROUTER_BASE = 'https://openrouter.ai/api/v1'
GLM_MODEL = os.environ.get("GLM_MODEL", "glm-5.1")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "google/gemini-3.1-flash-image-preview")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'outputs')
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')

# Try reading secrets from .env file if not in environment
if not ZAI_KEY or not OPENROUTER_KEY:
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key == 'ZAI_KEY' and not ZAI_KEY:
                        ZAI_KEY = val
                    elif key == 'OPENROUTER_KEY' and not OPENROUTER_KEY:
                        OPENROUTER_KEY = val

print(f"[CONFIG] ZAI_KEY: {'SET (' + ZAI_KEY[:8] + '...)' if ZAI_KEY else 'MISSING'}")
print(f"[CONFIG] OPENROUTER_KEY: {'SET (' + OPENROUTER_KEY[:8] + '...)' if OPENROUTER_KEY else 'MISSING'}")
USERS_DB_PATH = os.path.join(os.path.dirname(__file__), 'users_db.json')

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

# Helper Functions
def load_user_db():
    if os.path.exists(USERS_DB_PATH):
        try:
            with open(USERS_DB_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print("Error reading user database:", e)
    return {"users": {}}

def save_user_db(db):
    try:
        with open(USERS_DB_PATH, 'w', encoding='utf-8') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("Error writing user database:", e)

def get_training_history(user_id):
    db = load_user_db()
    users = db.get("users", {})
    user = users.get(user_id or 'default_user')
    if user and "ai_training_history" in user:
        return user["ai_training_history"]
    return []

def save_training_history(user_id, messages):
    db = load_user_db()
    id_key = user_id or 'default_user'
    if "users" not in db:
        db["users"] = {}
    if id_key not in db["users"]:
        db["users"][id_key] = {}
    db["users"][id_key]["ai_training_history"] = messages
    save_user_db(db)

def write_systemprombet_backup(messages, ai_response=None):
    try:
        merged = json.loads(json.dumps(messages))
        if ai_response:
            content = ai_response if isinstance(ai_response, str) else json.dumps(ai_response, indent=2, ensure_ascii=False)
            merged.append({"role": "assistant", "content": content})
            
        backup_content = ""
        for m in merged:
            backup_content += f"[{m['role'].upper()}]:\n{m['content']}\n\n═══════════════════════════════════════\n\n"
            
        with open('systemprombet', 'w', encoding='utf-8') as f:
            f.write(backup_content)
        with open('systemprombet.txt', 'w', encoding='utf-8') as f:
            f.write(backup_content)
        with open('systemprombet.json', 'w', encoding='utf-8') as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
            
        sync_to_github()
    except Exception as e:
        print("Failed to write systemprombet backup:", str(e))

def sync_to_github():
    try:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            return
        git_url = f"https://toxichassan22:{token}@github.com/toxichassan22/manafe-presentation-generator.git"
        init_cmd = ""
        if not os.path.exists(".git"):
            init_cmd = f"git init && git remote add origin {git_url} && git fetch origin main && git reset origin/main && "
            
        cmd = (
            f"{init_cmd}"
            'git config user.email "toxichassan22@github.com" && '
            'git config user.name "toxichassan22" && '
            'git add -f systemprombet systemprombet.txt systemprombet.json users_db.json && '
            'git diff --cached --quiet && echo "No changes to commit" || '
            f'(git commit -m "Auto-save chat history and backup [bot]" && '
            f'git push {git_url} HEAD:main)'
        )
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"sync_to_github failed: {e}")

def build_messages_with_training(system_content, current_messages, user_id=None):
    MAX_HISTORY_CHARS = 4000
    history = get_training_history(user_id or 'default_user')
    merged = []
    
    if system_content:
        merged.append({"role": "system", "content": system_content})
        
    if history:
        history_chars = 0
        trimmed_history = []
        for msg in reversed(history):
            content = msg.get("content") or ""
            msg_len = len(content)
            if history_chars + msg_len > MAX_HISTORY_CHARS:
                break
            history_chars += msg_len
            trimmed_history.insert(0, msg)
            
        for msg in trimmed_history:
            if msg.get("role") in ["user", "assistant", "system"]:
                merged.append({"role": msg["role"], "content": msg["content"]})
                
    for msg in current_messages:
        merged.append(msg)
        
    write_systemprombet_backup(merged)
    return merged

def compute_cache_analytics(response_json, fallback_session_id=None):
    usage = response_json.get("usage", {})
    cached_tokens = 0
    prompt_tokens = usage.get("prompt_tokens") or 0
    completion_tokens = usage.get("completion_tokens") or 0
    total_tokens = usage.get("total_tokens") or 0
    
    if "cached_tokens" in usage:
        cached_tokens = usage["cached_tokens"]
    elif "prompt_tokens_details" in usage and isinstance(usage["prompt_tokens_details"], dict):
        cached_tokens = usage["prompt_tokens_details"].get("cached_tokens") or 0
        
    saving_percentage = 0.0
    if prompt_tokens > 0:
        saving_percentage = round((cached_tokens / prompt_tokens) * 100, 1)
        
    status = "HIT" if cached_tokens > 0 else "MISS"
    session_id = response_json.get("id") or fallback_session_id or f"sess_{int(time.time())}"
    
    return {
        "status": status,
        "cached_tokens": cached_tokens,
        "session_id": session_id,
        "saving_percentage": saving_percentage,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens
    }

def get_mock_image_uri():
    try:
        p = os.path.join(os.path.dirname(__file__), 'mock-architecture.png')
        if os.path.exists(p):
            with open(p, 'rb') as f:
                data = f.read()
            return 'data:image/png;base64,' + base64.b64encode(data).decode('utf-8')
    except Exception:
        pass
    return 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNmYGD4DwAEhQGDc2a8fAAAAABJRU5ErkJggg=='

def call_image_api(prompt):
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Manafe PPTX Generator"
        }
        payload = {
            "model": IMAGE_MODEL,
            "messages": [{"role": "user", "content": prompt}]
        }
        print(f"  [ImageAPI] Calling {IMAGE_MODEL}...")
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=120)
        data = response.json()
        print(f"  [ImageAPI] Response status: {response.status_code}")
        if "error" in data:
            print(f"  [ImageAPI] ERROR: {data['error']}")
            return None
        if "choices" in data and len(data["choices"]) > 0:
            msg = data["choices"][0].get("message", {})
            # Check for images array
            if "images" in msg and len(msg["images"]) > 0:
                img = msg["images"][0]
                if isinstance(img, dict) and "image_url" in img:
                    url = img["image_url"].get("url")
                    print(f"  [ImageAPI] Got image URL (images array): {url[:80]}...")
                    return url
            # Check for content with inline image (base64)
            content = msg.get("content", "")
            if content and content.startswith("data:image"):
                print(f"  [ImageAPI] Got inline base64 image")
                return content
            # Check for multipart content
            if isinstance(msg.get("content"), list):
                for part in msg["content"]:
                    if part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url")
                        if url:
                            print(f"  [ImageAPI] Got image URL (content part): {url[:80]}...")
                            return url
            print(f"  [ImageAPI] No image found. Message keys: {list(msg.keys())}")
            print(f"  [ImageAPI] Content preview: {str(content)[:200]}")
        else:
            print(f"  [ImageAPI] No choices. Full response: {str(data)[:500]}")
    except Exception as e:
        print("  [ImageAPI] Exception:", str(e))
    return None

def call_image_api_with_reference(reference_image_base64, prompt):
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Manafe PPTX Generator"
        }
        payload = {
            "model": IMAGE_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": reference_image_base64}}
                    ]
                }
            ]
        }
        print(f"  [ImageAPI+Ref] Calling {IMAGE_MODEL} with reference image...")
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=120)
        data = response.json()
        print(f"  [ImageAPI+Ref] Response status: {response.status_code}")
        if "error" in data:
            print(f"  [ImageAPI+Ref] ERROR: {data['error']}")
            return None
        if "choices" in data and len(data["choices"]) > 0:
            msg = data["choices"][0].get("message", {})
            if "images" in msg and len(msg["images"]) > 0:
                img = msg["images"][0]
                if isinstance(img, dict) and "image_url" in img:
                    url = img["image_url"].get("url")
                    print(f"  [ImageAPI+Ref] Got image URL: {url[:80]}...")
                    return url
            content = msg.get("content", "")
            if content and content.startswith("data:image"):
                print(f"  [ImageAPI+Ref] Got inline base64 image")
                return content
            if isinstance(msg.get("content"), list):
                for part in msg["content"]:
                    if part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url")
                        if url:
                            print(f"  [ImageAPI+Ref] Got image URL (content part): {url[:80]}...")
                            return url
            print(f"  [ImageAPI+Ref] No image found. Message keys: {list(msg.keys())}")
            print(f"  [ImageAPI+Ref] Content preview: {str(content)[:200]}")
        else:
            print(f"  [ImageAPI+Ref] No choices. Full response: {str(data)[:500]}")
    except Exception as e:
        print("  [ImageAPI+Ref] Exception:", str(e))
    return None

def call_zai_chat(system_prompt, user_content, user_id=None, temperature=0.7, max_tokens=4000, disable_thinking=True, reference_image=None):
    headers = {
        "Authorization": f"Bearer {ZAI_KEY}",
        "Content-Type": "application/json"
    }
    
    # GLM/ZAI only supports text content - no image_url type
    user_message_content = user_content
        
    messages = build_messages_with_training(system_prompt, [{"role": "user", "content": user_message_content}], user_id)
    payload = {
        "model": GLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    if disable_thinking:
        payload["thinking"] = {"type": "disabled"}
        
    response = requests.post(f"{ZAI_BASE}/chat/completions", headers=headers, json=payload, timeout=180)
    return response.json(), messages

def truncate_project_data(data, max_chars=8000):
    if not data:
        return data
    s = json.dumps(data, ensure_ascii=False)
    if len(s) <= max_chars:
        return data
    obj = json.loads(s)
    keys = list(obj.keys())
    per_key = max_chars // len(keys)
    for k in keys:
        val = obj[k]
        if isinstance(val, str) and len(val) > per_key:
            obj[k] = val[:per_key] + "..."
        elif isinstance(val, list):
            arr_str = json.dumps(val, ensure_ascii=False)
            if len(arr_str) > per_key:
                obj[k] = val[:5]
    return obj


def build_adaptive_content_fallback(project_data, content_count):
    """Return safe content-only fallback slide titles for the official 16-slide outline."""
    project_data = project_data or {}
    project_name = (project_data.get('projectName') or '').strip()
    project_type = (project_data.get('projectType') or '').strip()
    city = (project_data.get('city') or '').strip()

    topics = [
        'الملخص التنفيذي للمشروع',
        'فكرة المشروع وهيكلته الاستثمارية',
        'الموقع الجغرافي والميزات المحيطة',
        'مميزات المشروع والقيمة المضافة',
        'مكونات المشروع والمساحات التأجيرية',
        'افتراضات الإيرادات والربح التشغيلي',
        'افتراضات التكاليف والاستثمار المطلوب',
        'الأرباح المتوقعة واستراتيجية التخارج',
        'المؤشرات المالية المتوقعة',
        'الجدول الزمني ومراحل التنفيذ',
        'فرص الاستثمار ونقاط القوة',
        'المخاطر والافتراضات',
    ]

    if project_type:
        topics[1] = f'فكرة {project_type} وهيكلته الاستثمارية'
    if city:
        topics[2] = f'الموقع الجغرافي في {city} والميزات المحيطة'
    if project_name:
        topics[0] = f'الملخص التنفيذي لمشروع {project_name}'

    out = []
    for title in topics[:max(0, int(content_count or 0))]:
        out.append({'title': title, 'requires_image': False, 'type': 'content', 'bullets': []})
    return out

# Flask Routes
@app.route('/')
def index_route():
    return send_from_directory('.', 'index.html')

@app.route('/outputs/<path:path>')
def serve_outputs(path):
    return send_from_directory('outputs', path)

@app.route('/api/project-data', methods=['GET'])
def get_project_data():
    data_path = os.path.join(os.path.dirname(__file__), 'project-data.json')
    if os.path.exists(data_path):
        with open(data_path, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify(None)

@app.route('/api/generate', methods=['POST'])
def generate_pptx():
    topic = request.json.get('topic')
    if not topic:
        return jsonify({'error': 'Topic is required'}), 400
        
    print("\n" + "="*39)
    print("  Starting generation from web UI...")
    print(f"  Topic: {topic}")
    print("="*39)
    
    try:
        data_file = os.path.join(os.path.dirname(__file__), 'project-data.json')
        escaped_topic = topic.replace('"', '\\"')
        cmd = f'node glm-designer.js "{escaped_topic}" "{data_file}"'
        print(f"Executing command: {cmd}")
        
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=os.path.dirname(__file__),
            capture_output=True,
            text=True,
            timeout=300
        )
        print(result.stdout)
        if result.stderr:
            print("Stderr:", result.stderr)
            
        files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.pptx')]
        files_with_time = []
        for f in files:
            p = os.path.join(OUTPUT_DIR, f)
            files_with_time.append((f, os.path.getmtime(p)))
            
        files_with_time.sort(key=lambda x: x[1], reverse=True)
        
        if files_with_time:
            latest_file = files_with_time[0][0]
            return jsonify({
                'success': True,
                'file': latest_file,
                'downloadUrl': f'/outputs/{latest_file}'
            })
        else:
            return jsonify({'success': True, 'file': None, 'message': 'Generation completed but no file found'})
    except Exception as e:
        print("Generation error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/files', methods=['GET'])
def list_files():
    if not os.path.exists(OUTPUT_DIR):
        return jsonify([])
    files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.pptx')]
    files_info = []
    for f in files:
        p = os.path.join(OUTPUT_DIR, f)
        stat = os.stat(p)
        files_info.append({
            'name': f,
            'url': f'/outputs/{f}',
            'size': stat.st_size,
            'time': datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    files_info.sort(key=lambda x: x['time'], reverse=True)
    return jsonify(files_info)

@app.route('/api/save-training', methods=['POST'])
def api_save_training():
    messages = request.json.get('messages') or request.json.get('history')
    user_id = request.json.get('userId') or 'default_user'
    if not messages or not isinstance(messages, list):
        return jsonify({'error': 'Messages array is required'}), 400
    try:
        save_training_history(user_id, messages)
        write_systemprombet_backup(messages)
        print(f"[Training] Saved training history and backup files for user: {user_id} ({len(messages)} messages)")
        return jsonify({'success': True, 'message': 'Training history and backup saved successfully'})
    except Exception as e:
        print("[Training] Save error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/get-training', methods=['GET'])
def api_get_training():
    user_id = request.args.get('userId') or 'default_user'
    try:
        history = get_training_history(user_id)
        return jsonify({'success': True, 'messages': history, 'history': history})
    except Exception as e:
        print("[Training] Get error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-main-image', methods=['POST'])
def api_generate_main_image():
    prompt = request.json.get('prompt')
    reference_image = request.json.get('referenceImage')
    mock = request.json.get('mock')
    
    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400
    if mock:
        print("  [Mock Mode] Returning mock cover image")
        return jsonify({'success': True, 'image': get_mock_image_uri()})
        
    print("\n[Image] Generating main cover image...")
    print(f"  Prompt: {prompt[:100]}...")
    
    try:
        suffix = '. Focus ONLY on the building itself and its architectural details. Keep the background clean and minimal, with absolutely no complex surrounding elements, no unnecessary context, no people, no busy surrounding streets, and no complex landscapes. Just the building itself. Professional architectural photography, modern luxury building, high quality, no text, no watermarks.'
        if reference_image:
            print("  Using uploaded image as base reference for main image...")
            image = call_image_api_with_reference(reference_image, prompt + suffix)
        else:
            image = call_image_api(prompt + suffix)
            
        if image:
            print("  [OK] Main image generated successfully")
            return jsonify({'success': True, 'image': image})
        else:
            print("  [WARN] No image returned, using placeholder")
            return jsonify({'success': False, 'error': 'No image generated', 'image': None})
    except Exception as e:
        print("  [FAIL] Main image error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-image-prompt', methods=['POST'])
def api_generate_image_prompt():
    """Generate an AI image prompt from project data."""
    data = request.json or {}
    project_name = data.get('projectName', '')
    project_type = data.get('projectType', '')
    city = data.get('city', '')
    location = data.get('location', '')
    building_name = data.get('buildingName', '')
    idea = data.get('idea', '')
    structure = data.get('structure', '')
    project_features = data.get('projectFeatures', [])
    components = data.get('components', [])
    mock = data.get('mock', False)

    if mock:
        return jsonify({'success': True, 'prompt': f'فوتوريالستك، {project_name} في {city}، واجهات زجاجية حديثة، إضاءة غروب ذهبية، جودة عالية'})

    system_prompt = """أنت مهندس معماري ومحترف في كتابة prompts لتوليد الصور بالذكاء الاصطناعي.
اكتب وصفاً تفصيلياً باللغة الإنجليزية لصورة غلاف احترافية للمشروع العقاري المقدم.
الوصف يجب أن يكون:
- باللغة الإنجليزية (وليس العربية)
- فوتوريالستيك وواقعي
- يتضمن تفاصيل المبنى والواجهة والإضاءة
- مناسب لـ Gemini أو DALL-E
-طوله 3-5 جمل
- يبدأ بصفات المبنى من الخارج
- يذكر المدينة والموقع إن وُجد
- لا يذكر أي نصوص أو أرقام داخل الصورة
- يركز على الواجهة المعمارية فقط

أرجع فقط نص الوصف الإنجليزي بدون أي تنسيق إضافي."""

    user_prompt = f"""بيانات المشروع:
- اسم المشروع: {project_name}
- اسم المبنى: {building_name}
- نوع المشروع: {project_type}
- المدينة: {city}
- الموقع: {location}
- الفكرة: {idea}
- الهيكل: {structure}
- ميزات المشروع: {', '.join(project_features) if isinstance(project_features, list) else project_features}
- المكونات: {', '.join([c.get('name','') for c in components]) if isinstance(components, list) else ''}

اكتب وصف الصورة الأساسية (الغلاف) لهذا المشروع."""

    try:
        from services.llm_service import generate_content
        prompt_text = generate_content(system_prompt, user_prompt)
        prompt_text = prompt_text.strip().strip('"').strip("'")
        print(f"  [OK] Generated image prompt: {prompt_text[:100]}...")
        return jsonify({'success': True, 'prompt': prompt_text})
    except Exception as e:
        print(f"  [FAIL] Image prompt generation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/generate-images', methods=['POST'])
def api_generate_images():
    prompts = request.json.get('prompts')
    reference_image = request.json.get('referenceImage')
    mock = request.json.get('mock')
    
    if not prompts or not isinstance(prompts, list) or len(prompts) == 0:
        return jsonify({'error': 'Prompts array is required'}), 400
    if mock:
        print("  [Mock Mode] Returning mock variant images")
        mock_img = get_mock_image_uri()
        images = [{'url': mock_img, 'prompt': p} for p in prompts]
        return jsonify({'success': True, 'images': images})
        
    print(f"\n[Images] Generating {len(prompts)} mood board images...")
    
    try:
        images = []
        base_reference = reference_image
        
        if base_reference:
            print("  [OK] Using uploaded main image as base reference for all generated images...")
            for i, p in enumerate(prompts):
                print(f"  [{i+1}/{len(prompts)}] Generating variant from reference...")
                img = call_image_api_with_reference(
                    base_reference,
                    p + '. Same building style, same architectural identity, professional photography, no text.'
                )
                if img:
                    images.append({'url': img, 'prompt': p})
                    print("    [OK] Variant created")
                else:
                    fallback = call_image_api(p + '. Professional architectural photography, high quality, no text.')
                    images.append({'url': fallback or base_reference, 'prompt': p})
                    print("    [OK] Fallback created")
                if i < len(prompts) - 1:
                    time.sleep(1.5)
        else:
            print(f"  [1/{len(prompts)}] Base image...")
            first_image = call_image_api(
                prompts[0] + '. Professional architectural photography, modern luxury building, high quality, no text.'
            )
            if first_image:
                images.append({'url': first_image, 'prompt': prompts[0]})
                print("    [OK] Base image created")
                
                for i in range(1, len(prompts)):
                    p = prompts[i]
                    print(f"  [{i+1}/{len(prompts)}] Variant image...")
                    variant = call_image_api_with_reference(
                        first_image,
                        p + '. Same building style, same architectural identity, professional photography, no text.'
                    )
                    if variant:
                        images.append({'url': variant, 'prompt': p})
                        print("    [OK] Variant created")
                    else:
                        images.append({'url': first_image, 'prompt': p})
                        print("    [OK] Used base image as fallback")
                    time.sleep(1.5)
            else:
                for i, p in enumerate(prompts):
                    print(f"  [{i+1}/{len(prompts)}] Independent image...")
                    img = call_image_api(p + '. Professional architectural photography, high quality, no text.')
                    images.append({'url': img, 'prompt': p})
                    if i < len(prompts) - 1:
                        time.sleep(1.5)
                        
        print(f"  [OK] Generated {len([x for x in images if x['url']])}/{len(prompts)} images")
        return jsonify({'success': True, 'images': images})
    except Exception as e:
        print("  [FAIL] Images error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-image', methods=['POST'])
def api_generate_image():
    prompt = request.json.get('prompt')
    reference_image = request.json.get('referenceImage')
    mock = request.json.get('mock')
    
    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400
    if mock:
        print("  [Mock Mode] Returning mock image")
        mock_img = get_mock_image_uri()
        return jsonify({'success': True, 'image': mock_img})
        
    print(f"\n[Image] Generating single image...")
    try:
        img = None
        if reference_image:
            img = call_image_api_with_reference(
                reference_image,
                prompt + '. Same building style, same architectural identity, professional photography, no text.'
            )
        if not img:
            img = call_image_api(prompt + '. Professional architectural photography, high quality, no text.')
        if img:
            print("  [OK] Image generated")
            return jsonify({'success': True, 'image': img})
        else:
            return jsonify({'error': 'Image generation failed'}), 500
    except Exception as e:
        print("  [FAIL] Image error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-slide-image', methods=['POST'])
def api_generate_slide_image():
    prompt = request.json.get('prompt')
    reference_image = request.json.get('referenceImage')
    mock = request.json.get('mock')
    
    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400
    if mock:
        print("  [Mock Mode] Returning mock slide image")
        return jsonify({'success': True, 'image': get_mock_image_uri()})
        
    print("\n[SlideImage] Generating slide image...")
    
    try:
        suffix_ref = '. Focus ONLY on the building itself and its architectural details. Keep the background clean and minimal, with absolutely no complex surrounding elements, no unnecessary context, no people, no busy surrounding streets, and no complex landscapes. Just the building itself. Same building style, professional architectural photography, high quality, no text.'
        suffix_no_ref = '. Focus ONLY on the building itself and its architectural details. Keep the background clean and minimal, with absolutely no complex surrounding elements, no unnecessary context, no people, no busy surrounding streets, and no complex landscapes. Just the building itself. Professional architectural photography, high quality, no text, no watermarks.'
        if reference_image:
            image = call_image_api_with_reference(reference_image, prompt + suffix_ref)
        else:
            image = call_image_api(prompt + suffix_no_ref)
            
        if image:
            print("  [OK] Slide image generated")
            return jsonify({'success': True, 'image': image})
        else:
            return jsonify({'success': False, 'error': 'No image generated'})
    except Exception as e:
        print("  [FAIL] Slide image error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/edit-deck-data', methods=['POST'])
def api_edit_deck_data():
    edit_request = request.json.get('request')
    project_data = request.json.get('data')
    user_id = request.json.get('userId') or 'default_user'
    
    if not edit_request:
        return jsonify({'error': 'Edit request is required'}), 400
        
    print("\n[Edit] AI deck data edit...")
    print(f"  Request: {edit_request[:100]}")
    
    try:
        system_prompt = (
            'You are a professional investment project data editor for "منافع الاقتصادية" (Manafe).\n'
            'The user will give you a request to modify project data fields. You must return the COMPLETE modified data as JSON.\n\n'
            'RULES:\n'
            '- Return ONLY valid JSON, no markdown, no code blocks\n'
            '- Keep all existing fields intact unless the user specifically asks to change them\n'
            '- For array fields (locationFeatures, projectFeatures, investmentHighlights, risks, components, timelineRows), maintain the same structure\n'
            '- Use Arabic text when editing Arabic fields\n'
            '- Make smart improvements based on the user\'s request\n'
            '- Return the FULL data object with all fields'
        )
        user_content = f"PROJECT DATA:\n{json.dumps(project_data, indent=2, ensure_ascii=False)}\n\nEDIT REQUEST:\n{edit_request}"
        
        data, messages = call_zai_chat(system_prompt, user_content, user_id, reference_image=project_data.get('mainImageData'))
        
        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM failed: " + json.dumps(data, ensure_ascii=False))
            
        cache_analytics = compute_cache_analytics(data, 'edit_deck_' + str(int(time.time())))
        if "usage" in data:
            u = data["usage"]
            print(f"  [OK] Tokens: {u.get('total_tokens')} | Cache: {cache_analytics['status']} ({cache_analytics['cached_tokens']} tokens)")
            
        result_text = data["choices"][0]["message"]["content"].strip()
        write_systemprombet_backup(messages, result_text)
        
        match = re.search(r'\{[\s\S]*\}', result_text)
        if match:
            edited_data = json.loads(match.group(0))
            print("  [OK] Data edited successfully")
            return jsonify({'success': True, 'data': edited_data, 'cache_analytics': cache_analytics})
        else:
            raise Exception("Could not parse AI response as JSON")
    except Exception as e:
        print("  [FAIL] Edit error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai-edit-slide', methods=['POST'])
def api_ai_edit_slide():
    slide_title = request.json.get('slideTitle')
    slide_content = request.json.get('slideContent')
    edit_request = request.json.get('editRequest')
    project_data = truncate_project_data(request.json.get('projectData'), 8000)
    user_id = request.json.get('userId') or 'default_user'
    chat_only = request.json.get('chatOnly', False)
    
    if not edit_request:
        return jsonify({'error': 'Edit request is required'}), 400
        
    print(f"\n[SlideEdit] Editing slide: {slide_title}")
    print(f"  Request: {edit_request[:100]}")
    
    try:
        system_prompt = (
            'You are a standalone AI assistant for editing individual slides of "منافع الاقتصادية" (Manafe).\n'
            'You are COMPLETELY INDEPENDENT of any slide generation, outline generation, or design-generation system.\n'
            'You only edit the provided single slide content.\n\n'
            'RULES:\n'
            '- Return a JSON object with: { "title": "slide title", "content": "new HTML content for the slide", "bullets": ["bullet1", "bullet2"] }\n'
            '- The content should be HTML that works inside a div\n'
            '- Keep the same style and language as the original\n'
            '- Make smart improvements based on the user\'s request\n'
            '- For investment project slides, maintain professional tone in Arabic\n'
            '- Return ONLY valid JSON, no markdown\n'
            '- NEVER mention errors like "1260", "text too large", or any system error\n'
            '- NEVER include unrelated slide generation context'
        )
        user_content = (
            f"SLIDE TITLE: {slide_title}\n\n"
            f"CURRENT CONTENT:\n{slide_content}\n\n"
            f"EDIT REQUEST:\n{edit_request}"
        )
        if project_data:
            user_content += f"\n\nPROJECT DATA CONTEXT:\n{json.dumps(project_data or {}, indent=2, ensure_ascii=False)}"
        if chat_only:
            user_content += "\n\n[IMPORTANT: This is a chat-only edit. Do NOT perform any bulk generation or reference other systems.]"
        
        data, messages = call_zai_chat(system_prompt, user_content, user_id, reference_image=project_data.get('mainImageData') if project_data else None)
        
        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM failed: " + json.dumps(data, ensure_ascii=False))
            
        cache_analytics = compute_cache_analytics(data, 'edit_slide_' + str(int(time.time())))
        result_text = data["choices"][0]["message"]["content"].strip()
        write_systemprombet_backup(messages, result_text)
        
        match = re.search(r'\{[\s\S]*\}', result_text)
        if match:
            edited = json.loads(match.group(0))
            print(f"  [OK] Slide edited successfully | Cache: {cache_analytics['status']}")
            return jsonify({'success': True, 'data': edited, 'cache_analytics': cache_analytics})
        else:
            raise Exception("Could not parse AI response")
    except Exception as e:
        print("  [FAIL] Slide edit error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai-chat', methods=['POST'])
def api_ai_chat():
    message = request.json.get('message')
    slides_data = request.json.get('slidesData')
    current_slide_idx = request.json.get('currentSlideIdx')
    project_data = truncate_project_data(request.json.get('projectData'), 8000)
    user_id = request.json.get('userId') or 'default_user'
    
    if not message:
        return jsonify({'error': 'Message is required'}), 400
        
    print("\n[Chat] AI chat message...")
    print(f"  Message: {message[:100]}")
    
    try:
        system_prompt = (
            'أنت محرر عروض تقديمية احترافي لشركة "منافع الاقتصادية" (Manafe).\n'
            'تساعد المستخدمين في تحرير وتحسين عروض مشاريعهم الاستثمارية.\n\n'
            'CRITICAL RULE - WHICH SLIDE TO EDIT:\n'
            '- The user is currently viewing and editing a SPECIFIC slide (given as "currentSlideIdx").\n'
            '- When the user says "change the title" or "edit the content" WITHOUT specifying which slide, '
            'you MUST edit the CURRENT slide (the one marked as currentSlideIdx).\n'
            '- NEVER edit a different slide unless the user explicitly names it (e.g., "edit slide 3" or "change the executive summary").\n'
            '- Always respond with the correct slideIdx matching the current slide.\n\n'
            'IMPORTANT RULES FOR APPLYING INSTRUCTIONS TO ALL SLIDES:\n'
            '- When the user asks to change design/style/colors/fonts that should apply to ALL slides, you MUST:\n'
            '  1. Respond with "style_override" action\n'
            '  2. Make sure the CSS covers ALL slide elements (not just one slide)\n'
            '  3. Explain clearly that the change will be applied to ALL slides in the presentation\n\n'
            'You can:\n'
            '1. Edit slide content based on requests\n'
            '2. Suggest improvements and general styling changes (colors, font size, alignment, margins)\n'
            '3. Generate new content\n'
            '4. Answer questions about the project\n\n'
            'When the user asks to modify the design/style/layout/colors/fonts (which will apply to the PDF export), respond with:\n'
            '{ "action": "style_override", "css": "CSS rules to inject, e.g. .ge-slide-title { color: #C4A35A !important; } .ge-slide-card { border-color: #C4A35A !important; }", "response": "Message in Arabic explaining that this style change will be applied to ALL slides in the presentation" }\n\n'
            'When the user asks you to edit slide content, respond with:\n'
            '{ "action": "edit", "slideIdx": <number>, "changes": { "title": "new title if changed", "content": "new HTML content" } }\n\n'
            'When the user asks you to edit multiple slides, respond with:\n'
            '{ "action": "edit_multiple", "updates": [ { "slideIdx": <number>, "changes": { "title": "new title if changed", "content": "new HTML content" } } ], "response": "Message in Arabic explaining the edits" }\n\n'
            'When the user asks a question or wants suggestions, respond with:\n'
            '{ "action": "chat", "response": "your response in Arabic" }\n\n'
            'Always respond in Arabic unless asked otherwise.\n'
            'Return ONLY valid JSON.'
        )
        
        context_data = {
            "currentSlide": current_slide_idx,
            "message": message
        }
        if slides_data:
            context_data["slides"] = [
                {"idx": i, "title": s.get("title", "")}
                for i, s in enumerate(slides_data)
            ]
        # Also send current slide content for context
        if slides_data and current_slide_idx is not None and 0 <= current_slide_idx < len(slides_data):
            current = slides_data[current_slide_idx]
            context_data["currentSlideTitle"] = current.get("title", "")
            context_data["currentSlideContent"] = (current.get("glm_html") or current.get("content") or "")[:2000]
            
        user_content = (
            f"PROJECT DATA:\n{json.dumps(project_data or {}, indent=2, ensure_ascii=False)}\n\n"
            f"SLIDES CONTEXT:\n{json.dumps(context_data, indent=2, ensure_ascii=False)}\n\n"
            f"USER MESSAGE:\n{message}"
        )
        
        data, messages = call_zai_chat(system_prompt, user_content, user_id, reference_image=project_data.get('mainImageData'))
        
        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM failed: " + json.dumps(data, ensure_ascii=False))
            
        cache_analytics = compute_cache_analytics(data, 'chat_' + str(int(time.time())))
        result_text = data["choices"][0]["message"]["content"].strip()
        write_systemprombet_backup(messages, result_text)
        
        match = re.search(r'\{[\s\S]*\}', result_text)
        if match:
            result = json.loads(match.group(0))
            print(f"  [OK] Chat response generated | Cache: {cache_analytics['status']}")
            return jsonify({'success': True, 'data': result, 'cache_analytics': cache_analytics})
        else:
            return jsonify({
                'success': True,
                'data': {'action': 'chat', 'response': result_text},
                'cache_analytics': cache_analytics
            })
    except Exception as e:
        print("  [FAIL] Chat error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-outline', methods=['POST'])
def api_generate_outline():
    project_data = truncate_project_data(request.json.get('projectData'), 4000)
    user_id = request.json.get('userId') or 'default_user'
    
    print("\n[Outline] Generating outline structure via GLM 5.1...")
    
    try:
        system_content = (
            'أنت خبير في إعداد عروض تقديمية استثمارية احترافية لشركات العقارات والاستثمار في السعودية. مهمتك إنشاء هيكل (outline) للعرض التقديمي بناءً على بيانات المشروع.\n\n'
            'أعد النتيجة كـ JSON فقط بدون أي نص إضافي بالشكل:\n'
            '{\n'
            '  "slides": [\n'
            '    {\n'
            '      "title": "عنوان الشريحة",\n'
            '      "bullets": ["نقطة 1", "نقطة 2", "نقطة 3"],\n'
            '      "requires_image": true أو false (حدد true لـ 5 شرائح بصرية كحد أقصى كالغلاف وصور الموقع ومميزات المشروع ومكوناته، والباقي false)\n'
            '    }\n'
            '  ]\n'
            '}\n\n'
            'اجعل العرض يحتوي على 16 شريحة بالضبط تشمل:\n'
            '1. غلاف المشروع\n'
            '2. الفهرس (جدول محتويات العرض)\n'
            '3. الملخص التنفيذي\n'
            '4. فكرة المشروع والهيكلة\n'
            '5. مميزات الموقع (إذا تم توفير رابط قوقل ماب googleMapsLink في بيانات المشروع، يجب تضمينه كنقطة تحتوي على الرابط لعرضه)\n'
            '6. مميزات المشروع\n'
            '7. مكونات المشروع والمساحات\n'
            '8. افتراضات الربح التشغيلي التأجيري\n'
            '9. افتراضات التكاليف\n'
            '10. الأرباح والتخارج\n'
            '11. المؤشرات المالية المتوقعة\n'
            '12. الجدول الزمني ومراحل المشروع\n'
            '13. فرص الاستثمار ونقاط القوة\n'
            '14. المخاطر والافتراضات\n'
            '15. معاينة الهوية البصرية (Mood Board)\n'
            '16. الختام وبيانات التواصل\n\n'
            'اجعل النقاط مختصرة واحترافية ومحددة. لا تكتب نصاً طويلاً - فقط نقاط ملخصة.'
        )
        user_content = f"بيانات المشروع:\n{json.dumps(project_data or {}, indent=2, ensure_ascii=False)}"
        
        reference_image = None
        if project_data and isinstance(project_data, dict):
            reference_image = project_data.get('mainImageData')
        
        data, messages = call_zai_chat(system_content, user_content, user_id, max_tokens=2000, reference_image=reference_image)
        
        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM failed: " + json.dumps(data, ensure_ascii=False))
            
        cache_analytics = compute_cache_analytics(data, 'outline_' + str(int(time.time())))
        result_text = data["choices"][0]["message"]["content"].strip()
        write_systemprombet_backup(messages, result_text)
        
        match = re.search(r'\{[\s\S]*\}', result_text)
        if match:
            result = json.loads(match.group(0))
            slides = result.get("slides") or []
            
            # Enforce exactly 16 slides
            required_slides = [
                'غلاف المشروع', 'الفهرس', 'الملخص التنفيذي', 'فكرة المشروع والهيكلة', 'مميزات الموقع',
                'مميزات المشروع', 'مكونات المشروع والمساحات', 'افتراضات الربح التشغيلي التأجيري', 'افتراضات التكاليف',
                'الأرباح والتخارج', 'المؤشرات المالية المتوقعة', 'الجدول الزمني ومراحل المشروع', 'فرص الاستثمار ونقاط القوة',
                'المخاطر والافتراضات', 'معاينة الهوية البصرية', 'الختام وبيانات التواصل'
            ]
            
            if len(slides) < 16:
                existing_titles = [s.get('title', '') for s in slides]
                for i, req_title in enumerate(required_slides):
                    if i >= len(slides):
                        slides.append({
                            'title': req_title,
                            'bullets': [],
                            'requires_image': False
                        })
                    elif not any(req_title in t for t in existing_titles):
                        slides.insert(i, {
                            'title': req_title,
                            'bullets': [],
                            'requires_image': False
                        })
                slides = slides[:16]
                print(f"  [FIX] Padded outline to {len(slides)} slides")
            
            print(f"  [OK] Outline generated: {len(slides)} slides | Cache: {cache_analytics['status']}")
            return jsonify({'success': True, 'outline': slides, 'cache_analytics': cache_analytics})
        else:
            raise Exception("No JSON in GLM response")
    except Exception as e:
        print("  [FAIL] Outline generation error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-titles', methods=['POST'])
def api_generate_titles():
    project_data = truncate_project_data(request.json.get('projectData'), 4000)
    mock = request.json.get('mock')
    slide_count = min(max(int(request.json.get('slideCount', 16) or 16), 3), 16)
    user_id = request.json.get('userId') or 'default_user'
    
    content_count = slide_count - 4  # cover + toc + moodboard + closing are fixed
    
    if mock:
        print(f"  [Mock Mode] Returning {slide_count} mock titles (cover + toc + {content_count} content + moodboard + closing)")
        all_mock_content = [
            {"title": "غلاف المشروع", "requires_image": True, "type": "cover"},
            {"title": "الفهرس", "requires_image": False, "type": "toc"},
            {"title": "الملخص التنفيذي", "requires_image": False, "type": "content"},
            {"title": "فكرة المشروع والهيكلة", "requires_image": False, "type": "content"},
            {"title": "مميزات الموقع", "requires_image": True, "type": "content"},
            {"title": "مميزات المشروع", "requires_image": True, "type": "content"},
            {"title": "مكونات المشروع والمساحات", "requires_image": True, "type": "content"},
            {"title": "الربح التشغيلي", "requires_image": False, "type": "content"},
            {"title": "التكاليف", "requires_image": False, "type": "content"},
            {"title": "الأرباح والتخارج", "requires_image": False, "type": "content"},
            {"title": "المؤشرات المالية المتوقعة", "requires_image": False, "type": "content"},
            {"title": "الجدول الزمني ومراحل المشروع", "requires_image": False, "type": "content"},
            {"title": "فرص الاستثمار ونقاط القوة", "requires_image": False, "type": "content"},
            {"title": "المخاطر والافتراضات", "requires_image": False, "type": "content"},
            {"title": "معاينة الهوية البصرية", "requires_image": True, "type": "moodboard"},
            {"title": "ختام العرض", "requires_image": False, "type": "closing"}
        ]
        mock_titles = all_mock_content[:slide_count]
        if slide_count >= 3:
            mock_titles[0] = {"title": "غلاف المشروع", "requires_image": True, "type": "cover"}
            mock_titles[-1] = {"title": "ختام العرض", "requires_image": False, "type": "closing"}
        return jsonify({
            'success': True,
            'titles': mock_titles,
            'totalSlides': len(mock_titles),
            'cache_analytics': {'status': 'MOCKED', 'cached_tokens': 0, 'total_tokens': 0}
        })
        
    print(f"\n[Titles] Generating {slide_count} titles (cover + toc + {content_count} content + moodboard + closing)...")
    start_time = time.time()
    
    try:
        all_topics = [
            "الملخص التنفيذي",
            "فكرة المشروع والهيكلة",
            "مميزات الموقع",
            "مميزات المشروع",
            "مكونات المشروع والمساحات",
            "الربح التشغيلي",
            "التكاليف",
            "الأرباح والتخارج",
            "المؤشرات المالية المتوقعة",
            "الجدول الزمني ومراحل المشروع",
            "فرص الاستثمار ونقاط القوة",
            "المخاطر والافتراضات"
        ]

        system_content = (
            f'أنت خبير في العروض التقديمية الاستثمارية.\n\n'
            f'العرض التقديمي يحتوي على بالضبط {slide_count} شريحة.\n'
            f'أنت تولّد العناوين للشرائح الوسطى ({content_count} شريحة محتوى فقط).\n'
            f'الشريحة الأولى (غلاف) والثانية (فهرس) والبنت لوحتين الأخيرتين (مود بورد + ختام) ستُولَّد تلقائياً — لا تضع عناوين لهما.\n\n'
            f'اختر بالضبط {content_count} مواضيع محتوى مناسبة:\n'
            + '\n'.join([f'{i+1}. {t}' for i, t in enumerate(all_topics)])
            + '\n\n'
            'أعد النتيجة كـ JSON فقط بالصيغة:\n'
            '{"titles": [{"title": "عنوان الشريحة", "requires_image": true أو false}]}\n\n'
            'قواعد:\n'
            f'1. ولّد بالضبط {content_count} عناوين (لا أكثر ولا أقل)\n'
            '2. حدد requires_image: true لـ 3 شرائح بصرية كحد أقصى (صور الموقع ومميزات المشروع ومكوناته)\n'
            '3. باقي الشرائح requires_image: false\n'
            '4. لا تضع عناوين للغلاف أو الفهرس أو المود بورد أو الختام — هي تلقائية'
        )
        user_content = f"بيانات المشروع:\n{json.dumps(project_data or {}, indent=2, ensure_ascii=False)}"
        
        data, messages = call_zai_chat(system_content, user_content, user_id, max_tokens=1500, disable_thinking=True, reference_image=project_data.get('mainImageData'))
        
        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM failed: " + json.dumps(data, ensure_ascii=False))
            
        cache_analytics = compute_cache_analytics(data, 'titles_' + str(int(time.time())))
        result_text = data["choices"][0]["message"]["content"].strip()
        write_systemprombet_backup(messages, result_text)
        
        match = re.search(r'\{[\s\S]*\}', result_text)
        if not match:
            raise Exception("No JSON in response")
            
        result = json.loads(match.group(0))
        content_titles = result.get("titles") or result.get("slides") or []
        
        if len(content_titles) > content_count:
            content_titles = content_titles[:content_count]
        
        final_titles = [
            {"title": "غلاف المشروع", "requires_image": True, "type": "cover"},
            {"title": "الفهرس", "requires_image": False, "type": "toc"}
        ]
        for t in content_titles:
            if isinstance(t, dict):
                t["type"] = "content"
            else:
                t = {"title": t, "requires_image": False, "type": "content"}
            final_titles.append(t)
        final_titles.append({"title": "معاينة الهوية البصرية", "requires_image": True, "type": "moodboard"})
        final_titles.append({"title": "ختام العرض", "requires_image": False, "type": "closing"})
        
        print(f"  [OK] Got {len(final_titles)} titles (cover + toc + {len(content_titles)} content + moodboard + closing) in {time.time() - start_time:.1f}s | Cache: {cache_analytics['status']}")
        return jsonify({'success': True, 'titles': final_titles, 'totalSlides': len(final_titles), 'cache_analytics': cache_analytics})
    except Exception as e:
        print("  [FAIL] Titles error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-bullets', methods=['POST'])
def api_generate_bullets():
    project_data = truncate_project_data(request.json.get('projectData'), 4000)
    slides = request.json.get('slides') or []
    mock = request.json.get('mock')
    user_id = request.json.get('userId') or 'default_user'
    
    if mock:
        print(f"  [Mock Mode] Returning mock bullets for {len(slides)} slides")
        mock_results = []
        for s in slides:
            title = s.get('title', '')
            idx = s.get('index', 0)
            bullets = []
            if title == "مميزات الموقع":
                bullets = [
                    "موقع استراتيجي وحيوي لتسهيل الوصول والتنقل.",
                    "قريب من الشوارع الرئيسية ومحاور الحركة بجدة.",
                    "رابط الموقع الجغرافي للمشروع متوفر مباشرة عبر قوقل ماب."
                ]
                if project_data and project_data.get('googleMapsLink'):
                    bullets.append("رابط قوقل ماب: " + project_data['googleMapsLink'])
            elif title == "غلاف المشروع":
                bullets = [
                    "مشروع استثماري واعد.",
                    "تم الإعداد بواسطة منافع الاقتصادية."
                ]
            else:
                bullets = [
                    "نقطة تجريبية أولى توضح الأهمية التشغيلية للمشروع.",
                    "نقطة تجريبية ثانية تدعم نموذج العمل والعوائد الاستثمارية.",
                    "نقطة تجريبية ثالثة لتقييم المخاطر والمؤشرات المالية للموقع."
                ]
            mock_results.append({'index': idx, 'title': title, 'bullets': bullets})
        return jsonify({
            'success': True,
            'slides': mock_results,
            'cache_analytics': {'status': 'MOCKED', 'cached_tokens': 0, 'total_tokens': 0}
        })
        
    print(f"\n[Bullets] Generating bullets for {len(slides)} slides...")
    
    try:
        from concurrent.futures import ThreadPoolExecutor
        
        def generate_single_slide_bullets(slide):
            title = slide.get('title', '')
            idx = slide.get('index', 0)
            slide_type = slide.get('type', 'content')
            
            # Skip cover and closing — they use hardcoded templates
            if slide_type in ('cover', 'closing') or idx == 0 or idx == len(slides) - 1:
                return {'index': idx, 'title': title, 'bullets': [], 'usage': None, 'id': None}
            
            system_content = (
                'أنت خبير في العروض التقديمية الاستثمارية. أنشئ 3-5 نقاط مختصرة واحترافية لهذه الشريحة. '
                'إذا كانت الشريحة هي "مميزات الموقع" وكان هناك رابط قوقل ماب (googleMapsLink) في بيانات المشروع، '
                'أضف نقطة تحتوي على رابط قوقل ماب المعطى بوضوح.\n\n'
                'أعد النتيجة كـ JSON فقط:\n'
                '{"bullets": ["نقطة 1", "نقطة 2", "نقطة 3"]}'
            )
            user_content = f"بيانات المشروع:\n{json.dumps(project_data or {}, indent=2, ensure_ascii=False)}\n\nعنوان الشريحة: {title}"
            
            try:
                d, messages = call_zai_chat(system_content, user_content, user_id, max_tokens=1000, disable_thinking=True, reference_image=project_data.get('mainImageData'))
                m = d["choices"][0]["message"] if ("choices" in d and len(d["choices"]) > 0) else {}
                text = m.get("content", "").strip()
                match = re.search(r'\{[\s\S]*\}', text)
                bullets = []
                if match:
                    bullets = json.loads(match.group(0)).get("bullets") or []
                return {'index': idx, 'title': title, 'bullets': bullets, 'usage': d.get('usage'), 'id': d.get('id')}
            except Exception as err:
                print(f"  [FAIL] Bullet error {idx}:", str(err))
                return {'index': idx, 'title': title, 'bullets': [], 'usage': None, 'id': None}
                
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(generate_single_slide_bullets, slides))
            
        results.sort(key=lambda x: x['index'])
        
        # Consolidate caching analytics
        total_prompt_tokens = 0
        total_cached_tokens = 0
        total_completion_tokens = 0
        total_tokens_count = 0
        session_ids = []
        
        for r in results:
            usage = r.get('usage')
            if usage:
                total_prompt_tokens += usage.get('prompt_tokens') or 0
                total_completion_tokens += usage.get('completion_tokens') or 0
                total_tokens_count += usage.get('total_tokens') or 0
                
                cached = 0
                if 'cached_tokens' in usage:
                    cached = usage['cached_tokens']
                elif 'prompt_tokens_details' in usage and isinstance(usage['prompt_tokens_details'], dict):
                    cached = usage['prompt_tokens_details'].get('cached_tokens') or 0
                total_cached_tokens += cached
                
            if r.get('id'):
                session_ids.append(r['id'])
            r.pop('usage', None)
            r.pop('id', None)
            
        saving_percentage = 0.0
        if total_prompt_tokens > 0:
            saving_percentage = round((total_cached_tokens / total_prompt_tokens) * 100, 1)
            
        cache_analytics = {
            "status": "HIT" if total_cached_tokens > 0 else "MISS",
            "cached_tokens": total_cached_tokens,
            "session_id": session_ids[0] if session_ids else 'bullets_' + str(int(time.time())),
            "saving_percentage": saving_percentage,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens_count
        }
        
        print(f"  [OK] Got bullets for {len(results)} slides | Cache: {cache_analytics['status']} ({cache_analytics['cached_tokens']} tokens)")
        return jsonify({'success': True, 'slides': results, 'cache_analytics': cache_analytics})
    except Exception as e:
        print("  [FAIL] Bullets error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-content', methods=['POST'])
def api_generate_content():
    project_data = truncate_project_data(request.json.get('projectData'), 4000)
    outline = request.json.get('outline')
    mock = request.json.get('mock')
    user_id = request.json.get('userId') or 'default_user'
    
    if outline:
        outline = [
            {
                'title': s.get('title') or '',
                'bullets': s.get('bullets')[:4] if isinstance(s.get('bullets'), list) else (s.get('bullets') or ''),
                'content': s.get('content')[:500] if isinstance(s.get('content'), str) else s.get('content')
            }
            for s in outline
        ]
        
    if mock:
        print("  [Mock Mode] Returning mock HTML content for slides")
        mock_slides = []
        for idx, s in enumerate(outline):
            title = s.get('title', '')
            bullets = s.get('bullets') or []
            html = f'<div class="ge-slide-title">{title}</div>'
            html += f'<div class="ge-slide-subtitle">تفاصيل وبنية الشريحة الاستثمارية {idx + 1}</div>'
            
            if title == "مميزات الموقع" and project_data and project_data.get('googleMapsLink'):
                html += '<div class="ge-slide-body"><ul>'
                for b in bullets:
                    html += f'<li>{b}</li>'
                html += '</ul>'
                html += f'<div style="margin-top: 15px;">'
                html += f'<a href="{project_data["googleMapsLink"]}" target="_blank" class="ge-maps-btn" style="display:inline-block; padding:10px 20px; background:#7A0C0C; color:#fff; text-decoration:none; border-radius:8px; font-weight:bold;">📍 فتح موقع المشروع على Google Maps</a>'
                html += '</div></div>'
            else:
                html += '<div class="ge-slide-body"><ul>'
                if bullets:
                    for b in bullets:
                        html += f'<li>{b}</li>'
                else:
                    html += '<li>نقطة استثمارية أولى توضح الرؤية والأهداف.</li>'
                    html += '<li>نقطة استثمارية ثانية لتحليل المؤشرات والعوائد.</li>'
                    html += '<li>نقطة استثمارية ثالثة لتقييم فرص النمو المتاحة.</li>'
                html += '</ul></div>'
            mock_slides.append({'title': title, 'content': html})
        return jsonify({
            'success': True,
            'slides': mock_slides,
            'cache_analytics': {'status': 'MOCKED', 'cached_tokens': 0, 'total_tokens': 0}
        })
        
    print("\n[Content] Generating full slide content via GLM 5.1...")
    
    try:
        system_content = (
            'أنت كاتب محتوى احترافي للعروض التقديمية الاستثمارية. مهمتك كتابة محتوى كامل ومفصل لكل شريحة في العرض التقديمي. '
            'إذا كانت الشريحة هي مميزات الموقع وتم توفير رابط قوقل ماب googleMapsLink في بيانات المشروع، قم بإنشاء زر أو رابط تشعبي HTML واضح '
            '(باستخدام <a href="..." target="_blank">) لعرض موقع المشروع على قوقل ماب.\n\n'
            'أعد النتيجة كـ JSON فقط بدون أي نص إضافي بالشكل:\n'
            '{\n'
            '  "slides": [\n'
            '    {\n'
            '      "title": "عنوان الشريحة",\n'
            '      "content": "<div class=\\"ge-slide-title\\">العنوان</div><div class=\\"ge-slide-subtitle\\">العنوان الفرعي</div><div class=\\"ge-slide-body\\"><ul><li>نقطة 1</li><li>نقطة 2</li></ul></div>"\n'
            '    }\n'
            '  ]\n'
            '}\n\n'
            'كل شريحة يجب أن تحتوي على:\n'
            '- title: العنوان الرئيسي المختصر\n'
            '- content: HTML markup بتنسيق احترافي يستخدم CSS classes: ge-slide-title, ge-slide-subtitle, ge-slide-body, ge-slide-metrics, ge-metric, ge-metric-label, ge-metric-value\n\n'
            'اكتب محتوى عربي احترافي ومفصل. استخدم الأرقام والبيانات المالية من بيانات المشروع.\n'
            '7. عدد الشرائح في المصفوفة يجب أن يساوي بالضبط عدد شرائح الـ Outline المُرسل — لا تضف شرائح إضافية ولا تحذف أي شريحة.'
        )
        user_content = (
            f"بيانات المشروع:\n{json.dumps(project_data or {}, indent=2, ensure_ascii=False)}\n\n"
            f"هيكل العرض (Outline) — {len(outline or [])} شريحة بالضبط:\n{json.dumps(outline or [], indent=2, ensure_ascii=False)}\n\n"
            f"مهم: أعد بالضبط {len(outline or [])} شريحة في مصفوفة slides — لا أكثر ولا أقل."
        )
        
        data, messages = call_zai_chat(system_content, user_content, user_id, max_tokens=6000, reference_image=project_data.get('mainImageData'))
        
        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM failed: " + json.dumps(data, ensure_ascii=False))
            
        cache_analytics = compute_cache_analytics(data, 'content_' + str(int(time.time())))
        result_text = data["choices"][0]["message"]["content"].strip()
        write_systemprombet_backup(messages, result_text)
        
        match = re.search(r'\{[\s\S]*\}', result_text)
        if match:
            json_str = match.group(0)
            slides = []
            try:
                result = json.loads(json_str)
                slides = result.get("slides") or []
            except Exception:
                print("  [WARN] JSON parse failed, attempting auto-repair in python...")
                slide_matches = re.findall(r'\{[^{}]*"title"[^{}]*"content"[^{}]*\}', json_str)
                for sm in slide_matches:
                    try:
                        slides.append(json.loads(sm))
                    except Exception:
                        pass
                        
            if slides:
                expected = len(outline) if outline else 14
                if len(slides) > expected:
                    print(f"  [FIX] Trimmed content slides from {len(slides)} to {expected}")
                    slides = slides[:expected]
                elif len(slides) < expected and outline:
                    for i in range(len(slides), expected):
                        o = outline[i]
                        slides.append({
                            'title': o.get('title', f'شريحة {i+1}'),
                            'content': f'<div class="ge-slide-title">{o.get("title", "")}</div><div class="ge-slide-body"><ul>' +
                                       ''.join(f'<li>{b}</li>' for b in (o.get('bullets') or [])) + '</ul></div>'
                        })
                print(f"  [OK] Content generated for {len(slides)} slides | Cache: {cache_analytics['status']}")
                return jsonify({'success': True, 'slides': slides, 'cache_analytics': cache_analytics})
            else:
                raise Exception("No JSON in GLM response")
        else:
            raise Exception("No JSON in GLM response")
    except Exception as e:
        print("  [FAIL] Content generation error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/organize-text', methods=['POST'])
def api_organize_text():
    project_data = truncate_project_data(request.json.get('projectData'), 4000)
    raw_text = request.json.get('rawText')
    if raw_text and len(raw_text) > 3000:
        raw_text = raw_text[:3000] + '\n... [تم اختصار النص]'
    outline = request.json.get('outline')
    user_id = request.json.get('userId') or 'default_user'
    
    print("\n[Organize] Organizing text across slides via GLM 5.1...")
    
    try:
        system_content = (
            'أنت خبير في تنظيم المحتوى للعروض التقديمية. مهمتك تنظيم نص خام على شرائح العرض التقديمي حسب المحتوى المناسب لكل شريحة.\n\n'
            'أعد النتيجة كـ JSON فقط بدون أي نص إضافي بالشكل:\n'
            '{\n'
            '  "slides": [\n'
            '    {\n'
            '      "title": "عنوان الشريحة",\n'
            '      "bullets": ["نقطة 1 من النص", "نقطة 2 من النص"],\n'
            '      "requires_image": true أو false (حدد true لـ 5 شرائح بصرية كحد أقصى كالغلاف وصور الموقع ومميزات المشروع ومكوناته، والباقي false),\n'
            '      "missingInfo": "معلومات إضافية مطلوبة إن وُجدت"\n'
            '    }\n'
            '  ]\n'
            '}\n\n'
            'قواعد التنظيم:\n'
            '1. وزع محتوى النص على الشرائح المناسبة حسب الهيكل المحدد\n'
            '2. إذا كانت معلومات شريحة معينة غير مكتملة أو ناقصة، اذكرها في missingInfo\n'
            '3. احتفظ بالعناوين الأصلية للشرائح\n'
            '4. اجعل النقاط مختصرة ومنظمة\n'
            '5. لا تختلق معلومات - استخدم فقط ما يوجد في النص المكتوب\n'
            '6. إذا كان النص خالياً أو قصيراً جداً، اذكر ذلك في missingInfo'
        )
        user_content = (
            f"بيانات المشروع:\n{json.dumps(project_data or {}, indent=2, ensure_ascii=False)}\n\n"
            f"هيكل العرض:\n{json.dumps(outline or [], indent=2, ensure_ascii=False)}\n\n"
            f"النص المكتوب يدوياً:\n{raw_text or 'لا يوجد نص'}"
        )
        
        data, messages = call_zai_chat(system_content, user_content, user_id, max_tokens=3000)
        
        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM failed: " + json.dumps(data, ensure_ascii=False))
            
        cache_analytics = compute_cache_analytics(data, 'organize_' + str(int(time.time())))
        result_text = data["choices"][0]["message"]["content"].strip()
        write_systemprombet_backup(messages, result_text)
        
        match = re.search(r'\{[\s\S]*\}', result_text)
        if match:
            result = json.loads(match.group(0))
            slides = result.get("slides") or []
            print(f"  [OK] Text organized across {len(slides)} slides | Cache: {cache_analytics['status']}")
            return jsonify({'success': True, 'slides': slides, 'cache_analytics': cache_analytics})
        else:
            raise Exception("No JSON in GLM response")
    except Exception as e:
        print("  [FAIL] Organize text error:", str(e))
        return jsonify({'error': str(e)}), 500

DESIGN_SYSTEM_PROMPT_BASE = """You are a world-class luxury real estate investment presentation designer for "منافع الاقتصادية للعقار" (Manafe Economic Co. for Real Estate).

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
Font: 'The Sans Arabic', Arial, sans-serif — DO NOT use Cairo or any font not listed here.
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
15. CRITICAL: Content must fit within slide boundaries. NEVER let text overflow. Use overflow:hidden on the container div. If content is long, reduce font size or use ellipsis — but NEVER exceed the slide area.
16. CRITICAL: Use 'The Sans Arabic', Arial as fonts.
17. CRITICAL: PRESERVE THE EXACT TEXT from the outline. Do NOT paraphrase, abbreviate, or modify the user's content. If the outline says "صافي الربح التشغيلي بلغ 15 مليون ريال سعودي" — write EXACTLY that, not a shorter version. The user's words are sacred.

═════════════════════════════════════════════════════════════════
IMAGE PLACEHOLDERS (CRITICAL)
═════════════════════════════════════════════════════════════════
You MUST use these exact placeholder strings as the `src` attribute for images:
- "##MOODBOARD_IMAGE_1##": Use for first slide (cover/opening) and last slide (closing) background image.
- "##MOODBOARD_IMAGE_2##": Use for a location/map related slide image card.
- "##MOODBOARD_IMAGE_3##": Use for a features/advantages slide image card.
- "##MOODBOARD_IMAGE_4##": Use for a components/table slide image card.
Always style images with object-fit: cover, width: 100%, and height: 100% inside their respective styled containers.
If a slide type doesn't exist in the outline, skip its image placeholder.

═════════════════════════════════════════════════════════════════
HEADER & FOOTER (ALL SLIDES)
═════════════════════════════════════════════════════════════════
HEADER: Logo top-right (proper aspect ratio, no distortion) + slide title in small font + thin burgundy line
FOOTER: Project name + "منافع الاقتصادية للعقار" + page number in burgundy circle/rectangle. Footer must be unified across all slides and never overlap content.

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
- font-family: 'The Sans Arabic', Arial, sans-serif
- position: relative
- background: white
- box-sizing: border-box
- word-wrap: break-word (to prevent text overflow)

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
- Generate EXACTLY the number of slides listed below
- All financial data must match the project data provided
- Numbers formatted with commas (e.g., 1,500,000)
- Arabic text only for all labels and content
- Return ONLY valid JSON, no explanations, no markdown code blocks"""


def build_design_prompt(outline):
    """Build dynamic DESIGN_SYSTEM_PROMPT based on actual outline titles."""
    slide_count = len(outline)
    
    # Build dynamic slide descriptions from outline
    slide_descriptions = []
    for i, slide in enumerate(outline):
        title = slide.get('title', f'شريحة {i+1}')
        bullets = slide.get('bullets', [])
        bullets_text = '\n'.join([f'  - {b}' for b in bullets]) if bullets else '  (no specific bullets)'
        
        # Determine slide type hint based on title keywords
        hint = ''
        title_lower = title.lower() if title else ''
        if any(k in title_lower for k in ['غلاف', 'cover', 'افتتاح']):
            hint = 'Design as a COVER/OPENING slide: Full-bleed background image using <img src="##MOODBOARD_IMAGE_1##" style="width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;z-index:-1;">, semi-transparent burgundy overlay, logo CENTERED and LARGE, project name centered. Simple and luxurious.'
        elif any(k in title_lower for k in ['ختام', 'شكرا', 'closing', 'نهاية']):
            hint = 'Design as a CLOSING slide: Burgundy luxury background or project image with transparent overlay using <img src="##MOODBOARD_IMAGE_1##" style="width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;z-index:-1;">. "شكراً لكم" in large font centered. Contact info at bottom.'
        elif any(k in title_lower for k in ['ملخص', 'executive', 'summary']):
            hint = 'Design as an Executive Summary dashboard: 6 large KPI cards (2x3 grid) with financial metrics. Each card with icon and prominent numbers.'
        elif any(k in title_lower for k in ['موقع', 'location', 'مواقع']):
            hint = 'Design with feature cards and SVG icons. Include image card using <img src="##MOODBOARD_IMAGE_2##" style="width:100%;height:100%;object-fit:cover;border-radius:8px;">. Make Google Maps button prominent.'
        elif any(k in title_lower for k in ['مزايا', 'مميزات', 'advantages', 'strengths', 'فرص']):
            hint = 'Design as marketing cards grid. Include image card using <img src="##MOODBOARD_IMAGE_3##" style="width:100%;height:100%;object-fit:cover;border-radius:8px;">. Each card: icon + title + description.'
        elif any(k in title_lower for k in ['مكونات', 'components', 'مساحات', 'جدول']):
            hint = 'Design with professional table (burgundy header, alternating rows). Include image card using <img src="##MOODBOARD_IMAGE_4##" style="width:100%;height:100%;object-fit:cover;border-radius:8px;">.'
        elif any(k in title_lower for k in ['تكاليف', 'cost', 'تكلفة']):
            hint = 'Design as cost comparison: large cards for each cost item, total cost most prominent at center/bottom.'
        elif any(k in title_lower for k in ['أرباح', 'profit', 'operating', 'تشغيل']):
            hint = 'Design as visual equation flow: Revenue - Expense = Profit. Each number in clear financial card. Make profit the largest element.'
        elif any(k in title_lower for k in ['خروج', 'exit', 'رسملة']):
            hint = 'Design as investment value flow: equation with arrows. Make exit value and total profit most prominent.'
        elif any(k in title_lower for k in ['مؤشر', 'indicator', 'financial', 'عائد', 'noi']):
            hint = 'Design as Financial Dashboard: ROI, NOI, Payback in large upper cards. Total cost vs profit comparison below.'
        elif any(k in title_lower for k in ['جدول', 'timeline', 'مراحل', 'timeline']):
            hint = 'Design as Gantt-style timeline. Years and quarters at top. Each phase as horizontal bar. Use calm colors.'
        elif any(k in title_lower for k in ['مخاطر', 'risks', 'افتراضات']):
            hint = 'Design as ordered risk cards. NOT negative or scary. Gray and beige with burgundy touch. Warning icons.'
        elif any(k in title_lower for k in ['فكرة', 'concept', 'هيكل']):
            hint = 'Design as information board: split into cards for each topic. Each card with appropriate icon.'
        
        slide_descriptions.append(
            f"SLIDE {i+1} — {title}:\n"
            f"EXACT CONTENT (use these EXACT words, do NOT paraphrase or abbreviate):\n{bullets_text}\n"
            f"{('Design guidance: ' + hint) if hint else 'Design this slide professionally based on its content. Use card-based layouts, SVG icons, and the brand color palette.'}"
        )
    
    slide_section = '\n\n'.join(slide_descriptions)
    
    return (
        DESIGN_SYSTEM_PROMPT_BASE +
        f'\n\n═════════════════════════════════════════════════════════════════\n'
        f'SLIDE TYPES ({slide_count} SLIDES — follow this EXACT order)\n'
        f'═════════════════════════════════════════════════════════════════\n\n'
        f'{slide_section}\n\n'
        f'═════════════════════════════════════════════════════════════════\n'
        f'IMPORTANT: Design EXACTLY {slide_count} slides in the EXACT order listed above.\n'
        f'Do NOT add slides that are not in the list. Do NOT skip any slides.\n'
        f'The slide titles above are the EXACT titles to use — do not rename them.\n'
        f'CRITICAL: The "EXACT CONTENT" listed for each slide is the user\'s original text.\n'
        f'You MUST use these EXACT words in your design. Do NOT abbreviate, paraphrase, or shorten them.\n'
        f'If the content says "إجمالي التكلفة بلغ 74,581,195 ريال سعودي" — write EXACTLY that number and those words.\n'
        f'If content is too long for the slide, reduce font size — but NEVER remove or change the text.\n'
        f'═════════════════════════════════════════════════════════════════'
    )


@app.route('/api/generate-design', methods=['POST'])
def api_generate_design():
    project_data = truncate_project_data(request.json.get('projectData'), 3000)
    outline = request.json.get('outline') or []
    user_id = request.json.get('userId') or 'default_user'
    user_instructions = request.json.get('instructions') or ''

    if not project_data:
        return jsonify({'error': 'Project data is required'}), 400

    print("\n[Design] Generating HTML slide design via GLM 5.1...")
    print(f"  Slides: {len(outline)}")

    try:
        slide_list = '\n'.join([
            f"{i+1}. {s.get('title', '')}" + (('\n   ' + '\n   '.join(s.get('bullets', []))) if s.get('bullets') else '')
            for i, s in enumerate(outline)
        ])

        image_info = ''
        if project_data and project_data.get('mainImageData'):
            image_info = f"\n\nMAIN COVER IMAGE URL: {project_data['mainImageData'][:100]}... (full data URI provided)"

        user_message = 'PROJECT DATA:\n' + json.dumps({
            'projectName': project_data.get('projectName'),
            'projectType': project_data.get('projectType'),
            'city': project_data.get('city'),
            'location': project_data.get('location'),
            'idea': project_data.get('idea'),
            'structure': project_data.get('structure'),
            'developer': project_data.get('developer'),
            'components': project_data.get('components'),
            'landArea': project_data.get('landArea'),
            'buildingRatio': project_data.get('buildingRatio'),
            'areaNote': project_data.get('areaNote'),
            'avgRent': project_data.get('avgRent'),
            'serviceFees': project_data.get('serviceFees'),
            'annualRevenue': project_data.get('annualRevenue'),
            'annualOpex': project_data.get('annualOpex'),
            'landCost': project_data.get('landCost'),
            'developmentCost': project_data.get('developmentCost'),
            'totalOperatingProfit': project_data.get('totalOperatingProfit'),
            'exitValue': project_data.get('exitValue'),
            'capRate': project_data.get('capRate'),
            'annualROI': project_data.get('annualROI'),
            'noiRate': project_data.get('noiRate'),
            'payback': project_data.get('payback'),
            'timelineRows': project_data.get('timelineRows'),
            'risks': project_data.get('risks'),
            'recommendation': project_data.get('recommendation'),
            'preparedBy': project_data.get('preparedBy'),
            'contactInfo': project_data.get('contactInfo'),
            'googleMapsLink': project_data.get('googleMapsLink'),
            'locationFeatures': project_data.get('locationFeatures'),
            'projectFeatures': project_data.get('projectFeatures'),
            'investmentHighlights': project_data.get('investmentHighlights')
        }, indent=2, ensure_ascii=False)

        user_message += '\n\nSLIDE TO DESIGN:\n' + slide_list
        if image_info:
            user_message += image_info
        if user_instructions:
            user_message += f'\n\nADDITIONAL DESIGN INSTRUCTIONS:\n{user_instructions}'
        user_message += (
            '\n\nIMPORTANT: You must generate BOTH the content AND the design together. '
            'Do NOT just return a design shell — write the actual Arabic content (text, bullets, numbers, descriptions) inside the slide. '
            'Use the project data above to fill in real numbers, names, and details. '
            'CRITICAL: Use the EXACT text from the "SLIDE TO DESIGN" section. Do NOT paraphrase, abbreviate, or shorten the content. '
            'If the text is long, reduce font size to fit — but NEVER change the words. '
            'Return ONLY the JSON object with "slides" array containing ONE slide with "title" and "html" keys. '
            'The html must be a COMPLETE, self-contained slide with ALL inline CSS, real Arabic content, and a stunning visual design — rich backgrounds, gradients, decorative elements, professional typography. '
            'Do NOT use plain white backgrounds. Each slide must feel like a premium investment presentation slide. '
            'Content MUST fit within the slide boundaries. Use overflow:hidden. If text is too long, reduce font size — NEVER let text overflow outside the slide.'
        )

        # GLM/ZAI only supports text content - no image_url type
        user_message_content = user_message
        main_image = project_data.get('mainImageData') if project_data else None
        if main_image:
            print("  Image available but GLM only supports text - skipping image")

        dynamic_prompt = build_design_prompt(outline)
        data, messages = call_zai_chat(dynamic_prompt, user_message_content, user_id, max_tokens=16000)

        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM failed: " + json.dumps(data, ensure_ascii=False))

        cache_analytics = compute_cache_analytics(data, 'design_' + str(int(time.time())))
        result_text = data["choices"][0]["message"]["content"].strip()
        write_systemprombet_backup(messages, result_text)

        if data.get('usage'):
            u = data['usage']
            print(f"  Tokens: {u.get('total_tokens', 0)} | Cache: {cache_analytics['status']}")

        match = re.search(r'\{[\s\S]*\}', result_text)
        if not match:
            raise Exception("No JSON in GLM response")

        result = None
        try:
            result = json.loads(match.group(0))
        except json.JSONDecodeError:
            slides_match = re.search(r'"slides"\s*:\s*\[[\s\S]*\]', match.group(0))
            if slides_match:
                try:
                    result = json.loads('{' + slides_match.group(0) + '}')
                except json.JSONDecodeError:
                    raise Exception("Could not parse GLM design response")
            else:
                raise Exception("No slides array in GLM response")

        slides = result.get("slides", [])
        if outline and len(slides) > len(outline):
            print(f"  [FIX] Trimmed design slides from {len(slides)} to {len(outline)}")
            slides = slides[:len(outline)]
        print(f"  [OK] Generated design for {len(slides)} slides")
        return jsonify({'success': True, 'slides': slides, 'cache_analytics': cache_analytics})

    except Exception as e:
        print(f"  [FAIL] Design generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/official-outline', methods=['POST'])
def api_official_outline():
    """GLM generates the outline (titles + bullets) based on project data — 16 slides."""
    total_slides = 16
    project_data = request.json.get('projectData', {})

    print(f"\n[Official Outline] Asking GLM to generate outline for project: {project_data.get('projectName', 'Unknown')}...")

    outline_prompt = """أنت كاتب عروض استثمارية عقارية فاخرة. مهمتك كتابة هيكل (outline) عرض PowerPoint استثماري عقاري.

المطلوب: بالضبط 16 شريحة بالترتيب التالي:
1. شريحة غلاف (type="cover")
2. شريحة الفهرس (type="index") — جدول محتويات العرض
3-14. 12 شريحة محتوى (type="content") تغطي تفاصيل المشروع بطريقة مخصصة
15. شريحة المود بورد (type="mood_board") — تعرض الهوية البصرية للمشروع
16. شريحة الختام (type="closing") — "شكراً لكم" مع بيانات التواصل

لكل شريحة محتوى:
- عنوان واضح ومختصر (عربي)
- 3-5 نقاط (bullets) مختصرة تعكس بيانات المشروع الحقيقية

تعليمات مهمة:
- استخدم البيانات المالية والمعلومات الحقيقية من مشروع المستخدم في النقاط
- العناوين يجب أن تكون احترافية ومناسبة لعرض استثماري
- لا تكرر العناوين — كل شريحة لها موضوع مختلف
- لا تكتب نقاط عامة — كن محدداً حسب بيانات المشروع
- الغلاف والختام بدون نقاط
- الفهرس يحتوي على عناوين الشرائح فقط (بدون نقاط)
- يجب أن يكون ترتيب الشرائح النهائي كالتالي بالضبط: غلاف، فهرس، 12 شريحة محتوى، مود بورد، ختام.
- لا تضف شريحة "فريق العمل والتواصل" أو "بيانات التواصل" منفصلة؛ بيانات التواصل تظهر فقط في شريحة الختام.
- لا تضع عنوان مشروع كشريحة محتوى منفصلة في نهاية العرض.
- ابقَ على 16 شريحة بالضبط — لا تزيد ولا تنقص.

Return ONLY valid JSON: {"titles": [{"title": "عنوان الشريحة", "bullets": ["نقطة 1", "نقطة 2"], "type": "content"}]}

أنواع الشرائح: "cover" (أول شريحة فقط)، "index" (ثاني شريحة فقط)، "content" (شرائح 3-14)، "mood_board" (الشريحة 15 فقط)، "closing" (الشريحة 16 فقط).
الشريحة الأولى type="cover" والثانية type="index" والقبل الأخيرة type="mood_board" والأخيرة type="closing" وباقي الشرائح الوسطى type="content"."""

    user_msg = f"بيانات المشروع:\n{json.dumps(project_data, ensure_ascii=False, indent=2)}\n\nاكتب الهيكل المكون من بالضبط 16 شريحة."

    try:
        data, messages = call_zai_chat(outline_prompt, user_msg, 'default_user', max_tokens=4000)

        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM returned no choices")

        raw = data["choices"][0].get("message", {}).get("content", "")
        print(f"  [GLM Outline] Raw response length: {len(raw)} chars")

        # Extract JSON
        import re
        json_match = re.search(r'\{[\s\S]*"titles"[\s\S]*\}', raw)
        if not json_match:
            raise Exception("No JSON found in GLM response")

        parsed = json.loads(json_match.group())
        titles = parsed.get('titles', [])

        if not titles or len(titles) < 10:
            raise Exception(f"GLM returned only {len(titles)} slides, need 16")

        # Ensure first and last slides never exceed 16
        total_slides = 16
        titles = titles[:total_slides]

        # Remove any mood_board slides that GLM snuck in; we will re-add at index 14
        titles = [t for t in titles if t.get('type') != 'mood_board']
        # Re-truncate if removal reduced count below 16
        titles = titles[:total_slides]

        # Force correct types
        if titles[0].get('type') != 'cover':
            titles[0]['type'] = 'cover'
            titles[0]['requires_image'] = True
        for i in range(1, len(titles) - 1):
            titles[i]['type'] = 'content'
        if titles[-1].get('type') != 'closing':
            titles[-1]['type'] = 'closing'

        # Strip unwanted titles that look like contact/team or duplicated project title
        forbidden_in_content = [
            'فريق العمل والتواصل',
            'فريق العمل',
            'بيانات التواصل',
            'معلومات التواصل',
            'أبراج الواحة السكنية التجارية الفاخرة',
        ]
        for t in titles:
            title_text = t.get('title', '')
            title_lower = title_text.lower()
            if t.get('type') == 'content' and any(f.lower() in title_lower for f in forbidden_in_content):
                t['type'] = 'skip'
        titles = [t for t in titles if t.get('type') != 'skip']

        # Extract special slides if present, else create defaults
        cover_slide = None
        for t in titles:
            if t.get('type') == 'cover' or any(w in t.get('title', '').lower() for w in ['غلاف', 'cover']):
                cover_slide = t
                break
        if not cover_slide:
            cover_slide = {'title': 'غلاف المشروع', 'requires_image': True, 'type': 'cover', 'bullets': []}

        index_slide = None
        for t in titles:
            if t.get('type') == 'index' or any(w in t.get('title', '').lower() for w in ['فهرس', 'أجندة', 'index', 'toc']):
                index_slide = t
                break
        if not index_slide:
            index_slide = {'title': 'فهرس المحتويات', 'requires_image': False, 'type': 'index', 'bullets': []}

        closing_slide = None
        for t in titles:
            if t.get('type') == 'closing' or any(w in t.get('title', '').lower() for w in ['ختام', 'شكر', 'closing', 'thanks']):
                closing_slide = t
                break
        if not closing_slide:
            closing_slide = {'title': 'الختام', 'requires_image': False, 'type': 'closing', 'bullets': []}
        # Always force the last slide to be the real closing, replacing any trailing duplicated project-title slide
        closing_slide = {'title': 'الختام', 'requires_image': False, 'type': 'closing', 'bullets': []}

        # Collect all remaining slides as content slides
        content_slides = []
        for t in titles:
            # Skip if it matches one of the extracted special slides by reference or title keywords
            if t is cover_slide or t is index_slide or t is closing_slide:
                continue
            if t.get('type') in ('cover', 'index', 'closing'):
                continue
            title_lower = t.get('title', '').lower()
            if any(w in title_lower for w in ['غلاف', 'cover', 'فهرس', 'أجندة', 'index', 'toc', 'ختام', 'شكر', 'closing', 'thanks', 'فريق العمل', 'بيانات التواصل']):
                continue
            t['type'] = 'content'
            content_slides.append(t)

        # Enforce exactly 12 content slides so total becomes 16
        target_content_count = total_slides - 4  # 16 - 4 = 12
        if len(content_slides) < target_content_count:
            fallback_needed = target_content_count - len(content_slides)
            fallback_titles = build_adaptive_content_fallback(project_data, fallback_needed)
            for ft in fallback_titles:
                ft['type'] = 'content'
                content_slides.append(ft)
        elif len(content_slides) > target_content_count:
            content_slides = content_slides[:target_content_count]

        # Re-assemble the 16 slides in the correct structure
        titles = [
            cover_slide,
            index_slide
        ] + content_slides + [
            {'title': 'المود بورد', 'requires_image': True, 'type': 'mood_board', 'bullets': []},
            closing_slide
        ]

        # Force correct types and properties on all slides
        titles[0]['type'] = 'cover'
        titles[0]['requires_image'] = True
        titles[1]['type'] = 'index'
        titles[1]['requires_image'] = False
        titles[-2]['type'] = 'mood_board'
        titles[-2]['requires_image'] = True
        titles[-1]['type'] = 'closing'
        titles[-1]['requires_image'] = False
        for i in range(2, len(titles) - 2):
            titles[i]['type'] = 'content'

        print(f"  [OK] GLM generated {len(titles)} slides: {[t['title'] for t in titles]}")

        return jsonify({
            'success': True,
            'titles': titles,
            'totalSlides': total_slides,
            'cache_analytics': {'status': 'GLM_GENERATED', 'cached_tokens': 0, 'total_tokens': len(raw)}
        })
    except Exception as e:
        print(f"  [ERROR] GLM outline generation failed: {e}")
        # Fallback to hardcoded outline
        print("  [FALLBACK] Using hardcoded outline")
        official_titles = [
            {'title': 'غلاف المشروع', 'requires_image': True, 'type': 'cover', 'bullets': []},
            {'title': 'الفهرس', 'type': 'toc', 'bullets': []},
            {'title': 'الملخص التنفيذي', 'type': 'content', 'bullets': [
                'نظرة عامة على المشروع والأهداف الرئيسية',
                'إجمالي التكلفة والعائد المتوقع',
                'التوصية النهائية للمستثمرين'
            ]},
            {'title': 'فكرة المشروع والهيكلة', 'type': 'content', 'bullets': [
                'تعريف المشروع ورسالته',
                'هيكلة المشروع والunits المختلفة',
                'الجهة المطورة والخبرات'
            ]},
            {'title': 'مميزات الموقع', 'requires_image': True, 'type': 'content', 'bullets': [
                'الموقع الجغرافي والاستراتيجي',
                'البنية التحتية المحيطة',
                'سهولة الوصول والمواصلات'
            ]},
            {'title': 'مميزات المشروع', 'requires_image': True, 'type': 'content', 'bullets': [
                'التصميم المعماري والعصري',
                'المرافق والتجهيزات الفاخرة',
                'نظام الأمان والتشغيل الذكي'
            ]},
            {'title': 'مكونات المشروع والمساحات', 'type': 'content', 'bullets': [
                'تفصيل الوحدات السكنية والتجارية',
                'المساحات المبنية والتأجيرية',
                'أسعار الإيجار المقدرة'
            ]},
            {'title': 'افتراضات الربح التشغيلي التأجيري', 'type': 'content', 'bullets': [
                'متوسط إيجار المتر ورسوم الخدمات',
                'الإيرادات السنوية المتوقعة',
                'المصروف التشغيلي السنوي'
            ]},
            {'title': 'افتراضات التكاليف', 'type': 'content', 'bullets': [
                'تكلفة الأرض والتطوير',
                'إجمالي التكلفة الاستثمارية',
                'هيكل التمويل المتوقع'
            ]},
            {'title': 'الأرباح والتخارج', 'type': 'content', 'bullets': [
                'الربح التشغيلي طوال فترة المشروع',
                'قيمة التخارج المتوقعة',
                'معامل الرسملة'
            ]},
            {'title': 'المؤشرات المالية المتوقعة', 'type': 'content', 'bullets': [
                'نسبة العائد السنوي على الاستثمار',
                'نسبة صافي الربح التشغيلي NOI',
                'فترة استرداد رأس المال'
            ]},
            {'title': 'الجدول الزمني ومراحل المشروع', 'type': 'content', 'bullets': [
                'مراحل التصميم والتصاريح',
                'مراحل البناء والتشطيبات',
                'موعد التسليم والتشغيل'
            ]},
            {'title': 'فرص الاستثمار ونقاط القوة', 'type': 'content', 'bullets': [
                'الطلب المتزايد في المنطقة',
                'العائد الإيجالي المرتفع',
                'فرصة ارتفاع القيمة'
            ]},
            {'title': 'المخاطر والافتراضات', 'type': 'content', 'bullets': [
                'مخاطر الترخيص والتأخير',
                'تقلبات أسعار البناء',
                'مخاطر السوق والمنافسة'
            ]},
            {'title': 'المود بورد', 'type': 'mood_board', 'requires_image': False, 'bullets': [
                'لوحة الألوان والهوية البصرية',
                'نمط التصميم المعماري',
                'الصور التوضيحية للمشروع'
            ]},
            {'title': 'الختام', 'type': 'closing', 'bullets': []}
        ]
        return jsonify({
            'success': True,
            'titles': official_titles,
            'totalSlides': total_slides,
            'cache_analytics': {'status': 'FALLBACK', 'cached_tokens': 0, 'total_tokens': 0}
        })


def detect_slide_type(title):
    """Detect slide type from title for design instruction lookup."""
    t = (title or '').lower()
    if any(k in t for k in ['غلاف', 'cover']):
        return 'cover'
    if any(k in t for k in ['فهرس', 'toc', 'جدول محتويات', 'محتويات']):
        return 'toc'
    if any(k in t for k in ['ختام', 'closing', 'توصية']):
        return 'closing'
    if any(k in t for k in ['مود بورد', 'mood board', 'لوحة الأفكار', 'لوحة الأنماط', 'معاينة الهوية', 'الهوية البصرية']):
        return 'moodboard'
    if any(k in t for k in ['ملخص تنفيذي', 'executive', 'summary', 'dashboard']):
        return 'dashboard'
    if any(k in t for k in ['فكرة', 'هيكل', 'مفهوم', 'concept', 'structure']):
        return 'info-cards'
    if any(k in t for k in ['مميزات الموقع', 'location', 'موقع', 'الموقع']):
        return 'feature-cards-location'
    if any(k in t for k in ['مميزات المشروع', 'مزايا', 'فرص الاستثمار', 'نقاط القوة']):
        return 'risks'  # slide 12 = opportunities
    if any(k in t for k in ['مكونات', 'مساحات', 'جدول.*مساحات', 'components', 'table']):
        return 'table'
    if any(k in t for k in ['ربح تشغيلي', 'ربح تأجيري', 'تشغيلي', 'equation', 'الافتراضات.*الربح']):
        return 'equation'
    if any(k in t for k in ['تكاليف', 'تكلفة', 'comparison', 'الافتراضات.*التكلفة']):
        return 'comparison'
    if any(k in t for k in ['أرباح', 'تخارج', 'exit', 'flow']):
        return 'flow'
    if any(k in t for k in ['مؤشرات مالية', 'مؤشر', 'roi', 'noi', 'payback', 'المؤشرات المالية']):
        return 'dashboard-finance'
    if any(k in t for k in ['جدول زمني', 'زمني', 'timeline', 'مراحل']):
        return 'timeline'
    if any(k in t for k in ['مخاطر', 'افتراضات', 'risk', 'المخاطر']):
        return 'risks-assumptions'
    return 'standard'


# Design variation styles for parallel workers — each gets a different aesthetic angle
DESIGN_VARIATIONS = [
    "",  # default — full prompt
    "DESIGN STYLE: Minimalist luxury. Clean white space, thin gold lines, elegant typography. No busy backgrounds — use subtle gradients.",
    "DESIGN STYLE: Bold modern. Strong geometric shapes, large typography, dramatic color blocks in burgundy and gold.",
    "DESIGN STYLE: Editorial magazine layout. Asymmetric grid, large hero numbers, sophisticated typography hierarchy.",
    "DESIGN STYLE: Corporate premium. Card-based dashboard layout, subtle shadows, data visualization feel with clean icons.",
    "DESIGN STYLE: Architectural. Blueprint-inspired subtle background patterns, structured grid, precise alignment, monochrome with gold accents.",
    "DESIGN STYLE: Warm luxury. Soft beige backgrounds, rounded cards, warm gold tones, inviting and premium feel.",
    "DESIGN STYLE: High contrast. Dark burgundy headers, white content areas, sharp edges, strong visual hierarchy.",
    "DESIGN STYLE: Flowing organic. Subtle curved shapes, soft gradients, gentle transitions between sections.",
    "DESIGN STYLE: Data-driven. Focus on large KPI numbers, minimal text, maximum visual impact for financial data.",
    "DESIGN STYLE: Classic elegance. Traditional investment brochure feel, serif-inspired styling, timeless layout.",
    "DESIGN STYLE: Futuristic premium. Thin lines, glass-morphism effects, subtle transparency, modern tech feel.",
]

# Condensed single-slide prompt — short base rules only
CONDENSED_DESIGN_PROMPT = """Luxury real estate presentation designer for "منافع الاقتصادية للعقار".
Brand: Burgundy #670D0C, Gold #C2A176, Beige #F5F0EE, White. Font: 'The Sans Arabic', Arial. RTL Arabic only.

SLIDE: EXACTLY 1280×720px. Outer div: dir="rtl" lang="ar" width:1280px; height:720px; overflow:hidden; position:relative; box-sizing:border-box; font-family:'The Sans Arabic',Arial,sans-serif. ALL content inside. dir="rtl" lang="ar" is MANDATORY for connected Arabic.

{variation}

DESIGN: Card-based, rounded corners (12-16px), shadows (0 4px 20px rgba(0,0,0,0.06)). Financial numbers LARGE (32-40px, bold, burgundy). Max 3 colors. Content between header (~70px) and footer (~50px). Use EXACT text from slide description. Subtle SVG patterns 5-8% opacity. Professional LINE icons.

IMAGES: ##MOODBOARD_IMAGE_1## → Cover only, ##MOODBOARD_IMAGE_2## → Location, ##MOODBOARD_IMAGE_3## → Features, ##MOODBOARD_IMAGE_4## → Components. Each once only. Image flex row — never overlap text.

Return ONLY valid JSON: {{"slides": [{{"title": "Slide title", "html": "<div>...</div>"}}]}}"""

# Per-slide design instructions — compact versions
SLIDE_DESIGN_INSTRUCTIONS = {
    'cover': "COVER: Full-bleed ##IMAGE_COVER## background, overlay gradient. Center logo big (200px), project name (48-56px white bold), gold line, subtitle. No header/footer. Luxury minimal.",

    'dashboard': "DASHBOARD: 6 KPI cards in 3×2 grid. Each: SVG icon, value (32-40px bold burgundy), label (12px gray). Total profit = biggest card with gold accent.",

    'info-cards': "INFO-CARDS: 5 cards grid — idea, location, structure, type, developer. Each with SVG icon. Google Maps button if link exists.",

    'feature-cards-location': "LOCATION FEATURES: Feature cards with LINE icons. Grid 2-3 columns. Google Maps button. Image flex if present.",

    'feature-cards': "PROJECT FEATURES: 4+ cards grid. LINE SVG icons, title (14px bold), description (12px). Real estate feel.",

    'table': "COMPONENTS TABLE: Professional table — burgundy header, alternating rows. Below: 3 info cards (land area, building ratio, note). Image flex if present.",

    'equation': "RENTAL EQUATION: Visual flow — Revenue − Expense = Profit. Each in large card (32-40px bold). Profit = biggest. Arrows between.",

    'comparison': "COST COMPARISON: Two cards side-by-side (land vs dev). Total cost = biggest gold card. Bar chart showing proportions.",

    'flow': "PROFITS & EXIT: Horizontal flow diagram — Operating Profit → Exit Value → Total. Arrows connecting cards. Total = most prominent.",

    'dashboard-finance': "FINANCIAL KPIs: Top row 3 KPIs (ROI, NOI, Payback). Bottom: cost vs profit comparison. Numbers very prominent.",

    'timeline': "TIMELINE: Years/Q1-Q3 at top. Phase bars by duration. Colors: burgundy, brown, beige, gray. Arabic labels.",

    'risks': "OPPORTUNITIES: Large cards with LINE icons. Marketing-focused, attractive. Growth elements in background.",

    'risks-assumptions': "RISKS: Ordered numbered cards (1,2,3). Warning triangle icons. Gray/beige/burgundy. Calm professional feel.",

    'closing': "CLOSING: Burgundy bg, image at 25% opacity. Center logo in white card, 'شكراً لكم' (52px white), gold line, project name. No header/footer.",

    'standard': "STANDARD: Card-based layout, LINE SVG icons, large financial numbers, subtle SVG patterns. Professional investment feel.",
}

# ═══════════════════════════════════════════════════════════════════
# BLUEPRINT SYSTEM — shared design identity for all slides
# ═══════════════════════════════════════════════════════════════════

BLUEPRINT_PROMPT = """Brand identity designer for "منافع الاقتصادية للعقار". Generate a design blueprint JSON for a luxury real estate presentation.

Return ONLY valid JSON:
{{
  "blueprint": {{
    "primary_color": "#670D0C",
    "secondary_color": "#C2A176",
    "background_color": "#FBFAF8",
    "card_background": "#FFFFFF",
    "font_family": "'The Sans Arabic', Arial, sans-serif",
    "header_html": "<!-- header: logo ##LOGO## + title + gradient line -->",
    "footer_html": "<!-- footer: page number + project name + company -->",
    "card_style": "border-radius:14px; box-shadow:0 4px 20px rgba(0,0,0,0.06);",
    "title_style": "font-size:14px; font-weight:800; color:#670D0C;",
    "value_style": "font-size:36px; font-weight:900; color:#670D0C;",
    "label_style": "font-size:12px; font-weight:600; color:#64748B;",
    "background_pattern": "<!-- subtle SVG pattern 5-8% opacity -->"
  }}
}}

Header: logo ##LOGO## (height:48px) + slide title (13px bold burgundy) + thin gradient line. Semi-transparent white bg.
Footer: slide number in burgundy circle (28×28px) + project name + "منافع الاقتصادية للعقار". Height ~40px.
Project: {project_name}, Type: {project_type}, City: {city}
Return ONLY the JSON."""


def generate_blueprint(project_data, user_id):
    """Generate a design blueprint that all slides will share for visual consistency."""
    project_name = project_data.get('projectName', 'المشروع')
    project_type = project_data.get('projectType', '')
    city = project_data.get('city', '')

    user_message = BLUEPRINT_PROMPT.format(
        project_name=project_name,
        project_type=project_type,
        city=city
    )

    try:
        data, messages = call_zai_chat(
            "You are a luxury brand identity designer. Return ONLY valid JSON.",
            user_message, user_id, max_tokens=4000
        )
        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM failed for blueprint")

        result_text = data["choices"][0]["message"]["content"].strip()

        # Extract JSON
        result = None
        slides_match = re.search(r'\{\s*"blueprint"\s*:', result_text)
        if slides_match:
            start = slides_match.start()
            depth, in_string, escape_next = 0, False, False
            end = start
            for i in range(start, len(result_text)):
                c = result_text[i]
                if escape_next: escape_next = False; continue
                if c == '\\' and in_string: escape_next = True; continue
                if c == '"' and not escape_next: in_string = not in_string; continue
                if not in_string:
                    if c == '{': depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0: end = i + 1; break
            try: result = json.loads(result_text[start:end])
            except json.JSONDecodeError: pass

        if not result:
            match = re.search(r'\{[\s\S]*\}', result_text)
            if match:
                try: result = json.loads(match.group(0))
                except json.JSONDecodeError: pass

        if result and result.get('blueprint'):
            print(f"  [BLUEPRINT] Generated successfully")
            return result['blueprint']
        else:
            raise Exception("No blueprint in response")

    except Exception as e:
        print(f"  [BLUEPRINT] Generation failed: {e}, using defaults")
        # Return default blueprint
        return {
            "primary_color": "#670D0C",
            "secondary_color": "#C2A176",
            "background_color": "#FBFAF8",
            "card_background": "#FFFFFF",
            "accent_color": "#A7A9AC",
            "font_family": "'The Sans Arabic', Arial, sans-serif",
            "header_html": '<div style="position:relative;z-index:3;display:flex;align-items:center;justify-content:space-between;padding:14px 32px 12px;border-bottom:1px solid #EFE7DC;background:linear-gradient(180deg,rgba(255,255,255,.7),rgba(255,255,255,.0))"><div style="display:flex;align-items:center;gap:12px"><img src="##LOGO##" style="height:48px;width:auto;object-fit:contain;display:block"><div style="width:1px;height:28px;background:#EFE7DC"></div><div style="font-size:13px;font-weight:800;color:#670D0C;letter-spacing:.2px">{{TITLE}}</div></div><div style="display:flex;align-items:center;gap:8px"><div style="font-size:10px;font-weight:700;color:#888;letter-spacing:.5px">مشروع استثماري</div><div style="width:8px;height:8px;border-radius:50%;background:#C2A176"></div></div></div>',
            "footer_html": '<div style="position:relative;z-index:3;display:flex;align-items:center;justify-content:space-between;padding:10px 32px;border-top:1px solid #EFE7DC;background:linear-gradient(0deg,rgba(255,255,255,.7),rgba(255,255,255,.0))"><div style="display:flex;align-items:center;gap:12px"><div style="width:28px;height:28px;border-radius:50%;background:#670D0C;color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:900">{{PAGE}}</div><div style="font-size:11px;color:#888;font-weight:600">/ {{TOTAL}}</div></div><div style="font-size:12px;color:#7A0C0C;font-weight:800">{{PROJECT}}</div><div style="font-size:11px;color:#888;font-weight:600">منافع الاقتصادية للعقار</div></div>',
            "card_style": "border-radius:14px; box-shadow:0 4px 20px rgba(0,0,0,0.06); background:#FFFFFF; padding:20px;",
            "title_style": "font-size:14px; font-weight:800; color:#670D0C; letter-spacing:.2px;",
            "value_style": "font-size:36px; font-weight:900; color:#670D0C;",
            "label_style": "font-size:12px; font-weight:600; color:#64748B;",
            "svg_icon_style": "width:32px; height:32px; stroke:#670D0C; stroke-width:1.5; fill:none;",
            "background_pattern": '<svg style="position:absolute;top:0;left:0;width:100%;height:100%;opacity:0.05;z-index:0" viewBox="0 0 1280 720"><line x1="0" y1="0" x2="1280" y2="720" stroke="#C2A176" stroke-width="0.5"/><line x1="1280" y1="0" x2="0" y2="720" stroke="#C2A176" stroke-width="0.5"/><rect x="100" y="100" width="1080" height="520" fill="none" stroke="#C2A176" stroke-width="0.3"/></svg>'
        }


def _generate_single_slide(slide_data, project_data, user_id, variation_idx=0, blueprint=None):
    """Generate design for a single slide with a specific design variation."""
    idx = slide_data['idx']
    outline_item = slide_data['outline']
    title = outline_item.get('title', f'شريحة {idx+1}')
    slide_type = outline_item.get('type', 'content')
    bullets = outline_item.get('bullets', [])
    project_name = project_data.get('projectName', 'المشروع')
    project_type = project_data.get('projectType', '')
    city = project_data.get('city', '')

    # COVER SLIDE — hardcoded template, NO GLM call
    if idx == 0 or slide_type == 'cover':
        cover_html = f'''<div dir="rtl" lang="ar" style="width:1280px;height:720px;position:relative;overflow:hidden;font-family:'The Sans Arabic',Arial,sans-serif;background:#1A0505;">
<img src="##IMAGE_COVER##" style="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;">
<div style="position:absolute;top:0;left:0;width:100%;height:100%;background:linear-gradient(135deg,rgba(26,5,5,0.7) 0%,rgba(103,13,12,0.5) 100%);"></div>
<svg style="position:absolute;top:0;left:0;width:100%;height:100%;opacity:0.06;z-index:1" viewBox="0 0 1280 720"><line x1="0" y1="0" x2="1280" y2="720" stroke="#C2A176" stroke-width="1"/><line x1="1280" y1="0" x2="0" y2="720" stroke="#C2A176" stroke-width="1"/><rect x="100" y="100" width="1080" height="520" fill="none" stroke="#C2A176" stroke-width="0.5"/></svg>
<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;width:80%;z-index:2;">
<img src="##LOGO##" style="width:200px;height:auto;margin-bottom:28px;">
<h1 style="font-size:52px;font-weight:900;color:#FFFFFF;margin:0 0 16px 0;letter-spacing:1px;">{project_name}</h1>
<div style="width:80px;height:3px;background:#C2A176;margin:0 auto 20px;"></div>
<p style="font-size:20px;color:#C2A176;margin:0;letter-spacing:2px;">عرض مشروع استثماري</p>
</div>
<div style="position:absolute;bottom:30px;left:0;width:100%;text-align:center;z-index:2;">
<p style="font-size:13px;color:rgba(255,255,255,0.4);margin:0;">منافع الاقتصادية للعقار</p>
</div>
</div>'''
        return {'idx': idx, 'success': True, 'html': cover_html, 'title': title}

    # CLOSING SLIDE — hardcoded template, NO GLM call
    if idx == slide_data.get('total_slides', 99) - 1 or slide_type == 'closing':
        closing_html = f'''<div dir="rtl" lang="ar" style="width:1280px;height:720px;position:relative;overflow:hidden;font-family:'The Sans Arabic',Arial,sans-serif;background:#670D0C;">
<img src="##IMAGE_COVER##" style="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;opacity:0.25;">
<div style="position:absolute;top:0;left:0;width:100%;height:100%;background:linear-gradient(180deg,rgba(103,13,12,0.92) 0%,rgba(80,10,10,0.95) 100%);"></div>
<svg style="position:absolute;top:0;left:0;width:100%;height:100%;opacity:0.05;z-index:1" viewBox="0 0 1280 720"><line x1="0" y1="180" x2="1280" y2="180" stroke="#C2A176" stroke-width="0.5"/><line x1="0" y1="540" x2="1280" y2="540" stroke="#C2A176" stroke-width="0.5"/><rect x="80" y="80" width="1120" height="560" fill="none" stroke="#C2A176" stroke-width="0.5"/></svg>
<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;width:80%;z-index:2;">
<div style="background:rgba(255,255,255,0.95);border-radius:20px;padding:24px 40px;display:inline-block;margin-bottom:30px;box-shadow:0 8px 32px rgba(0,0,0,0.3);">
<img src="##LOGO##" style="width:180px;height:auto;">
</div>
<h1 style="font-size:56px;font-weight:900;color:#FFFFFF;margin:0 0 16px 0;">شكراً لكم</h1>
<div style="width:80px;height:3px;background:#C2A176;margin:0 auto 24px;"></div>
<p style="font-size:22px;color:#C2A176;margin:0 0 40px 0;">{project_name}</p>
<div style="background:rgba(255,255,255,0.08);border-radius:12px;padding:16px 32px;display:inline-block;border:1px solid rgba(194,161,118,0.3);">
<p style="font-size:15px;color:#FFFFFF;margin:0 0 8px 0;">للاستفسارات والتواصل</p>
<p style="font-size:14px;color:#C2A176;margin:0;">راسل فريق الاستثمار — منافع الاقتصادية للعقار</p>
</div>
</div>
<div style="position:absolute;bottom:20px;left:0;width:100%;text-align:center;z-index:2;">
<p style="font-size:12px;color:rgba(255,255,255,0.3);margin:0;">© منافع الاقتصادية للعقار</p>
</div>
</div>'''
        return {'idx': idx, 'success': True, 'html': closing_html, 'title': title}

    # MOOD BOARD — hardcoded template, NO GLM call
    if slide_type == 'mood_board':
        mood_html = f'''<div dir="rtl" lang="ar" style="width:1280px;height:720px;position:relative;overflow:hidden;font-family:'The Sans Arabic',Arial,sans-serif;background:#FBFAF8;display:flex;flex-direction:column;">
<div style="position:relative;z-index:3;display:flex;align-items:center;justify-content:space-between;padding:14px 32px 12px;border-bottom:1px solid #EFE7DC;background:linear-gradient(180deg,rgba(255,255,255,.7),rgba(255,255,255,.0))">
<div style="display:flex;align-items:center;gap:12px">
<img src="##LOGO##" style="height:48px;width:auto;object-fit:contain;display:block">
<div style="width:1px;height:28px;background:#EFE7DC"></div>
<div style="font-size:14px;font-weight:800;color:#7A0C0C;letter-spacing:.3px">MOOD BOARD</div>
</div>
<div style="display:flex;align-items:center;gap:8px">
<div style="font-size:10px;font-weight:700;color:#888;letter-spacing:.5px">Visual Inspiration</div>
<div style="width:8px;height:8px;border-radius:50%;background:#C2A176"></div>
</div>
</div>
<div style="position:relative;z-index:2;flex:1;padding:18px 32px 8px;display:flex;flex-direction:column;min-height:0">
<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:14px;flex:1">
<div style="border-radius:14px;overflow:hidden;position:relative;box-shadow:0 6px 18px rgba(0,0,0,0.08);background:#f7f4ef">
<img src="##MOODBOARD_IMAGE_1##" style="width:100%;height:100%;object-fit:cover;display:block">
<div style="position:absolute;bottom:0;left:0;right:0;background:linear-gradient(0deg,rgba(103,13,12,0.88),rgba(103,13,12,0.6));padding:8px 12px;color:#fff;font-size:12px;font-weight:700;text-align:center">Exterior Hero</div>
</div>
<div style="border-radius:14px;overflow:hidden;position:relative;box-shadow:0 6px 18px rgba(0,0,0,0.08);background:#f7f4ef">
<img src="##MOODBOARD_IMAGE_2##" style="width:100%;height:100%;object-fit:cover;display:block">
<div style="position:absolute;bottom:0;left:0;right:0;background:linear-gradient(0deg,rgba(103,13,12,0.88),rgba(103,13,12,0.6));padding:8px 12px;color:#fff;font-size:12px;font-weight:700;text-align:center">Right Facade</div>
</div>
<div style="border-radius:14px;overflow:hidden;position:relative;box-shadow:0 6px 18px rgba(0,0,0,0.08);background:#f7f4ef">
<img src="##MOODBOARD_IMAGE_3##" style="width:100%;height:100%;object-fit:cover;display:block">
<div style="position:absolute;bottom:0;left:0;right:0;background:linear-gradient(0deg,rgba(103,13,12,0.88),rgba(103,13,12,0.6));padding:8px 12px;color:#fff;font-size:12px;font-weight:700;text-align:center">Aerial View</div>
</div>
<div style="border-radius:14px;overflow:hidden;position:relative;box-shadow:0 6px 18px rgba(0,0,0,0.08);background:#f7f4ef">
<img src="##MOODBOARD_IMAGE_4##" style="width:100%;height:100%;object-fit:cover;display:block">
<div style="position:absolute;bottom:0;left:0;right:0;background:linear-gradient(0deg,rgba(103,13,12,0.88),rgba(103,13,12,0.6));padding:8px 12px;color:#fff;font-size:12px;font-weight:700;text-align:center">Left Facade</div>
</div>
</div>
<div style="margin-top:10px;display:flex;gap:14px;justify-content:center;font-size:11px;color:#7A0C0C;font-weight:bold">
<span style="display:flex;align-items:center;gap:4px"><span style="width:12px;height:12px;background:#670D0C;border-radius:3px;display:inline-block"></span> Burgundy</span>
<span style="display:flex;align-items:center;gap:4px"><span style="width:12px;height:12px;background:#C2A176;border-radius:3px;display:inline-block"></span> Gold</span>
<span style="display:flex;align-items:center;gap:4px"><span style="width:12px;height:12px;background:#F5F0EE;border-radius:3px;display:inline-block;border:1px solid #ccc"></span> Beige</span>
</div>
</div>
<div style="position:relative;z-index:3;display:flex;align-items:center;justify-content:space-between;padding:10px 32px;border-top:1px solid #EFE7DC;background:linear-gradient(0deg,rgba(255,255,255,.7),rgba(255,255,255,.0))">
<div style="display:flex;align-items:center;gap:12px">
<div style="width:28px;height:28px;border-radius:50%;background:#7A0C0C;color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:900">{idx+1}</div>
</div>
<div style="font-size:12px;color:#7A0C0C;font-weight:800">{project_name}</div>
<div style="font-size:11px;color:#888;font-weight:600">منافع الاقتصادية للعقار</div>
</div>
</div>'''
        return {'idx': idx, 'success': True, 'html': mood_html, 'title': title}

    try:
        slide_list = f"{idx+1}. {title}"
        if bullets:
            slide_list += '\n   ' + '\n   '.join(bullets)

        # Use condensed prompt with variation for speed
        variation = DESIGN_VARIATIONS[variation_idx % len(DESIGN_VARIATIONS)]
        dynamic_prompt = CONDENSED_DESIGN_PROMPT.format(variation=variation)

        # Append slide-type-specific design instruction
        slide_type_key = detect_slide_type(title)
        if slide_type_key in SLIDE_DESIGN_INSTRUCTIONS:
            dynamic_prompt += '\n\n' + SLIDE_DESIGN_INSTRUCTIONS[slide_type_key]

        # Inject blueprint into prompt if available
        if blueprint:
            bp = blueprint
            dynamic_prompt += f'''

══════════════════════════════════════════════════════════════════
MANDATORY DESIGN BLUEPRINT — YOU MUST USE EXACTLY THESE VALUES
══════════════════════════════════════════════════════════════════
Colors: primary={bp.get("primary_color","#670D0C")}, secondary={bp.get("secondary_color","#C2A176")}, bg={bp.get("background_color","#FBFAF8")}, card_bg={bp.get("card_background","#FFFFFF")}
Font: {bp.get("font_family","'The Sans Arabic',Arial,sans-serif")}
Card style: {bp.get("card_style","border-radius:14px; box-shadow:0 4px 20px rgba(0,0,0,0.06)")}
Title style: {bp.get("title_style","font-size:14px; font-weight:800; color:#670D0C")}
Value style: {bp.get("value_style","font-size:36px; font-weight:900; color:#670D0C")}
Label style: {bp.get("label_style","font-size:12px; font-weight:600; color:#64748B")}
SVG icon style: {bp.get("svg_icon_style","width:32px; height:32px; stroke:#670D0C; stroke-width:1.5; fill:none")}

HEADER HTML (use this EXACT header at the top of your slide):
{bp.get("header_html","")}

FOOTER HTML (use this EXACT footer at the bottom of your slide):
{bp.get("footer_html","")}

BACKGROUND PATTERN (add as first child of outer div):
{bp.get("background_pattern","")}'''

        # Build compact user message — skip unnecessary fields for speed
        compact_data = {
            'projectName': project_data.get('projectName'),
            'projectType': project_data.get('projectType'),
            'city': project_data.get('city'),
            'location': project_data.get('location'),
            'idea': project_data.get('idea'),
            'developer': project_data.get('developer'),
            'components': project_data.get('components'),
            'landArea': project_data.get('landArea'),
            'avgRent': project_data.get('avgRent'),
            'annualRevenue': project_data.get('annualRevenue'),
            'annualOpex': project_data.get('annualOpex'),
            'landCost': project_data.get('landCost'),
            'developmentCost': project_data.get('developmentCost'),
            'totalOperatingProfit': project_data.get('totalOperatingProfit'),
            'exitValue': project_data.get('exitValue'),
            'capRate': project_data.get('capRate'),
            'annualROI': project_data.get('annualROI'),
            'noiRate': project_data.get('noiRate'),
            'payback': project_data.get('payback'),
        }
        user_message = 'PROJECT DATA:\n' + json.dumps(compact_data, ensure_ascii=False)
        user_message += f'\n\nSLIDE TO DESIGN:\n{slide_list}'
        user_message += '\n\nReturn ONLY JSON with one slide in "slides" array. html must be complete with ALL inline CSS.'

        data, messages = call_zai_chat(dynamic_prompt, user_message, user_id, max_tokens=12000)

        if "choices" not in data or len(data["choices"]) == 0:
            error_msg = str(data)[:200]
            print(f"  [GLM ERROR] Slide {idx+1}: {error_msg}")
            raise Exception(f"GLM failed: {error_msg}")

        result_text = data["choices"][0]["message"]["content"].strip()

        # Robust JSON extraction — handle GLM returning text around JSON
        result = None
        # Method 1: Find {"slides": [...]} with proper bracket matching
        slides_match = re.search(r'\{\s*"slides"\s*:\s*\[', result_text)
        if slides_match:
            start = slides_match.start()
            depth, in_string, escape_next = 0, False, False
            end = start
            for i in range(start, len(result_text)):
                c = result_text[i]
                if escape_next:
                    escape_next = False
                    continue
                if c == '\\' and in_string:
                    escape_next = True
                    continue
                if c == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if not in_string:
                    if c == '{': depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
            try:
                result = json.loads(result_text[start:end])
            except json.JSONDecodeError:
                pass
        # Method 2: Greedy regex fallback
        if not result:
            match = re.search(r'\{[\s\S]*\}', result_text)
            if match:
                try: result = json.loads(match.group(0))
                except json.JSONDecodeError: pass
        # Method 3: Fix trailing commas
        if not result:
            first_brace = result_text.find('{')
            last_brace = result_text.rfind('}')
            if first_brace != -1 and last_brace > first_brace:
                candidate = result_text[first_brace:last_brace+1]
                candidate = re.sub(r',\s*([}\]])', r'\1', candidate)
                try: result = json.loads(candidate)
                except json.JSONDecodeError: pass

        if not result:
            raise Exception("No valid JSON in GLM response")

        slides = result.get("slides", [])
        if slides and slides[0].get('html'):
            html = slides[0]['html']
            if len(html) < 100:
                raise Exception(f"HTML too short ({len(html)} chars) — likely truncated")
            return {'idx': idx, 'success': True, 'html': html, 'title': slides[0].get('title', title)}
        else:
            raise Exception("No html in response")
    except Exception as e:
        print(f"  [FAIL] Slide {idx+1} ({title}): {str(e)}")
        return {'idx': idx, 'success': False, 'error': str(e)}


def _generate_single_slide_legacy(slide_data, project_data, user_id):
    """Generate design for a single slide — legacy full prompt version."""
    idx = slide_data['idx']
    outline_item = slide_data['outline']
    title = outline_item.get('title', f'شريحة {idx+1}')
    slide_type = outline_item.get('type', 'content')
    bullets = outline_item.get('bullets', [])
    project_name = project_data.get('projectName', 'المشروع')

    # COVER — hardcoded
    if idx == 0 or slide_type == 'cover':
        cover_html = f'''<div dir="rtl" lang="ar" style="width:1280px;height:720px;position:relative;overflow:hidden;font-family:'The Sans Arabic',Arial,sans-serif;background:#1A0505;'>
<img src="##IMAGE_COVER##" style="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;">
<div style="position:absolute;top:0;left:0;width:100%;height:100%;background:linear-gradient(135deg,rgba(26,5,5,0.7) 0%,rgba(103,13,12,0.5) 100%);"></div>
<div style="position:absolute;top:0;right:0;width:53px;height:100%;background:#670D0C;"></div>
<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;width:80%;">
<img src="##LOGO##" style="width:240px;height:auto;margin-bottom:24px;">
<h1 style="font-size:52px;font-weight:900;color:#FFFFFF;margin:0 0 16px 0;letter-spacing:1px;">{project_name}</h1>
<div style="width:80px;height:3px;background:#C2A176;margin:0 auto 20px;"></div>
<p style="font-size:20px;color:#C2A176;margin:0;letter-spacing:2px;">عرض مشروع استثماري</p>
</div>
<div style="position:absolute;bottom:30px;left:0;width:100%;text-align:center;">
<p style="font-size:13px;color:rgba(255,255,255,0.4);margin:0;">منافع الاقتصادية للعقار</p>
</div>
</div>'''
        return {'idx': idx, 'success': True, 'html': cover_html, 'title': title}

    # CLOSING — hardcoded
    if idx == slide_data.get('total_slides', 99) - 1 or slide_type == 'closing':
        closing_html = f'''<div dir="rtl" lang="ar" style="width:1280px;height:720px;position:relative;overflow:hidden;font-family:'The Sans Arabic',Arial,sans-serif;background:#670D0C;">
<div style="position:absolute;top:0;left:0;width:100%;height:100%;background:linear-gradient(180deg,rgba(103,13,12,1) 0%,rgba(80,10,10,1) 100%);"></div>
<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;width:80%;">
<div style="background:rgba(255,255,255,0.95);border-radius:20px;padding:24px 40px;display:inline-block;margin-bottom:30px;box-shadow:0 8px 32px rgba(0,0,0,0.3);">
<img src="##LOGO##" style="width:220px;height:auto;">
</div>
<h1 style="font-size:56px;font-weight:900;color:#FFFFFF;margin:0 0 16px 0;">شكراً لكم</h1>
<div style="width:80px;height:3px;background:#C2A176;margin:0 auto 24px;"></div>
<p style="font-size:22px;color:#C2A176;margin:0 0 40px 0;">{project_name}</p>
<div style="background:rgba(255,255,255,0.08);border-radius:12px;padding:16px 32px;display:inline-block;border:1px solid rgba(194,161,118,0.3);">
<p style="font-size:15px;color:#FFFFFF;margin:0 0 8px 0;">للاستفسارات والتواصل</p>
<p style="font-size:14px;color:#C2A176;margin:0;">راسل فريق الاستثمار — منافع الاقتصادية للعقار</p>
</div>
</div>
<div style="position:absolute;bottom:20px;left:0;width:100%;text-align:center;">
<p style="font-size:12px;color:rgba(255,255,255,0.3);margin:0;">© منافع الاقتصادية للعقار</p>
</div>
</div>'''
        return {'idx': idx, 'success': True, 'html': closing_html, 'title': title}

    try:
        slide_list = f"{idx+1}. {title}"
        if bullets:
            slide_list += '\n   ' + '\n   '.join(bullets)

        image_info = ''
        if project_data and project_data.get('mainImageData'):
            image_info = f"\n\nMAIN COVER IMAGE URL: {project_data['mainImageData'][:100]}..."

        user_message = 'PROJECT DATA:\n' + json.dumps({
            'projectName': project_data.get('projectName'),
            'projectType': project_data.get('projectType'),
            'city': project_data.get('city'),
            'location': project_data.get('location'),
            'idea': project_data.get('idea'),
            'structure': project_data.get('structure'),
            'developer': project_data.get('developer'),
            'components': project_data.get('components'),
            'landArea': project_data.get('landArea'),
            'buildingRatio': project_data.get('buildingRatio'),
            'areaNote': project_data.get('areaNote'),
            'avgRent': project_data.get('avgRent'),
            'serviceFees': project_data.get('serviceFees'),
            'annualRevenue': project_data.get('annualRevenue'),
            'annualOpex': project_data.get('annualOpex'),
            'landCost': project_data.get('landCost'),
            'developmentCost': project_data.get('developmentCost'),
            'totalOperatingProfit': project_data.get('totalOperatingProfit'),
            'exitValue': project_data.get('exitValue'),
            'capRate': project_data.get('capRate'),
            'annualROI': project_data.get('annualROI'),
            'noiRate': project_data.get('noiRate'),
            'payback': project_data.get('payback'),
            'timelineRows': project_data.get('timelineRows'),
            'risks': project_data.get('risks'),
            'recommendation': project_data.get('recommendation'),
            'preparedBy': project_data.get('preparedBy'),
            'contactInfo': project_data.get('contactInfo'),
            'googleMapsLink': project_data.get('googleMapsLink'),
            'locationFeatures': project_data.get('locationFeatures'),
            'projectFeatures': project_data.get('projectFeatures'),
            'investmentHighlights': project_data.get('investmentHighlights')
        }, indent=2, ensure_ascii=False)

        user_message += f'\n\nSLIDE TO DESIGN:\n{slide_list}'
        if image_info:
            user_message += image_info
        user_message += (
            '\n\nIMPORTANT: You must generate BOTH the content AND the design together. '
            'Do NOT just return a design shell — write the actual Arabic content inside the slide. '
            'CRITICAL: Use the EXACT text from the "SLIDE TO DESIGN" section. Do NOT paraphrase, abbreviate, or shorten the content. '
            'If the text is long, reduce font size to fit — but NEVER change the words. '
            'Return ONLY the JSON object with "slides" array containing ONE slide with "title" and "html" keys. '
            'The html must be a COMPLETE, self-contained slide with ALL inline CSS, real Arabic content, and a stunning visual design. '
            'Do NOT use plain white backgrounds. Content MUST fit within the slide boundaries. Use overflow:hidden.'
        )

        dynamic_prompt = build_design_prompt([outline_item])
        data, messages = call_zai_chat(dynamic_prompt, user_message, user_id, max_tokens=16000)

        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM failed")

        result_text = data["choices"][0]["message"]["content"].strip()

        # Robust JSON extraction
        result = None
        slides_match = re.search(r'\{\s*"slides"\s*:\s*\[', result_text)
        if slides_match:
            start = slides_match.start()
            depth, in_string, escape_next = 0, False, False
            end = start
            for i in range(start, len(result_text)):
                c = result_text[i]
                if escape_next: escape_next = False; continue
                if c == '\\' and in_string: escape_next = True; continue
                if c == '"' and not escape_next: in_string = not in_string; continue
                if not in_string:
                    if c == '{': depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0: end = i + 1; break
            try: result = json.loads(result_text[start:end])
            except json.JSONDecodeError: pass
        if not result:
            match = re.search(r'\{[\s\S]*\}', result_text)
            if match:
                try: result = json.loads(match.group(0))
                except json.JSONDecodeError: pass
        if not result:
            raise Exception("No valid JSON in GLM response")

        slides = result.get("slides", [])
        if slides and slides[0].get('html'):
            html = slides[0]['html']
            if len(html) < 100:
                raise Exception(f"HTML too short ({len(html)} chars)")
            return {'idx': idx, 'success': True, 'html': html, 'title': slides[0].get('title', title)}
        else:
            raise Exception("No html in response")
    except Exception as e:
        print(f"  [FAIL] Slide {idx+1} ({title}): {str(e)}")
        return {'idx': idx, 'success': False, 'error': str(e)}


@app.route('/api/generate-design-batch', methods=['POST'])
def api_generate_design_batch():
    """Generate designs with BLUEPRINT system:
    1. Generate shared design blueprint (1 GLM call)
    2. All slides use same blueprint for consistency (parallel GLM calls)
    First valid result per slide wins."""
    from flask import Response
    import json as _json

    project_data = truncate_project_data(request.json.get('projectData'), 3000)
    outline = request.json.get('outline') or []
    user_id = request.json.get('userId') or 'default_user'
    parallel_per_slide = min(request.json.get('parallel', 3), 5)
    use_sse = request.json.get('sse', False)

    if not project_data:
        return jsonify({'error': 'Project data is required'}), 400

    slide_count = len(outline)
    if slide_count == 0:
        return jsonify({'error': 'No slides to generate — outline is empty'}), 400

    start_time = time.time()

    # STEP 1: Generate blueprint (shared design identity)
    print(f"\n[Batch Design] Step 1: Generating blueprint...")
    blueprint = generate_blueprint(project_data, user_id)
    blueprint_time = time.time() - start_time
    print(f"  [BLUEPRINT] Done in {blueprint_time:.1f}s")

    # STEP 2: Generate all slides — sequential with retries for reliability
    print(f"[Batch Design] Step 2: Generating {slide_count} slides sequentially with retries")

    def _generate_one_slide_inner(idx, outline_item):
        """Generate one slide with blueprint, retry up to 3 times."""
        slide_data = {'idx': idx, 'outline': outline_item, 'total_slides': slide_count}
        best_result = None

        for attempt in range(4):  # 1 initial + 3 retries
            variation_idx = attempt % len(DESIGN_VARIATIONS)
            try:
                result = _generate_single_slide(slide_data, project_data, user_id, variation_idx, blueprint)
                if result and result.get('success'):
                    best_result = result
                    break
            except Exception as e:
                pass
            if attempt < 3:
                import time as _time
                _time.sleep(2)

        if not best_result:
            best_result = {'idx': idx, 'success': False, 'error': 'All attempts failed'}
        return best_result

    if use_sse:
        # SSE streaming — send progress per slide as it completes
        def stream_generate():
            results = [None] * slide_count
            completed_count = [0]

            with ThreadPoolExecutor(max_workers=slide_count) as main_executor:
                main_futures = {}
                for idx in range(slide_count):
                    f = main_executor.submit(_generate_one_slide_inner, idx, outline[idx])
                    main_futures[f] = idx

                for future in main_futures:
                    idx = main_futures[future]
                    try:
                        result = future.result(timeout=180)
                        results[idx] = result
                        completed_count[0] += 1
                        elapsed = time.time() - start_time
                        event_data = {
                            'type': 'slide_done',
                            'idx': idx,
                            'success': result.get('success', False),
                            'html': result.get('html', ''),
                            'title': result.get('title', ''),
                            'completed': completed_count[0],
                            'total': slide_count,
                            'elapsed': round(elapsed, 1)
                        }
                        if not result.get('success'):
                            event_data['error'] = result.get('error', '')
                        yield f"data: {_json.dumps(event_data, ensure_ascii=False)}\n\n"
                        print(f"  [OK] Slide {idx+1} done ({completed_count[0]}/{slide_count}) | {elapsed:.1f}s")
                    except Exception as e:
                        results[idx] = {'idx': idx, 'success': False, 'error': str(e)}
                        completed_count[0] += 1
                        elapsed = time.time() - start_time
                        yield f"data: {_json.dumps({'type': 'slide_done', 'idx': idx, 'success': False, 'error': str(e), 'completed': completed_count[0], 'total': slide_count, 'elapsed': round(elapsed, 1)}, ensure_ascii=False)}\n\n"
                        print(f"  [FAIL] Slide {idx+1}: {str(e)}")

            elapsed = time.time() - start_time
            success_count = sum(1 for r in results if r and r.get('success'))
            print(f"  [DONE] {success_count}/{slide_count} slides in {elapsed:.1f}s ({elapsed/max(slide_count,1):.1f}s per slide)")

            final_event = {
                'type': 'done',
                'success_count': success_count,
                'total': slide_count,
                'elapsed': round(elapsed, 1),
                'slides': results
            }
            yield f"data: {_json.dumps(final_event, ensure_ascii=False)}\n\n"

        return Response(stream_generate(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    else:
        # Non-SSE mode — process in batches of 4 to avoid rate limiting
        results = [None] * slide_count
        batch_size = 4

        for batch_start in range(0, slide_count, batch_size):
            batch_end = min(batch_start + batch_size, slide_count)
            print(f"  [BATCH] Slides {batch_start+1}-{batch_end} of {slide_count}")

            with ThreadPoolExecutor(max_workers=batch_size) as batch_executor:
                batch_futures = {}
                for idx in range(batch_start, batch_end):
                    f = batch_executor.submit(_generate_one_slide_inner, idx, outline[idx])
                    batch_futures[f] = idx

                for future in batch_futures:
                    idx = batch_futures[future]
                    try:
                        result = future.result(timeout=180)
                        results[idx] = result
                        if result.get('success'):
                            print(f"  [OK] Slide {idx+1} done")
                        else:
                            print(f"  [FAIL] Slide {idx+1}: {result.get('error', 'unknown')}")
                    except Exception as e:
                        results[idx] = {'idx': idx, 'success': False, 'error': str(e)}
                        print(f"  [FAIL] Slide {idx+1}: {str(e)}")

        elapsed = time.time() - start_time
        success_count = sum(1 for r in results if r and r.get('success'))
        print(f"  [DONE] {success_count}/{slide_count} slides in {elapsed:.1f}s ({elapsed/max(slide_count,1):.1f}s per slide)")

        return jsonify({
            'success': True,
            'slides': results,
            'elapsed': round(elapsed, 1),
            'success_count': success_count
        })


@app.route('/api/redesign-slide', methods=['POST'])
def api_redesign_slide():
    slide_html = request.json.get('slideHtml')
    slide_title = request.json.get('slideTitle')
    edit_request = request.json.get('editRequest')
    project_data = truncate_project_data(request.json.get('projectData'), 6000)
    all_slides = request.json.get('allSlides') or []
    user_id = request.json.get('userId') or 'default_user'
    is_global_style = request.json.get('isGlobalStyle', False)

    if not edit_request:
        return jsonify({'error': 'Edit request is required'}), 400

    print(f"\n[Redesign] Redesigning slide: {slide_title}")
    print(f"  Request: {edit_request[:100]}")
    print(f"  Global style: {is_global_style}")

    try:
        if is_global_style:
            system_prompt = (
                'You are a luxury presentation designer for "منافع الاقتصادية للعقار". '
                'The user wants to change the design style of ALL slides. '
                'You will receive the current HTML of the slide and a request for style changes. '
                'Return a JSON object with: { "action": "global_style", "css": "CSS rules to apply globally", "response": "Arabic explanation", "updated_slides": [{ "title": "...", "html": "..." }] }. '
                'The css should target slide elements like: .slide, .slide-title, .kpi-card, etc. '
                'The updated_slides array should contain redesigned versions of the slides that need visual changes.'
            )
        else:
            system_prompt = (
                'You are a luxury presentation designer for "منافع الاقتصادية للعقار". '
                'Redesign this specific slide based on the user request. '
                'Return a JSON object with: { "title": "new title (keep if not changing)", "html": "new complete HTML with inline CSS" }. '
                'Keep the same brand colors: burgundy #670D0C, gold #C2A176, silver #A7A9AC, beige #F5F0EE. '
                'Font: The Sans Arabic. RTL layout. '
                'The html must be a complete div with ALL inline styles, width:100%, height:100%, dir=rtl, lang=ar. '
                'If images were in the original slide, keep them in the redesigned version.'
            )

        user_message = f'SLIDE TITLE: {slide_title}\n\n'
        user_message += f'CURRENT HTML:\n{slide_html or "No HTML"}\n\n'
        user_message += 'PROJECT DATA CONTEXT:\n' + json.dumps({
            'projectName': project_data.get('projectName') if project_data else '',
            'annualRevenue': project_data.get('annualRevenue') if project_data else 0,
            'totalCost': ((project_data.get('landCost') or 0) + (project_data.get('developmentCost') or 0)) if project_data else 0,
            'annualROI': project_data.get('annualROI') if project_data else '',
            'noiRate': project_data.get('noiRate') if project_data else '',
            'payback': project_data.get('payback') if project_data else ''
        }, indent=2, ensure_ascii=False) + '\n\n'

        if is_global_style and len(all_slides) > 0:
            user_message += 'ALL CURRENT SLIDES:\n'
            for i, s in enumerate(all_slides):
                user_message += f"\n--- Slide {i+1}: {s.get('title', '')} ---\n"
                user_message += (s.get('html') or '')[:500] + '\n...\n'

        user_message += f'USER REQUEST:\n{edit_request}'

        # GLM/ZAI only supports text content - no image_url type
        user_message_content = user_message
        main_image = project_data.get('mainImageData') if project_data else None
        if main_image:
            print("  Image available but GLM only supports text - skipping image")

        data, messages = call_zai_chat(system_prompt, user_message_content, user_id, max_tokens=12000)

        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM failed: " + json.dumps(data, ensure_ascii=False))

        cache_analytics = compute_cache_analytics(data, 'redesign_' + str(int(time.time())))
        result_text = data["choices"][0]["message"]["content"].strip()
        write_systemprombet_backup(messages, result_text)

        print(f"  [OK] Redesign completed | Cache: {cache_analytics['status']}")

        match = re.search(r'\{[\s\S]*\}', result_text)
        if match:
            result = json.loads(match.group(0))
            return jsonify({'success': True, 'data': result, 'cache_analytics': cache_analytics})
        else:
            raise Exception("No JSON in response")

    except Exception as e:
        print(f"  [FAIL] Redesign error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/save-file', methods=['POST'])
def api_save_file():
    filename = request.json.get('filename')
    base64_data = request.json.get('data')
    
    if not filename or not base64_data:
        return jsonify({'error': 'filename and data are required'}), 400
        
    filename = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filename)
    
    try:
        file_path = os.path.join(OUTPUT_DIR, filename)
        buffer = base64.b64decode(base64_data)
        
        with open(file_path, 'wb') as f:
            f.write(buffer)
            
        print(f"  [OK] Saved file to {file_path}")
        return jsonify({'success': True, 'url': f'/outputs/{filename}'})
    except Exception as e:
        print("  [FAIL] Error saving file:", str(e))
        return jsonify({'error': str(e)}), 500

PDF_DESIGN_PROMPT = """أنت مصمم جرافيك محترف ومبدع لتصميم عروض PDF تقديمية فاخرة لشركة "منافع الاقتصادية للعقار". مهمتك: تقرر التصميم البصري لكل سلايد في العرض بناءً على نوعه ومحتواه.

═══════════════════════════════════════════════════════════════
هوية العلامة التجارية
═══════════════════════════════════════════════════════════════
الألوان الأساسية:
- Burgundy (رئيسي): #7A0C0C — العناوين، الشرائط، العناصر الرئيسية
- Gold (ثانوي): #C4A35A — لمسات فاخرة، إبراز
- Beige (خلفية فاتحة): #F5F0EE — خلفيات البطاقات
- White: #FFFFFF — الخلفيات الأساسية
- نص داكن: #2D2D2D | نص رمادي: #777777

الخطوط: Helvetica-Bold للعناوين، Helvetica للمحتوى
اتجاه النص: RTL

═══════════════════════════════════════════════════════════════
صور المشروع — 4 صور فقط (لا تستخدم غيرهم)
═══════════════════════════════════════════════════════════════
يوجد 4 صور للمشروع فقط، كل صورة لها استخدام محدد:

【صورة 1 — غلاف المكان (cover_image)】
- وصف: لقطة خارجية للمشروع مع ناس سعوديين في المقدمة
- متطلبات: لا تظهر مباني مجاورة | اسم المبنى ظاهر لو موجود
- استخدامات:
  * Slide 1 (Cover): خلفية كاملة مع طبقة شفافة عنابية
  * Slide 14 (Closing): خلفية كاملة مع طبقة شفافة
  * Slide 3 (فكرة المشروع): بطاقة جانبية كبيرة
- حقل الصورة: "image_b64" أو "cover_image_b64"

【صورة 2 — واجهة يمين (facade_right)】
- وصف: واجهة المبنى من الجانب الأيمن
- متطلبات: لا مباني مجاورة | اسم المبنى ظاهر
- استخدامات:
  * Slide 5 (مميزات المشروع): بطاقة داخل الشبكة
  * Slide 6 (المكونات): بطاقة جانبية بجانب الجدول
  * Slide 12 (فرص الاستثمار): صورة خلفية شفافة
- حقل الصورة: "facade_right_b64"

【صورة 3 — واجهة يسار (facade_left)】
- وصف: واجهة المبنى من الجانب الأيسر
- متطلبات: لا مباني مجاورة | اسم المبنى ظاهر
- استخدامات:
  * Slide 4 (موقع المشروع): بطاقة مع خريطة
  * Slide 7 (الربح التشغيلي): صورة جانبية
  * Slide 8 (التكاليف): صورة في المقارنة
- حقل الصورة: "facade_left_b64"

【صورة 4 — واجهة من الأعلى (aerial_view)】
- وصف: لقطة جوية/من الأعلى للمشروع بالكامل
- متطلبات: لا مباني مجاورة | اسم المبنى ظاهر
- استخدامات:
  * Slide 2 (الملخص التنفيذي): صورة صغيرة في الـ Dashboard
  * Slide 9 (الأرباح والتخارج): صورة خلفية شفافة
  * Slide 10 (المؤشرات المالية): صورة جانبية
  * Slide 11 (الجدول الزمني): صورة فوق التايم لاين
- حقل الصورة: "aerial_view_b64"

【صورة العميل المرفوعة (client_reference)】
- إذا رفع العميل صورة مرجعية، استخدمها كـ inspiration
- AI يمكنه توليد صور مشابهة بناءً عليها
- حقل الصورة: "client_image_b64"
- ملاحظة: هذه الصورة للإلهام فقط، ليست جزء من الـ 4 الأساسية

═══════════════════════════════════════════════════════════════
قواعد استخدام الصور
═════════════════════════════════════════════════════════════
1. استخدم فقط الـ 4 صور المحددة أعلاه — لا تضيف صور عشوائية
2. كل سلايد يستخدم صورة واحدة كحد أقصى (ماعدا Cover/Closing)
3. الصور لازم يكون لها إطار أنيق (border radius + shadow)
4. لا تمدد الصور بشكل مشوه — استخدم preserveAspectRatio
5. ضع نص فوق الصور بخلفية شفافة إذا لزم الأمر
6. إذا لم تتوفر صورة معينة، اترك مكانها فارغاً أو استخدم زخرفة بدلاً منها

═══════════════════════════════════════════════════════════════
القواعد العامة للتصميم (تُطبق على كل الشرائح)
═══════════════════════════════════════════════════════════════
1. اللوقو: شعار "منافع الاقتصادية" أعلى يمين كل شريحة بحجم واضح وأبعاد صحيحة
2. اسم الشريحة: بجانب اللوقو بخط صغير
3. خط هندسي رفيع أسفل الهيدر
4. الفوتر: اسم المشروع + "منافع الاقتصادية للعقار" + رقم الشريحة
5. رقم الشريحة داخل دائرة أو مستطيل عنابي صغير
6. الفوتر موحد في كل الشرائح ولا يزاحم المحتوى
7. مساحات بيضاء كافية — لا تزاحم
8. أيقونات خطية احترافية (ليست كرتونية)
9. رسومات هندسية خفيفة في الخلفية (خطوط معمارية، أشكال مجردة، Pattern بسيط)
10. الأرقام المالية كبيرة وواضحة ومميزة بصرياً

═══════════════════════════════════════════════════════════════
أنواع السلايدات وتصميماتها المحددة
═══════════════════════════════════════════════════════════════

【SLIDE 1 — الغلاف / COVER】
- نوع: "cover"
- الصورة: cover_image (غلاف المكان مع ناس سعوديين) → خلفية كاملة
- التصميم: خلفية داكنة فاخرة (gradient_v من #5A0808 إلى #7A0C0C)
- صورة المشروع كخلفية إذا وُجدت مع طبقة شفافة عنابية (opacity 0.55)
- اللوقو في المنتصف بحجم كبير (لا تضعه صغيراً في الزاوية)
- اسم المشروع في منتصف الشريحة بخط كبير جداً
- تحته وصف مثل "عرض مشروع استثماري"
- لمسة ذهبية (stripe أو decorative elements)
- mood: dramatic | layout: centered | title_style: large_centered
- decorative_elements: دوائر ذهبية شفافة + شريط مائل
- image_to_use: "cover_image"

【SLIDE 2 — الملخص التنفيذي】
- نوع: "content" أو "metrics"
- الصورة: aerial_view (صورة من الأعلى) → صورة صغيرة في أعلى الـ Dashboard
- تصميم: Dashboard استثماري فاخر
- النص التعريفي في أعلى الشريحة
- المؤشرات الرئيسية داخل بطاقات كبيرة (2x3 أو 3x2):
  * إجمالي التكلفة، الإيرادات السنوية، إجمالي الأرباح (الأكثر بروزاً)
  * العائد السنوي المتوقع، NOI المتوقع، استرداد رأس المال
- كل بطاقة لها لون خاص مع ظل خفيف
- mood: modern | layout: cards | title_style: top_bar
- decorative_elements: glow خفيفة + dot grid

【SLIDE 3 — فكرة المشروع والهيكلة】
- نوع: "content"
- الصورة: cover_image (غلاف المكان) → بطاقة جانبية كبيرة
- تصميم: لوحة معلومات منظمة
- المحتوى مقسّم إلى بطاقات: فكرة المشروع، الموقع، هيكلة المشروع، نوع المشروع، المطور
- كل بطاقة مع أيقونة مناسبة
- زر Google Maps واضح إذا وُجد الرابط
- خلفية هندسية خفيفة
- mood: modern | layout: cards | card_style: rounded_shadow
- decorative_elements: خطوط هندسية خفيفة + شريط جانبي
- image_to_use: "cover_image"

【SLIDE 4 — مميزات الموقع】
- نوع: "content"
- الصورة: facade_left (واجهة يسار) → بطاقة مع الخريطة
- تصميم: بطاقات مميزة لكل ميزة
- كل ميزة في بطاقة مستقلة مع أيقونة
- أيقونات: Location Pin، Road، Accessibility، Population، Growth
- عنصر خريطة أو Pin في الخلفية بشكل شفاف
- زر Google Maps واضح
- mood: bold | layout: split_rl | title_style: side_accent
- decorative_elements: circle خريطة شفافة + dot grid
- image_to_use: "facade_left"

【SLIDE 5 — مميزات المشروع】
- نوع: "content"
- الصورة: facade_right (واجهة يمين) → بطاقة داخل الشبكة
- تصميم: شبكة تسويقية جذابة
- 4 بطاقات أو أكثر، كل بطاقة: أيقونة + عنوان + وصف
- خلفية بيج فاتحة مع عناوين عنابية
- عناصر معمارية خفيفة في الخلفية
- mood: warm | layout: cards | card_style: rounded_shadow
- decorative_elements: geometric lines + circle
- image_to_use: "facade_right"

【SLIDE 6 — مكونات المشروع والمساحات】
- نوع: "table"
- الصورة: facade_right (واجهة يمين) → بطاقة جانبية بجانب الجدول
- تصميم: جدول احترافي
- رأس الجدول burgundy مع نص أبيض
- صفوف متناوبة (أبيض + بيج)
- صف الإجمالي بخط Bold وخلفية مختلفة
- أسفل الجدول 3 بطاقات: مساحة الأرض، نسبة البناء، ملاحظة المساحات
- mood: minimal | layout: cards | title_style: top_bar
- decorative_elements: line أفقية + stripe خفيفة
- image_to_use: "facade_right"

【SLIDE 7 — افتراضات الربح التشغيلي】
- نوع: "content"
- الصورة: facade_left (واجهة يسار) → صورة جانبية
- تصميم: معادلة بصرية
- المعادلة: الإيرادات - المصروفات = الربح = معروفة بصرياً
- كل رقم داخل بطاقة مالية واضحة
- إجمالي الربح هو العنصر الأكبر والأوضح
- جدول صغير أسفل كمرجع
- mood: modern | layout: split_rl | title_style: top_bar
- decorative_elements: arrow/flow lines + glow
- image_to_use: "facade_left"

【SLIDE 8 — افتراضات التكاليف】
- نوع: "content"
- الصورة: facade_left (واجهة يسار) → صورة في المقارنة
- تصميم: مقارنة بين تكلفة الأرض وتكلفة التطوير
- تكلفة الأرض في بطاقة كبيرة + تكلفة التطوير في بطاقة كبيرة
- إجمالي التكلفة في بطاقة أكبر وأكثر بروزًا
- Bar يوضح مساهمة كل بند
- mood: modern | layout: cards | title_style: top_bar
- decorative_elements: bar_chart_simulated + circle
- image_to_use: "facade_left"

【SLIDE 9 — الأرباح والتخارج】
- نوع: "content"
- الصورة: aerial_view (من الأعلى) → خلفية شفافة
- تصميم: مسار قيمة استثماري
- المعادلة بصرياً: الربح التشغيلي + قيمة التخارج = إجمالي الأرباح
- سهم أفقي أو Flow Diagram
- قيمة التخارج وإجمالي الأرباح أكثر بروزًا
- mood: bold | layout: centered | title_style: large_centered
- decorative_elements: arrow + stripe + glow
- image_to_use: "aerial_view"

【SLIDE 10 — المؤشرات المالية المتوقعة】
- نوع: "metrics"
- الصورة: aerial_view (من الأعلى) → صورة جانبية
- تصميم: Financial Dashboard
- بطاقات علوية كبيرة: ROI، NOI، Payback
- أسفلها مقارنة بصرية: إجمالي التكلفة vs إجمالي الأرباح
- أرقام بارزة وواضحة جدًا (18-24px)
- mood: minimal | layout: cards | title_style: top_bar
- decorative_elements: dot_grid + geometric lines
- image_to_use: "aerial_view"

【SLIDE 11 — الجدول الزمني ومراحل المشروع】
- نوع: "timeline"
- الصورة: aerial_view (من الأعلى) → فوق التايم لاين كخلفية شفافة
- كل مرحلة كشريط أفقي ممتد حسب مدتها
- ألوان هادئة: burgundy، بني فاتح، بيج، رمادي
- أسماء المراحل واضحة داخل أو بجانب الشرائط
- خلفية فاتحة مع شبكة زمنية
- mood: minimal | layout: timeline | title_style: top_bar
- decorative_elements: grid lines + bar styles
- image_to_use: "aerial_view"

【SLIDE 12 — فرص الاستثمار ونقاط القوة】
- نوع: "content"
- الصورة: facade_right (واجهة يمين) → صورة خلفية شفافة
- تصميم: High Impact marketing
- كل فرصة في بطاقة كبيرة مع أيقونة
- عنوان قصير + وصف مختصر
- أسلوب تسويقي جذاب
- عنصر بصري: سهم نمو أو مخطط صاعد في الخلفية
- mood: bold | layout: cards | card_style: flat_border
- decorative_elements: arrow + stripe + glow
- image_to_use: "facade_right"

【SLIDE 13 — المخاطر والافتراضات】
- نوع: "content"
- الصورة: بدون صورة (استخدم زخرفة بدلاً منها)
- تصميم: احترافي وهادئ (ليس سلبياً)
- مخاطر مقسّمة إلى بطاقات مرتبة
- أيقونة تنبيه بسيطة لكل خطر
- ألوان رمادية وبيج مع لمسة عنابية
- عنوان فرعي: "نقاط يجب التحقق منها في الدراسة التفصيلية"
- mood: minimal | layout: cards | card_style: rounded_shadow
- decorative_elements: dot_grid + line borders
- image_to_use: null

【SLIDE 14 — الختام / CLOSING】
- نوع: "closing"
- الصورة: cover_image (غلاف المكان) → خلفية كاملة مع طبقة شفافة
- تصميم: خلفية فاخرة (gradient_v أو صورة مع طبقة شفافة)
- شعار منافع الاقتصادية واضح في الأعلى أو المنتصف
- "شكراً لكم" بخط كبير في المنتصف
- اسم المشروع أسفلها
- بيانات التواصل مرتبة في الأسفل
- لمسة ذهبية زخرفية
- mood: dramatic | layout: centered | title_style: large_centered
- decorative_elements: دوائر كبيرة + شريط مائل + خطوط ذهبية

═══════════════════════════════════════════════════════════════
أنواع الخلفيات المتاحة (background_style)
═══════════════════════════════════════════════════════════════
- "solid" → لون خلفية واحد (يحتاج bg_color)
- "gradient_v" → تدرج عمودي (يحتاج gradient_top_color + gradient_bottom_color)
- "gradient_h" → تدرج أفقي (يحتاج gradient_left_color + gradient_right_color)
- "radial_glow" → إضاءة من نقطة (يحتاج glow_x_pct, glow_y_pct, glow_radius_mm, glow_color)
- "split" → تقسيم الصفحة (يحتاج split_direction + split_position_pct)
- "geometric" → شبكة نقط + خطوط هندسية خفيفة
- "wave" → موجة زخرفية (يحتاج wave_y_pct, wave_amplitude_mm, wave_wavelength_mm, wave_color)
- "dark" → خلفية داكنة مع إضاءة خفيفة

═══════════════════════════════════════════════════════════════
أنواع العناصر الزخرفية (decorative_elements)
═══════════════════════════════════════════════════════════════
- {"type": "circle", "x_pct": 0-1, "y_pct": 0-1, "r_mm": 20-100, "color": "#hex", "alpha": 0.03-0.2}
- {"type": "stripe", "position": "top-right"/"bottom-left"/"top-left"/"bottom-right", "width_mm": 50-200, "depth_mm": 100-300, "color": "#hex"}
- {"type": "line", "x1_pct": 0-1, "y1_pct": 0-1, "x2_pct": 0-1, "y2_pct": 0-1, "width": 0.5-3, "color": "#hex"}
- {"type": "dot_grid", "spacing_mm": 10-25, "dot_r_mm": 0.3-1.2, "color": "#hex", "alpha": 0.03-0.15}
- {"type": "glow", "x_pct": 0-1, "y_pct": 0-1, "radius_mm": 40-150, "color": "#hex", "alpha": 0.05-0.25}
- {"type": "rect", "x_pct": 0-1, "y_pct": 0-1, "w_mm": 20-200, "h_mm": 20-200, "color": "#hex", "radius": 0-10, "alpha": 0.03-0.15}
- {"type": "arch_pattern", "style": "building"/"grid"/"circles"/"diamonds", "color": "#hex", "alpha": 0.03-0.1}
- {"type": "corner_accent", "position": "top-left"/"top-right"/"bottom-left"/"bottom-right", "size_mm": 20-60, "color": "#hex", "width": 0.5-2}
- {"type": "frame_lines", "inset_mm": 5-15, "color": "#hex", "width": 0.3-1, "alpha": 0.1-0.3}

═══════════════════════════════════════════════════════════════
أيقونات محددة لكل سلايد (slide_icons)
═══════════════════════════════════════════════════════════════
أضف حقل "slide_icons" لكل سلايد — مصفوفة من الأيقونات المستخدمة:
available_icons:
  "building", "chart_up", "chart_bar", "money", "coin", "clock", "calendar",
  "location", "map_pin", "road", "people", "user", "star", "shield",
  "check", "alert", "arrow_right", "arrow_up", "target", "globe",
  "house", "key", "compass", "leaf", "diamond", "flag", "lightbulb",
  "gear", "wifi", "phone", "mail", "link", "download", "upload"

مثال: "slide_icons": ["building", "money", "chart_up"]

═══════════════════════════════════════════════════════════════
أنواع التخطيط (layout)
═══════════════════════════════════════════════════════════════
- "centered" → النص في المنتصف
- "split_lr" → نص يسار + صورة يمين
- "split_rl" → نص يمين + صورة يسار
- "cards" → بطاقات متناثرة
- "full_bleed" → صورة كاملة مع نص فوق
- "asymmetric" → تخطيط غير متناظر

═══════════════════════════════════════════════════════════════
أنواع العناوين (title_style)
═══════════════════════════════════════════════════════════════
- "top_bar" → شريط علوي بلون غامق مع عنوان أبيض
- "side_accent" → شريط جانبي مع عنوان بجانبه
- "floating_card" → بطاقة عائمة تحتوي العنوان
- "large_centered" → عنوان كبير في المنتصف

═══════════════════════════════════════════════════════════════
الإخراج المطلوب — JSON فقط
═══════════════════════════════════════════════════════════════
{
  "slides": [
    {
      "type": "cover|content|metrics|table|timeline|closing|comparison|quote|section_divider",
      "title": "العنوان بالعربي",
      "subtitle": "العنوان الفرعي",
      "bullets": ["نقطة1", "نقطة2"],
      "metrics": [{"label": "الوسم", "value": "القيمة"}],
      "table": [["رأس1", "رأس2"], ["صف1", "صف2"]],
      "content": "محتوى نصي",
      "projectName": "اسم المشروع",
      "slide_icons": ["building", "chart_up", "money"],
      "image_to_use": "cover_image|facade_right|facade_left|aerial_view|null",
      "design": {
        "mood": "dramatic|modern|luxury|warm|bold|minimal|playful",
        "background_style": "solid|gradient_v|gradient_h|radial_glow|split|geometric|wave|dark",
        "gradient_top_color": "#hex (إذا gradient_v)",
        "gradient_bottom_color": "#hex (إذا gradient_v)",
        "gradient_left_color": "#hex (إذا gradient_h)",
        "gradient_right_color": "#hex (إذا gradient_h)",
        "glow_x_pct": 0.0-1.0 (إذا radial_glow),
        "glow_y_pct": 0.0-1.0 (إذا radial_glow),
        "glow_radius_mm": 40-150 (إذا radial_glow),
        "glow_color": "#hex (إذا radial_glow)",
        "split_direction": "horizontal|vertical (إذا split)",
        "split_position_pct": 0.1-0.9 (إذا split),
        "wave_y_pct": 0.3-0.8 (إذا wave),
        "wave_amplitude_mm": 5-25 (إذا wave),
        "wave_wavelength_mm": 40-120 (إذا wave),
        "wave_color": "#hex (إذا wave)",
        "primary_color": "#7A0C0C",
        "secondary_color": "#C4A35A",
        "accent_color": "#F5F0EE",
        "bg_color": "#FFFFFF",
        "text_color": "#2D2D2D",
        "layout": "centered|split_lr|split_rl|cards|full_bleed|asymmetric",
        "title_style": "top_bar|side_accent|floating_card|large_centered",
        "card_style": "rounded_shadow|flat_border|glass|none",
        "bullet_style": "diamond|circle|bar",
        "decorative_elements": [
          {"type": "circle", "x_pct": 0.9, "y_pct": 0.1, "r_mm": 60, "color": "#C4A35A", "alpha": 0.08},
          {"type": "arch_pattern", "style": "building", "color": "#7A0C0C", "alpha": 0.05},
          {"type": "corner_accent", "position": "bottom-left", "size_mm": 40, "color": "#C4A35A", "width": 1.5},
          {"type": "frame_lines", "inset_mm": 10, "color": "#C4A35A", "width": 0.5, "alpha": 0.15}
        ]
      }
    }
  ]
}

مهم جداً:
1. كل سلايد لازم يكون تصميمه مختلف ومتنوع — لا تكرر نفس الألوان أو نفس الـ background_style
2. اتبع المتطلبات المحددة لكل نوع سلايد في الأقسام أعلاه
3. لا تضع خلفية بيضا أبداً — لازم يكون فيها لون أو تدرج أو زخرفة
4. العناصر الزخرفية تزيد جمالية التصميم — لا تخف من استخدامها"""


def _run_glm_batch_design(slides, project_name, user_id):
    """Call GLM in batches of 3 to design each slide. Returns modified slides list."""
    BATCH_SIZE = 3
    all_designed = []
    
    for batch_start in range(0, len(slides), BATCH_SIZE):
        batch = slides[batch_start:batch_start + BATCH_SIZE]
        if not batch:
            break
        
        batch_num = (batch_start // BATCH_SIZE) + 1
        print(f"  [Batch {batch_num}] Slides {batch_start+1}-{batch_start+len(batch)} of {len(slides)}")
        
        batch_specs = []
        for i, s in enumerate(batch):
            spec = {
                "slide_idx": batch_start + i + 1,
                "type": s.get('type', 'content'),
                "title": s.get('title', ''),
                "subtitle": s.get('subtitle', ''),
            }
            if s.get('bullets'):
                spec['bullets'] = s['bullets']
            if s.get('metrics'):
                spec['metrics'] = s['metrics']
            if s.get('table'):
                spec['table'] = s['table']
            if s.get('content'):
                c = str(s['content'])
                spec['content'] = c[:400] + ('...' if len(c) > 400 else '')
            if s.get('image_b64') or s.get('cover_image_b64') or s.get('facade_right_b64') or s.get('facade_left_b64') or s.get('aerial_view_b64'):
                spec['has_image'] = True
            batch_specs.append(spec)
        
        batch_request = "=== Project: %s ===\n\n=== Batch %d (%d slides) of %d ===\n" % (project_name, batch_num, len(batch), len(slides))
        batch_request += json.dumps(batch_specs, ensure_ascii=False, indent=2)
        batch_request += "\n\nDesign unique visual style for these slides only.\n"
        batch_request += "Return JSON only: array of slides with design spec for each."
        
        data, _ = call_zai_chat(PDF_DESIGN_PROMPT, batch_request, user_id, max_tokens=6000)
        
        if "choices" not in data or len(data["choices"]) == 0:
            print(f"  [WARN] Batch {batch_num} GLM failed")
            continue
        
        result_text = data["choices"][0]["message"]["content"].strip()
        match = re.search(r'\{[\s\S]*\}', result_text)
        if match:
            try:
                result = json.loads(match.group(0))
                batch_slides = result.get("slides", [])
                
                for j, designed in enumerate(batch_slides):
                    orig_idx = (batch_start + j)
                    if orig_idx < len(slides):
                        slides[orig_idx]['design'] = designed.get('design', {})
                        for key in ['title','subtitle','bullets','metrics','table','content']:
                            if key in designed and designed[key]:
                                slides[orig_idx][key] = designed[key]
                        all_designed.append(orig_idx)
                
                print(f"  [OK] Batch {batch_num}: {len(batch_slides)} slides designed")
            except Exception as e:
                print(f"  [WARN] Batch {batch_num} parse error: {e}")
        else:
            print(f"  [WARN] Batch {batch_num}: no JSON in response")
    
    for i, s in enumerate(slides):
        if i not in all_designed:
            s['design'] = _default_pdf_design(s.get('type', 'content'))
    
    return slides


# ════════════════════════════════════════════════════════════════════
# PDF DESIGN ONLY — returns designed slides (no file generation)
# ════════════════════════════════════════════════════════════════════

@app.route('/api/pdf-design', methods=['POST'])
def api_pdf_design():
    slides = request.json.get('slides')
    project_name = request.json.get('projectName', 'project')
    user_id = request.json.get('userId') or 'default_user'
    
    if not slides or not isinstance(slides, list):
        return jsonify({'error': 'slides array is required'}), 400
    
    print(f"\n[PDF-DESIGN] Designing {len(slides)} slides via GLM batches...")
    start_time = time.time()
    
    try:
        designed_slides = _run_glm_batch_design(slides, project_name, user_id)
        elapsed = time.time() - start_time
        print(f"  [OK] All slides designed in {elapsed:.1f}s")
        return jsonify({'success': True, 'slides': designed_slides})
    except Exception as e:
        print(f"  [FAIL] PDF design error: {str(e)}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ════════════════════════════════════════════════════════════════════
# PDF DESIGN STREAM — SSE: streams each slide as GLM designs it
# ════════════════════════════════════════════════════════════════════

@app.route('/api/pdf-design-stream', methods=['POST'])
def api_pdf_design_stream():
    from flask import Response
    slides = request.json.get('slides')
    project_name = request.json.get('projectName', 'project')
    user_id = request.json.get('userId') or 'default_user'
    
    if not slides or not isinstance(slides, list):
        return jsonify({'error': 'slides array is required'}), 400
    
    print(f"\n[PDF-STREAM] Streaming design for {len(slides)} slides...")
    
    def generate():
        BATCH_SIZE = 2
        total = len(slides)
        all_designed = []
        
        # Send total count first
        yield f"data: {json.dumps({'type':'start','total':total})}\n\n"
        
        for batch_start in range(0, total, BATCH_SIZE):
            batch = slides[batch_start:batch_start + BATCH_SIZE]
            if not batch:
                break
            
            batch_num = (batch_start // BATCH_SIZE) + 1
            batch_end = min(batch_start + BATCH_SIZE, total)
            
            # Send progress
            yield f"data: {json.dumps({'type':'progress','batch':batch_num,'current':batch_start+1,'to':batch_end,'of':total})}\n\n"
            
            try:
                # Build specs for this batch
                batch_specs = []
                for i, s in enumerate(batch):
                    spec = {
                        "slide_idx": batch_start + i + 1,
                        "type": s.get('type', 'content'),
                        "title": s.get('title', ''),
                        "subtitle": s.get('subtitle', ''),
                    }
                    if s.get('bullets'): spec['bullets'] = s['bullets']
                    if s.get('metrics'): spec['metrics'] = s['metrics']
                    if s.get('table'): spec['table'] = s['table']
                    if s.get('content'):
                        c = str(s['content'])
                        spec['content'] = c[:400] + ('...' if len(c) > 400 else '')
                    if s.get('image_b64') or s.get('cover_image_b64') or s.get('facade_right_b64') or s.get('facade_left_b64') or s.get('aerial_view_b64'):
                        spec['has_image'] = True
                    batch_specs.append(spec)
                
                batch_request = "=== Project: %s ===\n\n=== Batch %d (%d slides) of %d ===\n" % (project_name, batch_num, len(batch), total)
                batch_request += json.dumps(batch_specs, ensure_ascii=False, indent=2)
                batch_request += "\n\nDesign unique visual style for these slides only.\n"
                batch_request += "Return JSON only: array of slides with design spec for each."
                
                data, _ = call_zai_chat(PDF_DESIGN_PROMPT, batch_request, user_id, max_tokens=6000)
                
                if "choices" in data and len(data["choices"]) > 0:
                    result_text = data["choices"][0]["message"]["content"].strip()
                    match = re.search(r'\{[\s\S]*\}', result_text)
                    if match:
                        try:
                            result = json.loads(match.group(0))
                            batch_slides = result.get("slides", [])
                            
                            designed_in_batch = []
                            for j, designed in enumerate(batch_slides):
                                orig_idx = (batch_start + j)
                                if orig_idx < len(slides):
                                    slides[orig_idx]['design'] = designed.get('design', {})
                                    for key in ['title','subtitle','bullets','metrics','table','content']:
                                        if key in designed and designed[key]:
                                            slides[orig_idx][key] = designed[key]
                                    all_designed.append(orig_idx)
                                    designed_in_batch.append({
                                        "idx": orig_idx,
                                        "slide": slides[orig_idx]
                                    })
                            
                            # Send designed slides to frontend
                            yield f"data: {json.dumps({'type':'designed','slides':designed_in_batch})}\n\n"
                            continue
                        except Exception as e:
                            yield f"data: {json.dumps({'type':'error_batch','batch':batch_num,'msg':str(e)})}\n\n"
                
                # If GLM failed, send defaults
                fallback = []
                for i in range(len(batch)):
                    orig_idx = batch_start + i
                    if orig_idx < len(slides):
                        slides[orig_idx]['design'] = _default_pdf_design(slides[orig_idx].get('type', 'content'))
                        all_designed.append(orig_idx)
                        fallback.append({"idx": orig_idx, "slide": slides[orig_idx]})
                if fallback:
                    yield f"data: {json.dumps({'type':'designed','slides':fallback})}\n\n"
                    
            except Exception as e:
                yield f"data: {json.dumps({'type':'error_batch','batch':batch_num,'msg':str(e)})}\n\n"
        
        # Fill any missing with defaults
        for i, s in enumerate(slides):
            if i not in all_designed:
                s['design'] = _default_pdf_design(s.get('type', 'content'))
                yield f"data: {json.dumps({'type':'designed','slides':[{'idx':i,'slide':s}]})}\n\n"
        
        yield f"data: {json.dumps({'type':'done','total_designed':len(all_designed)})}\n\n"
    
    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


# ════════════════════════════════════════════════════════════════════
# LOGO ENDPOINT — serves the company logo as base64 data URI
# ════════════════════════════════════════════════════════════════════

@app.route('/api/logo')
def api_logo():
    from config.logo_data import LOGO_B64
    return jsonify({'logo': LOGO_B64})

# ════════════════════════════════════════════════════════════════════
# PDF GENERATION — renders PDF from (pre-)designed slides
# ════════════════════════════════════════════════════════════════════

@app.route('/api/export-pdf', methods=['POST'])
def api_export_pdf():
    slides_html = request.json.get('slidesHtml', '')
    project_name = request.json.get('projectName', 'project')
    
    if not slides_html:
        return jsonify({'error': 'slidesHtml is required'}), 400
    
    try:
        import time as _time
        from pathlib import Path
        project_root = Path(__file__).resolve().parent
        filename = f"{project_name}_{int(_time.time())}.pdf"
        output_path = os.path.join(str(project_root), 'outputs', filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        from config.fonts_data import FONT_LIGHT_B64, FONT_BOLD_B64
        from config.logo_data import LOGO_B64
        font_faces = ''
        for family, b64, mime, css_format, css_weight in [
            ('TheSansArabic-Light', FONT_LIGHT_B64, 'font/opentype', 'opentype', 'normal'),
            ('TheSansArabic-Bold', FONT_BOLD_B64, 'font/truetype', 'truetype', 'bold'),
        ]:
            font_faces += f"@font-face {{ font-family:'{family}'; src:url('data:{mime};base64,{b64}') format('{css_format}'); font-weight:{css_weight}; font-style:normal; font-display:swap; }}\n"
            font_faces += f"@font-face {{ font-family:'The Sans Arabic'; src:url('data:{mime};base64,{b64}') format('{css_format}'); font-weight:{css_weight}; font-style:normal; font-display:swap; }}\n"
        
        logo_tag = f'<img src="{LOGO_B64}" style="height:48px;width:auto;object-fit:contain;display:block">'
        slides_html = slides_html.replace('##LOGO##', logo_tag)
        slides_html = slides_html.replace('/manafe-logo.png', LOGO_B64)
        
        full_html = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head><meta charset="UTF-8"><style>
@page {{ size: 1280px 720px; margin: 0; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
{font_faces}
.slide {{ width: 1280px; height: 720px; direction: rtl; font-family: 'The Sans Arabic', 'TheSansArabic-Light', 'TheSansArabic-Bold', Tahoma, Arial, sans-serif; position: relative; overflow: hidden; page-break-after: always; page-break-inside: avoid; }}
.slide:last-child {{ page-break-after: auto; }}
img {{ max-width: 100%; max-height: 100%; object-fit: cover; }}
</style></head>
<body>
{slides_html}
</body>
</html>"""
        
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--font-render-hinting=none'])
            page = browser.new_page()
            page.set_content(full_html, wait_until='load')
            page.wait_for_timeout(500)
            page.pdf(
                path=output_path,
                width='1280px',
                height='720px',
                print_background=True,
                margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'},
                prefer_css_page_size=True,
            )
            browser.close()
        
        return jsonify({'url': f'/outputs/{filename}', 'filename': filename})
    except Exception as e:
        print(f"[PDF Export Error] {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/generate-pdf', methods=['POST'])
def api_generate_pdf():
    slides = request.json.get('slides')
    project_name = request.json.get('projectName', 'project')
    user_id = request.json.get('userId') or 'default_user'
    skip_design = request.json.get('skip_design', False)
    
    if not slides or not isinstance(slides, list):
        return jsonify({'error': 'slides array is required'}), 400
    
    print(f"\n[PDF] Generating PDF with {len(slides)} slides (skip_design={skip_design})...")
    start_time = time.time()
    
    try:
        if not skip_design:
            slides = _run_glm_batch_design(slides, project_name, user_id)
        else:
            print("  [INFO] Skipping GLM design — using pre-designed slides")
            for i, s in enumerate(slides):
                if not s.get('design') or len(s.get('design', {})) < 3:
                    s['design'] = _default_pdf_design(s.get('type', 'content'))
        
        from pdf_generator_html import generate_pdf
        
        filename = re.sub(r'[^a-zA-Z0-9_\-]', '_', project_name) + '.pdf'
        output_path = os.path.join(OUTPUT_DIR, filename)
        
        generate_pdf(slides, project_name, output_path)
        
        elapsed = time.time() - start_time
        print(f"  [OK] PDF generated in {elapsed:.1f}s → {filename}")
        return jsonify({'success': True, 'url': f'/outputs/{filename}', 'filename': filename})
        
    except Exception as e:
        print(f"  [FAIL] PDF error: {str(e)}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def _default_pdf_design(slide_type):
    defaults = {
        'cover': {'mood':'dramatic','background_style':'gradient_v','primary_color':'#7A0C0C',
                 'secondary_color':'#5A0808','accent_color':'#C4A35A','bg_color':'#7A0C0C',
                 'text_color':'#FFFFFF','layout':'centered','title_style':'large_centered'},
        'closing': {'mood':'dramatic','background_style':'gradient_v','primary_color':'#7A0C0C',
                   'secondary_color':'#5A0808','accent_color':'#C4A35A','bg_color':'#5A0808',
                   'text_color':'#FFFFFF','layout':'centered','title_style':'large_centered'},
        'content': {'mood':'modern','background_style':'solid','primary_color':'#7A0C0C',
                  'secondary_color':'#C4A35A','accent_color':'#F5F0EE','bg_color':'#FBFAF8',
                  'text_color':'#2D2D2D','layout':'split_rl','title_style':'top_bar',
                  'card_style':'rounded_shadow','bullet_style':'diamond'},
        'metrics': {'mood':'modern','background_style':'solid','primary_color':'#7A0C0C',
                   'secondary_color':'#C4A35A','accent_color':'#FBF6EE','bg_color':'#FBF6EE',
                   'text_color':'#2D2D2D','layout':'cards','title_style':'top_bar'},
        'table': {'mood':'minimal','background_style':'solid','primary_color':'#7A0C0C',
                  'secondary_color':'#C4A35A','accent_color':'#FAF7F2','bg_color':'#FAF7F2',
                  'text_color':'#2D2D2D','layout':'cards','title_style':'top_bar'},
    }
    d = defaults.get(slide_type, defaults['content'])
    d['decorative_elements'] = []
    return d


# ════════════════════════════════════════════════════════════════════
# PDF CHAT — AI-powered direct editing of PDF designs
# ════════════════════════════════════════════════════════════════════

PDF_CHAT_SYSTEM_PROMPT = """أنت مساعد ذكاء اصطناعي متخصص في تعديل وتصميم عروض PDF تقديمية لشركة "منافع الاقتصادية للعقار".

قدراتك:
1. تعديل نصوص سلايدات محددة (عنوان، نقاط، محتوى)
2. تغيير تصميم سلايدات (ألوان، خلفية، زخرفة)
3. تغيير مكان الصور على السلايدات
4. إعادة تصميم سلايد بالكامل
5. استخراج بيانات من الملفات المرفوعة
6. إضافة/حذف/تعديل مؤشرات أو جداول

الـ 4 صور المتاحة للمشروع:
- cover_image: غلاف المكان مع ناس سعوديين → تستخدم في Cover, Closing, فكرة المشروع
- facade_right: واجهة يمين → تستخدم في مميزات المشروع, المكونات, فرص الاستثمار
- facade_left: واجهة يسار → تستخدم في موقع المشروع, الربح التشغيلي, التكاليف
- aerial_view: واجهة من الأعلى → تستخدم في الملخص التنفيذي, الأرباح, المؤشرات, الجدول الزمني

قواعد الاستجابة:
- رد دائماً بـ JSON صالح
- لا تعدل إلا ما طلبه المستخدم (لا تغير كل شيء)
- احتفظ ببنية البيانات الصحيحة لكل سلايد
- إذا طلب تغيير صورة، استخدم image_to_use المناسب
- إذا طلب تغيير تصميم، عدّل حقل design فقط
- إذا طلب تعديل نص، عدّل الحقل المناسب (title, subtitle, bullets, content)

أنواع الإجراءات الممكنة:
1. "edit_text" → تعديل نص في سلايد محدد
2. "redesign" → إعادة تصميم سلايد (تغيير colors, background, decorations)
3. "change_image" → تغيير صورة سلايد (image_to_use)
4. "add_content" → إضافة محتوى (bullets, metrics, table rows)
5. "remove_content" → حذف محتوى
6. "reorder" → ترتيب الشرائح
7. "extract_data" → استخراج بيانات من ملف مرفوع
8. "full_redesign" → إعادة تصميم كامل للعرض

صيغة JSON للرد:
{
  "action": "نوع_الإجراء",
  "message": "رسالة للمستخدم بالعربي توضح ما تم",
  "updated_slides": [
    {
      "slide_idx": رقم_السلايد,
      "changes": { "الحقل_المعدل": "القيمة_الجديدة" }
    }
  ]
}

مهم: رد بـ JSON فقط بدون markdown."""


@app.route('/api/pdf-chat', methods=['POST'])
def api_pdf_chat():
    message = request.json.get('message', '')
    slides = request.json.get('slides', [])
    project_name = request.json.get('projectName', 'project')
    user_id = request.json.get('userId') or 'default_user'
    uploaded_file = request.json.get('uploadedFile', None)  # base64 file data
    uploaded_filename = request.json.get('uploadedFilename', '')
    
    if not message:
        return jsonify({'error': 'Message is required'}), 400
    
    print(f"\n[PDF Chat] Message: {message[:100]}")
    
    try:
        # Build context with current slides summary
        context_parts = []
        if slides:
            slides_summary = []
            for i, s in enumerate(slides):
                ss = f"Slide {i+1} [{s.get('type','?')}]: {s.get('title','')}"
                if s.get('design'):
                    d = s['design']
                    ss += f" | mood={d.get('mood','?')} bg={d.get('background_style','?')} colors={d.get('primary_color','?')}"
                if s.get('image_to_use'):
                    ss += f" | image={s['image_to_use']}"
                if s.get('bullets'):
                    ss += f" | {len(s['bullets'])} bullets"
                slides_summary.append(ss)
            context_parts.append("CURRENT SLIDES:\n" + '\n'.join(slides_summary))
        
        # Add uploaded file info
        if uploaded_file and uploaded_filename:
            context_parts.append(f"\nUPLOADED FILE: {uploaded_filename}")
            context_parts.append("(File is available for analysis)")
        
        context_parts.append(f"\nPROJECT: {project_name}")
        context_parts.append(f"\nUSER REQUEST: {message}")
        
        user_content = '\n\n'.join(context_parts)
        
        data, _ = call_zai_chat(PDF_CHAT_SYSTEM_PROMPT, user_content, user_id, max_tokens=6000)
        
        if "choices" not in data or len(data["choices"]) == 0:
            raise Exception("GLM failed")
        
        result_text = data["choices"][0]["message"]["content"].strip()
        
        match = re.search(r'\{[\s\S]*\}', result_text)
        if not match:
            return jsonify({
                'success': True,
                'data': {'action': 'chat', 'response': result_text}
            })
        
        result = json.loads(match.group(0))
        action = result.get('action', 'chat')
        response_msg = result.get('message', result_text)
        updated_slides = result.get('updated_slides', [])
        
        # Apply changes to slides
        if updated_slides and slides:
            for update in updated_slides:
                idx = update.get('slide_idx')
                changes = update.get('changes', {})
                if idx is not None and 0 <= idx < len(slides):
                    for key, value in changes.items():
                        slides[idx][key] = value
                    print(f"  [OK] Updated slide {idx}: {list(changes.keys())}")
        
        print(f"  [OK] PDF Chat response: {action}")
        return jsonify({
            'success': True,
            'data': {
                'action': action,
                'response': response_msg,
                'slides': slides if updated_slides else None
            }
        })
        
    except Exception as e:
        print(f"  [FAIL] PDF Chat error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/pdf-chat/upload', methods=['POST'])
def api_pdf_chat_upload():
    """Handle file upload for PDF chat — extract data from uploaded files."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    uploaded_file = request.files['file']
    if not uploaded_file.filename:
        return jsonify({'error': 'No filename'}), 400
    
    try:
        filename = secure_filename(uploaded_file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        uploaded_file.save(filepath)
        
        # Convert to base64 for AI processing
        import base64
        with open(filepath, 'rb') as f:
            file_b64 = base64.b64encode(f.read()).decode('utf-8')
        
        # Get file info
        file_ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        file_size = os.path.getsize(filepath)
        
        print(f"[Upload] {filename} ({file_size} bytes)")
        
        return jsonify({
            'success': True,
            'data': {
                'filename': filename,
                'file_b64': file_b64,
                'file_size': file_size,
                'file_type': file_ext,
                'filepath': filepath
            }
        })
        
    except Exception as e:
        print(f"  [FAIL] Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    # Parse command line port arguments
    PORT = int(os.environ.get("PORT", 7860))
    for i in range(len(sys.argv)):
        if sys.argv[i] == "--port" and i + 1 < len(sys.argv):
            PORT = int(sys.argv[i+1])
        elif sys.argv[i] == "--server.port" and i + 1 < len(sys.argv):
            PORT = int(sys.argv[i+1])
        elif sys.argv[i].startswith("--server.port="):
            PORT = int(sys.argv[i].split("=")[1])
            
    print("\n" + "="*39)
    print(f"  [NET] Server starting on port {PORT}")
    print(f"  [URL] http://127.0.0.1:{PORT}")
    print("="*39 + "\n")
    
    # Auto-open browser in background if local
    if not os.environ.get("SPACE_ID") and not os.environ.get("DOCKER_CONTAINER"):
        try:
            import threading
            def open_browser():
                time.sleep(1.5)
                webbrowser.open(f"http://127.0.0.1:{PORT}")
            threading.Thread(target=open_browser, daemon=True).start()
        except Exception as e:
            print("Could not auto-open browser:", e)
    
    # Use debug mode only when not on HF Spaces to avoid restart loops
    is_hf = bool(os.environ.get("SPACE_ID"))
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
