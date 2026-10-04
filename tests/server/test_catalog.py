from __future__ import annotations

from fastapi.testclient import TestClient


def test_products_crud(admin: TestClient) -> None:
    r = admin.post("/api/products", json={"sku": "ABC12", "gtin": "3012345678902", "name": "Box"})
    assert r.status_code == 201, r.text
    product = r.json()
    assert product["gtin"] == "03012345678902"  # GTIN-13 padded to 14 digits

    assert admin.post("/api/products", json={"sku": "ABC12"}).status_code == 409
    bad_check_digit = {"sku": "X1", "gtin": "03012345678901"}
    assert admin.post("/api/products", json=bad_check_digit).status_code == 422

    r = admin.patch(f"/api/products/{product['id']}", json={"name": " Big box "})
    assert r.json()["name"] == "Big box"
    assert [p["sku"] for p in admin.get("/api/products", params={"q": "big"}).json()] == ["ABC12"]

    assert admin.delete(f"/api/products/{product['id']}").status_code == 204
    assert admin.get("/api/products").json() == []


def test_product_with_scans_cannot_be_deleted(admin: TestClient) -> None:
    admin.post("/api/scans", json={"barcode": "(01)03012345678902", "sku": "ABC12"})
    product = admin.get("/api/products").json()[0]
    assert admin.delete(f"/api/products/{product['id']}").status_code == 409


def test_locations(admin: TestClient) -> None:
    r = admin.post("/api/locations", json={"code": "w1-a01", "warehouse": " W1 "})
    assert r.status_code == 201
    loc = r.json()
    assert (loc["code"], loc["warehouse"]) == ("W1-A01", "W1")

    assert admin.post("/api/locations", json={"code": "W1-A01"}).status_code == 409
    assert admin.post("/api/locations", json={"code": "has space"}).status_code == 422

    admin.patch(f"/api/locations/{loc['id']}", json={"is_active": False})
    assert admin.get("/api/locations").json() == []
    assert len(admin.get("/api/locations", params={"include_inactive": True}).json()) == 1


def test_location_labels_pdf(admin: TestClient) -> None:
    ids = [admin.post("/api/locations", json={"code": f"L{i}"}).json()["id"] for i in range(15)]
    r = admin.get("/api/locations/labels.pdf", params={"ids": ",".join(map(str, ids))})
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
    assert admin.get("/api/locations/labels.pdf", params={"ids": "999"}).status_code == 404
    assert admin.get("/api/locations/labels.pdf", params={"ids": "x"}).status_code == 422


def test_operator_can_read_but_not_edit_catalog(operator: TestClient) -> None:
    assert operator.get("/api/products").status_code == 200
    assert operator.get("/api/locations").status_code == 200
    assert operator.post("/api/products", json={"sku": "A"}).status_code == 403
    assert operator.post("/api/locations", json={"code": "A"}).status_code == 403
