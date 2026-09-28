"""The global command set: editing, scrolling, tabs, windows, system.

Two properties matter more than any single command. Anything that is not
exactly a command stays dictation -- "copy that paragraph and paste it below"
is a sentence, not "copy". And nothing here touches the real machine: routers
run a dry-run executor, or live ones wired to recording fakes.
"""

from __future__ import annotations

import time
import unittest

import stubs

stubs.install()

from voicevibe.actions import (  # noqa: E402
    Cancelled,
    Confirm,
    Executor,
    Focus,
    Keys,
    Lock,
    Scroll,
    TypeText,
    Wait,
    Window,
)
from voicevibe.control import NOT_HANDLED, Repeater, Router  # noqa: E402
from voicevibe.winctl import match_window  # noqa: E402

try:
    from voicevibe import app
except Exception:  # numpy / sounddevice / PIL missing on a bare checkout
    app = None


CHROME = {"hwnd": 101, "title": "Inbox - Gmail - Google Chrome", "process_name": "chrome.exe", "z": 1}
CODE = {"hwnd": 102, "title": "control.py - Voice_Vibe - Visual Studio Code",
        "process_name": "Code.exe", "z": 0}
WORD = {"hwnd": 103, "title": "Report.docx - Word", "process_name": "WINWORD.EXE", "z": 2}
DOCS_TAB = {"hwnd": 104, "title": "Claude Code docs - Google Chrome",
            "process_name": "chrome.exe", "z": 3}


class FakeDesktop:
    def __init__(self, windows=(CHROME, CODE, WORD), front=102) -> None:  # noqa: ANN001
        self._windows = list(windows)
        self.front = front
        self.focused: list[int] = []
        self.shown: list[str] = []
        self.locked = 0

    def windows(self) -> list[dict]:
        return self._windows

    def foreground(self) -> int:
        return self.front

    def focus(self, hwnd: int) -> bool:
        self.focused.append(hwnd)
        return True

    def show(self, op: str) -> bool:
        self.shown.append(op)
        return True

    def lock(self) -> bool:
        self.locked += 1
        return True


def dry_router(commands=None, desktop=None) -> Router:  # noqa: ANN001
    executor = Executor(dry_run=True, desktop=desktop or FakeDesktop())
    return Router({"enabled": True}, executor=executor, commands=commands)


def steps_for(command: str, router: Router | None = None) -> list:
    r = router or dry_router()
    route = r.route(command)
    assert route.handled, f"{command!r} was not handled"
    return list(r.executor.performed)


K = Keys


class TestEditing(unittest.TestCase):
    def test_commands(self) -> None:
        for said, expected in (
            ("save", [K("ctrl+s")]),
            ("Save.", [K("ctrl+s")]),
            ("please save the file", [K("ctrl+s")]),
            ("save as Q3 Report", [K("ctrl+shift+s"), Wait(1.0), TypeText("Q3 Report")]),
            ("Save as.", [K("ctrl+shift+s")]),
            ("find", [K("ctrl+f")]),
            ("find the login handler", [K("ctrl+f"), Wait(0.3), TypeText("the login handler")]),
            ("find and replace", [K("ctrl+h")]),
            ("select all", [K("ctrl+a")]),
            ("copy that", [K("ctrl+c")]),
            ("cut", [K("ctrl+x")]),
            ("paste it", [K("ctrl+v")]),
            ("undo", [K("ctrl+z")]),
            ("redo that", [K("ctrl+y")]),
            ("bold", [K("ctrl+b")]),
            ("make it italic", [K("ctrl+i")]),
            ("italicize that", [K("ctrl+i")]),
            ("underline", [K("ctrl+u")]),
        ):
            with self.subTest(said=said):
                self.assertEqual(steps_for(said), expected)

    def test_save_as_keeps_the_name_as_spoken(self) -> None:
        # Enter is not pressed: the name was heard, not seen.
        steps = steps_for("Save as Budget 2026 Final.")
        self.assertEqual(steps[-1], TypeText("Budget 2026 Final"))
        self.assertNotIn(K("enter"), steps)

    def test_delete_line_asks_once(self) -> None:
        # "delete" is a trigger word: the whole command is confirmed, and its
        # delete key is not asked about a second time.
        self.assertEqual(steps_for("delete line"), [
            Confirm("delete line", "delete"), K("home"), K("shift+down"), K("delete"),
        ])


