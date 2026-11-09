from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.handlers.common import lookup_song
from bot.keyboards import to_pool_kb
from bot.texts import rating_card, song_title
from services.llm_rater import GeminiRater, LLMRater
from services.rate_limit import SlidingWindowLimiter
from services.songs import add_to_pool, ensure_rating, get_or_create_user
from services.spotify import SpotifyClient

router = Router(name="rate")

CAPTION_LIMIT = 1024


@router.message(Command("rate"))
async def cmd_rate(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    spotify: SpotifyClient,
    rater: "LLMRater | GeminiRater | None",
    settings: Settings,
    llm_limiter: SlidingWindowLimiter,
) -> None:
    query = (command.args or "").strip()
    if not query:
        await message.answer("Напиши так: <code>/rate Queen — Bohemian Rhapsody</code>")
        return
    user = message.from_user
    if not llm_limiter.hit(user.id):
        await message.answer(f"⏳ Слишком часто. Подожди {llm_limiter.retry_after(user.id)} с.")
        return

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await get_or_create_user(session, user.id, user.username)
    song = await lookup_song(message, session, spotify, query)
    if song is None:
        return

    result = await ensure_rating(session, song, rater, settings.llm_min_confidence)
    text = rating_card(result)
    kb = None if song.in_pool else to_pool_kb(song.id)

    if song.cover_url and len(text) <= CAPTION_LIMIT:
        await message.answer_photo(song.cover_url, caption=text, reply_markup=kb)
    else:
        if song.cover_url:
            await message.answer_photo(song.cover_url, caption=song_title(song))
        await message.answer(text, reply_markup=kb, link_preview_options=LinkPreviewOptions(is_disabled=True))


@router.callback_query(F.data.startswith("pool:"))
async def cb_to_pool(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        song_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    song = await add_to_pool(session, song_id)
    if song is None:
        await callback.answer("Песня не найдена", show_alert=True)
        return
    await callback.answer("Готово! Песня участвует в баттлах ⚔️", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=None)
