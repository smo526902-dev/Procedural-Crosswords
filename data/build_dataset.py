"""Build the scored word + tiered clue list used by the generator.

Sources
-------
* WordNet 3.0 (via NLTK): vocabulary, definitions, synonyms, hypernyms and
  example sentences.  WordNet license: https://wordnet.princeton.edu/license-and-commercial-use
* wordfreq: corpus frequency (Zipf scale) used as the "obscurity" score.
* data/curated_clues.tsv: hand-written clues (function words, irregular verb
  forms, and misdirection / wordplay clues).  These always take priority.

Output
------
data/wordlist.tsv.gz with one row per answer:

    WORD <tab> score(0-100) <tab> flags <tab> tier1 <tab> tier2 <tab> tier3 <tab> tier4

Clue tiers: 1 = straightforward, 2 = moderate, 3 = tricky / less common sense,
4 = expert (rare senses, obscure synonyms, wordplay).  A tier may be empty.

Flags: P = proper noun, M = multiword phrase, I = inflected form, C = curated.

Run:  NLTK_ALLOW_PROXIED_URLOPEN=1 python data/build_dataset.py
(needs `pip install nltk wordfreq` and `nltk.download('wordnet')`).
"""
from __future__ import annotations

import gzip
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from nltk.corpus import wordnet as wn
from wordfreq import zipf_frequency

HERE = Path(__file__).resolve().parent
OUT = HERE / "wordlist.tsv.gz"
CURATED = HERE / "curated_clues.tsv"

MIN_LEN, MAX_LEN = 3, 15
MIN_ZIPF = 1.5           # below this a word is too obscure to ever use
MIN_FORM_ZIPF = 2.0      # generated inflections must be at least this common

BAD_DOMAINS = {"obscenity.n.02", "ethnic_slur.n.01", "disparagement.n.01",
               "vulgarism.n.01", "obscenity.n.01"}
BAD_GLOSS = re.compile(r"\b(offensive|obscene|vulgar|slur|derogatory|disparaging|"
                       r"sexual intercourse|genitals?|penis|vagina|feces|excrement)\b", re.I)
SKIP_CLUE_DOMAINS = {"slang.n.02", "archaism.n.01", "combining_form.n.01",
                     "colloquialism.n.01", "trademark.n.02"}
# Extra words we never want in a grid, even if WordNet lists a clean sense.
BLOCKLIST = set("""
ASS ASSES BITCH COCK COCKS CUNT DICK DICKS FAG FUCK FUCKS FUCKED FUCKING PISS PISSED
SHIT SHITS TIT TITS TITTY WHORE SLUT NIGGER NIGGA SPIC KIKE CHINK GOOK RAPE RAPED
RAPIST RAPING KILLER NAZI HOMO DYKE TWAT PRICK BONER CRAP PORN PORNO SEX SEXY
""".split())

STOPWORDS = set("""
a an the of or and to in on at by for with from as is be that which who
its it's one's someone's something's some any not no into out up over
""".split())


def norm(lemma: str) -> str:
    """WordNet lemma -> grid answer (A-Z only)."""
    return re.sub(r"[^A-Za-z]", "", lemma).upper()


def zipf(text: str) -> float:
    return zipf_frequency(text.replace("_", " "), "en")


def score_from_zipf(z: float) -> int:
    # zipf 1.0 -> 0, zipf 6.0+ -> 100
    return int(round(max(0.0, min(1.0, (z - 1.0) / 5.0)) * 100))


def stems(word: str) -> set[str]:
    """Prefixes that must not appear in a clue for `word` (answer leakage)."""
    w = word.lower()
    out = {w}
    if len(w) >= 5:
        out.add(w[: max(4, len(w) - 3)])
    return out


def leaks(clue: str, banned: set[str], answer: str = "") -> bool:
    toks = re.findall(r"[a-z]+", clue.lower())
    joined = "".join(toks)
    for b in banned:
        if len(b) >= 4 and b in joined:
            return True
        if any(t == b or (len(b) >= 4 and t.startswith(b)) for t in toks):
            return True
    for a in (x for x in banned if len(x) >= 5 or x.isalpha()):
        # clue words that are a big chunk of the answer: RUN in RUNNING,
        # CREAM in ICECREAM
        for t in toks:
            if len(t) >= 4 and t in a:
                return True
            if len(a) >= 3 and a in t and a not in STOPWORDS:
                return True  # TEATIME for TEA
            if len(t) == 3 and t not in STOPWORDS and (a.startswith(t) or a.endswith(t)):
                return True
    return False


