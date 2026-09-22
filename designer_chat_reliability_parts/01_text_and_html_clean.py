

def _clean_text(value: Any) -> str:
    text = html_lib.unescape(str(value or ""))
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _url_keys(value: Any) -> List[str]:
    raw = html_lib.unescape(str(value or "")).strip()
    if not raw or raw.startswith("data:") or len(raw) > 4096:
        return []
    try:
        parsed = urlsplit(raw)
        path = unquote(parsed.path or raw).replace("\\", "/")
    except Exception:
        path = raw.split("?", 1)[0].split("#", 1)[0].replace("\\", "/")
    path = re.sub(r"/+", "/", path).rstrip("/").lower()
    if not path:
        return []
    keys = [path]
    name = PurePosixPath(path).name
    if name and name not in keys:
        keys.append(name)
    return keys


def _first_text(item: Dict[str, Any]) -> str:
    for key in ("description", "caption", "image_description", "imageDescription"):
        text = _clean_text(item.get(key))
        if text:
            return text
    return ""


def _item_urls(item: Dict[str, Any]) -> Iterable[str]:
    for key in (
        "approvedImageUrl", "approved_image_url", "imageUrl", "image_url",
        "url", "src", "path",
    ):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            yield value


def collect_image_descriptions(
    project_data: Dict[str, Any] | None,
    creative_images: Dict[str, Any] | None,
) -> Dict[str, str]:
    """Return URL/basename keys mapped to descriptions already stored by the user."""

    descriptions: Dict[str, str] = {}
    seen: set[int] = set()

    def add(url: Any, description: Any) -> None:
        text = _clean_text(description)
        if not text:
            return
        for key in _url_keys(url):
            descriptions.setdefault(key, text)

    def pair_parallel_arrays(container: Dict[str, Any]) -> None:
        for urls_key, meta_key, text_keys in (
            ("moodboard", "moodboard_meta", ("caption", "description")),
            ("plans", "plan_meta", ("description", "caption")),
        ):
            urls = container.get(urls_key)
            meta = container.get(meta_key)
            if not isinstance(urls, list) or not isinstance(meta, list):
                continue
            for url, item in zip(urls, meta):
                if not isinstance(item, dict):
                    continue
                description = next((_clean_text(item.get(key)) for key in text_keys if _clean_text(item.get(key))), "")
                add(item.get("url") or url, description)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            object_id = id(value)
            if object_id in seen:
                return
            seen.add(object_id)
            pair_parallel_arrays(value)
            description = _first_text(value)
            if description:
                for url in _item_urls(value):
                    add(url, description)
            for child in value.values():
                walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child)

    walk(project_data or {})
    walk(creative_images or {})
    return descriptions


def _description_for_src(src: str, descriptions: Dict[str, str]) -> str:
    for key in _url_keys(src):
        if key in descriptions:
            return descriptions[key]
    return ""


def _caption_already_follows(html: str, image_end: int, next_image_start: int, description: str) -> bool:
    limit = min(len(html), image_end + 1400, next_image_start)
    following = html[image_end:limit]
    if re.search(r"data-(?:project-image-description|visual-media-caption)\s*=", following, re.IGNORECASE):
        return True
    if re.search(r"<figcaption\b", following, re.IGNORECASE):
        return True
    return description and description in _clean_text(following)


def add_missing_image_descriptions(
    html: str,
    descriptions: Dict[str, str],
) -> Tuple[str, int, List[str]]:
    """Insert stored captions after matching images only when no caption is present."""

    source = str(html or "")
    matches = list(_IMG_RE.finditer(source))
    if not matches or not descriptions:
        return source, 0, []

    chunks: List[str] = []
    cursor = 0
    added: List[str] = []
    for index, match in enumerate(matches):
        chunks.append(source[cursor:match.end()])
        cursor = match.end()
        src_match = _SRC_RE.search(match.group(0))
        src = src_match.group(2).strip() if src_match else ""
        description = _description_for_src(src, descriptions)
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        if not description or _caption_already_follows(source, match.end(), next_start, description):
            continue
        marker = hashlib.sha1((src + "\0" + description).encode("utf-8")).hexdigest()[:12]
        caption = (
            f'<div data-project-image-description="{marker}" data-visual-media-caption="1" '
            'style="font-size:13px;line-height:1.55;color:#4b5563;margin-top:7px;'
            'font-weight:400;text-align:right;">'
            f'{html_lib.escape(description)}</div>'
        )
        chunks.append(caption)
        added.append(description)
    chunks.append(source[cursor:])
    return "".join(chunks), len(added), added


def is_image_description_request(message: Any) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    normalized = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    has_image = any(word in normalized for word in ("صورة", "صوره", "صور", "الصور", "مخطط", "المخططات"))
    has_description = any(word in normalized for word in ("وصف", "اوصاف", "أوصاف", "كابشن", "تعليق", "شرح"))
    has_placement = any(word in normalized for word in (
        "اضف", "أضف", "ضيف", "يضيف", "اضافة", "إضافة", "حط", "ضع",
        "اظهر", "أظهر", "اكتب", "ناقص", "مش محطوط", "غير موجود",
    ))
    return has_image and has_description and (has_placement or "وصف الصور" in normalized or "اوصاف الصور" in normalized)


