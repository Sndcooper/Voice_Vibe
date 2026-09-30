"""tools/bench/metrics.py: normalisation, WER, command match, loops, summaries."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "bench"))

import metrics  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_case_punctuation_and_aliases(self) -> None:
        self.assertEqual(metrics.normalize("Okay, Computer!"), "ok computer")
        self.assertEqual(metrics.normalize("Open Git Hub."), "open github")
        self.assertEqual(metrics.normalize("Run Claude in the VSCode terminal"),
                         "run claude in the vs code terminal")
        self.assertEqual(metrics.normalize("click 7"), "click seven")
        self.assertEqual(metrics.normalize("Let's meet—tomorrow"), "let's meet tomorrow")
        self.assertEqual(metrics.normalize("check my Linked-In"), "check my linkedin")
        self.assertEqual(metrics.normalize("  "), "")


class WerTests(unittest.TestCase):
    def test_edit_counts(self) -> None:
        self.assertEqual(metrics.edits("a b c", "a b c"), (0, 3))
        self.assertEqual(metrics.edits("a b c", "a x c"), (1, 3))
        self.assertEqual(metrics.edits("a b c", "a c"), (1, 3))
        self.assertEqual(metrics.edits("a b", "a b c d"), (2, 2))
        self.assertEqual(metrics.edits("", "phantom words"), (2, 0))

    def test_corpus_wer(self) -> None:
        pairs = [("run claude", "surround the cloud"), ("press enter", "press enter")]
        # "run claude" -> "surround the cloud": 3 edits over 2 words; + 0 over 2.
        self.assertAlmostEqual(metrics.wer(pairs), 3 / 4)


class CommandAndLoopTests(unittest.TestCase):
    def test_command_match(self) -> None:
        self.assertTrue(metrics.command_ok("computer run Claude", "Computer, run Claude."))
        self.assertFalse(metrics.command_ok("computer run Claude", "Computer, surround the cloud."))

    def test_loop_detection(self) -> None:
        ref = "First fix it and then write it up and then send it to the team for review."
        looped = "fix it and then write it up and then write it up and then write it up and then"
        self.assertTrue(metrics.looped(ref, looped))
        self.assertFalse(metrics.looped(ref, ref))
        self.assertTrue(metrics.looped("press enter", "press enter thank you for watching and see you"))
        self.assertFalse(metrics.looped("yeah yeah", "yeah yeah"))


class SummaryTests(unittest.TestCase):
    def test_summarize(self) -> None:
        rows = [
            {"kind": "command", "text": "press enter", "hyp": "Press enter.", "seconds": 1.0, "decode_s": 0.1},
            {"kind": "wake", "text": "hey computer", "hyp": "Hey, computers.", "seconds": 1.0, "decode_s": 0.3},
            {"kind": "dictation", "text": "a b c d", "hyp": "a b c d", "seconds": 2.0, "decode_s": 0.2},
            {"kind": "silence", "text": "", "hyp": "Thank you.", "seconds": 5.0, "decode_s": 0.4},
            {"kind": "noise", "text": "", "hyp": "", "seconds": 5.0, "decode_s": 0.1},
        ]
        s = metrics.summarize(rows)
        self.assertEqual(s["n_speech"], 3)
        self.assertAlmostEqual(s["cmd_acc"], 0.5)
        self.assertAlmostEqual(s["wer"], 1 / 8)
        self.assertAlmostEqual(s["phantom_rate"], 0.5)
        self.assertEqual(s["loops"], 0)
        self.assertAlmostEqual(s["lat_mean"], 0.2)
        self.assertAlmostEqual(s["rtf"], 0.6 / 4.0)

    def test_empty(self) -> None:
        s = metrics.summarize([])
        self.assertIsNone(s["wer"])
        self.assertIsNone(s["cmd_acc"])


if __name__ == "__main__":
    unittest.main()
