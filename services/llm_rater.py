"""Стартовая оценка песни через Claude API + строгий парсинг JSON-ответа."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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

SYSTEM_PROMPT = f"""You are a strict, fair music critic. You rate songs on craft, not popularity.

Score each criterion from 1 to 10 (5 = an average, competent song):
{chr(10).join(f'- "{k}": {v}' for k, v in CRITERIA.items())}

Rules:
- Judge the song itself. Streams, chart positions and hype are NOT evidence of quality.
  "legacy" is about lasting influence and how well the song holds up, not raw popularity.
- Use the full scale. Most songs are 4-7. Reserve 9-10 for genuinely exceptional work.
- If you do not actually know this specific recording (not just the artist), do NOT guess:
  set "criteria" to null, "elo" to null, "confidence" below 0.3, and explain in "weaknesses"
  that you don't know the song.
- If a criterion genuinely does not apply (e.g. "vocals" for an instrumental piece), set it to null.
- "confidence" (0-1) = how well you know this exact recording.
- "elo": your estimate on the scale 1/10 ≈ 800, 5/10 ≈ 1500, 10/10 ≈ 2200.
- "strengths" and "weaknesses": 1-3 short points each, written in Russian.
- Reply with ONE JSON object and nothing else, exactly this shape:
{{"criteria": {{{", ".join(f'"{k}": int | null' for k in CRITERIA)}}}, "elo": int, "strengths": [str], "weaknesses": [str], "confidence": float}}"""


MIN_APPLICABLE_CRITERIA = 4


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
        }


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _extract_json_object(text: str) -> dict:
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Модель могла добавить текст вокруг — берём первый {...} верхнего уровня.
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise LLMParseError("В ответе нет JSON-объекта") from None
        try:
            data = json.loads(cleaned[start : end + 1])
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

    return LLMRating(
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
        return parse_llm_response(text)

    async def close(self) -> None:
        await self._client.close()


class GeminiRater:
    """То же самое через Google Gemini API (есть бесплатный тариф в AI Studio)."""

    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str, timeout: float = 60.0) -> None:
        self._key = api_key
        self._model = model
        self._http = httpx.AsyncClient(timeout=timeout)

    @property
    def model(self) -> str:
        return self._model

    async def rate(self, track: TrackInfo) -> LLMRating:
        resp = await self._http.post(
            self.URL.format(model=self._model),
            headers={"x-goog-api-key": self._key},
            json={
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": build_user_prompt(track)}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
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
        return parse_llm_response(text)

    async def close(self) -> None:
        await self._http.aclose()
