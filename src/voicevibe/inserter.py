"""Put text into whatever field currently has focus.

Two strategies:
  paste - copy to clipboard, send Ctrl+V, restore the old clipboard. Fast and
          unicode-safe, which matters because Whisper emits smart quotes and em
          dashes. This is what every field accepts, including terminals.
  type  - synthesize keystrokes. Slower, but works in the rare app that blocks
          programmatic paste.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
import time
from typing import Any

import pyperclip
from pynput.keyboard import Controller, Key

from .polish import polish as polish_text

log = logging.getLogger(__name__)

# Modifiers we force-release before pasting. If a hotkey modifier is still held
# (physically or logically), Ctrl+V turns into Ctrl+Shift+V or worse.
_MODIFIERS = (Key.shift, Key.shift_r, Key.ctrl, Key.ctrl_r, Key.alt, Key.alt_r, Key.cmd)


def focused_window() -> str:
    """Title of the window that will receive the text. Windows only."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # An HWND is truncated on 64-bit without an explicit restype.
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        return title[:60] if title else ""
    except Exception:
        return ""


_TRAILING_PUNCTUATION = " \t\n.,!?;:\"')]}\u2019\u201d"

# Keys reachable from a voice command. Modifiers are held, the main key is tapped.
_MODIFIER_KEYS = {
    "ctrl": Key.ctrl,
    "control": Key.ctrl,
    "shift": Key.shift,
    "alt": Key.alt,
    "cmd": Key.cmd,
    "win": Key.cmd,
    "super": Key.cmd,
}

def _optional(name: str):  # noqa: ANN201
    """Some Key members are platform-specific; skip the ones this OS lacks."""
    return getattr(Key, name, None)


_MAIN_KEYS = {
    "enter": Key.enter,
    "return": Key.enter,
    "tab": Key.tab,
    "esc": Key.esc,
    "escape": Key.esc,
    "space": Key.space,
    "backspace": Key.backspace,
    "delete": Key.delete,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "home": Key.home,
    "end": Key.end,
    "page_up": Key.page_up,
    "page_down": Key.page_down,
    **{f"f{n}": getattr(Key, f"f{n}") for n in range(1, 13)},
}

# Added separately because pynput does not define all of these on every platform.
_MAIN_KEYS.update(
    {
        name: key
        for name, key in {
            "insert": _optional("insert"),
            "caps_lock": _optional("caps_lock"),
            "print_screen": _optional("print_screen"),
            "menu": _optional("menu"),
            "play_pause": _optional("media_play_pause"),
            "next_track": _optional("media_next"),
            "previous_track": _optional("media_previous"),
            "volume_up": _optional("media_volume_up"),
            "volume_down": _optional("media_volume_down"),
            "mute": _optional("media_volume_mute"),
        }.items()
        if key is not None
    }
)


def _resolve_keys(spec: str) -> tuple[list[Key], Key | str | None]:
    modifiers: list[Key] = []
    main: Key | str | None = None
    for part in str(spec).split("+"):
        token = part.strip().lower()
        if not token:
            continue
        if token in _MODIFIER_KEYS:
            modifiers.append(_MODIFIER_KEYS[token])
        elif token in _MAIN_KEYS:
            main = _MAIN_KEYS[token]
        elif len(token) == 1:
            main = token
    return modifiers, main


