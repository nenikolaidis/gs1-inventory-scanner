"""Server settings, read from environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from gs1_scanner import paths


def _env(name: str, default: str) -> str:
    """An environment variable; unset or empty means ``default``."""
    return os.environ.get(name, "").strip() or default


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name, "")
    return default if not value else value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # SQLAlchemy URL, e.g. sqlite:///path/scanner.db or postgresql+psycopg://user:pw@host/db
    database_url: str = field(
        default_factory=lambda: _env(
            "GS1_SCANNER_DATABASE_URL", f"sqlite:///{paths.data_dir() / 'scanner.db'}"
        )
    )
    # Set to true when the app is served over HTTPS.
    secure_cookies: bool = field(
        default_factory=lambda: _env_bool("GS1_SCANNER_SECURE_COOKIES", False)
    )
    session_days: int = field(default_factory=lambda: int(_env("GS1_SCANNER_SESSION_DAYS", "14")))
    # Which SKUs are accepted. Default: 1-40 letters, digits, '-', '_' or '.'.
    sku_pattern: str = field(
        default_factory=lambda: _env("GS1_SCANNER_SKU_PATTERN", r"[A-Za-z0-9._-]{1,40}")
    )

    # Stock expiring within this many days is flagged.
    expiry_warning_days: int = field(
        default_factory=lambda: int(_env("GS1_SCANNER_EXPIRY_WARNING_DAYS", "30"))
    )

    # Network label printer for ZPL, "host" or "host:port" (default port 9100).
    zebra_printer: str = field(default_factory=lambda: _env("GS1_SCANNER_ZEBRA_PRINTER", ""))
    # Thermal label printer resolution (dots per inch) and label size.
    label_dpi: int = field(default_factory=lambda: int(_env("GS1_SCANNER_LABEL_DPI", "203")))
    label_size: str = field(default_factory=lambda: _env("GS1_SCANNER_LABEL_SIZE", "4x6"))

    def __post_init__(self) -> None:
        re.compile(self.sku_pattern)  # fail at startup, not on first scan
        if self.label_dpi not in (203, 300, 600):
            raise ValueError("GS1_SCANNER_LABEL_DPI must be 203, 300 or 600.")
        if self.label_size not in ("4x6", "100x150"):
            raise ValueError("GS1_SCANNER_LABEL_SIZE must be 4x6 or 100x150.")