def is_split_request(message: Any) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    normalized = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))

    # Guard 1: Creative generation or redesign instructions are for the AI agent, not a mechanical split
    creative_agent_intent = bool(re.search(
        r"(?:(?:أ|إ|ا)?عد\s*(?:توليد|تصميم|صياغة|بناء|ابتكار)|"
        r"(?:توليد|تصميم|ابتكار|تطوير|تحديث)\s+قسم|"
        r"مصمم[ةه]\s+جيد[ااً]|قوي[ةه]\s+بصري[ااً]|بصري[ااً]|"
        r"فخم[ةه]?|إبداع|ابداع|تصميم\s+جديد)",
        normalized
    ))
    if creative_agent_intent:
        return False

    # Guard 2: Section references where "قسم" is a noun (section), e.g. "في قسم كذا", "اعد توليد قسم كذا"
    if re.search(r"(?:في|عن|من|لكل|لهذا|بشأن|بخصوص|(?:أ|إ|ا)?عد\s+توليد|(?:أ|إ|ا)?عد\s+تصميم)\s+قسم\s+", normalized):
        if not re.search(r"(?:إلى|الى|على|لـ)\s*(?:\d+|شريحت|جز|نصف)|فكك|جزئ|شطر", normalized):
            return False

    # Guard 3: Pure section title reference like "قسم التصور البصري"
    if re.search(r"^\s*قسم\s+(?:التصور|الهوية|الفريق|المشروع|الارض|الأرض|الموقع|السوق|المالية|الخاتمة|الغلاف|المخططات)(?:\s+[\w\s]+)?$", normalized):
        if not re.search(r"(?:إلى|الى|على|لـ)\s*(?:\d+|شريحت|جز|نصف)|محتو|كروت|بطاق", normalized):
            return False

    split_explicit_verb = r"(?:(?:أ|إ|ا)قسم|قس[ّ]?م|تقسيم|تجزئة|جز[ّ]?ئ|فك[ّ]?ك|تفكيك|فص[ّ]?ل|شطر|وز[ّ]?ع)"
    split_targets = r"(?:الشريحة|شريحة|السلايد|سلايد|ها|محتوى|محتوي|البيانات|بيانات|الجدول|جدول|الكروت|كروت|البطاقات|بطاقات|العناصر|عناصر|الفقرات|فقرات|الملخص|التنفيذي|الدراسة|المالية|الموقع|السوق|الأرض|الارض)"

    if re.search(rf"{split_explicit_verb}\s*(?:.*?\b)?{split_targets}", normalized):
        return True

    if re.search(r"(?:قس[ّ]?م|تقسيم)\s*(?:(?:الشريحة|شريحة|السلايد|سلايد|محتوى|محتوي|الجدول|جدول)|ها)", normalized):
        return True

    if re.search(r"(?:على|إلى|الى|لـ)?\s*(?:شريحتين|جزأين|جزئين|نصفين|قسمين)(?:\s+(?:متناسقتين|منفصلتين|متوازنتين))?", normalized) and re.search(r"(?:اقسم|قس[ّ]?م|توزيع|تجزئة|فصل|فكك|اعمل|اجعل|خل|خلي)", normalized):
        return True

    return False


def split_request_parts(message: Any) -> SplitParts:
    text = str(message or "").strip().lower()
    normalized = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    if any(word in normalized for word in ("تلقائي", "اوتوماتيك", "حسب ما", "حسب المحتوى", "على حسب", "زي ما", "كما يرى")):
        return "auto"
    match = re.search(r"(?:الى|إلى|لـ?|على)\s*(\d{1,2})\s*(?:شرائح|شرايح|سلايد|أجزاء|اجزاء|قطع)?", normalized)
    if not match:
        match = re.search(r"(\d{1,2})\s*(?:شرائح|شرايح|سلايد|أجزاء|اجزاء)", normalized)
    if match:
        return max(2, min(20, int(match.group(1))))
    word_counts = (
        ("عشر", 10), ("تسع", 9), ("ثمان", 8), ("تماني", 8),
        ("سبع", 7), ("ست", 6), ("خمس", 5), ("اربع", 4), ("أربع", 4),
        ("تلات", 3), ("ثلاث", 3), ("اتنين", 2), ("اثنين", 2), ("شريحتين", 2),
        ("شريحتان", 2), ("جزأين", 2), ("جزئين", 2), ("نصفين", 2), ("قسمين", 2),
    )
    for word, number in word_counts:
        if word in normalized:
            return number
    return "auto"


