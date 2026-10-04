"""Where the app keeps its data when no database URL is configured."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "gs1-scanner"


def data_dir() -> Path:
    """Per-user data directory, overridable with ``GS1_SCANNER_HOME``."""
    if override := os.environ.get("GS1_SCANNER_HOME"):
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_DIR_NAME