class TestScrolling(unittest.TestCase):
    def test_commands(self) -> None:
        for said, expected in (
            ("scroll down", [Scroll("down", 5)]),
            ("scroll up", [Scroll("up", 5)]),
            ("scroll down 3", [Scroll("down", 3)]),
            ("Scroll down, five.", [Scroll("down", 5)]),
            ("scroll left 2 times", [Scroll("left", 2)]),
            ("scroll right by ten", [Scroll("right", 10)]),
            ("page down", [K("page_down")]),
            ("page up", [K("page_up")]),
            ("go to the top", [K("ctrl+home")]),
            ("scroll to the bottom of the page", [K("ctrl+end")]),
            ("scroll down to the bottom", [K("ctrl+end")]),
            ("top of the document", [K("ctrl+home")]),
        ):
            with self.subTest(said=said):
                self.assertEqual(steps_for(said), expected)

    def test_scroll_amount_is_configurable(self) -> None:
        r = Router({"enabled": True, "scroll_amount": 2}, executor=Executor(dry_run=True))
        self.assertEqual(steps_for("scroll down", r), [Scroll("down", 2)])

    def test_scrolling_does_not_move_the_pointer(self) -> None:
        # The wheel goes to whatever is under the pointer, so it must stay put.
        mouse = stubs.FakeMouse()
        executor = Executor(keyboard=stubs.FakeController(), mouse=mouse, step_delay=0)
        Router({"enabled": True}, executor=executor).route("scroll down 3")
        self.assertEqual(mouse.events, [("scroll", 0, -3)])


class TestKeepScrolling(unittest.TestCase):
    def live(self, limit: float = 5.0) -> tuple[Router, stubs.FakeMouse]:
        mouse = stubs.FakeMouse()
        executor = Executor(keyboard=stubs.FakeController(), mouse=mouse, step_delay=0)
        r = Router({"enabled": True, "keep_scrolling_limit": limit}, executor=executor)
        r.repeater.interval = 0.005
        return r, mouse

    def wait_for(self, condition, seconds: float = 2.0) -> None:  # noqa: ANN001
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            time.sleep(0.005)

    def test_scrolls_until_stopped(self) -> None:
        r, mouse = self.live()
        route = r.route("keep scrolling")
        self.assertTrue(route.handled)
        self.wait_for(lambda: len(mouse.events) >= 3)
        self.assertTrue(r.repeater.running)
        self.assertTrue(r.route("stop").handled)
        self.assertFalse(r.repeater.running)
        count = len(mouse.events)
        time.sleep(0.05)
        self.assertEqual(len(mouse.events), count)
        self.assertTrue(all(e == ("scroll", 0, -1) for e in mouse.events))

    def test_direction(self) -> None:
        r, mouse = self.live()
        r.route("keep scrolling up")
        self.wait_for(lambda: mouse.events)
        r.stop()
        self.assertEqual(mouse.events[0], ("scroll", 0, 1))

    def test_stops_by_itself_at_the_limit(self) -> None:
        r, mouse = self.live(limit=0.03)
        r.route("keep scrolling")
        self.wait_for(lambda: not r.repeater.running)
        self.assertFalse(r.repeater.running)

    def test_any_other_command_stops_it(self) -> None:
        r, mouse = self.live()
        r.route("keep scrolling")
        self.wait_for(lambda: mouse.events)
        r.route("next tab")
        self.assertFalse(r.repeater.running)

    def test_bare_stop_counts_only_while_scrolling(self) -> None:
        r, _ = self.live()
        self.assertFalse(r.is_stop("stop"))
        r.route("keep scrolling")
        try:
            for said in ("stop", "Stop.", "stop scrolling", "computer, stop", "that's enough"):
                with self.subTest(said=said):
                    self.assertTrue(r.is_stop(said))
            for said in ("stop the build", "don't stop", "scroll down"):
                with self.subTest(said=said):
                    self.assertFalse(r.is_stop(said))
        finally:
            r.stop()

    def test_stop_with_nothing_running_is_harmless(self) -> None:
        r, mouse = self.live()
        self.assertTrue(r.route("stop").handled)
        self.assertEqual(mouse.events, [])

    def test_a_failing_repeat_ends_quietly(self) -> None:
        class Broken(stubs.FakeMouse):
            def scroll(self, dx: int, dy: int) -> None:
                raise RuntimeError("no wheel")

        executor = Executor(keyboard=stubs.FakeController(), mouse=Broken(), step_delay=0)
        repeater = Repeater(executor, interval=0.001)
        with self.assertLogs("voicevibe.control", level="ERROR"):
            repeater.start({"scroll": ["down", 1]})
            deadline = time.monotonic() + 2
            while repeater.running and time.monotonic() < deadline:
                time.sleep(0.005)
        self.assertFalse(repeater.running)


