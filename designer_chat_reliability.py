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
from html.parser import HTMLParser
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


_AR_DIGITS_TABLE_EDIT = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹أإآٱى", "01234567890123456789ااااي"
)

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
    text = str(message or "").casefold().translate(_AR_DIGITS_TABLE_EDIT)
    text = re.sub(r"[\u0640\u064b-\u065f\u0670]", "", text)
    return re.sub(r"\s+", " ", text).strip()


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
    if not value or any(ch.isdigit() or ch in (chr(10), chr(13)) for ch in value):
        return None
    return {"by": "name", "name": value}


def detect_table_edit_request(message: Any) -> Dict[str, Any]:
    """Detect before routing to an AI planner, including unsafe/unsupported edits.

    handled=True is a routing barrier, not evidence that an edit succeeded.
    Call apply_table_delete_request only with the original user message. Slide
    selection belongs to the caller; numbers here refer only to rows/columns.
    """
    text = _normalize_table_edit_text(message)
    # Words in quoted labels cannot introduce a second operation or axis.
    masked = _TABLE_QUOTES_RE.sub(lambda match: " " * len(match.group()), text)
    axes = list(_TABLE_AXIS_RE.finditer(masked))
    if any(word in masked.split() for word in ("والصف", "والعمود", "وصفوف", "وأعمدة", "واعمدة")):
        axes.append(None)
    verbs = list(_TABLE_DELETE_RE.finditer(masked))
    cell = re.search(r"(?<!\w)(?:الخليه|الخلية|خليه|خلية|الخلايا|خلايا|cells?)(?!\w)", masked)
    edit = re.search(r"(?<!\w)(?:و)?(?:اضف|اضافة|عدل|تعديل|غير|استبدل|add|edit|replace|change)(?!\w)", masked)
    whole_table = _TABLE_SCOPE_RE.search(masked)
    handled = bool((verbs or edit or re.search(r"تحذف|تمسح", masked)) and (axes or cell or whole_table))
    result = {"handled": handled, "operation": "delete" if verbs else "edit",
              "supported": False, "reason": "not_a_table_edit", "request": None}
    if not handled:
        return result
    result["reason"] = "unsupported_table_edit"
    if re.search(r"(?<!\w)(?:لا|لاتحذف|متشيلش|متمسحش|ليس|بدون|دون|not|never|don't)(?!\w)", masked):
        result["reason"] = "negated_or_conditional_request"
        return result
    if re.search(r"(?<!\w)(?:اذا|لو|if|unless)(?!\w)", masked):
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
        r"(?<!\w)(?:(?:من|في|in|from|on)\s+)?(?:ال)?(?:شريحه|شريحة|شرايح|شرائح|سلايد|slides?)(?!\w)",
        _TABLE_QUOTES_RE.sub(lambda m: " " * len(m.group()), tail),
    )
    if slide_scope:
        tail = tail[:slide_scope.start()]
    scopes = list(_TABLE_SCOPE_RE.finditer(masked))
    if len(scopes) > 1:
        result["reason"] = "ambiguous_table_request"
        return result
    if scopes:
        scope = scopes[0]
        if scope.start() > axis.end():
            selector_text = text[scope.end():]
            selector_text = re.split(r"\s+(?:من|في|in|from|on)\s+(?:ال)?(?:شريح[هة]|شرائح|slides?)\b", selector_text)[0]
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
    tail = re.sub(r"\s+(?:فقط|فضلا|لو سمحت|please)\s*$", "", tail.strip())
    # Permit the common reversed form «احذف آخر صف» / 'delete last row'.
    before_axis = text[verbs[0].end():axis.start()].strip()
    if before_axis:
        if tail.strip() or _table_selector(before_axis) is None:
            result["reason"] = "ambiguous_table_request"
            return result
        tail = before_axis
    contains = bool(re.match(r"^(?:اللي فيه|الذي يحتوي|يحتوي على|containing)\s+", tail.strip()))
    tail = re.sub(r"^(?:اللي فيه|الذي يحتوي(?: على)?|يحتوي على|containing|الخاص ب|بعنوان|باسم|بإسم|باسم|اسمه|عنوانه|named)\s*", "", tail.strip())
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


