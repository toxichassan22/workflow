# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Map/location language support.
#
# The project-language choice picked at creation is stored on the draft
# (project_language — slide_engine owns the aliases and the content-detection
# fallback). Maps work cannot import slide_engine without a circular import, so
# the stored-choice read is mirrored here: resolve_offer_lang() in the app layer
# decides prompt language; map_language() decides which language Google calls,
# baked map labels, and collected site fields are produced in.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MAP_LANG_KEYS = ('project_language', 'offer_lang', 'offerLang', 'projectLanguage')
# Same written forms slide_engine.normalize_offer_lang accepts — a draft
# hand-edited to «إنجليزي» must still produce English map data.
_MAP_LANG_EN = frozenset((
    'en', 'eng', 'en-us', 'en-gb', 'english',
    'انجليزي', 'إنجليزي', 'الانجليزية', 'الإنجليزية', 'انجليزية', 'إنجليزية',
))

# One Arabic-script test shared by every "does this name need re-localization"
# check (road discovery prefers a localized geocode when the route summary
# arrives in the other script).
_ARABIC_CHAR_RE = re.compile('[\\u0600-\\u06FF]')


def _lang_norm(language):
    """Clamp a maps-API language argument to the two supported codes."""
    return 'en' if str(language or '').strip().lower() in _MAP_LANG_EN else 'ar'


def map_language(project_data):
    """'en' when the draft's stored language choice is English, else 'ar'.

    Unlike resolve_offer_lang() there is no content detection here: with no
    stored choice the historical Arabic behavior is preserved exactly.
    """
    if isinstance(project_data, dict):
        for key in _MAP_LANG_KEYS:
            value = str(project_data.get(key) or '').strip().lower()
            if value:
                return 'en' if value in _MAP_LANG_EN else 'ar'
    return 'ar'


def _distance_unit(language):
    return 'km' if _lang_norm(language) == 'en' else 'كم'


def _duration_unit(language, plural=False):
    if _lang_norm(language) == 'en':
        return 'min'
    return 'دقائق' if plural else 'دقيقة'
