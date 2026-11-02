"""Grid geometry: black squares, slots (answer positions) and numbering."""
from __future__ import annotations

from dataclasses import dataclass

Cell = tuple[int, int]
Blocks = list[list[bool]]  # True = black square


@dataclass(frozen=True)
class Slot:
    id: int
    number: int
    direction: str  # "A" (across) or "D" (down)
    row: int
    col: int
    length: int

    @property
    def cells(self) -> list[Cell]:
        if self.direction == "A":
            return [(self.row, self.col + i) for i in range(self.length)]
        return [(self.row + i, self.col) for i in range(self.length)]

    @property
    def label(self) -> str:
        return f"{self.number}{'-Across' if self.direction == 'A' else '-Down'}"


def runs(line: list[bool]) -> list[tuple[int, int]]:
    """(start, length) of each maximal run of white squares in a row/column."""
    out, start = [], None
    for i, black in enumerate(line + [True]):
        if not black and start is None:
            start = i
        elif black and start is not None:
            out.append((start, i - start))
            start = None
    return out


def find_slots(blocks: Blocks, min_len: int = 2) -> list[Slot]:
    """Extract and number all across/down slots in standard crossword order."""
    rows, cols = len(blocks), len(blocks[0])

    def white(r: int, c: int) -> bool:
        return 0 <= r < rows and 0 <= c < cols and not blocks[r][c]

    slots: list[Slot] = []
    number = 0
    for r in range(rows):
        for c in range(cols):
            if not white(r, c):
                continue
            starts_a = not white(r, c - 1) and white(r, c + 1)
            starts_d = not white(r - 1, c) and white(r + 1, c)
            if not (starts_a or starts_d):
                continue
            number += 1
            if starts_a:
                n = 0
                while white(r, c + n):
                    n += 1
                if n >= min_len:
                    slots.append(Slot(len(slots), number, "A", r, c, n))
            if starts_d:
                n = 0
                while white(r + n, c):
                    n += 1
                if n >= min_len:
                    slots.append(Slot(len(slots), number, "D", r, c, n))
    return slots


def mirror(size: int, r: int, c: int) -> Cell:
    return size - 1 - r, size - 1 - c


def is_symmetric(blocks: Blocks) -> bool:
    n = len(blocks)
    return all(blocks[r][c] == blocks[n - 1 - r][n - 1 - c] for r in range(n) for c in range(n))


def is_connected(blocks: Blocks) -> bool:
    rows, cols = len(blocks), len(blocks[0])
    whites = [(r, c) for r in range(rows) for c in range(cols) if not blocks[r][c]]
    if not whites:
        return False
    seen = {whites[0]}
    stack = [whites[0]]
    while stack:
        r, c = stack.pop()
        for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if 0 <= nr < rows and 0 <= nc < cols and not blocks[nr][nc] and (nr, nc) not in seen:
                seen.add((nr, nc))
                stack.append((nr, nc))
    return len(seen) == len(whites)


def all_runs(blocks: Blocks) -> list[int]:
    lengths = [n for row in blocks for _, n in runs(list(row))]
    lengths += [n for c in range(len(blocks[0])) for _, n in runs([row[c] for row in blocks])]
    return lengths


def to_text(blocks: Blocks, letters: dict[Cell, str] | None = None) -> str:
    letters = letters or {}
    lines = []
    for r, row in enumerate(blocks):
        lines.append(" ".join("#" if b else letters.get((r, c), ".") for c, b in enumerate(row)))
    return "\n".join(lines)
