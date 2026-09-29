"""The screen skill: what is on the user's screen, from Voice Vibe's bundle.

Voice Vibe builds the context (voicevibe/context.py: window, caret text,
pointer element, region crop + Windows OCR, privacy guard). This skill asks
for a deep one with `get_context {deep: true}` when it needs more than the
shallow bundle every request carries, and adds what only the hub has:
a Windows-MCP `Snapshot` of the region (CursorTouch/Windows-MCP, MIT, the
on-demand stdio client WS3 wrote for Zen: telemetry off, PowerShell/Registry/
FileSystem excluded) -- `use_dom` for browsers, so Zen pages are readable.

Actions here (T8): focus / unfocus (the pin lives in Voice Vibe; `get_context`
carries `pin: true|false`) and read (selection, else the region's OCR).
explain / summarize use the LLM on crops (T9).

Screen text is data (rule 11): it is spoken or summarised, never routed or
acted on. A redacted bundle (privacy guard) is never enriched or read.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from .. import protocol
from ..schemas import Plan, Result
from .base import Skill

log = logging.getLogger(__name__)

ToolCaller = Callable[[str, dict], Awaitable[str]]
MCP_TEXT = 6000
BROWSERS = frozenset({"edge", "zen", "chrome", "firefox", "brave", "opera", "vivaldi"})
PRIVATE = "That window is private, so I won't look at it."
OFFLINE = "Voice Vibe isn't connected, so I can't see the screen."


def _field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


async def fetch_context(hub: Any, deep: bool = False, pin: bool | None = None) -> dict | None:
    """The §3.3 bundle from Voice Vibe, or None if it isn't connected."""
    bus = getattr(hub, "bus", None)
    if bus is None or not bus.connected("voicevibe"):
        return None
    fields: dict[str, Any] = {"deep": bool(deep)}
    if pin is not None:
        fields["pin"] = bool(pin)
    reply = await bus.send_to("voicevibe", protocol.message("get_context", **fields))
    if isinstance(reply.get("context"), dict):
        return reply["context"]
    return {k: v for k, v in reply.items() if k not in ("id", "type", "re")}


def _windows_mcp() -> ToolCaller:
    from ..browser.drivers import WindowsMCP

    return WindowsMCP(timeout=30.0)


class ScreenSkill(Skill):
    name = "screen"
    category = "screen"
    actions = {
        "focus": "pin the screen region around the mouse cursor as what to look at",
        "unfocus": "stop pinning the screen region",
        "read": "read the selected or focused text on the screen out loud",
    }
    critical_actions: set[str] = set()
    MAX_SPOKEN = 600

    def __init__(self, mcp: ToolCaller | None = None) -> None:
        super().__init__()
        self._mcp = mcp

    @property
    def mcp(self) -> ToolCaller:
        if self._mcp is None:
            self._mcp = _windows_mcp()
        return self._mcp

    async def plan(self, decision: Any, context: dict) -> Plan:
        action = _field(decision, "action", "") or "read"
        previews = {"focus": "Focus on the area around your cursor", "unfocus": "Stop focusing",
                    "read": "Read what's on screen"}
        return Plan(skill=self.name, action=action, args={},
                    preview=previews.get(action, self.actions.get(action, action)))

    async def deep_context(self, pin: bool | None = None) -> dict | None:
        """Deep bundle from Voice Vibe + the Windows-MCP region snapshot."""
        bundle = await fetch_context(self.hub, deep=True, pin=pin)
        if not bundle or bundle.get("redacted"):
            return bundle
        region = bundle.get("region") or {}
        rect = region.get("rect")
        browser = (bundle.get("browser") or {}).get("name") in BROWSERS
        if rect:
            try:
                text = await self.mcp("Snapshot", {"region": list(rect), "use_vision": False,
                                                   "use_annotation": False, "use_dom": browser})
            except Exception as exc:  # noqa: BLE001 - optional component (rule 19)
                log.debug("Windows-MCP snapshot skipped: %s", exc)
                text = ""
            if text:
                if browser:
                    bundle.setdefault("browser", {})["dom_text"] = text[:MCP_TEXT]
                else:
                    region["ui_text"] = text[:MCP_TEXT]
                    bundle["region"] = region
        return bundle

    async def run(self, plan: Plan, approval: Any = None, dry_run: bool = False) -> Result:
        if dry_run:
            return Result(ok=True, text=plan.preview, speak=False)
        if plan.action in ("focus", "unfocus"):
            bundle = await fetch_context(self.hub, deep=False, pin=plan.action == "focus")
            if bundle is None:
                return Result(ok=False, text=OFFLINE)
            if plan.action == "focus":
                return Result(ok=True, text="Focused on the area around your cursor.")
            return Result(ok=True, text="Focus off.")
        if plan.action == "read":
            return await self._read()
        return Result(ok=False, text="I can't do that with the screen yet.")

    async def _read(self) -> Result:
        bundle = await fetch_context(self.hub, deep=True)
        if bundle is None:
            return Result(ok=False, text=OFFLINE)
        if bundle.get("redacted"):
            return Result(ok=False, text=PRIVATE)
        text = (bundle.get("selection") or bundle.get("caret_text")
                or (bundle.get("region") or {}).get("ocr_text") or "").strip()
        if not text:
            return Result(ok=False, text="I can't find any text there.")
        if len(text) > self.MAX_SPOKEN:
            text = text[: self.MAX_SPOKEN].rsplit(" ", 1)[0] + " …"
        return Result(ok=True, text=text)


SKILL = ScreenSkill()
