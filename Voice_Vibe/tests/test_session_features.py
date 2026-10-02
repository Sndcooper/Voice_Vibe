"""Session-only restoration; all desktop, speech and input effects are faked."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import stubs
stubs.install()

from voicevibe import app
from voicevibe.control import Router
from voicevibe.inserter import Inserter
from voicevibe.intent import Responder
from voicevibe.screen import ScreenContext
from voicevibe.wake import PhraseMatcher


class TestSessionFeatures(unittest.TestCase):
    def make(self, confirm=True):
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.config = SimpleNamespace(output={}, control={}, feedback={}, wake={})
        vv.wake_enabled = True
        vv._wake_state = app.DICTATING
        vv._last_inserted = "Meet Tuesday. "
        vv._ends_dictation = False
        vv.wake_matcher = PhraseMatcher(["hey computer"])
        vv.sleep_matcher = PhraseMatcher(["never mind"])
        vv.executor = app.Executor(keyboard=stubs.FakeController(),
            desktop=SimpleNamespace(foreground=lambda: 1, process=lambda hwnd: "test.exe"),
            confirmer=Mock(return_value=confirm))
        vv.router = Router({"enabled": True}, executor=vv.executor,
                           finder=Mock(), profiles={})
        # Router's desktop is injected; never query the real foreground app.
        vv.router._front = lambda: 1
        launcher = Mock()
        launcher.resolve.return_value = SimpleNamespace(name="Notepad")
        launcher.launch.return_value = True
        vv.responder = Responder(launcher=launcher,
            screen=SimpleNamespace(read=lambda **kwargs: ScreenContext(title="Test editor")))
        vv.inserter = Inserter({"mode": "type"}, [])
        vv.history = Mock()
        vv.overlay = Mock()
        vv.airoot = Mock()
        vv.beeper = Mock()
        vv.voice = Mock()
        return vv

    def test_plain_dictation_does_not_launch_answer_or_edit(self):
        for text in ("computer open notepad", "what's on my screen", "scratch that"):
            vv = self.make()
            vv.config.output["spoken_edits"] = True  # obsolete option cannot leak
            with patch.object(app, "focused_window", return_value="Test"):
                vv._do_insert(text, .1)
            vv.responder.launcher.launch.assert_not_called()
            vv.voice.say.assert_not_called()
            self.assertTrue(any(kind == "type" for kind, _ in vv.inserter.keyboard.events))
            self.assertEqual(vv._last_inserted, "")

    def test_prefixed_session_launch(self):
        vv = self.make()
        vv._do_session("computer open notepad", .1)
        vv.responder.launcher.launch.assert_called_once()
        vv.voice.say.assert_called_once_with("Opening Notepad.")
        self.assertEqual(vv.inserter.keyboard.events, [])

    def test_prefixed_screen_question(self):
        vv = self.make()
        vv._do_session("computer where am I", .1)
        vv.voice.say.assert_called_once_with("You're in Test editor.")

    def test_armed_session_ignores_commands(self):
        vv = self.make()
        vv._wake_state = app.ARMED
        vv._do_session("computer open notepad", .1)
        vv.responder.launcher.launch.assert_not_called()
        self.assertEqual(vv.inserter.keyboard.events, [])

    def test_delete_edit_requires_confirmation(self):
        vv = self.make(confirm=False)
        vv._do_session("computer delete the last word", .1)
        vv.executor.confirmer.assert_called_once()
        self.assertEqual(vv._last_inserted, "Meet Tuesday. ")
        self.assertEqual(vv.inserter.keyboard.events, [])

    def test_lists_are_session_only_and_raw_is_literal(self):
        text = "bullet milk bullet eggs"
        inserter = Inserter({}, [])
        self.assertEqual(inserter.prepare(text, format_lists=True)[0], "- Milk.\n- Eggs.\n")
        self.assertNotIn("\n", inserter.prepare(text)[0])
        raw = Inserter({"raw_dictation": True}, [])
        self.assertEqual(raw.prepare(text, format_lists=True)[0], text)


if __name__ == "__main__":
    unittest.main()
