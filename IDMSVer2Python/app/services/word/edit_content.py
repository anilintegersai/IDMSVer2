"""Edit content operations for user-inserted text."""

from __future__ import annotations

from dataclasses import dataclass
from lxml import etree

from app.config import Settings
from app.core.namespaces import w_tag
from app.services.word import bookmarks
from app.services.word.document_package import DOCUMENT_XML, DocxPackage
from app.services.word.paragraph import _html_to_paragraphs, _shading_properties


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
        with DocxPackage(request.document_path).read() as pkg:
            body = pkg.body
            heading_styles = bookmarks.get_heading_style_map(pkg)
            
            editable_sections: list[EditableContent] = []
            
            # Find all Content_Start bookmarks
            for bookmark_start in body.findall(f".//w:bookmarkStart[@w:name[starts-with(., 'Content_Start_')]]", namespaces=bookmarks.NS):
                bookmark_name = bookmark_start.get(f"{{{bookmarks.NS['w']}}}name")
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
        with DocxPackage(request.document_path).read() as pkg:
            body = pkg.body
            heading_styles = bookmarks.get_heading_style_map(pkg)
            
            markers: list[ContentMarker] = []
            
            # Find the section paragraph
            section_para = bookmarks.find_bookmark_paragraph(body, request.section_bookmark)
            if section_para is None:
                return GetContentMarkersResult(markers=[])
            
            # Find the end of this section (next heading or end of body)
            next_heading = bookmarks.find_next_heading(body, section_para, heading_styles)
            
            # Find all Content_Start bookmarks within this section
            for bookmark_start in body.findall(f".//w:bookmarkStart[@w:name[starts-with(., 'Content_Start_')]]", namespaces=bookmarks.NS):
                bookmark_name = bookmark_start.get(f"{{{bookmarks.NS['w']}}}name")
                logical_id = bookmark_name.replace("Content_Start_", "")
                
                # Check if this bookmark is within the current section
                bookmark_para = bookmarks.find_bookmark_paragraph(body, bookmark_name)
                if bookmark_para is None:
                    continue
                
                # Check if bookmark is between section start and next heading
                is_in_section = bookmarks.is_element_between(bookmark_para, section_para, next_heading)
                if is_in_section:
                    preview = self._get_content_preview(body, logical_id)
                    if preview:  # Only add if there's actual content
                        markers.append(ContentMarker(logical_id=logical_id, preview=preview))
            
            return GetContentMarkersResult(markers=markers)

    def get_content_text(self, request: GetContentTextRequest) -> GetContentTextResult:
        """Get the full HTML content between Content_Start and Content_End markers."""
        with DocxPackage(request.document_path).read() as pkg:
            body = pkg.body
            
            start_name = f"Content_Start_{request.logical_id}"
            end_name = f"Content_End_{request.logical_id}"
            
            start_para = bookmarks.find_bookmark_paragraph(body, start_name)
            end_para = bookmarks.find_bookmark_paragraph(body, end_name)
            
            if start_para is None or end_para is None:
                return GetContentTextResult(html_content="")
            
            # Extract paragraphs between start and end
            content_paras = bookmarks.get_elements_between(start_para, end_para)
            
            # Convert paragraphs to HTML
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
            body = pkg.document
            
            start_name = f"Content_Start_{request.logical_id}"
            end_name = f"Content_End_{request.logical_id}"
            
            start_para = bookmarks.find_bookmark_paragraph(body, start_name)
            end_para = bookmarks.find_bookmark_paragraph(body, end_name)
            
            if start_para is None or end_para is None:
                raise ValueError(f"Markers for logical_id {request.logical_id} not found")
            
            # Get the paragraph after the start bookmark (this is where content starts)
            content_start = bookmarks.get_element_after_bookmark(body, start_name)
            if content_start is None:
                raise ValueError("Could not find content start position")
            
            # Remove all elements between content start and end bookmark
            elements_to_remove = bookmarks.get_elements_between(content_start, end_para)
            for elem in elements_to_remove:
                if elem.getparent() is not None:
                    elem.getparent().remove(elem)
            
            # Convert new HTML to paragraphs
            new_paras = _html_to_paragraphs(request.new_html_content, None)
            
            # Insert new paragraphs before the end bookmark
            for para in reversed(new_paras):
                bookmarks.insert_elements_before(end_para, [para])
            
            pkg.set_xml(DOCUMENT_XML, pkg.document)
        
        return ReplaceContentTextResult(output_path=output_path, created_copy=created_copy)

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
        start_name = f"Content_Start_{logical_id}"
        end_name = f"Content_End_{logical_id}"
        
        start_para = bookmarks.find_bookmark_paragraph(body, start_name)
        end_para = bookmarks.find_bookmark_paragraph(body, end_name)
        
        if start_para is None or end_para is None:
            return ""
        
        content_paras = bookmarks.get_elements_between(start_para, end_para)
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

    def _paragraphs_to_html(self, paragraphs: list[etree._Element]) -> str:
        """Convert Word paragraphs back to HTML."""
        html_parts = []
        
        for para in paragraphs:
            # Extract text and formatting
            text = ""
            runs = para.findall(w_tag("r"))
            for run in runs:
                run_text = run.findtext(w_tag("t"), default="")
                if run_text:
                    # Check for formatting
                    rpr = run.find(w_tag("rPr"))
                    if rpr is not None:
                        if rpr.find(w_tag("b")) is not None:
                            run_text = f"<b>{run_text}</b>"
                        if rpr.find(w_tag("i")) is not None:
                            run_text = f"<i>{run_text}</i>"
                    text += run_text
            
            if text.strip():
                html_parts.append(f"<p>{text}</p>")
        
        return "".join(html_parts)
