from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.texts import HELP

router = Router(name="start")


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELP)
