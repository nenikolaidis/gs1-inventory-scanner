"""Application logic shared by every front end (currently the Tkinter GUI)."""

from __future__ import annotations

from pathlib import Path

from gs1_scanner import storage
from gs1_scanner.gs1 import ParseResult, parse_barcode
from gs1_scanner.models import InventoryRecord, clean, is_valid_sku


class InventoryService:
    def __init__(self, db_path: str | Path):
        self.db_path = db_path
        self.conn = storage.connect(db_path)

    @staticmethod
    def parse(barcode: str) -> ParseResult:
        return parse_barcode(barcode)

    def build_record(
        self,
        barcode: str,
        sku: str | None = None,
        warehouse: str | None = None,
        aisle: str | None = None,
        position: str | None = None,
        shelf: str | None = None,
    ) -> InventoryRecord:
        """Parse ``barcode`` and combine it with the manual fields.

        Raises ValueError if the barcode has no GS1 data or the SKU is malformed.
        """
        parsed = parse_barcode(barcode)
        if not parsed.elements:
            raise ValueError("No GS1 data could be read from the barcode.")
        sku = clean(sku)
        if sku and not is_valid_sku(sku):
            raise ValueError("SKU must be 5 or 6 letters or digits.")
        return InventoryRecord(
            raw_barcode=barcode.strip(),
            elements=parsed.data,
            gs1_hri=parsed.hri,
            sku=sku,
            warehouse=clean(warehouse),
            aisle=clean(aisle),
            position=clean(position),
            shelf=clean(shelf),
        )

    def save(self, record: InventoryRecord) -> int:
        return storage.insert_record(self.conn, record)

    def get(self, record_id: int) -> InventoryRecord | None:
        return storage.get_record(self.conn, record_id)

    def delete(self, record_id: int) -> bool:
        return storage.delete_record(self.conn, record_id)

    def search(self, query: str, limit: int = 100) -> list[InventoryRecord]:
        return storage.search_records(self.conn, query, limit=limit)

    def close(self) -> None:
        self.conn.close()
