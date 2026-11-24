# inky

**A writing tool assistant. It massages your typos — it does not correct you.**

inky exists because of a question — *"i hate typos. who is solving typos?"*
(Craig Weiss, 2026-11-24; charted as star #1 in `starchart.phext`) — and
because the commodity answer is broken in a specific way: every existing
corrector measures your writing against *the dictionary's* habits, so it
confidently "fixes" the words you invented on purpose, flattens the sentences
you built on purpose, and waves through the errors that actually matter.
inky measures your writing against **you**.

## The writer-model: vocabulary + sentence structure

A typo is a deviation from the writer's own lexicon and the writer's own
structural patterns — not from the dictionary's.

**Vocabulary layer.**
- Your coinages are protected. inky ships with a snapshot of Will Bickford's
  Singular lexicon (`protect.txt`); at runtime the *book* is computed as
  **your lexicon − the general dictionary − the known-typo table**: the words
  that are yours alone (`phext`, `phdoc`, `designbox`, `exocortex`). Book
  words are never flagged and never changed. ALL-CAPS coinages and camelCase
  identifiers are protected by rule as well.
- What remains suspect is tested against a general dictionary plus a table
  of classic typos (`teh`, `recieve`, `adress`, …).

**Structure layer.**
- Your sentence structure is style, not error. inky **never merges or splits
  your sentences, never reorders clauses, never "fixes" fragments,
  inversions, or punctuation rhythm.** The commodity corrector's deepest
  failure is structural flattening; inky's structural pass touches only what
  is mechanically unambiguous:
  - doubled words (`the the` → `the`; legitimate doubles like `had had` exempt),
  - spaces before punctuation, missing spaces after sentence punctuation,
  - unbalanced quotes/parens — flagged, never silently repaired.

## HIPPOS

The big errors that drift in under dictionary-era tools: **every word spelled
correctly, the sentence still wrong** — real-word substitutions (`form/from`,
`their/there/they're`, `its/it's`, `then/than`). Old tools wave them through
precisely because each word, alone, is fine. A hippo is only visible as a
deviation from what *this writer* does in *this construction* — which is why
the writer-model is the fence.

In this rung, confusables are **flag-only, never auto-fixed, whatever the
eval says**: their ambiguity is structural, and a wrong auto-fix is worse
than the hippo. The per-writer structural model (below) is the real fence.

## The engine

inky is built like a chess engine at the edge of the writer's board.

- **Move generation.** For each suspect word, candidate replacements are
  moves: classic-typo table entries (the *opening book* — for a known
  classic, the move list is just the entry, still scored), edit-distance
  neighbors, and — at hippo positions — the confusable set only.
- **Evaluation.** A feature-based eval with named, tunable weights (see
  `inky.py`, the `W_*` constants), scoring **whole lines** (complete
  sentences), never isolated words, on two axes:
  - *Lexicon fit* — the candidate's standing in **your** lexicon: book
    membership is the strongest signal; frequency in your own usage
    (`--lexicon`, `--corpus`) next.
  - *Structure fit* — same word class, similar length/syllable count (your
    sentence's rhythm survives), and fit to your own local pairings
    (bigrams from your corpus).
  - Dictionary frequency enters only as `W_DICT_FREQ` — **explicitly the
    weakest signal in the eval**, a tiebreaker prior, never the driver.
  - A hippo left standing costs the line `W_HIPPO`; keeping a non-word
    costs `W_NONWORD`.
- **Search.** A replacement changes the context its neighbors are judged in,
  so inky evaluates *lines*, not moves: beam search (width 8) over one
  sentence's suspects, then a quiescence pass that re-scores finalists with
  full context. Hippo positions get extra depth — their full confusable set
  is always carried through the beam. Document-wide search is roadmap.
- **Opening book.** Your frequent constructions and pet phrases are the
  book. Lines you play are never flagged for leaving book.
- **Analysis mode is the default relationship.** Like an engine at the
  board's edge, inky shows lines with their evals; **the writer moves.**
  Auto-apply is the narrow exception: the winning line must clear
  `APPLY_THRESHOLD`, every applied change must individually clear
  `MOVE_THRESHOLD` in that line's full context **and** beat the runner-up
  move at its own position by `APPLY_MARGIN` (a tie at the top is
  ambiguity, and ambiguity is flagged, never applied), and no hippo is
  ever auto-changed. A shaky suspect never holds certain fixes hostage —
  it is left as written and flagged.

### Tiers — the engine's spoken language

Scored lines are reported in named tiers, not raw numbers; the numeric eval
rides underneath for anyone who wants it.

| tier | meaning |
| --- | --- |
| **blunder** | the line makes things worse |
| **dubious** | playable only with a reason |
| **playable** | sound, unremarkable |
| **good** | the engine's best verdict on its own suggestions |
| **god-tier** | **reserved** — see below |

`god-tier` is the top of the scale and is reserved by design: **the writer's
own book constructions live there by definition.** The engine's best
possible verdict on its own suggestion is that it reaches the tier the
writer's hand already occupies.

### The author's test

The suite's anchor is the author's own live test (2026-11-24): the sentence
*"hippos drift in too easily with old tools"* is correct as written — `too`
is the excess sense, correctly used — and inky must return it
**byte-identical**. A corrector that touches this sentence has failed.

## Usage

```
python3 inky.py [FILE]            # analysis + narrow auto-fixes; text to stdout,
                                  # report to stderr (or --report FILE)
python3 inky.py --check [FILE]    # analysis only; modify nothing; exit 1 on findings
python3 inky.py --corpus my.txt   # score against your own usage (frequencies + pairings)
python3 inky.py --lexicon my.txt  # extra writer wordlist (word [count] per line)
python3 inky.py --protect f.txt   # extra protect-list files
cat draft.txt | python3 inky.py - # stdin works; bytes round-trip exactly
```

Phext safety: input is handled as bytes; phext structural bytes (delimiters
0x01, 0x17–0x1F) and coordinate text pass through untouched — inky only ever
replaces whole word tokens inside prose segments.

## Data

- `words-en.txt` — vendored fallback dictionary (79,013 forms), extracted
  2026-11-24 from the hunspell `en_US` dictionary on aletheia-core with
  affix flags stripped. At runtime inky prefers a system dictionary
  (`/usr/share/hunspell/en_US.dic`, `/usr/share/dict/words`, `$INKY_DICT`)
  and generates regular inflections in the loader.
- `protect.txt` — snapshot of the writer's Singular lexicon (46k entries):
  `words.txt` + `words-authored.txt` from the Singular skill, the
  singular-coined tracker headwords, and the observed coinages in
  `phext/singular-new-words.md`. Will's new words are always approved; the
  snapshot refreshes from those sources.

## The next rungs (roadmap)

- **The structural model.** The shipped eval reads structure locally —
  class, rhythm, pairings. The next rung is a per-writer structural model:
  the writer's own corpus as a structural fingerprint, deviations measured
  against *his* patterns at both the word and sentence level. That is the
  real hippo fence.
- **The learning loop.** Every accept/reject is training data: the eval's
  weights tune toward the writer over time — NNUE-style, an eval learned
  from the writer's own games.
- **Wider search.** Beam over paragraphs and documents, not just sentences.

## Tests

```
python3 test_inky.py   # 15 tests: pass-through anchors, fixes, hippos, scoring, CLI
```

MIT licensed (see `LICENSE`). Home: `wbic16/inky`, branch `exo`.
