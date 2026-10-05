from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from gs1_scanner.server import migrate
from gs1_scanner.server.db import Base


def test_migrations_match_the_models(tmp_path: Path) -> None:
    """Fails if a model changed without a migration (run `gs1-scanner db revision`)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    migrate.upgrade(engine)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
