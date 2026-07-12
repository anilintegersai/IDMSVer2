"""Read and update inserted text via bookmark markers."""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from app.config import Settings
from app.core.namespaces import CUSTOM_XML_NS, w_tag
from app.services.word import bookmarks, metadata
from app.services.word.document_package import DOCUMENT_XML, DocxPackage
from app.services.word.paragraph import _html_to_paragraphs, _text_paragraph


@dataclass
class UpdateInsertedTextRequest:
    document_path: str
    logical_id: str
    text: str
    highlight: bool = False
    is_html: bool = False


class InsertedTextService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def get_markers(self, document_path: str, section_number: str) -> list[dict[str, str]]:
        pkg = DocxPackage(document_path, writable=False)
        root = metadata.read_metadata(pkg)
        if root is None:
            return []
        ns = CUSTOM_XML_NS
        markers: list[dict[str, str]] = []
        for tag in ("InsertedParagraph", "InsertedSection"):
            for el in root.findall(f"{{{ns}}}{tag}"):
                sec = el.find(f"{{{ns}}}SectionNumber")
                if sec is not None and sec.text == section_number:
                    lid = el.get("LogicalId")
                    if lid:
                        markers.append({"logical_id": lid, "section_number": section_number})
        return markers

    def get_content(self, document_path: str, logical_id: str) -> str | None:
        pkg = DocxPackage(document_path, writable=False)
        root = metadata.read_metadata(pkg)
        if root is None:
            return None
        exists = any(
            el.get("LogicalId") == logical_id for el in root.iter() if el.get("LogicalId")
        )
        if not exists:
            return None

        body = pkg.body
        start_name = f"Insert_Start_{logical_id}"
        end_name = f"Insert_End_{logical_id}"
        body_children = list(body)
        start_idx = next(
            (i for i, e in enumerate(body_children) if e.tag == w_tag("bookmarkStart") and e.get(w_tag("name")) == start_name),
            -1,
        )
        end_idx = next(
            (i for i, e in enumerate(body_children) if e.tag == w_tag("bookmarkStart") and e.get(w_tag("name")) == end_name),
            -1,
        )
        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx + 1:
            return ""

        parts: list[str] = []
        for el in body_children[start_idx + 2 : end_idx]:
            if el.tag == w_tag("p"):
                parts.append(bookmarks.paragraph_text(el))
        return "\n".join(parts)

    def update_content(self, request: UpdateInsertedTextRequest) -> bool:
        shade = self.settings.shade_fill if request.highlight else None
        start_name = f"Insert_Start_{request.logical_id}"
        end_name = f"Insert_End_{request.logical_id}"

        with DocxPackage(request.document_path).edit_copy() as pkg:
            body = pkg.body
            children = list(body)
            start_idx = next(
                (i for i, e in enumerate(children) if e.tag == w_tag("bookmarkStart") and e.get(w_tag("name")) == start_name),
                -1,
            )
            end_idx = next(
                (i for i, e in enumerate(children) if e.tag == w_tag("bookmarkStart") and e.get(w_tag("name")) == end_name),
                -1,
            )
            if start_idx == -1 or end_idx == -1:
                return False

            # Remove old content between markers
            for el in children[start_idx + 2 : end_idx]:
                body.remove(el)

            if request.is_html:
                new_paras = _html_to_paragraphs(request.text, shade)
            else:
                new_paras = [_text_paragraph(request.text, shade)]

            anchor = children[end_idx]
            for offset, para in enumerate(new_paras):
                body.insert(body.index(anchor) + offset, para)

            pkg.set_xml(DOCUMENT_XML, pkg.document)
        return True

    def get_editable_sections(self, document_path: str) -> list[dict[str, str]]:
        pkg = DocxPackage(document_path, writable=False)
        root = metadata.read_metadata(pkg)
        if root is None:
            return []
        ns = CUSTOM_XML_NS
        sections: dict[str, dict[str, str]] = {}
        for tag in ("InsertedParagraph", "InsertedSection", "MergedSection"):
            for el in root.findall(f"{{{ns}}}{tag}"):
                sec_el = el.find(f"{{{ns}}}SectionNumber")
                if sec_el is None:
                    sec_el = el.find(f"{{{ns}}}SourceSection")
                sec = sec_el.text if sec_el is not None else ""
                if sec and sec not in sections:
                    sections[sec] = {
                        "sl_no": sec,
                        "item_text": f"Section {sec}",
                        "page_ref": "",
                        "page_no": "",
                    }
        return list(sections.values())
