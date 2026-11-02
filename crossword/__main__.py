"""Command line: python -m crossword --level 3 --seed 42"""
from __future__ import annotations

import argparse
import json
import sys

from .difficulty import ALL_AIDS
from .generate import generate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="crossword", description="Generate an American-style crossword.")
    ap.add_argument("--level", type=int, default=3, help="difficulty 1 (easy) to 5 (expert)")
    ap.add_argument("--seed", type=int, help="random seed (same seed = same puzzle)")
    ap.add_argument("--size", type=int, choices=[5, 7, 9, 11, 13, 15], help="override grid size")
    ap.add_argument("--min-score", type=int, help="override word obscurity floor (0-100)")
    ap.add_argument("--clue-tier", type=int, choices=[1, 2, 3, 4], help="override clue difficulty")
    ap.add_argument("--aids", help=f"comma-separated subset of {','.join(ALL_AIDS)} (or 'none')")
    ap.add_argument("--hide-answers", action="store_true", help="print an unsolved grid")
    ap.add_argument("--json", action="store_true", help="print puzzle JSON")
    ap.add_argument("--puz", metavar="FILE", help="also write an Across Lite .puz file")
    ap.add_argument("--html", metavar="FILE", help="also write a printable HTML file")
    args = ap.parse_args(argv)

    aids = None
    if args.aids is not None:
        aids = [] if args.aids == "none" else [a.strip() for a in args.aids.split(",") if a.strip()]
    p = generate(args.level, args.seed, size=args.size, min_score=args.min_score,
                 clue_tier=args.clue_tier, aids=aids)
    if args.json:
        print(json.dumps(p.to_dict(), indent=2))
    else:
        d = p.difficulty
        print(f"{d.name} (level {d.level})  {p.size}x{p.size}  seed={p.seed}  "
              f"quality={p.quality.overall}  avg word score={p.quality.avg_word_score}  "
              f"[{p.stats['seconds']}s, {p.stats['attempts']} patterns]\n")
        print(p.to_text(show_answers=not args.hide_answers))
    if args.puz:
        from .export import to_puz
        with open(args.puz, "wb") as fh:
            fh.write(to_puz(p))
    if args.html:
        from .export import to_html
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(to_html(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
