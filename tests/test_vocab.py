"""Hotwords and per-app prompt hints.

What matters: hotwords reach faster-whisper, the hint follows the front app,
and nothing but the wake phrases is in the prompt while a session is armed --
a code-flavoured hint there would only make wake detection worse.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

import stubs

stubs.install()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voicevibe.config import DEFAULTS  # noqa: E402
from voicevibe.transcriber import Transcriber  # noqa: E402
from voicevibe.vocab import BUILTIN_PROMPTS, Vocabulary, echoes_prompt  # noqa: E402

try:
    from voicevibe import app
except Exception:  # numpy / sounddevice / PIL missing on a bare checkout
    app = None


class TestVocabulary(unittest.TestCase):
    def test_hotwords(self) -> None:
        vocab = Vocabulary({"hotwords": ["PyTorch", " Voice Vibe ", "", "PyTorch"]})
        self.assertEqual(vocab.hotwords_text(), "PyTorch, Voice Vibe")
        self.assertIsNone(Vocabulary().hotwords_text())
        self.assertEqual(Vocabulary({"hotwords": "Kubernetes"}).hotwords_text(), "Kubernetes")

    def test_builtin_hints_by_process(self) -> None:
        vocab = Vocabulary(DEFAULTS["vocab"])
        self.assertIn("pytest", vocab.hint("Code.exe"))
        self.assertIn("git status", vocab.hint("WindowsTerminal.exe"))
        self.assertIn("summarize", vocab.hint("claude.exe"))
        self.assertEqual(vocab.hint("notepad.exe"), "")
        self.assertEqual(vocab.hint(""), "")

    def test_user_hints_override_and_disable(self) -> None:
        vocab = Vocabulary({"prompts": {"Code.exe": "FastAPI, pydantic.", "claude.exe": ""}})
        self.assertEqual(vocab.hint("code.exe"), "FastAPI, pydantic.")
        self.assertEqual(vocab.hint("claude.exe"), "")
        self.assertEqual(vocab.hint("cursor.exe"), BUILTIN_PROMPTS["cursor.exe"])

    def test_builtins_can_be_turned_off(self) -> None:
        vocab = Vocabulary({"app_prompts": False, "prompts": {"code.exe": "mine"}})
        self.assertEqual(vocab.hint("code.exe"), "mine")
        self.assertEqual(vocab.hint("cursor.exe"), "")


class TestPromptEcho(unittest.TestCase):
    HINT = BUILTIN_PROMPTS["code.exe"]

    def test_the_logged_phantom_is_an_echo(self) -> None:
        # Real log line, 2026-09-28, silent input with the VS Code hint.
        text = ("Open a pull request after the git commit commit commit commit commit "
                "commit commit commit")
        self.assertTrue(echoes_prompt(text, self.HINT))

    def test_the_whole_hint_read_back(self) -> None:
        self.assertTrue(echoes_prompt(self.HINT, self.HINT))

    def test_real_dictation_sharing_a_phrase_is_kept(self) -> None:
        for text in (
            "open a pull request after the git commit and tag the release for Friday",
            "please run pytest before you merge",
            "Thank you.",
            "commit",
        ):
            with self.subTest(text=text):
                self.assertFalse(echoes_prompt(text, self.HINT))

    def test_no_prompt_no_echo(self) -> None:
        self.assertFalse(echoes_prompt("open a pull request after the git commit", None))
        self.assertFalse(echoes_prompt("", self.HINT))


class TestTranscriberHotwords(unittest.TestCase):
    def test_hotwords_are_passed_through(self) -> None:
        transcriber = Transcriber.__new__(Transcriber)
        transcriber.cfg = {}
        transcriber.initial_prompt = "Code words."
        transcriber.hotwords = "PyTorch, Voice Vibe"
        transcriber.model = Mock()
        transcriber.model.transcribe.return_value = (iter([SimpleNamespace(text=" hi")]), None)
        transcriber.transcribe(np.ones(1600, dtype=np.float32))
        kwargs = transcriber.model.transcribe.call_args.kwargs
        self.assertEqual(kwargs["hotwords"], "PyTorch, Voice Vibe")
        self.assertEqual(kwargs["initial_prompt"], "Code words.")

    def test_no_hotwords_by_default(self) -> None:
        self.assertIsNone(Transcriber.hotwords)


@unittest.skipIf(app is None, "app.py needs numpy, sounddevice and pillow")
class TestDecoderPrompt(unittest.TestCase):
    def make(self, initial_prompt: str = "", prompts=None):  # noqa: ANN001, ANN201
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.config = SimpleNamespace(
            model={"initial_prompt": initial_prompt},
            wake={"bias_prompt": True, "phrases": ["hey computer", "ok computer"]},
        )
        vv.wake_enabled = True
        vv.vocab = Vocabulary({"prompts": prompts or {}})
        return vv

    def test_armed_is_wake_phrases_only(self) -> None:
        vv = self.make("Meeting notes.")
        prompt = vv._decoder_prompt(armed=True, process="code.exe")
        self.assertIn("hey computer", prompt)
        self.assertNotIn("pytest", prompt)

    def test_dictating_adds_the_front_apps_hint(self) -> None:
        vv = self.make("Meeting notes.")
        prompt = vv._decoder_prompt(armed=False, process="code.exe")
        self.assertTrue(prompt.startswith("Meeting notes."))
        self.assertIn("pytest", prompt)
        self.assertNotIn("hey computer", prompt)

    def test_nothing_to_say_is_none(self) -> None:
        self.assertIsNone(self.make()._decoder_prompt(armed=False, process="notepad.exe"))

    def test_hint_alone(self) -> None:
        vv = self.make(prompts={"notepad.exe": "Grocery list."})
        self.assertEqual(vv._decoder_prompt(armed=False, process="notepad.exe"), "Grocery list.")


if __name__ == "__main__":
    unittest.main()
