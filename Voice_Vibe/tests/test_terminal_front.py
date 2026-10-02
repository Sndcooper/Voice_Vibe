"""A terminal in front: AI CLI -> prompt typed; plain shell -> real commands.

All fakes: no window, process tree, hub or keyboard is real.
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import stubs

stubs.install()

import test_wake_request as twr  # noqa: E402

from voicevibe import app  # noqa: E402
from voicevibe.terminal import Terminal, detect  # noqa: E402


class DetectTests(unittest.TestCase):
    def d(self, title, process="WindowsTerminal.exe", remembered="", tree=()):  # noqa: ANN001, ANN201
        return detect(7, title, process, remembered=remembered, pid=9,
                      descendants=lambda pid: list(tree))

    def test_not_a_terminal(self) -> None:
        self.assertIsNone(self.d("Untitled - Notepad", "notepad.exe"))
        self.assertIsNone(detect(None, "Command Prompt", "cmd.exe"))

    def test_plain_shells(self) -> None:
        self.assertEqual((self.d("Command Prompt").shell, self.d("Command Prompt").ai), ("cmd", ""))
        self.assertEqual(self.d("Windows PowerShell").shell, "powershell")
        self.assertEqual(self.d(r"C:\WINDOWS\system32\cmd.exe").ai, "")

    def test_ai_cli_by_title(self) -> None:
        self.assertEqual(self.d("Command Prompt - claude").ai, "claude")
        self.assertEqual(self.d("kiro: Read C:\\Users\\vilas\\TASK.md").ai, "kiro")
        self.assertEqual(self.d("\u25d0 working on it").ai, "ai")

    def test_ai_cli_by_process_tree_outside_windows_terminal(self) -> None:
        self.assertEqual(self.d("Command Prompt", "cmd.exe", tree=[("claude.exe", "")]).ai, "claude")
        node = [("node.exe", r"node c:\npm\node_modules\@openai\codex\bin\codex.js")]
        self.assertEqual(self.d("x", "cmd.exe", tree=node).ai, "codex")
        # Windows Terminal hosts every window: its tree is not evidence.
        self.assertEqual(self.d("Command Prompt", tree=[("claude.exe", "")]).ai, "")

    def test_remembered_cli_until_the_title_is_plain_again(self) -> None:
        self.assertEqual(self.d("\u2733 Claude Code", remembered="claude").ai, "claude")
        self.assertEqual(self.d("some task title", remembered="claude").ai, "claude")
        self.assertEqual(self.d("Command Prompt", remembered="claude").ai, "")


class TerminalFlowTests(unittest.TestCase):
    make_base = twr.ImplicitRequestTests.make
    typed = twr.ImplicitRequestTests.typed
    enters = twr.ImplicitRequestTests.enters

    def make(self, ai: str = "", shell: str = "cmd", reply=None, connected=True):  # noqa: ANN001, ANN201
        vv = self.make_base()
        vv.config.control["session_mode"] = "control"
        vv._wake_state = app.DICTATING
        term = Terminal(hwnd=5, title="Command Prompt", process="windowsterminal.exe",
                        shell=shell, ai=ai)
        vv._front_terminal = lambda: term
        vv.hub = Mock(connected=connected)
        vv.hub.request.return_value = reply
        vv.router.route = Mock(wraps=vv.router.route)
        return vv

    def say(self, vv, text: str) -> None:  # noqa: ANN001
        with patch.object(app, "focused_window", return_value="Command Prompt"), \
                patch.object(app, "foreground", return_value=5):
            vv._do_session(text, 0.1)

    def test_shell_request_goes_to_the_terminal_skill(self) -> None:
        vv = self.make(reply={"type": "reply", "handled": True, "ok": True, "speak": True,
                              "text": "Show the contents of the current directory.",
                              "data": {"command": "dir", "ran": True}})
        self.say(vv, "List the files.")
        text, context = vv.hub.request.call_args.args
        self.assertEqual(text, "List the files.")
        self.assertEqual(context["terminal"]["shell"], "cmd")
        self.assertEqual(self.typed(vv), "")  # the hub typed the command, not us
        vv.voice.say.assert_called_once()

    def test_no_command_is_said_never_typed(self) -> None:
        vv = self.make(reply={"type": "reply", "handled": False, "text": "", "ok": False})
        self.say(vv, "I like pizza a lot.")
        self.assertEqual(self.typed(vv), "")
        self.assertIn("I don't know a command", vv.voice.say.call_args.args[0])

    def test_hub_slow_types_nothing(self) -> None:
        vv = self.make(reply=None)
        self.say(vv, "List the files.")
        self.assertEqual(self.typed(vv), "")

    def test_type_is_literal_and_raw_in_a_shell(self) -> None:
        vv = self.make()
        self.say(vv, "Type git status, press enter.")
        self.assertEqual(self.typed(vv), "git status")  # no capital, no period
        self.assertEqual(self.enters(vv), 1)
        vv.hub.request.assert_not_called()

    def test_hub_off_types_the_command_without_running_it(self) -> None:
        vv = self.make(connected=False)
        self.say(vv, "Git status.")
        self.assertEqual(self.typed(vv), "git status")
        self.assertEqual(self.enters(vv), 0)

    def test_window_verbs_still_work_in_a_shell(self) -> None:
        vv = self.make()
        vv.router.route = Mock(return_value=Mock(handled=True, caption="", speak="",
                                                 ends_dictation=False))
        self.say(vv, "Switch to chrome.")
        vv.router.route.assert_called_once_with("Switch to chrome.")
        vv.hub.request.assert_not_called()

    def test_ai_cli_gets_the_words_as_a_prompt(self) -> None:
        vv = self.make(ai="claude")
        self.say(vv, "Fix the login bug in app.py, press enter.")
        self.assertIn("Fix the login bug in app.py", self.typed(vv))
        self.assertEqual(self.enters(vv), 1)
        vv.hub.request.assert_not_called()

    def test_starting_an_ai_cli_is_remembered(self) -> None:
        vv = self.make(reply={"type": "reply", "handled": True, "ok": True, "speak": False,
                              "text": "claude", "data": {"command": "claude", "ran": True}})
        self.say(vv, "Claude.")
        self.assertEqual(vv._ai_windows(), {5: "claude"})
        vv = self.make()
        self.say(vv, "Type claude, press enter.")
        self.assertEqual(vv._ai_windows(), {5: "claude"})


class LaunchFirstTests(unittest.TestCase):
    make_base = twr.ImplicitRequestTests.make

    def test_known_app_beats_the_router(self) -> None:
        # 18:49: Explorer's "open {name}" rule swallowed "Open terminal".
        vv = self.make_base()
        vv.config.control["session_mode"] = "control"
        vv._front_terminal = lambda: None
        vv.router.route = Mock(return_value=Mock(handled=True, caption="", speak="",
                                                 ends_dictation=False))
        with patch.object(app, "focused_window", return_value="File Explorer"), \
                patch.object(app, "foreground", side_effect=[1, 2, 2, 2]):
            vv._do_session("Hey computer, open terminal.", 0.1)
        vv.responder.launcher.launch.assert_called_once()
        vv.router.route.assert_not_called()

    def test_unknown_name_still_reaches_the_router(self) -> None:
        vv = self.make_base()
        vv._front_terminal = lambda: None
        vv.router.route = Mock(return_value=Mock(handled=True, caption="", speak="",
                                                 ends_dictation=False))
        with patch.object(app, "focused_window", return_value="File Explorer"), \
                patch.object(app, "foreground", return_value=1):
            vv._do_session("Hey computer, open budget report.", 0.1)
        vv.responder.launcher.launch.assert_not_called()
        vv.router.route.assert_called_once()


if __name__ == "__main__":
    unittest.main()
