"""Shared data shapes (TASK.md §3). Every stream codes against these.

Plain dataclasses with `to_dict`/`from_dict`, so they cross the WebSocket and
SQLite as JSON without a schema library. Unknown keys are ignored on load, so
adding a field is not a breaking change; renaming or removing one is.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import Any

CATEGORIES = ("screen", "research", "notes", "social", "github", "code", "app", "chitchat")

# Rule 10: these always need approval, whatever Laya scores. Matched against a
# Plan's action name word by word ("linkedin_post" -> post), so a skill cannot
# dodge the gate by naming.
CRITICAL_WORDS = frozenset({
    "post", "publish", "push", "create_repo", "repo_create", "pr", "pull_request",
    "delete", "remove", "send", "message", "dm", "reply", "comment", "pay",
    "buy", "purchase", "merge",
})

APPROVAL_STATUSES = ("pending", "approved", "denied", "expired")


def is_critical(action: str) -> bool:
    """True if an action name contains a critical word (rule 10)."""
    name = action.lower().replace("-", "_").replace(" ", "_")
    if name in CRITICAL_WORDS:
        return True
    parts = name.split("_")
    joined = {"_".join(parts[i:i + 2]) for i in range(len(parts) - 1)}
    return bool(CRITICAL_WORDS & (set(parts) | joined))


class _Shape:
    @classmethod
    def from_dict(cls, data: dict | None):  # noqa: ANN206
        data = data or {}
        known = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)  # type: ignore[call-overload]


@dataclass
class Decision(_Shape):
    """What the smart router concluded about one request (§3.4)."""

    category: str = "chitchat"
    action: str = ""
    target: str = ""
    confidence: float = 0.0
    risk: float = 0.0
    critical: bool = False
    needs_approval: bool = False
    reason: str = ""
    laya_raw: dict = field(default_factory=dict)


@dataclass
class Plan(_Shape):
    """What a skill intends to do, before it does it (§3.6)."""

    skill: str
    action: str
    args: dict = field(default_factory=dict)
    preview: str = ""
    critical: bool = False

    def __post_init__(self) -> None:
        # A skill may under-report; it can never un-mark a critical action.
        self.critical = bool(self.critical or is_critical(self.action))


@dataclass
class Result(_Shape):
    ok: bool
    text: str = ""
    speak: bool = True
    data: dict = field(default_factory=dict)


@dataclass
class Approval(_Shape):
    """One approval request (§3.5)."""

    action: str
    preview: str = ""
    channel: str = "voice"
    status: str = "pending"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: float = field(default_factory=time.time)
    decided_by: str = ""


def context_bundle(**parts: Any) -> dict:
    """An empty-by-default context bundle (§3.3); pass the parts you have."""
    bundle: dict[str, Any] = {"pinned": False, "redacted": False}
    bundle.update({k: v for k, v in parts.items() if v is not None})
    return bundle
