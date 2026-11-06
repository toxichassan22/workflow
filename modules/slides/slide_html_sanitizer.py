"""Strip active content from slide HTML before it is shown to a third party.

Public share viewers insert slide markup with innerHTML. Anything the owner
pasted or the model generated (script tags, event-handler attributes,
javascript: URLs, embedded frames) must not run in the viewer's origin.
"""
import re

_DANGEROUS_BLOCK_TAGS = (
    'script', 'iframe', 'frame', 'frameset', 'object', 'embed', 'applet',
    'base', 'meta', 'link', 'form', 'noscript', 'template',
)
_BLOCK_TAG_RE = re.compile(
    r'<\s*(' + '|'.join(_DANGEROUS_BLOCK_TAGS) + r')\b[^>]*>.*?<\s*/\s*\1\s*>',
    re.I | re.S,
)
_VOID_TAG_RE = re.compile(
    r'<\s*/?\s*(' + '|'.join(_DANGEROUS_BLOCK_TAGS) + r')\b[^>]*>',
    re.I | re.S,
)
# Attributes whose value is a URL that can execute script.
_EVENT_ATTR_RE = re.compile(
    r'\s+on[a-z]+\s*=\s*(\"[^\"]*\"|\'[^\']*\'|[^\s>]+)', re.I,
)
_URL_ATTR_RE = re.compile(
    r'(\s+(?:href|src|xlink:href|action|formaction|data)\s*=\s*)'
    r'(\"[^\"]*\"|\'[^\']*\'|[^\s>]+)',
    re.I,
)
_UNSAFE_SCHEME_RE = re.compile(r'^\s*(?:javascript|vbscript|data\s*:\s*(?!image/))', re.I)
_CSS_EXPR_RE = re.compile(r'expression\s*\(|javascript\s*:|@import', re.I)


def _clean_url_attr(match):
    prefix, raw = match.group(1), match.group(2)
    value = raw.strip('"\'')
    if _UNSAFE_SCHEME_RE.match(value.replace('&#', '').replace('\x00', '')):
        return prefix + '"#"'
    return match.group(0)


def _clean_style_attr(match):
    raw = match.group(1)
    value = raw.strip('"\'')
    if _CSS_EXPR_RE.search(value):
        return ''
    return match.group(0)


def sanitize_slide_html_for_share(html):
    """Return slide markup with script-capable constructs removed."""
    if not html:
        return ''
    text = str(html)
    text = _BLOCK_TAG_RE.sub('', text)
    text = _VOID_TAG_RE.sub('', text)
    text = _EVENT_ATTR_RE.sub('', text)
    text = _URL_ATTR_RE.sub(_clean_url_attr, text)
    text = re.sub(r'\bstyle\s*=\s*(\"[^\"]*\"|\'[^\']*\')', _clean_style_attr, text, flags=re.I)
    return text