class Inserter:
    def __init__(
        self,
        output_cfg: dict[str, Any],
        replacements: list[dict[str, str]],
        commands: list[dict[str, str]] | None = None,
    ):
        self.cfg = output_cfg
        self.replacements = replacements
        self.commands = commands or []
        self.keyboard = Controller()

    def _normalize(self, text: str) -> str:
        # Keep dictated words literal; legacy replacement tables are ignored.
        return text.strip()

    def _finish(self, text: str, trailing_space: bool) -> str:
        if not text:
            return ""
        if self.cfg.get("polish", True):
            text = polish_text(text, terminate=trailing_space, spoken_marks=False)
        if self.cfg.get("lowercase"):
            text = text.lower()
        if self.cfg.get("strip_trailing_period") and text.endswith("."):
            text = text[:-1]
        if trailing_space and self.cfg.get("add_trailing_space", True):
            if not text.endswith((" ", "\n")):
                text += " "
        return text

    def polish(self, text: str) -> str:
        """Text only, no command handling. Used by the speak path."""
        if self.cfg.get("raw_dictation", False):
            return text.strip()
        return self._finish(self._normalize(text), trailing_space=True)

    def _extract_commands(self, text: str) -> tuple[str, list[dict[str, str]]]:
        """Only a separate utterance of 'press enter' may send a key."""
        if self.cfg.get("voice_commands", True) and re.fullmatch(
            r"press\s+enter[.!?]*", text.strip(), flags=re.IGNORECASE
        ):
            return "", [{"say": "press enter", "keys": "enter", "ends_dictation": True}]
        return text, []

    def prepare(self, text: str) -> tuple[str, list[dict[str, str]]]:
        """Split a transcript into text to insert and commands to fire after it."""
        if self.cfg.get("raw_dictation", False):
            return text.strip(), []
        normalized = self._normalize(text)
        remaining, commands = self._extract_commands(normalized)
        return self._finish(remaining, trailing_space=not commands), commands

    def press(self, spec: str) -> bool:
        """Send one key or combo, e.g. "enter" or "ctrl+enter"."""
        modifiers, main = _resolve_keys(spec)
        if main is None:
            log.warning("Unknown command key %r", spec)
            return False
        self._release_modifiers()
        for modifier in modifiers:
            self.keyboard.press(modifier)
        try:
            self.keyboard.press(main)
            self.keyboard.release(main)
        finally:
            for modifier in reversed(modifiers):
                self.keyboard.release(modifier)
        return True

    def _release_modifiers(self) -> None:
        for key in _MODIFIERS:
            try:
                self.keyboard.release(key)
            except Exception:
                pass

    def _paste(self, text: str) -> None:
        previous: str | None = None
        if self.cfg.get("restore_clipboard", True):
            try:
                previous = pyperclip.paste()
            except Exception:
                previous = None

        pyperclip.copy(text)
        # Give the target app a moment to observe the new clipboard contents.
        time.sleep(0.03)
        self._release_modifiers()
        with self.keyboard.pressed(Key.ctrl):
            self.keyboard.press("v")
            self.keyboard.release("v")

        if previous is not None:
            self._restore_clipboard(previous, text)

    def _restore_clipboard(self, previous: str, pasted: str) -> None:
        """Put the old clipboard back once the target has had time to read ours.

        Restoring inline was a race that slow apps (Electron chat boxes
        especially) lost, pasting the *previous* text. Waiting longer inline
        would instead delay the trailing Enter, so the wait happens off-thread.
        """
        delay = float(self.cfg.get("restore_delay", 0.5) or 0)

        def run() -> None:
            time.sleep(delay)
            try:
                # If the clipboard no longer holds what we put there, something
                # else claimed it in the meantime. Don't clobber that.
                if pyperclip.paste() != pasted:
                    return
                pyperclip.copy(previous)
            except Exception:
                pass

        threading.Thread(target=run, name="clipboard-restore", daemon=True).start()

    def _type(self, text: str) -> None:
        self._release_modifiers()
        delay = float(self.cfg.get("type_delay", 0.004) or 0)
        for char in text:
            if char == "\n":
                self.keyboard.tap(Key.enter)
            else:
                self.keyboard.type(char)
            if delay:
                time.sleep(delay)

    def erase(self, count: int) -> None:
        """Backspace over `count` characters already in the focused field."""
        if count <= 0:
            return
        self._release_modifiers()
        # Capped so a mishandled length cannot run away and eat a document.
        for _ in range(min(count, 2000)):
            self.keyboard.tap(Key.backspace)

    def insert_literal(self, text: str) -> None:
        """Put `text` in exactly as given, with no polishing or command parsing."""
        if not text:
            return
        mode = str(self.cfg.get("mode", "paste")).lower()
        try:
            if mode == "type":
                self._type(text)
            else:
                self._paste(text)
        except Exception as exc:
            log.error("Insertion failed (%s).", exc)

    def insert(self, text: str) -> tuple[str, list[dict[str, str]]]:
        """Insert the text, then fire any trailing voice commands.

        Returns (text inserted, commands actually fired).
        """
        body, commands = self.prepare(text)
        mode = str(self.cfg.get("mode", "paste")).lower()

        if body:
            try:
                if mode == "type":
                    self._type(body)
                else:
                    self._paste(body)
            except Exception as exc:
                log.error("Insertion failed (%s). Text is on your clipboard.", exc)
                try:
                    pyperclip.copy(body)
                except Exception:
                    pass
                return body, []

        fired: list[dict[str, str]] = []
        if commands:
            # Give the target app a moment to commit the paste before Enter,
            # otherwise a chat box can submit an empty message.
            time.sleep(float(self.cfg.get("command_delay", 0.12) or 0))
            for command in commands:
                try:
                    if self.press(command["keys"]):
                        fired.append(command)
                except Exception as exc:
                    log.error("Could not send %r: %s", command["keys"], exc)
        return body, fired