# ---------------------------------------------------------------- inflection
EXC_V = wn._exception_map["v"]  # inflected -> [base]
EXC_N = wn._exception_map["n"]
V_FORMS: dict[str, dict[str, str]] = defaultdict(dict)  # base -> {S, ED, ING, IRR}
for form, bases in EXC_V.items():
    for b in bases:
        if form.endswith("ing"):
            V_FORMS[b].setdefault("ING", form)
        elif form.endswith("ed"):
            V_FORMS[b].setdefault("ED", form)
        elif form.endswith("s") and form.startswith(b[:2]) and len(form) <= len(b) + 2:
            V_FORMS[b].setdefault("S", form)
        else:
            # irregular past / participle: prefer the past tense (not -n/-en)
            prev = V_FORMS[b].get("IRR")
            if prev is None or (prev.endswith("n") and not form.endswith("n")):
                V_FORMS[b]["IRR"] = form
V_FORMS.update({
    "be": {"S": "is", "IRR": "was", "ING": "being"},
    "have": {"S": "has", "IRR": "had", "ING": "having"},
    "do": {"S": "does", "IRR": "did", "ING": "doing"},
    "go": {"S": "goes", "IRR": "went", "ING": "going"},
})
IRREG_PLURAL_BASES = {b for bases in EXC_N.values() for b in bases}
# base -> irregular forms (took/taken, mice, ...) that become answers themselves
V_IRR: dict[str, set[str]] = defaultdict(set)
for form, bases in EXC_V.items():
    if not form.endswith(("ing", "ed", "s")) and "_" not in form:
        for b in bases:
            V_IRR[b].add(form)
N_IRR: dict[str, set[str]] = defaultdict(set)
for form, bases in EXC_N.items():
    if "_" not in form:
        for b in bases:
            if form != b:
                N_IRR[b].add(form)
VOWELS = set("aeiou")


def _best(cands: list[str]) -> str | None:
    cands = [c for c in dict.fromkeys(cands) if c]
    if not cands:
        return None
    best = max(cands, key=zipf)
    return best if zipf(best) >= MIN_FORM_ZIPF else None


def plural(w: str) -> str | None:
    if w in IRREG_PLURAL_BASES or w.endswith("s") and not w.endswith(("ss", "us")):
        return None
    if w.endswith(("s", "x", "z", "ch", "sh")):
        return _best([w + "es"])
    if w.endswith("y") and len(w) > 1 and w[-2] not in VOWELS:
        return _best([w[:-1] + "ies"])
    return _best([w + "s"])


def verb_form(w: str, kind: str, validate: bool = True) -> str | None:
    """kind in S / ED / ING.  ED returns the irregular past where one exists."""
    forms = V_FORMS.get(w, {})
    if kind == "ED" and "IRR" in forms:
        return forms["IRR"] if not validate else None
    if kind in forms:
        return forms[kind]
    if kind == "S":
        if w.endswith(("s", "x", "z", "ch", "sh", "o")):
            c = w + "es"
        elif w.endswith("y") and len(w) > 1 and w[-2] not in VOWELS:
            c = w[:-1] + "ies"
        else:
            c = w + "s"
        return _best([c]) if validate else c
    cvc = len(w) >= 3 and w[-1] not in VOWELS | {"w", "x", "y"} and w[-2] in VOWELS and w[-3] not in VOWELS
    if kind == "ED":
        if w.endswith("e"):
            cands = [w + "d"]
        elif w.endswith("y") and w[-2] not in VOWELS:
            cands = [w[:-1] + "ied"]
        else:
            cands = [w + "ed"] + ([w + w[-1] + "ed"] if cvc else [])
    else:  # ING
        if w.endswith("ie"):
            cands = [w[:-2] + "ying"]
        elif w.endswith("e") and not w.endswith(("ee", "ye", "oe")):
            cands = [w[:-1] + "ing"]
        else:
            cands = [w + "ing"] + ([w + w[-1] + "ing"] if cvc else [])
    if validate:
        return _best(cands)
    return max(cands, key=zipf)


def inflect_phrase(phrase: str, kind: str) -> str | None:
    """Inflect the first word of a verb phrase ('move fast' -> 'moved fast')."""
    if re.search(r"\b(and|or)\b|,", phrase):
        return None  # "lodge and take meals" would need every verb inflected
    parts = phrase.split(" ", 1)
    head = parts[0].lower()
    if not wn.synsets(head, pos="v"):
        return None
    if kind == "PL":
        return None
    if kind == "EDR":
        # clue for an irregular past/participle answer (TAKEN, TOOK): only a
        # regular -ed head reads correctly as both tenses
        if "IRR" in V_FORMS.get(head, {}):
            return None
        kind = "ED"
    form = V_FORMS.get(head, {}).get("IRR") if kind == "ED" and "IRR" in V_FORMS.get(head, {}) \
        else verb_form(head, kind, validate=False)
    if not form or zipf(form) < 2.5:
        return None
    return form + ((" " + parts[1]) if len(parts) > 1 else "")


