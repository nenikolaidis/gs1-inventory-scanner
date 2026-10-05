from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from gs1_scanner.server import migrate

GTIN = "03012345678902"
SSCC = "380334329001623191"


def loc(client: TestClient, code: str) -> int:
    r = client.post("/api/locations", json={"code": code})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def scan(client: TestClient, barcode: str, expect: int = 201, **body) -> dict:
    r = client.post("/api/scans", json={"barcode": barcode, **body})
    assert r.status_code == expect, r.text
    return r.json()


def stock(client: TestClient, **params) -> list[tuple]:
    rows = client.get("/api/stock", params=params).json()
    return [
        (r["location"]["code"] if r["location"] else None, r["lot"], r["sscc"], r["quantity"])
        for r in rows
    ]


def label(lot: str, expiry: str, qty: int | None = None, sscc: str | None = None) -> str:
    s = f"(00){sscc}" if sscc else ""
    s += f"(01){GTIN}(17){expiry}(10){lot}"
    return s + (f"(37){qty}" if qty is not None else "")


# --- receive ---


def test_receive_adds_stock(admin: TestClient) -> None:
    a1 = loc(admin, "A1")
    s = scan(admin, label("L1", "261231", 24), location_id=a1)
    assert s["action"] == "receive"
    assert [(m["kind"], m["quantity"]) for m in s["movements"]] == [("receive", 24)]
    scan(admin, label("L1", "261231"), location_id=a1, quantity=6)
    assert stock(admin) == [("A1", "L1", None, 30)]


def test_receive_requires_quantity_and_gtin(admin: TestClient) -> None:
    r = admin.post("/api/scans", json={"barcode": label("L1", "261231")})
    assert r.status_code == 422
    assert "quantity" in r.json()["detail"]
    r = admin.post("/api/scans", json={"barcode": f"(00){SSCC}", "quantity": 1})
    assert r.status_code == 422
    assert "no GTIN" in r.json()["detail"]
    # Failed scans are not saved at all.
    assert admin.get("/api/scans").json()["total"] == 0


def test_log_only_does_not_touch_stock(admin: TestClient) -> None:
    s = scan(admin, f"(00){SSCC}", action="log")
    assert (s["action"], s["movements"]) == ("log", [])
    assert stock(admin) == []


def test_receive_without_location(admin: TestClient) -> None:
    scan(admin, label("L1", "261231", 5))
    assert stock(admin) == [(None, "L1", None, 5)]
    assert stock(admin, unassigned=True) == [(None, "L1", None, 5)]


# --- pick ---


def test_pick_is_first_expiry_first_out(admin: TestClient) -> None:
    a1 = loc(admin, "A1")
    scan(admin, label("LATE", "261231", 10), location_id=a1)
    scan(admin, label("EARLY", "260630", 10), location_id=a1)
    s = scan(admin, f"(01){GTIN}", action="pick", location_id=a1, quantity=15)
    assert [(m["lot"], m["quantity"]) for m in s["movements"]] == [("EARLY", -10), ("LATE", -5)]
    assert s["quantity"] == 15
    assert stock(admin) == [("A1", "LATE", None, 5)]


def test_pick_needs_location_when_stock_is_in_several(admin: TestClient) -> None:
    a1, a2 = loc(admin, "A1"), loc(admin, "A2")
    scan(admin, label("L1", "261231", 10), location_id=a1)
    scan(admin, label("L1", "261231", 10), location_id=a2)
    r = admin.post("/api/scans", json={"barcode": label("L1", "261231", 4), "action": "pick"})
    assert r.status_code == 422
    assert "several locations (A1, A2)" in r.json()["detail"]
    scan(admin, label("L1", "261231", 4), action="pick", location_id=a2)
    assert stock(admin) == [("A1", "L1", None, 10), ("A2", "L1", None, 6)]


def test_pick_more_than_available_is_refused(admin: TestClient) -> None:
    a1 = loc(admin, "A1")
    scan(admin, label("L1", "261231", 10), location_id=a1)
    r = admin.post("/api/scans", json={"barcode": label("L1", "261231", 11), "action": "pick"})
    assert r.status_code == 422
    assert "Only 10 in stock" in r.json()["detail"]
    assert stock(admin) == [("A1", "L1", None, 10)]