class TestTabs(unittest.TestCase):
    def test_commands(self) -> None:
        for said, expected in (
            ("new tab", [K("ctrl+t")]),
            ("open a new tab", [K("ctrl+t")]),
            ("close tab", [K("ctrl+w")]),
            ("close this tab", [K("ctrl+w")]),
            ("next tab", [K("ctrl+tab")]),
            ("previous tab", [K("ctrl+shift+tab")]),
            ("tab 3", [K("ctrl+3")]),
            ("go to tab two", [K("ctrl+2")]),
            ("Tab to.", [K("ctrl+2")]),
            ("switch to the third tab", [K("ctrl+3")]),
            ("eighth tab", [K("ctrl+8")]),
            ("last tab", [K("ctrl+9")]),
            ("reopen closed tab", [K("ctrl+shift+t")]),
            ("restore the last closed tab", [K("ctrl+shift+t")]),
            ("duplicate tab", [K("alt+d"), Wait(0.15), K("alt+enter")]),
        ):
            with self.subTest(said=said):
                self.assertEqual(steps_for(said), expected)

    def test_pin_is_answered_not_faked(self) -> None:
        r = dry_router()
        route = r.route("pin this tab")
        self.assertTrue(route.handled)
        self.assertIn("can't pin", route.speak)
        self.assertEqual(list(r.executor.performed), [])


class TestWindows(unittest.TestCase):
    def test_commands(self) -> None:
        for said, expected in (
            ("minimize", [Window("minimize")]),
            ("minimise this window", [Window("minimize")]),
            ("maximize the window", [Window("maximize")]),
            ("restore", [Window("restore")]),
            ("snap left", [K("win+left")]),
            ("snap window to the right", [K("win+right")]),
            ("move to the other monitor", [K("win+shift+right")]),
            ("move this window to the left screen", [K("win+shift+left")]),
            ("show desktop", [K("win+d")]),
            ("minimize everything", [K("win+d")]),
        ):
            with self.subTest(said=said):
                self.assertEqual(steps_for(said), expected)

    def test_window_steps_reach_the_desktop(self) -> None:
        desktop = FakeDesktop()
        executor = Executor(keyboard=stubs.FakeController(), mouse=stubs.FakeMouse(),
                            desktop=desktop, step_delay=0)
        r = Router({"enabled": True}, executor=executor)
        r.route("minimize")
        r.route("maximize")
        r.route("switch to word")
        self.assertEqual(desktop.shown, ["minimize", "maximize"])
        self.assertEqual(desktop.focused, [103])


class TestSwitching(unittest.TestCase):
    def test_switches_by_app_or_title(self) -> None:
        for said, hwnd in (
            ("switch to chrome", 101),
            ("switch to Google Chrome", 101),
            ("switch to gmail", 101),
            ("switch to word", 103),
            ("switch to the report.docx window", 103),
            ("change to visual studio code", 102),
            ("focus on word", 103),
            ("bring up chrome", 101),
        ):
            with self.subTest(said=said):
                steps = steps_for(said)
                self.assertEqual(len(steps), 1)
                self.assertIsInstance(steps[0], Focus)
                self.assertEqual(steps[0].hwnd, hwnd)

    def test_nothing_open_is_said_out_loud(self) -> None:
        r = dry_router()
        route = r.route("switch to photoshop")
        self.assertTrue(route.handled)
        self.assertEqual(route.speak, "I don't see photoshop open.")
        self.assertEqual(list(r.executor.performed), [])


