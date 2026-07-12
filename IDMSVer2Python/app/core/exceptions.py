"""Domain-specific exceptions for document processing."""


class DocumentProcessingError(Exception):
    """Raised when a document operation fails."""

    def __init__(self, message: str, *, details: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class BookmarkNotFoundError(DocumentProcessingError):
    """Raised when a required bookmark is missing from a document."""


class DocumentNotFoundError(DocumentProcessingError):
    """Raised when a document file path does not exist."""
