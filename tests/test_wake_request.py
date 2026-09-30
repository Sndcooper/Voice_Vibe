"""A request right after "hey computer" needs no "computer" prefix.

Desktop, launching and the model are faked.
"""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import stubs

stubs.install()

from voicevibe import app  # noqa: E402
from voicevibe.control import Router  # noqa: E402
from voicevibe.inserter import Inserter  # noqa: E402
from voicevibe.intent import Responder  # noqa: E402
from voicevibe.screen import ScreenContext  # noqa: E402
from voicevibe.wake import PhraseMatcher  # noqa: E402


class ImplicitRequestTests(unittest.TestCase):
    """Right after the wake phrase, the "computer" prefix is optional once."""

    def make(self):  # noqa: ANN201
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.config = SimpleNamespace(output={}, control={}, feedback={}, wake={})
        vv.wake_enabled = True
        vv._wake_state = app.ARMED
        vv._confirm_wake = False
        vv._last_inserted = ""
        vv._ends_dictation = False
        vv.wake_matcher = PhraseMatcher(["hey computer"])
        vv.sleep_matcher = PhraseMatcher(["never mind"])
        vv.executor = app.Executor(keyboard=stubs.FakeController(),
            desktop=SimpleNamespace(foreground=lambda: 1, process=lambda hwnd: "test.exe"),
            confirmer=Mock(return_value=True))
        vv.router = Router({"enabled": True}, executor=vv.executor, finder=Mock(), profiles={})
        vv.router._front = lambda: 1
        launcher = Mock()
        # Like the real allowlist: only an app name resolves, not a sentence.
        launcher.resolve.side_effect = lambda name: (
            SimpleNamespace(name="Terminal") if name.lower().strip() == "terminal" else None)
        launcher.launch.return_value = True
        vv.responder = Responder(launcher=launcher,
            screen=SimpleNamespace(read=lambda **kwargs: ScreenContext(title="Test")))
        vv.inserter = Inserter({"mode": "type"}, [])
        vv.history, vv.overlay, vv.airoot, vv.beeper, vv.voice = (Mock() for _ in range(5))
        vv._set_wake_bias = Mock()
        vv._indicate = Mock()
        vv._session_tray = lambda: "armed"
        vv.LAUNCH_SETTLE_SECONDS = 0.0
        vv.LAUNCH_FOCUS_SECONDS = 0.3
        return vv

    def said(self, vv, *utterances: str, windows=(1, 2)) -> None:  # noqa: ANN001
        """`windows`: foreground hwnds; the first is before the launch, the
        last repeats (a changed hwnd = the launched app came to the front)."""
        seq = list(windows)

        def front() -> int:
            return seq.pop(0) if len(seq) > 1 else seq[0]

        with patch.object(app, "focused_window", return_value="Test"), \
                patch.object(app, "foreground", side_effect=front):
            for text in utterances:
                vv._do_session(text, 0.1)

    def typed(self, vv) -> str:  # noqa: ANN001
        return "".join(value for kind, value in vv.inserter.keyboard.events if kind == "type")

    def test_same_breath(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer, open terminal.")
        vv.responder.launcher.launch.assert_called_once()
        self.assertEqual(self.typed(vv), "")

    def test_next_utterance(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer.", "Open terminal.")
        vv.responder.launcher.launch.assert_called_once()
        self.assertEqual(self.typed(vv), "")

    def test_only_once_then_dictation(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer.", "Open terminal.", "Open terminal.")
        vv.responder.launcher.launch.assert_called_once()
        self.assertIn("Open terminal", self.typed(vv))

    def test_prefix_still_works_later(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer.", "Draft the notes.", "Computer open terminal.")
        vv.responder.launcher.launch.assert_called_once()

    def test_unrecognised_request_is_typed(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer.", "Draft the meeting notes for Tuesday.")
        vv.responder.launcher.launch.assert_not_called()
        self.assertIn("Draft the meeting notes for Tuesday", self.typed(vv))

    def test_rearm_cancels_the_pending_request(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer.")
        vv._arm("silent for 20s")
        self.said(vv, "Open terminal.")  # armed again: ignored, not typed
        vv.responder.launcher.launch.assert_not_called()
        self.assertEqual(self.typed(vv), "")

    def test_no_time_limit_while_awake(self) -> None:
        # 2026-09-30 17:57: a long request ending 15 s after the wake was typed.
        vv = self.make()
        self.said(vv, "Hey computer.")
        vv._last_activity -= 60  # time passing does not matter, only re-arming
        self.said(vv, "Open terminal.")
        vv.responder.launcher.launch.assert_called_once()

    def test_open_then_type(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer, open terminal and type git status.")
        vv.responder.launcher.launch.assert_called_once()
        self.assertEqual(self.typed(vv).strip().lower(), "git status.")

    def test_open_then_unhandled_rest_is_typed_in_the_new_window(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer.", "Open terminal and then start the tests.")
        vv.responder.launcher.launch.assert_called_once()  # never "an app called the tests"
        self.assertIn("start the tests", self.typed(vv).lower())
        self.assertNotIn("don't know", str(vv.voice.say.call_args_list))

    def test_rest_is_dropped_if_the_window_never_comes_up(self) -> None:
        vv = self.make()
        self.said(vv, "Hey computer, open terminal and type secret notes.", windows=(1,))
        vv.responder.launcher.launch.assert_called_once()
        self.assertEqual(self.typed(vv), "")
        self.assertIn("didn't come to the front", str(vv.voice.say.call_args_list))

    def test_armed_speech_is_still_ignored(self) -> None:
        vv = self.make()
        self.said(vv, "Open terminal.")
        vv.responder.launcher.launch.assert_not_called()
        self.assertEqual(self.typed(vv), "")


class SplitThenTests(unittest.TestCase):
    def test_split(self) -> None:
        from voicevibe.intent import _split_then

        self.assertEqual(_split_then("terminal and start the tests")[::2],
                         ("terminal", "start the tests"))
        self.assertEqual(_split_then("notepad, then type hello.")[::2], ("notepad", "type hello"))
        self.assertEqual(_split_then("terminal and then run it")[::2], ("terminal", "run it"))
        self.assertEqual(_split_then("blender")[::2], ("blender", ""))


if __name__ == "__main__":
    unittest.main()
