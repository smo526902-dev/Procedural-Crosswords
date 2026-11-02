import statistics

import pytest

from crossword.difficulty import ALL_AIDS, PRESETS, preset
from crossword.generate import generate


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_each_level_generates(wordlist, level):
    p = generate(level, 1)
    d = PRESETS[level]
    assert p.size == d.size
    assert p.stats["seconds"] < 25
    for e in p.entries:
        assert e.clue and e.answer.lower() not in e.clue.lower().split()
        assert wordlist.info[e.answer].score >= p.stats["min_score_used"]
    # every white cell belongs to an across and a down entry
    across = {(e.row, e.col + k) for e in p.across for k in range(len(e.answer))}
    down = {(e.row + k, e.col) for e in p.down for k in range(len(e.answer))}
    whites = {(r, c) for r, row in enumerate(p.solution) for c, ch in enumerate(row) if ch}
    assert across == down == whites
    assert len(p.givens) == d.starter_letters


def test_same_seed_same_puzzle(wordlist):
    a, b = generate(3, 1234), generate(3, 1234)
    assert a.to_dict() | {"stats": None} == b.to_dict() | {"stats": None}
    c = generate(3, 1235)
    assert c.to_dict()["grid"] != a.to_dict()["grid"]


def test_difficulty_scales(wordlist):
    tiers, scores, sizes = {}, {}, {}
    for level in (1, 3, 5):
        ts, ss = [], []
        for seed in range(3):
            p = generate(level, seed)
            ts += [e.tier for e in p.entries]
            ss.append(p.quality.avg_word_score)
            sizes[level] = p.size
        tiers[level], scores[level] = statistics.mean(ts), statistics.mean(ss)
    assert sizes[1] < sizes[3] < sizes[5]
    assert tiers[1] < tiers[3] < tiers[5]
    assert scores[1] > scores[3] > scores[5]


def test_overrides(wordlist):
    p = generate(5, 7, size=9, clue_tier=1, aids=["check"], min_score=40)
    assert p.size == 9
    assert p.difficulty.aids == ("check",)
    assert p.difficulty.min_score == 40
    assert sum(e.tier == 1 for e in p.entries) >= 0.8 * len(p.entries)


def test_preset_validation():
    with pytest.raises(ValueError):
        preset(9)
    with pytest.raises(ValueError):
        preset(3, size=8)
    with pytest.raises(ValueError):
        preset(3, aids=["teleport"])
    assert preset(1).aids == ALL_AIDS
    assert preset(5).aids == ()