class TestMatchWindow(unittest.TestCase):
    WINDOWS = [CHROME, CODE, WORD, DOCS_TAB]

    def test_exact_app_beats_a_title_that_mentions_it(self) -> None:
        # "Claude Code docs" contains "code"; Code.exe *is* code.
        self.assertIs(match_window("code", self.WINDOWS), CODE)

    def test_title_parts_are_names(self) -> None:
        self.assertIs(match_window("gmail", self.WINDOWS), CHROME)
        self.assertIs(match_window("voice vibe", self.WINDOWS), CODE)

    def test_prefers_a_window_not_already_in_front(self) -> None:
        # Both Chrome windows match "chrome" equally; the front one is not the
        # one you are asking to switch to.
        self.assertIs(match_window("chrome", self.WINDOWS, foreground=101), DOCS_TAB)

    def test_then_the_most_recently_used(self) -> None:
        self.assertIs(match_window("chrome", self.WINDOWS), CHROME)

    def test_nothing_close_is_none(self) -> None:
        for said in ("photoshop", "", "   ", "xyz"):
            with self.subTest(said=said):
                self.assertIsNone(match_window(said, self.WINDOWS))

    def test_a_similar_name_is_not_the_app(self) -> None:
        # Found live: "photoshop" scored 0.80 against Photos.exe.
        photos = {"hwnd": 105, "title": "jumping gaits.png", "process_name": "Photos.exe", "z": 0}
        self.assertIsNone(match_window("photoshop", [photos]))
        self.assertIs(match_window("photos", [photos]), photos)

    def test_edge_is_found_through_its_title(self) -> None:
        # msedge.exe alone is too far from "edge"; the title carries it,
        # zero-width space and all.
        edge = {"hwnd": 106, "title": "YouTube - Personal - Microsoft​ Edge",
                "process_name": "msedge.exe", "z": 0}
        self.assertIs(match_window("edge", [edge]), edge)

    def test_no_windows_is_none(self) -> None:
        self.assertIsNone(match_window("chrome", []))


class TestSystem(unittest.TestCase):
    def test_commands(self) -> None:
        for said, expected in (
            ("volume up", [K("volume_up")] * 5),
            ("volume down 2", [K("volume_down")] * 2),
            ("turn the volume up", [K("volume_up")] * 5),
            ("louder", [K("volume_up")] * 5),
            ("quieter", [K("volume_down")] * 5),
            ("mute", [K("mute")]),
            ("unmute", [K("mute")]),
            ("pause", [K("play_pause")]),
            ("play the music", [K("play_pause")]),
            ("next track", [K("next_track")]),
            ("skip this song", [K("next_track")]),
            ("previous song", [K("previous_track")]),
            ("take a screenshot", [K("win+shift+s")]),
            ("screen shot", [K("win+shift+s")]),
            ("clipboard history", [K("win+v")]),
            ("show the clipboard", [K("win+v")]),
        ):
            with self.subTest(said=said):
                self.assertEqual(steps_for(said), expected)

    def test_lock_is_always_confirmed(self) -> None:
        self.assertEqual(steps_for("lock the computer"),
                         [Confirm("Lock the computer?"), Lock()])

    def test_lock_runs_only_on_yes(self) -> None:
        for answer, locked in ((True, 1), (False, 0)):
            with self.subTest(answer=answer):
                desktop = FakeDesktop()
                executor = Executor(desktop=desktop, confirmer=lambda p, t: answer, step_delay=0)
                route = Router({"enabled": True}, executor=executor).route("lock")
                self.assertTrue(route.handled)
                self.assertEqual(desktop.locked, locked)
                if not answer:
                    self.assertEqual(route.caption, "Cancelled")

    def test_lock_without_a_way_to_ask_does_not_lock(self) -> None:
        desktop = FakeDesktop()
        executor = Executor(desktop=desktop, step_delay=0)
        with self.assertLogs("voicevibe.actions", level="WARNING"):
            Router({"enabled": True}, executor=executor).route("lock screen")
        self.assertEqual(desktop.locked, 0)


class TestNotCommands(unittest.TestCase):
    """Near misses are dictation: typed as heard, nothing sent."""

    def test_near_misses(self) -> None:
        r = dry_router()
        for said in (
            "",
            "copy that paragraph and paste it below",
            "open chrome",
            "save the world",
            "scroll down a bit",
            "scroll down 500",
            "tab banana",
            "tab 9",
            "volume up 100",
            "switch to",
            "delete everything",
            "the next tab over",
        ):
            with self.subTest(said=said):
                self.assertEqual(r.route(said), NOT_HANDLED)
        self.assertEqual(list(r.executor.performed), [])


