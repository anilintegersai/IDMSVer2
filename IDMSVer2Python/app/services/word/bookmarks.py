"""Bookmark discovery and manipulation in Word documents."""

from __future__ import annotations

import re
from typing import Iterator
from xml.etree import ElementTree as ET

from lxml import etree

from app.core.exceptions import BookmarkNotFoundError
from app.core.namespaces import NSMAP, W_NS, w_tag
from app.services.word.document_package import STYLES_XML, DocxPackage, clone_element


def find_bookmark_start(body: etree._Element, name: str) -> etree._Element | None:
    for bm in body.iter(w_tag("bookmarkStart")):
        if bm.get(w_tag("name")) == name:
            return bm
    return None


def find_bookmark_paragraph(body: etree._Element, name: str) -> etree._Element | None:
    bm = find_bookmark_start(body, name)
    if bm is None:
        return None
    parent = bm.getparent()
    while parent is not None and parent.tag != w_tag("body"):
        if parent.tag == w_tag("p"):
            return parent
        parent = parent.getparent()
    return bm.getparent()


def get_body_elements_between_bookmarks(
    body: etree._Element, start_name: str, stop_name: str
) -> list[etree._Element]:
    """Return top-level body elements from start bookmark paragraph through stop bookmark paragraph."""
    start_para = find_bookmark_paragraph(body, start_name)
    stop_para = find_bookmark_paragraph(body, stop_name)
    if start_para is None or stop_para is None:
        raise BookmarkNotFoundError(
            f"Bookmarks not found: start={start_name!r}, stop={stop_name!r}"
        )

    elements: list[etree._Element] = []
    capturing = False
    for child in list(body):
        if child is start_para:
            capturing = True
        if capturing:
            elements.append(clone_element(child))
        if child is stop_para:
            break
    return elements


def get_next_bookmark_id(body: etree._Element) -> int:
    ids = []
    for bm in body.iter(w_tag("bookmarkStart")):
        val = bm.get(w_tag("id"))
        if val and val.isdigit():
            ids.append(int(val))
    return (max(ids) if ids else 0) + 1


def create_zero_length_bookmark(name: str, bookmark_id: int) -> tuple[etree._Element, etree._Element]:
    start = etree.Element(w_tag("bookmarkStart"), {w_tag("id"): str(bookmark_id), w_tag("name"): name})
    end = etree.Element(w_tag("bookmarkEnd"), {w_tag("id"): str(bookmark_id)})
    return start, end


def insert_elements_before(anchor: etree._Element, elements: list[etree._Element]) -> None:
    parent = anchor.getparent()
    if parent is None:
        raise BookmarkNotFoundError("Cannot insert: anchor has no parent.")
    index = parent.index(anchor)
    for offset, element in enumerate(elements):
        parent.insert(index + offset, element)


def paragraph_text(paragraph: etree._Element) -> str:
    texts = []
    for node in paragraph.iter(w_tag("t")):
        if node.text:
            texts.append(node.text)
    return "".join(texts)


def is_toc_entry(paragraph: etree._Element) -> bool:
    ppr = paragraph.find("w:pPr", NSMAP)
    if ppr is None:
        return False
    style = ppr.find("w:pStyle", NSMAP)
    if style is not None:
        val = style.get(w_tag("val"), "")
        if val and "TOC" in val.upper():
            return True
    for fld in paragraph.iter(w_tag("instrText")):
        if fld.text and "TOC" in fld.text.upper():
            return True
    return False


def get_toc_items(body: etree._Element) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    sl_no = 0
    # Use iter() rather than findall("w:p"): modern Word wraps the table of
    # contents in a <w:sdt> block, so the TOC entry paragraphs are NOT direct
    # children of <w:body>. findall (direct children only) would miss them.
    for para in body.iter(w_tag("p")):
        if not is_toc_entry(para):
            continue
        text = paragraph_text(para).strip()
        if not text:
            continue
        sl_no += 1
        page_ref = ""
        tabs = para.findall(".//w:tab", NSMAP)
        if tabs:
            page_ref = paragraph_text(para).split("\t")[-1].strip()
        items.append(
            {
                "sl_no": str(sl_no),
                "item_text": text.split("\t")[0].strip(),
                "page_ref": page_ref,
                "page_no": page_ref,
            }
        )
    return items


