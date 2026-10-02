"""`computer save this conversation`: keep the hub's copy forever too (rule 15).

Voice Vibe saves its own turn history locally and forwards the phrase here, so
the hub's decisions, approvals and jobs for the same days survive the purge.
"""

from __future__ import annotations

import time

from ..schemas import Plan, Result
from ..store import RETENTION_SECONDS, today_conversation
from .base import Skill


class ConversationSkill(Skill):
    name = "conversation"
    category = "chitchat"
    actions = {"save_conversation": "keep this conversation forever instead of 2 days"}
    phrases = {
        "save this conversation": "save_conversation",
        "save the conversation": "save_conversation",
        "save conversation": "save_conversation",
        "save this chat": "save_conversation",
        "save the chat": "save_conversation",
        "keep this conversation": "save_conversation",
    }

    async def run(self, plan: Plan, approval=None, dry_run: bool = False) -> Result:  # noqa: ANN001
        now = time.time()
        # Every day still inside the retention window is "this conversation".
        days = {today_conversation(now - offset)
                for offset in range(0, RETENTION_SECONDS + 1, 86400)}
        if not dry_run:
            for day in sorted(days):
                self.hub.store.save_conversation(day)
        return Result(ok=True, text="Conversation saved.", data={"saved": sorted(days)})


SKILL = ConversationSkill()
