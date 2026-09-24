"""Global hotkey listener with hold-to-talk and toggle support.

Keys are normalised to lowercase string tokens before matching. On Windows a
letter key pressed together with Ctrl reports a control character rather than
the letter, so matching goes through the virtual-key code instead of `char`.
Left/right modifier variants collapse to a single token.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable

from pynput import keyboard

log = logging.getLogger(__name__)

_ALIASES = {
    "control": "ctrl",
    "ctl": "ctrl",
    "win": "cmd",
    "super": "cmd",
    "meta": "cmd",
    "option": "alt",
    "escape": "esc",
    "return": "enter",
    "spacebar": "space",
    "altgr": "alt_gr",
    "pgup": "page_up",
    "pgdn": "page_down",
}

_SIDED = ("ctrl", "shift", "alt", "cmd")


def _strip_side(name: str) -> str:
    for base in _SIDED:
        if name in (f"{base}_l", f"{base}_r"):
            return base
    return name


def normalize_key(key) -> str | None:  # noqa: ANN001
    """Turn a pynput key event into a stable lowercase token."""
    if isinstance(key, keyboard.Key):
        return _strip_side(key.name)

    if isinstance(key, keyboard.KeyCode):
        vk = key.vk
        if vk is not None:
            if 0x41 <= vk <= 0x5A:  # A-Z
                return chr(vk).lower()
            if 0x30 <= vk <= 0x39:  # 0-9
                return chr(vk)
            if 0x60 <= vk <= 0x69:  # numpad 0-9
                return f"num_{vk - 0x60}"
        if key.char:
            return key.char.lower()
    return None


def parse_hotkey(spec: str) -> frozenset[str]:
    tokens = set()
    for part in str(spec).split("+"):
        token = part.strip().lower()
        if not token:
            continue
        token = _ALIASES.get(token, token)
        tokens.add(_strip_side(token))
    return frozenset(tokens)


@dataclass
class Binding:
    keys: frozenset[str]
    on_activate: Callable[[], None] | None = None
    on_deactivate: Callable[[], None] | None = None
    active: bool = field(default=False, init=False)


class HotkeyListener:
    """Tracks held keys and dispatches binding activate/deactivate callbacks."""

    def __init__(self) -> None:
        self._bindings: list[Binding] = []
        self._held: set[str] = set()
        self._listener: keyboard.Listener | None = None

    def bind(
        self,
        spec: str,
        on_activate: Callable[[], None] | None = None,
        on_deactivate: Callable[[], None] | None = None,
    ) -> Binding | None:
        keys = parse_hotkey(spec)
        if not keys:
            return None
        binding = Binding(keys, on_activate, on_deactivate)
        self._bindings.append(binding)
        return binding

    def _fire(self, callback: Callable[[], None] | None) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception:
            log.exception("hotkey callback failed")

    def _on_press(self, key) -> None:  # noqa: ANN001
        token = normalize_key(key)
        if token is None:
            return
        self._held.add(token)

        satisfied = [b for b in self._bindings if b.keys <= self._held]
        for binding in satisfied:
            # `binding.active` makes key auto-repeat a no-op.
            if binding.active:
                continue
            # Prefer the most specific match. With "f9" and "shift+f9" both bound,
            # holding shift+f9 satisfies both, and plain f9 must stay quiet.
            if any(binding.keys < other.keys for other in satisfied):
                continue
            # Holding f9 (dictate already running) and *then* adding shift would
            # otherwise also satisfy shift+f9 and start speak on the same
            # gesture. A binding never fires on top of an active subset of itself.
            if any(other.active and other.keys < binding.keys for other in self._bindings):
                continue
            binding.active = True
            self._fire(binding.on_activate)

    def _on_release(self, key) -> None:  # noqa: ANN001
        token = normalize_key(key)
        if token is None:
            return
        self._held.discard(token)
        for binding in self._bindings:
            if binding.active and token in binding.keys:
                binding.active = False
                self._fire(binding.on_deactivate)

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def join(self) -> None:
        if self._listener is not None:
            self._listener.join()

    @staticmethod
    def describe(specs: Iterable[tuple[str, str]]) -> str:
        return "\n".join(f"  {label:<14} {spec}" for label, spec in specs if spec)
