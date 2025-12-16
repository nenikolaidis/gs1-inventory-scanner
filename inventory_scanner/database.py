import sqlite3
from typing import Any, Dict, List, Optional
from utils import json_dumps, json_loads

DB_PATH_DEFAULT = "inventory.db"


def get_conn(db_path: str = DB_PATH_DEFAULT) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
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
    conn.commit()


def insert_record(conn: sqlite3.Connection, record: Dict[str, Any]) -> int:
    record = dict(record)
    record["parsed_json"] = json_dumps(record.get("parsed_json", {}))

    cols = list(record.keys())
    placeholders = ", ".join(["?"] * len(cols))
    sql = f"INSERT INTO inventory_records ({', '.join(cols)}) VALUES ({placeholders})"

    cur = conn.execute(sql, [record[c] for c in cols])
    conn.commit()
    return int(cur.lastrowid)


def list_records(conn: sqlite3.Connection, limit: int = 200) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM inventory_records ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["parsed_json"] = json_loads(d.get("parsed_json") or "")
        out.append(d)
    return out