class TestUserCommands(unittest.TestCase):
    """[[commands]] rows are commands too, and win over built-ins."""

    def test_a_row_replaces_the_built_in(self) -> None:
        r = dry_router(commands=[{"say": "delete line", "keys": "ctrl+shift+k"}])
        self.assertEqual(steps_for("Delete line.", r),
                         [Confirm("Delete line.", "delete"), K("ctrl+shift+k")])

    def test_a_row_adds_a_command(self) -> None:
        r = dry_router(commands=[{"say": "format document", "keys": "shift+alt+f",
                                  "ends_dictation": True}])
        route = r.route("format document")
        self.assertTrue(route.ends_dictation)
        self.assertEqual(list(r.executor.performed), [K("shift+alt+f")])

    def test_a_bad_row_is_ignored_with_a_warning(self) -> None:
        with self.assertLogs("voicevibe.control", level="WARNING"):
            r = dry_router(commands=[{"say": "boom", "keys": "ctrl+nope"}])
        self.assertEqual(r.route("boom"), NOT_HANDLED)


class TestCancellation(unittest.TestCase):
    def test_a_refused_command_is_handled_not_typed(self) -> None:
        keyboard = stubs.FakeController()
        executor = Executor(keyboard=keyboard, mouse=stubs.FakeMouse(),
                            confirmer=lambda p, t: False, step_delay=0)
        route = Router({"enabled": True}, executor=executor).route("delete line")
        self.assertEqual((route.handled, route.caption), (True, "Cancelled"))
        self.assertEqual(keyboard.events, [])

    def test_cancelled_is_not_raised_to_the_caller(self) -> None:
        executor = Executor(confirmer=lambda p, t: False)
        try:
            Router({"enabled": True}, executor=executor).route("lock")
        except Cancelled:  # pragma: no cover - the assertion is that this never runs
            self.fail("Cancelled escaped the router")


class _Quiet:
    def __getattr__(self, name: str):  # noqa: ANN204
        return lambda *a, **k: None


class FakeVoice:
    def __init__(self) -> None:
        self.said: list[str] = []

    def say(self, text: str, block: bool = False) -> bool:
        self.said.append(text)
        return True


@unittest.skipIf(app is None, "app.py needs numpy, sounddevice and pillow")
class TestAppWiring(unittest.TestCase):
    def make(self, router: Router):  # noqa: ANN201
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.router = router
        vv.wake_enabled = True
        vv._wake_state = app.DICTATING
        vv.wake_matcher = stubs_matcher(["hey computer"])
        vv.sleep_matcher = stubs_matcher(["never mind"])
        vv._last_activity = 0.0
        vv._ends_dictation = False
        vv.beeper = vv.overlay = vv.history = _Quiet()
        vv.voice = FakeVoice()
        vv._arm = lambda reason: None
        vv.inserted = []
        vv._do_insert = lambda text, elapsed: vv.inserted.append(text)
        return vv

    def test_spoken_replies_are_said(self) -> None:
        vv = self.make(dry_router())
        vv._do_session("computer, switch to photoshop", 0.1)
        self.assertEqual(vv.voice.said, ["I don't see photoshop open."])
        self.assertEqual(vv.inserted, [])

    def test_bare_stop_works_even_after_re_arming(self) -> None:
        mouse = stubs.FakeMouse()
        executor = Executor(keyboard=stubs.FakeController(), mouse=mouse, step_delay=0)
        r = Router({"enabled": True}, executor=executor)
        vv = self.make(r)
        vv._do_session("computer keep scrolling", 0.1)
        self.assertTrue(r.repeater.running)
        # The watchdog re-armed the session while it scrolled.
        vv._wake_state = app.ARMED
        vv._do_session("Stop.", 0.1)
        self.assertFalse(r.repeater.running)
        self.assertEqual(vv.inserted, [])

    def test_stop_is_dictation_when_nothing_repeats(self) -> None:
        vv = self.make(dry_router())
        vv._do_session("stop", 0.1)
        self.assertEqual(vv.inserted, ["stop"])


def stubs_matcher(phrases: list[str]):  # noqa: ANN201
    from voicevibe.wake import PhraseMatcher

    return PhraseMatcher(phrases)


if __name__ == "__main__":
    unittest.main()
