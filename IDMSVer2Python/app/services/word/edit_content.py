"""Edit content operations for user-inserted text."""

from __future__ import annotations

from dataclasses import dataclass
from lxml import etree

from app.config import Settings
from app.core.namespaces import NSMAP, w_tag
from app.services.word import bookmarks
from app.services.word.document_package import DocxPackage
from app.services.word.paragraph import _html_to_paragraphs


@dataclass
class EditableContent:
    """Represents an editable content block with its metadata."""
    logical_id: str
    section_bookmark: str
    section_number: str
    section_title: str
    preview: str  # First 40-50 characters


@dataclass
class GetEditableSectionsRequest:
    document_path: str


@dataclass
class GetEditableSectionsResult:
    sections: list[EditableContent]


@dataclass
class GetContentMarkersRequest:
    document_path: str
    section_bookmark: str


@dataclass
class ContentMarker:
    logical_id: str
    preview: str


@dataclass
class GetContentMarkersResult:
    markers: list[ContentMarker]


@dataclass
class GetContentTextRequest:
    document_path: str
    logical_id: str


@dataclass
class GetContentTextResult:
    html_content: str


@dataclass
class ReplaceContentTextRequest:
    document_path: str
    logical_id: str
    new_html_content: str
    save_as_copy: bool = False
    copy_name: str | None = None


@dataclass
class ReplaceContentTextResult:
    output_path: str
    created_copy: bool


