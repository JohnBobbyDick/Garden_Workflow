"""track workflow version for chat proposals

Revision ID: 473b13b2d5b0
Revises: 79ba9cb909f1
Create Date: 2026-11-22 02:08:56.076918
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '473b13b2d5b0'
down_revision: str | None = '79ba9cb909f1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('workflow_chat_messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('base_version', sa.Integer(), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('workflow_chat_messages', schema=None) as batch_op:
        batch_op.drop_column('base_version')
