"""Suggesting [[replacements]] from history.

What matters: only correction-shaped evidence counts, rephrasing and grammar
are not "misheard words", known rows are not suggested again, and nothing is
proposed from a single stray event.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import stubs

stubs.install()

from voicevibe.suggest import load_history, report, suggest, swaps  # noqa: E402


def dictate(ts: str, heard: str, target: str = "Notepad") -> dict:
    return {"ts": f"2026-09-28T{ts}", "action": "dictate", "heard": heard,
            "inserted": heard, "target": target}


def edit(ts: str, name: str, **fields: str) -> dict:
    return {"ts": f"2026-09-28T{ts}", "action": "edit", "edit": name, **fields}


class TestSwaps(unittest.TestCase):
    def test_a_misheard_phrase(self) -> None:
        self.assertEqual(swaps("I trained it in pie torch last night",
                               "I trained it in PyTorch last night"),
                         [("pie torch", "PyTorch")])

    def test_a_different_sentence_is_not_a_retry(self) -> None:
        self.assertEqual(swaps("send the report to Anna", "what time is lunch today"), [])

    def test_case_only_and_grammar_changes_are_ignored(self) -> None:
        self.assertEqual(swaps("meet the team at noon", "Meet the team at noon"), [])
        self.assertEqual(swaps("send a report to the team", "send the report to the team"), [])

    def test_a_rewritten_clause_is_not_a_misheard_word(self) -> None:
        self.assertEqual(swaps("we will ship it after the review and the demo tomorrow",
                               "we will ship it once everyone has signed off on it tomorrow"), [])


class TestSuggest(unittest.TestCase):
    def test_replace_edits_count_fully(self) -> None:
        records = [edit("10:00:00", "replace", find="pie torch", replace="PyTorch"),
                   edit("11:00:00", "replace", find="Pie Torch", replace="PyTorch")]
        [s] = suggest(records)
        self.assertEqual((s.find, s.replace, s.score), ("pie torch", "PyTorch", 2.0))
        self.assertEqual(s.evidence, {"replace edit": 2})

    def test_scratch_and_retry(self) -> None:
        records = []
        for hour in ("09", "14"):
            records += [dictate(f"{hour}:00:00", "deploy it to cuber netties"),
                        edit(f"{hour}:00:05", "undo"),
                        dictate(f"{hour}:00:12", "deploy it to Kubernetes")]
        [s] = suggest(records)
        self.assertEqual((s.find, s.replace), ("cuber netties", "Kubernetes"))
        self.assertEqual(s.evidence, {"scratch & retry": 2})

    def test_a_slow_retry_is_not_evidence(self) -> None:
        records = [dictate("09:00:00", "deploy it to cuber netties"), edit("09:00:05", "undo"),
                   dictate("09:05:00", "deploy it to Kubernetes")] * 2
        self.assertEqual(suggest(records), [])

    def test_quick_retries_count_half(self) -> None:
        once = [dictate("09:00:00", "open the jason file"), dictate("09:00:10", "open the JSON file")]
        self.assertEqual(suggest(once), [])  # 0.5 < 2
        records = []
        for minute in range(4):
            records += [dictate(f"09:{minute:02}:00", "open the jason file"),
                        dictate(f"09:{minute:02}:10", "open the JSON file")]
        [s] = suggest(records)
        self.assertEqual((s.find, s.replace, s.score), ("jason", "JSON", 2.0))

    def test_quick_retry_needs_the_same_window(self) -> None:
        records = [dictate("09:00:00", "open the jason file", "Notepad"),
                   dictate("09:00:10", "open the JSON file", "Slack")] * 4
        self.assertEqual(suggest(records), [])

    def test_known_rows_are_not_suggested_again(self) -> None:
        records = [edit("10:00:00", "replace", find="pie torch", replace="PyTorch")] * 3
        self.assertEqual(suggest(records, existing=[{"find": "Pie Torch", "replace": "x"}]), [])

    def test_the_more_common_fix_wins(self) -> None:
        records = ([edit("10:00:00", "replace", find="jason", replace="JSON")] * 3
                   + [edit("10:00:00", "replace", find="jason", replace="Jason")] * 2)
        [s] = suggest(records)
        self.assertEqual(s.replace, "JSON")


class TestReport(unittest.TestCase):
    def test_reads_files_and_prints_toml(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            lines = [json.dumps(edit("10:00:00", "replace", find="pie torch", replace="PyTorch"))] * 2
            (Path(d) / "2026-09-28.jsonl").write_text("\n".join(lines) + "\nnot json\n",
                                                     encoding="utf-8")
            self.assertEqual(len(load_history(Path(d))), 2)
            out = report(Path(d), existing=[])
        self.assertIn('[[replacements]]\nfind = "pie torch"\nreplace = "PyTorch"', out)
        self.assertIn("apply_replacements = true", out)

    def test_empty_history_explains_itself(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = report(Path(d), existing=[])
        self.assertIn("Nothing yet", out)


if __name__ == "__main__":
    unittest.main()
