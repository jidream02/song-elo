"""Стартовая оценка песни через LLM (Gemini / Claude) + строгий парсинг JSON-ответа."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any

import httpx
from anthropic import AsyncAnthropic

from services.elo import score_to_elo
from services.spotify import TrackInfo

CRITERIA: dict[str, str] = {
    "melody": "Мелодия и запоминаемость",
    "vocals": "Вокал / исполнение",
    "production": "Аранжировка и продакшн",
    "originality": "Оригинальность",
    "emotion": "Эмоциональное воздействие",
    "legacy": "Культурное влияние и долговечность",
}

SYSTEM_PROMPT = f"""You are an experienced, fair music critic. You rate the craft of a specific recording,
not its popularity, and you take every song seriously — no lazy, generic verdicts.

Criteria:
{chr(10).join(f'- "{k}": {v}' for k, v in CRITERIA.items())}

Scale (use it exactly like this):
1-2 = broken / unlistenable; 3-4 = weak, below average; 5 = average, competent;
6 = good; 7 = very good; 8 = excellent; 9 = outstanding even within its genre; 10 = all-time landmark.
Most songs land between 4 and 7. 9-10 must be rare and earned.

How to judge:
- FIRST think, THEN score. Fill "analysis" before "criteria": one concrete sentence per criterion
  about THIS recording (a specific musical element, section, sound or choice), then the score that follows from it.
- Judge a song by the goals of its own genre. Ambient is not penalised for being calm or slow,
  punk/lo-fi/cloud rap are not penalised for raw production, a pop song is not rewarded just for being catchy.
- Reward craft depth: sophisticated harmony, non-trivial structure and development, layered arrangement,
  real instrumental/vocal technique, lyrical depth. Formulaic or low-effort tracks — type-beat loops,
  meme/novelty songs, sped-up/reverb edits, karaoke covers, songs built around one gimmick or catchphrase —
  must not get more than 4-5 for "melody", "production" and "originality", however catchy or viral they are.
- Simplicity is NOT a flaw by itself: in punk, minimal, lo-fi, folk etc. it can be a deliberate choice.
  Judge whether the simplicity is executed with intent and skill, or is just lack of effort.
- Popularity, streams, charts and memes are NOT quality. "legacy" = lasting artistic influence and how well
  the song holds up, not how famous it is.
- NEVER name session musicians, producers, engineers or sampled songs — such details are where critics
  hallucinate. Describe what is heard instead (instruments, textures, structure, delivery).
- "strengths"/"weaknesses": 1-3 points each, specific to this recording. Banned: generic phrases that could
  describe any song ("сильное эмоциональное воздействие", "хороший продакшн").
- If a criterion genuinely does not apply (e.g. "vocals" for an instrumental), set it to null.
- FIRST of all, decide "known": do you genuinely know THIS exact recording (you could describe how it actually
  sounds), not just the artist or a similar-sounding title? Inventing a description of a song you do not know
  is the worst possible error — far worse than admitting you don't know it.
  If "known" is false: set "analysis", "criteria" and "elo" to null, "confidence" below 0.3,
  and say in "weaknesses" that you don't know the song.
- "confidence" (0-1) = how well you know this exact recording.
- "elo": your overall estimate, 1/10 ≈ 800, 5/10 ≈ 1500, 10/10 ≈ 2200.
- Write "analysis", "strengths" and "weaknesses" in Russian.

