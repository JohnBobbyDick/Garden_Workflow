"""Add workspace custom nodes.

Revision ID: cd5457f8c8ee
Revises: 1d4df247396b
"""

import sqlalchemy as sa
from alembic import op

revision = "cd5457f8c8ee"
down_revision = "1d4df247396b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_nodes",
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(), primary_key=True),
        sa.UniqueConstraint("workspace_id", "name"),
    )


def downgrade() -> None:
    op.drop_table("custom_nodes")
