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
            'You are a senior real-estate investment and development strategist. Produce a compelling, '
            'authoritative, and value-focused English analysis that highlights the site’s strategic strengths, '
            'connectivity, and commercial opportunities, without inventing facts not supported by the data.\n\n'
            + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
        )
        prompt = f"""Write an authoritative, strategically balanced, and detailed English investment analysis of a real-estate project site based on the data below.

Required Tone & Objectives:
- Adopt a balanced, institutional investment tone: blend professional objectivity with compelling value articulation. Highlight genuine competitive advantages and connectivity without promotional hype, superlatives, or cynical skepticism.
- Speak as a senior real-estate investment strategist presenting to discerning investors: articulate how the site's factual attributes, road connectivity, and catchment dynamics reinforce the project's feasibility and appeal.
- Avoid both extremes: do not diminish the location with cynical or defensive warnings, nor inflate it with hollow marketing buzzwords. Keep the analysis grounded, credible, and strategically compelling.
- Write flowing, connected English paragraphs — do not collapse the analysis into a quick summary or generic phrases.
- Cover every category that has data below; skip none of them.
- The analysis must reference each of the following where available:
  1. Project type, idea, description, goal, current stage, and target audience, connecting them to the site's promise.
  2. Strategic features, strengths, and lucrative investment opportunities enabled by the location.
  3. The nature of the site, its prime positioning, detailed address, and coordinates.
  4. Population density and catchment demographics, framing them as a solid base of potential footfall and demand.
  5. Main access arteries, highlighting ease of transit and reach.
  6. Nearby landmarks and city hubs, citing travel times and distances as proof of prime connectivity and synergy.
  7. Catchment areas and influence zones, emphasizing market coverage.
- Tie every category to how the site empowers and enhances the project type, concept, and commercial viability.
- Invent no fictional facts or fabricated landmarks not present in the data.
- Use no headings or bullet points in the final text; return a polished, flowing English analysis ready for presentation.

Project and site data:
{data_block}"""
        return system_prompt, prompt

    system_prompt = (
        'أنت خبير ومستشار استراتيجي أول في التطوير والاستثمار العقاري. مهمتك إعداد تحليل استثماري '
        'احترافي ومقنع يُبرز القيمة الاستراتيجية للموقع ونقاط قوته التنافسية وتكامله مع أهداف المشروع، '
        'بأسلوب استثماري رصين وجذاب يخدم العرض الاستثماري دون اختلاق معطيات غير موجودة.'
    )
    prompt = f"""اكتب تحليلًا عقاريًا استثماريًا احترافيًا ومفصلًا لموقع المشروع استنادًا إلى البيانات المرفقة أدناه.

النبرة والأسلوب المطلوب:
- اعتمد نبرة استثمارية متوازنة ورصينة تجمع بين الواقعية المهنية والجاذبية الاستثمارية؛ ركّز على إبراز المزايا التنافسية والقيمة المضافة الحقيقية للموقع دون مبالغة إنشائية أو إفراط دعائي، ودون لغة تشكيكية جافة.
- تحدث بصوت مستشار تطوير واستثمار عقاري مؤسسي يخاطب مستثمرين وأصحاب قرار: حلل الموقع بموضوعية إيجابية ووقار مهني يرتكز على الأرقام والمعطيات الواقعية، موضحاً كيف يخدم الموقع أهداف المشروع ومكوناته.
- ابتعد عن التطرفين: لا تستخدم نبرة تشكيكية دفاعية تقلل من قيمة الموقع أو تشكك في المعالم، وتجنب في نفس الوقت عبارات المديح التسويقي الإنشائي المبالغ فيه.
- صغ المعطيات الواقعية (مثل شبكة المحاور والطرق، أوقات القيادة، المعالم القريبة، ومناطق الالتقاط) في سياق تحليلي رصين يبرز سهولة الوصول، والربط الحيوي، والعمق الجغرافي لقاعدة العملاء والزوار المتوقعة.
- اكتب تحليلًا عربيًا مسترسلًا في فقرات مترابطة وثرية ومهنية تليق بعرض استثماري رفيع، دون عناوين أو نقاط تعداد.
- غطِّ الفئات المتاحة في البيانات:
  1. نوع المشروع وفكرته وأهدافه والجمهور المستهدف وتوافقه مع بيئة الموقع الحيوية.
  2. المزايا التنافسية ونقاط القوة والفرص الاستثمارية الحقيقية التي يتيحها الموقع.
  3. الموقع الاستراتيجي والعنوان التفصيلي ومحيطه الجغرافي.
  4. الكثافة السكانية ومناطق التأثير بوصفها قاعدة داعمة للطلب والحركة.
  5. شبكة الطرق والمحاور الرئيسية وسلاسة الوصول للموقع.
  6. المعالم الحيوية ومعالم المدينة القريبة، موظفاً أوقات القيادة والمسافات كبرهان على حيوية النطاق وسهولة الاتصال.
- اربط كل عنصر بمدى تعزيزه لجاذبية المشروع ونجاح مرافقه وأنشطته الاستثمارية.
- التزم بالبيانات المتاحة دون اختلاق معالم وهمية، مع توظيف البيانات الواقعية برؤية استثمارية متزنة ورصينة.

بيانات المشروع والموقع:
{data_block}"""
    return system_prompt, prompt
