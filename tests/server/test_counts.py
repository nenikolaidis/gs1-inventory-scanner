from __future__ import annotations

from fastapi.testclient import TestClient

from tests.server.conftest import OPERATOR

GTIN = "03012345678902"
SSCC = "380334329001623191"


def setup_stock(client: TestClient) -> int:
    """A1 holds 10 of lot L1, 5 of lot L2, and a pallet of 24 (SSCC) of lot L3."""
    a1 = client.post("/api/locations", json={"code": "A1"}).json()["id"]
    for barcode in [
        f"(01){GTIN}(10)L1(37)10",
        f"(01){GTIN}(10)L2(37)5",
        f"(00){SSCC}(01){GTIN}(10)L3(37)24",
    ]:
        r = client.post("/api/scans", json={"barcode": barcode, "location_id": a1})
        assert r.status_code == 201, r.text
    return a1


def rows(count: dict) -> list[tuple]:
    return [(r["lot"], r["expected"], r["counted"], r["difference"]) for r in count["rows"]]


def stock(client: TestClient) -> list[tuple]:
    return [(r["lot"], r["quantity"]) for r in client.get("/api/stock").json()]


def test_count_and_apply(admin: TestClient) -> None:
    a1 = setup_stock(admin)
    count = admin.post("/api/counts", json={"location_id": a1}).json()
    assert count["status"] == "open"
    # Before anything is counted, everything is missing.
    assert rows(count) == [("L1", 10, 0, -10), ("L2", 5, 0, -5), ("L3", 24, 0, -24)]

    cid = count["id"]
    admin.post(f"/api/counts/{cid}/scan", json={"barcode": f"(01){GTIN}(10)L1", "quantity": 6})
    admin.post(f"/api/counts/{cid}/scan", json={"barcode": f"(01){GTIN}(10)L1", "quantity": 2})
    admin.post(f"/api/counts/{cid}/scan", json={"barcode": f"(00){SSCC}"})  # intact pallet
    admin.post(f"/api/counts/{cid}/scan", json={"barcode": f"(01){GTIN}(10)NEW(37)3"})
    count = admin.get(f"/api/counts/{cid}").json()
    assert rows(count) == [
        ("L1", 10, 8, -2),
        ("L2", 5, 0, -5),
        ("L3", 24, 24, 0),
        ("NEW", 0, 3, 3),
    ]

    applied = admin.post(f"/api/counts/{cid}/apply").json()
    assert applied["status"] == "applied"
    # The review keeps what was expected at the time.
    assert rows(applied) == rows(count)
    assert stock(admin) == [("L1", 8), ("L3", 24), ("NEW", 3)]

    adjustments = admin.get("/api/movements", params={"gtin": GTIN}).json()["items"]
    assert {(m["lot"], m["quantity"], m["note"]) for m in adjustments if m["kind"] == "adjust"} == {
        ("L1", -2, f"Stock count #{cid}"),
        ("L2", -5, f"Stock count #{cid}"),
        ("NEW", 3, f"Stock count #{cid}"),
    }
    entry = admin.get("/api/audit", params={"action": "count"}).json()["items"][0]
    assert entry["summary"] == f"Applied stock count #{cid} at A1: 3 correction(s)"

    # A closed count can't be changed.
    r = admin.post(f"/api/counts/{cid}/scan", json={"barcode": f"(01){GTIN}", "quantity": 1})
    assert r.status_code == 409


def test_one_open_count_per_location(admin: TestClient) -> None:
    a1 = setup_stock(admin)
    first = admin.post("/api/counts", json={"location_id": a1}).json()
    again = admin.post("/api/counts", json={"location_id": a1}).json()
    assert first["id"] == again["id"]
    assert [c["id"] for c in admin.get("/api/counts", params={"status": "open"}).json()] == [
        first["id"]
    ]


def test_edit_and_remove_lines(admin: TestClient) -> None:
    a1 = setup_stock(admin)
    cid = admin.post("/api/counts", json={"location_id": a1}).json()["id"]
    count = admin.post(
        f"/api/counts/{cid}/scan", json={"barcode": f"(01){GTIN}(10)L2", "quantity": 4}
    ).json()
    line_id = count["lines"][0]["id"]
    count = admin.patch(f"/api/counts/{cid}/lines/{line_id}", json={"quantity": 5}).json()
    assert ("L2", 5, 5, 0) in rows(count)
    count = admin.delete(f"/api/counts/{cid}/lines/{line_id}").json()
    assert count["lines"] == []


def test_count_scan_errors(admin: TestClient) -> None:
    a1 = setup_stock(admin)
    cid = admin.post("/api/counts", json={"location_id": a1}).json()["id"]
    r = admin.post(f"/api/counts/{cid}/scan", json={"barcode": f"(01){GTIN}(10)L1"})
    assert r.json()["detail"] == "Enter the counted quantity."
    r = admin.post(f"/api/counts/{cid}/scan", json={"barcode": "(00)380334329001623207"})
    assert "Unknown pallet" in r.json()["detail"]
    assert admin.post("/api/counts", json={"location_id": 999}).status_code == 422


def test_operators_count_but_admins_apply(admin: TestClient) -> None:
    a1 = setup_stock(admin)
    admin.post("/api/users", json={**OPERATOR, "role": "operator"})
    admin.post("/api/auth/logout")
    login = {"username": OPERATOR["username"], "password": OPERATOR["password"]}
    admin.post("/api/auth/login", json=login)
    op = admin

    cid = op.post("/api/counts", json={"location_id": a1}).json()["id"]
    r = op.post(f"/api/counts/{cid}/scan", json={"barcode": f"(01){GTIN}(10)L1", "quantity": 1})
    assert r.status_code == 200
    assert op.post(f"/api/counts/{cid}/apply").status_code == 403
    cancelled = op.post(f"/api/counts/{cid}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert stock(op) == [("L1", 10), ("L2", 5), ("L3", 24)]  # nothing changed
