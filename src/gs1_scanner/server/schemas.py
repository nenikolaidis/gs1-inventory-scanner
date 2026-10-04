"""Request and response bodies of the JSON API."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from gs1_scanner import ais
from gs1_scanner.server.db import Scan

Role = Literal["admin", "operator"]
T = TypeVar("T")

# SQLite returns naive datetimes; everything is stored in UTC, so say so in the API.
UtcDatetime = Annotated[
    datetime, AfterValidator(lambda d: d if d.tzinfo else d.replace(tzinfo=timezone.utc))
]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- users and auth ---


class UserOut(Orm):
    id: int
    username: str
    display_name: str
    role: Role
    is_active: bool
    created_at: UtcDatetime


class UserRef(Orm):
    id: int
    display_name: str


class LoginIn(BaseModel):
    username: str
    password: str


class SetupIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=128)
    password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=128)
    password: str
    role: Role = "operator"


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = None


# --- products and locations ---


class ProductOut(Orm):
    id: int
    sku: str
    gtin: str | None
    name: str


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    gtin: str | None = Field(default=None, max_length=14)
    name: str = Field(default="", max_length=256)


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    gtin: str | None = Field(default=None, max_length=14)
    name: str | None = Field(default=None, max_length=256)


class LocationOut(Orm):
    id: int
    code: str
    warehouse: str
    aisle: str
    position: str
    shelf: str
    description: str
    is_active: bool


class LocationIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    warehouse: str = Field(default="", max_length=64)
    aisle: str = Field(default="", max_length=64)
    position: str = Field(default="", max_length=64)
    shelf: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=256)


class LocationUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    warehouse: str | None = Field(default=None, max_length=64)
    aisle: str | None = Field(default=None, max_length=64)
    position: str | None = Field(default=None, max_length=64)
    shelf: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=256)
    is_active: bool | None = None


# --- scanning ---


class ElementOut(BaseModel):
    ai: str
    title: str
    value: str


class ParseOut(BaseModel):
    elements: list[ElementOut]
    warnings: list[str]
    hri: str


class ResolveIn(BaseModel):
    text: str = Field(max_length=500)


class ResolveOut(BaseModel):
    kind: Literal["location", "gs1", "unknown"]
    location: LocationOut | None = None
    parse: ParseOut | None = None
    product: ProductOut | None = None


class ScanIn(BaseModel):
    barcode: str = Field(min_length=1, max_length=500)
    location_id: int | None = None
    sku: str | None = Field(default=None, max_length=64)
    quantity: int | None = None
    note: str = Field(default="", max_length=500)


class ScanOut(BaseModel):
    id: int
    created_at: UtcDatetime
    user: UserRef | None
    location: LocationOut | None
    product: ProductOut | None
    raw_barcode: str
    gs1_hri: str
    elements: list[ElementOut]
    warnings: list[str]
    sku: str | None
    gtin: str | None
    sscc: str | None
    lot: str | None
    serial: str | None
    quantity: int | None
    production_date: date | None
    best_before: date | None
    expiry_date: date | None
    note: str

    @classmethod
    def from_scan(cls, scan: Scan) -> ScanOut:
        return cls(
            id=scan.id,
            created_at=scan.created_at,
            user=UserRef.model_validate(scan.user) if scan.user else None,
            location=LocationOut.model_validate(scan.location) if scan.location else None,
            product=ProductOut.model_validate(scan.product) if scan.product else None,
            raw_barcode=scan.raw_barcode,
            gs1_hri=scan.gs1_hri,
            elements=[
                ElementOut(ai=ai, title=ais.title(ai), value=value)
                for ai, value in scan.elements.items()
            ],
            warnings=scan.warnings or [],
            sku=scan.sku,
            gtin=scan.gtin,
            sscc=scan.sscc,
            lot=scan.lot,
            serial=scan.serial,
            quantity=scan.quantity,
            production_date=scan.production_date,
            best_before=scan.best_before,
            expiry_date=scan.expiry_date,
            note=scan.note,
        )
