"""knowledge base: kb_documents + kb_chunks (plan §6.9)

The FTS5 index (kb_chunks_fts) is created lazily by the KB domain layer with
CREATE VIRTUAL TABLE IF NOT EXISTS so test databases built via create_all get
it too — this migration only carries the ORM tables.

Revision ID: 0012_kb
Revises: 0011_asset_tags
Create Date: 2026-07-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_kb"
down_revision = "0011_asset_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kb_documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False, server_default="note"),
        sa.Column("source_ref", sa.String(600), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(24), nullable=False, server_default="ready"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_kb_documents_workspace_updated", "kb_documents", ["workspace_id", "updated_at"])
    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(64), sa.ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("idx_kb_chunks_document", "kb_chunks", ["document_id", "chunk_index"])


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kb_chunks_fts")
    op.drop_index("idx_kb_chunks_document", table_name="kb_chunks")
    op.drop_table("kb_chunks")
    op.drop_index("idx_kb_documents_workspace_updated", table_name="kb_documents")
    op.drop_table("kb_documents")
