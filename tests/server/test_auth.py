from __future__ import annotations

from fastapi.testclient import TestClient

from tests.server.conftest import ADMIN, OPERATOR


def test_first_run_setup(app_client: TestClient) -> None:
    assert app_client.get("/api/auth/setup").json() == {"needs_setup": True}
    assert app_client.get("/api/auth/me").status_code == 401

    r = app_client.post("/api/auth/setup", json=ADMIN)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    assert app_client.get("/api/auth/me").json()["username"] == "admin"

    assert app_client.get("/api/auth/setup").json() == {"needs_setup": False}
    assert app_client.post("/api/auth/setup", json=ADMIN).status_code == 409


def test_setup_rejects_short_password(app_client: TestClient) -> None:
    r = app_client.post("/api/auth/setup", json={**ADMIN, "password": "short"})
    assert r.status_code == 422


def test_login_logout(admin: TestClient) -> None:
    admin.post("/api/auth/logout")
    assert admin.get("/api/auth/me").status_code == 401

    bad = admin.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    assert bad.status_code == 401
    ok = admin.post("/api/auth/login", json={"username": " ADMIN ", "password": ADMIN["password"]})
    assert ok.status_code == 200
    assert admin.get("/api/auth/me").status_code == 200


def test_login_throttling(admin: TestClient) -> None:
    admin.post("/api/auth/logout")
    for _ in range(10):
        r = admin.post("/api/auth/login", json={"username": "admin", "password": "nope-nope"})
        assert r.status_code == 401
    r = admin.post("/api/auth/login", json={"username": "admin", "password": ADMIN["password"]})
    assert r.status_code == 429


def test_csrf_header_required(admin: TestClient) -> None:
    r = admin.post("/api/auth/logout", headers={"X-Requested-With": ""})
    assert r.status_code == 403
    assert admin.get("/api/auth/me").status_code == 200  # GETs don't need it


def test_session_cookie_flags(app_client: TestClient) -> None:
    r = app_client.post("/api/auth/setup", json=ADMIN)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_change_password(admin: TestClient) -> None:
    r = admin.post(
        "/api/auth/password",
        json={"current_password": "wrong", "new_password": "new-password"},
    )
    assert r.status_code == 400
    r = admin.post(
        "/api/auth/password",
        json={"current_password": ADMIN["password"], "new_password": "new-password"},
    )
    assert r.status_code == 204
    admin.post("/api/auth/logout")
    r = admin.post("/api/auth/login", json={"username": "admin", "password": "new-password"})
    assert r.status_code == 200


def test_operator_cannot_manage_users(operator: TestClient) -> None:
    assert operator.get("/api/users").status_code == 403
    r = operator.post("/api/users", json={**OPERATOR, "username": "x", "role": "admin"})
    assert r.status_code == 403


def test_admin_manages_users(admin: TestClient) -> None:
    r = admin.post("/api/users", json={**OPERATOR, "role": "operator"})
    assert r.status_code == 201
    op_id = r.json()["id"]
    assert admin.post("/api/users", json=OPERATOR).status_code == 409
    assert [u["username"] for u in admin.get("/api/users").json()] == ["admin", "op"]

    r = admin.patch(f"/api/users/{op_id}", json={"is_active": False})
    assert r.json()["is_active"] is False
    admin.post("/api/auth/logout")
    login = {"username": "op", "password": OPERATOR["password"]}
    assert admin.post("/api/auth/login", json=login).status_code == 401


def test_admin_cannot_lock_themselves_out(admin: TestClient) -> None:
    me = admin.get("/api/auth/me").json()
    assert admin.patch(f"/api/users/{me['id']}", json={"is_active": False}).status_code == 400
    assert admin.patch(f"/api/users/{me['id']}", json={"role": "operator"}).status_code == 400
