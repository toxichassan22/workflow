# -*- coding: utf-8 -*-
"""Run ONE real evidence-extraction stage exactly like _extract_full_regulation_evidence does."""
import _bootstrap  # noqa: F401  (repo-root sys.path wiring)
import sys, os, json, tempfile, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\workflow')

import db
db.DB_PATH = os.path.join(tempfile.mkdtemp(), 'v.db')
import app as A

site_facts = {
    'area_sqm': 600, 'zoning_code': 'س ف', 'land_use': 'سكني فلل',
    'city': 'جدة', 'project_type': 'فيلا سكنية', 'building_type': 'فيلا',
}

# Same entry point the pipeline uses
pkg, warns = A.search_official_regulations_evidence('سكني فلل ارتدادات', site_facts)
doc2 = next(d for d in pkg['documents'] if d['name'] == 'اشتراطات2.pdf')
tables2 = [t for t in pkg['table_pages'] if t['name'] == 'اشتراطات2.pdf']

chunks = A.split_regulation_context(doc2['context'])
print(f'doc2 context -> {len(chunks)} chunks; table pages={len(tables2)}')

# Locate the chunk holding the setbacks article (the /6 clause page)
target_chunk = None
target_idx = -1
for i, ch in enumerate(chunks):
    if 'رتداد األمامي' in ch or 'الرتداد األمامي' in ch:
        target_chunk = ch
        target_idx = i
        break
print('setbacks clause in chunk index:', target_idx)
pages_in_chunk = A.regulation_context_page_numbers(target_chunk or '')
print('pages in that chunk:', sorted(pages_in_chunk))

chunk_tables = [t for t in tables2 if t.get('page') in pages_in_chunk]
print('table pages attached to this chunk:', [t['page'] for t in chunk_tables])

# Reproduce run_stage() verbatim
source_name = 'اشتراطات2.pdf'
base_prompt = (
    "أنت مستخرج أدلة تنظيمية من ملف واحد كامل فقط. أعد JSON فقط بهذا الشكل: "
    '{"evidence":[{"field":"","value":"","page":0,"quote":""}],'
    '"uncertainties":[]} '
    f"المصدر الوحيد هو {source_name}. لا تستخدم أي معلومة من ملف آخر. "
    "اقرأ الجزء الحالي من المحتوى الكامل وصور الجداول المرفقة، واستخرج القواعد التي تنطبق على حقائق الموقع. "
    "يمكن حفظ رقم الصفحة داخليًا داخل evidence فقط لتتبع الدليل، ولا تضعه في أي قيمة اشتراط أو نص موجّه للمستخدم. "
    "أرقام الجداول تُقرأ من الصور المرفقة لأن النص قد يكون معكوسًا."
)
parts, rw = A.render_regulation_table_pages(chunk_tables, dpi=A.REGULATION_EVIDENCE_TABLE_DPI)
print('rendered image parts:', sum(1 for p in parts if p['type'] == 'image_url'), 'warnings:', rw)

user_content = [{
    'type': 'text',
    'text': base_prompt + f'\nهذا الجزء {target_idx + 1} من {len(chunks)} من المحتوى الكامل للملف.'
            + '\nحقائق الموقع المستخرجة من الكروكي:\n'
            + json.dumps(site_facts, ensure_ascii=False)
            + '\nجزء المحتوى الحالي:\n' + target_chunk
}] + parts

result, cap, error = A._run_land_json_stage(
    'verify-setbacks', base_prompt, user_content,
    A.REGULATION_EVIDENCE_MAX_TOKENS, A.REGULATION_EVIDENCE_MIN_TOKENS,
    A.REGULATION_EVIDENCE_MAX_TOKENS * 2,
)
print('=== STAGE RESULT ===')
print('error:', error, '| cap:', cap)
print(json.dumps(result, ensure_ascii=False, indent=2)[:6000])
