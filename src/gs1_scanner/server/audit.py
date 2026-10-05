"""Audit log: recorded in the same transaction as the change it describes."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gs1_scanner.server.db import AuditEntry, User


def _jsonable(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    return {f: _jsonable(getattr(obj, f)) for f in fields}


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[Any]]:
    """{"field": [old, new]} for the fields that changed."""
    return {k: [before.get(k), v] for k, v in after.items() if before.get(k) != v}


def record(
    db: Session,
    user: User | None,
    action: str,
    summary: str,
    *,
    entity: Any = None,
    details: dict[str, Any] | None = None,
    username: str | None = None,
) -> AuditEntry:
    entry = AuditEntry(
        user=user,
        username=username if username is not None else (user.username if user else ""),
        action=action,
        entity_type=type(entity).__name__.lower() if entity is not None else None,
        entity_id=getattr(entity, "id", None),
        summary=summary[:500],
        details=details or {},
    )
    db.add(entry)
    return entry


def recent_login_failures(db: Session, username: str, window_seconds: int) -> int:
    """Failed logins for ``username`` since its last successful login, within the window.

    Kept in the database, so the limit holds across server processes and restarts.
    """
    since = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    last_success = db.scalar(
        select(func.max(AuditEntry.created_at)).where(
            AuditEntry.action == "auth.login", AuditEntry.username == username
        )
    )
    if last_success is not None:
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=timezone.utc)
        since = max(since, last_success)
    return (
        db.scalar(
            select(func.count()).where(
                AuditEntry.action == "auth.login_failed",
                AuditEntry.username == username,
                AuditEntry.created_at > since,
            )
        )
        or 0
    )