def build_heading_level_map(styles_root: etree._Element | None) -> dict[str, int]:
    """Map paragraph ``styleId`` -> heading level (1-9) for heading styles.

    Word decouples the styleId from the visible name: a "Heading 3" style is
    routinely stored under an opaque styleId such as ``31``. Matching the
    literal string ``HeadingN`` against the styleId therefore misses real
    headings. We resolve a style as a heading when either its styleId looks like
    ``HeadingN`` *or* its ``<w:name>`` is the built-in ``heading N``.
    """
    result: dict[str, int] = {}
    if styles_root is None:
        return result
    for style in styles_root.iter(w_tag("style")):
        sid = style.get(w_tag("styleId"))
        if not sid:
            continue
        level: int | None = None
        m = re.match(r"heading\s*([1-9])$", sid, re.IGNORECASE)
        if m:
            level = int(m.group(1))
        else:
            name_el = style.find("w:name", NSMAP)
            name = name_el.get(w_tag("val"), "") if name_el is not None else ""
            m = re.match(r"heading\s*([1-9])$", name.strip(), re.IGNORECASE)
            if m:
                level = int(m.group(1))
        if level is not None:
            result[sid] = level
    return result


def get_heading_style_map(pkg: DocxPackage) -> dict[str, int]:
    """Convenience: build the styleId -> heading-level map for a package."""
    if STYLES_XML not in pkg.list_parts():
        return {}
    return build_heading_level_map(pkg.get_xml(STYLES_XML))


def get_section_number_from_bookmark(
    body: etree._Element, bookmark_name: str, heading_styles: dict[str, int] | None = None
) -> str:
    """Derive the hierarchical section number of the bookmark's paragraph.

    Walks every paragraph in document order (including SDT-nested content),
    maintaining a counter per heading level. The number returned is that of the
    nearest heading at or before the bookmark, e.g. ``"4.2.1"``.
    """
    para = find_bookmark_paragraph(body, bookmark_name)
    if para is None:
        return ""
    counters: list[int] = []
    last_section = ""
    for p in body.iter(w_tag("p")):
        level = _heading_level(p, heading_styles)
        if level is not None and level >= 1:
            if level <= len(counters):
                del counters[level:]
                counters[level - 1] += 1
            else:
                while len(counters) < level:
                    counters.append(1)
            last_section = ".".join(str(n) for n in counters)
        if p is para:
            return last_section
    return last_section


def _heading_level(
    paragraph: etree._Element, heading_styles: dict[str, int] | None = None
) -> int | None:
    ppr = paragraph.find("w:pPr", NSMAP)
    if ppr is None:
        return None
    style = ppr.find("w:pStyle", NSMAP)
    if style is None:
        return None
    val = style.get(w_tag("val"), "")
    # Preferred: resolve the styleId against the document's style definitions
    # (handles opaque ids like '31' whose name is "heading 3").
    if heading_styles and val in heading_styles:
        return heading_styles[val]
    # Fallback for documents that use conventional 'HeadingN' style ids.
    match = re.match(r"Heading(\d+)", val, re.IGNORECASE)
    if match:
        return int(match.group(1))
    # NOTE: TOC styles (TOC1..TOC9) are deliberately NOT treated as headings.
    # They live inside the TOC's <w:sdt> and would otherwise corrupt the
    # section-number walk once we iterate nested paragraphs.
    return None


def get_heading_level_at_bookmark(
    body: etree._Element, bookmark_name: str, heading_styles: dict[str, int] | None = None
) -> int:
    para = find_bookmark_paragraph(body, bookmark_name)
    if para is None:
        return 1
    level = _heading_level(para, heading_styles)
    if level is not None:
        return level
    # Walk forward to the bookmark, tracking the nearest preceding heading.
    for p in body.iter(w_tag("p")):
        if p is para:
            break
        lvl = _heading_level(p, heading_styles)
        if lvl is not None:
            level = lvl
    return level or 1


# ---------------------------------------------------------------------------
# Rich TOC tree (section number + text + page + bookmark anchor + level)
# ---------------------------------------------------------------------------

def paragraph_text_with_tabs(paragraph: etree._Element) -> str:
    """Like :func:`paragraph_text` but preserves tab stops as ``\\t``.

    TOC entries are laid out as ``<sectionNumber><tab><title><tab><page>``;
    the tabs are ``<w:tab/>`` elements (not text), so a plain text extraction
    glues the parts together. Preserving tabs lets us split the three fields.
    """
    out: list[str] = []
    for node in paragraph.iter():
        if node.tag == w_tag("t"):
            if node.text:
                out.append(node.text)
        elif node.tag == w_tag("tab"):
            out.append("\t")
    return "".join(out)


