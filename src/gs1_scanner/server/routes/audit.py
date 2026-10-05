from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from gs1_scanner.server.db import AuditEntry
from gs1_scanner.server.deps import DB, AdminUser
from gs1_scanner.server.schemas import AuditOut, Page

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/audit", response_model=Page[AuditOut])
def list_audit(
    _admin: AdminUser,
    db: DB,
    q: Annotated[str | None, Query(max_length=200)] = None,
    action: Annotated[
        str | None, Query(max_length=32, description="e.g. 'product' or 'auth.login'")
    ] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AuditOut]:
    """The audit log, newest first. ``action`` matches exactly or as a prefix ("product")."""
    stmt = select(AuditEntry)
    if q and q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(
            or_(
                AuditEntry.summary.ilike(like, escape="\\"),
                AuditEntry.username.ilike(like, escape="\\"),
            )
        )
    if action:
        stmt = stmt.where(
            or_(AuditEntry.action == action, AuditEntry.action.startswith(action + "."))
        )
    if date_from is not None:
        stmt = stmt.where(
            AuditEntry.created_at >= datetime.combine(date_from, time(), timezone.utc)
        )
    if date_to is not None:
        end = datetime.combine(date_to + timedelta(days=1), time(), timezone.utc)
        stmt = stmt.where(AuditEntry.created_at < end)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    entries = db.scalars(stmt.order_by(AuditEntry.id.desc()).limit(limit).offset(offset))
    return Page(items=[AuditOut.model_validate(e) for e in entries], total=total)
