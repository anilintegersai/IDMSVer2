"""Numbering and list-style remapping for merged content.

When content is copied from a source document into a destination document,
numbering definitions from the source must not overwrite the destination.
Instead, copied paragraphs are remapped to use the destination document's
existing bullet and numbered-list definitions so formatting stays consistent.
"""

from __future__ import annotations

import copy
from typing import Iterable

from lxml import etree

from app.core.namespaces import NSMAP, W_NS, w_tag


def _max_num_id(numbering_root: etree._Element | None) -> int:
    if numbering_root is None:
        return 0
    ids = []
    for num in numbering_root.findall("w:num", NSMAP):
        val = num.get(w_tag("numId"))
        if val and val.isdigit():
            ids.append(int(val))
    return max(ids) if ids else 0


def _max_abstract_num_id(numbering_root: etree._Element | None) -> int:
    if numbering_root is None:
        return 0
    ids = []
    for ab in numbering_root.findall("w:abstractNum", NSMAP):
        val = ab.get(w_tag("abstractNumId"))
        if val and val.isdigit():
            ids.append(int(val))
    return max(ids) if ids else 0


def ensure_numbering_part(pkg) -> etree._Element:
    from app.services.word.document_package import NUMBERING_XML

    if NUMBERING_XML not in pkg.list_parts():
        root = etree.Element(w_tag("numbering"), nsmap={"w": W_NS})
        pkg.set_xml(NUMBERING_XML, root)
    return pkg.get_xml(NUMBERING_XML)


def find_destination_list_num_ids(numbering_root: etree._Element) -> dict[str, int | None]:
    """Find representative numId values for bullet and decimal lists in destination."""
    result: dict[str, int | None] = {"bullet": None, "decimal": None}
    abstract_map: dict[str, str] = {}
    for ab in numbering_root.findall("w:abstractNum", NSMAP):
        ab_id = ab.get(w_tag("abstractNumId"))
        for lvl in ab.findall("w:lvl", NSMAP):
            num_fmt = lvl.find("w:numFmt", NSMAP)
            if num_fmt is not None and ab_id:
                fmt = num_fmt.get(w_tag("val"), "")
                if fmt == "bullet" and "bullet" not in abstract_map:
                    abstract_map["bullet"] = ab_id
                elif fmt == "decimal" and "decimal" not in abstract_map:
                    abstract_map["decimal"] = ab_id

    for num in numbering_root.findall("w:num", NSMAP):
        num_id = num.get(w_tag("numId"))
        ab_ref = num.find("w:abstractNumId", NSMAP)
        if ab_ref is None or not num_id:
            continue
        ab_val = ab_ref.get(w_tag("val"))
        for kind, ab_id in abstract_map.items():
            if ab_val == ab_id and result[kind] is None:
                result[kind] = int(num_id)
    return result


def _get_num_format(numbering_root: etree._Element, num_id: str) -> str | None:
    for num in numbering_root.findall("w:num", NSMAP):
        if num.get(w_tag("numId")) != num_id:
            continue
        ab_ref = num.find("w:abstractNumId", NSMAP)
        if ab_ref is None:
            continue
        ab_id = ab_ref.get(w_tag("val"))
        for ab in numbering_root.findall("w:abstractNum", NSMAP):
            if ab.get(w_tag("abstractNumId")) != ab_id:
                continue
            lvl = ab.find("w:lvl", NSMAP)
            if lvl is not None:
                fmt = lvl.find("w:numFmt", NSMAP)
                if fmt is not None:
                    return fmt.get(w_tag("val"))
    return None


