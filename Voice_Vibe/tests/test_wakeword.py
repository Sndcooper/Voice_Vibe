"""The dedicated wake word model and how the app hands over to Whisper.

What matters: audio is framed exactly as openWakeWord expects, one wake word
fires once, armed speech the model ignored is never transcribed, and Whisper
still vetoes a false alarm. The model is a fake; no audio device is used.
"""

from __future__ import annotations

import queue
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

import stubs

stubs.install()

from voicevibe.wake import PhraseMatcher  # noqa: E402
from voicevibe.wakeword import FRAME, WakeWordDetector, phrase_for  # noqa: E402

try:
    from voicevibe import app
except Exception:  # numpy / sounddevice / PIL missing on a bare checkout
    app = None


class FakeModel:
    """Scores 0.9 on frames whose first sample is positive, else 0."""

    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []
        self.resets = 0

    def predict(self, frame: np.ndarray) -> dict[str, float]:
        self.frames.append(frame)
        return {"hey_jarvis": 0.9 if frame[0] > 0 else 0.0}

    def reset(self) -> None:
        self.resets += 1


def detector(**kwargs):  # noqa: ANN003, ANN201
    fired: list[tuple[str, float]] = []
    d = WakeWordDetector(FakeModel(), lambda n, s: fired.append((n, s)), **kwargs)
    return d, fired


class TestPhrase(unittest.TestCase):
    def test_phrase_for(self) -> None:
        for model, phrase in (
            ("hey_jarvis", "hey jarvis"),
            ("alexa", "alexa"),
            ("C:/models/hey_computer.onnx", "hey computer"),
            ("hey_mycroft_v0.1.onnx", "hey mycroft"),
            ("ok-voice-vibe.onnx", "ok voice vibe"),
        ):
            with self.subTest(model=model):
                self.assertEqual(phrase_for(model), phrase)


class TestFraming(unittest.TestCase):
    def test_blocks_are_regrouped_into_80ms_int16_frames(self) -> None:
        d, _ = detector()
        block = np.full(480, -0.5, dtype=np.float32)  # the recorder's 30 ms blocks
        for _ in range(8):  # 3840 samples = exactly 3 frames
            d.process(block)
        frames = d.model.frames
        self.assertEqual([len(f) for f in frames], [FRAME] * 3)
        self.assertEqual(frames[0].dtype, np.int16)
        self.assertEqual(int(frames[0][0]), int(-0.5 * 32767))

    def test_the_remainder_waits_for_more(self) -> None:
        d, _ = detector()
        d.process(np.zeros(FRAME + 100, dtype=np.float32))
        self.assertEqual(len(d.model.frames), 1)
        d.process(np.zeros(FRAME - 100, dtype=np.float32))
        self.assertEqual(len(d.model.frames), 2)

    def test_clipping(self) -> None:
        d, _ = detector()
        d.process(np.full(FRAME, 3.0, dtype=np.float32))
        self.assertEqual(int(d.model.frames[0][0]), 32767)


class TestFiring(unittest.TestCase):
    def test_fires_above_threshold(self) -> None:
        d, fired = detector(threshold=0.5)
        d.process(np.full(FRAME, 0.2, dtype=np.float32))
        self.assertEqual(fired, [("hey_jarvis", 0.9)])

    def test_silence_does_not_fire(self) -> None:
        d, fired = detector()
        d.process(np.zeros(FRAME * 10, dtype=np.float32))
        self.assertEqual(fired, [])

    def test_threshold(self) -> None:
        d, fired = detector(threshold=0.95)
        d.process(np.full(FRAME, 0.2, dtype=np.float32))
        self.assertEqual(fired, [])

    def test_one_wake_word_fires_once(self) -> None:
        # Consecutive frames of the same word all score high.
        d, fired = detector(cooldown=1.5)
        d.process(np.full(FRAME * 5, 0.2, dtype=np.float32))
        self.assertEqual(len(fired), 1)

    def test_fires_again_after_the_cooldown(self) -> None:
        d, fired = detector(cooldown=0.01)
        d.process(np.full(FRAME, 0.2, dtype=np.float32))
        time.sleep(0.02)
        d.process(np.full(FRAME, 0.2, dtype=np.float32))
        self.assertEqual(len(fired), 2)

    def test_reset_forgets_partial_audio(self) -> None:
        d, _ = detector()
        d.process(np.zeros(FRAME - 1, dtype=np.float32))
        d.reset()
        d.process(np.zeros(10, dtype=np.float32))
        self.assertEqual(d.model.frames, [])
        self.assertEqual(d.model.resets, 1)


class TestThread(unittest.TestCase):
    def test_feed_is_scored_on_its_own_thread(self) -> None:
        d, fired = detector()
        d.start()
        try:
            d.feed(np.full(FRAME, 0.2, dtype=np.float32))
            deadline = time.monotonic() + 2
            while not fired and time.monotonic() < deadline:
                time.sleep(0.005)
        finally:
            d.stop()
        self.assertEqual(len(fired), 1)

    def test_a_full_queue_drops_instead_of_blocking(self) -> None:
        d, _ = detector()  # not started: nothing drains the queue
        for _ in range(500):
            d.feed(np.zeros(480, dtype=np.float32))  # must return immediately
        self.assertTrue(d._frames.full())


