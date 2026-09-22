

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


def _strip_table_units(text: str) -> str:
    t = re.sub(r"[\(\[\{].*?[\)\]\}]", "", str(text or ""))
    t = re.sub(r"(?<!\w)(?:ر\.?س\.?|ريال(?:\s+سعودي)?|م[٢2²]|متر\s+مربع|نسب[ةه])(?!\w)", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _strip_definite_article(text: str) -> str:
    """Strip Arabic definite article 'ال' from words for flexible column header matching."""
    words = []
    for w in str(text or "").split():
        if w.startswith("وال") and len(w) > 4:
            words.append("و" + w[3:])
        elif w.startswith("ال") and len(w) > 3:
            words.append(w[2:])
        else:
            words.append(w)
    return " ".join(words)


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
                    clean_needle = _normalize_table_edit_text(_strip_table_units(needle))
                    for index, row in enumerate(rows):
                        labels = [_table_node_text(cell) for cell in row["cells"]]
                        contains = target.get("contains") and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", " ".join(labels))
                        clean_labels = [_normalize_table_edit_text(_strip_table_units(cell_text)) for cell_text in labels]
                        if needle and (needle in labels or contains or needle in clean_labels or (clean_needle and clean_needle in clean_labels)):
                            hits.append((table_index, table, info, index))
                else:
                    indexes = {index for row in info["headers"] for index, cell in enumerate(row["cells"])
                               if needle and _table_node_text(cell) == needle}
                    if not indexes and needle:
                        clean_needle = _normalize_table_edit_text(_strip_table_units(needle))
                        indexes = {index for row in info["headers"] for index, cell in enumerate(row["cells"])
                                   if _normalize_table_edit_text(_strip_table_units(_table_node_text(cell))) in (needle, clean_needle)}
                    if not indexes and needle:
                        no_al_needle = _strip_definite_article(needle)
                        no_al_clean = _strip_definite_article(_normalize_table_edit_text(_strip_table_units(needle)))
                        indexes = {index for row in info["headers"] for index, cell in enumerate(row["cells"])
                                   if _strip_definite_article(_table_node_text(cell)) == no_al_needle
                                   or _strip_definite_article(_normalize_table_edit_text(_strip_table_units(_table_node_text(cell)))) in (no_al_needle, no_al_clean)}
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
        "update_slide_image",
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
                "payload": {"data": payload},
                "actor": {
                    "user_id": getattr(g, "user_id", None),
                    "user_name": getattr(g, "user_name", None),
                    "user_role": getattr(g, "user_role", None),
                },
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

    # The restart-resume sweep in app.py re-dispatches orphaned jobs through this worker.
    namespace["_designer_chat_run_job"] = run_job

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
        response_job = {k: v for k, v in job.items()
                        if k not in ("payload", "actor", "pid")}
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
