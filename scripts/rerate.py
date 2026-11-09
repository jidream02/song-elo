"""Переоценка всех песен текущей моделью/промптом — чтобы все были на одной шкале.

Запуск (в Docker):  docker compose run --rm bot python -m scripts.rerate
Только песни без баттлов:  ... python -m scripts.rerate --only-new

Правила:
- 0 баттлов → рейтинг = новая оценка ИИ;
- баттлы были и старая оценка ИИ была → рейтинг сдвигается на (новая − старая): голоса людей сохраняются;
- модель песню теперь не знает → у песен без баттлов рейтинг = 1500.
"""

import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from bot.config import get_settings
from db.models import Song
from db.session import make_engine, make_sessionmaker
from services.elo import BASE_RATING
from services.llm_rater import GeminiRater
from services.songs import _track_of


async def rate_with_retries(rater: GeminiRater, song: Song, tries: int = 5):
    for attempt in range(tries):
        try:
            return await rater.rate(_track_of(song))
        except Exception as exc:  # 503/429/таймаут/кривой JSON — ждём и пробуем снова
            wait = 10 * (attempt + 1)
            print(f"   ! {type(exc).__name__}: {str(exc)[:60]!r}, повтор через {wait} с")
            await asyncio.sleep(wait)
    return None


async def main() -> None:
    only_new = "--only-new" in sys.argv
    settings = get_settings()
    engine = make_engine(settings.database_url)
    sm = make_sessionmaker(engine)
    # Без запасной модели: вся переоценка — одной моделью, иначе шкала снова перемешается.
    rater = GeminiRater(settings.gemini_api_key, settings.gemini_model, None, timeout=60)

    async with sm() as session:
        q = select(Song.id).order_by(Song.id)
        if only_new:
            q = q.where(Song.matches == 0)
        ids = list((await session.scalars(q)).all())
    print(f"Песен к переоценке: {len(ids)} (модель {settings.gemini_model})\n")

    done = failed = 0
    for song_id in ids:
        async with sm() as session:
            song = await session.get(Song, song_id)
            llm = await rate_with_retries(rater, song)
            if llm is None:
                failed += 1
                print(f"✗ {song.artist} — {song.title}: не удалось, пропускаю")
                continue
            # Блокируем строку только на время записи, чтобы не мешать баттлам
            song = await session.get(Song, song_id, with_for_update=True, populate_existing=True)
            old_rating, old_llm = song.rating, song.llm_elo
            known = llm.is_known(settings.llm_min_confidence)

            if known and song.matches == 0:
                song.rating = float(llm.elo)
            elif known and old_llm is not None:
                song.rating += llm.elo - old_llm
            elif not known and song.matches == 0:
                song.rating = BASE_RATING
            if known:
                song.in_pool = True

            song.llm_payload = llm.to_dict()
            song.llm_elo = llm.elo
            song.llm_confidence = llm.confidence
            song.llm_model = llm.model
            song.llm_rated_at = song.llm_rated_at or datetime.now(timezone.utc)  # не трогаем дневной лимит
            await session.commit()
            done += 1
            status = f"{round(old_rating)} → {round(song.rating)}" if known else "не знаю"
            print(f"✓ {song.artist} — {song.title}: {status}  (баттлов {song.matches})")
        await asyncio.sleep(1.5)

    await rater.close()
    await engine.dispose()
    print(f"\nГотово: {done} переоценено, {failed} не удалось.")


if __name__ == "__main__":
    asyncio.run(main())
