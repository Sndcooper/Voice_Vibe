"""HTTP API for the control app (WS5), mounted on the hub by `install(app)`.

Every route under /ui/api requires `Authorization: Bearer <hub token>`
(router-level dependency, checked before anything else, constant-time
compare). The only routes without it are the static page files under /ui/:
HTML/JS/CSS that carry no data and no token (the window process hands the
token to the page through pywebview's JS bridge). The hub binds 127.0.0.1 only.

Secrets go one way: POST /ui/api/secrets/<name> -> keyring; responses only
ever say whether a secret is set.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse

from .. import __version__, data_dir, protocol
from .. import secrets as hub_secrets
from . import launcher, services
from .chats import Chats, NotFound
from .settings import validate, write

log = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"
ROLES = ("voicevibe", "bot", "ui")
_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="vvui")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self' ws://127.0.0.1:53874 ws://localhost:53874; frame-src 'self' blob:; "
       "object-src 'none'; base-uri 'none'; form-action 'none'")


def _default_checks() -> list[dict]:
    """All doctor checks in parallel, each time-limited (a slow CLI can't stall the rest)."""
    from .. import doctor

    def one(check: Any) -> dict:
        try:
            ok, detail = check.run()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        return {"name": check.name, "ok": bool(ok), "detail": str(detail), "needs_user": check.needs_user}

    futures = {c.name: _POOL.submit(one, c) for c in doctor.CHECKS}
    out = []
    for check in doctor.CHECKS:
        try:
            out.append(futures[check.name].result(timeout=30))
        except Exception:  # noqa: BLE001 - TimeoutError: report, don't wait
            out.append({"name": check.name, "ok": False, "detail": "timed out after 30 s",
                        "needs_user": check.needs_user})
    return out


def _default_pairing() -> Any:
    from vvbot.pairing import Pairing

    return Pairing()


def _default_notion() -> Any:
    from ..skills.notes import NotionNotes

    return NotionNotes()


def _default_snapshot() -> dict:
    from .procs import snapshot

    return snapshot()


@dataclass
class UIDeps:
    """Everything that touches the machine, swappable in tests."""

    config_path: Path = field(default_factory=lambda: launcher.REPO / "config.toml")
    run_checks: Callable[[], list[dict]] = _default_checks
    check_timeout: float = 45.0
    snapshot: Callable[[], dict] = _default_snapshot
    open_target: Callable[[str, Any], None] = services.open_target
    spawn: Callable[..., int] = launcher.spawn
    registry: Any = None  # None = the real winreg
    pairing: Callable[[], Any] = _default_pairing
    notion: Callable[[], Any] = _default_notion
    gh_status: Callable[[], tuple[bool, str]] = services.gh_status
    bot_python: Path = field(default_factory=lambda: launcher.VENVS / "telegram-bot" / "Scripts" / "pythonw.exe")
    cache: dict = field(default_factory=dict)


def _hub(request: Request) -> Any:
    return request.app.state.hub


def _deps(request: Request) -> UIDeps:
    return request.app.state.ui


async def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    presented = authorization or ""
    if not presented.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="bad or missing token")
    token = presented[len("Bearer "):].strip()
    hub = request.app.state.hub
    if not token or not hmac.compare_digest(token.encode(), str(hub.token).encode()):
        raise HTTPException(status_code=401, detail="bad or missing token")


async def _in_pool(fn: Callable, *args: Any, timeout: float | None = None) -> Any:
    future = asyncio.get_running_loop().run_in_executor(_POOL, fn, *args)
    return await (asyncio.wait_for(future, timeout) if timeout else future)


router = APIRouter(prefix="/ui/api", dependencies=[Depends(require_token)])
static_router = APIRouter()


# ---- static page (no data, no token) -------------------------------------------------
def _static(path: Path) -> FileResponse:
    resp = FileResponse(path)
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@static_router.get("/ui", include_in_schema=False)
@static_router.get("/ui/", include_in_schema=False)
async def index() -> FileResponse:
    return _static(STATIC / "index.html")


@static_router.get("/ui/static/{path:path}", include_in_schema=False)
async def asset(path: str) -> FileResponse:
    target = (STATIC / path).resolve()
    if STATIC not in target.parents or not target.is_file():
        raise HTTPException(status_code=404)
    return _static(target)


