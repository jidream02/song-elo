"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "songs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("spotify_id", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("artist", sa.String(300), nullable=False),
        sa.Column("album", sa.String(300)),
        sa.Column("year", sa.Integer()),
        sa.Column("genre", sa.String(200)),
        sa.Column("cover_url", sa.String(500)),
        sa.Column("spotify_url", sa.String(500)),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("matches", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("in_pool", sa.Boolean(), nullable=False),
        sa.Column("llm_elo", sa.Integer()),
        sa.Column("llm_confidence", sa.Float()),
        sa.Column("llm_model", sa.String(100)),
        sa.Column("llm_payload", sa.JSON()),
        sa.Column("llm_rated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_songs_rating", "songs", ["rating"])
    op.create_index("ix_songs_in_pool", "songs", ["in_pool"])

    op.create_table(
        "battle_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("song_a_id", sa.Integer(), sa.ForeignKey("songs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("song_b_id", sa.Integer(), sa.ForeignKey("songs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_battle_offers_user_id", "battle_offers", ["user_id"])

    op.create_table(
        "votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("song_low_id", sa.Integer(), sa.ForeignKey("songs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("song_high_id", sa.Integer(), sa.ForeignKey("songs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("winner_id", sa.Integer(), sa.ForeignKey("songs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vote_day", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "song_low_id", "song_high_id", "vote_day", name="uq_vote_pair_day"),
        sa.CheckConstraint("song_low_id < song_high_id", name="ck_vote_pair_order"),
    )
    op.create_index("ix_votes_user_id", "votes", ["user_id"])

    op.create_table(
        "user_song_ratings",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("song_id", sa.Integer(), sa.ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("matches", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_song_ratings")
    op.drop_table("votes")
    op.drop_table("battle_offers")
    op.drop_table("songs")
    op.drop_table("users")
