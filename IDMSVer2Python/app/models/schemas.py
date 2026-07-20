"""Pydantic request/response schemas for the documents API.

Every field includes a description that appears in Swagger UI when expanding
request/response models, making each endpoint self-documenting.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

_UNC_EXAMPLE = r"\\YokogawaSharedFolder\ProjectDocs\MyProject\document.docx"


class ApiResponse(BaseModel, Generic[T]):
    """Standard envelope returned by all document processing endpoints."""

    success: bool = Field(description="True when the operation completed without error.")
    message: str = Field(description="Human-readable summary of the result.")
    message_code: str | None = Field(
        default=None,
        description="Stable code for client-side branching (e.g. `merge_success`, `toc_empty`).",
    )
    data: T | None = Field(default=None, description="Typed payload — shape depends on the endpoint.")


class DocumentPathRequest(BaseModel):
    """Provide the full path to a Word document on shared or local storage."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"document_path": _UNC_EXAMPLE}]
        }
    )

    document_path: str = Field(
        ...,
        description="Full UNC or local path to an existing .docx file.",
        examples=[_UNC_EXAMPLE],
    )


class TocItem(BaseModel):
    """A node in the document table of contents / outline.

    The UI displays `section_number`, `item_text`, and `page_no`; the remaining
    fields (`bookmark`, `level`, `children`) drive the drag-and-drop merge.
    """

    sl_no: str = Field(default="", description="Serial/order number of the TOC entry.")
    section_number: str = Field(default="", description="Hierarchical section number, e.g. `4.2.1`.")
    item_text: str = Field(description="Heading or section title as shown in the TOC.")
    page_no: str = Field(default="", description="Printed page number shown in the TOC.")
    page_ref: str = Field(default="", description="Internal page reference, if present.")
    bookmark: str = Field(
        default="",
        description="Bookmark anchor (e.g. `_Toc12345`) this entry links to — used as the merge start/insert target.",
    )
    level: int = Field(default=1, description="Outline depth: 1 = top level, 2 = sub-section, …")
    children: list["TocItem"] = Field(
        default_factory=list, description="Nested child TOC entries (sub-sections)."
    )


TocItem.model_rebuild()


class TocEntry(BaseModel):
    """A single TOC entry with basic fields."""

    sl_no: int = Field(description="Serial/order number of the TOC entry.")
    item_text: str = Field(description="Heading or section title as shown in the TOC.")
    page_ref: str = Field(default="", description="Internal page reference/bookmark anchor.")
    page_no: str = Field(default="", description="Printed page number shown in the TOC.")
    section_number: str = Field(default="", description="Hierarchical section number, e.g. `1.2.3`.")
    level: int = Field(default=1, description="Outline depth: 1 = top level, 2 = sub-section, …")


class GetTocRequest(BaseModel):
    """Request to get TOC from a document."""

    document_path: str = Field(
        ...,
        description="Full UNC or local path to an existing .docx file.",
        examples=[_UNC_EXAMPLE],
    )


class GetTocResult(BaseModel):
    """Result containing TOC entries."""

    entries: list[TocEntry] = Field(description="List of TOC entries from the document.")


class DocumentListItem(BaseModel):
    """A selectable source document."""

    name: str = Field(description="File name shown in the dropdown.")
    path: str = Field(description="Full path used when calling TOC / merge endpoints.")


