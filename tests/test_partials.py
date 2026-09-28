"""Interim transcripts while speaking.

What matters: an interim decode never delays the final one (it steps aside
when the model is busy), a stale interim never replaces the final text, and
nothing is shown for speech that is not meant for the cursor (an armed
session, a confirmation answer).
"""

from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

import stubs

stubs.install()

from voicevibe.transcriber import Transcriber  # noqa: E402

try:
    from voicevibe import app
    from voicevibe.audio import Recorder, SegmentRecorder
except Exception:  # numpy / sounddevice / PIL missing on a bare checkout
    app = None

RATE = 16000


def transcriber(text: str = "hello there") -> Transcriber:
    t = Transcriber.__new__(Transcriber)
    t.cfg = {"beam_size": 3}
    t.initial_prompt = None
    t.model = Mock()
    t.model.transcribe.side_effect = lambda *a, **k: (iter([SimpleNamespace(text=" " + text)]), None)
    return t


class TestDecodeLock(unittest.TestCase):
    def test_interim_steps_aside_while_busy(self) -> None:
        t = transcriber()
        t._decode_lock().acquire()  # a final transcript is running
        try:
            self.assertIsNone(t.transcribe(np.ones(RATE, np.float32), wait=False))
        finally:
            t._decode_lock().release()
        self.assertEqual(t.transcribe(np.ones(RATE, np.float32), wait=False), "hello there")

    def test_beam_override(self) -> None:
        t = transcriber()
        t.transcribe(np.ones(RATE, np.float32), beam_size=1)
        self.assertEqual(t.model.transcribe.call_args.kwargs["beam_size"], 1)
        t.transcribe(np.ones(RATE, np.float32))
        self.assertEqual(t.model.transcribe.call_args.kwargs["beam_size"], 3)

    def test_final_waits_its_turn(self) -> None:
        t = transcriber()
        lock = t._decode_lock()
        lock.acquire()
        results: list[str] = []
        worker = threading.Thread(target=lambda: results.append(t.transcribe(np.ones(RATE))))
        worker.start()
        worker.join(0.05)
        self.assertEqual(results, [])  # still waiting, not dropped
        lock.release()
        worker.join(1)
        self.assertEqual(results, ["hello there"])


def blocks(level: float, count: int, size: int = 480) -> list[np.ndarray]:
    return [np.full((size, 1), level, dtype=np.float32) for _ in range(count)]


@unittest.skipIf(app is None, "needs numpy, sounddevice and pillow")
class TestSnapshots(unittest.TestCase):
    def test_session_snapshot_is_the_utterance_in_progress(self) -> None:
        done: list[np.ndarray] = []
        rec = SegmentRecorder(RATE, None, done.append, silence_duration=0.3, min_segment=0.1)
        for b in blocks(0.0005, 20):  # room tone
            rec._callback(b, len(b), None, None)
        self.assertIsNone(rec.snapshot())
        for b in blocks(0.3, 10):  # speech
            rec._callback(b, len(b), None, None)
        take, audio = rec.snapshot()
        self.assertTrue(rec.still(take))
        self.assertGreater(len(audio), 10 * 480 - 1)
        for b in blocks(0.0005, 30):  # the pause ends it
            rec._callback(b, len(b), None, None)
        self.assertEqual(len(done), 1)
        self.assertFalse(rec.still(take))
        self.assertIsNone(rec.snapshot())

    def test_each_utterance_gets_a_new_id(self) -> None:
        rec = SegmentRecorder(RATE, None, lambda a: None, silence_duration=0.3, min_segment=0.1)
        ids = []
        for _ in range(2):
            for b in blocks(0.0005, 20) + blocks(0.3, 10):
                rec._callback(b, len(b), None, None)
            ids.append(rec.snapshot()[0])
            for b in blocks(0.0005, 30):
                rec._callback(b, len(b), None, None)
        self.assertNotEqual(ids[0], ids[1])

    def test_hotkey_recording_snapshot(self) -> None:
        rec = Recorder(RATE)
        self.assertIsNone(rec.snapshot())
        rec._stream = object()  # recording, without a real device
        rec._take = 7
        for b in blocks(0.1, 4):
            rec._callback(b, len(b), None, None)
        take, audio = rec.snapshot()
        self.assertEqual((take, len(audio)), (7, 1920))
        self.assertTrue(rec.still(7))
        rec._stream = None
        self.assertFalse(rec.still(7))


