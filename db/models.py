from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from services.elo import BASE_RATING


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user id
    username: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Song(Base):
    __tablename__ = "songs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spotify_id: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    artist: Mapped[str] = mapped_column(String(300))
    album: Mapped[str | None] = mapped_column(String(300))
    year: Mapped[int | None] = mapped_column(Integer)
    genre: Mapped[str | None] = mapped_column(String(200))
    cover_url: Mapped[str | None] = mapped_column(String(500))
    spotify_url: Mapped[str | None] = mapped_column(String(500))

    rating: Mapped[float] = mapped_column(Float, default=BASE_RATING, index=True)
    matches: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    in_pool: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # участвует в баттлах

    # Стартовая оценка от LLM (кэшируется, чтобы не платить за повторный /rate)
    llm_elo: Mapped[int | None] = mapped_column(Integer)
    llm_confidence: Mapped[float | None] = mapped_column(Float)
    llm_model: Mapped[str | None] = mapped_column(String(100))
    llm_payload: Mapped[dict | None] = mapped_column(JSON)
    llm_rated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Кто запросил ИИ-оценку — для дневного лимита на человека и статистики «кто что добавил»
    llm_requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BattleOffer(Base):
    """Выданная пользователю пара. В callback-кнопке только id оффера —
    подделать произвольную пару или проголосовать дважды нельзя."""

    __tablename__ = "battle_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    song_a_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"))
    song_b_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Vote(Base):
    """Один голос на пару песен от пользователя в сутки (UTC) — гарантируется уникальным индексом."""

    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("user_id", "song_low_id", "song_high_id", "vote_day", name="uq_vote_pair_day"),
        CheckConstraint("song_low_id < song_high_id", name="ck_vote_pair_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    song_low_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"))
    song_high_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"))
    winner_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"))
    vote_day: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSongRating(Base):
    """Личный Elo песни для конкретного пользователя — для /mytop."""

    __tablename__ = "user_song_ratings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True)
    rating: Mapped[float] = mapped_column(Float, default=BASE_RATING)
    matches: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
