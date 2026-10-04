"""SQLite storage for inventory records.

The schema version lives in ``PRAGMA user_version``; :func:`connect` upgrades
older databases in place, including ones created by the pre-package app
(version 0).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from gs1_scanner.ais import AI_COLUMNS
from gs1_scanner.models import LOCATION_FIELDS, InventoryRecord

SCHEMA_VERSION = 2

SEARCH_COLUMNS = ("raw_barcode", "gs1_hri", "sku", *LOCATION_FIELDS, *AI_COLUMNS.values())


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema v{version} is newer than this app supports (v{SCHEMA_VERSION})."
        )
    with conn:
        if version < 1:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    raw_barcode TEXT,
                    parsed_json TEXT,
                    ai00_sscc TEXT,
                    ai01_gtin TEXT,
                    ai02_content_gtin TEXT,
                    ai10_lot TEXT,
                    ai11_prod_date TEXT,
                    ai21_serial TEXT,
                    ai37_qty TEXT,
                    ai240_additional_id TEXT,
                    ai241_customer_part TEXT,
                    sku TEXT,
                    warehouse TEXT,
                    aisle TEXT,
                    position TEXT,
                    shelf TEXT
                )
                """
            )
        if version < 2:
            for column in ("gs1_hri", "ai15_best_before", "ai17_expiry"):
                conn.execute(f"ALTER TABLE inventory_records ADD COLUMN {column} TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_records_sku ON inventory_records (sku)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_gtin ON inventory_records (ai01_gtin)"
            )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def insert_record(conn: sqlite3.Connection, record: InventoryRecord) -> int:
    row = record.to_row()
    columns = ", ".join(row)
    placeholders = ", ".join("?" * len(row))
    with conn:
        cur = conn.execute(
            f"INSERT INTO inventory_records ({columns}) VALUES ({placeholders})",
            list(row.values()),
        )
    record.id = int(cur.lastrowid)
    return record.id


def get_record(conn: sqlite3.Connection, record_id: int) -> InventoryRecord | None:
    row = conn.execute("SELECT * FROM inventory_records WHERE id = ?", (record_id,)).fetchone()
    return InventoryRecord.from_row(dict(row)) if row else None


def delete_record(conn: sqlite3.Connection, record_id: int) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM inventory_records WHERE id = ?", (record_id,))
    return cur.rowcount > 0


def search_records(conn: sqlite3.Connection, query: str, limit: int = 100) -> list[InventoryRecord]:
    """Newest records whose text fields contain ``query`` (all records if it is empty)."""
    query = query.strip()
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where = " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in SEARCH_COLUMNS)
        params: list[object] = [f"%{escaped}%"] * len(SEARCH_COLUMNS)
    else:
        where, params = "1", []
    rows = conn.execute(
        f"SELECT * FROM inventory_records WHERE {where} ORDER BY id DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    return [InventoryRecord.from_row(dict(r)) for r in rows]