class FakeSource:
    def __init__(self, seconds: float, take: int = 1, still: bool = True) -> None:
        self.audio = np.zeros(int(RATE * seconds), dtype=np.float32)
        self.take = take
        self.alive = still

    def snapshot(self):  # noqa: ANN201
        return self.take, self.audio

    def still(self, take: int) -> bool:
        return self.alive and take == self.take


@unittest.skipIf(app is None, "app.py needs numpy, sounddevice and pillow")
class TestPartialLoop(unittest.TestCase):
    def make(self, source: FakeSource | None, text="hello there", busy=False, pending=False):  # noqa: ANN001, ANN201
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.config = SimpleNamespace(audio={"sample_rate": RATE}, continuous={})
        vv.shown = []
        vv.airoot = SimpleNamespace(show_transcript=lambda t, label="": vv.shown.append((t, label)))
        vv.overlay = SimpleNamespace(show=lambda *a, **k: None)
        vv.confirmer = SimpleNamespace(pending=pending)
        model = Mock()
        model.transcribe.return_value = None if busy else text
        vv.transcriber = model
        vv.command_transcriber = None
        vv._partial_source = lambda: source
        return vv

    def test_shows_interim_text(self) -> None:
        vv = self.make(FakeSource(1.5))
        self.assertEqual(vv._partial_once((0, 0)), (1, int(RATE * 1.5)))
        self.assertEqual(vv.shown, [("hello there", "Listening")])
        self.assertEqual(vv.transcriber.transcribe.call_args.kwargs, {"beam_size": 1, "wait": False})

    def test_prefers_the_command_model(self) -> None:
        vv = self.make(FakeSource(1.5))
        vv.command_transcriber = Mock()
        vv.command_transcriber.transcribe.return_value = "fast"
        vv._partial_once((0, 0))
        vv.transcriber.transcribe.assert_not_called()
        self.assertEqual(vv.shown, [("fast", "Listening")])

    def test_too_short_to_bother(self) -> None:
        vv = self.make(FakeSource(0.5))
        self.assertEqual(vv._partial_once((0, 0)), (0, 0))
        vv.transcriber.transcribe.assert_not_called()

    def test_waits_for_the_take_to_grow(self) -> None:
        vv = self.make(FakeSource(1.5))
        self.assertEqual(vv._partial_once((1, int(RATE * 1.3))), (1, int(RATE * 1.3)))
        vv.transcriber.transcribe.assert_not_called()

    def test_a_busy_model_is_skipped_not_waited_for(self) -> None:
        vv = self.make(FakeSource(1.5), busy=True)
        self.assertEqual(vv._partial_once((0, 0)), (0, 0))
        self.assertEqual(vv.shown, [])

    def test_a_stale_result_is_dropped(self) -> None:
        # The utterance ended while decoding: the final transcript is showing.
        vv = self.make(FakeSource(1.5, still=False))
        vv._partial_once((0, 0))
        self.assertEqual(vv.shown, [])

    def test_nothing_during_a_confirmation(self) -> None:
        vv = self.make(FakeSource(1.5), pending=True)
        vv._partial_once((0, 0))
        vv.transcriber.transcribe.assert_not_called()

    def test_no_source_no_work(self) -> None:
        vv = self.make(None)
        vv._partial_once((0, 0))
        vv.transcriber.transcribe.assert_not_called()


@unittest.skipIf(app is None, "app.py needs numpy, sounddevice and pillow")
class TestSource(unittest.TestCase):
    def make(self, hotkey=False, session=False, armed=False):  # noqa: ANN001, ANN201
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.recorder = SimpleNamespace(is_recording=hotkey)
        vv.session = SimpleNamespace(is_recording=session)
        vv.wake_enabled = True
        vv._wake_state = app.ARMED if armed else app.DICTATING
        return vv

    def test_sources(self) -> None:
        vv = self.make(hotkey=True)
        self.assertIs(vv._partial_source(), vv.recorder)
        vv = self.make(session=True)
        self.assertIs(vv._partial_source(), vv.session)
        self.assertIsNone(self.make(session=True, armed=True)._partial_source())
        self.assertIsNone(self.make()._partial_source())

    def test_enabled(self) -> None:
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        for setting, device, expected in (
            ("auto", "cuda", True), ("auto", "cpu", False), (True, "cpu", True),
            ("true", "cpu", True), (False, "cuda", False), ("off", "cuda", False),
        ):
            with self.subTest(setting=setting, device=device):
                vv.config = SimpleNamespace(continuous={"partials": setting})
                vv.transcriber = SimpleNamespace(device=device)
                self.assertEqual(vv._partials_enabled(), expected)


if __name__ == "__main__":
    unittest.main()
