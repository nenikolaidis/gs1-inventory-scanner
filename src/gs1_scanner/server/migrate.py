"""Database migrations (Alembic), driven from code so no alembic.ini is needed."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _config(connection) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection"] = connection
    return cfg


def upgrade(engine: Engine) -> None:
    """Bring the database schema up to date."""
    with engine.begin() as connection:
        command.upgrade(_config(connection), "head")


def make_revision(engine: Engine, message: str) -> None:
    """Generate a new migration from model changes (for developers)."""
    with engine.begin() as connection:
        command.revision(_config(connection), message=message, autogenerate=True)
