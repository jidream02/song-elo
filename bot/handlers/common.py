"""Общие куски хендлеров."""

import logging

import httpx
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Song
from services.songs import find_or_create_song
from services.spotify import SpotifyClient, SpotifyError

log = logging.getLogger(__name__)


async def lookup_song(message: Message, session: AsyncSession, spotify: SpotifyClient, query: str) -> Song | None:
    """Ищет песню и сам отвечает пользователю, если не вышло."""
    try:
        song = await find_or_create_song(session, spotify, query)
    except (SpotifyError, httpx.HTTPError):
        log.exception("Spotify недоступен")
        await message.answer("⚠️ Spotify сейчас не отвечает, попробуй чуть позже.")
        return None
    if song is None:
        await message.answer(f"🔍 Не нашёл песню по запросу «{query[:100]}». Попробуй «исполнитель — название».")
    return song
