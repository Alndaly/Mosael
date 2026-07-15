"""transcript tables

Revision ID: 0003_transcripts
Revises: 0002_operation_history
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_transcripts"
down_revision = "0002_operation_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transcripts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.String(64), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language", sa.String(24), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="ready"),
        sa.Column("source", sa.String(40), nullable=False, server_default="imported"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_transcripts_asset", "transcripts", ["asset_id"])

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("transcript_id", sa.String(64), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("speaker", sa.String(80), nullable=True),
    )
    op.create_index("idx_transcript_segments_transcript_start", "transcript_segments", ["transcript_id", "start_time"])

    op.create_table(
        "transcript_tokens",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("segment_id", sa.String(64), sa.ForeignKey("transcript_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_index", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("text", sa.String(120), nullable=False),
    )
    op.create_index("idx_transcript_tokens_segment_index", "transcript_tokens", ["segment_id", "token_index"])

    op.create_table(
        "clip_transcript_refs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("clip_id", sa.String(64), sa.ForeignKey("clips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", sa.String(64), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", sa.String(64), sa.ForeignKey("transcript_segments.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("idx_clip_transcript_refs_clip", "clip_transcript_refs", ["clip_id"])


def downgrade() -> None:
    op.drop_table("clip_transcript_refs")
    op.drop_table("transcript_tokens")
    op.drop_table("transcript_segments")
    op.drop_table("transcripts")
