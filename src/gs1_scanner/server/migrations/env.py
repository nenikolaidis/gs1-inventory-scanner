"""Alembic environment. Run through `gs1-scanner db ...`, not the alembic CLI."""

from alembic import context

from gs1_scanner.server.db import Base

config = context.config
connection = config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    render_as_batch=True,  # lets ALTER-style migrations work on SQLite
    compare_type=True,
)
with context.begin_transaction():
    context.run_migrations()
