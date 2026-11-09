"""Бизнес-логика: поиск/создание песен, стартовая оценка, баттлы, топы.
Хендлеры бота только вызывают эти функции и форматируют ответ."""

from __future__ import annotations

import enum
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BattleOffer, Song, User, UserSongRating, Vote
from services.elo import BASE_RATING, is_provisional, update_ratings
from services.llm_rater import LLMParseError, LLMRater, LLMRating
from services.spotify import SpotifyClient, TrackInfo

log = logging.getLogger(__name__)


# ---------- пользователи ----------

async def get_or_create_user(session: AsyncSession, user_id: int, username: str | None) -> User:
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id, username=username)
        session.add(user)
        await session.flush()
    elif user.username != username:
        user.username = username
    return user


# ---------- песни ----------

async def find_or_create_song(session: AsyncSession, spotify: SpotifyClient, query: str) -> Song | None:
    track = await spotify.search_track(query)
    if track is None:
        return None
    song = await session.scalar(select(Song).where(Song.spotify_id == track.spotify_id))
    if song is not None:
        return song
    song = Song(
        spotify_id=track.spotify_id,
        title=track.title,
        artist=track.artist,
        album=track.album,
        year=track.year,
        genre=track.genre,
        cover_url=track.cover_url,
        spotify_url=track.url,
        rating=BASE_RATING,
        matches=0,
        wins=0,
        in_pool=False,
    )
    # add() обязательно внутри savepoint: begin_nested() сначала сбрасывает в БД всё ожидающее,
    # и INSERT вне savepoint при конфликте сломал бы всю транзакцию.
    try:
        async with session.begin_nested():
            session.add(song)
            await session.flush()
    except IntegrityError:  # параллельный запрос успел создать ту же песню
        song = await session.scalar(select(Song).where(Song.spotify_id == track.spotify_id))
    return song


class RatingSource(enum.Enum):
    BATTLES = "battles"  # ≥ 10 матчей — рейтинг из баттлов
    LLM = "llm"  # стартовая оценка LLM (+ возможно немного баттлов)
    UNKNOWN = "unknown"  # LLM не знает песню, баттлов мало
    LLM_ERROR = "llm_error"  # API недоступно / ответ не распарсился
    NO_LLM = "no_llm"  # ключа Claude нет — рейтинг только из баттлов


@dataclass
class SongRating:
    song: Song
    source: RatingSource
    llm: LLMRating | None


def _track_of(song: Song) -> TrackInfo:
    return TrackInfo(
        spotify_id=song.spotify_id,
        title=song.title,
        artist=song.artist,
        album=song.album,
        year=song.year,
        genre=song.genre,
        cover_url=song.cover_url,
        url=song.spotify_url,
    )


def _llm_from_song(song: Song) -> LLMRating | None:
    p = song.llm_payload
    if not p:
        return None
    return LLMRating(
        criteria=p.get("criteria"),
        elo=p.get("elo"),
        model_elo=p.get("model_elo"),
        strengths=p.get("strengths") or [],
        weaknesses=p.get("weaknesses") or [],
        confidence=p.get("confidence") or 0.0,
    )


async def ensure_rating(
    session: AsyncSession, song: Song, rater: LLMRater | None, min_confidence: float
) -> SongRating:
    """Правило /rate: ≥ 10 баттлов → рейтинг баттлов; иначе — стартовая оценка LLM (кэшируется).
    rater=None — ИИ выключен (нет ключа): песня сразу идёт в баттлы со стартом 1500."""
    cached = _llm_from_song(song)
    if not is_provisional(song.matches):
        return SongRating(song, RatingSource.BATTLES, cached)

    if rater is None and song.llm_rated_at is None:
        song.in_pool = True
        return SongRating(song, RatingSource.NO_LLM, None)

    if song.llm_rated_at is None and rater is not None:
        try:
            llm = await rater.rate(_track_of(song))
        except LLMParseError as exc:
            log.warning("LLM вернула невалидный ответ для %s: %s", song.spotify_id, exc)
            return SongRating(song, RatingSource.LLM_ERROR, None)
        except Exception:  # сеть, лимиты API и т.п. — не роняем бота
            log.exception("Ошибка LLM для %s", song.spotify_id)
            return SongRating(song, RatingSource.LLM_ERROR, None)

        song.llm_payload = llm.to_dict()
        song.llm_elo = llm.elo
        song.llm_confidence = llm.confidence
        song.llm_model = rater.model
        song.llm_rated_at = datetime.now(timezone.utc)
        if llm.is_known(min_confidence):
            # Оценка LLM — только стартовая точка: ставим её, только пока не было баттлов.
            if song.matches == 0 and llm.elo is not None:
                song.rating = float(llm.elo)
            song.in_pool = True
        cached = llm

    if cached is not None and cached.is_known(min_confidence):
        return SongRating(song, RatingSource.LLM, cached)
    return SongRating(song, RatingSource.UNKNOWN, cached)


async def add_to_pool(session: AsyncSession, song_id: int) -> Song | None:
    song = await session.get(Song, song_id)
    if song is not None:
        song.in_pool = True
    return song


# ---------- баттлы ----------

def _pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _today():
    return datetime.now(timezone.utc).date()


