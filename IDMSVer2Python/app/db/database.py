"""SQLAlchemy database session — only used when audit/payload logging is enabled."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class AuditTrail(Base):
    __tablename__ = "AuditTrail"

    audit_trail_id: Mapped[int] = mapped_column("AuditTrailId", Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column("UserId", Integer)
    audit_trail_text: Mapped[str | None] = mapped_column("AuditTrailText", String, nullable=True)
    created_on: Mapped[datetime | None] = mapped_column("CreatedOn", DateTime, nullable=True)


class Payload(Base):
    __tablename__ = "Payloads"

    payload_id: Mapped[int] = mapped_column("PayloadId", Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column("ProjectName", String)
    endpoint_name: Mapped[str] = mapped_column("EndpointName", String)
    payload_text: Mapped[str] = mapped_column("PayloadText", Text)
    created_on: Mapped[datetime] = mapped_column("CreatedOn", DateTime)
    created_by: Mapped[str] = mapped_column("CreatedBy", String)


_settings = get_settings()
_engine = None
_SessionLocal = None

if _settings.audit_enabled or _settings.payload_logging_enabled:
    _engine = create_engine(_settings.database_url, pool_pre_ping=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def get_db():
    if _SessionLocal is None:
        yield None
        return
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
