"""Database models and engine setup."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16))  # "admin" or "operator"
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    # SHA-256 of the session token; the token itself only exists in the cookie.
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    gtin: Mapped[str | None] = mapped_column(String(14), unique=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # What is printed on the shelf label and scanned, e.g. "W1-A03-P02-S1".
    code: Mapped[str] = mapped_column(String(64), unique=True)
    warehouse: Mapped[str] = mapped_column(String(64), default="")
    aisle: Mapped[str] = mapped_column(String(64), default="")
    position: Mapped[str] = mapped_column(String(64), default="")
    shelf: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(String(256), default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), index=True)

    # Set by the device that made the scan, so a retried upload (e.g. from the
    # offline queue) is recognised instead of saved twice.
    client_ref: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    # What the scan did to stock: "receive", "pick", "move" or "log" (nothing).
    action: Mapped[str] = mapped_column(String(16), default="receive", server_default="receive")
    raw_barcode: Mapped[str] = mapped_column(Text)
    gs1_hri: Mapped[str] = mapped_column(Text)
    elements: Mapped[dict[str, Any]] = mapped_column(JSON)  # AI -> value, scan order
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Frequently used AIs, copied out of `elements` for search and export.
    sku: Mapped[str | None] = mapped_column(String(64), index=True)
    gtin: Mapped[str | None] = mapped_column(String(14), index=True)  # AI 01, else 02
    sscc: Mapped[str | None] = mapped_column(String(18), index=True)
    lot: Mapped[str | None] = mapped_column(String(20), index=True)
    serial: Mapped[str | None] = mapped_column(String(20))
    quantity: Mapped[int | None] = mapped_column(Integer)
    production_date: Mapped[date | None] = mapped_column(Date)
    best_before: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(500), default="")

    user: Mapped[User | None] = relationship()
    location: Mapped[Location | None] = relationship()
    product: Mapped[Product | None] = relationship()
    # Undoing or deleting a scan also undoes its effect on stock.
    movements: Mapped[list[Movement]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", order_by="Movement.id"
    )


class Movement(Base):
    """One signed change to stock at one location.

    Current stock is the sum of movements per location + item, where an item is
    GTIN + lot + expiry date + SSCC (the pallet). A move is two rows: minus at
    the source, plus at the destination.
    """

    __tablename__ = "movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # receive, pick, move, adjust
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), index=True)
    gtin: Mapped[str] = mapped_column(String(14), index=True)
    lot: Mapped[str | None] = mapped_column(String(20))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    sscc: Mapped[str | None] = mapped_column(String(18), index=True)
    quantity: Mapped[int] = mapped_column(Integer)  # positive in, negative out
    note: Mapped[str] = mapped_column(String(500), default="")

    user: Mapped[User | None] = relationship()
    location: Mapped[Location | None] = relationship()
    scan: Mapped[Scan | None] = relationship(back_populates="movements")


class StockCount(Base):
    """A physical count of one location, compared with the system's stock."""

    __tablename__ = "stock_counts"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open, applied, cancelled
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    user: Mapped[User | None] = relationship(foreign_keys=[user_id])
    closed_by: Mapped[User | None] = relationship(foreign_keys=[closed_by_id])
    location: Mapped[Location] = relationship()
    lines: Mapped[list[CountLine]] = relationship(
        back_populates="count", cascade="all, delete-orphan", order_by="CountLine.id"
    )


class CountLine(Base):
    """How many of one item were counted (scanning the same item again adds to it)."""

    __tablename__ = "count_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    count_id: Mapped[int] = mapped_column(
        ForeignKey("stock_counts.id", ondelete="CASCADE"), index=True
    )
    gtin: Mapped[str] = mapped_column(String(14))
    lot: Mapped[str | None] = mapped_column(String(20))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    sscc: Mapped[str | None] = mapped_column(String(18))
    quantity: Mapped[int] = mapped_column(Integer)
    # The system's quantity when the count was applied (None while open).
    expected: Mapped[int | None] = mapped_column(Integer)

    count: Mapped[StockCount] = relationship(back_populates="lines")


class AuditEntry(Base):
    """Who changed what, for everything that isn't already a scan or movement."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    # Kept as text too: failed logins have no user, and it reads well in exports.
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(32), index=True)  # e.g. "product.update"
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(String(500), default="")
    # What changed, as {"field": [old, new]}, or other details.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    user: Mapped[User | None] = relationship()


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    if url.get_backend_name() == "sqlite":
        event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA journal_mode = WAL")  # readers don't block the scanner writing
    cur.close()


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(engine, expire_on_commit=False)
