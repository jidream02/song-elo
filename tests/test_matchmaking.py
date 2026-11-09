import random
from collections import Counter

from services.songs import _pair, choose_pair


def test_needs_two_songs():
    assert choose_pair([(1, 1500, 0)], set()) is None


def test_respects_voted_today():
    songs = [(1, 1500, 0), (2, 1600, 0), (3, 1700, 0)]
    voted = {_pair(1, 2), _pair(1, 3)}
    for seed in range(50):
        assert set(choose_pair(songs, voted, random.Random(seed))) == {2, 3}


def test_all_pairs_voted_returns_none():
    songs = [(1, 1500, 0), (2, 1600, 0)]
    assert choose_pair(songs, {_pair(1, 2)}) is None


def test_new_songs_appear_more_often():
    songs = [(1, 1500, 0)] + [(i, 1500, 40) for i in range(2, 12)]
    rng = random.Random(1)
    appearances = Counter()
    for _ in range(2000):
        appearances.update(choose_pair(songs, set(), rng))
    # новая песня (0 баттлов) должна попадаться заметно чаще любой «старой»
    assert appearances[1] > 3 * max(appearances[i] for i in range(2, 12))


def test_opponent_usually_close_in_rating():
    songs = [(i, 1000 + i * 50, 20) for i in range(1, 30)]
    rng = random.Random(2)
    diffs = []
    for _ in range(1000):
        a, b = choose_pair(songs, set(), rng)
        diffs.append(abs(a - b) * 50)
    close = sum(d <= 5 * 50 for d in diffs) / len(diffs)
    assert close > 0.75  # ~80% пар — среди ближайших по рейтингу
