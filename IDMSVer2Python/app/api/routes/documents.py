"""Unified document processing API routes.

Each endpoint is registered with `summary`, `description`, and `response_description`
so Swagger UI shows self-explanatory documentation. Request/response model fields
also carry `Field(description=…)` text visible when expanding schemas in Swagger.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.dependencies import validate_document_path
from app.core.exceptions import DocumentProcessingError
from app.db.database import get_db
from app.dependencies import (
    extract_project_name,
    get_audit_service,
    get_content_service,
    get_coversheet_service,
    get_edit_content_service,
    get_fields_service,
    get_image_service,
    get_inserted_text_service,
    get_merge_service,
    get_optional_user_id,
    get_paragraph_service,
    get_payload_service,
    get_replace_service,
    get_section_service,
)
from app.models.schemas import (
    ApiResponse,
    ApplyCoversheetRequest,
    ContentMarker,
    DeleteSectionRequest,
    DocumentListItem,
    DocumentPathRequest,
    EditableContent,
    GetContentMarkersRequest,
    GetContentMarkersResult,
    GetContentTextRequest,
    GetContentTextResult,
    GetEditableSectionsRequest,
    GetEditableSectionsResult,
    InsertContentRequest,
    InsertContentResult,
    InsertParagraphRequest,
    InsertSectionRequest,
    InsertSectionResult,
    InsertedMarkerInfo,
    InsertedMarkersRequest,
    InsertedTextRequest,
    MergeDocumentRequest,
    MergeDocumentResult,
    ReplaceContentTextRequest,
    ReplaceContentTextResult,
    MergeSectionApiRequest,
    TocItem,
    UpdateInsertedTextBody,
)
from app.services.word import bookmarks, placeholders, toc
from app.services.word.document_package import DocxPackage
from app.services.word.image import InsertImageRequest
from app.services.word.merge import MergeOutlineRequest, MergeSectionRequest
from app.services.word.paragraph import InsertParagraphRequest as ParagraphSvcRequest
from app.services.word.section import DeleteSectionRequest as DeleteSvcRequest
from app.services.word.section import InsertSectionRequest as SectionSvcRequest
from app.services.word.inserted_text import UpdateInsertedTextRequest as UpdateSvcRequest
from app.services.word.replace_document import TableIdentifierRule as ReplaceRule

router = APIRouter(prefix="/documents", tags=["Documents"])


def _ok(data, message: str, code: str, *, success: bool = True) -> ApiResponse:
    return ApiResponse(success=success, message=message, message_code=code, data=data)


def _log_payload(
    settings: Settings,
    payload_svc,
    db: Session,
    endpoint: str,
    project: str,
    body: object,
    user_id: int,
) -> None:
    if settings.payload_logging_enabled:
        payload_svc.create(db, project, endpoint, body, created_by=f"user-{user_id}")


def _toc_node_to_item(node: dict) -> TocItem:
    """Convert an outline dict (from bookmarks.get_toc_tree) into a TocItem."""
    return TocItem(
        sl_no=str(node.get("order", "")),
        section_number=node.get("section_number", ""),
        item_text=node.get("text", ""),
        page_no=node.get("page_no", ""),
        page_ref=node.get("page_no", ""),
        bookmark=node.get("bookmark", ""),
        level=node.get("level", 1),
        children=[_toc_node_to_item(child) for child in node.get("children", [])],
    )


@router.post(
    "/toc",
    response_model=ApiResponse[list[TocItem]],
    summary="Get document table of contents (hierarchical)",
    description=(
        "Reads the Word document and returns its table of contents as a **tree**. "
        "Each node carries `section_number`, `item_text`, and `page_no` for display, "
        "plus `bookmark` (anchor) and `level` used to drive drag-and-drop merge. "
        "Child sub-sections are nested under `children`."
    ),
    response_description="Hierarchical TOC in `data`, or empty list with `toc_empty` code.",
)
def get_table_of_contents(body: DocumentPathRequest) -> ApiResponse[list[TocItem]]:
    """Return the document's table of contents as a hierarchical tree."""
    # Validate the document path is inside allowed roots before opening
    norm_path = validate_document_path(body.document_path, get_settings())
    pkg = DocxPackage(norm_path, writable=False)
    items = [_toc_node_to_item(node) for node in bookmarks.get_toc_tree(pkg)]
    if items:
        return _ok(items, "TOC found.", "toc_success")
    return _ok([], "No TOC entries found.", "toc_empty", success=False)


