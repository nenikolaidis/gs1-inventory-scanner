from __future__ import annotations

import re
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gs1_scanner.gs1 import parse_barcode
from gs1_scanner.labels import (
    FNC1,
    LabelData,
    LocationLabel,
    code128_zpl_data,
    label_zpl,
    location_labels_zpl,
)
from gs1_scanner.server import printing
from gs1_scanner.server.app import create_app
from gs1_scanner.server.config import Settings
from tests.server.conftest import ADMIN

PALLET = "(02)38033432662426(11)250319(10)0090167063(00)380334329001623191(37)000360"


# --- ZPL generation ---


def test_code128_zpl_uses_explicit_subsets_and_fnc1() -> None:
    data, modules = code128_zpl_data(f"{FNC1}10LOT1{FNC1}3712")
    # Start B, FNC1, "10LOT1", switch to C, FNC1, "37", "12".
    assert data == ">:>810LOT1>5>83712"
    assert modules == 14 * 11 + 2


def test_zpl_escapes_special_characters() -> None:
    data, _ = code128_zpl_data("A>B^C~D_E")
    assert data == ">:A>0B_5EC_7ED_5FE"


def test_label_zpl_structure() -> None:
    zpl = label_zpl(LabelData(parse_barcode(PALLET).elements, location="A1"), title="ABC12")
    assert zpl.startswith("^XA^CI28^PW812^LL1218") and zpl.endswith("^XZ\n")
    assert zpl.count("^BC") == 2  # 64 characters: split over two symbols
    assert all(int(n) >= 2 for n in re.findall(r"\^BY(\d)", zpl))  # bars >= 0.25 mm
    assert "Location: A1" in zpl
    assert "^FD(00)380334329001623191(37)000360^FS" in zpl  # human-readable line


def test_label_zpl_sizes_and_resolutions() -> None:
    elements = parse_barcode(PALLET).elements
    assert "^PW1200^LL1800" in label_zpl(LabelData(elements), dpi=300)
    assert "^PW799^LL1199" in label_zpl(LabelData(elements), size="100x150")


def test_location_labels_zpl() -> None:
    zpl = location_labels_zpl([LocationLabel("A1", "Dock"), LocationLabel("B-2")])
    assert zpl.count("^XA") == 2
    assert ">:A1^FS" in zpl and "^FDDock^FS" in zpl


# --- printing ---


class FakePrinter:
    """A TCP server that records what is sent to it, like a Zebra on port 9100."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.address = f"127.0.0.1:{self.sock.getsockname()[1]}"
        self.received: list[bytes] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                chunks = []
                while chunk := conn.recv(65536):
                    chunks.append(chunk)
                self.received.append(b"".join(chunks))

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def printer() -> Iterator[FakePrinter]:
    p = FakePrinter()
    yield p
    p.close()


def client_with(tmp_path: Path, **settings) -> TestClient:
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'p.db'}", **settings))
    client = TestClient(app, headers={"X-Requested-With": "t"})
    client.__enter__()
    client.post("/api/auth/setup", json=ADMIN)
    return client


def test_parse_address() -> None:
    assert printing.parse_address("zebra.local") == ("zebra.local", 9100)
    assert printing.parse_address("10.0.0.5:6101") == ("10.0.0.5", 6101)
    with pytest.raises(printing.PrintError):
        printing.parse_address("host:abc")


def test_print_scan_and_location_labels(tmp_path: Path, printer: FakePrinter) -> None:
    client = client_with(tmp_path, zebra_printer=printer.address)
    assert client.get("/api/config").json()["label_printer"] is True
    loc = client.post("/api/locations", json={"code": "A1"}).json()
    scan = client.post("/api/scans", json={"barcode": PALLET, "location_id": loc["id"]}).json()

    assert client.post(f"/api/scans/{scan['id']}/print").status_code == 204
    assert client.post("/api/locations/print", json={"ids": [loc["id"]]}).status_code == 204
    client.__exit__(None, None, None)
    printer.thread.join(timeout=0.5)
    assert len(printer.received) == 2
    assert printer.received[0].startswith(b"^XA") and b"Location: A1" in printer.received[0]
    assert b">:A1^FS" in printer.received[1]


def test_print_errors(tmp_path: Path) -> None:
    client = client_with(tmp_path)
    scan = client.post("/api/scans", json={"barcode": PALLET}).json()
    r = client.post(f"/api/scans/{scan['id']}/print")
    assert r.status_code == 409  # no printer set up

    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()  # nothing listens there now
    client.app.state.settings = Settings(
        database_url=client.app.state.settings.database_url, zebra_printer=f"127.0.0.1:{port}"
    )
    r = client.post(f"/api/scans/{scan['id']}/print")
    assert r.status_code == 502
    assert "Could not reach the label printer" in r.json()["detail"]
    client.__exit__(None, None, None)


def test_zpl_downloads(admin: TestClient) -> None:
    loc = admin.post("/api/locations", json={"code": "A1"}).json()
    scan = admin.post("/api/scans", json={"barcode": PALLET}).json()
    r = admin.get(f"/api/scans/{scan['id']}/label.zpl")
    assert r.status_code == 200 and r.text.startswith("^XA")
    r = admin.get("/api/locations/labels.zpl", params={"ids": str(loc["id"])})
    assert r.status_code == 200 and ">:A1" in r.text