def remap_numbering_in_elements(
    elements: Iterable[etree._Element],
    source_numbering: etree._Element | None,
    dest_numbering: etree._Element,
) -> None:
    """Remap numId/ilvl on copied paragraphs to destination list styles."""
    dest_lists = find_destination_list_num_ids(dest_numbering)

    for element in elements:
        for para in element.iter(w_tag("p")):
            ppr = para.find("w:pPr", NSMAP)
            if ppr is None:
                continue
            num_pr = ppr.find("w:numPr", NSMAP)
            if num_pr is None:
                continue

            num_id_el = num_pr.find("w:numId", NSMAP)
            if num_id_el is None:
                continue

            old_num_id = num_id_el.get(w_tag("val"), "")
            fmt = _get_num_format(source_numbering, old_num_id) if source_numbering is not None else None

            if fmt == "bullet" and dest_lists["bullet"] is not None:
                num_id_el.set(w_tag("val"), str(dest_lists["bullet"]))
            elif fmt in ("decimal", "lowerLetter", "upperLetter", "lowerRoman", "upperRoman"):
                if dest_lists["decimal"] is not None:
                    num_id_el.set(w_tag("val"), str(dest_lists["decimal"]))
                else:
                    ppr.remove(num_pr)
            else:
                # Unknown or heading numbering — strip paragraph-level numbering
                # so destination styles control appearance
                ppr.remove(num_pr)


def remap_heading_styles(
    elements: Iterable[etree._Element],
    base_level: int,
    source_heading_styles: dict[str, int] | None = None,
    dest_heading_styles: dict[str, int] | None = None,
) -> None:
    """Re-level copied heading paragraphs to the destination's heading styles.

    Word decouples the ``styleId`` from the visible name, so source headings are
    routinely stored under opaque ids like ``31`` ("heading 3"). We therefore:

    * resolve each source paragraph's level via ``source_heading_styles``
      (falling back to a literal ``HeadingN`` id), and
    * rewrite ``pStyle`` to the destination's *own* style id for the target
      level via ``dest_heading_styles`` (falling back to ``HeadingN``).

    The copied block's shallowest heading is anchored at ``base_level`` and
    relative depth is preserved, so a subsection copied under a level-2 heading
    nests correctly instead of assuming the block starts at level 1.
    """
    import re

    dest_level_to_style: dict[int, str] = {}
    if dest_heading_styles:
        for style_id, lvl in dest_heading_styles.items():
            dest_level_to_style.setdefault(lvl, style_id)

    def _source_level(val: str) -> int | None:
        if source_heading_styles and val in source_heading_styles:
            return source_heading_styles[val]
        m = re.match(r"Heading(\d+)", val, re.IGNORECASE)
        return int(m.group(1)) if m else None

    headings: list[tuple[etree._Element, int]] = []
    for element in elements:
        for para in element.iter(w_tag("p")):
            ppr = para.find("w:pPr", NSMAP)
            if ppr is None:
                continue
            style = ppr.find("w:pStyle", NSMAP)
            if style is None:
                continue
            level = _source_level(style.get(w_tag("val"), ""))
            if level is not None:
                headings.append((style, level))

    if not headings:
        return
    min_src = min(level for _, level in headings)
    for style, level in headings:
        new_level = min(9, max(1, base_level + (level - min_src)))
        new_style = dest_level_to_style.get(new_level, f"Heading{new_level}")
        style.set(w_tag("val"), new_style)


def strip_foreign_numbering_from_non_lists(elements: Iterable[etree._Element]) -> None:
    """Remove numPr from normal paragraphs that are not list items."""
    for element in elements:
        for para in element.iter(w_tag("p")):
            ppr = para.find("w:pPr", NSMAP)
            if ppr is None:
                continue
            style = ppr.find("w:pStyle", NSMAP)
            style_val = style.get(w_tag("val"), "") if style is not None else ""
            if style_val.lower().startswith("heading"):
                continue
            num_pr = ppr.find("w:numPr", NSMAP)
            if num_pr is not None:
                ilvl = num_pr.find("w:ilvl", NSMAP)
                # Keep if explicitly a list item (has ilvl); otherwise remove orphan numbering
                if ilvl is None:
                    ppr.remove(num_pr)
