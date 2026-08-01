"""Merge sections from a source document into a destination document.

The merge preserves destination document formatting:
- Destination bullet/numbered-list styles are used for copied list paragraphs
- Heading styles are remapped to appropriate destination heading levels
- Source numbering definitions are NOT copied wholesale into the destination
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass

from app.config import Settings
from app.core.exceptions import BookmarkNotFoundError, DocumentProcessingError
from app.core.namespaces import w_tag
from app.services.word import bookmarks, metadata, numbering, style_reconcile, toc
from app.services.word.document_package import DOCUMENT_XML, NUMBERING_XML, DocxPackage

logger = logging.getLogger(__name__)


def _renumber_inserted_headings_by_parent(
    body: etree._Element,
    heading_styles: dict[str, int] | None,
    anchor_para: etree._Element,
) -> None:
    """Renumber inserted headings based on the parent section number.
    
    When content is inserted between sections, the parent section's number
    becomes the prefix for all inserted content. For example:
    - Parent: 3 (level 1)
    - Inserted: 4.5, 4.5.1, 4.5.2 (from source, levels 1, 2, 2)
    - Result: 3.1, 3.1.1, 3.1.2 (parent number + relative structure)
    
    The levels of inserted content are preserved, only the numbers change.
    """
    if not bookmarks.document_has_numbered_headings(body, heading_styles):
        return
    
    parent = anchor_para.getparent()
    if parent is None:
        return
    
    insertion_index = parent.index(anchor_para)
    
    # Find the parent section number (the section immediately before the insertion point)
    parent_section_number = None
    parent_level = 1
    
    # Walk backwards from the insertion point to find the parent heading
    for para in reversed(list(parent[:insertion_index])):
        level = bookmarks._heading_level(para, heading_styles)
        if level is not None:
            text = bookmarks.paragraph_text(para).strip()
            # Extract the section number from the heading text
            import re
            match = re.match(r"^(\d+(?:\.\d+)*)", text)
            if match:
                parent_section_number = match.group(1)
                parent_level = level
                break
    
    if parent_section_number is None:
        # No parent section found, can't renumber
        return
    
    # Find the next sibling heading at the same level as the parent
    # This marks the end of the inserted content
    next_sibling_index = None
    for i in range(insertion_index + 1, len(parent)):
        para = parent[i]
        level = bookmarks._heading_level(para, heading_styles)
        if level is not None and level == parent_level:
            next_sibling_index = i
            break
    
    # Renumber headings between insertion point and next sibling
    # Use parent_section_number as the base prefix
    parent_counters = [int(n) for n in parent_section_number.split(".")]
    
    # Track the minimum level in the inserted content
    min_inserted_level = None
    for i in range(insertion_index, next_sibling_index if next_sibling_index is not None else len(parent)):
        para = parent[i]
        level = bookmarks._heading_level(para, heading_styles)
        if level is not None:
            if min_inserted_level is None or level < min_inserted_level:
                min_inserted_level = level
    
    if min_inserted_level is None:
        return
    
    # Calculate the level offset from parent to first inserted heading
    level_offset = min_inserted_level - parent_level
    
    # Renumber each heading
    counters = parent_counters.copy()
    for i in range(insertion_index, next_sibling_index if next_sibling_index is not None else len(parent)):
        para = parent[i]
        level = bookmarks._heading_level(para, heading_styles)
        if level is None:
            continue
        
        # Calculate the relative level (1-based from parent level)
        relative_level = level - parent_level + 1
        
        # Extend counters if needed
        while len(counters) < relative_level:
            counters.append(1)
        
        # Increment the counter at this relative level
        if relative_level <= len(counters):
            counters[relative_level - 1] += 1
            # Reset deeper levels
            del counters[relative_level:]
        
        current_number = ".".join(str(n) for n in counters)
        bookmarks._update_heading_number(para, current_number)


@dataclass
class MergeSectionRequest:
    master_template_path: str
    output_path: str
    source_document_path: str
    source_start_bookmark: str
    source_stop_bookmark: str
    insert_before_bookmark: str
    update_toc: bool = False


@dataclass
class MergeOutlineRequest:
    """Merge a heading and all of its descendant content by outline.

    Unlike :class:`MergeSectionRequest`, ``source_stop_bookmark`` is *exclusive*
    (the next same-or-higher heading), and both it and ``insert_before_bookmark``
    may be ``None`` (copy to end of source / append at end of destination).
    """

    master_template_path: str
    output_path: str
    source_document_path: str
    source_start_bookmark: str
    source_stop_bookmark: str | None = None
    insert_before_bookmark: str | None = None


@dataclass
class MergeResult:
    success: bool
    message: str
    output_path: str
    logical_id: str | None = None
    embedded_objects_count: int = 0


class MergeService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def merge_section(self, request: MergeSectionRequest) -> MergeResult:
        if not os.path.isfile(request.master_template_path):
            raise DocumentProcessingError(
                f"Master template not found: {request.master_template_path}"
            )
        if not os.path.isfile(request.source_document_path):
            raise DocumentProcessingError(
                f"Source document not found: {request.source_document_path}"
            )

        os.makedirs(os.path.dirname(os.path.abspath(request.output_path)) or ".", exist_ok=True)

        if os.path.exists(request.output_path):
            return MergeResult(
                success=False,
                message=f"Output already exists: {os.path.basename(request.output_path)}",
                output_path=request.output_path,
            )

        pkg = DocxPackage(request.master_template_path, writable=False)
        dest = pkg.clone_to(request.output_path)

        source_pkg = DocxPackage(request.source_document_path, writable=False)
        source_body = source_pkg.body
        dest_body = dest.body

        source_heading_styles = bookmarks.get_heading_style_map(source_pkg)
        dest_heading_styles = bookmarks.get_heading_style_map(dest)

        source_section = bookmarks.get_section_number_from_bookmark(
            source_body, request.source_start_bookmark, source_heading_styles
        )
        dest_level = bookmarks.get_heading_level_at_bookmark(
            dest_body, request.insert_before_bookmark, dest_heading_styles
        )

        copied = bookmarks.get_body_elements_between_bookmarks(
            source_body, request.source_start_bookmark, request.source_stop_bookmark
        )

        source_numbering = (
            source_pkg.get_xml(NUMBERING_XML)
            if NUMBERING_XML in source_pkg.list_parts()
            else None
        )
        dest_numbering = numbering.ensure_numbering_part(dest)

        numbering.remap_numbering_in_elements(copied, source_numbering, dest_numbering)
        style_reconcile.reconcile_content_styles(
            copied, source_pkg, dest, skip_ids=set(source_heading_styles)
        )
        numbering.remap_heading_styles(
            copied, dest_level, source_heading_styles, dest_heading_styles
        )
        numbering.strip_foreign_numbering_from_non_lists(copied)
        dest.set_xml(NUMBERING_XML, dest_numbering)

        anchor_para = bookmarks.find_bookmark_paragraph(
            dest_body, request.insert_before_bookmark
        )
        if anchor_para is None:
            raise BookmarkNotFoundError(
                f"Insert bookmark not found in destination: {request.insert_before_bookmark}"
            )

        logical_id = uuid.uuid4().hex[:8]
        start_id = bookmarks.get_next_bookmark_id(dest_body)
        end_id = start_id + 1
        start_bm_s, start_bm_e = bookmarks.create_zero_length_bookmark(
            f"Merge_Start_{logical_id}", start_id
        )
        end_bm_s, end_bm_e = bookmarks.create_zero_length_bookmark(
            f"Merge_End_{logical_id}", end_id
        )

        to_insert: list = []
        if self.settings.insert_marker_text:
            to_insert.extend([start_bm_s, start_bm_e])
        to_insert.extend(copied)
        if self.settings.insert_marker_text:
            to_insert.extend([end_bm_s, end_bm_e])

        bookmarks.insert_elements_before(anchor_para, to_insert)

        metadata.add_merge_metadata(
            dest,
            logical_id,
            request.source_document_path,
            source_section,
            dest_level,
            request.master_template_path,
        )

        toc.update_toc(dest)  # mark TOC dirty + update-fields-on-open so the new section shows in the TOC
        dest.set_xml(DOCUMENT_XML, dest.document)
        dest.save()

        # Update TOC via COM automation if requested
        if request.update_toc:
            from app.services.word.section import update_toc_via_com
            update_toc_via_com(request.output_path)

        embedded_count = sum(1 for el in copied if el.tag.endswith("}tbl"))

        return MergeResult(
            success=True,
            message="Document section merged successfully.",
            output_path=request.output_path,
            logical_id=logical_id,
            embedded_objects_count=embedded_count,
        )

    def merge_section_outline(self, request: MergeOutlineRequest) -> MergeResult:
        """Merge a heading + its descendants (outline-based, exclusive stop)."""
        if not os.path.isfile(request.master_template_path):
            raise DocumentProcessingError(
                f"Master template not found: {request.master_template_path}"
            )
        if not os.path.isfile(request.source_document_path):
            raise DocumentProcessingError(
                f"Source document not found: {request.source_document_path}"
            )

        os.makedirs(os.path.dirname(os.path.abspath(request.output_path)) or ".", exist_ok=True)
        if os.path.exists(request.output_path):
            return MergeResult(
                success=False,
                message=f"Output already exists: {os.path.basename(request.output_path)}",
                output_path=request.output_path,
            )

        pkg = DocxPackage(request.master_template_path, writable=False)
        dest = pkg.clone_to(request.output_path)
        source_pkg = DocxPackage(request.source_document_path, writable=False)
        source_body = source_pkg.body
        dest_body = dest.body

        source_heading_styles = bookmarks.get_heading_style_map(source_pkg)
        dest_heading_styles = bookmarks.get_heading_style_map(dest)
        source_section = bookmarks.get_section_number_from_bookmark(
            source_body, request.source_start_bookmark, source_heading_styles
        )

        anchor_para = None
        if request.insert_before_bookmark:
            dest_level = bookmarks.get_heading_level_at_bookmark(
                dest_body, request.insert_before_bookmark, dest_heading_styles
            )
            anchor_para = bookmarks.find_bookmark_paragraph(
                dest_body, request.insert_before_bookmark
            )
            if anchor_para is None:
                raise BookmarkNotFoundError(
                    f"Insert bookmark not found in destination: {request.insert_before_bookmark}"
                )
        else:
            dest_level = 1  # appended at the end of the document → top level

        copied = bookmarks.get_section_elements(
            source_body, request.source_start_bookmark, request.source_stop_bookmark
        )
        if not copied:
            return MergeResult(
                success=False,
                message="No content found for the selected section.",
                output_path=request.output_path,
            )

        source_numbering = (
            source_pkg.get_xml(NUMBERING_XML)
            if NUMBERING_XML in source_pkg.list_parts()
            else None
        )
        dest_numbering = numbering.ensure_numbering_part(dest)
        numbering.remap_numbering_in_elements(copied, source_numbering, dest_numbering)
        style_reconcile.reconcile_content_styles(
            copied, source_pkg, dest, skip_ids=set(source_heading_styles)
        )
        # Remap heading styles to make inserted content children of the parent section
        # Use dest_level + 1 so the first heading becomes a child of the parent
        numbering.remap_heading_styles(copied, dest_level + 1, source_heading_styles, dest_heading_styles)
        numbering.strip_foreign_numbering_from_non_lists(copied)
        dest.set_xml(NUMBERING_XML, dest_numbering)

        logical_id = uuid.uuid4().hex[:8]
        start_id = bookmarks.get_next_bookmark_id(dest_body)
        end_id = start_id + 1
        start_bm_s, start_bm_e = bookmarks.create_zero_length_bookmark(
            f"Merge_Start_{logical_id}", start_id
        )
        end_bm_s, end_bm_e = bookmarks.create_zero_length_bookmark(
            f"Merge_End_{logical_id}", end_id
        )

        to_insert: list = []
        if self.settings.insert_marker_text:
            to_insert.extend([start_bm_s, start_bm_e])
        to_insert.extend(copied)
        if self.settings.insert_marker_text:
            to_insert.extend([end_bm_s, end_bm_e])

        if anchor_para is not None:
            bookmarks.insert_elements_before(anchor_para, to_insert)
        else:
            bookmarks.append_elements_before_sectpr(dest_body, to_insert)

        # Renumber the inserted headings based on the parent section
        if anchor_para is not None:
            _renumber_inserted_headings_by_parent(dest_body, dest_heading_styles, anchor_para)

        metadata.add_merge_metadata(
            dest,
            logical_id,
            request.source_document_path,
            source_section,
            dest_level,
            request.master_template_path,
        )

        toc.update_toc(dest)  # mark TOC dirty + update-fields-on-open so the new section shows in the TOC
        dest.set_xml(DOCUMENT_XML, dest.document)
        dest.save()

        embedded_count = sum(1 for el in copied if el.tag.endswith("}tbl"))
        return MergeResult(
            success=True,
            message="Section merged successfully.",
            output_path=request.output_path,
            logical_id=logical_id,
            embedded_objects_count=embedded_count,
        )