# ---------------------------------------------------------------- clue text
SEPARATORS = [", ", " that ", " which ", " who ", " especially ", " usually ",
              " typically ", " often ", " as in ", " in order to ", " so that "]


def clean_gloss(gloss: str, pos: str) -> str | None:
    g = gloss.split(";")[0]
    g = re.sub(r"\([^)]*\)", "", g)
    g = re.sub(r"\s+", " ", g).strip(" ,.:")
    g = re.sub(r"^(any|one|either|each) of (the )?(various|several|numerous|many|a number of|"
               r"a group of|a class of|a genus of|a family of)?\s*", "", g, flags=re.I)
    if pos == "n":
        g = re.sub(r"^(a|an|the|any)\s+", "", g, flags=re.I)
    words = g.split()
    if len(words) > 9:
        cut = None
        for sep in SEPARATORS:
            i = g.find(sep)
            if i > 0 and len(g[:i].split()) >= 3 and (cut is None or i < cut):
                cut = i
        if cut is not None:
            g = g[:cut].strip(" ,")
    if g.split(" ", 1)[0].lower() in {"sometimes", "usually", "often", "especially", "used",
                                         "formerly", "also", "typically", "known", "called", "found",
                                         "native", "related", "named", "of"}:
        return None
    if not g or len(g.split()) > 11 or len(g) > 70 or '"' in g or "`" in g:
        return None
    return g


def cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def display(lemma: str) -> str:
    return lemma.replace("_", " ")


def blank_example(example: str, form: str) -> str | None:
    """Turn a WordNet example sentence into a fill-in-the-blank clue."""
    toks = re.findall(r"[A-Za-z0-9']+|[^A-Za-z0-9'\s]", example)
    hits = [i for i, t in enumerate(toks) if t.lower() == form.lower()]
    if len(hits) != 1 or len([t for t in toks if t.isalpha()]) > 10:
        return None
    toks[hits[0]] = "___"
    s = " ".join(toks)
    s = re.sub(r"\s+([,.;:!?'])", r"\1", s).replace(" n't", "n't").strip(" .;")
    s = re.sub(r"(\w) - (\w)", r"\1-\2", s)  # "non - members" -> "non-members"
    if len(s) > 60 or '"' in s:
        return None
    return f'"{cap(s)}"'


# ---------------------------------------------------------------- collection
@dataclass
class Entry:
    word: str
    zipf: float
    flags: set[str] = field(default_factory=set)
    # tier -> list of (preference, clue).  lower preference wins.
    clues: dict[int, list[tuple[float, str]]] = field(default_factory=lambda: defaultdict(list))

    def add(self, tier: int, clue: str, pref: float = 0.0) -> None:
        tier = max(1, min(4, tier))
        clue = re.sub(r"[\t\n]+", " ", cap(clue.strip()))
        if clue and all(c != clue for _, c in self.clues[tier]):
            self.clues[tier].append((pref, clue))


entries: dict[str, Entry] = {}
banned_for: dict[str, set[str]] = defaultdict(set)


def entry(word: str, z: float) -> Entry:
    e = entries.get(word)
    if e is None:
        e = entries[word] = Entry(word, z)
    else:
        e.zipf = max(e.zipf, z)
    return e


def sense_ok(s) -> bool:
    if any(d.name() in BAD_DOMAINS for d in s.usage_domains()):
        return False
    return not BAD_GLOSS.search(s.definition())


def senses_for(lemma_name: str):
    lemmas = wn.lemmas(lemma_name)
    # WordNet orders by frequency already; sort by tagged count as a tiebreak.
    return sorted(enumerate(lemmas), key=lambda il: (-il[1].count(), il[0]))


GENERIC_HYPERNYMS = set("""
person individual someone somebody mortal soul organism being thing entity object
physical_object whole unit act deed human_action human_activity activity abstraction
group grouping artifact artefact matter state event attribute quality property process
location region structure instrumentality measure quantity relation communication
cognition content change happening causal_agent physical_entity part portion
""".split())


def first_clean_lemma(synsets, banned: set[str]) -> str | None:
    for h in synsets:
        if any(l.name().lower() in GENERIC_HYPERNYMS for l in h.lemmas()):
            continue
        for l in h.lemmas():
            n = l.name()
            if not re.search(r"[^A-Za-z_\-]", n) and not leaks(display(n), banned) and zipf(n) >= 2.5:
                return display(n)
    return None


