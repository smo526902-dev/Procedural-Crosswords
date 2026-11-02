"""Difficulty presets.

One level (1-5) sets four knobs, and each can be overridden on its own:

* grid size / density   - bigger grids, longer answers
* word obscurity        - minimum word score allowed in the fill
* clue trickiness       - mix of clue tiers (1 straight .. 4 wordplay/obscure)
* solver aids           - which check / reveal tools the UI offers
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

ALL_AIDS = ("check", "reveal_letter", "reveal_word", "reveal_puzzle")

# size -> (black-square ratio, longest allowed answer).  Tuned so the
# filler succeeds on a good share of random patterns with our word list.
GEOMETRY = {
    5: (0.15, 5),
    7: (0.26, 7),
    9: (0.20, 7),
    11: (0.20, 8),
    13: (0.22, 8),
    15: (0.20, 8),
}


@dataclass(frozen=True)
class Difficulty:
    level: int
    name: str
    size: int
    min_score: int                  # word obscurity floor (0-100)
    clue_mix: dict[int, float]      # clue tier -> weight
    aids: tuple[str, ...]
    starter_letters: int = 0        # letters pre-filled for the solver
    black_ratio: float = field(default=0.0)
    max_len: int = field(default=0)

    def __post_init__(self):
        ratio, max_len = GEOMETRY[self.size]
        if not self.black_ratio:
            object.__setattr__(self, "black_ratio", ratio)
        if not self.max_len:
            object.__setattr__(self, "max_len", max_len)

    def to_dict(self) -> dict:
        return {
            "level": self.level, "name": self.name, "size": self.size,
            "min_score": self.min_score, "clue_mix": self.clue_mix,
            "aids": list(self.aids), "starter_letters": self.starter_letters,
        }


PRESETS = {
    1: Difficulty(1, "Easy", 5, 55, {1: 1.0}, ALL_AIDS, starter_letters=2),
    2: Difficulty(2, "Gentle", 9, 45, {1: 0.6, 2: 0.4}, ALL_AIDS),
    3: Difficulty(3, "Medium", 11, 40, {1: 0.2, 2: 0.6, 3: 0.2}, ("check", "reveal_letter", "reveal_word")),
    4: Difficulty(4, "Hard", 13, 30, {2: 0.3, 3: 0.6, 4: 0.1}, ("check",)),
    5: Difficulty(5, "Expert", 15, 20, {3: 0.5, 4: 0.5}, ()),
}


def preset(level: int = 3, *, size: int | None = None, min_score: int | None = None,
           clue_tier: int | None = None, aids: list[str] | tuple[str, ...] | None = None,
           starter_letters: int | None = None) -> Difficulty:
    """A preset for `level`, with any knob overridden independently."""
    if level not in PRESETS:
        raise ValueError(f"level must be 1-5, got {level}")
    d = PRESETS[level]
    changes: dict = {}
    if size is not None:
        if size not in GEOMETRY:
            raise ValueError(f"size must be one of {sorted(GEOMETRY)}")
        ratio, max_len = GEOMETRY[size]
        changes.update(size=size, black_ratio=ratio, max_len=max_len)
    if min_score is not None:
        changes["min_score"] = max(0, min(100, int(min_score)))
    if clue_tier is not None:
        if clue_tier not in (1, 2, 3, 4):
            raise ValueError("clue_tier must be 1-4")
        changes["clue_mix"] = {clue_tier: 1.0}
    if aids is not None:
        bad = set(aids) - set(ALL_AIDS)
        if bad:
            raise ValueError(f"unknown aids: {sorted(bad)}")
        changes["aids"] = tuple(a for a in ALL_AIDS if a in aids)
    if starter_letters is not None:
        changes["starter_letters"] = max(0, int(starter_letters))
    return replace(d, **changes) if changes else d
