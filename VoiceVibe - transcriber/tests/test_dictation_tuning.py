"""Decoder hints must preserve speech and reject prompt-only hallucinations."""
import sys
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from voicevibe.app import VoiceVibe
from voicevibe.config import load_config
from voicevibe.vocab import Vocabulary


class DictationTuning(unittest.TestCase):
    def setUp(self):
        self.app = VoiceVibe.__new__(VoiceVibe)
        self.app.config = load_config(Path(__file__).resolve().parents[1] / "config.toml")
        self.app.vocab = Vocabulary(self.app.config.vocab)
        self.app.transcriber = Mock()
        self.app.inserter = Mock()
        self.app.inserter.insert.side_effect = lambda text: text
        self.app.airoot = Mock()
        self.app.beeper = Mock()
        self.app.overlay = Mock()

    def decode(self, text, process="code.exe"):
        self.app.transcriber.transcribe.return_value = text
        with patch("voicevibe.app.front_process", return_value=process), patch("voicevibe.app.focused_window", return_value="test"):
            self.app._transcribe_and_insert(np.zeros(16000, dtype=np.float32))

    def test_app_hint_changes_with_each_utterance(self):
        self.decode("Please fix my function.")
        self.assertIn("pytest", self.app.transcriber.initial_prompt)
        self.decode("Please fix my function.", "notepad.exe")
        self.assertIsNone(self.app.transcriber.initial_prompt)

    def test_prompt_echo_never_reaches_inserter(self):
        self.decode(self.app.vocab.hint("code.exe"))
        self.app.inserter.insert.assert_not_called()
        self.app.beeper.empty.assert_called_once()

    def test_real_speech_sharing_prompt_words_is_kept(self):
        self.decode("Please run pytest tomorrow and send me the results.")
        self.app.inserter.insert.assert_called_once_with("Please run pytest tomorrow and send me the results.")

    @unittest.skipUnless(sys.platform == "win32", "Windows desktop launcher")
    def test_launcher_loads_transcriber_with_full_app_installed(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([os.environ["COMSPEC"], "/d", "/c", ".\\run.bat", "--help"],
                                cwd=root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Press Ctrl+Alt+Space and it listens and types what you say.", result.stdout)


if __name__ == "__main__":
    unittest.main()
