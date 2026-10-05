"""Stock: derived from movements, never stored as a running total.

An *item* at a location is GTIN + lot + expiry date + SSCC. Stock of an item at
a location is the sum of its movements' quantities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from gs1_scanner.server.db import Location, Movement, Product, Scan, User
from gs1_scanner.server.scanning import ScanError

Action = Literal["receive", "pick", "move", "log"]


@dataclass(frozen=True)
class StockRow:
    location_id: int | None
    gtin: str
    lot: str | None
    expiry_date: date | None
    sscc: str | None
    quantity: int
    last_movement_at: datetime


def _escape_like(q: str) -> str:
    return "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def stock_query(
    *,
    location_id: int | None = None,
    unassigned: bool = False,
    gtin: str | None = None,
    lot: str | None = None,
    expiry_date: date | None = None,
    sscc: str | None = None,
    q: str | None = None,
    expires_before: date | None = None,
) -> Select:
    key = (Movement.location_id, Movement.gtin, Movement.lot, Movement.expiry_date, Movement.sscc)
    stmt = select(
        *key,
        func.sum(Movement.quantity).label("quantity"),
        func.max(Movement.created_at).label("last_movement_at"),
    )
    if location_id is not None:
        stmt = stmt.where(Movement.location_id == location_id)
    if unassigned:
        stmt = stmt.where(Movement.location_id.is_(None))
    if gtin is not None:
        stmt = stmt.where(Movement.gtin == gtin)
    if lot is not None:
        stmt = stmt.where(Movement.lot == lot)
    if expiry_date is not None:
        stmt = stmt.where(Movement.expiry_date == expiry_date)
    if sscc is not None:
        stmt = stmt.where(Movement.sscc == sscc)
    if expires_before is not None:
        stmt = stmt.where(Movement.expiry_date.is_not(None), Movement.expiry_date < expires_before)
    if q and q.strip():
        like = _escape_like(q)
        stmt = (
            stmt.outerjoin(Location, Location.id == Movement.location_id)
            .outerjoin(Product, Product.gtin == Movement.gtin)
            .where(
                or_(
                    *(
                        c.ilike(like, escape="\\")
                        for c in (
                            Movement.gtin,
                            Movement.lot,
                            Movement.sscc,
                            Location.code,
                            Product.sku,
                            Product.name,
                        )
                    )
                )
            )
        )
    return stmt.group_by(*key).having(func.sum(Movement.quantity) != 0)


def stock_rows(db: Session, **filters) -> list[StockRow]:
    rows = db.execute(stock_query(**filters)).all()
    return [StockRow(*row) for row in rows]


def _fefo(row: StockRow) -> tuple:
    # First expiry, first out; items without an expiry date go last, then oldest first.
    return (row.expiry_date is None, row.expiry_date or date.max, row.last_movement_at)


def _location_codes(db: Session, ids: set[int | None]) -> str:
    codes = {
        loc.id: loc.code
        for loc in db.scalars(select(Location).where(Location.id.in_([i for i in ids if i])))
    }
    return ", ".join(sorted(codes.get(i, "no location") if i else "no location" for i in ids))


def find_sources(
    db: Session, scan: Scan, location_id: int | None, quantity: int | None
) -> list[tuple[StockRow, int]]:
    """Decide which stock a pick or move takes, as (row, quantity) pairs.

    A scanned SSCC that is in stock identifies the pallet exactly. Otherwise the item is matched
    by GTIN, plus lot and expiry date when the label has them. Without a
    quantity, everything that matches is taken (e.g. the whole pallet).
    """
    rows: list[StockRow] = []
    if scan.sscc:
        rows = [r for r in stock_rows(db, sscc=scan.sscc) if r.quantity > 0]
    if rows:
        # An SSCC identifies the pallet, so where it is is already known; a
        # location the operator scanned earlier doesn't narrow it down further.
        location_id = None
    elif scan.gtin:
        filters = {"gtin": scan.gtin}
        if scan.lot:
            filters["lot"] = scan.lot
        if scan.expiry_date:
            filters["expiry_date"] = scan.expiry_date
        rows = [r for r in stock_rows(db, **filters) if r.quantity > 0]
    if not scan.gtin and not scan.sscc:
        raise ScanError("This barcode has no GTIN or SSCC, so it can't be matched to stock.")

    if location_id is not None:
        here = [r for r in rows if r.location_id == location_id]
        if not here:
            where = (
                f" Found at: {_location_codes(db, {r.location_id for r in rows})}." if rows else ""
            )
            location = db.get(Location, location_id)
            raise ScanError(
                f"Not in stock at {location.code if location else 'this location'}.{where}"
            )
        rows = here
    if not rows:
        raise ScanError("Not in stock.")
    locations = {r.location_id for r in rows}
    if len(locations) > 1:
        raise ScanError(
            f"In stock at several locations ({_location_codes(db, locations)}). "
            "Scan the location first."
        )

    rows.sort(key=_fefo)
    available = sum(r.quantity for r in rows)
    if quantity is None:
        return [(r, r.quantity) for r in rows]
    if quantity <= 0:
        raise ScanError("Quantity must be more than zero.")
    if quantity > available:
        raise ScanError(f"Only {available} in stock here, can't take {quantity}.")
    taken: list[tuple[StockRow, int]] = []
    remaining = quantity
    for r in rows:
        if remaining == 0:
            break
        take = min(r.quantity, remaining)
        taken.append((r, take))
        remaining -= take
    return taken


def expiry_warning(expiry: date | None, warning_days: int, today: date | None = None) -> str | None:
    if expiry is None:
        return None
    today = today or date.today()
    days = (expiry - today).days
    if days < 0:
        return f"Expired on {expiry.isoformat()}."
    if days == 0:
        return "Expires today."
    if days <= warning_days:
        return f"Expires in {days} day{'s' if days != 1 else ''} ({expiry.isoformat()})."
    return None


def apply_scan(
    db: Session,
    scan: Scan,
    *,
    action: Action,
    user: User | None,
    location: Location | None,
    to_location: Location | None,
    quantity: int | None,
    expiry_warning_days: int = 30,
) -> None:
    """Record the stock movements for a scan that was just created."""
    scan.action = action
    if action == "log":
        return

    def movement(kind: str, row_location_id: int | None, qty: int, **item) -> None:
        scan.movements.append(
            Movement(
                kind=kind,
                user=user,
                location_id=row_location_id,
                quantity=qty,
                note=scan.note,
                **item,
            )
        )

    if action == "receive":
        if not scan.gtin:
            raise ScanError(
                "This label has no GTIN, so it can't be added to stock. "
                "Use 'Log only' to record it anyway."
            )
        if not quantity or quantity <= 0:
            raise ScanError("Enter the quantity to receive.")
        movement(
            "receive",
            location.id if location else None,
            quantity,
            gtin=scan.gtin,
            lot=scan.lot,
            expiry_date=scan.expiry_date,
            sscc=scan.sscc,
        )
        scan.quantity = quantity
        if warning := expiry_warning(scan.expiry_date, expiry_warning_days):
            scan.warnings = [*(scan.warnings or []), warning]
        return

    if action == "move":
        if to_location is None:
            raise ScanError("Scan the destination location.")
        if location is not None and location.id == to_location.id:
            raise ScanError("The destination is the same as the source location.")

    taken = find_sources(db, scan, location.id if location else None, quantity)
    if action == "move" and taken[0][0].location_id == to_location.id:
        raise ScanError(f"This is already at {to_location.code}.")
    for row, qty in taken:
        item = {"gtin": row.gtin, "lot": row.lot, "expiry_date": row.expiry_date, "sscc": row.sscc}
        movement(action, row.location_id, -qty, **item)
        if action == "move":
            movement("move", to_location.id, qty, **item)
    scan.quantity = sum(qty for _, qty in taken)
    if scan.gtin is None:
        # Scanned by SSCC only: record what the pallet holds.
        first = taken[0][0]
        scan.gtin, scan.lot, scan.expiry_date = first.gtin, first.lot, first.expiry_date
        scan.product = db.scalar(select(Product).where(Product.gtin == first.gtin))
        scan.sku = scan.product.sku if scan.product else None
    source_id = taken[0][0].location_id
    if scan.location is None and source_id is not None:
        scan.location = db.get(Location, source_id)  # record where it came from


def adjust(
    db: Session,
    *,
    user: User,
    location_id: int | None,
    gtin: str,
    lot: str | None,
    expiry_date: date | None,
    sscc: str | None,
    new_quantity: int,
    note: str,
) -> Movement | None:
    """Set an item's quantity at a location, recording the difference as an adjustment."""
    if new_quantity < 0:
        raise ScanError("Quantity can't be negative.")
    current = db.scalar(
        select(func.coalesce(func.sum(Movement.quantity), 0)).where(
            and_(
                Movement.location_id.is_(None)
                if location_id is None
                else Movement.location_id == location_id,
                Movement.gtin == gtin,
                Movement.lot.is_(None) if lot is None else Movement.lot == lot,
                Movement.expiry_date.is_(None)
                if expiry_date is None
                else Movement.expiry_date == expiry_date,
                Movement.sscc.is_(None) if sscc is None else Movement.sscc == sscc,
            )
        )
    )
    delta = new_quantity - int(current or 0)
    if delta == 0:
        return None
    m = Movement(
        kind="adjust",
        user=user,
        location_id=location_id,
        gtin=gtin,
        lot=lot,
        expiry_date=expiry_date,
        sscc=sscc,
        quantity=delta,
        note=note,
    )
    db.add(m)
    return m
