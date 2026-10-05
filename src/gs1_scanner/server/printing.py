"""Sending labels straight to a network label printer (Zebra and compatibles)."""

from __future__ import annotations

import socket

DEFAULT_PORT = 9100  # "raw" printing port used by Zebra and most label printers


class PrintError(Exception):
    pass


def parse_address(address: str) -> tuple[str, int]:
    host, _, port = address.strip().rpartition(":") if ":" in address else (address, "", "")
    host = host.strip("[]") or address.strip()
    try:
        return host, int(port) if port else DEFAULT_PORT
    except ValueError as e:
        raise PrintError(f"Invalid printer address {address!r}.") from e


def send_raw(address: str, data: bytes, timeout: float = 5.0) -> None:
    host, port = parse_address(address)
    try:
        with socket.create_connection((host, port), timeout=timeout) as conn:
            conn.sendall(data)
    except OSError as e:
        raise PrintError(f"Could not reach the label printer at {host}:{port} ({e}).") from e
