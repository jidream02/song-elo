import json

import pytest

from services.llm_rater import CRITERIA, LLMParseError, parse_llm_response


def make(**overrides):
    data = {
        "criteria": {k: 7 for k in CRITERIA},
        "elo": 1780,
        "strengths": ["Цепкий припев"],
        "weaknesses": ["Затянутый бридж"],
        "confidence": 0.9,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def test_valid_response():
    r = parse_llm_response(make())
    assert r.criteria == {k: 7 for k in CRITERIA}
    assert r.elo == 1780  # 7/10 → 1500 + 2*140 — считаем сами
    assert r.model_elo == 1780
    assert r.strengths == ["Цепкий припев"]
    assert r.is_known(0.4)


def test_elo_is_computed_from_criteria_not_trusted_from_model():
    r = parse_llm_response(make(elo=2200))  # модель «завысила» итог
    assert r.elo == 1780
    assert r.model_elo == 2200


def test_code_fence_is_stripped():
    assert parse_llm_response(f"```json\n{make()}\n```").elo == 1780


def test_text_around_json():
    assert parse_llm_response(f"Вот оценка:\n{make()}\nНадеюсь, помог!").elo == 1780


def test_unknown_song():
    r = parse_llm_response(
        make(criteria=None, elo=None, strengths=[], weaknesses=["Не знаю эту песню"], confidence=0.1)
    )
    assert r.criteria is None
    assert r.elo is None
    assert not r.is_known(0.4)


def test_low_confidence_with_criteria_is_not_known():
    assert not parse_llm_response(make(confidence=0.2)).is_known(0.4)


def test_scores_are_clamped_and_rounded():
    crit = {k: 7 for k in CRITERIA}
    crit["melody"] = 14
    crit["vocals"] = 6.6
    r = parse_llm_response(make(criteria=crit, confidence=3))
    assert r.criteria["melody"] == 10
    assert r.criteria["vocals"] == 7
    assert r.confidence == 1.0


def test_missing_criterion_rejected():
    crit = {k: 7 for k in CRITERIA}
    del crit["legacy"]
    with pytest.raises(LLMParseError, match="legacy"):
        parse_llm_response(make(criteria=crit))


def test_not_applicable_criterion_excluded_from_average():
    crit = {k: 8 for k in CRITERIA}
    crit["vocals"] = None  # инструментал
    r = parse_llm_response(make(criteria=crit))
    assert r.criteria["vocals"] is None
    assert r.elo == 1920  # среднее по пяти оставшимся = 8


def test_mostly_empty_criteria_means_unknown():
    crit = {k: None for k in CRITERIA}
    crit["melody"] = 9
    r = parse_llm_response(make(criteria=crit, confidence=0.9))
    assert r.criteria is None
    assert r.elo is None
    assert not r.is_known(0.4)


def test_all_null_criteria_means_unknown():
    r = parse_llm_response(make(criteria={k: None for k in CRITERIA}, elo=None, confidence=0.1))
    assert r.criteria is None and not r.is_known(0.4)


@pytest.mark.parametrize("bad", ["семь", True, [7]])
def test_non_numeric_score_rejected(bad):
    crit = {k: 7 for k in CRITERIA}
    crit["emotion"] = bad
    with pytest.raises(LLMParseError):
        parse_llm_response(make(criteria=crit))


@pytest.mark.parametrize("text", ["", "Я не знаю такую песню", "{broken json", "[1, 2, 3]"])
def test_garbage_rejected(text):
    with pytest.raises(LLMParseError):
        parse_llm_response(text)


def test_criteria_wrong_type_rejected():
    with pytest.raises(LLMParseError):
        parse_llm_response(make(criteria="all good"))


def test_known_false_means_unknown_even_with_scores():
    r = parse_llm_response(make(known=False, confidence=0.5))
    assert r.criteria is None and r.elo is None and r.confidence <= 0.2


def test_known_true_keeps_scores():
    assert parse_llm_response(make(known=True)).elo == 1780


def test_trailing_garbage_after_json():
    assert parse_llm_response(make() + "\n}\n{\"note\": 1}").elo == 1780