def _row_capacity(rows: Sequence[str]) -> int:
    if not rows:
        return 1
    cell_counts = [max(1, len(_TD_RE.findall(row))) for row in rows]
    text_lengths = [len(_clean_text(row)) for row in rows]
    cells = max(cell_counts)
    average_text = sum(text_lengths) / len(text_lengths)
    capacity = 11
    if cells >= 8:
        capacity = 7
    elif cells >= 6:
        capacity = 8
    elif cells >= 4:
        capacity = 10
    if average_text > 500:
        capacity = min(capacity, 5)
    elif average_text > 300:
        capacity = min(capacity, 6)
    elif average_text > 180:
        capacity = min(capacity, 7)
    elif average_text > 100:
        capacity = min(capacity, 9)
    return max(4, min(12, capacity))


def _balanced_sizes(total: int, parts: int) -> List[int]:
    parts = max(1, min(parts, total))
    base, remainder = divmod(total, parts)
    return [base + (1 if index < remainder else 0) for index in range(parts)]


def _part_title(title: str, index: int, total: int) -> str:
    base = re.sub(r"\s*[-–—]\s*الجزء\s+\S+(?:\s+من\s+\S+)?\s*$", "", str(title or "")).strip()
    base = base or "شريحة"
    return f"{base} - الجزء {index} من {total}"


def split_table_slide(
    html: str,
    title: str,
    requested_parts: SplitParts = "auto",
) -> List[Dict[str, str]]:
    """Paginate the largest table into balanced, header-preserving slides."""

    source = str(html or "")
    candidates = []
    for table_match in _TABLE_RE.finditer(source):
        table_html = table_match.group(0)
        body_match = _TBODY_RE.search(table_html)
        if body_match:
            rows = _TR_RE.findall(body_match.group(2))
            candidates.append((len(rows), table_match, table_html, body_match, rows, "tbody"))
            continue

        row_matches = list(_TR_RE.finditer(table_html))
        if not row_matches:
            continue
        thead_match = re.search(r"<thead\b[^>]*>[\s\S]*?</thead>", table_html, re.IGNORECASE)
        data_matches = [
            row_match for row_match in row_matches
            if not thead_match or not (thead_match.start() <= row_match.start() < thead_match.end())
        ]
        implicit_header = None
        if not thead_match and data_matches and re.search(r"<th\b", data_matches[0].group(0), re.IGNORECASE):
            implicit_header = data_matches.pop(0)
        rows = [row_match.group(0) for row_match in data_matches]
        candidates.append((len(rows), table_match, table_html, (data_matches, implicit_header), rows, "direct"))
    if not candidates:
        return []
    _, table_match, table_html, body_info, rows, body_kind = max(candidates, key=lambda item: item[0])
    if len(rows) < 2:
        return []

    capacity = _row_capacity(rows)
    minimum_parts = max(1, math.ceil(len(rows) / capacity))
    if requested_parts == "auto":
        parts = minimum_parts
        if parts <= 1:
            return []
    else:
        try:
            parts = max(2, int(requested_parts))
        except (TypeError, ValueError):
            parts = minimum_parts
        parts = max(parts, minimum_parts)
    parts = min(parts, len(rows))
    sizes = _balanced_sizes(len(rows), parts)

    if body_kind == "tbody":
        prefix = table_html[:body_info.start(2)]
        suffix = table_html[body_info.end(2):]
        build_table = lambda page_rows: prefix + "".join(page_rows) + suffix
    else:
        data_matches, implicit_header = body_info
        table_template = table_html
        for row_match in reversed(data_matches):
            table_template = table_template[:row_match.start()] + table_template[row_match.end():]
        if implicit_header is not None:
            header_html = implicit_header.group(0)
            table_template = table_template[:implicit_header.start()] + table_template[implicit_header.end():]
            table_open_end = table_template.find(">") + 1
            table_template = (
                table_template[:table_open_end]
                + "<thead>" + header_html + "</thead>"
                + table_template[table_open_end:]
            )
        close_index = table_template.lower().rfind("</table>")
        build_table = lambda page_rows: (
            table_template[:close_index]
            + "<tbody>" + "".join(page_rows) + "</tbody>"
            + table_template[close_index:]
        )
    output: List[Dict[str, str]] = []
    offset = 0
    for index, size in enumerate(sizes, start=1):
        page_rows = rows[offset:offset + size]
        offset += size
        page_table = build_table(page_rows)
        page_html = source[:table_match.start()] + page_table + source[table_match.end():]
        output.append({"title": _part_title(title, index, parts), "html": page_html})
    return output


