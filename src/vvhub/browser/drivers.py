"""The two browsers the user runs: Edge (via OpenCLI) and Zen (via Windows-MCP).

OpenCLI is Chromium-only, so Zen (Firefox-based) is read through Windows-MCP's
`Scrape(use_dom=True)`, which pulls the active tab's DOM text over UIA /
IAccessible2 (CursorTouch/Windows-MCP, MIT). Windows-MCP is started on demand
over stdio, telemetry off, with PowerShell/Registry/FileSystem excluded.

Opening a page launches the browser's own exe with the URL as one argument
(no shell), so it lands as a new tab in the user's normal window rather than
in an OpenCLI-owned automation tab.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from .opencli import OpenCLI, OpenCLIError, workspace

ToolCaller = Callable[[str, dict], Awaitable[str]]
Launcher = Callable[[list[str]], Awaitable[None]]

EDGE_PROCESSES = {"msedge.exe", "msedge"}
ZEN_PROCESSES = {"zen.exe", "zen"}
EXCLUDED_MCP_TOOLS = "PowerShell,Registry,FileSystem"


class BrowserError(RuntimeError):
    def __init__(self, message: str, spoken: str | None = None) -> None:
        super().__init__(message)
        self.spoken = spoken or message


def safe_url(url: str) -> str:
    """http(s) only — never file:, javascript:, data: or an option-like arg."""
    text = (url or "").strip()
    if text and "://" not in text and re.fullmatch(r"[\w.-]+\.[a-z]{2,}(/\S*)?", text, re.I):
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or any(c.isspace() for c in text):
        raise BrowserError(f"not a web address: {url!r}", "That isn't a web address I can open.")
    return text


async def _launch(argv: list[str]) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) if os.name == "nt" else 0
    await asyncio.to_thread(subprocess.Popen, argv, close_fds=True, creationflags=flags,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _find_exe(names: list[str], candidates: list[Path]) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def edge_exe() -> str | None:
    pf86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    return _find_exe(["msedge"], [pf86 / "Microsoft/Edge/Application/msedge.exe",
                                  pf / "Microsoft/Edge/Application/msedge.exe"])


def zen_exe() -> str | None:
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    return _find_exe(["zen"], [pf / "Zen Browser/zen.exe", local / "Programs/Zen Browser/zen.exe"])


class Page(dict):
    """{"browser", "url", "title", "text"} for the page that was read."""


class EdgeBrowser:
    """The user's Edge, through the OpenCLI Browser Bridge extension."""

    name = "edge"
    SESSION = "vvhub-read"

    def __init__(self, cli: OpenCLI | None = None, launcher: Launcher | None = None,
                 exe: str | None = None) -> None:
        self.cli = cli or OpenCLI()
        self.launcher = launcher or _launch
        self._exe = exe

    async def open(self, url: str) -> None:
        url = safe_url(url)
        exe = self._exe or edge_exe()
        if not exe:
            raise BrowserError("msedge.exe not found", "I can't find Edge on this laptop.")
        await self.launcher([exe, url])

    async def read_current(self, max_chars: int = 30000) -> Page:
        """Markdown of the tab the user is looking at (bind -> extract -> unbind).
        Binding never closes or owns the user's tab."""
        s = self.SESSION
        try:
            await self.cli.run("browser", s, "bind", fmt=None, timeout=30)
            text, start, meta = [], 0, {}
            while start is not None and sum(map(len, text)) < max_chars:
                chunk = await self.cli.run("browser", s, "extract",
                                           flags={"chunk-size": 8000, "start": start or None},
                                           fmt=None, timeout=60)
                if not isinstance(chunk, dict):
                    text.append(str(chunk or ""))
                    break
                meta = meta or chunk
                text.append(str(chunk.get("content") or ""))
                nxt = chunk.get("next_start_char")
                start = nxt if isinstance(nxt, int) and nxt > start else None
        except OpenCLIError as exc:
            raise BrowserError(str(exc), f"I couldn't read the Edge page: {exc.spoken}.") from exc
        finally:
            try:
                await self.cli.run("browser", s, "unbind", fmt=None, timeout=15)
            except Exception:  # noqa: BLE001 - best effort; bind already failed or tab is gone
                pass
        return Page(browser=self.name, url=str(meta.get("url") or ""), title=str(meta.get("title") or ""),
                    text="".join(text)[:max_chars])


