"""Low-level DOCX package read/write using ZIP + lxml."""

from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

from lxml import etree

from app.core.exceptions import DocumentNotFoundError
from app.core.namespaces import NSMAP, W_NS, w_tag

ET.register_namespace("w", W_NS)
CONTENT_TYPES = "[Content_Types].xml"
RELS_ROOT = "_rels/.rels"
DOC_RELS = "word/_rels/document.xml.rels"
DOCUMENT_XML = "word/document.xml"
NUMBERING_XML = "word/numbering.xml"
STYLES_XML = "word/styles.xml"
SETTINGS_XML = "word/settings.xml"


class DocxPackage:
    """Mutable view of a .docx file for OOXML manipulation."""

    def __init__(self, path: str, *, writable: bool = True):
        self.path = os.path.normpath(path)
        if not os.path.isfile(self.path):
            raise DocumentNotFoundError(f"Document not found: {self.path}")
        self.writable = writable
        self._tmpdir: tempfile.TemporaryDirectory | None = None
        self._work_path = self.path
        self._parts: dict[str, bytes] = {}
        self._xml_cache: dict[str, etree._Element] = {}
        self._dirty_parts: set[str] = set()
        self._load()

    def _load(self) -> None:
        with zipfile.ZipFile(self.path, "r") as zf:
            for name in zf.namelist():
                self._parts[name] = zf.read(name)

    @contextmanager
    def edit_copy(self, destination: str | None = None) -> Iterator["DocxPackage"]:
        """Open a writable working copy and persist changes.

        By default the edits are saved back over the original path. Pass
        ``destination`` to write the result to a different file instead; the
        original is then left completely untouched (used for "save as a copy").
        """
        original = self.path
        target = os.path.normpath(destination) if destination else original
        tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        tmp.close()
        shutil.copy2(original, tmp.name)
        pkg = DocxPackage(tmp.name, writable=True)
        try:
            yield pkg
            pkg.save(destination=target)
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def get_xml(self, part: str) -> etree._Element:
        """Return the parsed XML tree for a part.

        The parsed tree is cached, so repeated access returns the *same*
        mutable element. In-place edits made through this element are retained
        and serialized back on ``save()`` — callers do not need to re-assign
        via ``set_xml`` for their changes to persist.
        """
        if part in self._xml_cache:
            return self._xml_cache[part]
        data = self._parts.get(part)
        if data is None:
            raise FileNotFoundError(f"Part not found in package: {part}")
        root = etree.fromstring(data)
        self._xml_cache[part] = root
        return root

    def set_xml(self, part: str, root: etree._Element) -> None:
        self._xml_cache[part] = root
        self._parts[part] = etree.tostring(
            root, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        self._dirty_parts.add(part)

    def get_or_create_part(self, part: str, root_tag: str) -> etree._Element:
        if part not in self._parts and part not in self._xml_cache:
            root = etree.Element(root_tag, nsmap={"w": W_NS})
            self.set_xml(part, root)
        return self.get_xml(part)

    @property
    def document(self) -> etree._Element:
        return self.get_xml(DOCUMENT_XML)

    @property
    def body(self) -> etree._Element:
        body = self.document.find("w:body", NSMAP)
        if body is None:
            raise DocumentNotFoundError("Document body is missing.")
        return body

    def _flush_xml_cache(self) -> None:
        """Serialize every cached XML tree back into the raw part bytes.

        Called before writing the package so that in-place edits to trees
        returned by :meth:`get_xml` / :attr:`document` / :attr:`body` are
        captured even when the caller never went through :meth:`set_xml`.
        """
        for part, root in self._xml_cache.items():
            self._parts[part] = etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )

    def save(self, destination: str | None = None) -> str:
        self._flush_xml_cache()
        target = destination or self.path
        os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in self._parts.items():
                zf.writestr(name, data)
        with open(target, "wb") as fh:
            fh.write(buffer.getvalue())
        return target

    def clone_to(self, destination: str) -> "DocxPackage":
        os.makedirs(os.path.dirname(os.path.abspath(destination)) or ".", exist_ok=True)
        shutil.copy2(self.path, destination)
        return DocxPackage(destination, writable=True)

    def list_parts(self) -> list[str]:
        return sorted(self._parts.keys())

    def read_part_bytes(self, part: str) -> bytes:
        if part in self._xml_cache:
            return etree.tostring(
                self._xml_cache[part], xml_declaration=True, encoding="UTF-8", standalone=True
            )
        return self._parts[part]

    def write_part_bytes(self, part: str, data: bytes) -> None:
        self._parts[part] = data
        # A raw byte write supersedes any cached parse of the same part.
        self._xml_cache.pop(part, None)
        self._dirty_parts.add(part)

    def add_media_part(self, ext: str, data: bytes) -> tuple[str, str]:
        """Add image bytes to word/media and return (part_path, relationship_id)."""
        media_dir = "word/media"
        existing = [n for n in self._parts if n.startswith(f"{media_dir}/image")]
        idx = len(existing) + 1
        part_path = f"{media_dir}/image{idx}.{ext.lstrip('.')}"
        self.write_part_bytes(part_path, data)

        rels_root = self.get_xml(DOC_RELS)
        rel_ids = [
            rel.get("Id", "")
            for rel in rels_root.findall("rel:Relationship", {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"})
        ]
        next_id = _next_rel_id(rel_ids)
        rel_type = _image_rel_type(ext)
        rel = etree.SubElement(
            rels_root,
            "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship",
            Id=next_id,
            Type=rel_type,
            Target=f"media/image{idx}.{ext.lstrip('.')}",
        )
        self.set_xml(DOC_RELS, rels_root)
        return part_path, next_id


def _next_rel_id(existing: list[str]) -> str:
    nums = [int(m.group(1)) for e in existing if (m := re.match(r"rId(\d+)", e))]
    return f"rId{(max(nums) if nums else 0) + 1}"


def _image_rel_type(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    mapping = {
        "png": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
        "jpg": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
        "jpeg": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
        "gif": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
        "bmp": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
    }
    return mapping.get(ext, mapping["png"])


def clone_element(element: etree._Element) -> etree._Element:
    return deepcopy(element)