def split_cards_or_blocks(html: str, title: str, num_parts: int = 2) -> List[Dict[str, str]]:
    """Deterministically partition cards, metric boxes, list items, or paragraphs across slides."""
    if not html or num_parts <= 1:
        return [{"title": title, "html": html}]

    # 1. Match card, metric, stat, col, box divs
    div_card_re = re.compile(
        r'<div\b[^>]*\bclass\s*=\s*["\'][^"\']*(?:card|metric|item|box|stat|col|widget)[^"\']*["\'][^>]*>',
        re.IGNORECASE,
    )
    starts = [m.start() for m in div_card_re.finditer(html)]
    blocks: List[Tuple[int, int, str]] = []
    if len(starts) >= num_parts:
        div_token = re.compile(r'<div\b[^>]*>|</div\s*>', re.IGNORECASE)
        for i, start in enumerate(starts):
            boundary = starts[i + 1] if i + 1 < len(starts) else len(html)
            fragment = html[start:boundary]
            depth = 0
            cut = None
            for token in div_token.finditer(fragment):
                if token.group(0).lower().startswith("</div"):
                    depth -= 1
                    if depth <= 0:
                        cut = token.end()
                        break
                else:
                    depth += 1
            if cut is not None:
                blocks.append((start, start + cut, fragment[:cut]))

    # 2. Fallback to <li> items
    if len(blocks) < num_parts:
        li_re = re.compile(r'<li\b[^>]*>[\s\S]*?</li>', re.IGNORECASE)
        li_matches = list(li_re.finditer(html))
        if len(li_matches) >= num_parts:
            blocks = [(m.start(), m.end(), m.group(0)) for m in li_matches]

    # 3. Fallback to <p> items
    if len(blocks) < num_parts:
        p_re = re.compile(r'<p\b[^>]*>[\s\S]*?</p>', re.IGNORECASE)
        p_matches = list(p_re.finditer(html))
        if len(p_matches) >= num_parts:
            blocks = [(m.start(), m.end(), m.group(0)) for m in p_matches]

    if len(blocks) < num_parts:
        return []

    total = len(blocks)
    parts_count = min(num_parts, total)
    base_size, rem = divmod(total, parts_count)
    sizes = [base_size + (1 if i < rem else 0) for i in range(parts_count)]

    output: List[Dict[str, str]] = []
    offset = 0
    clean_title = re.sub(r"\s*[-–—]\s*الجزء\s+\S+(?:\s+من\s+\S+)?\s*$", "", str(title or "")).strip() or "شريحة"
    for p_idx, size in enumerate(sizes, start=1):
        keep_indices = set(range(offset, offset + size))
        offset += size

        page_html = html
        for b_idx in reversed(range(total)):
            if b_idx not in keep_indices:
                b_start, b_end, _ = blocks[b_idx]
                page_html = page_html[:b_start] + page_html[b_end:]

        p_title = f"{clean_title} - الجزء {p_idx} من {parts_count}"
        output.append({"title": p_title, "html": page_html})

    return output


_PROSE_MIN_CHARS = 350
_PROSE_UNIT_TAGS = {
    "p", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
    "div", "section", "article", "span", "strong", "em", "b",
}
_PROSE_SKIP_TAGS = {
    "table", "thead", "tbody", "tfoot", "tr", "td", "th",
    "script", "style", "template", "svg", "select", "option",
}
_PROSE_UNSAFE_INNER = re.compile(
    r"<(?:img|svg|canvas|iframe|object|embed|video|audio|a)\b|url\(|data-", re.IGNORECASE
)
_VOID_TAGS = set("area base br col embed hr img input link meta param source track wbr".split())


