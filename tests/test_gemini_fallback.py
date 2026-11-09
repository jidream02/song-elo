import asyncio
import json

import httpx
import pytest

from services.llm_rater import CRITERIA, GeminiRater
from services.spotify import TrackInfo

TRACK = TrackInfo("id", "Song", "Artist", None, 2020, None, None, None)
GOOD = {
    "candidates": [
        {"content": {"parts": [{"text": json.dumps({"criteria": {k: 7 for k in CRITERIA}, "confidence": 0.9})}]}}
    ]
}


def transport(behaviour: dict[str, object]) -> httpx.MockTransport:
    """behaviour: имя модели → HTTP-код ошибки или 'ok'."""

    def handler(request: httpx.Request) -> httpx.Response:
        model = request.url.path.split("/models/")[1].split(":")[0]
        result = behaviour[model]
        if result == "ok":
            return httpx.Response(200, json=GOOD)
        if result == "timeout":
            raise httpx.ReadTimeout("slow")
        return httpx.Response(result, json={"error": {"code": result}})

    return httpx.MockTransport(handler)


def rate(behaviour, fallback="lite"):
    async def go():
        r = GeminiRater("key", "flash", fallback, transport=transport(behaviour))
        try:
            return await r.rate(TRACK)
        finally:
            await r.close()

    return asyncio.run(go())


def test_primary_answers():
    assert rate({"flash": "ok", "lite": "ok"}).model == "flash"


@pytest.mark.parametrize("failure", [503, 429, "timeout"])
def test_fallback_on_overload_quota_or_timeout(failure):
    r = rate({"flash": failure, "lite": "ok"})
    assert r.model == "lite"
    assert r.elo == 1780


def test_no_fallback_raises():
    with pytest.raises(RuntimeError):
        rate({"flash": 503}, fallback=None)


def test_both_fail_raises():
    with pytest.raises(RuntimeError):
        rate({"flash": 503, "lite": 503})
