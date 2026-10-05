# ---------------------------------------------------------------------------
# English translation pass for site-enrichment labels.
#
# Google's Maps APIs keep Arabic display names for places that have no stored
# English name, so an English project still receives Arabic labels from Places,
# Directions, Roads and curated geocoding. One batched text-model call
# translates every remaining Arabic label instead of a call per name. Any
# failure maps nothing, so callers can apply the returned dict unconditionally —
# untranslated values then still get rendered in English by the slide-prompt
# notes at authoring time.
# ---------------------------------------------------------------------------

_SITE_LABEL_ARABIC_RE = re.compile('[\\u0600-\\u06FF]')


def translate_site_labels_en(values, project_data=None, tenant_id=None):
    """Translate Arabic site labels to English in one batched model call.

    `values` is an iterable of raw strings (landmark/road names, categories,
    a formatted address). Returns {original: english} covering only values
    that contained Arabic script and came back with a usable translation;
    malformed or short responses map nothing.
    """
    unique = []
    for raw in values or []:
        text = str(raw or '').strip()
        if text and _SITE_LABEL_ARABIC_RE.search(text) and text not in unique:
            unique.append(text)
    if not unique:
        return {}
    response = call_text_chat(
        'You translate Saudi site/location data into clear professional English '
        'for a real-estate proposal. Return ONLY a JSON array of strings in the '
        'exact same order and length as the input. Translate or transliterate '
        'place, road, city and category names faithfully — use the well-known '
        'English name when one exists («مطار الملك عبدالعزيز الدولي» = "King '
        'Abdulaziz International Airport", «طريق الملك فهد» = "King Fahd Road") — '
        'and keep every number, code and coordinate exact. Never invent content.',
        json.dumps(unique, ensure_ascii=False),
        max_tokens=4000,
        usage_ctx=_usage_ctx('site', project_data, tenant_id=tenant_id),
    )
    content = ''
    try:
        choices = (response or {}).get('choices') or []
        content = str((choices[0].get('message') or {}).get('content') or '') if choices else ''
    except (AttributeError, IndexError, TypeError):
        content = ''
    parsed = None
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        for pattern in (r'\[[\s\S]*\]', r'\{[\s\S]*\}'):
            match = re.search(pattern, content)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except (json.JSONDecodeError, ValueError):
                    parsed = None
                if parsed is not None:
                    break
    if isinstance(parsed, dict):
        # Models occasionally wrap the array: {"translations": [...]}.
        parsed = parsed.get('translations') or parsed.get('items') or parsed.get('results')
    if not isinstance(parsed, list) or len(parsed) != len(unique):
        return {}
    mapping = {}
    for source, english in zip(unique, parsed):
        english = str(english or '').strip()
        if english:
            mapping[source] = english
    return mapping
