#!/usr/bin/env python3
"""inky — a writing tool assistant. It massages your typos; it does not correct you.

inky is built like a chess engine sitting at the edge of the writer's board:
it generates candidate replacements (moves), evaluates whole lines with a
feature-based eval (lexicon fit + structure fit), searches lines with a beam,
and shows its analysis. The writer moves. Auto-apply is a narrow exception:
the winning line must clear a high threshold, every applied change must
clear the move threshold in that line's context and beat the runner-up move
at its own position by a clear margin, and no hippo is ever auto-changed.

The writer-model is two-layered — vocabulary AND sentence structure:
  * A typo is a deviation from the WRITER'S OWN lexicon, not the dictionary's.
    His Singular coinages are protected: never flagged, never changed.
  * His sentence structure is style, not error: inky never merges or splits
    his sentences, never reorders clauses, never "fixes" fragments,
    inversions, or punctuation rhythm.
  * HIPPOS — real-word substitutions (form/from, their/there) where every
    word is spelled correctly and the sentence is still wrong — are
    FLAG-ONLY, always. A wrong auto-fix is worse than the hippo.

Phext safety: phext structural bytes (delimiters 0x01, 0x17-0x1F) and
coordinate text pass through untouched; inky only ever replaces whole word
tokens inside prose segments, so protected regions stay byte-identical.

Stdlib only. Input is read as bytes and decoded latin-1 so every byte —
including phext delimiters — round-trips exactly.
"""

import argparse
import math
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# The eval: named features, named weights (a classic engine eval, tunable).
# Dictionary frequency is deliberately the WEAKEST signal (W_DICT_FREQ):
# a tiebreaker prior, never the ranking's driver.
# ---------------------------------------------------------------------------
W_BOOK = 6.0          # candidate stands in the writer's own (Singular) lexicon
W_LEXICON = 2.0       # candidate is frequent in the writer's usage (--lexicon/--corpus), log-scaled
W_TABLE = 5.0         # candidate comes from the classic-typo table (teh -> the)
W_CLASS = 1.5         # candidate keeps the suspect's word class (structure fit)
W_CLASS_OFF = -1.0    # candidate changes word class where class is determinable
W_RHYTHM_LEN = 0.15   # per character of length delta (rhythm preservation)
W_RHYTHM_SYL = 0.8    # per syllable of syllable-count delta
W_PAIR = 1.2          # local pairing fit: writer's own bigrams around the slot, log-scaled
W_EDIT = 1.2          # per unit of edit distance from the suspect
W_NONWORD = -4.0      # "keep" move when the suspect is not a word at all
W_HIPPO = -5.0        # a line that leaves a hippo standing (display ranking only)
W_DICT_FREQ = 0.3     # candidate is a very common English word — weak prior only

APPLY_THRESHOLD = 3.5   # a line's eval must clear this to auto-apply
APPLY_MARGIN = 3.0      # ... and beat the runner-up line by this much
MOVE_THRESHOLD = 2.5    # every single change in an applied line must clear this
BEAM_WIDTH = 8          # search: beam over one sentence's suspects
MAX_CANDIDATES = 8      # moves kept per suspect position

TIER_GOOD = 3.5
TIER_PLAYABLE = 0.5
TIER_DUBIOUS = -3.0
# Below TIER_DUBIOUS: blunder. "god-tier" is never assigned by eval at all —
# it is reserved for the writer's own book constructions (see tier_for).

# Phext delimiters: library 0x01; scroll 0x17, section 0x18, chapter 0x19,
# book 0x1A, volume 0x1C, collection 0x1D, series 0x1E, shelf 0x1F.
PHEXT_DELIMS = "".join(chr(c) for c in (0x01, 0x17, 0x18, 0x19, 0x1A, 0x1C, 0x1D, 0x1E, 0x1F))

WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

