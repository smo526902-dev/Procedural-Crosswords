"""Export puzzles: Across Lite .puz (binary) and a printable HTML page."""
from __future__ import annotations

import html
import struct

from .generate import Puzzle

ENC = "latin-1"


def _cksum(data: bytes, ck: int = 0) -> int:
    for b in data:
        ck = ((ck >> 1) | ((ck & 1) << 15)) & 0xFFFF
        ck = (ck + b) & 0xFFFF
    return ck


def _s(text: str) -> bytes:
    return text.encode(ENC, errors="replace")


def to_puz(p: Puzzle, title: str | None = None, author: str = "Procedural Crosswords") -> bytes:
    """Serialize to the Across Lite .puz format (version 1.3)."""
    n = p.size
    solution = "".join("." if ch is None else ch for row in p.solution for ch in row).encode(ENC)
    fill = "".join("." if ch is None else "-" for row in p.solution for ch in row).encode(ENC)
    # Across Lite wants clues ordered by number, across before down.
    ordered = sorted(p.entries, key=lambda e: (e.number, e.direction != "A"))
    clues = [_s(e.clue) for e in ordered]
    title_b = _s(title or f"{p.difficulty.name} crossword #{p.id}")
    author_b = _s(author)
    copyright_b = b""
    notes_b = _s(f"Level {p.difficulty.level}, seed {p.seed}")

    w_h_etc = struct.pack("<BBHHH", n, n, len(clues), 1, 0)  # bitmask 1, unscrambled
    c_cib = _cksum(w_h_etc)

    def text_cksum(ck: int) -> int:
        for s in (title_b, author_b, copyright_b):
            if s:
                ck = _cksum(s + b"\0", ck)
        for c in clues:
            ck = _cksum(c, ck)
        if notes_b:
            ck = _cksum(notes_b + b"\0", ck)
        return ck

    c_sol, c_grid, c_part = _cksum(solution), _cksum(fill), text_cksum(0)
    overall = text_cksum(_cksum(fill, _cksum(solution, c_cib)))
    magic_lo = bytes([0x49 ^ (c_cib & 0xFF), 0x43 ^ (c_sol & 0xFF),
                      0x48 ^ (c_grid & 0xFF), 0x45 ^ (c_part & 0xFF)])
    magic_hi = bytes([0x41 ^ (c_cib >> 8), 0x54 ^ (c_sol >> 8),
                      0x45 ^ (c_grid >> 8), 0x44 ^ (c_part >> 8)])
    header = (struct.pack("<H", overall) + b"ACROSS&DOWN\0" + struct.pack("<H", c_cib)
              + magic_lo + magic_hi + b"1.3\0" + b"\0\0" + struct.pack("<H", 0) + b"\0" * 12
              + w_h_etc)
    assert len(header) == 0x34
    body = solution + fill + title_b + b"\0" + author_b + b"\0" + copyright_b + b"\0"
    body += b"".join(c + b"\0" for c in clues) + notes_b + b"\0"
    return header + body


def to_html(p: Puzzle, show_answers: bool = False) -> str:
    """A self-contained printable page (grid + clue lists)."""
    numbers = {(e.row, e.col): e.number for e in p.entries}
    cells = []
    for r, row in enumerate(p.solution):
        tds = []
        for c, ch in enumerate(row):
            if ch is None:
                tds.append('<td class="b"></td>')
                continue
            num = numbers.get((r, c))
            letter = ch if show_answers or (r, c) in p.givens else ""
            tds.append(f'<td><span class="n">{num or ""}</span><span class="l">{letter}</span></td>')
        cells.append("<tr>" + "".join(tds) + "</tr>")

    def clue_list(entries):
        return "".join(f"<li><b>{e.number}</b> {html.escape(e.clue)}</li>" for e in entries)

    d = p.difficulty
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{d.name} crossword {p.id}</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; color: #111; background: #fff; }}
h1 {{ font-size: 20px; margin: 0 0 4px; }} .meta {{ color: #555; font-size: 13px; margin-bottom: 16px; }}
.wrap {{ display: flex; gap: 28px; flex-wrap: wrap; align-items: flex-start; }}
table {{ border-collapse: collapse; }}
td {{ width: 32px; height: 32px; border: 1px solid #222; position: relative; padding: 0; }}
td.b {{ background: #111; }}
.n {{ position: absolute; top: 1px; left: 2px; font-size: 9px; font-family: Arial, sans-serif; }}
.l {{ display: block; text-align: center; line-height: 34px; font-size: 18px; font-family: Arial, sans-serif; }}
.clues {{ columns: 2; column-gap: 28px; max-width: 640px; font-size: 13px; }}
h2 {{ font-size: 14px; margin: 0 0 6px; }} ol {{ list-style: none; padding: 0; margin: 0 0 14px; }}
li {{ margin-bottom: 3px; break-inside: avoid; }}
@media print {{ body {{ margin: 0; }} }}
</style></head><body>
<h1>{d.name} crossword</h1>
<div class="meta">Level {d.level} &middot; {p.size}&times;{p.size} &middot; seed {p.seed}</div>
<div class="wrap"><table>{''.join(cells)}</table>
<div class="clues"><h2>Across</h2><ol>{clue_list(p.across)}</ol>
<h2>Down</h2><ol>{clue_list(p.down)}</ol></div></div>
</body></html>
"""
