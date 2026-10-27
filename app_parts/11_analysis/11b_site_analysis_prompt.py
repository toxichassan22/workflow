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
        prompt = f"""Write an authoritative, strategically positive, and detailed English investment analysis of a real-estate project site based on the data below.

Required Tone & Objectives:
- Maintain an encouraging, positive, and inspiring tone throughout the analysis: focus on maximizing strengths, emphasizing the site's vibrant potential, and framing every feature as a compelling investment opportunity.
- Adopt the confident, persuasive tone of a senior real-estate investment consultant presenting to decision-makers and investors.
- Highlight the site's competitive advantages, connectivity, and value drivers for the intended project uses.
- Avoid cynical, defensive, or overly cautionary phrasing (do not debate data points, dispute road measurements, or diminish the site's potential). Instead, frame the location's attributes, road network, and nearby amenities constructively around market appeal, accessibility, and catchment strength.
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
- كن إيجابياً ومحفزاً ومشجعاً في تحليلك بالكامل: ركّز على تعظيم نقاط القوة، وإبراز المقومات الواعدة للموقع وجاذبيته العالية، وصياغة كل ميزة كفرصة استثمارية قوية ومقنعة للعميل والمستثمر.
- تحدث بصوت مستشار تطوير عقاري استراتيجي يخاطب المستثمرين وأصحاب القرار؛ ركّز على إبراز المزايا التنافسية، وقوة الموقع الاستراتيجي، وفرص النمو والقيمة المضافة التي يمنحها الموقع للمشروع.
- ابتعد تماماً عن النبرة التشكيكية أو التحذيرية المفرطة أو لغة التدقيق الدفاعية السلبية (تجنب تماماً عبارات مثل "لا يثبت انتقال الطلب"، "ليست دليلاً على النجاح"، أو التشكيك في المعالم واختلاف التسميات).
- صغ المعطيات الواقعية (مثل شبكة المحاور والطرق، أوقات القيادة، المعالم القريبة، ومناطق الالتقاط) في سياق تعزيز سهولة الوصول، والربط الحيوي، واتساع قاعدة العملاء والزوار المستهدفة.
- اكتب تحليلًا عربيًا مسترسلًا في فقرات مترابطة وثرية ومهنية تليق بعرض استثماري رفيع، دون عناوين أو نقاط تعداد.
- غطِّ الفئات المتاحة في البيانات:
  1. نوع المشروع وفكرته وأهدافه والجمهور المستهدف وتوافقه مع بيئة الموقع الحيوية.
  2. المزايا التنافسية ونقاط القوة والفرص الاستثمارية الواعدة التي يتيحها الموقع.
  3. الموقع الاستراتيجي والعنوان التفصيلي ومحيطه الجغرافي.
  4. الكثافة السكانية ومناطق التأثير بوصفها قاعدة داعمة للطلب والحركة.
  5. شبكة الطرق والمحاور الرئيسية وسلاسة الوصول للموقع.
  6. المعالم الحيوية ومعالم المدينة القريبة، موظفاً أوقات القيادة والمسافات كبرهان على حيوية النطاق وسهولة الاتصال.
- اربط كل عنصر بمدى تعزيزه لجاذبية المشروع ونجاح مرافقه وأنشطته الاستثمارية.
- التزم بالبيانات المتاحة دون اختلاق معالم وهمية، مع توظيف البيانات الواقعية بإيجابية ورؤية استثمارية داعمة للمشروع.

بيانات المشروع والموقع:
{data_block}"""
    return system_prompt, prompt
