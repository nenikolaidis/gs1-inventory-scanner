"""Products (SKU <-> GTIN) and locations."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from gs1_scanner import ais
from gs1_scanner.labels import LocationLabel, location_labels_pdf
from gs1_scanner.server.db import Location, Product, Scan
from gs1_scanner.server.deps import DB, AdminUser, AppSettings, CurrentUser
from gs1_scanner.server.scanning import LOCATION_CODE_RE, normalize_location_code
from gs1_scanner.server.schemas import (
    LocationIn,
    LocationOut,
    LocationUpdate,
    ProductIn,
    ProductOut,
    ProductUpdate,
)

router = APIRouter(prefix="/api", tags=["catalog"])

QueryText = Annotated[str | None, Query(max_length=200)]


def _like(q: str) -> str:
    return "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _commit_or_conflict(db: DB, message: str) -> None:
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, message) from e


# --- products ---


def _check_product(sku: str | None, gtin: str | None, sku_pattern: str) -> None:
    if sku is not None and not re.fullmatch(sku_pattern, sku):
        raise HTTPException(422, f"SKU {sku!r} is not in the expected format.")
    if gtin is not None and not (
        len(gtin) == 14 and gtin.isdigit() and ais.check_digit_ok("01", gtin)
    ):
        raise HTTPException(
            422,
            "GTIN must be 14 digits with a valid check digit (pad shorter GTINs with zeros).",
        )


def _clean_gtin(gtin: str | None) -> str | None:
    gtin = (gtin or "").strip()
    return gtin.zfill(14) if gtin.isdigit() and len(gtin) in (8, 12, 13) else (gtin or None)


@router.get("/products", response_model=list[ProductOut])
def list_products(
    _user: CurrentUser,
    db: DB,
    q: QueryText = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[Product]:
    stmt = select(Product).order_by(Product.sku).limit(limit)
    if q and q.strip():
        like = _like(q)
        stmt = stmt.where(
            or_(*(c.ilike(like, escape="\\") for c in (Product.sku, Product.gtin, Product.name)))
        )
    return list(db.scalars(stmt))


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(body: ProductIn, _admin: AdminUser, db: DB, settings: AppSettings) -> Product:
    sku, gtin = body.sku.strip(), _clean_gtin(body.gtin)
    _check_product(sku, gtin, settings.sku_pattern)
    product = Product(sku=sku, gtin=gtin, name=body.name.strip())
    db.add(product)
    _commit_or_conflict(db, "A product with this SKU or GTIN already exists.")
    return product


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int, body: ProductUpdate, _admin: AdminUser, db: DB, settings: AppSettings
) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.")
    fields = body.model_dump(exclude_unset=True)
    if "sku" in fields:
        fields["sku"] = fields["sku"].strip()
    if "gtin" in fields:
        fields["gtin"] = _clean_gtin(fields["gtin"])
    _check_product(fields.get("sku"), fields.get("gtin"), settings.sku_pattern)
    for name, value in fields.items():
        setattr(product, name, value.strip() if name == "name" else value)
    _commit_or_conflict(db, "A product with this SKU or GTIN already exists.")
    return product


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: int, _admin: AdminUser, db: DB) -> None:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.")
    if db.scalar(select(func.count()).where(Scan.product_id == product_id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This product has scans and can't be deleted."
        )
    db.delete(product)
    db.commit()


# --- locations ---


def _clean_code(code: str) -> str:
    code = normalize_location_code(code)
    if not LOCATION_CODE_RE.fullmatch(code):
        raise HTTPException(
            422,
            "Location codes may use letters, digits and . _ / - (no spaces).",
        )
    return code


@router.get("/locations", response_model=list[LocationOut])
def list_locations(
    _user: CurrentUser,
    db: DB,
    q: QueryText = None,
    include_inactive: bool = False,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> list[Location]:
    stmt = select(Location).order_by(Location.code).limit(limit)
    if not include_inactive:
        stmt = stmt.where(Location.is_active)
    if q and q.strip():
        like = _like(q)
        columns = (Location.code, Location.warehouse, Location.description)
        stmt = stmt.where(or_(*(c.ilike(like, escape="\\") for c in columns)))
    return list(db.scalars(stmt))


@router.post("/locations", response_model=LocationOut, status_code=status.HTTP_201_CREATED)
def create_location(body: LocationIn, _admin: AdminUser, db: DB) -> Location:
    fields = {k: v.strip() for k, v in body.model_dump().items()}
    fields["code"] = _clean_code(body.code)
    location = Location(**fields)
    db.add(location)
    _commit_or_conflict(db, f"Location {fields['code']} already exists.")
    return location


@router.patch("/locations/{location_id}", response_model=LocationOut)
def update_location(location_id: int, body: LocationUpdate, _admin: AdminUser, db: DB) -> Location:
    location = db.get(Location, location_id)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found.")
    for name, value in body.model_dump(exclude_unset=True).items():
        if name == "code":
            value = _clean_code(value)
        elif isinstance(value, str):
            value = value.strip()
        setattr(location, name, value)
    _commit_or_conflict(db, "Another location already uses this code.")
    return location


@router.get("/locations/labels.pdf")
def location_labels(
    _user: CurrentUser,
    db: DB,
    ids: Annotated[str, Query(description="Comma-separated location IDs", max_length=20000)],
) -> Response:
    try:
        wanted = [int(i) for i in ids.split(",") if i.strip()]
    except ValueError as e:
        raise HTTPException(422, "Invalid location IDs.") from e
    by_id = {loc.id: loc for loc in db.scalars(select(Location).where(Location.id.in_(wanted)))}
    locations = [by_id[i] for i in wanted if i in by_id]
    if not locations:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such locations.")
    pdf = location_labels_pdf([LocationLabel(loc.code, loc.description) for loc in locations])
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="location-labels.pdf"'},
    )