class TestCreate(unittest.TestCase):
    def test_missing_package_means_whisper(self) -> None:
        with mock.patch.dict(sys.modules, {"openwakeword": None}), \
                self.assertLogs("voicevibe.wakeword", level="WARNING"):
            self.assertIsNone(WakeWordDetector.create("hey_jarvis", lambda n, s: None))

    def test_wrong_sample_rate(self) -> None:
        with self.assertLogs("voicevibe.wakeword", level="WARNING"):
            self.assertIsNone(WakeWordDetector.create("hey_jarvis", lambda n, s: None,
                                                      sample_rate=44100))


class _Quiet:
    def __getattr__(self, name: str):  # noqa: ANN204
        return lambda *a, **k: None


@unittest.skipIf(app is None, "app.py needs numpy, sounddevice and pillow")
class TestAppHandOver(unittest.TestCase):
    def make(self, confirm: bool = True):  # noqa: ANN201
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.config = SimpleNamespace(
            wake={"confirm_with_whisper": confirm, "log_ignored": True, "model": "hey_jarvis"},
            audio={"sample_rate": 16000}, model={}, feedback={},
        )
        vv.wake_enabled = True
        vv._wake_state = app.ARMED
        vv._confirm_wake = False
        vv.detector, _ = detector()
        vv.wake_matcher = PhraseMatcher(["hey computer", "hey jarvis"], fuzzy=0.82)
        vv.sleep_matcher = PhraseMatcher(["never mind"])
        vv.session = SimpleNamespace(is_recording=True)
        vv.transcriber = None
        vv.beeper = vv.overlay = vv.history = vv.tray = vv.airoot = _Quiet()
        vv._indicate = lambda state: None
        vv.router = SimpleNamespace(is_stop=lambda t: False, split=lambda t: None)
        vv._last_activity = 0.0
        vv._ends_dictation = False
        vv.inserted = []
        vv._do_insert = lambda text, elapsed, **kwargs: vv.inserted.append(text)
        return vv

    def test_the_model_wakes_the_session(self) -> None:
        vv = self.make()
        vv._on_wake_word("hey_jarvis", 0.97)
        self.assertEqual(vv._wake_state, app.DICTATING)
        self.assertTrue(vv._confirm_wake)

    def test_ignored_when_not_armed_or_not_listening(self) -> None:
        vv = self.make()
        vv._wake_state = app.DICTATING
        vv._on_wake_word("hey_jarvis", 0.97)
        self.assertFalse(vv._confirm_wake)
        vv = self.make()
        vv.session.is_recording = False
        vv._on_wake_word("hey_jarvis", 0.97)
        self.assertEqual(vv._wake_state, app.ARMED)

    def test_frames_reach_the_model_only_while_armed(self) -> None:
        vv = self.make()
        vv._on_frame(np.zeros(480, dtype=np.float32))
        vv._wake_state = app.DICTATING
        vv._on_frame(np.zeros(480, dtype=np.float32))
        self.assertEqual(vv.detector._frames.qsize(), 1)

    def test_whisper_confirms_and_the_wake_phrase_is_stripped(self) -> None:
        vv = self.make()
        vv._on_wake_word("hey_jarvis", 0.97)
        vv._do_session("Hey Jarvis, open the report.", 0.1)
        self.assertEqual(vv.inserted, ["open the report."])
        vv._do_session("and the summary", 0.1)  # later utterances are plain dictation
        self.assertEqual(vv.inserted[-1], "and the summary")

    def test_wake_word_alone_types_nothing(self) -> None:
        vv = self.make()
        vv._on_wake_word("hey_jarvis", 0.97)
        vv._do_session("Hey Jarvis.", 0.1)
        self.assertEqual(vv.inserted, [])
        self.assertEqual(vv._wake_state, app.DICTATING)

    def test_a_false_alarm_goes_back_to_waiting(self) -> None:
        vv = self.make()
        vv._on_wake_word("hey_jarvis", 0.97)
        vv._do_session("they are driving to the airport", 0.1)
        self.assertEqual(vv.inserted, [])
        self.assertEqual(vv._wake_state, app.ARMED)

    def test_confirmation_can_be_turned_off(self) -> None:
        vv = self.make(confirm=False)
        vv._on_wake_word("hey_jarvis", 0.97)
        vv._do_session("open the report", 0.1)
        self.assertEqual(vv.inserted, ["open the report"])

    def test_armed_segments_are_never_transcribed(self) -> None:
        vv = self.make()
        vv.transcriber = mock.Mock()
        vv._jobs = queue.Queue()
        vv._jobs.put((np.zeros(16000, dtype=np.float32), app.SESSION))
        vv._jobs.put(None)
        vv._worker()
        vv.transcriber.transcribe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
