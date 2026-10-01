"""Audible cues and an optional tray icon, so you know the app's state."""

from __future__ import annotations

import logging
import sys
import threading

log = logging.getLogger(__name__)

_IDLE = (90, 90, 96)
_LISTENING = (220, 60, 60)
_BUSY = (230, 170, 40)


class Beeper:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and sys.platform == "win32"

    def _beep(self, freq: int, ms: int) -> None:
        if not self.enabled:
            return

        def run() -> None:
            try:
                import winsound

                winsound.Beep(freq, ms)
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    def done(self) -> None:
        self._beep(1320, 55)

    def empty(self) -> None:
        self._beep(500, 70)

    def error(self) -> None:
        self._beep(300, 160)

    def _sequence(self, tones: list[tuple[int, int]]) -> None:
        if not self.enabled:
            return

        def run() -> None:
            try:
                import winsound

                for freq, ms in tones:
                    winsound.Beep(freq, ms)
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    def listen_start(self) -> None:
        self._sequence([(700, 55), (1050, 70)])

    def listen_end(self) -> None:
        self._sequence([(1050, 55), (700, 70)])


class Tray:
    """System tray indicator. Silently no-ops if pystray/Pillow are unavailable."""

    def __init__(self, enabled: bool, on_quit) -> None:  # noqa: ANN001
        self.icon = None
        self._on_quit = on_quit
        if not enabled:
            return
        try:
            import pystray
            from PIL import Image, ImageDraw

            self._pystray = pystray
            self._Image = Image
            self._ImageDraw = ImageDraw
            self.icon = pystray.Icon(
                "voicevibe",
                self._render(_IDLE),
                "Voice Vibe - idle",
                menu=pystray.Menu(pystray.MenuItem("Quit", self._quit)),
            )
        except Exception as exc:
            log.debug("tray unavailable: %s", exc)
            self.icon = None

    def _render(self, color):  # noqa: ANN001
        img = self._Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = self._ImageDraw.Draw(img)
        draw.ellipse((6, 6, 58, 58), fill=color + (255,))
        draw.rounded_rectangle((26, 18, 38, 40), radius=6, fill=(255, 255, 255, 235))
        draw.rectangle((30, 42, 34, 50), fill=(255, 255, 255, 235))
        draw.rectangle((24, 49, 40, 53), fill=(255, 255, 255, 235))
        return img

    def _quit(self) -> None:
        if self._on_quit:
            self._on_quit()

    def set_state(self, state: str) -> None:
        if self.icon is None:
            return
        color, tip = {
            "busy": (_BUSY, "Voice Vibe - transcribing"),
            "listening": (_LISTENING, "Voice Vibe - listening"),
        }.get(state, (_IDLE, "Voice Vibe - off (Ctrl+Alt+Space to listen)"))
        try:
            self.icon.icon = self._render(color)
            self.icon.title = tip
        except Exception:
            pass

    def run(self) -> None:
        if self.icon is not None:
            self.icon.run()

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