class WindowsMCP:
    """On-demand stdio client for Windows-MCP (one short session per call)."""

    def __init__(self, command: list[str] | None = None, timeout: float = 60.0) -> None:
        self.command = command
        self.timeout = timeout

    def resolve(self) -> list[str] | None:
        if self.command:
            return self.command
        exe = workspace() / "venvs" / "windows-mcp" / "Scripts" / "windows-mcp.exe"
        return [str(exe), "serve"] if exe.is_file() else None

    async def __call__(self, tool: str, args: dict) -> str:
        command = self.resolve()
        if command is None:
            raise BrowserError("Windows-MCP not installed in venvs\\windows-mcp",
                               "Windows-MCP isn't installed, so I can't read Zen.")
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = dict(os.environ, ANONYMIZED_TELEMETRY="false", WINDOWS_MCP_DISABLE_FLASH="1",
                   WINDOWS_MCP_EXCLUDE_TOOLS=EXCLUDED_MCP_TOOLS)
        params = StdioServerParameters(command=command[0], args=command[1:], env=env)

        async def _go() -> str:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, args)
            parts = getattr(result, "content", None) or []
            return "\n".join(str(getattr(p, "text", "")) for p in parts if getattr(p, "text", None))

        return await asyncio.wait_for(_go(), self.timeout)


class ZenBrowser:
    """Zen: open via zen.exe, read the foreground tab's DOM via Windows-MCP."""

    name = "zen"

    def __init__(self, call_tool: ToolCaller | None = None, launcher: Launcher | None = None,
                 exe: str | None = None) -> None:
        self.call_tool = call_tool or WindowsMCP()
        self.launcher = launcher or _launch
        self._exe = exe

    async def open(self, url: str) -> None:
        url = safe_url(url)
        exe = self._exe or zen_exe()
        if not exe:
            raise BrowserError("zen.exe not found", "I can't find Zen on this laptop.")
        await self.launcher([exe, url])

    async def read_current(self, max_chars: int = 30000, context: dict | None = None) -> Page:
        try:
            raw = await self.call_tool("Scrape", {"url": "about:current", "use_dom": True,
                                                  "use_sampling": False})
        except BrowserError:
            raise
        except Exception as exc:  # noqa: BLE001 - MCP transport / tool errors
            raise BrowserError(f"Windows-MCP Scrape failed: {exc}", "I couldn't read the Zen page.") from exc
        if not raw or raw.startswith("No DOM information"):
            raise BrowserError("no DOM from Zen", "Zen needs to be the front window for me to read it.")
        text = raw.split("Content:\n", 1)[1] if "Content:\n" in raw else raw
        for marker in ("Reached top\n", "Scroll up to see more\n"):
            if text.startswith(marker):
                text = text[len(marker):]
        browser = (context or {}).get("browser") or {}
        window = (context or {}).get("window") or {}
        title = browser.get("title") or re.sub(r"\s+[—-]\s+Zen( Browser)?$", "", window.get("title", ""))
        return Page(browser=self.name, url=browser.get("url", ""), title=title, text=text[:max_chars])


def detect(context: dict | None, text: str = "", last: str | None = None) -> str:
    """Which browser the user means: a spoken name wins, then the foreground
    window's process, then the last one used, else Edge."""
    spoken = (text or "").lower()
    if re.search(r"\bzen\b", spoken):
        return "zen"
    if re.search(r"\b(edge|microsoft edge)\b", spoken):
        return "edge"
    ctx = context or {}
    process = str((ctx.get("window") or {}).get("process") or "").lower()
    name = str((ctx.get("browser") or {}).get("name") or "").lower()
    if process in ZEN_PROCESSES or name == "zen":
        return "zen"
    if process in EDGE_PROCESSES or name == "edge":
        return "edge"
    return last if last in ("edge", "zen") else "edge"


class Browsers:
    """Holds one driver per browser and remembers the last one used."""

    def __init__(self, edge: Any = None, zen: Any = None) -> None:
        self.edge = edge or EdgeBrowser()
        self.zen = zen or ZenBrowser()
        self.last: str | None = None

    def pick(self, context: dict | None = None, text: str = "") -> Any:
        name = detect(context, text, self.last)
        self.last = name
        return self.zen if name == "zen" else self.edge

    async def read_current(self, context: dict | None = None, text: str = "", max_chars: int = 30000) -> Page:
        browser = self.pick(context, text)
        if browser.name == "zen":
            return await browser.read_current(max_chars=max_chars, context=context)
        return await browser.read_current(max_chars=max_chars)
