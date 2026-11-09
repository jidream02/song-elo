from aiogram import Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.handlers.common import lookup_song
from bot.texts import song_title
from services.elo import is_provisional, win_probability
from services.llm_rater import GeminiRater, LLMRater
from services.rate_limit import SlidingWindowLimiter
from services.songs import RatingSource, ensure_rating, get_or_create_user
from services.spotify import SpotifyClient

router = Router(name="compare")

USAGE = "Напиши так: <code>/compare Queen — Bohemian Rhapsody | Nirvana — Smells Like Teen Spirit</code>"


def _reliability(source: RatingSource, matches: int) -> str:
    if source is RatingSource.BATTLES:
        return f"по {matches} баттлам"
    if source is RatingSource.LLM:
        return "оценка ИИ" + (f" + {matches} баттлов" if matches else "")
    if matches:
        return f"по {matches} баттлам (пока мало)"
    return "⚠️ баттлов ещё не было, взято среднее 1500"


@router.message(Command("compare"))
async def cmd_compare(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    spotify: SpotifyClient,
    rater: "LLMRater | GeminiRater | None",
    settings: Settings,
    llm_limiter: SlidingWindowLimiter,
) -> None:
    parts = [p.strip() for p in (command.args or "").split("|")]
    if len(parts) != 2 or not all(parts):
        await message.answer(USAGE)
        return
    user = message.from_user
    if not llm_limiter.hit(user.id):
        await message.answer(f"⏳ Слишком часто. Подожди {llm_limiter.retry_after(user.id)} с.")
        return

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await get_or_create_user(session, user.id, user.username)
    a = await lookup_song(message, session, spotify, parts[0])
    if a is None:
        return
    b = await lookup_song(message, session, spotify, parts[1])
    if b is None:
        return
    if a.id == b.id:
        await message.answer("Это одна и та же песня 🙂 Шансы 50/50.")
        return

    ra = await ensure_rating(session, a, rater, settings.llm_min_confidence)
    rb = await ensure_rating(session, b, rater, settings.llm_min_confidence)
    p = win_probability(a.rating, b.rating)
    fav, pf = (a, p) if p >= 0.5 else (b, 1 - p)

    text = (
        "🔮 <b>Прогноз баттла</b>\n\n"
        f"🅰 {song_title(a)}\n   Elo {round(a.rating)} — {_reliability(ra.source, a.matches)}\n"
        f"🅱 {song_title(b)}\n   Elo {round(b.rating)} — {_reliability(rb.source, b.matches)}\n\n"
        f"Шанс победы: 🅰 <b>{p * 100:.1f}%</b> / 🅱 <b>{(1 - p) * 100:.1f}%</b>\n"
        f"Фаворит: {song_title(fav)} ({pf * 100:.0f}%)"
    )
    if is_provisional(a.matches) or is_provisional(b.matches):
        text += "\n\n<i>Рейтинг хотя бы одной песни ещё предварительный — прогноз неточный.</i>"
    await message.answer(text)
