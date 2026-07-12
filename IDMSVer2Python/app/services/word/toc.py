"""TOC field update and table-of-contents utilities."""

from __future__ import annotations

from lxml import etree

from app.core.namespaces import NSMAP, w_tag
from app.services.word.document_package import DOCUMENT_XML, DocxPackage


def mark_toc_fields_dirty(pkg: DocxPackage) -> bool:
    """Mark TOC fields as dirty so Word refreshes them on open."""
    body = pkg.body
    changed = False
    for fld_char in body.iter(w_tag("fldChar")):
        dirty = fld_char.get(w_tag("dirty"))
        fld_type = fld_char.get(w_tag("fldCharType"))
        if fld_type == "begin" and dirty != "true":
            fld_char.set(w_tag("dirty"), "true")
            changed = True

    for instr in body.iter(w_tag("instrText")):
        if instr.text and "TOC" in instr.text.upper():
            parent_run = instr.getparent()
            if parent_run is not None:
                grand = parent_run.getparent()
                if grand is not None:
                    for sibling in grand.iter(w_tag("fldChar")):
                        if sibling.get(w_tag("fldCharType")) == "begin":
                            sibling.set(w_tag("dirty"), "true")
                            changed = True

    if changed:
        pkg.set_xml(DOCUMENT_XML, pkg.document)
    return changed


def update_toc(pkg: DocxPackage) -> bool:
    """Best-effort TOC refresh without Word COM — marks fields dirty."""
    return mark_toc_fields_dirty(pkg)
