"""Section insert and delete operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from lxml import etree

from app.config import Settings
from app.core.exceptions import BookmarkNotFoundError
from app.core.namespaces import w_tag
from app.services.word import bookmarks, metadata, numbering
from app.services.word.document_package import DOCUMENT_XML, NUMBERING_XML, DocxPackage
from app.services.word.paragraph import _html_to_paragraphs, _shading_properties, _text_paragraph


@dataclass
class InsertSectionRequest:
    document_path: str
    insert_before_bookmark: str
    title: str
    content: str
    level: int = 1
    highlight: bool = False
    is_html: bool = False
    track_in_history: bool = False


@dataclass
class DeleteSectionRequest:
    document_path: str
    toc_bookmarks: dict[str, str]
    track_in_history: bool = False


class SectionService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def insert_section(self, request: InsertSectionRequest) -> bool:
        shade = self.settings.shade_fill if request.highlight else None
        level = min(9, max(1, request.level))

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

            heading = etree.Element(w_tag("p"))
            ppr = etree.SubElement(heading, w_tag("pPr"))
            style = etree.SubElement(ppr, w_tag("pStyle"))
            style.set(w_tag("val"), f"Heading{level}")
            if shade:
                heading.insert(0, _shading_properties(shade))
            run = etree.SubElement(heading, w_tag("r"))
            t = etree.SubElement(run, w_tag("t"))
            t.text = request.title

            if request.is_html:
                content_paras = _html_to_paragraphs(request.content, shade)
            else:
                content_paras = [_text_paragraph(request.content, shade)]

            to_insert: list = [start_bm_s, start_bm_e, heading]
            to_insert.extend(content_paras)
            to_insert.extend([end_bm_s, end_bm_e])

            bookmarks.insert_elements_before(anchor, to_insert)
            metadata.add_insert_section_metadata(
                pkg, logical_id, request.document_path, section, level
            )
            pkg.set_xml(DOCUMENT_XML, pkg.document)
        return True

    def delete_sections(self, request: DeleteSectionRequest) -> bool:
        with DocxPackage(request.document_path).edit_copy() as pkg:
            body = pkg.body
            for start_bm, stop_bm in request.toc_bookmarks.items():
                start_para = bookmarks.find_bookmark_paragraph(body, start_bm)
                stop_para = bookmarks.find_bookmark_paragraph(body, stop_bm)
                if start_para is None or stop_para is None:
                    raise BookmarkNotFoundError(
                        f"Section bookmarks not found: {start_bm} -> {stop_bm}"
                    )
                removing = False
                for child in list(body):
                    if child is start_para:
                        removing = True
                    if removing:
                        body.remove(child)
                    if child is stop_para:
                        break
            pkg.set_xml(DOCUMENT_XML, pkg.document)
        return True
