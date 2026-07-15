"""agent host + feishu bots tables

Revision ID: 0008_agent_host
Revises: 0007_tool_confirmations
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_agent_host"
down_revision = "0007_tool_confirmations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(200), nullable=False, server_default="新对话"),
        sa.Column("origin", sa.String(24), nullable=False, server_default="ui"),
        sa.Column("external_key", sa.String(200), nullable=True, unique=True),
        sa.Column("adapter", sa.String(40), nullable=False, server_default="claude"),
        sa.Column("adapter_session_id", sa.String(120), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="idle"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_agent_sessions_ws_updated", "agent_sessions", ["workspace_id", "updated_at"])

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_agent_messages_session_created", "agent_messages", ["session_id", "created_at"])

    op.create_table(
        "feishu_bots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False, server_default="Mibu 助手"),
        sa.Column("app_id", sa.String(120), nullable=False),
        sa.Column("app_secret", sa.String(200), nullable=False),
        sa.Column("capability", sa.String(24), nullable=False, server_default="editor"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(24), nullable=False, server_default="offline"),
        sa.Column("status_detail", sa.String(400), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("feishu_bots")
    op.drop_table("agent_messages")
    op.drop_table("agent_sessions")
