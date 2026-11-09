import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker


class DbSessionMiddleware(BaseMiddleware):
    """Одна сессия/транзакция на апдейт: commit при успехе, rollback при исключении."""

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self.sessionmaker = sessionmaker

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.sessionmaker() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
            except Exception:
                await session.rollback()
                raise
            await session.commit()
            return result


WAKE_UP_TEXT = (
    "😺 <b>Мяу!</b> Судья-кот проснулся и включил комп.\n"
    "Пока он спал, ты успел написать — сейчас вынесу вердикт 👇"
)


class WakeUpMiddleware(BaseMiddleware):
    """Если сообщение пролежало в очереди Telegram (комп спал или был выключен),
    перед ответом кот сообщает, что проснулся. Один раз на чат за «пробуждение»."""

    def __init__(self, stale_after: float = 60.0, greet_cooldown: float = 600.0, clock=time.time) -> None:
        self.stale_after = stale_after  # сообщение старше — значит, бот его «проспал»
        self.greet_cooldown = greet_cooldown  # не приветствовать один чат чаще раза в 10 минут
        self._clock = clock
        self._greeted_at: dict[int, float] = {}

    def should_greet(self, chat_id: int, sent_at: float) -> bool:
        now = self._clock()
        if now - sent_at < self.stale_after:
            return False
        last = self._greeted_at.get(chat_id)
        if last is not None and now - last < self.greet_cooldown:
            return False
        self._greeted_at[chat_id] = now
        return True

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and self.should_greet(event.chat.id, event.date.timestamp()):
            try:
                await event.answer(WAKE_UP_TEXT)
            except Exception:  # приветствие не должно ломать основной ответ
                pass
        return await handler(event, data)
