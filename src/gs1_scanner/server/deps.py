"""FastAPI dependencies: database session, current user, settings."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from gs1_scanner.server.config import Settings
from gs1_scanner.server.db import AuthSession, User
from gs1_scanner.server.security import hash_token

SESSION_COOKIE = "gs1_session"


def as_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; everything stored is UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as db:
        yield db


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def current_user(request: Request, db: DB) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth = db.get(AuthSession, hash_token(token))
        if auth is not None:
            if as_utc(auth.expires_at) > datetime.now(timezone.utc) and auth.user.is_active:
                return auth.user
            db.delete(auth)
            db.commit()
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in.")


CurrentUser = Annotated[User, Depends(current_user)]


def admin_user(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only.")
    return user


AdminUser = Annotated[User, Depends(admin_user)]
