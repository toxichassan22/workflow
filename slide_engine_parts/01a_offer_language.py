

# ---------------------------------------------------------------------------
# Offer language — detection, the stored per-project choice and resolution.
#
# Every deck/analysis prompt resolves its output language through
# resolve_offer_lang().  Order of precedence:
#   1. an explicit offer_lang argument (a caller that already knows),
#   2. the project's own stored choice (project_language, picked when the
#      project was created; offer_lang/offerLang/projectLanguage aliases are
#      accepted so older payloads keep working),
#   3. content detection — the historical fallback for drafts that predate
#      the language picker.
# ---------------------------------------------------------------------------

# Draft keys that hold the project-language choice itself.  Stored on the
# project draft, carried verbatim through clean_project_data and every
# generation payload.
_OFFER_LANG_STORED_KEYS = ('project_language', 'offer_lang', 'offerLang', 'projectLanguage')

# The picker stores the canonical codes; every other written form that can
# plausibly arrive (old payloads, hand-edited drafts, the select's Arabic
# labels) normalizes back to 'ar'/'en' rather than silently disabling the
# choice.
_OFFER_LANG_EN_ALIASES = frozenset((
    'en', 'eng', 'en-us', 'en-gb', 'english',
    'انجليزي', 'إنجليزي', 'الانجليزية', 'الإنجليزية', 'انجليزية', 'إنجليزية',
))
_OFFER_LANG_AR_ALIASES = frozenset((
    'ar', 'ara', 'ar-sa', 'arabic',
    'عربي', 'العربية', 'عربية',
))


def normalize_offer_lang(value):
    """Fold any written form of the language choice down to 'ar'/'en'/''."""
    text = str(value or '').strip().lower()
    if not text:
        return ''
    if text in _OFFER_LANG_EN_ALIASES:
        return OFFER_LANG_ENGLISH
    if text in _OFFER_LANG_AR_ALIASES:
        return OFFER_LANG_ARABIC
    return ''


def stored_offer_lang(project_data):
    """The language the project itself selected, or '' when unset/legacy."""
    if not isinstance(project_data, dict):
        return ''
    for key in _OFFER_LANG_STORED_KEYS:
        lang = normalize_offer_lang(project_data.get(key))
        if lang:
            return lang
    return ''


def _iter_offer_text_values(value, budget, _key=''):
    """Yield human string values for offer-language detection.

    Detection is intentionally conservative: genuine Arabic content wins, while
    machine identifiers and small auto-filled fragments (city, road names) can
    never flip an English project.
    """
    if budget[0] <= 0:
        return
    if isinstance(value, str):
        chunk = value[:budget[0]]
        budget[0] -= len(chunk)
        yield chunk
    elif isinstance(value, dict):
        for item_key, item in value.items():
            if isinstance(item_key, str) and _MACHINE_OFFER_KEY_RE.search(item_key):
                continue
            yield from _iter_offer_text_values(item, budget, item_key)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_offer_text_values(item, budget, _key)


def detect_offer_lang(project_data):
    """Detect the deck language from the project data itself.

    Returns 'en' only for substantial Latin data with at most fragmentary
    Arabic (auto-filled city/district, a road name); everything else —
    including empty drafts and mixed content — stays 'ar', which preserves
    the historical behavior exactly.
    """
    if not isinstance(project_data, dict):
        return OFFER_LANG_ARABIC
    budget = [50000]
    arabic = 0
    latin = 0
    for text in _iter_offer_text_values(project_data, budget):
        arabic += len(_ARABIC_SCRIPT_RE.findall(text))
        if arabic >= 40:
            return OFFER_LANG_ARABIC
        latin += len(_LATIN_LETTER_RE.findall(text))
    if latin >= 30:
        return OFFER_LANG_ENGLISH
    return OFFER_LANG_ARABIC


def resolve_offer_lang(project_data, offer_lang=None):
    """Resolve the deck language: explicit arg > stored project choice > detect."""
    explicit = normalize_offer_lang(offer_lang)
    if explicit:
        return explicit
    stored = stored_offer_lang(project_data)
    if stored:
        return stored
    return detect_offer_lang(project_data)


def section_title(section_key, offer_lang=OFFER_LANG_ARABIC):
    """Canonical deck-chrome title for a section in the deck language."""
    if offer_lang == OFFER_LANG_ENGLISH:
        return PRESENTATION_SECTION_TITLES_EN.get(section_key,
                                                  PRESENTATION_SECTION_TITLES.get(section_key, section_key))
    return PRESENTATION_SECTION_TITLES.get(section_key, section_key)


def offer_chrome(key, offer_lang=OFFER_LANG_ARABIC):
    """Fixed non-data deck label (cover/index markers) in the deck language."""
    if offer_lang == OFFER_LANG_ENGLISH:
        return OFFER_CHROME_EN.get(key, OFFER_CHROME_AR.get(key, key))
    return OFFER_CHROME_AR.get(key, key)
