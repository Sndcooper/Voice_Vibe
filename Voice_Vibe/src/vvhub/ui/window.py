"""`python -m vvhub.ui`: the control panel window (pywebview 6 on WebView2).

A separate, short-lived process: it exists only while the window is open
(~120 MB measured, CONV.md §8), then exits. It makes sure the hub runs, then
shows http://127.0.0.1:53874/ui/, which the hub serves. The page gets the
hub token through pywebview's JS bridge, and only while the window is on the
hub's own /ui/ page: a page the window navigated to gets nothing.
"""

from __future__ import annotations

import ctypes
import re
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .. import HOST, PORT
from . import launcher

TITLE = "Voice Vibe control panel"
URL = f"http://{HOST}:{PORT}/ui/"
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _our_page(url: Any) -> bool:
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return False
    return (parts.scheme == "http" and parts.hostname == HOST and parts.port == PORT
            and (parts.path == "/ui" or parts.path.startswith("/ui/")))


def _save_dialog(win: Any, name: str) -> str | None:
    import webview

    kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None)
    if kind is None:
        kind = webview.SAVE_DIALOG
    result = win.create_file_dialog(kind, save_filename=name)
    if not result:
        return None
    return result if isinstance(result, str) else result[0]


class JsApi:
    """Exposed to the page as window.pywebview.api (runs on pywebview's threads)."""

    def __init__(self, token_reader: Callable[[], str | None] = launcher.read_token,
                 dialog: Callable[[Any, str], str | None] = _save_dialog) -> None:
        self._token_reader = token_reader
        self._dialog = dialog
        self.window: Any = None

    def _trusted(self) -> bool:
        try:
            return self.window is not None and _our_page(self.window.get_current_url())
        except Exception:  # noqa: BLE001
            return False

    def token(self) -> str:
        return (self._token_reader() or "") if self._trusted() else ""

    def save_text(self, filename: str, text: str) -> str | None:
        if not self._trusted():
            return None
        name = _BAD_CHARS.sub("-", str(filename or "")).strip(" .")[:120] or "voicevibe-export.txt"
        path = self._dialog(self.window, name)
        if not path:
            return None
        Path(path).write_text(str(text), encoding="utf-8")
        return str(path)


def _find(title: str) -> int:
    return int(ctypes.windll.user32.FindWindowW(None, title) or 0)


def _show(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)


def focus_existing(find: Callable[[str], int] = _find, show: Callable[[int], None] = _show) -> bool:
    hwnd = find(TITLE)
    if hwnd:
        show(hwnd)
        return True
    return False


def _start(url: str, api: JsApi) -> None:
    import webview

    win = webview.create_window(TITLE, url, js_api=api, width=1180, height=800, min_size=(820, 560),
                                text_select=True)
    api.window = win
    webview.start(private_mode=True)


def main(argv: list[str] | None = None, *, focus: Callable[[], bool] = focus_existing,
         ensure: Callable[[], str] = lambda: launcher.ensure_hub(wait=12.0),
         start: Callable[[str, JsApi], None] = _start) -> int:
    if focus():
        return 0
    ensure()  # Voice Vibe's tray can open the panel before the hub is up
    start(URL, JsApi())
    return 0


if __name__ == "__main__":
    sys.exit(main())
