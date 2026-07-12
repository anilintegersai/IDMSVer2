"""Coversheet application — merge template body content onto a coversheet."""

from __future__ import annotations

import os
import shutil
from datetime import datetime

from lxml import etree

from app.core.namespaces import w_tag
from app.services.word import bookmarks, numbering
from app.services.word.document_package import DOCUMENT_XML, NUMBERING_XML, DocxPackage, clone_element


class CoversheetService:
    def apply_coversheet(self, template_path: str, coversheet_path: str) -> str:
        if not os.path.isfile(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")
        if not os.path.isfile(coversheet_path):
            raise FileNotFoundError(f"Coversheet not found: {coversheet_path}")

        stamp = datetime.now().strftime("%d%b%Y_%H%M%S")
        base = os.path.basename(coversheet_path).replace(".docx", "")
        output = template_path.replace(
            os.path.basename(template_path), f"{base}-{stamp}.docx"
        )
        shutil.copy2(coversheet_path, output)

        template_pkg = DocxPackage(template_path, writable=False)
        dest = DocxPackage(output, writable=True)

        source_body = template_pkg.body
        dest_body = dest.body

        # Copy styles/numbering from template to preserve destination-like formatting
        for part in (NUMBERING_XML, "word/styles.xml"):
            if part in template_pkg.list_parts():
                dest.write_part_bytes(part, template_pkg.read_part_bytes(part))

        # Find content after SDT/TOC block in template
        start_index = 0
        for idx, child in enumerate(source_body):
            if child.tag == w_tag("sdt"):
                start_index = idx + 1
                break

        elements = [clone_element(el) for el in list(source_body)[start_index:]]
        source_numbering = (
            template_pkg.get_xml(NUMBERING_XML)
            if NUMBERING_XML in template_pkg.list_parts()
            else None
        )
        dest_numbering = numbering.ensure_numbering_part(dest)
        numbering.remap_numbering_in_elements(elements, source_numbering, dest_numbering)
        numbering.strip_foreign_numbering_from_non_lists(elements)
        dest.set_xml(NUMBERING_XML, dest_numbering)

        for el in elements:
            dest_body.append(el)

        dest.set_xml(DOCUMENT_XML, dest.document)
        dest.save()
        return output
