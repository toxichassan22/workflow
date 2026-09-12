"""Deterministic reliability helpers for the presentation designer chat.

The AI planner may choose an action, but these helpers make two user-visible
operations deterministic: adding stored image descriptions and paginating
large tables without dropping or duplicating rows.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import math
import re
import concurrent.futures
import copy
import json
import os
import threading
import time
import uuid
from functools import wraps
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Sequence, Tuple, Union
from urllib.parse import unquote, urlsplit


SplitParts = Union[int, str]
_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)
_SRC_RE = re.compile(r"\bsrc\s*=\s*([\"'])(.*?)\1", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_TABLE_RE = re.compile(r"<table\b[^>]*>[\s\S]*?</table>", re.IGNORECASE)
_TBODY_RE = re.compile(r"(<tbody\b[^>]*>)([\s\S]*?)(</tbody>)", re.IGNORECASE)
_TR_RE = re.compile(r"<tr\b[^>]*>[\s\S]*?</tr>", re.IGNORECASE)
_TD_RE = re.compile(r"<(?:td|th)\b[^>]*>[\s\S]*?</(?:td|th)>", re.IGNORECASE)


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


_AR_DIGITS_TABLE_EDIT = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

_TABLE_EDIT_VERBS = (
    "احذف", "حذف", "امسح", "مسح", "شيل", "اشيل", "أشيل", "شال",
    "ازيل", "أزيل", "ازال", "إزالة", "ازالة", "ازل", "أزل",
    "احذفلي", "امسحلي", "شيللي", "remove", "delete",
)

_TABLE_EDIT_ROW_WORDS = (
    "صف", "صفوف", "الصف", "الصفوف", "سطر", "سطور", "السطر", "السطور",
    "row", "rows",
)

_TABLE_EDIT_COL_WORDS = (
    "عمود", "عامود", "العمود", "العامود", "اعمدة", "أعمدة", "الاعمدة",
    "الأعمدة", "عواميد", "column", "columns",
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
    text = str(message or "").strip().lower()
    if not text:
        return ""
    return text.translate(_AR_DIGITS_TABLE_EDIT)


def is_table_row_column_request(message: Any) -> bool:
    """True when the user asks to delete a row/column inside a slide table.

    «احذف الشريحة 5» is a slide deletion, not a table edit, so a bare
    slide/slide-deletion phrasing without any row/column word never matches.
    «احذف الصف الثالث من الشريحة 5» mentions a slide only as the location,
    so the row/column word decides.
    """
    normalized = _normalize_table_edit_text(message)
    if not normalized:
        return False
    has_verb = any(verb in normalized for verb in _TABLE_EDIT_VERBS)
    if not has_verb:
        return False
    has_row = any(word in normalized for word in _TABLE_EDIT_ROW_WORDS)
    has_col = any(word in normalized for word in _TABLE_EDIT_COL_WORDS)
    return bool(has_row or has_col)


def _ordinal_number_in_text(normalized: str) -> Union[int, None]:
    for variants, number in _TABLE_EDIT_ORDINALS:
        for variant in variants:
            if variant in normalized:
                return number
    return None


def _last_requested_in_text(normalized: str) -> bool:
    return any(word in normalized for word in _TABLE_EDIT_LAST_WORDS)


def _digit_after_keyword(normalized: str, keywords: Sequence[str]) -> Union[int, None]:
    for keyword in keywords:
        match = re.search(rf"{re.escape(keyword)}\s*(?:رقم\s*)?(\d{{1,3}})", normalized)
        if match:
            try:
                number = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if 1 <= number <= 200:
                return number
    generic = re.search(r"(?:رقم\s*)(\d{1,3})", normalized)
    if generic:
        try:
            number = int(generic.group(1))
        except (TypeError, ValueError):
            return None
        if 1 <= number <= 200:
            return number
    return None


def _extract_quoted_text(message: Any) -> str:
    raw = str(message or "")
    for pattern in (r'"([^"]{2,80})"', r"'([^']{2,80})'", r"«([^»]{2,80})»", r"“([^”]{2,80})”"):
        match = re.search(pattern, raw)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return ""


def _extract_row_text_hint(normalized: str, raw_message: Any) -> str:
    quoted = _extract_quoted_text(raw_message)
    if quoted:
        return quoted
    for marker in ("اللي فيه", "اللي فيها", "الذي فيه", "الذي يحتوي", "التي تحتوي",
                   "يحتوي على", "تحتوي على", "الخاص ب", "الخاصة ب", "الخاصه ب", "بعنوان", "باسم", "بإسم", "نصه"):
        if marker in normalized:
            tail = normalized.split(marker, 1)[1].strip()
            tail = re.split(r"[،,.؛;!؟?]", tail)[0].strip()
            words = [word for word in re.split(r"\s+", tail) if word and word not in _TABLE_EDIT_STOPWORDS]
            hint = " ".join(words[:6]).strip()
            if len(hint) >= 2:
                return hint
    return ""


def _extract_column_name_hint(normalized: str, raw_message: Any) -> str:
    quoted = _extract_quoted_text(raw_message)
    if quoted:
        return quoted
    for keyword in ("العمود", "العامود", "عمود", "عامود"):
        if keyword in normalized:
            tail = normalized.split(keyword, 1)[1].strip()
            tail = re.sub(r"^(?:رقم\s*\d+\s*)", "", tail).strip()
            tail = re.split(r"[،,.؛;!؟?]", tail)[0].strip()
            words = []
            for word in re.split(r"\s+", tail):
                if not word or word in _TABLE_EDIT_STOPWORDS:
                    if words:
                        break
                    continue
                if word.isdigit():
                    continue
                if any(v in word for v in ("صف", "سطر", "جدول", "شريح", "سلايد")):
                    break
                words.append(word)
                if len(words) >= 3:
                    break
            hint = " ".join(words).strip()
            hint = re.sub(r"^(?:اللي|الذي|التي|ذو|ذات)\s+", "", hint).strip()
            if len(hint) >= 2:
                return hint
    return ""


def parse_table_edit_request(message: Any) -> Union[Dict[str, Any], None]:
    """Parse «احذف الصف الثالث» / «شيل عمود السعر» into a structured target."""
    normalized = _normalize_table_edit_text(message)
    if not normalized:
        return None
    if not any(verb in normalized for verb in _TABLE_EDIT_VERBS):
        return None
    has_row = any(word in normalized for word in _TABLE_EDIT_ROW_WORDS)
    has_col = any(word in normalized for word in _TABLE_EDIT_COL_WORDS)
    # Ambiguous («احذف الصف والعمود») stays with the model so it can ask.
    if has_row and has_col:
        return None
    if not (has_row or has_col):
        return None
    kind = "row" if has_row else "column"
    keywords = _TABLE_EDIT_ROW_WORDS if kind == "row" else _TABLE_EDIT_COL_WORDS
    number = _digit_after_keyword(normalized, keywords)
    if number is None:
        ordinal = _ordinal_number_in_text(normalized)
        if ordinal is not None:
            number = ordinal
    is_last = _last_requested_in_text(normalized)
    if kind == "row":
        if number is None and not is_last:
            hint = _extract_row_text_hint(normalized, message)
            if not hint:
                return None
            return {"kind": "row", "by": "text", "text": hint}
        if is_last and number is None:
            return {"kind": "row", "by": "number", "number": "last"}
        return {"kind": "row", "by": "number", "number": int(number)}
    if number is not None:
        return {"kind": "column", "by": "number", "number": int(number)}
    name_hint = _extract_column_name_hint(normalized, message)
    if not name_hint:
        return None
    return {"kind": "column", "by": "name", "name": name_hint}


def _split_table_for_edit(table_html: str) -> Union[Dict[str, Any], None]:
    """Split one table into header cells and data rows for surgical deletion."""
    body_match = _TBODY_RE.search(table_html)
    if body_match:
        rows = _TR_RE.findall(body_match.group(2))
        if len(rows) < 1:
            return None
        thead_match = re.search(r"<thead\b[^>]*>[\s\S]*?</thead>", table_html, re.IGNORECASE)
        header_cells: List[str] = []
        if thead_match:
            header_cells = _TD_RE.findall(thead_match.group(0))
        else:
            first_row = _TR_RE.search(body_match.group(2))
            if first_row and re.search(r"<th\b", first_row.group(0), re.IGNORECASE):
                header_cells = _TD_RE.findall(first_row.group(0))
                rows = rows[1:]
                if not rows:
                    return None
        return {
            "kind": "tbody",
            "table_html": table_html,
            "body_match": body_match,
            "rows": rows,
            "header_cells": header_cells,
        }
    row_matches = list(_TR_RE.finditer(table_html))
    if not row_matches:
        return None
    thead_match = re.search(r"<thead\b[^>]*>[\s\S]*?</thead>", table_html, re.IGNORECASE)
    data_matches = [
        row_match for row_match in row_matches
        if not thead_match or not (thead_match.start() <= row_match.start() < thead_match.end())
    ]
    header_cells = []
    if thead_match:
        header_cells = _TD_RE.findall(thead_match.group(0))
    elif data_matches and re.search(r"<th\b", data_matches[0].group(0), re.IGNORECASE):
        header_cells = _TD_RE.findall(data_matches.pop(0).group(0))
    rows = [row_match.group(0) for row_match in data_matches]
    if not rows:
        return None
    return {
        "kind": "direct",
        "table_html": table_html,
        "row_matches": data_matches,
        "rows": rows,
        "header_cells": header_cells,
    }


def _row_has_merged_cells(row_html: str) -> bool:
    return bool(re.search(r"\b(?:colspan|rowspan)\s*=", row_html, re.IGNORECASE))


def _remove_data_row_from_table(table_html: str, data_index: int) -> Union[str, None]:
    """Remove the Nth data row (0-based, header excluded). Returns new table or None."""
    info = _split_table_for_edit(table_html)
    if not info or data_index < 0 or data_index >= len(info["rows"]):
        return None
    target_row = info["rows"][data_index]
    if _row_has_merged_cells(target_row):
        return None
    if len(info["rows"]) <= 1:
        return None
    if info["kind"] == "tbody":
        body_match = info["body_match"]
        kept = [row for idx, row in enumerate(info["rows"]) if idx != data_index]
        prefix = table_html[:body_match.start(2)]
        suffix = table_html[body_match.end(2):]
        return prefix + "".join(kept) + suffix
    row_matches = info["row_matches"]
    doomed = row_matches[data_index]
    return table_html[:doomed.start()] + table_html[doomed.end():]


def _remove_column_from_table(table_html: str, col_index: int) -> Union[str, None]:
    """Remove the Nth column (0-based, DOM order) from header and every data row."""
    if col_index < 0:
        return None
    if re.search(r"\b(?:colspan|rowspan)\s*=", table_html, re.IGNORECASE):
        return None
    changed = False

    def drop_cell(row_html: str) -> str:
        nonlocal changed
        cells = list(_TD_RE.finditer(row_html))
        if col_index >= len(cells):
            return row_html
        doomed = cells[col_index]
        changed = True
        return row_html[:doomed.start()] + row_html[doomed.end():]

    output = _TR_RE.sub(
        lambda match: drop_cell(match.group(0)),
        table_html,
    )
    if not changed:
        return None
    # The header row must keep at least one cell, and every data row must keep one.
    for row_html in _TR_RE.findall(output):
        if not _TD_RE.search(row_html):
            return None
    return output


def _candidate_tables(html: str) -> List[Tuple[Any, str]]:
    return [(match, match.group(0)) for match in _TABLE_RE.finditer(str(html or ""))]


def apply_table_row_column_edit(html: str, message: Any) -> Tuple[Union[str, None], str]:
    """Deterministically delete one table row/column named by the user.

    Returns (new_html, description) on success, or (None, reason) when the
    request is not a concrete row/column deletion. HTML-only: project facts
    are never touched, so preservation rules for source data still hold.
    """
    request = parse_table_edit_request(message)
    if not request:
        return None, "not_a_table_edit"
    source = str(html or "")
    candidates = _candidate_tables(source)
    if not candidates:
        return None, "no_table_in_slide"
    kind = request.get("kind")
    if kind == "row" and request.get("by") == "number":
        number = request.get("number")
        scored = []
        for match, table_html in candidates:
            info = _split_table_for_edit(table_html)
            if not info:
                continue
            scored.append((len(info["rows"]), match, table_html, info))
        if not scored:
            return None, "no_data_rows"
        scored.sort(key=lambda item: item[0], reverse=True)
        count, match, table_html, info = scored[0]
        target = (count - 1) if number == "last" else (int(number) - 1)
        if target < 0 or target >= count:
            return None, "row_number_out_of_range"
        updated_table = _remove_data_row_from_table(table_html, target)
        if not updated_table:
            return None, "row_not_removable"
        updated = source[:match.start()] + updated_table + source[match.end():]
        label = "الأخير" if number == "last" else f"رقم {number}"
        return updated, f"تم حذف الصف {label} من جدول الشريحة (الترقيم يشمل صفوف البيانات دون رأس الجدول) مع الحفاظ على بقية الصفوف والتنسيق."
    if kind == "row" and request.get("by") == "text":
        needle = re.sub(r"\s+", " ", str(request.get("text") or "")).strip()
        if len(needle) < 2:
            return None, "row_text_too_short"
        needle_folded = needle.casefold()
        for match, table_html in candidates:
            info = _split_table_for_edit(table_html)
            if not info:
                continue
            hit = -1
            for idx, row_html in enumerate(info["rows"]):
                cleaned = _clean_text(row_html).casefold()
                if needle_folded in cleaned or needle_folded in str(row_html).casefold():
                    hit = idx
                    break
            if hit < 0:
                # Fall back to a looser word-overlap match for inflected Arabic.
                needle_words = [word for word in re.split(r"\s+", needle_folded) if len(word) >= 3]
                if needle_words:
                    for idx, row_html in enumerate(info["rows"]):
                        cleaned = _clean_text(row_html).casefold()
                        if needle_words and all(word in cleaned for word in needle_words[:2]):
                            hit = idx
                            break
            if hit >= 0:
                updated_table = _remove_data_row_from_table(table_html, hit)
                if not updated_table:
                    return None, "row_not_removable"
                updated = source[:match.start()] + updated_table + source[match.end():]
                return updated, f"تم حذف الصف الذي يحتوي على «{needle}» من جدول الشريحة مع الحفاظ على بقية الصفوف والتنسيق."
        return None, "row_text_not_found"
    if kind == "column" and request.get("by") == "number":
        number = int(request.get("number") or 0)
        scored = []
        for match, table_html in candidates:
            info = _split_table_for_edit(table_html)
            if not info or not info["rows"]:
                continue
            widths = [len(_TD_RE.findall(row)) for row in info["rows"]]
            if info["header_cells"]:
                widths.append(len(info["header_cells"]))
            scored.append((max(widths) if widths else 0, match, table_html))
        if not scored:
            return None, "no_columns"
        scored.sort(key=lambda item: item[0], reverse=True)
        width, match, table_html = scored[0]
        target = number - 1
        if target < 0 or target >= width:
            return None, "column_number_out_of_range"
        updated_table = _remove_column_from_table(table_html, target)
        if not updated_table:
            return None, "column_not_removable"
        updated = source[:match.start()] + updated_table + source[match.end():]
        return updated, f"تم حذف العمود رقم {number} من جدول الشريحة من كل الصفوف (بما فيها رأس الجدول) مع الحفاظ على بقية الأعمدة والتنسيق."
    if kind == "column" and request.get("by") == "name":
        needle = re.sub(r"\s+", " ", str(request.get("name") or "")).strip()
        if len(needle) < 2:
            return None, "column_name_too_short"
        needle_folded = needle.casefold()
        for match, table_html in candidates:
            info = _split_table_for_edit(table_html)
            if not info:
                continue
            header_texts = [_clean_text(cell) for cell in info["header_cells"]]
            header_folded = [text.casefold() for text in header_texts]
            hit = -1
            for idx, text in enumerate(header_folded):
                if needle_folded in text or text in needle_folded:
                    hit = idx
                    break
            if hit < 0 and header_folded:
                needle_words = [word for word in re.split(r"\s+", needle_folded) if len(word) >= 3]
                for idx, text in enumerate(header_folded):
                    if needle_words and any(word in text for word in needle_words):
                        hit = idx
                        break
            if hit < 0:
                # No header row: probe the first data row positionally.
                first_cells = [_clean_text(cell).casefold() for cell in _TD_RE.findall(info["rows"][0])]
                for idx, text in enumerate(first_cells):
                    if needle_folded in text:
                        hit = idx
                        break
            if hit >= 0:
                updated_table = _remove_column_from_table(table_html, hit)
                if not updated_table:
                    return None, "column_not_removable"
                updated = source[:match.start()] + updated_table + source[match.end():]
                return updated, f"تم حذف عمود «{needle}» من جدول الشريحة من كل الصفوف مع الحفاظ على بقية الأعمدة والتنسيق."
        return None, "column_name_not_found"
    return None, "unsupported_table_edit"


def materially_changed(before: Any, after: Any, response_text: Any = "") -> bool:
    response = str(response_text or "")
    if "تم الحفاظ على تصميم الشريحة" in response or "تعذر التعديل التلقائي" in response:
        return False
    normalize = lambda value: re.sub(r"\s+", " ", str(value or "")).strip()
    return normalize(before) != normalize(after)


def _load_workspace(payload: Dict[str, Any], namespace: Dict[str, Any]):
    from flask import g

    cleaner = namespace.get("clean_project_data", lambda value: value if isinstance(value, dict) else {})
    project_data = cleaner(payload.get("projectData") or {})
    slides = copy.deepcopy(payload.get("slidesData")) if isinstance(payload.get("slidesData"), list) else []
    presentation_id = payload.get("presentationId")
    if presentation_id and (not slides or not project_data):
        presentation = namespace["db"].get_presentation(presentation_id, tenant_id=g.tenant_id)
        if presentation:
            if not project_data:
                try:
                    project_data = cleaner(json.loads(presentation.get("project_data") or "{}"))
                except (TypeError, ValueError):
                    project_data = {}
            if not slides:
                try:
                    slides = json.loads(presentation.get("slides_data") or "[]")
                except (TypeError, ValueError):
                    slides = []
    creative_images = copy.deepcopy(payload.get("creativeImages")) if isinstance(payload.get("creativeImages"), dict) else {}
    if not creative_images and isinstance(project_data.get("tenantCreativeImages"), dict):
        creative_images = copy.deepcopy(project_data["tenantCreativeImages"])
    try:
        project_data, creative_images = namespace["_hydrate_map_assets_for_request"](
            project_data, creative_images, g.tenant_id, presentation_id=presentation_id
        )
    except Exception:
        pass
    try:
        creative_images = namespace["_augment_generation_images"](
            creative_images, project_data, g.tenant_id
        )
    except Exception:
        pass
    branding = namespace["db"].get_branding(g.tenant_id) or {}
    return project_data, slides, creative_images, branding, presentation_id


def _canonicalize_single_slide_html(slide_html: str, full_html: str = "") -> str:
    html = str(slide_html or "").strip()
    if not html:
        return html

    style_blocks = ""
    if full_html:
        styles = re.findall(r'<style\b[^>]*>[\s\S]*?</style>', full_html, re.IGNORECASE)
        if styles and not re.search(r'<style\b', html, re.IGNORECASE):
            style_blocks = "\n".join(styles) + "\n"

    def replace_slide_class(match):
        attrs_before = match.group(1)
        attrs_after = match.group(4)
        return f'<div{attrs_before}class="slide"{attrs_after}'

    normalized = re.sub(
        r'<div(\b[^>]*?)\bclass\s*=\s*(["\'])([^"\']*?\bslide\b[^"\']*?)\2([^>]*>)',
        replace_slide_class,
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    if 'class="slide"' not in normalized and "class='slide'" not in normalized:
        normalized = f'<div class="slide" style="width:1280px;height:720px;position:relative;overflow:hidden;box-sizing:border-box;">{normalized}</div>'

    return style_blocks + normalized


def _auto_heal_workspace_slides(slides: Sequence[Any], namespace: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    if not isinstance(slides, list):
        return []
    healed: List[Dict[str, Any]] = []

    for idx, slide in enumerate(slides):
        if not isinstance(slide, dict):
            continue
        html = str(slide.get("html") or "").strip()
        if not html:
            continue

        extracted = []
        try:
            import design_templates
            extracted = design_templates.extract_slide_elements(html)
        except Exception:
            pass

        if not extracted:
            m = re.findall(r'<div\b[^>]*\bclass\s*=\s*["\'][^"\']*\bslide\b[^"\']*["\'][\s\S]*?</div>', html, re.IGNORECASE)
            if m:
                extracted = m

        if len(extracted) > 1:
            base_title = slide.get("title") or f"شريحة {idx + 1}"
            clean_title = re.sub(r"\s*[-–—]\s*الجزء\s+\d+.*$", "", base_title).strip()
            for part_num, part_html in enumerate(extracted, start=1):
                part_slide = copy.deepcopy(slide)
                part_slide["title"] = f"{clean_title} - الجزء {part_num}"
                part_slide["html"] = _canonicalize_single_slide_html(part_html, full_html=html)
                part_slide["_designer_keep_html"] = True
                healed.append(part_slide)
        elif len(extracted) == 1:
            slide_copy = copy.deepcopy(slide)
            slide_copy["html"] = _canonicalize_single_slide_html(extracted[0], full_html=html)
            healed.append(slide_copy)
        else:
            slide_copy = copy.deepcopy(slide)
            wrapped = f'<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;box-sizing:border-box;background:#ffffff;">{html}</div>'
            slide_copy["html"] = wrapped
            healed.append(slide_copy)

    return healed


def _target_indexes(payload: Dict[str, Any], slides: Sequence[Dict[str, Any]], namespace: Dict[str, Any] = None) -> List[int]:
    total = len(slides)
    message = str(payload.get("message") or "")
    scope = str(payload.get("target") or payload.get("scope") or "").lower()
    all_request = scope == "all" or bool(re.search(
        r"كل\s*(?:الشرائح|الشرايح|السلايدات)|جميع\s*الشرائح|العرض\s*(?:كامل|كله)",
        message,
        re.IGNORECASE,
    ))
    if all_request:
        return list(range(total))
    candidates = payload.get("indexes") if isinstance(payload.get("indexes"), list) else []
    if not candidates:
        candidates = payload.get("focusIndexes") if isinstance(payload.get("focusIndexes"), list) else []
    indexes: List[int] = []
    for value in candidates:
        try:
            index = int(value) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < total and index not in indexes:
            indexes.append(index)
    if indexes:
        return indexes
    normalized = message.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    match = re.search(r"(?:الشريحة|شريحة|السلايد|سلايد)\s*(?:رقم\s*)?(\d+)", normalized, re.IGNORECASE)
    if match:
        index = int(match.group(1)) - 1
        if 0 <= index < total:
            return [index]

    # Match slide titles and section names
    norm_msg = re.sub(r'[^\w\s]', ' ', normalized).lower()
    for idx, s in enumerate(slides):
        if not isinstance(s, dict):
            continue
        title = (s.get("title") or "").strip().lower()
        if len(title) >= 3:
            norm_title = re.sub(r'[^\w\s]', ' ', title).strip()
            if norm_title and norm_title in norm_msg:
                return [idx]
        section = (s.get("section_key") or s.get("sectionKey") or "").strip().lower()
        engine = (namespace or {}).get("slide_engine")
        sec_titles = getattr(engine, "PRESENTATION_SECTION_TITLES", {}) if engine else {}
        sec_title = sec_titles.get(section, "")
        if not sec_title:
            default_sec_titles = {
                "executive_summary": "الملخص التنفيذي",
                "financial": "الدراسة المالية",
                "location": "تحليل الموقع",
                "land": "تحليل الأرض",
                "market": "تحليل السوق",
                "overview": "نبذة عن المشروع",
                "components": "مكونات المشروع",
                "swot_risks": "تحليل المخاطر",
                "timeline": "الجدول الزمني",
                "team": "فريق العمل",
            }
            sec_title = default_sec_titles.get(section, "")
        if sec_title and len(sec_title) >= 3:
            norm_sec = re.sub(r'[^\w\s]', ' ', sec_title).strip().lower()
            if norm_sec and norm_sec in norm_msg:
                return [idx]

    try:
        current = int(payload.get("slideIndex", 0))
    except (TypeError, ValueError):
        current = 0
    return [max(0, min(total - 1, current))] if total else []


def _finalize_slides(slides, project_data, creative_images, branding, namespace):
    from flask import g

    try:
        slides = namespace["slide_engine"].renumber_presentation_slides(
            slides,
            branding=branding,
            project_data=project_data,
            tenant_id=g.tenant_id,
            allow_all_maps=True,
            creative_images=creative_images,
        )
    except Exception as error:
        print(f"[DESIGNER RELIABILITY RENUMBER] {error}")
    return slides


def _workspace_response(message, slides, creative_images, actions, focus, payload, namespace):
    from flask import jsonify

    slides = _auto_heal_workspace_slides(slides, namespace=namespace)
    validation = {"valid": True, "issues": []}
    validator = namespace.get("_validate_workspace_data")
    if validator:
        validation = validator({"slidesData": slides})
        if not validation.get("valid"):
            slides = _auto_heal_workspace_slides(slides, namespace=namespace)
            validation = validator({"slidesData": slides})
            if not validation.get("valid"):
                return jsonify({
                    "success": False,
                    "error": "تم رفض التعديل لأن العرض يحتوي على شرائح غير صالحة",
                    "validation": validation,
                }), 422
    return jsonify({
        "success": True,
        "data": {
            "action": "workspace_update",
            "response": message,
            "slidesData": slides,
            "creativeImages": creative_images,
            "actions": actions,
            "validation": validation,
            "memory": str(payload.get("memory") or "")[:4000],
            "focusIndexes": focus,
            "saved": False,
        },
    })


def _handle_image_descriptions(payload, namespace):
    project_data, slides, creative_images, branding, _ = _load_workspace(payload, namespace)
    if not slides:
        from flask import jsonify
        return jsonify({"success": False, "error": "لا توجد شرائح مفتوحة لتنفيذ الطلب"}), 400
    descriptions = collect_image_descriptions(project_data, creative_images)
    indexes = _target_indexes(payload, slides)
    changed = []
    added = 0
    for index in indexes:
        slide = slides[index] if isinstance(slides[index], dict) else {}
        updated, count, _ = add_missing_image_descriptions(slide.get("html", ""), descriptions)
        if count:
            slide["html"] = updated
            slide["_designer_keep_html"] = True
            slides[index] = slide
            changed.append(index)
            added += count
    slides = _finalize_slides(slides, project_data, creative_images, branding, namespace)
    if added:
        message = f"تمت إضافة {added} من أوصاف الصور المحفوظة إلى الصور التي كان وصفها غير ظاهر."
        status = "success"
    elif descriptions:
        message = "كل الصور المطابقة لها أوصاف ظاهرة بالفعل؛ لم تتم إضافة نص مكرر."
        status = "noop"
    else:
        message = "لا توجد أوصاف صور محفوظة ومطابقة للصور الحالية في بيانات المشروع."
        status = "failed"
    return _workspace_response(
        message,
        slides,
        creative_images,
        [{"tool": "apply_image_descriptions", "status": status, "indexes": changed, "descriptions_added": added}],
        [index + 1 for index in (changed or indexes)],
        payload,
        namespace,
    )


def _handle_split(payload, namespace, original_call=None):
    from flask import jsonify, g, current_app

    project_data, slides, creative_images, branding, presentation_id = _load_workspace(payload, namespace)
    if not slides:
        return jsonify({"success": False, "error": "لا توجد شرائح مفتوحة لتنفيذ الطلب"}), 400
    indexes = _target_indexes(payload, slides, namespace=namespace)
    if not indexes:
        if original_call:
            return _verify_original_result(original_call(), payload, namespace)
        return jsonify({"success": False, "error": "لم يتم تحديد الشريحة المطلوب تقسيمها"}), 400
    index = indexes[0]
    base = slides[index] if isinstance(slides[index], dict) else {}
    requested = split_request_parts(payload.get("message"))
    table_parts = split_table_slide(base.get("html", ""), base.get("title", f"شريحة {index + 1}"), requested)
    strategy = "balanced_table_rows"
    generated = []
    if table_parts:
        for part in table_parts:
            slide = copy.deepcopy(base)
            slide["title"] = part["title"]
            slide["html"] = part["html"]
            slide["_designer_keep_html"] = True
            generated.append(slide)
    else:
        try:
            flask_app = current_app._get_current_object()
        except Exception:
            flask_app = None
        tenant_id = getattr(g, "tenant_id", None) or project_data.get("tenant_id")

        parts = estimate_semantic_parts(base.get("html", ""), requested)
        strategy = "semantic"
        editor = namespace.get("_designer_edit_slide")
        if not editor:
            if original_call:
                return _verify_original_result(original_call(), payload, namespace)
            return jsonify({"success": False, "error": "محرر الشرائح غير متاح"}), 503
        total_after = len(slides) + parts - 1

        def render_part(number):
            def _invoke():
                title = f"{base.get('title', f'شريحة {index + 1}')} - الجزء {number} من {parts}"
                output, response = editor(
                    base.get("html", ""),
                    title,
                    semantic_part_instruction(number, parts),
                    index + number - 1,
                    project_data,
                    presentation_id,
                    branding,
                    tenant_id=tenant_id,
                    creative_images=creative_images,
                    slide_type=base.get("type", "content"),
                    total_slides=total_after,
                    content_source=base.get("content_source") or base.get("contentSource"),
                )
                return number, title, output, response

            if flask_app:
                with flask_app.app_context():
                    from flask import g
                    g.tenant_id = tenant_id
                    return _invoke()
            return _invoke()

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, parts)) as executor:
            futures = [executor.submit(render_part, number) for number in range(1, parts + 1)]
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as error:
                    print(f"[DESIGNER RELIABILITY SPLIT] {error}")
        results.sort(key=lambda item: item[0])
        if len(results) != parts or any(
            not materially_changed(base.get("html", ""), output, response)
            for _, _, output, response in results
        ):
            card_parts = split_cards_or_blocks(base.get("html", ""), base.get("title", f"شريحة {index + 1}"), parts)
            if card_parts and len(card_parts) >= 2:
                strategy = "balanced_cards_or_blocks"
                for part in card_parts:
                    slide = copy.deepcopy(base)
                    slide["title"] = part["title"]
                    slide["html"] = part["html"]
                    slide["_designer_keep_html"] = True
                    generated.append(slide)
            else:
                if original_call:
                    print("[DESIGNER RELIABILITY SPLIT] Fast split incomplete; delegating to full AI agent.")
                    return _verify_original_result(original_call(), payload, namespace)
                return _workspace_response(
                    "تعذر إنشاء كل أجزاء الشريحة دون فقد محتوى؛ تم الإبقاء على الشريحة الأصلية كما هي.",
                    slides,
                    creative_images,
                    [{"tool": "split_slide", "status": "failed", "reason": "incomplete_split"}],
                    [index + 1],
                    payload,
                    namespace,
                )
        else:
            for _, title, output, _ in results:
                slide = copy.deepcopy(base)
                slide["title"] = title
                slide["html"] = output
                slide["_designer_keep_html"] = True
                generated.append(slide)

    slides[index:index + 1] = generated
    slides = _finalize_slides(slides, project_data, creative_images, branding, namespace)
    if strategy == "balanced_table_rows":
        message = (
            f"تم تقسيم جدول الشريحة رقم {index + 1} إلى {len(generated)} شرائح متوازنة، "
            "مع تكرار رأس الجدول والحفاظ على كل صف مرة واحدة."
        )
    elif strategy == "balanced_cards_or_blocks":
        message = f"تم تقسيم عناصر ومحتوى الشريحة رقم {index + 1} إلى {len(generated)} شرائح متوازنة مع الحفاظ على كامل المحتوى."
    else:
        message = f"تم تقسيم الشريحة رقم {index + 1} فعليًا إلى {len(generated)} شرائح متوازنة حسب معنى المحتوى."
    focus = list(range(index + 1, index + len(generated) + 1))
    return _workspace_response(
        message,
        slides,
        creative_images,
        [{"tool": "split_slide", "status": "success", "split_index": index, "parts": len(generated), "strategy": strategy}],
        focus,
        payload,
        namespace,
    )


def _verify_original_result(result, payload, namespace):
    from flask import jsonify

    response = result[0] if isinstance(result, tuple) else result
    status_code = result[1] if isinstance(result, tuple) and len(result) > 1 else getattr(response, "status_code", 200)
    body = response.get_json(silent=True) if hasattr(response, "get_json") else None
    data = body.get("data") if isinstance(body, dict) else None
    actions = data.get("actions") if isinstance(data, dict) and isinstance(data.get("actions"), list) else []
    mutating = {
        "edit_slides", "edit_design_slide", "edit_design_slides", "generate_image",
        "generate_design_image", "insert_image_into_slide", "insert_canonical_map",
        "insert_map", "insert_financial_chart", "update_financial_chart", "insert_team_logo",
        "insert_company_logo_panel", "delete_slide", "remove_slide", "duplicate_slide",
        "clone_slide", "reorder_slides", "move_slide", "split_slide", "split_dense_slide",
        "create_slide", "create_design_slide", "merge_slides", "combine_slides",
        "apply_watermark", "remove_watermark", "apply_image_descriptions",
    }
    successful_mutations = [item for item in actions if item.get("tool") in mutating and item.get("status") == "success"]
    if not successful_mutations or not isinstance(data.get("slidesData"), list):
        return result
    _, before, _, _, _ = _load_workspace(payload, namespace)
    after = data["slidesData"]
    before_signature = [(item.get("title", ""), re.sub(r"\s+", " ", item.get("html", "")).strip()) for item in before if isinstance(item, dict)]
    after_signature = [(item.get("title", ""), re.sub(r"\s+", " ", item.get("html", "")).strip()) for item in after if isinstance(item, dict)]
    fallback_claim = "تم الحفاظ على تصميم الشريحة" in str(data.get("response") or "")
    if before_signature != after_signature and not fallback_claim:
        return result
    for item in successful_mutations:
        item["status"] = "failed"
        item["reason"] = "no_verified_change"
    data["response"] = "لم يتم تأكيد تغيير فعلي في العرض، لذلك لم تُسجل العملية كتعديل ناجح."
    return jsonify(body), status_code


def install(app, namespace: Dict[str, Any]) -> None:
    """Install queued designer jobs and deterministic command handlers."""

    if app.extensions.get("designer_chat_reliability"):
        return
    original = app.view_functions.get("api_designer_chat")
    if not original:
        raise RuntimeError("api_designer_chat route is not registered")
    require_auth = namespace["require_auth"]
    write_job = namespace["_write_job"]
    read_job = namespace["_read_job"]
    job_path = namespace["_job_path"]

    @wraps(original)
    def reliable_designer_chat():
        from flask import request

        payload = request.get_json(silent=True) or {}
        # Language interpretation belongs to the contextual planner. Deterministic
        # rendering remains available after it chooses an operation and its scope.
        return _verify_original_result(original(), payload, namespace)

    secured_designer_chat = require_auth(reliable_designer_chat)
    app.view_functions["api_designer_chat"] = secured_designer_chat

    def job_context(payload):
        project_data = payload.get("projectData") if isinstance(payload.get("projectData"), dict) else {}
        context = {
            "presentationId": payload.get("presentationId") or None,
            "draftId": project_data.get("draftId") or project_data.get("draft_id") or None,
        }
        # The retry key is valid only for the exact AI request. Hashing the complete payload
        # prevents a stale tab from reusing an old result after slides, facts, images, history or
        # attachments have changed, without storing a second copy of that large request on disk.
        identity = {
            key: value for key, value in payload.items()
            if key not in {"requestId", "_job_id"}
        }
        encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        context["requestHash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return context

    def claim_job(tenant_id, job_id, initial_payload):
        """Create one queued record across Gunicorn workers before starting the AI thread."""
        path = job_path(".designer_chat_jobs", tenant_id, job_id)
        claim_path = path + ".claim"
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                descriptor = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                existing = read_job(".designer_chat_jobs", tenant_id, job_id)
                if existing:
                    return False, existing
                try:
                    if time.time() - os.path.getmtime(claim_path) > 30:
                        os.unlink(claim_path)
                        continue
                except OSError:
                    pass
                time.sleep(0.025)
                continue
            try:
                existing = read_job(".designer_chat_jobs", tenant_id, job_id)
                if existing:
                    return False, existing
                write_job(".designer_chat_jobs", tenant_id, job_id, initial_payload)
                return True, initial_payload
            finally:
                os.close(descriptor)
                try:
                    os.unlink(claim_path)
                except OSError:
                    pass
        existing = read_job(".designer_chat_jobs", tenant_id, job_id)
        if existing:
            return False, existing
        raise RuntimeError("Designer chat job registration lock timed out")

    def run_job(flask_app, tenant_id, payload, job_id, authorization):
        payload_with_job = dict(payload)
        payload_with_job["_job_id"] = job_id
        job_record_context = job_context(payload)
        heartbeat_stop = threading.Event()

        def heartbeat():
            # Touching the published file does not race with its JSON contents. The status route
            # reads the mtime as a heartbeat, so a killed worker is distinguishable from a model
            # call that is still legitimately taking several minutes.
            path = job_path(".designer_chat_jobs", tenant_id, job_id)
            while not heartbeat_stop.wait(15):
                try:
                    os.utime(path, None)
                except OSError:
                    pass

        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        with flask_app.test_request_context(
            "/api/designer-chat",
            method="POST",
            json=payload_with_job,
            headers={
                "Authorization": authorization,
                "X-Designer-Job-Id": job_id,
            },
        ):
            try:
                write_job(".designer_chat_jobs", tenant_id, job_id, {
                    **job_record_context,
                    "status": "running", "success": True, "progress": 10,
                    "message": "جاري تنفيذ وتطبيق التعديل...",
                })
                result = flask_app.view_functions["api_designer_chat"]()
                response = result[0] if isinstance(result, tuple) else result
                status_code = result[1] if isinstance(result, tuple) and len(result) > 1 else response.status_code
                body = response.get_json(silent=True) or {}
                succeeded = 200 <= int(status_code) < 300 and body.get("success")
                response_data = body.get("data") if isinstance(body.get("data"), dict) else {}
                failure_reason = body.get("failureReason") or response_data.get("failureReason")
                final_payload = {
                    **body,
                    **job_record_context,
                    "status": "completed" if succeeded else "failed",
                    "success": bool(succeeded),
                    "progress": 100,
                    "message": "اكتمل تنفيذ تعديل العرض" if succeeded else body.get("error", "تعذر تعديل العرض"),
                }
                if failure_reason:
                    final_payload["failureReason"] = failure_reason
                write_job(".designer_chat_jobs", tenant_id, job_id, final_payload)
            except Exception as error:
                flask_app.logger.exception("Designer chat background job failed")
                write_job(".designer_chat_jobs", tenant_id, job_id, {
                    **job_record_context,
                    "status": "failed", "success": False, "progress": 100,
                    "error": f"تعذر تنفيذ تعديل العرض: {error}", "failureReason": "job_failed",
                })
            finally:
                heartbeat_stop.set()

    def queue_job():
        from flask import current_app, g, jsonify, request

        payload = request.get_json(silent=True) or {}
        if not str(payload.get("message") or "").strip():
            return jsonify({"success": False, "error": "الطلب فارغ"}), 400
        requested_id = str(payload.get("requestId") or "").strip()
        if requested_id and not re.fullmatch(r"[A-Za-z0-9-]{8,64}", requested_id):
            return jsonify({"success": False, "error": "معرف الطلب غير صالح"}), 400
        job_id = requested_id or str(uuid.uuid4())
        queued_context = job_context(payload)
        try:
            created, existing = claim_job(g.tenant_id, job_id, {
                **queued_context,
                "status": "queued", "success": True, "progress": 1,
                "message": "تم استلام طلب تعديل العرض",
            })
        except RuntimeError as error:
            app.logger.error("Designer chat job registration failed: %s", error)
            return jsonify({
                "success": False,
                "error": "تعذر تسجيل مهمة تعديل العرض مؤقتًا",
                "failureReason": "job_registration_failed",
            }), 503
        if not created:
            if existing.get("requestHash") and existing.get("requestHash") != queued_context["requestHash"]:
                return jsonify({
                    "success": False,
                    "error": "معرف الطلب مستخدم لمهمة تعديل أخرى",
                    "failureReason": "request_id_conflict",
                }), 409
            return jsonify({
                "success": True,
                "jobId": job_id,
                "status": existing.get("status") or "queued",
                "progress": existing.get("progress") or 1,
                "message": existing.get("message") or "مهمة تعديل العرض مسجلة",
                "reused": True,
            }), 202
        threading.Thread(
            target=run_job,
            args=(current_app._get_current_object(), g.tenant_id, payload, job_id, request.headers.get("Authorization", "")),
            daemon=True,
        ).start()
        return jsonify({
            "success": True, "jobId": job_id, "status": "queued", "progress": 1,
            "message": "بدأ تعديل العرض في الخلفية",
        }), 202

    def job_status(job_id):
        from flask import g, jsonify, request

        if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", str(job_id or "")):
            return jsonify({"success": False, "error": "معرف مهمة غير صالح"}), 400
        job = read_job(".designer_chat_jobs", g.tenant_id, job_id)
        if not job:
            return jsonify({
                "success": False, "status": "not_found",
                "error": "مهمة تعديل العرض غير موجودة أو انتهت صلاحيتها",
                "failureReason": "job_not_found",
            }), 404
        try:
            heartbeat_at = os.path.getmtime(job_path(".designer_chat_jobs", g.tenant_id, job_id))
        except OSError:
            heartbeat_at = float(job.get("updatedAt") or 0)
        response_job = dict(job)
        response_job["jobId"] = str(job_id)
        response_job["heartbeatAt"] = heartbeat_at
        if response_job.get("status") in {"queued", "running"} and heartbeat_at:
            response_job["stale"] = time.time() - heartbeat_at > 90
            if response_job["stale"]:
                response_job["message"] = "توقفت تحديثات مهمة تعديل العرض على الخادم"
        include_result = request.args.get("includeResult") == "1"
        if not include_result:
            response_job["resultReady"] = response_job.get("status") == "completed" and isinstance(response_job.get("data"), dict)
            response_job.pop("data", None)
        return jsonify(response_job)

    app.add_url_rule(
        "/api/designer-chat/jobs",
        endpoint="api_designer_chat_reliability_job",
        view_func=require_auth(queue_job),
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/designer-chat/jobs/<job_id>",
        endpoint="api_designer_chat_reliability_job_status",
        view_func=require_auth(job_status),
        methods=["GET"],
    )
    app.extensions["designer_chat_reliability"] = True