def is_table_row_column_request(message: Any) -> bool:
    """Legacy routing guard, now also catches blocked table/cell edit intent."""
    return detect_table_edit_request(message)["handled"]


def parse_table_edit_request(message: Any) -> Union[Dict[str, Any], None]:
    """Legacy parsed target shape; use detection to distinguish blocked requests."""
    return detect_table_edit_request(message)["request"]


class _TableSourceParser(HTMLParser):
    """Read source spans without serializing/reformatting any surviving HTML.

    Omitted/misnested table tags and nested tables are deliberately not repaired.
    Browser HTML recovery is not reliable evidence of the intended table grid.
    """

    _void = frozenset("area base br col embed hr img input link meta param source track wbr".split())
    _structural = frozenset("table caption colgroup col thead tbody tfoot tr td th".split())

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.lines = [0] + [match.end() for match in re.finditer(chr(10), source)]
        self.stack: List[Dict[str, Any]] = []
        self.tables: List[Dict[str, Any]] = []
        self.inert = 0
        self.feed(source)
        self.close()
        for node in self.stack:
            if node.get("table") is not None:
                node["table"]["invalid"] = True

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1] if self.stack else None
        table = next((node for node in reversed(self.stack) if node["tag"] == "table" and "rows" in node), None)
        node = {"tag": tag, "attrs": dict(attrs), "start": self._offset(),
                "end": None, "parent": parent, "table": table, "children": [], "text": []}
        if tag in ("template", "textarea", "title"):
            self.inert += 1
        if tag == "table" and not self.inert:
            node.update(table=node, rows=[], invalid=False, nested=table is not None, cols=[], captions=[])
            if table is not None:
                table["nested"] = True
            table = node
            self.tables.append(node)
        if table is not None:
            if len(attrs) != len(dict(attrs)):
                table["invalid"] = True
            expected = {"tr": {"table", "thead", "tbody", "tfoot"},
                        "td": {"tr"}, "th": {"tr"}, "thead": {"table"},
                        "tbody": {"table"}, "tfoot": {"table"}, "caption": {"table"},
                        "colgroup": {"table"}, "col": {"table", "colgroup"}}
            if tag in expected and (not parent or parent["tag"] not in expected[tag]):
                table["invalid"] = True
            if tag == "tr":
                node["cells"] = []
                node["group"] = parent["tag"] if parent else "table"
                table["rows"].append(node)
            elif tag in ("td", "th") and parent and parent["tag"] == "tr":
                parent["cells"].append(node)
            elif tag in ("col", "colgroup"):
                table["cols"].append(node)
            elif tag == "caption":
                table["captions"].append(node)
            # Non-cell content in a table grid gets foster-parented by browsers.
            elif tag not in self._structural and parent and parent["tag"] in {"table", "thead", "tbody", "tfoot", "tr", "colgroup"}:
                table["invalid"] = True
        if parent:
            parent["children"].append(node)
        if tag in self._void:
            node["end"] = node["start"] + len(self.get_starttag_text())
        else:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._void:
            if self.stack and self.stack[-1].get("table") is not None:
                self.stack[-1]["table"]["invalid"] = True
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        found = next((index for index in range(len(self.stack) - 1, -1, -1)
                      if self.stack[index]["tag"] == tag), None)
        if found is None:
            if self.stack and self.stack[-1].get("table") is not None:
                self.stack[-1]["table"]["invalid"] = True
            return
        closing = self.stack[found:]
        if len(closing) > 1:
            for node in closing:
                if node.get("table") is not None:
                    node["table"]["invalid"] = True
        end = self.source.find(">", self._offset()) + 1
        for node in closing:
            node["end"] = end
            if node["tag"] in ("template", "textarea", "title"):
                self.inert -= 1
        del self.stack[found:]

    def handle_data(self, data):
        if not self.stack:
            return
        if any(node["tag"] in {"script", "style", "template", "textarea", "title"} for node in self.stack):
            return
        parent = self.stack[-1]
        if data.strip() and parent["tag"] in {"table", "thead", "tbody", "tfoot", "tr", "colgroup"}:
            if parent.get("table") is not None:
                parent["table"]["invalid"] = True
        for node in self.stack:
            if node["tag"] in {"td", "th", "caption"}:
                node["text"].append(data)


