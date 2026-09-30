"""Spoken key presses and window closing, in any app (terminals included).

"press ctrl c", "hit down arrow on my keyboard", "escape", "close the terminal":
these must press keys, never be typed. The executor is a dry run; nothing is
sent to the real keyboard.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import stubs

stubs.install()

from voicevibe.actions import Executor, Keys  # noqa: E402
from voicevibe.control import Router, spoken_keys  # noqa: E402


def router() -> Router:
    ex = Executor(dry_run=True, desktop=SimpleNamespace(
        foreground=lambda: 1, process=lambda h: "windowsterminal.exe", windows=lambda: []))
    r = Router({"enabled": True}, executor=ex, finder=Mock(), profiles={})
    r._front = lambda: 1
    return r


def pressed(text: str) -> list[str] | None:
    r = router()
    route = r.route(text)
    if not route.handled:
        return None
    return [s.spec for s in r.executor.performed if isinstance(s, Keys)]


class SpokenKeysTests(unittest.TestCase):
    def test_names(self) -> None:
        cases = {
            "ctrl c": "ctrl+c", "control c": "ctrl+c", "control shift t": "ctrl+shift+t",
            "down arrow": "down", "arrow down": "down", "the up arrow key": "up",
            "escape": "esc", "enter": "enter", "return": "enter", "backspace": "backspace",
            "alt f4": "alt+f4", "tab": "tab", "shift tab": "shift+tab", "space": "space",
            "page down": "page_down", "f5": "f5", "y": "y", "ctrl plus c": "ctrl+c",
            "windows d": "win+d", "delete": "delete",
        }
        for spoken, keys in cases.items():
            self.assertEqual(spoken_keys(spoken), keys, spoken)

    def test_not_keys(self) -> None:
        for spoken in ("the release", "yes i trust this folder", "my team", "ctrl", "", "c c c"):
            self.assertIsNone(spoken_keys(spoken), spoken)


class RouteTests(unittest.TestCase):
    def test_press_phrases(self) -> None:
        cases = {
            "press ctrl c": ["ctrl+c"],
            "hit ctrl c on this terminal": ["ctrl+c"],
            "hit down arrow on my keyboard": ["down"],
            "down arrow": ["down"],
            "press the down arrow twice": ["down", "down"],
            "press escape": ["esc"],
            "hit tab three times": ["tab", "tab", "tab"],
            "press y": ["y"],
        }
        for text, keys in cases.items():
            self.assertEqual(pressed(text), keys, text)

    def test_close_window(self) -> None:
        for text in ("close the terminal", "close this window", "close the app", "close it"):
            self.assertEqual(pressed(text), ["alt+f4"], text)

    def test_close_current_tab_in_named_app(self) -> None:
        self.assertEqual(pressed("close the current tab on chrome"), ["ctrl+w"])

    def test_dictation_is_left_alone(self) -> None:
        for text in ("press release goes out tomorrow", "hit the gym later",
                     "select yes i trust this folder", "close the deal with the client"):
            self.assertIsNone(pressed(text), text)


class AICliCommandTests(unittest.TestCase):
    """With Claude/Kiro in front, commands act; everything else is the prompt.

    Replays the 22:13 session where "Down arrow", "Hit ctrl c on this
    terminal" and "Close the terminal" were typed into Claude as prompts.
    """

    def setUp(self) -> None:
        import test_terminal_front as ttf

        self.flow = ttf.TerminalFlowTests()

    def keys(self, vv) -> list:  # noqa: ANN001
        # By name: test_devices reloads voicevibe.*, so class identity differs.
        return [s.spec for s in vv.executor.performed if type(s).__name__ == "Keys"]

    def test_commands_press_keys_not_typed(self) -> None:
        cases = {"Down arrow.": ["down"], "Hit down arrow on my keyboard.": ["down"],
                 "Hit ctrl c on this terminal.": ["ctrl+c"], "Close the terminal.": ["alt+f4"]}
        for said, keys in cases.items():
            with self.subTest(said=said):
                vv = self.flow.make(ai="claude")
                vv.executor.dry_run = True
                self.flow.say(vv, said)
                self.assertEqual(self.keys(vv), keys)
                self.assertEqual(self.flow.typed(vv), "")

    def test_prompts_are_still_typed(self) -> None:
        for said in ("Fix the login bug in app.py.", "Focus on the parser and add tests."):
            with self.subTest(said=said):
                vv = self.flow.make(ai="kiro")
                vv.router.finder.elements = Mock(return_value=[])
                vv.executor.desktop.windows = lambda: []
                self.flow.say(vv, said)
                self.assertIn(said.rstrip("."), self.flow.typed(vv))


class ThinkingStateTests(unittest.TestCase):
    """Ctrl+Alt+W sessions show "Thinking"; plain dictation "Transcribing"."""

    def vv(self, recording: bool, state: str):  # noqa: ANN201
        from voicevibe import app

        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.session = Mock(is_recording=recording)
        vv._wake_state = state
        vv.wake_enabled = True
        vv.config = Mock(airoot={})
        return vv, app

    def test_control_session_thinks(self) -> None:
        from voicevibe import app

        vv, app = self.vv(True, app.DICTATING)
        self.assertEqual(vv._airoot_state("busy"), "thinking")

    def test_dictation_transcribes(self) -> None:
        from voicevibe import app

        vv, app = self.vv(False, app.ARMED)
        self.assertEqual(vv._airoot_state("busy"), "busy")

    def test_bridge_sends_thinking(self) -> None:
        from voicevibe.airoot import AirootBridge

        bridge = AirootBridge({"enabled": False})
        self.assertEqual(bridge._command_for("thinking"), "thinking")
        self.assertEqual(bridge._command_for("busy"), "transcribing")


if __name__ == "__main__":
    unittest.main()
