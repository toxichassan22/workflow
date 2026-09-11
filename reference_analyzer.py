"""
Reference Image Analyzer.
Uses Gemini Vision (via OpenRouter) to analyze a reference design image
and extract color palette, design style, and layout type.
"""

import os
import base64
import json
import re
import requests

OPENROUTER_BASE = 'https://openrouter.ai/api/v1'
VISION_MODEL = 'google/gemini-3.1-flash-image-preview'


def encode_image_to_base64(image_path):
    """Read an image file and return a base64 data URI."""
    with open(image_path, 'rb') as f:
        img_data = base64.b64encode(f.read()).decode('utf-8')

    ext = os.path.splitext(image_path)[1].lower()
    mime = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
    }.get(ext, 'image/png')

    return f"data:{mime};base64,{img_data}"


def _extract_reference_metering(data, model_name):
    """Copy generation id, tokens and direct response cost before content parsing."""
    metering = {'generation_id': None, 'usage': {}, 'model': model_name,
                'cost_usd': None, 'cost_raw': None}
    try:
        generation_id = data.get('id') if isinstance(data, dict) else None
        metering['generation_id'] = generation_id if isinstance(generation_id, str) and generation_id else None
        usage = data.get('usage') if isinstance(data, dict) else None
        if isinstance(usage, dict):
            def _num(value):
                try:
                    return int(value or 0)
                except (TypeError, ValueError):
                    return 0

            metering['usage'] = {
                'prompt_tokens': _num(usage.get('prompt_tokens')),
                'completion_tokens': _num(usage.get('completion_tokens')),
                'total_tokens': _num(usage.get('total_tokens')),
            }
            for key in ('cost', 'total_cost'):
                raw_value = usage.get(key)
                if raw_value is None or isinstance(raw_value, bool):
                    continue
                try:
                    from decimal import Decimal
                    import math as _math
                    if isinstance(raw_value, float) and (not _math.isfinite(raw_value)):
                        continue
                    amount = Decimal(str(raw_value).strip())
                    if not amount.is_finite() or amount < 0:
                        continue
                    metering['cost_usd'] = float(amount)
                    metering['cost_raw'] = str(raw_value).strip()
                    metering['usage']['cost_usd'] = float(amount)
                    metering['usage']['cost_raw'] = str(raw_value).strip()
                    break
                except Exception:
                    continue
    except Exception:
        pass
    return metering


def analyze_reference_image(image_path, openrouter_key, on_metering=None):
    """
    Analyze a reference design image using Gemini Vision.
    Returns (result_dict, metering_dict) where metering carries the provider
    generation id and token usage so the caller can record the spend.
    When on_metering is supplied it is invoked with the metering dict
    immediately after the provider response arrives and before content
    parsing, so a paid response with invalid content never loses its cost.
    """
    if not openrouter_key:
        raise ValueError("OpenRouter API key is required for image analysis")

    if not os.path.exists(image_path):
        raise ValueError(f"Image not found: {image_path}")

    data_uri = encode_image_to_base64(image_path)

    prompt = """حلل هذا التصميم المرجعي واستخرج المعلومات التالية:

1. لوحة الألوان (hex codes للـ 4-5 ألوان رئيسية):
   - primary: اللون الرئيسي للعناوين والأزرار
   - secondary: لون أغمق للتدرجات
   - accent: لون مميز للزخارف والتفاصيل
   - background: لون الخلفية
   - text: لون النص

2. نمط التصميم (اختر واحد):
   - modern: عصري نظيف
   - classic: كلاسيكي أنيق
   - minimal: بسيط بمساحات بيضاء
   - luxury: فاخر بتدرجات ذهبية
   - corporate: مؤسسي احترافي
   - nature: طبيعي بألوان ترابية

3. نوع التخطيط (اختر واحد):
   - grid: شبكة
   - cards: بطاقات
   - timeline: خط زمني
   - dashboard: لوحة معلومات

4. نمط البطاقات (اختر واحد):
   - bordered: بحدود رفيعة
   - shadow: بظلال
   - flat: مسطحة
   - gradient: بتدرجات

5. نمط الهيدر (اختر واحد):
   - minimal: بسيط
   - ornate: مزخرف
   - none: بدون هيدر

أعد JSON فقط بالصيغة:
{
  "colors": {
    "primary": "#hexcode",
    "secondary": "#hexcode",
    "accent": "#hexcode",
    "background": "#hexcode",
    "text": "#hexcode"
  },
  "design_style": "modern|classic|minimal|luxury|corporate|nature",
  "layout_type": "grid|cards|timeline|dashboard",
  "card_style": "bordered|shadow|flat|gradient",
  "header_style": "minimal|ornate|none",
  "notes": "ملاحظات إضافية عن الستايل بالعربي"
}

اكتب JSON فقط بدون أي شرح إضافي."""

    headers = {
        "Authorization": f"Bearer {openrouter_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com",
        "X-Title": "Real Estate Proposal Generator - Reference Analyzer"
    }

    payload = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}}
            ]
        }],
        "modalities": ["text"],
        "max_tokens": 1000,
    }

    response = requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers=headers,
        json=payload,
        timeout=60
    )
    data = response.json()
    metering = _extract_reference_metering(data, VISION_MODEL)
    if callable(on_metering):
        try:
            on_metering(dict(metering))
        except Exception:
            pass

    if 'error' in data:
        err = data['error']
        msg = err.get('message', str(err)) if isinstance(err, dict) else str(err)
        raise Exception(f"Vision API error: {msg}")

    if 'choices' not in data or not data['choices']:
        raise Exception("Vision API returned no choices")

    content = data['choices'][0].get('message', {}).get('content', '')
    if not content:
        raise Exception("Vision API returned empty content")

    # Extract JSON from response
    json_match = re.search(r'\{[\s\S]*\}', content)
    if not json_match:
        raise Exception("No JSON in vision API response")

    result = json.loads(json_match.group())
    return result, metering
