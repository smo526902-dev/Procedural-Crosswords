# Procedural Crosswords

Generates American-style crosswords (rotationally symmetric black squares, every letter
checked across *and* down) with a single difficulty dial, and lets you solve them in the
browser.

```
$ python -m crossword --level 3 --seed 42
Medium (level 3)  11x11  seed=42  quality=61.7  avg word score=67.3  [1.02s, 3 patterns]

T R A P # # S A I D #        ACROSS
H O B O # S E N S E D          1. Device in which something can be caught and penned  (4)  TRAP
O S L O # H E A L E R          5. Aforementioned  (4)  SAID
U S E D T O # L A M E          9. Bum  (4)  HOBO
...                           12. Capital and largest city of Norway  (4)  OSLO
```

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install fastapi uvicorn          # runtime
pip install pytest httpx puzpy       # tests (optional)
```

Generate from the command line:

```bash
python -m crossword --level 3 --seed 42            # print grid + clues with answers
python -m crossword --level 5 --hide-answers --puz expert.puz --html expert.html
python -m crossword --level 2 --size 13 --clue-tier 3 --aids check
```

Run the web solver at <http://localhost:8000>:

```bash
uvicorn server.app:app --reload
```

Run the tests:

```bash
python -m pytest
```

## Difficulty

One dial (1–5) sets four knobs. Each knob can be overridden on its own in the UI's
*Advanced* panel, from the CLI, or through the API.

| Level | Grid | Word obscurity floor | Clue style mix | Solver aids |
|---|---|---|---|---|
| 1 Easy | 5×5 | 55 (everyday words) | tier 1 | check, reveal, 2 starter letters |
| 2 Gentle | 9×9 | 45 | tiers 1–2 | check, reveal |
| 3 Medium | 11×11 | 40 | mostly tier 2 | check, reveal letter/word |
| 4 Hard | 13×13 | 30 | mostly tier 3 | check only |
| 5 Expert | 15×15 | 20 | tiers 3–4 | none |

* **Word obscurity:** every answer has a 0–100 score based on how often it appears in real
  text. The fill never goes below the floor and always prefers higher-scoring words.
* **Clue tiers:**
  1. Straight definitions and fill-in-the-blanks from the word's everyday sense
     (`"Iced ___ is a cooling drink"`).
  2. Single-word synonyms and categories (`Mouser`, `Feline, for one`).
  3. Less common senses and rarer synonyms (`Jazz fan, old-style`).
  4. Obscure senses plus hand-written misdirection (`Bank job?` → TELLER).
* **Aids:** Check (letter, word or puzzle) and Reveal (letter, word or puzzle) are offered
  only when the level allows them. *Give up* is always available.

## How it works

```
patterns.py  random symmetric block pattern (min 3 letters, connected, no 2x2 clumps)
    │
fill.py      constraint-satisfaction search over the slots
    │
quality.py   score the fill; keep the best of several attempts
    │
clues.py     choose one clue per answer to match the clue-tier mix
    │
export.py    JSON for the UI, Across Lite .puz, printable HTML
```

**The filler** (`crossword/fill.py`) does most of the work toward a satisfying grid:

* **Bitset index.** Every `(length, position, letter)` maps to a big-int bitset over the
  words, sorted best-first, so a pattern like `?A??E` resolves with a few ANDs.
* **Variable order.** The search fills the slot with the fewest candidates next, giving long
  slots priority while they are still flexible.
* **Value order.** It tries the best-scoring words first, re-ranked by a lookahead (how many
  options each crossing keeps), with seeded random jitter so every seed gives a new puzzle.
* **Pruning.** Forward checking, plus an arc-consistency test on nearly-forced slots, cuts
  dead ends early. Conflict-directed backjumping returns straight to the slot that caused a
  failure.
* **No repeats.** No answer appears twice, and no near-duplicate stems (BOARD with BOARDED).
* **Restarts.** Each attempt has a node budget. The generator moves on to fresh patterns and
  keeps the highest-quality fill, so a puzzle typically takes 0.2–3 s.

The same `level` and `seed` (and overrides) always produce the same puzzle. The web UI puts
them in the URL, so *Copy share link* reproduces the exact grid.

## The word list

`data/wordlist.tsv.gz` (~75k answers) is built offline by `data/build_dataset.py`:

* **Sources.** WordNet 3.0 supplies the vocabulary, definitions, synonyms, hypernyms and
  example sentences. `wordfreq` supplies the frequency scores.
* **Generated forms.** Plurals and verb forms (`-S`, `-ED`, `-ING`, irregulars such as
  TOOK/TAKEN) are generated, kept only when they're real words, and clued by inflecting the
  base word's synonyms and definitions.
* **Safety.** Offensive senses are never used for clues. Words whose main meaning is
  offensive are dropped. Clues never contain the answer or its stem.
* **Curated clues.** `data/curated_clues.tsv` holds hand-written clues: function words,
  irregular verbs and tricky wordplay. They take priority over generated ones. Adding lines
  there is the easiest way to make tier 3–4 clues more fun.

Rebuild the list (about a minute):

```bash
pip install nltk wordfreq
python -c "import nltk; nltk.download('wordnet')"
python data/build_dataset.py
```

See [`data/LICENSES.md`](data/LICENSES.md) for data attribution.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/presets` | difficulty presets, sizes, aids |
| POST | `/api/puzzle` | body: `{level, seed?, size?, min_score?, clue_tier?, aids?, starter_letters?}` |
| GET | `/api/puzzle/{id}` | puzzle JSON (recently generated puzzles are cached) |
| GET | `/api/puzzle/{id}/puz` | Across Lite download |
| GET | `/api/puzzle/{id}/print?answers=false` | printable page |

The puzzle JSON includes the answers so the browser can check work locally. This keeps the
server stateless; it isn't meant for competitive play.

## Known limitations

* WordNet has no names, brands or abbreviations. Short fill (3–4 letters) is therefore
  thinner than in a professional word list, which is why the big grids use a little more
  black than a newspaper puzzle.
* Generated clues are definitional. True wordplay comes only from the curated file.
