"""Stock counts: count a location, compare with the system, apply the differences."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from gs1_scanner.gs1 import parse_barcode
from gs1_scanner.server import audit, stock
from gs1_scanner.server.db import CountLine, Location, Movement, Product, StockCount, utc_now
from gs1_scanner.server.deps import DB, AdminUser, CurrentUser
from gs1_scanner.server.scanning import gs1_date
from gs1_scanner.server.schemas import LocationOut, Orm, ProductOut, UserRef, UtcDatetime

router = APIRouter(prefix="/api/counts", tags=["counts"])

Key = tuple[str, str | None, date | None, str | None]  # gtin, lot, expiry, sscc


class CountStart(BaseModel):
    location_id: int


class CountScan(BaseModel):
    barcode: str = Field(min_length=1, max_length=500)
    quantity: int | None = Field(default=None, ge=0)


class LineUpdate(BaseModel):
    quantity: int = Field(ge=0)


class CountLineOut(Orm):
    id: int
    gtin: str
    lot: str | None
    expiry_date: date | None
    sscc: str | None
    quantity: int
    expected: int | None


class CountRowOut(BaseModel):
    gtin: str
    product: ProductOut | None
    lot: str | None
    expiry_date: date | None
    sscc: str | None
    expected: int
    counted: int
    difference: int
    line_id: int | None


class CountSummaryOut(Orm):
    id: int
    created_at: UtcDatetime
    status: Literal["open", "applied", "cancelled"]
    location: LocationOut
    user: UserRef | None
    closed_at: UtcDatetime | None
    closed_by: UserRef | None


class CountOut(CountSummaryOut):
    lines: list[CountLineOut]
    rows: list[CountRowOut]


def _key(obj) -> Key:
    return (obj.gtin, obj.lot, obj.expiry_date, obj.sscc)


def _rows(db: DB, count: StockCount) -> list[CountRowOut]:
    """Expected (live stock) vs counted, per item. Uncounted stock counts as zero."""
    expected: dict[Key, int] = {}
    if count.status == "open":
        for r in stock.stock_rows(db, location_id=count.location_id):
            expected[_key(r)] = r.quantity
    lines = {_key(line): line for line in count.lines}
    keys = sorted(
        set(expected) | set(lines),
        key=lambda k: (k[0], k[2] or date.max, k[1] or "", k[3] or ""),
    )
    products = {
        p.gtin: p for p in db.scalars(select(Product).where(Product.gtin.in_({k[0] for k in keys})))
    }
    out = []
    for k in keys:
        line = lines.get(k)
        counted = line.quantity if line else 0
        if count.status == "open":
            exp = expected.get(k, 0)
        else:
            exp = line.expected if line and line.expected is not None else counted
        out.append(
            CountRowOut(
                gtin=k[0],
                product=ProductOut.model_validate(products[k[0]]) if k[0] in products else None,
                lot=k[1],
                expiry_date=k[2],
                sscc=k[3],
                expected=exp,
                counted=counted,
                difference=counted - exp,
                line_id=line.id if line else None,
            )
        )
    return out


def _out(db: DB, count: StockCount) -> CountOut:
    summary = CountSummaryOut.model_validate(count)
    return CountOut(
        **summary.model_dump(),
        lines=[CountLineOut.model_validate(line) for line in count.lines],
        rows=_rows(db, count),
    )


def _get(db: DB, count_id: int, *, open_only: bool = False) -> StockCount:
    count = db.get(StockCount, count_id)
    if count is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Count not found.")
    if open_only and count.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"This count is already {count.status}.")
    return count


@router.get("", response_model=list[CountSummaryOut])
def list_counts(
    _user: CurrentUser,
    db: DB,
    status_: Annotated[
        Literal["open", "applied", "cancelled"] | None, Query(alias="status")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[StockCount]:
    stmt = select(StockCount).options(
        selectinload(StockCount.location), selectinload(StockCount.user)
    )
    if status_:
        stmt = stmt.where(StockCount.status == status_)
    return list(db.scalars(stmt.order_by(StockCount.id.desc()).limit(limit)))


@router.post("", response_model=CountOut)
def start_count(body: CountStart, user: CurrentUser, db: DB) -> CountOut:
    """Start counting a location, or continue its open count."""
    location = db.get(Location, body.location_id)
    if location is None or not location.is_active:
        raise HTTPException(422, "Unknown or inactive location.")
    count = db.scalar(
        select(StockCount).where(StockCount.location_id == location.id, StockCount.status == "open")
    )
    if count is None:
        count = StockCount(user=user, location=location)
        db.add(count)
        db.commit()
    return _out(db, count)


@router.get("/{count_id}", response_model=CountOut)
def get_count(count_id: int, _user: CurrentUser, db: DB) -> CountOut:
    return _out(db, _get(db, count_id))


@router.post("/{count_id}/scan", response_model=CountOut)
def count_scan(count_id: int, body: CountScan, _user: CurrentUser, db: DB) -> CountOut:
    """Add a scanned item to the count. Scanning the same item again adds to it."""
    count = _get(db, count_id, open_only=True)
    parsed = parse_barcode(body.barcode)
    data = parsed.data
    gtin = data.get("01") or data.get("02")
    quantity = body.quantity
    if quantity is None and data.get("37", "").isdigit():
        quantity = int(data["37"])

    found: list[tuple[Key, int]] = []
    if gtin:
        if quantity is None:
            raise HTTPException(422, "Enter the counted quantity.")
        key = (gtin, data.get("10"), gs1_date("17", data.get("17")), data.get("00"))
        found.append((key, quantity))
    elif data.get("00"):
        # A pallet label with only an SSCC: count the pallet as intact.
        rows = [r for r in stock.stock_rows(db, sscc=data["00"]) if r.quantity > 0]
        if not rows:
            raise HTTPException(
                422, "Unknown pallet: scan a label with a GTIN and enter the quantity."
            )
        found = [(_key(r), r.quantity) for r in rows]
    else:
        raise HTTPException(422, parsed.warnings[0] if parsed.warnings else "No GTIN on label.")

    lines = {_key(line): line for line in count.lines}
    for key, qty in found:
        if key in lines:
            lines[key].quantity += qty
        else:
            gtin_, lot, expiry, sscc = key
            count.lines.append(
                CountLine(gtin=gtin_, lot=lot, expiry_date=expiry, sscc=sscc, quantity=qty)
            )
    db.commit()
    return _out(db, count)


def _line(count: StockCount, line_id: int) -> CountLine:
    for line in count.lines:
        if line.id == line_id:
            return line
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not found.")


@router.patch("/{count_id}/lines/{line_id}", response_model=CountOut)
def update_line(
    count_id: int, line_id: int, body: LineUpdate, _user: CurrentUser, db: DB
) -> CountOut:
    count = _get(db, count_id, open_only=True)
    _line(count, line_id).quantity = body.quantity
    db.commit()
    return _out(db, count)


@router.delete("/{count_id}/lines/{line_id}", response_model=CountOut)
def delete_line(count_id: int, line_id: int, _user: CurrentUser, db: DB) -> CountOut:
    count = _get(db, count_id, open_only=True)
    count.lines.remove(_line(count, line_id))
    db.commit()
    return _out(db, count)


@router.post("/{count_id}/apply", response_model=CountOut)
def apply_count(count_id: int, admin: AdminUser, db: DB) -> CountOut:
    """Correct stock to what was counted, as adjustments noted with the count number."""
    count = _get(db, count_id, open_only=True)
    rows = _rows(db, count)
    changed = [r for r in rows if r.difference != 0]
    note = f"Stock count #{count.id}"
    for r in changed:
        db.add(
            Movement(
                kind="adjust",
                user=admin,
                location_id=count.location_id,
                gtin=r.gtin,
                lot=r.lot,
                expiry_date=r.expiry_date,
                sscc=r.sscc,
                quantity=r.difference,
                note=note,
            )
        )
    # Keep what the system expected at the time, for the record.
    lines = {_key(line): line for line in count.lines}
    for r in rows:
        key = (r.gtin, r.lot, r.expiry_date, r.sscc)
        if key not in lines:
            lines[key] = CountLine(
                gtin=r.gtin, lot=r.lot, expiry_date=r.expiry_date, sscc=r.sscc, quantity=0
            )
            count.lines.append(lines[key])
        lines[key].expected = r.expected
    count.status, count.closed_at, count.closed_by = "applied", utc_now(), admin
    audit.record(
        db,
        admin,
        "count.apply",
        f"Applied stock count #{count.id} at {count.location.code}: "
        + (f"{len(changed)} correction(s)" if changed else "no differences"),
        entity=count,
        details={
            "differences": [
                [r.product.sku if r.product else r.gtin, r.lot, r.expected, r.counted]
                for r in changed
            ]
        },
    )
    db.commit()
    return _out(db, count)


@router.post("/{count_id}/cancel", response_model=CountOut)
def cancel_count(count_id: int, user: CurrentUser, db: DB) -> CountOut:
    count = _get(db, count_id, open_only=True)
    if not user.is_admin and count.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can cancel others' counts.")
    count.status, count.closed_at, count.closed_by = "cancelled", utc_now(), user
    audit.record(
        db,
        user,
        "count.cancel",
        f"Cancelled stock count #{count.id} at {count.location.code}",
        entity=count,
    )
    db.commit()
    return _out(db, count)