def _table_node_text(node: Dict[str, Any]) -> str:
    # Text chunks split only by inline markup (<br>, <span>, <b>, ...) must not glue
    # together: «نقطة التسمية<br>المقياس» is one header reading «نقطة التسمية المقياس»,
    # not «نقطة التسميةالمقياس». Joining with a space keeps exact-name matching working
    # for multi-line headers; the normalizer collapses any surplus whitespace.
    return _normalize_table_edit_text(" ".join(node["text"]))


def _table_edit_info(table: Dict[str, Any], source: str) -> Dict[str, Any]:
    rows = table["rows"]
    headers = [row for row in rows if row["group"] == "thead"]
    if not headers:
        for row in rows:
            if row["group"] == "tfoot":
                continue
            if row["cells"] and all(cell["tag"] == "th" and cell["attrs"].get("scope") != "row" for cell in row["cells"]):
                headers.append(row)
            else:
                break
    header_ids = {id(row) for row in headers}
    data_rows = [row for row in rows if id(row) not in header_ids and row["group"] != "tfoot"]
    return {"kind": "source_spans", "table_html": source[table["start"]:table["end"]],
            "table": table, "data_rows": data_rows, "headers": headers,
            "rows": [source[row["start"]:row["end"]] for row in data_rows],
            "header_cells": [source[cell["start"]:cell["end"]] for row in headers for cell in row["cells"]]}


def _col_span_value(node: Dict[str, Any]) -> Union[int, None]:
    """A <col>/<colgroup> span as an int, or None when it is not a plain single column."""
    raw = node.get("attrs", {}).get("span", "1")
    if not re.fullmatch(r"1", str(raw).strip()):
        return None
    return 1


def _column_layout(table: Dict[str, Any]) -> Union[List[Dict[str, Any]], None]:
    """Expand <col>/<colgroup> specs to one node per table column, or None when complex.

    Only width/style-only layouts qualify: every <col> covers exactly one column, every
    <colgroup> is closed and either holds <col> children or covers one column itself.
    Anything else (spans, unclosed groups, stray nodes) keeps the column delete blocked,
    because the matching <col> cannot be removed by pure span deletion.
    """
    cols = table.get("cols") or []
    if not cols:
        return []
    sequence: List[Dict[str, Any]] = []
    for node in cols:
        if not isinstance(node, dict):
            return None
        if node.get("end") is None:
            return None
        parent = node.get("parent") or {}
        if node.get("tag") == "col":
            if parent.get("tag") not in ("table", "colgroup"):
                return None
            if _col_span_value(node) != 1:
                return None
            if parent.get("tag") == "colgroup":
                # Covered through the group below; counting it here would double-count.
                continue
            sequence.append(node)
        elif node.get("tag") == "colgroup":
            if parent.get("tag") != "table":
                return None
            children = [child for child in node.get("children", [])
                        if isinstance(child, dict) and child.get("tag") == "col"]
            if children:
                if "span" in node.get("attrs", {}) and str(node["attrs"]["span"]).strip() != "1":
                    return None
                for child in children:
                    if child.get("end") is None or _col_span_value(child) != 1:
                        return None
                    sequence.append(child)
            else:
                if _col_span_value(node) != 1:
                    return None
                sequence.append(node)
        else:
            return None
    return sequence