# ---- status ---------------------------------------------------------------------------------
def _midnight() -> float:
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _today(store: Any) -> dict:
    import json

    since = _midnight()
    by_source: dict[str, int] = {}
    requests = 0
    for row in store._rows("SELECT role, data FROM turns WHERE ts >= ?", (since,)):
        if row["role"] != "user":
            continue
        requests += 1
        try:
            source = json.loads(row["data"] or "{}").get("source") or "voice"
        except ValueError:
            source = "voice"
        by_source[source] = by_source.get(source, 0) + 1
    auto = asked = 0
    for row in store.decisions(since):
        try:
            d = json.loads(row["decision"]) if isinstance(row["decision"], str) else row["decision"]
        except ValueError:
            continue
        if d.get("needs_approval") or d.get("critical"):
            asked += 1
        else:
            auto += 1
    approvals: dict[str, int] = {}
    for row in store._rows("SELECT status FROM approvals WHERE created >= ?", (since,)):
        approvals[row["status"]] = approvals.get(row["status"], 0) + 1
    return {"requests": requests, "by_source": by_source, "auto": auto, "asked": asked, "approvals": approvals}


@router.get("/status")
async def status(request: Request) -> dict:
    hub, deps = _hub(request), _deps(request)
    snap = await _in_pool(deps.snapshot, timeout=10)
    checks = (deps.cache.get("services") or {}).get("checks") or []
    return {"hub": {"ok": True, "version": __version__}, "connected": {r: hub.bus.connected(r) for r in ROLES},
            "today": await _in_pool(_today, hub.store), "processes": snap.get("processes", []),
            "total_ram_mb": snap.get("total_ram_mb", 0.0), "checks": checks, "at": time.time()}


# ---- services + secrets ---------------------------------------------------------------------
async def _run_checks(deps: UIDeps) -> dict:
    error = ""
    try:
        checks = await _in_pool(deps.run_checks, timeout=deps.check_timeout)
    except asyncio.TimeoutError:
        checks, error = [], f"doctor checks timed out after {deps.check_timeout:g} s"
    try:
        gh = await _in_pool(deps.gh_status, timeout=20)
    except asyncio.TimeoutError:
        gh = (False, "gh auth status timed out")
    return {"at": time.time(), "checks": checks, "gh": gh, "error": error}


@router.get("/services")
async def services_(request: Request, refresh: int = 0) -> dict:
    deps = _deps(request)
    cached = deps.cache.get("services")
    if refresh or cached is None:
        cached = deps.cache["services"] = await _run_checks(deps)
    by_name = {c["name"]: c for c in cached["checks"]}
    pairing = deps.pairing()
    cards = []
    for card in services.CARDS:
        state, detail = services.card_status(card, by_name)
        if card["id"] == "github":
            gh_ok, gh_detail = cached["gh"]
            state, detail = ("ok" if gh_ok and state != "fail" else ("fail" if state == "fail" else "user")), gh_detail
        entry = {"id": card["id"], "title": card["title"], "status": state, "detail": detail,
                 "help": card["help"], "secret": card["secret"],
                 "secret_set": bool(card["secret"] and hub_secrets.get(card["secret"])),
                 "actions": [{"id": k, "label": v[0]} for k, v in card["actions"].items()]}
        if card["id"] == "telegram":
            entry["paired"] = pairing.owner is not None
            entry["bot_connected"] = _hub(request).bus.connected("bot")
        cards.append(entry)
    return {"cards": cards, "checks": cached["checks"], "checked_at": cached["at"], "error": cached["error"]}


@router.post("/services/{card}/{action}")
async def service_action(request: Request, card: str, action: str) -> dict:
    deps = _deps(request)
    spec = services.CARD_BY_ID.get(card)
    if spec is None or action not in spec["actions"]:
        raise HTTPException(status_code=404, detail="unknown action")
    _label, kind, target = spec["actions"][action]
    if kind != "internal":
        try:
            await _in_pool(deps.open_target, kind, target, timeout=15)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": "Opened."}
    if action == "notion_setup":
        try:
            layout = await asyncio.wait_for(deps.notion().layout(), 60)
        except Exception as exc:  # noqa: BLE001 - NotesError carries a user-facing sentence
            return {"ok": False, "message": str(exc)}
        sections = [k for k in layout if k != "root"]
        return {"ok": True, "message": "Notion is ready: " + ", ".join(sections) + " under 'Voice Vibe'."}
    pairing = deps.pairing()
    if action == "telegram_pair":
        if pairing.owner is not None:
            return {"ok": True, "message": "Already paired with your chat. Unpair first to pair another."}
        code = pairing.new_code()
        return {"ok": True, "code": code,
                "message": f"Send this to your bot from your phone within an hour:  /pair {code}"}
    if action == "telegram_unpair":
        pairing.unpair()
        return {"ok": True, "message": "Unpaired. The bot answers nobody until you pair again."}
    if action == "telegram_start":
        if not hub_secrets.get("telegram_bot_token"):
            return {"ok": False, "message": "Paste the bot token first."}
        if _hub(request).bus.connected("bot"):
            return {"ok": True, "message": "The bot is already running."}
        python = Path(deps.bot_python)
        if not python.exists():
            return {"ok": False, "message": f"{python} is missing (see src\\vvbot\\UPSTREAM.md)."}
        env = launcher.child_env()
        env["PYTHONPATH"] = str(launcher.REPO / "src")
        try:
            await _in_pool(deps.spawn, [str(python), "-m", "vvbot"], launcher.REPO, env, timeout=15)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"Couldn't start the bot: {exc}"}
        return {"ok": True, "message": "Bot started; it connects to the hub in a few seconds."}
    raise HTTPException(status_code=404, detail="unknown action")


