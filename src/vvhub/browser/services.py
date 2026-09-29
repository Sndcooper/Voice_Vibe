"""How WS3 code reaches other streams' services (llm, laya, approvals, store, bus).

Order: an explicit override (tests pass fakes) -> the attribute on the hub the
registry bound to the skill -> the module named in TASK.md §3.7. Anything
missing resolves to None, and callers degrade (rule 19) instead of crashing.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from typing import Any

log = logging.getLogger(__name__)

MODULES = {
    "llm": "vvhub.llm",
    "laya": "vvhub.laya_engine",
    "approvals": "vvhub.approvals",
    "store": "vvhub.store",
    "secrets": "vvhub.secrets",
}


class Services:
    def __init__(self, hub: Any = None, **overrides: Any) -> None:
        self.hub = hub
        self._overrides = overrides

    def get(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        if self.hub is not None:
            value = getattr(self.hub, name, None)
            if value is None and name == "laya":
                value = getattr(self.hub, "laya_engine", None)
            if value is not None:
                return value
        module = MODULES.get(name)
        if module is None:
            return None
        try:
            return importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 - another stream's module may not exist yet
            log.debug("service %s unavailable: %s", name, exc)
            return None


async def call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a sync or async service function. Sync ones (Laya is CPU-bound)
    run in a worker thread so the hub's event loop keeps serving."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    result = await asyncio.to_thread(fn, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def approved(approval: Any) -> bool:
    if approval is None:
        return False
    if isinstance(approval, dict):
        return approval.get("status") == "approved" or approval.get("approved") is True
    status = getattr(approval, "status", None)
    return status == "approved" or (status is None and getattr(approval, "approved", False) is True)


def channel_of(approval: Any) -> str:
    if isinstance(approval, dict):
        return str(approval.get("channel") or "")
    return str(getattr(approval, "channel", "") or "")


def field(obj: Any, key: str, default: Any = None) -> Any:
    """Read a key from a dataclass or a dict (Decision, context parts)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def is_llm_unavailable(exc: BaseException) -> bool:
    """WS2's `LLMUnavailable`, matched by name so we don't import vvhub.llm."""
    return any(cls.__name__ == "LLMUnavailable" for cls in type(exc).__mro__)
