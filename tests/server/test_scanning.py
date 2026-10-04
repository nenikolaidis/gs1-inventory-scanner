from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from gs1_scanner.server.db import Scan
from tests.server.conftest import OPERATOR

GTIN = "03012345678902"
PALLET = f"(01){GTIN}(17)261231(10)LOT1(37)24"
SSCC_PALLET = "(00)380334329001623191(02)38033432662426(37)360"


def make_location(client: TestClient, code: str = "W1-A01-S1", **extra) -> dict:
    r = client.post("/api/locations", json={"code": code, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_resolve(admin: TestClient) -> None:
    loc = make_location(admin, "w1-a01-s1", warehouse="W1")
    assert loc["code"] == "W1-A01-S1"

    r = admin.post("/api/resolve", json={"text": " w1-a01-s1 "}).json()
    assert r["kind"] == "location"
    assert r["location"]["id"] == loc["id"]

    r = admin.post("/api/resolve", json={"text": PALLET}).json()
    assert r["kind"] == "gs1"
    assert r["product"] is None
    assert [e["ai"] for e in r["parse"]["elements"]] == ["01", "17", "10", "37"]
    assert r["parse"]["elements"][1]["title"] == "USE BY or EXPIRY"

    r = admin.post("/api/resolve", json={"text": "hello"}).json()
    assert r["kind"] == "unknown"
    assert r["parse"]["warnings"]


def test_save_scan_extracts_fields(operator: TestClient) -> None:
    r = operator.post("/api/scans", json={"barcode": PALLET})
    assert r.status_code == 201, r.text
    scan = r.json()
    assert scan["gtin"] == GTIN
    assert scan["lot"] == "LOT1"
    assert scan["quantity"] == 24
    assert scan["expiry_date"] == "2026-12-31"
    assert scan["user"]["display_name"] == "Otto Operator"
    assert scan["location"] is None
    assert scan["gs1_hri"] == PALLET


def test_scan_with_location_and_quantity_override(admin: TestClient) -> None:
    loc = make_location(admin)
    r = admin.post(
        "/api/scans",
        json={"barcode": SSCC_PALLET, "location_id": loc["id"], "quantity": 300, "note": " ok "},
    )
    scan = r.json()
    assert scan["location"]["code"] == "W1-A01-S1"
    assert scan["sscc"] == "380334329001623191"
    assert scan["gtin"] == "38033432662426"  # from AI 02 when there is no AI 01
    assert scan["quantity"] == 300
    assert scan["note"] == "ok"


def test_scan_errors(admin: TestClient) -> None:
    assert admin.post("/api/scans", json={"barcode": "hello"}).status_code == 422
    r = admin.post("/api/scans", json={"barcode": PALLET, "location_id": 999})
    assert r.status_code == 422
    loc = make_location(admin)
    admin.patch(f"/api/locations/{loc['id']}", json={"is_active": False})
    r = admin.post("/api/scans", json={"barcode": PALLET, "location_id": loc["id"]})
    assert r.status_code == 422
    r = admin.post("/api/scans", json={"barcode": PALLET, "quantity": -1})
    assert r.status_code == 422


def test_sku_is_learned_from_first_scan(admin: TestClient) -> None:
    r = admin.post("/api/scans", json={"barcode": PALLET, "sku": "ABC12"})
    assert r.json()["sku"] == "ABC12"

    products = admin.get("/api/products").json()
    assert [(p["sku"], p["gtin"]) for p in products] == [("ABC12", GTIN)]

    # Next scan of the same GTIN: the product is found without typing the SKU.
    r = admin.post("/api/resolve", json={"text": PALLET}).json()
    assert r["product"]["sku"] == "ABC12"
    assert admin.post("/api/scans", json={"barcode": PALLET}).json()["sku"] == "ABC12"

    # A conflicting SKU for a known GTIN is refused.
    r = admin.post("/api/scans", json={"barcode": PALLET, "sku": "OTHER"})
    assert r.status_code == 422
    assert "belongs to SKU ABC12" in r.json()["detail"]


def test_sku_pattern_is_enforced(admin: TestClient) -> None:
    r = admin.post("/api/scans", json={"barcode": PALLET, "sku": "has space"})
    assert r.status_code == 422


def test_list_search_and_delete(admin: TestClient) -> None:
    loc = make_location(admin, "DOCK-1")
    first = admin.post("/api/scans", json={"barcode": PALLET}).json()
    admin.post("/api/scans", json={"barcode": SSCC_PALLET, "location_id": loc["id"]})

    page = admin.get("/api/scans").json()
    assert page["total"] == 2
    assert page["items"][0]["sscc"] == "380334329001623191"  # newest first

    assert admin.get("/api/scans", params={"q": "lot1"}).json()["total"] == 1
    assert admin.get("/api/scans", params={"q": "dock"}).json()["total"] == 1
    assert admin.get("/api/scans", params={"location_id": loc["id"]}).json()["total"] == 1
    assert admin.get("/api/scans", params={"q": "%"}).json()["total"] == 0
    assert admin.get("/api/scans", params={"limit": 1}).json()["total"] == 2

    assert admin.get(f"/api/scans/{first['id']}").json()["lot"] == "LOT1"
    assert admin.delete(f"/api/scans/{first['id']}").status_code == 204
    assert admin.get(f"/api/scans/{first['id']}").status_code == 404


def test_operator_can_undo_only_own_recent_scans(admin: TestClient) -> None:
    admins_scan = admin.post("/api/scans", json={"barcode": PALLET}).json()
    admin.post("/api/users", json={**OPERATOR, "role": "operator"})
    admin.post("/api/auth/logout")
    login = {"username": OPERATOR["username"], "password": OPERATOR["password"]}
    assert admin.post("/api/auth/login", json=login).status_code == 200
    operator = admin

    assert operator.delete(f"/api/scans/{admins_scan['id']}").status_code == 403
    own = operator.post("/api/scans", json={"barcode": PALLET}).json()
    old = operator.post("/api/scans", json={"barcode": PALLET}).json()

    app = operator.app
    with app.state.session_factory() as db:
        scan = db.get(Scan, old["id"])
        scan.created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
        db.commit()

    assert operator.delete(f"/api/scans/{own['id']}").status_code == 204
    assert operator.delete(f"/api/scans/{old['id']}").status_code == 403


def test_csv_export(admin: TestClient) -> None:
    admin.post("/api/scans", json={"barcode": PALLET, "note": "=HYPERLINK(1)"})
    r = admin.get("/api/scans/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 1
    assert rows[0]["gtin"] == GTIN
    assert rows[0]["expiry_date"] == "2026-12-31"
    assert rows[0]["note"] == "'=HYPERLINK(1)"  # formula injection neutralised


def test_scan_label_pdf(admin: TestClient) -> None:
    scan = admin.post("/api/scans", json={"barcode": PALLET}).json()
    r = admin.get(f"/api/scans/{scan['id']}/label.pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


def test_requires_login(app_client: TestClient) -> None:
    for method, url in [
        ("get", "/api/scans"),
        ("post", "/api/scans"),
        ("post", "/api/resolve"),
        ("get", "/api/products"),
        ("get", "/api/locations"),
        ("get", "/api/scans/export.csv"),
    ]:
        assert getattr(app_client, method)(url).status_code in (401, 422), url
    assert app_client.post("/api/resolve", json={"text": "x"}).status_code == 401
