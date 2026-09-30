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
    r'(?:فوتر|footer|تذييل|الشريط\s*السفلي|أسفل|اسفل|السفلي|تحت|bottom\b|lower'
    r'|رقم\s*(?:الصفحة|الصفحه|الشريحة|الشريحه)|ترقيم|counter|page\s*number)',
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
