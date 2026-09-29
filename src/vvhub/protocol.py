"""The Voice Vibe <-> hub WebSocket protocol (TASK.md §3.2).

Stdlib only: Voice Vibe imports this module too, and must not need the hub's
dependencies to do so.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

VERSION = 1

TYPES = frozenset({
    "hello", "welcome", "request", "reply", "confirm", "confirm_result",
    "approval_request", "approval_result", "run_steps", "steps_result",
    "get_context", "context", "list_mics", "set_mic", "mics", "ok",
    "transcribe", "text", "notify", "ping", "pong", "error",
})

ROLES = frozenset({"voicevibe", "bot", "ui"})

# Seconds a sender waits for the reply to each request type.
TIMEOUTS = {"request": 20.0, "confirm": 15.0, "approval_request": 300.0}
DEFAULT_TIMEOUT = 10.0

# WebSocket close codes.
CLOSE_UNAUTHORIZED = 4401
CLOSE_BAD_HELLO = 4400


class ProtocolError(ValueError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def message(type_: str, *, re: str | None = None, **fields: Any) -> dict:
    """Build a message. `re` marks it as the reply to message `re`."""
    if type_ not in TYPES:
        raise ProtocolError(f"unknown message type {type_!r}")
    msg: dict[str, Any] = {"id": new_id(), "type": type_}
    if re is not None:
        msg["re"] = re
    msg.update(fields)
    return msg


def reply_to(request: dict, type_: str, **fields: Any) -> dict:
    return message(type_, re=request.get("id"), **fields)


def encode(msg: dict) -> str:
    return json.dumps(msg, ensure_ascii=False)


def decode(raw: str | bytes) -> dict:
    """Parse and minimally validate one message."""
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"not JSON: {exc}") from exc
    if not isinstance(msg, dict):
        raise ProtocolError("message is not an object")
    if msg.get("type") not in TYPES:
        raise ProtocolError(f"unknown message type {msg.get('type')!r}")
    if not isinstance(msg.get("id"), str):
        raise ProtocolError("message has no id")
    return msg


def timeout_for(type_: str) -> float:
    return TIMEOUTS.get(type_, DEFAULT_TIMEOUT)
