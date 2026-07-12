"""FastAPI dependency injection helpers."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.database import get_db
from app.services.audit_service import AuditService, PayloadService
from app.services.word.coversheet import CoversheetService
from app.services.word.fields import FieldsService
from app.services.word.image import ImageService
from app.services.word.inserted_text import InsertedTextService
from app.services.word.merge import MergeService
from app.services.word.paragraph import ParagraphService
from app.services.word.section import SectionService
from app.services.word.replace_document import ReplaceDocumentService


def get_merge_service(settings: Annotated[Settings, Depends(get_settings)]) -> MergeService:
    return MergeService(settings)


def get_paragraph_service(settings: Annotated[Settings, Depends(get_settings)]) -> ParagraphService:
    return ParagraphService(settings)


def get_section_service(settings: Annotated[Settings, Depends(get_settings)]) -> SectionService:
    return SectionService(settings)


def get_image_service(settings: Annotated[Settings, Depends(get_settings)]) -> ImageService:
    return ImageService(settings)


def get_coversheet_service() -> CoversheetService:
    return CoversheetService()


def get_fields_service() -> FieldsService:
    return FieldsService()


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


def get_optional_user_id(request: Request) -> int:
    """JWT stub — returns user id 1 until full auth is implemented."""
    return int(request.headers.get("X-User-Id", "1"))


def extract_project_name(document_path: str) -> str:
    marker = "ProjectDocs\\"
    idx = document_path.find(marker)
    if idx == -1:
        marker = "ProjectDocs/"
        idx = document_path.find(marker)
    if idx == -1:
        return ""
    start = idx + len(marker)
    end = document_path.find("\\", start)
    if end == -1:
        end = document_path.find("/", start)
    if end == -1:
        return document_path[start:]
    return document_path[start:end]
