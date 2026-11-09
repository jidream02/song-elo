import asyncio
import json

import pytest

from db.models import Base, User
from db.session import make_engine, make_sessionmaker
from services.llm_rater import CRITERIA, parse_llm_response
from services.songs import RatingSource, ensure_rating, find_or_create_song
from services.spotify import TrackInfo


class FakeSpotify:
    async def search_track(self, q):
        return TrackInfo(q, q, "Artist", None, 2020, None, None, None)


class FakeRater:
    model = "fake"

    def __init__(self):
        self.calls = 0

    async def rate(self, track):
        self.calls += 1
        return parse_llm_response(
            json.dumps({"criteria": {k: 6 for k in CRITERIA}, "elo": 1640, "confidence": 0.9})
        )


async def _scenario(limit):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = make_sessionmaker(engine)
    rater, spotify = FakeRater(), FakeSpotify()
    results = []
    async with sm() as s:
        s.add_all([User(id=1), User(id=2)])
        await s.flush()

        async def rate(user_id, query):
            song = await find_or_create_song(s, spotify, query)
            return await ensure_rating(s, song, rater, 0.4, user_id, limit)

        for i in range(limit + 1):
            results.append(await rate(1, f"song-{i}"))
        # уже оценённая песня — лимит не тратит и доступна даже тому, кто лимит исчерпал
        again = await rate(1, "song-0")
        # у другого человека свой лимит
        other = await rate(2, "other-song")
    await engine.dispose()
    return results, again, other, rater.calls


def test_daily_limit_per_user():
    results, again, other, calls = asyncio.run(_scenario(limit=3))
    assert [r.source for r in results[:3]] == [RatingSource.LLM] * 3
    assert results[3].source is RatingSource.DAILY_LIMIT
    assert results[3].retry_at is not None and results[3].daily_limit == 3
    assert again.source is RatingSource.LLM
    assert other.source is RatingSource.LLM
    assert calls == 4  # 3 оценки первого + 1 второго; заблокированная и повторная — без запроса к ИИ
