"""Placeholder discovery in Word documents."""

from __future__ import annotations

import re

from app.services.word.document_package import DocxPackage
from app.core.namespaces import w_tag

PLACEHOLDER_PATTERN = re.compile(r"<[A-Za-z0-9_#]+>")


def find_placeholders(document_path: str) -> list[str]:
    pkg = DocxPackage(document_path, writable=False)
    found: set[str] = set()
    for part in pkg.list_parts():
        if not part.endswith(".xml"):
            continue
        try:
            root = pkg.get_xml(part)
        except Exception:
            continue
        for node in root.iter(w_tag("t")):
            if node.text:
                found.update(PLACEHOLDER_PATTERN.findall(node.text))
    return sorted(found)
