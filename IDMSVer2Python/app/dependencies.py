"""FastAPI dependency injection helpers."""

from typing import Annotated

import logging
from fastapi import Depends, Request, HTTPException, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.auth import get_current_user_optional
from app.db.database import get_db
from app.services.audit_service import AuditService, PayloadService
from app.services.word.content import ContentService
from app.services.word.coversheet import CoversheetService
from app.services.word.edit_content import EditContentService
from app.services.word.fields import FieldsService
from app.services.word.image import ImageService
from app.services.word.inserted_text import InsertedTextService
from app.services.word.merge import MergeService
from app.services.word.paragraph import ParagraphService
from app.services.word.section import SectionService
from app.services.word.replace_document import ReplaceDocumentService

logger = logging.getLogger(__name__)


def get_merge_service(settings: Annotated[Settings, Depends(get_settings)]) -> MergeService:
    return MergeService(settings)


def get_paragraph_service(settings: Annotated[Settings, Depends(get_settings)]) -> ParagraphService:
    return ParagraphService(settings)


def get_section_service(settings: Annotated[Settings, Depends(get_settings)]) -> SectionService:
    return SectionService(settings)


def get_content_service(settings: Annotated[Settings, Depends(get_settings)]) -> ContentService:
    return ContentService(settings)


def get_image_service(settings: Annotated[Settings, Depends(get_settings)]) -> ImageService:
    return ImageService(settings)


def get_coversheet_service() -> CoversheetService:
    return CoversheetService()


def get_fields_service() -> FieldsService:
    return FieldsService()


def get_edit_content_service(settings: Annotated[Settings, Depends(get_settings)]) -> EditContentService:
    return EditContentService(settings)


def get_inserted_text_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> InsertedTextService:
    return InsertedTextService(settings)


def get_replace_service() -> ReplaceDocumentService:
    return ReplaceDocumentService()


def get_audit_service(settings: Annotated[Settings, Depends(get_settings)]) -> AuditService:
    return AuditService(settings)


def get_payload_service(settings: Annotated[Settings, Depends(get_settings)]) -> PayloadService:
    return PayloadService(settings)


def get_optional_user_id(
    request: Request,
    user_id: int | None = Depends(get_current_user_optional),
    settings: Settings = Depends(get_settings),
) -> int:
    """Resolve the current user id.

    - When JWT is enabled: return the user id from the token (or 401 if absent).
    - When JWT is disabled and debug=True: allow X-User-Id header for local testing.
    - Otherwise fall back to user id 1 (legacy behavior) but emit a warning.
    """
    if settings.jwt_enabled:
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization required")
        return user_id

    # JWT disabled
    if settings.debug:
        try:
            return int(request.headers.get("X-User-Id", "1"))
        except ValueError:
            logger.warning("Invalid X-User-Id header; defaulting to 1")
            return 1

    # Legacy default: return 1 but warn — prefer enabling JWT for production
    logger.warning("JWT disabled and debug=False: defaulting to user id 1")
    return 1


def extract_project_name(document_path: str) -> str:
    marker = "ProjectDocs\\\\"
    idx = document_path.find(marker)
    if idx == -1:
        marker = "ProjectDocs/"
        idx = document_path.find(marker)
    if idx == -1:
        return ""
    start = idx + len(marker)
    end = document_path.find("\\\\", start)
    if end == -1:
        end = document_path.find("/", start)
    if end == -1:
        return document_path[start:]
    return document_path[start:end]


def validate_document_path(path: str, settings: Settings) -> str:
    """Normalize and ensure the provided path is inside allowed folders.

    Raises HTTPException(403) when the path is outside configured roots.
    Returns the normalized absolute path when valid.
    """
    import os
    from fastapi import HTTPException

    norm = os.path.normpath(path)
    allowed_roots = [
        os.path.normpath(settings.template_source_base_path),
        os.path.normpath(settings.merged_base_path),
    ]
    if not any(norm.lower().startswith(root.lower()) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders.")
    return norm