@router.get(
    "/list",
    response_model=ApiResponse[list[DocumentListItem]],
    summary="List available source documents",
    description=(
        "Returns every `.docx` file in the configured source-templates folder "
        "(`TEMPLATE_SOURCE_BASE_PATH`). Used to populate the Master/Associated dropdowns."
    ),
)
def list_documents(settings: Settings = Depends(get_settings)) -> ApiResponse[list[DocumentListItem]]:
    folder = settings.template_source_base_path
    items: list[DocumentListItem] = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(".docx") and not name.startswith("~$"):
                items.append(DocumentListItem(name=name, path=os.path.join(folder, name)))
    if items:
        return _ok(items, "Documents listed.", "list_success")
    return _ok([], f"No .docx files found in {folder}.", "list_empty", success=False)


@router.post(
    "/merge-section",
    response_model=ApiResponse[MergeDocumentResult],
    summary="Merge a heading (and its descendants) into a copy of the master",
    description=(
        "Copies the section that starts at `source_start_bookmark` — including all of its "
        "sub-sections up to `source_stop_bookmark` (exclusive) — from the source document "
        "into a **copy** of the master, inserted before `insert_before_bookmark`. "
        "The original master and source are never modified. The merged file is written to the "
        "configured merged-output folder and its path is returned."
    ),
)
def merge_section(
    body: MergeSectionApiRequest,
    merge_svc=Depends(get_merge_service),
    settings: Settings = Depends(get_settings),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[MergeDocumentResult]:
    merged_dir = settings.merged_base_path
    os.makedirs(merged_dir, exist_ok=True)

    # Validate the master and source paths before proceeding
    master_path = validate_document_path(body.master_template_path, settings)
    source_path = validate_document_path(body.source_document_path, settings)

    if body.output_filename and body.output_filename.strip():
        # basename() strips any path components — the name must stay inside merged_dir.
        filename = os.path.basename(body.output_filename.strip())
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        master_stem = Path(master_path).stem
        source_stem = Path(source_path).stem
        filename = f"{master_stem}__with__{source_stem}__{stamp}.docx"
    if not filename.lower().endswith(".docx"):
        filename += ".docx"
    output_path = os.path.join(merged_dir, filename)

    result = merge_svc.merge_section_outline(
        MergeOutlineRequest(
            master_template_path=master_path,
            output_path=output_path,
            source_document_path=source_path,
            source_start_bookmark=body.source_start_bookmark,
            source_stop_bookmark=body.source_stop_bookmark,
            insert_before_bookmark=body.insert_before_bookmark,
        )
    )
    if result.success:
        audit_svc.create(db, user_id, f"Section merged into {result.output_path}")
        return _ok(
            MergeDocumentResult(
                output_path=result.output_path,
                logical_id=result.logical_id,
                embedded_objects_count=result.embedded_objects_count,
            ),
            result.message,
            "merge_success",
        )
    return _ok(
        MergeDocumentResult(output_path=result.output_path),
        result.message,
        "merge_failed",
        success=False,
    )


@router.get(
    "/download",
    summary="Download / stream a document",
    description=(
        "Streams a `.docx` file for in-browser preview. Restricted to the configured "
        "source-templates and merged-output folders."
    ),
)
def download_document(
    path: str = Query(..., description="Full path to the .docx file to stream."),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    norm = os.path.normpath(path)
    allowed_roots = [
        os.path.normpath(settings.template_source_base_path),
        os.path.normpath(settings.merged_base_path),
    ]
    if not any(norm.lower().startswith(root.lower()) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders.")
    if not os.path.isfile(norm):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        norm,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=os.path.basename(norm),
    )


@router.post(
    "/placeholders",
    response_model=ApiResponse[list[str]],
    summary="Find placeholders in a document",
    description=(
        "Scans the document XML for placeholder tokens matching the pattern `<NAME>`, "
        "including header, footer, and body parts."
    ),
)
def get_placeholders(body: DocumentPathRequest) -> ApiResponse[list[str]]:
    norm_path = validate_document_path(body.document_path, get_settings())
    found = placeholders.find_placeholders(norm_path)
    if found:
        return _ok(found, "Placeholders fetched successfully.", "placeholders_success")
    return _ok([], "No placeholders found.", "placeholders_empty", success=False)


@router.post(
    "/merge",
    response_model=ApiResponse[MergeDocumentResult],
    summary="Merge a section into a master template",
    description=(
        "Copies content between bookmarks in a source document and inserts it into a cloned "
        "master template before the specified destination bookmark. "
        "**Destination formatting is preserved**: bullets and numbered lists use the master "
        "template's numbering definitions; heading styles are remapped to the correct level; "
        "source numbering definitions are not copied wholesale."
    ),
)
def merge_document(
    body: MergeDocumentRequest,
    merge_svc=Depends(get_merge_service),
    settings: Settings = Depends(get_settings),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[MergeDocumentResult]:
    # Validate paths
    master_path = validate_document_path(body.master_template_path, settings)
    source_path = validate_document_path(body.source.source_document_path, settings)

    result = merge_svc.merge_section(
        MergeSectionRequest(
            master_template_path=master_path,
            output_path=body.output_path,
            source_document_path=source_path,
            source_start_bookmark=body.source.start_bookmark,
            source_stop_bookmark=body.source.stop_bookmark,
            insert_before_bookmark=body.insert_before_bookmark,
        )
    )
    if result.success:
        audit_svc.create(
            db,
            user_id,
            f"Document merge created: {body.output_path}",
        )
        return _ok(
            MergeDocumentResult(
                output_path=result.output_path,
                logical_id=result.logical_id,
                embedded_objects_count=result.embedded_objects_count,
            ),
            result.message,
            "merge_success",
        )
    return _ok(
        MergeDocumentResult(output_path=result.output_path),
        result.message,
        "merge_failed",
        success=False,
    )


@router.post(
    "/paragraphs",
    response_model=ApiResponse[bool],
    summary="Insert a plain-text paragraph",
    description=(
        "Inserts one or more paragraphs (split on newlines) immediately before the "
        "section identified by the TOC bookmark. Optional highlight shading can be applied."
    ),
)
def insert_paragraph(
    body: InsertParagraphRequest,
    svc=Depends(get_paragraph_service),
    settings: Settings = Depends(get_settings),
    payload_svc=Depends(get_payload_service),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[bool]:
    # Validate path before processing and payload logging
    norm_path = validate_document_path(body.document_path, settings)
    _log_payload(settings, payload_svc, db, "/documents/paragraphs", extract_project_name(norm_path), body.model_dump(), user_id)
    ok = svc.insert_plain(
        ParagraphSvcRequest(
            document_path=norm_path,
            insert_before_bookmark=body.insert_before_bookmark,
            text=body.text,
            highlight=body.highlight,
            track_in_history=body.track_in_history,
        )
    )
    if ok:
        audit_svc.create(db, user_id, f"Plain text inserted in {body.document_path}")
        return _ok(True, "Paragraph inserted.", "paragraph_insert_success")
    return _ok(False, "Paragraph insert failed.", "paragraph_insert_failed", success=False)


@router.post(
    "/paragraphs/formatted",
    response_model=ApiResponse[bool],
    summary="Insert an HTML-formatted paragraph",
    description=(
        "Parses simple HTML (paragraphs, bold, italic, line breaks) and inserts the "
        "formatted content before the target TOC bookmark."
    ),
)
def insert_formatted_paragraph(
    body: InsertParagraphRequest,
    svc=Depends(get_paragraph_service),
    settings: Settings = Depends(get_settings),
    payload_svc=Depends(get_payload_service),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[bool]:
    norm_path = validate_document_path(body.document_path, settings)
    _log_payload(settings, payload_svc, db, "/documents/paragraphs/formatted", extract_project_name(norm_path), body.model_dump(), user_id)
    ok = svc.insert_formatted(
        ParagraphSvcRequest(
            document_path=norm_path,
            insert_before_bookmark=body.insert_before_bookmark,
            text=body.text,
            highlight=body.highlight,
            track_in_history=body.track_in_history,
        )
    )
    if ok:
        audit_svc.create(db, user_id, f"Formatted text inserted in {body.document_path}")
        return _ok(True, "Formatted paragraph inserted.", "paragraph_formatted_success")
    return _ok(False, "Formatted paragraph insert failed.", "paragraph_formatted_failed", success=False)


@router.post(
    "/sections",
    response_model=ApiResponse[InsertSectionResult],
    summary="Insert a new document section",
    description=(
        "Adds a heading and body content before the specified TOC bookmark. "
        "Heading level (1-9) controls the outline level in the destination document. "
        "Set `save_as_copy` to write the change to a new copy (named `copy_name`) in the "
        "source folder, leaving the original untouched."
    ),
)
def insert_section(
    body: InsertSectionRequest,
    svc=Depends(get_section_service),
    settings: Settings = Depends(get_settings),
    payload_svc=Depends(get_payload_service),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[InsertSectionResult]:
    # Validate path and log payload
    norm_path = validate_document_path(body.document_path, settings)
    _log_payload(settings, payload_svc, db, "/documents/sections", extract_project_name(norm_path), body.model_dump(), user_id)

    # Resolve where the edit is written. A copy protects the original: it is
    # saved beside the source and its name must not collide with an existing
    # file (so we can never overwrite an original or a previous copy).
    if body.save_as_copy:
        name = os.path.basename((body.copy_name or "").strip())
        if not name:
            return _ok(None, "Please provide a name for the copy.", "section_copy_name_required", success=False)
        if not name.lower().endswith(".docx"):
            name += ".docx"
        output_path = os.path.join(os.path.dirname(os.path.abspath(norm_path)), name)
        if os.path.normpath(output_path) == os.path.normpath(norm_path):
            return _ok(None, "The copy name matches the original. Choose a different name.", "section_copy_name_conflict", success=False)
        if os.path.exists(output_path):
            return _ok(None, f"A file named '{name}' already exists. Choose a different name.", "section_copy_exists", success=False)
        created_copy = True
    else:
        output_path = norm_path
        created_copy = False

    ok = svc.insert_section(
        SectionSvcRequest(
            document_path=norm_path,
            insert_before_bookmark=body.insert_before_bookmark,
            title=body.title,
            content=body.content,
            level=body.level,
            highlight=body.highlight,
            is_html=body.is_html,
            track_in_history=body.track_in_history,
            output_path=output_path if created_copy else None,
        )
    )
    if ok:
        where = f"copy {output_path}" if created_copy else norm_path
        audit_svc.create(db, user_id, f"Section inserted in {where}")
        message = (
            "Section inserted into a new copy - the original is unchanged."
            if created_copy else "Section inserted."
        )
        return _ok(
            InsertSectionResult(output_path=output_path, created_copy=created_copy),
            message,
            "section_insert_success",
        )
    return _ok(None, "Section insert failed.", "section_insert_failed", success=False)


@router.post(
    "/content",
    response_model=ApiResponse[InsertContentResult],
    summary="Insert content at the end of a section",
    description=(
        "Inserts HTML content and/or an image at the end of a section's content, "
        "before the next heading. The content is appended after all existing content "
        "of the specified section. Set `save_as_copy` to write the change to a new copy "
        "(named `copy_name`) in the source folder, leaving the original untouched."
    ),
)
def insert_content(
    body: InsertContentRequest,
    svc=Depends(get_content_service),
    settings: Settings = Depends(get_settings),
    payload_svc=Depends(get_payload_service),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[InsertContentResult]:
    # Validate path and log payload
    norm_path = validate_document_path(body.document_path, settings)
    _log_payload(settings, payload_svc, db, "/documents/content", extract_project_name(norm_path), body.model_dump(), user_id)

    # Resolve where the edit is written
    if body.save_as_copy:
        name = os.path.basename((body.copy_name or "").strip())
        if not name:
            return _ok(None, "Please provide a name for the copy.", "content_copy_name_required", success=False)
        if not name.lower().endswith(".docx"):
            name += ".docx"
        output_path = os.path.join(os.path.dirname(os.path.abspath(norm_path)), name)
        if os.path.normpath(output_path) == os.path.normpath(norm_path):
            return _ok(None, "The copy name matches the original. Choose a different name.", "content_copy_name_conflict", success=False)
        if os.path.exists(output_path):
            return _ok(None, f"A file named '{name}' already exists. Choose a different name.", "content_copy_exists", success=False)
        created_copy = True
    else:
        output_path = norm_path
        created_copy = False

    try:
        from app.services.word.content import InsertContentRequest as ContentSvcRequest
        actual_output_path, actual_created_copy = svc.insert_content(
            ContentSvcRequest(
                document_path=norm_path,
                section_bookmark=body.section_bookmark,
                html_content=body.html_content,
                image_data=body.image_data,
                image_caption=body.image_caption,
                image_width=body.image_width,
                image_height=body.image_height,
                highlight=body.highlight,
                save_as_copy=body.save_as_copy,
                copy_name=body.copy_name,
                track_in_history=body.track_in_history,
            )
        )
        where = f"copy {actual_output_path}" if actual_created_copy else norm_path
        audit_svc.create(db, user_id, f"Content inserted in {where}")
        message = (
            "Content inserted into a new copy - the original is unchanged."
            if actual_created_copy else "Content inserted."
        )
        return _ok(
            InsertContentResult(output_path=actual_output_path, created_copy=actual_created_copy),
            message,
            "content_insert_success",
        )
    except Exception as e:
        return _ok(None, f"Content insert failed: {str(e)}", "content_insert_failed", success=False)


@router.post(
    "/editable-sections",
    response_model=ApiResponse[GetEditableSectionsResult],
    summary="Get all sections with editable content",
    description=(
        "Returns a list of all sections that contain user-inserted content (from Insert Content "
        "or Insert Section operations). Each entry includes the section bookmark, number, title, "
        "and a preview of the editable content."
    ),
)
def get_editable_sections(
    body: GetEditableSectionsRequest,
    svc=Depends(get_edit_content_service),
    settings: Settings = Depends(get_settings),
    payload_svc=Depends(get_payload_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[GetEditableSectionsResult]:
    norm_path = validate_document_path(body.document_path, settings)
    _log_payload(settings, payload_svc, db, "/documents/editable-sections", extract_project_name(norm_path), body.model_dump(), user_id)

    try:
        from app.services.word.edit_content import GetEditableSectionsRequest as EditSvcRequest
        result = svc.get_editable_sections(
            EditSvcRequest(document_path=norm_path)
        )
        return _ok(result, "Found editable sections.", "editable_sections_retrieved")
    except Exception as e:
        return _ok(None, f"Failed to retrieve editable sections: {str(e)}", "editable_sections_failed", success=False)


@router.post(
    "/content-markers",
    response_model=ApiResponse[GetContentMarkersResult],
    summary="Get content markers for a section",
    description=(
        "Returns all content markers within a specific section. Each marker represents a block "
        "of user-inserted content that can be edited. Includes a preview of each content block."
    ),
)
def get_content_markers(
    body: GetContentMarkersRequest,
    svc=Depends(get_edit_content_service),
    settings: Settings = Depends(get_settings),
    payload_svc=Depends(get_payload_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[GetContentMarkersResult]:
    norm_path = validate_document_path(body.document_path, settings)
    _log_payload(settings, payload_svc, db, "/documents/content-markers", extract_project_name(norm_path), body.model_dump(), user_id)

    try:
        from app.services.word.edit_content import GetContentMarkersRequest as EditSvcRequest
        result = svc.get_content_markers(
            EditSvcRequest(document_path=norm_path, section_bookmark=body.section_bookmark)
        )
        return _ok(result, "Found content markers.", "content_markers_retrieved")
    except Exception as e:
        return _ok(None, f"Failed to retrieve content markers: {str(e)}", "content_markers_failed", success=False)


@router.post(
    "/content-text",
    response_model=ApiResponse[GetContentTextResult],
    summary="Get full content text between markers",
    description=(
        "Returns the complete HTML content between the Content_Start and Content_End markers "
        "for a given logical_id. This text can be edited by the user and then replaced using "
        "the replace-content-text endpoint."
    ),
)
def get_content_text(
    body: GetContentTextRequest,
    svc=Depends(get_edit_content_service),
    settings: Settings = Depends(get_settings),
    payload_svc=Depends(get_payload_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[GetContentTextResult]:
    norm_path = validate_document_path(body.document_path, settings)
    _log_payload(settings, payload_svc, db, "/documents/content-text", extract_project_name(norm_path), body.model_dump(), user_id)

    try:
        from app.services.word.edit_content import GetContentTextRequest as EditSvcRequest
        result = svc.get_content_text(
            EditSvcRequest(document_path=norm_path, logical_id=body.logical_id)
        )
        return _ok(result, "Content text retrieved.", "content_text_retrieved")
    except Exception as e:
        return _ok(None, f"Failed to retrieve content text: {str(e)}", "content_text_failed", success=False)


@router.post(
    "/replace-content-text",
    response_model=ApiResponse[ReplaceContentTextResult],
    summary="Replace content text between markers",
    description=(
        "Replaces the content between Content_Start and Content_End markers with new HTML content. "
        "Set `save_as_copy` to write the change to a new copy (named `copy_name`) in the source folder, "
        "leaving the original untouched."
    ),
)
def replace_content_text(
    body: ReplaceContentTextRequest,
    svc=Depends(get_edit_content_service),
    settings: Settings = Depends(get_settings),
    payload_svc=Depends(get_payload_service),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[ReplaceContentTextResult]:
    norm_path = validate_document_path(body.document_path, settings)
    _log_payload(settings, payload_svc, db, "/documents/replace-content-text", extract_project_name(norm_path), body.model_dump(), user_id)

    # Resolve where the edit is written
    if body.save_as_copy:
        name = os.path.basename((body.copy_name or "").strip())
        if not name:
            return _ok(None, "Please provide a name for the copy.", "replace_content_copy_name_required", success=False)
        if not name.lower().endswith(".docx"):
            name += ".docx"
        output_path = os.path.join(os.path.dirname(os.path.abspath(norm_path)), name)
        if os.path.normpath(output_path) == os.path.normpath(norm_path):
            return _ok(None, "The copy name matches the original. Choose a different name.", "replace_content_copy_conflict", success=False)
        if os.path.exists(output_path):
            return _ok(None, f"A file named '{name}' already exists. Choose a different name.", "replace_content_copy_exists", success=False)
        created_copy = True
    else:
        output_path = norm_path
        created_copy = False

    try:
        from app.services.word.edit_content import ReplaceContentTextRequest as EditSvcRequest
        result = svc.replace_content_text(
            EditSvcRequest(
                document_path=norm_path,
                logical_id=body.logical_id,
                new_html_content=body.new_html_content,
                save_as_copy=body.save_as_copy,
                copy_name=body.copy_name,
            )
        )
        where = f"copy {result.output_path}" if result.created_copy else norm_path
        audit_svc.create(db, user_id, f"Content text replaced in {where}")
        message = (
            "Content text replaced into a new copy - the original is unchanged."
            if result.created_copy else "Content text replaced."
        )
        return _ok(result, message, "replace_content_success")
    except Exception as e:
        return _ok(None, f"Content text replacement failed: {str(e)}", "replace_content_failed", success=False)


@router.post(
    "/sections/delete",
    response_model=ApiResponse[bool],
    summary="Delete document sections by bookmark range",
    description=(
        "Removes content from each start bookmark through the corresponding stop bookmark. "
        "Pass a map of `{start_bookmark: stop_bookmark}` pairs in the `sections` field."
    ),
)
def delete_sections(
    body: DeleteSectionRequest,
    svc=Depends(get_section_service),
    settings: Settings = Depends(get_settings),
    payload_svc=Depends(get_payload_service),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[bool]:
    # Validate path and log payload
    norm_path = validate_document_path(body.document_path, settings)
    _log_payload(settings, payload_svc, db, "/documents/sections/delete", extract_project_name(norm_path), body.model_dump(), user_id)
    ok = svc.delete_sections(
        DeleteSvcRequest(
            document_path=norm_path,
            toc_bookmarks=body.sections,
            track_in_history=body.track_in_history,
        )
    )
    if ok:
        audit_svc.create(db, user_id, f"Sections deleted in {norm_path}")
        return _ok(True, "Sections removed.", "section_delete_success")
    return _ok(False, "Section delete failed.", "section_delete_failed", success=False)


@router.post(
    "/images",
    response_model=ApiResponse[bool],
    summary="Insert an image with optional caption",
    description=(
        "Upload an image file and insert it before the target TOC bookmark. "
        "Supports caption above or below the image with alignment and font options."
    ),
)
async def insert_image(
    document_path: Annotated[str, Form(description="Full path to the target .docx file.")],
    insert_before_bookmark: Annotated[str, Form(description="TOC bookmark before which the image is inserted.")],
    file: UploadFile = File(..., description="Image file (PNG, JPG, GIF, BMP)."),
    image_caption: Annotated[str, Form(description="Optional caption text.")] = "",
    font_size: Annotated[int, Form(description="Caption font size in points.")] = 13,
    is_caption_bold: Annotated[bool, Form(description="Render caption in bold.")] = True,
    caption_placement: Annotated[str, Form(description="'top' or 'bottom'.")] = "bottom",
    caption_alignment: Annotated[str, Form(description="'left', 'center', or 'right'.")] = "center",
    highlight: Annotated[bool, Form(description="Highlight the inserted block.")] = False,
    svc=Depends(get_image_service),
    settings: Settings = Depends(get_settings),
    payload_svc=Depends(get_payload_service),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[bool]:
    # Validate path and enforce upload size limit
    norm_path = validate_document_path(document_path, settings)
    image_bytes = await file.read()
    # Basic upload size protection (reject > 10MB by default)
    max_size = getattr(settings, 'max_upload_size_bytes', 10 * 1024 * 1024)
    if len(image_bytes) > max_size:
        raise HTTPException(status_code=413, detail="Uploaded image exceeds maximum allowed size")

    _log_payload(
        settings,
        payload_svc,
        db,
        "/documents/images",
        extract_project_name(norm_path),
        {"document_path": norm_path, "insert_before_bookmark": insert_before_bookmark, "filename": file.filename},
        user_id,
    )
    ok = svc.insert_image(
        InsertImageRequest(
            document_path=norm_path,
            insert_before_bookmark=insert_before_bookmark,
            image_bytes=image_bytes,
            filename=file.filename or "image.png",
            caption=image_caption,
            font_size=font_size,
            caption_bold=is_caption_bold,
            caption_placement=caption_placement,
            caption_alignment=caption_alignment,
            highlight=highlight,
        )
    )
    if ok:
        audit_svc.create(db, user_id, f"Image inserted in {norm_path}")
        return _ok(True, "Image inserted.", "image_insert_success")
    return _ok(False, "Image insert failed.", "image_insert_failed", success=False)


@router.post(
    "/coversheet",
    response_model=ApiResponse[str],
    summary="Apply a coversheet to a template",
    description=(
        "Clones the coversheet and appends the template body content after the coversheet's "
        "front matter, preserving destination list/numbering styles."
    ),
)
def apply_coversheet(
    body: ApplyCoversheetRequest,
    svc=Depends(get_coversheet_service),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[str]:
    output = svc.apply_coversheet(body.template_path, body.coversheet_path)
    audit_svc.create(
        db,
        user_id,
        f"Coversheet {body.coversheet_path} applied to {body.template_path}",
    )
    return _ok(output, "Coversheet applied.", "coversheet_success")


@router.post(
    "/fields/update",
    response_model=ApiResponse[bool],
    summary="Update table/image captions and fields",
    description=(
        "Marks caption and sequence fields as dirty so Microsoft Word recalculates "
        "them the next time the document is opened."
    ),
)
def update_fields(
    body: DocumentPathRequest,
    svc=Depends(get_fields_service),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[bool]:
    norm_path = validate_document_path(body.document_path, settings)
    ok = svc.update_captions(norm_path)
    if ok:
        audit_svc.create(db, user_id, f"Fields updated for {norm_path}")
        return _ok(True, "Fields marked for update.", "fields_update_success")
    return _ok(True, "No fields required updating.", "fields_update_noop")


@router.post(
    "/toc/update",
    response_model=ApiResponse[bool],
    summary="Refresh the table of contents",
    description=(
        "Marks TOC fields as dirty so Word rebuilds the table of contents on next open. "
        "Pure OOXML approach — no Word COM automation required."
    ),
)
def update_toc(
    body: DocumentPathRequest,
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
) -> ApiResponse[bool]:
    norm_path = validate_document_path(body.document_path, get_settings())
    with DocxPackage(norm_path).edit_copy() as pkg:
        changed = toc.update_toc(pkg)
    if changed:
        audit_svc.create(db, user_id, f"TOC updated for {norm_path}")
        return _ok(True, "TOC marked for refresh.", "toc_update_success")
    return _ok(True, "TOC update not required.", "toc_update_noop")


@router.post(
    "/replace",
    response_model=ApiResponse[bool],
    summary="Replace a document after table verification",
    description=(
        "Upload a new document and replace the existing file only when a target table "
        "matches identifying cell rules in both files. Prevents accidental overwrites."
    ),
)
async def replace_document(
    old_document_path: Annotated[str, Form(description="Path to the existing document to replace.")],
    identifying_rules_json: Annotated[
        str,
        Form(
            description='JSON array of table rules, e.g. `[{"row":1,"col":1,"value":"Doc-ID"}]`.',
            examples=['[{"row": 1, "col": 1, "value": "Document ID"}]'],
        ),
    ],
    new_document: UploadFile = File(..., description="Replacement .docx file."),
    svc=Depends(get_replace_service),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
    settings: Settings = Depends(get_settings),
) -> ApiResponse[bool]:
    rules_data = json.loads(identifying_rules_json)
    rules = [ReplaceRule(row=r["row"], col=r["col"], value=r["value"]) for r in rules_data]
    # Validate the existing document path and enforce upload limits
    norm_old_path = validate_document_path(old_document_path, settings)
    content = await new_document.read()
    max_size = getattr(settings, 'max_upload_size_bytes', 10 * 1024 * 1024)
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail="Uploaded document exceeds maximum allowed size")
    ok = svc.compare_and_replace(content, norm_old_path, rules)
    if ok:
        audit_svc.create(db, user_id, f"Document replaced: {norm_old_path}")
        return _ok(True, "Document replaced successfully.", "replace_success")
    return _ok(False, "Replace failed — table or content mismatch.", "replace_failed", success=False)


@router.post(
    "/inserted-text/markers",
    response_model=ApiResponse[list[InsertedMarkerInfo]],
    summary="List editable inserted-text markers in a section",
    description=(
        "Returns logical IDs for inserted paragraphs/sections within a given section number. "
        "Use these IDs with the content and update endpoints."
    ),
)
def get_inserted_markers(body: InsertedMarkersRequest, svc=Depends(get_inserted_text_service), settings: Settings = Depends(get_settings)) -> ApiResponse[list[InsertedMarkerInfo]]:
    norm_path = validate_document_path(body.document_path, settings)
    markers = [
        InsertedMarkerInfo(logical_id=m["logical_id"], section_number=m["section_number"])
        for m in svc.get_markers(norm_path, body.section_number)
    ]
    if markers:
        return _ok(markers, "Markers found.", "markers_success")
    return _ok([], "No markers found for this section.", "markers_empty", success=False)


@router.post(
    "/inserted-text/content",
    response_model=ApiResponse[str],
    summary="Get text content for an inserted marker",
    description="Retrieves the plain text between the start and end bookmarks for a logical marker ID.",
)
def get_inserted_text(body: InsertedTextRequest, svc=Depends(get_inserted_text_service), settings: Settings = Depends(get_settings)) -> ApiResponse[str]:
    norm_path = validate_document_path(body.document_path, settings)
    content = svc.get_content(norm_path, body.logical_id)
    if content is None:
        return _ok("", "Marker not found.", "inserted_text_not_found", success=False)
    return _ok(content, "Content retrieved.", "inserted_text_success")


@router.put(
    "/inserted-text",
    response_model=ApiResponse[bool],
    summary="Update text for an inserted marker",
    description=(
        "Replaces content between the marker bookmarks. Supports plain text or simple HTML "
        "and optional highlight shading."
    ),
)
def update_inserted_text(
    body: UpdateInsertedTextBody,
    svc=Depends(get_inserted_text_service),
    audit_svc=Depends(get_audit_service),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_optional_user_id),
    settings: Settings = Depends(get_settings),
) -> ApiResponse[bool]:
    norm_path = validate_document_path(body.document_path, settings)
    ok = svc.update_content(
        UpdateSvcRequest(
            document_path=norm_path,
            logical_id=body.logical_id,
            text=body.text,
            highlight=body.highlight,
            is_html=body.is_html,
        )
    )
    if ok:
        audit_svc.create(
            db,
            user_id,
            f"Inserted text {body.logical_id} updated in {norm_path}",
        )
        return _ok(True, "Inserted text updated.", "inserted_text_update_success")
    return _ok(False, "Update failed — marker not found.", "inserted_text_update_failed", success=False)


@router.post(
    "/inserted-text/sections",
    response_model=ApiResponse[list[TocItem]],
    summary="List sections that contain inserted editable content",
    description=(
        "Scans custom XML metadata and returns section numbers that have inserted or "
        "merged content available for editing."
    ),
)
def get_editable_sections(body: DocumentPathRequest, svc=Depends(get_inserted_text_service), settings: Settings = Depends(get_settings)) -> ApiResponse[list[TocItem]]:
    norm_path = validate_document_path(body.document_path, settings)
    sections = [TocItem(**row) for row in svc.get_editable_sections(norm_path)]
    if sections:
        return _ok(sections, "Editable sections found.", "editable_sections_success")
    return _ok([], "No editable sections found.", "editable_sections_empty", success=False)
