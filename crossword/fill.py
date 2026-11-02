"""Constraint-satisfaction grid filler.

Depth-first search over slots:
* variable order: fewest remaining candidates (MRV), biased toward long slots
* value order: best-scoring words first, re-ranked by a one-step lookahead
  (how many options each crossing slot keeps) plus seeded random jitter, so
  fills are both high quality and different for every seed
* forward checking: a candidate that leaves a crossing slot with zero
  options is never tried; nearly-forced slots get an arc-consistency check
* conflict-directed backjumping: a failure jumps straight back to the most
  recent slot that actually caused it
* no answer (or near-duplicate stem such as BOARD/BOARDED) may appear twice
* a node budget bounds each attempt; the generator restarts with a new
  pattern when an attempt fails

Slot ids must equal their index in the ``slots`` list (as produced by
``grid.find_slots``).
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from .grid import Cell, Slot
from .wordlist import Index, iter_bits


class _OutOfBudget(Exception):
    pass


@dataclass
class FillStats:
    nodes: int = 0
    backtracks: int = 0
    seconds: float = 0.0


@dataclass
class FillOptions:
    top_k: int = 40           # viable candidates tried per slot
    max_examine: int = 600    # words scanned per slot looking for viable ones
    score_weight: float = 1.0  # preference for high-scoring words
    lookahead_weight: float = 0.6
    jitter: float = 0.35       # randomness: higher = more varied, lower quality
    node_limit: int = 4000
    time_limit: float = 8.0
    length_bias: float = 0.5  # how strongly long slots are filled first
    small_domain: int = 40    # run the arc-consistency check below this size
    banned: set[str] = field(default_factory=set)


class Filler:
    def __init__(self, slots: list[Slot], index: Index, rng: random.Random,
                 options: FillOptions | None = None):
        self.slots = slots
        self.index = index
        self.rng = rng
        self.opt = options or FillOptions()
        self.cells = {s.id: s.cells for s in slots}
        self.letters: dict[Cell, str] = {}
        self.assigned: dict[int, str] = {}
        self.used_by: dict[str, int] = {w: -1 for w in self.opt.banned}
        self.owner: dict[Cell, int] = {}
        self.stats = FillStats()
        # crossings[s] = [(pos_in_s, other_slot_id, pos_in_other)]
        by_cell: dict[Cell, list[tuple[int, int]]] = {}
        for s in slots:
            for p, cell in enumerate(s.cells):
                by_cell.setdefault(cell, []).append((s.id, p))
        self.crossings: dict[int, list[tuple[int, int, int]]] = {s.id: [] for s in slots}
        for entries in by_cell.values():
            for sid, p in entries:
                for oid, q in entries:
                    if oid != sid:
                        self.crossings[sid].append((p, oid, q))
        self._dom: dict[int, int] = {}
        self._deadline = 0.0

    # ------------------------------------------------------------- domains
    def domain(self, sid: int) -> int:
        m = self._dom.get(sid)
        if m is None:
            s = self.slots[sid]
            masks = self.index.masks.get(s.length)
            m = self.index.all.get(s.length, 0)
            if masks is not None:
                for p, cell in enumerate(self.cells[sid]):
                    ch = self.letters.get(cell)
                    if ch is not None:
                        m &= masks[p].get(ch, 0)
                        if not m:
                            break
            self._dom[sid] = m
        return m

    def _place(self, sid: int, word: str) -> list[Cell]:
        placed = []
        for p, cell in enumerate(self.cells[sid]):
            if cell not in self.letters:
                self.letters[cell] = word[p]
                self.owner[cell] = sid
                placed.append(cell)
        self.assigned[sid] = word
        self.used_by[word] = sid
        for _, oid, _ in self.crossings[sid]:
            self._dom.pop(oid, None)
        return placed

    def _unplace(self, sid: int, word: str, placed: list[Cell]) -> None:
        for cell in placed:
            del self.letters[cell]
            del self.owner[cell]
        del self.assigned[sid]
        self.used_by.pop(word, None)
        for _, oid, _ in self.crossings[sid]:
            self._dom.pop(oid, None)

    def _check_small(self, sid: int, dom: int) -> set[int] | None:
        """Cheap arc-consistency test for a slot with few candidates: every
        empty cell must offer at least one letter the crossing slot accepts."""
        s = self.slots[sid]
        words = self.index.words[s.length]
        cand = list(iter_bits(dom))
        for p, oid, q in self.crossings[sid]:
            if oid in self.assigned or self.cells[sid][p] in self.letters:
                continue
            letters = {words[w][p] for w in cand}
            if len(letters) >= 20:
                continue
            omasks = self.index.masks[self.slots[oid].length][q]
            odom = self.domain(oid)
            if not any(odom & omasks.get(ch, 0) for ch in letters):
                return self._owners(sid) | self._owners(oid)
        return None

    def _stem_clash(self, word: str) -> int | None:
        """Slot holding a near-duplicate answer (BOARD vs BOARDED), if any."""
        for other, sid in self.used_by.items():
            a, b = (word, other) if len(word) <= len(other) else (other, word)
            if len(a) >= 3 and len(b) - len(a) <= 3 and b.startswith(a):
                return sid
        return None

    def _owners(self, sid: int) -> set[int]:
        """Assigned slots that put letters into slot `sid`."""
        return {self.owner[c] for c in self.cells[sid] if c in self.owner}

    # -------------------------------------------------------------- search
    def _candidates(self, sid: int, dom: int, conflict: set[int]) -> list[str]:
        s = self.slots[sid]
        words = self.index.words[s.length]
        scores = self.index.scores[s.length]
        open_cross = []
        for p, oid, q in self.crossings[sid]:
            if oid in self.assigned or self.cells[sid][p] in self.letters:
                continue
            o = self.slots[oid]
            open_cross.append((p, self.domain(oid), self.index.masks[o.length][q], oid))
        ranked = []
        examined = 0
        for wid in iter_bits(dom):
            if len(ranked) >= self.opt.top_k or examined >= self.opt.max_examine:
                break
            examined += 1
            word = words[wid]
            if word in self.used_by:
                conflict.add(self.used_by[word])
                continue
            clash = self._stem_clash(word)
            if clash is not None:
                conflict.add(clash)
                continue
            look = 0.0
            ok = True
            worst = 1 << 30
            for p, odom, omasks, oid in open_cross:
                c = (odom & omasks.get(word[p], 0)).bit_count()
                if c == 0:
                    ok = False
                    conflict |= self._owners(oid)
                    break
                look += math.log(c + 1)
                worst = min(worst, c)
            if not ok:
                continue
            if open_cross:
                look = 0.5 * look / len(open_cross) + 0.5 * math.log(worst + 1)
            key = (self.opt.score_weight * scores[wid] / 20.0
                   + self.opt.lookahead_weight * look
                   + self.opt.jitter * 5.0 * self.rng.random())
            ranked.append((key, word))
        ranked.sort(reverse=True)
        return [w for _, w in ranked]

    def _solve(self) -> set[int] | None:
        """Return None on success, else the conflict set (assigned slots
        responsible for the failure) for conflict-directed backjumping."""
        st = self.stats
        st.nodes += 1
        if st.nodes > self.opt.node_limit or (st.nodes & 63 == 0 and time.monotonic() > self._deadline):
            raise _OutOfBudget
        best = None
        for s in self.slots:
            if s.id in self.assigned:
                continue
            dom = self.domain(s.id)
            c = dom.bit_count()
            if c == 0:
                return self._owners(s.id)
            if c <= self.opt.small_domain:
                bad = self._check_small(s.id, dom)
                if bad is not None:
                    return bad
            # fewest options first, but long slots get priority: filling them
            # while they are still flexible avoids dead ends in the endgame
            key = (math.log(c) - self.opt.length_bias * s.length, -s.length)
            if best is None or key < best[0]:
                best = (key, s.id)
        if best is None:
            return None
        sid = best[1]
        conflict = self._owners(sid)
        for word in self._candidates(sid, self.domain(sid), conflict):
            placed = self._place(sid, word)
            sub = self._solve()
            self._unplace(sid, word, placed)
            if sub is None:
                self._place(sid, word)
                return None
            st.backtracks += 1
            if sid not in sub:
                return sub  # changing this slot cannot help: jump further back
            conflict |= sub
        conflict.discard(sid)
        conflict.discard(-1)
        return conflict

    def fill(self) -> dict[int, str] | None:
        t0 = time.monotonic()
        self._deadline = t0 + self.opt.time_limit
        try:
            ok = self._solve() is None
        except _OutOfBudget:
            ok = False
        except RecursionError:
            ok = False
        self.stats.seconds = time.monotonic() - t0
        return dict(self.assigned) if ok else None
