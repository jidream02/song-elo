from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.texts import top_line
from services.elo import PROVISIONAL_MATCHES
from services.songs import top_songs, user_top

router = Router(name="top")


@router.message(Command("top"))
async def cmd_top(message: Message, session: AsyncSession) -> None:
    proven = await top_songs(session, 20, proven=True)
    pending = await top_songs(session, 10, proven=False)
    if not proven and not pending:
        await message.answer("Пока пусто. Оцени пару песен через /rate.")
        return
    lines = [f"🏆 <b>Проверено людьми</b> — {PROVISIONAL_MATCHES}+ баттлов\n"]
    if proven:
        lines += [top_line(i, s, s.rating, s.matches) for i, s in enumerate(proven, 1)]
    else:
        lines.append(f"<i>Пока ни одна песня не набрала {PROVISIONAL_MATCHES} баттлов — играйте в /battle!</i>")
    if pending:
        lines.append(f"\n🤖 <b>Мнение ИИ</b> — пока меньше {PROVISIONAL_MATCHES} баттлов, рейтинг уточняется\n")
        lines += [
            f"{top_line(i, s, s.rating, s.matches, medals=False, mark_provisional=False)}"
            f" · {s.matches}/{PROVISIONAL_MATCHES}"
            for i, s in enumerate(pending, 1)
        ]
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
