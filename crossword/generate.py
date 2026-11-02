"""Pattern -> fill -> clues -> quality, with restarts.  The public entry point."""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from functools import lru_cache

from .clues import pick_clues
from .difficulty import Difficulty, preset
from .fill import Filler, FillOptions
from .grid import Blocks, Cell, find_slots, to_text
from .patterns import generate_pattern
from .quality import Quality, assess
from .wordlist import WordList


@lru_cache(maxsize=1)
def default_wordlist() -> WordList:
    return WordList.load()


@dataclass
class Entry:
    number: int
    direction: str  # "A" / "D"
    row: int
    col: int
    answer: str
    clue: str
    tier: int

    def to_dict(self) -> dict:
        return {"number": self.number, "direction": self.direction, "row": self.row,
                "col": self.col, "length": len(self.answer), "answer": self.answer,
                "clue": self.clue, "tier": self.tier}


@dataclass
class Puzzle:
    id: str
    seed: int
    difficulty: Difficulty
    blocks: Blocks
    solution: list[list[str | None]]
    entries: list[Entry]
    quality: Quality
    givens: list[Cell] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.blocks)

    @property
    def across(self) -> list[Entry]:
        return [e for e in self.entries if e.direction == "A"]

    @property
    def down(self) -> list[Entry]:
        return [e for e in self.entries if e.direction == "D"]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "seed": self.seed,
            "size": self.size,
            "difficulty": self.difficulty.to_dict(),
            "grid": ["".join("#" if ch is None else ch for ch in row) for row in self.solution],
            "entries": [e.to_dict() for e in self.entries],
            "givens": [list(c) for c in self.givens],
            "quality": self.quality.to_dict(),
            "stats": self.stats,
        }

    def to_text(self, show_answers: bool = True) -> str:
        letters = {(r, c): ch for r, row in enumerate(self.solution)
                   for c, ch in enumerate(row) if ch and (show_answers or (r, c) in self.givens)}
        out = [to_text(self.blocks, letters), "", "ACROSS"]
        out += [f"{e.number:>3}. {e.clue}  ({len(e.answer)})" + (f"  {e.answer}" if show_answers else "")
                for e in self.across]
        out += ["", "DOWN"]
        out += [f"{e.number:>3}. {e.clue}  ({len(e.answer)})" + (f"  {e.answer}" if show_answers else "")
                for e in self.down]
        return "\n".join(out)


class GenerationError(RuntimeError):
    pass


def puzzle_id(seed: int, d: Difficulty) -> str:
    key = json.dumps([seed, d.to_dict()], sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def generate(level: int = 3, seed: int | None = None, *, size: int | None = None,
             min_score: int | None = None, clue_tier: int | None = None,
             aids: list[str] | None = None, starter_letters: int | None = None,
             wordlist: WordList | None = None, time_budget: float = 25.0,
             candidates: int | None = None) -> Puzzle:
    """Generate a puzzle.  The same arguments and seed give the same puzzle
    (unless the safety time budget is hit before any fill succeeds)."""
    d = preset(level, size=size, min_score=min_score, clue_tier=clue_tier, aids=aids,
               starter_letters=starter_letters)
    if seed is None:
        seed = random.SystemRandom().randrange(1, 10**9)
    wl = wordlist or default_wordlist()
    rng = random.Random(seed)
    t0 = time.monotonic()
    want = candidates or (4 if d.size <= 9 else 2)
    node_limit = {5: 2000, 7: 3000, 9: 2000, 11: 3000, 13: 3000, 15: 3000}.get(d.size, 3000)

    min_score_now = d.min_score
    best = None
    attempts = fills = 0
    misses = 0
    while time.monotonic() - t0 < time_budget:
        attempts += 1
        blocks = generate_pattern(d.size, rng, d.black_ratio, d.max_len)
        fill_rng = random.Random(rng.getrandbits(64))
        if blocks is None:
            continue
        slots = find_slots(blocks, 3)
        index = wl.index(min_score_now, d.size)
        filler = Filler(slots, index, fill_rng, FillOptions(node_limit=node_limit, time_limit=time_budget))
        result = filler.fill()
        if result is None:
            misses += 1
            # If the vocabulary is too tight for this grid, relax it gradually.
            if misses % 12 == 0 and best is None and min_score_now > 0:
                min_score_now = max(0, min_score_now - 10)
            continue
        fills += 1
        q = assess(list(result.values()), wl)
        if best is None or q.overall > best[0].overall:
            best = (q, blocks, slots, result, dict(filler.letters))
        if fills >= want:
            break
    if best is None:
        raise GenerationError(f"no fill found for {d.size}x{d.size} within {time_budget}s")

    q, blocks, slots, result, letters = best
    answers = [result[s.id] for s in slots]
    clues = pick_clues(answers, wl, d.clue_mix, random.Random(rng.getrandbits(64)))
    entries = [Entry(s.number, s.direction, s.row, s.col, a, c, t)
               for s, a, (c, t) in zip(slots, answers, clues)]
    solution = [[None if blocks[r][c] else letters[(r, c)] for c in range(d.size)]
                for r in range(d.size)]
    white = [(r, c) for r in range(d.size) for c in range(d.size) if not blocks[r][c]]
    givens = sorted(rng.sample(white, min(d.starter_letters, len(white))))
    stats = {"attempts": attempts, "fills": fills, "seconds": round(time.monotonic() - t0, 2),
             "min_score_used": min_score_now}
    return Puzzle(puzzle_id(seed, d), seed, d, blocks, solution, entries, q, givens, stats)
