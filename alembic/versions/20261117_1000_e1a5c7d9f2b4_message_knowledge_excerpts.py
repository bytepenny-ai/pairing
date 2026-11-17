"""add messages.knowledge_excerpts (Knowledge base excerpts kept with their message for the prompt cache)

Revision ID: e1a5c7d9f2b4
Revises: d9e4f6a8b0c3
"""

import sqlalchemy as sa

from alembic import op

revision = "e1a5c7d9f2b4"
down_revision = "d9e4f6a8b0c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("knowledge_excerpts", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("knowledge_excerpts")
