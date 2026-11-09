import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.config import get_settings
from bot.handlers import battle, compare, rate, start, top
from bot.middlewares import DbSessionMiddleware, WakeUpMiddleware
from db.session import make_engine, make_sessionmaker
from services.llm_rater import GeminiRater, LLMRater
from services.rate_limit import SlidingWindowLimiter
from services.spotify import SpotifyClient

COMMANDS = [
    BotCommand(command="rate", description="Оценить песню"),
    BotCommand(command="battle", description="Баттл двух песен"),
    BotCommand(command="top", description="Топ-20 песен"),
    BotCommand(command="mytop", description="Мой рейтинг"),
    BotCommand(command="compare", description="Кто победит: песня1 | песня2"),
    BotCommand(command="help", description="Помощь"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()

    engine = make_engine(settings.database_url)
    spotify = SpotifyClient(settings.spotify_client_id, settings.spotify_client_secret)
    gemini_key = settings.gemini_api_key.strip()
    claude_key = settings.anthropic_api_key.strip()
    if gemini_key:
        rater = GeminiRater(gemini_key, settings.gemini_model, settings.gemini_fallback_model)
    elif claude_key.startswith("sk-ant-"):
        rater = LLMRater(claude_key, settings.claude_model)
    else:
        rater = None
    if rater is None:
        logging.warning("Нет ключа LLM — ИИ-оценка выключена, рейтинг только из баттлов")
    else:
        logging.info("ИИ-оценка: %s", rater.model)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # Всё, что положено в dp[...], aiogram передаёт в хендлеры по имени параметра.
    dp = Dispatcher(
        settings=settings,
        spotify=spotify,
        rater=rater,
        vote_limiter=SlidingWindowLimiter(settings.battles_per_minute, 60),
        llm_limiter=SlidingWindowLimiter(settings.rates_per_minute, 60),
    )
    dp.update.middleware(DbSessionMiddleware(make_sessionmaker(engine)))
    # outer — срабатывает даже на сообщения без команды
    dp.message.outer_middleware(WakeUpMiddleware())
    dp.include_routers(start.router, rate.router, battle.router, top.router, compare.router)

    await bot.set_my_commands(COMMANDS)
    try:
        await dp.start_polling(bot)
    finally:
        await spotify.close()
        if rater is not None:
            await rater.close()
        await engine.dispose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