async def pick_battle(session: AsyncSession, user_id: int, attempts: int = 15) -> BattleOffer | None:
    """Случайная пара из пула, за которую пользователь сегодня ещё не голосовал."""
    ids = list((await session.scalars(select(Song.id).where(Song.in_pool.is_(True)))).all())
    if len(ids) < 2:
        return None

    voted_today = {
        (low, high)
        for low, high in (
            await session.execute(
                select(Vote.song_low_id, Vote.song_high_id).where(
                    Vote.user_id == user_id, Vote.vote_day == _today()
                )
            )
        ).all()
    }
    total_pairs = len(ids) * (len(ids) - 1) // 2
    if len(voted_today) >= total_pairs:
        return None

    for _ in range(attempts):
        a, b = random.sample(ids, 2)
        if _pair(a, b) not in voted_today:
            break
    else:
        # Почти всё перепробовано — перебираем явно.
        free = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1 :] if _pair(a, b) not in voted_today]
        if not free:
            return None
        a, b = random.choice(free)

    offer = BattleOffer(user_id=user_id, song_a_id=a, song_b_id=b, resolved=False)
    session.add(offer)
    await session.flush()
    return offer


class VoteStatus(enum.Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    NOT_YOURS = "not_yours"  # в группе нажал чужую кнопку
    ALREADY = "already"  # оффер уже закрыт или за пару сегодня уже голосовали


@dataclass
class VoteResult:
    status: VoteStatus
    winner: Song | None = None
    loser: Song | None = None
    winner_delta: float = 0.0
    loser_delta: float = 0.0


async def _personal(session: AsyncSession, user_id: int, song_id: int) -> UserSongRating:
    row = await session.get(UserSongRating, (user_id, song_id), with_for_update=True)
    if row is None:
        row = UserSongRating(user_id=user_id, song_id=song_id, rating=BASE_RATING, matches=0, wins=0)
        session.add(row)
    return row


async def record_vote(session: AsyncSession, user_id: int, offer_id: int, pick_a: bool) -> VoteResult:
    offer = await session.scalar(
        select(BattleOffer).where(BattleOffer.id == offer_id).with_for_update()
    )
    if offer is None:
        return VoteResult(VoteStatus.NOT_FOUND)
    if offer.user_id != user_id:
        return VoteResult(VoteStatus.NOT_YOURS)
    if offer.resolved:
        return VoteResult(VoteStatus.ALREADY)

    winner_id, loser_id = (
        (offer.song_a_id, offer.song_b_id) if pick_a else (offer.song_b_id, offer.song_a_id)
    )
    low, high = _pair(winner_id, loser_id)
    offer.resolved = True

    try:
        async with session.begin_nested():
            session.add(
                Vote(user_id=user_id, song_low_id=low, song_high_id=high, winner_id=winner_id, vote_day=_today())
            )
            await session.flush()
    except IntegrityError:
        return VoteResult(VoteStatus.ALREADY)

    # Блокируем обе песни в фиксированном порядке, чтобы не было дедлоков и потерянных обновлений.
    songs = {
        s.id: s
        for s in (
            await session.scalars(select(Song).where(Song.id.in_([low, high])).order_by(Song.id).with_for_update())
        ).all()
    }
    if len(songs) != 2:
        return VoteResult(VoteStatus.NOT_FOUND)
    winner, loser = songs[winner_id], songs[loser_id]

    upd = update_ratings(winner.rating, loser.rating, 1.0, winner.matches, loser.matches)
    winner.rating, loser.rating = upd.new_a, upd.new_b
    winner.matches += 1
    loser.matches += 1
    winner.wins += 1

    # Личный рейтинг пользователя
    pw, pl = await _personal(session, user_id, winner_id), await _personal(session, user_id, loser_id)
    pupd = update_ratings(pw.rating, pl.rating, 1.0)  # K = 32
    pw.rating, pl.rating = pupd.new_a, pupd.new_b
    pw.matches += 1
    pl.matches += 1
    pw.wins += 1

    return VoteResult(VoteStatus.OK, winner, loser, upd.delta_a, upd.delta_b)


async def get_offer_songs(session: AsyncSession, offer: BattleOffer) -> tuple[Song, Song]:
    a = await session.get(Song, offer.song_a_id)
    b = await session.get(Song, offer.song_b_id)
    assert a is not None and b is not None
    return a, b


# ---------- топы ----------

async def top_songs(session: AsyncSession, limit: int = 20) -> list[Song]:
    return list(
        (
            await session.scalars(
                select(Song).where(Song.in_pool.is_(True)).order_by(Song.rating.desc()).limit(limit)
            )
        ).all()
    )


async def user_top(session: AsyncSession, user_id: int, limit: int = 20) -> list[tuple[Song, UserSongRating]]:
    rows = await session.execute(
        select(Song, UserSongRating)
        .join(UserSongRating, UserSongRating.song_id == Song.id)
        .where(UserSongRating.user_id == user_id, UserSongRating.matches > 0)
        .order_by(UserSongRating.rating.desc())
        .limit(limit)
    )
    return [(s, r) for s, r in rows.all()]


async def user_votes_count(session: AsyncSession, user_id: int) -> int:
    return await session.scalar(select(func.count()).select_from(Vote).where(Vote.user_id == user_id)) or 0