def _table_safety_reason(table: Dict[str, Any], kind: str) -> str:
    if table["nested"]:
        return "nested_table_unsupported"
    if table["invalid"] or table["end"] is None or any(not row["cells"] for row in table["rows"]):
        return "malformed_table"
    for row in table["rows"]:
        for cell in row["cells"]:
            for attr in ("rowspan", "colspan"):
                if attr in cell["attrs"] and str(cell["attrs"][attr]).strip() != "1":
                    return "merged_cells_unsupported"
    if kind == "column":
        if table["cols"]:
            widths = {len(row["cells"]) for row in table["rows"]}
            layout = _column_layout(table)
            # A width-only <colgroup> is fine: the matching <col> is removed together
            # with the cells. Anything else (spans, unclosed groups, count mismatch)
            # stays blocked so column widths cannot silently shift onto other columns.
            if layout is None or len(widths) != 1 or len(layout) != next(iter(widths)):
                return "column_layout_unsupported"
        if len({len(row["cells"]) for row in table["rows"]}) > 1:
            return "non_rectangular_table"
    return ""


def _split_table_for_edit(table_html: str) -> Union[Dict[str, Any], None]:
    tables = _TableSourceParser(table_html).tables
    if len(tables) != 1 or _table_safety_reason(tables[0], "row"):
        return None
    return _table_edit_info(tables[0], table_html)


def _delete_source_spans(source: str, spans: Sequence[Tuple[int, int]]) -> str:
    for start, end in sorted(set(spans), reverse=True):
        source = source[:start] + source[end:]
    return source


def _remove_data_row_from_table(table_html: str, data_index: int) -> Union[str, None]:
    info = _split_table_for_edit(table_html)
    if not info or not 0 <= data_index < len(info["data_rows"]) or len(info["data_rows"]) <= 1:
        return None
    row = info["data_rows"][data_index]
    return _delete_source_spans(table_html, [(row["start"], row["end"])])


def _remove_column_from_table(table_html: str, col_index: int) -> Union[str, None]:
    result = apply_table_delete_request(table_html, f"delete column {col_index + 1}")
    return result["html"] if result["changed"] else None


