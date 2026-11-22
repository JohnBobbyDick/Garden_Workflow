"""link recheck to fixed project archive

Revision ID: f0c925885a95
Revises: fdc2a991e14a
Create Date: 2026-11-22 08:16:36.291439
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'f0c925885a95'
down_revision: str | None = 'fdc2a991e14a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fixed_upload_id', sa.String(), nullable=True))
        batch_op.create_foreign_key('fk_run_fixed_upload', 'uploads', ['fixed_upload_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_constraint('fk_run_fixed_upload', type_='foreignkey')
        batch_op.drop_column('fixed_upload_id')
