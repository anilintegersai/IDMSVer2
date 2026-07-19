from __future__ import annotations

import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import Settings
from app.services.word.edit_content import (
    EditContentService,
    GetContentMarkersRequest,
    GetContentTextRequest,
    GetEditableSectionsRequest,
    ReplaceContentTextRequest,
)


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _write_minimal_docx(path: Path) -> None:
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:bookmarkStart w:id="1" w:name="_TocAlpha"/>
      <w:r><w:t>Alpha</w:t></w:r>
      <w:bookmarkEnd w:id="1"/>
    </w:p>
    <w:bookmarkStart w:id="2" w:name="Content_Start_abc12345"/>
    <w:bookmarkEnd w:id="2"/>
    <w:p><w:r><w:t>First inserted</w:t></w:r></w:p>
    <w:p><w:r><w:t>Second inserted</w:t></w:r></w:p>
    <w:bookmarkStart w:id="3" w:name="Content_End_abc12345"/>
    <w:bookmarkEnd w:id="3"/>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:bookmarkStart w:id="4" w:name="_TocBeta"/>
      <w:r><w:t>Beta</w:t></w:r>
      <w:bookmarkEnd w:id="4"/>
    </w:p>
  </w:body>
</w:document>
"""
    styles_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
  </w:style>
</w:styles>
"""
    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>
"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/styles.xml", styles_xml)


class EditContentServiceTests(unittest.TestCase):
    def test_content_markers_are_found_when_markers_are_body_siblings(self) -> None:
        with TemporaryDirectory() as tmp:
            docx_path = Path(tmp) / "editable.docx"
            _write_minimal_docx(docx_path)
            svc = EditContentService(Settings())

            sections = svc.get_editable_sections(
                GetEditableSectionsRequest(document_path=str(docx_path))
            ).sections
            self.assertEqual(
                [(s.logical_id, s.section_bookmark, s.section_number, s.preview) for s in sections],
                [("abc12345", "_TocAlpha", "1", "First inserted Second inserted")],
            )

            markers = svc.get_content_markers(
                GetContentMarkersRequest(document_path=str(docx_path), section_bookmark="_TocAlpha")
            ).markers
            self.assertEqual(
                [(m.logical_id, m.preview) for m in markers],
                [("abc12345", "First inserted Second inserted")],
            )

            html = svc.get_content_text(
                GetContentTextRequest(document_path=str(docx_path), logical_id="abc12345")
            ).html_content
            self.assertEqual(html, "<p>First inserted</p><p>Second inserted</p>")

    def test_replace_content_keeps_marker_pair_editable(self) -> None:
        with TemporaryDirectory() as tmp:
            docx_path = Path(tmp) / "editable.docx"
            _write_minimal_docx(docx_path)
            svc = EditContentService(Settings())

            result = svc.replace_content_text(
                ReplaceContentTextRequest(
                    document_path=str(docx_path),
                    logical_id="abc12345",
                    new_html_content="<p>Changed content</p>",
                    save_as_copy=True,
                    copy_name="edited.docx",
                )
            )

            edited_path = Path(tmp) / "edited.docx"
            self.assertTrue(result.created_copy)
            self.assertEqual(result.output_path, str(edited_path))

            html = svc.get_content_text(
                GetContentTextRequest(document_path=str(edited_path), logical_id="abc12345")
            ).html_content
            self.assertEqual(html, "<p>Changed content</p>")

            markers = svc.get_content_markers(
                GetContentMarkersRequest(document_path=str(edited_path), section_bookmark="_TocAlpha")
            ).markers
            self.assertEqual(
                [(m.logical_id, m.preview) for m in markers],
                [("abc12345", "Changed content")],
            )


if __name__ == "__main__":
    unittest.main()
