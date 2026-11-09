from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.texts import top_line
from services.songs import top_songs, user_top

router = Router(name="top")


@router.message(Command("top"))
async def cmd_top(message: Message, session: AsyncSession) -> None:
    songs = await top_songs(session, 20)
    if not songs:
        await message.answer("Пока пусто. Оцени пару песен через /rate.")
        return
    lines = ["🏆 <b>Топ-20 песен</b>\n"]
    lines += [top_line(i, s, s.rating, s.matches) for i, s in enumerate(songs, 1)]
    lines.append("\n<i>(пред.)</i> — меньше 10 баттлов, рейтинг ещё уточняется.")
    await message.answer("\n".join(lines))


@router.message(Command("mytop"))
async def cmd_mytop(message: Message, session: AsyncSession) -> None:
    rows = await user_top(session, message.from_user.id, 20)
    if not rows:
        await message.answer("У тебя пока нет баттлов. Начни с /battle ⚔️")
        return
    lines = ["🎧 <b>Твой личный рейтинг</b>\n"]
    lines += [top_line(i, s, r.rating, r.matches) for i, (s, r) in enumerate(rows, 1)]
    lines.append("\n<i>Считается только по твоим голосам.</i>")
    await message.answer("\n".join(lines))
