"""Reconcile paragraph/character/table style references in merged content.

When content is copied from a source document into a destination, its style
references (``w:pStyle`` / ``w:rStyle`` / ``w:tblStyle``) point at the *source*
document's style ids. Those ids frequently don't exist in the destination —
Word stores styles under opaque ids (e.g. ``aff`` for "List Paragraph"), so the
copied paragraphs silently fall back to *Normal* and lose their intended look.

This module rewrites those references to the destination's own style ids by
matching on the style **name**, and copies any source style that has no
destination equivalent (with its ``basedOn`` / ``link`` / ``next`` dependency
chain) into the destination's ``styles.xml``.

Heading styles are intentionally skipped here: the merge re-levels headings
separately (a source ``Heading 1`` may become a destination ``Heading 2``
depending on the drop location), which name-matching must not undo.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Iterable

from lxml import etree

from app.core.namespaces import NSMAP, w_tag
from app.services.word.document_package import STYLES_XML, DocxPackage

_REF_TAGS = (w_tag("pStyle"), w_tag("rStyle"), w_tag("tblStyle"))
_DEP_TAGS = ("basedOn", "link", "next")


def _style_index(styles_root: etree._Element):
    """Return (styleId -> element, lowercased-name -> styleId, styleId -> name)."""
    by_id: dict[str, etree._Element] = {}
    name_to_id: dict[str, str] = {}
    name_by_id: dict[str, str] = {}
    for style in styles_root.findall("w:style", NSMAP):
        sid = style.get(w_tag("styleId"))
        if not sid:
            continue
        by_id[sid] = style
        name_el = style.find("w:name", NSMAP)
        name = (name_el.get(w_tag("val")) or "").strip().lower() if name_el is not None else ""
        name_by_id[sid] = name
        if name and name not in name_to_id:
            name_to_id[name] = sid
    return by_id, name_to_id, name_by_id


def reconcile_content_styles(
    elements: Iterable[etree._Element],
    source_pkg: DocxPackage,
    dest_pkg: DocxPackage,
    skip_ids: set[str] | None = None,
) -> dict[str, str]:
    """Remap style references in `elements` to destination styles by name.

    Any source style with no same-named destination style is copied into the
    destination (with a non-colliding id and its dependency chain). References
    whose id is in `skip_ids` (e.g. heading styles handled elsewhere) are left
    untouched. Returns the ``{source_id: dest_id}`` remap that was applied.
    """
    skip_ids = skip_ids or set()
    if STYLES_XML not in source_pkg.list_parts() or STYLES_XML not in dest_pkg.list_parts():
        return {}

    src_root = source_pkg.get_xml(STYLES_XML)
    dest_root = dest_pkg.get_xml(STYLES_XML)
    src_by_id, _src_name_to_id, src_name_by_id = _style_index(src_root)
    _dest_by_id, dest_name_to_id, _dest_name_by_id = _style_index(dest_root)
    dest_ids = set(_dest_by_id)

    remap: dict[str, str] = {}
    added: list[etree._Element] = []

    def ensure(src_id: str) -> str:
        if src_id in remap:
            return remap[src_id]
        if src_id not in src_by_id:
            remap[src_id] = src_id  # not a style we can resolve — leave as-is
            return src_id
        name = src_name_by_id.get(src_id, "")
        if name and name in dest_name_to_id:
            remap[src_id] = dest_name_to_id[name]
            return remap[src_id]
        # No destination style with this name → copy the source style in.
        final_id = src_id
        if final_id in dest_ids:
            n = 1
            while f"{src_id}-{n}" in dest_ids:
                n += 1
            final_id = f"{src_id}-{n}"
        remap[src_id] = final_id
        dest_ids.add(final_id)
        if name:
            dest_name_to_id[name] = final_id
        clone = deepcopy(src_by_id[src_id])
        clone.set(w_tag("styleId"), final_id)
        for dep in _DEP_TAGS:
            dep_el = clone.find(f"w:{dep}", NSMAP)
            if dep_el is not None and dep_el.get(w_tag("val")):
                dep_el.set(w_tag("val"), ensure(dep_el.get(w_tag("val"))))
        added.append(clone)
        return final_id

    ref_els = [ref for el in elements for ref in el.iter(*_REF_TAGS)]
    for ref in ref_els:
        val = ref.get(w_tag("val"))
        if val and val not in skip_ids:
            ensure(val)
    for ref in ref_els:
        val = ref.get(w_tag("val"))
        if val and val not in skip_ids and remap.get(val, val) != val:
            ref.set(w_tag("val"), remap[val])

    for clone in added:
        dest_root.append(clone)
    if added:
        dest_pkg.set_xml(STYLES_XML, dest_root)
    return remap