def get_toc_style_map(pkg: DocxPackage) -> dict[str, int]:
    """Map paragraph ``styleId`` -> TOC level for ``TOC1``..``TOC9`` styles.

    Handles opaque style ids (e.g. ``11``/``23``) by resolving the style name
    ("toc 1".."toc 9") from styles.xml, mirroring the heading-style approach.
    """
    result: dict[str, int] = {}
    if STYLES_XML not in pkg.list_parts():
        return result
    styles_root = pkg.get_xml(STYLES_XML)
    for style in styles_root.iter(w_tag("style")):
        sid = style.get(w_tag("styleId"))
        if not sid:
            continue
        m = re.match(r"toc\s*([1-9])$", sid, re.IGNORECASE)
        if not m:
            name_el = style.find("w:name", NSMAP)
            name = name_el.get(w_tag("val"), "") if name_el is not None else ""
            m = re.match(r"toc\s*([1-9])$", name.strip(), re.IGNORECASE)
        if m:
            result[sid] = int(m.group(1))
    return result


def _toc_entry_fields(paragraph: etree._Element, toc_style_map: dict[str, int]) -> dict | None:
    """Parse one TOC entry paragraph into its component fields.

    Returns ``None`` for entries without a bookmark anchor (e.g. the
    "Table of Contents" heading), since those cannot participate in a merge.
    """
    anchor = None
    for hl in paragraph.iter(w_tag("hyperlink")):
        a = hl.get(w_tag("anchor"))
        if a:
            anchor = a
            break
    if anchor is None:
        return None

    tokens = [t.strip() for t in paragraph_text_with_tabs(paragraph).split("\t") if t.strip()]
    if not tokens:
        return None

    page_no = ""
    if len(tokens) >= 2 and re.fullmatch(r"\d+|[ivxlcdm]+", tokens[-1], re.IGNORECASE):
        page_no = tokens[-1]
        tokens = tokens[:-1]

    rest = " ".join(tokens).strip()
    section_number = ""
    m = re.match(r"^(\d+(?:\.\d+)*)\s*(.*)$", rest)
    if m:
        section_number, rest = m.group(1), m.group(2).strip()

    if section_number:
        level = section_number.count(".") + 1
    else:
        ppr = paragraph.find("w:pPr", NSMAP)
        st = ppr.find("w:pStyle", NSMAP) if ppr is not None else None
        sid = st.get(w_tag("val")) if st is not None else ""
        level = toc_style_map.get(sid, 1)

    return {
        "bookmark": anchor,
        "section_number": section_number,
        "text": rest,
        "page_no": page_no,
        "level": max(1, level),
    }


def get_toc_flat(pkg: DocxPackage) -> list[dict]:
    """Ordered flat list of TOC entries with fields + document order index."""
    body = pkg.body
    toc_style_map = get_toc_style_map(pkg)
    flat: list[dict] = []
    order = 0
    for p in body.iter(w_tag("p")):
        if not is_toc_entry(p):
            continue
        info = _toc_entry_fields(p, toc_style_map)
        if info is None:
            continue
        info["order"] = order
        order += 1
        flat.append(info)
    return flat


def get_toc_tree(pkg: DocxPackage) -> list[dict]:
    """Hierarchical TOC: nested nodes by level, each carrying its bookmark."""
    roots: list[dict] = []
    stack: list[dict] = []  # nodes on the current ancestor path
    for info in get_toc_flat(pkg):
        node = {**info, "children": []}
        while stack and stack[-1]["level"] >= node["level"]:
            stack.pop()
        (stack[-1]["children"] if stack else roots).append(node)
        stack.append(node)
    return roots


def get_section_elements(
    body: etree._Element, start_name: str, stop_name: str | None = None
) -> list[etree._Element]:
    """Clone top-level body elements for a section: from the start bookmark's
    paragraph up to (but NOT including) the stop bookmark's paragraph.

    ``stop_name=None`` captures through the end of the body, excluding the
    body-level ``<w:sectPr>``. This yields a heading plus all of its descendant
    content (the next same-or-higher heading is the stop boundary).
    """
    start_para = find_bookmark_paragraph(body, start_name)
    if start_para is None:
        raise BookmarkNotFoundError(f"Bookmark not found: start={start_name!r}")
    stop_para = find_bookmark_paragraph(body, stop_name) if stop_name else None

    elements: list[etree._Element] = []
    capturing = False
    for child in list(body):
        if child is start_para:
            capturing = True
        if stop_para is not None and child is stop_para:
            break
        if child.tag == w_tag("sectPr"):
            break
        if capturing:
            elements.append(clone_element(child))
    return elements


def append_elements_before_sectpr(body: etree._Element, elements: list[etree._Element]) -> None:
    """Append elements at the end of the body, before the section properties."""
    sectpr = next((c for c in body if c.tag == w_tag("sectPr")), None)
    if sectpr is not None:
        index = list(body).index(sectpr)
        for offset, element in enumerate(elements):
            body.insert(index + offset, element)
    else:
        for element in elements:
            body.append(element)
