"""Opt-in guards against Whisper phantoms and repetition loops.

The model is faked; code defaults stay raw, config.toml turns the guards on.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

import stubs

stubs.install()

from voicevibe.transcriber import FALLBACK_TEMPERATURES, Transcriber  # noqa: E402


def _segment(text: str, logprob: float) -> SimpleNamespace:
    return SimpleNamespace(text=text, avg_logprob=logprob, no_speech_prob=0.0)


class TranscriptionGuardTests(unittest.TestCase):
    def make(self, segments, **cfg):  # noqa: ANN001, ANN201
        transcriber = Transcriber.__new__(Transcriber)
        transcriber.cfg = {"language": "en", **cfg}
        transcriber.initial_prompt = None
        transcriber.model = Mock()
        transcriber.model.transcribe.return_value = (iter(segments), None)
        return transcriber

    def run_on(self, transcriber) -> str:  # noqa: ANN001
        return transcriber._transcribe(np.ones(16000, dtype=np.float32), None)

    def test_defaults_stay_raw(self) -> None:
        t = self.make([_segment(" Thank you.", -1.2)])
        self.assertEqual(self.run_on(t), "Thank you.")
        self.assertEqual(t.model.transcribe.call_args.kwargs["temperature"], 0.0)

    def test_fallback_temperatures(self) -> None:
        t = self.make([_segment(" Hello there.", -0.2)], temperature_fallback=True)
        self.run_on(t)
        self.assertEqual(t.model.transcribe.call_args.kwargs["temperature"],
                         list(FALLBACK_TEMPERATURES))
        self.assertEqual(FALLBACK_TEMPERATURES[0], 0.0)  # clean decodes stay deterministic

    def test_unsure_short_phantom_dropped(self) -> None:
        segments = [_segment(" Open terminal.", -0.2), _segment(" Thank you.", -1.1)]
        t = self.make(segments, drop_unsure_short=True, unsure_max_words=5, unsure_logprob=-0.8)
        self.assertEqual(self.run_on(t), "Open terminal.")

    def test_long_or_confident_segments_kept(self) -> None:
        segments = [_segment(" Yes.", -0.3),
                    _segment(" this is a longer sentence the model was unsure of", -1.3)]
        text = self.run_on(self.make(segments, drop_unsure_short=True))
        self.assertIn("Yes.", text)
        self.assertIn("longer sentence", text)

    def test_real_short_speech_kept_even_when_unsure(self) -> None:
        # 2026-09-30: these were dropped when any short unsure segment was.
        for text, logprob in ((" ok computer", -1.09), (" Press Enter.", -1.07),
                              (" Open terminal.", -1.2)):
            t = self.make([_segment(text, logprob)], drop_unsure_short=True)
            self.assertEqual(self.run_on(t), text.strip())

    def test_confident_phantom_kept(self) -> None:
        # A clearly spoken "Thank you." is real speech.
        t = self.make([_segment(" Thank you.", -0.2)], drop_unsure_short=True)
        self.assertEqual(self.run_on(t), "Thank you.")


if __name__ == "__main__":
    unittest.main()