@router.get("/secrets")
async def secret_status() -> dict:
    return {name: bool(hub_secrets.get(name)) for name in services.SECRETS}


@router.post("/secrets/{name}")
async def set_secret(name: str, payload: dict = Body(default_factory=dict)) -> dict:
    if name not in services.SECRETS:
        raise HTTPException(status_code=404, detail="unknown secret")
    value = payload.get("value") if isinstance(payload, dict) else None
    problem = services.check_secret(name, value)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    hub_secrets.set(name, value.strip())
    log.info("secret %s updated from the control app", name)
    return {"ok": True, "name": name, "set": True}


@router.delete("/secrets/{name}")
async def delete_secret(name: str) -> dict:
    if name not in services.SECRETS:
        raise HTTPException(status_code=404, detail="unknown secret")
    hub_secrets.delete(name)
    log.info("secret %s removed from the control app", name)
    return {"ok": True, "name": name, "set": False}


# ---- chats ------------------------------------------------------------------------------------
def _chats(request: Request) -> Chats:
    return Chats(_hub(request).store, data_dir() / "history")


@router.get("/chats")
async def chats(request: Request, q: str = "") -> dict:
    c = _chats(request)
    items = await _in_pool(c.items)
    body = {"retention_days": 2, "items": items}
    if q.strip():
        body["matches"] = await _in_pool(c.search, q)
    return body


@router.get("/chats/{cid:path}/export")
async def export_chat(request: Request, cid: str, format: str = "md") -> dict:  # noqa: A002
    try:
        return await _in_pool(_chats(request).export, cid, "json" if format == "json" else "md")
    except NotFound:
        raise HTTPException(status_code=404, detail="no such chat") from None


@router.post("/chats/{cid:path}/save")
async def save_chat(request: Request, cid: str, payload: dict = Body(default_factory=dict)) -> dict:
    title = str((payload or {}).get("title") or "") if isinstance(payload, dict) else ""
    try:
        return await _in_pool(_chats(request).save, cid, title)
    except NotFound:
        raise HTTPException(status_code=404, detail="no such chat") from None


@router.get("/chats/{cid:path}")
async def get_chat(request: Request, cid: str) -> dict:
    try:
        return await _in_pool(_chats(request).get, cid)
    except NotFound:
        raise HTTPException(status_code=404, detail="no such chat") from None


# ---- approvals --------------------------------------------------------------------------------
@router.get("/approvals")
async def approvals(request: Request) -> dict:
    hub = _hub(request)
    rows = hub.store.approvals()
    return {"pending": [r for r in rows if r["status"] == "pending"],
            "recent": sorted(rows, key=lambda r: r["created"], reverse=True)[:50],
            "ui_connected": hub.bus.connected("ui")}


# ---- logs + reports ---------------------------------------------------------------------------
def _tail(path: Path, lines: int, q: str) -> list[str]:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - 512 * 1024))
        text = handle.read().decode("utf-8", errors="replace")
    rows = text.splitlines()
    if size > 512 * 1024:
        rows = rows[1:]  # first line is probably cut
    if q:
        rows = [r for r in rows if q.lower() in r.lower()]
    return rows[-lines:]


@router.get("/logs")
async def logs(name: str = "vvhub", lines: int = 200, q: str = "") -> dict:
    folder = data_dir() / "logs"
    names = sorted(p.stem for p in folder.glob("*.log")) if folder.exists() else []
    if not _NAME.match(name) or name not in names:
        raise HTTPException(status_code=404, detail="no such log")
    rows = await _in_pool(_tail, folder / f"{name}.log", max(1, min(lines, 2000)), q.strip())
    return {"name": name, "names": names, "lines": rows}


