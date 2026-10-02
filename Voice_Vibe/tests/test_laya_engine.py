"""vvhub.laya_engine: the one place the hub talks to Laya.

No model is loaded here. Backends are fakes returning Laya's result shape, or
the built-in keyword backend, so the suite runs on a bare checkout.
"""

from __future__ import annotations

import unittest

import stubs

stubs.install()

from vvhub import laya_engine  # noqa: E402
from vvhub.laya_engine import Engine, KeywordBackend, LayaUnavailable  # noqa: E402


class ScriptedLaya:
    """Answers every question from a table, in Laya's result shape."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.calls: list[tuple] = []
        self.closed = False

    def predict(self, state, questions, min_confidence=None):  # noqa: ANN001, ANN201
        self.calls.append((state, questions, min_confidence))
        out = {}
        for qid, q in questions.items():
            spec = self.answers[qid]
            if q["type"] == "choice":
                choice, conf = spec
                probs = {k: (conf if k == choice else (1 - conf) / max(1, len(q["criteria"]) - 1))
                         for k in q["criteria"]}
                out[qid] = {"type": "choice", "choice": choice, "probabilities": probs,
                            "answer_confidence": conf}
            elif q["type"] == "score":
                out[qid] = {"type": "score", "score": spec, "answer_confidence": 0.9}
            else:
                out[qid] = {"type": "noul", "noul": spec, "answer_confidence": max(spec, 1 - spec)}
            if min_confidence is not None and out[qid]["answer_confidence"] < min_confidence:
                out[qid]["low_confidence"] = True
        return {"answers": out}

    def close(self) -> None:
        self.closed = True


class EngineTests(unittest.TestCase):
    def test_decide_passes_through_laya_shape(self) -> None:
        fake = ScriptedLaya({"category": ("screen", 0.9)})
        engine = Engine(loader=lambda: fake, tier="fake")
        q = {"category": {"type": "choice", "instructions": "?",
                          "criteria": {"screen": "s", "code": "c"}}}
        result = engine.decide("explain this", q, min_confidence=0.95)
        self.assertEqual(result["answers"]["category"]["choice"], "screen")
        self.assertTrue(result["answers"]["category"]["low_confidence"])
        self.assertEqual(fake.calls[0][2], 0.95)
        self.assertEqual(result["tier"], "fake")
        self.assertGreaterEqual(result["elapsed_ms"], 0)

    def test_default_min_confidence_is_applied(self) -> None:
        fake = ScriptedLaya({"q": ("a", 0.5)})
        engine = Engine(loader=lambda: fake, min_confidence=0.6)
        engine.decide("x", {"q": {"type": "choice", "instructions": "?",
                                  "criteria": {"a": "", "b": ""}}})
        self.assertEqual(fake.calls[0][2], 0.6)

    def test_score_normalised_to_unit_range(self) -> None:
        engine = Engine(loader=lambda: ScriptedLaya({"score": 2.0}))
        self.assertAlmostEqual(engine.score("x", "how risky", ["low", "mid", "high"]), 1.0)
        engine = Engine(loader=lambda: ScriptedLaya({"score": 1.0}))
        self.assertAlmostEqual(engine.score("x", "how risky", ["low", "mid", "high"]), 0.5)

    def test_yes_no(self) -> None:
        engine = Engine(loader=lambda: ScriptedLaya({"yes_no": 0.83}))
        self.assertAlmostEqual(engine.yes_no("x", "is it?"), 0.83)

    def test_loads_lazily_once_and_unloads_when_idle(self) -> None:
        made = []
        clock = [100.0]

        def loader():  # noqa: ANN202
            made.append(ScriptedLaya({"yes_no": 0.5}))
            return made[-1]

        engine = Engine(loader=loader, idle_seconds=60, clock=lambda: clock[0])
        self.assertFalse(engine.loaded)
        engine.yes_no("x", "?")
        engine.yes_no("x", "?")
        self.assertEqual(len(made), 1)
        clock[0] += 30
        self.assertFalse(engine.reap())
        clock[0] += 31
        self.assertTrue(engine.reap())
        self.assertFalse(engine.loaded)
        self.assertTrue(made[0].closed)
        engine.yes_no("x", "?")
        self.assertEqual(len(made), 2)

    def test_loader_failure_raises_unavailable_and_is_remembered(self) -> None:
        tries = []

        def loader():  # noqa: ANN202
            tries.append(1)
            raise ImportError("no torch")

        engine = Engine(loader=loader)
        with self.assertRaises(LayaUnavailable):
            engine.yes_no("x", "?")
        with self.assertRaises(LayaUnavailable):
            engine.yes_no("x", "?")
        self.assertEqual(len(tries), 1)
        self.assertFalse(engine.available())

    def test_fallback_drops_to_keywords(self) -> None:
        def loader():  # noqa: ANN202
            raise ImportError("no torch")

        engine = Engine(loader=loader, tier="gpu", fallback=True)
        self.assertEqual(engine.yes_no("x", "?"), 0.5)
        self.assertEqual(engine.tier, "keywords")


class KeywordBackendTests(unittest.TestCase):
    Q = {"category": {"type": "choice", "instructions": "Which?", "criteria": {
        "screen": "explain what is on the screen, this error",
        "github": "create a repository, push code, pull request",
        "chitchat": "small talk",
    }}}

    def test_picks_overlapping_option(self) -> None:
        result = KeywordBackend().predict({"request": "open a pull request"}, self.Q)
        self.assertEqual(result["answers"]["category"]["choice"], "github")

    def test_confidence_is_capped_so_policy_asks(self) -> None:
        answer = KeywordBackend().predict("explain this error on the screen", self.Q)
        self.assertEqual(answer["answers"]["category"]["choice"], "screen")
        self.assertLessEqual(answer["answers"]["category"]["answer_confidence"],
                             KeywordBackend.MAX_CONFIDENCE)

    def test_no_overlap_falls_to_last_option_with_low_confidence(self) -> None:
        answer = KeywordBackend().predict("zzz qqq", self.Q, min_confidence=0.5)
        a = answer["answers"]["category"]
        self.assertEqual(a["choice"], "chitchat")
        self.assertTrue(a["low_confidence"])

    def test_noul_and_score_are_neutral(self) -> None:
        q = {"n": {"type": "noul", "instructions": "?"},
             "s": {"type": "score", "instructions": "?", "criteria": ["a", "b", "c"]}}
        answers = KeywordBackend().predict("x", q)["answers"]
        self.assertEqual(answers["n"]["noul"], 0.5)
        self.assertEqual(answers["s"]["score"], 1.0)


class TierTests(unittest.TestCase):
    def test_forced_tier_wins(self) -> None:
        self.assertEqual(laya_engine.detect_tier(env={"VVHUB_LAYA_TIER": "keywords"}), "keywords")

    def test_no_laya_means_keywords(self) -> None:
        tier = laya_engine.detect_tier(env={}, has=lambda name: False)
        self.assertEqual(tier, "keywords")

    def test_gpu_when_cuda(self) -> None:
        tier = laya_engine.detect_tier(env={}, has=lambda name: True, cuda=lambda: True)
        self.assertEqual(tier, "gpu")

    def test_cpu_prefers_onnx_int8_file(self) -> None:
        tier = laya_engine.detect_tier(env={}, has=lambda name: True, cuda=lambda: False,
                                       onnx_file=lambda: "C:/m/laya.int8.onnx")
        self.assertEqual(tier, "onnx")
        tier = laya_engine.detect_tier(env={}, has=lambda name: True, cuda=lambda: False,
                                       onnx_file=lambda: None)
        self.assertEqual(tier, "cpu")

    def test_module_level_api_uses_installed_engine(self) -> None:
        old = laya_engine.set_engine(Engine(loader=lambda: ScriptedLaya({"yes_no": 0.25})))
        try:
            self.assertAlmostEqual(laya_engine.yes_no("x", "?"), 0.25)
        finally:
            laya_engine.set_engine(old)


if __name__ == "__main__":
    unittest.main()
