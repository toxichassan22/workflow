

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Site-analysis prompt construction. Extracted from 11a (file-size budget) and
# bilingual: the stored project_language choice decides which prose the model
# authors — Arabic by default, English when the project picked English.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def build_site_analysis_prompts(project_data, offer_lang):
    """Return (system_prompt, user_prompt) for the flowing site analysis."""
    data_block = json.dumps(project_data, ensure_ascii=False, indent=2)
    if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
        system_prompt = (
            'You are a meticulous real-estate site analyst. Produce a smooth English analysis '
            'that covers every category present in the data without skipping any, and without '
            'inventing information that is not there.\n\n'
            + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
        )
        prompt = f"""Write a professional, detailed English analysis of a real-estate project site based only on the data below.

Required:
- Write flowing, connected English paragraphs — do not collapse the analysis into a quick summary or generic phrases.
- Cover every category that has data below; skip none of them.
- The analysis must briefly reference each of the following where available, roughly in this order:
  1. Project type, idea, description, goal, current stage, and target audience.
  2. Initial features, strengths, and suitable investment opportunities.
  3. The nature of the site, its strategic position, detailed address, and coordinates.
  4. Population density and its source, when available.
  5. Main roads and the nature of access.
  6. Nearby landmarks and city landmarks, citing distances and drive times as evidence, not as the main topic.
  7. Catchment areas and zones of influence, when available.
- Tie every category to how suitable the site is for the project type, idea, goal, stage, target audience, features, and opportunities.
- Explain relationships and conclusions in detail without repeating the same fact.
- Invent nothing that is not in the data.
- If a piece of information is unavailable, never mention it rather than fabricating it.
- Use no headings or bullet points in the final text; return a smooth English analysis ready for presentation.

Project and site data:
{data_block}"""
        return system_prompt, prompt

    system_prompt = 'أنت محلل مواقع عقارية دقيق. أخرج تحليلًا عربيًا سلسًا يغطي كل فئة متاحة من البيانات دون تخطي أي منها، ودون اختلاق معلومات غير موجودة.'
    prompt = f"""اكتب تحليلًا عربيًا احترافيًا ومفصلًا لموقع مشروع عقاري اعتمادًا على البيانات التالية فقط.

المطلوب:
- اكتب تحليلًا عربيًا مسترسلًا في فقرات مترابطة، ولا تختصره إلى ملخص سريع أو عبارات عامة.
- غطِّ جميع الفئات التالية الموجودة في البيانات ولا تتخطى أي فئة فيها بيانات.
- يجب أن يتضمن التحليل إشارة مختصرة إلى كل ما يلي متاح منه، بالترتيب التالي قدر الإمكان:
  1. نوع المشروع وفكرته ووصفه والهدف منه ومرحلته الحالية والجمهور المستهدف.
  2. المميزات الأولية ونقاط القوة وفرص الاستثمار المناسبة للمشروع.
  3. طبيعة الموقع وموقعه الاستراتيجي والعنوان التفصيلي والإحداثيات.
  4. الكثافة السكانية ومصدرها إن وجدت.
  5. الطرق الرئيسية وطبيعة الوصول.
  6. المعالم القريبة ومعالم المدينة، مع ذكر المسافات وأوقات القيادة كدليل لا كموضوع رئيسي.
  7. نطاق التأثير ومناطق الالتقاط إن وجدت.
- اربط كل فئة بصلاحية الموقع لنوع المشروع وفكرته وهدفه ومرحلته والجمهور المستهدف ومميزات المشروع وفرصه.
- اشرح العلاقة والاستنتاجات بالتفصيل دون تكرار نفس المعلومة.
- لا تخترع أي معلومة غير موجودة في البيانات.
- إذا كانت معلومة غير متوفرة، لا تذكرها أبدًا بدلًا من اختلاقها.
- لا تستخدم عناوين أو نقاط تعداد في النص النهائي؛ أعد تحليلًا عربيًا سلسًا جاهزًا للعرض.

بيانات المشروع والموقع:
{data_block}"""
    return system_prompt, prompt
