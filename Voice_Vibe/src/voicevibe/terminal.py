"""Is a terminal in front, and is an AI CLI running in it?

A plain shell (cmd, PowerShell) gets real commands: the hub's terminal skill
turns "list the files" into `dir`. An AI CLI running in the terminal (Claude
Code, Codex, Kiro, Gemini...) gets what you say typed as a prompt, because
there the words are the input.

Detection is by window title (cmd shows "Command Prompt - claude" while
Claude runs; Kiro shows "kiro: ..."; CLIs working show a spinner glyph) and,
for a standalone console window, its own process tree. Windows Terminal hosts
every window in one process, so there the title is all there is; the app
also remembers an AI CLI it started itself in that window.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

TERMINAL_PROCESSES = frozenset({"windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
                                "conhost.exe", "openconsole.exe", "wezterm-gui.exe",
                                "alacritty.exe", "mintty.exe"})
AI_CLIS = frozenset({"claude", "codex", "gemini", "kiro-cli", "kiro", "aider", "ollama", "qwen",
                     "opencode", "copilot", "crush"})
_AI_TITLE = re.compile(r"(?i)\b(claude|codex|gemini|kiro|aider|copilot|ollama|qwen|opencode|crush)\b")
# Leading status glyphs AI CLIs put in the title while they work.
_SPINNERS = frozenset("\u2733\u2736\u273b\u273d\u2722\u00b7\u25d0\u25d3\u25d1\u25d2"
                      "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f")
_PLAIN = re.compile(r"(?i)^(?:administrator:\s*)?(?:command prompt|windows powershell|powershell"
                    r"|cmd(?:\.exe)?|.*\\(?:cmd|powershell|pwsh)\.exe)$")


@dataclass
class Terminal:
    hwnd: int
    title: str
    process: str
    shell: str          # "cmd" or "powershell"
    ai: str = ""        # "" = plain shell, else which CLI

    @property
    def plain(self) -> bool:
        return not self.ai


def _ai_in_title(title: str) -> str:
    match = _AI_TITLE.search(title)
    if match:
        return match.group(1).lower()
    stripped = title.lstrip()
    return "ai" if stripped[:1] in _SPINNERS else ""


def plain_title(title: str) -> bool:
    return bool(_PLAIN.match(title.strip()))


def _descendants(pid: int) -> list[tuple[str, str]]:
    """(exe name, command line) of every process under `pid`."""
    try:
        import psutil

        out = []
        for child in psutil.Process(pid).children(recursive=True):
            try:
                name = child.name().lower()
                line = " ".join(child.cmdline()).lower() if name == "node.exe" else ""
                out.append((name, line))
            except Exception:  # noqa: BLE001 - processes come and go
                continue
        return out
    except Exception:  # noqa: BLE001
        return []


def _ai_in_tree(children: list[tuple[str, str]]) -> str:
    for name, line in children:
        stem = name.removesuffix(".exe")
        if stem in AI_CLIS:
            return stem
        if name == "node.exe":
            line = line.replace("\\", "/")
            for cli in ("claude-code", "@openai/codex", "gemini-cli", "kiro"):
                if cli in line:
                    return cli.split("/")[-1].split("-")[0]
    return ""


def _shell(title: str, process: str, children: list[tuple[str, str]]) -> str:
    lowered = title.lower()
    if "powershell" in lowered or "pwsh" in lowered:
        return "powershell"
    if "command prompt" in lowered or "cmd.exe" in lowered:
        return "cmd"
    if process in ("powershell.exe", "pwsh.exe"):
        return "powershell"
    if process == "cmd.exe":
        return "cmd"
    names = {n for n, _ in children}
    if names & {"powershell.exe", "pwsh.exe"} and "cmd.exe" not in names:
        return "powershell"
    return "cmd"


def detect(hwnd: int | None, title: str, process: str, remembered: str = "",
           pid: int | None = None,
           descendants: Callable[[int], list[tuple[str, str]]] = _descendants) -> Terminal | None:
    """The terminal in front, or None if the window is not a terminal."""
    process = (process or "").lower()
    if not hwnd or process not in TERMINAL_PROCESSES:
        return None
    title = title or ""
    # Windows Terminal hosts every tab and window in one process: its tree
    # says nothing about the one in front.
    children = descendants(pid) if pid and process != "windowsterminal.exe" else []
    ai = _ai_in_title(title) or _ai_in_tree(children)
    if not ai and remembered and not plain_title(title):
        ai = remembered
    return Terminal(hwnd=int(hwnd), title=title, process=process,
                    shell=_shell(title, process, children), ai=ai)


def front() -> tuple[int | None, str, str, int | None]:
    """(hwnd, title, process name, pid) of the foreground window."""
    try:
        import ctypes

        from . import winctl
        from .screen import window_title

        hwnd = winctl.foreground()
        if not hwnd:
            return None, "", "", None
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        return hwnd, window_title(hwnd), winctl.process(hwnd), int(pid.value) or None
    except Exception as exc:  # noqa: BLE001 - off Windows or no window
        log.debug("front window unknown: %s", exc)
        return None, "", "", None
