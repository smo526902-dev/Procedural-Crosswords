import random

import pytest

from crossword.grid import all_runs, find_slots, is_connected, is_symmetric
from crossword.patterns import generate_pattern, validate
from crossword.difficulty import GEOMETRY


@pytest.mark.parametrize("size", sorted(GEOMETRY))
def test_patterns_follow_american_rules(size):
    ratio, max_len = GEOMETRY[size]
    for seed in range(5):
        b = generate_pattern(size, random.Random(seed), ratio, max_len)
        assert b is not None
        assert validate(b, 3, max_len) == []
        assert is_symmetric(b)
        assert is_connected(b)
        assert all(3 <= n <= max_len for n in all_runs(b))


def test_every_white_square_is_checked():
    b = generate_pattern(15, random.Random(1), *GEOMETRY[15])
    slots = find_slots(b, 3)
    across = {c for s in slots if s.direction == "A" for c in s.cells}
    down = {c for s in slots if s.direction == "D" for c in s.cells}
    whites = {(r, c) for r in range(15) for c in range(15) if not b[r][c]}
    assert across == down == whites


def test_numbering_is_standard():
    b = [[False] * 5 for _ in range(5)]
    b[0][0] = b[4][4] = True
    slots = find_slots(b, 3)
    labels = [(s.number, s.direction) for s in slots]
    assert labels[:3] == [(1, "A"), (1, "D"), (2, "D")]
    assert slots[0].cells == [(0, 1), (0, 2), (0, 3), (0, 4)]
    nums = [s.number for s in slots]
    assert nums == sorted(nums)


def test_validate_reports_problems():
    b = [[False] * 5 for _ in range(5)]
    b[0][1] = True  # breaks symmetry and leaves a 1-letter run
    problems = validate(b)
    assert "not rotationally symmetric" in problems
    assert any("shorter" in p for p in problems)
