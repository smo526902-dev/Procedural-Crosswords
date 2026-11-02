"""Word list loading and a bitset index for fast pattern queries.

Every (length, position, letter) triple maps to a Python int used as a bitset
over the words of that length.  Words are sorted best-first, so bit 0 is the
highest-scoring word: scanning the low bits of a mask yields candidates in
quality order.
"""
from __future__ import annotations

import gzip
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "wordlist.tsv.gz"
ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass
class WordInfo:
    word: str
    score: int
    flags: str
    clues: dict[int, list[str]]  # tier -> options


class WordList:
    def __init__(self, infos: list[WordInfo]):
        self.info = {w.word: w for w in infos}

    @classmethod
    def load(cls, path: Path | str = DATA) -> "WordList":
        infos = []
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                word, score, flags = parts[0], int(parts[1]), parts[2]
                clues = {t: [c for c in parts[2 + t].split(" || ") if c]
                         for t in (1, 2, 3, 4) if len(parts) > 2 + t and parts[2 + t]}
                infos.append(WordInfo(word, score, flags, clues))
        return cls(infos)

    @classmethod
    def from_words(cls, words: dict[str, int]) -> "WordList":
        """Build a list from {word: score} (used in tests)."""
        return cls([WordInfo(w.upper(), s, "", {1: [f"Clue for {w}"]}) for w, s in words.items()])

    def index(self, min_score: int = 0, max_len: int = 15) -> "Index":
        return _cached_index(self, min_score, max_len)


@lru_cache(maxsize=16)
def _cached_index(wl: WordList, min_score: int, max_len: int) -> "Index":
    return Index([w for w in wl.info.values() if w.score >= min_score and len(w.word) <= max_len])


def _bits(indices: list[int], n: int) -> int:
    buf = bytearray((n + 7) // 8)
    for i in indices:
        buf[i >> 3] |= 1 << (i & 7)
    return int.from_bytes(buf, "little")


class Index:
    def __init__(self, infos: list[WordInfo]):
        by_len: dict[int, list[WordInfo]] = {}
        for w in infos:
            by_len.setdefault(len(w.word), []).append(w)
        self.words: dict[int, list[str]] = {}
        self.scores: dict[int, list[int]] = {}
        self.ids: dict[str, int] = {}
        self.all: dict[int, int] = {}
        self.masks: dict[int, list[dict[str, int]]] = {}
        for L, ws in by_len.items():
            ws.sort(key=lambda w: (-w.score, w.word))
            self.words[L] = [w.word for w in ws]
            self.scores[L] = [w.score for w in ws]
            for i, w in enumerate(ws):
                self.ids[w.word] = i
            n = len(ws)
            self.all[L] = (1 << n) - 1
            pos_masks = []
            for p in range(L):
                buckets: dict[str, list[int]] = {}
                for i, w in enumerate(ws):
                    buckets.setdefault(w.word[p], []).append(i)
                pos_masks.append({ch: _bits(idx, n) for ch, idx in buckets.items()})
            self.masks[L] = pos_masks

    def __len__(self) -> int:
        return len(self.ids)

    def match_mask(self, pattern: str) -> int:
        """Bitset of words matching e.g. 'C?T' (any non-letter is a wildcard)."""
        L = len(pattern)
        m = self.all.get(L, 0)
        for p, ch in enumerate(pattern):
            if ch in ALPHA:
                m &= self.masks[L][p].get(ch, 0)
                if not m:
                    break
        return m

    def matches(self, pattern: str, limit: int | None = None) -> list[str]:
        return list(iter_words(self.words.get(len(pattern), []), self.match_mask(pattern), limit))


def iter_words(words: list[str], mask: int, limit: int | None = None):
    """Yield words for set bits of mask, lowest (= best) bits first."""
    k = 0
    while mask and (limit is None or k < limit):
        low = mask & -mask
        yield words[low.bit_length() - 1]
        mask ^= low
        k += 1


def iter_bits(mask: int, limit: int | None = None):
    k = 0
    while mask and (limit is None or k < limit):
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low
        k += 1
