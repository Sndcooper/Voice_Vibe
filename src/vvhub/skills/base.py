"""The skill contract (TASK.md §3.6).

A skill module in `vvhub/skills/` exposes `SKILL = MySkill()`. The hub finds it
by itself; there is no registry file to edit.
"""

from __future__ import annotations

from typing import Any

from ..schemas import Decision, Plan, Result


class Skill:
    name: str = ""
    category: str = "chitchat"
    # action -> one-line description; the smart router offers these to Laya.
    actions: dict[str, str] = {}
    # Actions that always need approval, on top of schemas.is_critical().
    critical_actions: set[str] = set()
    # Exact lowercase phrases this skill answers without Laya (after the
    # "computer" prefix). Keep this tiny; Laya does the real routing.
    phrases: dict[str, str] = {}

    def __init__(self) -> None:
        self.hub: Any = None  # set by the registry: .store, .bus, .skills

    def bind(self, hub: Any) -> None:
        self.hub = hub

    async def plan(self, decision: Decision, context: dict) -> Plan:
        return Plan(
            skill=self.name,
            action=decision.action,
            args={"target": decision.target},
            critical=decision.action in self.critical_actions,
        )

    async def run(self, plan: Plan, approval: Any = None, dry_run: bool = False) -> Result:
        raise NotImplementedError