# Classic unambiguous typos (the teh/recieve/adress class), incl. transpositions.
COMMON_TYPOS = {
    "teh": "the", "hte": "the", "thier": "their", "recieve": "receive",
    "adress": "address", "seperate": "separate", "occured": "occurred",
    "untill": "until", "wich": "which", "adn": "and", "taht": "that",
    "jsut": "just", "liek": "like", "wtih": "with", "from": None,  # placeholder guard, removed below
    "accomodate": "accommodate", "embarass": "embarrass", "enviroment": "environment",
    "goverment": "government", "independant": "independent", "neccessary": "necessary",
    "definately": "definitely", "immediatly": "immediately", "accross": "across",
    "apparantly": "apparently", "arguement": "argument", "basicly": "basically",
    "begining": "beginning", "beleive": "believe", "calender": "calendar",
    "cemetary": "cemetery", "changable": "changeable", "collegue": "colleague",
    "comming": "coming", "commited": "committed", "concious": "conscious",
    "copywrite": "copyright", "curiousity": "curiosity", "dissapear": "disappear",
    "dissapoint": "disappoint", "driectly": "directly", "equiped": "equipped",
    "existance": "existence", "experiance": "experience", "finaly": "finally",
    "flourescent": "fluorescent", "foriegn": "foreign", "fourty": "forty",
    "freind": "friend", "freindly": "friendly", "grammer": "grammar",
    "greatful": "grateful", "happend": "happened", "humurous": "humorous",
    "independant": "independent", "knowlege": "knowledge", "liason": "liaison",
    "libary": "library", "maintainance": "maintenance", "millenium": "millennium",
    "miniscule": "minuscule", "mispell": "misspell", "noticable": "noticeable",
    "occassion": "occasion", "omision": "omission", "opose": "oppose",
    "paralel": "parallel", "pasttime": "pastime", "posession": "possession",
    "preferance": "preference", "publich": "publish", "realy": "really",
    "refering": "referring", "remeber": "remember", "repitition": "repetition",
    "restaraunt": "restaurant", "rhythem": "rhythm", "secratary": "secretary",
    "sieze": "seize", "similiar": "similar", "speach": "speech",
    "strenght": "strength", "succesful": "successful", "supercede": "supersede",
    "suprise": "surprise", "tendancy": "tendency", "tomorow": "tomorrow",
    "tounge": "tongue", "truely": "truly", "vaccuum": "vacuum",
    "vegeterian": "vegetarian", "vigilence": "vigilance", "wierd": "weird",
    "writen": "written", "yeild": "yield",
    "recieved": "received", "recieving": "receiving", "reciever": "receiver",
    "seperated": "separated", "seperating": "separating", "occured": "occurred",
    "adressing": "addressing", "adresses": "addresses", "enviroments": "environments",
    "goverments": "governments", "independantly": "independently",
    "neccessarily": "necessarily", "definate": "definite", "definately": "definitely",
    "writting": "writing", "comming": "coming", "stoped": "stopped",
    "langage": "language", "knowlegeable": "knowledgeable", "libaries": "libraries",
    "restaraunts": "restaurants", "tomorows": "tomorrow's", "wierdly": "weirdly",
}
COMMON_TYPOS.pop("from", None)

# HIPPOS: confusable sets. Every word spelled correctly; the sentence still
# wrong. FLAG-ONLY — never auto-fixed, whatever the eval says.
CONFUSABLES = [
    {"their", "there", "they're"}, {"its", "it's"}, {"then", "than"},
    {"form", "from"}, {"to", "too", "two"}, {"your", "you're"},
    {"affect", "effect"}, {"loose", "lose"}, {"quiet", "quite"},
    {"where", "were", "wear"}, {"hear", "here"}, {"are", "our"},
    {"by", "buy", "bye"}, {"right", "write"}, {"weak", "week"},
    {"peace", "piece"}, {"principal", "principle"}, {"desert", "dessert"},
    {"breath", "breathe"}, {"advice", "advise"}, {"council", "counsel"},
    {"elicit", "illicit"}, {"stationary", "stationery"},
    {"complement", "compliment"}, {"passed", "past"}, {"lead", "led"},
    {"sight", "site", "cite"}, {"plain", "plane"}, {"rain", "reign", "rein"},
]
CONFUSE_MAP = {}
for group in CONFUSABLES:
    for w in group:
        CONFUSE_MAP[w] = group

# "too" is the correct excess sense before an adverb/adjective — the fence
# that keeps the author's own live test sentence unflagged.
TOO_OK_NEXT_SUFFIX = ("ly",)
TOO_OK_NEXT = {"much", "many", "far", "late"}

# Doubled words that are legitimate English ("had had", "that that", ...).
LEGIT_DOUBLES = {"had", "that", "is", "do", "does", "can", "could", "would",
                 "should", "will", "may", "so", "very", "too", "as", "it"}

