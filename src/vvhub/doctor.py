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
#
# WS1 component checks. Every probe is bounded by a short timeout: nothing
# here may wait on the user (e.g. `opencli doctor` blocks until the Edge
# extension connects, so the daemon's /status endpoint is read instead).
# Each check body is a plain function with injectable probes for the tests.

import json
import os
import sys
from pathlib import Path

FREELLMAPI_URL = "http://127.0.0.1:3001/v1"
OPENCLI_DAEMON = "http://127.0.0.1:19825/status"
WINDOWS_MCP_VERSION = "0.8.5"
WINDOWS_MCP_EXCLUDED = ("PowerShell", "Registry", "FileSystem")
LAYA_REPO_DIR = "models--convaiinnovations--laya"


def workspace() -> Path:
    """The folder holding Voice_Vibe\\, venvs\\ and Repos\\ (TASK.md layout)."""
    override = os.environ.get("VVHUB_WORKSPACE")
    return Path(override) if override else Path(__file__).resolve().parents[3]


def http_get(url: str, headers: dict | None = None, timeout: float = 3.0) -> tuple[int | None, str]:
    """(status, body); status None when nothing answers. Loopback only."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - localhost
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (OSError, ValueError):
        return None, ""


def _secret(name: str) -> str | None:
    from . import secrets

    return secrets.get(name)


def laya_status(has=importlib.util.find_spec, hf_home: str | None = None,
                tier=None, onnx=None) -> tuple[bool, str]:
    if has("laya") is None:
        return False, "laya not installed in venvs\\voicevibe"
    hf = Path(hf_home or os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
    snapshots = hf / "hub" / LAYA_REPO_DIR / "snapshots"
    if not snapshots.is_dir() or not any(snapshots.iterdir()):
        return False, f"model convaiinnovations/laya not in {hf} (HF_HOME)"
    if tier is None or onnx is None:
        from . import laya_engine

        tier = tier or laya_engine.detect_tier
        onnx = onnx or laya_engine._onnx_file
    found = onnx()
    return True, f"tier {tier()}; int8 onnx {'at ' + found if found else 'missing (CPU tier falls back to torch)'}"


def freellmapi_status(get=http_get, url: str = FREELLMAPI_URL) -> tuple[bool, str]:
    status, _ = get(f"{url}/models")
    if status is None:
        return False, r"not running on 127.0.0.1:3001; start venvs\freellmapi\app\FreeLLMAPI.exe"
    return True, f"listening ({url})"


def freellmapi_key_status(get=http_get, secret=_secret, url: str = FREELLMAPI_URL) -> tuple[bool, str]:
    key = secret("freellmapi_key")
    if not key:
        return False, "unified key not in keyring (voicevibe/freellmapi_key)"
    status, body = get(f"{url}/models", {"Authorization": f"Bearer {key}"})
    if status is None:
        return False, "FreeLLMAPI not running"
    if status != 200:
        return False, f"key rejected (HTTP {status})"
    try:
        count = len(json.loads(body).get("data", []))
    except (ValueError, AttributeError):
        count = 0
    return count > 0, f"{count} models" if count else "no models: add provider keys in the dashboard"


def opencli_status(root: Path | None = None, which=shutil.which) -> tuple[bool, str]:
    pkg = (root or workspace()) / "venvs" / "node" / "node_modules" / "@jackwener" / "opencli"
    if not (pkg / "dist" / "src" / "main.js").is_file():
        return False, r"not installed (npm i -g @jackwener/opencli with prefix venvs\node)"
    if which("node") is None:
        return False, "node not on PATH"
    version = json.loads((pkg / "package.json").read_text(encoding="utf-8")).get("version", "?")
    return True, f"opencli {version}"


def opencli_extension_status(get=http_get) -> tuple[bool, str]:
    status, body = get(OPENCLI_DAEMON, {"X-OpenCLI": "1"}, 2.0)
    if status is None:
        return False, "daemon not running (starts with the first opencli command)"
    try:
        info = json.loads(body)
    except ValueError:
        return False, f"daemon answered HTTP {status}"
    if info.get("extensionConnected"):
        return True, f"Edge extension connected (daemon {info.get('daemonVersion', '?')})"
    return False, r"Edge extension not connected: load venvs\node\opencli-extension\v1.0.24 in edge://extensions"


def windows_mcp_status(root: Path | None = None) -> tuple[bool, str]:
    venv = (root or workspace()) / "venvs" / "windows-mcp"
    if not (venv / "Scripts" / "windows-mcp.exe").is_file():
        return False, r"not installed in venvs\windows-mcp"
    cfg = (venv / "pyvenv.cfg").read_text(encoding="utf-8") if (venv / "pyvenv.cfg").is_file() else ""
    python = next((line.split("=", 1)[1].strip() for line in cfg.splitlines()
                   if line.split("=", 1)[0].strip() in ("version", "version_info")), "?")
    if not python.startswith("3.13"):
        return False, f"venv Python is {python}, expected 3.13"
    site = venv / "Lib" / "site-packages"
    if not (site / f"windows_mcp-{WINDOWS_MCP_VERSION}.dist-info").is_dir():
        return False, f"windows-mcp is not the pinned {WINDOWS_MCP_VERSION}"
    config = venv / "config.toml"
    import tomllib

    excluded = set(tomllib.loads(config.read_text(encoding="utf-8")).get("tools", {}).get("exclude", [])) \
        if config.is_file() else set()
    missing = [t for t in WINDOWS_MCP_EXCLUDED if t not in excluded]
    if missing:
        return False, f"config.toml does not exclude {', '.join(missing)}"
    return True, f"windows-mcp {WINDOWS_MCP_VERSION} on Python {python}"


def agent_reach_status(run=subprocess.run, scripts: Path | None = None) -> tuple[bool, str]:
    exe = (scripts or Path(sys.executable).parent) / ("agent-reach.exe" if os.name == "nt" else "agent-reach")
    if not exe.is_file():
        return False, "agent-reach not installed in this venv"
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    done = run([str(exe), "doctor", "--json"], capture_output=True, text=True, timeout=60,
               encoding="utf-8", errors="replace", env=env)
    try:
        channels = json.loads(done.stdout)
    except ValueError:
        return False, f"doctor gave no JSON (exit {done.returncode})"
    ok = sorted(k for k, v in channels.items() if isinstance(v, dict) and v.get("status") == "ok")
    if "web" not in ok:
        return False, "web reader (Jina) not ok"
    return True, f"{len(ok)}/{len(channels)} channels ok ({', '.join(ok)})"


def secret_status(name: str, how: str, secret=_secret) -> tuple[bool, str]:
    return (True, "set") if secret(name) else (False, f"missing: {how}")


@check("laya")
def _laya() -> tuple[bool, str]:
    return laya_status()


@check("freellmapi")
def _freellmapi() -> tuple[bool, str]:
    return freellmapi_status()


@check("freellmapi key", needs_user=True)
def _freellmapi_key() -> tuple[bool, str]:
    return freellmapi_key_status()


@check("opencli")
def _opencli() -> tuple[bool, str]:
    return opencli_status()


@check("opencli edge extension", needs_user=True)
def _opencli_extension() -> tuple[bool, str]:
    return opencli_extension_status()


@check("windows-mcp")
def _windows_mcp() -> tuple[bool, str]:
    return windows_mcp_status()


@check("agent-reach")
def _agent_reach() -> tuple[bool, str]:
    return agent_reach_status()


@check("notion token", needs_user=True)
def _notion() -> tuple[bool, str]:
    return secret_status("notion_token", "store the Notion integration token in keyring (voicevibe/notion_token)")


@check("telegram token", needs_user=True)
def _telegram() -> tuple[bool, str]:
    return secret_status("telegram_bot_token", "python -m vvbot set-token")


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
