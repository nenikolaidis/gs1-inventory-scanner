from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select

from gs1_scanner.server import audit
from gs1_scanner.server.db import AuthSession, User
from gs1_scanner.server.deps import DB, AdminUser
from gs1_scanner.server.routes.auth import check_password_strength, normalize_username
from gs1_scanner.server.schemas import UserCreate, UserOut, UserUpdate
from gs1_scanner.server.security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])

USER_FIELDS = ["username", "display_name", "role", "is_active"]


@router.get("", response_model=list[UserOut])
def list_users(_admin: AdminUser, db: DB) -> list[User]:
    return list(db.scalars(select(User).order_by(User.username)))


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, admin: AdminUser, db: DB) -> User:
    username = normalize_username(body.username)
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"User {username!r} already exists.")
    check_password_strength(body.password)
    user = User(
        username=username,
        display_name=body.display_name.strip() or username,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        admin,
        "user.create",
        f"Created {user.role} {username}",
        entity=user,
        details=audit.snapshot(user, USER_FIELDS),
    )
    db.commit()
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, admin: AdminUser, db: DB) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if user.id == admin.id and (body.is_active is False or body.role == "operator"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You can't deactivate or demote your own account."
        )
    before = audit.snapshot(user, USER_FIELDS)
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or user.username
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password is not None:
        check_password_strength(body.password)
        user.password_hash = hash_password(body.password)
    if body.is_active is False or body.password is not None:
        db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    changes = audit.diff(before, audit.snapshot(user, USER_FIELDS))
    if body.password is not None:
        changes["password"] = ["(hidden)", "(changed)"]
    if changes:
        audit.record(
            db,
            admin,
            "user.update",
            f"Changed user {user.username}: {', '.join(changes)}",
            entity=user,
            details=changes,
        )
    db.commit()
    return user
