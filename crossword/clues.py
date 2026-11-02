"""Choose one clue per answer to match the requested clue difficulty."""
from __future__ import annotations

import random
import re

from .wordlist import WordList


def _tier_order(target: int) -> list[int]:
    """Nearest tiers first; on ties prefer the easier one for easy targets
    and the harder one for hard targets."""
    lean = 1 if target >= 3 else -1
    return sorted((1, 2, 3, 4), key=lambda t: (abs(t - target), -lean * t))


def _mentions(clue: str, answers: set[str]) -> bool:
    words = {w.upper() for w in re.findall(r"[A-Za-z]+", clue)}
    return bool(words & answers)


def pick_clues(answers: list[str], wordlist: WordList, clue_mix: dict[int, float],
               rng: random.Random) -> list[tuple[str, int]]:
    """Return (clue, tier) for each answer, in the same order."""
    tiers, weights = zip(*sorted(clue_mix.items()))
    grid_answers = set(answers)
    used: set[str] = set()
    out = []
    for answer in answers:
        info = wordlist.info.get(answer)
        target = rng.choices(tiers, weights)[0]
        choice = None
        for t in _tier_order(target):
            opts = list(info.clues.get(t, [])) if info else []
            rng.shuffle(opts)
            for c in opts:
                if c in used or _mentions(c, grid_answers - {answer}):
                    continue
                choice = (c, t)
                break
            if choice:
                break
        if choice is None:  # every option clashed; accept a repeat over nothing
            for t in _tier_order(target):
                if info and info.clues.get(t):
                    choice = (info.clues[t][0], t)
                    break
        if choice is None:
            choice = (f"{len(answer)}-letter word", 1)
        used.add(choice[0])
        out.append(choice)
    return out
