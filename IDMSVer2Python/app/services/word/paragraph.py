"""Paragraph insertion (plain and HTML formatted)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag
from lxml import etree

from app.config import Settings
from app.core.namespaces import NSMAP, w_tag
from app.services.word import bookmarks, metadata
from app.services.word.document_package import DOCUMENT_XML, DocxPackage


@dataclass
class InsertParagraphRequest:
    document_path: str
    insert_before_bookmark: str
    text: str
    highlight: bool = False
    track_in_history: bool = False


def _shading_properties(color: str) -> etree._Element:
    ppr = etree.Element(w_tag("pPr"))
    shd = etree.SubElement(ppr, w_tag("shd"))
    shd.set(w_tag("val"), "clear")
    shd.set(w_tag("color"), "auto")
    shd.set(w_tag("fill"), color)
    return ppr


def _text_paragraph(text: str, shade: str | None) -> etree._Element:
    para = etree.Element(w_tag("p"))
    if shade:
        para.append(_shading_properties(shade))
    for line in text.split("\n"):
        run = etree.SubElement(para, w_tag("r"))
        t = etree.SubElement(run, w_tag("t"))
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = line
    return para


def _append_run(parent: etree._Element, text: str, *, bold: bool = False, italic: bool = False) -> None:
    run = etree.SubElement(parent, w_tag("r"))
    if bold or italic:
        rpr = etree.SubElement(run, w_tag("rPr"))
        if bold:
            etree.SubElement(rpr, w_tag("b"))
        if italic:
            etree.SubElement(rpr, w_tag("i"))
    t = etree.SubElement(run, w_tag("t"))
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text


def _html_to_paragraphs(html: str, shade: str | None) -> list[etree._Element]:
    soup = BeautifulSoup(html, "html.parser")
    paragraphs: list[etree._Element] = []

    def handle_block(tag: Tag) -> etree._Element:
        para = etree.Element(w_tag("p"))
        if shade:
            para.append(_shading_properties(shade))

        def walk(node):
            if isinstance(node, NavigableString):
                text = str(node)
                if text:
                    _append_run(para, text)
            elif isinstance(node, Tag):
                if node.name in ("b", "strong"):
                    _append_run(para, node.get_text(), bold=True)
                elif node.name in ("i", "em"):
                    _append_run(para, node.get_text(), italic=True)
                elif node.name == "br":
                    _append_run(para, "\n")
                else:
                    for child in node.children:
                        walk(child)

        for child in tag.children:
            walk(child)
        if not list(para):
            _append_run(para, tag.get_text())
        return para

    blocks = soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"])
    if blocks:
        for block in blocks:
            paragraphs.append(handle_block(block))
    else:
        paragraphs.append(_text_paragraph(soup.get_text(), shade))
    return paragraphs


class ParagraphService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def insert_plain(self, request: InsertParagraphRequest) -> bool:
        return self._insert(request, html=False)

    def insert_formatted(self, request: InsertParagraphRequest) -> bool:
        return self._insert(request, html=True)

    def _insert(self, request: InsertParagraphRequest, *, html: bool) -> bool:
        shade = self.settings.shade_fill if request.highlight else None
        with DocxPackage(request.document_path).edit_copy() as pkg:
            body = pkg.body
            heading_styles = bookmarks.get_heading_style_map(pkg)
            section = bookmarks.get_section_number_from_bookmark(
                body, request.insert_before_bookmark, heading_styles
            )
            anchor = bookmarks.find_bookmark_paragraph(body, request.insert_before_bookmark)
            if anchor is None:
                return False

            logical_id = uuid.uuid4().hex[:8]
            start_id = bookmarks.get_next_bookmark_id(body)
            end_id = start_id + 1
            start_bm_s, start_bm_e = bookmarks.create_zero_length_bookmark(
                f"Insert_Start_{logical_id}", start_id
            )
            end_bm_s, end_bm_e = bookmarks.create_zero_length_bookmark(
                f"Insert_End_{logical_id}", end_id
            )

            if html:
                paragraphs = _html_to_paragraphs(request.text, shade)
            else:
                paragraphs = [_text_paragraph(request.text, shade)]

            to_insert: list = [start_bm_s, start_bm_e]
            to_insert.extend(paragraphs)
            to_insert.extend([end_bm_s, end_bm_e])

            bookmarks.insert_elements_before(anchor, to_insert)
            metadata.add_insert_paragraph_metadata(
                pkg, logical_id, request.document_path, section
            )
            pkg.set_xml(DOCUMENT_XML, pkg.document)
        return True
