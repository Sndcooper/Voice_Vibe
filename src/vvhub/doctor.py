"""`python -m vvhub doctor`: one row per component, green or red.

Framework by WS0; the component checks below are WS1's to extend (TASK.md §4).
Each check prefers the project's own health command (`opencli doctor`,
`agent-reach doctor`, FreeLLMAPI `/v1/models`). A check returns
(ok, detail); an exception counts as red with the message as detail.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

from . import HOST, PORT


@dataclass
class Check:
    name: str
    run: Callable[[], tuple[bool, str]]
    needs_user: bool = False  # red is expected until the user links an account


CHECKS: list[Check] = []


def check(name: str, needs_user: bool = False) -> Callable:
    def register(fn: Callable[[], tuple[bool, str]]) -> Callable[[], tuple[bool, str]]:
        CHECKS.append(Check(name, fn, needs_user))
        return fn

    return register


def module_present(name: str) -> tuple[bool, str]:
    spec = importlib.util.find_spec(name)
    return (spec is not None, "installed" if spec else f"python module {name} missing")


def command_present(name: str) -> tuple[bool, str]:
    path = shutil.which(name)
    return (path is not None, path or f"{name} not on PATH")


def command_ok(args: list[str], timeout: float = 20.0) -> tuple[bool, str]:
    """Run a command (argument list, no shell); green on exit code 0."""
    if shutil.which(args[0]) is None:
        return False, f"{args[0]} not on PATH"
    done = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")
    lines = (done.stdout or done.stderr).strip().splitlines()
    return done.returncode == 0, lines[-1] if lines else f"exit {done.returncode}"


# --- checks -------------------------------------------------------------

@check("hub server")
def _hub() -> tuple[bool, str]:
    import urllib.request

    from .server import load_or_create_token

    request = urllib.request.Request(
        f"http://{HOST}:{PORT}/health",
        headers={"Authorization": f"Bearer {load_or_create_token()}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310 - localhost
            return response.status == 200, f"{HOST}:{PORT}"
    except OSError as exc:
        return False, f"not running ({exc.__class__.__name__}); start: python -m vvhub serve"


@check("gh CLI")
def _gh() -> tuple[bool, str]:
    return command_ok(["gh", "auth", "status"])


@check("keyring")
def _keyring() -> tuple[bool, str]:
    return module_present("keyring")


# WS1: add checks for laya, freellmapi, opencli, windows-mcp, agent-reach,
# notion, telegram... with @check("name", needs_user=...) below this line.


def run_checks(checks: list[Check] | None = None) -> list[tuple[Check, bool, str]]:
    results = []
    for item in checks if checks is not None else CHECKS:
        try:
            ok, detail = item.run()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{exc.__class__.__name__}: {exc}"
        results.append((item, bool(ok), str(detail)))
    return results


def render(results: list[tuple[Check, bool, str]]) -> str:
    width = max((len(c.name) for c, _, _ in results), default=10)
    lines = []
    for item, ok, detail in results:
        mark = "OK  " if ok else ("USER" if item.needs_user else "FAIL")
        lines.append(f"  {mark}  {item.name:<{width}}  {detail}")
    return "\n".join(lines)


def main() -> int:
    results = run_checks()
    print(render(results))
    hard_fail = [c for c, ok, _ in results if not ok and not c.needs_user]
    return 1 if hard_fail else 0
