from __future__ import annotations

from pathlib import Path

import pytest

from gs1_scanner.service import InventoryService


@pytest.fixture
def service(tmp_path: Path) -> InventoryService:
    s = InventoryService(tmp_path / "inventory.db")
    yield s
    s.close()


def test_build_save_and_search(service: InventoryService) -> None:
    record = service.build_record(
        "  (01)03012345678902(10)LOT1  ", sku=" abc12 ", warehouse=" W1 ", aisle=""
    )
    assert record.raw_barcode == "(01)03012345678902(10)LOT1"
    assert record.sku == "abc12"
    assert record.warehouse == "W1"
    assert record.aisle is None
    new_id = service.save(record)
    assert [r.id for r in service.search("lot1")] == [new_id]


@pytest.mark.parametrize("sku", ["ABC1", "ABCDEFG", "AB-12"])
def test_rejects_bad_sku(service: InventoryService, sku: str) -> None:
    with pytest.raises(ValueError, match="SKU"):
        service.build_record("(10)LOT1", sku=sku)


def test_rejects_unparseable_barcode(service: InventoryService) -> None:
    with pytest.raises(ValueError, match="No GS1 data"):
        service.build_record("hello")
