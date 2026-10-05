from __future__ import annotations

from fastapi.testclient import TestClient

from gs1_scanner.server.app import create_app
from gs1_scanner.server.config import Settings
from tests.server.conftest import ADMIN, OPERATOR

GTIN = "03012345678902"


def entries(client: TestClient, **params) -> list[dict]:
    r = client.get("/api/audit", params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_setup_and_logins_are_logged(admin: TestClient) -> None:
    admin.post("/api/auth/logout")
    admin.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    admin.post("/api/auth/login", json={"username": "admin", "password": ADMIN["password"]})
    actions = [(e["action"], e["username"]) for e in entries(admin, action="auth")]
    assert actions == [
        ("auth.login", "admin"),
        ("auth.login_failed", "admin"),
        ("auth.setup", "admin"),
    ]


def test_catalog_changes_are_logged_with_what_changed(admin: TestClient) -> None:
    p = admin.post("/api/products", json={"sku": "ABC12", "gtin": GTIN, "name": "Box"}).json()
    admin.patch(f"/api/products/{p['id']}", json={"name": "Big box"})
    admin.patch(f"/api/products/{p['id']}", json={"name": "Big box"})  # no change: not logged
    admin.delete(f"/api/products/{p['id']}")
    log = entries(admin, action="product")
    assert [e["action"] for e in log] == ["product.delete", "product.update", "product.create"]
    assert log[1]["details"] == {"name": ["Box", "Big box"]}
    assert log[1]["summary"] == "Changed product ABC12: name"
    assert log[1]["entity_type"] == "product"

    loc = admin.post("/api/locations", json={"code": "A1"}).json()
    admin.patch(f"/api/locations/{loc['id']}", json={"is_active": False})
    assert entries(admin, action="location.update")[0]["details"] == {"is_active": [True, False]}


def test_user_changes_hide_passwords(admin: TestClient) -> None:
    u = admin.post("/api/users", json={**OPERATOR, "role": "operator"}).json()
    admin.patch(f"/api/users/{u['id']}", json={"role": "admin", "password": "another-password"})
    update = entries(admin, action="user.update")[0]
    assert update["details"] == {
        "role": ["operator", "admin"],
        "password": ["(hidden)", "(changed)"],
    }
    assert "another-password" not in str(entries(admin))


def test_scan_deletion_and_stock_corrections_are_logged(admin: TestClient) -> None:
    loc = admin.post("/api/locations", json={"code": "A1"}).json()
    barcode = f"(01){GTIN}(10)L1(37)10"
    s = admin.post("/api/scans", json={"barcode": barcode, "location_id": loc["id"]}).json()
    admin.post(
        "/api/stock/adjust",
        json={
            "location_id": loc["id"],
            "gtin": GTIN,
            "lot": "L1",
            "quantity": 8,
            "note": "damaged",
        },
    )
    admin.delete(f"/api/scans/{s['id']}")

    adjust, delete = entries(admin, action="stock")[0], entries(admin, action="scan")[0]
    assert adjust["summary"] == f"Set {GTIN} lot L1 at A1 to 8 (-2): damaged"
    assert adjust["details"] == {"quantity": [10, 8]}
    assert delete["summary"].startswith(f"Deleted scan #{s['id']} (receive ")
    assert "reverting +10 at A1" in delete["summary"]
    assert delete["details"]["movements"] == [["A1", 10]]


def test_search_and_permissions(admin: TestClient) -> None:
    admin.post("/api/products", json={"sku": "ABC12"})
    assert [e["action"] for e in entries(admin, q="abc12")] == ["product.create"]
    admin.post("/api/users", json={**OPERATOR, "role": "operator"})
    admin.post("/api/auth/logout")
    login = {"username": OPERATOR["username"], "password": OPERATOR["password"]}
    admin.post("/api/auth/login", json=login)
    assert admin.get("/api/audit").status_code == 403


def test_login_limit_survives_a_restart(admin: TestClient) -> None:
    admin.post("/api/auth/logout")
    for _ in range(10):
        admin.post("/api/auth/login", json={"username": "admin", "password": "nope-nope"})
    # A second server process (or a restart) on the same database still blocks.
    url = admin.app.state.settings.database_url
    with TestClient(create_app(Settings(database_url=url)), headers={"X-Requested-With": "t"}) as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN["password"]})
        assert r.status_code == 429
