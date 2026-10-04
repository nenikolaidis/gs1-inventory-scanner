from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select

from gs1_scanner.server.db import AuthSession, User
from gs1_scanner.server.deps import DB, SESSION_COOKIE, AppSettings, CurrentUser
from gs1_scanner.server.schemas import LoginIn, PasswordChangeIn, SetupIn, UserOut
from gs1_scanner.server.security import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    hash_token,
    new_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Simple in-memory brute-force protection: per username, at most
# MAX_FAILURES failed logins within FAILURE_WINDOW seconds.
MAX_FAILURES = 10
FAILURE_WINDOW = 300


def check_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            422,
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )


def normalize_username(username: str) -> str:
    return username.strip().lower()


def _start_session(db: DB, settings: AppSettings, response: Response, user: User) -> None:
    token = new_session_token()
    max_age = settings.session_days * 24 * 3600
    db.add(
        AuthSession(
            token_hash=hash_token(token),
            user=user,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=max_age),
        )
    )
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
    )


@router.get("/setup")
def setup_status(db: DB) -> dict[str, bool]:
    """Whether the first admin account still has to be created."""
    return {"needs_setup": db.scalar(select(func.count()).select_from(User)) == 0}


@router.post("/setup", response_model=UserOut)
def setup(body: SetupIn, db: DB, settings: AppSettings, response: Response) -> User:
    """Create the first admin account. Only allowed while there are no users."""
    if db.scalar(select(func.count()).select_from(User)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup has already been done.")
    check_password_strength(body.password)
    username = normalize_username(body.username)
    user = User(
        username=username,
        display_name=body.display_name.strip() or username,
        password_hash=hash_password(body.password),
        role="admin",
    )
    db.add(user)
    _start_session(db, settings, response, user)
    return user


@router.post("/login", response_model=UserOut)
def login(
    body: LoginIn, request: Request, db: DB, settings: AppSettings, response: Response
) -> User:
    username = normalize_username(body.username)
    state = request.app.state
    if not hasattr(state, "login_failures"):
        state.login_failures = defaultdict(deque)
    failures: deque[float] = state.login_failures[username]
    now = time.monotonic()
    while failures and failures[0] < now - FAILURE_WINDOW:
        failures.popleft()
    if len(failures) >= MAX_FAILURES:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins. Try again in a few minutes."
        )

    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        failures.append(now)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password.")
    failures.clear()
    _start_session(db, settings, response, user)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: DB, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordChangeIn, user: CurrentUser, db: DB, request: Request) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong.")
    check_password_strength(body.new_password)
    user.password_hash = hash_password(body.new_password)
    # Log out everywhere else.
    current = hash_token(request.cookies.get(SESSION_COOKIE, ""))
    db.execute(
        delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.token_hash != current)
    )
    db.commit()