class EditContentService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def get_editable_sections(self, request: GetEditableSectionsRequest) -> GetEditableSectionsResult:
        """Get all sections that have editable content markers."""
        pkg = DocxPackage(request.document_path, writable=False)
        body = pkg.body
        heading_styles = bookmarks.get_heading_style_map(pkg)

        editable_sections: list[EditableContent] = []

        # Find all Content_Start bookmarks
        for bookmark_start in body.findall(".//w:bookmarkStart", namespaces=NSMAP):
            bookmark_name = bookmark_start.get(f"{{{NSMAP['w']}}}name")
            if bookmark_name and bookmark_name.startswith("Content_Start_"):
                logical_id = bookmark_name.replace("Content_Start_", "")

                # Find the section this content belongs to
                section_bookmark, section_number, section_title = self._find_section_for_content(body, bookmark_start, heading_styles)

                if section_bookmark:
                    # Get preview text
                    preview = self._get_content_preview(body, logical_id)

                    editable_sections.append(EditableContent(
                        logical_id=logical_id,
                        section_bookmark=section_bookmark,
                        section_number=section_number,
                        section_title=section_title,
                        preview=preview
                    ))

        return GetEditableSectionsResult(sections=editable_sections)

    def get_content_markers(self, request: GetContentMarkersRequest) -> GetContentMarkersResult:
        """Get all content markers for a specific section."""
        pkg = DocxPackage(request.document_path, writable=False)
        body = pkg.body
        heading_styles = bookmarks.get_heading_style_map(pkg)

        markers: list[ContentMarker] = []

        # Find the section bookmark element
        section_bm = bookmarks.find_bookmark_start(body, request.section_bookmark)
        if section_bm is None:
            return GetContentMarkersResult(markers=[])

        # Find the section paragraph
        section_para = bookmarks.find_bookmark_paragraph(body, request.section_bookmark)
        if section_para is None:
            return GetContentMarkersResult(markers=[])

        # Find the end of this section (next heading or end of body)
        next_heading = bookmarks.find_next_heading(body, section_para, heading_styles)

        # Find all Content_Start bookmarks within this section
        for bookmark_start in body.findall(".//w:bookmarkStart", namespaces=NSMAP):
            bookmark_name = bookmark_start.get(f"{{{NSMAP['w']}}}name")
            if bookmark_name and bookmark_name.startswith("Content_Start_"):
                logical_id = bookmark_name.replace("Content_Start_", "")

                # Check if this bookmark is within the current section using bookmark positions
                # instead of paragraph positions
                if self._is_bookmark_in_section(body, bookmark_start, section_bm, next_heading):
                    preview = self._get_content_preview(body, logical_id)
                    if preview:  # Only add if there's actual content
                        markers.append(ContentMarker(logical_id=logical_id, preview=preview))

        return GetContentMarkersResult(markers=markers)

    def get_content_text(self, request: GetContentTextRequest) -> GetContentTextResult:
        """Get the full HTML content between Content_Start and Content_End markers."""
        pkg = DocxPackage(request.document_path, writable=False)
        body = pkg.body

        content_paras = self._get_content_elements(body, request.logical_id)
        html_content = self._paragraphs_to_html(content_paras)
        return GetContentTextResult(html_content=html_content)

    def replace_content_text(self, request: ReplaceContentTextRequest) -> ReplaceContentTextResult:
        """Replace the content between markers with new HTML content."""
        # Determine output path
        if request.save_as_copy:
            if not request.copy_name:
                raise ValueError("copy_name is required when save_as_copy is true")
            import os
            name = os.path.basename(request.copy_name.strip())
            if not name.lower().endswith(".docx"):
                name += ".docx"
            output_path = os.path.join(os.path.dirname(os.path.abspath(request.document_path)), name)
            if os.path.normpath(output_path) == os.path.normpath(request.document_path):
                raise ValueError("The copy name matches the original. Choose a different name.")
            if os.path.exists(output_path):
                raise ValueError(f"A file named '{name}' already exists. Choose a different name.")
            created_copy = True
        else:
            output_path = request.document_path
            created_copy = False

        with DocxPackage(request.document_path).edit_copy(destination=output_path if created_copy else None) as pkg:
            body = pkg.body

            boundaries = self._content_range_boundaries(body, request.logical_id)
            if boundaries is None:
                raise ValueError(f"Markers for logical_id {request.logical_id} not found")

            start_boundary, end_boundary = boundaries

            # Remove only the editable body elements. The zero-length bookmark
            # start/end pairs are kept intact so the same logical ID remains editable.
            elements_to_remove = bookmarks.get_elements_between(start_boundary, end_boundary)
            for elem in elements_to_remove:
                if elem.getparent() is not None:
                    elem.getparent().remove(elem)

            # Convert new HTML to paragraphs
            new_paras = _html_to_paragraphs(request.new_html_content, None)

            # Insert new paragraphs immediately before the end marker.
            bookmarks.insert_elements_before(end_boundary, new_paras)

        return ReplaceContentTextResult(output_path=output_path, created_copy=created_copy)

    def _is_bookmark_in_section(self, body: etree._Element, content_bm: etree._Element, section_bm: etree._Element, next_heading: etree._Element | None) -> bool:
        """Check if a content bookmark is within a section based on body positions."""
        content_child = self._body_child_for_element(body, content_bm)
        section_child = self._body_child_for_element(body, section_bm)
        if content_child is None or section_child is None:
            return False

        section_index = body.index(section_child)
        content_index = body.index(content_child)
        if content_index <= section_index:
            return False

        # If there's a next heading, check if content comes before it
        if next_heading is not None:
            next_child = self._body_child_for_element(body, next_heading)
            if next_child is not None and content_index >= body.index(next_child):
                return False

        return True

    def _find_section_for_content(self, body: etree._Element, bookmark_start: etree._Element, heading_styles: dict) -> tuple[str, str, str]:
        """Find the section bookmark, number, and title for a given content bookmark."""
        bookmark_para = bookmarks.find_bookmark_paragraph_by_element(body, bookmark_start)
        if bookmark_para is None:
            return "", "", ""

        # Find the heading paragraph before this content
        heading_para = bookmarks.find_previous_heading(body, bookmark_para, heading_styles)
        if heading_para is None:
            return "", "", ""

        # Get the bookmark for this heading
        heading_bookmark = bookmarks.get_bookmark_for_paragraph(body, heading_para)
        if heading_bookmark is None:
            return "", "", ""

        # Get section number and title
        section_number = bookmarks.get_section_number_from_bookmark(body, heading_bookmark, heading_styles)
        section_title = bookmarks.get_heading_text(heading_para)

        return heading_bookmark, section_number, section_title

    def _get_content_preview(self, body: etree._Element, logical_id: str) -> str:
        """Get a preview (40-50 characters) of the content."""
        content_paras = self._get_content_elements(body, logical_id)
        if not content_paras:
            return ""

        # Extract text from first paragraph
        text = ""
        for para in content_paras[:2]:  # Check first 2 paragraphs
            para_text = etree.tostring(para, method="text", encoding="unicode")
            text += para_text.strip() + " "
            if len(text) >= 50:
                break

        preview = text.strip()[:50]
        return preview

    def _get_content_elements(self, body: etree._Element, logical_id: str) -> list[etree._Element]:
        """Return top-level body elements inside a content marker pair."""
        boundaries = self._content_range_boundaries(body, logical_id)
        if boundaries is None:
            return []
        start_boundary, end_boundary = boundaries
        return bookmarks.get_elements_between(start_boundary, end_boundary)

    def _content_range_boundaries(self, body: etree._Element, logical_id: str) -> tuple[etree._Element, etree._Element] | None:
        """Return the body children that bound editable content for a logical ID."""
        start_bm = bookmarks.find_bookmark_start(body, f"Content_Start_{logical_id}")
        end_bm = bookmarks.find_bookmark_start(body, f"Content_End_{logical_id}")
        if start_bm is None or end_bm is None:
            return None

        # bookmarkEnd elements do not carry w:name, only the numeric w:id.
        # Use the start bookmark's matching end as the lower boundary so it
        # remains in the document when content is replaced.
        start_end = self._bookmark_end_for_start(body, start_bm)
        start_boundary = self._body_child_for_element(body, start_end if start_end is not None else start_bm)
        end_boundary = self._body_child_for_element(body, end_bm)
        if start_boundary is None or end_boundary is None:
            return None
        if start_boundary.getparent() is not body or end_boundary.getparent() is not body:
            return None
        if body.index(end_boundary) <= body.index(start_boundary):
            return None
        return start_boundary, end_boundary

    def _bookmark_end_for_start(self, body: etree._Element, bookmark_start: etree._Element) -> etree._Element | None:
        bookmark_id = bookmark_start.get(w_tag("id"))
        if not bookmark_id:
            return None
        for bookmark_end in body.iter(w_tag("bookmarkEnd")):
            if bookmark_end.get(w_tag("id")) == bookmark_id:
                return bookmark_end
        return None

    def _body_child_for_element(self, body: etree._Element, element: etree._Element | None) -> etree._Element | None:
        """Return the top-level body child containing element."""
        current = element
        while current is not None and current.getparent() is not body:
            current = current.getparent()
        return current

    def _paragraphs_to_html(self, paragraphs: list[etree._Element]) -> str:
        """Convert Word paragraphs back to HTML."""
        html_parts = []

        for para in paragraphs:
            # Extract text and formatting
            text = ""
            runs = para.findall(w_tag("r"), namespaces=NSMAP)
            for run in runs:
                run_text = run.findtext(w_tag("t"), default="", namespaces=NSMAP)
                if run_text:
                    # Check for formatting
                    rpr = run.find(w_tag("rPr"), namespaces=NSMAP)
                    if rpr is not None:
                        if rpr.find(w_tag("b"), namespaces=NSMAP) is not None:
                            run_text = f"<b>{run_text}</b>"
                        if rpr.find(w_tag("i"), namespaces=NSMAP) is not None:
                            run_text = f"<i>{run_text}</i>"
                    text += run_text

            if text.strip():
                html_parts.append(f"<p>{text}</p>")

        return "".join(html_parts)