def sense_difficulty(lemma, rank: int, mixed_case: bool) -> int:
    """0 = the everyday sense of a word, higher = progressively more obscure."""
    s = lemma.synset()
    d = 0 if rank == 0 else (1 if rank <= 2 else 2)
    if rank >= 1 and lemma.count() == 0:
        d += 1
    if any(dom.name() in SKIP_CLUE_DOMAINS for dom in s.usage_domains()):
        d += 1
    if mixed_case and lemma.name()[0].isupper():
        d += 1 if rank == 0 else 2  # TELLER the physicist is not an easy clue
    return min(d, 3)


def add_sense_clues(e: Entry, lemma, rank: int, banned: set[str], kind: str | None = None,
                    mixed_case: bool = False) -> None:
    """Add clues for one sense of a lemma.  kind: None (base), PL, S, ED, ING.

    tier = 1 + sense difficulty + clue-type difficulty, where definitions and
    fill-in-the-blanks are the most direct, then synonyms / categories, with
    rare synonyms pushed up further.
    """
    s = lemma.synset()
    pos = s.pos()
    d = sense_difficulty(lemma, rank, mixed_case)

    def add(type_d: int, text: str | None, pref: float) -> None:
        if text and not leaks(text, banned):
            e.add(1 + d + type_d, text, pref=rank * 10 + pref)

    def inflect(text: str) -> str | None:
        if kind is None:
            return text
        if kind == "PL":
            if " " in text:
                return None
            p = plural(text.lower())
            return (text[0] + p[1:]) if p else None
        return inflect_phrase(text, kind)

    # 1. synonyms (other lemmas in the synset; looser "similar" adjectives)
    syns = [(l, 0) for l in s.lemmas() if norm(l.name()) != e.word]
    if pos in ("a", "s"):
        syns += [(sim.lemmas()[0], 1) for sim in s.similar_tos()[:3]]
    for l, loose in syns:
        n = l.name()
        if re.search(r"[^A-Za-z_\-]", n) or n[0].isupper() != lemma.name()[0].isupper():
            continue
        z = zipf(n)
        if z < 2.0 or (len(n) <= 3 and z < 3.0):
            continue
        rare = (1 if z < 3.5 else 0) + (1 if z < 2.5 else 0)
        add(1 + loose + rare - (1 if z >= 5.0 and rank == 0 and not loose else 0),
            inflect(display(n)), pref=-z)

    # 2. definition
    g = clean_gloss(s.definition(), pos)
    if g:
        if kind in ("S", "ED", "ING", "EDR"):
            g = inflect_phrase(g, kind) if pos == "v" else None
        elif kind == "PL":
            g = None
        add(0, g, pref=len(g.split()) * 0.3 if g else 0)

    # 3. category clues for nouns ("Feline, for one" / "Some felines")
    if pos == "n" and kind in (None, "PL"):
        hyp = first_clean_lemma(s.hypernyms() or s.instance_hypernyms(), banned)
        if hyp:
            hard = 1 if zipf(hyp) < 3.2 else 0
            if kind is None:
                if s.instance_hypernyms() or (rank + len(e.word)) % 2:
                    text = f"{cap(hyp)}, for one"
                else:
                    text = f"Kind of {hyp}"
                add(hard + (1 if rank else 0), text, pref=2.0)
            elif " " not in hyp:
                p = plural(hyp.lower())
                add(hard + (1 if rank else 0), f"Some {p}" if p else None, pref=2.0)

    # 4. fill-in-the-blank from example sentences (classic easy clue)
    form = e.word.lower()
    for ex in s.examples()[:3]:
        b = blank_example(ex, form)
        if b:
            add(0, b, pref=0.5)
            break


