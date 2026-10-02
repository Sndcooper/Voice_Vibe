"""`computer ping hub`: proves the Voice Vibe <-> hub link end to end."""

from __future__ import annotations

from ..schemas import Plan, Result
from .base import Skill


class EchoSkill(Skill):
    name = "echo"
    category = "chitchat"
    actions = {"ping": "check that the hub is online"}
    phrases = {"ping hub": "ping", "ping the hub": "ping", "hub status": "ping"}

    async def run(self, plan: Plan, approval=None, dry_run: bool = False) -> Result:  # noqa: ANN001
        return Result(ok=True, text="Hub is online.")


SKILL = EchoSkill()
