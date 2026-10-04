from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from gs1_scanner.server import security
from gs1_scanner.server.app import create_app
from gs1_scanner.server.config import Settings
from gs1_scanner.server.db import Base, make_engine

ADMIN = {"username": "admin", "display_name": "Ada Admin", "password": "admin-password"}
OPERATOR = {"username": "op", "display_name": "Otto Operator", "password": "op-password"}


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "_N", 2**4)


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    """A client for a fresh app with an empty database and no one logged in.

    Uses SQLite, or the database in TEST_DATABASE_URL (e.g. PostgreSQL in CI),
    which is emptied after each test.
    """
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    app = create_app(Settings(database_url=url))
    try:
        with TestClient(app, headers={"X-Requested-With": "test"}) as client:
            yield client
    finally:
        if os.environ.get("TEST_DATABASE_URL"):
            engine = make_engine(url)
            with engine.begin() as conn:
                Base.metadata.drop_all(conn)
                conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
            engine.dispose()


@pytest.fixture
def admin(app_client: TestClient) -> TestClient:
    """Logged in as the admin created through first-run setup."""
    r = app_client.post("/api/auth/setup", json=ADMIN)
    assert r.status_code == 200, r.text
    return app_client


@pytest.fixture
def operator(admin: TestClient) -> TestClient:
    """Logged in as an operator (the admin account also exists)."""
    r = admin.post("/api/users", json={**OPERATOR, "role": "operator"})
    assert r.status_code == 201, r.text
    admin.post("/api/auth/logout")
    r = admin.post(
        "/api/auth/login",
        json={"username": OPERATOR["username"], "password": OPERATOR["password"]},
    )
    assert r.status_code == 200, r.text
    return admin
