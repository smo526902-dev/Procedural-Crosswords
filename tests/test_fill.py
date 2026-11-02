import random

import pytest

from crossword.difficulty import GEOMETRY
from crossword.fill import Filler, FillOptions
from crossword.grid import find_slots
from crossword.patterns import generate_pattern
from crossword.wordlist import WordList


def test_index_pattern_matching():
    wl = WordList.from_words({"cat": 90, "cot": 80, "cut": 70, "dog": 60, "cart": 50})
    idx = wl.index()
    assert idx.matches("C?T") == ["CAT", "COT", "CUT"]  # best score first
    assert idx.matches("??G") == ["DOG"]
    assert idx.matches("X??") == []
    assert idx.matches("C??T") == ["CART"]


def test_fills_a_tiny_word_square():
    words = {w: 50 for w in ["BAT", "ARE", "TEN", "BAT", "ARE", "TEN", "CAB", "ODE", "WET"]}
    wl = WordList.from_words(words)
    blocks = [[False] * 3 for _ in range(3)]
    slots = find_slots(blocks, 3)
    # BAT/ARE/TEN read the same across and down, but answers may not repeat
    assert Filler(slots, wl.index(), random.Random(0)).fill() is None
    wl = WordList.from_words({w: 50 for w in ["CAB", "ODE", "WET", "COW", "ADE", "BET"]})
    result = Filler(slots, wl.index(), random.Random(0)).fill()
    assert result is not None and sorted(result.values()) == sorted(["CAB", "ODE", "WET", "COW", "ADE", "BET"])


def _check_fill(slots, result, letters, wordlist):
    assert len(result) == len(slots)
    assert len(set(result.values())) == len(result), "duplicate answer"
    for s in slots:
        word = result[s.id]
        assert word in wordlist.info
        assert "".join(letters[c] for c in s.cells) == word  # crossings agree


@pytest.mark.parametrize("size,min_score", [(5, 55), (9, 45), (11, 40)])
def test_real_fill_is_consistent(wordlist, size, min_score):
    ratio, max_len = GEOMETRY[size]
    rng = random.Random(3)
    for _ in range(40):
        b = generate_pattern(size, rng, ratio, max_len)
        slots = find_slots(b, 3)
        f = Filler(slots, wordlist.index(min_score), random.Random(rng.random()), FillOptions(node_limit=3000))
        result = f.fill()
        if result:
            _check_fill(slots, result, f.letters, wordlist)
            assert all(wordlist.info[w].score >= min_score for w in result.values())
            return
    pytest.fail("no pattern filled")


def test_no_near_duplicate_stems(wordlist):
    from crossword.generate import generate
    p = generate(3, 21)
    answers = [e.answer for e in p.entries]
    for a in answers:
        for b in answers:
            if a != b and len(a) >= 3 and b.startswith(a):
                assert len(b) - len(a) > 3, (a, b)
