"""store chat proposal preview and request reference

Revision ID: fdc2a991e14a
Revises: 473b13b2d5b0
Create Date: 2026-11-22 02:30:44.060729
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'fdc2a991e14a'
down_revision: str | None = '473b13b2d5b0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('workflow_chat_messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_message_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('proposal_details', sa.JSON(), nullable=True))
        batch_op.create_foreign_key('fk_chat_request', 'workflow_chat_messages', ['user_message_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('workflow_chat_messages', schema=None) as batch_op:
        batch_op.drop_constraint('fk_chat_request', type_='foreignkey')
        batch_op.drop_column('proposal_details')
        batch_op.drop_column('user_message_id')