Reply with ONE JSON object and nothing else, keys in exactly this order:
{{"known": bool, "analysis": {{{", ".join(f'"{k}": str' for k in CRITERIA)}}}, "criteria": {{{", ".join(f'"{k}": int | null' for k in CRITERIA)}}}, "elo": int, "strengths": [str], "weaknesses": [str], "confidence": float}}"""


MIN_APPLICABLE_CRITERIA = 4


log = logging.getLogger(__name__)


class LLMParseError(ValueError):
    """Модель вернула не то, что мы просили."""


@dataclass(frozen=True)
class LLMRating:
    criteria: dict[str, int | None] | None  # None у критерия = неприменим (вокал у инструментала)
    elo: int | None  # считаем сами по критериям — это источник истины
    model_elo: int | None  # что написала модель (для отладки)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    confidence: float = 0.0
    model: str | None = None  # какая модель реально ответила (важно при запасной модели)
    analysis: dict[str, str] | None = None  # разбор по критериям — «почему такой балл»

    def is_known(self, min_confidence: float) -> bool:
        return self.criteria is not None and self.confidence >= min_confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria": self.criteria,
            "elo": self.elo,
            "model_elo": self.model_elo,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "confidence": self.confidence,
            "analysis": self.analysis,
            "model": self.model,
        }


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _extract_json_object(text: str) -> dict:
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Модель могла добавить текст до или после JSON (или второй объект) —
        # берём первый целый объект, начиная с первой «{», хвост игнорируем.
        start = cleaned.find("{")
        if start == -1:
            raise LLMParseError("В ответе нет JSON-объекта") from None
        try:
            data, _ = json.JSONDecoder().raw_decode(cleaned, start)
        except json.JSONDecodeError as exc:
            raise LLMParseError(f"Невалидный JSON: {exc}") from None
    if not isinstance(data, dict):
        raise LLMParseError("Ожидался JSON-объект")
    return data


def _as_number(value: Any, name: str) -> float:
    # bool — подкласс int, но «true» оценкой не является.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LLMParseError(f"Поле {name} должно быть числом, получено {value!r}")
    return float(value)


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LLMParseError("strengths/weaknesses должны быть списками")
    return [str(x).strip() for x in value if str(x).strip()][:5]


def parse_llm_response(text: str) -> LLMRating:
    data = _extract_json_object(text)

    confidence = min(max(_as_number(data.get("confidence", 0), "confidence"), 0.0), 1.0)

    raw_criteria = data.get("criteria")
    if data.get("known") is False:  # модель сама сказала «не знаю» — баллы не принимаем
        raw_criteria = None
        confidence = min(confidence, 0.2)
    criteria: dict[str, int | None] | None
    if raw_criteria in (None, {}):
        criteria = None
    elif isinstance(raw_criteria, dict):
        missing = [k for k in CRITERIA if k not in raw_criteria]
        if missing:
            raise LLMParseError(f"Нет критериев: {', '.join(missing)}")
        criteria = {
            k: None if raw_criteria[k] is None else int(round(min(max(_as_number(raw_criteria[k], k), 1), 10)))
            for k in CRITERIA
        }
        if sum(v is not None for v in criteria.values()) < MIN_APPLICABLE_CRITERIA:
            # Модель не знает песню, но вместо criteria=null прислала пустые критерии —
            # это тот же «не знаю», а не ошибка.
            criteria = None
            confidence = min(confidence, 0.2)
    else:
        raise LLMParseError("criteria должен быть объектом или null")

    model_elo = data.get("elo")
    model_elo = None if model_elo is None else round(_as_number(model_elo, "elo"))

    elo = None
    if criteria is not None:
        scores = [v for v in criteria.values() if v is not None]
        elo = score_to_elo(sum(scores) / len(scores))

    raw_analysis = data.get("analysis")
    analysis = None
    if isinstance(raw_analysis, dict) and criteria is not None:
        analysis = {k: str(v).strip()[:300] for k, v in raw_analysis.items() if k in CRITERIA and v}

    return LLMRating(
        analysis=analysis,
        criteria=criteria,
        elo=elo,
        model_elo=model_elo,
        strengths=_str_list(data.get("strengths")),
        weaknesses=_str_list(data.get("weaknesses")),
        confidence=confidence,
    )


def build_user_prompt(track: TrackInfo) -> str:
    return (
        f"Title: {track.title}\n"
        f"Artist: {track.artist}\n"
        f"Album: {track.album or 'unknown'}\n"
        f"Genre: {track.genre or 'unknown'}\n"
        f"Year: {track.year or 'unknown'}"
    )


class LLMRater:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def rate(self, track: TrackInfo) -> LLMRating:
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(track)}],
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        return replace(parse_llm_response(text), model=self._model)

    async def close(self) -> None:
        await self._client.close()


class GeminiRater:
    """То же самое через Google Gemini API (есть бесплатный тариф в AI Studio)."""

    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(
        self,
        api_key: str,
        model: str,
        fallback_model: str | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,  # для тестов
    ) -> None:
        self._key = api_key
        self._model = model
        self._fallback = fallback_model if fallback_model and fallback_model != model else None
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)

    @property
    def model(self) -> str:
        return f"{self._model} → {self._fallback}" if self._fallback else self._model

    async def rate(self, track: TrackInfo) -> LLMRating:
        """Сначала основная модель; при таймауте, перегрузке (503), лимите (429)
        или кривом ответе — запасная (обычно быстрая lite)."""
        try:
            return await self._rate_with(self._model, track)
        except Exception as exc:
            if self._fallback is None:
                raise
            log.warning("Gemini %s не справилась (%s: %s), пробую %s",
                        self._model, type(exc).__name__, str(exc)[:120], self._fallback)
            return await self._rate_with(self._fallback, track)

    async def _rate_with(self, model: str, track: TrackInfo) -> LLMRating:
        resp = await self._http.post(
            self.URL.format(model=model),
            headers={"x-goog-api-key": self._key},
            json={
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": build_user_prompt(track)}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError):
            raise LLMParseError(f"Пустой ответ Gemini: {str(data)[:300]}") from None
        # Модели с «размышлениями» могут вернуть служебные части с thought=true — их пропускаем.
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return replace(parse_llm_response(text), model=model)

    async def close(self) -> None:
        await self._http.aclose()
