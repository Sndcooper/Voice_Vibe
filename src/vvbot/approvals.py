"""Approval cards: hub `approval_request` -> Telegram card -> `approval_result`.

A card has Approve / Deny buttons; a strict "yes"/"no" (text or voice note)
also answers it (answers.py). Nothing else ever approves. A card past its
deadline is marked expired and can no longer be answered -- the hub has
already treated it as denied (rule 10, timeout = deny).

`answer` in the result carries what the user actually said, so the hub's
approvals (WS2) can double-check it with Laya and only ever downgrade.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from vvhub import protocol

from .hub_client import HubUnavailable

DEFAULT_TIMEOUT = 300.0
_CALLBACK = re.compile(r"^ap:([A-Za-z0-9_-]{1,40}):([yn])$")


@dataclass
class Pending:
    id: str
    request: dict
    action: str
    preview: str
    text: str
    chat_id: int
    message_id: int
    deadline: float


class ApprovalDesk:
    def __init__(self, messenger: Any, hub: Any, clock: Callable[[], float] = time.time,
                 default_timeout: float = DEFAULT_TIMEOUT) -> None:
        self.messenger = messenger
        self.hub = hub
        self.clock = clock
        self.default_timeout = default_timeout
        self.pending: dict[str, Pending] = {}

    async def open(self, msg: dict, chat_id: int) -> Pending:
        record = msg.get("approval") if isinstance(msg.get("approval"), dict) else msg
        approval_id = str((record.get("id") or msg["id"]) if record is not msg else msg["id"])
        action = str(record.get("action", "") or "")
        preview = str(record.get("preview", "") or action)
        timeout = float(msg.get("timeout") or record.get("timeout") or self.default_timeout)
        text = f"🔐 Approval needed\n\n{preview}\n\n(action: {action})" if action else f"🔐 Approval needed\n\n{preview}"
        buttons = [("✅ Approve", f"ap:{approval_id}:y"), ("❌ Deny", f"ap:{approval_id}:n")]
        message_id = await self.messenger.send_card(chat_id, text, buttons)
        pending = Pending(approval_id, msg, action, preview, text, chat_id, message_id, self.clock() + timeout)
        self.pending[approval_id] = pending
        return pending

    def by_message(self, message_id: int | None) -> Pending | None:
        return next((p for p in self.pending.values() if p.message_id == message_id), None)

    async def decide(self, approval_id: str, approved: bool, answer: str = "") -> str:
        pending = self.pending.get(approval_id)
        if pending is None:
            return "That request is no longer pending."
        if self.clock() > pending.deadline:
            await self._expire(pending)
            return "That request expired, so it was denied."
        del self.pending[approval_id]
        result = protocol.reply_to(pending.request, "approval_result", approved=bool(approved),
                                   decided_by="telegram", answer=answer or ("yes" if approved else "no"))
        try:
            await self.hub.send(result)
        except HubUnavailable:
            await self.messenger.edit_text(pending.chat_id, pending.message_id,
                                           f"{pending.text}\n\n⚠️ The hub is offline; nothing was approved.")
            return "The hub is offline; nothing was approved."
        verdict = "✅ Approved" if approved else "❌ Denied"
        await self.messenger.edit_text(pending.chat_id, pending.message_id, f"{pending.text}\n\n{verdict}")
        return "Approved." if approved else "Denied."

    async def on_callback(self, data: str) -> str:
        match = _CALLBACK.match(data or "")
        if not match:
            return "Unknown button."
        return await self.decide(match.group(1), match.group(2) == "y", answer="button")

    async def _expire(self, pending: Pending) -> None:
        self.pending.pop(pending.id, None)
        await self.messenger.edit_text(pending.chat_id, pending.message_id,
                                       f"{pending.text}\n\n⌛ Expired (treated as denied)")

    async def sweep(self) -> None:
        now = self.clock()
        for pending in [p for p in self.pending.values() if now > p.deadline]:
            await self._expire(pending)

    def describe(self) -> str:
        if not self.pending:
            return "No approvals waiting."
        lines = [f"• {p.preview}" for p in self.pending.values()]
        return "Waiting for you:\n" + "\n".join(lines)
