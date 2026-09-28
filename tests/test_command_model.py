"""The small command model: when it is loaded and which utterances it gets.

What matters: dictation is never left with the small model's text. Only
utterances that turn out to be commands (or that can only be commands) keep
its transcript; everything else is transcribed again by the dictation model.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

import stubs

stubs.install()

from voicevibe.transcriber import choose_command_model, model_size  # noqa: E402

try:
    from voicevibe import app
except Exception:  # numpy / sounddevice / PIL missing on a bare checkout
    app = None


class TestChoosing(unittest.TestCase):
    def test_sizes(self) -> None:
        for name, rank in (
            ("tiny.en", 0), ("base", 1), ("small.en", 2), ("distil-small.en", 2),
            ("medium", 3), ("large-v3", 4), ("deepdml/faster-whisper-large-v3-turbo-ct2", 4),
            ("Systran/faster-distil-whisper-large-v3", 4),
        ):
            with self.subTest(name=name):
                self.assertEqual(model_size(name), rank)

    def test_auto(self) -> None:
        self.assertEqual(choose_command_model("auto", "small.en", "en"), "base.en")
        self.assertEqual(choose_command_model("auto", "large-v3", None), "base")
        self.assertEqual(choose_command_model("auto", "medium", "de"), "base")

    def test_no_second_model_when_the_main_one_is_small(self) -> None:
        self.assertIsNone(choose_command_model("auto", "base.en", "en"))
        self.assertIsNone(choose_command_model("auto", "tiny.en", "en"))
        self.assertIsNone(choose_command_model("small", "small.en", "en"))

    def test_off_and_explicit(self) -> None:
        for off in ("", "none", "off", "false"):
            self.assertIsNone(choose_command_model(off, "large-v3", "en"))
        self.assertEqual(choose_command_model("tiny.en", "small.en", "en"), "tiny.en")


class FakeRouter:
    def __init__(self, enabled: bool = True, expects: bool = False) -> None:
        self.enabled = enabled
        self.expects = expects

    def expects_command(self) -> bool:
        return self.expects

    def split(self, text: str) -> str | None:
        return text[len("computer "):] if text.lower().startswith("computer ") else None


def model(text: str) -> Mock:
    m = Mock()
    m.transcribe.return_value = text
    m.initial_prompt = None
    return m


@unittest.skipIf(app is None, "app.py needs numpy, sounddevice and pillow")
class TestRouting(unittest.TestCase):
    def make(self, fast_text="computer scroll down", main_text="the main transcript",
             fast=True, **router):  # noqa: ANN001, ANN003, ANN201
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.config = SimpleNamespace(
            model={"command_max_seconds": 3.0, "initial_prompt": ""},
            audio={"sample_rate": 16000},
            wake={"bias_prompt": True, "phrases": ["hey computer"]},
        )
        vv.wake_enabled = True
        vv.vocab = SimpleNamespace(hint=lambda process: "")
        vv.router = FakeRouter(**router)
        vv.transcriber = model(main_text)
        vv.command_transcriber = model(fast_text) if fast else None
        return vv

    def seconds(self, s: float) -> np.ndarray:
        return np.zeros(int(16000 * s), dtype=np.float32)

    def test_a_short_command_keeps_the_fast_transcript(self) -> None:
        vv = self.make()
        text = vv._transcribe_job(self.seconds(1.5), app.SESSION, armed=False)
        self.assertEqual(text, "computer scroll down")
        vv.transcriber.transcribe.assert_not_called()

    def test_short_dictation_is_redone_by_the_dictation_model(self) -> None:
        vv = self.make(fast_text="the quick fox")
        self.assertEqual(vv._transcribe_job(self.seconds(1.5), app.SESSION, armed=False),
                         "the main transcript")
        vv.command_transcriber.transcribe.assert_called_once()

    def test_long_utterances_go_straight_to_the_dictation_model(self) -> None:
        vv = self.make()
        vv._transcribe_job(self.seconds(8), app.SESSION, armed=False)
        vv.command_transcriber.transcribe.assert_not_called()

    def test_armed_wake_checks_use_the_fast_model(self) -> None:
        vv = self.make(fast_text="hey computer")
        self.assertEqual(vv._transcribe_job(self.seconds(8), app.SESSION, armed=True),
                         "hey computer")
        vv.transcriber.transcribe.assert_not_called()

    def test_expected_answers_use_the_fast_model(self) -> None:
        vv = self.make(fast_text="7", expects=True)
        self.assertEqual(vv._transcribe_job(self.seconds(1), app.SESSION, armed=False), "7")

    def test_no_first_pass_when_commands_are_off(self) -> None:
        vv = self.make(enabled=False)
        vv._transcribe_job(self.seconds(1), app.SESSION, armed=False)
        vv.command_transcriber.transcribe.assert_not_called()

    def test_hotkey_dictation_is_never_first_passed(self) -> None:
        vv = self.make()
        vv._transcribe_job(self.seconds(1), app.INSERT, armed=False)
        vv.command_transcriber.transcribe.assert_not_called()

    def test_without_a_command_model_everything_is_main(self) -> None:
        vv = self.make(fast=False)
        self.assertEqual(vv._transcribe_job(self.seconds(1), app.SESSION, armed=True),
                         "the main transcript")

    def test_both_models_get_the_prompt(self) -> None:
        vv = self.make()
        vv._transcribe_job(self.seconds(1), app.SESSION, armed=True)
        self.assertIn("hey computer", vv.transcriber.initial_prompt)
        self.assertEqual(vv.command_transcriber.initial_prompt, vv.transcriber.initial_prompt)


if __name__ == "__main__":
    unittest.main()
