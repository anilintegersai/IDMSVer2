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


def get_elements_between(start: etree._Element, end: etree._Element) -> list[etree._Element]:
    """Return all elements between start and end (exclusive)."""
    parent = start.getparent()
    if parent is None or parent != end.getparent():
        return []
    
    elements: list[etree._Element] = []
    capturing = False
    for child in parent:
        if child is start:
            capturing = True
            continue
        if child is end:
            break
        if capturing:
            elements.append(child)
    return elements


def is_element_between(element: etree._Element, start: etree._Element, end: etree._Element | None) -> bool:
    """Check if element is between start and end (exclusive)."""
    if end is None:
        # If no end, check if element comes after start
        parent = start.getparent()
        if parent is None:
            return False
        found_start = False
        for child in parent:
            if child is start:
                found_start = True
            elif found_start and child is element:
                return True
        return False
    
    parent = start.getparent()
    if parent is None or parent != element.getparent() or parent != end.getparent():
        return False
    
    found_start = False
    for child in parent:
        if child is start:
            found_start = True
        elif found_start and child is element:
            return True
        elif child is end:
            break
    return False


def find_bookmark_paragraph_by_element(body: etree._Element, bookmark_start: etree._Element) -> etree._Element | None:
    """Find the paragraph containing a bookmark start element."""
    parent = bookmark_start.getparent()
    while parent is not None and parent.tag != w_tag("body"):
        if parent.tag == w_tag("p"):
            return parent
        parent = parent.getparent()
    return None


def get_bookmark_for_paragraph(body: etree._Element, paragraph: etree._Element) -> str | None:
    """Get the bookmark name for a paragraph."""
    for bm in paragraph.iter(w_tag("bookmarkStart")):
        name = bm.get(w_tag("name"))
        if name:
            return name
    return None


def get_element_after_bookmark(body: etree._Element, bookmark_name: str) -> etree._Element | None:
    """Get the element immediately after the bookmark end."""
    bookmark_end = body.find(f".//w:bookmarkEnd[@w:name='{bookmark_name}']", namespaces=NSMAP)
    if bookmark_end is None:
        return None
    
    # Find the next sibling after the bookmark end
    parent = bookmark_end.getparent()
    if parent is None:
        return None
    
    index = parent.index(bookmark_end)
    if index + 1 < len(parent):
        return parent[index + 1]
    
    # If no sibling in parent, look for next paragraph in body
    para = find_bookmark_paragraph(body, bookmark_name)
    if para is None:
        return None
    
    parent_body = para.getparent()
    if parent_body is None:
        return None
    
    para_index = parent_body.index(para)
    if para_index + 1 < len(parent_body):
        return parent_body[para_index + 1]
    
    return None


def find_next_heading(body: etree._Element, start_para: etree._Element, heading_styles: dict[str, int]) -> etree._Element | None:
    """Find the next heading paragraph after start_para."""
    parent = start_para.getparent()
    if parent is None:
        return None
    
    found_start = False
    for child in parent:
        if child is start_para:
            found_start = True
        elif found_start:
            if _heading_level(child, heading_styles) is not None:
                return child
    return None


def find_previous_heading(body: etree._Element, start_para: etree._Element, heading_styles: dict[str, int]) -> etree._Element | None:
    """Find the previous heading paragraph before start_para."""
    parent = start_para.getparent()
    if parent is None:
        return None
    
    previous_heading = None
    for child in parent:
        if child is start_para:
            break
        if _heading_level(child, heading_styles) is not None:
            previous_heading = child
    return previous_heading


def get_heading_text(paragraph: etree._Element) -> str:
    """Get the text content of a heading paragraph."""
    return paragraph_text(paragraph)


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


# ---------------------------------------------------------------------------
# Heading renumbering after section insertion
# ---------------------------------------------------------------------------

_SECTION_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)(\s+)(.*)$", re.DOTALL)


def _update_heading_number(para: etree._Element, new_number: str) -> bool:
    """Replace the section-number prefix in a heading paragraph.

    Preserves formatting by only mutating ``<w:t>`` text nodes, never
    restructuring ``<w:r>`` elements. Returns ``True`` when the heading
    already carried a section number and was updated."""
    text_nodes = [n for n in para.iter(w_tag("t")) if n.text]
    if not text_nodes:
        return False

    full_text = "".join(t.text or "" for t in text_nodes)
    m = _SECTION_NUMBER_RE.match(full_text)
    if not m:
        return False

    old_num = m.group(1)
    space = m.group(2)
    prefix_len = len(old_num) + len(space)

    # Strip the old number+space from the beginning of the text-node sequence.
    to_remove = prefix_len
    for node in text_nodes:
        txt = node.text or ""
        if len(txt) <= to_remove:
            node.text = ""
            to_remove -= len(txt)
        else:
            node.text = txt[to_remove:]
            to_remove = 0
            break

    # Prepend the new number to the first text node.
    text_nodes[0].text = new_number + space + (text_nodes[0].text or "")
    return True


def document_has_numbered_headings(
    body: etree._Element, heading_styles: dict[str, int] | None = None
) -> bool:
    """Return ``True`` when at least one heading paragraph starts with a
    ``1.2.3`` style section number."""
    for para in body.iter(w_tag("p")):
        level = _heading_level(para, heading_styles)
        if level is None:
            continue
        text = paragraph_text(para).strip()
        if _SECTION_NUMBER_RE.match(text):
            return True
    return False


def renumber_headings_after_insert(
    body: etree._Element,
    heading_styles: dict[str, int] | None,
    inserted_para: etree._Element,
) -> str | None:
    """Recalculate section numbers for all headings from *inserted_para*
    onwards and update their text when they already carry a number.

    Returns the computed section number for the inserted heading, or
    ``None`` when the document does not use numbered headings."""
    if not document_has_numbered_headings(body, heading_styles):
        return None

    counters: list[int] = []
    found_inserted = False
    inserted_number: str | None = None

    for para in body.iter(w_tag("p")):
        level = _heading_level(para, heading_styles)
        if level is None:
            continue

        # Advance counters
        if level <= len(counters):
            del counters[level:]
            counters[level - 1] += 1
        else:
            while len(counters) < level:
                counters.append(1)

        current_number = ".".join(str(n) for n in counters)

        if para is inserted_para:
            found_inserted = True
            inserted_number = current_number
            # New heading gets the number unconditionally (it has none yet).
            _prepend_number_to_heading(para, current_number)
        elif found_inserted:
            # Only update existing headings that already have a number.
            _update_heading_number(para, current_number)

    return inserted_number


def _prepend_number_to_heading(para: etree._Element, number: str) -> None:
    """Prepend ``number`` + space to the first text node of a heading.
    Safe for newly-created headings that do not yet carry a section number."""
    for node in para.iter(w_tag("t")):
        if node.text is not None or node.getparent() is not None:
            node.text = number + " " + (node.text or "")
            break
    else:
        # No text node found – create one inside the first run.
        first_run = para.find(w_tag("r"), NSMAP)
        if first_run is not None:
            t = etree.SubElement(first_run, w_tag("t"))
            t.text = number + " "
        else:
            run = etree.SubElement(para, w_tag("r"))
            t = etree.SubElement(run, w_tag("t"))
            t.text = number + " "


# ---------------------------------------------------------------------------
# TOC helpers
# ---------------------------------------------------------------------------

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
