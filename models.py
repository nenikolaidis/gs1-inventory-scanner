from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any


@dataclass
class InventoryRecord:
    # Barcode-derived fields (GS1 AIs)
    ai00_sscc: Optional[str] = None
    ai01_gtin: Optional[str] = None
    ai02_content_gtin: Optional[str] = None
    ai10_lot: Optional[str] = None
    ai11_prod_date: Optional[str] = None  # stored as YYMMDD or ISO later
    ai21_serial: Optional[str] = None
    ai37_qty: Optional[str] = None
    ai240_additional_id: Optional[str] = None
    ai241_customer_part: Optional[str] = None

    # Manual fields
    sku: Optional[str] = None
    warehouse: Optional[str] = None
    aisle: Optional[str] = None
    position: Optional[str] = None
    shelf: Optional[str] = None

    # Metadata
    raw_barcode: Optional[str] = None
    parsed_json: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))

    def to_db_dict(self) -> Dict[str, Any]:
        return {
            "ai00_sscc": self.ai00_sscc,
            "ai01_gtin": self.ai01_gtin,
            "ai02_content_gtin": self.ai02_content_gtin,
            "ai10_lot": self.ai10_lot,
            "ai11_prod_date": self.ai11_prod_date,
            "ai21_serial": self.ai21_serial,
            "ai37_qty": self.ai37_qty,
            "ai240_additional_id": self.ai240_additional_id,
            "ai241_customer_part": self.ai241_customer_part,
            "sku": self.sku,
            "warehouse": self.warehouse,
            "aisle": self.aisle,
            "position": self.position,
            "shelf": self.shelf,
            "raw_barcode": self.raw_barcode,
            "parsed_json": self.parsed_json,
            "created_at": self.created_at,
        }
