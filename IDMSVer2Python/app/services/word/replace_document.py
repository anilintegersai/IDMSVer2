"""Compare uploaded document with existing file and replace if tables match."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass

from lxml import etree

from app.core.namespaces import w_tag
from app.services.word.document_package import DocxPackage


@dataclass
class TableIdentifierRule:
    row: int
    col: int
    value: str


def _find_table_by_rules(document_path: str, rules: list[TableIdentifierRule]):
    pkg = DocxPackage(document_path, writable=False)
    for table in pkg.body.findall("w:tbl", {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}):
        rows = table.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr")
        match = True
        for rule in rules:
            if rule.row <= 0 or rule.row > len(rows):
                match = False
                break
            cells = rows[rule.row - 1].findall(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc"
            )
            if rule.col <= 0 or rule.col > len(cells):
                match = False
                break
            cell_text = "".join(
                t.text or ""
                for t in cells[rule.col - 1].iter(
                    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
                )
            ).strip()
            if rule.value.lower() not in cell_text.lower():
                match = False
                break
        if match:
            return table
    return None


def _table_signature(table: etree._Element) -> list[str]:
    cells = []
    for cell in table.iter(w_tag("tc")):
        text = "".join(t.text or "" for t in cell.iter(w_tag("t"))).strip()
        cells.append(text)
    return cells


class ReplaceDocumentService:
    def compare_and_replace(
        self,
        new_document_bytes: bytes,
        old_document_path: str,
        rules: list[TableIdentifierRule],
    ) -> bool:
        if not os.path.isfile(old_document_path):
            return False

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(new_document_bytes)
            tmp_path = tmp.name

        try:
            old_table = _find_table_by_rules(old_document_path, rules)
            new_table = _find_table_by_rules(tmp_path, rules)
            if old_table is None or new_table is None:
                return False
            if _table_signature(old_table) != _table_signature(new_table):
                return False
            shutil.copy2(tmp_path, old_document_path)
            return True
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
