"""Fact scopes for AI prompts.

A deck section only needs the project sections it actually renders. Passing the
whole project brief to every slide and every planner call was the largest
prompt cost in the deck path. This module is the one place that maps a deck
(or project) section to the project field sections it depends on.

Unknown scopes deliberately return ``None`` — meaning "use the full brief".
Sending an extra section costs tokens; dropping a required one costs quality.
"""

# Deck section -> project field-section keys (db.FIELD_SECTIONS).
DECK_SECTION_FACT_SECTIONS = {
    'overview': ('basic', 'location'),
    'components': ('basic', 'section-financial-calc'),
    'land': ('basic', 'location', 'land_croquis'),
    'location': ('basic', 'location'),
    'market': ('basic', 'location', 'section-market-study'),
    'swot_risks': ('basic', 'section-market-study'),
    'timeline': ('basic', 'section-timeline'),
    'financial': ('basic', 'land_croquis', 'section-timeline', 'section-financial-calc'),
    'team': ('basic', 'section-team'),
    'plans': ('basic', 'location', 'land_croquis', 'section-financial-calc',
              'section-visual-concept'),
    'exterior': ('basic', 'land_croquis', 'section-financial-calc', 'section-visual-concept'),
    'interior': ('basic', 'section-financial-calc', 'section-visual-concept'),
    'closing': ('basic', 'contact'),
    # The executive summary is the one section that genuinely reads every
    # earlier section. None means the full brief, never a partial one.
    'executive_summary': None,
}

# Project form section -> project field-section keys. The section-generation
# route receives a project section key (section-financial-calc, ...), while
# each slide carries a deck section key (financial, ...).
PROJECT_SECTION_FACT_SECTIONS = {
    'basic': ('basic',),
    'location': ('basic', 'location'),
    'land_croquis': ('basic', 'location', 'land_croquis'),
    'section-timeline': ('basic', 'section-timeline'),
    'section-financial-calc': ('basic', 'land_croquis', 'section-timeline',
                               'section-financial-calc'),
    'section-team': ('basic', 'section-team'),
    'section-market-study': ('basic', 'location', 'section-market-study'),
    'section-visual-concept': ('basic', 'location', 'land_croquis',
                               'section-financial-calc', 'section-visual-concept'),
    'section-executive-content': None,
    'contact': ('basic', 'contact'),
    'section-best-use': ('basic', 'section-best-use'),
}

# Extra blocks appended by build_project_facts. Each one is large enough that
# sending it to an unrelated section is a real cost.
SPECIAL_BLOCK_SECTIONS = {
    'team': 'section-team',
    'market': 'section-market-study',
    'executive': 'section-executive-content',
    'contact': 'contact',
}

# Notes appended next to the facts. They are not field sections: the financial
# note, for example, is the full report and is only useful to the financial
# and executive decks, not to a visual-concept deck that merely needs the
# component rows from the financial section.
NOTE_SCOPES = {
    'location': ('location', 'land', 'land_croquis'),
    'landmarks': ('location', 'land', 'land_croquis'),
    'timeline': ('timeline', 'financial', 'section-timeline',
                 'section-financial-calc', 'executive_summary',
                 'section-executive-content'),
    'financial': ('financial', 'section-financial-calc', 'executive_summary',
                  'section-executive-content'),
}

# Sections that need the component program even when they do not need the
# full financial report. Their compact component note replaces the report.
COMPONENT_SCOPES = ('components', 'plans', 'exterior', 'interior', 'overview',
                    'section-financial-calc', 'section-visual-concept')


def _clean_keys(keys):
    if isinstance(keys, str):
        keys = [keys]
    return tuple(str(key).strip() for key in (keys or []) if str(key).strip())


def fact_section_keys(scope_keys):
    """The project field sections a scope needs, or ``None`` for the full brief.

    Accepts deck section keys (financial, market, ...) and project form keys
    (section-financial-calc, ...). An unknown key and the executive summary
    both fall back to the full brief so a custom or future section can never
    silently lose a fact.
    """
    keys = _clean_keys(scope_keys)
    if not keys:
        return None
    selected = set()
    for key in keys:
        if key in DECK_SECTION_FACT_SECTIONS:
            mapped = DECK_SECTION_FACT_SECTIONS[key]
        elif key in PROJECT_SECTION_FACT_SECTIONS:
            mapped = PROJECT_SECTION_FACT_SECTIONS[key]
        else:
            return None
        if mapped is None:
            return None
        selected.update(mapped)
    return tuple(sorted(selected)) if selected else None


def scope_includes_any(scope_keys, *wanted):
    """True when one of ``wanted`` is in the raw scope, or the scope is full."""
    keys = _clean_keys(scope_keys)
    if not keys:
        return True
    wanted = {str(item).strip() for item in wanted if str(item).strip()}
    return any(key in wanted for key in keys)


def note_in_scope(scope_keys, note):
    """Whether a large optional note belongs to this scope."""
    return scope_includes_any(scope_keys, *NOTE_SCOPES.get(note, ()))


def scope_needs_components(scope_keys):
    """Whether the compact component program belongs to this scope."""
    return scope_includes_any(scope_keys, *COMPONENT_SCOPES)

