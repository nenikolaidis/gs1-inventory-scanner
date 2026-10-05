from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from gs1_scanner.server import audit, stock
from gs1_scanner.server.db import Location, Movement, Product
from gs1_scanner.server.deps import DB, AdminUser, AppSettings, CurrentUser
from gs1_scanner.server.routes.scans import _csv_safe
from gs1_scanner.server.scanning import ScanError
from gs1_scanner.server.schemas import (
    AdjustIn,
    LocationOut,
    MovementOut,
    Page,
    ProductOut,
    StockRowOut,
)

router = APIRouter(prefix="/api", tags=["stock"])

QueryText = Annotated[str | None, Query(max_length=200)]


def _stock(
    db: DB,
    q: str | None,
    location_id: int | None,
    unassigned: bool,
    gtin: str | None,
    sscc: str | None,
    expires_within_days: int | None,
) -> list[StockRowOut]:
    expires_before = (
        date.today() + timedelta(days=expires_within_days + 1)
        if expires_within_days is not None
        else None
    )
    rows = stock.stock_rows(
        db,
        q=q,
        location_id=location_id,
        unassigned=unassigned,
        gtin=gtin,
        sscc=sscc,
        expires_before=expires_before,
    )
    locations = {
        loc.id: loc
        for loc in db.scalars(
            select(Location).where(Location.id.in_({r.location_id for r in rows if r.location_id}))
        )
    }
    products = {
        p.gtin: p
        for p in db.scalars(select(Product).where(Product.gtin.in_({r.gtin for r in rows})))
    }
    out = [
        StockRowOut(
            location=LocationOut.model_validate(locations[r.location_id])
            if r.location_id in locations
            else None,
            gtin=r.gtin,
            product=ProductOut.model_validate(products[r.gtin]) if r.gtin in products else None,
            lot=r.lot,
            expiry_date=r.expiry_date,
            sscc=r.sscc,
            quantity=r.quantity,
            last_movement_at=r.last_movement_at,
        )
        for r in rows
    ]
    out.sort(
        key=lambda r: (
            r.location.code if r.location else "",
            r.product.sku if r.product else r.gtin,
            r.expiry_date or date.max,
            r.lot or "",
        )
    )
    return out


@router.get("/stock", response_model=list[StockRowOut])
def list_stock(
    _user: CurrentUser,
    db: DB,
    q: QueryText = None,
    location_id: int | None = None,
    unassigned: bool = False,
    gtin: Annotated[str | None, Query(max_length=14)] = None,
    sscc: Annotated[str | None, Query(max_length=18)] = None,
    expires_within_days: Annotated[int | None, Query(ge=0, le=3650)] = None,
) -> list[StockRowOut]:
    """Current stock, one row per location + item. Negative rows mean missing stock."""
    return _stock(db, q, location_id, unassigned, gtin, sscc, expires_within_days)


@router.get("/stock/expiry")
def expiry_summary(_user: CurrentUser, db: DB, settings: AppSettings) -> dict[str, int]:
    """How much stock is expired, or expires within the warning period."""
    today = date.today()
    soon = today + timedelta(days=settings.expiry_warning_days + 1)
    rows = [r for r in stock.stock_rows(db, expires_before=soon) if r.quantity > 0]
    expired = [r for r in rows if r.expiry_date < today]
    expiring = [r for r in rows if r.expiry_date >= today]
    return {
        "warning_days": settings.expiry_warning_days,
        "expired_lines": len(expired),
        "expired_units": sum(r.quantity for r in expired),
        "expiring_lines": len(expiring),
        "expiring_units": sum(r.quantity for r in expiring),
    }


@router.get("/stock/export.csv")
def export_stock(
    _user: CurrentUser,
    db: DB,
    q: QueryText = None,
    location_id: int | None = None,
    unassigned: bool = False,
    expires_within_days: Annotated[int | None, Query(ge=0, le=3650)] = None,
) -> Response:
    rows = _stock(db, q, location_id, unassigned, None, None, expires_within_days)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["location", "sku", "product", "gtin", "lot", "expiry_date", "sscc", "quantity"]
    )
    for r in rows:
        writer.writerow(
            _csv_safe(v)
            for v in [
                r.location.code if r.location else "",
                r.product.sku if r.product else "",
                r.product.name if r.product else "",
                r.gtin,
                r.lot,
                r.expiry_date,
                r.sscc,
                r.quantity,
            ]
        )
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="stock-{date.today()}.csv"'},
    )


@router.post("/stock/adjust", response_model=MovementOut | None)
def adjust_stock(body: AdjustIn, admin: AdminUser, db: DB) -> Movement | None:
    """Set the quantity of an item at a location (e.g. after a recount or damage)."""
    location = None
    if body.location_id is not None:
        location = db.get(Location, body.location_id)
        if location is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found.")
    try:
        movement = stock.adjust(
            db,
            user=admin,
            location_id=body.location_id,
            gtin=body.gtin,
            lot=body.lot or None,
            expiry_date=body.expiry_date,
            sscc=body.sscc or None,
            new_quantity=body.quantity,
            note=body.note.strip(),
        )
    except ScanError as e:
        raise HTTPException(422, str(e)) from e
    if movement is not None:
        where = location.code if body.location_id is not None else "no location"
        item = " ".join(
            x
            for x in [body.gtin, body.lot and f"lot {body.lot}", body.sscc and f"SSCC {body.sscc}"]
            if x
        )
        audit.record(
            db,
            admin,
            "stock.adjust",
            f"Set {item} at {where} to {body.quantity} ({movement.quantity:+d}): {movement.note}",
            entity=movement,
            details={"quantity": [body.quantity - movement.quantity, body.quantity]},
        )
    db.commit()
    return movement


@router.get("/movements", response_model=Page[MovementOut])
def list_movements(
    _user: CurrentUser,
    db: DB,
    location_id: int | None = None,
    unassigned: bool = False,
    gtin: Annotated[str | None, Query(max_length=14)] = None,
    lot: Annotated[str | None, Query(max_length=20)] = None,
    sscc: Annotated[str | None, Query(max_length=18)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[MovementOut]:
    """Movement history, newest first, e.g. for one item at one location."""
    stmt = select(Movement)
    if location_id is not None:
        stmt = stmt.where(Movement.location_id == location_id)
    if unassigned:
        stmt = stmt.where(Movement.location_id.is_(None))
    if gtin is not None:
        stmt = stmt.where(Movement.gtin == gtin)
    if lot is not None:
        stmt = stmt.where(Movement.lot == lot)
    if sscc is not None:
        stmt = stmt.where(Movement.sscc == sscc)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.options(selectinload(Movement.user), selectinload(Movement.location))
        .order_by(Movement.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return Page(items=[MovementOut.model_validate(m) for m in items], total=total)
