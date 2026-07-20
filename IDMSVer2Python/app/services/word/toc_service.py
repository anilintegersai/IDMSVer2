"""TOC extraction service for reading document table of contents."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.services.word import bookmarks
from app.services.word.document_package import DocxPackage


@dataclass
class TocEntry:
    """Represents a single TOC entry."""
    sl_no: int
    item_text: str
    page_ref: str
    page_no: str
    section_number: str
    level: int


@dataclass
class GetTocRequest:
    """Request to get TOC from a document."""
    document_path: str


@dataclass
class GetTocResult:
    """Result containing TOC entries."""
    entries: list[TocEntry]


class TocService:
    """Service for extracting TOC from Word documents."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def get_toc(self, request: GetTocRequest) -> GetTocResult:
        """Extract TOC entries from a Word document."""
        pkg = DocxPackage(request.document_path, writable=False)
        toc_entries = bookmarks.get_toc_flat(pkg)

        entries: list[TocEntry] = []
        for entry in toc_entries:
            toc_entry = TocEntry(
                sl_no=entry.get("order", 0) + 1,
                item_text=entry.get("text", ""),
                page_ref=entry.get("bookmark", ""),
                page_no=entry.get("page_no", ""),
                section_number=entry.get("section_number", ""),
                level=entry.get("level", 1)
            )
            entries.append(toc_entry)

        return GetTocResult(entries=entries)
