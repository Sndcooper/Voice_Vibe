"""vvhub eval: routing accuracy, latency and memory for the current Laya tier."""

from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO

import stubs

stubs.install()

from vvhub import laya_engine  # noqa: E402
from vvhub.evals import runner  # noqa: E402
from vvhub.laya_engine import Engine  # noqa: E402
from vvhub.schemas import CATEGORIES  # noqa: E402


class TableLaya:
    """Right for every request in `right`, says chitchat otherwise."""

    def __init__(self, right: dict) -> None:
        self.right = right

    def predict(self, state, questions, min_confidence=None):  # noqa: ANN001, ANN201
        want = self.right.get(state["request"], {})
        out = {}
        for qid, q in questions.items():
            if q["type"] == "choice":
                pick = want.get(qid)
                if pick not in q["criteria"]:
                    pick = list(q["criteria"])[-1]
                out[qid] = {"type": "choice", "choice": pick, "answer_confidence": 0.8}
            elif q["type"] == "score":
                out[qid] = {"type": "score", "score": 0.0, "answer_confidence": 0.8}
            else:
                yes = qid == want.get("category", "chitchat")
                out[qid] = {"type": "noul", "noul": 0.95 if yes else 0.0,
                            "answer_confidence": 0.95}
        return {"answers": out}


class IntentsFileTests(unittest.TestCase):
    def test_file_is_big_enough_and_covers_every_category(self) -> None:
        rows = runner.load_intents()
        self.assertGreaterEqual(len(rows), 80)
        counts = {c: 0 for c in CATEGORIES}
        for row in rows:
            self.assertIn(row["category"], CATEGORIES, row)
            self.assertTrue(row["text"].strip())
            counts[row["category"]] += 1
        for category, n in counts.items():
            self.assertGreaterEqual(n, 5, category)

    def test_texts_are_unique(self) -> None:
        texts = [r["text"].lower() for r in runner.load_intents()]
        self.assertEqual(len(texts), len(set(texts)))


class EvaluateTests(unittest.TestCase):
    ROWS = [
        {"text": "explain this", "category": "screen"},
        {"text": "push my changes", "category": "github"},
        {"text": "hello", "category": "chitchat"},
        {"text": "note this", "category": "notes"},
    ]

    def setUp(self) -> None:
        laya = TableLaya({"explain this": {"category": "screen"},
                          "push my changes": {"category": "github"}})
        self.old = laya_engine.set_engine(Engine(loader=lambda: laya, tier="fake"))

    def tearDown(self) -> None:
        laya_engine.set_engine(self.old)

    def test_accuracy_and_confusions(self) -> None:
        report = runner.run_eval(self.ROWS)
        self.assertEqual(report["n"], 4)
        self.assertAlmostEqual(report["category_accuracy"], 0.75)
        self.assertEqual(report["per_category"]["notes"], {"n": 1, "correct": 0})
        self.assertEqual(report["confusions"], [{"text": "note this", "expected": "notes",
                                                  "got": "chitchat"}])
        self.assertEqual(report["tier"], "fake")
        for key in ("p50", "p95", "max"):
            self.assertGreaterEqual(report["latency_ms"][key], 0.0)
        self.assertIn("rss_mb", report)

    def test_format_mentions_accuracy_and_latency(self) -> None:
        text = runner.format_report(runner.run_eval(self.ROWS))
        self.assertIn("category accuracy", text)
        self.assertIn("75.0%", text)
        self.assertIn("p95", text)
        self.assertIn("note this", text)

    def test_main_json(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = runner.main(["--json", "--limit", "3"], engine_factory=lambda tier: None)
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report["n"], 3)


if __name__ == "__main__":
    unittest.main()