def build() -> None:
    names = sorted(set(wn.all_lemma_names()))
    name_set = set(names)
    print(f"{len(names)} lemma names", file=sys.stderr)
    for i, name in enumerate(names):
        if i % 20000 == 0:
            print(f"  {i}/{len(names)}  entries={len(entries)}", file=sys.stderr)
        if re.search(r"[0-9./]", name):
            continue
        word = norm(name)
        if not (MIN_LEN <= len(word) <= MAX_LEN) or word in BLOCKLIST:
            continue
        lemma_senses = senses_for(name)
        if not lemma_senses:
            continue
        # Abbreviations (all caps lemma) and lemmas whose every sense is bad.
        real_names = {l.name() for _, l in lemma_senses}
        if all(re.sub(r"[^A-Za-z]", "", n).isupper() for n in real_names):
            continue
        # Drop a word whose main meaning is offensive; otherwise just never
        # clue it by its offensive senses (KNOW, BED, QUEEN keep their place).
        bad = [not sense_ok(l.synset()) for _, l in lemma_senses]
        if bad[0] or sum(bad) * 2 > len(bad):
            BLOCKLIST.add(word)
            entries.pop(word, None)
            continue
        lemma_senses = [il for il, b in zip(lemma_senses, bad) if not b]
        multi = "_" in name or "-" in name
        parts = re.split(r"[_\-]", name)
        if multi and parts[0][:1].isupper() and parts[-1][:1].islower() and len(parts) == 2:
            continue  # taxonomic binomial such as Salmo_salar
        z = zipf(name)
        if multi:
            # wordfreq overrates phrases built from common words ("save all");
            # discount them, but credit phrases that WordNet's corpus tags.
            count = sum(l.count() for _, l in lemma_senses)
            # People writing the phrase solid ("icecream", "hotdog") is a good
            # sign it is a real, lively unit rather than two words.
            solid = zipf_frequency("".join(parts).lower(), "en")
            z = z - 2.0 + min(1.5, 0.5 * math.log2(1 + count)) + min(1.5, 0.6 * solid)
        if z < MIN_ZIPF:
            continue
        banned = stems(word) | {p.lower() for p in re.split(r"[_\-]", name) if len(p) >= 3}
        e = entry(word, z)
        if multi:
            e.flags.add("M")
        is_proper = all(l.name()[0].isupper() for _, l in lemma_senses)
        if is_proper:
            e.flags.add("P")
        mixed_case = not is_proper and any(l.name()[0].isupper() for _, l in lemma_senses)
        seen_synsets = set()
        rank = 0
        for _, l in lemma_senses:
            if l.synset() in seen_synsets:
                continue
            seen_synsets.add(l.synset())
            add_sense_clues(e, l, rank, banned, mixed_case=mixed_case)
            rank += 1

        # Inflected forms of single, lower-case words.
        if multi or is_proper:
            continue
        base = name.lower()
        noun_senses = [l for _, l in lemma_senses if l.synset().pos() == "n" and l.name()[0].islower()]
        verb_senses = [l for _, l in lemma_senses if l.synset().pos() == "v"]
        forms: list[tuple[str, str, list]] = []
        if noun_senses:
            p = plural(base)
            if p:
                forms.append(("PL", p, noun_senses))
            for f in N_IRR.get(base, ()):
                forms.append(("PL", f, noun_senses))
        if verb_senses:
            for kind in ("S", "ED", "ING"):
                f = verb_form(base, kind)
                if f:
                    forms.append((kind, f, verb_senses))
            for f in V_IRR.get(base, ()):
                forms.append(("EDR", f, verb_senses))
        for kind, f, senses in forms:
            fw = norm(f)
            if not (MIN_LEN <= len(fw) <= MAX_LEN) or fw in BLOCKLIST:
                continue
            fz = zipf(f)
            if fz < MIN_FORM_ZIPF:
                continue
            fe = entry(fw, fz)
            if f not in name_set:
                fe.flags.add("I")
            fbanned = banned | stems(fw)
            for r, l in enumerate(senses[:6]):
                add_sense_clues(fe, l, r, fbanned, kind=kind)

    # Curated clues override / extend everything.
    for line in CURATED.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        word, tier, clue = line.split("\t")
        word = norm(word)
        e = entry(word, zipf(word.lower()))
        e.flags.add("C")
        e.add(int(tier), clue, pref=-100.0)

    rows = []
    for w, e in entries.items():
        if w in BLOCKLIST:
            continue
        tiers = []
        seen_clues: set[str] = set()
        for t in (1, 2, 3, 4):
            opts = [o for o in sorted(e.clues.get(t, [])) if o[1] not in seen_clues]
            seen_clues.update(c for _, c in opts[:2])
            tiers.append(opts[0][1] if opts else "")
            # keep a second option in the same tier for variety
            if len(opts) > 1:
                tiers[-1] += " || " + opts[1][1]
        if not any(tiers):
            continue
        score = score_from_zipf(e.zipf)
        if "P" in e.flags:
            score -= 5
        if "C" in e.flags:
            score = max(score, 40)
        rows.append((w, max(0, min(100, score)), "".join(sorted(e.flags)), *tiers))
    rows.sort()
    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write("\t".join(map(str, r)) + "\n")
    print(f"wrote {len(rows)} answers to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    build()
