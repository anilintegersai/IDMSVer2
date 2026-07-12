"""Audit trail and payload logging services (Phase 2 — disabled by default)."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.database import AuditTrail, Payload


class AuditService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def create(self, db: Session | None, user_id: int, text: str) -> int:
        if not self.settings.audit_enabled or db is None:
            return 0
        row = AuditTrail(
            user_id=user_id,
            audit_trail_text=text,
            created_on=datetime.now(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.audit_trail_id


class PayloadService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def create(
        self,
        db: Session | None,
        project_name: str,
        endpoint_name: str,
        payload: object,
        created_by: str,
    ) -> int:
        if not self.settings.payload_logging_enabled or db is None:
            return 0
        row = Payload(
            project_name=project_name or "",
            endpoint_name=endpoint_name,
            payload_text=json.dumps(payload, default=str),
            created_on=datetime.now(),
            created_by=created_by,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.payload_id
