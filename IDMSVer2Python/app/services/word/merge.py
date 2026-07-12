"""Merge sections from a source document into a destination document.

The merge preserves destination document formatting:
- Destination bullet/numbered-list styles are used for copied list paragraphs
- Heading styles are remapped to appropriate destination heading levels
- Source numbering definitions are NOT copied wholesale into the destination
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from app.config import Settings
from app.core.exceptions import BookmarkNotFoundError, DocumentProcessingError
from app.services.word import bookmarks, metadata, numbering, style_reconcile
from app.services.word.document_package import DOCUMENT_XML, NUMBERING_XML, DocxPackage


@dataclass
class MergeSectionRequest:
    master_template_path: str
    output_path: str
    source_document_path: str
    source_start_bookmark: str
    source_stop_bookmark: str
    insert_before_bookmark: str


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

        dest.set_xml(DOCUMENT_XML, dest.document)
        dest.save()

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
        numbering.remap_heading_styles(copied, dest_level, source_heading_styles, dest_heading_styles)
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

        metadata.add_merge_metadata(
            dest,
            logical_id,
            request.source_document_path,
            source_section,
            dest_level,
            request.master_template_path,
        )

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
