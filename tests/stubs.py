"""Minimal stand-ins for the OS-input packages.

hotkey and inserter import pynput/pyperclip at module scope, but the logic worth
testing here (binding overlap, trailing-command extraction) touches neither the
keyboard nor the clipboard. Stubbing the imports keeps this suite runnable on a
bare checkout, which is the point of a stdlib-only test suite.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


class FakeKey:
    """Stands in for pynput.keyboard.Key. Only `.name` is read by normalize_key."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"Key.{self.name}"


class FakeKeyCode:
    def __init__(self, vk: int | None = None, char: str | None = None) -> None:
        self.vk = vk
        self.char = char


class FakeController:
    """Records what would have been sent instead of touching the real keyboard."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def press(self, key: object) -> None:
        self.events.append(("press", key))

    def release(self, key: object) -> None:
        self.events.append(("release", key))

    def tap(self, key: object) -> None:
        self.events.append(("tap", key))

    def type(self, text: str) -> None:
        self.events.append(("type", text))

    def pressed(self, *keys: object):  # noqa: ANN201
        controller = self

        class _Held:
            def __enter__(self) -> None:
                for key in keys:
                    controller.events.append(("press", key))

            def __exit__(self, *exc: object) -> None:
                for key in reversed(keys):
                    controller.events.append(("release", key))

        return _Held()


class FakeListener:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.daemon = False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def join(self) -> None:
        pass


def install() -> None:
    """Put the stubs on sys.modules and src on sys.path. Idempotent."""
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    if "pynput" not in sys.modules:
        keyboard = types.ModuleType("pynput.keyboard")
        # Every name in _MAIN_KEYS / _MODIFIERS is read as an attribute of Key.
        for name in (
            "ctrl", "ctrl_r", "shift", "shift_r", "alt", "alt_r", "alt_gr", "cmd",
            "enter", "tab", "esc", "space", "backspace", "delete", "up", "down",
            "left", "right", "home", "end", "page_up", "page_down", "insert",
            "caps_lock", "print_screen", "menu",
            "media_play_pause", "media_volume_up", "media_volume_down",
            "media_volume_mute", "media_next", "media_previous",
        ):
            setattr(FakeKey, name, FakeKey(name))
        for n in range(1, 13):
            setattr(FakeKey, f"f{n}", FakeKey(f"f{n}"))

        keyboard.Key = FakeKey
        keyboard.KeyCode = FakeKeyCode
        keyboard.Controller = FakeController
        keyboard.Listener = FakeListener

        pynput = types.ModuleType("pynput")
        pynput.keyboard = keyboard
        sys.modules["pynput"] = pynput
        sys.modules["pynput.keyboard"] = keyboard

    if "pyperclip" not in sys.modules:
        clipboard = types.ModuleType("pyperclip")
        clipboard._value = ""

        def copy(text: str) -> None:
            clipboard._value = text

        def paste() -> str:
            return clipboard._value

        clipboard.copy = copy
        clipboard.paste = paste
        sys.modules["pyperclip"] = clipboard
