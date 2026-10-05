"""Command-line interface: ``gs1-scanner <command>``."""

from __future__ import annotations

import argparse
import getpass
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from gs1_scanner import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gs1-scanner", description="GS1 Scanner server.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="run the web server")
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="address to listen on; use 0.0.0.0 so handhelds on the network can connect",
    )
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("create-user", help="create a user account")
    p.add_argument("username")
    p.add_argument("--display-name", default="")
    p.add_argument("--admin", action="store_true", help="give the user the admin role")
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser(
        "import-legacy", help="import records from the old desktop app's inventory.db"
    )
    p.add_argument("path", type=Path)
    p.set_defaults(func=cmd_import_legacy)

    p = sub.add_parser("db", help="database maintenance")
    db_sub = p.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("upgrade", help="apply pending migrations").set_defaults(func=cmd_db_upgrade)
    rev = db_sub.add_parser("revision", help="generate a migration from model changes (dev)")
    rev.add_argument("-m", "--message", required=True)
    rev.set_defaults(func=cmd_db_revision)

    args = parser.parse_args(argv)
    return args.func(args) or 0


def _settings_and_session():
    from gs1_scanner.server import migrate
    from gs1_scanner.server.config import Settings
    from gs1_scanner.server.db import make_engine, make_session_factory

    settings = Settings()
    engine = make_engine(settings.database_url)
    migrate.upgrade(engine)
    return settings, make_session_factory(engine)


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from gs1_scanner.server.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    from gs1_scanner.server.db import User
    from gs1_scanner.server.security import MIN_PASSWORD_LENGTH, hash_password

    _, session_factory = _settings_and_session()
    username = args.username.strip().lower()
    with session_factory() as db:
        if db.scalar(select(User).where(User.username == username)):
            print(f"User {username!r} already exists.", file=sys.stderr)
            return 1
        password = getpass.getpass("Password: ")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
            return 1
        if getpass.getpass("Repeat password: ") != password:
            print("Passwords don't match.", file=sys.stderr)
            return 1
        db.add(
            User(
                username=username,
                display_name=args.display_name.strip() or username,
                password_hash=hash_password(password),
                role="admin" if args.admin else "operator",
            )
        )
        db.commit()
    print(f"Created {'admin' if args.admin else 'operator'} {username!r}.")
    return 0


LEGACY_NOTE = "Imported from desktop app, record #{}"


def cmd_import_legacy(args: argparse.Namespace) -> int:
    from gs1_scanner.server import stock
    from gs1_scanner.server.db import Location, Scan
    from gs1_scanner.server.scanning import LOCATION_CODE_RE, ScanError, create_scan

    if not args.path.is_file():
        print(f"No such file: {args.path}", file=sys.stderr)
        return 1
    # Read-only, so the old database is never modified.
    legacy = sqlite3.connect(f"file:{args.path.resolve()}?mode=ro", uri=True)
    legacy.row_factory = sqlite3.Row
    rows = legacy.execute("SELECT * FROM inventory_records ORDER BY id").fetchall()
    legacy.close()

    settings, session_factory = _settings_and_session()
    imported = skipped = 0
    with session_factory() as db:
        for row in rows:
            note = LEGACY_NOTE.format(row["id"])
            if db.scalar(select(Scan.id).where(Scan.note == note)):
                skipped += 1
                continue
            parts = [(row[k] or "").strip() for k in ("warehouse", "aisle", "position", "shelf")]
            location_id = None
            if any(parts):
                code = re.sub(r"[^A-Z0-9._/-]+", "", "-".join(p for p in parts if p).upper())
                if LOCATION_CODE_RE.fullmatch(code):
                    location = db.scalar(select(Location).where(Location.code == code))
                    if location is None:
                        location = Location(
                            code=code,
                            warehouse=parts[0],
                            aisle=parts[1],
                            position=parts[2],
                            shelf=parts[3],
                        )
                        db.add(location)
                        db.flush()
                    location_id = location.id
            try:
                scan = create_scan(
                    db,
                    user=None,
                    barcode=row["raw_barcode"] or "",
                    sku_pattern=settings.sku_pattern,
                    location_id=location_id,
                    sku=row["sku"],
                    note=note,
                )
                # Records with an item and a quantity become stock; the rest are logged.
                in_stock = scan.gtin and scan.quantity and scan.quantity > 0
                stock.apply_scan(
                    db,
                    scan,
                    action="receive" if in_stock else "log",
                    user=None,
                    location=scan.location,
                    to_location=None,
                    quantity=scan.quantity,
                )
            except ScanError as e:
                print(f"Record #{row['id']}: skipped ({e})", file=sys.stderr)
                db.rollback()
                skipped += 1
                continue
            created = datetime.fromisoformat(row["created_at"])
            scan.created_at = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
            db.commit()
            imported += 1
    print(f"Imported {imported} record(s), skipped {skipped}.")
    return 0


def cmd_db_upgrade(_args: argparse.Namespace) -> int:
    _settings_and_session()
    print("Database is up to date.")
    return 0


def cmd_db_revision(args: argparse.Namespace) -> int:
    from gs1_scanner.server import migrate
    from gs1_scanner.server.config import Settings
    from gs1_scanner.server.db import make_engine

    engine = make_engine(Settings().database_url)
    migrate.upgrade(engine)
    migrate.make_revision(engine, args.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
