from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from gs1_scanner.gs1 import Element
from gs1_scanner.labels import LabelData, label_pdf_bytes
from gs1_scanner.server.db import Location, Scan
from gs1_scanner.server.deps import DB, AppSettings, CurrentUser, as_utc
from gs1_scanner.server.scanning import ScanError, create_scan, parse_to_json, resolve
from gs1_scanner.server.schemas import (
    LocationOut,
    Page,
    ParseOut,
    ProductOut,
    ResolveIn,
    ResolveOut,
    ScanIn,
    ScanOut,
)

router = APIRouter(prefix="/api", tags=["scans"])

UNDO_WINDOW = timedelta(minutes=10)


@router.post("/resolve", response_model=ResolveOut)
def resolve_scan(body: ResolveIn, _user: CurrentUser, db: DB) -> ResolveOut:
    """Identify scanned text as a location label or a GS1 barcode, without saving anything."""
    r = resolve(db, body.text)
    return ResolveOut(
        kind=r.kind,
        location=LocationOut.model_validate(r.location) if r.location else None,
        parse=ParseOut(**parse_to_json(r.parsed)) if r.parsed else None,
        product=ProductOut.model_validate(r.product) if r.product else None,
    )


@router.post("/scans", response_model=ScanOut, status_code=status.HTTP_201_CREATED)
def save_scan(body: ScanIn, user: CurrentUser, db: DB, settings: AppSettings) -> ScanOut:
    try:
        scan = create_scan(
            db,
            user=user,
            barcode=body.barcode,
            sku_pattern=settings.sku_pattern,
            location_id=body.location_id,
            sku=body.sku,
            quantity=body.quantity,
            note=body.note,
        )
    except ScanError as e:
        raise HTTPException(422, str(e)) from e
    db.commit()
    return ScanOut.from_scan(scan)


def _filtered(
    q: str | None,
    location_id: int | None,
    date_from: date | None,
    date_to: date | None,
) -> Select:
    stmt = select(Scan).outerjoin(Scan.location)
    if q and q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        columns = [Scan.sku, Scan.gtin, Scan.sscc, Scan.lot, Scan.serial, Scan.gs1_hri]
        columns += [Scan.raw_barcode, Scan.note, Location.code]
        stmt = stmt.where(or_(*(c.ilike(like, escape="\\") for c in columns)))
    if location_id is not None:
        stmt = stmt.where(Scan.location_id == location_id)
    if date_from is not None:
        stmt = stmt.where(Scan.created_at >= datetime.combine(date_from, time(), timezone.utc))
    if date_to is not None:
        end = datetime.combine(date_to + timedelta(days=1), time(), timezone.utc)
        stmt = stmt.where(Scan.created_at < end)
    return stmt


QueryText = Annotated[str | None, Query(max_length=200)]


@router.get("/scans", response_model=Page[ScanOut])
def list_scans(
    _user: CurrentUser,
    db: DB,
    q: QueryText = None,
    location_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ScanOut]:
    stmt = _filtered(q, location_id, date_from, date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    scans = db.scalars(
        stmt.options(
            selectinload(Scan.user), selectinload(Scan.location), selectinload(Scan.product)
        )
        .order_by(Scan.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return Page(items=[ScanOut.from_scan(s) for s in scans], total=total or 0)


CSV_COLUMNS = [
    "id",
    "created_at",
    "user",
    "location",
    "warehouse",
    "aisle",
    "position",
    "shelf",
    "sku",
    "gtin",
    "sscc",
    "lot",
    "serial",
    "quantity",
    "production_date",
    "best_before",
    "expiry_date",
    "gs1_hri",
    "raw_barcode",
    "note",
    "warnings",
]


def _csv_safe(value: object) -> str:
    """Stop spreadsheet apps from running scanned text as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/scans/export.csv")
def export_scans(
    _user: CurrentUser,
    request: Request,
    q: QueryText = None,
    location_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> StreamingResponse:
    stmt = (
        _filtered(q, location_id, date_from, date_to)
        .options(selectinload(Scan.user), selectinload(Scan.location))
        .order_by(Scan.id)
    )

    def rows() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(CSV_COLUMNS)
        # Own session: the response body is streamed after the endpoint returns.
        with request.app.state.session_factory() as db:
            scans = list(db.scalars(stmt))
        for scan in scans:
            loc = scan.location
            writer.writerow(
                _csv_safe(v)
                for v in [
                    scan.id,
                    as_utc(scan.created_at).isoformat(),
                    scan.user.username if scan.user else "",
                    loc.code if loc else "",
                    loc.warehouse if loc else "",
                    loc.aisle if loc else "",
                    loc.position if loc else "",
                    loc.shelf if loc else "",
                    scan.sku,
                    scan.gtin,
                    scan.sscc,
                    scan.lot,
                    scan.serial,
                    scan.quantity,
                    scan.production_date,
                    scan.best_before,
                    scan.expiry_date,
                    scan.gs1_hri,
                    scan.raw_barcode,
                    scan.note,
                    "; ".join(scan.warnings or []),
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()
        yield buf.getvalue()

    filename = f"scans-{datetime.now(timezone.utc):%Y%m%d-%H%M}.csv"
    return StreamingResponse(
        rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _get_scan(db: DB, scan_id: int) -> Scan:
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found.")
    return scan


@router.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(scan_id: int, _user: CurrentUser, db: DB) -> ScanOut:
    return ScanOut.from_scan(_get_scan(db, scan_id))


@router.delete("/scans/{scan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scan(scan_id: int, user: CurrentUser, db: DB) -> None:
    """Admins can delete any scan; operators can undo their own recent scans."""
    scan = _get_scan(db, scan_id)
    if not user.is_admin:
        age = datetime.now(timezone.utc) - as_utc(scan.created_at)
        if scan.user_id != user.id or age > UNDO_WINDOW:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only admins can delete this scan. You can undo your own scans "
                f"for {UNDO_WINDOW.seconds // 60} minutes.",
            )
    db.delete(scan)
    db.commit()


@router.get("/scans/{scan_id}/label.pdf")
def scan_label(scan_id: int, _user: CurrentUser, db: DB) -> Response:
    scan = _get_scan(db, scan_id)
    loc = scan.location
    pdf = label_pdf_bytes(
        LabelData(
            elements=[Element(ai, value) for ai, value in scan.elements.items()],
            location=loc.code if loc else "",
            sku=scan.sku or "",
            warehouse=loc.warehouse if loc else "",
            aisle=loc.aisle if loc else "",
            position=loc.position if loc else "",
            shelf=loc.shelf if loc else "",
        )
    )
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="scan-{scan.id}.pdf"'},
    )
