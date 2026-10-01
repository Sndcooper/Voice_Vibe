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


class Inserter:
    def __init__(self, output_cfg: dict[str, Any]) -> None:
        self.cfg = output_cfg
        self.keyboard = Controller()

    def polish(self, text: str) -> str:
        """The text as it will be inserted: capitals, spacing, punctuation."""
        text = text.strip()
        if not text or self.cfg.get("raw_dictation", False):
            return text
        if self.cfg.get("polish", True):
            text = polish_text(text, terminate=True, spoken_marks=False)
        if self.cfg.get("lowercase"):
            text = text.lower()
        if self.cfg.get("strip_trailing_period") and text.endswith("."):
            text = text[:-1]
        if self.cfg.get("add_trailing_space", True) and not text.endswith((" ", "\n")):
            text += " "
        return text

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
        especially) lost, pasting the *previous* text, so the wait happens
        off-thread.
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

    def insert(self, text: str) -> str:
        """Polish `text` and put it at the cursor. Returns what was inserted."""
        body = self.polish(text)
        if not body:
            return ""
        mode = str(self.cfg.get("mode", "paste")).lower()
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
        return body
