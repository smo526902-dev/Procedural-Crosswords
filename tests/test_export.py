import struct

import pytest

from crossword.export import _cksum, to_html, to_puz
from crossword.generate import generate


@pytest.fixture(scope="module")
def puzzle(wordlist):
    return generate(2, 99)


def test_puz_header_and_checksums(puzzle):
    data = to_puz(puzzle)
    assert data[2:14] == b"ACROSS&DOWN\0"
    w, h, nclues = struct.unpack("<BBH", data[0x2C:0x30])
    assert (w, h) == (puzzle.size, puzzle.size)
    assert nclues == len(puzzle.entries)
    cib = _cksum(data[0x2C:0x34])
    assert struct.unpack("<H", data[0x0E:0x10])[0] == cib
    sol = data[0x34:0x34 + w * h].decode()
    assert sol == "".join(ch or "." for row in puzzle.solution for ch in row)


def test_puz_loads_in_puzpy(puzzle):
    puz = pytest.importorskip("puz")
    data = to_puz(puzzle)
    p = puz.load(data)
    assert p.global_cksum() == struct.unpack("<H", data[:2])[0]
    assert p.magic_cksum() == int.from_bytes(data[0x10:0x18], "little")
    numbering = p.clue_numbering()
    ours = {(e.number, e.direction): e.clue for e in puzzle.entries}
    for c in numbering.across:
        assert ours[(c["num"], "A")] == c["clue"]
    for c in numbering.down:
        assert ours[(c["num"], "D")] == c["clue"]


def test_html_has_grid_and_clues(puzzle):
    page = to_html(puzzle)
    assert page.count('class="b"') == sum(ch is None for row in puzzle.solution for ch in row)
    for e in puzzle.entries[:5]:
        assert e.clue.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;") in page
    assert puzzle.entries[0].answer not in page.split("<table>")[1].split("</table>")[0]