# A tiny frequency prior: very common words get W_DICT_FREQ and nothing more.
COMMON_WORDS = set("""the of and a an to in is you that it he was for on are as with his they i
at be this have from or one had by word but not what all were we when your can said there use each
which she do how their if will up other about out many then them these so some her would make like
him into time has look two more write go see number no way could people my than first water been
call who oil its now find long down day did get come made may part work world life hand play
dragon scroll realm""".split())

FUNCTION_WORDS = set("""the a an and or but if then than to of in on at by for with from as is are was
were be been am do does did have has had will would can could shall should may might must i you he
she it we they me him her us them my his its our your their this that these those not no yes so too
very just""".split())


# ---------------------------------------------------------------------------
# Loading: dictionary, protect list, the writer's usage data.
# ---------------------------------------------------------------------------

def _read_word_lines(path):
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def load_dictionary(extra_path=None):
    """Base English forms. Lookup order: --dict, $INKY_DICT, system hunspell,
    /usr/share/dict/words, then the vendored words-en.txt beside this script."""
    candidates = []
    if extra_path:
        candidates.append(extra_path)
    if os.environ.get("INKY_DICT"):
        candidates.append(os.environ["INKY_DICT"])
    candidates += ["/usr/share/hunspell/en_US.dic", "/usr/share/dict/words",
                   os.path.join(HERE, "words-en.txt")]
    for path in candidates:
        if path and os.path.isfile(path):
            words = set()
            for line in _read_word_lines(path):
                w = line.split("/")[0].strip().lower()  # strip hunspell affix flags
                if w:
                    words.add(w)
            return words, path
    return set(), None


def inflections(w):
    """Regular English inflections of a base form (loader heuristic: keeps the
    validity set honest about plurals/pasts that hunspell stores as flags)."""
    forms = {w}
    if len(w) < 2:
        return forms
    if w.endswith("e"):
        forms.add(w + "d")
        forms.add(w[:-1] + "ing")
    else:
        forms.add(w + "ed")
        forms.add(w + "ing")
        if re.search(r"[^aeiou][aeiou][^aeiouwx]$", w):  # run -> running
            forms.add(w + w[-1] + "ing")
            forms.add(w + w[-1] + "ed")
    if w.endswith(("s", "x", "z", "ch", "sh")):
        forms.add(w + "es")
    else:
        forms.add(w + "s")
    if w.endswith("y") and w[-2] not in "aeiou":
        forms.add(w[:-1] + "ies")
        forms.add(w[:-1] + "ied")
        forms.add(w[:-1] + "ily")
    forms.add(w + "er")
    forms.add(w + "est")
    forms.add(w + "ly")
    return forms


def load_protect(extra_paths=()):
    words = set()
    paths = [os.path.join(HERE, "protect.txt")] + list(extra_paths)
    for path in paths:
        if path and os.path.isfile(path):
            for line in _read_word_lines(path):
                words.add(line.strip().lower())
    return words


class Usage:
    """The writer's own usage data: word frequencies + bigram pairings."""

    def __init__(self):
        self.freq = Counter()
        self.bigrams = Counter()

    def add_text(self, text):
        toks = [m.group(0).lower() for m in WORD_RE.finditer(text)]
        self.freq.update(toks)
        for a, b in zip(toks, toks[1:]):
            self.bigrams[(a, b)] += 1

    def add_wordlist(self, path):
        for line in _read_word_lines(path):
            parts = line.split()
            if not parts:
                continue
            w = parts[0].lower()
            n = 1
            if len(parts) > 1 and parts[1].isdigit():
                n = int(parts[1])
            self.freq[w] += n


# ---------------------------------------------------------------------------
# The engine: move generation, the eval, beam search over a sentence.
# A "position" is one sentence; a "line" is a complete choice of moves for
# every suspect in it. Scores attach to lines, never to isolated words.
# ---------------------------------------------------------------------------

def syllables(w):
    return max(1, len(re.findall(r"[aeiouy]+", w)))


def word_class(w):
    if w in FUNCTION_WORDS:
        return "func"
    if w.endswith("ly") and len(w) > 3:
        return "adv"
    if w.endswith(("ing", "ed")):
        return "verb"
    if w.endswith(("tion", "sion", "ness", "ment", "ity", "ance", "ence")):
        return "noun"
    if w.endswith(("ous", "ive", "al", "ic", "able", "ible", "ful", "less")):
        return "adj"
    return "other"


