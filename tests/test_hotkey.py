"""Hotkey binding overlap.

f9 (dictate) and shift+f9 (speak) share a key, so which one fires depends on the
order keys go down. Getting this wrong starts two recordings from one gesture.
"""

from __future__ import annotations

import unittest

import stubs

stubs.install()

from voicevibe.hotkey import HotkeyListener, parse_hotkey  # noqa: E402
from stubs import FakeKey  # noqa: E402


class TestParseHotkey(unittest.TestCase):
    def test_splits_and_lowercases(self) -> None:
        self.assertEqual(parse_hotkey("Ctrl+Shift+F12"), frozenset({"ctrl", "shift", "f12"}))

    def test_applies_aliases(self) -> None:
        self.assertEqual(parse_hotkey("control+return"), frozenset({"ctrl", "enter"}))
        self.assertEqual(parse_hotkey("win+escape"), frozenset({"cmd", "esc"}))

    def test_collapses_sided_modifiers(self) -> None:
        self.assertEqual(parse_hotkey("ctrl_r+f9"), frozenset({"ctrl", "f9"}))

    def test_empty_spec_is_empty(self) -> None:
        self.assertEqual(parse_hotkey(""), frozenset())
        self.assertEqual(parse_hotkey("  +  "), frozenset())


class TestBindingOverlap(unittest.TestCase):
    """Mirrors the real [hotkeys] defaults: f9 and shift+f9."""

    def setUp(self) -> None:
        self.fired: list[str] = []
        self.listener = HotkeyListener()
        self.listener.bind("shift+f9", on_activate=lambda: self.fired.append("speak"))
        self.listener.bind("f9", on_activate=lambda: self.fired.append("dictate"))

    def press(self, *names: str) -> None:
        for name in names:
            self.listener._on_press(FakeKey(name))  # noqa: SLF001

    def release(self, *names: str) -> None:
        for name in names:
            self.listener._on_release(FakeKey(name))  # noqa: SLF001

    def test_plain_key_fires_only_its_own_binding(self) -> None:
        self.press("f9")
        self.assertEqual(self.fired, ["dictate"])

    def test_modifier_first_fires_only_the_specific_binding(self) -> None:
        self.press("shift", "f9")
        self.assertEqual(self.fired, ["speak"])

    def test_adding_modifier_mid_hold_does_not_fire_a_second_action(self) -> None:
        # Tap f9 (dictation starts), then happen to press shift while it is
        # still held. shift+f9 becomes satisfied, but speak must not start.
        self.press("f9")
        self.press("shift")
        self.assertEqual(self.fired, ["dictate"])

    def test_auto_repeat_does_not_refire(self) -> None:
        self.press("f9", "f9", "f9")
        self.assertEqual(self.fired, ["dictate"])

    def test_rearms_after_full_release(self) -> None:
        self.press("f9")
        self.release("f9")
        self.press("f9")
        self.assertEqual(self.fired, ["dictate", "dictate"])

    def test_release_deactivates_and_allows_the_other_binding(self) -> None:
        self.press("f9")
        self.release("f9")
        self.press("shift", "f9")
        self.assertEqual(self.fired, ["dictate", "speak"])


class TestDefaultBindings(unittest.TestCase):
    """The shipped defaults: dictate and speak share ctrl+alt+space."""

    def setUp(self) -> None:
        from voicevibe.config import DEFAULTS

        keys = DEFAULTS["hotkeys"]
        self.fired: list[str] = []
        self.listener = HotkeyListener()
        self.listener.bind(keys["speak"], on_activate=lambda: self.fired.append("speak"))
        self.listener.bind(keys["dictate"], on_activate=lambda: self.fired.append("dictate"))

    def press(self, *names: str) -> None:
        for name in names:
            self.listener._on_press(FakeKey(name))  # noqa: SLF001

    def test_defaults_avoid_function_keys(self) -> None:
        from voicevibe.config import DEFAULTS

        for action, spec in DEFAULTS["hotkeys"].items():
            with self.subTest(action=action):
                self.assertFalse(
                    any(t.startswith("f") and t[1:].isdigit() for t in parse_hotkey(spec)),
                    f"{action} = {spec!r} depends on an F-key",
                )

    def test_dictate_combo(self) -> None:
        self.press("ctrl_l", "alt_l", "space")
        self.assertEqual(self.fired, ["dictate"])

    def test_speak_combo_does_not_also_dictate(self) -> None:
        self.press("ctrl_l", "alt_l", "shift", "space")
        self.assertEqual(self.fired, ["speak"])

    def test_modifier_order_does_not_matter(self) -> None:
        self.press("shift", "alt_l", "ctrl_l", "space")
        self.assertEqual(self.fired, ["speak"])


class TestHoldBindings(unittest.TestCase):
    def test_deactivate_fires_on_release(self) -> None:
        events: list[str] = []
        listener = HotkeyListener()
        listener.bind(
            "f8",
            on_activate=lambda: events.append("down"),
            on_deactivate=lambda: events.append("up"),
        )
        listener._on_press(FakeKey("f8"))  # noqa: SLF001
        listener._on_release(FakeKey("f8"))  # noqa: SLF001
        self.assertEqual(events, ["down", "up"])

    def test_empty_spec_binds_nothing(self) -> None:
        listener = HotkeyListener()
        self.assertIsNone(listener.bind("", on_activate=lambda: None))


if __name__ == "__main__":
    unittest.main()
