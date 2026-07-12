"""Caption/field update utilities."""

from __future__ import annotations

from app.core.namespaces import w_tag
from app.services.word.document_package import DOCUMENT_XML, DocxPackage


class FieldsService:
    def update_captions(self, document_path: str) -> bool:
        """Mark SEQ and other fields dirty so Word recalculates captions on open."""
        with DocxPackage(document_path).edit_copy() as pkg:
            changed = False
            for fld in pkg.body.iter(w_tag("fldChar")):
                if fld.get(w_tag("fldCharType")) == "begin":
                    fld.set(w_tag("dirty"), "true")
                    changed = True
            if changed:
                pkg.set_xml(DOCUMENT_XML, pkg.document)
        return changed
