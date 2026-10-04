from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from gs1_scanner import storage
from gs1_scanner.models import InventoryRecord


def make_record(**overrides) -> InventoryRecord:
    fields = dict(
        raw_barcode="010301234567890210LOT1",
        elements={"01": "03012345678902", "10": "LOT1"},
        gs1_hri="(01)03012345678902(10)LOT1",
        sku="ABC12",
        warehouse="W1",
    )
    fields.update(overrides)
    return InventoryRecord(**fields)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = storage.connect(tmp_path / "sub" / "inventory.db")
    yield c
    c.close()


def test_round_trip(conn: sqlite3.Connection) -> None:
    record = make_record(elements={"10": "LOT1", "01": "03012345678902", "17": "261231"})
    new_id = storage.insert_record(conn, record)
    loaded = storage.get_record(conn, new_id)
    assert loaded == record
    assert list(loaded.elements) == ["10", "01", "17"]
    row = conn.execute("SELECT ai17_expiry, ai01_gtin FROM inventory_records").fetchone()
    assert tuple(row) == ("261231", "03012345678902")


def test_search(conn: sqlite3.Connection) -> None:
    storage.insert_record(conn, make_record(sku="AAA11"))
    storage.insert_record(conn, make_record(sku="BBB22", warehouse="100%_dock"))
    assert [r.sku for r in storage.search_records(conn, "")] == ["BBB22", "AAA11"]
    assert [r.sku for r in storage.search_records(conn, "aaa")] == ["AAA11"]
    assert [r.sku for r in storage.search_records(conn, "LOT1")] == ["BBB22", "AAA11"]
    # LIKE wildcards in the query are matched literally
    assert [r.sku for r in storage.search_records(conn, "%_")] == ["BBB22"]
    assert storage.search_records(conn, "_") == storage.search_records(conn, "%_")


def test_delete(conn: sqlite3.Connection) -> None:
    new_id = storage.insert_record(conn, make_record())
    assert storage.delete_record(conn, new_id)
    assert storage.get_record(conn, new_id) is None
    assert not storage.delete_record(conn, new_id)


def test_upgrades_database_from_original_app(tmp_path: Path) -> None:
    path = tmp_path / "inventory.db"
    old = sqlite3.connect(path)
    old.execute(
        """CREATE TABLE inventory_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            raw_barcode TEXT, parsed_json TEXT,
            ai00_sscc TEXT, ai01_gtin TEXT, ai02_content_gtin TEXT, ai10_lot TEXT,
            ai11_prod_date TEXT, ai21_serial TEXT, ai37_qty TEXT,
            ai240_additional_id TEXT, ai241_customer_part TEXT,
            sku TEXT, warehouse TEXT, aisle TEXT, position TEXT, shelf TEXT)"""
    )
    old.execute(
        "INSERT INTO inventory_records (created_at, raw_barcode, parsed_json, ai10_lot) "
        "VALUES (?, ?, ?, ?)",
        ("2025-12-16T15:09:34", "(10)LOT1", json.dumps({"10": "LOT1"}), "LOT1"),
    )
    old.commit()
    old.close()

    conn = storage.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION
    record = storage.get_record(conn, 1)
    assert record.elements == {"10": "LOT1"}
    assert record.gs1_hri == "(10)LOT1"
    storage.insert_record(conn, make_record())
    conn.close()

    # Opening again is a no-op.
    storage.connect(path).close()


def test_refuses_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "inventory.db"
    c = sqlite3.connect(path)
    c.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION + 1}")
    c.close()
    with pytest.raises(RuntimeError, match="newer"):
        storage.connect(path)