class MergeSectionApiRequest(BaseModel):
    """Merge a heading (and all its descendants) from a source doc into a copy
    of the master, saving the result to the merged-output folder."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "master_template_path": _UNC_EXAMPLE,
                    "source_document_path": _UNC_EXAMPLE,
                    "source_start_bookmark": "_Toc100000010",
                    "source_stop_bookmark": "_Toc100000020",
                    "insert_before_bookmark": "_Toc500000030",
                }
            ]
        }
    )

    master_template_path: str = Field(..., description="Master document — a copy is created; the original is never modified.")
    source_document_path: str = Field(..., description="Associated document to copy the section from.")
    source_start_bookmark: str = Field(..., description="Bookmark of the dragged heading (start of the section).")
    source_stop_bookmark: str | None = Field(
        default=None,
        description="Bookmark of the next same-or-higher heading (exclusive end). Null copies to end of source.",
    )
    insert_before_bookmark: str | None = Field(
        default=None,
        description="Master bookmark to insert before. Null appends at the end of the master.",
    )
    output_filename: str | None = Field(
        default=None, description="Optional output file name; auto-generated when omitted."
    )


class MergeSourceSection(BaseModel):
    """Identifies which section to copy from the source (associated) document."""

    source_document_path: str = Field(
        ...,
        description="Path to the source .docx that contains the section to merge.",
        examples=[_UNC_EXAMPLE],
    )
    start_bookmark: str = Field(
        ...,
        description="Bookmark name at the start of the section (usually a `_Toc…` bookmark).",
        examples=["_Toc123456789"],
    )
    stop_bookmark: str = Field(
        ...,
        description="Bookmark name at the end of the section (exclusive boundary).",
        examples=["_Toc987654321"],
    )


class MergeDocumentRequest(BaseModel):
    """Merge a section from a source document into a cloned master template.

    Processing preserves **destination** list bullets, numbering styles, and heading
    levels. Source numbering definitions are not copied wholesale into the output.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "master_template_path": _UNC_EXAMPLE,
                    "output_path": r"\\YokogawaSharedFolder\ProjectDocs\MyProject\merged-R1.docx",
                    "insert_before_bookmark": "_Toc500000001",
                    "source": {
                        "source_document_path": r"\\YokogawaSharedFolder\ProjectDocs\MyProject\associated.docx",
                        "start_bookmark": "_Toc100000001",
                        "stop_bookmark": "_Toc100000002",
                    },
                }
            ]
        }
    )

    master_template_path: str = Field(
        ...,
        description="Path to the master template used as the merge destination base.",
    )
    output_path: str = Field(
        ...,
        description="Full path where the new merged .docx will be written. Must not already exist.",
    )
    insert_before_bookmark: str = Field(
        ...,
        description="TOC bookmark in the master template — copied content is inserted immediately before this section.",
    )
    source: MergeSourceSection = Field(
        ...,
        description="Source document and bookmark range defining the content block to copy.",
    )


class MergeDocumentResult(BaseModel):
    """Result of a successful or attempted merge operation."""

    output_path: str = Field(description="Path to the generated merged document.")
    logical_id: str | None = Field(
        default=None,
        description="8-character ID for the merge marker — use with inserted-text endpoints to locate content.",
    )
    embedded_objects_count: int = Field(
        default=0,
        description="Number of tables copied during the merge.",
    )


