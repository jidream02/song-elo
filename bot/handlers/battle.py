from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, User
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import battle_kb, next_battle_kb
from bot.texts import battle_text, song_title
from services.rate_limit import SlidingWindowLimiter
from services.songs import VoteStatus, get_offer_songs, get_or_create_user, pick_battle, record_vote

router = Router(name="battle")

NO_BATTLE = (
    "😴 Сейчас нет пар для баттла: либо в базе меньше двух песен, "
    "либо ты уже проголосовал за все пары сегодня.\n"
    "Добавь песен через /rate или возвращайся завтра."
)


async def _battle_message(session: AsyncSession, user: User, in_group: bool) -> tuple[str, object | None]:
    offer = await pick_battle(session, user.id)
    if offer is None:
        return NO_BATTLE, None
    a, b = await get_offer_songs(session, offer)
    text = battle_text(a, b)
    if in_group:  # в группе видно, чей это баттл — голосовать может только он
        text = f"👤 Баттл для {escape(user.first_name)}\n\n" + text
    return text, battle_kb(offer.id, a, b)


@router.message(Command("battle"))
async def cmd_battle(message: Message, session: AsyncSession) -> None:
    user = message.from_user
    await get_or_create_user(session, user.id, user.username)
    text, kb = await _battle_message(session, user, message.chat.type != "private")
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "battle:next")
async def cb_next(callback: CallbackQuery, session: AsyncSession) -> None:
    user = callback.from_user
    await get_or_create_user(session, user.id, user.username)
    text, kb = await _battle_message(session, user, callback.message.chat.type != "private")
    await callback.answer()
    await callback.message.answer(text, reply_markup=kb)


def _signed(x: float) -> str:
    return f"+{round(x)}" if x >= 0 else f"−{abs(round(x))}"


@router.callback_query(F.data.startswith("vote:"))
async def cb_vote(callback: CallbackQuery, session: AsyncSession, vote_limiter: SlidingWindowLimiter) -> None:
    try:
        _, offer_id, side = callback.data.split(":")
        offer_id = int(offer_id)
        if side not in ("a", "b"):
            raise ValueError
    except ValueError:
        await callback.answer()
        return

    user = callback.from_user
    if not vote_limiter.hit(user.id):
        await callback.answer(
            f"⏳ Слишком много баттлов подряд. Подожди {vote_limiter.retry_after(user.id)} с.", show_alert=True
        )
        return

    await get_or_create_user(session, user.id, user.username)
    result = await record_vote(session, user.id, offer_id, pick_a=(side == "a"))

    if result.status is VoteStatus.NOT_YOURS:
        await callback.answer("Это чужой баттл 🙂 Запусти свой: /battle", show_alert=True)
        return
    if result.status is VoteStatus.NOT_FOUND:
        await callback.answer("Этот баттл не найден.", show_alert=True)
        return
    if result.status is VoteStatus.ALREADY:
        await callback.answer("Ты уже голосовал за эту пару сегодня.", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    w, l = result.winner, result.loser
    text = (
        f"✅ Твой выбор: {song_title(w)}\n\n"
        f"🏆 {song_title(w)}: {round(w.rating)} ({_signed(result.winner_delta)})\n"
        f"💔 {song_title(l)}: {round(l.rating)} ({_signed(result.loser_delta)})"
    )
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=next_battle_kb())