@router.get("/reports")
async def reports() -> dict:
    folder = data_dir() / "reports"
    items = []
    for path in sorted(folder.glob("*.html"), reverse=True) if folder.exists() else []:
        items.append({"name": path.name, "modified": path.stat().st_mtime, "size": path.stat().st_size})
    return {"items": items}


@router.post("/reports/now")
async def report_now(request: Request) -> dict:
    from ..scheduler import report_now as make

    try:
        report = await asyncio.wait_for(make(_hub(request)), 180)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Report failed: {exc}"}
    return {"ok": True, "message": f"{report.title}: {report.total} items.", "delivery": report.delivery}


@router.get("/reports/{name}")
async def report(name: str) -> dict:
    folder = data_dir() / "reports"
    path = (folder / name).resolve()
    if not _NAME.match(name) or not name.endswith(".html") or path.parent != folder.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="no such report")
    return {"name": name, "html": path.read_text(encoding="utf-8", errors="replace")}


# ---- microphone -----------------------------------------------------------------------------
async def _to_voicevibe(request: Request, type_: str, **fields: Any) -> dict:
    hub = _hub(request)
    if not hub.bus.connected("voicevibe"):
        raise HTTPException(status_code=503, detail="Voice Vibe isn't running (or isn't linked to the hub).")
    try:
        reply = await hub.bus.send_to("voicevibe", protocol.message(type_, **fields), timeout=10)
    except Exception as exc:  # noqa: BLE001 - NotConnected / timeout
        raise HTTPException(status_code=503, detail=f"Voice Vibe didn't answer: {exc}") from None
    if reply.get("type") == "error":
        raise HTTPException(status_code=409, detail=str(reply.get("message", "refused")))
    return reply


@router.get("/mics")
async def mics(request: Request) -> dict:
    reply = await _to_voicevibe(request, "list_mics")
    return {"devices": reply.get("devices", []), "current": reply.get("current", "")}


@router.post("/mics")
async def set_mic(request: Request, payload: dict = Body(default_factory=dict)) -> dict:
    device = str((payload or {}).get("device") or "").strip() if isinstance(payload, dict) else ""
    if not device or len(device) > 200:
        raise HTTPException(status_code=422, detail="pick a device")
    reply = await _to_voicevibe(request, "set_mic", device=device)
    return {"ok": True, "device": reply.get("device", device)}


# ---- settings + autostart ---------------------------------------------------------------------
@router.get("/settings")
async def get_settings(request: Request) -> dict:
    path = _deps(request).config_path
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    errors, warnings = validate(text)
    return {"path": str(path), "text": text, "errors": errors, "warnings": warnings}


@router.post("/settings/validate")
async def validate_settings(payload: dict = Body(default_factory=dict)) -> dict:
    text = str((payload or {}).get("text", "")) if isinstance(payload, dict) else ""
    errors, warnings = validate(text)
    return {"errors": errors, "warnings": warnings}


@router.put("/settings")
async def put_settings(request: Request, payload: dict = Body(default_factory=dict)) -> dict:
    text = (payload or {}).get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or len(text) > 256 * 1024:
        raise HTTPException(status_code=422, detail={"errors": ["no config text"], "warnings": []})
    errors, warnings = validate(text)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors, "warnings": warnings})
    backup = write(_deps(request).config_path, text)
    log.info("config.toml replaced from the control app (backup %s)", backup.name)
    return {"ok": True, "warnings": warnings, "backup": str(backup),
            "message": "Saved. Restart Voice Vibe to apply."}


@router.get("/autostart")
async def get_autostart(request: Request) -> dict:
    return {"enabled": launcher.autostart_enabled(reg=_deps(request).registry)}


@router.put("/autostart")
async def put_autostart(request: Request, payload: dict = Body(default_factory=dict)) -> dict:
    enabled = bool((payload or {}).get("enabled")) if isinstance(payload, dict) else False
    launcher.set_autostart(enabled, reg=_deps(request).registry)
    return {"enabled": launcher.autostart_enabled(reg=_deps(request).registry)}


def install(app: FastAPI, deps: UIDeps | None = None) -> None:
    """Add the control app to the hub's FastAPI app (server.create_app)."""
    app.state.ui = deps or UIDeps()
    app.include_router(static_router)
    app.include_router(router)
