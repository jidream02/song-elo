import pytest

from services.elo import (
    K_DEFAULT,
    K_NEW,
    expected_score,
    k_factor,
    score_to_elo,
    update_ratings,
    win_probability,
)


def test_equal_ratings_give_50_percent():
    assert expected_score(1500, 1500) == pytest.approx(0.5)


def test_400_points_is_10_to_1():
    assert expected_score(1900, 1500) == pytest.approx(10 / 11)
    assert expected_score(1500, 1900) == pytest.approx(1 / 11)


def test_probabilities_sum_to_one():
    assert win_probability(1723, 1411) + win_probability(1411, 1723) == pytest.approx(1.0)


@pytest.mark.parametrize("matches,expected", [(0, K_NEW), (9, K_NEW), (10, K_DEFAULT), (500, K_DEFAULT)])
def test_k_factor(matches, expected):
    assert k_factor(matches) == expected


def test_equal_established_ratings_win_gives_16():
    upd = update_ratings(1500, 1500, 1.0, 20, 20)
    assert upd.delta_a == pytest.approx(16)
    assert upd.delta_b == pytest.approx(-16)
    assert upd.new_a + upd.new_b == pytest.approx(3000)  # при равных K сумма сохраняется


def test_new_song_moves_faster():
    upd = update_ratings(1500, 1500, 1.0, matches_a=0, matches_b=50)
    assert upd.delta_a == pytest.approx(24)  # K=48 * 0.5
    assert upd.delta_b == pytest.approx(-16)  # K=32 * 0.5


def test_upset_gives_more_points_than_expected_win():
    upset = update_ratings(1400, 1800, 1.0, 20, 20).delta_a
    expected_win = update_ratings(1800, 1400, 1.0, 20, 20).delta_a
    assert upset > expected_win > 0


def test_draw_between_equals_changes_nothing():
    upd = update_ratings(1600, 1600, 0.5, 20, 20)
    assert upd.delta_a == pytest.approx(0)


def test_invalid_score_rejected():
    with pytest.raises(ValueError):
        update_ratings(1500, 1500, 2.0)


@pytest.mark.parametrize(
    "score,elo", [(1, 800), (5, 1500), (10, 2200), (3, 1150), (7.5, 1850), (0, 800), (11, 2200)]
)
def test_score_to_elo(score, elo):
    assert score_to_elo(score) == elo
