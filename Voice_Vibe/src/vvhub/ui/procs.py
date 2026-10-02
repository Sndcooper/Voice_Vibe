"""RAM / CPU per component for the Status page (psutil).

RAM = private working set (psutil USS), what Task Manager's Memory column
shows; WS = full working set incl. shared DLLs. A component's children count
towards it (the venv's pythonw stub starts the real interpreter; the control
app starts WebView2). CPU % needs two samples, so Process objects are kept
between calls: the first reading is 0.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

MB = 2 ** 20
PORTS = {"freellmapi": 3001, "opencli daemon": 19825}
CACHE_SECONDS = 3.0

# (component, test on lowercase "name cmdline"); first match wins.
GROUPS: list[tuple[str, Any]] = [
    ("hub", lambda s: "vvhub serve" in s),
    ("voicevibe", lambda s: "-m voicevibe" in s),
    ("telegram bot", lambda s: "-m vvbot" in s),
    ("control app", lambda s: "-m vvhub.ui" in s and "launcher" not in s),
    ("freellmapi", lambda s: "freellmapi" in s),
    ("opencli daemon", lambda s: "opencli" in s and "node" in s),
    ("windows-mcp", lambda s: "windows-mcp" in s or "windows_mcp" in s),
    ("airoot overlay", lambda s: "airootvoiceoverlay" in s),
]
_NAMES = ("python", "node", "freellmapi", "airoot", "windows-mcp", "uv")

_lock = threading.Lock()
_procs: dict[int, Any] = {}
_cache: tuple[float, dict] | None = None


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.2) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def _proc(psutil: Any, pid: int) -> Any:
    p = _procs.get(pid)
    if p is None:
        p = _procs[pid] = psutil.Process(pid)
    return p


def _scan(psutil: Any) -> dict:
    groups: dict[str, set[int]] = {name: set() for name, _ in GROUPS}
    claimed: set[int] = set()
    for p in psutil.process_iter(["name"]):
        name = (p.info.get("name") or "").lower()
        if not name.startswith(_NAMES) and "freellmapi" not in name:
            continue
        try:
            text = f"{name} {' '.join(p.cmdline())}".lower().replace("\\", "/")
        except (psutil.Error, OSError):
            continue
        for group, test in GROUPS:
            if p.pid not in claimed and test(text):
                pids = {p.pid}
                try:
                    pids |= {c.pid for c in p.children(recursive=True)}
                except psutil.Error:
                    pass
                pids -= claimed
                groups[group] |= pids
                claimed |= pids
                break
    rows, total = [], 0.0
    for group, _ in GROUPS:
        ram = ws = cpu = 0.0
        alive = []
        for pid in sorted(groups[group]):
            try:
                p = _proc(psutil, pid)
                mi = p.memory_full_info()
                ram += mi.uss / MB
                ws += mi.rss / MB
                cpu += p.cpu_percent(None)
                alive.append(pid)
            except (psutil.Error, OSError):
                _procs.pop(pid, None)
        port = PORTS.get(group)
        running = bool(alive) or (port is not None and port_open(port))
        rows.append({"name": group, "running": running, "pids": alive, "ram_mb": round(ram, 1),
                     "ws_mb": round(ws, 1), "cpu_pct": round(cpu / max(psutil.cpu_count() or 1, 1), 1),
                     **({"port": port} if port else {})})
        total += ram
    for pid in [pid for pid in _procs if not any(pid in g for g in groups.values())]:
        _procs.pop(pid, None)
    return {"processes": rows, "total_ram_mb": round(total, 1), "at": time.time()}


def snapshot() -> dict:
    """Cached for a few seconds: the page polls, psutil is not free."""
    global _cache
    with _lock:
        if _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
            return _cache[1]
        try:
            import psutil
        except ImportError:
            return {"processes": [], "total_ram_mb": 0.0, "error": "psutil not installed"}
        data = _scan(psutil)
        _cache = (time.monotonic(), data)
        return data