def apply_table_delete_request(html: str, message: Any) -> Dict[str, Any]:
    """Atomic surgical deletion with an explicit routing outcome.

    status is not_applicable, blocked or applied. html is ALWAYS the original
    on failure. Every handled outcome must stop generative fallthrough. Row
    numbering excludes semantic headers and tfoot; columns use DOM order,
    including row-label columns in RTL tables. Names are normalized exact cell
    labels (or unique explicit 'containing' row phrases), never fuzzy matches.
    No full-table/last-data-row/last-column deletion is inferred here: an explicit
    whole-table request is handled but blocked for separate confirmation.
    changes lists removed source spans against the ORIGINAL HTML.
    """
    source = str(html or "")
    detection = detect_table_edit_request(message)
    result = {"handled": detection["handled"], "status": "blocked" if detection["handled"] else "not_applicable",
              "changed": False, "html": source, "reason": detection["reason"],
              "request": detection["request"], "description": "", "changes": []}
    if not detection["supported"]:
        return result
    request = detection["request"]
    kind = request["kind"]
    tables = _TableSourceParser(source).tables
    if not tables:
        result["reason"] = "no_table_in_slide"
        return result
    candidates = list(enumerate(tables))
    selector = request.get("table")
    if selector:
        if selector["by"] == "number":
            index = len(tables) - 1 if selector["number"] == "last" else selector["number"] - 1
            candidates = [(index, tables[index])] if 0 <= index < len(tables) else []
        else:
            needle = _normalize_table_edit_text(selector["name"])
            candidates = [(index, table) for index, table in candidates if needle in
                          [_normalize_table_edit_text(table["attrs"].get(key)) for key in ("id", "aria-label", "data-table-name")]
                          + [_table_node_text(node) for node in table["captions"]]]
        if len(candidates) != 1:
            result["reason"] = "ambiguous_table" if candidates else "table_not_found"
            return result
    targets = request.get("targets") or [request]
    if len(candidates) > 1 and any(target["by"] == "number" for target in targets):
        result["reason"] = "ambiguous_table"
        return result
    matches = []
    for target in targets:
        hits = []
        for table_index, table in candidates:
            safety = _table_safety_reason(table, kind)
            # Do not silently ignore an unsafe table and select another one.
            if safety:
                result["reason"] = safety
                return result
            info = _table_edit_info(table, source)
            rows = info["data_rows"]
            width = len(table["rows"][0]["cells"]) if table["rows"] else 0
            if target["by"] == "number":
                count = len(rows) if kind == "row" else width
                index = count - 1 if target["number"] == "last" else target["number"] - 1
                if 0 <= index < count:
                    hits.append((table_index, table, info, index))
            else:
                needle = _normalize_table_edit_text(target.get("text") or target.get("name"))
                if kind == "row":
                    for index, row in enumerate(rows):
                        labels = [_table_node_text(cell) for cell in row["cells"]]
                        contains = target.get("contains") and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", " ".join(labels))
                        if needle and (needle in labels or contains):
                            hits.append((table_index, table, info, index))
                else:
                    indexes = {index for row in info["headers"] for index, cell in enumerate(row["cells"])
                               if needle and _table_node_text(cell) == needle}
                    hits.extend((table_index, table, info, index) for index in sorted(indexes))
        if len(hits) != 1:
            result["reason"] = "ambiguous_table_target" if hits else (
                f"{kind}_number_out_of_range" if target["by"] == "number" else f"{kind}_name_not_found")
            return result
        matches.append(hits[0])
    if len({match[0] for match in matches}) != 1:
        result["reason"] = "ambiguous_table"
        return result
    table_index, table, info, _ = matches[0]
    indexes = sorted({match[3] for match in matches})
    count = len(info["data_rows"]) if kind == "row" else len(table["rows"][0]["cells"])
    if len(indexes) >= count:
        result["reason"] = "would_empty_table"
        return result
    doomed = ([info["data_rows"][index] for index in indexes] if kind == "row" else
              [row["cells"][index] for row in table["rows"] for index in indexes])
    if kind == "column" and table.get("cols"):
        # A width-only <colgroup> stays consistent only when the matching <col> leaves
        # together with the cells; otherwise the surviving columns inherit wrong widths.
        # (Safety above already validated the layout; this re-check is defensive.)
        layout = _column_layout(table)
        if layout is None or len(layout) != count:
            result["reason"] = "column_layout_unsupported"
            return result
        seen_col_ids = set()
        for index in indexes:
            node = layout[index]
            if id(node) not in seen_col_ids:
                seen_col_ids.add(id(node))
                doomed.append(node)
    changes = [{"start": node["start"], "end": node["end"], "kind": kind,
                "tableIndex": table_index, "removedHtml": source[node["start"]:node["end"]]} for node in doomed]
    description = "تم حذف الصفوف المحددة مع الحفاظ على بقية المحتوى والتنسيق." if kind == "row" else "تم حذف الأعمدة المحددة مع الحفاظ على بقية المحتوى والتنسيق."
    result.update(status="applied", changed=True, reason="", description=description, changes=changes,
                  html=_delete_source_spans(source, [(node["start"], node["end"]) for node in doomed]))
    return result


def apply_table_row_column_edit(html: str, message: Any) -> Tuple[Union[str, None], str]:
    """Compatible tuple API. A None result MUST NOT trigger a broad AI rewrite."""
    result = apply_table_delete_request(html, message)
    return (result["html"], result["description"]) if result["changed"] else (None, result["reason"])


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
        # Snapshot BEFORE the inner handler runs: api_designer_chat edits the very same
        # slidesData list/dicts in place (request.get_json is cached per request), so reading
        # "before" afterwards always equals "after" and every genuine edit was downgraded to
        # «لم يتم تأكيد تغيير فعلي» while the client discarded the correct slidesData.
        pristine_slides = copy.deepcopy(payload.get("slidesData")) if isinstance(payload.get("slidesData"), list) else []
        result = original()
        verify_payload = dict(payload)
        verify_payload["slidesData"] = pristine_slides
        # Language interpretation belongs to the contextual planner. Deterministic
        # rendering remains available after it chooses an operation and its scope.
        return _verify_original_result(result, verify_payload, namespace)

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