class InsertParagraphRequest(BaseModel):
    """Insert plain text before a TOC bookmark."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "document_path": _UNC_EXAMPLE,
                    "insert_before_bookmark": "_Toc500000001",
                    "text": "This paragraph will appear before section 4.2.",
                    "highlight": True,
                    "track_in_history": False,
                }
            ]
        }
    )

    document_path: str = Field(..., description="Target .docx file path.")
    insert_before_bookmark: str = Field(
        ...,
        description="TOC bookmark name — content is inserted directly before this section heading.",
    )
    text: str = Field(..., description="Plain text to insert. Use `\\n` for multiple lines.")
    highlight: bool = Field(
        default=False,
        description="When true, applies the configured shade color (default E2EAF4) to inserted paragraphs.",
    )
    track_in_history: bool = Field(
        default=False,
        description="Reserved for revision-history table integration (Phase 2).",
    )


class InsertSectionRequest(BaseModel):
    """Insert a new heading and body content before a TOC bookmark."""

    document_path: str = Field(..., description="Target .docx file path.")
    insert_before_bookmark: str | None = Field(default=None, description="TOC bookmark before which the section is added.")
    title: str = Field(..., description="Heading text for the new section.")
    content: str = Field(..., description="Body text or HTML content below the heading.")
    level: int = Field(
        default=1,
        ge=1,
        le=9,
        description="Word heading level (1 = top-level, 9 = deepest sub-section).",
    )
    highlight: bool = Field(default=False, description="Apply highlight shading to heading and body.")
    is_html: bool = Field(
        default=False,
        description="Parse `content` as HTML (supports p, b, i, br, div, li tags).",
    )
    save_as_copy: bool = Field(
        default=False,
        description="When true, the change is written to a NEW copy (named `copy_name`) in the "
        "source folder and the original document is left untouched. When false, the original is "
        "edited in place.",
    )
    copy_name: str | None = Field(
        default=None,
        description="File name for the copy (required when `save_as_copy` is true). `.docx` is "
        "appended if missing; any path components are stripped so the copy stays in the source folder.",
    )
    track_in_history: bool = Field(default=False, description="Reserved for revision-history integration.")


class InsertSectionResult(BaseModel):
    """Result of an insert-section operation."""

    output_path: str = Field(description="Path to the document that was written (the copy, or the original when edited in place).")
    created_copy: bool = Field(default=False, description="True when the change was written to a new copy, leaving the original unchanged.")


class InsertContentRequest(BaseModel):
    """Insert HTML content and images at the end of a section (before the next heading)."""

    document_path: str = Field(..., description="Target .docx file path.")
    section_bookmark: str = Field(
        ...,
        description="TOC bookmark of the section where content should be appended (at the end of the section's content, before the next heading).",
    )
    html_content: str = Field(
        default="",
        description="HTML content to insert (supports p, b, i, br, div, li, img tags).",
    )
    image_data: str | None = Field(
        default=None,
        description="Base64-encoded image data (with data URL prefix like 'data:image/png;base64,...').",
    )
    image_caption: str | None = Field(
        default=None,
        description="Caption text for the image (if image_data is provided).",
    )
    image_width: float | None = Field(
        default=None,
        description="Image width in inches (if image_data is provided). Default is 5 inches.",
    )
    image_height: float | None = Field(
        default=None,
        description="Image height in inches (if image_data is provided). Default is 3.75 inches.",
    )
    highlight: bool = Field(default=False, description="Apply highlight shading to inserted content.")
    save_as_copy: bool = Field(
        default=False,
        description="When true, the change is written to a NEW copy (named `copy_name`) in the "
        "source folder and the original document is left untouched. When false, the original is "
        "edited in place.",
    )
    copy_name: str | None = Field(
        default=None,
        description="File name for the copy (required when `save_as_copy` is true). `.docx` is "
        "appended if missing; any path components are stripped so the copy stays in the source folder.",
    )
    track_in_history: bool = Field(default=False, description="Reserved for revision-history integration.")


class InsertContentResult(BaseModel):
    """Result of an insert-content operation."""

    output_path: str = Field(description="Path to the document that was written (the copy, or the original when edited in place).")
    created_copy: bool = Field(default=False, description="True when the change was written to a new copy, leaving the original unchanged.")


class EditableContent(BaseModel):
    """Represents an editable content block with its metadata."""
    logical_id: str = Field(description="Unique identifier for the content block.")
    section_bookmark: str = Field(description="TOC bookmark of the section containing this content.")
    section_number: str = Field(description="Section number (e.g., '6.1', '7.2.1').")
    section_title: str = Field(description="Section title.")
    preview: str = Field(description="Preview text (first 40-50 characters).")


class GetEditableSectionsRequest(BaseModel):
    """Request to get all sections with editable content."""
    document_path: str = Field(..., description="Target .docx file path.")


class GetEditableSectionsResult(BaseModel):
    """Result containing all sections with editable content."""
    sections: list[EditableContent] = Field(description="List of editable content blocks.")


class ContentMarker(BaseModel):
    """Represents a content marker within a section."""
    logical_id: str = Field(description="Unique identifier for the content block.")
    preview: str = Field(description="Preview text (first 40-50 characters).")


class GetContentMarkersRequest(BaseModel):
    """Request to get content markers for a specific section."""
    document_path: str = Field(..., description="Target .docx file path.")
    section_bookmark: str = Field(..., description="TOC bookmark of the section.")


class GetContentMarkersResult(BaseModel):
    """Result containing content markers for a section."""
    markers: list[ContentMarker] = Field(description="List of content markers in the section.")


class GetContentTextRequest(BaseModel):
    """Request to get the full text between markers."""
    document_path: str = Field(..., description="Target .docx file path.")
    logical_id: str = Field(..., description="Unique identifier for the content block.")


class GetContentTextResult(BaseModel):
    """Result containing the HTML content between markers."""
    html_content: str = Field(description="HTML content between the markers.")


class ReplaceContentTextRequest(BaseModel):
    """Request to replace content between markers."""
    document_path: str = Field(..., description="Target .docx file path.")
    logical_id: str = Field(..., description="Unique identifier for the content block.")
    new_html_content: str = Field(..., description="New HTML content to insert.")
    save_as_copy: bool = Field(default=False, description="When true, write to a new copy instead of modifying original.")
    copy_name: str | None = Field(default=None, description="File name for the copy (required when save_as_copy is true).")


class ReplaceContentTextResult(BaseModel):
    """Result of a replace-content operation."""
    output_path: str = Field(description="Path to the document that was written (the copy, or the original when edited in place).")
    created_copy: bool = Field(default=False, description="True when the change was written to a new copy, leaving the original unchanged.")


class DeleteSectionRequest(BaseModel):
    """Remove one or more sections identified by bookmark pairs."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "document_path": _UNC_EXAMPLE,
                    "sections": {
                        "_Toc100000001": "_Toc100000002",
                        "_Toc200000001": "_Toc200000002",
                    },
                    "track_in_history": False,
                }
            ]
        }
    )

    document_path: str = Field(..., description="Target .docx file path.")
    sections: dict[str, str] = Field(
        ...,
        description="Dictionary mapping each **start** bookmark to its **stop** bookmark. All content between them is removed.",
    )
    track_in_history: bool = Field(default=False, description="Reserved for revision-history integration.")


