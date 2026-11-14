"""Knowledge-base folders: document_folders, and documents.folder_id (a label; files stay where they are on disk)

Revision ID: c8d3e5f7a9b2
Revises: b7d2f4a6c8e1
"""

import sqlalchemy as sa

from alembic import op
from app.models._base import Timestamp

revision = "c8d3e5f7a9b2"
down_revision = "b7d2f4a6c8e1"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "document_folders",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", Timestamp, nullable=True),
        sa.UniqueConstraint("owner_id", "name", name="uq_document_folders_owner_name"),
    )
    op.create_index("ix_document_folders_owner_id", "document_folders", ["owner_id"])
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("folder_id", sa.String(32), nullable=True))
        batch.create_foreign_key("fk_documents_folder_id", "document_folders", ["folder_id"], ["id"])
        batch.create_index("ix_documents_folder_id", ["folder_id"])


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_index("ix_documents_folder_id")
        batch.drop_constraint("fk_documents_folder_id", type_="foreignkey")
        batch.drop_column("folder_id")
    op.drop_index("ix_document_folders_owner_id", "document_folders")
    op.drop_table("document_folders")
