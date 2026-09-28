"""Per-app profiles: the same words mean different things in different apps.

What matters: the front app's profile wins, a missing on-screen target is
said rather than guessed, trigger words still apply (to the phrase, not the
words filled into it), and Zen's shortcuts come from Zen's own settings.
Nothing touches a real window or file outside a temp directory.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import stubs

stubs.install()

from voicevibe import profiles as profiles_mod  # noqa: E402
from voicevibe.actions import Confirm, Executor, Keys, Say, TypeText, Wait  # noqa: E402
from voicevibe.config import load_config  # noqa: E402
from voicevibe.control import NOT_HANDLED, Router  # noqa: E402
from voicevibe.inserter import Key  # noqa: E402
from voicevibe.profiles import (  # noqa: E402
    build_commands,
    compile_phrase,
    fill,
    load_profiles,
    zen_combo,
    zen_table,
)
from voicevibe.screen import OcrLine, OcrResult, OcrWord  # noqa: E402
from voicevibe.uia import Element  # noqa: E402

HWND = 700


class Live(Element):
    """An element whose patterns work, recording what was done to it."""

    def __init__(self, name: str, kind: str = "Button", rect=(0, 0, 40, 20)) -> None:  # noqa: ANN001
        super().__init__(name, kind, rect)
        self.done: list[str] = []

    def invoke(self) -> bool:
        self.done.append("invoke")
        return True

    def select(self) -> bool:
        self.done.append("select")
        return True

    def focus(self) -> bool:
        self.done.append("focus")
        return True


class Screen:
    """A fake finder whose contents can change as steps run (menus open)."""

    def __init__(self, *elements: Element, lines=()) -> None:  # noqa: ANN001
        self.items = list(elements)
        self.lines = tuple(lines)
        self.on_invoke: dict[str, list[Element]] = {}

    def new_command(self) -> None:
        pass

    def elements(self, hwnd, types=None, popups=False):  # noqa: ANN001, ANN201
        return [e for e in self.items if not types or e.control_type in types]

    def text(self, hwnd):  # noqa: ANN001, ANN201
        return OcrResult(self.lines)


class FakeDesktop:
    def __init__(self, process: str) -> None:
        self.app = process

    def foreground(self) -> int:
        return HWND

    def process(self, hwnd) -> str:  # noqa: ANN001
        return self.app


def router(process: str, screen: Screen | None = None, profiles=None, confirmer=None,
           dry_run: bool = False, **cfg):  # noqa: ANN001, ANN003, ANN201
    said: list[str] = []
    executor = Executor(dry_run=dry_run, keyboard=stubs.FakeController(), mouse=stubs.FakeMouse(),
                        desktop=FakeDesktop(process), confirmer=confirmer, step_delay=0,
                        type_delay=0, say=said.append)
    r = Router({"enabled": True, **cfg}, executor=executor, finder=screen or Screen(),
               profiles=profiles)
    return r, said


def pressed(r: Router) -> list:
    """Main keys and typed text sent, without modifier bookkeeping."""
    out = []
    for kind, value in r.executor.keyboard.events:
        if kind == "type":
            out.append(value)
        elif kind == "press" and not str(value).startswith("Key.") and value not in ("",):
            out.append(value)
    return out


# ----------------------------------------------------------------- templates
class TestTemplates(unittest.TestCase):
    def test_placeholders_and_alternatives(self) -> None:
        patterns, literal = compile_phrase("new folder called {name}|new folder named {name}")
        self.assertEqual(literal, "new folder called")
        m = patterns[1].fullmatch("New folder named Q3 Reports")
        self.assertEqual(m["name"], "Q3 Reports")
        self.assertIsNone(patterns[0].fullmatch("new folder"))

    def test_fill_reaches_nested_strings_only(self) -> None:
        spec = [{"type_text": "{name}"}, {"click_named": {"name": "{name}", "pick": "last"}},
                {"wait": 0.5}]
        self.assertEqual(fill(spec, {"name": "Budget"}), [
            {"type_text": "Budget"}, {"click_named": {"name": "Budget", "pick": "last"}},
            {"wait": 0.5},
        ])

    def test_unknown_placeholders_are_left_alone(self) -> None:
        self.assertEqual(fill("{other}", {"name": "x"}), "{other}")

    def test_bad_rows_are_dropped_with_a_warning(self) -> None:
        with self.assertLogs("voicevibe.profiles", level="WARNING"):
            commands = build_commands({"good": {"keys": "ctrl+s"}, "bad": {"keys": "ctrl+nope"}},
                                      "test")
        self.assertEqual([c.phrase for c in commands], ["good"])


# ------------------------------------------------------------------------ Zen
def zen_entry(shortcut_id: str, key: str = "", keycode=None, disabled=False, **mods):  # noqa: ANN001, ANN003, ANN201
    base = {"control": False, "alt": False, "shift": False, "meta": False, "accel": False}
    return {"id": shortcut_id, "key": key, "keycode": keycode, "group": "zen-other",
            "modifiers": {**base, **mods}, "disabled": disabled}


class TestZen(unittest.TestCase):
    def test_combo_from_the_real_format(self) -> None:
        for entry, combo in (
            (zen_entry("a", "s", accel=True), "ctrl+s"),
            (zen_entry("a", "", "VK_RIGHT", accel=True, alt=True), "ctrl+alt+right"),
            (zen_entry("a", "C", accel=True, shift=True), "ctrl+shift+c"),
            (zen_entry("a", "*", accel=True, shift=True), "ctrl+shift+*"),
            (zen_entry("a", "k", meta=True), "win+k"),
            (zen_entry("a"), None),                       # unbound
            (zen_entry("a", "s", disabled=True, accel=True), None),
            (zen_entry("a", "", "VK_WEIRD", accel=True), None),
        ):
            with self.subTest(entry=entry):
                self.assertEqual(zen_combo(entry), combo)

    def write(self, directory: str, entries: list[dict]) -> Path:
        path = Path(directory) / "zen-keyboard-shortcuts.json"
        path.write_text(json.dumps({"shortcuts": entries}), encoding="utf-8")
        return path

    def test_table_uses_the_users_keys(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, [
                zen_entry("zen-workspace-forward", "", "VK_RIGHT", accel=True, alt=True),
                zen_entry("zen-toggle-pin-tab", "d", accel=True, shift=True),
                zen_entry("zen-toggle-sidebar"),  # unbound
            ])
            table = zen_table(path)
        self.assertEqual(table["next workspace"], {"keys": "ctrl+alt+right"})
        self.assertEqual(table["pin tab|pin this tab|unpin tab|unpin this tab"],
                         {"keys": "ctrl+shift+d"})
        # Unbound or absent: the phrase answers instead of being typed.
        self.assertEqual(table["toggle sidebar|hide sidebar"],
                         {"say": "toggle sidebar has no shortcut set in Zen."})
        self.assertIn("say", table["compact mode|toggle compact mode"])
        self.assertEqual(table["go back|back"], {"keys": "alt+left"})

    def test_no_file_means_fixed_keys_only(self) -> None:
        table = zen_table(None)
        self.assertEqual(table["reload|refresh|reload the page"], {"keys": "ctrl+r"})
        self.assertIn("say", table["next workspace"])

    def test_the_profile_rereads_a_changed_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, [zen_entry("zen-compact-mode-toggle", "s", accel=True)])
            with mock.patch.object(profiles_mod, "zen_shortcut_file", return_value=path):
                r, _ = router("zen.exe")
                r.route("compact mode")
                self.write(d, [zen_entry("zen-compact-mode-toggle", "j", accel=True, alt=True)])
                later = time.time() + 5
                os.utime(path, (later, later))
                r.route("compact mode")
        self.assertEqual(pressed(r), ["s", "j"])

    def test_pin_tab_means_pin_in_zen(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, [zen_entry("zen-toggle-pin-tab", "d", accel=True, shift=True)])
            with mock.patch.object(profiles_mod, "zen_shortcut_file", return_value=path):
                zen, _ = router("zen.exe")
                self.assertTrue(zen.route("pin this tab").handled)
        self.assertEqual(pressed(zen), ["d"])
        # Anywhere else it is still the global answer.
        other, _ = router("notepad.exe")
        self.assertIn("can't pin", other.route("pin this tab").speak)


# -------------------------------------------------------------- File Explorer
class TestExplorer(unittest.TestCase):
    def test_known_folders_go_through_the_address_bar(self) -> None:
        r, _ = router("explorer.exe", dry_run=True)
        r.route("go to downloads")
        self.assertEqual(list(r.executor.performed), [
            Keys("alt+d"), Wait(0.2), TypeText("shell:Downloads"), Keys("enter"),
        ])

    def test_navigation_keys(self) -> None:
        for said, combo in (("go up", "alt+up"), ("back", "alt+left"), ("go forward", "alt+right"),
                            ("copy path", "ctrl+shift+c"), ("new folder", "ctrl+shift+n")):
            with self.subTest(said=said):
                r, _ = router("explorer.exe", dry_run=True)
                r.route(said)
                self.assertEqual(list(r.executor.performed), [Keys(combo)])

    def test_new_folder_and_rename_type_the_name_as_said(self) -> None:
        r, _ = router("explorer.exe", dry_run=True)
        r.route("New folder called Q3 Reports")
        self.assertIn(TypeText("Q3 Reports"), r.executor.performed)
        r.executor.performed.clear()
        r.route("rename it to final draft")
        self.assertEqual(list(r.executor.performed),
                         [Keys("f2"), Wait(0.3), TypeText("final draft"), Keys("enter")])

    def test_delete_selects_first_and_always_asks(self) -> None:
        report = Live("Report", "ListItem")
        asked: list[str] = []
        r, _ = router("explorer.exe", Screen(report, Live("Notes", "ListItem")),
                      confirmer=lambda prompt, t: asked.append(prompt) or True)
        r.route("delete report")
        self.assertEqual(asked, ["delete"])
        self.assertEqual(report.done, ["select"])  # selected, not opened
        self.assertIn(("press", Key.delete), r.executor.keyboard.events)

    def test_delete_declined_touches_nothing(self) -> None:
        report = Live("Report", "ListItem")
        r, _ = router("explorer.exe", Screen(report), confirmer=lambda p, t: False)
        self.assertEqual(r.route("delete report").caption, "Cancelled")
        self.assertEqual(report.done, [])
        self.assertEqual(r.executor.keyboard.events, [])

    def test_delete_of_something_not_there_is_said(self) -> None:
        r, _ = router("explorer.exe", Screen(Live("Notes", "ListItem")),
                      confirmer=lambda p, t: True)
        route = r.route("delete budget")
        self.assertEqual(route.speak, "I can't find budget.")
        self.assertNotIn(("press", Key.delete), r.executor.keyboard.events)

    def test_sort_finds_the_menu_the_previous_step_opened(self) -> None:
        screen = Screen()
        date = Live("Date modified", "MenuItem")

        class Sort(Live):
            def invoke(self) -> bool:
                super().invoke()
                screen.items.append(date)  # the menu opens
                return True

        sort = Sort("Sort", "Button")
        screen.items.append(sort)
        r, _ = router("explorer.exe", screen)
        self.assertTrue(r.route("sort by date").handled)
        self.assertEqual((sort.done, date.done), (["invoke"], ["invoke"]))

    def test_open_double_clicks(self) -> None:
        r, _ = router("explorer.exe", Screen(Live("Budget", "ListItem", (100, 100, 200, 120))))
        r.route("open budget")
        self.assertEqual(r.executor.mouse.events[-1][0], "click")
        self.assertEqual(r.executor.mouse.events[-1][2], 2)


# ------------------------------------------------------------------ chat apps
class TestChat(unittest.TestCase):
    def test_ask_focuses_types_and_sends_without_asking(self) -> None:
        prompt = Live("Prompt", "Edit")
        asked: list[str] = []
        r, _ = router("claude.exe", Screen(prompt), confirmer=lambda p, t: asked.append(p) or True)
        r.route("ask how do I delete a git branch")
        self.assertEqual(prompt.done, ["focus"])
        self.assertIn("how do I delete a git branch", "".join(
            v for k, v in r.executor.keyboard.events if k == "type"))
        # "delete" was in the question, not the command: nothing to confirm.
        self.assertEqual(asked, [])

    def test_new_chat_opens_the_sidebar_when_it_has_to(self) -> None:
        screen = Screen()
        new_chat = Live("New chat")

        class Sidebar(Live):
            def invoke(self) -> bool:
                super().invoke()
                screen.items.append(new_chat)
                return True

        sidebar = Sidebar("Show sidebar")
        screen.items.append(sidebar)
        r, _ = router("claude.exe", screen)
        self.assertTrue(r.route("new chat").handled)
        self.assertEqual((sidebar.done, new_chat.done), (["invoke"], ["invoke"]))

    def test_copy_and_read_use_the_newest_answer(self) -> None:
        old = Live("Copy", rect=(0, 100, 20, 120))
        new = Live("Copy", rect=(0, 900, 20, 920))
        stubs.sys.modules["pyperclip"].copy("The answer is 42.")
        r, said = router("claude.exe", Screen(new, old))
        r.route("read the answer")
        self.assertEqual((old.done, new.done), ([], ["invoke"]))
        self.assertEqual(said, ["The answer is 42."])

    def test_scroll_to_latest_falls_back_to_scrolling(self) -> None:
        r, _ = router("claude.exe", Screen())
        self.assertTrue(r.route("scroll to latest").handled)
        self.assertEqual(r.executor.mouse.events, [("scroll", 0, -50)])

    def test_stop_generating_when_nothing_is_generating(self) -> None:
        r, _ = router("claude.exe", Screen())
        self.assertEqual(r.route("stop generating").speak, "I can't find Stop response.")

    def test_chatgpt_uses_its_shortcuts(self) -> None:
        r, _ = router("chatgpt.exe", dry_run=True)
        r.route("new chat")
        r.route("copy the last answer")
        self.assertEqual(list(r.executor.performed), [Keys("ctrl+shift+o"), Keys("ctrl+shift+c")])


# ------------------------------------------------------------- precedence
class TestPrecedence(unittest.TestCase):
    def test_profile_beats_global(self) -> None:
        # Global "scroll to the bottom" is ctrl+end; Claude's is its own button.
        bottom = Live("Scroll to bottom")
        r, _ = router("claude.exe", Screen(bottom))
        r.route("scroll to the bottom")
        self.assertEqual(bottom.done, ["invoke"])

    def test_other_apps_get_the_global_meaning(self) -> None:
        r, _ = router("notepad.exe", dry_run=True)
        r.route("scroll to the bottom")
        self.assertEqual(list(r.executor.performed), [Keys("ctrl+end")])

    def test_user_rows_extend_and_override(self) -> None:
        rows = [{"process": "explorer.exe", "commands": {
            "go up": {"keys": "backspace"},
            "open terminal here": {"keys": "ctrl+shift+2"},
        }}]
        r, _ = router("explorer.exe", profiles=rows, dry_run=True)
        r.route("go up")
        r.route("open terminal here")
        r.route("go back")  # untouched built-in still there
        self.assertEqual(list(r.executor.performed),
                         [Keys("backspace"), Keys("ctrl+shift+2"), Keys("alt+left")])

    def test_builtin_false_replaces_the_profile(self) -> None:
        rows = [{"process": "explorer.exe", "builtin": False,
                 "commands": {"go up": {"keys": "backspace"}}}]
        profiles = load_profiles(rows)
        self.assertEqual([c.phrase for c in profiles["explorer.exe"].commands], ["go up"])

    def test_a_new_app(self) -> None:
        rows = [{"process": "Code.exe", "commands": {"delete line": {"keys": "ctrl+shift+k"}}}]
        r, _ = router("code.exe", profiles=rows, dry_run=True)
        r.route("delete line")
        self.assertEqual(list(r.executor.performed),
                         [Confirm("delete line", "delete"), Keys("ctrl+shift+k")])


class TestImplicitClick(unittest.TestCase):
    def test_off_unless_configured(self) -> None:
        r, _ = router("notepad.exe", Screen(Live("Downloads")))
        self.assertEqual(r.route("downloads"), NOT_HANDLED)

    def test_exact_name_is_clicked(self) -> None:
        downloads = Live("Downloads")
        r, _ = router("notepad.exe", Screen(downloads), implicit_click=True)
        self.assertTrue(r.route("Downloads.").handled)
        self.assertEqual(downloads.done, ["invoke"])

    def test_a_near_name_is_dictation(self) -> None:
        # "click download" would find Downloads; a bare word must match outright.
        r, _ = router("notepad.exe", Screen(Live("Downloads")), implicit_click=True)
        self.assertEqual(r.route("download"), NOT_HANDLED)

    def test_ocr_only_when_asked(self) -> None:
        lines = (OcrLine("Sign in", (OcrWord("Sign", (0, 0, 20, 10)), OcrWord("in", (22, 0, 30, 10)))),)
        off, _ = router("notepad.exe", Screen(lines=lines), implicit_click=True)
        self.assertEqual(off.route("sign in"), NOT_HANDLED)
        on, _ = router("notepad.exe", Screen(lines=lines), implicit_click=True, implicit_ocr=True)
        self.assertTrue(on.route("sign in").handled)
        self.assertEqual(on.executor.mouse.events[-1][0], "click")


class TestConfigLoading(unittest.TestCase):
    def test_profiles_table(self) -> None:
        toml = (
            '[[profiles]]\nprocess = "Code.exe"\n[profiles.commands]\n'
            '"delete line" = { keys = "ctrl+shift+k" }\n'
            '"go to file {name}" = [{ keys = "ctrl+p" }, { type_text = "{name}" }]\n'
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            path.write_text(toml, encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config.profiles, [{
            "process": "code.exe", "builtin": True,
            "commands": {"delete line": {"keys": "ctrl+shift+k"},
                         "go to file {name}": [{"keys": "ctrl+p"}, {"type_text": "{name}"}]},
        }])
        self.assertTrue(config.control["implicit_click"])


if __name__ == "__main__":
    unittest.main()
