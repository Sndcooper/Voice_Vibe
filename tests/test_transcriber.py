"""Quiet speech and uncertain segments must reach raw dictation output."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from voicevibe.transcriber import Transcriber


class TestRawTranscription(unittest.TestCase):
    def make(self, **cfg):
        transcriber = Transcriber.__new__(Transcriber)
        transcriber.cfg = cfg
        transcriber.initial_prompt = None
        transcriber.model = Mock()
        transcriber.model.transcribe.return_value = (
            iter([SimpleNamespace(text=" quiet speech", no_speech_prob=.99,
                                  avg_logprob=-1.8)]), None
        )
        return transcriber

    def test_quiet_audio_survives_legacy_peak_setting(self):
        transcriber = self.make(silence_peak=.1)
        audio = np.full(16000, .00001, dtype=np.float32)
        self.assertEqual(transcriber.transcribe(audio), "quiet speech")
        args = transcriber.model.transcribe.call_args
        self.assertIs(args.args[0], audio)
        self.assertFalse(args.kwargs["vad_filter"])
        self.assertIsNone(args.kwargs["no_speech_threshold"])

    def test_no_second_segment_drop_when_filter_is_opted_in(self):
        transcriber = self.make(no_speech_threshold=.6, vad_filter=True)
        self.assertEqual(transcriber.transcribe(np.ones(16000)), "quiet speech")

    def test_empty_buffer_is_not_decoded(self):
        transcriber = self.make()
        self.assertEqual(transcriber.transcribe(np.array([], dtype=np.float32)), "")
        transcriber.model.transcribe.assert_not_called()