class _ProseMap(HTMLParser):
    """Locate visible elements carrying enough direct text to split verbatim."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.html = html
        self._lines = [0] + [m.end() for m in re.finditer(r"\n", html)]
        self.stack: List[Dict[str, Any]] = []
        self.units: List[Dict[str, Any]] = []
        try:
            self.feed(html)
            self.close()
        except Exception:
            pass
        self.stack = []
        kept: List[Dict[str, Any]] = []
        for unit in sorted(self.units, key=lambda u: (u["start"], -u["end"])):
            if kept and unit["start"] < kept[-1]["end"]:
                continue
            kept.append(unit)
        self.units = kept

    def _abs(self) -> int:
        line, col = self.getpos()
        return self._lines[line - 1] + col if 0 < line <= len(self._lines) else 0

    def handle_starttag(self, tag, attrs):
        start = self._abs()
        attr_map = dict(attrs)
        parent = self.stack[-1] if self.stack else None
        style = re.sub(r"\s+", "", attr_map.get("style") or "").lower()
        hidden = (
            bool(parent and parent["hidden"])
            or tag in ("script", "style", "template")
            or "hidden" in attr_map
            or attr_map.get("aria-hidden") == "true"
            or any(rule in style for rule in ("display:none", "visibility:hidden", "opacity:0;", "font-size:0"))
            or style.endswith("opacity:0")
        )
        classes = (attr_map.get("class") or "").split()
        hidden = hidden or any(key in attr_map for key in ("data-slide-footer", "data-slide-counter")) \
            or bool({"slide-footer", "slide-counter"} & set(classes))
        frame = {
            "tag": tag,
            "start": start,
            "inner_start": start + len(self.get_starttag_text() or ""),
            "hidden": hidden,
            "skipped": bool(parent and parent["skipped"]) or tag in _PROSE_SKIP_TAGS,
            "direct": 0,
            "texts": [],
        }
        if tag not in _VOID_TAGS:
            self.stack.append(frame)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        pos = self._abs()
        index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i]["tag"] == tag), None)
        if index is None:
            return
        while len(self.stack) > index + 1:
            self.stack.pop()
        frame = self.stack.pop()
        gt = self.html.find(">", pos)
        end = gt + 1 if gt >= 0 else pos + len(tag) + 3
        if (
            not frame["hidden"]
            and not frame["skipped"]
            and frame["tag"] in _PROSE_UNIT_TAGS
            and frame["direct"] >= _PROSE_MIN_CHARS
        ):
            inner = self.html[frame["inner_start"]:pos]
            if not _PROSE_UNSAFE_INNER.search(inner):
                text = " ".join("".join(frame["texts"]).split())
                if text:
                    self.units.append({**frame, "inner_end": pos, "end": end, "text": text})

    def handle_data(self, data):
        for frame in self.stack:
            frame["texts"].append(data)
        if self.stack:
            self.stack[-1]["direct"] += len(data.strip())


def _sentence_split_points(text: str, num_parts: int) -> List[int]:
    """Balanced cut positions, snapped to sentence ends then word boundaries."""
    total = len(text)
    if total < num_parts * 40:
        return []
    sentence_bounds = [m.end() for m in re.finditer(r"[.!؟?؛…]+[)\]]*\s+|\n+", text)]
    word_bounds = [m.end() for m in re.finditer(r"\s+", text)]
    cuts = []
    prev = 0
    for i in range(1, num_parts):
        target = total * i // num_parts
        window = total // (num_parts * 4)
        near = [b for b in sentence_bounds if prev < b < total and abs(b - target) <= window]
        if near:
            cut = min(near, key=lambda b: abs(b - target))
        else:
            ahead = [b for b in word_bounds if prev < b < total]
            if not ahead:
                return []
            cut = min(ahead, key=lambda b: abs(b - target))
        if cut <= prev or cut >= total:
            return []
        cuts.append(cut)
        prev = cut
    return cuts if len(cuts) == num_parts - 1 else []


def split_prose_slide(html: str, title: str, num_parts: int = 2) -> List[Dict[str, str]]:
    """Deterministically partition large prose text across slides at sentence
    boundaries, for dense slides whose block count is too small for
    split_cards_or_blocks (e.g. one giant paragraph card)."""
    if not html or num_parts <= 1:
        return []
    units = _ProseMap(html).units
    if not units:
        return []
    stream = " ".join(unit["text"] for unit in units)
    if len(stream) < _PROSE_MIN_CHARS:
        return []
    cuts = _sentence_split_points(stream, num_parts)
    if len(cuts) != num_parts - 1:
        return []
    spans = []
    prev = 0
    for cut in cuts:
        spans.append((prev, cut))
        prev = cut
    spans.append((prev, len(stream)))
    offsets = []
    cursor = 0
    for unit in units:
        offsets.append((cursor, cursor + len(unit["text"])))
        cursor += len(unit["text"]) + 1
    clean_title = re.sub(r"\s*[-–—]\s*الجزء\s+\S+(?:\s+من\s+\S+)?\s*$", "", str(title or "")).strip() or "شريحة"
    output: List[Dict[str, str]] = []
    for part_index, (span_start, span_end) in enumerate(spans, start=1):
        edits = []
        for unit, (unit_start, unit_end) in zip(units, offsets):
            share_start = max(span_start, unit_start)
            share_end = min(span_end, unit_end)
            if share_start >= share_end:
                edits.append((unit["start"], unit["end"], ""))
            elif share_start > unit_start or share_end < unit_end:
                share = stream[share_start:share_end].strip()
                edits.append((unit["inner_start"], unit["inner_end"], html_lib.escape(share)))
        part_html = html
        for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
            part_html = part_html[:start] + replacement + part_html[end:]
        output.append({"title": f"{clean_title} - الجزء {part_index} من {num_parts}", "html": part_html})
    return output


def estimate_semantic_parts(html: str, requested_parts: SplitParts = "auto") -> int:
    if requested_parts != "auto":
        try:
            return max(2, min(8, int(requested_parts)))
        except (TypeError, ValueError):
            pass
    source = re.sub(r"<(?:script|style)\b[^>]*>[\s\S]*?</(?:script|style)>", " ", str(html or ""), flags=re.IGNORECASE)
    text_length = len(_clean_text(source))
    block_count = len(re.findall(r"<(?:li|p|article|section|tr)\b|class=[\"'][^\"']*(?:card|metric|item|col|grid)", source, re.IGNORECASE))
    parts = max(math.ceil(text_length / 900), math.ceil(block_count / 5), 2)
    return max(2, min(6, parts))


def semantic_part_instruction(part_index: int, total_parts: int) -> str:
    return (
        f"هذه عملية تقسيم فعلية إلى {total_parts} شرائح. أنشئ الجزء {part_index} من {total_parts} فقط. "
        "قسّم العناصر والفقرات المتتابعة إلى مجموعات متوازنة حسب المعنى، واحتفظ في هذا الجزء "
        "بالمجموعة المقابلة له فقط، دون تكرار أي عنصر في جزء آخر ودون حذف معلومة. "
        "حافظ على عنوان وسياق مختصرين، واجعل كل المحتوى ظاهرًا داخل 1280x720 دون قص أو تمرير."
    )


_AR_DIGITS_TABLE_EDIT = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹²³أإآٱىة", "0123456789012345678923اااايه"
)

_TABLE_EDIT_VERBS = (
    "احذف", "حذف", "امسح", "مسح", "شيل", "اشيل", "أشيل", "شال",
    "ازيل", "أزيل", "ازال", "إزالة", "ازالة", "ازل", "أزل",
    "تشيل", "تشيلي", "شيلي", "تزيل", "تزيلي", "ازيلي", "أزيلي",
    "تحذف", "تحذفي", "احذفي", "تمسح", "تمسحي", "امسحي",
    "الغي", "ألغي", "إلغاء", "الغاء", "الغ",
    "اسقط", "أسقط", "إسقاط",
    "طير", "تطير",
    "احذفلي", "امسحلي", "شيللي", "remove", "delete",
)

_TABLE_EDIT_ROW_WORDS = (
    "صف", "صفوف", "الصف", "الصفوف", "سطر", "سطور", "السطر", "السطور",
    "row", "rows",
)

_TABLE_EDIT_COL_WORDS = (
    "عمود", "عامود", "العمود", "العامود", "اعمدة", "أعمدة", "الاعمدة",
    "الأعمدة", "عواميد", "العواميد", "column", "columns",
)

_TABLE_EDIT_ORDINALS = (
    (("الأول", "الاول", "الاولى", "الأولى", "اول", "أول", "اولى", "أولى"), 1),
    (("الثاني", "الثانى", "الثانية", "الثانيه", "ثاني", "ثانى", "تاني", "التاني"), 2),
    (("الثالث", "الثالثة", "الثالثه", "ثالث", "تالت", "التالت"), 3),
    (("الرابع", "الرابعة", "الرابعه", "رابع"), 4),
    (("الخامس", "الخامسة", "الخامسه", "خامس"), 5),
    (("السادس", "السادسة", "السادسه", "سادس"), 6),
    (("السابع", "السابعة", "السابعه", "سابع"), 7),
    (("الثامن", "الثامنة", "الثامنه", "ثامن", "تامن"), 8),
    (("التاسع", "التاسعة", "التاسعه", "تاسع"), 9),
    (("العاشر", "العاشرة", "العاشره", "عاشر"), 10),
)

_TABLE_EDIT_LAST_WORDS = ("اخر", "آخر", "الاخر", "الآخر", "الاخير", "الأخير", "الاخيرة", "الأخيرة", "last")

_TABLE_EDIT_STOPWORDS = {
    "من", "في", "فى", "الجدول", "جدول", "الشريحة", "شريحة", "الشريحه",
    "شريحه", "السلايد", "سلايد", "الحالي", "الحالى", "الحالية", "الحاليه",
    "ده", "دي", "ذي", "لو", "سمحت", "فضلا", "فضلاً", "عايز", "عايزه",
    "اريد", "أريد", "ممكن", "رقم", "برقم", "اللي", "الذي", "التي",
    "فيه", "فيها", "عنوانه", "عنوانها", "اسمه", "اسمها", "نصه", "اللى",
    "اللى", "ده", "دى",
}


def _normalize_table_edit_text(message: Any) -> str:
    text = html_lib.unescape(str(message or ""))
    text = text.casefold().translate(_AR_DIGITS_TABLE_EDIT)
    text = re.sub(r"[\u0640\u064b-\u065f\u0670\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", text)
    return re.sub(r"[\u00a0\s]+", " ", text).strip()


def _table_word_pattern(words: Sequence[str]) -> str:
    words = sorted({_normalize_table_edit_text(word) for word in words}, key=len, reverse=True)
    return r"(?<!\w)(?:" + "|".join(re.escape(word) for word in words) + r")(?!\w)"


_TABLE_AXIS_RE = re.compile(_table_word_pattern(_TABLE_EDIT_ROW_WORDS + _TABLE_EDIT_COL_WORDS))
_TABLE_DELETE_RE = re.compile(_table_word_pattern(_TABLE_EDIT_VERBS))
_TABLE_SCOPE_RE = re.compile(
    r"(?<!\w)(?:(?:من|في|from|in)\s+)?(?:الجدول|جدول|table)(?!\w)"
)
_TABLE_QUOTES_RE = re.compile(r'''"([^"
]+)"|'([^'
]+)'|«([^»
]+)»|"([^"
]+)"''')


def _table_selector(value: str) -> Union[Dict[str, Any], None]:
    value = value.strip(" .،,؛;!؟?")
    quoted = _TABLE_QUOTES_RE.fullmatch(value)
    if quoted:
        return {"by": "name", "name": next(part for part in quoted.groups() if part)}
    value = re.sub(r"^(?:رقم|برقم|number|no\.?|#)\s*", "", value).strip()
    if re.fullmatch(r"\d{1,6}(?:st|nd|rd|th)?", value):
        return {"by": "number", "number": int(re.match(r"\d+", value).group())}
    normalized_last = {_normalize_table_edit_text(word) for word in _TABLE_EDIT_LAST_WORDS}
    if value in normalized_last:
        return {"by": "number", "number": "last"}
    for variants, number in _TABLE_EDIT_ORDINALS:
        if value in {_normalize_table_edit_text(word) for word in variants}:
            return {"by": "number", "number": number}
    english = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
               "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
    if value in english:
        return {"by": "number", "number": english[value]}
    if not value or any(ch in (chr(10), chr(13)) for ch in value):
        return None
    if re.fullmatch(r"\d+(?:\s+\d+)+", value):
        return None
    return {"by": "name", "name": value}


def detect_table_edit_request(message: Any) -> Dict[str, Any]:
    """Detect before routing to an AI planner, including unsafe/unsupported edits.

    handled=True is a routing barrier, not evidence that an edit succeeded.
    Call apply_table_delete_request only with the original user message. Slide
    selection belongs to the caller; numbers here refer only to rows/columns.
    """
    text = _normalize_table_edit_text(message)
    # Strip leading polite conversational fillers
    text = re.sub(r"^(?:لو\s*(?:سمحت|تكرمت|ممكن|تفضلت)|من\s*فضلك|بعد\s*اذنك|ممكن|تقدر|ياريت|يا\s*ريت|فضلا|فضلاً)\s*", "", text)
    # Words in quoted labels cannot introduce a second operation or axis.
    masked = _TABLE_QUOTES_RE.sub(lambda match: " " * len(match.group()), text)
    # Preservation phrases (e.g. "دون حذف", "بدون مسح") state what NOT to delete and must not count as deletion verbs
    verbs_scan = re.sub(r"(?<!\w)(?:بدون|دون|عدم|من\s*غير|بلا)\s+(?:اي\s+|أي\s+)?(?:حذف|مسح|ازالة|إزالة|إسقاط|اسقاط)(?!\w)", " ", masked)
    axes = list(_TABLE_AXIS_RE.finditer(masked))
    if any(word in masked.split() for word in ("والصف", "والعمود", "وصفوف", "وأعمدة", "واعمدة")):
        axes.append(None)
    verbs = list(_TABLE_DELETE_RE.finditer(verbs_scan))
    cell = re.search(r"(?<!\w)(?:الخليه|الخلية|خليه|خلية|الخلايا|خلايا|cells?)(?!\w)", masked)
    edit = re.search(r"(?<!\w)(?:و)?(?:اضف|اضافة|عدل|تعديل|غير|استبدل|add|edit|replace|change)(?!\w)", masked)
    whole_table = _TABLE_SCOPE_RE.search(masked)
    is_slide_redesign = bool(re.search(r"(?<!\w)(?:اعد\s*تصميم|إعادة\s*تصميم|غير\s*تصميم|تصميم\s*الشريح|تنسيق\s*الشريح)(?!\w)", text))
    if is_slide_redesign and not verbs:
        return {"handled": False, "operation": "edit", "supported": False, "reason": "not_a_table_edit", "request": None}
    handled = bool((verbs or edit or re.search(r"تحذف|تمسح|تشيل", masked)) and (axes or cell or whole_table))
    result = {"handled": handled, "operation": "delete" if verbs else "edit",
              "supported": False, "reason": "not_a_table_edit", "request": None}
    if not handled:
        return result
    result["reason"] = "unsupported_table_edit"
    if re.search(r"(?<!\w)(?:لا|لاتحذف|متشيلش|متمسحش|ليس|بدون|دون|not|never|don't)(?!\w)", masked):
        result["reason"] = "negated_or_conditional_request"
        return result
    if re.search(r"(?<!\w)(?:اذا|لو(?!\s*(?:سمحت|تكرمت|ممكن|تفضلت|عليك امر))|if|unless)(?!\w)", masked):
        result["reason"] = "negated_or_conditional_request"
        return result
    if not verbs or edit or cell:
        return result
    if len(axes) != 1 or len(verbs) != 1:
        result["reason"] = "ambiguous_table_request"
        return result
    axis = axes[0]
    word = axis.group().lstrip("و")
    kind = "row" if word in {_normalize_table_edit_text(w) for w in _TABLE_EDIT_ROW_WORDS} else "column"
    request: Dict[str, Any] = {"kind": kind}
    tail = text[axis.end():]
    # A slide qualifier is never a row number or part of a target label.
    slide_scope = re.search(
        r"(?<!\w)(?:(?:من|في|in|from|on)\s+)?(?:(?:ال)?(?:شريح[ةه]|شرايح|شرائح|سلايد[ةهات]*|صفح[ةه]|صفحات)|slides?|(?:من|في)\s+رقم)(?!\w)",
        _TABLE_QUOTES_RE.sub(lambda m: " " * len(m.group()), tail),
    )
    if slide_scope:
        tail = tail[:slide_scope.start()]
    tail = re.sub(r"\s+(?:من|في|in|from|on)\s+(?:(?:ال)?(?:شريح[ةه]|سلايد[ةه]?|صفح[ةه]|رقم)\s+)?\d+\s*$", "", tail)
    scopes = list(_TABLE_SCOPE_RE.finditer(masked))
    if len(scopes) > 1:
        result["reason"] = "ambiguous_table_request"
        return result
    if scopes:
        scope = scopes[0]
        if scope.start() > axis.end():
            selector_text = text[scope.end():]
            selector_text = re.split(r"\s+(?:من|في|in|from|on)\s+(?:(?:ال)?(?:شريح[هة]|شرائح|سلايد[ةهات]*|صفح[هة]|صفحات)|slides?)\b", selector_text)[0]
            tail = text[axis.end():scope.start()]
        else:
            selector_text = text[scope.end():verbs[0].start()]
        selector_text = re.sub(r"^(?:باسم|بعنوان|المسمي|المسمى|named)\s+", "", selector_text).strip(" .،,؛;!؟?")
        if selector_text:
            selector = _table_selector(selector_text)
            if selector is None:
                result["reason"] = "ambiguous_table_selector"
                return result
            request["table"] = selector
    courtesy_suffix_re = re.compile(
        r"\s+(?:لو سمحت|من فضلك|لو تكرمت|بعد اذنك|فضلا|فضلاً|بالله|شكرا|شكراً|رجاء|رجاءً|please|thanks|thx|فقط)\s*$",
        re.IGNORECASE,
    )
    tail = courtesy_suffix_re.sub("", tail.strip())
    # Permit the common reversed form «احذف آخر صف» / 'delete last row'.
    before_axis = text[verbs[0].end():axis.start()].strip()
    if before_axis:
        if tail.strip() or _table_selector(before_axis) is None:
            result["reason"] = "ambiguous_table_request"
            return result
        tail = before_axis
    contains = bool(re.match(r"^(?:اللي فيه|الذي يحتوي|يحتوي على|containing)\s+", tail.strip()))
    tail = re.sub(
        r"^(?:اللي فيه|الذي يحتوي(?: على)?|يحتوي على|containing|"
        r"بتاع(?:ة|ت)?|حق(?:ة)?|تبع|"
        r"(?:اللي|اللى|الذي|التي)\s+(?:اسمها|اسمه|بعنوان|باسم)|"
        r"الخاص\s+ب(?:ـ)?|خاص\s+ب(?:ـ)?|"
        r"بعنوان|باسم|بإسم|اسمه|اسمها|عنوانه|عنوانها|المسمى|المسمي|المعنون|named)\s*",
        "", tail.strip(),
    )
    tail = courtesy_suffix_re.sub("", tail.strip())
    if not tail:
        result["reason"] = "missing_table_target"
        return result
    # Keep quoted names intact, including punctuation and conjunctions.
    pieces = []
    cursor = 0
    for quote in _TABLE_QUOTES_RE.finditer(tail):
        pieces.append(tail[cursor:quote.start()])
        pieces.append(quote.group())
        cursor = quote.end()
    pieces.append(tail[cursor:])
    if any(_TABLE_QUOTES_RE.fullmatch(piece) for piece in pieces):
        unquoted = "".join(piece for piece in pieces if not _TABLE_QUOTES_RE.fullmatch(piece))
        if not re.fullmatch(r"[\s,،]*(?:(?:و|and)[\s,،]*)*", unquoted):
            result["reason"] = "ambiguous_table_request"
            return result
        targets = [_table_selector(piece) for piece in pieces if _TABLE_QUOTES_RE.fullmatch(piece)]
    else:
        # Numeric lists only; an unquoted name containing 'و' remains one label.
        number_list = re.split(r"\s*(?:,|،|\s+و\s*|\s+and\s+)\s*", tail)
        parsed = [_table_selector(piece) for piece in number_list]
        targets = parsed if all(item and item["by"] == "number" for item in parsed) else [_table_selector(tail)]
    if not targets or any(target is None for target in targets):
        result["reason"] = "ambiguous_table_target"
        return result
    # Never execute a prefix of an unrecognized compound request.
    if re.search(r"(?<!\w)(?:ثم|وبعد|وكمان|وايضا|وغير|واجعل|then|also)(?!\w)", masked):
        result["reason"] = "compound_table_request"
        return result
    for target in targets:
        if target["by"] == "name" and kind == "row":
            target["by"] = "text"
            target["text"] = target.pop("name")
            if contains:
                target["contains"] = True
    request.update(targets[0])
    if len(targets) > 1:
        request["targets"] = targets
    result.update(supported=True, reason="", request=request)
    return result
