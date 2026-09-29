"""Run OpenCLI (jackwener/opencli, Apache-2.0) commands from the hub.

OpenCLI drives the user's real, logged-in Edge through its Browser Bridge
extension. We only build argument lists and parse its output:

- It is called as `node <prefix>/node_modules/@jackwener/opencli/dist/src/main.js`,
  never through `opencli.cmd`: a .cmd shim runs under cmd.exe, which re-parses
  arguments (`&`, `|`, `%`...) — unsafe for dictated post text.
- Positionals go after `--`, so text starting with "-" can't become an option.
- Exit codes follow OpenCLI's sysexits table (docs/guide/exit-codes.md).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Awaitable, Callable

Runner = Callable[[list[str], float], Awaitable[tuple[int, str, str]]]

EXIT_KINDS = {
    1: "error",
    2: "usage",
    66: "empty",
    69: "bridge_unavailable",
    75: "timeout",
    77: "auth_required",
    78: "config",
    130: "interrupted",
}

SPOKEN = {
    "bridge_unavailable": "the OpenCLI extension isn't connected in Edge",
    "auth_required": "you're not logged in to that site in Edge",
    "timeout": "the browser step timed out",
    "empty": "nothing came back",
    "config": "OpenCLI is missing a setting",
    "usage": "OpenCLI rejected the command",
    "missing": "OpenCLI isn't installed",
}


class OpenCLIError(RuntimeError):
    def __init__(self, kind: str, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code

    @property
    def spoken(self) -> str:
        return SPOKEN.get(self.kind, "the browser step failed")


def workspace() -> Path:
    """The folder holding Voice_Vibe\\, venvs\\ and Repos\\ (TASK.md layout)."""
    override = os.environ.get("VVHUB_WORKSPACE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[4]


def find_opencli() -> list[str] | None:
    """argv prefix to run OpenCLI, or None if it isn't installed."""
    override = os.environ.get("VVHUB_OPENCLI_MAIN")
    main = Path(override) if override else (
        workspace() / "venvs" / "node" / "node_modules" / "@jackwener" / "opencli" / "dist" / "src" / "main.js")
    node = shutil.which("node")
    if node and main.is_file():
        return [node, str(main)]
    return None


async def subprocess_runner(argv: list[str], timeout: float) -> tuple[int, str, str]:
    env = dict(os.environ, NO_COLOR="1", FORCE_COLOR="0")
    kwargs: dict[str, Any] = dict(capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout, env=env)
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = await asyncio.to_thread(subprocess.run, argv, **kwargs)
    except subprocess.TimeoutExpired:
        return 75, "", f"timed out after {timeout:.0f}s"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _error_message(out: str, err: str) -> str:
    text = f"{err}\n{out}"
    try:
        data = json.loads(out)
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            return str(data["error"].get("message") or data["error"])
    except (ValueError, TypeError):
        pass
    match = re.search(r"message:\s*(.+)", text)
    if match:
        return match.group(1).strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[0] if lines else "unknown error"


def parse_output(out: str) -> Any:
    out = out.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return out


class OpenCLI:
    def __init__(self, prefix: list[str] | None = None, runner: Runner | None = None,
                 timeout: float = 120.0) -> None:
        self._prefix = prefix
        self.runner = runner or subprocess_runner
        self.timeout = timeout

    @property
    def prefix(self) -> list[str] | None:
        if self._prefix is None:
            self._prefix = find_opencli()
        return self._prefix

    def available(self) -> bool:
        return self.prefix is not None

    def argv(self, *words: str, positionals: tuple = (), flags: dict | None = None,
             fmt: str | None = "json") -> list[str]:
        prefix = self.prefix
        if prefix is None:
            raise OpenCLIError("missing", "OpenCLI not found under venvs\\node")
        for word in words:
            if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", word):
                raise OpenCLIError("usage", f"bad command word {word!r}")
        argv = [*prefix, *words]
        for key, value in (flags or {}).items():
            if value is None or value is False:
                continue
            if not re.fullmatch(r"[a-z][a-z0-9-]*", key):
                raise OpenCLIError("usage", f"bad flag {key!r}")
            argv.append(f"--{key}")
            if value is not True:
                argv.append(str(value))
        if fmt:
            argv += ["-f", fmt]
        if positionals:
            argv.append("--")
            argv += [str(p) for p in positionals]
        return argv

    async def run(self, *words: str, positionals: tuple = (), flags: dict | None = None,
                  fmt: str | None = "json", timeout: float | None = None) -> Any:
        argv = self.argv(*words, positionals=positionals, flags=flags, fmt=fmt)
        code, out, err = await self.runner(argv, timeout or self.timeout)
        if code != 0:
            raise OpenCLIError(EXIT_KINDS.get(code, "error"), _error_message(out, err), code)
        return parse_output(out)
