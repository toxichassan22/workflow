import sys
import json
from app import app, db, build_design_rules, call_zai_chat, extract_chat_content
from flask import g

sys.stdout.reconfigure(encoding='utf-8')

# Mock Flask request context
with app.test_request_context():
    g.tenant_id = '809bfb86-d0d6-4dd1-a37f-30d1e8e9374f'
    g.user_id = 'test-user-id'
    g.user_name = 'Test User'

    print("Tenant ID:", g.tenant_id)
    branding = db.get_branding(g.tenant_id) or {}
    print("Branding colors in DB:", branding.get('primary_color'), branding.get('accent_color'))
    
    dynamic_rules = build_design_rules(branding)
    print("\n--- DYNAMIC RULES ---")
    print(dynamic_rules)
    print("----------------------\n")
    
    # Let's mock a simple slide HTML (with blue theme style)
    slide_html = """
    <div class="slide" style="width:1280px;height:720px;background:#f4f9fc;color:#333;position:relative;font-family:'The Sans Arabic';">
      <div style="position:absolute;top:0;right:0;left:0;height:56px;background:#fff;border-bottom:2px solid #3b6e91;display:flex;align-items:center;padding:0 20px;">
        <span style="font-size:16px;font-weight:600;color:#3b6e91;">العنوان الرئيسي للشرائح</span>
      </div>
      <div style="padding: 100px 50px;">
        <h1 style="color:#3b6e91;">شريحة تجريبية</h1>
        <p>هذا النص تجريبي للشريحة.</p>
      </div>
    </div>
    """
    
    system_prompt = f"""{dynamic_rules}

مهمتك: تعديل شريحة HTML واحدة فقط بناءً على طلب المستخدم، أو الرد على استفساراته.

قواعد الاستجابة:
يجب أن تكون إجابتك بصيغة JSON صالحة تحتوي على حقلين:
1. "html": كود HTML الكامل للشريحة المعدلة داخل div class="slide" (أو قيمة null إذا لم يكن هناك تعديل أو تغيير في الشريحة).
2. "response": رسالة ودية وذكية باللغة العربية تشرح فيها ما قمت بتعديله بالتفصيل، أو تسأل المستخدم لتوضيح طلبه إذا كان غامضاً، أو تجيب على سؤاله.

مثال للاستجابة:
{{
  "html": "<div class=\"slide\">...</div>",
  "response": "لقد قمت بتغيير ألوان الشريحة لتطابق هوية الشركة، وتكبير حجم الخط للعناوين الرئيسية لتسهيل القراءة."
}}

⚠️ قواعد صارمة:
- لا تضف أي نص خارج كتلة الـ JSON.
- يجب أن يبدأ ردك بـ {{ وينتهي بـ }}.
- حافظ دائماً على هوية وألوان الشركة والخطوط المحددة في قواعد التصميم.
- لا تضف أي صور خارجية إلا إذا كانت من الصور المتاحة للمشروع.
"""
    
    user_msg = f"الشريحة الحالية (مقدمة):\n\n{slide_html}\n\nالطلب: أضف نقطة جديدة تحت العنوان: 'هذه شريحة زرقاء'"
    
    print("Calling GLM...")
    response = call_zai_chat(system_prompt, user_msg, max_tokens=6000)
    print("\n--- RAW RESPONSE ---")
    print(json.dumps(response, ensure_ascii=False, indent=2))
    print("--------------------\n")
    
    reply = extract_chat_content(response, "DESIGNER-CHAT").strip()
    print("\n--- EXTRACTED REPLY ---")
    print(reply)
    print("-----------------------\n")
