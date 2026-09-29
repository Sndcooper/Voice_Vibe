"""The app skill: bring a window forward, list or change the microphone.

Built on what Voice Vibe already has: `winctl.top_level_windows` (the
Alt+Tab list) and `winctl.match_window` (the scoring "switch to X" uses)
for windows, and Voice Vibe's own executor for the focus itself, reached
with a `run_steps` message -- Windows lets the foreground-owning input path
do focus changes, and it keeps every input action in one process. Mics go
through `list_mics` / `set_mic` (TASK.md §3.2).

Stereo Mix and other loopbacks are never offered or set (rule 20): they
record the speakers, and on this laptop that means silence.

Nothing here is critical: switching windows and mics is the "small task"
the hub does as the user.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .. import protocol
from ..schemas import Plan, Result
from .base import Skill

log = logging.getLogger(__name__)

# Same list as voicevibe.audio._LOOPBACK_HINTS (not imported: audio pulls in
# sounddevice, which the hub does not need).
LOOPBACK_HINTS = ("stereo mix", "what u hear", "wave out", "output mix", "loopback",
                  "rec. playback", "pc speaker")


def is_loopback(name: str) -> bool:
    lowered = str(name).lower()
    return any(hint in lowered for hint in LOOPBACK_HINTS)


def _field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _live_windows() -> list[dict]:
    from voicevibe.winctl import top_level_windows

    return top_level_windows()


class AppSkill(Skill):
    name = "app"
    category = "app"
    actions = {
        "focus_window": "bring a window or app that is already open to the front",
        "list_mics": "say which microphones are available",
        "set_mic": "change the microphone Voice Vibe records from",
    }
    critical_actions: set[str] = set()

    def __init__(self, windows: Callable[[], list[dict]] | None = None) -> None:
        super().__init__()
        self._windows = windows or _live_windows

    # -------------------------------------------------------- targets
    def windows(self) -> list[dict]:
        try:
            return [w for w in self._windows() if w.get("title")]
        except Exception as exc:  # noqa: BLE001 - enumeration is best effort
            log.debug("window list failed: %s", exc)
            return []

    def target_options(self, decision: Any, context: dict) -> dict[str, str]:
        """For focus_window: open windows, title -> process, most recent first."""
        if _field(decision, "action") != "focus_window":
            return {}
        return {w["title"]: str(w.get("process_name") or "") for w in self.windows()}

    # ----------------------------------------------------------- plan
    async def plan(self, decision: Any, context: dict) -> Plan:
        action = _field(decision, "action", "") or ""
        target = str(_field(decision, "target", "") or "").strip()
        if action == "focus_window":
            window = self._find_window(target)
            if window is None:
                return Plan(skill=self.name, action=action, args={"target": target},
                            preview=f"Switch to {target or 'a window'}")
            return Plan(skill=self.name, action=action,
                        args={"hwnd": int(window["hwnd"]), "title": window["title"]},
                        preview=f"Switch to {window['title']}")
        if action == "set_mic":
            device, devices = await self._match_mic(target)
            return Plan(skill=self.name, action=action,
                        args={"target": target, "device": device, "devices": devices},
                        preview=f"Use the microphone {device or target}")
        return Plan(skill=self.name, action=action, args={}, preview=self.actions.get(action, action))

    def _find_window(self, target: str) -> dict | None:
        if not target:
            return None
        windows = self.windows()
        for window in windows:
            if window["title"] == target:
                return window
        from voicevibe.winctl import match_window

        return match_window(target, windows)

    async def _mics(self) -> dict:
        reply = await self.hub.bus.send_to("voicevibe", protocol.message("list_mics"))
        return {"devices": [str(d) for d in reply.get("devices") or []],
                "current": str(reply.get("current") or "")}

    async def _match_mic(self, spoken: str) -> tuple[str, list[str]]:
        if not spoken or not self._voicevibe_up():
            return "", []
        try:
            devices = (await self._mics())["devices"]
        except Exception as exc:  # noqa: BLE001
            log.debug("list_mics failed: %s", exc)
            return "", []
        from voicevibe.launcher import Launcher, _normalize

        wanted = _normalize(spoken)
        words = wanted.split()
        best, best_score = "", 0.0
        for device in devices:
            key = _normalize(device)
            s = 1.0 if key == wanted else Launcher._score(key, wanted, words)
            if s > best_score:
                best, best_score = device, s
        if best_score < 0.6 or is_loopback(best):
            return ("" if best_score < 0.6 else best), devices
        return best, devices

    # ------------------------------------------------------------ run
    def _voicevibe_up(self) -> bool:
        bus = getattr(self.hub, "bus", None)
        return bool(bus is not None and bus.connected("voicevibe"))

    async def run(self, plan: Plan, approval: Any = None, dry_run: bool = False) -> Result:
        if plan.action == "focus_window":
            return await self._focus(plan, dry_run)
        if plan.action == "list_mics":
            return await self._list_mics(dry_run)
        if plan.action == "set_mic":
            return await self._set_mic(plan, dry_run)
        return Result(ok=False, text="I can't do that with windows or microphones.")

    async def _focus(self, plan: Plan, dry_run: bool) -> Result:
        if "hwnd" not in plan.args:
            name = plan.args.get("target") or "that"
            return Result(ok=False, text=f"I can't see a window called {name}.")
        if dry_run:
            return Result(ok=True, text=plan.preview, speak=False)
        if not self._voicevibe_up():
            return Result(ok=False, text="Voice Vibe isn't connected, so I can't switch windows.")
        step = {"focus": {"hwnd": plan.args["hwnd"], "title": plan.args["title"]}}
        reply = await self.hub.bus.send_to("voicevibe", protocol.message(
            "run_steps", steps=[step], dry_run=False))
        if reply.get("ok") is False:
            return Result(ok=False, text=f"Windows wouldn't switch: {reply.get('error') or 'refused'}.")
        return Result(ok=True, text="", speak=False, data={"hwnd": plan.args["hwnd"]})

    async def _list_mics(self, dry_run: bool) -> Result:
        if dry_run:
            return Result(ok=True, text="Would list the microphones.", speak=False)
        if not self._voicevibe_up():
            return Result(ok=False, text="Voice Vibe isn't connected.")
        mics = await self._mics()
        usable = [d for d in mics["devices"] if not is_loopback(d)]
        if not usable:
            return Result(ok=True, text="I can't find a microphone.")
        now = f" Using {mics['current']}." if mics["current"] else ""
        return Result(ok=True, text="Microphones: " + "; ".join(usable) + "." + now,
                      data={"devices": usable, "current": mics["current"]})

    async def _set_mic(self, plan: Plan, dry_run: bool) -> Result:
        device = plan.args.get("device") or ""
        if device and is_loopback(device):
            return Result(ok=False, text=f"{device} records the speakers, not you; I won't use it.")
        if not device:
            spoken = plan.args.get("target") or "that"
            return Result(ok=False, text=f"I can't find a microphone called {spoken}.")
        if dry_run:
            return Result(ok=True, text=plan.preview, speak=False)
        if not self._voicevibe_up():
            return Result(ok=False, text="Voice Vibe isn't connected.")
        reply = await self.hub.bus.send_to("voicevibe", protocol.message("set_mic", device=device))
        if reply.get("type") == "error":
            return Result(ok=False, text=f"Couldn't switch: {reply.get('message', 'error')}.")
        return Result(ok=True, text=f"Using {device}.")


SKILL = AppSkill()
