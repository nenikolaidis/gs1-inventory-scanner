from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select

from gs1_scanner.cli import main
from gs1_scanner.server.config import Settings
from gs1_scanner.server.db import (
    Location,
    Movement,
    Product,
    Scan,
    make_engine,
    make_session_factory,
)


def make_legacy_db(path: Path) -> None:
    """A database as written by the original Tkinter app."""
    db = sqlite3.connect(path)
    db.execute(
        """CREATE TABLE inventory_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            raw_barcode TEXT, parsed_json TEXT,
            ai00_sscc TEXT, ai01_gtin TEXT, ai02_content_gtin TEXT, ai10_lot TEXT,
            ai11_prod_date TEXT, ai21_serial TEXT, ai37_qty TEXT,
            ai240_additional_id TEXT, ai241_customer_part TEXT,
            sku TEXT, warehouse TEXT, aisle TEXT, position TEXT, shelf TEXT)"""
    )
    rows = [
        ("2025-12-16T15:09:34", "(01)03012345678902(10)LOT1(37)5", "ABC12", "W1", "3", "", "2"),
        ("2025-12-17T08:00:00", "garbage", None, None, None, None, None),
    ]
    db.executemany(
        "INSERT INTO inventory_records "
        "(created_at, raw_barcode, sku, warehouse, aisle, position, shelf) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    db.commit()
    db.close()


def test_import_legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    legacy = tmp_path / "inventory.db"
    make_legacy_db(legacy)
    before = legacy.read_bytes()
    url = f"sqlite:///{tmp_path / 'new.db'}"
    monkeypatch.setenv("GS1_SCANNER_DATABASE_URL", url)

    assert main(["import-legacy", str(legacy)]) == 0
    assert "Imported 1 record(s), skipped 1." in capsys.readouterr().out
    assert main(["import-legacy", str(legacy)]) == 0  # running again adds nothing
    assert "Imported 0 record(s), skipped 2." in capsys.readouterr().out
    assert legacy.read_bytes() == before  # the old database is never modified

    with make_session_factory(make_engine(Settings().database_url))() as db:
        scan = db.scalar(select(Scan))
        assert scan.lot == "LOT1"
        assert scan.quantity == 5
        assert scan.sku == "ABC12"
        assert scan.created_at.year == 2025
        assert db.scalar(select(Location.code)) == "W1-3-2"
        assert db.scalar(select(Product.gtin)) == "03012345678902"
        movement = db.scalar(select(Movement))
        assert (movement.kind, movement.quantity, movement.lot) == ("receive", 5, "LOT1")


def test_import_legacy_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GS1_SCANNER_DATABASE_URL", f"sqlite:///{tmp_path / 'new.db'}")
    assert main(["import-legacy", str(tmp_path / "nope.db")]) == 1
