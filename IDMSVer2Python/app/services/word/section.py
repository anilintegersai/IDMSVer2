"""Section insert and delete operations."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from lxml import etree

from app.config import Settings
from app.core.exceptions import BookmarkNotFoundError
from app.core.namespaces import w_tag
from app.services.word import bookmarks, metadata, numbering, toc
from app.services.word.document_package import DOCUMENT_XML, NUMBERING_XML, DocxPackage
from app.services.word.paragraph import _html_to_paragraphs, _shading_properties, _text_paragraph

logger = logging.getLogger(__name__)


def update_toc_via_com(document_path: str) -> bool:
    """Update TOC field using Word COM automation (requires Word installed).
    
    Args:
        document_path: Path to the Word document
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import win32com.client
    except ImportError:
        logger.warning("pywin32 not installed - COM automation not available. Install with: pip install pywin32")
        return False
    
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        
        doc = word.Documents.Open(document_path)
        
        # Update all TOCs in the document
        toc_count = doc.TablesOfContents.Count
        logger.info(f"Found {toc_count} TOC(s) in document")
        
        for toc_index in range(1, toc_count + 1):
            doc.TablesOfContents(toc_index).Update()
            logger.info(f"Updated TOC {toc_index}")
        
        doc.Close(SaveChanges=True)
        word.Quit()
        
        logger.info(f"Successfully updated TOC via COM for {document_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to update TOC via COM: {e}")
        try:
            word.Quit()
        except:
            pass
        return False


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
    update_toc: bool = False
    # When set, the edit is written here (a copy) instead of over document_path,
    # leaving the original untouched. When None, the original is edited in place.
    output_path: str | None = None


@dataclass
class DeleteSectionRequest:
    document_path: str
    toc_bookmarks: dict[str, str]
    track_in_history: bool = False
    update_toc: bool = False


class SectionService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def insert_section(self, request: InsertSectionRequest) -> bool:
        shade = self.settings.shade_fill if request.highlight else None
        level = min(9, max(1, request.level))

        with DocxPackage(request.document_path).edit_copy(
            destination=request.output_path
        ) as pkg:
            body = pkg.body
            heading_styles = bookmarks.get_heading_style_map(pkg)
            if request.insert_before_bookmark:
                section = bookmarks.get_section_number_from_bookmark(
                    body, request.insert_before_bookmark, heading_styles
                )
                anchor = bookmarks.find_bookmark_paragraph(body, request.insert_before_bookmark)
                if anchor is None:
                    return False
            else:
                section = ""
                anchor = None

            logical_id = uuid.uuid4().hex[:8]
            start_id = bookmarks.get_next_bookmark_id(body)
            heading_end_id = start_id + 1
            content_start_id = heading_end_id + 1
            content_end_id = content_start_id + 1
            
            # Markers for heading (not editable)
            heading_start_bm_s, heading_start_bm_e = bookmarks.create_zero_length_bookmark(
                f"Heading_Start_{logical_id}", start_id
            )
            heading_end_bm_s, heading_end_bm_e = bookmarks.create_zero_length_bookmark(
                f"Heading_End_{logical_id}", heading_end_id
            )
            
            # Markers for content (editable)
            content_start_bm_s, content_start_bm_e = bookmarks.create_zero_length_bookmark(
                f"Content_Start_{logical_id}", content_start_id
            )
            content_end_bm_s, content_end_bm_e = bookmarks.create_zero_length_bookmark(
                f"Content_End_{logical_id}", content_end_id
            )

            heading = etree.Element(w_tag("p"))
            ppr = etree.SubElement(heading, w_tag("pPr"))
            style = etree.SubElement(ppr, w_tag("pStyle"))
            style.set(w_tag("val"), f"Heading{level}")
            if shade:
                shd = etree.SubElement(ppr, w_tag("shd"))
                shd.set(w_tag("val"), "clear")
                shd.set(w_tag("color"), "auto")
                shd.set(w_tag("fill"), shade)
            run = etree.SubElement(heading, w_tag("r"))
            t = etree.SubElement(run, w_tag("t"))
            t.text = request.title

            if request.is_html:
                content_paras = _html_to_paragraphs(request.content, shade)
            else:
                content_paras = [_text_paragraph(request.content, shade)]

            to_insert: list = [heading_start_bm_s, heading_start_bm_e, heading, heading_end_bm_s, heading_end_bm_e]
            to_insert.extend([content_start_bm_s, content_start_bm_e])
            to_insert.extend(content_paras)
            to_insert.extend([content_end_bm_s, content_end_bm_e])

            if anchor is not None:
                bookmarks.insert_elements_before(anchor, to_insert)
            else:
                bookmarks.append_elements_before_sectpr(body, to_insert)
            
            # Recalculate section numbers and update text in the document body
            bookmarks.renumber_headings_after_insert(body, heading_styles, heading)
            
            metadata.add_insert_section_metadata(
                pkg, logical_id, request.document_path, section, level
            )
            
            # Bake the updated TOC directly into the document: splice in an
            # entry for the new heading and renumber, while preserving every
            # existing entry's page-number field and formatting. Because the
            # field's cached result is now correct, neither MS Word nor the
            # in-app viewer needs to update fields on open — so the user is NOT
            # prompted ("update fields?" / "update table of contents?"). Page
            # numbers keep their pre-insert values (approximate for entries
            # after the insert); a manual F9 in Word, or the optional
            # LibreOffice finalize pass, recomputes them exactly.
            toc.insert_toc_entry(
                pkg, heading, request.insert_before_bookmark, heading_styles
            )
            toc.clear_update_fields_on_open(pkg)

            pkg.set_xml(DOCUMENT_XML, pkg.document)
        
        # Update TOC via COM automation if requested
        if request.update_toc:
            output_path = request.output_path or request.document_path
            update_toc_via_com(output_path)
        
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
                    if child is stop_para:
                        # Stop before removing the stop paragraph
                        break
                    if child is start_para:
                        removing = True
                    if removing:
                        body.remove(child)
            pkg.set_xml(DOCUMENT_XML, pkg.document)
        
        # Update TOC via COM automation if requested
        if request.update_toc:
            update_toc_via_com(request.document_path)
        
        return True
