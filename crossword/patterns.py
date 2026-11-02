"""Random American-style block patterns.

Rules enforced:
* 180-degree rotational symmetry
* every across/down run of white squares is at least ``min_len`` long, which
  also means every white square is checked (part of an across AND a down word)
* all white squares are connected
* no 2x2 clumps of black squares
* no run longer than ``max_len`` and roughly ``black_ratio`` black squares
"""
from __future__ import annotations

import random

from .grid import Blocks, all_runs, is_connected, mirror, runs


def _line_ok(line: list[bool], min_len: int) -> bool:
    return all(n >= min_len for _, n in runs(line))


def _locally_ok(blocks: Blocks, cells: list[tuple[int, int]], min_len: int) -> bool:
    n = len(blocks)
    for r, c in cells:
        if not _line_ok(list(blocks[r]), min_len):
            return False
        if not _line_ok([blocks[i][c] for i in range(n)], min_len):
            return False
        # no 2x2 black clump touching this cell
        for dr in (-1, 0):
            for dc in (-1, 0):
                rr, cc = r + dr, c + dc
                if 0 <= rr < n - 1 and 0 <= cc < n - 1 and all(
                        blocks[rr + a][cc + b] for a in (0, 1) for b in (0, 1)):
                    return False
    return True


def validate(blocks: Blocks, min_len: int = 3, max_len: int | None = None) -> list[str]:
    """Return a list of rule violations (empty = valid)."""
    problems = []
    n = len(blocks)
    if any(blocks[r][c] != blocks[n - 1 - r][n - 1 - c] for r in range(n) for c in range(n)):
        problems.append("not rotationally symmetric")
    lengths = all_runs(blocks)
    if any(L < min_len for L in lengths):
        problems.append(f"run shorter than {min_len}")
    if max_len and any(L > max_len for L in lengths):
        problems.append(f"run longer than {max_len}")
    if not is_connected(blocks):
        problems.append("white squares not connected")
    return problems


def _long_runs(blocks: Blocks, max_len: int, min_len: int) -> list[tuple[int, int]]:
    """Cells that could split a run that is longer than max_len."""
    n = len(blocks)
    out = []
    for r in range(n):
        for start, L in runs(list(blocks[r])):
            if L > max_len:
                out += [(r, start + i) for i in range(min_len, L - min_len)]
    for c in range(n):
        for start, L in runs([blocks[i][c] for i in range(n)]):
            if L > max_len:
                out += [(start + i, c) for i in range(min_len, L - min_len)]
    return out


def generate_pattern(size: int, rng: random.Random, black_ratio: float = 0.16,
                     max_len: int | None = None, min_len: int = 3,
                     restarts: int = 60) -> Blocks | None:
    max_len = max_len or size
    target = round(size * size * black_ratio)
    for _ in range(restarts):
        blocks = [[False] * size for _ in range(size)]
        count = 0
        stalls = 0
        while stalls < 200:
            long_cells = _long_runs(blocks, max_len, min_len)
            if count >= target and not long_cells:
                if validate(blocks, min_len, max_len) == []:
                    return blocks
                break
            pool = long_cells or [(r, c) for r in range(size) for c in range(size) if not blocks[r][c]]
            best = None
            for r, c in rng.sample(pool, min(10, len(pool))):
                mr, mc = mirror(size, r, c)
                if blocks[r][c]:
                    continue
                cells = [(r, c)] if (r, c) == (mr, mc) else [(r, c), (mr, mc)]
                for rr, cc in cells:
                    blocks[rr][cc] = True
                ok = _locally_ok(blocks, cells, min_len) and is_connected(blocks)
                if ok:
                    # prefer placements that create few 3-letter words
                    shorts = sum(1 for L in all_runs(blocks) if L == min_len)
                    key = shorts + rng.random() * 1.5
                    if best is None or key < best[0]:
                        best = (key, cells)
                for rr, cc in cells:
                    blocks[rr][cc] = False
            if best is None:
                stalls += 1
                continue
            for rr, cc in best[1]:
                blocks[rr][cc] = True
            count += len(best[1])
            if count > target + 6:
                break  # overshot; start again
    return None
