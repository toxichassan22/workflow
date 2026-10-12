# ── Designer chrome intent ──────────────────────────────────────────────────
# Header, footer, logos and the page counter are ordinary slide chrome: Sol may
# edit, move or remove them whenever the user asks, under whatever wording the
# user picks («أعلى الصفحة» can mean the header). No hard gate sits in front of
# the model — Sol decides. The helpers below only decide whether the
# deterministic heals (missing-logo overlay, counter/footer injection) should
# step in: they stand down the moment a removal was declared by the model
# (``removed`` in its JSON) or plainly requested by the user's own words, so a
# deliberate deletion is never silently undone.

_DESIGNER_REMOVE_VERB_RE = re.compile(
    r'(?:احذف|حذف|احذفي|ازل|أزل|إزال|ازال|اشيل|شيل|شلي|امسح|مسح|اخف|إخف|اخف'
    r'|بلاش|بلا|بدون|من\s*غير|مش\s*عا[يي]ز|مش\s*عاوز|عا[يي]زه?ا?\s*من\s*غير'
    r'|remove|delet|hid(?:e|den)|drop|strip|without|take\s+off|get\s+rid)',
    re.IGNORECASE)
_DESIGNER_LOGO_WORD_RE = re.compile(
    r'(?:شعار|شعارات|لوجو|لوقو|لوجوه|علامة|علامه|brand|logo)', re.IGNORECASE)
_DESIGNER_HEADER_WORD_RE = re.compile(
    r'(?:هيدر|header|ترويس|الشريط\s*العلوي|أعلى|اعلى|العلوي|فوق|top\b|upper)',
    re.IGNORECASE)
_DESIGNER_FOOTER_WORD_RE = re.compile(
    r'(?:فوتر|footer|تذييل|الشريط\s*السفلي|أسفل|اسفل|السفلي|تحت|bottom\b|lower)',
    re.IGNORECASE)
# The counter gets its own bucket: «احذف الترقيم» takes the number away, not
# the whole footer. Bare «رقم»/«أرقام» and a literal «7/1» pattern count too —
# over-matching only disarms a heal, it never deletes anything.
_DESIGNER_COUNTER_WORD_RE = re.compile(
    r'(?:رقم|أرقام|ارقام|ترقيم|counter|numbers?|page\s*number'
    r'|\d+\s*[/\-–—]\s*\d+)',
    re.IGNORECASE)


def _designer_chrome_removal_intent(instruction):
    """Loose wording fallback: what managed elements the user asked to drop.

    Only ever widens what an edit may remove — never blocks one. Sol's declared
    ``removed`` list stays the primary signal; this rescues the same intent
    when the model forgets to declare it.
    """
    text = str(instruction or '')
    if not text or not _DESIGNER_REMOVE_VERB_RE.search(text):
        return set()
    intent = set()
    if _DESIGNER_LOGO_WORD_RE.search(text):
        intent.update(('company_logo', 'project_logo'))
    if _DESIGNER_HEADER_WORD_RE.search(text):
        # The header carries the brand marks — removing it removes them too.
        intent.update(('header', 'company_logo', 'project_logo'))
    if _DESIGNER_FOOTER_WORD_RE.search(text):
        intent.update(('footer', 'counter'))
    if _DESIGNER_COUNTER_WORD_RE.search(text):
        intent.add('counter')
    return intent


def _designer_declared_removals(removed_elements):
    """Normalize Sol's ``removed`` entries into the managed-element set."""
    suppressed = set()
    for raw in removed_elements or []:
        entry = re.sub(r'[\s\-]+', '_', str(raw or '').strip().lower())
        if not entry:
            continue
        if re.search(r'logo|شعار|لوجو|لوقو|brand', entry):
            if 'project' in entry or 'مشروع' in entry:
                suppressed.add('project_logo')
            elif 'company' in entry or 'شركة' in entry:
                suppressed.add('company_logo')
            else:
                suppressed.update(('company_logo', 'project_logo'))
        if re.search(r'header|هيدر|ترويس', entry):
            suppressed.update(('header', 'company_logo', 'project_logo'))
        if re.search(r'footer|فوتر|تذييل', entry):
            suppressed.update(('footer', 'counter'))
        if re.search(r'counter|page_?number|ترقيم|رقم', entry):
            suppressed.add('counter')
        if 'chrome' in entry:
            suppressed.update(('header', 'footer', 'counter', 'company_logo', 'project_logo'))
    return suppressed


