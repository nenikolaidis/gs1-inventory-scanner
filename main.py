from __future__ import annotations

from typing import Any, Dict, List, Optional

import database
from barcode_parser import parse_barcode, ParseResult
from models import InventoryRecord
from utils import normalize_ws, is_valid_sku


class InventoryApp:
    def __init__(self, db_path: str = database.DB_PATH_DEFAULT):
        self.conn = database.get_conn(db_path)
        database.init_db(self.conn)

    def parse(self, raw_barcode: str) -> ParseResult:
        return parse_barcode(raw_barcode)

    def build_record(
        self,
        raw_barcode: str,
        parsed: ParseResult,
        sku: Optional[str],
        warehouse: Optional[str],
        aisle: Optional[str],
        position: Optional[str],
        shelf: Optional[str],
    ) -> InventoryRecord:
        raw_barcode = normalize_ws(raw_barcode)
        sku = normalize_ws(sku)

        if sku and not is_valid_sku(sku):
            raise ValueError("SKU must be 5 or 6 alphanumeric characters.")

        d = parsed.data if parsed else {}

        return InventoryRecord(
            ai00_sscc=d.get("00"),
            ai01_gtin=d.get("01"),
            ai02_content_gtin=d.get("02"),
            ai10_lot=d.get("10"),
            ai11_prod_date=d.get("11"),
            ai21_serial=d.get("21"),
            ai37_qty=d.get("37"),
            ai240_additional_id=d.get("240"),
            ai241_customer_part=d.get("241"),
            sku=sku,
            warehouse=normalize_ws(warehouse),
            aisle=normalize_ws(aisle),
            position=normalize_ws(position),
            shelf=normalize_ws(shelf),
            raw_barcode=raw_barcode,
            parsed_json=dict(d),
        )

    def save_record(self, record: InventoryRecord) -> int:
        return database.insert_record(self.conn, record.to_db_dict())
    
    from typing import Any, Dict, List, Optional  # ensure these are imported at top

    def search_records(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        return database.search_records(self.conn, query, limit=limit)

    def get_record(self, record_id: int) -> Optional[Dict[str, Any]]:
        return database.get_record_by_id(self.conn, record_id)


    @staticmethod
    def format_parse_for_display(parsed: ParseResult) -> str:
        if not parsed or not parsed.data:
            text = "(no data parsed)"
        else:
            lines = [f"({ai}) {val}" for ai, val in sorted(parsed.data.items(), key=lambda x: (len(x[0]), x[0]))]
            text = "\n".join(lines)

        if parsed and parsed.warnings:
            text += "\n\nWarnings:\n" + "\n".join([f"- {w}" for w in parsed.warnings])

        return text

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


def main() -> None:
    from gui import run

    app = InventoryApp()
    try:
        run(app)
    finally:
        app.close()


if __name__ == "__main__":
    main()