def test_pick_from_wrong_location_says_where_it_is(admin: TestClient) -> None:
    a1, b1 = loc(admin, "A1"), loc(admin, "B1")
    scan(admin, label("L1", "261231", 10), location_id=a1)
    r = admin.post(
        "/api/scans",
        json={"barcode": label("L1", "261231", 1), "action": "pick", "location_id": b1},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Not in stock at B1. Found at: A1."


def test_pick_unknown_item(admin: TestClient) -> None:
    r = admin.post("/api/scans", json={"barcode": label("L1", "261231", 1), "action": "pick"})
    assert r.status_code == 422
    assert r.json()["detail"] == "Not in stock."


# --- move ---


def test_move_whole_pallet_by_sscc(admin: TestClient) -> None:
    dock, a1 = loc(admin, "DOCK"), loc(admin, "A1")
    scan(admin, label("L1", "261231", 24, sscc=SSCC), location_id=dock)
    # Only the SSCC is needed to move the pallet, and no source location.
    s = scan(admin, f"(00){SSCC}", action="move", to_location_id=a1)
    assert [(m["location"]["code"], m["quantity"]) for m in s["movements"]] == [
        ("DOCK", -24),
        ("A1", 24),
    ]
    assert s["location"]["code"] == "DOCK"  # where it came from
    assert (s["gtin"], s["lot"]) == (GTIN, "L1")  # filled in from the pallet
    assert stock(admin) == [("A1", "L1", SSCC, 24)]


def test_sscc_ignores_a_stale_source_location(admin: TestClient) -> None:
    dock, a1, a2 = loc(admin, "DOCK"), loc(admin, "A1"), loc(admin, "A2")
    scan(admin, label("L1", "261231", 24, sscc=SSCC), location_id=dock)
    s = scan(admin, f"(00){SSCC}", action="move", location_id=a1, to_location_id=a2)
    assert [m["location"]["code"] for m in s["movements"]] == ["DOCK", "A2"]


def test_move_part_of_a_location(admin: TestClient) -> None:
    a1, a2 = loc(admin, "A1"), loc(admin, "A2")
    scan(admin, label("L1", "261231", 10), location_id=a1)
    scan(admin, f"(01){GTIN}", action="move", location_id=a1, to_location_id=a2, quantity=3)
    assert stock(admin) == [("A1", "L1", None, 7), ("A2", "L1", None, 3)]


def test_move_errors(admin: TestClient) -> None:
    a1 = loc(admin, "A1")
    scan(admin, label("L1", "261231", 10), location_id=a1)
    r = admin.post("/api/scans", json={"barcode": label("L1", "261231"), "action": "move"})
    assert "destination" in r.json()["detail"]
    r = admin.post(
        "/api/scans",
        json={"barcode": label("L1", "261231"), "action": "move", "to_location_id": a1},
    )
    assert r.json()["detail"] == "This is already at A1."
    r = admin.post(
        "/api/scans",
        json={"barcode": label("L1", "261231"), "action": "move", "to_location_id": 999},
    )
    assert r.status_code == 422


# --- undo, adjust, history ---


def test_undoing_a_scan_reverts_stock(admin: TestClient) -> None:
    a1 = loc(admin, "A1")
    scan(admin, label("L1", "261231", 10), location_id=a1)
    pick = scan(admin, label("L1", "261231", 4), action="pick")
    assert stock(admin) == [("A1", "L1", None, 6)]
    assert admin.delete(f"/api/scans/{pick['id']}").status_code == 204
    assert stock(admin) == [("A1", "L1", None, 10)]


def test_adjust(admin: TestClient) -> None:
    a1 = loc(admin, "A1")
    scan(admin, label("L1", "261231", 10), location_id=a1)
    item = {"location_id": a1, "gtin": GTIN, "lot": "L1", "expiry_date": "2026-12-31"}
    r = admin.post("/api/stock/adjust", json={**item, "quantity": 7, "note": "2 damaged, 1 lost"})
    assert r.status_code == 200
    assert (r.json()["kind"], r.json()["quantity"]) == ("adjust", -3)
    assert stock(admin) == [("A1", "L1", None, 7)]
    # Setting the same quantity again changes nothing.
    r = admin.post("/api/stock/adjust", json={**item, "quantity": 7, "note": "recount"})
    assert r.json() is None
    # A note is required; quantities can't be negative.
    assert (
        admin.post("/api/stock/adjust", json={**item, "quantity": 1, "note": ""}).status_code == 422
    )
    assert (
        admin.post("/api/stock/adjust", json={**item, "quantity": -1, "note": "x"}).status_code
        == 422
    )
    # Adjusting to zero removes the row.
    admin.post("/api/stock/adjust", json={**item, "quantity": 0, "note": "written off"})
    assert stock(admin) == []


def test_operator_cannot_adjust(operator: TestClient) -> None:
    r = operator.post("/api/stock/adjust", json={"gtin": GTIN, "quantity": 1, "note": "x"})
    assert r.status_code == 403


def test_stock_filters(admin: TestClient) -> None:
    a1, a2 = loc(admin, "A1"), loc(admin, "B2")
    soon = (date.today() + timedelta(days=10)).strftime("%y%m%d")
    later = (date.today() + timedelta(days=100)).strftime("%y%m%d")
    scan(admin, label("SOON", soon, 1), location_id=a1, sku="ABC12")
    scan(admin, label("LATER", later, 2), location_id=a2)
    assert [r[1] for r in stock(admin, expires_within_days=30)] == ["SOON"]
    assert [r[1] for r in stock(admin, location_id=a2)] == ["LATER"]
    assert [r[1] for r in stock(admin, q="b2")] == ["LATER"]
    assert len(stock(admin, q="abc12")) == 2  # SKU search via the product's GTIN
    rows = admin.get("/api/stock").json()
    assert rows[0]["product"]["sku"] == "ABC12"


def test_movements_history_and_csv(admin: TestClient) -> None:
    a1 = loc(admin, "A1")
    scan(admin, label("L1", "261231", 10), location_id=a1)
    scan(admin, label("L1", "261231", 4), action="pick")
    page = admin.get("/api/movements", params={"gtin": GTIN, "location_id": a1}).json()
    assert page["total"] == 2
    assert [(m["kind"], m["quantity"]) for m in page["items"]] == [("pick", -4), ("receive", 10)]
    assert page["items"][0]["user"]["display_name"] == "Ada Admin"

    rows = list(csv.DictReader(io.StringIO(admin.get("/api/stock/export.csv").text)))
    assert [(r["location"], r["lot"], r["quantity"]) for r in rows] == [("A1", "L1", "6")]


# --- data migration ---


@pytest.mark.skipif(
    "TEST_DATABASE_URL" in __import__("os").environ, reason="uses its own SQLite database"
)
def test_migration_turns_existing_scans_into_stock(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        command.upgrade(migrate._config(conn), "0001")
        conn.execute(
            text(
                "INSERT INTO locations (id, code, warehouse, aisle, position, shelf, "
                "description, is_active, created_at) "
                "VALUES (1, 'A1', '', '', '', '', '', 1, '2025-01-01')"
            )
        )
        insert = text(
            "INSERT INTO scans (created_at, location_id, raw_barcode, gs1_hri, elements, "
            "warnings, gtin, lot, quantity, note) "
            "VALUES ('2025-01-01', :loc, '', '', '{}', '[]', :gtin, 'L1', :qty, '')"
        )
        conn.execute(insert, {"loc": 1, "gtin": GTIN, "qty": 24})
        conn.execute(insert, {"loc": 1, "gtin": None, "qty": 5})  # SSCC-only: no item
        conn.execute(insert, {"loc": None, "gtin": GTIN, "qty": None})  # no quantity
    migrate.upgrade(engine)
    with engine.connect() as conn:
        movements = conn.execute(
            text("SELECT scan_id, kind, location_id, quantity FROM movements")
        ).all()
        actions = conn.execute(text("SELECT action FROM scans ORDER BY id")).scalars().all()
    assert movements == [(1, "receive", 1, 24)]
    assert actions == ["receive", "log", "log"]


# --- expiry ---


def test_receiving_expired_or_expiring_stock_warns(admin: TestClient) -> None:
    yymmdd = lambda days: (date.today() + timedelta(days=days)).strftime("%y%m%d")  # noqa: E731
    expired = scan(admin, label("OLD", yymmdd(-3), 1))
    assert expired["warnings"][-1].startswith("Expired on ")
    soon = scan(admin, label("SOON", yymmdd(5), 1))
    assert soon["warnings"][-1].startswith("Expires in 5 days")
    fine = scan(admin, label("FINE", yymmdd(200), 1))
    assert fine["warnings"] == []

    summary = admin.get("/api/stock/expiry").json()
    assert summary == {
        "warning_days": 30,
        "expired_lines": 1,
        "expired_units": 1,
        "expiring_lines": 1,
        "expiring_units": 1,
    }


def test_expiry_warning_text() -> None:
    from gs1_scanner.server.stock import expiry_warning

    today = date(2026, 1, 10)
    assert expiry_warning(None, 30, today) is None
    assert expiry_warning(date(2026, 1, 9), 30, today) == "Expired on 2026-01-09."
    assert expiry_warning(date(2026, 1, 10), 30, today) == "Expires today."
    assert expiry_warning(date(2026, 1, 11), 30, today) == "Expires in 1 day (2026-01-11)."
    assert expiry_warning(date(2026, 3, 1), 30, today) is None


def test_retried_upload_is_saved_once(admin: TestClient) -> None:
    a1 = loc(admin, "A1")
    body = {"barcode": label("L1", "261231", 10), "location_id": a1, "client_ref": "dev1-0001"}
    first = admin.post("/api/scans", json=body)
    again = admin.post("/api/scans", json=body)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    assert stock(admin) == [("A1", "L1", None, 10)]