def edits1(w):
    letters = "abcdefghijklmnopqrstuvwxyz"
    splits = [(w[:i], w[i:]) for i in range(len(w) + 1)]
    deletes = [a + b[1:] for a, b in splits if b]
    transposes = [a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1]
    replaces = [a + c + b[1:] for a, b in splits if b for c in letters]
    inserts = [a + c + b for a, b in splits for c in letters]
    return set(deletes + transposes + replaces + inserts)


def edit_distance(a, b, cap=3):
    """Damerau-Levenshtein (optimal string alignment): an adjacent
    transposition — the classic typo — costs 1, not 2."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        best = d[i][0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
            best = min(best, d[i][j])
        if best > cap:
            return cap + 1
    return d[la][lb]


class Engine:
    def __init__(self, base_dict, valid, protect, usage):
        self.base = base_dict          # base dictionary forms (candidate pool source)
        # The typo table vetoes validity: a known typo is never a word, even
        # if it appears in the writer's observed vocabulary (he typed it once;
        # that makes it data, not a coinage).
        self.valid = set(valid) - set(COMMON_TYPOS)
        # The book is the writer's lexicon MINUS the general dictionary MINUS
        # known typos: his coinages (phext, phdoc, designbox) — the words a
        # commodity corrector would mangle. Ordinary English he happens to
        # use is not protected; his own past typos are not coinages.
        self.protect = set(protect) - set(base_dict) - set(COMMON_TYPOS)
        # Junk fence: an observed token within edit distance 1 of a known
        # correction ("reciever" beside "receiver") is a past typo that
        # drifted into the usage data — not a coinage. It leaves the book,
        # the validity set, and the candidate pool together.
        near_corrections = set()
        for corr in set(COMMON_TYPOS.values()):
            near_corrections |= edits1(corr)
        junk = self.protect & near_corrections
        if junk:
            self.protect -= junk
            self.valid -= junk
        self.usage = usage             # Usage() — may be empty
        self.pool = self.valid         # candidates drawn from the fenced validity set

    # -- protection ---------------------------------------------------------
    def is_protected(self, token):
        if token.lower() in self.protect:
            return True
        letters = [c for c in token if c.isalpha()]
        if len(letters) >= 2 and all(c.isupper() for c in letters):
            return True  # ALL-CAPS coinages/acronyms
        if any(c.isupper() for c in token[1:]) and any(c.islower() for c in token):
            return True  # camelCase identifiers
        return False

    def is_valid(self, token):
        w = token.lower()
        if w in self.valid or w in self.protect:
            return True
        if "'" in w:  # contractions: base + clitic
            base, _, clitic = w.partition("'")
            if clitic in {"s", "t", "re", "ve", "ll", "d", "m"} and base in self.valid:
                return True
            if w.endswith("'s") and w[:-2] in self.valid:
                return True
        return False

    # -- move generation ----------------------------------------------------
    def candidates(self, suspect):
        """Moves for one suspect word: typo table, edit neighbors, confusables."""
        w = suspect.lower()
        moves = {}  # word -> feature seed info
        if w in CONFUSE_MAP:
            # Hippo position: the move list is the confusable set, nothing
            # else — edit-neighbors of a real word are noise, not analysis.
            for c in CONFUSE_MAP[w]:
                if c != w:
                    moves[c] = {"table": False, "dist": edit_distance(w, c), "confusable": True}
            return list(moves.items())
        if w in COMMON_TYPOS:
            # The classic-typo table is the opening book: for a known classic
            # the line is already known, so the move list is {keep, entry} —
            # still scored, still required to clear threshold + margin, but
            # edit-neighbor noise never crowds the board.
            t = COMMON_TYPOS[w]
            return [(t, {"table": True, "dist": edit_distance(w, t)})]
        near = edits1(w) & self.pool
        for c in near:
            if c != w:
                moves.setdefault(c, {"table": False, "dist": 1})
        if not near and len(w) >= 5:  # widen once, only when the near net is empty
            near2 = set()
            for e in edits1(w):
                near2 |= edits1(e) & self.pool
                if len(near2) > 40:
                    break
            for c in near2:
                if c != w:
                    moves.setdefault(c, {"table": False, "dist": 2})
        # Bound the move list: keep by quick promise (table, book, lexicon, closeness).
        def promise(item):
            c, info = item
            p = 0.0
            if info.get("table"):
                p += 10
            if c in self.protect:
                p += 8
            if self.usage.freq.get(c):
                p += 2
            p -= info["dist"]
            return -p
        ranked = sorted(moves.items(), key=promise)[:MAX_CANDIDATES]
        return ranked

    # -- the eval -----------------------------------------------------------
    def move_features(self, suspect, cand, info, prev_word, next_word):
        """Feature vector for one move, in the writer's sentence context.
        Returns (lexicon_axis, structure_axis, total)."""
        s = suspect.lower()
        c = cand.lower()
        lex = 0.0
        if c in self.protect:
            lex += W_BOOK
        f = self.usage.freq.get(c, 0)
        if f:
            lex += W_LEXICON * min(3.0, math.log1p(f))
        if c in COMMON_WORDS:
            lex += W_DICT_FREQ  # weakest signal, by design
        struct = 0.0
        cs, cc = word_class(s), word_class(c)
        if cs != "other" and cc != "other":
            struct += W_CLASS if cs == cc else W_CLASS_OFF
        struct -= W_RHYTHM_LEN * abs(len(c) - len(s))
        struct -= W_RHYTHM_SYL * abs(syllables(c) - syllables(s))
        if self.usage.bigrams:
            pair = 0.0
            if prev_word:
                pair += math.log1p(self.usage.bigrams.get((prev_word.lower(), c), 0))
            if next_word:
                pair += math.log1p(self.usage.bigrams.get((c, next_word.lower()), 0))
            struct += W_PAIR * min(3.0, pair)
        total = lex + struct
        if info.get("table"):
            total += W_TABLE
        total -= W_EDIT * info.get("dist", 1)
        return lex, struct, total

    def analyze_sentence(self, tokens):
        """tokens: list of word strings in one sentence.
        Returns (suspects, lines): suspects = [(index, word, kind)],
        lines = ranked [(eval, choices, per-move detail)] best first.
        kind is 'typo' or 'hippo'. The keep-original line is always present."""
        suspects = []
        for i, tok in enumerate(tokens):
            if self.is_protected(tok):
                continue
            w = tok.lower()
            if w in CONFUSE_MAP and self._hippo_live(tokens, i):
                suspects.append((i, tok, "hippo"))
            elif not self.is_valid(tok):
                # Proper-noun heuristic: a Capitalized non-sentence-initial
                # token we don't know is a name, not a typo.
                if tok[:1].isupper() and i != 0 and w not in COMMON_TYPOS:
                    continue
                if len(tok) < 2 and w not in COMMON_TYPOS:
                    continue
                suspects.append((i, tok, "typo"))
        if not suspects:
            return suspects, []
        move_lists = []
        for i, tok, kind in suspects:
            cands = self.candidates(tok)
            move_lists.append([(tok, {"keep": True, "dist": 0})] +
                              [(c, info) for c, info in cands])
        # Beam search over positions, in sentence order. Partial lines are
        # scored with left-context pairing; the quiescence pass below then
        # re-scores the finalists with full context, and hippo positions are
        # never pruned out of the beam (extra depth at flagged positions).
        beam = [(0.0, [])]  # (partial eval, [(cand, info), ...])
        for pos, (idx, tok, kind) in enumerate(suspects):
            prev_tok = tokens[idx - 1] if idx > 0 else None
            nxt = []
            for ev, chosen in beam:
                for cand, info in move_lists[pos]:
                    if info.get("keep"):
                        step = W_NONWORD if kind == "typo" else 0.0
                        nxt.append((ev + step, chosen + [(cand, info)]))
                    else:
                        _, _, tot = self.move_features(tok, cand, info, prev_tok, None)
                        nxt.append((ev + tot, chosen + [(cand, info)]))
            nxt.sort(key=lambda x: -x[0])
            beam = nxt[:BEAM_WIDTH]
        # Quiescence: full-context rescoring of the finalists.
        lines = []
        for _, chosen in beam:
            total = 0.0
            detail = []
            hippo_touched = False
            for pos, (idx, tok, kind) in enumerate(suspects):
                cand, info = chosen[pos]
                prev_word = self._line_word(tokens, suspects, chosen, idx - 1)
                next_word = self._line_word(tokens, suspects, chosen, idx + 1)
                if info.get("keep"):
                    step = W_NONWORD if kind == "typo" else 0.0
                    if kind == "hippo":
                        step += W_HIPPO
                    detail.append((tok, cand, 0.0, 0.0, step, info))
                    total += step
                else:
                    if kind == "hippo":
                        hippo_touched = True
                    lex, struct, tot = self.move_features(tok, cand, info, prev_word, next_word)
                    detail.append((tok, cand, lex, struct, tot, info))
                    total += tot
            lines.append((total, chosen, detail, hippo_touched))
        lines.sort(key=lambda x: -x[0])
        # Deduplicate identical choice-lines, keep the best score.
        seen, uniq = set(), []
        for ln in lines:
            key = tuple(c for c, _ in ln[1])
            if key not in seen:
                seen.add(key)
                uniq.append(ln)
        return suspects, uniq

    def _line_word(self, tokens, suspects, chosen, j):
        if j < 0 or j >= len(tokens):
            return None
        for pos, (idx, tok, kind) in enumerate(suspects):
            if idx == j:
                return chosen[pos][0]
        return tokens[j]

    def _hippo_live(self, tokens, i):
        """Light context fence: 'too' in its correct excess sense is not a hippo."""
        w = tokens[i].lower()
        if w == "too" and i + 1 < len(tokens):
            nxt = tokens[i + 1].lower()
            if nxt.endswith(TOO_OK_NEXT_SUFFIX) or nxt in TOO_OK_NEXT:
                return False
        return True


def tier_for(value, is_writers_book=False):
    """The engine's spoken language. god-tier is reserved: it names the
    writer's own book constructions, never the engine's suggestions."""
    if is_writers_book:
        return "god-tier"
    if value >= TIER_GOOD:
        return "good"
    if value >= TIER_PLAYABLE:
        return "playable"
    if value >= TIER_DUBIOUS:
        return "dubious"
    return "blunder"


# ---------------------------------------------------------------------------
# Text processing. Order per prose segment:
#   1. deterministic structural fixes (spacing, doubled words)
#   2. the engine, per sentence (beam search + narrow auto-apply)
#   3. flag-only structural checks (unbalanced quotes/parens)
# Sentence boundaries are only a search scope — never altered. Fragments,
# inversions, and punctuation rhythm pass through untouched by design.
# ---------------------------------------------------------------------------

SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+[\"'\)\]]*)?")
SPACE_BEFORE_PUNCT = re.compile(r"([A-Za-z])[ \t]+([,.;:!?])")
MISSING_SPACE_DOT = re.compile(r"([A-Za-z]+)\.([A-Z][a-z]+)")
MISSING_SPACE_COMMA = re.compile(r"([A-Za-z]+),([A-Za-z]+)")
DOUBLE_WORD = re.compile(r"\b([A-Za-z]+)([ \t]+)([A-Za-z]+)\b")


class Report:
    def __init__(self):
        self.fixes = []      # (kind, before, after, note)
        self.flags = []      # (kind, text, note)
        self.analyses = []   # formatted analysis blocks (check mode / detail)

    def fix(self, kind, before, after, note=""):
        self.fixes.append((kind, before, after, note))

    def flag(self, kind, text, note=""):
        self.flags.append((kind, text, note))


def structural_fixes(seg, engine, rep):
    # Space before punctuation: "word ." -> "word."
    def _sbp(m):
        rep.fix("structure", m.group(0), m.group(1) + m.group(2), "space before punctuation")
        return m.group(1) + m.group(2)
    seg = SPACE_BEFORE_PUNCT.sub(_sbp, seg)
    # Missing space after sentence punctuation: "end.Start" -> "end. Start"
    def _dot(m):
        if engine.is_valid(m.group(1)) and engine.is_valid(m.group(2)):
            rep.fix("structure", m.group(0), m.group(1) + ". " + m.group(2), "missing space after period")
            return m.group(1) + ". " + m.group(2)
        return m.group(0)
    seg = MISSING_SPACE_DOT.sub(_dot, seg)

    def _comma(m):
        if engine.is_valid(m.group(1)) and engine.is_valid(m.group(2)):
            rep.fix("structure", m.group(0), m.group(1) + ", " + m.group(2), "missing space after comma")
            return m.group(1) + ", " + m.group(2)
        return m.group(0)
    seg = MISSING_SPACE_COMMA.sub(_comma, seg)
    # Doubled words: "the the" -> "the" (legitimate doubles exempt).
    out, last = [], 0
    for m in DOUBLE_WORD.finditer(seg):
        if m.group(1).lower() == m.group(3).lower() and m.group(1).lower() not in LEGIT_DOUBLES:
            out.append(seg[last:m.start()])
            out.append(m.group(1))
            rep.fix("structure", m.group(0), m.group(1), "doubled word")
            last = m.end()
    if out:
        out.append(seg[last:])
        seg = "".join(out)
    return seg


def balance_flags(seg, rep):
    for open_c, close_c, name in (("(", ")", "parentheses"), ("[", "]", "brackets"), ("{", "}", "braces")):
        if seg.count(open_c) != seg.count(close_c):
            rep.flag("structure", seg.strip()[:60],
                     f"unbalanced {name}: {seg.count(open_c)} open / {seg.count(close_c)} close")
    if seg.count('"') % 2 == 1:
        rep.flag("structure", seg.strip()[:60], "unbalanced double quotes (odd count)")


def apply_case(original, replacement):
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def engine_pass(seg, engine, rep, check_only):
    spans = [m.span() for m in SENTENCE_RE.finditer(seg)]
    if not spans:
        spans = [(0, len(seg))]
    replacements = {}  # absolute offset of token start -> new text
    for s0, s1 in spans:
        sentence = seg[s0:s1]
        toks = [(m.group(0), s0 + m.start()) for m in WORD_RE.finditer(sentence)]
        if not toks:
            continue
        words = [t for t, _ in toks]
        suspects, lines = engine.analyze_sentence(words)
        if not suspects:
            continue
        best = lines[0] if lines else None
        applied = False
        applied_idx = set()
        if best and not check_only:
            ev, chosen, detail, hippo_touched = best
            # Application is per-change within the winning line: the line
            # must clear APPLY_THRESHOLD, each applied change must clear
            # MOVE_THRESHOLD in that line's full context, AND the change's
            # move must beat the runner-up move AT ITS OWN POSITION by
            # APPLY_MARGIN (a tie at the top — jaat vs ccat — is ambiguity,
            # and ambiguity is flagged, never applied). A shaky suspect
            # never holds certain fixes hostage. Hippos never auto-change.
            if ev >= APPLY_THRESHOLD:
                words_now = [t for t, _ in toks]
                for p, (idx, tok, kind) in enumerate(suspects):
                    cand, info = chosen[p]
                    tot = detail[p][4]
                    if info.get("keep") or kind == "hippo":
                        continue
                    prev_w = engine._line_word(words_now, suspects, chosen, idx - 1)
                    next_w = engine._line_word(words_now, suspects, chosen, idx + 1)
                    rivals = [W_NONWORD if kind == "typo" else 0.0]  # the keep move
                    for rc, rinfo in engine.candidates(tok):
                        if rc != cand:
                            rivals.append(engine.move_features(tok, rc, rinfo, prev_w, next_w)[2])
                    if tot >= MOVE_THRESHOLD and tot - max(rivals) >= APPLY_MARGIN:
                        replacements[toks[idx][1]] = apply_case(tok, cand)
                        rep.fix("word", tok, cand, f"line eval {ev:.2f} [{tier_for(ev)}]")
                        applied_idx.add(idx)
                        applied = True
        unresolved = []
        if best:
            unresolved = [suspects[p][1] for p in range(len(suspects))
                          if suspects[p][0] not in applied_idx]
        if check_only or not applied or unresolved:
            rep.analyses.append(format_analysis(sentence, suspects, lines, engine))
            for idx, tok, kind in suspects:
                if kind == "hippo":
                    rep.flag("hippo", tok, "real word, possibly the wrong one — flag only, never auto-fixed")
                elif applied and tok in unresolved:
                    rep.flag("typo", tok, "suspect — its move did not clear the bar; left as written")
    if not replacements:
        return seg
    out, last = [], 0
    for m in WORD_RE.finditer(seg):
        if m.start() in replacements:
            out.append(seg[last:m.start()])
            out.append(replacements[m.start()])
            last = m.end()
    out.append(seg[last:])
    return "".join(out)


def format_analysis(sentence, suspects, lines, engine):
    out = [f"sentence: {sentence.strip()!r}"]
    names = ", ".join(f"{tok!r} ({kind})" for _, tok, kind in suspects)
    out.append(f"  suspects: {names}")
    book_line = any(tok.lower() in engine.protect for _, tok, _ in suspects) or \
        any(m.group(0).lower() in engine.protect for m in WORD_RE.finditer(sentence))
    rendered = []
    keep_rendered = None
    for ev, chosen, detail, hippo_touched in lines:
        changes = []
        is_keep = all(info.get("keep") for _, info in chosen)
        for (tok, cand, lex, struct, tot, info) in detail:
            if not info.get("keep"):
                changes.append(f"{tok!r} -> {cand!r} (lexicon {lex:.2f} · structure {struct:.2f})")
        label = "keep" if is_keep else "; ".join(changes)
        tier = tier_for(ev, is_writers_book=(is_keep and book_line and
                                             not any(k == "typo" for _, _, k in suspects)))
        note = " [touches a hippo — never auto-applied]" if hippo_touched else ""
        row = f"  [{tier}] {label} · eval {ev:.2f}{note}"
        if is_keep:
            keep_rendered = row
        else:
            rendered.append(row)
    out.extend(rendered[:3])
    if keep_rendered is not None:
        out.append(keep_rendered)  # the writer's own line is always on the board
    return "\n".join(out)


def process(text, engine, check_only):
    rep = Report()
    parts = re.split(f"([{re.escape(PHEXT_DELIMS)}])", text)
    out = []
    for part in parts:
        if len(part) == 1 and part in PHEXT_DELIMS:
            out.append(part)  # structural byte: untouched, always
            continue
        if not part:
            continue
        if check_only:
            scratch = Report()
            structural_fixes(part, engine, scratch)
            for kind, before, after, note in scratch.fixes:
                rep.flag(kind, before, f"would fix -> {after!r} ({note})")
            seg = part
        else:
            seg = structural_fixes(part, engine, rep)
        seg = engine_pass(seg, engine, rep, check_only)
        balance_flags(seg, rep)
        out.append(seg)
    return "".join(out), rep


# ---------------------------------------------------------------------------
# CLI. Default relationship is analysis: corrected text rides stdout with
# only the narrow, high-confidence fixes applied; the full analysis (lines,
# tiers, evals) goes to the report stream. --check modifies nothing.
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="inky", description="A writing tool assistant — massages your typos, never corrects you.")
    ap.add_argument("file", nargs="?", default="-", help="input file (default: stdin)")
    ap.add_argument("--check", action="store_true", help="analysis only; modify nothing")
    ap.add_argument("--lexicon", help="writer's wordlist (word [count] per line) — lexicon-fit data")
    ap.add_argument("--corpus", help="a file of the writer's own text — frequencies + pairings")
    ap.add_argument("--protect", action="append", default=[], help="extra protect-list file(s)")
    ap.add_argument("--dict", dest="dict_path", help="dictionary file override")
    ap.add_argument("--report", help="write the change/analysis report here (default: stderr)")
    args = ap.parse_args(argv)

    base, _src = load_dictionary(args.dict_path)
    valid = set(base)
    for w in list(base):
        valid |= inflections(w)
    protect = load_protect(args.protect)
    valid |= protect
    usage = Usage()
    if args.lexicon:
        usage.add_wordlist(args.lexicon)
    if args.corpus:
        with open(args.corpus, encoding="utf-8", errors="replace") as f:
            usage.add_text(f.read())
    engine = Engine(base, valid, protect, usage)

    raw = sys.stdin.buffer.read() if args.file == "-" else open(args.file, "rb").read()
    text = raw.decode("latin-1")
    result, rep = process(text, engine, args.check)
    sys.stdout.buffer.write(result.encode("latin-1"))  # byte-exact round-trip
    sys.stdout.buffer.flush()

    lines = []
    for kind, before, after, note in rep.fixes:
        lines.append(f"FIXED [{kind}] {before!r} -> {after!r} {note}".rstrip())
    for block in rep.analyses:
        lines.append(block)
    for kind, txt, note in rep.flags:
        if kind != "hippo":  # hippos already appear inside their analysis blocks
            lines.append(f"FLAG [{kind}] {txt!r} {note}".rstrip())
    report = "\n".join(lines)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report + ("\n" if report else ""))
    elif report:
        print(report, file=sys.stderr)
    if args.check:
        return 1 if (rep.analyses or rep.flags) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
