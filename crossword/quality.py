"""Score a finished fill so the generator can keep its best attempt."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .wordlist import WordList


@dataclass
class Quality:
    overall: float        # 0-100, higher is better
    avg_word_score: float
    worst_word_score: int
    words: int
    three_letter_words: int
    long_words: int       # 7+ letters: the lively entries
    shared_stems: int     # e.g. RUN and RUNS in the same grid

    def to_dict(self) -> dict:
        return asdict(self)


def _stem_clashes(answers: list[str]) -> int:
    clashes = 0
    ordered = sorted(answers, key=len)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if len(a) >= 3 and b.startswith(a) and len(b) - len(a) <= 3:
                clashes += 1
    return clashes


def assess(answers: list[str], wordlist: WordList) -> Quality:
    scores = sorted(wordlist.info[a].score if a in wordlist.info else 0 for a in answers)
    n = len(answers) or 1
    avg = sum(scores) / n
    threes = sum(1 for a in answers if len(a) == 3)
    longs = sum(1 for a in answers if len(a) >= 7)
    clashes = _stem_clashes(answers)
    p10 = scores[len(scores) // 10] if scores else 0
    overall = (0.75 * avg + 0.25 * p10
               - 25.0 * max(0.0, threes / n - 0.2)
               + 10.0 * min(longs / n, 0.25)
               - 4.0 * clashes)
    return Quality(round(max(0.0, min(100.0, overall)), 1), round(avg, 1),
                   scores[0] if scores else 0, len(answers), threes, longs, clashes)
