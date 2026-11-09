"""songs.llm_requested_by — кто запросил ИИ-оценку (дневной лимит на человека)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "songs",
        sa.Column("llm_requested_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_index("ix_songs_llm_requested_by_rated_at", "songs", ["llm_requested_by", "llm_rated_at"])


def downgrade() -> None:
    op.drop_index("ix_songs_llm_requested_by_rated_at", table_name="songs")
    op.drop_column("songs", "llm_requested_by")
