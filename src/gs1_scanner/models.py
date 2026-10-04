from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from gs1_scanner.ais import AI_COLUMNS

SKU_RE = re.compile(r"[A-Za-z0-9]{5,6}")
LOCATION_FIELDS = ("warehouse", "aisle", "position", "shelf")


def is_valid_sku(sku: str) -> bool:
    return SKU_RE.fullmatch(sku) is not None


def clean(value: str | None) -> str | None:
    """Strip whitespace; empty strings become None."""
    value = (value or "").strip()
    return value or None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class InventoryRecord:
    raw_barcode: str
    elements: dict[str, str]  # AI -> value, in scan order
    gs1_hri: str
    sku: str | None = None
    warehouse: str | None = None
    aisle: str | None = None
    position: str | None = None
    shelf: str | None = None
    created_at: str = field(default_factory=utc_now)
    id: int | None = None

    def to_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "created_at": self.created_at,
            "raw_barcode": self.raw_barcode,
            "gs1_hri": self.gs1_hri,
            "parsed_json": json.dumps(self.elements, ensure_ascii=False),
            "sku": self.sku,
            **{name: getattr(self, name) for name in LOCATION_FIELDS},
        }
        for ai, column in AI_COLUMNS.items():
            row[column] = self.elements.get(ai)
        return row

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> InventoryRecord:
        elements = json.loads(row.get("parsed_json") or "{}")
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            raw_barcode=row.get("raw_barcode") or "",
            elements=elements,
            # Records saved before schema v2 have no HRI column value.
            gs1_hri=row.get("gs1_hri") or "".join(f"({ai}){v}" for ai, v in elements.items()),
            sku=row.get("sku"),
            **{name: row.get(name) for name in LOCATION_FIELDS},
        )
