"""scan client ref

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-05 19:22:34.556639

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('scans', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_ref', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_scans_client_ref', ['client_ref'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('scans', schema=None) as batch_op:
        batch_op.drop_index('ix_scans_client_ref')
        batch_op.drop_column('client_ref')
