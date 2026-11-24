#!/usr/bin/env python3
"""Tests for inky — the writing tool assistant.

Anchors, in order of importance:
  1. The author's own live test (Will, 2026-11-24 15:08 CST): the sentence
     "hippos drift in too easily with old tools" is CORRECT as written and
     must pass through byte-identical. A corrector that touches it has failed.
  2. The writer's Singular words are never flagged or changed.
  3. Phext structure (delimiters, coordinates) survives byte-identical.
  4. Deliberate fragments and inversions — his structure — pass untouched.
  5. Hippos are flagged, never fixed.
  6. Candidate scoring: the writer-fit candidate outranks the dictionary
     favorite when the writer's own usage data says so.
"""

import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inky


def make_engine(corpus_text=None):
    base, _ = inky.load_dictionary()
    valid = set(base)
    for w in list(base):
        valid |= inky.inflections(w)
    protect = inky.load_protect()
    valid |= protect
    usage = inky.Usage()
    if corpus_text:
        usage.add_text(corpus_text)
    return inky.Engine(base, valid, protect, usage)


class PassThrough(unittest.TestCase):
    """No-false-positive anchors: these inputs are correct as written."""

    def setUp(self):
        self.engine = make_engine()

    def assert_untouched(self, text):
        out, rep = inky.process(text, self.engine, check_only=False)
        self.assertEqual(out, text)
        self.assertEqual(rep.fixes, [])
        out_check, _ = inky.process(text, self.engine, check_only=True)
        self.assertEqual(out_check, text)

    def test_authors_live_test_sentence(self):
        # Will's live test, 2026-11-24: "too" is the excess sense, correct.
        self.assert_untouched("hippos drift in too easily with old tools")

    def test_deliberate_fragment(self):
        self.assert_untouched("Because the night was not done with him yet.")

    def test_inverted_sentence(self):
        self.assert_untouched("Never had he seen such a thing.")

    def test_singular_words_survive(self):
        self.assert_untouched(
            "The phext scroll names phdoc and designbox beside the exocortex.")

    def test_phext_coordinate_line(self):
        self.assert_untouched("1.1.1/1.1.1/1.1.1")


class Fixes(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()

    def test_classic_typos_fixed(self):
        out, rep = inky.process("teh dragon will recieve teh scroll",
                                self.engine, check_only=False)
        self.assertEqual(out, "the dragon will receive the scroll")
        self.assertTrue(any(f[1] == "teh" for f in rep.fixes))

    def test_phext_delimiters_and_coordinates_preserved(self):
        src = "1.1.1/1.1.1/1.1.1\x17teh dragon sleeps\x17"
        out, _ = inky.process(src, self.engine, check_only=False)
        self.assertEqual(out, "1.1.1/1.1.1/1.1.1\x17the dragon sleeps\x17")

    def test_doubled_word_caught(self):
        out, rep = inky.process("the the dragon sleeps", self.engine, check_only=False)
        self.assertEqual(out, "the dragon sleeps")
        self.assertTrue(any("doubled" in f[3] for f in rep.fixes))

    def test_legitimate_double_survives(self):
        out, _ = inky.process("he had had enough", self.engine, check_only=False)
        self.assertEqual(out, "he had had enough")

    def test_ambiguous_flagged_not_changed(self):
        out, rep = inky.process("the caat sleeps", self.engine, check_only=False)
        self.assertEqual(out, "the caat sleeps")
        self.assertTrue(rep.analyses)


class Hippos(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()

    def test_hippo_flagged_never_fixed(self):
        src = "Their going to win, form the looks of it."
        out, rep = inky.process(src, self.engine, check_only=False)
        self.assertEqual(out, src)
        kinds = [f[0] for f in rep.flags]
        self.assertIn("hippo", kinds)

    def test_unbalanced_quote_flagged_not_changed(self):
        src = 'She said "hello and left.'
        out, rep = inky.process(src, self.engine, check_only=False)
        self.assertEqual(out, src)
        self.assertTrue(any("unbalanced" in f[2] for f in rep.flags))


class Scoring(unittest.TestCase):
    """The eval ranks by the writer's lexicon + structure, not the dictionary."""

    CORPUS = ("the dragon hoard grows. " * 12 +
              "guard the dragon hoard well. " * 6 +
              "hoard by hoard the dragon counts. " * 4)

    def test_writer_fit_outranks_dictionary_favorite(self):
        engine = make_engine(corpus_text=self.CORPUS)
        suspects, lines = engine.analyze_sentence(["the", "dragon", "hord", "grows"])
        self.assertTrue(suspects)
        best_line = lines[0]
        best_choice = best_line[1][0][0]
        self.assertEqual(best_choice, "hoard")
        # and it must beat a common dictionary word head-to-head on the axes
        detail = {d[1]: d for d in best_line[2]}
        self.assertIn("hoard", detail)
        self.assertGreater(detail["hoard"][2], 0)  # lexicon axis carries it

    def test_god_tier_reserved_for_the_writers_book(self):
        engine = make_engine()
        out, rep = inky.process("the phext holds their secrets",
                                engine, check_only=True)
        self.assertEqual(out, "the phext holds their secrets")
        joined = "\n".join(rep.analyses)
        self.assertIn("god-tier", joined)  # the writer's own line, book word aboard


class Cli(unittest.TestCase):
    def test_check_mode_anchor_sentence_exit_clean(self):
        here = os.path.dirname(os.path.abspath(__file__))
        proc = subprocess.run(
            [sys.executable, os.path.join(here, "inky.py"), "--check"],
            input=b"hippos drift in too easily with old tools",
            capture_output=True)
        self.assertEqual(proc.stdout, b"hippos drift in too easily with old tools")
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