def _designer_suppressed_chrome(removed_elements=None, instruction=None):
    """Union of Sol-declared removals and loose instruction intent."""
    return _designer_declared_removals(removed_elements) | _designer_chrome_removal_intent(instruction)


# ── Persisted removals (data-chrome-off) ─────────────────────────────────────
# A suppression only lasts one turn. Once an element is deliberately removed
# the fact must survive inside the saved slide itself, or every later save,
# renumber and unrelated edit would heal it back. ``data-chrome-off`` on the
# slide root is that memory: finalize stamps the absent+suppressed tokens, any
# element Sol brings back drops out of the list again.

_CHROME_OFF_RE = re.compile(
    r'\s*\bdata-chrome-off\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)
_CHROME_PRESENT_RES = (
    ('header', re.compile(r'\bdata-slide-header\s*=|<header\b', re.IGNORECASE)),
    ('footer', re.compile(r'\bdata-slide-footer\s*=|<footer\b', re.IGNORECASE)),
    ('counter', re.compile(r'\bdata-slide-counter\s*=', re.IGNORECASE)),
)
_SLIDE_ROOT_TAG_RE = re.compile(
    r'<div\b[^>]*\bclass\s*=\s*["\'][^"\']*\bslide\b[^"\']*["\'][^>]*>',
    re.IGNORECASE)


def _chrome_off_tokens(html):
    """Off-tokens stamped on the slide root by an earlier finalize."""
    match = _CHROME_OFF_RE.search(str(html or ''))
    if not match:
        return set()
    return {t for t in re.split(r'[\s,]+', match.group(1).strip().lower()) if t}


def _chrome_off_reconcile(html, present=None, suppressed=None):
    """Off-token set for the html's current state: prior stamps plus this
    turn's suppressions, minus whatever is visibly back on the slide."""
    off = (_chrome_off_tokens(html) | set(suppressed or ())) - set(present or ())
    for key, pattern in _CHROME_PRESENT_RES:
        if pattern.search(str(html or '')):
            off.discard(key)
    return off


def _stamp_chrome_off(html, off_tokens):
    """Write the off-token list onto the slide root (or strip it when empty)."""
    attr = ' data-chrome-off="' + ' '.join(sorted(off_tokens)) + '"' if off_tokens else ''

    def patch(match):
        tag = _CHROME_OFF_RE.sub('', match.group(0))
        return tag[:-1] + attr + '>' if attr else tag
    return _SLIDE_ROOT_TAG_RE.sub(patch, str(html or ''), count=1)


def _norm_logo_src(value):
    """Logo URL compare form — cache-busting query strings do not matter."""
    return re.sub(r'\?.*$', '', str(value or '').strip())


def _company_logo_sources(branding=None, tenant_id=None):
    """Every URL that counts as the company logo (same set finalize uses)."""
    branding = branding if isinstance(branding, dict) else {}
    sources = {
        resolve_logo_in_html('##LOGO##', tenant_id, _branding_cache=branding),
        branding.get('logo_path'), branding.get('logo'), branding.get('logo_url'),
        '/assets/logo.png',
    }
    return {str(src).strip() for src in sources if src and str(src).strip()}


def _shared_brand_logo(project_logo, branding=None, tenant_id=None):
    """True when the project logo resolves to the company logo image itself —
    the pair is then one brand mark, not two, and rendering both is a duplicate."""
    if not project_logo:
        return False
    normalized = _norm_logo_src(project_logo)
    return bool(normalized) and normalized in {
        _norm_logo_src(src) for src in _company_logo_sources(branding, tenant_id)}
