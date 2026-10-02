"""Voice-control sessions: control mode, the logo, and the silence watchdog.

Reuses test_wake_request's fakes (no desktop, launcher or overlay is real).
"""

from __future__ import annotations

import json
import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import stubs

stubs.install()

import test_wake_request as twr  # noqa: E402

from voicevibe import app  # noqa: E402
from voicevibe.airoot import AirootBridge  # noqa: E402
from voicevibe.audio import SegmentRecorder  # noqa: E402

_Harness = twr.ImplicitRequestTests


class ControlModeTests(unittest.TestCase):
    """[control].session_mode = "control": every utterance while awake is a request."""

    make_base = _Harness.make
    said = _Harness.said
    typed = _Harness.typed
    enters = _Harness.enters

    def make(self):  # noqa: ANN201
        vv = self.make_base()
        vv.config.control["session_mode"] = "control"
        return vv

    def test_every_request_needs_no_prefix(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer.", "Open terminal.", "Open terminal.")
        self.assertEqual(vv.responder.launcher.launch.call_count, 2)
        self.assertEqual(self.typed(vv), "")

    def test_enter_keeps_the_session_awake(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer, open terminal.", "Type claude, press enter.",
                  "Type ls, press enter.")
        self.assertEqual(self.enters(vv), 2)
        self.assertEqual(vv._wake_state, app.DICTATING)
        self.assertEqual(self.typed(vv).lower(), "claudels")

    def test_unrecognised_is_still_typed(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer.", "Draft the meeting notes for Tuesday.")
        self.assertIn("Draft the meeting notes for Tuesday", self.typed(vv))

    def test_sleep_phrase_still_rearms(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer.", "Never mind.")
        self.assertEqual(vv._wake_state, app.ARMED)

    def test_dictation_mode_is_unchanged(self) -> None:
        vv = self.make_base()
        self.said(vv, "Hey computer, open terminal.", "Type claude, press enter.")
        self.assertEqual(vv._wake_state, app.ARMED)  # Enter ends it, as before


class LogoTests(unittest.TestCase):
    def listening(self, recording: bool, state: str, airoot: dict) -> bool:
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.session = SimpleNamespace(is_recording=recording)
        vv.wake_enabled = True
        vv._wake_state = state
        vv.config = SimpleNamespace(airoot=airoot)
        return vv._is_listening("armed")

    def test_show_while_armed(self) -> None:
        self.assertTrue(self.listening(True, app.ARMED, {"show_while_armed": True}))
        self.assertFalse(self.listening(True, app.ARMED, {}))
        self.assertTrue(self.listening(True, app.DICTATING, {}))
        self.assertFalse(self.listening(False, app.ARMED, {"show_while_armed": True}))

    def bridge(self, state: str) -> tuple[AirootBridge, list]:
        bridge = AirootBridge({"enabled": False})
        bridge.enabled = True
        sent: list = []
        bridge._send = sent.append
        bridge._state = state
        return bridge, sent

    def test_reply_never_dismisses_a_listening_logo(self) -> None:
        # 18:2x: "hey computer, open terminal" -> the spoken reply faded the logo
        # out and nothing brought it back.
        bridge, sent = self.bridge("listening")
        bridge.show_transcript("Opening Windows Terminal.", "Reply")
        self.assertEqual(sent, [])

    def test_completion_is_sent_while_transcribing(self) -> None:
        bridge, sent = self.bridge("busy")
        bridge.show_transcript("hello")
        self.assertEqual(json.loads(sent[0])["event"], "transcript")


class WatchdogTests(unittest.TestCase):
    def make(self, in_speech: bool = False):  # noqa: ANN201
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.config = SimpleNamespace(wake={"active_timeout": 40})
        vv.wake_enabled = True
        vv._wake_state = app.DICTATING
        vv.session = SimpleNamespace(is_recording=True, in_speech=in_speech)
        vv._jobs = queue.Queue()
        vv._last_activity = time.monotonic() - 100
        vv._arm = Mock()
        return vv

    def test_silence_rearms(self) -> None:
        vv = self.make()
        vv._watchdog_check()
        vv._arm.assert_called_once_with("silent for 40s")

    def test_talking_is_not_silence(self) -> None:
        vv = self.make(in_speech=True)
        vv._watchdog_check()
        vv._arm.assert_not_called()
        self.assertLess(time.monotonic() - vv._last_activity, 1)

    def test_pending_or_running_utterance_is_not_silence(self) -> None:
        vv = self.make()
        vv._jobs.put(("audio", app.SESSION))
        vv._watchdog_check()
        vv._arm.assert_not_called()
        vv = self.make()
        vv._job_running = True
        vv._watchdog_check()
        vv._arm.assert_not_called()

    def test_segmenter_reports_speech(self) -> None:
        rec = SegmentRecorder.__new__(SegmentRecorder)
        rec._lock = threading.Lock()
        rec._in_speech = True
        self.assertTrue(rec.in_speech)
        rec._in_speech = False
        self.assertFalse(rec.in_speech)


if __name__ == "__main__":
    unittest.main()
