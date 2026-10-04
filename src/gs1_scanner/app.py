"""Command-line entry point: ``gs1-scanner`` or ``python -m gs1_scanner``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gs1_scanner import __version__, paths
from gs1_scanner.service import InventoryService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gs1-scanner", description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help=f"SQLite database file (default: {paths.default_db_path()})",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    try:
        from gs1_scanner.gui import run
    except ImportError as e:
        if "tkinter" not in str(e):
            raise
        print(
            "Tkinter is not available. On Debian/Ubuntu install python3-tk, "
            "on Fedora python3-tkinter.",
            file=sys.stderr,
        )
        return 1

    service = InventoryService(args.db or paths.default_db_path())
    try:
        run(service)
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
