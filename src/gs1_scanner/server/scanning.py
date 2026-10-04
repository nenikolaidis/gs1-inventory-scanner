"""Turning scanned text into locations, products and scan records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from biip import ParseError
from biip.gs1_element_strings import GS1ElementString
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gs1_scanner.gs1 import ParseResult, parse_barcode
from gs1_scanner.server.db import Location, Product, Scan, User

LOCATION_CODE_RE = re.compile(r"[A-Z0-9][A-Z0-9._/-]{0,63}")


class ScanError(ValueError):
    """A scan can't be saved; the message is shown to the user."""


def normalize_location_code(code: str) -> str:
    return code.strip().upper()


def find_location_by_code(db: Session, code: str) -> Location | None:
    code = normalize_location_code(code)
    if not code:
        return None
    return db.scalar(select(Location).where(Location.code == code, Location.is_active))


def find_product_by_gtin(db: Session, gtin: str | None) -> Product | None:
    if not gtin:
        return None
    return db.scalar(select(Product).where(Product.gtin == gtin))


def gs1_date(ai: str, value: str | None) -> date | None:
    """Convert a GS1 YYMMDD value to a date, using GS1's century and day-00 rules."""
    if not value:
        return None
    try:
        return GS1ElementString.extract(ai + value).date
    except ParseError:
        return None


@dataclass(frozen=True)
class Resolved:
    kind: str  # "location", "gs1" or "unknown"
    location: Location | None = None
    parsed: ParseResult | None = None
    product: Product | None = None


def resolve(db: Session, text: str) -> Resolved:
    """Work out what a scan is: a location label, a GS1 barcode, or neither.

    Location codes are checked first, by exact match, so the scan screen can use
    a single input for both.
    """
    location = find_location_by_code(db, text)
    if location is not None:
        return Resolved("location", location=location)
    parsed = parse_barcode(text)
    if not parsed.elements:
        return Resolved("unknown", parsed=parsed)
    data = parsed.data
    return Resolved(
        "gs1", parsed=parsed, product=find_product_by_gtin(db, data.get("01") or data.get("02"))
    )


def create_scan(
    db: Session,
    *,
    user: User | None,
    barcode: str,
    sku_pattern: str,
    location_id: int | None = None,
    sku: str | None = None,
    quantity: int | None = None,
    note: str = "",
) -> Scan:
    """Parse ``barcode`` (never trust a client-side parse) and add a Scan to ``db``.

    If the GTIN is unknown and the user typed a SKU, the GTIN -> SKU mapping is
    learned as a new product so the next scan of that GTIN fills it in.
    """
    parsed = parse_barcode(barcode)
    if not parsed.elements:
        raise ScanError(parsed.warnings[0] if parsed.warnings else "No GS1 data in barcode.")
    data = parsed.data
    gtin = data.get("01") or data.get("02")

    location = None
    if location_id is not None:
        location = db.get(Location, location_id)
        if location is None or not location.is_active:
            raise ScanError("Unknown or inactive location.")

    sku = (sku or "").strip() or None
    product = find_product_by_gtin(db, gtin)
    if sku and not re.fullmatch(sku_pattern, sku):
        raise ScanError(f"SKU {sku!r} is not in the expected format.")
    if product is not None:
        if sku and sku.lower() != product.sku.lower():
            raise ScanError(f"GTIN {gtin} belongs to SKU {product.sku}, not {sku}.")
    elif sku:
        product = db.scalar(select(Product).where(func.lower(Product.sku) == sku.lower()))
        if product is None:
            product = Product(sku=sku, gtin=gtin)
            db.add(product)
        elif product.gtin is None and gtin:
            product.gtin = gtin

    if quantity is None and data.get("37", "").isdigit():
        quantity = int(data["37"])
    if quantity is not None and quantity < 0:
        raise ScanError("Quantity can't be negative.")

    scan = Scan(
        user=user,
        location=location,
        product=product,
        raw_barcode=barcode.strip(),
        gs1_hri=parsed.hri,
        elements=data,
        warnings=list(parsed.warnings),
        sku=product.sku if product else None,
        gtin=gtin,
        sscc=data.get("00"),
        lot=data.get("10"),
        serial=data.get("21"),
        quantity=quantity,
        production_date=gs1_date("11", data.get("11")),
        best_before=gs1_date("15", data.get("15")),
        expiry_date=gs1_date("17", data.get("17")),
        note=note.strip(),
    )
    db.add(scan)
    return scan


def parse_to_json(parsed: ParseResult) -> dict[str, Any]:
    return {
        "elements": [{"ai": e.ai, "title": e.title, "value": e.value} for e in parsed.elements],
        "warnings": list(parsed.warnings),
        "hri": parsed.hri,
    }
