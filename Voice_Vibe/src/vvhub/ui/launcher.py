"""Start the hub and Voice Vibe so they outlive the shell that launched them (T19).

`run.bat` -> `python -m vvhub.ui.launcher start [Voice Vibe args]`:
1. `hub_up()`: GET http://127.0.0.1:53874/health. Any HTTP answer (200, or a
   401 for a stale token) means the hub is up; a refused / timed-out
   connection means it isn't.
2. Down -> `pythonw -m vvhub serve` is started hidden, before Voice Vibe.
3. `pythonw -m voicevibe [args]`.

"Detached" = CreateProcess with DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP |
CREATE_BREAKAWAY_FROM_JOB, so a terminal, IDE or tool shell that kills its
job object on exit doesn't take the apps along. If that job forbids
breakaway, WMI `Win32_Process.Create` starts them instead (their parent is
then WmiPrvSE, outside any job), with this environment passed along
explicitly because WMI doesn't inherit it.

Login autostart is opt-in: `autostart on|off|status` writes / removes one
value, HKCU\\...\\Run "VoiceVibe" = "<pythonw>" -m vvhub.ui.launcher start --
the key tauri-plugin-autostart uses on Windows (OpenJarvis desktop).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .. import HOST, PORT, data_dir

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

HEALTH_URL = f"http://{HOST}:{PORT}/health"
REPO = Path(__file__).resolve().parents[3]          # ...\Voice_Vibe
VENVS = REPO.parent / "venvs"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "VoiceVibe"


def read_token() -> str | None:
    try:
        return (data_dir() / "hub.token").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def hub_up(url: str = HEALTH_URL, token: str | None = None, timeout: float = 1.5,
           opener: Callable[..., Any] = urllib.request.urlopen) -> bool:
    """True if anything answers HTTP on the hub's /health."""
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with opener(req, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True  # it answered (e.g. 401): the hub is up
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return False


def pythonw() -> str:
    """The windowless interpreter next to this one (falls back to this one)."""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else exe)


