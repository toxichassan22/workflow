"""Conservative designer-chat color edits, without HTML/CSS serialization.

Integration contract:
* apply_color_edit(html, request) returns (html, message) on success (including
  a no-op), (None, NOT_APPLICABLE) for unrelated work, or (None, REFUSAL_PREFIX
  + Arabic reason). A refusal must NOT silently fall through to generation.
* is_color_only_request includes ambiguous color-only requests, not mixed edits.
* color_only_content_preserved(before, after) is a deliberately strict guard for
  generative color edits: only existing supported CSS color literals may change.
  Reformatting, new declarations, selector changes and logo edits fail closed.

Only stdlib is required. Existing declarations are patched by source offset.
Scoped commands change existing literal declarations, never invent selectors or
colors. Unsupported selectors/functions remain immutable. This is not a CSS
cascade engine or a contrast validator; retain the application's branding and
contrast checks, revision/history writes and tenant/slide targeting upstream.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
import re

NOT_APPLICABLE = 'not_applicable'
REFUSAL_PREFIX = 'refused: '

# CSS named colors with unambiguous everyday Arabic equivalents.
_NAMES = {
    'black': '000000', 'white': 'ffffff', 'red': 'ff0000', 'green': '008000',
    'blue': '0000ff', 'yellow': 'ffff00', 'orange': 'ffa500', 'purple': '800080',
    'pink': 'ffc0cb', 'gray': '808080', 'grey': '808080', 'brown': 'a52a2a',
    'gold': 'ffd700', 'silver': 'c0c0c0', 'navy': '000080', 'teal': '008080',
    'cyan': '00ffff', 'aqua': '00ffff', 'magenta': 'ff00ff', 'lime': '00ff00',
    'maroon': '800000', 'olive': '808000', 'beige': 'f5f5dc',
}
_ARABIC = {
    'اسود': 'black', 'سوداء': 'black', 'ابيض': 'white', 'بيضاء': 'white',
    'احمر': 'red', 'حمراء': 'red', 'اخضر': 'green', 'خضراء': 'green',
    'ازرق': 'blue', 'زرقاء': 'blue', 'اصفر': 'yellow', 'صفراء': 'yellow',
    'برتقالي': 'orange', 'بنفسجي': 'purple', 'وردي': 'pink', 'رمادي': 'gray',
    'بني': 'brown', 'ذهبي': 'gold', 'فضي': 'silver', 'كحلي': 'navy',
    'تركوازي': 'teal', 'سماوي': 'cyan', 'بيج': 'beige',
}


def _normalize_request(text):
    text = re.sub(r'[\u064b-\u065f\u0670\u0640]', '', text.lower())
    return re.sub(r'\s+', ' ', text.translate(str.maketrans('أإآى', 'اااي'))).strip(' .!؟?')


def _color(value, arabic=False):
    """Return exact RGBA bytes, not a nearest-color guess."""
    value = value.strip().lower()
    if arabic:
        value = _normalize_request(value)
        value = re.sub(r'^(?:باللون |بلون |اللون |لون )', '', value)
        if value.startswith('ال'):
            value = value[2:]
        value = _ARABIC.get(value, _ARABIC.get(value.removesuffix('ة'), value))
    if value == 'transparent':
        return (0, 0, 0, 0)
    if value in _NAMES:
        value = '#' + _NAMES[value]
    if re.fullmatch(r'#[0-9a-f]{3,4}|#[0-9a-f]{6}(?:[0-9a-f]{2})?', value):
        raw = value[1:]
        if len(raw) in (3, 4):
            raw = ''.join(c * 2 for c in raw)
        return tuple(bytes.fromhex(raw if len(raw) == 8 else raw + 'ff'))
    match = re.fullmatch(r'(rgb|rgba)\(([^()]*)\)', value)
    if not match:
        return None
    body = match[2]
    if ',' in body:
        parts = [p.strip() for p in body.split(',')]
        if len(parts) != (4 if match[1] == 'rgba' else 3):
            return None
    else:
        split = body.split('/')
        if len(split) > 2:
            return None
        parts = split[0].split()
        if len(parts) != 3:
            return None
        if len(split) == 2:
            parts.append(split[1].strip())
    result = []
    try:
        for index, part in enumerate(parts):
            percent = part.endswith('%')
            number = Decimal(part[:-1] if percent else part)
            bound = Decimal(100 if percent else (1 if index == 3 else 255))
            if not number.is_finite() or not 0 <= number <= bound:
                return None
            # Decimal preserves fractional channels and alpha without rounding.
            result.append(number * 255 / bound)
    except (InvalidOperation, ValueError):
        return None
    return tuple(result + ([255] if len(result) == 3 else []))


@dataclass(frozen=True)
class ColorEdit:
    scope: str
    target: tuple
    source: tuple | None = None


_COLOR_INTENT = re.compile(r'لون|الوان|خلفي[ةه]|\bcolou?rs?\b|\bbackground\b|#[0-9a-f]{3,8}\b|\brgba?\(', re.I)
_MIXED = re.compile(r'احذف|حذف|اضف|اضافة|انقل|حرك|كبر|صغر|حجم|استبدل النص|\b(?:delete|remove|add|move|resize|rewrite|font|size|text content)\b', re.I)


def is_color_only_request(request):
    if not isinstance(request, str):
        return False
    text = _normalize_request(request)
    has_color = bool(_COLOR_INTENT.search(text) or any(
        re.search(r'(?<!\w)(?:ال)?' + word + r'ة?(?!\w)', text) for word in (*_ARABIC, *_NAMES)))
    return has_color and not _MIXED.search(text)


def parse_color_edit(request):
    """Return (ColorEdit or None, status); accept a bounded, full-match grammar."""
    if not is_color_only_request(request):
        return None, NOT_APPLICABLE
    text = _normalize_request(request)
    text = re.sub(r'^(?:من فضلك |لو سمحت |please )', '', text)
    text = re.sub(r' (?:فقط|لا غير|only)$', '', text)
    replacement = re.fullmatch(
        r'(?:استبدل|بدل|غير|حول|replace|change) (?:اللون |لون )?(.+?) (?:الي|ب|باللون|to|with)\s*(.+)', text)
    if replacement:
        source, target = (_color(v, arabic=True) for v in replacement.groups())
        if source is not None and target is not None:
            return ColorEdit('replace', target, source), 'parsed'
    scoped = re.fullmatch(
        r'(?:(?:اجعل|خلي|غير|حول|لون|change|set|make) )?'
        r'(?:لون )?(الخلفية|خلفية الشريحة|خلفية|النص|النصوص|كل النصوص|نص الشريحة|العناوين|العنوان|background|text|headings)'
        r'(?: (?:في الشريحة|بالكامل|كلها))? (?:الي |الى |باللون |بلون |to )?(.+)', text)
    if scoped:
        target = _color(scoped[2], arabic=True)
        if target is not None:
            scope = ('background' if scoped[1] in ('الخلفية', 'خلفية الشريحة', 'خلفية', 'background')
                     else 'headings' if scoped[1] in ('العناوين', 'العنوان', 'headings') else 'text')
            return ColorEdit(scope, target), 'parsed'
    return None, REFUSAL_PREFIX + 'طلب الألوان غير محدد أو يتضمن نطاقا غير مدعوم.'


class _Unsafe(ValueError):
    pass


@dataclass
class _Node:
    tag: str
    attrs: dict
    parent: object
    protected: bool

    @property
    def root(self):
        return 'slide' in self.attrs.get('class', '').split()

    @property
    def heading(self):
        return bool(re.fullmatch('h[1-6]', self.tag) or self.attrs.get('role') == 'heading'
                    or set(self.attrs.get('class', '').split()) & {'title', 'heading', 'slide-title', 'section-title'})


_ATTR = re.compile(r'''\s+([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?''')
_VOID = set('area base br col embed hr img input link meta param source track wbr'.split())
_PROTECTED_TAGS = set('img picture svg script textarea title xmp iframe noembed noframes template noscript'.split())


class _HTML(HTMLParser):
    CDATA_CONTENT_ELEMENTS = ('script', 'style', 'textarea', 'title', 'xmp', 'iframe', 'noembed', 'noframes')

    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0] + [m.end() for m in re.finditer('\n', source)]
        self.stack = []
        self.nodes = []
        self.regions = []
        self.feed(source)
        self.close()
        if self.stack:
            raise _Unsafe('Unclosed HTML')

    def pos(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        raw, start = self.get_starttag_text(), self.pos()
        parent = self.stack[-1] if self.stack else None
        values = {k: v or '' for k, v in attrs}
        if len(values) != len(attrs):
            raise _Unsafe('Duplicate attributes')
        protected = (tag in _PROTECTED_TAGS or bool(parent and parent.protected)
                     or any('logo' in k or (k in ('id', 'class') and 'logo' in v.lower()) for k, v in values.items()))
        node = _Node(tag, values, parent, protected)
        self.nodes.append(node)
        # Match each whole attribute; never find a fake style inside another value.
        cursor = re.match(r'<[^\s/>]+', raw).end()
        while cursor < len(raw):
            match = _ATTR.match(raw, cursor)
            if not match:
                if not re.fullmatch(r'\s*/?>', raw[cursor:]):
                    raise _Unsafe('Unsupported HTML attribute syntax')
                break
            cursor = match.end()
            if match[1].lower() == 'style':
                group = next((n for n in (2, 3, 4) if match[n] is not None), None)
                if group is None:
                    continue
                value = match[group]
                # Encoded CSS needs a second source map. Leave it immutable instead.
                if unescape(value) == value and not protected:
                    self.regions.append((start + match.start(group), value, node))
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if not self.stack or self.stack[-1].tag != tag:
            raise _Unsafe('Mismatched HTML tags')
        self.stack.pop()

    def handle_data(self, data):
        if self.stack and self.stack[-1].tag == 'style' and not self.stack[-1].protected:
            if self.stack[-1].attrs.get('type', 'text/css').lower() == 'text/css':
                self.regions.append((self.pos(), data, None))


# CSS lexing is intentionally small: escaped identifiers and unknown functions
# are opaque. Strings, comments and complete url(...) tokens are never colors.
_TOKEN = re.compile(r'/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|#[\w-]+|[-\w\\]+|\s+|.', re.S)
_COLOR_PROPS = {'color', 'background-color', 'border-color', 'border-top-color', 'border-right-color',
                'border-bottom-color', 'border-left-color', 'outline-color', 'text-decoration-color',
                'column-rule-color', 'caret-color', 'text-emphasis-color'}
_COMPOUND_PROPS = {'background', 'border', 'border-top', 'border-right', 'border-bottom', 'border-left',
                   'outline', 'column-rule', 'text-decoration', 'box-shadow', 'text-shadow'}
_GRADIENTS = {'linear-gradient', 'radial-gradient', 'conic-gradient', 'repeating-linear-gradient',
              'repeating-radial-gradient', 'repeating-conic-gradient'}


def _tokens(css):
    tokens = list(_TOKEN.finditer(css))
    stack, pairs = [], {}
    for i, token in enumerate(tokens):
        value = token[0]
        if value in ('(', '[', '{'):
            stack.append((value, i))
        elif value in (')', ']', '}'):
            if not stack or stack[-1][0] != {')': '(', ']': '[', '}': '{'}[value]:
                raise _Unsafe('Unbalanced CSS')
            _, opening = stack.pop()
            pairs[opening] = i
        elif value in ('"', "'") or (value == '/' and i + 1 < len(tokens) and tokens[i + 1][0] == '*'):
            raise _Unsafe('Unclosed CSS string/comment')
    if stack:
        raise _Unsafe('Unbalanced CSS')
    return tokens, pairs


def _simple_match(node, selector):
    if not re.fullmatch(r'(?:[a-zA-Z][\w-]*|\*)?(?:[.#][\w-]+)*', selector) or not selector:
        raise _Unsafe('Unsupported selector')
    tag = re.match(r'^[a-zA-Z][\w-]*', selector)
    if tag and node.tag != tag[0].lower():
        return False
    return all((node.attrs.get('id') == name if kind == '#' else name in node.attrs.get('class', '').split())
               for kind, name in re.findall(r'([.#])([\w-]+)', selector))


def _matches(node, selector):
    parts = selector.split()
    if not parts:
        raise _Unsafe('Empty selector')
    # Validate every component even when the rightmost one does not match.
    for part in parts:
        _simple_match(node, part)
    if not _simple_match(node, parts[-1]):
        return False
    ancestor = node.parent
    for part in reversed(parts[:-1]):
        while ancestor and not _simple_match(ancestor, part):
            ancestor = ancestor.parent
        if ancestor is None:
            return False
        ancestor = ancestor.parent
    return True


@dataclass(frozen=True)
class _Literal:
    start: int
    end: int
    rgba: tuple
    prop: str
    nodes: tuple


def _literals(source):
    doc = _HTML(source)
    found = []
    for base, css, inline_node in doc.regions:
        tokens, pairs = _tokens(css)

        def value_colors(lo, hi, prop, nodes):
            i = lo
            while i < hi:
                token, value = tokens[i], tokens[i][0]
                if i + 1 < hi and tokens[i + 1][0] == '(':
                    close = pairs[i + 1]
                    if value.lower() in ('rgb', 'rgba'):
                        rgba = _color(css[token.start():tokens[close].end()])
                        if rgba is not None:
                            found.append(_Literal(base + token.start(), base + tokens[close].end(), rgba, prop, nodes))
                    elif value.lower() in _GRADIENTS and prop == 'background':
                        value_colors(i + 2, close, prop, nodes)
                    i = close + 1
                    continue
                if value in ('(', '[', '{'):
                    i = pairs[i] + 1
                    continue
                rgba = _color(value)
                if rgba is not None:
                    found.append(_Literal(base + token.start(), base + token.end(), rgba, prop, nodes))
                i += 1

        def declarations(lo, hi, nodes):
            begin, i = lo, lo
            while i <= hi:
                if i == hi or tokens[i][0] == ';':
                    segment = tokens[begin:i]
                    colon = next((n for n, t in enumerate(segment) if t[0] == ':'), None)
                    if colon is not None:
                        name = ''.join(t[0] for t in segment[:colon]).strip().lower()
                        if name in _COLOR_PROPS | _COMPOUND_PROPS:
                            value_colors(begin + colon + 1, i, name, nodes)
                    begin = i + 1
                elif tokens[i][0] in ('(', '['):
                    i = pairs[i]
                elif tokens[i][0] in ('{', '}'):
                    raise _Unsafe('Nested declarations are not supported')
                i += 1

        def rules(lo, hi):
            begin, i = lo, lo
            while i < hi:
                value = tokens[i][0]
                if value in ('(', '['):
                    i = pairs[i]
                elif value == ';':
                    begin = i + 1
                elif value == '{':
                    close = pairs[i]
                    prelude = ''.join(t[0] for t in tokens[begin:i] if not t[0].startswith('/*')).strip()
                    if re.match(r'^@(?:media|supports|layer|container)\b', prelude, re.I):
                        rules(i + 1, close)
                    elif not prelude.startswith('@'):
                        selectors = prelude.split(',')
                        try:
                            nodes = tuple(node for node in doc.nodes if any(_matches(node, s.strip()) for s in selectors))
                        except _Unsafe:
                            nodes = ()
                        # Shared selectors must not incidentally alter an image/logo.
                        if nodes and not any(n.protected for n in nodes):
                            declarations(i + 1, close, nodes)
                    i, begin = close, close + 1
                i += 1

        if inline_node is not None:
            declarations(0, len(tokens), (inline_node,))
        else:
            rules(0, len(tokens))
    return found


def _css_color(rgba):
    if all(value == int(value) for value in rgba):
        return '#' + bytes(int(v) for v in (rgba[:3] if rgba[3] == 255 else rgba)).hex()
    def number(value):
        return format(Decimal(value).normalize(), 'f')
    return 'rgba(' + ','.join(number(v) for v in (*rgba[:3], Decimal(rgba[3]) / 255)) + ')'


def _patch(source, replacements):
    for start, end, value in sorted(replacements, reverse=True):
        source = source[:start] + value + source[end:]
    return source


def color_only_content_preserved(before, after):
    """Fail closed unless every non-color byte, including logo CSS, is identical."""
    if not isinstance(before, str) or not isinstance(after, str) or not before.strip() or not after.strip():
        return False
    try:
        def skeleton(source):
            return _patch(source, [(v.start, v.end, '\x00COLOR\x00') for v in _literals(source)])
        return skeleton(before) == skeleton(after)
    except (ValueError, RecursionError):
        return False


def apply_color_edit(html, request):
    edit, message = parse_color_edit(request)
    if edit is None:
        return None, message
    if not isinstance(html, str) or not html.strip():
        return None, REFUSAL_PREFIX + 'الشريحة فارغة.'
    try:
        literals = _literals(html)
    except (ValueError, RecursionError):
        return None, REFUSAL_PREFIX + 'بنية HTML أو CSS غير مدعومة للتعديل الآمن.'
    if edit.scope == 'replace':
        selected = [v for v in literals if v.rgba == edit.source]
    elif edit.scope == 'background':
        selected = [v for v in literals if v.prop in ('background', 'background-color') and all(n.root for n in v.nodes)]
        # A gradient is multiple colors, not a singular slide background color.
        if any(v.prop == 'background' and not _pure_background(html, v) for v in selected):
            return None, REFUSAL_PREFIX + 'خلفية الشريحة مركبة وليست لونا منفردا.'
    else:
        selected = [v for v in literals if v.prop == 'color' and (edit.scope == 'text' or all(n.heading for n in v.nodes))]
    if not selected:
        return None, REFUSAL_PREFIX + 'لا يوجد تصريح لون مطابق قابل للتعديل في النطاق المحدد.'
    target = _css_color(edit.target)
    updated = _patch(html, [(v.start, v.end, target) for v in selected if v.rgba != edit.target])
    if not color_only_content_preserved(html, updated):
        return None, REFUSAL_PREFIX + 'تعذر ضمان بقاء محتوى الشريحة دون تغيير.'
    return updated, ('لم تتغير الألوان؛ اللون المطلوب موجود بالفعل.' if updated == html
                     else 'تم تعديل تصريحات اللون المطابقة مع إبقاء المحتوى والتخطيط والشعارات دون تغيير.')


def _pure_background(source, literal):
    # Only accept a standalone color value (plus optional !important). Nearby
    # token boundaries include the inline quote and the stylesheet declaration.
    before = source[max(source.rfind(':', 0, literal.start), 0):literal.start]
    after = re.split(r'[;\}\"\']', source[literal.end:], maxsplit=1)[0]
    return bool(re.fullmatch(r':\s*', before) and re.fullmatch(r'\s*(?:!\s*important\s*)?', after, re.I))