class ApplyCoversheetRequest(BaseModel):
    """Copy template body content onto a coversheet document."""

    template_path: str = Field(
        ...,
        description="Source template — its body content (after the TOC block) is appended to the coversheet.",
    )
    coversheet_path: str = Field(
        ...,
        description="Coversheet .docx that receives the template content. A timestamped copy is created.",
    )


class InsertedMarkersRequest(BaseModel):
    """List editable content markers within a specific section."""

    document_path: str = Field(..., description="Document containing previously inserted or merged content.")
    section_number: str = Field(
        ...,
        description="Section number (e.g. `4.2`) to filter markers. Obtain section numbers from the TOC endpoint.",
        examples=["4.2"],
    )


class InsertedTextRequest(BaseModel):
    """Retrieve the text stored under a specific marker."""

    document_path: str = Field(..., description="Document containing the marker.")
    logical_id: str = Field(
        ...,
        description="8-character marker ID returned by the `/inserted-text/markers` endpoint.",
        examples=["a1b2c3d4"],
    )


class UpdateInsertedTextBody(BaseModel):
    """Replace the content between a marker's start and end bookmarks."""

    document_path: str = Field(..., description="Document containing the marker.")
    logical_id: str = Field(..., description="Marker ID to update.")
    text: str = Field(..., description="New plain text or HTML content.")
    highlight: bool = Field(default=False, description="Apply highlight shading to the updated content.")
    is_html: bool = Field(default=False, description="When true, `text` is parsed as HTML.")


class InsertedMarkerInfo(BaseModel):
    """A single editable content marker within a section."""

    logical_id: str = Field(description="Unique marker ID for get/update operations.")
    section_number: str = Field(description="Section number this marker belongs to.")


class TableIdentifierRule(BaseModel):
    """Identifies a table by checking cell values — used for safe document replacement."""

    row: int = Field(ge=1, description="1-based row index in the table.")
    col: int = Field(ge=1, description="1-based column index in the table.")
    value: str = Field(
        ...,
        description="Substring that must appear in the cell (case-insensitive match).",
        examples=["Document ID"],
    )