def child_env(base: dict | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    env.setdefault("HF_HOME", str(VENVS / "hf-cache"))
    env.setdefault("UV_CACHE_DIR", str(VENVS / "uv-cache"))
    env.pop("PYTHONHOME", None)
    return env


def command_line(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv)


def wmi_create(argv: list[str], cwd: str | None, env: dict) -> int:
    """Win32_Process.Create through pywin32's COM client (no PowerShell start-up)."""
    import pythoncom  # noqa: F401 - initialises COM for this thread
    import win32com.client

    wmi = win32com.client.GetObject(r"winmgmts:\\.\root\cimv2")
    startup = wmi.Get("Win32_ProcessStartup").SpawnInstance_()
    startup.ShowWindow = 0  # SW_HIDE
    startup.EnvironmentVariables = [f"{k}={v}" for k, v in env.items() if "=" not in k and k]
    proc = wmi.Get("Win32_Process")
    params = proc.Methods_("Create").InParameters.SpawnInstance_()
    params.CommandLine = command_line(argv)
    if cwd:
        params.CurrentDirectory = str(cwd)
    params.ProcessStartupInformation = startup
    out = proc.ExecMethod_("Create", params)
    if int(out.ReturnValue) != 0:
        raise OSError(f"Win32_Process.Create returned {out.ReturnValue}")
    return int(out.ProcessId)


def spawn(argv: list[str], cwd: str | Path | None = None, env: dict | None = None, *,
          popen: Callable[..., Any] = subprocess.Popen, wmi: Callable[..., int] | None = wmi_create) -> int:
    """Start argv outside this shell's job; returns the pid."""
    base = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    common = dict(cwd=str(cwd) if cwd else None, env=env, close_fds=True,
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return popen(argv, creationflags=base | CREATE_BREAKAWAY_FROM_JOB, **common).pid
    except OSError:
        pass  # the job this shell runs in forbids breakaway
    if wmi is not None:
        try:
            return wmi(argv, common["cwd"], env or dict(os.environ))
        except Exception:  # noqa: BLE001 - no pywin32 / WMI off: best effort below
            pass
    return popen(argv, creationflags=base, **common).pid


def ensure_hub(*, hub_up: Callable[..., bool] = hub_up, spawn: Callable[..., int] = spawn,
               env: dict | None = None, wait: float = 3.0, out: Callable[[str], None] = lambda s: None) -> str:
    """'running' | 'started' | 'failed: ...'. Waits up to `wait` s for /health after starting."""
    if hub_up(token=read_token()):
        return "running"
    try:
        spawn([pythonw(), "-m", "vvhub", "serve"], cwd=REPO, env=env or child_env())
    except Exception as exc:  # noqa: BLE001 - Voice Vibe still runs without the hub (rule 8)
        out(f"hub not started: {exc}")
        return f"failed: {exc}"
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        time.sleep(0.25)
        if hub_up(token=read_token(), timeout=0.5):
            break
    return "started"


def start(voicevibe_args: list[str], *, hub_up: Callable[..., bool] = hub_up,
          spawn: Callable[..., int] = spawn, wait: float = 3.0,
          out: Callable[[str], None] = lambda s: None) -> int:
    env = child_env()
    out(f"hub: {ensure_hub(hub_up=hub_up, spawn=spawn, env=env, wait=wait, out=out)}")
    try:
        pid = spawn([pythonw(), "-m", "voicevibe", *voicevibe_args], cwd=REPO, env=env)
    except Exception as exc:  # noqa: BLE001
        out(f"Voice Vibe not started: {exc}")
        return 1
    out(f"voicevibe: started (pid {pid})")
    return 0


# ---- control panel (tray entry) -------------------------------------------------
def open_control_panel(spawn: Callable[..., int] = spawn) -> int:
    """Start `pythonw -m vvhub.ui` detached; it focuses an already open window itself."""
    return spawn([pythonw(), "-m", "vvhub.ui"], cwd=REPO, env=child_env())


def add_tray_entry(tray: Any, opener: Callable[[], Any] = open_control_panel) -> bool:
    """Put a default "Control panel" item on top of Voice Vibe's tray menu (double-click opens it)."""
    icon = getattr(tray, "icon", None)
    if icon is None:
        return False
    import pystray

    items = tuple(getattr(getattr(icon, "menu", None), "items", ()) or ())
    icon.menu = pystray.Menu(pystray.MenuItem("Control panel", lambda: opener(), default=True), *items)
    return True


# ---- login autostart (HKCU Run) ----------------------------------------------
def _winreg() -> Any:
    import winreg

    return winreg


def autostart_command() -> str:
    return f'"{pythonw()}" -m vvhub.ui.launcher start'


def autostart_enabled(reg: Any = None) -> bool:
    reg = reg or _winreg()
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ) as key:
            value, _ = reg.QueryValueEx(key, RUN_VALUE)
    except OSError:
        return False
    return bool(value)


def set_autostart(enabled: bool, reg: Any = None) -> None:
    reg = reg or _winreg()
    with reg.CreateKey(reg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            reg.SetValueEx(key, RUN_VALUE, 0, reg.REG_SZ, autostart_command())
        else:
            try:
                reg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass


SECRET_ALIASES = {"freellmapi": "freellmapi_key", "notion": "notion_token", "telegram": "telegram_bot_token"}


def set_secret(alias: str, *, ask: Callable[[str], str] = input, out: Callable[[str], None] = print) -> int:
    """Paste a key at a visible prompt -> keyring (hidden prompts often drop Ctrl+V)."""
    from .. import secrets
    from .services import check_secret

    name = SECRET_ALIASES.get(alias, alias)
    if name not in SECRET_ALIASES.values():
        out(f"Unknown key. Use one of: {', '.join(SECRET_ALIASES)}")
        return 2
    value = (ask(f"Paste the {alias} key and press Enter: ") or "").strip()
    problem = check_secret(name, value)
    if problem:
        out(f"Not saved. {problem}")
        return 1
    secrets.set(name, value)
    out(f"{alias} key saved to Windows Credential Manager ({len(value)} characters).")
    return 0


def main(argv: list[str] | None = None, *, reg: Any = None, out: Callable[[str], None] = print,
         ask: Callable[[str], str] = input) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["start"]:  # everything after "start" belongs to Voice Vibe, dashes included
        return start(argv[1:], out=out)
    if argv[:1] == ["set-secret"]:
        return set_secret(argv[1] if len(argv) > 1 else "", ask=ask, out=out)
    parser = argparse.ArgumentParser(prog="python -m vvhub.ui.launcher")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("start", help="hub (if down) then Voice Vibe, both detached; later args go to Voice Vibe")
    sub.add_parser("hub", help="start the hub only if /health doesn't answer")
    au = sub.add_parser("autostart", help="start at login (off by default)")
    au.add_argument("action", choices=["on", "off", "status"])
    args = parser.parse_args(argv)

    if args.command == "hub":
        out(f"hub: {ensure_hub(out=out)}")
        return 0
    if args.action != "status":
        set_autostart(args.action == "on", reg=reg)
    out(f"autostart at login: {'on' if autostart_enabled(reg=reg) else 'off'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
